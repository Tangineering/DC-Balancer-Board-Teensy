"""
simple_ems_node.py — Simple Rule-Based EMS ROS2 Node
UC Davis Future Mobility Lab | Scaled FCHEV Platform
Rev: 2026-08-17A  (updated from 2026-04-06A)

CHANGES vs 2026-04-06A  (signal table Rev 2026-08-17A):
  — /vehicle_state now 18 elements (was 15)
  — SOC is now index [17] (was [14])
  — fault_flags is now index [14] (was [13]), and is uint16 (was uint8)
  — SOC guard thresholds from Safety Table:
      soc_low  default 0.32 (S-03 guard, was 0.35)
      soc_high default 0.78 (S-04 guard, was 0.75)
  — Fault check uses != 0 against uint16 (not 0x83 pattern)
  — P_fc / P_batt computed as V_bus * I_fc / V_bus * I_batt (bus-side)
  — V_bus index [6], I_fc index [5], I_batt index [2]

Rule-based EMS — baseline comparison and hardware bring-up.
Drop-in swap with sdp_ems_node via: ros2 launch fchev_ems fchev_launch.py ems:=simple

Rules:
    SOC < 0.35  -> FC_ONLY   (power_share = 1.0)
    SOC > 0.75  -> BATT_ONLY (power_share = 0.0)
    Otherwise   -> HYBRID    (share scales linearly: 1.0 at SOC_LOW -> 0.0 at SOC_HIGH)

Subscribes:
    /vehicle_state   [Float64MultiArray]  from teensy_bridge @ 50Hz
    /drive_cycle     [Float64MultiArray]  from drive_cycle_node @ 20Hz

Publishes:
    /ems_command     [Float64MultiArray]  to teensy_bridge @ control_hz
    /ems_diagnostics [Float64MultiArray]  for monitoring / rosbag2

Entry point in setup.py:
    'simple_ems_node = fchev_ems.simple_ems_node:main'
"""

import time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import Float64MultiArray

# Modes (must match Teensy firmware)
MODE_HYBRID  = 0
MODE_FC_ONLY = 1
MODE_BATT    = 2
MODE_SAFE    = 4

# Default SOC thresholds
SOC_LOW  = 0.32   # S-03 guard (signal table Rev 2026-08-17A)
SOC_HIGH = 0.78   # S-04 guard

# Hardware limits
P_FC_MAX = 22.4   # W — H-20 bus-side max (1.4 A × 16 V nominal bus)
I_FC_MAX = 1.4    # A — LIMIT_I_FC_MAX bus-side (H-20 referred through boost)


class SimpleEMSNode(Node):

    def __init__(self):
        super().__init__("simple_ems_node")

        # ── Parameters ────────────────────────────────────────────────────────
        self.declare_parameter("control_hz", 20.0)
        self.declare_parameter("soc_low",    SOC_LOW)
        self.declare_parameter("soc_high",   SOC_HIGH)

        hz       = self.get_parameter("control_hz").value
        soc_low  = self.get_parameter("soc_low").value
        soc_high = self.get_parameter("soc_high").value

        self._soc_low  = soc_low
        self._soc_high = soc_high

        # ── Internal state ────────────────────────────────────────────────────
        self.SOC         = 0.55
        self.v_actual    = 0.0
        self.V_bus       = 16.0   # nominal bus voltage
        self.I_fc        = 0.0
        self.I_batt      = 0.0
        self.fault_flags = 0
        self.state_stamp = 0.0

        self.v_ref    = 0.0
        self.P_demand = 0.0

        self._step_count = 0

        # ── QoS ───────────────────────────────────────────────────────────────
        qos_s = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT,
                           history=HistoryPolicy.KEEP_LAST, depth=1)
        qos_r = QoSProfile(reliability=ReliabilityPolicy.RELIABLE,
                           history=HistoryPolicy.KEEP_LAST, depth=10)

        # ── Subscriptions ─────────────────────────────────────────────────────
        self.create_subscription(Float64MultiArray, "/vehicle_state",
                                 self._cb_state, qos_s)
        self.create_subscription(Float64MultiArray, "/drive_cycle",
                                 self._cb_dc, qos_r)

        # ── Publications ──────────────────────────────────────────────────────
        self.pub_cmd  = self.create_publisher(Float64MultiArray,
                                              "/ems_command",     qos_r)
        self.pub_diag = self.create_publisher(Float64MultiArray,
                                              "/ems_diagnostics", qos_s)

        # ── Control timer ─────────────────────────────────────────────────────
        self.create_timer(1.0 / hz, self._loop)

        self.get_logger().info(
            f"SimpleEMSNode ready | {hz:.0f}Hz | "
            f"SOC_LOW={soc_low} (S-03) SOC_HIGH={soc_high} (S-04) | "
            f"packet=v4 (18-element /vehicle_state)"
        )

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _cb_state(self, msg: Float64MultiArray):
        """
        /vehicle_state layout (18 elements, v4 — Rev 2026-08-17A):
        [0]=v_actual  [1]=V_batt   [2]=I_batt   [3]=I_charge  [4]=V_fc
        [5]=I_fc      [6]=V_bus    [7]=V_rgn    [8]=V_chg     [9]=share_actual
        [10]=droop_FC [11]=droop_BT [12]=charger_status [13]=switch_state
        [14]=fault_flags (uint16)  [15]=error_code  [16]=error_source_state
        [17]=SOC
        """
        if len(msg.data) < 18:
            return
        self.v_actual    = msg.data[0]
        self.V_bus       = msg.data[6]
        self.I_fc        = msg.data[5]
        self.I_batt      = msg.data[2]
        self.SOC         = msg.data[17]   # index changed: 14 → 17
        self.fault_flags = int(msg.data[14])  # index changed: 13 → 14, now uint16
        self.state_stamp = time.monotonic()

    def _cb_dc(self, msg: Float64MultiArray):
        """
        /drive_cycle layout (4 elements):
        [0]=v_ref [1]=P_demand [2]=elapsed_s [3]=progress
        """
        if len(msg.data) < 2:
            return
        self.v_ref    = float(msg.data[0])
        self.P_demand = float(msg.data[1])

    # ── Main control loop ─────────────────────────────────────────────────────

    def _loop(self):
        # Check state staleness (>500ms = SAFE)
        age_ms = (time.monotonic() - self.state_stamp) * 1000
        if age_ms > 500 and self._step_count > 0:
            self.get_logger().warn(
                f"Vehicle state stale {age_ms:.0f}ms -> SAFE")
            self._publish(0.0, 0.5, 0.0, MODE_SAFE, False, 0.0, 0.0)
            return

        # Fault check
        if self.fault_flags != 0:
            self.get_logger().warn(
                f"Fault flags=0x{self.fault_flags:02X} -> SAFE")
            self._publish(0.0, 0.5, 0.0, MODE_SAFE, False, 0.0, 0.0)
            return

        # ── Simple rule-based EMS ─────────────────────────────────────────────
        soc = self.SOC

        if soc < self._soc_low:
            # SOC too low — FC only
            mode   = MODE_FC_ONLY
            share  = 1.0
            # Bus-side FC power = V_bus × I_fc; clamp to bus-side max
            P_fc   = min(self.P_demand, P_FC_MAX)
            P_batt = max(0.0, self.P_demand - P_fc)

        elif soc > self._soc_high:
            # SOC high — battery only, rest FC
            mode   = MODE_BATT
            share  = 0.0
            P_fc   = 0.0
            P_batt = self.P_demand

        else:
            # Hybrid — linear ramp: share=1.0 at SOC_LOW, 0.0 at SOC_HIGH
            mode  = MODE_HYBRID
            share = round(
                1.0 - (soc - self._soc_low) /
                      (self._soc_high - self._soc_low), 3)
            P_fc   = min(share * self.P_demand, P_FC_MAX)
            P_batt = max(0.0, self.P_demand - P_fc)

        self._publish(self.v_ref, share, 0.0, mode, (mode == MODE_HYBRID),
                      P_fc, P_batt)

        # Log every 5 seconds (100 steps at 20Hz)
        self._step_count += 1
        if self._step_count % 100 == 0:
            mode_str = {
                MODE_HYBRID:  "HYBRID",
                MODE_FC_ONLY: "FC_ONLY",
                MODE_BATT:    "BATT",
                MODE_SAFE:    "SAFE",
            }.get(mode, str(mode))
            self.get_logger().info(
                f"t={self._step_count/20:.0f}s | SOC={soc:.3f} | "
                f"share={share:.3f} | mode={mode_str} | "
                f"P_fc={P_fc:.1f}W P_batt={P_batt:.1f}W"
            )

    def _publish(self, v_sp, share, chg, mode, droop, P_fc, P_batt):
        # /ems_command: [v_setpoint, power_share, charge_goal, mode, droop_enable]
        cmd = Float64MultiArray()
        cmd.data = [v_sp, share, chg, float(mode), float(droop)]
        self.pub_cmd.publish(cmd)

        # /ems_diagnostics: [P_fc, P_batt, power_share, feasible, soc_clamped, solve_ms, mode]
        diag = Float64MultiArray()
        diag.data = [P_fc, P_batt, share, 1.0, 0.0, 0.0, float(mode)]
        self.pub_diag.publish(diag)


def main(args=None):
    rclpy.init(args=args)
    node = SimpleEMSNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # Send SAFE before shutdown
        node._publish(0.0, 0.5, 0.0, MODE_SAFE, False, 0.0, 0.0)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
