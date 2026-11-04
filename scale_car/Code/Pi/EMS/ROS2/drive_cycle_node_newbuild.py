"""
drive_cycle_node.py — Drive Cycle Publisher
UC Davis Future Mobility Lab | Scaled FCHEV Platform
Rev: 2026-03-16A

Loads a drive cycle CSV and publishes v_ref + P_demand at real time.
Replaces the DriveCycle class that was embedded in sdp_ems_standalone.py.

Publications:
    /drive_cycle  [std_msgs/Float64MultiArray]  @ publish_hz
        data = [v_ref_mps, P_demand_W, elapsed_s, progress_0_to_1]

    /drive_cycle_status  [std_msgs/Float64MultiArray]  @ 1 Hz
        data = [elapsed_s, total_s, progress, done_flag]

Drive cycle CSV format:
    time_s,v_mps
    0.0,0.0
    1.0,1.2
    ...

If no CSV is provided, publishes a built-in sine-wave test profile.

Install in workspace:
    ~/ros2_ws/src/fchev_ems/fchev_ems/drive_cycle_node.py

Entry point in setup.py:
    'drive_cycle_node = fchev_ems.drive_cycle_node:main'
"""

ROAD_A0, ROAD_A1, ROAD_A2, ROAD_A4 = 0.0, 4.0297, 0.4658, 1.1695
import csv
import math
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import Float64MultiArray

# ── Scaled vehicle physical constants ─────────────────────────────────────────
# New build: the road-load model is non-negative by construction and the
# full UDDS reaches 5 m/s -> ~32 W steady. Grid matches the cost-to-go.
PDEM_MIN = 0.0      # W
PDEM_MAX = 35.0     # W


class DriveCycleNode(Node):

    def __init__(self):
        super().__init__("drive_cycle_node")

        # ── Parameters ────────────────────────────────────────────────────────
        self.declare_parameter("csv_path",     "")
        # 3.5 kg = translational mass plus the flywheel's rotating inertia
        # referred to translation, at its current position (Sid, 2026-10-29).
        self.declare_parameter("vehicle_mass", 3.5)
        # Road-load coefficients, fit_pdemand.py over three UDDS bags.
        self.declare_parameter("road_a0", 0.0000)    # standing draw, W
        self.declare_parameter("road_a1", 4.0297)    # rolling, W per m/s
        self.declare_parameter("road_a2", 0.4658)    # viscous, W per (m/s)^2
        self.declare_parameter("road_a4", 1.1695)    # inertia multiplier
        self.declare_parameter("publish_hz",   20.0)
        self.declare_parameter("loop",         False)   # loop drive cycle?
        self.declare_parameter("start_delay",  3.0)     # s before playback starts

        csv_path    = self.get_parameter("csv_path").value
        self._mass  = self.get_parameter("vehicle_mass").value
        global ROAD_A0, ROAD_A1, ROAD_A2, ROAD_A4
        ROAD_A0 = float(self.get_parameter("road_a0").value)
        ROAD_A1 = float(self.get_parameter("road_a1").value)
        ROAD_A2 = float(self.get_parameter("road_a2").value)
        ROAD_A4 = float(self.get_parameter("road_a4").value)
        pub_hz      = self.get_parameter("publish_hz").value
        self._loop  = self.get_parameter("loop").value
        start_delay = self.get_parameter("start_delay").value

        # ── Load drive cycle ──────────────────────────────────────────────────
        if csv_path and Path(csv_path).exists():
            self._times, self._speeds = self._load_csv(csv_path)
            self.get_logger().info(
                f"Drive cycle loaded: {csv_path} | "
                f"duration={self._times[-1]:.1f}s | "
                f"v_max={max(self._speeds):.2f}m/s"
            )
        else:
            self._times, self._speeds = self._sine_wave_profile()
            self.get_logger().warning(
                "No CSV provided or file not found — using built-in "
                "sine-wave test profile (120s)"
            )

        self._total_s  = self._times[-1]
        self._start_t  = time.monotonic() + start_delay
        self._done     = False
        self._run_count = 0

        # ── QoS ───────────────────────────────────────────────────────────────
        qos_dc = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )

        # ── Publishers ────────────────────────────────────────────────────────
        self._pub_dc = self.create_publisher(
            Float64MultiArray, "/drive_cycle", qos_dc
        )
        self._pub_status = self.create_publisher(
            Float64MultiArray, "/drive_cycle_status", qos_dc
        )

        # ── Timers ────────────────────────────────────────────────────────────
        self._pub_timer    = self.create_timer(1.0 / pub_hz, self._publish)
        self._status_timer = self.create_timer(1.0,          self._publish_status)

        self.get_logger().info(
            f"DriveCycleNode ready | mass={self._mass}kg | "
            f"hz={pub_hz:.0f} | loop={self._loop} | "
            f"start_delay={start_delay:.1f}s"
        )

    # ── CSV loader ─────────────────────────────────────────────────────────────
    def _load_csv(self, path: str):
        times, speeds = [], []
        with open(path) as f:
            for row in csv.DictReader(f):
                times.append(float(row["time_s"]))
                speeds.append(float(row["v_mps"]))
        return times, speeds

    def _sine_wave_profile(self):
        """120s sine-wave test profile: v = 3 + 2*sin(2π*t/30) m/s"""
        times  = [float(t) for t in range(121)]
        speeds = [3.0 + 2.0 * math.sin(2 * math.pi * t / 30.0) for t in times]
        return times, speeds

    # ── Interpolate speed and compute power demand ─────────────────────────────
    def _get_current(self, t: float):
        """Returns (v_ref, P_demand) at elapsed time t."""
        times  = self._times
        speeds = self._speeds

        if t <= 0:
            return 0.0, 0.0
        if t >= times[-1]:
            return 0.0, 0.0

        # Binary search for bracket
        lo, hi = 0, len(times) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if times[mid] <= t:
                lo = mid
            else:
                hi = mid

        alpha = (t - times[lo]) / max(times[hi] - times[lo], 1e-9)
        v     = speeds[lo] + alpha * (speeds[hi] - speeds[lo])

        dt  = max(times[hi] - times[lo], 0.02)
        acc = (speeds[hi] - speeds[lo]) / dt

        # ── ROAD-LOAD DEMAND MODEL (new build, 2026-10-29) ───────────────────
        # P was mass*v*acc: inertial power only. Fitted against measured bus
        # power (V_bus * (I_fc + I_batt)) over three UDDS bags, that model
        # understated the real load by 24.8x on the mean -- 0.41 W against
        # 10.24 W measured, and it peaked at 3.7 W where the bus drew 24 W.
        #
        # That mis-scaling was not cosmetic. The EMS commands a SHARE, which is
        # what reaches the hardware; with demand 6x too small the solver asked
        # for 84% of a load it had mis-measured, and the stack delivered 1.22 A
        # into a 1.4 A limit. The OC_FC latch on 2026-10-29_19-51-48 is this bug.
        # It also kept the fuel cell below the H-20's first fuel-map kink
        # (13.95 W bus), where the hydrogen curve is flat and no split exists.
        #
        # Coefficients from fit_pdemand.py, non-negative least squares over
        # 15802 moving samples, R^2 0.596, residual RMS 2.86 W. Sensor noise
        # alone accounts for 1.12 W of that, so ~2.6 W is genuine model error
        # (mostly VESC efficiency varying with load). Known and accepted.
        P_mech = self._mass * v * acc                 # SIGNED. Braking detector.
        P = (ROAD_A0
             + ROAD_A1 * v
             + ROAD_A2 * v * v
             + max(ROAD_A4 * P_mech, 0.0))            # rectified: no regen path
        P = max(PDEM_MIN, min(PDEM_MAX, P))

        # P_mech is returned SIGNED and published separately. The road-load P is
        # non-negative by construction (every term is a loss or a rectified
        # inertia), so it can no longer serve as the braking signal the way the
        # old mass*v*acc did. Gating regen on it would mean regen never arms.
        return float(v), float(P), float(P_mech)

    # ── Main publish callback ──────────────────────────────────────────────────
    def _publish(self):
        now     = time.monotonic()
        elapsed = now - self._start_t

        # Before start delay
        if elapsed < 0:
            msg = Float64MultiArray()
            msg.data = [0.0, 0.0, 0.0, 0.0, 0.0]
            self._pub_dc.publish(msg)
            return

        # After drive cycle ends
        if elapsed >= self._total_s:
            if self._loop:
                self._start_t = now
                self._run_count += 1
                self.get_logger().info(
                    f"Drive cycle loop #{self._run_count + 1} started"
                )
                elapsed = 0.0
            else:
                if not self._done:
                    self._done = True
                    self.get_logger().info("Drive cycle complete")
                msg = Float64MultiArray()
                msg.data = [0.0, 0.0, self._total_s, 1.0, 0.0]
                self._pub_dc.publish(msg)
                return

        v_ref, P_dem, P_mech = self._get_current(elapsed)
        progress     = elapsed / self._total_s

        msg = Float64MultiArray()
        # data = [v_ref_mps, P_demand_W, elapsed_s, progress, P_mech_signed_W]
        # Element 4 is NEW: signed mechanical power, for braking detection.
        # Backward compatible -- anything reading the first four is unaffected.
        msg.data = [v_ref, P_dem, elapsed, progress, P_mech]
        self._pub_dc.publish(msg)

    # ── Status publisher ───────────────────────────────────────────────────────
    def _publish_status(self):
        elapsed  = max(0.0, time.monotonic() - self._start_t)
        progress = min(elapsed / self._total_s, 1.0)
        done     = 1.0 if self._done else 0.0

        msg = Float64MultiArray()
        msg.data = [elapsed, self._total_s, progress, done]
        self._pub_status.publish(msg)

        if not self._done and elapsed > 0:
            remaining = self._total_s - elapsed
            self.get_logger().info(
                f"Drive cycle: {elapsed:.0f}/{self._total_s:.0f}s "
                f"({progress*100:.0f}%) | remaining={remaining:.0f}s"
            )


def main(args=None):
    rclpy.init(args=args)
    node = DriveCycleNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
