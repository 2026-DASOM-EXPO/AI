"""
안전장비 착용 인식 웹캠 실시간 객체 인식 스크립트

사용 예시:
    python scripts\\detect_webcam.py                  # 커스텀 안전장비 모델로 인식
    python scripts\\detect_webcam.py --camera 1        # 카메라 인덱스 지정
    python scripts\\detect_webcam.py --conf 0.5        # confidence threshold 지정
    python scripts\\detect_webcam.py --model models\\yolov8n.pt --imgsz 640  # COCO 사전학습 모델 사용
    python scripts\\detect_webcam.py --model runs\\train\\safety_equipment-3\\weights\\best.pt --imgsz 640  # 이전(3차) 모델

종료: 웹캠 창이 활성화된 상태에서 'q' 키
"""

import argparse
from pathlib import Path

import cv2
from ultralytics import YOLO

SCRIPT_DIR = Path(__file__).resolve().parent
# YOLO11s / imgsz 1280 (v4b). 근거리 성능은 3차(v8n/640)와 동등, 드론 중간거리(test_midrange)는 대폭 개선 — README 참고
DEFAULT_MODEL_PATH = SCRIPT_DIR.parent / "runs" / "train" / "safety_equipment_v4b_11s_1280" / "weights" / "best.pt"
DEFAULT_IMGSZ = 1280  # 학습 해상도와 맞춘다 (640으로 넣으면 원거리 헬멧이 다시 뭉개짐)


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
    parser.add_argument(
        "--imgsz",
        type=int,
        default=DEFAULT_IMGSZ,
        help=f"추론 입력 크기 (기본값: {DEFAULT_IMGSZ}, 3차 모델이나 yolov8n.pt 를 쓸 때는 640 권장)",
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
                imgsz=args.imgsz,
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
