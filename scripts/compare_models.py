"""
3차 모델(YOLOv8n/640)과 v4b 모델(YOLO11s/640, YOLO11s/1280 — test_midrange 카메라 제외 재학습)을 같은 test set(datasets/v4/test)에서
클래스별 mAP50 / mAP50-95 로 비교하고, 출처(자체 촬영 / 컬러 PPE / 그레이스케일)별로도 나눠 본다.

주의: 3차 모델은 그레이스케일 'multi-person-menggunakan-salah-satu-APD' 영상 프레임과
일부 컬러 PPE 원본(복사본)을 train에서 이미 봤다. v4 test에서는 이 둘이 test로 옮겨졌으므로
grayscale / color_ppe 구간은 3차 모델에 유리하게(누수) 나온다. 공정한 비교는 'own'(자체 촬영, person3) 구간.

사용법:
    python scripts\\compare_models.py
"""

import tempfile
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent.parent
TEST_DIR = ROOT / "datasets" / "v4" / "test" / "images"
NAMES = ["helmet_not_worn", "helmet_worn", "shoe_not_worn", "shoe_worn", "vest_not_worn", "vest_worn"]
FOCUS = {"helmet_not_worn", "vest_not_worn", "shoe_not_worn"}

MODELS = [
    ("3차 v8n/640", ROOT / "runs" / "train" / "safety_equipment-3" / "weights" / "best.pt", 640),
    ("v4b 11s/640", ROOT / "runs" / "train" / "safety_equipment_v4b_11s_640" / "weights" / "best.pt", 640),
    ("v4b 11s/1280", ROOT / "runs" / "train" / "safety_equipment_v4b_11s_1280" / "weights" / "best.pt", 1280),
    ("v4c 11s/1280 +신발", ROOT / "runs" / "train" / "safety_equipment_v4c_11s_1280" / "weights" / "best.pt", 1280),
]
SUBSETS = {
    "all": lambda n: True,
    "own": lambda n: not n.startswith("ext_"),
    "color_ppe": lambda n: n.startswith("ext_ppe"),
    "grayscale": lambda n: n.startswith("ext_ryan"),
}
OUT_MD = ROOT / "runs" / "compare_v4.md"


def evaluate(weights: Path, imgsz: int, list_file: Path, tmp: Path) -> dict[str, tuple[float, float]]:
    yaml_path = tmp / "subset.yaml"
    yaml_path.write_text(
        f"train: {list_file.as_posix()}\nval: {list_file.as_posix()}\ntest: {list_file.as_posix()}\n"
        f"nc: {len(NAMES)}\nnames: {NAMES}\n",
        encoding="utf-8",
    )
    m = YOLO(str(weights)).val(
        data=str(yaml_path), split="test", imgsz=imgsz, batch=8, plots=False, verbose=False,
        project=str(tmp), name="val", exist_ok=True,
    )
    out = {NAMES[c]: m.box.class_result(i)[2:4] for i, c in enumerate(m.box.ap_class_index)}
    out["all"] = (m.box.map50, m.box.map)
    return out


def main() -> None:
    images = sorted(p for p in TEST_DIR.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    results = {}  # (subset, model) -> {class: (ap50, ap)}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for subset, keep in SUBSETS.items():
            chosen = [p for p in images if keep(p.name)]
            list_file = tmp / f"{subset}.txt"
            list_file.write_text("\n".join(str(p) for p in chosen) + "\n", encoding="utf-8")
            for label, weights, imgsz in MODELS:
                results[(subset, label)] = evaluate(weights, imgsz, list_file, tmp)
            results[(subset, "_n")] = len(chosen)

    labels = [m[0] for m in MODELS]
    lines = [f"# {' vs '.join(labels)} — datasets/v4/test", "", "각 칸: mAP50 / mAP50-95", ""]
    for subset in SUBSETS:
        lines += [
            f"## {subset} ({results[(subset, '_n')]}장)", "",
            "| class | " + " | ".join(labels) + " |",
            "|---" * (len(labels) + 1) + "|",
        ]
        for name in NAMES + ["all"]:
            vals = [results[(subset, m)].get(name) for m in labels]
            if all(v is None for v in vals):
                continue
            label = f"**{name}**" if name in FOCUS or name == "all" else name
            lines.append(f"| {label} | " + " | ".join(f"{(v or (0, 0))[0]:.3f} / {(v or (0, 0))[1]:.3f}" for v in vals) + " |")
        lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"저장: {OUT_MD}")


if __name__ == "__main__":
    main()
