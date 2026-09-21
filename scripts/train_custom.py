"""
YOLOv8n 커스텀 파인튜닝 스크립트 (산업 안전장비 착용 여부 인식)

동작 순서:
    1. datasets/data.yaml에 정의된 train/val/test 경로가 실제로 존재하는지 검증
    2. GPU(CUDA) 사용 가능 여부를 확인해 device/batch를 자동 설정
    3. models/yolov8n.pt(COCO 사전학습 가중치)를 기반으로 100 epoch 파인튜닝

사용 예시:
    python scripts\\train_custom.py

GPU가 없는 경우 (Google Colab에서 학습하는 방법):
    1. https://colab.research.google.com 에서 새 노트북 생성
    2. 메뉴 [런타임 > 런타임 유형 변경 > 하드웨어 가속기]에서 GPU 선택
    3. Google Drive 마운트 (드라이브에 EXPO 프로젝트를 업로드해둔 경우)
         from google.colab import drive
         drive.mount('/content/drive')
    4. 패키지 설치
         !pip install ultralytics
    5. datasets/ 폴더(train/valid/test 이미지+라벨, data.yaml)와
       models/yolov8n.pt를 Colab 환경(또는 마운트된 드라이브)에 준비
    6. 이 스크립트를 그대로 실행하거나, 노트북 셀에서 직접 실행
         from ultralytics import YOLO
         model = YOLO("yolov8n.pt")
         model.train(data="data.yaml", epochs=100, imgsz=640, batch=-1, device=0)
    7. 학습 완료 후 runs/train/safety_equipment/weights/best.pt 를 다운로드하여
       로컬 EXPO/runs/ 아래로 옮기거나 detect_webcam.py --model 인자로 사용
"""

import argparse
import sys
from pathlib import Path

import torch
import yaml
from ultralytics import YOLO

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_YAML = SCRIPT_DIR.parent / "datasets" / "data.yaml"
BASE_MODEL = SCRIPT_DIR.parent / "models" / "yolov8n.pt"

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def validate_dataset_paths(data_yaml_path: Path) -> None:
    """data.yaml에 적힌 train/val/test 경로가 실제 폴더로 존재하고 이미지가 있는지 검증한다."""
    if not data_yaml_path.exists():
        sys.exit(f"[오류] data.yaml을 찾을 수 없습니다: {data_yaml_path}")

    with open(data_yaml_path, "r", encoding="utf-8") as f:
        data_cfg = yaml.safe_load(f)

    base_dir = data_yaml_path.parent
    problems = []

    for split in ("train", "val", "test"):
        rel_path = data_cfg.get(split)
        if rel_path is None:
            if split == "test":
                continue  # test 경로는 선택 항목
            problems.append(f"  - '{split}' 키가 data.yaml에 없습니다.")
            continue

        resolved = (base_dir / rel_path).resolve()
        if not resolved.is_dir():
            problems.append(f"  - {split}: {resolved} 폴더가 존재하지 않습니다.")
            continue

        images = [p for p in resolved.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS]
        if not images:
            problems.append(f"  - {split}: {resolved} 폴더에 이미지 파일이 없습니다.")
        else:
            print(f"[확인] {split}: {resolved} ({len(images)}장)")

    if problems:
        print("\n[오류] data.yaml 경로 검증 실패:")
        for problem in problems:
            print(problem)
        sys.exit(1)

    print("[확인] data.yaml 경로 검증을 통과했습니다.\n")


def resolve_device_and_batch() -> tuple[str | int, int]:
    """GPU 사용 가능 여부에 따라 device와 batch size를 자동으로 정한다."""
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        print(f"[GPU 감지] {gpu_name} ({vram_gb:.1f} GB VRAM) -> GPU로 학습합니다.")
        print("[배치 크기] GPU 메모리 사용량에 맞춰 자동 산정 (Ultralytics AutoBatch, batch=-1)\n")
        return 0, -1

    if torch.backends.mps.is_available():
        print("[MPS 감지] Apple GPU(mps)로 학습합니다. 통합 메모리 부담을 줄이기 위해 batch=8 사용\n")
        return "mps", 8

    print("[GPU 미감지] CUDA를 사용할 수 없어 CPU로 학습합니다. (속도가 매우 느릴 수 있습니다)")
    print("[배치 크기] CPU 환경 기본값 batch=16 사용")
    print("Tip: GPU가 없다면 이 파일 상단 docstring의 Google Colab 안내를 참고하세요.\n")
    return "cpu", 16


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA_YAML), help="data.yaml 경로 (안전모+벨트: datasets/data_ppe_v2.yaml)")
    ap.add_argument("--name", default="safety_equipment", help="runs/train 하위 결과 폴더명")
    ap.add_argument("--epochs", type=int, default=100)
    args = ap.parse_args()
    data_yaml = Path(args.data).resolve()
    validate_dataset_paths(data_yaml)

    if not BASE_MODEL.exists():
        sys.exit(f"[오류] 사전학습 가중치를 찾을 수 없습니다: {BASE_MODEL}")

    device, batch = resolve_device_and_batch()

    model = YOLO(str(BASE_MODEL))
    model.train(
        data=str(data_yaml),
        epochs=args.epochs,
        imgsz=640,
        batch=batch,
        device=device,
        project=str(SCRIPT_DIR.parent / "runs" / "train"),
        name=args.name,
    )


if __name__ == "__main__":
    main()
