# SDP alpha sweep at the measured charger billing, 2026-09-08

## 1. Purpose and scope

This document records the stochastic-DP (SDP) alpha sweep solved against the
**measured** charger billing, `--eta-chg measured` = 0.801172836631146. It
reports the 41-point sweep in `tools/sdp_policies/sweep_20260908_meas/`, the two
behaviour boundaries located by bisection, the offline evaluation of every point
on two stimuli, and the three points selected for live campaign use.

The sweep is the deferred item of `docs/modeling/sdp_alpha_resolve_20260903.md`
section 10.6 and of `WORK_QUEUE.md` section 0e item 20. It follows the operator
ruling of 2026-09-08, "rerun the alpha sweep, hold off on the DP re-solves". No
matched-DP record is re-solved in this round.

Two predecessor documents remain valid for their own eras.
`docs/modeling/sdp_alpha_sweep_20260901.md` records the 1:1 current-transfer
charger. `docs/modeling/sdp_alpha_sweep_eta088_20260902.md` records the model
billing at `ETA_CHG` 0.88 and is the direct predecessor of this one; section 7
below states the comparability rule against it.

The charger billing is defined by decision D15 of `tools/sdp_ems_solver.py`. The
literal `measured` resolves to `ETA_CHG_MEASURED_ROUND_TRIP`, which is derived
from the five lever readings of `EMS_LEVER_ETA_READINGS` as
`mean(L_chg)/mean(L_share)` = 0.3337114 / 0.4165286. A sixth reading moves it.

## 2. The eras this sweep carries

Two eras are recorded, and they are separate quantities.

The **solve era** is the charger billing every artifact was solved at. It is the
measured round trip, and every artifact in this folder declares
`charger.eta_chg_basis` = `measured-round-trip`, exactly as
`tools/sdp_policies/sdp_policy_v6.json` does. The manifest records the same
declaration in its own `eta_chg_basis` field.

The **plant era** is the simulator the offline walks of section 6 were run
against. It is the fw v28 governor era, and the manifest's new `plant` block
records its fingerprint:

| Quantity | Value |
|:--|:--|
| `hil_plant_sim` `constants_hash` | `e7c5f452ce694ef90f18da3d97f92e6dfffce52b0cba303efe5b52a9a1e7de1a` |
| `I_AUX_A` | 0.09 A |
| `ASYM_SIMPLE_I_MIN_A` | 0.08 A |

The walk itself prices a charge window at the plant's converter efficiency,
`eta_chg` 0.88, and not at the round trip. Section 10.3 of the alpha-resolve
document states the reason: the round trip is an accounting efficiency for the
energy-management objective, and it must not be written into
`hil_electrical.ETA_CHG`, which prices the plant.

## 3. The lever arithmetic and the two windows

Value iteration prices SoC at the discounted shadow price `alpha / (1 - gamma)`
grams per SoC, so a control whose lever is `L` is taken exactly when
`L > (1 - gamma) / alpha`. The share lever is era-invariant:

    L_share = 1 / (k * V_pack * C_As) = 0.450450450450 SoC/g

The modelled charge lever bills at the solve era, so at the measured round trip
it is

    L_chg = 0.801172836631146 * 0.450450450450 = 0.360888 SoC/g

and the modelled admission window - the alphas that admit the share lever and
reject the charge lever - opens from the eta-0.88 era's (0.111000, 0.126136) to

    ( 0.05/0.450450 , 0.05/0.360888 ) = ( 0.111000 , 0.138547 )

The measured-lever weight 0.134110280093 lies inside it. That is the whole point
of the ruling this sweep implements.

The **measured** window the sweep prints, (0.121359, 0.122481), is not that
window. It is `measured_levers()`'s old-era projection, which the solver keeps
for the pre-`lever-measured` modes; the sweep's grid points carry an explicit
alpha and therefore all solve with `--allow-out-of-window` regardless. The
predecessor sweep behaves the same way, and nothing in this document rests on
the projected pair.

## 4. The sweep

### 4.1 Grid and folder

The sweep is written to `tools/sdp_policies/sweep_20260908_meas/`, a new folder,
because the artifact filenames carry the alpha and not the era. It holds 41
artifacts, a `manifest.json`, and the pick file of section 6.

Points 0 to 20 are the 20-point geomspace over the bench alpha range
[0.0514, 0.514] plus the anchor, inserted in sorted position. The anchor is
`sdp_policy_v6.json`'s weight 0.134110280093, and it enters the grid at
**index 8**, one rung above the index 7 the v4 weight took - as predicted by
`test_the_v6_alpha_enters_the_grid_one_rung_above_the_v4_alpha()`. The 20
log-spaced points are untouched. Points 21 to 40 are the refinement of
section 5.

The anchor check reports **MATCH**: the index-8 artifact reproduces
`sdp_policy_v6.json`'s policy block, digest
`a7fd8893915c8b4577e5eb08425cf672aa8f4290140df506e15a3f6e888682f9`.

### 4.2 Invocation

    C:/Users/ricky/miniforge3/python.exe tools/sdp_alpha_sweep.py solve \
        --eta-chg measured \
        --sweep-dir tools/sdp_policies/sweep_20260908_meas \
        --anchor-artifact tools/sdp_policies/sdp_policy_v6.json --force

    C:/Users/ricky/miniforge3/python.exe tools/sdp_alpha_sweep.py refine \
        --eta-chg measured \
        --sweep-dir tools/sdp_policies/sweep_20260908_meas \
        --anchor-artifact tools/sdp_policies/sdp_policy_v6.json

### 4.3 The three tool changes this round needed

All three are additive and default to the previous behaviour.

- `--eta-chg` accepts the literal `measured` on the solving subcommands, and
  resolves it through the solver's own `_eta_chg_arg()` rather than through a
  copied number. The resolved value is a `MeasuredEtaChg` float subclass, and it
  is passed **through to the solver as the literal**, so every artifact declares
  `charger.eta_chg_basis`. `--walk-eta-chg` accepts the same literal.
- The manifest records `eta_chg_basis` beside `eta_chg`, on both the grid block
  and the refinement block.
- The manifest records the `plant` block of section 2. The plant constants are
  not a solver input, which is exactly why they have to be written down: a
  reader cannot infer the walk era from the artifacts.

## 5. The two behaviour boundaries, bisected

The method is unchanged from the predecessor: geometric bisection on the
log-alpha axis through the solver itself, both bracket ends verified by a solve
before the bisection starts, stop width 1e-6 relative. The brackets are the
era's own analytic thresholds widened by 10 % on each side.

| Boundary | Bisected alpha | Analytic alpha | Relative error | Half-width | Solves |
|:--|--:|--:|--:|--:|--:|
| degeneracy | 0.110999993716 | 0.111000000000 | -5.66e-08 | 4.25e-08 | 20 |
| charge | 0.138546876081 | 0.138546883924 | -5.66e-08 | 5.30e-08 | 20 |

The degeneracy boundary is **unmoved** at 0.111000, as it must be: it is
`(1-gamma)/L_share`, and the share lever never touches the charger. The charge
boundary moved **up** from the eta-0.88 era's 0.126136356495 to
**0.138546876081**, by the ratio 0.88 / 0.801173 = 1.0984. Both relative errors
are identical to three significant figures and are the bisection's own
interval-midpoint bias, not a physical offset.

The measured-lever weight **0.134110280093 lies between the two boundaries**. It
is 20.8 % above the degeneracy boundary and **3.2 % below the charge boundary**,
so charging is rejected endogenously with a margin of 3.2 % in alpha. Under the
eta-0.88 billing the same weight sat 6.3 % **above** the charge boundary and
admitted charging on 558 of 2525 cells. That inversion is the ruling of
`sdp_alpha_resolve_20260903.md` section 10, now re-measured by bisection rather
than asserted from the closed form.

Twenty refinement points are placed at `boundary * (1 -/+ d)` for `d` in
{0.5, 1, 2, 4, 8} %, five on each side of each boundary, indexed 21 to 40. The
two groups no longer interleave: the boundaries are 24.8 % apart, against 13.6 %
in the eta-0.88 era, and 8 % on each side of each does not reach the other.

## 6. Offline evaluation, and the three live points

Every point was walked offline through `tools/ems_walk.py` at the plant's
`eta_chg` 0.88, bound to the non-frontier `sdp-v2` strategy role, on `ems-sdp`
and `ems-ftp75-sdp`. Equivalent hydrogen is priced at `lambda = 0.41` SoC/g
against the anchor's SoC change on the same stimulus. The full per-point tables
are `sweep_eval_all_ems-sdp.csv` / `.md` and
`sweep_eval_all_ems-ftp75-sdp.csv` / `.md` in
`docs/modeling/sdp_alpha_sweep_measured_20260908/`, beside the two aggregate
figures.

A point is *greedy* when its share map is degenerate, *charge admitting* when at
least one cell selects charge, and *calibrated* otherwise.

| Leg | Indices | alpha range | Points | Charge cells |
|:--|:--|:--|--:|--:|
| greedy | 0 to 6, 21 to 25 | 0.051400000 to 0.110444994 | 12 | 0 |
| calibrated | 7 to 9, 26 to 35 | 0.111554994 to 0.137854142 | 13 | 0 |
| charge admitting | 10 to 20, 36 to 40 | 0.139239610 to 0.514000000 | 16 | 552 to 600 |

Scenario `ems-sdp`:

| Leg | h2 (g) | dSoC | eq-H2 (g) | Charge windows | vs. calibrated |
|:--|--:|--:|--:|--:|--:|
| greedy | 0.002766191 | -0.005232 | 0.0128117 | 0 | +0.674 % |
| calibrated (anchor) | 0.012726001 | -0.001113 | 0.0127260 | 0 | - |
| charge admitting | 0.015014630 | -0.000381 | 0.0132284 | 1 | +3.949 % |

Scenario `ems-ftp75-sdp`:

| Leg | h2 (g) | dSoC | eq-H2 (g) | Charge windows | vs. calibrated |
|:--|--:|--:|--:|--:|--:|
| greedy | 0.010557031 | -0.015717 | 0.0163793 | 0 | -0.176 % |
| calibrated (anchor) | 0.016408073 | -0.013330 | 0.0164081 | 0 | - |
| charge admitting | 0.016408073 | -0.013330 | 0.0164081 | 0 | 0 % |

Two observations follow, and the second is a loss of discrimination.

The calibrated leg is the eq-H2 minimum on `ems-sdp`, and the charge-admitting
leg is worse by 3.95 %, which is the offline expression of the ruling.

**The drive cycle no longer discriminates the charge leg.** On
`ems-ftp75-sdp` the charge-admitting artifacts open zero charge windows and walk
to the calibrated leg's totals digit for digit. In the eta-0.88 era that stimulus
opened one window and separated all three legs. The charge boundary has since
moved up by 9.8 %, so the charge cells sit at demand and SoC coordinates this
trajectory does not visit. On that stimulus the `charge` leg is now a same-law
repeat of the `cal` leg, and only `ems-sdp` separates the three.

Within a leg every walk total again coincides to nine decimals although the
policy tables differ, so a live run cannot discriminate two points inside one
leg. One point per leg is therefore selected.

The selection rule is the predecessor's: the geometric midpoint of each leg's
alpha range over the points that exist, resolved to the nearest existing point
in log-alpha. **The calibrated leg deviates**, and deliberately. Its midpoint,
0.124009, resolves to index 31 (alpha 0.127463), because the calibrated leg is
no longer symmetric about the anchor: the anchor sits 3.2 % under the upper
boundary while the lower boundary is 20.8 % away. The leg's declared role in
`hil_plant_sim.SCENARIOS` is the in-family control - "the sweep anchor, whose
policy block IS the shipped artifact" - and only the anchor satisfies it. Since
every point in the leg walks identically, the two choices are indistinguishable
offline and the role decides. The anchor is the pick.

| Scenario binding | Leg | Index | alpha | Charge cells | Policy sha256 |
|:--|:--|--:|--:|--:|:--|
| `ems-sdp-alpha-greedy` | greedy | 3 | 0.073936324258 | 0 | `2ababa984f4a158a...` |
| `ems-sdp-alpha-cal` | calibrated | 8 | 0.134110280093 | 0 | `a7fd8893915c8b45...` |
| `ems-sdp-alpha-charge` | charge admitting | 15 | 0.280417572369 | 593 | `38d4ef27f9b1d4a9...` |

The greedy pick's digest is **the same digest the eta-0.88 sweep selected**
(`2ababa98...`, index 3, the same alpha): a share-0 map has no remaining degree
of freedom, so the greedy leg is billing-invariant as well as era-invariant. The
calibrated pick's digest is `sdp_policy_v6.json`'s. The charge pick moved from
index 14 to index 15 because the leg's lower end moved up with the boundary.

The machine-readable form is
`tools/sdp_policies/sweep_20260908_meas/live_picks.json`, keyed by the three
scenario names above, and it carries the `plant` block of section 2.

## 7. Comparability with the eta-0.88 sweep

The artifacts of `tools/sdp_policies/sweep_20260902_eta088/` remain valid
policies and are not retracted. Three statements bound their comparison with
this folder.

1. An eta-0.88 artifact's alpha, admission windows and charge-cell count belong
   to the model billing. Its charge lever, 0.396396, is not this sweep's
   0.360888.
2. The h2, dSoC and eq-H2 columns of the two documents were walked against
   **different plants**, not only different billings: this sweep walks the fw
   v28 governor at `I_AUX_A` 0.09 A, and the predecessor walked the fw v26
   governor at 0.15 A. A leg-to-leg difference across the two documents is a
   difference of two plants and two billings at once, and no single-cause
   reading of it is available.
3. Only the era-invariant quantities carry across unchanged: the share lever,
   the degeneracy boundary at 0.111000, the greedy leg's policy digest, the
   demand map, the TPM, gamma and the share-ladder grid.

## 8. What the first fw v28 campaign should read

Every bound below is offline. No campaign has run any leg of this sweep, and the
fw v28 firmware was not flashed when it was solved.

1. **The `cal` leg against `ems-sdp` itself.** Both play `sdp_policy_v6.json`'s
   decision law on the same stimulus, so their h2 totals should agree to the
   same-config floor (65 ppm within a campaign, 250 ppm typical across
   campaigns). A disagreement is a binding or provenance defect, not a policy
   result.
2. **The `greedy` leg's h2 floor.** The sweep-native walk gives **0.002766191 g**
   on `ems-sdp`, which puts the +/- 25 % band at [0.00207464, 0.00345774].
   `run_hil_suite.py`'s `_FW28_FLOOR_VERDICT` quotes a fw v28 walk of
   **0.0009750 g** for the same leg against the current 0.003070 g floor. The
   two figures differ by 2.8x on what is the **same policy digest**
   (`2ababa98...`), so they differ in the walk configuration and not in the law.
   That discrepancy must be resolved before the greedy band is re-derived; it is
   not resolved here, and nothing is widened or lowered on the strength of one
   of the two numbers.
3. **The `charge` leg is single-stimulus.** It discriminates on `ems-sdp` (one
   window, 593 charge cells) and not on `ems-ftp75-sdp` (zero windows). A
   campaign that reads zero charge windows on the drive cycle is reading the
   modelled behaviour, not a defect.
4. **The charge lever's sixth reading.** It is one row of
   `EMS_LEVER_ETA_READINGS`, and it now moves the weight, the billing, the
   charge boundary and therefore this sweep. The lever's spread over campaigns C
   to F is 2.1 % and remains unexplained.

## 9. Deferred, and what is NOT done here

- **The three `ems-sdp-alpha-*` legs are NOT rebound.** They resolve their
  artifacts through `hil_plant_sim.SDP_LIVE_PICKS_PATH`, a module constant that
  still names `sweep_20260902_eta088/live_picks.json`. Moving them is a one-line
  change to that constant, plus the three `walk_h2_g` figures in
  `run_hil_suite.py`'s `_alpha_expectation()` calls and their leg comments.
  Both halves must move together: new bands against the old artifacts, or the
  reverse, would be a leg whose expectation describes a law it does not play.
  The pointer edit is outside this round's guardrails and awaits the operator.
- **No matched-DP record is re-solved**, per the ruling. The record key carries
  no policy file, weight or strategy, so none of the 75 records is stale on
  account of this sweep; the `I_AUX_A` provenance drift recorded on 2026-09-04
  is a separate item.
- **No figure set was rendered.** The predecessor's 164 per-point walk figures
  were not regenerated; the two aggregate figures are.

## 10. Reproduction

    SW=tools/sdp_policies/sweep_20260908_meas
    A=tools/sdp_policies/sdp_policy_v6.json
    D=docs/modeling/sdp_alpha_sweep_measured_20260908
    P=C:/Users/ricky/miniforge3/python.exe

    $P tools/sdp_alpha_sweep.py solve  --eta-chg measured --sweep-dir $SW \
        --anchor-artifact $A --force
    $P tools/sdp_alpha_sweep.py refine --eta-chg measured --sweep-dir $SW \
        --anchor-artifact $A
    $P tools/sdp_alpha_sweep.py evaluate --include all --sweep-dir $SW \
        --anchor-artifact $A --walk-eta-chg 0.88 \
        --scenario ems-sdp --scenario ems-ftp75-sdp --out $D

Wall time: 5 s to solve the 21 grid points, 11 s to bisect both boundaries and
solve the 20 refinement points, 124 s to evaluate all 41 points on both stimuli.

---

## Appendix A (2026-09-08): the greedy-leg walk discrepancy, settled, and the rebind

This appendix closes item 2 of section 8 and takes the rebind that section 9
deferred. Both halves of the deferral moved in one edit, as section 9 requires.

### A.1 The two numbers, reproduced

Section 8 item 2 records two figures for one policy digest (`2ababa98...`, the
greedy pick at index 3): the sweep-native walk at 0.002766191 g and
`run_hil_suite.py`'s `_FW28_FLOOR_VERDICT` figure at 0.0009750 g. Both are
reproduced from their own commands.

    P=C:/Users/ricky/miniforge3/python.exe

    # the sweep's configuration (section 10's `evaluate`, one point)
    $P -c "import sys; sys.path.insert(0,'tools'); import ems_walk as W;
           print(W.walk('sdp-v2','ems-sdp',
                 policy_file='tools/sdp_policies/sweep_20260908_meas/'
                             'alpha_03_0.073936.json', eta_chg=0.88).h2_g)"
    # -> 0.002766191432

    # the suite's configuration (the file's standard anchor invocation)
    $P -c "import sys; sys.path.insert(0,'tools');
           import ems_walk as W, hil_plant_sim as S;
           print(W.walk('sdp-sweep','ems-sdp-alpha-greedy', governor=True,
                 loss_map=S.plant_loss_map(), dv0_v=0.013522,
                 droop_scale_fc=0.9434).h2_g)"
    # -> 0.000844287876

### A.2 The difference that accounts for the ratio

The difference is the **asymmetry triple** `loss_map` / `dv0_v` /
`droop_scale_fc`, and nothing else. `ems_walk.walk()` defaults them to `None`,
0.0 and 1.0; the sweep's `evaluate` subcommand passes only `eta_chg`, so every
figure in section 6 is walked without them, while every anchor in
`run_hil_suite.py` is walked with them.

Five walks of the one artifact separate the axes.

| Configuration | h2 (g) | dSoC |
|:--|--:|--:|
| bare (the sweep's) | 0.002766191432 | -0.00523215 |
| `loss_map` only | 0.002721822944 | -0.00514612 |
| `dv0_v` only | 0.000861721488 | -0.00604525 |
| `droop_scale_fc` only | 0.000861136062 | -0.00604549 |
| all three (the suite's) | 0.000844287876 | -0.00594662 |

Either asymmetry term alone carries the whole effect; the loss map alone moves
the total by 1.6 %. The mechanism is the fuel cell's minority sliver: a share-0
map leaves the FC channel at the governor's conduction floor for the whole run,
and the droop asymmetry sets what that floor delivers. The greedy leg is the
only one of the three where the sliver is the entire fuel-cell contribution,
which is why it is the leg that moved 3.3x.

Four control walks establish that nothing else differs: the scenario name
(`ems-sdp` against `ems-sdp-alpha-greedy`) and the strategy name (`sdp-v2`
against `sdp-sweep`) are both inert, and all four combinations reproduce their
configuration's number to ten digits.

### A.3 The residual, and the campaign's configuration

The suite's quoted 0.0009750 g does not reproduce on the current tree; the
suite configuration gives 0.0008443 g. The figure is correct for the tree it
was walked on: at commit `e7ab118` the same invocation returns
0.0009749977374, and commit `c11a464` - the `governor_model` port of fw v28
rev 4-6 - moves it to 0.0008442878762 with everything else held. This was
confirmed by running the current tree against `e7ab118`'s `governor_model.py`,
which restores 0.0009750 exactly. The governor era is therefore 13.4 % of the
gap and the walk configuration is the remaining 3.3x.

**The suite configuration is the campaign's.** A suite child runs the live
scenario against the campaign's plant, which carries the loss map and the
converter asymmetry; a band centred on an asymmetry-free walk describes no run
the rig can produce. The sweep document's section 6 tables are internally
consistent and remain the correct basis for **comparing points within the
sweep**, where the omitted terms are common to every row; they are not a live
prediction, and section 8 item 2 should be read with that distinction.

### A.4 The rebind, and the re-derived anchors

`hil_plant_sim.SDP_LIVE_PICKS_PATH` now names
`tools/sdp_policies/sweep_20260908_meas/live_picks.json`. The three
`run_hil_suite.py` anchors were re-derived in the same edit under the
configuration of A.2, one process per leg.

| Leg | Old walk (g) | Old idx | New walk (g) | New idx | `alpha_h2_accounted` |
|:--|--:|--:|--:|--:|--:|
| greedy | 0.0040930228 | 3 | 0.0008442879 | 3 | 0.000633 (was 0.003070) |
| cal | 0.0126027355 | 7 | 0.0125240293 | 8 | 0.009393 |
| charge | 0.0150647315 | 14 | 0.0148082323 | 15 | 0.011106 |

The band contract is unchanged at +/- 25 % about the walk. The greedy floor
falls because the walk it is derived from was measured under the wrong
configuration, not because a band was widened to absorb a result; the
`_FW28_FLOOR_VERDICT` entry that called the leg unreachable is retired by this
re-derivation and says so at the anchor.

The calibrated leg is the check on the rebind. Its pick's policy block is now
byte-identical to `tools/sdp_policies/sdp_policy_v6.json`'s - the shipped
artifact - where the eta-0.88 folder's index-7 pick carried `sdp_policy_v4`'s.
Its suite-configuration walk is consequently **bit-identical to `ems-sdp`'s
own**, 0.0125240293 g at dSoC -0.00109539, which is exactly the in-family
control the leg is declared to be. The pinning test is
`test_the_alpha_legs_bind_to_the_measured_billing_sweep()`.

One provenance consequence is recorded rather than fixed: the bound artifacts
declare `charger.eta_chg_basis` = `measured-round-trip` and bill at 0.801173
where the plant's converter is 0.88, so `provenance["era_match"]` reads `False`
with the difference declared - the same arrangement `ems-sdp` has run under
since `sdp_policy_v6` shipped.
