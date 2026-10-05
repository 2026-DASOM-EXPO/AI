"""
기존 데이터셋(datasets/train|valid|test)을 정리하고 Worksite-Obj-Det 드론각도 타일을 합쳐
새 데이터셋 datasets/v4/{train,valid,test} 를 만든다. 기존 폴더는 건드리지 않는다
(3차 모델과 비교 평가할 수 있도록 보존).

정리 규칙:
1) 그레이스케일 PPE(ext_ryan, 영상 5개에서 뽑은 연속 프레임)
   - Roboflow 증강으로 프레임 하나당 최대 3장 복사본이 있다 -> 프레임당 1장만 사용
     (valid/test에 있던 비증강 원본을 우선, 없으면 train 복사본 중 첫 번째)
   - 같은 영상에서 프레임 번호 간격이 RYAN_FRAME_GAP 미만인 프레임은 버린다
     (연속 프레임은 화소 평균차 0.7/255 수준의 사실상 중복)
   - 영상 단위로 split 배정 (RYAN_VIDEO_SPLIT)
2) 컬러 PPE(ext_ppe)
   - 같은 원본에서 나온 복사본이 train과 valid/test에 동시에 있으면(누수) valid/test 쪽만 남긴다
   - valid/test 안에서는 원본당 1장만 남긴다 (train 쪽 증강 복사본은 유지)
3) 자체 촬영(person 단위)
   - person1, person2 -> train / person3 -> valid, test
   - person3의 미착용 시나리오(no_helmet, no_vest, no_shoe)는 영상 앞 40% valid, 뒤 60% test로
     시간순 분할해서 test에 자체 촬영 helmet_not_worn / vest_not_worn / shoe_not_worn 이 모두 들어가게 한다
4) Worksite-Obj-Det 드론각도 타일(scripts/prepare_worksite_tiles.py 결과) -> train에 추가
   - 단, MIDRANGE_CAMERAS 카메라의 타일은 train에서 빼고 test_midrange(중간거리 검증용)로 따로 둔다.
     타임랩스 카메라라 같은 카메라 프레임끼리는 배경이 같으므로 카메라 단위로 분리한다.
     헬멧/조끼 박스가 둘 다 적당히 있는 카메라를 골랐고, 이름이 비슷해 같은 현장일 수 있는
     TL2213 / TLA2213 은 train에 남겼다.
5) 공개 신발 데이터셋 발 크롭(scripts/prepare_shoe_crops.py 결과: Patras 전체 + boots-detection 서브샘플)
   -> train에만 추가 (스테이징 폴더가 없으면 건너뜀)

사용법:
    python scripts\\prepare_worksite_tiles.py     # (먼저 1회)
    python scripts\\prepare_shoe_crops.py         # (먼저 1회)
    python scripts\\rebuild_dataset_v4.py
"""

import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "datasets"
DST = ROOT / "datasets" / "v4"
WORKSITE_TILES = ROOT / "datasets" / "external" / "worksite_tiles"
SHOE_CROPS = ROOT / "datasets" / "external" / "shoe_crops"
SRC_SPLITS = ("train", "valid", "test")
SPLITS = SRC_SPLITS + ("test_midrange",)
NAMES = ["helmet_not_worn", "helmet_worn", "shoe_not_worn", "shoe_worn", "vest_not_worn", "vest_worn"]

MIDRANGE_CAMERAS = {"tla2119", "TLA2181VF", "TL2174"}

RYAN_FRAME_GAP = 4
RYAN_VIDEO_SPLIT = {
    "pelatihan-single-person-lengkap-semua-1": "train",
    "pelatihan-single-person-tidak-lengkap-semua-1": "train",
    "pelatihan-multi-person-lengkap-semua-1": "train",
    "pelatihan-multi-person-tidak-lengkap-semua-1": "valid",
    "pelatihan-multi-person-menggunakan-salah-satu-APD-1": "test",
}

OWN_GROUP_SPLIT = {
    "all_worn_person1": "train", "no_helmet_person1": "train", "no_shoe_person1": "train", "no_vest_person1": "train",
    "all_worn_person2": "train", "no_helmet_person2": "train", "no_shoe_person2": "train", "no_vest_person2": "train",
    "shoe_closeup_1": "train", "shoe_closeup_2": "train",
    "all_worn_person3": "valid", "shoe_closeup_3": "valid",
    "shoe_closeup_4": "test",
    # 시간순 분할 대상
    "no_helmet_person3": "time_split", "no_vest_person3": "time_split", "no_shoe_person3": "time_split",
}
TIME_SPLIT_VALID_RATIO = 0.4

RYAN_PATTERN = re.compile(r"^ext_ryan_(.+)_mp4-(\d+)_jpg\.rf\.")
OWN_PATTERN = re.compile(r"^(.+?)_(\d+)_jpg\.rf\.")
RF_SUFFIX = re.compile(r"\.rf\.[0-9a-f]+$")


def collect() -> list[tuple[str, Path, Path]]:
    """(원래 split, 이미지 경로, 라벨 경로) 목록."""
    entries = []
    for split in SRC_SPLITS:
        for img in sorted((SRC / split / "images").iterdir()):
            lbl = SRC / split / "labels" / (img.stem + ".txt")
            if lbl.exists():
                entries.append((split, img, lbl))
    return entries


def plan_ryan(entries) -> list[tuple[str, Path, Path]]:
    frames = defaultdict(dict)  # video -> frame_no -> (split, img, lbl)
    for split, img, lbl in entries:
        m = RYAN_PATTERN.match(img.name)
        if not m:
            continue
        video, frame_no = m.group(1), int(m.group(2))
        current = frames[video].get(frame_no)
        # 비증강(valid/test) 복사본 우선
        if current is None or (current[0] == "train" and split != "train"):
            frames[video][frame_no] = (split, img, lbl)

    out = []
    for video, by_frame in frames.items():
        last = None
        for frame_no in sorted(by_frame):
            if last is not None and frame_no - last < RYAN_FRAME_GAP:
                continue
            last = frame_no
            _, img, lbl = by_frame[frame_no]
            out.append((RYAN_VIDEO_SPLIT[video], img, lbl))
    return out


def plan_ppe(entries) -> list[tuple[str, Path, Path]]:
    groups = defaultdict(list)
    for split, img, lbl in entries:
        if img.name.startswith("ext_ppe_"):
            groups[RF_SUFFIX.sub("", img.stem)].append((split, img, lbl))

    out = []
    for copies in groups.values():
        splits = {s for s, _, _ in copies}
        if "test" in splits or "valid" in splits:
            target = "test" if "test" in splits else "valid"
            _, img, lbl = next(c for c in copies if c[0] == target)
            out.append((target, img, lbl))
        else:
            out.extend(copies)
    return out


def plan_own(entries) -> list[tuple[str, Path, Path]]:
    groups = defaultdict(list)
    for _, img, lbl in entries:
        if img.name.startswith("ext_"):
            continue
        m = OWN_PATTERN.match(img.name)
        groups[m.group(1)].append((int(m.group(2)), img, lbl))

    out = []
    for group, items in groups.items():
        rule = OWN_GROUP_SPLIT[group]
        if rule != "time_split":
            out.extend((rule, img, lbl) for _, img, lbl in items)
            continue
        frame_nos = sorted({n for n, _, _ in items})
        cut = frame_nos[int(len(frame_nos) * TIME_SPLIT_VALID_RATIO)]
        out.extend(("valid" if n < cut else "test", img, lbl) for n, img, lbl in items)
    return out


def plan_worksite() -> list[tuple[str, Path, Path]]:
    if not WORKSITE_TILES.is_dir():
        raise SystemExit(f"[오류] {WORKSITE_TILES} 가 없습니다. scripts\\prepare_worksite_tiles.py 를 먼저 실행하세요.")
    out = []
    for img in sorted((WORKSITE_TILES / "images").iterdir()):
        camera = img.name.removeprefix("ext_worksite_").split("_")[0]
        split = "test_midrange" if camera in MIDRANGE_CAMERAS else "train"
        out.append((split, img, WORKSITE_TILES / "labels" / (img.stem + ".txt")))
    return out


def plan_shoe_crops() -> list[tuple[str, Path, Path]]:
    if not SHOE_CROPS.is_dir():
        print(f"[알림] {SHOE_CROPS} 가 없어 신발 크롭은 건너뜁니다 (scripts\prepare_shoe_crops.py).")
        return []
    return [
        ("train", img, SHOE_CROPS / "labels" / (img.stem + ".txt"))
        for img in sorted((SHOE_CROPS / "images").iterdir())
    ]


def source_of(name: str) -> str:
    for prefix, src in (("ext_ryan", "grayscale"), ("ext_ppe", "color_ppe"), ("ext_worksite", "worksite"),
                        ("ext_shoe", "shoe_ext")):
        if name.startswith(prefix):
            return src
    return "own"


def main() -> None:
    entries = collect()
    plan = plan_own(entries) + plan_ryan(entries) + plan_ppe(entries) + plan_worksite() + plan_shoe_crops()

    if DST.exists():
        shutil.rmtree(DST)
    for split in SPLITS:
        (DST / split / "images").mkdir(parents=True)
        (DST / split / "labels").mkdir(parents=True)

    img_count = defaultdict(Counter)   # split -> class -> 이미지 수
    box_count = defaultdict(Counter)   # split -> class -> 박스 수
    src_count = defaultdict(Counter)   # split -> source -> 이미지 수
    own_count = defaultdict(Counter)   # split -> class -> 자체촬영 이미지 수
    for split, img, lbl in plan:
        shutil.copy2(img, DST / split / "images" / img.name)
        shutil.copy2(lbl, DST / split / "labels" / lbl.name)
        classes = [int(line.split()[0]) for line in lbl.read_text(encoding="utf-8").splitlines() if line.strip()]
        src = source_of(img.name)
        src_count[split][src] += 1
        for c in classes:
            box_count[split][NAMES[c]] += 1
        for c in set(classes):
            img_count[split][NAMES[c]] += 1
            if src == "own":
                own_count[split][NAMES[c]] += 1

    (ROOT / "datasets" / "data_v4.yaml").write_text(
        "train: v4/train/images\nval: v4/valid/images\ntest: v4/test/images\n"
        "test_midrange: v4/test_midrange/images\n\n"
        f"nc: {len(NAMES)}\nnames: {NAMES}\n",
        encoding="utf-8",
    )

    print(f"생성 완료: {DST}")
    print("\n[출처별 이미지 수]")
    for split in SPLITS:
        print(f"  {split:5}: {sum(src_count[split].values()):5}장  {dict(src_count[split])}")
    print("\n[클래스별 이미지 수 / 박스 수]  (괄호: 자체 촬영 이미지 수)")
    print(f"  {'class':16}" + "".join(f"{s:>22}" for s in SPLITS))
    for name in NAMES:
        row = "".join(
            f"{f'{img_count[s][name]} / {box_count[s][name]} ({own_count[s][name]})':>22}" for s in SPLITS
        )
        print(f"  {name:16}{row}")


if __name__ == "__main__":
    main()
