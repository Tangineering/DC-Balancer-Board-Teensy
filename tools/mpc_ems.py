"""mpc_ems.py - governor-aware model-predictive energy management.

WHAT THIS IS
------------
A receding-horizon energy-management strategy for the DC balancer rig, built to
the adjudicated design in ``docs/modeling/mpc_design_20260901/adjudication.md``
and documented in ``docs/modeling/mpc_design_20260901.md``.  It commands the two
energy fields of the 22-byte Pi command packet - ``power_share_setpoint`` and
``charge_goal`` - and nothing else, so no firmware, wire or artifact change is
implied by it.

Two variants are provided.  ``mpc-det`` reads the scenario's own speed profile
as an exact demand PREVIEW; ``mpc-sto`` replaces that preview with the demand
transition-probability matrix's conditional mean and tightens the fuel-cell
overcurrent bound to the 90 % quantile of the k-step distribution.

⚠️ ``mpc-det`` IS A PREVIEW STRATEGY, NOT A CAUSAL ONE.  It reads the future
   demand exactly, which no supervisor on the vehicle can do without route
   preview.  Its result against a causal law measures the value of preview plus
   the value of the horizon, and the two are not separable by these runs
   (adjudication section 1; candidate_opus section 1.3).

⚠️ SIM-ONLY.  Like ``soc-band`` and ``sdp-v3``, the state is the pack state of
   charge read from ``fb["soc"]``, which is PLANT TRUTH and not
   telemetry-equivalent.  A port to a real Pi needs the same battery-voltage
   state-of-charge estimator those two need.

STDLIB ONLY on the decision path.  ``hil_plant_sim`` is imported lazily for its
constants and its scenario registry; ``gen_dp_ems_table`` (which needs numpy) is
NEVER imported here.  The demand, mask and pack models are scalar ports of that
module's functions, and ``tools/test_mpc_ems.py`` asserts their equality with
the numpy originals to 1e-12 in both charger eras.  That test is the mechanism
that keeps the two from drifting.

MODEL COMPOSITION
-----------------
``build_demand()``          ported here as ``build_demand()``          (D7)
``scenario_drain_a()``      ported here as ``scenario_drain_a()``
``charge_mask()``           ported here as ``charge_mask()``           (D10)
``step_discharge()``        ported here, scalar                       (D6)
``step_charge()``           ported here, scalar                       (D11/D12)
``charger_power``           imported verbatim (stdlib)
``governor_model``          imported verbatim (stdlib) - the delivery model
``hil_plant_sim.SDP_CHG_*`` imported - the charge dwell latch's constants

PREDICTION MODEL (adjudication section 2.1, the hybrid ruling)
--------------------------------------------------------------
1. CONTROL-INDEPENDENT PRECOMPUTE.  The governor's load filter retains
   ``0.95**1000 = 5.29e-23`` of its state across a 1 s stage, so the filtered
   source total, the open/closed mode and the minority clip bound are functions
   of the preview alone and are computed once per decision, before the search
   (candidate_opus Property A; 240 of 240 stage modes matched a full roll).
2. TRANSITION-STAGE EXACT ROLLS.  Every previewed mode transition (0.60 A
   upward, 0.55 A downward, a charge window opening or closing) is rolled
   through the real ``GovernorModel`` at 1 kHz, once per ladder point, to
   produce ``r_hold[stage][share]`` - the ratio the governor leaves standing at
   drop-out.  Open stages carry that value.  The rolls are SLICED across the
   50 Hz callbacks at ``roll_budget_ms`` (default 2.0 ms) and the previous
   decision's table is used until the new one completes (candidate_fable
   section 2.2 item 2; adjudication section 2.2).
3. CLOSED-STAGE ALGEBRAIC SURROGATE.  On a closed-loop stage the delivered
   share is ``clip(s, lo, 1-lo)`` with ``lo = min(0.5, 0.30/I_tot)``
   (candidate_opus Property B: mean error 8.2e-4, maximum 1.49e-2 over 145
   closed stages).  NO SURROGATE IS WRITTEN FOR THE OPEN-LOOP BRANCH; that is
   the branch two earlier walks in this repository got wrong, and item 2 is
   what replaces it.
4. SHADOW GOVERNOR.  One ``GovernorModel`` is ticked at 1 kHz between feedback
   samples and corrected from the observation each 50 Hz call, so the committed
   governor state is never surrogate-propagated across a decision.

HONEST LIMITS
-------------
* The demand model has NO REGEN TERM (inherited from ``build_demand()``), so
  the controller over-states demand on every decelerating stage and under-values
  coasting.  The live plant has injected regen since the WP-C round, so the
  divergence is larger now than when the DP tables were generated.  Unquantified.
* The stage cost is the ``eta_fc = 0.4`` proxy and the scored quantity is the
  plant's Gfc map, a constant 1.1812 apart.  The constant cancels in a ranking
  at matched terminal state of charge; it does not cancel against the terminal
  price, so the chosen operating point depends on a coefficient that is
  ``TODO(calibrate)`` at rig scale.
* ``ems-sdp-braking``-class profiles are OUTSIDE ``governor_model``'s licensed
  fidelity, so no braking stimulus is registered for this strategy in the first
  round (candidate_fable section 2.3).
* The transition-probability matrix behind ``mpc-sto`` is a vehicle's, its
  diagonal mass is 0.762 at dt = 1 s (near-persistence over short horizons), and
  no simulator stimulus is a draw from it.
"""

from __future__ import annotations

import bisect
import math
import os
import struct
import sys
import time
import zlib
from dataclasses import dataclass, field

_TOOLS = os.path.dirname(os.path.abspath(__file__))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import charger_power as chg_mod          # stdlib only
import governor_model as gov_mod         # stdlib only
# The pack constants live in hil_electrical (stdlib, math + time only); the DP
# generator imports the SAME names from the SAME module, so the two models
# cannot be pointed at different batteries.
from hil_electrical import (                                        # noqa: E402
    LIPO_OCV_SOC, LIPO_OCV_V, BATT_CELLS, BATT_RS_NOM, BATT_CAPACITY_AH)

_sim = None


def _load_sim():
    """Import ``hil_plant_sim`` once.  Stdlib; no I/O at import."""
    global _sim
    if _sim is None:
        import hil_plant_sim as sim      # noqa: WPS433 (deliberate lazy import)
        _sim = sim
    return _sim


# ─────────────────────────────────────────────────────────────────────────────
# Constants.  Every value is restated with the file it came from, in the style
# gen_dp_ems_table.py and sdp_ems_solver.py use, so a drift shows up as a
# citation that no longer matches.
# ─────────────────────────────────────────────────────────────────────────────

# Decision clock.  The SDP artifact's `decision_dt_s` and the TPM's dt, so the
# deterministic variant, the stochastic variant and the SDP benchmark share one
# stage clock (adjudication section 1).
DECISION_DT_S = 1.0

# Preview / model stage length.  gen_dp_ems_table.DP_STAGE_DT_S, restated: a
# walk and a DP table share this discretization, and so does the preview here.
PREVIEW_DT_S = 0.1

# Horizon, in decision stages (adjudication section 1).
HORIZON_N = 20

# Move blocks (adjudication section 2.3, Opus's parametrization).
MOVE_BLOCKS = (2, 6, 12)

# Ladder band.  The default is the DP's own [DP_SHARE_MIN, DP_SHARE_MAX]
# (gen_dp_ems_table.py) - it stops 0.10 short of DROOP_R_MIN/DROOP_R_MAX, so
# updateShareSetpointCutoff() can never latch and applyShareRatio() can never
# attempt an r-based cut.  The SDP envelope is selectable for a like-for-like
# leg against sdp-v3 (adjudication section 2.3).
SHARE_BAND_DP = (0.25, 0.75)
SHARE_BAND_SDP = (0.15, 0.85)
SHARE_LEVELS = 7

# Overcurrent margins.  LIMIT_I_FC_MAX 1.4 A (.ino:1375) and LIMIT_I_BT_MAX
# 3.0 A (.ino:1426), both with gen_dp_ems_table's DP_CHARGE_FC_MARGIN of 0.85
# headroom (adjudication section 1; candidate_fable Table 1).
LIMIT_I_FC_MAX_A = 1.4
LIMIT_I_BT_MAX_A = 3.0
OC_MARGIN = 0.85
I_FC_MAX_A = OC_MARGIN * LIMIT_I_FC_MAX_A          # 1.19 A
I_BT_MAX_A = OC_MARGIN * LIMIT_I_BT_MAX_A          # 2.55 A

# Hydrogen proxy.  ems_walk.H2_PROXY_ETA_FC / H2_LHV_J_PER_G, restated so the
# runtime path does not import ems_walk (which lazily imports numpy modules).
ETA_FC_PROXY = 0.4
Q_LHV_J_PER_G = 120000.0
PROXY_GPS_PER_W = 1.0 / (ETA_FC_PROXY * Q_LHV_J_PER_G)   # 2.0833333e-05 g/s/W

# The plant-side metric this run is SCORED on (hil_plant_sim.py:1047).  Used
# only to price the terminal cost in the proxy's own basis; the controller never
# minimises it.
H2_GFC_DC_GAIN_GPS_PER_W = 1.7637602179836514e-05

# The proxy over-reads the plant metric by this factor at every operating point
# (both candidates measured 1.181).
PROXY_OVER_READ = PROXY_GPS_PER_W / H2_GFC_DC_GAIN_GPS_PER_W   # 1.1811885

# The suite's own equivalent-hydrogen exchange rate
# (run_hil_suite.EMS_EQ_H2_LAMBDA_SOC_PER_G = 0.41, band 0.409-0.415).  Restated
# rather than imported: run_hil_suite is the CONSUMER of a campaign, and a
# strategy that imported its scorer would couple the two in the wrong direction.
EQ_H2_LAMBDA_SOC_PER_G = 0.41

# Terminal price modes (adjudication section 2.4: Huber shape at the metric
# price, converted to the proxy basis).
TERMINAL_DELTA_SOC = 0.0015          # hil_plant_sim.SOC_BAND_HALF, restated
RHO_METRIC_G_PER_SOC = PROXY_OVER_READ / EQ_H2_LAMBDA_SOC_PER_G      # 2.880948
# The SDP's own shadow price in the proxy basis: kappa * alpha/(1-gamma) with
# kappa = (1/(0.85*0.4))/(1/0.5) converting the solver's bus-side eta 0.5 basis
# to the stack-side eta 0.4 proxy (candidate_fable section 3.4).
SDP_KAPPA = (1.0 / (0.85 * ETA_FC_PROXY)) / (1.0 / 0.5)              # 1.4705882
SDP_ALPHA_V3 = 0.1629624189805737     # sdp_policies/sdp_policy_v3.json
SDP_ONE_MINUS_GAMMA = 0.05            # gamma 0.95 per 1 s stage
RHO_SDP_SHADOW_G_PER_SOC = SDP_KAPPA * SDP_ALPHA_V3 / SDP_ONE_MINUS_GAMMA  # 4.793012

# Model levers, recomputed from sdp_ems_solver.model_levers()'s own algebra
# with k = 1/(0.5*Q_LHV), V_pack 7.4 V, V_bus 15.95 V, C_As 18000 A s.  Both
# candidates recomputed these independently (adjudication section 1).
_LEVER_K = 1.0 / (0.5 * Q_LHV_J_PER_G)
_LEVER_C_AS = 5.0 * 3600.0
LEVER_SHARE_SOC_PER_G = 1.0 / (_LEVER_K * 7.4 * _LEVER_C_AS)          # 0.4504505
LEVER_CHG_OLD_SOC_PER_G = 1.0 / (_LEVER_K * 15.95 * _LEVER_C_AS)      # 0.2089864
LEVER_CHG_ETA_SOC_PER_G = chg_mod.ETA_CHG_DEFAULT * LEVER_SHARE_SOC_PER_G  # 0.3963964
# sdp_policy_v3's admission threshold, (1-gamma)/alpha.  The eta-era charge
# lever EXCEEDS it, so the v3 alpha admits charging in the eta era.
SDP_V3_ADMISSION_SOC_PER_G = SDP_ONE_MINUS_GAMMA / SDP_ALPHA_V3       # 0.3068192

# Real-time budgets (adjudication section 2.2).
BUDGET_MS_DEFAULT = 12.0
ROLL_BUDGET_MS_DEFAULT = 2.0

# Governor constants read through governor_model, never re-typed.
GOV_ENTRY_A = 2.0 * gov_mod.GOV_CONST["SHARE_MINORITY_I_MIN_A"]        # 0.60 A
GOV_RELEASE_A = GOV_ENTRY_A - gov_mod.GOV_CONST["SHARE_GOV_OL_HYST_A"]  # 0.55 A
GOV_MIN_LOAD_A = gov_mod.GOV_CONST["SHARE_I_TOT_MIN_A"]                # 0.075 A
GOV_MINORITY_A = gov_mod.GOV_CONST["SHARE_MINORITY_I_MIN_A"]           # 0.30 A
GOV_TICK_S = gov_mod.GOV_CONST["POWER_BAL_PERIOD_US"] * 1e-6           # 1 ms

# Stage mode classes.  Named here rather than reusing governor_model.MODE_*
# because these are PREVIEW classes over a whole stage, not per-tick firmware
# modes, and conflating the two vocabularies is how a census gets misread.
STAGE_CLOSED = "closed"
STAGE_OPEN = "open"
STAGE_FROZEN = "frozen"

# The stochastic variant's chance-constraint quantile
# (sdp_ems_solver.CHARGE_QUANTILE, the same 0.90 the solver uses for admission).
STO_OC_QUANTILE = 0.90


# ─────────────────────────────────────────────────────────────────────────────
# Scalar pack model - ports of gen_dp_ems_table's D6 / D11 / D12 functions.
# ─────────────────────────────────────────────────────────────────────────────
def _interp(xs, ys, x):
    """``np.interp`` on a scalar, with numpy's clamped end behaviour."""
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    i = bisect.bisect_right(xs, x) - 1
    if i >= len(xs) - 1:
        return float(ys[-1])
    x0, x1 = xs[i], xs[i + 1]
    if x1 == x0:
        return float(ys[i])
    return float(ys[i]) + (float(ys[i + 1]) - float(ys[i])) * (x - x0) / (x1 - x0)


def pack_ocv(soc):
    """Pack open-circuit voltage [V] - gen_dp_ems_table.pack_ocv(), scalar."""
    return BATT_CELLS * _interp(LIPO_OCV_SOC, LIPO_OCV_V, float(soc))


def pack_rs(soc):
    """Pack series resistance [ohm] - gen_dp_ems_table.pack_rs(), scalar."""
    s = float(soc)
    k = 1.0 if s > 0.15 else 1.0 + 3.0 * (0.15 - s) / 0.15
    return BATT_CELLS * BATT_RS_NOM * k


def pack_charge_voltage(soc, chg_a):
    """Pack terminal voltage while charging [V] - D12, scalar."""
    return pack_ocv(soc) + float(chg_a) * pack_rs(soc)


def pack_current_from_bus_power(p_bt_bus_w, soc):
    """Pack-side current [A] for a bus-side battery power - D6(a), scalar."""
    sim = _load_sim()
    ocv = pack_ocv(soc)
    rs = pack_rs(soc)
    i0 = p_bt_bus_w / (sim.ETA_BOOST * ocv)
    v1 = max(ocv - i0 * rs, 1.0)
    return p_bt_bus_w / (sim.ETA_BOOST * v1)


def step_discharge(soc, share, p_dem, v_bus, dt, cap_as):
    """One stage on the split control.  Returns ``(soc_next, h2_g, h2_plant_g)``."""
    sim = _load_sim()
    p_fc_bus = share * p_dem
    p_bt_bus = p_dem - p_fc_bus
    i_pack = pack_current_from_bus_power(p_bt_bus, soc)
    soc_next = soc - i_pack * dt / cap_as
    h2 = H2_GFC_DC_GAIN_GPS_PER_W * (p_fc_bus / sim.ETA_BOOST) * dt
    return soc_next, h2, h2


def step_charge(soc, p_dem, v_bus, chg_a, dt, cap_as, eta_chg=None):
    """One stage on the charge control.  Returns ``(soc_next, h2_g, h2_plant_g)``.

    D12: the pack receives ``chg_a`` in BOTH eras - the efficiency sits on the
    charger's INPUT side - so ``soc_next`` never moves with the era; only the
    bus power the fuel cell is billed for does."""
    sim = _load_sim()
    soc_next = soc + chg_a * dt / cap_as
    p_fc_bus_phys = p_dem + chg_mod.charger_bus_power_w(
        chg_a, v_bus, pack_charge_voltage(soc, chg_a), eta_chg)
    h2 = H2_GFC_DC_GAIN_GPS_PER_W * (p_fc_bus_phys / sim.ETA_BOOST) * dt
    h2_plant = H2_GFC_DC_GAIN_GPS_PER_W * (p_dem / sim.ETA_BOOST) * dt
    return soc_next, h2, h2_plant


# ─────────────────────────────────────────────────────────────────────────────
# Scalar demand model - ports of gen_dp_ems_table's D7 / D10 functions.
# ─────────────────────────────────────────────────────────────────────────────
def scenario_drain_a(scenario, t, aux_preload_a=None):
    """The scenario's bus-side auxiliary load [A] at time ``t``.

    Mirrors gen_dp_ems_table.scenario_drain_a() term for term, INCLUDING its
    SOC_BAND_DRAIN_SCENARIOS whitelist.  The whitelist is read from the
    simulator's own branch (apply_scenario()'s three names) rather than from the
    generator, so a generator missing a branch cannot silently halve this
    strategy's modelled demand - the defect ems_walk._drain_override() exists to
    catch."""
    sim = _load_sim()
    if scenario not in SOC_BAND_DRAIN_SCENARIOS:
        if aux_preload_a is None:
            preload = sim.scenario_aux_preload_a(scenario, t)
        elif not aux_preload_a:
            preload = 0.0
        else:
            ramp = (t - sim.AUX_PRELOAD_START_S) / sim.SOC_LOAD_RAMP_S
            preload = float(aux_preload_a) * max(0.0, min(1.0, ramp))
        return sim.I_AUX_A + preload
    ramp_in = max(0.0, min(1.0, (t - sim.SOC_BAND_DRAIN_START_S) / sim.SOC_LOAD_RAMP_S))
    ramp_out = max(0.0, min(1.0, (t - sim.SOC_BAND_DRAIN_END_S) / sim.SOC_LOAD_RAMP_S))
    return sim.I_AUX_A + sim.SOC_BAND_DRAIN_LOAD_A * (ramp_in - ramp_out)


# The simulator's own whitelist (hil_plant_sim.apply_scenario()), restated for
# the reason scenario_drain_a() above gives.  A new MPC scenario that shares the
# `ems-soc-band` stimulus MUST be added here AND to
# gen_dp_ems_table.SOC_BAND_DRAIN_SCENARIOS at registration - the B2 defect of
# 2026-09-01 was exactly that omission.
SOC_BAND_DRAIN_SCENARIOS = ("ems-soc-band", "ems-dp-replay", "ems-sdp")


def build_demand(scenario, meta, times, dt, aux_preload_a=None):
    """Per-stage ``(v, a, p_dem, v_bus, i_total, cruise)`` lists - D7, scalar.

    A term-for-term port of gen_dp_ems_table.build_demand(), including the four
    Picard iterations on the droop node and the central-difference acceleration.

    ⚠️ NO REGEN TERM (``p_mech = max(0, F*v)``), inherited deliberately: this is
    the model the DP bound is computed against, and a controller predicting on a
    different demand model could not be compared with it.  The consequence is
    that demand is over-stated on decelerating stages."""
    sim = _load_sim()
    prof = meta.get("ems_v_profile")
    if not prof:
        raise ValueError("scenario %r defines no ems_v_profile - this "
                         "prediction model derives its demand from one (D7)"
                         % scenario)
    n = len(times)
    v = [0.0] * n
    a = [0.0] * n
    i_aux = [0.0] * n
    for k in range(n):
        t = times[k]
        v[k] = sim.piecewise(prof, t)
        a[k] = (sim.piecewise(prof, t + 0.5 * dt)
                - sim.piecewise(prof, t - 0.5 * dt)) / dt
        i_aux[k] = scenario_drain_a(scenario, t, aux_preload_a)

    p_mech = [0.0] * n
    for k in range(n):
        if v[k] > sim.V_STICTION:
            f_coul = sim.F_COULOMB
        elif v[k] < -sim.V_STICTION:
            f_coul = -sim.F_COULOMB
        else:
            f_coul = 0.0
        force = sim.M_EFF * a[k] + f_coul + sim.B_EFF * v[k]
        p_mech[k] = max(0.0, force * v[k])

    v_bus = [sim.V_BUS_DROOP_V0] * n
    i_total = [0.0] * n
    for _ in range(4):
        for k in range(n):
            i_motor = p_mech[k] / (sim.ETA_BOOST * v_bus[k])
            i_total[k] = i_motor + i_aux[k]
            v_bus[k] = sim.V_BUS_DROOP_V0 - sim.K_DROOP_BUS_SHARED * i_total[k]
    p_dem = [0.0] * n
    for k in range(n):
        i_motor = p_mech[k] / (sim.ETA_BOOST * v_bus[k])
        i_total[k] = i_motor + i_aux[k]
        p_dem[k] = v_bus[k] * i_total[k]

    cruise = [(abs(a[k]) <= sim.SOC_BAND_CRUISE_SLOPE_MAX
               and v[k] >= sim.SOC_BAND_CRUISE_MIN_MPS) for k in range(n)]
    return v, a, p_dem, v_bus, i_total, cruise


def charge_mask(times, p_dem, v_bus, cruise, chg_ceiling_a, run_exit_s,
                eta_chg=None, v_pack_ref=None):
    """Per-stage boolean: may a charge window open here? - D10, scalar port."""
    sim = _load_sim()
    chg_mod.check_eta_chg(eta_chg)
    if eta_chg is not None and v_pack_ref is None:
        raise ValueError("charge_mask needs v_pack_ref when eta_chg is set "
                         "(the new era bills the charger at the PACK voltage)")
    out = []
    for k in range(len(times)):
        in_run = sim.EMS_RUN_ENTRY_S <= times[k] < run_exit_s
        i_chg_bus = chg_mod.charger_bus_current_a(chg_ceiling_a, v_bus[k],
                                                  v_pack_ref, eta_chg)
        budget_ok = ((p_dem[k] / v_bus[k] + i_chg_bus)
                     <= OC_MARGIN * LIMIT_I_FC_MAX_A)
        out.append(bool(in_run and cruise[k] and budget_ok))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# A stdlib MATLAB v5 reader, for the stochastic variant's demand matrix.
#
# WHY IT IS HERE.  sdp_policy_v4.json carries the TPM's PATH and sha256 but not
# its CONTENTS, and sdp_ems_solver.load_tpm() is numpy+scipy.  The runtime path
# must not import either, so the matrix is read directly.  The file format
# allows it: `TPM_dt1_hil.mat` is a MAT-file 5.0 whose single element is a
# zlib-compressed miMATRIX holding a full double array, and zlib + struct are
# stdlib.  The reader refuses anything it does not understand rather than
# guessing - a silent misparse of a transition matrix would be invisible in
# every downstream number.
# ─────────────────────────────────────────────────────────────────────────────
_MI_INT8, _MI_UINT8, _MI_INT16, _MI_UINT16 = 1, 2, 3, 4
_MI_INT32, _MI_UINT32, _MI_SINGLE, _MI_DOUBLE = 5, 6, 7, 9
_MI_MATRIX, _MI_COMPRESSED = 14, 15
_MX_DOUBLE_CLASS = 6

_MI_FMT = {_MI_INT8: "b", _MI_UINT8: "B", _MI_INT16: "h", _MI_UINT16: "H",
           _MI_INT32: "i", _MI_UINT32: "I", _MI_SINGLE: "f", _MI_DOUBLE: "d"}
_MI_SIZE = {_MI_INT8: 1, _MI_UINT8: 1, _MI_INT16: 2, _MI_UINT16: 2,
            _MI_INT32: 4, _MI_UINT32: 4, _MI_SINGLE: 4, _MI_DOUBLE: 8}


def _mat_tag(buf, off, endian):
    """Read one data-element tag.  Returns ``(dtype, nbytes, data_off, next)``.

    Handles the SMALL-ELEMENT form, in which the two high bytes of the first
    word carry the byte count and the payload follows in the same word."""
    (word,) = struct.unpack_from(endian + "I", buf, off)
    small = (word >> 16) & 0xFFFF
    if small:
        return word & 0xFFFF, small, off + 4, off + 8
    dtype = word
    (nbytes,) = struct.unpack_from(endian + "I", buf, off + 4)
    pad = (8 - (nbytes % 8)) % 8
    return dtype, nbytes, off + 8, off + 8 + nbytes + pad


def _mat_read(buf, off, endian):
    """Read one element's payload as a list of Python numbers."""
    dtype, nbytes, data_off, nxt = _mat_tag(buf, off, endian)
    if dtype not in _MI_FMT:
        raise ValueError("unsupported MAT data type %d" % dtype)
    n = nbytes // _MI_SIZE[dtype]
    vals = list(struct.unpack_from(endian + str(n) + _MI_FMT[dtype],
                                   buf, data_off))
    return vals, nxt


def _mat_parse_matrix(buf, off, endian, out):
    """Parse one miMATRIX element into ``out[name] = (rows, cols, data)``."""
    dtype, nbytes, data_off, nxt = _mat_tag(buf, off, endian)
    if dtype != _MI_MATRIX:
        return nxt
    p = data_off
    flags, p = _mat_read(buf, p, endian)
    mclass = flags[0] & 0xFF
    complex_flag = bool((flags[0] >> 8) & 0x08)
    dims, p = _mat_read(buf, p, endian)
    name_vals, p = _mat_read(buf, p, endian)
    name = "".join(chr(c) for c in name_vals)
    if mclass != _MX_DOUBLE_CLASS or complex_flag or len(dims) != 2:
        # Not a real 2-D double array: skipped, not guessed at.
        return nxt
    data, p = _mat_read(buf, p, endian)
    out[name] = (int(dims[0]), int(dims[1]), [float(x) for x in data])
    return nxt


def load_mat_doubles(path):
    """Every real 2-D double array in a MAT-file 5.0, as ``{name: (r, c, data)}``.

    ``data`` is COLUMN-MAJOR, as MATLAB stores it.  Raises on a file this reader
    does not understand."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if len(raw) < 128:
        raise ValueError("%s is too short to be a MAT-file" % path)
    if raw[:6] != b"MATLAB":
        raise ValueError("%s is not a MAT-file 5.0 (bad header)" % path)
    endian = "<" if raw[126:128] == b"IM" else ">"
    out = {}
    off = 128
    while off + 8 <= len(raw):
        dtype, nbytes, data_off, nxt = _mat_tag(raw, off, endian)
        if dtype == _MI_COMPRESSED:
            inner = zlib.decompress(raw[data_off:data_off + nbytes])
            ioff = 0
            while ioff + 8 <= len(inner):
                ioff = _mat_parse_matrix(inner, ioff, endian, out)
        elif dtype == _MI_MATRIX:
            _mat_parse_matrix(raw, off, endian, out)
        off = nxt
    return out


def load_tpm(path, name="TPM"):
    """The transition-probability matrix as a list of row lists.

    ``name`` selects the variable; the sole array in the file is used when the
    named one is absent, so a matrix stored under a different variable name is
    still readable without a guess about WHICH of several it is."""
    arrays = load_mat_doubles(path)
    if name not in arrays:
        if len(arrays) != 1:
            raise ValueError("%s carries %d arrays (%s); name one"
                             % (path, len(arrays), ", ".join(sorted(arrays))))
        name = next(iter(arrays))
    rows, cols, data = arrays[name]
    if rows != cols:
        raise ValueError("%s[%s] is %dx%d, not square" % (path, name, rows, cols))
    # MATLAB is column-major: element (i, j) sits at j*rows + i.
    return [[data[j * rows + i] for j in range(cols)] for i in range(rows)]


# ─────────────────────────────────────────────────────────────────────────────
# Preview and the control-independent precompute (Property A).
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Preview:
    """The scenario's demand over the whole run, at ``PREVIEW_DT_S``."""
    times: list = field(default_factory=list)
    p_dem: list = field(default_factory=list)
    v_bus: list = field(default_factory=list)
    i_total: list = field(default_factory=list)
    cruise: list = field(default_factory=list)
    chg_ok: list = field(default_factory=list)
    dt: float = PREVIEW_DT_S

    def index(self, t):
        """The preview sample covering time ``t``, clamped to the array."""
        k = int(math.floor(t / self.dt + 1e-9))
        if k < 0:
            return 0
        if k >= len(self.times):
            return len(self.times) - 1
        return k


@dataclass
class StagePrecompute:
    """Per-decision-stage, control-independent quantities (Property A).

    Every field here is a function of the PREVIEW ALONE.  The governor's load
    filter retains ``0.95**1000 = 5.29e-23`` of its state across a 1 s stage, so
    the filtered total - and therefore the open/closed mode and the minority clip
    bound - cannot depend on the candidate control.  That is what makes the
    search's inner loop a table lookup."""
    n: int = 0
    i_tot: list = field(default_factory=list)        # per sub-sample, per stage
    p_dem: list = field(default_factory=list)
    v_bus: list = field(default_factory=list)
    lo: list = field(default_factory=list)           # minority clip bound
    mode: list = field(default_factory=list)         # STAGE_* per sub-sample
    chg_ok: list = field(default_factory=list)       # all sub-samples admit
    transition: list = field(default_factory=list)   # a mode change inside
    p_dem_mean: list = field(default_factory=list)
    v_bus_mean: list = field(default_factory=list)
    i_tot_mean: list = field(default_factory=list)
    # ABSOLUTE preview sample at each stage's start.  The transition-roll table
    # is keyed on this, not on the horizon-relative index: a table computed at
    # one decision may still be in use one or two decisions later (it is sliced
    # across the callbacks), by which time the horizon has receded and a
    # relative key would silently point at the WRONG stage.
    stage_key: list = field(default_factory=list)


def precompute_stages(prev, k0, horizon, dt_dec=DECISION_DT_S,
                      mode_seed=STAGE_CLOSED):
    """Classify ``horizon`` decision stages from preview sample ``k0``.

    ``mode_seed`` is the governor's mode as the horizon opens; the hysteresis is
    carried forward from it, so a horizon that starts inside a closed-loop run
    does not re-derive the entry threshold from nothing."""
    n_sub = int(round(dt_dec / prev.dt))
    out = StagePrecompute(n=horizon)
    mode = mode_seed
    npv = len(prev.times)
    for j in range(horizon):
        it, pd, vb, lo, md, ok = [], [], [], [], [], True
        changed = False
        for s in range(n_sub):
            k = min(npv - 1, k0 + j * n_sub + s)
            i_tot = prev.i_total[k]
            # Settled-filter classification with the firmware's own hysteresis
            # (.ino:10126-10145): entry at 0.60 A, release at 0.55 A.
            if i_tot < GOV_MIN_LOAD_A:
                m = STAGE_FROZEN
            elif mode == STAGE_CLOSED:
                m = STAGE_CLOSED if i_tot >= GOV_RELEASE_A else STAGE_OPEN
            else:
                m = STAGE_CLOSED if i_tot > GOV_ENTRY_A else STAGE_OPEN
            if m != mode:
                changed = True
            mode = m if m != STAGE_FROZEN else mode
            it.append(i_tot)
            pd.append(prev.p_dem[k])
            vb.append(prev.v_bus[k])
            lo.append(min(0.5, GOV_MINORITY_A / i_tot) if i_tot > 0.0 else 0.5)
            md.append(m)
            ok = ok and prev.chg_ok[k]
        out.i_tot.append(it)
        out.p_dem.append(pd)
        out.v_bus.append(vb)
        out.lo.append(lo)
        out.mode.append(md)
        out.chg_ok.append(ok)
        out.transition.append(changed)
        out.stage_key.append(k0 + j * n_sub)
        out.p_dem_mean.append(sum(pd) / len(pd))
        out.v_bus_mean.append(sum(vb) / len(vb))
        out.i_tot_mean.append(sum(it) / len(it))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Transition-stage exact rolls (adjudication section 2.1's replacement for a
# hand-written open-loop surrogate), computed once per decision and SLICED.
# ─────────────────────────────────────────────────────────────────────────────
class RollJob:
    """A sliceable set of 1 kHz governor rolls over the previewed transitions.

    One work item per (transition stage, ladder point).  ``advance(budget_s)``
    runs items until the budget is spent and returns True when the table is
    complete.  Until then the caller keeps using the PREVIOUS decision's table,
    which is what makes the whole decision anytime (adjudication section 2.2)."""

    # THE ROLL BUDGET IS STRUCTURAL, NOT AN ASSUMPTION ABOUT THE PREVIEW.  The
    # adjudication's arithmetic (section 2.1) bounds the slice at four
    # transitions per decision, and a preview with more of them would otherwise
    # push the table past the 50 callbacks it has to complete in.  The FIRST
    # transitions are kept, which are the ones nearest the present and therefore
    # the ones the executed first move depends on; a later transition carries the
    # standing ratio until the horizon recedes onto it, at which point it is
    # rolled.  A preview that trips this is a preview whose share authority is
    # oscillating faster than 4 transitions per 20 s.
    MAX_TRANSITIONS = 4

    def __init__(self, pre, ladder, dt_dec=DECISION_DT_S, dv0_v=0.0,
                 charge_stage=None, tick_s=GOV_TICK_S,
                 max_transitions=None):
        self.pre = pre
        self.ladder = list(ladder)
        self.dt_dec = float(dt_dec)
        self.dv0_v = float(dv0_v)
        self.tick_s = float(tick_s)
        self.charge_stage = charge_stage or (lambda j: False)
        cap = self.MAX_TRANSITIONS if max_transitions is None else int(max_transitions)
        stages = [j for j in range(pre.n) if pre.transition[j]][:cap]
        self.transition_stages = stages
        self.dropped_transitions = sum(1 for j in range(pre.n)
                                       if pre.transition[j]) - len(stages)
        self.items = [(j, si) for j in stages
                      for si in range(len(self.ladder))]
        self.stage_key = list(pre.stage_key)
        self.cursor = 0
        self.table = {}
        self.rolls = 0

    @property
    def done(self):
        return self.cursor >= len(self.items)

    def advance(self, budget_s):
        """Run work items for at most ``budget_s`` seconds of wall clock."""
        t0 = time.perf_counter()
        while self.cursor < len(self.items):
            j, si = self.items[self.cursor]
            self.table[(self.stage_key[j], si)] = self._roll(j, si)
            self.cursor += 1
            self.rolls += 1
            if time.perf_counter() - t0 >= budget_s:
                break
        return self.done

    def run_all(self):
        """Complete the table with no budget - for tests and the offline walk."""
        while not self.done:
            self.advance(1e9)
        return self.table

    def _roll(self, j, si):
        """One exact 1 kHz roll of stage ``j`` under ladder point ``si``.

        The governor is seeded with the CLOSED-LOOP delivered ratio for this
        ladder point at the stage's entry current, which is the assumption
        stated in candidate_fable section 2.2: the command is held across the
        transition.  The roll returns the ratio standing at the stage end - the
        value the following open stages carry."""
        pre = self.pre
        s = self.ladder[si]
        lo0 = pre.lo[j][0]
        seed = min(max(s, lo0), 1.0 - lo0)
        g = gov_mod.GovernorModel(dt_s=self.tick_s, dv0_v=self.dv0_v,
                                  seed_r=seed)
        # Enter the stage already in a converged closed-loop run when the
        # preview says the stage opens closed; otherwise let the model decide.
        g.state.filt_total = pre.i_tot[j][0]
        if pre.mode[j][0] == STAGE_CLOSED:
            g.state.closed_loop_mode = True
            g.state.closed_loop_run = True
            g.state.acted_sp = s
        n_sub = len(pre.i_tot[j])
        ticks = int(round(self.dt_dec / self.tick_s))
        per = max(1, ticks // n_sub)
        delivered = seed
        charging = bool(self.charge_stage(j))
        for tk in range(ticks):
            sub = min(n_sub - 1, tk // per)
            i_tot = pre.i_tot[j][sub]
            i_fc = delivered * i_tot
            sw_fc = True
            sw_bt = not charging
            o = g.step(s, i_fc, i_tot - i_fc, sw_fc, sw_bt,
                       tk * self.tick_s, charge_path_owns_bt=charging)
            delivered = g.delivered_share(o.r_applied, i_tot,
                                          o.fc_bus_req, o.bt_bus_req)
        return g.state.r_prev


# ─────────────────────────────────────────────────────────────────────────────
# The charge dwell latch.  Semantics reproduced from
# SdpStrategy.charge_hold_status() with the SDP_CHG_* constants IMPORTED, not
# re-typed, so the two cannot drift (adjudication section 1).
# ─────────────────────────────────────────────────────────────────────────────
class ChargeLatch:
    """The 8 s minimum-dwell charge latch, with the SDP's three exits."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.hold_until = None
        self.v_ref = None
        self.holds = 0
        self.drops = 0
        self.drop_reason = None

    def status(self, t, fb):
        """``None`` / ``"active"`` / ``"expired"`` / ``"dropped"``.

        Term for term SdpStrategy.charge_hold_status(): a fault is tested BEFORE
        expiry (a fault landing on an expiry tick is a withdrawal, not a
        re-decision), then the cruise-exit test, then the dwell."""
        sim = _load_sim()
        if self.hold_until is None or t is None:
            return None
        flags = fb.get("fault_flags")
        if flags is not None and (int(flags) & sim.SDP_CHG_ABORT_FAULT_MASK):
            self._drop("board faulted")
            return "dropped"
        v_now = fb.get("v_profile")
        if (v_now is not None and self.v_ref is not None
                and abs(float(v_now) - self.v_ref) > sim.SDP_CHG_CRUISE_DELTA_MPS):
            self._drop("drive left the admitted cruise")
            return "dropped"
        if t >= self.hold_until:
            self._drop("dwell expired")
            return "expired"
        return "active"

    def arm(self, t, v_profile):
        sim = _load_sim()
        self.hold_until = float(t) + sim.SDP_CHG_MIN_DWELL_S
        self.v_ref = None if v_profile is None else float(v_profile)
        self.holds += 1

    def _drop(self, reason):
        self.hold_until = None
        self.v_ref = None
        self.drop_reason = reason
        if reason != "dwell expired":
            self.drops += 1

    def stages_remaining(self, t, dt_dec=DECISION_DT_S):
        """Decision stages the latch still pins high from ``t``."""
        if self.hold_until is None or t is None:
            return 0
        return max(0, int(math.ceil((self.hold_until - float(t)) / dt_dec)))


# ─────────────────────────────────────────────────────────────────────────────
# Terminal cost (adjudication section 2.4: Huber shape at the metric price).
# ─────────────────────────────────────────────────────────────────────────────
def terminal_price(mode):
    """The terminal state-of-charge price in PROXY grams per unit SoC."""
    if mode == "metric":
        return RHO_METRIC_G_PER_SOC
    if mode == "sdp-shadow":
        return RHO_SDP_SHADOW_G_PER_SOC
    try:
        rho = float(mode)
    except (TypeError, ValueError):
        raise ValueError("terminal price mode must be 'metric', 'sdp-shadow' "
                         "or a number, got %r" % (mode,))
    if rho < 0.0:
        raise ValueError("an explicit terminal price must not be negative")
    return rho


def huber(delta_soc, rho, delta=TERMINAL_DELTA_SOC):
    """Huber penalty: quadratic inside the dead band, linear outside.

    The dead band is ``soc-band``'s own half-width, and it exists so a 1 Hz
    decision does not chatter about the target: a purely linear price is
    bang-bang at the origin (candidate_fable section 3.4)."""
    d = abs(float(delta_soc))
    if delta <= 0.0:
        return rho * d
    if d <= delta:
        return rho * d * d / (2.0 * delta)
    return rho * (d - 0.5 * delta)


# ─────────────────────────────────────────────────────────────────────────────
# The planner.
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Decision:
    share: float = 0.5
    charge: bool = False
    plan_share: list = field(default_factory=list)     # per stage, whole horizon
    plan_charge: list = field(default_factory=list)
    cost: float = float("inf")
    solve_ms: float = 0.0
    budget_hit: bool = False
    candidates: int = 0
    pruned: int = 0
    share_pred: float = 0.5       # predicted DELIVERED share of stage 0
    feasible: bool = True


class Planner:
    """Move-blocked enumeration with warm start and branch-and-bound.

    The search carries the governor state EXACTLY along each candidate through
    the precomputed tables, which a state-space dynamic program cannot do
    without an 882-state governor axis (candidate_opus section 3.1)."""

    def __init__(self, *, horizon=HORIZON_N, blocks=MOVE_BLOCKS,
                 share_band=SHARE_BAND_DP, share_levels=SHARE_LEVELS,
                 terminal_mode="metric", budget_ms=BUDGET_MS_DEFAULT,
                 eta_chg=chg_mod.ETA_CHG_DEFAULT, chg_a=0.8,
                 cap_as=5.0 * 3600.0, h2_map="proxy", h2_convex=None,
                 dt_dec=DECISION_DT_S):
        if sum(blocks) != horizon:
            raise ValueError("move blocks %r do not sum to the horizon %d"
                             % (blocks, horizon))
        if share_levels < 2:
            raise ValueError("share_levels must be at least 2")
        self.horizon = int(horizon)
        self.blocks = tuple(blocks)
        self.band = (float(share_band[0]), float(share_band[1]))
        self.ladder = [self.band[0] + (self.band[1] - self.band[0])
                       * i / float(share_levels - 1)
                       for i in range(share_levels)]
        self.terminal_mode = terminal_mode
        self.rho = terminal_price(terminal_mode)
        self.budget_ms = float(budget_ms)
        self.eta_chg = chg_mod.check_eta_chg(eta_chg)
        self.chg_a = float(chg_a)
        self.cap_as = float(cap_as)
        self.dt_dec = float(dt_dec)
        if h2_map not in ("proxy", "convex"):
            raise ValueError("h2_map must be 'proxy' or 'convex'")
        if h2_map == "convex" and not h2_convex:
            # REFUSED UNLESS SUPPLIED (adjudication section 1).  a0, P_peak and
            # eta_peak are stack quantities this rig has not measured, and
            # inventing rig-scale defaults for them is exactly the class of
            # unsourced constant this repository has had to retract before.
            raise ValueError(
                "--mpc-h2-map convex needs a0, p_peak and eta_peak: they are "
                "UNMEASURED stack quantities for this rig (TODO(calibrate)) and "
                "no defaults are invented")
        self.h2_map = h2_map
        self.h2_convex = dict(h2_convex or {})
        self.incumbent = None      # the previous decision's block share indices
        self.incumbent_charge = 0
        self._order_cache = {}

    # -- stage cost ---------------------------------------------------------
    def h2_rate_gps(self, p_fc_stack_w):
        """Hydrogen rate [g/s] for a STACK power, under the selected map."""
        if p_fc_stack_w <= 0.0:
            return 0.0
        if self.h2_map == "proxy":
            return p_fc_stack_w * PROXY_GPS_PER_W
        a0 = self.h2_convex["a0"]
        p_peak = self.h2_convex["p_peak"]
        eta_peak = self.h2_convex["eta_peak"]
        a2 = a0 / (p_peak * p_peak)
        a1 = (p_peak / (eta_peak * Q_LHV_J_PER_G) - 2.0 * a0) / p_peak
        return a0 + a1 * p_fc_stack_w + a2 * p_fc_stack_w * p_fc_stack_w

    # -- the control-independent delivered-share table ----------------------
    def delivery_table(self, pre, r_hold, r_seed, charge_stages, i_tot_oc=None):
        """Per (stage, ladder point): delivered share, FC power, BT power, feasibility.

        This is the whole search model.  It is built ONCE per decision, so the
        candidate rollouts below are table lookups plus one pack step per stage.

        ``r_hold`` maps ``(absolute stage key, ladder index)`` to the roll's end-of-stage
        ratio; a missing entry falls back to the standing carried ratio, which is
        what the previous decision's table supplies while a new roll is being
        sliced.  ``i_tot_oc`` optionally supplies a per-stage source total to
        judge the overcurrent constraint against, which is how the stochastic
        variant tightens the bound to a quantile without changing the cost."""
        n_s = len(self.ladder)
        d_tab = [[0.0] * n_s for _ in range(pre.n)]
        pfc_tab = [[0.0] * n_s for _ in range(pre.n)]
        pbt_tab = [[0.0] * n_s for _ in range(pre.n)]
        ok_tab = [[True] * n_s for _ in range(pre.n)]
        for si in range(n_s):
            s = self.ladder[si]
            carried = r_seed
            for j in range(pre.n):
                if charge_stages[j]:
                    # BT is off the bus: the fuel cell is the single source and
                    # also feeds the charger.  The traction split is 1.0 and the
                    # ratio winds onto DROOP_R_MIN, which the next transition
                    # roll picks up (CLAUDE.md 2026-09-01c).
                    carried = gov_mod.GOV_CONST["DROOP_R_MIN"]
                    i_chg_bus = chg_mod.charger_bus_current_a(
                        self.chg_a, pre.v_bus_mean[j],
                        pack_charge_voltage(0.6, self.chg_a), self.eta_chg)
                    i_fc = (i_tot_oc[j] if i_tot_oc else pre.i_tot_mean[j]) + i_chg_bus
                    d_tab[j][si] = 1.0
                    pfc_tab[j][si] = pre.p_dem_mean[j]
                    pbt_tab[j][si] = 0.0
                    ok_tab[j][si] = i_fc <= I_FC_MAX_A
                    continue
                acc_d = acc_fc = acc_bt = 0.0
                n_sub = len(pre.i_tot[j])
                feasible = True
                oc_scale = ((i_tot_oc[j] / pre.i_tot_mean[j])
                            if (i_tot_oc and pre.i_tot_mean[j] > 0.0) else 1.0)
                for sub in range(n_sub):
                    if pre.mode[j][sub] == STAGE_CLOSED:
                        lo = pre.lo[j][sub]
                        d = min(max(s, lo), 1.0 - lo)
                        carried = d
                    else:
                        d = carried
                    acc_d += d
                    acc_fc += d * pre.p_dem[j][sub]
                    acc_bt += (1.0 - d) * pre.p_dem[j][sub]
                    i_tot = pre.i_tot[j][sub] * oc_scale
                    if d * i_tot > I_FC_MAX_A or (1.0 - d) * i_tot > I_BT_MAX_A:
                        feasible = False
                key = (pre.stage_key[j], si)
                if key in r_hold:
                    carried = r_hold[key]
                d_tab[j][si] = acc_d / n_sub
                pfc_tab[j][si] = acc_fc / n_sub
                pbt_tab[j][si] = acc_bt / n_sub
                ok_tab[j][si] = feasible
        return d_tab, pfc_tab, pbt_tab, ok_tab

    # -- one candidate ------------------------------------------------------
    def _rollout(self, soc0, soc_ref, pre, tabs, charge_stages, block_idx,
                 bound):
        """Cost of one move-blocked candidate, abandoned above ``bound``."""
        sim = _load_sim()
        d_tab, pfc_tab, pbt_tab, ok_tab = tabs
        soc = soc0
        cost = 0.0
        stage = 0
        for bi, blen in enumerate(self.blocks):
            si = block_idx[bi]
            for _ in range(blen):
                if stage >= pre.n:
                    break
                if not ok_tab[stage][si]:
                    return None, 0.0, 0.0
                if charge_stages[stage]:
                    p_fc_bus = (pre.p_dem_mean[stage]
                                + chg_mod.charger_bus_power_w(
                                    self.chg_a, pre.v_bus_mean[stage],
                                    pack_charge_voltage(soc, self.chg_a),
                                    self.eta_chg))
                    soc = soc + self.chg_a * self.dt_dec / self.cap_as
                else:
                    p_fc_bus = pfc_tab[stage][si]
                    i_pack = pack_current_from_bus_power(pbt_tab[stage][si], soc)
                    soc = soc - i_pack * self.dt_dec / self.cap_as
                cost += self.h2_rate_gps(p_fc_bus / sim.ETA_BOOST) * self.dt_dec
                if cost >= bound:
                    # Sound: the remaining stage costs are non-negative and the
                    # terminal term is bounded below by zero.
                    return None, 0.0, 0.0
                stage += 1
        cost += huber(soc - soc_ref, self.rho)
        return cost, soc, d_tab[0][block_idx[0]]

    # -- enumeration --------------------------------------------------------
    def solve(self, soc0, soc_ref, pre, r_hold, r_seed, charge_options,
              i_tot_oc=None, budget_ms=None):
        """Search the candidate set.  Returns a ``Decision``.

        ``charge_options`` is a list of per-stage boolean lists, the first of
        which MUST be the no-charge option so an expired budget always has a
        feasible incumbent.  Ties resolve to the smaller share and to no charge
        (the SDP's D8 rule), which is why the enumeration walks the ladder
        upward and the charge options in the order given."""
        t0 = time.perf_counter()
        budget_s = (self.budget_ms if budget_ms is None else float(budget_ms)) * 1e-3
        n_s = len(self.ladder)
        nb = len(self.blocks)
        tabs_by_opt = [self.delivery_table(pre, r_hold, r_seed, cs, i_tot_oc)
                       for cs in charge_options]

        # THE INFEASIBLE FALLBACK, stated: if no candidate is feasible the
        # decision keeps this seed - the lowest ladder point, no charge, which
        # is the least fuel-cell-loaded command available - and
        # `feasible` stays False so the run's summary and the CSV show it. A
        # decision that commanded nothing would leave the previous share
        # standing without saying so.
        best = Decision(cost=float("inf"))
        best.share = self.ladder[0]
        best.plan_share = [self.ladder[0]] * pre.n
        best.plan_charge = list(charge_options[0])
        order = self._enumeration_order(n_s, nb)
        n_eval = 0
        pruned = 0
        hit = False
        for oi, cs in enumerate(charge_options):
            tabs = tabs_by_opt[oi]
            for block_idx in order:
                cost, soc_n, d0 = self._rollout(soc0, soc_ref, pre, tabs, cs,
                                                block_idx, best.cost)
                n_eval += 1
                if cost is None:
                    pruned += 1
                elif cost < best.cost:
                    best.cost = cost
                    best.share = self.ladder[block_idx[0]]
                    best.charge = bool(cs[0])
                    best.share_pred = d0
                    best.plan_share = self._expand(block_idx)
                    best.plan_charge = list(cs)
                    self.incumbent = tuple(block_idx)
                    self.incumbent_charge = oi
                if time.perf_counter() - t0 >= budget_s:
                    hit = True
                    break
            if hit:
                break
        best.candidates = n_eval
        best.pruned = pruned
        best.budget_hit = hit
        best.feasible = math.isfinite(best.cost)
        best.solve_ms = (time.perf_counter() - t0) * 1e3
        return best

    def _enumeration_order(self, n_s, nb):
        """Candidates ordered outward in ladder distance from the incumbent.

        THE SHIFT IS DEGENERATE HERE, and that is a property of the
        parametrization rather than an omission: with a FIXED block partition
        (2, 6, 12) the incumbent sequence shifted one stage carries the same
        three block values, so the shifted incumbent and the incumbent are the
        same candidate.  Warm start therefore means "start at the previous
        decision's block indices", which is what makes the search ANYTIME:
        abandoning it at any point leaves a feasible command that was validated
        one second earlier.

        The ordering is cached on the seed: it is a pure function of
        ``(n_s, nb, seed)`` and rebuilding 343 tuples per decision is work the
        budget of section 2.2 should not be spending."""
        seed = self.incumbent if self.incumbent is not None else (n_s // 2,) * nb
        seed = tuple(min(n_s - 1, max(0, int(x))) for x in seed[:nb])
        if len(seed) < nb:
            seed = seed + (seed[-1],) * (nb - len(seed))
        key = (n_s, nb, seed)
        cached = self._order_cache.get(key)
        if cached is not None:
            return cached
        all_idx = []

        def rec(prefix):
            if len(prefix) == nb:
                all_idx.append(tuple(prefix))
                return
            for i in range(n_s):
                rec(prefix + [i])

        rec([])
        all_idx.sort(key=lambda c: (sum(abs(c[i] - seed[i]) for i in range(nb)),
                                    c))
        # Bounded: one entry per distinct seed, and there are n_s**nb seeds at
        # most.  Cleared wholesale rather than grown without bound.
        if len(self._order_cache) > 64:
            self._order_cache.clear()
        self._order_cache[key] = all_idx
        return all_idx

    def _expand(self, block_idx):
        plan = []
        for bi, blen in enumerate(self.blocks):
            plan.extend([self.ladder[block_idx[bi]]] * blen)
        return plan[:self.horizon]


# ─────────────────────────────────────────────────────────────────────────────
# The shadow governor (adjudication section 2.1: the state estimate).
# ─────────────────────────────────────────────────────────────────────────────
class ShadowGovernor:
    """One ``GovernorModel`` ticked at 1 kHz between 50 Hz feedback samples.

    ⚠️ THE MDAC CORRECTION IS CONDITIONAL ON THE FEEDBACK VIEW.  The design calls
       for ``r_prev`` to be overwritten from ``governor_model.r_from_codes()``
       each feedback sample.  The simulator's EMS feedback view
       (hil_plant_sim.py, the MODE A ``_fb()`` builder) does NOT currently carry
       the two MDAC words, so this class uses them when a caller supplies
       ``mdac_fc``/``mdac_bt`` and otherwise corrects from the MEASURED delivered
       share ``|I_fc|/(|I_fc|+|I_batt|)``, which is telemetry-equivalent and
       available.  Adding the two words to the feedback view is an additive
       registration step (see the design document); until it lands, the
       ``mdac_corrections`` counter reads zero and ``current_corrections`` carries
       the load."""

    def __init__(self, dv0_v=0.0, seed_r=0.5, tick_s=GOV_TICK_S):
        self.tick_s = float(tick_s)
        self.model = gov_mod.GovernorModel(dt_s=tick_s, dv0_v=dv0_v,
                                           seed_r=seed_r)
        self.last_t = None
        self.mdac_corrections = 0
        self.current_corrections = 0
        self.mode_mismatch = 0
        self.ticks = 0

    def reset(self, seed_r=0.5):
        self.model.reset(seed_r)
        self.last_t = None
        self.mdac_corrections = 0
        self.current_corrections = 0
        self.mode_mismatch = 0
        self.ticks = 0

    @property
    def r(self):
        return self.model.state.r_prev

    @property
    def closed(self):
        return bool(self.model.state.closed_loop_mode)

    def observe(self, fb):
        """Correct the model from one feedback sample."""
        r_obs = gov_mod.r_from_codes(fb.get("mdac_fc"), fb.get("mdac_bt"))
        if r_obs is not None:
            if abs(r_obs - self.model.state.r_prev) > 0.05:
                self.mode_mismatch += 1
            self.model.state.r_prev = r_obs
            self.mdac_corrections += 1
            return
        i_fc = abs(float(fb.get("I_fc") or 0.0))
        i_bt = abs(float(fb.get("I_batt") or 0.0))
        tot = i_fc + i_bt
        # Only where BOTH channels conduct and the loop is closed does the
        # measured split identify the applied ratio; below the release threshold
        # the split is whatever stood, which the model already carries.
        if tot > GOV_ENTRY_A and i_fc > 0.0 and i_bt > 0.0:
            r_obs = i_fc / tot
            if abs(r_obs - self.model.state.r_prev) > 0.05:
                self.mode_mismatch += 1
            self.model.state.r_prev = r_obs
            self.current_corrections += 1

    def tick_to(self, t, share, fb, charging=False, max_ticks=200):
        """Advance the model to ``t`` at 1 kHz on the HELD feedback sample."""
        if self.last_t is None:
            self.last_t = float(t)
            return
        n = int(round((float(t) - self.last_t) / self.tick_s))
        if n <= 0:
            self.last_t = float(t)
            return
        n = min(n, max_ticks)
        i_fc = float(fb.get("I_fc") or 0.0)
        i_bt = float(fb.get("I_batt") or 0.0)
        for k in range(n):
            ts = self.last_t + k * self.tick_s
            sw_fc = True
            sw_bt = not charging
            self.model.step(share, i_fc, i_bt, sw_fc, sw_bt, ts,
                            charge_path_owns_bt=charging)
            self.ticks += 1
        self.last_t = float(t)


# ─────────────────────────────────────────────────────────────────────────────
# The strategy.
# ─────────────────────────────────────────────────────────────────────────────
class MpcStrategy:
    """Governor-aware receding-horizon EMS.  Same surface as ``SdpStrategy``.

    ``bind_scenario(scenario, meta)``, ``reset()``, ``__call__(t, fb)``,
    ``summary_line()`` and a ``provenance`` attribute, so registration in
    ``hil_plant_sim.EMS_STRATEGIES`` and a branch in ``ems_walk._instantiate()``
    are the whole plumbing (see the design document's registration section).

    ``variant`` is ``"det"`` (exact preview) or ``"sto"`` (the TPM's conditional
    mean, with the overcurrent bound at the 90 % quantile)."""

    def __init__(self, name="mpc-det", variant="det", horizon=HORIZON_N,
                 blocks=MOVE_BLOCKS, share_band=SHARE_BAND_DP,
                 share_levels=SHARE_LEVELS, terminal_price_mode="metric",
                 budget_ms=BUDGET_MS_DEFAULT,
                 roll_budget_ms=ROLL_BUDGET_MS_DEFAULT,
                 h2_map="proxy", h2_convex=None, dv0_v=0.0,
                 soc_ref_offset=0.0, eta_chg=chg_mod.ETA_CHG_DEFAULT,
                 tpm_path=None, preview_dt_s=PREVIEW_DT_S):
        if variant not in ("det", "sto"):
            raise ValueError("variant must be 'det' or 'sto'")
        self.name = name
        self.variant = variant
        self.horizon = int(horizon)
        self.blocks = tuple(blocks)
        self.share_band = (float(share_band[0]), float(share_band[1]))
        self.share_levels = int(share_levels)
        self.terminal_price_mode = terminal_price_mode
        self.budget_ms = float(budget_ms)
        self.roll_budget_ms = float(roll_budget_ms)
        self.h2_map = h2_map
        self.h2_convex = h2_convex
        self.dv0_v = float(dv0_v)
        self.soc_ref_offset = float(soc_ref_offset)
        self.eta_chg = chg_mod.check_eta_chg(eta_chg)
        self.preview_dt_s = float(preview_dt_s)
        self.tpm_path = tpm_path
        self.tpm = None
        self.tpm_edges = None
        self.tpm_map_w = (0.0, 25.0)     # sdp_ems_solver.DEMAND_MAP_DEFAULT_W
        self.provenance = None
        self.scenario = None
        self.meta = None
        self.preview = None
        self.planner = None
        self.reset()

    # -- lifecycle ----------------------------------------------------------
    def reset(self):
        """Per-RUN state.  The bound scenario and preview are NOT run state and
        survive, exactly as ``SdpStrategy`` keeps its loaded artifact."""
        sim = _load_sim()
        self.soc_ref = None
        self.last_t = None
        self.next_decision_t = None
        self.decisions = 0
        self.last_share = sim.SOC_BAND_SHARE_NOMINAL
        self.last_goal = 0.0
        self.latch = ChargeLatch()
        self.shadow = ShadowGovernor(dv0_v=self.dv0_v,
                                     seed_r=sim.SOC_BAND_SHARE_NOMINAL)
        self.roll_job = None
        self.r_hold = {}
        self.budget_hits = 0
        self.incumbent_retained = 0
        self.solve_ms_last = 0.0
        self.solve_ms_max = 0.0
        self.solve_ms_all = []
        self.share_pred = None
        self.share_pred_err = None
        self.share_pred_err_max = 0.0
        self.infeasible_decisions = 0
        self.clamped_bin_high = 0
        self.clamped_bin_low = 0
        if self.planner is not None:
            self.planner.incumbent = None

    def bind_scenario(self, scenario, meta):
        """Build the preview and the planner for one scenario."""
        sim = _load_sim()
        self.scenario = scenario
        self.meta = meta
        self.reset()
        chg_a = sim.dp_chg_ceiling_a(meta)
        run_exit_s = float(sim.SOC_BAND_RUN_EXIT_S
                           if meta.get("ems_run_exit_s") is None
                           else meta["ems_run_exit_s"])
        duration = float(meta["duration_s"])
        dt = self.preview_dt_s
        n = int(round(duration / dt)) + 1
        times = [k * dt for k in range(n)]
        v, a, p_dem, v_bus, i_total, cruise = build_demand(scenario, meta,
                                                           times, dt)
        v_pack_ref = (None if self.eta_chg is None
                      else pack_charge_voltage(0.7, chg_a))
        chg_ok = charge_mask(times, p_dem, v_bus, cruise, chg_a, run_exit_s,
                             self.eta_chg, v_pack_ref)
        self.preview = Preview(times=times, p_dem=p_dem, v_bus=v_bus,
                               i_total=i_total, cruise=cruise, chg_ok=chg_ok,
                               dt=dt)
        self.run_exit_s = run_exit_s
        self.chg_a = chg_a
        self.planner = Planner(horizon=self.horizon, blocks=self.blocks,
                               share_band=self.share_band,
                               share_levels=self.share_levels,
                               terminal_mode=self.terminal_price_mode,
                               budget_ms=self.budget_ms, eta_chg=self.eta_chg,
                               chg_a=chg_a,
                               cap_as=BATT_CAPACITY_AH * 3600.0,
                               h2_map=self.h2_map, h2_convex=self.h2_convex)
        if self.variant == "sto":
            self._load_tpm()
        self.provenance = self._provenance()
        return self.provenance

    def _load_tpm(self):
        path = self.tpm_path
        if path is None:
            path = os.path.join(os.path.dirname(_TOOLS), "references", "EMS",
                                "generated", "TPM_dt1_hil.mat")
        self.tpm = load_tpm(path)
        self.tpm_path = path
        n = len(self.tpm)
        # The SDP artifact's own bin edges on the normalized [0, 1] axis, so a
        # measured bus power classifies into the SAME bin sdp-v3 would use.
        self.tpm_edges = [i / float(n) for i in range(n + 1)]

    def _provenance(self):
        """The sidecar's ``config.mpc`` block (adjudication section 2.6)."""
        prov = {
            "variant": self.name,
            "horizon_n": self.horizon,
            "decision_dt_s": DECISION_DT_S,
            "preview_dt_s": self.preview_dt_s,
            "block_lengths": list(self.blocks),
            "share_band": list(self.share_band),
            "share_levels": self.share_levels,
            "ladder": list(self.planner.ladder) if self.planner else None,
            "terminal": {
                "shape": "huber",
                "mode": self.terminal_price_mode,
                "rho_g_per_soc": terminal_price(self.terminal_price_mode),
                "delta_soc": TERMINAL_DELTA_SOC,
                "kappa": SDP_KAPPA,
                "proxy_over_read": PROXY_OVER_READ,
            },
            "terminal_price_mode": self.terminal_price_mode,
            "h2_model": self.h2_map,
            "eta_fc_proxy": ETA_FC_PROXY,
            "eta_chg": self.eta_chg,
            "budget_ms": self.budget_ms,
            "roll_budget_ms": self.roll_budget_ms,
            "soc_ref_offset": self.soc_ref_offset,
            "dv0_v": self.dv0_v,
            "governor_commit": True,
            "preview_source": ("scenario_profile" if self.variant == "det"
                               else "tpm"),
            "levers_soc_per_g": {
                "share_model": LEVER_SHARE_SOC_PER_G,
                "charge_model_eta_era": LEVER_CHG_ETA_SOC_PER_G,
                "charge_model_old_era": LEVER_CHG_OLD_SOC_PER_G,
                "sdp_v3_admission": SDP_V3_ADMISSION_SOC_PER_G,
            },
            "scenario": self.scenario,
            "chg_i_ceiling_a": getattr(self, "chg_a", None),
        }
        if self.h2_map == "convex":
            prov["h2_convex"] = dict(self.h2_convex or {})
        if self.variant == "sto":
            prov["tpm_path"] = self.tpm_path
            prov["tpm_n_bins"] = len(self.tpm) if self.tpm else None
            prov["oc_quantile"] = STO_OC_QUANTILE
            prov["demand_map_w"] = list(self.tpm_map_w)
        return prov

    # -- the stochastic demand path ----------------------------------------
    def _bin_of(self, p_dem_w):
        lo, hi = self.tpm_map_w
        x = (float(p_dem_w) - lo) / (hi - lo)
        if x < 0.0:
            x, self.clamped_bin_low = 0.0, self.clamped_bin_low + 1
        elif x > 1.0:
            x, self.clamped_bin_high = 1.0, self.clamped_bin_high + 1
        n = len(self.tpm_edges) - 1
        i = bisect.bisect_right(self.tpm_edges, x) - 1
        return 0 if i < 0 else (n - 1 if i >= n else i)

    def _tpm_forecast(self, b0):
        """``(mean_w[k], quantile_w[k])`` for k = 1..horizon.

        The mean is the certainty-equivalent demand path; the quantile is the
        90 % point of the k-step bin distribution, which the overcurrent bound
        is judged against (adjudication section 2.5)."""
        n = len(self.tpm)
        lo, hi = self.tpm_map_w
        centres = [lo + (hi - lo) * (i + 0.5) / n for i in range(n)]
        p = [0.0] * n
        p[b0] = 1.0
        means, quants = [], []
        for _ in range(self.horizon):
            q = [0.0] * n
            for i in range(n):
                pi = p[i]
                if pi == 0.0:
                    continue
                row = self.tpm[i]
                for j in range(n):
                    if row[j]:
                        q[j] += pi * row[j]
            p = q
            means.append(sum(p[i] * centres[i] for i in range(n)))
            acc = 0.0
            qb = n - 1
            for i in range(n):
                acc += p[i]
                if acc >= STO_OC_QUANTILE:
                    qb = i
                    break
            quants.append(centres[qb])
        return means, quants

    # -- one decision -------------------------------------------------------
    def decide(self, t, fb):
        """One decision.  Returns ``(share, goal)`` and updates diagnostics."""
        sim = _load_sim()
        soc = fb.get("soc")
        if soc is None:
            # No state-of-charge term.  The SoC axis is the whole controlled
            # state, so rather than invent a reference the strategy holds the
            # nominal split - the same honest degradation SocBandStrategy and
            # SdpStrategy apply.
            self.last_share = sim.SOC_BAND_SHARE_NOMINAL
            self.last_goal = 0.0
            return self.last_share, self.last_goal
        soc = float(soc)
        if self.soc_ref is None:
            self.soc_ref = soc - self.soc_ref_offset

        prev = self.preview
        k0 = prev.index(t)
        pre = precompute_stages(prev, k0, self.horizon,
                                mode_seed=(STAGE_CLOSED if self.shadow.closed
                                           else STAGE_OPEN))

        # The stochastic variant replaces the previewed demand with the TPM's
        # conditional mean and tightens the overcurrent bound to the quantile.
        i_tot_oc = None
        if self.variant == "sto":
            p_meas = ((fb.get("V_bus") or 0.0)
                      * ((fb.get("I_fc") or 0.0) + (fb.get("I_batt") or 0.0)))
            means, quants = self._tpm_forecast(self._bin_of(p_meas))
            for j in range(pre.n):
                vb = pre.v_bus_mean[j]
                scale = (means[j] / pre.p_dem_mean[j]
                         if pre.p_dem_mean[j] > 0.0 else 1.0)
                for sub in range(len(pre.p_dem[j])):
                    pre.p_dem[j][sub] *= scale
                    pre.i_tot[j][sub] *= scale
                    pre.lo[j][sub] = (min(0.5, GOV_MINORITY_A / pre.i_tot[j][sub])
                                      if pre.i_tot[j][sub] > 0.0 else 0.5)
                pre.p_dem_mean[j] = means[j]
                pre.i_tot_mean[j] = means[j] / vb if vb > 0.0 else 0.0
            i_tot_oc = [quants[j] / pre.v_bus_mean[j] if pre.v_bus_mean[j] > 0.0
                        else 0.0 for j in range(pre.n)]

        # ── the charge candidates (adjudication section 2.3) ────────────────
        hold = self.latch.status(t, fb)
        latched = self.latch.stages_remaining(t) if hold == "active" else 0
        charge_options = [[False] * pre.n]
        if latched:
            charge_options = [[j < latched for j in range(pre.n)]]
        elif hold != "dropped" and pre.chg_ok[0]:
            dwell = int(round(sim.SDP_CHG_MIN_DWELL_S / DECISION_DT_S))
            opt_dwell = [j < dwell and pre.chg_ok[j] for j in range(pre.n)]
            seg = []
            run = True
            for j in range(pre.n):
                run = run and pre.chg_ok[j]
                seg.append(run)
            # Only offer a segment option that differs from the 8 s one, and
            # never one shorter than the dwell the latch will impose anyway.
            charge_options.append(opt_dwell)
            if sum(seg) > dwell:
                charge_options.append(seg)

        # ── the sliced transition rolls ────────────────────────────────────
        if self.roll_job is None or self.roll_job.done:
            self.roll_job = RollJob(pre, self.planner.ladder, dv0_v=self.dv0_v,
                                    charge_stage=lambda j, o=charge_options[-1]: o[j])
        if self.roll_job.advance(self.roll_budget_ms * 1e-3):
            self.r_hold = self.roll_job.table
            self.roll_job = None

        dec = self.planner.solve(soc, self.soc_ref, pre, self.r_hold,
                                 self.shadow.r, charge_options,
                                 i_tot_oc=i_tot_oc)
        self.decisions += 1
        self.solve_ms_last = dec.solve_ms
        self.solve_ms_all.append(dec.solve_ms)
        self.solve_ms_max = max(self.solve_ms_max, dec.solve_ms)
        if dec.budget_hit:
            self.budget_hits += 1
        if not dec.feasible:
            self.infeasible_decisions += 1
        if dec.share == self.last_share and dec.charge == (self.last_goal > 0.0):
            self.incumbent_retained += 1

        # Predicted delivered share of the stage about to run, scored against
        # the delivered share measured at the NEXT decision.
        self.share_pred = dec.share_pred

        share = dec.share
        goal = sim.SOC_BAND_CHARGE_GOAL if dec.charge else 0.0
        if hold == "active":
            goal = sim.SOC_BAND_CHARGE_GOAL
        elif hold == "dropped":
            goal = 0.0
        elif goal > 0.0:
            self.latch.arm(t, fb.get("v_profile"))
        self.last_share = share
        self.last_goal = goal
        return share, goal

    # -- the 50 Hz surface --------------------------------------------------
    def __call__(self, t, fb):
        sim = _load_sim()
        if self.preview is None:
            raise RuntimeError(
                "%s was called without bind_scenario(): the prediction model "
                "IS the scenario's demand preview, and there is no honest "
                "default for it" % self.name)
        if self.last_t is not None and t < self.last_t:
            self.reset()            # rewind => a new run, not this one's tail
        self.last_t = t

        v_sp = fb.get("v_profile")
        if v_sp is None:
            v_sp = sim.EMS_DEFAULT_CRUISE_MPS

        charging = self.last_goal > 0.0
        # The shadow governor is the committed state: it is ticked at 1 kHz on
        # the held feedback, then corrected from this sample.
        self.shadow.tick_to(t, self.last_share, fb, charging=charging)
        self.shadow.observe(fb)

        # The prediction error of the LAST decision, measured now.
        if self.share_pred is not None:
            i_fc = abs(float(fb.get("I_fc") or 0.0))
            i_bt = abs(float(fb.get("I_batt") or 0.0))
            tot = i_fc + i_bt
            if tot > GOV_MIN_LOAD_A and not charging:
                self.share_pred_err = abs(self.share_pred - i_fc / tot)
                self.share_pred_err_max = max(self.share_pred_err_max,
                                              self.share_pred_err)

        if self.next_decision_t is None or t >= self.next_decision_t:
            self.decide(t, fb)
            # Anchor on `t`: a late call must not accumulate a backlog of missed
            # stages to fire back to back (SdpStrategy's own reasoning).
            self.next_decision_t = t + DECISION_DT_S

        in_run = sim.EMS_RUN_ENTRY_S <= t < sim.ems_run_exit(fb, self.run_exit_s)
        if not in_run and self.latch.hold_until is not None:
            self.latch._drop("outside the Run window")
        return {
            "mode_cmd": sim.MODE_HYBRID if in_run else sim.MODE_SAFE,
            "power_share_setpoint": self.last_share,
            "v_setpoint": v_sp,
            "charge_goal": self.last_goal if in_run else 0.0,
        }

    # -- reporting ----------------------------------------------------------
    def timing(self):
        """Decision-timing statistics for the sidecar's finalize block."""
        if not self.solve_ms_all:
            return {"solve_ms_median": None, "solve_ms_max": None,
                    "decisions": 0, "budget_hits": 0}
        xs = sorted(self.solve_ms_all)
        n = len(xs)
        med = xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])
        return {"solve_ms_median": med, "solve_ms_max": xs[-1],
                "decisions": n, "budget_hits": self.budget_hits}

    def summary_line(self):
        if not self.decisions:
            return None
        tm = self.timing()
        return ("[hil] " + self.name + ": %d decisions, solve %.2f ms median / "
                "%.2f ms max, budget expired on %d (%.1f %%) — an expiry returns "
                "the shifted incumbent, which is feasible and was validated one "
                "second earlier, so a nonzero count is a WARNING about the "
                "search depth and not about the command; incumbent retained on "
                "%d; share prediction error max %.4f (predicted minus delivered "
                "stage share, charge windows excluded — the claim this strategy "
                "makes, reported as a level); shadow governor %d ticks, %d MDAC "
                "corrections, %d current-derived corrections, %d mode "
                "mismatches; charge dwell latches %d, early drops %d%s; "
                "terminal price %s = %.6f g/SoC in the eta_fc %.2f proxy basis; "
                "preview %s%s"
                % (self.decisions, tm["solve_ms_median"], tm["solve_ms_max"],
                   self.budget_hits,
                   100.0 * self.budget_hits / self.decisions,
                   self.incumbent_retained, self.share_pred_err_max,
                   self.shadow.ticks, self.shadow.mdac_corrections,
                   self.shadow.current_corrections, self.shadow.mode_mismatch,
                   self.latch.holds, self.latch.drops,
                   ("" if self.latch.drop_reason is None
                    else " (last: %s)" % self.latch.drop_reason),
                   self.terminal_price_mode,
                   terminal_price(self.terminal_price_mode), ETA_FC_PROXY,
                   ("the scenario profile — ⚠️ PREVIEW, NOT CAUSAL"
                    if self.variant == "det" else "the demand TPM (causal)"),
                   ("" if self.variant != "sto" else
                    "; demand bin clamped HIGH on %d and LOW on %d"
                    % (self.clamped_bin_high, self.clamped_bin_low))))


def make_mpc(name="mpc-det", **kwargs):
    """Factory used by the registration step.  ``mpc-sto`` selects the variant."""
    variant = "sto" if name.endswith("sto") else "det"
    return MpcStrategy(name=name, variant=variant, **kwargs)
