"""모의 PX4 FC (UDP). 우리 서버 로직 검증용이며 PX4의 실제 수락 동작을 검증하지 않는다.

흉내 내는 PX4 1.16 동작(소스 확인 기준):
- 하트비트 autopilot=12, type=13(hexarotor), sysid 1 / compid 1, custom_mode = (sub<<24)|(main<<16)
- MAV_PROTO_VER 자동: v1로 송신 시작, v2 프레임을 받으면 v2로 전환
- COMMAND target이 (1,1) 또는 (1,0)이 아니면 무응답 (mavlink_receiver evaluate_target_ok)
- DO_REPOSITION: param2 bit0(CHANGE_MODE) 없으면 UNSUPPORTED (Commander), COMMAND_INT의 frame은 무시,
  z를 AMSL로 사용 (navigator), lat/lon/alt 모두 NaN이면 정지
- SET_MESSAGE_INTERVAL / REQUEST_MESSAGE 처리

단독 실행: python -m drone.tests.mock_fc --port 14540
"""
import argparse
import math
import socket
import threading
import time

from drone.geo import haversine_m
from drone.mav import encode_custom_mode, mavlink

INT32_MAX = 2147483647


class _UdpPeer:
    """서버(udpin)로 보내는 최소 UDP 엔드포인트. mav = v2 dialect MAVLink(v1 강제 송신 가능)."""

    def __init__(self, dest):
        self.dest = dest
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.01)
        self.mav = mavlink.MAVLink(self, srcSystem=1, srcComponent=1)
        self.mav.robust_parsing = True
        self._queue = []

    def write(self, buf):
        try:
            self.sock.sendto(buf, self.dest)
        except OSError:
            pass

    def recv_match(self, blocking=True, timeout=0.01):
        if self._queue:
            return self._queue.pop(0)
        try:
            data, _ = self.sock.recvfrom(4096)
        except (socket.timeout, OSError):
            return None
        msgs = self.mav.parse_buffer(data) or []
        self._queue.extend(msgs[1:])
        return msgs[0] if msgs else None

    def close(self):
        self.sock.close()


class MockFC:
    def __init__(self, port=14540, v2_capable=True, speed_scale=1.0,
                 home=(37.5665000, 126.9780000, 40.0), alt_rel=10.0):
        self.port = port
        self.v2_capable = v2_capable
        self.speed_scale = speed_scale
        self.lock = threading.RLock()
        # pymavlink udpout은 Windows에서 목적지와 같은 포트로 bind해서 루프백 테스트가 꼬인다 → raw 소켓 사용
        self.conn = _UdpPeer(("127.0.0.1", port))
        self.tx_v2 = False
        self.home = dict(lat=home[0], lon=home[1], alt=home[2])
        self.lat, self.lon = home[0], home[1]
        self.alt_amsl = home[2] + alt_rel
        self.armed = True
        self.landed_state = 2  # IN_AIR
        self.main, self.sub = 4, 3  # Hold
        self.fix_type, self.sats, self.eph = 3, 12, 80
        self.heartbeat_enabled = True
        self.ack_enabled = True
        self.target = None  # dict(lat, lon, alt, speed)
        self.rates = {"HEARTBEAT": 1.0, "GLOBAL_POSITION_INT": 1.0, "GPS_RAW_INT": 0.5,
                      "SYS_STATUS": 0.5, "EXTENDED_SYS_STATE": 0.5}
        self._last_sent = {}
        self.received = []  # (type, msg dict, wire, src)
        self._stop = threading.Event()
        self._thread = None

    # ---------- 테스트 제어 ----------
    def set_mode(self, main, sub=0):
        with self.lock:
            self.main, self.sub = main, sub
            if not (main == 4 and sub == 3):
                self.target = None  # 조종사가 가져감

    def commands(self, command=None):
        with self.lock:
            return [r for r in self.received
                    if r[0] in ("COMMAND_LONG", "COMMAND_INT")
                    and (command is None or r[1]["command"] == command)]

    # ---------- lifecycle ----------
    def start(self):
        self._thread = threading.Thread(target=self._run, name="mock-fc", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.conn.close()

    def _run(self):
        last = time.time()
        while not self._stop.is_set():
            msg = self.conn.recv_match(blocking=True, timeout=0.01)
            if msg is not None:
                self._handle(msg)
            now = time.time()
            self._physics(now - last)
            last = now
            self._streams(now)

    # ---------- tx ----------
    def _v1(self):
        return not self.tx_v2

    def _send_named(self, name):
        m = self.conn.mav
        v1 = self._v1()
        boot_ms = int(time.time() * 1000) & 0xFFFFFFFF
        if name == "HEARTBEAT":
            if not self.heartbeat_enabled:
                return
            base = mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED | (
                mavlink.MAV_MODE_FLAG_SAFETY_ARMED if self.armed else 0)
            m.heartbeat_send(13, 12, base, encode_custom_mode(self.main, self.sub),
                             mavlink.MAV_STATE_ACTIVE, force_mavlink1=v1)
        elif name == "GLOBAL_POSITION_INT":
            m.global_position_int_send(boot_ms, int(self.lat * 1e7), int(self.lon * 1e7),
                                       int(self.alt_amsl * 1000), int((self.alt_amsl - self.home["alt"]) * 1000),
                                       0, 0, 0, 0, force_mavlink1=v1)
        elif name == "GPS_RAW_INT":
            m.gps_raw_int_send(int(time.time() * 1e6), self.fix_type, int(self.lat * 1e7), int(self.lon * 1e7),
                               int(self.alt_amsl * 1000), self.eph, 65535, 0, 65535, self.sats,
                               force_mavlink1=v1)
        elif name == "SYS_STATUS":
            m.sys_status_send(0, 0, 0, 500, 23800, 1250, 76, 0, 0, 0, 0, 0, 0, force_mavlink1=v1)
        elif name == "EXTENDED_SYS_STATE":
            m.extended_sys_state_send(0, self.landed_state, force_mavlink1=v1)
        elif name == "HOME_POSITION":
            m.home_position_send(int(self.home["lat"] * 1e7), int(self.home["lon"] * 1e7),
                                 int(self.home["alt"] * 1000), 0, 0, 0, [1, 0, 0, 0], 0, 0, 0,
                                 force_mavlink1=v1)

    def _streams(self, now):
        with self.lock:
            for name, hz in self.rates.items():
                if hz <= 0:
                    continue
                if now - self._last_sent.get(name, 0) >= 1.0 / hz:
                    self._last_sent[name] = now
                    self._send_named(name)

    def _ack(self, msg, command, result):
        if not self.ack_enabled:
            return
        self.conn.mav.command_ack_send(command, result, 0, 0, msg.get_srcSystem(), msg.get_srcComponent(),
                                       force_mavlink1=self._v1())

    # ---------- rx ----------
    def _handle(self, msg):
        t = msg.get_type()
        if t == "BAD_DATA":
            return
        is_v2 = msg.get_msgbuf()[0] == 0xFD
        if is_v2 and not self.v2_capable:
            return  # v1 전용 FC 흉내: v2 프레임을 해석하지 못함
        if is_v2 and not self.tx_v2:
            self.tx_v2 = True  # PX4 MAV_PROTO_VER=0(auto)
        with self.lock:
            self.received.append((t, msg.to_dict(), "v2" if is_v2 else "v1",
                                  (msg.get_srcSystem(), msg.get_srcComponent())))
            if t in ("COMMAND_LONG", "COMMAND_INT"):
                if msg.target_system != 1 or msg.target_component not in (1, 0):
                    return
                self._command(msg, t)

    def _command(self, msg, kind):
        c = msg.command
        if kind == "COMMAND_LONG":
            p = [msg.param1, msg.param2, msg.param3, msg.param4, msg.param5, msg.param6, msg.param7]
        else:
            x = float("nan") if msg.x == INT32_MAX else msg.x / 1e7
            y = float("nan") if msg.y == INT32_MAX else msg.y / 1e7
            p = [msg.param1, msg.param2, msg.param3, msg.param4, x, y, msg.z]
        if c == mavlink.MAV_CMD_SET_MESSAGE_INTERVAL:
            name = mavlink.mavlink_map[int(p[0])].msgname if int(p[0]) in mavlink.mavlink_map else None
            if name and p[1] > 0:
                self.rates[name] = 1e6 / p[1]
            self._ack(msg, c, mavlink.MAV_RESULT_ACCEPTED)
        elif c == mavlink.MAV_CMD_REQUEST_MESSAGE:
            self._ack(msg, c, mavlink.MAV_RESULT_ACCEPTED)
            if int(p[0]) == mavlink.MAVLINK_MSG_ID_HOME_POSITION:
                self._send_named("HOME_POSITION")
        elif c == mavlink.MAV_CMD_DO_REPOSITION:
            flags = int(p[1]) if math.isfinite(p[1]) else 0
            if (flags & 1) == 0 or (flags & ~1) != 0:
                self._ack(msg, c, mavlink.MAV_RESULT_UNSUPPORTED)
                return
            self.main, self.sub = 4, 3
            if all(not math.isfinite(v) for v in (p[4], p[5], p[6])):
                self.target = None  # pause
            elif math.isfinite(p[4]) and math.isfinite(p[5]):
                speed = p[0] if (math.isfinite(p[0]) and p[0] > 0) else 5.0
                alt = p[6] if math.isfinite(p[6]) else self.alt_amsl
                self.target = dict(lat=p[4], lon=p[5], alt=alt, speed=speed)
            self._ack(msg, c, mavlink.MAV_RESULT_ACCEPTED)
        elif c == mavlink.MAV_CMD_DO_SET_MODE:
            if int(p[0]) & mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED:
                self.set_mode(int(p[1]), int(p[2]))
            self._ack(msg, c, mavlink.MAV_RESULT_ACCEPTED)
        else:
            self._ack(msg, c, mavlink.MAV_RESULT_UNSUPPORTED)

    # ---------- 단순 운동 모델 ----------
    def _physics(self, dt):
        with self.lock:
            tg = self.target
            if not tg or not (self.main == 4 and self.sub == 3):
                return
            step = tg["speed"] * self.speed_scale * dt
            d = haversine_m(self.lat, self.lon, tg["lat"], tg["lon"])
            if d <= step or d < 0.01:
                self.lat, self.lon = tg["lat"], tg["lon"]
            else:
                f = step / d
                self.lat += (tg["lat"] - self.lat) * f
                self.lon += (tg["lon"] - self.lon) * f
            dz = tg["alt"] - self.alt_amsl
            zs = 1.0 * self.speed_scale * dt
            self.alt_amsl = tg["alt"] if abs(dz) <= zs else self.alt_amsl + math.copysign(zs, dz)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=14540)
    ap.add_argument("--v1-only", action="store_true")
    ap.add_argument("--speed-scale", type=float, default=1.0)
    a = ap.parse_args()
    fc = MockFC(a.port, v2_capable=not a.v1_only, speed_scale=a.speed_scale).start()
    print("mock FC -> udp 127.0.0.1:%d (Ctrl+C 종료)" % a.port, flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        fc.stop()


if __name__ == "__main__":
    main()
