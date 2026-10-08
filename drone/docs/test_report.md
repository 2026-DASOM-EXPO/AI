# 테스트 리포트 — drone dispatch MVP (2026-10-08)

## 요약

| 항목 | 결과 |
|---|---|
| 자동 시나리오 (pytest, mock FC) | **22/22 통과** (변경 이력 3 이후) — Python 3.11.9 (Windows), Python 3.10.12 (WSL Ubuntu 22.04). 이력 2 시점에도 22/22 (3.11.9, 3.10.21 + PyYAML 5.4.1) |
| E2E (`python -m drone.server` 별도 프로세스 + `python -m drone.tests.mock_fc`, curl) | 통과: 401 → /status → dispatch(10 m, alt_rel 12) → arrived(수평오차 0.01 m, 고도 12.0 m, 2.9 s) → abort |
| PX4 SITL | **7항목 통과 (2026-10-08 오후 SITL 검증 절, WSL2 + PX4 v1.16.0 SIH)**. 이 과정에서 서버 결함 2건 발견·수정(변경 이력 3). 아래 "SITL을 쓰지 못한 사유"는 오전 기록 |
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
| 3 | 2026-10-08 | SITL 검증에서 발견한 버그 수정 (새 기능 없음): ① 구간 측정 `time.time()` → `time.monotonic()` (`link.py` 8곳, `controller.py` 3곳, `server.py` 2곳) ② `heartbeat_timeout_s` 기본 1.0 → 1.5 (`config.py`, `config.example.yaml`), README `link_ok` 행·5절 문구, 체크리스트 A6 문구. 근거: 아래 "SITL 검증" 절 | **22/22 통과** (3.11.9 Windows, 3.10.12 WSL). SITL 재확인: link_lost 0회, C절·abort 재통과 |

`limits`의 범위: `speed_mps`, `max_radius_from_home_m`, `alt_rel_min_m`, `alt_rel_max_m`, `gps_min_fix`, `gps_min_sats`, `gps_max_hdop`, `arrival_radius_m`, `arrival_hold_s` (사전검증·도착 판정 값). 타임아웃류(`heartbeat_timeout_s` 등)는 경고 대상이 아니다.

## SITL 검증 (2026-10-08 11:05~11:27, WSL2 + PX4 v1.16.0 SIH)

### 환경

| 구분 | 내용 |
|---|---|
| WSL | WSL 3.0.1.0, 커널 6.18.40.1-1, Ubuntu 22.04.5 LTS (root), Python 3.10.12 |
| PX4 | `v1.16.0` shallow clone, `Tools/setup/ubuntu.sh --no-nuttx --no-sim-tools`, `make px4_sitl sihsim_quadx` (headless SIH, airframe 10040). shallow clone이라 NuttX 태그가 없어 `px_update_git_header.py`가 실패 → `platforms/nuttx/NuttX/nuttx`에서 `git fetch --depth 50 --tags` 후 빌드 성공 |
| 홈 | `PX4_HOME_LAT=37.5665 PX4_HOME_LON=126.9780 PX4_HOME_ALT=47.0` |
| 서버 | WSL `~/drone_venv` (requirements.txt), `--config`로 `connection: udpin:0.0.0.0:14540` (PX4 onboard 링크 14580→14540), sysid 1 / compid 191, 나머지 기본값 |
| 독립 관찰자 | `observer.py`: PX4 GCS 링크(18570→14550)에서 HEARTBEAT/GLOBAL_POSITION_INT/COMMAND_ACK/STATUSTEXT를 타임스탬프와 기록(`obs.jsonl`). 서버와 다른 링크라 서버 판단과 독립된 근거 |
| 이륙 | SITL 전용으로 pxh 클라이언트 `px4-param set MIS_TAKEOFF_ALT 10`, `px4-commander takeoff` (서버에는 이륙 기능 없음, 추가 안 함) |
| SITL 파라미터 | `MAV_PROTO_VER=2`, `COM_RC_IN_MODE=1`, GPS fix 3 / 위성 10 / eph 70(hdop 0.7) |
| 증거 | `drone/logs/sitl_20261008/` (gitignore 대상): 서버 JSONL(`logs/` 수정 전, `logs_nopause/`, `logs_fixed/` 수정 후), `obs.jsonl`, `px4.log`, 각 시험의 `*_before/_dispatch/_abort/_after.json`, `t4_probe.jsonl`, 실행 스크립트 전부 |

### 사전 확인: 홈 AMSL ≠ 0 — 통과

- `HOME_POSITION.altitude` = **47.413 m** (obs.jsonl 첫 HOME_POSITION)
- 지상 `GLOBAL_POSITION_INT`: alt 47.084, relative_alt −0.329 → alt − relative_alt = **47.413 m**
- 비행 중 서버 `home_ref_amsl`(= GPI.alt − relative_alt) = **46.915 m**. HOME_POSITION(47.413)과 **0.50 m 차이**. 비행 중 PX4의 relative_alt 기준은 HOME_POSITION.altitude가 아니라 이 값이므로, 서버가 HOME_POSITION 대신 GPI로 기준을 잡는 설계가 맞다(HOME_POSITION을 썼다면 0.5 m 오차).

### 7항목 결과

| # | 항목 | 판정 | 근거 (로그) |
|---|---|---|---|
| 1 | DO_REPOSITION(param2=1), compid 191 수락/ACK | **통과** | `link_open source [1,191]`. COMMAND_INT DO_REPOSITION 13회(dispatch 10 + abort 정지 3) 전부 `command_ack 192 ACCEPTED target [1,191] frame v2`, 응답 8~17 ms. `px4.log`에 `Ignore command` 0건 |
| 2 | alt_rel→AMSL 변환 후 실제 relative_alt (2개 이상) | **통과** (주의 1건) | 아래 표. z_amsl = 46.915 + alt_rel 정확. 안정 후 오차 ≤ 0.13 m. 단 `arrived` 시점 기록값은 수직이 아직 수렴 중이라 −0.64 / +1.03 m까지 나옴(도착 판정이 수평 기준이기 때문, 설계대로) |
| 3 | /abort 후 정지 (NaN 포함/제외) | **포함: 통과 / 제외: 정지 안 함** | 아래 표. NaN DO_REPOSITION 없이 DO_SET_MODE(Hold)만 보내면 ACK ACCEPTED인데도 기체가 목표까지 계속 감 → `abort_also_pause: true`(기본값) 필수 |
| 4 | DO_SET_MODE ACK와 실제 모드 전환 시점 | **확인됨: ACK ≠ 전환** | 아래 표. Position 요청은 ACK ACCEPTED(4 ms)인데 8 s 동안 모드 안 바뀜. 서버 abort의 DO_SET_MODE는 ACK가 **2개**(+3~6 ms, +12~15 ms 둘 다 ACCEPTED, abort 4회 모두)이고 서버는 첫 번째를 사용 |
| 5 | 하트비트 실제 수신 주기, custom_mode 디코딩 | **통과** (결함 1건 발견→수정) | HEARTBEAT **1.0 Hz 고정**: 관찰자 간격 1.010~1.043 s, 서버 `rx_rates_hz.HEARTBEAT` 1.0(5 s 창 경계에서 0.8). `SET_MESSAGE_INTERVAL(HEARTBEAT, 2 Hz)` → **FAILED** (128회 전부), 다른 4개 스트림은 ACCEPTED. custom_mode 50593792 → main 4 / sub 3 / `AUTO_LOITER` / Hold, 84148224 → 4/5 Return. 1.0 s 타임아웃에서 link_ok가 매초 깜빡임 → 수정(변경 이력 3) |
| 6 | MAVLink v1/v2 | **v2 통과, v1 폴백은 SITL에서 재현 불가** | 서버: `proto_confirmed proto v2 rx_frame v2`, 모든 ACK frame v2. 프로브가 `force_mavlink1`로 보낸 DO_SET_MODE(Hold)는 수락되고 모드 전환(0.044 s), **ACK는 v2로 옴**(SITL `MAV_PROTO_VER=2`). 따라서 "v2 요청 무응답 → v1 폴백" 경로는 SITL에서 발생하지 않아 미검증(mock에서만 검증) |
| 7 | 체크리스트 C절 재현 (alt_rel = 현재 상대고도) | **통과** (수정 전/후 각 1회) | 아래 표. 이동 중 최대 수직 변화 0.19 m / 0.18 m (기준 3 m) |

**6번 주의**: SITL은 **UDP**이고 서버도 `udpin`으로 붙는다. 시리얼(`/dev/ttyTHS1` 57600)과는 다르다: 바이트 손실/프레이밍 오류 없음, 대역폭 제한 없음(수신 23.5 KB/s — 57600 링크 용량 5.76 KB/s의 4배. PX4 onboard 링크가 4 MB/s 설정이라), `MAV_PROTO_VER`도 실기체 설정과 다를 수 있음. 실기체의 v1/v2 동작, 링크 점유율, 시리얼 송수신은 여전히 **미검증**.

#### 2·7. 고도 (서버 응답 `sent_detail`, `dispatch.result`, 관찰자 GPI)

| 시험 | 요청 alt_rel | z_amsl 송신 | home_ref | 시작 rel | arrived 시 rel (alt_err) | 안정 후 rel | 수평오차 | 이동 중 최대 수직 변화 |
|---|---|---|---|---|---|---|---|---|
| t7 (C절) | 9.9 (현재값) | 56.815 | 46.915 | 9.869 | 10.00 (+0.10) | 9.93 | 0.52 m | **0.19 m** |
| t2a | 15.0 | 61.915 | 46.915 | 9.903 | 14.36 (−0.64) | 14.42 (0.25 s 후 다음 시험 시작, 미안정) | 0.59 m | – |
| t2b | 5.0 | 51.915 | 46.915 | 14.421 | 5.36 (+0.36) | 4.88 | 0.77 m | – |
| t2c (30 m에서 하강) | 15.0 | 61.915 | 46.915 | 30.059 | 16.03 (+1.03) | **14.87~15.12** (arrived+12~17 s) | 0.53 m | – |
| t7_fixed (C절, 수정 후) | 15.2 (현재값) | 62.115 | 46.915 | 15.148 | 15.31 (+0.11) | 15.29 | 0.09 m | **0.18 m** |

C절 판정 기준(체크리스트): z_amsl ≈ C1 alt_amsl (t7: 56.815 vs 56.784, 차 0.03 m) 그리고 전/후 alt_rel 차 < 1 m (9.869 → 9.93) → 정상.

#### 3. abort (dispatch 후 4 s에 `/abort`, 관찰자 15 s)

| 시험 | 서버 설정 | ACK | abort 후 15 s 이동 | 목표까지 남은 거리 | 판정 |
|---|---|---|---|---|---|
| t3_pause | `abort_also_pause: true` (기본) | DO_SET_MODE ACCEPTED 8 ms, DO_REPOSITION(NaN, x/y=INT32_MAX) ACCEPTED 18 ms | **1.72 m** (1.5 s 안에 1.36 m 감속 후 정지, 끝 속도 0.04 m/s) | 12.97 m | 정지 |
| t3_nopause | `abort_also_pause: false` | DO_SET_MODE ACCEPTED 8 ms | **7.95 m** (1.5 s 후에도 1.72 m/s) | **0.21 m** (목표 도달) | **정지 안 함** |
| t3_fixed2 | 기본, 수정 후 서버 | 둘 다 ACCEPTED (12 / 17 ms) | 1.60 m | 16.21 m | 정지 |

- 이미 Hold(AUTO_LOITER)인 상태에서 Hold 재설정은 진행 중인 reposition을 취소하지 않는다(소스 추정이 SITL로 확인됨).
- nopause 설정에서도 서버는 `ok: true, state: aborted`를 반환했다. 즉 **`abort_also_pause: false`로 운용하면 서버 응답이 실제 정지를 의미하지 않는다.** 기본값 true 유지, false로 바꾸지 말 것(코드는 변경하지 않음 — 응답 의미 변경은 새 기능 범위).
- PX4 소스 확인: `mavlink_receiver.cpp`는 COMMAND_INT x=y=INT32_MAX를 param5/6 = NaN으로 바꾼다 → 서버의 정지 명령 인코딩이 맞다.
- t3_fixed(첫 시도)는 기체가 이미 목표 1.71 m 앞이라 무효, 서쪽으로 22 m 옮긴 뒤 t3_fixed2로 다시 함.

#### 4. DO_SET_MODE ACK vs 실제 모드 (프로브 `probe.py`, onboard 링크 14280→14030, sysid 1 / compid 192)

| 요청 | ACK (요청 후) | HEARTBEAT에서 모드 확인 (요청 후) | 비고 |
|---|---|---|---|
| Position (1,3,0) | ACCEPTED, 4 ms | **8 s 동안 안 바뀜** | RC 없는 SITL. PX4 로그에 거절 메시지 없음 |
| Hold (1,4,3) | ACCEPTED, 4 ms | 이미 Hold | |
| Return (1,4,5) | ACCEPTED, 0 ms | 프로브 링크 0.589 s, 서버 링크 0.584 s, GCS 링크 0.507 s | 서버가 `pilot_override` 래치(`was idle, armed True, landed_state 2`) — SITL에서 RC 우선 로직 동작 확인. 이후 Hold에서 `/reset` → idle |
| Hold, **v1 프레임** (1,4,3) | ACCEPTED, 3 ms (ACK는 v2) | 프로브 링크 0.044 s, 서버 링크 0.040 s, GCS 링크 0.985 s | |

→ **ACK ACCEPTED는 모드 전환의 증거가 아니다.** 실제 전환은 ACK 뒤 0.04~1.0 s(링크별 1 Hz 하트비트 위상)에 HEARTBEAT로만 확인된다. 서버 abort 응답의 `mode_now`는 ACK 직후 값이므로 전환 확인용이 아니다. 현장에서는 abort 후 1.5 s 이상 지난 `/status.mode`로 확인할 것.

### 발견한 결함과 수정 (서버 코드는 버그 수정만, 변경 이력 3)

1. **구간 측정에 벽시계(`time.time()`) 사용** — WSL 시계가 약 31 s마다 −1.2~−1.8 s 역행(관찰자 로그 10.5분 동안 20회). 그 결과 `/status.heartbeat_age_s = -0.68`, 하트비트 간격이 음수로 계산됨. link_ok, position_fresh, 도착 유지 시간, 도착 제한시간이 모두 영향을 받음. Jetson은 RTC 배터리가 없으면 부팅 후 NTP 동기화 때 시계가 크게 점프하므로, 역행하면 실제 링크 끊김 뒤에도 그 점프 폭만큼 link_ok가 true로 남고, 전진하면 거짓 arrival_timeout이 날 수 있음. → `link.py`, `controller.py`, `server.py`의 구간 계산을 `time.monotonic()`으로(로그 `ts`는 벽시계 유지).
2. **`heartbeat_timeout_s` 기본 1.0 s** — PX4가 HEARTBEAT 2 Hz 요청을 FAILED로 거절하고 1.02 s 간격으로 보냄 → 수정 전 서버는 약 2분간 `link_lost`/`link_up` 127회, `link_up`마다 SET_MESSAGE_INTERVAL 5개 재전송(128회). 그 순간에 들어온 dispatch는 `link_ok`로 409. → 기본값 1.5 s (`config.py`, `config.example.yaml`, README, 체크리스트 A6 문구).

수정 후 SITL 재확인(`logs_fixed/`): 40 s 동안 `/status` 80회, heartbeat_age 0.01~1.01 s(음수 0), link_ok 전부 true, 시계 역행 2회를 포함해 `link_lost` **0회**, `request_streams` 1회. C절 재현(t7_fixed)과 abort(t3_fixed2) 다시 통과.

### SITL로도 검증되지 않은 것

- 시리얼 57600 링크(대역폭, 프레이밍, v1 폴백, 실기체 `MAV_PROTO_VER`), QGC와 동시 접속, 실제 RC 조종사 개입(SITL에서는 Return 모드 전환으로 대신함), 실제 GPS/기압계 오차, 바람.
- Position 모드 전환이 ACK ACCEPTED 후 적용되지 않은 원인(RC 없음으로 추정, PX4 로그에 메시지 없음).
