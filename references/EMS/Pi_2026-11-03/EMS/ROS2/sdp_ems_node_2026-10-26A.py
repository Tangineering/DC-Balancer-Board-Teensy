"""
sdp_ems_node.py — SDP Energy Management ROS 2 Node
UC Davis Future Mobility Lab | Scaled FCHEV Platform
Rev: 2026-10-26A

CHANGES vs 2026-03-16A
  (1) v4 PACKET INDICES. Was reading the 15-element v3 layout: SOC at [14] and
      fault_flags at [13]. Under v4 those are fault_flags and switch_state, so
      SOC read ~0 (driving FC_ONLY) and the fault gate read the switch bitmask —
      zero in Idle, NONZERO IN RUN. The node therefore commanded SAFE the moment
      the Teensy entered Run, which bounced it Run -> Finish -> Idle -> Run
      forever. Now SOC=[17], fault_flags=[14], guard len < 18.
  (2) FAULT GATE IS LATCH-ONLY. Since fw v30 four faults (OV_BUS, UV_FC,
      UV_BATT, UV_BUS) set their bit as a NON-LATCHING transient indication
      while a dwell filter decides. Gating on any nonzero value makes the EMS
      command SAFE on every H-20 purge. Only FAULT_ERROR (0x8000) means stop.
  (3) PACK CONSTANTS. Q_AH 8.0 -> 5.0 (Buddy RC 2S 18650, 5000 mAh / 36 Wh) and
      Em 7.4 -> 7.2 V (2S Li-ion nominal; 7.4 is the LiPo figure). The old 8.0 Ah
      made every SOC_next in the lookup 60% too small.
  (4) SOC BAND 0.30-0.80 -> 0.25-0.90, with a HARD GUARD. cost_J's rows are tied
      to the grid it was computed on; changing the band without recomputing the
      table silently remaps the policy (the shape check still passes). The node
      now refuses to start unless cost_j_soc_min/max match SOC_MIN/MAX.
  (5) REGEN ON BRAKING, NO FC CHARGING. charge_goal was hardcoded 0.0, and the
      firmware's chargingControl() returns immediately when charge_goal <= 0.05 —
      so the regen path was never reachable. The Teensy detects braking itself
      (regenActive = VESC commanded current < -0.1 A) and opens REGEN_ENABLE;
      it only needs charge_goal raised. But charge_goal > 0 ALSO opens the
      FC->charger path on the cruise branch, so this node raises it ONLY while
      braking and returns it to 0 otherwise. FC never charges the battery.

Entry point in setup.py:
    'sdp_ems_node = fchev_ems.sdp_ems_node:main'
"""

import time
import numpy as np
import scipy.io
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import Float64MultiArray

USING_STD_MSGS = True

# ── SOC grid. MUST match the grid cost_J was computed on (see the guard). ─────
SOC_MIN=0.25; SOC_MAX=0.90; SOC_BINS=250; SOC_REF=0.55
PDEM_MIN=-54.0; PDEM_MAX=150.0; PDEM_BINS=50
P_FC_MAX=24.0; P_BATT_MAX=125.0; P_BATT_MIN=-54.0
Em=7.2; Q_AH=5.0; ETA_FC=0.40; Q_LHV_H2=120000; GAMMA=0.95; ALPHA=500; U_STEPS=50
MODE_HYBRID=0; MODE_FC_ONLY=1; MODE_BATT=2; MODE_CHARGE=3; MODE_SAFE=4
SOC_LOW_ENTER=0.30; SOC_LOW_EXIT=0.33; SOC_HIGH_ENTER=0.88; SOC_HIGH_EXIT=0.85

# /vehicle_state v4 indices (Signal Table Rev 2026-08-17A, 18 elements)
IDX_V_ACTUAL=0; IDX_I_BATT=2; IDX_I_FC=5; IDX_V_BUS=6
IDX_FAULTS=14; IDX_SOC=17
VSTATE_LEN=18

# Fault bits — must match the Teensy. FAULT_ERROR is the LATCH marker, set by
# triggerFault() only on State 99 entry. Everything else can appear transiently.
FAULT_ERROR = 0x8000
FAULT_NAMES = {
    0x0001:"OC_FC", 0x0002:"UV_BATT", 0x0004:"OV_BUS", 0x0008:"SW_CONFLICT",
    0x0010:"PI_TIMEOUT", 0x0020:"OV_BATT", 0x0040:"UV_FC", 0x0080:"OC_BT",
    0x0100:"UV_BUS", 0x0200:"OV_RGN", 0x0400:"OV_CHG", 0x0800:"I2C_CHARGER",
    0x1000:"CHARGER_STAT", 0x2000:"INIT_FAIL", 0x4000:"MOT_HOTPLUG",
    0x8000:"ERROR(latched)",
}


def decode_faults(flags: int) -> str:
    if not flags:
        return "none"
    return ",".join(n for b, n in sorted(FAULT_NAMES.items()) if flags & b)


class SDPController:
    def __init__(self, cost_to_go_path, alpha=ALPHA):
        mat = scipy.io.loadmat(cost_to_go_path)
        self.J         = mat["cost_J"].astype(float)
        self.soc_grid  = np.linspace(SOC_MIN,  SOC_MAX,  SOC_BINS)
        self.pdem_grid = np.linspace(PDEM_MIN, PDEM_MAX, PDEM_BINS)
        self.u_grid    = np.linspace(0, P_FC_MAX, U_STEPS)
        self.alpha     = alpha
        if self.J.shape != (SOC_BINS, PDEM_BINS):
            raise ValueError(
                f"cost_J shape {self.J.shape} != ({SOC_BINS},{PDEM_BINS}) — "
                f"recompute the table for this grid")

    def step(self, P_dem, SOC):
        t0 = time.perf_counter()
        soc_clamped = SOC < SOC_MIN or SOC > SOC_MAX
        SOC = float(np.clip(SOC, SOC_MIN, SOC_MAX))
        pd_idx = int(np.argmin(np.abs(self.pdem_grid - np.clip(P_dem, PDEM_MIN, PDEM_MAX))))
        P_batt   = P_dem - self.u_grid
        SOC_next = SOC - (P_batt/Em)/(3600.0*Q_AH)
        feas = (P_batt>=P_BATT_MIN)&(P_batt<=P_BATT_MAX)&(SOC_next>=SOC_MIN)&(SOC_next<=SOC_MAX)
        if not feas.any():
            return dict(P_fc=0.0,P_batt=P_dem,power_share=0.0,feasible=False,
                        soc_clamped=soc_clamped,solve_ms=(time.perf_counter()-t0)*1000)
        idx=np.where(feas)[0]; u_f=self.u_grid[idx]; sn_f=SOC_next[idx]
        nsi=np.array([int(np.argmin(np.abs(self.soc_grid-s))) for s in sn_f])
        fut=self.J[nsi,pd_idx]
        costs=np.where(np.isinf(fut),np.inf,
                       u_f/(ETA_FC*Q_LHV_H2)+self.alpha*np.abs(sn_f-SOC_REF)+GAMMA*fut)
        bi=int(np.argmin(costs))
        if np.isinf(costs[bi]):
            return dict(P_fc=0.0,P_batt=P_dem,power_share=0.0,feasible=False,
                        soc_clamped=soc_clamped,solve_ms=(time.perf_counter()-t0)*1000)
        P_fc=float(u_f[bi]); share=float(np.clip(P_fc/max(abs(P_dem),1.0),0.0,1.0))
        return dict(P_fc=P_fc,P_batt=P_dem-P_fc,power_share=share,feasible=True,
                    soc_clamped=soc_clamped,solve_ms=(time.perf_counter()-t0)*1000)


class SDPEMSNode(Node):
    def __init__(self):
        super().__init__("sdp_ems_node")
        self.declare_parameter("cost_j_path", "CostToGo_J_scaled_2026-03-16A.mat")
        self.declare_parameter("alpha",       float(ALPHA))
        self.declare_parameter("control_hz",  20.0)
        # The SOC grid cost_J was BUILT on. Must equal SOC_MIN/SOC_MAX above, or
        # every row of the table means a different state than the code assumes.
        self.declare_parameter("cost_j_soc_min", 0.25)
        self.declare_parameter("cost_j_soc_max", 0.90)
        self.declare_parameter("allow_grid_mismatch", False)
        # Regen: raise charge_goal only while braking. Firmware opens REGEN_ENABLE
        # on its own (VESC current < -0.1 A); charge_goal just has to be > 0.05 so
        # chargingControl() does not return early. Held at 0 otherwise so the
        # cruise branch never opens the FC->charger path.
        self.declare_parameter("regen_enable",      True)
        self.declare_parameter("regen_pdem_w",     -2.0)   # P_demand below this = braking
        self.declare_parameter("regen_charge_goal", 1.0)

        cost_j = self.get_parameter("cost_j_path").value
        alpha  = self.get_parameter("alpha").value
        hz     = self.get_parameter("control_hz").value

        tmin = float(self.get_parameter("cost_j_soc_min").value)
        tmax = float(self.get_parameter("cost_j_soc_max").value)
        if abs(tmin - SOC_MIN) > 1e-9 or abs(tmax - SOC_MAX) > 1e-9:
            msg = (f"cost_J was built on SOC=[{tmin},{tmax}] but this node uses "
                   f"[{SOC_MIN},{SOC_MAX}]. The shape check CANNOT catch this — "
                   f"row i of the table would mean a different SOC than the code "
                   f"assumes, and the policy would be silently wrong. Recompute "
                   f"cost_J on [{SOC_MIN},{SOC_MAX}], or set allow_grid_mismatch "
                   f"to run anyway (results are NOT valid).")
            if self.get_parameter("allow_grid_mismatch").value:
                self.get_logger().error("GRID MISMATCH, RUNNING ANYWAY: " + msg)
            else:
                raise ValueError(msg)

        self.ctrl = SDPController(cost_j, alpha=alpha)
        self.get_logger().info(
            f"SDP loaded: {cost_j} | alpha={alpha} | SOC grid [{SOC_MIN},{SOC_MAX}] "
            f"| pack {Q_AH} Ah @ {Em} V")

        self._regen_on   = bool(self.get_parameter("regen_enable").value)
        self._regen_pdem = float(self.get_parameter("regen_pdem_w").value)
        self._regen_goal = float(self.get_parameter("regen_charge_goal").value)
        self._braking    = False

        self.SOC=0.55; self.v_actual=0.0; self.fault_flags=0
        self.state_stamp=0.0; self.v_ref=0.0; self.P_demand=0.0
        self._soc_low=False; self._soc_high=False
        self._steps=0; self._solve_sum=0.0
        self._last_transient=0

        qos_s = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=1)
        qos_r = QoSProfile(reliability=ReliabilityPolicy.RELIABLE,    history=HistoryPolicy.KEEP_LAST, depth=10)

        self.create_subscription(Float64MultiArray, "/vehicle_state", self._cb_state, qos_s)
        self.create_subscription(Float64MultiArray, "/drive_cycle",   self._cb_dc,    qos_r)
        self.pub_cmd  = self.create_publisher(Float64MultiArray, "/ems_command",     qos_r)
        self.pub_diag = self.create_publisher(Float64MultiArray, "/ems_diagnostics", qos_s)
        self.create_timer(1.0/hz, self._loop)
        self.get_logger().info(
            f"SDPEMSNode ready | {hz:.0f}Hz | regen={'on' if self._regen_on else 'off'} "
            f"(braking below {self._regen_pdem:.1f} W) | FC never charges the pack")

    def _cb_state(self, msg):
        # v4: 18 elements. SOC at [17], fault_flags at [14].
        if len(msg.data) < VSTATE_LEN:
            self.get_logger().warning(
                f"vehicle_state has {len(msg.data)} elements, expected {VSTATE_LEN} "
                f"— is the bridge on the v4 packet?")
            return
        self.v_actual    = msg.data[IDX_V_ACTUAL]
        self.SOC         = msg.data[IDX_SOC]
        self.fault_flags = int(msg.data[IDX_FAULTS])
        self.state_stamp = time.monotonic()

    def _cb_dc(self, msg):
        # data=[v_ref, P_demand, elapsed, progress]
        if len(msg.data) < 2: return
        self.v_ref=float(msg.data[0]); self.P_demand=float(msg.data[1])

    def _charge_goal(self) -> float:
        """
        Raise charge_goal only while braking, so the firmware reaches its regen
        branch (it returns early at charge_goal <= 0.05). Zero otherwise, which
        keeps the cruise branch — and therefore FC->battery charging — shut.
        """
        if not self._regen_on:
            return 0.0
        braking = self.P_demand < self._regen_pdem
        if braking != self._braking:
            self._braking = braking
            self.get_logger().info(
                f"{'regen armed' if braking else 'regen released'} "
                f"(P_demand={self.P_demand:.1f} W)")
        return self._regen_goal if braking else 0.0

    def _loop(self):
        age_ms = (time.monotonic()-self.state_stamp)*1000
        if age_ms > 500:
            self.get_logger().warn(f"State stale {age_ms:.0f}ms -> SAFE")
            self._pub(0.0,0.5,0.0,MODE_SAFE,False,0.0,0.0,False,False,0.0); return

        soc = self.SOC
        if soc < SOC_LOW_ENTER:   self._soc_low  = True
        elif soc > SOC_LOW_EXIT:  self._soc_low  = False
        if soc > SOC_HIGH_ENTER:  self._soc_high = True
        elif soc < SOC_HIGH_EXIT: self._soc_high = False

        # Fault gate — LATCH ONLY. A transient indication is logged, not acted on.
        if self.fault_flags & FAULT_ERROR:
            self.get_logger().error(
                f"LATCHED fault_flags=0x{self.fault_flags:04X} "
                f"({decode_faults(self.fault_flags)}) -> SAFE")
            self._pub(0.0,0.5,0.0,MODE_SAFE,False,0.0,0.0,False,False,0.0); return
        if self.fault_flags and self.fault_flags != self._last_transient:
            self.get_logger().warning(
                f"transient fault_flags=0x{self.fault_flags:04X} "
                f"({decode_faults(self.fault_flags)}) — not latched, continuing")
        self._last_transient = self.fault_flags

        chg = self._charge_goal()

        if self._soc_low:
            P_fc=min(self.P_demand,P_FC_MAX)
            self._pub(self.v_ref,1.0,chg,MODE_FC_ONLY,True,P_fc,self.P_demand-P_fc,True,False,0.0); return
        if self._soc_high:
            self._pub(self.v_ref,0.0,chg,MODE_BATT,False,0.0,self.P_demand,True,False,0.0); return

        r = self.ctrl.step(P_dem=self.P_demand, SOC=soc)
        self._steps+=1; self._solve_sum+=r["solve_ms"]
        if self._steps % 100 == 0:
            self.get_logger().info(
                f"t={self._steps/20:.0f}s SOC={soc:.3f} P_dem={self.P_demand:.1f}W "
                f"P_fc={r['P_fc']:.1f}W share={r['power_share']:.2f} "
                f"chg={chg:.1f} solve_avg={self._solve_sum/self._steps:.3f}ms")
        self._pub(self.v_ref,r["power_share"],chg,MODE_HYBRID,True,
                  r["P_fc"],r["P_batt"],r["feasible"],r["soc_clamped"],r["solve_ms"])

    def _pub(self, v_sp, share, chg, mode, droop, P_fc, P_batt, feasible, clamped, ms):
        cmd=Float64MultiArray(); cmd.data=[v_sp,share,chg,float(mode),float(droop)]
        self.pub_cmd.publish(cmd)
        diag=Float64MultiArray(); diag.data=[P_fc,P_batt,share,float(feasible),float(clamped),ms,float(mode)]
        self.pub_diag.publish(diag)


def main(args=None):
    rclpy.init(args=args)
    node = SDPEMSNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node._pub(0.0,0.5,0.0,MODE_SAFE,False,0.0,0.0,False,False,0.0)
        node.destroy_node(); rclpy.shutdown()

if __name__ == "__main__":
    main()
