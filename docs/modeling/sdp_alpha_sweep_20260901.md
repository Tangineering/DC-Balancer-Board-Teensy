# SDP alpha sweep, 2026-09-01

## 1. Purpose

The stochastic-DP energy-management objective prices SoC deviation by the weight
`alpha`. The shipped artifact `tools/sdp_policies/sdp_policy_v3.json` carries one
value of that weight, set by two-sided lever calibration (decision D12). This
document records a 21-point sweep of `alpha` over the bench-scaled range of the
full-scale study, so the operator can choose three points for live runs and so
the charge-admission boundary is located by measurement rather than by argument.

The sweep artifacts are offline-evaluation artifacts. Section 5 states the
condition under which one may reach the board.

## 2. Range derivation

The full-scale study (`references/EMS/SDP_EnergyManagement2.m`) swept
`alpha` over [100, 1000]. Round B scaled the full-size weight onto this rig by
coulombic energy, which mapped 500 onto 0.2569444. The scale factor is therefore

    k = 0.2569444 / 500 = 5.138889e-4

and the bench-scaled range is

    [100, 1000] * k = [0.0514, 0.5139] ~= [0.0514, 0.514].

The grid takes 20 log-spaced points over [0.0514, 0.514] (`numpy.geomspace`,
endpoints inclusive). The shipped lever-calibrated weight,
`alpha = 0.1629624189805737`, is added as a flagged 21st anchor point. The anchor
is an addition, not a replacement: deleting it leaves the log-spaced grid intact.

## 3. The grid

Indices are assigned after an ascending sort, so the anchor takes index 10.
`in_model` and `in_measured` report whether the point lies strictly inside the
modelled admission window (0.111000, 0.239250) and the campaign-measured window
(0.121359, 0.211506), both read from the shipped artifact's own
`alpha.admission` block.

| idx | alpha | in_model | in_measured | anchor | charge cells | value-iteration sweeps |
|---:|---:|:--|:--|:--|---:|---:|
| 0 | 0.051400 | no | no | | 0 | 424 |
| 1 | 0.058022 | no | no | | 0 | 426 |
| 2 | 0.065498 | no | no | | 0 | 429 |
| 3 | 0.073936 | no | no | | 0 | 431 |
| 4 | 0.083462 | no | no | | 0 | 433 |
| 5 | 0.094215 | no | no | | 0 | 436 |
| 6 | 0.106354 | no | no | | 0 | 438 |
| 7 | 0.120056 | yes | no | | 0 | 440 |
| 8 | 0.135524 | yes | yes | | 0 | 443 |
| 9 | 0.152984 | yes | yes | | 0 | 445 |
| 10 | 0.162962 | yes | yes | ANCHOR | 0 | 446 |
| 11 | 0.172695 | yes | yes | | 0 | 448 |
| 12 | 0.194944 | yes | yes | | 0 | 450 |
| 13 | 0.220060 | yes | no | | 0 | 452 |
| 14 | 0.248413 | no | no | | 288 | 455 |
| 15 | 0.280418 | no | no | | 294 | 457 |
| 16 | 0.316546 | no | no | | 294 | 459 |
| 17 | 0.357329 | no | no | | 294 | 462 |
| 18 | 0.403367 | no | no | | 296 | 464 |
| 19 | 0.455336 | no | no | | 298 | 466 |
| 20 | 0.514000 | no | no | | 300 | 469 |

Every point converged (final sup-norm delta below the 1e-12 tolerance). Each
solve took approximately 0.2 s of wall time, so the whole sweep runs in about
five seconds.

## 4. Solver invocation

Each point is solved through `sdp_ems_solver.main(argv)` with

    --alpha <value> --demand-map 0.0 25.0 --out <artifact> [--allow-out-of-window]

An explicit `--alpha` overrides `--alpha-mode` entirely
(`tools/sdp_ems_solver.py:1092-1096`): the requested value is written to
`alpha.value` exactly, and `alpha.mode` records the string `"explicit"`. The
sweep therefore never passes `--alpha-mode`. The D12 admission tripwire refuses
a solve whose alpha lies outside either window, so `--allow-out-of-window` is
added for exactly the points marked "no" in Section 3. The demand map is the
consumer-owned rig-scale map [0, 25] W (decision D11), which is also the solver
default; it is passed explicitly so the artifact's `argv` records it.

## 5. Admission windows and live use

Twelve of the 21 points lie outside at least one admission window. Points 8-12
lie inside both. The consumer-side certificate
`sdp_assert_calibrated_benchmark()` (`tools/hil_plant_sim.py:4103`) requires
`alpha.mode == "lever"` in addition to both window flags, so **no sweep artifact
can be bound to the frontier-scored `sdp-v3` strategy** — including the anchor,
whose explicit alpha makes its mode `"explicit"` rather than `"lever"`. A sweep
point reaches the board only through the non-frontier `sdp-v2` role, which the
certificate's own refusal text names as the correct destination for an
uncertified artifact. A run so bound is a dynamics demonstration, and its
hydrogen and SoC pair must not be placed on the EMS frontier.

## 6. Artifact identity

Two digests are recorded per point, and they answer different questions.

- `policy_sha256` is the digest of the `policy` block alone, matching the
  consumer's identity rule (`load_sdp_policy`, `tools/hil_plant_sim.py:4063-4080`).
  It is the decision law, and it is invariant to `generated_utc`, `argv`, and the
  alpha provenance block.
- `file_sha256` is the digest of the whole file. It moves on every regeneration
  because `generated_utc` moves. Never pin it.

**Anchor verification: MATCH.** The anchor point's `policy_sha256` is
`0443febf240a9f5c207c42595f5841d2842496ac786c4d5342f1f8dfe33c61a2`, identical to
`sdp_policy_v3.json`'s. The explicit-alpha path therefore reproduces the shipped
decision law bit for bit against the same TPM, demand map, and grid arguments.

## 7. Where charging enters the policy

Charging is absent from the policy for every point up to and including
alpha = 0.220060, and present from alpha = 0.248413 upward. A geometric
bisection between those two points, run through the solver's `--dry-run` path,
locates the boundary at

    alpha_charge = 0.23925 (+/- 1e-5)

which is the upper end of the modelled admission window, (0.111000, 0.239250),
to five decimal places. The window arithmetic and the solved policy therefore
agree: charging is taken exactly when the shadow price `alpha/(1-gamma)` makes
the modelled Ag105 charge lever worth its hydrogen. Above the boundary the charge
cell count rises slowly with alpha, from 288 cells at 0.248413 to 300 cells at
0.514000, out of 2525 policy cells.

A second structural boundary sits at the other end of the grid. Points 0 to 6
(alpha <= 0.106354) command share 0.0 in **every** policy cell: the SoC term is
too weak to buy any fuel-cell bias, and the policy collapses to pure hydrogen
greed. Points 7 upward carry a non-degenerate share map. The sweep therefore
brackets both degeneracies, which is the property that makes it useful for
choosing live points.

## 8. Offline evaluation

Every point was walked offline through `tools/ems_walk.py` bound to `sdp-v2`
(Section 5), on two stimuli: `ems-sdp` (the 61 s comparison scenario) and
`ems-ftp75-sdp` (the 340 s drive cycle). Equivalent hydrogen prices the SoC
difference against the anchor at lambda = 0.41 SoC/g
(`tools/run_hil_suite.py:6497`).

These figures come from the corrected walk (post-fix-round `ems_walk.py`: the
`ems-sdp` drain profile and the state-gated governor with firmware-like bus
re-assertion). The anchor's `ems-sdp` hydrogen is 0.0126027 g, +0.48 % against
the campaign-measured 0.0125424 g. Any earlier figure from this sweep is
superseded.

### 8.1 Scenario `ems-sdp`

| points | alpha range | h2 (g) | dSoC | eq-H2 (g) | charge windows |
|:--|:--|---:|---:|---:|---:|
| 0-6 | 0.051400 - 0.106354 | 0.00409302 | -0.0051763 | 0.0126924 | 0 |
| 7-13 (incl. anchor) | 0.120056 - 0.220060 | 0.01260270 | -0.0016506 | 0.0126027 | 0 |
| 14-20 | 0.248413 - 0.514000 | 0.01673160 | -0.0007880 | 0.0146277 | 1 |

### 8.2 Scenario `ems-ftp75-sdp`

| points | alpha range | h2 (g) | dSoC | eq-H2 (g) | charge windows |
|:--|:--|---:|---:|---:|---:|
| 0-6 | 0.051400 - 0.106354 | 0.0327379 | -0.0304816 | 0.0614450 | 0 |
| 7-20 (incl. anchor) | 0.120056 - 0.514000 | 0.0610959 | -0.0187117 | 0.0610959 | 0 |

### 8.3 Observations

1. **Charge windows now open, on `ems-sdp` only.** Every charge-admitting
   artifact (points 14-20) opens exactly one charge window on `ems-sdp`, and
   none on the drive cycle. The charge boundary of Section 7 is therefore
   observable in behaviour, not only in the table. It costs hydrogen: those
   points consume 32.8 % more hydrogen than the calibrated band and finish
   16.1 % worse in equivalent hydrogen, for 0.00086 SoC of extra charge. This
   reproduces the standing charge-economics finding on a new axis.
2. **The "points 7-20 indistinguishable" claim from the pre-fix walk does not
   survive on `ems-sdp`.** The grid now resolves into three legs there, split at
   both boundaries the solver predicted: the share degeneracy at
   alpha <= 0.106354 and the charge admission at alpha = 0.23925. On
   `ems-ftp75-sdp` the claim does survive: points 7 through 20 are identical to
   every digit, because that stimulus never reaches an admitted charge bin.
3. **The calibrated band wins on both stimuli, and the margin is no longer
   knife-edge on the low side.** On `ems-sdp` the anchor band leads the
   degenerate leg by 0.71 % and the charge-admitting leg by 16.1 % in equivalent
   hydrogen; on the drive cycle it leads the degenerate leg by 0.57 %. The
   ordering is the same on both stimuli, which the pre-fix walk did not show.
   The 0.57-0.71 % margins are still inside the lambda band (0.409, 0.415), so
   the degenerate-leg comparison remains a weak result; the 16.1 % charge-leg
   margin is not.
4. **For choosing three live points**, `ems-sdp` is the discriminating stimulus:
   one point from each leg (for example idx 3, the anchor at idx 10, and idx 17)
   produces three distinct runs. Three points drawn from 7-20 would be identical
   on the drive cycle and distinct on `ems-sdp` only if they straddle 0.23925.

The figures `sdp_alpha_sweep_20260901/sweep_h2_vs_dsoc_<scenario>.png` plot
hydrogen against SoC change with alpha annotated; the tables above are
reproduced per scenario in `sweep_eval_<scenario>.md` and as CSV in
`sweep_eval_<scenario>.csv`.

## 9. Reproduction

    C:/Users/ricky/miniforge3/python.exe tools/sdp_alpha_sweep.py grid
    C:/Users/ricky/miniforge3/python.exe tools/sdp_alpha_sweep.py solve --force
    C:/Users/ricky/miniforge3/python.exe tools/sdp_alpha_sweep.py evaluate \
        --scenario ems-sdp --scenario ems-ftp75-sdp         --out docs/modeling/sdp_alpha_sweep_20260901/

`evaluate --self-test` exercises the evaluation path against a synthetic walk
result and writes a `selftest` table, for use when the walk module is
unavailable.
