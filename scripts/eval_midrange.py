"""
중간거리(드론 고각, 헬멧 ~36px) 재검증: datasets/v4/test_midrange 에서
모델 x 입력 해상도 x (원본 그대로 / 사람 크롭 2단계) 를 같은 기준으로 비교한다.

test_midrange 는 Worksite-Obj-Det 3개 카메라(tla2119, TLA2181VF, TL2174)의 1280 타일로,
v4b 모델들(11s/640, 11s/1280)은 이 카메라들을 학습에서 보지 않았다. 3차 v8n/640 은 Worksite 자체를 본 적이 없다.
(기존 safety_equipment_v4_11s_1280 은 이 카메라들로 학습했으므로 비교에서 뺐다.)

한계: Worksite 원본에 미착용 라벨이 없어서 test_midrange 에는 helmet_worn / vest_worn 만 있다.
미착용 클래스는 mAP를 잴 수 없으므로 'conf>=0.4 미착용 예측 수'를 오탐 지표로 함께 보여준다
(타일은 라벨된 사람 전원이 헬멧을 쓴 것만 골랐으므로 helmet_not_worn 예측은 사실상 오탐).

사용법:
    python scripts\\eval_midrange.py
"""

from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

from detect_two_stage import DEFAULT_PERSON_MODEL, TwoStageDetector, load_split, match, summarize

ROOT = Path(__file__).resolve().parent.parent
DATA_YAML = ROOT / "datasets" / "data_v4.yaml"
OUT_MD = ROOT / "runs" / "compare_midrange.md"
TRAIN = ROOT / "runs" / "train"

# (표시 이름, 가중치, 원본 그대로 입력 크기)
MODELS = [
    ("3차 v8n/640", TRAIN / "safety_equipment-3" / "weights" / "best.pt", 640),
    ("v4b 11s/640", TRAIN / "safety_equipment_v4b_11s_640" / "weights" / "best.pt", 640),
    ("v4b 11s/1280", TRAIN / "safety_equipment_v4b_11s_1280" / "weights" / "best.pt", 1280),
    ("v4c 11s/1280 +신발", TRAIN / "safety_equipment_v4c_11s_1280" / "weights" / "best.pt", 1280),
]
# 2단계: 사람 탐지는 1280, 크롭은 640으로 PPE 모델에 넣는다 (detect_two_stage.py 기본값)
PERSON_IMGSZ, CROP_IMGSZ = 1280, 640
OP_CONF = 0.4  # 실사용(웹캠 표시) 기준 confidence
WORN = ("helmet_worn", "vest_worn")


def operating_point(stats, names, conf_th: float) -> dict[str, tuple[float, float]]:
    """conf_th 이상 예측만 남겼을 때 IoU 0.5 기준 클래스별 (precision, recall)."""
    out = {}
    tp = np.concatenate(stats["tp"])[:, 0]
    conf, pcls, tcls = (np.concatenate(stats[k]) for k in ("conf", "pcls", "tcls"))
    keep = conf >= conf_th
    for c, name in names.items():
        n_pred = int((keep & (pcls == c)).sum())
        n_tp = int((tp & keep & (pcls == c)).sum())
        n_gt = int((tcls == c).sum())
        if n_gt or n_pred:
            out[name] = (n_tp / n_pred if n_pred else 0.0, n_tp / n_gt if n_gt else 0.0)
    return out


def main() -> None:
    items = load_split(DATA_YAML, "test_midrange")
    gt_counts = Counter(int(c) for _, _, cls in items for c in cls)

    rows = []  # (모델, 방식, mAP dict, op dict, not_worn 오탐 Counter)
    crop_cover = None
    for label, weights, imgsz in MODELS:
        if not weights.exists():
            print(f"[건너뜀] {label}: {weights} 없음")
            continue
        det = TwoStageDetector(str(weights), str(DEFAULT_PERSON_MODEL), PERSON_IMGSZ, 0.25, CROP_IMGSZ, 0.15, 0.10)
        names = det.ppe.names
        stats = defaultdict(lambda: {"tp": [], "conf": [], "pcls": [], "tcls": []})
        inside = total = 0
        for img_path, gt_xyxy, gt_cls in items:
            frame = cv2.imread(str(img_path))
            r = det.ppe.predict(frame, imgsz=imgsz, conf=0.001, verbose=False)[0]
            direct = (r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy(), r.boxes.cls.cpu().numpy().astype(int))
            boxes, confs, classes, regions = det(frame, conf=0.001)
            for gx1, gy1, gx2, gy2 in gt_xyxy:
                total += 1
                inside += any(x1 <= gx1 and y1 <= gy1 and gx2 <= x2 and gy2 <= y2 for x1, y1, x2, y2 in regions)
            for method, (pb, pc, pk) in ((f"원본 {imgsz}", direct), ("2단계 크롭", (boxes, confs, classes))):
                s = stats[method]
                s["tp"].append(match(gt_xyxy, gt_cls, pb, pk))
                s["conf"].append(pc)
                s["pcls"].append(pk)
                s["tcls"].append(gt_cls)
        crop_cover = (inside, total)

        for method, s in stats.items():
            pcls, conf = np.concatenate(s["pcls"]), np.concatenate(s["conf"])
            fp_notworn = Counter(names[int(c)] for c in pcls[conf >= OP_CONF] if names[int(c)].endswith("not_worn"))
            rows.append((label, method, summarize(s, names), operating_point(s, names, OP_CONF), fp_notworn))
        print(f"[완료] {label}")

    hw, vw = gt_counts[1], gt_counts[5]
    lines = [
        "# 중간거리 재검증 — datasets/v4/test_midrange", "",
        f"- 이미지 {len(items)}장 (1280x1280 타일, Worksite 카메라 tla2119 / TLA2181VF / TL2174, 학습 미사용)",
        f"- GT: helmet_worn {hw}개, vest_worn {vw}개 (미착용 라벨 없음)",
        f"- 2단계: 사람 탐지 yolo11s(COCO) imgsz {PERSON_IMGSZ} -> 사람 크롭을 PPE 모델에 imgsz {CROP_IMGSZ}로 입력",
        f"- 사람 크롭 안에 완전히 들어간 GT 비율: {crop_cover[0]}/{crop_cover[1]} = {crop_cover[0] / max(crop_cover[1], 1):.1%}"
        " (밖에 있는 GT는 2단계에서 구조적으로 놓침)" if crop_cover else "",
        "",
        "## mAP (conf 0.001, 전체 PR 곡선)", "",
        "| 모델 | 방식 | helmet_worn mAP50 | vest_worn mAP50 | 평균 mAP50 | helmet_worn 50-95 | vest_worn 50-95 | 평균 50-95 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for label, method, m, _, _ in rows:
        h, v = m.get("helmet_worn", (0, 0)), m.get("vest_worn", (0, 0))
        lines.append(
            f"| {label} | {method} | {h[0]:.3f} | {v[0]:.3f} | {(h[0] + v[0]) / 2:.3f} | {h[1]:.3f} | {v[1]:.3f} | {(h[1] + v[1]) / 2:.3f} |"
        )
    lines += [
        "", f"## 실사용 기준 (conf >= {OP_CONF}, IoU 0.5)", "",
        "| 모델 | 방식 | helmet_worn P / R | vest_worn P / R | 미착용 예측 수(오탐 추정) |",
        "|---|---|---|---|---|",
    ]
    for label, method, _, op, fp in rows:
        h, v = op.get("helmet_worn", (0, 0)), op.get("vest_worn", (0, 0))
        fp_txt = ", ".join(f"{k} {n}" for k, n in sorted(fp.items())) or "0"
        lines.append(f"| {label} | {method} | {h[0]:.2f} / {h[1]:.2f} | {v[0]:.2f} / {v[1]:.2f} | {fp_txt} |")

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n저장: {OUT_MD}")


if __name__ == "__main__":
    main()
