# Full-Order TPS61288 Model — Empirical Validation of the Simplified Design Plant

Companion to `system_model.md`. The Youla-H share controller was synthesized against the
deliberately simplified plant of §6d,
$G_P(s) = K\,e^{-T_d s}/((\tau_r s + 1)(\tau_f s + 1))$, in which the two TPS61288
converter voltage loops are lumped into the single first-order lag $\tau_r$. §6e argued
that lump valid by datasheet arithmetic (time-scale separation). This document makes the
argument **empirical**: a complete small-signal LTI model of the share plant — full
TPS61288 dynamics per datasheet §9.2.2.5 on both channels, the droop-injection network,
bus coupling, sense chain, and the digital layer — is constructed independently, and the
simplified model is shown to cover it, both open-loop and closed-loop with the shipped
controller.

**Implementation:** `tps61288_full_model.py` (all results below are its gate-checked
output; regenerate with the ctrl-venv Python). MATLAB mirror: `full_order_model.m` →
`MATLAB_fullorder_validation.txt`. Figures: `figures/fullorder_*.svg` (+ CSVs).

---

## 1. Model structure

### 1.1 Per-channel converter: Norton equivalent that reduces exactly to DS Eq. 7

The TPS61288 is a current-mode boost; with the inner current loop treated as ideal
(valid far below $f_{SW}$ = 500 kHz), each converter is modeled as a **Norton
equivalent** at its output node:

$$\hat i_{N} = K_{COMP}\,(1{-}D)\,\Big(1 - \frac{s}{\omega_{RHPZ}}\Big)\,\hat v_{comp},
\qquad R_{int} = \frac{V_{bus,0}}{I_{0}},\qquad
\omega_{RHPZ} = \frac{R_{int}(1{-}D)^2}{L}$$

with the local output capacitance in shunt. The datasheet's power-stage model (Eq. 7)
embeds a *resistive load* and therefore cannot be paralleled directly; the Norton form
can. The license for the abstraction is that it **reduces exactly to Eq. 7** when
terminated in a single resistive load $R_o = R_{int}$: the two parallel resistances give
the $R_o/2$ gain factor and the $2/(R_oC_o)$ load pole, and the ESR and RHP zeros carry
through.

> Gate A result: Norton vs exact parallel-impedance algebra — max relative error
> **4.5×10⁻¹⁶** (machine precision). Versus the DS Eq. 7 form: 5×10⁻⁴, exactly the
> documented ESR-in-the-pole approximation of DS Eq. 8 (bound $ESR/(R_o/2)$).

### 1.2 Error amplifier: exact compensation impedance

Rather than the datasheet's factored two-pole approximation (Eq. 11), the gm-amp is
modeled with the exact COMP-pin impedance
$Z_{comp}(s) = R_{EA} \,\|\, (R_C + 1/sC_C) \,\|\, 1/sC_P$, i.e.

$$\hat v_{comp} = -\,G_{EA}\,Z_{comp}(s)\,\hat v_{FB}, \qquad
Z_{comp}(s) = \frac{1 + sR_CC_C}{s^2 R_CC_CC_P + s(C_P + C_C + R_CC_C/R_{EA}) + 1/R_{EA}}$$

$R_{EA}$ (EA output resistance) is **not specified** in the datasheet EC table; it sets
only the low-frequency compensator plateau (the loop is $R_{EA}$-independent in the
gm-integrator region around crossover), so it is swept 1–100 MΩ in the envelope study —
a documented non-sensitivity, verified rather than assumed.

### 1.3 FB node, droop injection, and the bilinear control term

The three-resistor FB node (superposition; the OPA197 output is a driven node):
$\hat v_{FB} = h_1\hat v_o + h_2\hat v_{op}$ with
$h_1 = (R_{D2}\|R_{inj})/(R_{D1} + R_{D2}\|R_{inj})$ and $h_2/h_1 = R_{D1}/R_{inj}$
exactly — recovering the static droop law of `system_model.md` §2 at DC.

The droop injection is **bilinear** in (sensed current, MDAC gain); linearized at the
operating point $(g_0, I_0)$:

$$\hat v_{op} = A_v K_{sns}\big(g_0\,H_{INA}(s)\,\hat i \;+\; I_0\,\hat g\big),
\qquad \hat g_F = -\tfrac{k_d}{R_{e,max}r_0^2}\hat r,\quad
\hat g_B = +\tfrac{k_d}{R_{e,max}(1-r_0)^2}\hat r$$

The $I_0\,\hat g$ term is where the control input enters the loop; the $g_0\,\hat i$ term
closes each channel's analog droop feedback. $H_{INA}$: one pole at 350 kHz.

### 1.4 Interconnection

Node structure: per-channel output node ($C_{O,i}$, Norton shunt $R_{int,i}$) — 2 mΩ INA
shunt (also the current-sense element) — shared bus node ($C_{bus}$; 30 µF Idle,
~500 µF Run with the V-MOT node connected) — CC load (matching the CAL procedures).
Linearized share output $\hat\alpha = (I_{B0}\hat i_F - I_{F0}\hat i_B)/I_{tot,0}^2$;
digital layer identical to the simplified model (Padé(2) of $T_d$ = 1 ms; ZOH at
$T_s$ = 1 ms for the discrete studies). Result: an **11-state** LTI model
$r \to \alpha$ per operating point (vs 2 states + delay in the simplified design model).
ESR of the ceramic output caps is omitted from the interconnection (its zero sits at
≥ 5×10⁶ rad/s, four decades above the converter crossover; it is retained in the Gate A
reduction check). PFM light-load operation is out of scope (CCM small-signal model;
see `system_model.md` §6e item 3 for why PFM cannot threaten the share loop).

## 2. Structural gate checks (model self-verification)

| Gate | Result |
|---|---|
| A — Norton ≡ DS Eq. 7 reduction | exact to 4.5×10⁻¹⁶ (§1.1) |
| B — DC gain $d\alpha/dr$ from the full linearization | **0.9933** — the statics' unity gain emerges, short of 1 only by the finite EA DC gain ($G_{EA}R_{EA}$); the controller's exact integrator makes closed-loop tracking exact regardless (ramp gate below) |
| B′ — open-loop stability | all poles LHP (slowest at −3×10³ rad/s) |
| C — per-channel voltage-loop crossovers | FC: 16.33 kHz vs §6e formula 16.84 (ratio 0.97); FC/66µ: 7.59 vs 7.65 (0.99); BT/7.4V: 13.52 vs 13.84 (0.98); BT/8.4V/66µ: 7.09 vs 7.14 (0.99) — the independent state-space assembly reproduces the §6e datasheet arithmetic to 1–3 % |

## 3. Open-loop comparison: full vs simplified

- **Nominal vs nominal** (design band ω ≤ 1100 rad/s, ~10× the share-loop crossover):
  max deviation **3.86 %** (`figures/fullorder_bode_overlay.svg` — the traces are
  visually indistinguishable through the band; they separate only beyond ~10⁴ rad/s
  where the loop gain is far below unity).
- **Envelope study** (`figures/fullorder_envelope.svg`): 432 operating points
  {V_in,FC 9/12} × {V_in,BT 7.4/8.4} × {I_tot 1/2/4 A} × {r₀ 0.3/0.5/0.7} ×
  {C_O 30/66 µF} × {C_bus 30/500 µF} × {R_EA 1/10/100 MΩ}. Every full-order response
  lies within **5.78 %** (median 4.30 %) of some member of the simplified corner family
  ({T_d 0.5/1/2 ms} × {τ_r 20/100/300 µs}, K = 1). The corner family visibly *bounds*
  the full-order family with margin — i.e., the uncertainty set used for synthesis was
  a superset of the true dynamics.
- Gain uncertainty (K ≠ 1) is the **static mismatch axis**, validated exactly and
  separately by `validate_model.py` (the closed-form $\alpha = r + \Delta V_0
  r(1{-}r)/(k_d I_{tot})$ law); this study isolates the **dynamic** axis. The two are
  orthogonal by construction.

## 4. Closed-loop equivalence with the shipped controller

The shipped $G_C(z)$ (parsed from `share_controller_coeffs.h`, with the measurement
filter $H_f(z)$ in the feedback path — firmware-accurate topology):

| Check | Full-order model | Simplified-model result |
|---|---|---|
| Discrete CL stability | **432/432** operating points | 60/60 corners |
| Worst discrete ‖S‖∞ | **1.240** | 1.867 (corner family) |
| Step 0.5→0.7 overlay | max divergence **0.0008 share** (`fullorder_step_overlay.svg`) | — |
| 2 % settle | 25 ms | 22–25 ms |
| Ramp tracking error (t = 3 s) | 4.3×10⁻⁴ → 0 | 4.5×10⁻⁴ |

The full-order worst ‖S‖∞ (1.24) being *lower* than the simplified corner-family worst
(1.87) is the expected sign: the corner family was deliberately pessimistic (2 ms delay,
300 µs lag corners), and the true dynamics sit well inside it.

## 5. Conclusion (thesis statement)

The reduced-order design model of `system_model.md` §6d is **empirically valid**: an
independently constructed full-order model containing every dynamic element of the
TPS61288 datasheet's small-signal description deviates from it by < 4 % nominally and
< 6 % across a 432-point operating envelope within the design band, and the synthesized
controller's closed-loop behavior on the full-order plant is indistinguishable from its
design predictions (step responses coincide to < 10⁻³ share; robustness margins are
*better* than the design's worst case). The simplification — lumping two ~7–22 kHz
converter voltage loops into one 20–300 µs uncertain lag beneath a 17.5 Hz share loop —
discards nothing the controller can perceive.

## 6. Reproduction

```
ctrl-venv/Scripts/python tps61288_full_model.py   # ALL GATES PASSED + CSVs + metrics
ctrl-venv/Scripts/python plot_results.py          # renders fullorder_*.svg
# MATLAB (optional cross-check): run full_order_model.m
#   -> MATLAB_fullorder_validation.txt must end VERDICT: PASS
```

After bench calibration changes any constant (`system_model.md` §9 →
`controller_synthesis.md` §7 regeneration loop), re-run `tps61288_full_model.py` last:
it re-parses the firmware coefficients and re-validates the whole comparison
automatically. Numeric summary of the current run: `fullorder_metrics.txt`.
