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
    parser.add_argument(
        "--person-model",
        type=str,
        default=None,
        help="지정 시(예: models\\yolov8n.pt) 사람 단위로 안전모/벨트 착용을 판정해 OK/WARNING 표시",
    )
    return parser.parse_args()


# 사람 단위 판정: 사람 박스 안(상체 영역)에 든 장비 박스를 연결하고, 최근 N프레임 다수결로 깜빡임을 줄인다.
HISTORY = 8


def center_in(box, person):
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return person[0] <= cx <= person[2] and person[1] <= cy <= person[3]


def judge_people(persons, gear, names):
    """persons: [(x1,y1,x2,y2)], gear: [(name, box, conf)] -> [{'helmet': bool|None, 'belt': bool|None}]"""
    out = []
    for p in persons:
        state = {}
        for item in ("helmet", "belt"):
            cands = [(c, n) for n, b, c in gear if n.startswith(item) and center_in(b, p)]
            state[item] = max(cands)[1].endswith("_worn") if cands else None
        out.append(state)
    return out


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
    person_model = YOLO(args.person_model) if args.person_model else None
    history = {}

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

            if person_model is not None:
                r = results[0]
                gear = [(r.names[int(c)], b.tolist(), float(cf))
                        for c, b, cf in zip(r.boxes.cls, r.boxes.xyxy, r.boxes.conf)]
                pr = person_model.track(frame, classes=[0], conf=args.conf, persist=True, verbose=False)[0]
                if pr.boxes.id is not None:
                    for pid, pb, st in zip(pr.boxes.id.int().tolist(), pr.boxes.xyxy.tolist(),
                                           judge_people(pr.boxes.xyxy.tolist(), gear, r.names)):
                        h = history.setdefault(pid, {"helmet": [], "belt": []})
                        for k in h:
                            if st[k] is not None:
                                h[k] = (h[k] + [st[k]])[-HISTORY:]
                        # 벨트/안전모가 한 번도 확인 안 됐거나 다수결이 미착용이면 경고 (안전 측 판정)
                        ok = all(h[k] and sum(h[k]) * 2 > len(h[k]) for k in h)
                        color = (0, 200, 0) if ok else (0, 0, 255)
                        x1, y1, x2, y2 = map(int, pb)
                        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 3)
                        label = "OK" if ok else "WARNING"
                        cv2.putText(annotated, f"#{pid} {label}", (x1, max(y1 - 8, 20)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

            cv2.imshow(window_title, annotated)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
