"""
sweep_ems_node.py — Power-Share Sweep EMS (characterisation node)
UC Davis Future Mobility Lab | Scaled FCHEV Platform
Rev: 2026-09-07A

PURPOSE
    This is a DIAGNOSTIC node, not an energy management strategy. It ignores
    SOC entirely and sweeps power_share across its range on a fixed period so
    you can watch commanded vs achieved share without waiting for SOC to drift.

    Use it to answer: does the droop loop actually track what the EMS asks for,
    and how fast?

    Compare /ems_command[1] (commanded) against /vehicle_state[9] (achieved).

WHY IT HOLDS A CONSTANT SPEED
    share_actual = I_fc / (I_fc + I_batt). With the car stationary both
    currents are ~0 and that ratio is numerical noise. A steady load makes
    share the only variable changing, so the step/ramp response is clean.
    Set v_hold to something that draws real current.

WAVEFORMS
    triangle   — ramps share_min -> share_max -> share_min over `period_s`.
                 Shows continuous tracking lag and any hysteresis.
    staircase  — holds each of `n_steps` levels for period_s/n_steps.
                 Shows per-step rise time and steady-state error. Usually the
                 more informative of the two for controller characterisation.

SAFETY
    Same guards as simple_ems_node: commands SAFE on any nonzero fault_flags,
    on stale vehicle_state, and on shutdown. The sweep does not override those.

    Default share range is [0.15, 0.85], NOT [0, 1]. The extremes correspond to
    fully cutting off one source; the firmware governor warns about bus-switch
    opening under load below DROOP_R_MIN. Widen only deliberately.

Install:
    ~/ros2_ws/src/fchev_ems/fchev_ems/sweep_ems_node.py

Entry point in setup.py:
    'sweep_ems_node = fchev_ems.sweep_ems_node:main'
"""

import math
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import Float64MultiArray

# Modes — must match Teensy firmware
MODE_HYBRID  = 0
MODE_FC_ONLY = 1
MODE_BATT    = 2
MODE_SAFE    = 4

# /vehicle_state v4 indices (Signal Table Rev 2026-08-17A)
IDX_V_ACTUAL   = 0
IDX_I_BATT     = 2
IDX_I_FC       = 5
IDX_V_BUS      = 6
IDX_SHARE_ACT  = 9
IDX_FAULTS     = 14
IDX_SOC        = 17
VEHICLE_STATE_LEN = 18

STALE_MS = 500.0


class SweepEMSNode(Node):

    def __init__(self):
        super().__init__("sweep_ems_node")

        # ── Parameters ────────────────────────────────────────────────────────
        self.declare_parameter("control_hz",  20.0)
        self.declare_parameter("period_s",    20.0)
        self.declare_parameter("share_min",    0.15)
        self.declare_parameter("share_max",    0.85)
        self.declare_parameter("waveform",    "triangle")   # or "staircase"
        self.declare_parameter("n_steps",      7)           # staircase only
        self.declare_parameter("v_hold",       1.0)         # m/s, constant load
        self.declare_parameter("use_drive_cycle", False)
        self.declare_parameter("settle_s",     3.0)         # hold share_min before sweeping

        hz              = float(self.get_parameter("control_hz").value)
        self._period    = float(self.get_parameter("period_s").value)
        self._smin      = float(self.get_parameter("share_min").value)
        self._smax      = float(self.get_parameter("share_max").value)
        self._waveform  = str(self.get_parameter("waveform").value).lower()
        self._n_steps   = int(self.get_parameter("n_steps").value)
        self._v_hold    = float(self.get_parameter("v_hold").value)
        self._use_dc    = bool(self.get_parameter("use_drive_cycle").value)
        self._settle    = float(self.get_parameter("settle_s").value)

        if self._smin < 0.0 or self._smax > 1.0 or self._smin >= self._smax:
            self.get_logger().error(
                f"Invalid share range [{self._smin}, {self._smax}] — "
                "must satisfy 0 <= min < max <= 1. Falling back to [0.15, 0.85]."
            )
            self._smin, self._smax = 0.15, 0.85

        if self._waveform not in ("triangle", "staircase"):
            self.get_logger().warning(
                f"Unknown waveform '{self._waveform}' — using triangle.")
            self._waveform = "triangle"

        # ── Vehicle state ─────────────────────────────────────────────────────
        self.v_actual    = 0.0
        self.share_act   = 0.0
        self.I_fc        = 0.0
        self.I_batt      = 0.0
        self.V_bus       = 16.0
        self.SOC         = 0.0
        self.fault_flags = 0
        self.state_stamp = 0.0

        # ── Drive cycle (only used if use_drive_cycle) ────────────────────────
        self.v_ref    = 0.0
        self.P_demand = 0.0

        # ── Timing ────────────────────────────────────────────────────────────
        self._t_start    = None      # set on first healthy loop
        self._step_count = 0
        self._cycles     = 0
        self._last_log_cycle = -1

        # ── QoS ───────────────────────────────────────────────────────────────
        qos_s = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT,
                           history=HistoryPolicy.KEEP_LAST, depth=1)
        qos_r = QoSProfile(reliability=ReliabilityPolicy.RELIABLE,
                           history=HistoryPolicy.KEEP_LAST, depth=10)

        self.create_subscription(Float64MultiArray, "/vehicle_state",
                                 self._cb_state, qos_s)
        self.create_subscription(Float64MultiArray, "/drive_cycle",
                                 self._cb_dc, qos_r)

        self.pub_cmd  = self.create_publisher(Float64MultiArray,
                                              "/ems_command", qos_r)
        self.pub_diag = self.create_publisher(Float64MultiArray,
                                              "/ems_diagnostics", qos_s)

        self.create_timer(1.0 / hz, self._loop)

        src = "drive cycle" if self._use_dc else f"constant {self._v_hold:.2f} m/s"
        extra = f" | {self._n_steps} steps" if self._waveform == "staircase" else ""
        self.get_logger().info(
            f"SweepEMSNode ready | {hz:.0f}Hz | {self._waveform}{extra} | "
            f"share {self._smin:.2f}..{self._smax:.2f} | period {self._period:.1f}s | "
            f"speed: {src}"
        )
        self.get_logger().warning(
            "DIAGNOSTIC NODE — ignores SOC entirely. Not an EMS strategy. "
            "Watch SOC yourself; this node will happily drain or overcharge."
        )

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _cb_state(self, msg: Float64MultiArray):
        if len(msg.data) < VEHICLE_STATE_LEN:
            return
        self.v_actual    = msg.data[IDX_V_ACTUAL]
        self.I_batt      = msg.data[IDX_I_BATT]
        self.I_fc        = msg.data[IDX_I_FC]
        self.V_bus       = msg.data[IDX_V_BUS]
        self.share_act   = msg.data[IDX_SHARE_ACT]
        self.fault_flags = int(msg.data[IDX_FAULTS])
        self.SOC         = msg.data[IDX_SOC]
        self.state_stamp = time.monotonic()

    def _cb_dc(self, msg: Float64MultiArray):
        if len(msg.data) < 2:
            return
        self.v_ref    = float(msg.data[0])
        self.P_demand = float(msg.data[1])

    # ── Share waveform ────────────────────────────────────────────────────────

    def _share_at(self, t: float) -> float:
        """Commanded share at elapsed time t (seconds), after settle."""
        span = self._smax - self._smin

        if t < self._settle:
            return self._smin                      # hold low while load settles

        u = (t - self._settle) % self._period      # position within one cycle
        frac = u / self._period                    # 0..1

        if self._waveform == "triangle":
            # 0 -> 1 -> 0 across the period
            tri = 2.0 * frac if frac < 0.5 else 2.0 * (1.0 - frac)
            return self._smin + span * tri

        # staircase: up the levels then back down, holding each
        n = max(2, self._n_steps)
        total = 2 * n - 2                          # up then down, no repeat at ends
        k = int(frac * total)
        k = k if k < n else total - k              # fold the descent
        return self._smin + span * (k / (n - 1))

    def _cycle_index(self, t: float) -> int:
        if t < self._settle:
            return 0
        return int((t - self._settle) / self._period)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _loop(self):
        now = time.monotonic()

        # Stale state -> SAFE (and hold the clock, so the sweep resumes cleanly)
        age_ms = (now - self.state_stamp) * 1000.0
        if self.state_stamp == 0.0 or age_ms > STALE_MS:
            if self._step_count > 0:
                self.get_logger().warning(
                    f"Vehicle state stale {age_ms:.0f}ms -> SAFE")
            self._t_start = None
            self._publish(0.0, 0.5, MODE_SAFE, False, 0.0, 0.0)
            return

        # Faults -> SAFE
        if self.fault_flags != 0:
            self.get_logger().warning(
                f"fault_flags=0x{self.fault_flags:04X} -> SAFE")
            self._t_start = None
            self._publish(0.0, 0.5, MODE_SAFE, False, 0.0, 0.0)
            return

        # Healthy — start or continue the sweep clock
        if self._t_start is None:
            self._t_start = now
            self.get_logger().info(
                f"Sweep started — settling {self._settle:.1f}s at "
                f"share={self._smin:.2f}")

        t = now - self._t_start
        share = round(self._share_at(t), 4)

        v_sp = self.v_ref if self._use_dc else self._v_hold

        # Bookkeeping for readable logs
        cyc = self._cycle_index(t)
        if cyc != self._last_log_cycle and t >= self._settle:
            self._last_log_cycle = cyc
            self.get_logger().info(f"--- sweep cycle {cyc + 1} ---")

        # Measured powers, bus-side
        P_fc   = self.V_bus * self.I_fc
        P_batt = self.V_bus * self.I_batt

        self._publish(v_sp, share, MODE_HYBRID, True, P_fc, P_batt)

        # Log a tracking line every 0.5 s
        self._step_count += 1
        if self._step_count % 10 == 0:
            err = share - self.share_act
            self.get_logger().info(
                f"t={t:6.1f}s  cmd={share:.3f}  act={self.share_act:.3f}  "
                f"err={err:+.3f} | I_fc={self.I_fc:.3f} I_bt={self.I_batt:.3f} "
                f"v={self.v_actual:.2f} SOC={self.SOC:.3f}"
            )

    def _publish(self, v_sp, share, mode, droop, P_fc, P_batt):
        cmd = Float64MultiArray()
        cmd.data = [float(v_sp), float(share), 0.0, float(mode), float(droop)]
        self.pub_cmd.publish(cmd)

        diag = Float64MultiArray()
        # [P_fc, P_batt, share_cmd, feasible, soc_clamped, solve_ms, mode]
        diag.data = [float(P_fc), float(P_batt), float(share),
                     1.0, 0.0, 0.0, float(mode)]
        self.pub_diag.publish(diag)


def main(args=None):
    rclpy.init(args=args)
    node = SweepEMSNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node._publish(0.0, 0.5, MODE_SAFE, False, 0.0, 0.0)
            node.get_logger().info("Sweep shutdown — SAFE published")
        except Exception:
            pass
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
