# H∞ + Youla-H Controller Synthesis — Design Record

Companion to `system_model.md` (the plant). This documents the synthesis of the robust
power-share controller that replaces `PI_Controller_Power()`, the validation evidence,
and the path from mathematics to the C++ in the firmware. Method:
*A Practical Youla Gain-Tuning Framework for H∞ Controller Realization*
(Tan, Yadav, Assadian 2026) — H∞ mixed-sensitivity synthesis followed by the Youla-H
post-synthesis gain adjustment enforcing $T(0)=1$.

**Reproduce:** `hinf_synthesis.py` (library; run directly for its self-tests) →
`synthesize_controller.py` (full pipeline; regenerates every artifact) →
`plot_results.py` (figures). Python venv: `uv venv && uv pip install numpy scipy matplotlib`.
`droop_plant.m` is the MATLAB cross-validation harness: it re-synthesizes with the
exact shipped weights, parses `share_controller_coeffs.h` (so it always tests the
coefficients actually in the firmware), and re-runs the corner/step/ramp battery in
the firmware-accurate topology. It writes `MATLAB_validation.txt` and three
`figures/MATLAB_*.png` automatically. A pre-alignment run with the §7 template
weights (`MATLAB_results.txt`, `figures/MATLAB-Fig-*.png`) already corroborated the
method structurally: same DC deficiency → T(0)=1 after Youla-H, M₂ preserved through
the gain change, integrator visible in G_C, and an exact match on the weight-independent
MDAC mapping constant (g = 0.2973 at r = 0.5).

---

## 1. Solver note (no MATLAB on this machine)

MATLAB/slycot were unavailable, so the S/KS/T problem is solved by a purpose-built
implementation (`hinf_synthesis.py`):

- Riccati equations via the **Hamiltonian matrix + ordered real Schur** stable-subspace
  method; γ-iteration by bisection on the DGKF feasibility conditions.
- The augmented plant is constructed so the **regular D11 = 0 problem** applies exactly:
  the plant is strictly proper and $W_p$ is chosen strictly proper (first-order
  $W_p = M a/(s+a)$ — a legitimate S-weight, since $S \to 1$ at HF needs no penalty).
- For this structure the estimation Riccati **degenerates analytically**
  ($D_{21}=1 \Rightarrow Q_y = 0$, $A_y = A - B_1C_2$ stable $\Rightarrow Y=0$, $Z=I$,
  $L=-B_1$), leaving one Riccati and the central controller
  $\dot{\hat x} = (A_y + B_2F)\hat x + B_1 e$, $u = F\hat x$. The degeneracy assumption
  is asserted at runtime.
- **Trust chain:** the library self-tests check every primitive against scipy or
  analytic references, and every synthesized controller passes an *a-posteriori gate* —
  closed-loop stability plus $\|T_{zw}\|_\infty \le \gamma$ computed by an independent
  Hamiltonian-bisection norm. A derivation error cannot silently produce a bad
  controller. Final numbers can additionally be cross-checked in MATLAB via
  `droop_plant.m`.

## 2. Plant and weights

Nominal design plant (`system_model.md` §6d, Padé(2) for the delay):

$$G_P(s) = \frac{e^{-T_d s}}{(\tau_r s + 1)(\tau_f s + 1)}, \quad T_d = 1\,\text{ms},\ \tau_r = 100\,\mu s,\ \tau_f = 0.8\,\text{ms}$$

| Weight | Form | Values | Intent |
|---|---|---|---|
| $W_p$ (on S) | strictly proper $\frac{Ma}{s+a}$ | $M = 10^4$, unity-crossing 40 rad/s | integral-action pressure, disturbance rejection below ~40 rad/s |
| $W_d$ (on T) | `makeweight(0.5, 250, 40)` | | force T rolloff above ~250 rad/s (noise, unmodeled HF) |
| $W_u$ (on Y) | `makeweight(0.3, 600, 20)` | | cap actuator effort, roll off MDAC activity above ~600 rad/s |

## 3. Results

| Quantity | Value |
|---|---|
| $\gamma_{opt}$ | **0.6532** (comfortably < 1: all weight targets met with margin) |
| Controller built at | $\gamma = 0.6859$ (5 % back-off), $\|T_{zw}\|_\infty = 0.6841$ ✓ gate |
| H∞ controller order | 7 (= 4 plant + 3 weight states) |
| $T_H(0)$ | 0.99996423 — the classic H∞ DC deficiency (0.0036 %) |
| Achieved S/T crossover | ~110 rad/s (weights allowed more than the 40 rad/s floor; kept — delay margin remains huge, see §5) |
| $\|S\|_\infty,\ \|T\|_\infty,\ \|Y\|_\infty$ | 1.25, 1.00, 1.01 |

**Youla-H step** (paper Eq. 5, numeric): $Y_{YH} = Y_H / T_H(0)$ — a +0.0036 % gain
shift — then $G_{C,YH} = Y_{YH}(1 - G_P Y_{YH})^{-1}$. This plants an exact integrator
in the controller: the near-origin pole of $G_{C,YH}$ came out at $|p| = 5.6\times10^{-9}$
and is snapped to a true integrator by the spectral split below. Result: $T(0) = 1$
**exactly** (machine precision), so the DC mismatch disturbance $d$ of the plant model
is fully rejected and ramp references (EMS share blends) accrue no bias.

## 4. Reduction and discretization

- Spectral split: $G_{C,YH} = \frac{k_I}{s} + R(s)$ with $k_I = 111.93$ (consistent with
  crossover: $|L| = 1$ where $k_I/\omega \approx 1$).
- Balanced truncation of the 21-state stable remainder → **3 states** (Hankel σ:
  14.8, 0.035, 0.0018, 5·10⁻⁵ …); max relative frequency-response error vs the full
  controller **0.8 %**.
- Tustin at $T_s = 1$ ms → three first-order sections + trapezoidal integrator.
  Coefficients: generated into `teensy_controller/share_controller_coeffs.h` (never
  hand-edit). Note one section carries the slow pole $z = 0.999996$ — the $W_p$ weight
  pole reappearing nearly-cancelled in the controller; it is representable in float32
  and its Hankel σ (0.035) says it genuinely contributes.

## 5. Validation evidence (all automated in `synthesize_controller.py`)

| Check | Result |
|---|---|
| Continuous corner sweep — 60 corners: $K \in \{0.55..1.45\}$, $T_d \in \{0.5,1,2\}$ ms, $\tau_r \in \{20,300\}$ µs, $\tau_f \in \{0,0.8\}$ ms | **all stable**; worst $M_2 = 0.59$ (at K=1.45, Td=2 ms) |
| Nominal margins | $M_2 = 0.80$, PM = 73.9° at 110 rad/s, **delay margin 11.7 ms** (≈ 6× the worst-case modeled delay) |
| Discrete corner sweep (ZOH plant ⊗ implemented $G_C(z)$) | all $|z| < 1$ |
| Step 0.5 → 0.7 (nominal, discrete) | 2 % settle **22 ms**, overshoot 0 %, SS error 8·10⁻⁹ |
| Ramp 0.05 share/s | tracking error → 4·10⁻⁴ (no accumulating bias — the Youla-H point) |
| Anti-windup (reference into the 0.85 rail, 0.5 s) | output rails cleanly, leaves the rail ≤ 3 ticks after error reversal, recovery < 150 ms |
| **Legacy PI comparison** (worst corner, discrete $\|S\|_\infty$) | Youla-H **1.87** vs PI $K_p{=}K_i{=}1$ **26.9** — the PI is near-unstable at the parameter corners; the robust design is the difference between a 5.4 dB and a 28.6 dB sensitivity peak |

Figures (`figures/`): `loopshapes_youla_h.svg` (S/T/Y vs 1/weights),
`controller_bode.svg` (H∞ vs Youla-H vs reduced vs discrete — the DC integrator is
visible as the diverging low-frequency branch), `timedomain_step_ramp.svg`.
Raw data in the matching CSVs. `synthesis_metrics.txt` is the generated numeric summary.

## 6. C++ implementation (firmware)

| Piece | Where | Notes |
|---|---|---|
| Coefficients | `teensy_controller/share_controller_coeffs.h` | **generated** — regenerate after bench calibration |
| Runtime | `teensy_controller/share_controller.h` | `shareControllerStep()`: DF2T biquad cascade + trapezoidal integrator, output $u = 0.5 + R(z)e + I(z)e$ clamped to $[0.15, 0.85]$ with back-calculation anti-windup (integrator absorbs the clamp excess; biquads are stable and never wound) |
| Wrapper | `teensy_controller.ino` `youlaController_Power(setpoint, alphaRaw)` | gates the update to $T_s$ = `SHARE_CTRL_TS_US` via `micros()`, holds the output between updates (this ZOH is in the design plant); applies the 200 Hz measurement prefilter (`shareControllerFilterMeas`, coefficient generated as `SHARE_CTRL_MEAS_FILT_A`) to the measured share only — the EMS setpoint is not smoothed |
| Selection | `USE_YOULA_SHARE_CONTROLLER` (default 1) | legacy PI kept compiled as bench fallback / A-B path |
| Freeze semantics | unchanged | `powerBalance()` early-returns when $I_{tot}\approx 0$, so controller states hold — matches the model's validity limits (§3 of system_model.md) |

Host-native tests (`test/test_main.cpp`): replay of **generated reference vectors**
(64 ticks incl. a saturated episode, C++ float vs Python double, tol 5·10⁻⁴),
zero-error hold, integral ratchet, anti-windup rail entry/exit, wrapper Ts-gating,
and `powerBalance()` integration through the corrected MDAC mapping.
**314 production + 6 bench tests pass.**

## 7. Recalibration loop (do this after the bench work of system_model.md §9)

1. Update `TD_NOM/TAUR_NOM/TAUF`, the corner sets, and (if $\Delta V_0$ measured) the
   gain set in `synthesize_controller.py`; update `K_DROOP` in the `.ino` if $k_d$ changes.
2. Re-run `synthesize_controller.py` — it regenerates `share_controller_coeffs.h` and
   `reference_vectors.h` and re-runs every gate.
3. Rebuild the host tests (`cd test && mingw32-make` from MSYS2) — the reference-vector
   test revalidates the C++ against the new design automatically.
4. Cross-check in MATLAB with `droop_plant.m` — it re-parses the regenerated
   `share_controller_coeffs.h` automatically, so no MATLAB-side edits are needed
   unless the plant nominals/corner grid changed (§A/§C constants at the top).
   Review `MATLAB_validation.txt` for the verdict line.

## 8. Known limitations / open items

- All plant timing numbers are **pre-calibration estimates** (`TODO(calibrate)`):
  $T_d$, $\tau_r$, $C_{bus}$, $\Delta V_0$, and $k_d$. The corner sweep is the hedge;
  the design is deliberately delay-tolerant (11.7 ms margin vs 2 ms worst modeled).
- The measurement prefilter $\tau_f$ = 0.8 ms **is implemented** — as a one-pole
  filter on the measured share inside `youlaController_Power()`, at the controller's
  own 1 kHz cadence (loop-equivalent to the design plant's placement). The corner
  sweep also covers $\tau_f = 0$, so a bench decision to disable it (set `TAUF = 0`
  and resynthesize) stays inside the validated set.
- Plant gain assumed positive-definite over the operating set: at $I_{tot} < ~1$ A with
  worst-case mismatch the gain envelope of `validate_model.py` widens beyond the design
  set; the EMS should avoid commanding extreme shares at near-zero load (the loop is
  frozen at $I_{tot} \approx 0$ regardless).
- Float32 wordlength: the slow section pole ($1 - z^{-1}$ distance 4·10⁻⁶) is ~30×
  above float32 eps at 1.0; the reference-vector test bounds short-horizon error and
  stability bounds the long horizon. If a respin ever moves to double precision this
  note is moot.
