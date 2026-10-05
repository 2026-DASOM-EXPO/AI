"""
공개 신발 데이터셋(Patras 전체 + boots-detection 서브샘플)을 '발 크롭'으로 잘라
우리 6클래스 라벨(shoe_not_worn=2, shoe_worn=3)로 변환해 스테이징 폴더에 저장한다.
조사/필터링 근거는 runs/shoe_survey/README.md, 규칙은 scripts/survey_shoe_datasets.py 와 같다.

실제 train 병합은 scripts/rebuild_dataset_v4.py 가 이 스테이징 폴더를 읽어서 한다.

필터링 (survey_shoe_datasets.py 와 동일):
1) Roboflow 증강 복사본은 원본당 1장(valid/test 비증강본 우선), aHash 동일 이미지 1장
2) 신발 박스 외접 영역을 위 1.0x / 좌우 0.5x(+박스높이) 넓혀 자른 '발 크롭'만 사용
   (이 데이터셋들엔 헬멧/조끼 라벨이 없으므로 3차 모델이 크롭에서 헬멧/조끼를 conf>=0.5로 잡으면 제외)
3) Patras: 화면에 녹색 박스가 구워진 프레임 제외

boots-detection 서브샘플 기준 ("어두운 신발 = 안전화" 편향 억제):
- not_safety_shoe 가 들어 있는 크롭은 전부 사용
- shoe_worn 만 있는 크롭은 '어두운 신발이 하나도 없는'(갈색/노랑/유색 안전화) 크롭만 고른다.
  Patras 의 안전화가 대부분 검은색이라 Patras 만으로도 어두운 worn/not_worn 비율이 조금 오르므로,
  어두운 안전화를 더 넣지 않고 '안전화 = 검은색만은 아니다'를 보여주는 크롭만 추가한다.
- 그 크롭도 train 전체 shoe_worn/shoe_not_worn 박스 비율이 병합 전 값의 MAX_RATIO_GROWTH 배를
  넘지 않는 데까지만 넣는다.

사용법:
    python scripts\\prepare_shoe_crops.py      # 그 다음 python scripts\\rebuild_dataset_v4.py
"""

import random
import re
import shutil
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import yaml
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "datasets" / "external" / "shoes"
OUT_DIR = ROOT / "datasets" / "external" / "shoe_crops"
V4_TRAIN_LABELS = ROOT / "datasets" / "v4" / "train" / "labels"
CHECK_MODEL = ROOT / "runs" / "train" / "safety_equipment-3" / "weights" / "best.pt"

NOT_WORN, WORN = 2, 3
HELMET_VEST = {0, 1, 4, 5}
MAP = {
    "patras": {"safe_boots": WORN, "not_safety": NOT_WORN},
    "boots_detection": {"safety_shoe": WORN, "Safety-shoes": WORN, "not_safety_shoe": NOT_WORN},
}
MAX_RATIO_GROWTH = 1.05
RF = re.compile(r"\.rf\.[0-9a-f]+$")


def ahash(img) -> bytes:
    g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (16, 16), interpolation=cv2.INTER_AREA)
    return (g > g.mean()).tobytes()


def is_dark(crop) -> bool:
    """박스 중앙 60% 영역의 HSV 중앙값 기준. 푸른 색조 CCTV의 어두운 신발도 포함."""
    h, w = crop.shape[:2]
    c = crop[int(h * .2):int(h * .8) + 1, int(w * .2):int(w * .8) + 1]
    hsv = cv2.cvtColor(c, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    v, s = np.median(hsv[:, 2]), np.median(hsv[:, 1])
    return bool(v < 60 or (v < 90 and s < 80))


def burned_green(img) -> bool:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = (hsv[..., 0] > 45) & (hsv[..., 0] < 75) & (hsv[..., 1] > 120) & (hsv[..., 2] > 120)
    return m.mean() > 0.0005


def read_boxes(lbl: Path, W: int, H: int) -> list[tuple[int, float, float, float, float]]:
    out = []
    for line in lbl.read_text(encoding="utf-8").splitlines() if lbl.exists() else []:
        r = line.split()
        if len(r) != 5:
            continue
        x, y, w, h = map(float, r[1:])
        out.append((int(r[0]), (x - w / 2) * W, (y - h / 2) * H, (x + w / 2) * W, (y + h / 2) * H))
    return out


def baseline() -> Counter:
    """병합 전 v4 train(외부 신발 크롭 제외)의 신발 박스 수와 어두운 신발 박스 수."""
    st = Counter()
    for lbl in V4_TRAIN_LABELS.glob("*.txt"):
        if lbl.name.startswith("ext_shoe_"):
            continue
        rows = [l.split() for l in lbl.read_text(encoding="utf-8").splitlines() if l.strip()]
        shoes = [r for r in rows if int(r[0]) in (NOT_WORN, WORN)]
        if not shoes:
            continue
        img_path = next(lbl.parent.parent.joinpath("images").glob(lbl.stem + ".*"))
        img = cv2.imread(str(img_path))
        H, W = img.shape[:2]
        for r in shoes:
            c = int(r[0])
            x, y, w, h = map(float, r[1:])
            sub = img[int((y - h / 2) * H):int((y + h / 2) * H), int((x - w / 2) * W):int((x + w / 2) * W)]
            st[c] += 1
            if sub.size and is_dark(sub):
                st[f"dark{c}"] += 1
    return st


def candidate_crops(name: str, model: YOLO, stats: Counter) -> list[dict]:
    names = yaml.safe_load((SRC / name / "data.yaml").read_text(encoding="utf-8"))["names"]
    cmap = MAP[name]
    seen_group, seen_hash, out = set(), set(), []
    for split in ("valid", "test", "train"):  # 비증강(valid/test) 복사본 우선
        for p in sorted((SRC / name / split / "images").glob("*")):
            group = RF.sub("", p.stem)
            if group in seen_group:
                continue
            seen_group.add(group)
            img = cv2.imread(str(p))
            h_ = ahash(img)
            if h_ in seen_hash:
                continue
            seen_hash.add(h_)
            H, W = img.shape[:2]
            shoes = [(cmap[names[c]], *b) for c, *b in read_boxes(p.parent.parent / "labels" / (p.stem + ".txt"), W, H)
                     if names[c] in cmap]
            if not shoes:
                continue
            if name == "patras" and burned_green(img):
                stats[f"{name}_drop_burned_box"] += 1
                continue
            x1, y1 = min(b[1] for b in shoes), min(b[2] for b in shoes)
            x2, y2 = max(b[3] for b in shoes), max(b[4] for b in shoes)
            bh = float(np.median([b[4] - b[2] for b in shoes]))
            cx1, cy1 = int(max(0, x1 - 0.5 * (x2 - x1) - bh)), int(max(0, y1 - bh))
            cx2, cy2 = int(min(W, x2 + 0.5 * (x2 - x1) + bh)), int(min(H, y2 + 0.3 * bh))
            crop = img[cy1:cy2, cx1:cx2]
            pred = model.predict(crop, imgsz=640, conf=0.5, verbose=False)[0]
            if any(int(c) in HELMET_VEST for c in pred.boxes.cls.tolist()):
                stats[f"{name}_drop_helmet_vest_visible"] += 1
                continue
            cw, ch = cx2 - cx1, cy2 - cy1
            labels, n, dark = [], Counter(), Counter()
            for c, bx1, by1, bx2, by2 in shoes:
                labels.append(
                    f"{c} {((bx1 + bx2) / 2 - cx1) / cw:.6f} {((by1 + by2) / 2 - cy1) / ch:.6f} "
                    f"{(bx2 - bx1) / cw:.6f} {(by2 - by1) / ch:.6f}"
                )
                n[c] += 1
                sub = img[int(by1):int(by2), int(bx1):int(bx2)]
                if sub.size and is_dark(sub):
                    dark[c] += 1
            out.append({"stem": f"ext_shoe_{name}_{group}", "crop": crop, "labels": labels, "n": n, "dark": dark})
    return out


def main() -> None:
    model = YOLO(str(CHECK_MODEL))
    stats = Counter()
    base = baseline()
    ratio_all = base[WORN] / base[NOT_WORN]
    ratio_dark = base[f"dark{WORN}"] / base[f"dark{NOT_WORN}"]

    chosen = candidate_crops("patras", model, stats)
    boots = candidate_crops("boots_detection", model, stats)
    chosen += [c for c in boots if c["n"][NOT_WORN]]
    worn_only = [c for c in boots if not c["n"][NOT_WORN] and not c["dark"][WORN]]
    random.Random(0).shuffle(worn_only)

    def totals(items):
        t = Counter(base)
        for c in items:
            t[WORN] += c["n"][WORN]
            t[NOT_WORN] += c["n"][NOT_WORN]
            t[f"dark{WORN}"] += c["dark"][WORN]
            t[f"dark{NOT_WORN}"] += c["dark"][NOT_WORN]
        return t

    for c in worn_only:
        t = totals(chosen + [c])
        if t[WORN] / t[NOT_WORN] > ratio_all * MAX_RATIO_GROWTH:
            break
        chosen.append(c)

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    (OUT_DIR / "images").mkdir(parents=True)
    (OUT_DIR / "labels").mkdir(parents=True)
    for c in chosen:
        cv2.imwrite(str(OUT_DIR / "images" / f"{c['stem']}.jpg"), c["crop"], [cv2.IMWRITE_JPEG_QUALITY, 95])
        (OUT_DIR / "labels" / f"{c['stem']}.txt").write_text("\n".join(c["labels"]) + "\n", encoding="utf-8")

    after = totals(chosen)
    by_src = Counter(c["stem"].split("_")[2] for c in chosen)
    added = Counter()
    for c in chosen:
        for k in (WORN, NOT_WORN):
            added[k] += c["n"][k]
            added[f"dark{k}"] += c["dark"][k]
    print(f"후보 크롭: patras {sum(1 for c in chosen if 'patras' in c['stem'])}장 (전부 사용), "
          f"boots-detection {len(boots)}장 (not_safety_shoe 포함 {sum(1 for c in boots if c['n'][NOT_WORN])}장, "
          f"어두운 신발 없는 shoe_worn 전용 {len(worn_only)}장)")
    print(f"제외: {dict(stats)}")
    print(f"저장한 크롭: {len(chosen)}장  {dict(by_src)}")
    print(f"  추가 박스: shoe_worn {added[WORN]} (어두운 {added[f'dark{WORN}']}), "
          f"shoe_not_worn {added[NOT_WORN]} (어두운 {added[f'dark{NOT_WORN}']})")
    print(f"  train worn/not_worn 박스 비율: {ratio_all:.2f} -> {after[WORN] / after[NOT_WORN]:.2f}")
    print(f"  train 어두운 worn/not_worn 비율: {ratio_dark:.2f} -> {after[f'dark{WORN}'] / after[f'dark{NOT_WORN}']:.2f}")
    print(f"출력: {OUT_DIR}")


if __name__ == "__main__":
    main()
