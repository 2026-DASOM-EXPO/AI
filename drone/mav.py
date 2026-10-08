"""pymavlink import 진입점. MAVLINK20=1 을 pymavlink import 전에 설정해야 v2 dialect가 로드된다.

v2 dialect는 v1 프레임도 파싱하고, send(..., force_mavlink1=True)로 v1 송신도 가능하므로
v1 폴백은 런타임 플래그로 처리한다(drone.link.FcLink.force_v1).
"""
import os

os.environ["MAVLINK20"] = "1"

from pymavlink import mavutil  # noqa: E402

mavlink = mavutil.mavlink

# PX4 custom_mode (src/modules/commander/px4_custom_mode.h)
MAIN_MODES = {
    1: "MANUAL", 2: "ALTCTL", 3: "POSCTL", 4: "AUTO", 5: "ACRO", 6: "OFFBOARD",
    7: "STABILIZED", 8: "RATTITUDE", 9: "SIMPLE", 10: "TERMINATION",
}
AUTO_SUB_MODES = {
    1: "READY", 2: "TAKEOFF", 3: "LOITER", 4: "MISSION", 5: "RTL", 6: "LAND",
    8: "FOLLOW_TARGET", 9: "PRECLAND", 10: "VTOL_TAKEOFF",
}
FRIENDLY = {(3, 0): "Position", (2, 0): "Altitude", (1, 0): "Manual", (7, 0): "Stabilized",
            (5, 0): "Acro", (6, 0): "Offboard", (4, 3): "Hold", (4, 4): "Mission",
            (4, 5): "Return", (4, 6): "Land", (4, 2): "Takeoff", (4, 8): "Follow Me",
            (4, 9): "Precision Land"}

HOLD_MAIN, HOLD_SUB = 4, 3


def decode_custom_mode(cm):
    main = (cm >> 16) & 0xFF
    sub = (cm >> 24) & 0xFF
    if main == 4:
        name = "AUTO_" + AUTO_SUB_MODES.get(sub, "SUB%d" % sub)
    else:
        name = MAIN_MODES.get(main, "MAIN%d" % main)
    return main, sub, name, FRIENDLY.get((main, sub if main == 4 else 0), name)


def encode_custom_mode(main, sub):
    return ((sub & 0xFF) << 24) | ((main & 0xFF) << 16)


ACK_RESULTS = {
    0: "ACCEPTED", 1: "TEMPORARILY_REJECTED", 2: "DENIED", 3: "UNSUPPORTED",
    4: "FAILED", 5: "IN_PROGRESS", 6: "CANCELLED",
}
