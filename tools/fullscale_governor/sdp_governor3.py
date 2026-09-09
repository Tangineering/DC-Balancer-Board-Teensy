#!/usr/bin/env python3
"""sdp_governor3.py - Python port of references/EMS/SDP_EnergyManagement_Governor3.m.

Stochastic-DP energy management for the FULL-SCALE fuel-cell hybrid (106 kW
stack, 78 kW / 720 V / 100 Ah pack) with the bench power-share governor scaled
UP into the forward simulation.  The SDP policy is governor-unaware; the
forward loop treats its P_fc output as a request, converts it to a share
setpoint sp = |I_fc| / (|I_fc| + |I_bat|), ticks the governor `n_subticks`
times per SDP sample and converts the applied ratio back to a power split.
SoC propagates from the ACHIEVED battery power.

Port discipline
---------------
* Line-for-line semantics against the MATLAB (section markers below name the
  MATLAB function they mirror).  Nothing numeric is re-derived; the defaults in
  `fill_defaults()` are the MATLAB `fill_defaults` verbatim.
* Nearest-grid snapping (`use_interp = False`) is kept as the default because
  the student's tables were produced with it.  Ties in `min(abs(...))` resolve
  to the LOWEST index in MATLAB; `np.argmin` does the same.
* Value iteration is vectorised over (SoC, u) per demand bin; the arithmetic
  is identical, only the loop order differs.  The forward simulation's governor
  tick is scalar Python, as in the MATLAB, so the two implementations can be
  compared tick by tick.
* Validation: tools/fullscale_governor/compare_with_matlab.py checks this port
  against the MATLAB run on the same P_dem vector (see the README).

The governor model here is the STUDENT'S transcription of the fw v25 governor
spec (setpoint latch, min-load gate, ALPHA filter, conduction-aware slew,
minority clip, PI share-controller stub).  It is NOT tools/governor_model.py
(the firmware port); the two differ, and that difference is part of what the
sub-project is measuring.  Do not "fix" this file toward the firmware port
without recording the change in the README.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# ------------------------------------------------------------------------
# 1. VEHICLE / SDP PARAMETERS (MATLAB section 1)
# ------------------------------------------------------------------------
P_FC_MAX = 106000.0      # W
P_BATT_MAX = 78000.0     # W, discharging
P_BATT_MIN = -78000.0    # W, charging
Q_AH = 100.0             # Ah
EM_V = 720.0             # V, battery OCV
Q_LHV_H2 = 120000.0      # J/g
ETA_FC_CONST = 0.5       # only for h2_model = 'constant'
SOC_REF = 0.6
K_SOC = 1.0 / (EM_V * 3600.0 * Q_AH)
BIG = 1e6
PDEM_BIN_LO, PDEM_BIN_HI = -50000.0, 60000.0
EPS = np.finfo(float).eps


def fill_defaults(cfg: Optional[dict]) -> dict:
    """MATLAB fill_defaults(), verbatim defaults."""
    V_bus = 720.0
    P_tot = 184000.0
    I_tot = P_tot / V_bus
    d = dict(
        Ts=1.0, gamma=0.95, alpha=500.0, n_SOC=250, SOC_min=0.55, SOC_max=0.65,
        SOC_hard_min=0.40, SOC_hard_max=0.80, n_u=50, max_iterations=1000,
        tolerance=1e-3, use_interp=False, policy_cache=None,
        governor_enabled=True, n_subticks=880, V_bus_nominal=V_bus,
        P_tot_nominal_W=P_tot, I_tot_nominal_A=I_tot, I_bench_nominal_A=2.0,
        S_I=None,
        P_fc_ramp_W_per_s=50000.0, slew_handoff_ratio=10.0, dwell_allowance_s=0.200,
        fcRegEnable=True, btRegEnable=True,
        h2_model="convex", h2_a0=0.05, h2_P_peak_W=35000.0, h2_eta_peak=0.50,
        h2_coeffs=None, h2_shutdown_at_zero=True, h2_start_cost_g=0.5,
        h2_s_eq_fixed=None,
        Kp_share=0.30, Ki_share=50.0, verbose=True,
        # EXPERIMENT KNOB (not in the MATLAB): clip the share setpoint handed to the
        # governor into [lo, hi] before the tick, e.g. (0.15, 0.85).  None = MATLAB
        # behaviour (out-of-band setpoints reach the setpoint latch).
        sp_preclip=None,
    )
    out = dict(d)
    for k, v in (cfg or {}).items():
        if v is not None:
            out[k] = v
    if out["S_I"] is None:
        out["S_I"] = out["I_tot_nominal_A"] / out["I_bench_nominal_A"]
    return out


# ------------------------------------------------------------------------
# HYDROGEN RATE MAP (MATLAB h2_coefficients / h2_rate)
# ------------------------------------------------------------------------
@dataclass
class H2Map:
    model: str
    a: np.ndarray          # [a0 a1 a2], g/s per W^n
    shutdown: bool
    LHV: float = Q_LHV_H2


def h2_coefficients(cfg: dict) -> H2Map:
    model = cfg["h2_model"].lower()
    if model == "constant":
        return H2Map(model, np.array([0.0, 1.0 / (ETA_FC_CONST * Q_LHV_H2), 0.0]), False)
    if model == "convex":
        if cfg["h2_coeffs"] is not None:
            a = np.asarray(cfg["h2_coeffs"], dtype=float).ravel()
            if a.size != 3:
                raise ValueError("cfg.h2_coeffs must be [a0 a1 a2].")
        else:
            a0, Pp, ep = cfg["h2_a0"], cfg["h2_P_peak_W"], cfg["h2_eta_peak"]
            a2 = a0 / Pp ** 2
            a1 = (Pp / (ep * Q_LHV_H2) - 2 * a0) / Pp
            if a1 <= 0:
                raise ValueError("h2 map: a1 <= 0")
            a = np.array([a0, a1, a2])
        return H2Map(model, a, bool(cfg["h2_shutdown_at_zero"]))
    raise ValueError("cfg.h2_model must be 'convex' or 'constant'.")


def h2_rate(P_fc, h2: H2Map):
    """Hydrogen rate [g/s]; vectorised; zero at P_fc <= 0 when shutdown."""
    P = np.maximum(np.asarray(P_fc, dtype=float), 0.0)
    W = h2.a[0] + h2.a[1] * P + h2.a[2] * P ** 2
    if h2.shutdown:
        W = np.where(P <= 0, 0.0, W)
    return W


# ------------------------------------------------------------------------
# 2. VALUE ITERATION + policy extraction (MATLAB section 2 / 2b)
# ------------------------------------------------------------------------
def _nearest_idx(grid: np.ndarray, x):
    """MATLAB [~, i] = min(abs(grid - x)) - first index on ties."""
    return np.argmin(np.abs(grid[None, :] - np.asarray(x)[..., None]), axis=-1)


def _stage_tables(SOC_grid, Pdemand_bins, u_grid, h2, alpha, Ts, c_start):
    """Everything in the inner loop that does not depend on J.

    Returns (feasible[i,pd,u], ns[i,pd,u], stage[i,pd,u,onPrev]) with stage
    cost = W_H2*Ts + alpha*|SOC_next - SOC_ref| + c_start*(onNext & ~onPrev).
    """
    nSOC, nPd, nU = len(SOC_grid), len(Pdemand_bins), len(u_grid)
    P_batt = Pdemand_bins[:, None] - u_grid[None, :]                    # [pd,u]
    feas_pu = (P_batt <= P_BATT_MAX) & (P_batt >= P_BATT_MIN)
    SOC_next = SOC_grid[:, None, None] - P_batt[None, :, :] * Ts * K_SOC  # [i,pd,u]
    feas = feas_pu[None, :, :] & (SOC_next >= SOC_grid[0]) & (SOC_next <= SOC_grid[-1])
    ns = _nearest_idx(SOC_grid, SOC_next)                                  # [i,pd,u]
    W = h2_rate(u_grid, h2) * Ts                                          # [u]
    onNext = u_grid > 0                                                   # [u]
    soc_pen = alpha * np.abs(SOC_next - SOC_REF)                          # [i,pd,u]
    stage = np.empty((nSOC, nPd, nU, 2))
    for onPrev in (0, 1):
        start_pen = c_start * (onNext & (onPrev == 0))
        stage[..., onPrev] = W[None, None, :] + soc_pen + start_pen[None, None, :]
    return feas, ns, onNext.astype(int), stage, SOC_next


def value_iteration(SOC_grid, Pdemand_bins, u_grid, TPM, h2, alpha, gamma, Ts,
                    c_start, max_iterations, tolerance, use_interp=False, verbose=False):
    nSOC, nPd, nU = len(SOC_grid), len(Pdemand_bins), len(u_grid)
    feas, ns, m_next, stage, SOC_next = _stage_tables(SOC_grid, Pdemand_bins, u_grid, h2, alpha, Ts, c_start)
    J = np.zeros((nSOC, nPd, 2))
    pd_idx = np.arange(nPd)[None, :, None]
    m_idx = m_next[None, None, :]
    iteration = 0
    delta = np.nan
    for iteration in range(1, max_iterations + 1):
        J_exp = np.einsum("spm,qp->sqm", J, TPM)          # J_exp(s,pd,m) = sum_next TPM(pd,next) J(s,next,m)
        if use_interp:
            fut = np.empty((nSOC, nPd, nU))
            for pd in range(nPd):
                for m in (0, 1):
                    sel = m_next == m
                    fut[:, pd, sel] = np.interp(SOC_next[:, pd, sel], SOC_grid, J_exp[:, pd, m])
        else:
            fut = J_exp[ns, pd_idx, m_idx]                # [i,pd,u]
        J_new = np.empty_like(J)
        for onPrev in (0, 1):
            total = stage[..., onPrev] + gamma * fut
            total = np.where(feas, total, np.inf)
            mn = total.min(axis=2)
            J_new[..., onPrev] = np.where(np.isfinite(mn), np.minimum(mn, BIG), BIG)
        delta = np.max(np.abs(J_new - J))
        J = J_new
        if delta < tolerance:
            break
    if verbose:
        print("Value iteration: %d sweeps, final delta = %.3e (start cost %.3g g)" % (iteration, delta, c_start))
    # 2b. greedy policy on the converged J
    J_exp = np.einsum("spm,qp->sqm", J, TPM)
    if use_interp:
        fut = np.empty((nSOC, nPd, nU))
        for pd in range(nPd):
            for m in (0, 1):
                sel = m_next == m
                fut[:, pd, sel] = np.interp(SOC_next[:, pd, sel], SOC_grid, J_exp[:, pd, m])
    else:
        fut = J_exp[ns, pd_idx, m_idx]
    U_star = np.zeros((nSOC, nPd, 2))
    for onPrev in (0, 1):
        total = np.where(feas, stage[..., onPrev] + gamma * fut, np.inf)
        best = total.argmin(axis=2)                       # first index on ties, like MATLAB '<'
        allinf = ~np.isfinite(total.min(axis=2))
        U_star[..., onPrev] = np.where(allinf, 0.0, u_grid[best])
    return J, U_star, iteration, delta


# ------------------------------------------------------------------------
# GOVERNOR CONSTANTS / STATE (MATLAB governor_constants, governor_init_state)
# ------------------------------------------------------------------------
@dataclass
class GovConst:
    TICK_S: float
    R_MIN: float = 0.15
    R_MAX: float = 0.85
    ALPHA: float = 0.05
    CUTOFF_HYST: float = 0.01
    SP_CHANGE_EPS: float = 1e-4
    MOTION_EPS: float = 1e-6
    I_TOT_MIN_A: float = 0.0
    MINORITY_I_MIN_A: float = 0.0
    OL_HYST_A: float = 0.0
    HANDOFF_MIN_A: float = 0.0
    HANDOFF_LIVE_A: float = 0.0
    CUT_MAX_HANDOFF_A: float = 0.0
    SLEW_PER_TICK: float = 0.0
    SLEW_HANDOFF: float = 0.0
    DWELL_MAX_TICKS: int = 0
    V_BUS_CHARGED: float = 0.0
    K_DROOP: float = 0.30
    RE_MAX: float = 2.014
    MDAC_RES: int = 4095
    Kp: float = 0.30
    Ki: float = 50.0


def governor_constants(cfg: dict) -> GovConst:
    C = GovConst(TICK_S=cfg["Ts"] / cfg["n_subticks"])
    S = cfg["S_I"]
    C.I_TOT_MIN_A = 0.075 * S
    C.MINORITY_I_MIN_A = 0.30 * S
    C.OL_HYST_A = 0.05 * S
    C.HANDOFF_MIN_A = 0.15 * S
    C.HANDOFF_LIVE_A = 0.20 * S
    C.CUT_MAX_HANDOFF_A = 0.5 * S
    C.SLEW_PER_TICK = (cfg["P_fc_ramp_W_per_s"] / cfg["P_tot_nominal_W"]) * C.TICK_S
    C.SLEW_HANDOFF = C.SLEW_PER_TICK / cfg["slew_handoff_ratio"]
    C.DWELL_MAX_TICKS = int(round(cfg["dwell_allowance_s"] / C.TICK_S))
    C.V_BUS_CHARGED = cfg["V_bus_nominal"] - 2.5
    C.Kp = cfg["Kp_share"]
    C.Ki = cfg["Ki_share"]
    return C


@dataclass
class GovState:
    govTotAFilt: float = 0.0
    droopSlewPrev: float = 0.5
    closedLoopMode: bool = False
    closedLoopRun: bool = False
    actedSp: float = 0.5
    spEffPrev: float = 0.5
    spCutFC: bool = False
    spCutBT: bool = False
    isoFC: bool = False
    isoBT: bool = False
    cutDeferredFC: bool = False
    cutDeferredBT: bool = False
    iFcFilt: float = 0.0
    iBtFilt: float = 0.0
    darkFC: bool = True
    darkBT: bool = True
    dwell: int = 0
    handoffPrevRatio: float = 0.5
    step: float = 0.0
    swFC: bool = True
    swBT: bool = True
    ctrlI: float = 0.5
    gFC: float = 0.0
    gBT: float = 0.0
    codeFC: int = 0
    codeBT: int = 0


def governor_init_state(C: GovConst) -> GovState:
    st = GovState()
    st.step = C.SLEW_HANDOFF
    st.gFC = C.K_DROOP / (C.RE_MAX * 0.5)
    st.gBT = C.K_DROOP / (C.RE_MAX * 0.5)
    return st


def reset_share_control_state(st: GovState, sp: float, C: GovConst) -> None:
    st.govTotAFilt = 0.0
    st.closedLoopMode = False
    st.closedLoopRun = False
    st.actedSp = sp
    st.spEffPrev = 0.5
    st.cutDeferredFC = False
    st.cutDeferredBT = False
    st.iFcFilt = 0.0
    st.iBtFilt = 0.0
    st.darkFC = True
    st.darkBT = True
    st.dwell = 0
    st.handoffPrevRatio = st.droopSlewPrev
    st.step = C.SLEW_HANDOFF
    st.ctrlI = st.droopSlewPrev


def _clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


# ------------------------------------------------------------------------
# ONE GOVERNOR TICK (MATLAB governor_tick and helpers)
# ------------------------------------------------------------------------
def update_setpoint_cutoff(st: GovState, sp, I_fc, I_batt, V_bus, fcRegEn, btRegEn, C: GovConst) -> bool:
    frozen = False
    justReleased = False
    # self-heal
    if st.spCutFC and st.swFC:
        st.spCutFC = False
        reset_share_control_state(st, sp, C)
        justReleased = True
    if st.spCutBT and st.swBT:
        st.spCutBT = False
        reset_share_control_state(st, sp, C)
        justReleased = True
    if st.isoFC and not st.spCutFC and st.swFC:
        st.isoFC = False
    if st.isoBT and not st.spCutBT and st.swBT:
        st.isoBT = False
    # release
    if st.spCutFC and sp >= C.R_MIN and V_bus >= C.V_BUS_CHARGED and fcRegEn:
        st.swFC = True
        st.spCutFC = False
        st.isoFC = False
        reset_share_control_state(st, sp, C)
        justReleased = True
    if st.spCutBT and sp <= C.R_MAX and V_bus >= C.V_BUS_CHARGED and btRegEn:
        st.swBT = True
        st.spCutBT = False
        st.isoBT = False
        reset_share_control_state(st, sp, C)
        justReleased = True
    st.cutDeferredFC = False
    st.cutDeferredBT = False
    # entry
    if not justReleased and not st.spCutFC and not st.spCutBT:
        bothClosed = st.swFC and st.swBT
        if sp < C.R_MIN:
            if bothClosed and abs(I_fc) <= C.CUT_MAX_HANDOFF_A:
                st.swFC = False
                st.spCutFC = True
                return True
            elif bothClosed:
                st.cutDeferredFC = True
        elif sp > C.R_MAX:
            if bothClosed and abs(I_batt) <= C.CUT_MAX_HANDOFF_A:
                st.swBT = False
                st.spCutBT = True
                return True
            elif bothClosed:
                st.cutDeferredBT = True
    if st.spCutFC or st.spCutBT:
        frozen = True
    return frozen


def _hyst_dark(dark, iFilt, minA, liveA):
    if dark:
        if iFilt >= liveA:
            dark = False
    else:
        if iFilt < minA:
            dark = True
    return dark


def update_share_slew_mode(st: GovState, I_fc, I_batt, C: GovConst) -> None:
    moved = abs(st.droopSlewPrev - st.handoffPrevRatio) > C.MOTION_EPS
    st.handoffPrevRatio = st.droopSlewPrev
    st.iFcFilt += C.ALPHA * (abs(I_fc) - st.iFcFilt)
    st.iBtFilt += C.ALPHA * (abs(I_batt) - st.iBtFilt)
    st.darkFC = _hyst_dark(st.darkFC, st.iFcFilt, C.HANDOFF_MIN_A, C.HANDOFF_LIVE_A)
    st.darkBT = _hyst_dark(st.darkBT, st.iBtFilt, C.HANDOFF_MIN_A, C.HANDOFF_LIVE_A)
    if not (st.darkFC or st.darkBT):
        st.dwell = 0
        st.step = C.SLEW_PER_TICK
    elif st.dwell >= C.DWELL_MAX_TICKS:
        st.step = C.SLEW_PER_TICK
    else:
        if moved:
            st.dwell += 1
        st.step = C.SLEW_HANDOFF


def share_controller(st: GovState, sp_eff, share_meas, C: GovConst) -> float:
    e = sp_eff - share_meas
    st.ctrlI = _clamp(st.ctrlI + C.Ki * C.TICK_S * e, 0.0, 1.0)
    return _clamp(st.ctrlI + C.Kp * e, 0.0, 1.0)


def apply_share_ratio(st: GovState, r, V_bus, fcRegEn, btRegEn, C: GovConst) -> None:
    r = _clamp(r, 0.0, 1.0)
    if r < C.R_MIN and not st.cutDeferredFC:
        if st.swFC and st.swBT:
            st.swFC = False
            st.isoFC = True
    elif r > C.R_MAX and not st.cutDeferredBT:
        if st.swFC and st.swBT:
            st.swBT = False
            st.isoBT = True
    if st.isoFC and not st.spCutFC and r >= C.R_MIN + C.CUTOFF_HYST and V_bus >= C.V_BUS_CHARGED and fcRegEn:
        st.swFC = True
        st.isoFC = False
    if st.isoBT and not st.spCutBT and r <= C.R_MAX - C.CUTOFF_HYST and V_bus >= C.V_BUS_CHARGED and btRegEn:
        st.swBT = True
        st.isoBT = False
    if st.isoFC or st.isoBT:
        return
    rc = _clamp(r, C.R_MIN, C.R_MAX)
    st.droopSlewPrev = rc
    g_FC = C.K_DROOP / (C.RE_MAX * rc)
    g_BT = C.K_DROOP / (C.RE_MAX * (1.0 - rc))
    st.gFC = g_FC
    st.gBT = g_BT
    st.codeFC = int(math.floor(_clamp(g_FC, 0.0, 1.0) * C.MDAC_RES))
    st.codeBT = int(math.floor(_clamp(g_BT, 0.0, 1.0) * C.MDAC_RES))


def governor_tick(st: GovState, sp, I_fc, I_batt, V_bus, fcRegEn, btRegEn, C: GovConst) -> float:
    """One governor tick; returns r_applied.  Mirrors MATLAB governor_tick()."""
    frozen = update_setpoint_cutoff(st, sp, I_fc, I_batt, V_bus, fcRegEn, btRegEn, C)
    if frozen:
        return st.droopSlewPrev
    I_tot = abs(I_fc) + abs(I_batt)
    if I_tot < C.I_TOT_MIN_A:
        return st.droopSlewPrev
    st.govTotAFilt += C.ALPHA * (I_tot - st.govTotAFilt)
    update_share_slew_mode(st, I_fc, I_batt, C)
    step = st.step
    if (not st.closedLoopMode) and st.govTotAFilt > 2 * C.MINORITY_I_MIN_A:
        st.closedLoopMode = True
        st.ctrlI = st.droopSlewPrev
    elif st.closedLoopMode and st.govTotAFilt < 2 * C.MINORITY_I_MIN_A - C.OL_HYST_A:
        st.closedLoopMode = False
    if not st.closedLoopMode:
        spChanged = abs(sp - st.actedSp) > C.SP_CHANGE_EPS
        if st.closedLoopRun and not spChanged and not (st.isoFC or st.isoBT):
            return st.droopSlewPrev
        if spChanged:
            st.closedLoopRun = False
        if sp < C.R_MIN or sp > C.R_MAX:
            return st.droopSlewPrev
        r = _clamp(sp, st.droopSlewPrev - step, st.droopSlewPrev + step)
        apply_share_ratio(st, r, V_bus, fcRegEn, btRegEn, C)
        st.actedSp = sp
        return st.droopSlewPrev
    # closed loop
    st.closedLoopRun = True
    st.actedSp = sp
    sp_eff_target = sp
    if st.cutDeferredFC or st.cutDeferredBT:
        sp_eff_target = _clamp(sp_eff_target, C.R_MIN, C.R_MAX)
    if C.R_MIN <= sp_eff_target <= C.R_MAX:
        lo = C.MINORITY_I_MIN_A / st.govTotAFilt
        if lo > 0.5:
            lo = 0.5
        sp_eff_target = _clamp(sp_eff_target, lo, 1.0 - lo)
    st.spEffPrev = _clamp(sp_eff_target, st.spEffPrev - step, st.spEffPrev + step)
    sp_eff = st.spEffPrev
    share_meas = abs(I_fc) / I_tot
    r = share_controller(st, sp_eff, share_meas, C)
    if C.R_MIN <= r <= C.R_MAX:
        r = _clamp(r, st.droopSlewPrev - step, st.droopSlewPrev + step)
    apply_share_ratio(st, r, V_bus, fcRegEn, btRegEn, C)
    return st.droopSlewPrev


# ------------------------------------------------------------------------
# SHARE RATIO <-> POWER SPLIT
# ------------------------------------------------------------------------
def share_from_split(P_fc, P_bat) -> float:
    den = abs(P_fc) + abs(P_bat)
    return 0.5 if den < EPS else abs(P_fc) / den


def ratio_to_split(r, P_dem, chargeBranch, swFC, swBT):
    hit = False
    if not swFC:
        P_fc = 0.0
    elif not swBT:
        P_fc = P_dem
    else:
        if P_dem >= 0 and not chargeBranch:
            P_fc = r * P_dem
        else:
            den = 2 * r - 1
            P_fc = P_FC_MAX if abs(den) < 1e-9 else r * P_dem / den
    if P_fc < 0:
        P_fc = 0.0
        hit = True
    if P_fc > P_FC_MAX:
        P_fc = P_FC_MAX
        hit = True
    P_bat = P_dem - P_fc
    if P_bat > P_BATT_MAX:
        P_bat = P_BATT_MAX
        P_fc = P_dem - P_bat
        hit = True
    elif P_bat < P_BATT_MIN:
        P_bat = P_BATT_MIN
        P_fc = P_dem - P_bat
        hit = True
    if P_fc < 0:
        P_fc = 0.0
        P_bat = P_dem
        hit = True
    elif P_fc > P_FC_MAX:
        P_fc = P_FC_MAX
        P_bat = P_dem - P_fc
        hit = True
    return P_fc, P_bat, hit


# ------------------------------------------------------------------------
# MAIN: SDP_EnergyManagement_Governor3
# ------------------------------------------------------------------------
@dataclass
class GovResult:
    P_fc_cmd: np.ndarray
    P_fc_applied: np.ndarray
    P_batt_applied: np.ndarray
    SOC: np.ndarray
    sp_cmd: np.ndarray
    r_applied: np.ndarray
    closedLoop: np.ndarray
    latchFC: np.ndarray
    latchBT: np.ndarray
    isoFC: np.ndarray
    isoBT: np.ndarray
    saturated: np.ndarray
    stackOn: np.ndarray
    n_starts: int
    n_latch_events: int
    M_H2_applied: np.ndarray
    M_H2_cmd: np.ndarray
    s_eq: float
    h2: H2Map
    C: GovConst
    cfg: dict
    policy_cache: dict
    vi_sweeps: int
    summary: dict = field(default_factory=dict)


def sdp_governor3(P_dem_array, SOC_initial, TPM, cfg=None) -> GovResult:
    cfg = fill_defaults(cfg)
    P_dem_array = np.asarray(P_dem_array, dtype=float).ravel()
    TPM = np.asarray(TPM, dtype=float)
    N = len(P_dem_array)
    SOC_grid = np.linspace(cfg["SOC_min"], cfg["SOC_max"], cfg["n_SOC"])
    alpha, gamma, Ts = float(cfg["alpha"]), float(cfg["gamma"]), float(cfg["Ts"])
    h2 = h2_coefficients(cfg)
    Pdemand_bins = np.linspace(PDEM_BIN_LO, PDEM_BIN_HI, TPM.shape[0])
    u_grid = np.linspace(0.0, P_FC_MAX, cfg["n_u"])
    c_start = float(cfg["h2_start_cost_g"])

    policy_sig = dict(alpha=alpha, gamma=gamma, Ts=Ts, n_SOC=len(SOC_grid), SOC_lo=SOC_grid[0],
                      SOC_hi=SOC_grid[-1], n_u=len(u_grid), use_interp=bool(cfg["use_interp"]),
                      tolerance=cfg["tolerance"], h2_a=tuple(h2.a.tolist()), h2_shutdown=h2.shutdown,
                      c_start=c_start, nPd=len(Pdemand_bins), TPM_sum=float(TPM.sum()),
                      TPM_trace=float(np.trace(TPM)))
    cache = cfg["policy_cache"]
    if cache is not None and cache.get("sig") == policy_sig:
        J, U_star, sweeps = cache["J"], cache["U_star"], cache.get("sweeps", -1)
    else:
        J, U_star, sweeps, _ = value_iteration(SOC_grid, Pdemand_bins, u_grid, TPM, h2, alpha, gamma, Ts,
                                               c_start, cfg["max_iterations"], cfg["tolerance"],
                                               cfg["use_interp"], cfg["verbose"])
    policy_cache = dict(sig=policy_sig, J=J, U_star=U_star, sweeps=sweeps)

    # 3. forward simulation
    C = governor_constants(cfg)
    st = governor_init_state(C)
    n_sub = int(cfg["n_subticks"])
    dt_sub = Ts / n_sub
    V_bus = float(cfg["V_bus_nominal"])
    fcEn, btEn = bool(cfg["fcRegEnable"]), bool(cfg["btRegEnable"])

    SOC_out = np.zeros(N + 1)
    P_fc_applied = np.zeros(N)
    P_batt_applied = np.zeros(N)
    P_fc_cmd_log = np.zeros(N)
    sp_cmd_log = np.zeros(N)
    r_app_log = np.zeros(N)
    mode_log = np.zeros(N, bool)
    latchFC_log = np.zeros(N, bool)
    latchBT_log = np.zeros(N, bool)
    isoFC_log = np.zeros(N, bool)
    isoBT_log = np.zeros(N, bool)
    sat_log = np.zeros(N, bool)
    stackOn_log = np.zeros(N, bool)
    SOC_out[0] = SOC_initial
    P_fc_now = 0.0
    P_bat_now = 0.0
    stackOnPrev = False
    governed = bool(cfg["governor_enabled"])

    for k in range(N):
        SOC_current = SOC_out[k]
        P_dem = P_dem_array[k]
        soc_idx = int(np.argmin(np.abs(SOC_grid - SOC_current)))
        pd_idx = int(np.argmin(np.abs(Pdemand_bins - P_dem)))
        P_fc_cmd = U_star[soc_idx, pd_idx, int(stackOnPrev)]
        P_fc_cmd = min(max(P_fc_cmd, 0.0), P_FC_MAX)
        P_bat_cmd = P_dem - P_fc_cmd
        if P_bat_cmd > P_BATT_MAX:
            P_fc_cmd = P_dem - P_BATT_MAX
        elif P_bat_cmd < P_BATT_MIN:
            P_fc_cmd = P_dem - P_BATT_MIN
        P_fc_cmd = min(max(P_fc_cmd, 0.0), P_FC_MAX)
        P_bat_cmd = P_dem - P_fc_cmd

        if not governed:
            P_fc_applied[k] = P_fc_cmd
            P_batt_applied[k] = P_bat_cmd
            P_fc_cmd_log[k] = P_fc_cmd
            sp_cmd_log[k] = share_from_split(P_fc_cmd, P_bat_cmd)
            r_app_log[k] = sp_cmd_log[k]
            SOC_out[k + 1] = SOC_current - P_batt_applied[k] * Ts * K_SOC
            stackOnPrev = P_fc_applied[k] > 0
            stackOn_log[k] = stackOnPrev
            continue

        sp_cmd = share_from_split(P_fc_cmd, P_bat_cmd)
        if cfg["sp_preclip"] is not None:
            sp_cmd = _clamp(sp_cmd, cfg["sp_preclip"][0], cfg["sp_preclip"][1])
        chargeBranch = P_bat_cmd < 0
        E_fc = 0.0
        E_bat = 0.0
        sat_hit = False
        for _ in range(n_sub):
            r_app = governor_tick(st, sp_cmd, P_fc_now / V_bus, P_bat_now / V_bus, V_bus, fcEn, btEn, C)
            P_fc_now, P_bat_now, hit = ratio_to_split(r_app, P_dem, chargeBranch, st.swFC, st.swBT)
            sat_hit = sat_hit or hit
            E_fc += P_fc_now * dt_sub
            E_bat += P_bat_now * dt_sub
        P_fc_applied[k] = E_fc / Ts
        P_batt_applied[k] = E_bat / Ts
        SOC_next = SOC_current - P_batt_applied[k] * Ts * K_SOC
        SOC_out[k + 1] = min(max(SOC_next, cfg["SOC_hard_min"]), cfg["SOC_hard_max"])

        P_fc_cmd_log[k] = P_fc_cmd
        sp_cmd_log[k] = sp_cmd
        r_app_log[k] = st.droopSlewPrev
        mode_log[k] = st.closedLoopMode
        latchFC_log[k] = st.spCutFC
        latchBT_log[k] = st.spCutBT
        isoFC_log[k] = st.isoFC
        isoBT_log[k] = st.isoBT
        sat_log[k] = sat_hit
        stackOnPrev = P_fc_applied[k] > 0
        stackOn_log[k] = stackOnPrev

    # 4. outputs
    n_starts = int(np.sum(np.diff(np.r_[False, stackOn_log].astype(int)) == 1))
    latched = latchFC_log | latchBT_log
    n_latch_events = int(np.sum(np.diff(np.r_[False, latched].astype(int)) == 1))
    W_app = h2_rate(P_fc_applied, h2)
    W_cmd = h2_rate(P_fc_cmd_log, h2)
    M_app = np.cumsum(W_app) * Ts
    M_cmd = np.cumsum(W_cmd) * Ts
    s_eq = (1.0 / (cfg["h2_eta_peak"] * Q_LHV_H2)) if cfg["h2_s_eq_fixed"] is None else float(cfg["h2_s_eq_fixed"])
    dP = P_fc_applied - P_fc_cmd_log
    summary = dict(
        SOC_final=float(SOC_out[-1]),
        SOC_rms_dev=float(np.sqrt(np.mean((SOC_out[1:] - SOC_REF) ** 2))),
        M_H2_total=float(M_app[-1]),
        M_H2_total_cmd=float(M_cmd[-1]),
        frac_closed_loop=float(mode_log.mean()),
        frac_latched=float(latched.mean()),
        frac_isolated=float((isoFC_log | isoBT_log).mean()),
        frac_saturated=float(sat_log.mean()),
        mean_abs_dP_fc=float(np.mean(np.abs(dP))),
        n_starts=n_starts,
        n_latch_events=n_latch_events,
        M_H2_starts=c_start * n_starts,
    )
    return GovResult(P_fc_cmd_log, P_fc_applied, P_batt_applied, SOC_out, sp_cmd_log, r_app_log,
                     mode_log, latchFC_log, latchBT_log, isoFC_log, isoBT_log, sat_log, stackOn_log,
                     n_starts, n_latch_events, M_app, M_cmd, s_eq, h2, C, cfg, policy_cache, sweeps, summary)


def mh2_eq(res: GovResult, SOC_initial: float) -> float:
    """The student's charge-sustaining correction: M_H2 + E_bat_drawn * s_eq."""
    Eb = -(res.SOC[-1] - SOC_initial) * EM_V * 3600.0 * Q_AH
    return res.summary["M_H2_total"] + Eb * res.s_eq
