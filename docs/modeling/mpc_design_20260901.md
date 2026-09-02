# Governor-aware model-predictive energy management: the implemented design

This document records the design as implemented in `tools/mpc_ems.py`, with the
host-native test suite in `tools/test_mpc_ems.py`. It is written from the
adjudication in `docs/modeling/mpc_design_20260901/adjudication.md`, which is
binding. Each ruling below cites the adjudication section that fixed it, and
each measured number cites the candidate that measured it. Numbers measured in
this implementation round are marked as such and were taken on the host named in
section 6.4.

The strategy is REGISTERED as of 2026-09-02. Section 8 was the registration
step list and now records where each item landed, what deviated from it, and the
two offline gates that were run.

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

The decisions LAND at 1.02 s, not at 1.00 s. The next decision instant is
anchored on the call that served the last one, so a late call cannot accumulate
a backlog of missed stages to fire back to back, and the commands are issued on
a 50 Hz grid whose first sample at or after 1.00 s is 1.02 s. `SdpStrategy` has
the same clock and the same 2 % slip, so the two strategies remain comparable on
it. The slip is why the roll table is keyed on the decision grid rather than on
the preview grid; see section 2.4.

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
| pack and hydrogen step | `_dp_step_discharge()`, `_dp_step_charge()` | scalar ports |
| charger bus draw | `tools/charger_power.py` | imported verbatim |
| delivered share | `governor_model.GovernorModel` | imported verbatim |
| charge dwell latch | `SdpStrategy.charge_hold_status()` | re-implemented on imported constants |

`gen_dp_ems_table` imports numpy, and the decision path must not. Every function
in the first four rows is therefore re-expressed as scalar stdlib code, and
`tools/test_mpc_ems.py` asserts equality with the numpy original to 1e-12
relative, in both charger eras and on three registered scenarios. That test is
the mechanism that keeps the two from drifting.

⚠️ THE DRIFT GUARD RUNS ONLY UNDER AN INTERPRETER THAT HAS NUMPY. The equality
tests import `gen_dp_ems_table` and SKIP when that import fails, so the suite run
under `.venv_hil` reports four skips and passes. A change to either model must be
checked under miniforge, where the four equality tests actually execute. The
stdlib run alone does not establish that the two models still agree. The pack constants are imported
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

A stage qualifies as a transition on any of FOUR classes: the 0.60 A upward
crossing, the 0.55 A downward crossing, and a charge window opening or closing.
The charge pair reaches the classifier two ways, and both are needed. The
PREVIEW's own `chg_ok` edges enter `precompute_stages()`, because a window that
the mask opens or closes takes the battery off or back onto the bus; and the
CHARGE OPTION's own edges enter `RollJob`, because a candidate that charges for
eight stages moves the battery at stage 8 whatever the mask says beyond it.

The roll seeds the governor with the closed-loop delivered ratio for its ladder
point at the stage entry current, which encodes the assumption that the command
is held across the transition. It also seeds `closed_loop_run`, the flag that
makes the firmware's open-loop branch HOLD a converged split instead of slewing
the multiplying DACs toward the setpoint. That flag is STICKY: a closed-loop run
sets it and only a setpoint change clears it, so under the roll's own held-
command assumption it never clears, and `run_entry` carries it. Seeding it from
the stage's OWN opening mode instead made every roll of an already-open stage
take the feedforward branch and return the commanded share, which is a slew the
firmware does not perform. The test suite reproduces one such roll independently
and requires bit-exact agreement.

The table is keyed on the ABSOLUTE stage index on the DECISION grid, not on the
horizon-relative index and not on the preview sample. The rolls are sliced across
callbacks, so a table computed at one decision may still be in use one or two
decisions later, by which time the horizon has receded, and a relative key would
then point silently at the wrong stage. A PREVIEW-SAMPLE key, which is what the
first implementation used, fails for a second reason: the decisions land at
1.02 s (section 1.1) while the preview grid is 0.1 s, so the preview index of a
horizon start advances by 9, 10 or 11 samples and a table written at one decision
missed the next decision's keys on two of the three deltas. The measured lookup
hit rate was 5.39 % against the 8.05 % the transition census allows; keying on
the stage's own start time recovers the difference.

The number of rolled transitions per decision is capped at four, which is the
adjudication's own arithmetic in section 2.1. A preview carrying more of them
has the first four rolled, which are the transitions nearest the present and
therefore the ones the executed first move depends on. A later transition
carries the standing ratio until the horizon recedes onto it.

The cap does not bind on the registered stimulus. Over the 61 decisions of
`ems-soc-band` the census counts 1.75 transition stages per horizon and a
maximum of 3, of which 61 are governor-class crossings and 46 are charge-mask
edges; no decision reaches the cap, so nothing is dropped. The `dropped`
count is nevertheless reported per run, because a stimulus with a faster share
authority would reach it silently otherwise.

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
1.3. Seven points give a resolution of 0.0833, which is 117 mA of fuel-cell
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

`load_tpm()` also makes the two checks `sdp_ems_solver.load_tpm()` makes, at the
solver's own tolerances: every row sums to 1 within 1e-9, and no entry is below
-1e-15. A matrix failing either is not a transition matrix, and the forecast
built from one is a number with no meaning.

The demand axis map and the bin edges are READ from the shipped policy artifact
(`normalization.p_dem_min_w`, `normalization.p_dem_max_w` and
`demand_bins.edges` of `sdp_policy_v3.json`), so the stochastic variant and
`sdp-v3` classify a measured bus power into the same bin by construction rather
than by coincidence. The module's own 0 to 25 W is the ASSERTION the loader makes
against the file: an artifact that moved the map is refused, because the measured
figures in this document were taken against that map. The artifact's
`demand_map_source` string is carried into the provenance block. The two clamp
counters are reported for the reason the SDP strategy reports them.

While a charge hold is in force the measured demand has the strategy's OWN
charger draw subtracted from it, `V_bus * I_charge`, floored at the map's own
minimum. This is `SdpStrategy`'s self-load subtraction term for term, and it
exists for the reason campaign 20260901_000816 found: a policy that reads its own
charger as demand forecasts the demand its own decision created.

### 5.1 The transition matrix on THIS stimulus

The 0.762 diagonal mass quoted for the matrix is OCCUPANCY-WEIGHTED over the
vehicle log the matrix was fitted on, and the registered stimulus does not sit
where that mass is. On `ems-soc-band` the modal demand bin is bin 23, which holds
250 of the 611 preview samples, and that bin's self-transition probability is
EXACTLY zero. One step from bin 23 the conditional mean falls from the bin centre
of 23.5 W to 21.5 W.

The consequence is stated rather than mitigated: `mpc-sto` systematically
UNDER-predicts this stimulus's cruise demand, by about 2 W on the first step. A
`mpc-sto` leg that under-charges relative to `mpc-det` is therefore expected, and
is a property of the matrix rather than of the horizon. The test suite pins the
modal bin, its occupancy and its zero self-transition, so a re-fitted matrix
cannot move them silently.

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
the exit summary. The default budget is 10.0 ms; section 6.4 derives it.

⚠️ A WALL-CLOCK BUDGET MAKES THE TRAJECTORY HOST-DEPENDENT. The search is cut by
a `perf_counter()` reading, so the same command line on a slower machine can cut
at a different candidate and commit a different share. An MPC leg must therefore
NEVER be cited in a repeatability ledger the way the bit-exact `scp` cut current
or the `ems-sdp` hydrogen total are cited, and a bit-difference between two MPC
runs of the same command is not by itself evidence of a defect. The deterministic
secondary cap `max_candidates` exists for a campaign leg that needs
reproducibility: with it set, the search stops at a fixed candidate count and the
wall-clock budget only ever fires as the safety net it was meant to be. The
per-decision candidate count is reported next to the expiry counter, so a reader
can tell a search that finished from one that was cut, and by which cap.

### 6.2 Slicing

The transition rolls are computed control-independently once per decision and
sliced across callbacks at 2.0 ms per call. The slice runs in the 50 Hz command
callback, ahead of the decision gate; the decision path only CREATES the job. The
search uses the previous decision's roll table until the new one completes.

The budget is checked after a CHUNK of 100 governor ticks, not after a whole
1 s roll. One roll is 1000 ticks and costs 2.554 ms, so a per-item check overran
a 2.0 ms slice by more than the slice itself and the callback bound derived from
it was not a bound. The measured worst slice at a 2.0 ms budget is 2.296 ms, an
overshoot of one chunk. Progress is still guaranteed: at least one chunk runs per
call, so a zero budget advances and the job cannot livelock.

The completed table is published by MERGE, and only keys whose absolute stage has
receded past the job's own horizon start are dropped. Both halves are load
bearing. A replacement wipes the standing table whenever the completed job
carried no items, which happens whenever the horizon holds no transition; a merge
without the prune grows without bound over a run.

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
| one `GovernorModel.step()` tick, closed-loop branch | 2.694 microseconds |
| one full 1 kHz roll of one 1 s stage | 2.554 ms |
| one control-independent precompute, 20 stages | 56.7 microseconds |
| one delivery table, 20 stages by 7 ladder points | 301 microseconds |
| one candidate rollout, 20 stages | 12.3 microseconds |
| one roll slice at the 2.0 ms budget, worst | 2.296 ms |
| the 50 Hz surface's own work on a decision callback | 0.17 ms |

Candidate_opus measured 2.721 microseconds for the governor tick, so the two
agree to 1.0 %.

Over a 61 s inline loop on the `ems-soc-band` stimulus at the 50 Hz command
rate, the deterministic variant makes 61 decisions at a median solve time of
4.63 ms and a maximum of 10.01 ms, the maximum set by the budget. The stochastic
variant measures 4.58 ms median and 9.15 ms maximum. Budget expiry occurred on
4 of 61 decisions for the deterministic variant and on none for the stochastic
variant. The largest single callback observed was 10.18 ms for the deterministic
variant and 9.69 ms for the stochastic one.

THE CALLBACK BOUND is not that observation, because on this stimulus every roll
job completes before the next decision and the two costs never coincide. The
bound is their sum, and each term is measured: 10.01 ms of solve, 2.296 ms of
roll slice, and 0.17 ms of surface work, which is 12.5 ms against the 20 ms
command period. That arithmetic is why the default budget is 10.0 ms rather than
the 12.0 ms of the first implementation. Lowering it costs nothing in search
depth on this stimulus, since budget expiry stands at 4 of 61 decisions at either
value, and it buys 2 ms of margin. The per-item roll granularity of the first
implementation made the same arithmetic read 10.01 + 5.32 + 0.17, because the
slice could overrun by a whole 2.554 ms roll rather than by a 0.27 ms chunk.

The search evaluates 343 candidates per charge option, which is the full ladder
cube for seven levels and three move blocks; on the registered stimulus the
minimum over the run is also 343, so the enumeration completes on every decision
that does not expire.

### 6.5 Measured prediction accuracy

The delivered share predicted for the executed stage was compared against a full
1 kHz `GovernorModel` roll of the same committed command sequence, over the whole
`ems-soc-band` stimulus. The prediction is a STAGE-MEAN delivered share, so it is
scored against the mean of the samples accumulated across the stage rather than
against whichever 20 ms sample the next decision lands on.

| Configuration | mean | max | worst stage's mode |
|---|---|---|---|
| roll table never consulted | 0.00390 | 0.16667 | `open_feedforward` |
| roll table consulted, mis-seeded hold flag | 0.00562 | 0.25000 | `open_feedforward` |
| roll table consulted, as shipped | 0.00971 | 0.25000 | `open_feedforward` |

The per-mode census of the shipped configuration is 30 closed stages at a mean of
0.00308, 13 `open_hold` stages at exactly zero, and 18 `open_feedforward` stages
at a mean of 0.02776. The roll table is now actually present when it is
consulted: it holds 10.4 entries on the average decision, at most 21, and is
empty on 1 of the 61 decisions, against 38 of 61 empty before the review. The
stochastic variant measures 0.00595 mean and 0.16133 maximum on the same
comparison, which is LOWER than the deterministic variant's - it commands a
smoother share sequence because its conditional-mean demand path is smoother,
not because it predicts the governor better. Every stage of the error is in the open-loop class the
design predicts it would be in: 50.6 % of this stimulus's preview samples carry a
source total below the 0.55 A release threshold, so the commanded share is inert
over half the run.

⚠️ THE SHIPPED CONFIGURATION FAILS candidate_opus's Gate 1 band of 5e-03, and the
first row of that table is the number the first implementation reported. That row
was measured on a controller whose roll table was never consulted, because the
slice ran once per decision instead of once per callback and the table was
overwritten empty; the review of 2026-09-02 established that a mutation removing
the table entirely left the whole suite green. With the table live and the
governor's hold flag seeded faithfully, the same measurement reads 0.00971.

The mechanism is stated rather than tuned away. The open-stage surrogate models a
HOLD: it carries the standing ratio, and the roll that produces that ratio itself
assumes the command is held across the transition. The firmware's open-loop
branch holds only while the setpoint does not change, and a receding-horizon
controller re-commands every 1.02 s. Each re-command that lands in an open stage
drops the governor out of hold into a feedforward slew that neither the surrogate
nor the roll represents, and those are exactly the 18 stages carrying the error.
The table's value is therefore not established on this stimulus, and no claim is
made for it. Two consequences follow. First, Gate 1 is now a FAILING gate, and
the fallback it selects is the one the design already names: roll the full
governor on open stages with a reduced candidate set. Second, the fallback should
be evaluated against a fourth configuration, an open-stage model that slews the
carried ratio toward the commanded share when the command has changed, which is
cheaper than a full roll and addresses the measured class directly. Neither is in
this round.

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
   `ems-soc-band` 50.6 % of the preview is below that line and on the FTP-75
   Run window the measured figure is 64.5 %, so a large fraction of each cycle
   is share-blind. An improvement confined to that region is unmeasurable, and a
   regression confined to it is equally invisible.
4. The controller minimises the proxy and is scored on the Gfc metric
   (section 1.1).

---

## 8. Registration: the step list for the next agent

**STATUS: items 1 to 10 are DONE (2026-09-02); item 11 is partly done.** Each
item below carries the `file:line` of its registration. Line numbers are as of
the registration commit and are a starting point, not an anchor; the symbol
names beside them are the anchor.

| item | where | note |
|---|---|---|
| 1 strategy registry | `tools/hil_plant_sim.py:6018` `_MpcProxy`, `:6122` the two instances, `:6256` `EMS_STRATEGIES`, `:6397` `EMS_STRATEGY_META` | lazy proxy, no import cycle, no import-time I/O |
| 2 scenarios | `:8211` `ems-mpc`, `:8228` `ems-mpc-sto`, `:8243` `ems-mpc-cross`, `:7579` `ems-ftp75-mpc`; `tools/run_hil_suite.py:342` `FTP75_SCENARIOS` | `ems-mpc-sto` added beyond the item's three |
| 3 drain whitelist | `tools/hil_plant_sim.py:7326`, `tools/gen_dp_ems_table.py:500`, `tools/ems_walk.py:203` | all three mirrors carry `ems-mpc` / `ems-mpc-sto`; `tools/mpc_ems.py:363` was extended by the concurrent review round |
| 4 feedback view | `tools/hil_plant_sim.py:10695` | `mdac_fc` / `mdac_bt` added to `_fb()` |
| 5 CSV columns | `:10078` header, `:10819` row | after `p_chg_loss_w`, blank elsewhere and on replay |
| 6 sidecar | `:10303` `config.mpc`, `:10377` the `timing()` merge at finalize | |
| 7 command-line flags | `:9280` onward, resolved by `mpc_configure_kwargs()` at `:6142` | all default to None, i.e. to the constructor's own value; `--mpc-max-candidates` added beyond the item's seven |
| 8 `ems_walk._instantiate()` | `tools/ems_walk.py:297` | re-instantiates through `mpc_ems.make_mpc()` |
| 9 suite expectations | `tools/run_hil_suite.py:3702` `_mpc_expectation()` and the four entries below it; `:8043` `cycle61-mpc`, `ftp75-mpc` | every band carries a `provisional_note` |
| 10 `dp_db` prefill | `ems-mpc` stored at the Gate-2 terminal SoC; `ems-mpc-cross` stored; the FTP-75 leg is **pending** | see below |
| 11 gates + campaign | Gates 2 and 3 run (the table below); Gate 1 and the supervised campaign are **not** done | |

**Deviations, each with its reason.**

1. **The third drain mirror was extended by another agent.** This round was forbidden to edit `tools/mpc_ems.py` while a concurrent review round held it, so it extended only `hil_plant_sim`, `gen_dp_ems_table` and `ems_walk` and reported the third as required. That review round then added the two names at `tools/mpc_ems.py:363`, so the mirror assertion in `tools/test_mpc_ems.py` holds. `ems-mpc-cross` is deliberately absent from all four, exactly as `ems-sdp-cross` is.
2. **`max_continuous_ticks` on a current threshold is not expressible.** Section
   7.3 asks for it on the fuel-cell current above the margin, but that kind
   needs a switch bit, an aux bit or a masked integer — the suite has no
   numeric-threshold run kind. A `max_value` ceiling at the planner's own
   1.19 A margin expresses the same budget claim; adding a check kind was out of
   scope for a registration round.
3. **`edge_count_between` is asserted on `SW_FC_CHARGE`, not on the
   `charge_goal` column,** for the same reason: the kind counts transitions of a
   bit. The switch is the board-side manifestation of the charge intent.
4. **The prediction-error ceilings are 0.30, not 0.10.** The walk measures peaks
   of 0.209, 0.168, 0.168 and 0.186 across the four legs. The walk's feedback
   view carries no MDAC words, so its shadow governor is corrected only from the
   measured current split, which identifies the applied ratio only above the
   0.60 A closed-loop gate; a campaign feeds `mdac_fc`/`mdac_bt` (item 4) and
   should read lower. One uniform ceiling on the conservative side, tightened
   onto the first measurement.
5. **Gate 1 FAILS offline, and the round shipped with that recorded.** With
   the governor roll table actually consulted, the surrogate's
   delivered-share error on the `ems-soc-band` stimulus is mean 0.0097 and
   max 0.25000, against section 7.1's 5e-03 acceptance. The worst stages are
   `open_feedforward`: every 1 Hz re-command that lands in an open-loop stage
   triggers a governor feedforward slew that neither model represents. The
   suite's `mpc_share_pred_err` ceiling is 0.30, a first-registration band
   derived from that offline measurement rather than a widened pin, and the
   first campaign is its calibration reading. Section 7.1's stated fallback —
   rolling the full governor on open stages with a reduced candidate set — is
   the decision that reading informs. A mean-side bound would be the better
   assertion (the mean is 26x under the max) but `run_hil_suite.py` has no
   column-mean check kind, and a registration round is not where one is added.
6. **The four legs declare a deterministic candidate cap.** Each carries
   `mpc_max_candidates` = `hil_plant_sim.MPC_CAMPAIGN_MAX_CANDIDATES` = 343,
   which is 7**3 — the FULL enumeration at the shipped ladder and move-block
   structure, so the cap removes the wall clock's influence on the candidate
   count without removing a single candidate. `ems_walk._instantiate()`
   applies the same scenario key, so the Gate-2 table above is walked under
   the campaign's own search bound. It does NOT make an MPC run
   bit-reproducible: the roll-table slicing is still wall-clock bounded (that
   is what the `ems-mpc-cross` −21 % figure above measures) and so is the
   board.
7. **No `dp_db` entry is prefilled for `ems-ftp75-mpc`.** Its matched solve is a
   job of tens of minutes and the FTP-75 bound leg's own table is stale, so the
   entry is deferred rather than stored against a stimulus that is about to be
   regenerated.

**Gate 2 (`ems_walk.walk(..., governor=True, dv0_v=0.030223)`, soc0 0.7,
2026-09-02, three repeats per leg reproducing to six decimals).** The walk's
plant IS the controller's prediction model, so these numbers show the plumbing
works and the plan is self-consistent; they do not score the controller
(section 7.1).

| leg | strategy | h2 (g) | ΔSoC | eq-H2 (λ 0.41) | open-hold | share range |
|---|---|---|---|---|---|---|
| `ems-soc-band` | `soc-band` | 0.012264 | −0.002002 | 0.017146 | 0.118 | 0.250 |
| `ems-dp-replay` | `dp-replay` | 0.011900 | −0.001936 | 0.016622 | 0.000 | 0.500 |
| `ems-sdp` | `sdp-v4` | 0.012729 | −0.001600 | 0.016631 | 0.338 | 0.000 |
| `ems-mpc` | `mpc-det` | 0.010429 | −0.002537 | 0.016616 | 0.223 | 0.417 |
| `ems-mpc-sto` | `mpc-sto` | 0.009313 | −0.002998 | 0.016625 | 0.338 | 0.333 |
| `ems-mpc-cross` | `mpc-det` | 0.014134 | −0.006007 | 0.028786 | 0.629 | 0.250 |
| `ems-ftp75-socband` | `soc-band` | 0.041873 | −0.006306 | 0.057254 | 0.097 | 0.250 |
| `ems-ftp75-sdp` | `sdp-v4` | 0.019918 | −0.014691 | 0.055750 | 0.097 | 0.700 |
| `ems-ftp75-mpc` | `mpc-det` | 0.023771 | −0.013112 | 0.055751 | 0.020 | 0.333 |
| `ems-ftp75-dp` | `dp-replay` | — | — | — | — | — |

`cycle61-mpc` reads vs_reference **0.9691** and vs_bound **0.9996**; `ftp75-mpc`
reads vs_reference **0.9738** and has no vs_bound prediction, because the shipped
`dp_ems_table_ems-ftp75-dp.csv` carries a stale stimulus fingerprint and refuses
to walk until it is regenerated. The prediction of section 7.1 held: the
available headroom is small, and the vs-bound arm sits where section 7.4.1 says
a charge-free candidate's arm sits.

**The pair is the result, and the hydrogen alone is not.** Three repeats of each
walk reproduce the totals above to six decimals, but raising the search budget
from the shipped 12 ms to 1e5 ms moves `ems-mpc-cross`'s hydrogen by −21 %
(0.014134 → 0.011163) while its equivalent hydrogen moves by 0.13 % (0.028786 →
0.028750). A deeper search buys hydrogen with state of charge. Every
`h2_cum_g` band in the suite is therefore a scale and accumulation tripwire; the
equivalent-hydrogen total is the search-invariant quantity, and the frontier
check computes it across runs rather than per run.

The same effect separates the two variants on one stimulus. `mpc-sto`'s pair on
`ems-mpc-sto` differs from `mpc-det`'s on `ems-mpc` — 0.009313 / −0.002998
against 0.010429 / −0.002537 — while the two equivalent totals agree to 0.05 %.
The certainty-equivalent demand path and the 90 % overcurrent quantile move the
plan along the share lever without moving its value, which is the expected
outcome on a stimulus that is not a draw from the matrix.

The ΔSoC-matched dynamic-programming bound for `ems-mpc` at the walk's own
terminal state is **0.010418 g** (`tools/dp_db`, key `62151bd59b9cd787`) against
the walk's 0.010429 g — 0.10 % above the bound, which is the consistency check a
plan is allowed to pass, and not a result about the controller. The
`ems-mpc-cross` entry is stored at key `e9d9c021b52e763a`.

**Gate 3, the governor-hold audit.** The open-hold column above is the fraction
of each walk spent below the firmware's 0.55 A open-loop drop-out, where the
commanded share is not acted on. Read it as a caveat on each leg, not as a
score: `ems-mpc-cross` at **0.629** is two thirds share-blind, so an improvement
or a regression confined to that region is invisible to any metric
(section 7.4.3). ⚠️ The two 61 s legs differ materially on that line — 0.223 for
`mpc-det` against 0.338 for `mpc-sto` on the identical cycle — because the two
plans command different splits at the same demand. The two runs are
therefore not interchangeable evidence about the governor, and a comparison of
their share-tracking quality is not a comparison of the same experiment.

Nothing below was done in the round that wrote this document. Each item is
additive.

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

Six items are not implemented exactly as ruled, and each is recorded at its site
in the code as well as here.

1. The multiplying-DAC correction of the shadow governor falls back to the
   measured delivered share, because the feedback view does not carry the two
   words. Section 2.5 states the fallback and section 8 item 4 is the fix.
2. One transition-roll table serves all charge candidates of a decision and is
   computed against the most aggressive charge option. Section 2.4 states the
   residual.
3. The transition rolls are capped at four per decision. The adjudication's own
   arithmetic assumes at most four, so the cap makes the slice bound structural
   rather than an assumption about the preview. The cap DOES NOT BIND on the
   registered stimulus: over the 61 decisions of `ems-soc-band` the maximum is
   3 transition stages per horizon and the mean is 1.75, of which 61 are
   governor-class crossings and 46 are charge-mask edges, so no decision drops
   anything. The dropped count is reported per run all the same.
4. The default decision budget is 10.0 ms, not the 12.0 ms of the first
   implementation, and the roll slice is checked at a 100-tick chunk rather than
   between whole rolls. Both changes follow from the callback arithmetic of
   section 6.4, which the per-roll granularity made unsound.
5. The search accepts a deterministic secondary cap, `max_candidates`, which the
   adjudication does not specify. A wall-clock budget alone makes the committed
   trajectory host-dependent; section 6.1 states the consequence for a
   repeatability ledger and the cap is what a campaign leg sets to avoid it.
   The default is no cap, so an untouched command line is the adjudicated
   search.
6. THE PREDICTION MODEL DOES NOT MEET GATE 1. Section 6.5 gives the measurement,
   the mechanism and the two follow-ons. The adjudication's ruling stands - the
   transition rolls replace a hand-written open-loop surrogate - but the ruling's
   premise, that the roll removes the 0.2484 open-stage error class, is not
   confirmed on this stimulus, and the earlier measurement that appeared to
   confirm it was taken on a controller that never consulted the table.

### 9.1 What the review of 2026-09-02 changed

The review found four defects that the original suite could not see, and five
mutations that survived it. Recorded here because each changes a number this
document reports.

1. The roll slice ran on the 1 Hz decision path rather than the 50 Hz callback,
   so a job received one slice per decision. The table was empty on 38 of 61
   decisions.
2. A completed job with no items published an EMPTY table by replacement, wiping
   whatever stood.
3. `bind_scenario()` did not accept the hook's two trailing arguments, which
   `main()` passes by name. Registration would have raised `TypeError` before a
   frame was sent. The binder now also reads the run's `capacity_ah` and the
   scenario's `mpc_soc_ref_offset`.
4. The roll table was keyed on the preview grid while the decisions land on a
   1.02 s grid, so two of the three index deltas missed every key.

The five surviving mutations were: dropping the minority clip from the delivery
table, dropping the charger's bus power from the charge stage cost, flipping the
charge state-of-charge sign, never consulting the roll table, and zeroing the
terminal cost. Each now has a consumption test. The mutation battery run at the
close of the round covers fourteen mutations, including the four defects above,
and catches all fourteen.

---

## 10. Risks

1. The surrogate misprices open-loop stages, and this is now a MEASURED FAILURE
   rather than a risk. The mean absolute delivered-share error on `ems-soc-band`
   is 0.00971 against a Gate 1 band of 5e-03, the maximum is 0.25000, and
   50.6 % of that stimulus sits in the open-loop regime. Section 6.5 gives the
   mechanism: the surrogate and the roll both model a HOLD, and a re-command
   landing in an open stage produces a feedforward slew instead. The mitigations
   are the per-decision commit state and the fallback the design already names,
   rolling the full governor on open stages with a reduced candidate set.
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
