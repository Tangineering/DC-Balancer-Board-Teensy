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

The same document is equally explicit about the parasitic ring: the ~100 MHz LC ring on the
boost output hot loops is **not integrated** in `hil_electrical.py` at all — it is an analytic
event estimate `V_peak ~= V_node + L*di/dt` at a fixed worst-case `di/dt = 1.3e9 A/s`, evaluated
at each switch opening and compared to `V_ABSMAX = 20.0 V` (research brief 2 §4). PSCAD/EMTDC
at a nanosecond timestep can simulate both of those, because it does not have to keep up with
a 1 kHz wall clock.

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

| # | Item | As-designed | As-fitted (model this) | Date / source | Confidence |
|---|---|---|---|---|---|
| B1 | VBUS FB divider `R_D1`, **both** channels | 237 kΩ (schematic + BOM; an older mfg export says 243 kΩ — see OQ-1) | **215 kΩ** → design `V0 = 0.6*(1 + 215/10 + 215/53.6) = 15.91 V`; both boosts measured regulating 15.9 V no-load | Bodged 2026-07-11, reconfirmed by measurement 2026-07-31 (`boost-bringup-debug.md:229–330`; `system_model.md` §2) | CONFIRMED (DMM + scope, both channels) |
| B2 | `R_C` TPS61288 compensator, BT channel | 27.4 kΩ | **61.2 kΩ** (matches FC; symmetric lags are the assumption behind the shared `τ_r`) | 2026-07-10 (`CLAUDE.md` bodge record; `system_model.md` §6e) | CONFIRMED |
| B3 | RT1987 soft-start `C_SS`, 3 of 6 switches | 5.6 nF on **all six** (BOM line 80, C-DS qty 6) | **100 nF on D-BT-EN, D-FC-EN, D-MT-EN**; D-FC-CH / D-RG-EN / D-BT-SQ **deliberately left at 5.6 nF** (operator decision 2026-08-07: charger-node caps too small to trip the 250 µs SCP blank) | D-BT-EN 2026-08-03 (capture 8), D-MT-EN 2026-08-07 (capture 11), D-FC-EN date not recorded (OQ-6) | CONFIRMED (BT/MOT dated + single-variable validated; FC value confirmed, date uncertain) |
| B4 | Hot-loop bodge caps at boost `VOUT` pin | none beyond the 3×22 µF bank (240 mil away on BT, 40 mil on FC) | **10 µF + 0.1 µF ceramic directly at the IC output pin, BOTH channels** | BT fitted+validated 2026-07-07 (4 surviving bring-ups at Death-4 conditions); FC confirmed fitted by 2026-08-11 by operator correction, date not recorded (OQ-5) | CONFIRMED BT (dated, scope-validated); CONFIRMED-by-correction FC |
| B5 | OPA197 (MDAC output amp) supply rail | not stated anywhere in the swept corpus (OQ-3) | **5 V rail**; output ceiling ≈ 4.9 V — a hard constraint on droop-injection authority | `CLAUDE.md` §7; `system_model.md` §8; `HIL_PLANT.md` §8 | CONFIRMED as-fitted; as-designed NOT FOUND |
| B6 | Current sense part | INA253A3IPWR intended (0.4 V/A) | **INA253A1IPWR fitted, both channels — `K_sns = 0.1 V/A`** | Factory BOM substitution at original manufacture (`CLAUDE.md` §5; `.ino:1861–1865`) | CONFIRMED |
| B7 | RT1987 EN-to-GND resistors | none | **10 kΩ EN→GND** so every switch defaults low while the Teensy GPIO is high-Z during reset/boot | `CLAUDE.md` §2 — single mention, no date, per-switch scope not itemized (OQ-7) | CONFIRMED they exist; scope + date uncertain |
| B8 | Regen chopper clamp | no explicit trip-voltage spec found on the schematic | **18.1 V** trip, 47 Ω dump, 20 W device rating | Bench-calibrated 2026-08-27 (observed `V_rgn` 13.3 → 18.1 V held); retires the earlier 16.5 V placeholder | CONFIRMED as a **measurement**, not a hardware rework |
| B9 | Bench supplies, log batches 153–180 | n/a | Supplies **swapped** — stiffer on BT, looser on FC | `CLAUDE.md` 2026-08-17b; `boost-bringup-debug.md:1373–1377` | Swap CONFIRMED; **impedances never quantified** (OQ-8) |

### 2.2 Consequences for the PSCAD models

- The **as-fitted `R_D1 = 215 kΩ`** sets `V0`. A PSCAD model built from the schematic's 237 kΩ
  would produce `V0 = 0.6*(1 + 23.7 + 4.421) = 17.47 V` and be wrong by 1.6 V — the same
  stale-constant class that produced this repo's one false "bus 1.6 V below nominal" alarm
  (`CLAUDE.md` 2026-08-17). Use 215 kΩ.
- **`R_C = 61.2 kΩ on both channels`** is what makes the shared `τ_r` assumption legitimate.
  A T2-FAST switching study that uses the schematic's 27.4 kΩ on BT will show a BT crossover
  around 6.2–7.0 kHz instead of 13.8–15.7 kHz (research brief 1 §4) and will not match the board.
- The **CSS split (100 nF on the three bus/motor switches, 5.6 nF on the three charger-path
  switches)** is not a schematic feature; it is exactly the split `hil_electrical.py` models.
  `hil_electrical.py`'s own citation of "schematic 20260622" for the 100 nF values is
  **imprecise** — the paper schematic still shows 5.6 nF everywhere (research brief 2 §1).
- **`K_sns = 0.1 V/A`** (not 0.4). See OQ-12: the block-diagram PDF still labels the sense
  output "400 mV/A".

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
| Source→bus ORing | Plain master-library diode with low `V_f` | RT1987 `t_D_ON`, soft-start, foldback, reverse comparator, servo offset |
| Bus | One lumped capacitor | Per-node capacitance split, ESR/ESL |
| Load | Controlled current source: manual slider / timed step / simple drive-shaped profile | Motor mechanics, VESC behaviour |
| Droop chain | **One gain block** `I_sense -> K_sns*A_v*g -> setpoint shift`, with a slider for `g` | INA253 bandwidth, MDAC quantization, OPA197 rail, injection network |
| Share control | Minimal **sampled PI** at the firmware share tick rate, trimming the two droop gains | The shipped Youla-H controller (deliberately — see below) |

**Why a PI and not the shipped controller.** Tier 1's purpose is to teach discrete-control
blocks in PSCAD (sample-and-hold, ZOH, a sampled loop closed around a continuous plant). The
shipped share controller is 3 DF2T biquads plus a separate exact integrator with generated
coefficients; putting it in Tier 1 would teach nothing about PSCAD and would risk a
hand-transcribed coefficient set. It belongs in Tier 2 (§4.6), imported from the generated
header. **Tier 1's PI is not the board's controller and no Tier-1 result is a statement about
the shipped loop.**

**Why the ideal-diode simplification is safe here.** The RT1987 behaviours that matter
(8 ms `t_D_ON`, 1–20 ms soft-start ramps, the −50 mV reverse comparator that produces the
TP0178/TP0201 reactive-pickup gap) are all *transient* mechanisms. Tier 1's acceptance criteria
are all *steady-state* (§3.4). A plain diode gets the steady-state ORing right and gets every
one of those transients wrong; Tier 1 must therefore never be used to argue about a handoff
transient. That is Tier 2's job (§4.5).

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
| `C_BUS` | 35 µF | Lumped VBUS capacitance | "30–40 µF band, midpoint" — 4×10 µF RT1987 ceramics + BUS-V divider (`boost-bringup-debug.md:49–50`); `hil_electrical.py` |
| `I_OUT_MAX` | 6.0 A | Per-channel boost output current limit | `hil_electrical.py`, **`TODO(verify)`** |
| `ETA_BOOST` | 0.85 | Boost efficiency for input-current referral | `hil_electrical.py:209`, **`TODO(verify)`** — simulator-only tuning value; numerically coincides with the unrelated drivetrain `η_dt`, which is a coincidence, not a shared measurement |
| `V_f` (Tier-1 ORing diode) | set 0.035 V | Stand-in for the RT1987 forward servo offset | RT1987 DS §17.6 `V_FWD` 35 mV typ (`hil_electrical.py` `RT_V_FWD`). A real silicon diode's 0.7 V would move `V0` visibly and is wrong here |
| `R_s` "stiff" preset | 0.05 Ω | Series source resistance, stiff supply | `R_BT_INT` legacy scalar, `hil_electrical.py:206–207`, **`TODO(verify)`** — an assumption, **not** a measured supply impedance |
| `R_s` "loose" preset | 0.45 Ω | Series source resistance, loose supply | `R_FC_INT` legacy scalar, **`TODO(calibrate)`** — the "0.447 Ω effective at 2 A" FC fit target; likewise not a supply-impedance measurement |

> **⚠ The two stiffness presets are assumptions, not measurements.** No numeric output-impedance
> spec for either bench supply exists anywhere in the repo; the batch 153–180 swap is documented
> qualitatively only ("stiffer on BT, looser on FC"). The 0.05 / 0.45 Ω pair above is borrowed
> from the HIL engine's *source* internal resistances, which are themselves `TODO(verify)` /
> `TODO(calibrate)`. Treat T1-E4 as a sensitivity study, not a reproduction. See OQ-8.

### 3.3 Solver settings

| Setting | Recommendation | Reason |
|---|---|---|
| Solution timestep | 20 µs (acceptable range 10–50 µs) | Must resolve `τ_r` = 100 µs comfortably; 20 µs gives 5 points per lag time constant. If you set `τ_r` to its 20 µs lower bound, drop the timestep to 2–5 µs |
| Plot/output step | 200 µs | Ten solution steps per plotted point; keeps the graph responsive over multi-second runs |
| Run duration | 2–10 s | Long enough for a load sweep and for the sampled share loop to settle |
| Interpolation | Leave EMTDC's default switching interpolation on | Harmless here (no real switching), and you want the habit before Tier 2 |
| Snapshot | Take one at t = 1.0 s once the bus is settled | Teaches the snapshot workflow; makes E5/E6 iterate faster |

### 3.4 Exercise ladder

Each exercise = a PSCAD concept + a build step + a number to check. Do them in order; each
builds on the previous canvas.

#### T1-E1 — workspace, canvas, master library, static two-source bus

*PSCAD concepts:* workspace vs project; the main canvas; the master library palette; wiring
electrical nodes; a voltmeter; an output channel; a graph frame; running a case.

*Build:* two DC sources + series `R_s` (stiff preset) + two averaged boost controlled sources
(hold `g_F = g_B = 0`, i.e. no droop yet) + two diodes into `N_BUS` + `C_BUS`. No load.

*Expected:* `V_bus = V0 - V_f = 15.95 - 0.035 = 15.915 V` steady. With `g = 0` there is no
droop term. Check the design alternative too: setting `V0 = 15.91` gives `V_bus = 15.875 V`.
The 0.04 V spread between the measured and design `V0` is the model's own uncertainty floor;
note it, because it is small compared to everything else in this document.

#### T1-E2 — droop slope

*PSCAD concepts:* controlled current source; slider input; on-line plotting while a case runs;
reading a slope off two operating points.

*Build:* add the load current source, driven by a slider 0 → 3 A. Enable one channel only
(force the other's `V_src` to zero). Set `g` so `Re = RE_MAX * g` equals the value under test.

*Expected (measured preset, single-source):* configure `Re = 0.1615 Ω` (i.e. `g = 0.0802`).
Then `V_bus(I) = 15.915 - 0.1615*I`:

| `I_load` | `V_bus` |
|---|---|
| 0 A | 15.915 V |
| 1 A | 15.754 V |
| 3 A | 15.431 V |

*Expected (design preset, single-source):* `Re = 0.60 Ω` (`g = 0.298`) → 15.915 / 15.315 /
14.115 V. The visible difference between these two tables **is** the ×4 open finding at
system level. Tier 1 cannot say which is right; it shows what is at stake.

#### T1-E3 — two-source sharing and the mode ratio

*PSCAD concepts:* two sources on one node; measuring a ratio of two branch currents; a
computed output channel (share = `I_F/(I_F+I_B)`).

*Build:* both channels live. Set per-channel droop from a target ratio `r`:

```
Re_F = k_d / r          Re_B = k_d / (1 - r)
```

*The circuit solves the droop equation for you.* With equal `V0`:

```
I_F = (V0 - V_bus)/Re_F ,  I_B = (V0 - V_bus)/Re_B
alpha = I_F/(I_F+I_B) = Re_B/(Re_F+Re_B) = r
V_bus = V0 - (Re_F || Re_B) * I_tot ,  and  Re_F || Re_B = k_d  (constant, by construction)
```

*Expected, `k_d = 0.074` (measured combined), `I_tot = 3 A`:*

| `r` | `Re_F` | `Re_B` | measured `alpha` | `V_bus` |
|---|---|---|---|---|
| 0.50 | 0.148 Ω | 0.148 Ω | 0.500 | 15.693 V |
| 0.30 | 0.2467 Ω | 0.1057 Ω | 0.300 | 15.693 V |
| 0.85 | 0.0871 Ω | 0.4933 Ω | 0.850 | 15.693 V |

The invariance of `V_bus` across `r` is the point of the `k_d/r` mapping and is worth
plotting.

*Mode ratio:* disable BT. The surviving channel presents `Re_F = k_d/r`; at `r = 0.5` that is
`2*k_d`, so **single-source droop is exactly 2× shared droop** at the balanced point. Check
against the measured pair: `0.1615 / 0.074 = 2.18`, i.e. +9 % off the theoretical 2.00. Log
this — see OQ-19; it is a second, weaker inconsistency riding on top of the ×4 finding.

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

*Expected:* with the input-power referral in place, at `V_bus ≈ 15.7 V`, `I_F ≈ 2.55 A`,
`V_in_F ≈ 12 V`, the reflected input current is
`I_in_F = 15.7*2.55/(0.85*12) ≈ 3.93 A`, so the FC source sags by `0.45*3.93 ≈ 1.77 V` —
enough to matter, and the sag is self-reinforcing (lower `V_in` → higher `I_in`). Converge
the algebraic loop by inspection or let PSCAD's solver do it, and record where the channel
drops out.

> **The teaching point is a negative result.** This is *not* the mechanism behind TP0178. The
> "looser FC supply transient" hypothesis for TP0178 was **REFUTED** by TP0201 (2026-08-25):
> at the dropout instant `V_fc` was **rising** (8.12 → 8.68 V) while `I_fc` stepped to zero in
> the same sample — the boost **stopped drawing**, which a sagging supply cannot cause. The
> resolved root cause is architectural: the share loop slews the droop ratio across an FC↔BT
> conduction crossing while the pickup channel is a *dark standby*, and the standby RT1987
> picks up only reactively, after the sag. (`boost-bringup-debug.md:1367–1436`; mitigation is
> the fw v19 handoff-dwell slew cap.) T1-E4 shows what a stiffness problem *does* look like,
> so you can tell the two apart. Reproducing TP0178 needs Tier 2's RT1987 model (§4.5).

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

| Check | Target | Tolerance |
|---|---|---|
| No-load bus | 15.95 V (measured) / 15.91 V (design) | ±0.05 V, and state which `V0` you used |
| Droop slope, both sources, `k_d` configured = 0.074 | `dV/dI = -0.074 V/A` | ±5 % (it is a configured value; this checks the circuit, not the board) |
| Single-source / shared droop ratio | 2.00 | exact by construction at `r = 0.5` |
| Share tracking, `sp = 0.5` | `alpha = 0.500` | ±0.005 (bench sees 0.503 ± 0.028 with noise Tier 1 does not model) |
| Governor clip band at `I_tot = 0.72 A` | [0.4167, 0.5833] | exact |

**Tier 1 uses the MEASURED droop as the configured value**, because Tier 1 has no mechanism
that could derive it. Tier 1 therefore cannot say anything about the ×4 finding beyond
showing its magnitude. Deriving the droop from the circuit is Tier 2's job.

---

## 4. Tier 2 — full detailed simulation

**Project name suggestion:** `droop_t2` in the same workspace, with two run configurations.

### 4.1 The two-configuration structure

| Configuration | Power stage | Timestep | Window | Purpose |
|---|---|---|---|---|
| **T2-SYS** | Averaged boost (reduced-form controlled source) | 1–5 µs | 10–60 s | Everything compared against HIL scenarios and bench logs: sequencing, droop realization, share loop, sag/handoff transients, fault thresholds |
| **T2-FAST** | Switching TPS61288 (real L, switch, sync rectifier, `f_SW`) + parasitic L + node ESR/ESL | 10–20 ns (switching) down to 0.2–2 ns (ring) | 0.5–5 ms | Switching ripple reaching the sense chain; body-diode back-feed edges; hot-plug / ring events (Death-5 class); SCP inrush |

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
  cross-checked against `tps61288_full_model.py`'s crossover numbers (research brief 1 §4:
  FC 16.33 vs formula 16.84 kHz, ratio 0.97; BT/7.4 V 13.52 vs 13.84, 0.98 — 1–3 % agreement).
  A T2-FAST small-signal extraction that does not land inside that band is wrong, and the
  existing full-order model is the referee.

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
| `V_FC_OPEN` / `R_FC_INT` | 13.0 V / 0.45 Ω | Legacy scalar fallback (use for the bench-supply configuration) | `hil_electrical.py:204–207`, **`TODO(calibrate)`** |
| `BATT_CELLS` | 2 | 2S pack | `hil_electrical.py:473` |
| `BATT_CAPACITY_AH` | 5.0 Ah | Coulomb-count denominator | `hil_electrical.py`, **`TODO(verify)`** |
| `BATT_RS_NOM` | 0.040 Ω | Series R, flat mid-band, ×1→×4 below SOC 0.15 | `hil_electrical.py:473–477, 521–524`, **`TODO(calibrate)`** |
| `BATT_R1` / `BATT_C1` | 0.020 Ω / 200 F (τ ≈ 4 s) | Single RC relaxation branch | ibid., **`TODO(calibrate)`** |
| `LIPO_OCV_SOC/_V` | 9-point generic 2S curve | OCV(SOC) lookup | `hil_electrical.py:471–472` — **generic, NOT a measured pack characterization**, `TODO(calibrate)` |
| Battery operating band | 7.4–8.4 V | System decision 2026-07-10; the BT boost margin analysis assumes it | `CLAUDE.md` bodge record B2 rationale |
| `V_BT_OPEN` / `R_BT_INT` | 8.0 V / 0.05 Ω | Legacy scalar fallback | `hil_electrical.py:206–207`, **`TODO(verify)`** |

#### PSCAD realization

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
if V_src > V_OVP:  latch off                # hardware OVP
if disabled or OVP-latched:  body-diode path active (below)
```

**Body-diode passthrough — this must exist in the model.** A *disabled* TPS61288 still has a
body-diode/synchronous-rectifier path from its input to its output, and a VESC regen event
back-feeding through it is the documented mechanism that destroys converters (`CLAUDE.md` §2).
Model it explicitly as a Norton source `(V_in - V_BODYDIODE)` behind `R_BODY_DIODE` onto the
channel output node, active when the boost is disabled or OVP-latched and `V_in > 1.0 V`
(`hil_electrical.py:102–103, 1120–1131`). In PSCAD this is cleanest as a real diode in
parallel with the averaged source, gated by the enable signal — the point is that **the
back-feed hazard must be present in the model, not assumed away.**

#### T2-FAST: switching

Real power stage: input node → inductor `L` → low-side switch (IGBT/MOSFET from the master
library) → node → synchronous rectifier / diode → output node → `C_O`. Drive it from a
current-mode control page (peak-current comparator + slope, `V_COMP` from the error amp with
the `R_C`/`C_C`/`C_P` compensator) at `f_SW`.

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
| `V_OVP` | 19.0 V | Hardware OVP trip | `hil_electrical.py:100`, "confirmed 19 V". Firmware's `LIMIT_V_BUS_MAX = 17.5 V` trips first |
| `V_ABSMAX` | 20.0 V | Abs-max, the ring-estimate comparison threshold | `hil_electrical.py` |
| `V_BODYDIODE` | 0.55 V | Disabled-boost passthrough drop | `hil_electrical.py:102–103` |
| `R_BODY_DIODE` | 0.15 Ω | Passthrough series resistance | `hil_electrical.py:103`, **`TODO(verify)` — not extracted from any datasheet** (OQ-17) |
| `C_O` | 3×22 µF ⇒ **30 µF derated / 66 µF nominal** | Boost output bank, DC-derated at 17.5 V | BOM line 6; `boost-bringup-debug.md:51` |
| `TAU_R` | 100 µs | Reduced-form lag | `hil_electrical.py`; design-plant nominal, `TODO(calibrate)` |
| `I_OUT_MAX` | 6.0 A | Reduced-form current limit | `hil_electrical.py`, **`TODO(verify)`** |
| `R_OUT` | 0.010 Ω | Small-signal output resistance placeholder | `hil_electrical.py`, **`TODO(verify)`** |
| `f_RHPZ` | 31–330 kHz | RHP zero over the 2–8 A envelope at 7.4 V BT / 16 V bus | `system_model.md` §6e |

**Voltage-loop crossover** (`f_c = R_C*(1-D)*V_ref*G_EA*K_COMP / (2*pi*V_OUT*C_O)`), the
T2-FAST acceptance target:

| Channel | `f_c` (derated `C_O` / nominal `C_O`) | `τ_r = 1/(2*pi*f_c)` |
|---|---|---|
| FC (`V_in` 9–12 V) | 16.8–22.5 / 7.7–10.2 kHz | 7–21 µs |
| BT (`V_in` 7.4–8.4 V, `R_C` = 61.2 k post-bodge) | 13.8–15.7 / 6.3–7.1 kHz | 10–25 µs |
| *(BT pre-bodge, 27.4 k — for the record only)* | 6.2–7.0 / 2.8–3.2 kHz | 23–57 µs |

#### What validates it

- **T2-SYS:** step-load bus responses against HIL `step-load` and against the bench sag
  arithmetic (§6.2). Nothing else — T2-SYS makes no margin claim.
- **T2-FAST:** an AC extraction (inject a small perturbation at the FB node, measure the loop)
  must land inside the table above to within ~5 %, matching the 1–3 % agreement
  `full_order_validation.md` Gate C already demonstrates between the formula and the 11-state
  model. Ripple amplitude and the RHPZ-region phase are the other two checks.

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
  four candidate explanations for the ×4 finding (§5). `TODO(verify)`: OPA197 GBW and slew rate
  are not recorded in the repo; take them from `OPA197.pdf`.
- **Injection + FB network:** real resistors on the electrical canvas, into a node that the
  boost's control page reads as `V_FB`. In T2-SYS the boost is a controlled source, so close
  the outer loop explicitly: drive the source magnitude with an integrator/regulator that
  holds `V_FB = V_ref`, with the loop bandwidth set to the §4.3 crossover for that channel.
  That way the droop still emerges from the resistor network, exactly as on the board, while
  the fast dynamics stay at the reduced-form level.
- **Component tolerances:** make `R_D1`, `R_D2`, `R_inj`, `Rop1`, `Rop2`, `K_sns` and `V_ref`
  project parameters, not literals, so the Multiple Run component can sweep them (§5).

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

The `_restart_no_ss` path is the mechanism behind the TP0178 / TP0201 **reactive-pickup handoff
gap**: a dark standby channel's switch only closes *after* the bus has already sagged enough to
forward-bias it.

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
| `C_SS` — D-FC-EN, D-BT-EN, D-MT-EN | **100 nF** | Soft-start cap, **as fitted** (bodge B3) | Ramp ≈ **19.8 ms** at `V_IN` = 16 V |
| `C_SS` — D-RG-EN, D-FC-CH, D-BT-SQ | **5.6 nF** | As designed and deliberately retained | Ramp ≈ **1.07 ms** at `V_IN` = 16 V |

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
| `FC_BUS_ENABLE` | 0x01 | D-FC-EN | `N_OFC → N_BUS` |
| `BT_BUS_ENABLE` | 0x02 | D-BT-EN | `N_OBT → N_BUS` |
| `MOT_PWR_ENABLE` | 0x04 | D-MT-EN | `N_BUS → N_MOT` |
| `REGEN_ENABLE` | 0x08 | D-BRG | `N_MOT → N_RGN` |
| `FC_CHARGE_ENABLE` | 0x10 | D-BFC / D-BC-FC | `N_BUS → N_CHG` |
| `BT_SEQUENCE_ENABLE` | 0x20 | B-BSQ / D-BT-SQ | gates the pack into the BT boost **input** (enable-state only; no node link in the HIL model) |

(BOM line 77: RT1987N-A qty 6, designators D-FC, D-BT, D-MT, D-BRG, D-BFC, B-BSQ.)

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
| ADC sampling + quantization | loop rate | Quantize `V_bus`, `V_fc`, `V_batt`, `I_fc`, `I_batt` at the firmware's `analogReadResolution()` before they reach any control block |
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
m_eff * dv/dt = K_F * I_cmd - sign(v)*F_c - b_eff*v          # mechanical, control page
p_mech  = max(0, f_drive * v)                                # REGEN FLOORED AT 0 on the bus side
i_motor = p_mech / (ETA_BOOST * v_bus)   when MOT_PWR closed and v_bus > 1.0 V
i_total = i_motor + I_AUX_A
```

Motor force is produced only when `MOT_PWR_ENABLE` is closed **and** `v_bus > 5.0 V`.

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
that dumps the regen node into 47 Ω. It sits on the **regen node only**; `V_bus` is unaffected.

```
if V_rgn > V_CHOPPER_TRIP:  conduct, P = V_rgn^2 / R_CHOPPER
```

#### Constants

| Constant | Value | Meaning / units | Provenance |
|---|---|---|---|
| `V_CHOPPER_TRIP` | **18.1 V** | Clamp threshold | Bench-calibrated 2026-08-27 (observed `V_rgn` 13.3 → 18.1 V held). Retires the 16.5 V `TODO` placeholder |
| `R_CHOPPER` | 47.0 Ω | Dump resistor | `hil_electrical.py:187–198`; BOM |
| `P_CHOPPER_MAX_W` | 20.0 W | Device/resistor rating | ibid. |
| Switch | BSP170PH6327XTSA1, P-ch 60 V 1.9 A SOT223-4 | BOM line 34, designator Q-SNT | |

Arithmetic worth checking in the model: steady dissipation at the clamp is
`18.1²/47 ≈ 6.97 W`; 20 W is only reached past `sqrt(20*47) ≈ 30.7 V`. So the chopper is not
thermally limiting at its own clamp point — a useful sanity result.

#### Role, stated correctly

The chopper is the **PRIMARY fast clamp**. The Ag105 is the slow secondary harvester. The
firmware's `MPPT_DISABLE` assertion during braking exists to stop the Ag105's perturb-and-
observe loop fighting the transient — **not** because the chopper needs help. **There is no
`V_rgn` fault check in the firmware at all**, which is itself worth knowing when reading a
PSCAD run where `V_rgn` goes somewhere interesting.

#### What validates it

The observed clamp behaviour during the sustained regen rail in logs 153–180:
`V_rgn` 13.3 → 18.1 V peak, held, with `V_bus` unmoved.

### 4.9 Node capacitors

| Node | Model value | Provenance |
|---|---|---|
| `N_OFC` (FC boost output) | **40.1 µF** — see flag below | 3×22 µF X7R 1210 (BOM line 6) DC-derated to ~30 µF at 17.5 V (`boost-bringup-debug.md:51`) **plus the 10 µF + 0.1 µF hot-loop bodge caps (B4)** |
| `N_OBT` (BT boost output) | **40.1 µF** | 30 µF derated + 10.1 µF BT bodge caps (`bench_calibration_manual.md:51`; `system_model.md`) |
| `N_BUS` | 35 µF | "30–40 µF band, midpoint": 4×10 µF RT1987 ceramics (D-FC-EN VOUT, D-BT-EN VOUT, D-MT-EN VIN, D-BC-FC VIN) + the BUS-V divider (`boost-bringup-debug.md:49–50`) |
| `N_MOT` | 470 µF (ESR 80 mΩ) **+ VESC input 0.5 mF** (0.2–0.9 mF envelope) | BOM line 30 (CAL 470 µF 35 V Al-el, 80 mΩ) — labelled "Charging path capacitor" in the BOM but it is the **V-MOT bulk cap**, explicitly *not* on VBUS. VESC input capacitance is `--vesc-cap-uf`, **`TODO(verify)`** (OQ-11) |
| `N_CHG` | 10 µF | **`TODO(verify)`** — no separate cap identified on the schematic |
| `N_RGN` | 10 µF | **`TODO(verify)`** likewise |

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

**ESR/ESL: T2-FAST only.** In T2-SYS, adding ESR/ESL to every node buys nothing at a 1–5 µs
timestep and costs conditioning. In T2-FAST it is mandatory — the 470 µF electrolytic's 80 mΩ
ESR and the ceramics' ESL are what set the actual hot-plug edge and the ring damping.
`TODO(verify)`: no ESL values for any of these parts exist in the repo; take them from the
part datasheets and record them in the project.

### 4.10 Parasitic inductances (T2-FAST only)

FastHenry extraction from the as-manufactured **long-trace** output loops
(`papers/Droop_Control/sections/05_bringup_debugging.tex`, Table `Lsweep`):

| Path | Mesh pitch | Extracted `L` | Analytic bound | Loop length | Effective width |
|---|---|---|---|---|---|
| Fuel cell | 0.3 mm | **1.538 nH** | 1.456 nH | 4.74 mm | 12.47 mm |
| Battery | 0.2 mm | **3.480 nH** | 3.149 nH | 9.69 mm | 5.91 mm |

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

Timestep honesty: an `L ≈ 1.5–3.5 nH` loop against the ceramic bank's effective capacitance
rings in the ~100 MHz class (10 ns period). At 1–2 ns you get 5–10 samples per ring cycle —
enough to bound the **peak**, marginal for **waveform shape**. For shape, 0.2–0.5 ns. A 1 ms
window at 1 ns is 10^6 timesteps; keep these runs to the sub-millisecond windows around a
single event and use snapshots to get there.

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

**Also run the clean version** (a slow deliberate load ramp, no share activity) and report
both. If the two disagree, the measurement methodology is a live candidate (§5.3d) and that
alone is a result.

### 5.3 The four undiscriminated candidate causes, and how to attack each

From research brief 5 OQ-9, the candidates are: **component tolerance stack**, **OPA197
headroom clipping**, **VESC/motor-node loading**, and a **measurement-methodology artifact**.
None has been discriminated. Each maps to a PSCAD experiment.

**(a) Tolerance stack — `R_D1`, `R_inj`, `A_v`, `K_sns`, `V_ref`.**
*Attack:* make all seven constants project parameters and drive a **Multiple Run** sweep, or a
Monte-Carlo run set, over their tolerance bands (`V_ref` ±2 % = 0.588–0.612 V is the one band
actually documented; resistor tolerances are `TODO(verify)` — read them off the BOM before
running).
*Discriminating prediction:* `Re` is **linear** in each of `K_sns`, `A_v`, `R_D1/R_inj`. A ×4
error needs the product to be off by ×4. 1 % resistors cannot do that; a **part substitution**
can. Note that `K_sns` has *already* been substituted once by a factor of 4 in this exact
chain (INA253A3 intended, A1 fitted — bodge B6): **`0.4/0.1 = 4.0`, which is numerically the
size of the discrepancy, with the sign such that assuming A3 while A1 is fitted would make the
realized droop 4× SMALLER than a model that assumed 0.4 V/A.**
> **ORCHESTRATOR REVIEW — hypothesis, not a finding.** The firmware uses `K_sns = 0.1` (the
> as-fitted A1 value), so the *firmware's* mapping is already consistent with A1; a naive
> "the code assumed A3" story does not close. But the coincidence of the factor is exact, it
> lives in this chain, and no source in the repo has considered it. **This document does not
> claim a root cause.** It flags the numerical coincidence as the first thing T2-X1 should
> test: run the sweep with `K_sns = 0.4` and confirm whether the realized bus droop lands on
> 0.074 or on 0.30 V/A, and check every place a 0.1-vs-0.4 assumption could enter (firmware
> mapping, the `RE_MAX` constant, the block-diagram PDF of OQ-12, and the bench fit itself).
> Report the result to the operator either way; a clean refutation is as valuable as a hit.

**(b) OPA197 headroom clipping.**
*Attack:* add a dedicated output channel on `V_op` for each channel, with the 4.9 V ceiling
drawn on the graph, and a "clipped" logic flag integrated over the run.
*Prediction:* headroom is computed non-binding for `g*I ≤ 9.8 A`, and the bench dataset ran at
`I_tot ≈ 0.72 A` — so clipping should **not** be reachable in the TP0170–0180 conditions. If
the PSCAD monitor shows clipping there, either the headroom arithmetic or the 5 V rail
assumption (bodge B5, as-designed rail unknown — OQ-3) is wrong. Sweep the rail (3.3 / 5 V) to
see how much droop authority the bodge actually bought.

**(c) Load-path effects.**
*Attack:* single-source vs both-source runs, and with/without the motor node connected. The
already-measured mode ratio is a free discriminator: theory says single/shared = **exactly
2.00** at `r = 0.5`; the measured pair gives **0.1615/0.074 = 2.18** (+9 %). A model that
reproduces 2.18 has found something; a model that produces 2.00 has not (see OQ-19).
*Also:* the bus-side droop is measured against `I_fc + I_batt`, which is the *source* current,
while the load sits behind the RT1987 `MOT_PWR` switch (`R_ON = 21 mΩ`, servo 35 mV) and the
`N_MOT` bulk capacitance. Series resistance between the measurement node and the load adds to
the apparent droop; it cannot subtract from it, so this candidate can only explain the gap in
the wrong direction. Confirm that in the model rather than assuming it.

**(d) Measurement-methodology artifact.**
*Attack:* the §5.2 dual protocol. Feed the PSCAD run through the *same* 200 ms quasi-steady
block regression, and separately through a clean ramp. If a share loop that is actively moving
the droop ratio during the "quasi-steady" blocks biases the regression, the PSCAD run will show
it, because in PSCAD the true `Re` is known exactly at every instant while the regression is
being computed. **This is the one candidate PSCAD can settle outright**, and it is cheap: run
it first.

### 5.4 Acceptance

T2-X1 succeeds if it produces **any** of:

- A reproduction of ~0.074 V/A from component values, with the responsible mechanism
  identified. (Best outcome.)
- A demonstration that the measured number is a regression artifact of the share-sweep
  methodology. (Second best; retires the finding.)
- A clean refutation of all four candidates — i.e. a PSCAD model that stubbornly produces
  0.30 V/A under every perturbation within the documented tolerance bands. That narrows the
  search to something *outside* the modelled chain and is a genuine result. (Third; still
  useful.)

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
| `V_fc` | `V_fc` | `V_fc` (v3+) | V | FC source terminal |
| `V_batt` | `V_batt` | `V_batt` (v3+) | V | Pack terminal |
| `V_bus` | `V_bus` | `V_bus` | V | `N_BUS` |
| `V_chg` | `V_chg` | `V_chg` (v3+) | V | `N_CHG` |
| `V_rgn` | `V_rgn` | `V_rgn` (v3+) | V | `N_RGN` |
| `I_fc` | `I_fc` | `I_fc` | A | Bus-side FC branch current (what the INA253 sees) |
| `I_batt` | `I_batt` | `I_batt` | A | Bus-side BT branch current |
| `mdac_fc` / `mdac_bt` | `mdac_fc` / `mdac_bt` | `gFC` / `gBT` | raw 16-bit word / fraction | HIL logs the **raw AD5443 word**; convert with `(word & 0x0FFF)/4095` after validating the `0x1000` nibble. BLG `gFC`/`gBT` are the gain commands |
| `switch` | `switch` | — | bitmask | `SW_FC_BUS 0x01`, `SW_BT_BUS 0x02`, `SW_MOT_PWR 0x04`, `SW_REGEN 0x08`, `SW_FC_CHARGE 0x10`, `SW_BT_SEQ 0x20` |
| `aux` | `aux` | — | bitmask | bit0 `FC_REG_ENABLE`, bit1 `BT_REG_ENABLE`, bit2 `MPPT_DISABLE`, bit3 `CBAL_DISABLE` |
| `current` | `current` | `I_cmd` | A | Post-clamp motor current command |
| `v_actual` | `v_actual` | `v_act` | m/s | Flywheel **surface** speed — there is no separate vehicle-speed scale |
| `I_charge` | `I_charge` | — | A | Ag105 stub output |
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
| **TP0178 handoff sag** | `share_sp = 0.85` (governor-clipped ≈ 0.60), FC sourcing 100 % (~0.55–0.65 A). At t ≈ 7.484 s `I_fc` steps to 0 while `V_fc` steps **8.12 → 8.68 V** in the same sample. `V_bus` decays **15.34 → 12.149 V min** over ~6 ms under ~6 A motor load; `I_batt` recovers with overshoot 0.67 → 1.74 A; total ~10 ms; **no fault** (0.15 V above `LIMIT_V_BUS_MIN`, and < 20 ms dwell) | T2-SYS: drive the share ratio across an FC↔BT conduction crossing with BT as a dark standby, RT1987 models live | Sag **depth** within ±0.3 V and **duration** within ±3 ms. The `V_fc` **rise** at dropout is the signature that must reproduce |
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

> **ORCHESTRATOR REVIEW — `ems-drive-cycle`.** The architecture plan lists `ems-drive-cycle`
> among the scenarios to map. `CLAUDE.md` (2026-08-27e) records it as added — "New scenario
> `ems-drive-cycle` (60 s, 8-point accelerate/cruise/step/decel profile)" — but research
> brief 4 §2 reports that a scenario by that literal name **did not appear in the `SCENARIOS`
> registry** during the research pass. This document therefore does **not** list an
> `ems-drive-cycle` row above. Verify against `tools/hil_plant_sim.py`'s registry before
> writing a PSCAD equivalent; if it exists, it maps to a 60 s T2-SYS run driven by the same
> 8-point velocity profile. Logged as OQ-14.

#### Tier C — T2-FAST, scope comparisons

Only where a scope capture exists. `docs/boost-bringup-debug.md` carries the numbered capture
series (capture 8 = the D-BT-EN 100 nF validation, capture 11 = D-MT-EN, capture 15 = the
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
| **1** | Tier 1, exercises T1-E1 → T1-E6 (§3.4) | §3.5 acceptance table, all five rows |
| **2a** | T2-SYS skeleton: Tier-1 topology upgraded to the real source models (§4.2) and per-node capacitors (§4.9) | `V0` from the resistor network within ±0.05 V of 15.91 V; steady-state currents match Tier 1 |
| **2b** | RT1987 behavioral switches ×6 (§4.5) + the sequencing harness | Soft-start ramps 19.8 ms / 1.07 ms; the `bringup` staging reproduces; an illegal switch combination can be commanded and its consequence observed |
| **2c** | Component-level droop chain (§4.4) + discrete MCU controls (§4.6). **Run T2-X1 here** (§5) | §4.4's three static checks, then T2-X1 §5.4 — this is the earliest point at which the ×4 question can be attacked, which is why it is stage 2c and not later |
| **2d** | Motor/VESC load (§4.7) + regen chopper (§4.8) + Ag105 stub (§4.11); scenario matching against HIL (§6.2 Tiers A and B) | TP0178 sag depth/duration within band **with a stiff supply** |
| **2e** | T2-FAST: switching power stage (§4.3) + parasitics (§4.10) + ESR/ESL | Loop crossover within ~5 % of the §4.3 table; then the Tier-C qualitative comparisons |

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
- **No EMI/EMC claims.** T2-FAST resolves a ~100 MHz ring on an assumed inductance. That is a
  circuit study, not an emissions prediction, and nothing here supports a compliance statement.
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
  FastHenry values are real (§4.10).
- **VESC behaviour is a behavioral overlay, not physics.** The 6.0 A forward cap, the 1.5 A
  regen clip and the ≈428 ms reversal dead window reproduce observed symptoms with no
  mechanism claim, and none of them is in the Python plant.
- **Simulator-only tuning values stay flagged.** `V_STICTION`, `R_BUS_BLEED`, `ETA_BOOST`,
  `I_AUX_A`, `R_FC_INT`/`R_BT_INT`, `AG105_TAU_S`, `AG105_V_IN_MIN`, `C_CHG_NODE`/`C_RGN_NODE`,
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
were raised by the architecture plan or during the writing of this document.

| # | Question | Conflicting sources / what is unclear | Bearing on PSCAD | Status |
|---|---|---|---|---|
| **OQ-1** | `R_D1` **as-designed** value is contested | Schematic + downstream docs say pre-bodge **237 kΩ**; `docs/reviews/design-review-2026-07-28.md:98` flags an older manufacturing export saying **243 kΩ**. As-fitted 215 kΩ is bench-confirmed | None for the model (use 215 kΩ), but it matters for any "what changed" narrative | OPEN — as-fitted unaffected |
| **OQ-2** | 27.4 kΩ naming collision | `R_C`-BT pre-bodge compensator (27.4k → 61.2k, a real bodge) vs **R1-FC**, the FC input-voltage ADC divider, which is 27.4 kΩ **by design** (R1-BT is 16.2 kΩ, intentionally asymmetric). Do not conflate | Direct: mis-bodging R1-FC in the model would corrupt the FC voltage sense | OPEN — documentation hazard, not a hardware question |
| **OQ-3** | OPA197 **as-designed** supply rail is not stated anywhere in the swept corpus | Only the as-fitted 5 V rail is documented (bodge B5). Needs the schematic PDF or operator input | Sets the droop-injection ceiling; candidate (b) in T2-X1 (§5.3) | OPEN — needs schematic/operator |
| **OQ-4** | Encoder pull-up rail unconfirmed and possibly unsafe | 2.2 kΩ pull-ups may be on 5 V; Teensy pins 14/15 are **not** 5 V tolerant; "move to 3.3 V if on 5 V" is still open | None (out of scope for the power sim) | OPEN — **genuine hardware-safety item**, flagged here because it should not be lost |
| **OQ-5** | FC hot-loop bodge-cap fit **date** unrecorded | Confirmed present by 2026-08-11 (operator correction of an earlier "un-bodged" note); likely fitted with the post-Death-5 FC boost replacement 2026-07-08, but not stated | Bounds which log batches the 40.1 µF FC node applies to | OPEN — value confirmed, date uncertain |
| **OQ-6** | D-FC-EN `C_SS` = 100 nF fit **date** unrecorded | Predates the 2026-08-06 capture-10 run; D-BT-EN (2026-08-03) and D-MT-EN (2026-08-07) are dated | Same: which logs the 19.8 ms FC ramp applies to | OPEN |
| **OQ-7** | 10 kΩ EN-to-GND resistors: **scope and date** underspecified | One uncorroborated `CLAUDE.md` mention ("every switch"); not itemized per switch, no date | Boot/reset transient studies only | OPEN |
| **OQ-8** | Bench-supply output impedances **never quantified** | Batches 153–180 swap is documented qualitatively ("stiffer on BT, looser on FC") with no scope-measured `R_out` for either supply | The Tier-1/Tier-2 stiffness presets (0.05 / 0.45 Ω) are therefore **assumptions borrowed from the FC/BT source models**, not supply measurements | OPEN — a bench measurement would close it cheaply |
| **OQ-9** | **Realized droop ~4× below design has no attributed root cause** | Design 0.30 V/A vs measured 0.074 (shared) / 0.1615 (single). Candidates not discriminated: tolerance stack, OPA197 headroom, load-path effects, measurement-methodology artifact. The two Python engines sit on opposite sides | **The core open question; §5 is the experiment** | OPEN — highest value |
| **OQ-10** | `docs/boost-bringup-debug.md` internal staleness | Its "Next steps" §0 (~line 1614) still lists the BT `R_D1` = 215k verification as open; the same file's 2026-07-31 update (lines 269–330) already resolved it | None — housekeeping | OPEN — housekeeping only |
| **OQ-11** | VESC Six EDU **input capacitance unmeasured** | `boost-bringup-debug.md:388–390`. The HIL default is 0.5 mF over a 0.2–0.9 mF envelope (`--vesc-cap-uf`) | Bounds confidence in "100 nF `C_SS` keeps the motor-node connect self-limiting"; directly sets the `scp-inrush` margin | OPEN — a measurement would tighten §4.9 and §6.2 |
| **OQ-12** | Block-diagram PDF still labels the sense output **400 mV/A** | `references/DC Controller-DroopCircuit 2026-06-09.pdf` says "`V DROOP, 400mV/A (K_sns)`" (the A3 part); the fitted part is **A1, 0.1 V/A**, and `papers/Droop_Control/sections/02_droop_design.tex:249–250` calls it "a consequence of a component substitution error" | As-fitted wins (`K_sns = 0.1`). But the factor is **exactly 4**, which is the size of OQ-9 — see the §5.3(a) `ORCHESTRATOR REVIEW` note | OPEN — PDF stale; **numerical coincidence flagged, not claimed** |
| **OQ-13** | `LIMIT_V_BUS_MAX` disagreement | `docs/VESC_MOTOR_INTEGRATION.md` says 17.0 V; `.ino` says **17.5 V** (`V_BUS_NOMINAL + 1.5`) | `.ino` is authoritative; the doc is stale. Use 17.5 V in any fault-logic model | OPEN — doc fix |
| **OQ-14** | Does `ems-drive-cycle` literally exist in the `SCENARIOS` registry? | `CLAUDE.md` 2026-08-27e says it was added; research brief 4 §2 did not find it by that name during the research pass | Only affects the §6.2 scenario map | OPEN — verify against `tools/hil_plant_sim.py` |
| **OQ-15** | `hil_electrical.py` FC-node capacitance asymmetry | `C_BOOST_OUT_FC = 30 µF` omits the +10.1 µF hot-loop bodge caps that `C_BOOST_OUT_BT = 40.1 µF` gets, yet `boost-bringup-debug.md` (operator corrections 2026-08-11) says **both** boosts carry them | This document specifies **40.1 µF on both** (§4.9). Any PSCAD-vs-HIL comparison of a fast FC-node transient will differ from the Python engine until reconciled | OPEN — looks like an un-updated model asymmetry, not real hardware asymmetry |
| **OQ-16** | INA253 and OPA197 dynamic specs are not in the repo | No bandwidth for the INA253A1, no GBW/slew for the OPA197 anywhere in the swept corpus | Irrelevant at T2-SYS rates; **decides whether switching ripple reaches the FB node in T2-FAST** | OPEN — read from the part datasheets before stage 2e |
| **OQ-17** | `R_BODY_DIODE = 0.15 Ω` is not extracted | `hil_electrical.py:103`, `TODO(verify)`; no datasheet basis recorded | Sets the magnitude of the disabled-boost back-feed — the hazard the whole sequencing discipline exists for | OPEN |
| **OQ-18** | Post-bodge (`"short"`) parasitic inductances have **no extraction**, and `OTHER = 2.5 nH` is unexplained | Only the two `"long"` FC/BT values (1.538 / 3.480 nH) come from FastHenry. The `"short"` 1.5 nH flat set is the engine's **default** | Every T2-FAST ring result rests on it; acceptance in §6.2 Tier C is qualitative for this reason | OPEN — a FastHenry re-run on the bodged geometry would close it |
| **OQ-19** | Measured single/shared droop **mode ratio is 2.18, not 2.00** | Parallel-Thevenin theory gives exactly 2.00 at `r = 0.5`; the measured pair `0.1615/0.074 = 2.18` is +9 %. The repo describes the ratio as "exactly 2" as a structural fact and does not comment on the measured deviation | A second, weaker inconsistency riding on OQ-9; a free discriminator for §5.3(c) | OPEN — raised by this document |

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
body-diode back-feed edges, and the *bounding* of ring peaks. **It is not trustworthy for**
absolute ring amplitudes on the post-bodge geometry (OQ-18), nor for anything thermal or
EMC-related.

### 10.2 Every open marker carried into these models, by name

Grouped by where it bites. This is the list to shorten.

**Blocks a quantitative droop result (attack first):**

| Marker | Where | Kind |
|---|---|---|
| `K_DROOP` = 0.30 Ω | §4.4, `.ino:1875–1879` | `TODO(calibrate)` — and the subject of OQ-9 |
| The ×4 droop discrepancy itself | §1.2, §5 | OPEN FINDING, root cause unattributed |
| INA253A1 bandwidth; OPA197 GBW / slew rate | §4.4 | `TODO(verify)` — OQ-16 |
| OPA197 as-designed supply rail | §4.4, bodge B5 | Unknown — OQ-3 |
| Resistor tolerance bands for `R_D1`, `R_D2`, `R_inj`, `Rop1`, `Rop2` | §4.4 / §5.3(a) | `TODO(verify)` — read from the BOM |

**Blocks a quantitative transient result:**

| Marker | Where | Kind |
|---|---|---|
| `I_OUT_MAX` = 6.0 A, `R_OUT` = 0.010 Ω | §4.3 | `TODO(verify)` |
| `R_BODY_DIODE` = 0.15 Ω | §4.3 | `TODO(verify)` — OQ-17 |
| `TAU_R` = 100 µs (range 20–300) | §4.3 | `TODO(calibrate)` |
| VESC input capacitance 0.5 mF (0.2–0.9 mF) | §4.9 | `TODO(verify)` — OQ-11 |
| `C_CHG_NODE` / `C_RGN_NODE` = 10 µF each | §4.9 | `TODO(verify)` |
| Node ESL values (all parts) | §4.9 | `TODO(verify)` — not in the repo at all |
| `"short"` trace-L set = 1.5 nH flat; `OTHER` = 2.5 nH | §4.10 | `TODO(verify)` — OQ-18 |
| RT1987 min/max spread | §4.5 | Not modelled — typicals only |
| VESC ≈ 428 ms reversal dead window | §4.7 | `TODO(verify)` — characterized from one log |
| Bench-supply output impedances | §3.2, §4.2 | Unquantified — OQ-8 |

**Simulator-only tuning values inherited from `hil_electrical.py` (never launder):**

`V_STICTION` 0.02 m/s · `R_BUS_BLEED` 2000 Ω · `ETA_BOOST` 0.85 · `I_AUX_A` 0.15 A ·
`R_FC_INT` 0.45 Ω / `R_BT_INT` 0.05 Ω · `AG105_TAU_S` 0.4 s · `AG105_V_IN_MIN` 8.0 V ·
`C_CHG_NODE` / `C_RGN_NODE` 10 µF.

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
disagreement with design is not).

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
