#!/usr/bin/env python3
"""sdp_ems_solver.py - offline STOCHASTIC-DP EMS policy solver (baked lookup table).

+===========================================================================+
| CAUSAL, STATIONARY, INFINITE-HORIZON POLICY - NOT a foreknowledge table.  |
|                                                                           |
| Unlike tools/gen_dp_ems_table.py (a NON-CAUSAL, time-indexed setpoint     |
| table solved with perfect knowledge of one specific drive cycle), what    |
| this script produces is a STATE-FEEDBACK POLICY pi(SoC, demand_bin) ->    |
| (power_share_setpoint, charge_goal).  It is solved once, offline, against |
| a Markov model of the demand (the TPM), and is then implementable by a    |
| causal supervisor: read the SoC, classify the present demand into a bin,  |
| look the action up.  It is valid for ANY trajectory the TPM describes,    |
| not for one profile.                                                      |
|                                                                           |
| It is nevertheless SIM-ONLY, for the same reason `soc-band` is: the SoC   |
| axis of the state is plant truth in the simulator and is NOT part of the  |
| v4 telemetry a real Pi bridge sees.  A pack-voltage SoC estimator is the  |
| portable path and is future work.                                         |
+===========================================================================+

Provenance.  The STRUCTURE is ported from the PhD student's MATLAB FCHEV study
(references/EMS/SDP_EnergyManagement2.m, 155 lines): value iteration over a
(SoC grid x demand bin) state, a hydrogen stage cost, an SoC-deviation penalty,
a discount factor, and a transition-probability matrix over the demand bins.
Nothing NUMERIC transfers - the MATLAB is a 106 kW fuel cell against a 720 V /
100 Ah pack, and this is a bench rig whose whole demand span is under 3 W.

The TPM is consumed as delivered infrastructure:
    references/EMS/generated/TPM_dt1_hil.mat  (+ its .provenance.json sidecar)
built by tools/tpm_generator.py.  The matrix is UNITLESS: its bins partition
[0, 1] and it is invariant to affine rescaling of the demand axis.  THIS
SCRIPT owns the energy scaling — see D11 for WHICH map is in force and why the
sidecar's is no longer the default.

============================================================================
DECLARED PORT DECISIONS  (each states the MATLAB behaviour and why it moved)
============================================================================

D1. LINEAR INTERPOLATION of J over the SoC axis.  *The single most important
    correctness item in this file.*
    SDP_EnergyManagement2.m:50 snaps SOC_next to the nearest grid index
    (`[~, next_soc_idx] = min(abs(SOC_grid - SOC_next))`).  On the full-size
    vehicle one stage moves SoC by ~2.3e-4 against a 4e-4 grid spacing, so the
    quantization is merely coarse.  At THIS rig's power it is fatal: one 1 s
    stage moves SoC by ~7e-6 against a 1e-3 grid spacing, so EVERY transition
    - for every action - snaps back onto the state it started from.  SoC would
    be frozen, the action would have no consequence, the alpha term would
    become a constant offset, and the policy would collapse to pure hydrogen
    greed with no SoC feedback whatsoever.  Here the expected cost-to-go is
    LINEARLY INTERPOLATED at the continuous SOC_next (np.interp), exactly as
    tools/gen_dp_ems_table.py's D1 does, so the interpolated value carries the
    local slope dJ/dSoC and one stage's 7e-6 step is worth 7e-6 * dJ/dSoC.

D2. ALPHA IS RE-DERIVED, NOT CARRIED OVER.  See ALPHA_DERIVATION below and
    --alpha-mode.  The short version: the hydrogen term scales with absolute
    power, the alpha term does not, so alpha = 500 does not transfer.  The
    invariant that DOES transfer is the ratio of the two MARGINAL rates.

D3. SOC_next IS CLAMPED TO THE GRID, not made infeasible.
    SDP_EnergyManagement2.m:49 skips any action whose SOC_next leaves
    [0.55, 0.65].  At full-size power that is a live constraint; here a stage
    moves 7e-6 against a 0.1-wide window, so the test could only ever fire
    within 7e-6 of an edge and, being a hard skip, would leave the two edge
    states with min_cost = +inf and poison the value function through D1's
    interpolation.  The honest port at this scale is to CLAMP the transition
    to the window and let the alpha penalty - which is at its maximum exactly
    there - do the work of keeping the policy inside.

    KNOWN CONSEQUENCE AT THE GRID FLOOR, stated rather than papered over.  At
    the bottom SoC node every discharging action clamps to the SAME SOC_next
    (the node itself), so the SoC term is identical across the share ladder
    and the ranking falls to the hydrogen term alone: the actions TIE on
    everything the state can distinguish, and D8's ascending-ladder tie-break
    resolves to share = 0.0 - the MOST discharging command, i.e. an INVERSION
    of the policy the row above it carries.  It is one row of 101, at the far
    edge of the charge-sustaining window, and it is visible in the shipped
    artifact: row 0 of bin 24 reads 0.00 where rows 1..50 of that bin read
    1.00, so "share = 1.00 at every SoC node at or below the target" has this
    single boundary exception.  Changing the tie-break (e.g. resolving floor
    ties toward the LARGEST share) is a policy change and needs the operator;
    it is deliberately NOT made here.

D4. NEGATIVE-DEMAND (REGEN) BINS DO NOT SHARE.
    The MATLAB lets P_batt = P_dem - P_fc go negative, i.e. surplus demand
    recharges the pack through the same path it discharges it.  On THIS board
    it cannot: the INA253s see only the FORWARD current of the two boost
    regulators, and regen energy travels a separate path through the
    TL431/BSP170P chopper and the Ag105 charger (CLAUDE.md 2026-08-17b; the
    firmware's own share loop only apportions forward current).  So for a bin
    whose de-normalized centre power is negative this script sets
    P_fc = P_batt = 0: the share command is inert, SoC does not move on the
    traction path, and the ONLY way to capture that energy is the charge
    action.  Consequence, stated: in those bins every share action has an
    identical cost, the argmin is a tie, and the tie is broken toward the
    SMALLEST share (least hydrogen) by the ascending ladder ordering.

D5. THE ACTION SET IS THIS BOARD'S, AND CHARGING IS A SECOND, MASKED CONTROL.
    The MATLAB's control is a continuous 50-point P_fc grid.  The firmware's
    actual actuators are `power_share_setpoint` (a fraction, quantized here to
    a 21-step 0.05 ladder) and `charge_goal` (binary).  P_fc is therefore
    s * max(P_dem, 0) rather than a free variable, and charging is a discrete
    extra control worth `charge_i_ceiling_a` into the pack.
    OPERATOR RULING (b), 2026-08-30: FC-charge plus hard acceleration is
    infeasible by design.  Charging is therefore FORBIDDEN OUTRIGHT in the
    upper-tail demand bins - see CHARGE_FORBIDDEN below - and the constraint
    is baked into the artifact as `charge_forbidden_bins`, asserted before the
    file is written rather than left to the consumer.

D6. STAGE COST IS dt-SCALED ON BOTH TERMS.
    The MATLAB's stage cost is W_H2 + alpha*|dSoC| with an implicit dt = 1 s.
    Here both terms carry an explicit * dt, which makes the tuning
    dt-INVARIANT (the same discipline as gen_dp_ems_table.py's D5).  At this
    script's dt = 1.0 the two forms are numerically identical.

D7. CONVERGENCE TOLERANCE IS RE-SCALED, AND NON-CONVERGENCE REFUSES TO WRITE.
    The MATLAB's absolute 1e-3 is tuned against O(10) g costs; this rig's
    value function is O(1e-2) g, so 1e-3 would "converge" after a handful of
    sweeps with the policy still moving.  Default tolerance here is 1e-12 in
    the same units (see --tol), and the script REFUSES to emit an artifact
    that did not reach it (the MATLAB silently falls through its iteration
    cap).  The achieved sup-norm delta is recorded in the JSON either way.

D8. THE ARGMIN POLICY IS EXTRACTED ONCE, FROM THE CONVERGED J.
    SDP_EnergyManagement2.m:98-153 re-solves the whole minimisation inside its
    forward-simulation loop, duplicating :30-85 - two copies of one rule that
    can drift apart.  Here a single final greedy sweep produces the policy
    tables that get baked.

    TIE-BREAKING IS PART OF THE POLICY, so it is stated here rather than left
    to np.argmin's documentation: a tie resolves to the LOWEST control index,
    the share ladder is ascending and the charge control is last, so an
    indifferent state resolves to the smallest share and never to charging.
    TWO state classes are genuinely indifferent, and each is documented at its
    source: the negative-demand bins (D4 - no action moves SoC or burns
    hydrogen there, and least-hydrogen is the reading one wants) and the
    SoC-grid FLOOR row (D3 - the clamp makes SOC_next identical across the
    ladder, and there the same rule reads as an INVERSION).

D9. VECTORIZED EXPECTATION.  The MATLAB's innermost loop (:63-66) sums
    TPM(pd, :) * J(next_soc_idx, :) per action.  Because the SoC transition is
    DETERMINISTIC given (state, action) and the expectation is linear, the
    expected cost-to-go can be formed ONCE per sweep as EJ = J @ TPM.T - an
    (n_soc x n_bin) array whose column j is the expected cost-to-go as a
    function of SoC in bin j - and then interpolated per action.  Identical
    mathematics, ~4 orders of magnitude faster.

D10. THE CONVERGENCE BREAK IS TAKEN AFTER THE UPDATE, NOT BEFORE IT.
    SDP_EnergyManagement2.m:80-84 tests `max(abs(J_new - J)) < tolerance` and
    `break`s BEFORE reaching its `J = J_new` assignment on :84, so the J the
    MATLAB carries out of the loop is the sweep BEFORE the one that satisfied
    the tolerance.  Here J is updated unconditionally and the loop then breaks,
    so the returned J IS the sweep that met the tolerance.  Recorded as a
    deviation for completeness, not as a disagreement on design: the MATLAB's
    ordering reads as an unintentional off-by-one rather than an intent.  The
    effect is bounded by the tolerance itself - the two candidates differ by
    exactly the delta the test just found to be under it, i.e. under 1e-12 g
    here - and `solver.final_delta` is the delta of the sweep that was KEPT.

D11. THE DEMAND MAP IS THE CONSUMER'S, NOT THE SIDECAR'S  (2026-08-31,
    operator-ruled; this is what separates sdp_policy_v2.json from v1).
    The TPM's own sidecar carries an IDEAL-SCALING normalization block
    (p_dem_scaled_min_w -1.124773 W, p_dem_scaled_max_w +1.639842 W): the
    full-size cycles' demand span carried through the systemic-scaling ratio.
    v1 solved against it, and the ONLINE consumer (SdpStrategy in
    tools/hil_plant_sim.py) then measured this rig's ACTUAL bus power
    P_dem = V_bus*(I_fc + I_batt) at 0 .. 22.887 W - an ORDER OF MAGNITUDE
    above the modelled span.  Campaign hil_report_20260831_191509 measured the
    consequence: the normalized demand clamped to the top bin on ~98 % of
    decisions, the policy interior was never addressed, and `sdp-v1` emitted a
    single constant clamped share for the whole run.  The plumbing and the
    provenance were validated; the POLICY was not exercised.

    The unitless-TPM contract already anticipates this: the matrix describes
    TRANSITIONS between quantiles of a demand distribution and is invariant to
    an affine rescaling of the axis, so the CONSUMER owns the map from watts
    onto [0, 1].  The fix is therefore a re-map plus a re-solve of the SAME
    matrix, not a new TPM.

    DEMAND_MAP_DEFAULT_W = (0.0, 25.0) is the shipped map.  Derivation:
      * upper 25.0 W = the campaign's measured maximum 22.887 W (the ems-sdp
        and ems-soc-band CSVs' P_dem p95 is 22.876 W; the ems drive-cycle
        peaks at 14.758 W) plus ~9 % headroom, rounded to a round number so it
        reads as a DECLARED ENVELOPE rather than a fitted statistic.  A demand
        above it still clamps into bin 24 - the clamp is not removed, it is
        moved out to the edge of the measured envelope where it belongs.
      * lower 0.0 W because this rig's INA253s see only FORWARD boost current
        (D4): P_dem as the consumer computes it is >= 0 by construction, so a
        negative low edge would spend bins on a region no run can visit.  It
        also makes the regen-bin degeneracy of D4 unreachable rather than
        merely unlikely: with p_min = 0 no bin centre is negative.
    A DIFFERENT map is a DIFFERENT POLICY.  --demand-map re-states it
    explicitly and --demand-map-sidecar reproduces v1's mapping; whichever is
    used is recorded in the artifact under `normalization` (the map ACTUALLY
    USED, which is the block the consumer reads) with `demand_map_source`
    naming its provenance and `sidecar_p_dem_*_w` preserving the sidecar's own
    numbers beside it, so no field silently changes meaning between v1 and v2.

    WHAT DOES NOT MOVE: the TPM matrix, its bin edges, the dwell distribution
    behind `charge_forbidden_bins`' rule (a), gamma, and alpha - which is
    derived from the pack's coulombic energy (D2) and has no demand-axis term
    at all.  WHAT DOES: every watt-denominated quantity - the bin centres, the
    stage cost's P_fc and its hydrogen, the per-stage dSoC, and rule (b) of
    charge_forbidden_bins (the FC current budget), which is no longer
    vacuous at 25 W the way it was at 1.64 W.

============================================================================
WHAT THIS MODEL DOES NOT CONTAIN
============================================================================
  * A pack OCV(SoC) curve.  V_pack is a fixed 7.4 V nominal (2S).  The
    MATLAB's own Em = 720 V is likewise fixed, and gen_dp_ems_table.py's D6
    measured the full nonlinear pack against this reduction at ~0.5 % on the
    pack current.  TODO(calibrate).
  * The pack capacity is BATT_CAPACITY_AH = 5.0 Ah, which hil_electrical.py
    itself marks `plausible 2S RC pack  TODO(verify)`.  That caveat is carried
    into the artifact's `battery.caveat` field and is NOT laundered away here.
  * The Ag105's settle time, CV taper and MPPT threshold.  A charge stage is
    worth a flat `charge_i_ceiling_a` into the pack.
  * Boost efficiency.  P_fc is a BUS-SIDE power; the stack-side draw is
    larger by 1/ETA_BOOST.  Omitting it scales the hydrogen term by a constant
    and therefore does not change the ARGMIN at any state (the alpha term is
    re-derived against the same convention - see ALPHA_DERIVATION).

    THE COMPARISON THIS FORECLOSES, stated explicitly so nobody attempts it:
    this solver's J is built on BUS-side P_fc, while the online consumer's
    `h2_sdp_cum_g` column integrates STACK-side P_fc.  The two bases differ by
    ~1/ETA_BOOST, and on top of that this solver uses the student's static
    eta_fc = 0.5 proxy where the simulator uses the Gfc map (a further
    +16.4 %).  A J value is therefore NOT a prediction of, and must never be
    differenced against, a logged hydrogen total.  THIS ARTIFACT SHIPS A
    POLICY, NOT A HYDROGEN PREDICTION; hydrogen comparisons belong between two
    RUNS measured on the same column, at matched terminal SoC.

Usage:
    # regenerate the SHIPPED artifact (tools/sdp_policies/sdp_policy_v2.json,
    # demand map 0..25 W - D11):
    C:/Users/ricky/miniforge3/python.exe tools/sdp_ems_solver.py --force
    # reproduce the v1 mapping (ideal-scaling span from the TPM sidecar):
    C:/Users/ricky/miniforge3/python.exe tools/sdp_ems_solver.py \
        --demand-map-sidecar --out tools/sdp_policies/sdp_policy_v1.json --force

Requires numpy + scipy (miniforge).  `.venv_hil` is stdlib-only - it is the
SIMULATOR's interpreter, not this one.  This script is OFFLINE tooling:
nothing in the 1 kHz simulator loop imports it.
"""

import argparse
import datetime
import hashlib
import json
import os
import sys

import numpy as np
from scipy.io import loadmat

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
REPO_ROOT = os.path.dirname(_HERE)

from tpm_generator import rescale_gamma                              # noqa: E402


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
DEFAULT_TPM = os.path.join(REPO_ROOT, "references", "EMS", "generated",
                           "TPM_dt1_hil.mat")
DEFAULT_OUT = os.path.join(_HERE, "sdp_policies", "sdp_policy_v2.json")
# The SCHEMA is the FILE FORMAT contract between this script and
# hil_plant_sim.py's load_sdp_policy(); it is NOT the artifact's version.  v2
# changes the demand MAP (D11), not the shape of the document, so the schema
# stays `sdp-policy-v1` and the existing consumer parses both files unchanged.
SCHEMA = "sdp-policy-v1"

# ── THE DEMAND MAP (D11).  Watts -> the normalized [0, 1] TPM bin axis. ──────
# The SHIPPED map, measured against campaign hil_report_20260831_191509 (see
# D11 for the full derivation and for what the sidecar's own block is).
DEMAND_MAP_DEFAULT_W = (0.0, 25.0)
DEMAND_MAP_DEFAULT_SOURCE = (
    "consumer demand map, campaign 20260831_191509 measured P_dem 0-22.887 W "
    "(V_bus*(I_fc+I_batt) on the ems-sdp / ems-soc-band CSVs; p95 22.876 W, "
    "drive-cycle peaks 14.758 W) + ~9 % headroom, rounded to 25.0 W")


# ---------------------------------------------------------------------------
# Constants this script owns.
#
# NOTHING is imported from tools/hil_plant_sim.py or tools/hil_electrical.py.
# That is deliberate: the ONLINE consumer of this artifact lives in
# hil_plant_sim.py, and an offline solver that imports its own consumer
# couples the two in the wrong direction (and makes this script unrunnable
# while that file is mid-edit).  Every value below is restated WITH its
# citation, and any drift shows up as a citation that no longer matches.
# ---------------------------------------------------------------------------

# 2S pack, hil_electrical.py:491-492.  The capacity is marked TODO(verify)
# THERE and stays marked here.
BATT_CELLS = 2
BATT_CAPACITY_AH = 5.0
# 2S nominal terminal voltage.  D6 of gen_dp_ems_table.py models the full
# 9-point LIPO_OCV curve; this solver uses the flat nominal because the policy
# is solved over a 0.55-0.65 SoC window across which that curve moves ~2 %.
V_PACK_NOMINAL_V = 7.4

# Measured no-load bus intercept, hil_plant_sim.py:249 (V_BUS_DROOP_V0 15.95).
# Used ONLY to convert the Ag105's charge CURRENT into the bus POWER the fuel
# cell must supply for it (the `physical` charger accounting, D11 of
# gen_dp_ems_table.py).  The droop term is not modelled: at this demand scale
# it moves the bus by under 0.2 V.
V_BUS_NOMINAL_V = 15.95

# .ino LIMIT_I_FC_MAX - the fuel-cell channel overcurrent limit the firmware
# faults on.  Not exposed as a Python constant anywhere in tools/, so it is
# restated with its citation (same treatment as gen_dp_ems_table.py:241).
LIMIT_I_FC_MAX_A = 1.4
# Headroom kept on that limit when admitting a charge bin, mirroring
# gen_dp_ems_table.py's DP_CHARGE_FC_MARGIN and its rationale: with
# FC_CHARGE_ENABLE open, assertFcChargeEnable() (.ino:10046) has dropped BT off
# the bus, so the FC channel alone carries the load PLUS the charger.
CHARGE_FC_MARGIN = 0.85

# The Ag105 charge-current ceiling.  0.8 A is the `ems-soc-band` scenario's
# own `chg_i_ceiling_a` (CLAUDE.md 2026-08-31d).
CHARGE_I_CEILING_A = 0.8

# Student's static hydrogen proxy, SDP_EnergyManagement2.m:12-13.  Kept
# VERBATIM so the ported objective is the student's; see the `h2.note` field
# for the discrepancy against the simulator's own Gfc map.
ETA_FC = 0.5
Q_LHV_J_PER_G = 120000.0

# SoC grid and target, SDP_EnergyManagement2.m:4 and :56.  The window transfers
# unchanged (it is a dimensionless charge-sustaining band, not a vehicle
# number); the point count does not need to - 101 points at 1e-3 spacing is
# ample under D1's interpolation, where the grid only has to resolve the SHAPE
# of J, not one stage's step.
SOC_TARGET = 0.6
SOC_GRID_MIN = 0.55
SOC_GRID_MAX = 0.65
SOC_GRID_N = 101

# Share ladder (D5).  21 steps of 0.05 spanning the full [0, 1] command range.
# NOTE, and it is the consumer's business not the solver's: the firmware's
# updateShareSetpointCutoff() (.ino:9377-9385) drives a channel's *_BUS_ENABLE
# LOW for a setpoint outside [DROOP_R_MIN 0.15, DROOP_R_MAX 0.85].  The ladder
# deliberately SPANS that band rather than stopping short of it, because this
# is a general-purpose policy artifact and clipping the action set would hide
# the optimizer's actual preference.  A consumer that must not trip the latch
# clips the commanded value; the JSON records the full ladder either way.
SHARE_LADDER_N = 21

# Discount factor, SDP_EnergyManagement2.m:11, tuned per 1 s step.
GAMMA_BASE = 0.95
DECISION_DT_S = 1.0

# Value-iteration budget (D7).
TOL_DEFAULT = 1.0e-12
MAX_ITER_DEFAULT = 5000

# Charge admission (D5 / operator ruling (b)).  Charging is admitted only in
# the demand bins that make up the lower CHARGE_QUANTILE of the TPM's OBSERVED
# DWELL (the sidecar's `results.row_occupancy`) - the idle/cruise mass - and is
# forbidden in the upper-tail bins, which are the acceleration transients.
# 0.90 is chosen against this TPM's own occupancy histogram: bins 0..10 carry
# 85.0 % of the samples (bin 10, the idle bin, alone carries 75.5 %) and bin 11
# takes the cumulative to 91.3 %, so the cut lands immediately above the
# cruise/idle mass and forbids the 8.7 % acceleration tail.  Using the dwell
# distribution rather than a hand-picked power threshold means a regenerated
# TPM moves the cut with the data.
CHARGE_QUANTILE = 0.90

# Full-size reference numbers, used ONLY by the alpha derivation below.
# SDP_EnergyManagement2.m:8-10, :16.
FULL_SIZE_ALPHA = 500.0
FULL_SIZE_EM_V = 720.0
FULL_SIZE_Q_AH = 100.0
FULL_SIZE_P_DEM_MAX_W = 60000.0
FULL_SIZE_P_DEM_MIN_W = -50000.0


ALPHA_DERIVATION = """\
alpha does not transfer verbatim.  The stage cost is

    stage(s) = W_H2 + alpha * |SOC_next - SOC_target|,   W_H2 = P_fc/(eta*Q_LHV)

and its two terms scale DIFFERENTLY with the size of the powertrain: W_H2 is
proportional to absolute power, while |SOC deviation| is dimensionless and does
not scale at all.  The full-size study's alpha = 500 is balanced against a
106 kW fuel cell; used unchanged against a demand span of -1.125 .. +1.640 W it
out-weighs the hydrogen term by ~6 orders of magnitude AT THE DEMAND MAXIMUM
(and by more as the demand falls toward the idle bin, where the hydrogen term
goes to zero and the ratio is unbounded), so the policy would be pure SoC
regulation with no hydrogen content anywhere.

What must be preserved is not either term's LEVEL but the ratio of the two
MARGINAL rates - the exchange rate the optimizer actually trades on:

    d(W_H2)/d(P_fc)          = 1 / (eta_fc * Q_LHV)          [g/s per W]
    d(alpha*|dSOC|)/d(P_bt)  = alpha / (V_pack * 3600 * Q_Ah) [1/s per W]

eta_fc and Q_LHV are unchanged by the port, so holding the ratio fixed gives

    alpha_scaled = alpha_full * (V_pack_scaled * Q_Ah_scaled)
                              / (Em_full       * Q_Ah_full)
                 = 500 * (7.4 * 5.0) / (720.0 * 100.0)
                 = 0.2569444444444444

i.e. alpha scales with the pack's COULOMBIC ENERGY (V * A*s), which is exactly
the quantity that converts a watt of battery power into a rate of SoC change.
Because eta_fc, Q_LHV and gamma are all unchanged, this makes the whole
decision problem structurally identical to the full-size one in the
(SoC, normalized demand) coordinates the TPM already works in - which is the
correct meaning of "port the structure, not the numbers".

ALPHA IS INVARIANT TO THE DEMAND MAP (D11).  The marginal derivation above has
no demand-axis term - only the pack's coulombic energy - so re-mapping watts
onto the bin axis does NOT move alpha, and the shipped value is the same
0.2569444444444444 in sdp_policy_v1.json and sdp_policy_v2.json.  The rejected
`level` mode below IS map-dependent (it divides by the map's own maximum), and
the numbers quoted for it are the SIDECAR map's; under the shipped 25.0 W map
it recomputes to 500*25/60000 = 0.20833, which is a different number for the
same rejected reason.  The paragraph is kept as written because it is a record
of the derivation, not of a shipped value.

REJECTED ALTERNATIVE (measured, --alpha-mode level; figures below are for the
SIDECAR map, see the note above): scaling alpha by the POWER-SPAN ratio
instead,

    alpha_level = 500 * (p_dem_max_scaled / P_dem_max_full)
                = 500 * 1.639842192501809 / 60000 = 0.013665

preserves the two terms' relative LEVELS but not their marginal rates.  The
reproducible figure for the gap between the two derivations is their ratio,

    alpha_marginal / alpha_level = 0.2569444444 / 0.0136653516 = 18.803

which is equivalently the ratio of the two systems' PER-STAGE SoC swings when
each is worked at its OWN maximum demand: the full-size vehicle moves 18.8x
more SoC per stage at 60 kW than this rig does at 1.64 W, while the hydrogen
cost per joule of fuel-cell output is identical between them.  Scaling alpha by
the power span alone therefore under-weights the SoC axis by that factor.
Under it the hydrogen term dominates the discounted comparison by
~8x at every state and the solved policy COLLAPSES to share = 0.0 in every
cell with charge_goal never asserted - pure hydrogen greed with the SoC axis
inert.  That degeneracy is the reason the marginal-rate derivation is the
default; --alpha-mode level reproduces it for inspection.

Note on the boost efficiency: P_fc here is a BUS-SIDE power, so both marginal
rates above are referred to the bus.  Referring both to the stack instead
multiplies the hydrogen rate by 1/ETA_BOOST and leaves the SoC rate alone,
which WOULD move the balance - but it moves it identically at full size, where
the same reduction is made, so the ported ratio is unaffected.  What the
omission does cost is that J is not a hydrogen PREDICTION; this artifact ships
a policy, not a gram figure."""


# ---------------------------------------------------------------------------
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_tpm(path):
    """The 25x25 row-stochastic matrix, validated."""
    d = loadmat(path)
    keys = [k for k in d if not k.startswith("__")]
    if "TPM" not in d:
        raise SystemExit("%s: no 'TPM' variable (found %s)" % (path, keys))
    tpm = np.asarray(d["TPM"], dtype=np.float64)
    if tpm.ndim != 2 or tpm.shape[0] != tpm.shape[1]:
        raise SystemExit("%s: TPM is %s, expected a square matrix"
                         % (path, tpm.shape))
    rows = tpm.sum(axis=1)
    if not np.allclose(rows, 1.0, atol=1e-9):
        raise SystemExit("%s: TPM is not row-stochastic (row sums %.12g .. "
                         "%.12g)" % (path, rows.min(), rows.max()))
    if (tpm < -1e-15).any():
        raise SystemExit("%s: TPM has negative entries" % path)
    return tpm


def load_sidecar(tpm_path):
    """The .provenance.json sidecar - the source of the ENERGY SCALING.

    Read at solve time, never hardcoded: the matrix is unitless and the
    normalization block is the only thing that ties it to watts."""
    path = tpm_path + ".provenance.json"
    if not os.path.isfile(path):
        raise SystemExit(
            "missing sidecar %s.\nThe TPM is UNITLESS - without the sidecar's "
            "normalization block there is no way to map a bin onto watts, and "
            "hardcoding one would silently outlive the matrix it belongs to."
            % path)
    with open(path, "r", encoding="utf-8") as f:
        side = json.load(f)
    for key in ("normalization", "bins"):
        if key not in side:
            raise SystemExit("%s: sidecar has no %r block" % (path, key))
    norm = side["normalization"]
    for key in ("p_dem_scaled_min_w", "p_dem_scaled_max_w"):
        if key not in norm:
            raise SystemExit("%s: sidecar normalization has no %r" % (path, key))
    return path, side


# ---------------------------------------------------------------------------
# Charge admission (D5, operator ruling (b))
# ---------------------------------------------------------------------------
def charge_forbidden_bins(side, p_centers, quantile, chg_a):
    """0-based bin indices in which the policy may NEVER assert charge_goal.

    TWO independent rules, unioned:

      (a) DWELL TAIL.  Bins above the `quantile` point of the TPM's observed
          row occupancy are the acceleration transients; operator ruling (b)
          (2026-08-30) forbids FC-charge there by design.
      (b) FC CURRENT BUDGET.  With FC_CHARGE_ENABLE open the FC channel alone
          carries the load plus the charger's draw.  Any bin where
              P_dem/V_bus + chg_a > CHARGE_FC_MARGIN * LIMIT_I_FC_MAX_A
          is forbidden regardless of dwell.

    Rule (b) is belt-and-braces at this demand scale (the whole span is under
    2 W, i.e. ~0.1 A of bus current) and is expected to select nothing; it is
    present so that a TPM regenerated against a larger energy scale cannot
    silently produce a policy that commands an overcurrent.
    """
    n = len(p_centers)
    occ = side.get("results", {}).get("row_occupancy")
    if occ is None or len(occ) != n:
        raise SystemExit(
            "sidecar has no usable results.row_occupancy (%r) - the charge "
            "admission cut is derived from the observed dwell distribution "
            "and refuses to fall back on a hand-picked threshold"
            % (None if occ is None else len(occ)))
    occ = np.asarray(occ, dtype=np.float64)
    total = occ.sum()
    if total <= 0:
        raise SystemExit("sidecar row_occupancy sums to zero")
    cum = np.cumsum(occ) / total
    # The cut bin is the FIRST whose cumulative dwell reaches `quantile`; it
    # and everything below it are admitted, everything above is forbidden.
    cut = int(np.argmax(cum >= quantile))
    forbid_dwell = np.zeros(n, dtype=bool)
    forbid_dwell[cut + 1:] = True

    i_fc = np.maximum(p_centers, 0.0) / V_BUS_NOMINAL_V + chg_a
    forbid_budget = i_fc > CHARGE_FC_MARGIN * LIMIT_I_FC_MAX_A

    forbid = forbid_dwell | forbid_budget
    return (sorted(int(i) for i in np.nonzero(forbid)[0]),
            {"cut_bin": cut,
             "cum_dwell_at_cut": float(cum[cut]),
             "n_forbidden_by_dwell": int(forbid_dwell.sum()),
             "n_forbidden_by_fc_budget": int(forbid_budget.sum())})


# ---------------------------------------------------------------------------
# The solver
# ---------------------------------------------------------------------------
def build_stage(p_centers, shares, soc_grid, alpha, dt, cap_as, chg_a,
                chg_allowed, soc_target, soc_lo, soc_hi):
    """Per-bin (stage_cost, soc_next, feasible) arrays.

    Returned shapes are (n_bin, n_soc, n_ctrl) with n_ctrl = len(shares) + 1;
    control index len(shares) is the CHARGE action.  Everything here is
    stationary, so it is built once and reused by every value-iteration sweep.
    """
    n_bin = len(p_centers)
    n_soc = len(soc_grid)
    m = len(shares)
    n_ctrl = m + 1

    soc_next = np.empty((n_bin, n_soc, n_ctrl))
    stage = np.empty((n_bin, n_soc, n_ctrl))
    feas = np.ones((n_bin, n_soc, n_ctrl), dtype=bool)

    for j, p in enumerate(p_centers):
        # D4: regen bins put nothing through the share path.
        p_pos = max(float(p), 0.0)
        p_fc = shares * p_pos                                    # (m,)
        p_bt = p_pos - p_fc
        i_batt = p_bt / V_PACK_NOMINAL_V                         # + = discharge
        d_soc = -i_batt * dt / cap_as                            # (m,)
        soc_next[j, :, :m] = soc_grid[:, None] + d_soc[None, :]
        h2 = p_fc / (ETA_FC * Q_LHV_J_PER_G) * dt                # (m,) grams
        stage[j, :, :m] = h2[None, :]

        # Charge control.  `physical` accounting (D11 of gen_dp_ems_table.py):
        # the fuel cell is billed for the charger's bus draw on top of the
        # traction demand, because that is what the hi-fi plant stamps on the
        # bus node and what the hardware actually does.
        soc_next[j, :, m] = soc_grid + chg_a * dt / cap_as
        p_fc_chg = p_pos + V_BUS_NOMINAL_V * chg_a
        stage[j, :, m] = p_fc_chg / (ETA_FC * Q_LHV_J_PER_G) * dt
        feas[j, :, m] = bool(chg_allowed[j])

        # FC channel overcurrent, control-wise.  Cannot bind at this demand
        # scale; present so a rescaled TPM cannot produce an illegal policy.
        feas[j, :, :m] &= ((p_fc / V_BUS_NOMINAL_V) <= LIMIT_I_FC_MAX_A)[None, :]

    # D3: clamp rather than forbid.
    np.clip(soc_next, soc_lo, soc_hi, out=soc_next)
    stage += alpha * np.abs(soc_next - soc_target) * dt
    stage = np.where(feas, stage, np.inf)
    return stage, soc_next, feas


def value_iterate(stage, soc_next, soc_grid, tpm, gamma, tol, max_iter):
    """Infinite-horizon value iteration.  Returns (J, iters, final_delta).

    D9: the expectation over the next demand bin is formed ONCE per sweep as
    EJ = J @ TPM.T, because the SoC transition is deterministic given the
    state and action and the expectation is linear.  EJ[:, j] is then the
    expected cost-to-go as a function of SoC in bin j, and D1's interpolation
    is applied to it.
    """
    n_bin, n_soc, n_ctrl = stage.shape
    J = np.zeros((n_soc, n_bin))
    delta = float("inf")
    it = 0
    for it in range(1, max_iter + 1):
        EJ = J @ tpm.T                                    # (n_soc, n_bin)
        J_new = np.empty_like(J)
        for j in range(n_bin):
            fut = np.interp(soc_next[j].ravel(), soc_grid,
                            EJ[:, j]).reshape(n_soc, n_ctrl)
            J_new[:, j] = np.min(stage[j] + gamma * fut, axis=1)
        delta = float(np.max(np.abs(J_new - J)))
        # D10: the update is applied BEFORE the break, so the J returned is the
        # sweep that met the tolerance.  SDP_EnergyManagement2.m:80-84 breaks
        # first and keeps the sweep before it; the two differ by `delta`, which
        # the test has just bounded by `tol`.
        J = J_new
        if delta < tol:
            break
    return J, it, delta


def greedy_policy(J, stage, soc_next, soc_grid, tpm, gamma):
    """One final argmin sweep against the converged J (D8).

    Ties are broken toward the LOWEST control index.  The share ladder is
    ascending and the charge control is last, so a tie resolves to the
    smallest share and never to charging.  TWO state classes tie, and the same
    rule reads differently in each:
      * the negative-demand bins (D4) - no action moves SoC or burns hydrogen,
        so smallest-share is the least-hydrogen reading and is what one wants;
      * the SoC-grid FLOOR row (D3) - the clamp makes SOC_next identical across
        the ladder, so smallest-share resolves to the MOST discharging command,
        an inversion of the row above it.  Left as-is deliberately: changing
        the tie-break is a policy change and needs the operator.
    """
    n_bin, n_soc, n_ctrl = stage.shape
    EJ = J @ tpm.T
    idx = np.empty((n_soc, n_bin), dtype=np.int64)
    for j in range(n_bin):
        fut = np.interp(soc_next[j].ravel(), soc_grid,
                        EJ[:, j]).reshape(n_soc, n_ctrl)
        idx[:, j] = np.argmin(stage[j] + gamma * fut, axis=1)
    return idx


# ---------------------------------------------------------------------------
def render_policy_json(args, meta):
    """The artifact, as an ordered dict matching the schema contract."""
    return {
        "schema": SCHEMA,
        "generated_utc": meta["generated_utc"],
        "tool": "tools/sdp_ems_solver.py",
        "argv": meta["argv"],
        "causal": True,
        "sim_only": True,
        "tpm": meta["tpm"],
        "normalization": meta["normalization"],
        "demand_bins": meta["demand_bins"],
        "decision_dt_s": float(args.dt),
        "gamma": meta["gamma"],
        "alpha": meta["alpha"],
        "soc": meta["soc"],
        "actions": meta["actions"],
        "battery": {
            "capacity_ah": float(args.capacity_ah),
            "cells": BATT_CELLS,
            "v_pack_nominal": V_PACK_NOMINAL_V,
            "caveat": "capacity TODO(verify) - hil_electrical.py:492 marks "
                      "BATT_CAPACITY_AH 5.0 Ah a plausible 2S RC pack, not a "
                      "measured value; v_pack_nominal is a flat 2S nominal, "
                      "not the OCV(SoC) curve",
        },
        "h2": {
            "eta_fc": ETA_FC,
            "q_lhv_j_per_g": Q_LHV_J_PER_G,
            "note": "student's static proxy (SDP_EnergyManagement2.m:12-13), "
                    "ported verbatim; the sim's Gfc DC gain implies eta 47.25% "
                    "(+16.4% on the same power), so J values here are NOT "
                    "comparable to a run's h2_cum_g - this artifact ships a "
                    "policy, not a hydrogen prediction. TODO(calibrate)",
        },
        "solver": meta["solver"],
        "policy": meta["policy"],
    }


def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Solve the stochastic-DP EMS policy and bake it as a "
                    "sdp-policy-v1 JSON lookup table.")
    ap.add_argument("--tpm", default=DEFAULT_TPM,
                    help="TPM .mat (default references/EMS/generated/"
                         "TPM_dt1_hil.mat; its .provenance.json sidecar must "
                         "sit beside it)")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="output path (default tools/sdp_policies/"
                         "sdp_policy_v2.json — the SHIPPED artifact)")
    ap.add_argument("--demand-map", nargs=2, type=float, default=None,
                    metavar=("MIN_W", "MAX_W"),
                    help="the map from bus watts onto the TPM's normalized "
                         "[0, 1] demand axis (default %g %g — see D11). A "
                         "DIFFERENT MAP IS A DIFFERENT POLICY."
                         % DEMAND_MAP_DEFAULT_W)
    ap.add_argument("--demand-map-sidecar", action="store_true",
                    help="use the TPM sidecar's own normalization block "
                         "(p_dem_scaled_min_w/max_w) as the demand map "
                         "instead of the default. This is the IDEAL-SCALING "
                         "span sdp_policy_v1.json was solved against; on this "
                         "rig it clamps ~98 %% of decisions into the top bin "
                         "(D11), so it is kept for reproduction only.")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing artifact (refused otherwise)")
    ap.add_argument("--dt", type=float, default=DECISION_DT_S,
                    help="decision step in s (default %g; MUST match the TPM's "
                         "own dt - a TPM built at another step describes "
                         "different transitions)" % DECISION_DT_S)
    ap.add_argument("--gamma-base", type=float, default=GAMMA_BASE,
                    help="discount per 1 s step (default %g); rescaled to --dt "
                         "by tpm_generator.rescale_gamma()" % GAMMA_BASE)
    ap.add_argument("--alpha", type=float, default=None,
                    help="explicit SoC-deviation weight, overriding "
                         "--alpha-mode (see the ALPHA_DERIVATION note)")
    ap.add_argument("--alpha-mode", default="marginal",
                    choices=["marginal", "level"],
                    help="how alpha is re-derived from the full-size 500 "
                         "(default marginal). 'level' reproduces the REJECTED "
                         "power-span scaling, which collapses the policy to "
                         "pure hydrogen greed - kept for inspection only.")
    ap.add_argument("--soc-n", type=int, default=SOC_GRID_N,
                    help="SoC grid points (default %d)" % SOC_GRID_N)
    ap.add_argument("--soc-min", type=float, default=SOC_GRID_MIN)
    ap.add_argument("--soc-max", type=float, default=SOC_GRID_MAX)
    ap.add_argument("--soc-target", type=float, default=SOC_TARGET)
    ap.add_argument("--share-n", type=int, default=SHARE_LADDER_N,
                    help="share ladder points over [0, 1] (default %d = a 0.05 "
                         "ladder)" % SHARE_LADDER_N)
    ap.add_argument("--capacity-ah", type=float, default=BATT_CAPACITY_AH,
                    help="pack capacity in Ah (default %g, TODO(verify))"
                         % BATT_CAPACITY_AH)
    ap.add_argument("--charge-i-ceiling", type=float,
                    default=CHARGE_I_CEILING_A,
                    help="Ag105 charge current in A (default %g)"
                         % CHARGE_I_CEILING_A)
    ap.add_argument("--charge-quantile", type=float, default=CHARGE_QUANTILE,
                    help="dwell quantile above which charging is forbidden "
                         "(default %g; operator ruling (b))" % CHARGE_QUANTILE)
    ap.add_argument("--tol", type=float, default=TOL_DEFAULT,
                    help="value-iteration sup-norm tolerance (default %g; the "
                         "MATLAB's 1e-3 is tuned to O(10) costs and this rig's "
                         "J is O(1e-2))" % TOL_DEFAULT)
    ap.add_argument("--max-iter", type=int, default=MAX_ITER_DEFAULT,
                    help="iteration cap (default %d); NOT converging refuses "
                         "to write" % MAX_ITER_DEFAULT)
    ap.add_argument("--dry-run", action="store_true",
                    help="solve and report, write nothing")
    args = ap.parse_args(argv)

    if args.dt <= 0 or args.capacity_ah <= 0 or args.charge_i_ceiling < 0:
        ap.error("--dt and --capacity-ah must be > 0, --charge-i-ceiling >= 0")
    if args.soc_n < 2 or args.share_n < 2:
        ap.error("--soc-n and --share-n must be >= 2")
    if not (args.soc_min < args.soc_target < args.soc_max):
        ap.error("--soc-target must lie strictly inside [--soc-min, --soc-max]")
    if not 0.0 < args.charge_quantile <= 1.0:
        ap.error("--charge-quantile must be in (0, 1]")
    if args.demand_map is not None and args.demand_map_sidecar:
        ap.error("--demand-map and --demand-map-sidecar are mutually exclusive "
                 "- they are two ways of answering the same question")
    if args.demand_map is not None and not args.demand_map[1] > args.demand_map[0]:
        ap.error("--demand-map MAX_W must exceed MIN_W")

    tpm_path = os.path.abspath(args.tpm)
    if not os.path.isfile(tpm_path):
        ap.error("TPM not found: %s" % tpm_path)
    tpm = load_tpm(tpm_path)
    sidecar_path, side = load_sidecar(tpm_path)
    n_bin = tpm.shape[0]

    # ── energy scaling: THE DEMAND MAP (D11) ────────────────────────────────
    # The sidecar's block is ALWAYS read - it is validated, reported, and
    # recorded beside the map actually used - but it is no longer the default
    # source of the map. See D11.
    side_min = float(side["normalization"]["p_dem_scaled_min_w"])
    side_max = float(side["normalization"]["p_dem_scaled_max_w"])
    if not side_max > side_min:
        ap.error("sidecar normalization is degenerate (min %r >= max %r)"
                 % (side_min, side_max))
    if args.demand_map_sidecar:
        p_min, p_max = side_min, side_max
        map_source = ("TPM sidecar normalization block "
                      "(p_dem_scaled_min_w/max_w) - the IDEAL-SCALING span; "
                      "--demand-map-sidecar, reproduces sdp_policy_v1.json's "
                      "mapping")
    elif args.demand_map is not None:
        p_min, p_max = float(args.demand_map[0]), float(args.demand_map[1])
        map_source = "explicit --demand-map %.9g %.9g" % (p_min, p_max)
    else:
        p_min, p_max = DEMAND_MAP_DEFAULT_W
        map_source = DEMAND_MAP_DEFAULT_SOURCE
    n_declared = side["bins"].get("n_bins")
    if n_declared is not None and int(n_declared) != n_bin:
        ap.error("sidecar declares %d bins but the matrix is %dx%d"
                 % (int(n_declared), n_bin, n_bin))
    edges = np.linspace(0.0, 1.0, n_bin + 1)
    centers_norm = 0.5 * (edges[:-1] + edges[1:])
    # Bin -> watts.  The CENTRE is used as the bin's representative demand:
    # the bins are uniform in the normalized coordinate, so the centre is the
    # midpoint of the interval the online consumer will map onto this row.
    p_centers = p_min + centers_norm * (p_max - p_min)

    # ── gamma ────────────────────────────────────────────────────────────────
    # dt_base is passed as a LITERAL 1.0 rather than read from the sidecar's
    # `gamma_rescaling.dt_base_s`, and the asymmetry with the normalization
    # block above is intentional.  The normalization is per-TPM DATA - it
    # changes whenever the matrix is rebuilt against different cycles, so
    # hardcoding it would silently outlive the matrix.  dt_base is not data
    # about this TPM at all: it is the step the STUDENT'S gamma = 0.95 was
    # tuned at (SDP_EnergyManagement2.m:11), a fixed property of the source
    # this script ports, and it stays 1.0 whatever TPM is loaded.  The sidecar
    # merely restates it as documentation.  --gamma-base is the knob for
    # retuning; there is deliberately no --gamma-dt-base.
    gamma = rescale_gamma(args.gamma_base, args.dt, 1.0)

    # ── alpha (D2) ───────────────────────────────────────────────────────────
    alpha_marginal = FULL_SIZE_ALPHA * (V_PACK_NOMINAL_V * args.capacity_ah) \
        / (FULL_SIZE_EM_V * FULL_SIZE_Q_AH)
    alpha_level = FULL_SIZE_ALPHA * p_max / FULL_SIZE_P_DEM_MAX_W
    if args.alpha is not None:
        alpha = float(args.alpha)
        alpha_rationale = ("EXPLICIT --alpha %r, overriding the derivation "
                           "below.\n\n%s" % (alpha, ALPHA_DERIVATION))
    elif args.alpha_mode == "level":
        alpha = alpha_level
        alpha_rationale = ("--alpha-mode level: the REJECTED power-span "
                           "scaling, present for inspection.\n\n%s"
                           % ALPHA_DERIVATION)
    else:
        alpha = alpha_marginal
        alpha_rationale = ALPHA_DERIVATION

    # ── grids ────────────────────────────────────────────────────────────────
    soc_grid = np.linspace(args.soc_min, args.soc_max, args.soc_n)
    shares = np.linspace(0.0, 1.0, args.share_n)
    cap_as = args.capacity_ah * 3600.0
    chg_a = float(args.charge_i_ceiling)

    forbidden, chg_info = charge_forbidden_bins(
        side, p_centers, args.charge_quantile, chg_a)
    chg_allowed = np.ones(n_bin, dtype=bool)
    chg_allowed[forbidden] = False

    print("[sdp] TPM %s (%dx%d, row-stochastic)"
          % (os.path.relpath(tpm_path, REPO_ROOT), n_bin, n_bin))
    print("[sdp] demand map: P_dem in [%.9g, %.9g] W; bin centres "
          "%.6g .. %.6g W" % (p_min, p_max, p_centers[0], p_centers[-1]))
    print("[sdp]   source: %s" % map_source)
    print("[sdp]   sidecar's own block (recorded, not necessarily used): "
          "[%.9g, %.9g] W" % (side_min, side_max))
    print("[sdp] gamma_base %g @ dt %g s -> gamma_eff %.12g"
          % (args.gamma_base, args.dt, gamma))
    print("[sdp] alpha = %.12g  (mode %s; marginal %.12g, level %.12g)"
          % (alpha, "explicit" if args.alpha is not None else args.alpha_mode,
             alpha_marginal, alpha_level))
    print("[sdp] charge admission: dwell cut at bin %d (cum %.4f), "
          "%d bins forbidden by dwell, %d by FC budget -> %d forbidden"
          % (chg_info["cut_bin"], chg_info["cum_dwell_at_cut"],
             chg_info["n_forbidden_by_dwell"],
             chg_info["n_forbidden_by_fc_budget"], len(forbidden)))

    # ── solve ────────────────────────────────────────────────────────────────
    stage, soc_next, _feas = build_stage(
        p_centers, shares, soc_grid, alpha, args.dt, cap_as, chg_a,
        chg_allowed, args.soc_target, soc_grid[0], soc_grid[-1])
    J, iters, delta = value_iterate(stage, soc_next, soc_grid, tpm, gamma,
                                    args.tol, args.max_iter)
    converged = delta < args.tol
    print("[sdp] value iteration: %d sweeps, final sup-norm delta %.6g "
          "(tol %g) -> %s"
          % (iters, delta, args.tol, "CONVERGED" if converged else "NOT CONVERGED"))
    if not converged:
        print("[sdp] REFUSING to write an unconverged policy (D7). Raise "
              "--max-iter or relax --tol.", file=sys.stderr)
        return 2

    idx = greedy_policy(J, stage, soc_next, soc_grid, tpm, gamma)
    m = len(shares)
    pol_share = np.where(idx < m, shares[np.minimum(idx, m - 1)], 1.0)
    # A CHARGE cell carries share = 1.0: FC_CHARGE_ENABLE open means
    # assertFcChargeEnable() (.ino:10046) has already dropped BT off the bus,
    # so there is no minority channel to apportion and the FC is carrying
    # everything anyway.  The value is informational for such a cell.
    pol_charge = np.where(idx == m, 1.0, 0.0)

    # ── acceptance check 3, asserted BEFORE writing ─────────────────────────
    if forbidden:
        bad = np.nonzero(pol_charge[:, forbidden] > 0.0)
        if bad[0].size:
            raise SystemExit(
                "INTERNAL: charge_goal asserted in a forbidden bin "
                "(soc row %d, bin %d) - the action mask and the policy "
                "extraction disagree"
                % (int(bad[0][0]), forbidden[int(bad[1][0])]))

    # ── report ───────────────────────────────────────────────────────────────
    i_tgt = int(np.abs(soc_grid - args.soc_target).argmin())
    n_charge = int((pol_charge > 0.0).sum())
    print("[sdp] policy: share min %.3f / mean %.4f / max %.3f over %d cells; "
          "charge-enabled cells %d"
          % (pol_share.min(), pol_share.mean(), pol_share.max(),
             pol_share.size, n_charge))
    print("[sdp] charge_forbidden_bins: %s" % (forbidden or "none"))
    print("[sdp] share slice at SoC %.4f (row %d), by demand bin:"
          % (soc_grid[i_tgt], i_tgt))
    print("[sdp]   " + " ".join("%.2f" % v for v in pol_share[i_tgt]))
    print("[sdp] share column at demand bin 10 (the dominant idle bin), "
          "every 10th SoC row:")
    print("[sdp]   " + " ".join(
        "%.3f:%.2f" % (soc_grid[i], pol_share[i, 10])
        for i in range(0, len(soc_grid), 10)))
    # Acceptance check 2 - non-degeneracy on BOTH axes, reported not assumed.
    var_bins = float(pol_share[i_tgt].max() - pol_share[i_tgt].min())
    var_soc = float(pol_share[:, 10].max() - pol_share[:, 10].min())
    print("[sdp] non-degeneracy: share spread across bins at SoC target "
          "%.3f; across SoC at bin 10 %.3f" % (var_bins, var_soc))
    if var_bins <= 0.0 or var_soc <= 0.0:
        print("[sdp] WARNING: the policy is DEGENERATE on one axis (spread 0) "
              "- see the ALPHA_DERIVATION note; this is what --alpha-mode "
              "level produces by construction.", file=sys.stderr)

    meta = {
        "generated_utc": datetime.datetime.now(datetime.timezone.utc)
                                 .isoformat().replace("+00:00", "Z"),
        "argv": list(sys.argv[1:] if argv is None else argv),
        "tpm": {
            "path": os.path.relpath(tpm_path, REPO_ROOT).replace("\\", "/"),
            "sha256": sha256_file(tpm_path),
            "sidecar_path": os.path.relpath(sidecar_path,
                                            REPO_ROOT).replace("\\", "/"),
            "sidecar_sha256": sha256_file(sidecar_path),
        },
        # THE MAP ACTUALLY USED - this is the block hil_plant_sim.py's
        # load_sdp_policy() reads, and its meaning is unchanged from v1: watts
        # -> the normalized demand coordinate.  What changed (D11) is WHERE the
        # numbers come from, so the provenance is carried IN the same block
        # rather than replacing any existing field: `demand_map_source` names
        # it, and `sidecar_p_dem_*_w` preserve the sidecar's own numbers beside
        # it so a v1-vs-v2 diff shows the map move explicitly.
        "normalization": {
            "p_dem_min_w": p_min, "p_dem_max_w": p_max,
            "demand_map_source": map_source,
            "sidecar_p_dem_min_w": side_min,
            "sidecar_p_dem_max_w": side_max,
        },
        "demand_bins": {
            "n": int(n_bin),
            "edges": [float(e) for e in edges],
            "convention": "matlab-discretize-last-closed",
        },
        "gamma": {
            "base": float(args.gamma_base),
            "dt_s": float(args.dt),
            "effective": float(gamma),
            "rule": "gamma_eff = gamma_base ** (dt/dt_base)",
        },
        "alpha": {"value": float(alpha), "rationale": alpha_rationale},
        "soc": {
            "target": float(args.soc_target),
            "grid_min": float(args.soc_min),
            "grid_max": float(args.soc_max),
            "n": int(args.soc_n),
            "grid": [float(v) for v in soc_grid],
        },
        "actions": {
            "share_ladder": [float(v) for v in shares],
            "charge_goal_values": [0.0, 1.0],
            "charge_forbidden_bins": forbidden,
            "charge_i_ceiling_a": chg_a,
        },
        "solver": {
            "iterations": int(iters),
            "final_delta": float(delta),
            "tolerance": float(args.tol),
            "converged": bool(converged),
            "max_iterations": int(args.max_iter),
        },
        "policy": {
            "share": [[float(v) for v in row] for row in pol_share],
            "charge_goal": [[float(v) for v in row] for row in pol_charge],
        },
    }
    obj = render_policy_json(args, meta)

    if args.dry_run:
        print("[sdp] --dry-run: nothing written")
        return 0
    out = os.path.abspath(args.out)
    if os.path.exists(out) and not args.force:
        print("[sdp] REFUSING to overwrite %s - pass --force" % out,
              file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(out), exist_ok=True)
    atomic_write_json(out, obj)
    print("[sdp] wrote %s (sha256 %s)"
          % (os.path.relpath(out, REPO_ROOT), sha256_file(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
