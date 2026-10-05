# EXPO - 산업 안전 통합 시스템 (YOLO 기반 객체 인식)

## 프로젝트 개요
산업 현장의 안전 관리를 위해 YOLOv8 기반 실시간 객체 인식 시스템을 구축하는 프로젝트입니다.
경량 모델(YOLOv8n)을 기반으로 사람 인식 테스트를 시작으로, 향후 안전모/안전조끼/안전벨트
착용 여부를 인식하는 커스텀 모델로 확장할 계획입니다.

## 현재 진행 상태
- [x] Python 3.11 가상환경 및 개발 환경 구성
- [x] `ultralytics`(YOLOv8), `opencv-python` 설치
- [x] YOLOv8n(`yolov8n.pt`) 사전학습 모델 다운로드
- [x] 웹캠 실시간 객체 인식 스크립트(`scripts/detect_webcam.py`) 작성 및 사람(person) 인식 테스트 완료
- [x] 안전장비(헬멧/조끼/신발) 착용 여부 데이터셋 수집 및 라벨링 (Roboflow, 1676장)
- [x] 커스텀 모델 1차 학습 완료 — 단, 자체 검증에서 한계점 발견 (아래 [학습 결과 및 한계점](#학습-결과-및-한계점) 참고)
- [x] Roboflow Universe 공개 PPE 데이터셋 2종을 클래스 매핑 후 병합하여 재학습 (특히 취약했던 `shoe_worn`/`shoe_not_worn` 보강)
- [x] 드론 각도(중간거리) 대응 4차 학습: YOLO11s + 입력 1280, Worksite 고각 카메라 타일 추가, 데이터 누수 정리 → **기본 배포 모델을 4차(v4b, 11s/1280)로 교체** (아래 [4차 학습](#4차-학습-yolo11s--1280-드론-중간거리-대응) 참고)
- [x] 사람 크롭 2단계 구조(사람 탐지 → 크롭 → PPE) 검증 → 중간거리에서 오히려 성능 하락하여 **폐기**
- [x] 공개 신발 데이터셋(Patras + boots-detection 서브샘플) 발 크롭 153장 병합 후 재학습(v4c) → `shoe_not_worn` 개선 없음, **배포 모델은 v4b 유지** (아래 [4차 추가 학습 (v4c)](#4차-추가-학습-v4c-공개-신발-데이터-병합) 참고)
- [ ] 추가 촬영 및 재학습 (중간점검 이후 진행 예정)

## 향후 계획
1. **다음 드론 촬영 시 검은 운동화 ↔ 안전화 페어 촬영 필수** — 같은 사람·같은 장소·같은 고도에서 검은/남색 운동화,
   검은 구두, 검은 안전화를 번갈아 신고 촬영. `shoe_not_worn`은 모든 모델에서 자체 촬영 test 기준 mAP50 ≈ 0이고,
   공개 데이터에는 '착용 상태의 검은 일반 신발' 예시가 거의 없다 (`runs/shoe_survey/README.md`).
   색 외의 단서(토캡 돌출, 두꺼운 밑창, 발목 높이)를 학습시키려면 색만 같은 대조 쌍이 가장 효과적이다.
   공개 신발 데이터 153장 병합(v4c)으로도 자체 촬영 검은 운동화는 132개 중 0개를 `shoe_not_worn`으로 잡았다 — 공개 데이터로는 해결 불가 확인.
2. **`shoe_not_worn` 라벨 정의 정리** — 자체 촬영 `no_vest_*` 이미지에서는 '안전화를 신은 사람 옆 바닥에 벗어 둔 운동화'가
   `shoe_not_worn`으로 라벨돼 있다 (train 104 / valid 69 / test 104박스). '사람이 안전화를 안 신음'과 다른 개념이라
   학습 신호를 흐리고 test 수치도 왜곡한다. 사람에게 신겨지지 않은 신발은 라벨에서 빼거나 별도 처리하고 재학습 필요.
3. `vest_not_worn` 클래스 표본 보강 (누수 없는 v4 test의 컬러 PPE 구간 기준 v4b mAP50 0.213으로 가장 취약)
4. 드론 중간거리용 미착용(helmet_not_worn / vest_not_worn) 라벨 데이터 확보 — 현재 중간거리 검증셋(`test_midrange`)에는 착용 라벨만 있어 미착용 성능은 측정 불가
5. 촬영 인원 확대 후 추가 촬영 (`datasets/raw_images`) 및 재학습
6. 실제 배포 환경(웹캠 등)과 유사한 조건의 이미지 보강

## 폴더 구조
```
EXPO/
├── venv/                  # 가상환경 (git 제외)
├── scripts/
│   ├── detect_webcam.py           # 웹캠 실시간 인식 스크립트 (기본: 4차 v4b 11s/1280)
│   ├── train_custom.py            # 커스텀 YOLOv8 학습 스크립트 (1~3차)
│   ├── merge_external_datasets.py # 외부 Roboflow PPE 데이터셋 병합 스크립트 (3차)
│   ├── resplit_by_person.py       # person 단위 train/valid/test 재분리
│   ├── extract_frames.py          # 영상에서 프레임 추출
│   ├── prepare_worksite_tiles.py  # (4차) Worksite 고각 카메라 4K → 1280 타일
│   ├── prepare_shoe_crops.py      # (4차) 공개 신발 데이터셋 → 발 크롭 (Patras + boots-detection 서브샘플)
│   ├── rebuild_dataset_v4.py      # (4차) 중복/누수 정리 + 외부 데이터 합쳐 datasets/v4 생성
│   ├── train_v4.py                # (4차) YOLO11s 학습 (--imgsz 640|1280)
│   ├── compare_models.py          # 모델별 v4 test 비교 → runs/compare_v4.md
│   ├── eval_midrange.py           # 중간거리(test_midrange) 비교, 원본 vs 2단계 → runs/compare_midrange.md
│   ├── survey_shoe_datasets.py    # 공개 신발 데이터셋 필터링 통계
│   └── detect_two_stage.py        # 사람 크롭 2단계 파이프라인 (검증 결과 폐기, 기록용)
├── models/
│   ├── yolov8n.pt          # YOLOv8n 사전학습 가중치 (COCO)
│   └── yolo11s.pt          # YOLO11s 사전학습 가중치 (COCO, 4차 학습 베이스, git 미추적 — 없으면 train_v4.py 실행 시 자동 다운로드)
├── datasets/
│   ├── raw_images/        # 원본 촬영 이미지 (git 제외)
│   ├── raw_videos/        # 원본 촬영 영상 (git 제외)
│   ├── external/          # 외부 Roboflow 데이터셋 다운로드 스테이징 (git 제외, merge 스크립트가 소비)
│   ├── train/, valid/, test/  # 실제 학습에 쓰이는 images/labels (용량 문제로 git 제외, 로컬에만 존재)
│   ├── v4/                # 4차 데이터셋 train/valid/test/test_midrange (git 제외, rebuild_dataset_v4.py로 재생성)
│   ├── data.yaml          # 1~3차 학습용 데이터셋 정의 (6클래스)
│   └── data_v4.yaml       # 4차 학습용 데이터셋 정의 (같은 6클래스 + test_midrange)
├── runs/
│   ├── train/safety_equipment_v4b_11s_1280/  # 현재 배포 모델(4차) — weights/best.pt, results.png, confusion_matrix.png만 git 추적
│   ├── train/safety_equipment-3/  # 이전 배포 모델(3차) — 같은 방식으로 일부만 git 추적
│   ├── compare_v4.md, compare_midrange.md  # 4차 교체 근거 리포트
│   └── shoe_survey/       # 공개 신발 데이터셋 조사 리포트 + 샘플 이미지
├── requirements.txt
└── .gitignore
```
> ⚠️ `datasets/train|valid|test`는 용량(약 1.5GB) 문제로 git에 올리지 않습니다. 저장소를 새로 clone하면
> 웹캠 인식(`detect_webcam.py`)은 바로 되지만, 재학습(`train_custom.py`)을 하려면 데이터셋을 별도로 준비해야 합니다
> (원본 Roboflow 프로젝트 `datasets/data.yaml`의 `roboflow.url` + 아래 3차 학습에서 쓴 외부 데이터셋 2종).

## 설치 및 실행 방법

### 1. 가상환경 생성 및 활성화 (Windows PowerShell)
```powershell
cd C:\EXPO
python -m venv venv
.\venv\Scripts\Activate.ps1
```
> 실행 정책 오류(스크립트 실행 차단) 발생 시:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

### 2. 패키지 설치
```powershell
pip install -r requirements.txt
```
> `requirements.txt`의 `torch`/`torchvision`은 CPU 빌드 기준 버전입니다. 재학습(`train_custom.py`)을
> GPU(CUDA)로 돌리고 싶다면, 위 설치 후 아래처럼 CUDA 빌드로 덮어 설치하세요 (이 프로젝트는 CUDA 12.4 기준으로 검증됨):
> ```powershell
> pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
> ```
> GPU 없이 CPU로만 돌려도 웹캠 인식(`detect_webcam.py`)은 정상 동작합니다 (속도만 느려짐).

### 3. 웹캠 실시간 인식 실행
> 새 터미널을 열었다면 먼저 가상환경을 다시 활성화해야 합니다. (프롬프트 앞에 `(venv)`가 표시되는지 확인)
> ```powershell
> cd C:\EXPO
> .\venv\Scripts\Activate.ps1
> ```

```powershell
# 기본값: 4차 안전장비 모델(runs/train/safety_equipment_v4b_11s_1280/weights/best.pt), 입력 1280으로 인식
python scripts\detect_webcam.py

# 카메라 인덱스 / confidence threshold 지정
python scripts\detect_webcam.py --camera 0 --conf 0.5

# 이전(3차, YOLOv8n/640) 모델로 실행
python scripts\detect_webcam.py --model runs\train\safety_equipment-3\weights\best.pt --imgsz 640

# COCO 사전학습 모델(80개 클래스)로 실행하고 싶을 때
python scripts\detect_webcam.py --model models\yolov8n.pt --imgsz 640
```
> 4차 모델은 YOLO11s + 입력 1280이라 3차(v8n/640)보다 무겁다 (RTX 4060 Ti 기준 이미지당 추론 약 8ms, CPU에서는 크게 느려짐).
> CPU만 있는 환경에서 속도가 부족하면 `--imgsz 640`으로 낮출 수 있지만 원거리(드론) 인식률이 떨어진다.
종료: 웹캠 창이 활성화된 상태에서 `q` 키 입력

## 사용 모델
- 기본값(`detect_webcam.py` 기본 실행): `runs/train/safety_equipment_v4b_11s_1280/weights/best.pt`
  (YOLO11s, 입력 1280, 안전장비 착용 여부 6개 클래스, 교체 근거는 아래 [4차 학습](#4차-학습-yolo11s--1280-드론-중간거리-대응) 참고)
- 이전 모델: `runs/train/safety_equipment-3/weights/best.pt` (YOLOv8n/640, 3차)
- `--model models\yolov8n.pt` 지정 시: COCO 사전학습 모델 (person 클래스 포함 80개 클래스)

## 학습 결과 및 한계점
> 1차·2차 학습 가중치는 저장소 용량 정리를 위해 삭제되었습니다 (1차는 처음부터 git 미추적, 2차는 `git rm`으로 추적 해제).
> **3차(`safety_equipment-3`)가 1,105장을 포함한 전체 병합 데이터(6,410장)로 COCO 베이스부터 재학습된 최종 모델이며,
> 정보 손실 없이 그 이전 데이터를 포함하므로 1·2차를 대체합니다.** 아래 1·2차 결과는 진행 과정 기록용으로만 남겨둠.
> **현재 배포 모델은 [4차(v4b, YOLO11s/1280)](#4차-학습-yolo11s--1280-드론-중간거리-대응)이며, 3차 가중치는 비교용으로 유지합니다.**

### 1차 학습 결과 (초기) — 이전 기록
- mAP50: 0.974 (validation set) — **누수로 부풀려진 이전 기록**
- ⚠️ 이후 자체 검증 과정에서 데이터 누수(data leakage) 발견:
  동일 영상에서 추출한 인접 프레임이 train/valid에 나뉘어 포함되어 있어
  실제 일반화 성능이 과대평가됨

### 2차 검증 (person 단위 재분리 후, 정직한 평가)
`scripts/resplit_by_person.py`로 촬영 인물(person) 단위로 train/valid/test를 다시 나눠
같은 사람의 프레임이 여러 split에 섞이지 않도록 재구성한 뒤 재학습했다.

- 학습에 사용되지 않은 인물(person3) 기준
- valid mAP50: 0.652
- test mAP50: 0.709

### 클래스별 성능 (person3 기준, mAP50)
| 클래스 | valid | test | 비고 |
|---|---|---|---|
| helmet_worn | 0.960 | 0.995 | 우수, 일관됨 |
| helmet_not_worn | 0.000 (표본 3개) | 0.995 | valid는 표본이 3개뿐이라 신뢰 불가 — test 기준 우수 |
| vest_worn | 0.954 | 0.951 | 우수, 일관됨 |
| vest_not_worn | 0.994 | 표본 없음 | valid 기준 우수, test에서는 미검증 |
| shoe_worn | 0.988 | 0.575 | **valid-test 편차가 커서 불안정 — 일반화 신뢰도 낮음** |
| shoe_not_worn | 0.017 | 0.029 | **취약. 두 세트 모두 거의 인식 못함** (confusion matrix 기준 정분류율 약 2%, 55%는 미검출, 40%는 shoe_worn으로 오분류) |

### 원인 분석
- 촬영 인원이 2~3명으로 제한되어 새로운 인물에 대한 일반화력이 부족함
- 특히 `shoe_not_worn`은 사람마다 형태(맨발/양말/슬리퍼 등)가 다양해
  소수 인원 데이터로는 공통 패턴 학습이 어려움
- `shoe_worn`은 valid에서는 높은 점수(0.988)를 보였지만 test에서는 크게
  떨어짐(0.575) — 검증 세트 하나만으로는 실제 성능을 판단하기 어렵다는 것을 보여줌

### 향후 개선 계획
1. 촬영 인원 확대 (2~3명 → 5~6명 이상)
2. `shoe_worn` / `shoe_not_worn` 두 클래스 모두 다양한 신발·각도로 집중 보강 촬영
3. 실제 배포 환경(웹캠 등)과 유사한 조건으로 촬영 추가
4. person 단위 데이터 분리(`scripts/resplit_by_person.py`)를 유지해 신뢰성 있는 검증 지속

### 3차 학습 (외부 Roboflow 공개 PPE 데이터셋 병합) — 이전 기록

> ⚠️ **이전 기록 (누수로 부풀려진 수치)**: 아래 3차 test 수치는 4차 데이터 재구성(`scripts/rebuild_dataset_v4.py`)에서
> 그레이스케일 영상의 Roboflow 증강 복사본·인접 프레임과 컬러 PPE 중복 원본이 train↔test에 걸쳐 있던 것이 확인되어 과대평가된 값이다.
> 특히 `shoe_not_worn` 0.387은 대부분 그레이스케일 구간의 누수 효과이고, 누수 없는 자체 촬영(person3) test에서 3차 모델의
> `shoe_not_worn`은 **0.009**다. 현재 기준 수치는 [4차 학습](#4차-학습-yolo11s--1280-드론-중간거리-대응) 표를 볼 것.

2차 검증에서 드러난 가장 큰 약점(`shoe_not_worn` 거의 미검출)을 보완하기 위해, Roboflow Universe에서
우리 클래스 체계와 맞는 공개 데이터셋 2종을 찾아 클래스를 리매핑한 뒤 기존 데이터셋에 병합하여 재학습했다
(`scripts/merge_external_datasets.py`, `datasets/data.yaml`은 동일한 6클래스 유지).

- **PPE by ryan** (CC BY 4.0, 1,581장): `boots`/`no boots`/`helmet`/`no helmet` → `shoe_worn`/`shoe_not_worn`/`helmet_worn`/`helmet_not_worn`에 매핑. 전처리 단계에서 그레이스케일이 적용된 이미지라 색상 단서는 없지만 형태 학습에는 기여.
- **PPE by "PPE"** (CC BY 4.0, 2,482장): `Helmet`/`No-Helmet`/`Vest`/`No-vest` → 동일 클래스에 매핑 (컬러 원본, 증강 없음). `Gloves` 등 우리 체계에 없는 클래스는 라벨에서 제거.
- 매핑 후 남은 라벨이 없는 이미지(장갑/우주복만 라벨링된 경우 등)는 제외.
- 병합 결과: train 1,105 → **6,410장**, valid 308 → **625장**, test 263 → **544장**.

#### 3차 학습 결과 (test set, `runs/train/safety_equipment-3`)
| 클래스 | mAP50 | mAP50-95 | 비고 |
|---|---|---|---|
| helmet_not_worn | 0.727 | 0.410 | 안정적으로 개선 |
| helmet_worn | 0.791 | 0.535 | 양호 |
| shoe_not_worn | **0.387** | 0.255 | 2차 대비 대폭 개선 (0.017~0.029 → 0.387) |
| shoe_worn | 0.644 | 0.401 | 양호 |
| vest_not_worn | 0.281 | 0.148 | 여전히 취약 — 외부 데이터에도 vest_not_worn 표본이 적음 |
| vest_worn | 0.952 | 0.642 | 우수, 일관됨 |
| **전체 평균** | **0.630** | 0.399 | |

- test set 구성이 이전(person3 단독)과 달리 외부 데이터셋의 다양한 환경 이미지를 포함하므로 절대 수치를
  1·2차와 단순 비교하기는 어렵지만, 가장 취약했던 `shoe_not_worn`이 실질적으로 개선된 점이 핵심 성과.
- `vest_not_worn`은 여전히 표본이 적어(외부 데이터셋에도 No-vest 비중이 낮음) 다음 보강 대상으로 남음.
- 당시 기본 배포 모델을 `runs/train/safety_equipment-3/weights/best.pt`로 교체함 (현재는 4차 v4b).

### 4차 학습 (YOLO11s + 1280, 드론 중간거리 대응)

드론 고각·중간거리(헬멧 ~30px)에서 3차 모델이 거의 인식하지 못하는 문제를 해결하기 위해 모델·해상도·데이터를 함께 바꿨다.

- 모델 YOLOv8n → **YOLO11s** (COCO 사전학습), 입력 640 → **1280**
- 데이터 `datasets/v4` (`scripts/rebuild_dataset_v4.py`)
  - 그레이스케일 영상 프레임: Roboflow 증강 복사본·연속 프레임 솎아내고 영상 단위로 split 재배정 (누수 제거)
  - 컬러 PPE: train↔valid/test 에 같은 원본이 있던 누수 제거
  - **Worksite-Obj-Det** (Roboflow, CC BY 4.0) 고각 타임랩스 카메라 4K 프레임을 1280 타일로 잘라 helmet_worn / vest_worn 추가
    (`scripts/prepare_worksite_tiles.py`, 라벨 누락 의심 타일 제외)
  - 중간거리 검증용 **`test_midrange`**: Worksite 카메라 3대(tla2119 / TLA2181VF / TL2174)의 타일 249장을 train에서 빼서 별도 보관
    (카메라 단위 분리, 학습 미사용). Worksite 원본에 미착용 라벨이 없어 helmet_worn 301 / vest_worn 117 박스만 있음
- `scripts/train_v4.py --imgsz 1280 --name safety_equipment_v4b_11s_1280` (RTX 4060 Ti, batch 6, 69 epoch에서 조기 종료)

#### 중간거리 (`test_midrange`, `runs/compare_midrange.md`)
| 모델 | 방식 | helmet_worn mAP50 | vest_worn mAP50 | 평균 mAP50 | helmet P / R (conf 0.4) |
|---|---|---|---|---|---|
| 3차 v8n/640 | 원본 | 0.124 | 0.151 | 0.138 | 0.80 / 0.04 |
| 4차 11s/640 | 원본 | 0.760 | 0.439 | 0.599 | 0.94 / 0.66 |
| **4차 11s/1280 (배포)** | **원본** | **0.834** | 0.409 | **0.622** | **0.95 / 0.73** |
| 4차 11s/1280 | 2단계 크롭 | 0.575 | 0.311 | 0.443 | 1.00 / 0.14 |

#### 근거리 (자체 촬영 test, person3 255장, `runs/compare_v4.md`, mAP50)
| 클래스 | 3차 v8n/640 | 4차 11s/640 | 4차 11s/1280 |
|---|---|---|---|
| helmet_not_worn | 0.995 | 0.994 | 0.951 |
| helmet_worn | 0.995 | 0.995 | 0.994 |
| shoe_not_worn | 0.009 | 0.000 | 0.003 |
| shoe_worn | 0.813 | 0.818 | 0.821 |
| vest_not_worn | 0.995 | 0.995 | 0.995 |
| vest_worn | 0.987 | 0.989 | 0.968 |
| **전체** | **0.799** | **0.798** | **0.789** (mAP50-95는 0.586으로 셋 중 최고) |

#### 결론 — 배포 모델을 4차(v4b, 11s/1280)로 교체
- **근거리: 3차와 동등** (자체 촬영 test mAP50 0.799 vs 0.789, mAP50-95 0.579 vs 0.586)
- **중간거리: 대폭 개선** (평균 mAP50 0.138 → 0.622, 헬멧 재현율 0.04 → 0.73). 1280 입력은 640 대비 헬멧에서 추가 이득(0.760 → 0.834)
- **2단계 크롭(사람 탐지 → 크롭 → PPE)은 폐기**: 사람 크롭 안에 온전히 들어가는 GT가 67%뿐이고, 크롭 확대 시 미착용 오탐이
  53~95건으로 늘었다. 정밀도는 약간 높았지만 mAP와 재현율(헬멧 0.73 → 0.14)이 원본 1280 추론보다 크게 낮았다
  (`scripts/detect_two_stage.py`는 기록용으로만 남김)
- 주의: v4 test 전체(all) 수치는 3차가 높게 나오지만(0.716 vs 0.616), 그레이스케일·컬러 PPE 구간은 3차가 학습 때 본 이미지가
  test로 옮겨진 것이라(누수) 3차에 유리하다. 공정한 비교는 자체 촬영(own) 구간과 `test_midrange`.
- `shoe_not_worn`은 3·4차 모두 자체 촬영 test 기준 거의 0 — 남은 최대 약점 ([향후 계획](#향후-계획) 1·2번)

### 4차 추가 학습 (v4c, 공개 신발 데이터 병합)

`shoe_not_worn` 보강을 위해 공개 신발 데이터셋 발 크롭을 v4 train에 추가하고 v4b와 같은 설정으로 재학습했다
(조사 근거 `runs/shoe_survey/README.md`).

- 추가 데이터 (`scripts/prepare_shoe_crops.py` → `rebuild_dataset_v4.py`): **153장 / 406박스** (shoe_worn 333, shoe_not_worn 73)
  - Patras(Univ. of Patras Safety Shoes v2) 전체 61장 + boots-detection 서브샘플 92장
  - "어두운 신발 = 안전화" 편향 억제: boots-detection은 `not_safety_shoe` 포함 크롭은 전부, 안전화만 있는 크롭은
    **어두운 신발이 하나도 없는 것(갈색·노랑·유색 안전화)만** 넣고, train 전체 shoe_worn/shoe_not_worn 비율이 병합 전의 1.05배를 넘지 않게 제한
- `scripts/train_v4.py --imgsz 1280 --name safety_equipment_v4c_11s_1280` — 91 epoch에서 조기 종료(best 61 epoch, valid mAP50 0.802)
- v4c 가중치는 배포하지 않으므로 git에 올리지 않음 (로컬 `runs/train/safety_equipment_v4c_11s_1280/`에만 보관)

#### v4b vs v4c (mAP50 / mAP50-95, `runs/compare_v4.md`, `runs/compare_midrange.md`)
v4b와 v4c는 같은 v4 split으로 학습했으므로 v4 test의 모든 구간(컬러 PPE·그레이스케일 포함)이 둘 사이에서는 공정한 비교다.

| 구간 / 클래스 | v4b 11s/1280 (배포) | v4c +신발 |
|---|---|---|
| 자체 촬영 `shoe_not_worn` | 0.003 / 0.003 | 0.004 / 0.002 |
| 자체 촬영 `shoe_worn` | 0.821 / 0.620 | 0.840 / 0.597 |
| 자체 촬영 헬멧·조끼 4클래스 | 0.95~0.995 | 0.98~0.995 (mAP50-95는 4개 중 3개 하락, 최대 −0.04) |
| 자체 촬영 전체 | 0.789 / 0.586 | 0.802 / 0.576 |
| 컬러 PPE `helmet_worn` | **0.686** / 0.359 | 0.553 / 0.286 (**−0.133**) |
| 컬러 PPE `vest_worn` | **0.766** / 0.389 | 0.687 / 0.367 (**−0.079**) |
| 컬러 PPE 전체 | 0.492 / 0.237 | 0.462 / 0.218 |
| 그레이스케일 `shoe_not_worn` | 0.163 / 0.071 | 0.070 / 0.027 |
| v4 test 전체 | 0.616 / 0.390 | 0.603 / 0.374 |
| 중간거리 평균 (helmet / vest) | 0.622 (0.834 / 0.409) | **0.678** (0.855 / 0.502) |
| 중간거리 conf 0.4 helmet R · vest P | 0.73 · 0.62 | 0.75 · 0.69 (미착용 오탐 둘 다 0건) |

자체 촬영 test GT 신발 박스별 예측 (conf ≥ 0.25, IoU ≥ 0.3):

| GT | v4b | v4c |
|---|---|---|
| `no_shoe` 검은 운동화 신은 사람 (shoe_not_worn 132) | worn 121 / 미검출 11 / **not_worn 0** | worn 122 / 미검출 10 / **not_worn 0** |
| `no_vest` 바닥에 벗어 둔 신발 (shoe_not_worn 104) | worn 4 / 미검출 100 | worn 6 / 미검출 98 |
| 안전화 착용 (shoe_worn 378) | worn 371 / 미검출 7 | worn 374 / 미검출 4 |

#### 결론 — v4c 미채택, 배포 모델은 v4b 유지
- **목적(`shoe_not_worn`) 달성 실패**: 검은 운동화 132개 중 `shoe_not_worn` 예측 0개, conf 0.001까지 내려도 매칭되는 예측이 없다. v4c도 검은 운동화를 여전히 `shoe_worn`으로 낸다
  (샘플 이미지 기준 conf 0.7~0.9, v4b보다 점수만 약간 낮아짐, 예: 0.85→0.74). 공개 데이터에는 '착용 상태의 검은 일반 신발'이 없어 이 혼동을 깨지 못한다.
- **컬러 PPE 헬멧·조끼 하락**: helmet_worn −0.133, vest_worn −0.079. 자체 촬영 외의 실제 현장 사진에서 착용 장비를 덜 잡는다는 뜻이라 무시하기 어렵다.
- **중간거리 개선(+0.056)은 신발 데이터 효과로 보기 어렵다**: 추가한 153장은 헬멧·조끼·드론 시점이 없는 발 크롭이다.
  학습 1회씩의 비교라 시드에 따른 변동과 구분할 수 없고, 같은 크기의 변동이 컬러 PPE에서는 반대 방향으로 나왔다.
- 중간거리(드론)만 쓰는 배포라면 v4c가 유리할 수 있으나, 확인하려면 v4b·v4c를 시드를 바꿔 2~3회씩 다시 학습해 변동 폭부터 재야 한다.
