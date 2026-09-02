# Governor-aware model-predictive energy management — design document

Status: DESIGN ONLY. No repository file was modified and no git operation was run in its
preparation. Every numeric value below was recomputed in this session; the provenance of each
is stated at its first use.

Scope: a receding-horizon energy-management strategy for the DC balancer rig, registered as an
EMS strategy in the hardware-in-the-loop suite alongside `soc-band`, `sdp-v3` and `dp-replay`,
and evaluable offline through `tools/ems_walk.py`. Section 4 covers the stochastic variant.
Bench calibration of the underlying plant constants is outside the scope of this document.

---

## 0. Notation and imported quantities

The document uses the following symbols. Each is defined once and reused verbatim.

| Symbol | Meaning | Value | Source |
|---|---|---|---|
| `s` | commanded `power_share_setpoint`, fuel-cell fraction | control | firmware command packet |
| `c` | commanded `charge_goal`, binary | control | firmware command packet |
| `x` | pack state of charge | state | `hil_plant_sim` plant truth |
| `alpha_d` | delivered fuel-cell share, `abs(I_fc)/I_tot` | derived | `governor_model.delivered_share()` |
| `I_tot` | source total, `abs(I_fc) + abs(I_batt)` | A | plant |
| `dt_dec` | decision period | 1.0 s | `sdp_policy_v3.json:decision_dt_s` |
| `dt_gov` | governor tick | 1.0e-3 s | `GOV_CONST["POWER_BAL_PERIOD_US"]` |
| `N` | prediction horizon, in decision stages | 20 | this design, §3.1 |
| `lambda_T` | terminal state-of-charge price | 2.439024 g/SoC | recomputed, §3.4 |
| `eta_fc` | proxy fuel-cell efficiency | 0.40 | operator ruling; `ems_walk.H2_PROXY_ETA_FC` |
| `Q_LHV` | hydrogen lower heating value | 120000 J/g | `ems_walk.H2_LHV_J_PER_G` |

Firmware limits that bind the design: `LIMIT_I_FC_MAX` 1.4 A and `LIMIT_I_BT_MAX` 3.0 A, both
bus-referred (`teensy_controller.ino:1375` and `:1426`); `DROOP_R_MIN` 0.15 and `DROOP_R_MAX`
0.85 (`GOV_CONST`); `SHARE_MINORITY_I_MIN_A` 0.30 A; the closed-loop entry threshold
2 x 0.30 = 0.60 A with `SHARE_GOV_OL_HYST_A` 0.05 A, that is a release at 0.55 A.

---

## 1. Problem statement

### 1.1 State, controls and objective

The controlled state is the pack state of charge `x`. The prediction model carries a second,
non-optimised state: the share governor's internal state, treated in §2.

The control at each decision is the pair `(s, c)`. The share `s` is quantized onto a ladder;
the charge intent `c` is binary. Both are exactly the two energy fields of the 22-byte command
packet, so the strategy commands nothing the Raspberry Pi bridge cannot command.

The horizon objective is the hydrogen mass burnt over the horizon plus a terminal
state-of-charge price. In symbols, over stages `k = 0 .. N-1`,

    J = sum_k  h2(s_k, c_k, k) * dt_dec  +  lambda_T * abs(x_N - x_ref)

The stage hydrogen rate is the student's online proxy, per the operator ruling:

    h2(P_fc) = P_fc / (eta_fc * Q_LHV)       [g/s]

with `eta_fc = 0.40`, so the proxy coefficient is 1/(0.40 x 120000) = 2.083333e-05 g/s/W. The
plant-side Gfc metric (`H2_GFC_DC_GAIN_GPS_PER_W` = 1.7637602179836514e-05 g/s/W) remains the
scored quantity and is not used inside the controller. The two differ by a factor
2.083333e-05 / 1.763760e-05 = 1.18119, that is the proxy over-states hydrogen by 18.1 % at
every operating point. Because the factor is a constant multiplier on a linear stage cost, it
does not change the ranking of two candidates at equal terminal state of charge; it does change
the trade-off against `lambda_T`, and §3.4 prices `lambda_T` in the same units as the proxy to
keep the two commensurate. The convex fuel-cell map is a flagged option, `--mpc-h2-map convex`,
carrying `TODO(calibrate)` at rig scale.

`P_fc` is the fuel-cell **bus-side** power referred to the stack through `ETA_BOOST` = 0.85,
matching `ems_walk.walk()`'s own proxy accumulation (`ems_walk.py:502`). During a charge window
the fuel cell additionally supplies the charger, so `P_fc` carries the charger term under the
physical accounting of `gen_dp_ems_table` D11.

### 1.2 Horizon and decision rate

Decisions are made every `dt_dec` = 1.0 s. That rate is not free: it is the
`decision_dt_s` of the shipped SDP artifact and the `dt` of the transition-probability matrix
`TPM_dt1_hil.mat`, so the deterministic and stochastic variants, the SDP benchmark and the
Markov model all share one stage clock.

The horizon is `N` = 20 stages, that is 20 s. Three considerations fix it. First, the
`ems-sdp` stimulus runs 61 s and its Run window is 55 s, so a 20 s horizon sees roughly
one third of the cycle and the receding-horizon claim is not vacuous. Second, the pack moves
approximately 1e-04 of state of charge per second at this rig's currents, so a 20 s horizon
resolves 2e-03 of state of charge against a whole-cycle excursion of about 5e-03 — a
meaningful fraction. Third, the compute budget of §3.5 admits it with a factor of 116 in hand
at the decision period. `N` is a constructor parameter, not a literal.

### 1.3 Preview source

The deterministic variant needs the demand trajectory over the horizon. It obtains it in the
simulator through the strategy's `bind_scenario(scenario, meta)` hook, which already receives
the scenario metadata dictionary, and reconstructs the bus demand from `meta["ems_v_profile"]`
by calling `gen_dp_ems_table.build_demand()` — the same function `ems_walk.walk()` calls, so
the controller's demand model and the offline walk's demand model cannot diverge.

This is preview, not clairvoyance about the state trajectory. The distinction matters for how
the result may be reported. `dp-replay` optimises the whole state trajectory offline with full
foreknowledge; the deterministic MPC re-optimises a truncated horizon at 1 Hz from the measured
state. However, the MPC does read the future demand exactly, which no causal supervisor can do,
so it must be labelled a PREVIEW strategy and must not be described as causal on the rig.

The vehicle mapping is explicit. On a real vehicle the preview would come from route preview:
a navigation-supplied speed or grade profile over the next 20 s. Where no route preview exists,
the stochastic variant of §4 replaces it with the transition-probability matrix, and that
variant IS causal. The two variants therefore bracket the information assumption, and the pair
is the deliverable, not either one alone.

### 1.4 Constraints

The following constraints are enforced inside the optimiser, not left to the actuation layer.

1. **Share band.** The commanded share is restricted to `[0.25, 0.75]`, which is
   `DP_SHARE_MIN` .. `DP_SHARE_MAX` from `gen_dp_ems_table.py:267-268`. Two reasons, both
   already argued in that file and both binding here. The band stops 0.10 short of
   `DROOP_R_MIN` and `DROOP_R_MAX`, so the setpoint cutoff can never fire; and it gives the MPC
   exactly the actuator authority the DP bound and `soc-band` have, so a comparison measures
   the decision rule rather than the range. A consequence used throughout §2: with the command
   confined to the band, `updateShareSetpointCutoff()` never latches and `applyShareRatio()`
   never attempts an r-based cut, so the prediction model needs no cut, no load guard and no
   survivor-blanking branch. That is a modelling simplification obtained by a constraint, not
   by an omission.
2. **Fuel-cell overcurrent margin.** The predicted fuel-cell channel current must satisfy
   `alpha_d * I_tot <= 0.85 * LIMIT_I_FC_MAX` = 1.19 A, the same `DP_CHARGE_FC_MARGIN`
   headroom the DP and the SDP solver apply. A candidate that violates it at any predicted
   stage is infeasible.
3. **Battery overcurrent margin.** `(1 - alpha_d) * I_tot <= 0.85 * LIMIT_I_BT_MAX` = 2.55 A.
   This cannot bind at this rig's demand (the peak source total measured on the EMS stimuli is
   about 1.45 A) and is present so a rescaled stimulus cannot produce an illegal command.
4. **Charge admission.** A charge window may open only where `gen_dp_ems_table.charge_mask()`
   admits it: inside the Run window, on a cruise region
   (`abs(dv/dt) <= SOC_BAND_CRUISE_SLOPE_MAX` 0.05 and `v >= SOC_BAND_CRUISE_MIN_MPS` 0.5),
   and where the single-source budget `P_dem/V_bus + chg_ceiling <= 0.85 * 1.4` holds. The
   cruise term is operator ruling (b) of 2026-08-30 and is a hard constraint, not a penalty.
5. **FC_CHARGE / REGEN mutual exclusion.** The firmware enforces it in
   `assertFcChargeEnable()`; the MPC never commands the regen path, so the exclusion is
   satisfied by construction. The prediction model nevertheless applies
   `charge_path_owns_bt=True` on a predicted charge stage, which is what
   `GovernorModel.step()` expects and what makes the topology-pinned share wind-up appear in
   the prediction (§2.3).
6. **Charge-window minimum dwell.** Once a charge window opens it is held for
   `SDP_CHG_MIN_DWELL_S` = 8.0 s, and the demand fed to the next decision has the charger's own
   bus draw subtracted. This is the campaign-222036 chatter ruling and is reproduced verbatim
   from `SdpStrategy.charge_hold_status()` rather than re-derived. The MPC therefore does not
   optimise `c` freely per stage: `c` is a block-scale decision (§3.2), which is the honest
   parametrisation given an 8 s latch.
7. **State-of-charge window.** `x` is kept inside `[0.55, 0.65]` relative to the artifact's
   grid, the SDP's own window. The constraint is a soft one, priced through `lambda_T`, for the
   reason `sdp_ems_solver.py` D3 gives: at this rig's rate one stage moves `x` by about 1e-04
   against a 0.1-wide window, so a hard test could only ever fire within 1e-04 of an edge and
   would poison the terminal value by interpolation.

---

## 2. Prediction model

### 2.1 Composition

The prediction model reuses existing code and adds no second copy of any physical law.

| Quantity | Function reused | Module |
|---|---|---|
| speed, acceleration, bus demand, bus voltage, source total, cruise mask | `build_demand()` | `gen_dp_ems_table` |
| auxiliary load | `scenario_drain_a()` | `gen_dp_ems_table` |
| charge admissibility | `charge_mask()` | `gen_dp_ems_table` |
| pack and hydrogen step, discharging | `step_discharge()` | `gen_dp_ems_table` |
| pack and hydrogen step, charging | `step_charge()` | `gen_dp_ems_table` |
| delivered share from a commanded share | `GovernorModel` | `governor_model` |
| offline walk harness | `walk()` | `ems_walk` |

`gen_dp_ems_table` imports numpy. The controller runtime must not, per the operator ruling, so
the MPC calls `build_demand()`, `charge_mask()` and `scenario_drain_a()` ONCE at
`bind_scenario()` time on the horizon-resolution time grid, converts the resulting arrays to
Python lists, and the 1 Hz decision path touches only lists and floats. `step_discharge()` and
`step_charge()` are re-expressed as scalar stdlib functions in `tools/mpc_ems.py` with a
compile-time equivalence test against the numpy originals (§6, step 4). That test is the
mechanism that keeps the two from drifting; a hand copy without it would be the defect this
repository has already recorded twice.

### 2.2 The governor is the delivery model

The requirement is that the MPC predict what the firmware DELIVERS, not what the strategy
commands. The prediction model therefore drives every candidate share command through
`governor_model.GovernorModel`, whose per-tick semantics are the firmware's:

* the minimum-load freeze below `SHARE_I_TOT_MIN_A` = 0.075 A;
* the open-loop / closed-loop hysteresis at 0.60 A entry and 0.55 A release on the filtered
  source total;
* the open-loop HOLD, in which a commanded change is not acted on at all;
* the minority-current clip to `[I_min/I_filt, 1 - I_min/I_filt]` in closed loop;
* the per-tick ratio slew ceilings, 0.02 nominal and 0.002 while a channel is dark;
* the static droop law `alpha = r + dV0*r*(1-r)/(k_d*I_tot)` inverted by the integral action.

### 2.3 Integration step, and where the full 1 kHz roll is required

A full 1 kHz roll of the governor over a 20 s horizon costs 20 x 1000 ticks. Measured on this
machine (`.venv_hil`, CPython 3.14.5, 200000 closed-loop `GovernorModel.step()` calls) one tick
costs **2.721 us**, so one predicted second costs **2.721 ms** and a full-horizon rollout costs
**54.4 ms**. A search that rolls hundreds of candidates at that price does not fit 1 Hz, and,
more seriously, does not fit the simulator: `hil_plant_sim.py` paces a 1 kHz loop and
resynchronises rather than catching up beyond 0.25 s of overrun, and a host stall of 1 s is
read by fw v23 and later as a run boundary and provokes a mid-run warm reset. A blocking
half-second solve inside the 50 Hz command callback is therefore not merely slow, it corrupts
the run.

The resolution rests on two properties of the governor that were measured here rather than
assumed.

**Property A — the governor's load filter has no memory across a decision stage.** The filter
weight is `SHARE_GOV_FILT_ALPHA` = 0.05 per 1 ms tick, so over one 1 s stage the retained
fraction of the previous filter state is 0.95^1000 = 5.29e-23. The filtered total at the end of
any stage therefore equals that stage's source total to full double precision. Because the
source total is the sum of the two channel currents and is set by the demand, not by the split,
the filtered total, the open/closed mode and the minority clip bound are all functions of the
PREVIEW ALONE and are independent of the candidate control. They can be precomputed once per
decision, before the search.

**Property B — an algebraic stage map reproduces the governor on closed-loop stages, and does
not reproduce it on open-loop stages.** A stage-level surrogate was written and scored against
a full 1 kHz `GovernorModel` roll over 240 stages of 12 synthetic 20-stage profiles with
randomised in-band setpoints. The mode classification produced by the Property-A precompute
matched the governor's dominant mode on **240 of 240** stages. With the surrogate state
re-seeded from the governor's own delivered share at each stage boundary, the delivered-share
error over the 145 CLOSED stages was **mean 8.2e-04, maximum 1.49e-02**. Over the 95 open or
frozen stages no surrogate variant tried was acceptable: a feedforward-branch surrogate gave a
whole-set mean of 9.8e-03 with a maximum of **0.2484**, and a hold-everything surrogate was
worse still, mean 5.88e-02 with a maximum of 0.3817. Every one of the 16 stages whose error
exceeded 0.02 was an open-loop stage that the firmware resolved as `open_hold`.

That measurement is the design's central fact and is stated plainly: **a hand-written surrogate
for the open-loop branch must not be written.** The branch that broke two earlier walks in this
repository is precisely the branch a surrogate gets wrong.

The prediction model is therefore **hybrid**:

1. **Precompute, once per decision, control-independent** (Property A): per stage `k`, the
   source total `I_tot[k]`, the bus voltage, the demand, the settled filter value, the
   open/closed/frozen mode class, the minority clip bound `lo[k]`, and the charge
   admissibility.
2. **Search, on the surrogate** (Property B): candidate rollouts evaluate closed stages with
   the algebraic map and carry the standing delivered share through open and frozen stages,
   with those stages FLAGGED AS UNCONTROLLED so the search assigns them no credit for a
   commanded change.
3. **Commit, on the full governor**: the winning first-stage command is rolled through the real
   `GovernorModel` at 1 kHz for one stage, and the resulting governor state — including
   `closed_loop_run`, `acted_sp` and `r_prev` — is carried into the next decision. The
   controller's estimate of the governor state is therefore never surrogate-propagated across
   more than one decision.

The residual bias is stated, not hidden: on open-loop stages the search's delivered share can
be wrong by up to about 0.25 in share, and the bias is only partly common-mode across
candidates. Three things bound its consequence. The horizon recedes every second, so an open
stage predicted at horizon index 12 is re-predicted eleven more times before it is acted on.
The commit roll keeps the state estimate exact. And the acceptance gate of §5.1 measures the
predicted-versus-realised delivered share over a whole walk and fails the implementation if the
integrated discrepancy exceeds the stated band. If the gate fails, the fallback is to roll the
full governor on open stages only and to shrink the candidate set accordingly; the budget
arithmetic for that fallback is given in §3.5.

### 2.4 Pack, state-of-charge and demand model

The pack model is `gen_dp_ems_table` D6: the nine-point `LIPO_OCV` table at `BATT_CELLS` = 2,
the state-of-charge dependent series resistance, one Picard iteration from bus-side power to
pack current, and the coulomb count `x -= i*dt/capacity_as` at `BATT_CAPACITY_AH` = 5.0 Ah. The
resistor-capacitor pair is not modelled, exactly as D6(b) states.

The demand model inherits `build_demand()`'s declared boundaries, and one of them is
load-bearing for this controller: **the demand model has no regen term**, so it over-states
demand on every decelerating stage. The MPC will therefore under-value coasting. The magnitude
is unquantified and the live plant does inject regen since the WP-C round, so the divergence is
larger now than when the DP table was first generated. This is recorded as an open item, not
patched here.

### 2.5 The charger-efficiency change

The parallel physics change makes the plant charger an energy-conserving converter at
`eta_chg` = 0.88, so the bus power drawn for charging becomes `V_pack * i_chg / eta_chg` rather
than `V_bus * i_chg`. The MPC's charge stage cost must move with it, and so must the
state-of-charge price. Recomputed from `sdp_ems_solver.model_levers()`'s own algebra:

* share lever, unchanged: `L_share` = 1/(k * V_pack * C_As) = **0.4504504505 SoC/g** with
  `k` = 1/(0.5 * 120000), `V_pack` = 7.4 V, `C_As` = 18000 A s;
* charge lever, pre-change: `L_chg` = 1/(k * V_bus * C_As) = **0.2089864159 SoC/g**, that is
  the share lever divided by `V_bus/V_pack` = 2.155405;
* charge lever, post-change: `L_chg` = `eta_chg` * `L_share` = 0.88 x 0.4504504505 =
  **0.3963963964 SoC/g**.

The consequence is checkable against the standing revisit condition, which states that charging
returns on its own if the charger lever exceeds 0.31 SoC/g. The `sdp_policy_v3` admission
threshold is `(1-gamma)/alpha` = 0.05/0.1629624189805737 = **0.3068192060 SoC/g**, and
0.3963963964 exceeds it. **Under the eta-era model the charge action is admitted even at
`sdp_policy_v3`'s own alpha.** The two-sided calibrated alpha for the eta era is
`(1-gamma)/sqrt(L_share*L_chg)` = **0.1183263980**, whose shadow price is
0.1183263980/0.05 = **2.366528 g/SoC**, against `sdp_policy_v3`'s 3.259248 g/SoC.

The MPC must not hard-code either. It reads the charge accounting from one constant,
`MPC_ETA_CHG`, defaulting to the plant's own value, and prices the terminal state of charge per
§3.4. A campaign run under the pre-change plant and one run after it are not comparable on
hydrogen, and the strategy records `eta_chg` in its provenance so a report can say so.

---

## 3. Optimiser

### 3.1 Structure

The optimiser is a **move-blocked exhaustive search over candidate command sequences,
warm-started from the previous decision**, and not a state-space dynamic program. The reason is
structural and is worth stating because the alternative looks attractive.

A horizon dynamic program over the state of charge would need the governor's persistent state
in the state vector, since the delivered share at a stage depends on `closed_loop_run`,
`acted_sp` and the standing ratio `r_prev`. Quantizing the standing ratio and the last acted
setpoint onto the 21-step ladder gives a governor state space of 2 x 21 x 21 = 882 states, and
a dynamic program over (state of charge x governor state x control x stage) is far outside the
budget of §3.5. A trajectory-based search carries the governor state EXACTLY along each
candidate at no extra cost, because the state is a function of the candidate's own history.
That is the correct method for a plant whose hidden state is cheap to propagate and expensive
to enumerate.

### 3.2 Control parametrisation

The horizon is divided into three blocks of 2, 6 and 12 stages. The share command is constant
within a block. The block lengths are geometric because prediction confidence decays with
horizon index and because only the first block is ever executed.

The share alphabet within a block is a seven-point uniform ladder spanning the §1.4 band:
0.25, 0.3333, 0.4167, 0.50, 0.5833, 0.6667, 0.75. Seven points give a share resolution of
0.0833, which at the EMS stimuli's drain-phase source total of about 1.45 A is 121 mA of
fuel-cell current per step. That is coarser than the DP's 41-point grid (25 mA per step) and
the coarseness is deliberate: the MPC re-decides every second and the executed command is
refined by the next decision, whereas the DP commits its whole trajectory once. A
`--mpc-share-levels` flag exposes the count.

The charge intent is a single binary decision applied to block 1 only, and it is offered only
when `charge_mask()` admits every stage of block 1. Blocks 2 and 3 carry the charge intent
forward under the 8 s minimum-dwell latch and do not re-decide it. This parametrisation follows
from constraint 6 of §1.4: with an 8 s latch, a per-stage charge decision would be a fiction.

The candidate count is 7^3 x 2 = **686** sequences per decision.

### 3.3 Search and warm start

The 686 candidates are enumerated in an order seeded by the previous decision's solution: the
incumbent sequence, shifted one stage, is evaluated first, and the enumeration proceeds outward
in ladder distance from it. Three properties follow. The incumbent's cost is available
immediately, so the search is ANYTIME — it can be abandoned at any point and still return a
feasible, previously-validated command. Candidates whose partial cost already exceeds the
incumbent's total are abandoned mid-rollout, which is a sound bound because the stage cost is
non-negative and the terminal term is bounded below by zero. And a decision that finds no
improvement re-commands the incumbent, which suppresses needless share motion and therefore
needless governor slewing.

A hard budget `mpc_budget_ms` bounds the search. On expiry the incumbent is returned and a
counter is incremented; the counter appears in the exit summary, so a budget that is actually
binding is visible rather than silent.

### 3.4 Terminal cost

The default terminal cost is

    lambda_T * abs(x_N - x_ref)

with `x_ref` the run's captured initial state of charge, exactly as `SdpStrategy` regulates
around the captured `soc0` rather than an absolute target, and

    lambda_T = 1 / EMS_EQ_H2_LAMBDA_SOC_PER_G = 1/0.41 = 2.439024 g/SoC.

The choice is deliberate and is the single most consequential number in the design. The suite
scores every EMS leg on **equivalent hydrogen**,
`eq_H2 = h2 - (dSoC - dSoC_reference)/lambda` at `lambda` = 0.41 SoC/g
(`run_hil_suite.py:7095`, band 0.409 to 0.415). A controller whose internal state-of-charge
price differs from the metric's exchange rate optimises a different objective than it is scored
on, and its deficit against the bound is then partly an artefact of the mismatch. Setting
`lambda_T` to the metric's own reciprocal rate makes the horizon objective the truncated eq-H2
metric itself.

The two alternative prices are recorded for comparison, and their spread is the honest
uncertainty on this constant: `sdp_policy_v3`'s shadow price is 3.259248 g/SoC, which is
+33.6 % against 2.439024; the eta-era two-sided price of §2.5 is 2.366528 g/SoC, which is
-3.0 % against it. The proximity of the eta-era price to the metric's rate is a check on both,
not a coincidence to be leaned on. `--mpc-terminal-price` selects among `metric` (default),
`sdp-shadow` and an explicit value, and the selection is recorded in the run provenance.

Discounting inside the horizon is disabled, that is `gamma_horizon` = 1. The scored metric is
an undiscounted total over the run, and `gen_dp_ems_table`'s objective is likewise undiscounted
stage cost plus terminal penalty. With `gamma_horizon` = 1 and a terminal price the MPC's
horizon objective is a receding-horizon instance of exactly the DP's objective (D5), which is
what makes the comparison in §5 legible.

**Flagged alternative, requiring a solver change.** The theoretically preferable terminal cost
is the SDP's own converged value function, `J_SDP(x_N, bin_N)`, interpolated linearly on the
state-of-charge axis. With it, the MPC is an `N`-step lookahead rollout on the SDP policy: at
`N` = 0 it reduces to `sdp-v3` exactly, and any `N >= 1` is a policy-improvement step, which is
a far stronger claim than "it does better on this cycle". The obstacle is that the shipped
artifact does not carry `J`: `sdp_policy_v3.json` holds `policy` with two tables and no value
function. Adding an optional `value_function` block to `sdp_ems_solver.py` is a
schema-additive change (the consumer reads `alpha.value` and the policy tables, so extra keys
are compatible by construction) costing 101 x 25 = 2525 floats, of order 50 kB of JSON. It is
recommended as a follow-on, not as a prerequisite; the discount consistency it requires
(`gamma_horizon` = `gamma` = 0.95, with `gamma^20` = 0.358486 weighting the terminal term)
changes the objective away from the scored metric and must be evaluated as its own variant.

### 3.5 Compute budget

All timings below were measured in this session on this machine using `.venv_hil`
(CPython 3.14.5), and the arithmetic built on them is stated so it can be rechecked.

| Item | Measured cost |
|---|---|
| one `GovernorModel.step()` tick, closed-loop branch | 2.721 us |
| one full 1 kHz governor roll of one 1 s stage | 2.721 ms |
| one control-independent precompute, 20 stages | 4.4 us |
| one surrogate stage evaluation, including the pack and hydrogen step | 0.43 us |

The per-decision cost of the deterministic variant is therefore

    686 candidates x 20 stages x 0.43 us  = 5.90 ms   (search)
  +                     20 stages x 0.22 us = 0.004 ms (precompute)
  +                        1 stage x 2.721 ms = 2.72 ms (commit roll)
  ----------------------------------------------------------------
                                             = 8.63 ms per decision

Against the 1 s decision period that is a margin of **116x**. The binding constraint is not the
decision period but the 50 Hz command callback: the whole decision executes inside one
`__call__`, which must not stall the simulator's 1 kHz loop. 8.63 ms sits inside the 20 ms
command period with a factor of 2.3, is an order of magnitude below the 0.25 s
resynchronisation threshold, and is two orders below the 1 s run-boundary threshold that
triggers a mid-run warm reset. Branch-and-bound pruning reduces the typical case well below the
worst case, and `mpc_budget_ms` (default 12 ms) caps it absolutely.

For the fallback of §2.3 — rolling the full governor on open-loop stages rather than
surrogating them — the arithmetic changes materially. The 2026-09-01e measurement records that
64.5 % of the FTP-75 Run window sits below the 0.55 A open-loop line, so a 20-stage horizon
would carry about 13 open stages at 2.721 ms each, that is 35.4 ms per candidate. The candidate
set must then shrink to about 8 sequences (283 ms per decision, sliced across the 50 command
callbacks at under 6 ms each) or the horizon must shorten. The fallback is specified but is not
the design; it is what the acceptance gate of §5.1 selects if the surrogate fails.

---

## 4. Stochastic variant

### 4.1 The demand model

The stochastic variant replaces the preview with the Markov model in
`references/EMS/generated/TPM_dt1_hil.mat`. Its structure was read in this session from the
matrix and its provenance sidecar: **25 bins, dt = 1.0 s, 211 non-zero entries, diagonal mass
0.762**, row occupancy concentrated in bin 10 which carries 6498 of 8609 samples, that is
75.5 %. The non-zeros per row run from 1 to **17** with a mean of 8.44, and bin 10's diagonal
probability is 0.928.

The demand axis map from watts to the normalised bin axis is the SDP artifact's, 0 to 25 W
(`DEMAND_MAP_DEFAULT_W`), so the stochastic MPC and `sdp-v3` classify a measured bus power into
the same bin. Bin centres therefore sit at 0.5, 1.5, ... 24.5 W. That map also fixes which bins
admit charging: with `chg_i_ceiling_a` = 0.8 A the single-source budget forbids any bin whose
centre exceeds `(0.85*1.4 - 0.8) * 15.95` = **6.2205 W**, that is bins 6 and above, which
reproduces the shipped artifact's `charge_forbidden_bins` list of 6 through 24 exactly. Note
what that means and do not soften it: under this map the idle bin that carries three quarters
of the dwell is a charge-forbidden bin, and the charge action is reachable only in bins 0 to 5.

### 4.2 What changes against the deterministic variant

Only the demand trajectory. The governor model, the pack model, the constraint set, the
parametrisation, the search and the terminal cost are unchanged. The stochastic variant is
therefore a strict information ablation of the deterministic one, which is what makes the pair
informative.

A scenario tree is rejected on arithmetic: with a maximum out-degree of 17 the exhaustive tree
over 20 stages is not enumerable, and pruning it to the three most probable children per node
gives 3^20 leaves, still far outside the budget. Two admissible constructions remain.

**Certainty-equivalent (the fallback).** Propagate the bin distribution forward as
`p_{k+1} = p_k * TPM` from the measured bin, and take the expected de-normalised power at each
stage as a single deterministic demand trajectory. Cost is identical to the deterministic
variant. It is honest about the mean and blind to the variance, and it is the ablation baseline.

**Sampled scenario fan (the recommendation).** Draw `M` = 8 demand trajectories from the
transition-probability matrix, starting from the measured bin, using **common random numbers**:
one seed per decision, the same `M` sampled bin sequences applied to every candidate. Common
random numbers matter here for a specific reason — the objective is a difference of two
candidates' costs, and shared noise removes the sampling variance from that difference, so a
ranking on eight scenarios is far more stable than eight independent draws would suggest. The
candidate cost is the mean over the fan; a `--mpc-risk cvar` option scores the worst
`ceil(M/4)` scenarios instead, which is the min-max-flavoured variant if it is wanted.

Cost: 686 candidates x 20 stages x 8 scenarios x 0.43 us = **47.2 ms** search, plus the 2.72 ms
commit roll, that is about 50 ms per decision. That exceeds the 20 ms command period and must
NOT be run in one callback. The stochastic decision is therefore **sliced across the 50 command
callbacks** between decisions, at a `mpc_budget_ms_per_call` of 2.0 ms, with the incumbent
returned on every callback until the slice completes. The anytime property of §3.3 is what
makes the slicing safe: an incomplete search returns the shifted incumbent, which is feasible
and was validated one second earlier.

### 4.3 Honest limits of the stochastic variant on this rig

The transition-probability matrix was built from ten full-size Simulink drive cycles and is
unitless by construction; its shape is a vehicle's, not this rig's. The 0 to 25 W consumer map
places this rig's demand somewhere inside it, but nothing has verified that the rig's demand
DYNAMICS match the matrix's transition structure. The concrete symptom to watch is the clamp
counters `SdpStrategy` already reports: a high clamp rate means the map is wrong, and the
stochastic MPC must report the same two counters for the same reason. A second limit is that
the matrix's 0.762 diagonal mass at dt = 1 s makes the one-step-ahead prediction nearly a
persistence forecast, so on this rig the stochastic variant will look close to a
hold-last-demand controller over short horizons; if that is what the campaign measures, it is a
property of the matrix and must be reported as one rather than as a controller result.

---

## 5. Evaluation plan

### 5.1 Offline, before any board time

Three gates, in order. None of them requires hardware.

**Gate 1 — the surrogate acceptance test.** For each of `ems-sdp`, `ems-soc-band`,
`ems-ftp75-sdp` and `ems-ftp75-socband`, run the MPC's own prediction of the delivered share
against a full-governor `ems_walk.walk(..., governor=True)` of the SAME committed command
sequence, and compare per stage. Acceptance: mean absolute delivered-share error at or below
5e-03 and the integrated hydrogen difference at or below 1 % of the run total. These bands are
derived from the closed-stage measurement of §2.3 (mean 8.2e-04) with a factor of six for the
open-stage contribution, and they are PROVISIONAL until the first walk measures them. Failure
selects the §3.5 fallback.

**Gate 2 — the walk comparison.** Walk `mpc-det` and `mpc-tpm` through `ems_walk.walk()` on
`ems-sdp`, `ems-soc-band`, `ems-dp-replay` and the four `ems-ftp75-*` scenarios, against
`soc-band`, `sdp-v3` and `dp-replay` on the same scenarios and the same `soc0`. Report the
`(h2, delta_soc)` pair for every leg — never `h2` alone — and the eq-H2 total at
`lambda` = 0.41. The prediction to state before running it: on `ems-sdp`, `sdp-v3` landed on the
DP bound at 1.0000x and beat `soc-band` by 10 % (campaign 024231), so the MPC's available
headroom on that stimulus is at most that 10 % and realistically much less; a result claiming
more than the DP bound is a defect in the walk, not a controller success.

**Gate 3 — the governor-hold audit.** `WalkResult.mode_fractions` reports the fraction of ticks
in `open_hold`. Any MPC walk whose commanded share moved materially inside a high-hold window is
a walk whose commands were not acted on, and the reported total is then a property of the hold,
not of the policy. This gate exists because the standing rule — walks must model the open-loop
hold — was written after two walks failed for exactly that reason.

### 5.2 Live scenarios

Four new scenarios, all reusing existing stimuli so that no new stimulus has to be validated at
the same time as a new controller.

| Scenario | Stimulus | Strategy | Purpose |
|---|---|---|---|
| `ems-mpc` | the `ems-soc-band` 61 s profile and drain, the same list object | `mpc-det` | the primary comparison, three-way against `ems-soc-band` and `ems-dp-replay` |
| `ems-mpc-tpm` | the same profile and drain | `mpc-tpm` | the information ablation |
| `ems-ftp75-mpc` | `FTP75_PROFILE`, behind `--with-ftp75` | `mpc-det` | drive-cycle scale |
| `ems-mpc-cross` | the `ems-sdp-cross` profile, with `sdp_soc_ref_offset` reused as an MPC `soc_ref_offset` | `mpc-det` | the switching-surface stimulus, to see whether the MPC's continuous price removes the SDP's limit cycle |

Each must declare `chg_i_ceiling_a` equal to `SCENARIOS["ems-soc-band"]["chg_i_ceiling_a"]`
(0.8 A), `aux_preload_a` 0.0 on the drive-cycle legs per the 2026-09-01 ruling, and
`electrical: "any"`.

### 5.3 Expectation checks

Every check must be **phase-free**, per the overnight-session rule: no check may assert that an
event happened at a particular time, because the MPC's decision timing is not phase-locked to
the stimulus and a phase-locked check has already failed a correct board once (campaign 024231,
`ems-sdp-cross`). The following kinds already exist in `run_hil_suite.py` and are sufficient:

* `min_value` / `max_value` with a broad `t_window` on `cmd_share_sp` — assert the command
  stayed inside `[0.25, 0.75]` for the whole Run window, which is constraint 1 of §1.4 and
  fails loudly if the band is ever escaped;
* `max_continuous_ticks` on the fuel-cell current above 1.19 A — asserts the §1.4 constraint 2
  margin without asserting when;
* `edge_count_between` on the `charge_goal` rising edge — bounds the number of charge windows,
  which is the 8 s dwell's observable, without pinning their times;
* `column_range_at_least` on `cmd_share_sp` — asserts the MPC actually moved the share, so a
  degenerate controller that commands one constant cannot pass by doing nothing;
* `min_rows` on the Run window — de-vacuates every window-scoped check above;
* `h2_cum_g` `min_value` — asserts the run actually burnt hydrogen.

All bands are PROVISIONAL on first registration, derived from the Gate-2 walk and annotated
with `provisional_note`, and are re-derived from the first campaign that evaluates them. The
`FAULT_EXPECTATIONS` entry for each scenario expects no fault at all, with `allow_only` unset.

### 5.4 The delta-state-of-charge-matched DP comparison

`hil_report_analysis.py --matched-dp lookup` picks the MPC legs up with no change, provided
each new scenario's stimulus fingerprint is prefilled into `tools/dp_db/`. The FTP-75 leg's
matched solve takes about 24 minutes offline and must be prefilled before the campaign, not
during it. The per-run percentage deviation from the matched DP is the primary number; the
cross-strategy table gives the ranking.

### 5.5 The EMS frontier

A new registry entry in `EMS_FRONTIERS`, id `cycle61-mpc`, with reference `ems-soc-band`,
candidate `ems-mpc` and bound `ems-dp-replay`. `vs_bound_max` stays 1.06, the scale-free value.
`vs_reference_max` is set PROVISIONALLY to 0.98, matching the `cycle61` tuple, because on this
stimulus the DP does beat `soc-band` by 14.33 % and a 2 % ask is not aggressive. The FTP-75
tuple must use 1.02 for the reason `EMS_FRONTIER_FTP75` already records: at drive-cycle scale
the offline DP ties `soc-band` at -0.01 %, so demanding a win there would fail a correct
candidate. `stimulus_mismatch_exit_affecting` is False for one campaign, as the FTP-75 tuple's
comment prescribes for any tuple no campaign has yet evaluated.

### 5.6 What the metric structurally cannot distinguish

Four limits, each of which must appear in the report rather than being discovered later.

1. **The vs-bound arm is structurally near 1.0 for charge-free candidates.** Campaign 080905
   established that when the candidate and the bound differ only along the share lever, and
   `lambda` IS that lever's rate, eq-H2 makes the two coincide by construction. The arm detects
   lever-class deviations, such as the candidate opening the charger when the bound does not;
   it does not measure optimality. It must not be tightened on a charge-free reading.
2. **Preview and causality are not separated by the metric.** `mpc-det` reads the future demand
   and `sdp-v3` does not. A win by `mpc-det` over `sdp-v3` is therefore a measurement of the
   VALUE OF PREVIEW plus the value of the horizon, and the two cannot be separated by these
   runs. The `mpc-tpm` leg is what separates them, and the separation is only as good as §4.3's
   caveats allow.
3. **The metric cannot see the open-loop hold.** Two controllers that command different shares
   through a sub-0.55 A window deliver the same split and score identically. On the FTP-75
   stimulus 64.5 % of the Run window is below that line, so a large majority of the drive cycle
   is share-blind. A controller improvement confined to that region is unmeasurable on this rig,
   and a controller REGRESSION confined to it is equally invisible.
4. **The proxy stage cost is not the scored cost.** The controller minimises the
   `eta_fc` = 0.40 proxy and is scored on the Gfc metric, an 18.1 % constant apart. The
   constant cancels in a ranking at matched terminal state of charge; it does not cancel in the
   trade-off against `lambda_T`, so the MPC's chosen operating point is a function of a
   coefficient that is `TODO(calibrate)` at rig scale.

---

## 6. Registration, plumbing and the implementation step list

### 6.1 Names and files

* New module `tools/mpc_ems.py`, stdlib only, importable without numpy.
* New test `tools/test_mpc_ems.py`, run under `.venv_hil`.
* Strategy names `mpc-det` and `mpc-tpm`, registered in `hil_plant_sim.EMS_STRATEGIES` and
  `EMS_STRATEGY_META`.
* Scenario names `ems-mpc`, `ems-mpc-tpm`, `ems-ftp75-mpc`, `ems-mpc-cross`.

### 6.2 Sidecar provenance fields

`MpcStrategy.bind_scenario()` populates `self.provenance`, which `main()` copies into the CSV
meta sidecar, exactly as `SdpStrategy` does. Fields: `horizon_n`, `block_lengths`,
`share_levels`, `terminal_price_mode`, `lambda_t_g_per_soc`, `eta_fc_proxy`, `eta_chg`,
`preview_source` (`"scenario_profile"` or `"tpm"`), `tpm_sha256` and `n_bins` for the
stochastic variant, `budget_ms`, `soc_ref_offset`, and `governor_commit` (True when the commit
roll is enabled). The exit summary reports decisions made, budget-expiry count,
incumbent-retained count, open-loop-hold fraction seen, and the two demand-map clamp counters
for `mpc-tpm`.

### 6.3 Step list

1. Write `tools/mpc_ems.py` with, in order: the control-independent precompute (§2.3
   Property A); the scalar stdlib re-expression of `step_discharge` and `step_charge`; the
   closed-stage surrogate; the candidate enumerator with warm start and branch-and-bound; the
   terminal cost with the three price modes; and the `MpcStrategy` class exposing
   `bind_scenario`, `reset`, `decide`, `__call__` and `summary_line`, matching `SdpStrategy`'s
   surface so `ems_walk._instantiate()` needs one branch and no restructuring.
2. Add the `MpcStrategy` branch to `ems_walk._instantiate()` alongside the `SdpStrategy`,
   `SocBandStrategy` and `DpReplayStrategy` branches, re-instantiating rather than reusing the
   registry singleton for the reason that function already documents.
3. Register both strategies in `EMS_STRATEGIES` and `EMS_STRATEGY_META`. `frontier_eligible` is
   True for both; `role_note` is omitted for both because both pursue an energy objective.
   Note that `EMS_STRATEGY_META`'s import-time assertions test `policy_file` and
   `require_calibrated_benchmark` only for `SdpStrategy` instances, so no new assertion is
   needed; `policy_file` is None for `mpc-det` and the TPM path for `mpc-tpm`.
4. Add `tools/test_mpc_ems.py` covering, at minimum: the scalar pack and hydrogen steps against
   the numpy originals to 1e-12 relative; the precompute's mode classification against a full
   `GovernorModel` roll on a synthetic profile; the closed-stage surrogate band of §5.1 Gate 1;
   constraint enforcement, that is no candidate outside `[0.25, 0.75]` and none violating the
   1.19 A margin; the charge mask, that is no charge command outside `charge_mask()`; the 8 s
   dwell; the warm start and the anytime budget path, that is a zero budget returns the
   incumbent and does not raise; the terminal-price modes; and the recomputed lever arithmetic
   of §2.5 as literal pinned values.
5. Add the four `SCENARIOS` entries with the shared stimulus objects, the 0.8 A charge ceiling,
   `aux_preload_a` 0.0, and `electrical: "any"`. Add `ems-ftp75-mpc` to `FTP75_SCENARIOS`.
6. Add the four `FAULT_EXPECTATIONS` entries with `signals_require` per §5.3, every band
   annotated `provisional_note`.
7. Add the `cycle61-mpc` entry to `EMS_FRONTIERS` per §5.5.
8. Run Gates 1 to 3 of §5.1. Record the measured surrogate bands in the module docstring in the
   style `governor_model.py` uses, that is a table of every scenario with an explicit UNSCORED
   verdict where a run carries no share motion, and an explicit statement that the headline is
   the range and not its best member.
9. Prefill `tools/dp_db/` for the four new scenarios, the FTP-75 leg first because it is the
   slow one.
10. Run one supervised campaign, `--with-ftp75`, and analyse it under the hil-agent-analysis
    discipline. De-provisionalise the bands from the measurement.

The step list contains no decision the implementer has to refer back for, with one exception
that is deliberate: step 8's measured bands may fail Gate 1, in which case the §3.5 fallback is
selected and steps 5 to 10 proceed against the reduced candidate set. That branch is an outcome
of a measurement, not an open question.

### 6.4 Command-line flags

`hil_plant_sim.py` gains `--mpc-horizon`, `--mpc-share-levels`, `--mpc-budget-ms`,
`--mpc-terminal-price {metric,sdp-shadow,VALUE}`, `--mpc-h2-map {proxy,convex}`,
`--mpc-risk {mean,cvar}` and `--mpc-scenarios` for the fan size. Every flag's resolved value
lands in the sidecar provenance of §6.2, so no run's behaviour depends on an unrecorded
argument.

---

## 7. Risks and reversal

### 7.1 Risks

1. **The surrogate misprices open-loop stages.** Measured maximum error 0.2484 in delivered
   share, all on stages the firmware resolved as `open_hold`, and 64.5 % of the FTP-75 Run
   window is in that regime. Mitigations: Gate 1 of §5.1; the per-decision commit roll; the
   §3.5 fallback. This is the largest technical risk and it is quantified rather than hedged.
2. **A blocking solve corrupts a run.** A stall of 0.25 s resynchronises the simulator loop and
   a stall of 1 s provokes a mid-run warm reset that makes the rest of the run something other
   than the scenario. Mitigations: the hard `mpc_budget_ms`; the anytime incumbent; slicing for
   the stochastic variant; and a `max_overrun_ms` check on the run's own summary.
3. **The terminal price is a choice, and the three candidate values span 38 %.** 2.366528,
   2.439024 and 3.259248 g/SoC. A result that is sensitive to which one is used is a result
   about the price, not about the controller. Mitigation: report the chosen value in every
   figure caption and run at least one sensitivity leg offline.
4. **The charger-efficiency change moves the charge lever across the admission threshold.**
   §2.5 recomputes it at 0.3963963964 SoC/g against `sdp_policy_v3`'s 0.3068192060 threshold,
   so the eta-era MPC will open charge windows that the pre-change model rejected. Every
   pre-change campaign's charge behaviour therefore becomes incomparable. Mitigation: `eta_chg`
   in the provenance, and an explicit era banner in the report.
5. **The demand model has no regen term.** Inherited from `build_demand()`, and now larger than
   when the DP table was first generated because the live plant injects regen. The MPC will
   under-value coasting by an unquantified amount. Mitigation: recorded as an open item;
   quantifying it needs the regen-fidelity work already on the queue.
6. **Preview is not causality.** `mpc-det` must never be reported as a causal controller on
   this rig. Mitigation: a banner on the class in the style `DpReplayStrategy` and
   `SdpStrategy` already carry, and `preview_source` in the provenance.
7. **The transition-probability matrix is a vehicle's.** §4.3. Mitigation: the clamp counters
   and an explicit statement in the report.

### 7.2 Reversal path

The change is confined to one new module, one new test, and additive entries in four registries.
A single revert restores the previous behaviour completely, because:

* `tools/mpc_ems.py` and `tools/test_mpc_ems.py` are new files with no importer outside the
  registration;
* the `EMS_STRATEGIES` and `EMS_STRATEGY_META` entries are additive, and the import-time
  assertion that pins the two key sets fails loudly if only one is removed;
* the four `SCENARIOS` entries and their `FAULT_EXPECTATIONS` entries are additive, and
  `build_plan()` iterates `SCENARIOS`, so removing them removes the runs;
* the `EMS_FRONTIERS` entry is a list element, and the runner iterates the list;
* one branch is added to `ems_walk._instantiate()`;
* the `hil_plant_sim.py` flags are additive with defaults that no existing run reads.

No wire protocol changes: the MPC commands the same `power_share_setpoint` and `charge_goal`
fields the existing strategies command, so the firmware is untouched and the telemetry and
observation frames keep their v4 and 18-byte layouts. No existing artifact, table or constant is
modified. The recommended `value_function` addition to `sdp_ems_solver.py` of §3.4 is a
SEPARATE, schema-additive commit and is not a prerequisite for any of the above.
