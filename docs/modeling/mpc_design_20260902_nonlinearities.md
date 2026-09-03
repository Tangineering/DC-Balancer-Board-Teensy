# Firmware nonlinearities between the MPC command and the delivered current

Date: 2026-09-02. Scope: `tools/mpc_ems.py`, the governor-aware model-predictive
energy-management strategy of `docs/modeling/mpc_design_20260901.md`.

This note enumerates every firmware nonlinearity that stands between the two
energy fields the strategy commands (`power_share_setpoint` and `charge_goal`)
and the currents the two channels deliver. For each item the note states whether
the prediction model already represents it, what it contributes to the Gate 1
delivered-share prediction error, and whether it belongs in the prediction model,
in the constraint set, or outside the scope of this strategy. The note also
records the two items implemented in the same round: the open-loop feedforward
submode (section 3) and, on a second operator ruling of the same date, the
adaptive solve budget and the transition-aware ladder coarsening (section 4).
Both are reported with their measurements.

The authority for every firmware constant quoted here is
`tools/governor_model.py`'s `GOV_CONST`, which cites `teensy_controller.ino` line
by line. No constant is re-typed in this note without that citation path.

---

## 1. The measurement

Gate 1 is the acceptance test of `mpc_design_20260901.md` section 7.1: the mean
absolute error between the delivered share the strategy predicts for the stage it
is about to command and the stage-mean share that is actually delivered, over the
`ems-soc-band` stimulus walk, at an acceptance of 5e-03. The metric is the
strategy's own `share_pred_err`, reported by `MpcStrategy.timing()`; the harness
is `ems_walk.walk(strategy, "ems-soc-band", soc0=0.7, governor=True)`, whose plant
is a full 1 kHz `GovernorModel` roll of the committed command sequence.

Table 1 gives the Gate 1 result before and after the change of section 3.

| plant | configuration | strategy | mean | maximum | verdict at 5e-03 |
|---|---|---|---|---|---|
| symmetric (`dv0` 0) | hold-only stage model (shipped 2026-09-01) | `mpc-det` | 0.010334 | 0.250000 | FAIL |
| symmetric | feedforward-aware stage model | `mpc-det` | **0.000095** | **0.003560** | **PASS** |
| symmetric | hold-only stage model | `mpc-sto` | 0.007071 | 0.166667 | FAIL |
| symmetric | feedforward-aware stage model | `mpc-sto` | **0.003931** | 0.117956 | **PASS** |
| measured (`dv0` 0.013522) | map inert | `mpc-det` | 0.016211 | 0.060578 | FAIL |
| measured | **map passed, as the campaign now passes it** | `mpc-det` | **0.000323** | **0.013752** | **PASS** |
| measured | map inert | `mpc-sto` | 0.019739 | 0.122043 | FAIL |
| measured | map passed | `mpc-sto` | 0.009019 | 0.118574 | **FAIL** |

The lower half of Table 1 is the configuration the campaign now runs.
`hil_plant_sim.resolve_asymmetry_dv0_v()` gives the run's own offset one owner
and `mpc_configure_kwargs()` passes it to the strategy, so `Planner`, the
`ShadowGovernor` and every `RollJob` carry the plant's `dv0`. On the measured
plant the deterministic variant passes with a 15x margin.

⚠️ **`mpc-sto` FAILS Gate 1 on the measured plant**, at a mean of 0.009019
against the 5e-03 band. The residual is not a delivery-model residual: it is one
`open_hold` stage carrying 0.117956, which is the same stage that carries the
symmetric plant's maximum of 0.117956, and it arises because the stochastic
variant classifies stage modes on the transition matrix's conditional-mean demand
rather than on the demand the plant delivers. A demand path that says a stage is
closed when the plant leaves it open puts a whole stage of commanded share into
the wrong arm. This is a stated limit of `mpc-sto` **on a deterministic
stimulus**, where its forecast has nothing to average over; no delivery model
removes it, and no stimulus drawn from the transition matrix is registered.

The `mpc-det` mean falls by a factor of 109 and the maximum by a factor of 70,
so BOTH now sit inside the 5e-03 acceptance rather than only the mean. The
design record's own figure for the first row is 0.00971 rather than 0.010334; the
search is wall-clock budgeted, so a walk on a different host explores a slightly
different candidate set. Every row of Table 1 was measured on one host in one
session, so the rows are comparable with each other.

Table 2 decomposes the same measurement by the governor mode that dominated the
scored stage.

| stage class | stages | mean before | mean after | maximum before | maximum after |
|---|---|---|---|---|---|
| `closed` | 30 | 0.004000 | 0.000022 | 0.120000 | 0.000655 |
| `open_feedforward` | 15 before, 28 after | 0.033333 | 0.000051 | 0.250000 | 0.001440 |
| `open_hold` | 15 before, 2 after | 0.000002 | 0.001796 | 0.000032 | 0.003560 |

Two readings follow. First, the whole of the previous error sat on
`open_feedforward` stages, exactly as the design record predicted. Second, the
stage-class census itself moves, because a controller with a better delivery model
commands a different sequence: the number of feedforward stages rises from 15 to
28 while their mean error falls by a factor of 654. The worst stage class is now
`open_hold`, at a mean of 0.001796 over two stages.

For `mpc-sto` the residual is not a delivery-model residual. Its per-mode census
after the change reads `closed` 31 stages at 0.003758 and one `open_hold` stage at
0.117956, against `open_feedforward` 28 stages at 0.000051 - the same figure the
deterministic variant reaches, so the feedforward model works equally well on
both and the residual is elsewhere. On the measured plant that residual is enough
to fail the gate outright (Table 1, last row); the mechanism and the reason no
delivery model removes it are stated under the table. The stochastic variant
replaces the previewed demand with the transition matrix's conditional mean, so
its stage-mode classification and its minority-clip bound are computed on a demand
path the plant does not follow. The residual is forecast error, and no delivery
model removes it.

---

## 2. The survey

Table 3 is the enumeration. "Represented" names the mechanism in `mpc_ems.py`
that carries the item, or states that none does.

| # | nonlinearity | represented? | measured contribution to Gate 1 | recommendation |
|---|---|---|---|---|
| 1 | Open-loop FEEDFORWARD slew, `DROOP_RATIO_SLEW_PER_TICK` 0.02/tick and `DROOP_RATIO_SLEW_HANDOFF_PER_TICK` 0.002/tick | **YES, new this round** — `delivery_table()`'s feedforward branch, integrated in closed form by `ramp_mean()` | the whole of the previous failure: mean 0.033333 and maximum 0.250000 over 15 stages, now 0.000051 and 0.001440 over 28 | prediction model. Implemented; section 3 |
| 2 | Open-loop HOLD, conditional on `shareClosedLoopRun`, `SHARE_SP_CHANGE_EPS` 1e-4 and no outstanding isolation | PARTLY — the hold arm models the first two conditions; `!(shareIsoFC \|\| shareIsoBT)` (.ino:10173) is NOT modelled, because an outstanding isolation is a consequence of a cut and the ladder band is chosen so that no candidate can cause one. Where one does arise the transition rolls carry the real flag, since they run the real `GovernorModel` | 0.001796 mean over 2 stages after the change; exactly zero before it, because the model assumed a hold everywhere | prediction model. The isolation condition stays out: adding it needs a seed the table has no source for, and the constraint of item 5 is what keeps it unreachable |
| 3 | Closed-loop minority clip `lo = min(0.5, 0.30/I_tot)` | YES — the algebraic surrogate, mechanism 3 | 0.000022 mean, 0.000655 maximum over 30 stages | prediction model. No further work indicated |
| 4 | Governor entry and release hysteresis, 0.60 A and 0.55 A, on a load filter of `SHARE_GOV_FILT_ALPHA` 0.05 per tick | YES — `precompute_stages()` classifies each sub-sample with the firmware's own hysteresis; the filter retains 5.29e-23 of its state across a 1 s stage, which is what makes the classification control-independent | not separable on this stimulus; the mode census matched a full roll on at least 95 % of stages in the standing property test | prediction model. Already there |
| 5 | Setpoint band `[DROOP_R_MIN 0.15, DROOP_R_MAX 0.85]`, the out-of-band setpoint latch and its cut-and-restore topology, the fw v25 share-cut load guard `SHARE_CUT_MAX_HANDOFF_A` 0.5 A, and the 30 ms survivor blanking | PARTLY — the ladder band `[0.25, 0.75]` places every candidate strictly inside the actuator band by construction, so no candidate can reach the latch. The feedforward branch additionally reproduces the F1 idle return for an out-of-band setpoint | zero on the shipped ladder. On the wider `SHARE_BAND_SDP` ladder `[0.15, 0.85]` Gate 1 reads 0.000272 mean and 0.012110 maximum, still inside the band and with no latch or cut fired | CONSTRAINT, and it already is one. Do not add the latch to the prediction model: the correct treatment of a mechanism that must never be reached is a constraint that keeps the search away from it, and a model of it would license candidates that reach it |
| 6 | Conduction-handoff slew mode and dwell, `SHARE_HANDOFF_MIN_A` 0.15 A, `SHARE_HANDOFF_LIVE_A` 0.20 A, `SHARE_HANDOFF_DWELL_MAX_TICKS` 175 | PARTLY — the transition rolls now seed the two channel filters and the two dark flags from the stage's entry currents and publish the dark state they ended in; the feedforward branch selects the slow ceiling on a flagged stage, and the 175-tick dwell allowance is modelled and spent on moving ticks, as the firmware spends it | the flag fires on 62 of 196 published roll entries and costs nothing (Gate 1 is 0.000095 with it consulted and 0.000095 with it ignored). BEFORE the seeding fix it fired on 104 of 196 and COST 0.000234. An instantaneous proxy for the dark flags was separately measured and REJECTED: 0.000315 against 0.000095 | prediction model, as implemented. Do not add the instantaneous proxy; see section 3.3 |
| 7 | Converter asymmetry (`dv0` 0.013522 V measured, `droop_scale_fc` 0.9434, `asymmetry` default-on since 2026-09-01) and 12-bit MDAC quantization of the `K_DROOP` code mapping | **YES for the asymmetry, since this round.** `Planner(dv0_v=...)` maps the open-loop applied ratio to a delivered share through `GovernorModel.delivered_share()`, and `hil_plant_sim.resolve_asymmetry_dv0_v()` through `mpc_configure_kwargs()` passes the run's own offset to it. Quantization is not modelled | It WAS the largest delivery error by two orders. On a walk whose plant carries the measured dv0 0.013522 V, Gate 1 reads 0.016211 mean and 0.060578 maximum with the map inert, against 0.000323 and 0.013752 with it passed, at a bit-identical committed trajectory. At the Gate 2 plant's dv0 0.030223 V the pair is 0.036175 against 0.000317, a factor of 114. Quantization contributes at most 4.3e-04 in delivered share at r = 0.75 and 7.8e-05 at r = 0.50 | DONE for the asymmetry. Quantization is OUT OF SCOPE at two orders below the band. ⚠️ A WALK still has to pass `dv0_v` itself: `ems_walk.walk()` builds the strategy from `strategy_kwargs` and does not consult `mpc_configure_kwargs()` |
| 8 | Charge-path exclusivity: `FC_CHARGE_ENABLE` requires `BT_BUS_ENABLE` off, so a charge window forces single-source FC and the bus sags (15.76 V to 14.15 V measured), raising the charger's bus draw; the 8 s SDP charge dwell; the Ag105 ramp `AG105_TAU_S` 0.4 s | MOSTLY — the charge branch pins the traction split at 1.0 and winds the ratio onto `DROOP_R_MIN`, the charge stage cost bills `charger_bus_power_w()` at the previewed bus voltage, a window edge is a transition class for the rolls, and `ChargeLatch` reproduces the dwell semantics with the SDP's own constants. The 0.4 s current ramp is NOT modelled | zero on this stimulus: the walk opened no charge window (`latch.holds` 0) | prediction model for the ramp, LATER. At a 1 s stage the ramp costs at most one stage's worth of a 0.4 s first-order rise, and no registered stimulus in the current Gate 1 exercises it. Re-measure on an FTP-75 leg, which does charge |
| 9 | Regen: the demand model has no regen term, and neither the VESC regen clip nor the braking chopper appears in it | NO — honest limit 1 of the module docstring | not measurable on Gate 1, which scores a delivered SHARE and not a demand. The error is in the DEMAND path and shows up in the hydrogen total, not in the share prediction | prediction model, but a separate round. Adding a regen term changes the demand model the DP bound is computed against, so the DP tables and the bound would have to move with it. Out of scope for a delivery-model round |
| 10 | The power-share PI transient and its `sampleTime` gating | YES, as a settled surrogate — the closed-stage arm predicts the converged clip and not the approach | 0.000022 mean over 30 closed stages after the change | prediction model. No further work indicated: the residual is four orders below the acceptance band |
| 11 | The `Gfc` dynamic map against the `eta_fc` 0.4 stage-cost proxy, a constant factor 1.1811885 | YES, as a documented constant, `PROXY_OVER_READ` | none: this is a COST nonlinearity, not a delivery one, and Gate 1 does not score it | prediction model, as is. The constant cancels in a ranking at matched terminal state of charge and does not cancel against the terminal price, which is why the terminal price is quoted in the proxy basis |

### 2.1 Ranking

The items are ranked by the Gate 1 error they remove, against the cost they add to
the decision callback (10 ms as this round opened; per-decision and adaptive as it
closed, section 4). The cost figures are the median build time of one
`delivery_table()`, measured over 200 builds of a 20-stage horizon at seven ladder
points; a decision builds at most three of them, one per charge option.

| rank | item | Gate 1 error removed | callback cost |
|---|---|---|---|
| 1 | 1 and 2, the two open-loop submodes | 0.010239 of 0.010334 | 0.516 ms to 0.675 ms per table, +0.159 ms, +31 % |
| 2 | 7, the asymmetry map (enabled this round) | 0.015888 of 0.016211 at the plant's own dv0 | 0.675 ms to 1.069 ms per table, +0.394 ms |
| 3 | 6, seeding the roll's own handoff state (section 3.4) | 0.000234 of 0.000329 | none: it is a change of seed, not of work |
| 4 | 8, the Ag105 ramp | unexercised on this stimulus | one first-order state per charge stage; negligible |
| 5 | 6, an instantaneous dark-flag proxy | NEGATIVE: it ADDS 0.000220 | measured; rejected |
| 6 | 7, MDAC quantization | at most 0.00043 | negligible |
| — | 9, a regen demand term | not scored by Gate 1 | out of scope; moves the DP bound |

---

## 3. The change made this round

### 3.1 What the firmware does

`governor_model._open_loop()` is a port of `.ino:10147-10213`. It holds the
standing split, writing nothing, only when all three of the following are true: a
closed-loop run stands (`shareClosedLoopRun`), the commanded setpoint is within
`SHARE_SP_CHANGE_EPS` of the setpoint last acted on (`share_actedSp`), and no
channel isolation is outstanding. On any other open tick the branch clears
`shareClosedLoopRun`, clips the commanded setpoint to the tick's slew ceiling
around the standing ratio, passes it to `applyShareRatio()`, which clips it again
to `[DROOP_R_MIN, DROOP_R_MAX]`, and writes both MDACs. `docs/HIL_PLANT.md`
section 4.4 records 356 such write ticks measured on `ems-y-b00-v3`, so this is
board behaviour and not a property of the model.

Two consequences drive the design. First, a receding-horizon controller
re-commands every stage, so a re-command that lands in an open stage always enters
the feedforward submode. Second, once the branch has fired,
`shareClosedLoopRun` is clear and every later open tick stays on the feedforward
branch until a closed-loop run re-arms the hold; the hold is not the default state
of an open stage but the state that follows a converged closed-loop run under an
unchanged command.

### 3.2 What the model does

`Planner.delivery_table()` now carries three state variables per ladder point: the
applied ratio, the setpoint last acted on, and the closed-loop-run flag. They are
seeded from the shadow governor, which is the committed estimate of the same three
firmware variables. On each open sub-sample the model takes the hold arm under the
firmware's own three conditions and the feedforward arm otherwise. On the
feedforward arm the ratio walks toward the band-clipped setpoint at the tick
ceiling, and the sub-sample mean of the applied ratio is evaluated by `ramp_mean()`
in closed form. A per-tick loop would cost 100 evaluations per sub-sample, which is
14 000 per table, and the decision budget does not have them; the ramp is an
arithmetic series and the closed form is exact.

The transition rolls of mechanism 2 are integrated rather than duplicated. A roll
seeds `share_actedSp` with the ladder point and `shareClosedLoopRun` true, so it
models the command as HELD across the transition. Its carry is therefore consumed
on a stage the model held and skipped on a stage the model slewed, where the
integrated ramp is the better carry. The rolls additionally publish the
conduction-handoff state they ended in, which selects the slow ceiling for that
stage.

Three conditions route a sub-sample to the hold arm, and the third is not the
open-loop branch at all. Below `SHARE_I_TOT_MIN_A` (0.075 A) the firmware's
minimum-load gate returns before the loop-mode decision is taken, so a frozen
sub-sample writes nothing whatever the setpoint did. The first draft of this
branch routed a frozen sub-sample to the feedforward arm and would have modelled
a slew at standstill; the defect was latent on the Gate 1 stimulus, where the
frozen sub-samples all carry an unchanged setpoint, and is pinned by
`test_a_frozen_sub_sample_holds_whatever_the_setpoint_did` against a full roll
whose mode census is 1000 frozen ticks of 1000.

The branch is INERT unless both seeds are supplied. With either seed absent every
open sub-sample takes the hold arm, which is the pre-2026-09-02 model bit for bit;
`test_the_feedforward_branch_is_inert_without_the_seeds` asserts equality of the
whole table, not approximate equality. The closed-stage arm is untouched in either
setting, and the asymmetry map degenerates to the identity at the shipped
`dv0_v` of 0.0, so the shipped controller's closed-stage behaviour is unchanged.

Verification is against a full 1 kHz `GovernorModel` roll of the same stage, seeded
with the same three firmware variables. On the full ceiling the model and the roll
agree to 0.0e+00, which is why the test pins them at 1e-12 rather than at a band.
On the handoff ceiling they agree to 1.34e-04, the dwell allowance being spent on
moving ticks and the release to the full ceiling therefore landing one tick apart.

### 3.3 The dark-flag proxy, measured and rejected

`updateShareSlewMode()` selects the slow ceiling while a channel is dark, and the
dark flags are filtered at 0.05 per tick with hysteresis at 0.20 A entry and 0.15 A
exit. An instantaneous proxy for them, evaluated on each sub-sample's own entry
currents, was implemented behind `ff_dark_model` and measured: Gate 1 reads 0.000315
mean with the proxy and 0.000095 without it, a factor of 3.3. The proxy declares a channel dark where
the filter's hysteresis has already released it, and the modelled ramp is then ten
times too slow. The default is therefore `False`, the option is retained and
tested, and the roll's own flag, which is the real filtered state at a rolled
stage's end, is consulted in either setting.

### 3.4 The roll's own handoff state, seeded

The flag the roll publishes is only worth consulting if the roll reaches it
honestly. `updateShareSlewMode()`'s two channel filters and two dark flags are RUN
state, and `GovernorState` starts them at zero and True, so a roll that inherited
those defaults spent its opening ticks on the handoff ceiling and could end dark
for a reason that was the seeding and not the stage. Measured: 104 of 196
published roll entries carried a handoff flag under the default seeding, and
consulting that flag COST Gate 1, which read 0.000329 mean against 0.000095 with
the flag ignored. `_roll_begin()` now seeds the two filters from the stage's own
entry currents and the two flags from those filters; 62 of 196 entries then carry
the flag, and consulting it costs exactly nothing (0.000095 either way). This is
the same class of defect as the mis-seeded hold flag the review of 2026-09-02
found in the same function, and it has the same remedy.

### 3.5 Gate 2

Gate 2 is the walk comparison of `mpc_design_20260901.md` section 7.1, at
`soc0` 0.7 and a PLANT `dv0_v` of 0.030223, three repeats per leg. Every leg below
reproduced to six decimals across its three repeats. Equivalent hydrogen is
`h2 - delta_soc / lambda` at the suite's `lambda` of 0.41.

⚠️ The CONTROLLER's `dv0_v` is 0.0 in every row, on both sides of the comparison.
`ems_walk.walk()` builds the strategy from `strategy_kwargs` and does not consult
`mpc_configure_kwargs()`, so a walk must pass the offset by hand and this table
deliberately does not, in order to isolate the change of section 3 from the
change of section 5 item 1. The delivered-share error under that mismatch is
reported below and is NOT the campaign's.

| leg | strategy | h2 (g) before | h2 (g) after | delta-SoC before | delta-SoC after | eq-H2 before | eq-H2 after |
|---|---|---|---|---|---|---|---|
| `ems-soc-band` | `soc-band` | 0.012264 | 0.012264 | -0.002002 | -0.002002 | 0.017146 | 0.017146 |
| `ems-sdp` | `sdp-v4` | 0.012729 | 0.012729 | -0.001600 | -0.001600 | 0.016631 | 0.016631 |
| `ems-mpc` | `mpc-det` | 0.010429 | **0.009910** | -0.002537 | -0.002747 | 0.016616 | **0.016610** |
| `ems-mpc-sto` | `mpc-sto` | 0.009313 | **0.008729** | -0.002998 | -0.003233 | 0.016625 | **0.016615** |

The two reference legs are unmoved, which is the check that the walk itself did not
change. The two MPC legs spend 5.0 % and 6.3 % less hydrogen and 8.3 % and 7.8 %
more state of charge, so the equivalent-hydrogen totals move by -0.004 % and
-0.06 %. The offline ranking is therefore unchanged in substance: `mpc-det` remains
the lowest equivalent-hydrogen leg of the four and its margin over `sdp-v4` widens
from 0.090 % to 0.126 %. That margin exceeds the ~50 ppm same-configuration
repeatability floor by a factor of about 25, so it is a real ordering, but it is a
small one and it is measured under the inverse-crime condition below.

The "before" rows were produced on the same host in the same session by disabling
the feedforward branch at its seeds, and they reproduce the design record's own
Gate 2 row for each MPC leg to all six decimals. That is the check that the
comparison is a comparison of the change and not of two hosts.

⚠️ ONE FIGURE FROM THE SAME RUNS DOES NOT IMPROVE. On the Gate 2 configuration the
plant carries `dv0` 0.030223 V while the controller's map is inert, and the
delivered-share prediction error there reads 0.036175 mean after the change against
0.039943 before it. The feedforward model removes only a tenth of that error,
because item 7 of Table 3 dominates it. The Gate 1 configuration, whose plant runs
at `dv0` 0.0, is where the feedforward mechanism is separable, and Table 1 is the
measurement of it.

Note that the walk's plant IS the controller's prediction model, so Gate 2 shows
that the plumbing works and that the plan is self-consistent. It does not score the
controller; that is the inverse-crime condition of `mpc_design_20260901.md`
section 7.1, and it applies with more force after this round than before it, because
the model and the plant now agree on one more mechanism.

### 3.6 Solve time

The per-decision budget is 10 ms, 15 ms on `ems-mpc-cross`, against a 20 ms command
period. Measured on the Gate 2 walk with the feedforward branch enabled and
disabled in one session, at the fixed 10 ms budget both configurations then used,
the deterministic variant reads a median solve time of 6.139 ms against 6.092 ms
and the stochastic variant 5.963 ms against 5.918 ms, with the same 13 of 61
budget expiries in both settings. The median therefore rises by 0.047 ms, not by
the 0.159 ms per-table cost of section 2.1: a decision that expires its budget
spends the same wall clock either way, and one that does not evaluates fewer
candidates in the same time. The per-table figure is the honest cost of the
branch and the per-decision figure is what the callback sees.

Under the shipped configuration, which also carries the adaptive budget and the
coarsening of section 4, the same walk reads a median of 5.978 ms for `mpc-det`
and 5.890 ms for `mpc-sto`, with maxima of 7.88 ms and 6.89 ms and **no budget
expiry on either leg**. No decision exceeded its budget by more than the
one-candidate overshoot the design bounds it at.

---

## 4. The search budget and the ladder (operator ruling, 2026-09-02)

The ruling that accompanies the survey is that the strategy's ability to make
decisions the non-governor-aware strategies cannot make must be fully expressed
rather than truncated by the wall clock. Campaign C measured the truncation:
`ems-mpc-cross` ran a median solve of 10.002 ms against a 10 ms budget and expired
that budget on 57.4 % of its decisions, against 6.6 % on `ems-mpc`, 10.3 % on
`ems-ftp75-mpc` and 0 % on `mpc-sto`. An expiry returns the shifted incumbent, and
the enumeration is ordered outward from the incumbent, so an expiry drops the
candidates FURTHEST from standing still. The truncation is therefore biased and
not merely partial. The 15 ms per-scenario `mpc_budget_ms` key added in commit
`5f1cfed` is a stopgap for one leg.

### 4.1 The adaptive budget

`derive_budget_ms()` is the derivation, and it is the callback bound of the
`BUDGET_MS_DEFAULT` banner read as an equation rather than as a comment:

    budget + one rollout of overshoot
          + the roll slice + one chunk of overshoot
          + the 50 Hz surface's own work            <=  the command period

The command period is 20.0 ms (`COMMAND_PERIOD_MS`), the stated margin is 2.0 ms
(`BUDGET_MARGIN_MS`), the roll slice and the surface work are MEASURED on the
callback that is about to decide, and the per-candidate overshoot is the previous
decision's `solve_ms / candidates`. Where a term has no measurement its nominal
constant is used: `ROLL_BUDGET_MS_DEFAULT` plus `ROLL_CHUNK_OVERSHOOT_MS` 0.296 ms,
`SURFACE_MS_NOMINAL` 0.17 ms and `ROLLOUT_MS_NOMINAL` 0.012 ms, each measured in
the review of 2026-09-02. The result is clamped to `[BUDGET_MS_FLOOR 4.0,
BUDGET_MS_CEILING 15.0]`; the ceiling is `ems-mpc-cross`'s own hand-set budget,
kept as the blunter second guard that hardware has already run.

⚠️ **THE FLOOR IS NOT PART OF THE BOUND.** Once the rest of the callback costs
more than `command_period_ms - margin_ms - floor_ms`, the floor keeps the search
alive at the price of a callback total that EXCEEDS the command period: a roll
slice of 18 ms puts the total at 22.2 ms. `derive_budget_raw_ms()` therefore
returns the unclamped arithmetic and `derive_budget_ms()` is that function
clamped, so a caller can tell a budget the bound produced from one the floor
imposed. `timing()` reports `budget_floor_binding`, the count of decisions on
which the floor bound; it read zero on every leg measured here, and a nonzero
value is a statement that the callback overran its period, not a tuning
observation.

An explicit `budget_ms` disables the derivation and takes precedence, so the
`mpc_budget_ms` scenario key and the `--mpc-budget-ms` flag behave exactly as
before. `MpcStrategy.budget_ms` therefore reads `None` on an adaptive strategy and
`budget_ms_fixed` is the predicate. The budget actually spent is reported per
decision as `budget_ms_min`, `budget_ms_median` and `budget_ms_max` in `timing()`,
because it is no longer a constant of the run and a reader cannot recover it from
the configuration.

### 4.2 The ladder coarsening

`coarsen_ladder()` returns the ladder INDICES a decision's enumeration walks. The
ladder itself never changes: the roll table is keyed on `(stage key, ladder
index)`, and a ladder that moved under it would silently re-point every entry.

`coarse_ladder_set()` builds the set for a nominal size `k`: both rails and the
centre, `k` evenly spaced indices, and then the incumbent's block values TOGETHER
WITH THEIR IMMEDIATE NEIGHBOURS. The incumbent keeps the shifted incumbent a
candidate and preserves the anytime property; the neighbours keep every ladder
index reachable, which the evenly-spaced rule alone does not (section 4.4).

`coarsen_ladder()` then takes the largest admissible size from `LADDER_SIZES`
(7, 5, 3) whose REALISED set has a full enumeration
`n_options * len(set) ** n_blocks` fitting an allowance of
`LADDER_ENUM_SAFETY 0.85 * budget_ms / candidate_cost_ms`, halving that allowance
on a TRANSITION-HEAVY horizon. Transition-heavy is defined by the design's own
constant: at least `RollJob.MAX_TRANSITIONS` previewed transition stages in the
horizon, which is a horizon carrying more transitions than the roll table can
hold.

Two properties of that sentence are load-bearing. The selection is on the
REALISED set, not on the nominal `k`, because the three unions can only ADD
points and budgeting the nominal is wrong in the one direction a budget cannot
absorb. And `LADDER_SIZES` carries no entry 4: the centre is always unioned in,
so at seven levels a nominal four realises `{0, 2, 3, 4, 6}`, the same set a
nominal five realises, and the entry could never be selected — it was previously
admitted on an allowance sized for 64 candidates per option and then walked 125.

The per-candidate cost is a NAMED CONSTANT, `CANDIDATE_COST_MS_NOMINAL` =
0.0300 ms, and section 4.4 gives the measurement it comes from and the defect
that made a measured value unacceptable. The `candidate_cost_ms` constructor
argument overrides it for a caller that has profiled its own host.

### 4.3 Measurement

Table 4 is four configurations of each leg, all measured in one session on one
host, at `soc0` 0.7 and `dv0_v` 0.030223. "Expiry" is the fraction of decisions
that reached the budget; "ladder" is the census of ladder points walked per
decision.

| leg | configuration | h2 (g) | delta-SoC | eq-H2 | solve median / max (ms) | expiry | ladder census |
|---|---|---|---|---|---|---|---|
| `ems-mpc` | fixed 10 ms, no coarsening | 0.009910 | -0.002747 | 0.016610 | 6.12 / 10.01 | 21.3 % | 7 x 61 |
| `ems-mpc` | fixed 15 ms, no coarsening | 0.009910 | -0.002747 | 0.016610 | 6.12 / 15.02 | 6.6 % | 7 x 61 |
| `ems-mpc` | adaptive, no coarsening | 0.009910 | -0.002747 | 0.016610 | 6.09 / 15.01 | 6.6 % | 7 x 61 |
| `ems-mpc` | **shipped** | 0.009910 | -0.002747 | 0.016610 | **5.98 / 7.92** | **0.0 %** | 7 x 48, 6 x 1, 4 x 12 |
| `ems-mpc-sto` | fixed 10 ms, no coarsening | 0.008729 | -0.003233 | 0.016615 | 6.00 / 10.02 | 4.9 % | 7 x 61 |
| `ems-mpc-sto` | **shipped** | 0.008729 | -0.003233 | 0.016615 | 5.87 / 6.56 | **0.0 %** | 7 x 48, 5 x 11, 4 x 2 |
| `ems-mpc-cross` | fixed 10 ms, no coarsening | 0.010942 | -0.007300 | 0.028747 | 10.01 / 10.57 | 89.0 % | 7 x 200 |
| `ems-mpc-cross` | fixed 15 ms, no coarsening (the `5f1cfed` stopgap) | 0.010942 | -0.007300 | 0.028747 | 15.00 / 15.04 | 57.0 % | 7 x 200 |
| `ems-mpc-cross` | adaptive, no coarsening | 0.010942 | -0.007300 | 0.028747 | 15.00 / 15.04 | 56.0 % | 7 x 200 |
| `ems-mpc-cross` | **shipped** | 0.010942 | -0.007300 | 0.028747 | **4.15 / 9.38** | **0.0 %** | 7 x 19, 5 x 61, 4 x 120 |

Four readings follow.

The four `shipped` rows are the fix round's; the other rows disable the
coarsening and are therefore unaffected by it. Three repeats of each shipped row
reproduce the hydrogen, the state-of-charge change AND the ladder census exactly
(section 4.4). The expiry fractions of the fixed-budget rows move by up to two and
a half points between sessions (`ems-mpc-cross` at a fixed 10 ms read 86.5 % in
one session against 89.0 % in another), which is the wall clock and not the
controller; no hydrogen or state-of-charge column moved at all.

⚠️ The census now contains four-, five- and seven-point sets rather than five and
seven. That is the neighbour union of section 4.4: the realised set depends on
where the incumbent sits, and a three-point nominal around a rail realises four
points rather than five.

First, **budget expiry is eliminated on all three legs**: 89.0 % to 0.0 % on
`ems-mpc-cross`, 21.3 % to 0.0 % on `ems-mpc`, 4.9 % to 0.0 % on `ems-mpc-sto`.
Every decision now completes the enumeration it started, so no decision is
returning the shifted incumbent because it ran out of clock.

Second, the adaptive budget alone does NOT achieve that. It saturates at the
15 ms ceiling on every decision of every leg - the measured roll slice, surface
work and per-candidate overshoot together come to well under a millisecond, so
the derivation returns 17.6 ms and the ceiling clamps it - which reproduces the `5f1cfed`
stopgap rather than improving on it, and `ems-mpc-cross` still expires 56 % of its
decisions there because 1029 candidates at the 0.0162 ms per candidate measured
unbudgeted on that leg is 16.7 ms.
The coarsening is what closes the gap, and the budget is what tells it how much to
coarsen.

Third, and this is the honest headline, **the committed trajectory does not
move**. Hydrogen, state-of-charge change and equivalent hydrogen are identical to
six decimals across all four configurations of all three legs, and an unbudgeted
run (`budget_ms` 1e5, median solve 16.697 ms on `ems-mpc-cross`) commits the same
plan as the 10 ms fixed one. On these stimuli the incumbent-ordered enumeration
already holds the optimum, so the round delivers an uncut search and a lower
median wall clock (10.01 ms to 4.15 ms on `ems-mpc-cross`, a 59 % reduction), and
not a better plan. The reduction is larger than the round's first measurement
reported, because the fix round's projection coarsens more of the cross leg's
decisions than the measured projection did. The bias an expiry introduces is real and is now removed; that it
was not costing anything on these three stimuli is a measurement, not an argument
that it never would.

Fourth, `ems-mpc-cross` coarsens on 181 of 200 decisions and keeps the full
seven-point ladder on 19. The coarsening is therefore selective rather than a
blanket reduction: it fires on the decisions that carry three charge options and
stands aside on the ones that do not.

### 4.4 Reproducibility

The first version of this rule read the previous decision's MEASURED
per-candidate cost, and the review of the same date established that this made
the committed plan host-dependent. On `ems-soc-band` at a 15 ms budget a
projected cost at or under 0.030 ms keeps the full ladder and commits h2
0.009717712, while one at or above 0.03717 ms coarsens and commits 0.010523689,
**8.29 % more hydrogen with the budget-expiry count still zero**; the measured
cost on one host spanned 0.0097 to 0.0261 ms, so a 1.4x slower machine moved the
headline figure silently. Two structural facts made the move that large: at seven
levels the evenly-spaced rule can only produce `{0, 2, 3, 4, 6}` or `{0, 3, 6}`,
so index 5 was unreachable — and index 5 is 0.6667, the cruise share `mpc-det`
commands on 260 of 610 commands over that stimulus.

Both are fixed. `coarsen_ladder()` projects on `CANDIDATE_COST_MS_NOMINAL`
(0.0300 ms, the slowest per-candidate cost observed in this round plus the same
15 % headroom `LADDER_ENUM_SAFETY` uses) and no caller passes it a measurement;
the measurement is reported by `timing()` as `candidate_cost_ms_seen` beside a
`candidate_cost_over_nominal` flag, so a host the projection did not size for is
visible rather than silently re-planned around. And `coarse_ladder_set()` unions
the incumbent's IMMEDIATE NEIGHBOURS as well as the incumbent, so every ladder
index is one coarsened decision away from an adjacent one.

Table 5 is the cliff probe repeated after the fix: the projection is swept over a
20x range on `ems-soc-band` at a fixed 15 ms budget, and the committed plan is
read off the walk.

| projected cost (ms) | h2 (g) | vs the first row | ladder census | commands at the 0.6667 cruise share |
|---|---|---|---|---|
| 0.0097 | 0.009717712 | — | 7 x 61 | 260 |
| 0.0162 | 0.009717712 | +0.000 % | 7 x 57, 6 x 4 | 260 |
| **0.0300 (the nominal)** | 0.009717712 | +0.000 % | 7 x 48, 6 x 1, 4 x 12 | 260 |
| 0.0372 (the old cliff) | 0.009731235 | +0.139 % | 7 x 10, 6 x 38, 5 x 1, 4 x 12 | 260 |
| 0.0500 | 0.009731235 | +0.139 % | 7 x 10, 6 x 38, 5 x 1, 4 x 12 | 260 |
| 0.0800 | 0.009731235 | +0.139 % | 7 x 9, 6 x 7, 5 x 25, 4 x 20 | 260 |
| 0.2000 | 0.009731235 | +0.139 % | 7 x 9, 6 x 7, 5 x 24, 4 x 20, 3 x 1 | 260 |

The **8.29 %** step at 0.0372 ms is **0.139 %**, and the cruise-share command
count is 260 on every row including the three-point floor set. The projection is
no longer a lever on the plan, which is what made pinning it to a constant safe;
had the sweep still shown a cliff, the constant would have been hiding a defect
rather than fixing one.

Measured after the fix, over three repeats of each of the three legs: the ladder
census and the committed trajectory are **exactly reproducible on all three**, not
approximately. The largest per-candidate cost measured on this host across the
Gate 1 runs was 0.0257 ms, inside the nominal, so `candidate_cost_over_nominal`
read false throughout.

What remains host-dependent is the adaptive BUDGET, which moves the width in the
coarse steps `LADDER_SIZES` allows. Two levers remove even that, in increasing
strength: an explicit `budget_ms` pins the budget, and `max_candidates` bounds
the search outright. The last is unchanged and remains the campaign's own lever.

---

## 5. What was not done, and why

1. **DONE — the asymmetry map is enabled.** The recommendation this note made
   was taken up in the same round by the agent that owns `hil_plant_sim.py`:
   `resolve_asymmetry_dv0_v()` gives the run's injected offset a single owner,
   and `mpc_configure_kwargs()` now always passes it as `dv0_v`, refusing loudly
   if the checkout's `MpcStrategy` has no such argument. `--asymmetry off`
   resolves to exactly 0.0, so the shipped default keeps meaning what it meant
   and every charge-free comparison that predates the change stands. The Gate 1
   effect is the lower half of Table 1.
2. **No regen term was added to the demand model.** It is the largest surviving
   modelling gap, but the demand model is shared with the dynamic-program bound
   and the tables would have to move with it. That is a table-regeneration round,
   not a delivery-model round.
3. **The Ag105 0.4 s current ramp is not modelled.** No stimulus in the current
   Gate 1 opens a charge window, so the item cannot be measured here.
4. **No firmware, wire-protocol or plant change was made.** The firmware is the
   authority this note is written against and was read only.
5. **DONE — `ems-mpc-cross`'s `mpc_budget_ms` key is removed.** The same agent
   removed the 15 ms stopgap of commit `5f1cfed`, so the leg now runs the
   adaptive budget of section 4.1 like every other. The key itself still works
   and still takes precedence for any scenario that declares one; no scenario
   does.
6. **MDAC quantization is still not modelled.** It is bounded at 4.3e-04 in
   delivered share, two orders under the acceptance band, and modelling it would
   put a second copy of the code mapping in the planner.
7. **`mpc-sto` is left failing Gate 1 on the measured plant.** The mechanism is
   its own demand forecast, not the delivery model (section 1), and the fix is a
   stimulus drawn from the transition matrix rather than a change to this file.

---

## 6. Reversal path

The change is confined to `tools/mpc_ems.py` and `tools/test_mpc_ems.py`, plus
the two registration lines in `hil_plant_sim.py` that section 5 item 1 records.
Removing the two seed arguments from the `Planner.solve()` call in
`MpcStrategy.decide()` restores the pre-2026-09-02 delivery model exactly, because
the branch is unreachable without them; constructing the strategy with
`budget_ms=10.0` and `coarsen_ladder_enabled=False` restores the pre-2026-09-02
search exactly; and `--asymmetry off` resolves `dv0_v` to 0.0, which restores the
symmetric prediction model. The three reversals are independent. The `RollJob.handoff` table, the `ramp_mean()` helper and the
`dv0_v` plumbing are additive and inert at their defaults.


---

## 2026-09-02: survey item 5 becomes a control, not a constraint

Survey item 5 records the setpoint cut and its restore as a **constraint** the planner
must stay clear of: the ladder band stopped 0.10 short of both rails so
`updateShareSetpointCutoff()` could never latch, and the cut was something the plan
avoided rather than something it used.

⚠️ **That framing is superseded by the operator ruling of 2026-09-02.** The ladder now
spans the full firmware band [0.15, 0.85], and the MPC is to gain 0 and 1 single-source
commands as **candidates**. The cut and its restore therefore move from the constraint
side of the model to the control side: a single-source command is a deliberate topology
change issued through the setpoint latch, and its cost, its feasibility and its restore
transient all belong inside the search rather than outside it.

Three consequences follow, and the first is the one that is not yet resolved.

- **The cut guard is path-dependent.** The doomed channel is cut only when its own
  current is at or under `SHARE_CUT_MAX_HANDOFF_A` 0.5 A, and that current depends on the
  share the plan held in the previous stage. The planner's stage tables are
  control-independent by construction, so the guard does not fit them. The three candidate
  resolutions are set out in `mpc_design_20260901.md`, section "2026-09-02"; the choice is
  open.
- **The bus law changes with the topology.** The fitted law is two-source and its `g_par`
  is a parallel droop code. The single-source law is measured and implemented
  (`dp_loss_map_20260902.md`, addendum): the same slope scaled by 1.9453 for FC-only and
  2.0579 for BT-only, each with its own no-load intercept.
- **The minority-current floor does not apply.** `SHARE_MINORITY_I_MIN_A` 0.30 A clips the
  delivered share toward the middle when both channels are on the bus. With one channel
  off there is no minority to protect, so the closed-stage surrogate must not clip a 0 or
  1 candidate. This is a change to `delivery_table()` and not to the governor.
