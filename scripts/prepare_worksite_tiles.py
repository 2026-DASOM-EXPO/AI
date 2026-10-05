"""
Worksite-Obj-Det(Roboflow Universe, timelapselab, v1, CC BY 4.0) 4K 이미지에서
'고각(위에서 내려다보는) 카메라' 프레임만 골라 1280x1280 타일로 잘라
우리 6클래스 체계 라벨로 변환해 스테이징 폴더에 저장한다.

실제 train 병합은 scripts/rebuild_dataset_v4.py 가 이 스테이징 폴더를 읽어서 한다.

판단 기준:
- 시점: 'Aerial platforms' 클래스는 고소작업대(장비)라 시점과 무관하다. 고정형 타임랩스
  카메라 20대를 파일명 접두사로 묶어 육안으로 분류했고, 지상/측면 시점인
  TL2073, TL1928 두 대를 제외했다.
- 타일: 4K 원본을 통째로 1280으로 줄이면 헬멧이 ~12px가 되므로, 원본 해상도로
  1280 타일을 잘라 헬멧 ~36px를 유지한다(중거리 학습용).
- 라벨 누락 대응: 헬멧 라벨이 없는 사람 중 10~15%는 실제로 헬멧을 쓰고 있다.
  타일 안의 모든 사람(중심 기준)에게 헬멧 박스가 매칭되는 '깨끗한 타일'만 쓴다.
- 클래스 매핑: Helmets -> helmet_worn, Orange-yellow protective jackets -> vest_worn.
  나머지(Person, Face, Cars, Trucks, excavator, Aerial platforms, plates)는 제거.
  미착용 라벨이 없으므로 helmet_not_worn / vest_not_worn 은 만들지 않는다.

사용법:
    python scripts\\prepare_worksite_tiles.py
"""

import shutil
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "datasets" / "external" / "worksite_obj_det"
OUT_DIR = ROOT / "datasets" / "external" / "worksite_tiles"

EXCLUDED_CAMERAS = {"TL2073", "TL1928"}

SRC_HELMET, SRC_VEST, SRC_PERSON = 3, 4, 5
CLASS_MAP = {SRC_HELMET: 1, SRC_VEST: 5}  # -> helmet_worn, vest_worn

TILE = 1280
MIN_VISIBLE = 0.5  # 타일 경계에 걸린 박스는 면적 50% 이상 보일 때만 유지


def tile_origins(size: int) -> list[int]:
    """size 길이를 TILE 크기로 덮는 시작점 목록 (마지막 타일은 끝에 맞춘다)."""
    if size <= TILE:
        return [0]
    starts = list(range(0, size - TILE, TILE))
    starts.append(size - TILE)
    return starts


def read_boxes(label_path: Path, W: int, H: int) -> list[tuple[int, float, float, float, float]]:
    """YOLO 라벨을 픽셀 좌표 (cls, x1, y1, x2, y2)로 읽는다. 폴리곤 줄은 무시."""
    boxes = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        p = line.split()
        if len(p) != 5:
            continue
        c, x, y, w, h = int(p[0]), *map(float, p[1:])
        boxes.append((c, (x - w / 2) * W, (y - h / 2) * H, (x + w / 2) * W, (y + h / 2) * H))
    return boxes


def has_helmet(person, helmets) -> bool:
    """헬멧 박스 중심이 사람 박스의 가로 범위 안 + 상반신 위쪽에 있으면 매칭."""
    _, px1, py1, px2, py2 = person
    ph = py2 - py1
    for _, hx1, hy1, hx2, hy2 in helmets:
        hx, hy = (hx1 + hx2) / 2, (hy1 + hy2) / 2
        if px1 <= hx <= px2 and py1 - 0.1 * ph <= hy <= py1 + 0.5 * ph:
            return True
    return False


def main() -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    (OUT_DIR / "images").mkdir(parents=True)
    (OUT_DIR / "labels").mkdir(parents=True)

    stats = Counter()
    for label_path in sorted(SRC_DIR.glob("*/labels/*.txt")):
        camera = label_path.name.split("_")[0]
        if camera in EXCLUDED_CAMERAS:
            continue
        images = list(label_path.parent.parent.joinpath("images").glob(label_path.stem + ".*"))
        if not images:
            continue

        with Image.open(images[0]) as im:
            W, H = im.size
            boxes = read_boxes(label_path, W, H)
            targets = [b for b in boxes if b[0] in CLASS_MAP]
            if not targets:
                continue
            stats["source_images"] += 1
            helmets = [b for b in boxes if b[0] == SRC_HELMET]
            persons = [b for b in boxes if b[0] == SRC_PERSON]

            for ty in tile_origins(H):
                for tx in tile_origins(W):
                    tx2, ty2 = tx + TILE, ty + TILE
                    lines = []
                    for c, x1, y1, x2, y2 in targets:
                        cx1, cy1, cx2, cy2 = max(x1, tx), max(y1, ty), min(x2, tx2), min(y2, ty2)
                        if cx2 <= cx1 or cy2 <= cy1:
                            continue
                        if (cx2 - cx1) * (cy2 - cy1) < MIN_VISIBLE * (x2 - x1) * (y2 - y1):
                            continue
                        lines.append(
                            f"{CLASS_MAP[c]} {((cx1 + cx2) / 2 - tx) / TILE:.6f} {((cy1 + cy2) / 2 - ty) / TILE:.6f} "
                            f"{(cx2 - cx1) / TILE:.6f} {(cy2 - cy1) / TILE:.6f}"
                        )
                    if not lines:
                        continue

                    tile_persons = [
                        p for p in persons if tx <= (p[1] + p[3]) / 2 < tx2 and ty <= (p[2] + p[4]) / 2 < ty2
                    ]
                    if any(not has_helmet(p, helmets) for p in tile_persons):
                        stats["tiles_rejected_unlabeled_person"] += 1
                        continue

                    stem = f"ext_worksite_{label_path.stem}_t{tx}_{ty}"
                    im.crop((tx, ty, tx2, ty2)).convert("RGB").save(OUT_DIR / "images" / f"{stem}.jpg", quality=95)
                    (OUT_DIR / "labels" / f"{stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
                    stats["tiles"] += 1
                    for line in lines:
                        stats[f"box_cls{line.split()[0]}"] += 1
                    stats["tiles_with_helmet"] += any(l.startswith("1 ") for l in lines)
                    stats["tiles_with_vest"] += any(l.startswith("5 ") for l in lines)

    print(f"원본 이미지(고각, 헬멧/조끼 라벨 있음): {stats['source_images']}장")
    print(f"저장한 타일: {stats['tiles']}장  (라벨 누락 의심으로 제외한 타일: {stats['tiles_rejected_unlabeled_person']}장)")
    print(f"  helmet_worn: 타일 {stats['tiles_with_helmet']}장 / 박스 {stats['box_cls1']}개")
    print(f"  vest_worn  : 타일 {stats['tiles_with_vest']}장 / 박스 {stats['box_cls5']}개")
    print(f"출력: {OUT_DIR}")


if __name__ == "__main__":
    main()
