# drone/ — PX4 dispatch MVP 서버

> **Jetson 오프라인 설치용 wheelhouse**: `C:\EXPO\drone\wheelhouse\` (aarch64 / cp310 휠 19개, 약 17 MB, 2026-10-08 생성).
> 용량 때문에 **git에 커밋하지 않는다**(`drone/.gitignore`의 `wheelhouse/`). 다시 만드는 명령은 1절 참고.
> 복사: USB로 저장소째 옮기거나, 네트워크가 되면 PC에서
> `scp -r C:\EXPO\drone\wheelhouse <user>@<jetson>:~/EXPO/drone/` → Jetson에서
> `~/drone_venv/bin/pip install --no-index --find-links ~/EXPO/drone/wheelhouse -r ~/EXPO/drone/requirements.txt`

이미 **조종사가 띄워 놓은** PX4 기체를 지정 좌표로 보내고(`DO_REPOSITION`) 상태를 조회하는 최소 HTTP 서버.
이륙/착륙/arm/disarm은 구현하지 않는다(조종사가 RC로 수행). 영상 추론(`scripts/`, `detect_stream.py`)과 **완전히 분리된 별도 프로세스·별도 venv**로 돈다.

| 항목 | 값 |
|---|---|
| 실행 | 저장소 루트에서 `python -m drone.server` |
| HTTP 포트 | **8100** (MediaMTX 8554/8889/8888/9997/8000/8001 회피, `config.yaml`의 `http.port`) |
| 인증 | 모든 요청에 `X-API-Key` 헤더. 키는 `drone/config.yaml`, 없으면 첫 실행 때 랜덤 생성 후 콘솔 출력 |
| FC 연결 | `/dev/ttyTHS1` 57600 baud, MAVLink v2 시도 → ACK 없으면 v1 폴백 |
| 송신 신원 | sysid 1 / compid 191(ONBOARD_COMPUTER). 255(GCS)는 QGC와 충돌하므로 금지 |
| 명령 대상 | target_system 1 / target_component 1 (0 사용 안 함) |
| 로그 | `drone/logs/drone_YYYYMMDD.jsonl` (요청/검증/송신/ACK/모드 변화 전부) |
| Python | 3.10 호환 (Jetson). 3.10.21 + PyYAML 5.4.1, 3.11.9 에서 테스트 |

## 1. Jetson 설치

```bash
# 영상 추론 환경과 분리된 전용 venv
python3 -m venv ~/drone_venv
source ~/drone_venv/bin/activate
pip install --upgrade pip
cd ~/EXPO                       # 저장소 루트
pip install -r drone/requirements.txt
```

`uvicorn[standard]`는 쓰지 않는다(uvloop/httptools 등 aarch64 소스 빌드 위험). 순수 `uvicorn`으로 충분하다.

### (선택) Jetson이 인터넷이 안 될 때: PC에서 wheelhouse 만들기

PC(Windows/Linux 무관)에서:

```bash
pip download -r drone/requirements.txt -d drone/wheelhouse \
  --platform manylinux2014_aarch64 --python-version 310 --implementation cp --only-binary=:all:
```

2026-10-08에 실제로 실행해 19개 휠 전부 받아짐(소스 빌드 0건: pymavlink, pydantic_core, lxml, fastcrc, pyyaml 모두 aarch64/cp310 바이너리 존재).
`drone/wheelhouse/`를 USB 등으로 Jetson에 복사한 뒤:

```bash
source ~/drone_venv/bin/activate
pip install --no-index --find-links drone/wheelhouse -r drone/requirements.txt
```

## 2. 시리얼 포트 점유 확인

```bash
sudo fuser -v /dev/ttyTHS1        # 출력이 비어 있어야 함
# 점유 중이면: nvgetty 콘솔 / mavlink-router / MAVProxy / 이전 서버 프로세스 등을 먼저 종료
#   sudo systemctl stop nvgetty   (해당되는 경우)
groups | grep dialout             # 없으면: sudo usermod -aG dialout $USER 후 재로그인
```

포트를 열지 못하면 서버는 즉시 종료하며 위 확인 방법을 출력한다.

## 3. 실행

```bash
source ~/drone_venv/bin/activate
cd ~/EXPO
python -m drone.server                       # config: drone/config.yaml
# 첫 실행 시 콘솔에 "X-API-Key: ...." 출력 → 메모
```

`override_requires_airborne`가 true가 아니거나 limits(`speed_mps`, `max_radius_from_home_m`, `alt_rel_min_m`, `alt_rel_max_m`, `gps_min_fix`, `gps_min_sats`, `gps_max_hdop`, `arrival_radius_m`, `arrival_hold_s`)가 기본값과 다르면 시작 시 `WARNING: NON-DEFAULT SAFETY CONFIG` 배너가 출력되고 JSON 로그 `server_start`에도 남는다.

옵션: `--config 경로`, `--connection udpin:0.0.0.0:14540`(SITL 등으로 연결 문자열만 덮어쓰기).

## 4. API

```bash
K="X-API-Key: <키>"
curl -s -H "$K" http://<jetson>:8100/status
curl -s -H "$K" -H "Content-Type: application/json" \
     -d '{"lat":37.56659,"lon":126.97800,"alt_rel":10}' http://<jetson>:8100/dispatch
curl -s -X POST -H "$K" http://<jetson>:8100/abort
curl -s -X POST -H "$K" http://<jetson>:8100/reset
```

| 엔드포인트 | 동작 |
|---|---|
| `GET /status` | `config_flags`(override_requires_airborne, abort_also_pause, 현재 limits, 기본값과 다른 `limits_changed`), mode(main/sub/이름/custom_mode), armed, in_air, lat/lon, 상대·AMSL 고도, GPS fix/위성/hdop, 배터리, link_ok, 하트비트 나이, 메시지별 실제 수신 주기(`rx_rates_hz`), 수신 바이트/링크 점유율(`rx_link`), MAVLink 버전(`mavlink.proto`), 홈, dispatch 상태 |
| `POST /dispatch` | 사전검증 전부 통과 시에만 `DO_REPOSITION`(COMMAND_INT) 전송, ACK 2 s 대기. 실패 시 409 + `reasons`(명령 미전송). ACK 거절/타임아웃 시 502 |
| `POST /abort` | `DO_SET_MODE(1,4,3)`=Hold + `DO_REPOSITION(NaN,NaN,NaN)`=정지. pilot_override 중이거나 Hold가 아니면 409(조종사 모드를 빼앗지 않음) |
| `POST /reset` | pilot_override 등 래치 해제 → idle. **모드가 Hold일 때만** |

dispatch 상태: `idle | moving | arrived | aborted | failed | pilot_override`

### 사전검증 사유 코드 (409 `reasons`)

| 코드 | 조건 (config `dispatch.*`, 시작값) |
|---|---|
| `not_pilot_override` | pilot_override 래치 중 |
| `not_in_progress` | 이미 moving |
| `link_ok` | 하트비트 1.0 s 초과 끊김 |
| `armed` / `in_air` | armed 아님 / EXTENDED_SYS_STATE ≠ IN_AIR |
| `mode_hold` | 모드가 Hold(main 4, sub 3)가 아님 |
| `gps_fix` / `gps_sats` / `gps_hdop` | fix<3 / 위성<8 / hdop(eph/100)>2.0 또는 미상 |
| `position_fresh` | GLOBAL_POSITION_INT가 1 s 이상 안 옴 |
| `home_known` / `radius_from_home` | 홈 미상 / 홈에서 목표까지 > 30 m |
| `alt_range` | 상대고도 3~20 m 밖 |
| `command_busy` | 다른 dispatch/abort 처리 중 |
| `invalid_request` (422) | 숫자 아님, NaN/Inf, 위경도 범위 밖 |

홈: `HOME_POSITION`(시작 후 5 s마다 `REQUEST_MESSAGE`로 수신될 때까지 요청). 못 받으면 armed 전환 시점 위치.

### 고도 기준 (중요)

PX4 v1.16.0 소스 확인 결과:
- `mavlink_receiver.cpp handle_message_command_int`: COMMAND_INT의 `frame` 필드를 **읽지 않고** `z`를 그대로 `param7`로 넘김.
- `navigator_main.cpp` DO_REPOSITION: `param7`을 `get_global_position()->alt`(AMSL)와 같은 기준으로 그대로 사용.
- → **DO_REPOSITION 고도는 AMSL**. `MAV_FRAME_GLOBAL_RELATIVE_ALT`로 보내도 상대고도로 해석되지 않는다.

그래서 서버는 `z = (GLOBAL_POSITION_INT.alt − relative_alt) + alt_rel` 로 변환해 `frame=MAV_FRAME_GLOBAL`로 보낸다. 도착 시 `GLOBAL_POSITION_INT.relative_alt`로 실제 도달 고도와 오차(`alt_err_m`)를 기록한다. SITL/실기체 실측은 **미검증**(docs/test_report.md).

또 `Commander.cpp`는 DO_REPOSITION의 `param2`에 bit0(`MAV_DO_REPOSITION_FLAGS_CHANGE_MODE`)이 없으면 `UNSUPPORTED`를 반환하므로 `param2=1`로 보낸다.

### RC 우선 (pilot_override)

공중(armed & IN_AIR) 또는 moving 상태에서 모드가 Hold → 다른 모드로 바뀌면 즉시 `pilot_override` 래치. 이후 `/dispatch`, `/abort` 모두 거절하고 FC에 아무 명령도 보내지 않는다. 조종사가 Hold로 되돌린 뒤 `POST /reset`으로만 해제.

## 5. 링크 대역폭 근거

57600 baud, 8N1 → 5,760 B/s. 요청 스트림(프레임 = 페이로드 + 헤더/CRC, v2 12 B, v1 8 B, v2는 확장 필드 포함 최악치):

| 메시지 | Hz | v2 프레임 B | v2 B/s | v1 프레임 B | v1 B/s |
|---|---|---|---|---|---|
| HEARTBEAT | 2 | 21 | 42 | 17 | 34 |
| GLOBAL_POSITION_INT | 5 | 40 | 200 | 36 | 180 |
| GPS_RAW_INT | 2 | 64 | 128 | 38 | 76 |
| SYS_STATUS | 1 | 55 | 55 | 39 | 39 |
| EXTENDED_SYS_STATE | 2 | 14 | 28 | 10 | 20 |
| **합계** | | | **453 (7.9%)** | | **349 (6.1%)** |
| HOME_POSITION | 1회 | 72 | – | 60 | – |

상한(링크의 절반) 2,880 B/s 대비 충분히 작다. 단 PX4는 해당 TELEM 포트의 `MAV_x_MODE` 기본 스트림도 함께 보내므로 실제 총량은 `/status`의 `rx_link.bytes_per_s`, `utilization_pct`로 확인한다. 50%를 넘으면 QGC에서 그 포트의 `MAV_x_MODE`/`MAV_x_RATE`를 조정(서버는 파라미터를 바꾸지 않음).

HEARTBEAT 2 Hz 요청이 PX4에서 반영되는지는 **미검증**. `rx_rates_hz.HEARTBEAT`가 1.0 근처면 1 s 타임아웃과 겹쳐 `link_ok`가 깜빡일 수 있으니 `heartbeat_timeout_s`를 1.5로 올린다.

## 6. 테스트 (PC)

```bash
python -m venv drone/.venv && drone/.venv/Scripts/pip install -r drone/requirements-dev.txt   # Windows
drone/.venv/Scripts/python -m pytest drone/tests -v
# 수동: 모의 FC + 서버
python -m drone.tests.mock_fc --port 14540 --speed-scale 5
python -m drone.server --connection udpin:127.0.0.1:14540
```

mock은 **우리 서버 로직만** 검증한다. PX4의 실제 수락 동작은 검증하지 못한다. 결과: [docs/test_report.md](docs/test_report.md). 현장 절차: [docs/prop_off_checklist.md](docs/prop_off_checklist.md).
