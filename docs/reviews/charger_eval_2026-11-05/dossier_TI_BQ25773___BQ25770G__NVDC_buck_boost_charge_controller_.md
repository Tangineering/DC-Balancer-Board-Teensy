# Dossier: TI BQ25773 / BQ25770G (BQ2577x NVDC quasi-dual-phase buck-boost controller), Path A candidate

## Source-access caveat (read first)
- **No primary PDF could be retrieved.**
  - WebFetch reported ENOTFOUND (outside the allowed domains) for www.ti.com (the bq25770g.pdf symlink and SLUUD24) and for www.mouser.com (the bq25770g-3454118.pdf mirror).
  - Following the tool's guidance after the second blocked host, I made no further attempts. Untried mirrors: static6.arrow.com (bq25773.pdf), alldatasheet.com (BQ25773 HTML pages), manualslib.com (SLUUCY2).
  - **To unblock:** allow ti.com (or mouser.com / arrow.com) in the session network settings, then fetch SLUSEK7 (bq25773.pdf), SLUSFK8 (bq25770g.pdf), SLUUCY2 and SLUUD24.
  - Nothing was copied to `datasheets/`.
- **Evidence classes:**
  - **[DV]:** text from TI's own documents, quoted only through WebSearch result extraction. Section, table and page numbers are therefore NOT confirmed.
  - **[INF]:** my arithmetic on [DV] numbers.
  - **[SIB]:** a value from a sibling part (BQ25713/BQ25720/BQ25730/BQ25731). It is not a BQ2577x value.
  - **UNVERIFIED:** not read in any source.
- Board facts come from `spec.md` (cited as "spec §N").

## 1. Identity: which part and which EVM
| Item | Finding | Class |
|---|---|---|
| BQ25773 | "40V, I2C, 2- to 5-Cell, Narrow VDC Quasi Dual Phase Buck-Boost Battery Charge Controller". Datasheet **SLUSEK7**, Sep 2024 (JA: JAJSLS9) | [DV] |
| BQ25770G | "40V, SMBus, 2- to 5-Cell, Narrow VDC Quasi Dual Phase Buck-Boost" for GaN HEMTs. Datasheet **SLUSFK8**, Apr 2024 | [DV] |
| **SLUUCY2** | "BQ25770EVM, BQ25773EVM (BQ2577xEVM)": the silicon-FET EVMs | [DV] |
| **SLUUD24** | "BQ25770GEVM, BQ25773GEVM (BQ2577xGEVM)", May 2024: the GaN EVMs. U1 is BQ25770G on the BQ25770GEVM and BQ25773G on the BQ25773GEVM. The BQ25773 board uses the I2C port; the BQ25770 board uses SMBus | [DV] |
| EVM rating | 3.5-40 V input, 2-5 cell programmable output, 0-16.3 A charge. Maximum input 8.2 A with RAC = 10 mΩ (SLUUCY2) | [DV] |
| Host adapter | The EVM assumes a TI EV2400, sold separately | [DV] Mouser listing |

- **The triage label mixes two boards.** "BQ25773EVM" is documented in SLUUCY2 (silicon FETs). SLUUD24 is the GaN BQ2577xG family.
- **For this board, choose an I2C variant:** the BQ25773EVM (SLUUCY2) or the BQ25773GEVM (SLUUD24). The BQ25770G is SMBus. A Teensy can usually talk SMBus at 100 kHz, but the I2C part avoids SMBus timeout and PEC questions.
- **The "1S vs 2-5 cell" inconsistency is resolved: the BQ2577x family is 2-5 cell** (SLUSEK7 and SLUSFK8 titles). The 1-5 cell I2C parts are the BQ25730 and BQ25731 [DV]. This board's 2S pack sits at the **minimum** cell count, which is legal.

## 2. Common ground (R-GND), the key requirement
- **Architecture:**
  - Charge current is regulated differentially across SRP/SRN [DV], with the sense resistor RSR in the SYS-to-BAT high-side path.
  - Input current is sensed across ACP/ACN, with RAC in series with VBUS on the high side [DV pin names; SLUUCY2 quotes RAC = 10 mΩ].
  - In the NVDC family there is no sense element or switch in the return path. This is the opposite of the Ag105 (spec §0.3).
- **EVM:** the SLUUCY2 and SLUUD24 schematic and BOM were **not read**. I could not confirm:
  - that the input, battery and system grounds are one pour;
  - where any battery-disconnect jumper sits;
  - whether any shunt sits in PGND.
- **Verdict: UNVERIFIED** (architecture PASS). To close it, read the SLUUCY2/SLUUD24 schematic and check two things:
  - the VIN-, BAT- and SYS- terminals share one ground node with no shunt or FET between them;
  - any BATFET or battery-removal jumper sits in BAT+.

## 3. VIN operating range, absolute maximum, OVP
| Item | Value | Class |
|---|---|---|
| Input operating range | 3.5-40 V (product page, EVM guides) | [DV] |
| Absolute maximum on VBUS/ACP/ACN/SRP/SRN | **UNVERIFIED**. The triage's "45 V abs max (TI listing)" was not re-read | – |
| ACOV | Programmable via ACOV_ADJ, sized per input class (36 V EPR, 28 V EPR, 20 V SPR, 15 V SPR) to protect the converter MOSFETs. **Default 33 V ("28 V ERP application")**. FAULT_ACOV status bit is cleared by a host read | [DV] SLUSEK7 ACOV section |
| ACOV in the block diagram | A 41 V ACOV label appears, presumably the 36 V EPR setting | [DV], code-to-threshold table UNVERIFIED |
| CHRG_OK | Goes low when VBUS < 3.2 V or VBUS > ACOV rising. Returns high after a **50 ms deglitch** once VBUS recovers. Latched faults hold it low until the host clears them | [DV] |

Against the spec:
- **Regen headroom (spec §2 B, §8 Q1):** at the default 33 V ACOV, there is **11.6 V above the 21.4 V clamp**, against 3.6-4.4 V on the BQ25713/BQ25720 (24-26 V class). This is the candidate's main reason to exist. An unmeasured V-MOT overshoot to ~30 V would still not trip OVP.
- **Absolute maximum:** meets the ≥ 30 V requirement if the class is 40 V-plus, but the actual absolute maximum is UNVERIFIED.
- **Input UVLO:** start threshold 3.5 V is far below the spec's ~10 V. That is acceptable only because the converter does not start during the 1.3-1.75 ms RT1987 ramp: the 50 ms CHRG_OK deglitch dominates (§11).
- **C-D8/C-D10:** the 25 V parts must still go to ≥ 35 V (spec §2). That is the only input-side rework the candidate forces, as the triage said.

## 4. Input-voltage threshold (R3) and regen/FC mode switching
- **VINDPM register:** VINDPM() [DV]. The SLUSEK7 VINDPM accuracy table lists two register points [DV]:
  - VINDPM() = 0x384 → 18000 mV
  - VINDPM() = 0x0E0 → 4480 mV
  - **[INF]:** 900 × 20 = 18000 and 224 × 20 = 4480, so the register has a 20 mV LSB with no offset.
  - The register ceiling, field width and accuracy at those points are **UNVERIFIED**.
  - The sibling 3.2-19.52 V / 64 mV encoding belongs to the BQ25720/BQ25731 [SIB] and must NOT be applied here.
- **Codes for the two modes [INF]:**
  - FC mode 13.5 V: code 675 (0x2A3) → 13.500 V.
  - Regen mode 19.0 V: code 950 (0x3B6) → 19.000 V. This is valid if the field reaches above 18 V. That is very likely for a 40 V part but UNVERIFIED.
  - Resolution is fine enough for both spec §4 windows.
- **POR default:** VINDPM = measured no-load VBUS minus 1.28 V [DV]. At POR the converter shuts off, takes one VBUS ADC reading, then writes VINDPM [DV].
  - **Hazard for R3:** a cold start from the 15.8 V bus gets a default of about 14.5 V. That default would let the bus feed the charger.
  - The protection is that ChargeCurrent resets to 0 (§6). Firmware must write VINDPM before writing a non-zero ChargeCurrent on every power-up.
- **Runtime switching:** I2C write only. No hardware threshold-select pin was found (UNVERIFIED), so spec §4's FET-switched resistor option does not exist.
- **It is a regulation loop, not a hard off** (spec §4 "acceptable"). Bench-verify about 0 A from a stiff 15.8 V source at VINDPM 19.0 V, and check loop stability from a high-impedance V-MOT source.
- **Hard offs:**
  - ChargeCurrent = 0 [DV, watchdog text].
  - HIZ / ILIM_HIZ pin: a family feature [SIB BQ25713/BQ25720]; on the BQ25773 it is **UNVERIFIED**.
  - CHRG_INHIBIT bit: [SIB], UNVERIFIED on the BQ25773.

## 5. Charge current
- **Range:** BQ25770G 128-16320 mA with a 5 mΩ RSR; "up to 16.3 A / 30 A with 5 mΩ / 2 mΩ" [DV search excerpt].
  - [INF] This implies a 128 mA LSB at 5 mΩ. With a larger RSR (for example 10 mΩ) the LSB would likely scale to 64 mA, if an RSR-select bit allows it (RSNS_RSR, UNVERIFIED).
  - The BQ25773 LSB is **UNVERIFIED**.
- **2.5 A:** in range.
- **0.25 A floor (spec §2):** about 2 LSB at 5 mΩ, so coarse. Low-current accuracy is UNVERIFIED and likely poor near the bottom of a 16 A scale.
- **The EVM is sized for 16 A, about 200+ W.** For this ~20 W application it is a gross over-design. Swapping RSR to raise resolution is a rework of the EVM.
- **Input current limit:** IIN_HOST register [DV]. The final IIN_DPM can differ from IIN_HOST after ICO [DV]. The minimum and LSB are UNVERIFIED.
  - Spec §2 needs ≤ 1.0 A in FC mode. With the EVM's RAC = 10 mΩ that is plausible, but UNVERIFIED.

## 6. CV for 2S and accuracy
- **Register:** ChargeVoltage() at 0x04 (SLUUCY2 shows a 16.8 V example written to 0x04) [DV].
- **2S default:** CELL_BATPRES is read at converter start-up to set the cell configuration [DV]. Siblings default to 4.2 V/cell from that pin [SIB]. The BQ25773's 2S default (presumably 8.4 V) is **UNVERIFIED**.
- **LSB and accuracy:** **UNVERIFIED**. The family typically quotes ±0.5 % [SIB], which meets the spec's ±0.5 %. It does not meet the ±0.3 % needed before compensating for D-BT-SQ (spec §2).
- **Where CV is sensed:** at SRN/BAT, which on this board is VCHG upstream of D-BT-SQ. The pack therefore ends 35-50 mV low (~-0.42 %, spec §2). Write ~8.43 V only if accuracy is verified ≤ ±0.3 %.

## 7. Behaviour through D-BT-SQ (an ideal diode between charger output and the pack)
- **NVDC topology:** the converter regulates VSYS; a BATFET (external, driven by the charger; polarity on the BQ2577x UNVERIFIED) connects SYS to BAT through RSR.
- **On this board:**
  - There is no system load on SYS. The VSYS output can be left unloaded, or SYS and BAT tied on the carrier.
  - The BAT node is the VCHG polygon (10 µF, C-D11) followed by D-BT-SQ.
- **Battery detection:** with VCHG at 0 V and D-BT-SQ blocking, the charger sees "no battery". It powers up in NVDC mode, regulates VSYS to its minimum-system voltage (2S value UNVERIFIED), and charges the 10 µF.
  - D-BT-SQ conducts only once VCHG > VBT + 35 mV. Whether the charger's battery-present logic and pre-charge then behave correctly is **UNVERIFIED**.
  - The CELL_BATPRES pin presumably also flags battery presence; it can be strapped "present".
- **Termination and recharge:** the charger reads VCHG, not the pack. After termination VCHG decays through D-BT-SQ's own supply draw, so auto-recharge cycles. Firmware should terminate on the board's V_batt ADC (pin 25) and set ChargeCurrent = 0.
- **Battery-only / VAP behaviour [DV]:** with only a battery present, the device can charge VBUS from the battery to store energy in the input capacitors.
  - With D-BT-SQ in place the charger is never battery-powered, so this cannot occur.
  - **If D-BT-SQ is bridged (spec §3 option), the VAP/OTG modes must be confirmed disabled at POR.** Otherwise the pack could drive VCHG-IN. The RT1987s D-BC-FC and D-BC-RG block VCHG-IN → VBUS/V-MOT, so no bus back-feed results; only the input capacitors would be charged.
- **Configuration is lost every input-power cycle** (spec §3). There is no pack bias through D-BT-SQ, and the charger logic runs from VBUS. Firmware must re-write VINDPM, ChargeVoltage, IIN_HOST, the watchdog setting and ChargeCurrent, in that order, on every power-up.
- **Step-load re-close:** D-BT-SQ re-closes without soft-start after a reverse block (spec §2). The NVDC charger's cycle-by-cycle limit on the converter is a family feature; UNVERIFIED here.

## 8. Fail-safe disable during Teensy reset
- **Layer 1 (existing):** RT1987 EN pull-downs keep VCHG-IN unpowered. This is unaffected by the charger choice.
- **Layer 2 (POR):**
  - ChargeCurrent defaults to 0 and charging needs a host write. This is family behaviour; for the BQ25773 it is inferred from "watchdog timeout resets CHARGE_CURRENT() to 0 A" [DV]. The POR default itself is UNVERIFIED.
  - This passes spec §3's "no charging until the host enables it", because there is no EPROM.
- **Pin 5 reuse:** if the BQ25773 has an ILIM_HIZ pin (UNVERIFIED), pull it LOW for Hi-Z [SIB: < 0.4 V enters, > 0.8 V exits]. Pin 5 then becomes **active-HIGH "converter allowed", with a carrier pull-down to GND.**
  - This matches spec §3 exactly.
  - Caveat: ILIM_HIZ also sets the hardware input current limit from its voltage [SIB]. A 3.3 V logic drive would give the maximum ILIM, so a divider is needed.
- **Watchdog:** default **175 s**, adjustable via WDTMR_ADJ, with options of 140, 175 and 210 s (mapping UNVERIFIED); 00b disables it [DV]. Expiry resets ChargeCurrent to 0 A and BATFET should turn off [DV]. A write to ChargeVoltage or ChargeCurrent, or WD_RST, resets the timer [DV].
  - **This does not meet spec §3's ≤ ~5 s host-silence stop.** The fallback is the existing layer 1 (Teensy drops FC_CHARGE/REGEN), which needs a live Teensy.

## 9. I2C and rails
- **Address:** 7-bit 0x6B (family table covering BQ25710/13/20/23/73) [DV]. It is the only device on the bus, so there is no conflict.
- **Logic levels:** VIH/VIL and absolute maximum on SDA/SCL are UNVERIFIED. The family is typically 1.8/3.3 V compatible [SIB].
- **Back-powering:**
  - With VCHG-IN unpowered (the normal state), the Teensy's 3V3 pull-ups sit on an unpowered charger's SDA/SCL.
  - Whether those pins have ESD diodes to an internal rail that would clamp the bus or back-power VDDA is **UNVERIFIED**. Measure the bus-high level with the charger unpowered.
- **EVM pull-ups:** the EVM's EV2400 header likely has pull-ups to an on-board rail (UNVERIFIED). Remove them and use only RSDA/RSCL to Teensy 3V3.
- **Speed:** 100 kHz, per spec §3.

## 10. Status output and thermistor
- **Status:**
  - CHRG_OK: open-drain, "adapter present and valid", deglitched [DV].
  - PROCHOT: system alarm.
  - There is no Ag105-style charge-state pin (UNVERIFIED). Charge state comes from the I2C ChargerStatus register.
- **Wiring options:** CHRG_OK to pin 6 needs a 3.3 V pull-up (J1.29/30) or `INPUT_PULLUP` (spec §3). It would serve as "input valid", replacing STAT steady-LOW.
- **Thermistor:** NVDC controllers in this family have no JEITA TS pin, only a CMPIN/CMPOUT comparator [SIB]. On the BQ25773 this is UNVERIFIED.
  - J-NTC cannot be used directly. Wire it to the comparator with a bias divider on the carrier, or monitor it from a spare Teensy ADC.

## 11. Start-up latency (spec §5)
- **Required sequence after VCHG-IN appears:**
  1. VBUS exceeds 3.5 V.
  2. **CHRG_OK deglitch, 50 ms** [DV].
  3. One VBUS ADC conversion with the converter held off, then the VINDPM default is written [DV].
  4. Host I2C config (~2-3 ms).
  5. Converter soft start and the ChargeCurrent ramp (UNVERIFIED).
- **Total ≥ ~55-60 ms before current flows**, plus soft start [INF], then the board overhead of 12-20 ms.
- **Against the spec:**
  - The ≤ 30 ms target **FAILS** on the deglitch alone.
  - The ≤ 100 ms hard maximum is **probably met but UNVERIFIED** (soft start and ICO timing unknown).
  - Per [P37] M1, onset after ~75 ms captures only the back half of a 0.3-0.6 s regen burst.
- **The FC-charge mode is unaffected:** it is a steady state.

## 12. Hot-plug inrush and EVM input capacitance (spec §6)
- **EVM input capacitance:** **UNVERIFIED** (SLUUCY2/SLUUD24 BOM not read). An 8.2 A-input, 40 V, quasi-dual-phase EVM typically carries several 10 µF ceramics per phase and may carry a bulk polymer or electrolytic.
- **Budget:** spec §6 allows ≤ ~50 µF effective (hard bound ~80 µF) because of the single-sample OC_FC 1.4 A latch.
  - **Hazard:** any bulk electrolytic on the EVM input must be removed.
  - The ceramics must be counted at their DC-bias value at 16-21 V.
- **No switching during the 1.3-1.75 ms RT1987 ramp:** satisfied by the 50 ms deglitch.

## 13. Efficiency and thermal at 16 V → 8 V, 2.5 A
- **Operating point:** buck mode, about 21 W output. The EVM is designed for ~200 W, so conduction loss will be trivially low. Switching and gate-drive loss for two phases at light load dominate: GaN reduces them, silicon does not.
- **Efficiency figures:** none were read, at either 21 W or the ~2 W regen average. UNVERIFIED.
- **Light-load mode:** whether there is a PFM/burst mode and single-phase operation at light load is UNVERIFIED. The family offers phase shedding ("quasi dual phase") [DV title].
- **Thermal:** off-board mounting (§14) removes the LM1084 proximity issue (spec §8 Q11).

## 14. Size and mounting
- **EVM dimensions:** UNVERIFIED, but an 8 A dual-phase EVM is far larger than the 32 × 35 mm Ag105 outline.
- **It cannot sit on the footprint.** It needs a small carrier PCB in the 22 holes breaking out:
  - VIN+ / GND / VBAT+ / VBAT- / SDA / SCL / pin 5 / pin 6 / THERM
- **Leads:** short twisted pairs to the off-board EVM. Input-side leads add inductance, which interacts with the ceramic input capacitance at hot-plug (Death-5 class). Keep them short and consider a small damping network.
- **Bare IC on a carrier:** a custom ≤ 32 × 35 mm BQ25773 carrier is possible, but it needs 2 phases × (4 FETs + inductor), RAC, RSR and the BATFET. A 32 × 35 mm, 2-layer carrier for that is ambitious, and building it is effectively a mini re-spin.

## 15. Price, stock, lead time
- **TI.com:** the BQ25773EVM page shows "Order now / In stock", but price was not visible [DV snippet]. EmbeddedRelated lists it Active with 9 in stock.
- **EV2400:** sold separately, but not needed (the Teensy is the host).
- **Price:** UNVERIFIED. No price was found for any BQ2577x EVM or IC.

## 16. EVM mods required
1. Remove the EVM I2C pull-ups and any connection to its EV2400 header rail. Run SDA/SCL to the carrier (Teensy 18/19 with the board's 10 kΩ to 3V3).
2. Remove any bulk input capacitor. Keep total effective input capacitance (EVM + C-D8/C-D10) ≤ ~50 µF.
3. Swap C-D8/C-D10 from 25 V to ≥ 35 V parts (spec §2). No other input-side rework is needed thanks to the 33 V default ACOV.
4. Strap CELL_BATPRES for 2S and "battery present" (exact resistor UNVERIFIED).
5. If the ILIM_HIZ pin exists: drive it from pin 5 through a divider plus a pull-down, so that LOW gives Hi-Z (fail-safe) and HIGH gives the ILIM level for ≤ 1.0 A input.
6. Tie VSYS to BAT on the carrier, or leave SYS unloaded. Decide after reading how the BATFET is driven (UNVERIFIED).
7. Optionally increase RSR (e.g. to 10 mΩ) for usable 0.25-2.5 A resolution.
8. Pull CHRG_OK up to 3.3 V, then route it to pin 6.
9. NTC: bias network into CMPIN, or leave the NTC to the Teensy.
10. Firmware: replace the Ag105 code with a BQ2577x driver. The per-power-up config order is VINDPM → ChargeVoltage → IIN_HOST → WDTMR → ChargeCurrent. Port the `J` guards G1-G3 and the trip latch.

## 17. Showstoppers and risks
- **Showstoppers confirmed:** none, because no primary document could be read.
- **Showstoppers that are POTENTIAL (close before ranking):**
  - (a) Start-up latency: the 50 ms CHRG_OK deglitch alone fails the 30 ms regen target. The 100 ms hard maximum is UNVERIFIED.
  - (b) EVM input capacitance above the ~50-80 µF OC_FC budget.
  - (c) EVM ground continuity, until the schematic is read.
- **Risks:**
  - Gross over-design: a 16 A scale gives coarse low-current control and unknown light-load efficiency at the ~2 W regen average.
  - The EVM is physically large, so mounting is off-board.
  - VINDPM is a regulation loop, not a hard off.
  - The watchdog is 140-210 s, not ≤ 5 s.
  - The POR VINDPM default (VBUS - 1.28 V) is permissive toward the bus. Safety relies on the ChargeCurrent = 0 default plus write ordering.
  - Config is lost on each power cycle.
  - NVDC battery detection and termination through D-BT-SQ are unproven.
  - CV is sensed upstream of D-BT-SQ (-0.42 %).
  - No JEITA TS input.
  - The silicon EVM (SLUUCY2) and the GaN EVM (SLUUD24) differ: GaN gate-drive margins with a 3.3 V host are irrelevant, but the BOMs differ.
  - Price unknown.

## Fit score: 4 / 10
- **Strengths:**
  - The best OVP and absolute-maximum headroom of the I2C NVDC candidates (33 V default ACOV, 40 V operating). This closes spec open question 1.
  - Common-ground architecture.
  - Fine VINDPM resolution (20 mV [INF]) that covers both R3 thresholds at runtime.
  - Host-gated charging at POR.
- **Weaknesses:**
  - Regen cold-start latency.
  - Size and over-design.
  - Watchdog.
  - Every number short of the product titles is unread in a primary document.
- **Re-rank only after:**
  - reading SLUSEK7 (absolute maximum, VINDPM ceiling, ChargeCurrent LSB, ILIM_HIZ, BATFET, soft start);
  - reading SLUUCY2/SLUUD24 (schematic ground, input capacitors, pull-ups, size).
