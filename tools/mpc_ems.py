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

⚠️ THE DRIFT GUARD RUNS ONLY UNDER AN INTERPRETER THAT HAS NUMPY.  The equality
   tests import ``gen_dp_ems_table`` and SKIP when the import fails, so a run of
   the suite under ``.venv_hil`` (stdlib only) reports them as skipped and
   passes.  A change to either model must be checked under miniforge, where the
   four equality tests actually execute; the stdlib run alone does NOT establish
   that the two models still agree.

MODEL COMPOSITION
-----------------
``build_demand()``          ported here as ``build_demand()``          (D7)
``scenario_drain_a()``      ported here as ``scenario_drain_a()``
``charge_mask()``           ported here as ``charge_mask()``           (D10)
``step_discharge()``        ported here as ``_dp_step_discharge()``     (D6)
``step_charge()``           ported here as ``_dp_step_charge()``   (D11/D12)
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
2. TRANSITION-STAGE EXACT ROLLS.  Every previewed mode transition (the
   ``GOV_ENTRY_A`` gate upward, ``GOV_RELEASE_A`` downward, a charge window
   opening or closing; 0.30 / 0.25 A at fw v27 rev 2, 0.60 / 0.55 A before it,
   and both derived from ``SHARE_MINORITY_I_MIN_A``) is rolled
   through the real ``GovernorModel`` at 1 kHz, once per ladder point, to
   produce ``r_hold[stage][share]`` - the ratio the governor leaves standing at
   drop-out.  Open stages carry that value.  The rolls are SLICED across the
   50 Hz callbacks at ``roll_budget_ms`` (default 2.0 ms) and the previous
   decision's table is used until the new one completes (candidate_fable
   section 2.2 item 2; adjudication section 2.2).
3. CLOSED-STAGE ALGEBRAIC SURROGATE.  On a closed-loop stage the delivered
   share is ``clip(s, lo, 1-lo)`` with ``lo = min(0.5, 0.15/I_tot)``
   (fw v27 rev 2 re-pin, 2026-09-03: SHARE_MINORITY_I_MIN_A 0.30 -> 0.15 A)
   (candidate_opus Property B: mean error 8.2e-4, maximum 1.49e-2 over 145
   closed stages).
4. SHADOW GOVERNOR.  One ``GovernorModel`` is ticked at 1 kHz between feedback
   samples and corrected from the observation each 50 Hz call, so the committed
   governor state is never surrogate-propagated across a decision.
5. OPEN-LOOP SUBMODE MODEL (2026-09-02).  The firmware's open-loop branch has
   TWO submodes and the first shipped version of this file modelled only one.
   It HOLDS while a closed-loop run stands and the commanded setpoint has not
   moved by more than ``SHARE_SP_CHANGE_EPS``; on any other open tick it takes
   the slew-limited FEEDFORWARD branch, walks the applied ratio toward the
   setpoint at ``DROOP_RATIO_SLEW_PER_TICK`` (or the conduction-handoff ceiling
   ``DROOP_RATIO_SLEW_HANDOFF_PER_TICK``), clips it to
   ``[DROOP_R_MIN, DROOP_R_MAX]`` and WRITES the MDACs.  A receding-horizon
   controller re-commands every stage, so every re-command landing in an open
   stage enters FEEDFORWARD, and that is the class of stage the shipped Gate 1
   failure sat in.  ``delivery_table()`` now models both submodes: the ramp is
   integrated in closed form by ``ramp_mean()``, the transition rolls of item 2
   supply the carry on HELD stages only, and the whole branch is UNREACHABLE
   unless ``sp_acted`` and ``run_seed`` are supplied, so a caller that does not
   name the governor's setpoint state gets the pre-2026-09-02 table bit for bit.
   Measured on the `ems-soc-band` stimulus walk, Gate 1 moves from a mean
   absolute delivered-share error of 0.010334 (maximum 0.25000) to 0.000095
   (maximum 0.00356) against the 5e-03 acceptance, so both the mean and the
   maximum are now inside it.  The survey behind the change, including the
   rejected instantaneous dark-flag proxy and the `_roll_begin()` handoff-state
   seeding defect the round also closed, is
   ``docs/modeling/mpc_design_20260902_nonlinearities.md``.

6. ADAPTIVE SOLVE BUDGET AND LADDER COARSENING (2026-09-02).  The solve budget
   is derived per decision from the callback bound's own terms - the measured
   roll slice, the measured 50 Hz surface work and the previous decision's
   measured per-candidate cost - against the 20 ms command period with a 2 ms
   margin (``derive_budget_ms()``).  Where even that budget cannot hold the FULL
   enumeration, ``coarsen_ladder()`` restricts the search to a coarser subset of
   the ladder that CAN be enumerated completely, always keeping both rails, the
   centre and the incumbent's block values.  The reason for preferring a coarse
   complete search to a cut full one is that the enumeration is ordered outward
   from the incumbent, so an expiry drops the candidates FURTHEST from standing
   still and is therefore biased, while a coarse search is merely coarse.
   Measured on the offline stimuli: budget expiry falls from 88.5 % to 0.0 % of
   decisions on ``ems-mpc-cross``, from 21.3 % to 0.0 % on ``ems-mpc`` and from
   4.9 % to 0.0 % on the stochastic leg (the scenario that carried `mpc-sto`
   at the time; the two names swapped in the 2026-09-02 promotion), at a
   BIT-IDENTICAL committed trajectory on
   every leg - so what the change buys is an uncut search and 27 % less median
   wall clock, not a better plan.  An explicit ``budget_ms`` -
   which is what the ``mpc_budget_ms`` scenario key supplies - disables the
   derivation and TAKES PRECEDENCE.

HONEST LIMITS
-------------
* THE SEARCH WIDTH IS PROJECTED ON A CONSTANT, NOT ON A MEASUREMENT (H1, fix
  round of 2026-09-02).  It was the measured per-candidate cost for one round,
  and that made the COMMITTED PLAN host-dependent: the review measured an 8.29 %
  move in `ems-soc-band` hydrogen between a projection of 0.030 ms and one of
  0.0372 ms per candidate, with the budget-expiry count zero at both.
  ``coarsen_ladder()`` now reads ``CANDIDATE_COST_MS_NOMINAL``, the measurement
  is reported by ``timing()`` beside a ``candidate_cost_over_nominal`` flag, and
  the incumbent's NEIGHBOURS are unioned into the coarse set so that no ladder
  index - in particular index 5, the 0.6667 cruise share - is structurally
  unreachable.  What remains host-dependent is the adaptive BUDGET, and the
  width still moves with it in the coarse steps ``LADDER_SIZES`` allows; an
  explicit ``budget_ms`` removes even that, and ``max_candidates`` bounds the
  search outright.
* THE CONVERTER ASYMMETRY IS MODELLED, AND ONLY BECAUSE THE RUN PASSES IT.
  ``dv0_v`` maps the open-loop applied ratio to a delivered share through
  ``GovernorModel.delivered_share()`` and reaches the delivery table, the shadow
  governor and every roll.  The constructor default is 0.0, which is a SYMMETRIC
  plant and not a shipped choice: the value comes from
  ``hil_plant_sim.resolve_asymmetry_dv0_v()`` through ``mpc_configure_kwargs()``,
  which refuses loudly rather than silently predicting on a symmetric plant if
  this module has no such argument.  The closed loop absorbs the offset by
  integral action, so the cost of getting it wrong is confined to open stages -
  and it is large there: on a walk whose plant carries dv0 = 0.030223 V the
  Gate 1 mean is 0.036175 with the map inert and 0.000317 with it matched, at no
  change in the committed trajectory (0.016211 against 0.000323 at the plant's
  own dv0 of 0.013522 V).  A WALK is the one caller that still has to pass it by
  hand: ``ems_walk.walk()`` builds the strategy from ``strategy_kwargs`` and does
  not consult ``mpc_configure_kwargs()``, so a walk on an asymmetric plant must
  name ``dv0_v`` itself.
* ``mpc-sto`` FAILS GATE 1 ON THE MEASURED PLANT, at a mean of 0.009019 against
  the 5e-03 band, where ``mpc-det`` reads 0.000323.  The residual is ONE
  ``open_hold`` stage carrying 0.118574 and its mechanism is the stochastic
  variant's own conditional-mean demand forecast, not the delivery model: a
  forecast that calls a stage closed where the plant leaves it open puts a whole
  stage of commanded share into the wrong arm.  Every registered stimulus is
  deterministic, so that forecast has nothing to average over.
* THE REGEN TERM IS ERA-SELECTED (2026-09-02), and the statement that stood
  here was wrong in its sign.  It read "the controller over-states demand on
  every decelerating stage": it does not.  ``max(0, F*v)`` bills ZERO motor
  demand while ``F*v < 0``, exactly as the plant does; what the pre-regen model
  omitted is the ENERGY THE PLANT GIVES BACK, a CREDIT to the battery.  With
  ``eta_regen`` set the credit is modelled here, in the DP bound and in the walk
  from ONE chain (``tools/regen_power.py``).  In the pre-regen era the omission
  stands, and on the MEASURED RIG PROFILE it is 0.001 J of a 30.8 J braking
  kinetic energy, because the rig road load exceeds the inertial force at every
  deceleration in every registered cycle.
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
import copy
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
import regen_power as regen_mod          # stdlib only
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

# Ladder band.  THE FULL FIRMWARE COMMAND BAND, taken from the firmware
# constants through `governor_model.GOV_CONST` and NEVER RE-TYPED.
#
# STANDING OPERATOR RULE (2026-09-02): every EMS strategy gets access to the
# full [0.15, 0.85] range.  The MPC is a strategy for this purpose, and a
# planner that cannot reach the operating points the causal policies use plans
# over a control set the plant does not have.
#
# ⚠️ WIDENED FROM (0.25, 0.75) ON 2026-09-02, in lockstep with the DP grid.
# The old default stopped 0.10 short of DROOP_R_MIN/DROOP_R_MAX so
# updateShareSetpointCutoff() could never latch.  That margin is not needed:
# the cut compares STRICTLY, so the rails themselves are IN band, and the
# firmware carries SHARE_CUTOFF_HYST 0.01 BEYOND the band on top of that.
# `sdp-v4` has railed at 0.8500 on 100 % of ticks across two campaigns with
# zero hazard cuts.  `SHARE_BAND_SDP` and `SHARE_BAND_DP` are now the SAME
# band; both names are kept because scenarios and tests select by name.
SHARE_BAND_DP = (gov_mod.GOV_CONST["DROOP_R_MIN"], gov_mod.GOV_CONST["DROOP_R_MAX"])
SHARE_BAND_SDP = (gov_mod.GOV_CONST["DROOP_R_MIN"], gov_mod.GOV_CONST["DROOP_R_MAX"])
# Ladder points across that band.  ⚠️ 7 -> 9 WITH THE WIDENING (2026-09-02),
# so the SPACING is held rather than the count: 0.0833 over the old 0.50-wide
# band becomes 0.0875 over the 0.70-wide one, a 5 % coarsening, against 20 % at
# 8 points and 40 % at 7.  That is the DP grid's own principle applied here -
# holding the count instead would have made the widening a change of resolution
# as well as of reach, and confounded any before/after comparison.
#
# MEASURED BEFORE CHOOSING, on `ems-mpc` and `ems-mpc-cross`, on a host already
# running a DP solve (so the readings are pessimistic).  All of 7, 8 and 9 gave
# ZERO budget expiries; over three repeats of `ems-mpc` (183 decisions) the
# worst single solve was 11.28 ms at 8 points and 10.11 ms at 9, with 0 hits in
# both.  The budget arithmetic therefore permits 9, which is what the operator
# ruling conditions the choice on, so resolution decides it.
# Cost: 2187 candidates against 1029 - see MPC_CAMPAIGN_MAX_CANDIDATES.
SHARE_LEVELS = 9

# ── THE CHARGE AXIS OF THE ENUMERATION (2026-09-02) ─────────────────────────
# `MpcStrategy.__call__()` builds AT MOST three per-stage charge plans per
# decision: the no-charge option (always index 0, so an expired budget has a
# feasible incumbent), the 8 s minimum-dwell option, and — only when the
# admissible run is longer than the dwell — the full segment.  A latched charge
# window replaces the whole list with one option.  The planner enumerates the
# share ladder ONCE PER OPTION, so the full search is `enumeration_size()`
# candidates, not `share_levels ** len(blocks)`.
#
# It is a named constant because the campaign cap is derived from it: with the
# cap set to ONE option's worth of candidates, and the no-charge option
# enumerated FIRST, every capped decision was truncated BEFORE the charge axis
# was reached — so "the MPC chose not to charge" was not a supported reading of
# any leg (campaign 20260902_011926, 13 of 61 decisions capped on mpc-sto).
MAX_CHARGE_OPTIONS = 3


def enumeration_size(share_levels=SHARE_LEVELS, blocks=MOVE_BLOCKS,
                     charge_options=MAX_CHARGE_OPTIONS):
    """Full candidate count for one decision: ladder^blocks per charge plan."""
    return int(share_levels) ** len(tuple(blocks)) * int(charge_options)

# Overcurrent margins.  LIMIT_I_FC_MAX 1.4 A (.ino:1375) and LIMIT_I_BT_MAX
# 3.0 A (.ino:1426), both with gen_dp_ems_table's DP_CHARGE_FC_MARGIN of 0.85
# headroom (adjudication section 1; candidate_fable Table 1).
LIMIT_I_FC_MAX_A = 1.4
LIMIT_I_BT_MAX_A = 3.0
OC_MARGIN = 0.85
I_FC_MAX_A = OC_MARGIN * LIMIT_I_FC_MAX_A          # 1.19 A
I_BT_MAX_A = OC_MARGIN * LIMIT_I_BT_MAX_A          # 2.55 A

# ── SINGLE-SOURCE (0/1) CANDIDATES (2026-09-03, the operator ruling) ─────────
# The MPC may command a share of exactly 0 or exactly 1, which takes one boost
# OFF the bus through `updateShareSetpointCutoff()` and leaves the other
# carrying the whole load.  The DP and the SDP do NOT get these candidates
# (operator ruling, 2026-09-02); the MPC does, and the ruling on the cut
# guard's path dependence is "the rollout-time test" - see `_ss_admissible()`
# and `docs/modeling/mpc_design_20260901.md`, section "Single-source
# candidates".
#
# NAMING.  The mode names the SURVIVING source, which is the one that carries
# the bus.  `SS_MODE_BT` commands share 0.0, so the FUEL CELL is cut and the
# battery survives; `SS_MODE_FC` commands 1.0 and the battery is cut.
SS_MODE_BT = "bt"
SS_MODE_FC = "fc"
SS_SHARE = {SS_MODE_BT: 0.0, SS_MODE_FC: 1.0}
# The channel the setpoint latch CUTS in each mode, for the load guard.
SS_CUT_CHANNEL = {SS_MODE_BT: "fc", SS_MODE_FC: "bt"}
# The survivor's own overcurrent bound, at the same 0.85 margin the two-source
# table uses.  Single-source is the whole reason these differ: with one channel
# off the bus the survivor carries `i_total`, not its share of it.
SS_LIMIT_A = {SS_MODE_BT: I_BT_MAX_A, SS_MODE_FC: I_FC_MAX_A}
# How far the admissibility roll runs, in 1 kHz governor ticks.  The cut is
# evaluated at the TOP of every `powerBalance()` tick, so an admissible cut
# fires within a few ticks of the command; the window exists to let a REFUSED
# cut clear - the survivor's 30 ms blanking is the longest such refusal, and
# the load guard's own current is the filtered plant split, which moves on the
# governor's ~20 ms EMA.  200 ticks is 200 ms, and it costs ~0.55 ms per
# candidate against the 2.761 ms a full 1000-tick transition roll costs.
#
# ⚠️ THE MARGIN, RE-DERIVED FROM A GRID (2026-09-03, review LOW-1).  The
# earlier justification "six blanking windows and ten filter time constants"
# was arithmetic on the mechanisms, not a measurement of the roll.  A grid over
# I_tot in [0.60, 2.55] A (0.05 A steps) x r0 in {0.15, 0.30, 0.50, 0.70, 0.85}
# x both modes, at the measured plant dv0 0.013522 V and through this module's
# own `_ss_admissible()`, engages at up to **95 ticks** (I_tot 0.75 A, r0
# 0.85, BT-only).  So the margin is **2.11x**, not six windows, and the
# unmodelled two-source residual at the worst grid point is 9.5 % of a 1 s
# stage rather than the design record's 3.4 %.  The roll carries NO plant
# current lag - the doomed channel's current follows the model's own delivered
# split instantly - so 95 is a LOWER bound on what the board would take.
#
# fw v27 rev 2 re-pin, 2026-09-03: 118 -> 95 ticks and 1.69x -> 2.11x, because
# `SHARE_MINORITY_I_MIN_A` moved 0.30 -> 0.15 A and the deferral's clipped
# reference therefore walks the doomed channel to half the current it could
# reach before, clearing the 0.5 A load guard sooner.  The grid's own start at
# 0.60 A is the fw v26 closed-loop gate; extending it down to the rev 2 gate
# 0.30 A was measured and returns the same maximum at the same grid point.
# `test_the_admission_roll_grid_maximum_and_its_margin` pins both figures.
SS_ADMIT_MAX_TICKS = 200
# ⚠️ WHAT THE ROLL ACTUALLY FINDS, measured (2026-09-03) and recorded because it
# is not what the design record's resolution 1 assumed.  The load guard does NOT
# permanently refuse a cut anywhere in the OVERCURRENT-admissible region: when
# it refuses the first tick, the firmware's own DEFERRAL clips the closed-loop
# reference back into [DROOP_R_MIN, DROOP_R_MAX], which walks the doomed
# channel's current DOWN until the guard admits.  The deferral's floor is the LOOSER of
# the band edge and the conduction floor,
# `max(DROOP_R_MIN, min(0.5, SHARE_MINORITY_I_MIN_A/I_tot)) * I_tot`.  fw v27
# rev 2 re-pin, 2026-09-03: with the floor at 0.15 A that reduces to
# `DROOP_R_MIN * I_tot` for every total above 1.0 A, which clears the 0.5 A
# guard only above 3.33 A of total, and both survivor bounds (1.19 A fuel cell,
# 2.55 A battery) refuse the candidate long before that.  So what the roll returns is a DELAY, not a
# verdict: 1 tick at 0.4 A on the doomed channel, 17 at 0.6 A, 34 at the largest
# case measured.  34 ms of a 1 s stage is 3.4 % of a stage run two-source that
# the plan modelled single-source, which is inside every band this leg carries.
# The consequence for the CONSERVATIVE TABLE TEST the design record offered as
# resolution 1: it would have refused every one of those candidates.
#
# ⚠️ CORRECTED 2026-09-03 (review LOW-1), on the grid the constant above
# describes.  Two claims in the paragraph above are too strong.  (a) The
# maximum delay is **95 ticks**, not 34 - the four points quoted were
# hand-picked.  (b) `SS_REFUSE_CUT_LOAD` was NOT purely defensive at fw v26: at
# I_tot 0.60 A commanded from either rail the clip band was EMPTY
# (`lo = 0.30/0.60 = 0.5`), the doomed channel parked at 0.5157 A, a hair over
# the 0.5 A guard, the reference did NOT walk down, and the roll expired -
# 2 of the 400 grid points refused on load.
#
# fw v27 rev 2 re-pin, 2026-09-03: those two points are GONE - 0 of the 400
# refuse on load - because the band at 0.60 A is now `lo = 0.15/0.60 = 0.25`
# and the deferral walks the doomed channel down to 0.15 A.  So the sentence
# "the load guard does NOT permanently refuse a cut anywhere in the
# overcurrent-admissible region" holds across the whole grid again.  The
# refusal path is still reachable by construction and is exercised directly by
# `test_a_cut_that_cannot_engage_inside_the_window_is_refused_on_load`;
# `test_the_admission_roll_grid_maximum_and_its_margin` pins the grid figures.
#
# Refusal reasons, reported per decision.  One string per mechanism, so a
# campaign can tell a guard refusal from an overcurrent one.
# The observation frame's `REGEN_ENABLE` bit, restated so the runtime path does
# not import `hil_plant_sim` (which pulls numpy in lazily) for one mask.  It is
# `hil_plant_sim.SW_REGEN` and a test pins the two together; the simulator's own
# header calls it offset 3, bit 3 of `switch_state`.
SW_REGEN_BIT = 0x08

SS_REFUSE_REGEN = "regen_commanded"
SS_REFUSE_CHARGE = "charge_window"
SS_REFUSE_DEFERRED = "deferred_cut"
SS_REFUSE_LATCHED = "latch_standing"
SS_REFUSE_CUT_LOAD = "cut_refused_load"
SS_REFUSE_CUT_BLANK = "cut_refused_blank"
SS_REFUSE_CUT_NEVER = "cut_never_engaged"
SS_REFUSE_OC = "single_source_overcurrent"
SS_REFUSE_RESTORE = "restore_overcurrent"

# ── THE SHARE-STEP GUARD (2026-09-03, the operator ruling) ──────────────────
# THE RULE, verbatim from `docs/fw26_current_ceiling_governor.md` section 8.6.3
# and `docs/modeling/mpc_design_20260902_nonlinearities.md` ("2026-09-03: a
# hazard the stage model does not represent"):
#
#     No strategy may command an upward share step in the same decision as an
#     upward demand step, wherever the resulting two-source total exceeds
#     1.65 A.
#
# WHY THE HAZARD EXISTS.  fw v26's `applyShareCurrentCeilings()` clamps the
# commanded share against a ~20 ms EMA of the two-source total
# (`SHARE_GOV_FILT_ALPHA` 0.05 per tick), while the reference itself moves at
# `DROOP_RATIO_SLEW_PER_TICK` 0.02.  When BOTH axes step upward in one packet
# the slew-limited reference crosses the safe delivered share in about 4 ticks
# while the filter needs about 25 to see the new total, so the clamp holds what
# it believes is 1.2500 A while the board delivers more.  Campaign E measured
# 1.4890 A on `fw26-clamp-sweep` and latched `FAULT_OC_FC`; the filter
# under-read the rising total by 25.6 % against a 12 % design headroom.
#
# THE GUARD CONSTANT, and it has TWO derivations that must both be cited:
#   * `LIMIT_I_FC_MAX / DROOP_R_MAX` = 1.40 / 0.85 = **1.6471 A** under the
#     pre-2026-09-03 split law - the necessary condition quoted in both design
#     records and in the CLAUDE.md campaign-E addendum.  Below it the droop
#     band itself bounds the fuel-cell demand and no share step can reach the
#     fault limit.
#   * the same ratio under the CORRECTED split law (rho plus the 0.033 ohm
#     series floor, `docs/modeling/governor_split_law_20260903.md`) moves it to
#     **1.645 A**.
# The shipped constant is the 1.65 A DESIGN figure, which is above both, i.e.
# the guard engages no earlier than either derivation requires.  Named ONCE
# here; nothing else in the tree may restate the number.
SHARE_STEP_GUARD_I_TOT_A = 1.65
# The refusal reason, in the `ss_refusals` census's own vocabulary.  It counts
# CANDIDATE COLUMNS removed from block 0, not decisions - see `timing()`.
SHARE_STEP_REFUSE_UPWARD = "share_step_rising_demand"

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

# Real-time budgets (adjudication section 2.2).  THE CALLBACK BOUND, and how
# these two numbers are chosen (M1, review of 2026-09-02): a decision callback
# costs at most `BUDGET_MS_DEFAULT` plus one candidate rollout of overshoot
# (12 us), a roll slice of `ROLL_BUDGET_MS_DEFAULT` plus one chunk of overshoot
# (0.296 ms measured), and the 50 Hz surface's own work (0.17 ms measured) -
# 12.5 ms against the 20 ms command period.  The budget was 12.0 ms until the
# review; 10.0 ms buys 2 ms of headroom at no cost in search depth (budget
# expiry on 4 of 61 decisions at either value on `ems-soc-band`).
BUDGET_MS_DEFAULT = 10.0
ROLL_BUDGET_MS_DEFAULT = 2.0

# ── THE ADAPTIVE SOLVE BUDGET (2026-09-02) ──────────────────────────────────
# The banner above is the callback bound, and it was being spent as a FIXED
# 10 ms whatever the rest of the callback actually cost.  Campaign C measured
# the consequence: `ems-mpc-cross` ran a median solve of 10.002 ms and expired
# the budget on 57.4 % of its decisions, and an expiry returns the shifted
# incumbent - so the search was being truncated toward standing still on the one
# leg whose stimulus most needs it.  The response is to derive the budget from
# the SAME arithmetic the banner states, per decision, rather than to patch one
# scenario's number.
#
# Every term below is a NAMED constant with its measurement, and
# `derive_budget_ms()` is the derivation.  The per-scenario `mpc_budget_ms` key
# still works and TAKES PRECEDENCE: an explicit budget disables the derivation
# entirely, which is also what makes a run bit-reproducible (M6).
COMMAND_PERIOD_MS = 20.0        # 1000 / PiCommander.PI_CMD_HZ, restated
BUDGET_MARGIN_MS = 2.0          # the stated headroom against the command period
# ⚠️ NOT RE-MEASURED IN THE fw v26 TOOLS ROUND (2026-09-02), and stated
# rather than assumed. Both constants below are wall-clock costs of the
# 50 Hz surface and of one roll chunk. The round added the fw v26
# current-ceiling clamp to `GovernorModel.step()`, which the rolls tick,
# so both are in principle affected. After the L6 constant hoist the
# clamp's per-tick cost measures at -0.5 % over 50 000 ticks (0.2312 s
# live against 0.2323 s with the ceilings out of reach, best of seven),
# i.e. inside the machine's noise, so neither constant was moved. A
# future ceiling change that is NOT free per tick must re-measure them.
SURFACE_MS_NOMINAL = 0.17       # the 50 Hz surface's own work, measured
ROLLOUT_MS_NOMINAL = 0.012      # one candidate rollout of expiry overshoot
ROLL_CHUNK_OVERSHOOT_MS = 0.296  # one TICK_CHUNK of roll-slice overshoot
BUDGET_MS_FLOOR = 4.0           # never search less than this
BUDGET_MS_CEILING = 15.0        # `ems-mpc-cross`'s hand-set budget (5f1cfed)

# ── THE LADDER COARSENING (2026-09-02) ──────────────────────────────────────
# Second line of defence, for a decision whose FULL enumeration does not fit the
# derived budget: walk a coarser subset of the ladder so the enumeration
# completes instead of being cut.  A cut search is biased (the enumeration is
# ordered outward from the incumbent, so the candidates it drops are the ones
# furthest from standing still); a coarse search is not, it is merely coarse.
#
# ── THE PER-CANDIDATE COST IS A CONSTANT, DELIBERATELY (H1, review of
# 2026-09-02) ───────────────────────────────────────────────────────────────
# The first version of this code passed the PREVIOUS decision's measured
# `solve_ms / candidates`, and that made the COMMITTED PLAN host-dependent,
# which is the M6 property this repository has already had to defend once.  The
# review measured the cliff: on `ems-soc-band` at a 15 ms budget, a projected
# cost at or under 0.030 ms keeps the full ladder and commits h2 0.009717712,
# while one at or above 0.03717 ms (= 0.85 * 15 / 343) coarsens and commits
# 0.010523689, 8.29 % more hydrogen, with the budget-expiry count still zero.
# The measured cost on one host spanned 0.0097 to 0.0261 ms across legs and
# configurations, so a 1.4x slower machine moved the headline number silently.
#
# The projection is therefore a NAMED CONSTANT and the measurement is a
# DIAGNOSTIC.  The rule is: the slowest per-candidate cost yet MEASURED on a
# live leg, plus 15 % - the same headroom factor `LADDER_ENUM_SAFETY` and the
# overcurrent margin use.  `timing()` reports the nominal, the largest cost
# actually measured, and a flag when the measurement exceeded the nominal, so
# a host slow enough to invalidate the projection is VISIBLE rather than
# silently re-planned around.
#
# RE-DERIVED 2026-09-03 (campaign hil_report_20260902_220604 F7): 0.0300 ->
# 0.0392 ms.  The 0.0300 figure was the offline round's 0.0261 ms plus 15 %,
# and it was UNDER the measurement on the board: two live legs measured
# 0.0313 and 0.0341 ms per candidate, so `candidate_cost_over_nominal` was
# raised on both and the projection was optimistic on every decision of the
# campaign.  0.0341 x 1.15 = 0.0392.
#
# THE TRADE-OFF, stated because raising this constant is not free.  A HIGHER
# projection coarsens EARLIER, so the ladder subset a decision walks is
# smaller; campaign 20260902_220604 already coarsened on 100 % of decisions
# (4-8 points searched of 9) at the old value, so the widened ladder is only
# partly realized at run time and this makes it slightly less so.  What it
# buys is the property the constant exists for: an enumeration that is
# projected to fit the budget actually fits it, so the search COMPLETES on a
# coarser subset instead of being CUT on a finer one - and a cut search is
# biased toward the incumbent while a coarse one is merely coarse.  The cost
# is bounded and measured: `test_the_committed_plan_is_insensitive_to_the_
# projection` sweeps the projection over 0.0097-0.0500 ms, which BRACKETS
# both the old and the new value, and holds the committed hydrogen to under
# 0.5 % and the cruise-share command exactly constant.
#
# RE-PINNED 2026-09-03 (campaign E, hil_report_20260903_031220, A8):
# 0.0392 -> 0.0360 ms, AND THE RULE CHANGED WITH IT.  Campaign E measured
# `candidate_cost_ms_seen` on all five live MPC legs - 0.03512, 0.03623,
# 0.03552, 0.03520 and 0.03711 ms - so 0.0392 over-estimated the measurement
# by 5.6 % to 11.6 % on every leg, and the ladder coarsened on 100 % of
# decisions (4-8 points searched of 9).
#
# THE RULE IS NOW THE MEAN, NOT THE MAXIMUM PLUS HEADROOM.  Under the old rule
# the new maximum 0.03711 would project 0.0427 and coarsen harder still.  That
# rule was written when an under-estimate had no observable, and it no longer
# does: `timing()` reports `candidate_cost_ms_seen` and raises
# `candidate_cost_over_nominal` on any decision whose measured cost exceeds the
# nominal, and a search that is nevertheless cut returns the shifted incumbent
# rather than an unsafe command.  0.0360 sits 0.5 % above the campaign-E mean
# 0.03584 and 3.0 % below the two-campaign maximum 0.03711.
#
# ⚠️ THE TRADE-OFF REVERSES DIRECTION, and is stated for the same reason the
# 0.0392 note stated its own.  A LOWER projection coarsens LATER, so a decision
# walks a finer ladder subset; the cost is that a decision whose true cost sits
# at the 0.03711 maximum may now be CUT instead of coarsened, and a cut search
# is biased toward the incumbent while a coarse one is merely coarse. The
# bracketing test `test_the_committed_plan_is_insensitive_to_the_projection`
# sweeps 0.0097-0.0500 ms, which still brackets this value; campaign F must
# read `mpc_budget_hit` and `candidate_cost_over_nominal` on every MPC leg
# before this pin is treated as settled.
#
# A caller may still pin its own value through `candidate_cost_ms`; nothing
# reads the clock for this quantity.
CANDIDATE_COST_MS_NOMINAL = 0.0360
LADDER_ENUM_SAFETY = 0.85
# Ladder sizes the coarsening may select, largest first.  Three is the floor:
# the two rails and the centre, which is the smallest set that still spans the
# band and still contains the incumbent after the union below.
#
# FOUR IS ABSENT ON PURPOSE (M1, same review).  The realised set always carries
# the centre, so at seven levels a nominal four ({0, 2, 4, 6} plus the centre 3)
# is the SAME five-point set a nominal five produces - it was admitted on an
# allowance sized for 64 candidates per option and then walked 125.  Selection
# is now made on the REALISED set size, which makes the entry not merely
# harmless but unreachable, so it is removed rather than left as dead weight.
LADDER_SIZES = (7, 5, 3)

# Governor constants read through governor_model, never re-typed.
GOV_ENTRY_A = 2.0 * gov_mod.GOV_CONST["SHARE_MINORITY_I_MIN_A"]        # 0.60 A
GOV_RELEASE_A = GOV_ENTRY_A - gov_mod.GOV_CONST["SHARE_GOV_OL_HYST_A"]  # 0.55 A
GOV_MIN_LOAD_A = gov_mod.GOV_CONST["SHARE_I_TOT_MIN_A"]                # 0.075 A
GOV_MINORITY_A = gov_mod.GOV_CONST["SHARE_MINORITY_I_MIN_A"]           # 0.30 A
GOV_TICK_S = gov_mod.GOV_CONST["POWER_BAL_PERIOD_US"] * 1e-6           # 1 ms

# ── THE OPEN-LOOP FEEDFORWARD SUBMODE (2026-09-02) ──────────────────────────
# The firmware's open-loop branch has TWO submodes, not one (docs/HIL_PLANT.md
# section 4.4; governor_model._open_loop()).  It HOLDS only while a closed-loop
# run is standing AND the commanded setpoint has not moved by more than
# SHARE_SP_CHANGE_EPS AND no isolation is outstanding.  On any other open tick
# it takes the slew-limited FEEDFORWARD branch, which writes the MDACs: the
# applied ratio walks toward the raw setpoint at DROOP_RATIO_SLEW_PER_TICK per
# 1 kHz tick, or at DROOP_RATIO_SLEW_HANDOFF_PER_TICK while the conduction-aware
# slew mode holds a channel dark, and is clipped to [DROOP_R_MIN, DROOP_R_MAX].
# A receding-horizon controller re-commands every stage, so every re-command
# landing in an open stage enters FEEDFORWARD.  These five constants are the
# whole submode; all five are READ from governor_model, never re-typed.
SHARE_SP_CHANGE_EPS = gov_mod.GOV_CONST["SHARE_SP_CHANGE_EPS"]         # 1e-4
SLEW_FULL_PER_TICK = gov_mod.GOV_CONST["DROOP_RATIO_SLEW_PER_TICK"]    # 0.02
SLEW_HANDOFF_PER_TICK = gov_mod.GOV_CONST[
    "DROOP_RATIO_SLEW_HANDOFF_PER_TICK"]                               # 0.002
HANDOFF_DWELL_MAX_TICKS = gov_mod.GOV_CONST[
    "SHARE_HANDOFF_DWELL_MAX_TICKS"]                                   # 175
HANDOFF_DARK_A = gov_mod.GOV_CONST["SHARE_HANDOFF_MIN_A"]              # 0.15 A
DROOP_R_MIN = gov_mod.GOV_CONST["DROOP_R_MIN"]                         # 0.15
DROOP_R_MAX = gov_mod.GOV_CONST["DROOP_R_MAX"]                         # 0.85

# Stage mode classes.  Named here rather than reusing governor_model.MODE_*
# because these are PREVIEW classes over a whole stage, not per-tick firmware
# modes, and conflating the two vocabularies is how a census gets misread.
STAGE_CLOSED = "closed"
STAGE_OPEN = "open"
STAGE_FROZEN = "frozen"

# The stochastic variant's chance-constraint quantile
# (sdp_ems_solver.CHARGE_QUANTILE, the same 0.90 the solver uses for admission).
STO_OC_QUANTILE = 0.90

# Transition-matrix validation tolerances, restated from
# sdp_ems_solver.load_tpm() (`np.allclose(rows, 1.0, atol=1e-9)` and
# `(tpm < -1e-15).any()`), so the two readers accept exactly the same files.
TPM_ROW_SUM_TOL = 1e-9
TPM_TOL = 1e-15

# The SDP artifact whose demand map the stochastic variant classifies against.
# READ, not re-typed (M3, review of 2026-09-02): the bin a measured bus power
# lands in must be the bin `sdp-v3` would have used, and the artifact is the
# only authority on that.  The constants below are the ASSERTION the loader
# makes against the file, not the source of the values.
SDP_POLICY_FOR_DEMAND_MAP = "sdp_policy_v3.json"
DEMAND_MAP_W_EXPECTED = (0.0, 25.0)


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


def _dp_step_discharge(soc, share, p_dem, v_bus, dt, cap_as):
    """One stage on the split control.  Returns ``(soc_next, h2_g, h2_plant_g)``."""
    sim = _load_sim()
    p_fc_bus = share * p_dem
    p_bt_bus = p_dem - p_fc_bus
    i_pack = pack_current_from_bus_power(p_bt_bus, soc)
    soc_next = soc - i_pack * dt / cap_as
    h2 = H2_GFC_DC_GAIN_GPS_PER_W * (p_fc_bus / sim.ETA_BOOST) * dt
    return soc_next, h2, h2


def _dp_step_charge(soc, p_dem, v_bus, chg_a, dt, cap_as, eta_chg=None):
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
    # `_soc_band_drain_scenarios()` and NOT the module attribute: PEP 562's
    # module `__getattr__` is consulted for an ATTRIBUTE access from outside,
    # never for a bare global name resolved inside the module itself.
    if scenario not in _soc_band_drain_scenarios():
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


# The simulator's own whitelist (hil_plant_sim.apply_scenario()), now READ FROM IT
# rather than restated.  This was the FOURTH copy of one list, and the copies had
# gone stale twice: `ems-sdp` in 2026-09-01 (defect B2) and the three
# `ems-sdp-alpha-*` sweep legs until 2026-09-03, each time producing a matched-DP
# baseline against roughly half the real demand.  A LAZY module-level read is safe
# here for the reason `_load_sim()` exists at all: this module is stdlib-only and
# the simulator import is deferred, so the value is resolved on first use.
def _soc_band_drain_scenarios():
    return tuple(_load_sim().SOC_BAND_DRAIN_SCENARIO_NAMES)


# `SOC_BAND_DRAIN_SCENARIOS` IS A REAL TUPLE, RESOLVED LAZILY THROUGH PEP 562
# (review finding L1, 2026-09-03).  It was first written as a custom object
# implementing `__contains__`/`__iter__`/`__len__`/`__eq__`, on the reasoning
# that a plain tuple would have to be built at import and would force the
# simulator import this module deliberately defers.  The reasoning holds; the
# object did not.  A name that reads as a tuple must BE one: `d[0]`, `hash(d)`,
# `json.dumps(d)` and even `d == None` all raised on the custom object, so any
# reader treating it as the tuple its name promises failed in a way the type
# gave no warning of.  A module-level `__getattr__` defers exactly as far and
# hands back the genuine article.
def __getattr__(name):
    if name == "SOC_BAND_DRAIN_SCENARIOS":
        return tuple(_soc_band_drain_scenarios())
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


def build_demand(scenario, meta, times, dt, aux_preload_a=None,
                 loss_map=None, drag_mode=None, eta_regen=None,
                 eta_chg=None, v_pack_ref=None, regen_i_max_a=None,
                 source_mode="both"):
    """Per-stage ``(v, a, p_dem, v_bus, i_total, cruise)`` lists - D7, scalar.

    A term-for-term port of gen_dp_ems_table.build_demand(), including the
    Picard iterations on the droop node and the central-difference acceleration.

    ``loss_map`` (2026-09-02) selects the DEMAND-MODEL ERA and is threaded in
    LOCKSTEP with the generator and ``ems_walk``: ``None`` is the loss-map-free
    model, a dict prices the plant's static losses and the realized
    ``--droop design`` bus law.  ``test_mpc_ems.py`` asserts the three demand
    models agree stage for stage on a random preview in BOTH eras; that
    equality is the only thing keeping the planner's prediction and the bound
    it is scored against on one model.

    ``drag_mode`` and ``eta_regen`` (2026-09-02) select the ROAD-LOAD PROFILE
    and the REGEN DEMAND ERA, threaded in the same LOCKSTEP and defaulting to
    the same pre-round configuration.  The seventh return element ``i_regen``
    is the pack charge current a braking stage delivers, all zeros in the
    pre-regen era.

    ⚠️ THE RETRACTED STATEMENT.  This docstring used to say the model
    "over-states demand on decelerating stages".  It does not and never did:
    ``max(0, F*v)`` and the plant both bill ZERO motor demand while ``F*v < 0``.
    What the pre-regen model omitted is the ENERGY THE PLANT GIVES BACK, a
    CREDIT to the battery rather than a load, so the omission's sign was
    backwards.  With ``eta_regen`` set the credit is modelled and the
    controller's prediction and the DP bound carry the same one."""
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

    k_air = sim.drag_k_air(sim.DRAG_MODE_RIG if drag_mode is None
                           else drag_mode)
    eta_regen = regen_mod.check_eta_regen(eta_regen)
    if eta_regen is not None and (v_pack_ref is None or regen_i_max_a is None):
        raise ValueError(
            "build_demand needs v_pack_ref and regen_i_max_a when eta_regen "
            "is set - see the generator's own note on state-independence")
    p_mech = [0.0] * n
    i_regen = [0.0] * n
    for k in range(n):
        if k_air:
            force = sim.M_EFF * a[k] + k_air * v[k] * abs(v[k])
        else:
            if v[k] > sim.V_STICTION:
                f_coul = sim.F_COULOMB
            elif v[k] < -sim.V_STICTION:
                f_coul = -sim.F_COULOMB
            else:
                f_coul = 0.0
            force = sim.M_EFF * a[k] + f_coul + sim.B_EFF * v[k]
        p_mech[k] = max(0.0, force * v[k])
        if eta_regen is not None:
            i_regen[k] = regen_mod.regen_pack_current_from_force_a(
                force, v[k], eta_regen=eta_regen, eta_chg=eta_chg,
                v_pack_v=float(v_pack_ref), k_f=sim.K_F,
                i_clip_a=sim.VESC_REGEN_I_MAX_A,
                i_max_a=float(regen_i_max_a))

    lm = sim.check_loss_map(loss_map)
    i_total = [0.0] * n
    p_dem = [0.0] * n
    if lm is None:
        v_bus = [sim.V_BUS_DROOP_V0] * n
        for _ in range(4):
            for k in range(n):
                i_motor = p_mech[k] / (sim.ETA_BOOST * v_bus[k])
                i_total[k] = i_motor + i_aux[k]
                v_bus[k] = (sim.V_BUS_DROOP_V0
                            - sim.K_DROOP_BUS_SHARED * i_total[k])
        for k in range(n):
            i_motor = p_mech[k] / (sim.ETA_BOOST * v_bus[k])
            i_total[k] = i_motor + i_aux[k]
            p_dem[k] = v_bus[k] * i_total[k]
    else:
        # ``source_mode`` selects the BUS TOPOLOGY (2026-09-02, the MPC 0/1
        # round).  "both" is the two-source law the map was fitted on and is
        # bit-identical to the pre-round code; "fc"/"bt" are the measured
        # single-source law, which is the same slope scaled and its own no-load
        # intercept (hil_plant_sim.single_source_bus_law).  It matters: at
        # 1.6 A the two differ by ~0.5 V of bus voltage.
        v0, k_eff = sim.single_source_bus_law(lm, source_mode)
        g_bus, g_oth = lm["g_node_bus"], lm["g_node_other"]
        v_fwd, r_on = lm["rt_v_fwd"], lm["rt_r_on"]
        v_bus = [v0] * n
        for _ in range(sim.DP_LOSS_MAP_PICARD_ITERS):
            for k in range(n):
                i_motor = p_mech[k] / (sim.ETA_BOOST * v_bus[k])
                v_mot = ((v_bus[k] - v_fwd - r_on * i_motor)
                         / (1.0 + r_on * g_oth))
                i_par = v_bus[k] * g_bus + v_mot * g_oth
                i_total[k] = i_motor + i_aux[k] + i_par
                v_bus[k] = v0 - k_eff * i_total[k]
        for k in range(n):
            i_motor = p_mech[k] / (sim.ETA_BOOST * v_bus[k])
            v_mot = (v_bus[k] - v_fwd - r_on * i_motor) / (1.0 + r_on * g_oth)
            i_par = v_bus[k] * g_bus + v_mot * g_oth
            i_total[k] = i_motor + i_aux[k] + i_par
            p_dem[k] = v_bus[k] * i_total[k]

    cruise = [(abs(a[k]) <= sim.SOC_BAND_CRUISE_SLOPE_MAX
               and v[k] >= sim.SOC_BAND_CRUISE_MIN_MPS) for k in range(n)]
    return v, a, p_dem, v_bus, i_total, cruise, i_regen


def charge_mask(times, p_dem, v_bus, cruise, chg_ceiling_a, run_exit_s,
                eta_chg=None, v_pack_ref=None, i_regen=None):
    """Per-stage boolean: may a charge window open here? - D10, scalar port.

    ``i_regen`` (2026-09-02) carries the EXCLUSIVITY term: a stage cannot both
    FC-charge and regen-charge, because ``assertFcChargeEnable()`` drives REGEN
    LOW before it raises FC_CHARGE and ``detectFaults()`` latches
    FAULT_SWITCH_CONFLICT on the illegal pair."""
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
        if i_regen is not None and i_regen[k] > 0.0:
            budget_ok = False
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
    tpm = [[data[j * rows + i] for j in range(cols)] for i in range(rows)]
    # The two checks sdp_ems_solver.load_tpm() makes, ported (M7, review of
    # 2026-09-02).  A matrix that is not row-stochastic is not a transition
    # matrix, and the forecast built from one is a number with no meaning; the
    # tolerance is the solver's own.
    for i, row in enumerate(tpm):
        neg = [j for j, x in enumerate(row) if x < -TPM_TOL]
        if neg:
            raise ValueError("%s[%s] row %d holds negative probabilities at "
                             "columns %s" % (path, name, i, neg[:8]))
        rs = math.fsum(row)
        if abs(rs - 1.0) > TPM_ROW_SUM_TOL:
            raise ValueError("%s[%s] row %d sums to %.12g, not 1 (tolerance "
                             "%g): this is not a transition matrix"
                             % (path, name, i, rs, TPM_ROW_SUM_TOL))
    return tpm


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
    # THE BRAKING CREDIT [A into the pack] (2026-09-02), per preview sample.
    # Empty on a pre-regen preview, which every consumer reads as zero.
    i_regen: list = field(default_factory=list)
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
    # Stage-mean braking credit [A].  The MEAN is the right reduction: the
    # rollout integrates it over `dt_dec`, so mean x dt_dec is exactly the
    # charge the sub-samples deliver.  Zero on a pre-regen preview.
    i_regen_mean: list = field(default_factory=list)
    # ABSOLUTE preview sample at each stage's start.  The transition-roll table
    # is keyed on this, not on the horizon-relative index: a table computed at
    # one decision may still be in use one or two decisions later (it is sliced
    # across the callbacks), by which time the horizon has receded and a
    # relative key would silently point at the WRONG stage.
    stage_key: list = field(default_factory=list)
    # The governor mode standing as each stage OPENS, i.e. the last sub-sample
    # of the stage before it (``mode_seed`` for stage 0).
    mode_entry: list = field(default_factory=list)
    # STICKY: has a closed-loop run occurred at or before this stage's opening?
    # A transition roll needs it.  `closed_loop_run` - the flag that makes an
    # UNCHANGED setpoint HOLD instead of slewing the MDACs - is set by a
    # closed-loop run and cleared ONLY by a setpoint change
    # (governor_model._open_loop, .ino:10147-10213), so it survives an arbitrary
    # number of open stages.  A roll assumes the command is HELD across the
    # transition (candidate_fable section 2.2), and under a held command the
    # flag therefore never clears - which is what makes this sticky rather than
    # a copy of `mode_entry`.
    run_entry: list = field(default_factory=list)
    # Sub-samples whose preview index was clamped to the end of the run (L6).
    beyond_preview: int = 0


def precompute_stages(prev, k0, horizon, dt_dec=DECISION_DT_S,
                      mode_seed=STAGE_CLOSED, chg_seed=None):
    """Classify ``horizon`` decision stages from preview sample ``k0``.

    ``mode_seed`` is the governor's mode as the horizon opens; the hysteresis is
    carried forward from it, so a horizon that starts inside a closed-loop run
    does not re-derive the entry threshold from nothing.  ``chg_seed`` is the
    charge mask's standing value at the same instant, for the same reason.

    ``transition[j]`` marks a stage a roll must cover.  A stage qualifies on a
    GOVERNOR mode change (``GOV_ENTRY_A`` upward, ``GOV_RELEASE_A`` downward
    - 0.30 / 0.25 A at fw v27 rev 2) OR on a CHARGE-MASK
    edge: a window opening or closing takes BT off or back onto the bus, which
    moves the ratio exactly as a mode change does (adjudication section 2.1
    names all four classes; the charge pair was missing until M5, review of
    2026-09-02).

    ⚠️ BEYOND THE PREVIEW the sample index is CLAMPED to the last one, and
    ``beyond_preview`` counts the sub-samples that fall there.  On every
    registered stimulus the profile ends at standstill, so the clamped sample
    carries the auxiliary load alone (``I_AUX_A`` plus any declared preload) -
    the clamp and "hold I_AUX_A" are the same model here.  They would NOT be
    the same on a profile ending under load, and no such profile is registered
    for this strategy (design document section 9)."""
    n_sub = int(round(dt_dec / prev.dt))
    out = StagePrecompute(n=horizon)
    mode = mode_seed
    run_seen = (mode_seed == STAGE_CLOSED)
    chg_state = chg_seed
    npv = len(prev.times)
    for j in range(horizon):
        it, pd, vb, lo, md, ok = [], [], [], [], [], True
        reg_acc = 0.0
        reg_src = prev.i_regen
        out.mode_entry.append(mode)
        out.run_entry.append(run_seen)
        changed = False
        for s in range(n_sub):
            k_raw = k0 + j * n_sub + s
            k = min(npv - 1, k_raw)
            if k_raw >= npv:
                out.beyond_preview += 1
            i_tot = prev.i_total[k]
            # Settled-filter classification with the firmware's own hysteresis
            # (.ino:10126-10145): entry at GOV_ENTRY_A, release at
            # GOV_RELEASE_A (0.30 / 0.25 A at fw v27 rev 2, both derived
            # from SHARE_MINORITY_I_MIN_A).
            if i_tot < GOV_MIN_LOAD_A:
                m = STAGE_FROZEN
            elif mode == STAGE_CLOSED:
                m = STAGE_CLOSED if i_tot >= GOV_RELEASE_A else STAGE_OPEN
            else:
                m = STAGE_CLOSED if i_tot > GOV_ENTRY_A else STAGE_OPEN
            if m != mode:
                changed = True
            mode = m if m != STAGE_FROZEN else mode
            if m == STAGE_CLOSED:
                run_seen = True
            it.append(i_tot)
            pd.append(prev.p_dem[k])
            vb.append(prev.v_bus[k])
            lo.append(min(0.5, GOV_MINORITY_A / i_tot) if i_tot > 0.0 else 0.5)
            reg_acc += (reg_src[k] if k < len(reg_src) else 0.0)
            md.append(m)
            c = bool(prev.chg_ok[k])
            if chg_state is None:
                chg_state = c
            elif c != chg_state:
                changed = True
                chg_state = c
            ok = ok and c
        out.i_tot.append(it)
        out.p_dem.append(pd)
        out.v_bus.append(vb)
        out.lo.append(lo)
        out.mode.append(md)
        out.chg_ok.append(ok)
        out.i_regen_mean.append(reg_acc / n_sub)
        out.transition.append(changed)
        # THE ABSOLUTE STAGE KEY, on the DECISION grid rather than the preview
        # grid.  A key of `k0 + j*n_sub` is a preview-sample index, and the
        # decisions do not land on the preview grid: they fire at 1.02 s
        # intervals (section 1.1), so `k0` advances by 9, 10 or 11 samples and a
        # table written at one decision missed the next decision's keys on two
        # deltas out of three.  Measured lookup hit rate 5.39 % against the
        # 8.75 % the transition census allows; keying on the stage's own start
        # time recovers it.  Ties at the half-sample are one-stage shifts, which
        # is the same approximation the preview-sample key already made.
        out.stage_key.append(int(round((k0 + j * n_sub) * prev.dt / dt_dec)))
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
                 max_transitions=None, droop_scale_fc=1.0, r_series_ohm=0.0):
        self.pre = pre
        self.ladder = list(ladder)
        self.dt_dec = float(dt_dec)
        self.dv0_v = float(dv0_v)
        # The other two split-law parameters (2026-09-03).  See the block in
        # `MpcStrategy.__init__` for why all three travel together.
        self.droop_scale_fc = float(droop_scale_fc)
        self.r_series_ohm = float(r_series_ohm)
        self.tick_s = float(tick_s)
        self.charge_stage = charge_stage or (lambda j: False)
        cap = self.MAX_TRANSITIONS if max_transitions is None else int(max_transitions)
        # The CHARGE-OPTION boundary is a transition class too (M5): the option
        # this job is built for takes BT off the bus at the window it opens and
        # puts it back at the close, and the ratio standing at each edge is what
        # the following open stages carry.  `pre.transition` already carries the
        # PREVIEW's own chg_ok edges; this adds the edges of the OPTION.
        cand = set(j for j in range(pre.n) if pre.transition[j])
        prev_c = None
        for j in range(pre.n):
            c = bool(self.charge_stage(j))
            if prev_c is not None and c != prev_c:
                cand.add(j)
            prev_c = c
        ordered = sorted(cand)
        stages = ordered[:cap]
        self.transition_stages = stages
        self.dropped_transitions = len(ordered) - len(stages)
        self.items = [(j, si) for j in stages
                      for si in range(len(self.ladder))]
        self.stage_key = list(pre.stage_key)
        self.cursor = 0
        self.table = {}
        # Parallel to `table`: True where the roll ENDED in the conduction-
        # handoff slew mode, i.e. `updateShareSlewMode()` had a channel dark and
        # the 0.002/tick ceiling was in force.  The feedforward stage model
        # reads it to pick the tick ceiling for the stages the roll covers.
        self.handoff = {}
        self.rolls = 0
        self.chunks = 0
        self._cur = None            # a partially-rolled item, resumed next call

    @property
    def done(self):
        return self.cursor >= len(self.items)

    # PER-TICK CHUNKING (M1, review of 2026-09-02).  One item is 1000 governor
    # ticks and cost 2.761 ms measured, so an `advance()` that checked the clock
    # only BETWEEN items overran a 2.0 ms slice by more than the slice itself,
    # and the callback bound derived from it was not the bound.  The roll is now
    # resumable at TICK_CHUNK granularity, so an overrun is bounded by the cost
    # of one chunk instead of the cost of one item.
    TICK_CHUNK = 100

    def advance(self, budget_s):
        """Run work for at most ``budget_s`` seconds of wall clock.

        Progress is GUARANTEED: at least one chunk runs per call, so a zero
        budget still advances and the job can never livelock."""
        t0 = time.perf_counter()
        while self.cursor < len(self.items):
            if self._cur is None:
                j, si = self.items[self.cursor]
                self._cur = self._roll_begin(j, si)
            self.chunks += 1
            if self._roll_chunk(self._cur, self.TICK_CHUNK):
                j, si = self.items[self.cursor]
                self.table[(self.stage_key[j], si)] = self._cur["r_end"]
                self.handoff[(self.stage_key[j], si)] = self._cur["handoff_end"]
                self._cur = None
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

    def _roll_begin(self, j, si):
        """Seed one exact 1 kHz roll of stage ``j`` under ladder point ``si``.

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
                                  droop_scale_fc=self.droop_scale_fc,
                                  r_series_ohm=self.r_series_ohm,
                                  seed_r=seed)
        # Enter the stage already in a converged closed-loop run when the
        # preview says the stage opens closed; otherwise let the model decide.
        g.state.filt_total = pre.i_tot[j][0]
        # ── SEEDING THE HOLD FLAG ──────────────────────────────────────────
        # `closed_loop_run` is what makes the firmware's open-loop branch HOLD a
        # converged split instead of slewing the MDACs toward the setpoint.  It
        # is set by a closed-loop run and cleared ONLY by a setpoint change, so
        # under this roll's held-command assumption it is STICKY - `run_entry`.
        # Seeding it from THIS stage's opening mode alone (the shipped code
        # until the review of 2026-09-02) made every roll of an already-open
        # stage take the feedforward branch and return the commanded share, i.e.
        # it predicted a slew the firmware does not perform.  Measured on
        # `ems-soc-band` that mis-seeding cost a Gate 1 mean of 0.00562 against
        # 0.00390 for a table that was never consulted at all: the roll table
        # was ACTIVELY WORSE than no table.
        run_entry = (pre.run_entry[j] if pre.run_entry
                     else pre.mode[j][0] == STAGE_CLOSED)
        if pre.mode[j][0] == STAGE_CLOSED:
            g.state.closed_loop_mode = True
        if run_entry or pre.mode[j][0] == STAGE_CLOSED:
            g.state.closed_loop_run = True
            g.state.acted_sp = s
        # ── SEEDING THE CONDUCTION-HANDOFF STATE (2026-09-02) ───────────────
        # `updateShareSlewMode()`'s two channel filters and its two dark flags
        # are RUN state, and `GovernorState` starts them at zero and True.  A
        # roll that inherits those defaults spends its opening ticks on the
        # 0.002/tick handoff ceiling, and can END dark, for a reason that is the
        # seeding and not the stage: measured on `ems-soc-band`, 104 of 196
        # published roll entries carried a handoff flag under the default
        # seeding, and consulting that flag COST Gate 1 - 0.000329 mean against
        # 0.000095 with the flag ignored.  This is the same class of defect as
        # the mis-seeded hold flag the review of 2026-09-02 found, and the same
        # remedy: seed the state from the stage's own entry currents.
        i_tot0 = pre.i_tot[j][0]
        g.state.handoff_i_fc_filt = abs(seed * i_tot0)
        g.state.handoff_i_bt_filt = abs((1.0 - seed) * i_tot0)
        g.state.dark_fc = (g.state.handoff_i_fc_filt
                           < gov_mod.GOV_CONST["SHARE_HANDOFF_MIN_A"])
        g.state.dark_bt = (g.state.handoff_i_bt_filt
                           < gov_mod.GOV_CONST["SHARE_HANDOFF_MIN_A"])
        g.state.handoff_prev_ratio = seed
        n_sub = len(pre.i_tot[j])
        ticks = int(round(self.dt_dec / self.tick_s))
        return {"j": j, "s": s, "g": g, "delivered": seed, "tk": 0,
                "ticks": ticks, "n_sub": n_sub,
                "per": max(1, ticks // n_sub),
                "charging": bool(self.charge_stage(j)), "r_end": seed,
                "handoff_end": False}

    def _roll_chunk(self, st, n_ticks):
        """Advance a seeded roll by at most ``n_ticks``.  True when complete."""
        pre = self.pre
        j, s, g = st["j"], st["s"], st["g"]
        per, n_sub = st["per"], st["n_sub"]
        charging = st["charging"]
        sw_bt = not charging
        delivered = st["delivered"]
        end = min(st["ticks"], st["tk"] + int(n_ticks))
        for tk in range(st["tk"], end):
            sub = min(n_sub - 1, tk // per)
            i_tot = pre.i_tot[j][sub]
            i_fc = delivered * i_tot
            o = g.step(s, i_fc, i_tot - i_fc, True, sw_bt,
                       tk * self.tick_s, charge_path_owns_bt=charging)
            delivered = g.delivered_share(o.r_applied, i_tot,
                                          o.fc_bus_req, o.bt_bus_req)
        st["tk"] = end
        st["delivered"] = delivered
        st["r_end"] = g.state.r_prev
        st["handoff_end"] = bool(g.state.dark_fc or g.state.dark_bt)
        return end >= st["ticks"]

    def _roll(self, j, si):
        """One complete roll, unsliced - the equality reference for the tests."""
        st = self._roll_begin(j, si)
        while not self._roll_chunk(st, st["ticks"]):
            pass
        return st["r_end"]


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
# The open-loop FEEDFORWARD ramp, in closed form.
# ─────────────────────────────────────────────────────────────────────────────
def ramp_mean(r0, target, n_ticks, step_fast=SLEW_FULL_PER_TICK,
              step_slow=None, dwell_left=0):
    """Mean applied ratio over ``n_ticks`` of a slew-limited feedforward.

    Returns ``(mean_ratio, end_ratio, dwell_left_after)``.

    The firmware writes one ratio per 1 kHz tick, and the ratio after tick ``k``
    is ``r0 + sign * min(k * step, |target - r0|)`` for whichever step ceiling
    ``updateShareSlewMode()`` selected on that tick.  The mean over a whole
    sub-sample is therefore an arithmetic series, and this function evaluates it
    in closed form rather than ticking: a per-tick loop would cost 100 evaluations
    per sub-sample and the decision budget of section 2.2 does not have them.

    ``step_slow`` is the conduction-handoff ceiling.  It applies for at most
    ``dwell_left`` MOVING ticks, which is ``SHARE_HANDOFF_DWELL_MAX_TICKS``
    counted down by ``_slew_mode()``'s motion gate; the full ceiling resumes when
    the allowance is spent.  Passing ``step_slow=None`` selects the full ceiling
    throughout."""
    n = int(n_ticks)
    if n <= 0:
        return float(r0), float(r0), int(dwell_left)
    r = float(r0)
    d = float(target) - r
    if d == 0.0:
        return r, r, int(dwell_left)
    sgn = 1.0 if d > 0.0 else -1.0
    d = abs(d)
    acc = 0.0
    left = n
    dw = int(dwell_left)
    segments = []
    if step_slow is not None and step_slow > 0.0 and dw > 0:
        segments.append((float(step_slow), dw))
    segments.append((float(step_fast), n))
    for step, cap in segments:
        if left <= 0 or d <= 0.0:
            break
        m = min(left, cap, int(math.ceil(d / step - 1e-12)))
        if m <= 0:
            continue
        full = min(m, int(math.floor(d / step + 1e-12)))
        # Ticks 1..full take a whole step; any remaining tick of this segment
        # lands exactly on the target.
        acc += m * r + sgn * (step * full * (full + 1) / 2.0 + (m - full) * d)
        moved = min(m * step, d)
        r += sgn * moved
        d -= moved
        left -= m
        if step_slow is not None and step == step_slow:
            dw -= m
    if left > 0:
        acc += left * r
    return acc / n, r, max(0, dw)


# ─────────────────────────────────────────────────────────────────────────────
# The adaptive budget and the ladder coarsening.
# ─────────────────────────────────────────────────────────────────────────────
def derive_budget_raw_ms(roll_slice_ms=None, surface_ms=None, rollout_ms=None,
                         command_period_ms=COMMAND_PERIOD_MS,
                         margin_ms=BUDGET_MARGIN_MS):
    """The callback bound's own arithmetic, UNCLAMPED.

    Split out from `derive_budget_ms()` so a caller can tell a budget the bound
    produced from one the floor imposed (M2, review of 2026-09-02).  A negative
    or tiny value here means the rest of the callback has already spent the
    command period, and the floor the clamped function applies is then a
    DEVIATION FROM THE BOUND rather than an application of it."""
    roll = (ROLL_BUDGET_MS_DEFAULT + ROLL_CHUNK_OVERSHOOT_MS
            if roll_slice_ms is None else float(roll_slice_ms))
    surf = SURFACE_MS_NOMINAL if surface_ms is None else float(surface_ms)
    roll_out = ROLLOUT_MS_NOMINAL if rollout_ms is None else float(rollout_ms)
    return float(command_period_ms) - float(margin_ms) - roll - surf - roll_out


def derive_budget_ms(roll_slice_ms=None, surface_ms=None, rollout_ms=None,
                     command_period_ms=COMMAND_PERIOD_MS,
                     margin_ms=BUDGET_MARGIN_MS,
                     floor_ms=BUDGET_MS_FLOOR, ceiling_ms=BUDGET_MS_CEILING):
    """The solve budget for one decision, from the callback bound's own terms.

    The bound stated at ``BUDGET_MS_DEFAULT`` is

        budget + one rollout of overshoot
              + the roll slice + one chunk of overshoot
              + the 50 Hz surface's own work            <=  the command period

    so the budget is what the command period has left after the other three
    terms and a stated margin.  Each term is MEASURED where the caller has a
    measurement and falls back to its nominal constant where it does not; the
    result is clamped to ``[floor_ms, ceiling_ms]`` so a pathological measurement
    can neither starve the search nor spend the whole period on it.

    ⚠️ THE FLOOR IS NOT PART OF THE BOUND (M2, review of 2026-09-02).  Once the
    rest of the callback costs more than ``command_period_ms - margin_ms -
    floor_ms``, the floor keeps the search alive at the price of a callback total
    that EXCEEDS the command period - a roll slice of 18 ms puts the total at
    22.2 ms.  `derive_budget_raw_ms()` returns the unclamped value so the caller
    can tell the two apart, and `MpcStrategy.timing()` reports
    ``budget_floor_binding`` as the count of decisions on which it did.

    ⚠️ THE RESULT IS WALL-CLOCK DERIVED, and a trajectory that depends on it is
    host-dependent in exactly the way review M6 names.  The levers against that
    are unchanged: an explicit ``budget_ms`` disables this function outright, and
    ``max_candidates`` bounds the search deterministically whatever the clock
    says.  The SEARCH WIDTH no longer is: `coarsen_ladder()` projects on a named
    constant, never on a measurement."""
    b = derive_budget_raw_ms(roll_slice_ms, surface_ms, rollout_ms,
                             command_period_ms, margin_ms)
    return min(float(ceiling_ms), max(float(floor_ms), b))


def coarse_ladder_set(n_levels, k, incumbent=None):
    """The REALISED ladder-index set for a nominal coarse size ``k``.

    Three unions, and each has a reason:

    * the two RAILS and the CENTRE, so the set always spans the band and always
      contains a middle point whatever ``k`` is;
    * ``k`` evenly spaced indices, which is the coarsening proper;
    * the incumbent's block indices AND THEIR IMMEDIATE NEIGHBOURS.

    The neighbours are the H1 fix of the review of 2026-09-02.  At seven levels
    the evenly-spaced rule can only ever produce ``{0, 2, 3, 4, 6}`` or
    ``{0, 3, 6}``, so indices 1 and 5 are STRUCTURALLY UNREACHABLE on a
    coarsened decision - and index 5 is 0.6667, the cruise share `mpc-det`
    actually commands on 260 of 610 commands over `ems-soc-band`.  Unioning the
    incumbent alone lets the controller HOLD such a point but never REACH one,
    which is a ratchet, not a coarsening.  With the neighbours in, any index is
    two coarsened decisions away from any other."""
    n_levels = int(n_levels)
    idx = {0, n_levels - 1, (n_levels - 1) // 2}
    k = int(k)
    if k > 1:
        for i in range(k):
            idx.add(int(round(i * (n_levels - 1) / float(k - 1))))
    for v in (incumbent or ()):
        v = int(v)
        if 0 <= v < n_levels:
            for w in (v - 1, v, v + 1):
                if 0 <= w < n_levels:
                    idx.add(w)
    return tuple(sorted(i for i in idx if 0 <= i < n_levels))


def coarsen_ladder(n_levels, n_blocks, n_options, incumbent=None,
                   budget_ms=BUDGET_MS_DEFAULT, n_transitions=0,
                   transition_heavy=None, sizes=LADDER_SIZES,
                   candidate_cost_ms=CANDIDATE_COST_MS_NOMINAL,
                   safety=LADDER_ENUM_SAFETY):
    """The ladder INDICES this decision's enumeration walks.

    Returns a sorted tuple of indices into the planner's fixed ladder.  The
    ladder itself never changes - the roll table is keyed on ``(stage key, ladder
    index)`` and a ladder that moved under it would silently re-point every
    entry - so the coarsening restricts the SEARCH and nothing else.

    The rule is: take the largest admissible ladder size whose REALISED set - the
    one `coarse_ladder_set()` builds, unions and all - has a full enumeration
    ``n_options * len(set) ** n_blocks`` fitting ``safety * budget_ms /
    candidate_cost_ms``, halving that allowance on a TRANSITION-HEAVY horizon
    (at least ``transition_heavy`` previewed transition stages, which defaults to
    the roll cap ``RollJob.MAX_TRANSITIONS`` - a horizon with more transitions
    than the roll table can carry is one whose callback has least room).

    ⚠️ THE SELECTION IS ON THE REALISED SET, NOT ON ``k`` (M1, review of
    2026-09-02).  The unions can only ever ADD points, so budgeting a nominal
    ``k`` and then walking a larger set is a projection that is wrong in the one
    direction the budget cannot absorb.

    PURE, AND WALL-CLOCK-FREE.  ``candidate_cost_ms`` defaults to a named
    constant and no caller passes a measurement, so with a fixed ``budget_ms``
    the whole rule is a function of the configuration.  Under the adaptive
    budget the width still moves with the budget, but only in the coarse steps
    this size list allows."""
    n_levels = int(n_levels)
    full = tuple(range(n_levels))
    if n_levels < 3 or n_blocks < 1:
        return full
    heavy = (RollJob.MAX_TRANSITIONS if transition_heavy is None
             else int(transition_heavy))
    allowance = float(safety) * float(budget_ms) / float(candidate_cost_ms)
    if int(n_transitions) >= heavy:
        allowance *= 0.5
    admissible = sorted({k for k in sizes if 3 <= k <= n_levels}, reverse=True)
    if not admissible:
        return full
    chosen = None
    for k in admissible:
        cand = coarse_ladder_set(n_levels, k, incumbent)
        # `float(n_options)`, not `int()` (2026-09-03): the MPC's
        # single-source round passes a FRACTIONAL option count to charge the
        # extra block-0 columns to the same allowance, and `int()` truncated
        # that surcharge away.  Every integer caller is unaffected.
        if float(n_options) * len(cand) ** int(n_blocks) <= allowance:
            chosen = cand
            break
    if chosen is None:
        # Nothing fits.  The smallest set is the floor: a search that cannot be
        # made to fit is still run, and the budget expiry reports it.
        chosen = coarse_ladder_set(n_levels, admissible[-1], incumbent)
    if len(chosen) >= n_levels:
        return full
    return chosen


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
    cap_hit: bool = False
    worst_violation_a: float = 0.0
    candidates: int = 0
    pruned: int = 0
    share_pred: float = 0.5       # predicted DELIVERED share of stage 0
    feasible: bool = True
    ladder_points: int = 0        # ladder points this decision's search walked
    # ── SINGLE-SOURCE (2026-09-03) ─────────────────────────────────────────
    # `single_source` names the SURVIVING source ("fc"/"bt") when the committed
    # block-0 command is one of the two single-source columns, and is None
    # otherwise - which is every decision of a run with the feature off.
    single_source: object = None
    ss_offered: int = 0           # admissible single-source columns searched
    # ── THE SHARE-STEP GUARD (2026-09-03) ──────────────────────────────────
    # `share_step_guarded` is True on a decision whose block-0 column set was
    # filtered by the rule; `share_step_refused` counts the columns it removed.
    # Both are 0/False on every decision the guard did not fire on, which is
    # every decision of every registered stimulus.
    share_step_guarded: bool = False
    share_step_refused: int = 0


class Planner:
    """Move-blocked enumeration with warm start and branch-and-bound.

    The search carries the governor state EXACTLY along each candidate through
    the precomputed tables, which a state-space dynamic program cannot do
    without an 882-state governor axis (candidate_opus section 3.1)."""

    def __init__(self, *, horizon=HORIZON_N, blocks=MOVE_BLOCKS,
                 share_band=SHARE_BAND_DP, share_levels=SHARE_LEVELS,
                 terminal_mode="metric", budget_ms=BUDGET_MS_DEFAULT,
                 max_candidates=None,
                 eta_chg=chg_mod.ETA_CHG_DEFAULT, chg_a=0.8,
                 cap_as=5.0 * 3600.0, h2_map="proxy", h2_convex=None,
                 dt_dec=DECISION_DT_S, dv0_v=0.0, ff_dark_model=False,
                 single_source=False, droop_scale_fc=1.0, r_series_ohm=0.0):
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
        # ── THE SINGLE-SOURCE COLUMNS (2026-09-03) ─────────────────────────
        # Appended AFTER the in-band ladder, so every index the coarsening, the
        # roll table and every pre-2026-09-03 caller use keeps its meaning.
        # `n_band` is the number of IN-BAND rungs and is what `coarsen_ladder()`
        # is sized on; `len(self.ladder)` is the full column set.  With
        # `single_source` False the two are equal and this class is bit-for-bit
        # what it was.
        self.n_band = int(share_levels)
        self.single_source = bool(single_source)
        self.ss_index = {}
        if self.single_source:
            self.ss_index = {SS_MODE_BT: len(self.ladder),
                             SS_MODE_FC: len(self.ladder) + 1}
            self.ladder = self.ladder + [SS_SHARE[SS_MODE_BT],
                                         SS_SHARE[SS_MODE_FC]]
        self.ss_mode_of = {v: k for k, v in self.ss_index.items()}
        self.terminal_mode = terminal_mode
        self.rho = terminal_price(terminal_mode)
        self.budget_ms = float(budget_ms)
        # M6 (review of 2026-09-02).  A wall-clock budget makes the trajectory
        # HOST-DEPENDENT: the same command line on a slower machine cuts the
        # search at a different candidate and can commit a different share.
        # `max_candidates` is the deterministic secondary cap a campaign leg
        # sets so its trajectory is reproducible; the wall-clock budget then
        # only ever fires as the safety net it was meant to be.  None = no cap.
        self.max_candidates = (None if max_candidates is None
                               else int(max_candidates))
        if self.max_candidates is not None and self.max_candidates < 1:
            raise ValueError("max_candidates must be at least 1")
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
        # ── THE ASYMMETRY MAP (item 7 of the nonlinearity survey) ───────────
        # `dv0_v` is the converter-asymmetry offset the plant runs with.  At the
        # module default of 0.0 the droop map degenerates to the identity, so
        # the delivered share and the applied ratio are the same number and
        # every table below is bit-identical to the pre-2026-09-02 one.  A
        # non-zero value maps the OPEN-loop ratio through
        # `governor_model.GovernorModel.delivered_share()`; the CLOSED loop
        # corrects the offset out by integral action, so its surrogate is
        # unchanged in either case.
        self.dv0_v = float(dv0_v)
        # The other two split-law parameters (2026-09-03).  See the block in
        # `MpcStrategy.__init__` for why all three travel together.
        #
        # THE `_map is None` SHORTCUT KEYS ON ALL THREE (N2).  It used to key on
        # `dv0_v == 0.0` alone, which stopped meaning "the map is the identity"
        # the moment R_f entered the law: an `--asymmetry off` run would keep
        # the WRONG map (no map at all) while its plant realizes the 0.033 ohm
        # floor.  The predicate is asked of `GovernorModel` rather than
        # re-derived here, so the two cannot drift.
        self.droop_scale_fc = float(droop_scale_fc)
        self.r_series_ohm = float(r_series_ohm)
        _m = gov_mod.GovernorModel(dt_s=GOV_TICK_S, dv0_v=self.dv0_v,
                                   droop_scale_fc=self.droop_scale_fc,
                                   r_series_ohm=self.r_series_ohm)
        self._map = None if _m.map_is_identity() else _m
        # ── THE HANDOFF CEILING, AND WHY THE DEFAULT IS `False` ────────────
        # `updateShareSlewMode()` selects the 0.002/tick ceiling while a channel
        # is DARK, and the dark flags are FILTERED (0.05/tick) with hysteresis
        # (live 0.20 A, dark 0.15 A).  `True` adds an INSTANTANEOUS proxy for
        # them, evaluated on the sub-sample's own entry currents.  It is a
        # proxy, and it was measured to be a worse one than trusting the roll's
        # own flag alone: Gate 1 on `ems-soc-band` reads 0.000315 mean with the
        # proxy and 0.000095 without it, because the proxy declares a channel
        # dark where the filter's hysteresis has already released it and the
        # modelled ramp is then ten times too slow.  The roll's flag, which is
        # the real filtered state at a rolled stage's end, is consulted in
        # either setting.
        self.ff_dark_model = bool(ff_dark_model)
        # Diagnostics: how much of the table the new branch actually built.
        self.ff_cells = 0
        self.hold_cells = 0
        self.closed_cells = 0

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
    # -- the two open-loop submodes ----------------------------------------
    def _alpha(self, r, i_tot):
        """Delivered share for an applied ratio, under the asymmetry map."""
        if self._map is None:
            return r
        return self._map.delivered_share(r, i_tot, True, True)

    def _ratio_for(self, alpha, i_tot):
        """The applied ratio whose delivered share is ``alpha`` - the inverse.

        Reaches `GovernorModel._ratio_for_delivered()` deliberately: it is the
        exact inverse of the map `_alpha()` uses, and re-deriving the quadratic
        here would be a second copy of a law that has one authority."""
        if self._map is None:
            return alpha
        return self._map._ratio_for_delivered(alpha, i_tot)

    def delivery_table(self, pre, r_hold, r_seed, charge_stages, i_tot_oc=None,
                       soc_hint=0.6, sp_acted=None, run_seed=None,
                       handoff=None, active=None, pre_ss=None):
        """Per (stage, ladder point): delivered share, FC power, BT power, feasibility.

        This is the whole search model.  It is built ONCE per decision, so the
        candidate rollouts below are table lookups plus one pack step per stage.

        ``r_hold`` maps ``(absolute stage key, ladder index)`` to the roll's end-of-stage
        ratio; a missing entry falls back to the standing carried ratio, which is
        what the previous decision's table supplies while a new roll is being
        sliced.  ``i_tot_oc`` optionally supplies a per-stage source total to
        judge the overcurrent constraint against, which is how the stochastic
        variant tightens the bound to a quantile without changing the cost.

        ``soc_hint`` is the state of charge the charger's PACK-side voltage is
        evaluated at (L4).  It is a hint and not a state: the table is built once
        per decision while the rollouts walk the SoC forward, so the exact value
        is the decision's own starting point rather than a fixed 0.6.  The
        residual is second-order - across the +-0.05 SoC a decision's horizon
        can traverse, the pack voltage moves under 0.2 V.

        ``viol_tab`` carries the WORST constraint violation in amperes for each
        (stage, ladder point), 0.0 where the point is feasible.  It is what the
        infeasible fallback (L5) minimises, so an infeasible decision commands
        the least-violating point available rather than the bottom rail.

        ── THE OPEN-LOOP SUBMODE MODEL (2026-09-02) ────────────────────────
        ``sp_acted`` is the setpoint the firmware last ACTED on
        (``share_actedSp``) and ``run_seed`` is the standing ``shareClosedLoopRun``
        flag, both read from the shadow governor.  Supplied together they select
        the feedforward-aware model: an open sub-sample HOLDS only while a
        closed-loop run stands and the ladder point equals the acted setpoint,
        and otherwise slews the applied ratio toward the setpoint at the tick
        ceiling ``ramp_mean()`` integrates.  ``handoff`` optionally maps
        ``(stage key, ladder index)`` to True where a roll ended in the
        conduction-handoff slew mode.

        ⚠️ TWO OF THE FIRMWARE'S THREE HOLD CONDITIONS ARE MODELLED, NOT THREE
        (L1, review of 2026-09-02).  `_open_loop()` holds on a standing run AND
        an unchanged setpoint AND ``!(shareIsoFC || shareIsoBT)`` (.ino:10173).
        This table models the first two.  An outstanding isolation is a state the
        table has no seed for - it is a consequence of a cut - and where it does
        arise the transition rolls carry the real flag, because they run the real
        `GovernorModel`.

        ⚠️ THE BAND NO LONGER RULES A CUT OUT (2026-09-02).  This used to say
        the ladder band ``[0.25, 0.75]`` was chosen so no candidate could cause
        an isolation, so a held-versus-slewed disagreement was possible only
        after a cut the search could not command.  The ladder now spans the
        firmware band ``[0.15, 0.85]``.  A cut still needs a setpoint OUTSIDE
        that band (the firmware compares strictly, and carries
        ``SHARE_CUTOFF_HYST`` beyond it), so no LADDER candidate can command
        one; but the single-source candidates the operator ruling adds are
        exactly such a command, and when they land this seed has to carry the
        isolation state rather than assume it away.

        ⚠️ THE MODELLED RAMP IS NOT BAND-CUT (L2, same review).  ``carried``
        walks freely in [0, 1] and the delivered share follows the droop map,
        while `applyShareRatio()` takes a channel OFF THE BUS once the ratio
        leaves ``[DROOP_R_MIN, DROOP_R_MAX]`` and the firmware then delivers a
        rail.  The two agree wherever the ratio stays in band, which is
        everywhere the search can command it; they diverge only when ``r_seed``
        is already out of band - after a cut - for the few ticks the ramp needs
        to re-enter, about 5 of the 100 ticks in a sub-sample at the full
        ceiling.

        ⚠️ BOTH SEEDS DEFAULT TO None, AND THE BRANCH IS THEN UNREACHABLE.  With
        either seed absent every open sub-sample is treated as a HOLD, which is
        the pre-2026-09-02 model exactly - bit-for-bit, not approximately - so a
        caller that does not supply the governor's setpoint state gets the table
        it always got."""
        ff_enabled = (sp_acted is not None and run_seed is not None)
        handoff = handoff or {}
        # ``active`` restricts the table to the ladder points this decision's
        # enumeration will actually visit (the coarsening of `coarsen_ladder`).
        # The columns left out are never read - `solve()` walks the same set -
        # and the ladder itself is untouched, so the roll table's keys still
        # mean what they meant.
        # `active=None` means THE IN-BAND LADDER, not every column: the
        # single-source columns need a `pre_ss` demand and are opt-in per
        # decision, so a caller that names no active set gets exactly the
        # pre-2026-09-03 table.
        cols = (tuple(range(self.n_band)) if active is None
                else tuple(int(i) for i in active))
        ticks_per_sub = max(1, int(round(self.dt_dec / len(pre.i_tot[0])
                                         / GOV_TICK_S))) if pre.n else 1
        n_s = len(self.ladder)
        d_tab = [[0.0] * n_s for _ in range(pre.n)]
        pfc_tab = [[0.0] * n_s for _ in range(pre.n)]
        pbt_tab = [[0.0] * n_s for _ in range(pre.n)]
        ok_tab = [[True] * n_s for _ in range(pre.n)]
        viol_tab = [[0.0] * n_s for _ in range(pre.n)]
        v_chg = pack_charge_voltage(soc_hint, self.chg_a)
        for si in cols:
            # ── THE SINGLE-SOURCE COLUMNS (2026-09-03) ─────────────────────
            # A column of its own, and it shares nothing with the in-band
            # branch below except the table it writes into.  THREE differences,
            # each of which is why the branch exists rather than being a rung
            # with an extreme value:
            #  * THE BUS LAW.  With one channel off the bus the fitted
            #    two-source law's `g_par` is a parallel droop code that does not
            #    exist, so the demand is read from a preview built with
            #    `build_demand(source_mode=...)` - the measured single-source
            #    law (`hil_plant_sim.single_source_bus_law()`).  At the 61 s
            #    cycle's peak that is worth ~0.45 V of bus voltage.
            #  * THE MINORITY CLIP DOES NOT APPLY.  `updateShareSetpointCutoff()`
            #    returns True for an out-of-band setpoint and the whole share
            #    loop is FROZEN (.ino:10087), so the closed-loop clip, the fw
            #    v26 ceiling clamp and the feedforward slew are all unreachable.
            #    The delivered share is exactly 1.0 or exactly 0.0.
            #  * THE OVERCURRENT BOUND IS THE SURVIVOR'S OWN.  It carries
            #    `i_total`, not a share of it.
            # ADMISSIBILITY is decided OUTSIDE this table, by the rollout-time
            # test in `MpcStrategy._ss_admissible()`; a column that reaches here
            # has already been admitted, and this branch judges only the
            # steady-state overcurrent of the stages it would run.
            if si in self.ss_mode_of:
                mode = self.ss_mode_of[si]
                if not pre_ss or mode not in pre_ss:
                    raise ValueError(
                        "delivery_table was given single-source column %d "
                        "(%s) with no `pre_ss` demand for it; the two-source "
                        "law is NOT the single-source law and substituting it "
                        "would under-state the bus sag" % (si, mode))
                p = pre_ss[mode]
                lim = SS_LIMIT_A[mode]
                d_fixed = 1.0 if mode == SS_MODE_FC else 0.0
                for j in range(pre.n):
                    oc_scale = ((i_tot_oc[j] / pre.i_tot_mean[j])
                                if (i_tot_oc and pre.i_tot_mean[j] > 0.0)
                                else 1.0)
                    worst = 0.0
                    for sub in range(len(p.i_tot[j])):
                        worst = max(worst, p.i_tot[j][sub] * oc_scale - lim)
                    d_tab[j][si] = d_fixed
                    pfc_tab[j][si] = d_fixed * p.p_dem_mean[j]
                    pbt_tab[j][si] = (1.0 - d_fixed) * p.p_dem_mean[j]
                    # A CHARGE STAGE IS NEVER SINGLE-SOURCE-COMMANDABLE.
                    # `assertFcChargeEnable()` already holds BT_BUS LOW and owns
                    # the topology; a setpoint latch on top of that is a second
                    # owner of the same switch, which is the "one owner per
                    # setpoint" invariant the firmware carries.  The guard in
                    # `MpcStrategy.decide()` refuses the candidate outright, and
                    # this is the table-side backstop.
                    ok_tab[j][si] = (worst <= 0.0) and not charge_stages[j]
                    viol_tab[j][si] = max(0.0, worst)
                continue
            s = self.ladder[si]
            carried = r_seed
            acted = sp_acted
            run_flag = bool(run_seed)
            # The setpoint the open-loop branch actually drives toward: the raw
            # command clipped to the actuator band by applyShareRatio().
            s_ff = min(max(s, DROOP_R_MIN), DROOP_R_MAX)
            # F1 idle: an out-of-band setpoint is never actuated in open loop
            # (.ino:10197), so such a ladder point can only ever HOLD.
            s_in_band = (DROOP_R_MIN <= s <= DROOP_R_MAX)
            for j in range(pre.n):
                n_sub = len(pre.i_tot[j])
                oc_scale = ((i_tot_oc[j] / pre.i_tot_mean[j])
                            if (i_tot_oc and pre.i_tot_mean[j] > 0.0) else 1.0)
                if charge_stages[j]:
                    # BT is off the bus: the fuel cell is the single source and
                    # also feeds the charger.  The traction split is 1.0 and the
                    # ratio winds onto DROOP_R_MIN, which the next transition
                    # roll picks up (CLAUDE.md 2026-09-01c).
                    carried = gov_mod.GOV_CONST["DROOP_R_MIN"]
                    # The loop is RUNNING through the window - topology-pinned,
                    # not held - so the acted setpoint tracks the command and a
                    # stage that follows the window can HOLD.
                    acted = s
                    run_flag = True
                    # PER SUB-SAMPLE, like the discharge branch (L4): the bound
                    # is an instantaneous current limit, and judging it on the
                    # stage MEAN admits a stage whose peak is over the margin.
                    worst = 0.0
                    for sub in range(n_sub):
                        i_chg_bus = chg_mod.charger_bus_current_a(
                            self.chg_a, pre.v_bus[j][sub], v_chg, self.eta_chg)
                        i_fc = pre.i_tot[j][sub] * oc_scale + i_chg_bus
                        worst = max(worst, i_fc - I_FC_MAX_A)
                    d_tab[j][si] = 1.0
                    pfc_tab[j][si] = pre.p_dem_mean[j]
                    pbt_tab[j][si] = 0.0
                    ok_tab[j][si] = worst <= 0.0
                    viol_tab[j][si] = max(0.0, worst)
                    continue
                acc_d = acc_fc = acc_bt = 0.0
                worst = 0.0
                # The conduction-handoff dwell allowance, RE-ARMED PER STAGE.
                # The firmware's counter is a run-length quantity that survives a
                # stage boundary, so this is optimistic by at most one stage's
                # worth of allowance (175 ticks of 1000).  It is a simplification
                # and not a fidelity claim; the stage-mean effect of it is under
                # the 1.34e-04 the handoff comparison test measures.
                dwell_left = HANDOFF_DWELL_MAX_TICKS
                ff_used = False
                ho = bool(handoff.get((pre.stage_key[j], si)))
                for sub in range(n_sub):
                    i_tot_sub = pre.i_tot[j][sub]
                    if pre.mode[j][sub] == STAGE_CLOSED:
                        lo = pre.lo[j][sub]
                        d = min(max(s, lo), 1.0 - lo)
                        # fw v26 CURRENT-CEILING CLAMP, in the firmware's own
                        # order: the minority-current clip above owns the floor,
                        # and the ceiling clamp bounds the result before it
                        # becomes the reference the controller tracks
                        # (.ino:10635).  It is what makes the DELIVERED share
                        # differ from the commanded one on a high-total stage,
                        # and therefore a component of `mpc_share_pred_err`.
                        d = gov_mod.ceiling_bounded_share(d, i_tot_sub)
                        carried = self._ratio_for(d, i_tot_sub)
                        self.closed_cells += 1
                        acted = s
                        run_flag = True
                    elif (not ff_enabled or not s_in_band
                          or pre.mode[j][sub] == STAGE_FROZEN
                          or (run_flag
                              and abs(s - acted) <= SHARE_SP_CHANGE_EPS)):
                        # HOLD.  No MDAC write; the standing split stands.
                        #
                        # THREE WAYS IN, and the third is not the open-loop
                        # branch at all: below `SHARE_I_TOT_MIN_A` the firmware's
                        # minimum-load gate returns before the loop-mode decision
                        # is even taken (.ino:10099), so a frozen sub-sample
                        # writes nothing whatever the setpoint did.  Routing it
                        # to the feedforward arm would model a slew on a
                        # standstill.
                        d = self._alpha(carried, i_tot_sub)
                        self.hold_cells += 1
                    else:
                        # OPEN FEEDFORWARD.  The ratio slews toward the raw
                        # setpoint at the tick ceiling; the command has been
                        # acted on, so `closed_loop_run` clears and every later
                        # open tick stays on this branch until a closed-loop run
                        # re-arms the hold.
                        step_slow = None
                        if ho or (self.ff_dark_model
                                  and (carried * i_tot_sub < HANDOFF_DARK_A
                                       or (1.0 - carried) * i_tot_sub
                                       < HANDOFF_DARK_A)):
                            step_slow = SLEW_HANDOFF_PER_TICK
                        # fw v27 rev 2: THE RELAXING MINORITY-CURRENT CLIP RUNS
                        # ON THE FEEDFORWARD PATH TOO, and it runs FIRST
                        # (`GovernorModel.feedforward_clip_target()`,
                        # .ino:10810).  An EMPTY band is a HOLD at the ratio the
                        # hardware already carries, NOT a collapse to 0.5.
                        #
                        # fw v27 rev 2 re-pin, 2026-09-03: the modelled
                        # feedforward target moved `s_ff` -> `clip(s_ff, lo,
                        # 1-lo)` with a HOLD on an empty band, because
                        # SHARE_MINORITY_I_MIN_A moved 0.30 -> 0.15 A and the
                        # firmware grew this clip on the open-loop path.  The
                        # band is empty whenever `lo >= 0.5`, i.e. whenever
                        # `I_tot <= 2*I_min = GOV_ENTRY_A`, and an OPEN
                        # sub-sample is by definition at or below that gate - so
                        # at the shipped constants this branch is a HOLD at
                        # every reachable open-loop total and the modelled slew
                        # is retired.  It is written as the arithmetic, not as
                        # the hold it degenerates to, so a future retune of the
                        # floor re-opens it exactly as the firmware re-opens it.
                        lo_ff = pre.lo[j][sub]      # min(0.5, I_min/I_tot)
                        if i_tot_sub > GOV_MIN_LOAD_A and lo_ff < 0.5:
                            s_ff_t = min(max(s_ff, lo_ff), 1.0 - lo_ff)
                        else:
                            s_ff_t = carried        # empty band -> hold
                        # fw v26: the FEEDFORWARD submode DOES write the
                        # MDACs, so it takes the clamp too (.ino:10562); HOLD
                        # does not, and is left alone above.  Inert at every
                        # reachable open-loop total, applied so a ceiling
                        # retune cannot leave a writing path unguarded.
                        s_ff_c = gov_mod.ceiling_bounded_share(s_ff_t, i_tot_sub)
                        r_mean, carried, dwell_left = ramp_mean(
                            carried, s_ff_c, ticks_per_sub,
                            step_fast=SLEW_FULL_PER_TICK,
                            step_slow=step_slow, dwell_left=dwell_left)
                        # The asymmetry map is evaluated at the sub-sample's mean
                        # ratio.  It is EXACT at dv0 = 0 (the map is the
                        # identity) and second-order in the map's curvature
                        # otherwise.
                        d = self._alpha(r_mean, i_tot_sub)
                        run_flag = False
                        acted = s
                        ff_used = True
                        self.ff_cells += 1
                    acc_d += d
                    acc_fc += d * pre.p_dem[j][sub]
                    acc_bt += (1.0 - d) * pre.p_dem[j][sub]
                    i_tot = pre.i_tot[j][sub] * oc_scale
                    worst = max(worst, d * i_tot - I_FC_MAX_A,
                                (1.0 - d) * i_tot - I_BT_MAX_A)
                key = (pre.stage_key[j], si)
                # THE ROLL'S CARRY IS A HELD-COMMAND RESULT.  `_roll_begin()`
                # seeds `acted_sp` with the ladder point and `closed_loop_run`
                # true, so the roll models the command as HELD across the
                # transition.  Where this stage actually took the feedforward
                # branch that assumption does not hold, and the ramp integrated
                # above is the better carry - so the override is skipped there
                # rather than overwriting a modelled slew with a held roll.
                if key in r_hold and not ff_used:
                    carried = r_hold[key]
                d_tab[j][si] = acc_d / n_sub
                pfc_tab[j][si] = acc_fc / n_sub
                pbt_tab[j][si] = acc_bt / n_sub
                ok_tab[j][si] = worst <= 0.0
                viol_tab[j][si] = max(0.0, worst)
        return d_tab, pfc_tab, pbt_tab, ok_tab, viol_tab

    # -- one candidate ------------------------------------------------------
    def _rollout(self, soc0, soc_ref, pre, tabs, charge_stages, block_idx,
                 bound):
        """Cost of one move-blocked candidate, abandoned above ``bound``."""
        sim = _load_sim()
        d_tab, pfc_tab, pbt_tab, ok_tab, _viol = tabs
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
                # THE BRAKING CREDIT (2026-09-02), in LOCKSTEP with
                # gen_dp_ems_table.step_discharge()/step_charge(): a per-stage
                # constant, share-INDEPENDENT, added to both transitions.  Its
                # share-independence is what keeps it out of the candidate
                # comparison entirely - every candidate gains the same SoC on a
                # braking stage - so the search cannot "choose" to regenerate.
                reg = (pre.i_regen_mean[stage]
                       if stage < len(pre.i_regen_mean) else 0.0)
                if charge_stages[stage]:
                    p_fc_bus = (pre.p_dem_mean[stage]
                                + chg_mod.charger_bus_power_w(
                                    self.chg_a, pre.v_bus_mean[stage],
                                    pack_charge_voltage(soc, self.chg_a),
                                    self.eta_chg))
                    soc = soc + (self.chg_a + reg) * self.dt_dec / self.cap_as
                else:
                    p_fc_bus = pfc_tab[stage][si]
                    i_pack = pack_current_from_bus_power(pbt_tab[stage][si], soc)
                    soc = soc + (reg - i_pack) * self.dt_dec / self.cap_as
                cost += self.h2_rate_gps(p_fc_bus / sim.ETA_BOOST) * self.dt_dec
                if cost >= bound:
                    # Sound: the remaining stage costs are non-negative and the
                    # terminal term is bounded below by zero.
                    return None, 0.0, 0.0
                stage += 1
        cost += huber(soc - soc_ref, self.rho)
        return cost, soc, d_tab[0][block_idx[0]]

    # -- enumeration --------------------------------------------------------
    @staticmethod
    def share_step_guard_stage(pre, i_tot_prev, block0_len):
        """The block-0 stage the share-step rule fires on, or ``None``.

        THE DEFINITION OF "RISING", stated once and encoded here.  The rule
        names "an upward share step IN THE SAME DECISION AS an upward demand
        step", so both halves are judged at the DECISION BOUNDARY, over the
        stages the block-0 command is actually held for:

            stage j (0 <= j < block0_len) fires when
                i_tot_mean[j] >  SHARE_STEP_GUARD_I_TOT_A          (the level)
            AND i_tot_mean[j] >  i_tot_mean[j - 1]                 (rising)

        where ``i_tot_mean[-1]`` is ``i_tot_prev``, the total the PREVIOUS
        decision predicted for the stage that has just run.  That is what makes
        stage 0 - the stage the new command lands on - testable at all: without
        the carried value there is no earlier total to compare it against, and
        stage 0 is precisely where a re-command lands on an acceleration.  On
        the FIRST decision of a run ``i_tot_prev`` is None and stage 0 is
        treated as NOT rising (nothing stepped; the run has only just begun).

        Returns the first firing stage index, or None.  A pure function, so the
        tests can drive it without a strategy."""
        prev = i_tot_prev
        n = min(int(block0_len), pre.n)
        for j in range(n):
            cur = pre.i_tot_mean[j]
            if cur > SHARE_STEP_GUARD_I_TOT_A and prev is not None and cur > prev:
                return j
            prev = cur
        return None

    def solve(self, soc0, soc_ref, pre, r_hold, r_seed, charge_options,
              i_tot_oc=None, budget_ms=None, sp_acted=None, run_seed=None,
              handoff=None, active=None, ss_modes=(), pre_ss=None,
              share_step_guard_r=None):
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
        cols = (tuple(range(self.n_band)) if active is None
                else tuple(sorted(set(int(i) for i in active))))
        if not cols:
            raise ValueError("the active ladder set is empty")
        # ── THE SINGLE-SOURCE COLUMNS, BLOCK 0 ONLY (2026-09-03) ───────────
        # ⚠️ A DEVIATION FROM THE DESIGN RECORD'S SCOPING, and it is what makes
        # the rollout-time test EXACT rather than approximate.  The record's
        # remaining-work list says "the two extra candidate indices", which
        # reads as two extra rungs available at every block.  They are offered
        # at BLOCK 0 ONLY, for three reasons:
        #  1. THE ADMISSIBILITY TEST IS A ROLL FROM THE CURRENT GOVERNOR STATE.
        #     `_ss_admissible()` rolls the real `GovernorModel` from the shadow
        #     estimate, which is a fact only about NOW.  Admitting a
        #     single-source value at block 1 would need the governor state six
        #     stages into a candidate PATH, i.e. one roll per path - the inner
        #     loop the anytime budget is spent in, which is exactly what
        #     resolution 2 of the design record warns about.
        #  2. ONLY BLOCK 0 IS COMMITTED.  The horizon recedes every stage, so a
        #     block-1 single-source value is never executed as planned; it is a
        #     tail estimate, and an inadmissible one would bias the tail.
        #  3. THE ENUMERATION.  Two extra rungs at every block take 9^3 to
        #     11^3 = 1331 per charge option, +83 %.  At block 0 alone it is
        #     11*9*9 = 891, +21 %, which the coarsening arithmetic can absorb.
        # THE MODELLING RESIDUAL, stated: the restore from a single-source block
        # into block 1's in-band value is a transient of at most the 30 ms
        # blanking plus 175 ticks of conduction-handoff slew, against the 6 s of
        # block 1 - under 3.5 % of that block, and it is not modelled.
        ss_cols = tuple(self.ss_index[m] for m in (ss_modes or ())
                        if m in self.ss_index)
        cols0 = cols + tuple(c for c in ss_cols if c not in cols)

        # ── THE SHARE-STEP GUARD, applied to BLOCK 0 (2026-09-03) ──────────
        # `share_step_guard_r` is the COMMITTED share (the governor's standing
        # ratio) when the caller's stage test fired, and None otherwise.  Every
        # block-0 column whose share is strictly ABOVE it is an upward share
        # step landing on a rising demand step, and is refused.
        #
        # SCOPE, and why it is block 0 only: block 0 is the only block that is
        # COMMITTED, so it is the only one that can command the packet the
        # hazard needs.  The later blocks are a receding-horizon tail, re-planned
        # before they are ever issued.  This is the same scoping the
        # single-source columns carry, for the same reason.
        #
        # THE SINGLE-SOURCE COLUMNS ARE INSIDE THE GUARD, not exempt from it:
        # `SS_MODE_FC` is share 1.0, the largest upward step available, so the
        # comparison catches it exactly as it catches a rung.  `SS_MODE_BT` is
        # share 0.0 and is always downward, so it always survives.
        #
        # THE SET IS NEVER EMPTIED.  If every block-0 column is above the
        # committed share (a coarsened ladder whose rungs all sit above it), the
        # LOWEST-SHARE column is kept: refusing the whole block would make the
        # decision infeasible and hand the fallback a command nobody chose,
        # which is a worse outcome than the smallest upward step available.
        n_step_refused = 0
        if share_step_guard_r is not None:
            r_ref = float(share_step_guard_r)
            keep = tuple(c for c in cols0 if self.ladder[c] <= r_ref + 1e-9)
            if not keep:
                keep = (min(cols0, key=lambda c: (self.ladder[c], c)),)
            n_step_refused = len(cols0) - len(keep)
            cols0 = keep
        # THE BLOCK-0 FALLBACK POOL.  Both fallbacks below (the seed and L5)
        # choose a BLOCK-0 command, so under the guard they must choose from the
        # surviving set - and they may only index `tabs0`, which is built over
        # `cols0`.  Unguarded this is `cols` itself, so every pre-2026-09-03
        # path is unchanged.
        cols_fb = tuple(c for c in cols if c in cols0) or (cols0[0],)

        # THE INFEASIBLE FALLBACK, stated: if no candidate is feasible the
        # decision keeps this seed - the lowest ladder point, no charge, which
        # is the least fuel-cell-loaded command available - and
        # `feasible` stays False so the run's summary and the CSV show it. A
        # decision that commanded nothing would leave the previous share
        # standing without saying so.
        best = Decision(cost=float("inf"))
        best.share = self.ladder[cols_fb[0]]
        best.plan_share = [self.ladder[cols_fb[0]]] * pre.n
        best.plan_charge = list(charge_options[0])
        best.ladder_points = len(cols)
        # Counted AFTER the share-step filter: a single-source column the guard
        # removed was not searched, and `ss_searched` must not claim it was.
        best.ss_offered = sum(1 for c in ss_cols if c in cols0)
        best.share_step_guarded = share_step_guard_r is not None
        best.share_step_refused = n_step_refused
        order = self._enumeration_order(cols, nb, cols0=cols0)
        n_eval = 0
        pruned = 0
        hit = False
        cap_hit = False
        tabs0 = None
        for oi, cs in enumerate(charge_options):
            # M1: the delivery tables are BUILT INSIDE the budget and one option
            # at a time, with the clock checked between them.  Building all of
            # them up front spent budget the expiry check could not see, and the
            # no-charge option (index 0) is the one an expiry must always have.
            if oi > 0 and time.perf_counter() - t0 >= budget_s:
                hit = True
                break
            tabs = self.delivery_table(pre, r_hold, r_seed, cs, i_tot_oc,
                                       soc_hint=soc0, sp_acted=sp_acted,
                                       run_seed=run_seed, handoff=handoff,
                                       active=cols0, pre_ss=pre_ss)
            if oi == 0:
                tabs0 = tabs
            for block_idx in order:
                # The cap is judged BEFORE a candidate is evaluated, so a cap
                # equal to the enumeration size flags nothing (nothing was cut);
                # `cap_hit` means at least one candidate was left unevaluated.
                if (self.max_candidates is not None
                        and n_eval >= self.max_candidates):
                    cap_hit = True
                    break
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
                    best.single_source = self.ss_mode_of.get(block_idx[0])
                    best.plan_share = self._expand(block_idx)
                    best.plan_charge = list(cs)
                    self.incumbent = tuple(block_idx)
                    self.incumbent_charge = oi
                if time.perf_counter() - t0 >= budget_s:
                    hit = True
                    break
            if hit or cap_hit:
                break
        # ── THE INFEASIBLE FALLBACK (L5) ───────────────────────────────────
        # Not the bottom rail: the ladder point whose WORST constraint violation
        # over the horizon is smallest, judged on the no-charge option.  A rail
        # is the least fuel-cell-loaded command but not the least-violating one,
        # and on a battery-side violation it is the worst point on the ladder.
        if not math.isfinite(best.cost) and tabs0 is not None:
            viol = tabs0[4]
            worst = {si: max(viol[j][si] for j in range(pre.n))
                     for si in cols_fb}
            si_best = min(cols_fb, key=lambda i: (worst[i], i))
            best.share = self.ladder[si_best]
            best.plan_share = [self.ladder[si_best]] * pre.n
            best.share_pred = tabs0[0][0][si_best]
            best.worst_violation_a = worst[si_best]
        best.candidates = n_eval
        best.cap_hit = cap_hit
        best.pruned = pruned
        best.budget_hit = hit
        best.feasible = math.isfinite(best.cost)
        best.solve_ms = (time.perf_counter() - t0) * 1e3
        return best

    def _snap_seed(self, x, pool):
        """The column of ``pool`` nearest to incumbent column ``x`` BY SHARE.

        Distance is measured on the ladder VALUE, with the column index as the
        tiebreak.  See the note in `_enumeration_order()`: the single-source
        columns are appended, so index distance would snap a share-0.0
        incumbent onto the 0.85 rung.  An index outside the ladder (a caller
        whose ladder shrank between decisions) falls back to index distance,
        which is the only metric available for it."""
        x = int(x)
        if 0 <= x < len(self.ladder):
            xv = self.ladder[x]
            return min(pool, key=lambda c: (abs(self.ladder[c] - xv), c))
        return min(pool, key=lambda c: (abs(c - x), c))

    def _enumeration_order(self, cols, nb, cols0=None):
        """Candidates ordered outward in ladder distance from the incumbent.

        ``cols0`` (2026-09-03) is the column set BLOCK 0 draws from, which is
        ``cols`` plus this decision's admissible single-source columns; the
        remaining blocks always draw from ``cols``.  It defaults to ``cols``, so
        every pre-2026-09-03 caller gets the order it got.

        ⚠️ THE SINGLE-SOURCE COLUMNS SORT LAST, and that is a property of the
        distance metric rather than a ranking.  They are appended after the
        in-band ladder, so ``|c - seed|`` puts them further from any incumbent
        than any rung is - which means a BUDGET EXPIRY drops them first.  That
        direction is the safe one (an expiry keeps the in-band search it was
        going to commit anyway), and the ladder coarsening exists precisely so
        the enumeration COMPLETES; a decision that expires with single-source
        columns offered is reported through ``budget_hits`` like any other.

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
        cols = tuple(int(i) for i in cols)
        cols0 = cols if cols0 is None else tuple(int(i) for i in cols0)
        mid = cols[len(cols) // 2]
        seed = self.incumbent if self.incumbent is not None else (mid,) * nb
        # An incumbent index outside the active set is snapped to the nearest
        # active one, so the warm start still starts near where the last
        # decision left off.  `coarsen_ladder()` unions the incumbent in, so
        # this only ever fires for a caller that supplied its own active set.
        #
        # ⚠️ SNAPPED BY LADDER VALUE, NOT BY INDEX (fixed 2026-09-03, review
        # MED-1).  The single-source columns are APPENDED after the in-band
        # ladder, so index distance is not share distance for them: after a
        # BT-only commit the incumbent is index `n_band` (share 0.0) and the
        # nearest index in a full in-band set is `n_band - 1`, which is share
        # 0.85 - the OPPOSITE rail.  A budget expiry then commits that seed,
        # which is a 0.85 command issued as the "warm start" of a decision whose
        # last command was 0.0.  Snapping by |ladder[c] - ladder[x]| puts the
        # same case on 0.15, the nearest rung to what was actually commanded.
        # The index tiebreak is kept, so an in-band incumbent inside the active
        # set still snaps to itself and every pre-2026-09-03 order is unchanged
        # (an in-band ladder is monotone, so value order IS index order there).
        seed = tuple(self._snap_seed(x, (cols0 if bi == 0 else cols))
                     for bi, x in enumerate(seed[:nb]))
        if len(seed) < nb:
            seed = seed + (seed[-1],) * (nb - len(seed))
        key = (cols, cols0, nb, seed)
        cached = self._order_cache.get(key)
        if cached is not None:
            return cached
        all_idx = []

        def rec(prefix):
            if len(prefix) == nb:
                all_idx.append(tuple(prefix))
                return
            for i in (cols0 if not prefix else cols):
                rec(prefix + [i])

        rec([])
        all_idx.sort(key=lambda c: (sum(abs(c[i] - seed[i]) for i in range(nb)),
                                    c))
        # Bounded: one entry per distinct (active set, seed) pair.  Cleared
        # wholesale rather than grown without bound.
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
       available.
       ⚠️ STALE CLAUSE CORRECTED 2026-09-02 (campaign 20260902_011926, F6): the
       design's ``mdac_corrections`` counter DOES NOT read zero — the additive
       registration step landed with the MPC round, so ``_fb()`` carries
       ``mdac_fc``/``mdac_bt`` and the first live campaign measured **2968 MDAC
       corrections** on the stochastic leg (then named ``ems-mpc-sto``; the
       names swapped in the 2026-09-02 promotion).  The two words are outside
       ``FB_TELEMETRY_EQUIV_KEYS`` deliberately (they are not in the v4 packet
       and are not portable to a real Pi), so the current-derived path remains
       the fallback and ``current_corrections`` is what a Mode B run would use.
       docs/modeling/mpc_design_20260901.md §2.5 carries the same stale
       sentence; it is the docs agent's to correct."""

    def __init__(self, dv0_v=0.0, seed_r=0.5, tick_s=GOV_TICK_S,
                 droop_scale_fc=1.0, r_series_ohm=0.0):
        self.tick_s = float(tick_s)
        self.model = gov_mod.GovernorModel(dt_s=tick_s, dv0_v=dv0_v,
                                           droop_scale_fc=droop_scale_fc,
                                           r_series_ohm=r_series_ohm,
                                           seed_r=seed_r)
        self.last_t = None
        self.mdac_corrections = 0
        self.current_corrections = 0
        self.mode_mismatch = 0
        self.ticks = 0
        # ── THE BATTERY-ONLY START (H2, 2026-09-03) ─────────────────────────
        # THE BOARD AND THE WALK BOTH START WITH FC_BUS LOW, and this shadow
        # must too. fw v27 rev 2 arms a one-shot battery-only cut at every
        # profile start (`armShareBatteryOnlyStart()`, .ino:11737), which
        # `ems_walk.walk()` mirrors at ems_walk.py:661. Without the same call
        # here the shadow rolls from a state in which the fuel cell is already
        # on the bus, `tick_to()` asserts `sw_fc = True` through the whole
        # pre-gate window, and `_ss_admissible()` judges single-source
        # candidates against a topology the board does not have.
        self.model.arm_battery_only_start()

    def reset(self, seed_r=0.5):
        self.model.reset(seed_r)
        self.last_t = None
        self.mdac_corrections = 0
        self.current_corrections = 0
        self.mode_mismatch = 0
        self.ticks = 0
        # Re-arm on every reset, exactly where the walk arms: `reset()` is the
        # planner's profile boundary. `GovernorModel.reset()` clears the flag,
        # so this must follow it rather than precede it.
        self.model.arm_battery_only_start()

    @property
    def r(self):
        return self.model.state.r_prev

    @property
    def closed(self):
        return bool(self.model.state.closed_loop_mode)

    @property
    def acted_sp(self):
        """``share_actedSp`` - the setpoint the open-loop branch compares against."""
        return float(self.model.state.acted_sp)

    @property
    def closed_loop_run(self):
        """``shareClosedLoopRun`` - the flag that makes an unchanged setpoint HOLD."""
        return bool(self.model.state.closed_loop_run)

    @property
    def sp_cut(self):
        """The standing setpoint latch: ``"fc"``, ``"bt"`` or None.

        Names the channel that is OFF the bus, so ``"fc"`` means the FUEL CELL
        is cut and the battery is carrying the load."""
        st = self.model.state
        if st.sp_cut_fc:
            return "fc"
        if st.sp_cut_bt:
            return "bt"
        return None

    @property
    def deferred(self):
        """True while the load guard is holding a cut off - ``shareCutDeferred*``."""
        st = self.model.state
        return bool(st.deferred_fc or st.deferred_bt)

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
        st = self.model.state
        for k in range(n):
            ts = self.last_t + k * self.tick_s
            # ── WHO OWNS THE SWITCH BELIEFS (2026-09-03) ────────────────────
            # Normally the shadow asserts the Run-state topology: both boosts on
            # the bus, BT held LOW by the charge path while a window is open.
            # Once the COMMANDED setpoint leaves [DROOP_R_MIN, DROOP_R_MAX] -
            # which only a single-source command does - the setpoint latch is
            # the switch's owner, and asserting FC HIGH every tick would trip
            # the S1 self-heal (`if sp_cut_fc and sw_fc: clear`) and erase the
            # very latch being modelled.  So while a single-source command
            # stands, or while a latch is standing from one, the MODEL's own
            # beliefs are fed back.
            # ⚠️ INERT WITH THE FEATURE OFF.  No in-band setpoint can latch, so
            # the predicate is False on every tick of every pre-2026-09-03 run
            # and the two lines below are the two lines that were there.
            if (share < DROOP_R_MIN or share > DROOP_R_MAX
                    or st.sp_cut_fc or st.sp_cut_bt):
                sw_fc, sw_bt = st.sw_fc, st.sw_bt
            else:
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

    ``bind_scenario(scenario, meta, electrical_mode=None, args=None)``,
    ``reset()``, ``__call__(t, fb)``,
    ``summary_line()`` and a ``provenance`` attribute, so registration in
    ``hil_plant_sim.EMS_STRATEGIES`` and a branch in ``ems_walk._instantiate()``
    are the whole plumbing (see the design document's registration section).

    ``variant`` is ``"det"`` (exact preview) or ``"sto"`` (the TPM's conditional
    mean, with the overcurrent bound at the 90 % quantile)."""

    def __init__(self, name="mpc-det", variant="det", horizon=HORIZON_N,
                 blocks=MOVE_BLOCKS, share_band=SHARE_BAND_DP,
                 share_levels=SHARE_LEVELS, terminal_price_mode="metric",
                 budget_ms=None,
                 roll_budget_ms=ROLL_BUDGET_MS_DEFAULT, max_candidates=None,
                 adaptive_budget=True, coarsen_ladder_enabled=True,
                 candidate_cost_ms=None,
                 h2_map="proxy", h2_convex=None, dv0_v=0.0,
                 soc_ref_offset=0.0, eta_chg=chg_mod.ETA_CHG_DEFAULT,
                 tpm_path=None, preview_dt_s=PREVIEW_DT_S,
                 ff_dark_model=False, loss_map=None, single_source=False,
                 droop_scale_fc=1.0, r_series_ohm=0.0):
        if variant not in ("det", "sto"):
            raise ValueError("variant must be 'det' or 'sto'")
        self.name = name
        self.variant = variant
        self.horizon = int(horizon)
        self.blocks = tuple(blocks)
        self.share_band = (float(share_band[0]), float(share_band[1]))
        self.share_levels = int(share_levels)
        self.terminal_price_mode = terminal_price_mode
        # ── THE BUDGET, AND WHICH OF THE TWO IT IS ─────────────────────────
        # `budget_ms=None` (the default since 2026-09-02) selects the ADAPTIVE
        # budget of `derive_budget_ms()`.  An explicit value - which is what the
        # per-scenario `mpc_budget_ms` key and the `--mpc-budget-ms` flag both
        # supply - is a FIXED budget and TAKES PRECEDENCE, exactly as before.
        # `self.budget_ms` therefore reads None on an adaptive strategy, and
        # `budget_ms_fixed` is the predicate rather than a comparison against
        # the default.
        self.budget_ms = (None if budget_ms is None else float(budget_ms))
        self.budget_ms_fixed = (budget_ms is not None)
        self.adaptive_budget = bool(adaptive_budget) and not self.budget_ms_fixed
        self.coarsen_ladder_enabled = bool(coarsen_ladder_enabled)
        # PINNING THE PROJECTION.  None selects `CANDIDATE_COST_MS_NOMINAL`,
        # which is a CONSTANT: nothing on this path reads the clock, so with a
        # fixed `budget_ms` as well the search width is bit-reproducible across
        # hosts.  An explicit value overrides the constant, for a caller that has
        # profiled its own host and wants to say so.
        self.candidate_cost_ms = (None if candidate_cost_ms is None
                                  else float(candidate_cost_ms))
        self.candidate_cost_ms_used = (CANDIDATE_COST_MS_NOMINAL
                                       if self.candidate_cost_ms is None
                                       else self.candidate_cost_ms)
        self.roll_budget_ms = float(roll_budget_ms)
        self.max_candidates = (None if max_candidates is None
                               else int(max_candidates))
        self.h2_map = h2_map
        self.h2_convex = h2_convex
        self.dv0_v = float(dv0_v)
        # ── THE OTHER TWO SPLIT-LAW PARAMETERS (2026-09-03, review run-002
        #    PLANT-R2-F3/N2) ──────────────────────────────────────────────────
        # THE CANONICAL STATEMENT; `Planner.__init__`, `RollJob.__init__` and
        # `ShadowGovernor` carry the same pair and point here.
        # `dv0_v` is only one of three: `droop_scale_fc` (rho) and
        # `r_series_ohm` (R_f) complete the static split law, and R_f is
        # present with the asymmetry OFF as well.  All three default to the
        # identity map, so a caller that passes none is bit-identical to the
        # pre-2026-09-03 planner.  This class is the one that receives them
        # from `hil_plant_sim.mpc_configure_kwargs()` and hands them on to
        # every model it builds, so a parameter dropped here is dropped
        # everywhere.
        self.droop_scale_fc = float(droop_scale_fc)
        self.r_series_ohm = float(r_series_ohm)
        self.ff_dark_model = bool(ff_dark_model)
        # ── SINGLE-SOURCE CANDIDATES (2026-09-03) ──────────────────────────
        # OFF by default and deliberately so: with it off this class is
        # bit-for-bit the 2026-09-02 controller, which is what keeps every
        # Gate-1/Gate-2 record and every campaign anchor comparable.  A scenario
        # turns it on with the `mpc_single_source` key, or a caller with this
        # constructor argument; `--mpc-single-source` is the command line's.
        self.single_source = bool(single_source)
        self.soc_ref_offset = float(soc_ref_offset)
        self.eta_chg = chg_mod.check_eta_chg(eta_chg)
        # THE DEMAND-MODEL ERA (2026-09-02).  `None` (the default) is the
        # loss-map-free model, which is what every Gate-1 and Gate-2 record
        # before this round was measured on.  A campaign binds the plant's map
        # explicitly through `bind_scenario()`'s `mpc_loss_map` key, so the
        # planner predicts on the SAME demand the DP bound it is scored
        # against was solved with.
        self.loss_map = _load_sim().check_loss_map(loss_map)
        self.preview_dt_s = float(preview_dt_s)
        self.tpm_path = tpm_path
        self.tpm = None
        self.tpm_edges = None
        # All three are OVERWRITTEN from the SDP artifact at _load_tpm() (M3),
        # which only the `sto` variant calls.  The seed value is the shipped
        # artifact's map, and it is also the ASSERTION the loader makes against
        # whatever file it reads (DEMAND_MAP_W_EXPECTED).
        self.tpm_map_w = DEMAND_MAP_W_EXPECTED
        self.demand_map_source = None
        self.demand_map_path = None
        self.provenance = None
        self.scenario = None
        self.meta = None
        self.electrical_mode = None
        self.cap_as = BATT_CAPACITY_AH * 3600.0
        self.preview = None
        self.preview_ss = {}
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
                                     droop_scale_fc=self.droop_scale_fc,
                                     r_series_ohm=self.r_series_ohm,
                                     seed_r=sim.SOC_BAND_SHARE_NOMINAL)
        self.roll_job = None
        self.r_hold = {}
        self.r_handoff = {}
        self.budget_hits = 0
        self.cap_hits = 0
        self.incumbent_retained = 0
        self.solve_ms_last = 0.0
        self.solve_ms_max = 0.0
        self.solve_ms_all = []
        # Per-decision budget and search width (2026-09-02).
        self.budget_ms_all = []
        self.ladder_points_all = []
        self.coarsened_decisions = 0
        self.budget_floor_binding = 0
        self.candidate_cost_ms_seen = 0.0
        self.transition_stages_last = 0
        # The two measured callback terms the budget derivation consumes.  Both
        # are the LAST callback's, not an average: the derivation is a bound on
        # the callback about to run, and a mean would under-state a slice that
        # has just grown.
        self._roll_slice_ms = None
        self._surface_ms = None
        self._rollout_ms = None
        self.share_pred = None
        self.share_pred_err = None
        self.share_pred_err_max = 0.0
        self.share_pred_err_sum = 0.0
        self.share_pred_err_n = 0
        # -- THE SAME PAIR, WINDOWED TO THE SCORED WINDOW (2026-09-03) ------
        # The four accumulators above run from the FIRST decision, which is
        # before Run entry: campaign 20260902_220604 reported a whole-run
        # maximum of 0.4067-0.4113 whose entire population is ~3020 pre-Run
        # ticks in t in [1.003, 4.031] s, while the run's own
        # `mpc_share_prediction` check reads 0.0604 over its Run window. The
        # headline figure therefore described a phase nothing scores, and it
        # read as a near-miss of the 0.30 band. These accumulate only over
        # in-Run decisions, and the summary line reports them FIRST with the
        # whole-run pair beside them, explicitly labelled.
        self.share_pred_err_run_max = 0.0
        self.share_pred_err_run_sum = 0.0
        self.share_pred_err_run_n = 0
        self._stage_share_sum = 0.0
        self._stage_share_n = 0
        self.rolls_started = 0
        self.rolls_published = 0
        self.rolls_empty = 0
        self.roll_dropped_transitions = 0
        self.candidates_last = None
        self.candidates_min = None
        # `candidates_max` (2026-09-02, campaign C): enumeration GROWTH is what
        # the deterministic cap and the solve budget are both spent on, and the
        # last/fewest pair could not show it -- a run whose search doubled
        # between decisions reports the same two numbers as one that did not.
        self.candidates_max = None
        self.infeasible_decisions = 0
        self.clamped_bin_high = 0
        self.clamped_bin_low = 0
        # ── SINGLE-SOURCE CENSUS (2026-09-03) ──────────────────────────────
        # Per DECISION, not per tick.  `offered` counts the two candidates a
        # decision could have tested (2 whenever the feature is armed and the
        # run is inside a decision), `admissible` those the rollout-time test
        # accepted, `selected_*` the decisions whose COMMITTED command was one.
        # `refusals` is a reason census, so a campaign can say WHY the feature
        # did nothing rather than only that it did.
        self.ss_offered = 0
        self.ss_admissible = 0
        # Columns the SEARCH actually walked, summed from `Decision.ss_offered`
        # (2026-09-03, review LOW-3).  It differs from `ss_admissible` when a
        # mode the rollout test admitted failed to reach the planner - a
        # plumbing defect - OR, since the share-step guard (2026-09-03), when
        # the guard removed an admitted `SS_MODE_FC` column (share 1.0 is
        # inside the guard).  The second path is legitimate and is counted
        # under `share_step_refusals`; the first is a defect.  Read here.
        self.ss_searched = 0
        self.ss_selected_fc = 0
        self.ss_selected_bt = 0
        self.ss_selected_last = None
        self.ss_refusals = {}
        self.ss_admit_ms_max = 0.0
        self.ss_admit_ticks_max = 0
        # ── THE SHARE-STEP GUARD CENSUS (2026-09-03) ───────────────────────
        # `decisions` counts the decisions the rule FIRED on (level and rising
        # both true somewhere in block 0); `refusals` is the reason census of
        # the candidate COLUMNS it removed, in `ss_refusals`'s vocabulary.  A
        # decision can fire and refuse nothing - that is the case where every
        # block-0 column was already at or below the committed share, i.e. the
        # planner was not going to step up anyway, and the two counters have to
        # be able to say so separately.  `_i_tot_prev` is the carried total the
        # "rising" half is judged against; it is per-run state, so it resets
        # with the census.
        self.share_step_guard_decisions = 0
        self.share_step_guard_stage_last = None
        self.share_step_refusals = {}
        self._i_tot_prev = None
        if self.planner is not None:
            self.planner.incumbent = None

    def bind_scenario(self, scenario, meta, electrical_mode=None,
                      args=None, droop_mode=None, asymmetry_mode=None,
                      drag_mode=None):
        """Build the preview and the planner for one scenario.

        The four trailing arguments are the generic startup hook's contract
        (``main()`` passes them BY NAME, so a signature without them is a
        TypeError at campaign time).  ``electrical_mode``, ``droop_mode`` and
        ``asymmetry_mode`` ARE consumed since 2026-09-02 (fix M1): together
        they resolve the DEMAND-MODEL ERA the planner predicts on.

        ⚠️ CORRECTED CLAIM.  This docstring used to say ``electrical_mode`` is
        "accepted and recorded but not consumed: the prediction model is the
        scenario's demand preview, which the bus engine does not change".  That
        stopped being true when the preview gained a static-loss map.  The four
        MPC scenarios are ``electrical: "any"`` and each declares
        ``mpc_loss_map``, so applying that key unconditionally would have made
        the planner predict on the hi-fi map during an ``--electrical simple``
        or ``--droop measured`` run, while the run sidecar and
        ``hil_report_analysis.matched_dp_for_run()`` both resolve the era from
        the run's own configuration and record ``None``.  Plan and bound would
        then sit on two different demand models, which is the defect the
        2026-09-02 round removed.  ``args`` IS
        consumed - its ``capacity_ah`` is the pack the run actually integrates,
        and a planner sized on the module default while the plant runs another
        capacity would mis-price every SoC term (the M2 check SdpStrategy makes
        for the same reason).

        The scenario may also declare ``mpc_soc_ref_offset``, the placement on
        the SoC axis, exactly as ``sdp_soc_ref_offset`` is a scenario property
        rather than a command-line one.  It is read AFTER ``reset()`` because
        the offset is a BINDING, not run state."""
        sim = _load_sim()
        self.scenario = scenario
        self.meta = meta
        self.electrical_mode = electrical_mode
        self.reset()
        cap_ah = BATT_CAPACITY_AH
        if args is not None and getattr(args, "capacity_ah", None):
            cap_ah = float(args.capacity_ah)
            if cap_ah <= 0.0:
                raise ValueError("capacity_ah must be positive, got %r" % (cap_ah,))
        self.cap_as = cap_ah * 3600.0
        offset = meta.get("mpc_soc_ref_offset")
        if offset is not None:
            self.soc_ref_offset = float(offset)
        # ── THE DEMAND-MODEL ERA, RECONCILED (2026-09-02, fix M1) ──────────
        # A scenario may bind the era, exactly as it binds the SoC reference
        # offset -- but the scenario key is a STATIC declaration resolved at
        # import, and the RUN decides which plant actually executes.  So the
        # key is an INTENT and the run's configuration is the fact, and the two
        # are reconciled here rather than the key winning blind.
        #
        #   both absent            -> keep the constructor's value (an ad-hoc
        #                             `--ems mpc-det` on some other scenario is
        #                             unaffected, which is the pre-fix
        #                             behaviour for every unregistered leg)
        #   key only, no run info  -> take the key (a walk, a test, any caller
        #                             that does not pass the modes)
        #   both, and they AGREE   -> take it
        #   both, and they DIFFER  -> take the RUN's, and SAY SO. Not a refusal:
        #                             a `--electrical simple` run of an
        #                             `electrical: "any"` scenario is a
        #                             legitimate thing to ask for, and the
        #                             correct answer is to plan on the demand
        #                             model that run will actually draw, which
        #                             is the same one its bound is priced with.
        want_lm = meta.get("mpc_loss_map")
        if want_lm is not None:
            want_lm = sim.check_loss_map(want_lm)
        if electrical_mode is not None:
            run_lm = sim.loss_map_for_config(
                electrical_mode,
                droop_mode if droop_mode is not None
                else sim.DP_LOSS_MAP_DROOP_MODE,
                asymmetry_mode if asymmetry_mode is not None
                else sim.DP_LOSS_MAP_ASYMMETRY_MODE)
            if want_lm is not None and run_lm != want_lm:
                print("[mpc] scenario %r declares a demand-model era this run "
                      "does not have (electrical=%s droop=%s asymmetry=%s); "
                      "planning on the RUN's era instead, so the plan and the "
                      "DP bound stay on one demand model.\n"
                      "[mpc]   scenario: %s\n"
                      "[mpc]   run:      %s"
                      % (scenario, electrical_mode, droop_mode,
                         asymmetry_mode, sim.loss_map_era_label(want_lm),
                         sim.loss_map_era_label(run_lm)), file=sys.stderr)
            self.loss_map = run_lm
        elif want_lm is not None:
            self.loss_map = want_lm
        chg_a = sim.dp_chg_ceiling_a(meta)
        run_exit_s = float(sim.SOC_BAND_RUN_EXIT_S
                           if meta.get("ems_run_exit_s") is None
                           else meta["ems_run_exit_s"])
        duration = float(meta["duration_s"])
        dt = self.preview_dt_s
        n = int(round(duration / dt)) + 1
        times = [k * dt for k in range(n)]
        # -- THE ROAD-LOAD PROFILE AND THE REGEN ERA (2026-09-02) --------
        # Resolved off the RESOLVED run configuration when `main()` supplies
        # it, and off the scenario's own key otherwise, so a walk and a live
        # run predict on the same plant.  `eta_regen` follows the drag profile
        # on the generator's rule: a compensated run regenerates, and a planner
        # that did not model the credit would systematically under-value
        # coasting relative to the bound it is scored against.
        drag = drag_mode or meta.get("drag") or sim.DRAG_MODE_RIG
        self.drag_mode = drag
        self.eta_regen = (None if drag == sim.DRAG_MODE_RIG
                          else float(sim.ETA_REGEN))
        # ONE reference pack voltage, at the NOMINAL 0.7 SoC.  The 0.7 is this
        # module's existing convention for `v_pack_ref` (it predates the regen
        # term and prices the charge mask's FC budget), and the regen credit
        # reuses it rather than minting a second reference: both quantities
        # must stay STATE-INDEPENDENT for the stage tables to remain a lookup.
        # ⚠️ The DP generator and the walk price the same two quantities at the
        # SOLVE'S OWN soc0. Every registered scenario runs soc0 = 0.7, so the
        # three agree today; a campaign at another soc0 would move the
        # planner's credit by the pack's OCV slope over that offset and no
        # other consumer's.
        v_pack_ref_all = pack_charge_voltage(0.7, chg_a)
        v, a, p_dem, v_bus, i_total, cruise, i_regen = build_demand(
            scenario, meta, times, dt, loss_map=self.loss_map,
            drag_mode=drag, eta_regen=self.eta_regen, eta_chg=self.eta_chg,
            v_pack_ref=v_pack_ref_all, regen_i_max_a=chg_a)
        v_pack_ref = (None if self.eta_chg is None else v_pack_ref_all)
        chg_ok = charge_mask(times, p_dem, v_bus, cruise, chg_a, run_exit_s,
                             self.eta_chg, v_pack_ref,
                             i_regen if self.eta_regen is not None else None)
        self.preview = Preview(times=times, p_dem=p_dem, v_bus=v_bus,
                               i_total=i_total, cruise=cruise, chg_ok=chg_ok,
                               i_regen=i_regen, dt=dt)
        self.run_exit_s = run_exit_s
        self.chg_a = chg_a
        # ── THE TWO SINGLE-SOURCE PREVIEWS (2026-09-03) ────────────────────
        # Built ONCE per scenario, not per decision: they are the same demand
        # model on the same profile with a different BUS LAW, and that law is a
        # property of the topology rather than of the state.  A scenario key
        # ORs with the constructor flag, so `--mpc-single-source` can arm a
        # scenario that does not declare it and vice versa.
        if meta.get("mpc_single_source"):
            self.single_source = True
        self.preview_ss = {}
        if self.single_source:
            if self.loss_map is None:
                # REFUSED, NOT DEGRADED.  `single_source_bus_law()` is a
                # SCALING of the fitted loss map's own effective droop
                # (1.9453x FC-only, 2.0579x BT-only); with no map there is no
                # law to scale, and billing a single-source stage on the
                # two-source law under-states the bus sag by ~0.45 V at the
                # 61 s cycle's peak.  Predicting a topology on the wrong bus
                # law is the class of defect this repository has had to retract
                # before, so the bind fails loudly instead.
                raise ValueError(
                    "%s: single-source candidates need a demand LOSS MAP - "
                    "the measured single-source bus law is a scaling of it "
                    "(hil_plant_sim.single_source_bus_law) and there is no "
                    "loss-map-free form of it. Bind the scenario with "
                    "`mpc_loss_map`, or run without --mpc-single-source."
                    % self.name)
            for _mode in (SS_MODE_FC, SS_MODE_BT):
                _v, _a, _pd, _vb, _it, _cr, _ir = build_demand(
                    scenario, meta, times, dt, loss_map=self.loss_map,
                    drag_mode=drag, eta_regen=self.eta_regen,
                    eta_chg=self.eta_chg, v_pack_ref=v_pack_ref_all,
                    regen_i_max_a=chg_a, source_mode=_mode)
                # `chg_ok` is ALL FALSE on a single-source preview and that is
                # not a shortcut: a charge window is itself a single-source
                # topology owned by `assertFcChargeEnable()`, and the two owners
                # are mutually exclusive (see `delivery_table`'s backstop and
                # the `SS_REFUSE_CHARGE` guard).
                self.preview_ss[_mode] = Preview(
                    times=times, p_dem=_pd, v_bus=_vb, i_total=_it,
                    cruise=_cr, chg_ok=[False] * len(times),
                    i_regen=_ir, dt=dt)
        self.planner = Planner(horizon=self.horizon, blocks=self.blocks,
                               share_band=self.share_band,
                               share_levels=self.share_levels,
                               terminal_mode=self.terminal_price_mode,
                               budget_ms=(BUDGET_MS_DEFAULT
                                          if self.budget_ms is None
                                          else self.budget_ms),
                               max_candidates=self.max_candidates,
                               eta_chg=self.eta_chg,
                               chg_a=chg_a,
                               cap_as=self.cap_as,
                               h2_map=self.h2_map, h2_convex=self.h2_convex,
                               dv0_v=self.dv0_v,
                               droop_scale_fc=self.droop_scale_fc,
                               r_series_ohm=self.r_series_ohm,
                               ff_dark_model=self.ff_dark_model,
                               single_source=self.single_source)
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
        # ── THE DEMAND MAP AND THE BIN EDGES, READ FROM THE ARTIFACT ────────
        # M3 (review of 2026-09-02).  The map (`normalization.p_dem_min_w` /
        # `p_dem_max_w`) and the NORMALIZED edges (`demand_bins.edges`) were
        # hard-coded here as (0, 25) W and a uniform 1/n partition.  Both
        # happen to be right for `sdp_policy_v3.json`, and that is precisely
        # the failure mode: a regenerated artifact with a different map would
        # have moved sdp-v3's bins and left this strategy classifying against
        # the old one, with nothing in either trace to show it.  The file is
        # now the source and the constants are the assertion.
        self.demand_map_source = None
        try:
            self._read_demand_map()
        except (OSError, ValueError, KeyError) as exc:
            raise ValueError(
                "mpc-sto cannot read the demand map from %s: %s.  The bin a "
                "measured bus power lands in must be the bin sdp-v3 would "
                "use, and no default for it is invented here."
                % (SDP_POLICY_FOR_DEMAND_MAP, exc))
        if len(self.tpm_edges) - 1 != n:
            raise ValueError(
                "the SDP artifact declares %d demand bins but %s is %dx%d: the "
                "policy and the transition matrix are not the same demand map"
                % (len(self.tpm_edges) - 1, os.path.basename(path), n, n))

    def _read_demand_map(self):
        """Load `normalization` and `demand_bins.edges` from the SDP artifact."""
        import json                       # stdlib
        pol_path = os.path.join(_TOOLS, "sdp_policies",
                                SDP_POLICY_FOR_DEMAND_MAP)
        with open(pol_path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        norm = doc["normalization"]
        lo = float(norm["p_dem_min_w"])
        hi = float(norm["p_dem_max_w"])
        if not hi > lo:
            raise ValueError("p_dem_max_w %r must exceed p_dem_min_w %r"
                             % (hi, lo))
        edges = [float(e) for e in doc["demand_bins"]["edges"]]
        if len(edges) < 2 or any(b <= a for a, b in zip(edges, edges[1:])):
            raise ValueError("demand_bins.edges must be strictly increasing")
        if abs(edges[0]) > 1e-9 or abs(edges[-1] - 1.0) > 1e-9:
            raise ValueError("demand_bins.edges must span [0, 1], got "
                             "[%r, %r]" % (edges[0], edges[-1]))
        # THE ASSERTION.  The shipped artifact's map is the one every measured
        # figure in the design document was taken against; a file that moved it
        # is a file this strategy has not been evaluated on, and it says so
        # rather than silently repricing the forecast.
        if (abs(lo - DEMAND_MAP_W_EXPECTED[0]) > 1e-9
                or abs(hi - DEMAND_MAP_W_EXPECTED[1]) > 1e-9):
            raise ValueError(
                "the artifact's demand map is (%g, %g) W but this strategy's "
                "measured figures were taken against (%g, %g) W: re-measure "
                "before moving the constant"
                % ((lo, hi) + DEMAND_MAP_W_EXPECTED))
        self.tpm_map_w = (lo, hi)
        self.tpm_edges = edges
        self.demand_map_source = norm.get("demand_map_source")
        self.demand_map_path = pol_path

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
            "loss_map": (None if self.loss_map is None
                         else dict(self.loss_map)),
            # THE ROAD-LOAD PROFILE AND THE REGEN ERA the planner PREDICTED ON
            # (2026-09-02).  Recorded for `loss_map`'s reason: `config.mpc` is
            # the only place a trace says which demand model the controller
            # carried, and a mismatch against the plant is invisible otherwise.
            "drag": getattr(self, "drag_mode", None),
            "eta_regen": getattr(self, "eta_regen", None),
            # None means ADAPTIVE: the per-decision budget is derived by
            # `derive_budget_ms()` and reported in `timing()` as the
            # budget_ms_min/median/max triple, because it is no longer a
            # constant of the run.
            "budget_ms": self.budget_ms,
            "budget_adaptive": self.adaptive_budget,
            "budget_margin_ms": BUDGET_MARGIN_MS,
            "budget_floor_ms": BUDGET_MS_FLOOR,
            "budget_ceiling_ms": BUDGET_MS_CEILING,
            "coarsen_ladder": self.coarsen_ladder_enabled,
            "candidate_cost_ms": self.candidate_cost_ms,
            "roll_budget_ms": self.roll_budget_ms,
            "roll_tick_chunk": RollJob.TICK_CHUNK,
            "max_transitions": RollJob.MAX_TRANSITIONS,
            "max_candidates": self.max_candidates,
            # The number the cap has to be read AGAINST (2026-09-02).  A cap
            # BELOW this truncates the search, and — because the charge options
            # are enumerated after the share ladder — it truncates the CHARGE
            # AXIS first, which is exactly the reading an MPC leg is used to
            # make.  Recorded per run so a report never has to reconstruct it
            # from the ladder and the move blocks.
            "enumeration_size": enumeration_size(self.share_levels, self.blocks),
            "max_charge_options": MAX_CHARGE_OPTIONS,
            "soc_ref_offset": self.soc_ref_offset,
            # ── SINGLE-SOURCE (2026-09-03) ─────────────────────────────────
            # Recorded for `loss_map`'s reason: it changes the CONTROL SET, so
            # a trace that does not say whether it was armed cannot be compared
            # with one that does.  `single_source_admit_ticks` is the roll
            # window the admissibility test spends per candidate.
            "single_source": self.single_source,
            "single_source_admit_ticks": (SS_ADMIT_MAX_TICKS
                                          if self.single_source else None),
            "single_source_cut_guard_a": (
                gov_mod.GOV_CONST["SHARE_CUT_MAX_HANDOFF_A"]
                if self.single_source else None),
            # ── THE SHARE-STEP GUARD (2026-09-03) ──────────────────────────
            # Recorded for `single_source`'s reason exactly: the guard changes
            # the CONTROL SET at block 0, so a trace that does not say which
            # threshold it was planned under cannot be compared with one that
            # does.  It is always armed - there is no flag - so the constant is
            # the whole declaration; the counts are in `timing()`.
            "share_step_guard_i_tot_a": SHARE_STEP_GUARD_I_TOT_A,
            "dv0_v": self.dv0_v,
            # THE SPLIT LAW THE PLANNER PREDICTED WITH (2026-09-03, review
            # run-002 PLANT-R2-F3).  Recorded beside `dv0_v` because the three
            # are one law: a trace that says only which dV0 was modelled cannot
            # be told apart from one planned on the pre-2026-09-03 map.
            "droop_scale_fc": self.droop_scale_fc,
            "r_series_ohm": self.r_series_ohm,
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
            "capacity_ah": self.cap_as / 3600.0,
            "electrical_mode": self.electrical_mode,
        }
        if self.h2_map == "convex":
            prov["h2_convex"] = dict(self.h2_convex or {})
        if self.variant == "sto":
            prov["tpm_path"] = self.tpm_path
            prov["tpm_n_bins"] = len(self.tpm) if self.tpm else None
            prov["oc_quantile"] = STO_OC_QUANTILE
            prov["demand_map_w"] = list(self.tpm_map_w)
            prov["demand_map_path"] = self.demand_map_path
            prov["demand_map_source"] = self.demand_map_source
            prov["demand_bin_edges_n"] = (None if self.tpm_edges is None
                                          else len(self.tpm_edges) - 1)
        return prov

    # -- the roll table -----------------------------------------------------
    def _publish_roll(self, job):
        """Fold a completed roll job into ``r_hold``.

        H2 (review of 2026-09-02).  This used to be ``self.r_hold = job.table``,
        which WIPED the standing table whenever the completed job carried no
        items - and a job carries no items whenever the horizon holds no
        transition, which on `ems-soc-band` is 8 consecutive decisions.  The
        table is now MERGED, and only keys whose absolute stage has receded past
        the job's own horizon start are dropped.  Both halves matter: a merge
        without the prune grows without bound over a run, and a replacement
        without the merge throws away rolls that are still current."""
        if not job.table:
            self.rolls_empty += 1
            return
        self.r_hold.update(job.table)
        self.r_handoff.update(job.handoff)
        k_min = min(job.stage_key) if job.stage_key else 0
        self.r_hold = {k: v for k, v in self.r_hold.items() if k[0] >= k_min}
        self.r_handoff = {k: v for k, v in self.r_handoff.items()
                          if k[0] >= k_min}
        self.rolls_published += 1
        self.roll_dropped_transitions += job.dropped_transitions

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
    # ── THE ROLLOUT-TIME CUT-GUARD TEST (2026-09-03) ───────────────────────
    def _ss_shadow_copy(self):
        """A throwaway ``GovernorModel`` carrying the shadow's committed state.

        The admissibility roll must not disturb the committed estimate, so it
        runs on a copy.  ``GovernorState`` is a dataclass of scalars and one
        counter dict, so ``copy.deepcopy`` is exact and cheap (~6 us)."""
        g = gov_mod.GovernorModel(dt_s=GOV_TICK_S, dv0_v=self.dv0_v,
                                  droop_scale_fc=self.droop_scale_fc,
                                  r_series_ohm=self.r_series_ohm)
        g.v_bus_ok = self.shadow.model.v_bus_ok
        g.state = copy.deepcopy(self.shadow.model.state)
        return g

    def _ss_admissible(self, mode, t, pre, pre_ss, i_tot_oc=None):
        """Is the single-source command ``mode`` admissible from HERE?

        THE OPERATOR'S RULING, implemented: "let's do the rollout-time test".
        The firmware's share-cut load guard refuses a cut while the DOOMED
        channel carries more than ``SHARE_CUT_MAX_HANDOFF_A`` 0.5 A, and that
        current is the DELIVERED split at the instant of the cut - a property of
        the path, not of the stage.  So the test rolls the REAL
        ``GovernorModel`` forward from the shadow governor's committed state, at
        1 kHz, with the single-source setpoint commanded and the plant currents
        taken from this stage's preview sub-samples, and asks whether the latch
        actually engages.

        Returns ``(ok, reason, ticks, ms)``.  ``reason`` is None when admissible
        and one of the ``SS_REFUSE_*`` strings otherwise.

        FOUR CONDITIONS, in the order they are cheapest to fail:

        1. THE SURVIVOR'S OWN OVERCURRENT, over the stages the candidate would
           run (block 0).  With one channel off the bus the survivor carries
           ``i_total`` on the SINGLE-SOURCE bus law, judged against 0.85 x its
           firmware limit - 1.19 A for the fuel cell, 2.55 A for the battery.
           Scaled by ``i_tot_oc`` where the caller supplies one, so `mpc-sto`
           judges this condition on the SAME quantile-tightened demand
           ``delivery_table()`` judges the column on.
        2. THE RESTORE, over the first stage after block 0.  ⚠️ CHECKED
           ALGEBRAICALLY, NOT ROLLED, and the reason is in the firmware: the
           RELEASE arm of ``updateShareSetpointCutoff()`` carries NO load guard
           (.ino, and ``governor_model._setpoint_cutoff()``'s release branch) -
           it tests only the charged-bus/boost-enabled condition, modelled as
           ``v_bus_ok``.  There is therefore nothing path-dependent to roll.
           What CAN still bite is the survivor carrying the whole load through
           the restored channel's 30 ms turn-on blanking, so the restore stage's
           opening current is judged against the SAME survivor bound.
        3. THE CUT ITSELF, rolled.  Admissible only if the latch engages within
           ``SS_ADMIT_MAX_TICKS``.
        4. THE REFUSAL REASON, if it does not: the roll's own
           ``refused_load`` / ``refused_blank`` counters say which guard held it
           off, and a roll that never even proposed a cut reports
           ``cut_never_engaged``."""
        t0 = time.perf_counter()
        lim = SS_LIMIT_A[mode]
        p = pre_ss[mode]
        n_block0 = min(pre.n, self.blocks[0])

        # THE QUANTILE TIGHTENING REACHES CONDITIONS 1 AND 2 (fixed
        # 2026-09-03, review LOW-2).  On `mpc-sto` the demand the table is
        # SCORED on is the TPM's conditional mean, while the demand it is
        # judged OVERCURRENT-safe on is the 90 % quantile - that is what
        # `i_tot_oc` is.  `delivery_table()` applies the per-stage ratio to the
        # single-source column; this test judged the SAME candidate on the
        # unscaled mean, so a candidate the table would mark infeasible could
        # still be admitted here.  The ratio is taken against the TWO-source
        # stage mean exactly as `delivery_table()` takes it: it is a
        # DEMAND-FORECAST scale, not a topology one, so the same number applies
        # to both bus laws.  `None` (the deterministic variant) leaves 1.0.
        def _oc(j):
            if i_tot_oc and 0 <= j < pre.n and pre.i_tot_mean[j] > 0.0:
                return i_tot_oc[j] / pre.i_tot_mean[j]
            return 1.0

        for j in range(n_block0):
            sc = _oc(j)
            for sub in range(len(p.i_tot[j])):
                if p.i_tot[j][sub] * sc > lim:
                    return (False, SS_REFUSE_OC, 0,
                            (time.perf_counter() - t0) * 1e3)
        if n_block0 < pre.n and p.i_tot[n_block0]:
            # The restore stage's OPENING sub-sample: the blanking window is
            # 30 ms and a sub-sample is 100 ms, so the opening sample is the one
            # the survivor carries alone.
            if p.i_tot[n_block0][0] * _oc(n_block0) > lim:
                return (False, SS_REFUSE_RESTORE, 0,
                        (time.perf_counter() - t0) * 1e3)

        sp = SS_SHARE[mode]
        cut_ch = SS_CUT_CHANNEL[mode]
        g = self._ss_shadow_copy()
        st = g.state
        load0, blank0 = st.refused_load, st.refused_blank
        # The plant the roll is driven by is the TWO-SOURCE preview, because
        # until the cut fires both channels are on the bus - which is exactly
        # the current the load guard reads.
        n_sub = len(pre.i_tot[0])
        per = max(1, int(round(DECISION_DT_S / GOV_TICK_S)) // n_sub)
        delivered = self.shadow.model.delivered_share(
            st.r_prev, pre.i_tot[0][0], st.sw_fc, st.sw_bt)
        engaged = None
        for tk in range(SS_ADMIT_MAX_TICKS):
            sub = min(n_sub - 1, tk // per)
            i_tot = pre.i_tot[0][sub]
            i_fc = delivered * i_tot
            o = g.step(sp, i_fc, i_tot - i_fc, st.sw_fc, st.sw_bt,
                       float(t) + tk * GOV_TICK_S)
            delivered = g.delivered_share(o.r_applied, i_tot,
                                          o.fc_bus_req, o.bt_bus_req)
            if (st.sp_cut_fc if cut_ch == "fc" else st.sp_cut_bt):
                engaged = tk + 1
                break
        ms = (time.perf_counter() - t0) * 1e3
        if engaged is not None:
            return True, None, engaged, ms
        if st.refused_load > load0:
            return False, SS_REFUSE_CUT_LOAD, SS_ADMIT_MAX_TICKS, ms
        if st.refused_blank > blank0:
            return False, SS_REFUSE_CUT_BLANK, SS_ADMIT_MAX_TICKS, ms
        return False, SS_REFUSE_CUT_NEVER, SS_ADMIT_MAX_TICKS, ms

    def _ss_refuse(self, reason, n=1):
        self.ss_refusals[reason] = self.ss_refusals.get(reason, 0) + n

    def _ss_state_guards_pass(self, fb, charge_options):
        """The CHEAP guards, evaluated before any preview work is done.

        Split out from `_ss_modes()` so a decision the state already forbids
        costs nothing: on `ems-mpc-cross` the charge guard alone refuses 362 of
        400 offers, and building two extra stage precomputes for them would be
        work spent inside the callback bound for a verdict already known."""
        if not self.single_source or not self.planner.ss_index:
            return False
        self.ss_offered += 2
        # ── THE THREE STATE GUARDS (deliverable 3) ─────────────────────────
        # 1. A REGEN WINDOW.  The firmware's `regenActive` branch owns REGEN and
        #    MOT_PWR and the braking chopper is clamping; a setpoint latch on
        #    top of a regen transient hands the whole braking current to one
        #    channel through a 30 ms blanking window.  The same guard the charge
        #    dwell already carries.
        #    ⚠️ TWO SOURCES, EITHER OF WHICH REFUSES (fixed 2026-09-03, review
        #    MED-3).  `regen_commanded` is a HOST key, written onto the feedback
        #    view by the scenario's `RegenManager`; a scenario without one -
        #    `ems-mpc-single` is exactly that - never carries the key, and the
        #    guard was inert there while the FIRMWARE's own `regenActive` can
        #    still open `REGEN_ENABLE` off the commanded current.  So the
        #    OBSERVED switch word is consulted too: `SW_REGEN` set in the
        #    observation frame's `switch` byte means the board has the regen
        #    path open right now, whoever opened it.
        #    THE LIMITATION, stated: the observed bit is one HIL round trip
        #    behind (~1.9 ms) and is BLANK before the first observation frame
        #    decodes, so on a run with no `RegenManager` the guard is a
        #    one-frame-late detector rather than a predictive one.  It is the
        #    only regen evidence such a run has.
        _sw = fb.get("switch")
        if fb.get("regen_commanded") or (_sw is not None
                                         and (int(_sw) & SW_REGEN_BIT)):
            self._ss_refuse(SS_REFUSE_REGEN, 2)
            return False
        # 2. AN FC-CHARGE WINDOW.  `assertFcChargeEnable()` ALREADY holds BT off
        #    the bus, so the topology is single-source and the share loop is
        #    pinned; a second owner of the same switch is the "one owner per
        #    setpoint" invariant broken.  Judged on the option the decision may
        #    COMMIT, which is stage 0 of any offered option.
        if any(o[0] for o in charge_options):
            self._ss_refuse(SS_REFUSE_CHARGE, 2)
            return False
        # 3. A DEFERRED CUT OR A STANDING LATCH.  A deferred cut means the load
        #    guard is already refusing a handoff the firmware wants; commanding
        #    a second one is the leak the fw v6 deferral exists to prevent.  A
        #    standing latch means one channel is already off the bus, so the
        #    candidate is not a decision the planner still has to make.
        if self.shadow.deferred:
            self._ss_refuse(SS_REFUSE_DEFERRED, 2)
            return False
        if self.shadow.sp_cut is not None:
            self._ss_refuse(SS_REFUSE_LATCHED, 2)
            return False
        # ⚠️ THE fw v26 CURRENT-CEILING CLAMP IS IRRELEVANT HERE, and this is
        # why.  `applyShareCurrentCeilings()` runs inside `powerBalance()`'s
        # CLOSED-LOOP and FEEDFORWARD arms; an out-of-band setpoint returns from
        # `updateShareSetpointCutoff()` with the whole share loop FROZEN before
        # either arm is reached (.ino:10087, and `GovernorModel.step()`'s
        # `MODE_LATCHED` return, which explicitly clears the clamp state).  The
        # clamp also constrains its result into [DROOP_R_MIN, DROOP_R_MAX], so
        # it could not express a single-source split even if it ran.  The
        # survivor's overcurrent is bounded by condition 1 of
        # `_ss_admissible()` instead, at the same 0.85 margin.
        return True

    def _ss_modes(self, t, pre, pre_ss, i_tot_oc=None):
        """The single-source modes this decision may search, after the cheap
        guards have already passed.  Tuple, possibly empty; every refusal is
        counted in ``ss_refusals`` by reason."""
        out = []
        for mode in (SS_MODE_BT, SS_MODE_FC):
            ok, reason, ticks, ms = self._ss_admissible(
                mode, t, pre, pre_ss, i_tot_oc=i_tot_oc)
            self.ss_admit_ms_max = max(self.ss_admit_ms_max, ms)
            if ok:
                self.ss_admissible += 1
                self.ss_admit_ticks_max = max(self.ss_admit_ticks_max, ticks)
                out.append(mode)
            else:
                self._ss_refuse(reason)
        return tuple(out)

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
        # The per-stage forecast scale, kept so the SINGLE-SOURCE precomputes
        # can be moved onto the SAME demand the two-source one was moved onto
        # (2026-09-03).  `None` on the deterministic variant, where nothing is
        # scaled.
        sto_scale = None
        if self.variant == "sto":
            p_meas = ((fb.get("V_bus") or 0.0)
                      * ((fb.get("I_fc") or 0.0) + (fb.get("I_batt") or 0.0)))
            # SELF-LOAD SUBTRACTION (M2, review of 2026-09-02), term for term
            # SdpStrategy's: while a charge hold is in force the strategy must
            # not read its OWN charger as demand.  That feedback is the chatter
            # the campaign-000816 hysteresis round removed; a forecast built on
            # it classifies a charging cruise as a high-demand bin and predicts
            # the demand its own decision created.  Floored at the demand map's
            # own minimum, not at 0, because the two products are measured
            # independently and a sub-milliwatt negative residue would be
            # counted as a map excursion it is not.
            hold_now = self.latch.status(t, fb)
            if hold_now in ("active", "expired"):
                p_chg = ((fb.get("V_bus") or 0.0) * (fb.get("I_charge") or 0.0))
                p_meas = max(self.tpm_map_w[0], p_meas - p_chg)
            means, quants = self._tpm_forecast(self._bin_of(p_meas))
            sto_scale = [1.0] * pre.n
            for j in range(pre.n):
                vb = pre.v_bus_mean[j]
                scale = (means[j] / pre.p_dem_mean[j]
                         if pre.p_dem_mean[j] > 0.0 else 1.0)
                sto_scale[j] = scale
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
        # `status()` has side effects (it is what DROPS a latch), so it is
        # evaluated exactly once per decision and the result reused.
        hold = hold_now if self.variant == "sto" else self.latch.status(t, fb)
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

        # ── the transition rolls: CREATED here, SLICED in __call__ ─────────
        # H1 (review of 2026-09-02).  `advance()` used to be called from HERE,
        # which is the 1 Hz decision path, so the job received ONE slice per
        # DECISION rather than one per 50 Hz callback and the table almost never
        # completed - r_hold was empty on 38 of 61 decisions.  The slice now
        # runs in __call__() ahead of the decision gate; this path only CREATES
        # the job, and only when none is in flight.
        if self.roll_job is None:
            # ⚠️ THE IN-BAND LADDER ONLY (2026-09-03).  A transition roll
            # produces `r_hold[stage][ladder index]`, the ratio a HELD in-band
            # command leaves standing across a mode change.  A single-source
            # column has no such carry - the share loop is frozen and the ratio
            # is whatever the latch left - and rolling the two extra columns
            # would add 22 % to the slice for entries `delivery_table()` never
            # reads.
            self.roll_job = RollJob(pre,
                                    self.planner.ladder[:self.planner.n_band],
                                    dv0_v=self.dv0_v,
                                    droop_scale_fc=self.droop_scale_fc,
                                    r_series_ohm=self.r_series_ohm,
                                    charge_stage=lambda j, o=charge_options[-1]: o[j])
            self.rolls_started += 1

        # THE OPEN-LOOP SUBMODE SEEDS.  `share_actedSp` and `shareClosedLoopRun`
        # are the two firmware variables that decide whether an open tick HOLDS
        # or takes the feedforward slew, and the shadow governor is the committed
        # estimate of both.  Passing them is what arms the feedforward-aware
        # stage model; without them the planner falls back to the hold-only
        # table (see `delivery_table`).
        # ── THE ADAPTIVE BUDGET (2026-09-02) ───────────────────────────────
        # Derived from the callback bound's own terms, with this callback's
        # measured roll slice and surface work and the previous decision's
        # measured per-candidate cost.  A fixed `budget_ms` short-circuits it.
        if self.adaptive_budget:
            raw_ms = derive_budget_raw_ms(roll_slice_ms=self._roll_slice_ms,
                                          surface_ms=self._surface_ms,
                                          rollout_ms=self._rollout_ms)
            budget_ms = min(BUDGET_MS_CEILING, max(BUDGET_MS_FLOOR, raw_ms))
            # M2: the floor is a DEVIATION from the callback bound, not an
            # application of it - past this point the callback total exceeds the
            # command period.  Counted so `timing()` can say so.
            if raw_ms < BUDGET_MS_FLOOR:
                self.budget_floor_binding += 1
        else:
            budget_ms = (BUDGET_MS_DEFAULT if self.budget_ms is None
                         else self.budget_ms)

        # ── THE SINGLE-SOURCE CANDIDATES (2026-09-03) ──────────────────────
        # Resolved BEFORE the coarsening, because the coarsening's allowance has
        # to be sized on the enumeration the search will actually walk, and an
        # admitted single-source column adds a block-0 value to it.  The
        # admissibility rolls are charged to THIS decision's budget: they are
        # wall-clock work inside the same callback, and leaving them out would
        # make the derived budget a bound the callback does not meet.
        ss_modes = ()
        pre_ss = None
        if (self.preview_ss
                and self._ss_state_guards_pass(fb, charge_options)):
            _t_ss = time.perf_counter()
            pre_ss = {m: precompute_stages(
                self.preview_ss[m], k0, self.horizon,
                mode_seed=(STAGE_CLOSED if self.shadow.closed
                           else STAGE_OPEN))
                for m in self.preview_ss}
            # THE STOCHASTIC VARIANT'S FORECAST REACHES THE SINGLE-SOURCE
            # DEMAND TOO (2026-09-03).  Without this the survivor's overcurrent
            # condition would be judged on the DETERMINISTIC preview while the
            # two-source table was judged on the TPM's conditional mean, i.e.
            # the two arms of one decision would sit on two demand forecasts.
            # The scale is the same per-stage ratio, applied to the
            # single-source arrays: the bus law differs between the two
            # previews, the DEMAND FORECAST does not.
            if sto_scale is not None:
                for p_m in pre_ss.values():
                    for j in range(p_m.n):
                        sc = sto_scale[j]
                        if sc == 1.0:
                            continue
                        for sub in range(len(p_m.i_tot[j])):
                            p_m.i_tot[j][sub] *= sc
                            p_m.p_dem[j][sub] *= sc
                        p_m.i_tot_mean[j] *= sc
                        p_m.p_dem_mean[j] *= sc
            ss_modes = self._ss_modes(t, pre, pre_ss, i_tot_oc=i_tot_oc)
            budget_ms = max(BUDGET_MS_FLOOR,
                            budget_ms - (time.perf_counter() - _t_ss) * 1e3)

        # ── THE LADDER COARSENING ──────────────────────────────────────────
        # A pure function of the ladder size, the block count, this decision's
        # charge-option count, the previewed transition count and the budget.
        n_trans = sum(1 for j in range(pre.n) if pre.transition[j])
        self.transition_stages_last = n_trans
        active = None
        if self.coarsen_ladder_enabled:
            # ⚠️ SIZED ON `n_band`, NOT ON `len(ladder)` (2026-09-03).  The
            # coarsening chooses a subset of the IN-BAND rungs; the
            # single-source columns are not rungs and are never coarsened away
            # (they are already admissible or already refused).  Their cost is
            # charged instead through `n_options`, below: an admitted
            # single-source column multiplies the block-0 arm of the
            # enumeration by (k + n_ss)/k, and scaling the option count by the
            # same factor is the same allowance.
            _ss_growth = ((len(ss_modes) + self.planner.n_band)
                          / float(self.planner.n_band)) if ss_modes else 1.0
            active = coarsen_ladder(self.planner.n_band,
                                    len(self.planner.blocks),
                                    len(charge_options) * _ss_growth,
                                    incumbent=self.planner.incumbent,
                                    budget_ms=budget_ms,
                                    n_transitions=n_trans,
                                    candidate_cost_ms=(
                                        self.candidate_cost_ms
                                        or CANDIDATE_COST_MS_NOMINAL))
            if len(active) >= self.planner.n_band:
                active = None

        # ── THE SHARE-STEP GUARD (2026-09-03, the operator ruling) ─────────
        # Evaluated HERE, after the stochastic variant has moved `pre` onto the
        # TPM's conditional mean: the rule is about the demand the planner is
        # ACTING ON, so it must read the same forecast the delivery table does.
        # `self._i_tot_prev` is the total the previous decision predicted for
        # the stage that has just run - see `Planner.share_step_guard_stage()`
        # for the definition of "rising" and why the carried value is what makes
        # stage 0 testable.  The reference the upward step is measured FROM is
        # the governor's committed ratio `self.shadow.r`, which is the same
        # quantity `solve()` already takes as `r_seed`.
        step_guard_r = None
        j_fire = Planner.share_step_guard_stage(
            pre, self._i_tot_prev, self.planner.blocks[0])
        if j_fire is not None:
            step_guard_r = self.shadow.r
            self.share_step_guard_decisions += 1
            self.share_step_guard_stage_last = j_fire
        self._i_tot_prev = pre.i_tot_mean[0] if pre.n else None

        dec = self.planner.solve(soc, self.soc_ref, pre, self.r_hold,
                                 self.shadow.r, charge_options,
                                 i_tot_oc=i_tot_oc, budget_ms=budget_ms,
                                 sp_acted=self.shadow.acted_sp,
                                 run_seed=self.shadow.closed_loop_run,
                                 handoff=self.r_handoff, active=active,
                                 ss_modes=ss_modes, pre_ss=pre_ss,
                                 share_step_guard_r=step_guard_r)
        if dec.share_step_refused:
            self.share_step_refusals[SHARE_STEP_REFUSE_UPWARD] = (
                self.share_step_refusals.get(SHARE_STEP_REFUSE_UPWARD, 0)
                + dec.share_step_refused)
        self.ss_searched += int(dec.ss_offered)
        if dec.single_source == SS_MODE_FC:
            self.ss_selected_fc += 1
        elif dec.single_source == SS_MODE_BT:
            self.ss_selected_bt += 1
        self.ss_selected_last = dec.single_source
        self.budget_ms_all.append(budget_ms)
        self.ladder_points_all.append(dec.ladder_points)
        if active is not None:
            self.coarsened_decisions += 1
        # The per-candidate cost.  TWO USES, and only one of them is a control
        # input: the next budget derivation charges it as its one rollout of
        # expiry overshoot (a wall-clock term of a wall-clock budget), and
        # `timing()` reports the largest value seen so a host too slow for
        # `CANDIDATE_COST_MS_NOMINAL` is visible.  It does NOT reach
        # `coarsen_ladder()` any more (H1).
        if dec.candidates:
            self._rollout_ms = dec.solve_ms / float(dec.candidates)
            self.candidate_cost_ms_seen = max(self.candidate_cost_ms_seen,
                                              self._rollout_ms)
        self.decisions += 1
        self.candidates_last = dec.candidates
        self.candidates_min = (dec.candidates if self.candidates_min is None
                               else min(self.candidates_min, dec.candidates))
        self.candidates_max = (dec.candidates if self.candidates_max is None
                               else max(self.candidates_max, dec.candidates))
        self.solve_ms_last = dec.solve_ms
        self.solve_ms_all.append(dec.solve_ms)
        self.solve_ms_max = max(self.solve_ms_max, dec.solve_ms)
        if dec.budget_hit:
            self.budget_hits += 1
        if dec.cap_hit:
            self.cap_hits += 1
        if not dec.feasible:
            self.infeasible_decisions += 1
        if dec.share == self.last_share and dec.charge == (self.last_goal > 0.0):
            self.incumbent_retained += 1

        # ── the stage prediction, SCORED (L1) ──────────────────────────────
        # The claim is a STAGE-MEAN delivered share, so it is scored against the
        # mean of the samples accumulated across the stage that has just run,
        # not against one sample at this instant.
        if self.share_pred is not None and self._stage_share_n:
            err = abs(self.share_pred
                      - self._stage_share_sum / self._stage_share_n)
            self.share_pred_err = err
            self.share_pred_err_max = max(self.share_pred_err_max, err)
            self.share_pred_err_sum += err
            self.share_pred_err_n += 1
            # ... and again over the SCORED window alone. The stage just
            # scored ENDS at this decision, so `t` is the right instant to
            # ask the question at.
            if sim.EMS_RUN_ENTRY_S <= t < sim.ems_run_exit(fb,
                                                          self.run_exit_s):
                self.share_pred_err_run_max = max(
                    self.share_pred_err_run_max, err)
                self.share_pred_err_run_sum += err
                self.share_pred_err_run_n += 1
        self._stage_share_sum = 0.0
        self._stage_share_n = 0
        # Predicted delivered share of the stage about to run, scored at the
        # NEXT decision by the block above.
        self.share_pred = dec.share_pred

        share = dec.share
        goal = sim.SOC_BAND_CHARGE_GOAL if dec.charge else 0.0
        if hold == "active":
            goal = sim.SOC_BAND_CHARGE_GOAL
        elif hold == "dropped":
            goal = 0.0
        elif goal > 0.0 and not fb.get("regen_commanded"):
            # A REGEN WINDOW MUST NOT ARM AN FC DWELL (M2, 2026-09-02), the
            # same guard `SdpStrategy.decide()` and `SocBandStrategy.__call__()`
            # already carry.  The 8 s dwell is a HOST construct governing the
            # FC-PATH windows; inside a regen window the firmware's
            # `regenActive` branch owns the charger and the FC path is shut, so
            # arming here would put a window in the census that never existed
            # and would pin the intent high for 8 s after the braking ended.
            # `regen_commanded` is absent, i.e. False, on every run without a
            # regen manager, so no existing trace moves.
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

        # ── THE ROLL SLICE, at 50 Hz and AHEAD of the decision gate (H1) ────
        # This is the mechanism the adjudication's section 2.2 specifies: the
        # transition table is built across the callbacks of the second BETWEEN
        # decisions, and the decision that follows consumes whatever is
        # standing.  Running it here rather than inside decide() is what gives
        # the job its 50 slices per second instead of one.
        _t_surface0 = time.perf_counter()
        _t_roll = 0.0
        if self.roll_job is not None:
            _t0 = time.perf_counter()
            done = self.roll_job.advance(self.roll_budget_ms * 1e-3)
            _t_roll = (time.perf_counter() - _t0) * 1e3
            if done:
                self._publish_roll(self.roll_job)
                self.roll_job = None
        # MEASURED, not assumed: the roll slice is what it cost including its
        # one-chunk overshoot, and the surface work is everything this callback
        # does outside the slice and the decision.  Both are taken BEFORE the
        # decision gate below and are therefore consumed by THIS callback's own
        # budget derivation, not by the next one - which is the point, since the
        # bound they enforce is a bound on this callback (L3, review of
        # 2026-09-02).  The one term that IS carried from the previous decision
        # is the per-candidate rollout cost, which cannot be known before the
        # search it describes has run.
        #
        # TWO KNOWN OPTIMISMS, both bounded and both stated rather than
        # corrected.  A callback with no roll job in flight measures a slice cost
        # of zero, and the decision it may then take creates one - so the FIRST
        # callback after a publication under-charges the slice by at most
        # `roll_budget_ms` plus one chunk.  And the surface measurement stops at
        # the decision gate, so the command dictionary's own construction is not
        # counted.  Both are far inside the 2 ms margin the derivation holds
        # back, and the 15 ms ceiling bounds the result independently.
        self._roll_slice_ms = _t_roll

        # ── the prediction claim, ACCUMULATED OVER THE STAGE (L1) ──────────
        # `share_pred` is the mean DELIVERED share the model predicts for the
        # whole stage, so the honest error is against the stage's MEAN measured
        # share, not against whichever 20 ms sample the next decision happens to
        # land on.  The samples are accumulated here and scored once per
        # decision, in decide().
        if self.share_pred is not None:
            i_fc = abs(float(fb.get("I_fc") or 0.0))
            i_bt = abs(float(fb.get("I_batt") or 0.0))
            tot = i_fc + i_bt
            if tot > GOV_MIN_LOAD_A and not charging:
                self._stage_share_sum += i_fc / tot
                self._stage_share_n += 1

        self._surface_ms = ((time.perf_counter() - _t_surface0) * 1e3
                            - _t_roll)
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
                    "decisions": 0, "budget_hits": 0, "cap_hits": 0,
                    "candidates_last": None, "candidates_min": None,
                    "candidates_max": None,
                    "rolls_published": 0, "rolls_empty": 0,
                    "roll_dropped_transitions": 0,
                    "budget_ms_min": None, "budget_ms_median": None,
                    "budget_ms_max": None, "budget_adaptive": self.adaptive_budget,
                    "ladder_points_min": None, "ladder_points_median": None,
                    "ladder_points_max": None, "coarsened_decisions": 0,
                    "budget_floor_binding": 0,
                    "candidate_cost_ms_nominal": self.candidate_cost_ms_used,
                    "candidate_cost_ms_seen": 0.0,
                    "candidate_cost_over_nominal": False,
                    "share_pred_err_mean": None, "share_pred_err_max": 0.0,
                    "share_pred_err_run_mean": None,
                    "share_pred_err_run_max": 0.0,
                    "share_pred_err_run_n": 0,
                    "single_source": self.single_source,
                    "ss_offered": 0, "ss_admissible": 0,
                    "ss_searched": 0,
                    "ss_selected_fc": 0, "ss_selected_bt": 0,
                    "ss_refusals": {}, "ss_admit_ms_max": 0.0,
                    "ss_admit_ticks_max": 0,
                    "share_step_guard_i_tot_a": SHARE_STEP_GUARD_I_TOT_A,
                    "share_step_guard_decisions": 0,
                    "share_step_refusals": {}}

        def _stats(xs):
            """min / median / max of a per-decision series."""
            if not xs:
                return None, None, None
            ys = sorted(xs)
            m = len(ys)
            return ys[0], (ys[m // 2] if m % 2
                           else 0.5 * (ys[m // 2 - 1] + ys[m // 2])), ys[-1]

        xs = sorted(self.solve_ms_all)
        n = len(xs)
        med = xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])
        b_lo, b_med, b_hi = _stats(self.budget_ms_all)
        l_lo, l_med, l_hi = _stats(self.ladder_points_all)
        return {"solve_ms_median": med, "solve_ms_max": xs[-1],
                # THE BUDGET ACTUALLY SPENT, per decision (2026-09-02).  With
                # the adaptive derivation the budget is no longer a constant of
                # the run, so a reader cannot recover it from the configuration
                # and the three figures are reported beside the expiry count
                # they explain.
                "budget_ms_min": b_lo, "budget_ms_median": b_med,
                "budget_ms_max": b_hi,
                "budget_adaptive": self.adaptive_budget,
                # THE SEARCH WIDTH, per decision.  `coarsened_decisions` counts
                # the decisions whose enumeration walked a proper subset of the
                # ladder so that the FULL enumeration of that subset fitted the
                # budget - the alternative being a cut search, which is biased
                # toward the incumbent rather than merely coarse.
                "ladder_points_min": l_lo, "ladder_points_median": l_med,
                "ladder_points_max": l_hi,
                "coarsened_decisions": self.coarsened_decisions,
                # M2: the decisions on which the floor, not the bound, set the
                # budget.  Nonzero means the callback total exceeded the 20 ms
                # command period on that many decisions.
                "budget_floor_binding": self.budget_floor_binding,
                # H1: the search width is projected on the NOMINAL and the
                # measurement is reported beside it.  `over_nominal` true means
                # this host is slower than the projection assumed, so a decision
                # the rule sized to fit may not have - visible, rather than
                # silently re-planned around.
                "candidate_cost_ms_nominal": self.candidate_cost_ms_used,
                "candidate_cost_ms_seen": self.candidate_cost_ms_seen,
                "candidate_cost_over_nominal": (
                    self.candidate_cost_ms_seen > self.candidate_cost_ms_used),
                "decisions": n, "budget_hits": self.budget_hits,
                # M6: the per-decision candidate count sits NEXT TO the expiry
                # counter, so a reader can tell a search that finished from one
                # that was cut - and, with `max_candidates` set, that the cut
                # was the deterministic one rather than the wall clock's.
                "cap_hits": self.cap_hits,
                "candidates_last": self.candidates_last,
                "candidates_min": self.candidates_min,
                "candidates_max": self.candidates_max,
                "rolls_published": self.rolls_published,
                "rolls_empty": self.rolls_empty,
                "roll_dropped_transitions": self.roll_dropped_transitions,
                "share_pred_err_mean": (
                    self.share_pred_err_sum / self.share_pred_err_n
                    if self.share_pred_err_n else None),
                "share_pred_err_max": self.share_pred_err_max,
                # THE SCORED-WINDOW PAIR (2026-09-03). The two above are
                # WHOLE-RUN and include the pre-Run decisions; these are
                # what `mpc_share_prediction` judges.
                "share_pred_err_run_mean": (
                    self.share_pred_err_run_sum / self.share_pred_err_run_n
                    if self.share_pred_err_run_n else None),
                "share_pred_err_run_max": self.share_pred_err_run_max,
                "share_pred_err_run_n": self.share_pred_err_run_n,
                # ── THE SINGLE-SOURCE CENSUS (2026-09-03) ──────────────────
                # Per DECISION.  `offered` is 2 per decision the feature was
                # armed for, `admissible` the rollout-time test's acceptances,
                # `selected_*` the committed commands, and `refusals` the reason
                # census - which is what says whether the feature was inert
                # because the plant refused it or because the economics did.
                "single_source": self.single_source,
                "ss_offered": self.ss_offered,
                "ss_admissible": self.ss_admissible,
                "ss_searched": self.ss_searched,
                "ss_selected_fc": self.ss_selected_fc,
                "ss_selected_bt": self.ss_selected_bt,
                "ss_refusals": dict(self.ss_refusals),
                "ss_admit_ms_max": self.ss_admit_ms_max,
                "ss_admit_ticks_max": self.ss_admit_ticks_max,
                # ── THE SHARE-STEP GUARD CENSUS (2026-09-03) ───────────────
                # The guard constant is reported BESIDE its counts so a sidecar
                # says which threshold the run was guarded at, not merely that
                # it was guarded.  `decisions` is the count the rule fired on,
                # `refusals` the reason census of the block-0 candidate columns
                # it removed.  Both are 0 on every registered stimulus: the
                # largest two-source total any of them commands is 1.4714 A,
                # 10.7 % under the guard.  A NONZERO value is the signal that a
                # new stimulus has entered the hazard's regime.
                "share_step_guard_i_tot_a": SHARE_STEP_GUARD_I_TOT_A,
                "share_step_guard_decisions": self.share_step_guard_decisions,
                "share_step_refusals": dict(self.share_step_refusals)}

    def summary_line(self):
        if not self.decisions:
            return None
        tm = self.timing()
        return ("[hil] " + self.name + ": %d decisions, solve %.2f ms median / "
                "%.2f ms max, %s candidates on the last decision (fewest %s, "
                "most %s, deterministic cap %s, cut by it on %d), budget "
                "%s %.2f / %.2f / %.2f ms min/median/max (floor bound the "
                "budget on %d - on those the callback total EXCEEDS the 20 ms "
                "command period), ladder %s/%s/%s "
                "points min/median/max (coarsened on %d; the width is projected "
                "on a NOMINAL %.4f ms per candidate and the largest measured "
                "was %.4f ms%s), expired on "
                "%d (%.1f %%) — an expiry returns "
                "the shifted incumbent, which is feasible and was validated one "
                "second earlier, so a nonzero count is a WARNING about the "
                "search depth and not about the command; incumbent retained on "
                "%d; roll table published %d times (%d completed jobs held no "
                "transition and were merged as no-ops, %d transitions dropped "
                "by the cap of %d); share prediction error IN THE RUN WINDOW "
                "%s mean / %.4f max over %d decisions, WHOLE RUN %s mean / "
                "%.4f max "
                "(predicted minus delivered STAGE-MEAN share, charge windows "
                "excluded — the claim this strategy makes, reported as a "
                "level. The WHOLE-RUN pair includes the pre-Run decisions, "
                "whose error is large and is scored by nothing; the RUN "
                "figures are what `mpc_share_prediction` judges); "
                "shadow governor %d ticks, %d MDAC "
                "corrections, %d current-derived corrections, %d mode "
                "mismatches; charge dwell latches %d, early drops %d%s; "
                "terminal price %s = %.6f g/SoC in the eta_fc %.2f proxy basis; "
                "preview %s%s"
                % (self.decisions, tm["solve_ms_median"], tm["solve_ms_max"],
                   tm["candidates_last"], tm["candidates_min"],
                   tm["candidates_max"],
                   ("none" if self.max_candidates is None
                    else "%d" % self.max_candidates), self.cap_hits,
                   ("adaptive" if self.adaptive_budget else "fixed"),
                   tm["budget_ms_min"], tm["budget_ms_median"],
                   tm["budget_ms_max"], tm["budget_floor_binding"],
                   tm["ladder_points_min"], tm["ladder_points_median"],
                   tm["ladder_points_max"], tm["coarsened_decisions"],
                   tm["candidate_cost_ms_nominal"],
                   tm["candidate_cost_ms_seen"],
                   (" - OVER the nominal, so this host is slower than the "
                    "projection assumed"
                    if tm["candidate_cost_over_nominal"] else ""),
                   self.budget_hits,
                   100.0 * self.budget_hits / self.decisions,
                   self.incumbent_retained,
                   tm["rolls_published"], tm["rolls_empty"],
                   tm["roll_dropped_transitions"], RollJob.MAX_TRANSITIONS,
                   ("n/a" if tm["share_pred_err_run_mean"] is None
                    else "%.4f" % tm["share_pred_err_run_mean"]),
                   tm["share_pred_err_run_max"],
                   tm["share_pred_err_run_n"],
                   ("n/a" if tm["share_pred_err_mean"] is None
                    else "%.4f" % tm["share_pred_err_mean"]),
                   self.share_pred_err_max,
                   self.shadow.ticks, self.shadow.mdac_corrections,
                   self.shadow.current_corrections, self.shadow.mode_mismatch,
                   self.latch.holds, self.latch.drops,
                   ("" if self.latch.drop_reason is None
                    else " (last: %s)" % self.latch.drop_reason),
                   self.terminal_price_mode,
                   terminal_price(self.terminal_price_mode), ETA_FC_PROXY,
                   # ASCII "(!)" deliberately (2026-09-02): the U+26A0 U+FE0F
                   # pair that used to sit here could not be encoded to the
                   # cp1252 console, so printing THIS LINE raised
                   # UnicodeEncodeError and killed ems-mpc, ems-mpc-cross and
                   # ems-ftp75-mpc after their runs were complete but before
                   # their sidecars were finalized. `mpc-sto`'s variant of the
                   # label had no such glyph and printed, which is why one of
                   # the four MPC legs passed. Keep summary/banner text ASCII.
                   ("the scenario profile - (!) PREVIEW, NOT CAUSAL"
                    if self.variant == "det" else "the demand TPM (causal)"),
                   ("" if self.variant != "sto" else
                    "; demand bin clamped HIGH on %d and LOW on %d"
                    % (self.clamped_bin_high, self.clamped_bin_low)))
                + self._ss_summary_fragment(tm)
                + self._share_step_summary_fragment(tm))

    def _ss_summary_fragment(self, tm):
        """The single-source census, appended to the summary line.

        EMPTY when the feature is off, so every pre-2026-09-03 line is
        unchanged character for character.  ASCII only - see the note on the
        cp1252 console above."""
        if not self.single_source:
            return ""
        reasons = tm["ss_refusals"]
        txt = ", ".join("%s %d" % (k, reasons[k]) for k in sorted(reasons))
        return ("; single-source 0/1 candidates ARMED: %d offered, %d admitted "
                "by the ROLLOUT-TIME cut-guard test (worst roll %d ticks / "
                "%.3f ms), committed %d times FC-only and %d times BT-only%s"
                % (tm["ss_offered"], tm["ss_admissible"],
                   tm["ss_admit_ticks_max"], tm["ss_admit_ms_max"],
                   tm["ss_selected_fc"], tm["ss_selected_bt"],
                   ("" if not txt else "; refusals by reason: " + txt)))

    def _share_step_summary_fragment(self, tm):
        """The share-step guard census, appended to the summary line.

        EMPTY when the guard never fired, which is every registered stimulus,
        so a line that carries it is itself the finding.  ASCII only."""
        if not tm["share_step_guard_decisions"]:
            return ""
        reasons = tm["share_step_refusals"]
        txt = ", ".join("%s %d" % (k, reasons[k]) for k in sorted(reasons))
        return ("; share-step guard FIRED on %d decisions at %.2f A of "
                "predicted two-source total (an upward share step was refused "
                "in the same decision as a rising demand step; last firing "
                "block-0 stage %s)%s"
                % (tm["share_step_guard_decisions"],
                   tm["share_step_guard_i_tot_a"],
                   self.share_step_guard_stage_last,
                   ("" if not txt else "; refused columns by reason: " + txt)))


def make_mpc(name="mpc-det", **kwargs):
    """Factory used by the registration step.  ``mpc-sto`` selects the variant."""
    variant = "sto" if name.endswith("sto") else "det"
    return MpcStrategy(name=name, variant=variant, **kwargs)
