# 테스트 리포트 — drone dispatch MVP (2026-10-08)

## 요약

| 항목 | 결과 |
|---|---|
| 자동 시나리오 (pytest, mock FC) | **22/22 통과** (변경 이력 2 이후) — Python 3.11.9, Python 3.10.21 + PyYAML 5.4.1 각각. 최초 19/19는 3.11에서 4회 반복 모두 통과 |
| E2E (`python -m drone.server` 별도 프로세스 + `python -m drone.tests.mock_fc`, curl) | 통과: 401 → /status → dispatch(10 m, alt_rel 12) → arrived(수평오차 0.01 m, 고도 12.0 m, 2.9 s) → abort |
| PX4 SITL | **사용 못 함** (아래 사유) |
| 실기체 | **미검증** (전 항목) |
| MAVLink 버전 | mock 기준 v2 확정(`proto=v2`), v1 전용 mock에서 v1 폴백 동작 확인. **실기체에서 어느 쪽으로 동작할지는 미검증** |

## 환경

| 구분 | 내용 |
|---|---|
| PC | Windows 11 Home 10.0.26200 (x64), AMD Ryzen 5 7500F, RTX 4060 Ti 8 GB (드라이버 591.86) |
| WSL2 | **미설치** (`wsl --status`: "Linux용 Windows 하위 시스템이 설치되어 있지 않습니다"), `HypervisorPresent=False` |
| Docker | 없음 |
| Python | 3.11.9 (개발 venv `drone/.venv`), 3.10.21 (uv로 만든 검증용 venv, PyYAML 5.4.1 순수 파이썬 구현) |
| 패키지 | pymavlink 2.4.50, pyserial 3.5, fastapi 0.142.4, starlette 1.7.0, pydantic 2.13.5, uvicorn 0.54.0, pytest 9.1.1, httpx 0.28.1 |
| 대상 | **mock FC** (`drone/tests/mock_fc.py`, UDP 루프백) |

## SITL을 쓰지 못한 사유 (소요 약 5분)

1. PX4 v1.16 공식 문서의 Windows 개발 환경은 **WSL2 기반**이 정식 경로이고, Cygwin 툴체인은 "Community Supported"로 분류.
2. 이 PC는 WSL이 설치되어 있지 않고 하이퍼바이저도 꺼져 있음. WSL2를 설치하려면 관리자 권한 + Windows 기능 활성화 + **재부팅**이 필요 → 사용자 확인 없이 진행하기에는 시스템 변경 범위가 커서 시도하지 않음.
3. 따라서 지침대로 mock으로 진행. SITL 명령 자체(`make px4_sitl ...`)는 실행하지 않았으므로 문서의 정확한 명령을 여기 적지 않는다.

→ WSL2 설치를 허락하면 그 뒤에 SITL 검증을 별도로 진행할 수 있다(시간 상한 60분 기준).

## 시나리오별 결과

환경 표기: **M** = mock FC (Python 3.11.9·3.10.21 둘 다), **S** = SITL, **R** = 실기체

| # | 시나리오 | 테스트 | M | S | R | 확인 내용 |
|---|---|---|---|---|---|---|
| 1 | 정상 이동 | `test_dispatch_normal` | 통과 | 미검증 | 미검증 | 200 + ACK ACCEPTED, 실제 송신 프레임: COMMAND_INT, src (1,191), target (1,1), frame 0, param1=2.0, param2=1, param4=NaN, x/y=degE7, **z=AMSL(홈 40 + 15 = 55)**, v2. 수평 <2 m 2 s 지속 후 arrived, 도달 상대고도 15±0.5 m |
| 2 | 반경 초과 거절 | `test_reject_radius` | 통과 | 미검증 | 미검증 | 홈에서 40 m → 409 `["radius_from_home"]`, FC로 명령 0건 |
| 3 | 고도 범위 밖 거절 | `test_reject_alt_range[2.0/25.0/nan]` | 통과 | – | 미검증 | 2 m, 25 m → 409 `["alt_range"]`; NaN → 422. 명령 0건 |
| 4 | GPS 불량 거절 | `test_reject_gps[4종]` | 통과 | – | 미검증 | 위성 5 → `gps_sats`, eph 300 → `gps_hdop`, fix 2 → `gps_fix`, eph 65535(미상) → `gps_hdop`. 명령 0건 |
| 5 | 모드가 Hold 아님 거절 | `test_reject_mode_not_hold` | 통과 | 미검증 | 미검증 | Position에서 409 `["mode_hold"]`, override 래치 안 됨 |
| 5b | 지상(IN_AIR 아님) 거절 | `test_reject_not_in_air` | 통과 | – | 미검증 | 409 `["in_air"]` |
| 6 | 이동 중 모드 변경 → pilot_override | `test_pilot_override_during_move` | 통과 | 미검증 | 미검증 | moving 중 Position → 2 s 이내 pilot_override; dispatch/abort/reset(Position) 모두 409; Hold 복귀만으로는 해제 안 됨; Hold에서 /reset → idle; 래치 중 FC로 명령 0건 |
| 7 | abort | `test_abort` | 통과 | 미검증 | 미검증 | DO_SET_MODE (1,4,3) target (1,1) + DO_REPOSITION(NaN×3) 정지, 상태 aborted, mock 위치 고정 |
| 8 | 하트비트 소실 | `test_heartbeat_loss` | 통과 | – | 미검증 | 하트비트 중단 → link_ok=false(1.0 s 기준), dispatch 409 `["link_ok"]`, 재개 시 복구 |
| 9 | ACK 타임아웃 | `test_ack_timeout` | 통과 | – | 미검증 | 502 `["ack_timeout"]`, 응답 시간 1.9~3.0 s, 상태 failed |
| 10 | API 키 없는 요청 거절 | `test_api_key_required` | 통과 | – | 미검증 | 키 없음/틀림 → 401 (GET/POST 전부, 바디 오류보다 키 검사가 먼저), FC로 명령 0건 |
| 11 | v2→v1 폴백 | `test_v1_fallback` | 통과 | 미검증 | 미검증 | v2 프레임을 무시하는 mock → 3 s 후 v1 재요청 → `proto=v1`, dispatch ACK v1 |
| 12 | 상태/수신 주기 | `test_status_fields_and_rates` | 통과 | 미검증 | 미검증 | custom_mode 50593792 → main 4/sub 3/Hold; 실측 수신 주기 HB 1.8, GPI 5.0, GPS 1.8, SYS 1.0, ESS 1.8 Hz (5 s 창, 요청 2/5/2/1/2) |
| 13 | JSON 라인 로그 | `test_json_log_written` | 통과 | – | – | link_open, request_streams, proto_confirmed, http, dispatch_validate/send/ack, command_ack, dispatch_state 기록 |

## mock이 검증하지 못하는 것 (= 실기체/SITL에서 확인 필요)

mock은 **우리 서버 로직만 검증한다. PX4의 실제 수락 동작은 검증하지 못한다.** mock은 PX4 v1.16.0 소스를 읽고 흉내 낸 것이며, 아래는 모두 **미검증**:

| 항목 | 근거(소스 확인) | 상태 |
|---|---|---|
| DO_REPOSITION 고도 = AMSL (frame 무시) | `mavlink_receiver.cpp` COMMAND_INT에서 frame 미사용, `navigator_main.cpp`가 param7을 global alt 기준으로 사용 | 소스 확인, 실측 미검증 |
| param2 bit0 필요 (없으면 UNSUPPORTED) | `Commander.cpp` DO_REPOSITION case | 소스 확인, 실측 미검증 |
| compid 191 송신 명령이 수락되는지 | `evaluate_target_ok`: target sys = 자기 sysid, comp = 자기 compid 또는 0. 같은 sys/comp에서 온 명령만 거부 → 1/191은 통과 예상 | **추정** |
| DO_SET_MODE ACK | receiver가 기본 ACCEPTED ACK를 보내고 commander도 응답할 수 있음 → 첫 ACK가 실제 모드 전환 결과가 아닐 수 있음. abort 응답의 `mode_now`와 /status로 확인 | 미검증 |
| 이미 Hold인데 DO_SET_MODE(Hold)만으로 reposition이 멈추는지 | 같은 모드 재진입은 navigator 재활성화가 안 될 수 있어 NaN DO_REPOSITION(정지, navigator 소스의 "pause vehicle" 분기)을 추가로 보냄 | 미검증 |
| HEARTBEAT 2 Hz 요청 반영 | PX4가 HEARTBEAT 스트림 주기 변경을 허용하는지 미확인 | 미검증 |
| 실제 MAVLink 버전 (MAV_PROTO_VER 자동 전환) | 이전 실측에서 수신이 v1. 우리가 v2를 보내면 PX4가 v2로 바뀌는 게 기대 동작 | 미검증 |
| 57600 링크 실사용률 | 계산치: 요청 스트림 v2 453 B/s (7.9%), v1 349 B/s (6.1%). 기본 스트림 포함 실측은 `/status.rx_link` | 미검증 |
| 시리얼 `/dev/ttyTHS1` 실제 송수신 | Windows에서 COM 포트 없음 → 열기 실패 메시지만 확인 | 미검증 |

## 개발 중 발견·수정한 결함

1. NaN 고도 요청 시 500: 검증 응답 JSON에 NaN이 들어가 직렬화 실패 → 입력 단계에서 NaN/Inf 422 거절 + 422 응답에서 입력값 미반환.
2. Windows pymavlink `udpout`이 목적지 포트로 bind해서 루프백 테스트가 자기 패킷을 수신 → mock은 raw UDP 소켓 사용 (서버 코드에는 영향 없음).
3. PyYAML 5.4.1 sdist는 Windows/3.10에서 C 확장 빌드 실패(Cython 3 / 컴파일러 없음) → 순수 파이썬 lib3로 검증. Jetson은 venv에 PyYAML 6.0.3 aarch64 휠이 설치되며, 코드는 `safe_load`/`safe_dump`만 사용.

## 변경 이력

| # | 날짜 | 변경 | 테스트 |
|---|---|---|---|
| 1 | 2026-10-08 | 최초 구현 (서버, mock FC, 시나리오 19개, README, 체크리스트) | 19/19 통과 (3.11.9, 3.10.21) |
| 2 | 2026-10-08 | 후속 수정 (새 기능 없음): ① 시작 시 `override_requires_airborne != true` 또는 limits가 기본값과 다르면 콘솔에 `WARNING: NON-DEFAULT SAFETY CONFIG` 배너 출력 + `server_start` 로그에 기록, `/status`에 `config_flags`(override_requires_airborne, abort_also_pause, limits, limits_default, limits_changed) 노출 ② 체크리스트에 "비행 전 확인" P1~P4 (config_flags 확인) ③ "C. 첫 실비행 dispatch" 절차 (alt_rel = 현재 상대고도, 수평 ≤ 10 m, 수직 변화 > 3 m면 즉시 RC 개입, 전/후 relative_alt·GLOBAL_POSITION_INT.alt 기록 칸) ④ QGC 기록 칸에 GF_ACTION / GF_MAX_HOR_DIST / GF_MAX_VER_DIST / GF_SOURCE + 마지막 방어선 설명 ⑤ wheelhouse `drone/wheelhouse/` 생성(19개, 17 MB), README 첫머리에 경로·복사 방법, gitignore 유지 | **22/22 통과** (3.11.9, 3.10.21). 추가: `test_config_flags_default`, `test_config_flags_nondefault`, `test_server_start_prints_warning`(실제 `python -m drone.server` 프로세스 출력 확인) |

`limits`의 범위: `speed_mps`, `max_radius_from_home_m`, `alt_rel_min_m`, `alt_rel_max_m`, `gps_min_fix`, `gps_min_sats`, `gps_max_hdop`, `arrival_radius_m`, `arrival_hold_s` (사전검증·도착 판정 값). 타임아웃류(`heartbeat_timeout_s` 등)는 경고 대상이 아니다.
