# Dossier: ADI DC2039A (LTC4015 demo board), Path A replacement for the Ag105

Date: 2026-11-05. Board rev 20260622. Spec: `charger_eval/spec.md` ([SPEC] below). Operator framing: Path A (wire an off-the-shelf
charger onto the current board) and Path B (re-spin) are alternate paths, not primary/fallback.

## 0. How the sources were read (read this first)
- **No primary PDF was fetched.** `datasheet.chipsmall.com` and `docs.ampnuts.ru` both fail DNS in this session, which means
  they are outside the allowed network domains. Per the tool policy I stopped trying further hosts after the second failure.
  **Nothing was saved to `datasheets/`.** To close this dossier, allow one of: `www.analog.com` (LTC4015 datasheet,
  `media/en/technical-documentation/user-guides/DC2039A.pdf`), `dtsheet.com` (doc 1686583 = LTC4015 datasheet, doc 1998572 =
  DC2039A demo manual), or `www.electronicsdatasheets.com`, then re-run this dossier against them.
- Evidence tiers:
  - **[WS]** = web-search summaries of the LTC4015 datasheet and the DC2039A demo manual (Rev D per the search). Tertiary: leads only.
  - **[TRIAGE]** = the workflow's triage rationale. Secondary.
  - **[REC]** = my recollection of the LTC4015 datasheet. **Always UNVERIFIED.** Never act on it without a primary re-read.
  - **[SPEC]** = `charger_eval/spec.md` (board facts already verified from repo design files).
- **Literature numbers:** ADI does not use TI-style lit numbers. Documents are "LTC4015 datasheet" (revision UNVERIFIED) and
  "DC2039A Demo Manual" (Rev D per [WS]). Page and section citations cannot be given until they are read; where [WS]
  located a section it is named (for example the register map in "Register Description", around datasheet p.49-50 [WS]).

## 1. Verdict
- **Fit score: 5.5 / 10 (provisional).** Nothing found is a confirmed showstopper. Four items could become one once read:
  POR behaviour, start-up latency, battery detection through D-BT-SQ, and the UVCL threshold mechanism.
- **Strengths:**
  - High-side sense on both sides (RSNSI on the input, RSNSB between the inductor and BAT+), so common ground holds by
    architecture.
  - 40 V absolute maximum on VIN/CSN [WS] meets the spec's ≥ 36 V preference.
  - IBAT / VIN / VBAT telemetry plus a coulomb counter over I2C keep `I_charge` real.
  - An input ideal-diode controller (INFET) blocks battery-to-input back-feed. That makes the "bridge D-BT-SQ" variant [SPEC s3]
    viable, which in turn fixes the lost-settings problem.
- **Weaknesses:**
  - **The board is sized for 8 A** [WS]. Its stock POR defaults (max charge current, max input current) are far above this board's
    limits. Both sense resistors must be changed so that the **hardware** limits are safe at POR (section 5).
  - **No charge-enable pin and (per [REC]) no I2C watchdog.** Layer-2 fail-safe [SPEC s3] needs an external circuit.
  - **UVCL is a regulation loop, not a hard off**, and whether its threshold is I2C-programmable over 13.5-19 V is UNVERIFIED
    (section 4).
  - **The demo board cannot sit on the 32 × 35 mm footprint**; it must be mounted off-board, or the LTC4015 goes on a custom carrier.
  - **The input and SYS capacitance must be audited** against the ≤ ~50 µF limit [SPEC s6]. Both are unknown.
- **Recommended configuration if pursued:**
  1. Bridge D-BT-SQ (or wire BATSENS to VBT; see section 9 for the hazard).
  2. RSNSB → 12 mΩ (2.67 A hardware ceiling).
  3. RSNSI → 32 mΩ (1.0 A hardware input ceiling).
  4. UVCL resistor divider strapped to the 19 V (regen-safe) value, with an FC_CHARGE-net FET to drop it to 13.5 V.
  5. Fit a 10 k resistor at THERM if no NTC is fitted.
  6. Remove every electrolytic on VIN/SYS.
  7. Remove the QuikEval pull-ups.

## 2. Common ground (R-GND)
- **Verdict: UNVERIFIED on the DC2039A schematic. PASS is expected from the IC architecture.**
- LTC4015 topology [REC, consistent with TRIAGE]:
  - Power path: VIN → external N-FET input ideal diode (INFET) → RSNSI (CLP-CLN, input-side sense) → SYS → synchronous buck → inductor → RSNSB (CSP-CSN) → BAT+.
  - Both sense elements are in positive rails. Ground is one PGND/GND node.
  - [WS] confirms RSNSI 3 mΩ and RSNSB 4 mΩ exist on DC2039A. CSP/CSN being in the inductor-to-BAT+ path is [TRIAGE]/[REC].
- **Before ordering:** read the DC2039A schematic and confirm that the VIN-return and BAT-return terminals are the same copper,
  with no shunt or jumper between them. A demo board meant for coulomb counting would not normally add a low-side shunt, but
  this is not yet read.

## 3. VIN operating range, absolute maximum, OVP
- **LTC4015 VIN, CSN absolute maximum: -0.3 V to 40 V** [WS]. CLP and CLN are limited to ±0.3 V relative to SYS [WS].
- **Operating range:**
  - Charging input 4.5-35 V [WS].
  - DC2039A operating input 5-35 V, battery 5-35 V for Li chemistries [WS].
- **Against [SPEC s2]:**
  - Operating ≤ 12 V to ≥ 23 V: **met**, with 12 V of margin above the ~21.4 V clamp. The unmeasured V-MOT overshoot is much
    less critical here than on the 24 V-class TI parts.
  - Absolute maximum ≥ 30 V required / ≥ 36 V preferred: **met** (40 V).
- **No input OVP comparator trips inside 12-23 V** [REC]. The INFET is an ideal diode, not an OVP switch.
- **Board work:**
  - Still replace C-D8/C-D10 (25 V) with ≥ 35 V parts [SPEC s2].
  - DC2039A's own VIN/SYS capacitor voltage ratings are UNVERIFIED. They are presumably ≥ 35 V on a 35 V-rated board.

## 4. Input threshold (R3) and FC/regen mode switching
- **Mechanism: input undervoltage current limit (UVCL).** It "can be engaged to help keep the input voltage from decreasing beyond
  a minimum voltage" from a resistive or power-limited source [WS, Digi-Key LTC4015 tutorial]. This is VINDPM-class regulation,
  the spec's **"acceptable"** tier, not a hard off [SPEC s4].
- **Programming: UNVERIFIED.**
  - [REC] There is a UVCLFB pin with an external divider from VIN, plus a `VIN_UVCL_SETTING` register that trims the regulation
    point.
  - Neither the formula, the range, nor whether I2C can move the threshold across 13.5-19.0 V without a resistor change was found
    [WS: "register formula not found"].
  - **Read the Register Description section first.** If the register range relative to a single divider cannot span 13.5 → 19.0 V,
    use the spec's hardware option:
    - Strap the divider to **19.0 V** (the safe POR value).
    - An N-FET, gated from the FC_CHARGE net (J1.45/46), switches a parallel resistor that drops the threshold to **13.5 V**.
    - The RT1987 8 ms tD_ON settles the select line before VCHG-IN appears [SPEC s4].
    - The divider value survives POR, which suits a part that loses its registers every input cycle (section 8).
- **MPPT:** pre-programmed MPPT exists [WS]. On a moving regen V-MOT or a stiff FC bus it would hunt (same reasoning as the TI
  dossiers). **Keep it disabled.** Its POR default (`mppt_en_i2c`, [REC] default off) is UNVERIFIED.
- **Hard off:**
  - The `suspend_charger` bit in `CONFIG_BITS` [REC, register name UNVERIFIED] is a host-written off that is lost at POR.
  - There is no programmable hysteretic input UVLO [REC]. The fixed VIN UVLO is ~4 V class [REC]: useless as an R3 threshold.
- **Bench requirement [SPEC s4]:** verify ~0 A from a stiff 15.8 V source with UVCL at 19.0 V, and loop stability on a
  high-impedance regen source.
- **This does not replace** firmware layers 1/3 and the fw v37 rev 2 `J` guards G1-G3 plus the trip latch. Port those.

## 5. Charge current, input current, CV (and the 8 A oversizing)
- **DC2039A stock:**
  - RSNSB = 4 mΩ, giving 7.9 / 8 / 8.1 A charge current [WS].
  - RSNSI = 3 mΩ [WS].
- **Formulas [REC, UNVERIFIED]:**
  - `ICHARGE_TARGET` (5-bit): I = (N+1) × 1 mV / RSNSB, max 32 mV / RSNSB. This is consistent with 8 A at 4 mΩ [WS].
  - `IIN_LIMIT_SETTING` (6-bit): I = (N+1) × 0.5 mV / RSNSI, max 32 mV / RSNSI (≈ 10.7 A at 3 mΩ).
  - **The POR defaults are believed to be the maximum codes** [REC]. On the stock board, a cold start would therefore aim at 8 A
    out and ~10.7 A in. That violates the FC input budget (≤ ~1.0 A, OC_FC 1.4 A single-sample latch [SPEC s2]) on every cold
    start, before firmware can write anything.
- **Required resistor changes (so the hardware bounds are safe even with POR defaults):**
  - **RSNSB 4 → 12 mΩ:** maximum 2.67 A (spec 2.5 A, pack limit UNVERIFIED [SPEC s8 Q4]), 83 mA steps, minimum 83 mA. Meets
    "≤ 0.25 A capable". If the pack must never see > 2.5 A, use 13 mΩ (2.46 A max).
  - **RSNSI 3 → 32 mΩ:** maximum 1.0 A input at POR, 15.6 mA steps.
    - Regen needs ~1.1 A in for 2.5 A out at 21 V (21 W / 21 V plus losses), so a 1.0 A cap trims regen at most ~10 %.
    - In exchange the hardware bound holds in FC mode with no firmware dependency.
    - 1.0 A in FC mode gives ~1.7-1.8 A out [SPEC s2].
  - These changes also fix the triage's "10 mV at 2.5 A" resolution concern: 2.5 A × 12 mΩ = 30 mV, about full scale.
- **IBAT telemetry:** [REC] LSB = 1.46487 µV / RSNSB, which is 0.12 mA at 12 mΩ. Fine for `I_charge`. Accuracy is UNVERIFIED.
- **CV:**
  - CHEM/CELLS are three-level pins set by 0603 0 Ω resistors, chosen so settings cannot change after power-up [WS]. The cell
    table is in demo manual Fig 3 [WS]. Up to 9 Li-ion cells are supported [WS].
  - **Strap 2S Li-ion (programmable variant).** The default case in the manual is already 7.4 V battery / 25 V in / 8 A [WS],
    i.e. 2S.
  - [REC] `VCHARGE_SETTING` (Li-ion): (N/80 + 3.8125) V/cell, maximum 4.2 V/cell = 8.400 V. The register can only lower it.
    Accuracy is UNVERIFIED ([REC] ~±0.5 %?).
  - The D-BT-SQ drop leaves the pack at ~8.365 V [SPEC s2]. It cannot be compensated upward via the register.
  - **BATSENS (remote Kelvin pin [REC])** is the better lever: it removes the drop. See section 9 for the hazard of Kelvin sensing
    across D-BT-SQ.

## 6. Start-up latency (regen cold start)
| Step | Time | Source |
|---|---|---|
| Board overhead (detect + RT1987 tD_ON + ramp) | 12-20 ms | [SPEC s5] |
| LTC4015 INTVCC / measurement system up after VIN | UNVERIFIED | – |
| Battery detection on charge start (Li-ion) | UNVERIFIED ([REC] a test period of order 100s of ms is possible) | – |
| NTC / JEITA qualification on first measurement cycle | UNVERIFIED | – |
| Buck soft-start to 90 % ICHARGE | UNVERIFIED | – |

- **Requirement [SPEC s5]:** ≤ 30 ms target, ≤ 100 ms hard maximum from input applied.
- **Unknown, and the main regen risk.** The LTC4015 is a "smart" charger with a state machine (battery detection, JEITA, measurement
  system). Its cold-start time to current is not in any snippet I found.
- **Bridging D-BT-SQ (section 9) probably shortens the regen cold start.** With the pack on BAT, the IC stays alive with the
  battery present and qualified, so a burst should only need input qualification and soft-start. UNVERIFIED; measure (M1).
- Abrupt input loss: the INFET opens and the IC falls back to battery-only. This should restart cleanly on the next burst
  [REC]. Measure.

## 7. Hot-plug inrush and input capacitance (spec section 6)
- **RT1987 slew is 12.0 V/ms, giving 12 mA/µF** [SPEC s6]. Effective budget on VCHG-IN: ≤ ~50 µF beyond the board's 20 µF
  (hard ~80 µF).
- **DC2039A CIN: UNVERIFIED.** [WS] saw several 10 µF 1206 capacitors on the schematic but could not attribute them.
  - An 8 A, 35 V-in buck controller board typically carries several ceramic µF on VIN and SYS, and possibly an electrolytic.
  - **Count the SYS capacitors too.** The INFET conducts as soon as VIN > SYS, so SYS charges on the same 12 V/ms ramp.
- **Required audit:**
  - Sum VIN + SYS effective capacitance at ~16-21 V DC bias.
  - Remove every electrolytic and depopulate ceramics down to ≤ ~50 µF total effective (keep the buck's minimum input
    capacitance per the datasheet, UNVERIFIED).
  - A 470 µF-class bulk part would draw 5.6 A, the Death-5 class [SPEC s6].
- **INFET:** may have its own gate charge-up delay [REC]. This helps here (a second, soft entry), but it is unverified.
- **The buck must not switch during the 1.3-1.75 ms ramp.** The LTC4015 input-qualification delay is UNVERIFIED.

## 8. Control, fail-safe, POR, watchdog
- **Charge-enable pin: none** [REC]. Charge is suspended via the I2C `suspend_charger` bit [REC], which is lost at POR.
- **Fail-safe during Teensy reset [SPEC s3]:**
  - Layer 1 (RT1987 EN pull-downs, no input power) is unchanged and remains the primary fail-safe.
  - Layer 2 has no native implementation. Option: reuse pin 5 (MPPTD net) as an active-HIGH enable that switches the UVCL
    divider:
    - pin LOW or floating (pull-down ≤ 47 kΩ on the carrier) → UVCL forced above ~30 V → the charger takes ≈ 0 A;
    - pin HIGH → normal threshold (combined with the FC_CHARGE-net select).
    - This is a regulation-loop "off", not a hard off. Bench-verify. Feasibility depends on the UVCLFB mechanism (section 4).
- **POR default:**
  - Charging starts autonomously on VIN with the strapped chemistry and default (max) current [REC].
  - This **fails** the spec's "no charging until host enables" rule. Section 5's resistor changes make the autonomous start
    *bounded* (2.67 A out / 1.0 A in), not *absent*.
  - With D-BT-SQ in place, the registers reset on every input cycle, because the IC loses all power when VCHG decays.
- **Watchdog: none known** [REC, UNVERIFIED]. The host-silence stop (≤ ~5 s) must come from firmware layer 1 (opening the RT1987s).
- **Mode switching:**
  - Hardware threshold select (section 4) is preferred.
  - I2C writes after every power-up only if the register can span the range.

## 9. Operation with D-BT-SQ (RT1987 ideal diode) between charger output and pack
- **Keeping D-BT-SQ:**
  - At input power-up the charger output sees 10 µF, with the pack hidden until VCHG > VBT + 35 mV [SPEC s3].
  - The LTC4015 battery detection [REC: test current / voltage-response based] could declare `bat_missing` on a 10 µF node, or
    see a step load when D-BT-SQ closes. Whether it retries automatically, and how fast, is UNVERIFIED. **This is the key bench
    test if D-BT-SQ is kept.**
  - Telemetry VBAT reads VCHG, not the pack. Use pin 25 for the pack.
  - The coulomb counter keeps working: it counts the current that reaches the pack, less D-BT-SQ leakage.
- **BATSENS Kelvin to VBT (at C-D12) while keeping D-BT-SQ: NOT recommended.** If D-BT-SQ ever blocks (EN low, UVLO,
  reverse-comparator trip), the CV loop opens:
  - BATSENS still reads the pack, so the buck drives VCHG upward, toward VIN (21 V+) in regen.
  - C-D11 on VCHG is a 25 V part.
  - Any battery-overvoltage protection on CSN is UNVERIFIED.
- **Bridging D-BT-SQ: the recommended LTC4015 configuration.**
  - Pack on BAT/CSN, BATSENS local.
  - The IC is then powered from the pack, so registers persist across bursts, the battery is always detected, CV is sensed at
    the pack, and the coulomb counter runs continuously (useful for SoC).
  - The INFET blocks pack → SYS → VIN back-feed, so the bus is not fed from the pack and R3 is unaffected.
  - SYS is back-biased from the pack through the top-FET body diode, but nothing is connected to SYS on this board.
  - **Costs:**
    - Firmware loses the hard battery-side disconnect [SPEC s3].
    - Battery-only quiescent drain is UNVERIFIED ([REC] tens of µA with telemetry off).
    - Any EVM jumper that bypasses the INFET must be removed.
    - The POR default problem returns only after a pack disconnect.

## 10. I2C, rails, status, thermistor
- **Address:** 0x68 (7-bit) [REC, UNVERIFIED]. No conflict: the Ag105 (0x30) is removed, and the charger is the only device on
  the bus [SPEC s3].
- **SMBus levels:**
  - Open-drain. Compatible with the Teensy's 10 kΩ pull-ups to 3V3 and 100 kHz [REC].
  - VIH/VIL and the SDA/SCL absolute maximum are UNVERIFIED.
  - Whether an unpowered LTC4015 clamps SDA/SCL is UNVERIFIED. This matters only if D-BT-SQ is kept (unpowered between bursts).
- **DC2039A QuikEval (DC590/Linduino) connector:** pull-ups to the connector's supply [REC]. **Remove them** and do not connect a
  DC590, so the 3V3 rail is not back-powered and SDA/SCL never go to 5 V.
- **STAT:** there is no STAT pin. SMBALERT (open-drain [REC]) could go to pin 6 with `INPUT_PULLUP`, but its semantics differ
  (alert, not charging). Use the I2C `CHARGER_STATE` / `CHARGE_STATUS` registers [REC names] as the readiness source.
- **Thermistor:**
  - NTC pin with a bias resistor from NTCBIAS [REC]. JEITA is on by default for Li-ion [REC].
  - With J-NTC empty, an open NTC probably reads "cold" and pauses charging, which would silently kill every cold-start burst.
  - **Fit a 10 kΩ fixed resistor** (or the NTC) at THERM / J-NTC. Check the demo board's default NTC fitting (UNVERIFIED).

## 11. Efficiency / thermal (16 V and 8 V at 2.5 A)
- Not read. [REC] expects ~93-95 % at 16 V → 8.4 V, 2.5 A with the DC2039A's 8 A-class FETs (about 1-1.5 W loss; thermally trivial
  on that board).
- **Light-load (~2 W regen) efficiency is the concern:** fixed-frequency PWM with large FETs. Switching frequency and the
  light-load mode are UNVERIFIED.

## 12. Size / mounting
- DC2039A dimensions are UNVERIFIED (a demo board with terminals and a QuikEval header, far larger than 32 × 35 mm [SPEC s7]).
  It cannot sit on the footprint.
- **Option 1: off-board on short twisted leads.**
  - VIN pair ≤ 1.0 A to VCHG-IN/GND.
  - BAT pair ≤ 2.5 A to VCHG/GND, or to VBT/GND if D-BT-SQ is bridged.
  - SDA/SCL/GND plus enable and THERM on a small cable from the Ag105 pads.
  - The capacitance audit (section 7) must account for lead inductance and ringing at hot-plug.
- **Option 2:** LTC4015 (38-lead 5 × 7 QFN [REC]) on a custom ≤ 32 × 35 mm carrier using the 22 holes. A two-sided carrier is
  probably feasible at 2.5 A, but that is effectively a mini re-spin, overlapping Path B.

## 13. Price / stock / lead time
- Mouser 44 pcs, about USD 152 [TRIAGE]. Not re-verified here. Also listed at Farnell/element14 (4032839) and Digi-Key (9664282) [WS].

## 14. Firmware impact (summary)
- Replace `pollAg105` / `initAg105Charger` / `ag105IsReady` with LTC4015 equivalents:
  - `I_charge` from IBAT;
  - VIN/VBAT telemetry;
  - CHARGER_STATE as readiness;
  - with D-BT-SQ kept, re-write ICHARGE/IIN/VCHARGE/JEITA/MPPT after every input power-up, and keep `suspend_charger` set until
    then (this only shortens, not prevents, the autonomous POR start).
- Keep `chargerHasPower()`. Port the `J` guards G1-G3 and the trip latch. The `AG105_VBATN_ISOLATED` gate becomes "charger return
  verified".
- Pin 5 meaning changes (enable via UVCL divider). Pin 6 → SMBALERT or unused. **The CSV goes first.**

## 15. Bench checklist before committing
1. Read the DC2039A schematic: GND continuity VIN-return ↔ BAT-return; CIN/CSYS values; the INFET bypass option; NTC default;
   QuikEval pull-ups.
2. Read the LTC4015 datasheet:
   - UVCL mechanism and range;
   - POR defaults of every charge register;
   - battery-detection algorithm and retry;
   - watchdog (if any);
   - cold-start timing;
   - CV accuracy;
   - SDA/SCL absolute maximum and unpowered behaviour.
3. Bench (M1): VIN step 0 → 21 V at 12 V/ms (RT1987 profile) to time-to-90 % of ICHARGE, with D-BT-SQ kept and bridged.
4. Bench: stiff 15.8 V source with UVCL at 19.0 V gives ≈ 0 A (R3).
5. Bench: inrush on the FC path stays ≤ 1.0 A including CIN + CSYS.

## Sources consulted
- [LTC4015 datasheet listing, dtsheet doc 1686583](https://dtsheet.com/doc/1686583/ltc4015---multichemistry-buck-battery-charger-controller-...) (search summary only)
- [DC2039A demo manual, dtsheet doc 1998572](https://dtsheet.com/doc/1998572/dc2039a---demo-manual) (search summary only)
- [DC2039A.pdf at analog.com CCE](https://www-cce.cldnet.analog.com/media/en/technical-documentation/user-guides/DC2039A.pdf) (search listing only)
- [Digi-Key LTC4015 PTM tutorial](https://www.digikey.com/en/ptm/l/linear-technology/ltc4015-multi-chemistry-buck-battery-charger-controller/tutorial?slide=6) (UVCL and MPPT description)
- [alldatasheet LTC4015 page](https://html.alldatasheet.com/html-pdf/719056/LINER/LTC4015_15/471/3/LTC4015_15.html) (absolute maximum snippet)
- [Farnell DC2039A](https://no.farnell.com/analog-devices/dc2039a/demo-board-battery-charger/dp/4032839), [Digi-Key DC2039A](https://punchouttest.digikey.com.mx/en/products/detail/analog-devices-inc/DC2039A/9664282)
- Blocked (DNS, outside the allowed domains): datasheet.chipsmall.com, docs.ampnuts.ru.
