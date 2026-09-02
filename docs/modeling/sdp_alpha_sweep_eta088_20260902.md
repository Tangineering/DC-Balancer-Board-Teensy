# SDP alpha sweep in the charge-efficiency era, 2026-09-02

## 1. Purpose and scope

This document records the stochastic-DP (SDP) alpha sweep solved against the
energy-conserving Ag105 charger model at `ETA_CHG = 0.88`. It reports the
shipped artifact `tools/sdp_policies/sdp_policy_v4.json`, the 41-point sweep in
`tools/sdp_policies/sweep_20260902_eta088/`, the offline evaluation of every
point on two stimuli, and the three points selected for live campaign use.

The predecessor document, `docs/modeling/sdp_alpha_sweep_20260901.md`, records
the same procedure against the 1:1 current-transfer charger. That document
remains valid for its own era. Section 8 states the comparability rule between
the two.

The charger era is defined in `tools/charger_power.py` and in decision D13 of
`tools/sdp_ems_solver.py`. In the earlier era the charger moved current, so one
delivered amp cost `V_bus` watts. In this era the charger converts energy, so
one delivered amp costs `V_pack / eta_chg` watts.

## 2. The lever arithmetic

A lever is an exchange rate in SoC per gram of hydrogen. Value iteration prices
SoC at the discounted shadow price `alpha / (1 - gamma)` grams per SoC, so an
action is taken exactly when its lever exceeds the admission bound
`(1 - gamma) / alpha`.

The share lever never touches the charger and is therefore era-invariant:

    L_share = 1 / (k * V_pack * C_As) = 0.450450450450 SoC/g

The charge lever bills at the era's charger voltage. In this era both levers
bill at the pack voltage and differ only by the conversion loss, so the charge
lever is the share lever times the efficiency:

    L_chg = eta_chg * L_share = 0.88 * 0.450450450450
          = 0.396396396396 SoC/g

The previous era's value was `L_chg = 0.208986417000 SoC/g`, computed at the
bus voltage. The two levers were 2.155 times apart; they are now `1/eta_chg`
= 1.136 times apart.

The leg widths collapse in the same ratio. The calibrated interval — the alphas
that admit the share lever and reject the charge lever — is

    ( (1-gamma)/L_share , (1-gamma)/L_chg )
      = (0.111000000000, 0.126136363636)     [this era]
      = (0.111000000000, 0.239250000000)     [the previous era]

Its lower end is fixed by the era-invariant share lever, and its upper end moves
with the charger. Note that the interval width in log-alpha is exactly
`ln(1/eta_chg) = 0.1278`, whatever the pack, the bus, or the capacity do.

## 3. The shipped artifact `sdp_policy_v4.json`

### 3.1 The ruling

The operator rule is that alpha follows the DP. Work package WP-1B1 regenerated
the eta-era matched DP tables and reported that the DP charges on zero stages on
`ems-sdp` and on `ems-ftp75-dp`. The alpha rule that agrees with that behaviour
is `--alpha-mode lever`, which places alpha at the geometric mean of the two
admission thresholds and therefore rejects the weaker lever structurally. The
`charge-edge` mode, which places alpha just inside the charge lever's admission
window, is retained as a sweep point and is not shipped.

### 3.2 Reproduction of the predecessor

Before the new artifact was solved, `sdp_policy_v3.json` was reproduced with

    C:/Users/ricky/miniforge3/python.exe tools/sdp_ems_solver.py \
        --eta-chg-none --alpha-mode lever --out <scratch> --force

The reproduction's policy block digest is
`0443febf240a9f5c207c42595f5841d2842496ac786c4d5342f1f8dfe33c61a2`, which is
`sdp_policy_v3.json`'s digest exactly. The recorded alpha, 0.1629624189805737,
is also exact. The solver therefore still reproduces the previous era on demand,
and the changes of the intervening round did not disturb it.

### 3.3 The solve

    C:/Users/ricky/miniforge3/python.exe tools/sdp_ems_solver.py \
        --eta-chg 0.88 --alpha-mode lever \
        --out tools/sdp_policies/sdp_policy_v4.json --force

That argument vector is recorded verbatim in the artifact's `argv` field.
(`sdp_policy_v3.json` records an empty `argv`, because it was baked from the
defaults; the explicit invocation above makes this artifact reproducible from
its own record.)

| Quantity | Value |
|:--|:--|
| alpha | 0.11832639757736393 |
| alpha mode | `lever` |
| shadow price | 2.366527951547 g/SoC |
| admission bound | 0.422559978362 SoC/g |
| model levers (share / charge) | 0.450450450450 / 0.396396396396 SoC/g |
| measured levers (share / projected charge) | 0.412000 / 0.448393 SoC/g |
| model window, intent "admit share, reject charge" | (0.111000000000, 0.126136363636) |
| `window_intent` | `admit share, reject charge` |
| `in_window_model` | `true` |
| `window_measured` / `in_window_measured` | `null` / `null` |
| charge-enabled policy cells | 0 |
| `charge_forbidden_bins` | 12 … 24 (13 bins; the previous era forbade 19) |
| value iteration | 440 sweeps, final sup-norm delta 9.83394e-13, converged |
| policy sha256 | `8ca7dceeeaeb16257aa18eb889d3d76df38dbe10ea94e8574249984c078fd770` |
| file sha256 | `4877ad698ef07e6039b5570a3903851fbe4d1454fdc514f01921fbbfc5ed3c26` |

The admission bound sits 6.19 % below the share lever and 6.60 % above the
charge lever, in place of the previous era's 47 % and 32 %. Charging is
therefore rejected endogenously, by the economics, and not by the
`--forbid-charge` mask, which is off in this artifact.

⚠️ The overnight ruling in `OVERNIGHT_LOG.md` names the policy digest
`6c4843bb…`. The digest computed here is `8ca7dcee…`, and it agrees bit for bit
with the independent WP-1B1 candidate held in the scratchpad
(`cand_eta088_lever.json`). Every substantive quantity in the ruling — the mode,
alpha to nine digits, and the zero charge cells — is confirmed. The `6c4843bb…`
string matches neither the policy digest nor the file digest of either solve and
is read as a transcription error in the log, not as a divergence in the solve.

### 3.4 The measured-lever inversion

The measured share lever, 0.412 SoC/g, was measured on campaign
`hil_report_20260831_191509` and is era-invariant. The measured charge lever was
measured as 0.2364 SoC/g on campaigns `20260831_222036` and `20260901_000816`,
whose plant billed the charger at the bus voltage. `measured_levers()` projects
it onto this era by the ratio of the two billing voltages, giving 0.448393
SoC/g.

Under that projection the measured charge lever **overtakes** the measured share
lever: the measurement orders the two controls the opposite way from the model,
which puts the charge lever below the share lever by exactly `1/eta_chg`. The
intent "admit share, reject charge" then has no interval of alpha that satisfies
it, so the solver writes `window_measured: null` and `in_window_measured: null`
rather than a pair it cannot compute, and the artifact reports the window as
UNDECIDABLE rather than as passed.

⚠️ No decision in this document rests on the projected measured pair. The
projection assumes that the campaign accounting scales with the billing voltage
and with nothing else, which is exactly the assumption the first eta-era
campaign tests. `TODO(verify)`: re-measure the charge lever on the first
post-2026-09-01 campaign and replace the projection with the measurement.

## 4. The sweep

### 4.1 Grid and folder

The sweep is written to `tools/sdp_policies/sweep_20260902_eta088/` — a new
folder, because artifact filenames carry the alpha and not the era, so a
same-folder solve would overwrite the previous era's points. It holds 41
artifacts, a `manifest.json` whose `eta_chg` field records 0.88, and the pick
file of Section 7.

Points 0 … 20 are the 20-point geomspace over the bench alpha range
[0.0514, 0.514] plus the v4 anchor at index 7, inserted in sorted position. The
range derivation is unchanged and is given in Section 2 of the predecessor
document. Points 21 … 40 are the refinement of Section 5.

The anchor check compares the anchor point's policy block against the shipped
artifact and reports MATCH: the sweep's index-7 artifact reproduces
`sdp_policy_v4.json`'s policy block, digest `8ca7dcee…`.

### 4.2 Invocation

    C:/Users/ricky/miniforge3/python.exe tools/sdp_alpha_sweep.py solve \
        --eta-chg 0.88 \
        --sweep-dir tools/sdp_policies/sweep_20260902_eta088 \
        --anchor-artifact tools/sdp_policies/sdp_policy_v4.json --force

    C:/Users/ricky/miniforge3/python.exe tools/sdp_alpha_sweep.py refine \
        --eta-chg 0.88 \
        --sweep-dir tools/sdp_policies/sweep_20260902_eta088 \
        --anchor-artifact tools/sdp_policies/sdp_policy_v4.json

## 5. The two behaviour boundaries, bisected

### 5.1 Method

Each boundary is located by geometric bisection on the log-alpha axis through
the solver itself, with the predicate false below the boundary and true above
it. The degeneracy predicate is "the solved share map commands a non-zero share
in at least one cell"; the charge predicate is "at least one policy cell selects
`charge_goal > 0`". Both bracket ends are verified by a solve before the
bisection starts, so a bracket that does not straddle the boundary is an error
and not a silently wrong answer. The stop width is 1e-6 relative.

The brackets are the era's own analytic thresholds widened by 10 % on each side.
The previous era's literal brackets could not be reused: its charge bracket,
(0.220060, 0.248413), no longer straddles anything, because the charge boundary
moved to 0.126136.

### 5.2 Results

| Boundary | Bisected alpha | Analytic alpha | Relative error | Half-width | Solves |
|:--|--:|--:|--:|--:|--:|
| degeneracy | 0.110999993716 | 0.111000000000 | −5.66e−08 | 4.25e−08 | 20 |
| charge | 0.126136356495 | 0.126136363636 | −5.66e−08 | 4.83e−08 | 20 |

The analytic thresholds are `(1-gamma)/L_share` and `(1-gamma)/L_chg`, the two
ends of the calibrated interval of Section 2. Both hold to 5.66e−08 relative,
which is the same order as the previous era's ≤ 1.2e−07 and is below the
bisection's own stop width. The two relative errors are identical to three
significant figures, which identifies the residual as the bisection's own
interval-midpoint bias rather than as a physical offset in either boundary.

What the bisection establishes is not the closed form, which is the solver's own
algebra, but that the SoC grid, the `J` interpolation over that grid, and the
forbidden-bin mask do not displace the analytic threshold.

### 5.3 The refinement points

Twenty points are placed at `boundary * (1 -/+ d)` for `d` in
{0.5, 1, 2, 4, 8} %, five on each side of each boundary, indexed 21 … 40 in
ascending alpha within each boundary group. The pair straddling a boundary
differs by 1 % in alpha.

Because the two boundaries are now only 13.6 % apart, the two refinement groups
interleave: the degeneracy group's outermost point above (index 30, alpha
0.119880) sits inside the charge group's span, and the charge group's outermost
point below (index 31, alpha 0.116045) sits inside the degeneracy group's. Both
groups nevertheless lie wholly on the correct side of their own boundary, and no
refinement point crosses the other group's boundary. In the previous era, where
the boundaries were 2.155 times apart, the two groups were disjoint.

## 6. Offline evaluation

Every point is walked offline through `tools/ems_walk.py` at `eta_chg = 0.88`,
bound to the non-frontier `sdp-v2` strategy role, on two stimuli. Equivalent
hydrogen is priced at `lambda = 0.41` SoC/g against the v4 anchor's SoC change
on the same stimulus:

    eq_H2 = h2 - (dSoC - dSoC_anchor) / lambda

The walk is the governed offline walk, not a board run. Its fidelity boundaries
are those of `tools/ems_walk.py`: the DP demand model, no Youla dynamics, and
charge admission by the DP mask.

### 6.1 The three legs

The legs are identified by policy behaviour, not by alpha: a point is *greedy*
when its share map is degenerate (share 0.0 in all 2525 cells), *charge
admitting* when at least one cell selects charge, and *calibrated* otherwise.

| Leg | Indices | alpha range | Charge cells |
|:--|:--|:--|--:|
| greedy | 0 … 6, 21 … 25 (12 points) | 0.051400000 … 0.110444994 | 0 |
| calibrated | 7, 8, 26 … 35 (12 points) | 0.111554994 … 0.125505675 | 0 |
| charge admitting | 9 … 20, 36 … 40 (17 points) | 0.126767038 … 0.514000000 | 540 … 600 |

### 6.2 Scenario `ems-sdp`

| Leg | h2 (g) | dSoC | eq-H2 (g) | Charge windows | vs. calibrated |
|:--|--:|--:|--:|--:|--:|
| greedy | 0.004093023 | −0.005176398 | 0.012692424 | 0 | +0.7117 % |
| calibrated (anchor) | 0.012602735 | −0.001650644 | 0.012602735 | 0 | — |
| charge admitting | 0.015064732 | −0.000848219 | 0.013107600 | 1 | +4.0060 % |

### 6.3 Scenario `ems-ftp75-sdp`

| Leg | h2 (g) | dSoC | eq-H2 (g) | Charge windows | vs. calibrated |
|:--|--:|--:|--:|--:|--:|
| greedy | 0.016205300 | −0.016210302 | 0.019348465 | 0 | +0.0077 % |
| calibrated (anchor) | 0.019346974 | −0.014921605 | 0.019346974 | 0 | — |
| charge admitting | 0.020032979 | −0.014691883 | 0.019472681 | 1 | +0.6498 % |

The full per-point tables are `sweep_eval_all_ems-sdp.csv` /`.md` and
`sweep_eval_all_ems-ftp75-sdp.csv` /`.md` beside this document.

### 6.4 Observations

The shipped calibrated leg is the eq-H2 minimum on both stimuli. The
charge-admitting leg is worse by 4.01 % on `ems-sdp` and by 0.65 % on the drive
cycle, which is the offline expression of the ruling: admitting the charge lever
at this efficiency costs hydrogen at the campaign exchange rate.

Both stimuli discriminate all three legs in this era. In the previous era the
drive cycle did not: its points 7 … 20 were identical, because no bin was
admitted for charging on that stimulus. The charge boundary has since moved down
to 0.126136, and one charge window now opens on the drive cycle as well.

Within a leg the walk totals coincide to nine decimals although the policy
tables differ. The calibrated leg's twelve points carry ten distinct policy
digests, and its extreme point (index 26) differs from the anchor in 125 of 2525
share cells; the walk trajectory nevertheless never visits a differing cell. The
consequence for campaign design is that a live run cannot discriminate two
points inside one leg either, which is why Section 7 selects one point per leg
and not three points inside one.

The greedy leg's twelve points carry a single policy digest, as they must: a map
that is share-0 in every cell has no remaining degree of freedom.

## 7. The three live points

The selection rule is the geometric midpoint of each leg's alpha range over the
sweep points that exist, resolved to the nearest existing point in log-alpha.

| Scenario binding | Leg | Index | alpha | Charge cells | Policy sha256 |
|:--|:--|--:|--:|--:|:--|
| `ems-sdp-alpha-greedy` | greedy | 3 | 0.073936324258 | 0 | `2ababa984f4a158a…` |
| `ems-sdp-alpha-cal` | calibrated | 7 | 0.118326397577 | 0 | `8ca7dceeeaeb1625…` |
| `ems-sdp-alpha-charge` | charge admitting | 14 | 0.248412614263 | 591 | `00dede9db9a610d6…` |

The calibrated leg's geometric midpoint is 0.118324912, and the anchor sits
1.26e−05 away from it in log-alpha. That coincidence is structural rather than
fortunate: the leg is bounded by the two boundaries scaled by (1 ± 0.005), and
the `lever` alpha is by construction the geometric mean of those same two
boundaries. The anchor is therefore the pick, and the live calibrated point is
the shipped policy `sdp_policy_v4.json` itself.

Walked metrics for the three picks:

| Index | `ems-sdp` h2 (g) | `ems-sdp` dSoC | `ems-ftp75-sdp` h2 (g) | `ems-ftp75-sdp` dSoC |
|--:|--:|--:|--:|--:|
| 3 | 0.004093023 | −0.005176398 | 0.016205300 | −0.016210302 |
| 7 | 0.012602735 | −0.001650644 | 0.019346974 | −0.014921605 |
| 14 | 0.015064732 | −0.000848219 | 0.020032979 | −0.014691883 |

The machine-readable form is
`tools/sdp_policies/sweep_20260902_eta088/live_picks.json`, keyed by the three
scenario names above.

## 8. Comparability with the previous era

The artifacts of `tools/sdp_policies/sweep_20260901/` remain valid policies:
they are converged solutions of a stated objective, and nothing about them has
been retracted. Their hydrogen pricing, however, is old-era. Three statements
follow.

1. An old-era artifact's recorded alpha, admission windows, and charge-cell
   count belong to the 1:1 current-transfer charger, and its charge lever
   (0.208986) is not this plant's.
2. The h2, dSoC, and eq-H2 columns of the predecessor document's evaluation
   tables were walked in the old era and must not be differenced against this
   document's tables. A leg-to-leg comparison across the two eras is a
   comparison of two plants, not of two policies.
3. Only the era-invariant quantities carry across unchanged: the share lever,
   the degeneracy boundary at 0.111, the demand map, the TPM, gamma, and the
   share-ladder grid.

## 9. Figures

Each sweep point carries two figures synthesized from its offline walk, under
`plots/<scenario>/alpha_<idx>_<alpha>/`. They carry a `walk_` filename prefix
and an "OFFLINE GOVERNOR WALK … not a board run" suptitle, so that neither a
glob nor a reader can mistake one for a campaign figure. 164 figures were
rendered over the two stimuli.

One pair per leg, on `ems-sdp` — the three live picks:

![greedy, index 3](plots/ems-sdp/alpha_03_0.073936/walk_currents_and_share.png)
![greedy, index 3](plots/ems-sdp/alpha_03_0.073936/walk_hil_charger_and_soc.png)

![calibrated, index 7 (the anchor)](plots/ems-sdp/alpha_07_0.118326/walk_currents_and_share.png)
![calibrated, index 7 (the anchor)](plots/ems-sdp/alpha_07_0.118326/walk_hil_charger_and_soc.png)

![charge admitting, index 14](plots/ems-sdp/alpha_14_0.248413/walk_currents_and_share.png)
![charge admitting, index 14](plots/ems-sdp/alpha_14_0.248413/walk_hil_charger_and_soc.png)

The immediate neighbours of the degeneracy boundary (indices 25 and 26, 1 %
apart in alpha):

![index 25, below](plots/ems-sdp/alpha_25_0.110445/walk_currents_and_share.png)
![index 26, above](plots/ems-sdp/alpha_26_0.111555/walk_currents_and_share.png)

The immediate neighbours of the charge boundary (indices 35 and 36):

![index 35, below](plots/ems-sdp/alpha_35_0.125506/walk_hil_charger_and_soc.png)
![index 36, above](plots/ems-sdp/alpha_36_0.126767/walk_hil_charger_and_soc.png)

The two aggregate views are `sweep_h2_vs_alpha_all_<scenario>.png`, which draws
both quantities as step functions of alpha with the two boundaries marked, and
`sweep_h2_vs_dsoc_all_<scenario>.png`, which draws one marker per behaviour leg.

## 10. Reproduction

    # the shipped artifact
    C:/Users/ricky/miniforge3/python.exe tools/sdp_ems_solver.py \
        --eta-chg 0.88 --alpha-mode lever \
        --out tools/sdp_policies/sdp_policy_v4.json --force

    # the sweep, its refinement, its evaluation and its figures
    SW=tools/sdp_policies/sweep_20260902_eta088
    A=tools/sdp_policies/sdp_policy_v4.json
    D=docs/modeling/sdp_alpha_sweep_eta088_20260902
    C:/Users/ricky/miniforge3/python.exe tools/sdp_alpha_sweep.py solve \
        --eta-chg 0.88 --sweep-dir $SW --anchor-artifact $A --force
    C:/Users/ricky/miniforge3/python.exe tools/sdp_alpha_sweep.py refine \
        --eta-chg 0.88 --sweep-dir $SW --anchor-artifact $A
    C:/Users/ricky/miniforge3/python.exe tools/sdp_alpha_sweep.py evaluate \
        --include all --sweep-dir $SW --anchor-artifact $A --walk-eta-chg 0.88 \
        --scenario ems-sdp --scenario ems-ftp75-sdp --out $D
    C:/Users/ricky/miniforge3/python.exe tools/sdp_alpha_sweep.py plots \
        --include all --sweep-dir $SW --anchor-artifact $A --walk-eta-chg 0.88 \
        --scenario ems-sdp --scenario ems-ftp75-sdp --out $D/plots

`tools/sdp_alpha_sweep.py` gained four arguments for this round, all additive
and all defaulting to the previous behaviour: `--anchor-artifact` (the shipped
artifact a sweep anchors on, from which the anchor alpha is read), `--sweep-dir`
on `evaluate` and `plots` as well as on `solve` and `refine`, and
`--walk-eta-chg` / `--walk-eta-chg-none` on the two walking subcommands. Two
defects that blocked an eta-era sweep were fixed at the same time: the bisection
probe did not pass the charger era to the solver, and the refinement brackets
were literals from the previous era.
