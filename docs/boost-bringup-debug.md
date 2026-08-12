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
- Boost: **TPS61288**, L = 2.2 µH, 15 A cycle-by-cycle switch limit, OVP **18.3 min / 19 typ /
  19.5 V max** (§7.5; corrected 2026-08-03 — the old "19 V (≤19.5 V)" shorthand omitted the
  min), **recommended VOUT max 18 V** (§7.3), SW/VOUT abs-max 20 V, ~3 ms soft-start.
  (Datasheet: `references/Datasheets/TPS61288LRQQR.pdf`)

---

## Failure datapoints

| # | Source | What was done | Result |
|---|---|---|---|
| pre-1 | Two 9 V batteries (FC + BT separate) | Both boosts enabled, **both bus switches OFF** | Both regulated **17.5 V** standalone, fine |
| pre-1 | 9 V batteries | Enabled `FC_BUS_ENABLE` (FC → VBUS) | FC on VBUS, **no incident** |
| **Death 1** | 9 V batteries | FC already disconnected from VBUS; enabled `BT_BUS_ENABLE` | **BT boost fried** |
| **Death 2** | DC supply, **120 mA** limit, BT input only, no FC | Old FW: State-0 turned bus switches on, then boosts | Supply collapsed into CC at 120 mA; **BT boost fried** |
| **Death 3** | DC supply, **full (≥5 A)**, BT input only, no FC | New FW (BENCH_TEST): booted to Idle fine, sensors OK; sent `G` (bring-up) | Supply hit **5–7 A with collapsed voltage**; **BT boost fried** |
| **Death 4** | DC supply, **8.2 V / 200 mA limit** on BT input (board-powered), no FC | `RC-BT` reverted to **61.2 kΩ**; **known-good FC TPS61288 moved to BT pad** (regulated 17.5 V standalone after reflow); sent `G` (gentle; bus pre-charged ~7.7 V through the **enabled** `D-BT-EN`, sourced from the body-diode-held boost output — mechanism name corrected 2026-08-03, review BOOST-R1-F6; measured in `2-VBUS.jpg`) | Draw **immediately pegged 200 mA CC**, voltage collapsed; **BT boost fried** (`VBT`↔GND short) |

Other confirmed conditions:
- `BT_SEQUENCE_ENABLE` (battery → charger): **ON in deaths 1–3** (as reported at the time).
  **Death 4: UNCERTAIN, likely OFF** — the operator initially logged it ON but later recalled it was
  off; under the BENCH_TEST firmware used for Death 4, the power stage (including `BT_SEQUENCE`)
  boots LOW and `G` does not touch it, so OFF is the more likely state unless manually toggled.
  (Moot for causation either way: the 2026-07-07 surviving runs also had it OFF, so the only delta
  vs Death 4 is the added output caps.)
- In death 1 the FC boost was **already disconnected** when BT was connected (not a paralleling fight).
- Post-mortem each time: `VBT → GND` short (the dead boost: VIN–SW–VOUT fused to GND).
- **Death 4 conditions** (most controlled yet): `MOT_PWR_ENABLE`, `REGEN_ENABLE`,
  `FC_CHARGE_ENABLE` all OFF; `FC_BUS_ENABLE` **ON** (raised by `G` unconditionally —
  record corrected 2026-08-03, review BOOST-R1-F6; harmless: FC boost dark and unsourced,
  RT1987 reverse-blocks → no bus contribution); `BT_SEQUENCE_ENABLE` likely OFF (see above);
  `BT_BUS_ENABLE` brought up by `G` in sequence with `BT_REG_ENABLE`. `G` energizes the bus
  switches **first**, so the bus was pre-charged to ~7.7 V before the boost soft-started —
  **not** a 0 V hot-plug. *Mechanism corrected 2026-08-03 (review F6):* the **source** of the
  7.7 V is the boost's HS body diode holding VOUT ≈ VIN, but the **path to the bus** is the
  enabled `D-BT-EN` conducting (a *disabled* RT1987 has back-to-back FETs and no passive
  path). Under the 200 mA CC limit the connect was supply-limited, not ISCP-limited: 40 µF to
  7.7 V at 0.2 A = 1.5 ms, inside `BUS_SETTLE_MS` = 5 ms. **This pre-charge holds only for
  the pre-2026-07-08 `bringUpBus()`, which left `MOT_PWR_ENABLE` LOW** — see the 2026-08-01
  dual-channel entry for why the bus no longer retains it.
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
2. `2-VBUS.jpg` — VBUS: **true 0 V** (trace on the CH1 ground marker) → **8.3 V step at
   ~1.3 ms before the boost ramp** → ramp to 17.7 V, flat for the rest of the capture.
   *(Caption corrected 2026-08-03, review BOOST-R1-F6: the step is the **enabled** `D-BT-EN`
   conducting at low voltage ~3.7 ms after its EN — not a passive body-diode path. It
   completed because the only load behind the switch in this firmware generation was the
   ~40 µF bus ceramics (`MOT_PWR_ENABLE` still LOW pre-Death-5): 0.33 mC at the ~7.5 A
   foldback ≈ 44 µs ≪ the 250 µs SCP window. Note the connect edge measures ~0.12 ms vs a
   ~554 µs gate-ramp prediction — plausibly already an ISCP-clamped amps-class event
   [UNCONFIRMED, review N5]. Also: the flat post-ramp VBUS does NOT establish "no hiccup this
   run" — VBUS is blind to a VOUT hiccup behind D-BT-EN's reverse blocking, per the
   "Startup hiccup explained" note.)*
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

### Recurring FAULT_OV_BUS on `G` — nondestructive; BT boost still regulating at pre-retune ~17.4 V (2026-07-31)

**Context:** the 16 V bus retune (Death-5 action 2) was executed as a hardware bodge on
2026-07-11 — RD1 changed 237 k → 215 k **on both boost FB networks** per the firmware changelog,
expected V0 = 15.91 V no-load — and firmware followed (`V_BUS_NOMINAL = 16.0f`, so
`LIMIT_V_BUS_MAX = 17.0 V`, no longer 18.5).

**Configuration:** battery-side-only DC supply (no FC source); BENCH_TEST build; State-98 `G`
bring-up. Nondestructive — hardware survives repeated attempts.

**Observed:**
- ~80 % of `G` attempts latch **0x8004 = `FAULT_ERROR | FAULT_OV_BUS`** essentially immediately;
  ~20 % come up without fault.
- Scope, BT boost VOUT: body-diode pre-charge ~3.8 V → soft-start ramp to **17.4 V in ~1.32 ms**,
  then flat **regulation at 17.4 V** (one brief deep transient dip with fast recovery — consistent
  with an RT1987 downstream-cap hand-off, benign with the bodge caps fitted). Captures currently
  chat-only; file into `references/scope_captures/` (pending).
- Scope, VBUS: never seen above what the operator believed the OV limit to be. **The paradox is
  resolved by the stale limit assumption:** the firmware limit is now **17.0 V**, not 18.5 — a bus
  tracking a 17.4 V boost through the RT1987 (~0 V drop) *is* over the current limit even though it
  never approaches 18.5 V.

**Diagnosis (leading, UNCONFIRMED):** the BT boost is regulating at the **old 237 k setpoint**
(design 17.5 V; measured 17.4 V here, 17.7 V in the 2026-07-07 validation), not the retuned
15.91 V — i.e. **the RD1 215 k bodge is electrically absent on the BT channel** (never applied
to BT, wrong value, or lifted/cold joint). The arithmetic fits: ΔV0 = Vref·ΔRD1/RD2 ≈ +1.5 V
over 15.91 V ≈ 17.4 V. Firmware then does exactly what it should: 17.4 V > `LIMIT_V_BUS_MAX`
(17.0) → `FAULT_OV_BUS` → State-99 teardown. The 80/20 intermittency is the bus sitting *at* the
threshold: whether a given attempt trips depends on the ramp hand-off transient and where the
ADC samples land (divider tolerance / noise), not on any real state difference.
**Settling measurement:** board unpowered, ohm RD1 on the BT FB network (expect 215 k; 237 k
confirms); or measure each boost's no-load VOUT standalone — FC at ~15.9 V with BT at ~17.4 V is
conclusive.

**Safety implication if confirmed:** the abs-max headroom the 16 V retune was supposed to buy
(4 V to the 20 V SW/VOUT abs-max) is **absent on the BT channel** — it still runs at ~17.4 V
nominal (~2.6 V headroom), on the channel with the worst hot-loop history. Fixing the bodge is
hardware-protective, not just fault-silencing. Do **not** paper over it by raising
`LIMIT_V_BUS_MAX`.

#### UPDATE (2026-07-31, same day) — RD1 theory REFUTED; revised diagnosis: parked load-dump overshoot, peak-held by the ideal diode

The settling measurements were done and **refute the missing-RD1-bodge diagnosis above**:
- **Standalone (bus switches open), each boost regulates 15.9 V** — the retuned FB network is
  correct and effective on both channels.
- **OPA197 output reads 0 V at no load** — the injection pedestal is at its design point; the
  FB/injection network is exonerated entirely.
- (RD1/RD2/RINJ could not be ohmed reliably in-circuit — readings drift, likely cap charging —
  but the standalone V0 makes the resistor values moot.)
- **MDACs are inactive in this test** (no SPI-driven droop), so the injection chain contributes
  only its static op-amp-at-0V pedestal (included in the 15.91 V design V0). Droop therefore
  explains NOTHING here — neither the level of the first flat (it is plain V0 regulation, not
  droop-depressed) nor the post-dip level. Any overshoot must come from converter/load-transient
  dynamics.
- Additional observation: the ramp → dropout → recovery-overshoot signature **only occurs
  bus-connected**; the overshoot reaches 17.2–17.5 V. Standalone bring-up is a single clean ramp
  to 15.9 V, every time.

**Revised leading mechanism (UNCONFIRMED, pending dual-channel capture):** a **load-dump
overshoot that gets peak-held on the unloaded bus** by the RT1987:
1. `G` closes the RT1987s at ~4 V pre-charge, then the boost ramps. The bus/motor-node charging
   demand through the RT1987 exceeds its SCP during or just after the ramp → the RT1987
   disconnects; the boost regulates its local caps at the true V0 ≈ 15.9–16 V (the first flat
   level — previously misread as the anomaly's "before" state; it is in fact correct regulation).
2. The RT1987 auto-retries: the re-strike connects the still-lower bus node → inrush surge →
   the deep Vout dip in the capture.
3. The surge terminates abruptly (node caught up, or SCP cuts again) with the boost's error amp
   railed from the dip → the converter keeps delivering amps into now-unloaded local caps for
   the voltage-loop latency (~50–250 µs at the 4–19 kHz crossover) → **Vout overshoots V0 by
   ~1.3–1.6 V** (≈100 µC into ~50–80 µF — easily available).
4. **The RT1987 is an ideal diode, i.e. a peak detector:** it charges the near-unloaded bus
   (~40 µF, only divider/quiescent load, ~mA) up to the overshoot peak and then blocks reverse.
   Both nodes then decay at only ~50–100 V/s, so the 17.2–17.5 V peak **parks for tens of ms** —
   ample for `detectFaults()` to sample `V_bus` > 17.0 → `FAULT_OV_BUS` (0x8004). A boost cannot
   sink current, so nothing pulls it back down. *[Decay rate SUPERSEDED 2026-08-03 (review
   BOOST-R1-N1): capture-5 metrology measures ~113 V/s (VESC quiescent + dividers on the
   ~590 µF attached node) — the rail spends only ~1.5 ms above 17.0 V per event. The peak-hold
   mechanism stands; the "tens to hundreds of ms" duration does not.]*
5. The ~80/20 intermittency is the peak amplitude/timing sitting marginally about the 17.0 V
   limit. Nondestructive because 17.5 V is well under the 19 V OVP / 20 V abs-max.

Why standalone never shows it: no downstream caps → no RT1987 SCP/re-strike events → no load
dump → no overshoot. Why the earlier VBUS capture looked benign: a parked 17.2 V at 5 V/div is
easy to misread, and the operator's assumed limit was the stale 18.5 V.

**Supporting capture (same day, 5 ms/div, BT VOUT on `G`):** pre-charge flat → soft-start ramp
to **regulation at 16.0 V** (cursor-measured; in-circuit regulation is correct, small notch on
the ramp shoulder = first, mild event) → flat 16.0 V for ~9 ms → a **second, deeper dip** →
recovery **overshooting to 17.4 V (ΔY = 1.4 V cursor-measured)** and **parking flat with no
visible decay for the remaining ≥15 ms** of the capture. Matches the predicted signature:
discrete re-strike events, regulation between them, load-dump overshoot parking after the deep
event. Decay math says the park is effectively indefinite on firmware timescales: the only
loads are the dividers (~70 µA FB-side on ~76 µF local → ~1 V/s; ~310 µA BUS-V divider on
~40 µF bus → ~8 V/s), so falling from 17.4 below the 17.0 limit takes ~50–400 ms — dozens to
hundreds of `detectFaults()` samples. *[Divider-only decay math SUPERSEDED 2026-08-03 (review
BOOST-R1-N1): the motor node + VESC are attached during `G` (MOT_PWR raised with the bus
switches), so the real load is ~38 mA on ~590 µF → measured ~113 V/s, ~1.5 ms above 17.0 V.]*
Plausible event identification (UNCONFIRMED): first event
= D-BT-EN charging the small bus caps; second = D-MT-EN re-strike into the 470 µF motor node
(the RT1987's ~1.17 ms CSS soft-start cannot carry that charge → SCP → retry ~ms later).
*[Second-event identification SUPERSEDED 2026-08-03: capture-5 metrology shows the deep dip is
the D-BT-EN soft-start COMPLETING into bus+motor node — see the corrected capture-5 subsection.]*

**Settling measurement (remaining):** dual-channel single-shot on `G` — BT VOUT + VBUS (expect
VBUS stepping at each re-strike, then peak-parking at the overshoot), and a second run with VBT
on ch2 to rule supply sag in/out. A stiff supply is NOT expected to fix this (the dump is
RT1987-inrush-driven, not source-sag-driven) — that itself is a discriminating prediction. If
the second event is D-MT-EN, a capture with the motor path left open (`G` modified or MOT
refused) should show only the first, mild event and no parked overshoot.

#### Datasheet reconciliation (2026-08-01, RT1987 DS §17.1–17.6) — firmware timing bug CONFIRMED; SCP-cut link NOT confirmed (retitled 2026-08-03, review BOOST-R1-F5: the original "mechanism CONFIRMED on paper" overclaimed — capture 5 later falsified the SCP-cut link, see below)

Reading `references/Datasheets/RT1987_DS-00.pdf` closes the loop quantitatively:

- **`tD_ON` = 8 ms (typ)** from EN rising to VOUT reaching 10% — the RT1987 does NOT begin
  conducting for ~8 ms after enable. **`BUS_SETTLE_MS` = 5 ms is therefore too short: the
  boosts ramp at t = 5 ms while every RT1987 is still in its turn-on delay.** The
  "pre-charge the stack at low voltage, ramp everything together" design (Death-5 fix)
  never actually executes — the switches connect ~3 ms *after* the boost is already at
  16 V, i.e. a full-ΔV connect into discharged nodes, exactly what the sequencing was
  meant to prevent. (The old comment "RT1987 soft-start ≈ 1.17 ms + margin" sized the
  settle from `tON` and missed `tD_ON` entirely.)
- **Start-up SCP is a foldback current limit + a 250 µs *continuous-clamp* timer** (§17.5):
  the limit starts at 2.5 A (VOUT < 2 V) and rises inversely with VIN−VOUT; **the timer
  resets whenever the current drops below the limit**; on trip, auto-retry after
  `tSCP_RST` = 64 ms. *(Corrected 2026-08-03, review BOOST-R1-F5: the 2.5 A figure applies
  only at ΔV ≥ 26 V — unreachable on a ≤17 V bus. Interpolating the EC points (2.5 A @ ≥26 V,
  7 A @ 10 V, 8.5 A @ ≤5 V) gives ≈5.3 A at ΔV = 16 V, rising to 8.5 A as the bus catches
  up.)* At CSS = 5.6 nF, `tON`(16 V) ≈ 1.07 ms → connect demand for the measured ~590 µF
  bus+motor node ≈ 0.8·C·V/tON ≈ **7 A vs the ~5.3 A applicable limit → the connect is
  protection-MARGINAL at ramp start — NOT a guaranteed trip** (superseding this bullet's
  original "guaranteed, every time"). Capture 5 in fact shows a connect that **completed**:
  1.77 ms of continuous conduction (7.1× the timer), no cut, no 64 ms retry, current
  terminating exactly as ΔV → 0 — it survived because the boost sagged (realised ramp
  9.5 kV/s, not 15), keeping the drawn 5–6.9 A under the rising foldback limit. The DS's
  one-liner still applies: *"Large output capacitors may require a longer soft-start time."*
- **SCP is disabled once soft-start completes** — a fully-enhanced RT1987 passes the boost
  ramp current (4–9 A, well under 8 A cont/20 A peak) with no protection involvement. So a
  *completed* low-voltage soft-start makes the subsequent boost ramp safe by design.
- **Timeline now fully explains the long capture:** switch ENs at t = −5 ms → boost ramp
  at t = 0 (unloaded → clean 1.3 ms rise to 16.0) → D-BT-EN conducts at t ≈ +3 ms
  (8 ms after EN; 40 µF bus caps → ~0.6 A → the small notch) → bus valid re-arms D-MT-EN
  (VIN-good) → its own ~8 ms delay → **t ≈ +11 ms: D-MT-EN soft-starts into the discharged
  470 µF+VESC node at full ΔV → foldback clamp → 250 µs timer → cut** (the deep dip's end
  = load dump → boost overshoot parks at 17.4) → next retry at +64 ms, outside the
  capture window (hence no third event). Observed second-dip spacing ~9 ms vs predicted
  ~11 ms — within typ-value scatter. *[Deep-dip portion of this timeline SUPERSEDED
  2026-08-03 (review BOOST-R1-F5): capture-5 metrology shows the deep dip IS the bus+motor
  node charging through a soft-start that COMPLETES (VBUS ramps 0.9 → 16.85 V during it; no
  cut, no retry). The tD_ON arithmetic and the dip-#1 timing stand.]*
- **CSS sizing (§17.3, corrected 2026-08-03, review BOOST-R1-F2):** `tON = VIN/35 ×
  (CSS/0.0023 − 100)` µs (CSS in nF); tON is the DS-defined 10–90 % time, so demand
  `I = 0.8·C·VIN/tON` and the full 0→VIN charge takes tON/0.8. CSS = **100 nF →
  tON(16 V) = 19.8 ms** (full ramp 24.8 ms) → **0.65 A per mF** of node capacitance.
  **Measured node (capture 5, bare board, no VESC input caps counted separately):
  ∫I dt ≈ 7.4–9.3 mC ÷ ~16 V ≈ 0.4–0.6 mF → 0.3–0.4 A demand — a 6–8× margin to the
  2.5 A ramp-start clamp.** Bounds, not guarantees: ISCP and tON are both **typ-only**
  (EC: no min/max), and 2.5 A is the *typ initial value* at VOUT < 2 V, not a minimum.
  Demand reaches 1 A at C ≈ 1.55 mF and the ramp-start typ at C ≈ 3.87 mF (worst-case
  CSS −10 % tol −15 % X7R drift: 1.16 / 2.90 mF). **Open qualification: the VESC Six
  EDU's input capacitance is unmeasured anywhere in this project** — it would have to add
  > 2.3 mF to break the bound; measure it before using guarantee language. Dissipation:
  ½CV² = 64–77 mJ at the measured node (128 mJ at 1 mF), P_peak = 2×P_avg ≈ 5–10 W over
  ~25 ms; **NOT datasheet-qualified** — §17.2 defers SOA to "example calculations and SOA
  curves" in Application Information, and §18 contains neither (verified). A θJC-only
  estimate puts ΔTJ ≈ 30 °C at the measured node — comfortable vs OTP 140 °C — but this
  is an inference, not a spec. *(This bullet's original "SCP never engages in any
  scenario" and "SOA-class, acceptable" are superseded as overclaims.)*

**Conclusions (rewritten 2026-08-03 per review BOOST-R1-F1/F2/N4):**
(1) **The open-loop settle is REJECTED at any fixed value** (superseding the original
"≈ 20 ms"). Measured chain from switch EN (capture 5, lower bounds — taken with the boost
already delivering ~8 A): tD_ON expiry/first attempt at **8.1 ms** (vs 8 ms typ ✓), silent
retry, D-BT-EN conduction at **17.7 ms**, VBUS full at **18.5 ms**, motor-node charge
complete at **19.3 ms** — leaving ~0.7 ms (3.5 %) margin on a typ-only/no-max spec; with
the boosts OFF (the fix's own scenario) the pre-charge takes longer or SCP-trips into the
64 ms retry; and with 100 nF CSS fitted a fixed delay would need ~33 ms. **Gate boost
enable on V_bus AND V_rgn ADCs confirming the pre-charge landed, with a timeout →
`FAULT_INIT_FAIL`** (the `BUS_CHARGE_TIMEOUT_MS` pattern). The gate needs its own
low-voltage thresholds — `V_BUS_CHARGED_THRESH` (13.5 V) is a post-boost constant; the
pre-charge plateau is only ~3.4–8 V (both ADCs resolve it: 4.55 / 7.15 mV/count). The
chain is NOT 8+8 ms serial: D-MT-EN's tD_ON does not re-run when its VIN rises with EN
already high (bench + DS §17.2).
(2) a CSS increase on D-MT-EN (5.6 nF → ~100 nF) cuts the connect demand to **0.3–0.4 A on
the measured 0.4–0.6 mF node (6–8× margin)** — the strongest hardware lever, and
self-limiting for C_node ≲ 2.9 mF (worst-case CSS) — **not unconditionally**; qualify the
VESC-attached capacitance first. Belt and suspenders: do both. Neither is implemented yet.

#### Dual-channel capture (2026-08-01, 2 ms/div: CH1 = BT VOUT, CH3 = VBUS) — theory refined

**Confirmed (direct capture):**
- **VBUS sits at ~0 V (≤0.9 V measured) through the entire boost ramp and for ~10+ ms after**
  — direct proof the RT1987s are not conducting during the ramp (`tD_ON` ≫ `BUS_SETTLE_MS`),
  and a **correction to a long-standing assumption: there is no PASSIVE (body-diode) path
  that pre-charges the bus.** The disabled RT1987's back-to-back FETs fully isolate; the
  ~3.8 V "pre-charge" seen on earlier captures is the boost's LOCAL output node upstream of
  the switch. **Scope of this correction (added 2026-08-03, review BOOST-R1-F6 — does NOT
  supersede the 2026-07-07 record):** the bus *can* still be pre-charged through an
  **enabled** switch conducting at low voltage, and `2-VBUS.jpg` measures exactly that
  (0 → 8.3 V step before the boost ramp). What changed is the configuration, not the
  physics: the post-Death-5 `bringUpBus()` also enables `D-MT-EN`, hanging 470 µF + the
  VESC behind the bus at a pre-charge level (~3.4–3.8 V) straddling D-MT-EN's 3.0–3.35 V
  rising VIN-UVLO, so the low-voltage connect no longer completes and is drained back —
  hence VBUS ≈ 0 here. **Under current firmware timing, assume every bus connect is a
  full-ΔV (≈16 V) connect.**
- **VBUS then ramps 0 → ~16.5 V in ~1.5–2 ms** — a textbook RT1987 soft-start signature,
  matching the CSS = 5.6 nF `tON` math. This is D-BT-EN's (first successful) soft-start,
  observed ~12 ms after the boost ramp ≈ 17 ms after switch EN (timing convention
  normalised 2026-08-03: quote times from the boost-ramp fiducial; the 8 ms `tD_ON` is
  typ-only with no max — size any firmware delay from measurement, not typ).
- **The deep dip fires exactly as VBUS completes its ramp.** *[Its SCP-cut interpretation
  ("clamp ending in the 250 µs-timer cut; the cut is the load dump") is SUPERSEDED
  2026-08-03 (review BOOST-R1-F5): capture-5 metrology shows 1.77 ms of continuous
  conduction terminating as ΔV → 0 — the soft-start COMPLETES; the release at convergence
  is the unload. Park readings here (ΔY = 1.4 V cursor) are edge-to-edge over-reads;
  centre-to-centre parks are +0.65–0.72 V — see the metrology conventions.]*

**Inferred (SS-pin unconfirmed — see bench matrix item 3):**
- Since D-MT-EN acts within ~1 ms of bus-good (no fresh 8 ms delay) but shows soft-start
  behaviour, its `tD_ON` does not re-run after a VIN-UVLO cycle but its soft-start does.

**Revised/open:**
- The small first dip (~3 ms after ramp, ~8 ms after EN) is **NOT D-BT-EN connecting** — VBUS
  doesn't move at it. In this run the park to 17.4 V happened at THIS event (before the bus
  ever rose); in the 5 ms/div run the park happened at the deep dip instead. Identity
  UNCONFIRMED (possibly internal turn-on/charge-pump activity at `tD_ON` expiry, or an
  aborted first attempt); a ~0.5 A × ~150 µs unload is enough to park +1.4 V given the boost
  cannot sink. Run-to-run, whichever unload event catches the loop wound parks the rail.
- **New caveat for the firmware-only fix:** even with a correct (≥ ~20 ms measured) settle,
  the low-voltage pre-charge the bus reaches is only ~Vsupply − 0.5 V(body) − 35 mV ≈ 3.4–3.8 V
  on this bench — **right at D-MT-EN's VIN UVLO (3.0–3.35 V rising)**. Below it, D-MT-EN
  never pre-charges the motor node and the full-ΔV connect just happens later. On a 2S pack
  (~7.9 V) the margin is comfortable; on low bench supplies it is not. The CSS fix is immune
  to this corner too — further weight on doing both.

#### Research round (2026-08-01) — dip #1 candidates, overshoot arithmetic, compensation verdict

Three research passes (RT1987 startup behaviour; boost-side artifacts; compensation assessment
vs TI SLVA452/TPS61288 DS §9.2.2.5) produced the following. No RT1987 field literature exists
(part is Sept-2024-new; no errata/forums) — bench measurement will out-produce further search.

**Overshoot arithmetic (scope corrected 2026-08-03, review BOOST-R1-F3/F8 — retained as a
model bound, WITHDRAWN as clamp-current evidence).** In its *linear regime* the gm-amp loop
gives unload overshoot `ΔV = ΔI·V_OUT/[R_C(1−D)·V_REF·G_EA·K_COMP]` — independent of C_OUT
**in that regime only** (adding C_O at fixed R_C lowers f_c proportionally; the 2026-07-07
bodge-cap non-observation is uninformative either way: +10 µF on ~106 µF predicts a 0.13 V
change, inside the ±0.15 V run-to-run scatter). At the capture's own operating point —
V_IN ≈ 8.2–8.7 V, read off CH1's 8.0 V body-diode pre-ramp (the original 0.24 V/A end
assumed V_IN = 12 V, which the 2S battery channel never sees) — the coefficient is
**0.32–0.35 V/A**. Direct measurement supersedes all back-calculation: the shunt shows
**6.3–7.2 A** released (see the corrected triple-channel entry), and the *centre-to-centre*
parks are **+0.65–0.72 V** (the 1.4–1.5 V cursor ΔY over-reads edge-to-edge across trace
thickness), giving an empirical **0.10–0.19 V/A that BOTH candidate models over-predict**
(linear 0.32–0.35; EA-slew ~0.6–0.7). **The overshoot mechanism is OPEN** — settled by one
COMP-pin probe through a `G` — and with it the question of whether added C_OUT is a real
mitigation (slew regime: park ∝ 1/C_node → yes; linear regime → no). The earlier "0.5 A
predicts only ~0.17 V" remark survives as order-of-magnitude only.

**Dip #1 combined ranking:**
1. **Shared-VBT logic load step** (Teensy+PHY behind the LM1084 on the same rail): line
   transient → loop winds → park on recovery. One story for the whole signature; precedent for
   unloaded-TPS610xx park on TI E2E (TPS61088, secondary source). Weakness: dip #1 appears
   phase-locked ~8 ms after EN (≈ tD_ON), which a logic load step shouldn't be.
2. **RT1987 aborted first soft-start attempt (foldback clamp, 250 µs timer):** onset timing
   perfect, width fits, and the new ΔV/ΔI math *supports* an amps-class event — but the
   observed ~4–9 ms silent retry contradicts the specified 64 ms `tSCP_RST` (unexplained by
   anything found; would be reportable to Richtek if confirmed).
3. **RT1987 internal bias/charge-pump brownout at the tD_ON hand-off** (aborts before the FET
   engages): explains the flat bus perfectly, retry unconstrained by the 64 ms spec — but every
   documented ideal-diode bias current is µA–20 mA class, far below an amps event.

**Ruled out:** RT1987 quiescent draw (650–780 µA — 1000× too small), TPS61288 PFM/burst ripple
(documented mV-class), OVP on either part (thresholds 18.3–19.5 V / 23–33 V untouched), TRCB
chatter (diode strongly forward-biased throughout).

**Discriminating bench matrix (in value order):**
1. **✅ DONE (2026-08-01): INA253 current output (`BT-CURR`) vs boost VOUT + VBUS, through both
   dips.** Result: **~700–900 mV peak on the INA253A1 (100 mV/A) = 7–9 A peak through the
   shunt, on BOTH dips.** Dip #1 is a real amps-class conduction event from the boost into the
   switch stack — **candidate 1 (shared-VBT logic load step) REFUTED** (the shunt would read
   ~0) and **candidate 3 (internal bias draw) refuted as the load** (µA–mA class). **Dip #1 =
   D-BT-EN's first turn-on attempt conducting hard and being cut short.** What cuts it remains
   open: a true SCP-timer trip predicts the 64 ms retry (contradicted by the observed ~4–9 ms
   silent retry), so either an undocumented abort path (bias collapse under gate-drive load?)
   or an SCP variant with fast retry — the SS-pin/FLTB probe (item 3) still discriminates, and
   the anomaly is Richtek-reportable. *(Foldback comparison re-sited 2026-08-03, review
   BOOST-R1-F3: only dip #1 sees the high-ΔV condition — its 7.2 A vs the ~2.5 A ramp-start
   typ is the genuine spec exceedance. The deep dip fires at bus-top where the 8.5 A-typ
   value applies and the measured 7.8 A band-top is a match, not an anomaly.)*
   **Charge bookkeeping constraint — HARDENED 2026-08-03 (review BOOST-R1-N3):** capture-5
   metrology bounds VBUS motion at dip #1 to **≤0.023 V (≤4 µC)** while 0.6–1.3 mC left the
   boost — a **14–300× charge-conservation violation** that excludes every delivered-charge
   mechanism (real SCP clamp, UVLO race). Surviving candidates: an **oscillatory/ring event
   half-rectified by the unipolar INA253A1** (REF = GND — it cannot render the negative
   half-cycles, so the one-sided trace is not evidence against a ring), or a **CH2
   common-mode artifact** during the multi-volt step (the 4.4 V VOUT dip is real either way).
   **Stress note:** every `G` currently puts 7–9 A load-dump events through the boost, shunt,
   and RT1987 — survivable (validated by many nondestructive repeats) but the same event
   family as the death history. Minimize gratuitous `G` cycles until the CSS fix is in.
2. **Separate logic supply + VBT on ch2** — no longer needed for dip #1 (cand. 1 refuted);
   still good bench hygiene.
3. **RT1987 SS pin (+ FLTB)** — identifies the CUT path
   (real SCP trip w/ anomalous retry vs pre-/mid-attempt internal abort).
4. **Zoomed 20–50 µs/div single-shot on dip #1** (trigger CH2 rising edge) — now the TOP
   bench priority (2026-08-03): separates a flat DC clamp from a rectified ring envelope,
   yields true pulse width/charge, and shows any VBUS motion in the same shot. Supersedes the
   original "VBUS at 1–2 V/div" item — capture 5 already bounds VBUS motion at ≤0.1 V.

**Compensation verdict: DO NOT change the TPS61288 compensation now** *(scope corrected
2026-08-03, review BOOST-R1-F8)*. The R_C lever stays rejected on measured grounds: f_c =
13.5 kHz vs f_RHPZ/5 = 16.6 kHz at the BT derated-C_O corner leaves only a 1.23× legal
increase (worth ≤0.4 V), and R_C is load-bearing for the Youla-H share plant (τ_r ∝ 1/f_c).
Bandwidth cannot shorten a park behind a peak-holding ideal diode. **Corrections:** (a) the
original "more C_OUT does NOT help (ΔV independent of C_OUT)" was a *linear-regime-only*
result — in the EA-slew regime the park is ∝ 1/C_node, so added C_OUT is a real ~1:1
mitigation *if* that regime is confirmed (COMP-pin probe decides; see the corrected
mechanism discussion). The bodge-cap non-observation cannot discriminate (predicted effect
0.13 V < the ±0.15 V scatter). Park *duration above the OV limit* actually falls with
C_node. (b) the C_C lever (2 nF → 1 nF, doubles EA slew) carries **NO share-plant
collateral** — DS Eq. 12 contains no C_C (recomputed: f_c moves <0.1 %, τ_r <0.1 µs; real
cost is 5–11° of a 76–79° phase margin, gate on a bench load-step ringing check) — the
original "same re-synthesis collateral" dismissal was wrong. Both cap levers are **open
secondary mitigations**, behind CSS, which uniquely removes the events. (c) "CSS dominates
5–10×" holds if CSS keeps the loop linear (ΔV ≈ 0.24–0.39 V at 1 A); if a shallower dip
still rails the EA it is 2–2.5× — either way it dominates.

#### Capture 5 filed + re-read at full resolution (2026-08-03) — two corrections, one new alternative

`references/scope_captures/5-Vout yellow-Vmot blue-Ibat purple.jpg` (CH1 Vout 5 V/div, CH3
VBUS 5 V/div, CH2 INA253A1 500 mV/div = 5 A/div, 2 ms/div). Re-reading against the earlier
chat-photo transcriptions:

- **This run parks at 17.5 V (cursor Y1 = 16.0, Y2 = 17.5, ΔY = 1.5 V)** — not 17.4/1.4.
  Confirmed run-to-run park range 17.2–17.5 V, i.e. up to exactly the new `LIMIT_V_BUS_MAX`;
  marginal trips remain expected even at +1.5.
- **The deep-dip current event is a WIDE hump, not a cut-short clamp:** ~7–10 A sustained for
  ~1 ms+. Integrated charge ≈ 8–10 mC ≈ 470 µF·17 V + bus caps ≈ 8.7 mC — **the motor-node
  charge actually COMPLETES around the deep-dip event in this run.** This weakens the "SCP
  250 µs timer cut = the load dump" detail (a completed charge naturally terminates its own
  current, which can also be the release that parks the rail). Park mechanism (wound loop +
  no sink + ideal-diode peak-hold) unaffected.
- **~~During the deep dip, VBUS appears to HOLD near top~~ — REFUTED by pixel metrology
  (2026-08-03, review BOOST-R1-F5): VBUS does the OPPOSITE.** It sits at ~0.9 V for the full
  12 ms before the deep dip and **ramps monotonically 0.91 → 16.85 V DURING it**, meeting
  VOUT as VOUT sags to a 9.68 V floor; afterwards VBUS peak-holds (~16.5 V) while VOUT parks
  and decays. The deep dip is a **capacitive charge transfer into the bus + V-MOT node
  through a soft-start that COMPLETES** (conduction 1.77 ms = 7.1× the SCP timer; current
  tapers, τ ≈ 124 µs, as ΔV → 0; no cut, no 64 ms retry; measured node ≈ 590 µF = 470 µF +
  VESC + bus, consistent with `bringUpBus()` raising MOT_PWR with the switches). **The
  VIN-UVLO-hiccup alternative floated here is RETIRED:** the 9.68 V VOUT floor is *above*
  the 8.10 V input-passthrough level with 5–7 A still flowing out — a UVLO'd, non-switching
  converter can do neither. What the floor *does* show: the source (VBT supply + boost) was
  the binding current constraint for ~1.8 ms — the boost is driven into sag/current-limit on
  every `G` (Death-5-class stress, repeated). Residual question (VBT sag vs the boost's own
  15 A limit): **VBT on a spare channel through one `G`** still discriminates.
  (**Channel correction 2026-08-03: this CH3 trace was V-MOT, not VBUS** — the ramp described
  is the motor-node charge; see the global reconciliation below.)
- **Dip #1 bookkeeping sharpened:** the coincident INA needle is ~7–10 A but narrow; even
  100 µs at that current is ~1 mC, which has no DC destination that matches VBUS staying flat
  (40 µF would jump ~19 V+). Either the needle is far narrower than the photo suggests, or
  the event is substantially **oscillatory (ring envelope through the shunt, net charge ≈ 0)**.
  UNCONFIRMED; zoomed single-shot on dip #1 would settle it.

**Plan refinements surfaced (open operator decisions — REVISED 2026-08-03 per review
BOOST-R1-F7/F9/N1):**
- **Windowed OV — the 18.0 V variant is WITHDRAWN** (review F7): the threshold is a firmware
  *reading*, and the reading is uncalibrated. The divider is ±0.1 % thin-film (BOM ERA-3AEB
  parts → only ±30 mV), but the ADC references the Teensy's 3.3 V rail with no calibration
  (~±2 %, dominant): worst-case reading→true multiplier ≈ 1.026, so a reading of "18.0" can
  be a true **18.47 V** — above the TPS61288 OVP *min* (18.3 V) and its **recommended VOUT
  max (18 V, §7.3 — a rung the original ladder omitted)**. Highest tolerance-legal window =
  **17.5 V**. Corrected ladder: 16 nom / 17.0 FW armed / 17.5 FW windowed / 18 rec-max /
  18.3–19.5 OVP / 20 abs-max. **Caveat: no legal window rides out the observed parks**
  (cursor peaks reach 17.5), so a 17.0/17.5 window's only real value is restoring the tight
  detector outside bring-up. Preconditions if implemented: ADC calibration + raw-count
  logging first (see TODO below); specified arming/hard-expiry/re-arm/State-99 interaction;
  the CSS fix (park ≤ ~0.7 V) clears a 17.0 blanket outright and makes any window moot.
- **Persistence filter REVIVED** (review N1 — supersedes "a short persistence filter would
  NOT ride it out"): measured park decay is **~113 V/s** (VESC quiescent + dividers on the
  ~590 µF attached node), so the rail spends only **~1.5 ms above 17.0 V** per event — a
  2–3-sample filter rides it out. Cheapest firmware mitigation on the menu; gate on one
  decay-confirmation run and a test that it cannot mask a genuine sustained overvoltage.
- **Optional bleed on VBUS — largely OBSOLETED by the measured decay** (review F9): the node
  already self-discharges in ~ms. If fitted anyway (2.7 kΩ 0.5 W ≈ 6 mA): decay figures
  depend on the node model (bus-only 40 µF: 2.5–7.5 ms for 0.4–1.2 V; bus+local ~76–120 µF:
  5–22 ms); it dissipates **95–113 mW continuously through Idle/Run/Finish** (`doState3()`
  leaves the bus energized); and share-loop immunity comes from quantization (6.4 mA ≈
  0.8 ADC LSB at `SCALE_I` ≈ 8.06 mA/count), NOT from `powerBalance()`'s 1 µA gate (a
  divide-by-zero guard, not a filter).
- **TODO (review F10/N2):** `V_bus` here is a scope-cursor quantity; `analogRead(BUS_VOLTAGE)`
  is unfiltered with an assumed 3.3 V reference (±0.26 V at 17.5 V). Before citing any
  firmware-reported voltage as precise, log raw BUS ADC counts + timestamps around `G` and
  calibrate at 16.0/17.5 V against a DMM. One such run also settles the observed node
  discrepancy: capture-5's VBUS (the ADC's node) peaked at **16.85 V — below the then-armed
  17.0 limit — while the 17.5 V cursor sat on the boost-local node**; whether the trips fire
  on real bus voltage, calibration error, or node identity is open until then.
  (**N2's node-discrepancy premise dissolved 2026-08-03** — the 16.85 V trace was V-MOT; see
  the reconciliation. The calibration/raw-count TODO stands.)

#### Triple-channel capture with INA253 current (2026-08-02, amplitudes corrected 2026-08-03) — dip #1 IS an RT1987-side conduction event

Capture: CH1 BT VOUT (5 V/div), CH3 VBUS (5 V/div), CH2 INA253A1 output (500 mV/div,
0.1 V/A → 5 A/div), all probes 1×; filed as
`references/scope_captures/5-Vout yellow-Vmot blue-Ibat purple.jpg`. **Both dips coincide with
real forward current pulses through the BT output shunt, peak ≈ 7–9 A each.** *(Amplitude
provenance note, 2026-08-03: an earlier version of this entry recorded "1.5–1.9 A" — a
transcription artifact from an abandoned working branch (division count with the 5 A/div factor
dropped), corrected by the operator. Photometric re-read of the filed capture — pixel scale
calibrated two independent ways agreeing to 0.6 %, CH2 zero verified against its ground marker:
**dip #1 needle 7.2 ± 0.4 A** (FWHM ≈ 180 µs as rendered, charge ~0.6–1.2 mC); **deep-dip hump
6.3 A ripple-band centre / 7.8 A band top**, FWHM ≈ 1.4 ms, **∫I dt ≈ 7.4 mC** (envelope
5.1–9.6 mC) vs ~8.7 mC to fill 470 µF + bus — the motor-node charge substantially (~85 %)
completes.)* Park cursor this run: 16.0 → **17.5 V (ΔY = 1.5 V)** — parking exactly AT the
interim OV limit, explaining the residual marginal trips.

**Consequences (rewritten 2026-08-03 with the corrected amplitudes):**
- **Shared-VBT/logic-rail candidate is DEAD** (it predicted ~zero shunt current), and with it
  the boost-internal artifact candidates. Dip #1 is definitively a downstream (RT1987-side)
  conduction event — the boost delivered ~7 A toward D-BT-EN's VIN at the tD_ON mark.
- **Overshoot mechanism (linear vs EA-slew-limited): OPEN.** At the corrected amplitude the
  measured park (1.5 V from a 6.3 A hump-centre release) is bracketed by BOTH models: the
  linear coefficient at the capture's own VIN ≈ 8.2–8.7 V (read off CH1's 8.0 V body-diode
  pre-ramp) is 0.32–0.35 V/A → predicts 2.0–2.2 V (over by ~1.4×); the EA-slew model
  (COMP railed by the multi-volt dip — the 5.9 V sag refers 223 mV onto FB, 2× the 111 mV
  linear knee — then 20 µA into C_C = 2 nF → 10 V/ms slew-down) predicts
  I_dump·t_slew/C_node ≈ 1.2–2.0 V with the motor node attached (~510 µF). Neither is
  excluded; the park amplitude alone cannot discriminate. **Settling measurement: one COMP-pin
  probe through a `G`** (does COMP rail?). Which model applies decides whether added C_OUT is
  a real mitigation (slew regime: park ∝ 1/C_node → yes; linear regime: C_OUT-independent →
  no); see the review-corrected compensation verdict above.
- **Safety corollary (rescaled with the corrected numbers):** at the linear 0.32–0.35 V/A,
  reaching the 19 V OVP band needs a ~9–10 A dump and the 20 V abs-max ~12 A — the observed
  7–8 A dumps sit uncomfortably close to the former. Capping the dump < 1 A via CSS bounds the
  park ≤ ~0.35 V (linear) / ~0.3–0.7 V (slew) — categorically safe under either model.
- **Compensation verdict UNCHANGED as a design decision (CSS first)** — but per the 2026-08-03
  review round: the C_C lever (2 nF → 1 nF) carries NO share-plant collateral (DS Eq. 12
  contains no C_C; recomputed f_c moves < 0.1 %, τ_r < 0.1 µs; cost is 5–11° of a 76–79°
  phase margin), and added C_OUT helps if-and-only-if the slew regime is confirmed. Both stay
  open as testable secondary mitigations behind CSS, which uniquely removes the events.
- **Measured clamp currents (7.2 A needle / 6.3 A hump centre) sit WITHIN the RT1987's typ
  foldback band** (2.5–8.5 A curve): the deep dip fires at bus-top where the 8.5 A-typ value
  applies (measured band top 7.8 A ✓). **Dip #1 at 7.2 A vs the ~2.5 A ramp-start typ for its
  high-ΔV condition genuinely exceeds spec — Richtek-reportable.** Take 6.3–7.2 A (band
  centre – needle peak) as this unit's empirical dump amplitude; peaks to 9 A on band-top
  readings.
- **Dip #1 charge-destination puzzle — UVLO race REFUTED (2026-08-03, review BOOST-R1-F5/N3):**
  ~0.6–1.3 mC left the boost while VBUS moved **≤0.023 V (≤4 µC)** — a 14–300×
  charge-conservation violation. The UVLO-race sub-hypothesis needed the bus to pop
  0.91 → 3.35 V (86 px on the capture; measured ≤2 px) — dead, along with every other
  delivered-charge mechanism. **Surviving candidates: (a) an oscillatory/ring event
  half-rectified by the unipolar INA253A1** (REF = GND — it cannot render negative
  half-cycles, so the one-sided trace does not exclude a ring), **or (b) a CH2 common-mode
  artifact** during the multi-volt step (the 4.4 V VOUT dip is real either way; the 7.8 A
  amplitude need not be). Discriminator: **zoomed 20–50 µs/div single-shot, trigger CH2
  rising** — top bench priority; the SS-pin/FLTB probe remains complementary.
  (**RESOLVED 2026-08-03: CH3 was V-MOT; the charge went into the unmonitored 40 µF VBUS** —
  see the reconciliation below.)
- **Park metrology note (2026-08-03, review N6):** the 16.0/17.5 cursor pair reads
  edge-to-edge across ~0.2 V-thick traces and over-states the step. Trace-centre parks are
  **+0.72 V (dip #1) and +0.65 V (deep dip)** above the immediately-preceding level, decaying
  at ~44–113 V/s. Both dips parked the rail in this run (the "whichever event catches the
  loop" framing becomes "both, amplitude set by the release current").

#### Capture 6 — dip #1 zoomed single-shot (2026-08-03; `6-dip 1 zoomed in.jpg`) — ring hypothesis DEAD; conservation violation sharpened to a two-way fork

Settings (per metrology conventions): 50 µs/div, 500 MSa/s, BW Full, all probes 1×; CH1 Vout
5 V/div; CH2 INA253A1 500 mV/div = 5 A/div; CH3 VBUS 5 V/div; cursors Y1 = 16.0 / Y2 = 17.5 V.

**Measured:** CH2: single **smooth unipolar lobe**, peak 1.4 div × 5 A/div = **6.9 A**, width
≈ 2 div ≈ **100 µs** (smooth ~60 µs + small hashy tail), **∫I dt ≈ 0.25–0.4 mC**. CH1: V-dip
1.15 div × 5 V/div = **5.75 V deep** (floor ≈ 10.3 V), ~100–150 µs, recovery parking on the
17.5 V cursor (**+1.5 V park from a ~7 A/60 µs release ≈ 0.21 V/A** — new datapoint for the
open linear-vs-slew question). CH3: **flat** — conclusive at this timebase/sample rate.

**Conclusions:**
- **Ring/net-zero hypothesis DEAD** (was a surviving candidate from review BOOST-R1-N3): any
  ≥100 kHz oscillation resolves at 500 MSa/s; the lobe is smooth and one-sided.
- Earlier width/charge (180 µs / 0.6–1.2 mC) were photo-exaggerated → **~60–100 µs / ~0.3 mC**.
- **Source-side bookkeeping CLOSES:** local bank (~35–50 µF derated) × 5.75 V = 0.2–0.3 mC ≈
  the lobe charge — the dip IS the local caps delivering the lobe.
- **Destination-side violation stands** (bus absorbs ≤0.05 mC at generous bounds). Surviving
  fork, exactly two: **(a) the RT1987 internally sank ~7 A from VIN for ~60 µs during the
  aborted turn-on** (VIN→GND through the part — undocumented, ~10,000× its spec'd 650 µA IQ;
  Richtek-reportable if confirmed), or **(b) common-cause artifact pair** — the boost briefly
  reverse-conducts ~0.3 mC into VBT (a path bypassing the output shunt) causing the dip, while
  the INA253 lobe is a common-mode transient artifact of the 5.75 V/50 µs step that
  coincidentally mirrors it. (a) keeps the measurement honest but breaks the datasheet;
  (b) keeps the datasheet but needs a coincidence. (**CLOSED 2026-08-03: CH3 was V-MOT — the
  charge went into the unmonitored 40 µF VBUS; both fork candidates dead.** See the
  reconciliation.)
- **Discriminator (one run): VBT on the spare channel at this zoom.** (b) predicts a visible
  upward VBT blip (~0.3 mC into the input bank) coincident with the dip; (a) predicts
  flat-or-sag. Same acquisition also answers the deep-dip source-limiting question.

#### Capture 7 + the 400 mV pre-charge test (2026-08-03; `7- dip 1 zoomed in-5Vrail yellow-Vbt blue-Ibat purple.jpg`) — dip-1 cut mechanism IDENTIFIED (VIN-UVLO abort, documented); bench pre-charge functionally IMPOSSIBLE at 5.6 nF CSS

**New steady-state datapoint (operator):** boost disabled (VOUT = 8.4 V body-diode-held from
VBT), `BT_BUS_ENABLE` on → **the bus rises to only ~400 mV**, never toward 8.4 V. The
low-voltage pre-charge does not merely arrive late — it does not happen.

**Capture 7** (50 µs/div, 500 MSa/s; CH1 **5 V logic rail** 2 V/div *(channel attribution
corrected by operator 2026-08-03 — originally logged as VOUT; file renamed to match; VOUT was
unmonitored this run and is taken to behave per capture 6)*; CH2 INA253A1 500 mV/div =
5 A/div; CH3 **VBT** 2 V/div; cursors Y2 = 8.60 / Y1 = 3.40, ΔY = 5.20 V): coincident with
the ~8 A dip-1 lobe, **VBT collapses 8.6 → 3.4 V for ~150–200 µs**, then recovers.
**The 5 V logic rail sags ~1 V (to ~4.3–4.6 V) during the event** — consistent with the
LM1084 (dropout ~1.3 V) fully in dropout at VBT = 3.4 V and the rail riding its output caps
under the ~200 mA logic load; it snaps back on VBT recovery (the scope trigger was CH1
falling through 4.16 V, i.e. the rail sag itself). Teensy 3.3 V regulation survives at
4.3 V input, but with <1 V margin: **each dip-1 event brings the board-powered MCU within
one deeper/longer event of a brownout — measured confirmation that the separate-logic-supply
bench rule is load-bearing** (a mid-bring-up MCU reset is the motorboating precursor from
the death history).

**Conclusions:**
- **Dip-1 cut mechanism IDENTIFIED — VIN-UVLO abort, a documented behaviour (§17.1), not an
  undocumented internal path.** The turn-on inrush collapses the current-limited source; the
  RT1987's VIN (≈ VBT − body drop ≈ 2.9 V at the floor) crosses its falling UVLO (~2.93 V) →
  path disabled → source recovers → re-enable. **The ~9.5 ms "anomalous silent retry"
  dissolves:** a UVLO cycle re-runs the enable sequence, and UVLO-recovery + tD_ON (8 ms typ)
  matches the gap. *(Residual tension, UNCONFIRMED: D-MT-EN was observed conducting <1 ms
  after first-VIN-application — apparently skipping tD_ON — while D-BT-EN re-runs it after a
  UVLO cycle. First-application vs UVLO-cycle re-arm may differ; SS-pin probe would settle.)*
- **The capture-6 fork RESOLVES: the current is real.** An INA253 CM artifact cannot collapse
  a power supply, and the boost-reverse-conduction variant would push VBT *up*, not crash it
  5.2 V. Both artifact readings are dead. The charge-destination puzzle (bus flat in capture
  6) remains, narrowed to through-flow or abort-time discharge — next probes: **motor-node
  voltage (V_rgn / State-98 `S`) during the disabled-boost retry loop**, and the bus at fine
  vertical scale (per-retry sawtooth?). (Fork fully closed 2026-08-03 — see the CH3 = V-MOT
  reconciliation.)
- **The Death-5 pre-charge sequencing has NEVER functioned on the bench, and cannot, at
  CSS = 5.6 nF on a current-limited supply:** attempt → ~8 A inrush → source collapse → UVLO
  abort → ~10 ms retry loop → bus parked at leakage-level mV. This supersedes the framing of
  the timing bug as the sole obstacle (the 5 ms/tD_ON bug is real but not sufficient to fix).
  On a stiff 2S pack (~50–100 mΩ → ~0.5–0.8 V sag at 8 A) the pre-charge is *expected* to
  complete even at 5.6 nF — UNCONFIRMED, bench-verify before relying on it.
- **Fix ordering consequence: the CSS bodge must PRECEDE the ADC-gated settle.** At 100 nF
  the pre-charge attempt inrush is ~26 mA-class (0.8·40 µF·8.4 V / 10.4 ms) — no source on
  this bench collapses at that draw, the UVLO-abort loop cannot start, and the pre-charge
  completes on any supply → the gate then passes and is meaningful. With 5.6 nF still
  fitted, the gate would (correctly) refuse every bench bring-up. Verification once CSS is
  fitted is trivial: boost off, `BT_BUS_ENABLE` on → bus must climb to ~VBT − 0.5 V.
- **Safety note:** each dip-1 event yanks VBT to ~3.4 V for ~150 µs — below the LM1084's
  dropout for the board-powered logic. The standing separate-logic-supply bench rule is
  load-bearing here, not optional.

**INTERIM MITIGATION APPLIED (operator decision, 2026-07-31):** `LIMIT_V_BUS_MAX` raised from
`V_BUS_NOMINAL + 1.0` (17.0 V) to **`+ 1.5` (17.5 V)** so marginal bring-ups proceed. This
matches the Death-5 ladder (nominal 16 < FW 17.5 < OVP 19 < abs-max 20) and keeps firmware
first in the protection order. Caveats: observed peaks reach "even 17.5 V", so occasional trips
remain possible; and the limit change treats the symptom — the RT1987 SCP re-strike cycling
(and its repetitive load-dumps on the boost) still happens on every `G`. **Root-fix candidates
(open design decision):** slow the D-MT-EN soft-start so it can carry the 470 µF charge without
SCP-tripping (larger CSS — hardware, one cap), stage the node charge in firmware, or a
bring-up grace window on `FAULT_OV_BUS`. *(The original "park lasts ~50–400 ms, so a short
persistence filter would NOT ride it out" is SUPERSEDED 2026-08-03, review BOOST-R1-N1:
measured decay ~113 V/s → ~1.5 ms above 17.0 V → a 2–3-sample persistence filter IS viable.)*

#### ⭐ FIX VALIDATION (partial) — Capture 8: first `G` with CSS = 100 nF (2026-08-03; `8-Vout yellow-Vmot blue-Ibat purple.jpg`)

**Single variable changed:** CSS 5.6 nF → **100 nF** (operator; fitted on **`D-BT-EN` ONLY**,
operator-confirmed 2026-08-03 — **`D-MT-EN` remains at 5.6 nF**). Same bench config otherwise
(current-limited supply on VBT, State-98 `G`). No VESC attached this run; FC side unpowered.

**Scope state:** 5 ms/div, delay 26.5 ms, 10 MSa/s, trigger Edge CH1 rising (DC); CH1 BT VOUT
5 V/div 1×; CH2 INA253A1 500 mV/div 1× = 5 A/div (BW setting not recorded); CH3 VBUS 5 V/div 1×.
Cursors X1 = −0.2 ms (VOUT ramp start) → X2 = 28.1 ms (bus ramp complete), ΔX = 28.3 ms;
Y1 = 15.9 V (standalone regulation) / Y2 = 17.5 V.

(**Channel correction 2026-08-03: CH3 was V-MOT, not VBUS** — see the global reconciliation;
the 'VBUS' readings in this entry are motor-node readings.)

**Measured timeline** (t = 0 at boost enable / VOUT ramp):
- t < 0: VOUT ≈ 8 V (VBT body-diode passthrough), VBUS ≈ 0.9 V, I ≈ 0.
- t ≈ 0: VOUT ramps to **15.9 V** (Y1 cursor on it — the 16 V retune's standalone level, again).
- t ≈ 18.4 ms: **one** conduction event — CH2 spike ≈ 1.4 div × 5 A/div ≈ **7 A**, width sub-ms
  (photo-limited; ≲ 1 ms → ∫I dt ≈ 2–6 mC envelope); VOUT notches to ≈ 10 V and recovers with a
  brief pop grazing ~17.5 V; VBUS steps fast 0.9 → ≈ 11 V (± 1 V trace-centre).
- t ≈ 18.4 → 28.1 ms: VBUS **ramps linearly ~0.6 V/ms** to ≈ 16.2–16.4 V. No visible CH2 current —
  implied 590 µF × 0.6 V/ms ≈ **0.35–0.4 A** (< 0.1 div at this scale, consistent).
  *(superseded 2026-08-03: topology operator-confirmed — 470 µF is on V-MOT; the bus-side node
  here was ~40 µF and the ramp current correspondingly ~24 mA, equally invisible at 5 A/div;
  the C-derived current figures in this entry are assumption-dependent, see the capture-9
  retraction note)*
- t > 28.1 ms (~30 ms of record): both traces **flat**. VOUT trace-centre ≈ **17.0 ± 0.3 V**
  (clearly ~+1 V above its own pre-event 15.9 V level, and now *below* the 17.5 cursor);
  VBUS ≈ **16.2 ± 0.3 V**.

**Validated:**
- **Timing formula and single-shot sequence:** ΔX 28.3 ms vs predicted tD_ON (8 ms typ) +
  tON(16 V, 100 nF) = 19.8 ms → **27.8 ms, a 1.8 % match**. Also evidence the RT1987 ran its full
  enable sequence from the **boost-enable/VIN-step instant**, not from switch-EN 5 ms earlier
  (that would predict 22.8 ms from trigger) — feeds the open tD_ON re-arm question; mechanism of
  the restart UNCONFIRMED.
- **The UVLO-abort retry loop is GONE:** one event, no dip-1/deep-dip pair, no ~9.5 ms retry
  signature, run completes. (VBT was unmonitored this run — supply survival is inferred from the
  absent retry structure, not measured.)
- **The rail no longer parks at/above the limit:** post-event VOUT ≈ 17.0 V trace-centre vs
  17.2–17.5 V pre-fix — under the interim 17.5 V `LIMIT_V_BUS_MAX`, and the ADC's node (VBUS)
  ends ≈ 16.2 V, well clear. Expected outcome: no `FAULT_OV_BUS` — **CONFIRMED (operator,
  2026-08-03): no `FAULT_OV_BUS` trip, > 4 consecutive clean `G`s — fix validated for the
  no-VESC bench config.**

**NOT as predicted (model revisions):**
- **The ~26 mA gentle-connect prediction is DEAD.** The linear-gate-ramp inrush model
  (0.8·C·V/tON) predicted tens of mA; observed is a **two-phase connect**: conduction onset
  (~53 % into the gate ramp, where gate ≈ V_bus + Vth) dumps ~**2/3 of the node charge
  (0.9 → 11 V ≈ 6 mC) at foldback-class ~7 A in ≲ 1 ms**, and only the top ~5 V rides the
  gate-ramp at ~0.4 A. Reading (UNCONFIRMED): at onset the FET's current capability outruns the
  bus, the foldback SCP (~7 A mid-ΔV, matching the curve) governs until the source catches the
  gate, then the ramp governs. CSS therefore bounds the *duration/handoff point*, not the onset
  current. Consequence: the pre-charge verification (boost off, `BT_BUS_ENABLE` on) may still
  draw a foldback-class ~0.3 mC/40 µs surge at 8.4 V rather than 26 mA — the "no source collapses
  at 26 mA" rationale is weakened, though the far smaller charge should still be benign. Verify
  before relying on it.
- **Anomalous post-connect steady state (top open item):** VOUT − VBUS ≈ **0.5–0.9 V forward
  differential, flat for 30+ ms**. This fits *neither* standing model: a fully-enhanced RT1987
  should drop mV, and a parked (unregulated) node should decay at ~113 V/s — neither trace
  decays. VOUT sitting ~1 V above its standalone regulation point while *supplying* the bus node
  suggests either a pixel-read error (± 0.3 V bounds don't cover 0.7 V), a not-fully-enhanced
  diode regime, or a real regulation-point shift when bus-connected. **Settling measurement:
  DMM VOUT and VBUS after one `G`** (10 s), before restoring the 17.0 V limit — if VOUT really
  regulates ≈ 17.0 V bus-connected, a 17.0 blanket limit would re-trip on regulation, not parks.
  **RESOLVED (operator DMM, 2026-08-03): VOUT regulates 15.9 V in steady state — no
  regulation-point shift exists. The scope-window ~17.0 V was a slowly-decaying park (the
  boost-local node behind a barely/non-conducting diode leaks only through dividers, ~V/s
  class — cf. the same slow-park behavior in capture 9), and the 0.5–0.9 V differential was
  that decaying transient, not a standing regime. The 17.0 V limit restoration is unblocked
  from the regulation angle (still gated on review TODO N2, ADC node identity/calibration).**

**Consequences for the plan:**
- Fixed-settle firmware is now *measured* to need ≥ ~28–33 ms (review F1/N4's prediction
  confirmed in-family) — the **ADC-gated settle is unblocked and remains the only correct
  variant**; implement per the standing plan (CSS is fitted).
- Death-5-class stress per `G` is reduced (sub-ms at ~7 A vs 1.8 ms at 6–8 A, park −0.4 V) but
  **not eliminated** — the onset surge persists. If further reduction is wanted, the levers are
  the ones already open: pre-charge sequencing that actually completes (raises the onset point),
  C_C/C_OUT secondaries pending the COMP probe.

#### Capture 9 — VESC attached: SCP-cut + 64 ms retry observed for the first time; ~18 V park on the unmonitored boost node (2026-08-03; `9-Vout yellow-Vmot blue-Ibat purple-VESC.jpg`)

**Single variable changed vs capture 8: VESC attached at the motor output.** Config: `D-BT-EN`
CSS = 100 nF, **`D-MT-EN` still 5.6 nF**, VBT from a bench DC supply at 8.4 V, FC side
unpowered, State-98 `G`.

**Scope state:** 10 ms/div, delay 57.0 ms, 2.5 MSa/s, trigger Edge CH1 rising (DC); CH1 BT VOUT
5 V/div 1×; CH2 INA253A1 500 mV/div 1× = 5 A/div, DC coupling, **BW Limit Full** (menu captured
on-screen); CH3 VBUS 5 V/div 1×. Y cursors 15.9/17.5 V; X cursors carried over from capture 8
(not aligned to this run's events).

(**Channel correction 2026-08-03: CH3 was V-MOT, not VBUS** — see the global reconciliation;
the 'VBUS' readings in this entry are motor-node readings.)

**Measured timeline** (t = 0 at boost enable / VOUT ramp):
- t < 0: VOUT ≈ 8 V (VBT passthrough), VBUS ≈ 1.4 V (± 0.5), I ≈ 0.
- t ≈ 0: VOUT ramps to 15.9 V (on the Y1 cursor).
- t ≈ 18 ms: **dip 1 — D-BT-EN conduction onset, same ~18 ms mark as capture 8, but this time
  it ABORTS.** CH2 spike ≈ 2 div × 5 A/div ≈ **10 A** (operator live read; photo-consistent),
  width unresolvable at this timebase (≲ 1 ms). VBUS steps only ~1.4 → **~3.9 V** and stops.
  VOUT transient peaks ≈ **18 V** (operator live read; photo shows the excursion to
  ≈ 17.9–18.1 V), then parks ≈ 17.2 V decaying at only ~3 V/s.
- t ≈ 18 → 83 ms: dead gap, **~65 ms** (pixel read 64.5 ms): VBUS holds ~3.6–3.9 V, no current,
  parked VOUT slowly decaying.
- t ≈ 83 ms: **dip 2 — retry conducts and COMPLETES.** ~10 A lobe, ~1–2 ms wide
  (∫I dt ≈ 10–20 mC envelope); VBUS ramps 4 → ~15 V in ~2–3 ms; VOUT notches and recovers to
  ≈ 15.9–16.3 V with "acceptable overshoot" (operator). Bring-up succeeds; no OV trip reported.

**Conclusions:**
- **First clean observation of the RT1987 SCP-cut/retry fingerprint.** The ~65 ms gap ≈
  tSCP_RST = 64 ms (typ). With the VESC attached, D-BT-EN's onset surge trips SCP and latches
  off; the retry from the ~4 V pre-charged bus completes. (Contrast review BOOST-R1-F5:
  capture-5's deep dip was NOT a cut — both readings stand; SCP cuts happen when the node is
  big enough.)
- **The cut-release park confirms the empirical release coefficient:** 15.9 V + 10 A ×
  0.21 V/A = **18.0 V** — matching the observed ~18 V peak. Cut-release at full clamp current
  is the worst-case park; taper-release (dip 2) parks small. Consistent across captures
  5/6/8/9. (Still does not discriminate linear vs EA-slew — review F3 stays OPEN.)
- **Protection gap (safety-relevant):** the 18 V excursion lives on the **boost-local node
  behind the cut diode**; VBUS — the node `analogRead(BUS_VOLTAGE)` watches — sat at 4 V
  throughout. **`FAULT_OV_BUS` cannot see this event class.** Firmware cannot protect the boost
  from cut-release parks; only hardware can (CSS, bodge caps, possibly C_C). 18 V = TPS61288
  recommended-VOUT max, 0.3 V under the OVP-min band — operator's "unacceptably high" is
  correct.
- **470 µF topology now LOAD-BEARING and IN QUESTION.** The corrected failure analysis
  (2026-06-24) recorded the 470 µF on V-MOT *behind* `MOT_PWR_ENABLE` with VBUS carrying only
  ~30–40 µF. The operator's staged-bring-up proposal (below) places it **on VBUS proper**.
  Charge bookkeeping now leans the operator's way: (a) capture-8's onset step (0.9 → 11 V at
  ~7 A, sub-ms) and ramp current (~0.35–0.4 A at 0.6 V/ms) both fit a **~510 µF bus-side
  node**, not 40 µF (40 µF predicts a ~60 µs onset and ~24 mA ramp); (b) capture-9's dip-1
  charge (10 A × ~150 µs ≈ 1.5 mC ≈ 510 µF × 2.5 V) balances with 470 µF on the bus, while
  40 µF gives ~0.1 mC — a 10× deficit of the same N3 class; (c) D-MT-EN cannot have been
  conducting pre-dip-1 (its VIN = VBUS ≈ 1.4 V < RT1987 UVLO 3.0–3.35 V rising), so the extra
  capacitance was not the motor node. UNCONFIRMED — **settle by board/schematic inspection:
  which side of D-MT-EN does the 470 µF electrolytic sit on?** Every staged-bring-up design
  decision keys off this. **RESOLVED (operator confirmation, 2026-08-03): the 470 µF sits on
  V-MOT downstream of `D-MT-EN` — the 2026-06-24 record stands; the bus-side lean above is
  RETRACTED.** The retraction is a metrology lesson: the 'measurements' behind the lean were
  circular — spike widths are unresolvable at 5–10 ms/div (a 60 µs and a 700 µs event render
  identically as a thin vertical line), and the ramp current was inferred FROM an assumed node
  capacitance (40 µF at ~24 mA fits the captures exactly as well as 510 µF at ~0.4 A).
  Assumption-derived currents must not be cited as evidence of node size.
- **Why capture 8 was clean and capture 9 cut:** the single variable is the VESC. If the
  470 µF is bus-side, capture-8's D-MT connect saw a near-empty node (invisible — consistent
  with no second event in capture 8) and capture-9's larger effective node behind/at the
  connect pushed the onset past the SCP threshold. Exact path of the VESC capacitance into
  dip 1 is UNCONFIRMED pending the topology check and a V-MOT-probed run. **SUPERSEDED by the
  confirmed topology:** at dip-1 time BOTH captures had the same ~40 µF bus-side node (D-MT-EN
  cannot conduct below its VIN UVLO), so capacitance does not explain the difference.
  Reconciled reading (UNCONFIRMED): the cut/complete split tracks the onset peak against the
  RT1987's low-VOUT foldback limit (8.5 A typ @ ≤5 V) — capture 9's ~10 A exceeded it
  (start-up SCP cut), capture 8's ~7 A rode under it. Why the onset peak varied run-to-run
  with identical bus-side C is itself open (supply state / gate-race variation). Also open:
  capture-8's motor-node (470 µF) connect is not visible in-window — consistent with a warm
  (still-charged from a prior `G`) motor node or a post-window D-MT retry completion. (Itself
  superseded by the CH3 = V-MOT reconciliation: the unified >250 µs-clamp rule replaces the
  onset-peak reading.)
- **First in-system VESC capacitance bound (partially discharges review F2's 'unmeasured'
  item):** dip-2's ∫I dt ≈ 10–20 mC over the ~15 V motor-node charge requires the motor node +
  VESC to have charged through `D-BT-EN` during dip 2 (D-MT conducting by then) →
  **C_VESC ≈ 0.2–0.9 mF** (wide envelope; proper measurement still wanted). Corollary puzzle:
  with `MOT_PWR` HIGH and VBUS ≈ 3.9 V (above D-MT's UVLO) the bus HELD through the 65 ms gap
  instead of collapsing into the discharged ~1 mF VESC node — consistent with D-MT itself
  start-up-SCP-cutting each attempt (µs-scale, invisible at this timebase) and running its own
  64 ms retry loop. UNCONFIRMED; a V-MOT-probed `G` settles it. (Puzzle dissolved by the
  CH3 = V-MOT correction — the held 3.9 V node WAS the VESC node.)

**Operator proposal (2026-08-03, open design decision — staged bring-up):** remove
`MOT_PWR_ENABLE` from the initial `G` phase; charge VBUS (and its 470 µF, if bus-resident) to
regulation first, then enable `D-MT-EN` so the charged bus + boost source the VESC-node
connect. Assessment (pre-implementation): direction endorsed — it is the recorded "stage the
node charge in firmware" lever, and capture 9 accidentally demonstrated the principle (dip-2
retry from a pre-charged bus completed with acceptable overshoot). Prerequisites before
implementation: (1) ~~settle the 470 µF location~~ RESOLVED: V-MOT side (operator,
2026-08-03) — so phase 1 charges only the ~40 µF bus (trivially benign) and **phase 2 is the
full ~1–1.5 mF event (470 µF + VESC), sourced by the boost through `D-BT-EN` plus the 40 µF
bus — the 470 µF cannot 'assist'; it is part of the phase-2 load.** The empirical precedent
for phase 2 is exactly capture-9's dip 2 (same event class: charged bus + boost sourcing the
big node at ~10 A for ~2 ms, completed, acceptable overshoot); (2) **fit 100 nF on `D-MT-EN` first** — at
5.6 nF, closing MOT_PWR at full bus onto the discharged VESC node is the literal Death-5
event; (3) the firmware inversion is real: `motPwrHotPlugUnsafe()` / `assertMotPwrEnable()`
exist precisely to refuse what phase 2 would deliberately do, and CLAUDE.md §2's low-V
pre-charge doctrine would be superseded — coordinated rework of the guard semantics,
`doState0()` phases, State-98 `G`, and docs; (4) phase-2 first runs scope-armed — SCP
cut/retry during phase 2 remains possible even at 100 nF (capture 9 proves 100 nF does not
prevent cuts on a big node), and any cut-release park is invisible to firmware (see protection
gap above). Operator-floated hardware alternatives, assessed: a manual VESC-wire switch is
unnecessary (the staged sequence achieves the same isolation via D-MT in firmware); **bodging
extra capacitance onto VBUS is recommended AGAINST** — it would convert the now-benign
phase-1 connect back into a dip-1-class SCP-cut candidate with the ~18 V park, to provide an
assist the boost already supplies. Remaining hardware prerequisite: 100 nF on `D-MT-EN` only.

#### Operator correction (2026-08-03): CH3 in captures 5–9 was V-MOT, not VBUS — global reconciliation

**The cyan/CH3 trace in captures 5, 6, 8, 9 (and the dual-channel capture) was probing V-MOT**
— the motor node downstream of `D-MT-EN` (470 µF bulk; + VESC in capture 9) — **not VBUS.**
(Capture 7's CH3 was VBT; unaffected.) VBUS proper — the ~40 µF node between the source
switches and `D-MT-EN`, and the node `analogRead(BUS_VOLTAGE)` actually watches — **was never
scoped in this entire investigation.** Files renamed `…Vbus blue…` → `…Vmot blue…`; per-entry
claims below are superseded in place with pointers here. This is the third channel-attribution
error of the investigation (after the current-scale slip and the capture-7 5 V-rail mixup):
the metrology lesson is to verify the channel↔net mapping against the physical probe points at
capture time, not from memory.

**What the correction RESOLVES:**
- **Review N3 (dip-1 charge-conservation violation, 14–300×): RESOLVED — probe-node
  misattribution.** The ~0.3 mC that "vanished" went into the unmonitored 40 µF VBUS:
  0.3 mC / 40 µF ≈ 7.5 V, charging the real bus toward ~8 V before the VIN-UVLO abort cut it.
  Conservation closes exactly. Both fork candidates die — the undocumented-internal-sink
  hypothesis (and with it the Richtek-reportable framing; the dip-1 clamp comparison must also
  be re-read against the switch's true output node, VBUS proper at low V, where the 8.5 A typ
  band applies and 7.2 A is within spec) and the CH2 common-mode-artifact hypothesis (already
  killed by capture 7).
- **Review N2 (OV-trip node discrepancy): the anomaly DISSOLVES.** "VBUS peaked 16.85 V, below
  the then-armed 17.0 limit, while trips fired" — that 16.85 V was V-MOT. VBUS proper couples
  to the parked VOUT through the conducting `D-BT-EN`, so **the ADC was reading the parks
  correctly all along**; the historic ~80 % trip rate at the 17.0 limit is fully explained,
  and the interim 17.5 limit's clean captures 8/9 are consistent (parks ≤ ~17.2 trace-centre).
  The F10 calibration/raw-count TODO stands on its own merits; the node-identity mystery is
  closed. Note the ADC node itself remains unscoped — one VBUS-probed `G` would close the loop
  entirely.
- **A unified SCP-cut rule now covers every capture: a cut occurs iff the current actually
  rides the foldback clamp for > 250 µs (the documented continuous-clamp timer).** Capture-5
  deep dip: 6.3 A < the ~8.5 A low-V clamp → never clamped → 1.77 ms conduction, no cut ✓.
  Capture-8 onset: ~7 A < clamp → no cut ✓. Capture-9 dip-1: ~10 A at clamp for ≈ 250 µs
  (≈ 1 mF VESC-node × 2.5 V ≈ 2.5 mC ≈ 10 A × 250 µs — bookkeeping closes) → timer cut +
  64 ms retry ✓. The larger VESC node is what lets the current build to the clamp before ΔV
  collapses; no run-to-run mystery remains. This SUPERSEDES the previous round's "onset peak
  vs start-up SCP" speculation and dissolves the "bus held 3.9 V through the gap" corollary
  puzzle (the 3.9 V node WAS the VESC node) and the "D-MT self-SCP retry loop" speculation.

**Per-capture re-read:**
- **Capture 5 / dual-channel:** "VBUS ramps monotonically 0.91 → 16.85 V DURING the deep dip"
  → **V-MOT ramps**: the deep dip is the **motor-node (470 µF) charge through the full chain**
  (boost → D-BT → VBUS → D-MT), with D-MT the completing element. F5's mechanism conclusion
  (soft-start completing, taper release at ΔV→0, no cut) is intact; the charge arithmetic
  sharpens to exact (∫ ≈ 7.4 mC ≈ 470 µF × 16 V).
- **Capture 6:** "CH3 VBUS flat" → V-MOT flat (not yet connected); the destination-side
  "violation" was an artifact of watching the wrong node — see N3 resolution above. The
  two-way fork bullet is CLOSED.
- **Capture 8:** the cyan step-then-ramp was the **combined ~510 µF bus + motor node**
  charging through `D-BT-EN`'s 100 nF-gated ramp, with **D-MT transparent** — it conducts as
  soon as VIN arrives, consistent with (and strengthening) capture-7's residual-tension
  observation that tD_ON apparently runs from EN while VIN-starved. The earlier "~510 µF node"
  inference was numerically CORRECT; only its bus-side topology conclusion was wrong (the
  probe sat on the motor node). The "warm motor node / post-window retry" speculation dies —
  the motor node visibly charged in-window.
- **Capture 9:** dip-1 charged bus + (transparent D-MT) motor+VESC node; cut per the unified
  rule above. Dip-2 and the C_VESC ≈ 0.2–0.9 mF bound survive unchanged (the probed node IS
  the VESC node — attribution now clean).

**What SURVIVES unchanged:** F5's taper-release mechanism; the 0.21 V/A empirical park
coefficient and the ~18 V cut-release park; the CSS timing validation (28.3 ms); the SCP-cut +
64 ms retry identification; capture-8's fix validation (no trip, > 4 clean `G`s); the VIN-UVLO
dip-1 abort (capture 7) — whose source-side bookkeeping now closes too.

**Protection gap, sharpened:** firmware **sees taper-parks** (VBUS tracks parked VOUT through
conducting D-BT — those were our historic trips) but **is blind to cut-release parks** (D-BT
open → the 18 V excursion lived only on the boost-local node). `FAULT_OV_BUS` is a real
detector for the common case and blind to the worst case; the hardware fixes carry the worst
case.

**Staged-bring-up proposal: conclusions unchanged, rationale cleaner.** D-MT's transparency is
precisely why the whole ~0.5–1.4 mF chain charges as one `D-BT` event today; holding `MOT_PWR`
LOW in phase 1 genuinely shrinks phase 1 to the ~40 µF bus. Phase 2 (D-MT at 100 nF connecting
470 µF + VESC from the charged bus + boost) now has TWO empirical precedents: capture-5's deep
dip (completed at 6.3 A, no cut, park ≤ ~0.7 V — at 5.6 nF!) and capture-9's dip-2. Cut risk
in phase 2 exists iff the connect current rides the clamp > 250 µs — scope-armed first runs
stand.

#### Firmware implemented (2026-08-03): staged bring-up + OV persistence

The firmware round following the capture-9 staged-bring-up proposal is implemented in
`teensy_controller/teensy_controller.ino` (pending host-test green + adversarial review + bench
validation): shared non-blocking machine `busBringupTick()` (P0 bus pre-charge with MOT_PWR held
LOW → P1 boosts → P2 dwell → P3 motor-node connect from the regulated bus, each phase ADC-gated
with a timeout → FAULT_INIT_FAIL / FAULT_MOT_HOTPLUG), used by production `doState0()` and the
now-automatic State-98 `G` ('X'/'Q' abort and darken the stage); the hot-plug guard inverted to
`motPwrConnectBlocked()` (connect sanctioned ONLY from a regulated bus — supersedes the Death-5
low-voltage pre-charge doctrine in code); `FAULT_OV_BUS` latches only after 10 ms + 3 consecutive
over-samples (decaying parks show a truthful transient bit, no latch). `LIMIT_V_BUS_MAX` stays
17.5 V until bench validation (operator decision). HARDWARE PREREQUISITE before any P3 run:
100 nF CSS on `D-MT-EN`. Bench validation steps are in the plan's Verification section
(scope-armed first `G`, ≥4 clean cycles, then optionally restore 17.0 V).

#### Capture 10 — dual-source `G` with VESC: NON-CONVERGING 15.5 Hz SCP cut/retry limit cycle; motor node never charges; VESC boot-loops (2026-08-06; `10-Vbat yellow-Vmot blue-Ifc purple.jpg`)

**Config (deltas vs capture 9: FC side now powered; current probe moved to the FC INA):** bench
DC supply at **8.4 V on BOTH the battery and fuel-cell terminals**; VESC attached at the motor
terminal; State-98 `G`. **Firmware = the capture-8/9 build (git HEAD)** — i.e. the OLD
`bringUpBus()` that raises `MOT_PWR_ENABLE` with the bus switches at t = 0. **The staged
bring-up implemented above was NOT flashed for this run.** CSS: `D-BT-EN` = 100 nF; **`D-MT-EN`
(and, presumed, `D-FC-EN`) still 5.6 nF**. *(Presumption CORRECTED by operator 2026-08-07:
**`D-FC-EN` was ALREADY 100 nF in this run** — only `D-MT-EN` was 5.6 nF. This kills candidate
(a) below and, with capture 11's single-variable intervention, confirms `D-MT-EN` as the cutting
switch — see capture 11.)* Non-destructive: no parts died; the loop was still running when
captured.

**Scope state:** 10 ms/div, delay 57.0 ms, 5 MSa/s / 700 kpts; trigger Edge CH2 rising, DC
coupling, level 180 mV, Noise Reject off; **hardware counter on the trigger channel
f = 15.5366 Hz**. CH1 VBT 5 V/div 1× DC; CH2 **FC INA253A1** 500 mV/div 1× = 5 A/div (BW setting
not recorded); CH3 V-MOT 5 V/div 1× DC. The cursors on screen (ΔX = 30.0 ms; Y = 15.9 / 17.5 V)
are carried over from captures 8/9 and are NOT aligned to this run's events.

**Measured (steady state — the record is mid-loop; no bring-up start is in-window):**
- CH2 (FC current): flat ≈ 0 between events, with a repeating narrow spike ≈ 1 div × 5 A/div ≈
  **5 A photo-read**, width unresolvable at 10 ms/div (≲ 1 ms) — the true peak is photo-limited
  and, per the prior captures' foldback behaviour, plausibly the ~8.5–10 A clamp.
  **Period = 1/15.5366 Hz = 64.4 ms ≈ tSCP_RST = 64 ms (typ)** — the RT1987 SCP-retry
  fingerprint, for the first time **continuous and indefinite** (operator reports sustained
  audible clicking at this rate; two spikes in-window, spacing photo-consistent with 64 ms).
- CH3 (V-MOT): **sawtooth ratchet, trace-centre ≈ 5.5 → ≈ 7 V (± 0.7 V, photo perspective)**:
  a step of ≈ +1.6 V coincident with each current burst, decaying ≈ 1.3 V across each 64 ms gap.
  The motor node never approaches the bus.
- CH1 (VBT): ≈ 8.4 V throughout, small (≲ 1 V) level shifts correlated with the bursts; **no
  collapse — no VIN-UVLO retry signature** (not the capture-7 supply-collapse class; the supply
  is holding).
- VESC (operator): blue LED **blinks** and the VESC never boots; the same VESC shows a solid
  LED on an external supply. Clicking-noise source not identified (candidates: magnetics /
  ceramics under the 64 ms current bursts, or the VESC itself on each boot attempt) — a benign
  symptom either way.
- Unmonitored this run: VBUS proper (still never scoped in this entire investigation), both
  boost VOUTs, BT INA current.

**Reading — a charge-budget limit cycle (leading mechanism; switch attribution UNCONFIRMED):**
- Each SCP retry conducts only until the continuous-clamp timer cuts it: ~10 A × ~250 µs ≈
  **2.5 mC** into the ~1–1.5 mF motor+VESC chain ≈ **+1.6–2.5 V per retry** — matching the
  measured +1.6 V step (the capture-9 unified cut rule, applied per-retry).
- Between retries the node parks at ≈ 5.5–7 V — **inside the VESC's brownout/boot-attempt
  band** — and drains ≈ 1.3 V per 64 ms ≈ C·dV/dt ≈ **15–30 mA** (consistent with the VESC's
  logic repeatedly attempting boot; the blinking LED is this loop made visible). Charge-in ≈
  charge-out → **the ratchet converges to a fixed point below the bus instead of to the bus.**
  First observed non-terminating retry loop (captures 5/8/9 all completed or aborted); the
  qualitatively new ingredient is a *load* on the node being charged.
- **Which switch is cutting is UNCONFIRMED.** The bursts ride the FC INA, so the **FC boost
  sources them**. Candidates: (a) `D-FC-EN` (5.6 nF) cut/retrying into the bus+motor+VESC chain
  with `D-MT-EN` transparent (capture-9's dip-1 event class, now on the FC switch); (b)
  `D-MT-EN` cut/retrying from a bus held up by a source switch. Both fit the V-MOT sawtooth.
  **(RESOLVED 2026-08-07: (b). The operator correction above removes (a)'s 5.6 nF premise —
  `D-FC-EN` was already 100 nF — and capture 11 (single variable: `D-MT-EN` 5.6 → 100 nF)
  converges the identical configuration, attributing the cut to `D-MT-EN` by intervention.
  Corollary: the "17–18 V park on the sourcing FC boost every 64 ms" inference two bullets
  down weakens — the cut was downstream of the boost, through a conducting `D-FC-EN`, so the
  release energy lands on the VBUS node rather than an isolated boost output; consistent with
  no OV_BUS trip having been reported despite the then-armed single-sample 17.5 V limit. Where
  the per-retry release actually parked remains UNCONFIRMED — boost VOUTs and VBUS were
  unmonitored.)**
- **Why capture 9 converged and this run doesn't — open.** The added variable vs capture 9 is
  the powered FC side, whose 5.6 nF switch reaches conduction ~20 ms before the 100 nF
  `D-BT-EN`. *(Premise corrected 2026-08-07: `D-FC-EN` was 100 nF too, so the timing-asymmetry
  clause is void; the dual-source diode-OR and the VESC drain band remain the live
  candidates.)* Candidate contributors (unproven): the winning source's 64 ms retry rhythm
  perturbing the other switch's enable/enhancement sequence (diode-OR interaction), and the
  VESC drain band — capture 9's inter-retry park was 3.9 V, plausibly *below* the VESC's draw
  threshold, while this run parks inside it, so capture-9's dip-2 charged a quiet node.
  Standing tension noted: dip-2 conducted ~10 A for 1–2 ms *without* cutting, so the 250 µs
  timer model is incomplete — whether 100 nF on `D-MT-EN` raises the charge-per-attempt enough
  to escape the fixed point is likewise UNCONFIRMED until tried.
- **Discriminator (one run):** spare channel on the **BT INA** (does BT ever conduct?) and/or
  **VBUS proper** — the latter also finally closes the "ADC node never scoped" item and settles
  (a) vs (b) directly: (b) predicts VBUS held ≈ 16 V between bursts; (a) predicts VBUS
  sawtoothing with V-MOT.
- Inferred, UNCONFIRMED (boost VOUTs unmonitored): each cut-release should park the sourcing
  boost's local node at ≈ 15.9 + I × 0.21 V/A ≈ **17–18 V** per the empirical release
  coefficient — i.e. the FC boost may be taking a ~17–18 V park **every 64 ms**. *(Corrected
  2026-08-11, operator: this bullet originally said "un-bodged FC boost" — the FC boost DOES
  carry hot-loop bodge caps.)*

**Consequences:**
- **SAFETY — do not leave this configuration running.** Every burst is a Death-5-class SCP
  load-dump sourced by the **FC boost** *(corrected 2026-08-11, operator: this originally read
  "which has NO hot-loop bodge caps" — the FC boost DOES carry them; the load dumps remain
  Death-5-class stress, but with the validated overshoot mitigation fitted)* — at 15.5 Hz that is
  ~930 such events per minute, plus the inferred repeated ~17–18 V parks. The loop does not
  self-terminate; abort promptly (`X`/`Q` or power-down). Rule added to Safety rules below.
- **The low-V motor-node pre-charge doctrine is now bench-falsified in its target
  configuration** (VESC attached): it neither pre-charges the node (capture 7) nor lets the
  post-boost connect converge (this capture). This is the direct empirical case for the staged
  bring-up implemented above. Note that under the staged machine this same physics would appear
  in P3 and correctly **fail dark** via `MOT_CONNECT_TIMEOUT_MS` (500 ms ≈ 7 retries) →
  `FAULT_MOT_HOTPLUG` — with the VESC drain the cycle can outlast *any* timeout, so a P3
  timeout-fault is the *expected* outcome with a VESC attached until the charge-per-retry is
  raised (`D-MT-EN` CSS) or one conduction charges the node past the VESC's boot band.
- **Fix path unchanged, now ordered and blocking** (see Next steps): (1) fit **100 nF CSS on
  `D-MT-EN`** (the standing hardware prerequisite); (2) flash the staged bring-up (after its
  pending test/review gates); (3) scope-armed VESC-attached `G` with the discriminator channels
  above.

#### ⭐ FIX VALIDATION — Capture 11: 100 nF on ALL THREE switches converges the capture-10 configuration (2026-08-07; `11-Vout yellow-Vmot blue-Ibat purple-VESC.jpg`)

**Single variable vs capture 10: `D-MT-EN` CSS 5.6 nF → 100 nF** (operator-confirmed
2026-08-07 — `D-FC-EN` and `D-BT-EN` were already 100 nF in capture 10; all three switches now
carry 100 nF). A true single-variable intervention, which also settles capture-10's
switch-attribution question: **`D-MT-EN` was the cutting switch.** Same otherwise: dual bench
DC supplies (8.4 V battery + fuel-cell terminals), VESC attached, State-98 `G` on the **OLD
(pre-staged-bring-up) firmware** — the staged build was still not flashed.

**Scope state:** 5 ms/div, delay 28.9 ms, 10 MSa/s / 700 kpts, trigger Edge CH1 rising DC; CH1
BT VOUT 5 V/div 1×; CH2 **BT INA253A1 100 mV/div 1× = 1 A/div** (DC, BW Full — note the 5×
finer current scale vs prior captures); CH3 V-MOT 5 V/div 1×. Cursors X1 = 0 → X2 = 43.6 ms;
Y = 15.9 / 17.5 V.

**Measured:**
- CH1 (VOUT): steps ~8 → 15.9 V at t ≈ 0 (boost enable, on the Y1 cursor), then stays
  15.9–16.3 V for the whole record — **no dips, no overshoot, nowhere near the 17.5 V cursor.**
- CH3 (V-MOT): flat ~1 V until t ≈ 13 ms, then **one smooth continuous ramp ~0.5 V/ms to
  ~16 V, completing at X2 = 43.6 ms** — no steps, no sawtooth, no retry gaps.
- CH2 (BT current): a **broad ~0.7–1 A hump spanning the ramp** (≈ 0.7–1 div at 1 A/div), no
  spikes. ∫I dt ≈ 0.8 A × 30 ms ≈ **24 mC** ≈ the full chain charge — implying an effective
  motor-node+VESC capacitance ≈ 24 mC / 15 V ≈ **1.4–1.6 mF** (refines the capture-9 C_VESC
  bound upward: VESC ≈ 0.9–1.2 mF, wide envelope; BT-side share only — the FC INA was
  unmonitored, so total chain current may be up to ~2× if the sources split).
- Outcome (operator): clean bring-up, no fault, "working well."

**Conclusions:**
- **The capture-10 non-converging limit cycle is RESOLVED by hardware.** With all three
  switches at 100 nF, the same dual-source + VESC configuration that ratcheted at 15.5 Hz
  indefinitely now completes in one ~30 ms gate-ramp-limited pass at ~1 A — no SCP cut is even
  approached (clamp is ~8–10 A). ~930 Death-5-class events/min → zero.
- **First observed genuinely gentle whole-chain connect.** Unlike capture 8's two-phase onset
  (~2/3 of the charge at ~7 A), the V-MOT ramp here is gate-slew-limited end to end at ~1 A.
  Why the source-follower regime held this time is UNCONFIRMED (candidates: the VESC-loaded
  node's slower dV/dt keeping the FET inside the gate ramp; the D-MT 100 nF ramp governing while
  the bus switches were already enhanced) — a nice-to-know, not a blocker.
- **No park, no OV excursion** — consistent with no cut occurring (parks are cut-release
  artifacts).
- **The staged-firmware hardware prerequisite (100 nF on `D-MT-EN`) is SATISFIED**, and the
  P0-at-100 nF behaviour the new firmware assumes (benign switch-path pre-charge) is now
  empirically supported in-family. Remaining delta when the staged build is flashed: P0 holds
  the boosts OFF until the bus pre-charges (capture 11 had them on 5 ms in) — expected benign,
  first `G` scope-armed per the plan.
- **Remaining RT1987s (D-FC-CH, D-RG-EN, D-BT-SQ) deliberately NOT bodged (operator decision,
  2026-08-07).** Rationale: the SCP-cut class requires the clamp ridden > 250 µs ≈ > ~2 mC of
  demanded charge — only the mF-scale motor+VESC node qualifies (confirmed by the capture-10/11
  single-variable result). The charger-input nodes behind D-FC-CH/D-RG-EN are expected tens of
  µF (≲ 1 mC at 16 V → completes inside the timer, no cut, at 5.6 nF); D-BT-SQ is once-per-boot,
  input-side, stiff-pack-fed, anomaly-free, and physically inaccessible under the Ag105. Rework
  risk to a working board outweighs the speculative benefit. **WATCH ITEM:** the charge/regen
  paths are still bench-unexercised — scope the charger input node on the FIRST powered
  engagement of `FC_CHARGE_ENABLE` and of `REGEN_ENABLE`; the 64 ms retry fingerprint (clicking,
  ~15.5 Hz spikes, sawtooth) or Ag105 config/fault flapping in `pollAg105()` would mean the
  charger input capacitance is larger than assumed → bodge that one switch then, on evidence.

### TP0010 share-sweep bus collapse — nondestructive; ~17 Hz droop/dropout limit cycle drops VBUS to 6.5 V (2026-08-11; SD log `logs/TP0010`, no scope)

**Source: SD bench log only** (1 kHz-nominal logger, measured ~865 Hz effective / 1.15 ms
median sample interval, no drops), decoded via `tools/benchlog_analysis`. No scope was armed —
all numbers below are ADC-path readings through the firmware's `analogReadAveraging` chain, so
sub-millisecond structure (and any SW-node overshoot) is invisible. Scope-metrology
conventions apply to the follow-up capture, not to this entry.

**Conditions:** State-98 trapezoidal profile `T 6 3 1` (I_cmd 0→6 A at 1 A/s, 3 s hold, ramp
down), run 4 of a seven-run share-setpoint sweep (order 0.5, 0.7, 1.0, **0.3**, 0.0, 0.15,
0.85), `share_sp = 0.30` constant, Youla share controller active, `K_DROOP = 0.300 Ω`.
Firmware: pre-v1 (fw ledger "version 0"), `BENCH_TEST` build → **only OV faults armed; bus UV
cannot latch**. VBUS regulating ~15.9 V no-load. Supply configuration was not recorded in the
log (dual-source session per the sweep context; treat as unconfirmed). Share-controller state
carries over between runs (no reset at profile entry); TP0010 inherited TP0009's
rails-adjacent MDAC pair.

**Observed (from `logs/TP0010/TP0010.csv`):**
- t = 4.33–6.15 s (mid ramp-up, I_cmd ≈ 4.3–6.0 A, total channel current < ~1.2 A): a
  sustained relaxation limit cycle, **median period 58–59 ms ≈ 17 Hz, ~31–44 cycles**. The
  MDAC commands bang rail-to-rail each cycle (`gFC`/`gBT` ≈ 0.18 ↔ 0.90+), and the two boost
  channels conduct **mutually exclusively** (both conducting in only ~0.1 % of samples;
  `I_fc = 0` for 71 % of the window).
- **VBUS collapses during the handoffs: 64 excursions below 15 V, minimum 6.55 V**, each dip
  ~17–18 ms wide, with ~10–18 ms windows where *both* channels read zero current — the bus
  riding only its ~40 µF of ceramics. Sag depth grows monotonically with the I_cmd ramp
  (13.3 V at I_cmd = 4.4 A → 6.5 V at 6.0 A).
- Channel current spikes to **3.2 A (FC) / 3.6 A (BT)** at the ADC (8 mA LSB; true peak
  between samples unknown) — >2× the steady-state peak of any run in the sweep.
- **Self-clears at t = 6.15 s** once total current exceeds ~1.2 A; the rest of the run is
  clean (share error σ 0.011, no saturation, VBUS 15.75–15.91 V). Brief re-entry at
  t ≈ 13.5 s on the low-current tail.
- **Zero fault flags for the entire run** (expected: `BENCH_TEST` arms OV only). The
  persistence-filtered `FAULT_OV_BUS` never tripped either — the excursions are all downward.
- Milder sibling: **TP0013 (`share_sp = 0.85`)** shows the same signature at **18.5–18.7 Hz**
  as minority-channel (BT) dropout chatter during both ramps, `I_batt` pinned at exactly 0 for
  0.77 s / 1.36 s bands, but **no bus collapse** (only ~100 mV notches). Interior setpoints
  (0.15, 0.5, 0.7) and the degenerate endpoints (0, 1) are clean.

**Inferred mechanism (UNCONFIRMED — no scope):** a starved-minority-channel dropout limit
cycle in the share loop at low total current. The channel commanded to carry the small
fraction falls out of conduction entirely (droop command raises its effective source
impedance until its RT1987 blocks), measured share slams to 0/1, the controller rails both
MDACs, the starved channel slams back on with a large spike, repeat. What is NOT explained by
that loop alone is the **both-channels-off 10–18 ms windows** in TP0010 — candidates:
(a) both boosts simultaneously droop-commanded out of conduction during the crossover;
(b) **RT1987 SCP cut/retry participation** — the 58–59 ms period is suspiciously close to the
64 ms tSCP_RST fingerprint from captures 9/10 (15.5 Hz), and `D-FC-EN`/`D-BT-EN` carry 100 nF
CSS since 2026-08-07, lengthening each reconnect. A single scope capture (BT INA + VBUS
proper, trigger < 14 V) during a repeat at `share_sp = 0.3` on the ramp would discriminate:
SCP involvement shows the cut/retry sawtooth on VBUS; pure droop dropout shows conduction
handoffs without switch cuts.

**Why it matters despite being nondestructive:** ~33 both-channels-off collapse/reconnect
events per run with 3+ A reconnect spikes is Death-5-*family* stress (load-dump class, far
milder per event). Both boosts carry the validated hot-loop bodge caps (operator-confirmed
2026-08-11 — an earlier version of this entry wrongly called the FC boost un-bodged), which
bounds the known overshoot mechanism; the repeated collapse/reconnect duty is nevertheless
unscoped stress on the power stage. Repeat runs at `share_sp ≈ 0.3` with ramping load should
be treated as a known stressor until scoped.

**Firmware relevance:** the pending fw v1 features target this family — the
`SHARE_I_TOT_MIN_A = 75 mA` integrator hold and `applyShareRatio()` starved-channel cutoff
with hysteresis. But note: (1) TP0010/TP0013 misbehave at **in-band** setpoints (0.3, 0.85),
so the v1 out-of-band cutoff logic does not directly address them; (2) the limit cycle lives
at total currents up to ~1.2 A — **an order of magnitude above the 75 mA hold threshold** —
so the v1 integrator hold as parameterized would NOT have suppressed it. Flagged as a
follow-up firmware task (raise/ramp-gate the hold threshold, or rate-limit the MDAC slew),
not bundled into this entry.

#### Capture 12 — TP0010-condition repeat, scope-armed: total source-feed dropout confirmed; `D-MT-EN` ruled out as the cutting element; droop-vs-SCP NOT discriminated (2026-08-11; `12-Vbus yellow-Vmot blue-Ibat purple-P0.3.jpg`; retitled same day — the original title claimed "`D-MT-EN` SCP cut CONFIRMED", a trace misread, corrected below)

**This is the discriminator capture requested by the TP0010 entry above (Next steps §0c).**
Conditions (operator-confirmed 2026-08-11): repeat of the TP0010 configuration — State-98
trapezoid `T 6 3 1`, share setpoint 0.30 (the filename's "P0.3" is shorthand for the setpoint,
not the P profile), VESC attached, motor loaded. **No SD log was kept for this run** — the
scope photo is the only record; all cross-referencing to TP0010 is by condition, not by
synchronized timebase.

**Scope state:** 20 ms/div, delay 105 ms, 2.5 MSa/s / 700 kpts, trigger Edge CH1 **falling**
DC, level **14.0 V** (the "VBUS below 15 V" discriminator trigger — it fired). CH1 VBUS
5 V/div 1× (offset −15.0 V); CH2 **BT INA253A1 100 mV/div 1× = 1 A/div**; CH3 V-MOT 5 V/div
1× (offset −15.0 V). Cursors: X1 = 6.0 ms → X2 = 73.6 ms, **ΔX = 67.6 ms (14.79 Hz)**;
Y1 = 15.9 V, Y2 = 17.5 V, **ΔY = 1.6 V**.

**CORRECTION (2026-08-11, same day, operator):** the first analysis of this capture claimed
CH1 (VBUS) held near baseline while CH3 (V-MOT) sawtoothed volts below it, and concluded
`D-MT-EN` was SCP-cutting. That was a **trace misread** — the flat yellow feature near
15.9 V is the horizontal Y1 *cursor*, not the CH1 trace. Operator confirmation: **the yellow
(VBUS) and blue (V-MOT) traces overlap nearly everywhere; VBUS dips together with V-MOT**,
with no measurable separation at this resolution. Everything below is the corrected reading;
the original `D-MT-EN`-cut conclusion is retracted (another instance of the trace/cursor
misread class the metrology conventions exist for — this time in analysis, not transcription).

**Measured (photo re-read; provisional per metrology rules):**
- **Event period: 67.6 ms ≈ 14.8 Hz by cursor** — in the RT1987 `tSCP_RST` neighborhood
  (64 ms ≈ 15.5 Hz, captures 9/10) but also close to the TP0010 SD-log median (58–59 ms);
  the period alone does not discriminate.
- **CH1 VBUS and CH3 V-MOT, overlapping:** the two nodes move as one — repeating **slow
  linear ramps down ~0.6–0.8 div × 5 V ≈ 3–4 V** from the ~15.9 V baseline (at least one
  crossing the 14.0 V trigger), each ending in a sharp snap-back recovery. The Y-cursor pair
  (15.9 → 17.5 V, ΔY = 1.6 V) brackets a **+1.6 V excursion above baseline** at recovery
  (park-like; provisional). The deep 6.5 V floors of the TP0010 SD log are not reproduced in
  this photo window (different execution; possibly a milder stretch of the cycle).
- **CH2 I_batt:** per event: a quiet dropout interval → a **reconnect spike ~1 div ≈ 1 A** →
  a noisy conduction plateau **~0.4–0.5 div ≈ 0.4–0.5 A** → dropout again, synchronized with
  the voltage recoveries. (FC INA unmonitored, as in prior captures.)

**Conclusions (corrected):**
- **`D-MT-EN` is ruled OUT as the cutting element.** VBUS and V-MOT track each other through
  every dip — the motor switch is conducting throughout. The original conclusion is inverted:
  the motor path is fine; **the bus is losing its source feed**.
- **The events are total source-feed dropout windows.** With `D-MT-EN` conducting, the bus
  rides the combined bus + motor + VESC capacitance (~1–1.5 mF — which is exactly why the
  decay is a slow 3–4 V over tens of ms rather than the µs collapse bare ~40 µF VBUS would
  show). During each window neither source channel feeds the bus; a reconnect (the ~1 A BT
  burst) then recharges the whole node. This also corroborates the TP0010 SD-log reading of
  10–18 ms both-channels-off windows.
- **The droop-vs-SCP discrimination is NOT settled by this capture.** Both candidates predict
  exactly this signature at the bus: (a) the droop loop railing both MDACs antiphase pushes
  both source channels out of conduction (voltage-driven blocking, no SCP involved); (b) a
  source-side switch (`D-FC-EN`/`D-BT-EN`) SCP-cuts and retries on the 64 ms timer. The
  67.6 ms period is consistent with both. What WOULD discriminate (next capture, if the
  firmware mitigation underperforms): probe a **boost VOUT alongside VBUS** during a dropout
  — (a) predicts the disconnected boost's VOUT parked *above* the decaying bus (RT1987
  blocking on reverse voltage) with reconnect at the voltage crossing; (b) predicts reconnect
  on a fixed 64 ms cadence regardless of the voltage crossing. FC INA + a synchronized SD log
  (gain commands) would additionally settle the master/slave question.
- **Operational hazard (revised):** the full bus — sources to VESC — sags 3–4 V ~15×/s
  during the cycle (and per the TP0010 log can reach 6.5 V, deep into any load's UVLO
  territory). The mitigation case (feasibility-gated integrator hold, MDAC slew limiting)
  stands unchanged; the specific VESC-brownout-via-motor-switch-cut framing from the first
  analysis is withdrawn along with the `D-MT-EN` claim.
- Screen-read numbers are provisional until re-read photometrically; the entry follows the
  metrology conventions (div × scale quoted throughout).

---

## Scope-metrology conventions (adopted 2026-08-03, review BOOST-R1-N6)

Two transcription errors survived into this log during the OV investigation (a 3.9× current
unit slip and an inverted VBUS reading). These rules exist so that class of error cannot recur:

1. **Record scope currents/voltages as `<divisions> div × <scale> = <value>`**, never as a
   bare engineering value. For current channels also record: probe attenuation, coupling,
   **bandwidth-limit setting**, the zero-reference used (channel ground marker or baseline
   cursor) and its agreement with the quiescent trace.
2. **Quote trace-centre levels.** A cursor pair placed edge-to-edge across two ~0.2 V-thick
   traces over-reads a step by ~0.3–0.4 V.
3. **Report both a peak and an ∫I dt with an uncertainty envelope** for any current event;
   for a chopped/rippled trace give the band centre and band top.
4. **File the capture before building conclusions on it**; screen-read numbers are
   provisional until re-read photometrically against on-screen references. Write the probed
   net into the filename and file a one-line scope-state transcription with it.
5. **Sections append in chronological order**, and any later correction to an earlier entry
   gets an explicit "supersedes §X" pointer at the superseded text.

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
  first, so the boost soft-started into a bus pre-charged to ~7.7 V **through the enabled
  `D-BT-EN`** (mechanism name corrected 2026-08-03, review BOOST-R1-F6; measured in
  `2-VBUS.jpg`). Gentle, pre-charged bring-up still kills it. **This refutation applies to the
  pre-2026-07-08 sequencing only** — it is not a claim that the bus pre-charges under the
  current `bringUpBus()` (it does not; see the 2026-08-01 dual-channel entry).
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
- **Do not leave a `G` bring-up clicking (capture 10, 2026-08-06).** A sustained ~15.5 Hz
  click/current-burst pattern is a non-converging RT1987 SCP cut/retry limit cycle: ~930
  Death-5-class load dumps per minute on the sourcing boost (the FC boost, in the dual-source
  config; correction 2026-08-11 — it carries hot-loop bodge caps, an earlier version of this
  rule said otherwise), plus inferred ~17–18 V cut-release parks. It does NOT self-terminate —
  abort promptly (`X`/`Q` or power-down). No VESC-attached `G` on the old (pre-staged-bring-up)
  firmware; prerequisites first: 100 nF CSS on `D-MT-EN`, then the staged-bring-up flash.
- **Treat asymmetric share setpoints (~0.3, and ~0.85) under ramping load as a known stressor
  (TP0010, 2026-08-11).** At low total current (< ~1.2 A) the share loop can enter a ~17–18.5 Hz
  minority-channel dropout limit cycle; at `share_sp = 0.3` it collapsed VBUS to 6.5 V ~33 times
  with 3+ A reconnect spikes, and under `BENCH_TEST` no fault latches (OV-only). Nondestructive
  so far, but Death-5-family stress; both boosts carry hot-loop bodge caps (operator-confirmed
  2026-08-11), which mitigates but does not retire the concern. Capture 12 (2026-08-11,
  corrected reading) confirmed the cycle drops the bus's *source feed* ~15×/s — the whole
  bus+motor node sags together (3–4 V on-screen; to 6.5 V in the TP0010 log) with everything
  downstream riding the decay — so the restriction stands until the firmware mitigation
  lands, not merely until scoped. Interior
  setpoints 0.15/0.5/0.7 and the endpoints 0/1 are demonstrated clean.

---

## Next steps (fix validated — quantify margin, then escalate load)

The caps are in, the boost survives `G` bring-ups (×4). Remaining work, in order:

**0. Verify/redo the BT RD1 215 k bodge (2026-07-31 — blocks all `G` work).** The recurring
`FAULT_OV_BUS` datapoint above says the BT boost still regulates at ~17.4 V, i.e. the 16 V retune
never took effect on the BT FB network. Ohm RD1-BT unpowered (expect 215 k) or compare no-load
VOUT FC vs BT; rework the bodge if it reads 237 k. File the 2026-07-31 scope captures into
`references/scope_captures/` while at it.

**0b. Capture-10 limit cycle (2026-08-06) — blocks all VESC-attached `G` runs.** In order:
(1) fit **100 nF CSS on `D-MT-EN`** (standing staged-bring-up hardware prerequisite); (2) flash
the **staged bring-up** (pending its test/review gates); (3) one scope-armed VESC-attached `G`
with the capture-10 discriminator channels — **BT INA and/or VBUS proper** (the latter finally
closes the "ADC node never scoped" item and settles which switch is cut/retrying). Expected
outcomes: P3 completes (done), or times out to `FAULT_MOT_HOTPLUG` (dark, safe — then evaluate
raising the charge-per-retry or the VESC drain question with the capture in hand).

**0c. TP0010 share-loop limit cycle (2026-08-11) — capture 12 taken: source-feed dropout
confirmed, `D-MT-EN` ruled out, droop-vs-SCP still open; firmware mitigation is the next
move regardless.** The scope-armed repeat landed 2026-08-11 (capture 12, above, corrected
same day): VBUS and V-MOT sag together ~3–4 V at ~14.8 Hz — the bus loses its *source feed*
each cycle; the motor switch conducts throughout. Whether the source disconnection is
droop-commanded blocking or a source-switch (`D-FC-EN`/`D-BT-EN`) SCP cut is NOT yet
discriminated — both fit the signature and the 67.6 ms period. Remaining, in order:
(1) firmware mitigation — **IMPLEMENTED (fw v2, 2026-08-11, pending flash; ledger row in
`docs/firmware-versions.md`)**: setpoint governor (commanded minority-channel current
≥ `SHARE_MINORITY_I_MIN_A` = 0.20 A — empirical from the sweep; the CAL-1 ΔV0 = +0.05 V
linear bound is far lower, so the floor is the light-load nonlinearity), droop-ratio slew
limit (0.02/tick, controller path only), and share-controller state reset at every profile
entry. 1261 production + 95 bench host tests pass. Both candidate mechanisms are downstream
of the droop loop railing, so the mitigation stands without settling the discrimination.
(2) If the mitigation underperforms, the sharper
discriminator: **boost VOUT alongside VBUS** during a dropout — voltage-crossing reconnect
= droop blocking; fixed 64 ms cadence reconnect = SCP — plus FC INA + a synchronized SD log
for the master/slave question. (3) A ⭐ FIX VALIDATION re-entry of the TP0010 condition once
the mitigation is flashed.

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
