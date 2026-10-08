"""FC 연결: 수신 스레드 1개 + 락. 상태 캐시, 수신 주기 측정, 명령 송신/ACK 대기, v2→v1 폴백."""
import collections
import math
import threading
import time

from drone.mav import ACK_RESULTS, decode_custom_mode, mavlink, mavutil

RATE_WINDOW_S = 5.0
HOME_RETRY_S = 5.0
MAV_LANDED_STATE_IN_AIR = 2
MAV_AUTOPILOT_PX4 = 12
TRACKED = ("HEARTBEAT", "GLOBAL_POSITION_INT", "GPS_RAW_INT", "SYS_STATUS",
           "EXTENDED_SYS_STATE", "HOME_POSITION")


class FcLink:
    def __init__(self, mcfg, log, on_update=None):
        self.cfg = mcfg
        self.log = log
        self.on_update = on_update  # 수신 스레드에서 호출: on_update(link, msg_type or None)
        self.lock = threading.RLock()
        self.send_lock = threading.Lock()
        self.conn = None
        self._stop = threading.Event()
        self._thread = None

        self.force_v1 = False
        self.proto = "probing_v2"  # probing_v2 | v2 | probing_v1 | v1 | unconfirmed_v1
        self._probe_started = None
        self._streams_acked = False
        self.last_rx_frame = None  # "v1" | "v2"

        self.hb_time = None
        self.armed = None
        self.custom_mode = None
        self.mode = None  # (main, sub, name, friendly)
        self.landed_state = None
        self.gpi = None  # dict
        self.gpi_time = None
        self.gps = None
        self.sys = None
        self.home = None  # dict(lat, lon, alt_amsl, source)
        self._home_req_time = 0.0
        self._last_own_hb = 0.0
        self._link_ok_prev = False
        self._rx_times = {k: collections.deque() for k in TRACKED}
        self._rx_bytes = collections.deque()  # (t, bytes) 모든 수신 메시지(타 컴포넌트 포함)
        self._ack_waiters = {}  # command -> list[(Event, holder)]
        self._foreign_seen = set()

    # ---------- lifecycle ----------
    def start(self):
        c = self.cfg
        kw = dict(source_system=c["source_system"], source_component=c["source_component"],
                  autoreconnect=True)
        conn_str = c["connection"]
        if not conn_str.startswith(("udp", "tcp")):
            kw["baud"] = c["baud"]
        self.conn = mavutil.mavlink_connection(conn_str, **kw)
        self.log.write("link_open", connection=conn_str, baud=c.get("baud"),
                       source=[c["source_system"], c["source_component"]],
                       target=[c["target_system"], c["target_component"]],
                       wire=mavutil.mavlink.WIRE_PROTOCOL_VERSION)
        self._thread = threading.Thread(target=self._run, name="fc-rx", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass

    # ---------- rx loop ----------
    def _run(self):
        while not self._stop.is_set():
            try:
                self._periodic(time.monotonic())
                msg = self.conn.recv_match(blocking=True, timeout=0.05)
            except Exception as e:  # 시리얼 일시 오류 등
                self.log.write("rx_error", error=repr(e))
                time.sleep(0.2)
                continue
            if msg is None:
                if self.on_update:
                    self.on_update(self, None)
                continue
            self._handle(msg)

    def _from_fc(self, msg):
        return (msg.get_srcSystem() == self.cfg["target_system"]
                and msg.get_srcComponent() == self.cfg["target_component"])

    def _handle(self, msg):
        t = msg.get_type()
        if t == "BAD_DATA":
            return
        try:
            nbytes = len(msg.get_msgbuf())
        except Exception:
            nbytes = 0
        with self.lock:
            now0 = time.monotonic()
            self._rx_bytes.append((now0, nbytes))
            while self._rx_bytes and now0 - self._rx_bytes[0][0] > RATE_WINDOW_S:
                self._rx_bytes.popleft()
        if not self._from_fc(msg):
            key = (msg.get_srcSystem(), msg.get_srcComponent())
            if key not in self._foreign_seen:
                self._foreign_seen.add(key)
                self.log.write("foreign_source_ignored", src=list(key), type=t)
            return
        now = time.monotonic()
        try:
            self.last_rx_frame = "v2" if msg.get_msgbuf()[0] == 0xFD else "v1"
        except Exception:
            pass
        with self.lock:
            if t in self._rx_times:
                dq = self._rx_times[t]
                dq.append(now)
                while dq and now - dq[0] > RATE_WINDOW_S:
                    dq.popleft()
            if t == "HEARTBEAT":
                if msg.autopilot != MAV_AUTOPILOT_PX4:
                    return
                self.hb_time = now
                armed = bool(msg.base_mode & mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                if armed and self.armed is False and self.gpi and self.home is None:
                    # HOME_POSITION 미수신 시 armed 전환 시점 위치를 홈으로
                    self.home = dict(lat=self.gpi["lat"], lon=self.gpi["lon"],
                                     alt_amsl=self.gpi["alt_amsl"], source="arm_position")
                    self.log.write("home_from_arm", home=self.home)
                if armed != self.armed:
                    self.log.write("armed_change", armed=armed)
                self.armed = armed
                if msg.custom_mode != self.custom_mode:
                    self.log.write("mode_change", custom_mode=msg.custom_mode,
                                   mode=decode_custom_mode(msg.custom_mode))
                self.custom_mode = msg.custom_mode
                self.mode = decode_custom_mode(msg.custom_mode)
            elif t == "GLOBAL_POSITION_INT":
                self.gpi = dict(lat=msg.lat / 1e7, lon=msg.lon / 1e7, alt_amsl=msg.alt / 1000.0,
                                alt_rel=msg.relative_alt / 1000.0,
                                vx=msg.vx / 100.0, vy=msg.vy / 100.0, vz=msg.vz / 100.0)
                self.gpi_time = now
            elif t == "GPS_RAW_INT":
                self.gps = dict(fix_type=msg.fix_type, sats=msg.satellites_visible,
                                hdop=None if msg.eph == 65535 else msg.eph / 100.0)
            elif t == "SYS_STATUS":
                self.sys = dict(
                    voltage_v=None if msg.voltage_battery == 65535 else msg.voltage_battery / 1000.0,
                    current_a=None if msg.current_battery == -1 else msg.current_battery / 100.0,
                    remaining_pct=None if msg.battery_remaining == -1 else msg.battery_remaining)
            elif t == "EXTENDED_SYS_STATE":
                self.landed_state = msg.landed_state
            elif t == "HOME_POSITION":
                new = dict(lat=msg.latitude / 1e7, lon=msg.longitude / 1e7,
                           alt_amsl=msg.altitude / 1000.0, source="HOME_POSITION")
                if self.home is None or self.home.get("source") != "HOME_POSITION" or \
                        abs(new["lat"] - self.home["lat"]) > 1e-7 or abs(new["lon"] - self.home["lon"]) > 1e-7:
                    self.log.write("home_position", home=new)
                self.home = new
            elif t == "COMMAND_ACK":
                self._on_ack(msg)
        if self.on_update:
            self.on_update(self, t)

    def _on_ack(self, msg):
        # v2 ACK에는 target 필드가 있다. 우리 것이 아닌(QGC 등) ACK는 무시.
        ts = getattr(msg, "target_system", 0) or 0
        tc = getattr(msg, "target_component", 0) or 0
        mine = (ts == 0 or ts == self.cfg["source_system"]) and \
               (tc == 0 or tc == self.cfg["source_component"])
        res = ACK_RESULTS.get(msg.result, str(msg.result))
        self.log.write("command_ack", command=msg.command, result=res, mine=mine,
                       target=[ts, tc], frame=self.last_rx_frame)
        if not mine:
            return
        if msg.command == mavlink.MAV_CMD_SET_MESSAGE_INTERVAL and not self._streams_acked:
            self._streams_acked = True
            self._on_proto_confirmed()
        if msg.result == mavlink.MAV_RESULT_IN_PROGRESS:
            return
        for ev, holder in self._ack_waiters.get(msg.command, []):
            if not ev.is_set():
                holder["result"] = res
                holder["result_code"] = msg.result
                holder["frame"] = self.last_rx_frame
                ev.set()

    # ---------- periodic (rx thread) ----------
    def _periodic(self, now):
        if now - self._last_own_hb >= 1.0:
            self._last_own_hb = now
            self._send(lambda m, v1: m.heartbeat_send(
                mavlink.MAV_TYPE_ONBOARD_CONTROLLER, mavlink.MAV_AUTOPILOT_INVALID, 0, 0,
                mavlink.MAV_STATE_ACTIVE, force_mavlink1=v1))
        ok = self.link_ok(now)
        if ok and not self._link_ok_prev:
            self.log.write("link_up")
            self._request_streams()
            if self._probe_started is None:
                self._probe_started = now
        elif not ok and self._link_ok_prev:
            self.log.write("link_lost", hb_age=None if self.hb_time is None else round(now - self.hb_time, 2))
        self._link_ok_prev = ok

        # v2 → v1 폴백
        if self._probe_started is not None and not self._streams_acked:
            waited = now - self._probe_started
            to = self.cfg["proto_probe_timeout_s"]
            if self.proto == "probing_v2" and waited > to:
                self.force_v1 = True
                self.proto = "probing_v1"
                self.log.write("proto_fallback", reason="no COMMAND_ACK to v2 SET_MESSAGE_INTERVAL",
                               waited_s=round(waited, 2))
                self._request_streams()
            elif self.proto == "probing_v1" and waited > 2 * to:
                self.proto = "unconfirmed_v1"
                self.log.write("proto_unconfirmed", note="no ACK in v2 nor v1; staying v1")

        if ok and (self.home is None or self.home.get("source") != "HOME_POSITION") and \
                now - self._home_req_time >= HOME_RETRY_S:
            self._home_req_time = now
            self._send(lambda m, v1: m.command_long_send(
                self.cfg["target_system"], self.cfg["target_component"],
                mavlink.MAV_CMD_REQUEST_MESSAGE, 0,
                mavlink.MAVLINK_MSG_ID_HOME_POSITION, 0, 0, 0, 0, 0, 0, force_mavlink1=v1))

    def _on_proto_confirmed(self):
        self.proto = "v1" if self.force_v1 else "v2"
        self.log.write("proto_confirmed", proto=self.proto, rx_frame=self.last_rx_frame)

    def _request_streams(self):
        for name, hz in self.cfg["stream_rates_hz"].items():
            if not hz or hz <= 0:
                continue
            msg_id = getattr(mavlink, "MAVLINK_MSG_ID_" + name)
            interval_us = int(1e6 / hz)
            self._send(lambda m, v1, i=msg_id, us=interval_us: m.command_long_send(
                self.cfg["target_system"], self.cfg["target_component"],
                mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0, i, us, 0, 0, 0, 0, 0, force_mavlink1=v1))
        self.log.write("request_streams", rates=self.cfg["stream_rates_hz"],
                       wire="v1" if self.force_v1 else "v2")

    def _send(self, fn):
        with self.send_lock:
            try:
                fn(self.conn.mav, self.force_v1)
            except Exception as e:
                self.log.write("tx_error", error=repr(e))

    # ---------- commands (HTTP 스레드) ----------
    def command(self, kind, command, params, timeout=None, frame=mavlink.MAV_FRAME_GLOBAL):
        """kind='long': params=7 floats. kind='int': (p1,p2,p3,p4,x,y,z).
        반환: dict(result=str|None, result_code, elapsed_s, wire)."""
        timeout = self.cfg["ack_timeout_s"] if timeout is None else timeout
        ev, holder = threading.Event(), {}
        with self.lock:
            self._ack_waiters.setdefault(command, []).append((ev, holder))
        ts, tc = self.cfg["target_system"], self.cfg["target_component"]
        t0 = time.monotonic()
        wire = "v1" if self.force_v1 else "v2"
        try:
            if kind == "long":
                self._send(lambda m, v1: m.command_long_send(ts, tc, command, 0, *params, force_mavlink1=v1))
            else:
                p1, p2, p3, p4, x, y, z = params
                self._send(lambda m, v1: m.command_int_send(ts, tc, frame, command, 0, 0,
                                                            p1, p2, p3, p4, x, y, z, force_mavlink1=v1))
            got = ev.wait(timeout)
        finally:
            with self.lock:
                lst = self._ack_waiters.get(command, [])
                if (ev, holder) in lst:
                    lst.remove((ev, holder))
        out = dict(command=command, result=holder.get("result") if got else None,
                   result_code=holder.get("result_code") if got else None,
                   timeout=not got, elapsed_s=round(time.monotonic() - t0, 3), wire=wire)
        return out

    # ---------- state ----------
    def link_ok(self, now=None):
        now = time.monotonic() if now is None else now
        return self.hb_time is not None and (now - self.hb_time) <= self.cfg["heartbeat_timeout_s"]

    def airborne(self):
        return bool(self.armed) and self.landed_state == MAV_LANDED_STATE_IN_AIR

    def is_hold(self):
        return self.mode is not None and self.mode[0] == 4 and self.mode[1] == 3

    def rates_hz(self, now=None):
        now = time.monotonic() if now is None else now
        out = {}
        with self.lock:
            for k, dq in self._rx_times.items():
                n = sum(1 for x in dq if now - x <= RATE_WINDOW_S)
                out[k] = round(n / RATE_WINDOW_S, 2)
        return out

    def home_ref_amsl(self):
        """상대고도 0 기준의 AMSL(= GPI.alt - GPI.relative_alt). PX4가 relative_alt를 계산하는 기준과 동일 소스."""
        if not self.gpi:
            return None
        return self.gpi["alt_amsl"] - self.gpi["alt_rel"]

    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            mode = None
            if self.mode:
                mode = dict(main=self.mode[0], sub=self.mode[1], name=self.mode[2],
                            friendly=self.mode[3], custom_mode=self.custom_mode)
            return dict(
                link_ok=self.link_ok(now),
                heartbeat_age_s=None if self.hb_time is None else round(now - self.hb_time, 2),
                mavlink=dict(proto=self.proto, tx_wire="v1" if self.force_v1 else "v2",
                             last_rx_frame=self.last_rx_frame),
                mode=mode,
                armed=self.armed,
                landed_state=self.landed_state,
                in_air=self.landed_state == MAV_LANDED_STATE_IN_AIR if self.landed_state is not None else None,
                position=None if not self.gpi else dict(
                    lat=self.gpi["lat"], lon=self.gpi["lon"], alt_rel_m=round(self.gpi["alt_rel"], 2),
                    alt_amsl_m=round(self.gpi["alt_amsl"], 2),
                    ground_speed_mps=round(math.hypot(self.gpi["vx"], self.gpi["vy"]), 2),
                    age_s=round(now - self.gpi_time, 2)),
                gps=self.gps,
                battery=self.sys,
                home=self.home,
                rx_rates_hz=self.rates_hz(now),
                requested_rates_hz=self.cfg["stream_rates_hz"],
                rx_link=self._rx_link_usage(now),
            )

    def _rx_link_usage(self, now):
        """MAVLink 프레임 기준 수신 바이트/s. 시리얼이면 8N1(10 bit/byte) 용량 대비 점유율."""
        total = sum(b for t, b in self._rx_bytes if now - t <= RATE_WINDOW_S)
        bps = total / RATE_WINDOW_S
        out = dict(bytes_per_s=round(bps, 1))
        if not self.cfg["connection"].startswith(("udp", "tcp")):
            cap = self.cfg["baud"] / 10.0
            out.update(capacity_bytes_per_s=cap, utilization_pct=round(100.0 * bps / cap, 1))
        return out
