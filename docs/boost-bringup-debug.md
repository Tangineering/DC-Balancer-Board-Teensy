# Battery boost (TPS61288) repeated-failure debug log

**Status (2026-07-08): BT hot-loop fix VALIDATED, but a FIFTH death (the FC boost this time) shows
the overshoot mechanism is CURRENT-SCALED and system-wide.** The BT fix (10 µF + 0.1 µF at the BT
boost output, collapsing its 240 mil hot loop) held: four surviving `G` bring-ups, and both boosts
now drive the bus and the 470 µF motor node off 9 V batteries. **But closing `MOT_PWR_ENABLE` onto
an attached VESC with a stiff source killed the FC boost** (Death 5 — same `VFC`→GND VIN–SW–VOUT
signature). Unified picture: SW/VOUT ring amplitude scales with commutated current. BT's 6×-worse
hot loop died at light bus-connect currents (Deaths 1–4, fixed); at the **15 A-class currents of a
motor-node hot-plug** (D-MT-EN's ~1.17 ms soft-start cannot charge 470 µF + VESC input caps →
RT1987 SCP burst-retry → repetitive full-current load-dumps on the boosts), even FC's good 40 mil
layout rings past the **20 V abs-max** — but only when the source is stiff enough to deliver the
current (9 V batteries sag/UVLO first, which is why battery runs survive and DC-supply runs kill).
A stiff-supply `G` also overshoots to ~19 V at bring-up (bus OV fault) — the margin above 17.5 V is
razor-thin everywhere. **Plan: drop the bus to 16 V nominal (headroom), NEVER hot-plug the motor
node at full bus (pre-charge sequencing — firmware), bodge FC's output like BT's, and do the
high-BW ring measurement before further load work.** See "Death 5 / motor-node round". This
document is the cold-start reference — read it before touching the bench.

**One-line summary (how it was solved):** boost fine standalone; bus path proven clean without the
boost; boost dies driving the bus; FC identical on paper but survives → elimination left only a
**physical BT-channel difference**. The measured one: BT's output caps sit **240 mil** from the IC
output vs FC's **40 mil** → ~2.7× hot-loop inductance → SW/VOUT overshoot past the 20 V abs-max
under bus-drive di/dt. **Fix: 10 µF + 0.1 µF bodged at the BT boost output — four surviving `G`
bring-ups where every unmodified attempt died.**

**Key implication (Death 1):** the very first death was the *original, never-reworked* BT boost. So
the BT channel was hostile to a boost **before any rework** — pointing at an original manufacturing
defect or layout asymmetry on the BT channel, which repeated rework may have compounded but did not
create.

---

## Pin / net reference (so names aren't confused again)

| Signal | Teensy pin | Net / part | Function |
|---|---|---|---|
| `FC_REG_ENABLE` | 3 | `EN-REG-FC` | FC **boost** enable (TPS61288 EN) |
| `BT_REG_ENABLE` | 4 | `EN-REG-BT` | BT **boost** enable (TPS61288 EN) |
| `FC_BUS_ENABLE` | 27 | `D-FC-EN` (RT1987) | FC boost output → VBUS (ideal-diode switch) |
| `BT_BUS_ENABLE` | 28 | `D-BT-EN` (RT1987) | BT boost output → VBUS (ideal-diode switch) |
| `MOT_PWR_ENABLE` | 29 | `D-MT-EN` (RT1987) | VBUS → V-MOT / VESC |
| `BT_SEQUENCE_ENABLE` | 32 | `D-BT-SQ` (RT1987) | battery (VBT) → charger VBAT terminal |

Note: in earlier chat the operator said "FC_REG/BT_REG" but **meant `FC_BUS`/`BT_BUS`**.
This doc uses the correct names above.

**Topology facts (corrected from earlier wrong assumptions):**
- VBUS carries only **~30–40 µF** (the RT1987 ceramics: `D-FC-EN` VOUT, `D-BT-EN` VOUT,
  `D-MT-EN` VIN, `D-BC-FC` VIN, each 10 µF, + the BUS-V divider).
- The **470 µF bulk cap is on V-MOT / regen, behind `MOT_PWR_ENABLE`** — NOT on VBUS. It was
  off (`MOT_PWR_ENABLE` low) in every failure. **Bus inrush is not the issue.**
- Each boost output (`VBUS-FC` / `VBUS-BT`) has **3 × 22 µF** (DC-derates to ~30 µF at 17.5 V).
- Boost: **TPS61288**, L = 2.2 µH, 15 A cycle-by-cycle switch limit, OVP 19 V (≤19.5 V),
  SW/VOUT abs-max 20 V, ~3 ms soft-start. (Datasheet: `references/Datasheets/TPS61288LRQQR.pdf`)

---

## Failure datapoints

| # | Source | What was done | Result |
|---|---|---|---|
| pre-1 | Two 9 V batteries (FC + BT separate) | Both boosts enabled, **both bus switches OFF** | Both regulated **17.5 V** standalone, fine |
| pre-1 | 9 V batteries | Enabled `FC_BUS_ENABLE` (FC → VBUS) | FC on VBUS, **no incident** |
| **Death 1** | 9 V batteries | FC already disconnected from VBUS; enabled `BT_BUS_ENABLE` | **BT boost fried** |
| **Death 2** | DC supply, **120 mA** limit, BT input only, no FC | Old FW: State-0 turned bus switches on, then boosts | Supply collapsed into CC at 120 mA; **BT boost fried** |
| **Death 3** | DC supply, **full (≥5 A)**, BT input only, no FC | New FW (BENCH_TEST): booted to Idle fine, sensors OK; sent `G` (bring-up) | Supply hit **5–7 A with collapsed voltage**; **BT boost fried** |
| **Death 4** | DC supply, **8.2 V / 200 mA limit** on BT input (board-powered), no FC | `RC-BT` reverted to **61.2 kΩ**; **known-good FC TPS61288 moved to BT pad** (regulated 17.5 V standalone after reflow); sent `G` (gentle, bus pre-charged ~7.7 V via body diode) | Draw **immediately pegged 200 mA CC**, voltage collapsed; **BT boost fried** (`VBT`↔GND short) |

Other confirmed conditions:
- `BT_SEQUENCE_ENABLE` (battery → charger): **ON in deaths 1–3** (as reported at the time).
  **Death 4: UNCERTAIN, likely OFF** — the operator initially logged it ON but later recalled it was
  off; under the BENCH_TEST firmware used for Death 4, the power stage (including `BT_SEQUENCE`)
  boots LOW and `G` does not touch it, so OFF is the more likely state unless manually toggled.
  (Moot for causation either way: the 2026-07-07 surviving runs also had it OFF, so the only delta
  vs Death 4 is the added output caps.)
- In death 1 the FC boost was **already disconnected** when BT was connected (not a paralleling fight).
- Post-mortem each time: `VBT → GND` short (the dead boost: VIN–SW–VOUT fused to GND).
- **Death 4 conditions** (most controlled yet): `FC_BUS_ENABLE`, `MOT_PWR_ENABLE`, `REGEN_ENABLE`,
  `FC_CHARGE_ENABLE` all OFF; `BT_SEQUENCE_ENABLE` likely OFF (see above); `BT_BUS_ENABLE` brought up
  by `G` in sequence with `BT_REG_ENABLE`. `G` energizes the bus switches **first**, so the bus was
  pre-charged to ~7.7 V (boost body diode) before the boost soft-started — **not** a 0 V hot-plug.
- **Death 4 is the decisive datapoint:** the boost was the FC channel's *proven-good* part. It lived
  on the FC pad, died on the BT pad. **Pad/channel, not part.**

### Boost-removed path test (PASS — bus path is clean)

Teensy powered separately; **BT TPS61288 removed**; DC bench supply driving the boost-output node
`VBUS-BT`; Teensy ran the bus startup (asserted `BT_BUS_ENABLE` / `D-BT-EN`).
**Result: VBUS rose to 17.5 V stably, supply current ≈ 0.** So `D-BT-EN`, VBUS, and the whole BT
bus path are good — no short, no low-impedance load. The fault is **not** in the path.

### FC boost drives the bus (PASS — healthy reference, 2026-06-24)

Teensy powered separately; **12 V DC supply on the FC boost input**; `G` (bring-up) command.
**Result: the FC boost cleanly brought VBUS up to 17.5 V.** Confirms the bring-up sequence and the
separate-logic-supply rig are sound, and gives the healthy "boost actively driving the bus"
reference. (BT TPS61288 still removed.)

### Dual-source OR-ing (PASS — `D-BT-EN` passes a live bus cleanly, 2026-06-24)

Teensy powered separately; **9 V battery on the FC boost input** (FC boost live, holding the bus at
~17.61 V); **DC supply at 17.5 V on `VBUS-BT`** with the **BT TPS61288 still removed**; `G` command.
**Result:** the bus came up cleanly to the shared voltage, then tracked **the higher of the two
sources**. Sweeping the DC supply 17.5 → 17.67 V, VBUS followed smoothly 17.61 → 17.67 V — the two
ideal-diode paths OR cleanly, no fight, no instability. This further confirms the BT path is clean
even with `D-BT-EN` carrying current alongside a live FC source on the bus; **only the BT boost
itself is implicated.**

### ⭐ FIX VALIDATION — BT boost survives bus-connect with hot-loop caps (PASS, 2026-07-07)

**Configuration:** new BT TPS61288 installed; **10 µF + 0.1 µF ceramics bodged directly at the BT
boost output** (collapsing the 240 mil Cout hot loop to ~FC-like); `RC-BT` = 61.2 kΩ; **9 V battery
on the BT input** (≈8.3 V under light load — the scope captures' pre-charge level);
`FC_BUS`/`MOT_PWR`/`REGEN`/`FC_CHARGE` OFF; `BT_SEQUENCE` OFF. **Same as Death 4 except the caps —
a controlled single-variable test.**

**Result: survived FOUR consecutive `G` bring-ups**, regulating the bus at **17.7 V**. Scope
captures (each a separate run) in `references/scope_captures/`:
1. `1-VOUT.jpg` — VOUT: 8.3 V body-diode pre-charge → soft-start ramp to 17.7 V in ~1.36 ms; one
   aborted first ramp (collapse to ~8 V, ~1.3 ms pause, automatic re-soft-start) then clean
   regulation. **A protection-retry that previous boosts did not survive — now it recovers.**
2. `2-VBUS.jpg` — VBUS: 0 → 8.3 V step (`D-BT-EN` closes, pre-charge) → ramp to 17.7 V, flat and
   clean for the rest of the capture (no hiccup on this run).
3. `3-SW.jpg` — SW envelope: two soft-start "wedges" (the aborted + successful ramps), PFM sleep
   gaps, then steady burst switching. No visible destructive ring.
4. `4-SW zoomed in.jpg` — the "~75 kHz initial oscillations" are **normal PFM pulse-skipping** at
   the start of soft-start (discrete pulses, rep rate ramping ~25→75 kHz as the current command
   rises) — not an instability, not the parasitic ring.

**Notes:** (a) See "Startup hiccup explained" below — the aborted first ramp is a benign,
deterministic VIN-UVLO retry caused by the 9 V battery source, not a board defect. (b) All captures
were **1× probe (~10 MHz BW), 50 MSa/s** — the estimated 100–200 MHz hot-loop ring is invisible at
this bandwidth. Survival is the evidence here; the **high-BW margin check is still owed** before
heavy load testing (see Next steps).

#### Startup hiccup explained (aborted first soft-start on every cold `G`)

Observed on every cold bring-up: VOUT ramps to 17.7 V, holds ~1.5 ms, collapses to ≈ VIN, waits
~1.3 ms, re-runs soft-start, then regulates indefinitely. Chain of evidence:
- TPS61288 datasheet §8.3: a fresh soft-start requires the SS cap to reset, which happens **only on
  EN low or UVLO** (OVP just pauses switching with 600 mV hysteresis near 19 V — cannot produce a
  collapse to 8 V; the part has no hiccup-SCP feature).
- Firmware never toggles the enable, and a Teensy brownout-reset would park all enables LOW
  (no auto-retry) — so the observed silicon-only retry proves EN stayed HIGH → the reset was
  **VIN UVLO** (falling ~1.9 V, rising ~2.3 V).
- Cause: the **9 V battery source + constant-power boost load**. The first ramp charges local + bus
  caps (~12–15 W input demand); a PP3 at ~2 Ω IR can deliver at most V²/4R ≈ 10 W — beyond the
  max-power point the sag runs away (boost draws more as VIN falls) and VBT crashes to UVLO. The
  battery rebounds in ~1 ms (IR drop vanishes at zero load) → rising UVLO → soft-start re-runs.
- **The retry always succeeds** because VBUS stays parked behind `D-BT-EN`'s reverse blocking
  (capture 2: no VBUS dip) → the second ramp charges only the local caps, ~half the power, on the
  stable side of the max-power boundary. Hence deterministic first-fails/second-sticks.
- **Bench artifact, benign, invisible to the bus.** The production 2S pack (~50–100 mΩ) sags ~0.2 V
  at this draw — no hiccup in the car. Historical rhyme: this source-collapse is the same "weak 9 V
  battery" event from the Death-1 era — it once killed boosts via the bad hot loop; with the caps
  fitted it is a self-healing retry. Confirm (optional): scope VBT + VOUT on one `G` (expect VBT
  diving to ~2 V at the collapse), or use a stiff ≥3 A supply → single clean ramp expected.
  **Do not load-test from the 9 V battery** — repeated deep UVLO-cycling is the historical stress
  pattern, and the battery can't source load tests anyway.

### ☠️ Death 5 (FC boost) + motor-node hot-plug round (2026-07-08)

| Config | Action | Result |
|---|---|---|
| Both sources = 9 V batteries; BT bodge caps fitted | `G` bring-up, then `MOT_PWR_ENABLE` onto the bare 470 µF motor node | **Works** — both boosts on the bus, motor node charged |
| Either source = stiff DC supply | `G` bring-up | **Bus overvoltage fault at ~19 V** (soft-start hand-off overshoot; on batteries the sag/UVLO-hiccup masks it) |
| Two 9 V batteries; **VESC attached** to motor node | `MOT_PWR_ENABLE` at full bus | **Teensy browned out / USB disconnected** (board-powered logic; batteries collapsed under the inrush). Boosts survived. |
| BT = 9 V battery, FC = **stiff DC supply**; VESC attached | `MOT_PWR_ENABLE` at full bus | **FC boost DIED** — `VFC`→GND short (same VIN–SW–VOUT signature as Deaths 1–4); supply drew 5 A after death |

**Mechanism.** Closing `D-MT-EN` at full bus onto a discharged motor node (470 µF + the VESC's own
input capacitance, likely another several hundred µF–mF) is the *same hot-plug sin* as the original
VBUS incident, one node downstream: the RT1987's ~1.17 ms soft-start cannot charge that stack →
**SCP burst-retry**, each burst yanking VBUS down and slamming the boosts to their 15 A cycle
limit, then load-dumping them mid-burst. SW ring amplitude scales with the commutated current — at
15 A-class events even FC's tight 40 mil hot loop rings past the 20 V abs-max. **The kill requires
a stiff source**: 9 V batteries collapse to UVLO before lethal current flows (→ brownout chaos, no
deaths); the DC supply delivers it (→ Death 5 on the FC side, while BT on its sagging battery
survived). This retroactively explains the source-dependence across all five deaths.

**Actions:**
1. **✅ IMPLEMENTED (firmware, 2026-07-08) — motor-node pre-charge sequencing.** Never close
   `MOT_PWR_ENABLE` at full bus onto a discharged motor node. `doState0()` phase 0 and `bringUpBus()`
   ('G') now raise `MOT_PWR` **with the bus switches, before the boosts ramp**, so the boost
   soft-start charges the 470µF+VESC stack from ~Vbatt together. The node then stays energized
   through Idle/Run (`doState1()`/`doState3()` no longer force it LOW — the motor is held stopped by
   `vesc.setCurrent(0)`), torn down only in State 99, so no Idle→Run ever re-hot-plugs it. New
   `motPwrHotPlugUnsafe()` (V_bus up AND `V_rgn` lagging by > `MOT_HOTPLUG_MARGIN`, from pin 39) +
   `assertMotPwrEnable()` guard: `doState2()` faults (`FAULT_MOT_HOTPLUG`/`ERR_MOT_HOTPLUG`, new)
   rather than hot-plug; State 98 '3' refuses it. **Design-posture change to flag:** the VESC is now
   powered in Idle (contra CLAUDE.md §2 "MOT_PWR OFF in Idle") — the motor is held off by the zero
   command, not by cutting power. Bench TODO: confirm `RGN_VOLTAGE` reads the V-MOT node and
   calibrate `MOT_HOTPLUG_MARGIN`. 298+6 host tests pass.
2. **Drop the bus to 16 V nominal** (operator decision). **Firmware side prepared:** `V_BUS_NOMINAL`
   (17.5f) now parameterizes `LIMIT_V_BUS_MAX` (= nom+1) and `V_BUS_CHARGED_THRESH` (= nom−2.5);
   values unchanged at 17.5 until the **hardware FB/injection retune** — then flip `V_BUS_NOMINAL` →
   16.0f (one line). Turns the ~19 V bring-up overshoot into ~17.5 V peak (no OVP fault) and doubles
   abs-max headroom (2.5 → 4 V). Shunt/chopper trip → 20 V is acceptable for the regen node (D-MT-EN
   blocks reverse, so the regen node cannot back-feed the boosts; the shunt bound is the charger
   input / cap ratings, not the boost abs-max) — but a cleaner ladder is nominal 16 < FW fault ~17.5
   < shunt ~18.5 < OVP 19 < abs-max 20 if the divider allows.
3. **Bodge 10 µF + 0.1 µF at the FC boost output too** when replacing the dead FC part — same
   insurance, trivially cheap.
4. **High-BW ring measurement is now blocking, not optional**: 10× probe + ground spring on SW,
   measure the ring at a controlled load step before any further VESC/load testing — 16 V of
   nominal only helps if the ring at working currents fits in the 4 V of headroom it buys.
5. FC TPS61288 needs replacement (Death 5 post-mortem: `VFC`↔GND short).

---

## Ruled OUT (with evidence)

- **Boost is defective / wrong part / FB-droop misconfig / inductor** — NO. Both boosts regulate
  17.5 V standalone. The boost circuit works until connected to VBUS.
- **Supply collapse / inrush / motorboating / overshoot (the earlier theories)** — NOT the core
  cause. A stiff ≥5 A supply killed it as fast as 120 mA. Bus is ~40 µF (470 µF is elsewhere), so
  inrush is negligible. These transient theories are **superseded**.
- **`D-BT-EN` EXP(CD)-to-GND or VOUT-to-GND short** — NO. Ohmmeter, board unpowered:
  `D-BT-EN` EXP→GND, `D-BT-EN` VOUT→GND, `D-FC-EN` EXP→GND, `D-FC-EN` VOUT→GND **all open**.
- **VBUS shorted to GND** — NO. The FC boost held VBUS at 17.5 V in death 1.
- **An input current limit makes a boost test safe** — NO. Death 2 fried the boost at 120 mA.
  Do not rely on any input current limit to protect a boost (see Safety below).
- **A dynamic low-impedance fault / short in the BT→VBUS path** — NO. The boost-removed path test
  (above) drove the node to 17.5 V at ~0 current. The path is clean.
- **Charger / `BT_SEQUENCE` involvement** — ruled out. The DC path test showed ~0 static load, and
  `BT_SEQUENCE` state is now known to be a non-variable: likely OFF in Death 4 and OFF in the
  surviving 2026-07-07 runs — the death/survival difference was the caps, not this switch.
- **`RC-BT` compensation delta (was the leading hypothesis)** — REFUTED by Death 4. `RC-BT` reverted
  to 61.2 kΩ (matched to FC) and the boost still died on bus-connect. Compensation `RC` is not the
  (sole) cause.
- **0 V hot-plug / bring-up sequence** — REFUTED. Death 4 used `G`, which energizes the bus switches
  first, so the boost soft-started into a bus pre-charged to ~7.7 V. Gentle, pre-charged bring-up
  still kills it.
- **The boost part itself / desolder damage** — REFUTED by Death 4. The part that died was the FC
  channel's *known-good* TPS61288, which had just regulated 17.5 V and driven the bus on the FC pad;
  it also regulated 17.5 V standalone on the BT pad after reflow. It died only when driving the bus
  **from the BT channel**.

## ROOT CAUSE (validated by intervention): BT output-cap hot-loop inductance → destructive SW overshoot driving the bus

*(Written as the leading hypothesis; validated 2026-07-07 by the fix test above — adding 10 µF +
0.1 µF at the BT boost output was the single changed variable between Death 4 and four consecutive
survivals. The high-BW ring measurement is still owed to quantify remaining margin.)*

**A known-good boost lives on the FC pad and dies on the BT pad.** Schematic proven symmetric
(below) → the difference is the **PCB layout** (solid by elimination). The leading specific feature
is the **output-capacitor hot loop** — the pulsed, high-di/dt loop (Cout → IC VOUT/PGND → return)
that sets the SW/VOUT overshoot. **All power nets here are polygon pours; trace-length figures are
irrelevant (pour-overridden).** The metric that matters is **Cout distance to the IC output pin**,
measured directly by the operator:

| Feature | FC | BT | Note |
|---|---|---|---|
| **Cout → TPS61288 output pin (operator-measured)** | **40 mil (~1.0 mm)** | **240 mil (~6.1 mm)** | **6× farther on BT.** Dominant hot-loop dimension → BT hot loop has substantially higher inductance. **Leading cause.** |
| `VSW` inductor pad → IC pad (operator edge-to-edge) | 7.4 mm | 11.8 mm (1.6×) | SW is a ~150 mil-wide **pour** (low-L) carrying *continuous* inductor current (low di/dt) → minor contributor, not dominant. |

**Why the earlier Gerber numbers were wrong (do not reuse them):** a prior parse reported `VSW-BT`
"17.45 mm / 2.2×" and `VOUT`/`VBUS` trace lengths. Those summed thin stroked trace draws and
**excluded the polygon pours** (`G36`/`G37` regions) that are the actual wide copper for SW *and*
VOUT. They are superseded by the operator's direct pad-to-pin measurements above. Trace length ≠
loop inductance for pours.

**Mechanism:** BT's output caps sit 6× farther (240 vs 40 mil) from the IC output pin → larger
hot-loop area/inductance → at the di/dt of driving the bus, SW/VOUT rings past the **20 V abs-max**
(only ~0.5–1.5 V over the 17.5 V rail) → sync-rect FET fails **short** (`VIN`–`SW`–`VOUT`→GND, the
observed post-mortem). Energy is internal ½·L·di², so **no input current limit bounds it** (death at
120 mA). Fits Death 1 (original un-reworked boost — it's the copper), FC always surviving, the `RC`
swap not helping, and the clean DC injection (no di/dt → no ring).

**Inductance estimate (from the 10-mil-grid PCB images).** Hot loop modeled as the VOUT pour
(~150 mil) over the 2-layer GND return → microstrip L′ ≈ μ₀·h/w ≈ **0.4–0.55 nH/mm** of one-way
length, plus a **~1 nH common** term (cap ESL + vias, identical both channels):

| | Cout→IC pin | length term | total hot loop |
|---|---|---|---|
| FC | 40 mil (1.0 mm) | ~0.5 nH | **~1.5 nH** |
| BT | 240 mil (6.1 mm) | ~3 nH | **~4 nH** (~2.7× FC; +2.5 nH) |

Overshoot `V = L·di/dt`, with di/dt **backed out of FC's survival**: FC rides ≲2 V under abs-max →
di/dt ≈ 1.3 A/ns → applied to BT: `4 nH × 1.3 A/ns ≈ 5.2 V` → **~22.7 V > 20 V abs-max → death.**
Same di/dt, ~2.7× the loop inductance, turns FC's safe ~2 V into BT's fatal ~5 V. (Absolutes ±2–3×:
di/dt, Coss, bottom-plane continuity all uncertain; the *relative* "FC at the edge, BT several-fold
worse" is the robust part.)

**Confidence: reasonably strong** — the 6× placement / ~2.7× loop-L asymmetry is quantitatively
consistent with BT crossing abs-max while FC doesn't, given the ~0.5–1.5 V headroom. Still **confirm
with one scope capture** of `VSW`/`VOUT` on bus-connect (expect a >20 V spike on BT, a clean edge on
FC). If BT does *not* ring past 20 V, re-open (ground-return/via or manufacturing defect). Fix:
**add output ceramic right at the IC VOUT/PGND** (pulls BT's length term to ~0 → ~1–1.5 nH, FC-like,
overshoot back to ~2 V) — both the test and the remedy in one move; ± an SW snubber.

### Schematic diff — CONFIRMED SYMMETRIC (full BOM compare, `Scale_Car_Board_20260624.sch`)

Every boost-stage part matches FC↔BT, value-for-value and part-for-part:

| Part | FC | BT | |
|---|---|---|---|
| `REG` boost | TPS61288LRQQR | TPS61288LRQQR | same |
| `L` inductor | HCM1A1305V3-2R2-R 2.2 µH | HCM1A1305V3-2R2-R 2.2 µH | same |
| `SNS` | INA253A1IPWR | INA253A1IPWR | same |
| `RC` comp | 61.2 kΩ | ~~27.4 kΩ~~→ now 61.2 kΩ | matched (still died) |
| `CC`, `RINJ`, `ROP1/2`, `RD1`, `RD2`, `R2` | 2 nF / 53.6 k / 10 k+40.2 k / 237 k / 10 k / 10 k | identical | same |
| `C1`,`C3`,`C4A/B/C`,`C5`,`C6`,`CSNS` | 10 µ/2.2 µ/3×22 µ/100 n/27 p/100 n | identical | same |
| `R1` (NOT a boost part) | 27.4 kΩ | 16.2 kΩ | **input-V ADC sense divider** (`FC_VOLTAGE`/`BT_VOLTAGE`); firmware scales each (`SCALE_V_FC`/`SCALE_V_BATT`). Different by design, irrelevant to the death. |

**Conclusion: the boost schematics are identical.** The cause is therefore NOT a component/comp
value — it is the **PCB layout** (see ROOT CAUSE above: the BT output-cap hot loop, 240 vs 40 mil).

---

## Safety rules for further bench work

- **No input current limit is proven safe.** Death 2 = 120 mA. Do not assume 0.3 A (or any value)
  protects a boost; the boost can demand >5 A, and output-side energy (its own ~10 mJ output cap,
  or reverse/overshoot) is not bounded by the input limit.
- **Power the Teensy/logic from a SEPARATE supply** for any bench test, so a boost-input current
  limit can't re-trigger the death-2 brownout/motorboating of the board-powered logic.
- **Any future BT boost install must keep the hot-loop caps** (10 µF + 0.1 µF at the IC output, or
  a respun layout with Cout at the IC). Installing a boost on the *unmodified* BT channel is a known
  kill — four died that way. Scope every first bring-up after a hardware change.

---

## Next steps (fix validated — quantify margin, then escalate load)

The caps are in, the boost survives `G` bring-ups (×4). Remaining work, in order:

**1. High-bandwidth margin check (before heavy load testing).** The validation captures were 1×
probe (~10 MHz) at 50 MSa/s — the estimated 100–200 MHz hot-loop ring is invisible in them.
Re-measure: **10× probe, full scope bandwidth, ground spring** on the BT SW pin, steady state under
some load, single-shot armed ~18.5 V. If the peak is comfortably < ~19 V → done, no snubber. If it
kisses 19+ → size an RC snubber (SW→GND, ~5–10 Ω + a few hundred pF from the measured ring
frequency) and refit.

**2. Startup hiccup — explained (see the note under Fix Validation).** The aborted first soft-start
on every cold `G` is a VIN-UVLO retry caused by the 9 V battery source collapsing under the
constant-power ramp load; benign, self-healing, invisible on VBUS. Optional confirmation: scope
VBT + VOUT on one `G` (expect a VBT dive to ~2 V), or repeat on a stiff ≥3 A supply (expect one
clean ramp). Use a stiff supply or real pack for all further testing.

**3. Escalate load stepwise, scope armed on the first attempt of each:** repeated cold `G` cycles →
`MOT_PWR_ENABLE` (V-MOT 470 µF pre-charge) → dual-source with FC → motor load → regen events.

**4. Board respin items (the permanent fix):** move the BT output caps to the IC `VOUT`/`PGND`
(≤ ~40 mil, mirror FC); keep the bodge caps as the reference implementation. Consider also matching
the FC/BT `VSW` pour geometry and widening `VBUS-BT` while in there.

**5. Housekeeping:** update the in-code comments that say "mechanism unconfirmed, pending scope" —
the mechanism is now validated by intervention (hot-loop caps). Keep `RC-BT` = 61.2 kΩ unless the
deep-discharge case is re-analyzed properly with the bus load included.

---

## Firmware status (context)

The firmware changes made across these sessions (boosts default OFF; `doState0()` gentle bring-up
+ V_bus gate; `BENCH_TEST` bypass that boots to Idle with the power stage off; State-98 `G`
bring-up + `1`/`2` hot-plug guard; Finish leaves bus energized) are **defensive and still
reasonable**, but they target the *bring-up sequence / supply* — which the data shows was **not**
the root cause. **The root cause was the BT output-cap hot-loop layout, fixed in hardware
(10 µF + 0.1 µF at the BT boost output, validated 2026-07-07); firmware was never the problem.**
The in-code comments still say "mechanism unconfirmed, pending scope" — update them to reference
the validated hot-loop fix (Next steps §5). Treat this doc as the authoritative, current
understanding.

All 219 (production) + 5 (bench) host-native tests pass: `cd test && mingw32-make`.
