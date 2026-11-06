# Dossier: TI BQ24650 / BQ24650EVM-639, Path A replacement candidate for the Ag105 (board rev 20260622)

Author: charger_eval subagent, 2026-11-05. Read against `spec.md` in this folder.

## 0. Source status (read this first)
- **ti.com and www.ti.com do not resolve in this cloud session.** The egress allowlist blocks them. So neither the BQ24650
  datasheet PDF (SLUSA75B) nor the EVM user guide PDF (SLUU444A) could be downloaded, and **no PDF copy is saved under `datasheets/`**.
  The session's network settings must allow `ti.com` / `www.ti.com` before this dossier can be closed out against primary PDFs.
  Following the tool's instruction, no further hosts were tried after the two TI failures. Mirrors that turned up in search
  (mouser, farnell, ciiva, scribd) were not fetched.
- **Every BQ24650 number below comes from WebSearch result text** that quotes the TI HTML document viewer for SLUSA75B
  (rev B, July 2010 to January 2020) or its translations ZHCSKO6B / JAJSBJ1B, or TI E2E answers.
  - Tag **[DS-snip]** = a datasheet table row as quoted in search results. The values are consistent across the EN/CN/JP mirrors, but the PDF was not read, so they are formally UNVERIFIED until the PDF is opened.
  - Tag **[E2E]** = a TI engineer's forum answer. This is weaker.
  - Board-side numbers come from `spec.md` and the repo sources it cites.
- **Revision check:** SLUSA75B (2020) gives VCC/SRP/SRN/STAT1/STAT2 = -0.3 to **33 V**, PH = -2 to **36 V**, SRP-SRN ±0.5 V. The 2010
  original gives **28 V / 30 V / ±0.2 V** [DS-snip, Abs Max]. **Design to SLUSA75B and confirm the die revision of the purchased
  parts.** The EVM itself is from 2010 (SLUU444A, Aug/Oct 2010), and its passives and FETs may be rated to the old 28 V class (UNVERIFIED).

## 1. Architecture vs the R-GND requirement
- The BQ24650 is a standalone synchronous buck controller: external high-side and low-side NMOS, BTST/HIDRV/PH/LODRV.
  - Charge current is sensed differentially across RSR between **SRP and SRN, in the BAT+ output path**. ITERM = 4 mV / RSR,
    about 1/10 of fast-charge current, which implies a 40 mV full-scale regulation drop [DS-snip / E2E]. The 40 mV figure is UNVERIFIED in the PDF.
  - Battery voltage is sensed through a VFB divider from the battery node, regulating to about 2.1 V at VFB [E2E: "When VFB is 50 mV below 2.1 V, then we will recharge"].
  - There is one GND pin. Input return, power ground and battery return are one node by construction. No low-side shunt and no
    battery-side FET exist in the architecture.
- **Verdict: PASS by architecture, UNVERIFIED on the EVM.** The SLUU444A Figure 8 schematic (p.17 per an element14 forum post) could not be read.
  - Known EVM fact: input diode **D1 (PDS1040)** sits in the positive input leg (VSYS ≈ VIN minus one diode; element14 forum).
    It sits in the positive leg, so it does not break ground continuity.
  - **Action before purchase:** open SLUU444A Figure 8 and confirm that the input "-" terminal, PGND and the battery "-" terminal are one copper net with no 0 Ω/jumper/shunt between them.
- Generic "BQ24650 5 A MPPT module" boards (AliExpress, reviewed by beyondlogic.org) usually copy TI's application circuit, but the schematic could not be read here.
  Each listing must be checked for a negative-leg element (UNVERIFIED). Use one only as a backup.

## 2. Input voltage, threshold (R3) and mode switching
| Item | Value | Source | vs spec |
|---|---|---|---|
| VCC/SRP/SRN abs max | 33 V | SLUSA75B Abs Max [DS-snip] | meets required ≥30 V; misses preferred 36 V |
| PH abs max | 36 V | same | ok |
| MPPSET, TS, REGN, LODRV, TERM_EN abs max | 7 V | same | – |
| Recommended input | 5–28 V | TI product page (search text) | covers 12–23 V, no OVP trip (the BQ24650 has no input OVP comparator found in any snippet; UNVERIFIED) |
| VCC UVLO rising | 3.65 / 3.85 / 4.0 V, hyst 350 mV | [DS-snip] | far below the spec's ≥10 V start; the 1.5 s enable delay (below) is the effective start guard |
| VCC LOWV | charge off < 4.1 V falling, on > 4.35 V rising | [DS-snip] | – |
| SLEEP comparator | VCC − SRN falling 40/100/150 mV, hyst 500 mV; power-up deglitch 30 ms | [DS-snip] | VCHG-IN 15.8 V vs SRN ≈ 8 V: awake |
| **MPPSET regulation** | **1.2 V**, about ±0.6 % input-regulation accuracy; VIN_REG = 1.2 V·(1 + R3/R4) | [DS-snip] | hardware threshold, the Ag105 method done right |
| **MPPSET disable / enable** | **< 75 mV disables charge; > 175 mV re-enables** | [DS-snip] VMPPSET_CD / VMPPSET_CE | fail-safe hardware enable |
| **Charge-enable delay** | **1.5 s from MPPSET > 175 mV until the charger may turn on** (also on every power-up, because MPPSET is divided from VIN) | [DS-snip] EC table | see section 5: **kills cold-start regen** |

**The R3 class is "acceptable", not "preferred".** MPPSET is an input-voltage *regulation* loop. Below the set point the loop cuts charge current toward zero
[DS-snip: "maintains the input voltage by reducing the charge current"]. One source says it stays in the loop at zero output current,
but whether switching stops is UNVERIFIED (datasheet section 8.3.9). It is not a hard UVLO-off. Two bench checks are required:
- ~0 A from a stiff 15.8 V source at a 19 V set point;
- loop stability from the high-impedance regen source.

The hard off is MPPSET < 75 mV.

**Runtime programmability:** none by register (no I2C). Two thresholds are selectable in hardware.
- Proposed network (my design, UNVERIFIED on the bench):
  - R3 = 148 kΩ (VIN side) and R4 = 10.0 kΩ + 4.42 kΩ in series. Q_sel (small NMOS) sits across the 4.42 kΩ.
  - Q_sel ON (default): 1.2·(1 + 148/10.0) = **18.96 V**, the regen threshold.
  - Q_sel OFF: 1.2·(1 + 148/14.42) = **13.52 V**, the FC threshold.
  - Q_sel's gate is pulled up to BQ24650 VREF (3.3 V, live only while the charger is powered) and pulled down by Q_inv, whose gate is the **FC_CHARGE net (J1.45/46)**.
  - Result: FC_CHARGE low or floating gives the high 19 V threshold, which is the fail-safe side.
  - The RT1987's 8 ms tD_ON and the BQ24650's own 1.5 s enable delay mean the select line is always settled before the converter may switch.
- Divider tolerance: use 0.1 % parts. The 19.0 V setting needs ≤ ±3.5 % (spec section 4), and 1 % parts plus ±0.6 % comfortably meet it. 18.96 V minus 3.5 % = 18.3 V = TPS61288 OVP min.

**Hard disable (fail-safe):** NMOS Q_en from MPPSET to GND.
- Q_en's gate is pulled up to VREF (100 kΩ) and pulled down by Q_drv. Q_drv's gate is Teensy pin 5 with a ≤ 47 kΩ pull-down.
- Teensy pin 5 LOW or high-Z (reset): Q_drv off, Q_en on, MPPSET < 75 mV, **no charging**.
- Pin 5 HIGH: charging is enabled after 1.5 s.
- This matches spec section 3 layer 2: an active-HIGH enable with a pull-down. Pin 5 changes meaning from MPPT_DISABLE (active-LOW inhibit) to CHG_ENABLE, so update the CSV first.
- The existing `setup()` drives pin 5 LOW, which is already the safe level.
- Shorting MPPSET also clears the 30-min precharge-timeout fault latch (POR or MPPSET < 75 mV resets charge enable [E2E]).

## 3. Charge-current setting
- RSR sets the current: I_CHG = 40 mV / RSR (UNVERIFIED in the PDF; consistent with ITERM = 4 mV/RSR ≈ 1/10). There is no ISET pin and no register.
  - For 2.5 A: RSR = 16 mΩ (the triage figure). The EVM factory setting is about 2 A (triage; SLUU444A BOM not read, UNVERIFIED).
- **There is no input current limit.** FC mode must keep the bus-side draw ≤ ~1.0 A (spec section 2A; OC_FC latches at 1.4 A on one sample), and the 13.5 V MPPSET only acts once the bus has *already* sagged.
  - At 2.5 A out: 8.4·2.5/0.9 ≈ 23 W ≈ 1.48 A from 15.8 V, plus 0.10–0.15 A aux → **OC_FC trip.**
  - **Recommendation: RSR ≈ 24 mΩ (≈1.67 A)**, giving ≈ 15.6 W ≈ 0.99 A in. The η = 0.90 assumption is UNVERIFIED (the EVM efficiency curve was not read).
  - This costs nothing for regen, which averages ~0.2 A and ~0.7 J per decel ([P37] 3.2). It does give up the "2.5 A capable" line of the spec.
  - Fast-charge time from the FC rises about 1.5x. A switched parallel RSR is possible but adds an FET's Rds in the sense path. Not recommended.
- No charge-current readback. To keep `I_charge` in telemetry, add a high-side current monitor on the VCHG lead into a spare ADC pin (10, 16, 17, 20–23, 33, 34; CSV first).
  Alternative: a differential amp across RSR itself.

## 4. CV, 2S configuration and accuracy
- VFB regulates to ≈ 2.1 V [E2E]. A 2S 8.40 V divider ratio is 4.0. Example: Rtop 30.1 kΩ / Rbot 10.0 kΩ → 8.42 V. Choose the actual values from the datasheet VFB figure, which is UNVERIFIED.
- Charge-voltage regulation accuracy is UNVERIFIED (not in the snippets; the PDF EC table is needed). The spec needs ±0.5 %.
- EVM rework: the EVM ships for a higher cell count (it supports up to 26 V output, TI product page; factory VREG UNVERIFIED). The **VFB divider must be reworked to 8.4 V before first connection.** With no hardware OVP acting on the pack (spec 0.4), this is the single most important rework.
- Recharge comparator: VFB 35/50/65 mV below VREG, 10 ms deglitch [DS-snip]. That is 140–260 mV at the 8.4 V output.
- TERM_EN: high (> 1.6 V) allows termination, low disables it [DS-snip].

## 5. Start-up latency (section 5 of spec)
- Cold start = VCC above UVLO → 30 ms power-up deglitch [DS-snip] → **1.5 s charge-enable delay** [DS-snip] → battery detection (a battery is present if VFB rises above the recharge threshold within 500 ms [DS-snip, 8.3.21]) → soft start of 8 steps × 1.6 ms = 12.8 ms [DS search text].
  - Total ≳ **1.54 s** plus the board's 12–20 ms.
  - Spec: ≤ 30 ms target, ≤ 100 ms hard maximum. Regen bursts last 0.3–0.6 s.
  - **Cold-start regen under R3 layer 1 (charger unpowered until V-MOT > bus) is impossible: the burst is over before the charger may switch.** SHOWSTOPPER for regen as the spec's section 5 frames it.
- **Only workaround: always-armed regen.**
  - Keep REGEN (D-BC-RG) closed for the whole of Run. The charger stays powered from V-MOT, which equals the bus at ~15.85 V. Keep MPPSET enabled with the 19 V set point.
  - The charger then sits in input regulation at zero current, and draws only when braking lifts V-MOT above 19 V. Latency becomes the VIN-regulation loop's recovery from zero current (UNVERIFIED; measure as M1). It is not the 1.5 s timer.
  - Does soft start re-run when leaving input regulation? The text says it repeats "each time the charger re-enters fast charge", and whether VINDPM exit counts is UNVERIFIED.
  - **This replaces R3's "charger unpowered in Run" layer with the regulation threshold alone.** It is the spec's "acceptable" class, and it needs an **operator ruling on R3**: the charger IC and EVM quiescent load would be bus-fed in Run at mA level.
  - Termination would not fire in this state: VCHG decays through the VFB divider (D-BT-SQ blocks the pack), so VFB stays below the recharge threshold.
  - Firmware's REGEN/FC_CHARGE mutual exclusion still holds. FC mode is unaffected.
- **FC charging:** the 1.5 s delay is harmless. Firmware asserts FC_CHARGE, then pin 5 HIGH, and accepts a ~1.6 s ramp.

## 6. Behaviour through D-BT-SQ (the RT1987 ideal diode between charger output and pack)
- SRN/VFB see VCHG, not the pack. CV lands at the pack 35–50 mV low (spec section 2): about 8.35–8.365 V. Compensate VREG to ~8.43 V only if the datasheet's VREG accuracy is ≤ ±0.3 % (UNVERIFIED).
- **Battery detection is a real risk.** Per [E2E], the IC sources current out of SRN and watches VFB. If VFB climbs past the threshold, it declares "absent" and retries.
  - D-BT-SQ needs VCHG above its 3.0–3.35 V UVLO, then possibly an 8 ms tD_ON (UNVERIFIED, spec Q3), before it conducts.
  - If the detect current lifts 10 µF + the output cap past the threshold before D-BT-SQ conducts, the charger may call "battery absent" and cycle.
  - A nearly full pack (> ~8.2 V) may legitimately read "absent". That outcome is benign.
  - **Bench item:** detect on a 7.4 V and an 8.2 V pack through D-BT-SQ.
- Auto-recharge cycling after termination (VCHG bleeds down through the VFB divider): **tie TERM_EN LOW.** Firmware ends charge by current (via the added INA) or by V_batt (pin 25), and drops pin 5.
- **No reverse blocking in the IC.** The high-side FET's body diode conducts VCHG to VIN.
  - With D-BT-SQ in place only the output cap can back-feed. That is benign: D-BC-FC/RG are ideal diodes and block onward.
  - **If D-BT-SQ is ever bridged,** the pack would hold VCHG-IN at ~8 V through the body diode: SLEEP state and a parasitic drain. The EVM's input Schottky D1 must then stay in circuit.
- Output short / step loads: D-BT-SQ can re-close as a step load (RT1987 Table 1). The BQ24650 has cycle-by-cycle current limiting, but its threshold is UNVERIFIED. Bench check.

## 7. Fail-safe disable during Teensy reset
- Layer 1 (existing): the RT1987 EN pull-downs keep VCHG-IN unpowered (spec section 3).
- Layer 2 (new): MPPSET is shorted by Q_en unless pin 5 is actively driven HIGH (section 2 above). With pin 5 high-Z, the 47 kΩ pull-down keeps the charger disabled. This holds regardless of the Teensy reset pad state (UNVERIFIED, spec Q6).
- Power-on default: no stored settings exist. Every parameter is resistor-strapped, so behaviour is identical on every input-power cycle. **This removes the Ag105 EPROM problem** (the stored 12.85 V threshold) and the spec's "settings lost each input cycle" issue.
- Watchdog: none in the IC (no host interface). Firmware or the Pi watchdog must drop pin 5 and the path switches. Where this lives: the existing State-99 path.
- In always-armed regen mode the charger is enabled with no host interaction. A firmware hang leaves the regen path armed at 19 V. That is acceptable because 19 V sits above anything the boosts produce, but it must be noted in the R3 ruling.

## 8. I2C and rails
- No I2C. The Ag105 SDA/SCL pads stay unconnected. The board's 10 kΩ pull-ups to Teensy 3V3 terminate on nothing. There is no address conflict and nothing to back-power.
- Firmware: delete the I2C side of `pollAg105`, `initAg105Charger`, `ag105IsReady`, the reg-0x02 MPPT manager and the `J` I2C steps.
- Back-powering the 3.3 V logic signals:
  - Q_drv's gate is the only Teensy-driven node. It drives a gate, not a charger pin, so an unpowered charger cannot be back-powered.
  - STAT1/STAT2 are open-drain, rated to 33 V [DS-snip]. Pull them up to Teensy 3V3 (J1.29/30 or J2.05/06) or use `INPUT_PULLUP`.
  - Q_sel/Q_en pull-ups go to the charger's own VREF, so no Teensy rail ties to a charger rail.

## 9. Status output
- STAT1 and STAT2 are open drain. Truth table UNVERIFIED (the snippets did not include it).
- Only pin 6 (CHARGER_STAT) is wired. STAT2 needs a spare pin (CSV first) or a wired-OR with loss of fault discrimination.
- Use V_batt, V_chg (pin 38) and the added INA as the primary readiness signals. STAT is secondary.

## 10. Thermistor
- TS pin with a VREF-referenced window. E2E reports a suspend outside ~1.6–2.5 V; the datasheet thresholds are UNVERIFIED.
- With no NTC fitted (spec Q5), a fixed divider must place TS mid-window. Wire J-NTC through to the TS network with a bias resistor, or strap it. The EVM's TS network is UNVERIFIED.

## 11. EVM input capacitance and inrush
- EVM input capacitance and voltage rating: **UNVERIFIED** (SLUU444A BOM not read).
- Limits from spec section 6:
  - **C_chg ≤ ~50 µF effective** (hard ≤ 80 µF) at 12 mA/µF.
  - No bulk electrolytic.
  - Parts ≥ 35 V, because V-MOT reaches ≥ 21.4 V and VCC is rated to 33 V.
- Remove any EVM electrolytic or excess MLCC. Also swap the board's C-D8/C-D10 (25 V) to ≥ 35 V.
- The 1.5 s enable delay guarantees no switching during the 1.3–1.75 ms RT1987 ramp.

## 12. Efficiency and thermal (16 V → 8 V, 2.5 A / 1.67 A)
- UNVERIFIED: the SLUU444A efficiency curves and the datasheet application curves were not read.
- Synchronous buck at about 300 kHz with external FETs (switching frequency UNVERIFIED). Expect ~90 %+ at 1–2.5 A. Light-load efficiency at ~2 W regen is unknown: check the spec's ≥ 80 % target on the bench.

## 13. Size and mounting
- EVM board dimensions UNVERIFIED. It is very likely larger than the 32 × 35 mm Ag105 outline.
- Options:
  - Mount off-board on short twisted leads to the Ag105 pads: VIN+ pin 10, VIN- pin 4, VBAT+ 18/19, VBAT- 14/15 (spec section 7).
  - Better: lay out a **custom ≤ 32 × 35 mm carrier** with the BQ24650 (VQFN-16), two NMOS, an inductor, RSR and the strap/FET network. This fits the 22-hole footprint and keeps the section-6 capacitance under control.

## 14. Price, stock and lead time
- UNVERIFIED (the DigiKey page was not fetched). Triage note: DigiKey shows a 12-week lead time for BQ24650EVM-639. BQ24650RVAR (the IC) is listed at LCSC (C53712; price and stock not read).
- Generic modules cost USD 5–15 (triage figure, UNVERIFIED).

## 15. Required EVM / board modifications (Path A)
1. VFB divider to 2S 8.40 V (or 8.43 V, see section 6). Verify before first connection.
2. RSR to 24 mΩ (1.67 A, FC-budget-safe) or 16 mΩ (2.5 A, only if FC charging is current-limited elsewhere).
3. MPPSET network: 148 kΩ / (10.0 kΩ + 4.42 kΩ) with Q_sel gated by the FC_CHARGE net (J1.45/46) → 19.0 V default, 13.5 V in FC mode.
4. Q_en / Q_drv hard-disable on MPPSET. Pin 5 becomes an active-HIGH CHG_ENABLE with a ≤ 47 kΩ pull-down. CSV first.
5. TERM_EN tied LOW (no auto-termination/recharge cycling behind D-BT-SQ).
6. TS strapped mid-window, or J-NTC wired with a bias.
7. STAT1 (and STAT2 if a pin is found) pulled up to 3V3.
8. Input capacitance cut to ≤ ~50 µF effective, all ≥ 35 V. Also swap the board's C-D8/C-D10 to ≥ 35 V.
9. Confirm EVM GND continuity input↔battery, and remove the EVM's input diode D1 only if D-BT-SQ stays fitted. Keep D1 if D-BT-SQ is bridged.
10. A high-side current monitor on the VCHG lead to a spare ADC pin (CSV first), to keep `I_charge`.
11. Firmware: remove Ag105 I2C code; add the CHG_ENABLE sequencing (FC_CHARGE first, then pin 5, then a 1.6 s wait); port the J-guards G1–G3 and the trip latch; and, if ruled, the always-armed regen mode.

## 16. Fit score: 5.5 / 10
- **Strengths:**
  - Common ground by architecture.
  - Hardware MPPSET threshold with a fail-safe hard-disable via one GPIO.
  - No stored state, no I2C.
  - Abs max 33/36 V (rev B).
  - Cheap and simple.
- **Weaknesses:**
  - The **1.5 s charge-enable delay kills cold-start regen.** Regen is viable only in an always-armed mode that weakens R3 layer 1 and needs an operator ruling.
  - No input current limit, which forces RSR ≤ ~1.67 A for the FC budget.
  - Regulation-class (not hard-off) R3 threshold.
  - No telemetry.
  - Battery-detect behaviour through D-BT-SQ is unknown.
  - The EVM's 2010 rating class.
- **FC charging alone fits well.**
