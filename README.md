# EXPO - 산업 안전 통합 시스템 (YOLOv8 기반 객체 인식)

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
- [ ] 추가 촬영 및 재학습 (중간점검 이후 진행 예정)

## 향후 계획
1. `vest_not_worn` 클래스 표본 보강 (3차 학습 기준 mAP50 0.281로 가장 취약, 아래 [3차 학습](#3차-학습-외부-roboflow-공개-ppe-데이터셋-병합) 참고)
2. 촬영 인원 확대 후 추가 촬영 (`datasets/raw_images`) 및 재학습
3. 실제 배포 환경(웹캠 등)과 유사한 조건의 이미지 보강

## 폴더 구조
```
EXPO/
├── venv/                  # 가상환경 (git 제외)
├── scripts/
│   ├── detect_webcam.py           # 웹캠 실시간 인식 스크립트
│   ├── train_custom.py            # 커스텀 YOLOv8 학습 스크립트
│   ├── merge_external_datasets.py # 외부 Roboflow PPE 데이터셋 병합 스크립트
│   ├── resplit_by_person.py       # person 단위 train/valid/test 재분리
│   └── extract_frames.py          # 영상에서 프레임 추출
├── models/
│   └── yolov8n.pt          # YOLOv8n 사전학습 가중치 (COCO)
├── datasets/
│   ├── raw_images/        # 원본 촬영 이미지 (git 제외)
│   ├── raw_videos/        # 원본 촬영 영상 (git 제외)
│   ├── external/          # 외부 Roboflow 데이터셋 다운로드 스테이징 (git 제외, merge 스크립트가 소비)
│   ├── train/, valid/, test/  # 실제 학습에 쓰이는 images/labels (용량 문제로 git 제외, 로컬에만 존재)
│   └── data.yaml          # 커스텀 학습용 데이터셋 정의 (6클래스)
├── runs/
│   └── train/safety_equipment-3/  # 최종(3차) 학습 결과 — weights/best.pt, results.png, confusion_matrix.png만 git 추적, 나머지는 git 제외
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
# 기본값: 커스텀 안전장비 모델(runs/train/safety_equipment-3/weights/best.pt)로 인식
python scripts\detect_webcam.py

# 카메라 인덱스 / confidence threshold 지정
python scripts\detect_webcam.py --camera 0 --conf 0.5

# COCO 사전학습 모델(80개 클래스)로 실행하고 싶을 때
python scripts\detect_webcam.py --model models\yolov8n.pt
```
종료: 웹캠 창이 활성화된 상태에서 `q` 키 입력

## 사용 모델
- 기본값(`detect_webcam.py` 기본 실행): `runs/train/safety_equipment-3/weights/best.pt` (안전장비 착용 여부 6개 클래스, 성능은 아래 참고)
- `--model models\yolov8n.pt` 지정 시: COCO 사전학습 모델 (person 클래스 포함 80개 클래스)

## 학습 결과 및 한계점
> 1차·2차 학습 가중치는 저장소 용량 정리를 위해 삭제되었습니다 (1차는 처음부터 git 미추적, 2차는 `git rm`으로 추적 해제).
> **3차(`safety_equipment-3`)가 1,105장을 포함한 전체 병합 데이터(6,410장)로 COCO 베이스부터 재학습된 최종 모델이며,
> 정보 손실 없이 그 이전 데이터를 포함하므로 1·2차를 대체합니다.** 아래 1·2차 결과는 진행 과정 기록용으로만 남겨둠.

### 1차 학습 결과 (초기)
- mAP50: 0.974 (validation set)
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

### 3차 학습 (외부 Roboflow 공개 PPE 데이터셋 병합)

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
- 기본 배포 모델을 `runs/train/safety_equipment-3/weights/best.pt`로 교체함.
