# Dossier: TI BQ25720 on the BQ25720EVM (BQ25723EVM sibling), Path A candidate

## Source-access caveat (read first)
- **No primary PDF could be retrieved.** www.ti.com, ti.com and www.ti.com.cn are all blocked. The gateway returned 403 to CONNECT, and WebFetch reported "ENOTFOUND" (outside the allowed domains). pdf.elecfans.com was blocked the same way. Following the tool's guidance, I made no further attempts on other mirrors (alldatasheet, mouser, ampheo).
  - **To unblock:** allow ti.com in the session network settings, then fetch SLUSDU3 (bq25720.pdf) and SLUUC74 (sluuc74.pdf).
  - A mirror copy of SLUUC74 exists at resources.ampheo.com/static/datasheets/texas-instruments/bq25720evm.pdf and on mouser.com.
- **Evidence classes below:**
  - [DV]: text from TI's own SLUSDU3 (May 2021) document viewer or PDF, quoted through WebSearch result extraction. This is primary text, but I did not open the PDF myself, so table and section numbers are not confirmed.
  - [E2E]: TI E2E forum answer (thread 1253760). Secondary.
  - [SIB]: value read in a sibling datasheet, not in SLUSDU3.
  - UNVERIFIED: not read in any source.
- None of the datasheet pages were copied to datasheets/, because none could be downloaded.
- The spec references `spec.md` sections; board facts come from it.

## 1. Identity
- **IC:** BQ25720. SMBus, 1-4 cell, NVDC buck-boost charge controller ("SMBus 1- to 4-Cell Narrow VDC Buck-Boost Battery Charge Controller", SLUSDU3, May 2021) [DV].
- **I2C sibling:** BQ25723 (BQ25723EVM). Same silicon family with an I2C register map (ChargeCurrent at 03/02h, like the BQ25713) [DV, BQ25723 search result].
- **EVM:** BQ25720EVM, user guide SLUUC74 (May 2021). U1 = BQ25720 on the BQ25720EVM, BQ25723 on the BQ25723EVM [DV of SLUUC74 TOC]. BOM is Table 3-1 and the schematic is Figure 3-7; neither was read (UNVERIFIED).
- **Firmware port:**
  - The BQ25720 is **SMBus**: ChargeOption0 12h, ChargeCurrent 14h, ChargeVoltage 15h, InputVoltage 3Dh [DV]. These differ from the BQ25713's I2C map (02h/04h/0Ah).
  - So "same register model" holds at the field level, but every address changes.
  - **The BQ25723EVM is the right choice if the BQ25713 driver draft is to be reused verbatim.** Its address and map are UNVERIFIED here, but [DV] shows 03/02h for ChargeCurrent.

## 2. Common ground (R-GND)
- **Architecture:** charge-current sense RSR is across SRP/SRN in BAT+, and input sense RAC is across ACP/ACN on the high side of the input [DV pin names; SIB SLUSD83C pin table]. No sense element sits in the return. This is the opposite of the Ag105.
- **EVM:** J1 = VIN / PGND [DV SLUUC74 test-setup text]. The BAT and PGND continuity on Figure 3-7 was NOT read.
- **Verdict: UNVERIFIED** (architecture PASS). Close it by reading SLUUC74 Figure 3-7. Check that the J1 PGND, BAT GND and SYS GND pours are one node with no shunt, and that any battery-removal jumper (JP4 "battery removal" [DV]) is in BAT+, not BAT-.

## 3. VIN operating range, absolute maximum, OVP
| Item | Value | Class |
|---|---|---|
| Abs max SRN, SRP, ACN, ACP, VBUS, VSYS | -0.3 to 32 V | [DV] §8.1 table text; [E2E] "abs max 32V" |
| Abs max SRP-SRN, ACP-ACN | -0.5 to 0.5 V | [DV] |
| Input range (product page / family table) | 3.5-26 V | [DV] product page; BQ2577x family table |
| Recommended VBUS max | 26 V | [SIB] BQ25731 layout; **UNVERIFIED for BQ25720** |
| CHRG_OK window | HIGH after 50 ms deglitch when 3.5 V < VBUS < 25.8 V; LOW below 3.2 V or above 26.8 V | [DV] |
| ACOV | fixed threshold with hysteresis; trip if VBUS > VACOV_RISE for > 100 µs; recover below VACOV_FALL for > 1 ms; on trip, CHRG_OK low and converter disabled | [DV] |
| ACOV level | "26 V" | [E2E] only; VACOV_RISE/FALL min/typ/max **UNVERIFIED** |

Against the spec:
- **Absolute maximum:** 32 V meets the ≥ 30 V requirement but misses the ≥ 36 V preference.
- **Regen headroom:** about 4.4 V from the 21.4 V clamp to 25.8 V (CHRG_OK upper edge), versus about 3.6 V on the BQ25713 (25 V ACOV minimum).
- **Abs-max headroom:** 32 - 21.4 = 10.6 V over the unmeasured V-MOT overshoot.
- **Board work:** C-D8/C-D10 (25 V) must still be swapped to ≥ 35 V parts.

## 4. Input-voltage threshold (R3) and regen/FC mode switching
- **VINDPM register:** InputVoltage 3Dh. 8-bit code, 3.2 V offset, 64 mV LSB, range 3.2-19.52 V; host-writable after POR [DV]. "VBUS at no load - 1.28 V" is the POR behaviour/guidance [DV].
- **Runtime switching:** yes, by an SMBus write.
  - FC mode 13.5 V: code (13.5 - 3.2) / 0.064 = 160.9 -> 160, giving 13.44 V.
  - Regen mode 19.0 V: code 246.9 -> 247, giving 19.008 V.
  - Both fit inside the 19.52 V ceiling, but regen has only 0.5 V of headroom above 19.0 V.
  - VINDPM accuracy is UNVERIFIED.
- **It is a regulation loop, not a hard off.** Bench-verify that it draws about 0 A from a stiff 15.8 V source, and check stability from a high-impedance V-MOT source.
- **PROCHOT_VINDPM / LOWER_PROCHOT_VINDPM** choose between 83/91/100 % of VINDPM for PROCHOT only [DV]. Not useful here.
- **Hard offs:**
  - ChargeCurrent = 0, POR default [DV].
  - Watchdog expiry zeroes ChargeCurrent [DV].
  - CHRG_INHIBIT bit (ChargeOption0) [SIB SLUSD83C §9.6.1.1]; UNVERIFIED bit position on the BQ25720.
  - ILIM_HIZ pin Hi-Z: < 0.4 V enters, > 0.8 V exits [SIB]; UNVERIFIED on the BQ25720.
  - No hardware threshold-select pin exists, so the resistor-switch option in spec §4 is not available. Mode switching is SMBus-only.
- **Default at reset:** the POR VINDPM follows VBUS - 1.28 V [DV]. This is not a safe high threshold. Safety at POR therefore rests on ChargeCurrent = 0 until the host writes it, which is a PASS (see §8).

## 5. Charge current
- **ChargeCurrent 14h:** 64 mA LSB, 0-8128 mA, reset 0000h, 0 A at POR [DV]. The LSB assumes the reference RSR; the EVM's RSR value is UNVERIFIED (10 mOhm on the 713 EVM).
- **Charge start:** "After CHRG_OK goes high, the charge will start when the host writes the charging current to REG0x14()" [DV].
- **Settings:**
  - 2.5 A -> code 39 = 2.496 A.
  - 0.25 A -> code 4 = 0.256 A.
  - Input current limit IIN_HOST ≤ 1.0 A for FC mode. Register and LSB UNVERIFIED (family: 3Fh, 50 mA LSB at 10 mOhm [SIB]).
- **Termination:** host-controlled [SIB SLUSD83C §9.4.1.2]. UNVERIFIED on the BQ25720.

## 6. CV for 2S and accuracy
- **ChargeVoltage 15h:** 8 mV LSB, 3000-24000 mV. Default 4.2 V/cell from the CELL_BATPRESZ pin, so 2S = 8400 mV [DV].
- **Accuracy:** UNVERIFIED (±0.5 % on the BQ25713 [SIB]).
- **Compensation:** 8.43 V is code 1053.75. Use 8424 mV (1053) or 8432 mV (1054) only if accuracy proves to be ≤ ±0.3 %.

## 7. Operation through D-BT-SQ (ideal diode between SRN and the pack)
- **What the charger sees:**
  - SRN senses battery voltage at VCHG, not at the pack, so CV is set at VCHG.
  - The pack ends 35-50 mV low (spec §2).
  - The BQ25720 has no battery-detection gate on charging; the host writes ChargeCurrent.
  - CELL_BATPRESZ is a divider: a pin pulled low means "battery absent" [SIB]. It must be strapped high to its 2S level and must not be tied to sensing of the BAT node.
- **NVDC / BATFET:**
  - The BQ25720 drives a BATFET between VSYS and BAT. On the EVM the "BAT" connector is downstream of the BATFET, and SYS is regulated about 160 mV above VBAT minimum [SIB].
  - Wiring EVM BAT -> Ag105 VBAT+ pads (VCHG) with SYS left open: charge current flows only when VCHG rises above VBT + 35 mV. Until then the BQ25720 sees about 10 µF, which it treats as "battery present but low or absent".
  - Expected to work. **Bench-verify** that the charger does not fold back into pre-charge or a battery-absent mode when VBAT starts at 0 V. Pre-charge on the BQ2571x family is host-governed and limited (≤ 384 mA below VSYS_MIN [SIB]), so the first ~ms after power-up may be current-limited until VCHG exceeds VSYS_MIN. **VSYS_MIN (3Eh) must be written below 7.4 V** (UNVERIFIED default for 2S; family default 6.6 V for 2S [SIB]).
- **Power source when the input is absent:** the BQ25720 powers from the higher of VBUS or VBAT [DV]. With D-BT-SQ in place, VBAT (VCHG) collapses when the input is removed. That causes a POR each power-up, so registers are lost: ChargeCurrent returns to 0, which is fail-safe, but the config must be re-written every time.
- **Bridging D-BT-SQ** would keep the charger alive from the pack (quiescent draw on the pack is UNVERIFIED). It requires confirming that the EVM's input path blocks reverse flow from battery to VBUS.

## 8. Fail-safe disable
- **POR state:** ChargeCurrent = 0 A, so the charger does not charge after any POR until the host writes 14h [DV]. This beats the Ag105's EPROM-latched behaviour.
- **Watchdog:** 175 s default; 00b disables it. Expiry zeroes ChargeCurrent and keeps the other registers. ChargeVoltage or ChargeCurrent writes reset it [DV]. The spec asks for ≤ ~5 s; the family offers 5 s via WDTMR_ADJ = 01b [SIB]. UNVERIFIED that the BQ25720 encoding is the same.
- **Hardware disable pin:**
  - The EVM's ILIM_HIZ control is HIGH = disable on the 713 EVM [SIB], i.e. active-HIGH Hi-Z. A low or floating Teensy pin during reset then leaves the converter enabled.
  - On this board, layer 1 (RT1987 EN pull-downs) removes input power during a Teensy reset, and POR ChargeCurrent = 0 keeps it from charging. **Pin 5 does not need to be a fail-safe enable.**
  - Recommended use of pin 5:
    - Drive the ILIM_HIZ pin directly, with a 10 k pull-down to GND so that Hi-Z is the default (ILIM < 0.4 V = Hi-Z [SIB]).
    - The Teensy drives HIGH (> 0.8 V) to enable.
    - **This turns pin 5 into an active-HIGH enable with a pull-down, which is exactly the spec's layer-2 shape.**
    - Requires removing the EVM's ILIM pre-bias jumper and the ILIM_control inverter. The jumper designators are UNVERIFIED in SLUUC74.
  - Caution: ILIM_HIZ also sets the input current limit through its voltage level on this family. Driving it to 3.3 V gives the maximum ILIM from the pin, and the effective limit is the lower of the pin and IIN_HOST [SIB]. Set the limit by IIN_HOST. UNVERIFIED.

## 9. SMBus / I2C, pull-up rails
- **Address:** 7-bit 0x09 (SLUUC74 "target address 12(9)") [DV]. No conflict, because the charger is the only bus device.
- **Speed:** SMBus at 100 kHz; Teensy Wire default 100 kHz. Compatible. The SMBus 25-35 ms clock-low timeout means the Teensy must never stretch or hold SCL low (normal Wire behaviour).
- **Logic levels:** SDA/SCL thresholds are UNVERIFIED for the BQ25720 (the BQ25713 is fine with a 3.3 V pull-up, ROC to 6.5 V [SIB]).
- **3V3 rail (EVM JP8):** on = the on-board LDO (fed from the charger's VDDA/VIN side) drives EVM 3V3; off = supply 3V3 externally [DV].
  - **Remove JP8 and feed EVM 3V3 from the Teensy 3V3** (J1.29/30). Otherwise the EVM pull-ups sit on a dead rail whenever the charger is unpowered (always, outside charge windows), which can clamp the bus through the dead LDO.
  - Also remove the EVM's own SDA/SCL pull-ups if fitted, because the board already has 10 k to 3V3. Their designators are UNVERIFIED.
  - Back-powering of the BQ25720 through SDA/SCL when VDDA is dead is UNVERIFIED.

## 10. STAT output
- **CHRG_OK:** open-drain, active-high = input good [DV/SIB], with a 50 ms deglitch. Pin 6 needs a 3.3 V pull-up, either wired from J1.29/30 or by changing the firmware to INPUT_PULLUP.
- It indicates input presence only, not charging. Use the SMBus ChargerStatus register as the primary state (register address UNVERIFIED; 20h on the family).

## 11. Thermistor
- The BQ25720 has no battery NTC/JEITA input (the family uses CMPIN and PROCHOT; TS is absent [SIB]). UNVERIFIED.
- J-NTC (THERM pad) therefore stays unused, or is read by the Teensy on a spare ADC pin. Any new pin use must go into the CSV first.

## 12. Start-up latency (spec §5: ≤ 30 ms target, ≤ 100 ms hard maximum)
- **The structural floor is ≥ 50 ms:** CHRG_OK requires a 50 ms deglitch on VBUS [DV], and charging starts only after CHRG_OK is high and the host writes 14h [DV].
- **Converter power-up:** the family sibling powers up the converter 150 ms after VBUS rises above VVBUS_CONVEN (BQ25713/BQ25710 [SIB]). If the BQ25720 has the same delay, the total is about 150-170 ms plus the charge-current soft start (step and time UNVERIFIED; [DV] confirms an "internal soft start during charge enable" exists).
  - **Verdict: misses the 30 ms target for certain. Very likely misses the 100 ms hard maximum** on cold regen starts.
- **Burst capture:** regen bursts last 0.3-0.6 s and peak 0.10-0.20 s after onset (spec §2), so a cold-start charger captures at most the tail.
- **FC charging:** latency does not matter.
- **Ways to keep regen viable:**
  - (a) Keep VBUS powered through Run from V-MOT (D-BC-RG closed), with VINDPM = 19.0 V and ILIM_HIZ low (Hi-Z). On a regen edge, release Hi-Z (exit time UNVERIFIED). This draws quiescent current from the bus and closes REGEN with V-MOT at about bus level, which is the spec §2 C configuration, now bounded by VINDPM and Hi-Z. **R3 operator ruling needed.**
  - (b) Bridge D-BT-SQ so the device stays alive from VBAT. The 50 ms CHRG_OK deglitch still applies to a VBUS edge, so this does not remove the floor.
- **Measurement M1** on the bench is mandatory.

## 13. Efficiency and thermal at 16 V / 8 V / 2.5 A
- **Mode:** the buck works at 16 V -> 8.4 V.
- **Datasheet figures:** efficiency curves at this point are UNVERIFIED (none read). The family typically shows > 90 % at 20 W in buck mode [SIB, general]; treat that as UNVERIFIED.
- **Light load:** at regen's ~2 W, light-load efficiency is UNVERIFIED. The family uses PFM at light load (EN_OOA / PFM options) [SIB].
- **EVM layout:** the EVM is a large 4-layer-class layout with its own inductor. Thermal performance is not a concern at 21 W off-board, but the board sits near the LM1084 if hovered.

## 14. EVM input capacitance and inrush
- **Unknown:** the SLUUC74 BOM (Table 3-1) was not read, so the EVM VBUS capacitance is UNVERIFIED.
  - Family EVMs typically carry several 10 µF ceramics on VBUS plus a bulk electrolytic or polymer footprint [SIB, SLUUBT8B context]. That would exceed the spec §6 bound of ≤ ~50 µF effective (C × 12 mA/µF; OC_FC 1.4 A latch in FC mode).
- **Action:**
  - Count the VBUS-side capacitors on Figure 3-7.
  - Depopulate any bulk part.
  - Keep ≤ ~40 µF ceramic, which derates to about 20 µF effective at 16-21 V.
  - Check whether the EVM's input FETs (if any; the product page says "N-channel MOSFET selector" [DV]) can be jumpered into bypass, since the RT1987 does the switching. UNVERIFIED.

## 15. Size and mounting
- **Fit:** EVM dimensions are UNVERIFIED; it is far larger than the 32 × 35 mm Ag105 outline. It cannot sit in the footprint.
- **Mounting:**
  - Off-board on twisted leads: VIN/GND ~1.5 A, BAT/GND 2.5 A.
  - Or hover it on a carrier plugged into the 22 Ag105 holes.
- **Lead inductance:** keep the input leads short. The ceramic input capacitance at the EVM then sits at the far end of the lead, so the inrush bound in §14 still applies.

## 16. Price, stock, lead time
DigiKey listings (undated, from WebSearch):
| Region | Stock | Unit price (before tax) |
|---|---|---|
| UK | 5 | £138.01 |
| DE | not shown | €154.43 |
| CH | 4 | CHF 143.04 |
| JP | 4 | not shown (purchase cap every 30 days) |
- Manufacturer standard lead time: 12 weeks (DigiKey UK).
- Re-check before ordering.

## 17. EVM modifications required (all designators UNVERIFIED until SLUUC74 is read)
1. Remove JP8 and feed EVM 3V3 from Teensy 3V3. Remove the EVM SDA/SCL pull-ups.
2. Cell setting: strap 2S on the CELL jumpers.
3. Depopulate bulk VBUS capacitance; ≤ ~40 µF ceramic stays.
4. Bypass any EVM input FETs (the RT1987 already switches).
5. ILIM_HIZ: remove the pre-bias jumper. Wire Teensy pin 5 to ILIM_HIZ with a 10 k pull-down (Hi-Z default). Set IIN_HOST by SMBus.
6. Add a 3.3 V pull-up for CHRG_OK -> pin 6.
7. Leave SYS open.
8. On the board, replace C-D8/C-D10 with ≥ 35 V parts.
9. Firmware: SMBus driver at 0x09.
   - Write VSYS_MIN, ChargeVoltage 8400, IIN_HOST, VINDPM (mode-dependent) and watchdog 5 s on every input power-up after CHRG_OK, then ChargeCurrent last.
   - Port the J guards G1-G3 and the trip latch.
   - Pin 5 inverts meaning (HIGH = enable). Update the CSV first.

## 18. Showstoppers and risks
- **Showstopper (regen only):** cold-start latency ≥ 50 ms structurally (CHRG_OK deglitch) and plausibly ~150+ ms (sibling converter power-up). This breaks the ≤ 100 ms hard maximum for regen under R3 as written. It is fixable only by an R3 ruling (keep it powered from V-MOT in Hi-Z) or by accepting tail-only capture. FC charging is unaffected.
- **Risks:**
  - SLUSDU3 and SLUUC74 were not read directly.
  - Every table value above is index-extracted or sibling-sourced.
  - EVM input capacitance and common-ground continuity on Figure 3-7 are unverified.
  - ACOV min/typ/max are unverified.
  - The SMBus register map differs from the BQ25713 draft.
  - VINDPM's 19.52 V ceiling leaves only 0.5 V above the 19.0 V regen threshold.
  - The 32 V abs max is below the 36 V preference.
  - Pre-charge or VSYS_MIN behaviour into the 0 V VCHG node behind D-BT-SQ.
  - No thermistor input.
  - Off-board leads.

**Fit score: 5/10.** Good for FC charging and R-GND (by architecture). Weak for regen because of start-up latency. Pending a full read of SLUSDU3 and SLUUC74.
