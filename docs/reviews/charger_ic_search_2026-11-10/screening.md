# Charger IC search: candidate screening and finalist selection (2026-11-10)

## 1. Method

### 1.1 Inputs

This document screens every charger candidate found by the 2026-11-10 vendor sweeps and by the re-screen of the
2026-11-05 candidates. It applies the framework of `screening_criteria.md` in this folder (cited as **CRIT**):
must-haves M1-M13 (CRIT section 2), scored criteria S1-S16 (CRIT section 3.1), the evidence cap (CRIT section 3.2) and
the decision rule against the BQ25798 baseline (CRIT section 3.5). The re-screen of the 2026-11-05 parts is
`rescreen_2026-11-05_candidates.md` in this folder (cited as **RESCREEN**).

Candidate facts come from the vendor sweeps of 2026-11-10. This document cites the primary datasheet by literature number
and page where the primary was read. The downloaded sweep material is not retained in the repository; the citations in
sections 1.3, 2 and 3 are the record. A fact from a product page, a distributor listing, a search snippet or recollection is marked
UNVERIFIED. Section 1.3 lists the facts that this screen re-read in the primary datasheet before it rejected or promoted a
part.

Status codes: P = PROVEN_DATASHEET, C = PROVEN_CALC, B = BENCH_GATE, F = FAIL, U = UNKNOWN or missing primary,
sys = blocked at system level.

### 1.2 Application of the must-haves

The must-haves are applied strictly. A must-have fails only on a documented contrary fact. A must-have whose evidence is
U or B is a conditional pass, written "Mn c", and becomes a named bench gate or a fetch item. The following readings apply
to every candidate:

1. **M2 (35 V).** Only the pins that see VCHG-IN, the switch node and the bootstrap pins are judged. A 30 V or 32 V input
   rating fails M2. The BQ25798 baseline also fails M2 as written (VAC1/VAC2/VBUS 30 V, SLUSDV2C section 6.1 p.7). The
   baseline is outside this screen; section 5.2 flags the consequence for the scoring (scoring.md). This screen uses the
   strict reading. scoring.md section 2.1 adopts the protected-standoff reading and re-admits the parts rejected here on
   M2 F alone; the main document section 6.4 bounds that class without re-screening it.
2. **M9 (no cold restart).** The per-burst inhibit is the path that the H1 V-MOT/VBUS comparator drives. H1 trips at the
   end of each regen burst and releases at the next one. A part whose only pin-level inhibit has a documented restart of
   10 ms or longer therefore fails M9, even if its input-voltage loop is warm. This reading is the one that rejected the
   BQ25756 on 2026-11-05 (EVAL section 0.2).
3. **M10 and M12 (host interface, runtime current control).** A part without I2C or SMBus fails M10. A CCB current monitor
   satisfies M11 (telemetry) but not M10 or M12, because the FC-window governor rewrites the input-current limit at 50 Hz
   (EVAL section 3.4) and a switched resistor network cannot follow that rate with a continuous value.
4. **M8 (input-voltage regulation).** The loop must be in the charger IC. A discrete amplifier that servos a current pin
   from a VIN divider is a CCB design, not an IC loop, and fails M8.

### 1.3 Spot-checks made by this screen

| Item | Primary read | Result | Effect |
|---|---|---|---|
| BQ25690 hardware input ceiling: RILIM_HIZ ROC 4.6-27.4 kOhm against the HR1 regen need of about 1.21 A | TI SLUSFN4A p.6 (ROC), EC KILIM row (KILIM 2890/3333/3780 A*Ohm, test points IIN_MAX = 1.6, 1.0, 0.5 A), section 6.3.8.1.2.1 p.26-27 | Confirmed: at 10 mOhm the pin ceiling inside the ROC is 0.63-0.82 A. The KILIM test point at 1.6 A implies about 2.08 kOhm, outside the ROC. Page 27 states that KILIM is referenced to 10 mOhm and that RAC_SNS = 1 "scales the internal values to provide the same A" with a 5 mOhm resistor. Inference (C, TODO(verify: TI E2E)): with a 5 mOhm input shunt and RAC_SNS held at its POR value 0, the pin ceiling in amperes doubles to 1.26-1.64 A at 4.6 kOhm. A write of RAC_SNS = 1 halves the ceiling, which is the safe direction, and a POR returns the design value | M7 conditional pass. The E2E question stays open; the 5 mOhm / RAC_SNS = 0 arrangement is a candidate design route for the dossier. (Superseded 2026-11-10 by dossier_BQ25690.md section 1.4 and scoring.md section 2.6: RILIM_HIZ recommended range 0-33 kOhm, CVIN >= 10 uF after derating, EN_CHG cleared by the ICHG strap fault at a true POR; this row is kept as the screening record.) |
| BQ25690 HIZ exit through the pin | SLUSFN4A section 6.3.3 / 6.3.6 (text lines on HIZ exit) | Confirmed: an exit through ILIM_HIZ re-reads the CELL, ICHG and VCHG straps. The per-burst inhibit must therefore be /CE (warm), and ILIM_HIZ HIZ is reserved for latched faults | M9 conditional pass on /CE only |
| LTC4015 charge-voltage tolerance | LTC4015 Rev B (4015fb) p.4, EC row VCHARGE(TOL), "l" over the operating junction range | Confirmed: +-1.25 % for all chemistries over junction temperature. At 2S and 4.2 V/cell this gives 8.295-8.505 V; the upper value exceeds the M3 limit of 8.484 V by 21 mV | M3 fails as written at 4.200 V/cell. At DAC code 11110 (4.1875 V/cell, 12.5 mV LSB, p.5) the band is 8.270-8.480 V: the upper limit holds and the lower limit is 0.55 % below the M3 band. See section 4.3 |
| LTC4015 operating input range | 4015fb p.4, VIN row | 3.1-35 V operating (l); abs max 40 V (p.3) | M2 pass; S9 score band 38-44 V |

Most rejections in section 2 rest on a primary-read fact cited by page. Three rejected or held entries do not: the BQ25822
(row 8) and LT8705/LT8705A (row 29) rejections are UNVERIFIED, and the BQ25820 (row 7) rests on an illegible figure (see the
note on row 7). The two Not-scorable entries (rows 24 and 25) also have no primary read and are not rejected.

## 2. Screening table

### 2.1 Candidates screened in full

The table gives the must-have outcome as the failing items (F) and the conditional items (c). Items not named pass on P or
C evidence. "Reject" means at least one documented F.

| # | Part | Vendor | Topology | Must-have outcome | Result | Reason |
|---|---|---|---|---|---|---|
| 1 | BQ25690 | TI | Integrated 4-switch buck-boost, NVDC, external sense resistors, 1-7S | M3 c (+-0.5 % specified at 4S), M4 c (3.3 A register ceiling, ICHG accuracy specified to 1.5 A), M6 c (EN_CHG POR 1; /CE needs an always-on CCB pull-up), M7 c (section 1.3), M8 c (FORCE_VINDPM reset by the watchdog), M9 c (/CE warm, typical curve only), M13 P | **Finalist** | Only integrated TI part with 45 V abs max (SLUSFN4A section 5.1 p.5) and VIN_OVP 35.5 V min. /CE leaves the converter regulating SYS in PFM, and the typical curve shows charge current about 1.4 ms after the /CE edge. Small (4.0 x 3.5 mm), C_IN 1.8 uF min. (Superseded 2026-11-10 by dossier_BQ25690.md section 1.4 and scoring.md section 2.6: RILIM_HIZ recommended range 0-33 kOhm, CVIN >= 10 uF after derating, EN_CHG cleared by the ICHG strap fault at a true POR; this row is kept as the screening record.) |
| 2 | BQ25773 (SMBus twin BQ25770G) | TI | External-FET quasi-dual-phase NVDC buck-boost controller, 2-5S | M7 c (ILIM_HIZ divider, EN_EXTILIM defeatable), M9 c (HIZ and FRC_CONV_OFF exit latency unspecified) | **Finalist** (reopened) | 45 V abs max, CHARGE_CURRENT 0 and EN_AUTO_CHG 0 at POR, VINDPM 3.2-27 V +-1 % at 18 V, independent comparator with FRC_CONV_OFF (1 us deglitch) that can take H1 directly (SLUSEK7 p.8, p.12, p.30, Table 7-2 p.31). The 2026-11-05 downgrade rested on the EVM (RESCREEN section 3.3). Cost: the hardest layout in the set |
| 3 | RAA489110 | Renesas | External-FET 4-switch NVDC buck-boost controller with N-FET BGATE, 8-bit ADC, 2-4S | M3 c (MaxSystemVoltage accuracy at 8.4 V TODO(verify: R16DS0212EU0202 EC)), M5 c (BATGONE opens BGATE; the converter keeps regulating VSYS), M7 c (sense-resistor full scale; one Rs1 cannot give two mode ceilings), M9 c (VIN loop warm per text; BATGONE exit timing unspecified), M13 c (stock UNVERIFIED) | **Finalist** | Only non-TI part that clears 35 V (CSIP/CSIN/DCIN/BYPSRC 36 V, R16DS0212EU0202 section 3.1 p.11) and has a runtime VIN register to 24.576 V, an I2C ADC for charge and adapter current, POR charge current 0, and a BATGONE pin that defaults to inhibit through its internal pull-up current source. Mechanism differs from the TI finalists (battery-FET inhibit) |
| 4 | LTC4015 | ADI (Linear) | External-FET synchronous buck controller with INFET/OUTFET drivers, I2C, coulomb counter | **M3 F as written** (section 1.3), M5 c (no inhibit pin; UVCLFB clamp FET), M9 c (UVCL release warm per R2 reading; a new charge cycle runs 2-4 s battery detection, 4015fb p.30), M13 c (analog.com blocked) | **Finalist under a declared exception** (section 4.3) | Only external-FET buck controller with I2C that survives M9. UVCL POR equals the divider maximum, so every charger POR lands in a regen-only state (4015fb p.4, p.22 via R2); high-side sense on both ports; 40 V abs max, OVLO 37.7 V min. Battery detection forces the IC to stay powered from the pack, which needs a motherboard bridge across D-BT-SQ (sys) |
| 5 | RAA489118 | Renesas | External-FET buck-boost charge controller, 2-7S, SMBus, no ADC | M5 c (BATGONE has an internal 5 uA pull-down; fail-safe needs a CCB pull-up), M7 c, M9 c (ACIN exit cold, 150 ms / 1.3 s; BATGONE warm), M11 c (no ADC; AMON/BMON analog only, CCB monitor needed) | Alternate (folded into the RAA489110 dossier) | Same 36 V class and VIN register (512 mV LSB, R16DS0321EU0200 Table 1 p.30) as RAA489110, but no ADC and an inhibit pin that defaults to permit. Adds nothing over RAA489110 except the 2-7S range |
| 6 | RAA489108 | Renesas | External-FET NVDC buck-boost controller, 2-4S, SMBus | M5 c, M7 c, M11 c (no ADC found), M13 c (DigiKey HK stock 0, UNVERIFIED) | Alternate (second source only) | Sibling of RAA489118 with 2-4S; no ADC, stock uncertain |
| 7 | BQ25820 | TI | External-FET buck controller (85 V), I2C, 16-bit ADC | **M9 F** (/CE edge to charge current about 120-160 ms, SLUSFN3B Fig 8-7 p.67, time base TODO(verify); ACUV/ACOV exit deglitch 12 ms, EC p.15; ILIM_HIZ HIZ turns REGN off, p.24) | Reject (first reserve if the per-burst inhibit moves off-pin). (Amended 2026-11-10: the main document grades M9 as U, not F, because the Fig 8-7 time base is illegible and the 12 ms ACUV/ACOV deglitch applies to a threshold crossing, not to the per-burst inhibit; the part is held in reserve pending the hand fetch.) | Best POR anchors in the sweep (hardware FB-divider CV with a +-2 % register trim, ACUV hardware VDPM floor, VAC_DPM reset by REG_RESET only, KILIM resistor ceiling). Every pin stop is cold, so H1 has no warm target. It also needs >= 80 uF on input and output (ROC p.8) |
| 8 | BQ25822 | TI | External-FET buck controller with boost reverse, 85 V | M9 F expected (same core as the BQ25820; SLUSG44A Fig 7-6 not read: UNVERIFIED); C_IN >= 80 uF | Reject | Adds nothing over the BQ25820 for this board |
| 9 | BQ25756 / BQ25756E / BQ25750 | TI | External-FET buck-boost controllers | **M9 F** (about 40 ms compensation toggle at startup, SLUSEN5A p.21, SLUSFF4A p.22, SLUSDY3 p.23, recurrence on every /CE start U; /CE to current 145-175 ms typical, R2 dossier A1) | Reject on the pin stops (rejection was IC-intrinsic, RESCREEN section 3.7); the W2 warm analog inhibit is held in reserve (section 4.4) | The custom board removes only the 217 uF EVM inrush; the 80 uF datasheet floor and the cold restarts remain |
| 9a | BQ25856-Q1 | TI | External-FET bidirectional buck-boost controller, 85 V, I2C + standalone | **M9 F** (about 40 ms compensation toggle at startup, SLUSFH5A section 7.3.3.3 p.22; /CE to current about 92 ms, 72-112 ms, Fig 8-7 p.66, 40 ms/div, figure reading; C_IN >= 80 uF, p.65) | Reject (W2 held in reserve with the BQ25756, section 4.4) | Automotive sibling of the BQ25756 (85 V absolute maximum, 4.4-70 V operating, 0.4-20 A, SLUSFH5A p.3, p.7); located 2026-11-10 under bq25856-q1.pdf after the bare bq25856.pdf returned HTTP 404 |
| 10 | RT9492 | Richtek | Integrated 4-switch buck-boost, NVDC, dual input | **M2 F** (VAC1/VAC2/VBUS/PMID 30 V abs max, 24 V operating, RT9492_DS-05 sections 12-13) | Reject (baseline second source) | Same 30 V ceiling and the same POR behaviour as the BQ25798 (autonomous 2 A charge, AUTO_MIVR = VBUS - 1.4 V at plug-in). Recorded as a functional BQ25798 alternate if the baseline is retained; not pin-compatible |
| 11 | RT9490S / RT9490 | Richtek | Integrated 4-switch buck-boost | **M2 F** (30 V abs max, RT9490S_DS-00 sections 11-12) | Reject | As RT9492, in a 2.93 x 3.46 mm WL-CSP |
| 12 | RT9478M | Richtek | External-FET NVDC buck-boost controller (BQ25713 class) | **M2 F** (VBUS/VSYS/CSIP/CSIN 30 V, RT9478M_DS-01 sections 10-11) | Reject | Also MIVR ceiling 19.52 V, re-derived at plug-in; SMBus with an 8-bit ADC |
| 13 | SGM41575 | SG Micro | Integrated 4-switch buck-boost | **M2 F** (VAC1/VAC2/VBUS 30 V, SGM41575 REV A.2 abs max table) | Reject | BQ25798-class architecture with the same rating gap |
| 14 | SC8815A / SC8815 | Southchip | External-FET 4-switch buck-boost controller, I2C, 10-bit ADC | **M9 F** (PSTOP low to charging: 220 ms typ / 330 ms max deglitch, SC8815A DS V1.1.0 p.12; SC8815 p.11), M6 c (PSTOP and /CE internally pulled low = enabled) | Reject | 40 V abs max, VINREG to 25.6 V and a POR input ceiling at the maximum code times RS1 are attractive, but the only pin inhibit is cold and the IC has no warm analog pin for H1 |
| 15 | SC8813 | Southchip | External-FET buck controller, I2C, 10-bit ADC | **M9 F** (PSTOP 220 ms deglitch, SC8813 DS p.11) | Reject | Buck-only sibling of the SC8815 with the same cold PSTOP path |
| 16 | SC8802 | Southchip | External-FET buck-boost controller, pin-programmed | **M10 F, M12 F** (no I2C, SC8802 DS pin table p.3-4) | Reject (reserve for an analog-only architecture) | Hardware CV (RCSEL 270 kOhm, 8.316-8.484 V, p.8) and hardware ILIM1/ILIM2 survive any POR, but runtime control and the host interface are absent; Chinese-only primary |
| 17 | LT3651-8.4 | ADI (Linear) | Integrated 4 A synchronous buck, fixed 8.4 V | **M8 F** (no input-voltage loop), **M10 F, M12 F** (no I2C, 36518284fa p.7-8) | Reject (reserve for an analog-only architecture) | Simplest layout and a true resistor-set input-current loop (CLP/CLN + ILIM, p.8, p.11), but the threshold loop and the host interface must be built on the CCB |
| 18 | LTC4020 | ADI (Linear) | External-FET 4-switch buck-boost charger controller, 55 V | **M10 F, M12 F** (no I2C, 4020fd p.8-9); M7 c (inductor-current ceiling only) | Reject | VIN_REG is a fixed divider that the datasheet cautions against for low-impedance sources (p.8); analog CSOUT monitor only |
| 19 | LTC4000 / LTC4000-1 (with a separate buck controller and an I2C monitor) | ADI (Linear) | Charge controller driving an external DC/DC through ITH | **M10 F, M12 F**; LTC4000: **M8 F** (no input-voltage loop); LTC4000-1: **M7 F** (no input-current loop) (4000fb p.1, p.8-10; 40001fa p.1) | Reject | Neither variant gives both M7 and M8; two-IC layout |
| 20 | LT8491 | ADI (Linear) | External-FET buck-boost MPPT charger, I2C, EEPROM | **M8 F** (input regulation owned by MPPT or absent in power-supply mode), **M9 F** (SHDN exit: EEPROM boot copy, CRC, soft-start, LT8491 Rev 0 p.18-19), M6 c (charge-enable preset from EEPROM) | Reject | Periodic panel scans would sweep a stiff 16 V bus (p.56) |
| 21 | LTC4162-L | ADI (Linear) | Integrated buck with PowerPath drivers, I2C | **M5 F** (no inhibit pin and no UVCL feedback pin; LTC4162-L Rev A p.21, p.23, p.27) | Reject (rejection now IC-intrinsic, RESCREEN section 3.10 resolved) | Every new charge cycle runs 2-4 s battery detection; 36 V abs max; ISW abs max 3.5 A at a 3.2 A ceiling |
| 22 | MAX17703 | ADI (Maxim) | External-FET buck charge controller, 65 V | **M7 F** (no input-current loop), **M8 F**, **M10 F** (19-100908 Rev 0 p.3-5) | Reject | Charge-current loop and EN/UVLO only |
| 23 | MP2759A / MP2759 | MPS | Integrated buck, resistor-programmed | **M4 F** (charge current "can be set up to 3A", MP2759A DS Rev 1.0 p.14-15; ROC p.5), **M9 F** (170 ms delay before the converter enables, p.13), **M10 F** | Reject (rejection was IC-intrinsic, RESCREEN section 3.9) | The MP2759A primary, missing on 2026-11-05, confirms the architecture |
| 24 | MP2769 | MPS | External-FET buck-boost controller, I2C/PMBus, 60 V | All U (primary behind an MPS account login; product page UNVERIFIED) | Not scorable; manual fetch requested | Only MPS part above 35 V with I2C. A forum report of a 10 A POR charge current (UNVERIFIED) would make HR4/HR5 rest entirely on pins. Marked "pre-release" by MPS |
| 25 | SY20776 / SY20779 | Silergy | External-FET NVDC buck-boost controllers | M2 likely F (3.5-25 V operation per snippet, UNVERIFIED); all other items U | Not scorable | Silergy pages return a server error; BQ25713 class by snippet |
| 26 | ISL81601 | Renesas | External-FET bidirectional buck-boost voltage controller | **M8 F** (FB_IN regulates the input only in reverse, FN9299 Rev 3.1 p.11-12), **M10 F** | Reject | Not a charger; EN/UVLO floats enabled |
| 27 | MCP19118 / MCP19119 | Microchip | Buck controller with integrated PIC | **M7 F** (no firmware-independent ceiling, DS20005350A section 4.1 and p.1) | Reject | Every charger function would be PIC firmware |
| 28 | LTC4013 | ADI (Linear) | External-FET buck controller, standalone | **M7 F** (charge-current loop only, 4013fa p.12), **M8 F** (fractional-VOC MPPT only, p.6), **M10 F** | Reject | Samples VOC every 10.2 s for 271 us |
| 29 | LT8705 / LT8705A | ADI (Linear) | External-FET 80 V buck-boost voltage controller | **M10 F** (no I2C, UNVERIFIED: primary blocked) | Reject | Not a charger IC; every limit is analog |
| 30 | Discrete buck controller + op-amp CC/CV/VINDPM + I2C monitor | Generic | External-FET buck with discrete charge control | **M8 F** under the section 1.2 reading (loop not in an IC); M3, M6 would rest on C/B evidence only | Reject (fallback only) | The only architecture in which warm response is fully under design control, but every charger-safety row moves from P to C/B |

### 2.2 Re-screened 2026-11-05 parts that stay rejected or unchanged

| Part | 2026-11-05 position | Result here | Reason (from RESCREEN, primary-cited via the R2 dossiers) |
|---|---|---|---|
| BQ25798 | Chosen (Path A) | Baseline, scored separately | Fails M2 as written (30 V); see section 5.2 |
| BQ25792 | Merged into BQ25798 | Baseline second source | Shares the BQ25798 EVM, the U1 footprint (VQFN-HR 29, BQ25792RQM) and the 3.6-24 V operating range, without MPPT and backup mode (SLUUCB5E p.3, p.19, p.23). Its datasheet SLUSDG1 (SLUUCB5E Table 1-1 p.3) was not obtained: every ti.com URL for the part, including the product page, returned HTTP 404 on 2026-11-10. Absolute maximum, ACOVP default and POR behaviour UNVERIFIED (the sibling BQ25790 defaults ACOVP to 7 V against 26 V for the BQ25798, SLUSDV2C Table 4-1 p.3); assumed to be the 30 V BQ2579x family. The TI store API listed BQ25792RQMR (10 964) and BQ25792EVM (131) on 2026-11-10 |
| BQ25713 | Runner-up | Reject: **M2 F** (30 V, SLUSD83C section 8.1 p.9) | Also VINDPM ceiling 19.52 V and AUTO_WAKEUP_EN = 1 at POR |
| BQ25720 / BQ25723 / BQ25731 | Rejected / "adds nothing" | Reject: **M2 F** (32 V, SLUSDU3 p.8; SLUSE66A p.8) | VINDPM ceiling 19.52 V; watchdog expiry loads 256 mA on the BQ25731 |
| BQ24650 | Rejected | Reject: **M2 F** (33 V, SLUSA75B p.5), **M9 F** (1.5 s MPPSET release), **M10 F** | IC-intrinsic |
| BQ25672 | Screened out | Reject: **M2 F** (30 V, SLUSEB9B p.7), **M4 F** (3 A) | IC-intrinsic |
| MAX77960 / MAX77961 (B and non-B) | Screened out | Reject: **M2 F** (CHGIN 30 V, 19-101123 Rev 0 p.2-3 for the B parts; non-B UNVERIFIED) | IC-intrinsic |
| LT8490 | Screened out | Reject: **M8 F, M9 F, M10 F** (LT8490 Rev A p.1) | Autonomous MPPT start-up, no I2C |

## 3. Quick-dismissal list

The sweeps dismissed the following parts on a single must-have or on scope. A dismissal marked UNVERIFIED rests on a
secondary source; none of these parts was a candidate for a finalist position, so no spot-check was made.

| Group | Parts | Dismissal |
|---|---|---|
| TI notebook and NVDC class | BQ25713(B), BQ25710, BQ25700A, BQ25703A, BQ25720, BQ25723, BQ25731, BQ24725A, BQ24735, BQ24780S, BQ24800, BQ24171, BQ24172 | M2 F: 30-32 V abs max (SLUSD83C p.9, SLUSD20B p.9, SLUSCQ8A p.8, SLUSCU1A p.9, SLUSDU3 p.8, SLUSE64 p.8, SLUSE66A p.8, SLUSAL0C p.4, SLUSAK9B p.4, SLUSC27C p.5, SLUSDO8A p.6, SLUSAF2C) |
| TI BQ2579x / BQ2567x | BQ25790, BQ25792, BQ25672 | M2 F: 30 V. BQ25790: SLUSDF9 p.7. BQ25672: SLUSEB9B p.7; also M4 F. BQ25792: UNVERIFIED; inferred from both siblings (SLUSDF9 p.7, SLUSDV2C p.7) and from SLUUCB5E p.3, which lists its datasheet as SLUSDG1 and gives 3.6-24 V operation; every ti.com URL for the part returned HTTP 404 on 2026-11-10 |
| TI standalone | BQ24610, BQ24617, BQ24630, BQ24650, BQ25306, BQ25308 | M2 F (28-33 V) and M10 F |
| TI wrong topology or cell count | BQ25883, BQ25887 (2S boost from 5 V); BQ25616, BQ25619, BQ25622, BQ25630, BQ25611D (1S); BQ25751 (lead-acid only); BQ25758 (DC/DC without charge profile, SLUSFN3B Table 4-1 p.3); BQ25853-Q1 (supercapacitor backup) | Out of scope |
| TI part numbers without a datasheet | BQ25770 (non-G), BQ25680, BQ25821, BQ25823, BQ25855, BQ25771/2/4 | HTTP 404 at ti.com/lit with and without the -q1 suffix; not located (UNVERIFIED). The BQ25856 is located as the BQ25856-Q1 (row 9a) |
| ADI/Maxim low rating or low current | MAX77962, MAX77963, MAX77787, MAX77789 (30 V class, UNVERIFIED); LT3652HV and LT3652 (2 A, M4 F); LT3650-8.4 (2 A); LTC4121 (400 mA); LTC4008 (28 V); LTC1760 (32 V); LTC4012, LTC4009, MAX1873, MAX8731, MAX8765, MAX17435 (28 V class, UNVERIFIED recollection); LTC4155, LTC4156 (1S); LTC4162-F/-S (wrong chemistry); LT8708 (not a charger); MAX17702 (lead-acid controller, no I2C, UNVERIFIED) | M2, M4, M10 or scope |
| MPS | MP2760, MP2761 (26 V DC abs max, 22 V operating, read); MP2651, MP2652, MP2762A, MP2650, MP2764, MP2765 (28 V class, UNVERIFIED); MP2658 (3 A, standalone); MP2659 (3-6 cell); MP26123, MP2619, MP2612, MP26124, MP2610, MP26101, MP2623, MP2615(A) (2 A, 26 V); MP2618 (NRFND, UNVERIFIED); MP2672(A), MP2639A/C (2S boost from 5 V); MP2731, MP2733, MP2723, MP2720, MP2668 (1S); MPQ4214 (not a charger) | M2, M4, M13 or scope |
| Richtek | RT9467, RT9466, RT9471, RT9759 (1S); RT9426 (fuel gauge) | Scope |
| Silergy | SY6970, SY6974, SY6981 (1S); SY6982, SY20762, SY6923 (2S boost, UNVERIFIED); SY6926, SY6990 (power bank); SY20783 (2 A); SY6912A, SY20741, SY6935 (<= 23 V or <= 3.5 A at <= 14 V); SY20745 (no datasheet) | M2, M4 or scope (UNVERIFIED snippets) |
| Renesas | ISL9241 (30 V, FN8945 section 2.1); ISL9238/C (28 V, FN8877 p.9); ISL9237 (28 V, FN8723 p.7); ISL95338, RAA489800 (voltage regulators, about 23 V); RAA489300 (3-level buck voltage controller, not a charger; noted as a possible custom-charger core); ISL81401, ISL81801, ISL78268, ISL78226 (generic controllers); ISL78693 (1S) | M2 or scope |
| onsemi | NCP1855, NCP1851, NCP1854, FAN54xx (1S); NCP1871 (Obsolete, UNVERIFIED); NCP81239 (USB-PD regulator); LC709xxx (fuel gauge) | Scope or M13 |
| ST | L6924D/U, STBC02, STNS01 (1S linear); SPV1040, SPV1050 (harvesters); PM6610, PM6613N, PM6611N, PM6612 (24 V class, Obsolete per snippet, UNVERIFIED); L5965 (PMIC) | Scope, M2 or M13 |
| NXP | MC34671, MC34673, MC32BC3770, PCA9420 (1S or PMIC); MC33772 (cell monitor) | Scope |
| Microchip | MCP73213 (18 V linear, UNVERIFIED); MCP73841-844 (12 V class); MCP73871, MCP73123, MIC79110 (1S); MCP19124/5, MCP19111 (custom PIC firmware) | Scope or M7 |
| Southchip | SC8886, SC8885 (24-29 V class, UNVERIFIED); SC8816 (not found); SC8812A (abs max unconfirmed; superseded by SC8815A); SC8902A, SC8906 (22 V class, UNVERIFIED); SC89601, SC89890, SC8960x, SC8551 (1S); SC8701, SC8703, SC8721 (converters, not chargers) | M2 or scope |
| Other Chinese vendors | Injoinic IP2368, IP2366, IP2326, IP5389 (30 V abs max, autonomous power-bank SoCs); SG Micro SGM41541/2/3 (1S, 22 V), SGM41527 (30 V standalone); Halo HL7139, HL7019 (1S); ETA ETA6003, ETA9640, ETA9697; Awinic AW32xxx; Nuvolta, Cellwise, Chipown, Joulwatt, Hynetek, Analogy, ConvenientPower (no qualifying part found) | M2, M6 or scope |
| Infineon | No standalone multi-cell Li-ion charger IC found | Scope |
| Incumbent | Silvertel Ag105 | Fails HR1 structurally at 2S and needs VBat- isolation (battery isolation feasibility, 2026-11-07) |

## 4. Finalists

### 4.1 Provisional scores

The table gives a provisional weighted score (CRIT section 3.1, with the section 3.2 evidence cap) so that the finalist
order is traceable. scoring.md replaces these values with dossier-backed scores. The BQ25798 row uses the same rules
and the 2026-11-05 record (EVAL section 1.3, WD); its S6 count is provisional (TODO(verify: WD section E)).

(Superseded 2026-11-10 by scoring.md sections 2.6 and 7: the dossier-backed totals are BQ25798 40.3, BQ25690 48.3, BQ25773
49.0, LTC4015 design B 46.0, RAA489110 35.7. The provisional values below are kept as the screening record only.)

| Criterion (weight) | BQ25798 (baseline) | BQ25690 | BQ25773 | LTC4015 | RAA489110 |
|---|---|---|---|---|---|
| S1 warm response (15) | 1 | 2 (B: typical curve) | 1 | 2 (B: R2 reading of p.18, p.31-32) | 1 |
| S2 fail-safe POR (10) | 0 | 1 | 2 | 1 | 2 |
| S3 ceiling quality (8) | 2 | 2 | 2 | 1 | 1 |
| S4 threshold quality (8) | 2 | 2 | 2 | 3 | 1 |
| S5 inhibit latency (7) | 1 | 1 | 2 | 1 | 1 |
| S6 interlock adders (10) | 1 | 2 | 2 | 1 | 3 |
| S7 telemetry (5) | 2 | 2 | 2 | 2 | 2 |
| S8 FC-mode fitness (6) | 2 | 2 | 2 | 0 | 1 |
| S9 rating margin (4) | 0 | 2 | 2 | 1 | 0 |
| S10 layout (7) | 1 | 1 | 0 | 1 | 0 |
| S11 package (3) | 1 | 1 | 2 | 2 | 1 |
| S12 stock (5) | 3 | 2 | 2 | 1 (U) | 1 (U) |
| S13 cost (2) | 3 | 3 | 1 | 1 | 1 |
| S14 round-6 findings (5) | 2 | 2 | 2 | 2 | 2 |
| S15 input capacitance (3) | 2 | 3 | 2 | 3 | 1 |
| S16 topology barrier (2) | 1 | 1 | 0 | 3 | 0 |
| **Provisional total (of 100)** | **about 45** | **about 59** | **about 55** | **about 49** | **about 42** |

The margins are provisional. Only the BQ25690 clears the 10-point margin of CRIT section 3.5 on these scores, and its S1
score rests on a typical curve taken in boost mode at a 5 V input, not in buck mode at 16-21 V.

### 4.2 Finalist list

| Rank | Part | Mechanism class | Why it is a finalist |
|---|---|---|---|
| 1 | BQ25690 (TI) | Integrated buck-boost, external sense resistors | The only integrated part that clears M2 (45 V abs max, VIN_OVP 35.5 V min). /CE is a warm inhibit: the converter keeps regulating SYS in PFM. The CELL, VCHG and ICHG straps clamp VREG and ICHG at POR, which may close round-6 finding 1 (TODO(verify: SLUSFN4A VREG clamp semantics)). C_IN of 1.8 uF minimum fits the H8 budget with margin (superseded: CVIN >= 10 uF after derating, dossier_BQ25690.md section 1.4). Open: the ILIM ceiling range (section 1.3), FORCE_VINDPM reset by the watchdog, battery detection at start-up against D-BT-SQ, buck-mode warm response |
| 2 | BQ25773 (TI) | External-FET NVDC buck-boost controller | Reopened from 2026-11-05. Strongest intrinsic HR5 record of the TI set (no charge out of POR, no NVM), 45 V abs max, VINDPM +-1 % at 18 V, and an on-chip comparator whose FRC_CONV_OFF output can host the H1 trip with a 1 us deglitch. Open: HIZ and FRC_CONV_OFF exit latency, single-phase or BATFET-less build, POR VINDPM 3.2 V (S16 0), 226 ms cold start (always-powered mandatory) |
| 3 | LTC4015 (ADI) | External-FET buck controller with I2C | Reopened from 2026-11-05 under a declared exception (section 4.3). Unique fail-safe input threshold: the UVCL POR value is the divider maximum, so every charger POR lands in a regen-only state; register writes can only lower it. Buck with a documented VIN-BATSENS differential UVLO (140-250 mV, 4015fb p.4), so S16 is the highest in the set. Open: M3, the clamp-FET inhibit latency, the motherboard bridge for battery detection, no host watchdog, lifecycle |
| 4 | RAA489110 (Renesas) | External-FET NVDC buck-boost controller, non-TI | The only non-TI part that passes the must-haves with an ADC. Mechanism diversity: the inhibit pin (BATGONE) defaults to inhibit through an internal pull-up current source and needs one external N-FET to permit, the smallest adder count in the set. Open: the inhibit opens the battery FET rather than the converter, VIN register step 128 mV, 30 V operating ceiling, BGATE turn-off latency against the 115 us budget, stock. RAA489118 and RAA489108 are covered as alternates in the same dossier |

Mechanism diversity: one integrated buck-boost, one external-FET buck controller, and two external-FET NVDC buck-boost
controllers from two vendors. No integrated buck with I2C and a 35 V rating survived the screen (the LT3651-8.4 and the
MP2759A fail M10; the LTC4162-L fails M5), and no controller-plus-monitor architecture passes M8 and M10 (section 1.2).

### 4.3 Declared exception: LTC4015 and M3

The LTC4015 fails M3 as written by 21 mV at the upper limit (section 1.3). This screen carries it as a finalist for three
reasons:

1. Without it, no external-FET buck controller with I2C survives, and the buck class carries the S16 hardware no-charge
   floor that CRIT section 4.8 credits.
2. The excess is recoverable in the upper direction by one DAC code (4.1875 V/cell gives 8.270-8.480 V). The cost is a
   lower bound 0.55 % below the M3 band, that is, a slightly lower full-charge voltage. Pack over-voltage is backstopped by
   the BQ29200 OVN term (R6 finding 1).
3. The 2026-11-05 evaluation ranked it first in round 1 and as runner-up in round 2; a dossier preserves that record.

Under CRIT section 3.5 condition 1, the LTC4015 cannot be recommended over the BQ25798 unless the operator rules on M3
(either accepting the 4.1875 V/cell setpoint or widening M3 to +-1.25 %). This is open item R-M3.

### 4.4 Parts held in reserve

| Part | Reserve role | Condition that would promote it |
|---|---|---|
| BQ25820 | Buck controller with the strongest hardware POR anchors | A primary-backed warm analog inhibit (for example an ACUV-node window between VREF_ACUV and the VDPM reference) that stops current without a restart, and an input-capacitance scheme for the >= 80 uF minimum |
| RT9492 | Functional BQ25798 alternate (30 V class) | The baseline is retained and a second source is wanted |
| LT3651-8.4, SC8802 | Analog-only architecture with a CCB VINDPM loop and an I2C monitor | The operator relaxes M10/M12 and accepts a CCB-built input-voltage loop |
| MP2769 | 60 V I2C buck-boost controller | The primary datasheet is fetched by hand and shows a pin-set input ceiling and a non-charging POR |
| BQ25756, BQ25756E, BQ25856-Q1 | External-FET buck-boost controllers whose pin stops fail M9 (rows 9, 9a) | The RESCREEN section 3.7 option W2 (ILIM_HIZ held at about 3.0 V, between VREF_ILIM_HIZ 2.0 V typ and VIH_ILIM_HIZ 3.7 V min, SLUSEN5A p.10) passes bench gate B10 of the round-2 dossier A1 on an EVM (I_IN < 10 mA, recovery <= 4 ms, REGN up), and an input-capacitance scheme meets the >= 80 uF minimum. W2 has a primary basis for its premise only: a pin voltage above VREF_ILIM_HIZ enters input-current regulation (SLUSEN5A section 6.3.5.1.1.1 p.29), DPM reduces the charge current to zero (section 6.3.5.1 p.28), and REGN stays enabled while charge is enabled and HIZ is not entered (sections 6.3.3.2 and 6.3.3.6, p.21-22). The recovery time, the residual input current and the pin's tolerance of an external drive are not specified (UNVERIFIED). The 40 ms toggle is stated for startup (p.21); its recurrence on every /CE start is a missing primary (dossier A1 section 11) |

## 5. Items carried into the dossiers and the scoring

### 5.1 Items each finalist dossier must close

1. Minimum on-time against duty 0.13-0.27 at the chosen switching frequency (CRIT section 4.8 item 4).
2. Internal resistance at 3.21 A, replacing the 100 mOhm assumption of CRIT section 4.3.
3. The S6 adder list, counted against the WD section E baseline.
4. Inhibit exit and warm-response evidence class (P, B or U) for S1 and S5.

### 5.2 Baseline rating

The BQ25798 fails M2 as written (30 V on VAC1/VAC2/VBUS). Either M2 admits the 22.28 V TL431/BSP170P clamp as a protected
standoff for the baseline, or the scoring records the baseline as an M2 failure. The second reading would strengthen
every finalist with a 36-45 V rating. The scoring must state which reading it applies.

## 6. Blocked fetches

The following fetches failed during the sweeps. The operator may fetch them by hand.

- https://www.ti.com/product/BQ25690 (and /BQ25820, /BQ25822, /BQ25773, /BQ25756E, /BQ25750): HTTP 403 to WebFetch and to
  curl with a browser user agent; lifecycle status, 1ku price and package options were not retrieved. Lifecycle was taken
  from each datasheet's orderable addendum instead.
- https://www.ti.com/power-management/battery-management/charger-ics/products.html: fetched, but contains no part table.
  The parametric selector https://www.ti.com/en-us/product-category/battery-management-ics/battery-charger-ics/products
  was not fetched (JavaScript-rendered; 403 expected). An export of the parametric table (Li-ion, 2 cells, VIN max >= 30 V)
  would confirm that no TI part was missed.
- https://www.ti.com/lit/ds/symlink/bq25792.pdf, bq25770.pdf, bq25680.pdf: HTTP 404 with and without -q1 (not located).
  For the BQ25792, https://www.ti.com/lit/gpn/BQ25792 and https://www.ti.com/product/BQ25792 also returned HTTP 404.
  bq25856.pdf: HTTP 404; bq25856-q1.pdf: HTTP 200 (screened, row 9a).
- TI store opninventory for BQ25853QRRVRQ1: Akamai "Access Denied" (wrong OPN; the datasheet OPN is BQ25853QWRRVRQ1, not
  retried).
- TI E2E question (not a fetch): BQ25690 RILIM_HIZ minimum 4.6 kOhm (SLUSFN4A ROC p.6) against the KILIM test point at
  IIN_MAX = 1.6 A and the 3.32 kOhm worked example (p.9, p.26). This decides whether the hardware input ceiling reaches
  1.21-1.6 A at 10 mOhm, and whether the 5 mOhm / RAC_SNS = 0 arrangement of section 1.3 is the intended use. (Superseded
  2026-11-10: dossier_BQ25690.md section 1.4 reads the recommended range as 0-33 kOhm, so the 4.6 kOhm premise of this
  question no longer holds; the open E2E items are those of dossier_BQ25690.md section 15.)
- https://www.analog.com/media/en/technical-documentation/data-sheets/LTC4020.pdf: curl and WebFetch time out. All
  ADI/Linear PDFs in this sweep were read from vendor PDFs mirrored on rlocman.ru or datasheet.chipsmall.com (LTC4015
  Rev B 4015fb, LTC4020 Rev D 4020fd, LT8491 Rev 0, LT8490 Rev A, LT3652HV Rev B, LT3651-8.x Rev A, LTC4000 Rev B,
  LTC4000-1 Rev A, LTC4013 Rev A, LTC4162-L Rev A, LTC4008, LTC1760, LTC4121). Confirm the revisions against analog.com.
- https://assets2.analog.com/cdp/onlinedatasheet/max77960-en/absolute_maximum_ratings.html: WebFetch timeout, curl exit 35.
- https://wcm-cce.cldnet.analog.com/media/en/technical-documentation/data-sheets/max77962.pdf: no response (MAX77962 abs
  max unread).
- https://www.analog.com/en/products/ltc4015.html, /ltc4020.html, /lt3651-8.4.html, /ltc4000.html, /max17703.html:
  lifecycle status and pricing unreadable; all M13 and stock entries for these parts are TODO(verify).
- Distributor stock and price pages (Mouser, Digi-Key) for LTC4015EUHF, LTC4020EUHF, LT3651EUHE-8.4: not attempted after
  the analog.com failure; the prior round reported Mouser DNS failures and timeouts.
- LTC4012, LTC4009, MAX1873, MAX8765, MAX17435 primary datasheets: radiolocman part pages returned no document link; these
  dismissals rest on UNVERIFIED recollection.
- MP2769 datasheet (MPS): the "pre-release" datasheet button on https://www.monolithicpower.cn/cn/mp2769.html and
  https://www.monolithicpower.com/jp/mp2769.html opens an MPS+ login popup; no public mirror found. Highest-value manual
  fetch in the sweep.
- All monolithicpower.com documentview URLs (for example
  https://www.monolithicpower.com/en/documentview/productdocument/index/version/2/document_type/Datasheet/lang/en/sku/MP2762AGV/):
  HTTP 200 serving a 3 kB JavaScript client-challenge page to curl.
- MP2762A datasheet: https://datasheets.ibselectronics.com/MP2762AGV-XXXX-Monolithic-Power-Systems-datasheet-156108905.pdf
  returned a 5.7 kB HTML page.
- MP2650 / MP2770 datasheets: https://www.mouser.lt/pdfDocs/MP2650.pdf and https://www.mouser.lt/pdfDocs/MP2770GL.pdf
  returned a 13.9 kB HTML block page.
- Richtek legacy asset URLs https://richtek.com/assets/product_file/RT9490/DS9490-01.pdf, .../RT9492/DS9492-04.pdf and
  .../DS9492-01.pdf: HTTP 404 (superseded by the /content/dam/ paths, which worked).
  https://mouser.com/datasheet/2/1458/DS9492_03-3514018.pdf returned an HTML block page.
- Silergy product pages https://www.silergy.com/productsview/SY20776QFQ, https://www.silergy.com/productsview/SY20779QFQ
  and https://us1.silergy.com/productsview/SY20779QFQ: PHP TypeError page; https://silergy.com/list/Battery+Chargers and
  /list/Switching+Battery+Chargers: "category does not exist". No Silergy multi-cell charger datasheet was obtained.
- Stock, price and lead time for RT9492, RT9478M and MP2759A: not attempted (Mouser, Digi-Key and Octopart blocked to
  curl and WebFetch in the earlier round).
- https://www.st.com/resource/en/datasheet/pm6610.pdf and pm6613n.pdf: curl and WebFetch time out;
  https://www.st.com/en/power-management/pm6610.html and pm6613n.html: WebFetch timeout 60 s.
- https://www.onsemi.com/pdf/datasheet/ncp1871-d.pdf: returned an HTML documentation shell instead of the PDF.
- Microchip MCP19118/19 current datasheet: only DS20005350A (2014) was retrievable
  (https://ww1.microchip.com/downloads/en/DeviceDoc/20005350A.pdf); newer revision URLs returned HTML.
- SC8886 / SC8886S primary datasheet: not located; only the Wurth Elektronik reference-design page
  https://www.we-online.com/en/components/icref/southchip/SC8886S-SC8886S-Demo-Buck-Boost. Southchip applications support
  (application@southchip.com) may supply it.
- LCSC live stock and price pages (https://www.lcsc.com/product-detail/C252406.html for SC8802; C727913 for SC8813;
  C429908 for SC8815): rendered without stock, price or lifecycle fields; SC8815A LCSC C-number not found.
- https://wmsc.lcsc.com/wmsc/upload/file/pdf/v2/lcsc/*.pdf links return a JavaScript redirect stub; the redirected
  datasheet.lcsc.com URL works with curl.
- SC8802 English full datasheet: only a brief exists
  (https://uploadcdn.oneyac.com/attachments/files/brand_pdf/southchip/17/67/SC8802_datasheet_brief_en.pdf, not read); the
  full LCSC datasheet is Chinese and its descriptive text was lost in extraction. A Chinese-capable read of pages 3-4 and
  10-16 is needed.
- SG Micro 30 V SMBus buck-boost document https://www.sg-micro.com/uploads/soft/20240417/1713322314.pdf: non-PDF (HTML)
  response; part number unknown.
- https://www.analog.com/media/en/technical-documentation/data-sheets/LT8491.pdf: WebFetch and curl time out (needed for
  LT8491 SHDN/EEPROM power-up, input-current limit, MPPT disable).
- https://www.analog.com/media/en/technical-documentation/data-sheets/LTC4000.pdf: timeout (mirror rev 4000fb used).
- https://www.analog.com/media/en/technical-documentation/data-sheets/LT8705.pdf (and LT8705A): timeout.
- https://www.analog.com/media/en/technical-documentation/data-sheets/max17702.pdf: timeout.
- https://www-cce.cldnet.analog.com/media/en/technical-documentation/data-sheets/{MAX17702,ltc4013,LT8491,LT8705,LTC4020,LTC4000}.pdf:
  ADI CDN mirror also unreachable.
- https://www.ti.com/lit/ds/symlink/lm5148.pdf: ti.com returned an HTML block page (403) after the BQ25820/BQ25756
  downloads (needed for the discrete-buck option).
- https://www.ti.com/lit/ds/symlink/ina238.pdf: same TI 403 (needed for the telemetry-monitor common-mode rating).
- https://www.radiolocman.com/datasheet/pdf.html?di=168165 (LT8491 mirror): page viewer serves images only.
- TI BQ25820 product page (stock and price): not attempted after the ti.com 403.
- SLUSFN3B Fig 8-5/8-7 (p.67) time-base label: illegible at the rendered resolution; read the CE-to-ICHG delay by hand.
- Renesas RAA489110 primary (R16DS0212EU0202 Rev 2.02): read by the sweep but no local copy is in the scratch folder; the
  dossier author must re-fetch it.
