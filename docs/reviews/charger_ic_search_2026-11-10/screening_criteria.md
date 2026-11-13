# Charger IC search: screening criteria and the buck versus buck-boost decision (2026-11-10)

This document defines the screening framework for a replacement of the Silvertel Ag105 (BOM `CHG`) on board rev 20260622,
for a charger that sits on a custom PCB. It also decides whether the input range requires a buck-boost converter or whether
a buck converter is sufficient.

Sources used in this document:

- `docs/charger_replacement_evaluation_2026-11-05.md` (cited as **EVAL**), sections 0.1-0.4, 1.1-1.3, 2, 3.2-3.4 and 6.4.
- `docs/reviews/charger_eval_2026-11-05/spec.md` (**SPEC**), the CHG pad table.
- `docs/reviews/charger_eval_2026-11-05/round3/review_loop.md` (**R6**), the round-6 dispositions.
- `docs/charger_bq25798_wiring_design_2026-11-05.md` (**WD**), as a reference for interlock functions and path resistances.
- `teensy_controller/teensy_controller.ino` at the worktree tip (**INO**), cited by line.
- `references/Datasheets/RT1987_DS-00.pdf` (**RT**), Richtek RT1987 DS-00, September 2024, read for this document.
- Round-2 dossiers in `docs/reviews/charger_eval_2026-11-05/round2/` for the dropout figures of three buck parts. Those
  figures were read from the primary datasheets by the round-2 authors; this document repeats them as recorded and does not
  re-read the primaries. They are marked **[R2]**.

Status codes follow EVAL section 1.2: P = PROVEN_DATASHEET, C = PROVEN_CALC, B = BENCH_GATE, F = FAIL, U = UNKNOWN or
missing primary, sys = blocked at system level.

---

## 1. Scope and changed meaning of the 2026-11-05 requirements

### 1.1 Form factor

The **custom charger board (CCB)** plugs into the 22 Ag105 through-holes on pin headers and may extend sideways past the
32.0 x 34.8 mm footprint (SPEC). The charger IC, its power stage and the hardware interlock all go on the CCB. Board area is
moderate. Reflow assembly is available, so QFN and WCSP packages are eligible. The 22 pads carry VCHG-IN, GND, VCHG (the
D-BT-SQ input), SDA, SCL, STAT, MPPTD and THERM (SPEC pad table). No pad carries the fuel-cell stack voltage or the pack
voltage on the pack side of D-BT-SQ.

### 1.2 Requirements whose meaning changes with a custom board

The 2026-11-05 evaluation screened parts as EVMs mounted off-board. With the CCB, the following requirements change meaning.

| ID (EVAL 1.1) | Meaning on 2026-11-05 | Meaning for the CCB |
|---|---|---|
| H8 inrush | Stock EVM input capacitance against the RT1987-ramped node; "stock F" where the EVM carried too much capacitance or an electrolytic | A design constraint on the CCB schematic. The input capacitance after DC-bias derating, plus the motherboard C-D8/C-D10, must keep the D-BC-FC close current at or below 1.0 A including the 0.15 A aux load (12 mA/uF with 5.6 nF CSS, EVAL 3.4 item 4). A part fails only if its datasheet demands more input capacitance than this budget allows (the BQ25756 80 uF minimum, EVAL 0.2, is the known case) |
| H10 thermal / mechanical | Loss <= 2 W and an off-board mount on leads | Loss <= 2 W is kept. "Off-board mount feasible" is replaced by "power stage, interlock and headers fit on one CCB with the IC heat path in CCB copper". Lead-length limits (R6 findings 13 and 14) do not apply |
| H11 availability | EVM stock at the vendor store | Stock of the IC and of its critical power-stage parts (external FETs, inductor, sense resistor) from an authorised distributor or the vendor store |
| EVM modifications | Mods M1-M11, EM1-EM4 and the EVM interface board | Schematic choices. A stock-EVM failure (for example /CE grounded by JP17, the /CE pull-up on the EVM PULLUP LDO) is no longer a penalty. A datasheet-level property (for example a pin function that a register can defeat) still is |
| HR5 / H3 "stock F" | Fails as shipped, passes after mods | The CCB design decides the inhibit bias. Only the IC's intrinsic POR behaviour and pin semantics are scored |
| HR4 hardware ceiling | Mode-switched ILIM_HIZ divider on the EVM | A hardware current ceiling may now come from the IC (ILIM pin or sense-resistor full scale) or from a CCB current regulator. The IC route is scored higher, because an eFuse trip removes harvest while an IC ceiling regulates |
| Telemetry H12 | The IC's own ADC only | The IC's ADC, or a CCB current monitor on the same I2C bus. The IC route is scored higher (fewer parts, one address, no second calibration) |
| EVAL 6.4 trigger 5 | Coupled-glitch and ground-shift faults of the hand-wired carrier | Largely retired. The CCB layout still needs the ground-shift and coupling checks of the R6 test registry |

HR1-HR5, H1, H2, H4, H5, H6, H7, H9 and H12 keep their 2026-11-05 pass conditions. The interlock functions that any charger
must support are those of WD and EVAL 2.6: the H1 V-MOT/VBUS comparator, the H2 FC-window permit with BT_ACT, the C7
qualifier, the `CHG_QUAL AND NOT P5` release term, the OVN pack-OV term from the BQ29200 OUT (R6 finding 1), the eFuse on
VCHG-IN, the mode-switched input ceiling keyed to FCC_net, and the MCU watchdog. These functions are system-level and the
same for every candidate. Section 3 scores only the IC-specific hardware that each candidate needs to connect to them.

---

## 2. Must-have criteria (pass/fail)

A candidate that fails one must-have is rejected. A must-have whose evidence is U or B passes **conditionally**: the
candidate stays on the list, the gap becomes a named bench gate, and the evidence cap of section 3.2 applies to the related
scored criterion. A must-have fails outright only on a documented contrary fact.

| ID | Requirement | Pass condition | Source requirement |
|---|---|---|---|
| **M1** | Common ground, no return-path element | Input return and battery return are one node. Charge-current sense is high-side (BAT+ or SYS-BAT) or input-side. No shunt or FET in the battery or input return | H1, the ML0227 incident (EVAL 1.0) |
| **M2** | Input voltage rating | Absolute maximum >= 35 V on every pin that sees VCHG-IN (or its switch node and bootstrap equivalent). Recommended operating range covers 22.28 V. No input OVP or ACOV disable at or below 22.28 V (minimum threshold) | H6, tightened from 30 V |
| **M3** | 2S charge profile | CV settable to 8.400 V with a total error of +-1.0 % or better over temperature, including any external divider at 0.1 %. The temperature basis is the TJ 0 to 85 C specification where the datasheet publishes one, otherwise the published range; the basis is stated per part. Pre-charge, CC and CV with termination available | H5 |
| **M4** | Charge-current capability | Charge-current regulation reaches >= 3.1 A at an 8.4 V pack with a power stage that fits the CCB and dissipates <= 2 W at that point | HR1 (regen capture; >= 23 W input at the threshold) |
| **M5** | Hard inhibit pin | A pin (not a register) that stops conversion, including pre-charge and trickle, while the input is powered. It acts from POR without any I2C transaction. A register bit that can disable the pin's function is acceptable only if the POR value enables the pin and the never-write list plus readback can hold it | HR5, H2 |
| **M6** | Fail-safe default | With the inhibit pin biased to its inhibit level by a resistor (from the IC's own regulator or from GND), the IC does not charge with the Teensy unpowered, in reset, hung or with I2C dead. No non-volatile setting (OTP, EEPROM, stored image) enables autonomous charging out of POR | HR5, H3 |
| **M7** | Hardware current ceiling | An absolute input-current or charge-current ceiling set by hardware (ILIM pin, or the sense-resistor full scale) that applies from POR and that no register write can raise. A CCB-level current regulator satisfies this requirement with a penalty in criterion S3 | HR4 |
| **M8** | Runtime input-voltage regulation | An input-voltage regulation loop (VINDPM, UVCL, MPPT-set or equivalent) settable at runtime to 13.5-15 V (FC mode) and 18.5-19.5 V (regen mode), by I2C or by a Teensy-switched resistor network. The loop regulates input current to zero below the threshold without shutting the converter down. Draw at the bus voltage <= 10 mA | H4 |
| **M9** | No cold restart in the regen path | Neither the input-voltage threshold crossing nor the per-burst inhibit exit re-runs an input-detect deglitch, a POR, or a soft-start of 10 ms or longer. A documented restart of that class (BQ25756 cold restart 145-175 ms, BQ24650 1.5 s MPPSET release, MP2759 VLIM re-enable about 175 ms; EVAL 0.2, 1.3) fails. Missing evidence is a conditional pass with a bench gate. A bench no-start on inhibit exit at any pack voltage within 7.4-8.4 V counts as a documented restart failure (bench-gate class) | HR1, EVAL 3.2 (cold start 65-170 ms never works) |
| **M10** | Host interface | I2C or SMBus, 100 kHz, open-drain, logic levels compatible with 3.3 V pull-ups (VIH max <= 2.3 V), no back-powering of SDA/SCL when the IC is unpowered | H9 |
| **M11** | Charge-current telemetry | Charge current readable by the Teensy at >= 50 Hz, by the IC's ADC or by a CCB current monitor on the I2C bus | H12 |
| **M12** | Runtime current control | Input-current limit settable at runtime (the FC-window governor rewrites it at 50 Hz, EVAL 3.4) and charge current settable at runtime | H5, EVAL 3.4 |
| **M13** | Lifecycle | Part status Active (not NRND, not obsolete) on the vendor page | H11 |

Notes:

- M9 does not require a published warm-response time. No TI, ADI or MPS datasheet read in round 2 publishes one (EVAL 0.2,
  HR1 row). The warm-response figure is scored in S1 and measured on the bench.
- M7 for the FC mode: the ceiling must be switchable by hardware between a regen value and an FC value (EVAL 3.4: FC
  0.74-0.96 A, regen 1.44-1.72 A in the BQ25798 design). A single fixed ceiling passes M7 and loses points in S3.

---

## 3. Scored criteria

### 3.1 Criteria, weights and scoring anchors

Each criterion is scored 0-3. The weighted score is the sum of weight x score / 3, with a maximum of 100. The BQ25798 is
scored with the same rules as the baseline.

| ID | Criterion | Weight | 0 | 1 | 2 | 3 |
|---|---|---|---|---|---|---|
| **S1** | Warm response and inhibit-exit path (HR1, EVAL 3.2: tau_warm <= 4 ms, 10-90 % <= 9 ms, <= 2 ms at board-only capacitance) | 15 | A restart longer than 10 ms on threshold crossing or inhibit exit is documented, but M9 passed conditionally | No documentation either way | The datasheet documents that the converter stays enabled in input-voltage regulation, and the inhibit exit has no deglitch or soft-start, or one shorter than 1 ms | As 2, plus a published input-regulation loop bandwidth or step response consistent with tau <= 4 ms |
| **S2** | Intrinsic fail-safe POR (HR5) | 10 | POR charges at a non-zero current with the inhibit pin inactive | POR charges, but the inhibit pin defaults to inhibit with a resistor that the CCB can bias from the IC's own rail | POR does not charge until a register write (charge current 0 or charge disabled at POR) | As 2, and the input-voltage threshold at POR is above 22.28 V or at its maximum (the charger cannot draw from the bus after a POR) |
| **S3** | Hardware ceiling quality (HR4) | 8 | Ceiling only on the CCB (eFuse or separate regulator) | IC ceiling exists, fixed, not mode-switchable without extra parts | IC ceiling switchable by one resistor and one switch keyed to FCC_net | As 2, and the ceiling is re-sampled continuously (not only at plug-in) with a published accuracy |
| **S4** | Input threshold quality (H4) | 8 | Range does not cover 18.5-19.5 V and 13.5-15 V without hardware switching | Ranges covered, step > 100 mV or accuracy worse than +-3 % | Step <= 100 mV and accuracy <= +-2 % at 18-19 V | As 2, and a host-written value is documented to survive inhibit exit, input dips and the charger watchdog (EVAL 0.2 reason 1) |
| **S5** | Inhibit latency (H2, EVAL 2.5: <= 115 us covers every row) | 7 | Inhibit latency documented > 1 ms | Not documented | Documented <= 1 ms or a pin deglitch <= 115 us documented | Documented converter-off within <= 115 us at the pin |
| **S6** | IC-specific interlock hardware (section 3.3) | 10 | > 8 adder parts, or an adder needed to defeat a register-defeatable pin | 6-8 adder parts | 3-5 adder parts | <= 2 adder parts |
| **S7** | Telemetry (H12) | 5 | CCB monitor needed for charge current | IC ADC for charge current only | IC ADC for charge current, input current and input voltage | As 2, with a published accuracy and a conversion time <= 20 ms for the three channels |
| **S8** | FC-mode fitness (H5, EVAL 3.4) | 6 | Input-current limit step > 100 mA, or no termination | Step <= 100 mA, CV +-1.0 % | Step <= 50 mA, CV +-0.5 %, termination programmable | As 2, with input-current regulation accuracy published at VIN >= 12 V |
| **S9** | Rating margin (H6) | 4 | Abs max 35-37 V | 38-44 V | 45-59 V | >= 60 V |
| **S10** | Layout difficulty | 7 | Buck-boost with external FETs (two hot loops), or switching frequency > 2 MHz with a 0.35 mm-pitch WCSP | Integrated buck-boost, or buck controller with external FETs and a separate BATFET | Buck controller with two external FETs, or integrated buck with exposed-pad QFN | Integrated buck in a leaded or 0.5 mm-pitch package with a published reference layout |
| **S11** | Package | 3 | WCSP or BGA at <= 0.4 mm pitch | QFN at <= 0.4 mm pitch, or a multi-pad QFN with inner pads | QFN at 0.5 mm pitch with one exposed pad | Leaded package (TSSOP, SOIC) or QFN at >= 0.65 mm pitch |
| **S12** | Stock (IC and power-stage parts) | 5 | No authorised stock | < 100 units at one source | >= 100 units at one source | >= 1000 units at two or more sources |
| **S13** | Cost (IC plus power stage, 5 boards) | 2 | > USD 60 per board | USD 30-60 | USD 15-30 | < USD 15 |
| **S14** | Round-6 findings (section 3.4) | 5 | Net reopens >= 2 IC-specific findings | Net reopens 1 | Net 0 | Net closes >= 1 IC-specific finding |
| **S15** | Input capacitance and inrush (H8, custom meaning) | 3 | Datasheet minimum input capacitance exceeds the section 1.2 budget | Minimum not stated and the reference design exceeds the budget | Reference design fits the budget | Fits with >= 30 % margin |
| **S16** | Topology barrier (section 4.6) | 2 | Buck-boost with a POR input threshold below the pack voltage | Buck-boost with a POR input threshold above the pack voltage | Buck | Buck with a documented sleep or headroom comparator that stops conversion below VBAT plus a fixed margin |

Weights sum to 100. The HR criteria (S1-S5, S8) carry 54 points; build and supply criteria (S10-S13, S15) carry 20; the
interlock count, the round-6 ledger and the topology barrier carry 17; telemetry and ratings carry 9.

### 3.2 Evidence cap

The score of a criterion is capped by the status of its evidence:

- P or C: no cap.
- B (mechanism documented, number unmeasured): cap 2.
- U, or any fact marked UNVERIFIED (product page, distributor listing, search snippet, forum, recollection): cap 1.

A dossier states the evidence status beside every score. This rule prevents a well-documented part from losing to a part
whose datasheet is silent.

### 3.3 Counting IC-specific interlock hardware (S6)

The system-level core (H1, H2 with BT_ACT, C7, OVN, the eFuse, the heartbeat monostables, the FCC/RGN level sensing, EVAL 2.6
and R6 findings 1 and 6) is the same for every candidate and is not counted. An **adder part** is any resistor network,
transistor, gate, comparator or switch that exists only to connect this IC to the core. Examples from the BQ25798 design (WD):

- the open-drain drive and REGN-biased pull-ups on /CE;
- the ILIM_HIZ hold-down and release transistors;
- the third ILIM resistor and its switch keyed to FCC_net;
- the `CHG_QUAL AND NOT P5` gates (one 1G04 and one 1G08, EVAL 2.3);
- any keep-alive or bridge needed by the D-BT-SQ disposition (EVAL 0.2 condition 4).

Resistors that the IC needs in any application (feedback dividers, the sense resistor, compensation) are not counted. The
BQ25798 baseline count is taken from the round-6 bill of materials (WD section E) in scoring.md, with the list above
as the minimum. TODO(verify: WD section E count).

### 3.4 Round-6 findings ledger (S14)

R6 lists 16 verified findings. They fall into three classes for a custom-board candidate.

| Class | R6 findings | Effect on the score |
|---|---|---|
| Closed by any single CCB (EVM-carrier geometry) | 13 (coordinate mirror), 14 (EIB lead lengths), 15 (stale J101 dimensions), 16 (W2 star pads) | Not counted: every candidate gains them equally. Finding 3 (battery-path copper sized below ICHG) reopens as a CCB copper-sizing task for every candidate; also not counted |
| System-level, IC-independent | 2 (D-BT-SQ short), 4 (eFuse IN spike vs MB ratings), 5 (eFuse IMON bypass capacitor), 6 (FCC/RGN LVC thresholds vs the RT1987 EN band), 7 (pins 38/39 ADC overvoltage), 9 (purge ride-through), 11 (feed-forward headroom admission) | Not counted |
| IC-dependent | 1 (VREG corruption, no fixed pack OVP), 8 (5 ms loop budget vs 1 ms deadlines, driven by the I2C write and read-back burden), 10 (`chg_src` misattribution of sub-H1 regen, driven by telemetry), 12 (reversal hold unattainable at 100 kHz, driven by the I2C write needed per mode change) | Counted. A candidate **closes** finding 1 if its CV is set by a hardware divider or pin strap that a register cannot raise; closes 8 or 12 if mode changes need no I2C write (hardware-pin threshold or ceiling switching) or fewer writes than the BQ25798 image; closes 10 if it measures input current per source or has an input-current ADC with a published accuracy. It **reopens** a finding if it makes the mechanism worse (more never-write registers, a slower ADC, a mode change that needs more writes) |

### 3.5 Decision rule against the baseline

A challenger is recommended over the BQ25798 only if all of the following hold:

1. It passes every must-have, and none of its conditional passes concerns M5, M6 or M7 where the BQ25798 has P evidence.
2. Its weighted score exceeds the BQ25798 score by at least 10 points. The margin is a judgement that covers the forward
   cost of a switch (the CCB layout in progress, a new register image, the IC-specific test entries and one review cycle);
   section 9 of scoring.md gives its basis.
3. It reopens no IC-dependent round-6 finding of major severity (R6 findings 1, 8 and 10 are major; 12 is minor).
4. Its S1 score is at least the BQ25798 S1 score, because HR1 is the requirement that both 2026-11-05 verdict rows leave
   UNDETERMINED.

A challenger that meets conditions 1, 3 and 4 with a margin below 10 points is recorded as the alternate.

---

## 4. Buck versus buck-boost

### 4.1 Question and method

A buck converter can charge only while its input exceeds its output by the dropout headroom. This section finds the lowest
VCHG-IN at which the charger must deliver current, the highest charger output voltage, and the dropout headroom of buck
chargers. It then lists the cases that would need boost.

### 4.2 Highest charger output voltage

The charger regulates its own output pin, which is VCHG on the input side of D-BT-SQ. The pack sits behind D-BT-SQ and the
motherboard path.

| Item | Value | Source |
|---|---|---|
| CV setpoint | 8.400 V | EVAL 3.4 |
| CV tolerance, M3 limit | +-1.0 % -> 8.316 V minimum and 8.484 V maximum at the charger output | M3 (BQ25798: -0.25/+0.65 %, 8.455 V, EVAL 3.4) |
| Charge current for headroom | 3.21 A (3.10 A image plus the +3.5 % ICHG tolerance) | WD H.11 |
| D-BT-SQ drop at 3.21 A | 64 mV at RON 20 mOhm typical (RT EC, RON_20V, VIN 20 V, 1 A, p.7); 96 mV at the 30 mOhm used by WD H.11. RON maximum: TODO(verify: RT1987 DS-00 p.7, the maximum column did not extract) | RT, WD |
| Battery leads and MB path | 12.6 mOhm + 6.8 mOhm = 19.4 mOhm -> 62 mV | WD H.11, H.22 |
| Pack CV through the path | 8.34-8.42 V at termination (BQ25798 design) | EVAL 3.4 |

During CC the pack is below CV, so the charger output stays at or below its CV setpoint; the D-BT-SQ and lead drops only
lengthen the CV phase. The highest charger output voltage is therefore **8.484 V** (M3 limit) and 8.455 V for the BQ25798.

### 4.3 Dropout headroom of buck chargers

The buck needs VIN >= (VOUT + I x R_internal) / D_max, where R_internal is the high-side FET, inductor DCR, sense resistor
and any series BATFET. The internal resistance is not known for unselected parts. This analysis uses 100 mOhm at 3.21 A
(0.32 V) as an assumed upper value for an integrated or two-FET stage; each finalist dossier replaces it with its own figures.

| Headroom model | Required VIN at 8.484 V out, 3.21 A | Source |
|---|---|---|
| D_max 98.4 % | (8.484 + 0.32) / 0.984 = **8.95 V** | LTC4015 maximum duty 98.4 % (LTC4015 Rev B p.7) [R2] |
| D_max 95 % (assumed generic value) | (8.484 + 0.32) / 0.95 = **9.27 V** | Assumption |
| VIN >= VBAT + about 1 V | **9.48 V** | BQ24650 (SLUU444A p.3) [R2] |
| VIN > VBAT + VHDRM 2.4 V | **10.88 V** | MP2759 DS Rev 1.0 p.6 [R2] |

The worst case of these four models is **10.88 V**. This value is the buck feasibility floor used below.

### 4.4 Lowest VCHG-IN at which the charger must deliver current

| Mode | Lowest VCHG-IN that must charge | Derivation | Margin over 10.88 V |
|---|---|---|---|
| FC charging, normal | 15.57 V | VBUS nominal 16.0 V (INO 2102; 15.91 V no-load); loaded sag 15.6 V measured (INO comment at 2156-2160); D-BC-FC drop at 1.0 A is the 35 mV VFWD regulation, because 1.0 A x 20 mOhm < 35 mV (RT §17.6) | 4.69 V (43 %) |
| FC charging, at the input-regulation floor | 13.14 V | FC-mode VINDPM 13.5 V at -2.6 % (EVAL 3.4). Below this value the input regulation loop takes the charge current to zero, so no charge is required | 2.26 V (21 %) |
| Regen | 18.13 V | Regen VINDPM 18.5 V at -2 % (H4 range bottom); conversion is also gated by H1, whose fall trip is >= 16.62 V (EVAL 2.2) | 7.25 V (67 %) |
| Bus under-voltage limit | 12.0 V | `LIMIT_V_BUS_MIN` (INO 2163). The bus is faulted below this value; it is not a charging point | 1.12 V |

In every mode where charging is required, VCHG-IN is at least 13.14 V. The lowest input-to-output ratio is
13.14 / 8.484 = **1.55**, a duty cycle of about 0.67 including the assumed internal drop. A buck therefore covers the full
operating envelope with at least 2.26 V of margin over the most pessimistic headroom model.

### 4.5 Low-input states where the charger must not charge

| State | VCHG-IN | Required charger behaviour | Buck | Buck-boost |
|---|---|---|---|---|
| Staged bring-up P0 (Init) | Bus = max(V_fc, V_batt) minus up to 1.5 V, floor 5.0 V (INO 2313-2330, `PRECHARGE_DROP_MAX`, `V_PRECHARGE_MIN`); FC_CHARGE and REGEN are LOW in Init, so VCHG-IN is normally unpowered | No charge | Cannot charge while VIN <= VBAT + headroom; the precharged bus can exceed this if V_fc > VBAT + 1.5 V + headroom (H-20 open-circuit voltage UNVERIFIED), so P0 relies on FC_CHARGE and REGEN LOW | Can charge if powered and enabled |
| Boosts disabled, bus fed through the TPS61288 body diode | Bus about V_batt minus one diode drop (passthrough, CLAUDE.md section 2 hazard) | No charge: this is a pack -> bus -> charger -> pack circulation | Cannot charge: VIN < VBAT | Can charge: a loop that only the interlock stops |
| H-20 purge in an FC window | FC-only bus collapses at about 2.57 V/ms (EVAL 3.4 item 1); the purge ruling (2026-11-08) inhibits FC charging before the purge | Inhibited by the Teensy and by H2 | Also stops by physics below VBAT plus headroom (LTC4015: about 7.5-8.7 V); above that only UVCL, the Teensy and the path switches stop it | Stops only at its input threshold; after a charger POR that threshold can be low (BQ25773 POR VINDPM 3.2 V, EVAL 1.3) |
| Cruise decay of VCHG (D-BT-SQ input) | VCHG, the charger output and D-BT-SQ input (not VCHG-IN), falls below the RT1987 UVLO in 0.17-0.78 s (EVAL 0.1a, lines 92-93); the next burst pays tD_ON 8 ms + tON about 1.9 ms | No charge | Not an input-side state; see P1 | Not an input-side state; see P1 |
| Purge collapse to about 1 V, bus UV | < 12.0 V, latched UV_BUS | No charge | Cannot charge | Cannot charge below its own UVLO |

In each of these states charging is either forbidden or useless. A buck cannot charge unless VIN exceeds VBAT plus its
headroom: a **hardware floor of about 7.5-10.9 V** over the 7.4-8.484 V pack range (LTC4015: VBAT + 0.14-0.25 V, 4015fb
p.4) that no register write or charger POR can lower. The floor blocks the passthrough-bus circulation, because that bus
lies below VBAT. In P0 the precharged bus can exceed the floor, so the absence of charge in P0 relies on FC_CHARGE and REGEN
being LOW. A buck-boost removes this floor.

### 4.6 Cases that would need boost

| Case | Required input range | Buck feasible? | Status on board rev 20260622 |
|---|---|---|---|
| Direct charging from the H-20 stack | Stack loaded at about 7.8 V at 2.6 A (H-20 brochure figure, INO 2085-2087; TODO(verify: H-20 datasheet)); purges to about 1 V (INO 2148) | No: the loaded stack is below the 8.4 V CV | Not possible on Path A: no CCB pad carries the stack voltage (SPEC). Needs a motherboard re-spin |
| 3S pack | CV 12.6 V; charger output up to 12.73 V at +-1 %; required VIN 13.7 V (D_max 95 %) to 15.1 V (VHDRM model) | Marginal: works from the 15.57 V loaded bus with 0.5-1.9 V margin; fails at the 13.14 V FC-mode floor, so the FC VINDPM must rise to about 15 V | Out of scope: the pack is 2S, 7.4-8.4 V by operator ruling (2026-07-10), and BT boost compensation, OV/UV limits and the BQ29200 assume 2S |
| 4S pack | CV 16.8 V, above the 16.0 V bus | No | Out of scope |
| Charging during bring-up or from a low bus | VCHG-IN 5-10 V | No | Not wanted (section 4.5) |

No case inside the 2S Path A envelope needs boost.

### 4.7 Cost and benefit of a buck-boost stage

| Item | Buck | Buck-boost |
|---|---|---|
| Switches, external-FET controller | 2 FETs (plus a BATFET if NVDC) | 4 FETs (plus a BATFET if NVDC), two gate-drive pairs |
| Hot loops | One (input capacitor, high-side and low-side FET) | Two (input side in buck mode, output side in boost mode); both must be minimised on the CCB |
| Small-signal | No right-half-plane zero | Right-half-plane zero in boost and buck-boost regions, f_RHPZ = R_load (1 - D)^2 / (2 pi L); the compensation must cover it whenever the controller can enter those regions, including at start-up and brown-out where VIN approaches VOUT |
| Buck-mode conduction | High-side FET, inductor | As buck, plus the output-side switch that stays on in buck mode; extra I^2 R loss at 3.21 A. For an integrated part (BQ25798) the extra switches are internal and the loss is in its efficiency curve |
| Low-input behaviour | Hardware no-charge floor at VBAT plus headroom (about 7.5-10.9 V over the 7.4-8.484 V pack; VIN > VBAT plus headroom) | Charges from any input above its UVLO and threshold; relies on the threshold register and the interlock in the states of section 4.5 |
| Benefit on this board | - | None inside the 2S envelope. It enables only 4S packs and direct-stack charging, and both need a motherboard re-spin |

### 4.8 Conclusion

**A buck charger is sufficient.** The lowest input at which charging is required is 13.14 V (FC-mode threshold floor) and
the nominal FC input is 15.57 V. The worst-case buck requirement is 10.88 V at 8.484 V out and 3.21 A. The margin is 2.26 V
(21 %) at the floor and 4.69 V (43 %) at nominal. Regen inputs (>= 18.13 V) have 7.25 V of margin. Buck-boost is not
required for any 2S operating mode, and the cases that would need it (direct-stack charging, a 4S pack) need a motherboard
re-spin first.

Buck-boost parts stay eligible: the BQ25798 baseline is a buck-boost IC that operates in buck mode across this envelope.
However, a buck-boost earns no credit for its boost capability, and a buck earns the S16 credit for its hardware no-charge
floor. That floor makes the passthrough-bus circulation of section 4.5 physically impossible, independent of registers and of
the interlock. A 3S future is marginal on a buck (0.5-1.9 V of margin from the loaded bus) and is noted as a re-spin trigger,
not as a screening requirement.

Open items from this section:

1. RT1987 RON maximum: TODO(verify: RT1987 DS-00 p.7).
2. The 100 mOhm internal-resistance assumption of section 4.3 is replaced by each finalist's datasheet figures.
3. The three [R2] dropout figures are repeated from the round-2 dossiers; a finalist dossier that relies on one re-reads its
   primary.
4. Minimum on-time check for each finalist: the smallest duty cycle is about 6.0 / 22.28 = 0.27 at a pre-charge pack, and
   about 0.13 if VCHG sits at 3 V. The finalist's t_on,min must satisfy t_on,min <= D_min / f_sw at its switching frequency
   (at 1.5 MHz and D 0.13: 87 ns).
