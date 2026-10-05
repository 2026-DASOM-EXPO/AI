"""
2단계 안전장비 인식: (1) COCO 사전학습 YOLO로 사람 탐지 -> (2) 사람 박스를 여유 있게 크롭 ->
(3) 크롭마다 PPE 모델 적용 -> 원본 좌표로 되돌린 뒤 클래스별 NMS로 합친다.

원본 프레임을 통째로 PPE 모델에 넣으면 작은 사람의 헬멧/신발이 입력 축소 과정에서 몇 픽셀로
뭉개지는데, 사람 영역만 잘라서 넣으면 원본 해상도의 화소를 그대로 쓸 수 있다.

사용 예시:
    # 실시간/파일 추론 (화면 표시, 'q'로 종료)
    python scripts\\detect_two_stage.py --source 0
    python scripts\\detect_two_stage.py --source rtsp://127.0.0.1:8554/a8mini
    python scripts\\detect_two_stage.py --source some_video.mp4

    # 평가: 같은 test set에서 '원본 그대로(1단계)' vs '사람 크롭(2단계)' mAP 비교
    python scripts\\detect_two_stage.py --eval datasets\\data_v4.yaml --split test
"""

import argparse
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import torch
import torchvision
import yaml
from ultralytics import YOLO
from ultralytics.utils.metrics import ap_per_class

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PPE_MODEL = ROOT / "runs" / "train" / "safety_equipment_v4_11s_1280" / "weights" / "best.pt"
DEFAULT_PERSON_MODEL = ROOT / "models" / "yolo11s.pt"
COCO_PERSON = 0
IOU_THRESHOLDS = np.linspace(0.5, 0.95, 10)


def parse_args():
    parser = argparse.ArgumentParser(description="사람 탐지 -> 크롭 -> PPE 인식 2단계 파이프라인")
    parser.add_argument("--source", default="0", help="웹캠 인덱스, 동영상/이미지 경로, RTSP 주소")
    parser.add_argument("--ppe-model", default=str(DEFAULT_PPE_MODEL))
    parser.add_argument("--person-model", default=str(DEFAULT_PERSON_MODEL), help="COCO 사전학습 모델 (person=0)")
    parser.add_argument("--person-imgsz", type=int, default=1280)
    parser.add_argument("--person-conf", type=float, default=0.25)
    parser.add_argument("--crop-imgsz", type=int, default=640, help="크롭을 PPE 모델에 넣을 때 입력 크기")
    parser.add_argument("--pad-x", type=float, default=0.15, help="사람 박스 좌우 패딩 (박스 너비 대비)")
    parser.add_argument("--pad-y", type=float, default=0.10, help="사람 박스 위아래 패딩 (박스 높이 대비)")
    parser.add_argument("--conf", type=float, default=0.4, help="PPE 표시용 confidence (평가 시에는 0.001 사용)")
    parser.add_argument("--direct-imgsz", type=int, default=1280, help="평가 시 '원본 그대로' 방식의 입력 크기")
    parser.add_argument("--device", default=None, help="예: 0, cpu (기본: 자동)")
    parser.add_argument("--eval", metavar="DATA_YAML", help="지정하면 평가 모드로 동작")
    parser.add_argument("--split", default="test")
    return parser.parse_args()


class TwoStageDetector:
    def __init__(self, ppe_model, person_model, person_imgsz, person_conf, crop_imgsz, pad_x, pad_y, device=None):
        self.ppe = YOLO(ppe_model)
        self.person = YOLO(person_model)
        self.person_imgsz = person_imgsz
        self.person_conf = person_conf
        self.crop_imgsz = crop_imgsz
        self.pad_x = pad_x
        self.pad_y = pad_y
        self.device = device

    def detect_persons(self, frame: np.ndarray) -> np.ndarray:
        r = self.person.predict(
            frame, imgsz=self.person_imgsz, conf=self.person_conf, classes=[COCO_PERSON], device=self.device, verbose=False
        )[0]
        return r.boxes.xyxy.cpu().numpy()

    def crop_regions(self, frame: np.ndarray, persons: np.ndarray) -> list[tuple[int, int, int, int]]:
        H, W = frame.shape[:2]
        regions = []
        for x1, y1, x2, y2 in persons:
            px, py = (x2 - x1) * self.pad_x, (y2 - y1) * self.pad_y
            regions.append(
                (int(max(0, x1 - px)), int(max(0, y1 - py)), int(min(W, x2 + px)), int(min(H, y2 + py)))
            )
        return regions

    def __call__(self, frame: np.ndarray, conf: float):
        """반환: (PPE 박스 xyxy, conf, cls, 사람 크롭 영역 목록) — 모두 원본 프레임 좌표."""
        regions = self.crop_regions(frame, self.detect_persons(frame))
        if not regions:
            return np.zeros((0, 4)), np.zeros(0), np.zeros(0, dtype=int), regions

        crops = [frame[y1:y2, x1:x2] for x1, y1, x2, y2 in regions]
        results = self.ppe.predict(crops, imgsz=self.crop_imgsz, conf=conf, device=self.device, verbose=False)

        boxes, confs, classes = [], [], []
        for (x1, y1, _, _), r in zip(regions, results):
            b = r.boxes
            if len(b) == 0:
                continue
            boxes.append(b.xyxy.cpu().numpy() + np.array([x1, y1, x1, y1]))
            confs.append(b.conf.cpu().numpy())
            classes.append(b.cls.cpu().numpy().astype(int))
        if not boxes:
            return np.zeros((0, 4)), np.zeros(0), np.zeros(0, dtype=int), regions

        boxes, confs, classes = np.concatenate(boxes), np.concatenate(confs), np.concatenate(classes)
        # 사람 크롭끼리 겹치면 같은 장비가 두 번 잡히므로 클래스별 NMS로 합친다
        keep = torchvision.ops.batched_nms(
            torch.from_numpy(boxes).float(), torch.from_numpy(confs).float(), torch.from_numpy(classes), 0.5
        ).numpy()
        return boxes[keep], confs[keep], classes[keep], regions


def draw(frame, boxes, confs, classes, regions, names):
    for x1, y1, x2, y2 in regions:
        cv2.rectangle(frame, (x1, y1), (x2, y2), (200, 200, 200), 1)
    for (x1, y1, x2, y2), c, k in zip(boxes.astype(int), confs, classes):
        color = (0, 0, 255) if names[k].endswith("not_worn") else (0, 200, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, f"{names[k]} {c:.2f}", (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
    return frame


def run_live(args):
    detector = TwoStageDetector(
        args.ppe_model, args.person_model, args.person_imgsz, args.person_conf, args.crop_imgsz, args.pad_x, args.pad_y,
        args.device,
    )
    names = detector.ppe.names
    source = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"소스를 열 수 없습니다: {args.source}")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            boxes, confs, classes, regions = detector(frame, args.conf)
            cv2.imshow("two-stage PPE", draw(frame, boxes, confs, classes, regions, names))
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


# ---------------------------------------------------------------- 평가 ----------------------------------------------------------------

def load_split(data_yaml: Path, split: str) -> list[tuple[Path, np.ndarray, np.ndarray]]:
    """(이미지 경로, GT xyxy 픽셀 좌표, GT cls) 목록."""
    cfg = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    img_dir = (data_yaml.parent / cfg["val" if split == "valid" else split]).resolve()
    items = []
    for img in sorted(img_dir.iterdir()):
        lbl = img.parent.parent / "labels" / (img.stem + ".txt")
        h, w = cv2.imread(str(img)).shape[:2]
        rows = [list(map(float, l.split())) for l in lbl.read_text(encoding="utf-8").splitlines() if l.strip()]
        arr = np.array(rows).reshape(-1, 5)
        xyxy = np.stack(
            [(arr[:, 1] - arr[:, 3] / 2) * w, (arr[:, 2] - arr[:, 4] / 2) * h,
             (arr[:, 1] + arr[:, 3] / 2) * w, (arr[:, 2] + arr[:, 4] / 2) * h], 1
        )
        items.append((img, xyxy, arr[:, 0].astype(int)))
    return items


def match(gt_xyxy, gt_cls, pred_xyxy, pred_cls) -> np.ndarray:
    """Ultralytics DetectionValidator.match_predictions 와 같은 방식으로 IoU 임계값별 TP 판정."""
    correct = np.zeros((len(pred_xyxy), len(IOU_THRESHOLDS)), dtype=bool)
    if len(gt_xyxy) == 0 or len(pred_xyxy) == 0:
        return correct
    iou = torchvision.ops.box_iou(torch.from_numpy(gt_xyxy).float(), torch.from_numpy(pred_xyxy).float()).numpy()
    iou = iou * (gt_cls[:, None] == pred_cls[None, :])
    for i, t in enumerate(IOU_THRESHOLDS):
        m = np.array(np.nonzero(iou >= t)).T
        if m.shape[0]:
            if m.shape[0] > 1:
                m = m[iou[m[:, 0], m[:, 1]].argsort()[::-1]]
                m = m[np.unique(m[:, 1], return_index=True)[1]]
                m = m[np.unique(m[:, 0], return_index=True)[1]]
            correct[m[:, 1], i] = True
    return correct


def source_of(name: str) -> str:
    for prefix, src in (("ext_ryan", "grayscale"), ("ext_ppe", "color_ppe")):
        if name.startswith(prefix):
            return src
    return "own"


def summarize(stats, names) -> dict[str, tuple[float, float]]:
    """{class name: (mAP50, mAP50-95)} + 'all'."""
    tp = np.concatenate(stats["tp"]) if stats["tp"] else np.zeros((0, 10), bool)
    conf = np.concatenate(stats["conf"]) if stats["conf"] else np.zeros(0)
    pcls = np.concatenate(stats["pcls"]) if stats["pcls"] else np.zeros(0)
    tcls = np.concatenate(stats["tcls"]) if stats["tcls"] else np.zeros(0)
    if len(tcls) == 0:
        return {}
    ap, classes = ap_per_class(tp, conf, pcls, tcls)[5:7]
    out = {names[c]: (ap[i, 0], ap[i].mean()) for i, c in enumerate(classes)}
    out["all"] = (ap[:, 0].mean(), ap.mean())
    return out


def run_eval(args):
    detector = TwoStageDetector(
        args.ppe_model, args.person_model, args.person_imgsz, args.person_conf, args.crop_imgsz, args.pad_x, args.pad_y,
        args.device,
    )
    names = detector.ppe.names
    items = load_split(Path(args.eval).resolve(), args.split)

    # stats[(방식, 출처)]
    stats = defaultdict(lambda: {"tp": [], "conf": [], "pcls": [], "tcls": []})
    gt_inside_crop = gt_total = 0
    for img_path, gt_xyxy, gt_cls in items:
        frame = cv2.imread(str(img_path))
        src = source_of(img_path.name)

        r = detector.ppe.predict(frame, imgsz=args.direct_imgsz, conf=0.001, device=args.device, verbose=False)[0]
        direct = (r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy(), r.boxes.cls.cpu().numpy().astype(int))
        boxes, confs, classes, regions = detector(frame, conf=0.001)

        for gx1, gy1, gx2, gy2 in gt_xyxy:
            gt_total += 1
            gt_inside_crop += any(x1 <= gx1 and y1 <= gy1 and gx2 <= x2 and gy2 <= y2 for x1, y1, x2, y2 in regions)

        for method, (pb, pc, pk) in (("direct", direct), ("two_stage", (boxes, confs, classes))):
            tp = match(gt_xyxy, gt_cls, pb, pk)
            for key in ((method, "all"), (method, src)):
                stats[key]["tp"].append(tp)
                stats[key]["conf"].append(pc)
                stats[key]["pcls"].append(pk)
                stats[key]["tcls"].append(gt_cls)

    print(f"\n평가 이미지: {len(items)}장 ({args.split})")
    print(f"GT 박스 중 사람 크롭 안에 완전히 들어간 비율: {gt_inside_crop}/{gt_total} = {gt_inside_crop / max(gt_total, 1):.1%}")
    print(f"(크롭 밖 GT는 2단계 방식에서 구조적으로 놓칠 수밖에 없다)\n")

    for src in ("all", "own", "color_ppe", "grayscale"):
        d, t = summarize(stats[("direct", src)], names), summarize(stats[("two_stage", src)], names)
        if not d:
            continue
        print(f"[{src}]  {'class':16} {'direct mAP50':>13} {'2stage mAP50':>13} {'direct 50-95':>13} {'2stage 50-95':>13}")
        for name in list(names.values()) + ["all"]:
            if name in d:
                (d50, d95), (t50, t95) = d[name], t.get(name, (0.0, 0.0))
                print(f"         {name:16} {d50:13.3f} {t50:13.3f} {d95:13.3f} {t95:13.3f}")
        print()


def main():
    args = parse_args()
    if args.eval:
        run_eval(args)
    else:
        run_live(args)


if __name__ == "__main__":
    main()
