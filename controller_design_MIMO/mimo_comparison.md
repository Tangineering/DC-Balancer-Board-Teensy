# MIMO vs. Decentralized — Comparison Results (Phase 5)

> ## ⚠ STALE — built on a retired plant (2026-08-16)
>
> Every number in this document was produced against the **pre-calibration** drive plant.
> The drive channel was measured on 2026-08-16 (`calibration/motor_id_20260815.md`), moving
> `G22(0)` 3.7085 → 1.4112 (m/s)/A, the drive pole −0.1219 → −0.0914 rad/s and `G12(0)`
> −2.757e-2 → −1.326e-2, with the clamp 20 A → 12 A. Drive-channel and coupling figures
> throughout are therefore stale — including the "slowest closed-loop mode 0.1219 rad/s"
> row in the headline table, which *is* the old drive pole and moves with it.
>
> `compare_controllers.py` cannot regenerate this document as it stands: it hard-crashes at
> stage 6 on a 20 A clamp assertion, and the MIMO controller it compares against no longer
> passes its own synthesis gates on the calibrated plant. Restoring the comparison is a new
> synthesis round, not a re-run. Scope and per-stage detail: `README.md` staleness banner.
>
> The document is kept as the published record of the ±20 A round.

**Status:** complete. All numbers in this document are emitted by
`compare_controllers.py` into `comparison_metrics.txt`; the metric key is quoted in every
table. Figures are produced by `plot_mimo_results.py` from the CSVs in `figures/`.

**Reproduce:**

```
ctrl-venv/Scripts/python.exe compare_controllers.py     # ~50 s, writes comparison_metrics.txt + figures/*.csv
ctrl-venv/Scripts/python.exe plot_mimo_results.py       # ~5 s,  writes figures/fig_*.svg
```

This document mirrors the rigour convention of `controller_design/full_order_validation.md`:
setup first, then the metric tables with their provenance keys, then a findings section that
answers the questions posed in `papers/Droop_Control/sections/06_mimo_outlook.tex`, then the
honest caveats, then a claim-slot map. **`06_mimo_outlook.tex` itself is NOT edited by this
round** — this document is the evidence base a later writing round would draw on.

> **±20 A recalibration round — 2026-08-04.** `MOTOR_I_CMD_MAX` / `I_CLAMP` moved
> **5 A → 20 A** and both controllers were re-synthesized. **Every number in this document
> is regenerated at ±20 A.** The superseded ±5 A figures are not deleted — §14 is a dated
> summary of what changed and why, and individual tables carry the old value where the
> comparison is instructive. Read §14 first if you have the ±5 A version in mind.

---

## 1. What is compared

| | **`dec`** (decentralized baseline) | **`dec500`** (rate-confound variant) | **`mimo`** (centralized) |
|---|---|---|---|
| Structure | `blkdiag(K_share, K_drive)` | same | full 2×2 |
| Share half | shipped Youla-H share controller, **1 kHz** | same controller re-discretized (Tustin) at **500 Hz** | — |
| Drive half | Phase-3 SISO Youla-H drive controller, **500 Hz** | same | — |
| Whole | — | — | Phase-4 2×2 H∞ / Youla-H, **500 Hz** |
| Continuous states | 9 (4 share + 5 drive) | 9 | **9** (2 exact integrators + **7** modal) |
| Anti-windup | share: back-calculation on the integrator (the shipped scheme); drive: **Hanus self-conditioning** (required — see §7) | same | `Du⁻¹·δ` back-calculation on the integrator subspace + authority clamp |
| Metric keys | `ctrl.dec.*` | — | `ctrl.mimo.*` |

The essential fairness condition: **both controllers are closed against the same coupled
2×2 plant**, using the same closed-loop assembly routine (`loop_matrices`, copied verbatim
from `synthesize_mimo_controller.py`), the same corner sets, and the same simulations. The
decentralized controller is never evaluated on a diagonal plant — that would flatter it by
construction.

### 1.1 Corner sets

* **Tier 1** (stability): the full `plant_mimo.tier1_corners()` cross product, 10 OPs × 24
  share corners × 24 drive corners = 5760, of which **4992 are feasible**
  (`tier1.n_feasible`) and 768 are skipped as unidirectional-switch-clamped operating points
  (`tier1.n_infeasible_skipped`).
* **Tier 2** (performance): the rep set is **copied verbatim** from
  `synthesize_mimo_controller.py:549–596` — 6 share reps × 4 drive reps × the OP grid, minus
  infeasible combinations = **208 corners** (`tier2.n_corners`), of which **168 are
  in-envelope** (`tier2.n_corners_in_envelope`) and 40 fall in the two documented waiver
  families (24 FC-cruise, 16 K-out-of-envelope). The waiver policy and its physical
  justification are copied along with the rep set, so the two controllers are judged on
  identical terms.

### 1.2 Rates and simulation

Time-domain results use a **multirate discrete simulator**, base step **0.1 ms**, plant
ZOH-discretized at the base rate per corner, controller outputs held between ticks. `dec`
runs its two halves at their native 1 kHz / 500 Hz; `mimo` runs single-rate at 500 Hz;
`dec500` exists purely to isolate the rate difference as a confound.

Frequency-domain results use **continuous** physical-coordinate controllers, recovered from
the emitted headers by exact inverse-Tustin plus the analytic `KI/s` integrator, so the two
controllers are compared as 2×2 systems `e = [Δα_err; Δv_err] → u = [Δr; Δi_cmd]`.

**All time-domain signals are small-signal deviations about the operating point** (nominal
OP: `I_tot0 = 2 A`, `r0 = 0.5`, `ΔV0 = +0.2 V`, `v0 = 2 m/s`). Every step amplitude is stated
in the tables, and the actuator-limited cases are flagged.

---

## 2. Metric 1 — coupling quantification (plant only)

This is the evidence for "is the decentralized design justified or merely convenient".

| Quantity | nominal (2 A, r=0.5) | light load (0.5 A) | FC cruise (r=0.85) | key |
|---|---|---|---|---|
| peak \|G_s,12\|/\|G_s,11\| | 1.5710 | **25.136** | 1.0451 | `coupling.*.max_G12_over_G11` |
| same, at DC | 1.5710 | 25.136 | 1.0451 | `coupling.*.G12_over_G11_at_dc` |
| cond(G_s) at DC | 21.238 | 51.064 | 27.588 | `coupling.*.cond_Gs_at_dc` |
| cond(G_s), in-band (DC…200 rad/s) | 101.9 | 6429.5 | 67.5 | `coupling.*.max_cond_Gs_inband` |
| ∂α/∂I_tot [share/A] | −0.04167 | **−0.66667** | −0.02125 | `coupling.*.dalpha_dItot` |

Over the whole feasible OP × ΔV0 grid (26 of 30 points feasible,
`coupling.dalpha_dItot.n_feasible`):

| Quantity | Value | Where | Key |
|---|---|---|---|
| worst \|∂α/∂I_tot\| | **1.120 share/A** | 0.5 A, r0=0.7, ΔV0=−0.4 V | `coupling.dalpha_dItot.max_abs_feasible` |
| worst DC cond(G_s) | 51.15 | — | `coupling.grid.max_cond_Gs_at_dc` |
| worst in-band cond(G_s) | 8834.6 | 0.5 A, r0=0.3, ΔV0=+0.4 V | `coupling.grid.max_cond_Gs_inband` |
| worst \|G_s,12\|/\|G_s,11\| | 25.14 | 0.5 A, r0=0.5, ΔV0=+0.2 V | `coupling.grid.max_G12_over_G11` |
| max \|RGA − I\| | **2.23e−16** | all cases, all frequencies | `coupling.max_RGA_departure_from_I` |

**Structure.** The design plant is *structurally upper-triangular* (`G21 ≡ 0`: the droop
ratio does not move the wheel speed), so the RGA is the identity to machine precision at
every frequency and every corner. RGA-based interaction measures therefore say *nothing*
here — a one-directional coupling is invisible to the RGA. This is a real methodological
point for the paper: **the RGA is the wrong instrument for this plant**, and the correct
instruments are the directional ratio |G12|/|G11| and the closed-loop cross-transfer
‖T_{α←v_ref}‖ (§3).

**These ratios are SCALED quantities and moved 4× with the clamp.** `G_s,12` carries
`Du(2,2)` (5 → 20 A) while `G_s,11` carries the unchanged `Du(1,1)`. The **physical**
coupling is identical to the ±5 A round; what changed is the units the synthesis and these
tables express it in. ±5 A values: 0.393 / 6.284 / 0.261 nominal / light-load / FC-cruise.

**Magnitude.** The coupling is not negligible and is strongly operating-point-dependent: at
the nominal 2 A load the drive-to-share path is now **1.6×** the direct path — it was 39 % of
it at ±5 A — and at 0.5 A it is **25×** the direct path, because ∂α/∂I_tot scales as
1/I_tot². That the nominal ratio crossed 1 is the substantive change: at the design point a
full-authority motor transient now has **more** authority over the share than a full-authority
droop command does. It is also **sign-uncertain**:
it is exactly zero at ΔV0 = 0 and flips sign with ΔV0, whose sign is not known
(±0.4 V budget). That single fact bounds everything a MIMO feedforward can buy — see §9.

*Note on the condition number:* the "in-band" window (DC…200 rad/s) is used deliberately.
cond(G_s(jω)) → ∞ as ω → ∞ for any strictly-proper plant whose two channels roll off at
different orders, so the full-sweep maximum (`coupling.*.max_cond_Gs_full_sweep`,
3.7e3–1.9e4) measures roll-off asymmetry, not coupling, and would be misleading in a table.

**Figures:** `fig_coupling_sigma.svg` (σ̄/σ̲ of G_s + the |G12|/|G11| overlay),
`fig_coupling_cond.svg`, `fig_coupling_gain_grid.svg`.

---

## 3. Metric 2 — worst-corner sensitivity, identical Tier-2 set

### 3.1 Nominal plant

| Quantity | `dec` | `mimo` | key |
|---|---|---|---|
| ‖S_o‖∞ (σ̄ peak) | 1.3974 | **1.2287** | `nominal.*.sigma_So_peak` |
| \|S11\| peak (share) | 1.2523 | **1.2114** | `nominal.*.S11_peak` |
| \|S22\| peak (drive) | 1.3851 | **1.2285** | `nominal.*.S22_peak` |
| ‖T_{α←v_ref}‖∞ [share/(m/s)] | 0.25676 | **0.00131** | `nominal.*.T_alpha_from_vref_peak` |
| slowest closed-loop mode [rad/s] | 0.00400 | **0.1219** | `nominal.*.max_real_cl_pole` |
| σ̄(S_u) peak (input node) | 1.3852 | **1.2385** | `compute_Su.py` |

The `dec` column is **unchanged from the ±5 A round** — every quantity here is a linear
frequency-domain one, and the decentralized controller was not re-synthesized (its clamp
metadata moved, its dynamics did not). Only the MIMO column moves.

At the nominal design point the MIMO controller reduces the closed-loop cross-coupling
transfer by a factor of **195** (±5 A: 293). This is the headline "MIMO buys coupling rejection" number —
and §9 explains exactly why it does not survive the ΔV0 sign flip.

### 3.2 Tier-2 corner family (168 in-envelope corners)

| Quantity | `dec` | `mimo` | key |
|---|---|---|---|
| worst σ̄(S_o), in-envelope | 2.5535 | **1.8754** | `tier2.*.worst_sigma_So_in_envelope` |
| worst \|S11\| peak | 1.5769 | **1.3721** | `tier2.*.worst_S11_peak_in_envelope` |
| worst \|S22\| peak | 2.4062 | **1.6743** | `tier2.*.worst_S22_peak_in_envelope` |
| worst ‖T_{α←v_ref}‖∞ | 0.8480 | **0.8020** | `tier2.*.worst_T_alpha_from_vref_in_envelope` |
| continuous-unstable corners | 0 | 0 | `tier2.*.n_unstable` |
| worst σ̄(S_o), FC-cruise (waived) | 2.4960 | **1.7471** | `tier2.*.waived_FC_cruise_worst_sigma_So` |
| worst σ̄(S_o), K-out-of-envelope (waived) | **5.7702** | 4.9334 | `tier2.*.waived_K_out_of_envelope_worst_sigma_So` |
| σ̄(S_u), worst Tier-2 corner (input node) | 1.8640 | **1.4749** | `compute_Su.py` |

Head-to-head: MIMO has the lower σ̄(S_o) at **167 of 168** in-envelope corners
(`tier2.mimo_better_sigma_So_count`; ±5 A: 156 of 168). The Phase-4 numbers reproduce exactly
(worst in-envelope 1.8754; waived K-out-of-envelope 4.9334), confirming the harness assembles
the MIMO loop the same way its synthesis script did.

**Two ±20 A reversals worth naming.** (a) The MIMO controller now wins the **worst-corner
cross-coupling transfer** too (0.8020 vs 0.8480) — at ±5 A the decentralized pair won that
row (0.8480 vs 1.1467). (b) The MIMO controller is now **better than** the decentralized pair
on the waived K-out-of-envelope family (4.93 vs 5.77) where at ±5 A it was nearly 2× worse
(10.82 vs 5.77). Both are consequences of the it.5 weight re-tune
(`mimo_synthesis.md` §3.2), which bought corner robustness at the price of γ and of a little
nominal performance.

### 3.3 The cross-coupling transfer, split by ΔV0 sign

Ratio statistics are taken only over the **96 coupled in-envelope corners** (ΔV0 ≠ 0;
`tier2.n_coupled_corners_in_envelope`) — at ΔV0 = 0 both controllers' cross-transfers are
zero to machine precision and the ratio is 0/0 noise.

| Quantity | Value | key |
|---|---|---|
| corners where MIMO \|T_{α←v_ref}\| is smaller | **28 of 96** | `tier2.mimo_better_T_alpha_vref_count` |
| median ratio MIMO/dec, all coupled corners | 1.470 | `tier2.T_alpha_vref_mimo_over_dec_median` |
| median ratio, ΔV0 **sign matches** synthesis (+) | **0.941** | `…_median_dV0_pos` |
| median ratio, ΔV0 **sign opposes** synthesis (−) | **2.162** | `…_median_dV0_neg` |
| best / worst ratio | 0.1938 / 4.378 | `…_best` / `…_worst` |

*(±5 A round, for comparison: 24 of 96; medians 2.218 all / 1.370 matching / 3.198 opposing;
best/worst 0.3154 / 7.267.)*

This is the sign-uncertainty finding in one table, and the ±20 A round **sharpens rather than
overturns it**. The headline improvement (195× at the nominal ΔV0 = +0.2 V point) still does
not survive the sweep: the median penalty over all coupled corners is **1.47×**. But the split
is now qualitatively cleaner — at the **matching** ΔV0 sign the MIMO controller is a slight
net *win* (median ratio **0.94 < 1**, where at ±5 A it was a 1.37× penalty), while at the
**opposing** sign it remains a 2.16× penalty. The finding is therefore no longer "MIMO loses
on the median even at its own sign"; it is the crisper **"MIMO helps if and only if ΔV0's sign
is the one it was built for, and that sign is an uncalibrated quantity."** The ratio between
the two medians (2.30×) is essentially unchanged from the ±5 A round (2.33×), which is the
robust part of the result.

**Figures:** `fig_sigma_S.svg`, `fig_S_channels.svg`, `fig_corner_scatter.svg`.

---

## 4. Metric 3 — Tier-1 corner stability (4992 feasible corners)

| Controller | continuous unstable | worst Re(λ) [rad/s] | discrete unstable | worst \|z\| |
|---|---|---|---|---|
| `dec` (multirate 1 kHz / 500 Hz) | **0 / 4992** | −0.00400 | **0 / 4992** | 0.999992 |
| `dec500` (both halves 500 Hz) | — | — | **0 / 4992** | 0.999992 |
| `mimo` (single-rate 500 Hz) | **0 / 4992** | −0.11999 | **0 / 4992** | 0.999760 |

Keys: `tier1.{dec,dec500,mimo}.{continuous,discrete}_*`.

**No decentralized instability was found anywhere in the Tier-1 family** — neither in
continuous time nor in the discrete multirate loop. This is a positive result for the
decentralized architecture and is reported as such.

The discrete check for `dec` is not an approximation: it is the exact **2-step monodromy**
of the 1 ms-lifted periodic loop (plant at 1 ms, share controller updating on both
sub-steps, drive controller updating on the first and its output held through the second).
`mimo` and `dec500` use the ordinary single-rate 2 ms closed loop.

The one asymmetry worth naming: the decentralized loop's slowest closed-loop mode is
**0.0040 rad/s** (≈ 250 s time constant) against the MIMO's **0.1200 rad/s** — a factor of
30. Both are stable, but the decentralized pair leaves a very slow, nearly-cancelled mode
that the centralized design does not.

---

## 5. Metric 4 — drive-transient share excursion

Speed-reference step applied at t = 0.05 s. **Amplitudes are deviations about the v0 = 2 m/s
operating point.** The step **amplitudes are deliberately unchanged from the ±5 A round** so
the two rounds are directly comparable — but their *character* changed, so rail fractions are
quoted in every table:

| | ±5 A rail fraction | ±20 A rail fraction |
|---|---|---|
| small step (0.05 m/s) | 0 % (linear) | 0 % (linear, and now far from the clamp) |
| large step (2 m/s) | 1.31–1.49 % | **0.18–0.34 %** |

The large step still saturates — a 2 m/s demand exceeds any plausible clamp — but it spends
**~4× less of the horizon on the rail**, and the post-saturation recovery, not the slew, now
dominates the metric. Saturation remains a **plant/actuator property, not a controller
property**. The small step is fully linear (0 % rail) and is the clean comparison.

### 5.1 Small signal, Δv_ref = +0.05 m/s (linear, unsaturated) — 12 s horizon

| | `dec` | `dec500` | `mimo` | key |
|---|---|---|---|---|
| max\|Δα\|, ΔV0 = **+0.4** | 0.01744 | 0.01868 | **0.00667** | `transient.small.dV0p.*.max_abs_dalpha` |
| max\|Δα\|, ΔV0 = **−0.4** | 0.01744 | 0.01868 | 0.01935 | `transient.small.dV0m.*.max_abs_dalpha` |
| Δα settle (<0.002) [s], +0.4 | 0.189 | 0.189 | **0.175** | `…dalpha_settle_2mshare_s` |
| v settle (2 %) [s] | 0.358 | 0.358 | **0.199** | `…v_settle_2pct_s` |
| peak \|i_cmd\| [A] | 2.071 | 2.071 | **1.179** | `…peak_abs_i_cmd_A` |
| rail fraction | 0 | 0 | 0 | `…i_rail_fraction` |
| MIMO/dec share-excursion ratio | — | — | **0.383** (+0.4) / **1.109** (−0.4) | `transient.small.*.mimo_over_dec_dalpha` |

**This is the cleanest single result in the study, and it improved.** At the ΔV0 sign the
MIMO controller was synthesized for it cuts the drive-induced share excursion by **62 %**
(±5 A: 39 %), settles the speed **44 % faster**, and does it with a **43 % smaller current
peak**. At the mirrored sign it is **11 % worse** than the decentralized pair — where at ±5 A
it was **78 %** worse. The sign penalty has shrunk from "large" to "marginal" while the
matching-sign benefit grew.

The decentralized numbers are *identical* at both signs — as they must be, since a diagonal
controller on a linear plant sees only the magnitude of the coupling, not its sign — and are
**bit-identical to the ±5 A round**, since this step never approaches either clamp.

### 5.2 Large signal, Δv_ref = +2 m/s (actuator-limited) — 60 s horizon

| | `dec` | `dec500` | `mimo` | key |
|---|---|---|---|---|
| max\|Δα\|, ΔV0 = +0.4 | 0.3306 | 0.3334 | **0.1729** | `transient.large.dV0p.*.max_abs_dalpha` |
| max\|Δα\|, ΔV0 = −0.4 | **0.3306** | 0.3334 | 0.6289 | `transient.large.dV0m.*.max_abs_dalpha` |
| Δα settle (<0.002) [s] | 0.599 | 0.601 | **0.337** (+) / **0.461** (−) | `…dalpha_settle_2mshare_s` |
| v settle (2 %) [s] | **0.501** | 0.501 | 22.45 | `…v_settle_2pct_s` |
| peak \|i_cmd\| [A] | 20.00 | 20.00 | 20.00 | `…peak_abs_i_cmd_A` |
| rail fraction | 0.0034 | 0.0034 | **0.0018** | `…i_rail_fraction` |
| MIMO/dec share-excursion ratio | — | — | **0.523** (+0.4) / **1.902** (−0.4) | `…mimo_over_dec_dalpha` |
| r range, ΔV0 = +0.4 | [0.431, **0.850**] | [0.431, 0.850] | [0.500, **0.850**] | `…r_min` / `r_max` |

**This metric flipped, and the flip is the most consequential ±20 A change.** At ±5 A the
decentralized pair won this row outright (0.0885 vs 0.2486–0.4521, i.e. MIMO 2.8–5.1× worse
at *both* ΔV0 signs). At ±20 A the large step behaves like the small one: **split by ΔV0
sign** — MIMO is 48 % *better* at the matching sign and 90 % worse at the opposing sign.

The mechanism of the change is the clamp, not the controllers. With 4× the current available,
the decentralized drive half accelerates far harder (v settles in 0.50 s instead of 1.14 s),
and that harder acceleration dumps a **4× larger bus-current transient** into the share
channel: `dec`'s share excursion grew 0.0885 → 0.3306 and it now **hits the r = 0.85 droop
clamp**, which it never did at ±5 A. The MIMO controller's coupling feedforward is precisely
the mechanism that anticipates that transient, so raising the clamp raised the value of the
feedforward — at the sign it was built for.

**What did not change:** the MIMO speed settle is still slow (22.45 s vs 0.50 s, a 45× gap,
worse in ratio than the ±5 A round's 11.6×). The mechanism is documented in
`mimo_synthesis.md` §8.4 — post-saturation recovery is governed by the drive integrator
residue against a 0.122 rad/s vehicle pole and is slow **by design**; the authority clamp
bounds but does not eliminate the transfer. The 60 s horizon was chosen so this is measured,
not reported as a horizon artefact. Whether a 22 s speed-settle tail is acceptable is an
application question this study does not settle — it is a real cost of the centralized design
and it got worse in ratio terms.

**Figures:** `fig_transient_small_dV0p.svg`, `fig_transient_small_dV0m.svg`,
`fig_transient_large_dV0p.svg`, `fig_transient_large_dV0m.svg`.

---

## 6. Metric 5 — regen event on the full-order truth model

Closed against `full_model_mimo.full_plant_mimo(..., with_bus_output=True)` — the **15-state
truth model** (`regen.truth_model_states`), not the 8-state design plant. Event: Δv_ref
stepped to **−2 m/s** (2 m/s → standstill), i_cmd rails at −20 A. The truth model carries no
τ_f by convention, so the 0.8 ms measured-share prefilter is applied digitally at the base
rate — the same filter that is part of the design plant. 60 s horizon.

| Quantity | `dec` | `dec500` | `mimo` | key |
|---|---|---|---|---|
| **max \|Δv_bus\| [V]** | 1.49112 | 1.49112 | **1.47429** | `regen.*.max_abs_dv_bus_V` |
| Δv_bus final [V] | 0.10478 | 0.10478 | 0.10477 | `regen.*.dv_bus_final_V` |
| v_bus recovery [s] | 0.582 | 0.582 | **0.431** | `regen.*.v_bus_recovery_s` |
| max \|Δα\| | 0.17467 | 0.17263 | **0.14478** | `regen.*.max_abs_dalpha` |
| peak i_cmd [A] | −20.00 | −20.00 | −20.00 | `regen.*.peak_neg_i_cmd_A` |
| rail fraction | 0.0034 | 0.0034 | **0.0018** | `regen.*.i_rail_fraction` |
| v settle (2 %) [s] | **0.501** | 0.501 | 22.45 | `regen.*.v_settle_2pct_s` |
| final \|Δv\| error [m/s] | 1.00e−10 | 1.00e−10 | 4.11e−04 | `regen.*.final_abs_dv_error` |

### 6.1 The regen verdict, RE-EXAMINED at ±20 A

The ±5 A round called this metric a **tie** and explained it by "both controllers are on the
same rail for the whole event, so neither has bus authority." **The verdict survives; that
explanation does not, and it is worth correcting because the outlook section proposes this
metric as a discriminator.**

What actually happened at ±20 A:

* **The bus excursion grew 3.53×** (0.4228 → 1.4911 V), close to the 4× the clamp change
  predicts — confirming the excursion is set by the **peak** regen current, which both
  controllers hit.
* **But the event is no longer rail-dominated.** The rail fraction fell from 1.31–1.50 % of
  the 60 s horizon to **0.18–0.34 %** (≈ 0.2 s for `dec`, ≈ 0.11 s for `mimo`), and the
  vehicle stops in 0.50 s instead of 1.14 s. The two controllers are on the rail for
  materially **different** durations — `mimo` for roughly half as long.
* **The ratio is nevertheless still 0.989** (`regen.mimo_over_dec_dv_bus`; ±5 A: 0.983).

So the metric **does not discriminate**, but for a sharper reason than before: the bus
excursion is set by the *peak* motor current, both controllers reach the same peak because
both briefly rail, and what they do *after* the rail is over does not move the maximum. A
controller could only differentiate here by choosing **not** to demand full regen current,
which is a reference-shaping decision, not a feedback-design one. **Recommendation for
`06_mimo_outlook.tex`: do not propose bus excursion during a hard regen stop as a
MIMO-vs-decentralized discriminator.** It measures the clamp.

One genuine change: **`mimo` no longer pays for the tie.** At ±5 A it bought a 1.7 % smaller
bus excursion at the cost of a 6.5× *larger* share excursion. At ±20 A it is better on
**both** — 1.1 % smaller bus excursion and a **17 % smaller** share excursion (0.1448 vs
0.1747). The lopsided trade is gone; the tie on the headline number remains.

The residual Δv_bus of 0.105 V is the new steady-state load operating point (the vehicle
stopped), not a tracking error — hence the recovery metric is measured about the final value.

**Figure:** `fig_regen_bus.svg`.

---

## 7. Metric 6 — FC-charge cruise (r_ref parked on the clamp)

Operating point (2 A, r0 = **0.85**), static share α0 = 0.8925 (`fccruise.alpha0`), the EMS
regime in which the droop ratio sits on its upper clamp and the share loop has **no upward
authority left by construction**. A Δv_ref = +0.5 m/s drive step is then applied. 60 s horizon.

| Quantity | `dec` | `dec500` | `mimo` | key |
|---|---|---|---|---|
| max \|Δα\| | 0.10310 | 0.10310 | **0.06129** | `fccruise.*.max_abs_dalpha` |
| r pinned at 0.85, fraction of horizon | 0.9965 | 0.9965 | **0.0042** | `fccruise.*.r_rail_fraction_upper` |
| r_min (downward authority used) | 0.83693 | 0.83690 | 0.84776 | `fccruise.*.r_min` |
| final \|Δα\| (windup-hang indicator) | 0.00190 | 0.00190 | 0.00202 | `fccruise.*.final_abs_dalpha` |
| final \|Δv\| error [m/s] | 2.47e−11 | 2.47e−11 | 1.52e−05 | `fccruise.*.final_abs_dv_error` |
| v settle (2 %) [s] | 0.360 | 0.360 | **0.199** | `fccruise.*.v_settle_2pct_s` |
| r stayed inside [0.15, 0.85] | yes | yes | yes | `fccruise.*.r_within_clamp` |
| tail r peak-to-peak, last 2 s | 0.0 | 0.0 | 2.21e−11 | `fccruise.*.tail_r_ptp_last_2s` |

**No windup interaction for either controller.** `dec` still saturates the droop ratio on its
upper clamp for essentially the whole horizon (99.65 %); the MIMO controller now spends only
**0.4 %** of the horizon pinned there (±5 A: 79.8 %), because the 0.5 m/s drive step no longer
saturates the motor channel (`mimo_synthesis.md` §8.4) and so demands far less droop
correction. Both use only the small downward authority available, both converge to a ~2e−3
residual share error (the authority loss itself, not a hang), and neither exhibits a limit
cycle (tail p-p ≤ 1e−5). MIMO's share excursion in this regime is now **41 % smaller** than
`dec`'s (0.0613 vs 0.1031); at ±5 A the two were within 3 %. The anti-windup schemes — the shipped
integrator back-calculation on the share half, Hanus self-conditioning on the drive half,
and the `Du⁻¹`-back-calculation-plus-authority-clamp on the MIMO — all behave gracefully in
the degenerate-authority regime. This closes out the risk flagged in the plan §10
("FC-cruise degeneracy").

**Figure:** `fig_fccruise.svg`.

---

## 8. Metric 7 — 30 s drive-cycle profile

Profile (absolute speed, converted to deviations about v0 = 2 m/s): standstill 0–2 s, ramp
0 → 2 m/s over 5 s, cruise to 17 s, coast 2 → 0.5 m/s over 3 s, hold to 26 s, → 0 by 28 s.
Share setpoint stepped Δα_ref = +0.2 over 11–15 s. Load disturbance: −1.0 A input step over
22–25 s.

| Quantity | `dec` | `dec500` | `mimo` | key |
|---|---|---|---|---|
| RMS speed error [m/s] | **0.10589** | 0.10589 | 0.23958 | `cycle.*.rms_speed_error_m_s` |
| RMS share error | **0.004750** | 0.004787 | 0.007299 | `cycle.*.rms_share_error` |
| RMS speed error, cruise window 8–11 s [m/s] | **2.94e−07** | 2.94e−07 | 0.19492 | `cycle.*.rms_speed_error_cruise_m_s` |
| RMS share error, cruise window | **6.38e−10** | 6.38e−10 | 2.55e−04 | `cycle.*.rms_share_error_cruise` |
| max \|speed error\| at load step [m/s] | **0.01908** | 0.01908 | 0.04201 | `cycle.*.max_abs_speed_error_load_step_m_s` |
| max \|share error\| at load step | **0.00911** | 0.00944 | 0.00974 | `cycle.*.max_abs_share_error_load_step` |
| peak \|i_cmd\| [A] | 20.00 | 20.00 | 20.00 | `cycle.*.peak_abs_i_cmd_A` |
| rail fraction | 0.0067 | 0.0067 | **0.0037** | `cycle.*.i_rail_fraction` |
| r range | [0.2886, 0.7003] | [0.2886, 0.7003] | **[0.1500, 0.7008]** | `cycle.*.r_min` / `r_max` |

**The decentralized pair's cycle tracking roughly halved** (RMS speed error 0.2026 → 0.1059
m/s) — with 4× the current it follows the ramps far better, and the rail fraction fell
0.0299 → 0.0067. The MIMO controller went the other way (0.2113 → 0.2396 m/s), so the gap on
this metric **widened from 4 % to 2.3× in the decentralized pair's favour**.

The **cruise window remains the discriminating segment** and the gap there widened too: `dec`
is at numerical zero (2.9e−7 m/s RMS) while `mimo` sits at 0.195 m/s — it is still recovering
from the ramp saturation, and because the ramp is now taken harder there is *more* to recover
from. Same mechanism as §5.2's 22 s speed settle. On the isolated load disturbance `dec` is
now clearly better on speed (0.0191 vs 0.0420 m/s) where at ±5 A the two were within 2 %;
they remain equivalent on share error (0.0091 vs 0.0097).

Unchanged result of note: the MIMO controller still **drives the droop ratio to its lower
clamp (r = 0.15)** during the cycle, whereas the decentralized pair never goes below 0.29
(0.44 at ±5 A). This is the cross-channel term spending droop authority in response to a
saturated drive channel — a real cost of centralization on this plant, not a numerical
artefact.

**Figure:** `fig_drive_cycle.svg`.

---

## 9. Findings — answering `06_mimo_outlook.tex`

### Q1. How large and of what structure is the coupling?

**One-directional and operating-point-dominated.** `G21 ≡ 0` structurally (the droop ratio
does not move the wheel speed), so the plant is exactly upper-triangular and **RGA ≡ I to
2.2e−16 at every frequency** — the instrument the outlook section names (RGA) is provably
uninformative here, which is itself a reportable methodological finding. The live coupling is
drive → share, through ∂α/∂I_tot = −ΔV0·r0(1−r0)/(k_d·I_tot0²), and it is:

* **large at light load** — |G12|/|G11| = **25.1** at 0.5 A vs **1.57** at 2 A (scaled
  coordinates at the ±20 A clamp; ±5 A: 6.28 / 0.39), because the gain scales as 1/I_tot²;
  worst feasible ∂α/∂I_tot is 1.120 share/A (a *physical* number, unchanged);
* **zero at ΔV0 = 0 and sign-uncertain** over the ±0.4 V budget;
* **benign for conditioning** — worst DC cond(G_s) over the whole feasible grid is 51.2
  (±5 A: 13.08); still far from ill-conditioned.

Note that the scaled ratio at the *nominal* operating point now exceeds 1 (1.57), where at
±5 A it was 0.39. Nothing physical changed — the input scaling did — but it is the honest
way to state the coupling's size relative to the actuator authority the controller has, and
by that measure the coupling channel is now the stronger of the two at the design point.

### Q2. Is the decentralized design justified, or merely convenient?

**Justified — and this round supplies the evidence rather than the assumption.**

* Stability: **0 instabilities in 4992 feasible Tier-1 corners**, continuous *and* in the
  exact multirate discrete loop. A decentralized pair designed channel-by-channel and then
  closed on the fully coupled plant never destabilizes anywhere in the uncertainty family.
* Performance: the decentralized pair pays a bounded price — worst in-envelope σ̄(S_o) of
  2.554 vs the MIMO's **1.875** (a **36 %** higher peak), and it is the worse controller at
  **167 of 168** corners (±5 A: 156 of 168). The frequency-domain case for the MIMO
  controller got **stronger** this round.
* It *still* wins on the operationally decisive large-signal metrics — speed settle after
  saturation (0.50 s vs 22.45 s, §5.2), drive-cycle RMS tracking (2.3× better, §8) — and it
  never touches the r = 0.15 droop clamp.
* **But two ±5 A arguments for decentralization no longer hold** and must not be repeated:
  it no longer wins the corner-worst cross-coupling transfer (0.848 vs **0.802**, MIMO), and
  it no longer wins the **large-signal share excursion**, which at ±20 A splits by ΔV0 sign
  exactly as the small-signal one does (§5.2).

The honest phrasing for the paper: decentralization is justified **for stability
unconditionally**, and justified **for large-signal/post-saturation behaviour and for
implementation simplicity**; on the frequency-domain and small-signal coupling metrics the
centralized controller is genuinely better, subject to the ΔV0 sign — see Q3.

### Q3. MIMO vs decentralized on the three headline metrics

| Headline metric (as named in the tex) | `dec` | `mimo` | verdict | ±5 A verdict |
|---|---|---|---|---|
| **worst-corner ‖S‖∞** (in-envelope σ̄(S_o)) | 2.5535 | **1.8754** | **MIMO wins**, −27 % | MIMO wins, −25 % |
| **drive-transient share excursion** (small-signal, ΔV0 = +0.4 / −0.4) | 0.01744 / 0.01744 | **0.00667** / 0.01935 | **split by ΔV0 sign** (−62 % / +11 %) | split by ΔV0 sign (−39 % / +78 %) |
| **regen-event bus excursion** | 1.49112 V | 1.47429 V | **tie** (ratio 0.989) | tie (ratio 0.983) |

The three metrics still give three different answers — that structure is the result and it
survived the recalibration — but two of the three moved in the MIMO controller's favour:

1. **Worst-corner sensitivity: MIMO wins, by slightly more.** A 27 % reduction in the worst
   in-envelope σ̄(S_o) (was 25 %), a 30 % lower worst |S22| peak, a 30× faster slowest
   closed-loop mode, and it is now the better controller at **167 of 168** corners rather
   than 156. The input-node check agrees: σ̄(S_u) 1.2385 vs 1.3852 nominal, 1.4749 vs 1.8640
   at the worst corner.
2. **Drive-transient share excursion: the ΔV0 sign still decides, but the asymmetry
   narrowed.** −62 % at the synthesis sign (was −39 %), **+11 %** at the mirrored sign (was
   +78 %); median cross-transfer ratio **0.94** at the matching sign (a net win — it was a
   1.37 penalty) vs **2.16** at the opposing sign. **The MIMO advantage on this metric is
   still not robust to a sign the hardware has not pinned down**, but the downside case is
   now marginal rather than severe. The nominal-point cross-transfer improvement is **195×**
   (was 293×) and remains a nominal-point number that must be quoted as such — see §13 for
   why it is also a continuous-domain number.
3. **Regen bus excursion: still no meaningful difference — but the ±5 A *reason* was wrong.**
   The old explanation ("both are on the rail for the whole event") no longer holds: the rail
   fraction fell 4× and the two controllers rail for materially different durations. The
   excursion is set by the *peak* current, which both reach. §6.1 re-derives this in full.
   **It is still not a discriminator, and the outlook section should not propose it as one.**
   The one improvement: MIMO no longer pays a 6.5× share-excursion penalty for the tie — it
   is now 17 % *better* on share excursion too.

Adding the operational metrics the tex does not name: the decentralized pair is still
**better on the post-saturation cases** — 45× faster speed settle after the 2 m/s step
(0.50 s vs 22.45 s), 2.3× better drive-cycle RMS tracking, and it never touches the
r = 0.15 droop clamp. But the ±5 A claim that it is better on **every** saturated
large-signal case is **no longer true**: on the 2 m/s step's share excursion it now loses at
the matching ΔV0 sign (0.331 vs 0.173) and on the FC-cruise share excursion it loses
outright (0.103 vs 0.061).

### Q4. Teensy 4.1 implementation cost

| Quantity | `dec` | `mimo` | ±5 A `mimo` | key |
|---|---|---|---|---|
| controller states | 4 (share) + 6 (drive) = **10** | **9** | 7 | `cost.dec.*.states`, `cost.mimo.states_total` |
| MAC per tick | 18 @ 1 kHz + 63 @ 500 Hz | 89 @ 500 Hz | 57 @ 500 Hz | `cost.*.mac_per_tick` |
| **MAC per second** | **49 500** | **44 500** | 28 500 | `cost.*.mac_per_second` |
| ratio MIMO / dec | — | **0.899** | 0.576 | `cost.mimo_over_dec_mac_per_second` |
| coefficient floats | — | 97 | 65 | `cost.mimo.coeff_floats` |

> **The cost argument weakened this round and the reason is a judgment call, not the plant.**
> The ±20 A MIMO controller needs a **7-state** stable remainder rather than 5 (9 total),
> because the Hankel singular values of the new design fall off more slowly and truncating at
> 5 no longer clears the tightened reduction tolerance. The order budget was deliberately
> raised 8 → 10 states rather than loosening that tolerance — the full rationale, including
> the "lucky truncation" precedent that motivated keeping it tight, is in
> `mimo_synthesis.md` §6. Consequence: MIMO is now **0.90×** the decentralized MAC/s, not
> **0.58×**. It is still the cheaper option and still has one fewer state, but "the
> centralized controller is dramatically cheaper" is no longer a claim this study supports.

**The MIMO controller is still the *cheaper* implementation** — 0.90× the MAC/s and one
fewer state. This is counter-intuitive and deserves the explanation, which is the Phase-3
finding recorded in `drive_siso_coeffs.h`: **the decentralized baseline cannot be implemented
as a biquad cascade.** Its non-integral branch has a 367.7 A/(m/s) low-frequency gain, so
against the clamp the biquad states wind up independently of the integrator. Raising the
clamp to ±20 A raises the saturation-error threshold 4× with it (13.6 → **54.4 mm/s**), which
makes integrator-only anti-windup **clean for steps up to ~0.2 m/s** — but it still fails the
0→2 m/s gate, so the **Hanus self-conditioned 5-state state-space form is still required**.
Its `Ac = Ad − Bd·Cd/Dd` product costs an extra n² per tick, and it runs one of its two halves
at 1 kHz. *(What changed: at ±5 A the Hanus form was needed for essentially any manoeuvre; at
±20 A it is needed only for large transients. The requirement is unchanged; its severity is
not.)*

**Two MAC figures exist for the MIMO controller and both are correct.** This table quotes
**89 MAC/tick** from `cost.mimo.mac_per_tick` — state-space core only, the same accounting
applied to the decentralized baseline, which is what makes the ratio meaningful.
`mimo_synthesis_metrics.txt` quotes **97 MAC/tick** because it also counts the `De⁻¹`/`Du`
scaling and the anti-windup ops, i.e. what the Teensy actually executes.

Both are negligible on a 600 MHz Cortex-M7 (49.5 k vs 44.5 k MAC/s is <0.1 % of the core).
The genuine costs of the MIMO option are therefore **not** cycles:

* it moves the share loop from 1 kHz to 500 Hz (a design decision, not a saving);
* float32 coefficient sensitivity, mitigated by the modal form + De/Du scaling
  (float32 replay verified <5e−4 in Phase 4);
* the UART frame floor (~781 µs) is unchanged and remains the true bottleneck;
* the anti-windup scheme becomes matrix-valued (`Du⁻¹` back-calculation + authority clamp),
  which is more code to get right than the shipped scalar scheme.

---

## 10. Caveats

1. **ΔV0 sign uncertainty bounds any feedforward benefit.** The entire MIMO coupling
   advantage lives in ∂α/∂I_tot, which is zero at ΔV0 = 0 and flips sign with ΔV0. The
   controller was synthesized at ΔV0 = +0.2 V (half-budget, deliberately). Median
   cross-transfer ratio is **0.94** at the matching sign (a slight win) and **2.16** at the
   opposing sign (±5 A: 1.37 / 3.20). **Until ΔV0 is measured on the bench, the honest claim
   is "MIMO buys coupling rejection at the design sign and costs it at the mirror sign", not
   "MIMO buys coupling rejection".** The 2.3× ratio between the two medians is essentially
   identical across the two clamp settings, which is evidence that this caveat is a property
   of the plant's sign structure rather than of any particular tuning.
2. **K-out-of-envelope corners are waived — and at ±20 A the MIMO is *better* there.** The 16
   light-load × full-mismatch corners (0.5 A with |ΔV0| = 0.4 V, share plant gain K ≈ 2.1)
   give σ̄(S_o) = **4.93** for the MIMO vs 5.77 for the decentralized pair. **This reverses
   the ±5 A finding** (10.82 vs 5.77, MIMO nearly 2× worse), which was listed here as a cost
   of centralization. It is no longer one: the it.5 weight re-tune more than halved the
   MIMO's worst waived corner. The waiver (stability only) is inherited verbatim from Phase 4
   and is physically justified there.
3. **Large steps are actuator-limited, but much less so.** Δv = 2 m/s and the drive-cycle
   ramps still saturate the ±20 A clamp, but the rail fractions fell ~4× (2 m/s step:
   1.3–1.5 % → 0.18–0.34 % of the horizon; drive cycle: 3.0 % → 0.4–0.7 %). Those
   comparisons are therefore now dominated by **post-saturation recovery** rather than by the
   slew itself — which is exactly where the MIMO controller is weakest (§5.2). The
   Δv = +0.05 m/s case (0 % rail) remains the clean linear comparison and is reported
   alongside every large-signal case. **Step amplitudes were deliberately held at their ±5 A
   values** so the two rounds compare directly; rail fractions are now quoted in every table
   so the character change is visible rather than inferred.
4. **The rate confound is isolated and is NOT the explanation.** `dec500` — the decentralized
   pair with the share half re-discretized at 500 Hz — changes the share excursion by only
   0.8 % on the large step and 7.1 % on the small step
   (`transient.*.dec500_over_dec_dalpha` = 1.008 / 1.071), leaves the regen bus excursion
   essentially identical (ratio 1.000), leaves Tier-1 stability at 0/4992, and changes the
   drive-cycle RMS errors in the 4th significant figure. **Every conclusion above survives
   equalizing the sample rates**, at ±20 A as at ±5 A.
5. **Controllers are rebuilt from their float32 headers**, not from a live synthesis run
   (the synthesis scripts are not importable without re-running and rewriting artefacts).
   This validates the emitted artefacts — the drive controller's `Dd` rebuilds to 3.1e−10 of
   the header banner value (`check.drive.Dd_header_vs_rebuilt`) — at the cost of ~1e−7
   relative coefficient truncation in the frequency-domain metrics, far below the reported
   precision.
6. **The shipped-share re-derivation carries a documented 0.67 % kI offset**
   (112.679 here vs 111.930 in the shipped firmware header), a solver-accuracy propagation
   from the γ_opt anchor that `shipped_share.py`'s own gates accept and report. It is well
   inside the corner family and does not affect any comparison above.
7. **Design-plant vs truth-model.** All frequency-domain and corner metrics use the 8-state
   design plant; only the regen event (§6) is run against the 15-state truth model. Phase 4
   cross-validated the two at **0.0 %** at ±20 A (σ̄(S_o) 1.2286 truth vs 1.2287 design;
   ±5 A: 4.1 %).
8. **Nothing here is bench-calibrated.** Every `TODO(calibrate)` in
   `mimo_system_model.md` §9 is still open (ΔV0 above all, plus k_t, encoder chain, m_eff,
   τ_v, Td_v). The corner families are wide precisely because of this, but a calibrated
   plant could move the verdicts — particularly Q3's metric 2.
9. **The clamp is a design choice with large consequences, now demonstrated.** The ±5 A →
   ±20 A change moved every large-signal verdict in this document and forced a re-synthesis
   (`mimo_synthesis.md` it.5) — it is not a parameter that can be varied after the fact. §14
   catalogues what moved. Any future change to `MOTOR_I_CMD_MAX` requires the same full loop:
   re-synthesize both controllers, re-run this harness, re-read the verdicts. The ±20 A value
   itself is motivated in `mimo_system_model.md` §2.1 (≈ 4.86 A bus-side at cruise, ≈ 77 W,
   inside the ≈67–87 W converter budget) — but note that the bus-power limit is **not**
   modelled as an explicit constraint; the motor clamp is only *approximately* equivalent to
   it, and only at the cruise operating point.

---

## 11. Claim-slot map — `06_mimo_outlook.tex`

The tex file is **not edited** by this round. This table maps each of its placeholder claim
slots to the evidence produced here.

| `06_mimo_outlook.tex` claim slot | Filled by | Evidence |
|---|---|---|
| "Augment the share plant with the drive dynamics … to form a 2×2 MIMO plant" | `plant_mimo.design_plant()` (8 states), `mimo_system_model.md` | §1; `full_model_mimo.py` 15-state truth model |
| "Quantify the off-diagonal coupling (RGA / σ-plots)" | §2 tables | `fig_coupling_sigma.svg`, `fig_coupling_cond.svg`, `fig_coupling_gain_grid.svg`; `coupling.*` keys |
| "… establish whether the decentralized design is actually justified or merely convenient" | §9 Q2 | `tier1.dec.*` (0/4992 unstable), `tier2.*.worst_sigma_So_in_envelope` |
| "author to sharpen the physical coupling argument — cross-coupling visible in the full-order model as the bus-node interaction" | §2 + §6 | ∂α/∂I_tot derivation; truth-model regen with `v_bus` output |
| "Synthesize a MIMO H∞ controller on the same weight philosophy" | Phase 4 | `mimo_synthesis.md`, `mimo_controller_coeffs.h` |
| **compare on: worst-corner ‖S‖∞** | §3.2, §9 Q3 row 1 | `tier2.{dec,mimo}.worst_sigma_So_in_envelope` = 2.5535 / 1.8754; `fig_sigma_S.svg`, `fig_corner_scatter.svg` |
| **compare on: drive-transient share excursion** | §5, §9 Q3 row 2 | `transient.small.dV0{p,m}.*.max_abs_dalpha`; `fig_transient_small_dV0{p,m}.svg` |
| **compare on: regen-event bus excursion** | §6 + §6.1, §9 Q3 row 3 | `regen.*.max_abs_dv_bus_V` = 1.4911 / 1.4743; `fig_regen_bus.svg`. **Reported as a non-discriminator** — §6.1 |
| "Assess implementation cost on the Teensy 4.1 (state count vs the current three-biquad realization at 1 kHz)" | §9 Q4 | `cost.*` keys; 10 states / 49.5 kMAC/s vs **9 states / 44.5 kMAC/s** |
| "The EMS commands share ≈ 1.0 during FC-charge cruise — the analysis should include that operating point" | §7 | `fccruise.*` keys; `fig_fccruise.svg` |
| FIGURE PLACEHOLDER: 2×2 block diagram with cross-coupling paths highlighted | **NOT filled** | still to be drawn; the structure it must show is `plant_mimo.design_plant()` §1 (G21 ≡ 0, G12 through the shared τ_f path) |
| "Decide … future work vs promote to a results section" | evidence now exists to promote | §9 gives four answerable questions with numbers |

---

## 12. File inventory

| File | Role |
|---|---|
| `compare_controllers.py` | the harness; emits every number below |
| `comparison_metrics.txt` | **GENERATED** — 290 metric keys; the Phase-5 gate |
| `plot_mimo_results.py` | reads the CSVs, writes the SVGs |
| `figures/coupling_freq.csv`, `coupling_cond_grid.csv`, `coupling_dalpha_dItot.csv` | §2 data |
| `figures/sigma_nominal_both.csv`, `sigma_worst_corner_both.csv`, `tier2_corner_scatter.csv` | §3 data |
| `figures/transient_{small,large}_dV0{p,m}.csv` | §5 data |
| `figures/regen_truth.csv`, `fccruise.csv`, `drive_cycle.csv` | §6–§8 data |
| `figures/fig_*.svg` (13) | thesis figures |

## 13. MATLAB cross-validation addendum — ±5 A DESIGN (superseded numbers)

> **✅ RE-RUN AT ±20 A (04-Aug-2026): VERDICT PASS on all six criteria.** See §13a below
> for the current-design log (`MATLAB_mimo_results.txt`); the ±5 A log is
> `MATLAB_mimo_results_5A.txt`. This section is retained because it validated the same
> machinery at the earlier actuator span and first surfaced the two *methodological*
> corrections (subsample lower bound; continuous- vs discrete-domain cross-transfer), both
> of which the ±20 A run reconfirms. Kept rather than deleted, per the
> supersede-don't-delete convention; its numbers are ±5 A numbers.

`mimo_crosscheck.m` (Control + Robust Control Toolbox) independently rebuilt the
plant from the documented equations, re-ran `hinfsyn` + the MIMO Youla-H
correction, parsed `mimo_controller_coeffs.h`, and re-ran the corner battery and
transients. **VERDICT: PASS** on all six criteria (`MATLAB_mimo_results.txt`).
Anchors: plant DC gain to 2.2e-9; `hinfsyn` γ = 1.8276 (between the bisection
1.1917 and the shipped a-posteriori 1.8168, as documented); ‖M−I‖ = 1.758e-4
(Python 1.75e-4); a-posteriori ‖Tzw‖∞ of the shipped artefact 1.8175 vs 1.8168
(0.04 %); T(0) = I to 1e-9 on the parsed header; transients within 4 %.

Two corrections it surfaced, both reproduced exactly by the Python model
afterward (this section supersedes the affected numbers above):

1. **The Tier-2 "worst σ̄(S_o) = 1.9153 (< 2.0)" is a subsample lower bound.**
   MATLAB's full 24×24 sweep at the nominal OP found σ̄(S_o) = **2.0345** at
   (ΔV0 = −0.4, Td = 2 ms, τr = 300 µs, τf = 0.8 ms, K_v = 2, pole_factor = 2,
   τ_v = 0.5 ms, Td_v = 4 ms) — a corner not in the Phase-4 rep set. Python
   reproduces 2.0345 exactly. Stability is unaffected (576/576, and Tier-1
   remains 0/4992 unstable); the < 2.0 performance gate number is
   subsample-dependent and the true full-grid worst is ≥ 2.03. The decentralized
   comparison point (2.5535) is the same subsample, so the *relative* verdict
   (MIMO ≈ −20–25 % worst-corner σ̄(S_o)) stands.
2. **The nominal cross-coupling rejection "293×" is a continuous-domain
   figure.** On the as-implemented 2 ms ZOH discrete loop,
   ‖T_{α←v_ref}‖ = 9.19e-3 (MATLAB and Python agree to 4 digits), i.e. **~28×**
   better than decentralized (0.2568), not 293×. The time-domain excursion
   metrics (§5), which were always simulated at the implemented rates, are
   unchanged and agree with MATLAB within 4 %.

---

## 13a. MATLAB cross-validation of the ±20 A design (04-Aug-2026) — **PASS**

`mimo_crosscheck.m`, re-run against the shipped ±20 A design
(`Du = diag(0.35, 20.0)`, `MIMO_CTRL_NX = 7`). Log: `MATLAB_mimo_results.txt`.
**VERDICT: PASS on all six criteria** (plant DC gain, all corners stable, T(0) = I,
nominal σ̄(S_o) within 5 %, a-posteriori γ within 5 %, transients within 25 %).

| Anchor | MATLAB | Python |
|---|---|---|
| design-plant DC gain, max abs dev | 2.23e-9 | — |
| `hinfsyn` γ | 1.0851 | 0.8977 (bisection) / 1.6456 (a-posteriori) — MATLAB lands between, as the P_f degeneracy predicts |
| ‖M_YH − I‖₂ | 9.631e-5 | 1.75e-4 |
| cond(Gs(0)Y_H(0)) | 1.0000 | 1.0001 |
| T(0) | I exactly (synthesis and parsed header) | I |
| nominal σ̄(S_o) | 1.2623 | 1.2287 (ZOH vs continuous; 2.7 %, inside the 5 % criterion) |
| ‖T_{α←v_ref}‖, implemented 2 ms loop | 1.109e-2 | 1.109e-2 |
| a-posteriori ‖Tzw‖∞ | 1.6457 | 1.6456 (0.006 %) |
| corner battery | 576/576 stable | — |
| exhaustive-sweep worst σ̄(S_o) | **1.9443** at (ΔV0 = −0.4, Td = 2 ms, τr = 300 µs, τf = 0.8 ms, K_v = 2, pf = 2, τ_v = 5 ms, Td_v = 4 ms) | **1.9445** at the same corner (independently reproduced) |
| share excursion, ΔV0 = +0.4 / −0.4 | 0.00636 / 0.01900 | 0.00667 / 0.01935 |
| peak \|i_cmd\|, +0.4 / −0.4 | 1.179 / 1.176 A | 1.179 / 1.176 A |

The exhaustive-sweep worst (1.9443) again exceeds the Tier-2 representative-set figure
(1.8754) — the same rep-set-subsample effect §13 identified at ±5 A. Stability is
unaffected (576/576 here, Tier-1 0/4992). The cross-transfer figure the report quotes for
the implemented loop (1.109e-2) is matched exactly.

Figures: `figures/MATLAB_mimo_sigmaS.png`, `MATLAB_mimo_corner_scatter.png`,
`MATLAB_mimo_transient.png` (regenerated at ±20 A).

---

## 14. ±20 A recalibration (2026-08-04)

**What changed and why.** `MOTOR_I_CMD_MAX` / `I_CLAMP` moved **5 A → 20 A**. The motivation is
in `mimo_system_model.md` §2.1: the clamp is a **motor-side** limit, and 20 A motor-side is
≈ **4.86 A bus-side** at cruise (`A_i = 0.2429 A/A`), ≈ **77 W** at `V_bus0 = 15.9 V` — inside
the converter pair's ≈ 67–87 W budget. At ±5 A the motor clamp bound roughly 4× earlier than
the power electronics did, which made nearly every large-signal metric in this document a
measurement of the clamp. The two budgets now bind together by construction at cruise. (The
bus-power limit is still not modelled as a separate constraint — only approximately
equivalent, and only at that operating point.)

**All numbers in §§1–12 above are the ±20 A numbers.** This section summarizes the deltas so a
reader holding the ±5 A version knows what to un-learn. It **supersedes** the ±5 A figures; it
does not delete them.

### 14.1 What had to be re-done

| | |
|---|---|
| `Du` | `diag(0.35, 5.0)` → `diag(0.35, **20.0**)` |
| MIMO controller | **re-synthesized**; new weight iteration **it.5** was required (`mimo_synthesis.md` §3.2) |
| Decentralized drive controller | **unchanged** — it was synthesized on the *physical* plant, so only its clamp metadata moved |
| γ (MIMO, a-posteriori) | 1.8168 → **1.6456** |
| MIMO controller order | 7 states (2+5) → **9 states (2+7)**; order budget raised 8 → 10 |
| MATLAB cross-check | **re-run at ±20 A — PASS** (§13a); ±5 A log kept as §13 |

The re-synthesis was **not optional**. `Wu` penalizes the *scaled* input, so quadrupling
`Du(2,2)` quartered the effective control-effort penalty. Re-running the old weight set
produced a *better* γ (1.08) together with **61 unstable Tier-1 corners** — the synthesis
spent the entire 4× on aggression. The exact compensation (`Wu × 4`) is not representable in
the weight family used, so `Wu`'s break frequency was moved 200 → 18 rad/s instead. Full sweep
and rationale: `mimo_synthesis.md` it.5.

### 14.2 Verdict deltas

| Metric | ±5 A verdict | ±20 A verdict | changed? |
|---|---|---|---|
| worst-corner σ̄(S_o) | MIMO −25 % | MIMO −27 % | no (strengthened) |
| corners where MIMO σ̄(S_o) is lower | 156 / 168 | **167 / 168** | no (strengthened) |
| small-signal share excursion | split by ΔV0 sign (−39 % / +78 %) | split by ΔV0 sign (−62 % / **+11 %**) | no (downside now marginal) |
| **large-signal (2 m/s) share excursion** | **`dec` wins outright** (2.8–5.1×) | **split by ΔV0 sign** (−48 % / +90 %) | **YES — reversed** |
| regen bus excursion | tie (0.983) | tie (0.989) | no (but the *reason* was wrong — §6.1) |
| worst-corner cross-transfer | `dec` wins (0.848 vs 1.147) | **MIMO wins** (0.802 vs 0.848) | **YES — reversed** |
| K-out-of-envelope (waived) | `dec` wins (5.77 vs 10.82) | **MIMO wins** (4.93 vs 5.77) | **YES — reversed** |
| FC-cruise share excursion | tie (within 3 %) | **MIMO wins** (−41 %) | **YES** |
| speed settle after saturation | `dec` wins 11.6× | `dec` wins **45×** | no (worse for MIMO) |
| drive-cycle RMS speed error | `dec` wins 4 % | `dec` wins **2.3×** | no (worse for MIMO) |
| Teensy cost | MIMO 0.58× dec | MIMO **0.90×** dec | no (weakened) |

**Net reading.** The recalibration **strengthened** the frequency-domain and coupling case for
centralization and **sharpened** the post-saturation case against it. The headline structure —
three metrics, three answers, bounded by the ΔV0 sign — is unchanged, and the ΔV0-sign
asymmetry ratio (≈ 2.3× between matching and opposing medians) is essentially identical across
both clamp settings, which is the most robust single result in the study.

**The overall project verdict is unchanged: the decentralized architecture is justified.** It
is unconditionally stable across 4992 corners, it dominates every post-saturation and
drive-cycle metric by margins that *grew* this round, and its advantages do not depend on an
uncalibrated sign. What changed is that several *secondary* arguments for it — cross-transfer,
waived-corner behaviour, large-signal share excursion, implementation cost — no longer hold and
must not be repeated in the write-up.

### 14.3 Amplitude-character changes (read before comparing to ±5 A plots)

Step amplitudes were held identical for comparability, but what they exercise changed:

| | ±5 A | ±20 A |
|---|---|---|
| drive AW saturation threshold `e_sat` | 13.6 mm/s | **54.4 mm/s** |
| acceleration limit `a_max` | 2.26 m/s² | **9.04 m/s²** |
| 0.05 m/s step | linear | linear, far from the clamp |
| 0.5 m/s step (synthesis gate) | **actuator-limited**, 23.2 s settle | **linear**, 150 ms settle, 11.79 A peak |
| 2 m/s step rail fraction | 1.31–1.49 % | **0.18–0.34 %** |
| drive-cycle rail fraction | 2.98–2.99 % | **0.37–0.67 %** |
| regen rail fraction | 1.31–1.50 % | **0.18–0.34 %** |
| FC-cruise: MIMO droop pinned at 0.85 | 79.8 % of horizon | **0.4 %** |

Two consequences for how results are read. (a) The 0.5 m/s synthesis gate
*"drive DC tracking exact after actuator-limited slew"* no longer passes through a saturation
episode, so the §8.3 anti-windup sim is now the only place that property is tested under
saturation. (b) Integrator-only anti-windup on the decentralized drive half is now **clean to
~0.2 m/s steps** — but it still fails the 0→2 m/s gate, so the Hanus self-conditioned form is
still required and the Q4 cost argument stands.
