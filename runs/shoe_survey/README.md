# 일반 신발(특히 검은색) 공개 데이터셋 조사 — shoe_not_worn 보강용

조사일 2026-10-03. 다운로드 위치 `datasets/external/shoes/` (Roboflow YOLOv11 export, 모두 CC BY 4.0).
필터링/통계 재현: `python scripts\survey_shoe_datasets.py` → `filter_result.txt`. 이 폴더의 `*.jpg`는 클래스별 박스 크롭 샘플.

## 1. 후보 조사 (Roboflow Universe 검색: safety shoes / no safety shoes / not_safety_shoe / sneakers / normal_shoe)

| 데이터셋 | 이미지 | 클래스 | 판단 |
|---|---|---|---|
| **boots-detection** (Marketwise, Nedrick Chandra 'Safety Shoes Detection'의 포크) | 1,693 | safety_shoe, Safety-shoes, not_safety_shoe, person | 받음. 원본(Nedrick)은 모든 버전이 160x160 + 회전 증강이라 못 씀 → 같은 이미지의 512x512 무증강 포크로 대체 |
| **Safety Shoes detection** (University of Patras) | 134 (v2 export 358) | safe_boots, not_safety | 받음 |
| **safety shoes** (Darshanas) | 313 | safety-shoes, casual shoes, skets, flip flop, slippers, SANDEL, heels (폴리곤) | 받음 |
| **no-shoes-workers** (duc) | 475 (v1 export 345) | no_shoes, shoes, no_glove … (Sport Shoes/Flats 등은 export 버전에 없음) | 받음 |
| Shoes/no-shoes (project-ibvat) | 1,030 | Safety Shoes / NO-Safety Shoes + Hardhat/Vest | 삭제됨/비공개 (Project Not Found) |
| ppe_grade_d (Vidya) | 13.8k | safety_shoe / no_safety_shoe / shoe_cover + 위생복 | 제약/클린룸 위생복 도메인이라 제외 |
| safety-shoes (bns218) | 10.8k | 클래스 '0' 하나 | 안전화 양성만, 미착용 없음 → 제외 |
| Sneakers (DS06) 외 sneaker 계열 | ~1k | sneaker | 상품 사진 위주, 사람 발 아님 → 제외 |
| KYT (no shoes) | 779 | Helmet, Vest | 이름과 달리 신발 라벨 없음 → 제외 |

## 2. 원본 상태 (육안 + 통계)

| 데이터셋 | 시점/장면 | 문제 |
|---|---|---|
| boots-detection | 현장 작업자 하반신·발 근접, 다양한 현장. 안전화(장화·작업화) 매우 다양 | 1,693장 중 788장이 증강 복사본(노이즈/회전/흑백), 199개 원본이 split 간 누수. **not_safety_shoe가 35박스뿐** (슬리퍼·운동화·샌들) |
| Patras | **고정 CCTV, 약간 위에서 본 보행자 하반신** — 검은 안전화 vs 남색/검은 운동화·샌들. 우리 문제와 가장 유사 | 카메라 1대, 원본 116프레임뿐. 37% 프레임에 녹색 박스가 화면에 구워져 있음. not_safety 라벨 일부 오류(검은 작업화가 not_safety로) |
| Darshanas | 대부분 **상품 사진**(흰 배경 신발 단독) + 일부 사무실 바닥 구두 | 발에 신은 장면이 드묾. safety-shoes 라벨에 검은 운동화 섞임 |
| no-shoes-workers | 공장 CCTV 1개, **맨발 1명** 연속 프레임 | 345장 중 aHash 고유 75장. 'shoes'는 바닥에 벗어둔 신발(착용 아님) → 매핑 금지 |

## 3. 필터링 규칙 (Worksite 때와 같은 취지)

1. 중복 제거: Roboflow 증강 복사본은 원본당 1장(valid/test 비증강본 우선) → aHash 동일 이미지 1장
2. 매핑: 안전화 → shoe_worn, 일반신발·슬리퍼·샌들·맨발 → shoe_not_worn, 나머지(person, 'shoes'(벗어둔 신발), 장갑/마스크 등) 제거
3. **발 크롭 + 깨끗한 크롭만**: 신발 박스 외접 영역을 위 1.0x·좌우 0.5x 넓혀 자르고, 현재 배포 모델(3차)이 크롭 안에서 헬멧/조끼를 conf≥0.5로 잡으면 제외
   (이 데이터셋들엔 헬멧/조끼 라벨이 없어서 그대로 넣으면 헬멧/조끼를 배경으로 학습함)
4. Patras 녹색 박스 구워진 프레임 제외, 짧은 변 12px 미만 박스 제외

## 4. 필터링 결과

| 데이터셋 | 원본 → 증강복사 제거 → 동일해시 → 기타 제외 → **최종 크롭** | shoe_worn 박스 | shoe_not_worn 박스 | not_worn 중 어두운 색 |
|---|---|---|---|---|
| boots-detection | 1,693 → −788 → 0 → 헬멧/조끼 −57, 소형 −1 → **847** | 2,032 | **35** | 12 |
| Patras | 358 → −242 → 0 → 녹색박스 −44, 헬멧/조끼 −11 → **61** | 169 | **37** | 14 (+남색 13) |
| Darshanas | 313 → −75 → −32 → 라벨없음 −4, 헬멧/조끼 −45*, 소형 −2 → **155** | 42 | 198 (상품 사진) | 39 |
| no-shoes-workers | 345 → −11 → −261 → −2 → **71** | 0 | 110 (맨발, 1명) | — |
| **합계** | **1,134** | **2,243** | **380** (착용 장면 72) | — |

\* Darshanas 상품 사진에서 3차 모델이 헬멧/조끼를 오탐해서 빠진 것 (실제로 헬멧이 보이는 건 아님).
색 분류는 박스 중앙부 HSV 중앙값 기준 대략치.

참고: 현재 v4 train의 shoe_not_worn은 468장 / 798박스(자체 촬영 333장).

## 5. 결론 / 제안

- **공개 데이터로는 '검은 운동화 착용' 예시를 거의 못 얻는다.** 착용 장면의 shoe_not_worn은 boots-detection 35 + Patras 37 = 72박스이고 그중 어두운 색은 ~40개.
  Darshanas 198박스는 상품 사진이라 발에 신은 모습과 도메인이 다르다.
- 반대로 shoe_worn(안전화)은 2,200박스가 늘고 그 절반이 검은색이다. 그대로 다 넣으면 **'검은 신발 = 안전화' 편향이 더 강해질 위험**이 있다
  (지금 문제가 바로 검은 일반 신발을 shoe_worn으로 보는 것).
- 제안:
  1. Patras(61크롭) + boots-detection의 **not_safety_shoe 포함 이미지 18장 전부** + boots-detection shoe_worn은 **검은색 비율을 낮춰 300~400크롭만 샘플링** → shoe_worn/not_worn 비율을 현재 수준으로 유지
  2. Darshanas는 casual shoes / skets(운동화)만 보조로 쓰되 비중을 작게 (상품 사진 도메인)
  3. no-shoes-workers(맨발)은 우리 시나리오(작업화 대신 운동화)와 달라 **보류**
  4. **근본 해결은 자체 촬영**: 검은/남색 운동화, 검은 구두, 검은 안전화를 같은 사람·같은 장소에서 번갈아 신고 찍는 대조 촬영
     (안전화의 토캡 돌출·두꺼운 밑창·발목 높이를 모델이 구분 근거로 쓰게 하려면 색 외에는 같은 조건의 쌍이 가장 효과적)
- 병합은 아직 안 했다 (승인 후 `rebuild_dataset_v4.py`에 추가 예정).
