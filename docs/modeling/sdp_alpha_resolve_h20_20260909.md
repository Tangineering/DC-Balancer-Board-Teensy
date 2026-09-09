# The lever prices, alpha and charge admission on the H-20 hydrogen axis (2026-09-09)

Design record for phase-B items 1 to 3 of `docs/HANDOFF_H2_MAP_20260909.md`: the eq-H2 lever
prices re-measured on the H-20 map, the alpha re-derivation that produced
`tools/sdp_policies/sdp_policy_v7.json`, and the charge-admission census against the map's
23.4 W stack ceiling.

Scope of this note: the lever tables, the alpha, the frontier decision, the charge census and
the reversal path. It does not restate a suite expectation band, re-solve a matched-DP record,
or re-run the MPC gates. Those are phase-B items 4 to 7 and belong to other agents.

Predecessors that remain valid for their own eras: `sdp_alpha_resolve_20260903.md` (the
five-reading lever procedure and the alpha that became `sdp_policy_v6.json`) and
`sdp_alpha_sweep_measured_20260908.md` (the sweep at the measured charger billing, on the
retired hydrogen law).

---

## 1. What this round found, in four sentences

The 2026-09-08 handoff's central quantitative premise is refuted by the campaign record: the
rig's Run-window median stack power is 13.3654 W, not the 3.2 W design estimate, so the rig
operates at 0.4314 LHV efficiency against the map's 0.4329 peak rather than far below it.
Every downstream number moves with it, and mostly in the direction opposite to the one the
handoff predicted: the eq-H2 share lever is 0.423 SoC/g and not the projected 0.57, the
constant `k = 1/(ETA_FC*Q_LHV)` is 7.5 % **below** the map's marginal rate rather than 31 %
above it, and the re-derived alpha therefore **rises** to 0.134041467771, 0.05 % from the value
`sdp_policy_v6.json` already carried. The H-20 stage cost nevertheless produces a materially
different policy, and `sdp_policy_v7` beats `sdp_policy_v6` by 9.23 % of equivalent hydrogen on
the 61 s stimulus. The one result that does not close is charge admission: the closed-form
admission window that has certified every SDP artifact since `v3` is **not a valid predicate
under a convex hydrogen map**, and `v7` admits charging in 46 cells while its tripwire reports
charging rejected.

---

## 2. The operating point, and why it is exogenous

### 2.1 The measurement

Campaign I's `ems-sdp` hi-fi run,
`HIL Results/hil_report_20260908_200836/scenario_ems-sdp_hifi`, 54 982 Run-window ticks
(`state == 2`), read in one streaming pass with the standard library.

The stack power is recovered by **inverting the map on the run's own `h2_rate_gps` column** -
`I = (rate - A0_OFFSET_GPS) / K_FARADAY_GPS_PER_A`, then `h2_map.stack_power_w(I)` - because
that is the exact argument `H2Consumption.step()` was called with.

| Statistic | Run window |
|:--|--:|
| Median stack power, map-inverted | **13.3654 W** |
| Mean stack power, map-inverted | 10.1364 W |
| Quartiles, map-inverted | q25 0.0000 W, q75 19.2762 W |
| Median `p_fc_w` / `ETA_BOOST` | 14.6440 W |
| Median `p_fc_w` (bus) | 12.4474 W |
| Saturated ticks | 0 |

The handoff asked for `p_fc_w / ETA_BOOST`. That proxy reads 14.6440 W, 9.6 % higher, and the
gap is the two-curve gap of `h20_hydrogen_map_20260908.md` section 6: `Plant.step()` bills
`FuelCellSource.v_terminal * fuel_cell.i` on the **source** side, not the bus power divided by
the boost efficiency. The map-inverted figure is the one that prices what the map actually
charged, and it is the one shipped.

**Caveat, stated because the number is one campaign and one scenario.** The distribution is
bimodal - q25 0.0 W against q75 19.3 W, the fw v28 governor's battery-only spans against its
full-share spans - so the median summarises a two-lobed sample and moves with duty. Re-derive
it from the next campaign rather than carrying it.

### 2.2 What it overturns

| Quantity | At the 3.2 W estimate | At the measured 13.3654 W |
|:--|--:|--:|
| Map marginal rate | 1.2797e-05 g/s/W | **1.8015e-05 g/s/W** |
| LHV efficiency | 0.2536 | **0.4314** (peak 0.4329 at 14.752 W) |
| `A0_OFFSET_GPS` as a fraction of the rate | 63.1 % | **25.7 %** |
| `k = 1/(ETA_FC*Q_LHV)` against it | +30.2 % | **-7.5 %** |

The retired justification for 3.0 W in `sdp_ems_solver.ALPHA_MISMATCH_REF_P_STACK_W` was "the
TPM's bin centres are a few watts of BUS power". The shipped TPM contradicts it directly: the
centres run 0.5 to 24.5 W, and its own `results.row_occupancy` puts **75.6 %** of the observed
dwell in the bin centred at 10.5 W and 93.4 % in 8.5 to 14.5 W.

### 2.3 The self-consistent alternative diverges, and this is why the reference is exogenous

The natural alternative is the solver's own operating point: the occupancy-weighted stack power
the policy commands on the SoC-target row. It is circular, and it does not merely fail to be a
fixed point - iterating solve, re-derive, solve walks **down** and off the end:

| Iteration | Reference in [W] | alpha | Reference out [W] |
|--:|--:|--:|--:|
| 0 | 12.5078 | 0.129170 | 10.9825 |
| 1 | 11.7451 | 0.125206 | 10.3394 |
| 2 | 11.0423 | 0.121854 | 9.7116 |
| 3 | 10.3770 | 0.118919 | 8.6352 |
| 4 | 9.5061 | 0.115309 | *tripwire refuses the solve* |

The mechanism is a positive feedback: a lower reference lowers the marginal rate, which lowers
alpha, which prices SoC lower, which commands a smaller fuel-cell share, which lowers the
reference again. A reference point taken from the policy it prices has no defensible resting
place. A reference point taken from a campaign has one.

---

## 3. The lever prices

### 3.1 The construction, unchanged

The 2026-09-03 procedure, verbatim: walk the three alpha legs on the 61 s `ems-sdp` stimulus,
where `cal` and `charge` command an identical constant share so their difference is purely the
charge windows, and `cal` minus `greedy` is purely the share lever.

    L_share = (dSoC_cal    - dSoC_greedy) / (h2_cal    - h2_greedy)
    L_chg   = (dSoC_charge - dSoC_cal)    / (h2_charge - h2_cal)

Walk configuration: `tools/ems_walk.py`, miniforge, one process, `governor=True`,
`loss_map=hil_plant_sim.plant_loss_map()`, `dv0_v=0.013522`, `droop_scale_fc=0.9434`,
`r_series_ohm=0.033`, strategy `sdp-sweep`, scenarios `ems-sdp-alpha-{greedy,cal,charge}`.

**The full split law is used.** `run_hil_suite.py`'s own alpha-anchor invocation omits
`--r-series 0.033` and carries only the `dv0` and `droop_scale_fc` halves of the M2 asymmetry
fit. The omission is inert at this measurement's precision: dropping the term moves `L_share`
by 0.03 % and `L_chg` by 3e-4 %. Both walks are tabulated below so the difference is on record
rather than asserted.

### 3.2 The tables

Walked levers, by hydrogen law and charger billing era (SoC per gram):

| Law | Charge billing | `L_share` | `L_chg` | ratio |
|:--|:--|--:|--:|--:|
| `gfc-linear` (retired) | plant 0.88 | 0.4153531 | 0.3198422 | 0.770049 |
| `gfc-linear` (retired) | measured 0.801173 | 0.4153531 | 0.2969050 | 0.714825 |
| **`h20`** | **plant 0.88** | **0.4222722** | **0.3743980** | **0.886627** |
| **`h20`** | **measured 0.801173** | **0.4222722** | **0.3417529** | **0.809319** |

Walked levers under the suite's own (no `r_series`) configuration, H-20 law, plant 0.88:
`L_share` 0.4221507, `L_chg` 0.3743968.

The underlying walk totals, H-20 law, `r_series_ohm=0.033`:

| Leg | h2 [g] | dSoC | saturated stages |
|:--|--:|--:|--:|
| greedy | 0.0046103558 | -0.0059510802 | 0 |
| cal | 0.0161092920 | -0.0010953995 | 0 |
| charge | 0.0180606635 | -0.0003648099 | 0 |

Model levers, from `sdp_ems_solver.model_levers()` with the marginal rate `k` replaced by
`h2_map.marginal_gps_per_w(13.3654 W)` = 1.801474e-05 g/s/W:

| Pair | `L_share` | `L_chg` (at 0.801173) |
|:--|--:|--:|
| classic `k = 1/(ETA_FC*Q_LHV)` | 0.4504505 | 0.3608887 |
| **H-20 marginal at 13.3654 W** | **0.4167424** | **0.3338827** |

The model pair keeps `L_chg = eta_chg * L_share` exactly, the D13 identity: `k` scales both
levers together, so it moves the level and not the ratio.

### 3.3 The comparison table the handoff asked for

| Lever | Shipped (Gfc grams) | Walked, H-20 | Model, H-20 at the operating point |
|:--|--:|--:|--:|
| `L_share` | 0.4165286 | 0.4222722 | 0.4167424 |
| `L_chg` (at 0.801173) | 0.3337114 | 0.3417529 | 0.3338827 |
| ratio `L_chg / L_share` | 0.801173 | 0.809319 | 0.801173 |

### 3.4 The validation that licenses the walk, and its limit

The same construction run under `--h2-map gfc-linear` walks `L_share` to 0.4153531 against the
board's own five-reading mean of 0.4165286: **agreement to 0.28 %**. That is what licenses the
walk to carry the *era ratio*. It does not license the walk to replace a board measurement of
the *level*: the same check on the charge lever walks 0.3198422 against the board's 0.3337114,
which the walk **under-reads by 4.2 %**.

**The walked H-20 levers are therefore PROVISIONAL model levers.** The board's H-20 levers come
from campaign II's three alpha legs and nothing here anticipates them.

### 3.5 The shipped lambda

`run_hil_suite.EMS_EQ_H2_LAMBDA_SOC_PER_G` = **0.423 SoC/g**, derived in three steps:

1. The board supplies the level: `L_share` = 0.4165286 SoC/g of Gfc hydrogen, the unweighted
   mean of the five eta-era campaign readings (`EMS_LEVER_ETA_READINGS`, campaigns B to F).
2. The walk supplies the era ratio, validated in section 3.4:
   0.4222722 / 0.4153531 = 1.016658.
3. The product: 0.4165286 x 1.016658 = 0.4234674, quoted as **0.423** on the same
   three-figure convention `0.41` used.

`EMS_EQ_H2_LAMBDA_BAND` moves from (0.409, 0.415) to **(0.4223, 0.4325)**. This is a change of
*unit*, not a widening of an expectation band: the two ends are the two independent
cross-checks of section 3.2 and 3.3 - the H-20 walk alone at the low end, the closed-form model
lever at the measured marginal rate at the high end. The relative spread is 2.4 % against the
Gfc era's 1.5 %, and the reason is that the level is board-measured while the transfer into
H-20 grams is modelled. A wider band makes **more** verdicts KNIFE-EDGE, not fewer.

Leaving the band at (0.409, 0.415) would not have been conservative: `lam_lo`/`lam_hi` take the
min and max over `[lambda] + band`, so a stale band would have swept every frontier verdict
across a 3.4 % interval spanning two units.

**The handoff's "roughly 0.57 SoC/g at the rig median" is refuted.** That estimate re-priced the
model lever at the 3.2 W design estimate. At the measured 13.3654 W the marginal rate is
1.80e-05 rather than 1.28e-05, and the lever moves +1.7 % between the two hydrogen eras instead
of +39 %.

### 3.6 The MPC constants that follow

| Constant | Was | Is | Mechanism |
|:--|--:|--:|:--|
| `mpc_ems.H2_BASIS_REF_P_STACK_W` | 3.2 | **13.3654** | section 2.1; closes its `TODO(calibrate)` |
| `mpc_ems.EQ_H2_LAMBDA_SOC_PER_G` | 0.41 | **0.423** | restates the suite constant |
| `mpc_ems.RHO_METRIC_G_PER_SOC_H20` | 1.7697 | **2.364066** | see below |
| `sdp_alpha_sweep.EQ_H2_LAMBDA_SOC_PER_G` | 0.41 | **0.423** | restates the suite constant |

`RHO_METRIC_G_PER_SOC_H20` was `(1/lambda) * marginal_h20(H2_BASIS_REF_P_STACK_W) /
H2_GFC_DC_GAIN_GPS_PER_W`, a conversion that existed because lambda was measured in Gfc grams.
Lambda is now stated in H-20 grams, so the conversion **retires exactly as its own
`TODO(calibrate)` said it would** and the price is `1/lambda` = 2.364066 g(H-20)/SoC.

The +33.6 % move is a real change to the planner's terminal price, and both of its components
were errors in the same direction: the lambda was in the wrong unit (+3.2 %) and the reference
operating point the conversion was evaluated at was 3.2 W instead of 13.3654 W (the rest). The
old value under-priced terminal SoC and biased the planner toward spending the pack. Re-running
the MPC gates is phase-B item 6 and is **not** done here.

---

## 4. Alpha, and `sdp_policy_v7.json`

### 4.1 The decision (solver D16)

`--alpha-mode lever-h20`: D12's two-sided geometric-mean placement, unchanged, and D15's
billing, unchanged. The one thing that moves is the marginal hydrogen rate the lever algebra is
a ratio against.

    alpha = (1 - gamma) / sqrt(L_share * L_chg)
    L_share = 1/(m * V_pack * C_As),   L_chg = eta_chg * L_share
    m = h2_map.marginal_gps_per_w(13.3654 W) = 1.801474e-05 g/s/W

**Which lever pair prices it, and why the MODEL pair.** The five board readings are Gfc-gram
levers and cannot price an H-20 alpha. The only empirical H-20 pair available is walked, and a
walk is a model. The alpha is therefore taken from the model pair, for D15's own reason:
`build_stage()` bills the model constants, and an alpha priced on a pair the solve does not use
is precisely the incoherence D14 measured. The walked pair is carried as the artifact's
`share_measured`/`charge_measured` and is enforced by the tripwire, so a disagreement between
the two would be a refusal rather than a footnote.

### 4.2 The certificate

    C:/Users/ricky/miniforge3/python.exe tools/sdp_ems_solver.py \
        --eta-chg measured --alpha-mode lever-h20 \
        --out tools/sdp_policies/sdp_policy_v7.json --force

| Field | Value |
|:--|:--|
| alpha | **0.134041467771** (v6: 0.134110280093, **-0.05 %**) |
| mode | `lever-h20` |
| charger | `eta_chg` 0.801172836631146, basis `measured-round-trip` |
| hydrogen law | `h20`, stack-side |
| model levers | share 0.4167424, charge 0.3338827 SoC/g |
| walked levers | share 0.4222722, charge 0.3417529 SoC/g |
| admission threshold | 0.373019 SoC/g |
| model window | (0.119978, 0.149753) - **IN** |
| measured (walked) window | (0.118407, 0.146305) - **IN** |
| `--allow-out-of-window` | **not passed** |
| convex-map warning | retired for this mode (D16) |
| value iteration | 443 sweeps, sup-norm 9.646e-13, CONVERGED |
| charge cells | **46** of 2525 |
| policy sha256 | `5400660d84f09236b3d930558499f647b40b1ce064b324f0a4ae5fdc4ae6740d` |
| file sha256 | `c08873a9012c34e4c4fa4cd608f9be26f10dd26a7e49782b96fd5a539da15821` |

Compared against the walked pair at the **plant's** 0.88 instead - the era `ems_walk` prices a
charge window at by default - the window is (0.118407, 0.133548) and this alpha still lies
inside it, so the choice of era does not carry the certificate.

### 4.3 The charge cells, and the finding that does not close

`sdp_policy_v7` admits charging in 46 of 2525 cells. The handoff expected the re-derivation to
remove most of the 46 that v6's configuration admits under the H-20 law. It removes none,
because the re-derivation barely moves alpha: the operating point turned out to be near the
efficiency peak, so v6's pre-convex-map alpha was already very nearly the right number.

Where they are, exactly:

| Demand bin | Bus traction | Charge-arm stack power | SoC rows | Cells |
|--:|--:|--:|:--|--:|
| 0 | 0.50 W | 9.281 W (under `P_MAX`) | 0.554 to 0.599 | 46 |

All 46 sit in demand bin **0** at SoC rows **below** the 0.600 target: "charge when nearly idle
and below target". That is convexity, not a mispriced alpha. At 0.5 W of traction the stack
sits at 0.6 W and 8 % LHV efficiency; the charger's own 7.389 W bus draw lifts it to 9.28 W and
40 %, so the charge action buys SoC at a better **average** price than the lever algebra's
single-point **marginal** comparison can express.

**And that is the structural finding.** The bisected charge boundary under the H-20 law is
alpha = 0.131941692 (section 5), and v7's alpha sits **1.59 % above it**. The closed-form
tripwire simultaneously reports `charge: model REJECT (0.333883 vs 0.373019)`. Both statements
are correct in their own terms and they disagree about the outcome, because the closed form
assumes one marginal price per action and a convex map does not have one.

> **The D12 admission window is necessary but no longer sufficient under a convex hydrogen
> law.** A certificate that asserts "charging is rejected endogenously" is, on this axis, an
> assertion about a linearised model and not about the solve.

Practical impact on this artifact: bin 0 carries **0.035 %** of the TPM's observed dwell, and
none of the six offline walks in section 6 opens a single charge window under v7.

**No alpha was moved to make the count zero.** Placing alpha just under a bisected boundary
would be `--alpha-mode charge-edge` in reverse - a placement chosen for its outcome - which is
exactly what D12 rejected when it refused `--forbid-charge` as the shipped mechanism. The
options are recorded in section 8 as an operator ruling.

### 4.4 Are the remaining charge cells refused by the ceiling anyway?

No. The charge arm at bin 0 draws 9.281 W of stack power against `P_MAX_W` = 23.416 W, 60 %
under the ceiling. The ceiling does not touch them.

---

## 5. The alpha sweep under the H-20 law

`tools/sdp_policies/sweep_20260909_h20/`, 41 artifacts, solved at `--eta-chg measured` and
anchored on `sdp_policy_v7.json`. The anchor check reports **MATCH**: the index-8 artifact
reproduces v7's policy block.

    tools/sdp_alpha_sweep.py solve  --eta-chg measured \
        --sweep-dir tools/sdp_policies/sweep_20260909_h20 \
        --anchor-artifact tools/sdp_policies/sdp_policy_v7.json --force
    tools/sdp_alpha_sweep.py refine --eta-chg measured \
        --sweep-dir tools/sdp_policies/sweep_20260909_h20 \
        --anchor-artifact tools/sdp_policies/sdp_policy_v7.json \
        --bracket degeneracy 0.0700 0.0950 --bracket charge 0.1190 0.1350

### 5.1 The closed form does not predict either boundary

| Boundary | Bisected alpha | Closed form | Relative error | Solves |
|:--|--:|--:|--:|--:|
| degeneracy | **0.087451658** | 0.119978184 | **-27.1 %** | 21 |
| charge | **0.131941692** | 0.149753185 | **-11.9 %** | 19 |

In the retired era the same comparison agreed to 5.7e-08. Under a convex map it does not agree
at all, and the default bisection bracket - the closed-form bound widened by 10 % - **fails to
straddle either boundary**. It fails loudly, which is the design: `bisect_boundary()` verifies
both ends by a solve before it starts. `refine` therefore gained a `--bracket NAME LO HI`
override, taken here from the two adjacent grid points. A bracket is a search interval, not a
result.

Both boundaries move **down** relative to the closed form, and for one reason: at the low
fuel-cell powers where the marginal decision is made the H-20 map is much cheaper per watt than
the constant `k` claims (1.19e-05 against 1.667e-05 at 1 W), so the fuel term is smaller and the
SoC term wins at a lower alpha.

### 5.2 The three behaviour legs

| Leg | alpha range | Charge cells |
|:--|:--|--:|
| greedy (degenerate share map) | 0.051400 to 0.087014 | 0 |
| calibrated | 0.087889 to 0.131282 | 0 |
| charge admitting | 0.132601 to 0.514000 | 45 to 600 |

**The anchor is in the charge-admitting leg**, which is new: in the retired era the anchor sat
3.2 % below the charge boundary and defined the calibrated leg. Section 6 states what that does
to the pick rule.

---

## 6. The frontier decision, and the live picks

### 6.1 v7 replaces v6

Offline walks, suite anchor configuration (`governor=True`, `loss_map=plant_loss_map()`,
`dv0_v=0.013522`, `droop_scale_fc=0.9434`, `r_series_ohm=0.033`), strategy `sdp-v2` with an
explicit `policy_file`, equivalent hydrogen at lambda 0.423 with v6 as the SoC reference:

| Scenario | v6 h2 [g] | v6 dSoC | v7 h2 [g] | v7 dSoC | eq-H2, v7 vs v6 | Charge windows |
|:--|--:|--:|--:|--:|--:|--:|
| `ems-sdp` | 0.016109292 | -0.0010954 | 0.010540835 | -0.0028217 | **-9.2336 %** | 0 / 0 |
| `ems-ftp75-sdp` | 0.035033940 | -0.0135317 | 0.034709058 | -0.0136636 | **-0.0372 %** | 0 / 0 |
| `ems-ftp75c-sdp` | 0.016990486 | -0.0000498 | 0.016990486 | -0.0000498 | **0.0000 %** | 0 / 0 |

v7 wins or ties on all three, no walk saturates the map, and no walk opens a charge window.

**The verdict is stable.** The `ems-sdp` result rests on a SoC correction, so its sign is
lambda-dependent by construction; it flips only below **lambda = 0.310 SoC/g**, which is 27 %
under the shipped band's lower edge. Across the band itself the figure runs -9.19 % to -9.79 %.

`ems-ftp75c-sdp` is bit-identical under the two artifacts: the compensated cycle's trajectory
never leaves the rows and bins on which the two share maps agree.

**One observation the band round must confront, flagged and not diagnosed here.** Campaign I's
`ems-sdp` run - which played `sdp-v6` - has a Run-window hydrogen of **0.012346 g** on the
board, while the v6 walk in the suite's own anchor configuration predicts **0.016109 g**, a
+30 % walk-over-board gap. The same v6 artifact walked in the SWEEP's configuration (no
asymmetry triple, no loss map) gives 0.012726 g, within 3 % of the board. Which walk
configuration the restated bands are stated against is therefore a live question on the H-20
axis and not the settled matter it was on the retired one. It is phase-B checklist item 5.

### 6.2 The registry re-point

| Site | Was | Is |
|:--|:--|:--|
| `EMS_STRATEGIES` | - | `sdp-v7` added |
| `EMS_STRATEGY_META["sdp-v6"].frontier_eligible` | True | **False** |
| `EMS_STRATEGY_META["sdp-v7"].frontier_eligible` | - | **True** |
| `SCENARIOS["ems-sdp"]["ems"]` | `sdp-v6` | **`sdp-v7`** |
| `SCENARIOS["ems-ftp75-sdp"]["ems"]` | `sdp-v6` | **`sdp-v7`** |
| `ems-ftp75c-sdp` binding | `sdp-v6` | **`sdp-v7`** |
| `sdp_assert_calibrated_benchmark()` accepted modes | `lever`, `lever-measured` | + **`lever-h20`** |

`sdp-v6` stays registered as the eta-proxy-era calibration and loses
`require_calibrated_benchmark` with its frontier eligibility, because the registry asserts the
two agree. v6 still passes the certificate; it no longer demands it, exactly as `sdp-v3` and
`sdp-v4` do not.

> ⚠️ **The verbatim transfer that accompanied every previous SDP rebind ENDS HERE.** v3 to v4
> to v6 differed only in weight and agreed on every traversed row. v7 solves a **different
> objective**, and `ems-sdp`'s walk moves -34.6 % in raw hydrogen. **Every walk-derived
> expectation on the frontier SDP legs must be re-stated** - phase-B checklist item 5. Nothing
> in this change moved a band other than the lambda constant's own.

### 6.3 The live picks

`tools/sdp_policies/sweep_20260909_h20/live_picks.json`, keyed by the three alpha scenarios.
The selection rule is the predecessor's - the geometric midpoint of each leg's alpha range over
the points that exist, resolved to the nearest existing point in log-alpha - with one
**documented deviation that reverses the predecessor's**.

In `sdp_alpha_sweep_measured_20260908.md` the `cal` leg took the anchor instead of its midpoint,
because the anchor's declared role is the in-family control and every point in the leg walked
identically. Under the H-20 law **the anchor is no longer in the calibrated leg** (section 5.2),
so it cannot play that role, and `ems-sdp-alpha-cal` takes the leg midpoint. The anchor is
instead the lowest charge-admitting point - but making it the `charge` pick would turn that leg
into a same-artifact repeat of `ems-sdp` and destroy its contrast, so the midpoint rule is
applied there too. **All three legs therefore take their midpoint, and all three picks moved.**

| Scenario binding | Leg | Index (was) | alpha | Charge cells | Policy sha256 |
|:--|:--|--:|--:|--:|:--|
| `ems-sdp-alpha-greedy` | greedy | **2** (3) | 0.065497734 | 0 | `2ababa98...` |
| `ems-sdp-alpha-cal` | calibrated | **6** (8) | 0.106353697 | 0 | `ddd20c03...` |
| `ems-sdp-alpha-charge` | charge admitting | **14** (15) | 0.248412614 | 587 | `9b145221...` |

The greedy pick's index moved even though a share-0 map is billing-invariant, because the
*leg's own alpha range* moved: the degeneracy boundary is 0.087452 under the H-20 law against
the closed form's 0.119978, so the leg is shorter and its geometric midpoint lands on a
different grid point.

> ⚠️ **The `run_hil_suite.py` h2 bands on the three `ems-sdp-alpha-*` legs were NOT re-derived
> in this change**, and the two halves have always moved together before. They are phase-B
> checklist item 5. Until that lands the three alpha legs will FAIL their `*_h2_accounted`
> expectations for a known reason - a new pick on a new hydrogen law - and not for a board
> defect. Do not run a campaign on these legs before the bands are re-stated.

---

## 7. Charge admission against the 23.4 W ceiling (phase-B item 3)

### 7.1 The premise in the handoff is wrong: the 1010 census is the SPLIT arm

The handoff and the phase-B brief both state that "1010 of 2525 default SDP cells refuse the
charge action under `P_MAX`". They do not. `build_stage()` prints one census covering **both**
arms, and every one of the 1010 comes from the **split** arm:

| Demand bin | Bus power | Share-ladder points over `P_MAX` | TPM dwell |
|--:|--:|--:|--:|
| 20 | 20.5 W | 1 | 0.035 % |
| 21 | 21.5 W | 2 | 0.047 % |
| 22 | 22.5 W | 2 | 0.023 % |
| 23 | 23.5 W | 3 | 0.012 % |
| 24 | 24.5 W | 2 | 0.023 % |

10 (bin, share) control pairs x 101 SoC rows = **1010 control cells**, in bins carrying
**0.14 %** of the TPM's observed dwell in total. They are control cells, not policy cells: the
census counts controls the solver refused to evaluate, not states in which the policy is
constrained.

### 7.2 On the charge arm the ceiling refuses nothing that was not already forbidden

The charger's bus draw at `chg_a` = 0.8 A and `eta_chg` = 0.801173 is
`V_pack * i / eta` = **7.3892 W**, so the charge arm crosses `P_MAX` = 23.416 W of stack power
in every bin whose centre exceeds 12.518 W - bins **13 to 24**.

`charge_forbidden_bins()` already forbids bins **12 to 24**, by both of its rules
independently: the dwell cut lands at bin 11 (cumulative dwell 0.9136, 13 bins forbidden) and
the FC current budget forbids the same 13.

**Intersection: all of them.** The map's ceiling refuses **zero** additional charge cells. The
ceiling is not the binding constraint on charge admission at any demand the TPM describes; the
dwell quantile and the FC current budget bind first, and both by a wide margin.

### 7.3 The refusal is the physical answer, and the firmware confirms it

Confirmed against `teensy_controller.ino`: an FC-path charge window is **single-source**.
`assertFcChargeEnable()` holds `BT_BUS_ENABLE` LOW for the whole window - the mutual-exclusion
guard - so `I_tot == I_fc` and the share ratio is pinned at `DROOP_R_MIN`. The battery is
**off the bus** and cannot carry traction while the charger runs.

Traction plus charger on the fuel cell alone is therefore the **physical case**, not an
artefact of billing the whole charger to the FC. `build_stage()`'s `physical` accounting and
`charge_forbidden_bins()`'s rule (b) - `P_dem/V_bus + i_chg_bus > 0.85 * LIMIT_I_FC_MAX_A` -
are modelling the hardware as it is built.

### 7.4 The three charge-window scenarios against the ceiling

`P_MAX_W` = 23.4161 W of stack power is 19.9037 W on the bus through `ETA_BOOST`, i.e.
**1.2479 A** of bus current at 15.95 V. Campaign I, Run window, map-inverted stack power:

| Scenario | Peak `I_fc` [A] | Against 1.2479 A | Peak stack power [W] | Saturated ticks |
|:--|--:|:--|--:|--:|
| `charge-cruise` | 1.4033 | **OVER** | 13.608 (58 % of `P_MAX`) | **0** |
| `charge-to-full` | 0.7622 | under | 11.628 | **0** |
| `mppt-tracking` | 0.7368 | under | 10.207 | **0** |
| `ems-sdp` | 1.1993 | under | 19.277 (82 %) | **0** |

**No leg accrued a single saturated tick**, `charge-cruise` included. Two mechanisms, both
worth naming because each one alone would be enough:

1. The plant bills `FuelCellSource.v_terminal * fuel_cell.i` on the **source** side, and that
   source is not the brochure curve (12 cells, ~0.45 ohm - the documented two-curve gap). At
   the instant `charge-cruise` reaches 1.4033 A of bus current the map is billed 13.6 W, not
   the 26.3 W that `p_fc_w / ETA_BOOST` would imply.
2. That instant is the `OC_FC` latch transient. Immediately afterwards State 99 phase 2 lowers
   `FC_REG_ENABLE`, `stack_on` goes false, and the map bills zero.

**What the map would do above the ceiling, for the record.** `h2_map.rate_gps()` clamps the
current at `I_PMAX_A` = 3.40 A and returns 5.2809e-04 g/s. The rate is then a **floor**, not an
estimate, and the map is **flat**: extra fuel-cell power is free. Two consequences for scoring
a saturated span, neither of which arises on this campaign but both of which would:
`h2_cum_g` understates, and - more damaging to a comparison - the span carries **zero
discriminating power**, since every strategy is billed the same rate there.

### 7.5 The flag, not changed

⚠️ **The ceiling question returns with the `FuelCellSource` refit** (handoff item 8). Section
7.4's headroom exists because the plant's electrical fuel cell is the *less accurate* curve.
Once it is refitted to the brochure, the same bus currents map to the higher stack powers, and
`charge-cruise`'s 1.4033 A becomes 26.3 W - **12 % over `P_MAX`**. The `fw26-clamp-*` legs
already sit on the boundary by design. Nothing in this round changed a scenario; this is the
record that the refit round must re-run section 7.4's table before quoting a hydrogen total on
any leg that touches 1.2479 A of bus current.

---

## 8. Open, for the operator

1. **The tripwire under a convex map.** Section 4.3. The closed-form admission window certifies
   `v7` as rejecting charge while the solve admits 46 cells. Options: accept the closed form as
   a necessary-but-not-sufficient check and report the solved charge-cell count beside it
   (cheap, honest, no artifact moves); or replace the certificate's charge clause with the
   **bisected** boundary from the sweep (correct, but couples the certificate to a sweep folder
   and costs ~20 solves per check). **Not decided here.**
2. **Whether `sdp_policy_v7` should charge at all.** Its 46 cells are economically reasoned and
   practically inert (0.035 % dwell, zero windows in six walks). Placing alpha just below the
   bisected boundary 0.131941692 would zero them, at the cost of choosing a placement for its
   outcome. **Not done.**
3. **The lambda level is not board-measured on this axis.** Section 3.4. Campaign II's three
   alpha legs replace `EMS_EQ_H2_LAMBDA_SOC_PER_G`, its band, and both walked lever constants.
4. **`H2_BASIS_REF_P_STACK_W` is one campaign's bimodal median.** Section 2.1. Re-derive from
   the next campaign; do not carry it.
5. **Which walk configuration the H-20 bands are stated against.** Section 6.1's +30 % gap. The
   suite's anchor configuration and the sweep's configuration bracket the board from opposite
   sides on this axis. Phase-B item 5 has to choose, and the choice is now consequential.
6. **The MPC's terminal price moved +33.6 %** (section 3.6) and its committed plan moved with
   it: on the light-load 61 s fixture the cruise command drops five ladder rungs, 0.675 to
   0.2375, on a 3.1 % price change. Gate 1 still holds (2.436e-03 against the 5e-03 band) and
   the coarsening deviation collapsed to bit-identical, but the sensitivity is real and the
   gates are phase-B item 6.

---

## 9. Reversal path

- `sdp_policy_v6.json` regenerates unchanged under
  `--h2-map eta-proxy --eta-chg measured --alpha-mode lever-measured`. Its registration is
  untouched; only `frontier_eligible` and `require_calibrated_benchmark` moved, and both are
  one-line reverts.
- Re-pointing the three scenario bindings from `sdp-v7` back to `sdp-v6` restores the previous
  frontier exactly; no expectation band was restated in this change, so nothing has to be
  un-restated with it.
- Every alpha mode other than `lever-h20` computes exactly what it computed before:
  `model_levers()`'s new `k_gps_per_w` argument defaults to `None`, and `candidates.lever` is
  reported at the classic constant `k` in every mode, so no artifact shipped before 2026-09-09
  changes shape or value.
- `analytic_boundaries()` takes an `h2_law` argument; passing the retired law by name
  reproduces a pre-2026-09-08 sweep's brackets.
