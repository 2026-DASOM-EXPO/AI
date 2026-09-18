"""
안전장비 착용 인식 웹캠 실시간 객체 인식 스크립트

사용 예시:
    python scripts\\detect_webcam.py                  # 커스텀 안전장비 모델로 인식
    python scripts\\detect_webcam.py --camera 1        # 카메라 인덱스 지정
    python scripts\\detect_webcam.py --conf 0.5        # confidence threshold 지정
    python scripts\\detect_webcam.py --model models\\yolov8n.pt  # COCO 사전학습 모델 사용

종료: 웹캠 창이 활성화된 상태에서 'q' 키
"""

import argparse
from pathlib import Path

import cv2
from ultralytics import YOLO

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_PATH = SCRIPT_DIR.parent / "runs" / "train" / "safety_equipment-3" / "weights" / "best.pt"


def parse_args():
    parser = argparse.ArgumentParser(description="안전장비 착용 웹캠 실시간 객체 인식")
    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="웹캠 장치 인덱스 (기본값: 0)",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.4,
        help="confidence threshold (기본값: 0.4)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=str(DEFAULT_MODEL_PATH),
        help=f"모델 가중치 경로 (기본값: {DEFAULT_MODEL_PATH})",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    model = YOLO(args.model)

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise RuntimeError(
            f"웹캠(index={args.camera})을 열 수 없습니다. "
            "다른 프로그램이 카메라를 사용 중이거나 --camera 인덱스가 잘못되었을 수 있습니다."
        )

    window_title = f"Webcam - {Path(args.model).stem}"

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("프레임을 읽지 못했습니다. 웹캠 연결을 확인하세요.")
                break

            results = model.predict(
                source=frame,
                conf=args.conf,
                verbose=False,
            )

            annotated = results[0].plot()

            cv2.imshow(window_title, annotated)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
