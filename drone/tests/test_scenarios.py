"""시나리오 테스트 (mock FC 대상). 실행: 저장소 루트에서 `python -m pytest drone/tests -v`

mock은 우리 서버 로직만 검증한다. PX4 실제 수락 동작은 검증하지 않는다.
"""
import contextlib
import copy
import json
import math
import os
import socket
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from drone.config import DEFAULTS, print_config_warnings
from drone.geo import offset_latlon
from drone.mav import mavlink
from drone.server import build
from drone.tests.mock_fc import MockFC

KEY = "test-key-123"
H = {"X-API-Key": KEY}
HOME = (37.5665000, 126.9780000, 40.0)


def free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_until(fn, timeout=8.0, step=0.05):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


@contextlib.contextmanager
def make_env(tmp_path, mode=(4, 3), wait_proto=True, dispatch_over=None, **mock_kw):
    port = free_udp_port()
    cfg = copy.deepcopy(DEFAULTS)
    cfg["dispatch"].update(dispatch_over or {})
    cfg["api_key"] = KEY
    cfg["log_dir"] = str(tmp_path / "logs")
    cfg["mavlink"]["connection"] = "udpin:127.0.0.1:%d" % port
    app, link, ctrl, log = build(cfg)
    link.start()  # 바인드 먼저 (Windows UDP reset 회피)
    time.sleep(0.1)
    fc = MockFC(port, home=HOME, **mock_kw)
    fc.main, fc.sub = mode
    fc.start()
    try:
        assert wait_until(lambda: link.link_ok() and link.gpi and link.gps and link.home
                          and link.landed_state is not None), "link not ready"
        if wait_proto:
            assert wait_until(lambda: link.proto in ("v1", "v2"), timeout=10), link.proto
        with TestClient(app) as client:
            yield client, fc, ctrl, link, cfg
    finally:
        fc.stop()
        link.stop()


def tgt(north, east=0.0):
    return offset_latlon(HOME[0], HOME[1], north, east)


def post_dispatch(client, north, alt_rel=15.0, east=0.0):
    lat, lon = tgt(north, east)
    return client.post("/dispatch", headers=H, json={"lat": lat, "lon": lon, "alt_rel": alt_rel})


def state(client):
    return client.get("/status", headers=H).json()["dispatch"]["state"]


# ---------------------------------------------------------------- 시나리오
def test_api_key_required(tmp_path):
    with make_env(tmp_path) as (c, fc, ctrl, link, cfg):
        assert c.get("/status").status_code == 401
        assert c.get("/status", headers={"X-API-Key": "wrong"}).status_code == 401
        lat, lon = tgt(10)
        r = c.post("/dispatch", json={"lat": lat, "lon": lon, "alt_rel": 10})
        assert r.status_code == 401
        assert c.post("/dispatch", json={"lat": "x"}).status_code == 401  # 키 검사가 바디 검증보다 먼저
        assert c.post("/abort").status_code == 401
        assert c.post("/reset").status_code == 401
        time.sleep(0.3)
        assert fc.commands(mavlink.MAV_CMD_DO_REPOSITION) == []
        assert c.get("/status", headers=H).status_code == 200


def test_status_fields_and_rates(tmp_path):
    with make_env(tmp_path) as (c, fc, ctrl, link, cfg):
        time.sleep(5.5)  # 수신 주기 창(5 s) 채우기
        s = c.get("/status", headers=H).json()
        assert s["link_ok"] is True
        assert s["mode"]["main"] == 4 and s["mode"]["sub"] == 3 and s["mode"]["friendly"] == "Hold"
        assert s["mode"]["custom_mode"] == 50593792  # 실측 Hold 값
        assert s["armed"] is True and s["in_air"] is True
        assert s["gps"] == {"fix_type": 3, "sats": 12, "hdop": 0.8}
        assert s["battery"]["voltage_v"] == 23.8 and s["battery"]["remaining_pct"] == 76
        assert abs(s["position"]["alt_rel_m"] - 10.0) < 0.01
        assert s["home"]["source"] == "HOME_POSITION"
        assert s["mavlink"]["proto"] == "v2" and s["mavlink"]["last_rx_frame"] == "v2"
        assert s["dispatch"]["state"] == "idle"
        r = s["rx_rates_hz"]
        assert 4.0 <= r["GLOBAL_POSITION_INT"] <= 6.0, r
        assert 1.4 <= r["GPS_RAW_INT"] <= 2.6, r
        assert 0.6 <= r["SYS_STATUS"] <= 1.4, r
        assert 1.4 <= r["EXTENDED_SYS_STATE"] <= 2.6, r
        assert 1.4 <= r["HEARTBEAT"] <= 2.6, r
        print("rx_rates_hz", r)


def test_dispatch_normal(tmp_path):
    with make_env(tmp_path, speed_scale=5.0) as (c, fc, ctrl, link, cfg):
        r = post_dispatch(c, north=10, alt_rel=15.0)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["accepted"] and b["ack"]["result"] == "ACCEPTED" and b["state"] == "moving"
        # 실제로 송신된 프레임 검증
        cmds = fc.commands(mavlink.MAV_CMD_DO_REPOSITION)
        assert len(cmds) == 1
        kind, m, wire, src = cmds[0]
        assert kind == "COMMAND_INT" and wire == "v2"
        assert src == (1, 191)
        assert (m["target_system"], m["target_component"]) == (1, 1)
        assert m["frame"] == mavlink.MAV_FRAME_GLOBAL
        assert m["param1"] == 2.0 and m["param2"] == 1.0 and math.isnan(m["param4"])
        lat, lon = tgt(10)
        assert m["x"] == int(round(lat * 1e7)) and m["y"] == int(round(lon * 1e7))
        assert abs(m["z"] - (HOME[2] + 15.0)) < 0.01  # AMSL = home 40 + 15
        # 도착: 수평 < 2 m 가 2 s 지속
        assert wait_until(lambda: state(c) == "arrived", timeout=10)
        s = c.get("/status", headers=H).json()["dispatch"]
        assert s["result"]["horizontal_err_m"] < 2.0
        assert abs(s["result"]["alt_rel_m"] - 15.0) < 0.5  # GPI relative_alt로 실제 도달고도 검증
        assert s["result"]["elapsed_s"] >= 2.0


def test_reject_radius(tmp_path):
    with make_env(tmp_path) as (c, fc, ctrl, link, cfg):
        r = post_dispatch(c, north=40)
        assert r.status_code == 409
        assert r.json()["reasons"] == ["radius_from_home"]
        assert r.json()["sent"] is False
        assert fc.commands(mavlink.MAV_CMD_DO_REPOSITION) == []


@pytest.mark.parametrize("alt", [2.0, 25.0, float("nan")])
def test_reject_alt_range(tmp_path, alt):
    with make_env(tmp_path) as (c, fc, ctrl, link, cfg):
        lat, lon = tgt(10)
        if math.isnan(alt):
            # JSON은 NaN 표준이 아님 → 문자열 바디로 전송
            r = c.post("/dispatch", headers={**H, "Content-Type": "application/json"},
                       content='{"lat": %r, "lon": %r, "alt_rel": NaN}' % (lat, lon))
            assert r.status_code == 422
        else:
            r = post_dispatch(c, north=10, alt_rel=alt)
            assert r.status_code == 409
            assert r.json()["reasons"] == ["alt_range"]
        assert fc.commands(mavlink.MAV_CMD_DO_REPOSITION) == []


@pytest.mark.parametrize("field,value,reason", [
    ("sats", 5, "gps_sats"), ("eph", 300, "gps_hdop"), ("fix_type", 2, "gps_fix"), ("eph", 65535, "gps_hdop"),
])
def test_reject_gps(tmp_path, field, value, reason):
    with make_env(tmp_path) as (c, fc, ctrl, link, cfg):
        setattr(fc, field, value)
        time.sleep(1.2)
        r = post_dispatch(c, north=10)
        assert r.status_code == 409
        assert r.json()["reasons"] == [reason], r.json()["reasons"]
        assert fc.commands(mavlink.MAV_CMD_DO_REPOSITION) == []


def test_reject_mode_not_hold(tmp_path):
    with make_env(tmp_path, mode=(3, 0)) as (c, fc, ctrl, link, cfg):  # Position에서 시작
        r = post_dispatch(c, north=10)
        assert r.status_code == 409
        assert r.json()["reasons"] == ["mode_hold"]
        assert state(c) == "idle"  # Hold였던 적이 없으므로 override 래치 아님
        assert fc.commands(mavlink.MAV_CMD_DO_REPOSITION) == []


def test_reject_not_in_air(tmp_path):
    with make_env(tmp_path) as (c, fc, ctrl, link, cfg):
        fc.landed_state = 1
        time.sleep(1.0)
        r = post_dispatch(c, north=10)
        assert r.status_code == 409 and r.json()["reasons"] == ["in_air"]


def test_pilot_override_during_move(tmp_path):
    with make_env(tmp_path, speed_scale=1.0) as (c, fc, ctrl, link, cfg):
        assert post_dispatch(c, north=25).status_code == 200
        assert state(c) == "moving"
        time.sleep(0.5)
        fc.set_mode(3, 0)  # 조종사 RC로 Position 전환
        assert wait_until(lambda: state(c) == "pilot_override", timeout=2)
        r = post_dispatch(c, north=5)
        assert r.status_code == 409 and "not_pilot_override" in r.json()["reasons"]
        assert c.post("/abort", headers=H).status_code == 409  # 조종사 모드를 빼앗지 않음
        assert c.post("/reset", headers=H).status_code == 409  # Hold 아님
        n_cmd = len(fc.commands())
        fc.set_mode(4, 3)  # 조종사가 다시 Hold
        time.sleep(0.8)
        assert state(c) == "pilot_override"  # Hold 복귀만으로는 해제 안 됨
        r = c.post("/reset", headers=H)
        assert r.status_code == 200 and r.json()["state"] == "idle"
        assert len(fc.commands()) == n_cmd  # 래치 중 서버는 FC에 아무 명령도 보내지 않음


def test_abort(tmp_path):
    with make_env(tmp_path, speed_scale=1.0) as (c, fc, ctrl, link, cfg):
        assert post_dispatch(c, north=25).status_code == 200
        time.sleep(1.0)
        r = c.post("/abort", headers=H)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["ok"] and b["state"] == "aborted"
        assert b["ack_set_mode"]["result"] == "ACCEPTED"
        sm = fc.commands(mavlink.MAV_CMD_DO_SET_MODE)
        assert len(sm) == 1
        m = sm[0][1]
        assert (m["param1"], m["param2"], m["param3"]) == (1.0, 4.0, 3.0)
        assert (m["target_system"], m["target_component"]) == (1, 1)
        rep = fc.commands(mavlink.MAV_CMD_DO_REPOSITION)
        assert len(rep) == 2 and rep[1][1]["x"] == 2147483647 and math.isnan(rep[1][1]["z"])
        assert fc.target is None  # mock 기준 정지
        lat0, lon0 = fc.lat, fc.lon
        time.sleep(0.5)
        assert (fc.lat, fc.lon) == (lat0, lon0)
        assert state(c) == "aborted"


def test_heartbeat_loss(tmp_path):
    with make_env(tmp_path) as (c, fc, ctrl, link, cfg):
        fc.heartbeat_enabled = False
        assert wait_until(lambda: c.get("/status", headers=H).json()["link_ok"] is False, timeout=2.5)
        r = post_dispatch(c, north=10)
        assert r.status_code == 409 and r.json()["reasons"] == ["link_ok"]
        assert fc.commands(mavlink.MAV_CMD_DO_REPOSITION) == []
        fc.heartbeat_enabled = True
        assert wait_until(lambda: c.get("/status", headers=H).json()["link_ok"] is True, timeout=2.5)


def test_ack_timeout(tmp_path):
    with make_env(tmp_path) as (c, fc, ctrl, link, cfg):
        fc.ack_enabled = False
        t0 = time.time()
        r = post_dispatch(c, north=10)
        dt = time.time() - t0
        assert r.status_code == 502
        b = r.json()
        assert b["reasons"] == ["ack_timeout"] and b["ack"]["timeout"] is True
        assert 1.9 <= dt <= 3.0
        assert state(c) == "failed"


def test_v1_fallback(tmp_path):
    with make_env(tmp_path, v2_capable=False) as (c, fc, ctrl, link, cfg):
        s = c.get("/status", headers=H).json()
        assert s["mavlink"]["proto"] == "v1" and s["mavlink"]["tx_wire"] == "v1"
        assert s["mavlink"]["last_rx_frame"] == "v1"
        r = post_dispatch(c, north=10)
        assert r.status_code == 200 and r.json()["ack"]["wire"] == "v1"


def test_json_log_written(tmp_path):
    with make_env(tmp_path) as (c, fc, ctrl, link, cfg):
        post_dispatch(c, north=40)
        post_dispatch(c, north=10)
        c.get("/status")
    files = os.listdir(cfg["log_dir"])
    assert len(files) == 1
    events = [json.loads(l)["event"] for l in open(os.path.join(cfg["log_dir"], files[0]), encoding="utf-8")]
    for e in ("link_open", "request_streams", "proto_confirmed", "http", "dispatch_validate",
              "dispatch_send", "dispatch_ack", "command_ack", "dispatch_state"):
        assert e in events, e


# ---------------------------------------------------------------- config 경고 / config_flags
def test_config_flags_default(tmp_path, capsys):
    with make_env(tmp_path) as (c, fc, ctrl, link, cfg):
        f = c.get("/status", headers=H).json()["config_flags"]
        assert f["override_requires_airborne"] is True and f["abort_also_pause"] is True
        assert f["limits_default"] is True and f["limits_changed"] == {}
        assert f["limits"]["max_radius_from_home_m"] == 30.0
        assert f["limits"]["alt_rel_min_m"] == 3.0 and f["limits"]["alt_rel_max_m"] == 20.0
        assert f["limits"]["gps_min_sats"] == 8 and f["limits"]["speed_mps"] == 2.0
        assert print_config_warnings(cfg) == []
        assert "WARNING" not in capsys.readouterr().out


def test_config_flags_nondefault(tmp_path, capsys):
    over = {"override_requires_airborne": False, "max_radius_from_home_m": 50.0}
    with make_env(tmp_path, dispatch_over=over) as (c, fc, ctrl, link, cfg):
        f = c.get("/status", headers=H).json()["config_flags"]
        assert f["override_requires_airborne"] is False
        assert f["limits_default"] is False
        assert f["limits_changed"] == {"max_radius_from_home_m": {"value": 50.0, "default": 30.0}}
        assert f["limits"]["max_radius_from_home_m"] == 50.0
        warns = print_config_warnings(cfg)
        out = capsys.readouterr().out
        assert len(warns) == 2
        assert "WARNING: NON-DEFAULT SAFETY CONFIG" in out
        assert "override_requires_airborne=False" in out and "max_radius_from_home_m=50.0" in out


def test_server_start_prints_warning(tmp_path):
    """실제 `python -m drone.server` 시작 경로에서 경고가 찍히는지 (포트 열기 실패로 바로 종료되게 함)."""
    cfgp = tmp_path / "c.yaml"
    cfgp.write_text("api_key: k\nlog_dir: %s\nmavlink:\n  connection: %s\n"
                    "dispatch:\n  override_requires_airborne: false\n  alt_rel_max_m: 30.0\n"
                    % (json.dumps(str(tmp_path / "logs")), json.dumps(str(tmp_path / "no_such_tty"))),
                    encoding="utf-8")
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    p = subprocess.run([sys.executable, "-m", "drone.server", "--config", str(cfgp)], cwd=root,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode != 0  # 시리얼 열기 실패로 종료
    assert "WARNING: NON-DEFAULT SAFETY CONFIG" in p.stdout, p.stdout + p.stderr
    assert "override_requires_airborne=False" in p.stdout
    assert "alt_rel_max_m=30.0 (default 20.0)" in p.stdout
