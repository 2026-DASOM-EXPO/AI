# SITL 진행 메모 (재부팅 재개용)

## 지금까지 한 일 (2026-10-08)

| 시각 | 내용 |
|---|---|
| 10:46 | 사전 확인: BIOS 가상화 활성(VirtualizationFirmwareEnabled=True, SLAT=True), HypervisorPresent=False, 셸은 비관리자, C: 여유 299 GB, RAM 31.7 GB |
| 10:57 | 브랜치 `feat/drone-dispatch` 생성 후 커밋 **`61bcb151167a186b40d7fe50b8f94cf02f5ab35d`** (drone/ + scripts/jetson_check.sh, final_pick.py, final_pick_c.py, 21 files, +2463). push 안 함. 그 시점 pytest 22/22 (3.11.9, 3.10.21+PyYAML 5.4.1) |
| 10:58 | `wsl --install --no-distribution` → 기본 내장 wsl.exe가 옵션을 받지 않음("WSL이 설치되어 있지 않습니다", exit 1) |
| 10:58 | 대신 관리자 DISM(UAC 승인)으로 기능 활성화: `Microsoft-Windows-Subsystem-Linux`, `VirtualMachinePlatform` 둘 다 "작업을 완료했습니다". **재부팅 대기** |

SITL 90분 타이머는 재부팅 후 아래 2단계부터 잰다.

## 재개 방법

재부팅 후 Claude Code를 `C:\EXPO`에서 다시 열고: **"drone/docs/sitl_progress.md 읽고 이어서 진행"**.
브랜치가 `feat/drone-dispatch`인지 먼저 확인 (`git branch --show-current`).

## 다음에 실행할 명령 (PX4 v1.16 공식 문서 확인 기준)

Windows (PowerShell):
```powershell
wsl --status                                   # 기능 활성 확인
wsl --update                                   # WSL 패키지 설치/갱신 (UAC 가능성)
wsl --set-default-version 2
wsl --install -d Ubuntu-22.04 --no-launch
ubuntu2204.exe install --root                  # 대화형 사용자 생성 없이 root로 초기화
wsl -l -v                                      # Ubuntu-22.04, VERSION 2 확인
```

WSL (root, 홈 디렉터리 = WSL 파일시스템. /mnt/c 아래에서 빌드하지 말 것):
```bash
cd ~
git clone https://github.com/PX4/PX4-Autopilot.git --recursive -b v1.16.0
bash ./PX4-Autopilot/Tools/setup/ubuntu.sh --no-nuttx --no-sim-tools   # Gazebo 등 시뮬 도구 제외
exit
```
```powershell
wsl --shutdown
```
```bash
# headless SIH (외부 시뮬레이터 없음). 홈 AMSL을 0이 아닌 값으로 지정 → 상대고도와 AMSL 구분
cd ~/PX4-Autopilot
export PX4_HOME_LAT=37.5665 PX4_HOME_LON=126.9780 PX4_HOME_ALT=47.0
make px4_sitl sihsim_quadx
# 문서 주의: SIH-as-SITL은 SENS_EN_GPSSIM / SENS_EN_BAROSIM / SENS_EN_MAGSIM 활성 필요할 수 있음 (pxh> param show SENS_EN_*)
```

서버는 WSL 안에서 실행 (Ubuntu 22.04 = Python 3.10, Jetson과 동일):
```bash
python3 -m venv ~/drone_venv && ~/drone_venv/bin/pip install -r /mnt/c/EXPO/drone/requirements.txt
cd /mnt/c/EXPO && ~/drone_venv/bin/python -m drone.server --config <sitl용 config> --connection udpin:0.0.0.0:14540
```
PX4 SITL의 offboard 링크는 14540(원격)/14580(로컬), `-m onboard` 모드 — 확인 필요.

## 검증 7항목 (결과는 test_report.md에)

1. DO_REPOSITION(param2=1) compid 191 수락/ACK
2. alt_rel→AMSL 변환 후 실제 relative_alt (2개 이상 고도)
3. /abort 후 정지 (NaN DO_REPOSITION 포함/제외 비교)
4. DO_SET_MODE ACK와 실제 모드 전환 시점
5. 하트비트 실제 수신 주기, custom_mode 디코딩 (Hold = 4/3)
6. MAVLink v1/v2 동작 (SITL은 UDP → 시리얼과 다름 명시)
7. prop_off_checklist C절 재현: alt_rel = 현재 상대고도 dispatch 시 수직 변화 ≤ 3 m

먼저 SITL 홈 AMSL ≠ 0 확인 (HOME_POSITION.altitude, GLOBAL_POSITION_INT.alt − relative_alt).
이륙은 SITL에서만 검증 목적으로 pxh `commander takeoff` 사용 (서버에는 이륙 기능 없음, 추가하지 않음).

## 제약 (사용자 지시)

- 서버 코드는 버그 수정만, 수정 전 diff·이유 보고, 새 기능 금지. 수정 후 pytest 전체 재실행.
- 커밋 금지 (앞의 61bcb15 커밋은 1회 예외로 허락된 것). push 금지.
- 90분 초과 시 중단하고 현황 보고.

## 재부팅 후 진행 결과 (2026-10-08 11:05~11:27) — 완료

- WSL 3.0.1 + Ubuntu-22.04 설치(`wsl --install -d Ubuntu-22.04 --no-launch`, 관리자 불필요), PX4 v1.16.0 SIH 빌드·실행 성공.
- 홈 AMSL 47.413 m (≠ 0) 확인 후 7항목 검증 완료, 결과·로그 근거는 `test_report.md`의 "SITL 검증" 절, 원본 로그는 `drone/logs/sitl_20261008/`.
- 버그 2건 수정(변경 이력 3): `time.monotonic()`, `heartbeat_timeout_s` 1.5. pytest 22/22 (3.11.9, 3.10.12). 커밋 안 함.
- WSL에 남은 것: `/root/PX4-Autopilot` (빌드 포함), `/root/drone_venv`. SITL 재실행: `drone/logs/sitl_20261008/`의 스크립트 참고.
