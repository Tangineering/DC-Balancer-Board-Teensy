#!/usr/bin/env python3
"""plant_mimo.py — 2x2 small-signal design plant for the MIMO share/drive study.

    u = [ dr        droop ratio command (dimensionless, r in [0.15, 0.85]) ]
        [ di_cmd    motor current command (A)                              ]
    y = [ dalpha    measured current share (dimensionless)                 ]
        [ dv        measured wheel speed (m/s)                             ]

Structure (see mimo_system_model.md §3):

    G(s) = [ G11(s)   G12(s) ]        G21 = 0 by construction (§4.3)
           [   0      G22(s) ]

  * G11 — the SHIPPED SISO share design plant, K*e^(-Td s)/((taur s+1)(tauf s+1)),
    Pade(2), with K evaluated at the operating point:
        K = 1 + dV0 (1 - 2 r0) / (k_d I_tot0)
    (controller_design/system_model.md §6d; the SISO K in [0.55, 1.45] envelope is
    exactly the image of this expression over the OP box).
  * G22 — the drive channel: VESC transport delay + current-loop lag -> motor
    torque -> longitudinal 1st-order vehicle mode -> encoder speed.
  * G12 — drive-to-share coupling: the motor's bus-current draw moves I_tot, and
    with a source-voltage mismatch dV0 != 0 the static share law is I_tot-dependent:
        dalpha/dI_tot = -dV0 r0 (1 - r0) / (k_d I_tot0^2)
    The coupling passes through the SAME 1/(tauf s + 1) measurement prefilter as
    G11 (shared states -- explicit block assembly, not a parallel duplicate).

State ordering (10 states nominal):
    x = [ x_share(3: Pade2(Td) + 1/(taur s+1)) ,
          x_drive(3: Pade2(Td_v) + 1/(tau_v s+1)) ,
          x_mech(1: 1/(m_eff s + b_eff)) ,
          x_est(2: Pade2(Td_est(v0)) -- velocity-estimator delay, MEASUREMENT path
                only; the coupling path G12 taps the UNDELAYED speed) ,
          x_filt(1: 1/(tauf s+1), dropped when tauf == 0) ]

Every constant below cites its source. Unknowns are tagged TODO(calibrate) /
TODO(identify) and each is covered by a named corner axis (mimo_system_model.md §8).

Run `<ctrl-venv python> validate_mimo_model.py` for the Phase-1 gate battery.
"""

import numpy as np

from hinf_mimo import (SS, tf2ss, pade2, ss_series, ss_scale, ss_lmul, ss_rmul)

# ─────────────────────────────────────────────────────────────────────────────
# Share-loop / droop constants
# COPIED from controller_design/validate_model.py @ 51b8962 (K_D, RD1, RD2,
# RINJ, AV, KSNS, VREF) — the as-built droop network after the 16 V retune.
# ─────────────────────────────────────────────────────────────────────────────
VREF   = 0.6            # V     TPS61288 FB reference        TODO(verify: TPS61288 DS §7.5)
RD1    = 215e3          # ohm   FB top; bodged 237k -> 215k (16 V retune 2026-07-11)
RD2    = 10e3           # ohm   schematic RD2-*
RINJ   = 53.6e3         # ohm   schematic RINJ-*
AV     = 1 + 40.2/10    # -     OPA197 non-inverting gain = 5.02
KSNS   = 0.1            # V/A   INA253A1 as fitted (CLAUDE.md §5)
RE_MAX = KSNS*AV*RD1/RINJ                 # ohm, max electronic droop resistance
K_D    = 0.30           # ohm   firmware K_DROOP (system_model.md §4)
V_BUS0 = VREF*(1 + RD1/RD2 + RD1/RINJ)    # 15.907 V no-load bus setpoint

# Share-loop dynamics (controller_design/synthesize_controller.py:47-57 @ 51b8962)
TD_NOM   = 1.0e-3       # s     loop transport delay        TODO(calibrate): bench step test
TAUR_NOM = 100e-6       # s     droop/bus response pole     TODO(calibrate)
TAUF_NOM = 0.8e-3       # s     200 Hz firmware measurement prefilter (implemented)

# ─────────────────────────────────────────────────────────────────────────────
# Drive-channel constants
# CALIBRATED 2026-08-15/16 — source of truth: calibration/motor_id_20260815.md.
# The pre-calibration placeholders (KV 1750 chain, 66 mm tire radius, M_BUILT +
# M_ROT mass split, aero/C_rr/free-run drag composite) are RETIRED; the drive
# channel is now a measured plant. See mimo_system_model.md §4.2 and §9.2.
# ─────────────────────────────────────────────────────────────────────────────
PHI     = 9.49          # -      motor -> flywheel reduction, stock gearing (VESC doc §3)
R_T     = 0.0762        # m      flywheel ROLLING radius (3.00 in, MEASURED 2026-08-13).
                        #        The encoder is coupled to the flywheel and the flywheel's
                        #        own radius is the rolling radius (coupling resolved
                        #        2026-08-16 as surface/roller), so v is flywheel SURFACE
                        #        speed and r_t is the correct linear conversion.
M_EFF   = 3.5           # kg     equivalent linear inertia of the flywheel assembly
                        #        (MEASURED: J = 0.0203 kg*m^2 at r_t; J/r_t^2 = 3.50 kg)
ETA_DT  = 0.85          # -      driveline efficiency (user decision 1)  TODO(calibrate)
                        #        DELIBERATELY UNCHANGED 2026-08-16b.  The ML0136-0139
                        #        ramp fits imply a force constant ~1.78x this chain's
                        #        (see K_V_NOM), i.e. eta_dt >= 1.0, which is unphysical --
                        #        so the residual is NOT an efficiency and is carried by
                        #        the K_v axis instead.  Raising eta_dt here would also
                        #        move i_m0 and the §4.4 coupling gains, which no
                        #        measurement of this round touches.
ETA_V   = 0.85          # -      VESC inverter efficiency  TODO(calibrate)
K_ENC   = 1.0           # -      encoder speed-chain gain. NO LONGER structurally
                        #        unknown: 240 counts/rev (120 slots x2 decode, counted
                        #        and hardware-confirmed 2026-08-16) and r_t above fix
                        #        the chain end to end.  Retained as an explicit unity
                        #        factor so the K_v corner has a place to act.

# Drive-channel gain residual, carried on K_v (see drive_corners() and
# mimo_system_model.md §4.2 "the gain datapoint").  MEASURED 2026-08-16b: the ML0136-0139
# +12 A ramps give a NET acceleration of 0.186-0.204 (m/s^2)/A (startup-excluded fits;
# the operator's 0.158 figure is the same ML0139 ramp fitted INCLUDING its startup window
# and is depressed by it -- reconciliation in calibration/motor_id_20260815.md).  Adding
# back the modelled drag at the fit speeds gives an implied K_F of 0.805 N/A = 1.78x the
# modelled 0.4516 N/A.  The measured 4.5 +- 0.4 A cruise hold pulls the OTHER way
# (implied K_F 0.409 N/A = 0.91x).  The two disagree by a factor of ~2 and no single
# constant in this chain reconciles them (m_eff ~ 1.6-2.0 kg would; that is an open bench
# item, not a modelling decision).  The design plant is therefore centred on the GEOMETRIC
# MEAN of the two implied gains and the K_v axis is widened to span both.
K_V_NOM = 1.25          # -      sqrt(0.906 * 1.783) = 1.271, rounded to 1.25.


# Motor torque constant. Castle Creations 1406 1900KV, 4-pole (p = 2 pole pairs).
# VESC Tool FOC detection 2026-08-15: flux linkage lambda = 1.422 mWb.
#   k_t = (3/2)*p*lambda = 1.5*2*1.422e-3 = 4.266e-3 N*m/A   (q-axis peak convention,
#   which is the convention setCurrent() commands).
# Cross-check: lambda_pred = 60/(sqrt(3)*2*pi*KV*p) = 1.451 mWb, 2.0 % off -> p = 2
# confirmed.  Replaces the 5.457e-3 KV-1750 placeholder (x0.78).
K_T     = 4.266e-3      # N*m/A  MEASURED (calibration/motor_id_20260815.md)

# Motor phase resistance, VESC Tool FOC detection 2026-08-15.
R_M     = 0.0226        # ohm    MEASURED (replaces the 0.075 ohm spec-can placeholder)

# VESC current-loop transport + lag.
TAU_V_NOM = 1.0e-3      # s      MEASURED 2026-08-16 (VESC Tool sampled current step,
                        #        63 % at ~1-1.5 ms; matches KP/L = KI/R = 1004 rad/s)
TD_V_NOM  = 2.0e-3      # s      DECIDED 2026-08-15 (analytic bound 0.9-2 ms: UART frame
                        #        781 us + packet thread <~1 ms + FOC pickup <= 70 us).
                        #        Not measured -- direct measurement was declined to keep
                        #        a current instrument out of the motor power path.

# ── Velocity-ESTIMATOR dynamics (NEW 2026-08-16b) ───────────────────────────
# The firmware's velocity estimate is NOT an ideal measurement and is no longer modelled
# as one.  This element was ABSENT from the synthesis plant, and its absence is the
# root cause of the ML0136-ML0139 closed-loop limit cycle (2.3-2.6 Hz = 14.5-16.3 rad/s =
# the design crossover, at every step size 0.1/0.5/1.0 m/s): the shipped estimator was a
# ~113 ms boxcar (~56 ms group delay = 52-58 deg at 16 rad/s, against a 49.6 deg design
# phase margin), i.e. the loop was closed around a lag the design never saw.
#
# The REPLACEMENT estimator (firmware round, parallel to this one) is an EDGE-PERIOD
# estimator; this is the contract it is modelled against:
#   * the period is measured same-edge-type over one full slot pitch;
#   * N periods are averaged (N = N_EST = 2, configurable in firmware);
#   * the estimate is LATCHED once per pitch (zero-order hold between pitches);
#   * below ~0.03 m/s the estimator times out and reports 0.
# Its dynamics are therefore an averaging window of N pitches plus a one-pitch hold:
#   averaging over the last N*pitch of travel  -> mean-value delay  N*pitch/(2v)
#   latched once per pitch (ZOH)               -> mean hold delay     pitch/(2v)
#   total effective transport delay Td_est(v)  = (N+1)*pitch/(2v)
# It is VELOCITY-DEPENDENT, and that dependence is the whole point: the delay explodes at
# low speed.  Modelled as a pure transport delay (Padé(2)), not as the exact boxcar: the
# difference is in the >1/Td_est stopband shape, which is far above any achieved crossover.
ENC_SLOTS = 120         # -      slots on the encoder disc (COUNTED 2026-08-16; the x2
                        #        quadrature decode gives 240 counts/rev, hardware-confirmed)
PITCH_M = 2.0*np.pi*R_T/ENC_SLOTS      # m, 3.9898 mm of flywheel SURFACE travel per slot
N_EST   = 2             # -      periods averaged (firmware default; configurable)
V_EST_MIN = 0.03        # m/s    estimator timeout floor -- below this it reports 0.
                        #        The design is NOT validated below V0_VALID_MIN (see
                        #        TD_EST_V0_SET); this constant only records the hard floor.
TD_EST_V0_SET = (0.5, 2.0, 5.0)   # m/s, the estimator-delay corner axis (§4.2)
V0_VALID_MIN  = 0.5     # m/s    VALIDITY FLOOR of the drive design.  Td_est at 0.5 m/s is
                        #        11.97 ms; at 0.3 m/s it is 19.9 ms and at 0.1 m/s 59.8 ms
                        #        -- i.e. below the floor the delay corner is OPEN and the
                        #        loop is not gate-checked.  Operating there needs either a
                        #        larger corner (bought with bandwidth) or a gain schedule.


def td_est(v0, N=N_EST, pitch=PITCH_M):
    """Effective velocity-estimator transport delay [s] at speed v0 [m/s].

        Td_est(v) = (N + 1) * pitch / (2 v)

    = N*pitch/(2v) (mean-value delay of the N-pitch averaging window)
    + pitch/(2v)   (mean staleness of the once-per-pitch latch).
    At N = 2, pitch = 3.9898 mm: 11.97 ms at 0.5 m/s, 2.99 ms at 2 m/s, 1.20 ms at 5 m/s.
    """
    v = max(float(v0), V_EST_MIN)
    return (N + 1.0)*pitch/(2.0*v)


# Longitudinal drag. MEASURED as a LUMPED law F(v) ~ F_c + b_eff*(v - v0) about the
# design speed, replacing the aero + C_rr + motor-free-run composite (which was three
# stacked placeholders and predicted the cruise current 4x low).
# Evidence: the TP0125-TP0134 steady-state ladder (10 holds, 3.5-5.5 A) plus the
# ML0135 small-signal staircase (5 incremental steps, 1.9-3.4 m/s) agree on the slope.
B_EFF_NOM = 0.32        # N*s/m  local dF/dv at v0 = 2.0 m/s, +-15 % (MEASURED; the
                        #        ladder fit and the small-signal steps agree to 6 %).
                        #        The full curve is strongly concave (Stribeck-like,
                        #        F = 1.751*v^0.30); pure viscous is excluded (chi^2 x1400).
                        #        BELOW ~1.5 m/s the local slope roughly DOUBLES -- that
                        #        amplitude dependence is carried by pole_factor, not by
                        #        a v0 term (see b_eff() and mimo_system_model.md §4.2).
F_COULOMB = 1.2         # N      Coulomb/breakaway drag term.  THERMALLY VARIABLE:
                        #        1.31 N cold (TP ladder) vs 1.05-1.1 N warm (ML0135);
                        #        1.2 +- 0.25 N is the adopted thermal-mean spread.
                        #        Enters the OPERATING POINT (i_m0 -> coupling gains
                        #        §4.4) only; its dF/dv is zero, so it is NOT in b_eff.


# ─────────────────────────────────────────────────────────────────────────────
# Operating point / parameter containers
# ─────────────────────────────────────────────────────────────────────────────

def nominal_op():
    """Nominal design operating point (plan §1, last bullet).

    dV0 = +0.2 V is HALF the +-0.4 V budget on purpose: it is a sign-uncertain
    quantity (mimo_system_model.md §4.4), so synthesizing at zero would give the
    MIMO controller no coupling to exploit, and synthesizing at a full corner
    would over-commit to one sign.
    """
    return dict(I_tot0=2.0, r0=0.5, dV0=0.2, v0=2.0)


def nominal_params():
    """Nominal plant parameters. Corner families override individual entries."""
    return dict(
        # share channel
        k_d=K_D, Td=TD_NOM, taur=TAUR_NOM, tauf=TAUF_NOM,
        # drive channel
        tau_v=TAU_V_NOM, Td_v=TD_V_NOM,
        k_t=K_T, phi=PHI, r_t=R_T, m_eff=M_EFF,
        eta_dt=ETA_DT, eta_v=ETA_V, K_enc=K_ENC,
        # velocity estimator: Td_est=None => derived from the OP speed via td_est().
        # Set it explicitly only to pin a corner independently of the OP.
        N_est=N_EST, Td_est=None,
        # load / coupling
        b_eff_nom=B_EFF_NOM, F_c=F_COULOMB,
        R_m=R_M, V_bus0=V_BUS0,
        # multiplicative corner knobs (pole_factor 1.0 = nominal; K_v is NOT 1.0 --
        # see K_V_NOM, the drive gain is centred on the measured evidence)
        K_v=K_V_NOM, pole_factor=1.0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Operating-point algebra (mimo_system_model.md §4)
# ─────────────────────────────────────────────────────────────────────────────

def share_gain_K(op, p):
    """K = 1 + dV0 (1 - 2 r0)/(k_d I_tot0).

    COPIED (as an expression) from controller_design/validate_model.py @ 51b8962
    check 2 -- there verified against a numeric derivative of the exact
    two-Thevenin circuit solution to 1e-4.
    """
    return 1.0 + op['dV0']*(1.0 - 2.0*op['r0'])/(p['k_d']*op['I_tot0'])


def dalpha_dItot(op, p):
    """Static coupling sensitivity  d(alpha)/d(I_tot) at the OP.

    alpha(r, I_tot) = r + dV0 r (1-r)/(k_d I_tot)   (validate_model.py check 1)
    => d(alpha)/d(I_tot) = -dV0 r0 (1-r0)/(k_d I_tot0^2).
    ZERO at dV0 = 0 and SIGN-UNCERTAIN over the +-0.4 V budget: the whole MIMO
    coupling opportunity lives in this one number (mimo_system_model.md §4.4).
    """
    r0 = op['r0']
    return -op['dV0']*r0*(1.0 - r0)/(p['k_d']*op['I_tot0']**2)


def op_alpha0(op, p):
    """Realized static share at the OP: alpha0 = r0 + dV0 r0(1-r0)/(k_d I_tot0)."""
    r0 = op['r0']
    return r0 + op['dV0']*r0*(1.0 - r0)/(p['k_d']*op['I_tot0'])


ALPHA_MARGIN = 0.02


def op_feasible(op, p, margin=ALPHA_MARGIN):
    """Is (OP, dV0) a physically realizable small-signal operating point?

    The RT1987 ideal-diode switches are UNIDIRECTIONAL: a source cannot sink.
    If the static share law puts alpha0 outside (0, 1) the weaker source is
    blocked, the plant is at a CLAMPED operating point, and the linearization
    (and the K / d(alpha)/d(I_tot) expressions built on it) is meaningless there.

    This is a REFINEMENT of the plan's corner spec, forced by the physics: the
    plan's full OP x share-corner cross product contains infeasible combinations
    (notably every I_tot0 = 0.5 A point at |dV0| = 0.4 V, where the mismatch term
    dV0*r(1-r)/(k_d*I_tot) reaches +-0.56 share).  Infeasible combinations are
    SKIPPED, and the count is reported, rather than silently linearized.
    See mimo_system_model.md §7.2.
    """
    a = op_alpha0(op, p)
    return margin < a < 1.0 - margin


def b_eff(op, p):
    """Linearized longitudinal damping at the OP, flywheel-referred [N*s/m].

        b_eff = b_eff_nom * pole_factor          (b_eff_nom = 0.32 N*s/m MEASURED)

    This is a MEASURED LOCAL SLOPE (dF/dv at v0 = 2.0 m/s), not a composite of
    modelled loss terms.  It therefore carries no explicit v0 dependence: the true
    drag curve is concave, so the slope is a function of speed, but the measurement
    fixes it only at the design speed.  The known amplitude dependence -- the slope
    roughly DOUBLES below ~1.5 m/s -- is carried by the pole_factor in {0.5, 3}
    corner axis, which is the honest representation of a locally-identified slope.

    F_c (Coulomb) is deliberately absent: it is sign(v)-shaped, so it sets the
    operating-point torque (see op_motor_current) but its derivative is zero.
    """
    return p['pole_factor']*p['b_eff_nom']


def force_per_amp(p):
    """Wheel force per amp of motor current [N/A] = k_t * eta_dt * phi / r_t."""
    return p['k_t']*p['eta_dt']*p['phi']/p['r_t']


def op_motor_current(op, p):
    """Steady-state motor current at the OP [A]: slope term + Coulomb term.

        F(v0) = b_eff*v0 + F_c   ->   i_m0 = F(v0)/force_per_amp

    At the nominal OP this yields i_m0 = 4.07 A.  The bench holds measure 4.5 +- 0.4 A,
    so the model sits ~9 % below the band's centre and 0.6 % BELOW its lower edge --
    close, but NOT inside it.  Carrying the F_c thermal endpoints through gives a model
    envelope of 3.74 A (warm, F_c 1.05) to 4.32 A (cold, F_c 1.31), which likewise
    straddles the band's lower edge rather than covering it.
    The claim this supports is bounded accordingly: the calibrated model reproduces the
    measured cruise current to within ~10 %, against the pre-calibration composite's
    0.97 A (a factor of 4 low).  The residual is consistent with the eta_dt = 0.85
    placeholder, which scales every absolute force and is not measured.
    """
    F = b_eff(op, p)*op['v0'] + p['F_c']
    return F*p['r_t']/(p['k_t']*p['eta_dt']*p['phi'])


def bus_current_gains(op, p):
    """Linearized bus-current draw  dI_bus = A_i*di_m + A_w*domega.

        I_bus = (k_t*omega*i_m + R_m*i_m^2) / (eta_v * V_bus0)      (motor power)
        A_i = (k_t*omega0 + 2 R_m i_m0)/(eta_v V_bus0)   [A per A]
        A_w = (k_t*i_m0)/(eta_v V_bus0)                  [A per rad/s]

    omega0 = v0*phi/r_t.  CAVEAT: this rotor<->ground mapping is NOT fixed on the
    real vehicle (limited-slip diffs + slip, VESC doc §7); it is the design-case
    mapping and is one of the things the K_v corner axis stands in for.
    """
    omega0 = op['v0']*p['phi']/p['r_t']
    i_m0 = op_motor_current(op, p)
    denom = p['eta_v']*p['V_bus0']
    A_i = (p['k_t']*omega0 + 2.0*p['R_m']*i_m0)/denom
    A_w = (p['k_t']*i_m0)/denom
    return A_i, A_w, i_m0, omega0


# ─────────────────────────────────────────────────────────────────────────────
# Sub-block builders
# ─────────────────────────────────────────────────────────────────────────────

def share_prefilter_path(op, p):
    """K * Pade2(Td) * 1/(taur s + 1)  -- the share plant WITHOUT the tauf filter.

    COPIED from controller_design/synthesize_controller.py:60-65 @ 51b8962.
    ADAPTED: K is the OP-evaluated share_gain_K() instead of a free corner scalar,
    and the tauf stage is factored out so it can be SHARED with the G12 path.
    """
    g = pade2(p['Td'])
    g = ss_series(g, tf2ss([1.0], [p['taur'], 1.0]))
    return ss_scale(g, share_gain_K(op, p))


def vesc_current_path(p):
    """di_cmd -> di_m : Pade2(Td_v) * 1/(tau_v s + 1).  3 states, D = 0."""
    return ss_series(pade2(p['Td_v']), tf2ss([1.0], [p['tau_v'], 1.0]))


def vehicle_mech(op, p):
    """Wheel force -> true ground speed: 1/(m_eff s + b_eff).  1 state, D = 0."""
    return tf2ss([1.0], [p['m_eff'], b_eff(op, p)])


def op_td_est(op, p):
    """Estimator delay at this (OP, params): explicit p['Td_est'] or td_est(op['v0'])."""
    if p.get('Td_est') is not None:
        return float(p['Td_est'])
    return td_est(op['v0'], p.get('N_est', N_EST))


def speed_estimator_path(op, p):
    """dv_phys -> dv_meas: Pade2(Td_est(v0)).  2 states, D = 1 (proper, not strictly).

    Placed at the MEASUREMENT end of the drive channel, which is where it physically
    sits: it delays what the controller sees, not what the vehicle does.  That
    distinction is invisible in the SISO loop (series elements commute) but NOT in the
    2x2 design_plant, where the true speed dv_phys also drives the bus-current coupling
    into the share channel -- that path must NOT be delayed (see design_plant).

    A SEPARATE Pade(2) is used rather than lumping Td_est into Td_v.  Reason: the two
    delays have different corner axes (Td_v in {1, 4} ms is an actuator-path
    uncertainty; Td_est is a DETERMINISTIC function of speed), and at the low-speed
    corner the total would reach 16 ms, where a single Pade(2) is a visibly poorer fit
    than two chained ones over the crossover decade.  Cost: 2 extra states.
    """
    return pade2(op_td_est(op, p))


def drive_plant(op, p):
    """G22 alone: di_cmd -> dv (MEASURED, i.e. through the estimator).  6 states."""
    g = ss_series(vesc_current_path(p),
                  ss_scale(vehicle_mech(op, p), force_per_amp(p)))
    g = ss_series(g, speed_estimator_path(op, p))
    return ss_scale(g, p['K_enc']*p['K_v'])


def share_plant(op, p):
    """G11 alone: dr -> dalpha (measured), including the tauf prefilter.  4 states."""
    g = share_prefilter_path(op, p)
    if p['tauf'] > 0:
        g = ss_series(g, tf2ss([1.0], [p['tauf'], 1.0]))
    return g


# ─────────────────────────────────────────────────────────────────────────────
# The 2x2 design plant -- explicit block state-space assembly
# ─────────────────────────────────────────────────────────────────────────────

def design_plant(op=None, params=None):
    """2x2 design plant.  u = [dr; di_cmd], y = [dalpha; dv].

    Assembled explicitly (NOT by parallel/blkdiag composition) so that the single
    1/(tauf s + 1) measurement prefilter is SHARED between the direct share path
    G11 and the coupling path G12 -- duplicating it would double the filter state
    count and, more importantly, misrepresent the physics: there is exactly one
    prefilter, in firmware, downstream of the current-share estimate.

    The velocity ESTIMATOR delay (mimo_system_model.md §4.2, NEW 2026-08-16b) sits on
    the speed OUTPUT only.
    Returns a strictly-proper SS (D = 0) with 10 states (9 when tauf == 0).
    """
    op = dict(nominal_op() if op is None else op)
    p = dict(nominal_params() if params is None else params)

    Sp = share_prefilter_path(op, p)          # 3 states, D = 0
    Dv = vesc_current_path(p)                 # 3 states, D = 0  (-> di_m)
    Mm = vehicle_mech(op, p)                  # 1 state,  D = 0  (-> dv_phys)
    Ev = speed_estimator_path(op, p)          # 2 states, D = 1  (dv_phys -> dv_meas)

    assert abs(Sp.D).max() < 1e-12 and abs(Dv.D).max() < 1e-12 and abs(Mm.D).max() < 1e-12

    ns, nd, nm, ne = Sp.n, Dv.n, Mm.n, Ev.n
    tauf = p['tauf']
    nf = 1 if tauf > 0 else 0
    n = ns + nd + nm + ne + nf
    iS = slice(0, ns)
    iD = slice(ns, ns + nd)
    iM = slice(ns + nd, ns + nd + nm)
    iE = slice(ns + nd + nm, ns + nd + nm + ne)
    iF = ns + nd + nm + ne                    # only valid when nf == 1

    KF = force_per_amp(p)                     # N/A
    A_i, A_w, _, _ = bus_current_gains(op, p)
    Aw_v = A_w*p['phi']/p['r_t']              # A per (m/s) of ground speed
    dAdI = dalpha_dItot(op, p)                # share per A of I_tot

    A = np.zeros((n, n))
    B = np.zeros((n, 2))
    C = np.zeros((2, n))

    # --- share pre-path: x_s' = As x_s + Bs*dr
    A[iS, iS] = Sp.A
    B[iS, 0:1] = Sp.B

    # --- VESC current path: x_d' = Ad x_d + Bd*di_cmd ;  di_m = Cd x_d
    A[iD, iD] = Dv.A
    B[iD, 1:2] = Dv.B
    row_im = np.zeros(n); row_im[iD] = Dv.C[0]

    # --- vehicle mode: x_m' = Am x_m + Bm*(KF * di_m) ; dv_phys = Cm x_m
    A[iM, iM] = Mm.A
    A[iM, :] += Mm.B @ (KF*row_im.reshape(1, n))
    row_v = np.zeros(n); row_v[iM] = Mm.C[0]

    # --- velocity estimator: x_e' = Ae x_e + Be*dv_phys ; dv_meas = Ce x_e + De*dv_phys
    # ONLY the measured output goes through it.  The coupling row below deliberately uses
    # the UNDELAYED dv_phys: the bus-current draw responds to the real shaft speed, not to
    # what the firmware's estimator has got round to reporting.
    A[iE, iE] = Ev.A
    A[iE, :] += Ev.B @ row_v.reshape(1, n)
    row_vm = float(Ev.D[0, 0])*row_v.copy()
    row_vm[iE] = Ev.C[0]

    # --- bus current draw (the coupling source):  dI_bus = A_i*di_m + Aw_v*dv_phys
    row_Ibus = A_i*row_im + Aw_v*row_v

    # --- un-filtered share:  alpha_pre = Cs x_s + dAdI * dI_bus
    row_alpha_pre = np.zeros(n); row_alpha_pre[iS] = Sp.C[0]
    row_alpha_pre = row_alpha_pre + dAdI*row_Ibus

    # --- shared measurement prefilter (one instance, both paths through it)
    if nf:
        A[iF, :] += row_alpha_pre/tauf
        A[iF, iF] += -1.0/tauf
        C[0, iF] = 1.0
    else:
        C[0, :] = row_alpha_pre

    # --- speed output (estimator output x encoder chain gain x K_v gain uncertainty)
    C[1, :] = p['K_enc']*p['K_v']*row_vm

    # G21 == 0 structurally: dr (input 0) reaches no state that feeds C[1, :].
    return SS(A, B, C, np.zeros((2, 2)))


# ─────────────────────────────────────────────────────────────────────────────
# Scaling (plan §3): work on Gs = De^-1 G Du so the synthesis sees O(1) numbers
# ─────────────────────────────────────────────────────────────────────────────
DE = np.diag([0.05, 0.5])     # max acceptable [share error, speed error (m/s)]
DU = np.diag([0.35, 20.0])    # [dr span over r in [0.15,0.85] -> 0.7/2, motor A clamp]
# Motor-current span: +-20 A MOTOR-SIDE (firmware MOTOR_I_CMD_MAX, revised 2026-08-04).
# The previous +-5 A was a bench derating that applied the ~67-87 W BUS power budget
# directly at the MOTOR node; that is a unit error.  The bus/motor current conversion at
# the nominal OP is A_i ~ 0.24 A_bus per A_mot (plant_mimo's bus_current_gains), so
# 20 A motor-side draws ~4.9 A on the bus -- i.e. at the revised clamp the MOTOR clamp
# and the BUS power budget bind TOGETHER, by construction.  The bus-power limit itself is
# NOT modeled here (no bus-current constraint in the plant), so in-sim only the motor
# clamp is enforced; it is no longer conservative w.r.t. the bus, it is coincident with it.
# STALE vs FIRMWARE (2026-08-16): firmware MOTOR_I_CMD_MAX is now 12.0 A (2026-08-15
# operator decision).  DU[1,1] is deliberately LEFT at 20.0 because it is the scaling
# used by the checked-in MIMO synthesis artifacts, which this calibration round does not
# regenerate; changing it here would silently invalidate them.  The SISO drive synthesis
# does not use DU -- it enforces the clamp directly (synthesize_drive_siso.I_CLAMP =
# 12.0).  Re-align DU[1,1] when the MIMO controller is next re-synthesized.


def scaling_matrices():
    return DE.copy(), DU.copy()


def scaled_plant(G=None, De=None, Du=None, op=None, params=None):
    """Gs = De^-1 * G * Du.  Pass a plant, or let it build the design plant."""
    if G is None:
        G = design_plant(op, params)
    De = DE if De is None else np.asarray(De, float)
    Du = DU if Du is None else np.asarray(Du, float)
    return ss_lmul(np.linalg.inv(De), ss_rmul(G, Du))


# ─────────────────────────────────────────────────────────────────────────────
# Corner families (plan §1, "Corner family (two tiers)")
# ─────────────────────────────────────────────────────────────────────────────

def op_grid():
    """10 operating points: {0.5, 2, 5} A x {0.3, 0.5, 0.7} plus FC-charge-cruise.

    (2.0 A, r0 = 0.85) is the FC-charge cruise corner: the EMS commands the share
    to the r clamp so the fuel cell carries the bus and the battery charges.
    """
    nom = nominal_op()
    pts = [(it, r) for it in (0.5, 2.0, 5.0) for r in (0.3, 0.5, 0.7)]
    pts.append((2.0, 0.85))
    out = []
    for it, r in pts:
        o = dict(nom); o['I_tot0'] = it; o['r0'] = r
        out.append(o)
    return out


def share_corners():
    """24 share-channel parameter corners.

    dV0 is carried here (not in the OP) because it is an UNCERTAINTY axis, not an
    operating choice: a corner's dV0 OVERRIDES the OP's dV0 when the two are
    combined (see corner_plant()).  tau_r in {20, 300} us absorbs the MOT_PWR
    bus-capacitance change (30-80 uF -> 500-1000 uF).
    """
    out = []
    for dV0 in (-0.4, 0.0, 0.4):
        for Td in (0.5e-3, 2.0e-3):
            for taur in (20e-6, 300e-6):
                for tauf in (0.0, 0.8e-3):
                    out.append(dict(dV0=dV0, Td=Td, taur=taur, tauf=tauf))
    return out


def drive_corners():
    """24 drive-channel parameter corners.

    K_v {0.5, 1, 2} -> {0.85, 1.25, 1.85}, RE-CENTRED not merely re-scaled
    (2026-08-16b).  The axis is no longer a structural placeholder: the drive gain has
    now been MEASURED end to end, twice, and the two measurements disagree.
      * ML0136-0139 +12 A ramps  -> implied K_F 0.805 N/A = 1.78x modelled
      * 4.5 +- 0.4 A cruise hold -> implied K_F 0.409 N/A = 0.91x modelled
    The nominal is the geometric mean (K_V_NOM = 1.25) and the corners bracket both
    endpoints.  Net effect: the span NARROWS from 4.0x to 2.2x while the nominal moves
    onto the evidence -- so this is a robustness RELAXATION and a nominal correction at
    the same time, and the relaxation is what pays for the estimator delay added below.
    See mimo_system_model.md §4.2.

    pole_factor scales b_eff (hence the drive pole and the DC gain jointly).
    WIDENED {0.5, 2} -> {0.5, 3} (2026-08-16): b_eff is a slope identified LOCALLY
    at v0 = 2.0 m/s, and the measured curve's slope roughly doubles below 1.5 m/s,
    so the upper corner must cover the low-speed end of the operating range.

    NOTE: the estimator-delay axis Td_est(v0) over TD_EST_V0_SET is NOT in this list.
    It is a function of the OPERATING SPEED, not a parameter uncertainty, so it is swept
    by varying op['v0'] (see synthesize_drive_siso.py §6); listing it here would hide
    that it is deterministic given v0.
    """
    out = []
    for K_v in (0.85, K_V_NOM, 1.85):
        for pf in (0.5, 3.0):
            for tau_v in (0.5e-3, 5.0e-3):
                for Td_v in (1.0e-3, 4.0e-3):
                    out.append(dict(K_v=K_v, pole_factor=pf, tau_v=tau_v, Td_v=Td_v))
    return out


def corner_plant(op, share_c, drive_c, params=None):
    """Build the design plant at (OP, share corner, drive corner).

    The share corner's dV0 overrides the OP's dV0 (see share_corners docstring).
    """
    p = dict(nominal_params() if params is None else params)
    o = dict(op)
    sc = dict(share_c)
    if 'dV0' in sc:
        o['dV0'] = sc.pop('dV0')
    p.update(sc)
    p.update(drive_c)
    return design_plant(o, p), o, p


def tier1_corners(skip_infeasible=True):
    """Generator over the Tier-1 cross product (10 OP x 24 share x 24 drive = 5760).

    Yields (op, share_corner, drive_corner, feasible).  With skip_infeasible the
    clamped (op, dV0) combinations are still yielded but flagged False so the
    caller can count them; see op_feasible().
    """
    p0 = nominal_params()
    for op in op_grid():
        for sc in share_corners():
            o = dict(op)
            if 'dV0' in sc:
                o = dict(op, dV0=sc['dV0'])
            feas = op_feasible(o, p0)
            for dc in drive_corners():
                yield op, sc, dc, feas


if __name__ == "__main__":
    op, p = nominal_op(), nominal_params()
    G = design_plant(op, p)
    A_i, A_w, i_m0, w0 = bus_current_gains(op, p)
    print(f"design plant: {G.n} states, {G.ny}x{G.nu}")
    print(f"  V_bus0     = {V_BUS0:.4f} V     Re_max = {RE_MAX:.4f} ohm")
    print(f"  K (share)  = {share_gain_K(op, p):.6f}")
    print(f"  b_eff      = {b_eff(op, p):.5f} N*s/m   (MEASURED local slope at "
          f"v0 = {op['v0']} m/s; F_c = {p['F_c']:.2f} N)")
    print(f"  k_t        = {K_T:.6e} N*m/A   force/amp = {force_per_amp(p):.5f} N/A")
    print(f"  i_m0       = {i_m0:.4f} A      omega0 = {w0:.1f} rad/s")
    print(f"             (measured cruise hold 4.5 +- 0.4 A: model is ~9 % low, just "
          f"below the band -- eta_dt placeholder)")
    print(f"  K_v        = {p['K_v']:.3f} (nominal, evidence-centred)   "
          f"G22(0) = {drive_plant(op, p).dcgain():.4f} (m/s)/A")
    print(f"  estimator  : pitch = {PITCH_M*1e3:.4f} mm, N = {p['N_est']}, "
          f"Td_est(v0={op['v0']}) = {op_td_est(op, p)*1e3:.3f} ms")
    print("               Td_est corners: " + ", ".join(
        f"{v} m/s -> {td_est(v)*1e3:.2f} ms" for v in TD_EST_V0_SET)
        + f"   (validity floor {V0_VALID_MIN} m/s)")
    print(f"  A_i        = {A_i:.6f} A/A    A_w = {A_w:.6e} A/(rad/s)")
    print(f"  dalpha/dI  = {dalpha_dItot(op, p):.6e} share/A")
    print(f"  DC gain:\n{G.dcgain_matrix()}")
    print(f"  poles: {np.sort_complex(G.poles())}")
