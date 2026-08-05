# MIMO Share/Drive Plant Model

**Scope:** the 2×2 small-signal design plant for the combined **current-share** and
**vehicle-speed** control problem on the SC001 scale car / DC balancer board, plus the
full-order truth model used to validate it. This is the parameter and plant **source of
truth** for `controller_design_MIMO/`; the synthesis record lives in `mimo_synthesis.md`
and the results in `mimo_comparison.md`.

**Relationship to `controller_design/`.** The SISO share model
(`controller_design/system_model.md`) is *unchanged and unmodified* — this sub-project only
reads it. Every constant reused from it is copied with a `# COPIED from … @ 51b8962`
provenance comment in `plant_mimo.py` / `full_model_mimo.py`. Where this document extends
or refines the SISO model, the refinement is called out explicitly (§7).

> **±20 A recalibration round — 2026-08-04.** `MOTOR_I_CMD_MAX` / `I_CLAMP` moved
> **5 A → 20 A**. That changes the actuator limit (§2.1), the input scaling
> `Du = diag(0.35, **20.0**)` (§8), and therefore every SCALED quantity in this document
> (the §5 coupling ratios in particular, which are 4× their ±5 A values — the *physical*
> coupling is unchanged). Superseded ±5 A values are kept alongside rather than deleted.

**Status (Phase 1 complete).** All 12 Phase-1 gates in `validate_mimo_model.py` pass.
Numbers quoted below are emitted by that script, not hand-copied.

**Files:**

| File | Role |
|---|---|
| `plant_mimo.py` | 2×2 design-plant builders, OP algebra, corner families, scaling |
| `full_model_mimo.py` | 15-state full-order truth model (copied 11-state TPS61288 model + drive graft) |
| `validate_mimo_model.py` | Phase-1 gate battery (G1.0 … G1.6, RGA) |
| `hinf_mimo.py` | general H∞ / state-space library (Phase 0, already verified) |

---

## 1. Notation (collision table)

The share literature, the powertrain-Youla papers, and the firmware all reuse the same
letters for different things. **This table is binding for the whole sub-project.**

| Symbol | Meaning here | Units | Explicitly NOT | Source |
|---|---|---|---|---|
| `r` | **droop ratio command** — the split the firmware asks for, `r ∈ [0.15, 0.85]` | – | *not* tire radius, *not* a reference signal | firmware `DROOP_R_MIN/MAX` |
| `r_t` | **tire radius**, 0.033 m | m | *not* the droop ratio | VESC doc §11 |
| `α` (`alpha`) | **current share** `I_FC/(I_FC+I_BT)`, the share-loop **output** | – | *never* mechanical/angular acceleration — that letter is not used for acceleration anywhere in this sub-project | `system_model.md` §3 |
| `K` | **share-plant DC gain** `∂α/∂r` at the OP | – | *not* a controller gain, *not* motor KV | §4.1 |
| `K_v` | **drive-channel structural gain uncertainty** multiplier | – | *not* motor KV (that is `KV_DESIGN`) | §4.2 |
| `K_enc` | encoder speed-chain gain, nominal 1 | – | | VESC doc §7 |
| `k_t` | **motor torque constant** | N·m/A | *not* `motorConstant` in firmware (which is a lumped PI-output→amps gain, VESC doc §11) | §4.2 |
| `k_d` | **droop scale**, 0.30 Ω (firmware `K_DROOP`) | Ω | | `system_model.md` §4 |
| `T` | **complementary sensitivity** | – | *not* torque (torque is `τ`), *not* sample period (`Ts`) | – |
| `S` | **sensitivity** | – | *not* Laplace `s`, *not* slip | – |
| `b` | qualified always: `b_eff` (wheel-referred damping, N·s/m), `b_motor` (shaft-referred, N·m·s/rad) | – | bare `b` is never used | §4.2 |
| `φ` (`phi`) | **overall drive ratio 9.49:1** (motor→wheel) | – | *not* flux linkage (that is `λ` and appears only in quoted VESC text) | VESC doc §3 |
| `ΔV0` (`dV0`) | **no-load source-voltage mismatch** FC vs BT, ±0.4 V budget | V | | `system_model.md` §3 |
| `I_tot` | total bus current out of the two sources | A | | – |
| `η_dt`, `η_v` | driveline / inverter efficiency | – | | §4.2 |

Small-signal deviations carry a leading `Δ` (code: `d…`). All plants below are
**strictly proper** (D = 0) and expressed about an operating point.

---

## 2. Operating point and signals

An operating point is the 4-tuple

```
OP = (I_tot0, r0, ΔV0, v0)
```

with the nominal design point (`plant_mimo.nominal_op()`):

| | value | why |
|---|---|---|
| `I_tot0` | 2.0 A | mid-range bus draw |
| `r0` | 0.50 | balanced share |
| `ΔV0` | **+0.2 V** | **half** the ±0.4 V budget: ΔV0 is *sign-uncertain* (§4.4). Synthesizing at 0 would show the controller no coupling at all; synthesizing at ±0.4 would over-commit to one sign. |
| `v0` | 2.0 m/s | cruise |

Inputs / outputs:

```
u = [ Δr        droop ratio command      ]      y = [ Δα   measured current share ]
    [ Δi_cmd    motor current command, A ]          [ Δv   measured wheel speed, m/s ]
```

Actuator limits (from firmware): `r ∈ [0.15, 0.85]`, `|i_cmd| ≤ 20 A`
(`MOTOR_I_CMD_MAX` / `I_CLAMP`, raised from 5 A on **2026-08-04** — see §2.1). Native
rates: share loop 1 kHz, motor loop 500 Hz (UART frame floor ≈ 781 µs).

### 2.1 The motor-current clamp is a MOTOR-side limit, not a bus-side one

`i_cmd` is the current commanded to the **VESC/motor** node, downstream of
`MOT_PWR_ENABLE`. The power-share plant, by contrast, lives on the **VBUS** node: what
`G12` actually sees is the bus current `ΔI_bus = A_i·Δi_m + A_ω·Δω` (§5), with
`A_i = 0.2429 A/A` at the cruise operating point. The two nodes are related by the boost
conversion ratio, so the clamp does **not** transfer one-for-one:

| | motor node | ⇒ bus node at cruise (`×A_i`) | ⇒ bus power at `V_bus0 = 15.9 V` |
|---|---|---|---|
| old clamp | ±5 A | ±1.21 A | ±19.3 W |
| **current clamp** | **±20 A** | **±4.86 A** | **±77 W** |

The ±20 A figure was chosen so the motor-side clamp and the converter pair's **≈67–87 W
bus budget** bind *together*: 4.86 A of bus current at 15.9 V is ≈ 77 W, i.e. squarely
inside that band. Below the old ±5 A the motor clamp bound ~4× earlier than the power
electronics did, which made every large-signal sim actuator-limited for reasons that had
nothing to do with the hardware's real limit.

**What is still NOT modelled:** the bus-power limit itself is not a separate constraint in
the plant or in either controller — there is no explicit `P_bus ≤ P_max` term anywhere. The
±20 A motor clamp is now *approximately equivalent* to it **by construction at the cruise
operating point**, which is the only sense in which the budget is enforced. Away from
cruise (`A_i` varies with `ω0` and `i_m0`) the equivalence degrades, and a genuine
bus-power constraint would still have to be added if that regime matters. Recorded here so
the approximation is not mistaken for a modelled limit.

Two consequences that show up downstream:

* **`Du(2,2)` scales with the clamp** (§8), so raising the clamp 4× silently weakened the
  H∞ control-effort penalty `Wu` by 4×. The synthesis weights had to be re-tuned to
  compensate — see `mimo_synthesis.md` it.5.
* **The saturation-error threshold moves 4×**: the decentralized drive controller's
  non-integral branch saturates above `e_sat = I_MOT_MAX/367.7` = **54.4 mm/s** (was
  13.6 mm/s), and the achievable acceleration limit becomes
  `a_max = k_t·φ/r_t·η/m_eff · I_MOT_MAX` = **9.04 m/s²** (1.3338 N/A × 20 A / 2.95 kg).

---

## 3. Block structure

```
        ┌                     ┐
G(s) =  │  G11(s)    G12(s)   │        8 states nominal
        │    0       G22(s)   │        (7 when τ_f = 0)
        └                     ┘
```

State ordering (`plant_mimo.design_plant`):

```
x = [ x_share(3)  : Padé₂(Td) ∘ 1/(τ_r s + 1)          ]
    [ x_drive(3)  : Padé₂(Td_v) ∘ 1/(τ_v s + 1)         ]
    [ x_mech(1)   : 1/(m_eff s + b_eff)                 ]
    [ x_filt(1)   : 1/(τ_f s + 1)   — SHARED, see §4.5   ]
```

The assembly is **explicit block state-space**, not a `parallel`/`blkdiag` composition,
precisely so that the single measurement prefilter `1/(τ_f s + 1)` is shared between the
direct share path and the coupling path. Duplicating it would add a spurious state *and*
misrepresent the hardware: there is exactly one prefilter, in firmware, downstream of the
share estimate.

---

## 4. The four blocks

### 4.1 G11 — share channel (4 states)

Identical in form to the shipped SISO design plant
(`controller_design/synthesize_controller.py:60-65` @ `51b8962`):

```
G11(s) = K · Padé₂(e^{−Td s}) · 1/(τ_r s + 1) · 1/(τ_f s + 1)
```

with **K evaluated at the operating point** rather than swept as a free corner scalar:

```
α(r, I_tot) = r + ΔV0 · r(1−r) / (k_d · I_tot)        (exact static share law)
K = ∂α/∂r  = 1 + ΔV0 (1 − 2 r0) / (k_d · I_tot0)
```

Both expressions are verified against the exact two-Thévenin circuit solution in
`controller_design/validate_model.py` @ `51b8962` (checks 1 and 2, to 1e-12 / 1e-4).
Gate **G1.1** confirms `G11 ≡` the shipped SISO plant to 8.0e-16 relative over all OPs and
five parameter corners.

**Contribution of this document:** the SISO envelope `K ∈ [0.55, 1.45]` is now derived,
not asserted — it is exactly the image of the expression above over the operating box.
See §7.3 for where the box *escapes* that envelope.

### 4.2 G22 — drive channel (4 states)

```
Δi_cmd → Padé₂(e^{−Td_v s}) → 1/(τ_v s + 1) → Δi_m
       → k_t·η_dt·φ/r_t  [N/A]  → 1/(m_eff s + b_eff) → Δv_phys → K_enc·K_v → Δv
```

DC gain (gate **G1.2**, exact to 2.4e-16 over all OPs × 24 drive corners):

```
G22(0) = K_enc · K_v · k_t · η_dt · φ / (r_t · b_eff)   = 3.7085 (m/s)/A  nominal
drive pole = −b_eff/m_eff = −0.1219 rad/s               (near-integrator, as expected)
```

The papers' powertrain form `G_P = (φ/(m·r_t))/(s + b φ²/(m r_t²))` is recovered exactly
when `b_eff` is written shaft-referred; here it is written wheel-referred instead, which is
the same system with the reflection folded into `b_motor·(φ/r_t)²`.

**`b_eff` — what is and is not in it.**

```
b_eff = ρ·C_dA·v0            aero, = d/dv of ½ρ C_dA v²  (linearization about v0)
      + b_motor·(φ/r_t)²     motor spinning loss, shaft → wheel referred
```

* At the nominal OP: aero 0.0245 + motor-spin **0.3352** = **0.3597 N·s/m**. The motor's
  own spinning loss **dominates the small-signal damping by 14×**, which is the direct
  small-signal consequence of the VESC doc §12.3 finding that free-run loss (not aero, not
  rolling resistance) sets the cruise draw. `b_motor = P_freerun/ω_freerun²` = 4.053e-6
  N·m·s/rad from the ≤2.5 A @ 16 V ≈ 40 W target at ~30 krpm.
* **`C_rr` is Coulomb**, magnitude `C_rr·m·g` with a `sign(v)` shape. It contributes to the
  **operating-point torque** (and therefore to `i_m0`, which sets the coupling gains in
  §4.3) but its derivative w.r.t. `v` is zero away from `v = 0`, so it **must not** appear
  in `b_eff`. This is commented at the definition in `plant_mimo.b_eff()`.
* `pole_factor ∈ {0.5, 2}` is the corner knob on `b_eff` (it moves the drive pole and the
  DC gain together, as a real damping error would).

**`K_v ∈ {0.5, 1, 2}` is structural, not a tolerance.** VESC doc §7: the encoder sits
downstream of the 9.49:1 reduction *and* the limited-slip differentials, so there is **no
fixed rotor↔ground-speed mapping**; `k_t` is uncalibrated (no motor selected); and
`motorConstant` in firmware is explicitly *not* a `k_t`. The entire `Δi_cmd → Δv` DC gain is
therefore uncertain by ~2× either way, and `K_v` carries that.

### 4.3 G21 = 0 — and why that is a modelling *result*, not an assumption

`Δr` reaches no state that feeds the speed output, in **both** the design plant and the
full-order truth model. Gate **G1.4** measures the scaled ratio `‖G21‖/‖G22‖` on the truth
model and gets **exactly 0**.

An exactly-zero gate result is only meaningful if the reason is stated, so:

* The VESC runs a **current loop**. At fixed `i_cmd` the delivered motor torque is
  independent of `v_bus` until the duty rail is reached.
* Gate G1.4 also reports the physical residual that this discards: `|Δv_bus/Δr|(DC)` =
  **0.2002 V per unit r**, i.e. **0.44 % of the 15.9 V bus** over the full ±0.35 r span.
  That is nowhere near a duty-saturation condition at any point in the operating envelope.
* **Where it would break:** deep battery discharge plus a large `i_cmd` (bus sag toward the
  boost's own regulation limit), or a regen event that pushes the bus into OVP. Both are
  outside the linear design envelope and are handled by the sequencing/fault layer in
  firmware, not by this controller. Recorded as a limitation, not modelled.

### 4.4 G12 — drive→share coupling (the whole point of the study)

Two stages.

**(a) Bus-current draw.** Linearizing motor input power `P = (k_t ω i_m + R_m i_m²)/η_v`
about the OP, at fixed `V_bus0`:

```
ΔI_bus = A_i · Δi_m + A_ω · Δω
A_i = (k_t ω0 + 2 R_m i_m0)/(η_v V_bus0)     = 0.24292  A/A          nominal
A_ω = (k_t i_m0)/(η_v V_bus0)                = 3.9272e-4 A/(rad/s)   nominal
ω0  = v0 · φ / r_t = 575.2 rad/s
i_m0 = (b_eff v0 + C_rr m g) r_t/(k_t η_dt φ) = 0.9731 A
```

The `Δω` term is what makes the coupling **dynamic** rather than a static feedthrough — it
routes through the vehicle mode, so the coupling inherits the near-integrator pole.
*Caveat:* `ω0 = v0 φ/r_t` is the **design-case** rotor↔ground mapping, which §4.2 has
already established does not hold rigidly; `K_v` stands in for it.

**(b) Share sensitivity.** Differentiating the static share law w.r.t. total current:

```
∂α/∂I_tot = − ΔV0 · r0 (1 − r0) / (k_d · I_tot0²)
```

so `G12(s) = (∂α/∂I_tot)·[A_i·W_v(s) + A_ω·(φ/r_t)·M(s)W_v(s)] · 1/(τ_f s + 1)` where
`W_v` is the VESC path and `M` the vehicle mode. Nominal:

```
∂α/∂I_tot = −4.1667e-2 share/A          G12(0) = −2.7573e-2 share per A of i_cmd
```

**Gate G1.3** checks `G12(0) / (dI_bus/di_cmd)|_DC` against a finite difference of the
static α map — 5.3e-10 relative over the OP grid × share × drive corners.

**Gate G1.3b** is the stronger one: the **full-order truth model reproduces this coupling
endogenously**, to **0.032 %**, with no coupling term written into it (see §6).

**Sign uncertainty — the central limitation of the whole study.** `∂α/∂I_tot` is

* **exactly zero at ΔV0 = 0** (matched sources: the coupling vanishes), and
* **sign-flipping over the ±0.4 V budget**, which is an *uncalibrated* quantity
  (`system_model.md` §9).

A MIMO controller synthesized at one ΔV0 sign implements a coupling **feedforward of the
wrong sign** at the mirror corner. Both ± corners are therefore mandatory in every
evaluation, and either outcome is a reportable result rather than a failure.

### 4.5 The shared measurement prefilter

`1/(τ_f s + 1)`, τ_f = 0.8 ms (200 Hz), is the firmware share-measurement prefilter —
implemented, not proposed. It sits downstream of the share estimate, so **both** G11 and
G12 pass through the *same* filter instance. `τ_f = 0` is a corner (the filter can be
disabled), which drops the plant to 7 states.

---

## 5. Interaction analysis — and why RGA is the wrong tool here

**Headline finding, stated up front (to be confirmed or refuted by Phase 5):**
*decentralized control is justified for stability; MIMO buys a coupling feedforward whose
value is bounded by the ΔV0 sign uncertainty.*

The design plant is **upper-triangular**, so its RGA is the identity — and gate **RGA**
confirms `max|RGA(0) − I| = 0.00e+00` at every corner, including ΔV0 = ±0.4.

**This is a property of triangularity, not of weak coupling.** `RGA(T) = I` for *any*
triangular `T`, no matter how large the off-diagonal entry. **RGA is blind to one-way
coupling and must not be used as the coupling metric in this sub-project.** (This is a
correction to the plan's implied use of RGA departure as the coupling measure; the plan's
own prediction "RGA = I nominal" is confirmed, but it is confirmed *structurally*, so it
carries no information about coupling strength.)

The informative metrics, computed on the **scaled** plant `Gs = De⁻¹ G Du` (§8), are:

**These are SCALED numbers, so they moved 4× with the clamp** (§2.1): `Gs12` carries
`Du(2,2)`, which went 5 → 20 A on 2026-08-04, while `Gs11` carries the unchanged
`Du(1,1) = 0.35`. The ratio below is therefore 4× its ±5 A value — the *physical* coupling
is identical; what changed is the units the synthesis sees it in. Values from
`comparison_metrics.txt` (keys given):

| Metric | Value | ±5 A value | key |
|---|---|---|---|
| `max_ω |Gs12|/|Gs11|`, nominal (2 A, r0 = 0.5, ΔV0 = +0.2) | **1.571** | 0.393 | `coupling.nominal.max_G12_over_G11` |
| `max_ω |Gs12|/|Gs11|`, light load (0.5 A) | **25.14** | 6.284 | `coupling.light_load_0p5A.max_G12_over_G11` |
| `max_ω |Gs12|/|Gs11|`, FC cruise (2 A, r0 = 0.85) | **1.045** | 0.261 | `coupling.fc_cruise_r0p85.max_G12_over_G11` |
| worst over the feasible OP × ΔV0 grid | **25.14** at (0.5 A, r0 = 0.5, ΔV0 = +0.2) | 6.284 | `coupling.grid.max_G12_over_G11` |
| `cond(Gs)` in-band, worst over the grid | **8.83e3** at (0.5 A, r0 = 0.3, ΔV0 = +0.4) | 2.81e3 | `coupling.grid.max_cond_Gs_inband` |
| `cond(Gs(0))` at the design point | **21.31** | 5.31 | `coupling.nominal.cond_Gs_at_dc` |

At the light-load corner the *scaled* coupling channel is now **25× stronger than the
direct share channel** — i.e. a full-authority motor transient can move the share far
further than a full-authority droop command can. That, not RGA, is the number that
motivates the MIMO design. Even at the nominal 2 A OP the ratio now exceeds 1 (1.571),
which it did not at ±5 A (0.393): **raising the clamp moved the nominal design point from
"coupling is a secondary effect" into "coupling has more authority over the share than the
droop actuator does"**, which is exactly why the synthesis weights had to be re-derived.

---

## 6. Full-order truth model (`full_model_mimo.py`)

`controller_design/tps61288_full_model.py` @ `51b8962` is copied **verbatim** (parameter
block, `zcomp_ss`, and the 11-state assembly) and preserved as `full_plant()`. Gate **G1.0**
re-imports the original module and confirms the copy reproduces it to **0.0e+00** relative
error. Three extensions:

**(1) `dv0` operating-point knob.** The original model is *structurally matched* — both
channels share `VREF` and the same divider network — so its no-load mismatch is ΔV0 = 0 and
its `∂α/∂I_tot` is identically zero. ΔV0 enters the small-signal model **only** through the
realized current split: the droop conductances stay set by the commanded `r0`, while the
actual split becomes `α0 = r0 + ΔV0 r0(1−r0)/(k_d I_tot)`. Setting `I_F0/I_B0` from `α0`
instead of `r0` is the entire change.

That change makes the coupling **emerge from the circuit**, and the algebra is worth
recording because it is the derivation that validates §4.4(b):

```
δα = (I_B0 δi_F − I_F0 δi_B)/I_tot²,   δi_F = −δv_bus/R_eF,  δi_B = −δv_bus/R_eB
R_eF = k_d/r,  R_eB = k_d/(1−r),  I_F0 = α0 I_tot
  ⇒ δα = −δv_bus (r − α0)/(k_d I_tot),     r − α0 = −ΔV0 r(1−r)/(k_d I_tot)
δv_bus = −δI_load·(R_eF ∥ R_eB) = −δI_load·k_d
  ⇒ δα/δI_load = −ΔV0 r(1−r)/(k_d I_tot²)     ✓ identical to §4.4(b)
```

Note the two cancellations that make this work: at ΔV0 = 0 the OP split *equals* the droop
split and the coupling is exactly zero; and `k_d` cancels once, leaving a single power.

**(2) `δI_load` input column + `v̂_bus` output row** (`full_plant_ext`): `B[v_bus, 1] =
−1/Cbus`, and a second output row picking the `v_bus` state.

> **Deviation from the plan spec (justified).** The plan also asked for an explicit
> "`∂α̂/∂I_tot` sensitivity term added to the `α̂` output row". That term is **not** added,
> because it would **double count**: the `α̂` row `(I_B0 i_F − I_F0 i_B)/I_tot²` is already
> the exact linearization of `i_F/(i_F+i_B)`, and a load step moves both channel currents
> through their droop load lines, so the full sensitivity is already present (as the algebra
> above shows). The analytic term is used as a **gate** instead (G1.3b): the truth model's
> DC `∂α̂/∂I_load` must *equal* the design plant's analytic `∂α/∂I_tot`. That is strictly
> stronger than importing the number — it validates the design plant's coupling row against
> the circuit rather than assuming it.

**(3) Drive branch grafted** (`full_plant_mimo`): the VESC path + vehicle mode are appended
as 4 states, their linearized `ΔI_bus` (imported from `plant_mimo`, not re-derived, so the
two models cannot drift) drives the `δI_load` column, and the speed becomes output 2.
Result: **15 states, 2 in / 2 out** (optionally 3 out with `v̂_bus`).

Like `full_order_validation.md`, the truth model carries **no `τ_f`** — that filter is
digital and common to both models — so comparisons use `design_plant(..., tauf=0)`.

**Gate G1.3b results.** Splitting the truth model's DC coupling into its odd- and
even-in-ΔV0 parts:

* **odd part** (the mismatch coupling): matches `−ΔV0 r0(1−r0)/(k_d I_tot²)` to
  **0.032 %** worst case over I_tot ∈ {0.5, 2, 5} A × r0 ∈ {0.3, 0.5, 0.7} × ΔV0 ∈ {0.2, 0.4}
  × Cbus ∈ {30 µF, 500 µF}.
* **even part** (a ΔV0-independent offset, ≤ **2.4e-3 share/A**): *not* a modelling error.
  The truth model's two channels are not structurally identical (`VinF = 9 V` vs
  `VinB = 8 V` give different `(1−D)`, `K_COMP(1−D)` and `ω_RHPZ`) and the error amplifiers
  have finite DC gain (`REA = 10 MΩ`), so a load step splits marginally unevenly even with
  matched references. Gated absolutely.

**Gate G1.5 — design plant vs truth model** (methodology mirrors
`full_order_validation.md` §2: max relative deviation per channel over the design band):

| Channel | Nominal, ω ≤ 200 rad/s |
|---|---|
| G11 share | **0.93 %** |
| G12 coupling | **0.71 %** |
| G22 drive | 0.00 % (shared construction by design) |

Envelope over the OP grid × ΔV0 ∈ {−0.4, 0, +0.4} × Cbus ∈ {30 µF, 500 µF}: worst
**7.71 %**, on G12 at (5 A, r0 = 0.3, ΔV0 = +0.4, Cbus = 500 µF). Gate 15 %.

---

## 7. Operating envelope, feasibility, and corner families

### 7.1 Corner families

| Family | Size | Members |
|---|---|---|
| `op_grid()` | **10** | `(I_tot0, r0)` ∈ {0.5, 2, 5} A × {0.3, 0.5, 0.7} ∪ **{(2 A, 0.85)}** |
| `share_corners()` | **24** | ΔV0 ∈ {−0.4, 0, +0.4} V × Td ∈ {0.5, 2} ms × τ_r ∈ {20, 300} µs × τ_f ∈ {0, 0.8} ms |
| `drive_corners()` | **24** | K_v ∈ {0.5, 1, 2} × pole_factor ∈ {0.5, 2} × τ_v ∈ {0.5, 5} ms × Td_v ∈ {1, 4} ms |

`(2 A, r0 = 0.85)` is the **FC-charge-cruise** operating point: the EMS drives the share to
the `r` clamp so the fuel cell carries the bus and the battery charges. τ_r ∈ {20, 300} µs
absorbs the `MOT_PWR_ENABLE` bus-capacitance change (30–80 µF → 500–1000 µF).

**ΔV0 lives in the share-corner family, not the OP**, because it is an *uncertainty* axis
rather than an operating choice. When a corner is combined with an OP, the corner's ΔV0
**overrides** the OP's (`plant_mimo.corner_plant`).

**Tier 1** (stability, eigenvalues) is the full cross product: 10 × 24 × 24 = **5760**.
Gate **G1.6**: **4992/4992 feasible corners** well-posed and open-loop stable (worst
`Re(p) = −6.10e-2`), **768 skipped as clamped** (§7.2), runtime **0.6 s** (0.11 ms/corner).

### 7.2 Operating-point feasibility (refinement of the plan's corner spec)

The RT1987 ideal-diode switches are **unidirectional**: a source cannot sink. If the static
share law puts `α0 = r0 + ΔV0 r0(1−r0)/(k_d I_tot0)` outside (0, 1), the weaker source is
**blocked**, the plant is at a *clamped* operating point, and the linearization — along with
`K` and `∂α/∂I_tot` — is meaningless there.

The plan's full cross product contains such points. At `I_tot0 = 0.5 A` the mismatch term
reaches **±0.56 share**, so e.g. `(0.5 A, r0 = 0.5, ΔV0 = ±0.4)` gives `α0 = 1.17` / `−0.17`.
`plant_mimo.op_feasible()` (margin 0.02) rejects these; **4 of 30 (OP, ΔV0) pairs**, i.e.
**768 of 5760** Tier-1 corners, are skipped, and the count is reported rather than silently
linearized. The full-order model raises a `ValueError` on the same condition.

### 7.3 Finding: the OP box escapes the shipped SISO K envelope

`controller_design/validate_model.py` @ `51b8962` states the shipped claim precisely:
*"K ∈ [0.75, 1.25] holds for r ∈ [0.3, 0.7] at I_tot ≥ 2 A; widen to [0.55, 1.45] at range
edges / light load."* Gate **G1.1** gates exactly that domain and passes:

| Domain | K envelope |
|---|---|
| Shipped domain: `I_tot ≥ 2 A`, `r ∈ [0.3, 0.7]` | **[0.733, 1.267]** ✓ inside [0.55, 1.45] |
| Full feasible OP set | **[0.533, 2.067]** |

Outside the shipped domain the OP-implied K **leaves** [0.55, 1.45]:

* **FC-charge cruise** `(2 A, r0 = 0.85)`: K ∈ [0.533, 1.467] — marginally outside both ends.
* **Light load** `(0.5 A, r0 = 0.3, ΔV0 = +0.4)`: **K = 2.067**, 43 % above the envelope.

**Consequence.** The shipped SISO controller was never gated at these points. In this
sub-project they are carried as **stability-only** corners (Tier 1), not performance
corners, and the FC-cruise waiver already contemplated in the plan (§8 phase table) applies.
This is a genuine gap in the shipped design's validated envelope and should be recorded as
such — it is not introduced by the MIMO work.

---

## 8. Scaling

Synthesis runs on `Gs = De⁻¹ · G · Du` (`plant_mimo.scaled_plant`, via `ss_lmul`/`ss_rmul`):

```
De = diag(0.05, 0.5)     max acceptable [share error (–), speed error (m/s)]
Du = diag(0.35, 20.0)    [half the r span (0.85−0.15)/2, motor current clamp (A)]
```

Nominal `G(0) = [[1, −0.02757], [0, 3.7085]]` → `Gs(0) = [[7.0, −11.029], [0, 148.34]]`,
`cond(Gs(0)) = 21.31`.

**`Du(2,2)` tracks the motor-current clamp** (§2.1), so the 2026-08-04 recalibration moved
it 5.0 → 20.0. This is not cosmetic: `Wu` penalizes the *scaled* input, so the same weight
suddenly permitted 4× more physical current. Re-running the unchanged weight set gave a
*better* γ (1.08) but 61 unstable Tier-1 corners — the synthesis spent the whole 4× on
aggression. The effort penalty had to be restored by moving `Wu`'s break frequency; the
sweep and the choice are recorded in `mimo_synthesis.md` it.5.

These are the current values; retuning during Phase 4 is recorded in `mimo_synthesis.md`.

---

## 9. TODO(calibrate) inventory

Every uncalibrated quantity, the corner axis that covers it, and where it is defined.

### 9.1 Inherited from the SISO share model

| Item | Nominal | Corner axis | Source |
|---|---|---|---|
| `ΔV0` no-load mismatch | ±0.4 V budget | `share_corners` ΔV0 ∈ {−0.4, 0, +0.4} | `system_model.md` §9 |
| `Td` loop delay | 1 ms | `share_corners` Td ∈ {0.5, 2} ms | bench step test |
| `τ_r` droop/bus pole | 100 µs | `share_corners` τ_r ∈ {20, 300} µs (incl. MOT_PWR cap change) | bench step test |
| `k_d` droop scale | 0.30 Ω | fixed (firmware constant, hard bound 0.3329) | `system_model.md` §4 |
| `K` share gain | OP-derived | **now derived** from ΔV0/r0/I_tot0 (§4.1) | this doc |
| `τ_f` prefilter | 0.8 ms | `share_corners` τ_f ∈ {0, 0.8} ms | firmware (implemented) |
| `VREF` = 0.6 V | – | TODO(verify: TPS61288 DS §7.5) | – |

### 9.2 New — drive channel

| Item | Placeholder used | Basis / status | Corner axis |
|---|---|---|---|
| **`k_t`** motor torque constant | **5.457e-3 N·m/A** (= 9.5493/1750) | **BLOCKING.** No motor selected/fitted. VESC doc §12.4 specifies KV 1600–1750; design case KV = 1750. Firmware `motorConstant` is *not* a `k_t`. | `K_v ∈ {0.5, 1, 2}` |
| **`K_enc`** encoder chain | 1.0 | **Structural**, not a tolerance: no fixed rotor↔ground mapping (VESC doc §7) | `K_v` |
| `J_rotor` → `M_ROT` | 0.45 kg apparent | VESC doc §12.3, "Rotor J is [measure]" | `pole_factor`, `K_v` |
| `M_BUILT` built mass | 2.50 kg | VESC doc §12.3: estimate, range 2.5–3.2 kg; nothing in repo records it | `pole_factor` (via DC gain), `K_v` |
| `b_eff` damping | 0.3597 N·s/m | derived (§4.2); `b_motor` from the ≤2.5 A/16 V free-run target, itself "[measure]" | `pole_factor ∈ {0.5, 2}` |
| `C_rr` | 0.020 | user decision 1; affects `i_m0` → coupling gains only | via `K_v` on the coupling |
| `C_dA` | 0.010 m² | user decision 1; only 6.8 % of `b_eff` | `pole_factor` |
| `η_dt` | 0.85 | user decision 1 | `K_v` |
| `η_v` inverter | 0.85 | TODO(calibrate) | `K_v` (coupling magnitude) |
| **`τ_v`** VESC current-loop lag | 1 ms | TODO(identify) — FOC closed-loop lag not measured | `τ_v ∈ {0.5, 5} ms` |
| **`Td_v`** command transport | 2 ms | TODO(identify) — UART frame floor ≈ 781 µs + ZOH | `Td_v ∈ {1, 4} ms` |
| **`R_m`** phase resistance | **0.075 Ω** | placeholder from the 3650 spec-can dyno point "110 W / 35 A / 0.075 Ω" (VESC doc §12.4). Enters only through `2 R_m i_m0` = 0.146 V of the 3.22 V `A_i` numerator (**4.5 %**), so it is a *low-sensitivity* placeholder. | `K_v` |
| `V_bus0` under load | 15.907 V | derived from the as-built divider; no load-line measurement | – (bounded by boost regulation) |
| `r_t` tire radius | 0.033 m | **[measure]** — caliper the mounted tire (VESC doc §11) | `K_v` |
| `φ` drive ratio | 9.49 | corroborated by two sources; internal reduction still `[measure]` | – |

### 9.3 Sensitivity note

Not all placeholders matter equally. `R_m` moves `A_i` by 4.5 %; `C_dA` moves `b_eff` by
6.8 %; `k_t`, `K_enc`, `r_t`, `φ` and the mass all enter the drive DC gain **multiplicatively**
and are jointly carried by the single `K_v ∈ {0.5, 2}` axis — which is why that axis is a
factor of 2 rather than a percentage. The one quantity with *no* magnitude bound that
matters more than its size is **ΔV0**, because it controls the coupling's **sign** (§4.4).

---

## 10. Bench identification priorities

In dependency order (mirrors `controller_design/bench_calibration_manual.md` conventions):

1. **`r_t` and the encoder chain** — cheap, blocking for everything downstream (VESC doc §11).
2. **`k_t`** — requires motor selection; blocking for the drive channel's absolute gain.
3. **`ΔV0`** — measure the two no-load bus setpoints directly. This is the **highest-value**
   measurement in the sub-project: it collapses the coupling sign uncertainty that bounds
   the entire MIMO advantage (§4.4).
4. **`τ_v`, `Td_v`** — VESC current-step response over UART.
5. **`τ_r`, `Td`** — the existing SISO share step test (`system_model.md` §9), unchanged.
6. **Free-run current at 16 V** — sets `b_motor`, which is 93 % of `b_eff`.

---

## 11. Change log

| Date | Change |
|---|---|
| 2026-08-04 | Phase 1: created. 2×2 design plant, 15-state truth model, 12-gate battery, all passing. Deviations from the plan spec recorded in §5 (RGA is blind to triangular coupling), §6 (no explicit `∂α̂/∂I_tot` term — it would double count; used as a gate instead), and §7.2 (OP feasibility filter added). Finding recorded in §7.3 (OP box escapes the shipped K envelope). |
