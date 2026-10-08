# 현장 체크리스트

> 서버는 PX4 파라미터를 **변경하지 않는다**. 아래 failsafe 값은 사람이 QGC에서 읽어 기록한다.

## 0. QGC 확인 기록 (사람이 기입)

| 파라미터 | 의미 | 확인 값 | 확인자/시각 |
|---|---|---|---|
| `NAV_RCL_ACT` | RC 신호 상실 시 동작 (0 Disabled, 1 Hold, 2 Return, 3 Land, 5 Terminate, 6 Lockdown) | | |
| `COM_RC_LOSS_T` | RC 상실 판정 시간(s) | | |
| `NAV_DLL_ACT` | 데이터링크(GCS) 상실 시 동작 (0 Disabled, 1 Hold, 2 Return, 3 Land, 5 Terminate, 6 Lockdown) | | |
| `COM_DL_LOSS_T` | 데이터링크 상실 판정 시간(s) | | |
| `MAV_1_CONFIG` / `MAV_2_CONFIG` | Jetson이 붙은 TELEM 포트 인스턴스 | | |
| 해당 포트 `MAV_x_MODE` / `MAV_x_RATE` / `SER_TELx_BAUD` | 기본 스트림 모드 / 전송률 상한 / 57600 확인 | | |
| `MAV_PROTO_VER` | 0=auto(v1 시작, v2 수신 시 전환) 예상 | | |
| `MAV_SYS_ID` | 1 이어야 함(서버 target_system) | | |
| `GF_ACTION` | 지오펜스 위반 시 동작 (0 None, 1 Warning, 2 Hold, 3 Return, 4 Terminate, 5 Land) | | |
| `GF_MAX_HOR_DIST` | 홈 기준 최대 수평거리(m), 0=비활성 | | |
| `GF_MAX_VER_DIST` | 홈 기준 최대 고도(m), 0=비활성 | | |
| `GF_SOURCE` | 지오펜스 위치 소스 (0 Global position, 1 GPS) | | |

지오펜스는 서버 사전검증(반경 30 m, 고도 3~20 m)이 소프트웨어 오류로 뚫렸을 때 FC가 스스로 막는 **마지막 방어선**이다. 값은 사람이 현장에서 정하며 서버 코드는 이 파라미터를 읽거나 바꾸지 않는다. (참고: PX4는 지오펜스 밖 DO_REPOSITION 목표를 "Reposition is outside geofence"로 무시한다 — navigator 소스 확인, 실측 미검증)

메모: 서버는 type=ONBOARD_CONTROLLER 하트비트를 1 Hz로 보낸다. PX4 1.16 `mavlink_receiver.cpp`는 type=GCS 하트비트 또는 같은 sysid 컴포넌트의 하트비트를 추적하는데, 우리 하트비트가 GCS 데이터링크(`NAV_DLL_ACT`) 판정에 포함되는지는 확인하지 못했다 — **미검증**. Jetson 서버를 껐을 때 QGC에 링크 경고가 뜨는지 프롭오프 상태에서 한 번 보고 기록할 것: ______

---

## A. 프롭 제거 상태 점검 (학교, 지상)

준비: 프롭 전부 제거, 배터리 연결, QGC 연결, Jetson-FC 시리얼 연결, GPS 안테나 하늘 보이게.

| # | 할 일 | 기대 결과 | 결과 |
|---|---|---|---|
| A1 | `sudo fuser -v /dev/ttyTHS1` | 출력 없음(점유 없음) | |
| A2 | `source ~/drone_venv/bin/activate && cd ~/EXPO && python -m drone.server` | 첫 실행이면 API 키 출력. 에러 없이 `Uvicorn running on http://0.0.0.0:8100` | |
| A3 | `curl -s http://<jetson>:8100/status` (키 없이) | **401** | |
| A4 | `curl -s -H "X-API-Key: $KEY" .../status` | `link_ok: true`, `heartbeat_age_s < 1` | |
| A5 | A4 응답의 `mavlink` | `proto`가 `v2` 또는 `v1` (어느 쪽인지 기록 → 보고) / `last_rx_frame` | proto=____ rx=____ |
| A6 | `rx_rates_hz` | GLOBAL_POSITION_INT≈5, GPS_RAW_INT≈2, SYS_STATUS≈1, EXTENDED_SYS_STATE≈2, HEARTBEAT≈1 (PX4가 2 Hz 요청 거절, SITL 실측. `heartbeat_timeout_s` 기본 1.5) | |
| A7 | `rx_link.utilization_pct` | < 50 | ____% |
| A8 | `mode`, `armed`, `in_air`, `gps`, `battery`, `home` | QGC 표시와 일치. 홈 `source: HOME_POSITION` | |
| A9 | 거절: 지상(disarmed) 상태에서 `/dispatch` (홈 근처 10 m, alt_rel 10) | 409, `reasons`에 `armed`, `in_air`, (Hold 아니면) `mode_hold`. **FC에 명령 미전송**(로그 `dispatch_validate`만, `dispatch_send` 없음) | |
| A10 | 거절: 홈에서 50 m 지점 | `radius_from_home` 포함 | |
| A11 | 거절: alt_rel 25, 1 | `alt_range` 포함 | |
| A12 | 거절: 헤더 없음 / 잘못된 키 | 401 | |
| A13 | 하트비트 소실: Jetson-FC TX/RX 선 중 FC→Jetson 선을 잠깐 분리 | 1 s 내 `link_ok: false`, `/dispatch` → `link_ok` 사유. 재연결 후 복귀, 로그 `link_lost`/`link_up` | |
| A14 | pilot_override (지상): `config.yaml`에 `dispatch.override_requires_airborne: false` 설정 후 서버 재시작 | | |
| A15 | QGC 또는 RC로 **Hold** 전환 (지상에서 Hold 진입은 GPS 필요). `/status` mode = Hold(4/3, custom_mode 50593792) | | |
| A16 | RC 스위치로 **Position** 전환 | 즉시 `dispatch.state: pilot_override`, 로그 `dispatch_state ... mode_left_hold` | |
| A17 | `/dispatch` → 409 `not_pilot_override`; `/abort` → 409; `/reset`(Position 상태) → 409 | | |
| A18 | RC로 Hold 복귀 → `/status`는 여전히 pilot_override → `/reset` → 200 `idle` | | |
| A19 | **`override_requires_airborne: true`로 되돌리고 서버 재시작** | | |
| A20 | `drone/logs/drone_*.jsonl` 확인 | http/검증/모드 변화 기록 존재 | |

---

## B. 현장 비행 순서

역할: 조종사(RC, 언제든 개입) / 운용자(curl) / 관찰자(QGC).
**조종사는 모드 스위치를 Position 위치에 손가락 대기. 이상하면 즉시 Position.**

### 비행 전 확인 (맨 먼저)

| # | 할 일 | 확인 |
|---|---|---|
| P1 | 서버 시작 콘솔에 `WARNING: NON-DEFAULT SAFETY CONFIG` 배너가 **없어야** 한다. 있으면 내용 확인 후 `drone/config.yaml` 수정·재시작 | |
| P2 | `/status`의 `config_flags.override_requires_airborne == true` (프롭오프 점검 A14에서 false로 바꿨다면 반드시 되돌림) | |
| P3 | `/status`의 `config_flags.limits`가 의도한 값인지: `max_radius_from_home_m` __, `alt_rel_min_m`/`alt_rel_max_m` __/__, `speed_mps` __, `gps_min_sats` __, `gps_max_hdop` __. 기본값과 다른 항목은 `limits_changed`에 표시됨 | |
| P4 | `config_flags.abort_also_pause == true` | |

### 비행 순서

| # | 할 일 | 확인 |
|---|---|---|
| B1 | A1~A8 재확인, 0번 표 값 기록 | |
| B2 | 조종사 RC로 arm → 이륙 (서버는 관여 안 함) | |
| B3 | Position 모드로 안정 호버 | `/status` armed true, in_air true |
| B4 | 고도 확보 (상대 5~10 m) | `position.alt_rel_m` |
| B5 | Hold 스위치 | mode Hold(4/3) |
| B6 | `/status`로 GPS(fix≥3, 위성≥8, hdop≤2.0), link_ok 확인 | |
| B7 | **첫 dispatch는 아래 C절 절차대로** (alt_rel = 현재 상대고도, 수평 ≤ 10 m) | 200, `ack.result: ACCEPTED`, `state: moving` |
| B8 | 이동 관찰 (2 m/s) | 수평 <2 m 2 s 지속 → `arrived`, `result.alt_err_m` 기록 |
| B9 | 고도 변경 dispatch (예: +3 m) | `result.alt_rel_m`가 요청값 근처 → **고도 기준(AMSL 변환) 실측 검증** |
| B10 | `/dispatch` 후 이동 중 `/abort` | 200, 기체가 그 자리에 정지, mode Hold 유지 |
| B11 | `/reset` → `/dispatch` 후 이동 중 조종사 RC로 Position | 즉시 `pilot_override`, 조종사 조종 정상 |
| B12 | 조종사 Hold 복귀 → `/reset` → idle | |
| B13 | 조종사 착륙/disarm (서버 관여 안 함) | |

중단 기준: ACK가 `ACCEPTED`가 아님, 이동 방향이 예상과 다름, 고도가 예상과 크게 다름(>2 m), `link_ok` 깜빡임 → 조종사 Position 전환 후 착륙, 로그 보존.

---

## C. 첫 실비행 dispatch (고도 변환 검증용)

목적: 서버가 상대고도를 AMSL로 바꿔 보내는 로직(`z = (GLOBAL_POSITION_INT.alt − relative_alt) + alt_rel`)이 실기체에서 맞는지, **수직 변화가 없어야 하는 조건**에서 확인한다. 이 확인 전에는 고도를 바꾸는 dispatch(B9)를 하지 않는다.

조건:
- `alt_rel` = 직전 `/status`의 `position.alt_rel_m`과 **같은 값**(소수 1자리 반올림).
- 목표는 현재 위치에서 **수평 10 m 이하**.
- **수직 변화가 3 m를 넘으면 즉시 조종사가 RC로 Position 전환** (서버 대기 없이). 이후 착륙, 로그 보존, 추가 dispatch 금지.

| # | 할 일 | 기록 |
|---|---|---|
| C1 | Hold 호버 안정 후 `/status` 저장 (`curl ... > before.json`) | `position.alt_rel_m` (relative_alt) = ______ m / `position.alt_amsl_m` (GLOBAL_POSITION_INT.alt) = ______ m |
| C2 | 목표 계산: 현재 위치에서 수평 ≤ 10 m, `alt_rel` = C1 값 | lat ______ lon ______ alt_rel ______ |
| C3 | `/dispatch` 응답 저장 | `ack.result` ______ / `sent_detail.z_amsl` ______ / `sent_detail.home_ref_amsl` ______ |
| C4 | 이동 중 관찰자가 QGC 고도 표시를 계속 읽음. 3 m 넘게 변하면 조종사 즉시 개입 | 최대 고도 변화 ______ m / 개입 여부 Y·N |
| C5 | `arrived` 후 `/status` 저장 (`after.json`) | `position.alt_rel_m` = ______ m / `position.alt_amsl_m` = ______ m / `dispatch.result.alt_err_m` = ______ |

판정:
- 정상: `z_amsl ≈ C1 alt_amsl` (차이 < 1 m) 이고 전/후 `alt_rel_m` 차이 < 1 m → AMSL 변환이 맞음. 이후 B9(고도 +3 m) 진행 가능.
- 비정상: `z_amsl`이 C1 alt_amsl과 크게 다르거나 기체가 상승/하강 → 중단, 로그(`drone/logs/*.jsonl`의 `dispatch_send`/`dispatch_ack`)와 C1~C5 기록 보존.
