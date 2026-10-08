"""
시연용 최종 모델 고르기 (학습 없음): A = v4b conf 0.4 / B = v5bg helmet_worn 0.5, vest 계열 0.3, 나머지 0.4
선택 규칙은 runs/final_pick/rule.md (실행 전에 고정).

입력: captures/scene1.mp4 전체 프레임(V) + captures/*.jpg 전체(S), imgsz 1280
출력 (runs/final_pick/):
    side_by_side.mp4   scene1 좌 A / 우 B
    contact_sheet.jpg  두 모델 검출 수 차이가 가장 큰 12프레임 (좌 A / 우 B)
    report.md, report.json
클래스별 conf 는 detect_stream.py --class-conf 와 같은 방식: conf 0.25 로 한 번 추론 후 클래스별 후필터링.

사용법:
    python scripts\\final_pick.py
"""

import json
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO

from baseline_v4b import head_rule
from captures_fp_all import OBJ_IOU, WEARABLE, box_iou, torso_rule

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "runs" / "final_pick"
CAP = ROOT / "captures"
COCO = ROOT / "models" / "yolo11s.pt"
IMGSZ, FLOOR = 1280, 0.25
SEATS = {56, 57, 13}  # COCO chair, couch, bench
CLASSES = ["helmet_worn", "helmet_not_worn", "vest_worn", "vest_not_worn", "shoe_worn", "shoe_not_worn"]
MODELS = {
    "A": (ROOT / "runs/train/safety_equipment_v4b_11s_1280/weights/best.pt", None),
    "B": (ROOT / "runs/train/safety_equipment_v5bg_11s_1280/weights/best.pt", "helmet_worn=0.5,vest_worn=0.3"),
}
DEFAULT_CONF = 0.4


def parse_class_conf(spec, names, default):
    """detect_stream.py 와 같은 해석: vest_worn 값은 vest_not_worn 에도 적용."""
    given = {}
    for part in (spec.split(",") if spec else []):
        k, v = part.split("=")
        given[k.strip()] = float(v)
    if "vest_worn" in given:
        given.setdefault("vest_not_worn", given["vest_worn"])
    return [given.get(names[i], default) for i in range(len(names))]


class Runner:
    def __init__(self, weights, spec):
        self.m = YOLO(str(weights))
        self.thr = parse_class_conf(spec, self.m.names, DEFAULT_CONF)

    def __call__(self, img):
        r = self.m.predict(img, imgsz=IMGSZ, conf=min(self.thr), verbose=False)[0]
        thr = torch.tensor(self.thr, device=r.boxes.conf.device)
        return r[r.boxes.conf >= thr[r.boxes.cls.long()]]


def coco_scan(coco, img):
    r = coco.predict(img, imgsz=IMGSZ, conf=0.25, verbose=False)[0]
    b, k = r.boxes.xyxy.cpu().numpy(), r.boxes.cls.cpu().numpy().astype(int)
    persons = b[k == 0]
    objects = b[(k != 0) & ~np.isin(k, list(WEARABLE))]
    seats = b[np.isin(k, list(SEATS))]
    return persons, objects, seats


def judge(r, names, persons, objects, seats):
    """프레임 하나의 클래스별 검출 수, 헬멧/조끼 오탐 후보, 사람 위 착용 검출 수."""
    d = {"count": {c: 0 for c in CLASSES}, "fp_helmet": 0, "fp_helmet_seat": 0, "fp_vest": 0,
         "on_helmet_worn": 0, "on_vest_worn": 0}
    for b, k in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.cpu().numpy().astype(int)):
        name = names[k]
        d["count"][name] += 1
        if name == "helmet_worn":
            fp = head_rule(b, persons)[0]
        elif name.startswith("vest"):
            fp = torso_rule(b, persons)[0]
        else:
            continue
        if len(objects) and box_iou(b, objects).max() >= OBJ_IOU:
            fp = True
        if name == "helmet_worn":
            if fp:
                d["fp_helmet"] += 1
                d["fp_helmet_seat"] += int(len(seats) > 0 and box_iou(b, seats).max() > 0)
            else:
                d["on_helmet_worn"] += 1
        else:
            if fp:
                d["fp_vest"] += 1
            elif name == "vest_worn":
                d["on_vest_worn"] += 1
    return d


def label(img, text):
    cv2.rectangle(img, (0, 0), (len(text) * 15 + 16, 40), (0, 0, 0), -1)
    cv2.putText(img, text, (8, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    return img


def summarize(frames):
    n = len(frames)
    ppl = [f for f in frames if f["persons"] > 0]
    s = {"frames": n, "person_frames": len(ppl)}
    for m in MODELS:
        s[m] = {"per_frame": {c: sum(f[m]["count"][c] for f in frames) / n for c in CLASSES},
                "fp_helmet": sum(f[m]["fp_helmet"] for f in frames),
                "fp_helmet_seat": sum(f[m]["fp_helmet_seat"] for f in frames),
                "fp_vest": sum(f[m]["fp_vest"] for f in frames),
                "on_helmet_worn": sum(f[m]["on_helmet_worn"] for f in ppl) / max(len(ppl), 1),
                "on_vest_worn": sum(f[m]["on_vest_worn"] for f in ppl) / max(len(ppl), 1)}
    s["R_h"] = s["B"]["on_helmet_worn"] / s["A"]["on_helmet_worn"] if s["A"]["on_helmet_worn"] else float("nan")
    s["R_v"] = s["B"]["on_vest_worn"] / s["A"]["on_vest_worn"] if s["A"]["on_vest_worn"] else float("nan")
    return s


def decide(sv, ss):
    verdicts, notes = [], []
    for tag, s in (("V", sv), ("S", ss)):
        dfp = s["A"]["fp_helmet"] - s["B"]["fp_helmet"]
        ok = dfp > 0 and s["R_h"] >= 0.80 and s["R_v"] >= 0.80
        amb = dfp <= 2 or any(0.80 <= s[k] < 0.85 for k in ("R_h", "R_v"))
        if any(np.isnan(s[k]) for k in ("R_h", "R_v")):
            ok, amb = False, True
            notes.append(f"{tag}: A 의 사람 위 착용 검출이 0 이라 비율 계산 불가")
        notes.append(f"{tag}: FP_h A−B = {dfp}, R_h {s['R_h']:.2f}, R_v {s['R_v']:.2f} → "
                     f"{'충족' if ok else '미충족'}{' (애매)' if amb else ''}")
        verdicts.append((ok, amb))
    if all(ok for ok, _ in verdicts) and not any(amb for _, amb in verdicts):
        return "B", notes
    if verdicts[0][0] != verdicts[1][0]:
        notes.append("V 와 S 결론이 다름 → 애매")
    return "A", notes


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    runners = {k: Runner(*v) for k, v in MODELS.items()}
    coco = YOLO(str(COCO))
    for k, r in runners.items():
        print(k, {r.m.names[i]: t for i, t in enumerate(r.thr)})

    # 후필터링 = 그 conf 로 직접 추론한 결과인지 확인 (A: conf 0.4 직접 추론과 비교)
    stills = sorted(CAP.glob("*.jpg"))
    mism = 0
    for p in stills[::4]:
        a = runners["A"](str(p))
        d = runners["A"].m.predict(str(p), imgsz=IMGSZ, conf=0.4, verbose=False)[0]
        mism += int(len(a.boxes) != len(d.boxes) or not torch.allclose(a.boxes.data, d.boxes.data, atol=1e-3))
    print(f"후필터링 동치 확인: {len(stills[::4])}장 중 불일치 {mism}")

    def frame_record(img, key):
        persons, objects, seats = coco_scan(coco, img)
        rec = {"key": key, "persons": len(persons)}
        res = {}
        for k, run in runners.items():
            res[k] = run(img)
            rec[k] = judge(res[k], run.m.names, persons, objects, seats)
        rec["diff"] = sum(abs(rec["A"]["count"][c] - rec["B"]["count"][c]) for c in CLASSES)
        return rec, res

    # V: scene1.mp4 전체 + 좌우 비교 영상
    cap = cv2.VideoCapture(str(CAP / "scene1.mp4"))
    fps = cap.get(cv2.CAP_PROP_FPS)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    vw = cv2.VideoWriter(str(OUT / "side_by_side.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W * 2, H))
    video, i = [], 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        rec, res = frame_record(f, f"scene1#{i:05d}")
        video.append(rec)
        vw.write(np.hstack([label(res["A"].plot(), "A v4b conf0.4"),
                            label(res["B"].plot(), "B v5bg h0.5 v0.3 else0.4")]))
        i += 1
        if i % 200 == 0:
            print(f"scene1 {i}")
    cap.release(); vw.release()

    # S: captures/*.jpg 전체
    still = [frame_record(str(p), p.name)[0] for p in stills]

    sv, ss = summarize(video), summarize(still)
    pick, notes = decide(sv, ss)

    # contact sheet: 검출 수 차이 상위 12프레임 (scene1 은 서로 25프레임 이상 떨어진 것만)
    chosen = []
    for rec in sorted(video + still, key=lambda r: -r["diff"]):
        if len(chosen) == 12:
            break
        if rec["key"].startswith("scene1#"):
            idx = int(rec["key"].split("#")[1])
            if any(c["key"].startswith("scene1#") and abs(int(c["key"].split("#")[1]) - idx) < 25 for c in chosen):
                continue
        chosen.append(rec)
    tiles = []
    cap = cv2.VideoCapture(str(CAP / "scene1.mp4"))
    for rec in chosen:
        if rec["key"].startswith("scene1#"):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(rec["key"].split("#")[1]))
            img = cap.read()[1]
        else:
            img = cv2.imread(str(CAP / rec["key"]))
        pair = [cv2.resize(runners[k](img).plot(), (480, 270)) for k in MODELS]
        t = np.hstack(pair)
        label(t, f"{rec['key']}  A{sum(rec['A']['count'].values())} B{sum(rec['B']['count'].values())}")
        tiles.append(t)
    cap.release()
    while len(tiles) % 3:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[j:j + 3]) for j in range(0, len(tiles), 3)]
    cv2.imwrite(str(OUT / "contact_sheet.jpg"), np.vstack(rows))

    res = {"V": sv, "S": ss, "pick": pick, "notes": notes, "postfilter_mismatch": mism,
           "contact": [r["key"] for r in chosen]}
    (OUT / "report.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# 최종 모델 선택 결과", "", "규칙: rule.md. A = v4b conf 0.4 / B = v5bg helmet_worn 0.5, vest 계열 0.3, 나머지 0.4. imgsz 1280", ""]
    for tag, s in (("V = scene1.mp4", sv), ("S = captures/*.jpg", ss)):
        lines += [f"## {tag} ({s['frames']}프레임, 사람 있는 프레임 {s['person_frames']})", "",
                  "| 지표 | A | B | B/A |", "|---|---|---|---|"]
        for c in CLASSES:
            a, b = s["A"]["per_frame"][c], s["B"]["per_frame"][c]
            lines.append(f"| {c} /프레임 | {a:.3f} | {b:.3f} | {b / a if a else float('nan'):.2f} |")
        for k, nm in (("fp_helmet", "헬멧 오탐 후보 (판정 지표)"), ("fp_helmet_seat", "└ 그중 COCO 의자/소파/벤치와 겹침"),
                      ("fp_vest", "조끼 계열 오탐 후보")):
            lines.append(f"| {nm} | {s['A'][k]} | {s['B'][k]} | |")
        lines.append(f"| 사람 프레임 helmet_worn(사람 위)/프레임 | {s['A']['on_helmet_worn']:.3f} | {s['B']['on_helmet_worn']:.3f} | {s['R_h']:.2f} |")
        lines.append(f"| 사람 프레임 vest_worn(사람 위)/프레임 | {s['A']['on_vest_worn']:.3f} | {s['B']['on_vest_worn']:.3f} | {s['R_v']:.2f} |")
        lines.append("")
    lines += ["## 판정", ""] + [f"- {n}" for n in notes] + [f"- **권고: {pick}**", "",
              f"후필터링 동치 확인 불일치 {mism}건. contact sheet: {', '.join(r['key'] for r in chosen)}"]
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
