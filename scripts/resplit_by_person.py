"""
train/valid/test를 프레임 단위가 아닌 '영상(사람) 단위'로 재구성하는 일회성 스크립트.

기존 데이터셋은 같은 영상에서 뽑은 프레임들이 train/valid/test에 랜덤으로 섞여 있어서
(예: all_worn_person1_002는 train, all_worn_person1_006은 valid) 검증 점수가
실제 일반화 성능보다 훨씬 높게 나오는 데이터 누수(leakage) 문제가 있었다.

이 스크립트는 파일명의 접두사(예: all_worn_person1, shoe_closeup_3)를 '영상 단위 그룹'으로
보고, 그룹 전체를 통째로 train/valid/test 중 한 곳에만 배정한다. person3는 train에서
완전히 제외하여 valid/test가 모델이 한 번도 보지 못한 사람으로 평가되도록 한다.

사용 예시:
    python scripts\\resplit_by_person.py            # 실제 이동 수행
    python scripts\\resplit_by_person.py --dry-run  # 이동 없이 계획만 출력
"""

import argparse
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATASET_DIR = SCRIPT_DIR.parent / "datasets"
SPLITS = ("train", "valid", "test")

GROUP_PATTERN = re.compile(r"^(.+?)_(\d+)_jpg\.rf\.")

# 그룹(영상 단위) -> 목표 split
GROUP_TO_SPLIT = {
    # person1, person2는 4가지 시나리오 전부 train
    "all_worn_person1": "train",
    "no_helmet_person1": "train",
    "no_shoe_person1": "train",
    "no_vest_person1": "train",
    "all_worn_person2": "train",
    "no_helmet_person2": "train",
    "no_shoe_person2": "train",
    "no_vest_person2": "train",
    "shoe_closeup_1": "train",
    "shoe_closeup_2": "train",
    # person3는 train에서 완전히 제외 (미확인 인물로 valid/test에만 사용)
    "all_worn_person3": "valid",
    "no_vest_person3": "valid",
    "shoe_closeup_3": "valid",
    "no_helmet_person3": "test",
    "no_shoe_person3": "test",
    "shoe_closeup_4": "test",
}


def group_of(filename: str) -> str:
    m = GROUP_PATTERN.match(filename)
    if not m:
        raise ValueError(f"파일명에서 그룹을 추출할 수 없습니다: {filename}")
    return m.group(1)


def collect_files() -> list[tuple[Path, Path, str]]:
    """(image_path, label_path, group) 목록을 모든 split 폴더에서 수집한다."""
    entries = []
    for split in SPLITS:
        images_dir = DATASET_DIR / split / "images"
        labels_dir = DATASET_DIR / split / "labels"
        for image_path in images_dir.iterdir():
            if image_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            label_path = labels_dir / (image_path.stem + ".txt")
            if not label_path.exists():
                raise FileNotFoundError(f"라벨 파일이 없습니다: {label_path}")
            group = group_of(image_path.name)
            entries.append((image_path, label_path, group))
    return entries


def main():
    parser = argparse.ArgumentParser(description="train/valid/test를 영상(사람) 단위로 재구성")
    parser.add_argument("--dry-run", action="store_true", help="실제로 이동하지 않고 계획만 출력")
    args = parser.parse_args()

    entries = collect_files()
    print(f"[확인] 총 {len(entries)}개 이미지/라벨 쌍을 찾았습니다.\n")

    unknown_groups = {group for _, _, group in entries} - set(GROUP_TO_SPLIT)
    if unknown_groups:
        sys.exit(f"[오류] GROUP_TO_SPLIT에 매핑되지 않은 그룹이 있습니다: {sorted(unknown_groups)}")

    plan = defaultdict(list)
    for image_path, label_path, group in entries:
        target_split = GROUP_TO_SPLIT[group]
        plan[target_split].append((image_path, label_path, group))

    for split in SPLITS:
        by_group = defaultdict(int)
        for _, _, group in plan[split]:
            by_group[group] += 1
        total = sum(by_group.values())
        print(f"[계획] {split}: 총 {total}장")
        for group, count in sorted(by_group.items()):
            print(f"    - {group}: {count}장")
        print()

    if args.dry_run:
        print("[dry-run] 실제 파일 이동은 수행하지 않았습니다.")
        return

    moved = 0
    for split in SPLITS:
        for image_path, label_path, group in plan[split]:
            target_images_dir = DATASET_DIR / split / "images"
            target_labels_dir = DATASET_DIR / split / "labels"
            target_image_path = target_images_dir / image_path.name
            target_label_path = target_labels_dir / label_path.name

            if image_path != target_image_path:
                shutil.move(str(image_path), str(target_image_path))
                moved += 1
            if label_path != target_label_path:
                shutil.move(str(label_path), str(target_label_path))

    print(f"[완료] {moved}개 이미지(+라벨)를 재배치했습니다.")


if __name__ == "__main__":
    main()
