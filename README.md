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
- [ ] 추가 촬영 및 재학습 (중간점검 이후 진행 예정)

## 향후 계획
1. `datasets/raw_images`에 현장 이미지 수집
2. 안전모/안전조끼/안전벨트 착용·미착용 클래스로 라벨링 (`datasets/labels`)
3. `datasets/data.yaml` 기준으로 YOLOv8 커스텀 학습 (`yolo train`)
4. 학습된 커스텀 모델을 `detect_webcam.py`에 연결하여 실시간 안전장비 인식으로 확장

## 폴더 구조
```
EXPO/
├── venv/                  # 가상환경 (git 제외)
├── scripts/
│   └── detect_webcam.py   # 웹캠 실시간 인식 스크립트
├── models/
│   └── yolov8n.pt          # YOLOv8n 사전학습 가중치
├── datasets/
│   ├── raw_images/        # 원본 이미지 (git 제외)
│   ├── labels/            # 라벨 파일
│   ├── images/train, val/ # 학습/검증 이미지
│   └── data.yaml          # 커스텀 학습용 데이터셋 정의
├── runs/                  # 학습/추론 결과 (git 제외)
├── requirements.txt
└── .gitignore
```

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

### 3. 웹캠 실시간 인식 실행
> 새 터미널을 열었다면 먼저 가상환경을 다시 활성화해야 합니다. (프롬프트 앞에 `(venv)`가 표시되는지 확인)
> ```powershell
> cd C:\EXPO
> .\venv\Scripts\Activate.ps1
> ```

```powershell
# COCO 80개 클래스 전체 인식
python scripts\detect_webcam.py

# 사람(person) 클래스만 인식
python scripts\detect_webcam.py --person-only

# 카메라 인덱스 / confidence threshold 지정
python scripts\detect_webcam.py --person-only --camera 0 --conf 0.5
```
종료: 웹캠 창이 활성화된 상태에서 `q` 키 입력

## 사용 모델
- 현재: `yolov8n.pt` (COCO 사전학습, person 클래스 포함 80개 클래스)
- 커스텀 학습 결과: `runs/train/safety_equipment-2/weights/best.pt` (안전장비 착용 여부 6개 클래스, 성능은 아래 참고)

## 학습 결과 및 한계점

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
