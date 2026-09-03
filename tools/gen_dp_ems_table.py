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

D12. THE CHARGER'S BUS DRAW HAS TWO ERAS, AND THE ERA IS AN INPUT.
    Until 2026-09-01 the simulator's hi-fi Ag105 was a 1:1 CURRENT-TRANSFER
    element (hil_electrical.py, `J[N_CHG] -= i_charge`): the pack received
    exactly the current the bus supplied, so a charge stage cost the bus
    V_bus*i_chg watts and the model destroyed i_chg*(V_chg - V_batt).  The
    plant is now an energy-conserving converter at a static charge efficiency,
    so the same charge current costs

        P_in = V_pack * i_chg / eta_chg

    which is NOT the old expression at eta = 1 - the old one billed at the BUS
    voltage and the new one bills at the PACK voltage.  Both eras are
    reachable and the era is selected EXPLICITLY, never by an efficiency
    value: `eta_chg = None` is the old era, a float is the new one.  Every
    site that prices the charger - the stage cost, the FC-budget charge mask
    and the reachability walk - goes through tools/charger_power.py so the
    three cannot disagree.  --eta-chg selects the era on the command line and
    the header records it as `eta_chg`; a scenario meta that declares the key
    supplies it otherwise.  DEFAULT: absent -> the OLD era, so a table
    generated before this change regenerates byte-identically (pinned by
    test_old_era_regeneration_reproduces_the_pre_change_table_byte_for_byte
    against a stored fixture).

    ⚠️ THE COMMITTED TABLES IN tools/dp_tables/ ARE ETA-ERA TABLES: they were
    regenerated with `--eta-chg 0.88` in this round, because the plant they
    are replayed against bills the charger that way, and a table solved in one
    era is not a bound on a run measured in the other.  THE LOADER REFUSES AN
    ERA MISMATCH: `DpReplayStrategy.bind_scenario()` compares the table's
    `# eta_chg:` header (absent = the old era) against `plant_eta_chg()`
    BEFORE the fingerprint check and raises.  It has to be a separate check
    because the FINGERPRINT cannot see the era: a live scenario declares no
    `eta_chg`, so `dp_profile_fingerprint()` hashes the same sentinel in both
    eras (hil_plant_sim.dp_eta_chg).  This generator's startup warning is the
    GENERATOR-SIDE notice of the same fact, and the test that pins the header
    line in every committed table is the third record.

    V_pack HERE IS THE PACK TERMINAL VOLTAGE AT THE CHARGE CURRENT,
    OCV(SoC) + i_chg*rs(SoC), not a flat nominal: D6 already models the full
    OCV curve and the series resistance, and the charger sees the terminal.
    The rs term is 0.064 V at 0.8 A on a ~7.86 V pack (0.8 %); the OCV term is
    the one that matters (7.86 V at SoC 0.7 against a 7.4 V 2S nominal, 6 %).
    ⚠️ TODO(verify): the plant's own charge model must bill at the same node.

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
import time
from dataclasses import dataclass

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
REPO_ROOT = os.path.dirname(_HERE)

import hil_plant_sim as sim                                        # noqa: E402
from hil_electrical import (                                       # noqa: E402
    LIPO_OCV_SOC, LIPO_OCV_V, BATT_CELLS, BATT_RS_NOM, BATT_CAPACITY_AH)
import governor_model as gov_mod                                   # noqa: E402
import regen_power                                                 # noqa: E402
from charger_power import (                                        # noqa: E402
    ETA_CHG_DEFAULT, charger_bus_current_a, charger_bus_power_w,
    check_eta_chg, era_label, resolve_eta_chg)


# ─────────────────────────────────────────────────────────────────────────────
# Constants this script owns.  Everything else is imported (D7).
# ─────────────────────────────────────────────────────────────────────────────

# .ino LIMIT_I_FC_MAX — the fuel-cell channel overcurrent limit the firmware
# faults on.  Not exposed as a Python constant anywhere in tools/, so it is
# restated here with its citation rather than imported.  Every FC-side
# feasibility test below is against this value.
LIMIT_I_FC_MAX_A = 1.4

# .ino LIMIT_I_BT_MAX (.ino:1476) — the battery channel's bus-side overcurrent
# limit, 3.0 A.  Restated here for the same reason and matching
# `mpc_ems.LIMIT_I_BT_MAX_A`.  It became load-bearing with fw v26: the current
# ceiling moves the fuel cell's surplus onto the pack, so a control the FC arm
# admits can now overdraw the BATTERY.  Before fw v26 nothing moved load there
# and the DP carried no battery-side feasibility test at all.
LIMIT_I_BT_MAX_A = 3.0

# ── fw v26 delivered-share semantics ─────────────────────────────────────────
# The firmware's source current-ceiling governor (fw v26,
# docs/fw26_current_ceiling_governor.md) bounds the COMMANDED fuel-cell
# fraction so the commanded channel current stays at or below
# SHARE_GOV_I_FC_CEIL_A, and forces every further amp of total demand onto the
# battery.  The consequence for a demand model is that a stage whose commanded
# share would overdraw the fuel cell is NO LONGER INFEASIBLE: the board delivers
# the CLAMPED share and the battery takes the rest.
#
# THE INFEASIBILITY BOUNDARY SURVIVES ONLY WHERE THE CLAMP CANNOT ACT.  In an
# FC-charge window `assertFcChargeEnable()` holds BT_BUS low, so the fuel cell
# is the single source, I_fc equals I_tot and no share command can move load
# anywhere.  `charge_mask()`'s single-source budget test is therefore UNCHANGED
# by this round; only the two-source SHARE controls gain the clamp.
#
# The scalar authority is `governor_model.ceiling_bounded_share()`.  This is its
# vectorised image and nothing else; `test_gen_dp_ems_table.py` pins the two
# elementwise so a divergence cannot be introduced silently.
GOV_I_FC_CEIL_A = gov_mod.GOV_CONST["SHARE_GOV_I_FC_CEIL_A"]
GOV_I_BT_CEIL_A = gov_mod.GOV_CONST["SHARE_GOV_I_BT_CEIL_A"]
GOV_I_TOT_MIN_A = gov_mod.GOV_CONST["SHARE_I_TOT_MIN_A"]


def delivered_share(share, i_tot):
    """Fuel-cell fraction the board DELIVERS for a commanded `share` at `i_tot`.

    Vectorised over both arguments by numpy broadcasting.  The order is the
    firmware's: battery lower bound first, fuel-cell upper bound second (so the
    fuel cell wins the infeasible pair above I_FC_CEIL + I_BT_CEIL = 3.95 A of
    total), then the droop band, and the band is applied only where a ceiling
    actually bound.  Below both ceilings the commanded share is returned
    unmodified, so a table whose stages stay under them is byte-identical to its
    pre-fw-v26 self."""
    s = np.asarray(share, dtype=float)
    tot = np.asarray(i_tot, dtype=float)
    s, tot = np.broadcast_arrays(s, tot)
    out = np.array(s, dtype=float)
    # AN OUT-OF-BAND COMMANDED SETPOINT IS NEVER CLAMPED -- it is owned by the
    # firmware's setpoint latch, not by the share loop.  See the contract in
    # `governor_model.ceiling_bounded_share()`.  The DP's own grid is the droop
    # band, so this term is inert here; it is present because the helper's
    # semantics must not depend on which caller is asking.
    in_band = (out >= gov_mod.GOV_CONST["DROOP_R_MIN"]) &               (out <= gov_mod.GOV_CONST["DROOP_R_MAX"])
    # ⚠️ THE REACHABILITY GUARD, and it is a CORRECTNESS term (2026-09-02).
    # The clamp runs AFTER the firmware's minority-current clip, which caps the
    # commanded fuel-cell fraction at 1 - SHARE_MINORITY_I_MIN_A/I_tot.  A
    # stage-level demand model carries no conduction floor, so without this
    # guard it clamps on totals the board cannot clamp at: 250 of
    # `ems-dp-replay`'s 34 827 cells bound at I_tot 1.47137 A, where the board's
    # clip caps the fuel cell at 1.1714 A.  `CEILING_REACHABLE_I_TOT_A` is
    # I_FC_CEIL + SHARE_MINORITY_I_MIN_A = 1.55 A, and is conservative for the
    # battery ceiling as well (its own threshold is 3.00 A).
    live = (tot >= gov_mod.CEILING_REACHABLE_I_TOT_A) & in_band
    safe = np.where(live, tot, 1.0)
    bt_bind = live & (((1.0 - out) * safe) > GOV_I_BT_CEIL_A)
    out = np.where(bt_bind, np.maximum(out, 1.0 - GOV_I_BT_CEIL_A / safe), out)
    fc_bind = live & ((out * safe) > GOV_I_FC_CEIL_A)
    out = np.where(fc_bind, np.minimum(out, GOV_I_FC_CEIL_A / safe), out)
    bound = bt_bind | fc_bind
    out = np.where(bound, np.clip(out, gov_mod.GOV_CONST["DROOP_R_MIN"],
                                  gov_mod.GOV_CONST["DROOP_R_MAX"]), out)
    return out

# ── Share control authority ────────────────────────────────────────
# THE DP'S SHARE GRID SPANS THE FULL FIRMWARE COMMAND BAND, [0.15, 0.85].
#
# STANDING OPERATOR RULE (2026-09-02): every EMS strategy gets access to the
# full [0.15, 0.85] range.  The DP and the MPC are strategies for this purpose
# - a benchmark that cannot reach the operating points the causal policies use
# is not a benchmark of them - so the grid is the BAND, taken from the firmware
# constants and never re-typed.
#
# ⚠️ WIDENED FROM [0.25, 0.75] ON 2026-09-02.  The previous grid was
# SOC_BAND_SHARE_NOMINAL +/- SOC_BAND_SHARE_SPAN, and it rested on two reasons.
# Both are answered:
#
#  1. "NEVER COMMAND THE CUT BAND'S EDGE."  updateShareSetpointCutoff()
#     (.ino:9377-9385, latch .ino:9231-9257) opens a channel's *_BUS_ENABLE for
#     a setpoint OUTSIDE the band, on a STRICT comparison: 0.15 and 0.85
#     themselves are IN band.  The old grid stopped 0.10 short of both rails
#     against a float round-trip through the 22-byte packet.  THE EVIDENCE NOW
#     SAYS THAT MARGIN IS NOT NEEDED.  `SdpStrategy.clamp_share()` emits the
#     rail EXACTLY - it is the same float object the firmware compares - and
#     `sdp-v4` has railed at 0.8500 on 100 % of ticks across campaigns
#     20260902_011926 and 20260902_041414 with ZERO hazard cuts.  The firmware
#     also carries SHARE_CUTOFF_HYST 0.01 BEYOND the band (.ino:3258), so the
#     cut needs a setpoint past 0.86 / under 0.14, not past the rail.  The grid
#     edges below are therefore the SAME floats the SDP clamp emits, which
#     `test_the_dp_grid_edges_match_the_sdp_clamp_through_the_packet` pins
#     through the actual command packet.
#  2. "EQUAL ACTUATOR AUTHORITY."  This reason is RESTORED by the widening
#     rather than answered.  The old grid was NARROWER than the policies it
#     bounded: `SdpStrategy.clamp_share()` clamps to the BAND, so on every
#     `ems-*-sdp` leg the DP was solving over a control set that did not
#     contain the policy's own operating point, and the causal run BEAT its own
#     "lower bound" (measured ~3 % on `ems-ftp75c-sdp`, ~0.35 % on `ems-sdp`).
#     A benchmark the referent beats ranks nothing.  With the band matched the
#     bound is a bound again, and the SDP legs' matched-DP deviation is
#     expected to be <= 0.
#
# n_share 57 KEEPS THE CONTROL SPACING AT 0.0125.  The old grid was 41 points
# over 0.50; the band is 0.70, and 0.70/0.0125 + 1 = 57.  Holding the spacing
# rather than the point count is what keeps the widening a change of REACH and
# not of resolution, at 1.39x the control count and about 2x the solve cost
# once the wider reachable window's larger SoC grid is counted.
#
# ERA HANDLING.  `n_share` and `share_span` are already KEY FIELDS
# (`dp_results_db.KEY_FIELDS`) and are already recorded in the table header and
# checked by `DpReplayStrategy.bind_scenario()`'s drift guard, so a record or a
# table solved on the old grid keys and binds as ITS OWN ERA rather than
# colliding with a new one.  Nothing is orphaned; the old artifacts simply stop
# matching a live scenario, which is the correct outcome for a benchmark solved
# over a control set the firmware no longer bounds the strategies to.
#
# TODO(queued): SINGLE-SOURCE COMMANDS (share 0 / 1) are NOT in this grid and
#   are a separate extension.  They are commanded through the setpoint latch
#   rather than through the share loop, and they are subject to the fw v25
#   share-cut load guard (no cut above 0.5 A of survivor current), so they need
#   their own control column with its own feasibility test rather than two more
#   points on this axis.  See the standing rule in docs/HIL_SCENARIOS.md.
#
# FC-current budget at the widest point: 0.85 x the drain phase's 1.462 A bus
# total = 1.24 A, 11 % under LIMIT_I_FC_MAX.  Tighter than the old grid's 22 %,
# and still inside the margin `charge_mask()`'s DP_CHARGE_FC_MARGIN enforces on
# the charge column; `forward_pass()` refuses an FC-overcurrent share outright,
# so an infeasible rail fails loudly rather than being emitted.
DP_SHARE_MIN = sim.SOC_BAND_SHARE_MIN
DP_SHARE_MAX = sim.SOC_BAND_SHARE_MAX

# The share value written into the table for a CHARGING stage.  With
# FC_CHARGE_ENABLE open the firmware has already dropped BT off the bus
# (assertFcChargeEnable(), .ino:10046), so the share loop has no minority
# channel to apportion and the commanded value is informational.  It is set to
# DP_SHARE_MAX rather than 1.0 so that IF the charge path fails to open and
# both channels are in fact still on the bus, the command is still an in-band
# split and cannot trip the cut.
#
# ⚠️ IT IS NOW ON THE RAIL (2026-09-02, the band widening): DP_SHARE_MAX is
# 0.85, the band edge itself, where it used to be 0.75 with 0.10 of margin.
# The reasoning is UNCHANGED and still holds, because
# updateShareSetpointCutoff() compares STRICTLY - 0.85 is IN band - and the
# firmware carries SHARE_CUTOFF_HYST 0.01 beyond it.  What has gone is the
# margin, not the guarantee.  A future retune that made the comparison
# inclusive would break this and the band guard in prepare_problem() together.
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

# Number of share controls, spanning [DP_SHARE_MIN, DP_SHARE_MAX] = the full
# firmware command band [0.15, 0.85].
#
# ⚠️ 41 -> 57 ON 2026-09-02, WITH THE GRID WIDENING, and the point of the
# change is that the SPACING IS HELD rather than the count.  41 points over the
# old 0.50-wide grid was 0.0125 spacing; 57 points over the 0.70-wide band is
# the SAME 0.0125.  Holding the count instead would have coarsened the control
# to 0.0175 and made the widening a change of resolution as well as of reach,
# which would have confounded any before/after comparison.
#
# At the drain phase's ~1.45 A bus total, 0.0125 is 18 mA of FC current per
# step, well under the share loop's own tracking spread (0.503 +/- 0.028
# measured, CLAUDE.md 2026-08-17b).  Cost: 1.39x the control count, and about
# 2x the solve once the wider reachable window's larger SoC grid is counted.
DP_N_SHARE = 57

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


def pack_charge_voltage(soc, chg_a):
    """Pack TERMINAL voltage [V] while CHARGING at `chg_a` (D12).

    OCV(SoC) + i*rs(SoC): the charge current is a fixed input, so unlike the
    discharge referral (D6(a)) this needs no iteration.  It is the voltage the
    Ag105 delivers into, and therefore the voltage the new-era bus draw
    V_pack*i/eta is billed at."""
    return pack_ocv(soc) + chg_a * pack_rs(soc)


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
# The scenarios whose auxiliary load is the bespoke SoC-band drain rather than
# the generic `aux_preload_a` term.  It MIRRORS hil_plant_sim.apply_scenario()'s
# own branch (:7417) and must be updated with it: the simulator applies the
# 1.0 A drain to all three names deliberately, because the three-way EMS
# comparison is only meaningful if the load is bit-identical.
#
# DEFECT FIXED 2026-09-01 (B2): this list carried only the first two names, so
# a DP baseline solved for an `ems-sdp` run saw roughly HALF the real demand
# (measured 0.0034 g against the campaign's 0.0125 g).  The generated
# `ems-dp-replay` table is unaffected — that scenario was already in the list —
# and is byte-identical across the fix.
# EXTENDED 2026-09-02 with the two MPC legs that share `ems-soc-band`'s stimulus
# OBJECT (`ems-mpc`, `ems-mpc-det`).  Same argument as the B2 fix above: a DP
# baseline solved for one of them against HALF the demand would be a bound the
# run cannot honestly be scored against.  `ems-mpc-cross` is absent, exactly as
# `ems-sdp-cross` is — it carries no SoC-band drain.
#
# ⚠️ THE SAME DEFECT RECURRED, AND THE LIST IS NO LONGER TYPED HERE
# (2026-09-03, campaign hil_report_20260902_220604 A6). The three
# `ems-sdp-alpha-*` sweep legs were added to the SIMULATOR's list when they were
# registered — they are the `ems-sdp` stimulus by construction, same profile
# object, same drain, same charge ceiling — and this mirror was not extended with
# it. The registration block said so and predicted the consequence exactly. When
# the matched-DP baselines were finally SOLVED for those three legs the
# prediction landed: `ems-sdp-alpha-cal` has a delta-SoC IDENTICAL to `ems-sdp`
# and a run hydrogen within 24 ppm of it, yet its bound came out at 0.0034595 g
# against `ems-sdp`'s 0.0124009 g — a +258 % "deviation" that is the missing 1.0 A
# drain and nothing else. (0.0034 g is the SAME number the B2 note above records
# for `ems-sdp` in 2026-09-01. The defect is not a coincidence; the duplicated
# list is.) `alpha-greedy` read +268 % with `lambda_term` pinned at 1.000000, NOT
# converged, because no lambda can match a terminal SoC the demand cannot reach.
#
# IT IS NOW DERIVED FROM THE SIMULATOR'S OWN LIST, which is the only copy that
# can be authoritative: `apply_scenario()` is what actually applies the drain, so
# a mirror that can disagree with it is a defect waiting for its third instance.
# Membership is UNCHANGED for every previously-listed scenario, so the three
# committed tables regenerate byte-identical; the only names this adds are the
# three alpha legs, which have no committed table. `ems-mpc-cross` and
# `ems-sdp-cross` remain absent because the SIMULATOR omits them.
SOC_BAND_DRAIN_SCENARIOS = tuple(sim.SOC_BAND_DRAIN_SCENARIO_NAMES)


def scenario_drain_a(scenario, t, aux_preload_a=None):
    """The scenario's bus-side auxiliary load [A] at time t.

    Mirrors apply_scenario()'s SOC_BAND_DRAIN_SCENARIOS branch term for term,
    and its
    GENERIC `aux_preload_a` branch by calling the same function the simulator
    does — so a DP table is always solved against the load the run will
    actually apply.  Returns I_AUX_A alone for a scenario with neither.

    The generic term was added 2026-08-31 with the `aux_preload_a` key.  It is
    0.0 for every scenario that predates the key, `ems-dp-replay` included, so
    the shipped table's demand is unchanged.

    STIMULUS ERA (2026-09-01).  `aux_preload_a`, when not None, OVERRIDES the
    value `sim.scenario_aux_preload_a()` reads out of the live SCENARIOS
    registry.  It exists because an ARCHIVED run executed under the preload
    constant of its own era, and a DP baseline solved for that run must use the
    load the board actually saw, not the load the current checkout declares.
    The ramp is the simulator's own, term for term.  None keeps the live
    lookup, so every existing caller is unchanged."""
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


def build_demand(scenario, meta, times, dt, aux_preload_a=None, loss_map=None,
                 drag_mode=None, eta_regen=None, eta_chg=None,
                 v_pack_ref=None, regen_i_max_a=None):
    """Per-stage (v, a, P_dem_bus, V_bus, I_total, cruise, I_regen) arrays.

    ⚠️ THE RETURN GREW A SEVENTH ELEMENT on 2026-09-02 (the ftp75c round).
    `i_regen` is the pack charge current a braking stage delivers, in AMPS, and
    it is ALL ZEROS in the pre-regen era, so every old-era caller that unpacks
    six gets a loud TypeError rather than a silently mis-priced demand.

    `drag_mode` (2026-09-02) selects the ROAD-LOAD PROFILE.  `None` and `"rig"`
    are the MEASURED bench road load `F_c*sgn(v) + b_eff*v`, which is what every
    committed table was solved against; the compensated modes replace it with
    `k_air*v*|v|` and zero Coulomb.  It changes the TRACTIVE demand, not only
    the braking credit, so it is fingerprinted.

    `eta_regen` selects the REGEN DEMAND ERA, in the shape `eta_chg` and
    `loss_map` established.  `None` is the pre-2026-09-02 model - the REGEN
    DIVERGENCE documented below - and a float credits braking stages through
    `tools/regen_power.py`, the one chain the plant, this generator, the walk
    and the MPC share.  `eta_chg`, `v_pack_ref` and `regen_i_max_a` price the
    credit's last stage (the Ag105's output-referred cap) and are REQUIRED when
    `eta_regen` is set: the reference pack voltage is a single scalar, not the
    trajectory's, so `i_regen` stays STATE-INDEPENDENT and the stage cost stays
    separable.

    `loss_map` (2026-09-02) selects the DEMAND-MODEL ERA, in the shape
    `eta_chg` established for the charger.  `None` is the pre-2026-09-02 model
    documented under ELECTRICS below.  A dict (see
    `hil_plant_sim.loss_map_for_config`) prices the plant's static losses and
    the realized `--droop design` bus law instead, which is what makes the
    delta-SoC-matched bound TIGHTER and BLEED-INVARIANT: the run and the bound
    then carry the same node bleeds, so a bleed retune moves both together.
    The full derivation, the fit and its residuals are in that module's
    "DP DEMAND MODEL'S STATIC-LOSS MAP" block; the mechanism is

        i_motor = p_mech / (ETA_BOOST * V_bus)
        V_MOT   = (V_bus - rt_v_fwd - rt_r_on*i_motor)/(1 + rt_r_on*g_node_other)
        i_par   = V_bus*g_node_bus + V_MOT*g_node_other
        I_total = i_motor + i_aux + i_par
        V_bus   = v0_eff - (r_fix + k_g*g_par) * I_total

    solved by DP_LOSS_MAP_PICARD_ITERS iterations of the same Picard loop the
    two-term model uses.  `V_MOT` carries no switch indicator because MOT_PWR
    is closed for the whole DP horizon: the bus is pre-charged during the
    low-voltage bring-up and kept energized through Idle and Run (CLAUDE.md
    section 2, Death 5).  The charger arm of `i_par` is deliberately absent —
    see the SCOPE note in the loss-map block.

    MECHANICS (Plant.step's model, without the stiction deadband — the profile
    never dwells inside V_STICTION while commanding force):
        F      = M_EFF*a + F_COULOMB*sgn(v) + B_EFF*v
        p_mech = max(0, F*v)            one-signed, matching Plant.step's floor
                                        (regen is a torque clip on this rig, not
                                        a dump path — CLAUDE.md 2026-08-17b)

    ⚠️ THE REGEN DIVERGENCE IS CLOSED IN THE REGEN ERA, AND OPEN OUTSIDE IT
    (E-M2, 2026-09-01; direction corrected 2026-09-02, review PLANT-R1-F5;
    CLOSED 2026-09-02, the ftp75c round).
    THE DECELERATION DEMAND WAS NEVER OVERSTATED.  `max(0, F*v)` and the plant
    both bill ZERO motor demand while F*v < 0; what the DP omitted is the
    ENERGY THE PLANT GIVES BACK on those stages, which is a credit to the
    battery, not a load.  Consequence at a MATCHED terminal SoC: the DP had to
    supply with hydrogen the SoC the live run got back from braking, so its
    total was INFLATED and a regen-bearing run's deviation against it was
    correspondingly optimistic.
    `hil_report_analysis.matched_dp_for_run` prices that bound per run
    (`regen_bound`, the returned energy at the Gfc DC gain).
    WITH `eta_regen` SET the credit is inside the DP and that per-run bound goes
    to zero, which is the purpose of the change: the bound stops being an
    unquantified inflation of the DP hydrogen total.
    WITHOUT IT the divergence stands exactly as it did - and on the MEASURED RIG
    PROFILE it is 0.001 J of a 30.8 J braking kinetic energy, because the rig
    road load exceeds the inertial force at every deceleration in every
    registered cycle.  That is why the pre-regen era remains the default and why
    every committed table is still a bound on the run it was solved for.

    THE CREDIT IS EXPRESSED AS A PACK CURRENT, NOT AS A NEGATIVE `p_dem`, and
    this is the central design choice.  Four reasons, each rooted in code below:
      * NOTHING FLOWS BACK TO THE BUS.  `MOT_PWR` is instantiated strict-forward
        and docs/HIL_PLANT.md records the bus contribution as structurally zero
        while the chopper clamps.  A negative `p_dem` would credit the bus.
      * `solve_dp()`'s split-control feasibility test `(p_fc / V) <=
        LIMIT_I_FC_MAX_A` and its stage cost both assume `p_dem >= 0`.  A
        negative `p_dem` would bill NEGATIVE HYDROGEN.
      * `charge_mask()`'s budget test would become trivially true on braking
        stages and would admit FC charge windows the firmware never opens there.
      * The MPC's violation tables bound `d*i_tot` and `(1-d)*i_tot`
        one-sidedly and would not catch a regen current limit.
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
        i_aux[k] = scenario_drain_a(scenario, t, aux_preload_a)

    # ── ROAD LOAD ────────────────────────────────────────────────────────────
    # `rig` is the pre-2026-09-02 expression VERBATIM (kept as its own arm so an
    # old-era table regenerates byte-identically); the compensated modes carry
    # ONE quadratic term and no Coulomb term, in the signed `v*|v|` form that
    # keeps the drag opposing motion.  This mirrors `Plant.step()`'s two arms
    # term for term, minus the stiction deadband - the profile never dwells
    # inside V_STICTION while commanding force.
    k_air = sim.drag_k_air(sim.DRAG_MODE_RIG if drag_mode is None
                           else drag_mode)
    if k_air == 0.0:
        f_coul = np.where(v > sim.V_STICTION, sim.F_COULOMB,
                          np.where(v < -sim.V_STICTION, -sim.F_COULOMB, 0.0))
        force = sim.M_EFF * a + f_coul + sim.B_EFF * v
    else:
        force = sim.M_EFF * a + k_air * v * np.abs(v)
    p_mech = np.maximum(0.0, force * v)

    # ── THE BRAKING CREDIT (2026-09-02) ─────────────────────────────────────
    # `p_pos = max(0, F*v)` above is UNCHANGED, which is the point of the
    # 2026-09-02 correction: the DP's deceleration demand was never overstated.
    # What it omitted was the credit, and this is it - the whole chain from
    # `tools/regen_power.py`, so the plant, this generator, the walk and the MPC
    # cannot price a braking stage four different ways.
    eta_regen = regen_power.check_eta_regen(eta_regen)
    if eta_regen is None:
        i_regen = np.zeros(n)
    else:
        if v_pack_ref is None or regen_i_max_a is None:
            raise ValueError(
                "build_demand needs v_pack_ref and regen_i_max_a when "
                "eta_regen is set: the credit's last stage is the Ag105's "
                "output-referred cap, and the reference pack voltage must be a "
                "SCALAR so `i_regen` stays state-independent and the DP's "
                "stage cost stays separable")
        i_regen = np.empty(n)
        for k in range(n):
            i_regen[k] = regen_power.regen_pack_current_from_force_a(
                float(force[k]), float(v[k]), eta_regen=eta_regen,
                eta_chg=eta_chg, v_pack_v=float(v_pack_ref),
                k_f=sim.K_F, i_clip_a=sim.VESC_REGEN_I_MAX_A,
                i_max_a=float(regen_i_max_a))

    if loss_map is None:
        # THE PRE-2026-09-02 MODEL, kept verbatim so an old-era table
        # regenerates byte-identically.
        v_bus = np.full(n, sim.V_BUS_DROOP_V0)
        for _ in range(4):
            i_motor = p_mech / (sim.ETA_BOOST * v_bus)
            i_total = i_motor + i_aux
            v_bus = sim.V_BUS_DROOP_V0 - sim.K_DROOP_BUS_SHARED * i_total
        i_motor = p_mech / (sim.ETA_BOOST * v_bus)
        i_total = i_motor + i_aux
    else:
        lm = sim.check_loss_map(loss_map)
        k_eff = lm["r_fix"] + lm["k_g"] * lm["g_par"]
        g_bus, g_oth = lm["g_node_bus"], lm["g_node_other"]
        v_fwd, r_on = lm["rt_v_fwd"], lm["rt_r_on"]
        v_bus = np.full(n, lm["v0_eff"])
        for _ in range(sim.DP_LOSS_MAP_PICARD_ITERS):
            i_motor = p_mech / (sim.ETA_BOOST * v_bus)
            v_mot = (v_bus - v_fwd - r_on * i_motor) / (1.0 + r_on * g_oth)
            i_par = v_bus * g_bus + v_mot * g_oth
            i_total = i_motor + i_aux + i_par
            v_bus = lm["v0_eff"] - k_eff * i_total
        i_motor = p_mech / (sim.ETA_BOOST * v_bus)
        v_mot = (v_bus - v_fwd - r_on * i_motor) / (1.0 + r_on * g_oth)
        i_par = v_bus * g_bus + v_mot * g_oth
        i_total = i_motor + i_aux + i_par
    p_dem = v_bus * i_total

    # Cruise mask (D10): the same test the causal `soc-band` policy applies,
    # with the same constants — but evaluated on the profile's own slope rather
    # than on a trailing window, because a table generator HAS the profile.
    cruise = (np.abs(a) <= sim.SOC_BAND_CRUISE_SLOPE_MAX) & \
             (v >= sim.SOC_BAND_CRUISE_MIN_MPS)
    return v, a, p_dem, v_bus, i_total, cruise, i_regen


def charge_mask(times, p_dem, v_bus, cruise, chg_ceiling_a, run_exit_s,
                eta_chg=None, v_pack_ref=None, i_regen=None):
    """Per-stage boolean: may the DP open the charger path at this stage? (D10)

    `eta_chg` / `v_pack_ref` select the charger era (D12).  The OLD era needs
    neither: a 1:1 current-transfer charger draws exactly `chg_ceiling_a` from
    the bus, which is the term this test has always added.  The NEW era draws
    V_pack*i/(eta*V_bus), which is SMALLER, so the budget binds later; the
    reference pack voltage is a single scalar (the solve's initial SoC) rather
    than the trajectory's, because this mask must stay state-INDEPENDENT for
    the stage cost to remain separable.

    THE DEMAND-MODEL ERA REACHES THIS MASK THROUGH `p_dem` AND `v_bus`, and it
    needs no argument of its own.  The single-source FC budget below is
    `p_dem/v_bus`, which is exactly `i_total`, so once `build_demand()` carries
    a loss map that budget includes the parallel bleed current `i_par` and the
    mask is correspondingly STRICTER: a stage the loss-map-free model admitted
    can be refused here because the bleed pushes the FC channel over
    `DP_CHARGE_FC_MARGIN * LIMIT_I_FC_MAX_A`.  That is the intended behaviour,
    and `test_gen_dp_ems_table.py` pins the `p_dem/v_bus == i_total` identity
    in both eras so a refactor cannot separate the two."""
    eta_chg = check_eta_chg(eta_chg)     # L8: validate AND normalise
    if eta_chg is not None and v_pack_ref is None:
        raise ValueError("charge_mask needs v_pack_ref when eta_chg is set "
                         "(the new era bills the charger at the PACK voltage)")
    in_run = (times >= sim.EMS_RUN_ENTRY_S) & (times < run_exit_s)
    # Single-source FC budget: with BT dropped off the bus the FC channel
    # carries the whole load PLUS the charger's stamped draw, against
    # LIMIT_I_FC_MAX with DP_CHARGE_FC_MARGIN of headroom.
    i_chg_bus = charger_bus_current_a(chg_ceiling_a, v_bus, v_pack_ref,
                                      eta_chg)
    budget_ok = ((p_dem / v_bus + i_chg_bus)
                 <= DP_CHARGE_FC_MARGIN * LIMIT_I_FC_MAX_A)
    # ── EXCLUSIVITY (2026-09-02) ────────────────────────────────────────────
    # A STAGE CANNOT BOTH FC-CHARGE AND REGEN-CHARGE.  This is the host-side
    # image of the hardware guard in `assertFcChargeEnable()`, which drives
    # BT_BUS LOW, then REGEN LOW, waits 100 us, then raises FC_CHARGE - so the
    # board can never have both paths open and a table that assumed it could is
    # optimizing over an infeasible control.
    #
    # `cruise` already excludes MOST braking stages but not all: a shallow
    # deceleration inside SOC_BAND_CRUISE_SLOPE_MAX can be regen-capable under
    # the compensated drag, where the inertial force needs only to beat a
    # quadratic term that vanishes at low speed.  The explicit term makes the
    # exclusion EXACT rather than incidental.
    #
    # It keeps the mask STATE-INDEPENDENT, which is the property that makes the
    # stage cost separable and the DP tractable: `i_regen` is a per-stage
    # constant computed against a reference pack voltage, not against the
    # trajectory's.
    if i_regen is not None:
        budget_ok = budget_ok & (i_regen <= 0.0)
    return in_run & cruise & budget_ok


# ─────────────────────────────────────────────────────────────────────────────
# Forward dynamics shared by the DP, the reachability walk and the heuristic
# reference walk — ONE implementation, so the three cannot disagree.
# ─────────────────────────────────────────────────────────────────────────────
def step_discharge(soc, share, p_dem, v_bus, dt, cap_as, i_regen=0.0):
    """One stage on the split control.  Returns (soc_next, h2_g, h2_plant_g).

    `i_regen` (2026-09-02) is the braking credit in AMPS INTO THE PACK, and it
    is SHARE-INDEPENDENT by construction: the flywheel returns what it returns
    whatever the split is doing.  That is what keeps the DP separable - the
    credit is a per-stage constant added to the transition, never a term the
    control index can move.  Zero in the pre-regen era, so every old-era total
    is bit-identical."""
    p_fc_bus = share * p_dem
    p_bt_bus = p_dem - p_fc_bus
    i_pack = pack_current_from_bus_power(p_bt_bus, soc)
    soc_next = soc - i_pack * dt / cap_as + i_regen * dt / cap_as
    h2 = sim.H2_GFC_DC_GAIN_GPS_PER_W * (p_fc_bus / sim.ETA_BOOST) * dt
    return soc_next, h2, h2


def step_charge(soc, p_dem, v_bus, chg_a, dt, cap_as, eta_chg=None,
                i_regen=0.0):
    """One stage on the charge control.  Returns (soc_next, h2_g, h2_plant_g).

    D11: `h2_g` charges the fuel cell for the charger energy (the physical
    answer, and what the objective minimises); `h2_plant_g` omits it, which is
    what a SIMPLE-mode simulator run's `h2_cum_g` column will actually show.

    D12: `eta_chg` selects the charger era.  The pack receives `chg_a` in BOTH
    eras - the efficiency is on the INPUT side - so `soc_next` never moves
    with it; only the bus power the fuel cell is billed for does."""
    # `i_regen` is PROVABLY ZERO on any stage reachable here: `charge_mask()`
    # ANDs `i_regen <= 0.0` in, which is the host-side image of
    # `assertFcChargeEnable()`'s hardware exclusion.  It is threaded anyway, and
    # deliberately: this function is also called by `reachable_soc_window()`'s
    # extreme-policy walk and by `ems_walk`, and a future admission rule that
    # relaxed the mask would otherwise silently drop the credit here instead of
    # failing.  The term is the same one `step_discharge()` adds, so the two
    # cannot price a braking stage differently.
    soc_next = soc + chg_a * dt / cap_as + i_regen * dt / cap_as
    p_fc_bus_phys = p_dem + charger_bus_power_w(
        chg_a, v_bus, pack_charge_voltage(soc, chg_a), eta_chg)
    h2 = sim.H2_GFC_DC_GAIN_GPS_PER_W * (p_fc_bus_phys / sim.ETA_BOOST) * dt
    h2_plant = sim.H2_GFC_DC_GAIN_GPS_PER_W * (p_dem / sim.ETA_BOOST) * dt
    return soc_next, h2, h2_plant


# ─────────────────────────────────────────────────────────────────────────────
# Reachability walk (D8)
# ─────────────────────────────────────────────────────────────────────────────
def reachable_soc_window(soc0, p_dem, v_bus, chg_ok, dt, cap_as, chg_a,
                         share_lo, share_hi, eta_chg=None, i_regen=None):
    """[lo, hi] SoC bounds over the two extreme admissible policies.

    THE DEMAND-MODEL ERA is likewise transparent here: it enters only through
    the `p_dem` and `v_bus` arrays the caller passes, so this function needs no
    `loss_map` argument and must not grow one.  What it MUST NOT do is mix
    eras: sizing an SoC grid with a loss-map-free demand and then solving on a
    loss-map demand gives a grid too narrow at one end.  `prepare_problem()`
    is the single caller and passes one demand to both.

    `eta_chg` (D12) reaches only the hydrogen totals inside step_charge, not
    the SoC transition, so GIVEN THE SAME MASK the window is era-invariant; it
    is threaded through so a walk cannot be run against a different charger
    model than the solve it sizes.  The mask itself is NOT era-invariant - the
    eta era's smaller bus draw admits charging at more stages (measured on
    ems-dp-replay: 129 -> 157 admitted stages, and the SoC grid it sizes 1746
    -> 1764 points) - so the two eras' windows do differ, through `chg_ok`."""
    # THE REGEN CREDIT MUST BE HERE (2026-09-02).  Regeneration raises the
    # upper bound reachable from any state, and transitions off the grid are
    # INFEASIBLE rather than clamped (see solve_dp's `feas &= (soc_next >= lo)`
    # test), so a window sized WITHOUT the credit would sit below trajectories
    # the DP can actually reach and would silently TRUNCATE the optimum.  It
    # also lowers the all-battery floor slightly, which is harmless but is the
    # same term and is applied on both walks for that reason.
    def _reg(k):
        return 0.0 if i_regen is None else float(i_regen[k])

    lo = hi = soc0
    s = soc0
    for k in range(len(p_dem)):        # all-battery: the deepest discharge
        s, _, _ = step_discharge(s, share_lo, p_dem[k], v_bus[k], dt, cap_as,
                                 _reg(k))
        lo = min(lo, s)
    s = soc0
    for k in range(len(p_dem)):        # all-FC + charge whenever admitted
        if chg_ok[k]:
            s, _, _ = step_charge(s, p_dem[k], v_bus[k], chg_a, dt, cap_as,
                                  eta_chg, _reg(k))
        else:
            s, _, _ = step_discharge(s, share_hi, p_dem[k], v_bus[k], dt,
                                     cap_as, _reg(k))
        hi = max(hi, s)
        lo = min(lo, s)
    return lo, hi


# ─────────────────────────────────────────────────────────────────────────────
# The DP itself
# ─────────────────────────────────────────────────────────────────────────────
def solve_dp(soc0, times, p_dem, v_bus, chg_ok, dt, cap_as, chg_a,
             shares, soc_grid, lam_dev, lam_term, charger_accounting,
             eta_chg=None, i_regen=None):
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
    # Pack terminal voltage while charging, per SoC row (D12).  Built once:
    # the charge current is fixed, so it does not depend on the stage.
    v_pack_chg = pack_charge_voltage(soc_grid, chg_a)

    J_next = lam_term * np.abs(soc_grid - soc0)
    Uopt = np.empty((n, n_stages), dtype=np.int16)

    soc_col = soc_grid[:, None]
    lo, hi = soc_grid[0], soc_grid[-1]

    for k in range(n_stages - 1, -1, -1):
        P = p_dem[k]
        V = v_bus[k]
        # THE BRAKING CREDIT, share-independent by construction (2026-09-02).
        # A scalar per stage, so it enters BOTH transitions as one added term
        # and the stage cost stays separable: SoC gains on a braking stage
        # WHATEVER the share decision is, which is exactly what makes the DP
        # tractable at the same complexity as before.
        R = 0.0 if i_regen is None else float(i_regen[k])

        # ── split controls ──────────────────────────────────────────────────
        # fw v26 DELIVERED-SHARE SEMANTICS.  The commanded share is a REQUEST;
        # the board's current-ceiling governor delivers `delivered_share()` of
        # it and puts the remainder on the battery.  Two consequences, and both
        # are the point of the change: the stage COST is billed on the fuel-cell
        # power actually delivered, and a stage whose commanded share would have
        # overdrawn the fuel cell is feasible instead of infeasible.
        d_share = delivered_share(shares, P / V)   # (m,)
        p_fc = d_share * P                     # (m,)
        p_bt = P - p_fc
        i0 = p_bt[None, :] / (sim.ETA_BOOST * ocv[:, None])
        v1 = np.maximum(ocv[:, None] - i0 * rs[:, None], 1.0)
        i_pack = p_bt[None, :] / (sim.ETA_BOOST * v1)
        soc_next = np.empty((n, ctrl_n))
        stage = np.empty((n, ctrl_n))
        soc_next[:, :m] = soc_col - i_pack * dt / cap_as + R * dt / cap_as
        stage[:, :m] = sim.H2_GFC_DC_GAIN_GPS_PER_W * (p_fc / sim.ETA_BOOST) * dt

        feas = np.empty((n, ctrl_n), dtype=bool)
        # ── FEASIBILITY IS JUDGED ON THE COMMANDED CURRENT (operator ruling
        #    D-3, 2026-09-02) ──────────────────────────────────────────────────
        # COST and DYNAMICS above use the DELIVERED share; feasibility does not.
        # The distinction is a transient one and it is the reason the guard is
        # not simply moved onto the clamped current:
        #
        #   WHAT THE CLAMP COVERS.  A slow ramp at an already-converged share
        #   ratio.  The reference is bounded before the controller ever tracks
        #   it, so the delivered fuel-cell current rises MONOTONICALLY to
        #   SHARE_GOV_I_FC_CEIL_A = 1.25 A and stops: `fw26-clamp-cruise`'s
        #   walk (tools/probes/probe_fw26_clamp_walk.py, entered from the
        #   scenario's own converged 0.50 pre-phase) shows a phase-A peak of
        #   exactly 1.2500 A and NO overshoot at all.
        #
        #   WHAT IT DOES NOT COVER.  A stage-to-stage DEMAND STEP.  The extra
        #   amps arrive at the CONVERGED droop ratio within one 1 ms sample,
        #   while the clamp needs roughly five reference-slew ticks plus the
        #   ~20 ms lag of the governor's own load EMA before it can move the
        #   ratio.  `detectFaults()` latches FAULT_OC_FC on a single raw sample
        #   above 1.4 A and has NO persistence filter, so a stage the clamp
        #   would settle can still latch on the way in.
        #
        # A DP stage boundary is exactly such a step, so the pre-clamp grid
        # point is the current the board can actually see, and the pre-fw-v26
        # predicate is restored unchanged.
        i_fc_cmd = shares * P / V                  # (m,) COMMANDED
        feas[:, :m] = (i_fc_cmd <= LIMIT_I_FC_MAX_A)[None, :]
        # ...and the BATTERY arm, new this round and the clamp's own liability.
        # Moving load off the fuel cell puts it on the pack, so a control the FC
        # arm now admits can overdraw the BATTERY -- which the DP had no test
        # for, because before fw v26 nothing moved load there. Judged on the
        # DELIVERED current, because the surplus is delivered: this is where the
        # clamp actually put the amps. Mirrors `mpc_ems.Planner._roll()`, which
        # bounds `(1 - d) * i_tot` against LIMIT_I_BT_MAX on the same reasoning.
        feas[:, :m] &= ((p_bt / V) <= LIMIT_I_BT_MAX_A)[None, :]

        # ── charge control ──────────────────────────────────────────────────
        # `R` is provably zero here - `charge_mask()` refuses a regen-capable
        # stage - but the term is written so the two columns cannot drift.
        soc_next[:, m] = soc_grid + chg_a * dt / cap_as + R * dt / cap_as
        # D11: which bus power the charge stage is billed for.  `physical`
        # charges the FC for the charger's draw; `simple` omits it, mirroring
        # the simple-mode plant's own bus node (and its logged h2_cum_g).
        # D12: the charger era must be priced HERE, not only in the forward
        # pass.  The Bellman recursion CHOOSES the policy from this number, so
        # billing the old 1:1 current-transfer power while the forward pass
        # reports the eta-era one selects an old-era policy and scores it in the
        # new era.  `charger_bus_power_w` broadcasts over the SoC rows through
        # `v_pack_chg`; in the old era it returns `V * chg_a` exactly, so the
        # pre-2026-09-01 tables stay byte-identical.
        p_fc_charge = (P + charger_bus_power_w(chg_a, V, v_pack_chg, eta_chg)) \
            if charger_accounting == "physical" else P
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
                 shares, soc_grid, Uopt, eta_chg=None, i_regen=None):
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
            soc, dh2, dh2p = step_charge(soc, p_dem[k], v_bus[k], chg_a, dt,
                                         cap_as, eta_chg,
                                         0.0 if i_regen is None
                                         else float(i_regen[k]))
            share_out[k] = DP_CHARGE_SHARE
            charge_out[k] = 1.0
        else:
            # fw v26 + operator ruling D-3.  THE COMMANDED share is the grid
            # point the backward pass chose and the value the BOARD is
            # commanded with; the DELIVERED share is what the ceiling governor
            # lets through, and is what the dynamics and the cost see.  The two
            # feasibility raises use the same split as `solve_dp()`, so a
            # forward pass cannot accept a control the backward pass refused:
            #   * the FC raise is on the COMMANDED current (a stage-boundary
            #     demand step arrives at the converged ratio inside one 1 ms
            #     sample, before the clamp's ~5 slew ticks and ~20 ms EMA lag,
            #     and FAULT_OC_FC has no persistence filter);
            #   * the BT raise is on the DELIVERED current, because that is
            #     where the clamp actually put the surplus amps.
            i_tot_k = p_dem[k] / v_bus[k]
            share_cmd = float(shares[u])
            share = float(delivered_share(share_cmd, i_tot_k))
            if (share_cmd * i_tot_k) > LIMIT_I_FC_MAX_A + 1e-12:
                raise DpInfeasible(
                    "policy selected an FC-overcurrent share at stage %d "
                    "(t=%.3f s): commanded share %.4f x %.3f W / %.3f V = "
                    "%.4f A > %.2f A"
                    % (k, times[k], share_cmd, p_dem[k], v_bus[k],
                       share_cmd * i_tot_k, LIMIT_I_FC_MAX_A))
            if ((1.0 - share) * i_tot_k) > LIMIT_I_BT_MAX_A + 1e-12:
                raise DpInfeasible(
                    "policy selected a BT-overcurrent share at stage %d "
                    "(t=%.3f s): delivered battery share %.4f x %.3f W / "
                    "%.3f V = %.4f A > %.2f A"
                    % (k, times[k], 1.0 - share, p_dem[k], v_bus[k],
                       (1.0 - share) * i_tot_k, LIMIT_I_BT_MAX_A))
            soc, dh2, dh2p = step_discharge(soc, share, p_dem[k], v_bus[k],
                                            dt, cap_as,
                                            0.0 if i_regen is None
                                            else float(i_regen[k]))
            # THE BOARD IS COMMANDED WITH THE GRID POINT, not with the clamped
            # value: the ceiling is the FIRMWARE's to apply, and emitting the
            # clamped share would command a split the board would then clamp a
            # second time. The delivered share is used for the dynamics above
            # and nowhere else.
            share_out[k] = share_cmd
        h2 += dh2
        h2_plant += dh2p
        soc_traj[k + 1] = soc

    return share_out, charge_out, soc_traj, h2, h2_plant


# ─────────────────────────────────────────────────────────────────────────────
# Causal reference walk — the SAME reduced model, driven by `soc-band`
# ─────────────────────────────────────────────────────────────────────────────
def heuristic_walk(scenario, meta, soc0, times, p_dem, v_bus, i_total, dt,
                   cap_as, chg_a, run_exit_s, eta_chg=None, i_regen=None,
                   socband_kwargs=None):
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
    # `socband_kwargs` carries the PER-SCENARIO charge thresholds (2026-09-02).
    # Without them the reference walk on a compensated profile would admit a
    # charge window at the first cruise sample and never exit it by current -
    # the shipped 0.60 A entry threshold sits ABOVE that cycle's entire source
    # total - so the "causal reference" recorded in a table header would be a
    # charge-saturated control rather than the policy.
    policy = sim.SocBandStrategy(**(socband_kwargs or {}))
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
            # Feedback view: the keys SocBandStrategy actually reads.  fw v26:
            # the policy measures the DELIVERED fuel-cell current, not the one
            # it asked for, so the feedback carries the clamped share.
            i_fc = float(delivered_share(share, i_total[k])) * i_total[k]
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
        reg = 0.0 if i_regen is None else float(i_regen[k])
        if charging and sim.EMS_RUN_ENTRY_S <= t < run_exit_s:
            soc, dh2, dh2p = step_charge(soc, p_dem[k], v_bus[k], chg_a, dt,
                                         cap_as, eta_chg, reg)
        else:
            # fw v26: the policy COMMANDS a share; the board's current-ceiling
            # governor DELIVERS the bounded one.  Same helper the DP uses, so
            # the matched-model comparison stays matched.
            soc, dh2, dh2p = step_discharge(
                soc, float(delivered_share(share, i_total[k])), p_dem[k],
                v_bus[k], dt, cap_as, reg)
        h2 += dh2
        h2_plant += dh2p
    return {"h2_g": h2, "h2_plant_g": h2_plant, "soc_final": soc,
            "band_exit_t": band_exit_t, "sat_t": sat_t, "charge_t": charge_t}


# ─────────────────────────────────────────────────────────────────────────────
# Library layer — the solve, callable without argparse
# ─────────────────────────────────────────────────────────────────────────────
# RATIONALE (2026-09-01, WORK_QUEUE §1).  The analysis pipeline must produce a
# delta-SoC-matched DP hydrogen baseline for every HIL run that executed a
# drive cycle.  That is the same solve `main()` performs, at a target read off
# the run rather than off a causal walk, and with no table written.  Everything
# below is a factoring of what `main()` already did; `main()` now calls it, so
# the generator and the analysis baseline cannot diverge.  The committed tables
# are byte-identical across the change (verified by regeneration and cmp).
@dataclass
class Problem:
    """Everything a DP solve needs, resolved once and reusable across lambdas."""
    scenario: str
    meta: dict
    soc0: float
    capacity_ah: float
    stage_dt: float
    n_share: int
    soc_step: float
    run_exit: float
    charger_accounting: str
    lambda_dev: float
    aux_preload_a: object          # None = the live registry value
    eta_chg: object                # None = the 1:1 current-transfer era (D12)
    loss_map: object               # None = the loss-map-free demand model
    drag_mode: object              # None = the measured rig road load
    eta_regen: object              # None = the pre-regen demand model
    fingerprint: str
    chg_a: float
    cap_as: float
    n_stages: int
    times: object
    v: object
    a: object
    p_dem: object
    v_bus: object
    i_total: object
    cruise: object
    i_regen: object
    chg_ok: object
    shares: object
    soc_grid: object
    grid_info: dict
    reach_lo: float
    reach_hi: float
    i0: int


@dataclass
class MatchedSolve:
    """One solved DP trajectory, matched or not."""
    h2_g: float
    h2_plant_g: float
    soc_final: float
    delta_soc: float
    residual_soc: object           # None when no target was requested
    converged: object              # True / False / None ("n/a")
    lambda_term: float
    n_solves: int
    j0: float
    share: list
    charge: list
    soc: list
    wall_s: float


def prepare_problem(scenario, meta, *, soc0, capacity_ah, stage_dt, n_share,
                    soc_step, run_exit, charger_accounting,
                    lambda_dev=DP_LAMBDA_DEV_G_PER_SOC_S,
                    aux_preload_a=None, eta_chg=None, loss_map=None,
                    drag_mode=None, eta_regen=None):
    """Resolve the demand, the control grid and the SoC grid for one scenario.

    Raises ValueError on an argument the solve cannot honour, so a library
    caller gets an exception rather than argparse's exit; `main()` converts it
    back into an `ap.error()`."""
    if n_share < 2:
        raise ValueError("n_share must be >= 2")
    if soc_step <= 0 or stage_dt <= 0 or capacity_ah <= 0:
        raise ValueError("soc_step, stage_dt and capacity_ah must all be > 0")
    if not 0.0 < soc0 < 1.0:
        raise ValueError("soc0 must be strictly inside (0, 1)")
    if charger_accounting not in ("simple", "physical"):
        raise ValueError("charger_accounting must be 'simple' or 'physical'")
    # D12.  None is the OLD 1:1 current-transfer era and is the DEFAULT, so a
    # caller that predates the charger-efficiency model solves exactly the
    # problem it used to.
    try:
        eta_chg = check_eta_chg(eta_chg)
    except ValueError as exc:
        raise ValueError(str(exc))
    # The demand-model era (2026-09-02).  None is the LOSS-MAP-FREE model and
    # is the DEFAULT, for the same reason `eta_chg`'s default is None: a caller
    # that predates the map solves exactly the problem it used to.
    loss_map = sim.check_loss_map(loss_map)
    # THE ROAD-LOAD AND REGEN ERAS (2026-09-02), on identical terms: both
    # default to the pre-round configuration, so a caller that predates them
    # solves exactly the problem it used to.
    if drag_mode is not None and drag_mode not in sim.DRAG_MODES:
        raise ValueError("drag_mode must be one of %s, got %r"
                         % (list(sim.DRAG_MODES), drag_mode))
    eta_regen = regen_power.check_eta_regen(eta_regen)

    duration = float(meta["duration_s"])
    dt = float(stage_dt)
    n_stages = int(round(duration / dt))
    times = np.arange(n_stages + 1) * dt      # N+1 rows: ZOH defined at the end
    cap_as = capacity_ah * 3600.0
    chg_a = sim.dp_chg_ceiling_a(meta)

    # ONE representative pack voltage, at the SOLVE'S INITIAL SoC.  Used by the
    # mask's FC-budget term (D12) AND by the regen credit's output-referred cap,
    # so both stay state-independent and the stage cost stays separable.
    # Computed unconditionally now that a second consumer needs it in an era
    # where `eta_chg` may still be None.
    v_pack_ref_all = float(pack_charge_voltage(float(soc0), chg_a))
    v_pack_ref = None if eta_chg is None else v_pack_ref_all

    v, a, p_dem, v_bus, i_total, cruise, i_regen = build_demand(
        scenario, meta, times, dt, aux_preload_a, loss_map=loss_map,
        drag_mode=drag_mode, eta_regen=eta_regen, eta_chg=eta_chg,
        v_pack_ref=v_pack_ref_all,
        # The Ag105's own ceiling bounds the regen credit exactly as it bounds
        # the FC-path charge current, and it is the SAME scenario key.
        regen_i_max_a=chg_a)
    chg_ok = charge_mask(times, p_dem, v_bus, cruise, chg_a, run_exit,
                         eta_chg, v_pack_ref,
                         i_regen if eta_regen is not None else None)

    shares = np.linspace(DP_SHARE_MIN, DP_SHARE_MAX, n_share)
    # THE BAND IS INCLUSIVE, so the test is <= / >= (2026-09-02).
    # updateShareSetpointCutoff() compares STRICTLY (.ino:9231-9257): a
    # setpoint outside [0.15, 0.85] opens the minority channel's bus switch,
    # and 0.15 and 0.85 THEMSELVES ARE IN BAND.  The grid's own edges are those
    # two floats exactly - the same ones SdpStrategy.clamp_share() emits - so a
    # strict test here would refuse the shipped grid.  What must still be
    # refused is a grid that CROSSES the band, which is the real hazard.
    if not (sim.SOC_BAND_SHARE_MIN <= shares[0]
            and shares[-1] <= sim.SOC_BAND_SHARE_MAX):
        raise ValueError(
            "share control grid [%.4f, %.4f] CROSSES the share-cut band "
            "[%.2f, %.2f] - commanding outside it makes "
            "updateShareSetpointCutoff() open a bus switch"
            % (shares[0], shares[-1], sim.SOC_BAND_SHARE_MIN,
               sim.SOC_BAND_SHARE_MAX))

    lo, hi = reachable_soc_window(soc0, p_dem[:n_stages], v_bus[:n_stages],
                                  chg_ok[:n_stages], dt, cap_as, chg_a,
                                  shares[0], shares[-1], eta_chg,
                                  i_regen[:n_stages])
    span = max(hi - lo, DP_SOC_WINDOW_MIN_PAD)
    pad = max(DP_SOC_WINDOW_PAD_FRAC * span, DP_SOC_WINDOW_MIN_PAD)
    # ── THE GRID-EDGE INFEASIBILITY POISON (found 2026-09-02) ───────────────
    # THE MECHANISM, and it is a property of the GRID, not of the physics.  At
    # the BOTTOM grid row every discharge control steps below `soc_grid[0]`, and
    # `feas &= (soc_next >= lo)` marks all of them infeasible - correctly, since
    # the transition leaves the model.  That row's cost-to-go is therefore
    # `inf`.  On the NEXT backward stage a row one step above it lands on a
    # point that BRACKETS the inf row, `np.interp` returns inf for any positive
    # bracket weight, and the row goes infinite too.  The infeasibility
    # therefore CREEPS UPWARD, and it does so at ROUGHLY one grid row per
    # stage.  ⚠️ "EXACTLY ONE ROW PER STAGE WHATEVER THE STEP SIZES" WAS
    # OVERSTATED and is retracted: the rate is set by how far a transition's
    # landing point reaches above its own row, so it depends on the step sizes
    # after all, and it was MEASURED at 1.94 and 2.91 rows per stage on two
    # configurations rather than at 1.  The bound the guard needs is therefore
    # `>= n_stages * soc_step` of climb, which is what it pads by; the pad is
    # CONSERVATIVE by whatever the true rate exceeds 1, and over-padding costs
    # solve time and nothing else.  TODO(verify): measure the rate as a
    # function of the step sizes and size the pad from it.
    #
    # WHEN THAT MATTERS.  It matters when the climb reaches the INITIAL STATE,
    # at which point the solve reports "the initial state has infinite
    # cost-to-go" and the DP is not merely inaccurate but unusable.  On
    # `ems-ftp75c-dp` it does: 1800 stages against a 1861-row grid whose bottom
    # pad is 219 rows, so the poison climbs past soc0's row 1046 at stage ~650.
    # The compensated road load is what exposes it - the tractive demand falls
    # ~4.5x, so the reachable window narrows, so the proportional pad narrows,
    # while the stage count is unchanged.
    #
    # THE GUARD.  Pad by at least the whole horizon's climb, which makes the
    # poison structurally unable to reach the reachable window at all.
    #
    # ⚠️ IT IS GATED ON THE REGEN ERA, AND THE GATE IS ABOUT ARTIFACTS, NOT
    # ABOUT PHYSICS.  The guard is correct for every solve; applying it
    # universally would move the SoC grid of all four committed tables and
    # every stored dp_db record, for a defect none of them actually hit at
    # soc0.  Measured on `ems-dp-replay`: 611 stages climb 0.003055 SoC from a
    # bottom edge 0.001782 below `reach_lo`, so the poison DOES enter the low
    # end of that table's reachable window - it simply never reaches 0.7.
    # TODO(verify): re-solve the pre-regen tables under this guard and quantify
    # the change before making it unconditional.  Until then the pre-round
    # artifacts keep the grid they were solved on, and the absence of the guard
    # is part of what "the pre-regen era" means.
    # GATED ON EITHER ERA KEY (M3, 2026-09-02).  Keying it on `eta_regen`
    # alone left `prepare_problem(drag_mode="scaled-air", eta_regen=None)` -
    # a legitimate configuration, and the one a compensated ZERO-REGEN CONTROL
    # solve uses - producing an infinite cost-to-go at the initial state.  The
    # poison is a property of the STAGE COUNT against the GRID WIDTH, and the
    # compensated road load narrows the reachable window whichever era the
    # credit is in.  Byte identity is preserved: a pre-round table carries
    # NEITHER key, so neither arm fires and its grid is untouched.
    if eta_regen is not None or drag_mode not in (None, sim.DRAG_MODE_RIG):
        pad = max(pad, (n_stages + 1) * soc_step)
    g_lo, g_hi = lo - pad, hi + pad
    n_soc = int(round((g_hi - g_lo) / soc_step)) + 1
    soc_grid = g_lo + np.arange(n_soc) * soc_step

    return Problem(
        scenario=scenario, meta=meta, soc0=float(soc0),
        capacity_ah=float(capacity_ah), stage_dt=dt, n_share=int(n_share),
        soc_step=float(soc_step), run_exit=float(run_exit),
        charger_accounting=charger_accounting, lambda_dev=float(lambda_dev),
        aux_preload_a=aux_preload_a, eta_chg=eta_chg, loss_map=loss_map,
        drag_mode=drag_mode, eta_regen=eta_regen,
        fingerprint=sim.dp_profile_fingerprint(scenario, meta),
        chg_a=float(chg_a), cap_as=float(cap_as), n_stages=n_stages,
        times=times, v=v, a=a, p_dem=p_dem, v_bus=v_bus, i_total=i_total,
        cruise=cruise, i_regen=i_regen, chg_ok=chg_ok, shares=shares,
        soc_grid=soc_grid,
        grid_info={"n": n_soc, "lo": float(soc_grid[0]),
                   "hi": float(soc_grid[-1])},
        reach_lo=float(lo), reach_hi=float(hi),
        i0=int(np.abs(soc_grid - soc0).argmin()))


def _roll(problem, lam_term):
    """One backward induction plus its forward rollout at `lam_term`."""
    p = problem
    n = p.n_stages
    J0, Uopt = solve_dp(p.soc0, p.times[:n], p.p_dem[:n], p.v_bus[:n],
                        p.chg_ok[:n], p.stage_dt, p.cap_as, p.chg_a, p.shares,
                        p.soc_grid, p.lambda_dev, lam_term,
                        p.charger_accounting, p.eta_chg, p.i_regen[:n])
    if not np.isfinite(J0[p.i0]):
        raise DpInfeasible(
            "the initial state (SoC %.6f) has infinite cost-to-go: no "
            "feasible trajectory exists under the current limits. Check "
            "the FC current ceiling (%.2f A) against the demand peak "
            "(%.3f A)." % (p.soc0, LIMIT_I_FC_MAX_A, p.i_total.max()))
    out = forward_pass(p.soc0, p.times[:n], p.p_dem[:n], p.v_bus[:n],
                       p.chg_ok[:n], p.stage_dt, p.cap_as, p.chg_a, p.shares,
                       p.soc_grid, Uopt, p.eta_chg, p.i_regen[:n])
    return (J0[p.i0],) + out


def _to_solve(problem, res, lam_term, *, residual, converged, n_solves,
              wall_s):
    j0, share, charge, soc_traj, h2, h2_plant = res
    return MatchedSolve(
        h2_g=float(h2), h2_plant_g=float(h2_plant),
        soc_final=float(soc_traj[-1]),
        delta_soc=float(soc_traj[-1]) - problem.soc0,
        residual_soc=residual, converged=converged,
        lambda_term=float(lam_term), n_solves=int(n_solves), j0=float(j0),
        share=[float(x) for x in share], charge=[float(x) for x in charge],
        soc=[float(x) for x in soc_traj], wall_s=float(wall_s))


def solve_unmatched(problem, lambda_term=DP_LAMBDA_TERM_G_PER_SOC):
    """Solve at a GIVEN terminal weight.  `converged` is None (not a match)."""
    t0 = time.time()
    res = _roll(problem, lambda_term)
    return _to_solve(problem, res, lambda_term, residual=None, converged=None,
                     n_solves=1, wall_s=time.time() - t0)


def solve_matched(problem, *, target_soc, match_tol=2.0e-6, lambda_term0=1.0):
    """Bisect LAMBDA_TERM until the terminal SoC lands on `target_soc`.

    LAMBDA_TERM -> terminal SoC is monotone non-decreasing but NOT continuous
    (the control grid is discrete), so the loop exits on the SoC tolerance OR
    on a narrow bracket and reports the residual either way.  The returned
    solve is the CLOSEST point visited, not the last one."""
    t0 = time.time()
    lo_l, hi_l = DP_LAMBDA_TERM_BISECT_RANGE
    best = None
    n_solves = 0
    for n_solves in range(1, DP_LAMBDA_TERM_BISECT_ITERS + 1):
        lam_term = (lo_l * hi_l) ** 0.5              # geometric midpoint
        res = _roll(problem, lam_term)
        err = float(res[3][-1]) - target_soc
        if best is None or abs(err) < abs(best[0]):
            best = (err, lam_term, res)
        if abs(err) <= match_tol:
            break
        if err < 0.0:
            lo_l = lam_term                          # too much discharge
        else:
            hi_l = lam_term
        if hi_l / lo_l < 1.0 + 1e-6:
            break
    err, lam_term, res = best
    return _to_solve(problem, res, lam_term, residual=float(err),
                     converged=bool(abs(err) <= match_tol),
                     n_solves=n_solves, wall_s=time.time() - t0)


def heuristic_reference(problem):
    """The causal `soc-band` walk through this problem's reduced model."""
    p = problem
    n = p.n_stages
    # The scenario's own soc-band charge thresholds, if it declares them: the
    # reference must be the POLICY on this stimulus, not a charge-saturated
    # control (see heuristic_walk).
    sb = {}
    for key, arg in (("soc_band_charge_enter_itot_a", "charge_enter_itot_a"),
                     ("soc_band_charge_exit_itot_a", "charge_exit_itot_a")):
        if p.meta.get(key) is not None:
            sb[arg] = float(p.meta[key])
    return heuristic_walk(p.scenario, p.meta, p.soc0, p.times[:n],
                          p.p_dem[:n], p.v_bus[:n], p.i_total[:n],
                          p.stage_dt, p.cap_as, p.chg_a, p.run_exit,
                          p.eta_chg, p.i_regen[:n], sb or None)


# ─────────────────────────────────────────────────────────────────────────────
# Table emission
# ─────────────────────────────────────────────────────────────────────────────
def resolve_loss_map_arg(loss_map_arg):
    """`--loss-map` -> the map dict, or None.  ONE resolution of the choice, so
    `main()`, `render_table()` and every test read the same era from the same
    string."""
    if loss_map_arg in (None, "none"):
        return None
    if loss_map_arg == "plant":
        return sim.plant_loss_map()
    raise ValueError("unknown --loss-map %r (choices: none, plant)"
                     % (loss_map_arg,))


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
    # D12.  The OLD (1:1 current-transfer) era appends NOTHING, so a table
    # solved before the charger-efficiency model regenerates byte-identically;
    # its ABSENCE is the record of the era.  The new era appends the term that
    # reproduces it.
    if args.eta_chg is not None:
        cmd += " --eta-chg %r" % float(args.eta_chg)
    loss_map = resolve_loss_map_arg(getattr(args, "loss_map", "none"))
    # The loss-map era appends its own flag, on exactly the same terms: the
    # LOSS-MAP-FREE era appends NOTHING, so a pre-2026-09-02 table regenerates
    # byte-identically and the ABSENCE of the flag is the record of its era.
    if loss_map is not None:
        cmd += " --loss-map plant"
    # The road-load and regen eras append their own flags, on exactly the terms
    # above: the RIG profile and the PRE-REGEN model append NOTHING, so a table
    # solved before 2026-09-02 regenerates byte-identically and the ABSENCE of
    # each flag is the record of its era.
    drag_mode = getattr(args, "drag", None)
    if drag_mode is not None and drag_mode != sim.DRAG_MODE_RIG:
        cmd += " --drag %s" % drag_mode
    eta_regen = getattr(args, "eta_regen", None)
    if eta_regen is not None:
        cmd += " --eta-regen %r" % float(eta_regen)
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
    # DEFAULT-MISMATCH BUG, fixed 2026-09-01 (WP-E).  This line recorded a 0.0
    # default while main() SOLVED with `sim.AG105_I_MAX` for the same absent
    # key, so a scenario that declares no `chg_i_ceiling_a` produced a table
    # whose header said "no charging was available" over a solution in which
    # 2.5 A was.  It is not cosmetic: DpReplayStrategy.bind_scenario()'s drift
    # guard compares this line against `meta.get("chg_i_ceiling_a",
    # AG105_I_MAX)` and REFUSED such a table at startup — which is how the
    # defect was found: the then-committed `ems-ftp75-5050` table carried 0.0
    # and would never have loaded.  It now carries 2.5, from the regeneration
    # that fix required.  E-L1 (2026-09-01) hoisted the resolution into
    # `sim.dp_chg_ceiling_a()`, which all three sites now call.
    A("# chg_ceiling_a: %r" % sim.dp_chg_ceiling_a(meta))
    # D12, and it is EMITTED ONLY IN THE NEW ERA on purpose.  Adding an
    # `eta_chg: none` line to every table would move the bytes of all three
    # committed tables without changing a single number in them; the absence
    # of the line is the old era's record, and the docstring's D12 says so.
    if args.eta_chg is not None:
        A("# eta_chg: %r" % float(args.eta_chg))
        A("#   D12 - the charger is an energy-conserving converter at this")
        A("#   efficiency: a charge stage costs the bus V_pack*i/eta_chg W.")
        A("#   A table with NO eta_chg line was solved against the 1:1")
        A("#   current-transfer charger (V_bus*i) and is not comparable.")
    # The loss map, on the `eta_chg` terms above: EMITTED ONLY when there is
    # one, so a loss-map-free table keeps its exact bytes and the absence of
    # the line is that era's record.
    if loss_map is not None:
        A("# loss_map: %s" % sim.loss_map_canonical(loss_map))
        A("#   2026-09-02 - the demand model carries the plant's STATIC")
        A("#   LOSSES (the per-node bleed on N_BUS and N_MOT) and the")
        A("#   realized `--droop design` bus law, so the delta-SoC-matched")
        A("#   bound is priced against the demand the board actually saw.")
        A("#   A table with NO loss_map line was solved against the")
        A("#   motor-plus-drain model on V_BUS_DROOP_V0 - K_DROOP_BUS_SHARED*I")
        A("#   and is not comparable. See hil_plant_sim's loss-map block.")
    # THE ROAD-LOAD PROFILE and THE REGEN ERA (2026-09-02), each emitted ONLY
    # when it is not the pre-round configuration, so a rig / pre-regen table
    # keeps its exact bytes and the absence of each line is that era's record.
    if drag_mode is not None and drag_mode != sim.DRAG_MODE_RIG:
        A("# drag: %s" % drag_mode)
        A("# drag_k_air: %r" % sim.drag_k_air(drag_mode))
        A("#   2026-09-02 - the mechanical road load is the study vehicle's")
        A("#   SCALED AIR DRAG (k_air*v*|v|, F_c = 0), not this bench's")
        A("#   measured F_c + b_eff*v. It cuts the tractive demand by roughly")
        A("#   4.5x and is what makes braking regenerative at all. A table")
        A("#   with NO drag line was solved against the rig road load.")
    if eta_regen is not None:
        A("# eta_regen: %r" % float(eta_regen))
        A("# vesc_regen_i_max_a: %r" % float(sim.VESC_REGEN_I_MAX_A))
        A("#   2026-09-02 - a braking stage is CREDITED with the pack current")
        A("#   the regen chain delivers (tools/regen_power.py): the VESC clip")
        A("#   as a force, ETA_REGEN to the V-MOT node, then the Ag105's")
        A("#   output-referred cap. A table with NO eta_regen line was solved")
        A("#   against p_mech = max(0, F*v) and NO credit, so at a matched")
        A("#   terminal SoC it must buy that SoC with hydrogen and its total")
        A("#   is INFLATED. The two are not comparable.")
        A("#   BOTH constants are recorded here and checked by")
        A("#   DpReplayStrategy.bind_scenario()'s drift guard - the")
        A("#   pre-committed obligation the NOT RECORDED note below carried.")
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
    # ── THE PRE-COMMITTED CONTRACT ON ETA_REGEN / VESC_REGEN_I_MAX_A ─────────
    # (E-M2, 2026-09-01; DISCHARGED 2026-09-02, the ftp75c round.)
    # The note that stood here said: these two govern the LIVE plant's regen
    # injection, they are NOT in this header and NOT in the guard because
    # neither ENTERS THE SOLVE — build_demand() had no regen term — and "⚠️ If a
    # future generator ever gives the demand model a regen term, BOTH must move
    # into this header and into the guard."
    # THAT GENERATOR IS THIS ONE.  Both constants now appear above, and both are
    # in the drift guard, WHENEVER the table is solved in the regen era.  In the
    # PRE-REGEN era the original argument still holds word for word — neither
    # constant enters that solve — so neither line is emitted and the committed
    # tables keep their exact bytes.  The contract is discharged by making the
    # obligation ERA-CONDITIONAL, not by weakening it.
    A("#")
    A("# ── tunables ─────────────────────────────────────────────────────────")
    # DOCUMENTATION ONLY (MED-4, 2026-09-01). The auxiliary preload is
    # already inside profile_fingerprint (it is one of
    # hil_plant_sim.DP_FINGERPRINT_META_KEYS), so this line is not a drift
    # guard and it moves no data row -- it makes the STIMULUS ERA READABLE.
    # Without it a reader can only discover which preload a table was solved
    # against by recomputing the digest, and a preload retune elsewhere
    # leaves two tables that differ only in a hash. The value recorded is the
    # RESOLVED preload: the bespoke SOC_BAND_DRAIN_SCENARIOS carry their
    # drain inside scenario_drain_a() and never read the key, so they
    # record 0.0. gen_dp_ems_table.py has no --aux-preload argument, so the
    # reconstructed command line above needs no new term.
    A("# aux_preload_a: %r"
      % (0.0 if scenario in SOC_BAND_DRAIN_SCENARIOS
         else float(meta.get("aux_preload_a") or 0.0)))
    A("#   Documentation, not a drift guard: profile_fingerprint above")
    A("#   already covers it.")
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
    # DEFAULT RESOLVED AFTER PARSING, not here: a scenario may declare its own
    # `ems_run_exit_s` (2026-08-31), and argparse cannot see which scenario was
    # selected while it is building its defaults. None means "resolve from the
    # scenario"; the resolution is a few lines below, next to the meta lookup.
    ap.add_argument("--run-exit", type=float, default=None,
                    help="time the strategy hands back MODE_SAFE (default: the "
                         "scenario's `ems_run_exit_s` if it declares one, else "
                         "%g = SOC_BAND_RUN_EXIT_S)" % sim.SOC_BAND_RUN_EXIT_S)
    ap.add_argument("--eta-chg", type=float, default=None,
                    help="Ag105 charge efficiency, selecting the CHARGER ERA "
                         "(D12). Omitted (the default) = the OLD 1:1 "
                         "current-transfer charger, which bills the bus "
                         "V_bus*i_chg and regenerates every committed table "
                         "byte-identically. A value (the plant's is %g) bills "
                         "V_pack*i_chg/eta instead. A scenario meta key "
                         "`eta_chg` supplies it when this is omitted."
                         % ETA_CHG_DEFAULT)
    ap.add_argument("--loss-map", choices=("none", "plant"), default="none",
                    help="DEMAND-MODEL ERA (2026-09-02). 'none' (the default) "
                         "is the loss-map-free model - motor draw plus "
                         "housekeeping drain, priced on V_BUS_DROOP_V0 - "
                         "K_DROOP_BUS_SHARED*I - and regenerates every "
                         "pre-2026-09-02 table byte-identically. 'plant' "
                         "carries the plant's static losses (the per-node "
                         "bleed on N_BUS and N_MOT) and the realized "
                         "`--droop design` bus law, which is what makes the "
                         "delta-SoC-matched bound tighter and "
                         "bleed-invariant. See hil_plant_sim's loss-map "
                         "block for the fit and its residuals.")
    ap.add_argument("--drag", default=None, choices=list(sim.DRAG_MODES),
                    help="ROAD-LOAD PROFILE (2026-09-02). Omitted = the "
                         "scenario's own `drag` key, or 'rig' - this bench's "
                         "MEASURED F_c + b_eff*v, which regenerates nothing "
                         "and regenerates every committed table "
                         "byte-identically. A compensated mode replaces it "
                         "with the study vehicle's scaled air drag and cuts "
                         "the tractive demand by roughly 4.5x, so it MUST "
                         "match the mode the run will replay under.")
    ap.add_argument("--eta-regen", type=float, default=None,
                    help="REGEN DEMAND ERA (2026-09-02). Omitted (the "
                         "default) = NO braking credit, p_mech = max(0, F*v), "
                         "which is what every pre-2026-09-02 table was solved "
                         "against. A value (the plant's is %g) credits a "
                         "braking stage with the pack current the regen chain "
                         "delivers, which is what stops the bound being "
                         "inflated by the energy the run gets back. It only "
                         "does anything under a compensated --drag: on the rig "
                         "road load the credit is 0.001 J of 30.8 J."
                         % regen_power.ETA_REGEN_DEFAULT)
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
    if args.run_exit is None:
        # Resolved per-scenario; must agree with what DpReplayStrategy's M2
        # header check computes on the consumer side, or a freshly-generated
        # table would be refused by the run it was generated for.
        args.run_exit = float(sim.SOC_BAND_RUN_EXIT_S
                              if meta.get("ems_run_exit_s") is None
                              else meta["ems_run_exit_s"])
    # Kept because --match-terminal-soc OVERWRITES args.lambda_term with the
    # solved weight, and the reproduction command must record the INPUT.
    args.lambda_term_input = args.lambda_term
    # D12: the CLI wins over the scenario meta; absent from both = the OLD
    # era.  The default is deliberately NOT the live plant's efficiency: an
    # archived run executed under the accounting of ITS OWN era, and a table
    # regenerated for one must reproduce it (the same discipline the
    # `aux_preload_a` stimulus-era argument records).  A NEW-era table is an
    # explicit act: --eta-chg, or a scenario that declares the key.
    if args.eta_chg is None:
        args.eta_chg = resolve_eta_chg(meta)
    try:
        args.eta_chg = check_eta_chg(args.eta_chg)
    except ValueError as exc:
        ap.error(str(exc))
    # CROSS-CHECK against the plant this table will be replayed under.  The
    # two can disagree silently HERE: the generator's default is the OLD era
    # (an archived run must be reproducible), while the simulator bills every
    # new run at hil_electrical.ETA_CHG.  The mismatch is NOT silent at LOAD
    # time - `DpReplayStrategy.bind_scenario()` refuses an era mismatch
    # outright, before it even checks the fingerprint - so this is the
    # GENERATOR-SIDE notice of the same fact: it reports at solve time what
    # the loader would otherwise report at the start of a campaign.  The
    # profile fingerprint is not what catches it and cannot be: a live
    # scenario declares no `eta_chg`, so both eras hash the same sentinel
    # (hil_plant_sim.dp_eta_chg).
    _live_eta = getattr(sim, "ETA_CHG", None)
    if _live_eta is not None:
        _live = float(_live_eta)
        if args.eta_chg is None or abs(args.eta_chg - _live) > 1e-12:
            print("[dp] WARNING: solving at charger era %s while the plant "
                  "bills new runs at eta_chg = %r.\n"
                  "[dp]          A table solved in one charger era is not a "
                  "bound on a run measured in the other; the plant's loader "
                  "REFUSES such a table at campaign start.\n"
                  "[dp]          Pass --eta-chg %r to solve the era the plant "
                  "will replay this table under."
                  % (era_label(args.eta_chg), _live, _live), file=sys.stderr)

    # ── THE ROAD-LOAD PROFILE (2026-09-02) ──────────────────────────────────
    # CLI wins over the scenario key, and absent from both = the rig profile.
    # Unlike `eta_chg` this key IS declared by scenarios, so the common case
    # needs no flag: `--scenario ems-ftp75c-dp` solves the compensated demand
    # because that scenario declares `drag`.
    if args.drag is None:
        args.drag = meta.get("drag") or sim.DRAG_MODE_RIG
    if args.drag not in sim.DRAG_MODES:
        ap.error("unknown --drag %r (choices: %s)"
                 % (args.drag, ", ".join(sim.DRAG_MODES)))
    # ── THE REGEN ERA (2026-09-02) ──────────────────────────────────────────
    # DEFAULTED FROM THE DRAG PROFILE, and this is the one era default in this
    # file that is derived rather than sentinel-absent.  The reason is that the
    # two are not independent in practice: a compensated run REGENERATES, and a
    # table solved for it without the credit is inflated by exactly the energy
    # the run gets back - which is the defect this round exists to close, and
    # `DpReplayStrategy.bind_scenario()` refuses such a table anyway.  A rig
    # solve still defaults to the pre-regen era and is byte-identical.  Either
    # direction can be forced: `--eta-regen 0.8` on a rig solve, or
    # `--eta-regen 0` is REFUSED by check_eta_regen (0 is not an era, it is an
    # invalid efficiency; the era is the ABSENCE of the term).
    if args.eta_regen is None and args.drag != sim.DRAG_MODE_RIG:
        args.eta_regen = float(sim.ETA_REGEN)
    try:
        args.eta_regen = regen_power.check_eta_regen(args.eta_regen)
    except ValueError as exc:
        ap.error(str(exc))

    duration = float(meta["duration_s"])
    dt = float(args.stage_dt)
    try:
        problem = prepare_problem(
            args.scenario, meta, soc0=args.soc0,
            capacity_ah=args.capacity_ah, stage_dt=args.stage_dt,
            n_share=args.n_share, soc_step=args.soc_step,
            run_exit=args.run_exit,
            charger_accounting=args.charger_accounting,
            lambda_dev=args.lambda_dev, eta_chg=args.eta_chg,
            loss_map=resolve_loss_map_arg(args.loss_map),
            drag_mode=args.drag, eta_regen=args.eta_regen)
    except ValueError as exc:
        # GUARD ORDER, deliberately changed (LOW-4, 2026-09-01): the scalar
        # argument checks and the share-cut-band check moved INTO
        # prepare_problem() so a library caller cannot bypass them, and they
        # now surface here as one ValueError.  The messages are unchanged
        # except for the dropped "--" prefixes, and they are still reported
        # through ap.error(), so the CLI's behaviour is the same.  The order
        # in which two simultaneously-invalid arguments are reported can
        # differ from the pre-2026-09-01 CLI.
        ap.error(str(exc))
    n_stages = problem.n_stages
    times = problem.times
    cap_as = problem.cap_as
    chg_a = problem.chg_a
    p_dem, v_bus, i_total = problem.p_dem, problem.v_bus, problem.i_total
    cruise, chg_ok = problem.cruise, problem.chg_ok
    shares, soc_grid = problem.shares, problem.soc_grid
    n_soc = problem.grid_info["n"]

    print("[dp] scenario %s: %.1f s, %d stages of %g s, chg ceiling %.2f A"
          % (args.scenario, duration, n_stages, dt, chg_a))
    print("[dp] charger era: %s" % era_label(args.eta_chg))
    print("[dp] road load: %s" % sim.drag_era_label(args.drag))
    print("[dp] regen era: %s" % regen_power.era_label(args.eta_regen))
    if args.eta_regen is not None:
        _reg = problem.i_regen[:n_stages]
        _nz = int((_reg > 0.0).sum())
        print("[dp] regen credit: %d/%d stages, peak %.4f A, %.4f C total"
              % (_nz, n_stages, float(_reg.max()), float(_reg.sum()) * dt))
    print("[dp] demand: peak %.3f W (%.3f A bus), mean %.3f W; "
          "charge-admissible stages %d/%d"
          % (p_dem.max(), i_total.max(), p_dem.mean(),
             int(chg_ok[:n_stages].sum()), n_stages))

    # The control grid, the D8 reachability walk and the SoC grid are all
    # resolved by prepare_problem(); the guard against the share-cut band lives
    # there too and surfaces here through the ValueError above.
    print("[dp] reachable SoC [%.6f, %.6f]; grid [%.6f, %.6f], %d points, "
          "step %g" % (problem.reach_lo, problem.reach_hi, soc_grid[0],
                       soc_grid[-1], n_soc, args.soc_step))

    # ── the causal reference walk runs FIRST: --match-terminal-soc heuristic
    #    needs its terminal SoC as the target.
    href = None
    if args.compare_heuristic or args.match_terminal_soc == "heuristic":
        href = heuristic_reference(problem)

    i0 = problem.i0

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
        solved = solve_matched(problem, target_soc=match_target,
                               match_tol=args.match_tol)
        err = solved.residual_soc
        lam_term = solved.lambda_term
        match_iters = solved.n_solves
        args.match_target_soc = float(match_target)
        args.match_residual_soc = float(err)
        args.match_converged = "yes" if solved.converged else "no"
        print("[dp] matched terminal SoC: target %.6f, solved lambda_term "
              "%.6g in %d solves, residual %+.2e SoC%s"
              % (match_target, lam_term, match_iters, err,
                 "" if abs(err) <= args.match_tol
                 else "  (ABOVE --match-tol %g - the control grid is discrete, "
                      "so this is the closest reachable point; report the "
                      "residual with any comparison)" % args.match_tol))
    else:
        solved = solve_unmatched(problem, lam_term)

    j0 = solved.j0
    share = np.asarray(solved.share)
    charge = np.asarray(solved.charge)
    soc_traj = np.asarray(solved.soc)
    h2, h2_plant = solved.h2_g, solved.h2_plant_g
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
