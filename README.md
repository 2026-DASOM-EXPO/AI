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
- [ ] 안전장비(헬멧/조끼/벨트) 착용 여부 데이터셋 수집 및 라벨링
- [ ] 커스텀 모델 학습 및 배포

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
- 향후: 안전장비 착용 여부 6개 클래스로 커스텀 학습된 YOLOv8 모델
