#!/usr/bin/env python3
"""gen_dp_ems_table.py — offline dynamic-programming benchmark EMS table generator.

╔═══════════════════════════════════════════════════════════════════════════╗
║ ⚠️  NON-CAUSAL / OFFLINE-OPTIMAL BENCHMARK — NOT A CONTROLLER            ║
║                                                                           ║
║ What this script produces is a TIME-INDEXED SETPOINT TABLE computed with  ║
║ perfect foreknowledge of the entire drive cycle and the entire auxiliary  ║
║ load.  Played back by the `dp-replay` EMS strategy it is a LOWER BOUND    ║
║ REFERENCE that causal strategies (`hold-5050`, `soc-band`) can be ranked  ║
║ against.  It is not implementable on the Raspberry Pi, it does not react  ║
║ to anything, and it is meaningless against any profile or load other than ║
║ the one it was generated for.                                             ║
╚═══════════════════════════════════════════════════════════════════════════╝

Provenance.  The STRUCTURE is ported from the PhD student's MATLAB FCHEV study
(references/EMS/DPtrial.m, references/EMS/DP_EnergyManagement2.m): backward Bellman
induction over a state-of-charge grid with a fuel-cell power control, a
hydrogen stage cost, a running SoC-deviation penalty and a heavy terminal
charge-sustaining penalty.  Nothing NUMERIC is imported from it — the MATLAB is
a 106 kW vehicle and this is a bench rig.

════════════════════════════════════════════════════════════════════════════
DECLARED PORT DECISIONS  (each one FIXES a defect rather than reproducing it)
════════════════════════════════════════════════════════════════════════════

D1. LINEAR INTERPOLATION of J(:, k+1) at SOC_next.
    DP_EnergyManagement2.m:39 snaps SOC_next to the NEAREST grid index
    (`[~, idx] = min(abs(SOC_grid - SOC_next))`).  On its own grid one stage
    moves SoC by ~1e-5 while the grid spacing is 2e-4, so ~99 % of realistic
    transitions quantize to "no change at all" and the cost-to-go carries no
    information about the control's SoC consequence.  Here J(:, k+1) is
    LINEARLY INTERPOLATED at the continuous SOC_next (np.interp), and
    transitions that leave the grid window are marked INFEASIBLE rather than
    clamped to an edge value.

D2. The ARGMIN POLICY IS STORED in the backward pass.
    DP_EnergyManagement2.m:61-95 re-solves the entire minimisation in the
    forward pass, duplicating :23-53 — two copies of one rule that can drift
    apart, and an O(N*m) cost paid twice.  Here the backward pass stores
    `Uopt[n_soc, N]` (int16 control index) and the forward pass is a table
    lookup at the continuous SoC.

D3. INFEASIBILITY RAISES.
    DP_EnergyManagement2.m:64-96 initialises `best_u = 0` and, if no control
    is feasible at a state, silently COMMANDS P_fc = 0 — handing the whole
    demand to the battery, which is exactly the limit the feasibility test was
    protecting.  Here the FORWARD pass raises `DpInfeasible` if the state it
    has reached has no feasible control, or if its interpolated cost-to-go is
    not finite.  (Backward-pass states at the very edge of the SoC window CAN
    legitimately be all-infeasible; that is normal, is not an error, and
    propagates as +inf.  The window is sized from a reachability walk with
    margin — see D8 — so the optimal path never runs against it.)

D4. STAGE COST uses the Gfc DC GAIN, not the MATLAB's static proxy.
        W_H2 = GFC_DC_GAIN * P_fc_stack * dt        [g]
    GFC_DC_GAIN = H2_GFC_DC_GAIN_GPS_PER_W = 1.7637602179836514e-05 g/s/W is
    IMPORTED from hil_plant_sim.py, so this objective and the simulator's
    logged `h2_cum_g` column are the same model and compare directly at steady
    state.  DPtrial.m:43 instead uses `P_fc/(0.55*120000)` = 1.5152e-05 g/s/W;
    the two disagree by +16.4 % (the Gfc DC gain implies eta = 47.25 % where
    the same script assumes 55 %).  ⚠️ EVERY hydrogen number this script
    prints or writes inherits the H2Consumption banner in hil_plant_sim.py.
    Per the operator ruling of 2026-08-31 that model is SCALE-PORTABLE — its
    input (P_fc, W) and output (g/s) both ride the system's energy scaling
    factor, per references/Systemic_Scaling_of_Powertrain_Models_with_Youla_
    Driver_Control.pdf — so these grams are the MODEL'S ESTIMATE of hydrogen
    mass, not merely a relative index.  The surviving caveat is that the
    coefficients are NOT identified against this rig's stack, TODO(calibrate);
    strategy RANKINGS on the same rig are robust regardless.

    Only the DC gain is used, not the 4-state discretization: the DP stage is
    dt = 0.1 s against a dominant Gfc time constant of 0.2212 s, so the
    transient is NOT resolved at this stage length.  Consequence, stated: the
    DP's predicted total is a steady-state-equivalent figure and will differ
    from the simulator's dynamically-integrated `h2_cum_g` by the transient
    contribution at each load step (small — the cycle has few steps and each
    settles in ~1 s).

D5. RUNNING AND TERMINAL PENALTIES ARE RE-NORMALISED, and the running one is
    dt-SCALED.
        stage    += LAMBDA_DEV  * |SOC_next - SOC0| * dt      [g]
        terminal  = LAMBDA_TERM * |SOC_N    - SOC0|           [g]
    The MATLAB's absolute 50 / 1e4 do not transfer (they are balanced against
    a 106 kW hydrogen term); only the ~200:1 terminal-to-stage RATIO does.
    Multiplying the running penalty by dt makes the tuning dt-INVARIANT, which
    the MATLAB's is not.  Both are in GRAMS so the trade-off is legible:
    LAMBDA_TERM = 1.0 g per unit SoC means "1 unit of SoC deviation at the end
    is worth 1 gram of hydrogen".  See --lambda-dev / --lambda-term.

D6. SOC DYNAMICS ARE THE SIMULATOR'S, NOT THE MATLAB'S LOSSLESS MODEL.
    DP_EnergyManagement2.m:33-36 uses a constant Em = 720 V and I = P/Em, i.e.
    a lossless linear pack.  OPERATOR RULING: match the plant.  This script
    copies hil_electrical.py's BatterySource (lines 489-554): the 9-point
    LIPO_OCV per-cell table, BATT_CELLS = 2, the SoC-dependent rs(), and the
    coulomb count `soc -= i*dt/capacity_as`.  That makes the problem
    NONLINEAR in the state — a DECLARED DIVERGENCE from the MATLAB.
    Two reductions inside that, both stated:
      (a) the pack current is found from the bus-side battery power by ONE
          Picard iteration on the terminal voltage,
              i0 = P_bt/(ETA_BOOST*OCV) ; V1 = OCV - i0*rs ; i = P_bt/(ETA_BOOST*V1)
          (residual < 0.05 % at this rig's ~1.8 A pack current);
      (b) the RC pair (BATT_R1 0.020 ohm, BATT_C1 200 F, tau ~4 s) is NOT
          modelled.  Its steady contribution is i*R1 ~ 0.036 V on a ~7.7 V
          terminal, i.e. ~0.5 % on the pack current.

D7. DEMAND IS DERIVED FROM THE SCENARIO, READ FROM hil_plant_sim.py.
    Nothing about the profile or the drain load is hand-copied: the scenario
    entry, `SOC_BAND_DRAIN_*`, `SOC_LOAD_RAMP_S`, `I_AUX_A`, `ETA_BOOST`,
    `M_EFF`/`K_F`/`F_COULOMB`/`B_EFF` and the droop constants are all IMPORTED
    at generation time.  If the scenario is retuned, regenerating the table
    picks the change up and the fingerprint (D9) changes with it.

D8. GRIDS ARE SIZED TO WHAT THE RUN CAN ACTUALLY TRAVERSE.
    The MATLAB's 0.55-0.65 x 500 window (2e-4 spacing) is a vehicle window; a
    61 s run on this rig moves SoC by ~1e-4 /s, i.e. ~6e-3 over the whole
    cycle.  Here the window is computed from a REACHABILITY WALK (the two
    extreme policies: all-battery, and all-fuel-cell-plus-charge-whenever-
    admitted), then padded — see SOC_WINDOW_PAD_FRAC.  Default spacing 5e-6 is
    ~1/2 of one stage's SoC step, so a stage transition always lands strictly
    inside a grid cell and D1's interpolation is doing real work.

D9. THE TABLE IS PINNED TO ITS PROFILE.
    The header carries `profile_fingerprint`, a sha256 over the scenario name,
    its speed profile and its drain constants, computed by
    `hil_plant_sim.dp_profile_fingerprint()` — ONE function, used by this
    generator and by the `dp-replay` strategy's loader.  The strategy REFUSES
    to run when the active scenario's fingerprint does not match the table's.

D10. CHARGING IS A DISCRETE SECOND CONTROL, MASKED BY THE PROFILE.
    The MATLAB lets P_batt go negative continuously.  On this board a negative
    pack current can only come from the Ag105, which needs `FC_CHARGE_ENABLE`
    open — and `assertFcChargeEnable()` (.ino:10046) drops BT off the bus, so
    the whole load plus the charger lands on the FC channel against
    LIMIT_I_FC_MAX 1.4 A.  Charging is therefore modelled as ONE extra control
    column (charge_goal = 1, pack current = -chg_i_ceiling_a) admitted only
    where a per-stage FEASIBILITY MASK allows it:
      * inside the Run window, and
      * a CRUISE region of the profile — |dv/dt| <= SOC_BAND_CRUISE_SLOPE_MAX
        and v >= SOC_BAND_CRUISE_MIN_MPS — never during acceleration
        (OPERATOR RULING (b), 2026-08-30), and
      * the single-source FC budget holds: P_dem/V_bus + chg_i_ceiling_a
        <= LIMIT_I_FC_MAX.
    Precedent for windowing a charge intent off the profile: `ems_regen_harvest`
    in hil_plant_sim.py asserts charge_goal only inside EMS_REGEN_BRAKE_WINDOWS,
    which are likewise read off the scenario's own ems_v_profile.

D11. THE CHARGER'S ENERGY IS ACCOUNTED TWO WAYS, AND THE OBJECTIVE PICKS ONE.
    In the simulator's SIMPLE electrical mode the Ag105's input draw is NOT
    stamped on the bus (Plant.step's `i_total = i_motor + i_aux`), so a charge
    window costs the fuel cell nothing in the logged `h2_cum_g`; in HI-FI mode
    it IS stamped (hil_electrical.py:1474, `J[N_CHG] -= i_charge`).  Both
    totals are always computed and always reported:
        h2_g_physical            — the charger's bus draw charged to the FC.
                                   The PHYSICALLY correct figure, and the one
                                   comparable to a HI-FI run's h2_cum_g.
        h2_g_simple_plant_equiv  — the charger's draw omitted.  The figure
                                   comparable to a SIMPLE-mode run's h2_cum_g.
    --charger-accounting selects WHICH ONE THE DP MINIMISES.  A benchmark's job
    is to LOWER-BOUND the metric that will actually be MEASURED, so the setting
    must match the electrical engine the table will be replayed under, and
    getting it wrong is not cosmetic:

      * `physical` (DEFAULT) — for `--electrical hifi`.  run_hil_suite.py's
        `--electrical-pref` defaults to hifi and the `ems-dp-replay` scenario
        declares `"electrical": "any"`, so THIS is what a default campaign
        runs.  Measured on this cycle: the DP never opens the charger path at
        all, because shifting the split toward the fuel cell buys 0.405 SoC per
        gram against the charger's 0.169 — charging is simply the worse lever
        at this rig's numbers.  Result: 14.3 % below the causal `soc-band`
        strategy at matched terminal SoC.
      * `simple` — for `--electrical simple`.  There the plant does not stamp
        the charger's draw on the bus, so the logged metric gives away pack
        charge for free.  A `physical` table replayed against that accounting
        is not a bound at all: the causal `soc-band` strategy BEATS it on the
        logged column (measured 1.042e-2 g vs 1.057e-2 g), purely because
        soc-band charges and the metric does not charge it for doing so, and a
        reference the referent can beat is worse than no reference.  Under
        `simple` the DP charges on every stage the mask admits — which is an
        artefact of the simple-mode bus model, NOT an energy-management
        insight, and must not be read as "the optimal charging policy".

════════════════════════════════════════════════════════════════════════════
COMPARING THE RESULT TO A CAUSAL STRATEGY
════════════════════════════════════════════════════════════════════════════
A raw hydrogen comparison between two EMS runs is ONLY valid at matched
terminal SoC: any strategy can burn less hydrogen by discharging the pack
harder.  Two things follow, and both are implemented:

  * The causal `soc-band` strategy is walked through the SAME reduced model
    (on by default; --no-compare-heuristic to skip), so both strategies'
    (h2, delta_soc) pairs are printed together and written into the table's
    `ref_*` header lines.  Read them as a PAIR.

  * MATCHED-TERMINAL-SOC SOLVE (--match-terminal-soc, default `heuristic`).
    The DP does not have one answer; it has a TRADE-OFF CURVE parametrised by
    LAMBDA_TERM.  Comparing an arbitrary point on that curve against a causal
    strategy is not a benchmark — at LAMBDA_TERM = 1.0 the DP measurably ends
    7e-4 SoC HIGHER than `soc-band` and 15.8 % higher in hydrogen, which says
    nothing about either policy.  So the generator BISECTS LAMBDA_TERM (a
    monotone, discrete-stepped map to terminal SoC) until the DP's terminal
    SoC equals the causal strategy's within --match-tol, and ships that point.
    There, and only there, the hydrogen difference is the answer to "how much
    did the causal strategy leave on the table?".  The solved weight and the
    residual are recorded in the table header.

Usage:
    C:/Users/ricky/miniforge3/python.exe tools/gen_dp_ems_table.py
    C:/Users/ricky/miniforge3/python.exe tools/gen_dp_ems_table.py --force

Requires numpy (miniforge; `.venv_hil` is stdlib-only and is the SIMULATOR's
interpreter, not this one).  This script is OFFLINE tooling: nothing in the
1 kHz simulator loop imports it.
"""

import argparse
import hashlib
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
REPO_ROOT = os.path.dirname(_HERE)

import hil_plant_sim as sim                                        # noqa: E402
from hil_electrical import (                                       # noqa: E402
    LIPO_OCV_SOC, LIPO_OCV_V, BATT_CELLS, BATT_RS_NOM, BATT_CAPACITY_AH)


# ─────────────────────────────────────────────────────────────────────────────
# Constants this script owns.  Everything else is imported (D7).
# ─────────────────────────────────────────────────────────────────────────────

# .ino LIMIT_I_FC_MAX — the fuel-cell channel overcurrent limit the firmware
# faults on.  Not exposed as a Python constant anywhere in tools/, so it is
# restated here with its citation rather than imported.  Every FC-side
# feasibility test below is against this value.
LIMIT_I_FC_MAX_A = 1.4

# ── Share control authority ─────────────────────────────────────────────────
# The DP's share grid spans EXACTLY the authority the causal `soc-band` policy
# gives itself: SOC_BAND_SHARE_NOMINAL +/- SOC_BAND_SHARE_SPAN = [0.25, 0.75].
# TWO reasons, and the first is a safety one:
#
#  1. NEVER COMMAND THE CUT BAND'S EDGE.  updateShareSetpointCutoff()
#     (.ino:9377-9385, latch .ino:9231-9257) drives a channel's *_BUS_ENABLE
#     LOW for a setpoint outside [DROOP_R_MIN 0.15, DROOP_R_MAX 0.85].  An
#     unconstrained DP happily sits at 0.15 and 0.85 — measured, before this
#     band was applied — i.e. exactly ON the boundary, where a float
#     round-trip through the 22-byte command packet decides whether the cut
#     fires.  Exercising that latch is `handoff-sag`'s job; this scenario must
#     never trip it, so the span stops 0.10 short of both rails, which is the
#     same margin and the same reasoning SOC_BAND_SHARE_SPAN records.
#  2. EQUAL ACTUATOR AUTHORITY.  A benchmark that is allowed a wider split
#     range than the strategy it bounds is not measuring the POLICY, it is
#     measuring the range.  Same band, same limits, so the difference is the
#     decision rule alone.
#
# FC-current budget at the widest point: 0.75 x the drain phase's 1.462 A bus
# total = 1.10 A, 22 % under LIMIT_I_FC_MAX — the `ems-soc-band` entry's own
# budget, unchanged.
DP_SHARE_MIN = sim.SOC_BAND_SHARE_NOMINAL - sim.SOC_BAND_SHARE_SPAN
DP_SHARE_MAX = sim.SOC_BAND_SHARE_NOMINAL + sim.SOC_BAND_SHARE_SPAN

# The share value written into the table for a CHARGING stage.  With
# FC_CHARGE_ENABLE open the firmware has already dropped BT off the bus
# (assertFcChargeEnable(), .ino:10046), so the share loop has no minority
# channel to apportion and the commanded value is informational.  It is set to
# DP_SHARE_MAX rather than 1.0 so that IF the charge path fails to open and
# both channels are in fact still on the bus, the command is still an ordinary
# in-band split and cannot trip the cut.
DP_CHARGE_SHARE = DP_SHARE_MAX

# Headroom kept on LIMIT_I_FC_MAX when admitting a charge stage.  0.85 -> the
# single-source FC total (load + charger) must stay at or under 1.19 A, i.e.
# 15 % below the fault limit.  This is not decoration: the `ems-soc-band`
# scenario's own SOC_BAND_DRAIN_END_S note records a case where the residual
# drain let a charge window open at a 1.42 A single-source total, OVER the
# 1.4 A limit, and the fix there was to move the load rather than to trust an
# exact-limit test.  The same discipline is applied here, and it lands the
# admitted window on exactly the 1.0 m/s cruise Route 2's scenario designed
# for (0.338 A load + 0.8 A charger = 1.138 A, the 19 % margin that entry
# budgets).  A further reason for headroom: the charger term is the SIM's
# STAMPED draw (the Ag105 OUTPUT current on the VCHG node, ~1.47x the physical
# input draw), so the test is already conservative and the margin keeps it so.
DP_CHARGE_FC_MARGIN = 0.85

# DP stage length.  0.1 s is 5x the 50 Hz command period, so every table row is
# held for exactly 5 command packets and the ZOH playback introduces no
# sub-stage aliasing; it is also 610 stages over the 61 s scenario, which the
# vectorized backward pass solves in ~2 s.  Finer buys nothing: the profile is
# piecewise-linear with segment lengths of 3-30 s and the plant's slowest
# relevant lag (AG105_TAU_S 0.4 s) is not modelled here anyway.
DP_STAGE_DT_S = 0.1

# SoC grid spacing.  One stage moves SoC by ~1e-5 at this rig's ~1.8 A pack
# current (dt 0.1 s / 18000 As), so 5e-6 puts every transition strictly inside
# a cell and D1's interpolation carries the control's consequence.  Halving it
# doubles memory (int16 policy table) and changes the answer in the 5th digit.
DP_SOC_STEP = 5.0e-6

# Number of share controls, spanning [SOC_BAND_SHARE_MIN, SOC_BAND_SHARE_MAX].
# 41 points = 0.0175 share resolution; at the drain phase's ~1.45 A bus total
# that is 25 mA of FC current per step, well under the share loop's own
# tracking spread (0.503 +/- 0.028 measured, CLAUDE.md 2026-08-17b).
DP_N_SHARE = 41

# Reachability padding (D8): the SoC window is [min, max] of the two extreme
# forward walks, expanded by this fraction of the span on each side (and by at
# least DP_SOC_WINDOW_MIN_PAD).  Padding keeps the +inf edge states away from
# the optimal path, so D1's interpolation never mixes an infeasible edge into
# a live cost.
DP_SOC_WINDOW_PAD_FRAC = 0.35
DP_SOC_WINDOW_MIN_PAD = 20.0 * DP_SOC_STEP

# ── Cost weights (D5), in GRAMS ─────────────────────────────────────────────
# Scale reference for both: the whole 61 s cycle burns ~1e-2 g of (comparative)
# hydrogen and moves SoC by ~5e-3.
#   LAMBDA_TERM 1.0 g/SoC  ->  a 5e-3 terminal deviation costs 5e-3 g, i.e.
#       about HALF the run's entire hydrogen bill.  Charge sustenance is
#       therefore a strong but not absolute pressure, which is the regime the
#       comparison needs: an absolute one would rail the split at
#       SOC_BAND_SHARE_MAX for the whole run and there would be nothing to
#       optimise.
#   LAMBDA_DEV DEFAULTS TO 0.0, and that is a decision, not an omission.
#       ⚠️ ANY NONZERO RUNNING PENALTY BREAKS THE BENCHMARK CLAIM.  The reason
#       this table can be called a LOWER BOUND is a one-line argument: among
#       all trajectories that end at the same terminal SoC, the terminal
#       penalty is IDENTICAL, so minimising (h2 + terminal penalty) is exactly
#       minimising h2.  A RUNNING penalty is not identical across those
#       trajectories — it depends on the whole path — so it re-ranks them, and
#       the DP stops being the minimum-hydrogen trajectory for its own terminal
#       SoC.  MEASURED, at the MATLAB-ratio value 0.05 g/(SoC*s): the
#       SoC-matched DP came out 0.07 % WORSE in hydrogen than the causal
#       `soc-band` strategy it is supposed to bound — a "lower bound" the thing
#       it bounds beats, purely because the DP was being charged 2.9e-3 g of
#       running penalty (a quarter of the run's whole hydrogen bill) that
#       `soc-band` never paid.
#       The MATLAB's structure is nonetheless preserved and reachable:
#       --lambda-dev 0.05 restores the TERMINAL:PER-STAGE ratio
#       1.0 / (0.05*0.1) = 200:1, matching DP_EnergyManagement2.m's 1e4:50 —
#       the one thing in its tuning that IS dimensionless and does transfer.
#       Use it to study SoC-trajectory shaping; do not use it to generate a
#       table anyone will quote as an optimum.
DP_LAMBDA_TERM_G_PER_SOC = 1.0
DP_LAMBDA_DEV_G_PER_SOC_S = 0.0

# --match-terminal-soc bisection bracket and budget.  The bracket spans 8
# decades around the nominal weight, which is wide enough that the endpoints
# are the two DEGENERATE policies (all-battery at the low end, all-fuel-cell
# plus charge-whenever-admitted at the high end) — i.e. the target is bracketed
# for any reachable terminal SoC.  30 geometric bisections narrow 1e8 to a
# factor of 1.0000006, far finer than the discrete control grid can resolve, so
# the loop always exits on the SoC tolerance or the bracket test first.
DP_LAMBDA_TERM_BISECT_RANGE = (1.0e-4, 1.0e4)
DP_LAMBDA_TERM_BISECT_ITERS = 30

# The scenario this generator is written against.  --scenario exists so the
# refusal path is testable, but no other scenario currently carries the drive
# profile + drain-load pair this model needs.
# The scenario a bare `--force` regeneration should target.  It is
# `ems-dp-replay`, NOT `ems-soc-band`: the two share a profile and a drain, so
# the DP solves identically for either, but `ems-dp-replay` is the ONLY
# scenario that CONSUMES a table (DpReplayStrategy loads
# dp_tables/dp_ems_table_<scenario>.csv by the ACTIVE scenario's name).  With
# the old default, a `gen_dp_ems_table.py --force` wrote
# dp_ems_table_ems-soc-band.csv — a file nothing ever reads — and left the
# shipped table stale while reporting success.  Contract review, 2026-08-31.
DP_DEFAULT_SCENARIO = "ems-dp-replay"

# Where the generated table lives.  RATIONALE for tools/dp_tables/ over
# references/: references/ holds EXTERNAL AUTHORITATIVE SOURCES (datasheets,
# the MATLAB study, extracted register tables) that this repository consumes
# but does not produce.  This file is a GENERATED ARTIFACT of a script in
# tools/, regenerated whenever the scenario changes, and read back at runtime
# by tools/hil_plant_sim.py — the same relationship
# controller_design_MIMO/*.csv has to its synthesis scripts.  It belongs next
# to its generator.
DP_TABLE_DIR = os.path.join(REPO_ROOT, "tools", "dp_tables")
DP_TABLE_NAME = "dp_ems_table_%s.csv"


class DpInfeasible(RuntimeError):
    """No feasible control at a state the forward pass actually reached (D3)."""


# ─────────────────────────────────────────────────────────────────────────────
# Pack model (D6) — vectorized copies of hil_electrical.BatterySource's terms.
# ─────────────────────────────────────────────────────────────────────────────
def pack_ocv(soc):
    """Pack open-circuit voltage [V] — BatterySource.ocv(), vectorized.

    np.interp reproduces `_interp`'s clamped piecewise-linear form exactly."""
    return BATT_CELLS * np.interp(soc, LIPO_OCV_SOC, LIPO_OCV_V)


def pack_rs(soc):
    """Pack series resistance [ohm] — BatterySource.rs(), vectorized.

    Flat above SoC 0.15, rising 4x by SoC 0."""
    k = np.where(soc > 0.15, 1.0, 1.0 + 3.0 * (0.15 - soc) / 0.15)
    return BATT_CELLS * BATT_RS_NOM * k


def pack_current_from_bus_power(p_bt_bus_w, soc):
    """Pack-side current [A] for a BUS-SIDE battery power, D6(a).

    Positive = discharge, matching BatterySource's sign convention.  The
    referral is ElectricalSim._source_current()'s, specialised to v_bus > v_batt
    (always true here — a 16 V bus off a 7.4-8.4 V pack):
        i_pack = i_bus * v_bus / (v_batt * ETA_BOOST) = P_bus / (ETA_BOOST * v_batt)
    """
    ocv = pack_ocv(soc)
    rs = pack_rs(soc)
    i0 = p_bt_bus_w / (sim.ETA_BOOST * ocv)
    v1 = np.maximum(ocv - i0 * rs, 1.0)
    return p_bt_bus_w / (sim.ETA_BOOST * v1)


# ─────────────────────────────────────────────────────────────────────────────
# Demand model (D7)
# ─────────────────────────────────────────────────────────────────────────────
def scenario_drain_a(scenario, t):
    """The scenario's bus-side auxiliary load [A] at time t.

    Mirrors apply_scenario()'s `ems-soc-band` branch term for term.  Returns
    I_AUX_A alone for a scenario with no drain."""
    if scenario not in ("ems-soc-band", "ems-dp-replay"):
        return sim.I_AUX_A
    ramp_in = max(0.0, min(1.0, (t - sim.SOC_BAND_DRAIN_START_S) / sim.SOC_LOAD_RAMP_S))
    ramp_out = max(0.0, min(1.0, (t - sim.SOC_BAND_DRAIN_END_S) / sim.SOC_LOAD_RAMP_S))
    return sim.I_AUX_A + sim.SOC_BAND_DRAIN_LOAD_A * (ramp_in - ramp_out)


def build_demand(scenario, meta, times, dt):
    """Per-stage (v, a, P_dem_bus, V_bus, I_total, cruise) arrays.

    MECHANICS (Plant.step's model, without the stiction deadband — the profile
    never dwells inside V_STICTION while commanding force):
        F      = M_EFF*a + F_COULOMB*sgn(v) + B_EFF*v
        p_mech = max(0, F*v)            one-signed, matching Plant.step's floor
                                        (regen is a torque clip on this rig, not
                                        a dump path — CLAUDE.md 2026-08-17b)
    ELECTRICS:
        i_motor = p_mech/(ETA_BOOST*V_bus);  I_total = i_motor + i_aux(t)
        V_bus   = V_BUS_DROOP_V0 - K_DROOP_BUS_SHARED*I_total
    V_bus and i_motor are mutually dependent (a droop node feeding a
    constant-power load).  Solved by 4 Picard iterations from V_BUS_DROOP_V0;
    the iteration contracts by ~K*i/V ~ 0.7 % per step, so 4 is ~1e-8.

    ⚠️ APPROXIMATION, stated: K_DROOP_BUS_SHARED (both sources live) is used at
    EVERY stage, including the charge windows where the firmware has dropped BT
    off the bus and the real droop is K_DROOP_BUS_SINGLE = 0.16 V/A.  At the
    charge window's ~0.34 A that is a 0.03 V difference on a ~15.9 V rail
    (0.2 %), which moves P_dem by 0.2 % — below every other reduction here.
    Using it uniformly keeps the demand INDEPENDENT of the control, which is
    what makes the stage cost separable and the DP tractable.

    `a` is a CENTRAL difference of the profile over one stage, which smooths
    the piecewise-linear corners over dt rather than aliasing them.
    """
    prof = meta.get("ems_v_profile")
    if not prof:
        raise SystemExit("scenario %r defines no ems_v_profile - this generator "
                         "derives its demand from one (D7)" % scenario)
    n = len(times)
    v = np.empty(n)
    a = np.empty(n)
    i_aux = np.empty(n)
    for k, t in enumerate(times):
        v[k] = sim.piecewise(prof, t)
        a[k] = (sim.piecewise(prof, t + 0.5 * dt)
                - sim.piecewise(prof, t - 0.5 * dt)) / dt
        i_aux[k] = scenario_drain_a(scenario, t)

    f_coul = np.where(v > sim.V_STICTION, sim.F_COULOMB,
                      np.where(v < -sim.V_STICTION, -sim.F_COULOMB, 0.0))
    force = sim.M_EFF * a + f_coul + sim.B_EFF * v
    p_mech = np.maximum(0.0, force * v)

    v_bus = np.full(n, sim.V_BUS_DROOP_V0)
    for _ in range(4):
        i_motor = p_mech / (sim.ETA_BOOST * v_bus)
        i_total = i_motor + i_aux
        v_bus = sim.V_BUS_DROOP_V0 - sim.K_DROOP_BUS_SHARED * i_total
    i_motor = p_mech / (sim.ETA_BOOST * v_bus)
    i_total = i_motor + i_aux
    p_dem = v_bus * i_total

    # Cruise mask (D10): the same test the causal `soc-band` policy applies,
    # with the same constants — but evaluated on the profile's own slope rather
    # than on a trailing window, because a table generator HAS the profile.
    cruise = (np.abs(a) <= sim.SOC_BAND_CRUISE_SLOPE_MAX) & \
             (v >= sim.SOC_BAND_CRUISE_MIN_MPS)
    return v, a, p_dem, v_bus, i_total, cruise


def charge_mask(times, p_dem, v_bus, cruise, chg_ceiling_a, run_exit_s):
    """Per-stage boolean: may the DP open the charger path at this stage? (D10)"""
    in_run = (times >= sim.EMS_RUN_ENTRY_S) & (times < run_exit_s)
    # Single-source FC budget: with BT dropped off the bus the FC channel
    # carries the whole load PLUS the charger's stamped draw, against
    # LIMIT_I_FC_MAX with DP_CHARGE_FC_MARGIN of headroom.
    budget_ok = ((p_dem / v_bus + chg_ceiling_a)
                 <= DP_CHARGE_FC_MARGIN * LIMIT_I_FC_MAX_A)
    return in_run & cruise & budget_ok


# ─────────────────────────────────────────────────────────────────────────────
# Forward dynamics shared by the DP, the reachability walk and the heuristic
# reference walk — ONE implementation, so the three cannot disagree.
# ─────────────────────────────────────────────────────────────────────────────
def step_discharge(soc, share, p_dem, v_bus, dt, cap_as):
    """One stage on the split control.  Returns (soc_next, h2_g, h2_plant_g)."""
    p_fc_bus = share * p_dem
    p_bt_bus = p_dem - p_fc_bus
    i_pack = pack_current_from_bus_power(p_bt_bus, soc)
    soc_next = soc - i_pack * dt / cap_as
    h2 = sim.H2_GFC_DC_GAIN_GPS_PER_W * (p_fc_bus / sim.ETA_BOOST) * dt
    return soc_next, h2, h2


def step_charge(soc, p_dem, v_bus, chg_a, dt, cap_as):
    """One stage on the charge control.  Returns (soc_next, h2_g, h2_plant_g).

    D11: `h2_g` charges the fuel cell for the charger energy (the physical
    answer, and what the objective minimises); `h2_plant_g` omits it, which is
    what a SIMPLE-mode simulator run's `h2_cum_g` column will actually show."""
    soc_next = soc + chg_a * dt / cap_as
    p_fc_bus_phys = p_dem + v_bus * chg_a
    h2 = sim.H2_GFC_DC_GAIN_GPS_PER_W * (p_fc_bus_phys / sim.ETA_BOOST) * dt
    h2_plant = sim.H2_GFC_DC_GAIN_GPS_PER_W * (p_dem / sim.ETA_BOOST) * dt
    return soc_next, h2, h2_plant


# ─────────────────────────────────────────────────────────────────────────────
# Reachability walk (D8)
# ─────────────────────────────────────────────────────────────────────────────
def reachable_soc_window(soc0, p_dem, v_bus, chg_ok, dt, cap_as, chg_a,
                         share_lo, share_hi):
    """[lo, hi] SoC bounds over the two extreme admissible policies."""
    lo = hi = soc0
    s = soc0
    for k in range(len(p_dem)):        # all-battery: the deepest discharge
        s, _, _ = step_discharge(s, share_lo, p_dem[k], v_bus[k], dt, cap_as)
        lo = min(lo, s)
    s = soc0
    for k in range(len(p_dem)):        # all-FC + charge whenever admitted
        if chg_ok[k]:
            s, _, _ = step_charge(s, p_dem[k], v_bus[k], chg_a, dt, cap_as)
        else:
            s, _, _ = step_discharge(s, share_hi, p_dem[k], v_bus[k], dt, cap_as)
        hi = max(hi, s)
        lo = min(lo, s)
    return lo, hi


# ─────────────────────────────────────────────────────────────────────────────
# The DP itself
# ─────────────────────────────────────────────────────────────────────────────
def solve_dp(soc0, times, p_dem, v_bus, chg_ok, dt, cap_as, chg_a,
             shares, soc_grid, lam_dev, lam_term, charger_accounting):
    """Backward Bellman induction (D1-D3, D5).

    Controls are indexed 0..m-1 = the share grid, and index m = CHARGE (present
    as a column at every stage, masked infeasible where `chg_ok` is False).

    Returns (J0, Uopt) with Uopt.shape == (n_soc, N), dtype int16.
    """
    n = len(soc_grid)
    m = len(shares)
    n_stages = len(p_dem)
    ctrl_n = m + 1

    ocv = pack_ocv(soc_grid)
    rs = pack_rs(soc_grid)

    J_next = lam_term * np.abs(soc_grid - soc0)
    Uopt = np.empty((n, n_stages), dtype=np.int16)

    soc_col = soc_grid[:, None]
    lo, hi = soc_grid[0], soc_grid[-1]

    for k in range(n_stages - 1, -1, -1):
        P = p_dem[k]
        V = v_bus[k]

        # ── split controls ──────────────────────────────────────────────────
        p_fc = shares * P                      # (m,)
        p_bt = P - p_fc
        i0 = p_bt[None, :] / (sim.ETA_BOOST * ocv[:, None])
        v1 = np.maximum(ocv[:, None] - i0 * rs[:, None], 1.0)
        i_pack = p_bt[None, :] / (sim.ETA_BOOST * v1)
        soc_next = np.empty((n, ctrl_n))
        stage = np.empty((n, ctrl_n))
        soc_next[:, :m] = soc_col - i_pack * dt / cap_as
        stage[:, :m] = sim.H2_GFC_DC_GAIN_GPS_PER_W * (p_fc / sim.ETA_BOOST) * dt

        feas = np.empty((n, ctrl_n), dtype=bool)
        # FC channel current limit, control-wise (state-independent).
        feas[:, :m] = ((p_fc / V) <= LIMIT_I_FC_MAX_A)[None, :]

        # ── charge control ──────────────────────────────────────────────────
        soc_next[:, m] = soc_grid + chg_a * dt / cap_as
        # D11: which bus power the charge stage is billed for.  `physical`
        # charges the FC for the charger's draw; `simple` omits it, mirroring
        # the simple-mode plant's own bus node (and its logged h2_cum_g).
        p_fc_charge = (P + V * chg_a) if charger_accounting == "physical" else P
        stage[:, m] = sim.H2_GFC_DC_GAIN_GPS_PER_W * \
            (p_fc_charge / sim.ETA_BOOST) * dt
        feas[:, m] = bool(chg_ok[k])

        # Transitions off the grid are INFEASIBLE, not clamped (D1).
        feas &= (soc_next >= lo) & (soc_next <= hi)

        stage += lam_dev * np.abs(soc_next - soc0) * dt
        cost = stage + np.interp(soc_next.ravel(), soc_grid,
                                 J_next).reshape(n, ctrl_n)
        cost = np.where(feas, cost, np.inf)

        idx = np.argmin(cost, axis=1)
        Uopt[:, k] = idx.astype(np.int16)
        J_next = cost[np.arange(n), idx]

    return J_next, Uopt


def forward_pass(soc0, times, p_dem, v_bus, chg_ok, dt, cap_as, chg_a,
                 shares, soc_grid, Uopt):
    """Table-lookup rollout at the CONTINUOUS SoC (D2), raising on D3.

    The POLICY lookup is nearest-neighbour on the SoC grid — the control index
    is a discrete argmin and has no meaningful interpolant — but the DYNAMICS
    are applied at the continuous SoC.  The lookup error is bounded by half a
    grid spacing (2.5e-6 SoC), which is a quarter of one stage's own SoC step.
    """
    m = len(shares)
    n_stages = len(p_dem)
    soc = float(soc0)
    soc_traj = np.empty(n_stages + 1)
    soc_traj[0] = soc
    share_out = np.empty(n_stages)
    charge_out = np.zeros(n_stages)
    h2 = 0.0
    h2_plant = 0.0
    lo, hi = soc_grid[0], soc_grid[-1]

    for k in range(n_stages):
        if not (lo <= soc <= hi):
            raise DpInfeasible(
                "forward pass left the SoC window at stage %d (t=%.3f s): "
                "soc=%.8f not in [%.8f, %.8f]. Widen the window "
                "(DP_SOC_WINDOW_PAD_FRAC) or re-check the demand model."
                % (k, times[k], soc, lo, hi))
        i = int(np.abs(soc_grid - soc).argmin())
        u = int(Uopt[i, k])
        if u == m:
            if not chg_ok[k]:
                raise DpInfeasible(
                    "policy selected CHARGE at stage %d (t=%.3f s) where the "
                    "charge mask forbids it - the backward pass and the mask "
                    "disagree" % (k, times[k]))
            soc, dh2, dh2p = step_charge(soc, p_dem[k], v_bus[k], chg_a, dt, cap_as)
            share_out[k] = DP_CHARGE_SHARE
            charge_out[k] = 1.0
        else:
            share = float(shares[u])
            if (share * p_dem[k] / v_bus[k]) > LIMIT_I_FC_MAX_A + 1e-12:
                raise DpInfeasible(
                    "policy selected an FC-overcurrent share at stage %d "
                    "(t=%.3f s): share %.4f x %.3f W / %.3f V = %.4f A > %.2f A"
                    % (k, times[k], share, p_dem[k], v_bus[k],
                       share * p_dem[k] / v_bus[k], LIMIT_I_FC_MAX_A))
            soc, dh2, dh2p = step_discharge(soc, share, p_dem[k], v_bus[k],
                                            dt, cap_as)
            share_out[k] = share
        h2 += dh2
        h2_plant += dh2p
        soc_traj[k + 1] = soc

    return share_out, charge_out, soc_traj, h2, h2_plant


# ─────────────────────────────────────────────────────────────────────────────
# Causal reference walk — the SAME reduced model, driven by `soc-band`
# ─────────────────────────────────────────────────────────────────────────────
def heuristic_walk(scenario, meta, soc0, times, p_dem, v_bus, i_total, dt,
                   cap_as, chg_a, run_exit_s):
    """Walk hil_plant_sim's SocBandStrategy through this script's model.

    The point is a MATCHED-MODEL comparison: the causal policy's hydrogen and
    terminal SoC computed with the identical demand, pack and Gfc terms the DP
    minimised, so any difference between the two is the POLICY and not the
    model.  It is NOT a substitute for running the scenario — the real firmware
    tracks the share command with a loop this model does not have, and the
    Ag105's settle+ramp is not modelled here.

    The policy is called at PiCommander.PI_CMD_HZ, exactly as the simulator
    calls it, and its `charging` output is honoured only where this script's
    own charge mask (D10) also admits it — the policy's own admission test is
    causal and current-based and can differ by a fraction of a second at the
    window edge.
    """
    policy = sim.SocBandStrategy()
    cmd_period = 1.0 / sim.PiCommander.PI_CMD_HZ
    soc = float(soc0)
    h2 = 0.0
    h2_plant = 0.0
    share = sim.SOC_BAND_SHARE_NOMINAL
    charging = False
    next_cmd = 0.0
    band_exit_t = None
    sat_t = None
    charge_t = None
    prof = meta.get("ems_v_profile")

    for k, t in enumerate(times):
        if t >= next_cmd:
            # Feedback view: the keys SocBandStrategy actually reads.
            i_fc = share * i_total[k]
            fb = {"t": t, "v_profile": sim.piecewise(prof, t), "soc": soc,
                  "I_fc": i_fc, "I_batt": i_total[k] - i_fc}
            out = policy(t, fb)
            share = float(out["power_share_setpoint"])
            charging = float(out["charge_goal"]) > 0.0
            next_cmd = t + cmd_period
            if band_exit_t is None and abs(policy.last_deficit) > sim.SOC_BAND_HALF:
                band_exit_t = t
            if sat_t is None and share >= (sim.SOC_BAND_SHARE_NOMINAL
                                           + sim.SOC_BAND_SHARE_SPAN - 1e-9):
                sat_t = t
            if charging and charge_t is None:
                charge_t = t
        if charging and sim.EMS_RUN_ENTRY_S <= t < run_exit_s:
            soc, dh2, dh2p = step_charge(soc, p_dem[k], v_bus[k], chg_a, dt, cap_as)
        else:
            soc, dh2, dh2p = step_discharge(soc, share, p_dem[k], v_bus[k],
                                            dt, cap_as)
        h2 += dh2
        h2_plant += dh2p
    return {"h2_g": h2, "h2_plant_g": h2_plant, "soc_final": soc,
            "band_exit_t": band_exit_t, "sat_t": sat_t, "charge_t": charge_t}


# ─────────────────────────────────────────────────────────────────────────────
# Table emission
# ─────────────────────────────────────────────────────────────────────────────
def default_table_path(scenario):
    return os.path.join(DP_TABLE_DIR, DP_TABLE_NAME % scenario)


def render_table(scenario, meta, args, fingerprint, times, share, charge,
                 predicted, grid_info, heuristic=None):
    """The full table file as one string.  BYTE-DETERMINISTIC: no timestamps,
    no absolute paths, no environment.  The `command` line is RECONSTRUCTED
    from the parsed arguments rather than echoing sys.argv, so regenerating
    from a different working directory produces identical bytes."""
    # REPRODUCIBILITY: `--lambda-term` here is the INPUT value, not the solved
    # one — with --match-terminal-soc active the input is only the bisection's
    # starting point and re-running this exact line re-solves to the same
    # weight.  The solved value is recorded separately as
    # `lambda_term_g_per_soc` below.
    cmd = ("python tools/gen_dp_ems_table.py --scenario %s --soc0 %r "
           "--capacity-ah %r --stage-dt %r --lambda-dev %r --lambda-term %r "
           "--n-share %d --soc-step %r --charger-accounting %s --run-exit %r "
           "--match-terminal-soc %s --match-tol %r"
           % (scenario, args.soc0, args.capacity_ah, args.stage_dt,
              args.lambda_dev, args.lambda_term_input, args.n_share,
              args.soc_step, args.charger_accounting, args.run_exit,
              args.match_terminal_soc, args.match_tol))
    L = []
    A = L.append
    A("# ══════════════════════════════════════════════════════════════════════")
    A("# NON-CAUSAL OFFLINE BENCHMARK — DP-OPTIMAL EMS SETPOINT TABLE")
    A("#")
    A("# GENERATED FILE. Do not hand-edit: regenerate with the command below.")
    A("# Computed with FULL FOREKNOWLEDGE of the drive cycle and the auxiliary")
    A("# load. It is a lower-bound reference for ranking CAUSAL strategies, not")
    A("# a controller, and it is meaningless against any other profile or load.")
    A("# The `dp-replay` strategy REFUSES to run when the active scenario's")
    A("# profile_fingerprint does not match the one recorded here.")
    A("#")
    A("# ⚠️ Every hydrogen figure below inherits the H2Consumption banner in")
    A("# tools/hil_plant_sim.py. The Gfc map is SCALE-PORTABLE (operator ruling")
    A("# 2026-08-31: P_fc in W and the g/s output both ride the system's energy")
    A("# scaling factor), so these grams are the MODEL'S ESTIMATE of hydrogen")
    A("# mass. What they are NOT is identified against this rig's stack —")
    A("# TODO(calibrate). Strategy RANKINGS on the same rig are robust either")
    A("# way; quote an absolute gram figure with the calibration caveat.")
    A("# ══════════════════════════════════════════════════════════════════════")
    A("# command: %s" % cmd)
    A("# generator: tools/gen_dp_ems_table.py")
    A("# scenario: %s" % scenario)
    A("# profile_fingerprint: %s" % fingerprint)
    A("# duration_s: %r" % float(meta["duration_s"]))
    A("# stage_dt_s: %r" % args.stage_dt)
    A("# run_entry_s: %r" % float(sim.EMS_RUN_ENTRY_S))
    A("# run_exit_s: %r" % float(args.run_exit))
    A("#")
    A("# ── model ────────────────────────────────────────────────────────────")
    A("# soc0: %r" % args.soc0)
    A("# capacity_ah: %r" % args.capacity_ah)
    A("# chg_ceiling_a: %r" % float(meta.get("chg_i_ceiling_a", 0.0)))
    A("# gfc_dc_gain_gps_per_w: %r" % sim.H2_GFC_DC_GAIN_GPS_PER_W)
    A("# eta_boost: %r" % sim.ETA_BOOST)
    A("# limit_i_fc_max_a: %r" % LIMIT_I_FC_MAX_A)
    A("# charge_share_value: %r" % DP_CHARGE_SHARE)
    # M2 (review, 2026-08-31): three more imported simulator constants that
    # SHAPE the solution and were previously unrecorded, so a retune of any of
    # them left a stale table indistinguishable from a current one.
    #   share_span       sets the control grid DP_SHARE_MIN/MAX, i.e. the whole
    #                    range of splits the DP is allowed to choose from;
    #   cruise_slope_max } the charge mask's cruise test (D10) — they decide
    #   cruise_min_mps   } which stages may open the charger path at all.
    # DpReplayStrategy.bind_scenario() refuses on any mismatch against the live
    # values; this is the record it checks against.
    A("# share_span: %r" % float(sim.SOC_BAND_SHARE_SPAN))
    A("# cruise_slope_max: %r" % float(sim.SOC_BAND_CRUISE_SLOPE_MAX))
    A("# cruise_min_mps: %r" % float(sim.SOC_BAND_CRUISE_MIN_MPS))
    A("#")
    A("# ── tunables ─────────────────────────────────────────────────────────")
    A("# charger_accounting: %s" % args.charger_accounting)
    A("#   D11 — which of the two hydrogen totals the DP minimised.")
    A("#   'simple'   matches a --electrical simple run's logged h2_cum_g")
    A("#   'physical' matches a --electrical hifi run's")
    A("# lambda_dev_g_per_soc_s: %r" % args.lambda_dev)
    A("# lambda_term_g_per_soc: %.9g" % args.lambda_term)
    A("# match_terminal_soc: %s" % args.match_terminal_soc)
    A("#   When not 'none', lambda_term above is the SOLVED value that lands")
    A("#   the DP's terminal SoC on the target, so the hydrogen comparison")
    A("#   against the causal strategy is made at matched SoC.")
    # M3 (review, 2026-08-31): the MATCH RESULT, recorded in the file rather
    # than only printed.  A reader comparing h2_g_physical against
    # ref_h2_g_physical is making a claim that is ONLY valid at matched
    # terminal SoC, and until now the file gave no way to check whether the
    # bisection actually got there — the evidence lived in the console output
    # of a run nobody kept.  `match_converged: no` marks a table whose
    # comparison must be quoted with the residual alongside it.
    A("# match_target_soc: %s"
      % ("%.9f" % args.match_target_soc
         if args.match_target_soc is not None else "none"))
    A("# match_residual_soc: %s"
      % ("%+.6e" % args.match_residual_soc
         if args.match_residual_soc is not None else "none"))
    A("# match_converged: %s" % args.match_converged)
    A("#   'yes'  the solved terminal SoC is within --match-tol of the target,")
    A("#          so the hydrogen difference against ref_* IS the answer to")
    A("#          'how much did the causal strategy leave on the table?'.")
    A("#   'no'   the closest reachable point missed the tolerance (the control")
    A("#          grid is discrete). Quote match_residual_soc with any")
    A("#          comparison. --allow-unmatched was required to write this.")
    A("#   'n/a'  --match-terminal-soc none: NOT a matched comparison at all.")
    A("# n_share: %d  (control span %r .. %r, inside the share-cut band "
      "%r .. %r)"
      % (args.n_share, float(DP_SHARE_MIN), float(DP_SHARE_MAX),
         float(sim.SOC_BAND_SHARE_MIN), float(sim.SOC_BAND_SHARE_MAX)))
    A("# soc_grid: %d points, %r .. %r, step %r"
      % (grid_info["n"], grid_info["lo"], grid_info["hi"], args.soc_step))
    A("#")
    A("# ── DP-PREDICTED TOTALS (this model, open loop) ───────────────────────")
    A("# h2_g_physical: %.9g" % predicted["h2_g"])
    A("# h2_g_simple_plant_equiv: %.9g" % predicted["h2_plant_g"])
    A("# soc_final: %.9f" % predicted["soc_final"])
    A("# delta_soc: %.9f" % (predicted["soc_final"] - args.soc0))
    A("# charge_stages: %d of %d" % (int(charge.sum()), len(charge)))
    A("# share_min: %.6f" % float(share.min()))
    A("# share_max: %.6f" % float(share.max()))
    if heuristic is not None:
        A("#")
        A("# ── CAUSAL REFERENCE `soc-band`, walked through the SAME reduced ──")
        A("# ── model (NOT a simulator run) — the comparison anchor ───────────")
        A("# ref_h2_g_physical: %.9g" % heuristic["h2_g"])
        A("# ref_h2_g_simple_plant_equiv: %.9g" % heuristic["h2_plant_g"])
        A("# ref_soc_final: %.9f" % heuristic["soc_final"])
    A("# ══════════════════════════════════════════════════════════════════════")
    A("t,power_share_setpoint,charge_goal")
    for t, s, c in zip(times, share, charge):
        A("%.3f,%.6f,%.1f" % (t, s, c))
    return "\n".join(L) + "\n"


# ─────────────────────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Generate the NON-CAUSAL DP-optimal EMS setpoint table "
                    "played back by hil_plant_sim.py's `dp-replay` strategy.")
    ap.add_argument("--scenario", default=DP_DEFAULT_SCENARIO,
                    help="scenario whose ems_v_profile + drain load define the "
                         "demand (default %s)" % DP_DEFAULT_SCENARIO)
    ap.add_argument("--out", default=None,
                    help="output path (default tools/dp_tables/dp_ems_table_<scenario>.csv)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing table (refused otherwise)")
    ap.add_argument("--soc0", type=float, default=0.7,
                    help="initial SoC - MUST match the simulator's --soc0 (default 0.7)")
    ap.add_argument("--capacity-ah", type=float, default=BATT_CAPACITY_AH,
                    help="pack capacity in Ah (default %g)" % BATT_CAPACITY_AH)
    ap.add_argument("--stage-dt", type=float, default=DP_STAGE_DT_S,
                    help="DP stage length in s (default %g)" % DP_STAGE_DT_S)
    ap.add_argument("--soc-step", type=float, default=DP_SOC_STEP,
                    help="SoC grid spacing (default %g)" % DP_SOC_STEP)
    ap.add_argument("--n-share", type=int, default=DP_N_SHARE,
                    help="share control-grid points (default %d)" % DP_N_SHARE)
    ap.add_argument("--lambda-dev", type=float, default=DP_LAMBDA_DEV_G_PER_SOC_S,
                    help="running SoC-deviation weight, g per SoC per s "
                         "(default %g)" % DP_LAMBDA_DEV_G_PER_SOC_S)
    ap.add_argument("--lambda-term", type=float, default=DP_LAMBDA_TERM_G_PER_SOC,
                    help="terminal SoC-deviation weight, g per SoC "
                         "(default %g)" % DP_LAMBDA_TERM_G_PER_SOC)
    ap.add_argument("--match-terminal-soc", default="heuristic",
                    help="make the comparison fair on the SoC axis by solving "
                         "for the LAMBDA_TERM that lands the DP's terminal SoC "
                         "on a target: 'heuristic' (default - the causal "
                         "`soc-band` walk's own terminal SoC), 'none' (use "
                         "--lambda-term as given), or an explicit SoC value. "
                         "See the MATCHED-TERMINAL-SOC note in the module "
                         "docstring.")
    ap.add_argument("--allow-unmatched", action="store_true",
                    help="write the table even when the matched-terminal-SoC "
                         "bisection did NOT reach --match-tol. Refused by "
                         "default: an unmatched table's hydrogen figure is not "
                         "comparable to the causal reference, which is the "
                         "table's whole purpose (M3, 2026-08-31). The header "
                         "then records match_converged: no and the residual.")
    ap.add_argument("--match-tol", type=float, default=2.0e-6,
                    help="terminal-SoC tolerance for --match-terminal-soc "
                         "(default 2e-6, i.e. ~0.4 %% of this cycle's SoC swing)")
    ap.add_argument("--charger-accounting", default="physical",
                    choices=["simple", "physical"],
                    help="which hydrogen accounting the DP MINIMISES (D11) - "
                         "MUST match the electrical engine the table will be "
                         "replayed under. 'physical' (default) charges the "
                         "fuel cell for the Ag105's bus draw, matching a "
                         "--electrical hifi run (and therefore a default "
                         "run_hil_suite.py campaign); 'simple' omits it, "
                         "matching --electrical simple. Both totals are "
                         "reported either way.")
    ap.add_argument("--run-exit", type=float, default=sim.SOC_BAND_RUN_EXIT_S,
                    help="time the strategy hands back MODE_SAFE (default %g, "
                         "SOC_BAND_RUN_EXIT_S)" % sim.SOC_BAND_RUN_EXIT_S)
    ap.add_argument("--no-compare-heuristic", dest="compare_heuristic",
                    action="store_false",
                    help="skip the matched-model `soc-band` reference walk")
    ap.add_argument("--dry-run", action="store_true",
                    help="solve and report, write nothing")
    args = ap.parse_args(argv)

    if args.scenario not in sim.SCENARIOS:
        ap.error("unknown scenario %r (known: %s)"
                 % (args.scenario, ", ".join(sorted(sim.SCENARIOS))))
    meta = sim.SCENARIOS[args.scenario]
    if args.n_share < 2:
        ap.error("--n-share must be >= 2")
    if args.soc_step <= 0 or args.stage_dt <= 0 or args.capacity_ah <= 0:
        ap.error("--soc-step, --stage-dt and --capacity-ah must all be > 0")
    if not 0.0 < args.soc0 < 1.0:
        ap.error("--soc0 must be strictly inside (0, 1)")
    # Kept because --match-terminal-soc OVERWRITES args.lambda_term with the
    # solved weight, and the reproduction command must record the INPUT.
    args.lambda_term_input = args.lambda_term

    duration = float(meta["duration_s"])
    dt = float(args.stage_dt)
    n_stages = int(round(duration / dt))
    times = np.arange(n_stages + 1) * dt          # N+1 rows: ZOH defined at the end
    cap_as = args.capacity_ah * 3600.0
    chg_a = float(meta.get("chg_i_ceiling_a", sim.AG105_I_MAX))

    v, a, p_dem, v_bus, i_total, cruise = build_demand(
        args.scenario, meta, times, dt)
    chg_ok = charge_mask(times, p_dem, v_bus, cruise, chg_a, args.run_exit)

    print("[dp] scenario %s: %.1f s, %d stages of %g s, chg ceiling %.2f A"
          % (args.scenario, duration, n_stages, dt, chg_a))
    print("[dp] demand: peak %.3f W (%.3f A bus), mean %.3f W; "
          "charge-admissible stages %d/%d"
          % (p_dem.max(), i_total.max(), p_dem.mean(),
             int(chg_ok[:n_stages].sum()), n_stages))

    shares = np.linspace(DP_SHARE_MIN, DP_SHARE_MAX, args.n_share)
    # Belt and braces: the grid is inside the cut band by construction (see
    # DP_SHARE_MIN/MAX), and this asserts it so a retune of the soc-band
    # constants cannot silently walk the DP onto DROOP_R_MIN/MAX.
    if not (sim.SOC_BAND_SHARE_MIN < shares[0]
            and shares[-1] < sim.SOC_BAND_SHARE_MAX):
        ap.error("share control grid [%.4f, %.4f] touches or crosses the "
                 "share-cut band [%.2f, %.2f] - commanding its edge risks "
                 "updateShareSetpointCutoff() opening a bus switch"
                 % (shares[0], shares[-1], sim.SOC_BAND_SHARE_MIN,
                    sim.SOC_BAND_SHARE_MAX))

    # ── D8 reachability walk -> SoC window ──────────────────────────────────
    lo, hi = reachable_soc_window(args.soc0, p_dem[:n_stages], v_bus[:n_stages],
                                  chg_ok[:n_stages], dt, cap_as, chg_a,
                                  shares[0], shares[-1])
    span = max(hi - lo, DP_SOC_WINDOW_MIN_PAD)
    pad = max(DP_SOC_WINDOW_PAD_FRAC * span, DP_SOC_WINDOW_MIN_PAD)
    g_lo, g_hi = lo - pad, hi + pad
    n_soc = int(round((g_hi - g_lo) / args.soc_step)) + 1
    soc_grid = g_lo + np.arange(n_soc) * args.soc_step
    print("[dp] reachable SoC [%.6f, %.6f]; grid [%.6f, %.6f], %d points, "
          "step %g" % (lo, hi, soc_grid[0], soc_grid[-1], n_soc, args.soc_step))

    # ── the causal reference walk runs FIRST: --match-terminal-soc heuristic
    #    needs its terminal SoC as the target.
    href = None
    if args.compare_heuristic or args.match_terminal_soc == "heuristic":
        href = heuristic_walk(args.scenario, meta, args.soc0, times[:n_stages],
                              p_dem[:n_stages], v_bus[:n_stages],
                              i_total[:n_stages], dt, cap_as, chg_a,
                              args.run_exit)

    i0 = int(np.abs(soc_grid - args.soc0).argmin())

    def _solve_and_roll(lam_term):
        J0, Uopt = solve_dp(args.soc0, times[:n_stages], p_dem[:n_stages],
                            v_bus[:n_stages], chg_ok[:n_stages], dt, cap_as,
                            chg_a, shares, soc_grid, args.lambda_dev, lam_term,
                            args.charger_accounting)
        if not np.isfinite(J0[i0]):
            raise DpInfeasible(
                "the initial state (SoC %.6f) has infinite cost-to-go: no "
                "feasible trajectory exists under the current limits. Check "
                "the FC current ceiling (%.2f A) against the demand peak "
                "(%.3f A)." % (args.soc0, LIMIT_I_FC_MAX_A, i_total.max()))
        out = forward_pass(args.soc0, times[:n_stages], p_dem[:n_stages],
                           v_bus[:n_stages], chg_ok[:n_stages], dt, cap_as,
                           chg_a, shares, soc_grid, Uopt)
        return (J0[i0],) + out

    # ── MATCHED-TERMINAL-SOC SOLVE ──────────────────────────────────────────
    # A hydrogen comparison between two energy-management strategies is only
    # valid at matched terminal SoC: any strategy burns less hydrogen by
    # discharging the pack harder, so an unmatched pair ranks nothing.  The DP
    # sits on a trade-off CURVE parametrised by LAMBDA_TERM, and the point on
    # that curve which makes the comparison legible is the one whose terminal
    # SoC equals the causal strategy's.  There the DP is, by construction, the
    # lower bound on hydrogen for that SoC outcome.
    #
    # LAMBDA_TERM -> terminal SoC is MONOTONE NON-DECREASING (a heavier
    # terminal weight can only make the optimiser value SoC more), so a
    # bisection on log(lambda) converges.  It is NOT continuous — the control
    # grid is discrete, so the reachable terminal SoCs are a step function of
    # lambda — which is why the loop stops on the SoC tolerance OR on a
    # narrow bracket, and reports the residual either way rather than
    # pretending it hit the target exactly.
    lam_term = args.lambda_term
    match_target = None
    match_iters = 0
    # M3: recorded into the table header by render_table().  'n/a' is the
    # --match-terminal-soc none case, which is not a matched comparison at all.
    args.match_target_soc = None
    args.match_residual_soc = None
    args.match_converged = "n/a"
    if args.match_terminal_soc not in ("none", "None", ""):
        if args.match_terminal_soc == "heuristic":
            match_target = href["soc_final"]
        else:
            try:
                match_target = float(args.match_terminal_soc)
            except ValueError:
                ap.error("--match-terminal-soc must be 'none', 'heuristic', or "
                         "an SoC value, got %r" % args.match_terminal_soc)
        lo_l, hi_l = DP_LAMBDA_TERM_BISECT_RANGE
        best = None
        for match_iters in range(1, DP_LAMBDA_TERM_BISECT_ITERS + 1):
            lam_term = (lo_l * hi_l) ** 0.5          # geometric midpoint
            res = _solve_and_roll(lam_term)
            soc_end = float(res[3][-1])
            err = soc_end - match_target
            if best is None or abs(err) < abs(best[0]):
                best = (err, lam_term, res)
            if abs(err) <= args.match_tol:
                break
            if err < 0.0:
                lo_l = lam_term                      # too much discharge -> heavier
            else:
                hi_l = lam_term
            if hi_l / lo_l < 1.0 + 1e-6:
                break
        err, lam_term, res = best
        args.match_target_soc = float(match_target)
        args.match_residual_soc = float(err)
        args.match_converged = "yes" if abs(err) <= args.match_tol else "no"
        print("[dp] matched terminal SoC: target %.6f, solved lambda_term "
              "%.6g in %d solves, residual %+.2e SoC%s"
              % (match_target, lam_term, match_iters, err,
                 "" if abs(err) <= args.match_tol
                 else "  (ABOVE --match-tol %g - the control grid is discrete, "
                      "so this is the closest reachable point; report the "
                      "residual with any comparison)" % args.match_tol))
    else:
        res = _solve_and_roll(lam_term)

    j0, share, charge, soc_traj, h2, h2_plant = res
    args.lambda_term = lam_term       # the SOLVED value is what the header records

    # Hold the last stage's command for the terminal row (ZOH, so the row at
    # t = duration is only ever read if the run overruns its own duration).
    share = np.append(share, share[-1])
    charge = np.append(charge, charge[-1])

    predicted = {"h2_g": h2, "h2_plant_g": h2_plant,
                 "soc_final": float(soc_traj[-1])}

    print("[dp] OPTIMAL (this model, open loop): J = %.6g g-equivalent" % j0)
    print("[dp]   h2 physical            %.6g g   (objective; charger energy "
          "charged to the FC)" % h2)
    print("[dp]   h2 simple-plant-equiv  %.6g g   (comparable to a SIMPLE-mode "
          "run's h2_cum_g)" % h2_plant)
    print("[dp]   SoC %.6f -> %.6f  (delta %+.6f)"
          % (args.soc0, predicted["soc_final"],
             predicted["soc_final"] - args.soc0))
    print("[dp]   share span %.4f .. %.4f; charge_goal asserted on %d of %d "
          "stages" % (share.min(), share.max(), int(charge.sum()), len(charge)))
    chg_idx = np.nonzero(charge > 0.0)[0]
    if chg_idx.size:
        print("[dp]   charge window(s): t = %.2f .. %.2f s"
              % (times[chg_idx[0]], times[chg_idx[-1]]))
        bad = chg_idx[~cruise[chg_idx]]
        if bad.size:
            raise DpInfeasible("charge asserted outside a cruise region at "
                               "t = %.3f s" % times[bad[0]])
        print("[dp]   (all charge stages are inside cruise regions - "
              "operator ruling (b) holds)")
    # ASCII on stdout, deliberately, and the rule covers EVERY string this
    # script can emit to a console: print(), stderr, ap.error(), argparse
    # --help text, and exception messages.  The script is run from consoles
    # whose default encoding is cp1252 (the Windows bench PC), where a
    # non-ASCII character is a UnicodeEncodeError that takes the whole report —
    # or, worse, the refusal message explaining why the table was not written —
    # with it.  L6 (review, 2026-08-31) swept the file for the em dashes that
    # had accumulated; keep new console strings ASCII.  The generated FILE is
    # written UTF-8 and keeps its full banner.
    print("[dp] NOTE: hydrogen figures are the Gfc MODEL'S ESTIMATE. The map is "
          "scale-portable; the")
    print("[dp]       stack is NOT identified against this rig - TODO(calibrate). "
          "Rankings on this")
    print("[dp]       rig are robust regardless. See the H2Consumption banner in "
          "hil_plant_sim.py.")

    if args.compare_heuristic and href is not None:
        h = href
        key = "h2_plant_g" if args.charger_accounting == "simple" else "h2_g"
        print("[dp] CAUSAL REFERENCE `soc-band`, SAME reduced model:")
        print("[dp]   h2 physical %.6g g, simple-plant-equiv %.6g g, "
              "SoC -> %.6f (delta %+.6f)"
              % (h["h2_g"], h["h2_plant_g"], h["soc_final"],
                 h["soc_final"] - args.soc0))
        print("[dp]   band exit t=%s, share saturation t=%s, first charge t=%s"
              % (("%.2f" % h["band_exit_t"]) if h["band_exit_t"] else "never",
                 ("%.2f" % h["sat_t"]) if h["sat_t"] else "never",
                 ("%.2f" % h["charge_t"]) if h["charge_t"] else "never"))
        # Compare on the SAME accounting the DP minimised, and say which.
        dp_v = h2_plant if key == "h2_plant_g" else h2
        print("[dp]   DP vs soc-band on the %s accounting: h2 %+.4g g "
              "(%+.2f %%), terminal SoC %+.6f"
              % (args.charger_accounting, dp_v - h[key],
                 100.0 * (dp_v - h[key]) / h[key] if h[key] else 0.0,
                 predicted["soc_final"] - h["soc_final"]))
        print("[dp]   NOTE: read the PAIR - a hydrogen comparison is only "
              "valid at matched terminal SoC (see --match-terminal-soc).")

    fingerprint = sim.dp_profile_fingerprint(args.scenario, meta)
    text = render_table(args.scenario, meta, args, fingerprint,
                        times, share, charge, predicted,
                        {"n": n_soc, "lo": float(soc_grid[0]),
                         "hi": float(soc_grid[-1])},
                        heuristic=href if args.compare_heuristic else None)
    if args.dry_run:
        print("[dp] --dry-run: %d bytes, %d rows NOT written"
              % (len(text.encode("utf-8")), len(times)))
        return 0

    # M3 (review, 2026-08-31): a table whose bisection missed the tolerance is
    # not a benchmark — its hydrogen figure is not comparable to ref_h2_g_* at
    # the SoC the causal strategy actually ended at, and that is the ONE claim
    # the table exists to support.  It has been printed as a parenthetical
    # since the bisection was added, which is exactly the kind of caveat that
    # gets read once and then forgotten by the reader of the CSV.  Refuse, and
    # make shipping one an explicit act (--allow-unmatched); --dry-run above
    # still reports freely, so investigating a hard case costs nothing.
    if args.match_converged == "no" and not args.allow_unmatched:
        print("[dp] REFUSING to write: matched-terminal-SoC bisection did NOT "
              "converge.\n"
              "     target %.9f, residual %+.3e SoC, tolerance %g.\n"
              "     The DP's hydrogen total is therefore NOT comparable to the "
              "causal reference's\n"
              "     (a strategy burns less hydrogen simply by discharging the "
              "pack harder), so this\n"
              "     table cannot answer 'how much did soc-band leave on the "
              "table?'.\n"
              "     Widen --match-tol, refine --n-share / --soc-step, or pass "
              "--allow-unmatched to\n"
              "     ship it anyway with match_converged: no recorded in the "
              "header."
              % (args.match_target_soc, args.match_residual_soc,
                 args.match_tol),
              file=sys.stderr)
        return 2

    out = args.out or default_table_path(args.scenario)
    if os.path.exists(out) and not args.force:
        print("[dp] REFUSING to overwrite %s - pass --force" % out,
              file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    # newline="" + explicit \n: identical bytes on Windows and POSIX, which is
    # what makes "two runs produce the same file" checkable with a hash.  The
    # OTHER half of that guarantee is tools/dp_tables/.gitattributes, which
    # marks these files `-text`: this repository runs core.autocrlf=true, so
    # without it git would check the table out with CRLF and a regenerated
    # table would no longer match the committed one (MEASURED — a stash/pop
    # round trip moved the digest).
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    print("[dp] wrote %s (%d rows, sha256 %s)"
          % (os.path.relpath(out, REPO_ROOT), len(times),
             hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
