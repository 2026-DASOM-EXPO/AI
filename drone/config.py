"""config.yaml 로드. 없으면 기본값으로 생성하고 API 키를 랜덤 발급한다.

Python 3.10 / PyYAML 5.4.1 호환: yaml.safe_load / yaml.safe_dump 만 사용.
"""
import copy
import os
import secrets

import yaml

DRONE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(DRONE_DIR, "config.yaml")

DEFAULTS = {
    "http": {
        "host": "0.0.0.0",
        "port": 8100,  # MediaMTX 8554/8889/8888/9997/8000/8001 회피
    },
    "api_key": "",  # 비어 있으면 첫 실행 시 생성
    "mavlink": {
        # Jetson: "/dev/ttyTHS1" + baud. SITL/mock: "udpin:0.0.0.0:14540"
        "connection": "/dev/ttyTHS1",
        "baud": 57600,
        "source_system": 1,
        "source_component": 191,  # MAV_COMP_ID_ONBOARD_COMPUTER. 255(GCS) 금지
        "target_system": 1,
        "target_component": 1,  # MAV_COMP_ID_AUTOPILOT1. 0 사용 금지
        "heartbeat_timeout_s": 1.0,
        "proto_probe_timeout_s": 3.0,  # v2 응답 대기 후 v1 폴백
        "ack_timeout_s": 2.0,
        # 요청 주기(Hz). 0 이하 = 요청 안 함
        "stream_rates_hz": {
            "HEARTBEAT": 2.0,
            "GLOBAL_POSITION_INT": 5.0,
            "GPS_RAW_INT": 2.0,
            "SYS_STATUS": 1.0,
            "EXTENDED_SYS_STATE": 2.0,
        },
    },
    "dispatch": {
        "speed_mps": 2.0,  # DO_REPOSITION param1
        "max_radius_from_home_m": 30.0,
        "alt_rel_min_m": 3.0,
        "alt_rel_max_m": 20.0,
        "gps_min_fix": 3,
        "gps_min_sats": 8,
        "gps_max_hdop": 2.0,
        "arrival_radius_m": 2.0,
        "arrival_hold_s": 2.0,
        # 도착 제한시간 = 거리/속도 * factor + margin. 초과 시 failed(arrival_timeout)
        "arrival_timeout_factor": 2.0,
        "arrival_timeout_margin_s": 30.0,
        # pilot_override 래치 조건에 airborne(IN_AIR & armed)을 요구할지.
        # 프롭오프(지상) 점검 때만 false로 바꿔 쓴다.
        "override_requires_airborne": True,
        # /abort 시 DO_SET_MODE(Hold) 다음에 DO_REPOSITION(NaN,NaN,NaN)=정지도 보낼지.
        # 이미 Hold인 상태에서 Hold 재설정만으로는 진행 중 reposition이 멈춘다는 보장이 없어서 기본 on.
        "abort_also_pause": True,
    },
    "log_dir": os.path.join(DRONE_DIR, "logs"),
}


# 사전검증/도착 판정에 쓰이는 한계값. 기본값과 다르면 시작 시 경고.
LIMIT_KEYS = (
    "speed_mps", "max_radius_from_home_m", "alt_rel_min_m", "alt_rel_max_m",
    "gps_min_fix", "gps_min_sats", "gps_max_hdop", "arrival_radius_m", "arrival_hold_s",
)


def config_flags(cfg):
    """/status 노출용: 안전 관련 플래그와 현재 limits, 기본값과 다른 항목."""
    d, dd = cfg["dispatch"], DEFAULTS["dispatch"]
    limits = {k: d[k] for k in LIMIT_KEYS}
    changed = {k: dict(value=d[k], default=dd[k]) for k in LIMIT_KEYS if d[k] != dd[k]}
    return dict(override_requires_airborne=d["override_requires_airborne"],
                abort_also_pause=d["abort_also_pause"],
                limits=limits, limits_default=not changed, limits_changed=changed)


def config_warnings(cfg):
    f = config_flags(cfg)
    out = []
    if f["override_requires_airborne"] is not True:
        out.append("override_requires_airborne=%r (ground-test setting). "
                   "Set it back to true before flight!" % f["override_requires_airborne"])
    for k, v in f["limits_changed"].items():
        out.append("limit %s=%r (default %r)" % (k, v["value"], v["default"]))
    return out


def print_config_warnings(cfg):
    """시작 시 콘솔 경고. ASCII만 사용(콘솔 로캘 무관)."""
    warns = config_warnings(cfg)
    if not warns:
        return warns
    bar = "!" * 72
    print(bar)
    print("!!  WARNING: NON-DEFAULT SAFETY CONFIG")
    for w in warns:
        print("!!  - " + w)
    print("!!  check GET /status -> config_flags")
    print(bar, flush=True)
    return warns


def _merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path=DEFAULT_CONFIG_PATH, create=True):
    """config를 읽어 기본값과 병합. 파일/키가 없으면 생성 후 콘솔에 키 출력."""
    user = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
    cfg = _merge(DEFAULTS, user)
    if not cfg.get("api_key"):
        cfg["api_key"] = secrets.token_urlsafe(24)
        if create:
            user["api_key"] = cfg["api_key"]
            if not os.path.exists(path):
                user = _merge(DEFAULTS, user)
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(user, f, allow_unicode=True, sort_keys=False)
        print("=" * 60)
        print("[drone] new API key generated, saved to %s" % path)  # ASCII: 콘솔 로캘 무관
        print("[drone] X-API-Key: %s" % cfg["api_key"])
        print("=" * 60, flush=True)
    return cfg
