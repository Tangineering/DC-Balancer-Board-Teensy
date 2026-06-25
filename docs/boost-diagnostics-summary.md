# Battery boost (TPS61288) failure — diagnostics summary

**For:** an engineer picking this up cold. **Scope:** what was tested and what it rules out. Full
detail in [`boost-bringup-debug.md`](boost-bringup-debug.md) — that document wins on any conflict.

## The fault in one line

A *known-good* TPS61288 boost regulates 17.5 V fine **standalone** on the BT pad, then dies the
instant it **drives VBUS** — `VBT`↔GND short (VIN–SW–VOUT fused) every time. **Four** battery-side
boosts have failed this way; the FC channel never fails. Leading cause: a **PCB-layout asymmetry**
(BT output-cap hot loop ~6× larger than FC's) — not a part, wiring, supply, or firmware problem.

## Tests performed

### Failure events (each destroyed a BT boost)

| # | Setup | Action | Result |
|---|---|---|---|
| Death 1 | 9 V batteries; FC already off VBUS | Enabled `BT_BUS_ENABLE` (BT boost → VBUS) | Fried. Was the *original, never-reworked* boost. |
| Death 2 | DC supply, **120 mA** limit, BT only | Old FW: bus switches, then boosts | Collapsed to CC @ 120 mA; fried. |
| Death 3 | DC supply, **full ≥5 A**, BT only | Booted to Idle OK; `G` bring-up | Hit 5–7 A, collapsed; fried. |
| Death 4 | DC supply 8.2 V/200 mA; **known-good FC boost moved to BT pad**; `RC-BT` matched to FC | `G` (gentle, bus pre-charged ~7.7 V) | Pegged 200 mA CC; fried. |

**Death 4 is decisive:** the FC channel's *proven-good* part lived on the FC pad, then died on the
BT pad → **pad/channel, not part.** Constant across all four: `VBT→GND` short post-mortem;
`BT_SEQUENCE_ENABLE` ON; 470 µF bulk cap (on V-MOT, behind `MOT_PWR_ENABLE`) OFF.

### Non-destructive tests (all PASS — isolate where the fault is *not*)

| Test | Result |
|---|---|
| **Boost-removed bus path** (DC supply on `VBUS-BT`, assert `BT_BUS_ENABLE`) | VBUS → 17.5 V, **~0 A**. BT bus path is clean. |
| **FC boost drives the bus** (12 V on FC input, `G`) | Clean 17.5 V. Healthy reference; rig + sequence sound. |
| **Dual-source OR-ing** (live FC bus + DC on `VBUS-BT`, boost removed) | Bus tracked higher source smoothly, no fight. `D-BT-EN` passes a live bus cleanly. |
| **Schematic BOM compare** (`Scale_Car_Board_20260624.sch`) | Boost stages **identical** part-for-part. Only `R1` differs — the input-V ADC divider, not a boost part. |
| **Operator copper measurement** | BT Cout sits **240 mil from the IC output pin vs FC's 40 mil (6×)**; SW pour 1.6× longer (minor). |
| **Ohmmeter, unpowered** | `D-BT-EN`/`D-FC-EN` EXP→GND and VOUT→GND all open. No static short. |

## Causes RULED OUT (with evidence)

- **Defective/wrong part, FB-droop, inductor** — both boosts regulate 17.5 V standalone; Death 4 was a known-good part.
- **Supply collapse / inrush / motorboating** — a stiff ≥5 A supply killed it as fast as 120 mA; VBUS is only ~40 µF (the 470 µF is elsewhere, and was off).
- **Static shorts** (`D-BT-EN` EXP/VOUT→GND, VBUS→GND) — ohmmeter open; FC held VBUS at 17.5 V in Death 1.
- **Dynamic low-Z fault in the BT→VBUS path** — boost-removed path ran at ~0 A.
- **Charger / `BT_SEQUENCE` static load** — path test ~0 A. *Caveat:* `BT_SEQUENCE` never isolated OFF; low-probability, not 100% closed.
- **Input current limit as a safety net** — Death 2 fried it at **120 mA**; destructive energy is internal (½·L·di²), unbounded by input limit.
- **`RC-BT` compensation value** — REFUTED by Death 4 (matched to FC, still died).
- **0 V hot-plug / bring-up sequence** — REFUTED; Death 4's gentle `G` into a pre-charged bus still died.
- **Rework/desolder damage** — REFUTED; the Death 4 part had just worked on the FC pad.
- **Old "BT `VSW` 2.2× longer" trace-length figure** — SUPERSEDED; that parse excluded the polygon pours. SW is a wide low-inductance pour (1.6×, minor); the dominant metric is Cout distance.

## Leading cause (strong, pending scope)

**BT output-capacitor hot loop.** Schematic proven symmetric → the difference is layout. All power
nets are polygon pours, so trace length is irrelevant; the metric that matters is **Cout distance to
the IC output pin: FC = 40 mil, BT = 240 mil (6×)**. The larger BT hot loop has higher inductance →
at the di/dt of driving the bus, SW/VOUT rings past the **20 V abs-max** (only ~0.5–1.5 V of
headroom over 17.5 V) → sync-rect FET fails short (`VIN`–`SW`–`VOUT`→GND, the observed post-mortem).
Fits every datapoint: Death 1 (original copper), FC always survives, `RC` swap didn't help, DC
injection clean (no di/dt), death at 120 mA (internal energy).

**Firmware cannot fix this.** Board-level remedy: add an output ceramic **right at the IC VOUT/PGND**
to collapse the BT hot loop to FC-like (± an SW snubber), or respin the BT channel.

**Before the next boost:** logic on a separate stiff supply; scope `VSW-BT`/`VOUT-BT` from t=0
(single-shot armed past ~18 V, fast kill ready). Expect a >20 V ring on BT, clean on FC. If BT
doesn't ring past 20 V, re-open (ground-return/via or manufacturing defect). Four boosts have died
without one scope capture — don't spend a fifth blind.
