# Dossier: TI BQ25713 on the BQ25713EVM-017, Path A replacement for the Ag105 (board rev 20260622)

Date: 2026-11-05. Candidate: BQ25713EVM-017 (user guide SLUUBT8B), IC BQ25713/BQ25713B (datasheet SLUSD83C). The IC is an
NVDC buck-boost charge controller with external FETs and a P-channel BATFET.

## How the sources were read
- **Primary PDFs were NOT fetched.** `www.ti.com` and `wmsc.lcsc.com` fail DNS in this session, which means they are outside the
  allowed network domains. Per tool policy I stopped trying further hosts. No PDF copy was saved to `datasheets/`.
  **To close this dossier, allow www.ti.com (lit/ds/symlink/bq25713.pdf and lit/ug/sluubt8b/sluubt8b.pdf) in the session network
  settings.**
- Evidence tiers used below:
  - **[NOTE]** = `docs/bq25713_charger_replacement_2026-11-04.md`. Its author read SLUSD83C and SLUUBT8B in full text. Section
    numbers are as cited there. This is a secondary source.
  - **[WS]** = web-search summaries of TI or datasheet-mirror pages. Tertiary; treat as UNVERIFIED leads.
  - **[SPEC]** = `charger_eval/spec.md`.
  - **UNVERIFIED** = not read in any primary source.
- Every number in this dossier needs a primary re-read before procurement.

## 1. Verdict
- **Fit score: 6 / 10.**
- **Fuel-cell charging: strong fit.** Common ground by architecture, a 2S CV strap, VINDPM inside the R3 window, POR ChargeCurrent = 0,
  and a 5 s watchdog are all available.
- **Regen: weak fit as wired.** Under R3 each regen burst is a cold start. The BQ25713's adapter-detect deglitch ([WS] 50 ms) and
  possible converter power-up delay ([WS] 150 ms in one revision) put cold-start latency at or beyond the 100 ms hard maximum
  [SPEC section 5]. Only the burst's tail would be captured.
- Regen becomes viable only if the charger stays input-powered and R3 is enforced by VINDPM (19.0 V) plus a hardware Hi-Z
  comparator (section 6). That moves R3 from "preferred" (hard off) to "acceptable" (regulation loop plus a hard-off comparator
  that is armed from VBUS), and needs an operator ruling.
- The EVM's footprint size, its input capacitance and the I2C pull-up rail must be dealt with by modification.

## 2. Common ground (R-GND)
- **Verdict: PASS by IC architecture. The EVM schematic was not re-read in this session.**
- Charge current is sensed by SRP/SRN across RSR (10 mOhm, R8) in the battery positive path. SRN also senses battery voltage
  [NOTE section 2 pin table, section 3].
- Input current is sensed by ACP/ACN across RAC (10 mOhm, R2), high-side in VBUS [NOTE section 3].
- The power stage (4-switch buck-boost) returns to PGND. Nothing sits in the battery negative path. EVM J1 GND and J5 GND are both
  board GND [NOTE section 3, section 4].
- **Before ordering:** confirm on the SLUUBT8B schematic (section 3.2) that no shunt or jumper sits between J1-GND and J5-GND.

## 3. Pad mapping (Ag105 removed, EVM off-board on a carrier)

| Ag105 pad / net | EVM | Notes |
|---|---|---|
| VIN+ (VCHG-IN) | J1 VIN | Keep JP1 on and JP7 top (bypasses Q9/Q10, factory setting) [NOTE section 3]. The board's RT1987s do the input switching. |
| VIN- / VBAT- (GND) | J1 GND, J5 GND | One node. |
| VBAT+ (VCHG to D-BT-SQ to pack) | J5 BAT | CV is regulated at SRN, which is the VCHG node, not the pack. |
| none | J6 SYS | **Leave unloaded.** If SYS were loaded, supplement mode could discharge VCHG. |
| Teensy 18/19 | J3 SDA/SCL | See section 9. |
| Teensy 6 CHARGER_STAT | J2 CHRG_OK | Open drain, active high = adapter valid [NOTE section 2, SLUSD83C s9.3.3.1]. Needs a 3.3 V pull-up. |
| Teensy 5 MPPT_DISABLE | J2 ILIM_control | HIGH = Hi-Z (disable) on the EVM [NOTE section 5 item 1]. See section 8 for polarity. |
| THERM / J-NTC | none | The BQ25713 has no TS/NTC pin (UNVERIFIED: pin list from recollection). Read the NTC on a spare Teensy ADC after a CSV update, or leave it unused. |

## 4. VIN operating range, absolute maximum and OVP
- VBUS/ACP/ACN recommended range: 0 to 24 V. Absolute maximum: -0.3 to 30 V [NOTE: SLUSD83C s8.3, s8.1].
- ACOV (input OVP): rising 25 / 26 / 27 V min / typ / max; falling 23.5 / 24.5 / 25 V; 100 µs deglitch [NOTE s8.5]. [WS] flags
  that the falling ACOV threshold differs between datasheet revisions, so re-read it.
- EVM operating range: VIN 3.5 to 24 V [NOTE section 3].
- Against [SPEC section 2]:
  - Operating range of 12 to at least 23 V with no OVP trip: **met** (23 V < 24 V recommended < 25 V ACOV min).
  - Absolute maximum of at least 30 V: **met with zero margin.** The preferred 36 V is not met.
- **(a) Regen headroom above the ~21.4 V clamp:**
  - 2.6 V to the 24 V recommended maximum.
  - 3.6 V to ACOV min. Above ACOV the converter simply stops; it is not damaged.
  - 8.6 V to the 30 V absolute maximum.
  - The V-MOT overshoot above 21.4 V is unmeasured [SPEC open question 1]. The 47 Ohm chopper sinks only about 0.46 A. **Measure
    the V-MOT peak with a scope before wiring.** If the peak exceeds about 24 V, add a TVS (SMBJ24A class) on VCHG-IN, or accept ACOV
    drop-outs at the peak.
  - The EVM's own VIN capacitor voltage rating is UNVERIFIED. If they are 25 V parts, they have the same issue as the board's C-D8
    and C-D10.

## 5. Input capacitance and inrush, question (b)
- The EVM's VIN bulk capacitance (SLUUBT8B Table 4 / section 3.2) is **UNVERIFIED**. [WS] found the table but not its rows.
- Bound [SPEC section 6]: C_chg <= ~50 µF effective, hard limit ~80 µF, and no electrolytic. The RT1987 slews at 12 V/ms, giving
  12 mA per µF.
  - Board 20 µF plus EVM 40 µF gives 0.72 A of inrush plus aux load, which is close to the about 1.0 A FC-mode budget.
- **Mod:** inventory the EVM VIN capacitors. Depopulate any electrolytic or polymer bulk part and keep at most about 30 to 40 µF
  ceramic (after DC-bias derating). Swap the board's C-D8/C-D10 to 35 V parts per [SPEC].
- The buck-boost start-up runs the converter after the CHRG_OK deglitch (section 7), well after the 1.3 to 1.75 ms RT1987 ramp. That
  meets [SPEC] "must not start switching during the ramp".

## 6. Input-voltage threshold (R3) and FC/regen mode switching
- **VINDPM** = InputVoltage register REG 0x0B/0x0A: 3.2 V offset, 64 mV LSB, range 3.2 to 19.52 V. The reset value is VBUS - 1.28 V
  (measured at power-up) [NOTE: SLUSD83C s9.6.6.1.3].
  - It can be written over I2C at any time, so it can be switched at runtime:
    - 13.5 V (FC mode) = code (13.5 - 3.2) / 0.064 = 160.9, rounded to 161, giving 13.504 V.
    - 19.0 V (regen mode) = code 246.9, rounded to 247, giving 19.008 V.
  - 19.0 V leaves 0.52 V of register range [NOTE].
  - VINDPM accuracy is **UNVERIFIED**. The spec needs about +/-3.5 % at 19 V.
  - VINDPM is a regulation loop, not an off switch. Per [SPEC section 4] it is in the "acceptable" class. Bench-verify that it draws
    about 0 A from a stiff 15.8 V source when set to 19 V.
- **Hard-off modes:**
  - ILIM_HIZ below 0.4 V enters Hi-Z; above 0.8 V exits [NOTE s8.5].
  - Register Hi-Z bit REG 0x35[7] [NOTE].
  - CHRG_INHIBIT bit in ChargeOption0 [NOTE s9.6.1.1].
  - ChargeCurrent = 0.
- **No programmable hysteretic input UVLO.** The only input threshold is the fixed VBUS_CONVEN detection level [WS: about 3.2 to
  3.5 V]. So the "preferred" R3 layer is not native to the IC.
- **Proposed hardware R3 layer (UNVERIFIED that the comparator suits this; needs a primary read of its specs):**
  - Use the on-chip independent comparator (CMPIN/CMPOUT, EVM header J4 [NOTE section 3]).
  - Feed CMPIN from a divider on VBUS (VCHG-IN). Wire the open-drain CMPOUT onto ILIM_HIZ, wired-OR with the Teensy's control.
  - Result: a hysteretic hardware input-UVLO that forces Hi-Z below the threshold.
  - Switch the threshold between 13.5 V and 19.0 V with an NMOS across one divider leg. Gate it from the FC_CHARGE net (J1.45/46);
    a low or floating gate gives 19 V, which is safe [SPEC section 4 recommendation].
  - The comparator reference, polarity, deglitch and POR default are UNVERIFIED.

## 7. Start-up latency, question (d)
- CHRG_OK rising deglitch: **50 ms** after VBUS exceeds about 3.5 V ([WS], from several mirrors of SLUSD83 B/C).
- One datasheet revision reportedly says the **converter powers up 150 ms** after VBUS exceeds VBUS_CONVEN [WS, ic-components
  mirror]. Unresolved, **UNVERIFIED**.
- POR register reset happens 5 ms after a supply is valid. That figure is from the sibling BQ25723 [WS], so it is UNVERIFIED for
  the BQ25713.
- The ChargeCurrent soft start steps in 64 mA increments at 8 µs per step [WS], so 2.5 A takes about 0.3 ms (negligible).
- Host writes take about 6 registers x 16 bit at 100 kHz, about 3 ms. They are only possible once VDDA is up.
- **Estimated input-applied to 90 % current: about 55 to 60 ms (if the 50 ms deglitch gates switching) up to about 155 to 160 ms (if
  the 150 ms figure applies).** Add 12 to 20 ms of board overhead.
- Against [SPEC section 5] (≤ 30 ms target, ≤ 100 ms hard maximum): **FAIL on the target, marginal or FAIL on the hard maximum**,
  for cold-start regen. For FC charging, latency is irrelevant.
- **Mitigation:** keep the charger powered through the regen phase, with REGEN closed and VINDPM at 19.0 V plus the comparator Hi-Z.
  The VINDPM/Hi-Z exit is then the only delay (Hi-Z exit time UNVERIFIED). This needs an operator ruling on R3.
- Measure M1 on the bench.

## 8. Fail-safe disable and POR defaults, question (c)
- **ChargeCurrent resets to 0** (REG 0x03/0x02, 64 mA LSB at 10 mOhm, 64 mA to 8.128 A) [NOTE s9.6.3]. Charging does not start until
  the host writes it. **Met.**
- **Watchdog:**
  - WDTMR_ADJ: 00 = off, 01 = 5 s, 10 = 88 s, 11 = 175 s (POR default) [NOTE s9.3.10.1]. [WS] confirms the 175 s default for the
    BQ25713, and the 5 s / 88 s encoding on sibling parts.
  - On expiry, only ChargeCurrent resets to 0 [WS]. Set it to 5 s on every power-up. That meets the ≤ 5 s requirement.
- **Teensy reset:**
  - Layer 1, RT1987 EN pull-downs: the input is cut, so the BQ25713 loses VBUS. With VBAT only a 10 µF capacitor behind D-BT-SQ, it
    PORs, and ChargeCurrent = 0 on the next power-up.
  - If an input path somehow stayed powered, the charger would keep its last setting until the 5 s watchdog expires.
- **ILIM_control polarity:** HIGH = disable [NOTE section 5 item 1], so a floating Teensy pin means enabled. This is not fail-safe on
  its own, though it is mitigated by POR ChargeCurrent = 0.
  - **Mod, preferred:** a small NMOS or NPN inverter, so pin 5 HIGH = enable. Put a 47 kOhm pull-down on the inverter input and a
    pull-up on ILIM_control so a floating input means Hi-Z.
  - **Alternative:** a 10 kOhm pull-up from ILIM_control to the Teensy 3V3, with the firmware driving LOW to enable. This inverts
    the MPPT_DISABLE meaning; update the CSV first.

## 9. I2C and rails
- Address 0x6B, 7-bit (D6h) for the BQ25713; the BQ25713B differs [NOTE s9.5]. There is no conflict, because the charger is the only
  device and the Ag105's 0x30 is gone.
- SDA/SCL tolerate up to 6.5 V [NOTE s8.3], so 3.3 V logic is fine. Unpowered clamping is presumed absent given the 6.5 V rating
  (UNVERIFIED).
- **Pull-up back-powering:** the EVM 3V3 comes from an on-board LDO fed from VIN (JP8) [NOTE section 3 and section 5 item 4].
  - With the input unpowered, the EVM pull-ups (value UNVERIFIED) sit on a dead rail. They fight the Teensy's 10 kOhm pull-ups, idle
    the bus at about mid-rail and back-feed the Teensy 3V3 into the dead LDO output.
  - **Mod:** remove JP8 and feed J3-3V3 from the Teensy 3V3 (J1.29/30). Or remove the EVM SDA/SCL pull-ups.
  - Then check what else on the EVM runs from 3V3 (CHRG_OK pull-up, ILIM pre-bias via JP5). UNVERIFIED.
- Use 100 kHz.
- **Watchdog servicing:** write ChargeCurrent or ChargeVoltage within 5 s.
- Registers are lost on every input power cycle (section 10). The firmware must rewrite them on every power-up.

## 10. Behaviour behind D-BT-SQ, question (e)
- **CV:**
  - The CELL_BATPRESZ divider at 40 % of VDDA sets 2S, giving MaxChargeVoltage 8.400 V by default and SYSOVP 12 V [NOTE s9.3.3.3].
    So the most critical setting is resistor-strapped and survives every POR. EVM jumpers for 2S: JP2 on, JP3 and JP4 off [NOTE].
  - CV is regulated at SRN, which is VCHG, so the pack ends 35 to 50 mV low. That is about 8.36 V, -0.4 to -0.6 %.
  - The ChargeVoltage register could raise the setting to about 8.43 V. The LSB and the ±0.5 % accuracy class are UNVERIFIED.
- **Open-output start:**
  - CELL_BATPRESZ is a divider, not a detector, so "battery present" is asserted regardless [NOTE section 5 item 5].
  - VCHG starts near 0 V, below VSYS_MIN (2S default UNVERIFIED). So the BATFET starts in linear or pre-charge mode with clamped
    current (value UNVERIFIED). It charges the 10 µF to about 8.4 V in well under a millisecond.
  - D-BT-SQ then closes once VCHG > VBT + 35 mV. The possible extra 8 ms tD_ON on leaving UVLO is UNVERIFIED [SPEC].
  - D-BT-SQ re-closes as a step load with no soft start; the charger's current loop absorbs it.
  - The pack (7.4 to 8.4 V) is above VSYS_MIN, so charging then runs in fast-charge mode.
- **Termination is host-controlled** [NOTE s9.4.1.2]. There is no autonomous recharge cycling problem, but the firmware must
  terminate on taper, using the pin-25 V_batt plus the IC's ADC IBAT readback (ADC register map UNVERIFIED).
- **NVDC/BATFET:**
  - The BATFET body diode conducts BAT to SYS. With SYS unloaded and D-BT-SQ blocking the pack, there is no back-feed path to VBUS.
  - The input FET bypass (JP1/JP7) is safe, because no battery-side source can reach VBUS: the pack is behind D-BT-SQ, and the
    buck-boost high-side body diodes point the other way.
- **Registers are lost every input cycle.** VDDA is supplied only from VBUS, or from VBAT, which is just the VCHG capacitor.
  - Rewrite sequence on every CHRG_OK rise: WDTMR = 5 s, VINDPM (mode value), IIN_HOST (FC 1.0 A), ChargeVoltage (optional trim),
    ChargeOption0 as needed, then ChargeCurrent last.
  - Until then, the reset VINDPM of VBUS - 1.28 V applies. At a 15.8 V bus that is about 14.5 V, which is harmless because
    ChargeCurrent = 0.

## 11. Charge-current setting
- ChargeCurrent: 64 mA LSB at RSR = 10 mOhm; range 64 mA to 8.128 A; POR 0 [NOTE s9.6.3].
  - 2.5 A = code 39, giving 2.496 A.
  - 0.25 A = code 4, giving 0.256 A.
- Input limit: IIN_HOST register combined with the ILIM pin (JP5 pre-bias). The lower of the two wins. LSB UNVERIFIED (expected
  50 mA at 10 mOhm).
- FC mode at 1.0 A input gives about 1.7 A output at an assumed ~94 % efficiency.

## 12. Efficiency and thermal at 16 V in, 8 V out, 2.5 A
- Typical curves are UNVERIFIED (not read). This is a buck-mode operating point. A low-90s % class is expected for this IC family,
  giving about 1.2 to 1.5 W of loss spread over the EVM's external FETs and inductor (the EVM is rated for 8 A).
- Thermal margin is ample if the EVM is off-board, away from the LM1084.
- Light-load efficiency at regen's ~2 W, and whether PFM or out-of-audio mode is available, is UNVERIFIED.

## 13. Status output
- CHRG_OK means VBUS is valid, not "charging". Charge state comes from I2C ChargerStatus (fast/pre-charge, fault bits; register
  address UNVERIFIED).
- PROCHOT is available but not needed.
- Pin 6 needs a pull-up (INPUT_PULLUP, or a 10 kOhm resistor to the Teensy 3V3).

## 14. Thermistor
None on the IC (UNVERIFIED). There is no JEITA in hardware. The host can implement a temperature cutoff if it reads J-NTC via a spare
ADC pin. Pin 13 is unused.

## 15. Size and mounting
- EVM dimensions are UNVERIFIED; [NOTE] says it is far larger than the 32 x 35 mm footprint.
- Mount it off-board, or hover it on a carrier plugged into the 22 Ag105 holes. Leads: about 2.5 A battery side, about 1.5 A input
  side, as short as possible and twisted.
- Count lead inductance against the EVM's ceramic VIN capacitors: possible input ringing on the RT1987 step. Scope it.

## 16. Price, stock and lead time
About USD 154 (task brief); DigiKey about 12 units, DigiKey NL 4 (about EUR 179); TI "limited quantities" [NOTE section 5 item 7].
Not re-verified this session (UNVERIFIED).

## 17. Required EVM and board modifications
1. 2S: JP2 on, JP3 and JP4 off. Verify CELL is about 2.7 V.
2. Keep JP1 on and JP7 top (input FET bypass).
3. Remove JP8 and feed J3-3V3 from the Teensy 3V3, or remove the EVM I2C pull-ups.
4. ILIM_control fail-safe: an inverter with a pull-down so pin 5 HIGH = enable, or a pull-up to the Teensy 3V3 with active-LOW enable
   (CSV first).
5. Depopulate EVM VIN bulk capacitance to ≤ ~30 to 40 µF effective ceramic, with no electrolytic or polymer parts.
6. Board C-D8 and C-D10: change to ≥ 35 V parts.
7. Add a CHRG_OK pull-up to 3.3 V.
8. Leave J6 SYS unloaded.
9. Optional: a CMPIN divider from VIN with a mode-select NMOS gated by the FC_CHARGE net, and CMPOUT onto ILIM_HIZ (hardware R3).
10. Optional: a TVS on VCHG-IN if the measured V-MOT peak exceeds about 24 V.
11. Firmware: a new 0x6B driver; rewrite registers on every power-up; 5 s watchdog servicing; host termination; port the `J`
    guards G1 to G3 and the trip latch; CSV updates for any pin meaning changes.

## 18. Risks
- The cold-start latency (50 to 150 ms, UNVERIFIED) defeats burst regen under strict R3.
- Regen headroom is only 2.6 V to the recommended maximum, with the V-MOT overshoot unmeasured.
- The 30 V absolute maximum leaves zero margin against the spec minimum.
- EVM input capacitance and its voltage rating are unknown.
- I2C pull-ups on a dead rail.
- ILIM_control polarity is not fail-safe without a modification.
- Registers are lost every input cycle: the firmware must sequence every write with ChargeCurrent last.
- The VINDPM loop has no off state; a bus-fed draw is possible if VINDPM is mis-set or reset to VBUS - 1.28 V while ChargeCurrent is
  not 0.
- Stock is thin and the EVM is not RoHS-production hardware.
- Pack CV ends about 0.4 to 0.6 % low behind D-BT-SQ.
- Off-board leads (ringing, EMI).
- No hardware NTC.

## 19. Showstoppers
- None confirmed.
- **Conditional:** if the measured cold-start latency exceeds 100 ms and the operator keeps R3 as hard-off with a cold start per
  burst, the regen goal is not met. That would leave this candidate an FC-charging-only solution.
