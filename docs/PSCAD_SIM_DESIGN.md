# PSCAD simulation design — droop control circuit (board rev 20260622, fw v21)

> **Companion documents.** [`docs/HIL_PLANT.md`](HIL_PLANT.md) is the plant-side reference for
> the Python HIL engines (simple + `--electrical hifi`) and is the source of most electrical
> constants restated here. [`docs/HIL_MODE.md`](HIL_MODE.md) carries the HIL frame tables, the
> H1–H5 test plan and the link-loss staging. [`controller_design/system_model.md`](../controller_design/system_model.md)
> is the authority on the droop plant algebra, the share-loop design plant and the boost
> voltage-loop crossover derivation. [`docs/boost-bringup-debug.md`](boost-bringup-debug.md)
> is the bench-incident ledger (the Death series, the hot-loop bodges, TP0178/TP0201).
>
> **What this document is:** the design for two PSCAD/EMTDC projects that model the board's
> droop control circuit — a Tier-1 teaching/verification project and a Tier-2 component-level
> project intended to be compared against HIL and bench data.
>
> **What this document is NOT:** it is not a PSCAD tutorial, not a firmware reference, not a
> restatement of the control synthesis (that is `controller_design/`), and it does not
> introduce any new measurement. Every electrical constant below is traced to an existing
> repo artifact or marked `TODO(verify)` / `TODO(calibrate)`. Nothing here has been measured
> for the purpose of this document.
>
> **Status:** design only. No PSCAD workspace exists in the repo as of this writing, and there
> is no prior PSCAD/EMTDC art anywhere in the tree — a repo-wide search returns the branch
> name and nothing else (research brief 4 §5).

---

## 1. Purpose and position among the existing models

### 1.1 What already exists

The board is already modelled three times over, at three different levels of abstraction:

| Existing model | Level | Where | What it is good for |
|---|---|---|---|
| Design plant `G_P(s)` | 2-state + delay LTI | `controller_design/system_model.md` §6d | Share-loop synthesis and robustness gates |
| Full-order TPS61288 model | 11-state LTI, small-signal | `controller_design/tps61288_full_model.py` | Boost voltage-loop stability/margin claims |
| Python HIL electrical engines | Average, time-domain, real-time | `tools/hil_plant_sim.py` (simple), `tools/hil_electrical.py` (hi-fi) | Closing a live loop around the real firmware |

None of them is a circuit simulator. There is **no SPICE/LTspice/ngspice artifact anywhere in
the repo** — confirmed by a repo-wide search across `.py` / `.md` / `.ino` / `.m` and for
`.asc` / `.cir` / `.sp` files (research brief 1 §5). All frequency-domain analysis of the droop
injection network is done algebraically (FB-node superposition) or as a hand-built state space.

### 1.2 What PSCAD adds

Three things, in order of importance.

**(a) PSCAD is offline, so it can integrate what the real-time engine explicitly could not.**
The hi-fi Python engine's `Boost` class docstring records the decision and the reason
verbatim (`tools/hil_electrical.py:791–825`):

> *"The first implementation of this class was the literal datasheet structure... It is
> numerically UNUSABLE here. That voltage loop crosses at 4-19 kHz (system_model.md §6e)...
> and the substep rate a stdlib-Python host actually achieves on this network is ~20-40 kHz.
> Integrating a 19 kHz loop at 20-40 kHz puts the crossover essentially at Nyquist: the
> explicit compensator-to-node coupling went unstable within three substeps and tripped the
> 19 V OVP on every bring-up. **The limiter was the DISCRETIZATION, not the physics.**"*

The same document is equally explicit about the parasitic ring: the LC ring on the
boost output hot loops is **not integrated** in `hil_electrical.py` at all — it is an analytic
event estimate `V_peak ~= V_node + L*di/dt` at a fixed worst-case `di/dt = 1.3e9 A/s`, evaluated
at each switch opening and compared to `V_ABSMAX = 20.0 V` (research brief 2 §4). PSCAD/EMTDC
can simulate both of those instead of estimating them, because it does not have to keep up with
a 1 kHz wall clock. (§4.10 re-derives what the ring frequency actually is — the repo's
"nH–µF ≈ 100 MHz" shorthand does not survive arithmetic, and the correction changes the
required timestep by two orders of magnitude.)

**(b) A third, independently-built model triangulates.** The repo's own precedent for this is
`controller_design/full_order_validation.md`, where an independently-built 11-state model is
checked against the 2-state design plant through named gates (max envelope deviation 5.78 %,
median 4.30 % over 432 operating points). Where PSCAD, the Python engines and bench data agree,
confidence compounds. Where they disagree, that is a finding — and one such disagreement is
already on the table:

> **⚠ OPEN FINDING — realized droop is ~4x below design.** Measured
> `K_DROOP_BUS_SHARED = 0.074 +/- 0.004 V/A` (both sources live) and
> `K_DROOP_BUS_SINGLE = 0.1615 +/- 0.001 V/A` (exactly one source live), against a
> design-predicted 0.30 V/A from the MDAC droop chain (`R_e = RE_MAX * g = 2.014 * 0.298
> = 0.60 ohm` per channel, 0.30 ohm combined). `docs/HIL_PLANT.md` §4.2 states plainly:
> *"Nothing in the repo explains the gap yet."* It is listed in §11.2 there as *"the highest-value
> open electrical question in the document."* The two Python engines land on **opposite sides**
> of it — the simple engine uses the measured number, the hi-fi engine derives its droop from
> FB-node superposition and therefore reproduces the design number. **§5 of this document
> (experiment T2-X1) is the attempt to reproduce or kill the gap with a component-level
> circuit.** Do not launder either number into a settled fact.

**(c) EMT simulation is a stated learning goal.** Tier 1 exists to teach the PSCAD workflow.
It is a teaching vehicle first and a verification artifact second, and it is designed
accordingly (§3).

### 1.3 Order of trust

When two models disagree, the ranking used in this document is:

```
bench measurement  >  HIL replay of a bench log  >  HIL synthetic scenario  >  PSCAD  >  design intent
```

with **one exception**: for sub-microsecond phenomena (switching-node ringing, the parasitic
LC transient, switching ripple reaching the INA253 sense output) PSCAD outranks the Python
engines, because those engines do not model those phenomena at all — the hi-fi engine detects
a ring *event* analytically, it does not simulate the waveform (`docs/HIL_PLANT.md` §8.5,
§11.1). A PSCAD result in that band is not being checked against a better model; it is the
only model.

---

## 2. As-fitted hardware baseline

**Rule for this document and for both PSCAD projects: build from AS-FITTED values.** The
schematic `Scale_Car_DC_Balancer_Board_Schematic_20260622.pdf` and the BOM predate a series of
post-manufacturing bodges. Where the schematic and the board disagree, the schematic is stale
and the board wins. Every constants table below carries the as-designed value in the
provenance column when it differs, so a schematic reader can see the delta rather than
silently disagreeing with the model.

### 2.1 Condensed bodge ledger — electrically relevant rows

From research brief 5 (transcript sweep of `docs/claude-md-archive.md`,
`docs/boost-bringup-debug.md`, `docs/firmware-versions.md`, `USER_NOTES.md`, `CLAUDE.md`,
`bench_calibration_manual.md`, `controller_design/system_model.md`,
`docs/reviews/design-review-2026-07-28.md`, `rt1987-softstart-bodge-slides.pptx`). Rows with
no bearing on the electrical model (encoder pin move, encoder pull-ups, 90-slot wheel, motor
swap, the not-yet-fitted 74HC14 Schmitt) are omitted; they are in brief 5 in full.

> **Designator convention (used throughout this document).** The six RT1987 switches are named
> by their **BOM line 77 designators**: **D-FC, D-BT, D-MT, D-BRG, D-BFC, B-BSQ**. Other repo
> sources use per-net variants for the same parts — `D-FC-EN` = D-FC, `D-BT-EN` = D-BT,
> `D-MT-EN` = D-MT, `D-RG-EN` = D-BRG, `D-FC-CH` / `D-BC-FC` = D-BFC, `D-BT-SQ` = B-BSQ. This
> is the only place the aliases are given; everywhere else this document uses the BOM spelling.

| # | Item | As-designed | As-fitted (model this) | Date / source | Confidence |
|---|---|---|---|---|---|
| B1 | VBUS FB divider `R_D1`, **both** channels | 237 kΩ (schematic + BOM; an older mfg export says 243 kΩ — see OQ-1) | **215 kΩ** → design `V0 = 0.6*(1 + 215/10 + 215/53.6) = 15.91 V`; both boosts measured regulating 15.9 V no-load | Bodged 2026-07-11, reconfirmed by measurement 2026-07-31 (`boost-bringup-debug.md:229–330`; `system_model.md` §2) | CONFIRMED (DMM + scope, both channels) |
| B2 | `R_C` TPS61288 compensator, BT channel | 27.4 kΩ | **61.2 kΩ** (matches FC; symmetric lags are the assumption behind the shared `τ_r`) | 2026-07-10 (`CLAUDE.md` bodge record; `system_model.md` §6e) | CONFIRMED |
| B3 | RT1987 soft-start `C_SS`, 3 of 6 switches | 5.6 nF on **all six** (BOM line 80, C-DS qty 6) | **100 nF on D-BT, D-FC, D-MT**; D-BFC / D-BRG / B-BSQ **deliberately left at 5.6 nF** (operator decision 2026-08-07: charger-node caps too small to trip the 250 µs SCP blank) | D-BT 2026-08-03 (capture 8), D-MT 2026-08-07 (capture 11), D-FC date not recorded (OQ-6) | CONFIRMED (BT/MOT dated + single-variable validated; FC value confirmed, date uncertain) |
| B4 | Hot-loop bodge caps at boost `VOUT` pin | none beyond the 3×22 µF bank (240 mil away on BT, 40 mil on FC) | **10 µF + 0.1 µF ceramic directly at the IC output pin, BOTH channels** | BT fitted+validated 2026-07-07 (4 surviving bring-ups at Death-4 conditions); FC confirmed fitted by 2026-08-11 by operator correction, date not recorded (OQ-5) | CONFIRMED BT (dated, scope-validated); CONFIRMED-by-correction FC |
| B5 | OPA197 (MDAC output amp) supply rail | not stated anywhere in the swept corpus (OQ-3) | **5 V rail**; output ceiling ≈ 4.9 V — a hard constraint on droop-injection authority | `CLAUDE.md` §7; `system_model.md` §8; `HIL_PLANT.md` §8 | CONFIRMED as-fitted; as-designed NOT FOUND |
| B6 | Current sense part | INA253A3IPWR intended (0.4 V/A) | **INA253A1IPWR fitted, both channels — `K_sns = 0.1 V/A`** | Factory BOM substitution at original manufacture (`CLAUDE.md` §5; `.ino:1861–1865`) | CONFIRMED |
| B7 | RT1987 EN-to-GND resistors | none | **10 kΩ EN→GND** so every switch defaults low while the Teensy GPIO is high-Z during reset/boot | `CLAUDE.md` §2 — single mention, no date, per-switch scope not itemized (OQ-7) | CONFIRMED they exist; scope + date uncertain |
| B8 | Regen chopper clamp | no explicit trip-voltage spec found on the schematic | **18.1 V** trip, into a 47 Ω dump | Bench-calibrated 2026-08-27 (observed `V_rgn` 13.3 → 18.1 V held); retires the earlier 16.5 V placeholder. *The 20 W figure quoted in §4.8 is the resistor/device **rating** from the parts data, not part of this measurement* | **18.1 V** CONFIRMED as a **measurement**, not a hardware rework; 47 Ω / 20 W are datasheet-class values |
| B9 | Bench supplies, log batches 153–180 | n/a | Supplies **swapped** — stiffer on BT, looser on FC | `CLAUDE.md` 2026-08-17b; `boost-bringup-debug.md:1373–1377` | Swap CONFIRMED; **impedances never quantified** (OQ-8) |

### 2.2 Consequences for the PSCAD models

- The **as-fitted `R_D1 = 215 kΩ`** sets `V0`. A PSCAD model built from the schematic's 237 kΩ
  would produce `V0 = 0.6*(1 + 23.7 + 4.421) = 17.47 V` and be wrong by 1.6 V. This is the same
  *class* of stale-constant error that produced this repo's one false "bus 1.6 V below nominal"
  alarm (`CLAUDE.md` 2026-08-17) — the matching 1.6 V magnitude is a numeric coincidence, not
  the same event. Use 215 kΩ.
- **`R_C = 61.2 kΩ on both channels`** is what makes the shared `τ_r` assumption legitimate.
  A T2-FAST switching study that uses the schematic's 27.4 kΩ on BT will show a BT crossover
  around 6.2–7.0 kHz instead of 13.8–15.7 kHz (research brief 1 §4) and will not match the board.
- The **CSS split (100 nF on the three bus/motor switches, 5.6 nF on the three charger-path
  switches)** is not a schematic feature; it is exactly the split `hil_electrical.py` models.
  `hil_electrical.py`'s own citation of "schematic 20260622" for the 100 nF values is
  **imprecise** — the paper schematic still shows 5.6 nF everywhere (research brief 2 §1).
- **`K_sns = 0.1 V/A`** (not 0.4). The block-diagram PDF still labels the sense output
  "400 mV/A" (OQ-12, PDF stale). Note that the *measured bus droop slope* is provably
  **independent** of which INA253 variant is fitted and of the firmware's `K_sns` constant —
  the gain cancels between the droop path and the current-report path (§5.3, CLOSED). That
  cancellation removes sense-gain error from the ×4 candidate list entirely; it does not
  make the stale PDF label harmless for a reader building a model from it.

---

## 3. Tier 1 — simplified teaching / verification project

**Project name suggestion:** `droop_t1` in a workspace `dc_balancer.pswx`. One canvas.

**Goal.** Teach the PSCAD workflow end to end and verify the droop mechanism quantitatively
with idealized components. Everything continuous/averaged: no switching, no parasitic
inductance, no RT1987 timing.

### 3.1 Modeling decisions (fixed by the architecture plan)

| Element | Tier-1 model | What is deliberately ignored |
|---|---|---|
| Boost converters | Averaged controlled voltage source `V_out = V0 - K_droop_ch * I_out` behind a first-order lag `1/(1 + s*τ_r)` | Switching, RHPZ, compensator dynamics, OVP |
| Sources | Ideal DC source + series resistance (the stiffness knob), two presets: "stiff bench supply" and "loose bench supply" | Polarization curve, SOC, double-layer RC |
| Source→bus ORing | Master-library diode with the RT1987 **forward drop folded in**: `V_f = 35 mV + 21 mΩ * I` (see below) | RT1987 `t_D_ON`, soft-start, foldback, reverse comparator |
| Bus | One lumped capacitor | Per-node capacitance split, ESR/ESL |
| Load | Controlled current source: manual slider / timed step / simple drive-shaped profile | Motor mechanics, VESC behaviour |
| Droop chain | **One gain block** `I_sense -> RE_MAX * g -> setpoint shift`, `RE_MAX = K_sns*A_v*(R_D1/R_inj) = 2.014 Ω`, with a slider for `g` | INA253 bandwidth, MDAC quantization, OPA197 rail, injection network |
| Share control | Minimal **sampled PI** at the firmware share tick rate, trimming the two droop gains | The shipped Youla-H controller (deliberately — see below) |

> **⚠ The `R_D1/R_inj` factor is not optional, even in Tier 1.** Writing the droop block as
> `K_sns*A_v*g` — omitting the FB injection attenuation `R_D1/R_inj = 4.011` — reproduces the
> **retired `k_eq` firmware defect verbatim** (`.ino:78–83` changelog: the old
> `g = k_eq/(r*K_sns*A_v)` mapping "omitted the FB injection attenuation", pinning both MDACs
> at full scale with achieved share stuck at ≈0.5). A Tier-1 model written that way produces
> droop 4× too large. Use `RE_MAX * g` throughout.

**Why a PI and not the shipped controller.** Tier 1's purpose is to teach discrete-control
blocks in PSCAD (sample-and-hold, ZOH, a sampled loop closed around a continuous plant). The
shipped share controller is 3 DF2T biquads plus a separate exact integrator with generated
coefficients; putting it in Tier 1 would teach nothing about PSCAD and would risk a
hand-transcribed coefficient set. It belongs in Tier 2 (§4.6), imported from the generated
header. **Tier 1's PI is not the board's controller and no Tier-1 result is a statement about
the shipped loop.**

**Why the diode simplification is safe here — and the one part of it that is not.** The RT1987
behaviours dropped in Tier 1 (8 ms `t_D_ON`, 1–20 ms soft-start ramps, the −50 mV reverse
comparator behind the TP0178/TP0201 reactive-pickup gap, SCP foldback) are all *transient*
mechanisms, and Tier 1's acceptance criteria are all *steady-state* (§3.5). A diode gets the
steady-state ORing right and every one of those transients wrong, so **Tier 1 must never be
used to argue about a handoff transient** — that is Tier 2's job (§4.5).

The **conduction drop is not transient and does not get that excuse.** Each RT1987 in the
source→bus path presents `R_ON = 21 mΩ` plus a 35 mV forward servo offset. Two channels in
parallel add ≈ **10.5 mΩ** in series with the measured droop — **+14 % on 0.074 V/A**, which is
larger than §3.5's ±5 % acceptance band. So the Tier-1 ORing element carries the drop
explicitly, `V_f = 35 mV + 21 mΩ * I`, and §3.5's targets are stated diode-corrected. This is
the same term that sharpens candidate (c) in §5.3.

### 3.2 Circuit description

Two identical channels (FC, BT) into a common bus node, plus a load.

```
   [DC source V_oc]--[R_s]--+                                     +--> [C_BUS]
        (stiffness preset)  |                                     |
                            +--> [averaged boost, channel X] --> [diode] --> N_BUS --> [I_load]
                                        ^                                     |
                                        |                                     v
                                  V0 - K_ch*I_X  <---- [gain g_X] <---- [current meter I_X]
```

PSCAD master-library components (names per PSCAD 5.x master library — **adjust to your
version**; where the exact component name differs, the functional description is what matters):

| Function | Component (typical) | Notes |
|---|---|---|
| Source EMF | DC voltage source | One per channel; `V_oc` from the preset |
| Source impedance | Resistor (or series RLC branch with L, C = 0) | The stiffness knob |
| Averaged boost output | **Controlled** single-phase voltage source (source magnitude driven from a control-page signal) | The whole boost is one controlled source; the control page computes its magnitude |
| ORing diode | Diode | `V_f` set low (see table below) |
| Bus capacitance | Capacitor | One lumped value |
| Load | Controlled current source | Driven from a control-page signal |
| Current sense | Ammeter / current meter on each channel branch | Feeds the droop gain block |
| Voltage sense | Voltmeter at `N_BUS`, at each channel output | |
| Droop gain | Gain block (constant multiplier), one per channel | Multiplier comes from a slider or from the share PI |
| Loop lag | First-order real-pole block `1/(1+sT)` | `T = τ_r` |
| Operator inputs | Slider, dial, two-state switch/button | Load current, `g_F`, `g_B`, stiffness preset select, scenario select |
| Sampled control | Sample-and-hold / zero-order hold + a sampling pulse train | The 1 kHz share tick |
| Recording | Output channel → graph frame; output channels also feed the project's output file | Set the plot/output step separately from the solution step |
| Sweeps | Multiple Run component | T1-E6 |

**Averaged boost control-page equation, per channel X ∈ {F, B}:**

```
V_cmd_X   = V0 - Re_X * I_X                      # static droop law
Re_X      = RE_MAX * g_X                         # g_X in [0, 1]
V_src_X   = V_cmd_X passed through 1/(1 + s*tau_r)
```

Add two guards so the model degrades honestly rather than silently:

```
I_X limited to I_OUT_MAX                          # boost current limit
if V_in_X < V_UVLO_boost:  V_src_X -> 0           # source collapse => channel drops out
```

`V_UVLO_boost` has **no value anywhere in the repo** — `TODO(verify)`: take the TPS61288's
input UVLO from `TPS61288LRQQR.pdf` §7.3/§7.5 before running T1-E4, which is the only exercise
that can reach it. Until then, set it below the battery operating floor (7.4 V) so it cannot
fire spuriously, and record that you did.

Without the input-power reflection below, a loose supply has **no effect at all** in an
averaged model — the boost regulates its output regardless — and exercise T1-E4 would show
nothing. Add:

```
I_in_X = V_src_X * I_X / (ETA_BOOST * V_in_X)     # reflected input current
V_in_X = V_oc_X - R_s_X * I_in_X                  # source droop
```

This is the same referral the Python plant uses (`_source_current()`, `hil_plant_sim.py`).

#### Tier-1 constants

| Constant | Value | Meaning / units | Provenance |
|---|---|---|---|
| `V0` (Tier-1 default) | **15.95 V** | No-load bus setpoint, measured intercept | Measured no-load intercept, per-log fits 15.943–15.957 V, `HIL_PLANT.md` §4.2 (`V_BUS_DROOP_V0`) |
| `V0` (design) | 15.907–15.91 V | Same quantity, predicted from the FB network | `system_model.md` §2 (15.91) / `tps61288_full_model.py` `VBUS0` (15.907), post-`R_D1`=215k retune |
| `RE_MAX` | 2.014 Ω | Max per-channel electronic droop resistance at `g = 1` | `K_sns*A_v*(R_D1/R_inj)`; `.ino` `const float RE_MAX`; `system_model.md` §2 |
| `K_DROOP` (design `k_d`) | 0.30 Ω | Design droop scale, **`TODO(calibrate)`** in firmware | `.ino:1875–1879`; `system_model.md` §4 |
| `K_DROOP_BUS_SHARED` | 0.074 ± 0.004 V/A | **Measured** combined droop, both sources live | `HIL_PLANT.md` §4.2; fit of TP0170–0180 (TP0178 excluded), ML0165, ML0169, fw v16 |
| `K_DROOP_BUS_SINGLE` | 0.1615 ± 0.001 V/A | **Measured** droop, exactly one source live | ibid.; FC-only and BT-only agree within 2 % |
| `tau_r` | 100 µs (range 20–300 µs) | Boost voltage-loop lag, design-plant nominal | `system_model.md` §6d, `TODO(calibrate)`; per-channel derived range 7–25 µs from §6e crossovers |
| `C_BUS` | 35 µF | Lumped VBUS capacitance | "30–40 µF band, midpoint" — 4×10 µF RT1987 ceramics (D-FC/D-BT VOUT, D-MT/D-BFC VIN) + BUS-V divider (`boost-bringup-debug.md:49–50`); `hil_electrical.py` |
| `I_OUT_MAX` | 6.0 A | Per-channel boost output current limit | `hil_electrical.py`, **`TODO(verify)`** |
| `ETA_BOOST` | 0.85 | Boost efficiency for input-current referral | `hil_electrical.py:209`, **`TODO(verify)`** — simulator-only tuning value; numerically coincides with the unrelated drivetrain `η_dt`, which is a coincidence, not a shared measurement. **It does double duty**: this referral *and* the bus→motor power mapping (§4.7). A sensitivity sweep on it moves two physically unrelated things at once — sweep them as separate parameters if the result matters |
| `V_f` (Tier-1 ORing element) | `0.035 V + 0.021 Ω * I` | RT1987 forward servo offset **plus** conduction drop | RT1987 DS §17.6 `V_FWD` 35 mV typ and `R_ON` 21 mΩ (`hil_electrical.py` `RT_V_FWD` / `RT_R_ON`). A real silicon diode's 0.7 V would move `V0` visibly and is wrong here; dropping `R_ON` costs +14 % of the droop slope (§3.1) |
| `R_BUS_BLEED` | 2000 Ω | Bus bleed path; sets the dark-bus decay `τ = R*C_BUS = 0.07 s` at Tier-1's 35 µF (0.94 s at the HIL model's `C_BUS_F`) | `hil_electrical.py`, **`TODO(verify)`** — simulator-only. Include it, or a no-load bus never discharges and the T1-E1 snapshot/teardown behaviour is unphysical |
| `R_s` "stiff" preset | 0.05 Ω | Series source resistance, stiff supply | `R_BT_INT` legacy scalar, `hil_electrical.py:206–207`, **`TODO(verify)`** — an assumption, **not** a measured supply impedance |
| `R_s` "loose" preset | 0.45 Ω | Series source resistance, loose supply | `R_FC_INT` legacy scalar, **`TODO(calibrate)`** — the "0.447 Ω effective at 2 A" FC fit target; likewise not a supply-impedance measurement |

> **⚠ The two stiffness presets are assumptions, not measurements.** No numeric output-impedance
> spec for either bench supply exists anywhere in the repo; the batch 153–180 swap is documented
> qualitatively only ("stiffer on BT, looser on FC"). The 0.05 / 0.45 Ω pair above is borrowed
> from the HIL engine's *source* internal resistances, which are themselves `TODO(verify)` /
> `TODO(calibrate)`. Treat T1-E4 as a sensitivity study, not a reproduction. See OQ-8.

### 3.3 Solver settings

**Set the timestep from the network's fastest RC, not from `τ_r`.** Tier 1's fastest pole is the
bus node seen through the parallel channel droop resistance:

```
tau_bus = K_droop_combined * C_BUS = 0.074 * 35 uF = 2.6 us     (measured droop)
                                   = 0.30  * 35 uF = 10.5 us    (design droop)
```

2.6 µs is the number that governs. `τ_r` = 100 µs is 40× slower and is not the constraint.

| Setting | Recommendation | Reason |
|---|---|---|
| Solution timestep | **2–5 µs** | ≈ 1–2 points per `tau_bus` = 2.6 µs at the measured droop. The earlier 20 µs recommendation under-resolves the bus node by 2–8× and will show a numerically-damped step response that looks like plant behaviour. Use 5 µs while building, 2 µs for any step-response number you intend to quote |
| Plot/output step | 100 µs (1 ms for multi-second sweeps) | Decouple from the solution step; a 2 µs plot step over 10 s is 5×10⁶ points for no benefit |
| Run duration | 2–10 s | Long enough for a load sweep and for the sampled share loop to settle |
| Interpolation | Leave EMTDC's switching interpolation and chatter removal **on** | See the solver note below — it is habit-forming here and load-bearing in Tier 2 |
| Snapshot | Take one at t = 1.0 s once the bus is settled | Teaches the snapshot workflow; makes E5/E6 iterate faster |
| Run cost | 10 s at 2 µs = 5×10⁶ steps on a ~4-node linear network — seconds to minutes | Tier 1 is cheap; Tier 2 is not (§4.1) |

> **⚠ EMTDC is trapezoidal, not backward Euler — this changes what an under-resolved step
> does.** The Python hi-fi engine chose **backward Euler** deliberately, because a 22 mΩ link
> between ~35 µF nodes is a **0.77 µs RC** that explicit methods cannot follow: BE is L-stable
> and settles to the quasi-static answer at any substep instead of resolving that transient
> (research brief 2 §6). **The trapezoidal rule is A-stable but not L-stable**: an
> under-resolved stiff branch does not settle, it *rings at Nyquist*. In Tier 1 the only stiff
> element is the ORing drop, so this is mild; in Tier 2 (§4.1) the RT1987 `R_ON` links make it
> the dominant numerical hazard. Keep interpolation and chatter removal enabled, and treat any
> node oscillation at exactly one or two timesteps per cycle as a **solver artifact, not a
> plant finding**.

### 3.4 Exercise ladder

Each exercise = a PSCAD concept + a build step + a number to check. Do them in order; each
builds on the previous canvas.

#### T1-E1 — workspace, canvas, master library, static two-source bus

*PSCAD concepts:* workspace vs project; the main canvas; the master library palette; wiring
electrical nodes; a voltmeter; an output channel; a graph frame; running a case.

*Build:* two DC sources + series `R_s` (stiff preset) + two averaged boost controlled sources
(hold `g_F = g_B = 0`, i.e. no droop yet) + the two ORing elements into `N_BUS` + `C_BUS`.
No load.

*Expected:* at zero load the `R_ON` term vanishes and only the servo offset remains, so
`V_bus = V0 - 0.035 = 15.915 V` steady. With `g = 0` there is no droop term. Check the design
alternative too: `V0 = 15.91` gives `V_bus = 15.875 V`. The 0.04 V spread between the measured
and design `V0` is the model's own uncertainty floor; note it, because it is small compared to
everything else in this document.

#### T1-E2 — droop slope

*PSCAD concepts:* controlled current source; slider input; on-line plotting while a case runs;
reading a slope off two operating points; separating a **configured** parameter from a
**realized** one.

*Build:* add the load current source, driven by a slider 0 → 3 A. Enable one channel only
(force the other's `V_src` to zero).

**The realized slope is not the configured `Re`.** The ORing element adds `R_ON = 21 mΩ` in
series, so single-source:

```
realized slope = Re_elec + R_ON        with Re_elec = RE_MAX * g
```

To reproduce the **measured** single-source 0.1615 V/A you therefore configure
`Re_elec = 0.1615 - 0.021 = 0.1405 Ω`, i.e. `g = 0.1405/2.014 = 0.0698`.

*Expected (measured preset, single-source):* `V_bus(I) = 15.915 - 0.1615*I`:

| `I_load` | `V_bus` |
|---|---|
| 0 A | 15.915 V |
| 1 A | 15.754 V |
| 3 A | 15.431 V |

*Expected (design preset, single-source):* `Re_elec = 0.60 Ω` (`g = 0.298`) → realized slope
0.621 V/A → 15.915 / 15.294 / 14.052 V.

*Which ×4?* The headline discrepancy is the **shared** pair, `0.30 / 0.074 = 4.05`. This
single-source exercise shows the *single-source* pair, `0.60 / 0.1615 = 3.72` — or 4.27 if you
compare electronic droop only (`0.60 / 0.1405`). Say which pair you are quoting; they are not
the same number. Tier 1 cannot say which is right; it shows what is at stake.

> **⚠ 3 A is outside the board's legal envelope, deliberately.** `LIMIT_I_FC_MAX = 1.4 A`
> bus-side (H-20 stack, 2.6 A source-side referred) and `LIMIT_I_BT_MAX = 3.0 A`. The bench
> dataset these exercises target ran at `I_tot ≈ 0.72 A`. 3 A is used here purely for slope
> resolution — the droop law is linear, so the slope is the same at 0.7 A, just harder to read
> off a plot. **No Tier-1 number taken at 3 A is a statement about a legal operating point**,
> and a 3 A single-channel FC point is 2.1× the fault limit. If you prefer to stay legal, run
> the sweeps at `I_tot ≤ 1.5 A` and accept the coarser slope.

#### T1-E3 — two-source sharing and the mode ratio

*PSCAD concepts:* two sources on one node; measuring a ratio of two branch currents; a
computed output channel (share = `I_F/(I_F+I_B)`).

*Build:* both channels live. Set per-channel droop from a target ratio `r`:

```
Re_F = k_d / r          Re_B = k_d / (1 - r)
```

*The circuit solves the droop equation for you.* With equal `V0` and an **ideal** ORing element
(`R_ON = 0`):

```
I_F = (V0 - V_bus)/Re_F ,  I_B = (V0 - V_bus)/Re_B
alpha = I_F/(I_F+I_B) = Re_B/(Re_F+Re_B) = r
V_bus = V0 - (Re_F || Re_B) * I_tot ,  and  Re_F || Re_B = k_d  (constant, by construction)
```

That identity — share set by the *ratio* of droop resistances, bus sag by their parallel
combination, both independent of the other — is the whole point of the `k_d/r` mapping.

**With `R_ON` folded in (§3.1), each branch presents `Re_X + 0.021 Ω` and the identity is
perturbed.** Configure the *electronic* droop to hit the measured combined slope at the
balanced point: `k_d,elec = 0.074 - 0.021/2 = 0.0635 Ω`. Then, at `I_tot = 3 A`:

| `r` (commanded) | `Re_F`+`R_ON` | `Re_B`+`R_ON` | realized `alpha` | realized slope | `V_bus` |
|---|---|---|---|---|---|
| 0.50 | 0.1480 Ω | 0.1480 Ω | 0.500 | 0.0740 V/A | 15.693 V |
| 0.30 | 0.2327 Ω | 0.1117 Ω | **0.324** | 0.0755 V/A | 15.689 V |
| 0.85 | 0.0957 Ω | 0.4443 Ω | **0.823** | 0.0787 V/A | 15.679 V |

Two results worth reading off that table: `alpha` is pulled **toward 0.5** away from the
balanced point (a fixed series resistance dilutes a commanded ratio), and `V_bus` is no longer
exactly invariant in `r`. Both are real effects of a real 21 mΩ, not artifacts. This is the same
term that sharpens candidate (c) in §5.3.

*Mode ratio:* disable BT. At `r = 0.5` the surviving channel presents `2*k_d,elec + R_ON`
= 0.148 Ω while both-live gives half of that, so **single-source droop is exactly 2× shared
droop** — `R_ON` cancels out of the ratio at the balanced point. Compare the measured pair:
`0.1615 / 0.074 = 2.18 ± 0.12` (uncertainties propagated from the two fits), so 2.00 is about
**1.5σ away — consistent, not anomalous.** Do not tune a model to close it; see OQ-19.

*Governor span:* the firmware clips the commanded share so that the minority channel carries
at least `SHARE_MINORITY_I_MIN_A = 0.30 A`, giving a legal band
`[0.30/I_tot, 1 - 0.30/I_tot]`. At the bench dataset's `I_tot ≈ 0.72 A` that is
**[0.4167, 0.5833]**, which is exactly the ~0.41 / ~0.59 clip bands observed in TP0170–0180
(`CLAUDE.md` 2026-08-17b). Implement the clip as a limiter block and reproduce the band.

#### T1-E4 — supply stiffness

*PSCAD concepts:* two-state switch / dial to select a preset; comparing two runs on one graph
frame; observing an *indirect* coupling (source R affects output only through the reflected
input current).

*Build:* switch the FC source to the loose preset (`R_s = 0.45 Ω`), keep BT stiff
(`R_s = 0.05 Ω`). Repeat T1-E3 at `r = 0.85` (FC-heavy).

*Expected:* with the input-power referral in place, at `V_bus ≈ 15.7 V`, `I_F ≈ 2.47 A`
(the realized `alpha` = 0.823 from E3, not the commanded 0.85), `V_in_F ≈ 12 V`, the reflected
input current is `I_in_F = 15.7*2.47/(0.85*12) ≈ 3.80 A`, so the FC source sags by
`0.45*3.80 ≈ 1.71 V` — enough to matter, and the sag is self-reinforcing (lower `V_in` →
higher `I_in`). Converge the algebraic loop by inspection or let PSCAD's solver do it, and
record where the channel drops out.

> **⚠ Doubly outside the envelope.** 2.47 A bus-side through FC is 1.8× `LIMIT_I_FC_MAX`, and
> the 3.80 A it refers back to exceeds the H-20 stack's 2.6 A source-side allowance. On the
> real rig this operating point would fault (or brown the stack out) before the sag developed.
> Run it in Tier 1 to see the *mechanism*; do not present the numbers as a board behaviour.

> **The teaching point is a negative result.** This is *not* the mechanism behind TP0178. The
> "looser FC supply transient" hypothesis was refuted by **TP0178's own data**: at the dropout
> instant `V_fc` was **rising**, 8.12 → 8.68 V, while `I_fc` stepped to zero in the same sample
> — the boost **stopped drawing**, which a sagging supply cannot cause. **TP0201 (2026-08-25)
> is a second, independent occurrence of the same architectural signature** (`V_bus` 15.86 →
> 12.185 V; §6.2) and is what settled the question. The resolved root cause is architectural:
> the share loop slews the droop ratio across an FC↔BT conduction crossing while the pickup
> channel is a *dark standby*, and the standby RT1987 picks up only reactively, after the sag
> (`boost-bringup-debug.md:1367–1436`; mitigation is the fw v19 handoff-dwell slew cap).
> T1-E4 shows what a stiffness problem *does* look like, so you can tell the two apart.
> Reproducing TP0178 needs Tier 2's RT1987 model (§4.5).

#### T1-E5 — discrete share loop

*PSCAD concepts:* sampling pulse train; sample-and-hold and zero-order hold; a discrete
controller closed around a continuous plant; observing sampling-rate artifacts.

*Build:* measure `alpha`, filter it with a 1-pole lag at 200 Hz (`τ_f = 0.8 ms` — this
prefilter is part of the design plant, `system_model.md` §6d), sample at **1 kHz**
(`SHARE_CTRL_TS_US = 1000`), run a PI, ZOH its output as the ratio command `rc`, and drive
`Re_F = k_d/rc`, `Re_B = k_d/(1-rc)`. Apply the ratio slew limit **0.02 per tick**
(`DROOP_RATIO_SLEW_PER_TICK`, `.ino`) — the full [0.15, 0.85] band walks in ≈ 35 ms.

*Expected:* a share step 0.50 → 0.65 with the slew limit active takes ≥ 0.15/0.02 = **7.5 ticks
= 7.5 ms** to reach the new command floor, regardless of PI gain — the slew limit dominates
small steps. Settle to `alpha = 0.65` with the loop closed. Deliberately raise the PI gain
until you see the 1 kHz sampling produce a visible stair/oscillation; that is the exercise.

*Do not* read a stability margin off this. The Tier-1 PI is not the shipped controller.

#### T1-E6 — parameter sweep, snapshot, export

*PSCAD concepts:* the Multiple Run component; parameterizing a run; snapshot start; writing
output files and getting data out of PSCAD.

*Build:* sweep `k_d` over {0.074, 0.10, 0.16, 0.20, 0.30} at fixed `I_tot = 3 A` and `r = 0.5`,
recording `V_bus` and `alpha`.

*Expected:* `V_bus = 15.915 - k_d*3` → {15.693, 15.615, 15.435, 15.315, 15.015} V and
`alpha = 0.500` at every point (share is set by the *ratio* of droop resistances, not their
magnitude — a fact worth seeing rather than being told).

*Export:* PSCAD writes column-ASCII output files per run; convert to CSV with the column
names of §6.3 so that Tier-1 output is already in the Tier-2 comparison format. Getting this
habit right in E6 is why E6 exists.

### 3.5 Tier-1 acceptance

Tier 1 is complete when it reproduces the TP0170–0180 steady-state facts to first order:

All targets below are **diode-corrected** — i.e. they are what the Tier-1 canvas actually reads
at `N_BUS`, with the 35 mV servo offset and the 21 mΩ `R_ON` of §3.1 included. The bare `V0`
and `k_d` figures are the *controlled-source* values behind them, which is a different node.

| Check | Where measured | Target | Tolerance |
|---|---|---|---|
| No-load bus | `N_BUS` | **15.915 V** (`= 15.95 - 0.035`, measured `V0`) / **15.875 V** (design `V0` 15.91) | ±0.05 V, and state which `V0` you used |
| No-load source setpoint | boost controlled-source output | 15.95 V / 15.91 V | ±0.01 V — this is the pre-diode node |
| Droop slope, both sources, `k_d,elec` configured = 0.0635 Ω | `N_BUS` vs `I_tot`, at `r = 0.5` | realized `dV/dI = -0.074 V/A` | ±5 % (it is a configured value; this checks the circuit, not the board) |
| Single-source / shared droop ratio | `N_BUS` | 2.00 | exact by construction at `r = 0.5`; `R_ON` cancels there |
| Share tracking, `sp = 0.5` | `I_F/(I_F+I_B)` | `alpha = 0.500` | ±0.005 (bench sees 0.503 ± 0.028 with noise Tier 1 does not model) |
| Share tracking, `sp = 0.30` | ibid. | `alpha = 0.324` (T1-E3) | ±0.005 — the deviation from 0.300 is the `R_ON` dilution, not an error |
| Governor clip band at `I_tot = 0.72 A` | commanded ratio | [0.4167, 0.5833] | exact |

**Tier 1 uses the MEASURED droop as the configured value**, because Tier 1 has no mechanism
that could derive it. Tier 1 therefore cannot say anything about the ×4 finding beyond
showing its magnitude. Deriving the droop from the circuit is Tier 2's job.

---

## 4. Tier 2 — full detailed simulation

**Project name suggestion:** `droop_t2` in the same workspace, with two run configurations.

### 4.1 The two-configuration structure

| Configuration | Power stage | Timestep | Window | Purpose |
|---|---|---|---|---|
| **T2-SYS** | Averaged boost (reduced-form controlled source) | 0.5 µs (transient windows) / 2–5 µs (long runs) | 10–60 s | Everything compared against HIL scenarios and bench logs: sequencing, droop realization, share loop, sag/handoff transients, fault thresholds |
| **T2-FAST** | Switching TPS61288 (real L, switch, sync rectifier, `f_SW`) + parasitic L + node ESR/ESL | 10–20 ns (switching, AC extraction) / 1–2 ns (ring) | 0.5–5 ms (10–20 ms for the AC extraction) | Switching ripple reaching the sense chain; disabled-boost passthrough edges (**not** reverse back-feed — §4.3, OQ-24); hot-plug / ring events (Death-5 class); SCP inrush |

**Timestep: set it from the fastest network RC in each configuration.**

| Configuration | Fastest network RC | Consequence |
|---|---|---|
| Tier 1 | `0.074 Ω × 35 µF = 2.6 µs` (bus node) | 2–5 µs step (§3.3) |
| T2-SYS | **`0.022 Ω × 35 µF = 0.77 µs`** — an RT1987 `R_ON` link between two ~35 µF nodes; this is the RC that made the Python engine choose backward Euler (research brief 2 §6) | 0.5 µs for any window where a switch changes state; 2–5 µs is acceptable only for slow steady-state and share-loop work, and only with chatter removal on |
| T2-FAST | Set by the ring, not by an RC — see §4.10 | §4.10 |

**EMTDC is trapezoidal, not backward Euler.** The Python engine could run *coarser* than
0.77 µs because BE is L-stable and simply settles a stiff branch to its quasi-static answer.
The trapezoidal rule is A-stable but **not** L-stable: an under-resolved 0.77 µs link does not
settle, it rings at Nyquist across every RT1987 state change. Keep EMTDC's interpolation and
chatter removal on — in T2-SYS they are **load-bearing, not hygiene** — and treat any node
oscillation at one or two timesteps per cycle as a solver artifact, never as a plant finding.

**Run cost, stated honestly for both configurations:**

| Run | Steps | Order of magnitude |
|---|---|---|
| T2-SYS, 60 s @ 5 µs | 1.2×10⁷ | Tens of minutes on a six-node nonlinear network |
| T2-SYS, 60 s @ 0.5 µs | 1.2×10⁸ | Hours — reserve 0.5 µs for windowed transient runs, not full scenarios |
| T2-SYS, 50 ms transient window @ 0.5 µs | 1×10⁵ | Seconds |
| T2-FAST, 5 ms @ 20 ns | 2.5×10⁵ | Seconds to minutes (large per-step cost: switching + parasitics) |
| T2-FAST, AC extraction, 20 ms @ 20 ns × ~20 frequency points | 2×10⁷ | Hours for the sweep |
| T2-FAST, 1 ms ring window @ 1 ns | 1×10⁶ | Minutes |

Use snapshots aggressively: run T2-SYS to a settled state once, save, and start every transient
window from the snapshot rather than re-integrating the bring-up.

**Why the split, in the repo's own words.** This mirrors and extends the decision recorded in
`hil_electrical.py`: the literal datasheet loop structure was *built and then replaced*
because integrating a 4–19 kHz voltage loop at a 20–40 kHz substep rate put the crossover at
Nyquist. The same document's instruction is unambiguous — *"Do not use this engine to judge
boost stability — use `tps61288_full_model.py`, which is what it is for."*

PSCAD removes the *rate* limitation but not the *cost* one. A 60 s system run at 2 ns is
3×10^10 timesteps and is not going to happen. So the split is by **timescale**, not by
fidelity ambition:

- **T2-SYS inherits the reduced form** — a droop-regulated Thevenin source behind a
  first-order lag — for exactly the reason the Python engine did, and carries the same
  caveat: **T2-SYS makes no boost-stability or voltage-loop-margin claim.**
- **T2-FAST is where a switching model may make such a claim**, but only after it has been
  cross-checked against `tps61288_full_model.py` (research brief 1 §4: FC 16.33 vs formula
  16.84 kHz, ratio 0.97; BT/7.4 V 13.52 vs 13.84, 0.98 — 1–3 % agreement **at the pre-bodge
  `C_O`**; §4.3 re-derives the as-fitted target). The existing full-order model is the referee,
  and the AC extraction must be given a window long enough to hold the frequency it is
  measuring: a 4–17 kHz crossover needs **10–20 ms** per point (40–340 cycles plus settling),
  not the 0.5–5 ms window the ripple and edge studies use.

### 4.2 Sources

#### Model

Two selectable source configurations, chosen by a dial:

1. **Rig/bench-supply configuration** (for replaying bench logs 153–180 and the HIL scenarios):
   ideal DC source + series `R_s` preset, as Tier 1.
2. **Vehicle-source configuration**: PEM fuel-cell stack and 2S LiPo pack, in the form used by
   `hil_electrical.py` after Yadav & Assadian, *Energies* 2025
   (`references/Robust Energy Management...pdf`), cited by equation in that file.

**Fuel cell** (`FuelCellSource`, `hil_electrical.py:380–463`):

```
V_stack = N * (E - Va - V_ohmic(I)) - R_SERIES_RIG * I
dVa/dt  = (V_act(I) + V_conc(I) - Va) / FC_TAU_S          # double-layer state
```

`V_act`, `V_conc`, `V_ohmic` are the paper's Eqs. (4)/(5)/(6) verbatim. The flow-state
Eqs. (8)–(10) are **not** modelled and `E` is held constant.

**Battery** (`BatterySource`, `hil_electrical.py:466–536`):

```
V_T    = Em(SOC) - I*Rs(SOC) - V1
dV1/dt = I/C1 - V1/(R1*C1)
dSOC/dt = -I / (3600 * capacity_Ah)                        # I > 0 discharge, I < 0 charge
```

#### Constants

| Constant | Value | Meaning / units | Provenance |
|---|---|---|---|
| `FC_E_NERNST` | 1.15 V/cell | Nernst EMF, held constant | `hil_electrical.py:381` |
| `FC_N_CELLS` | 12 | Cells in stack; fitted so `N*Vcell(0) ≈ 12.97 V` matches the ~13 V OC class | `hil_electrical.py:385` |
| `FC_AREA_CM2` | 3.0 cm² | Active area | `hil_electrical.py:386`, **`TODO(calibrate)`** — never measured on the H-20 |
| `FC_TAU_S` | 0.020 s | Double-layer RC; produces the "sag-then-recover" shape under a fast load step | `hil_electrical.py:387`, **`TODO(calibrate)`** |
| `FC_R_SERIES_RIG` | 0.41 Ω | Rig wiring/contact resistance added on top of the paper's ohmic term (paper ≈ 0.04 Ω at this area; bench sees ≈ 0.45 Ω total, 0.447 Ω effective at 2 A) | `hil_electrical.py:390`, **`TODO(calibrate)`** |
| `V_FC_OPEN` / `R_FC_INT` | 13.0 V / 0.45 Ω | Legacy scalar fallback (use for the bench-supply configuration) | `hil_electrical.py:204–207`, **`TODO(calibrate)`** — ⚠ **simulator-only**: `R_FC_INT`/`R_BT_INT` were never measured against a stable reference (the supplies were swapped mid-campaign, B9/OQ-8). They are the *source models'* internal resistances, borrowed in §3.2 as stiffness presets; neither is a bench-supply output impedance |
| `BATT_CELLS` | 2 | 2S pack | `hil_electrical.py:473` |
| `BATT_CAPACITY_AH` | 5.0 Ah | Coulomb-count denominator | `hil_electrical.py`, **`TODO(verify)`** |
| `BATT_RS_NOM` | 0.040 Ω | Series R, flat mid-band, ×1→×4 below SOC 0.15 | `hil_electrical.py:473–477, 521–524`, **`TODO(calibrate)`** |
| `BATT_R1` / `BATT_C1` | 0.020 Ω / 200 F (τ ≈ 4 s) | Single RC relaxation branch | ibid., **`TODO(calibrate)`** |
| `LIPO_OCV_SOC/_V` | 9-point generic 2S curve | OCV(SOC) lookup | `hil_electrical.py:471–472` — **generic, NOT a measured pack characterization**, `TODO(calibrate)` |
| Battery operating band | 7.4–8.4 V | System decision 2026-07-10; the BT boost margin analysis assumes it | `CLAUDE.md` bodge record B2 rationale |
| `V_BT_OPEN` / `R_BT_INT` | 8.0 V / 0.05 Ω | Legacy scalar fallback | `hil_electrical.py:206–207`, **`TODO(verify)`** — ⚠ simulator-only, same caveat as `R_FC_INT` above |

#### PSCAD realization notes

- The FC polarization curve is a static nonlinearity plus one state. Two options: (a) a
  non-linear transfer characteristic / X-Y lookup block fed with `I`, feeding a controlled
  voltage source; (b) a custom component (Component Workshop, Fortran) implementing the
  equations directly. Option (a) is enough for T2-SYS and keeps the project inside the
  master library; option (b) is worth it only if you want to sweep stack parameters.
- The double-layer state and the battery's RC branch are single first-order lag blocks on the
  control page — do **not** try to build them as physical RC networks, because their time
  constants (20 ms, 4 s) are hopelessly far from the electrical timestep and will cost
  nothing on the control page.
- SOC is one integrator with a reset input; expose the initial SOC as a project parameter
  (the Python tool exposes `--soc0` / `--capacity-ah`).

> **L6 fidelity boundary (inherited).** In `hil_electrical.py` the source models see the
> ideal-diode *switch-link* current, not the boost's own input draw — so with the bus switch
> open, an enabled-but-unbussed boost's effect on FC/SOC dynamics is not modelled. PSCAD can
> do better (the boost's input branch is a real node) and **should**: wire the source to the
> boost input, not to the switch link. Note the difference when comparing against HIL runs.

#### What validates it

Only weakly. There is no FC polarization sweep and no pack characterization in the repo; every
parameter above is `TODO(calibrate)`. The one usable check is the FC's effective resistance:
**≈ 0.447 Ω at 2 A** against the bench observation. Use the source models for *shape*
(sag-then-recover, SOC walk), never for absolute magnitudes.

### 4.3 Boost regulators

#### T2-SYS: averaged (reduced form)

Identical in structure to Tier 1's, plus the pieces Tier 1 omits:

```
V_cmd  = V0 - RE_MAX * g * I_out            # droop from the §4.4 chain, not a slider
V_src  = V_cmd  through 1/(1 + s*TAU_R)
clamp  I_out <= I_OUT_MAX
if V_node(N_OFC | N_OBT) > V_OVP:  latch off       # hardware OVP -- SENSES THE OUTPUT NODE
if disabled or OVP-latched:  passthrough path active (below)
```

> **⚠ The OVP must sense the output node, not the commanded magnitude.** The TPS61288's 19 V
> OVP watches its own `VOUT` pin. Every OVP-relevant event on this board — regen back-feed,
> load dump, hot-plug ring, a chopper failure propagating back — raises the **node** while the
> commanded `V_src` sits at ~15.9 V. A model written as `if V_src > V_OVP` therefore reports
> "no OVP" in `scp-inrush` and `handoff-sag` runs no matter how high the node actually goes,
> i.e. it is silent in exactly the scenarios it exists for. Sense `N_OFC` / `N_OBT`, latch (do
> not auto-recover), and give each channel a node-voltage output channel so the trip is
> visible. Note that the firmware's `LIMIT_V_BUS_MAX` = 17.5 V trips *before* 19 V only when
> `N_BUS` is the rising node; a channel output node can pass 19 V with the bus still legal.

**Passthrough of a disabled boost — and the direction it does *not* cover.** A disabled
TPS61288 conducts from its **input to its output** through the body-diode/synchronous-rectifier
path. Model that as a Norton source `(V_in - V_BODYDIODE)` behind `R_BODY_DIODE` onto the
channel output node, active when the boost is disabled or OVP-latched and `V_in > 1.0 V`
(`hil_electrical.py:102–103, 1120–1131`) — in PSCAD, a diode in parallel with the averaged
source, gated by the enable signal.

> **⚠ Fidelity boundary — this element is forward-only and does not model the back-feed
> hazard.** The hazard `CLAUDE.md` §2 names runs the **opposite** direction: a VESC regen event
> back-feeding *into* a disabled converter through its synchronous rectifier. A unidirectional
> input→output element never carries that current, so **this model reproduces the passthrough,
> not the back-feed.** That matches the Python engine's boundary exactly, and it is why the
> sequencing rules (§4.5) — which keep a regen path from ever pointing into a disabled boost —
> remain a *procedural* protection here rather than something the model can be run against.
> Specifying the reverse element would need the TPS61288's synchronous-rectifier behaviour in
> shutdown, which is **nowhere in the repo** (OQ-24). Carried to §8.

#### T2-FAST: switching

Real power stage: input node → inductor `L` → low-side switch (IGBT/MOSFET from the master
library) → node → synchronous rectifier / diode → output node → `C_O`. Drive it from a
current-mode control page (peak-current comparator + slope, `V_COMP` from the error amp with
the `R_C`/`C_C`/`C_P` compensator) at `f_SW`.

#### PSCAD realization notes

- **T2-SYS:** the whole power stage is one controlled voltage source per channel plus the
  passthrough diode; everything else (droop law, lag, current clamp, OVP latch) is control-page
  logic. Bring the OVP comparator's input from a node voltmeter, not from the command signal.
- **T2-FAST:** use master-library switching devices with EMTDC's interpolated switching — a
  500 kHz `f_SW` at a 20 ns step is 100 steps per period, so the duty resolution is the
  interpolation's, not the step's. Model the synchronous rectifier as a switch **with** its
  anti-parallel diode so the shutdown path is topologically present even though its reverse
  behaviour is not characterized (above).
- Make `C_O` a project parameter. Both the as-fitted and pre-bodge values are wanted (below),
  and the crossover is inversely proportional to it, so it is the single most consequential
  number in this subsystem.
- Keep the two configurations' compensator components identical and switch only the power
  stage, so any T2-SYS/T2-FAST discrepancy is attributable.

#### Constants (shared)

| Constant | Value | Meaning / units | Provenance |
|---|---|---|---|
| `V_ref` | 0.6 V (spread 0.588–0.612, ±2 %) | TPS61288 FB reference | `TPS61288LRQQR.pdf` §7.5, "verified"; `hil_electrical.py`, `tps61288_full_model.py` |
| `G_EA` | 180 µS | Error-amp transconductance | `tps61288_full_model.py:61–79` |
| `K_COMP` | 13.5 A/V | Power-stage transconductance | ibid. |
| `L` | 2.2 µH | Boost inductor | ibid. |
| `f_SW` | 500 kHz | Switching frequency | ibid. |
| `R_C` | **61.2 kΩ, BOTH channels** | Compensator zero resistor | **As-fitted** (bodge B2, 2026-07-10). Schematic shows 27.4 kΩ on BT — stale |
| `C_C` | 2 nF | Compensator zero cap | `tps61288_full_model.py` |
| `C_P` | 27 pF | COMP-pin pole cap | ibid. |
| `R_EA` | 10 MΩ (swept 1–100 MΩ in the envelope study) | EA output resistance; **not** in the DS EC table | ibid. |
| `V_COMP,MAX` | 2.4 V | COMP clamp / averaged-model saturation ceiling | ibid. |
| `V_OVP` | 19.0 V | Hardware OVP trip, **sensed at the channel output node** | `hil_electrical.py:100`, "confirmed 19 V". Firmware's `LIMIT_V_BUS_MAX = 17.5 V` trips first only when `N_BUS` is the rising node |
| `V_ABSMAX` | 20.0 V | Abs-max, the ring-estimate comparison threshold | `hil_electrical.py` |
| `V_BODYDIODE` | 0.55 V | Disabled-boost passthrough drop | `hil_electrical.py:102–103` |
| `R_BODY_DIODE` | 0.15 Ω | Passthrough series resistance | `hil_electrical.py:103`, **`TODO(verify)` — not extracted from any datasheet** (OQ-17) |
| `C_O` **as-fitted (use this)** | **40.1 µF derated / 76.1 µF nominal** | Boost output capacitance actually present at each channel output node | 3×22 µF bank DC-derated to 30 µF at 17.5 V (BOM line 6; `boost-bringup-debug.md:51`) **plus the 10 µF + 0.1 µF hot-loop bodge caps, both channels** (bodge B4). Must equal §4.9's node value — they are the same capacitance |
| `C_O` *pre-bodge, for the record* | 30 µF derated / 66 µF nominal | The bank alone | The value `system_model.md` §6e's published crossover table was computed at; **stale for this board** |
| `TAU_R` | 100 µs | Reduced-form lag | `hil_electrical.py`; design-plant nominal, `TODO(calibrate)` |
| `I_OUT_MAX` | 6.0 A | Reduced-form current limit | `hil_electrical.py`, **`TODO(verify)`** |
| `R_OUT` | 0.010 Ω | Small-signal output resistance placeholder | `hil_electrical.py`, **`TODO(verify)`** |
| `f_RHPZ` | 31–330 kHz | RHP zero over the 2–8 A envelope at 7.4 V BT / 16 V bus | `system_model.md` §6e |

**Voltage-loop crossover:** `f_c = R_C*(1-D)*V_ref*G_EA*K_COMP / (2*pi*V_OUT*C_O)`.

`f_c` is **inversely proportional to `C_O`**, so the published table and the as-fitted board do
not agree. Both are given; the second is the acceptance target.

*(i) As published — computed at the **pre-bodge** `C_O` (30 / 66 µF). This is what
`system_model.md` §6e and `full_order_validation.md` Gate C carry, and it is the number the
1–3 % formula-vs-full-order agreement was demonstrated against:*

| Channel | `f_c` (derated / nominal `C_O`) | `τ_r = 1/(2*pi*f_c)` |
|---|---|---|
| FC (`V_in` 9–12 V) | 16.8–22.5 / 7.7–10.2 kHz | 7–21 µs |
| BT (`V_in` 7.4–8.4 V, `R_C` = 61.2 k post-bodge) | 13.8–15.7 / 6.3–7.1 kHz | 10–25 µs |
| *(BT pre-bodge compensator, 27.4 k — for the record only)* | 6.2–7.0 / 2.8–3.2 kHz | 23–57 µs |

*(ii) **As-fitted — the T2-FAST acceptance target.** The same formula scaled by
`30/40.1 = 0.748` (derated) and `66/76.1 = 0.867` (nominal):*

| Channel | `f_c` (derated / nominal `C_O`) | `τ_r = 1/(2*pi*f_c)` |
|---|---|---|
| **FC** | **12.6–16.8 / 6.7–8.8 kHz** | 9.5–12.7 / 18–24 µs |
| **BT** (`R_C` = 61.2 k) | **10.3–11.7 / 5.5–6.2 kHz** | 13.6–15.4 / 26–29 µs |

A correctly-as-fitted T2-FAST model checked against table (i) misses by ~25 % and looks broken
when it is right. Check against (ii).

> **⚠ OPEN FINDING — does the hot-loop bodge capacitance sit inside the compensated loop?**
> The scaling above assumes the 10 µF + 0.1 µF at the IC output pin is part of `C_O` as the
> compensator sees it. That is the natural reading — it is at the `VOUT` pin, closer to the IC
> than the 3×22 µF bank (which is 40 mil away on FC, 240 mil on BT) — but **no source in the
> repo makes the argument either way**, and §4.9 mandates the same capacitance as a node value.
> If it is instead outside the compensated loop, table (i) stands and §4.9's node value and
> §4.3's `C_O` are legitimately different numbers for different purposes. This is a **repo-wide
> question, not a PSCAD one**: if the bodge caps are inside the loop, `system_model.md` §6e's
> crossover table, the `τ_r` range feeding the share-loop design plant, and the boost-margin
> arguments in the bring-up record were all computed at a stale `C_O` and need re-deriving.
> Logged as OQ-20; do not resolve it inside a PSCAD project.

#### What validates it

- **T2-SYS:** step-load bus responses against HIL `step-load` and against the bench sag
  arithmetic (§6.2). Nothing else — T2-SYS makes no margin claim.
- **T2-FAST:** an AC extraction (inject a small perturbation at the FB node, measure the loop)
  must land inside **table (ii)** to within ~5 %, matching the 1–3 % agreement
  `full_order_validation.md` Gate C demonstrates between the formula and the 11-state model.
  Give each frequency point a 10–20 ms window (§4.1) — a 0.5–5 ms window cannot resolve a
  4–17 kHz crossover with settling. Ripple amplitude and the RHPZ-region phase are the other
  two checks. If the extraction lands on table (i) instead, check `C_O` before concluding
  anything — that is the signature of the stale value.

### 4.4 The droop chain, component level — the centerpiece

This is the subsystem the whole Tier-2 project exists for. Model it as an actual circuit so
that **realized V/A droop is an OUTPUT, not a configured parameter.**

#### Signal path

```
I_out(channel)
  -> INA253A1  (in-package 2 mOhm shunt, K_sns = 0.1 V/A, unipolar 0-referenced: REF1=REF2=GND)
  -> V_droop
  -> AD5443 MDAC, VOLTAGE-SWITCHING mode: gain g = code/4095 in [0,1], 12-bit, ZOH at 1 kHz
  -> OPA197 non-inverting amp, A_v = 1 + 40.2k/10k = 5.02, output ceiling ~4.9 V (5 V rail)
  -> V_op
  -> R_inj = 53.6 kOhm
  -> TPS61288 FB node  (R_D1 = 215 kOhm to VOUT, R_D2 = 10 kOhm to GND, V_FB regulated to V_ref)
```

#### The algebra the circuit must reproduce

FB-node superposition (`system_model.md` §2; the same superposition
`tps61288_full_model.py` solves):

```
V_out = V_ref * (1 + R_D1/R_D2 + R_D1/R_inj)  -  (R_D1/R_inj) * V_op
V_op  = A_v * g * K_sns * I_out
=>  V_out = V0 - Re(g) * I_out,   Re(g) = K_sns * A_v * (R_D1/R_inj) * g = RE_MAX * g
```

Numerically: `R_D1/R_inj = 215/53.6 = 4.011`; `RE_MAX = 0.1 * 5.02 * 4.011 = 2.014 Ω`;
`V0 = 0.6*(1 + 21.5 + 4.011) = 15.907 V`. MDAC resolution `ΔRe = RE_MAX/4096 = 0.492 mΩ/LSB`.

**Do not implement this equation on the control page.** Implementing it as an equation
guarantees the design answer and makes T2-X1 (§5) meaningless. Build the resistors, the amp
and the injection node as real components and let PSCAD solve the node.

#### Constants

| Constant | Value | Meaning / units | Provenance |
|---|---|---|---|
| `K_sns` | **0.1 V/A** | INA253**A1** transimpedance, **as fitted** | Bodge B6; `.ino:1861–1865`. The A3 variant (0.4 V/A) was intended; the block-diagram PDF still labels 400 mV/A — OQ-12 |
| INA253 internal shunt | 2 mΩ | A fixed physical droop of ~0.1 % of `RE_MAX` | `hil_electrical.py` `R_SHUNT`; neglected in the algebra, keep it in the PSCAD circuit — it is free |
| `A_v` | 5.02 | OPA197 non-inverting gain, `1 + Rop2/Rop1`, `Rop1 = 10 kΩ`, `Rop2 = 40.2 kΩ` | `system_model.md` §8; `.ino:1865–1880` |
| `V_OP_CEIL` | ≈ 4.9 V | OPA197 output ceiling on the bodged 5 V rail | Bodge B5. Headroom is non-binding for `g*I <= 9.8 A`; **monitor it anyway** (§5) |
| `R_D1` | **215 kΩ** | FB top resistor, **as fitted, both channels** | Bodge B1. Schematic 237 kΩ; an older mfg export says 243 kΩ (OQ-1) |
| `R_D2` | 10 kΩ | FB bottom resistor | `system_model.md` §8 |
| `R_inj` | 53.6 kΩ | Droop injection resistor into the FB top node | ibid. |
| `R_D1/R_inj` | 4.011 | Injection attenuation | `.ino` `RD1_OVER_RINJ` (uses 215.0f) |
| `V_ref` | 0.6 V (±2 %: 0.588–0.612) | TPS61288 FB reference | `TPS61288LRQQR.pdf` §7.5 |
| `RE_MAX` | 2.014 Ω | Max per-channel droop resistance at `g = 1` | `.ino` `const float RE_MAX = K_sns * A_v * RD1_OVER_RINJ;` |
| `ΔRe` per LSB | 0.492 mΩ | MDAC quantization in droop terms | `RE_MAX/4096` |
| `MDAC_res` | 4095 | AD5443 12-bit full scale | `.ino`, "VERIFIED `ad5426_5432_5443.pdf` Table 1 + Fig 49" |
| MDAC command nibble | `0x1000` (`MDAC_CMD_LOAD_UPDATE`, C3..C0 = 0001) | "Load and update" | `ad5426_5432_5443.pdf` Table 10 |
| MDAC SPI | 1 MHz, MSB-first, **`SPI_MODE2`** | SCLK idles HIGH, data clocked on falling edges | DS Fig 2 / p.20; a prior `SPI_MODE0` bug put MOSI transitions on the sample edge |
| `K_DROOP` (`k_d`) | 0.30 Ω | Design droop scale | `.ino:1875–1879`, **`TODO(calibrate)`**; hard bound `RE_MAX*DROOP_R_MIN = 2.014*0.15 = 0.302 Ω` |
| `DROOP_R_MIN` | 0.15 | Minimum commanded share ratio | `.ino:1875–1879` |
| `g` at `r = 0.5` | 0.298 | `K_DROOP/(RE_MAX*0.5)` → `Re = 0.60 Ω/channel`, 0.30 Ω combined | Design arithmetic, `HIL_PLANT.md` §4.2 |

**Retired, for traceability:** the firmware previously used `k_eq = 0.45` in
`g = k_eq/(r*K_sns*A_v)`, omitting the `R_D1/R_inj` attenuation (then 4.42, pre-retune)
entirely. The consequence was both MDACs pinned at full scale over almost the whole commanded
range with achieved share stuck at ≈ 0.5. `k_eq` has been removed; current firmware uses the
`K_DROOP`/`RE_MAX` mapping directly. Do not resurrect `k_eq` in any model.

#### PSCAD realization notes

- **INA253:** a gain block (0.1 V/A) fed from the channel ammeter, then a first-order lag for
  its bandwidth. **`TODO(verify)`: the INA253's bandwidth is not recorded anywhere in the
  repo** — extract it from `INA253A1IPWR.pdf` before running T2-FAST, where it decides whether
  switching ripple reaches the FB node. For T2-SYS any bandwidth ≫ 1 kHz is indistinguishable.
  Model the 2 mΩ shunt as a real series resistor in the channel branch.
- **AD5443:** a multiplier — `V_op_in = g * V_droop` — with `g` quantized to 12 bits
  (`floor(g*4095)/4095`) and held by a ZOH clocked at the 1 kHz `powerBalance()` tick. The SPI
  transaction itself need not be modelled; only its *effect* (quantization + ZOH + update rate)
  matters. If you want the code words in the output file for direct comparison with the HIL
  CSV's `mdac_fc`/`mdac_bt`, emit `0x1000 | code` (see §6.3).
- **OPA197:** a gain block plus a first-order lag for GBW, a rate limiter for slew, and a
  **hard limiter at `V_OP_CEIL` and at 0 V**. The limiter is not decoration — it is one of the
  candidate explanations for the ×4 finding (§5.3(b)). `TODO(verify)`: OPA197 GBW and slew rate
  are not recorded in the repo; take them from `OPA197.pdf`.
- **Injection + FB network:** real resistors on the electrical canvas, into a node that the
  boost's control page reads as `V_FB`. In T2-SYS the boost is a controlled source, so close
  the outer loop explicitly: drive the source magnitude with an integrator/regulator that holds
  `V_FB = V_ref`. **Set that regulator's bandwidth to the reduced-form `1/(2*pi*TAU_R)` ≈
  1.6 kHz, not to the §4.3 crossover.** The droop still emerges from the resistor network at DC
  — which is all T2-X1 needs — while the loop stays inside what a 0.5–5 µs step can integrate.

  > **⚠ Why not close it at the real 10–17 kHz crossover.** At a 5 µs step, a 16.8 kHz loop is
  > 11.9 steps per period (~15° of discretization phase loss); at the pre-bodge 22.5 kHz figure
  > it is 8.9 steps (~20°). That is a milder version of **exactly the failure this document
  > quotes in §4.1** — a voltage loop integrated near its own Nyquist — inside the one subsystem
  > that promises to make no boost-stability claim. If you do want the real crossover closed in
  > T2-SYS, pin the timestep to **≤ 1 µs** for that run and check the ratio explicitly.
  >
  > **Standing check for both tiers:** report `steps per crossover period =
  > 1/(f_c * Δt)` for every closed loop in the model, and treat anything below ~20 as a
  > numerical result rather than a plant result.

- **Component tolerances:** make `R_D1`, `R_D2`, `R_inj`, `Rop1`, `Rop2`, `K_sns` and `V_ref`
  project parameters, not literals, so the Multiple Run component can sweep them (§5).
  `R_inj` and `R_D1` get the widest sweep range — they are candidate (e), T2-X1's first
  experiment.

#### What validates it

- The static law: with `g` fixed, a load sweep must give `dV/dI = -RE_MAX*g` to within the
  numerical noise floor.
- `V0` at `g = 0`: **15.907–15.91 V**, matching `system_model.md` and `tps61288_full_model.py`.
  If the PSCAD network does not produce this, the network is wired wrong — stop and fix it
  before anything else, because every downstream number depends on it.
- `ΔRe` per LSB = 0.492 mΩ, checked by stepping the MDAC code by 1.
- Then, and only then, §5.

### 4.5 RT1987 ideal-diode controllers (×6)

#### Model

Behavioral, per switch: four states **OFF → TD_ON → SOFT → ON**, with block/reverse paths back
to OFF. This is a direct port of `class Rt1987` (`hil_electrical.py:574–789`).

| State | Entry condition | Behaviour | Exit |
|---|---|---|---|
| OFF | EN low, or UVLO, or reverse-comparator trip, or SCP cut | **No network contribution at all** — back-to-back FETs, full isolation, matching the DS. Not a diode drop; an open circuit | EN high & `V_in > UVLO` → TD_ON |
| TD_ON | EN rise | Still open. Waits `RT_TD_ON_S` | `t_state >= 8 ms` → SOFT |
| SOFT | after TD_ON | Gate ramps over `tON(C_SS, V_IN)`; **SCP foldback is active only here** | `t_state >= tON` **AND** `(V_in - V_out) <= 2*V_FWD` (70 mV) → ON. Foldback clamp continuous ≥ 250 µs while `(V_in-V_out) > 1.0 V` → **CUT** (OFF, retry in 64 ms) |
| ON | soft-start complete | Forward servo: `i = (ΔV - V_FWD)/(R_ON + r_series)`; fast reverse comparator `(V_in - V_out) < -50 mV` → immediate OFF with `_restart_no_ss` set (re-arms **without** a new soft-start once forward again) | reverse trip / EN low / UVLO |
| *(any) → OFF via EN-low or UVLO* | EN falls, or `V_in` drops below UVLO | **`_restart_no_ss` is cleared UNCONDITIONALLY**, and **`t_retry` is reset to 0 unconditionally** | — |

> **⚠ Both unconditional resets are load-bearing; a model without them under-reports the
> hot-plug case.** They are the H2 and M1 review fixes already present in the Python engine
> (`hil_electrical.py:682–701`), not optional detail. Without the `_restart_no_ss` clear, a
> fresh enable into a **discharged** node inherits a stale re-arm flag and skips `TD_ON` +
> `SOFT` entirely — which **defeats foldback on exactly the Death-5 hot-plug case**, so the
> model reports as benign the one event `bringup` and `scp-inrush` (§6.2) exist to catch.
> Without the `t_retry` clear, an EN cycle does not reset the 64 ms retry timer. Build both
> into the state machine before running stage 2b (§7).

**What actually causes the TP0178 / TP0201 handoff gap** — and what `_restart_no_ss` does about
it. The gap is caused by **the reverse comparator opening the standby switch, plus the 35 mV
forward-servo threshold that must be re-crossed before it conducts again**: the bus has to sag
until the dark channel is forward-biased by more than 35 mV before any current flows.
`_restart_no_ss` is not the cause — it **bounds** the gap, by letting the re-closure happen
without a fresh `t_D_ON` + soft-start. Clearing it here would stretch the same event from
~6 ms to roughly **8 ms `t_D_ON` + ~19.8 ms ramp ≈ 28 ms**. Model it as the mitigation it is;
attributing the gap to it inverts cause and remedy.

**Soft-start ramp time** (DS §17.3 formula, `rt1987_t_on_s`):

```
tON = (V_IN / 35) * (C_SS_nF / 0.0023 - 100)   microseconds
```

#### Constants

| Constant | Value | Meaning / units | Provenance |
|---|---|---|---|
| `RT_UVLO_V` | 3.175 V (hysteresis 250 mV typ → release ≈ 2.925 V) | Undervoltage lockout | `RT1987_DS-00.pdf` §17.1 typ; exact match to `hil_electrical.py:124` |
| `RT_TD_ON_S` | 8 ms | EN rise → VOUT at 10 % of VIN | DS `t_D_ON` typ; `:125` |
| `RT_R_ON` | 0.021 Ω | Path resistance | DS 20 mΩ typ @20 V / 22 mΩ typ @5 V; `:126` |
| `RT_V_FWD` | 35 mV | Ideal-diode forward servo `V_IN - V_OUT` | DS §17.6; `:127` |
| `RT_V_REV` | −50 mV | Fast reverse comparator, `t_FRC` 0.5 µs typ | DS; `:128` |
| `RT_SCP_BLANK_S` | 250 µs | Continuous clamp before the path is disabled | DS §17.5; `:129` |
| `RT_SCP_RETRY_S` | 64 ms | `t_SCP_RST` auto-retry | DS; `:130` |
| `RT_I_FOLD_LOW/HIGH`, `RT_DV_FOLD_KNEE` | 2.5 A / 8.5 A / 5 V | SCP foldback: ΔV ≥ 26 V → 2.5 A, = 10 V → 7 A, ≤ 5 V → 8.5 A. The code's linear fit gives 7.05 A at 10 V (matches the DS point); "16 V → ≈5.3 A" is **interpolated**, not a datasheet point | DS SCP table; `:131–133` |
| `C_SS` — **D-FC, D-BT, D-MT** | **100 nF** | Soft-start cap, **as fitted** (bodge B3) | Ramp ≈ **19.8 ms** at `V_IN` = 16 V |
| `C_SS` — **D-BRG, D-BFC, B-BSQ** | **5.6 nF** | As designed and deliberately retained | Ramp ≈ **1.07 ms** at `V_IN` = 16 V |

> **⚠ Provenance correction.** `hil_electrical.py`'s `CSS_NF` table cites "schematic 20260622"
> for the 100 nF values. That citation is imprecise: BOM line 80 lists **one** 5600 pF
> soft-start part (C-DS, qty 6) for **all six** RT1987s, and the paper schematic still shows
> 5.6 nF everywhere. The 100 nF on three of six is a post-manufacturing bodge (B3). Model the
> as-fitted split; cite the bodge, not the schematic.

**All RT1987 figures above are TYPICALS ONLY.** The datasheet min/max spread is not modelled
anywhere in the repo. A PSCAD tolerance study of `t_D_ON` and `V_FWD` would be new information,
not a reproduction.

#### Topology and node mapping

| Firmware switch | Bit | Designator | Nodes |
|---|---|---|---|
| `FC_BUS_ENABLE` | 0x01 | D-FC | `N_OFC → N_BUS` |
| `BT_BUS_ENABLE` | 0x02 | D-BT | `N_OBT → N_BUS` |
| `MOT_PWR_ENABLE` | 0x04 | D-MT | `N_BUS → N_MOT` |
| `REGEN_ENABLE` | 0x08 | D-BRG | `N_MOT → N_CHG` (2026-08-30 topology fix — see note below) |
| `FC_CHARGE_ENABLE` | 0x10 | D-BFC | `N_BUS → N_CHG` |
| `BT_SEQUENCE_ENABLE` | 0x20 | B-BSQ | gates the pack into the BT boost **input** (enable-state only; no node link in the HIL model) |

(BOM line 77: RT1987N-A qty 6, designators D-FC, D-BT, D-MT, D-BRG, D-BFC, B-BSQ — the
spelling used throughout this document; per-net aliases are listed once in §2.1.)

> **Topology fix, 2026-08-30 (authority: schematic sheet 4).** `D-BRG` and `D-BFC` join their
> **outputs** at the single shared `VCHG-IN` node (`N_CHG`) that feeds the Ag105, and the
> `CHG-V` divider senses that node; the charger always draws from it, whichever path is open.
> The `RGN-V` divider and the TL431/BSP170P chopper sit on **V-MOT itself, upstream of the
> REGEN switch** — so there is no separate regen node. `N_RGN` is **retired** as a physical
> node (the earlier `N_MOT → N_RGN` mapping put the regen sense point on the wrong side of the
> switch). The same retirement is recorded in `tools/hil_electrical.py:568–575` and
> `docs/HIL_PLANT.md` §8.2.

Also present as-fitted: **10 kΩ EN-to-GND resistors** (bodge B7) so every switch defaults low
while the Teensy GPIO is high-Z during reset/boot. Include them; they only matter in a
power-on-transient study, which is exactly the kind of study T2-FAST is for.

#### PSCAD realization notes

- Each switch = a controlled breaker (or a MOSFET model) in series with the servo behaviour on
  a control page, plus the state machine. The state machine is a small piece of sequential
  logic: PSCAD's logic/timer blocks can express it, but a **custom component (Component
  Workshop, Fortran)** is the honest way to build a four-state machine with two timers and
  three comparators, and it makes the six instances trivially reusable.
- **The OFF state must be a genuine open circuit**, not a reverse-biased diode. Getting this
  wrong silently creates leakage paths that make the handoff experiments meaningless.
- The forward servo is best realized as a controlled voltage source of 35 mV in series with
  `R_ON` inside the switch, so the "diode" drop is the servo target rather than a junction.
- **Sequencing rules live in a test harness, not in the switch models.** The firmware's rules —
  `BT_SEQUENCE_ENABLE` initializes OFF then goes ON and stays; `FC_CHARGE_ENABLE` requires
  `BT_BUS_ENABLE` and `REGEN_ENABLE` OFF first; `REGEN_ENABLE` ⊕ `FC_CHARGE_ENABLE` mutually
  exclusive; `MOT_PWR_ENABLE` pre-charged during bring-up and held through Idle/Run
  (Death-5-superseded rule), torn down only in State 99 — belong in a scenario driver so that
  **illegal combinations can be deliberately simulated.** Hardwiring the guards into the model
  makes it impossible to ask what the guards are protecting against.
- **The `MOT_PWR` hot-plug guard has constants, and they belong in the harness.** The firmware
  does not simply close `MOT_PWR_ENABLE`: `assertMotPwrEnable()` / `motPwrHotPlugUnsafe()` gate
  it and raise `FAULT_MOT_HOTPLUG` (0x4000) / `ERR_MOT_HOTPLUG` (0x0F) instead of closing onto
  a discharged node. The parameters are **`MOT_HOTPLUG_MARGIN = 3.0 V`** (`.ino:1401`,
  **`TODO(calibrate)`**) and **`MOT_CONNECT_TIMEOUT_MS = 500 ms`** (`.ino:1409–1410`). Model
  them in the harness with a switch to disable the guard — running the guard *off* is how you
  see what it prevents, and it is the only way to reach the Death-5 stimulus deliberately.

#### What validates it

- Soft-start ramp times: **19.8 ms** (100 nF) and **1.07 ms** (5.6 nF) at `V_IN` = 16 V,
  against `hil_electrical.py:648–650` / `HIL_PLANT.md` §8.4.
- The `bringup` HIL scenario: staged P0–P3 bring-up against real `t_D(ON)` 8 ms plus the ramps.
- The `handoff-sag` HIL scenario and the TP0178/TP0201 bench shape (§6.2).
- The `scp-inrush` HIL scenario: foldback margin holds at 2 A V-MOT draw and breaks at ≥ 4 A
  into 64 ms burst-retry.

### 4.6 MCU discrete controls

#### Model

Everything the Teensy does that the electrical model can see, at its real rate.

| Function | Rate | Notes |
|---|---|---|
| ADC sampling + quantization | loop rate | Quantize `V_bus`, `V_fc`, `V_batt`, `I_fc`, `I_batt` before they reach any control block. **State the resolution explicitly** — `CLAUDE.md` §5 requires `analogReadResolution()` to be set deliberately with `ADC_MAX` matching (12-bit → `ADC_MAX = 4095`, the value the reconciliation specifies; the stale 10-bit `1023.0` must not be used). Read the shipped value out of `.ino` and pin it as a project parameter; the current LSB is `ADC_VREF/ADC_MAX/K_sns` (`.ino:1161` `SCALE_I`) |
| `powerBalance()` / share controller | **1 kHz** (`POWER_BAL_PERIOD_US = 1000`, `SHARE_CTRL_TS_US = 1000`) | The difference equations advance exactly once per `Ts` |
| Measurement prefilter | 200 Hz 1-pole (`τ_f = 0.8 ms`) | Part of the design plant; the **setpoint is not filtered** |
| Governor load filter | EMA α = 0.05/tick (≈ 20 ms settle) | `SHARE_GOV_FILT_ALPHA` |
| MDAC write | 1 kHz, ZOH | `setDroopMdac()` at the `powerBalance()` tick |
| Ratio slew limit | **0.02 / tick**; reduced during handoff dwell | `DROOP_RATIO_SLEW_PER_TICK`; `DROOP_RATIO_SLEW_HANDOFF_PER_TICK` (fw v19 TP0201 mitigation, `SHARE_HANDOFF_DWELL_MAX_TICKS ≈ 175 ticks ≈ 200 ms`, motion-gated) |
| Drive controller | 500 Hz (`DRIVE_CTRL_TS_US = 2000`), clamp ±12 A | **Optional** — see below |

**Share controller structure** (`teensy_controller/share_controller_coeffs.h`):

```
Gc(z) = R(z) + kI * Ts/2 * (z+1)/(z-1)
```

`R(z)` is `SHARE_CTRL_NSOS = 3` DF2T biquad sections; the integrator is kept separate in
firmware for back-calculation anti-windup. `SHARE_CTRL_KI = 111.9296298`. Tustin at
`Ts = 1 ms`. `SHARE_CTRL_MEAS_FILT_A = 0.2865047969` (the τ_f = 0.8 ms lag). γ = 0.6859,
`T(0) = 1` enforced.

> **⚠ Coefficient import rule.** `share_controller_coeffs.h` is **GENERATED** — regenerate via
> `controller_design/synthesize_controller.py`; it must never be hand-edited, and it must not
> be hand-transcribed into PSCAD either. Export the SOS coefficients to a text file from the
> generator and have the PSCAD project read them (a data file, a parameter table, or a
> generated `.f` include for a custom component). If you type them in by hand, record in the
> project which generator run produced them and check them digit-for-digit; a silently drifted
> coefficient set produces a plausible, wrong answer. The same rule applies to
> `drive_controller_coeffs.h` if the drive loop is included.

**Governor and arming logic** (reproduce these; they explain most of the observed share
behaviour):

- `SHARE_MINORITY_I_MIN_A = 0.30 A` (raised from 0.20).
- **0.60 A closed-loop entry gate** = 2 × `SHARE_MINORITY_I_MIN_A` of *filtered total current*.
  Below it the loop runs **open-loop feedforward/hold** — the old collapse-to-0.5 fallback was
  deleted after the TP0053 relay-cycle. At the crossing, the setpoint is clipped so the
  commanded minority current is ≥ 0.30 A, and the OPEN→CLOSED handover is a **deliberate
  discontinuity** up to the clip magnitude.
- Mode bits: bit2 = `shareClosedLoopMode`, bit3 = `shareClosedLoopRun` → CLOSED / OPEN(hold) /
  OPEN(feedforward).
- `powerBalanceLive`: manual runs step the closed loop only when armed. **This is why the
  TP0170–0180 sweep is the repo's only genuine closed-loop share dataset** — the ML/`'V'`
  manual runs had `gFC = gBT = 0` outright, and YP0152's total source current never crossed the
  0.60 A gate, so it ran open-loop feedforward for 99.8 % of the run.

**MDAC split** (`.ino:9201–9203`):

```
droop_gain_FC_actual = K_DROOP / (RE_MAX * rc)
droop_gain_BT_actual = K_DROOP / (RE_MAX * (1 - rc))
setDroopMdac(droop_gain_FC_actual, droop_gain_BT_actual)      # each constrained to [0,1] * 4095
```

**Drive loop: optional, default OFF.** The default Tier-2 load driver is a *commanded-current
profile* — a slider, a synthetic trapezoid, or a replayed BLG/HIL `I_cmd` trace. Duplicating
the 5-state Hanus-conditioned Youla drive controller adds essentially nothing to an
electrical study and adds a large surface for transcription error. Provide it as a
switchable subsystem for closed-loop studies only, and if you build it, import
`drive_controller_coeffs.h` under the same rule as above. Note that the drive controller's
state is kept in **double** in firmware for a documented reason (a float32 state recursion
measurably diverges); PSCAD's control page is double throughout, so this is a non-issue there.

#### PSCAD realization notes

- Build the sampling clock once (a pulse generator at 1 kHz) and fan it out to every
  sample-and-hold in the MCU subsystem, so every discrete element shares one edge — as they do
  on the board.
- The biquad chain is either three `1/(1+...)`-style discrete blocks or, better, one custom
  component implementing the DF2T recursion from the imported coefficients.
- The slew limiter and the governor clip are ordinary rate-limiter and hard-limiter blocks,
  but their **order matters**: firmware clips the setpoint, then the controller runs, then the
  ratio slew limits the *output*. Reproduce that order.

#### What validates it

Share tracking at `sp = 0.5` → **0.503 ± 0.028** (TP0170–0180); clip bands
**[0.4167, 0.5833]** at `I_tot ≈ 0.72 A`; rails passing through clean; and the shape of the
OPEN→CLOSED handover discontinuity at the 0.60 A crossing.

### 4.7 Motor / VESC load

#### Model

Bus-side current draw, matching the Python plant so the two are comparable:

```
f_drive = K_F * I_cmd                                        # the commanded tractive force, N
m_eff * dv/dt = f_drive - sign(v)*F_c - b_eff*v              # mechanical, control page
p_mech  = max(0, f_drive * v)                                # REGEN FLOORED AT 0 on the bus side
i_motor = p_mech / (ETA_BOOST * v_bus)   when MOT_PWR closed and v_bus > 1.0 V
i_total = i_motor + I_AUX_A
```

`f_drive` is the tractive force the commanded current produces (`K_F * I_cmd`); the drag terms
are excluded from it so that `p_mech` is the power the *converter* must supply, not the net
power accelerating the mass. Motor force is produced only when `MOT_PWR_ENABLE` is closed
**and** `v_bus > 5.0 V`.

`ETA_BOOST` here is the **same symbol** used for the source-side referral in §3.2, and it is
one number doing two physically unrelated jobs (converter efficiency into the bus, and bus
power into mechanical power). Give them separate project parameters if you intend to sweep
either.

> **Why regen is floored at zero on the bus side:** the VESC's Battery Regen Max is a **torque
> clip, not a dump path** — excess kinetic energy stays kinetic. This is a measurement, not a
> modelling convenience: at −12 A commanded, ~6 % was delivered (`CLAUDE.md` 2026-08-17b).
> Energy that *does* reach the board goes to the regen node and the chopper (§4.8), not back
> into VBUS.

#### Constants

| Constant | Value | Meaning / units | Provenance |
|---|---|---|---|
| `m_eff` | 3.5 kg | Effective translational mass; `J = 0.0203 kg·m²`, `J/r_fly² = 3.50` | `motor_id_20260815.md`; **CONFIRMED** by the fw v14 K_F correction |
| `K_F` | 0.7538 N/A | `k_t * η_dt * φ / r_tire` = `4.266e-3 * 0.85 * 6.86 / 0.033` | fw v14 force-axis correction (retired value 0.4516) |
| `F_c` | 2.00 N (±0.42; cold 2.19, warm 1.75–1.84) | Coulomb friction | fw v14 |
| `b_eff` | 0.534 N·s/m (±15 %) | Viscous drag | fw v14 |
| `r_tire` / `r_fly` | 0.033 m / 0.0762 m | Force radius / encoder+inertia radius — **distinct roles, do not conflate** | fw v14 |
| `φ` | 6.86:1 | Gear ratio (fitted 29T/70T, triple-confirmed; the retired 9.49 was stock gearing) | fw v14 |
| `k_t` | 4.266e-3 N·m/A | Motor torque constant (Castle 1406 1900KV, 4-pole) | `motor_id_20260815.md` |
| `R_m` / `L` / `λ` | 22.6 mΩ / 10.96 µH / 1.422 mWb | Motor electrical | ibid. |
| `η_dt` | 0.85 | Drivetrain efficiency, **`TODO(calibrate)` — "the largest surviving drive unknown"** | ibid. |
| VESC current-loop τ | ≈ 1.0 ms | First-order lag from `I_cmd` to delivered current | ibid. |
| `V_STICTION` | 0.02 m/s | Stiction deadband | `hil_plant_sim.py`, **simulator-only tuning value, `TODO(verify)`** |
| `I_AUX_A` | 0.15 A | Fixed housekeeping load on VBUS | `hil_electrical.py:208`, **`TODO(verify)`** |
| `MOTOR_I_CMD_MAX` | 12.0 A | Firmware command-side clamp (static-asserted against the drive controller's clamp) | `.ino` |
| VESC Battery Current Max | 6.0 A forward | Operator-set 2026-08-16; **above** the §12.4-derived ≈ 4.2 A allowance — open action | `docs/VESC_MOTOR_INTEGRATION.md` |
| VESC Battery Regen Max | 1.5 A | Operator-set | ibid. |
| Post-reversal dead window | ≈ 428 ms | +11.4 A commanded, < 50 mA delivered (ML0151 t = 42.0 s) | `VESC_MOTOR_INTEGRATION.md:230–233` |

#### PSCAD realization notes

- The mechanical ODE is two integrators and a sign function on the control page. `sign(v)` at
  `v ≈ 0` needs the stiction deadband or it will chatter at the timestep.
- The bus draw is a **controlled current source** at `N_MOT`, plus the 470 µF + VESC input
  capacitance (§4.9). Guard the `1/v_bus` division: the Python engine's H1 review finding was
  that an unguarded motor stamp into an open `MOT_PWR` node ran the solver to ~10 kV and
  manufactured a **false Death-5 banner**. Use a bounded Norton stamp (a current source with a
  parallel conductance) and a node-runaway backstop at 2×`V_ABSMAX`.
- The VESC layers — the **6.0 A forward cap**, the **1.5 A regen clip**, and the **428 ms
  reversal dead window** — are **optional behavioral overlays**, default ON for HIL
  comparison. None of them is in the Python plant (which floors regen at 0 and models no
  forward cap), so **turning them on makes PSCAD deviate from the HIL plant by design**;
  record which setting produced each comparison run.

> **The dead window is characterized, not explained.** ≈ 428 ms of near-zero delivered current
> after a hard regen→drive reversal is an *observation* from one log. Modelling it as a timed
> dropout reproduces the symptom without any claim about the mechanism. `TODO(verify)` —
> characterizing it on the bench (a `'W'`/`'T'` reversal test) is a standing bench item.

### 4.8 Regen chopper

#### Model

Autonomous, **not** firmware-controlled: a TL431 comparator driving a BSP170P P-channel MOSFET
that dumps the regen node into 47 Ω. It sits on **V-MOT** (`N_MOT`) — the regen node *is* the
motor node, upstream of the REGEN switch (2026-08-30 topology fix). It therefore does not
reach the bus through the REGEN path, but it **does** couple to `V_bus` through a closed
`MOT_PWR`: at the 18.1 V clamp the shunt draws ≈ 0.385 A, which the droop law (0.074 V/A
both-sources, 0.16 V/A single-source) turns into ≈ 0.03–0.06 V of bus sag — consistent with
the bench observation "`V_bus` unmoved".

```
if V_rgn > V_CHOPPER_TRIP:  conduct, P = V_rgn^2 / R_CHOPPER
```

#### Constants

| Constant | Value | Meaning / units | Provenance |
|---|---|---|---|
| `V_CHOPPER_TRIP` | **18.1 V** | Clamp threshold | Bench-calibrated 2026-08-27 (observed `V_rgn` 13.3 → 18.1 V held). Retires the 16.5 V `TODO` placeholder |
| `R_CHOPPER` | 47.0 Ω | Dump resistor | `hil_electrical.py:187–198`; BOM |
| `P_CHOPPER_MAX_W` | 20.0 W | Device/resistor **rating** — a parts figure, *not* part of the 2026-08-27 measurement | `hil_electrical.py:187–198` |
| Switch | BSP170PH6327XTSA1, P-ch 60 V 1.9 A SOT223-4 | BOM line 34, designator Q-SNT | |

Arithmetic worth checking in the model: steady dissipation at the clamp is
`18.1²/47 ≈ 6.97 W`; 20 W is only reached past `sqrt(20*47) ≈ 30.7 V`. So the chopper is not
thermally limiting at its own clamp point — a useful sanity result.

#### PSCAD realization notes

- A comparator with hysteresis driving a switch in series with a 47 Ω resistor from `N_MOT` to
  ground. The TL431's own dynamics are not modelled and there is no repo data to model them
  from; the element is a threshold, `TODO(verify)` on turn-on speed.
- Give it a dissipation output channel (`V_rgn²/47`, running peak) and a "chopper conducting"
  logic channel — the Python engine tracks exactly these two (`chopper_peak_w`,
  `chopper_over_power`) and `run_hil_suite` turns the second into a failing check.
- The chopper connects to `N_MOT`, **not** to `N_BUS` directly. Its only route to the bus is
  through the `MOT_PWR` switch element, which must be modelled as the switch it is. Do not
  attach the clamp straight to `N_BUS`; a model that clamps the bus unconditionally will hide
  every OVP-class event §4.3 exists to catch.

#### Role, stated correctly

The chopper is the **PRIMARY fast clamp**. The Ag105 is the slow secondary harvester. The
firmware's `MPPT_DISABLE` assertion during braking exists to stop the Ag105's perturb-and-
observe loop fighting the transient — **not** because the chopper needs help. The firmware
**does** check the regen node: `FAULT_OV_RGN` trips against `LIMIT_V_RGN_MAX = 28.0f`
(`teensy_controller.ino:1347`), which is 9.9 V above the 18.1 V clamp — so a PSCAD run in
which `V_rgn` goes somewhere interesting between 18.1 V and 28 V is below the firmware's
threshold, and only an excursion past 28 V would latch a fault.

#### What validates it

The observed clamp behaviour during the sustained regen rail in logs 153–180:
`V_rgn` 13.3 → 18.1 V peak, held, with `V_bus` unmoved.

### 4.9 Node capacitors

| Node | Model value | Provenance |
|---|---|---|
| `N_OFC` (FC boost output) | **40.1 µF** — see flag below | 3×22 µF X7R 1210 (BOM line 6) DC-derated to ~30 µF at 17.5 V (`boost-bringup-debug.md:51`) **plus the 10 µF + 0.1 µF hot-loop bodge caps (B4)** |
| `N_OBT` (BT boost output) | **40.1 µF** | 30 µF derated + 10.1 µF BT bodge caps (`bench_calibration_manual.md:51`; `system_model.md`) |
| `N_BUS` | 35 µF | "30–40 µF band, midpoint": 4×10 µF RT1987 ceramics (D-FC VOUT, D-BT VOUT, D-MT VIN, D-BFC VIN) + the BUS-V divider (`boost-bringup-debug.md:49–50`) |
| `N_MOT` | 470 µF (ESR 80 mΩ) **+ VESC input 0.5 mF** (0.2–0.9 mF envelope) | BOM line 30 (CAL 470 µF 35 V Al-el, 80 mΩ) — labelled "Charging path capacitor" in the BOM but it is the **V-MOT bulk cap**, explicitly *not* on VBUS. VESC input capacitance is `--vesc-cap-uf`, **`TODO(verify)`** (OQ-11) |
| `N_CHG` | 10 µF | **`TODO(verify)`** — no separate cap identified on the schematic |
| `N_RGN` | — | **RETIRED** as a physical node (2026-08-30 topology fix): the regen node *is* `N_MOT`. The 10 µF `C_RGN_NODE` entry survives in `tools/hil_electrical.py` only to pad the retired index and keep the matrix dimensions stable; do not instantiate a separate capacitor in PSCAD |
| `R_BUS_BLEED` (not a capacitance — the discharge path across `N_BUS`) | 2000 Ω → `τ = 0.07 s` at 35 µF | `hil_electrical.py`, **`TODO(verify)`**, simulator-only. Without it a dark bus never discharges and both the snapshot state and the State-99 teardown are unphysical |

Other BOM capacitance not broken out as separate nodes, but present on the board and worth
having in T2-FAST: boost input 10 µF + 0.1 µF + 2.2 µF per channel (BOM 3–5); the RT1987 set
C-D 10 µF ×9 (line 78), C-DC 1000 pF ×6 (line 79, CAP-pin timing), C-DS 5600 pF ×6 (line 80,
as-designed soft-start), C-D6/7/9 10 µF ×3 (line 81); 5 V rail CIN-5V 10 µF and CO-5V 10 µF
tantalum (lines 26–27).

> **ORCHESTRATOR REVIEW: FC boost-output capacitance — brief overrides plan.** The
> architecture plan's addendum carries "C_O 3×22 µF (30 µF derated / 40.1 µF BT with bodge
> caps)", i.e. FC without the bodge caps — matching `hil_electrical.py`'s
> `C_BOOST_OUT_FC = 30e-6` / `C_BOOST_OUT_BT = 40.1e-6`. Research brief 2 §3 flags this as an
> **un-updated model asymmetry, not a real hardware asymmetry**: `boost-bringup-debug.md`
> (lines 1154, 1159, 1615, 1623 — operator corrections 2026-08-11) says **both** boosts carry
> hot-loop bodge caps, and brief 5 row B4 records the FC part as CONFIRMED-by-correction (fit
> date unrecorded, OQ-5). Per the writing brief, the research brief wins: **this document
> specifies 40.1 µF on both channels** and flags the divergence from `hil_electrical.py`. A
> PSCAD-vs-HIL comparison of any fast FC-node transient will therefore differ from the Python
> engine by ~34 % of node capacitance until `hil_electrical.py` is reconciled. Logged as OQ-15.

#### PSCAD realization notes

- One capacitor per node on the electrical canvas, each a project parameter. `N_OFC` / `N_OBT`
  must be **the same number** as §4.3's as-fitted `C_O` — they are the same physical
  capacitance, and letting them drift apart is how the H2-class error (a stale acceptance gate)
  reappears.
- `N_MOT` is two elements, not one: the 470 µF electrolytic **with its 80 mΩ ESR as an explicit
  series resistor**, and the VESC input capacitance as a separate parameterized capacitor so
  the 0.2–0.9 mF envelope can be swept (it sets the `scp-inrush` margin directly).
- Model `R_BUS_BLEED` as a real resistor to ground on `N_BUS`.
- **ESR/ESL: T2-FAST only.** In T2-SYS, adding ESR/ESL to every node buys nothing at a
  0.5–5 µs timestep and costs conditioning. In T2-FAST it is mandatory — the electrolytic's
  ESR and the ceramics' ESL set the hot-plug edge and the ring damping.
  **`TODO(verify)`: no ESL value for any part on this board exists in the repo**; take them
  from the part datasheets and record them in the project. Until then, T2-FAST damping is
  assumed, which is why §6.2 Tier C acceptance is qualitative.

### 4.10 Parasitic inductances (T2-FAST only)

FastHenry extraction from the as-manufactured **long-trace** output loops
(`papers/Droop_Control/sections/05_bringup_debugging.tex`, Table `Lsweep`):

| Path | Geometry | Mesh pitch | Extracted `L` | Analytic bound | Loop length | Effective width |
|---|---|---|---|---|---|---|
| Fuel cell | *as-manufactured, **PRE-BODGE** routing — for the record only* | 0.3 mm | **1.538 nH** | 1.456 nH | 4.74 mm | 12.47 mm |
| Battery | *as-manufactured, **PRE-BODGE** routing — for the record only* | 0.2 mm | **3.480 nH** | 3.149 nH | 9.69 mm | 5.91 mm |
| Either channel | **as-fitted (post-bodge, hot-loop caps B4)** | — | **no extraction exists** | — | — | — |

Both extracted rows describe the board *before* the hot-loop bodge caps collapsed the loop
(B4). Neither is the as-fitted geometry — the same "for the record only" status as §4.3's
pre-bodge 27.4 kΩ compensator row. **The as-fitted loop has never been extracted** (OQ-18).

Pipeline: `tools/inductance/gerber_inductance.py` (Gerber + Excellon → copper masks →
FastHenry deck → L(f)), configs `config_vout_fc.json` / `_altclosure` / `config_vout_bt.json` /
`_altclosure`; `sweep_inductance.py` for mesh-pitch convergence; `analytic.py` for the
closed-form microstrip bound.

`hil_electrical.py` carries two sets:

```
TRACE_L_NH = { "long":  {FC: 1.538, BT: 3.480, OTHER: 2.5},
               "short": {FC: 1.5,   BT: 1.5,   OTHER: 1.5} }     # short: TODO(verify)
DI_DT_LOAD_DUMP = 1.3e9   # A/s, from the Death-5 analysis
```

> **⚠ Two of those numbers are placeholders, not extractions.** The `"short"` set (post-bodge,
> after the hot-loop caps collapsed the loop) has **no FastHenry extraction at all** and is the
> engine's *default*. `OTHER = 2.5 nH` is an unexplained placeholder in both sets. Only the two
> `"long"` FC/BT values are extracted. See OQ-18. A T2-FAST ring study run on the `"short"` set
> is a study of an assumed inductance.

**What PSCAD adds here.** `hil_electrical.py` does not integrate the ring: it raises an
analytic event on every switch opening, `V_peak ≈ V_node + L*di/dt` at a **fixed worst-case**
`di/dt` of 1.3 A/ns regardless of the actual cut current — explicitly to be read as "at least
this bad" — and compares to `V_ABSMAX = 20.0 V` to flag the Death-5 signature. The verdict is
plausibility-gated on `v_node ≤ V_ABSMAX` at the cut (the H1 review fix). **PSCAD can simulate
the ring instead of estimating it**, with the actual commutated current and the actual damping,
and that is one of the two things T2-FAST is for.

#### Which capacitance rings — and therefore what timestep is needed

> **⚠ The repo's "nH–µF ≈ 100 MHz" shorthand does not survive arithmetic, and this document
> previously repeated it.** With `f = 1/(2*pi*sqrt(L*C))` and the doc's own numbers:
>
> ```
> 1.538 nH against N_OFC's 40.1 uF  ->  641 kHz     (30 uF pre-bodge -> 741 kHz)
> 3.480 nH against N_OBT's 40.1 uF  ->  426 kHz
> ```
>
> **The extracted hot-loop inductances against the ceramic bank ring at 0.43–0.64 MHz
> as-fitted (0.74 MHz at the pre-bodge 30 µF), not 100 MHz** — and at 100 MHz a µF-class
> ceramic bank is inductive anyway, so it is not the resonating element. A 100 MHz ring against
> 1.5 nH needs `C ≈ 1.69 nF`; 100–300 pF of switch-node capacitance puts it at **240–410 MHz**.
> Whatever rings up there is the **switch-node parasitic** — MOSFET `C_oss` plus package and
> board capacitance — not the output bank.

This splits T2-FAST's fast studies into two, with very different costs:

| Study | Ringing elements | `f_ring` | Timestep | Status |
|---|---|---|---|---|
| **Output-loop ring** (the Death-5 hot-plug / load-dump edge) | extracted `L` (1.538 / 3.480 nH pre-bodge, as-fitted unextracted) against `C_O` = 40.1 µF | **0.43–0.64 MHz** as-fitted (1.6–2.3 µs period; 0.74 MHz pre-bodge) | **20 ns** gives 67–117 samples per cycle — ample. The earlier 0.2–2 ns tier was ~100× pessimistic for this study | Inductance assumed (OQ-18); frequency arithmetic sound |
| **Switch-node ring** | switch-node loop `L` × `C_oss` + package + board | **240–410 MHz** class (at 100–300 pF against 1.5 nH) | 1–2 ns bounds the **peak** (2.5–10 samples/cycle); **0.2–0.5 ns** for waveform shape | **`C_ring` = `TODO(verify)`** — take `C_oss` and the switch-node loop inductance from `TPS61288LRQQR.pdf` and the layout; **neither exists anywhere in the repo** (OQ-21). Do not run this study on a guessed capacitance |

At 1–2 ns the ring's **damping** is set by the ESR/ESL values §4.9 admits do not exist in the
repo either, so a switch-node waveform is doubly assumed: assumed capacitance, assumed damping.
Bound the peak; do not quote a shape.

Run cost: a 1 ms window at 1 ns is 10⁶ timesteps. Keep these runs to sub-millisecond windows
around a single event and use snapshots to get there (§4.1).

The **analytic `V_peak ≈ V_node + L*di/dt` estimate is independent of `C`** and is unaffected by
all of the above — `1.3e9 A/s × 1.538 nH = 2.0 V` on FC and `× 3.480 nH = 4.5 V` on BT, which
is the arithmetic behind "at 15 A even FC's 40 mil hot loop rings past 20 V abs-max". That
bound stands whether or not the ring frequency is ever pinned down.

#### PSCAD realization notes

- Series inductors in the boost output loops, as project parameters, with a two-state switch
  selecting the `"long"` (pre-bodge, extracted) or `"short"` (post-bodge, **assumed**) set.
  Label the selector so nobody reads a `"short"`-set result as measured.
- Parasitics belong to **T2-FAST only**. Adding nH-class inductors to a T2-SYS model at a
  0.5–5 µs step adds a resonance far above Nyquist and will produce chatter, not physics
  (§4.1's trapezoidal note).
- Give the switch-node its own voltage output channel and a running-maximum block, so a ring
  peak can be compared against `V_ABSMAX = 20.0 V` directly rather than reconstructed from a
  plot.
- Keep the analytic `V_peak ≈ V_node + L*di/dt` estimate as a parallel control-page channel
  even in T2-FAST. It costs nothing, and having the simulated peak and the Python engine's
  bound side by side is the whole point of building the third model (§1.2).

### 4.11 Ag105 charger — stub

**v1 of Tier 2 stubs the charger**, mirroring the repo's own fidelity choice: the HIL engines
model it at **status level only** — no SOC coupling, no CV taper, no MPPT perturb-and-observe
loop, no I2C transport.

Model: a power-gated current sink at `N_CHG`, first-order ramp to its ceiling.

```
powered  = FC_CHARGE_ENABLE  OR  (REGEN_ENABLE AND MOT_PWR_ENABLE)      # chargerHasPower()
if powered and V_chg > AG105_V_IN_MIN:  I_charge -> AG105_I_MAX with time constant AG105_TAU_S
else:                                   I_charge -> 0, configuration flag re-arms
```

| Constant | Value | Meaning / units | Provenance |
|---|---|---|---|
| `AG105_I_MAX` | 2.5 A | Configured ceiling (`reg 0x00 = 0x01`) | `Ag105_Table4_Charge_Current_Select.json`; `.ino` `AG105_VAL_2500MA` |
| Charge voltage select | `reg 0x01 = 0x08` → 2S / 8.4 V | Must be written or the pack is undercharged (default is 4.2 V / 1000 mA) | `Ag105_Table3_Charge_Voltage_Select.json` |
| I2C address | 0x30 | | `.ino` |
| `AG105_SETTLE_MS` | 500 ms | Bring-up window before lazy configuration | `.ino`, **`TODO(calibrate)`** |
| `AG105_TAU_S` | 0.4 s | Current ramp time constant | `hil_electrical.py`, **simulator-only, `TODO(verify)`** |
| `AG105_V_IN_MIN` | 8.0 V | Input floor below which no charging | ibid., **simulator-only, `TODO(verify)`** |
| `MPPT_DISABLE` polarity | **active-LOW** (LOW inhibits the P&O loop) | LOW at init and during regen; HIGH only when `chargerReady` | Confirmed from the PCB schematic; `.ino` §3 |

#### PSCAD realization notes

- One controlled current sink at `N_CHG` behind a first-order lag (`AG105_TAU_S`), gated by a
  control-page AND/OR of the two switch states plus the `V_chg > AG105_V_IN_MIN` test. No
  electrical model of the module, and no I2C — the register writes are firmware behaviour, not
  circuit behaviour, and the PSCAD project has no firmware in it.
- Emit `I_charge` and, if you want §6.1 completeness, a synthesized `ag105_status` byte from
  the Table-6 codes so the CSV column has something in it. Both are stub outputs; label them.
- The `MPPT_DISABLE` line is an **input** to this stub and changes nothing in it (the P&O loop
  is not modelled). Carry it as a logged aux bit only, so a scenario driver's sequencing is
  visible in the output.

**Why full MPPT dynamics are out of scope:** the Ag105 is slow and secondary; the TL431/BSP170P
chopper is the fast clamp and is not under firmware control. More decisively, **there is no
data to validate a charger model against** — the charger was confirmed *unpowered* in every
State-98 run in the logs (`V_chg = 0`; no charger path was ever opened), so no charger-path
transient has ever been recorded on this board.

---

## 5. Experiment T2-X1 — the droop realization audit

This is the reason Tier 2 has a component-level droop chain. It is a first-class experiment,
not a check.

### 5.1 The question

The MDAC droop chain predicts a per-channel Thevenin resistance
`Re = RE_MAX * g = 2.014 * 0.298 = 0.60 Ω`, i.e. **0.30 V/A** with both channels sharing. The
bench measures **0.074 ± 0.004 V/A**. `docs/HIL_PLANT.md` §4.2: *"four times the measured
0.074 V/A. Nothing in the repo explains the gap yet."*

The two Python engines straddle it: the simple engine **uses** the measured number as a
constant; the hi-fi engine **derives** its droop from FB-node superposition and therefore
reproduces the design number. Neither engine can discriminate, because neither contains a
mechanism that could be wrong in the required direction — the hi-fi engine's superposition is
the design algebra.

A PSCAD model with the real resistor network, a real amplifier with a real rail, and a real
load path **can** be wrong in interesting ways, which is the point.

### 5.2 Measurement protocol (mirror the bench methodology exactly)

The bench number came from regressing `V_bus` against `I_fc + I_batt` over **quasi-steady
200 ms blocks** of TP0170–0180 (TP0178 excluded — it is the handoff-sag log), plus ML0165 and
ML0169, all fw v16 (`HIL_PLANT.md` §4.2). Reproduce that, not something cleaner:

1. Run T2-SYS with the component droop chain, both sources live, the share loop closed.
2. Sweep `share_sp` over the same 11 points at a comparable `I_tot` — the bench dataset held
   `I_tot ≈ 0.72 A` at a 6 A trapezoid.
3. Export at 1 kHz (§6.3). Chop into 200 ms quasi-steady blocks. Regress `V_bus` on `I_tot`.
4. Repeat with exactly one source live for the single-source slope.
5. Report: slope shared, slope single, intercept `V0`, and the mode ratio.

> **⚠ Regress against the SENSE-CHAIN current, not a branch ammeter.** The bench number is
> `dV_bus / d(I_fc + I_batt)` where both currents are the **firmware-reported** values,
> i.e. `V_INA / K_sns_fw` (`.ino:1161`). That is not the same measurement as a true branch
> ammeter, and the difference is exactly what makes the sense-gain cancellation of §5.3 work.
> A PSCAD run regressed against ideal ammeters is measuring a different quantity and will not
> be comparable. Export both, and label which column is which (§6.1).

**Two fit-set caveats.** (i) The bench fit set is TP0170–0180 (TP0178 excluded) **plus ML0165
and ML0169**; the protocol above reproduces only the TP sweep and silently drops the two ML
runs. Say so when reporting. (ii) ML0165's own contribution is now known to be problematic —
see candidate (f) and OQ-22.

**Also run the clean version** (a slow deliberate load ramp, no share activity) and report
both. If the two disagree, the measurement methodology is a live candidate (§5.3(d)) and that
alone is a result.

### 5.3 The candidate causes, and how to attack each

Research brief 5 OQ-9 listed four undiscriminated candidates: **component tolerance stack**,
**OPA197 headroom clipping**, **load-path effects**, and a **measurement-methodology artifact**.
This document adds two — **(e) injection attenuation** and **(f) was the droop chain actually
commanded** — and **closes one whole class on paper**, below, before any PSCAD workspace exists.

**Run order:** (f) is already done (results below). Then **(e) first**, then (d), then (a), (b),
(c).

#### CLOSED — no sense-gain error, in the part or in the firmware constant, can produce this gap

The measured slope is `dV_bus / dI` where `I` is the **firmware-reported** `I_fc + I_batt`.
The droop injection and the reported current are taken from the **same INA253 output**, so the
part's true gain cancels. Let `S` be the true part transimpedance (V/A) and `K_sns_fw` the
firmware constant:

```
I_reported = V_INA / K_sns_fw = (S / K_sns_fw) * I_true          # .ino:1161, SCALE_I
Re_true    = S * A_v * (R_D1/R_inj) * g                          # the physical droop
g          = K_DROOP / (RE_MAX * rc),  RE_MAX = K_sns_fw*A_v*(R_D1/R_inj)   # .ino:1875

dV_bus/dI_reported = Re_true / (S/K_sns_fw)
                   = K_sns_fw * A_v * (R_D1/R_inj) * g
                   = K_DROOP / rc                                # S has cancelled exactly
```

**`S` disappears.** The measured V/A slope is independent of which INA253 variant is fitted
**and** of the value the firmware carries for `K_sns` — it is pinned to `K_DROOP = 0.30 Ω` by
construction, because the same constant divides the reported current and multiplies the
commanded gain. No sense-gain error of any size or sign can move it.

> **ORCHESTRATOR REVIEW — this replaces the A3/A1 hypothesis, which was wrong.** An earlier
> draft flagged the INA253A3→A1 substitution (`0.4/0.1 = 4.0`, bodge B6) as a numerical
> coincidence worth testing first. The algebra above shows it is not merely unproven but
> **self-cancelling**, and the proposed discriminating experiment had the wrong sign: setting
> the *part* gain to 0.4 V/A while the firmware keeps 0.1 leaves the reported-current slope at
> 0.30 V/A, and moves the *true-ammeter* slope to **1.2 V/A — 4× ABOVE design**, not below it.
> A1 is also the lowest-gain variant, so a substitution error could only ever make realized
> droop larger. **This is a genuine free narrowing of OQ-9:** an entire candidate class is
> eliminated on paper, at no bench cost, and OQ-12's PDF discrepancy is confirmed harmless to
> the measurement (it remains a documentation hazard for anyone building a model from the PDF).
> The residual `A_v`, `R_D1/R_inj` and `V_ref` terms do **not** cancel and stay in candidate (a).

*PSCAD consequence:* the model must reproduce this structure to be comparable — compute the
exported `I_fc`/`I_batt` from the sense chain (`V_INA / K_sns_fw`), not from branch ammeters
(§5.2). Export both and check that they differ only when you deliberately mis-set `S`.

#### (e) Injection attenuation `R_D1/R_inj` — the ×4 that actually lands. **First sweep.**

The FB injection attenuation is `R_D1/R_inj = 215/53.6 = 4.011`, and:

```
0.30 / 4.011 = 0.0748 V/A     vs measured 0.074 +/- 0.004 V/A
```

That is inside the error bar. Three things make it the leading candidate rather than a
curiosity:

1. It lives in **exactly the network T2-X1 builds** — the FB node superposition, not a
   downstream effect.
2. It **does not cancel.** From the algebra above,
   `dV_bus/dI_reported = (K_DROOP/rc) * (R_D1/R_inj)_true / (R_D1/R_inj)_fw` — so any mechanism
   that makes the *realized* injection see the attenuation once more than the firmware's
   constant assumes lands on 0.0748 V/A exactly.
3. **This factor has documented history of being dropped in this chain.** The retired `k_eq`
   defect (`.ino:78`) *"omitted the FB injection attenuation `R_D1/R_inj`"* — the identical
   error, in the identical place, in shipped firmware.

*Attack, and run it first:* sweep `R_inj` and `R_D1` **independently over ±4×** with the
Multiple Run component (i.e. `R_inj` up to ~215 kΩ, `R_D1` down to ~54 kΩ), and record the
realized bus slope at each point. Check whether any physically-plausible pair — a wrong fitted
resistor, an unmodelled parallel path at the FB top node, an op-amp output impedance in series
with `R_inj` — produces 0.074 V/A.

> **State this as a numerical coincidence with precedent, not as a root cause.** 0.0748 landing
> inside a ±0.004 bar is suggestive; it is not a mechanism. Nothing here identifies a physical
> reason the attenuation would be applied twice, and until the sweep produces a plausible
> component value that does it, candidate (e) is a hypothesis like the others — just the one
> worth testing first.

#### (f) Was the droop chain actually commanded during the fit runs? — **partially resolved**

If any log contributing to the fit ran at frozen or zero MDAC gain, the fit is measuring
parasitic and source impedance, not commanded droop. The BLG carries `gFC`/`gBT` directly, so
this is decidable from `logs/` at no cost — and it has been checked.

> **Audit result (2026-08-30), from the logged `gFC`/`gBT` columns:**
> - **ML0165** ran `gFC = gBT = 0.0000` for its entire **33,835 rows** — **zero commanded
>   droop**, and it was **included in the fit**.
> - **ML0169** and **TP0170** ran `g = 0.298` on both channels throughout — open-loop
>   feedforward at exactly the design gain.
> - **TP0174** shows live closed-loop variation (`gFC` 0.31–0.51, `gBT` 0.21–0.28).
>
> **The ×4 finding SURVIVES on the TP logs**: droop was commanded at the design gain and the
> board still realized roughly four times less. ML0165's inclusion is a **methodology footnote**
> for operator review, not a refutation — logged as **OQ-22**. No re-fit slope is quoted here;
> re-fitting is the operator's call, not this document's.

*PSCAD consequence:* when reproducing the protocol, log the commanded `g` alongside the
realized slope for every block, and discard blocks where `g` is not what you think it is. The
bench had no such check; the model should.

#### (a) Tolerance stack — `A_v`, `R_D1`, `R_D2`, `R_inj`, `V_ref` (`K_sns` removed, see above)

*Attack:* make the surviving constants project parameters and drive a **Multiple Run** sweep,
or a Monte-Carlo run set, over their tolerance bands. `V_ref` ±2 % (0.588–0.612 V) is the one
band actually documented; resistor tolerances are `TODO(verify)` — read them off the BOM before
running.
*Discriminating prediction:* the realized slope is **linear** in each of `A_v` and
`R_D1/R_inj`, so a ×4 error needs the product off by ×4. 1 % resistors cannot do that; only a
gross wrong-value fit can, which is what candidate (e) sweeps at ±4×. Expect (a) to **fail to
explain the gap** — its value is in bounding how much of it tolerance *can* account for
(a few percent), which sharpens everything else.

#### (b) OPA197 headroom clipping

*Attack:* add a dedicated output channel on `V_op` for each channel, with the 4.9 V ceiling
drawn on the graph, and a "clipped" logic flag integrated over the run.
*Prediction:* headroom is computed non-binding for `g*I ≤ 9.8 A`, and the bench dataset ran at
`I_tot ≈ 0.72 A` — so clipping should **not** be reachable in the TP0170–0180 conditions. If
the PSCAD monitor shows clipping there, either the headroom arithmetic or the 5 V rail
assumption (bodge B5, as-designed rail unknown — OQ-3) is wrong. Sweep the rail (3.3 / 5 V) to
see how much droop authority the bodge actually bought.

#### (c) Load-path effects — right conclusion, and the correct circuit segment

The segment that matters is **between each channel's FB sense node (the boost output node) and
the bus measurement node** — i.e. **D-FC's and D-BT's `R_ON` = 21 mΩ plus their 35 mV forward
servo**. It is **not** D-MT's `R_ON`: resistance *downstream* of the measurement node lies
outside the measured `dV_bus/dI` pair entirely and affects the steady-state slope not at all.

*Direction, and the sharpening it produces:* the two channel switches add ≈ **10.5 mΩ**
combined in series with the electronic droop, so the measured 0.074 V/A is an **upper bound**
on the true electronic droop, which is ≈ **0.0635 V/A**. The gap is therefore marginally
**larger** than ×4 — `0.30/0.0635 = 4.72` shared, and `0.60/0.1405 = 4.27` single-source.
Load-path resistance can only ever make the apparent droop bigger, so **this candidate cannot
explain the gap in the required direction.** Confirm that in the model rather than assuming it,
and use the corrected 0.0635 figure as the target the other candidates must reach.

*Also worth running:* single-source vs both-source, and with/without the motor node connected,
as a structural check that the model's measurement segment is the same one the bench used.

#### (d) Measurement-methodology artifact

*Attack:* the §5.2 dual protocol. Feed the PSCAD run through the *same* 200 ms quasi-steady
block regression, and separately through a clean ramp. If a share loop that is actively moving
the droop ratio during the "quasi-steady" blocks biases the regression, the PSCAD run will show
it, because in PSCAD the true `Re` is known exactly at every instant while the regression is
being computed. **This is the one candidate PSCAD can settle outright** — run it second, after
the (e) sweep. Candidate (f)'s audit already establishes that at least one fit log carried zero
commanded droop, which makes a methodology contribution demonstrably nonzero; (d) bounds it.

### 5.4 Acceptance

T2-X1 succeeds if it produces **any** of:

- A reproduction of ~0.074 V/A (or the `R_ON`-corrected 0.0635 V/A electronic figure) from
  component values, with the responsible mechanism identified. (Best outcome.)
- A demonstration that the measured number is a regression artifact of the share-sweep
  methodology. (Second best; retires the finding.)
- A clean refutation of every surviving candidate — i.e. a PSCAD model that stubbornly produces
  0.30 V/A under every perturbation within the documented tolerance bands. That narrows the
  search to something *outside* the modelled chain and is a genuine result. (Third; still
  useful.)

The sense-gain class is **already** eliminated, on paper, before the workspace exists — that
much of OQ-9 is closed regardless of what the model does.

It fails only if the model is built such that the droop is configured rather than derived —
which is why §4.4 forbids implementing the droop law on the control page.

**Whatever the outcome: do not update `K_DROOP_BUS_*` in `tools/hil_plant_sim.py` on the
strength of a PSCAD result.** Those are measured constants; PSCAD sits below bench measurement
in the §1.3 order of trust. A PSCAD result is a hypothesis to take to the bench.

---

## 6. Validation against HIL and bench data

### 6.1 Signal mapping

PSCAD output channels ↔ existing data streams. **Decimate PSCAD output to 1 kHz** — both the
HIL observation frame and the BLG bench record are 1 kHz, and the hi-fi engine's ~20–40 kHz
substepping is likewise reported back into a 1 kHz frame (`HIL_PLANT.md` §8.1).

| PSCAD channel | HIL CSV column | BLG field | Units | Notes |
|---|---|---|---|---|
| `t` | `t` | derived from record index | s | HIL/BLG `t` is **session-absolute** — for a rate, divide by `t[-1]-t[0]`, never by `t[-1]` |
| — | `seq` | — | u8 | Frame sequence counter. **No PSCAD analogue** — it is a link-integrity field, not a plant quantity. Emit a constant or leave the column empty; do not synthesize a fake one |
| `V_fc` | `V_fc` | `V_fc` (v3+) | V | FC source terminal |
| `V_batt` | `V_batt` | `V_batt` (v3+) | V | Pack terminal |
| `V_bus` | `V_bus` | `V_bus` | V | `N_BUS` |
| `V_chg` | `V_chg` | `V_chg` (v3+) | V | `N_CHG` |
| `V_rgn` | `V_rgn` | `V_rgn` (v3+) | V | `N_MOT` — the `RGN-V` divider sits on V-MOT, upstream of the REGEN switch (2026-08-30 topology fix); there is no separate `N_RGN` |
| `I_fc` | `I_fc` | `I_fc` | A | Bus-side FC branch current. **Compute this from the sense chain** (`V_INA/K_sns_fw`), as the firmware does — not from a branch ammeter. The difference is load-bearing for the droop fit (§5.2, §5.3) |
| `I_batt` | `I_batt` | `I_batt` | A | Bus-side BT branch current, same rule |
| `pscad_I_fc_true` / `pscad_I_bt_true` | — | — | A | The branch **ammeter** currents. PSCAD-only; export alongside so the two can be differenced |
| `mdac_fc` / `mdac_bt` | `mdac_fc` / `mdac_bt` | `gFC` / `gBT` | raw 16-bit word / fraction | HIL logs the **raw AD5443 word**; convert with `(word & 0x0FFF)/4095` after validating the `0x1000` nibble. BLG `gFC`/`gBT` are the gain commands |
| `switch` | `switch` | — | bitmask | `SW_FC_BUS 0x01`, `SW_BT_BUS 0x02`, `SW_MOT_PWR 0x04`, `SW_REGEN 0x08`, `SW_FC_CHARGE 0x10`, `SW_BT_SEQ 0x20` |
| `aux` | `aux` | — | bitmask | bit0 `FC_REG_ENABLE`, bit1 `BT_REG_ENABLE`, bit2 `MPPT_DISABLE`, bit3 `CBAL_DISABLE` |
| `current` | `current` | `I_cmd` | A | Post-clamp motor current command |
| `v_actual` | `v_actual` | `v_act` | m/s | Flywheel **surface** speed — there is no separate vehicle-speed scale |
| `I_charge` | `I_charge` | — | A | Ag105 stub output (§4.11) |
| `ag105_status` | `ag105_status` | — | u8 | Raw Ag105 Table-6 status byte. Only if the §4.11 stub synthesizes one; otherwise emit 0x00 and label it unmodelled |
| `state` | `state` | `ps_phase` (different meaning) | enum | Firmware main state; PSCAD's is the scenario driver's state |
| `fault_flags` | `fault_flags` | `fault_flags` (v3+) | u16 | Only if the PSCAD project models the firmware's fault logic (§6.4) |
| — | `soc` (simulated runs only) | — | 0–1 | Battery SOC |
| — | `elec_substep_hz`, `elec_events` (hifi only) | — | — | No PSCAD analogue; PSCAD's timestep is fixed |
| `pscad_*` | — | — | — | **Prefix every PSCAD-only channel** (`pscad_V_op_fc`, `pscad_Re_fc`, `pscad_ring_peak`, ...) so a comparison script can select the shared columns by name |

The 16-byte HIL observation frame (`0xB6`) carries `seq`, `mainState`, `switch_state`, aux pins,
post-clamp `current`, both MDAC words and `fault_flags` — i.e. the actuator side. The 40-byte
injection frame (`0xB5`) carries the 7 rails + `v_actual` + `I_charge` + the raw Ag105 status
byte. A PSCAD run corresponds to the **plant** half: it produces what the injection frame
carries and consumes what the observation frame carries.

### 6.2 Scenario correspondence and acceptance bands

Work in this order: **steady state first, transients second, T2-FAST scope comparisons last.**
A model that gets a transient right while getting `V0` wrong is fitting noise.

#### Tier A — steady state (do these first)

| Target | Source | PSCAD run | Acceptance |
|---|---|---|---|
| No-load bus `V0` | Measured 15.95 V (fits 15.943–15.957); design 15.907–15.91 V | T2-SYS, both sources, no load, `g` from the firmware mapping | Within ±0.05 V of the design number **from the resistor network**, and report the delta to 15.95 |
| Combined droop slope | 0.074 ± 0.004 V/A (TP0170–0180 excl. TP0178, ML0165, ML0169, fw v16) | T2-X1 §5.2 | **This is the open finding — report, do not tune to match** |
| Single-source droop slope | 0.1615 ± 0.001 V/A | T2-X1 §5.2, one source | ditto; also report the mode ratio against 2.00 |
| Share tracking at `sp = 0.5` | 0.503 ± 0.028 | T2-SYS, share loop closed, `I_tot` above the 0.60 A gate | Mean within ±0.01; spread will be smaller than bench (no sensor noise modelled) |
| Governor clip bands | [0.4167, 0.5833] at `I_tot = 0.72 A` | Sweep `share_sp` across both rails | Exact — it is arithmetic, `[0.30/I_tot, 1-0.30/I_tot]` |
| HIL `steady` | quiescent baseline (H1) | T2-SYS idle | Bus, currents and switch states match |
| HIL `step-load` | +1.2 A aux step at t = 5 s | T2-SYS step | Sag = `k * 1.2 A`: **0.089 V** at the shared slope, **0.194 V** at the single slope. Whichever `k` the model realizes must produce the matching sag — this is the same measurement as the droop slope, seen as a transient |

#### Tier B — transients

| Target | Source | PSCAD run | Acceptance |
|---|---|---|---|
| **TP0178 handoff sag** | `share_sp = 0.85` (governor-clipped ≈ 0.60), FC sourcing 100 % (~0.55–0.65 A). At t ≈ 7.484 s `I_fc` steps to 0 while `V_fc` steps **8.12 → 8.68 V** in the same sample. `V_bus` decays **15.34 → 12.149 V min** over ~6 ms; `I_batt` recovers with overshoot 0.67 → 1.74 A; total ~10 ms; **no fault** (0.15 V above `LIMIT_V_BUS_MIN`, < 20 ms dwell). **Units:** the "~6 A" in the source record is `I_cmd`, **motor-side**; the bus-side event is a **0.7 A source dropout** under that motor draw (`boost-bringup-debug.md:1389–1390, 1407) | T2-SYS: drive the share ratio across an FC↔BT conduction crossing with BT as a dark standby, RT1987 models live | Sag **depth** within ±0.3 V and **duration** within ±3 ms. The `V_fc` **rise** at dropout is the signature that must reproduce. **Plus the deliverable below** |
| **TP0201** | Same class: 15.86 → **12.185 V**, ~5.7 ms | ditto | ditto |
| **TP0178/TP0201 root cause — the model must get this right** | The "looser FC supply" hypothesis was **REFUTED** (2026-08-25). `V_fc` *rising* at dropout means the boost stopped drawing, which a sagging supply cannot cause. Root cause is architectural: **dark-standby reactive pickup** — the standby RT1987 closes only after the sag forward-biases it | Verify by running the same scenario with a **stiff** FC supply: the sag must still occur | If the model only reproduces the sag with a loose supply, the model has the wrong mechanism |
| HIL `handoff-sag` (hi-fi only) | Share driven to a rail so one source darkens | T2-SYS | Same shape as TP0178/TP0201 |
| HIL `bringup` (hi-fi only) | Staged P0–P3 against `t_D_ON` 8 ms + soft-start ramps | T2-SYS with the sequencing harness | 8 ms delay + 19.8 ms / 1.07 ms ramps visible and correctly ordered |
| HIL `scp-inrush` (hi-fi only) | RT1987 soft-start foldback margin on `MOT_PWR` into the VESC input envelope (0.9 mF) | T2-SYS | Margin holds at 2 A V-MOT draw; breaks at ≥ 4 A into 64 ms burst-retry |
| HIL `sag` | −5 V bus offset for 1 s at t = 5 s — the *real* UV path (H2) | T2-SYS | **Note the asymmetry:** in the hi-fi engine this is a **sensor-path injection** (`v_bus_sense_offset`), not a plant event. In PSCAD you can stamp it as a real plant event; say which you did |
| HIL `soc-depletion` | Battery-heavy load, coulomb-counted OCV walk toward UV_BATT | T2-SYS, vehicle-source configuration | Shape only — the OCV table is generic (§4.2) |
| HIL `charge-cruise` / `charge-regen` / `charge-fault` | Charger path sequencing and REGEN⇄FC_CHARGE exclusion | T2-SYS with the §4.11 stub | Sequencing and gating only; **no charger-energy claim** |
| HIL `comm-loss` | 1 s transmit gap, hold-then-zero staging (H3) | No PSCAD analogue | Skip — this is a link-layer test |
| HIL `drive` | Operator USB commands (H4) | No PSCAD analogue | Skip |
| HIL `ems-drive-cycle` | 58 s drive cycle under the `hold-5050` EMS (share 0.5), 8-point `v_setpoint` profile (`SCENARIOS["ems-drive-cycle"]` in `tools/hil_plant_sim.py`; duration trimmed 60 -> 58 s on 2026-08-30 — `EMS_RUN_EXIT_S` is 55.0 s, so 58 s is the exit plus ~3 s for Run -> Finish -> Idle; see the RESOLVED OQ-14 note below) | T2-SYS, vehicle-source configuration, motor load driven by the same profile | Bus/current traces through accel–cruise–step–decel; the two cruise levels give two incremental `dV_bus/dI` datapoints in one run; deceleration is gentler than coast, so **no regen entry is expected** — flag it if the model produces one |

> **⚠ TP0178's 6 ms does not close against this document's own `C_BUS`, and identifying what
> carries the bus through the gap is an explicit deliverable of the run.** A 0.7 A net deficit
> into `C_BUS` = 35 µF drains 3.19 V in
> `35e-6 * 3.19 / 0.7 = 160 us` — **not 6 ms, ~37× too fast**. Inverting the observation
> instead: sustaining 3.19 V over 6 ms needs either a **net deficit of only
> `35e-6 * 3.19/6e-3 = 19 mA`**, or an **effective capacitance of
> `0.7 * 6e-3 / 3.19 = 1.3 mF`**. Something supports the bus for those 6 ms. The two leading
> candidates demand **opposite** things of the model:
> - **`N_MOT` reservoir back-feeding the bus** — the ~1 mF on the motor node (470 µF + VESC
>   input) minus the motor's own draw. This requires D-MT to **stay closed** and its reverse
>   comparator (0.5 µs typ) *not* to isolate — i.e. the motor draw exceeds what the reservoir
>   returns, and the net is a slow ~19 mA deficit.
> - **BT partially conducting through the gap** — the standby channel already carrying part of
>   the load, so the deficit is small from the outset.
>
> **Do not tune `C_BUS` to fit the 6 ms.** It is pinned in §4.9 from a parts count and it must
> stay pinned; making it a free parameter would silently absorb whichever mechanism is real.
> Report which element carries the bus, with its current trace, as a first-class output of the
> TP0178 run. Logged as OQ-23.

> **RESOLVED (OQ-14, verified 2026-08-30):** `ems-drive-cycle` **does exist** in the
> `SCENARIOS` registry (`tools/hil_plant_sim.py:974`) — an earlier research pass missed it.
> 60 s, `electrical: any`, driven by the `hold-5050` EMS policy (share 0.5 constant) with NO
> `pi_timeline`; piecewise-linear `v_setpoint`: standstill 0–3 s → ramp to 1.5 m/s by 10 s →
> cruise to 30 s → ramp to 2.0 m/s by 32 s → cruise to 40 s → decelerate to 0 by 52 s
> (0.167 m/s², crossing the 0.5 m/s validity floor at t = 49 s) → standstill to 60 s.
> The PSCAD equivalent is the `ems-drive-cycle` row in the Tier-B table above.

#### Tier C — T2-FAST, scope comparisons

Only where a scope capture exists. `docs/boost-bringup-debug.md` carries the numbered capture
series (capture 8 = the D-BT 100 nF validation, capture 11 = D-MT, capture 15 = the
encoder front-end analog edges). Compare T2-FAST against the *power-path* captures only.

Targets: switching ripple amplitude at `N_OFC`/`N_OBT` and how much of it reaches `V_op`; the
body-diode back-feed edge when a disabled boost is back-fed; the hot-plug edge and ring peak
against `V_ABSMAX = 20.0 V`; the SCP burst-retry envelope at 64 ms.

**Acceptance is qualitative here** and should stay that way until the `"short"` parasitic set
is actually extracted (OQ-18). A ring *peak* within a factor of ~1.5 of a scope capture, on an
assumed inductance, is as much as can be honestly claimed.

### 6.3 The CSV contract (specified now; the script is future work)

Define the export format now so that a comparison script is mechanical later.

- **File:** one CSV per PSCAD run, `pscad_<project>_<config>_<scenario>_<runid>.csv`.
- **Rate:** 1 kHz, uniformly sampled (decimate; do not export at the solution step).
- **Columns:** exactly the HIL CSV names from §6.1 for every quantity that is the same
  quantity, in the HIL order, followed by `pscad_`-prefixed extras. Do not rename, do not
  reorder — the HIL CSV's first 19 columns are explicitly **frozen**
  (`HIL_PLANT.md` §7.1: *"19 columns and is frozen; everything since is appended, never
  reordered"*), and matching that order lets one loader read both.
- **Header:** a leading comment block recording the PSCAD project, configuration
  (T2-SYS/T2-FAST), solution timestep, `V0`/`K_DROOP`/`K_sns` used, which bodge set was
  modelled, and the scenario. Provenance in the file, not in a filename.

**Future `tools/pscad/` comparison script** — the contract it should honour:

- Reuse the **replay-suite declarative check vocabulary**: `tools/hil_replay_suite.py`'s
  `CHECK_KINDS` is 8 kinds — `no_fault`, `fault_latched`, `fault_not_latched`,
  `bounded_current`, `no_sustained_rail`, `no_rail_limit_cycle`, `returns_off_rail`,
  `near_zero_current`. A PSCAD-vs-HIL check set expressed in the same vocabulary is
  reviewable by anyone who already reads the replay suite.
- Follow the **`tools/benchlog_analysis` FIGURES-registry pattern** for any comparison figure:
  write `def pscad_comparison(data, cfg): ... return fig` in `figures.py` using the shared
  `COLORS` / `_style_axes` / `_legend` / `_suptitle` helpers, then append it to the `FIGURES`
  registry. **The PyInstaller analyzer exe must be rebuilt (`build_exe.ps1`) after any registry
  change** — and note that it already carries a standing rebuild debt (`CLAUDE.md`
  housekeeping).
- Emit a `REPORT.md` + `results.json` pair in the shape `tools/run_hil_suite.py` already
  produces, including a "Known open findings" section that restates the ×4 droop discrepancy
  — that suite always restates it, and a PSCAD report that quietly dropped it would be a
  regression in honesty.

**This script does not exist. Nothing in this document depends on it.** Tier 1 and Tier 2 are
both fully usable with manual comparison.

### 6.4 Should the PSCAD model include the firmware's fault logic?

Optional, and worth it for one specific reason: the **UV leaky-dwell filter** is what decided
that TP0178 and TP0201 did *not* latch a fault, and reproducing that is a sharp check on the
timing of a modelled sag.

Mechanism (`.ino` ~1276–1301, 4614–4723): a leaky integrator accumulating `+1*dt` while under
threshold and `-0.05*dt` while above, with `dt` capped at 5 ms per tick, latching at **20 ms**
net. TP0178 (12.149 V for ~10 ms) and TP0201 (12.185 V for ~5.7 ms) both land inside it.

Relevant limits, all from `teensy_controller.ino`:

| Constant | Value | Notes |
|---|---|---|
| `V_BUS_NOMINAL` | 16.0 V | Post-`R_D1`=215k retune; `V0` = 15.91 no-load |
| `LIMIT_V_BUS_MAX` | **17.5 V** (`= nominal + 1.5`) | `docs/VESC_MOTOR_INTEGRATION.md` says 17.0 — **stale**, `.ino` is authoritative (OQ-13). TPS61288 hardware OVP is 19 V, so firmware trips first |
| `LIMIT_V_BUS_MIN` | 12.0 V | While `uvBusArmed` |
| `V_BUS_CHARGED_THRESH` | 13.5 V (`nominal - 2.5`) | Bring-up "bus up" gate |
| `BUS_CHARGE_TIMEOUT_MS` | 800 ms | Bring-up timeout |
| `UV_BUS_DWELL_LATCH_MS` | 20.0 ms | Leaky integrator, **`TODO(calibrate)`** |
| `UV_FC_DWELL_LATCH_MS` | 20.0 ms | `V_fc` UV |
| `LIMIT_I_FC_MAX` | 1.4 A bus-side | H-20 stack, 2.6 A source-side referred |
| `LIMIT_I_BT_MAX` | 3.0 A bus-side | 6.0 A VESC battery-current split evenly is exactly this — zero margin |
| `LIMIT_V_BATT_MIN` | 6.2 V | 2S cutoff |
| `LIMIT_V_BATT_MAX` | 10.0 V | **Temporary bench value**; the real 8.6 V is commented out |

---

## 7. Build order

Tier 1 is completed **in full** before Tier 2 starts. Tier 1 *is* the PSCAD course; skipping to
Tier 2 means learning PSCAD and debugging a 6-node nonlinear model at the same time.

| Stage | Content | Gate before proceeding |
|---|---|---|
| **1** | Tier 1, exercises T1-E1 → T1-E6 (§3.4) | §3.5 acceptance table, all seven rows (diode-corrected targets) |
| **2a** | T2-SYS skeleton: Tier-1 topology upgraded to the real source models (§4.2) and per-node capacitors (§4.9) | `V0` from the resistor network within ±0.05 V of 15.91 V; steady-state currents match Tier 1 |
| **2b** | RT1987 behavioral switches ×6 (§4.5) + the sequencing harness | Soft-start ramps 19.8 ms / 1.07 ms; the `bringup` staging reproduces; an illegal switch combination can be commanded and its consequence observed |
| **2c** | Component-level droop chain (§4.4) + discrete MCU controls (§4.6). **Run T2-X1 here** (§5) | §4.4's three static checks, then T2-X1 §5.4 — this is the earliest point at which the ×4 question can be attacked, which is why it is stage 2c and not later |
| **2d** | Motor/VESC load (§4.7) + regen chopper (§4.8) + Ag105 stub (§4.11); scenario matching against HIL (§6.2 Tiers A and B) | TP0178 sag depth/duration within band **with a stiff supply** |
| **2e** | T2-FAST: switching power stage (§4.3) + parasitics (§4.10) + ESR/ESL | Loop crossover within ~5 % of §4.3 **table (ii), the as-fitted one** (FC 12.6–16.8 kHz, BT 10.3–11.7 kHz derated) — landing on table (i) instead means `C_O` is stale. Then the Tier-C qualitative comparisons |

Each stage is validated before the next. The reason is not process hygiene: a droop-chain bug
at stage 2c is findable in a model whose sources and switches are already trusted, and
effectively unfindable in one where they are not.

---

## 8. Non-goals and fidelity boundaries

What these projects deliberately do **not** do:

- **No thermal modelling.** Not the boosts, not the chopper resistor (§4.8 computes steady
  dissipation, which is arithmetic, not a thermal model), not the RT1987s, not the motor. The
  `F_c` cold/warm spread (2.19 vs 1.75–1.84 N) is in the constants table as a *range*, not as a
  temperature model.
- **No EMI/EMC claims.** T2-FAST's switch-node study runs on an assumed inductance *and* an
  assumed capacitance (§4.10, OQ-18/OQ-21). That is a bounding circuit study, not an emissions
  prediction, and nothing here supports a compliance statement.
- **No reverse conduction through a disabled boost.** The §4.3 element models the
  input→output **passthrough** only. The back-feed hazard `CLAUDE.md` §2 names — VESC regen
  driving current *into* a disabled converter through its synchronous rectifier — is
  **not modelled in either direction of this document's scope**, because the TPS61288's
  sync-rectifier behaviour in shutdown appears nowhere in the repo (OQ-24). The sequencing
  rules remain a procedural protection, not something the model can be run against. This is
  the same boundary the Python engine has.
- **No Ag105 MPPT dynamics** — no perturb-and-observe loop, no CV taper, no SOC coupling, no
  I2C transport (§4.11). There is no data to validate any of it against.
- **No cell-level battery model.** One 2S terminal model with a generic OCV table
  (`TODO(calibrate)`), one RC branch, coulomb counting. No per-cell balancing, no BQ29200
  behaviour.
- **No claim about boost voltage-loop stability from T2-SYS.** That is `tps61288_full_model.py`'s
  job and T2-FAST's, after cross-check (§4.1).
- **No encoder / velocity-estimator modelling.** The drive loop's input is a commanded current
  or a replayed trace; the edge-period estimator, its adaptive filter and its diagnostics are
  out of scope entirely.
- **T2-FAST parasitics are partly assumed.** The `"short"` (post-bodge) set is `1.5 nH` flat
  with **no extraction**; `OTHER = 2.5 nH` is an unexplained placeholder. Only the two `"long"`
  (pre-bodge geometry) FastHenry values are real (§4.10). The switch-node ring capacitance is
  not in the repo at all, and neither is any ESL.
- **VESC behaviour is a behavioral overlay, not physics.** The 6.0 A forward cap, the 1.5 A
  regen clip and the ≈428 ms reversal dead window reproduce observed symptoms with no
  mechanism claim, and none of them is in the Python plant.
- **Simulator-only tuning values stay flagged.** `V_STICTION`, `R_BUS_BLEED`, `ETA_BOOST`,
  `I_AUX_A`, `R_FC_INT`/`R_BT_INT`, `AG105_TAU_S`, `AG105_V_IN_MIN`, `C_CHG_NODE` (`C_RGN_NODE`
  is retired — §4.9),
  and the `"short"` trace-L set are inherited from `hil_electrical.py` as **`TODO(verify)` /
  `TODO(calibrate)`**. Using them in PSCAD does not promote them. A PSCAD run that agrees with
  a HIL run on a quantity governed by one of these has demonstrated that two models share an
  assumption, not that the assumption is right.
- **RT1987 datasheet spread is not modelled** — all six switch models use typicals only.
- **No new measurement.** Nothing in this document was measured for it. Every number is
  restated from an existing artifact with a citation, or marked open.

---

## 9. Open questions for operator review

Standing section, per the operator's instruction that anything uncertain gets logged for
review rather than resolved silently. OQ-1 … OQ-11 are research brief 5's list; OQ-12 … OQ-19
were raised by the architecture plan or during the writing of this document; OQ-20 … OQ-24 came
out of the fidelity/correctness review round. Entries are never deleted — a resolved one is
marked **CLOSED** with its reason so the reasoning stays on record.

| # | Question | Conflicting sources / what is unclear | Bearing on PSCAD | Status |
|---|---|---|---|---|
| **OQ-1** | `R_D1` **as-designed** value is contested | Schematic + downstream docs say pre-bodge **237 kΩ**; `docs/reviews/design-review-2026-07-28.md:98` flags an older manufacturing export saying **243 kΩ**. As-fitted 215 kΩ is bench-confirmed | None for the model (use 215 kΩ), but it matters for any "what changed" narrative | OPEN — as-fitted unaffected |
| **OQ-2** | 27.4 kΩ naming collision | `R_C`-BT pre-bodge compensator (27.4k → 61.2k, a real bodge) vs **R1-FC**, the FC input-voltage ADC divider, which is 27.4 kΩ **by design** (R1-BT is 16.2 kΩ, intentionally asymmetric). Do not conflate | Direct: mis-bodging R1-FC in the model would corrupt the FC voltage sense | OPEN — documentation hazard, not a hardware question |
| **OQ-3** | OPA197 **as-designed** supply rail is not stated anywhere in the swept corpus | Only the as-fitted 5 V rail is documented (bodge B5). Needs the schematic PDF or operator input | Sets the droop-injection ceiling; candidate (b) in T2-X1 (§5.3) | OPEN — needs schematic/operator |
| **OQ-4** | Encoder pull-up rail unconfirmed and possibly unsafe | 2.2 kΩ pull-ups may be on 5 V; Teensy pins 14/15 are **not** 5 V tolerant; "move to 3.3 V if on 5 V" is still open | None (out of scope for the power sim) | OPEN — **genuine hardware-safety item**, flagged here because it should not be lost |
| **OQ-5** | FC hot-loop bodge-cap fit **date** unrecorded | Confirmed present by 2026-08-11 (operator correction of an earlier "un-bodged" note); likely fitted with the post-Death-5 FC boost replacement 2026-07-08, but not stated | Bounds which log batches the 40.1 µF FC node applies to | OPEN — value confirmed, date uncertain |
| **OQ-6** | D-FC `C_SS` = 100 nF fit **date** unrecorded | Predates the 2026-08-06 capture-10 run; D-BT (2026-08-03) and D-MT (2026-08-07) are dated | Same: which logs the 19.8 ms FC ramp applies to | OPEN |
| **OQ-7** | 10 kΩ EN-to-GND resistors: **scope and date** underspecified | One uncorroborated `CLAUDE.md` mention ("every switch"); not itemized per switch, no date | Boot/reset transient studies only | OPEN |
| **OQ-8** | Bench-supply output impedances **never quantified** | Batches 153–180 swap is documented qualitatively ("stiffer on BT, looser on FC") with no scope-measured `R_out` for either supply | The Tier-1/Tier-2 stiffness presets (0.05 / 0.45 Ω) are therefore **assumptions borrowed from the FC/BT source models**, not supply measurements | OPEN — a bench measurement would close it cheaply |
| **OQ-9** | **Realized droop ~4× below design has no attributed root cause** | Design 0.30 V/A vs measured 0.074 (shared) / 0.1615 (single); ×4.72 / ×4.27 once the RT1987 `R_ON` is removed (§5.3(c)). Surviving candidates: **(e) injection attenuation `R_D1/R_inj` — new lead**, tolerance stack, OPA197 headroom, load-path effects, methodology artifact. **Two narrowings this round:** the sense-gain class is CLOSED (§5.3, the `S`-cancellation proof), and candidate (f)'s log audit shows the TP logs *did* command `g = 0.298` (OQ-22). The two Python engines still sit on opposite sides | **The core open question; §5 is the experiment** | **OPEN — narrowed, highest value** |
| **OQ-10** | `docs/boost-bringup-debug.md` internal staleness | Its "Next steps" §0 (~line 1614) still lists the BT `R_D1` = 215k verification as open; the same file's 2026-07-31 update (lines 269–330) already resolved it | None — housekeeping | OPEN — housekeeping only |
| **OQ-11** | VESC Six EDU **input capacitance unmeasured** | `boost-bringup-debug.md:388–390`. The HIL default is 0.5 mF over a 0.2–0.9 mF envelope (`--vesc-cap-uf`) | Bounds confidence in "100 nF `C_SS` keeps the motor-node connect self-limiting"; directly sets the `scp-inrush` margin | OPEN — a measurement would tighten §4.9 and §6.2 |
| **OQ-12** | Block-diagram PDF still labels the sense output **400 mV/A** | `references/DC Controller-DroopCircuit 2026-06-09.pdf` says "`V DROOP, 400mV/A (K_sns)`" (the A3 part); the fitted part is **A1, 0.1 V/A**, and `papers/Droop_Control/sections/02_droop_design.tex:249–250` calls it "a consequence of a component substitution error" | As-fitted wins (`K_sns = 0.1`). The ×4 coincidence with OQ-9 is **dead**: §5.3 proves the part gain `S` cancels exactly between the droop path and the firmware's reported current, so **no sense-gain error of any size or sign can move the measured slope**. The PDF remains a hazard for a reader building a model from it | **PARTLY CLOSED** — the OQ-9 link is closed with reason (cancellation proof, §5.3); the stale PDF label is still OPEN as a documentation fix |
| **OQ-13** | `LIMIT_V_BUS_MAX` disagreement | `docs/VESC_MOTOR_INTEGRATION.md` says 17.0 V; `.ino` says **17.5 V** (`V_BUS_NOMINAL + 1.5`) | `.ino` is authoritative; the doc is stale. Use 17.5 V in any fault-logic model | OPEN — doc fix |
| **OQ-14** | Does `ems-drive-cycle` literally exist in the `SCENARIOS` registry? | `CLAUDE.md` 2026-08-27e says it was added; research brief 4 §2 did not find it by that name during the research pass. **Verified 2026-08-30: it exists** (`SCENARIOS["ems-drive-cycle"]` in `tools/hil_plant_sim.py`; 58 s since the 2026-08-30 duration trim, was 60 s; `hold-5050` EMS, 8-point profile) — the research pass missed it. Anchored by registry KEY rather than by line number, which had already drifted | §6.2 Tier-B row added | **CLOSED** — verified against the registry |
| **OQ-15** | `hil_electrical.py` FC-node capacitance asymmetry | `C_BOOST_OUT_FC = 30 µF` omits the +10.1 µF hot-loop bodge caps that `C_BOOST_OUT_BT = 40.1 µF` gets, yet `boost-bringup-debug.md` (operator corrections 2026-08-11) says **both** boosts carry them | This document specifies **40.1 µF on both** (§4.9). Any PSCAD-vs-HIL comparison of a fast FC-node transient will differ from the Python engine until reconciled | OPEN — looks like an un-updated model asymmetry, not real hardware asymmetry |
| **OQ-16** | INA253 and OPA197 dynamic specs are not in the repo | No bandwidth for the INA253A1, no GBW/slew for the OPA197 anywhere in the swept corpus | Irrelevant at T2-SYS rates; **decides whether switching ripple reaches the FB node in T2-FAST** | OPEN — read from the part datasheets before stage 2e |
| **OQ-17** | `R_BODY_DIODE = 0.15 Ω` is not extracted | `hil_electrical.py:103`, `TODO(verify)`; no datasheet basis recorded | Sets the magnitude of the disabled-boost back-feed — the hazard the whole sequencing discipline exists for | OPEN |
| **OQ-18** | Post-bodge (`"short"`) parasitic inductances have **no extraction**, and `OTHER = 2.5 nH` is unexplained | Only the two `"long"` FC/BT values (1.538 / 3.480 nH) come from FastHenry. The `"short"` 1.5 nH flat set is the engine's **default** | Every T2-FAST ring result rests on it; acceptance in §6.2 Tier C is qualitative for this reason | OPEN — a FastHenry re-run on the bodged geometry would close it |
| **OQ-19** | Measured single/shared droop **mode ratio is 2.18, not 2.00** | Parallel-Thevenin theory gives exactly 2.00 at `r = 0.5`. Propagating the published fit uncertainties (0.1615 ± 0.001 over 0.074 ± 0.004, RSS 5.4 %) gives **2.18 ± 0.12**, so 2.00 sits ~**1.5σ** away — **consistent, not anomalous.** An earlier draft of this document presented the +9 % as an independent inconsistency, which would have invited tuning a model to noise | **Downgraded.** Removed from §5.3(c)'s discriminator list. Revisit only if the shared-slope uncertainty tightens materially | LOW — monitor only |
| **OQ-20** | **Do the hot-loop bodge caps sit inside the boost's compensated loop?** | §4.9 mandates them as node capacitance (40.1 µF); §4.3's crossover scaling assumes they are part of `C_O` as the compensator sees it — natural, since they sit at the `VOUT` pin, closer than the 3×22 µF bank (40 mil FC / 240 mil BT). **No repo source argues it either way** | Decides which §4.3 crossover table is the T2-FAST gate (12.6–16.8 vs 16.8–22.5 kHz FC). **Bigger than PSCAD:** if they *are* inside the loop, `system_model.md` §6e's crossover table, the `τ_r` range feeding the share-loop design plant, and the bring-up boost-margin arguments were all computed at a stale `C_O` and need re-deriving | OPEN — **repo-wide**, do not resolve inside a PSCAD project |
| **OQ-21** | **What capacitance actually rings at the "~100 MHz" the repo cites?** | The extracted hot-loop `L` against `C_O` gives **0.43–0.64 MHz** as-fitted (0.74 MHz pre-bodge), not 100 MHz (§4.10 arithmetic); a 100 MHz ring on 1.5 nH needs `C ≈ 1.69 nF`, and 100–300 pF of switch-node capacitance gives 240–410 MHz. The resonating element must be the **switch-node parasitic** (`C_oss` + package + board), for which **no value exists in the repo** | Sets T2-FAST's fast-tier timestep: 20 ns suffices for the output-loop ring, 0.2–2 ns only for the switch-node ring. The earlier blanket 0.2–2 ns tier was ~100× pessimistic for the study it was attached to | OPEN — take `C_oss` from `TPS61288LRQQR.pdf` and the switch-node loop from the layout |
| **OQ-22** | **ML0165 contributed zero commanded droop to the `K_DROOP_BUS` fit** | Log audit (2026-08-30) of the BLG `gFC`/`gBT` columns: **ML0165 ran `gFC = gBT = 0.0000` for all 33,835 rows** and was included in the fit set; ML0169 and TP0170 ran `g = 0.298` throughout; TP0174 shows live closed-loop variation (`gFC` 0.31–0.51, `gBT` 0.21–0.28) | **Methodology footnote, not a refutation** — the ×4 finding survives on the TP logs, which commanded droop at the design gain. Whether to re-fit excluding ML0165 is the operator's call; **no re-fit slope is quoted anywhere in this document** | OPEN — operator decision on the fit set |
| **OQ-23** | **TP0178's 6 ms sag does not close against the modelled `C_BUS`** | 0.7 A bus-side into 35 µF drains 3.19 V in ~160 µs, ~37× faster than observed. The observation implies either a **~19 mA net deficit** or an **effective ~1.3 mF**. Candidates — `N_MOT`'s ~1 mF reservoir back-feeding with D-MT still closed, or BT already partially conducting — **demand opposite things of the model** | Made an explicit deliverable of the TP0178 run (§6.2). **`C_BUS` must stay pinned** at its §4.9 parts-count value; letting it float would absorb whichever mechanism is real | OPEN — raised by this round; decidable in T2-SYS at stage 2d |
| **OQ-24** | **TPS61288 synchronous-rectifier behaviour in shutdown is undocumented** | The §4.3 passthrough element is forward-only (input→output), matching the Python engine. The hazard `CLAUDE.md` §2 names runs the other way — regen back-feeding *into* a disabled converter — and nothing in the repo describes what the sync rectifier does when the part is disabled | Without it the back-feed hazard is **unmodellable**, and the sequencing rules stay a procedural protection rather than something the model can be run against (§8) | OPEN — needs the TPS61288 datasheet's shutdown/sync-rect section, or a bench measurement |

---

## 10. Fidelity boundaries and extension roadmap

### 10.1 What these models will and will not be trustworthy for

**Tier 1 is trustworthy for:** the droop *mechanism* (that share is set by the ratio of droop
resistances and bus sag by their parallel combination), the governor arithmetic, the shape of a
sampled share loop, and teaching PSCAD. **It is not trustworthy for** any transient involving
the RT1987s, any statement about the realized droop value, or anything at switching timescales.

**T2-SYS is trustworthy for:** sequencing and switch timing at millisecond resolution, the
droop chain's static realization, share-loop behaviour including the governor and the
OPEN→CLOSED handover, sag depth and recovery on handoff events, and fault-threshold timing if
§6.4 is included. **It is not trustworthy for** boost voltage-loop margin, switching ripple, or
anything the parasitics govern.

**T2-FAST is trustworthy for:** switching waveform shape, the ripple path into the sense chain,
disabled-boost passthrough edges, and the *bounding* of output-loop ring peaks. **It is not
trustworthy for** absolute ring amplitudes on the post-bodge geometry (OQ-18), switch-node ring
frequency or shape (OQ-21 — the capacitance is not known), reverse conduction into a disabled
boost (OQ-24), or anything thermal or EMC-related.

### 10.2 Every open marker carried into these models, by name

Grouped by where it bites. This is the list to shorten.

**Blocks a quantitative droop result (attack first):**

| Marker | Where | Kind |
|---|---|---|
| `K_DROOP` = 0.30 Ω | §4.4, `.ino:1875–1879` | `TODO(calibrate)` — and the subject of OQ-9 |
| The ×4 droop discrepancy itself | §1.2, §5 | OPEN FINDING, root cause unattributed — **narrowed** this round (sense-gain class closed; TP-log droop commanded confirmed) |
| INA253A1 bandwidth; OPA197 GBW / slew rate | §4.4 | `TODO(verify)` — OQ-16 |
| OPA197 as-designed supply rail | §4.4, bodge B5 | Unknown — OQ-3 |
| Resistor tolerance bands for `R_D1`, `R_D2`, `R_inj`, `Rop1`, `Rop2` | §4.4 / §5.3(a), (e) | `TODO(verify)` — read from the BOM |
| `K_DROOP_BUS` fit set includes a zero-droop log (ML0165) | §5.3(f) | OQ-22 — operator decision on re-fitting |
| ADC resolution / `ADC_MAX` actually shipped | §4.6 | `TODO(verify)` — read from `.ino`, do not assume |

**Blocks a quantitative transient result:**

| Marker | Where | Kind |
|---|---|---|
| `I_OUT_MAX` = 6.0 A, `R_OUT` = 0.010 Ω | §4.3 | `TODO(verify)` |
| `R_BODY_DIODE` = 0.15 Ω | §4.3 | `TODO(verify)` — OQ-17 |
| `TAU_R` = 100 µs (range 20–300) | §4.3 | `TODO(calibrate)` |
| VESC input capacitance 0.5 mF (0.2–0.9 mF) | §4.9 | `TODO(verify)` — OQ-11 |
| `C_CHG_NODE` = 10 µF | §4.9 | `TODO(verify)` (`C_RGN_NODE` is retired — see §4.9) |
| Node ESL values (all parts) | §4.9 | `TODO(verify)` — not in the repo at all |
| `"short"` trace-L set = 1.5 nH flat; `OTHER` = 2.5 nH | §4.10 | `TODO(verify)` — OQ-18 |
| Switch-node ring capacitance (`C_oss` + package + board) | §4.10 | `TODO(verify)` — OQ-21, **not in the repo at all** |
| TPS61288 sync-rectifier behaviour in shutdown | §4.3, §8 | `TODO(verify)` — OQ-24; blocks any back-feed study |
| `V_UVLO_boost` (TPS61288 input UVLO) | §3.2 | `TODO(verify)` — no value anywhere in the repo |
| Whether the bodge caps are inside the compensated loop | §4.3 | OQ-20 — decides the T2-FAST crossover gate |
| RT1987 min/max spread | §4.5 | Not modelled — typicals only |
| VESC ≈ 428 ms reversal dead window | §4.7 | `TODO(verify)` — characterized from one log |
| Bench-supply output impedances | §3.2, §4.2 | Unquantified — OQ-8 |
| What carries the bus through the TP0178 6 ms gap | §6.2 | OQ-23 — a deliverable of the stage-2d run |

**Simulator-only tuning values inherited from `hil_electrical.py` (never launder):**

`V_STICTION` 0.02 m/s · `R_BUS_BLEED` 2000 Ω · `ETA_BOOST` 0.85 · `I_AUX_A` 0.15 A ·
`R_FC_INT` 0.45 Ω / `R_BT_INT` 0.05 Ω · `AG105_TAU_S` 0.4 s · `AG105_V_IN_MIN` 8.0 V ·
`C_CHG_NODE` 10 µF (`C_RGN_NODE` retired — §4.9).

**Source-model parameters, all `TODO(calibrate)`:**

`FC_AREA_CM2` 3.0 cm² · `FC_TAU_S` 20 ms · `FC_R_SERIES_RIG` 0.41 Ω · `BATT_CAPACITY_AH` 5.0 Ah
· `BATT_RS_NOM` 0.040 Ω · `BATT_R1` 0.020 Ω · `BATT_C1` 200 F · the generic `LIPO_OCV_*` table.

**Drivetrain / firmware constants carried but not owned by this document:**

`η_dt` 0.85 (`TODO(calibrate)`, "the largest surviving drive unknown") · `UV_BUS_DWELL_LATCH_MS`
20 ms (`TODO(calibrate)`) · `MOT_HOTPLUG_MARGIN` 3.0 V (`TODO(calibrate)`) · `AG105_SETTLE_MS`
500 ms (`TODO(calibrate)`) · `LIMIT_V_BATT_MAX` 10.0 V (temporary bench value; real 8.6 V
commented out).

**Resolved, kept for traceability:** the regen chopper trip (was a 16.5 V `TODO` placeholder,
now **18.1 V bench-calibrated 2026-08-27**); `K_DROOP_BUS_SHARED`/`_SINGLE` (was a 0.35 V/A
placeholder, now **measured** 0.074 / 0.1615 V/A — the measurement is settled even though its
disagreement with design is not); the **INA253 sense-gain class as a candidate for OQ-9**
(closed on paper by the cancellation proof, §5.3 — the part gain and the firmware constant both
drop out of the measured slope); the **mode-ratio "anomaly"** (2.18 ± 0.12 is ~1.5σ from 2.00 —
consistent, downgraded, OQ-19).

### 10.3 Flagged follow-ups

| Item | Scope |
|---|---|
| **T2-X1 result → bench** | Whatever §5 produces is a hypothesis for the bench, not a constant update. `K_DROOP_BUS_*` in `tools/hil_plant_sim.py` are measurements and outrank PSCAD (§1.3) |
| **`hil_electrical.py` FC node capacitance** | Reconcile `C_BOOST_OUT_FC` to 40.1 µF, or record why the asymmetry is intended (OQ-15) |
| **FastHenry re-run on the bodged geometry** | Closes OQ-18 and makes every T2-FAST ring number quantitative rather than indicative |
| **`tools/pscad/` comparison script** | Contract specified in §6.3; not written. Reuses `CHECK_KINDS` and the `FIGURES` registry pattern |
| **Bench-supply impedance measurement** | Closes OQ-8; converts the Tier-1 stiffness presets from assumptions into parameters |
| **Doc fixes** | `VESC_MOTOR_INTEGRATION.md` 17.0 → 17.5 V (OQ-13); the DroopCircuit PDF's 400 mV/A label (OQ-12); `boost-bringup-debug.md` §0 staleness (OQ-10) |
| **Charger-path data** | No charger-path transient has ever been recorded (charger unpowered in every logged run). Until a charge run exists, §4.11 cannot be validated at all |
| **`C_O` inside-vs-outside the compensated loop (OQ-20)** | **Repo-wide, and the highest-priority item in this table after T2-X1.** If the hot-loop bodge caps are part of `C_O`, `system_model.md` §6e's crossover table and the `τ_r` range feeding the share-loop design plant are stale by ×0.75. Settle it before regenerating any controller coefficients |
| **Switch-node ring capacitance (OQ-21)** | Extract `C_oss` from the TPS61288 datasheet and the switch-node loop from the layout; until then the 0.2–2 ns T2-FAST tier has nothing to resolve and should not be run |
| **`K_DROOP_BUS` fit set (OQ-22)** | Decide whether to re-fit excluding ML0165 (zero commanded droop across all 33,835 rows). This document quotes no re-fit slope |
| **TP0178 bus-support mechanism (OQ-23)** | A stage-2d deliverable, not a modelling choice. Resist the temptation to close it by adjusting `C_BUS` |
