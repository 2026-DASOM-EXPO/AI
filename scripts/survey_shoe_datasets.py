"""
신발 데이터셋 필터링 시뮬레이션 (실제 병합은 하지 않음, 통계만):
1) 중복 제거: Roboflow 증강 복사본(.rf. 접두 동일) -> 원본당 1장, 그 다음 aHash 동일 이미지 1장
2) 클래스 매핑: 안전화 -> shoe_worn(3), 일반신발/맨발 -> shoe_not_worn(2), 나머지 제거
3) '발 크롭': 신발 박스들의 외접 영역을 위로 1.0x, 좌우 0.5x 넓혀서 자른다 (헬멧/조끼가 라벨 없이 배경으로 들어가지 않게)
   -> 현재 배포 모델(3차)로 크롭에서 helmet/vest 계열이 conf>=0.5로 잡히면 '라벨 누락 의심'으로 제외 (Worksite 깨끗한 타일 규칙과 같은 취지)
4) 화면에 녹색 박스가 구워진 프레임(Patras) 제외
5) 크롭 안 신발 박스 짧은 변 < 12px 제외

입력: datasets/external/shoes/{boots_detection,patras,darshanas,no_shoes_workers} (Roboflow YOLOv11 export)
사용법:
    python scripts\survey_shoe_datasets.py
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np
import yaml
from ultralytics import YOLO


def ahash(img):
    g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (16, 16), interpolation=cv2.INTER_AREA)
    return (g > g.mean()).tobytes()


def color_bucket(crop):
    h, w = crop.shape[:2]
    c = crop[int(h * .2):int(h * .8) + 1, int(w * .2):int(w * .8) + 1]
    hsv = cv2.cvtColor(c, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    v, s, hue = np.median(hsv[:, 2]), np.median(hsv[:, 1]), np.median(hsv[:, 0])
    if v < 60 or (v < 90 and s < 80):  # Patras 같은 푸른 색조 CCTV의 어두운 신발도 dark로
        return "black/dark"
    if s < 40:
        return "white/gray" if v > 150 else "gray/neutral"
    if hue < 10 or hue >= 160:
        return "red/pink"
    if hue < 25:
        return "brown/orange"
    if hue < 35:
        return "yellow"
    if hue < 85:
        return "green"
    return "blue/purple"


ROOT = Path(r"C:\EXPO\datasets\external\shoes")
MODEL = YOLO(r"C:\EXPO\runs\train\safety_equipment-3\weights\best.pt")
RF = re.compile(r"\.rf\.[0-9a-f]+$")

MAP = {
    "boots_detection": {"safety_shoe": 3, "Safety-shoes": 3, "not_safety_shoe": 2},
    "patras": {"safe_boots": 3, "not_safety": 2},
    "darshanas": {"safety-shoes": 3, "casual shoes": 2, "skets": 2, "flip flop": 2, "slippers": 2, "SANDEL": 2, "heels": 2},
    "no_shoes_workers": {"no_shoes": 2},
}
NAMES = {2: "shoe_not_worn", 3: "shoe_worn"}
HV = {0, 1, 4, 5}  # helmet_not_worn, helmet_worn, vest_not_worn, vest_worn


def read(lbl, W, H):
    out = []
    for l in lbl.read_text().splitlines() if lbl.exists() else []:
        r = l.split()
        if len(r) == 5:
            x, y, w, h = map(float, r[1:])
        elif len(r) >= 7 and len(r) % 2 == 1:
            xs, ys = list(map(float, r[1::2])), list(map(float, r[2::2]))
            x, y, w, h = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, max(xs) - min(xs), max(ys) - min(ys)
        else:
            continue
        out.append((int(r[0]), (x - w / 2) * W, (y - h / 2) * H, (x + w / 2) * W, (y + h / 2) * H))
    return out


def burned_green(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = (hsv[..., 0] > 45) & (hsv[..., 0] < 75) & (hsv[..., 1] > 120) & (hsv[..., 2] > 120)
    return m.mean() > 0.0005


report = {}
for ds, cmap in MAP.items():
    names = yaml.safe_load((ROOT / ds / "data.yaml").read_text(encoding="utf-8"))["names"]
    st = Counter()
    boxes, colors, img_with = Counter(), defaultdict(Counter), Counter()
    seen_group, seen_hash = set(), set()
    for split in ("valid", "test", "train"):  # 비증강(valid/test) 복사본 우선
        for p in sorted((ROOT / ds / split / "images").glob("*")):
            st["0_images"] += 1
            g = RF.sub("", p.stem)
            if g in seen_group:
                st["1_drop_aug_copy"] += 1
                continue
            seen_group.add(g)
            img = cv2.imread(str(p))
            h_ = ahash(img)
            if h_ in seen_hash:
                st["2_drop_same_hash"] += 1
                continue
            seen_hash.add(h_)
            H, W = img.shape[:2]
            shoes = [(cmap[names[c]], *b) for c, *b in read(p.parent.parent / "labels" / (p.stem + ".txt"), W, H)
                     if names[c] in cmap]
            if not shoes:
                st["3_drop_no_shoe_label"] += 1
                continue
            if ds == "patras" and burned_green(img):
                st["4_drop_burned_box"] += 1
                continue
            x1 = min(b[1] for b in shoes); y1 = min(b[2] for b in shoes)
            x2 = max(b[3] for b in shoes); y2 = max(b[4] for b in shoes)
            bh = np.median([b[4] - b[2] for b in shoes]); bw = x2 - x1
            cx1, cy1 = int(max(0, x1 - 0.5 * bw - bh)), int(max(0, y1 - 1.0 * bh))
            cx2, cy2 = int(min(W, x2 + 0.5 * bw + bh)), int(min(H, y2 + 0.3 * bh))
            crop = img[cy1:cy2, cx1:cx2]
            r = MODEL.predict(crop, imgsz=640, conf=0.5, verbose=False)[0]
            if any(int(c) in HV for c in r.boxes.cls.tolist()):
                st["5_drop_helmet_vest_visible"] += 1
                continue
            kept = [b for b in shoes if min(b[3] - b[1], b[4] - b[2]) >= 12]
            if not kept:
                st["6_drop_tiny"] += 1
                continue
            st["7_kept_crops"] += 1
            for k in {b[0] for b in kept}:
                img_with[NAMES[k]] += 1
            for k, bx1, by1, bx2, by2 in kept:
                boxes[NAMES[k]] += 1
                sub = img[int(by1):int(by2), int(bx1):int(bx2)]
                if sub.size:
                    colors[NAMES[k]][color_bucket(sub)] += 1
    report[ds] = {"funnel": dict(sorted(st.items())), "images_with": dict(img_with), "boxes": dict(boxes),
                  "colors": {k: dict(v.most_common()) for k, v in colors.items()}}
    print(ds, json.dumps(report[ds], ensure_ascii=False), flush=True)
