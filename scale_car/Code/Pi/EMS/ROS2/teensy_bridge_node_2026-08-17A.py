"""
teensy_bridge_node.py — Teensy 4.1 UDP ↔ ROS 2 Bridge
UC Davis Future Mobility Lab | Scaled FCHEV Platform
Rev: 2026-08-17A  (updated from 2026-03-16A)

CHANGES vs 2026-03-16A  (signal table Rev 2026-08-17A, firmware v14):
  — Packet size: 54 → 58 bytes (TELEMETRY_VERSION 4)
  — T2P_FMT updated: added V_rgn, V_chg, switch_state, error_code,
    error_source_state; fault_flags widened uint8 → uint16
  — V_rgn (byte 35) replaces P_motor_actual
  — V_chg (byte 39) replaces power_share_echo (share_echo)
  — switch_state (byte 52): new RT1987 power-path bitmask
  — fault_flags (bytes 53-54): uint16 LE (was uint8)
  — error_code (byte 55): new latched State-99 cause
  — error_source_state (byte 56): new mainState at fault time
  — checksum: XOR bytes 1-56 (was 1-52)
  — /vehicle_state now 18 elements (was 15)
  — Fault stale synthetic flag updated for uint16 (0x8000)
  — LIMIT_I_FC_MAX updated to 1.4 A bus-side (H-20 referred through boost)
  — V_BUS_NOMINAL updated to 16.0 V (was 18 V) — stale value removed
  — P_fc_actual / P_batt_actual computed on Pi (not in packet)

/vehicle_state layout (18 elements):
  [0]  v_actual          m/s   flywheel surface speed
  [1]  V_batt            V     2S LiPo terminal voltage
  [2]  I_batt            A     battery bus-side discharge current (unipolar)
  [3]  I_charge          A     Ag105 MPPT charge current
  [4]  V_fc              V     fuel cell stack voltage
  [5]  I_fc              A     FC bus-side boost output current
  [6]  V_bus             V     DC bus voltage (nominal 16.0 V)
  [7]  V_rgn             V     regen node voltage (NEW — replaces P_motor)
  [8]  V_chg             V     charger input voltage (NEW — replaces share_echo)
  [9]  power_share_actual —    I_fc / (I_fc + I_batt)
  [10] droop_FC          cnts  FC MDAC droop gain (Q16)
  [11] droop_BT          cnts  BT MDAC droop gain (Q16)
  [12] charger_status    bits  Ag105 Table-6 status byte
  [13] switch_state      bits  RT1987 power-path bitmask (NEW)
  [14] fault_flags       bits  uint16 fault bitmask (extended)
  [15] error_code        enum  latched State-99 cause (NEW)
  [16] error_source_state enum mainState at fault time (NEW)
  [17] SOC               —     estimated from V_batt (Pi-side)

  Derived (not in /vehicle_state — publish separately or compute in EMS):
    P_fc_actual   = V_bus * I_fc
    P_batt_actual = V_bus * I_batt
"""

import socket
import struct
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import Float64MultiArray

# ── Packet constants (must match Teensy firmware v14 exactly) ─────────────────
TEENSY_HEADER = 0xAA
PI_HEADER     = 0xBB

# Teensy → Pi  58 bytes  (v4 layout, Rev 2026-08-17A)
# B   = uint8   (1 byte)
# I   = uint32  (4 bytes)
# H   = uint16  (2 bytes)
# f   = float32 (4 bytes)
#
# Byte  0: header       uint8
# Bytes 1-4: timestamp  uint32
# Bytes 5-6: pkt_ctr    uint16
# Bytes 7-10:  v_actual  float
# Bytes 11-14: V_batt    float
# Bytes 15-18: I_batt    float
# Bytes 19-22: I_charge  float
# Bytes 23-26: V_fc      float
# Bytes 27-30: I_fc      float
# Bytes 31-34: V_bus     float
# Bytes 35-38: V_rgn     float  (NEW — replaces P_motor_actual)
# Bytes 39-42: V_chg     float  (NEW — replaces power_share_echo)
# Bytes 43-46: power_share_actual float
# Bytes 47-48: droop_FC  uint16
# Bytes 49-50: droop_BT  uint16
# Byte  51: charger_status uint8
# Byte  52: switch_state   uint8  (NEW)
# Bytes 53-54: fault_flags uint16 (was uint8)
# Byte  55: error_code     uint8  (NEW)
# Byte  56: error_source_state uint8 (NEW)
# Byte  57: checksum       uint8  XOR bytes 1-56
T2P_FMT  = "<BIH" + "f" * 10 + "HHBBHBBB"
T2P_SIZE = struct.calcsize(T2P_FMT)
# Trace: B(1)+I(4)+H(2)+10f(40)+HH(4)+BB(2)+H(2)+BB(2)+B(1) = 58
assert T2P_SIZE == 58, f"T2P_SIZE={T2P_SIZE}, expected 58"

# Pi → Teensy  22 bytes  (layout UNCHANGED)
P2T_FMT  = "<BIHfffBBB"
P2T_SIZE = struct.calcsize(P2T_FMT)
assert P2T_SIZE == 22, f"P2T_SIZE={P2T_SIZE}, expected 22"

# ── UDP config ─────────────────────────────────────────────────────────────────
DEFAULT_TEENSY_IP = "192.168.1.50"
DEFAULT_LISTEN_IP = "0.0.0.0"
TEENSY_TX_PORT    = 5000   # Teensy sends here
TEENSY_RX_PORT    = 5001   # Teensy listens here
UDP_POLL_TIMEOUT  = 0.002  # s

# ── Safety thresholds (updated for firmware v14) ───────────────────────────────
TEENSY_STALE_MS   = 500    # ms — comms fault if no packet
PI_WATCHDOG_MS    = 500    # ms — Teensy triggers FAULT_PI_TIMEOUT after this
MODE_SAFE         = 4

# Fault flag bitmask (uint16 — extended in v14)
FAULT_OC_FC          = 0x0001
FAULT_UV_BATT        = 0x0002
FAULT_OV_BUS         = 0x0004
FAULT_SWITCH_CONFLICT= 0x0008
FAULT_PI_TIMEOUT     = 0x0010
FAULT_OV_BATT        = 0x0020
FAULT_UV_FC          = 0x0040
FAULT_OC_BT          = 0x0080
FAULT_UV_BUS         = 0x0100
FAULT_OV_RGN         = 0x0200
FAULT_OV_CHG         = 0x0400
FAULT_I2C_CHARGER    = 0x0800
FAULT_CHARGER_STAT   = 0x1000
FAULT_INIT_FAIL      = 0x2000
FAULT_MOT_HOTPLUG    = 0x4000
FAULT_ERROR          = 0x8000  # latch marker

# Synthetic fault injected by Pi when Teensy comms stale
FAULT_COMMS_STALE    = 0x8000  # reuse ERROR bit as comms-stale indicator


def _xor(data: bytes) -> int:
    r = 0
    for b in data:
        r ^= b
    return r


# ── SOC estimation ────────────────────────────────────────────────────────────
# Replaces the nine-step lookup on instantaneous V_batt. That table stepped SOC by
# 0.15 on a few millivolts of ripple, which is physically impossible for a 2S LiPo
# and fed a bang-bang reference straight into the EMS share rule. Worse, its break
# points look like LOADED terminal voltages (7.40 V -> 0.50), so it was reading
# IR drop as discharge.
#
# This is coulomb counting for the dynamics, with a slow OCV correction to stop
# the integrator drifting. Standard structure; nothing clever.

# 2S 18650 Li-ion open-circuit voltage -> SOC. Monotonic, interpolated.
# Pack: Buddy RC, 2S 18650, 5000 mAh / 36 Wh, nominal 7.2 V (3.6 V/cell),
# charge cutoff 8.2-8.4 V. Typical NMC 18650 shape, doubled for 2S.
#
# NOT a LiPo curve — 18650 cells sit lower through the mid-range (7.46 V is
# ~50% here against ~18% on a LiPo curve), so using the wrong one biases SOC
# badly exactly where the EMS thresholds live.
#
# STARTING POINT ONLY — calibrate with a slow rested discharge on your pack.
OCV_CURVE = [
    (6.00, 0.00), (6.60, 0.05), (6.82, 0.10), (7.02, 0.20), (7.18, 0.30),
    (7.32, 0.40), (7.46, 0.50), (7.62, 0.60), (7.78, 0.70), (7.96, 0.80),
    (8.16, 0.90), (8.40, 1.00),
]


def soc_from_ocv(v: float) -> float:
    """Linear interpolation on OCV_CURVE. Clamped at both ends."""
    if v <= OCV_CURVE[0][0]:
        return OCV_CURVE[0][1]
    if v >= OCV_CURVE[-1][0]:
        return OCV_CURVE[-1][1]
    for (v0, s0), (v1, s1) in zip(OCV_CURVE, OCV_CURVE[1:]):
        if v <= v1:
            return s0 + (s1 - s0) * (v - v0) / (v1 - v0)
    return OCV_CURVE[-1][1]


class SOCEstimator:
    """
    Coulomb counting + OCV correction.

    CURRENT REFERENCE FRAME — the thing most likely to be wrong here.
    The INA253 shunts sit between each boost's VOUT and VBUS, so I_batt is a
    BUS-SIDE current. Coulombs leave the pack on the BATTERY side, which at
    V_bus 15.8 / V_batt 8.1 / eta 0.9 is about 2.17x larger. Counting bus-side
    amps would make SOC fall roughly half as fast as it really does.

        I_pack = I_batt * V_bus / (V_batt * eta)

    I_charge comes from the Ag105 over I2C and is ASSUMED battery-side here.
    If it turns out to be bus-side, scale it the same way — check before
    trusting any charging run.
    """

    def __init__(self, capacity_ah, r_int, eta,
                 k_rest, k_load, rest_i, rest_s):
        self.q_as     = capacity_ah * 3600.0      # amp-seconds
        self.r_int    = r_int
        self.eta      = max(0.1, eta)
        self.k_rest   = k_rest                    # OCV pull per second, at rest
        self.k_load   = k_load                    # OCV pull per second, under load
        self.rest_i   = rest_i
        self.rest_s   = rest_s
        self.soc      = None
        self._rest_for = 0.0

    def seed(self, v_batt: float, soc_init: float = -1.0):
        self.soc = soc_from_ocv(v_batt) if soc_init < 0.0 else soc_init
        return self.soc

    def update(self, dt, v_batt, i_batt_bus, i_charge, v_bus):
        if self.soc is None:
            self.seed(v_batt)
        if dt <= 0.0 or dt > 1.0:        # startup, or a telemetry gap: skip
            return self.soc

        # Bus-side -> pack-side
        if v_batt > 1.0:
            i_pack = abs(i_batt_bus) * v_bus / (v_batt * self.eta)
        else:
            i_pack = 0.0
        i_net = i_pack - max(0.0, i_charge)        # + = net discharge

        # 1. Coulomb counting (the dynamics)
        if self.q_as > 0.0:
            self.soc -= i_net * dt / self.q_as

        # 2. OCV correction (the anchor)
        #    At rest V_batt is OCV directly. Under load, back it out through
        #    R_int — less trustworthy, so the gain drops by design.
        if abs(i_net) < self.rest_i:
            self._rest_for += dt
        else:
            self._rest_for = 0.0

        if self._rest_for >= self.rest_s:
            target = soc_from_ocv(v_batt)
            k = self.k_rest
        else:
            target = soc_from_ocv(v_batt + i_net * self.r_int)
            k = self.k_load
        self.soc += k * dt * (target - self.soc)

        self.soc = min(1.0, max(0.0, self.soc))
        return self.soc


class TeensyBridgeNode(Node):

    def __init__(self):
        super().__init__("teensy_bridge_node")

        # ── Parameters ────────────────────────────────────────────────────────
        self.declare_parameter("teensy_ip",  DEFAULT_TEENSY_IP)
        self.declare_parameter("publish_hz", 50.0)
        self.declare_parameter("comms_hz",   1.0)

        # ── SOC estimator ─────────────────────────────────────────────────────
        # pack_capacity_ah MUST be set to the real pack. Left at 0.0 the coulomb
        # integrator is disabled and SOC falls back to OCV tracking alone, which
        # is smooth but has no dynamics — the node warns loudly at startup.
        self.declare_parameter("pack_capacity_ah", 5.0)    # Buddy RC 2S 18650, 36 Wh
        self.declare_parameter("pack_r_int_ohm",   0.050)  # TODO measure, see below
        self.declare_parameter("boost_efficiency", 0.90)
        self.declare_parameter("soc_init",        -1.0)    # <0 = seed from OCV
        self.declare_parameter("soc_k_rest",       0.050)  # OCV pull /s at rest
        self.declare_parameter("soc_k_load",       0.002)  # OCV pull /s on load
        self.declare_parameter("soc_rest_i_a",     0.050)
        self.declare_parameter("soc_rest_s",       3.0)
        # Below this total current the FC/battery split is not meaningful, so
        # power_share_actual holds rather than reporting ratio noise.
        self.declare_parameter("share_min_i_a",    0.05)

        teensy_ip  = self.get_parameter("teensy_ip").value
        publish_hz = self.get_parameter("publish_hz").value
        comms_hz   = self.get_parameter("comms_hz").value

        cap_ah = float(self.get_parameter("pack_capacity_ah").value)
        self._soc = SOCEstimator(
            capacity_ah = cap_ah,
            r_int       = float(self.get_parameter("pack_r_int_ohm").value),
            eta         = float(self.get_parameter("boost_efficiency").value),
            k_rest      = float(self.get_parameter("soc_k_rest").value),
            k_load      = float(self.get_parameter("soc_k_load").value),
            rest_i      = float(self.get_parameter("soc_rest_i_a").value),
            rest_s      = float(self.get_parameter("soc_rest_s").value),
        )
        self._soc_t_prev = 0.0
        self._share_min_i = float(self.get_parameter("share_min_i_a").value)
        self._share_last  = 0.5          # neutral until a real split is seen
        _si = float(self.get_parameter("soc_init").value)
        if _si >= 0.0:
            self._soc.seed(0.0, _si)
        if cap_ah <= 0.0:
            self.get_logger().warning(
                "pack_capacity_ah is 0 — coulomb counting DISABLED, SOC is "
                "OCV-tracking only. Set it to the real pack capacity.")
        else:
            self.get_logger().info(
                f"SOC: coulomb counting, {cap_ah:.2f} Ah, "
                f"R_int {self.get_parameter('pack_r_int_ohm').value} ohm")

        self._teensy_addr = (teensy_ip, TEENSY_RX_PORT)

        # ── QoS ───────────────────────────────────────────────────────────────
        qos_sensor = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST, depth=1)
        qos_reliable = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST, depth=10)

        # ── Publishers ────────────────────────────────────────────────────────
        self._pub_state = self.create_publisher(
            Float64MultiArray, "/vehicle_state", qos_sensor)
        self._pub_comms = self.create_publisher(
            Float64MultiArray, "/comms_status", qos_reliable)

        # ── Subscriber ────────────────────────────────────────────────────────
        self._sub_cmd = self.create_subscription(
            Float64MultiArray, "/ems_command",
            self._cb_ems_command, qos_reliable)

        # ── Internal state ────────────────────────────────────────────────────
        self._last_state: list = [0.0] * 18   # 18 fields in /vehicle_state
        self._last_rx_ms: float = 0.0
        self._pkt_counter_prev: int = -1
        self._pkts_rx:   int = 0
        self._pkts_drop: int = 0
        self._tx_counter: int = 0
        self._last_cmd: tuple = (0.0, 0.5, 0.0, MODE_SAFE, 0)
        self._last_cmd_time: float = time.monotonic()

        # ── UDP sockets ───────────────────────────────────────────────────────
        self._rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rx_sock.bind((DEFAULT_LISTEN_IP, TEENSY_TX_PORT))
        self._rx_sock.settimeout(UDP_POLL_TIMEOUT)

        self._tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # ── UDP receive thread ────────────────────────────────────────────────
        self._running = True
        self._rx_thread = threading.Thread(
            target=self._udp_rx_loop, daemon=True)
        self._rx_thread.start()

        # ── ROS timers ────────────────────────────────────────────────────────
        self._pub_timer   = self.create_timer(
            1.0 / publish_hz, self._publish_state)
        self._comms_timer = self.create_timer(
            1.0 / comms_hz, self._publish_comms)
        self._wd_timer    = self.create_timer(0.1, self._watchdog_check)

        self.get_logger().info(
            f"TeensyBridgeNode ready | Teensy={teensy_ip} | "
            f"rx=:{TEENSY_TX_PORT} tx=:{TEENSY_RX_PORT} | "
            f"pub={publish_hz:.0f}Hz | packet=v4 (58 bytes)"
        )

    # ── UDP receive loop ──────────────────────────────────────────────────────
    def _udp_rx_loop(self):
        while self._running:
            try:
                data, _ = self._rx_sock.recvfrom(128)
                self._parse_and_store(data)
            except socket.timeout:
                pass
            except Exception as e:
                self.get_logger().error(f"UDP rx error: {e}")

    def _parse_and_store(self, data: bytes):
        if len(data) < T2P_SIZE:
            return
        for s in range(len(data) - T2P_SIZE + 1):
            if data[s] != TEENSY_HEADER:
                continue
            chunk = data[s:s + T2P_SIZE]
            # Checksum: XOR bytes 1-56 (all except header and checksum)
            if _xor(chunk[1:-1]) != chunk[-1]:
                self.get_logger().debug("Checksum mismatch — packet dropped")
                continue
            try:
                (_, ts, ctr,
                 v, Vb, Ib, Ic, Vfc, Ifc, Vbus,
                 Vrgn,                # NEW — regen node voltage (replaces P_motor)
                 Vchg,                # NEW — charger input voltage (replaces share_echo)
                 sha,                 # power_share_actual
                 dFC, dBT,           # droop gains uint16
                 chg_status,         # charger_status uint8
                 sw_state,           # switch_state uint8 (NEW)
                 flt,                # fault_flags uint16 (was uint8)
                 err_code,           # error_code uint8 (NEW)
                 err_src,            # error_source_state uint8 (NEW)
                 _cs,                # checksum
                 ) = struct.unpack(T2P_FMT, chunk)
            except struct.error as e:
                self.get_logger().debug(f"Unpack error: {e}")
                continue

            # Dropped packet detection
            if self._pkt_counter_prev >= 0:
                gap = (ctr - self._pkt_counter_prev) & 0xFFFF
                if gap > 1:
                    self._pkts_drop += gap - 1
                    self.get_logger().warning(
                        f"Dropped {gap-1} Teensy packets "
                        f"(total: {self._pkts_drop})")
            self._pkt_counter_prev = ctr
            self._pkts_rx += 1
            self._last_rx_ms = time.monotonic() * 1000

            # power_share_actual — recomputed with a usable low-current guard.
            # The Teensy computes it as |I_fc|/(|I_fc|+|I_batt|) behind a
            # `totalA > 1e-6` test, which is far too permissive: at a few tens of
            # milliamps the ratio is pure noise and swings 0..1, which is what
            # fills the share trace with hash whenever the car is stationary.
            # Below the threshold the split is meaningless, so hold the last
            # meaningful value instead of publishing noise.
            #
            # NOTE this fixes telemetry and logging only. The Teensy's own Youla
            # controller still feeds on its unguarded copy — the firmware guard
            # is the real fix.
            _tot = abs(Ifc) + abs(Ib)
            if _tot > self._share_min_i:
                self._share_last = abs(Ifc) / _tot
            sha = self._share_last

            # SOC — coulomb counting with OCV correction (see SOCEstimator)
            _now_s = time.monotonic()
            _dt = (_now_s - self._soc_t_prev) if self._soc_t_prev else 0.0
            self._soc_t_prev = _now_s
            soc = self._soc.update(_dt, Vb, Ib, Ic, Vbus)

            # /vehicle_state — 18 elements (v4)
            # [0]  v_actual
            # [1]  V_batt
            # [2]  I_batt
            # [3]  I_charge
            # [4]  V_fc
            # [5]  I_fc
            # [6]  V_bus
            # [7]  V_rgn          NEW (replaces P_motor_actual)
            # [8]  V_chg          NEW (replaces share_echo)
            # [9]  share_actual
            # [10] droop_FC
            # [11] droop_BT
            # [12] charger_status
            # [13] switch_state   NEW
            # [14] fault_flags    (uint16 — extended)
            # [15] error_code     NEW
            # [16] error_source_state NEW
            # [17] SOC
            self._last_state = [
                float(v),
                float(Vb),
                float(Ib),
                float(Ic),
                float(Vfc),
                float(Ifc),
                float(Vbus),
                float(Vrgn),
                float(Vchg),
                float(sha),
                float(dFC),
                float(dBT),
                float(chg_status),
                float(sw_state),
                float(flt),
                float(err_code),
                float(err_src),
                float(soc),
            ]
            return

    # ── EMS command callback ──────────────────────────────────────────────────
    def _cb_ems_command(self, msg: Float64MultiArray):
        if len(msg.data) < 5:
            self.get_logger().warning("EMS command msg too short")
            return
        v_sp     = float(msg.data[0])
        pshare   = float(msg.data[1])
        chg      = float(msg.data[2])
        mode     = int(msg.data[3])
        droop_en = bool(msg.data[4])
        self._last_cmd = (v_sp, pshare, chg, mode, droop_en)
        self._last_cmd_time = time.monotonic()
        self._send_udp_cmd(v_sp, pshare, chg, mode, droop_en)

    def _send_udp_cmd(self, v_sp, pshare, chg, mode, droop_en):
        ts = int(time.monotonic() * 1000) & 0xFFFFFFFF
        payload = struct.pack(
            "<BIHfffBB",
            PI_HEADER, ts, self._tx_counter & 0xFFFF,
            float(v_sp), float(pshare), float(chg),
            int(mode), int(droop_en),
        )
        pkt = payload + struct.pack("B", _xor(payload[1:]))
        self._tx_sock.sendto(pkt, self._teensy_addr)
        self._tx_counter = (self._tx_counter + 1) & 0xFFFF

    # ── Watchdog ──────────────────────────────────────────────────────────────
    def _watchdog_check(self):
        age_ms = (time.monotonic() - self._last_cmd_time) * 1000
        if age_ms > PI_WATCHDOG_MS:
            self._send_udp_cmd(0.0, 0.5, 0.0, MODE_SAFE, False)
            self.get_logger().warning(
                f"No EMS command for {age_ms:.0f}ms -> SAFE mode sent to Teensy")

    # ── Publish /vehicle_state ────────────────────────────────────────────────
    def _publish_state(self):
        age_ms = time.monotonic() * 1000 - self._last_rx_ms
        if age_ms > TEENSY_STALE_MS and self._pkts_rx > 0:
            self.get_logger().warning(
                f"Teensy telemetry stale ({age_ms:.0f}ms)")
            state = list(self._last_state)
            state[14] = float(FAULT_COMMS_STALE)  # inject comms fault
            self._last_state = state

        msg = Float64MultiArray()
        msg.data = self._last_state
        self._pub_state.publish(msg)

    # ── Publish /comms_status ─────────────────────────────────────────────────
    def _publish_comms(self):
        age_ms  = time.monotonic() * 1000 - self._last_rx_ms
        link_ok = 1.0 if age_ms < TEENSY_STALE_MS else 0.0
        msg = Float64MultiArray()
        msg.data = [
            float(self._pkts_rx),
            float(self._pkts_drop),
            float(age_ms),
            link_ok,
        ]
        self._pub_comms.publish(msg)
        if self._pkts_rx % 500 == 0 and self._pkts_rx > 0:
            self.get_logger().info(
                f"Comms: rx={self._pkts_rx} dropped={self._pkts_drop} "
                f"age={age_ms:.0f}ms link={'OK' if link_ok else 'DOWN'}"
            )

    # ── Cleanup ───────────────────────────────────────────────────────────────
    def destroy_node(self):
        self._running = False
        self._send_udp_cmd(0.0, 0.0, 0.0, MODE_SAFE, False)
        self.get_logger().info("Bridge shutdown — SAFE sent to Teensy")
        self._rx_sock.close()
        self._tx_sock.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = TeensyBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
