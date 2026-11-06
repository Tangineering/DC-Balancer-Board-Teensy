"""
teensy_bridge_node.py — Teensy 4.1 UDP ↔ ROS 2 Bridge
UC Davis Future Mobility Lab | Scaled FCHEV Platform
Rev: 2026-11-03A  (updated from 2026-10-31A)

CHANGES vs 2026-10-31A
  — Hydrogen usage tracked online, next to the SOC estimator. Cumulative H2 in
    GRAMS from Faraday's law on the stack current, published on /h2_usage.
    These are the two references the energy management problem tracks, so they
    belong in the same place and in physical units.
  — No fuel map lookup. Reading the H-20 datasheet's five points back through
    Faraday gives 0.70 V/cell flat below 15 W sagging to 0.50 V at 23.5 W: the
    published map IS Faraday with the polarisation droop folded in, so the
    stack current already carries everything it does.
  — Purge defaults to ZERO, not 3 ml/min. The purge timing is known from the
    bench (100 ms every 10.340 s, load-independent) but the flow it vents is
    not, and the datasheet curve passes through the origin so it gives no
    intercept either. An idle soak with no electrical load measures it.
  — /vehicle_state is UNCHANGED at 18 elements.

CHANGES in 2026-10-31A vs 2026-08-17A
  — SOC estimator replaced: fixed-gain complementary filter -> EKF.
    The old structure was coulomb counting plus an OCV pull at two hand-tuned
    rates (k_rest 0.05/s, k_load 0.002/s). Those constants encode a guess about
    how much to trust voltage versus current, held fixed regardless of operating
    point. The EKF computes that trade-off instead, from the OCV slope at the
    current SOC and the two noise covariances. Where the curve is steep and the
    pack is resting the correction is strong; under load, or on a flat part of
    the curve, it backs off on its own.
  — Optional 1-RC polarisation state. The old loaded-OCV correction backed out
    terminal voltage through a bare R_int, which attributes all of the IR
    transient to instantaneous resistance. Set pack_r1_ohm > 0 to model the
    slow part properly. Left at 0 the filter is single-state and behaves like
    the R-only model, so this is opt-in after characterisation.
  — i_charge reference frame is now explicit (soc_i_charge_bus_side). The old
    code assumed battery-side with a comment saying to check. It is still
    assumed battery-side BY DEFAULT — the parameter exists so the assumption is
    visible and flippable, not because it has been resolved.
  — abs() on I_batt is now conditional (soc_i_batt_bidirectional). The INA253
    path is unipolar today so abs() is a no-op; it becomes a sign-destroying bug
    the day a bidirectional sensor is fitted, which is exactly when regen starts
    working. Flag it then, not after a confusing run.
  — New /soc_diagnostics topic (6 elements) for tuning. /vehicle_state is
    UNCHANGED at 18 elements — every existing analysis script keeps working.
  — soc_k_rest / soc_k_load are still DECLARED so existing launch files and
    param overrides do not fail, but they are unused. Logged once at startup.

STILL UNCALIBRATED — the filter is only as good as these two:
  — OCV_CURVE is a generic 2S NMC shape, not your pack. It sets H = dOCV/dSOC,
    which IS the Kalman gain's numerator. A wrong slope scales every correction.
  — pack_r_int_ohm is a 0.050 placeholder. At 0.8 A that is 40 mV, against the
    ~23 mV of OCV swing across a whole run. R0 error aliases straight into SOC.
    Measure it before trusting any absolute SOC number.

/vehicle_state layout (18 elements) — UNCHANGED:
  [0]  v_actual          m/s   flywheel surface speed
  [1]  V_batt            V     2S LiPo terminal voltage
  [2]  I_batt            A     battery bus-side discharge current (unipolar)
  [3]  I_charge          A     Ag105 MPPT charge current
  [4]  V_fc              V     fuel cell stack voltage
  [5]  I_fc              A     FC bus-side boost output current
  [6]  V_bus             V     DC bus voltage (nominal 16.0 V)
  [7]  V_rgn             V     regen node voltage
  [8]  V_chg             V     charger input voltage
  [9]  power_share_actual —    I_fc / (I_fc + I_batt)
  [10] droop_FC          cnts  FC MDAC droop gain (Q16)
  [11] droop_BT          cnts  BT MDAC droop gain (Q16)
  [12] charger_status    bits  Ag105 Table-6 status byte
  [13] switch_state      bits  RT1987 power-path bitmask
  [14] fault_flags       bits  uint16 fault bitmask
  [15] error_code        enum  latched State-99 cause
  [16] error_source_state enum mainState at fault time
  [17] SOC               —     EKF estimate (Pi-side)

/h2_usage layout (6 elements) — NEW in 2026-11-03A:
  [0]  mdot_g_s          g/s   instantaneous H2 mass flow (Faraday + purge)
  [1]  total_g           g     cumulative since node start
  [2]  i_stack           A     stack-side FC current (bus current referred)
  [3]  p_stack           W     stack power, V_fc * i_stack
  [4]  faraday_ml_min    ml/min  stoichiometric flow, for the datasheet plot
  [5]  purge_g_s         g/s   the constant term (0 until measured)

/soc_diagnostics layout (6 elements) — NEW:
  [0]  soc               —     same value as /vehicle_state[17]
  [1]  sigma_soc         —     sqrt(P[0,0]), the filter's own uncertainty
  [2]  innovation        V     V_batt_measured - V_batt_predicted
  [3]  kalman_gain_soc   —     K[0], how hard voltage is moving SOC right now
  [4]  i_pack            A     pack-side net current (+ = discharge)
  [5]  v1                V     RC polarisation state (0 if disabled)
"""

import math
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

T2P_FMT  = "<BIH" + "f" * 10 + "HHBBHBBB"
T2P_SIZE = struct.calcsize(T2P_FMT)
assert T2P_SIZE == 58, f"T2P_SIZE={T2P_SIZE}, expected 58"

P2T_FMT  = "<BIHfffBBB"
P2T_SIZE = struct.calcsize(P2T_FMT)
assert P2T_SIZE == 22, f"P2T_SIZE={P2T_SIZE}, expected 22"

# ── UDP config ─────────────────────────────────────────────────────────────────
DEFAULT_TEENSY_IP = "192.168.1.50"
DEFAULT_LISTEN_IP = "0.0.0.0"
TEENSY_TX_PORT    = 5000
TEENSY_RX_PORT    = 5001
UDP_POLL_TIMEOUT  = 0.002

# ── Safety thresholds ──────────────────────────────────────────────────────────
TEENSY_STALE_MS   = 500
PI_WATCHDOG_MS    = 500
MODE_SAFE         = 4

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
FAULT_ERROR          = 0x8000

FAULT_COMMS_STALE    = 0x8000


def _xor(data: bytes) -> int:
    r = 0
    for b in data:
        r ^= b
    return r


# ── OCV model ─────────────────────────────────────────────────────────────────
# 2S 18650 Li-ion open-circuit voltage -> SOC. Monotonic, interpolated.
# Pack: Buddy RC, 2S 18650, 5000 mAh / 36 Wh, nominal 7.2 V (3.6 V/cell),
# charge cutoff 8.2-8.4 V. Typical NMC 18650 shape, doubled for 2S.
#
# STARTING POINT ONLY — calibrate with a slow rested discharge on your pack.
# This matters more under the EKF than it did under the old fixed-gain filter:
# the segment SLOPE is the measurement Jacobian H, so it sets the Kalman gain
# directly. A curve that is too flat here makes the filter ignore voltage; too
# steep and it chases voltage noise into SOC.
OCV_CURVE = [
    (6.00, 0.00), (6.60, 0.05), (6.82, 0.10), (7.02, 0.20), (7.18, 0.30),
    (7.32, 0.40), (7.46, 0.50), (7.62, 0.60), (7.78, 0.70), (7.96, 0.80),
    (8.16, 0.90), (8.40, 1.00),
]


def soc_from_ocv(v: float) -> float:
    """SOC for a given open-circuit voltage. Clamped at both ends."""
    if v <= OCV_CURVE[0][0]:
        return OCV_CURVE[0][1]
    if v >= OCV_CURVE[-1][0]:
        return OCV_CURVE[-1][1]
    for (v0, s0), (v1, s1) in zip(OCV_CURVE, OCV_CURVE[1:]):
        if v <= v1:
            return s0 + (s1 - s0) * (v - v0) / (v1 - v0)
    return OCV_CURVE[-1][1]


def ocv_from_soc(s: float) -> float:
    """Open-circuit voltage at a given SOC — the forward direction the EKF
    measurement model needs. The old filter only ever went the other way."""
    if s <= OCV_CURVE[0][1]:
        return OCV_CURVE[0][0]
    if s >= OCV_CURVE[-1][1]:
        return OCV_CURVE[-1][0]
    for (v0, s0), (v1, s1) in zip(OCV_CURVE, OCV_CURVE[1:]):
        if s <= s1:
            return v0 + (v1 - v0) * (s - s0) / (s1 - s0)
    return OCV_CURVE[-1][0]


def docv_dsoc(s: float) -> float:
    """dOCV/dSOC — the measurement Jacobian. Piecewise constant, since the
    curve is piecewise linear. Around SOC 0.70-0.80 on this curve it is
    1.8 V per unit SOC, so the ~0.013 of SOC a run traverses is about 23 mV
    of terminal voltage: resolvable, which is why the EKF is worth having on
    this chemistry. On LiFePO4 it would be near zero through the plateau and
    the update step would do nothing."""
    s = min(max(s, 0.0), 1.0)
    for (v0, s0), (v1, s1) in zip(OCV_CURVE, OCV_CURVE[1:]):
        if s <= s1:
            ds = s1 - s0
            return (v1 - v0) / ds if ds > 1e-9 else 0.0
    v0, s0 = OCV_CURVE[-2]
    v1, s1 = OCV_CURVE[-1]
    ds = s1 - s0
    return (v1 - v0) / ds if ds > 1e-9 else 0.0


class SOCEstimatorEKF:
    """
    Extended Kalman filter for SOC on a 2S 18650 NMC pack.

    STATE            x = [SOC, V1]
      SOC  coulomb-counted, corrected by terminal voltage through the OCV curve
      V1   1-RC polarisation voltage. Inert when pack_r1_ohm == 0, which makes
           the filter single-state and equivalent to an R-only model. Enable it
           only once R1 and tau have been measured from relaxation transients.

    PROCESS
      SOC(k+1) = SOC(k) - i_net·dt / Q
      V1(k+1)  = V1(k)·exp(-dt/tau) + R1·(1 - exp(-dt/tau))·i_pack

    MEASUREMENT
      V_batt = OCV(SOC) - i_pack·R0 - V1
      H      = [dOCV/dSOC, -1]

    CURRENT REFERENCE FRAME — the thing most likely to be wrong here, carried
    over verbatim from the previous revision because it has NOT been resolved.
    The INA253 shunts sit between each boost's VOUT and VBUS, so I_batt is a
    BUS-SIDE current. Coulombs leave the pack on the BATTERY side, which at
    V_bus 15.8 / V_batt 8.1 / eta 0.9 is about 2.17x larger.

        I_pack = I_batt · V_bus / (V_batt · eta)

    I_charge comes from the Ag105 over I2C and is assumed BATTERY-side. Set
    i_charge_bus_side=True if that turns out to be wrong. It has never been
    exercised, because nothing has ever charged this pack.

    WHY THE GAINS ARE NOT CONSTANTS ANY MORE. The previous filter pulled SOC
    toward the OCV estimate at k_rest when resting and k_load under load. That
    is the right instinct — trust voltage more at rest — but it is a fixed
    two-level approximation to something that genuinely varies: how informative
    the voltage reading is depends on the OCV slope at the present SOC, how
    noisy the measurement is, and how much the coulomb count has drifted since
    the last correction. K = P·H / (H·P·H + R) is exactly that quantity.
    """

    def __init__(self, capacity_ah, r_int, eta,
                 r1_ohm=0.0, tau_s=30.0,
                 q_soc=1e-9, q_v1=1e-7, r_meas=4e-4,
                 p0_soc=1e-2, p0_v1=1e-4,
                 i_batt_bidirectional=False, i_charge_bus_side=False):
        self.q_as   = capacity_ah * 3600.0
        self.r0     = r_int
        self.eta    = max(0.1, eta)
        self.r1     = max(0.0, r1_ohm)
        self.tau    = max(1e-3, tau_s)
        self.q_soc  = q_soc
        self.q_v1   = q_v1
        self.r_meas = max(1e-9, r_meas)
        self.bidir  = bool(i_batt_bidirectional)
        self.ic_bus = bool(i_charge_bus_side)

        self.soc = None
        self.v1  = 0.0
        # Covariance, 2x2 held as plain floats. Off-diagonals are carried
        # because the OCV correction couples SOC and V1 through the shared
        # measurement; dropping them would make the filter overconfident.
        self.p00, self.p01 = p0_soc, 0.0
        self.p10, self.p11 = 0.0, p0_v1

        # Diagnostics, published rather than logged so they can be plotted.
        self.innov = 0.0
        self.k_soc = 0.0
        self.i_pack = 0.0

    def seed(self, v_batt: float, soc_init: float = -1.0):
        """Seed from rested OCV. Valid because every cycle starts with 15 s of
        idle before the drive cycle begins, which is long enough for a usable
        open-circuit reading on this pack."""
        self.soc = soc_from_ocv(v_batt) if soc_init < 0.0 else soc_init
        self.v1 = 0.0
        return self.soc

    def _pack_currents(self, v_batt, i_batt_bus, i_charge, v_bus):
        ib = i_batt_bus if self.bidir else abs(i_batt_bus)
        if v_batt > 1.0:
            i_dis = ib * v_bus / (v_batt * self.eta)
        else:
            i_dis = 0.0
        ic = max(0.0, i_charge)
        if self.ic_bus and v_batt > 1.0:
            # Bus-side charge current referred to the pack. Note eta MULTIPLIES
            # here and divides for discharge: losses are on the far side of the
            # converter in each direction.
            ic = ic * v_bus * self.eta / v_batt
        return i_dis - ic, i_dis - ic

    def update(self, dt, v_batt, i_batt_bus, i_charge, v_bus):
        if self.soc is None:
            self.seed(v_batt)
        if dt <= 0.0 or dt > 1.0:        # startup, or a telemetry gap: skip
            return self.soc

        i_net, i_pack = self._pack_currents(v_batt, i_batt_bus, i_charge, v_bus)
        self.i_pack = i_pack

        # ── PREDICT ───────────────────────────────────────────────────────────
        if self.q_as > 0.0:
            self.soc -= i_net * dt / self.q_as
        if self.r1 > 0.0:
            a = math.exp(-dt / self.tau)
            self.v1 = self.v1 * a + self.r1 * (1.0 - a) * i_pack
        else:
            a = 0.0
            self.v1 = 0.0

        # P = F·P·F' + Q, with F = diag(1, a)
        self.p00 = self.p00 + self.q_soc * dt
        self.p01 = self.p01 * a
        self.p10 = self.p10 * a
        self.p11 = self.p11 * a * a + self.q_v1 * dt

        # ── UPDATE ────────────────────────────────────────────────────────────
        # Guard the correction when the pack is disconnected or the reading is
        # nonsense; predicting on alone is better than folding in garbage.
        if v_batt > 1.0:
            h0 = docv_dsoc(self.soc)
            h1 = -1.0 if self.r1 > 0.0 else 0.0

            v_pred = ocv_from_soc(self.soc) - i_pack * self.r0 - self.v1
            y = v_batt - v_pred
            self.innov = y

            # S = H·P·H' + R
            ph0 = self.p00 * h0 + self.p01 * h1
            ph1 = self.p10 * h0 + self.p11 * h1
            s = h0 * ph0 + h1 * ph1 + self.r_meas

            k0 = ph0 / s
            k1 = ph1 / s
            self.k_soc = k0

            self.soc += k0 * y
            if self.r1 > 0.0:
                self.v1 += k1 * y

            # Joseph form is overkill for 2x2 here; the simple form is stable
            # provided P stays symmetric, which the explicit symmetrise below
            # enforces against accumulated float drift.
            p00 = self.p00 - k0 * ph0
            p01 = self.p01 - k0 * ph1
            p10 = self.p10 - k1 * ph0
            p11 = self.p11 - k1 * ph1
            self.p00 = max(p00, 1e-12)
            self.p11 = max(p11, 1e-12)
            self.p01 = self.p10 = 0.5 * (p01 + p10)

        self.soc = min(1.0, max(0.0, self.soc))
        return self.soc

    @property
    def sigma_soc(self):
        return math.sqrt(max(self.p00, 0.0))


class H2Usage:
    """
    Hydrogen consumption from stack current. Faraday's law, plus one constant.

        m_dot = N . I_stack . M_H2 / (2F)  +  m_dot_purge
        I_stack = V_bus . I_fc / (V_fc . eta_boost)

    REFERENCE FRAME, the thing most likely to be wrong. V_fc (packet field 4)
    is the STACK voltage. I_fc (field 5) is the BUS-side boost output current.
    They are on opposite sides of the converter, so multiplying them gives
    neither stack power nor bus power -- that mistake understated FC power by
    about 2x in an earlier analysis. The conversion above is required.

    WHY NO FUEL MAP. The H-20 datasheet's flow-vs-power table, read back
    through Faraday at N=14, implies 0.70 V/cell flat from 5 to 15 W and then
    0.61 and 0.50 V at 20 and 23.5 W. That is a polarisation curve, so the map
    is Faraday with the droop already in it and carries nothing the measured
    stack current does not. Interpolating it here would add a second, staler
    copy of the same physics.

    WHAT IS NOT MEASURED. n_cells is INFERRED from that same datasheet map, not
    read off the manual. purge_ml_min is zero by default: the purge timer is
    fixed at 100 ms every 10.340 s regardless of load, so the term is a genuine
    constant, but its magnitude has never been measured and the datasheet curve
    passes through the origin so it supplies no intercept. A constant added to
    the stage cost cannot move the optimum, so this matters for accounting and
    not for the policy.
    """

    F_CONST = 96485.0      # C/mol
    VM      = 22414.0      # ml/mol at STP
    M_H2    = 2.016        # g/mol

    def __init__(self, n_cells=14, eta_boost=0.90, purge_ml_min=0.0):
        self.n     = max(1, int(n_cells))
        self.eta   = max(0.1, float(eta_boost))
        self.purge_g_s = float(purge_ml_min) / self.VM * self.M_H2 / 60.0
        self.total_g = 0.0
        self.i_stack = 0.0
        self.p_stack = 0.0
        self.mdot    = 0.0
        self.faraday_ml_min = 0.0

    def update(self, dt, v_fc, i_fc_bus, v_bus):
        if dt <= 0.0 or dt > 1.0:          # startup, or a telemetry gap
            return self.total_g

        if v_fc > 1.0:
            self.i_stack = v_bus * i_fc_bus / (v_fc * self.eta)
        else:
            self.i_stack = 0.0             # stack off the bus: no conduction
        if self.i_stack < 0.0:
            self.i_stack = 0.0             # the FC cannot sink current

        self.p_stack = v_fc * self.i_stack
        faraday_g_s  = self.i_stack * self.n * self.M_H2 / (2.0 * self.F_CONST)
        self.faraday_ml_min = faraday_g_s / self.M_H2 * self.VM * 60.0

        # Purge runs whenever the stack is pressurised, loaded or not, so it is
        # NOT gated on current. With the default of zero this adds nothing.
        self.mdot = faraday_g_s + self.purge_g_s
        self.total_g += self.mdot * dt
        return self.total_g


class TeensyBridgeNode(Node):

    def __init__(self):
        super().__init__("teensy_bridge_node")

        # ── Parameters ────────────────────────────────────────────────────────
        self.declare_parameter("teensy_ip",  DEFAULT_TEENSY_IP)
        self.declare_parameter("publish_hz", 50.0)
        self.declare_parameter("comms_hz",   1.0)

        # ── SOC estimator ─────────────────────────────────────────────────────
        self.declare_parameter("pack_capacity_ah", 5.0)    # Buddy RC 2S 18650, 36 Wh
        self.declare_parameter("pack_r_int_ohm",   0.050)  # TODO measure — see below
        self.declare_parameter("boost_efficiency", 0.90)
        self.declare_parameter("soc_init",        -1.0)    # <0 = seed from OCV

        # EKF tuning. Defaults are deliberately conservative: q_soc says the
        # coulomb count is good (it is, over a 200 s run), r_meas says the
        # voltage reading has about 20 mV of noise. Raise q_soc if SOC is
        # clearly lagging truth; raise r_meas if SOC is twitching on ripple.
        self.declare_parameter("pack_r1_ohm",      0.0)    # 0 = single-state
        self.declare_parameter("pack_tau_s",       30.0)
        self.declare_parameter("soc_q_soc",        1e-9)   # SOC^2 per second
        self.declare_parameter("soc_q_v1",         1e-7)   # V^2 per second
        self.declare_parameter("soc_r_meas",       4e-4)   # V^2  (20 mV sigma)
        self.declare_parameter("soc_p0",           1e-2)   # initial SOC variance
        self.declare_parameter("soc_i_batt_bidirectional", False)
        self.declare_parameter("soc_i_charge_bus_side",    False)

        # Retained so existing launch files and param overrides do not fail.
        # The EKF derives its gains; these are no longer read.
        self.declare_parameter("soc_k_rest",       0.050)
        self.declare_parameter("soc_k_load",       0.002)
        self.declare_parameter("soc_rest_i_a",     0.050)
        self.declare_parameter("soc_rest_s",       3.0)

        # ── Hydrogen usage ────────────────────────────────────────────────
        # n_cells is INFERRED from the H-20 fuel map, not read off the manual.
        # purge_ml_min is UNMEASURED: an idle soak with no electrical load
        # gives it directly, since Faraday consumption is then zero.
        self.declare_parameter("h2_n_cells",     14)
        self.declare_parameter("h2_eta_boost",   0.90)
        self.declare_parameter("h2_purge_ml_min", 0.0)

        self.declare_parameter("share_min_i_a",    0.05)

        teensy_ip  = self.get_parameter("teensy_ip").value
        publish_hz = self.get_parameter("publish_hz").value
        comms_hz   = self.get_parameter("comms_hz").value

        cap_ah = float(self.get_parameter("pack_capacity_ah").value)
        r1     = float(self.get_parameter("pack_r1_ohm").value)
        self._soc = SOCEstimatorEKF(
            capacity_ah = cap_ah,
            r_int       = float(self.get_parameter("pack_r_int_ohm").value),
            eta         = float(self.get_parameter("boost_efficiency").value),
            r1_ohm      = r1,
            tau_s       = float(self.get_parameter("pack_tau_s").value),
            q_soc       = float(self.get_parameter("soc_q_soc").value),
            q_v1        = float(self.get_parameter("soc_q_v1").value),
            r_meas      = float(self.get_parameter("soc_r_meas").value),
            p0_soc      = float(self.get_parameter("soc_p0").value),
            i_batt_bidirectional = bool(
                self.get_parameter("soc_i_batt_bidirectional").value),
            i_charge_bus_side = bool(
                self.get_parameter("soc_i_charge_bus_side").value),
        )
        self._h2 = H2Usage(
            n_cells      = int(self.get_parameter("h2_n_cells").value),
            eta_boost    = float(self.get_parameter("h2_eta_boost").value),
            purge_ml_min = float(self.get_parameter("h2_purge_ml_min").value),
        )
        self.get_logger().info(
            f"H2: Faraday from stack current, "
            f"N={self.get_parameter('h2_n_cells').value} cells (INFERRED), "
            f"eta {self.get_parameter('h2_eta_boost').value}, purge "
            f"{self.get_parameter('h2_purge_ml_min').value} ml/min"
            f"{' (UNMEASURED)' if float(self.get_parameter('h2_purge_ml_min').value) == 0.0 else ''}")

        self._soc_t_prev = 0.0
        self._share_min_i = float(self.get_parameter("share_min_i_a").value)
        self._share_last  = 0.5
        _si = float(self.get_parameter("soc_init").value)
        if _si >= 0.0:
            self._soc.seed(0.0, _si)

        if cap_ah <= 0.0:
            self.get_logger().warning(
                "pack_capacity_ah is 0 — coulomb counting DISABLED, the EKF "
                "prediction step does nothing and SOC is OCV-only. Set it to "
                "the real pack capacity.")
        else:
            self.get_logger().info(
                f"SOC: EKF, {cap_ah:.2f} Ah, R0 "
                f"{self.get_parameter('pack_r_int_ohm').value} ohm, "
                f"{'2-state (1-RC)' if r1 > 0 else '1-state (R only)'}, "
                f"sigma_v {math.sqrt(float(self.get_parameter('soc_r_meas').value))*1000:.0f} mV")
        self.get_logger().info(
            "SOC: soc_k_rest/soc_k_load are retained but UNUSED — the EKF "
            "derives its gain from the OCV slope and the covariances.")
        if abs(float(self.get_parameter("pack_r_int_ohm").value) - 0.050) < 1e-9:
            self.get_logger().warning(
                "pack_r_int_ohm is still the 0.050 placeholder. At 0.8 A that "
                "is 40 mV of IR, against ~23 mV of OCV swing across a run — "
                "absolute SOC is not trustworthy until this is measured.")

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
        # NEW — EKF internals, for tuning. Separate topic so /vehicle_state
        # keeps its 18-element contract and no analysis script has to change.
        self._pub_socdiag = self.create_publisher(
            Float64MultiArray, "/soc_diagnostics", qos_sensor)
        # NEW — cumulative hydrogen in grams. Own topic for the same reason as
        # /soc_diagnostics: /vehicle_state's 18-element contract is depended on
        # by every analysis script.
        self._pub_h2 = self.create_publisher(
            Float64MultiArray, "/h2_usage", qos_sensor)

        # ── Subscriber ────────────────────────────────────────────────────────
        self._sub_cmd = self.create_subscription(
            Float64MultiArray, "/ems_command",
            self._cb_ems_command, qos_reliable)

        # ── Internal state ────────────────────────────────────────────────────
        self._last_state: list = [0.0] * 18
        self._last_socdiag: list = [0.0] * 6
        self._last_h2: list = [0.0] * 6
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
            if _xor(chunk[1:-1]) != chunk[-1]:
                self.get_logger().debug("Checksum mismatch — packet dropped")
                continue
            try:
                (_, ts, ctr,
                 v, Vb, Ib, Ic, Vfc, Ifc, Vbus,
                 Vrgn,
                 Vchg,
                 sha,
                 dFC, dBT,
                 chg_status,
                 sw_state,
                 flt,
                 err_code,
                 err_src,
                 _cs,
                 ) = struct.unpack(T2P_FMT, chunk)
            except struct.error as e:
                self.get_logger().debug(f"Unpack error: {e}")
                continue

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

            _tot = abs(Ifc) + abs(Ib)
            if _tot > self._share_min_i:
                self._share_last = abs(Ifc) / _tot
            sha = self._share_last

            # SOC — EKF (see SOCEstimatorEKF)
            _now_s = time.monotonic()
            _dt = (_now_s - self._soc_t_prev) if self._soc_t_prev else 0.0
            self._soc_t_prev = _now_s
            soc = self._soc.update(_dt, Vb, Ib, Ic, Vbus)

            # H2 — Faraday on the stack current (see H2Usage)
            self._h2.update(_dt, Vfc, Ifc, Vbus)

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
            self._last_h2 = [
                float(self._h2.mdot),
                float(self._h2.total_g),
                float(self._h2.i_stack),
                float(self._h2.p_stack),
                float(self._h2.faraday_ml_min),
                float(self._h2.purge_g_s),
            ]
            self._last_socdiag = [
                float(soc),
                float(self._soc.sigma_soc),
                float(self._soc.innov),
                float(self._soc.k_soc),
                float(self._soc.i_pack),
                float(self._soc.v1),
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
            state[14] = float(FAULT_COMMS_STALE)
            self._last_state = state

        msg = Float64MultiArray()
        msg.data = self._last_state
        self._pub_state.publish(msg)

        dmsg = Float64MultiArray()
        dmsg.data = self._last_socdiag
        self._pub_socdiag.publish(dmsg)

        hmsg = Float64MultiArray()
        hmsg.data = self._last_h2
        self._pub_h2.publish(hmsg)

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
