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
SOC_MIN=0.25; SOC_MAX=0.90; SOC_BINS=250; SOC_REF=0.82
# Rescaled 2026-10-28 to the car's measured demand (-3.8..+3.9 W observed).
PDEM_MIN=0.0; PDEM_MAX=35.0; PDEM_BINS=50
# 24 W was 1.52 A at 15.8 V, over the firmware's 1.4 A LIMIT_I_FC_MAX.
P_FC_MAX=17.4; P_BATT_MAX=35.0; P_BATT_MIN=-17.4
Em=7.2; Q_AH=5.0; ETA_FC=0.40; Q_LHV_H2=120000; GAMMA=0.95; ALPHA=500; U_STEPS=50
ALPHA_N=4000.0
K_CONV = 0.193          # convexity of the fuel map (0 = linear = bang-bang)
MODE_HYBRID=0; MODE_FC_ONLY=1; MODE_BATT=2; MODE_CHARGE=3; MODE_SAFE=4
SOC_LOW_ENTER=0.30; SOC_LOW_EXIT=0.33; SOC_HIGH_ENTER=0.88; SOC_HIGH_EXIT=0.85

# /vehicle_state v4 indices (Signal Table Rev 2026-08-17A, 18 elements)
_FLOW_P  = np.array([0.0, 5.0, 10.0, 15.0, 20.0, 23.5])   # H-20 datasheet, stack W
_FLOW_ML = np.array([3.0, 50.0, 100.0, 150.0, 230.0, 330.0]) # ml/min
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
    def __init__(self, cost_to_go_path, alpha=ALPHA, alpha_n=ALPHA_N):
        mat = scipy.io.loadmat(cost_to_go_path)
        self.J         = mat["cost_J"].astype(float)
        self.soc_grid  = np.linspace(SOC_MIN,  SOC_MAX,  SOC_BINS)
        # Demand resolution comes FROM THE TABLE, not from a constant here.
        # 50 bins over 0-35 W is 0.7 W wide, finer than demand moves in one DP
        # step, which collapses the TPM to near-memoryless. A coarser grid may
        # be the right choice, and the node must follow whatever was built.
        self._pdem_bins = int(mat["pdem_bins"].squeeze()) if "pdem_bins" in mat \
                          else self.J.shape[1]
        self.pdem_grid = np.linspace(PDEM_MIN, PDEM_MAX, self._pdem_bins)
        self.u_grid    = np.linspace(0, P_FC_MAX, U_STEPS)
        self.alpha     = alpha
        self.alpha_n   = alpha_n
        # Read the cost parameters the table was BUILT with and use those, so the
        # online stage cost cannot drift from the one value iteration optimised.
        # A mismatch here does not error -- it silently returns a policy that is
        # optimal for a different problem, which is how the bang-bang run looked
        # like a working SDP.
        self.soc_ref = float(mat["soc_ref"].squeeze()) if "soc_ref" in mat else SOC_REF
        if "alpha_n" in mat: self.alpha_n = float(mat["alpha_n"].squeeze())
        self.k_conv  = float(mat["k_conv"].squeeze()) if "k_conv" in mat else K_CONV
        self.fc_may_charge = bool(int(mat["fc_may_charge"].squeeze())) \
            if "fc_may_charge" in mat else False
        # AVERAGE-COST TABLES carry cost_form "average_cost_no_soc_target".
        # They have NO SOC reference and NO discount: the stage cost is hydrogen
        # only, and charge sustenance comes from the band alone. h is a RELATIVE
        # value function, defined up to an additive constant, so only its
        # DIFFERENCES matter -- which is all the argmin uses anyway.
        _form = mat.get("cost_form")
        self.avg_cost = (str(_form[0]).strip() == "average_cost_no_soc_target"
                         if _form is not None else False)
        self.rho = float(mat["rho"].squeeze()) if "rho" in mat else 0.0
        _ff = mat.get("fuel_form")
        self.fuel_datasheet = (str(_ff[0]).strip() == "h20_datasheet_flow"
                               if _ff is not None else False)
        self.gamma   = float(mat["gamma"].squeeze())  if "gamma"  in mat else GAMMA
        fs_min = float(mat["soc_min"].squeeze()) if "soc_min" in mat else SOC_MIN
        fs_max = float(mat["soc_max"].squeeze()) if "soc_max" in mat else SOC_MAX
        if abs(fs_min - SOC_MIN) > 1e-9 or abs(fs_max - SOC_MAX) > 1e-9:
            raise ValueError(
                f"cost_J was built on SOC=[{fs_min},{fs_max}] but this node uses "
                f"[{SOC_MIN},{SOC_MAX}]. Row i means a different SOC in each, so "
                f"the shape check cannot catch it. Rebuild the table.")
        if self.J.shape != (SOC_BINS, self._pdem_bins):
            raise ValueError(
                f"cost_J shape {self.J.shape} != ({SOC_BINS},{self._pdem_bins}) — "
                f"recompute the table for this grid")

    def step(self, P_dem, SOC):
        t0 = time.perf_counter()
        soc_clamped = SOC < SOC_MIN or SOC > SOC_MAX
        SOC = float(np.clip(SOC, SOC_MIN, SOC_MAX))
        pd_idx = int(np.argmin(np.abs(self.pdem_grid - np.clip(P_dem, PDEM_MIN, PDEM_MAX))))
        P_batt   = P_dem - self.u_grid
        SOC_next = SOC - (P_batt/Em)/(3600.0*Q_AH)
        # THE FUEL CELL MAY NEVER EXCEED DEMAND. Must match make_costtogo3.py.
        # Without it the policy commands P_fc >> P_demand and the surplus goes
        # into the pack through the BUS, bypassing every I_charge guard -- 24 W
        # into a 4 W load on 2026-10-28, which is both the OC_FC latch and the
        # FC charging the battery. I_batt cannot read negative (firmware takes it
        # straight from analogRead), so that backflow is invisible and has to be
        # prevented by construction rather than detected.
        # Must match make_costtogo3.py's FC_MAY_CHARGE. Read from the table so the
        # two cannot drift: a mismatch here returns a policy optimal for a
        # different problem, silently.
        cap = P_FC_MAX if self.fc_may_charge else max(P_dem, 0.0)
        feas = ((P_batt>=P_BATT_MIN)&(P_batt<=P_BATT_MAX)
                &(SOC_next>=SOC_MIN)&(SOC_next<=SOC_MAX)
                &(self.u_grid<=cap+1e-9))
        if not feas.any():
            return dict(P_fc=0.0,P_batt=P_dem,power_share=0.0,feasible=False,
                        soc_clamped=soc_clamped,solve_ms=(time.perf_counter()-t0)*1000)
        idx=np.where(feas)[0]; u_f=self.u_grid[idx]; sn_f=SOC_next[idx]
        # LINEAR interp, matching make_costtogo2.py. With nearest-neighbour all
        # 50 actions snap to one successor bin (dSOC 1.85e-4 << bin 2.6e-3), the
        # future term cancels, and the policy degenerates to bang-bang.
        db = self.soc_grid[1] - self.soc_grid[0]
        pos = np.clip((sn_f - SOC_MIN)/db, 0.0, SOC_BINS-1.0)
        nsi = np.minimum(np.floor(pos).astype(int), SOC_BINS-2)
        whi = pos - nsi; wlo = 1.0 - whi
        fut = wlo*self.J[nsi,pd_idx] + whi*self.J[nsi+1,pd_idx]
        # Stage cost MUST match make_costtogo2.py exactly: normalised fuel plus
        # QUADRATIC normalised SOC deviation. The old form (kg/s fuel + alpha*
        # |SOC-ref|) is why the policy was a bang-bang switch at SOC_REF: the
        # absolute value has a constant gradient, so discharging always looked
        # equally good, and the kg/s fuel term was 772x too small to object.
        un  = u_f / P_FC_MAX
        if self.fuel_datasheet:
            # H-20 datasheet flow, same interpolation as make_costtogo_newbuild.
            # A quadratic cannot represent a map that is flat to 13.95 W then
            # triples its slope by 21.9 W, and that bend is the only reason a
            # blended split exists at all.
            fuel = np.interp(u_f / 0.93, _FLOW_P, _FLOW_ML) / _FLOW_ML[-1]
        else:
            fuel = un + self.k_conv*un**2
        if self.avg_cost:
            # g(u) = hydrogen only; no SOC term, no discount on the future.
            # -dh/dSOC is then the equivalence factor, derived not assumed.
            costs=np.where(np.isinf(fut), np.inf, fuel + fut)
        else:
            dev = (sn_f - self.soc_ref) / (SOC_MAX - SOC_MIN)
            costs=np.where(np.isinf(fut),np.inf,
                           fuel + self.alpha_n*dev**2 + self.gamma*fut)
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
        self.declare_parameter("regen_pdem_w",      0.0)   # arm: P_demand below this
        self.declare_parameter("regen_release_w",   0.5)   # release: P_demand above this
        self.declare_parameter("regen_charge_goal", 1.0)
        # Firmware DROOP_R_MIN / DROOP_R_MAX. Commanding a rail arms the share
        # selector; see the clamp in _pub(). Keep these matched to the firmware.
        self.declare_parameter("share_band_min", 0.15)
        self.declare_parameter("share_band_max", 0.85)
        # The firmware test is INCLUSIVE -- "sp <= DROOP_R_MIN (0.15, INCLUSIVE)
        # selects BT, sp >= DROOP_R_MAX (0.85, INCLUSIVE) selects FC" -- so a
        # command AT a rail arms the cut exactly as one past it does. Clamping to
        # 0.15/0.85 would have armed it every single tick. Stay strictly inside.
        self.declare_parameter("share_band_margin", 0.01)
        # ── FC CURRENT CEILING (2026-10-29) ──────────────────────────────────
        # The EMS commands a SHARE, not a current. The Teensy realises it with
        # droop, so the delivered FC current is share * I_total -- which has
        # nothing to do with the P_fc the solver picked.
        #
        # On rosbag_sdp_2026-10-29_19-51-48 the policy asked for at most 3.67 W
        # (0.237 A at 15.5 V), well under LIMIT_I_FC_MAX, and I_fc still reached
        # 1.23 A and latched OC_FC: share was at its 0.84 ceiling while I_total
        # peaked near 1.45 A. Capping P_fc in the cost function cannot prevent
        # this; only capping the SHARE against measured total current can.
        #
        # share_max_dynamic = i_fc_max_a / I_total_filtered, applied on top of the
        # band clamp. Filtered because I_total is noisy and an unfiltered divisor
        # injects that noise straight into the command.
        self.declare_parameter("i_fc_max_a", 1.10)      # below LIMIT_I_FC_MAX 1.4
        self.declare_parameter("itot_tau_s", 0.30)
        # ── HYDROGEN ACCOUNTING ──────────────────────────────────────────────
        # Two terms. The electrochemical one goes as stack power. The purge one
        # is a FIXED RATE: the H-20 purges on a timer, measured 10.340 s +/- 0.020
        # across 8 events, 100 ms each, independent of load.
        #
        # Purge is deliberately NOT in the SDP's stage cost. It has no u in it,
        # so adding it shifts every action's cost equally and cannot change the
        # argmin -- verified numerically across purge rates 0..5x the
        # electrochemical peak. It matters for what the run CONSUMED, not for
        # what the policy should DO, and that is what this accumulator is for.
        #
        # purge_g_per_event needs the tank-weight measurement. Left at 0 until
        # then, so the total is honest about what it does and does not include.
        self.declare_parameter("purge_g_per_event", 0.0)
        self.declare_parameter("purge_interval_s", 10.340)
        # Threshold on charging power before the charger path is opened, and the
        # goal sent when it is. Below the threshold the surplus is small enough
        # to be absorbed without opening a single-source charge window.
        self.declare_parameter("fc_charge_min_w", 0.5)
        self.declare_parameter("fc_charge_goal", 1.0)

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
        self._regen_pdem    = float(self.get_parameter("regen_pdem_w").value)
        self._regen_release = float(self.get_parameter("regen_release_w").value)
        _m = float(self.get_parameter("share_band_margin").value)
        self._share_lo = float(self.get_parameter("share_band_min").value) + _m
        self._share_hi = float(self.get_parameter("share_band_max").value) - _m
        self._band_warned = False
        self._i_fc_max = float(self.get_parameter("i_fc_max_a").value)
        self._itot_tau = float(self.get_parameter("itot_tau_s").value)
        self._itot_f   = None
        self._ceil_warned = False
        self.I_fc = 0.0; self.I_batt = 0.0
        self.P_mech = 0.0
        self._warned_no_pmech = False
        self._purge_g  = float(self.get_parameter("purge_g_per_event").value)
        self._purge_s  = float(self.get_parameter("purge_interval_s").value)
        self._fc_chg_w    = float(self.get_parameter("fc_charge_min_w").value)
        self._fc_chg_goal = float(self.get_parameter("fc_charge_goal").value)
        self._h2_g     = 0.0          # cumulative, grams
        self._h2_elec_g = 0.0         # electrochemical part alone
        self._h2_last  = None
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
            f"(arm < {self._regen_pdem:.1f} W, release > {self._regen_release:.1f} W) "
            f"| {'AVG-COST (no SOC target)' if self.ctrl.avg_cost else 'discounted'} "
            f"| I_fc cap {self._i_fc_max:.2f} A "
            f"| FC charge: {'ALLOWED' if self.ctrl.fc_may_charge else 'blocked'} "
            f"| share clamped to [{self._share_lo},{self._share_hi}] "
            f"| H2 purge {self._purge_g:.4f} g / {self._purge_s:.2f} s "
            f"| FC may charge: {self.ctrl.fc_may_charge}")

    def _cb_state(self, msg):
        # v4: 18 elements. SOC at [17], fault_flags at [14].
        if len(msg.data) < VSTATE_LEN:
            self.get_logger().warning(
                f"vehicle_state has {len(msg.data)} elements, expected {VSTATE_LEN} "
                f"— is the bridge on the v4 packet?")
            return
        self.v_actual    = msg.data[IDX_V_ACTUAL]
        self.I_fc        = msg.data[IDX_I_FC]
        self.I_batt      = msg.data[IDX_I_BATT]
        self.SOC         = msg.data[IDX_SOC]
        self.fault_flags = int(msg.data[IDX_FAULTS])
        self.state_stamp = time.monotonic()

    def _cb_dc(self, msg):
        # data=[v_ref, P_demand, elapsed, progress, P_mech_signed]
        #
        # Element 4 is new. P_demand is now a ROAD-LOAD model and is non-negative
        # by construction -- every term is a loss or a rectified inertia -- so it
        # can no longer serve as the braking signal. Gating regen on it would mean
        # regen never arms again. P_mech keeps its sign and is what braking is
        # detected from. Falls back to P_demand when a four-element message
        # arrives, so an old drive_cycle_node still runs (without regen).
        if len(msg.data) < 2: return
        self.v_ref=float(msg.data[0]); self.P_demand=float(msg.data[1])
        if len(msg.data) >= 5:
            self.P_mech=float(msg.data[4])
        else:
            if not self._warned_no_pmech:
                self.get_logger().warning(
                    "drive_cycle has 4 elements, no signed P_mech - regen cannot "
                    "arm. Is drive_cycle_node_newbuild deployed?")
                self._warned_no_pmech = True
            self.P_mech=float(msg.data[1])

    def _charge_goal(self) -> float:
        """
        Raise charge_goal only while braking, so the firmware reaches its regen
        branch (it returns early at charge_goal <= 0.05). Zero otherwise, which
        keeps the cruise branch — and therefore FC->battery charging — shut.
        """
        if not self._regen_on:
            return 0.0
        # ANY negative demand is regen. The arm threshold is regen_pdem_w, now 0,
        # so every watt the motor gives back goes to the pack.
        #
        # Release needs its own, higher threshold. With one threshold at 0 the
        # gate chatters every tick that P_demand dithers across zero -- and it
        # dithers constantly, because P = m*v*a is differentiated from a measured
        # speed. Each flip toggles REGEN_ENABLE in the firmware. Arming at <= 0
        # and releasing only above regen_release_w gives the gate a deadband, so
        # it latches through the noise and opens on real acceleration.
        if self._braking:
            braking = self.P_mech <= self._regen_release
        else:
            braking = self.P_mech < self._regen_pdem
        if braking != self._braking:
            self._braking = braking
            self.get_logger().info(
                f"{'regen armed' if braking else 'regen released'} "
                f"(P_mech={self.P_mech:.1f} W)")
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

        # REGEN AND FUEL CELL ARE MUTUALLY EXCLUSIVE.
        #
        # While the charger is enabled the FC output and the pack-charge path are
        # both live on the bus, so any FC current can reach the pack -- exactly
        # what "the FC must not charge the battery" rules out. Firmware also
        # drops fcChargeEnable inside the regenActive branch, but relying on that
        # leaves the Pi commanding something it does not mean. Braking has no
        # traction demand anyway, so the FC has nothing to contribute: idle it.
        # (This was invisible until the policy actually started using the FC --
        # with the old bang-bang table P_fc was 0 everywhere above SOC_REF.)
        # (The explicit regen/FC lockout that stood here is GONE as of the
        # 2026-10-28 rescale: with u <= max(P_dem, 0) the solver already
        # returns P_fc = 0 whenever demand is negative, so forcing BATT mode
        # on every armed tick only added mode thrash -- it put the run in
        # BATT for 65% of 2026-10-28_20-46-53 and idled the stack with it.)

        if self._soc_low:
            P_fc=min(max(self.P_demand,0.0),P_FC_MAX)
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
        # If the policy wants the stack to charge the pack, the firmware needs
        # charge_goal > 0.05 or chargingControl() returns early and the surplus
        # has nowhere to go but the bus -- the invisible backflow path, since
        # I_batt cannot read negative. The regen goal and the FC-charge goal are
        # the same signal to the Teensy, so take whichever is larger.
        if r["P_batt"] < -self._fc_chg_w:
            chg = max(chg, self._fc_chg_goal)
        self._pub(self.v_ref,r["power_share"],chg,MODE_HYBRID,True,
                  r["P_fc"],r["P_batt"],r["feasible"],r["soc_clamped"],r["solve_ms"])

    def _pub(self, v_sp, share, chg, mode, droop, P_fc, P_batt, feasible, clamped, ms):
        # ── SHARE BAND CLAMP (2026-10-27) ────────────────────────────────────
        # NEVER command at or outside [DROOP_R_MIN, DROOP_R_MAX] = [0.15, 0.85].
        # The rails themselves are forbidden: the firmware's test is INCLUSIVE
        # ("sp <= DROOP_R_MIN ... selects BT"), so 0.15 arms the cut just as 0.05
        # does. share_band_margin keeps the command strictly inside.
        #
        # A setpoint at or past either rail arms the firmware's share-setpoint
        # selector, which then migrates load off the minority channel and CUTS
        # IT OFF THE BUS. Cutting a channel that is still carrying current
        # collapses the bus -- the firmware says so itself: "the cut at 1.3-1.5 A
        # demonstrably does" (fw v6 RESIDUAL note in updateShareSetpointCutoff).
        # That is the ERR_UV_BUS the SDP kept hitting while the sweep ran clean:
        # with the alpha_n 1500 table, 85% of commanded shares sat under 0.15,
        # so the selector was being armed almost continuously. It reproduced with
        # regen both on and off, which is what ruled out the charging path.
        #
        # Nothing real is lost. The governor cannot deliver a minority split
        # below roughly 0.25 at this plant's currents anyway, so a command of
        # 0.055 was never going to be tracked -- it only ever armed the cut.
        #
        # SAFE keeps its 0.5 (both droop legs equal, no preference) and is
        # exempt: it is published when the plant is already being shut down.
        if mode != MODE_SAFE:
            lo, hi = self._share_lo, self._share_hi
            # Dynamic ceiling from measured total current, EMA-filtered.
            i_raw = abs(self.I_fc) + abs(self.I_batt)
            if self._itot_f is None:
                self._itot_f = i_raw
            else:
                _a = (1.0/20.0) / (self._itot_tau + 1.0/20.0)
                self._itot_f += _a * (i_raw - self._itot_f)
            if self._itot_f > 1e-6:
                hi_i = self._i_fc_max / self._itot_f
                if hi_i < hi:
                    if not self._ceil_warned:
                        self.get_logger().warning(
                            f"share ceiling cut to {hi_i:.3f} by the {self._i_fc_max:.2f} A "
                            f"FC limit at I_total {self._itot_f:.3f} A")
                        self._ceil_warned = True
                    hi = max(lo, hi_i)
            if share < lo or share > hi:
                if not self._band_warned:
                    self.get_logger().warning(
                        f"share {share:.3f} outside [{lo},{hi}] -> clamped; "
                        f"commanding a rail would arm the firmware share cut")
                    self._band_warned = True
                share = min(max(share, lo), hi)
        cmd=Float64MultiArray(); cmd.data=[v_sp,share,chg,float(mode),float(droop)]
        self.pub_cmd.publish(cmd)

        # Cumulative H2, in grams, integrated on the wall clock rather than an
        # assumed tick so a dropped cycle does not silently under-count.
        _now = time.monotonic()
        if self._h2_last is not None:
            _dt = _now - self._h2_last
            if 0.0 < _dt < 1.0:
                _elec = max(0.0, P_fc) / (ETA_FC * Q_LHV_H2) * 1000.0   # g/s
                _purge = (self._purge_g / self._purge_s) if self._purge_s > 0 else 0.0
                self._h2_elec_g += _elec * _dt
                self._h2_g      += (_elec + _purge) * _dt
        self._h2_last = _now

        diag=Float64MultiArray(); diag.data=[P_fc,P_batt,share,float(feasible),float(clamped),ms,float(mode),
                                             self._h2_g, self._h2_elec_g]
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
