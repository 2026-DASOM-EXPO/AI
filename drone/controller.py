"""dispatch 상태기계 + 사전검증.

상태: idle | moving | arrived | aborted | failed | pilot_override
- pilot_override 는 래치. 해제는 모드가 Hold인 상태에서 reset()으로만.
"""
import math
import threading
import time

from drone.config import config_flags
from drone.geo import haversine_m
from drone.mav import HOLD_MAIN, HOLD_SUB, mavlink

INT32_MAX = 2147483647


class Controller:
    def __init__(self, cfg, link, log):
        self.cfg = cfg
        self.d = cfg["dispatch"]
        self.link = link
        self.log = log
        self.lock = threading.RLock()
        self.cmd_lock = threading.Lock()  # dispatch/abort 직렬화
        self.state = "idle"
        self.reason = None
        self.target = None
        self.started_at = None
        self.deadline = None
        self.arrive_since = None
        self.result = None  # 도착/실패 시 상세
        self.last_ack = None
        self._prev_hold = None
        link.on_update = self.on_update

    # ---------- 수신 스레드 콜백 ----------
    def on_update(self, link, msg_type):
        if msg_type not in (None, "HEARTBEAT", "GLOBAL_POSITION_INT", "EXTENDED_SYS_STATE"):
            return
        now = time.time()
        with self.lock:
            hold = link.is_hold() if link.mode is not None else None
            if msg_type == "HEARTBEAT" and hold is not None:
                if self._prev_hold and not hold and self.state != "pilot_override":
                    engaged = self.state == "moving"
                    if engaged or link.airborne() or not self.d["override_requires_airborne"]:
                        self._set("pilot_override", reason="mode_left_hold",
                                  from_mode="Hold", to_mode=link.mode[3], was=self.state,
                                  armed=link.armed, landed_state=link.landed_state)
                self._prev_hold = hold
            if self.state == "moving":
                self._check_arrival(now)

    def _check_arrival(self, now):
        g = self.link.gpi
        if not g or not self.target:
            return
        dist = haversine_m(g["lat"], g["lon"], self.target["lat"], self.target["lon"])
        if dist < self.d["arrival_radius_m"]:
            if self.arrive_since is None:
                self.arrive_since = now
            elif now - self.arrive_since >= self.d["arrival_hold_s"]:
                self.result = dict(horizontal_err_m=round(dist, 2),
                                   alt_rel_m=round(g["alt_rel"], 2),
                                   alt_err_m=round(g["alt_rel"] - self.target["alt_rel"], 2),
                                   alt_amsl_m=round(g["alt_amsl"], 2),
                                   elapsed_s=round(now - self.started_at, 1))
                self._set("arrived", **self.result)
        else:
            self.arrive_since = None
            if self.deadline and now > self.deadline:
                self.result = dict(horizontal_err_m=round(dist, 2), alt_rel_m=round(g["alt_rel"], 2))
                self._set("failed", reason="arrival_timeout", **self.result)

    def _set(self, state, reason=None, **info):
        prev = self.state
        self.state = state
        self.reason = reason
        self.log.write("dispatch_state", prev=prev, state=state, reason=reason, **info)

    # ---------- 검증 ----------
    def validate(self, lat, lon, alt_rel):
        L, d = self.link, self.d
        now = time.time()
        reasons, checks = [], {}

        def check(code, ok, **val):
            checks[code] = dict(ok=bool(ok), **val)
            if not ok:
                reasons.append(code)

        with L.lock:
            check("not_pilot_override", self.state != "pilot_override", state=self.state)
            check("not_in_progress", self.state != "moving", state=self.state)
            check("valid_coordinates",
                  all(isinstance(v, (int, float)) and math.isfinite(v) for v in (lat, lon, alt_rel))
                  and -90 <= lat <= 90 and -180 <= lon <= 180,
                  lat=lat, lon=lon, alt_rel=alt_rel)
            check("link_ok", L.link_ok(now),
                  heartbeat_age_s=None if L.hb_time is None else round(now - L.hb_time, 2))
            check("armed", L.armed is True, armed=L.armed)
            check("in_air", L.landed_state == 2, landed_state=L.landed_state)
            check("mode_hold", L.is_hold(),
                  mode=None if L.mode is None else dict(main=L.mode[0], sub=L.mode[1], name=L.mode[3]),
                  required=dict(main=HOLD_MAIN, sub=HOLD_SUB))
            gps = L.gps or {}
            check("gps_fix", (gps.get("fix_type") or 0) >= d["gps_min_fix"],
                  value=gps.get("fix_type"), min=d["gps_min_fix"])
            check("gps_sats", (gps.get("sats") or 0) >= d["gps_min_sats"],
                  value=gps.get("sats"), min=d["gps_min_sats"])
            hdop = gps.get("hdop")
            check("gps_hdop", hdop is not None and hdop <= d["gps_max_hdop"],
                  value=hdop, max=d["gps_max_hdop"])
            pos_fresh = L.gpi is not None and now - L.gpi_time <= 1.0
            check("position_fresh", pos_fresh,
                  age_s=None if L.gpi_time is None else round(now - L.gpi_time, 2))
            home = L.home
            check("home_known", home is not None, source=None if home is None else home["source"])
            if home is not None and checks["valid_coordinates"]["ok"]:
                r = haversine_m(home["lat"], home["lon"], lat, lon)
                check("radius_from_home", r <= d["max_radius_from_home_m"],
                      value_m=round(r, 2), max_m=d["max_radius_from_home_m"])
            else:
                check("radius_from_home", False, value_m=None, max_m=d["max_radius_from_home_m"])
            alt_ok = checks["valid_coordinates"]["ok"] and d["alt_rel_min_m"] <= alt_rel <= d["alt_rel_max_m"]
            check("alt_range", alt_ok, value_m=alt_rel, min_m=d["alt_rel_min_m"], max_m=d["alt_rel_max_m"])
            ref = L.home_ref_amsl() if pos_fresh else None
        return reasons, checks, ref

    # ---------- API 동작 ----------
    def dispatch(self, lat, lon, alt_rel):
        if not self.cmd_lock.acquire(blocking=False):
            body = dict(accepted=False, sent=False, reasons=["command_busy"])
            self.log.write("dispatch_rejected", **body)
            return 409, body
        try:
            with self.lock:
                reasons, checks, ref = self.validate(lat, lon, alt_rel)
            req = dict(lat=lat, lon=lon, alt_rel=alt_rel)
            self.log.write("dispatch_validate", request=req, reasons=reasons, checks=checks)
            if reasons:
                return 409, dict(accepted=False, sent=False, reasons=reasons, checks=checks)

            # PX4 1.16: COMMAND_INT의 frame 필드는 무시되고 z는 그대로 param7 → navigator가 AMSL로 사용.
            # 따라서 상대고도를 AMSL로 변환해서 보낸다: z = (GPI.alt - GPI.relative_alt) + alt_rel
            alt_amsl = ref + alt_rel
            speed = float(self.d["speed_mps"])
            params = (speed, float(mavlink.MAV_DO_REPOSITION_FLAGS_CHANGE_MODE), 0.0, float("nan"),
                      int(round(lat * 1e7)), int(round(lon * 1e7)), float(alt_amsl))
            sent = dict(command="MAV_CMD_DO_REPOSITION", msg="COMMAND_INT", frame="MAV_FRAME_GLOBAL(AMSL)",
                        param1_speed=speed, param2_flags=1, param4_yaw="NaN",
                        x=params[4], y=params[5], z_amsl=round(alt_amsl, 3), home_ref_amsl=round(ref, 3),
                        target=[self.link.cfg["target_system"], self.link.cfg["target_component"]])
            self.log.write("dispatch_send", **sent)
            ack = self.link.command("int", mavlink.MAV_CMD_DO_REPOSITION, params,
                                    frame=mavlink.MAV_FRAME_GLOBAL)
            self.log.write("dispatch_ack", **ack)
            self.last_ack = ack
            with self.lock:
                if self.state == "pilot_override":
                    # ACK 대기 중 조종사 개입
                    return 409, dict(accepted=False, sent=True, ack=ack, reasons=["pilot_override_during_ack"])
                if ack["result"] == "ACCEPTED":
                    g = self.link.gpi
                    dist = haversine_m(g["lat"], g["lon"], lat, lon)
                    self.target = dict(lat=lat, lon=lon, alt_rel=alt_rel, alt_amsl=alt_amsl)
                    self.started_at = time.time()
                    self.deadline = self.started_at + dist / max(speed, 0.1) * self.d["arrival_timeout_factor"] \
                        + self.d["arrival_timeout_margin_s"]
                    self.arrive_since = None
                    self.result = None
                    self._set("moving", target=self.target, distance_m=round(dist, 2),
                              deadline_s=round(self.deadline - self.started_at, 1))
                    return 200, dict(accepted=True, sent=True, ack=ack, state=self.state,
                                     target=self.target, distance_m=round(dist, 2), sent_detail=sent)
                reason = "ack_timeout" if ack["timeout"] else "ack_" + str(ack["result"])
                self.target = dict(lat=lat, lon=lon, alt_rel=alt_rel, alt_amsl=alt_amsl)
                self._set("failed", reason=reason, ack=ack)
                return 502, dict(accepted=False, sent=True, ack=ack, state=self.state, reasons=[reason])
        finally:
            self.cmd_lock.release()

    def abort(self):
        with self.cmd_lock:
            L = self.link
            with self.lock:
                if self.state == "pilot_override":
                    body = dict(ok=False, reasons=["pilot_override_pilot_has_control"])
                    self.log.write("abort_rejected", **body)
                    return 409, body
                if not L.link_ok():
                    body = dict(ok=False, reasons=["link_lost"])
                    self.log.write("abort_rejected", **body)
                    return 409, body
                if not L.is_hold():
                    # Hold가 아니면 조종사가 다른 모드로 조종 중 → 모드를 빼앗지 않는다
                    body = dict(ok=False, reasons=["mode_not_hold_pilot_has_control"],
                                mode=None if L.mode is None else L.mode[3])
                    self.log.write("abort_rejected", **body)
                    return 409, body
            self.log.write("abort_send", command="MAV_CMD_DO_SET_MODE", params=[1, 4, 3])
            ack_mode = L.command("long", mavlink.MAV_CMD_DO_SET_MODE,
                                 (1.0, float(HOLD_MAIN), float(HOLD_SUB), 0, 0, 0, 0))
            self.log.write("abort_ack", which="DO_SET_MODE", **ack_mode)
            ack_pause = None
            if self.d["abort_also_pause"]:
                # 모두 NaN인 DO_REPOSITION = 현재 위치 정지(navigator "pause vehicle")
                ack_pause = L.command("int", mavlink.MAV_CMD_DO_REPOSITION,
                                      (-1.0, float(mavlink.MAV_DO_REPOSITION_FLAGS_CHANGE_MODE), 0.0,
                                       float("nan"), INT32_MAX, INT32_MAX, float("nan")))
                self.log.write("abort_ack", which="DO_REPOSITION_pause", **ack_pause)
            ok = ack_mode["result"] == "ACCEPTED" or (ack_pause is not None and ack_pause["result"] == "ACCEPTED")
            with self.lock:
                if ok and self.state != "pilot_override":
                    self._set("aborted", reason="api_abort")
                body = dict(ok=ok, state=self.state, ack_set_mode=ack_mode, ack_pause=ack_pause,
                            mode_now=None if L.mode is None else L.mode[3])
            return (200 if ok else 502), body

    def reset(self):
        with self.lock:
            if not self.link.is_hold():
                body = dict(ok=False, reasons=["mode_not_hold"], state=self.state)
                self.log.write("reset_rejected", **body)
                return 409, body
            if self.state == "moving":
                body = dict(ok=False, reasons=["dispatch_in_progress"], state=self.state)
                self.log.write("reset_rejected", **body)
                return 409, body
            self._set("idle", reason="api_reset")
            self.target = None
            self.result = None
            return 200, dict(ok=True, state=self.state)

    def status(self):
        s = self.link.snapshot()
        with self.lock:
            g = self.link.gpi
            dist = None
            if self.target and g:
                dist = round(haversine_m(g["lat"], g["lon"], self.target["lat"], self.target["lon"]), 2)
            s["dispatch"] = dict(state=self.state, reason=self.reason, target=self.target,
                                 distance_to_target_m=dist, result=self.result, last_ack=self.last_ack)
        s["config_flags"] = config_flags(self.cfg)
        return s
