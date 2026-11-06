# Round-2 dossier: TI BQ25713 on the BQ25713EVM-017, Path A replacement for the Ag105 (board rev 20260622)

Date: 2026-11-05. Supersedes the round-1 dossier
`docs/reviews/charger_eval_2026-11-05/dossier_TI_BQ25713__NVDC_buck_boost_charge_controller__external_FETs__P_ch_BATFET_.md`
for this part. It is written against the 2026-11-05 operator rulings: regen and FC charging are both hard requirements; Path A
must be shown fully feasible; R3 is replaced by "no circular loop, no runaway"; the always-powered charger architecture is accepted;
an MCU hardware watchdog is required future work.

## 0. Sources and evidence rules

Every number below comes from one of these primary documents, which were read in full (or the pages listed) on 2026-11-05. The
PDFs and pdftotext copies are in `scratchpad/charger_eval/datasheets/`. Per-page extracts and schematic renders are in `r2/bq713/`.

- **[DS]** TI SLUSD83C, *BQ25713, BQ25713B I2C NVDC Buck-Boost Battery Charge Controller*, June 2018, rev. May 2023 (85 pp.).
  Cited as "DS p.N" (PDF page = printed page) plus the section, table or figure.
  `BQ25713B_ds.pdf` is byte-identical to `BQ25713_ds.pdf` (same md5), since one datasheet covers both parts.
- **[UG]** TI SLUUBT8B, *BQ2571x Evaluation Module*, June 2018, rev. Oct 2018 (23 pp.): Table 1 I/O, Table 2 jumpers, Table 3
  ROC, Table 4 BOM (pp.10-12), Figure 11 schematic (p.17). The schematic was read from 450-900 dpi renders
  (`r2/bq713/in1.png`, `out1.png`, `out2.png`, `ilim1.png`, `low1.png`, `low2.png`, `low3.png`, `d5b.png`).
- **[RT]** Richtek RT1987 DS-00 (for D-BT-SQ VFWD and RON only).
- **[TIstore]** ti.com, fetched with plain curl on 2026-11-05 at 17:25 UTC:
  - the tool folder `https://www.ti.com/tool/BQ25713EVM-017` (`data-price` attribute);
  - the TI store inventory endpoint `https://www.ti.com/storeservices/cart/opninventory?opn=...`.
- Board facts are from the task brief, `docs/reviews/charger_eval_2026-11-05/spec.md` ([SPEC]), and the round-2 cross-cutting
  analyses `r2/loop_analysis.md` ([LOOP]) and `r2/regen_dynamics.md` ([REGEN]).
- Anything not found in a primary is marked **UNKNOWN** or **BENCH**, never filled from recollection.

## 1. Verdict

**FEASIBLE_WITH_CONDITIONS.** No hard requirement fails on the primaries. Proven from the documents:
- common ground (EVM net-tie NT1);
- a hardware converter-off pin (ILIM_HIZ < 0.4 V = Hi-Z);
- a host watchdog of 4-7 s;
- 2S/8.4 V CV at ±0.6 %;
- 64 mA-step charge current to 8.128 A;
- a VINDPM threshold settable to 19.008 V (18.44-19.39 V worst case) and to 13.5-15 V at runtime;
- no input re-qualification when V-MOT dips from regen back to bus level (no qualification threshold lies between 3.9 V and 25 V);
- 30 V absolute maximum with ACOV at ≥ 25 V;
- I2C telemetry for VBUS, IIN, ICHG and status.

Five things keep it from "proven":

1. **Regen capture is decided by three timing/retention facts the datasheet does not give** (bench gates B2, B3, B4). With
   the [LOOP] comparator gating ILIM_HIZ, the charger sits in Hi-Z for the whole cruise, because V-MOT ≈ VBUS < 1.067 × VBUS. It
   leaves Hi-Z only when a regen burst lifts V-MOT. The capture latency is therefore the **Hi-Z-exit** latency, plus any
   VBUS re-measurement the IC performs "right before the converter is enabled" (DS §9.3.3.2 p.25).
   - That re-measurement, if it happens on every Hi-Z exit, also **overwrites the host-written VINDPM** with "VBUS at no load −
     1.28 V". This is make-or-break for the always-powered regen architecture on this IC (section 5.4).
2. **The stock EVM is not fail-safe.**
   - EVM ILIM_control is pulled up to the EVM 3V3 (R26 383 kΩ), so a dead or high-Z Teensy leaves the converter **enabled**.
   - AUTO_WAKEUP_EN is 1 at POR, so the IC **charges 128 mA by itself** whenever its battery pin is below VSYSMIN. In this
     topology that is every input power-up, because VCHG starts at about 0 V behind D-BT-SQ.
   - Both are fixed by the hardware inhibit stage in section 7, which holds ILIM_HIZ LOW by default.
3. **The stock EVM input capacitance (94.5 µF nominal including a 33 µF tantalum) breaks the FC-mode inrush budget**
   (1.52 A predicted vs the 1.4 A OC_FC single-sample latch). Depopulate it (section 8).
4. **One EVM capacitor is under-rated for V-MOT.** C25 (0.47 µF, 16 V) sits on the VBUS-pin filter and must be replaced.
5. **The regen hard requirement also depends on the board, not the charger.**
   - The VESC stops regenerating at about 21.35 V within 19-47 ms ([REGEN]).
   - On the unmodified board, capture needs τ_warm ≤ 4 ms. M-R0/M-R3 decide whether that cut-off can be moved.
   - The BQ25713 cannot be judged a regen pass or fail until B4 is measured on the modified EVM in Hi-Z-exit mode.

Cold-start regen (charger unpowered between bursts) is **impossible** on this IC: the converter powers up 150 ms after VBUS
rises (DS §9.3.3 step 5, p.24; Figure 10-3 p.77 shows VSYS about 160 ms after VBUS at 40 ms/div). The always-powered architecture
is mandatory for this candidate.

## 2. Requirement matrix

| Req | Status | Evidence (primary citation) | Bench test that closes it |
|---|---|---|---|
| **H1** common ground, sense placement | PROVEN_DATASHEET | See 2.1 | B0: continuity J1-1 ↔ J5-1 ↔ J6-2 < 0.1 Ω |
| **H2** hard inhibit while powered | BENCH_GATE (mechanism proven, latency unknown) | See 2.2 | **B2** inhibit latency |
| **H3** fail-safe (a)-(d) | PROVEN_CALC with EVM mods (FAIL as shipped) | See 2.3 | B1 (TP22 < 0.4 V with the Teensy unpowered / in reset, ILIM stage fitted) |
| **H4** input-voltage threshold for always-powered regen | BENCH_GATE | See 2.4 | **B3** VINDPM retention, **B4** warm response, **B5** bus-level draw |
| **H5** FC-charging mode | PROVEN_DATASHEET | See 2.5 | B9 CV at the pack through D-BT-SQ |
| **H6** voltage ratings, ACOV | PROVEN_DATASHEET (with EVM mod C25) | See 2.6 | M-R2 (scope true V-MOT peak) |
| **H7** battery pin behind D-BT-SQ | PROVEN_DATASHEET | See 2.7 | B7 start into D-BT-SQ |
| **H8** inrush / hot-plug | PROVEN_CALC with EVM mod (FAIL as shipped) | See 2.8 | **B6** inrush plus SYS step vs OC_FC |
| **H9** I2C / logic / status pin | PROVEN_DATASHEET with EVM mods | See 2.9 | B8 back-feed / unpowered-pin leakage |
| **H10** thermal / efficiency / wiring / mechanical | PROVEN_DATASHEET (electrical); mechanical by off-board mount | See 2.10 | Fit check; scope the input ringing with the leads |
| **H11** availability | PROVEN_DATASHEET (TI store) | See 2.11 | – |
| **H12** telemetry | PROVEN_DATASHEET | See 2.12 | – |

### 2.1 H1: common ground and sense placement
- EVM J1-1, J5-1 and J6-2 are all PGND [UG Fig.11 p.17]. PGND ↔ GND are joined by the net-tie NT1 at U1's thermal pad (pin 33).
- RAC = R2, 10 mΩ, is high-side in VIN+ between the input node and Q1 (ACP/ACN).
- RSR = R8, 10 mΩ, sits in BAT+ between BATFET Q7 and J5-2 (SRP/SRN).
- Nothing is in the return path.
- DS pin table p.6-8: ACP/ACN input sense, SRP/SRN charge sense, SRN = battery voltage sense.

### 2.2 H2: hard inhibit while powered
Mechanisms:
- **(1) ILIM_HIZ pin < 0.4 V → Hi-Z; > 0.8 V exits** (DS p.7 pin table; p.18 VHIZ_HIGH/VHIZ_LO; §9.3.3.4 p.25).
  - Converter off (Q1-Q4 off); REGN stays on; registers kept.
  - The default is set by hardware (PTM_PINSEL = 0, DS p.40).
- **(2) EN_HIZ, REG0x35[7]**, POR 0 (DS p.44).
- **(3) CHRG_INHIBIT, REG0x00[0]**, POR 0 = enabled (DS p.39).
- **(4) ChargeCurrent = 0, REG0x03/02**, POR 0 except under auto-wakeup (DS p.56). The watchdog also sets it to 0 (p.30), and
  writing MaxChargeVoltage = 0 forces it to 0 (p.58).
- **(5) CELL_BATPRESZ < 15 % (battery removal)** disables charge and resets ChargeCurrent and MaxChargeVoltage. It latches
  until the host rewrites (DS p.6, p.18, p.56). EVM J2-4 CELL_control drives this.
- **(6) FORCE_LATCHOFF via the independent comparator** (REG0x30[3], DS p.41). On-die and register-configured, so not
  independent.

What each one stops:
- Only (1) and (2) turn the converter off.
- (3), (4) and (5) leave the NVDC converter regulating VSYS 160 mV above VBAT with the BATFET off (DS §9.4.1.1 p.31). That draws
  a few mA of PFM current from VBUS: 2.2 mA typ at 20 V in, buck, no load (DS p.13 IAC_SW_LIGHT_buck; no max given).
- In Hi-Z no DC path from VIN to BAT exists:
  - the Q1 body diode blocks VIN→SW1;
  - the BATFET body diode conducts BAT→SYS only (DS p.6 BATDRV; §9.3.10.2 p.30).
- Supplement mode and LEARN mode are discharge paths. The only autonomous charge-into-battery path is **auto-wakeup, 128 mA**
  (see H3), and Hi-Z blocks it.

Status:
- **Response time: not specified anywhere in SLUSD83C** (no ILIM_HIZ deglitch or Hi-Z entry/exit timing in §8.5/§8.6).
- Soft start "during charge enable" is 64 mA per 8 µs (DS p.17). That is a ramp-up figure, not an inhibit latency.
- The CHRG_INHIBIT and EN_HIZ registers need I2C, so they do not meet [LOOP] C1.
- The ILIM_HIZ pin meets C1.

### 2.3 H3: fail-safe
**(a) Teensy in reset / high-Z.**
- Layer 1 holds independently of the charger: the RT1987 EN 10 kΩ pull-downs open D-BC-FC and D-BC-RG, so the charger is
  unpowered.
- On the charger alone, the **stock EVM fails**. J2-1 ILIM_control is pulled up to the EVM 3V3 by R26 383 kΩ, and D5 (BAT54H)
  pulls ILIM_HIZ low only when ILIM_control is LOW [UG Fig.11; Table 2 "JP6 on: ILIM_HIZ LOW"]. A floating input therefore means
  ENABLED at the 3.0 A pre-bias (TP22 = 2.2 V, UG §2.4.1 p.9).
- With the section 7 stage (ILIM_HIZ held LOW by an NMOS whose gate is pulled up from the EVM 3V3, and released only by Teensy
  pin 5 HIGH AND comparator permit HIGH), a dead, reset or high-Z Teensy means Hi-Z.
- Timing: the EVM 3V3 comes up within ms of VBUS through D3/R38/U2. VDDA, which supplies the ILIM pre-bias through R19, appears
  only 50 ms after VBUS > VVBUS_CONVEN (DS §9.3.3 step 1 p.24). So the hold-down is established before the pre-bias even exists,
  and well before the 150 ms converter start.

**(b) Teensy hung with pins latched.**
- The charger watchdog resets ChargeCurrent to 0 if neither ChargeCurrent nor MaxChargeVoltage is written within WDTMR.
  - WDTMR is 175 s at POR (DS p.37, Table 9-5). The 5 s setting is 4/5.5/7 s min/typ/max (DS p.19 tWDI).
  - On expiry, every other register is kept and charging is suspended until a rewrite (DS §9.3.10.1 p.30).
- So a hung MCU bounds charging at the last setting to ≤ 7 s, after it last wrote.
- Firmware rules:
  - write WDTMR = 01 on every power-up, with readback;
  - **never write WDTMR = 00**, because that also *resumes* charging (DS p.30);
  - service the watchdog only from the main loop, after the interlock checks, never from an ISR.
- During those ≤ 7 s, only the hardware layers (comparator permit, FC-window permit) protect. Hence the **MCU hardware watchdog**
  (operator ruling 5, [LOOP] §10) is required future work. With RTWDOG at 100 ms, the hang window shrinks to 100 ms, after which
  the pins go high-Z and case (a) applies.

**(c) I2C dead or stuck.**
- Registers hold; charging continues at the last setting until the 4-7 s watchdog.
- The slave releases the bus after a clock-low timeout of 25-35 ms (DS p.19 ttimeout).
- The ILIM_HIZ hardware inhibit is independent of I2C.

**(d) POR defaults.**

| Register | POR value | Source |
|---|---|---|
| ChargeCurrent | 0 "when auto wakeup is not active" | DS p.56 |
| AUTO_WAKEUP_EN | **1**: if VBAT < VSYSMIN, 128 mA for up to 30 min, cleared once VBAT > VSYSMIN | DS p.41 |
| VSYSMIN (2S) | 6.144 V | DS p.36, p.60 |
| CHRG_INHIBIT | 0 (enabled) | DS p.39 |
| IIN_HOST | 3.25 A | DS p.62, reset 4100h |
| VINDPM | VBUS at no load − 1.28 V | DS p.64 |
| MaxChargeVoltage | 8.400 V from the CELL strap | DS p.58 |
| EN_LDO | 1 (pre-charge clamp 384 mA) | DS p.38 |
| EN_OTG | 0 | DS p.44 |

- Consequence: out of reset, the IC **does charge by itself**, at 128 mA, as long as SRN (= VCHG) < 6.144 V.
- Behind D-BT-SQ, VCHG is about 0 V at each input power-up, so auto-wakeup charges the VCHG node to about VSYSMIN and then clears.
  The pack (≥ 7.4 V) stays blocked by D-BT-SQ.
- Only a pack below about 6.1 V would actually receive 128 mA, for ≤ 30 min. That is bounded and not a runaway, but it violates
  [LOOP] C3. Hi-Z by default (the section 7 stage) prevents it, and firmware writes AUTO_WAKEUP_EN = 0 before the first Hi-Z
  release. This mirrors TI's own "configure in Hi-Z" sequence (DS §9.6.5.1 p.61).
- **Pull resistors needed for "dead MCU = no charging":**
  - a pull-up on the Q_a gate to the EVM 3V3 (100 kΩ);
  - a pull-down on the Q_b gate / pin 5 (47 kΩ);
  - remove R26, or leave ILIM_control unconnected and do not use D5;
  - the comparator's open-drain output into the Q_b gate.

### 2.4 H4: input-voltage threshold (always-powered regen)
**Register.** InputVoltage REG0x0B/0A: 8-bit, 64 mV LSB, 3.2 V offset, range 3.2-19.52 V (DS p.36 Table 9-4; p.64). It is a
two-byte write, LSB then MSB, and an MSB-only write is ignored (DS §9.5.1.8 p.35).
- Regen setting: code 247 = **19.008 V**. FC setting: code 161 = 13.504 V, or code 184 = 14.976 V.
- Runtime programmable: "The host can always program the input current and voltage limit after the charger being powered up"
  (DS §9.3.3.2 p.25).

**Accuracy** (DS p.12 VDPM_REG_ACC):
- −3 %/+2 % at 18.688 V, so 19.008 V gives **18.44-19.39 V**;
- −4 %/+2.5 % at 10.88 V;
- ±5 % at 4.48 V.
- FC 13.504 V, taking the −4 %/+2.5 % band as conservative, gives 12.96-13.84 V. That stays above the firmware UV backoff of
  12.8 V.

**Placement against the board.**
- 18.44 V minimum sits:
  - 0.94 V above the 17.5 V firmware OV;
  - 1.24 V above the 17.2 V measured overshoot;
  - only 0.14 V above the TPS61288 OVP minimum of 18.3 V.
- 19.39 V maximum sits 2.0 V below the 21.4 V clamp.
- The register ceiling of 19.52 V means a threshold above the boost's 19.5 V OVP maximum is unavailable. The failed-FB boost
  case rests on the [LOOP] V-MOT/VBUS comparator.

**Reset hazard.**
- The value is re-derived at every POR (DS p.64 reset "VBUS-1.28V").
- RESET_VINDPM (REG0x35[5]) re-measures on command, and "converter is disabled to measure" (DS p.44).
- RESET_REG keeps VINDPM (DS p.44).
- **The datasheet does not say whether a Hi-Z exit, an ACOV recovery or a watchdog expiry re-runs the measurement.** TI's own
  sequence starts the converter at Hi-Z exit (DS p.61), and the measurement is taken "right before the converter is enabled"
  (DS p.25). A per-exit re-measure is therefore plausible. **B3 decides it.**

**Draw at or under the threshold.**
- **No figure in SLUSD83C** for:
  - input current with VBUS below VINDPM and charge enabled;
  - Hi-Z quiescent from VBUS (the EC quiescent table, DS p.13, covers battery-only operation).
- The nearest figure is the PFM no-load input current of 2.2 mA typ (20 V in, 12.6 V out, DS p.13). **BENCH B5.**

**Warm response.**
- No loop bandwidth, VINDPM transient or Hi-Z-exit timing is given; DS §10.2.3 pp.77-80 has no such curve.
- The charge-enable soft start is 64 mA/8 µs, which is 0.31 ms to 2.5 A (DS p.17), but it is not stated to apply to a VINDPM
  release or a Hi-Z exit. **BENCH B4** against [REGEN]'s τ_warm ≤ 4 ms.

**No re-qualification on dips.**
- The only VBUS qualification thresholds are:
  - UVLO 2.40/2.55 V;
  - CONVEN 3.2-3.9 V rising / 2.9-3.5 V falling;
  - ACOV ≥ 25 V (DS p.14-15).
- A V-MOT swing between 16 V and 21.4 V crosses none of them. CHRG_OK stays HIGH, there is no 50 ms deglitch and no 150 ms
  power-up, and registers are kept (PROVEN_DATASHEET).
- In the comparator-gated design, the relevant transition is the Hi-Z exit, whose timing is unknown.

### 2.5 H5: FC charging
- Buck mode from 15.9 V to 8.4 V.
- ChargeCurrent: 64 mA LSB, 64 mA-8.128 A (DS p.35, p.56). Code 39 (REG 0x09C0) = 2.496 A.
  - Accuracy −4 %/+3 % at 2048 mA and −3 %/+2 % at 4096 mA, 0-85 °C (DS p.11), so about 2.40-2.57 A at 2.5 A.
- CV: MaxChargeVoltage 8 mV LSB; the 2S default is 8.400 V from the strap (DS p.58).
  - Accuracy ±0.6 % at 8.4 V, 0-85 °C (DS p.11), so 8.350-8.450 V at SRN.
- **Termination is host-controlled** (DS §9.4.1.2 p.31): there is no autonomous termination or recharge. Firmware must taper-detect
  (ADC ICHG plus board V_batt) and set CHRG_INHIBIT or ChargeCurrent = 0.
- The FC-mode VINDPM (13.5-15 V) also acts as an FC-sag guard: if the bus sags, the charger backs off.
- The FC input budget is the board's limit, not the IC's:
  - 2.5 A × 8.4 V / 0.93 / 15.9 V ≈ 1.42 A in, which is above the OC_FC single-sample latch.
  - FC mode therefore runs input-limited at IIN_HOST about 0.7 A, which is about 1.2 A charge.
  - A hardware ILIM ceiling backs this up (section 7).

### 2.6 H6: voltage ratings
- VBUS/ACP/ACN/SRP/SRN/VSYS absolute maximum −0.3 to 30 V; SW 30 V (DS p.9 §8.1).
- Recommended VBUS 0-24 V (DS p.9 §8.3). EC VINPUT_OP 3.5-26 V (DS p.10) conflicts with that; use 24 V.
- **ACOV:** rising 25/26/27 V, falling 23.5/24.5/25 V; 100 µs rising deglitch to stop, 1 ms falling deglitch to restart (DS p.15).
  - At ACOV: converter disabled, CHRG_OK low (DS §9.3.10.2 p.30).
  - **ChargeCurrent is NOT reset by ACOV** (DS p.56), so charging resumes by itself 1 ms after V-MOT falls back.
  - Round-1's load-drop hazard (charger load removed at the peak) stands.
- Margins:
  - clamp 21.4 V → 2.6 V to the recommended maximum, 3.6 V to ACOV minimum, 8.6 V to the absolute maximum;
  - design clamp 22.13 V → 1.9 V to the recommended maximum.
- EVM parts:
  - Q1-Q4 CSD17551Q3A, 30 V; Q5/Q6 DMP3035SFG, −30 V;
  - input MLCCs 25 V X5R (GRM21BR61E106KA73L); C53 tantalum 35 V;
  - Z1 SMAJ26CA (26 V bidirectional TVS) on the Q5/Q6 common node [UG BOM p.11-12; Fig.11];
  - **C25 0.47 µF 16 V X7R** on the VBUS-pin filter (with R13 1.0 Ω, [UG BOM p.10; Fig.11]) is **below the 19-21.4 V operating
    level**. Replace it with ≥ 35 V.
- Board C-D8/C-D10 (25 V) swap per [SPEC].

### 2.7 H7: battery pin through D-BT-SQ
- **Battery detection** is the CELL_BATPRESZ divider only (DS p.6, p.18). With the EVM 2S strap (JP2 on, JP3/JP4 off, CELL
  2.7 V, UG Table 2 p.3), the battery reads "present" whatever the voltage on SRN. There is no electrical detection, so nothing
  refuses to start.
- **About 0 V on SRN at power-up:**
  - SRN common-mode range 2.5-18 V (DS p.13); VBAT UVLO 2.40/2.55 V (DS p.14).
  - SRN < 2.4 V selects the reduced system-short OCP thresholds (DS p.16).
  - VBAT < VSYSMIN gives LDO/pre-charge, 384 mA clamp for 2S (DS p.11 ICLAMP; §9.6.3.1 p.57), with SYS regulated at VSYSMIN
    (6.144 V).
  - Auto-wakeup 128 mA applies at POR (H3d).
- **The VSYS short hiccup** (VSYS < 2.4 V, 2 ms deglitch, 500 ms off, 7 failures in 90 s = latch-off, DS §9.3.10.7 p.31) does not
  trip, because SYS reaches 2.4 V in about 0.1 ms at the input ceiling (B6/B7).
- **Charging sequence once enabled:**
  1. Pre-charge raises VCHG (C-D11 10 µF + EVM C26 10 µF) to VSYSMIN.
  2. Fast charge with the BATFET fully on; CC raises VCHG to VBT + 35 mV.
  3. D-BT-SQ conducts (VFWD 35 mV typ, RON 20 mΩ [RT]; at 2.5 A, I × RON = 50 mV, so it is fully on).
  4. The RT1987 auto-restarts without soft start ([SPEC] 3.4); the charger's CC loop bounds the step.
- **CV is regulated at SRN = VCHG.** The pack ends at VCHG − max(35 mV, I × 20 mΩ), which is about 8.315-8.415 V at taper.
- **BATOVP** is 102.5-105 % of VREG rising (8.61-8.82 V) with a 20 ms deglitch (DS p.15-16). It guards the D-BT-SQ
  open-mid-charge overshoot.
- **D-BT-SQ must NOT be bridged:**
  - With D-BT-SQ, OTG/VAP and supplement cannot draw the pack (the BAT pin only sees capacitors).
  - The pack cannot drive VCHG-IN through the converter.
  - The pack does not feed the EVM 3V3 LDO through D2, or the battery-only quiescent of 22-45 µA LPM / 880-1270 µA performance
    mode (DS p.13).
  - Bridging would re-enable an OTG path (EN_OTG pin + REG0x35[4] + REG0x34[5] + VBUS < CONVENZ, DS §9.3.4 p.25) and lose
    the hard battery-side disconnect.

### 2.8 H8: inrush / hot-plug
**EVM input node** [UG BOM pp.10-12; Fig.11]:
- C53 33 µF/35 V tantalum T521D;
- C3, C4, C23, C24, C44, C45, 6 × 10 µF/25 V X5R 0805;
- C18 1 µF behind R3 ∥ R4 (3.9 Ω each), the J1 snubber;
- C25 0.47 µF;
- C42, C43, C54 DNP;
- **94.5 µF nominal.**

**Calculation** (nominal capacitance is the worst case for inrush; DC-bias derating only lowers it):
- (94.5 + 20 board) µF × 12 mA/µF (RT1987 slew 12.0 V/ms, [SPEC] §6) = **1.37 A**.
- Adding I_aux 0.15 A gives **1.52 A, over the 1.4 A OC_FC latch: FAIL as shipped.**

**Mod:**
- depopulate C53 and three of the six 10 µF MLCCs (keep C3, C4 and one more, nearest Q1);
- 31.5 + 20 = 51.5 µF → 0.62 A + 0.15 = **0.77 A**, inside the ≤ 1.0 A budget;
- TI's minimum effective input capacitance is 4 µF even at 65 W (DS Table 10-1 p.75).

**Charger switching during the ramp: none.** CHRG_OK/LDO come up 50 ms after CONVEN, and the converter 150 ms after (DS p.24).
That is far beyond the 1.3-1.75 ms ramp.

**Second step: converter start / Hi-Z exit charging the SYS capacitors.**
- SYS capacitors: C5-C10, C21 (7 × 10 µF) + C48, C49 (33 µF Ta) + C41 ≈ 136 µF, plus the VCHG capacitors.
- That is ½CV² ≈ 4.8 mJ to 8.4 V, drawn at the input-current ceiling. Without a hardware ceiling, that ceiling is the
  **3.25 A IIN default** (DS p.62).
- Required: a hardware ILIM pin ceiling (section 7), plus IIN_HOST written before the first Hi-Z release.
- Do not depopulate the SYS capacitors: TI requires ≥ 50 µF effective on VSYS for loop stability (DS Table 10-2 p.76).
- Overshoot of the input-current loop is unspecified (**B6**).

**Death-5 class:** none, provided C53 is removed. No electrolytic or polymer bulk remains.

### 2.9 H9: I2C, logic and status pin
**Address and identity:**
- 7-bit **0x6B** (D6h) for BQ25713; 0x6A for BQ25713B (DS Table 6 p.5; §9.5 p.32).
- The EVM-017 fits **BQ25713RSNR** [UG BOM p.12].
- Firmware identity check: ManufacturerID 0x2E = 0x40, DeviceID 0x2F = **0x88** (DS p.72).
- There is no other device on the Teensy bus.

**Logic levels:** VIL 0.4 V, VIH 1.3 V (DS p.18), so 3.3 V-compatible. SDA/SCL recommended maximum 6.5 V, absolute maximum 7 V
(DS p.9). Open-drain leakage ±1 µA at 7 V (DS p.18).

**Unpowered-pin clamp behaviour: not specified** (B8).

**EVM 3V3 back-feed:**
- The EVM 3V3 is U2 LM3480-3.3, fed through JP8 / R38 10 Ω from D3 (VBUS) OR D2 (BAT), both BAT54H [UG Fig.11]. It is dead when
  the charger is unpowered.
- The EVM I2C pull-ups R32 and R35 (10 kΩ to EVM 3V3, J3) would back-feed that dead rail from the Teensy pull-ups and idle the bus
  at about mid-rail. **Remove R32 and R35.** Leave J3-4 (3V3 via R31) unconnected and keep JP8 fitted: the ILIM stage and the
  CHRG_OK pull-up use the EVM 3V3.

**Status pin (pin 6):**
- J2-2 CHRG_OK: open drain, pulled up by R33 10 kΩ to EVM 3V3, so 0-3.3 V at the Teensy.
- Meaning: input valid, below ACOV, no fault (DS §9.3.3.1 p.24); 50 ms rising deglitch (DS p.7). It does not mean "charging".
- An unpowered charger reads LOW, which is safe.
- Charge state comes from ChargerStatus REG0x21/20 (DS p.52-53).

**Pin 5:** see section 7. The schematic polarity of ILIM_control (LOW = Hi-Z) contradicts UG Table 1 ("logic high to pull the ILIM
pin down"), so the stage drives ILIM_HIZ directly at TP22.

### 2.10 H10: thermal, efficiency, wiring, mechanical
**Efficiency at 7.4 V out, 2.5 A, read from DS Fig. 8-6 / 8-7 pp.20-21 (figure reading, ±0.5 pt):**
- VIN 12 V: about 94.9 %;
- VIN 20 V: about 92.4 %;
- so about 93.5 % at 16 V and about 92.5 % at 19-21 V.

**Loss at 21 W out:** about 1.5 W in FC mode and about 1.7 W in regen. Add RSR 62 mW and RAC ≈ 20 mW (I²R).

**Light load (regen tail, 50 mA):** about 79 % at 20 V in, 8.4 V out (Fig. 8-3).

**Thermal:**
- RθJA 37.2 °C/W (DS p.10); TSHUT 155 °C (DS p.16).
- The EVM is rated 8 A out / 3 A in (UG Table 3 p.4), so 2.5 A is about 30 % of the rated output.
- The inductor L1 is 8.5 A, 20.3 mΩ (UG BOM).

**Mechanical:**
- SLUUBT8B gives no board dimensions.
- The 22-pin Ag105 footprint (32 × 34.8 mm, [SPEC] §7) cannot host it. Mount it off-board.

**Wiring:**
- leads: ≤ 1.5 A on the input pair, 2.5 A on the battery pair;
- twisted pairs, as short as possible;
- the J1 RC snubber (R3/R4/C18) is retained to damp lead-inductance ringing against the ceramic input capacitors;
- scope it at the RT1987 step.

### 2.11 H11: availability (2026-11-05, 17:25 UTC)
- TI store: **BQ25713EVM-017 USD 156.45, inventory 38** [TIstore].
- IC inventory: BQ25713RSNT 3441; BQ25713RSNR 0; BQ25713BRSNR 238 046 [TIstore].
- EV2400 USD 208.95 is not needed, because the Teensy is the host.
- Lead time is not published for in-stock units.
- **Mouser and Farnell could not be checked**:
  - www.mouser.com fails DNS (outside the allowed domains) and uk.farnell.com/www.farnell.com reset or time out;
  - www.mouser.com and www.farnell.com must be allowed in the session network settings, or checked by hand.

### 2.12 H12: telemetry
**ADC registers** (DS Table 9-4 p.35-36; §9.6.9-9.6.12 pp.68-71):

| Register | Field | LSB | Range |
|---|---|---|---|
| 0x27 | VBUS | 64 mV | 3.2-19.52 V; saturates above 19.52 V, so regen peaks are unreadable |
| 0x29 | ICHG | 64 mA | 8.128 A full scale |
| 0x28 | IDCHG | 256 mA | – |
| 0x2B | IIN | 50 mA | 6.4 A full scale at 10 mΩ |
| 0x2D / 0x2C | VSYS / VBAT | 64 mV | – |

**Conversion:** about 10 ms typical per set (no maximum). Continuous mode updates only every **1 s** (DS p.50). 50 Hz polling must
therefore use one-shot ADC_START every 20 ms.

**Status:** ChargerStatus REG0x21/20 (DS p.52-53):
- AC_STAT, IN_VINDPM, IN_IINDPM, IN_FCHRG, IN_PCHRG;
- latched faults ACOV, BATOC, ACOC, SYSOVP, SYS_SHORT, Latchoff (cleared by a host read; SYSOVP and SYS_SHORT by writing 0).

**IIN_DPM readback:** REG0x25 (DS p.63).

**Analog fast paths:** IADPT (20/40 × V_RAC) and IBAT (8/16 × V_RSR) pins (DS p.7, p.13-14). They are usable for a sub-ms J-guard
only with a spare Teensy ADC pin and a CSV change.

**Coarse resolution** (64 mA ICHG vs a ~0.2 A regen average) is the EMS limitation ([REGEN]).

**J-guard port:**
- G1/G2 keep using the board INA253/ADCs;
- G3 maps to the latched ChargerStatus faults plus SYSOVP/SYS_SHORT;
- IN_VINDPM = 1 at bus level is a positive "parked below threshold" check for the [LOOP] firmware interlock.

## 3. Register map excerpt (firmware driver)

| Reg (LSB/MSB) | Name | Reset | Fields that matter | Required setting |
|---|---|---|---|---|
| 00/01 | ChargeOption0 | E70Eh | 01[7] EN_LWPWR = 1; 01[6:5] WDTMR_ADJ = 11 (175 s); 01[1] PWM_FREQ = 1 (800 kHz, matches L1 2.2 µH); 00[2] EN_LDO = 1; 00[1] EN_IDPM = 1; 00[0] CHRG_INHIBIT = 0 | EN_LWPWR = 0; **WDTMR = 01 (5 s)**; keep 800 kHz; CHRG_INHIBIT = 1 until armed (p.37-39) |
| 02/03 | ChargeCurrent | 0 | bits 12:6, 64 mA LSB | 0 until armed; FC about 1.2 A (code 19); regen 2.496 A (code 39) **last** in sequence (p.56) |
| 04/05 | MaxChargeVoltage | 8400 mV (2S strap) | bits 14:3, 8 mV | Write 0x20D0 (8.400 V) explicitly, with readback; never write 0 (forces the default and ICHG = 0) (p.58) |
| 0A/0B | InputVoltage (VINDPM) | VBUS − 1.28 V | bits 13:6, 64 mV, +3.2 V offset | Regen code 247 (19.008 V); FC code 161 (13.504 V); readback after every Hi-Z exit (B3) (p.64) |
| 0C/0D | MinSystemVoltage | 6.144 V (2S) | 256 mV | leave (p.60) |
| 0E/0F | IIN_HOST | 3.25 A (4100h) | 50 mA LSB | FC 0.70 A; regen ≤ 1.25 A; the lower of the register and the ILIM pin wins (p.61-62) |
| 30/31 | ChargeOption1 | 0211h | 30[0] AUTO_WAKEUP_EN = 1; 30[3] FORCE_LATCHOFF; 30[7:4] comparator; 31[3:2] RAC/RSR = 10 mΩ | **AUTO_WAKEUP_EN = 0** (p.40-41) |
| 32/33 | ChargeOption2 | 02B7h | 32[7] EN_EXTILIM = 1 (ILIM pin active); 32[3] EN_ACOC = 0 | keep EN_EXTILIM = 1 (hardware ceiling); optionally EN_ACOC = 1 (p.42-43) |
| 34/35 | ChargeOption3 | 0030h | 35[7] EN_HIZ; 35[6] RESET_REG; 35[5] RESET_VINDPM; 35[4] EN_OTG = 0; 34[1] BATFETOFF_HIZ = 0 | EN_OTG = 0; optionally BATFETOFF_HIZ = 1 (p.44-45) |
| 3A/3B | ADCOption | 2000h | 3B[7] continuous (1 s) / one-shot; 3B[6] ADC_START; 3A enables | one-shot every 20 ms, with VBUS, IIN, ICHG, VBAT enabled (p.50-51) |
| 20/21 | ChargerStatus | 0 | listed in 2.12 | poll at 50 Hz (p.52-53) |
| 2E / 2F | ManufacturerID / DeviceID | 40h / 88h | – | identity check before any write (p.72) |

**Write order on every CHRG_OK rise or POR, with the charger held in Hi-Z by hardware:**
1. Identity check.
2. ChargeOption0 (WDTMR 5 s, EN_LWPWR 0, CHRG_INHIBIT 1).
3. AUTO_WAKEUP_EN 0.
4. MaxChargeVoltage 8.400 V, with readback.
5. IIN_HOST, with readback.
6. VINDPM, with readback.
7. EN_OTG 0.
8. Release Hi-Z (pin 5 HIGH, permit-gated).
9. **Re-read VINDPM** (B3 hazard). Rewrite if it changed.
10. CHRG_INHIBIT 0.
11. ChargeCurrent **last**.

All 16-bit writes are LSB then MSB (DS p.35).

## 4. Timing in words

**Cold power-up** (VCHG-IN switched on by D-BC-FC or D-BC-RG):
- t = 0: the RT1987 begins its 12 V/ms ramp; VBUS crosses 3.5 V at about 0.3 ms and 16 V at about 1.3 ms.
- t ≈ 50 ms: REGN/VDDA on, CHRG_OK HIGH; registers at POR values; I2C usable; the EVM 3V3 has been up since about 1 ms.
- t ≈ 150 ms: the IC would start the converter, but the hardware stage holds ILIM_HIZ < 0.4 V, so it stays in Hi-Z.
- t ≈ 150-160 ms: firmware writes the configuration (about 3 ms at 100 kHz) and releases Hi-Z.
- If B3 shows a re-measure: the converter starts after an unspecified VBUS no-load measurement, and VINDPM must be re-written.
- ChargeCurrent soft-starts at 64 mA/8 µs (DS p.17).

**Warm regen burst** (charger powered through REGEN, in Hi-Z, comparator permit LOW):
- V-MOT rises at about 0.11-0.28 V/ms ([REGEN]).
- About 17.07 V: the comparator crosses 1.067 × VBUS, the permit goes HIGH, and ILIM_HIZ is released.
- [unknown Hi-Z-exit latency, B4b] + [possible VINDPM re-measure, B3].
- The converter regulates V-MOT at VINDPM 19.0 V and charges at ≤ 2.5 A.
- V-MOT must not reach the VESC cut-off at about 21.35 V. The window is 15-38 ms from the comparator trip to the cut-off, and
  [REGEN] puts the budget at τ_warm ≤ 4 ms at 0.97 mF.
- Burst end: V-MOT falls; the permit drops at about 16.77 V (hysteresis 0.30 V) and Hi-Z is entered within the unknown entry
  latency (B2, must be ≤ 290 µs at 1.5 A [LOOP]). D-MT-EN can only conduct once V-MOT < VBUS.

**FC window:**
- BT_BUS and REGEN off; FC_CHARGE on (assertFcChargeEnable).
- VCHG-IN ramps; the charger is already configured if it stayed powered, or goes through cold power-up as above.
- VINDPM 13.5 V; IIN_HOST 0.7 A; ChargeCurrent about 1.2 A.
- [LOOP] FC-window permit = FC_CHARGE HIGH ∧ BT_BUS LOW ∧ REGEN LOW ∧ I_bt < 0.2 A.

## 5. EVM and board modifications (designators)

1. **2S strap:** JP2 on, JP3 and JP4 off (CELL about 2.7 V; UG Table 2). Leave JP4 off, since JP4 forces battery removal.
2. **Input path:** JP1 on, JP7 top (factory). The board RT1987s switch; Q5/Q6 are bypassed.
3. **Input capacitance:** remove **C53** (33 µF Ta) and three of C23/C24/C44/C45. Keep C3, C4 and one more nearest Q1, plus the C18
   snubber.
4. **Replace C25** (0.47 µF 16 V) with 0.47 µF ≥ 35 V X7R 0805.
5. **I2C pull-ups:** remove **R32, R35**. Leave J3-4 unconnected; keep JP8.
6. **Hardware inhibit stage** (replaces the ILIM_control use; see section 7). Remove R26 or leave J2-1 open. JP5 on; JP6 off.
7. **ILIM ceiling:** change **R27 220 kΩ → 127 kΩ.** That gives TP22 1.42-1.57 V over REGN 5.7-6.3 V (DS p.12), i.e.
   1.05-1.42 A (±0.2 A pin accuracy, DS p.12). It is a regen-capable ceiling of 1.235 A nominal, which is about 2.57 A charge at
   19 V. The FC-mode limit then comes from IIN_HOST 0.70 A.
   - Optional: a mode-switched second resistor (604 kΩ ∥ R27 → 105 kΩ, 0.73 A nominal), gated by an NMOS from the FC_CHARGE
     net. That makes the FC ceiling hardware too.
8. **CHRG_OK** (J2-2) → Teensy pin 6 through the existing R33 10 kΩ to EVM 3V3. Keep `pinMode(INPUT)` with no Teensy pull-up.
9. **J6 SYS unloaded.** Do not depopulate the SYS capacitors (stability, DS Table 10-2).
10. **Board:** C-D8/C-D10 → ≥ 35 V parts [SPEC].
11. **Board:** do not bridge D-BT-SQ.
12. **[LOOP] hardware:** the V-MOT/VBUS comparator (TLV3012B) and the FC-window permit, ANDed into the inhibit stage.
13. **CSV first:**
    - pin 5 meaning "CHG_ENABLE (HIGH = released)", which is the same polarity as the current `MPPT_DISABLE` HIGH = release;
    - pin 6 = CHRG_OK;
    - then a never-rotated CLAUDE.md bodge record.

## 6. Firmware impact specific to this IC
- New 0x6B driver with the write order in section 3.
- Re-configure on every CHRG_OK rise, plus a periodic readback of VINDPM, IIN_HOST, MaxChargeVoltage and WDTMR.
- Service the 5 s watchdog from the main loop only.
- Host-side termination.
- One-shot ADC at 50 Hz; status poll.
- Port G1-G3 and the trip latch.
- An IN_VINDPM / AC_STAT plausibility check in the 1 kHz monitor.
- **MCU hardware watchdog (RTWDOG 100 ms + WDOG1 1 s, [LOOP] §10) is REQUIRED FUTURE WORK** if Path A is pursued (operator
  ruling 5). The charger's own 4-7 s watchdog is not a substitute for the hardware layers during a hang.

## 7. Hardware inhibit stage (ILIM_HIZ, fail-safe)
- **Q_a** (2N7002-class): drain on TP22 (ILIM_HIZ); source on GND; gate pulled up by 100 kΩ to the EVM 3V3.
- **Q_b**: drain on the Q_a gate; source on GND; gate driven by Teensy pin 5 through 1 kΩ, with a 47 kΩ pull-down. The [LOOP]
  comparator's open-drain output and the FC-window permit output also connect to the Q_b gate.

Behaviour:
- Charger enabled only when pin 5 is HIGH AND every permit is released. Q_b on, Q_a off, so the R19/R27 divider sets ILIM.
- Any of the following gives Q_b off → Q_a on → ILIM_HIZ ≈ 0 V → Hi-Z:
  - Teensy unpowered, in reset or high-Z;
  - pin 5 LOW;
  - a permit LOW.
- An unpowered charger is harmless.

Requirements:
- The Q_a VGS(th) must be < 2.5 V at the EVM 3V3, and the Q_a on-state must hold ILIM_HIZ < 0.4 V against the R19 current
  (≈ 16 µA): trivially met. The 2N7002 datasheet was not read (MISSING); verify in B1.
- Do not use J2-1 / D5 for this. The D5 forward drop plus a pull-down leaves no margin to 0.4 V, and the schematic and UG Table 1
  disagree on polarity.

## 8. Bench gates (BQ25713-specific; [LOOP] M-numbers in brackets)
- **B0** Ground continuity; strap check, CELL 2.7 V.
- **B1** TP22 < 0.3 V with the Teensy unpowered, in reset, and with pin 5 LOW; with pin 5 HIGH and permits released, TP22 at the
  design ILIM voltage. Also confirm the UG Table 1 vs schematic ILIM_control polarity.
- **B2 [M2]** ILIM_HIZ falling edge → input current < 10 mA. Must be ≤ 290 µs at a 1.5 A input (scales 1/I).
- **B3 [M2]** Write VINDPM = 19.008 V, then read it back after each of: an ILIM_HIZ Hi-Z cycle, an EN_HIZ cycle, ACOV
  (26.5 V step), watchdog expiry, and a VBUS dip to 15 V. **Any change = the regen architecture fails on this IC** unless firmware
  can re-write it inside the burst.
- **B4 [M-R4]**:
  - (a) VINDPM step: input from 18.5 V to 20 V, stiff, charger enabled;
  - (b) **Hi-Z exit with the input at 20 V**;
  - for each, the time to 63 % / 90 % of 2.5 A battery current;
  - pass: τ ≤ 4 ms (10-90 % ≤ 9 ms), or the relaxed limit if M-R1/M-R0 change the budget.
- **B5** Stiff 16.0 / 17.5 / 18.3 V source; VINDPM 19.008 V; ChargeCurrent 2.496 A; not Hi-Z. Measure the input current (target
  < 10 mA, ICHG ADC = 0, IN_VINDPM = 1). Also measure the Hi-Z quiescent from VBUS.
- **B6** On the modified EVM with the board RT1987 ramp in FC mode: peak bus-side current < 1.0 A, including the Hi-Z-exit SYS
  step at the ILIM ceiling. OC_FC must not trip. Scope-armed, per ruling 4.
- **B7** Start into D-BT-SQ from VCHG = 0 V: auto-wakeup absent (written 0) or observed self-terminating at VSYSMIN; D-BT-SQ
  closes; no BATOVP or SYS_SHORT.
- **B8** Charger unpowered: Teensy SDA/SCL idle ≥ 3.0 V; leakage into the unpowered U1 pins < 10 µA.
- **B9** Pack voltage at taper through D-BT-SQ vs the 8.400 V setting.

## 9. Round-1 claims re-checked: corrections

| # | Round-1 claim | Primary finding |
|---|---|---|
| 1 | ILIM_control HIGH = Hi-Z; "NMOS inverter so pin 5 HIGH = enable" wired to J2 ILIM_control | **Schematic: ILIM_control LOW = Hi-Z** (D5 anode on ILIM_HIZ, cathode on ILIM_control; R26 383 kΩ to EVM 3V3; JP6 = "ILIM_HIZ LOW") [UG Fig.11, Table 2]. UG Table 1's wording contradicts its own schematic. The round-1 inverter on J2-1 would therefore give pin 5 HIGH = Hi-Z (inverted). Drive TP22 directly (section 7). "Floating = enabled" holds either way |
| 2 | "POR ChargeCurrent = 0: charging does not start until the host writes it. Met." | **Incomplete.** AUTO_WAKEUP_EN = 1 at POR gives 128 mA for up to 30 min while VBAT < VSYSMIN (DS p.41, p.56). Behind D-BT-SQ this fires at every input power-up. It self-terminates at about 6.1 V unless the pack is below that |
| 3 | "150 ms converter power-up" = [WS], uncorroborated; cold start 65-75 ms | **Primary:** DS §9.3.3 step 5 p.24 ("150 ms after VBUS above VVBUS_CONVEN, converter powers up"); Fig. 10-3 p.77 is consistent. Cold start is ≥ 150 ms plus board overhead. Cold-start regen is impossible |
| 4 | EVM 3V3 from an on-board LDO fed from VIN (JP8) | U2 LM3480 is fed through JP8 / R38 from **D3 (VBUS) OR D2 (BAT)** [UG Fig.11] |
| 5 | EVM VIN capacitance UNVERIFIED | **94.5 µF nominal, including C53 33 µF tantalum.** Over the OC_FC budget as shipped; mod in section 5 |
| 6 | (omitted) | **C25 0.47 µF is 16 V** on the VBUS-pin filter: below the operating V-MOT. Replace |
| 7 | (omitted) | **Z1 SMAJ26CA** 26 V TVS already on the EVM, on the Q5/Q6 node. Round-1 4.3 #5's "TVS unworkable / active clamp" is unaffected. SMAJ26CA datasheet not read |
| 8 | VINDPM accuracy −3 %/+2 % [snip] | Confirmed, DS p.12 (18.688 V row) → 18.44-19.39 V at code 247 |
| 9 | CHRG_OK 50 ms deglitch [snip/WS] | Confirmed, DS p.7, p.24 |
| 10 | Watchdog 5/88/175 s, only ChargeCurrent resets | Confirmed, DS p.30, p.37. **Add:** 5 s = 4-7 s (DS p.19); writing WDTMR = 00 *resumes* charging (DS p.30) |
| 11 | No TS/NTC pin (UNVERIFIED) | Confirmed, DS pin table p.6-8 |
| 12 | CV about ±0.6 % [snip] | Confirmed, DS p.11 (0-85 °C) |
| 13 | VSYSMIN 2S default UNVERIFIED; pre-charge clamp UNVERIFIED | 6.144 V (DS p.60); 384 mA for 2S-4S (DS p.11, p.57) |
| 14 | ADC register map UNVERIFIED; 50 Hz I_charge polling | Map in 2.12. **Continuous mode updates every 1 s; one-shot about 10 ms** (DS p.50). Use one-shot |
| 15 | NVDC may switch with ChargeCurrent 0 (small bus draw) | Confirmed: VSYS is regulated 160 mV above VBAT with the BATFET off (DS p.31); PFM no-load about 2.2 mA typ (DS p.13). Only Hi-Z stops the converter |
| 16 | (omitted) | **ACOV does not reset ChargeCurrent** (DS p.56): charging resumes 1 ms after ACOV clears (DS p.15) |
| 17 | (omitted) | New hardware inhibit option: CELL_BATPRESZ < 15 % (J2-4 CELL_control). It resets ChargeCurrent and VREG and latches until a host rewrite (DS p.6, p.56) |
| 18 | "Set the ILIM pin divider ≤ 1.0 A" | Conflicts with the regen hard requirement (≥ 2-2.5 A charge, [REGEN]). Use a 1.235 A nominal pin ceiling plus IIN_HOST 0.7 A in FC mode, or the mode-switched divider |
| 19 | Comparator gates the charger; warm response = VINDPM release | With the [LOOP] comparator on ILIM_HIZ, the charger is **in Hi-Z throughout cruise**, so capture latency = Hi-Z exit (plus a possible VINDPM re-measure). B3/B4b |
| 20 | Price about USD 154; DigiKey stock snapshots | TI store **USD 156.45, 38 in stock** (2026-11-05). DigiKey, Mouser and Farnell are not reachable from this session |
| 21 | VBUS recommended 0-24 V | Confirmed (DS p.9). Note the EC table says VINPUT_OP 3.5-26 V (DS p.10), an internal inconsistency; design to 24 V |
| 22 | Address 0x6B | Confirmed for BQ25713RSNR (EVM BOM p.12); BQ25713B = 0x6A; DeviceID 0x88 / 0x8A (DS p.72) |

## 10. Missing primaries (operator to fetch)
- **Hi-Z entry/exit latency, VINDPM loop bandwidth / transient, and VINDPM retention across Hi-Z/ACOV:** not in SLUSD83C. Ask TI
  E2E / FAE, or measure (B2-B4).
- VBUS-side quiescent in Hi-Z and below VINDPM: not in SLUSD83C (B5).
- LM3480 (EVM U2) datasheet: input voltage rating at 21.4 V via D3; quiescent.
- BAT54H (D2/D3/D5), SMAJ26CA (Z1), 2N7002 (inhibit stage), CSD25402Q3A (Q7 BATFET R_DS(on)), GRM21BR61E106KA73L DC-bias curve
  (effective input capacitance).
- EVM mechanical dimensions (not in SLUUBT8B): the TI EVM design files / Altium (TI E2E indicates they are on request).
- Mouser and Farnell stock and lead time: hosts not allowed in this session.
