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

> **Drive calibration round — 2026-08-16.** The drive channel is now MEASURED (§4.2, §9.2;
> source `calibration/motor_id_20260815.md`), and the firmware clamp moved **20 A → 12 A**.
> Scope of this round, stated precisely so nothing is assumed: §4.2, §4.4, §9.2, §9.3, §10
> and the SISO drive synthesis (`synthesize_drive_siso.py`, which enforces the 12 A clamp
> directly) are updated. **§2, §2.1, §5 and §8 are NOT.** Those sections describe the
> *scaled* MIMO plant `Gs = De⁻¹ G Du`, and `Du(2,2)` is deliberately left at 20.0 because
> it is the scaling the checked-in MIMO synthesis artifacts were built with; changing it
> here without regenerating them would make the document describe a plant no artifact
> implements. Consequence: the actuator limit stated in §2 (`|i_cmd| ≤ 20 A`), every SCALED
> number in §2.1, §5 and §8, and every unscaled drive figure quoted inside them
> (`A_i` = 0.2429, `G22(0)` = 3.7085, `e_sat` = 54.4 mm/s, `a_max` = 9.04 m/s²), are
> **stale**. The unscaled truth is in §4.2 and §4.4.
>
> **§2.1's conclusion is REVERSED, not merely re-numbered.** That section argues the motor
> clamp and the ≈67–87 W converter budget "bind together" at ±20 A. At the firmware's 12 A
> and the measured `A_i` = 0.0922 A/A, the clamp corresponds to **≈1.11 A ≈ 17.6 W** at the
> bus — roughly a quarter of the budget's lower edge. The **motor clamp is now the binding
> limit** and the bus-power budget is not approached; the coincidence §2.1 was built on no
> longer exists. Any downstream argument resting on it must be re-derived.
>
> **Velocity-estimator round — 2026-08-16b.** The drive channel changed **again**, in two
> ways that this document's §4.2 now carries: a **velocity-estimator delay** `Td_est(v0)`
> was added to `G22` (it was never modelled, and its omission is the root cause of the
> ML0136–ML0139 closed-loop limit cycle), and the **drive gain was re-centred on
> measurement** via `K_v` (nominal 1.0 → 1.25, corners {0.5, 1, 2} → {0.85, 1.25, 1.85}).
> Scope: §4.2, §9.2, §9.3, §10, this banner and the change log, plus the SISO drive
> synthesis (`synthesize_drive_siso.py`, re-run; new weight rung WC = 60, Wu(0.25, 300,
> 12.5)). **§2, §2.1, §5 and §8 remain NOT updated**, for the same reason as the previous
> round.
>
> **K_F force-axis correction — 2026-08-16c.** The drive channel's FORCE conversion was
> wrong on two counts and is corrected here: the gear ratio `φ` **9.49 → 6.86** (the 9.49
> was a stock-gearing web figure; the fitted pinion is 29T — Traxxas 4-Tec manual p.24
> formula with the counted 70T/29T gives 6.88, and the operator's rolling counts give
> 2.84–2.86 for the shaft/tire stage), and the force **radius** `0.0762 m → 0.033 m`. The
> rig is motor → gearbox → **tire** → roller → **flywheel**: torque acts through the gearbox
> on the *tire*, while the encoder and the inertia belong to the *flywheel*, so the two
> radii are different quantities and this model had been conflating them. Net
> `K_F` **0.4516 → 0.7538 N/A, ×1.669**. The drag law rescales with it (`b_eff` 0.32 →
> **0.534** N·s/m, `F_c` 1.2 → **2.00** N) because it was derived *from* hold currents
> *through* `K_F`, so `i_m0` = 4.07 A is invariant. The old ×2 ramp-vs-cruise gain
> contradiction **dissolves**, and `m_eff` = 3.5 kg is **vindicated** — the 1.6–2.4 kg
> inferences were `F/a` fits made through the understated force axis. `K_v` re-centred
> 1.25 → **1.00**, corners → **{0.75, 1.00, 1.35}**. Scope: §4.2, §4.4, §9.2, §9.3, the
> symbol table, this banner and the change log, plus the SISO drive synthesis (re-run; the
> shipped weight rung is UNCHANGED and passes every gate). **§2, §2.1, §5 and §8 remain NOT
> updated**, for the same reason as the previous rounds.
>
> **The MIMO staleness DEEPENS.** The frozen MIMO artifacts were already built on a
> retired plant; they are now stale on a *structural* count as well, not merely on
> parameter values — `design_plant` has grown from 8 states to 10, and `G22` from 4 to 6,
> because the estimator delay is a new element in the loop. **The 2026-08-16c force-axis
> correction adds a third count:** every absolute force, and therefore `K_F`, the drag law
> and `ω₀`, moved after those artifacts were frozen. Regenerating them is a new synthesis
> round, and one that must re-derive anything resting on the old state count or the old
> force axis.
>
> **Consequence to know about before running the Phase-1 battery: `validate_mimo_model.py`
> G1.5/G1.6 now FAIL on the drive channel** (`G22` in-band deviation 58.9 % vs a 15 %
> gate; `G11` 0.93 % and `G12` 0.71 % are unaffected). This is expected and is not a
> regression in the design plant: the 15-state truth model in `full_model_mimo.py` carries
> neither the estimator delay nor the re-centred `K_v`, so the two models are now
> describing different drive channels. Grafting both changes into `full_model_mimo.py` is
> part of the deferred MIMO regeneration round; until then the *drive* half of the
> validation battery is stale, and the SISO drive design is gate-checked by
> `synthesize_drive_siso.py` / `validate_drive_siso.py` instead.
>
> **The Phase-1 "all 12 gates pass" status line below therefore describes the previous
> state of this sub-project, not the current one.**
>
> The MIMO artifacts are frozen on the retired plant and their regeneration is a new
> synthesis round, not a re-run — per-stage failure detail is in the `README.md` banner.

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
| `r_t` | **TIRE rolling radius**, 0.033 m — the FORCE/`ω` conversion radius | m | *not* the droop ratio. Corrected 2026-08-16c: the encoder/inertia radius is `r_fly` = 0.0762 m (below); torque acts on the tire, not on the flywheel (§4.2) | 2026-08-16c |
| `r_fly` | **flywheel rolling radius**, 0.0762 m — the ENCODER/INERTIA radius | m | sets the slot pitch and `J/r²`; `v` throughout this model is flywheel surface speed | measured 2026-08-13 |
| `α` (`alpha`) | **current share** `I_FC/(I_FC+I_BT)`, the share-loop **output** | – | *never* mechanical/angular acceleration — that letter is not used for acceleration anywhere in this sub-project | `system_model.md` §3 |
| `K` | **share-plant DC gain** `∂α/∂r` at the OP | – | *not* a controller gain, *not* motor KV | §4.1 |
| `K_v` | **drive-channel structural gain uncertainty** multiplier | – | *not* motor KV (that is `KV_DESIGN`) | §4.2 |
| `K_enc` | encoder speed-chain gain, nominal 1 | – | | VESC doc §7 |
| `k_t` | **motor torque constant** | N·m/A | *not* `motorConstant` in firmware (which is a lumped PI-output→amps gain, VESC doc §11) | §4.2 |
| `k_d` | **droop scale**, 0.30 Ω (firmware `K_DROOP`) | Ω | | `system_model.md` §4 |
| `T` | **complementary sensitivity** | – | *not* torque (torque is `τ`), *not* sample period (`Ts`) | – |
| `S` | **sensitivity** | – | *not* Laplace `s`, *not* slip | – |
| `b` | qualified always: `b_eff` (wheel-referred damping, N·s/m), `b_motor` (shaft-referred, N·m·s/rad) | – | bare `b` is never used | §4.2 |
| `φ` (`phi`) | **motor→tire reduction 6.86:1**, as fitted | – | *not* flux linkage (that is `λ` and appears only in quoted VESC text). Corrected 2026-08-16c: 9.49 was the stock-gearing figure for a different pinion | Traxxas 4-Tec manual p.24 + counted 70T/29T |
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
  *(Stale: §2 was not updated in the 2026-08-16/16b/16c rounds. At the shipped
  `K_F` = 0.7538 N/A, clamp 12 A and `m_eff` = 3.5 kg the figure is 2.58 m/s².)*

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

### 4.2 G22 — drive channel (6 states)

```
Δi_cmd → Padé₂(e^{−Td_v s}) → 1/(τ_v s + 1) → Δi_m
       → k_t·η_dt·φ/r_t  [N/A]  → 1/(m_eff s + b_eff) → Δv_phys
       → Padé₂(e^{−Td_est(v0) s})  [velocity estimator]  → K_enc·K_v → Δv
```

`Δv_phys` is the **true** flywheel surface speed and `Δv` is what the **firmware measures**.
The two are no longer the same signal. Only `Δv` is fed back; the drive→share coupling of
§4.4 taps `Δv_phys`, because the motor's bus-current draw responds to the real shaft speed
and not to what the estimator has got round to reporting.

**Status: CALIBRATED (2026-08-16), estimator element ADDED (2026-08-16b).** Every constant in this block is now measured. The
authoritative record is `calibration/motor_id_20260815.md`; the values below are its
image in `plant_mimo.py`. The pre-calibration placeholder chain (KV 1750, 66 mm tire
radius, mass split, aero + rolling + free-run drag composite) is retired.

| Constant | Calibrated value | Source |
|---|---|---|
| `k_t` | 4.266e-3 N·m/A | `(3/2)·p·λ`, p = 2, λ = 1.422 mWb (VESC FOC detection, Castle 1406 1900KV) |
| `R_m` | 0.0226 Ω | VESC FOC detection |
| `m_eff` | 3.5 kg | J = 0.0203 kg·m² at `r_fly`; J/r_fly² = 3.50 kg |
| `φ` | 6.86 | motor→tire reduction as fitted (manual p.24 + counted 70T/29T), 2026-08-16c |
| `r_t` | 0.033 m | **tire** radius — FORCE and `ω` conversion, 2026-08-16c |
| `r_fly` | 0.0762 m | **flywheel** radius — encoder pitch and inertia, measured 2026-08-13 |
| `b_eff` | 0.534 N·s/m ±15 % | TP0125–TP0134 ladder + ML0135 small-signal steps, re-expressed in the corrected force axis |
| `F_c` | 2.00 ± 0.42 N | same, thermal spread (2.19 cold / 1.75–1.84 warm) |
| `τ_v` | 1.0 ms | VESC sampled current step; matches KP/L = KI/R = 1004 rad/s |
| `Td_v` | 2.0 ms | **decided**, not measured — analytic bound 0.9–2 ms |

**Two radii, two roles — corrected 2026-08-16c.** The rig chain is
motor → gear reduction `φ` → **tire** (`r_t`) → roller contact → **flywheel** (`r_fly`), and
tire surface speed = flywheel surface speed = `v`. Motor torque reaches the road through
the gearbox and the *tire*, so the force constant and the motor-speed mapping both use
`r_t` = 0.033 m. The encoder disc *is* the flywheel and the measured inertia is the
flywheel's, so the slot pitch and `J/r²` both use `r_fly` = 0.0762 m. `v` throughout this
model remains **flywheel surface speed** — the same quantity the firmware's `v_actual`
reports (coupling resolved 2026-08-16 as surface/roller), and the vehicle differentials do
not enter the velocity loop. The pre-2026-08-16c model used `φ` = 9.49 and `r` = 0.0762 m
for *both* roles and understated every absolute force by **×1.669**.

DC gain (gate **G1.2**, exact to 2.4e-16 over all OPs × 24 drive corners):

```
G22(0) = K_enc · K_v · k_t · η_dt · φ / (r_t · b_eff)   = 1.4116 (m/s)/A  nominal
K_F    = k_t · η_dt · φ / r_t                          = 0.7538 N/A
drive pole = −b_eff/m_eff = −0.1526 rad/s               (near-integrator, as expected)
```

Against the pre-calibration figures (3.7085 (m/s)/A, −0.1219 rad/s) the DC gain fell
**×0.38** and the pole moved **away from the origin (faster) by ×1.25**.
`K_F` and `b_eff` both carry the 2026-08-16c force-axis correction (×1.669), so their
ratio — and hence `G22(0)` — is nearly unmoved by it; what the correction changes is the
*pole*, through `b_eff/m_eff`, and every absolute force in §4.4. The drive controller synthesis is downstream of this and was re-run
(`synthesize_drive_siso.py`, §11).

The papers' powertrain form `G_P = (φ/(m·r_t))/(s + b φ²/(m r_t²))` is recovered when
`b_eff` is written shaft-referred; here it is written flywheel-referred instead.

**`b_eff` — what is and is not in it.**

```
b_eff = b_eff_nom · pole_factor            b_eff_nom = 0.534 N·s/m, MEASURED
```

* `b_eff` is a **measured local slope**, `dF/dv` at `v0 = 2.0 m/s`, not a sum of modelled
  loss terms. Two independent measurements agree: the TP0125–TP0134 steady-state ladder
  (ten holds, 3.5–5.5 A) and the ML0135 small-signal staircase (five incremental steps
  over 1.9–3.4 m/s). The ±15 % band is set by the 8 % disagreement
  between the two 4.0 A repeats, not by formal fit errors. **The raw data are hold
  CURRENTS**; only their conversion to force changed at 2026-08-16c, which is why the
  slope rescaled ×1.669 while the measurements themselves stand.
* **The measured drag curve is Coulomb-dominated and concave** (`F = 1.31 + 0.435·v`, or
  equivalently `F = 1.751·v^0.30`); **pure viscous is excluded at χ² ×1400**. The previous
  model's aero + motor-free-run composite was therefore the wrong *shape*, not merely the
  wrong magnitude — and it predicted the cruise current a factor of 4 low (§4.4).
* **`b_eff` carries no `v0` term.** A local slope is identified only at the speed it was
  measured at. The known amplitude dependence — the slope roughly **doubles below
  ~1.5 m/s** — is carried by the corner axis instead, which is why `pole_factor` was
  **widened {0.5, 2} → {0.5, 3}**. A consequence worth stating: `v0` no longer enters `G22`
  at all, so any sweep over `v0` in a drive-channel study is now degenerate.
* **`F_c` (Coulomb, 2.00 N) is deliberately absent from `b_eff`.** It is `sign(v)`-shaped, so
  it sets the operating-point torque (and therefore `i_m0`, which sets the coupling gains in
  §4.4) but its derivative w.r.t. `v` is zero away from `v = 0`. This is commented at the
  definition in `plant_mimo.b_eff()`.
* **`F_c` is thermally variable**, 1.31 N cold against 1.05–1.1 N warm at identical
  firmware and commanded current. The spread is carried as `1.2 ± 0.25 N` rather than a
  point value, and it propagates into the coupling gain, not into the plant dynamics.

**`K_v ∈ {0.5, 1, 2}` is retained, but its rationale has shrunk.** The axis was sized as
*structural*: no fixed rotor↔ground mapping, an uncalibrated `k_t`, and an uncalibrated
encoder chain. Two of those three are now closed — `k_t` is measured, and the encoder chain
is calibrated end to end (240 counts/rev, hardware-confirmed 2026-08-16; `r_t` = 0.0762 m;
surface/roller coupling resolved). What remains inside the axis is the `η_dt` = 0.85
placeholder and the thermal spread of the drag law, which together do not justify a factor
of 2. The axis is kept at its old width as the conservative default: narrowing it is a
performance lever, not a correctness fix, and at the achieved drive bandwidth it costs
nothing (the binding gates are phase margin and worst-corner ‖S‖ at `pole_factor` = 0.5,
`K_v` = 2 — see `drive_siso_metrics.txt`). Narrowing to {0.7, 1.0, 1.4} is the documented
next step if bandwidth is ever wanted.


**The velocity estimator — added 2026-08-16b, and why it was missing.**

The firmware's velocity estimate was modelled as an ideal measurement. It is not one, and
the first closed-loop `'V'` runs said so unambiguously: ML0136–ML0139 (fw v11) **limit
cycled at 2.3–2.6 Hz = 14.5–16.3 rad/s at every step size** (0.1, 0.5, 1.0 m/s). That band
is the drive design's crossover. The shipped estimator was a **≈113 ms boxcar** — ≈56 ms of
group delay, **52–58° of phase at 16 rad/s, against a 49.6° design phase margin** — with a
measured command→speed lag of 63–73 ms and 0.0177 m/s quantization. The loop was closed
around a lag the synthesis plant did not contain, so the margin the design reported was
never the margin the hardware had. A limit cycle at exactly the design crossover is the
signature of that specific error, not of a gain error and not of anti-windup: anti-windup
(Hanus) was independently confirmed working in those same runs (`u_unsat` hugged the rail
with ≤ 0.4 A typical excess, clean releases, ≈150 saturation episodes).

The **replacement** estimator (firmware round, parallel to this one) is an **edge-period**
estimator, and this is the contract it is modelled against:

* the period is measured same-edge-type over one full **slot pitch**,
  `pitch = 2π·r_t/120 = 3.9898 mm` of flywheel surface travel;
* **`N` = 2 periods are averaged** (configurable in firmware);
* the estimate is **latched once per pitch** (zero-order hold in between);
* below ≈0.03 m/s the estimator times out and reports 0.

Its dynamics are an averaging window of `N` pitches plus a one-pitch hold, so:

```
Td_est(v) = N·pitch/(2v)        mean-value delay of the N-pitch averaging window
          + pitch/(2v)          mean staleness of the once-per-pitch latch
          = (N + 1)·pitch/(2v)
```

| `v0` [m/s] | `Td_est` [ms] | phase at 16 rad/s |
|---|---|---|
| 0.5 (validity floor) | 11.97 | 11.0° |
| 2.0 (design point) | 2.99 | 2.7° |
| 5.0 | 1.20 | 1.1° |
| *(retired boxcar)* | *≈56* | *51°* |

It is modelled as a **pure transport delay** (Padé(2)), not as the exact boxcar: the
difference between the two lies above `1/Td_est`, far above any achievable crossover.

**`Td_est` is velocity-dependent, and that is a corner axis, not a footnote.** It is
carried by sweeping `v0` over `TD_EST_V0_SET = {0.5, 2, 5}` m/s, which takes the drive
corner family from 24 plants to **72**. Note what this does to the previous round's
bookkeeping: that round *dropped* the `v0` sweep as exactly degenerate, because the
calibrated `b_eff` is a local slope with no `v0` term. `v0` now re-enters `G22` in exactly
one place — the estimator — so the axis is reinstated, but as an **estimator-delay axis**,
not a drag axis. The drag-slope speed dependence stays on `pole_factor`.

**Validity floor: `v0 ≥ 0.5 m/s`** (`plant_mimo.V0_VALID_MIN`). `Td_est` grows without
bound as `v → 0` — 19.9 ms at 0.3 m/s, 59.8 ms at 0.1 m/s — and **this design is not
gate-checked below 0.5 m/s**. Closing the velocity loop below the floor requires either a
wider delay corner, paid for in bandwidth, or a gain schedule on `v`. This is a limitation
of the design, not a property of the vehicle.

**The measured gain datapoint — `K_v` re-centred, 2026-08-16b, RECOMPUTED 2026-08-16c.**

The drive gain has been measured end to end, twice. In the retired force axis the two
measurements disagreed by a factor of ≈2 (×1.78 ramps against ×0.91 cruise hold, both
against a modelled 0.4516 N/A). Recomputed against the corrected `K_F` = 0.7538 N/A and
the corrected drag law:

| Evidence | Implied `K_F` | vs modelled 0.7538 N/A |
|---|---|---|
| ML0139, +12 A ramp, startup-excluded: 0.186 (m/s²)/A net, drag added back at `v` ≈ 0.40 m/s | 0.836 N/A | **×1.109** |
| ML0137, +12 A ramp, startup-excluded: 0.204 (m/s²)/A net, drag added back at `v` ≈ 0.75 m/s | 0.914 N/A | **×1.213** |
| 4.5 ± 0.4 A cruise hold at `v0` = 2.0 m/s (drag `F` = 2.003 + 0.534·2 = 3.071 N) | 0.682 N/A | **×0.905** (band ×0.83–×0.99) |

**The factor-of-2 contradiction dissolves in the corrected axis, and it does so for a
stated reason.** The cruise-implied gain is `F(v0)/i_m0` and `F` is itself the drag law,
which was derived *from* hold currents *through* `K_F` — so the cruise ratio is invariant
under a rescaling of the force axis. The ramp-implied gain is `m_eff·a/I` plus the same
drag term, and its dominant part carries no `K_F` at all — so the ramp ratio moves by the
full ×1/1.669. Correcting `K_F` therefore moves one and not the other, and the two land
×1.09–×1.34 apart instead of ×2.

**`m_eff` = 3.5 kg is vindicated by the same arithmetic.** The 1.6–2.4 kg inferences were
`F/a` fits that read `F = K_F·I`; an understated `K_F` reads back as an understated mass in
exactly the observed ratio, and ×1.669 on the force axis moves them onto ≈3.5 kg. The
operator's 2026-08-16 ruling (`m_eff` is a floor set by the measured `J`; suspect `K_F`) is
confirmed, and the "open bench item" it raised is **closed**.

The modelling decision, therefore:

* `η_dt` stays at **0.85** and stays a `TODO(calibrate)`. The ramp residual is now only
  ×1.11–×1.21 — no longer the unphysical `η_dt ≥ 1.0` — so it is consistent with an
  efficiency slightly above 0.85 or with nothing at all. Raising it would still move `i_m0`
  and the §4.4 coupling gains, which nothing measured this round touches.
* the residual is carried by **`K_v`**, whose nominal moves **1.25 → 1.00** (the geometric
  mean of ×0.905 and the ×1.161 ramp-band centre) and whose corners move
  **{0.85, 1.25, 1.85} → {0.75, 1.00, 1.35}**. The corners bracket both evidence *bands*
  with margin: 0.75 sits 10 % below the cruise band's low edge (0.831) and 1.35 sits 11 %
  above the ramp band's high edge (1.213).

```
G22(0) = 1.7641 → 1.4116 (m/s)/A          effective K_F·K_v = 0.5645 → 0.7538 N/A  (×1.34)
```

The `K_v` span narrows again, ×2.2 → ×1.8, bought with the correction rather than
asserted. The re-synthesized controller needed **no weight change**: the shipped rung
(WC = 60, Wu(0.25, 300, 12.5)) passes every gate on the corrected plant, at crossover
17.52 rad/s with PM 50.8°, delay margin 50.6 ms and worst-corner ‖S‖∞ 2.427. Full ladder
and gates in `drive_siso_metrics.txt`.

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
A_i = (k_t ω0 + 2 R_m i_m0)/(η_v V_bus0)     = 0.144785 A/A          nominal
A_ω = (k_t i_m0)/(η_v V_bus0)                = 1.2842e-3 A/(rad/s)    nominal
ω0  = v0 · φ / r_t = 415.8 rad/s            (r_t = TIRE radius, 2026-08-16c)
i_m0 = (b_eff v0 + F_c) r_t/(k_t η_dt φ)     = 4.070 A
```

**The operating-point current moved by a factor of 4.2, and that is the calibration's
largest single consequence for the coupling.** The old model gave `i_m0` = 0.973 A at
cruise; the bench holds measure **4.5 ± 0.4 A**; the calibrated model gives **4.07 A**.

The agreement should be stated at its actual strength, which is *order-of-magnitude
correction*, not *closure*: 4.07 A is ~9 % below the band's centre and **0.6 % below its
lower edge — just outside it, not inside**. Propagating the `F_c` thermal endpoints gives a
model envelope of 3.74 A (warm) to 4.32 A (cold), which straddles that lower edge rather
than covering the band. The residual is consistent with the `η_dt` = 0.85 placeholder,
which scales every absolute force and is the largest surviving drive unknown (§9.2). What
the calibration does settle is that the old figure was wrong by a **factor of four** — the
arithmetic consequence of a drag law with the wrong shape (§4.2) — and that the motor's bus
draw was correspondingly under-stated.

Both coupling gains move as a result, in opposite directions:

* `A_ω ∝ k_t·i_m0` rises **×3.27** (`i_m0` ×4.19 against `k_t` ×0.78), from 3.93e-4 to
  1.284e-3 A/(rad/s). `i_m0` is invariant under the 2026-08-16c force-axis correction, so
  `A_ω` is too. Referred to ground speed, however, `A_ω·φ/r_t` = **0.2670 A per m/s**
  (was 0.1601 in the retired frame): `φ/r_t` is the corrected 207.9 rad/s per (m/s), and
  that is where the correction shows up in the coupling.
* `A_i` **falls ×0.60**, from 0.2429 to 0.14479 A/A, because its dominant term `k_t·ω0`
  carries `k_t` ×0.78 against `ω0` ×0.72. The `2 R_m i_m0` term is 0.184 V of the 1.957 V
  numerator — **9.4 %**, up from 4.5 %, so `R_m` is no longer the low-sensitivity
  placeholder it was. It is, however, now measured, so the sensitivity is harmless.

Net: a given motor-current command draws **less** bus current than the old model claimed,
while a given speed excursion draws **more**. Any conclusion in the MIMO comparison that
rested on the ratio of the two terms must be re-derived rather than carried over.

The `Δω` term is what makes the coupling **dynamic** rather than a static feedthrough — it
routes through the vehicle mode, so the coupling inherits the near-integrator pole.
*Caveat, now weaker than it was:* `ω0 = v0 φ/r_t` is the surface-speed↔motor mapping through
the 6.86:1 reduction and the **tire** radius (§4.2, corrected 2026-08-16c). Since the
encoder measures the flywheel and the flywheel runs at tire surface speed, this mapping is
a rigid gear-plus-rolling ratio rather than the slip-dependent rotor↔ground mapping the
earlier text warned about. One residual assumption remains: **no slip at the tire/roller
contact.** `K_v` still stands in for the residual (`η_dt`, thermal spread).

**(b) Share sensitivity.** Differentiating the static share law w.r.t. total current:

```
∂α/∂I_tot = − ΔV0 · r0 (1 − r0) / (k_d · I_tot0²)
```

so `G12(s) = (∂α/∂I_tot)·[A_i·W_v(s) + A_ω·(φ/r_t)·M(s)W_v(s)] · 1/(τ_f s + 1)` where
`W_v` is the VESC path and `M` the vehicle mode. Nominal:

```
∂α/∂I_tot = −4.1667e-2 share/A          G12(0) = −1.3256e-2 share per A of i_cmd
```

`∂α/∂I_tot` is unchanged (it depends only on share-channel quantities, which this
calibration did not touch). `G12(0)` **halves**, from −2.7573e-2 to −1.3256e-2 share per A
of `i_cmd`, because the `A_i` fall outweighs the `A_ω` rise at DC. The coupling is
therefore *weaker* than the pre-calibration model claimed — which, since the MIMO
advantage is bounded by the coupling magnitude, is a result the comparison must inherit
rather than an inconvenience to be absorbed.

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

> **Stale as of 2026-08-16** (see the banner in §1). On the calibrated plant the unscaled
> nominal is `G(0) = [[1, −0.01326], [0, 1.4112]]`. This block is left as-published because
> it documents the scaling the checked-in MIMO artifacts were synthesized with; it is
> re-derived when those artifacts are regenerated.

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

### 9.2 Drive channel — CALIBRATED 2026-08-16, estimator added 2026-08-16b

The drive channel was the placeholder-heavy half of this model. It is now measured. Rows
marked **MEASURED** cite `calibration/motor_id_20260815.md`, which is the source of truth;
the remaining rows are the residual placeholder set.

| Item | Value | Basis / status | Corner axis |
|---|---|---|---|
| **`k_t`** motor torque constant | **4.266e-3 N·m/A** | **MEASURED.** `(3/2)·p·λ` with p = 2, λ = 1.422 mWb from VESC FOC detection (Castle 1406 1900KV). Pole-pair count cross-checked against KV to 2.0 %. Replaces the 5.457e-3 KV-1750 placeholder. | `K_v` |
| **`R_m`** phase resistance | **0.0226 Ω** | **MEASURED** (VESC FOC detection). Replaces the 0.075 Ω spec-can placeholder. Now enters `A_i` at **14.8 %** (was 4.5 %) because `i_m0` rose ×4.2 — a higher sensitivity, but no longer a placeholder. | – |
| **`m_eff`** equivalent inertia | **3.5 kg** | **MEASURED and CONFIRMED** (2026-08-16c; the 2026-08-16b challenge is **withdrawn**). J = 0.0203 kg·m² at the flywheel; J/r_fly² = 3.50 kg. The 1.6–2.4 kg inferences were `F/a` fits reading `F = K_F·I` through the understated force axis; the ×1.669 `K_F` correction moves every one of them onto ≈3.5 kg. | `pole_factor` |
| **`r_t`** force/`ω` radius | **0.033 m** | **CORRECTED 2026-08-16c.** The TIRE radius: torque reaches the road through the gearbox and the tire, so `K_F` and `ω0` use it. The 0.0762 m flywheel figure had been used here in error (§4.2). | – |
| **`r_fly`** encoder/inertia radius | **0.0762 m** | **MEASURED** (3.00 in, 2026-08-13). Flywheel radius; the coupling was resolved 2026-08-16 as surface/roller, so `v` is flywheel surface speed and the slot pitch and `J/r²` use it (§4.2). | – |
| **`K_enc`** encoder chain | 1.0 | **CLOSED.** 240 counts/rev (120 slots × ×2 decode, counted and hardware-confirmed 2026-08-16) with `r_fly` above fixes the chain end to end. No longer structurally uncertain. The 2026-08-16c force-axis correction does **not** touch the velocity chain. | – |
| **`b_eff`** damping | **0.534 N·s/m ±15 %** | **MEASURED** twice, independently: TP0125–TP0134 steady-state ladder and ML0135 small-signal steps agree to 6 %. Local slope at `v0` = 2.0 m/s. Re-expressed ×1.669 at 2026-08-16c: the raw data are hold CURRENTS and are unchanged; only their force conversion moved. | `pole_factor ∈ {0.5, 3}` |
| **`F_c`** Coulomb drag | **1.2 ± 0.25 N** | **MEASURED**, thermally variable (1.31 N cold / 1.05–1.1 N warm). Sets `i_m0`, hence the coupling gains; contributes nothing to `b_eff`. Replaces the `C_rr·m·g` slot. | spread carried into §4.4 |
| **`τ_v`** VESC current-loop lag | **1.0 ms** | **MEASURED** 2026-08-16 (VESC Tool sampled current step, 63 % at ≈1–1.5 ms); independently implied by the detection gains, KP/L = KI/R = 1004 rad/s. | `τ_v ∈ {0.5, 5} ms` |
| **`Td_v`** command transport | 2.0 ms | **DECIDED, not measured** (operator, 2026-08-15). Analytic bound 0.9–2 ms (UART frame 781 µs + packet thread ≲1 ms + FOC pickup ≤70 µs), comfortably inside the corner axis; direct measurement was declined to keep a current instrument out of the motor power path. | `Td_v ∈ {1, 4} ms` |
| **`Td_est`** velocity-estimator delay | **(N+1)·pitch/(2·v0)** = 2.99 ms at `v0` = 2 m/s | **CONTRACT** (2026-08-16b), from the replacement edge-period estimator: `pitch` = 3.9898 mm (2π·r_t/120, `r_t` measured, 120 slots counted), `N` = 2 averaged periods, latched once per pitch. Not a fitted quantity — it is derived from the firmware design. What *is* uncertain is `N` (configurable) and the ≈0.03 m/s timeout. | `v0 ∈ {0.5, 2, 5}` m/s → `Td_est ∈ {11.97, 2.99, 1.20}` ms |
| **`K_v`** drive-gain residual | **1.00** (was 1.25) | **RE-CENTRED AGAIN** (2026-08-16c) on the same two measurements, recomputed in the corrected force axis: ramps ×1.109–×1.213, cruise hold ×0.905. The two no longer contradict, so the axis need not straddle a factor of 2. | `{0.75, 1.00, 1.35}` (span ×2.2 → ×1.8) |
| `η_dt` driveline efficiency | 0.85 | **TODO(calibrate)** — the largest surviving drive placeholder. All absolute forces scale with it, so it is what keeps `K_v` alive. | `K_v` |
| `η_v` inverter efficiency | 0.85 | **TODO(calibrate)** | `K_v` (coupling magnitude) |
| `V_bus0` under load | 15.907 V | derived from the as-built divider; no load-line measurement | – (bounded by boost regulation) |
| `φ` drive ratio | **6.86** | **CORRECTED 2026-08-16c.** Triple-confirmed: Traxxas 4-Tec manual p.24 formula (spur/pinion)×2.85 with the counted 70T/29T gives 6.88; the manual's chart cell (29, 70) reads 2.41 pre-transmission; operator rolling counts give 2.84–2.86 for the shaft/tire stage. The retired 9.49 was the STOCK-gearing web figure for a different pinion. The operator's flywheel-vs-motor spin count of ≈32 is ×2.02 the chain-predicted `φ·r_fly/r_t` = 15.8 because VESC Tool's RPM display reads ×2 the true mechanical speed — a display artifact only; `k_t` is unaffected (`λ` vs KV cross-check, 1.451 vs 1.422 mWb at p = 2). | – |
| `C_rr`, `C_dA`, `b_motor`, `P_freerun` | — | **RETIRED.** The aero + rolling + free-run composite is replaced by the measured lumped law. The measured curve is Coulomb-dominated and concave; pure viscous is excluded at χ² ×1400, so the composite had the wrong shape (§4.2). | – |

### 9.3 Sensitivity note

Not all placeholders matter equally, and the ranking changed with the calibration. The two
surviving drive placeholders are the **efficiencies**: `η_dt` scales the force constant and
therefore the whole `Δi_cmd → Δv` DC gain, and `η_v` scales the coupling magnitude. They
are what the `K_v` axis now carries, having previously carried `k_t`, `r_t`, the mass and
the encoder chain as well — all of which are now measured. That is why §4.2 records the
axis as over-wide rather than as sized-to-evidence.

**The ranking changed again on 2026-08-16b, and the top item is new.** The largest
uncertainty in the drive channel is no longer an efficiency: it is the **factor-of-2
disagreement between the ramp-gain and cruise-hold measurements** (§4.2), which is now
carried by `K_v`'s width. Unlike `η_dt`, it cannot be closed by measuring the item itself —
both gain measurements have been *made*; what is missing is the constant that reconciles
them, and `m_eff` is the leading candidate. A single timestamped coast-down from a high
plateau discriminates it, and that is the highest-value drive measurement outstanding.

**`Td_est` is a new sensitivity of a different kind: it is exactly known but strongly
speed-dependent.** Nothing about it needs measuring — it follows from the firmware contract
and the counted slot pitch — but its 10× variation across the operating range now sets the
worst corner of the drive design (0.5 m/s), where the previous round's worst corner was a
parameter extreme. Lowering `N` from 2 to 1 would cut it by a third; that is a firmware
lever on plant phase, and it is available if bandwidth is ever wanted.

`R_m` moved the *other* way: it is measured now, but its influence on `A_i` tripled to
14.8 % because `i_m0` rose ×4.2. Had it stayed a placeholder, this calibration would have
promoted it from a low-sensitivity item to a significant one.

The one quantity with *no* magnitude bound that matters more than its size is still
**ΔV0**, because it controls the coupling's **sign** (§4.4). It is a share-channel
quantity and is untouched by this round.

---

## 10. Bench identification priorities

In dependency order (mirrors `controller_design/bench_calibration_manual.md` conventions).
Items 1, 2, 4 and 6 of the original list are **DONE** as of 2026-08-16 and are struck
below rather than deleted, so the record shows what the drive-channel calibration closed.

1. **`ΔV0`** — measure the two no-load bus setpoints directly. Now the **highest-value
   remaining** measurement in the sub-project: it collapses the coupling sign uncertainty
   that bounds the entire MIMO advantage (§4.4), and it is the last quantity in the model
   whose *sign* is unknown. A partial result exists on the bench supply (+0.05 V at
   r = 0.5, `controller_design/system_model.md` §8); the **vehicle-source** measurement is
   still open.
2. **The ramp-vs-cruise gain disagreement — `m_eff` vs `η_dt`.** PROMOTED 2026-08-16b, and
   it now outranks `η_dt` alone. Two end-to-end gain measurements disagree by ×2 (§4.2)
   and `K_v`'s width is what absorbs it. The discriminating experiment is the one already
   in the calibration record's open list: **one timestamped coast-down from a ≥5 A
   plateau** (manual `K` log or a timestamped terminal capture — never the Serial Plotter
   axis). It separates `m_eff` from `η_dt` through the ×1.4–1.5 residual between observed
   and ladder-predicted deceleration, and `m_eff` ≈ 1.6–2.0 kg is what would reconcile all
   three observations at once. Closing it would let `K_v` narrow further and is the
   highest-value *drive* measurement outstanding.
3. **`τ_r`, `Td`** — the existing SISO share step test (`system_model.md` §9), unchanged.
4. **`η_v`** — inverter efficiency; affects the coupling magnitude only.
5. **`N` (estimator averaging depth) — a design lever, not a measurement.** `Td_est`
   scales as `(N+1)`, so `N` = 1 would cut the estimator's phase by a third at every
   speed, at the cost of estimate noise. It is worth a bench comparison only if drive
   bandwidth is ever wanted: at `N` = 2 the estimator costs 2.7° at the design point and
   is not what limits the loop.
6. **Cold-start repeat of one ML0135 step pair** — bounds the thermal `F_c` spread from
   below, tightening the `i_m0` band that sets the §4.4 coupling gains.

*Newly OPEN as of 2026-08-16b:* the estimator's low-speed behaviour below the
`v0` = 0.5 m/s validity floor. The design is not gate-checked there and the firmware
estimator times out below ≈0.03 m/s; a bench sweep of small `'V'` setpoints (0.2–0.5 m/s)
would establish whether the floor needs a gain schedule or merely a documented restriction.

*Closed by the 2026-08-16 drive calibration:* ~~`r_t` and the encoder chain~~ (measured and
hardware-confirmed); ~~`k_t`~~ (motor fitted, flux linkage measured); ~~`τ_v`, `Td_v`~~
(`τ_v` measured, `Td_v` decided against an analytic bound); ~~free-run current at 16 V~~
(superseded — `b_eff` is measured directly, and the free-run decomposition it would have
fed is retired).

---

## 11. Change log

| Date | Change |
|---|---|
| 2026-08-16c | **`K_F` force-axis correction; `m_eff` challenge withdrawn.** The force chain carried the wrong gear ratio *and* the wrong radius. `φ` **9.49 → 6.86** (as-fitted 29T pinion; Traxxas 4-Tec manual p.24 + counted 70T/29T → 6.88, operator rolling counts 2.84–2.86 for the shaft/tire stage; the 9.49 was a stock-gearing web figure) and the FORCE radius **0.0762 → 0.033 m** (`r_t` is the TIRE; `r_fly` = 0.0762 m is the encoder/inertia radius and is unchanged). Consequences: `K_F` 0.4516 → **0.7538 N/A (×1.669)**; `b_eff` 0.32 → **0.534 N·s/m** and `F_c` 1.2 → **2.00 ± 0.42 N** (the drag law was derived FROM hold currents THROUGH `K_F`, so it rescales with it and `i_m0` = 4.07 A is **invariant**); drive pole −0.0914 → **−0.1526 rad/s**; `ω0` 249.1 → **415.8 rad/s**; `A_i` 0.09221 → **0.14479 A/A**, `A_ω` unchanged at 1.284e-3 A/(rad/s) but **0.1601 → 0.2670 A per m/s** referred to ground speed. The ×2 ramp-vs-cruise gain contradiction **dissolves** (ratios ×1.109–×1.213 vs ×0.905) because the cruise-implied gain scales with the drag law and the ramp-implied one does not; `K_v` re-centred **1.25 → 1.00**, corners **{0.85, 1.25, 1.85} → {0.75, 1.00, 1.35}** (span ×2.2 → ×1.8); `G22(0)` 1.7641 → **1.4116 (m/s)/A**, effective `K_F·K_v` 0.5645 → **0.7538 N/A (×1.34)**. **`m_eff` = 3.5 kg CONFIRMED** and the 2026-08-16b challenge withdrawn — the 1.6–2.4 kg inferences were `F/a` fits through the understated axis. `η_dt` stays 0.85 (the ramp residual is no longer the unphysical ≥1.0). Sections 4.2, 4.4, 9.2, 9.3, the symbol table and the banner updated. The SISO drive synthesis was re-run downstream with **no weight change**: the shipped rung (WC = 60, Wu(0.25, 300, 12.5)) passes every gate — crossover 17.52 rad/s, PM 50.8°, DM 50.6 ms, worst ‖S‖∞ 2.427 cont / 2.535 disc over 72 corners, PM 41.8° at the 0.5 m/s corner. Firmware effect is coefficient regeneration only (fw v14). MIMO artifacts now stale on a third count (force axis). Source: `calibration/motor_id_20260815.md` §"K_F force-axis correction". |
| 2026-08-16b | **Velocity-estimator delay modelled; drive gain re-centred on measurement.** (a) `G22` gains `Padé₂(e^{−Td_est(v0) s})` on the MEASURED speed output, `Td_est = (N+1)·pitch/(2 v0)` with `pitch` = 3.9898 mm and `N` = 2 → 2.99 ms at the design speed, 11.97 ms at the 0.5 m/s validity floor. The element was ABSENT before, and its absence is the root cause of the ML0136–ML0139 closed-loop limit cycle (2.3–2.6 Hz = the design crossover; the retired ≈113 ms boxcar ate 52–58° against a 49.6° margin). `design_plant` 8 → 10 states, `G22` 4 → 6. The coupling path deliberately taps the UNDELAYED speed. (b) `K_v` nominal 1.0 → **1.25**, corners {0.5, 1, 2} → **{0.85, 1.25, 1.85}**: the geometric mean of the ramp-implied (×1.78) and cruise-hold-implied (×0.91) gains, bracketing both — a nominal correction and a span narrowing (×4.0 → ×2.2) at once. `η_dt` deliberately left at 0.85 (the ramps imply ≥ 1.0, which is not an efficiency; `m_eff` ≈ 1.6–2.0 kg is the reconciling candidate and is an open bench item). `G22(0)` 1.4112 → **1.7641** (m/s)/A. (c) The `v0` corner axis is REINSTATED — degenerate last round, now the estimator-delay axis — taking the drive corner family 24 → **72**; validity floor `v0 ≥ 0.5 m/s` stated explicitly. Sections 4.2, 9.2, 9.3, 10 and the banner updated. The SISO drive synthesis was re-run downstream (new rung WC = 60, Wu(0.25, 300, 12.5); crossover 15.98 rad/s HELD with PM 51.9° vs 49.6°, worst ‖S‖ 2.418 over 72 corners; two bench-evidence gates added — estimator phase at crossover < 10°, and PM > 30° at the 0.5 m/s corner). MIMO artifacts now stale STRUCTURALLY as well as numerically. |
| 2026-08-16 | **Drive channel calibrated.** `k_t` 5.457e-3 → 4.266e-3 N·m/A (measured flux linkage), `R_m` 0.075 → 0.0226 Ω, `m_eff` 2.95 → 3.5 kg (`M_BUILT`/`M_ROT` split retired), `r_t` 0.033 → 0.0762 m (flywheel rolling radius; the encoder measures flywheel surface speed), `τ_v` measured at 1.0 ms, `Td_v` 2.0 ms decided against an analytic bound. The aero + `C_rr` + free-run drag composite is **retired** and replaced by a measured lumped law, `b_eff` = 0.32 N·s/m local slope at `v0` = 2.0 m/s plus `F_c` = 1.2 ± 0.25 N Coulomb; pure viscous is excluded at χ² ×1400. `pole_factor` corner widened {0.5, 2} → {0.5, 3} to cover the slope doubling below 1.5 m/s, which also absorbs the `v0` dependence `b_eff` no longer carries. Consequences: `G22(0)` 3.7085 → 1.4112 (m/s)/A, drive pole −0.1219 → −0.0914 rad/s, `i_m0` 0.973 → 4.074 A (measured 4.5 ± 0.4 A — the old figure was 4× low), `A_ω` ×3.27, `A_i` ×0.38, `G12(0)` −2.757e-2 → −1.326e-2. Sections 4.2, 4.4, 9.2, 9.3, 10 rewritten. `K_v ∈ {0.5, 1, 2}` retained but recorded as over-wide (only `η_dt`/`η_v` remain inside it). Source: `calibration/motor_id_20260815.md`. The SISO drive synthesis was re-run downstream (`synthesize_drive_siso.py`; new weight rung WC = 55, Wu(0.15, 300, 7.5), clamp 20 → 12 A); the MIMO synthesis artifacts are **not** regenerated by this round and are stale against these constants. |
| 2026-08-04 | Phase 1: created. 2×2 design plant, 15-state truth model, 12-gate battery, all passing. Deviations from the plan spec recorded in §5 (RGA is blind to triangular coupling), §6 (no explicit `∂α̂/∂I_tot` term — it would double count; used as a gate instead), and §7.2 (OP feasibility filter added). Finding recorded in §7.3 (OP box escapes the shipped K envelope). |
