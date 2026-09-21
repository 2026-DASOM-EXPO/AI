"""
외부 Roboflow PPE 데이터셋(datasets/external/*)을 우리 6클래스 체계로 리매핑하여
datasets/train, datasets/valid, datasets/test 에 합쳐 넣는다.

우리 클래스 순서 (datasets/data.yaml 기준):
    0 helmet_not_worn
    1 helmet_worn
    2 shoe_not_worn
    3 shoe_worn
    4 vest_not_worn
    5 vest_worn

외부 데이터셋 중 우리 체계에 없는 클래스(gloves, wearpack 등)는 라벨에서 제거하고,
리매핑 후 라벨이 하나도 안 남는 이미지는 통째로 제외한다(라벨 노이즈 방지).

사용법:
    python scripts\\merge_external_datasets.py
"""

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
EXTERNAL_DIR = ROOT / "datasets" / "external"
TARGET_DIR = ROOT / "datasets"

# 외부 데이터셋별: (하위 폴더명, 파일명 접두사, {외부 class idx: 우리 class idx})
SOURCES = [
    {
        "dir": EXTERNAL_DIR / "ryan_helmet_boots",
        "prefix": "ext_ryan",
        # 원본: ['boots', 'helmet', 'no boots', 'no helmet', 'no wearpack', 'wearpack']
        "class_map": {0: 3, 1: 1, 2: 2, 3: 0},
    },
    {
        "dir": EXTERNAL_DIR / "ppe_helmet_vest",
        "prefix": "ext_ppe",
        # 원본: ['Gloves', 'Helmet', 'No-Helmet', 'No-gloves', 'No-vest', 'Vest']
        "class_map": {1: 1, 2: 0, 4: 4, 5: 5},
    },
    {
        "dir": EXTERNAL_DIR / "safe_helmet_vest",
        "prefix": "ext_safe",
        # 원본: ['NO_vest_detected', 'No_glasses_detected', 'No_helmet_detected',
        #        'Safety_glasses_detected', 'Safety_helmet_detected', 'Safety_vest_detected']
        # 안경 클래스(1, 3)는 우리 체계에 없어 제거. (Public Domain, 9,507장)
        "class_map": {0: 4, 2: 0, 4: 1, 5: 5},
    },
]

SPLIT_MAP = {"train": "train", "valid": "valid", "test": "test"}
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def remap_label_file(src_label: Path, class_map: dict) -> list[str]:
    lines_out = []
    for line in src_label.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        cls = int(parts[0])
        if cls not in class_map:
            continue
        new_cls = class_map[cls]
        lines_out.append(" ".join([str(new_cls)] + parts[1:]))
    return lines_out


def main() -> None:
    totals = {"train": 0, "valid": 0, "test": 0}
    skipped_empty = 0

    for source in SOURCES:
        src_dir: Path = source["dir"]
        prefix = source["prefix"]
        class_map = source["class_map"]

        if not src_dir.is_dir():
            print(f"[건너뜀] {src_dir} 폴더가 없습니다.")
            continue

        for split_src, split_dst in SPLIT_MAP.items():
            img_dir = src_dir / split_src / "images"
            label_dir = src_dir / split_src / "labels"
            if not img_dir.is_dir():
                continue

            out_img_dir = TARGET_DIR / split_dst / "images"
            out_label_dir = TARGET_DIR / split_dst / "labels"
            out_img_dir.mkdir(parents=True, exist_ok=True)
            out_label_dir.mkdir(parents=True, exist_ok=True)

            for img_path in sorted(img_dir.iterdir()):
                if img_path.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                label_path = label_dir / (img_path.stem + ".txt")
                if not label_path.exists():
                    continue

                remapped = remap_label_file(label_path, class_map)
                if not remapped:
                    skipped_empty += 1
                    continue

                new_stem = f"{prefix}_{img_path.stem}"
                out_img_path = out_img_dir / (new_stem + img_path.suffix)
                out_label_path = out_label_dir / (new_stem + ".txt")

                shutil.copy2(img_path, out_img_path)
                out_label_path.write_text("\n".join(remapped) + "\n", encoding="utf-8")

                totals[split_dst] += 1

    print("병합 완료:")
    for split, count in totals.items():
        print(f"  {split}: +{count} 장")
    print(f"  (리매핑 후 라벨이 없어 제외된 이미지: {skipped_empty}장)")


if __name__ == "__main__":
    main()
