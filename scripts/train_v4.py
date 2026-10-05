"""
4차 학습: YOLO11s + imgsz=1280, datasets/data_v4.yaml (scripts/rebuild_dataset_v4.py 결과) 사용.

3차(safety_equipment-3, YOLOv8n/640) 대비 바뀐 점:
    - 베이스 모델 YOLOv8n -> YOLO11s (COCO 사전학습)
    - 입력 해상도 640 -> 1280 (원거리 작은 객체용)
    - 데이터: 그레이스케일 영상 프레임 솎아내기 + 영상/사람 단위 재분할 + Worksite 드론각도 타일 추가

중간거리 재검증(test_midrange)용으로 Worksite 3개 카메라를 train에서 뺀 뒤 다시 학습할 때는
--imgsz / --name 으로 해상도별 실행을 구분한다.

사용 예시:
    python scripts\\train_v4.py
    python scripts\\train_v4.py --imgsz 640 --name safety_equipment_v4b_11s_640
"""

import argparse
from pathlib import Path

from ultralytics import YOLO

from train_custom import resolve_device_and_batch, validate_dataset_paths

ROOT = Path(__file__).resolve().parent.parent
DATA_YAML = ROOT / "datasets" / "data_v4.yaml"
BASE_MODEL = ROOT / "models" / "yolo11s.pt"  # 없으면 ultralytics가 자동 다운로드

# imgsz=1280에서 AutoBatch(batch=-1)가 batch=1로 잘못 산정해서 직접 측정한 값을 쓴다.
# RTX 4060 Ti 8GB 실측: batch=8은 VRAM 초과(공유메모리로 넘어가 3배 느려짐), batch=6은 6.3GB.
# 640에서는 이미지당 메모리가 1/4이라 24까지 들어가지만 여유를 두고 16을 쓴다.
GPU_BATCH = {1280: 6, 640: 16}


def parse_args():
    parser = argparse.ArgumentParser(description="4차 학습 (YOLO11s, data_v4.yaml)")
    parser.add_argument("--imgsz", type=int, default=1280, choices=sorted(GPU_BATCH))
    parser.add_argument("--name", default="safety_equipment_v4_11s_1280", help="runs/train 아래 결과 폴더 이름")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validate_dataset_paths(DATA_YAML)
    device, batch = resolve_device_and_batch()
    if device != "cpu":
        batch = GPU_BATCH[args.imgsz]

    model = YOLO(str(BASE_MODEL) if BASE_MODEL.exists() else "yolo11s.pt")
    model.train(
        data=str(DATA_YAML),
        epochs=100,
        patience=30,
        imgsz=args.imgsz,
        batch=batch,
        device=device,
        project=str(ROOT / "runs" / "train"),
        name=args.name,
    )


if __name__ == "__main__":
    main()
