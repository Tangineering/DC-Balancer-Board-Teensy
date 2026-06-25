# Battery boost (TPS61288) repeated-failure debug log

**Status:** LEADING HYPOTHESIS (pending scope) — **a BT-channel layout asymmetry causes a
destructive SW overshoot when the boost drives the bus**. FOUR battery-side TPS61288 boosts
destroyed, each the moment the battery boost actively drives VBUS. The schematic is **symmetric**
(every boost-stage part matches FC; only `RC` differed, now reverted; `R1` is the irrelevant ADC
sense divider). So the difference is **physical/layout in the BT channel** — by elimination, the
robust conclusion. Leading specific mechanism: the **output-capacitor hot loop**. All power nets are
**polygon pours** (trace-length figures are irrelevant), so the metric that matters is the **Cout
distance to the IC output pin**, measured directly by the operator: **FC = 40 mil, BT = 240 mil
(6× farther)**. BT's larger hot loop has higher inductance → SW/VOUT rings past the **20 V abs-max**
(only ~0.5–1.5 V over the 17.5 V rail) under the di/dt of driving the bus → sync-rect FET fails short
(`VIN`–`SW`–`VOUT`→GND). (The SW node itself is a wide pour, 1.6× longer on BT — a minor contributor.
An earlier Gerber trace-length figure of "17.45 mm / 2.2×" was **inflated/wrong** — it excluded the
pours; superseded.) Fits Death 1 (original un-reworked boost — it's the copper), FC always surviving,
the `RC` swap not helping, death at 120 mA (energy is internal ½·L·di², no input limit bounds it),
and the clean DC injection (no di/dt → no ring). **Confidence is now reasonably strong (6× on the
dominant dimension), but confirm with one scope capture** of the SW node on bus-connect before
trusting it; if BT doesn't ring past 20 V, suspect a return-path/via or manufacturing defect instead.
Board-level fix: **add output ceramic right at the IC VOUT/PGND** to collapse the BT hot loop to
FC-like (± SW snubber). Firmware cannot fix this. No spare boosts remain. This document is the
cold-start reference — read it before touching the bench.

**One-line summary:** A *known-good* boost regulates 17.5 V fine standalone on the BT pad, then dies
the instant it drives the bus — same as three before it, and now with the loop compensation (`RC`)
matched to the always-working FC channel. So it is **not** wiring, **not** a short, **not** the
supply, **not** the bring-up sequence, **not** `RC`. With `RC` matched and the only other catalogued
"delta" (`R1`) now known to be the **input-voltage ADC sense divider — not a boost-loop component
at all** — the two boost power stages/loops are, on paper, **identical**. Yet FC lives and BT dies.
The cause is therefore **not a compensation/design value**; it is something **physical** in the BT
channel — damaged output caps, a layout/pad/via defect, an *uncatalogued* component difference, or
the `BT_SEQUENCE` tie — that only bites when the boost actively switches into the bus.

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
- `BT_SEQUENCE_ENABLE` (battery → charger) was **ON in all FOUR deaths** — never once isolated OFF.
- In death 1 the FC boost was **already disconnected** when BT was connected (not a paralleling fight).
- Post-mortem each time: `VBT → GND` short (the dead boost: VIN–SW–VOUT fused to GND).
- **Death 4 conditions** (most controlled yet): `FC_BUS_ENABLE`, `MOT_PWR_ENABLE`, `REGEN_ENABLE`,
  `FC_CHARGE_ENABLE` all OFF; `BT_SEQUENCE_ENABLE` ON; `BT_BUS_ENABLE` brought up by `G` in sequence
  with `BT_REG_ENABLE`. `G` energizes the bus switches **first**, so the bus was pre-charged to
  ~7.7 V (boost body diode) before the boost soft-started — **not** a 0 V hot-plug.
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
- **Charger / `BT_SEQUENCE` static load** — effectively ruled out by the path test (~0 current with
  the path energized). (Caveat: the DC test has no switching ripple, so a charger interaction that
  needs the boost's switching can't be 100% excluded — but it's now low-probability. `BT_SEQUENCE`
  has nonetheless never been tested OFF — see Next steps.)
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

## LEADING HYPOTHESIS: BT output-cap hot-loop inductance → destructive SW overshoot driving the bus

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
value — it is the **PCB layout** (see ROOT CAUSE above: BT `VSW` 2.2× longer).

**Secondary checks (lower priority, do while reworking the BT channel):** measure the BT output caps
(3 × 22 µF) for cracks/lost capacitance; inspect the BT switch-node/output joints and vias; the
`BT_SEQUENCE` tie was on in all four deaths but the DC path test was clean, so it's low-probability.
None of these displaces the measured `VSW` layout asymmetry as the prime cause.

---

## Safety rules for further bench work

- **No input current limit is proven safe.** Death 2 = 120 mA. Do not assume 0.3 A (or any value)
  protects a boost; the boost can demand >5 A, and output-side energy (its own ~10 mJ output cap,
  or reverse/overshoot) is not bounded by the input limit.
- **Power the Teensy/logic from a SEPARATE supply** for any bench test, so a boost-input current
  limit can't re-trigger the death-2 brownout/motorboating of the board-powered logic.
- **Do not install another TPS61288 until (a) the full FC-vs-BT channel + layout diff is done,
  (b) the BT boost-stage passives/caps are verified against FC, and (c) you can SCOPE the next
  attempt.** Four boosts have died without a single scope capture of the failure — do not spend a
  fifth blind. (The BT bus path itself is already proven clean; `R1` is the ADC sense divider, not a
  suspect.)

---

## Next steps (leading cause = BT output-cap hot loop; confirm, then fix at board level)

We are out of TPS61288s and have killed four without ever capturing a scope trace. **The next boost
must not be spent blind.**

**1. Confirm the mechanism with ONE scoped boost (order several).**
- Logic on a **separate, stiff** supply (never board-powered for the bring-up).
- **Scope `VSW-BT`/`VOUT-BT` from t=0**, single-shot armed past ~18 V, fast manual kill ready.
  Expectation: a **>20 V spike / ring** at the bus-connect current step, exceeding the 20 V abs-max.
  No input current limit is protective (energy is internal ½·L·di²) — scope + fast cutoff is the net.
- Capture `VSW-FC`/`VOUT-FC` on the working FC channel as the clean reference (smaller, faster-damped).

**2. Board-level fix (firmware can't help) — collapse the BT hot loop first.**
- **Add a ceramic output cap (e.g. 1–4.7 µF, ≥25 V) bodged RIGHT at the BT IC `VOUT`/`PGND` pins**
  — pull Cout from 240 mil back to FC-like (~40 mil). This is the direct fix for the measured 6×
  hot-loop asymmetry and the first thing to try.
- **± RC snubber across the BT SW node** (SW→GND, a few hundred pF + ~1–10 Ω, value from the scoped
  ring frequency) to damp residual overshoot.
- **Respin the BT channel** to place the output caps tight to the IC like FC (proper fix); also widen
  the `VBUS-BT` run.
- Re-derate switching current / lower bus-connect di/dt as an interim de-risk.

**3. While reworking, knock out the cheap secondary checks:** measure the BT output caps for
cracks/lost capacitance; reflow/inspect the BT IC `VOUT`/`PGND` joints and vias; optionally run the
no-boost DC-injection test with `BT_SEQUENCE` OFF to close that loose end.

**Decisive confirmation:** a new boost on the BT channel **with a cap added at the IC VOUT/PGND**
that now survives the bus connect, scope showing the overshoot pulled under 20 V, closes this out.

---

## Firmware status (context)

The firmware changes made across these sessions (boosts default OFF; `doState0()` gentle bring-up
+ V_bus gate; `BENCH_TEST` bypass that boots to Idle with the power stage off; State-98 `G`
bring-up + `1`/`2` hot-plug guard; Finish leaves bus energized) are **defensive and still
reasonable**, but they target the *bring-up sequence / supply* — which the data shows is **not**
the root cause. **The leading hypothesis is a BT-channel layout asymmetry (output-cap hot loop, and
to a lesser degree the SW pour) causing a destructive SW overshoot, pending scope confirmation;
firmware cannot fix it — it needs an SW snubber / added local `Cout` near the IC / a BT-channel
respin.** The
in-code comments are deliberately framed as "mechanism unconfirmed, pending scope" — treat this
doc as the authoritative, current understanding.

All 219 (production) + 5 (bench) host-native tests pass: `cd test && mingw32-make`.
