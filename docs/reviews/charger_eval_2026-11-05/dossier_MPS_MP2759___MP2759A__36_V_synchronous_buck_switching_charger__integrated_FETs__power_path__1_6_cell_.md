# Dossier: MPS EV2759-Q-00A / EV2759-Q-01A / EV2759A-Q-00A (MP2759 / MP2759A) for Path A

## Source access: the primary documents were NOT read

- **Blocked hosts.** WebFetch could not reach www.farnell.com (datasheet 3632066.pdf) or www.mouser.com (EV2759A-Q-00A.pdf). Both failed with `getaddrinfo ENOTFOUND`, meaning they are outside the session's allowed network domains. Following the tool's guidance, no further hosts were tried (elecfans, monolithicpower.com, components.ru, jiepei).
- **To finish this dossier:** allow at least `www.monolithicpower.com` (or farnell / mouser) in the session network settings, then re-run.
- **No PDF was saved.** No copy of any MP2759 document exists under `datasheets/`.
- **What the facts below rest on.** Every MP2759 fact here comes from WebSearch result snippets that quote the datasheet or the EVB documents. They are tagged **[SNIP]** with the URL the snippet came from.
  - Snippet facts are second-hand, so **none of them is a primary-source verification.** Treat every one as UNVERIFIED until the PDF is read.
  - Board-side facts come from `spec.md` (tagged [SPEC]).

Snippet sources:
- [SNIP-F] https://www.farnell.com/datasheets/3632066.pdf (MPS MP2759 datasheet, 2021 revision per the snippet)
- [SNIP-C] https://cdn.components.ru/media/PDF/8093961.pdf (older MP2759 datasheet copy, 2020)
- [SNIP-E] https://pdf.elecfans.com/MPS/EV2759-Q-01A.html (EV2759-Q-01A EVB doc / quick start)
- [SNIP-M] https://www.mouser.com/pdfDocs/EV2759A-Q-00A.pdf (EV2759A-Q-00A EVB doc Rev 1.0, 7/29/2021)
- [SNIP-D] Digi-Key / Mouser product listings for EV2759A-Q-00A and EV2759-Q-01A
- [SNIP-FORUM] https://forum.monolithicpower.com/t/mp2759-not-working-with-36v-power-suply/3775
- [SNIP-MAN] https://manuals.online/mps/motherboard/ev2759-q-00a/user-manual/1ofbx

## 1. Identity

**MP2759**
- Standalone (pin-programmed, **no I2C**) synchronous buck switching charger with integrated FETs, for 1-6 series Li-ion/Li-polymer cells.
- Operates from a "maximum 36 V DC input" with "hold-off up to 45 V" [SNIP search summary].
- "Up to 3 A" charge current [SNIP-D, SNIP-M].
- Four charge phases (trickle, pre-charge, CC, CV) and a safety timer [SNIP search summary]. Timer duration UNVERIFIED.

**MP2759A**
- Same family; its EVB is the EV2759A-Q-00A. Differences from the MP2759 are UNVERIFIED.
- One distributor title reads "36 V input, 26.4 V, 3 A". 26.4 V = 6 × 4.4 V, which matches the VB table's maximum.

## 2. Requirement-by-requirement assessment against spec.md

### 2.1 Common ground (R-GND, the reason for replacing the Ag105)
- **Verdict: UNVERIFIED.**
- The triage claim is that RS1 = 20 mΩ sits between CSP and BATT, in the battery positive leg (high-side). That would satisfy R-GND, but I did not see the EVB schematic.
- The snippets name the CSP/BATT sense function only indirectly.
- **What to check in the EVB schematic:**
  - RS1 sits between SW-inductor/CSP and BATT+.
  - VIN-, PGND, AGND and BATT- are one copper node with no FET or shunt.
  - The EVB has no reverse-battery FET in the BATT- return.
- Architecturally, a monolithic buck with CSP/BATT sense is high-side by construction, so PASS is likely once the schematic is read.

### 2.2 Input voltage, OVP, absolute maximum (spec section 2)
- **Operating input:** distributor listings give 10-36 V [SNIP-E summary of the listings].
- **Input OVP:** nominal 36 V, minimum 35 V, per an MPS forum user quoting the datasheet [SNIP-FORUM]. That is far above the 23 V requirement, so it will not trip at the regen peak. PASS (UNVERIFIED).
- **Absolute maximum:** "hold-off up to 45 V" [SNIP]. The datasheet's abs-max table was not read, so UNVERIFIED.
  - If IN abs-max is ≥ 40 V, the part beats the spec's ≥ 36 V preference.
- **EVB limitation: "the EV2759A-Q-00A can work safely in applications where VIN < 20 V"** [SNIP-M; same note for EV2759-Q-01A, SNIP-E].
  - The regen case reaches ~21.4 V or more [SPEC section 2 case B]. **The EVB as shipped is not rated for the regen peak.**
  - The likely cause is low-voltage input capacitors (UNVERIFIED). The fix is ≥ 35-50 V input capacitors on the EVB, plus the C-D8/C-D10 swap the spec already requires.
  - This limitation applies to the EVB, not the IC. It must be confirmed in the EVB BOM.

### 2.3 Input-voltage threshold for R3
- **The pin.** VLIM is the "input voltage limit setting pin. Connect to a resistor divider from VLIM to IN and AGND" [SNIP-C/jiepei]. "This pin can be pulled low to disable charging" [SNIP].
- **Hard off or regulation loop?** It is an input-voltage *limit* (DPM-type regulation): below the set voltage the charger reduces its current to hold VIN.
  - That is the spec's "acceptable" class (VINDPM), not a hysteretic hard UVLO.
  - Bench-verify that it draws ~0 A from a stiff 15.8 V source when the threshold is set to 19 V.
- **Reference voltage:** UNVERIFIED. The ~1.2 V figure belongs to other MPS parts (MP2633, MP2639A); a different part shows 1.49-1.55 V. Do not use either.
- **Programmable range:** set by the divider, so any value from the UVLO floor up to ~36 V is reachable in principle. The 13.5 V and 19.0 V points are both inside it. Reference tolerance is UNVERIFIED, so the ±3.5 % budget at 19 V is UNVERIFIED.
- **Runtime switching between ~13.5 V (FC) and ~19 V (regen):** no I2C, so it has to be done in hardware.
  1. Divider = R_top from IN, R_bot to AGND, sized for 19 V.
  2. Add R_par in series with an N-FET from VLIM to AGND. With the FET on, the threshold drops to 13.5 V.
  3. Drive the FET gate from the FC_CHARGE net (J1.45/46), with a gate pull-down.
  4. Result: a low or floating gate leaves the safe high threshold [SPEC section 4]. The RT1987's 8 ms turn-on delay means the gate settles before VCHG-IN appears.
- **Hard-off mode:** pull VLIM to AGND with a second N-FET, which disables charging [SNIP].

### 2.4 Fail-safe disable (spec section 3)
- **No dedicated EN pin is documented in the snippets.** Disable is done by pulling VLIM low [SNIP].
- **Polarity of a disable FET on VLIM:**
  - If the Teensy drives its gate directly, a HIGH gate disables charging, and a gate pull-down means "enabled" during reset. That is **not** fail-safe on its own.
- **Recommended circuit (fail-safe by layer 2):**
  1. Disable N-FET from VLIM to AGND, with its gate pulled up to a charger-local rail (from VCC/VIN through a resistor and clamp) so the charger defaults to **disabled**.
  2. A second N-FET pulls that gate low when Teensy pin 5 is HIGH.
  3. Net effect: pin 5 HIGH = enable, pin 5 LOW or high-Z = disable. This matches the spec's recommended active-HIGH enable.
  4. With a ≤ 47 kΩ pull-down on the pin-5 side, it also matches [FW] 6720, which drives pin 5 LOW in `setup()`.
- **Layer 1 is unchanged:** with no input power, RT1987 EN pins 30/31 are low with the 10 kΩ bodge pull-downs.
- **Watchdog:** the IC has none (no host interface). Host-silence shutdown must come from the firmware: drop pins 30/31 and pin 5 when the Pi link is lost.

### 2.5 I2C and rails
- **No I2C.** SDA/SCL (pads 8/7) stay unconnected, so there is no address conflict.
- **Back-powering:** the Teensy-side 10 kΩ pull-ups to 3V3 go nowhere. No back-powering path exists unless an EVB pull-up is tied to a charger rail. Check the EVB for a VCC pull-up on STAT/ACOK.
- **Benefit: no lost configuration.** All settings are resistor-strapped (CELL, VB, ISET, VLIM). The "settings lost every input-power cycle" problem [SPEC section 3] disappears, and nothing can boot from stale EPROM settings.
- **Firmware rework:** remove `pollAg105`, `initAg105Charger`, `ag105IsReady` and the reg 0x02 MPPT manager. The GENSTAT readiness source goes away.

### 2.6 2S CV configuration and accuracy
- **CELL pin:** 30-40 kΩ to AGND selects 2 cells (Table 1, [SNIP-F]).
- **VB pin (per-cell voltage):**
  - AGND = 3.6 V; 30-40 kΩ = 4.0 V; 60-70 kΩ = 4.1/4.15 V (Table 2, [SNIP-F]).
  - 100-110 kΩ = 4.2 V; 160-170 kΩ = 4.35 V; pull-up to VCC = 4.4 V (2020 copy, [SNIP-C]).
- **For this pack:** CELL 30-40 kΩ plus VB 100-110 kΩ gives 2 × 4.2 = 8.40 V. The 4.2 V row must be confirmed in the 2021 table; the snippet was cut off there.
- **Accuracy:** "0.5 % battery regulation voltage accuracy" appears in the EV2759-Q-00A manual listing [SNIP-MAN]. The IC electrical table was not read: UNVERIFIED. ±0.5 % meets the spec's ≤ ±0.5 % at the limit.
- **CV is set in discrete steps only.** It cannot be trimmed to compensate D-BT-SQ's 35-50 mV drop. The pack would finish ~8.36 V (spec section 3, −0.42 %). Accept this, or bridge D-BT-SQ.
- **EVB defaults:** the EV2759-Q-01A ships configured 3-cell, 4.2 V [SNIP]. **It must be re-strapped for 2S before first power, or it will try to charge to 12.6 V.** BQ29200 detection at 4.35 V/cell drives nothing [SPEC 0.4], so this is a pack-overcharge hazard.

### 2.7 Charge-current setting
- **Resistor setting:** a resistor from ISET to AGND sets the charge current [SNIP]. The formula and the RS1-dependent scaling were not read: UNVERIFIED.
- **MCU adjustment:** MPS application note AN155 ("Using a microcontroller to adjust the MP2759 charging current", monolithicpower.com) describes adjusting ISET from an MCU. It was not fetched, so UNVERIFIED. A spare Teensy pin (PWM into RC, or a DAC on pin 10/16/17) could implement it, after a CSV update first.
- **Maximum:** "up to 3 A" [SNIP-D/M]. Whether 3 A appears in the IC datasheet's recommended operating table is UNVERIFIED.
- **2.5 A capability:** inside the 3 A rating.
- **EV2759-Q-01A inductor note:** the fitted inductor is for "700 kHz or charge current < 2.5 A". At 450 kHz or above 2.5 A, choose higher L or higher Isat [SNIP-E]. Running at ≤ 2.5 A on the stock inductor is within the note.
- **Input current limit for FC mode (≤ 1.0 A):** no separate input-current-limit pin is documented in the snippets. UNVERIFIED.
  - If none exists, FC-mode input current must be bounded through ISET: charge current × VBAT / (η × VIN) ≤ 1.0 A, which means about ≤ 1.6 A output at 15.8 V.
  - So FC mode needs ISET switched too, either in hardware alongside the VLIM FET or through AN155-style MCU control.
- **Lower bound:** a minimum of ≤ 0.25 A is UNVERIFIED.

### 2.8 Operation through D-BT-SQ (ideal diode between charger output and pack)
- **Battery-detection behaviour of the MP2759: UNVERIFIED.**
- **Risk 1, no battery seen at start-up.** With EN high and an unpowered charger output at 0 V, the charger sees no battery (only 10 µF) until VCHG > VBT + 35 mV.
  - Many standalone chargers run a battery-detect / "battery absent" routine that toggles the output or flags a fault. Read the datasheet's battery-detection and trickle-charge sections.
- **Risk 2, trickle charge on a 0 V output.** The IC starts in trickle charge (an open output looks like 0 V). It would deliver trickle current into C-D11 and climb to pre-charge and then CC once the output passes VBT. This adds latency.
- **Risk 3, auto-recharge cycling.** After termination, VCHG decays (D-BT-SQ blocks the pack), which triggers auto-recharge cycling.
  - The firmware must remove input power (pins 30/31) or disable via VLIM after termination. Terminate on the board's V_batt (pin 25) and its own current estimate.
- **Risk 4, CV sensed on the wrong side.** CV sense is BATT on VCHG, not on the pack. A Kelvin wire from VBT at C-D12 into BATT would move CV onto the pack, but then RS1 sense (CSP/BATT) would include D-BT-SQ in the loop.
  - That only works if D-BT-SQ is bridged. Keep the standard connection and accept the ~0.4 % undercharge.
- **Bridging D-BT-SQ:** the MP2759 is described as having power path [triage], so check reverse blocking from BATT to IN when the input is unpowered. An internal block FET would prevent back-feed into VCHG-IN (an R3 concern). UNVERIFIED.

### 2.9 Start-up latency (spec section 5: ≤ 30 ms target, ≤ 100 ms maximum)
- **UNVERIFIED.** No snippet gave the VIN-good deglitch, the soft-start time, or the trickle/pre-charge timer behaviour.
- Standalone MPS chargers commonly carry input-detection deglitch and soft-start delays in the tens of ms, but that is a generic expectation, not a cited number.
- **Bench measurement M1 is mandatory:** input applied to 90 % of ISET, with a cold output at 0 V behind D-BT-SQ.
- The trickle → pre-charge → CC progression while the output climbs from 0 V to ~7.4 V may dominate the delay.

### 2.10 Status output
- STAT/ACOK pins are likely open-drain, but their existence and polarity were UNVERIFIED (no snippet).
- An open-drain STAT on pin 6 needs a pull-up to 3V3, from J1.29/30 or by changing the firmware to `INPUT_PULLUP`.
- **No digital readout of charge current exists**, so `I_charge` telemetry would have to come from the board's own sensing. That is a loss against Ag105 reg 0x06.

### 2.11 Thermistor
- The IC has an NTC pin (the snippet showed a pin label "NTC"). The thresholds and the EVB bias network are UNVERIFIED.
- With no NTC fitted on J-NTC, the EVB may need a fixed 10 k resistor to report "normal" temperature. Read the NTC section.

### 2.12 Input capacitance and inrush (spec section 6: C_chg ≤ ~50 µF effective, hard bound ~80 µF, no bulk electrolytic)
- The EVB input capacitor values were not read: UNVERIFIED.
- The "VIN < 20 V safe" note suggests 25 V ceramics. Check for an input electrolytic.
- **If one is fitted, remove it.** At 12 mA/µF, any capacitor above ~50 µF breaks the FC-mode OC_FC budget.

### 2.13 Efficiency and thermal (16 V in, 8 V out, 2.5 A)
- UNVERIFIED; no efficiency curve was read. Integrated FETs and a 36 V process give typically ~90 %, but that is not cited.
- About 20 W out means ~2 W of dissipation in a small QFN-19 next to the hot LM1084.
- Light-load (~2 W regen) efficiency is UNVERIFIED.

### 2.14 Size and mounting
- The EVB size was not read. MPS EV boards of this class are typically ~50 × 50 mm or larger (UNVERIFIED), which exceeds the 32 × 35 mm footprint.
- **Options:**
  - Mount off-board on short twisted leads.
  - Or better: build a carrier PCB with the MP2759 IC itself (QFN-19 3 × 3 class, UNVERIFIED) on a ≤ 32 × 35 mm board plugged into the 22 Ag105 holes.
- The IC's integrated FETs make that carrier feasible: only the inductor, RS1, input/output capacitors and strap resistors are external.

### 2.15 Price, stock, lead time
- **EV2759A-Q-00A:** listed at Digi-Key (15861764), Mouser, element14 (3890219).
- **EV2759-Q-01A:** listed at Digi-Key (14552495) and Farnell (3773209). The German Farnell page shows a "notify me when back in stock" banner, which suggests out of stock there.
- Prices were not captured: UNVERIFIED.
- The IC MP2759GQ-0000-Z/-P is listed at Farnell (3773211 / 3773208); MP2759AGQ-0000-P at element14 (3890220).

## 3. Showstoppers
None proven. Conditional showstoppers:
- **EVB rated only for VIN < 20 V** [SNIP-M, SNIP-E], while the regen peak is ~21.4 V or more. Use as shipped is excluded; the input capacitors (and anything else in the < 20 V note) must be re-rated.
- **EVB defaults to 3-cell 4.2 V** (EV2759-Q-01A). It must be re-strapped before first connection to the 2S pack, or it charges toward 12.6 V with no hardware OVP action on the board.

## 4. Risks
1. **R-GND is unverified.** High-side RS1 is the triage claim; the EVB schematic was not read.
2. **VLIM is an input-voltage regulation, not a hard UVLO.** R3 compliance relies on DPM settling to ~0 A from a stiff bus. Bench-verify, including stability from a high-impedance regen source.
3. **No documented input-current limit,** so FC-mode ≤ 1.0 A input must be enforced through ISET. ISET switching is needed in step with the VLIM threshold.
4. **No I2C:** no charge-current readback (I_charge telemetry lost), no status byte, no watchdog. All readiness comes from STAT plus board ADCs.
5. **Start-up latency is unknown.** Trickle/pre-charge phases on the cold 0 V output behind D-BT-SQ could exceed 100 ms. Battery-absent detection could misfire.
6. **Auto-recharge cycling** after termination, because D-BT-SQ isolates the pack. The firmware must remove input power at termination.
7. **CV in discrete steps:** the pack finishes ~8.36 V (−0.42 %) because of the D-BT-SQ drop, with no trim available.
8. **Thermal:** ~2 W in a small QFN next to the LM1084.
9. **EVB form factor** is likely larger than the footprint, which means a custom carrier or off-board leads.
10. **The "MP2759 vs MP2759A" differences are unknown.** Confirm which variant the chosen EVB carries and read that datasheet.

## 5. Required EVM modifications (provisional)
1. Re-strap for 2S: CELL 30-40 kΩ to AGND, VB 100-110 kΩ (4.2 V/cell). Verify against the 2021 Tables 1-2.
2. Replace the input capacitors with ≥ 35-50 V parts. Remove any input electrolytic. Keep total VCHG-IN capacitance ≤ ~50 µF effective. Resolve every item behind the EVB's "VIN < 20 V" note.
3. Set the ISET resistor for 2.5 A on the regen profile. Add an FC-mode ISET reduction (FET-switched or AN155 MCU control) so input current stays ≤ 1.0 A.
4. Set the VLIM divider to 19.0 V. Add an N-FET plus resistor to lower it to 13.5 V, gated by the FC_CHARGE net (J1.45/46), with a gate pull-down.
5. Add a fail-safe VLIM disable: a default-on pull-down FET (gate pulled up), released by Teensy pin 5 HIGH through an inverter FET with a ≤ 47 kΩ pull-down.
6. Fit a 10 k NTC-equivalent resistor if no NTC is on J-NTC (verify the bias network).
7. Remove any EVB pull-ups to its own rails on STAT/ACOK. Pull STAT up to Teensy 3V3.
8. Keep the stock inductor only for ≤ 2.5 A at 700 kHz [SNIP-E].
9. Replace C-D8/C-D10 (25 V) on the main board with ≥ 35 V parts [SPEC].
10. Update the IO CSV first for any new pin use (ISET control).

## 6. Fit score
- **5.5 / 10.**
- **For:** input headroom (35 V minimum OVP, 45 V hold-off) is the best of the simple parts. High-side sense is likely. Resistor-strapped settings remove the lost-config and stale-EPROM problems. A hardware VLIM threshold is switchable for R3. VLIM pull-low gives a disable.
- **Against:** the EVB is rated < 20 V and defaults to 3S. There is no I2C, so no readback and no watchdog. No input-current limit is documented. Latency and battery-detection behaviour behind D-BT-SQ are unknown.
- **Re-score after reading** the primary datasheet and the EVB schematic.
