#!/usr/bin/env bash
# Jetson 현장 점검 (읽기 전용: 설치, sudo, 설정 변경 없음)
# 사용: bash scripts/jetson_check.sh   (다른 파이썬: PYTHON=/path/to/python3 bash scripts/jetson_check.sh)
# 출력은 터미널과 ~/jetson_check_YYYYmmdd_HHMM.log 에 동시에 남는다.

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
MODEL="$ROOT/runs/train/safety_equipment_v4b_11s_1280/weights/best.pt"
MODEL_SHA8="877f53bf"
SRC="rtsp://127.0.0.1:8554/a8mini_h264"
SERIAL="/dev/ttyTHS1"
FPS_MIN=18
LOG="$HOME/jetson_check_$(date +%Y%m%d_%H%M).log"

exec > >(tee -a "$LOG") 2>&1

SUMMARY=()
mark() {  # mark STATUS 항목 내용
    printf '[%-4s] %-22s %s\n' "$1" "$2" "$3"
    SUMMARY+=("$(printf '%-4s | %-22s | %s' "$1" "$2" "$3")")
}
have() { command -v "$1" >/dev/null 2>&1; }

echo "== Jetson 점검 $(date '+%F %T') =="
echo "저장소: $ROOT"
echo "로그:   $LOG"
echo

# 1) python / torch / ultralytics / CUDA
echo "-- 1) Python, torch, ultralytics"
if have "$PY"; then
    mark INFO "python" "$("$PY" -V 2>&1) ($(command -v "$PY"))"
    PYINFO="$("$PY" - <<'EOF' 2>&1
try:
    import torch
    print("torch", torch.__version__)
    print("cuda", torch.cuda.is_available())
except Exception as e:
    print("torch_error", repr(e))
try:
    import ultralytics
    print("ultralytics", ultralytics.__version__)
except Exception as e:
    print("ultralytics_error", repr(e))
EOF
)"
    echo "$PYINFO" | sed 's/^/    /'
    TORCH_V="$(echo "$PYINFO" | awk '$1=="torch"{print $2}')"
    ULT_V="$(echo "$PYINFO" | awk '$1=="ultralytics"{print $2}')"
    CUDA="$(echo "$PYINFO" | awk '$1=="cuda"{print $2}')"
    mark INFO "torch / ultralytics" "${TORCH_V:-불러오기 실패} / ${ULT_V:-불러오기 실패}"
    if [ "$CUDA" = "True" ]; then
        mark PASS "torch.cuda" "available"
    else
        mark FAIL "torch.cuda" "사용 불가 (${CUDA:-torch 불러오기 실패})"
    fi
else
    mark FAIL "python" "$PY 없음"
fi
if have ffmpeg; then
    mark INFO "ffmpeg" "$(ffmpeg -version 2>/dev/null | head -n1) (detect_stream.py 는 -vsync 사용, 4.x 에서 동작)"
else
    mark FAIL "ffmpeg" "없음 (detect_stream.py 출력에 필요)"
fi
echo

# 2) 모델 파일
echo "-- 2) 기본 모델 파일"
if [ -f "$MODEL" ]; then
    SHA="$(sha256sum "$MODEL" | cut -c1-8)"
    if [ "$SHA" = "$MODEL_SHA8" ]; then
        mark PASS "모델 sha256" "$SHA ($(stat -c %s "$MODEL") bytes)"
    else
        mark FAIL "모델 sha256" "$SHA (기대 $MODEL_SHA8)"
    fi
else
    mark FAIL "모델 파일" "없음: $MODEL"
fi
echo

# 3) MediaMTX 포트
echo "-- 3) MediaMTX 리스닝 포트"
if have ss; then
    for port in 8554 8889; do
        if ss -ltn | awk '{print $4}' | grep -Eq "[:.]${port}\$"; then
            mark PASS "포트 $port" "LISTEN"
        else
            mark FAIL "포트 $port" "리스닝 없음"
        fi
    done
else
    mark FAIL "ss" "명령 없음, 포트 확인 불가"
fi
echo

# 4) 원본 스트림
echo "-- 4) 원본 스트림 ffprobe: $SRC"
if have ffprobe; then
    PROBE="$(timeout 15 ffprobe -v error -rtsp_transport tcp -select_streams v:0 \
        -show_entries stream=codec_name,width,height,avg_frame_rate,r_frame_rate -of default=nw=1 "$SRC" 2>&1)"
    if echo "$PROBE" | grep -q '^codec_name='; then
        CODEC="$(echo "$PROBE" | sed -n 's/^codec_name=//p')"
        W="$(echo "$PROBE" | sed -n 's/^width=//p')"; H="$(echo "$PROBE" | sed -n 's/^height=//p')"
        RFR="$(echo "$PROBE" | sed -n 's/^r_frame_rate=//p')"; AFR="$(echo "$PROBE" | sed -n 's/^avg_frame_rate=//p')"
        mark PASS "원본 스트림" "$CODEC ${W}x${H} r=$RFR avg=$AFR"
    else
        mark FAIL "원본 스트림" "ffprobe 실패: $(echo "$PROBE" | head -n1)"
    fi
else
    mark FAIL "ffprobe" "명령 없음"
fi
echo

# 5) 시리얼
echo "-- 5) 시리얼 $SERIAL"
if [ -e "$SERIAL" ]; then
    mark PASS "$SERIAL 존재" "$(ls -l "$SERIAL")"
    if [ -r "$SERIAL" ] && [ -w "$SERIAL" ]; then
        mark PASS "$SERIAL 읽기/쓰기" "현재 사용자($(id -un)) 가능"
    else
        mark FAIL "$SERIAL 읽기/쓰기" "현재 사용자($(id -un)) 권한 없음"
    fi
else
    mark FAIL "$SERIAL 존재" "없음"
fi
if id -nG | tr ' ' '\n' | grep -qx dialout; then
    mark PASS "dialout 그룹" "$(id -un) 소속"
else
    mark FAIL "dialout 그룹" "$(id -un) 미소속 (현재 세션 기준, 로그인 후 추가했다면 재로그인 필요)"
fi
if have fuser && [ -e "$SERIAL" ]; then
    USERS="$(fuser "$SERIAL" 2>/dev/null | xargs)"
    if [ -n "$USERS" ]; then
        mark INFO "$SERIAL 점유" "PID $USERS ($(ps -o comm= -p "${USERS// /,}" 2>/dev/null | xargs))"
    else
        mark INFO "$SERIAL 점유" "없음 (sudo 없이는 다른 사용자 프로세스가 안 보일 수 있음)"
    fi
else
    mark INFO "$SERIAL 점유" "fuser 없음 또는 장치 없음, 확인 생략"
fi
echo

# 6) 디스크 / 전원
echo "-- 6) 디스크, 전원 모드"
mark INFO "디스크 여유" "$(df -h "$ROOT" | awk 'NR==2{print $4 " 남음 / " $2 " (" $6 ")"}')"
mark INFO "전원 모드" "수동 확인: sudo nvpmodel -q, 기대값 MAXN_SUPER"
echo

# 7) detect_stream.py FPS (20초)
echo "-- 7) detect_stream.py FPS (timeout 20, --imgsz 1280 --conf 0.4)"
if pgrep -f "detect_stream.py" >/dev/null 2>&1; then
    mark INFO "detect_stream FPS" "이미 실행 중인 detect_stream.py 가 있어 생략 (PID $(pgrep -f detect_stream.py | xargs))"
else
    RUNLOG="$(mktemp)"
    # SIGINT 로 끝내야 스크립트의 finally 가 ffmpeg 자식을 정리한다(SIGTERM 이면 정리 없이 종료)
    timeout -s INT -k 5 20 "$PY" -u "$ROOT/scripts/detect_stream.py" --imgsz 1280 --conf 0.4 >"$RUNLOG" 2>&1
    RC=$?
    tail -n 5 "$RUNLOG" | sed 's/^/    /'
    FPS_STAT="$(awk '/^FPS /{n++; s+=$2; if(n>1){m++; t+=$2}} END{
        if(n==0){print "none"} else {printf "%d %.1f %s\n", n, s/n, (m>0 ? sprintf("%.1f", t/m) : "na")}}' "$RUNLOG")"
    if [ "$FPS_STAT" = "none" ]; then
        mark FAIL "detect_stream FPS" "FPS 로그 없음 (종료 코드 $RC, 마지막 줄: $(tail -n1 "$RUNLOG"))"
    else
        read -r N MEAN MEAN2 <<<"$FPS_STAT"
        JUDGE="$MEAN2"; [ "$JUDGE" = "na" ] && JUDGE="$MEAN"
        if awk -v v="$JUDGE" -v m="$FPS_MIN" 'BEGIN{exit !(v>=m)}'; then ST=PASS; else ST=FAIL; fi
        mark "$ST" "detect_stream FPS" "평균 $JUDGE (첫 구간 제외, 전체 평균 $MEAN, ${N}줄). 기준 ${FPS_MIN}은 임의값, 이전 실측 약 21"
    fi
    sleep 2
    if pgrep -f "yolo_out" >/dev/null 2>&1; then
        mark FAIL "ffmpeg 자식 정리" "yolo_out 송출 프로세스 남음: PID $(pgrep -f yolo_out | xargs)"
    else
        mark PASS "ffmpeg 자식 정리" "남은 yolo_out 송출 프로세스 없음"
    fi
    rm -f "$RUNLOG"
fi
echo

# 요약
echo "================ 요약 ================"
printf '%-4s | %-22s | %s\n' "상태" "항목" "내용"
echo "-----+------------------------+-----------------------------"
for line in "${SUMMARY[@]}"; do echo "$line"; done
echo "======================================"
echo "PASS $(printf '%s\n' "${SUMMARY[@]}" | grep -c '^PASS')  FAIL $(printf '%s\n' "${SUMMARY[@]}" | grep -c '^FAIL')  INFO $(printf '%s\n' "${SUMMARY[@]}" | grep -c '^INFO')"
echo "로그: $LOG"
