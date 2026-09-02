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

D12. ALPHA IS CALIBRATED AGAINST BOTH LEVERS, NOT ONE  (2026-09-01,
    adjudicated; OVERNIGHT_LOG.md "SDP charge-economics adjudication").
    *This is what separates sdp_policy_v3.json from v2, and it is the only
    decision in this file that was shipped WRONG and then corrected.*

    THE DEFECT.  v1/v2 shipped alpha = 0.2569444 from D2's marginal-rate
    derivation.  That derivation preserves a SHARE-AXIS invariant carried over
    from SDP_EnergyManagement2.m - and the MATLAB source HAS NO CHARGE
    CONTROL.  The charge action is this port's own addition (D5), and it was
    never checked against the alpha the port inherited.  Under v2 the solver
    asserted charge_goal in 294 cells; campaign scoring, which prices SoC at
    the MEASURED share lever 1/0.412 = 2.427 g/SoC, read every one of them as
    a loss.

    THE MECHANISM, in closed form.  A lever L is an exchange rate in SoC per
    gram of hydrogen.  Value iteration prices SoC at the discounted shadow
    price alpha/(1 - gamma) g/SoC, so an action is TAKEN exactly when

        L  >  (1 - gamma) / alpha                       [the admission bound]

    At v2's numbers the bound is 0.05/0.2569444 = 0.1946 SoC/g while the
    modelled charge lever is L_chg = 0.2090 - it clears by 7.4 %, so charging
    is admitted.  A sweep confirms the flip at alpha ~ 0.2393, i.e. exactly
    (1 - gamma)/L_chg.  Nothing about the charger is mispriced; the SHADOW
    PRICE is, and it is mispriced by having been calibrated on one lever only.

    WHAT THE LOSS CHAIN DOES *NOT* EXPLAIN, since it was the first hypothesis
    and it is wrong.  The two levers share the hydrogen basis k = 1/(eta*Q_LHV)
    exactly, so k CANCELS from their ratio:

        L_share / L_chg = V_bus / V_pack  (model: 15.95/7.4 -> ratio 0.4640)

    against a measured ratio 0.2364/0.412 = 0.5738.  The model is therefore
    CONSERVATIVE about charging by 19 %, not optimistic: no efficiency term,
    no accounting basis and no eta_fc choice can produce the observed
    over-charging, because every one of them scales BOTH levers together.

    THE FIX - TWO-SIDED CALIBRATION.  alpha is now placed at the GEOMETRIC
    MEAN of the two levers' admission thresholds:

        alpha = (1 - gamma) / sqrt(L_share * L_chg)     [--alpha-mode lever]
              = 0.05 / sqrt(0.4504505 * 0.2089864)
              = 0.1629624

    which is the unique alpha whose admission bound sits equidistant (in log
    lever) from the two levers, so neither axis is calibrated against and the
    other left unchecked.  Under it the bound is 0.3068 SoC/g: the share lever
    (0.4505 modelled, 0.412 measured) clears it, the charge lever (0.2090
    modelled, 0.2364 measured) does not.  CHARGING IS THEREFORE REJECTED
    ENDOGENOUSLY, by the economics, not by a mask - `--forbid-charge` exists
    but is deliberately NOT the shipped mechanism, because a mask records no
    reason and cannot revise itself.

    THE KNIFE-EDGE, stated because it is the honest part.  v2's alpha sat
    0.1946 against a lever of 0.2090: a 7 % miss, not a gross one.  The two
    admission windows the tripwire below enforces are correspondingly narrow -
    model (0.1110, 0.2393), measured (0.1214, 0.2115) - and the shipped alpha
    clears both edges by 27-47 %.  Any future change to the pack voltage, the
    bus voltage, the capacity or gamma moves the windows, and the pre-solve
    assert is what makes that visible instead of silent.

    HONESTY AMENDMENT (adjudicated, and it is the reason the MEASURED levers
    below are documentation rather than the alpha source): the shipped alpha
    is MODEL-anchored - it is computed from this script's own constants, so it
    is reproducible from the file without reference to any campaign.  The
    measured-lever variant, alpha = 0.05/sqrt(0.412*0.2364) = 0.1602130, was
    solved and VERIFIED to produce a BIT-IDENTICAL policy table.  The choice
    between them is therefore free, and the model-anchored one is taken.

    THE REVISIT CONDITION, which is what a calibrated alpha buys over a mask.
    Charging returns to the policy ENDOGENOUSLY the moment the charger's real
    lever exceeds (1 - gamma)/alpha = 0.3068 SoC/g - e.g. after the R1 MPPT
    threshold question is answered and fw v24 writes Ag105 reg 0x02, or if the
    charger is replaced.  Nothing in this file needs editing for that to
    happen; the measured lever simply has to move, and the artifact records
    the bound it must cross.

D13. THE CHARGER HAS TWO ERAS, AND EVERY LEVER NUMBER ABOVE BELONGS TO ONE
    (2026-09-01, the charger-efficiency round).
    D12's whole argument is about an exchange rate; this decision changes one
    of the two rates it balances, so read the two together.

    Until 2026-09-01 the simulator's hi-fi Ag105 was a 1:1 CURRENT-TRANSFER
    element: the pack received exactly the current the bus supplied, so a
    delivered amp cost V_bus watts and the model destroyed i*(V_chg - V_batt).
    The plant is now an energy-conserving converter at a static efficiency
    (AG105_Silvertel.pdf DC Electrical Characteristics item 1, 88 % typ; the
    operator ruled a static 0.88 at this rig's 15-16 V in / 2S point), so a
    delivered amp costs V_pack/eta watts.  The charge lever moves with it:

        old:  L_chg = 1/(k * V_bus       * C_As) = 0.2089864 SoC/g
        new:  L_chg = 1/(k * V_pack/eta  * C_As) = eta * L_share
                                                 = 0.3963964 SoC/g at eta 0.88

    The new form is exact and pleasing: the charge lever is the share lever
    times the converter efficiency, whatever the pack, the bus or the capacity
    do, because BOTH levers now bill at the pack voltage and differ only by
    the conversion loss.  The two levers are 1/eta = 13.64 % apart where they
    used to be 2.16x apart, so D12's "knife-edge" is now a genuinely narrow
    band and the alpha placement matters more, not less.

    WHAT THIS DOES TO THE TWO ALPHA MODES, and it is the reason both exist:

      * `lever` (D12's geometric mean of the admission thresholds) still
        places alpha between the two levers and therefore still REJECTS the
        weaker one - now STRUCTURALLY, because the mean of two levers that
        differ only by eta always lands between them.  At eta 0.88 that is
        alpha = 0.1183264, an admission bound of 0.422560 SoC/g, and charging
        is rejected by 6.2 % of lever rather than by 47 %.
      * `charge-edge` (new) places alpha just inside the WORSE lever's
        admission window - alpha = (1-gamma)/L_chg * (1 + 1e-3) = 0.1262625 -
        so BOTH levers clear and charging is admitted ENDOGENOUSLY.  The
        epsilon is defined at alpha_charge_edge() and is three orders below
        the lever separation it sits inside.

    NEITHER IS SHIPPED BY THIS FILE'S AUTHOR.  The operator ruled that the
    eta-era matched DP is solved first and the rule that AGREES WITH WHAT THE
    DP DOES is the one that ships.  --alpha-mode selects; the artifact records
    the era under `charger` and the mode under `alpha.mode`.

    THE MEASURED LEVERS ARE OLD-ERA MEASUREMENTS.  EMS_LEVER_CHARGE_SOC_PER_G
    was measured on campaigns whose plant billed at the bus, so measured_levers()
    PROJECTS it onto the requested era by the billing-voltage ratio.  Under
    that projection the measured charge lever (0.448393) OVERTAKES the measured
    share lever (0.412), i.e. the measurement says charging is the BETTER lever
    exactly where the model says it is the worse - the same ~19 % model/measured
    disagreement D12 recorded, now large enough to change the ORDER.  The
    consequence is explicit in the tripwire: the MEASURED "admit share, reject
    charge" window is UNDECIDABLE in the eta era and is reported as such rather
    than passed.  ⚠️ TODO(verify): re-measure the charge lever on the first
    post-2026-09-01 campaign; until then no alpha decision may rest on the
    projected measured pair alone.

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
    # reproduce the SHIPPED artifact (tools/sdp_policies/sdp_policy_v3.json,
    # demand map 0..25 W - D11; alpha two-sided-calibrated - D12).  --eta-chg-none
    # is now REQUIRED: v3 was solved against the 1:1 current-transfer charger and
    # the default is the plant's eta 0.88 (D13).  Verified bit-identical in the
    # policy block.
    C:/Users/ricky/miniforge3/python.exe tools/sdp_ems_solver.py \
        --eta-chg-none --alpha-mode lever --force
    # the two ETA-ERA candidates (D13); neither is shipped by this file - the
    # operator picks against the eta-era matched DP:
    C:/Users/ricky/miniforge3/python.exe tools/sdp_ems_solver.py \
        --alpha-mode lever       --out <path> --force   # alpha 0.1183264, 0 charge cells
    C:/Users/ricky/miniforge3/python.exe tools/sdp_ems_solver.py \
        --alpha-mode charge-edge --out <path> --force   # alpha 0.1262625, 540 charge cells
    # reproduce v2's economics (the shipped-and-corrected alpha, D12); the
    # window assert refuses it without the explicit override:
    C:/Users/ricky/miniforge3/python.exe tools/sdp_ems_solver.py \
        --eta-chg-none --alpha-mode marginal --allow-out-of-window \
        --out tools/sdp_policies/sdp_policy_v2.json --force
    # reproduce the v1 mapping (ideal-scaling span from the TPM sidecar):
    C:/Users/ricky/miniforge3/python.exe tools/sdp_ems_solver.py \
        --eta-chg-none --demand-map-sidecar --alpha-mode marginal \
        --allow-out-of-window --out tools/sdp_policies/sdp_policy_v1.json --force

⚠️ `meta.argv` IN THE SHIPPED v3 ARTIFACT IS `[]`, not the command above.  It
records `sys.argv[1:]` of the invocation that baked the file, and that
invocation passed no flags (every value came from the defaults) — so an EMPTY
argv is the correct, faithful record of a default `--force` regeneration, NOT a
missing field.  Do not "fix" it by editing the JSON: `meta` is outside the
policy block, so a hand-edit would not move the policy-block sha256
(0443febf…) that identifies the artifact, and the file would then claim a
provenance no run produced.  Regenerate with the documented command instead if
a populated argv is ever wanted, and check the policy sha has NOT moved.

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

from charger_power import (                                          # noqa: E402
    ETA_CHG_DEFAULT, charger_billing_voltage_v, charger_bus_current_a,
    charger_bus_power_w, check_eta_chg, era_label)
from tpm_generator import rescale_gamma                              # noqa: E402


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
DEFAULT_TPM = os.path.join(REPO_ROOT, "references", "EMS", "generated",
                           "TPM_dt1_hil.mat")
DEFAULT_OUT = os.path.join(_HERE, "sdp_policies", "sdp_policy_v3.json")
# The SCHEMA is the FILE FORMAT contract between this script and
# hil_plant_sim.py's load_sdp_policy(); it is NOT the artifact's version.  v2
# changes the demand MAP (D11) and v3 the alpha CALIBRATION (D12) - neither
# changes the shape of the document, so the schema stays `sdp-policy-v1` and
# the existing consumer parses all three files unchanged.  (v3 ADDS keys under
# `alpha` and `actions`; the consumer reads `alpha.value` and the policy
# tables, so additive fields are compatible by construction.)
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
# Used to convert the Ag105's charge CURRENT into the bus POWER the fuel cell
# must supply for it (the `physical` charger accounting, D11 of
# gen_dp_ems_table.py) - directly in the OLD charger era, and as the bus-side
# reference for the FC-budget current in the new one (D13).  The droop term is
# not modelled: at this demand scale it moves the bus by under 0.2 V.
V_BUS_NOMINAL_V = 15.95

# ── THE CHARGER ERA (D13) ────────────────────────────────────────────────────
# None selects the OLD 1:1 current-transfer charger (a delivered amp costs a
# bus amp, i.e. V_bus watts); a float selects the energy-conserving converter
# the plant now models, where a delivered amp costs V_pack/eta watts.  The
# DEFAULT IS THE PLANT'S 0.88 (charger_power.ETA_CHG_DEFAULT, AG105 datasheet)
# because THIS artifact is a policy for the plant as it now is; the old era
# stays reachable with --eta-chg-none so v1/v2/v3 can be reproduced exactly.
ETA_CHG_MODEL = ETA_CHG_DEFAULT

# --alpha-mode charge-edge places alpha this far above the worse lever's
# admission bound.  See alpha_charge_edge().
ALPHA_CHARGE_EDGE_EPS = 1.0e-3

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

# ── MEASURED LEVERS (D12).  Hardware exchange rates, SoC per gram of H2. ────
# These are DOCUMENTATION and the source of the MEASURED admission window that
# the pre-solve tripwire checks against.  They are deliberately NOT the source
# of the shipped alpha, which is computed from this script's own model
# constants so that it is reproducible from the file alone (D12's honesty
# amendment).  The measured-lever alpha, 0.05/sqrt(0.412*0.2364) = 0.1602130,
# was solved and verified to produce a BIT-IDENTICAL policy table.
#
# SHARE lever: campaign hil_report_20260831_191509 measured 0.409-0.415 SoC/g
# on TWO independent stimuli (the 61 s ems cycle and the 340 s FTP75, 2.3 %
# apart); the offline DP solve predicted 0.405.  0.412 is the midpoint.
EMS_LEVER_SHARE_SOC_PER_G = 0.412
# CHARGE lever: the C1->C2 marginal accounting across campaigns 20260831_222036
# and 20260901_000816 (the offline figure was 0.169; 0.2364 is the marginal
# rate the two campaigns bracket).  The Ag105 is the ~1.74x WORSE lever, which
# is the whole finding.
EMS_LEVER_CHARGE_SOC_PER_G = 0.2364

# Full-size reference numbers, used ONLY by the alpha derivation below.
# SDP_EnergyManagement2.m:8-10, :16.
FULL_SIZE_ALPHA = 500.0
FULL_SIZE_EM_V = 720.0
FULL_SIZE_Q_AH = 100.0
FULL_SIZE_P_DEM_MAX_W = 60000.0
FULL_SIZE_P_DEM_MIN_W = -50000.0


ALPHA_DERIVATION = """\
THE SHIPPED DERIVATION IS `lever` (D12).  alpha is placed at the geometric
mean of the two control levers' admission thresholds,

    alpha = (1 - gamma) / sqrt(L_share * L_chg)

with both levers computed from THIS SCRIPT'S OWN constants as SoC per gram:

    L_share = 1 / (k * V_pack * C_As)      k = 1/(eta_fc * Q_LHV)  [g/J]
    L_chg   = 1 / (k * V_bus  * C_As)      C_As = capacity_Ah * 3600

An action is taken exactly when its lever exceeds (1 - gamma)/alpha, so this
placement leaves BOTH levers checked against the shadow price instead of one.
The full argument, including what went wrong under the derivation below, is
D12 at the top of this file.

============================================================================
THE PREVIOUS DERIVATION (`marginal`) - SHIPPED IN v1/v2, AND FAILED.
============================================================================
Kept reachable (--alpha-mode marginal) because it regenerates v1/v2's
economics, and kept in full because it is the record of how the defect got in:
it preserves a SHARE-AXIS invariant carried over from SDP_EnergyManagement2.m,
a source that HAS NO CHARGE CONTROL, and the charge action this port adds
(D5) was never checked against it.  The result priced SoC at 5.139 g/SoC and
admitted the Ag105 at 294 cells.  See D12.

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

Note on the boost efficiency, CORRECTED 2026-09-01 (D12).  P_fc here is a
BUS-SIDE power, so every rate above is referred to the bus.  Referring them to
the stack instead multiplies the hydrogen rate by 1/ETA_BOOST and leaves the
SoC rate alone.  The claim this note used to make - that the resulting shift is
absorbed because full size makes the same reduction, "so the ported ratio is
unaffected" - is true ONLY of the SHARE-VS-SHARE trade the ported ratio
describes.  It is FALSE of the CHARGE-VS-ALPHA trade, and the difference is the
whole of D12: a uniform 1/ETA_BOOST billing on the hydrogen term is
argmin-equivalent to scaling alpha by ETA_BOOST, which moves the admission
bound (1 - gamma)/alpha by 1/ETA_BOOST and FLIPS the charge decision at the
v1/v2 alpha.  A convention that cancels on one axis does not automatically
cancel on another that the source it was ported from did not have.  What the
omission still costs, unchanged: J is not a hydrogen PREDICTION; this artifact
ships a policy, not a gram figure."""


# ---------------------------------------------------------------------------
# The lever algebra (D12)
# ---------------------------------------------------------------------------
def model_levers(v_pack=V_PACK_NOMINAL_V, v_bus=V_BUS_NOMINAL_V,
                 capacity_ah=BATT_CAPACITY_AH, eta_fc=ETA_FC,
                 q_lhv=Q_LHV_J_PER_G, eta_chg=None):
    """(L_share, L_chg) in SoC per gram of hydrogen, from MODEL constants.

    A lever is `SoC gained (or not spent) per gram of hydrogen burnt`:

        share:  shifting one joule from the FC onto the pack costs
                1/(eta*Q_LHV) g of hydrogen NOT burnt, and spends
                1/(V_pack*C_As) of SoC  ->  L = 1/(k * V_pack * C_As)
        charge: one joule delivered to the charger costs the same k grams and
                buys 1/(V_chg_bill*C_As) of SoC, where V_chg_bill is the BUS
                WATTS THE CHARGER COSTS PER AMP IT DELIVERS  ->
                L = 1/(k * V_chg_bill * C_As)

    V_chg_bill is the whole charger-era question (D13):

        OLD (eta_chg None): V_bus.  The 1:1 current-transfer charger moved
            current, not energy, so a delivered amp cost a bus amp.
            L_chg = 1/(k * V_bus * C_As) = 0.2089864 at the shipped constants.
        NEW (eta_chg a float): V_pack/eta_chg.  An energy-conserving converter
            costs V_pack/eta watts per delivered amp, so
            L_chg = eta_chg * L_share  EXACTLY - the two levers are then
            1/eta_chg apart whatever the pack, the bus or the capacity do.
            At eta_chg 0.88: L_chg = 0.3963964, i.e. 13.64 % under L_share.

    The hydrogen basis k CANCELS from their ratio, which is why no efficiency
    or accounting convention on the HYDROGEN side can explain the v2
    over-charging - see D12.  The CHARGER-side convention is a different
    matter and does move the ratio: that is D13.
    """
    k = 1.0 / (eta_fc * q_lhv)
    cap_as = capacity_ah * 3600.0
    v_chg_bill = charger_billing_voltage_v(v_bus, v_pack, eta_chg)
    return (1.0 / (k * v_pack * cap_as), 1.0 / (k * v_chg_bill * cap_as))


def measured_levers(eta_chg=None,
                    share=None, charge=None,
                    v_pack=V_PACK_NOMINAL_V, v_bus=V_BUS_NOMINAL_V):
    """(L_share, L_chg) as MEASURED, projected onto the requested era.

    The share lever is era-INVARIANT: it never touches the charger.  The
    charge lever is not.  EMS_LEVER_CHARGE_SOC_PER_G was measured on campaigns
    whose plant billed the charger at the BUS voltage, so it is an OLD-ERA
    number, and using it unchanged against a new-era policy would price the
    charger against a plant that no longer exists.

    The projection is the ratio of the two eras' billing voltages,

        L_chg(eta) = L_chg(old) * V_bus / (V_pack/eta)

    ⚠️ IT IS A PROJECTION, NOT A MEASUREMENT.  It assumes the campaign
    accounting scales with the billing voltage and nothing else, which is
    exactly the assumption the first new-era campaign will test.
    TODO(verify): re-measure the charge lever on a post-2026-09-01 campaign
    and replace this projection with the number.
    """
    l_share = EMS_LEVER_SHARE_SOC_PER_G if share is None else float(share)
    l_chg = EMS_LEVER_CHARGE_SOC_PER_G if charge is None else float(charge)
    if check_eta_chg(eta_chg) is not None:
        l_chg *= v_bus / charger_billing_voltage_v(v_bus, v_pack, eta_chg)
    return (l_share, l_chg)


def admission_window(one_minus_gamma, lever_hi, lever_lo):
    """The open interval of alpha that ADMITS `lever_hi` and REJECTS `lever_lo`.

    Value iteration prices SoC at alpha/(1-gamma) g/SoC, so a lever L is taken
    exactly when L > (1-gamma)/alpha.  Admitting the better lever and rejecting
    the worse one therefore bounds alpha to

        ( (1-gamma)/lever_hi ,  (1-gamma)/lever_lo )

    Returned as (lo, hi) with lo < hi.  Requires lever_hi > lever_lo > 0.
    """
    if not (lever_hi > lever_lo > 0.0):
        raise ValueError("admission_window needs lever_hi > lever_lo > 0, got "
                         "%r, %r" % (lever_hi, lever_lo))
    return (one_minus_gamma / lever_hi, one_minus_gamma / lever_lo)


def admit_both_window(one_minus_gamma, lever_hi, lever_lo):
    """The interval of alpha that admits BOTH levers (D13, --alpha-mode charge-edge).

    A lever L is taken iff L > (1-gamma)/alpha, so admitting both means
    clearing the WORSE one: alpha > (1-gamma)/min(L).  There is no model-side
    upper bound - a larger alpha only prices SoC higher - so the interval is
    open above and is returned as (lo, inf).
    """
    lo = min(float(lever_hi), float(lever_lo))
    if lo <= 0.0:
        raise ValueError("admit_both_window needs positive levers, got %r, %r"
                         % (lever_hi, lever_lo))
    return (one_minus_gamma / lo, float("inf"))


def alpha_charge_edge(one_minus_gamma, lever_hi, lever_lo,
                      epsilon=ALPHA_CHARGE_EDGE_EPS):
    """The smallest alpha that admits BOTH levers, plus a margin (D13).

    "Just inside" is DEFINED here rather than left to a reader: alpha is the
    admission bound of the WORSE lever scaled by (1 + epsilon), with epsilon
    1e-3.  The margin exists because the admission test is a strict
    inequality and the bound is reached exactly at equality; 1e-3 is four
    orders above float64 round-off on these quantities and three orders below
    the 13.6 % lever separation it sits inside, so it cannot move a decision
    that the levers themselves do not already decide.
    """
    lo, _hi = admit_both_window(one_minus_gamma, lever_hi, lever_lo)
    return lo * (1.0 + float(epsilon))


def alpha_lever(one_minus_gamma, lever_hi, lever_lo):
    """The two-sided-calibrated alpha: the geometric mean of the window's ends.

    Equivalently (1-gamma)/sqrt(lever_hi*lever_lo) - the alpha whose admission
    bound is equidistant in log-lever from the two controls (D12).
    """
    lo, hi = admission_window(one_minus_gamma, lever_hi, lever_lo)
    return (lo * hi) ** 0.5


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
def charge_forbidden_bins(side, p_centers, quantile, chg_a, eta_chg=None):
    """0-based bin indices in which the policy may NEVER assert charge_goal.

    TWO independent rules, unioned:

      (a) DWELL TAIL.  Bins above the `quantile` point of the TPM's observed
          row occupancy are the acceleration transients; operator ruling (b)
          (2026-08-30) forbids FC-charge there by design.
      (b) FC CURRENT BUDGET.  With FC_CHARGE_ENABLE open the FC channel alone
          carries the load plus the charger's INPUT current.  Any bin where
              P_dem/V_bus + i_chg_bus > CHARGE_FC_MARGIN * LIMIT_I_FC_MAX_A
          is forbidden regardless of dwell.  `i_chg_bus` is `chg_a` itself in
          the old charger era (1:1 current transfer) and the smaller
          V_pack*chg_a/(eta*V_bus) in the new one (D13), so the new era's
          budget binds later.

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

    i_fc = (np.maximum(p_centers, 0.0) / V_BUS_NOMINAL_V
            + charger_bus_current_a(chg_a, V_BUS_NOMINAL_V, V_PACK_NOMINAL_V,
                                    eta_chg))
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
                chg_allowed, soc_target, soc_lo, soc_hi, eta_chg=None):
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
        # bus node and what the hardware actually does.  WHICH draw is the
        # charger era (D13): V_bus*i in the old one, V_pack*i/eta in the new.
        # V_PACK_NOMINAL_V is this solver's flat 2S nominal - it has no OCV
        # curve at all (see WHAT THIS MODEL DOES NOT CONTAIN), so the new-era
        # billing inherits that reduction and nothing more.
        soc_next[j, :, m] = soc_grid + chg_a * dt / cap_as
        p_fc_chg = p_pos + charger_bus_power_w(chg_a, V_BUS_NOMINAL_V,
                                               V_PACK_NOMINAL_V, eta_chg)
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
        "charger": {
            "eta_chg": (None if args.eta_chg is None else float(args.eta_chg)),
            "era": era_label(args.eta_chg),
            "billing_rule": ("bus power = V_bus * i_chg (1:1 current transfer)"
                             if args.eta_chg is None else
                             "bus power = V_pack * i_chg / eta_chg"),
            "v_bus_nominal_v": V_BUS_NOMINAL_V,
            "note": "D13. An artifact with eta_chg null was solved against "
                    "the pre-2026-09-01 charger model, which prices the "
                    "Ag105 ~1.9x too dearly against the current plant.",
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
    ap.add_argument("--eta-chg", type=float, default=ETA_CHG_MODEL,
                    help="Ag105 charge efficiency, selecting the CHARGER ERA "
                         "(D13). Default %g = the plant's energy-conserving "
                         "converter, in which a delivered amp costs "
                         "V_pack/eta watts. --eta-chg-none selects the OLD "
                         "1:1 current-transfer charger and is what reproduces "
                         "sdp_policy_v1/v2/v3." % ETA_CHG_MODEL)
    ap.add_argument("--eta-chg-none", action="store_true",
                    help="solve against the OLD 1:1 current-transfer charger "
                         "(a delivered amp costs a BUS amp). Required to "
                         "reproduce any artifact baked before 2026-09-01.")
    ap.add_argument("--alpha-mode", default="lever",
                    choices=["lever", "charge-edge", "marginal", "level"],
                    help="how alpha is derived (default lever - D12's "
                         "two-sided lever calibration, the SHIPPED value). "
                         "'charge-edge' (D13) places alpha just inside the "
                         "WORSE lever's admission window, so BOTH levers "
                         "clear and charging is admitted endogenously. "
                         "'marginal' is the share-axis-only derivation SHIPPED "
                         "IN v1/v2 AND FAILED (it admits the Ag105 charge "
                         "lever; needs --allow-out-of-window). 'level' "
                         "reproduces the REJECTED power-span scaling, which "
                         "collapses the policy to pure hydrogen greed - kept "
                         "for inspection only.")
    ap.add_argument("--allow-out-of-window", action="store_true",
                    help="permit an alpha OUTSIDE the lever admission windows "
                         "(D12). Required to reproduce v1/v2's economics; "
                         "without it a mispriced alpha is a hard refusal, "
                         "which is the tripwire that would have caught v2.")
    ap.add_argument("--forbid-charge", action="store_true",
                    help="mask the charge action in EVERY demand bin. "
                         "Available, but NOT the shipped mechanism: under the "
                         "default alpha charging is rejected ENDOGENOUSLY by "
                         "the economics (D12), which records a reason and "
                         "self-revises; a mask does neither.")
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
    if args.alpha is not None and args.alpha <= 0.0:
        ap.error("--alpha must be > 0 (it is a price; the admission bound "
                 "(1-gamma)/alpha is undefined at 0)")
    if not 0.0 < args.charge_quantile <= 1.0:
        ap.error("--charge-quantile must be in (0, 1]")
    # D13.  --eta-chg-none is not "--eta-chg 1.0": the old era bills at the
    # BUS voltage and eta = 1.0 would bill at the PACK voltage, which is a
    # third model neither plant ever implemented.  Hence a flag, not a value.
    if args.eta_chg_none:
        if args.eta_chg != ETA_CHG_MODEL:
            ap.error("--eta-chg and --eta-chg-none are mutually exclusive - "
                     "they are two ways of answering the same question")
        args.eta_chg = None
    try:
        args.eta_chg = check_eta_chg(args.eta_chg)
    except ValueError as exc:
        ap.error(str(exc))
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
    one_minus_gamma = 1.0 - gamma
    l_share, l_chg = model_levers(capacity_ah=args.capacity_ah,
                                  eta_chg=args.eta_chg)
    l_share_meas, l_chg_meas = measured_levers(args.eta_chg)

    # The REQUIRED window depends on what the alpha mode is trying to do
    # (D13): `lever` admits the better lever and rejects the worse, so its
    # window is bounded on both sides; `charge-edge` admits BOTH and its
    # window is open above.  `_window_or_none` returns None when the lever
    # pair cannot express the intent at all - a REAL case in the eta era,
    # where the PROJECTED measured charge lever overtakes the share lever and
    # no alpha admits share while rejecting charge.
    def _window_or_none(fn, hi, lo):
        try:
            return fn(one_minus_gamma, hi, lo)
        except ValueError:
            return None

    alpha_marginal = FULL_SIZE_ALPHA * (V_PACK_NOMINAL_V * args.capacity_ah) \
        / (FULL_SIZE_EM_V * FULL_SIZE_Q_AH)
    alpha_level = FULL_SIZE_ALPHA * p_max / FULL_SIZE_P_DEM_MAX_W
    alpha_two_sided = (alpha_lever(one_minus_gamma, l_share, l_chg)
                       if l_share > l_chg else float("nan"))
    alpha_edge = alpha_charge_edge(one_minus_gamma, l_share, l_chg)
    if args.alpha is not None:
        alpha = float(args.alpha)
        alpha_mode_used = "explicit"
        alpha_rationale = ("EXPLICIT --alpha %r, overriding the derivation "
                           "below.\n\n%s" % (alpha, ALPHA_DERIVATION))
    elif args.alpha_mode == "level":
        alpha = alpha_level
        alpha_mode_used = "level"
        alpha_rationale = ("--alpha-mode level: the REJECTED power-span "
                           "scaling, present for inspection.\n\n%s"
                           % ALPHA_DERIVATION)
    elif args.alpha_mode == "marginal":
        alpha = alpha_marginal
        alpha_mode_used = "marginal"
        alpha_rationale = ("--alpha-mode marginal: the share-axis-only "
                           "derivation SHIPPED IN v1/v2 AND FAILED (D12) - it "
                           "prices SoC at alpha/(1-gamma) = %.4f g/SoC, an "
                           "admission bound of %.4f SoC/g, which the modelled "
                           "charge lever %.4f clears.\n\n%s"
                           % (alpha_marginal / one_minus_gamma,
                              one_minus_gamma / alpha_marginal, l_chg,
                              ALPHA_DERIVATION))
    elif args.alpha_mode == "charge-edge":
        alpha = alpha_edge
        alpha_mode_used = "charge-edge"
        alpha_rationale = ("--alpha-mode charge-edge (D13): alpha is placed "
                           "at the WORSE lever's admission bound %.9g times "
                           "(1 + %g), so BOTH levers clear and charging is "
                           "admitted ENDOGENOUSLY. Levers: share %.6f, "
                           "charge %.6f (era: %s).\n\n%s"
                           % (one_minus_gamma / min(l_share, l_chg),
                              ALPHA_CHARGE_EDGE_EPS, l_share, l_chg,
                              era_label(args.eta_chg), ALPHA_DERIVATION))
    else:
        alpha = alpha_two_sided
        alpha_mode_used = "lever"
        alpha_rationale = ALPHA_DERIVATION
        if not (alpha == alpha):        # NaN: the levers do not order
            print("[sdp] REFUSING to solve: --alpha-mode lever needs the "
                  "share lever to BEAT the charge lever, and at this era "
                  "(%s) it does not (share %.6f, charge %.6f). Use "
                  "--alpha-mode charge-edge, or an explicit --alpha."
                  % (era_label(args.eta_chg), l_share, l_chg),
                  file=sys.stderr)
            return 2

    # ── the D12 tripwire, BEFORE any solve ──────────────────────────────────
    # The shipped alpha must lie STRICTLY inside both admission windows: the
    # modelled one (this script's own constants) and the measured one (the
    # campaign levers).  Outside either, the policy prices at least one control
    # against a lever it was never calibrated on - which is exactly how v2's
    # 294 charge cells got shipped.
    # D13: the window the tripwire enforces is the one the MODE is asking
    # for.  `lever` (and every historical mode) must admit share and reject
    # charge; `charge-edge` must admit both.  An UNDECIDABLE window (None -
    # a lever pair that cannot express the intent) is reported and skipped
    # rather than counted as a pass or as a refusal, because there is no
    # alpha it could refuse in favour of.
    if alpha_mode_used == "charge-edge":
        win_fn, win_intent = admit_both_window, "admit BOTH levers"
    else:
        win_fn, win_intent = admission_window, "admit share, reject charge"
    win_model = _window_or_none(win_fn, l_share, l_chg)
    win_meas = _window_or_none(win_fn, l_share_meas, l_chg_meas)
    in_model = win_model is not None and win_model[0] < alpha < win_model[1]
    in_meas = win_meas is not None and win_meas[0] < alpha < win_meas[1]
    undecidable = [name for name, w in (("MODEL", win_model),
                                        ("MEASURED", win_meas)) if w is None]
    checked_ok = ((win_model is None or in_model)
                  and (win_meas is None or in_meas))
    if not checked_ok and not args.allow_out_of_window:
        which = []
        if win_model is not None and not in_model:
            which.append("MODEL (%.6f, %.6f)" % win_model)
        if win_meas is not None and not in_meas:
            which.append("MEASURED (%.6f, %.6f)" % win_meas)
        print(
            "[sdp] REFUSING to solve: alpha = %.9g (mode %s) lies OUTSIDE the "
            "%s lever admission window%s (D12).\n"
            "[sdp]   A lever L is TAKEN iff L > (1-gamma)/alpha = %.6f SoC/g. "
            "Levers: share %.4f model / %.4f measured; charge %.4f model / "
            "%.4f measured.\n"
            "[sdp]   This is the tripwire that would have caught "
            "sdp_policy_v2.json. Use --alpha-mode lever, or pass "
            "--allow-out-of-window to reproduce a historical artifact."
            % (alpha, alpha_mode_used, " and ".join(which),
               "" if len(which) == 1 else "s", one_minus_gamma / alpha,
               l_share, l_share_meas, l_chg, l_chg_meas),
            file=sys.stderr)
        return 2

    # ── grids ────────────────────────────────────────────────────────────────
    soc_grid = np.linspace(args.soc_min, args.soc_max, args.soc_n)
    shares = np.linspace(0.0, 1.0, args.share_n)
    cap_as = args.capacity_ah * 3600.0
    chg_a = float(args.charge_i_ceiling)

    forbidden, chg_info = charge_forbidden_bins(
        side, p_centers, args.charge_quantile, chg_a, args.eta_chg)
    # L6: the DERIVED count, kept before the blanket mask can overwrite it, so
    # the summary line below can report both numbers instead of printing
    # "%d by dwell, %d by budget -> %d forbidden" with a total that is neither
    # their union nor related to them.
    derived_forbidden = list(forbidden)
    n_forbidden_derived = len(derived_forbidden)
    if args.forbid_charge:
        # The blanket mask.  Unioned with the derived set rather than replacing
        # it, so `charge_forbidden_bins` keeps one meaning in the artifact:
        # "bins in which the policy may never assert charge_goal".
        # (No flag is stored on `chg_info` here: the artifact's
        # `actions.forbid_charge_all` is written from `args.forbid_charge`
        # directly at the emit site, and nothing ever read a copy on this dict.)
        forbidden = sorted(set(range(n_bin)) | set(derived_forbidden))
    # UNION SEMANTICS, asserted rather than assumed: the mask may only ever ADD
    # forbidden bins.  A future edit that replaced the derived set instead of
    # unioning it would silently re-admit a bin the dwell or FC-budget rule
    # forbids, which is the one thing this variable must never do.
    assert set(forbidden) >= set(derived_forbidden), (
        "the charge mask dropped derived-forbidden bins %r"
        % sorted(set(derived_forbidden) - set(forbidden)))
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
    print("[sdp] charger era: %s" % era_label(args.eta_chg))
    print("[sdp] alpha = %.12g  (mode %s; lever %.12g, charge-edge %.12g, "
          "marginal %.12g, level %.12g)"
          % (alpha, alpha_mode_used, alpha_two_sided, alpha_edge,
             alpha_marginal, alpha_level))
    # ── D12 acceptance report: the lever economics this alpha implies ────────
    bound = one_minus_gamma / alpha
    print("[sdp] levers (SoC/g): share %.6f model / %.6f measured; "
          "charge %.6f model / %.6f measured%s"
          % (l_share, l_share_meas, l_chg, l_chg_meas,
             "" if args.eta_chg is None
             else "  (the measured charge lever is an OLD-ERA measurement "
                  "PROJECTED onto this era - see measured_levers())"))
    print("[sdp] shadow price alpha/(1-gamma) = %.6f g/SoC -> admission "
          "threshold (1-gamma)/alpha = %.6f SoC/g" % (alpha / one_minus_gamma,
                                                      bound))
    for name, lev_m, lev_meas in (
            ("share ", l_share, l_share_meas),
            ("charge", l_chg, l_chg_meas)):
        print("[sdp]   %s: model %s (%.6f vs %.6f), measured %s (%.6f)"
              % (name, "ADMIT " if lev_m > bound else "REJECT", lev_m, bound,
                 "ADMIT " if lev_meas > bound else "REJECT", lev_meas))
    def _fmt_win(w, flag):
        if w is None:
            return "UNDECIDABLE (the levers do not order for this intent)"
        return "(%.6f, %.6f) %s" % (w[0], w[1], "IN" if flag else "OUT")

    print("[sdp] admission windows (%s): model %s; measured %s"
          % (win_intent, _fmt_win(win_model, in_model),
             _fmt_win(win_meas, in_meas)))
    if undecidable:
        print("[sdp] NOTE: the %s lever pair cannot express %r, so that "
              "window was NOT checked. In the eta era the projected measured "
              "charge lever OVERTAKES the share lever, which is exactly the "
              "reading the first new-era campaign has to settle."
              % (" and ".join(undecidable), win_intent), file=sys.stderr)
    if not checked_ok:
        print("[sdp] WARNING: alpha is OUT of a lever admission window and "
              "--allow-out-of-window was given - this artifact reproduces a "
              "historical economics, it is not the shipped calibration (D12).",
              file=sys.stderr)
    if args.forbid_charge:
        print("[sdp] --forbid-charge: the charge action is MASKED in all %d "
              "bins (not the shipped mechanism - see D12)" % n_bin)
    # L6: the derived union is reported as the derived union.  The blanket mask
    # is reported SEPARATELY, as the override it is — folding it into this line
    # made the printed total disagree with both of its own components.
    print("[sdp] charge admission: dwell cut at bin %d (cum %.4f), "
          "%d bins forbidden by dwell, %d by FC budget -> %d forbidden "
          "(derived)%s"
          % (chg_info["cut_bin"], chg_info["cum_dwell_at_cut"],
             chg_info["n_forbidden_by_dwell"],
             chg_info["n_forbidden_by_fc_budget"], n_forbidden_derived,
             ("; --forbid-charge OVERRIDES this to all %d bins" % n_bin)
             if args.forbid_charge else ""))

    # ── solve ────────────────────────────────────────────────────────────────
    stage, soc_next, _feas = build_stage(
        p_centers, shares, soc_grid, alpha, args.dt, cap_as, chg_a,
        chg_allowed, args.soc_target, soc_grid[0], soc_grid[-1],
        args.eta_chg)
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
        # D12.  `value` keeps its v1/v2 meaning and position; everything else
        # in this block is ADDITIVE provenance, so a consumer that reads only
        # `alpha.value` is unaffected by the recalibration.
        "alpha": {
            "value": float(alpha),
            "mode": alpha_mode_used,
            "candidates": {
                "lever": (None if alpha_two_sided != alpha_two_sided
                          else float(alpha_two_sided)),
                "charge_edge": float(alpha_edge),
                "marginal": float(alpha_marginal),
                "level": float(alpha_level),
            },
            "levers_soc_per_g": {
                "share_model": float(l_share),
                "charge_model": float(l_chg),
                "share_measured": float(l_share_meas),
                "charge_measured": float(l_chg_meas),
                "charge_measured_is_projection": bool(args.eta_chg is not None),
                "charge_measured_as_measured": EMS_LEVER_CHARGE_SOC_PER_G,
                "measured_source":
                    "share 0.409-0.415 on two stimuli, campaign "
                    "hil_report_20260831_191509; charge C1->C2 marginal "
                    "accounting, campaigns 20260831_222036 / 20260901_000816",
            },
            "admission": {
                "shadow_price_g_per_soc": float(alpha / one_minus_gamma),
                "threshold_soc_per_g": float(one_minus_gamma / alpha),
                "window_intent": win_intent,
                "window_model": (None if win_model is None
                                 else [float(win_model[0]),
                                       float(win_model[1])]),
                "window_measured": (None if win_meas is None
                                    else [float(win_meas[0]),
                                          float(win_meas[1])]),
                # None, not False, when the window itself does not exist for
                # this era and intent (D13): the alpha was NOT CHECKED against
                # that pair, which is a different statement from "checked and
                # outside".  hil_plant_sim's calibrated-benchmark certificate
                # tests `is not True`, so an undecidable window still REFUSES
                # the frontier role - and now names the reason.
                "in_window_model": (None if win_model is None
                                    else bool(in_model)),
                "in_window_measured": (None if win_meas is None
                                       else bool(in_meas)),
                "allow_out_of_window": bool(args.allow_out_of_window),
                "rule": "a lever L is taken iff L > (1-gamma)/alpha; charging "
                        "returns to the policy endogenously if the charger's "
                        "measured lever ever exceeds threshold_soc_per_g",
            },
            "rationale": alpha_rationale,
        },
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
            # D12: TRUE only under the explicit --forbid-charge mask.  On the
            # shipped artifact this is False and the charge action is available
            # in the admitted bins but never chosen - the difference between
            # "forbidden" and "not worth it" is the whole point.
            "forbid_charge_all": bool(args.forbid_charge),
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
