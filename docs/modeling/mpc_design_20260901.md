# Governor-aware model-predictive energy management: the implemented design

This document records the design as implemented in `tools/mpc_ems.py`, with the
host-native test suite in `tools/test_mpc_ems.py`. It is written from the
adjudication in `docs/modeling/mpc_design_20260901/adjudication.md`, which is
binding. Each ruling below cites the adjudication section that fixed it, and
each measured number cites the candidate that measured it. Numbers measured in
this implementation round are marked as such and were taken on the host named in
section 6.4.

The strategy is not yet registered. Section 8 is the registration step list for
the next agent; nothing outside the two new files was modified in this round.

---

## 1. Problem statement

### 1.1 State, controls and objective

The controlled state is the pack state of charge. The prediction model carries a
second, non-optimised state, which is the firmware share governor's memory.

The control at each decision is the pair (share command, charge intent). The
share is quantized onto a ladder and the charge intent is binary. Both are
exactly the two energy fields of the 22-byte command packet, so the strategy
commands nothing the Raspberry Pi bridge cannot command.

Decisions are taken every 1.0 s over a horizon of `N` = 20 stages, without
discount inside the horizon (adjudication section 1). The decision period is the
`decision_dt_s` of the shipped stochastic-dynamic-programming artifact and the
`dt` of the demand transition-probability matrix, so every strategy in the
comparison shares one stage clock.

The horizon objective is the hydrogen mass burnt over the horizon plus a
terminal state-of-charge price. Equation (1) states it over stages
`k = 0 .. N-1`:

    J = sum_k h2(s_k, c_k, k) * dt_dec  +  huber(x_N - x_ref)          (1)

The stage hydrogen rate is the operator-ruled online proxy of equation (2), with
`eta_fc` = 0.40 and `Q_LHV` = 120000 J/g:

    h2(P) = P_fc,stack / (eta_fc * Q_LHV),   P_fc,stack = P_fc,bus / ETA_BOOST  (2)

The proxy coefficient is 2.0833333e-05 g/s/W. The plant-side metric that scores
the run is `H2_GFC_DC_GAIN_GPS_PER_W` = 1.7637602e-05 g/s/W, so the proxy
over-reads the scored quantity by the constant 1.1811885. The constant cancels
in a ranking at matched terminal state of charge. However, it does not cancel
against the terminal price, which is why section 4 prices that term in the
proxy's own basis. The convex fuel-cell map is available and is refused unless
its three stack coefficients are supplied (adjudication section 1).

### 1.2 Preview and causality

The deterministic variant reads the scenario's own speed profile through
`bind_scenario()` and reconstructs the demand from it. This is preview, not
clairvoyance about the state trajectory.

⚠️ The deterministic variant must be labelled a PREVIEW strategy and must never
be reported as causal on this rig (candidate_opus section 1.3). A result against
a causal law measures the value of preview plus the value of the horizon, and
these runs cannot separate the two. The stochastic variant of section 5 is the
information ablation that separates them, subject to its own caveats.

### 1.3 Constraints

Table 1 lists the constraints the optimiser enforces, with the source of each.

| Constraint | Form | Source |
|---|---|---|
| Share band | command confined to the ladder band, default [0.25, 0.75] | `DP_SHARE_MIN`/`DP_SHARE_MAX`; adjudication section 2.3 |
| Fuel-cell overcurrent | delivered `I_fc <= 0.85 * 1.4 = 1.19 A` at every stage | `LIMIT_I_FC_MAX` (.ino:1375), `DP_CHARGE_FC_MARGIN` |
| Battery overcurrent | delivered `I_batt <= 0.85 * 3.0 = 2.55 A` | `LIMIT_I_BT_MAX` (.ino:1426) |
| Charge admission | only where the ported `charge_mask()` admits | `gen_dp_ems_table` D10; operator ruling (b) 2026-08-30 |
| Charge minimum dwell | a window holds for `SDP_CHG_MIN_DWELL_S` = 8.0 s | `SdpStrategy.charge_hold_status()` |
| State-of-charge window | soft, priced through the terminal term | `sdp_ems_solver` D3 |

The default band is the dynamic program's own. It stops 0.10 short of
`DROOP_R_MIN` and `DROOP_R_MAX`, so `updateShareSetpointCutoff()` can never
latch and `applyShareRatio()` can never attempt a ratio-based cut. The
prediction model therefore needs no cut branch, no load guard and no
survivor-blanking branch. That is a simplification obtained by a constraint, not
by an omission. The wider SDP envelope [0.15, 0.85] is selectable through the
`share_band` parameter for a like-for-like leg against `sdp-v3`.

The fuel-cell-charge and regen paths are mutually exclusive in
`assertFcChargeEnable()`. The strategy never commands the regen path, so the
exclusion holds by construction. The prediction model nevertheless applies
`charge_path_owns_bt=True` on a predicted charge stage, which is what reproduces
the topology-pinned ratio wind-up onto `DROOP_R_MIN` recorded in campaign
20260901_080905.

---

## 2. Prediction model

### 2.1 Composition

The model reuses existing code and adds no second copy of any physical law that
is not equality-tested against its original. Table 2 lists the composition.

| Quantity | Origin | Form here |
|---|---|---|
| speed, acceleration, demand, bus voltage, source total, cruise | `gen_dp_ems_table.build_demand()` | scalar port, `build_demand()` |
| auxiliary load | `gen_dp_ems_table.scenario_drain_a()` | scalar port |
| charge admissibility | `gen_dp_ems_table.charge_mask()` | scalar port |
| pack and hydrogen step | `step_discharge()`, `step_charge()` | scalar ports |
| charger bus draw | `tools/charger_power.py` | imported verbatim |
| delivered share | `governor_model.GovernorModel` | imported verbatim |
| charge dwell latch | `SdpStrategy.charge_hold_status()` | re-implemented on imported constants |

`gen_dp_ems_table` imports numpy, and the decision path must not. Every function
in the first four rows is therefore re-expressed as scalar stdlib code, and
`tools/test_mpc_ems.py` asserts equality with the numpy original to 1e-12
relative, in both charger eras and on three registered scenarios. That test is
the mechanism that keeps the two from drifting. The pack constants are imported
from `hil_electrical`, which the dynamic-program generator also imports, so the
two models cannot be pointed at different batteries.

### 2.2 Control-independent precompute

The governor's load filter has weight 0.05 per 1 ms tick, so it retains
`0.95**1000` = 5.29e-23 of its state across one decision stage. The filtered
source total at the end of a stage therefore equals that stage's source total to
full double precision. The source total is set by the demand and not by the
split, so the filtered total, the open/closed mode and the minority clip bound
are functions of the preview alone (candidate_opus Property A).

`precompute_stages()` computes them once per decision, at the preview's 0.1 s
resolution, carrying the firmware's own hysteresis forward: entry above 0.60 A,
release below 0.55 A, and a minimum-load freeze below 0.075 A. It also marks
each stage that contains a mode change as a transition stage.

The test suite scores the resulting classification against a full 1 kHz
`GovernorModel` roll on randomised synthetic profiles and requires agreement on
at least 95 % of stages. Candidate_opus measured 240 of 240 on its own set; a
stage that straddles the hysteresis is genuinely ambiguous, so the acceptance
here is a band rather than an equality.

### 2.3 Closed-stage surrogate

On a closed-loop stage the delivered share is the minority-governor clip of the
command, given by equation (3) with `lo = min(0.5, 0.30 / I_tot)`:

    d = clip(s, lo, 1 - lo)                                            (3)

Candidate_opus measured this surrogate against a full roll over 145 closed
stages at mean error 8.2e-04 and maximum 1.49e-02. This round reproduces the
band: over the closed stages of five synthetic profiles at five ladder points
the mean absolute error is below 5e-03, which the test asserts.

⚠️ No surrogate is written for the open-loop branch. Candidate_opus measured a
maximum error of 0.2484 for a feedforward surrogate and 0.3817 for a
hold-everything surrogate, every large error on a stage the firmware resolved as
`open_hold`. That branch is the one two earlier walks in this repository got
wrong, and section 2.4 is what replaces it.

### 2.4 Transition-stage exact rolls

Every previewed mode transition is rolled through the real `GovernorModel` at
1 kHz, once per ladder point, and the ratio standing at the stage end becomes
`r_hold` for that stage and that ladder point (candidate_fable section 2.2, item
2; adjudication section 2.1). Open stages carry the value.

The roll seeds the governor with the closed-loop delivered ratio for its ladder
point at the stage entry current, which encodes the assumption that the command
is held across the transition. The test suite reproduces one such roll
independently and requires bit-exact agreement.

The table is keyed on the ABSOLUTE preview sample of the stage start, not on the
horizon-relative index. The rolls are sliced across callbacks, so a table
computed at one decision may still be in use one or two decisions later, by
which time the horizon has receded. A relative key would then point silently at
the wrong stage.

The number of rolled transitions per decision is capped at four, which is the
adjudication's own arithmetic in section 2.1. A preview carrying more of them
has the first four rolled, which are the transitions nearest the present and
therefore the ones the executed first move depends on. A later transition
carries the standing ratio until the horizon recedes onto it.

⚠️ One roll table serves all charge candidates in a decision, and it is computed
against the most aggressive charge option. A decision that commits to a shorter
charge window therefore predicts its window-close transition on a stage the roll
placed elsewhere. The residual is bounded by the receding horizon and by the
commit state of section 2.5, and it is reported through `share_pred_err`.

### 2.5 Shadow governor

One `GovernorModel` is ticked at 1 kHz between 50 Hz feedback samples and
corrected from each sample. The shadow governor is the committed state, so the
controller's estimate of the governor is never surrogate-propagated across a
decision (adjudication section 2.1). Candidate_fable measured the cost at
3.3 ms per second of run; this round measures 2.761 microseconds per tick, which
is 2.76 ms per second of run.

⚠️ DEVIATION, STATED. The adjudication specifies correction of the applied ratio
from `governor_model.r_from_codes()` on the observed multiplying-DAC words. The
simulator's energy-management feedback view does not carry those two words. The
implementation uses them when a caller supplies `mdac_fc` and `mdac_bt`, and
otherwise corrects from the measured delivered share, which is
telemetry-equivalent and available. The measured split identifies the applied
ratio only where both channels conduct above the closed-loop entry threshold, so
the correction is skipped below it and the model keeps its own state. Adding the
two words to the feedback view is an additive registration step; see section 8,
item 4. Until it lands, the `mdac_corrections` counter reads zero.

### 2.6 Pack, demand and charger models

The pack model is the dynamic program's D6: the nine-point open-circuit-voltage
table at two cells, the state-of-charge dependent series resistance, one Picard
referral from bus power to pack current, and a coulomb count at 5.0 Ah. The
resistor-capacitor pair is not modelled, exactly as D6(b) states.

The charge step bills the fuel cell for the charger's bus draw through
`charger_power`, so the charger era is one switch in one place. The default is
the plant's own energy-conserving converter at `eta_chg` = 0.88.

⚠️ The demand model has NO REGEN TERM, inherited from `build_demand()`. Demand
is therefore over-stated on every decelerating stage and coasting is
under-valued. The live plant has injected regen since the WP-C round, so the
divergence is larger now than when the dynamic-program tables were generated.
The magnitude is unquantified and quantifying it is outside the scope of this
document.

### 2.7 The charger-era lever arithmetic

The implementation recomputes the levers from the solver's own algebra and pins
them in the test suite. The share lever is 0.4504505 SoC/g, the pre-change
charge lever is 0.2089864 SoC/g, and the post-change charge lever is
0.88 x 0.4504505 = 0.3963964 SoC/g. The `sdp_policy_v3` admission threshold is
0.3068192 SoC/g.

The post-change charge lever exceeds that threshold. Under the eta-era model the
charge action is therefore admitted even at `sdp_policy_v3`'s own alpha, which
both candidates found independently (adjudication section 1). A campaign run
before the charger change and one run after it are not comparable on hydrogen,
and `eta_chg` is recorded in the run provenance so a report can say so.

---

## 3. Optimizer

### 3.1 Structure

The optimiser is a move-blocked exhaustive search over candidate command
sequences, warm-started from the previous decision, with branch-and-bound
pruning and a hard time budget (adjudication section 2.3).

A state-space dynamic program was rejected on structure. Such a program would
need the governor's persistent state in the state vector, and quantizing the
standing ratio and the last acted setpoint gives 882 governor states. A
trajectory-based search carries the governor state exactly along each candidate
at no extra cost, because that state is a function of the candidate's own
history (candidate_opus section 3.1).

### 3.2 Control parametrization

The horizon is divided into blocks of 2, 6 and 12 stages, and the share command
is constant within a block. The block lengths are geometric because prediction
confidence decays with horizon index and only the first block is ever executed.

The share alphabet is a seven-point uniform ladder spanning the band of section
1.3. Seven points give a resolution of 0.0833, which is 121 mA of fuel-cell
current per step at the stimuli's drain-phase source total.

The charge axis carries three window candidates where the mask admits the first
stage: no charge, charge now for eight stages, and charge now until the
admissible segment ends (adjudication section 2.3). A window starting later in
the horizon is not enumerated, because the receding horizon re-evaluates "start
now" every second. While a dwell latch is in force the charge stages are fixed
by the latch and only the latched prefix is solved.

The candidate count is therefore 343 share sequences times up to three charge
options, that is at most 1029 sequences per decision.

### 3.3 Search, warm start and ties

Candidates are enumerated outward in ladder distance from the incumbent, so the
search is anytime. Abandoning it at any point returns a feasible command that
was validated one second earlier. Candidates whose partial cost already exceeds
the incumbent's total are abandoned mid-rollout, which is sound because the
stage cost is non-negative and the terminal term is bounded below by zero.

⚠️ The shift is degenerate under a fixed block partition. The incumbent sequence
shifted one stage carries the same three block values, so the shifted incumbent
and the incumbent are the same candidate. Warm start therefore means starting at
the previous decision's block indices, and the design's anytime property is
unaffected.

Ties resolve to the smaller share and to no charge, which is the dynamic
program's D8 rule. The no-charge option is enumerated first and a strict
improvement is required to displace it, so an indifferent state never charges by
accident.

### 3.4 The search model

`Planner.delivery_table()` builds, once per decision and per charge option, the
delivered share, the fuel-cell bus power, the battery bus power and the
feasibility flag for every (stage, ladder point) pair. A candidate rollout is
then a table lookup plus one pack step per stage. The table is what makes the
enumeration affordable, and it is the concrete form of the
precompute-then-surrogate ruling.

The pack referral is evaluated once per decision stage on the stage-mean battery
bus power, rather than ten times on the preview's own 0.1 s samples. The
hydrogen term is accumulated at the preview resolution. The difference is below
1e-06 of a stage's state-of-charge step and is stated rather than hidden.

---

## 4. Terminal cost

The terminal cost is a Huber penalty at the metric price, converted to the proxy
basis (adjudication section 2.4). Equation (4) gives it with
`delta` = 0.0015, which is `soc-band`'s own half-width:

    huber(D) = rho*D^2/(2*delta)  for |D| <= delta,  rho*(|D| - delta/2) otherwise  (4)

The Huber shape is candidate_fable's and exists because a purely linear price is
bang-bang about the target at 1 Hz. The price is candidate_opus's, because the
suite scores every leg on equivalent hydrogen at 0.41 SoC/g and a controller
whose internal price differs from the metric's exchange rate optimises a
different objective than it is scored on.

Three price modes are selectable and are recorded in the provenance:

- `metric`, the default, at `1.1811885 / 0.41` = 2.880948 g/SoC in proxy grams;
- `sdp-shadow`, at `kappa * alpha / (1 - gamma)` = 4.793012 g/SoC, with
  `kappa` = 1.4705882 converting the solver's bus-side basis to the stack-side
  proxy;
- an explicit value.

The reference is the run's captured initial state of charge, offset by
`soc_ref_offset`, which is the convention `SdpStrategy` already uses.

⚠️ The three candidate prices span 38 %. A result that is sensitive to which one
is used is a result about the price, not about the controller. The chosen value
belongs in every figure caption, and at least one offline sensitivity leg is
required before a campaign result is quoted.

The stochastic-dynamic-programming value function as a terminal cost is a
follow-on requiring a schema-additive solver change and is not in this round
(adjudication section 2.4).

---

## 5. Stochastic variant

`mpc-sto` replaces the exact preview with the transition-probability matrix's
conditional-mean demand path and tightens the fuel-cell overcurrent bound to the
90 % quantile of the k-step distribution (adjudication section 2.5). Nothing
else changes, so the variant is a strict information ablation of the
deterministic one.

The matrix is read directly from `TPM_dt1_hil.mat`. The shipped policy artifact
carries the matrix's path and SHA-256 but not its contents, and the solver's own
loader needs numpy and scipy. The file format admits a stdlib reader: the file
is a MAT-file 5.0 whose single element is a zlib-compressed real double array,
and `zlib` and `struct` are stdlib. `load_mat_doubles()` refuses anything it
does not understand rather than guessing, because a silent misparse of a
transition matrix would be invisible in every downstream number. The test suite
compares the reader against `scipy.io.loadmat` element for element at zero
tolerance, and pins the matrix's 25 bins, 211 non-zeros and 0.762 diagonal mass
against the provenance sidecar.

The demand axis map is the artifact's 0 to 25 W, so the stochastic variant and
`sdp-v3` classify a measured bus power into the same bin. The two clamp counters
are reported for the reason the SDP strategy reports them.

⚠️ Three limits stand. The matrix's shape is a vehicle's, not this rig's. Its
diagonal mass of 0.762 at 1 s makes short-horizon prediction close to a
persistence forecast, so a result resembling a hold-last-demand controller is a
property of the matrix. No simulator stimulus is a draw from the matrix, so a
live leg measures the loss of replacing an exact preview by a Markov mean on a
deterministic cycle.

The sampled scenario fan with common random numbers is not implemented in this
round; the adjudication makes it conditional on time.

---

## 6. Real-time architecture and measured cost

### 6.1 In-callback anytime search

The whole decision executes inside one 50 Hz command callback, with a hard
budget (adjudication section 2.2). No worker process is used. A multiprocessing
worker inside the 1 kHz simulator loop carries spawn re-import, contention with
the adaptive high-fidelity substeps, and pickling per decision, and the budget
arithmetic does not require it.

Budget expiry returns the incumbent and increments a counter, which appears in
the exit summary. The default budget is 12.0 ms.

### 6.2 Slicing

The transition rolls are computed control-independently once per decision and
sliced across callbacks at 2.0 ms per call. The search uses the previous
decision's roll table until the new one completes. The budget is checked after
an item, so the job always advances and cannot livelock. The test suite drives a
four-transition, seven-point job to completion within 50 callbacks.

### 6.3 Why a blocking solve is unacceptable

The simulator paces a 1 kHz loop and resynchronises rather than catching up
beyond 0.25 s of overrun. A host stall of 1 s is read by firmware v23 and later
as a run boundary and provokes a mid-run warm reset. A blocking half-second
solve therefore corrupts the run rather than merely slowing it.

### 6.4 Measured cost

The following were measured in this implementation round under
`.venv_hil/Scripts/python.exe`, CPython 3.14.5, on the operator's Windows host.

| Item | Measured |
|---|---|
| one `GovernorModel.step()` tick, closed-loop branch | 2.761 microseconds |
| one full 1 kHz roll of one 1 s stage | 2.761 ms |
| one control-independent precompute, 20 stages | 56.7 microseconds |
| one delivery table, 20 stages by 7 ladder points | 301 microseconds |
| one candidate rollout, 20 stages | 12.3 microseconds |
| one roll job, one transition, 7 ladder points | 19.2 ms |

Candidate_opus measured 2.721 microseconds for the governor tick, so the two
agree to 1.5 %.

Over a 61 s inline loop on the `ems-soc-band` stimulus at the 50 Hz command
rate, the deterministic variant makes 61 decisions at a median solve time of
4.6 ms and a maximum of 12.0 ms, with the maximum set by the budget. The
stochastic variant measures 4.5 ms median and 8.9 ms maximum. Budget expiry
occurred on 5 of 61 decisions for the deterministic variant and on none for the
stochastic variant. The largest single callback, including a roll slice, was
14.9 ms, which is inside the 20 ms command period.

### 6.5 Measured prediction accuracy

The delivered share predicted for the executed stage was compared against a full
1 kHz `GovernorModel` roll of the same committed command sequence, over the
whole `ems-soc-band` stimulus. The mean absolute error is 0.00384 over 61 stages
and the maximum is 0.16605.

The mean satisfies candidate_opus's Gate 1 band of 5e-03, which remains
PROVISIONAL until a governed walk measures it. The maximum sits in the open-loop
class the design predicts it would: 51.2 % of this stimulus's preview samples
carry a source total below the 0.55 A release threshold, so the commanded share
is inert over half the run.

---

## 7. Evaluation plan

### 7.1 Offline, before any board time

Three gates apply, in order, and none needs hardware.

Gate 1 is the surrogate acceptance test of section 6.5, repeated through
`ems_walk.walk(..., governor=True)` on `ems-sdp`, `ems-soc-band`,
`ems-ftp75-sdp` and `ems-ftp75-socband`. Acceptance is a mean absolute
delivered-share error at or below 5e-03 and an integrated hydrogen difference at
or below 1 % of the run total. Failure selects the fallback of rolling the full
governor on open stages with a reduced candidate set.

Gate 2 is the walk comparison against `soc-band`, `sdp-v3` and `dp-replay` on
the same scenarios and the same initial state of charge. Every leg is reported
as a hydrogen and delta-state-of-charge PAIR, never hydrogen alone, together
with the equivalent-hydrogen total. The prediction to state before running it is
that available headroom on `ems-sdp` is at most the 10 % by which `sdp-v3` beat
`soc-band` in campaign 20260901_024231, and realistically much less. A result
claiming more than the dynamic-program bound is a defect in the walk.

Gate 3 is the governor-hold audit. Any walk whose commanded share moved
materially inside a high-hold window is a walk whose commands were not acted on,
and its reported total is a property of the hold rather than of the policy.

⚠️ THE WALK CANNOT SCORE THE MPC. The controller's prediction model is the
walk's own plant, so a walk can only check that the strategy is plumbed and that
its plan is self-consistent. That is the inverse-crime condition, and
candidate_fable section 5.1 states it. The live campaign against the
high-fidelity plant is the evaluation.

### 7.2 Live scenarios

The first round registers three scenarios, each reusing an existing stimulus
object so that no new stimulus is validated at the same time as a new
controller: `ems-mpc` on the `ems-soc-band` profile and drain, `ems-ftp75-mpc`
behind `--with-ftp75` at preload 0.0, and `ems-mpc-cross` on the
`ems-sdp-cross` profile. `ems-mpc-sto` follows in the stochastic round.

⚠️ No braking stimulus is registered until the post-window prediction is
validated. `governor_model` states that `ems-sdp-braking` is outside its
licensed fidelity.

### 7.3 Expectation checks

Every check must be phase-free, because the decision timing is not phase-locked
to the stimulus and a phase-locked check has already failed a correct board.
The kinds already in `run_hil_suite.py` suffice: `min_value` and `max_value` on
the commanded share over the whole Run window, `max_continuous_ticks` on the
fuel-cell current above the margin, `edge_count_between` on the charge-goal
rising edge, `column_range_at_least` on the commanded share so a degenerate
constant cannot pass, `min_rows` to de-vacuate the window-scoped checks, and a
`min_value` on cumulative hydrogen.

All bands are PROVISIONAL on first registration, carry a `provisional_note`, and
are re-derived from the first campaign that evaluates them.

### 7.4 What the metric structurally cannot distinguish

Four limits belong in the report rather than being discovered afterwards.

1. The versus-bound arm is structurally near 1.0 for charge-free candidates.
   Campaign 20260901_080905 established that when a candidate and the bound
   differ only along the share lever, and the exchange rate IS that lever's
   rate, equivalent hydrogen makes the two coincide by construction. The arm
   detects lever-class deviations and does not measure optimality.
2. Preview and causality are not separated by the metric (section 1.2).
3. The metric cannot see the open-loop hold. Two controllers commanding
   different shares through a sub-0.55 A window deliver the same split. On
   `ems-soc-band` 51.2 % of the preview is below that line and on the FTP-75
   Run window the measured figure is 64.5 %, so a large fraction of each cycle
   is share-blind. An improvement confined to that region is unmeasurable, and a
   regression confined to it is equally invisible.
4. The controller minimises the proxy and is scored on the Gfc metric
   (section 1.1).

---

## 8. Registration: the step list for the next agent

Nothing below was done in this round. Each item is additive.

1. `tools/hil_plant_sim.py`, strategy registry. Add lazy proxies
   `EMS_STRATEGIES["mpc-det"]` and `EMS_STRATEGIES["mpc-sto"]` that import
   `mpc_ems` inside `bind_scenario()` and `__call__()`, so no import cycle and
   no import-time I/O is created. Use `mpc_ems.make_mpc(name)`. Add the matching
   `EMS_STRATEGY_META` entries with `policy_file` None for `mpc-det` and the
   matrix path for `mpc-sto`, and `frontier_eligible` True for `mpc-det`. The
   import-time assertion that pins the two key sets needs no change.
2. `tools/hil_plant_sim.py`, scenarios. Add `ems-mpc`, `ems-ftp75-mpc` and
   `ems-mpc-cross`, each sharing an existing stimulus object, declaring
   `chg_i_ceiling_a` 0.8, `aux_preload_a` 0.0 on the drive-cycle legs, and
   `electrical: "any"`. Add `ems-ftp75-mpc` to `FTP75_SCENARIOS`.
3. Drain whitelist. Add `ems-mpc` to `hil_plant_sim.apply_scenario()`'s
   SoC-band drain branch, to `gen_dp_ems_table.SOC_BAND_DRAIN_SCENARIOS`, and to
   `mpc_ems.SOC_BAND_DRAIN_SCENARIOS`. The B2 defect of 2026-09-01 was exactly
   this omission, and `tools/test_mpc_ems.py` already asserts the last two
   agree.
4. Feedback view. Add `mdac_fc` and `mdac_bt` to the MODE A `_fb()` builder from
   the observation frame, so the shadow governor's correction is the one the
   adjudication specifies (section 2.5 above). The strategy already consumes
   them when present, so the change is additive and needs no strategy edit.
5. CSV columns. Append `mpc_solve_ms`, `mpc_share_pred_err` and
   `mpc_budget_hit` AFTER `p_chg_loss_w`, read through `getattr` the way
   `cmd_share_sp_raw` is, blank for every other strategy. The strategy exposes
   `solve_ms_last`, `share_pred_err` and the per-decision budget flag.
6. Sidecar. Write `config.mpc` from the strategy's `provenance` attribute the
   way `config.sdp_policy` is written, and merge `MpcStrategy.timing()` into it
   at finalize.
7. Command-line flags. Add `--mpc-horizon`, `--mpc-share-band`,
   `--mpc-share-levels`, `--mpc-budget-ms`, `--mpc-roll-budget-ms`,
   `--mpc-terminal-price` and `--mpc-h2-map`, each defaulting to the value the
   constructor already defaults to, and each landing in the provenance.
8. `tools/ems_walk.py`. Add one branch to `_instantiate()` that re-instantiates
   `MpcStrategy` rather than reusing the registry singleton, for the reason that
   function documents.
9. `tools/run_hil_suite.py`. Add the `FAULT_EXPECTATIONS` entries of section
   7.3 with `provisional_note` on every band, and the `EMS_FRONTIERS` tuples
   `cycle61-mpc` and `ftp75-mpc` with the sibling tuples' provisional values and
   `stimulus_mismatch_exit_affecting` False for one campaign.
10. Prefill `tools/dp_db/` for the new scenarios, the FTP-75 leg first because
    its matched solve takes tens of minutes and must not run during a campaign.
11. Run Gates 1 to 3 of section 7.1, record the measured bands in the module
    docstring in the style `governor_model.py` uses, then run one supervised
    campaign and de-provisionalise the bands from it.

---

## 9. Deviations from the adjudication

Three items were not implemented exactly as ruled, and each is recorded at its
site in the code as well as here.

1. The multiplying-DAC correction of the shadow governor falls back to the
   measured delivered share, because the feedback view does not carry the two
   words. Section 2.5 states the fallback and section 8 item 4 is the fix.
2. One transition-roll table serves all charge candidates of a decision and is
   computed against the most aggressive charge option. Section 2.4 states the
   residual.
3. The transition rolls are capped at four per decision. The adjudication's own
   arithmetic assumes at most four, so the cap makes the slice bound structural
   rather than an assumption about the preview. Section 2.4 states what a
   dropped transition costs.

---

## 10. Risks

1. The surrogate misprices open-loop stages. The measured maximum error is
   0.16605 in delivered share on `ems-soc-band`, and 51.2 % of that stimulus
   sits in the open-loop regime. Mitigations are Gate 1, the per-decision commit
   state, and the fallback of rolling the full governor on open stages.
2. The terminal price is a choice spanning 38 % across its three candidates
   (section 4).
3. The charger-efficiency change moves the charge lever across the SDP's
   admission threshold, so every pre-change campaign's charge behaviour is
   incomparable (section 2.7).
4. The demand model has no regen term (section 2.6).
5. Preview is not causality (section 1.2).
6. The transition-probability matrix is a vehicle's (section 5).

---

## 11. Reversal path

The change is one commit. `tools/mpc_ems.py` and `tools/test_mpc_ems.py` are new
files with no importer outside the registration of section 8, and every
registration item is an additive entry in a registry, a scenario dictionary, an
expectation table, a frontier list, a set of appended columns or a set of
flags with inert defaults. No firmware, wire protocol, artifact, table or
existing constant is touched, so the reverse leaves every earlier campaign's
comparability intact.
