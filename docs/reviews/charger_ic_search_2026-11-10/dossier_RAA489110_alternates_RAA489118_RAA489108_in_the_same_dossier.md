# Dossier: Renesas RAA489110 on the custom charger board, with the RAA489118 and RAA489108 as alternates (2026-11-10)

This dossier assesses the Renesas RAA489110 as the charger IC of the **custom charger board (CCB)** defined in
`screening_criteria.md` section 1.1: one board that plugs into the 22 Ag105 holes of board rev 20260622 and carries the
charger IC, its power stage and the hardware interlock. Section 4.2 of `screening.md` lists the RAA489110 as finalist 4, the
only non-TI part that passes the must-haves with an on-chip ADC. The RAA489118 and the RAA489108 are covered as alternates in
section 17. No 2026-11-05 dossier exists for these parts; every fact below was read from the primary documents listed in
section 1.

Source tags:

| Tag | Document |
|---|---|
| [DS] | Renesas R16DS0212EU0202 Rev.2.02, *RAA489110 Buck-Boost Configurable Battery Charger with SMBus Interface Supporting USB PD EPR*, Aug 17, 2026, 91 pp. plus the L32.4x4D package outline. Cited as DS p.N plus section, table or figure. PDF page = printed page |
| [UG] | Renesas R16UZ0064EU0102 Rev.1.02, *RTKA489110DE0000BU Evaluation Board Manual*, Aug 14, 2026, 26 pp. Read for layout and reference power-stage information only (schematic p.17, BOM pp.18-19) |
| [DS118] | Renesas R16DS0321EU0200 Rev.2.00, *RAA489118 Buck-Boost Battery Charger with SMBus Interface for General 30V and USB PD EPR*, Oct 28, 2025, 68 pp. |
| [DS108] | Renesas R16DS0159EU0105 Rev.1.05, *RAA489108 Buck-Boost Narrow VDC Battery Charger with SMBus Interface Supporting USB PD EPR*, Mar 14, 2025 |
| [EVAL] | `docs/charger_replacement_evaluation_2026-11-05.md` |
| [WD] | `docs/charger_bq25798_wiring_design_2026-11-05.md` |
| [R6] | `docs/reviews/charger_eval_2026-11-05/round3/review_loop.md`, review round 6 |
| [SPEC] | `docs/reviews/charger_eval_2026-11-05/spec.md` |
| [CRIT] | `docs/reviews/charger_ic_search_2026-11-10/screening_criteria.md` |
| [SCR] | `docs/reviews/charger_ic_search_2026-11-10/screening.md` |
| [B798] | `docs/reviews/charger_ic_search_2026-11-10/dossier_BQ25798.md` (baseline re-assessment) |

Status codes: P = PROVEN_DATASHEET, C = PROVEN_CALC, B = BENCH_GATE, F = FAIL, U = UNKNOWN or missing primary, sys = blocked
at system level. Values read off a datasheet figure are labelled "figure reading, typical". Values marked **A** are design
assumptions for parts that this dossier has not selected; they are not datasheet values. The calculations are in
`calc/raa_calc.py` and `calc/f1050.py` in this folder; every result used is restated in the text with its inputs.

---

## 1. Identity and sources

| Item | Value |
|---|---|
| Part | RAA489110, buck-boost NVDC and hybrid-power charge controller, 2-4 cells, SMBus/I2C, internal 8-bit ADC, external N-MOSFET power stage |
| Orderable part numbers | RAA489110ARGNP#AA0 (tube) and #HA0 (reel 6k), ambient -10 to +100 °C; RAA489110A3GNP#AA0 and #HA0, ambient -40 to +105 °C (DS p.91 section 12; DS p.11 section 3.3 states +100 °C for the A3GNP ambient maximum) |
| Package | 32 Ld TQFN 4.0 x 4.0 x 0.75 mm, 0.40 mm pitch, one 2.70 x 2.70 mm exposed pad, drawing L32.4x4D Rev04 (DS p.91 and outline page) |
| Evaluation board | RTKA489110DE0000BU (DS p.91; [UG]) |
| Primary read | [DS] in full for sections 1-10 and 12; tables re-read as rendered page images on pp.10-13, 15, 18-20, 30-31, 46, 48 and 63 because the text extraction scrambles them |
| Fetch | `https://www.renesas.com/en/document/dst/raa489110-datasheet`, curl, 2026-11-10; [UG] `https://www.renesas.com/en/document/mah/rtka489110de0000bu-evaluation-board-manual`, 2026-11-10; [DS118] `.../document/dst/raa489118-datasheet`; [DS108] `.../document/dst/raa489108-datasheet`, all 2026-11-10 |
| Secondary sources | Renesas product page `renesas.com/en/products/raa489110`, read through a summarising fetch on 2026-11-10: "Active", RAA489110A3GNP#AA0 USD 4.96 "In stock", RAA489110ARGNP#AA0 USD 4.51 "Out of stock". **UNVERIFIED** (summary of a dynamic page; no quantity) |

The manufacturer ID register reads 0x49 and the device ID register 0x16 (DS p.30 Table 1).

---

## 2. Architecture on the custom board

### 2.1 Topology

The RAA489110 drives a four-switch N-MOSFET buck-boost bridge: Q1/Q2 form the input (buck) leg and Q3/Q4 the output (boost)
leg, with one inductor between them (DS pp.65-66 section 8.1, Fig 38 on p.66). The controller selects buck, buck-boost or
boost from the VADP/VSYS ratio; the buck region starts at about 109-114 % (DS p.66 text; DS p.67 Fig 39, boundaries
"established by characterization and are not production tested"). An N-MOSFET driven by BGATE connects VSYS to the battery;
the battery current sense resistor Rs2 sits between CSOP (VSYS side) and CSON, both upstream of the BFET, and the VBAT pin sits
on the battery side of the BFET (DS p.71 section 8.3.1.2: Turbo mode compares CSON with VBAT across the BFET). The input sense
resistor Rs1 sits between CSIP and CSIN on the input (DS pp.4-6 Fig 2-4, p.67 Fig 40). The optional bypass FETs (BYPSG) and the NGATE FET are not used on the CCB: BYPSRC is
tied to VDDP and NGATE is left open (DS pp.7-8 pin table). This is the "NVDC Only" configuration of DS p.5 Fig 3.

On the CCB the input-to-output ratio is at least 13.18 / 8.484 = 1.55 ([CRIT] section 4.4 with the FC threshold of section 6),
so the bridge always operates in the buck region: Q1/Q2 switch, Q3 is off and Q4 is held on with boot-refresh pulses. A
buck-only population (Q3 and Q4 omitted) is not documented. TODO(verify: Renesas applications, buck-only population of the
RAA489110). The output leg therefore stays on the board and S10 is scored as a two-hot-loop buck-boost.

### 2.2 Placement between VCHG-IN and VCHG

```
VCHG-IN (pad 10, from D-BC-FC / D-BC-RG) -> eFuse (system core) -> Rs1 -> Q1/Q2 -- L -- Q4/Q3 -> VSYS_L (local node)
   VSYS_L -> Rs2 -> Q5 (BFET, BGATE) -> VCHG (pads 18/19, D-BT-SQ VIN) -> D-BT-SQ -> VBT (pack)
DCIN <- OR diodes from VCHG-IN and VSYS_L (DS p.8, p.47 section 7.1);  VBAT pin <- VCHG (Kelvin)
```

**The BFET Q5 is mandatory, and VSYS must not be connected to VCHG directly.** At POR the MaxSystemVoltage register holds
the PROG default (8.384 V for 2 cells, DS p.29 Table 1) and the converter regulates VSYS to it whenever an adapter is present
and BGATE is off (DS p.49 section 7.3.1). With VSYS tied to VCHG this regulation would push current into the pack through
D-BT-SQ out of POR, limited only by the adapter current limit; HR5 would fail. With Q5 present, the N-FET body diode points
from VCHG to VSYS_L, so a regulated VSYS_L cannot reach the pack while BGATE is off. Q5 is also the hard-inhibit element
(section 5).

The VSYS_L node carries no system load on the CCB: only the VSYS capacitors, CSOP and the DCIN OR diode. A parked VSYS_L
with no load is not a stable state in regen mode: section 6.1 shows that it can decay into the VSYS undervoltage fault.

**The [WD] B.5 keep-alive (or an equivalent VCHG bias above 2.7 V) is mandatory on this CCB.** Without it, VCHG has no
parking source: the Q5 body diode conducts only VCHG -> VSYS_L, and D-BT-SQ blocks pack -> VCHG. Section 8.4 gives the
reasons and section 9.2 counts the parts.

### 2.3 What the 22-hole plug-in board carries

| Group | Parts on the CCB |
|---|---|
| Charger | RAA489110, PROG resistor 1370 Ω at 1 % (2 cells, 724 kHz, REFADJ, ACLIM default 0.2 A at 20 mΩ, DS p.48 Table 18). The 0.1 % 931 Ω strap also gives 2 cells and 0.2 A but selects 1050 kHz and PSYS; PSYS has no CCB pad (section 10), so 1370 Ω is the baseline. Compensation (COMPF, COMPR), VDD/VDDP/DCIN/boot capacitors (DS pp.87-88 sections 9.5-9.7) |
| Power stage | Q1-Q4 (four N-MOSFETs, VDS >= 40 V for Q1/Q2 per [UG] p.17 note), Q5 BFET (VDS >= 30 V; gate-charge requirement in section 8.3), one inductor, Rs1 75 mΩ, Rs2 10 mΩ, input and VSYS capacitors |
| Interlock adders | Two series open-drain channels on BATGONE with gate pull-downs, one pull-up to VDD, the 10 kΩ BATGONE series resistor, the keep-alive, and the FC ceiling leg for parity with the BQ25798 (section 9.2) |
| System core (not counted) | eFuse on VCHG-IN, H1/H2/C7 comparators and logic, BQ29200 OVN term, heartbeat monostables, FCC/RGN sensing ([CRIT] section 3.3) |
| Pads | VCHG-IN (10), GND, VCHG (18/19), SDA/SCL, STAT (CMOUT/INT# or ACOK, open-drain to the MB 3.3 V input), MPPTD (P5 arm), THERM ([SPEC] pad table) |

---

## 3. Must-have check

| ID | Result | Value | Citation |
|---|---|---|---|
| M1 common ground | **Pass (P)** | One GND (exposed pad). Rs1 is on the input (CSIP/CSIN, high-side); Rs2 is between VSYS and BAT (CSOP/CSON, high-side); nothing in a return | DS pp.4-6 Fig 2-4, p.7 pin table |
| M2 input rating >= 35 V | **Pass (P)** | CSIP, CSIN, DCIN, BYPSRC abs max +36 V; PHASE1 +36 V (+39 V < 20 ns); BOOT1 VDDP + 36 V; adapter voltage operating 5-30 V; adapter OVP rising 32.5 V min / 33.3 V typ, 2 µs filter. No drop-out at 22.28 V | DS p.10 section 3.1, p.11 section 3.3, p.18 EC, p.63 section 7.6.1 |
| M3 2S CV +-1.0 % | **Pass (P)** | MaxSystemVoltage accuracy ±0.5 % at 8.4 V (both grades) -> 8.358-8.442 V at the 8.400 V code (8 mV LSB). Trickle, fast charge and CV with autonomous end-of-charge available | DS p.12 EC, p.31 Table 2, p.50 section 7.3.3, p.51 section 7.3.4 |
| M4 >= 3.1 A at 8.4 V, <= 2 W | **Pass (C with A parts)** | ChargeCurrentLimit to 6.14 A at Rs2 = 10 mΩ; estimated loss 1.41 W at 18.53 V in, 8.4 V, 3.25 A (section 11) | DS p.31 Table 2; section 11 |
| M5 hard inhibit pin from POR | **Conditional pass (P mechanism, c register-defeatable)** | BATGONE HIGH "forces the BGATE FET to turn off in any circumstances"; BGATE Force Off and BATGONE HIGH have the highest priority, above BGATE Force On and charging enable (Table 22). Two register bits defeat the sole pin: Control4 bit 15 (BATGONE Disable, "1 = Ignore BATGONE input") and Control4 bit 14 (BGATE tristate, which can leave the Q5 gate charged); both POR 0, never-write, read back at every poll (section 5.4). The pin acts on Q5 only, not on the converter (section 5.3). Pin state readable in Information2 bit 12. The BQ25798 has P evidence for M5 through ILIM_HIZ, whose 0.75 V stop level is published (SLUSDV2C p.27); its EN_EXTILIM interaction is B ([B798] section 3, S1-B3). The EN_EXTILIM analogy holds for M5 as well as M7 | DS p.9 pin table, p.37 Table 7, p.45 Table 15, p.71 section 8.3.1.2 and Table 22 |
| M6 fail-safe default | **Pass (P intrinsic, C bias)** | POR: ChargeCurrentLimit 0x0000 and MinSystemVoltage 0x0000, "which disables fast charging and trickle charging"; no non-volatile setting; an open or shorted PROG gives a safe 4.2 V default. BATGONE has an internal 1 µA pull-up (inhibit); the CCB adds a pull-up to VDD | DS p.29 Table 1, p.48 section 7.2, p.50 section 7.3.2, p.15 EC, p.52 section 7.3.6 |
| M7 hardware current ceiling | **Pass (P mechanism, C bounds, c register-defeatable)** | AdapterCurrentLimit1 clamps at 6140 mA at 20 mΩ, that is a 122.8 mV sense full scale that no register value exceeds; with Rs1 = 75 mΩ the ceiling is 1.59-1.69 A. Four register paths defeat or widen it: Control3 bit 5 (input current limit loop disable), Control3 bit 6 (AC and CC feedback gain x0.5), and Control7 bit 3 (PTM) or bits 4 and 3 together (PPS), each of which disables the adapter loop 4-7 ms after entry while Control4 bit 10 holds its POR value 0; PPS also turns BGATE on. All POR 0, never-write. Comparator backstop: adapter way-overcurrent 200-260 mV (2.64-3.50 A at 75 mΩ), auto-retry after 1.3 s or 150 ms (not latched), itself defeatable by Control4 bit 9 | DS p.31 Table 2, p.36 Table 6, p.37 Table 7, p.38 Table 8, pp.54-55 sections 7.3.11-7.3.12, p.18 EC, p.64 section 7.6.7; section 7 |
| M8 runtime input-voltage regulation | **Pass (P range; U accuracy at 19 V; B draw; U parked state)** | VIN register 0x4B, 128 mV LSB, maximum 24.576 V, R/W; regulates "by reducing battery charging current and then system power". The VIN loop sheds system power, so a parked VSYS_L can decay to the VSYS UV fault (section 6.1); the parked state is conditional on the Control9 bits 4:2 setting and bench gate R-B11 | DS p.30 Table 1, p.31 Table 2, p.69 section 8.2.2.1, p.63 section 7.6.5, p.40 Table 10 |
| M9 no cold restart in the regen path | **Conditional pass (U -> B)** | The VIN loop is a regulation loop and re-runs nothing. BATGONE release turns BGATE on through a 15-70 µA charge pump (specified for VBAT > 2.7 V only); no deglitch, soft-start or battery detection is stated for it. Two cold paths exist and must be excluded by configuration: a VSYS UV fault in the parked state (100 ms debounce, 1.3 s retry, ACOK low, section 6.1) and the AdapterCurrentLimit1 reload to 53 mA at every ACOK fall (section 7.3). Adapter re-insertion is cold (about 8 ms to ACOK and about 12 ms to first switching with a voltage on VBAT, Fig 7; 150 ms at first POR with no battery) and is excluded by the always-powered design | DS p.19-20 EC, p.21 Fig 6-7, p.47 section 7.1, p.49, p.63 section 7.6.5; section 8 |
| M10 host interface | **Pass (P; unpowered-pin behaviour U)** | SMBus/I2C 10-400 kHz, VIH 1.5 V min, VIL 0.7 V max, input bias 1 µA, 7-bit address 0x09, 16-bit word registers LO byte first; SCL/SDA abs max 6.5 V | DS p.10, p.20 EC and section 3.5, p.27 section 5.5, p.28 sections 5.6-5.7 |
| M11 charge-current telemetry | **Pass (P)** | 8-bit ADC: charge current 22.2 mA LSB at 10 mΩ, input current, VIN, VSYS, VBAT; 80 µs sample, 400 µs polling for the current and VIN channels | DS p.46 Table 17, p.62 section 7.5.4 |
| M12 runtime current control | **Pass (P)** | AdapterCurrentLimit1 and ChargeCurrentLimit 4 mA LSB at the reference resistors, R/W at any time | DS p.31 Table 2, p.49 section 7.3.2, p.68 section 8.2.1 |
| M13 lifecycle | **Pass (UNVERIFIED)** | "Active" on the product page (secondary). The datasheet carries no NRND notice and was revised in Aug 2026 | Section 1; DS p.91 section 13 |

---

## 4. HR1-HR5 and H1-H12 status

| Req | RAA489110 on the CCB | Basis |
|---|---|---|
| HR1 regen | **U (B)** | Input capability C: 29.4 W at the 18.53 V worst threshold and the 1.589 A ceiling minimum; charge-side 24.4 W at 7.4 V and 27.7 W at 8.4 V with η 0.94 (A). Warm response, BATGONE exit and inhibit latency are not published (section 8). Two further cold paths: the parked-state VSYS UV fault (section 6.1) and the 53 mA ACLIM reload at every ACOK fall (section 7.3); both need configuration and bench gates R-B11, R-B12 |
| HR2 FC | **C charger / sys** | FC ACLIM 0.869-0.932 A gives 1.51-1.62 A at 8.4 V (section 11.3); purge and budget blockers of [EVAL] 3.4 are system-level |
| HR3 loop | **C (conditional)** | Interlock H1/H2/C7 unchanged; PERMIT drives BATGONE, which acts only on Q5. Q5 is the only element that the hard inhibit acts on; the converter keeps switching while inhibited. A Q5 drain-source short (single fault) leaves the converter able to charge the pack with PERMIT LOW (section 5.3). Conditions: the Q5-short detection and response of section 5.3, the two-channel BATGONE pull-down of section 9.2. `CHG_QUAL AND NOT P5` has no function here (section 9) |
| HR4 runaway | **C** | 122.8 mV full-scale clamp (1.59-1.69 A); POR does not charge; PROG ACLIM default 53 mA after every POR (the reload at an ACOK fall without POR is disabled by Control3 bit 14 = 1 for HR1, section 7.3); way-overcurrent comparator 2.64-3.50 A with auto-retry (a hiccup limiter, not a latch). Register paths that defeat the ceiling (Control3 bits 5 and 6, PTM, PPS) are on the never-write list with readback (section 7) |
| HR5 fail-safe | **P intrinsic / C bias, conditional / B latency** | No charge out of POR, no NVM; BATGONE default-inhibit with a VDD pull-up; SMBus watchdog 4.95-175 s as second tier (sections 5, 10). Conditions: readback of Control4 bits 15 and 14 (the sole pin is register-defeatable), the Q5-short closure of section 5.3 and the two-channel pull-down of section 9.2 |
| H1 ground/sense | **P** | Section 3, M1 |
| H2 inhibit | **P mechanism / B latency** | BATGONE -> BGATE off covers fast and trickle charge (trickle is also a BGATE function, DS p.69 section 8.2.4); BGATE sink current P, pin filter U (section 8.3) |
| H3 fail-safe | **P / C** | As HR5 |
| H4 threshold | **P range / U accuracy / B warm and draw** | 128 mV LSB to 24.576 V; accuracy only at 4.096 V (3.98-4.22 V); retention across ACOK loss not stated (section 6) |
| H5 FC | **C** | >= 1.5 A at 8.4 V at the ACLIM minimum with η >= 0.93 (A); CV ±0.5 % meets the H5 wording; termination by firmware from the CC ADC, or the autonomous EOC (60-190 mA settings) |
| H6 ratings | **P** | 36 V abs max, adapter OVP 32.5 V min |
| H7 D-BT-SQ | **B** | The VBAT pin sits on VCHG behind D-BT-SQ; CSOP and CSON sit on VSYS_L upstream of Q5. VCHG parked below MinSystemVoltage enters trickle, and the trickle-to-fast transition can take up to 100 ms (DS p.50 section 7.3.3). Remedy: the [WD] B.5 keep-alive with MinSystemVoltage <= 3.5 V, mandatory on this CCB (section 8.4) |
| H8 inrush | **C** | Datasheet asks for > 15 µF on CSIP (DS p.8, p.90); about 27 µF effective on the CCB gives 0.32 A at 12 mA/µF, plus about 0.01-0.06 A for the VSYS_L charge if switching starts during the ramp (section 12.3) |
| H9 I2C/logic | **P (U unpowered pins)** | Section 10 |
| H10 thermal/mech | **C (A parts) / B** | 1.38-1.47 W estimated stage loss at 3.25 A; IC θJA 38 °C/W (DS p.10) |
| H11 stock | **U** | Product-page summary only (section 13) |
| H12 telemetry | **P / U accuracy** | Section 10 |

---

## 5. Hard inhibit and fail-safe

### 5.1 Inhibit mechanisms

| Mechanism | Type | Effect | Default with the Teensy absent | What its exit re-runs | Latency |
|---|---|---|---|---|---|
| BATGONE HIGH | Pin | BGATE off "in any circumstances"; charging (fast and trickle) stops; converter keeps regulating VSYS_L | Inhibit: internal 1 µA pull-up (DS p.15) plus the CCB pull-up to VDD | Not stated. BGATE turn-on through the 15-70 µA charge pump (DS p.20). Whether BATGONE falling restarts a trickle/fast decision on the 100 ms ADC poll is U | Not published; sink current 165-250 µA (DS p.19); section 8.3 |
| BGATE Force Off (Control1 bit 6) | Register | Same effect as BATGONE HIGH (DS p.71) | POR 0 (normal) | Register write | Not published |
| ChargeCurrentLimit = 0 or MinSystemVoltage = 0 | Register | Disables all charging | POR value 0 (inhibit) | Register write | Not published |
| MaxSystemVoltage = 0 | Register | Stops switching, READY state (DS p.49) | POR = PROG default (switching) | VSYS short check: 10 mA source until CSOP > 0.6 V, then 10 µs (DS p.63 section 7.6.4) | Not published |
| AdapterCurrentLimit1 = 0 | Register | Stops switching, READY state (DS p.68) | POR = PROG default | As above | Not published |
| SMBus timeout | Internal timer | Turns BGATE off if no write to MaxSystemVoltage or ChargeCurrentLimit within 175 / 87.5 / 43.75 / 4.95 s; ChargeCurrentLimit keeps its value | Enabled at POR, 175 s | A write to MaxSystemVoltage or ChargeCurrentLimit | Timer resolution not stated |
| Adapter removal (CSIN below ACOK) | Physical | Switching stops | - | ACOK debounce and start-up; 150 ms at first POR with no battery (DS p.47 section 7.1, p.21 Fig 6); with a battery connected, about 8 ms to ACOK and about 12 ms to first switching after VADP begins to rise (Fig 7, figure reading, typical) | Cold |

The RAA489110 has **one** inhibit pin. It acts on the battery FET, not on the converter. The converter keeps regulating
VSYS_L with no load while BATGONE is HIGH. This differs from the BQ25798, whose ILIM_HIZ < 0.75 V stops switching
([B798] section 3, M5).

### 5.2 Priority and register defeats

Table 22 (DS p.71) and its text give the priority order: BGATE Force Off and BATGONE HIGH first, then BGATE Force On (Control9
bit 15), then charging enable. A stray BGATE Force On therefore cannot override BATGONE HIGH. The only register that defeats
the pin is Control4 bit 15 "BATGONE Disable: 1 = Ignore BATGONE input" (DS p.37 Table 7), POR value 0. Control4 bit 14
(BGATE tristate) does not ignore the pin but releases the BGATE drive, so a charged Q5 gate can hold Q5 on; it is treated as
a second defeat path. M5 is therefore a conditional pass that depends on readback, in the same way as M7. Battery Learn mode
requires BATGONE LOW and exits when BATGONE rises (DS p.53 section 7.3.8). OTG requires BATGONE LOW with BGATE on (DS p.56
section 7.4.1). PPS mode turns BGATE on (DS p.55 section 7.3.12); the pin text "in any circumstances" covers it, but no PPS
statement names BATGONE. TODO(verify: Renesas, BATGONE priority in PPS mode). PPS is on the never-write list.

### 5.3 The BFET as the sole inhibit element, and its single faults

While BGATE is off, the body diode of Q5 blocks VSYS_L -> VCHG. Every forward path from VCHG-IN to the pack then needs Q5 to
conduct. Q5 is not an additional barrier: it is the only element that the hard inhibit acts on, and the converter keeps
switching while BATGONE is HIGH. The BQ25798 differs: its per-burst ILIM_HIZ input stops the converter itself, so a BATFET
fault does not remove its inhibit ([B798] section 9.1).

| Single fault | Effect with BATGONE HIGH (PERMIT LOW) | Detection | Residual |
|---|---|---|---|
| Q1 drain-source short | VSYS_L rises to VCHG-IN (at most 22.28 V; CSOP abs max 24 V, DS p.10); VSYS overvoltage stops switching (DS p.64 section 7.6.6); Q5 body diode blocks; pack isolated | VSYS ADC above MaxSystemVoltage | None while PERMIT is LOW. While PERMIT is HIGH a Q1 short reaches the pack; the eFuse on VCHG-IN stays in the system core ([EVAL] condition 7). Whether BGATE turns off on VSYS OV is not stated. TODO(verify: Renesas, BGATE action on VSYS OV) |
| **Q5 drain-source short** | VSYS_L joins VCHG. With BGATE off the IC "regulates the system bus voltage at the MaxSystemVoltage register setting" (DS p.49 section 7.3.1), that is 8.384 V onto VCHG -> D-BT-SQ -> pack. Charging needs BATGONE LOW (DS p.70 section 8.3.1.1), but VSYS regulation does not; the current is bounded only by AdapterCurrentLimit1 (up to the 1.59-1.69 A ceiling) and by the VIN loop | Charge-current ADC (0x85) non-zero with BATGONE HIGH; requires Control3 bit 0 = 1 so that the ADC runs outside charging (DS p.36 Table 6). Firmware check: any charge current above the ADC noise floor with PERMIT LOW opens REGEN and FC_CHARGE_ENABLE ([EVAL] 2.7 soft-layer fallback, which accepts a fault found within 6 ms; the 400 µs ADC poll fits) | **Regen mode:** VIN 19.072 V is the only barrier at bus level; [EVAL] 2.1 does not accept a threshold as an interlock. **FC mode:** VIN 13.568 V is below the bus, so FC charging continues with PERMIT LOW until firmware opens FC_CHARGE_ENABLE; this violates the FC purge ruling (no FC charging during or just before a purge) for the firmware response time. The eFuse does not trip, because the current stays under its regen-sized limit |
| BATGONE channel short (pull-down stuck ON) | BATGONE held LOW; no hardware inhibit | Information2 bit 12 reads LOW with PERMIT LOW | Closed by the second series channel of section 9.2 |

The Q5-short row keeps HR3 and HR5 conditional. Two closures exist. (1) The firmware detection above, which leaves the
firmware response time as an exposure. (2) A converter-stop path keyed to the static arm, for example the eFuse EN driven from
P5, so that a disarmed system removes VCHG-IN from the converter; this adds about 2 parts (section 9.2) and does not cover a
Q5 short inside an armed window between bursts. TODO(verify: system core, eFuse EN keyed to P5 against the always-powered
regen design of [EVAL] 0.2).

### 5.4 How HR5 is made fail-safe on the CCB

1. **POR.** No charge until the host writes non-zero ChargeCurrentLimit and MinSystemVoltage (DS p.50). No OTP, EEPROM or
   stored image exists in the register description. VDD below 2.5 V resets every register (DS p.8 VDD pin text).
2. **Teensy unpowered, in reset or hung.** The PERMIT network (system core) drives two open-drain channels in series that
   pull BATGONE LOW only while PERMIT is HIGH; each discrete channel has a gate pull-down, so it is off with its logic
   unpowered, and one shorted channel does not remove the inhibit (section 9.2). The BATGONE node is pulled to VDD (5 V, the charger's own LDO, DS p.11) by a resistor, so
   absent logic, an unpowered logic rail or a low PERMIT leaves BATGONE HIGH. VIH is VDD - 0.6 V min and VIL VDD - 1.2 V max
   (DS p.15). This replaces the REGN-biased /CE and ILIM_HIZ stages of [WD] B.6.
3. **I2C dead or hung host.** The SMBus timeout, set to 4.95 s (Control3 bits 12:11 = 11, DS p.36 Table 6), turns BGATE off.
   It is the second tier behind the MCU watchdog ([EVAL] 2.6). The timer is kicked by any write to ChargeCurrentLimit or
   MaxSystemVoltage, so the firmware rewrites the same ChargeCurrentLimit value at <= 2 s.
4. **Never-write list with readback** (each bit POR 0 unless stated):
   - Control0 (0x39): bit 9 bypass transition, bit 2 VIN loop disable, bit 7 SMBus timeout disable, bit 0 reverse turbo
     boost (DS pp.32-33 Table 3);
   - Control1 (0x3C): bit 11 OTG, bit 12 learn mode, bit 2 digital OV disable (DS pp.33-34 Table 4);
   - Control3 (0x4C, POR 0x0300): bit 7 autonomous charging, bit 6 feedback gain x0.5, bit 5 input current limit loop
     disable, bit 4 ACLIM disable when BATGONE = 1, bit 2 digital reset (DS p.36 Table 6);
   - Control4 (0x4E): bit 15 BATGONE disable, bit 14 BGATE tristate, bit 9 WOCP disable (DS p.37 Table 7);
   - Control7 (0x38): bit 7 analog OV disable, bits 4/3 PPS and PTM (each disables the adapter current loop 4-7 ms after
     entry, and PPS also turns BGATE on, DS pp.54-55 sections 7.3.11-7.3.12), bit 2 standby (DS p.38 Table 8);
   - Control8 (0x44) bits 15:13 supplemental mode; Control9 (0x45) bit 15 BGATE Force On (DS p.39 Tables 9-10);
   - read back with the list, because they set how the PTM/PPS defeat behaves: Control0 bit 8 (PPS overcurrent exit
     CCHOT_DB active only when 1, DS p.55) and Control4 bit 10 (adapter loop kept in PTM when 1, DS p.37 Table 7);
   - Control2 bit 11 stays 0 (1.3 s fault retry, the longer off-time, DS p.34 Table 5).
5. **Mandatory configuration image, written after every POR and every VCHG-IN loss and read back** (POR values differ):
   - Control0 bit 6 = 1, BGATE and NGATE charge pumps at 100 % duty (POR 0 = reduced duty; DS p.32 Table 3, p.44 Table 14
     note 1), so that the BGATE on-current applies continuously;
   - Control3 bit 0 = 1, ADC active in all modes (DS p.36 Table 6), for the Q5-short check of section 5.3 and a fresh VBAT
     sample at BATGONE release;
   - Control9 bits 4:2, VSYS UV threshold: 000 (disable) or a value below the parked VSYS_L (section 6.1; POR 011 = 4.8 V,
     DS p.40 Table 10);
   - AdapterCurrentLimit1 after every ACOK rise, or Control3 bit 14 = 1 (no reload) as decided in section 7.3;
   - SMBus timeout 4.95 s (Control3 bits 12:11 = 11), item 3.
6. **OTG hardware block.** With the general-purpose comparator disabled (Control2 bit 3 = 1), OTG needs both the register bit
   and the OTGEN pin (DS p.56 section 7.4.1); OTGEN/CMIN tied to GND then blocks OTG in hardware. With Control2 bit 3 at its
   POR value 0, OTG follows the register bit alone. The RT1987 D-BC-RG/D-BC-FC reverse blocking remains the physical barrier
   ([EVAL] 2.4).

---

## 6. Input-voltage regulation and POR behaviour

| Item | Value | Citation |
|---|---|---|
| Register | VIN Voltage 0x4B, bits 13:6, 128 mV LSB, maximum 24.576 V (clamped). Table 1 states "6" bits in the bit-count column and "8-bit" in the description; Table 2 lists eight weights (128 mV to 16 384 mV) with the 24.576 V maximum | DS p.30 Table 1, p.31 Table 2 |
| POR value | 0x0800 = 4.096 V, below the 7.4-8.4 V pack | DS p.30 Table 1 |
| Accuracy | 3.98-4.22 V at the 4.096 V code (-2.8 % / +3.0 %); no figure at 13-20 V. TODO(verify: Renesas, VIN loop accuracy at 19 V) | DS p.13 EC |
| Regen setting | 19.072 V (code 149). With the relative error of the 4.096 V row: 18.53-19.65 V; with an absolute error of ±0.12 V: 18.95-19.19 V | C, from DS p.13 |
| FC setting | 13.568 V (code 106): 13.18-13.98 V (relative error) | C |
| Loop disable | Control0 bit 2 = 1 disables the loop (never-write) | DS p.33 Table 3 |
| What resets it | VDD < 2.5 V (all registers), Control3 bit 2 digital reset. ACOK falling reloads AdapterCurrentLimit1 from PROG (Control3 bit 14 = 0) and battery-only mode resets MaxSystemVoltage to the PROG default when PSYS is disabled; neither statement names 0x4B. TODO(verify: Renesas, 0x4B retention across an ACOK fall with VDD held) | DS p.8, p.35 Table 6, p.49 section 7.2 |
| Autonomous charging at POR | None: ChargeCurrentLimit and MinSystemVoltage are 0; Control3 bit 7 (autonomous) POR 0 | DS p.29, p.36 |
| Input draw below the threshold | IQ1 2.25 mA typ / 2.35 mA max "VSYS state, no switching" at VADP 28 V; switching draw at no load not specified -> B (S1-B1 equivalent) | DS p.12 EC |

The POR threshold of 4.096 V places the part in the class that [EVAL] 2.1 describes: the threshold is a soft layer valid only
after a host write and readback. Unlike the BQ25798, whose VINDPM is re-measured at plug-in ([EVAL] 1.3), the RAA489110 does
not re-measure; a host-written value is lost only on a register reset, or possibly on an ACOK fall (TODO above). Because the
POR also leaves charging disabled, a charger POR inside a regen or FC window cannot draw charge power; it can only run the
no-load VSYS_L regulation (section 7.3), subject to the VSYS UV behaviour of section 6.1.

### 6.1 The parked regen state and the VSYS undervoltage fault

In Run the regen state parks VCHG-IN at bus level (about 16 V) below the 19.072 V VIN setting. The VIN loop then acts "by
reducing battery charging current and then system power", and "the system voltage may start to drop if the input power is
not high enough" (DS p.69 section 8.2.2.1). The VIN loop therefore does not hold VSYS_L up in the parked state; VSYS_L decays
at a rate set by its leakage and pin bias, which the datasheet does not give. When CSOP falls to the VSYS UV threshold
(Control9 bits 4:2, POR 011 = 4.8 V, DS p.40 Table 10), the IC waits a 100 ms debounce, enters FAULT, stops switching, retries
after 1.3 s and asserts ACOK low (DS p.63 section 7.6.5). The ACOK fall reloads AdapterCurrentLimit1 to the 53 mA PROG value
(DS p.49; section 7.3). A burst that arrives in FAULT, or after the reload, is cold or capped at about 53 mA x 18.5 V = 1 W.

With the mandatory keep-alive, VSYS_L is held through the Q5 body diode at about VCHG - 0.5 V = 3.1-3.9 V (A, body-diode drop),
which is below the 4.8 V default. The fault condition is therefore reached and stays. The configuration image of section 5.4
item 5 sets Control9 bits 4:2 to 000 (disable) or to 001 (3 V) only if the parked VSYS_L is shown to stay above it; a charger
POR restores the 4.8 V default, so the image is rewritten after every POR. Disabling VSYS UV removes the short-circuit role of
the function; WOCP (section 7.2) and the eFuse remain. This item keeps M8 and M9 conditional (U -> B) until bench gate R-B11
shows a 60 s park with no FAULT entry and no ACLIM reload.

---

## 7. Hardware input-current ceiling after POR (HR4)

### 7.1 Mechanism

The adapter current loop limits CSIP - CSIN (DS p.68 section 8.2.1). Any register value above the maximum is clamped at 6140 mA
at Rs1 = 20 mΩ (DS p.31 Table 2), that is 122.8 mV. The sense resistor therefore sets an IC-intrinsic ceiling that applies from
POR and that no AdapterCurrentLimit write raises. Four register paths defeat or widen it:

- Control3 bit 5 disables the loop (DS p.36 Table 6);
- Control3 bit 6 halves the AC and CC feedback gain (DS p.36 Table 6). This dossier reads bit 6 as doubling the regulated
  current per register code, from the PSYS gain definition (H = 0.5 when bit 6 = 1, DS p.61 EQ. 2). TODO(verify: Renesas,
  Control3 bit 6 effect on the regulated current);
- Control7 bit 3 (Pass-Through Mode) disables the adapter current loop 4-7 ms after PTM entry while Control4 bit 10 holds its
  POR value 0 (DS p.54 section 7.3.11, p.37 Table 7, p.38 Table 8);
- Control7 bits 4 and 3 together (PPS) do the same and also turn BGATE on, so the pack connects to a VSYS that follows VADP
  with no adapter-current loop; the PPS overcurrent exit CCHOT_DB is active only when Control0 bit 8 = 1 (DS p.55 section
  7.3.12).

All four are POR 0 and on the never-write list with readback (section 5.4).

### 7.2 Regen-mode value (C)

With Rs1 = 75 mΩ (1 %, A) and the ±2 % accuracy of the 100 mV row applied at 122.8 mV (an extrapolation; the EC table stops at
100 mV, DS p.12):

- nominal 122.8 / 75 = **1.637 A**;
- minimum 0.98 x 122.8 / (75 x 1.01) = **1.589 A**;
- maximum 1.02 x 122.8 / (75 x 0.99) = **1.687 A** (below the 1.72 A maximum of the BQ25798 regen leg, [EVAL] 2.5);
- with Control3 bit 6 set by a stray write: 3.27 A nominal;
- way-overcurrent comparator, 10-13 A at 20 mΩ (DS p.18) = 200-260 mV: **2.64-3.50 A** at 75 mΩ, switching stops after
  seven 10 µs counts within 50 ms, then the IC retries the start-up sequence after 1.3 s (Control2 bit 11 = 0, POR) or 150 ms
  (bit 11 = 1) (DS p.64 section 7.6.7, p.34 Table 5). WOCP is not latched: a sustained fault draws repetitive bursts, so it is
  a hiccup limiter. Control2 bit 11 stays 0 (the longer off-time) and is read back. The same 1.3 s retry applies to OTP and
  VSYS UV (DS p.63-64).

The register LSB scales to 4 mA x 20/75 = 1.07 mA. Rs1 dissipates 1.637² x 0.075 = 0.20 W at the ceiling.

### 7.3 After a charger POR

After a POR, and after an ACOK fall while Control3 bit 14 = 0, AdapterCurrentLimit1 reloads from PROG (DS p.68, p.49). The
0.2 A strap (1370 Ω at 1 %, or 931 Ω at 0.1 %, DS p.48 Table 18) gives 4 mV, that is **53 mA** at 75 mΩ; accuracy at 4 mV is not specified (±16 % at 5 mV,
DS p.12). ChargeCurrentLimit and MinSystemVoltage are 0, so the converter only regulates VSYS_L with no load. The FC-window
bound after a POR is therefore met intrinsically: bus load <= 0.053 A + 0.15 A aux plus the no-load switching draw. The
BQ25798 needed the mode-switched ILIM divider for the same bound because its POR charges at 1 A ([EVAL] 0.2 condition 5).

The reload is also an HR1 hazard. ChargeCurrentLimit and MinSystemVoltage persist across an ACOK fall while VDD holds, but
AdapterCurrentLimit1 drops to 53 mA at every ACOK fall: at each FC-window boundary that removes VCHG-IN, and at each VSYS UV
fault (section 6.1). Unless firmware rewrites it, the next regen burst is capped at about 53 mA x 18.5 V = 1 W and HR1 fails
without an alarm. Two dispositions exist:

- firmware rewrites AdapterCurrentLimit1 after every ACOK rise and reads it back (one extra write and read per VCHG-IN
  return, counted in section 14 against R6 findings 8 and 12);
- Control3 bit 14 = 1 (no reload, DS p.35 Table 6). The post-POR bound still holds, because a POR resets the register to the
  PROG value and ChargeCurrentLimit to 0; only the reload at an ACOK fall without POR is lost.

The dossier prefers the second, with the first as the readback check. Bench gate R-B12 reads 0x3F after every FC-window close.

### 7.4 FC mode

A single Rs1 cannot give both the 1.59-1.69 A regen ceiling and a 0.74-0.96 A FC ceiling. In an FC window the register value
holds the FC limit: 0.90 A -> 67.5 mV, ±2.5 % (60 mV row) and Rs1 1 % -> **0.869-0.932 A**, bus load <= 1.08 A with aux,
below the 1.247 A H-20 P_MAX and the 1.4 A OC_FC latch. A stray register write inside an FC window can raise the input to the
1.69 A hardware ceiling, which exceeds OC_FC; the firmware raw I_fc > 1.20 A arm drop and OC_FC then act ([EVAL] 3.4). The
BQ25798 build has a hardware FC ceiling against stray writes (its mode-switched ILIM divider). The only equivalent here is a
mode-switched current limit on the CCB eFuse (one resistor, one NMOS keyed to FCC_net and its gate pull-up), which is a trip,
not a regulated ceiling. Section 9.2 counts it in every build scored against the BQ25798.

---

## 8. Warm response and HIZ-exit timing

### 8.1 What the datasheet gives

| Item | Datasheet content | Status |
|---|---|---|
| Converter state below the threshold | Stays in the VSYS state; the VIN loop reduces charge current, then system power (DS p.69 section 8.2.2.1; Information1 bits 14:13 report the active loop, DS p.44) | P |
| VIN-loop dynamics | Fig 19-20 (DS p.23): output-voltage and charge-current loops to/from the input-voltage loop, boost mode, VADP 5 V, 0.5 -> 8 A system steps, 400 µs/div; IBAT recovers within about one division (figure reading, typical, boost mode at 5 V, not buck mode at 19 V). Buck-mode adapter-current transitions at 20 V and 28 V settle within about 0.4-0.8 ms (Fig 15-18, p.23, figure reading, typical) | B |
| Modulator | R3 modulator; "higher control loop bandwidth than conventional fixed frequency PWM" (DS p.82 section 8.4); no bandwidth figure | U |
| BATGONE exit | BGATE on-current 15 / 40 / 70 µA min / typ / max at VGS = 2 V, specified for VVBAT > 2.7 V only (DS p.20); the EC row does not state whether it applies at the POR reduced charge-pump duty (Control0 bit 6 = 0, DS p.32 Table 3); no pin filter, deglitch or detection step stated | U -> B |
| Compensation | COMPF internal resistor "faster" (default) or "slower" (Control2 bit 0, DS p.35) | P |

### 8.2 The per-burst sequence in regen mode

1. VCHG-IN is held at bus level through D-BC-RG in Run (always-powered, [EVAL] 0.2). BATGONE is HIGH (no PERMIT). The
   converter does not regulate VSYS_L in this state: VCHG-IN is below the VIN setting, the VIN loop sheds system power, and
   VSYS_L decays toward the keep-alive level, at which the Q5 body diode holds it. The state is warm only if the VSYS UV fault is configured
   out (section 6.1) and the ACLIM reload is disabled (section 7.3). Bench gate R-B11.
2. V-MOT rises; H1 permits at 17.1-17.9 V ([EVAL] 2.2), which leaves **1.8-11.6 ms** before V-MOT reaches the threshold
   ([EVAL] 3.2). PERMIT pulls BATGONE LOW.
3. BGATE turns Q5 on. With VCHG above 2.7 V (keep-alive fitted) and Control0 bit 6 = 1, for an 8 nC Q5 gate charge (the
   section 8.3 requirement): 8 nC / 15 µA = **0.53 ms** worst, 0.20 ms typical. This completes inside the minimum 1.8 ms head
   start if the pin has no filter longer than about 1.2 ms. At 15 nC the worst case is 1.0 ms. Below VCHG = 2.7 V the BGATE
   drive is not specified (DS p.20), which is a further reason for the mandatory keep-alive.
4. With Q5 on and VCHG-IN below the VIN setting, the VIN loop holds the charge current near zero.
5. V-MOT crosses the threshold; the VIN loop releases and the charge-current loop takes over. This step is the warm response
   that [EVAL] 3.2 requires (τ_warm <= 4 ms, 10-90 % <= 9 ms; <= 2 ms at board-only capacitance). No primary figure covers it.

The open risk in step 3 is behavioural: if BATGONE falling is treated as a battery insertion that waits for the next 100 ms
ADC poll before the trickle/fast decision (DS p.50 section 7.3.3), the exit is cold for this application. Bench gate R-B2.

### 8.3 Hard-stop latency (H1 trip to input-current stop, <= about 115 µs)

| Stage | Estimate | Status |
|---|---|---|
| H1 + PERMIT logic | <= 15 µs comparator + gate delay ([EVAL] 2.5 allowance) | system |
| BATGONE node rise | 47 kΩ pull-up (A) x about 20 pF = 0.9 µs time constant, about 2 µs to VDD - 0.6 V | C |
| BATGONE detection filter | Not published | U |
| BGATE turn-off to the Miller plateau | 4.5-8 nC (Q5 requirement below) / 165-250 µA = **18-48 µs**; at 15 nC, 60-91 µs | B (part not selected) |
| Converter response | Q5 opening forces the output current into the VSYS_L capacitors; VSYS OV (8.9-9.35 V at an 8.4 V setting, DS p.18) stops switching after 25 µF (A) x 0.5-0.95 V / 3.4 A = **3.7-7.0 µs**; switching resumes without debounce 400 mV below the OV threshold, at no load (DS p.64 section 7.6.6) | C |
| Total including the 15 µs H1 allowance, excluding the BATGONE filter | about 39-72 µs at Qg 4.5-8 nC; about 81-115 µs at 15 nC, whose worst case uses the whole 115 µs allowance | B |

**Q5 selection requirement.** Both the turn-on time of section 8.2 and the turn-off time above scale linearly with the Q5
gate charge, because BGATE is pumped to VBAT + 5 V (DS p.9) by fixed currents. The CCB requires Qg at VGS = 5 V <= 8 nC
together with RDS(on) <= 5 mΩ (the loss-model value of section 11.2). No part has been checked against both limits; the
reference board's BFET SIRA10BDP was not read. TODO(verify: a Q5 candidate's primary datasheet, Qg at 5 V and RDS(on)). If no
part meets both, section 11.2 is recomputed with the higher RDS(on) of a low-Qg part. The latency rows stay B until then.

The datasheet layout table asks for "the capacitor from BGATE to ground close to the MOSFET" (DS p.90, pin 32) without a value.
A BGATE capacitor adds 5 V x C of charge to remove: 1 nF adds 20-30 µs, 10 nF adds 200-300 µs and fails the 115 µs budget.
The evaluation board BOM does not list C38 at the BGATE net ([UG] pp.18-19), so it appears unpopulated there. TODO(verify:
R16UZ0064EU0102 schematic p.17, C38 population). The CCB leaves this capacitor unpopulated or <= 1 nF.

### 8.4 Interaction with D-BT-SQ (H7)

The VBAT pin sits on VCHG, which D-BT-SQ isolates from the pack whenever the charger output is below VBT; CSOP and CSON sit on
VSYS_L upstream of Q5, so the charge-current sense also sees the VSYS_L capacitor current at Q5 turn-on. If VCHG parks below
MinSystemVoltage, a charge start enters trickle mode (BGATE in linear control at the Control2 trickle current, VSYS at
MinSystemVoltage + 384 mV) and the transition to fast charge "can take up to 100 ms (ADC polling time)" (DS p.50).

**VCHG has no parking source without a keep-alive.** The Q5 body diode conducts only VCHG -> VSYS_L, so the regulated VSYS_L
cannot hold VCHG up, and D-BT-SQ blocks pack -> VCHG. VCHG therefore decays to near 0 V through leakage. A MinSystemVoltage
below a parked 0 V cannot be set: the smallest non-zero value is 64 mV, and 0x0000 "disables all battery charging" (DS p.50,
p.31). The trickle/fast decision also uses the VBAT ADC sample, polled every 100 ms (DS p.46 Table 17) and, at POR, taken
only while charging (Control3 bit 0 = 0, DS p.36 Table 6), so the sample at BATGONE release is stale. The BGATE on-current
is specified only for VBAT > 2.7 V (DS p.20), so the Q5 turn-on from a VCHG near 0 V is not specified.

The only valid disposition is therefore the [WD] B.5 keep-alive (VCHG held at 3.63-4.46 V with R_KA alone; minimum 3.58 V
with the T18 fuse and series resistor, [WD] T18 row and H.20) with MinSystemVoltage <= 3.5 V and Control3 bit 0 = 1. The
keep-alive is a condition of the verdict and is counted in S6 ([CRIT] section 3.3).

Register retention across a VCHG-IN loss is U. The low-power LDO (nominal 4.5 V) takes its input from an internal OR of VBAT
and CSIN (DS p.47 section 7.1), so with the keep-alive the LDO input is VBAT = VCHG = 3.58-4.46 V directly, not the DCIN
chain. VDD stays above the VDD_2P7 falling maximum of 2.9 V (DS p.11) only if the LDO dropout at 3.58 V is below 0.68 V; the
datasheet publishes no low-power LDO dropout (the VDD dropout row applies to the high-power LDO from DCIN at 4 V). Retention
is expected, not proven. Bench gate R-B9 decides it, and the firmware rewrites the full configuration image of section 5.4
after every VCHG-IN loss whatever the result. Bench gate R-B3 extends to a start from VCHG = 0 V to record whether Q5 turns
on at all.

---

## 9. Interlock hardware needed around it, versus the BQ25798 design

### 9.1 Function by function

| Function ([CRIT] 3.3, [EVAL] 2.6) | BQ25798 ([B798] section 9.1) | RAA489110 | IC-specific adder on the CCB |
|---|---|---|---|
| Per-burst hardware stop from GATE | ILIM_HIZ hold-down NMOS, open-drain release, release feed; stops the converter | BATGONE, open-drain pull-down; opens Q5 only, the converter keeps switching (section 5.3) | One open-drain channel (a channel of the PERMIT driver package or one 2N7002K) with a gate pull-down if discrete, one pull-up to VDD, the 10 kΩ series resistor (DS p.9, p.90): 3-4 |
| Static arm, fail-safe | /CE with REGN pull-up and open-drain channel; no register defeats /CE | Merged: PERMIT = P5 AND GATE already contains the arm; one pin carries both, and Control4 bits 15 and 14 can defeat it | 0 |
| Single-fault redundancy of the inhibit | Parity build: release PMOS, far-end readback (about 7 parts over the minimal set) | A shorted pull-down channel leaves BATGONE LOW with no second hardware inhibit; a second channel in series closes it; Information2 bit 12 gives readback over I2C | 1-2 (second channel and its gate pull-down) |
| Converter stop for a Q5 short | Not needed: ILIM_HIZ stops the converter | Firmware detection (section 5.3) or eFuse EN keyed to P5 | 0, or about 2 with the eFuse EN path |
| `CHG_QUAL AND NOT P5` | Needed: the ADC samples ILIM_HIZ during input qualification | No input-qualification read of a ceiling pin exists; the ceiling is the Rs1 full scale | 0 (removes U111 QQ one-shot, the 1G04 and 1G08 and the QUAL input) |
| Mode-switched ceiling keyed to FCC_net | ILIM divider leg: NMOS, R_FC, gate pull-up; a regulated ceiling | Not needed for the post-POR bound (section 7.3). Against stray writes in an FC window, only an eFuse ILIM leg exists; an eFuse current limit is a trip, not a regulated ceiling, so it is not functionally equal to the BQ25798 divider | 3 for parity |
| D-BT-SQ disposition | Keep-alive DNP option (+3) | Keep-alive mandatory (section 8.4) | 3 |
| Pin-level readback | Far-end readback of /CE and ILIM_HIZ (parity build, about 4 parts) | Information2 bit 12 reports the BATGONE pin over I2C (DS p.45) | 0 |
| eFuse on VCHG-IN | System core | System core; still needed (section 5.3) | Not counted |
| REGN-biased pull-ups | REGN | VDD (5 V LDO, 90 mA min OC, DS p.11) | Counted above |
| BQ29200 OVN term | System core (R6 finding 1) | System core | Not counted |

### 9.2 Part count

| Build | Adder parts | Notes |
|---|---|---|
| Bare BATGONE network (not a scored build) | 3-4: open-drain channel (gate pull-down if discrete), pull-up to VDD, 10 kΩ series | Gives neither the FC stray-write ceiling, the keep-alive nor single-fault redundancy |
| **CCB, equal function to the BQ25798 minimal build** (FC ceiling leg, mandatory keep-alive) | **about 10**: bare network 4 + keep-alive 3 + FC eFuse leg 3 | S6 = 0 (> 8) |
| CCB, equal function to the BQ25798 single-fault-parity build | about 11-14: the above + second series channel 1-2 + eFuse EN path for a Q5 short about 2 | S6 = 0 |
| BQ25798, CCB minimal / parity ([B798] 9.2) | 9 / about 16 | S6 = 0 |

Counted like-for-like, the RAA489110 needs about as many adder parts as the BQ25798. The earlier count of 3 compared a
build without the FC ceiling, the keep-alive and single-fault redundancy against a BQ25798 build that has the first and
offers the others; it is withdrawn.

The THERM pad (pack NTC to MB GND, [SPEC] pad 13) cannot sit in series with the permit pull-down because its low end is MB
GND. The baseline leaves the NTC function of BATGONE/NTC unused. The network topology is fixed so that the VDD pull-up
connects at the far (channel) end of the 10 kΩ series resistor. With the permit channel on, the pin then sees the NTC
step current into 10 kΩ only: the guaranteed step currents are 62-68, 126-134 and 250-270 µA (DS p.15), so the pin reads
0.62-2.70 V, against VIL max = VDD - 1.2 V = 3.30 V at VDD(min) 4.5 V (DS p.11, p.15): a margin of 0.60 V. If the pull-up
connected at the pin side (47 kΩ, A), the worst case would be 4.5 V x 10/57 + 270 µA x 8.25 kΩ = 3.02 V, a margin of only
0.28 V; that topology is not used. The 10 kΩ reads about 25 °C to the NTC sampler. The programmable temperature profile
stays disabled (Control10 bit 0 POR 0, DS p.41). Whether the NTC sampling acts on charging with the profile disabled is not
stated. TODO(verify: Renesas, NTC action with Control10 bit 0 = 0).

---

## 10. Telemetry and I2C

| Item | Value | Citation |
|---|---|---|
| Logic levels | VIH 1.5 V min, VIL 0.7 V max; compatible with 3.3 V pull-ups ("pull-up power supply higher than 1.5V") | DS p.20, p.28 section 5.6 |
| Speed | 10-400 kHz; Teensy 100 kHz is inside the range | DS p.20 section 3.5 |
| Address | 7-bit 0x09 (write 0x12, read 0x13); 0x92/0x94/0x96 write addresses on request with other part numbers | DS p.28 section 5.7 |
| Word format | 16-bit registers, LO byte first; an 8-bit I2C master needs auto-increment | DS p.27 Fig 32, p.28 section 5.6 |
| Unpowered behaviour | SCL/SDA abs max 6.5 V; clamping to VDD when unpowered not stated | U |
| ADC channels at the CCB resistors (Rs1 75 mΩ, Rs2 10 mΩ) | Charge current 0x85: 22.2 mA LSB, 0-5.68 A. Input current 0x83: 22.2 mA x 20/75 = 5.92 mA LSB, full scale 113.6 mV = **1.515 A** (saturates below the 1.59 A ceiling minimum). VIN 0x87: 144 mV LSB, 0-36.72 V. VSYS 0x86: 96 mV. VBAT 0x81: 64 mV. Die temperature 0x82. Discharge current 0x84 | DS p.46 Table 17 |
| Conversion | 80 µs sample window; 400 µs polling for the current, VSYS and VIN channels; 100 ms for VBAT, NTC and TJ | DS p.46 Table 17, p.63 Fig 35 |
| ADC accuracy | Not published (8-bit SAR) | U |
| ADC enable | Active by default only while the adapter is present and charging; Control3 bit 0 = 1 enables it in all modes (needed for the parked-state power-balance cross-check) | DS p.36 Table 6, p.62 section 7.5.4 |
| Watchdog | SMBus inactivity timeout, 175 s default, 4.95 s minimum option; turns BGATE off; kicked by ChargeCurrentLimit or MaxSystemVoltage writes | DS p.20, p.36, p.51 section 7.3.5 |
| Status pin for pad 3 (STAT) | CMOUT/INT# (open-drain, interrupt on 13 events incl. SMBus timeout, ADP OV, switching-FET fault) or ACOK | DS pp.42-43 Table 13 |
| Analog monitors | AMON/BMON (18x / 36x) and PSYS exist, but no free CCB pad reaches a Teensy analog input | DS p.9, p.60 section 7.5.1 |

The charge-current LSB of 22.2 mA is 22 times coarser than the BQ25798 IBAT ADC (1 mA, [B798] section 3, M11). The polling is
15 times faster (400 µs against 6 ms per channel).

---

## 11. Charge capability

### 11.1 Charge-current setting

ChargeCurrentLimit 3.248 A (code 812, 4 mA LSB): accuracy ±3.5 % at 30 mV (DS p.13; 32.5 mV here, 0-60 °C) with Rs2 1 % gives
3.248 x 0.965 / 1.01 = **3.103 A** minimum and 3.248 x 1.035 / 0.99 = 3.396 A maximum. The 3.1 A requirement holds at the minimum.
At the regen ceiling minimum the charge-side limit is 1.589 A x 18.53 V x 0.94 / 8.4 V = 3.30 A, so the input ceiling does not
bind below 3.1 A.

### 11.2 Efficiency and loss (C with A parts)

The datasheet gives no buck-mode efficiency curve at 16-19 V in and 8.4 V out; Fig 25-26 (DS p.24) cover boost and
buck-boost only (buck-boost 18 V -> 18.24 V about 98 %, figure reading, typical). The loss model of `calc/raa_calc.py` uses
724 kHz, the PROG default of the 1370 Ω strap (DS p.48 Table 18; with the 931 Ω strap the default is 1050 kHz unless Control1
bits 9:7 are written to 101 after POR, DS p.33 Table 4), Q1 8 mΩ / 8 nC, Q2 5 mΩ / 12 nC, Q4 and Q5 5 mΩ, inductor DCR 12 mΩ and 0.10 W core loss, 2 x 8 ns
transitions, 20 ns dead time at 0.7 V, gate drive through the VDD LDO from VIN, and IQ 2.35 mA (all A except IQ, DS p.12):

| VIN | Output | Loss | η | Input current |
|---|---|---|---|---|
| 18.53 V | 8.4 V, 3.25 A | 1.41 W | 95.1 % | 1.549 A |
| 18.53 V | 7.4 V, 3.25 A | 1.37 W | 94.6 % | 1.372 A |
| 21.50 V | 8.4 V, 3.25 A | 1.47 W | 94.9 % | 1.338 A |
| 15.57 V | 8.4 V, 1.60 A | 0.70 W | 95.1 % | 0.908 A |

The largest terms at 18.53 V are Q1 switching (0.35 W), gate drive dissipated in the VDD LDO (0.27 W) and Rs1 (0.18 W). The
loss stays below the 2 W limit of M4. The hard-loss figures in section 11.3 use η = 0.94 to cover part selection.

At 1050 kHz (931 Ω strap without the Control1 write) the same model gives 1.72 W (η 94.1 %) at 18.53 V / 8.4 V, 1.68 W
(93.5 %) at 18.53 V / 7.4 V, 1.83 W (93.7 %) at 21.50 V / 8.4 V and 0.88 W (93.8 %) in the FC case, still below 2 W. The
7.4 V case falls below the η = 0.94 of section 11.3; the 24.4 W row would become 24.6 W, which still meets 23 W. The 1370 Ω
strap avoids the question.

### 11.3 Regen input power at the threshold and FC mode

| Case | Calculation | Result |
|---|---|---|
| Input capability at the worst threshold | 1.589 A x 18.53 V | **29.4 W** >= 23 W (C) |
| Charge-limited input, 7.4 V pack | 3.103 A x 7.4 V / 0.94 | **24.4 W** >= 23 W (C, η A) |
| Charge-limited input, 8.4 V pack | 3.103 A x 8.4 V / 0.94 | 27.7 W |
| Peak of the defining 3 -> 1 m/s brake | [EVAL] 3.2 | 18.9 W, covered |
| FC charge, 8.4 V, loaded bus 15.57 V | 0.869-0.932 A x 15.57 V x 0.94 / 8.4 V | **1.51-1.62 A** (H5 >= 1.5 A holds at η >= 0.93) |
| FC charge, 7.4 V | same input / 7.4 V | 1.72-1.84 A, capped by the 1.60 A ChargeCurrentLimit |
| FC bus load | 0.932 A + 0.15 A aux | 1.08 A < 1.247 A P_MAX, < 1.4 A OC_FC |

Unlike the BQ25798 (2.87-2.91 A at an 8.4 V pack at the regen threshold floor, [B798] section 4), the RAA489110 reaches the full
3.1 A at the regen threshold, because the 75 mΩ ceiling sits above the charge-side input demand.

---

## 12. Layout, package, thermal, BOM estimate

### 12.1 Layout

The power stage has five N-MOSFETs and two hot loops (input capacitor - Q1 - Q2, and output capacitor - Q4 - Q3); the output
loop carries only DC in buck mode but must still be laid out for start-up transients in the buck-boost region. The datasheet
layout table (DS pp.88-90 section 10) asks for: five or more vias under the exposed pad; IC near the gate terminals; input and
output capacitors on the MOSFET layer; minimum phase-node area; Kelvin pairs from Rs1 and Rs2 routed from the pad centres;
CSOP as a short plane from Q4 drain; PHASE traces to the high-side source pins. The reference board uses four inner layers
([UG] p.21 Fig 14-17), PowerPAK SO-8 and 1212 FETs (SIRA74DP 40 V for Q1/Q2, SISA14DN for Q3/Q4, SIRA10BDP 30 V for the BFET)
and a 13 x 13 mm 2.2 µH 19 A inductor sized for 140 W ([UG] pp.17-19). A 30 W CCB can use 3 x 3 mm FETs and a 5 x 5 mm to
7 x 7 mm inductor (A). TODO(verify: inductor and FET part selection, saturation at the 3.5 A WOCP maximum).

### 12.2 Package and thermal

0.40 mm-pitch TQFN with one exposed pad (S11 = 1). θJA 38 °C/W, θJC 2.5 °C/W (DS p.10). IC dissipation is dominated by the gate
drive in the VDD LDO, about 0.27 W at 18.53 V (section 11.2), plus 0.04 W IQ: a rise of about 12 °C at θJA. OTP at 140-160 °C
(DS p.18).

### 12.3 Input capacitance and inrush (H8)

The datasheet asks for at least one capacitor > 15 µF on CSIP (DS p.8, p.90) and a 4.7 µF 50 V DCIN capacitor behind 10 Ω
(DS p.88 section 9.7). It warns against a bare capacitor at a cabled adapter node and offers a 2.2 Ω / 2.2 µF snubber (DS
p.85 section 9.3). A CCB with about 27 µF effective at 16 V (15 µF on CSIP plus about 10 µF of MLCC at Q1 drain plus the DCIN
branch, A) draws 27 x 12 mA/µF = **0.32 A** on the RT1987-ramped node; with the 0.15 A aux the remaining budget for the
motherboard C-D8/C-D10 is (1.0 - 0.15 - 0.32) / 0.012 = 44 µF. TODO(verify: board rev 20260622 BOM, C-D8 and C-D10 values).
The [B798] design reaches 0.46-0.57 A with the eFuse dVdT; the same eFuse on this CCB sets the close current in the same way.

Switching can start during the ramp. The 150 ms debounce applies only to "the first POR and no battery condition" (DS p.47
section 7.1, Fig 6 with no battery). On this CCB the VBAT pin sits on VCHG, which the mandatory keep-alive holds at
3.58-4.46 V; whether that level counts as a battery present is not stated (TODO(verify: Renesas, battery-detect level on
VBAT)). With a battery connected, Fig 7 shows switching about 12 ms after VADP begins to rise (figure reading, typical). The
load is then small: BATGONE is HIGH and ChargeCurrentLimit is 0, so only the VSYS_L capacitors charge to 8.384 V. Their
energy is 0.5 x 25 µF (A) x 8.4² V² = 0.88 mJ, plus an equal loss in a linear-equivalent charge, so about 1.8 mJ; drawn from
VCHG-IN at about 16 V this is about 0.11 mC, that is 0.011-0.055 A averaged over a 2-10 ms converter start (A). The term is
small against the 0.32 A capacitor inrush but is added to the H8 budget.
TODO(verify: soft-start duration of the VSYS regulation at start-up).

### 12.4 BOM estimate (charger IC and power stage; system core excluded)

| Group | Parts | Rough cost per board |
|---|---|---|
| RAA489110 | 1 | USD 4.51-4.96 (UNVERIFIED, product page) |
| Q1-Q5 | 5 | USD 2.5-5 (allowance, UNVERIFIED) |
| Inductor 3.3 µH class | 1 | USD 1-2 (allowance) |
| Rs1 75 mΩ, Rs2 10 mΩ (1 W 1206 class) | 2 | USD 0.5 |
| Input, VSYS and output MLCCs, DCIN, VDD, VDDP, boot capacitors | about 14 | USD 1.5 |
| PROG, compensation, DCIN 10 Ω, VDDP filter, OR diodes, BATGONE network | about 9 | USD 0.5 |
| **Total** | **about 32 parts** | **about USD 11-15** |

The BQ25798 power stage counts 27-28 parts at about USD 10-12 ([B798] section 12.4).

---

## 13. Stock and price

| Source | Date | Result | Status |
|---|---|---|---|
| Renesas product page (summarising fetch) | 2026-11-10 | Active; A3GNP#AA0 USD 4.96 "In stock", A3GNP#HA0 out of stock, ARGNP#AA0 and #HA0 out of stock at USD 4.51; no quantities | UNVERIFIED |
| DigiKey search | 2026-11-10 | HTTP 403 | blocked |
| Mouser search | 2026-11-10 | Timeout | blocked |

Stock and price are **UNKNOWN** at primary level. The evaluation board RTKA489110DE0000BU exists (DS p.91); its stock was not
checked because the custom board does not use it.

---

## 14. Round-6 findings of the BQ25798 carrier design

Only the IC-dependent findings are counted ([CRIT] section 3.4).

| R6 finding | Effect of the RAA489110 | Disposition |
|---|---|---|
| 1 vreg-corruption-no-fixed-pack-ovp (major) | MaxSystemVoltage is a register writable to 18.304 V (DS p.31); VSYS OV tracks the register (DS p.64). Battery-only mode resets MaxSystemVoltage to the PROG default when PSYS is disabled (DS p.49), so a corrupted CV clears at each VCHG-IN loss but not during a window | **Keeps** (the BQ29200 OVN term stays) |
| 8 loop-budget-5ms-breaks-1ms-tick-deadlines (major) | See the comparison table below. The RAA489110 needs the same three limit words per mode change, plus an AdapterCurrentLimit1 rewrite after every ACOK rise if Control3 bit 14 stays 0, plus a periodic SMBus-timeout kick; its readback image is larger and cannot be read in one burst | **Reopened (C, first-order)** |
| 10 chg-src-misattributes-subh1-regen (major) | An input-current ADC exists (5.92 mA LSB at 75 mΩ), but its accuracy is unpublished and it saturates at 1.515 A | **Keeps** |
| 12 ff-reversal-hold-unattainable-at-100khz (minor) | The threshold is a register; a mode change still needs I2C writes. BATGONE handles the per-burst stop without I2C, as ILIM_HIZ does | **Keeps** |

First-order comparison of the I2C burden (100 kHz; one 16-bit RAA489110 word transaction about 0.45 ms, one BQ25798 byte
about 0.09 ms within a burst):

| Item | BQ25798 ([WD] FR-46, slot-5 verify) | RAA489110 |
|---|---|---|
| Limit writes per mode change | VINDPM, IINDPM, ICHG (3 registers) with same-transaction readback of REG01:02 and REG05 | VIN, AdapterCurrentLimit1, ChargeCurrentLimit (3 words), each read back |
| Writes after a VCHG-IN return | Re-qualification through T9 (FR-30) | AdapterCurrentLimit1 rewrite after every ACOK rise unless Control3 bit 14 = 1; the full section 5.4 item 5 image after a POR |
| Periodic writes | Charger watchdog handling as in [WD] (not re-counted here) | One ChargeCurrentLimit write per <= 2 s (SMBus timeout kick) |
| Periodic readback | REG00-0A, one burst of 11 bytes every 20 ms, about 1.4 ms | About 9 control words (Control0, 1, 2, 3, 4, 7, 8, 9, and Information2) plus 5 DAC words at scattered addresses, about 14 transactions, about 6.3 ms; must be time-sliced (FR-45) |
| Never-write bits | REG14[1] EN_EXTILIM, the CELL field, the [WD] image | About 25 bits across 8 control registers (section 5.4 item 4), plus the 5 mandatory image fields of item 5 |

The RAA489110 needs more never-write registers and a longer readback, which [CRIT] section 3.4 classes as a reopened
finding. The count of BQ25798 never-write bits outside REG00-0A was not tabulated here. TODO(verify: [WD] full BQ25798
read-back image, for a word-by-word count).

Net: 0 closed, 1 major reopened (finding 8), S14 = 1. Findings 13-16 close for every CCB; findings 2, 4-7, 9 and 11 are
IC-independent.

---

## 15. Open questions, bench gates and blocked fetches

### 15.1 Open questions (Renesas or datasheet)

1. BATGONE input filter and the BATGONE-falling behaviour: does it wait for an ADC poll (100 ms) or re-run any detection?
2. VIN loop accuracy at 13-20 V; retention of 0x4B across an ACOK fall with VDD held.
3. Control3 bit 6 effect on the regulated current (section 7.1).
4. BGATE action on VSYS OV; BATGONE priority in PPS mode (sections 5.2, 5.3).
5. NTC action on charging with the programmable profile disabled (section 9.2).
6. Buck-only population (Q3/Q4 omitted) (section 2.1).
7. SCL/SDA behaviour with the IC unpowered.
8. Register 0x4B bit count (Table 1 "6" against Table 2's eight weights).
9. VSYS_L decay rate in the parked state and whether the VIN loop holds VSYS_L at any level (section 6.1).
10. Low-power LDO dropout at VBAT = 3.58 V; register retention with the keep-alive (section 8.4).
11. Battery-detect level on VBAT for the 150 ms first-POR debounce (section 12.3).
12. Whether the BGATE on-current of the EC table applies at the reduced charge-pump duty (Control0 bit 6 = 0).
13. A Q5 part with Qg at 5 V <= 8 nC and RDS(on) <= 5 mΩ (section 8.3).

### 15.2 Bench gates

| Gate | Test | Pass |
|---|---|---|
| R-B1 | Input draw at VCHG-IN 16 V, BATGONE HIGH, VSYS_L at no load (DE mode) | <= 5 mA ([EVAL] S1-B1) |
| R-B2 | BATGONE falling to charge current at 63 %, VIN above the threshold, VCHG parked as designed | <= 1 ms; no 100 ms step |
| R-B3 | Charge start from a parked VCHG at 0 V, 4 V and 7.4 V (section 8.4); at 0 V, record whether Q5 turns on at all | No trickle dwell above 1 ms at 4 V and 7.4 V |
| R-B4 | Warm response: VCHG-IN step from Vth - 0.5 V to Vth + 1 V with Q5 on | τ <= 4 ms, 10-90 % <= 9 ms ([EVAL] 3.2) |
| R-B5 | Hard stop: PERMIT falling to input current < 10 % at 1.5 A input | <= 115 µs ([EVAL] 2.5) |
| R-B6 | Ceiling: input current at AdapterCurrentLimit1 maximum, 18.5 V and 21.5 V | 1.59-1.69 A |
| R-B7 | VIN threshold at codes 106 and 149 | Within ±2 % for S4 = 2 |
| R-B8 | ADC charge-current and input-current error against a shunt at 0.3/0.9/1.5/3.1 A | Sets the power-balance threshold ([EVAL] 2.3) |
| R-B9 | 0x4B, 0x3F, 0x14 after a VCHG-IN collapse with the keep-alive fitted | Values retained or reload documented |
| R-B10 | Thermal at 3.25 A, 21.5 V, 0.6 s bursts and steady 1.6 A FC | <= 2 W, IC < 100 °C |
| R-B11 | Park 60 s at VCHG-IN = 16 V, VIN = 19.072 V, BATGONE HIGH, keep-alive fitted, with the section 5.4 item 5 image; log VSYS_L, ACOK, Information2 FAULT state and 0x3F; then a burst | No FAULT entry, no ACOK fall, 0x3F unchanged, burst warm per R-B2 |
| R-B12 | Read 0x3F after every FC-window close and every VCHG-IN return | Equal to the last written value (Control3 bit 14 = 1) |
| R-B13 | Q5-short emulation (Q5 bridged) with BATGONE HIGH in regen and FC modes | Firmware detects the charge current and opens REGEN / FC_CHARGE_ENABLE within the [EVAL] 2.7 6 ms window |
| Carried | [EVAL] S0-R3, S1-C, S3-all, S4-c, S5-a/b, MCU watchdog M6/S3-W | As [EVAL] 0.2 |

### 15.3 Blocked fetches

| URL | Reason | Needed for |
|---|---|---|
| `https://www.digikey.com/en/products/result?keywords=RAA489110` | HTTP 403 | Stock, price (S12, S13) |
| `https://www.mouser.com/c/?q=RAA489110` | Timeout | Stock, price |
| `https://www.renesas.com/en/products/raa489110` (Order / Buy tab with quantities) | Dynamic page; only a summarising fetch succeeded | Primary stock figure |
| Renesas RAA489110 firmware/programming guide referenced on DS p.70 ("See the RAA489110 device page for firmware documentation") | Not located | BATGONE and 0x4B behaviour |

---

## 16. Verdict and comparison with the BQ25798 baseline

**Verdict: FEASIBLE_W_COND.** No requirement fails on the primary datasheet. The conditions are those of [EVAL] 0.2 that are
not EVM-specific (conditions 1-8, 10-14 as restated in [B798] section 16), plus:

- the BFET Q5 between VSYS_L and VCHG with BGATE as the only charge path (section 2.2), and a Q5 with Qg at 5 V <= 8 nC and
  RDS(on) <= 5 mΩ (section 8.3);
- the never-write list and the mandatory configuration image of section 5.4 with readback, including Control4 bits 15 and
  14 (M5), the PTM/PPS bits (M7), Control0 bit 6, Control3 bit 0, Control9 bits 4:2 and Control3 bit 14;
- the mandatory keep-alive with MinSystemVoltage <= 3.5 V (section 8.4);
- the Q5-short closure of section 5.3 (firmware detection with the ADC in all modes, optionally the eFuse EN path) and the
  two-channel BATGONE pull-down (section 9.2);
- no or <= 1 nF BGATE capacitor (section 8.3);
- bench gates R-B1 to R-B5 and R-B11 to R-B13.

Score under [CRIT] section 3 with the evidence cap of section 3.2:

| Criterion (weight) | Score | Evidence | Basis |
|---|---|---|---|
| S1 warm response (15) | 1 | U/B | VIN loop keeps the converter enabled (P), but the parked state needs the VSYS UV and ACLIM-reload configuration (sections 6.1, 7.3); BATGONE exit undocumented; only boost-mode typical curves |
| S2 fail-safe POR (10) | 2 | P | No charge at POR; POR VIN threshold 4.096 V, so not 3 |
| S3 ceiling quality (8) | 1 | P/C | Fixed Rs1 full-scale clamp, continuous; not mode-switchable; four register defeat paths (Control3 bits 5 and 6, PTM, PPS) |
| S4 threshold quality (8) | 1 | P/U | 128 mV step; accuracy at 19 V unpublished |
| S5 inhibit latency (7) | 1 | U/B | BGATE sink current published, pin filter not; latency depends on the unselected Q5 gate charge |
| S6 interlock adders (10) | 0 | C | About 10 at equal function to the BQ25798 minimal build (FC leg and mandatory keep-alive), about 11-14 at single-fault parity (section 9.2) |
| S7 telemetry (5) | 2 | P | Charge current, input current, VIN; no accuracy |
| S8 FC-mode fitness (6) | 3 | P | ACLIM step 1.07 mA at 75 mΩ; CV ±0.5 %; EOC programmable (autonomous mode); adapter-current accuracy published at 28 V. Sensitivity: 2 if termination must be programmable outside autonomous mode |
| S9 rating margin (4) | 0 | P | 36 V |
| S10 layout (7) | 0 | P | External-FET buck-boost, two hot loops |
| S11 package (3) | 1 | P | 0.40 mm-pitch QFN |
| S12 stock (5) | 1 | cap | UNVERIFIED |
| S13 cost (2) | 1 | cap | About USD 11-15, allowances UNVERIFIED |
| S14 round-6 (5) | 1 | C | Net reopens 1 (finding 8, major; section 14) |
| S15 inrush (3) | 2 | C | 0.32 A from the CCB; MB share unverified |
| S16 topology barrier (2) | 0 | P | Buck-boost; POR VIN 4.096 V below the pack |
| **Weighted total** | **about 36** (107 / 3) | | Sensitivity: 34 with S8 = 2; 38 with S4 = 2 after R-B7; 37 with S14 = 2 if a word-by-word count shows no reopening |

**Comparison with the BQ25798 baseline (about 40, [B798] section 16).** The RAA489110 scores about 4 points below the
baseline. It does not justify a switch, and it does not qualify as the alternate under [CRIT] section 3.5:

- condition 1 is not decided on M5: M5 is a conditional pass (the sole inhibit pin is defeated by Control4 bits 15 and
  14), the class [CRIT] M5 admits; the BQ25798 has P evidence for M5 through ILIM_HIZ, whose 0.75 V stop level is
  published (SLUSDV2C p.27), and its EN_EXTILIM interaction is B ([B798] section 3, S1-B3). The EN_EXTILIM analogy holds
  for M5 as well as M7;
- condition 3 fails on the first-order count: the larger never-write list and readback image reopen R6 finding 8 (major);
- condition 4 holds (S1 equal at 1).

The RAA489110 is therefore recorded as a feasible finalist below the baseline. Its intrinsic advantages remain: a 36 V
input rating that passes M2 without the eFuse standoff, no charging out of POR with a 53 mA PROG ceiling after every POR, a
pack-isolating body diode while Q5 is off, no `CHG_QUAL` logic, and the full 3.1 A at the regen threshold, where the BQ25798
design stops at 2.87-2.91 A. Its costs are larger than first assessed:

- the hard inhibit acts on one series FET while the converter keeps switching, so a Q5 short leaves only the VIN soft layer
  in regen mode and only firmware in FC mode, which breaks the purge ruling for the firmware response time (section 5.3);
- the parked regen state can fall into the VSYS UV fault and an ACLIM reload to 53 mA, which needs configuration and bench
  proof (sections 6.1, 7.3);
- the keep-alive is mandatory, and at equal function the adder count (about 10-14) matches the BQ25798 (9-16);
- a five-FET external power stage with two hot loops on a 0.40 mm-pitch QFN, a 128 mV threshold step with no accuracy at
  19 V, 8-bit telemetry (22 mA charge-current LSB, input ADC saturating at 1.515 A) and unpublished BATGONE timing.

The BQ25798 keeps its place.

---

## 17. Alternates: RAA489118 and RAA489108

| Item | RAA489118 ([DS118]) | RAA489108 ([DS108]) |
|---|---|---|
| Class | Buck-boost charger, 2-7 cells, optional BFET, SMBus | Buck-boost NVDC charger, 2-4 cells, SMBus |
| Input rating | CSIP, CSIN, DCIN, ADP, ASGATE abs max 36 V; adapter OVP 32.2 / 33.3 / 33.95 V (p.17 EC) | CSIP, CSIN, DCIN, ADP, ASGATE abs max 36 V (p.9); adapter OVP 33.3 V for > 10 µs (p.65 section 8.11.1). PHASE2 24 V (DC and < 20 ns rows); BOOT2, UGATE2 VDDP + 24 V; VBAT, VSYS, CSOP, CSON, BGATE 24 V (p.9, read as a page image); the same split as the RAA489110 |
| VIN register | 0x4B, bits 13:8, **512 mV LSB**, POR 4.096 V (p.30 Table 1) | 0x4B, 6-bit, **512 mV LSB**, range 27.648 V, POR 4.096 V (p.26 Table 1) |
| Settings near target | Regen 18.944 V or 19.456 V; FC 13.312 V or 13.824 V | Same |
| ADC | None found in the register map | None found |
| BATGONE | Logic HIGH forces BGATE off "in any circumstances" (p.8); internal **5 µA pull-down** at 5 V (p.15): defaults to **permit**; a CCB pull-up to VDD and an open-drain pull-down restore the fail-safe | Same pin text (p.7); 5 µA pull-down (p.15 EC) |
| POR charging | ChargeCurrentLimit "256mA: CONFIG = VDD, 0A: Otherwise" (p.29 Table 1); PROG rows enable autonomous charging when CONFIG/PSYS is LOW at POR (p.54 Table 16 note 1). Fail-safe needs CONFIG LOW and a "No" PROG row: strap-dependent | ChargeCurrentLimit "reset to 0x0000H after POR" (p.27) |
| Extra pins | ACIN (external divider, valid above 0.6 V) and ASGATE adapter switch: ACIN pulled low is a second pin inhibit, but its exit is an adapter re-qualification (cold) | ADP/ASGATE adapter switch |
| Telemetry | AMON/BMON analog only; a CCB current monitor on I2C is needed (M11 conditional, S7 = 0) | Same |
| Stock | Not checked | DigiKey HK 0 ([SCR], UNVERIFIED) |
| Assessment | Adds the 2-7S range only. Coarser threshold, no ADC, permit-default pin and strap-dependent POR charging make it weaker than the RAA489110 on S2, S4, S6 and S7 | Weaker than the RAA489110 on S4 and S7; second source of the same mechanism only |

Neither alternate approaches the RAA489110 on the scored criteria; the RAA489108 is the closer second source because its POR
does not charge without strap conditions. Both share the RAA489110's BATGONE -> BGATE architecture, so the Q5-short,
parked-state and keep-alive findings of sections 5.3, 6.1 and 8.4 apply to them as well. TODO(verify: [DS118], [DS108],
BATGONE Disable and BGATE tristate register bits, VSYS UV default).

---

## 18. Verification log

Two independent reviewers checked this dossier against the primary documents. Each finding was re-checked against
R16DS0212EU0202 Rev.2.02 (pages re-read as text and, for pp.40 and 48 and Fig 7, as rendered page images) and against
R16DS0159EU0105 Rev.1.05 p.9 (rendered image).

| # | Finding | Severity | Disposition | Basis |
|---|---|---|---|---|
| 1 | PTM (Control7 bit 3) and PPS (bits 4+3) also defeat the adapter-current ceiling; PPS turns BGATE on | Major | Applied | DS p.54 section 7.3.11 (loop disabled 4-7 ms after PTM entry with Control4 bit 10 = 0), p.55 section 7.3.12 (BGATE on; CCHOT_DB needs Control0 bit 8 = 1), p.37 Table 7. M7, sections 7.1 and 5.4 rewritten; Control0 bit 8 and Control4 bit 10 added to readback |
| 2 | Fig 7 timing misread (17 ms) | Minor | Applied | Rendered Fig 7 (4 ms/div): VADP rise to ACOK about 7.7 ms, to the VSYS step about 11.7 ms. Section 5.1 and M9 corrected |
| 3 | 150 ms debounce applies only at first POR with no battery | Minor | Applied | DS p.47 section 7.1 wording; Fig 6 has no battery, Fig 7 has one. Section 12.3 rewritten; the VSYS_L charge added to H8 (about 0.01-0.06 A, A) |
| 4 | WOCP auto-retries (hiccup, not latch) | Minor | Applied | DS p.64 section 7.6.7, p.34 Table 5 bit 11. Sections 7.2, M7 and HR4 updated; Control2 bit 11 = 0 read back |
| 5 | BGATE on-current at reduced charge-pump duty and only for VBAT > 2.7 V | Minor | Applied | DS p.32 Table 3 bit 6, p.44 Table 14 note 1, p.20 EC condition. Control0 bit 6 = 1 made mandatory; section 8.2 restricted to VCHG > 2.7 V |
| 6 | NTC currents typical only; pull-up topology not stated | Minor | Applied | DS p.15 EC (62-68, 126-134, 250-270 µA), p.11 VDD 4.5-5.5 V. Recomputed: far-end pull-up 0.62-2.70 V (margin 0.60 V); pin-side 3.02 V (margin 0.28 V). Far-end topology fixed in section 9.2 |
| 7 | 931 Ω strap selects 1050 kHz and PSYS; 724 kHz needs 1370 Ω | Minor | Applied | Rendered DS p.48 Table 18. 1370 Ω made the baseline; 1050 kHz loss computed (1.68-1.83 W, below 2 W) |
| 8 | Two off-by-one page citations (Fig 38, Fig 39) | Minor | Applied | DS p.65 (section 8.1 start), p.66 (Fig 38, 109/114 % text), p.67 (Fig 39 and footnote) |
| 9 | RAA489108 abs-max TODO can be closed | Minor | Applied | Rendered DS108 p.9: PHASE2 24 V; BOOT2/UGATE2 VDDP + 24 V; VBAT, VSYS, CSOP, CSON, BGATE 24 V |
| 10 | Keep-alive VDD retention overstated as P/C (reviewer 1) | Minor | Applied | DS p.47 gives the low-power LDO without a dropout; the dropout row is for the DCIN LDO. Retention marked U, R-B9 decides |
| 11 | Parked regen state: VIN loop sheds system power, VSYS_L reaches the 4.8 V VSYS UV fault, ACOK low, ACLIM reload | Major | Applied | DS p.69 section 8.2.2.1, p.63 section 7.6.5, rendered p.40 Table 10 (POR 011 = 4.8 V), p.47 (ACOK low on VSYS UV), p.49 (reload). New section 6.1; M8, M9 conditional; Control9 bits 4:2 in the image; R-B11 added. The decay rate is not published (open question 9) |
| 12 | M5 is register-defeatable (Control4 bits 15, 14); decision-rule condition 1 not met | Major | Applied | DS p.37 Table 7; [B798] M5 = P with /CE not register-defeatable; [CRIT] section 3.5 condition 1. M5 conditional; alternate status withdrawn |
| 13 | Q5 is the sole inhibit element; a Q5 short charges the pack with PERMIT LOW | Major | Applied | DS p.49 section 7.3.1 (VSYS regulated with BGATE off), p.70 section 8.3.1.1 (BATGONE gates charging only). Single-fault table in section 5.3; HR3, HR5 conditional; R-B13 added |
| 14 | Adder count 3 vs 9 compares unequal builds | Major | Applied | [B798] section 9.2 minimal 9 includes the FC leg; [CRIT] section 3.3 counts the keep-alive. Recount about 10 (equal function) to 11-14 (parity); S6 2 -> 0 |
| 15 | MinSystemVoltage disposition invalid; keep-alive mandatory | Major | Applied | Q5 body-diode direction and D-BT-SQ leave VCHG without a parking source; DS p.50 (0x0000 disables charging; 100 ms ADC poll), p.36 Table 6 bit 0, p.20 EC condition. Disposition deleted; keep-alive made a verdict condition |
| 16 | DCIN path drops keep-alive below the VDD POR band (reviewer 2) | Minor | Partly applied | Retention marked U and 3.58 V reconciled with [WD] T18/H.20. The DCIN-chain reasoning is rejected: the low-power LDO input is an internal OR of VBAT and CSIN (DS p.47), so VBAT = VCHG feeds it directly, not through the Q5 body diode and the OR diodes |
| 17 | ACLIM reload to 53 mA at every ACOK fall silently caps HR1 | Minor | Applied | DS p.49, p.35 Table 6 bit 14. Section 7.3 adds the rewrite and the Control3 bit 14 = 1 option; R-B12 added; HR4 wording corrected |
| 18 | BATGONE timings rest on an unconstrained Q5 gate charge | Minor | Applied | DS p.9 (BGATE pumped to VBAT + 5 V), p.19-20 EC. Q5 requirement Qg(5 V) <= 8 nC with RDS(on) <= 5 mΩ; latency rows B; 15 nC case 81-115 µs |
| 19 | "The VBAT pin and CSON sit on VCHG" is wrong | Minor | Applied | DS p.71 section 8.3.1.2 (Turbo compares CSON with VBAT across the BFET). Sections 2.1, 8.4 and H7 corrected |
| 20 | R6 finding 8 "Keeps" asserted, not shown | Minor | Applied | First-order comparison table in section 14: about 14 word transactions (about 6.3 ms) against one 11-byte burst (about 1.4 ms); more never-write registers. Finding 8 reopened, S14 2 -> 1; word-by-word BQ25798 count left as TODO |

Result: 19 applied, 1 partly applied, 0 rejected. The verdict stays FEASIBLE_W_COND with a longer condition list; the score
falls from about 44 to about 36 against the baseline's about 40, and the RAA489110 no longer qualifies as the alternate
(conditions 1 and 3 of [CRIT] section 3.5 fail).
