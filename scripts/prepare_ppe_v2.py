"""
안전모 + 안전벨트 4클래스 데이터셋(datasets/ppe_v2) 생성 스크립트

클래스: 0 helmet_not_worn, 1 helmet_worn, 2 belt_not_worn, 3 belt_worn

1) 기존 6클래스 데이터(datasets/train|valid|test)에서 helmet 클래스만 유지 (신발/조끼 라벨 제거)
2) 안전벨트(하네스) 외부 데이터셋을 --source 로 추가 (Roboflow YOLOv8 포맷, train/valid/test 하위 구조)

사용 예시:
    python scripts\\prepare_ppe_v2.py \\
        --source datasets\\external\\harness1:hn1:0=3,1=2 \\
        --source datasets\\external\\harness2:hn2:1=3,0=2
    --source 형식: <폴더>:<파일명 접두사>:<외부idx>=<우리idx>,...   (우리 idx: 2=belt_not_worn, 3=belt_worn,
                   1=helmet_worn, 0=helmet_not_worn 도 매핑 가능)

Tip: 벨트 데이터의 클래스명은 각 데이터셋의 data.yaml 'names' 를 보고 매핑하세요.
"""

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "datasets"
OUT = DATASETS / "ppe_v2"
SPLITS = ("train", "valid", "test")
IMG_EXT = (".jpg", ".jpeg", ".png")

# 기존 6클래스 -> 4클래스 (helmet만 유지)
BASE_MAP = {0: 0, 1: 1}


def remap(label: Path, cmap: dict) -> list[str]:
    out = []
    for line in label.read_text(encoding="utf-8").splitlines():
        p = line.split()
        if p and int(p[0]) in cmap:
            out.append(" ".join([str(cmap[int(p[0])])] + p[1:]))
    return out


def copy_split(src_root: Path, prefix: str, cmap: dict, split: str) -> int:
    img_dir, lbl_dir = src_root / split / "images", src_root / split / "labels"
    if not img_dir.is_dir():
        return 0
    n = 0
    for img in img_dir.iterdir():
        if img.suffix.lower() not in IMG_EXT:
            continue
        lbl = lbl_dir / f"{img.stem}.txt"
        lines = remap(lbl, cmap) if lbl.exists() else []
        if not lines:  # 라벨 노이즈 방지: 남는 라벨 없으면 제외
            continue
        name = f"{prefix}_{img.name}"
        (OUT / split / "images").mkdir(parents=True, exist_ok=True)
        (OUT / split / "labels").mkdir(parents=True, exist_ok=True)
        shutil.copy2(img, OUT / split / "images" / name)
        (OUT / split / "labels" / f"{prefix}_{img.stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        n += 1
    return n


def parse_source(spec: str):
    folder, prefix, mapping = spec.rsplit(":", 2)
    cmap = {int(a): int(b) for a, b in (kv.split("=") for kv in mapping.split(","))}
    return Path(folder), prefix, cmap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="append", default=[], help="벨트 외부 데이터셋 (위 docstring 참고)")
    ap.add_argument("--no-base", action="store_true", help="기존 helmet 데이터 제외")
    args = ap.parse_args()

    if OUT.exists():
        shutil.rmtree(OUT)

    jobs = []
    if not args.no_base:
        jobs.append((DATASETS, "base", BASE_MAP))
    for s in args.source:
        folder, prefix, cmap = parse_source(s)
        jobs.append((folder if folder.is_absolute() else ROOT / folder, prefix, cmap))

    for src, prefix, cmap in jobs:
        counts = {sp: copy_split(src, prefix, cmap, sp) for sp in SPLITS}
        print(f"[{prefix}] {counts}")

    belt = sum(
        1 for sp in SPLITS if (OUT / sp / "labels").is_dir()
        for f in (OUT / sp / "labels").glob("*.txt")
        for l in f.read_text().splitlines() if l.split()[0] in ("2", "3")
    )
    print(f"\n완료: {OUT}  (벨트 라벨 {belt}개)")
    if belt == 0:
        print("[경고] 벨트 라벨이 없습니다. --source 로 벨트 데이터셋을 추가하세요.")


if __name__ == "__main__":
    main()
