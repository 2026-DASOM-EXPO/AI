"""
조건 C (v5bg, conf 0.4 단일) 만 측정해 A / B (report.json) 와 비교 -> runs/final_pick/report2.md, report2.json
규칙: runs/final_pick/rule2.md (실행 전 고정). 판정 함수는 final_pick.py 그대로.

사용법:
    python scripts\\final_pick_c.py
"""

import json

import cv2
from ultralytics import YOLO

import final_pick as fp

V5BG = fp.ROOT / "runs/train/safety_equipment_v5bg_11s_1280/weights/best.pt"
SEG = (954, 1271)  # 원거리 흰 헬멧 착용 구간 (report.md 사후 보조 분석과 같은 경계)
A_SEG, B_SEG = 153, 71  # report.md 사후 보조 분석 값 (report.json 에 없음)


def measure():
    run, coco = fp.Runner(V5BG, None), YOLO(str(fp.COCO))
    print("C", {run.m.names[i]: t for i, t in enumerate(run.thr)})

    def rec(img, key):
        persons, objects, seats = fp.coco_scan(coco, img)
        return {"key": key, "persons": len(persons), "C": fp.judge(run(img), run.m.names, persons, objects, seats)}

    cap = cv2.VideoCapture(str(fp.CAP / "scene1.mp4"))
    video, i = [], 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        video.append(rec(f, i))
        i += 1
    cap.release()
    still = [rec(str(p), p.name) for p in sorted(fp.CAP.glob("*.jpg"))]

    def summ(frames):
        ppl = [f for f in frames if f["persons"] > 0]
        s = {k: sum(f["C"][k] for f in frames) for k in ("fp_helmet", "fp_helmet_seat", "fp_vest")}
        s.update({k: sum(f["C"][k] for f in ppl) / max(len(ppl), 1) for k in ("on_helmet_worn", "on_vest_worn")})
        s["per_frame"] = {c: sum(f["C"]["count"][c] for f in frames) / len(frames) for c in fp.CLASSES}
        s["frames"], s["person_frames"] = len(frames), len(ppl)
        return s

    sv, ss = summ(video), summ(still)
    sv["seg_on_helmet_frames"] = sum(f["C"]["on_helmet_worn"] > 0 for f in video[SEG[0]:SEG[1]])
    return sv, ss


def main() -> None:
    out = fp.OUT
    prev = json.loads((out / "report.json").read_text(encoding="utf-8"))
    cv_, cs = measure()
    A = {"V": prev["V"]["A"], "S": prev["S"]["A"]}
    B = {"V": prev["V"]["B"], "S": prev["S"]["B"]}
    checks = [
        ("(a) scene1 954~1270 사람 위 helmet_worn 프레임 ≥ 123", cv_["seg_on_helmet_frames"] >= 123),
        ("(b) scene1 헬멧 의자·소파·벤치 겹침 오탐 ≤ 39", cv_["fp_helmet_seat"] <= 39),
        ("(c) 조끼 계열 오탐 scene1 ≤ 89, 사진 ≤ 6", cv_["fp_vest"] <= 89 and cs["fp_vest"] <= 6),
        ("(d) 사진 사람 위 helmet_worn ≥ 0.8×A, vest_worn ≥ 0.8×A",
         cs["on_helmet_worn"] >= 0.8 * A["S"]["on_helmet_worn"] and cs["on_vest_worn"] >= 0.8 * A["S"]["on_vest_worn"]),
    ]
    pick = "C" if all(ok for _, ok in checks) else "A"

    def row(name, a, b, c, f="{}"):
        return f"| {name} | {f.format(a)} | {f.format(b)} | {f.format(c)} |"

    L = ["# 조건 C 비교 (모델 효과 분리)", "",
         "A = v4b conf 0.4 / B = v5bg helmet_worn 0.5, vest 계열 0.3, 나머지 0.4 / C = v5bg conf 0.4 단일. imgsz 1280.",
         "A·B 는 report.json 값(구간 954~1270 프레임 수만 report.md 사후 분석 값), C 는 이번 측정. 규칙: rule2.md", "",
         "| 지표 | A | B | C |", "|---|---|---|---|",
         row("scene1 954~1270 사람 위 helmet_worn 프레임 (317프레임 중)", A_SEG, B_SEG, cv_["seg_on_helmet_frames"])]
    for t, cc, tag in (("V", cv_, "scene1"), ("S", cs, "사진 87장")):
        L += [row(f"{tag} helmet_worn 오탐 후보", A[t]["fp_helmet"], B[t]["fp_helmet"], cc["fp_helmet"]),
              row(f"{tag} └ 의자·소파·벤치 겹침", A[t]["fp_helmet_seat"], B[t]["fp_helmet_seat"], cc["fp_helmet_seat"]),
              row(f"{tag} 조끼 계열 오탐 후보", A[t]["fp_vest"], B[t]["fp_vest"], cc["fp_vest"]),
              row(f"{tag} 사람 위 helmet_worn / 사람 프레임", A[t]["on_helmet_worn"], B[t]["on_helmet_worn"], cc["on_helmet_worn"], "{:.3f}"),
              row(f"{tag} 사람 위 vest_worn / 사람 프레임", A[t]["on_vest_worn"], B[t]["on_vest_worn"], cc["on_vest_worn"], "{:.3f}")]
        for c in fp.CLASSES:
            L.append(row(f"{tag} {c} / 프레임", A[t]["per_frame"][c], B[t]["per_frame"][c], cc["per_frame"][c], "{:.3f}"))
    L += ["", "## 판정 (rule2.md)", ""] + [f"- {n}: {'충족' if ok else '**미충족**'}" for n, ok in checks]
    L += [f"- **결론: {'C 채택' if pick == 'C' else 'A 유지'}**"]
    (out / "report2.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (out / "report2.json").write_text(json.dumps({"C": {"V": cv_, "S": cs}, "checks": checks, "pick": pick},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
