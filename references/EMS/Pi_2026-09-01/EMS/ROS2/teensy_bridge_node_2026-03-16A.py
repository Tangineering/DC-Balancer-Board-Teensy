"""
teensy_bridge_node.py — Teensy 4.1 UDP ↔ ROS 2 Bridge
UC Davis Future Mobility Lab | Scaled FCHEV Platform
Rev: 2026-03-16A

This node is the ONLY piece of code that talks to the Teensy over UDP.
Everything else in the ROS 2 graph uses topics.

Subscriptions:
    /ems_command  [std_msgs/Float64MultiArray]
        data = [v_setpoint, power_share, charge_goal, mode, droop_enable]
        Published by sdp_ems_node (or fuzzy_ems_node, smpc_ems_node)

Publications:
    /vehicle_state  [std_msgs/Float64MultiArray]  @ 50 Hz
        data = [v_actual, V_batt, I_batt, I_charge, V_fc, I_fc,
                V_bus, P_motor, share_echo, share_actual,
                droop_FC, droop_BT, charger_status, fault_flags, SOC]

    /comms_status  [std_msgs/Float64MultiArray]  @ 1 Hz
        data = [packets_rx, packets_dropped, last_rx_age_ms, link_ok]

Install in workspace:
    ~/ros2_ws/src/fchev_ems/fchev_ems/teensy_bridge_node.py

Entry point in setup.py:
    'teensy_bridge = fchev_ems.teensy_bridge_node:main'
"""

import socket
import struct
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import Float64MultiArray

# ── Packet constants (must match Teensy firmware exactly) ─────────────────────
TEENSY_HEADER  = 0xAA
PI_HEADER      = 0xBB

T2P_FMT  = "<BIH" + "f" * 10 + "HHBBB"   # Teensy → Pi: 54 bytes
T2P_SIZE = struct.calcsize(T2P_FMT)        # 54

P2T_FMT  = "<BIHfffBBB"                   # Pi → Teensy: 22 bytes
P2T_SIZE = struct.calcsize(P2T_FMT)        # 22

assert T2P_SIZE == 54
assert P2T_SIZE == 22

# ── UDP config ─────────────────────────────────────────────────────────────────
DEFAULT_TEENSY_IP  = "192.168.1.50"
DEFAULT_LISTEN_IP  = "0.0.0.0"
TEENSY_TX_PORT     = 5000   # Teensy sends here
TEENSY_RX_PORT     = 5001   # Teensy listens here
UDP_POLL_TIMEOUT   = 0.002  # s — tight poll for 50 Hz

# ── Safety ─────────────────────────────────────────────────────────────────────
TEENSY_STALE_MS    = 500    # ms — publish fault if no packet
PI_WATCHDOG_MS     = 500    # ms — Teensy safe-mode trigger (firmware side)

MODE_SAFE = 4


def _xor(data: bytes) -> int:
    r = 0
    for b in data:
        r ^= b
    return r


def soc_from_vbatt(v: float) -> float:
    """2S LiPo SOC estimate from terminal voltage."""
    if v >= 8.40: return 1.00
    if v >= 8.10: return 0.90
    if v >= 7.80: return 0.75
    if v >= 7.60: return 0.60
    if v >= 7.40: return 0.50
    if v >= 7.20: return 0.35
    if v >= 7.00: return 0.20
    if v >= 6.60: return 0.10
    return 0.05


class TeensyBridgeNode(Node):

    def __init__(self):
        super().__init__("teensy_bridge_node")

        # ── Parameters ────────────────────────────────────────────────────────
        self.declare_parameter("teensy_ip",    DEFAULT_TEENSY_IP)
        self.declare_parameter("publish_hz",   50.0)
        self.declare_parameter("comms_hz",     1.0)

        teensy_ip   = self.get_parameter("teensy_ip").value
        publish_hz  = self.get_parameter("publish_hz").value
        comms_hz    = self.get_parameter("comms_hz").value

        self._teensy_addr = (teensy_ip, TEENSY_RX_PORT)

        # ── QoS ───────────────────────────────────────────────────────────────
        qos_sensor = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        qos_reliable = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )

        # ── Publishers ────────────────────────────────────────────────────────
        self._pub_state = self.create_publisher(
            Float64MultiArray, "/vehicle_state", qos_sensor
        )
        self._pub_comms = self.create_publisher(
            Float64MultiArray, "/comms_status", qos_reliable
        )

        # ── Subscriber: EMS command ───────────────────────────────────────────
        self._sub_cmd = self.create_subscription(
            Float64MultiArray,
            "/ems_command",
            self._cb_ems_command,
            qos_reliable,
        )

        # ── Internal state ────────────────────────────────────────────────────
        self._last_state: list = [0.0] * 15   # 15 fields in /vehicle_state
        self._last_rx_ms: float = 0.0
        self._pkt_counter_prev: int = -1
        self._pkts_rx:   int = 0
        self._pkts_drop: int = 0
        self._tx_counter: int = 0
        self._last_cmd: tuple = (0.0, 0.5, 0.0, MODE_SAFE, 0)

        # ── UDP sockets ───────────────────────────────────────────────────────
        self._rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rx_sock.bind((DEFAULT_LISTEN_IP, TEENSY_TX_PORT))
        self._rx_sock.settimeout(UDP_POLL_TIMEOUT)

        self._tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # ── UDP receive thread (runs at full speed, independent of ROS timer) -
        self._running = True
        self._rx_thread = threading.Thread(target=self._udp_rx_loop, daemon=True)
        self._rx_thread.start()

        # ── ROS timers ────────────────────────────────────────────────────────
        self._pub_timer   = self.create_timer(1.0 / publish_hz, self._publish_state)
        self._comms_timer = self.create_timer(1.0 / comms_hz,   self._publish_comms)
        # Watchdog: send SAFE if no EMS command for PI_WATCHDOG_MS
        self._last_cmd_time = time.monotonic()
        self._wd_timer = self.create_timer(0.1, self._watchdog_check)

        self.get_logger().info(
            f"TeensyBridgeNode ready | Teensy={teensy_ip} | "
            f"rx=:{TEENSY_TX_PORT} tx=:{TEENSY_RX_PORT} | "
            f"pub={publish_hz:.0f}Hz"
        )

    # ── UDP receive loop (background thread) ──────────────────────────────────
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
            if _xor(chunk[1:-1]) != chunk[-1]:
                self.get_logger().debug("Checksum mismatch")
                continue
            try:
                (_, ts, ctr,
                 v, Vb, Ib, Ic, Vfc, Ifc, Vbus, Pmot, she, sha,
                 dFC, dBT, chg, flt, _) = struct.unpack(T2P_FMT, chunk)
            except struct.error:
                continue

            # Dropped packet detection
            if self._pkt_counter_prev >= 0:
                gap = (ctr - self._pkt_counter_prev) & 0xFFFF
                if gap > 1:
                    self._pkts_drop += gap - 1
                    self.get_logger().warning(
                        f"Dropped {gap-1} Teensy packets "
                        f"(total: {self._pkts_drop})"
                    )
            self._pkt_counter_prev = ctr
            self._pkts_rx += 1
            self._last_rx_ms = time.monotonic() * 1000

            # Store as flat list for /vehicle_state
            # [v, Vb, Ib, Ic, Vfc, Ifc, Vbus, Pmot, she, sha, dFC, dBT, chg, flt, SOC]
            soc = soc_from_vbatt(Vb)
            self._last_state = [
                v, Vb, Ib, Ic, Vfc, Ifc, Vbus, Pmot,
                she, sha, float(dFC), float(dBT),
                float(chg), float(flt), soc
            ]
            return

    # ── EMS command callback ───────────────────────────────────────────────────
    def _cb_ems_command(self, msg: Float64MultiArray):
        """
        Receives EMS command from sdp_ems_node (or any EMS node).
        data = [v_setpoint, power_share, charge_goal, mode, droop_enable]
        Sends it to Teensy immediately over UDP.
        """
        if len(msg.data) < 5:
            self.get_logger().warning("EMS command msg too short")
            return

        v_sp       = float(msg.data[0])
        pshare     = float(msg.data[1])
        chg        = float(msg.data[2])
        mode       = int(msg.data[3])
        droop_en   = bool(msg.data[4])

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

    # ── Watchdog: send SAFE if EMS node stops publishing ──────────────────────
    def _watchdog_check(self):
        age_ms = (time.monotonic() - self._last_cmd_time) * 1000
        if age_ms > PI_WATCHDOG_MS:
            self._send_udp_cmd(0.0, 0.5, 0.0, MODE_SAFE, False)
            self.get_logger().warning(
                f"No EMS command for {age_ms:.0f}ms -> SAFE mode sent to Teensy"
            )

    # ── Publish /vehicle_state ─────────────────────────────────────────────────
    def _publish_state(self):
        age_ms = time.monotonic() * 1000 - self._last_rx_ms
        if age_ms > TEENSY_STALE_MS and self._pkts_rx > 0:
            self.get_logger().warning(
                f"Teensy telemetry stale ({age_ms:.0f}ms)"
            )
            # Inject fault flag to tell EMS nodes to go safe
            state = list(self._last_state)
            state[13] = 128.0   # bit 7 = COMMS_STALE synthetic fault
            self._last_state = state

        msg = Float64MultiArray()
        msg.data = self._last_state
        self._pub_state.publish(msg)

    # ── Publish /comms_status ──────────────────────────────────────────────────
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
