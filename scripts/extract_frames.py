"""
raw_videos 폴더의 영상에서 움직임(프레임 간 픽셀 diff) 기반으로 프레임을 추출해
raw_images 폴더에 저장하는 스크립트.

- 이전 프레임과의 픽셀 차이(diff)가 큰 프레임을 우선 저장 (고정 간격 저장 아님)
- 저장 간격은 최소 0.2초 ~ 최대 1.0초 사이로 제한
- 영상 길이와 목표 장수로부터 탐색 구간(window)을 계산하고, 각 구간에서
  움직임이 가장 큰 프레임을 골라 저장 -> 목표 장수에 가깝게 자동 수렴
  (목표 장수보다 많이 저장되는 것은 허용)

사용 예시:
    python scripts\\extract_frames.py
"""

from pathlib import Path

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
RAW_VIDEOS_DIR = SCRIPT_DIR.parent / "datasets" / "raw_videos"
RAW_IMAGES_DIR = SCRIPT_DIR.parent / "datasets" / "raw_images"

MIN_INTERVAL_SEC = 0.2
MAX_INTERVAL_SEC = 1.0

DIFF_RESIZE_WIDTH = 320  # diff 계산 속도를 위해 축소할 폭 (저장은 원본 해상도 그대로)

# 실제 촬영 파일명(IMG_31xx) -> 저장에 사용할 의미있는 이름
VIDEO_NAME_MAP = {
    "IMG_3105": "all_worn_person1",
    "IMG_3106": "no_helmet_person1",
    "IMG_3107": "no_shoe_person1",
    "IMG_3108": "no_vest_person1",
    "IMG_3109": "all_worn_person2",
    "IMG_3110": "no_helmet_person2",
    "IMG_3111": "no_shoe_person2",
    "IMG_3112": "no_vest_person2",
    "IMG_3113": "all_worn_person3",
    "IMG_3114": "no_helmet_person3",
    "IMG_3115": "no_shoe_person3",
    "IMG_3116": "no_vest_person3",
    "IMG_3117": "shoe_closeup_1",
    "IMG_3118": "shoe_closeup_2",
    "IMG_3119": "shoe_closeup_3",
    "IMG_3120": "shoe_closeup_4",
}

# 저장용 이름 -> 목표 장수
TARGET_COUNTS = {}
for _i in (1, 2, 3):
    TARGET_COUNTS[f"all_worn_person{_i}"] = 35
    TARGET_COUNTS[f"no_helmet_person{_i}"] = 35
    TARGET_COUNTS[f"no_vest_person{_i}"] = 35
    TARGET_COUNTS[f"no_shoe_person{_i}"] = 35
for _i in (1, 2, 3, 4):
    TARGET_COUNTS[f"shoe_closeup_{_i}"] = 50


def to_small_gray(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = DIFF_RESIZE_WIDTH / w
    small = cv2.resize(frame, (DIFF_RESIZE_WIDTH, max(1, int(h * scale))))
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def motion_score(prev_gray_small: np.ndarray, gray_small: np.ndarray) -> float:
    return float(np.mean(cv2.absdiff(prev_gray_small, gray_small)))


def extract_frames(video_path: Path, out_name: str, target_count: int, out_dir: Path) -> int:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"[SKIP] {video_path.name}: 영상을 열 수 없습니다.")
        return 0

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps > 0 else 0.0

    min_gap = max(1, round(MIN_INTERVAL_SEC * fps))
    max_gap = max(min_gap, round(MAX_INTERVAL_SEC * fps))

    # 목표 장수를 채우기 위한 이상적인 저장 간격(초) -> 0.2~1.0초로 clamp
    ideal_interval = duration / target_count if target_count > 0 and duration > 0 else MAX_INTERVAL_SEC
    window_interval = min(max(ideal_interval, MIN_INTERVAL_SEC), MAX_INTERVAL_SEC)
    window_gap = max(min_gap, min(round(window_interval * fps), max_gap))

    saved = 0
    frame_idx = -1
    prev_small_gray = None
    last_saved_idx = -min_gap  # 첫 프레임부터 저장 후보가 될 수 있도록

    best_idx = None
    best_score = -1.0
    best_frame = None

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1

        small_gray = to_small_gray(frame)
        score = motion_score(prev_small_gray, small_gray) if prev_small_gray is not None else 0.0
        prev_small_gray = small_gray

        window_start = last_saved_idx + min_gap
        window_end = last_saved_idx + window_gap

        if frame_idx < window_start:
            continue

        if score > best_score:
            best_score = score
            best_idx = frame_idx
            best_frame = frame

        if frame_idx >= window_end:
            saved += 1
            out_path = out_dir / f"{out_name}_{saved:03d}.jpg"
            cv2.imwrite(str(out_path), best_frame)
            last_saved_idx = best_idx
            best_idx, best_score, best_frame = None, -1.0, None

    # 영상 끝에서 아직 저장되지 않은 후보(마지막 미완성 구간)가 있으면 저장
    if best_frame is not None:
        saved += 1
        out_path = out_dir / f"{out_name}_{saved:03d}.jpg"
        cv2.imwrite(str(out_path), best_frame)

    cap.release()
    return saved


def main():
    RAW_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    video_files = sorted(RAW_VIDEOS_DIR.glob("*.mov"))
    if not video_files:
        print(f"[경고] {RAW_VIDEOS_DIR} 에서 영상을 찾지 못했습니다.")
        return

    print(f"총 {len(video_files)}개 영상 처리 시작")
    print(f"저장 위치: {RAW_IMAGES_DIR}\n")

    results = []
    for video_path in video_files:
        stem = video_path.stem
        out_name = VIDEO_NAME_MAP.get(stem)
        if out_name is None:
            print(f"[SKIP] {video_path.name}: 매핑 정보가 없습니다.")
            continue

        target_count = TARGET_COUNTS.get(out_name, 35)
        saved = extract_frames(video_path, out_name, target_count, RAW_IMAGES_DIR)

        status = "OK " if saved >= target_count else "부족"
        print(f"[{status}] {video_path.name} -> {out_name}: {saved}장 저장 (목표 {target_count}장)")
        results.append((out_name, saved, target_count))

    total = sum(s for _, s, _ in results)
    shortfall = [f"{name}({saved}/{target})" for name, saved, target in results if saved < target]

    print("\n=== 요약 ===")
    for name, saved, target in results:
        print(f"  {name}: {saved}/{target}")
    print(f"총 저장된 이미지: {total}장")
    if shortfall:
        print(f"목표 미달 영상: {', '.join(shortfall)} (영상 길이가 짧아 최소 간격(0.2초) 제약으로 더 뽑을 수 없음)")


if __name__ == "__main__":
    main()
