# controller_design_MIMO — MIMO H∞ Controller Design (share + drive)

Design workspace for the outlook section `papers/Droop_Control/sections/06_mimo_outlook.tex`:
a 2×2 H∞ controller over the coupled droop-share / drive plant, compared against a
decentralized baseline (the shipped SISO Youla-H share controller + a newly synthesized
SISO Youla-H drive controller), on the SC001 as-built vehicle plant.

**Status: Design study complete — bench calibration pending; coefficients emitted but
NOT wired into firmware.**

See the implementation plan (`we-need-to-extend-cached-star.md`) for the full design
rationale, corner-family definitions, and gate list. This README tracks what exists in
this folder and how to run it.

## Contents (read in this order)

| Step | File | Purpose |
|---|---|---|
| 1 | [`mimo_system_model.md`](mimo_system_model.md) **done** | The 2×2 plant: G11 (share), G22 (drive), G12 (drive→share coupling), G21≈0; corner-family definitions; parameter provenance + `TODO(calibrate)` table. |
| — | [`plant_mimo.py`](plant_mimo.py) **done** | 2×2 design-plant builders, OP/corner family, scaling matrices (`De`/`Du`). |
| — | [`full_model_mimo.py`](full_model_mimo.py) **done** | 11+4-state full-order truth model — `tps61288_full_model.py` copied + extended with a δI_load input and [α̂, v̂_bus] outputs; validates the 8-state design plant. |
| — | [`shipped_share.py`](shipped_share.py) **done** | Deterministic re-derivation of the SHIPPED Youla-H share controller as importable objects (`shipped_share_controller()`), gated against the frozen `controller_design/synthesis_metrics.txt` snapshot; read-only drift check vs the live firmware header (warn, not fail). |
| — | [`validate_mimo_model.py`](validate_mimo_model.py) **done** | Phase-1 gate battery: G11≡SISO plant, drive DC gain, coupling-gain finite-diff, G21≈0 vs full-order graft, design-vs-full-order envelope, Tier-1 well-posedness, RGA(0)=I check. |
| 2 | [`mimo_synthesis.md`](mimo_synthesis.md) **done** | Design record: weights, scaling, DGKF synthesis, MIMO Youla-H T(0)=I correction, order reduction, 500 Hz discretization, gate table, Teensy cost section. |
| — | [`hinf_mimo.py`](hinf_mimo.py) **done** | MIMO H∞ synthesis library: dimension-general primitives (copied from `controller_design/hinf_synthesis.py`), `AugPlantMIMO`, full two-Riccati `hinfsyn_dgkf`, `split_integrator_multi`, RGA/singular-value analysis helpers. Self-tests via `python hinf_mimo.py`, including the SISO regression anchor (γ_opt = 0.6532 ± 0.005) and a Y-ARE≈0 degeneracy cross-check against the shipped pipeline. |
| — | [`synthesize_drive_siso.py`](synthesize_drive_siso.py) **done** | Decentralized-baseline drive half: papers' SISO Youla-H recipe applied to G22, Tustin at 2 ms (500 Hz motor channel). |
| — | [`synthesize_mimo_controller.py`](synthesize_mimo_controller.py) **done** | Main MIMO pipeline: DGKF synthesis → MIMO Youla-H DC correction → integrator split + balanced truncation → 500 Hz Tustin discretization → anti-windup → coefficient/reference-vector emission. |
| 3 | [`mimo_comparison.md`](mimo_comparison.md) **done** | Results: RGA, corner tables, time-domain sims, verdict. Feeds `06_mimo_outlook.tex` claim slots (see note below). |
| — | [`compare_controllers.py`](compare_controllers.py) **done** | Comparison harness: MIMO controller vs decentralized baseline (both) closed against the identical coupled 2×2 plant — RGA/σ̄ sweeps, worst-corner `‖S‖∞`, drive-transient share excursion, regen-event bus excursion, FC-charge-cruise, drive-cycle-like profile. |
| — | [`plot_mimo_results.py`](plot_mimo_results.py) **done** | Thesis figures (SVG) rendered from the comparison CSVs. |
| — | [`compute_Su.py`](compute_Su.py) **done** | Input-sensitivity check σ̄(S_u) per Neoclassical Control §12.7.2 (both controllers, nominal + worst corner); emits the S_u numbers quoted in the internal report. Result: benign — dec 1.385/1.864, MIMO 1.309/1.414. |
| — | `mimo_controller_coeffs.h` **generated** | State-space header for the MIMO controller (not wired into the firmware build). |
| — | `mimo_reference_vectors.h` **generated** | 2-in/2-out replay reference vectors. |
| — | `drive_siso_coeffs.h` **generated (optional)** | Baseline drive controller in the shipped biquad format. |
| — | `drive_siso_metrics.txt` / `mimo_synthesis_metrics.txt` / `comparison_metrics.txt` **generated** | Numeric summaries of each pipeline stage. |
| — | `mimo_crosscheck.m` **done** | MATLAB cross-validation (run elsewhere; Control + Robust Control Toolbox, R2024b syntax). Rebuilds the 2×2 plant independently, re-runs hinfsyn + the MIMO Youla-H T(0)=I correction, parses `mimo_controller_coeffs.h`, and re-runs the 576-corner battery + small-signal transients. Writes `MATLAB_mimo_results.txt` + 3 PNGs — hand the .txt back to Claude to check. **STALE (2026-08-16):** the plant constants are hardcoded in the .m file against the retired pre-calibration plant, so it now cross-checks green against equally-stale metrics. The "verified to 8e-16" agreement was a transcription check against `plant_mimo.py` **as it stood on 2026-08-04**; it says nothing about the current plant and no longer holds. |
| — | `figures/` **done** | SVG figures + raw CSV data for the thesis. |

## Environment

```
uv venv ctrl-venv && uv pip install --python ctrl-venv numpy scipy matplotlib
```

No MATLAB/slycot on this machine — the H∞ synthesis (`hinfsyn_dgkf`) is implemented from
scratch (Hamiltonian/Schur + scipy-balanced ARE, self-tested against `scipy.linalg`), the
same approach as `controller_design/hinf_synthesis.py`.

Run order (each script exits non-zero on any gate failure):

```
ctrl-venv/Scripts/python hinf_mimo.py                    # library self-tests
ctrl-venv/Scripts/python validate_mimo_model.py           # plant-model checks
ctrl-venv/Scripts/python shipped_share.py                 # shipped-share re-derivation + gates
ctrl-venv/Scripts/python synthesize_drive_siso.py          # decentralized baseline: drive half
ctrl-venv/Scripts/python synthesize_mimo_controller.py     # main MIMO pipeline + artifact regen
ctrl-venv/Scripts/python compare_controllers.py             # MIMO vs decentralized, same coupled plant
ctrl-venv/Scripts/python plot_mimo_results.py                # figures
```

## Key results

> ## ⚠ STALE — the MIMO study below is frozen on a RETIRED plant (2026-08-16)
>
> The drive channel was **calibrated on 2026-08-16** (`calibration/motor_id_20260815.md`,
> `mimo_system_model.md` §4.2/§4.4/§9.2). `plant_mimo.py` now carries the measured
> constants, so **every MIMO artifact in this directory was built against a plant that no
> longer exists**: `G22(0)` 3.7085 → 1.4112 (m/s)/A, drive pole −0.1219 → −0.0914 rad/s,
> `i_m0` 0.973 → 4.074 A, `G12(0)` −2.757e-2 → −1.326e-2, `A_i` 0.2429 → 0.0922. The
> firmware clamp also moved **20 A → 12 A**.
>
> **What is current:** `plant_mimo.py`, `mimo_system_model.md` §4.2/§4.4/§9.2/§9.3/§10/§11,
> `synthesize_drive_siso.py` and its artifacts (`drive_siso_coeffs.h`,
> `drive_siso_metrics.txt`, `figures/drive_siso_step.csv`, `figures/drive_siso_replay.csv`),
> and `validate_drive_siso.py`.
>
> **What is stale, and how each stage now fails** — none of these fail loudly on their own,
> which is why they are listed:
>
> * `compare_controllers.py` — **hard-crashes at stage 6** on an assertion that the clamp is
>   20 A. It cannot be run at all until the round below is done.
> * `synthesize_mimo_controller.py` — **regresses 56/0 → 54/2 gates** on the calibrated
>   plant. The MIMO Youla-H DC correction no longer closes. This is a **design** failure, not
>   a stale constant: regenerating the MIMO controller is a new synthesis round (weights,
>   scaling and the `T(0) = I` correction all need revisiting), **not** a mechanical re-run.
> * `compute_Su.py` — flips **PASS → DRIFT**.
> * `mimo_crosscheck.m` — hardcodes the retired plant, so it will cross-check *green* against
>   the un-regenerated metrics. This is the most dangerous of the four: it produces a false
>   confirmation rather than an error. A banner is at the top of that file.
> * `mimo_comparison.md`, `mimo_synthesis.md`, `mimo_controller_coeffs.h`,
>   `mimo_reference_vectors.h`, `mimo_synthesis_metrics.txt`, `comparison_metrics.txt`,
>   `MATLAB_mimo_results*.txt`, and every `figures/mimo_*`/`fig_*` artifact — numerically
>   stale.
>
> The artifacts are **deliberately kept, not deleted**: they are the published record of the
> ±20 A round and the basis of the thesis comparison as it currently stands. Nothing here is
> regenerated piecemeal.
>
> **Superseded conclusion (`mimo_system_model.md` §2.1).** The "±20 A makes the motor clamp
> and the ≈67–87 W converter budget bind *together*" argument is **reversed**, not merely
> re-numbered. At 12 A and the measured `A_i` = 0.0922 A/A, the motor clamp draws
> **≈1.11 A ≈ 17.6 W** at the bus — a factor of ~4 below the budget. The **motor clamp is now
> the binding limit**, and the bus-power budget is not approached at all. Any argument that
> relied on the two coinciding must be re-derived.
>
> ---
>
> **Superseded — ±20 A recalibration round, 2026-08-04.** `MOTOR_I_CMD_MAX` / `I_CLAMP` moved
> **5 A → 20 A** (motor-side; ≈ 4.86 A / ≈ 77 W bus-side at cruise, so the motor clamp and the
> ≈ 67–87 W converter budget were held to bind together — `mimo_system_model.md` §2.1; **this
> claim is reversed above**). Both controllers were re-synthesized and every metric below
> regenerated. **The overall verdict is unchanged** — the decentralized architecture stays
> justified — but several secondary arguments for it reversed (worst-corner cross-transfer,
> waived-corner robustness, large-signal share excursion, and the size of the
> implementation-cost advantage). Deltas are catalogued in `mimo_comparison.md` §14;
> superseded ±5 A numbers are kept, not deleted. The MATLAB cross-check was re-run at ±20 A
> (04-Aug-2026): VERDICT PASS on all six criteria (`MATLAB_mimo_results.txt`; the ±5 A log is
> `MATLAB_mimo_results_5A.txt`) — **against the retired plant**.

**Machinery.** `hinf_mimo.py` implements a general two-Riccati DGKF H∞ synthesis (dimension-
general, self-tested against `scipy.linalg`). The SISO regression anchor gives γ_opt = 0.6505
vs the shipped controller's 0.6532 (within the documented ±0.005 solver-accuracy band — the
gap is solver-accuracy noise, not a design difference), and the Y-ARE≈0 DGKF degeneracy is
confirmed (the shipped share plant has a structurally singular Y-Riccati, consistent with its
single-input/single-output integrator structure). `shipped_share.py` reproduces the shipped
Youla-H share controller (γ_opt ≈ 0.65, kI ≈ 112, T(0)=1 exact) via the same general machinery,
and its firmware drift check is clean against `teensy_controller/share_controller_coeffs.h` as
of git `51b8962`.

**MIMO controller.** The synthesized 2×2 H∞/Youla-H controller has **9 states at Ts = 2 ms**
(2 exact integrators + 7 stable modal remainder; the order budget was deliberately raised
8 → 10 rather than loosening the reduction tolerance — `mimo_synthesis.md` §6), with an
a-posteriori achieved γ = **1.6456**. T(0) = I holds structurally (‖M − I‖ = 1.57e-4). Across the full Tier-1
stability battery (5760 corners = 10 OPs × 24 share corners × 24 drive corners, 4992 feasible
after excluding 768 unidirectional-switch-clamped corners), the closed loop is unstable in
**0/4992** cases, checked in both continuous and discretized (500 Hz) form. Over the Tier-2
performance battery, the worst in-envelope σ̄(S_o) is **1.8754** *(subsample lower bound —
the MATLAB full 24×24 sweep at ±20 A found σ̄(S_o) = 1.9443 at a corner outside the rep set,
reproduced by Python at 1.9445; stability unaffected — see `mimo_comparison.md` §13a)*. The discretized/float32 firmware-format
controller replays against the float64 reference within **5.52e-6**, and the estimated Teensy
compute cost is **44.5 kMAC/s**, vs **49.5 kMAC/s** for the decentralized baseline.

**Comparison verdict** (full detail in `mimo_comparison.md`, backed by `comparison_metrics.txt`):
worst in-envelope σ̄(S_o) is 2.5535 (decentralized) vs **1.8754** (MIMO), a **27 %** reduction
for the MIMO design, which is now the better controller at **167 of 168** in-envelope corners.
The input-node check agrees (σ̄(S_u) 1.3852 vs 1.2385 nominal, 1.8640 vs 1.4749 worst-corner).
Nominal cross-transfer ‖T(α←v_ref)‖ is **195×** better for the MIMO controller in the
continuous domain (a *nominal-point, continuous-domain* figure — see `mimo_comparison.md`
§13), but that advantage is bounded by the sign of ΔV0: the median cross-transfer ratio is
**0.94** at the synthesis-assumed sign (a slight win) vs **2.16** if ΔV0 is mirrored. The
regen-event bus excursion is effectively a tie (ratio 0.989) — and §6.1 of the comparison doc
now shows this is because the bus excursion is set by the **peak** current both controllers
reach, *not* because both rail for the whole event; it is not a usable discriminator.

Decentralized wins the **post-saturation** cases decisively (speed settle 0.50 s vs 22.45 s
after a 2 m/s step; 2.3× better drive-cycle RMS tracking) and shares the clean **0/4992**
Tier-1 stability record. K12/K11 = **2.15 %** quantifies how weakly the drive channel couples
back into the share controller's own gain. Headline: **the decentralized baseline is justified
on stability grounds** (unconditionally stable across the corner family, with no stability
advantage available to the MIMO design) **and on large-signal/post-saturation behaviour**,
while **the MIMO controller buys bounded in-envelope robustness and coupling rejection and is
still — more narrowly — the cheaper implementation** (0.90× the MAC/s, one fewer state; it was
0.58× at ±5 A) — a trade worth recording for the thesis outlook section but not (yet) a case
for replacing the shipped decentralized controller.

**MATLAB cross-validation: PASS at ±20 A (04-Aug-2026).** `mimo_crosscheck.m` independently
confirmed the shipped ±20 A design on all six criteria (`MATLAB_mimo_results.txt`): plant DC
gain to 2.23e-9, `hinfsyn` γ = 1.0851 (between the Python bisection 0.8977 and the shipped
a-posteriori 1.6456, exactly as the P_f degeneracy predicts), ‖M_YH − I‖ = 9.631e-5, T(0) = I
exactly on the parsed header, nominal σ̄(S_o) 1.2623 vs Python 1.2287 (ZOH vs continuous,
inside the 5 % criterion), a-posteriori ‖Tzw‖∞ 1.6457 vs 1.6456 (0.006 %), implemented-loop
‖T(α←v_ref)‖ = 1.109e-2 matching Python exactly, 576/576 corners stable, transients within
5 %. The exhaustive 24×24 sweep worst was **1.9443**, independently reproduced by the Python
model at **1.9445** — reconfirming the rep-set-subsample caveat first found at ±5 A. Full
addendum: `mimo_comparison.md` §13a (±5 A run preserved as §13 /
`MATLAB_mimo_results_5A.txt`).

**Open items.**
- Bench calibration: every `TODO(calibrate)` / `TODO(verify)` / `[measure]` item in
  `mimo_system_model.md` §9 remains open. **ΔV0** (the no-load voltage mismatch) is the
  highest-value measurement — it controls the *sign* of the drive→share coupling and therefore
  which side of the median cross-transfer ratio (**0.94 vs 2.16**) the real hardware sits on.
- ~~Re-run `mimo_crosscheck.m` in MATLAB to revalidate the ±20 A design~~ — **done
  04-Aug-2026, PASS** (`MATLAB_mimo_results.txt`; `mimo_comparison.md` §13a).
- A pre-existing gap, not introduced by this round: some corners (FC-cruise, light load) fall
  outside the shipped SISO share controller's own K envelope and are waived out of Tier-2
  rather than resolved.
- The large-signal/saturated-actuator comparisons (§5.2, §6, §8 of `mimo_comparison.md`) are
  caveated as actuator-limited — both controllers hit the same droop-ratio clamp, so those
  results characterize the plant/actuator limits as much as the controllers.

## Note: `06_mimo_outlook.tex` claim slots

`papers/Droop_Control/sections/06_mimo_outlook.tex` is the placeholder section this
sub-project fills in. Its claim slots (RGA/coupling structure, worst-corner `‖S‖∞`
comparison, drive-transient share excursion, regen-event bus excursion, Teensy
implementation cost) map onto the metrics emitted by `mimo_comparison.md` /
`compare_controllers.py` (Step 3, §6 of the implementation plan). **The `.tex` file
itself is not edited by this sub-project** — only read as the source of the claims it
expects `mimo_comparison.md` to back up.

## Self-containment

**Hard constraint: this sub-project writes only inside `controller_design_MIMO/`.**
`controller_design/`, `teensy_controller/`, and `papers/` are read-only from here.
Needed code and constants are copied in with explicit provenance comments
(`# COPIED from <path> @ <git hash>` or `# ADAPTED: <what changed>`); the reference
hash for everything copied so far is `51b8962` (the last `controller_design/` commit
at the time this sub-project was scaffolded). `git status` should show changes only
under `controller_design_MIMO/` at every checkpoint.
