# Custom BQ25798 charger board in the CHG footprint: design document (2026-11-10)

**Status:** revision r2 (2026-11-10). Table 0.9 (§0.9) records the revisions.

## 0. Status, scope and verdict

### 0.1 Status and scope

This document is a design document only. No part is ordered, no firmware is changed and no KiCad capture is made. All
proposed changes to repository files are listed in §5.10 and are not applied.

This document defines a **custom charger board (CCB)**. The CCB is one printed-circuit board that plugs into the 22 holes of
the Silvertel Ag105 (BOM designator CHG) on the motherboard (MB) rev 20260622. The Ag105 module sits raised above the MB, so
the CCB can extend sideways past the CHG footprint (§1.2).

The CCB carries the BQ25798 charger IC and its power stage, the interlock logic of the round-3 carrier (CR) and the drivers
of the round-3 EVM interface board (EIB). The CCB therefore removes the off-board BQ25798EVM, its 0.3 m leads and their
length limits, the EIB with its ribbon, and the EVM modifications. The study lists 11 EVM modifications ([EVAL] §4.2
M1-M11), which round 3 superseded with EM1-EM25 ([WD] C); §2.4 gives the disposition of each.

The design rests on the following constraints:

1. The pack is 2S, 7.4-8.4 V. Pack negative is PCB GND by design ([WD] A.6).
2. V-MOT reaches 21.2-21.5 V measured, with a design clamp of 21.98-22.28 V ([WD] C, EM14). Every external input-side part
   is therefore rated 35 V or more (§2.1.4).
3. The charge current is 2.5 A today and 3.10 A in the regen image. With the +3.5 % ICHG tolerance, the battery-side
   copper is sized for 3.21 A ([WD] A.3).
4. FC charging follows the operator ruling of 2026-11-08: no FC charging during or just before a purge, a preemptive
   share shift to the battery, and EMS-requested charging between purges. The firmware requirements FR-14 to FR-17 carry
   this ruling unchanged (§5.2; [WD] F.4).
5. The LM1084 (REG-5V) courtyard is 1.75 mm to the right of the CHG silk outline. The LM1084 is 4.83 mm tall and runs
   hot. The CO-5V silk touches the CHG silk outline. J-NTC and J-BL are to the left, and J-BL must stay serviceable
   ([MECH] §2.1, §7; §1.2).
6. The vehicle does not move. It sits on a testbench and drives flywheels (operator statement, 2026-11-10). This fact
   supersedes the r1 constraint "the CCB sits on a moving vehicle, for which no vibration specification exists".
   Retention therefore covers handling, probing and repeated insertion only (§1.7). Two further facts of the same
   statement apply:
   - **6a.** A fan may be mounted on the CCB. The fan takes its supply from the bench supply or from its own regulator,
     never from the LM1084 / CO-5V rail ([LC] §8.10; §1.2.3).
   - **6b.** The CCB has no height restriction. The free height H_env becomes a record-only value, and gate D-2 no longer
     constrains the CCB height (§1.3.2, §1.3.3).
7. A parallel study searches for alternative charger ICs. The IC-independent content is therefore kept separate from the
   BQ25798-specific content (§0.6).

### 0.2 Relationship to other documents

This document adds a third design path beside the two round-3 paths. It does not replace any existing document.

| Document | Content | Relationship |
|---|---|---|
| `docs/charger_bq25798_wiring_design_2026-11-05.md` ([WD], round 3 r6) | **Path A**: BQ25798EVM with modifications EM1-EM25, carrier CR in the 22 CHG holes, EIB on a ribbon, leads W1-W8 | Stays the Path A design. The CCB reuses its netlist values (B.1-B.8), register images (G.1), firmware requirements (G.2) and test registry (section I) |
| `docs/charger_replacement_evaluation_2026-11-05.md` ([EVAL]) | Charger study: rulings, requirements HR1-HR5, loop analysis, **Path B** (MB re-spin) | Stays the study and the Path B record. The CCB meets HR1-HR5 through the carried-over interlock (§1.12) |
| `docs/battery_isolation_feasibility_2026-11-07.md` | Battery isolation with the Ag105 kept; gate D-2 (Ag105 standoff height, unmeasured) | Gate D-2 is not a CCB gate. In r1 the standoff height was a measurement for the CCB envelope (§1.3.3, M1). In r2 it is record only, because the CCB has no height restriction (operator statement, 2026-11-10) |
| `docs/reviews/charger_eval_2026-11-05/round3/review_loop.md` ([LOOP]) | Six review rounds of the round-3 design | §7.2 dispositions all 203 finding keys against the CCB |

### 0.3 Verdict

The CCB is a feasible design path on paper. It is not shown to be feasible in hardware. Path A is not shown to be
feasible in hardware either, because its round-3 design was not audited ([EVAL] 0.1a).

The CCB removes the root cause of 29 of the 203 round-3 review findings, including the one blocker and 11 majors (§7.2.2).
It deletes the 0.3 m leads, the ribbon, the EIB and the 17 physical EVM modifications. On the recorded allowances, two
populated CCBs cost USD 470-745, against USD 505-540 for Path A (§4.5.3). However, the test plan needs four populated
boards (vehicle, spare, FI1 and LOOP1, §6.1.4). These cost USD 652-927, which is USD 112-422 above Path A before the LOOP1
layout variant is priced (§7.1.3). The r2 figures include the bench fan, its mount and the tall-stack headers (§4.5.2). The fault-injection build of Path A is not priced either. Cost therefore does not
favour the CCB.

However, the CCB costs about 70-155 h more effort than Path A. It delays the first bench charge from about 1-3 weeks to
about 7-13 weeks (§7.1.2, §7.1.4). These are base figures. One re-spin of the CCB (AS-9) adds about 26-62 h and 3-6
weeks. Condition 1 below places the Path A bench gates before the CCB. That sequence needs about 599-1032 h, and its first
CCB bench charge comes after about 12.5-21 weeks (§7.1.9). The CCB opens 27 new items (N-01 to N-27), of which 12 are proposed as major (§7.2.6). Its main risks are
listed below:

1. a first-pass layout of a 0.4 mm-pitch package (TI publishes no EVM layout files, but the TIDA-050047 reference design
   publishes an Altium project and 4-layer Gerbers of a BQ2579x power stage, transcribed in §3.4.7; §7.1.6);
2. about 2.7 W of loss at 13.4 mm from the courtyard of the hot LM1084, measured from the power cell edge (§1.6.1,
   §3.7). With the bench fan on over both sides at 2 m/s and g 5 mm, the junction is 49-61 C above room air. With the
   fan stopped, it is 79-117 C above room air, so the FR-50 trip must act ([LC] §8.6, §8.7; §3.7.2a);
3. 3.21 A through header pins of unverified current rating (§3.3);
4. retention of an 8-13 g board on a tall cantilevered stack during handling, probing and repeated insertion (§1.4,
   §1.7). The r1 form of this risk (a vehicle without a vibration specification) is superseded by the testbench facts
   (operator statement, 2026-11-10; §0.1 item 6).

**Verdict: the CCB is not the next step.** Path A stays the next step while the BQ25798 behaviour gates are open and while
the parallel IC search can still change the IC (§7.3.2). The operator can choose the CCB when all of the conditions below
are true:

1. The IC is fixed by bench evidence: the gates T-B-06, T-B-09, T-B-10, T-B-12 and T-B-21 pass, and the IC search keeps
   the BQ25798. Four of these gates need the modified EVM, the EIB and the CR of Path A (§7.3.3). §7.1.9 gives the effort,
   cost and schedule of this sequence.
2. The seated stack gives an underside air gap g of 5 mm or more, and preferably 5-8 mm (H_u 5.1-8.1 mm), so that the
   fan air passes under the power cell (§1.3.2 rule 3; [LC] §8.9). T-K-04 measures the seated H_u (M3). The r1 form of
   this condition (T-K-01 H_env at least the planned stack plus 1 mm, and h_k <= 5.0 mm) is superseded by the testbench
   facts: the CCB has no height restriction (operator statement, 2026-11-10). H_env is a record-only value.
3. The fan-on and fan-off soak T-K-20 (with its fan-on leg T-K-14; M15-M17) passes. With the fan on at 2.9 W, TDIE
   is 100 C or less at the measured room air, with 2 m/s or more in the gap and over the top (M15). With the fan
   stopped, the FR-50 trip acts before TREG_STAT (REG1D bit 2, [DS] Table 7-38) sets. The derate alone does not hold
   100 C ([LC] §8.7). The model gives 78-90 C on a 25 C bench at g 5 mm and 2 m/s over both sides ([LC] §8.6;
   §3.7.3a). Air through the gap only gives 88-115 C at 2.9 W, so the top flow is part of this condition ([LC] §8.6).
   No gap pad is needed. T_MB,0 is not decisive: with the fan on, T_J moves by 0.15-0.30 C per C of MB idle offset
   ([LC] §8.6b). r1 record, superseded by the testbench facts (operator statement, 2026-11-10): T-K-02 had to show
   T_MB,0 at or below the admissible value of §3.7.3. That value was 14-29 C for option S without the pad, 28-45 C
   with it, and 16-35 C for option K (h_k 3.0 mm) with a compressed k 3 pad.
4. A PCBA service with an inspection method for the hidden U501 joints is available (B-7).

Before the CCB PCB is ordered, three further conditions apply:

1. The capture closes L-1, L-11 and L-12 (area, power-cell fit and battery-path corridor) in a courtyard DRC.
2. The header pins and, for option K, the socket contacts are rated 3 A or more on pins 4 and 10 and 2.0 A or more on
   pins 14, 15, 18 and 19 (O-10).
3. A review loop on this document closes without an open blocker (§7.2.5 item 2).

When these conditions hold, the CCB is the preferred path if the T-G drive-cycle tests must run on the testbench with
a durable installation in place of chassis-mounted leads (§6.4.4, §7.3.2). If T-K-20 or T-K-17 fails, Path B1 is
preferred. B1 places the charger by design and carries the battery current in MB copper. On the testbench, T-K-02 is
record only and T-K-19 is not applicable. A hybrid sequence
is also possible: one stock BQ25798EVM (USD 156.45) runs the IC-behaviour subset of §6.5.3 while the CCB is designed and
fabricated (§7.3.3).

### 0.4 Labels

Every subsection and every table row carries one of these labels:

- **IC-independent (I):** the item carries over to any charger IC that fits the same outline and meets the interface
  contract of §1.14. Examples: the 22-pin header, the eFuse, the comparators, the permit logic, the heartbeat, the pack-OV
  term, the taps and the ground scheme.
- **BQ25798-specific (S):** the item exists because of a BQ25798 pin or behaviour. Examples: the power stage, PROG, the
  ILIM_HIZ network, the /CE drive with pull-ups to REGN, the QUAL one-shot and the REGN-anchored pin senses.
- **Mixed (M):** a generic function implemented with BQ25798 values.

### 0.5 Reference designators

- **3xx = ex-carrier (CR) parts.** Round-3 CR designator X1nn becomes X3nn (U101 -> U301, R175 -> R375, C102a -> C302a).
- **4xx = ex-EIB stages.** Round-3 EIB designator X2nn becomes X4nn (U201 -> U401, R272b -> R472b). The EVM-mounted ILIM
  guard parts R256 and C252 become R456 and C452.
- **5xx = charger power stage and charger pins (ex-EVM).** EVM designator Xnn becomes X5nn (U1 -> U501, L2 -> L501,
  C29 -> C529). New parts without an EVM predecessor take free 5xx numbers.
- **H301** is the 22-pad CHG header footprint. Its pad numbers are the Ag105 pin numbers ([WD] A.2; [MECH] §1).
- **F01-F24** are the tap pads. Their names are unchanged from [WD] A.4, so the MB rework documents stay valid.
- Net names reuse the round-3 names wherever the meaning is unchanged ([WD] B.8). MB net names are given in quotes where
  they differ from the board net names.

In text proposed for files outside this document (the IO CSV, CLAUDE.md, WORK_QUEUE.md), the CCB is written "charger
board", because those files do not define the abbreviation.

### 0.6 Separation of IC-independent and BQ25798-specific content

Section 1 is the IC-independent base. The BQ25798-specific design is section 2. Sections 3 to 7 mix both kinds of content
and label each subsection. Table 0.6 shows where each kind of content sits, so that another charger IC can replace only the
BQ25798-specific parts.

| Content | IC-independent (I) | BQ25798-specific (S) |
|---|---|---|
| Mechanics, outline, header, feet, keep-outs, retention | §1.1-1.5, §1.6.1, §1.7-1.9 | §1.6.2 (charger loss) |
| Architecture and interface contract | §1.10, §1.14 | §2.2, §2.3 (charger interface block) |
| Input protection (eFuse, TVS) | §1.11 | - |
| Interlock and permit logic | §1.12 | U311 QUAL one-shot (Table 1.12) |
| Ground scheme | §1.13 | Power-loop return placement (§3.4) |
| Power stage, control pins, EVM modifications | - | §2.1, §2.2, §2.4 |
| Netlist | §2.5.2, §2.5.3, §2.5.6-2.5.9 | §2.5.4, §2.5.5 |
| Power-up states | Logic columns of Table 2.8 | Pin columns of Table 2.8 |
| Layout | §3.1.2, §3.1.6, §3.2.1, §3.3, §3.5, §3.6, §3.9 | §3.4, §3.6.2, §3.7.1 |
| BOM and cost | §4.7 (I set) | §4.7 (S set) |
| Firmware and IO CSV | §5.9.1 | §5.9.2 |
| Tests | §6.6 (I set) | §6.6 (S set) |
| Comparison | §7.4 | §7.4 |

### 0.7 Conventions

1. Coordinates are Eagle board coordinates of the MB: top view, origin at the MB lower-left corner, +x right, +y up, in
   mm ([MECH] header). In KiCad (+y down), enter y as -y.
2. Citation keys in square brackets are defined in section 9. A bare section sign (§) refers to this document.
3. In section 5, bare section letters (A.4, B.6, D.3, G.1) refer to [WD].
4. "Mn" refers to item n of the measurement list in §1.9. Section 8.2 consolidates all operator measurements.
5. `TODO(verify: <source>)` marks a value that a named source must confirm. `TODO(measure)` marks a value that only a
   measurement can give. `TODO(calc)` marks a value that a stated calculation must give. **ESTIMATE** marks a figure derived
   from a stated basis without a recorded source figure.
6. "Interp." marks a reading of a TI layout image, or of a render of the TIDA-050047 Gerbers ([TLP]), that no TI text
   states.

### 0.8 Supporting files

The review folder `docs/reviews/charger_bq25798_custom_board_2026-11-10/` holds the supporting files of this document. Its
`README.md` lists each file. The main files are the following:

| File | Content |
|---|---|
| `bom.csv` | Machine-readable BOM: 111 part lines plus the PCB line (section 4) |
| `make_bom.py`, `bom_cost.json` | BOM generator and its cost roll-up ([BOMGEN]) |
| `schematic_blocks.txt` | Figure 1.10 as a separate text file |
| `mech_parse.py`, `mech_parse_out.txt`, `mech_parse_out.json` | Parser of the MB `.brd` file and its output ([MECH]) |
| `digest_mechanics.md` | Mechanical facts extracted from the parse ([MECH]) |
| [TID] | Transcribed facts of SLUSDV2C and SLUUCB5E ([TID]) |
| `tida_layout_parse.py`, `tida_layout_parse_out.txt` | Parser of the TIDA-050047 PCB file, Gerbers and drill file around U1, and its output ([TLP]) |
| `digest_study_reviews.md` | Rulings, requirements and the round 1-6 finding table ([STUDY]) |
| `layout_calc.py`, `layout_calc_out.txt` | Layout arithmetic: widths, vias, losses, thermal model (with the r2 forced-air section 8), area ([LC]) |
| `tall_stack_calc.py`, `tall_stack_calc_out.txt` | r2 tall header stack checks ([TS]) |
| `sch_calc.py`, `sch_calc_out.txt` | Schematic arithmetic: inductor ripple, peak and current requirement, capacitance, PMID ripple on a VBUS sweep, comparator-input impedances, pin currents ([CALC]) |
| `make_ledger.py`, `ledger_table.md` | Generator of the 203-key finding ledger of §7.A ([LEDG]) |
| `ti_prices.json` | TI store prices of 2026-11-10 ([TI-PD]) |
| `pre_assembly_critique.md` | The critique of the section drafts before assembly, with the applied fixes |

TI reference material for the power stage is held in `references/TI_BQ25798_design_files/` ([TIDA]). It includes the
SLUSDV2C and SLUUCB5E PDFs and the TIDA-050047 Altium project with 4-layer Gerbers. TI publishes no EVM layout files, but
the TIDA-050047 files give a fabricated BQ2579x power stage; §3.4.6-3.4.8 transcribe it and its land pattern ([TLP]).

### 0.9 Revision record

Table 0.9 lists the revisions of this document.

| Revision | Date | Change | Record |
|---|---|---|---|
| r0 | 2026-11-10 | First issue | - |
| r1 | 2026-11-10 | Applies review run 001: 22 findings (8 major, 12 minor, 2 nit; no blocker) and nine further corrections that the adjudication records with them. The main changes are the thermal gate on T_MB,0 with the MB self-heating term and the option-K stack (§3.7), the solder-bridge fault class (§2.3.2), the L501 saturation criterion (§2.1.3), the four-board cost and the re-spin contingency (§4.5, §7.1), five ledger statuses (§7.2), the header-joint and retention tests (§6.4) and the consistency corrections of findings CCB-R1-06, CCB-R1-07, CCB-R1-08 and CCB-R1-22 | Review folder: `run-001-2026-11-10.md` (findings, verification, adjudication), `ledger_table.md`, `layout_calc_out.txt`, `sch_calc_out.txt`, `bom_cost.json` |
| r2 | 2026-11-10 | Applies three operator facts (operator statement, 2026-11-10): the vehicle is a stationary testbench that drives flywheels; a fan may be mounted on the CCB; the CCB has no height restriction. The main changes are the forced-air thermal model and the fan-off guard (§1.6.3, §3.7.2a, §3.7.3a, §3.7.4a), the fan inlet and outlet edges (§1.2.3), the gap rule g 5 mm minimum and 5-8 mm recommended with the tall header and spacer classes (§1.3.2, §1.3.4, §1.4), the tall-pin resistance and loop inductance (§3.3), the fan and tall-stack BOM lines (§4), the new soak test T-K-20 and the measurements M15-M17 (§1.9, §6.4), and the comparison, ledger and open items (§7, §8). The envelope rule, gate D-2, the gap pad, the T_MB,0 heater-step gate, and the vibration and road items are superseded by these facts. They are kept as records, and their test IDs and measurement numbers stay. The tall-stack check found that the r1 statement "the IN-side transient is unchanged" (§1.11.2 item 4) does not hold without the W1/W2 lead (N-25). Revision r2 is not reviewed | Review folder: `layout_calc.py` section 8 and `layout_calc_out.txt` ([LC] §8), `tall_stack_calc.py` and `tall_stack_calc_out.txt` ([TS]), `make_bom.py`, `bom.csv`, `bom_cost.json` |

## 1. IC-independent base

This section holds the content that carries over to any charger IC that fits the CCB outline and meets the interface
contract of §1.14. Subsections 1.1 to 1.9 define the mechanics: the 22-pin field, the extension direction, the header
stack, the support feet, the keep-outs, the thermal zones beside the LM1084, the retention and the measurement list.
Subsection 1.10 gives the board architecture and the interface between the interlock and the charger. Subsections 1.11 to
1.13 give the input eFuse, the interlock and permit logic, and the ground scheme. Subsection 1.14 states the contract that a
replacement charger IC must meet.

Subsection 1.6.2 is the only BQ25798-specific part of this section, and it is labelled. The IC-independent layout rules are
in section 3 (Table 0.6).

### 1.1 Fixed interface: the 22-pin field (IC-independent)

The CHG footprint is a through-hole dual row of 22 square pads. Table 1.1 gives the interface facts the CCB must match.

| Item | Value | Source |
|---|---|---|
| Pin pitch | 2.54 mm | [AG] Fig 11 ("2.54 TYP"); [MECH] pad table |
| Row spacing | 25.0 mm (x 20.998 and x 45.998) | [AG] Fig 11; [MECH] §1 |
| Ag105 pin section | 0.64 mm | [AG] Fig 11 |
| MB drill / pad | 1.10 mm drill, square pads, 1.65 mm (DRU-derived) | [MECH] §1; [AG] Fig 11 recommends 1.1 +/- 0.05 mm |
| Left column (pins 11-22) | x 20.998, y 64.484 (pin 11) to y 36.544 (pin 22) | [MECH] pad table |
| Right column (pins 1-10) | x 45.998, y 39.084 (pin 1) to y 61.944 (pin 10) | [MECH] pad table |
| Ag105 standoff (nominal) | 2.54 mm +/- 0.5 mm; pins 3.00 mm below the standoff | [AG] Fig 11 |
| Ag105 top above the MB (nominal) | 2.54 + 1.60 + 9 = 13.14 mm (keep-out height) | [MECH] §1 |
| MB board | 2-layer, 1.6608 mm, GND poured on both layers, GND pads solid (no thermals) | [STUDY] §4.2 |

The pin field is a standard 2.54 mm grid with 0.64 mm pins, so a standard 0.64 mm square-pin header fits the holes. The
two columns are not equal in length (12 and 10 pins), and the right column is offset by one pitch. The CCB therefore
uses one 1x12 strip and one 1x10 strip, as the CR did ([WD] A.7, finding `chg-header-strips-10-12`).

Note that a y-mirrored capture fits the MB with every pin reversed in its column ([WD] A.8). The CCB keeps the CR rule:
an asymmetric outline feature marks pin 11, and `round3/calc/pin_identity_check.py` checks the pad export.

### 1.2 Direction of the sideways extension (IC-independent)

#### 1.2.1 Constraints on each side

The CCB can extend only where no neighbour forbids it. Table 1.2 ranks the four sides. All distances are from the CHG
silk line centre, x 17.198-49.199, y 32.843-67.644 ([MECH] §1).

| Rank | Side | Usable rectangle (MB mm) | Tallest MB part beneath | Decision and reason |
|---|---|---|---|---|
| **1** | High-y | **x 17.70-38.90, y 67.14-76.40** (rect A) | ROP1-FC 0603, 0.60 mm, only at x >= 38.0; otherwise bare GND pour | **Use.** No power copper, no switch node, three foot spots (1.4). The right edge (x 38.90) is 12.0 mm from the LM1084 courtyard (x 50.947). The y 76.40 limit stays 0.55 mm short of L-FC and 5.2 mm short of the VSW-FC pour ([MECH] §6). |
| 1a | High-y, extended right | x 38.90-48.70, y 67.14-76.40 | OP-FC SOIC-8, 1.75 mm; MDAC-FC height TODO(verify: AD5443 RM-10 outline) | **Reserve.** Only passive, low-noise parts above, and only with an underside height of 2.75 mm or more (1.3). The FC droop amplifier and MDAC lie beneath, so a switch node here is a noise risk. |
| 2 | Low-y | x 17.70-48.70, y 26.00-32.84 | C4A-BT / C4B-BT 1210, 1.35 mm | **Reject for this revision.** It covers BAL (BQ29200) and RB1A, the probe and lift sites of the isolation gates BG-17a/b and B-PKN. VBT traces up to 2.54 mm wide and the VOUT-BT pour lie beneath. No foot spot exists ([MECH] §6). |
| Reject | Right (+x) | none | CO-5V 2.10 mm at 0.0 mm (silks touch); LM1084 4.83 mm at 1.75 mm (courtyard) | The LM1084 runs hot. A board above it traps its heat and shades the tab pour (x 49.78-61.98, 0.585 mm from the silk). The CCB edge stays at x <= 48.70. |
| Reject | Left (-x) | none | J-BL, J-NTC, J-FC terminal blocks, 21.70 mm | The block screws are driven from above over x 3.5-16.1 and the wires enter at x 3.5 ([MECH] §2.2). Any cover blocks service. The CCB edge stays at x >= 17.70. |

#### 1.2.2 Reasoning for the high-y choice

The high-y band is the only side that is part-free, power-copper-free and away from the LM1084. Its only copper is the two
GND pours, one 0.254 mm N$8 trace at x 38.7-42.2 and one GND via at (38.75, 72.65) ([MECH] §4.2). Chafe of the CCB
underside on a GND pour does not create a hazard. In contrast, the low-y band covers VBT and the BT boost output.

The LM1084 constraint is thermal and vertical. The LM1084 is 4.83 mm tall (LM1084 DS, KTT0003B). The CCB top surface sits
at about 2.54 + 1.6 = 4.14 mm above the MB with the default header (1.3), so the CCB edge faces the LM1084 sidewall. The
gap is 2.86 mm from the CCB edge (x 48.70) to the LM1084 body (x 51.562) ([MECH] table 2.1). The CCB therefore never covers
the LM1084, at any header height. With the r2 gap rule (H_u 5.1-8.1 mm, §1.3.2 rule 3), the CCB underside is 0.3-3.3 mm
above the LM1084 top (4.83 mm). The CCB edge then faces the air above the LM1084, not its sidewall. The rule x <= 48.70
keeps the CCB 2.86 mm clear of the air that rises from the LM1084 body. The fan outlet air leaves away from the LM1084
(§1.2.3).

CO-5V (2.10 mm) touches the CHG silk. The CCB edge at x 48.70 is 0.54 mm inboard of the CO-5V silk (x 49.236). The CCB
underside (2.54 mm) is above the CO-5V top (2.10 mm), so a small plan error does not cause a static collision. However,
the vertical air over CO-5V would be only 0.44 mm, below the g_air minimum of 1.0 mm (1.3.2), so an overlap is a chafe
risk under vibration. A CCB with an underside below 3.1 mm (2.10 + 1.0) must therefore keep its right edge at x <= 48.70
with no exception. On the testbench the chafe source is handling, not vibration (operator statement, 2026-11-10). With
the r2 gap rule (H_u >= 5.1 mm), the air over CO-5V is 3.0 mm or more, so the CO-5V condition no longer binds. The
right edge stays at x <= 48.70 because of the LM1084.

J-BL is a screw terminal block, not a plug-and-socket connector ([MECH] §2.2). "Pluggable" here means that the
position-3 screw and the wires stay removable (gate JBL, `docs/battery_isolation_feasibility_2026-11-07.md` line 788).
The CCB left edge at x 17.70 is 1.30 mm from the J-BL courtyard (x 16.405). The screwdriver approaches vertically over
x 3.5-16.1. A tall CCB part near the left edge can obstruct an angled driver, so the screwdriver envelope is a
measurement (M8). The taller r2 stack (H_u 5.1-8.1 mm) raises the CCB left edge by 2.6-5.6 mm over the r1 value, and
the fan and its mount must stay at x >= 17.70 (§1.2.3). M8 and the T-K-04 screwdriver trial therefore stay in force at
the chosen H_u.

The high-y overhang is a cantilever. The last pin row is pin 11 at y 64.484, so the free edge at y 76.40 is 11.9 mm past
the pin field. A foot at y 70.64 (1.4) reduces the free cantilever to 5.8 mm. In r1 the load case was vehicle
acceleration. On the testbench (operator statement, 2026-11-10) the load case is handling: a cable plugged into the CCB,
a probe pressed on it, or a hand on the tab. A 10 N vertical force at the tab edge deflects the plate 0.04-0.07 mm
without the feet and about 0.01 mm with them, nearly independent of H_u ([TS] §(e); §1.4).

#### 1.2.3 Fan inlet and outlet edges (IC-independent, r2)

A fan may blow air through the underside gap and over the CCB top (operator statement, 2026-11-10). The air must enter
at an open side of the gap. Table 1.2a assesses each CCB edge as the fan inlet.

| Edge | Assessment as the inlet |
|---|---|
| **Low-y body edge** (y 34.14, x 17.70-48.70) | **Use.** It is a straight 31.0 mm edge without a foot. The header columns (x 20.998 and x 45.998) run along +y, so they bound the channel and do not block it. The feet (y 70.64) sit at the outlet ([LC] §8.1) |
| High-y tab edge (y 76.40) | **Reserve.** The lumped model has no term that depends on the flow direction, so it gives the same R_total for both directions by construction. [LC] §8.1 computes the low-y inlet only. However, both feet then sit at the inlet, and a fan there stands over L-FC (courtyard y >= 76.948, height unmeasured, M7) |
| Right (+x) | **Reject.** It faces the LM1084 and CO-5V (§1.2.1). The operator statement excludes this side |
| Left (-x) | **Reject.** The J-BL, J-NTC and J-FC blocks (21.70 mm) close this side, and a fan there obstructs the J-BL service (M8) |

The flow is therefore along +y. The channel between the column keep-outs is 22.34 mm wide (x 22.33-44.67), with 891 mm²
of the 1219 mm² CCB underside in the flow and a mean flow length of 39.9 mm ([LC] §8.1). The air leaves at the tab end
(y 76.40) and at the open body edge y 67.14 for x 38.90-44.67, away from the LM1084 ([LC] §8.1).

The flow direction does not change the overhang choice. The high-y choice of §1.2.2 rests on MB copper, probe access and
foot spots, and none of these depends on the flow. The high-y tab also leaves the low-y body edge free of feet, which
suits the inlet. A low-y overhang would still cover the BAL probe sites and would still have no foot spot.

A fan at the low-y inlet stands above part of the low-y band (rect B' of [MECH] §6). It carries no CCB copper there, but
it obstructs the bench access that §1.2.1 protects. The fan rules are the following:

1. Mount the fan at the low-y body edge with its axis along +y.
2. Make the fan face cover the gap and a stream of about 10 mm above the CCB top. [LC] §8.9 uses this geometry.
3. Keep the fan frame and its mount inside x 17.70-48.70.
4. Keep the lowest fan-frame edge 1.0 mm (g_air) or more above every MB part beneath it. The tallest parts there are
   C4A-BT and C4B-BT (1.35 mm) and BAL (1.00 mm) ([MECH] §2.1). The frame edge is therefore 2.35 mm or more above the MB.
5. Do not let the fan, its mount or a duct touch MB copper (§1.5 rule 6).
6. Remove the fan before the battery-isolation gates BG-17a/b and B-PKN. RB1A and BAL OUT lie under the fan position.
7. Connect the fan to the bench supply or to its own regulator. Do not connect it to the LM1084 / CO-5V rail.

Rule 7 follows from the LM1084 budget. The LM1084 carries 0.15-0.25 A of logic load. [LC] §8.10 assumes a fan current
of 0.05-0.20 A, because no fan MPN is chosen (TODO(verify: fan datasheet)). Such a fan adds 0.12-0.68 W
(+20 to +133 %) and about +5 to +27 C of junction rise at RθJA 40.4 C/W ([LC] §8.10). The limit is the LM1084 heating
and fan-motor noise on the Teensy rail, not the 5 A rating. This revision puts no fan supply on the CCB.

The fan must deliver 1.97-3.55 CFM for gaps of 5-8 mm at 2-3 m/s over both sides. At an assumed 30-50 % duct capture, the
fan rating is 3.9-11.8 CFM ([LC] §8.9). Its static pressure must exceed the bare-channel drop of 5.4-12.7 Pa by the
duct and obstacle losses ([LC] §8.2, §8.9).
The fan part number, its airflow and static-pressure curve, its depth and its mass are TODO(verify: fan datasheet). The
capture fraction and the gap velocity are TODO(measure: M15).

The fan need not be proven on. With the fan off, the FR-50 TDIE trip stops the charger; the derate alone does not hold
100 C. The CCB node time constant is 164-303 s, so the guard has minutes to act ([LC] §8.7; §3.7).

### 1.3 Header stack-up and underside height (IC-independent)

#### 1.3.1 Design variables

This subsection uses the following terms:

- **H_u**: the CCB underside height above the MB top surface.
- **h_s**: the fitted Ag105 standoff height (gate D-2), unmeasured ([STUDY] §4.1).
- **h_mb**: the tallest MB part under the CCB outline.
- **g_air**: the air gap between the tallest MB part and the lowest CCB feature (bottom part or pin tail).
- **H_env**: the free height above the MB at the CCB outline, limited by the chassis or by any part above the board.
  Record only in r2: the CCB has no height restriction (operator statement, 2026-11-10).
- **g**: the air gap of the fan channel, from the polyimide sheet (0.125 mm, §1.5 rule 3) to the CCB underside;
  g = H_u - 0.125 mm ([LC] §8.1).

#### 1.3.2 Design rule

H_u must meet rules 1 and 3 below. Rule 1 protects the MB parts. Rule 3 lets the fan air pass under the power cell.
Rule 2 is the r1 envelope rule and is record only in r2.

1. H_u >= h_mb + t_bot + g_air, where t_bot is the tallest CCB bottom feature above that MB part.
2. H_u + t_pcb + h_top <= H_env, where t_pcb is the CCB thickness and h_top its tallest top-side part. **Superseded by
   the testbench facts** (no height restriction, operator statement, 2026-11-10). Record H_env (M6), but do not use it to
   reject a stack.
3. g >= 5 mm (H_u >= 5.125 mm), and g of 5-8 mm (H_u 5.1-8.1 mm) is the recommended band ([LC] §8.9). This rule is new
   in r2.

The values for the default rect-A outline are:

- Under the footprint, h_mb = 1.10 mm (D-BT-SQ, C-D11, C-D12, C-DC11, C-DC12; [STUDY] §4.2). The CR kept bottom parts
  out of the keep-out x 24.5-36.0, y 48.5-53.5, so t_bot = 0 there and g_air = 2.54 - 1.10 = 1.44 mm ([WD] A.7).
- Under rect A, h_mb = 0.60 mm (ROP1-FC, x >= 38.0 only); elsewhere h_mb = 0 (GND pour).
- Under rect A', h_mb = 1.75 mm (OP-FC).
- The CR rule sets g_air >= 1.4 mm under the 1.10 mm parts and t_bot <= 1.0 mm for bottom passives outside the keep-out
  ([WD] A.7). This section keeps g_air >= 1.0 mm as the minimum and 1.4 mm as the target.

With the default 2.54 mm plastic header body, H_u = 2.54 mm. This value meets rule 1 under the footprint (1.44 mm air) and
under rect A (1.94 mm air or more). Over OP-FC (rect A'), the air is only 0.79 mm, below the 1.0 mm minimum. Rect A' therefore
needs H_u >= 1.75 + 1.0 = 2.75 mm.

Rule 3 sets a taller stack than r1. At H_u 5.125 mm, the air is 4.0 mm over the 1.10 mm parts under the footprint and
3.4 mm over OP-FC, so rule 1 holds everywhere and rect A' is open. The basis of rule 3 is the following ([LC] §8.1, §8.7,
§8.9):

- The 5 mm minimum clears the obstacles in the channel. With a 1.0 mm CCB underside part over a 1.10 mm MB part, the
  worst cross-section is 42 % blocked at g 5 mm and 70 % at g 3 mm.
- A taller gap does not lower the junction temperature with the fan on. At 2 m/s in the gap only, R_total rises from
  13.6-22.8 C/W at g 5 mm to 16.7-25.3 C/W at g 12 mm. The developing-flow h falls as the channel grows, and the pin
  and gap-conduction paths to the MB weaken. At a fixed flow of 1.0 CFM, T_J - T_air rises from 54-76 C (g 5 mm) to
  69-92 C (g 12 mm) at 2.7 W.
- A taller gap raises the junction temperature with the fan off. At 2.7 W, T_J - T_air is 79-117 C at g 5 mm and
  99-131 C at g 12 mm.

Above g 8 mm, therefore, the fan-on result gains nothing, and the fan-off result becomes worse. With both sides at
2 m/s, T_J - T_air is 49-61 C at g 5 mm, 51-62 C at g 8 mm and 52-63 C at g 10 mm. §3.7 gives the thermal model.

A preliminary estimate of 2026-11-10 proposed a gap of 8-12 mm and 8-14 C/W for air ducted through the gap only. The
calculation supports neither value. The gap path alone is 34.3-52.3 C/W at g 5 mm and 2 m/s ([LC] §8.5b). A taller gap
is worse with the fan on and with the fan off ([LC] §8.5, §8.7, §8.9).

Table 1.3a gives the header classes for each H_u ([TS] §(e)). For option S, the minimum pin length is the sum of a
1.0 mm tail under the MB, the 1.66 mm MB, H_u, the 1.6 mm CCB and 1.5 mm above the CCB. For option K, the socket seat
height is h_k = H_u - 2.54 mm, with a 2.54 mm male body.

| H_u | Option S, minimum pin length | Option K, h_k | Candidate classes (all heights and MPNs TODO(verify: maker drawing)) |
|---|---|---|---|
| 5 mm ([TS] row; the rule-3 minimum H_u 5.125 mm needs 10.9 mm and gives h_k 2.59 mm) | 10.8 mm | 2.46 mm, below common socket seat heights | S1, S2, S3 |
| 8 mm ([TS] row; the band top H_u 8.125 mm needs 13.9 mm and gives h_k 5.59 mm) | 13.8 mm | 5.46 mm | S1, S2, S3, K2, K3 |
| 10 mm (record) | 15.8 mm | 7.46 mm | S1, S2, S3, K2, K3 |
| 12 mm (record) | 17.8 mm | 9.46 mm | S1, S2, S3, K1 (H_u about 11.05 mm), K2, K3 |

The candidate classes are the following:

- S1, a Samtec TSW-110/-112 header with a long-post lead style;
- S2, a Samtec MTSW-110/-112 header with a movable body set at the gap;
- S3, a standard header with a spacer strip;
- K1, a Samtec SSW/SSQ socket strip with a TSW male header;
- K2, a Samtec ESQ elevated socket strip (long tail, stacking);
- K3, a Harwin M20 female header with a long-pin male header.

K1 with its 8.51 mm body (TODO(verify: Samtec SSW drawing)) gives H_u of about 11.05 mm, above the recommended band.
The two strips run along y, so they form the side walls of the channel under the power cell.

The taller pins add resistance and inductance. Over the r1 H_u of 2.54 mm, H_u 5-12 mm adds 0.66-2.54 mΩ per pin and at
most 43 mW over the six power pins ([TS] §(a); §3.3). The pin pair 10 and 4 gains up to 5.2 nH at H_u 5 mm and 10.8 nH at
H_u 8 mm ([TS] §(b)); §1.11.2 gives the effect on the eFuse hard-short transient. The I2C lines gain at most 0.82 pF
([TS] §(d)).

The two paragraphs below are the r1 record of rule 2. They are kept for traceability and do not constrain the r2 stack.

For rule 2, the Ag105 itself proves a free volume over the footprint up to h_s + 1.60 + 9 mm ([AG] Fig 11 keep-out). With
the nominal h_s = 2.54 mm, that is 13.14 mm. A CCB on the default header with a 3.0 mm inductor (TDK SPM6530T, [TID] line
139) reaches 2.54 + t_pcb + 3.0 mm. With t_pcb = 1.6 mm (TODO(verify: CCB fab stack-up)), that is 7.14 mm, which is 6.0 mm
below the nominal Ag105 top. Over rect A, the Ag105 envelope does not apply, so H_env must be measured there (M6).

These values are for option S of §1.3.4. For option K, H_u = h_k + 2.54 mm (male body), where h_k is the socket seat
height. The CCB top then reaches 7.14 + h_k mm, which is 6.0 - h_k mm below the nominal Ag105 top. With the proposed 1 mm
margin, the socket seat height must be h_k <= 13.14 - 1 - 7.14 = 5.0 mm ([LC] §5.3). An SSW-class socket body of 8.51 mm
(TODO(verify: Samtec SSW drawing)) gives a 15.65 mm top, 2.51 mm above the envelope.

Record (r2): with the 3.0 mm inductor and t_pcb 1.6 mm, the r2 band H_u 5.1-8.1 mm puts the CCB top at 9.7-12.7 mm.
This value stays below the nominal Ag105 top of 13.14 mm for H_u of 8.54 mm or less. A heatsink on U501 (§3.7) raises
h_top, which rule 2 no longer limits.

#### 1.3.3 Dependence on gate D-2

The CCB does not need to match the Ag105 height. The CCB clears the MB parts through rule 1, which does not contain h_s.
In r2, gate D-2 no longer constrains the CCB height, because the CCB has no height restriction (operator statement,
2026-11-10). Items 1 and 2 below are therefore record only. In r1, the value h_s entered the design in two places:

1. **As the proven envelope over the footprint.** The free height over the footprint is at least h_s + 10.6 mm. The CCB
   top must stay below it unless H_env is measured directly (M6). Option S (7.14 mm) meets this rule for any
   h_s >= 0 mm, so option S does not wait for D-2. Option K (7.14 + h_k mm) meets it when h_k <= h_s + 3.46 mm.
2. **As a reversibility check.** If the MB receives a socket strip (1.3.4, option K), an Ag105 can plug back into that
   socket. Its top then rises by the socket seat height h_k: h_top,Ag105 = h_k + 1.60 + 9 mm, measured from the MB.
   This value must stay below H_env.

The D-2 pass rule (solderable stub of 1 mm or more after a pin cut, [STUDY] §4.1) applies only to the
battery-isolation route that keeps the Ag105 with cut pins. The CCB route removes the module, so D-2 is not a CCB gate.
However, the module removal method sets the hole condition, which is a CCB gate (M2).

#### 1.3.4 Soldered versus socketed

Table 1.3 compares the two attachment options. Heights marked TODO come from the chosen part's drawing.

| Option | Stack (MB up) | H_u | Removal | Vibration behaviour (r2: handling and insertion) | MB rework |
|---|---|---|---|---|---|
| **S: soldered** | Male 0.64 mm square-pin strips (TSW-110 + TSW-112 class) soldered in the MB holes and in the CCB; r2: long-post or movable-body pins of 10.8-13.8 mm (classes S1-S3, Table 1.3a) | r1: 2.54 mm (body). r2: 5.1-8.1 mm from §1.3.2 rule 3, +/- seat variation TODO(measure: M3) | Desolder 22 pins. The MB GND pads are solid to both pours on a 1.66 mm board, so desoldering is a lifted-pad and barrel risk ([STUDY] §4.2) | 22 solder joints carry the load; no contact fretting | None beyond the module removal |
| **K: socketed** | Female socket strips soldered once in the MB holes; male strips on the CCB plug into them | h_k + male body height (h_k + 2.54 mm). r1: h_k <= 5.0 mm, superseded (no height restriction). r2: h_k 2.6-5.6 mm for §1.3.2 rule 3 (classes K2, K3, Table 1.3a), TODO(verify: socket and header drawings) | Pull the CCB; no heat on the MB | Contacts can fret or back out under repeated insertion; positive retention by the foot screw (1.4) is required | Socket strips soldered into the MB once |

This section recommends **option K with a screwed foot** for the first CCB revision. The first revision of a new power
board probably needs rework, and repeated desoldering on the solid-GND MB pads risks the MB. The socket also lets the Ag105
plug back in as a fallback (1.3.3 item 2). Option S is the choice for a frozen revision, because it has no contact interface.

In r2 the recommendation stands. On the testbench, repeated insertion is the main mechanical load case, which favours the
socket. Within rule 3, option K needs h_k of 2.6-5.6 mm. A seat height near 5.5 mm (H_u about 8 mm, class K2 or K3) is
the practical point, because h_k 2.59 mm at the rule-3 minimum (H_u 5.125 mm) is below common socket seat heights
([TS] §(e)). The fan-off cost of
H_u 8 mm over 5 mm is about +10 C at 2.7 W (T_J - T_air 89-124 C against 79-117 C, [LC] §8.7). With the fan on, the cost
is about +2 C (§1.3.2).

The socket choice must meet three conditions:

1. The socket tail fits the 1.10 mm MB drill. TODO(verify: socket drawing, tail section).
2. The socket accepts both the CCB header pin and the Ag105 0.64 mm pin, if Ag105 reversibility is wanted.
   TODO(verify: socket drawing, accepted pin range).
3. The socket body width fits beside the parts under the footprint. The nearest inboard part to the left column is C-D11 at
   x 26.2, 5.2 mm from the column ([STUDY] §4.2), so a single-row socket fits. TODO(measure: M3, dry fit).

The CCB height with option K is unknown until the socket is chosen. A taller H_u improves rule 1 and opens rect A' (H_u
>= 2.75 mm). In r1, a taller stack lengthened the lever arm of the pins under lateral acceleration, and h_k had to be
5.0 mm or less. Both points are superseded by the testbench facts (operator statement, 2026-11-10). For handling loads,
a 10 N lateral force sways the CCB 0.0041 mm at H_u 8 mm and 0.0137 mm at H_u 12 mm, with a pin bending stress of 13 and
20 MPa ([TS] §(e)). The pin yield stress of about 500 MPa is TODO(verify: Samtec pin alloy). The cost of a tall stack is
the foot-bond moment (§1.4), not the pin sway.

r1 record (still air; in r2 it applies only with the fan off): option K also costs thermal margin. The longer pin
path, the thicker air layer and the socket contacts raise R_board.
Option S has 14.3-18.3 C/W. Option K at h_k = 3.0 mm has 21.6-27.3 C/W before the contact term and 30.0-38.5 C/W with it
([LC] §5.5; §3.7.2). In r1, option K therefore needed the compressed gap pad of §3.7.4 to meet the junction target of
the r1 verdict condition 3. Option S on the vehicle MB, with option K on FIX1 only, kept more margin. Without the pad,
option S admits T_MB,0 of 14-29 C, against -41 to 11 C for option K at h_k = 3.0 mm (§3.7.3). However, option S brings back the desoldering risk on the
solid-GND MB pads.

In r2, with the fan on, both options
meet the junction target without the gap pad, and T_MB,0 has a small effect: dT_J/dT_MB0 is 0.15-0.30 at g 5 mm and
2 m/s over both sides ([LC] §8.6, §8.6b; §3.7). The gap pad is then not needed, and the r1 thermal argument for option S
over option K is superseded by the testbench facts (operator statement, 2026-11-10).

#### 1.3.5 Pin tails and the CCB underside

The CR rules transfer unchanged ([WD] A.7):

- Flush-cut every through-hole tail on the CCB underside to 0.5 mm or less.
- Use top-side SMT pads for every MB tap; put no tap tail on the underside.
- Fit only passives of 1.0 mm or less on the underside, outside the bottom keep-out x 24.5-36.0, y 48.5-53.5.
- Keep underside parts outside the projected outlines of MB VBT, the VBT pour, the VCHG pour and VCHG-IN, each grown by 1 mm.

In r2, every underside part inside x 22.33-44.67 stands in the fan channel ([LC] §8.1). The worst-section blockage of
§1.3.2 (42 % at g 5 mm) already assumes a 1.0 mm underside part over the 1.10 mm MB parts. The model does not credit the
mixing or the pressure drop of these obstacles. TODO(measure: M15).

### 1.4 Support at the overhang end (IC-independent)

No existing MB hole can take a standoff. The MB has only two NPTH holes, at (3.302, 3.302) and (3.302, 94.742), at least
30 mm from the footprint ([MECH] §5). Table 1.4 lists the support options.

| Option | Description | MB rework | Assessment |
|---|---|---|---|
| E: existing hole | Standoff into an existing MB hole | none | **Not possible**: no hole within reach |
| B: bonded foot | Nylon M3 hex spacer of length H_u, epoxy-bonded to the MB solder mask; nylon M3 screw from the CCB top into the spacer. r2: a tall spacer of 5.1-8.1 mm, equal to H_u (§1.3.2 rule 3) | **None** (adhesive only) | **Recommended.** It carries the cantilever and gives positive z retention for option K |
| D: drilled foot | Nylon M3 spacer and screw through a new MB hole | **Yes**: the hole cuts both GND pours (no trace); operator approval required | Strongest; use only if the bonded foot fails the retention check |
| P: pad only | Adhesive or silicone pad between the CCB and the MB, no fastener | none | Damps the cantilever, but gives no positive retention |

The foot spots are (23.20, 70.64), (27.70, 70.64) and (32.20, 70.64). Each spot is clear of all signal copper on both
layers, all vias, all pads and all top-side parts, within the 6 mm circle of [MECH] §5. Only the GND pours lie
beneath. Use two feet, at (23.20, 70.64) and (32.20, 70.64), to resist rotation about the pin rows.

The foot rules are:

1. Bond the foot to bare solder mask, not to the polyimide sheet. The CR sheet uses a silicone pressure-sensitive adhesive
   ([WD] A.7), which is a weak bond base. Cut the sheet clear of the foot spots.
2. Make the foot length equal to H_u of the chosen stack, measured on the dry fit (M3). A foot that is too long lifts the
   header out of the socket. In r2 the foot is a tall spacer of 5.1-8.1 mm. Standard nylon M3 hex spacer lengths cover this
   band. TODO(verify: spacer MPN and length tolerance).
3. Put a plated or bare M3 clearance hole in the CCB at each foot spot, with no copper within 3.0 mm except the GND net.
   TODO(verify: nylon screw head diameter, from the chosen part).
4. Choose the adhesive from a product with a datasheet shear strength. TODO(verify: adhesive datasheet). The CR BOM line
   "Adhesive" is RTV ([WD] A.3 W1), which is a strain-relief product, not a structural bond. The adhesion of the MB solder
   mask to its copper is a second, possibly weaker, link. TODO(verify: MB fabricator, solder-mask adhesion); T-K-18 tests
   the whole bond in torsion and in pull.
5. Run the T-K-18 torsion and pull test with a spacer of the chosen H_u. A lateral force F at the CCB loads each bond
   with the moment F x H_u. At 2.5 N per foot, the moment is 12.5 N mm at H_u 5 mm and 20.0 N mm at H_u 8 mm. At the
   r1 H_u of 2.54 mm it is 6.3 N mm ([TS] §(e)). The moment grows by the factor H_u / 2.54. This factor is 2.0-3.2 in
   the rule-3 band (H_u 5.125-8.125 mm) and 4.7 at H_u 12 mm.

The feet also carry the vertical handling loads at the tab. A 10 N force at the tab edge (y 76.40) puts 18.6-22.1 N
on the two feet (both clamp lines of [TS] §(e)), about twice the tip force, at any H_u from 5 to 12 mm ([TS] §(e)). An upward pull on the tab puts the
same force in tension on the foot screws and bonds. The plate deflection at that load is 0.010-0.014 mm with the feet and
0.039-0.070 mm without them. These figures exclude the socket-contact, bond and MB compliance and the rotation of the CCB
about the pin field. TODO(measure: T-K-18, dry fit). The laminate modulus (20 GPa) is TODO(verify: laminate datasheet).

The two foot spacers stand in the fan outlet at the tab end (§1.2.3). [LC] §8.1 lists them as obstacles and does not
credit their pressure drop.

### 1.5 Keep-outs over MB power copper and abrasion (IC-independent)

The voltages involved are small, but abrasion is the dominant risk. In r1 the source of abrasion was a moving vehicle. On
the testbench (operator statement, 2026-11-10) the sources are handling, probing and repeated insertion. V-MOT reaches 21.2-21.5 V and the
clamp 21.98-22.28 V ([WD] C, EM14). The IPC-2221B clearance at this voltage is small. TODO(verify: IPC-2221B Table 6-1).
The design therefore relies on insulation layers and on air gaps, not on spacing.

The MB copper under the CCB is the CR list ([WD] A.7): VBT (x 34.04-35.56, y 31.75-48.65, and a 1.016 mm run at y 34.54),
VCHG-IN (diagonal (39.62, 34.80)-(43.18, 38.35), then x 42.42-43.94 to y 61.2 and pad 10), the VCHG pour (x 20.14-28.65,
y 43.31-49.96), the VBT pour (x 30.81-34.98, y 48.34-49.76), logic traces and 14 GND vias inside the CR outline. Rect A adds
only GND copper.

The rules are:

1. Tent every CCB via on the underside. Put no exposed copper on the underside except the header pads and foot pads.
2. Put no underside part over the projected MB power copper grown by 1 mm (1.3.5).
3. Bond a 0.125 mm polyimide sheet with a pressure-sensitive adhesive over the MB area under the CCB, outline + 1 mm, with
   2.2 mm relief holes at the 22 pads and cut-outs over the five parts under the footprint ([WD] A.7, PM4). Extend the
   sheet over rect A, with holes at the two foot spots.
4. Keep the CCB underside at least g_air = 1.0 mm above every MB part (1.3.2), so vibration does not bring the two
   surfaces into contact. On the testbench the load is handling, not vibration; the r2 gap of 5 mm or more (1.3.2 rule 3)
   gives 4.0 mm or more over the 1.10 mm parts.
5. Inspect the sheet for chafe after the first drive, as in the CR inspection T-F-12 ([WD] A.7) and [DD] C-4. On the
   testbench, inspect it after the first bench run and after each reinsertion of the CCB.
6. Do not let the fan, its mount or a duct rest on MB copper (r2). The low-y band under the fan position holds VBT traces,
   the VOUT-BT pour and, below y 23.6, the VSW-BT switch-node pour ([MECH] §4.2, §6). When a duct wall must touch the MB,
   put it on the polyimide sheet or on solder mask over a GND pour.

Note that the MB logic traces MPPT-DISABLE (y 64.48, full width) and CB-DISABLE (x 33.27, x 41.40) run under the CCB. A CCB
switch node above them couples into them unless a solid CCB ground layer lies between. The CCB layer next to the underside
must be a solid GND plane under any switch node. Section 3.1.1 assigns the layers.

### 1.6 Thermal interaction with the LM1084

#### 1.6.1 Placement zones (IC-independent)

The LM1084 runs hot, and its dissipation and case temperature are unmeasured (M11). Its tab pad (x 51.22-62.06, y
46.64-54.26) lies beside the right pin column, pins 4-8 ([MECH] table 2.1). The 5V tab pour reaches x 49.78, 1.08 mm outside
the CCB edge. The zone rules are:

1. Put the charger power stage (IC, inductor, input and output capacitors) in the zone x 17.70-38.90, y 50-76.40. The zone
   edge (x 38.90) is 12.0 mm from the LM1084 courtyard (x 50.947), and it lies over GND pour and logic traces only.
2. Keep the battery-side copper short: pins 18/19 (VBAT+) are at x 21.0, y 44.16-46.70, at the lower edge of the zone.
3. Put low-dissipation logic (comparators, permit logic, gate drivers) in the strip x 38.9-48.70 beside the LM1084.
4. Put no temperature-sensitive reference, NTC-related part or electrolytic capacitor within 5 mm of the CCB right edge.
   TODO(measure: M11, the air temperature at x 48.7 sets this distance).
5. Put the eFuse near pad 10 (x 46.0, y 61.9), which is beyond the LM1084 courtyard (y <= 54.54).

Each distance to the LM1084 in this document names its two reference points ([MECH] table 2.1). The heat-source
distance is from the power cell edge (x 37.5, Table 3.4) to the LM1084 courtyard (x 50.947): 50.947 - 37.5 = 13.4 mm.
The other distances are the following:

- zone edge (x 38.90) to the LM1084 courtyard: 12.0 mm (rule 1);
- U501 centre to the LM1084 body: about 25.7 mm (§3.7.5);
- CCB right edge (x 48.70) to the LM1084 courtyard: 2.25 mm, and to the LM1084 body (x 51.562): 2.86 mm (§1.2.2);
- CHG silk outline to the LM1084 courtyard: 1.75 mm (§0.1 item 5).

The zone edge y 76.40 is 0.55 mm short of the L-FC courtyard (FC boost inductor, y >= 76.948). Keep the CCB inductor at
least one inductor length (7.1 mm) from the y 76.40 edge, and use a shielded part. In the floor plan of §3.2, L501 is at
y 51.5-58.0, that is 76.40 - 58.0 = 18.4 mm from that edge. TODO(verify: magnetic shielding of the chosen inductor).

#### 1.6.2 Charger dissipation (BQ25798-specific)

The BQ25798 has no exposed thermal pad. Heat leaves through the PMID, SW1, GND, SW2 and SYS power pads into copper (DS
pp.146-149; [TID] §1.2). The "thermal pad side" of the IC is therefore its power-pad edge. Orient that edge and its
copper spread away from +x, toward the -x/+y corner of the zone.

Table 1.6 gives the whole-charger loss from the DS efficiency curves. The efficiencies are the readings scripted in
[LC] §4, which §3.7.1 also uses. They are readings of the EVM curves (DS Fig 6-3 and 6-4, p.18; VBAT = 8 V, PFM disabled) and
carry about +/-1 percentage point of reading error.

| Case | f_sw | Efficiency (read) | P_out = 8.0 V x ICHG | P_loss = P_out (1/eta - 1) |
|---|---|---|---|---|
| VBUS 20 V, ICHG 3.10 A (regen) | 1.5 MHz | 90.7 % | 24.8 W | 2.54 W |
| VBUS 20 V, ICHG 3.10 A | 750 kHz | 92.4 % | 24.8 W | 2.04 W |
| VBUS 20 V, ICHG 2.50 A | 1.5 MHz | 91.2 % | 20.0 W | 1.93 W |
| VBUS 15 V, ICHG 2.50 A | 1.5 MHz | 93.2 % | 20.0 W | 1.46 W |

The curves stop at VBUS 20 V, while V-MOT reaches 21.5 V. The loss at 21.5 V is therefore TODO(measure: rev-A bench
efficiency). The split of the loss between the IC and the inductor is not published. If the whole 2.54 W were in the IC,
the JEDEC RθJA of 44.2 C/W (DS §6.4) would give a 112 C rise. That bound shows that copper spreading, not still air, must
remove the IC heat. The IC regulates its own die at TREG (default 120 C, DS REG16) by reducing the charge current, so an
overheated CCB loses charge current rather than failing. However, a 2-3 W source 13.4 mm from the LM1084 courtyard
(power cell edge) also raises the LM1084 ambient. TODO(measure: M11 and M12).

A 2.54 W loss (about 2.7 W with the eFuse and logic, §3.7.1) is about the same magnitude as the loss of the round-3 EVM.
The EVM sat 20 mm or more from the LM1084 on standoffs ([STUDY] line 269). The CCB moves this heat to 13.4 mm from the
LM1084 courtyard (power cell edge). In r1, it also put the heat over a closed air layer of H_u - 0.125 mm (2.415 mm for
option S). This is the one mechanical risk the CCB adds over Path A.

r1 record (still air): most of this heat enters the MB under the cell. For option S, the model of §3.7.2 sends 72-87 % of
the 2.7 W (1.9-2.35 W) into the MB. The heat passes through the pins, the air layer or the gap pad. This heat raises the
MB under the cell by 11-21 C ([LC] §5.5). The r1 thermal gate therefore used the MB temperature without the CCB, T_MB,0,
plus this computed self-heating (§3.7.3).

r2 (testbench): a fan may blow air through the gap and over the CCB top (operator statement, 2026-11-10). The fan-on
case is the design case, and the fan-off case is a fault case that FR-50 guards (§1.6.3). With air ducted through the
gap at 2-4 m/s and a still top, the MB far-field share falls to 23-48 % at g 5 mm ([LC] §8.5). With the fan on over both
sides, T_J moves by only 0.15-0.30 C per C of MB idle offset ([LC] §8.6b). T_MB,0 is therefore a record-only input in r2,
and the decisive thermal measurement is the fan-on and fan-off soak (M16; §3.7.3a).

#### 1.6.3 Bench fan: design case and fault case (IC-independent, r2)

The vehicle does not move: it sits on a testbench and drives flywheels. A fan may be mounted on the CCB, and the CCB has
no height restriction (operator statement, 2026-11-10). §1.2.3 sets the fan position, the flow direction (+y, inlet at
the low-y body edge) and the supply rule. This subsection sets the thermal role of the fan and the fan parts.

The thermal cases are the following ([LC] §8.6, §8.7; §3.7.2a):

1. **Design case, fan on.** Air at 2 m/s or more flows through the gap and over the CCB top. At g 5 mm and 2.7 W, the
   junction is 49-61 C above room air, and 74-86 C on a 25 C bench. At 2.9 W it is 78-90 C on a 25 C bench.
2. **Fault case, fan off.** At g 5 mm and 2.7 W, the junction is 79-117 C above room air. The FR-50 TDIE trip must act,
   because the derate alone does not hold 100 C (§5.6; [LC] §8.7). The CCB node time constant is 164-303 s, so the guard has minutes to act ([LC] §8.7).
3. **Partial cases.** Air through the gap only gives 59-84 C above room air at g 5 mm and 2 m/s; air over the top only
   gives 58-71 C. Both are worse than the design case, so the duct must cover both the gap and the top (§1.2.3 rule 2).

The fan parts are the following:

1. **Fan class.** An axial DC fan with a 25-30 mm frame at the low-y edge. Its rating must be 3.9-11.8 CFM free air. Its static
   pressure must exceed the bare-channel 5.4-12.7 Pa by the duct and obstacle losses ([LC] §8.9; Table 1.6a). The fan MPN, its airflow and static-pressure curve, its
   current and its depth are TODO(verify: fan datasheet). The frame size is a class only: a 31.0 mm body edge with a
   10 mm top stream sets the face area ([LC] §8.9).
2. **Supply.** The bench supply, or a regulator of its own if the fan voltage differs (DNP option in the BOM). Never the
   LM1084 / CO-5V rail (§1.2.3 rule 7; [LC] §8.10).
3. **Connector.** A 2-wire fan lead with an inline 2-pin connector to the bench supply. The fan has no connector on the
   CCB or on the MB, and it uses no CCB or MB copper. TODO(verify: connector MPN).
4. **Tachometer.** None. The fan is not on a Teensy pin. The only spare pins are 2 and 8, both on encoder nets, so no
   pin is proposed for a tachometer or a fan enable (§5.4.1). FR-50 makes fan supervision unnecessary (thermal case 2).
5. **Mount and duct.** A bracket or printed frame at the low-y edge per §1.2.3 rules 1-5. Side baffles that close the
   gap at the low-y corners are optional. TODO(verify: duct design after M15).

Table 1.6a gives the airflow requirement for the recommended gap band ([LC] §8.9). The duct covers the full 31.0 mm body
width and a 10 mm stream above the top. The capture fraction is an assumption, TODO(measure: M15).

| g | v (gap and top) | Gap flow | Top stream | Delivered | Fan rating at 30-50 % capture | Channel Δp |
|---|---|---|---|---|---|---|
| 5 mm | 2 m/s | 0.66 CFM | 1.31 CFM | 1.97 CFM | 3.9-6.6 CFM | >= 5.9 Pa |
| 5 mm | 3 m/s | 0.99 CFM | 1.97 CFM | 2.96 CFM | 5.9-9.9 CFM | >= 12.7 Pa |
| 8 mm | 2 m/s | 1.05 CFM | 1.31 CFM | 2.36 CFM | 4.7-7.9 CFM | >= 5.4 Pa |
| 8 mm | 3 m/s | 1.58 CFM | 1.97 CFM | 3.55 CFM | 7.1-11.8 CFM | >= 12.0 Pa |

The channel Δp excludes the duct and obstacle losses. An optional top-side heatsink on U501 lowers the fan-off case
by 14-26 C at R_sa 120 C/W (§3.7.4a).

### 1.7 Retention, coating and mass on the testbench (IC-independent)

The r1 title of this subsection was "Retention, coating and mass on a moving vehicle". The vehicle does not move: it sits
on a testbench and drives flywheels (operator statement, 2026-11-10). The r1 vibration case is therefore not applicable
(testbench). Retention covers handling, probing, cable insertion and repeated insertion of the CCB. The r1 basis is kept
below for traceability: no source gives a vibration or shock specification for the vehicle ([STUDY] §4.2), so the design
relies on positive retention and inspection, not on a rated vibration level.

#### 1.7.1 Mass estimate

Table 1.7 gives an upper-bound mass. Material densities are general values, not part data.

| Item | Basis | Mass |
|---|---|---|
| Laminate | Outline area ~1219 mm² (1.8) x 1.6 mm; FR-4 density ~1.85 g/cm³ TODO(verify: fab datasheet) | ~3.6 g |
| Copper | 4 layers, 1 oz outer + 2 oz inner (stack ST2 of §3.1.3; the ST1 baseline 1 oz / 1 oz gives about 1.5 g), full coverage as an upper bound, 8.96 g/cm³ | <= 2.3 g |
| Inductor (BQ25798-specific) | SPM6530T, 6.5 x 7.1 x 3.0 mm = 138 mm³, bounded by the density of iron (7.87 g/cm³) | <= 1.1 g; TODO(verify: TDK datasheet mass) |
| Header pins | 22 pins, 0.64 mm square, brass ~8.5 g/cm³. r1: ~12 mm long. r2: 10.8-17.8 mm for H_u 5-12 mm (Table 1.3a) TODO(verify: header drawing) | r1: ~0.9 g. r2: 0.83-1.36 g |
| Other parts | ~25 power-stage placements ([TID] EVM refdes table) plus the CR and EIB parts | TODO(verify: BOM masses); estimate a few grams |
| **Total** | Fan, fan mount and any U501 heatsink excluded (TODO(verify: fan and heatsink datasheets)) | **~8-13 g** (estimate; r1 ~8-12 g) |

Not applicable (testbench): at 10 g of acceleration, a 12 g board applies F = m a = 0.012 kg x 98.1 m/s² = 1.2 N. Two
feet and 22 contacts share this load. This r1 load case is superseded by the testbench facts (operator statement,
2026-11-10).

The r2 load case is handling. [TS] §(e) uses a force of 5-10 N at the tab edge, which is about 40-85 times the weight of
a 12 g board (0.12 N). With the feet screwed, the feet carry 18.6-22.1 N at 10 N (§1.4). With option K and no foot
screws, a 10 N downward force at the tab edge gives a moment of 119 N mm about pin 11 and a largest contact tension of
0.58 N ([TS] §(e)). The per-contact socket withdrawal force is TODO(verify: socket datasheet), so the margin without the
screws is not yet known. The screwed feet remove this load path.

#### 1.7.2 Retention rules

1. Screw the CCB to the two bonded feet. The screws, not the socket friction, hold the CCB in z.
2. Apply no thread-locking compound to a foot screw. A thread-locked screw needs a breakaway torque above its tightening
   torque, and the spacer bond reacts the excess in torsion. A blind female spacer cannot take a lock nut. Tighten each
   foot screw to the torque T_s with a torque driver, and hold the spacer hex while you tighten or loosen the screw.
   T_s = TODO(verify: nylon M3 screw datasheet); T-K-18 sets T_s at or below half the measured bond breakaway torque.
3. Stake the inductor and any part heavier than 1 g with a bead of adhesive to the CCB. TODO(verify: adhesive datasheet).
4. Strain-relieve every flying tap lead at the CCB within 30 mm, as the CR rule requires ([WD] r5-10, r5-23).
5. After the first drive, inspect every header joint, foot bond, staked part and tap lead, as in [DD] C-4. On the
   testbench, do this inspection after the first bench run and after each reinsertion of the CCB.
6. Support the tab with one hand when you plug a cable into the CCB or press a probe on it (r2).
7. Remove the two foot screws before you pull the CCB from its socket (r2). Pull the CCB straight up.
8. Attach the fan to its mount with screws. Do not let the fan hang on its cable or on the CCB parts (r2).

Rule 1 stays in force on the testbench, because handling and repeated insertion still need the screwed feet ([TS] §(e)).
The r1 road and vibration items (T-K-19, M14) are not applicable (testbench); T-K-18 applies to handling loads only.

#### 1.7.3 Conformal coating zones

1. Coat the CCB top and underside, except the zones in items 2-4.
2. Do not coat the header pins, the socket contacts, the foot screw holes or the fan-mount holes (r2).
3. Do not coat the test points and the SMT tap pads until the bench gates pass.
4. Do not coat the MB inside the socket strip footprint.
5. Choose a coating that tolerates the IC copper temperature. TODO(verify: coating datasheet, maximum temperature).

### 1.8 Board outline proposal (IC-independent)

The proposed outline is the CR outline plus the rect-A tab. It is an L-shaped board with one chamfer:

| Feature | MB coordinates | CCB-local (origin at (17.70, 34.14)) |
|---|---|---|
| Body | x 17.70-48.70, y 34.14-67.14 | x 0-31.00, y 0-33.00 |
| High-y tab (rect A) | x 17.70-38.90, y 67.14-76.40 | x 0-21.20, y 33.00-42.26 |
| Inner corner | (38.90, 67.14) | (21.20, 33.00); radius 0.5 mm or more |
| Pin-11 marker | 1.0 mm x 45 degree chamfer at (38.90, 76.40), the tab's +x/+y corner | (21.20, 42.26) |
| Left column, pins 22 to 11 | x 20.998, y 36.544-64.484 | x 3.298, y 2.404-30.344 |
| Right column, pins 1 to 10 | x 45.998, y 39.084-61.944 | x 28.298, y 4.944-27.804 |
| Foot holes | (23.20, 70.64), (32.20, 70.64) | (5.50, 36.50), (14.50, 36.50) |
| Fan-mount holes (r2, proposal) | (26.70, 36.14), (37.70, 36.14), M2 clearance, near the low-y inlet edge | (9.00, 2.00), (20.00, 2.00) |

The body is 31.0 x 33.0 mm = 1023 mm², and the tab is 21.2 x 9.26 mm = 196 mm². The total is about 1219 mm² per side.
Rect A' would add 9.8 x 9.26 = 91 mm² (H_u >= 2.75 mm, passives only).

The fan-mount holes (r2) carry a bracket that holds the fan at the low-y inlet edge (§1.2.3). The proposed positions
are the following:

- They are 5.7 mm from pin 22 (local (3.298, 2.404)) and 8.8 mm from pin 1 (local (28.298, 4.944)).
- Beneath them lies no MB power copper of the §1.5 list: VBT is at x 34.04-35.56 and the VCHG-IN diagonal starts at
  x 39.62 ([WD] A.7).
- They sit in the channel inlet (x 22.33-44.67), so the bracket screws are small obstacles to the gap flow.

The rules for the holes are the following:

1. Keep a copper-free ring around each hole, except the GND net, as for the foot holes (§1.4 rule 3).
2. Choose screws that end 1.0 mm (t_bot) or less below the CCB underside.
3. Fit no fan-mount holes if the fan stands on a bench stand. That option needs no CCB feature.

The hole positions, the bracket and the screw size are TODO(verify: capture placement, L-1; fan and bracket drawings).
The holes cost about 25 mm² of courtyard per side (two keep-out rings of about 2 mm radius), which L-1 must include.

The CR placed its pin-11 chamfer at (17.70, 67.14) ([WD] A.7). The tab removes that corner, so the marker must move. The
proposed marker sits on the tab's +x/+y corner; a y-mirrored capture moves it to a low-y corner. TODO(verify: rerun `pin_identity_check.py` with
the new outline, so a y-mirrored capture moves the marker to a corner the print check sees).

The CR booked about 1082 mm² of courtyard, double-sided, with no charger power stage ([WD] H.18, H.22(k)). The CCB adds a
power stage and removes the J101 header, the W1-W4 lead holes and the EIB interface. Whether 1219 mm² per side is enough is
a placement result. TODO(verify: capture placement, L-1). If it is not enough, rect A' is the first extension and a taller
H_u is its condition. The r2 gap rule (H_u >= 5.125 mm, §1.3.2 rule 3) meets that condition.

### 1.9 Measurements before layout

The operator must make the following measurements before CCB layout starts. Each item states what sets the design value.
Item n of this list is referred to as Mn.

1. **Ag105 standoff h_s (gate D-2).** Where: the fitted Ag105 on the vehicle MB, at all four module corners, before
   removal. Instrument: feeler gauges or a caliper depth rod. Precision: 0.1 mm. Sets: the proven envelope h_s + 10.6 mm
   (1.3.3 item 1). Also record the module top height and the pin length below the MB. r2: record only, because gate D-2
   no longer constrains the CCB height (operator statement, 2026-11-10).
2. **Hole condition after module removal.** Where: all 22 CHG holes. Instrument: pin gauges (1.05 / 1.10 / 1.15 mm) and a
   loupe. Precision: 0.05 mm, plus a pass/fail record for each lifted pad or damaged barrel. Sets: header or socket tail
   choice; any pad repair.
3. **Header and socket seat height.** Where: a dry fit of the chosen strips in the MB holes, with the CCB blank or a 1:1 FR-4
   template, after the module removal (T-K-04). Before the removal, an optional dry fit in a 1.66 mm FR-4 coupon drilled
   1.10 mm gives an early value (T-K-01). Instrument: caliper. Precision: 0.05 mm. Sets: H_u and the foot length (1.4
   rule 2). r2: also sets the channel gap g = H_u - 0.125 mm against 1.3.2 rule 3 (5 mm minimum, 5-8 mm recommended).
   Measure H_u at the inlet edge (y 34.14), at mid-body and at the tab.
4. **Hole positions.** Where: the 22 CHG holes, after the module removal (T-K-04), against a 1:1 print of the A.8 table
   and the pin-11 marker. Instrument:
   print overlay, then a caliper across the 25.0 mm row spacing and the 12-pin column length (27.94 mm). Precision: 0.1 mm.
   Sets: confirmation of the 1.1 pin field; `pin_identity_check.py` step 0.
5. **LM1084 and CO-5V actual heights and positions.** Where: REG-5V at (56.642, 45.974) and CO-5V at (50.800, 39.624).
   Instrument: caliper. Precision: 0.1 mm. Sets: the right-edge rule x <= 48.70 and the H_u > 2.10 mm condition (1.2.2).
   r2: the LM1084 clearance stays checked at the chosen H_u (1.2.2).
6. **Free height H_env.** Where: above the CHG footprint and above rect A, to the lowest chassis part, cable or body panel
   in the installed vehicle. Instrument: caliper or a stack of gauge blocks. Precision: 0.5 mm. Sets: rule 2 of 1.3.2 and
   the tallest top-side part. r2: **record only (testbench)**. The CCB has no height restriction (operator statement,
   2026-11-10), so H_env rejects no stack. Record it with the fan and its mount in place.
7. **Heights of the parts near rect A.** Where: L-FC at (29.464, 83.312), OP-FC at (42.672, 71.628), MDAC-FC at
   (50.038, 71.628), ROP1-FC. Instrument: caliper. Precision: 0.1 mm. Sets: the y 76.40 limit and the rect A' condition.
   The y 76.40 edge is 0.55 mm from the L-FC courtyard (y 76.948, [MECH] §6). If L-FC is taller than H_u, record
   also the gap from the L-FC body to y 76.40; when it is below 1.0 mm (the g_air minimum of 1.3.2), lower the tab edge
   so that the gap is 1.0 mm or more.
8. **J-BL wire and screw envelope.** Where: J-BL at (11.430, 45.720) with the installed wires, and J-NTC and J-FC. Record
   the wire bend radius, the wire exit height and the screwdriver path to the position-3 screw. Instrument: caliper and a
   trial with the operator's screwdriver. Precision: 0.5 mm. Sets: the maximum part height within 5 mm of the CCB left edge.
9. **Screwdriver access to the CCB foot screws.** Where: above (23.20, 70.64) and (32.20, 70.64) in the installed vehicle
   (r2: on the testbench, with the fan and its mount in place). Instrument: trial fit. Precision: pass/fail. Sets: whether
   option B can be serviced in place.
10. **Foot spot surface.** Where: (23.20, 70.64) and (32.20, 70.64). Instrument: loupe and a continuity check to GND.
    Precision: pass/fail (no exposed copper other than GND, no silkscreen ink under the bond). Sets: the bond surface
    preparation; confirms no MB rework is needed.
11. **LM1084 thermal state.** Where: the LM1084 tab and the air at x 48.7, z = 4 mm, beside pins 4-8, at the worst
    vehicle load. Instrument: thermocouple, with the Ag105 removed or fitted as it will be. Precision: 1 C. Sets: rule 4
    of 1.6.1 and the TREG setting.
12. **MB temperature T_MB,0 under the CCB position, and the MB resistance R_MB.** Where: the MB surface at the planned
    power-stage zone (x 25-35, y 55-75), with the Ag105 fitted and idle and no CCB. Instrument: thermocouple; a heater of
    about 400 mm² (for example 20 mm x 20 mm) bonded to the MB at or beside that zone, where the fitted Ag105 leaves room.
    Precision: 1 C. Method: record T_MB,0; then inject 2.3 W into the heater (the option-S P_MB at 2.7 W, §3.7.2) and
    record the steady-state rise of the MB surface beside it. R_MB is the rise divided by 2.3 W. Sets: the ambient for the
    charger thermal design (1.6.2) and the MB self-heating term of §3.7.3. TODO(verify: heater placement beside the fitted
    Ag105). r2: **record only**. With the fan on, T_J moves by 0.15-0.30 C per C of MB idle offset ([LC] §8.6b), so item
    16 replaces this item as the decisive thermal measurement.
13. **MB thickness and copper weight.** Where: an MB board edge. Instrument: micrometer; the fab order record for copper.
    Precision: 0.01 mm. Sets: the socket and header tail length and confirms the 1.6608 mm design value.
14. **Vibration environment.** Where: the MB mounting point on the vehicle during a drive. Instrument: an accelerometer or
    an IMU log, if available. Precision: peak acceleration within 1 g. Sets: the retention margin of 1.7.1. If no
    instrument is available, record TODO(measure) and rely on the post-drive inspection (1.7.2 item 5). r2: **not
    applicable (testbench)**. The vehicle does not move (operator statement, 2026-11-10).
15. **Fan delivery and gap velocity (r2).** Where: the fan at the low-y inlet (1.2.3). Measure first on the 1:1 FR-4
    template of item 3, seated at the chosen H_u before layout. Measure again on the built CCB. Measure the air velocity
    at the inlet edge, in the gap at the inlet, at mid-body and at the outlets (y 67.14 and y 76.40). Also measure it
    about 5 mm above the CCB top. Instrument: vane or hot-wire anemometer with a probe that fits the 5-8 mm gap,
    TODO(verify: instrument). Precision: 0.2 m/s. Sets: the gap and top velocities of the forced-air model (2 m/s or
    more on both sides, [LC] §8.6), the duct capture fraction (30-50 % assumed, [LC] §8.9) and the fan choice. Record
    the fan voltage and current. Make sure that the fan supply is not the LM1084 / CO-5V rail (1.2.3 rule 7).
16. **Fan-on and fan-off thermal soak (r2).** Where: the built CCB at the chosen H_u. Run the charger at the 2.7 W
    point and at the 2.08 W derate image ([LC] §5.8, §8.7). Instrument: thermocouples on the U501 top, the PGND pour
    beside U501, L501, the MB surface under the cell, the inlet air and the outlet air at y 67.14 and y 76.40; TDIE over
    I2C. Precision: 1 C. Method: record the fan-on steady state. Then stop the fan and record the transient to the
    FR-50 derate and trip. Sets: the real h and gap flow, the fan-on T_J at 2.9 W against the 100 C target (model
    78-90 C at 25 C room air, [LC] §8.6), and the FR-50 thresholds, TODO(calibrate). This item runs after the build.
    §3.7.3a and the T-K-20 row give the pass criteria. T-K-14 is the fan-on leg of T-K-20.
17. **Bench room air (r2).** Where: the fan inlet, over a bench session. Instrument: thermocouple. Precision: 1 C. Sets:
    T_air of the forced-air model. The [LC] §8 margins assume 25 C room air.

### 1.10 Architecture and the IC interface contract (IC-independent)

#### 1.10.1 Block structure

Figure 1.10 shows the board as five blocks:

1. **Header block (I):** H301, 22 pins; 11 carry nets, 11 are soldered anchors.
2. **Input protection block (I):** eFuse U301 with its input bulk C302a/b/c, TVS D307, output capacitor C303 and output
   Schottky D303. It converts the unprotected MB net VCHG-IN into the protected net VCHGOUT.
3. **Interlock block (I, with S exceptions):** the seven comparators U302-U304, U315, U319-U321, the permit logic U305-U310,
   U314, U316, U318, U322, the pack-OV input U323, the heartbeat monostable U313, the QUAL one-shot U311 (S), the readback
   resistors and the tap field F01-F24.
4. **Charger interface block (S):** open-drain drivers U401/U402, the ILIM_HIZ hold, release and FC-clamp switches
   Q401-Q403, the /CE pull-ups R472/R472b and the two pin senses U403/U404.
5. **Power stage block (S):** U501 BQ25798 and its passive network.

```
Figure 1.10. Block diagram of the custom charger board (CCB), one board in the 22 Ag105 (CHG) holes.
Labels: [I] IC-independent, [S] BQ25798-specific. Designators per section 0.5 of the design document.
Values: design document sections 1.11-1.13 and 2 (round-3 [WD] B.1-B.8 values carried over).

 MB (motherboard)                       CUSTOM CHARGER BOARD
 ================                       ====================================================================================

                                        [I] INPUT PROTECTION                         [S] POWER STAGE (U501 BQ25798RQMR)
 VCHG-IN (D-BC-FC/D-BC-RG) --H301.10--> VCHGIN --+--C302a/b/c, D307 TVS (>=36 V)     1.5 MHz, PROG R529 6.04k, L501 1.0 uH
  (<= 5 mm masked copper, no TP)                 |                                   +------------------------------------+
                                                 +--> U301 TPS26630 eFuse ---------->| VBUS(2,3)  VAC1(9) VAC2(8)          |
                                                     I_OL 2.23 A, OVP 23.12 V,       |   C511,C512 10u/50V, C513,C514 0.1u |
                                                     UVLO 9.91 V, dVdT C301          | PMID(29) C529-531 10u/50V, C532     |
                                                     IMON R305 -> R329 -> F18 (pin22)| SW1(28)--L501--SW2(26)  BTST C506/8 |
                                                     FLT -> F17 (pin 35)             | SYS(25) C518, C519-523 (local only) |
                                                     OUT: C303, D303 -> VCHGOUT      | BAT(22,23) C538,C539 ------------+  |
                                                                                     | BATP(18) <-R515 100R- BAT        |  |
                                                                                     | SDRV(24) -C536 1nF- GND          |  |
                                                                                     | ACDRV1/2 -> GND, D+/D- open      |  |
                                                                                     | REGN(5) C535 4.7u                |  |
                                                                                     | PROG(20) R529   TS(16) R518/R524 |  |
                                                                                     +----------------------------------|--+
 VCHG (C-D11) -> D-BT-SQ -> pack VBT <------------------------------- H301.18/19 <-------- VCHG <---------------------+
 GND (pack negative = PCB GND) <---------------- H301.4 (input return), H301.14/15 (battery return): the only GND contacts
 SDA/SCL (Teensy 18/19, MB 2.7k pull-ups) ------ H301.8/7 ---------------> U501 SDA(15)/SCL(14)   (no board pull-ups)
 J-NTC pin 1 (N$34) ---------------------------- H301.13 -- TS_EXT --R526 0R (NTC fitted)--> TS(16); XOR R525 10k TS-GND (sim)
 Teensy 6 (CHRG-STAT) <------------------------- H301.3 -- STAT <--R475 1k-- U501 STAT(1); R307 10k -> 3V3
 Teensy 5 (MPPT-DISABLE) ----------------------- H301.11 -- CHG_ARM (P5, R308 47k pull-down) --+
                                                                                               |
 FLYING TAPS (F01-F24)                   [I] INTERLOCK BLOCK (3V3 rail via R375 68R from T6)   v
 T1  V-MOT (R170 at C-D6) --F01--> U302 H1     V-MOT > 1.089 x VBUS ---+     U305 P5N
 T2  VBUS  (R171 at C-D2) --F03--> U302 IN-, U303 UVB (13.33/13.72 V) -+     U306-U310, U316, U318 permit gates:
 T8/T9 BT-CURR + Kelvin  --F09/F10--> U304 BT_OK (< 19.75 mV)          |       H1q = H1.RGN_ON.FCC_OFF.UVB
 T3  BT_BUS EN (pin 28)  --F04--> U315 BTB_OFF (< REF/3)               |       H2c = FCC_ON.BTB_OFF.BT_OK.FCI_OK.
 T5  FC_CHARGE EN (31)   --F06--> U319 FCC_OFF, U320 FCC_ON            +--->         ((UVB.FCCEIL) + H1.RGN_ON)
 T4  REGEN EN (30)       --F05--> U321 RGN_ON                          |       GATE = H1q + H2c
 T22 BQ29200 OUT         --F08--> R378/D308/R379 -> U323 -> OVN        |       ILIM_PRE = GATE + QQF  (QQF = QQ.FCCN) [S]
 T21 HB (pin 21)         --F21--> U313 heartbeat, tw 20-46 ms -> ARM_OK|       ARM_OK' = ARM_OK . OVN          (U322)
 T10 QUAL (pin 10)       --F11--> U311 one-shot 0.20-0.46 s -> QQ [S]  |       CE_DRV   = P5 . ARM_OK'         (U314A)
 T11 FCCEIL (pin 17)     --F12--> U316                                 |       ILIM_REL = ILIM_PRE . ARM_OK'   (U314B)
 T19 FC_CURR (DNP)       --F23--> U317 FCI_OK option (else R337 link)  |       RFC_OFF  = FCCN + H1R           (U306B)
 Readbacks: H1 -> F14 (pin 34), H2c -> F15 (pin 16), BT_OK -> F16 (pin 23)
 Keep-alive (DNP): F22 (5V via F101/R172 on MB) -> U312 TPS22810 (EN = RGN) -> D301 -> R392 680R -> VCHG
                                                                       |
                                       ======== IC INTERFACE CONTRACT (sections 1.10.2, 1.14) ========
                                       CE_DRV, ILIM_REL, RFC_OFF  ->      <- ILIM_SENSE, CE_SENSE, STAT
                                                                       |
                                        [S] CHARGER INTERFACE BLOCK (ex-EIB, now local)
                                        CE_DRV ---R467 pd---> U401 ch1 (open drain) ---> /CE(13) <- R472, R472b 47k to REGN
                                        ILIM_REL --R468 pd--> U401 ch2 --> Q403 BSS84 (S=REGN) -> R455 48.7k -> ILIM_HIZ(17)
                                        ILIM_REL --R470 pd--> U402 ------> Q401 2N7002K hold (gate R452 to REGN) -> ILIM_HIZ
                                        RFC_OFF ---R469 pd--> U401 ch3 --> Q402 2N7002K + R457 59.0k (FC clamp leg)
                                        ILIM_HIZ: R523 49.9k, R456 200k, C452 2.2nF to quiet GND
                                        U403 (ILIM sense, 0.587-0.650 V) -> R325 1k -> F13 (pin 33)
                                        U404 (/CE sense, ~2.5 V)         -> R348 1k -> F20 (pin 7, MB ROS pad)
                                        R474 10k 3V3 bleed

 GROUND: one plane (net GND). Power returns: input loop -> H301.4; battery loop (SYS/BAT caps, U501 GND) -> H301.14/15.
         Quiet returns (eFuse settings, ILIM, TS, PROG, comparator dividers, logic) join the plane away from both paths.
         Shields T7b (F02), T17r (F19) bonded at the board end only; BT_OK Kelvin via F10 with R343 100R to the plane.
```

#### 1.10.2 Interface contract between the interlock block and the charger

The interlock block produces three generic commands and consumes two pin senses. An alternative charger IC must accept
these signals with the same fail-safe meaning, or the charger interface block must be redesigned ([WD] B.1).

| Signal | Direction | Generic meaning | Fail-safe level | BQ25798 realisation |
|---|---|---|---|---|
| `CE_DRV` | logic -> charger | charge enable | LOW = inhibit (also with the driver unpowered) | U401 ch1 sinks /CE |
| `ILIM_REL` | logic -> charger | converter release | LOW = converter held off | U401 ch2 -> Q403 feed; U402 -> Q401 hold |
| `RFC_OFF` | logic -> charger | remove the FC current clamp | LOW = FC clamp in force | U401 ch3 -> Q402 |
| `ILIM_SENSE` | charger -> Teensy pin 33 | converter is released at the IC pin | dead source reads "held" | U403 on ILIM_HIZ |
| `CE_SENSE` | charger -> Teensy pin 7 | charge inhibit present at the IC pin | dead source reads "/CE LOW" (announces itself) | U404 on /CE |
| `STAT` | charger -> Teensy pin 6 | charger status | pulled HIGH by R307 | BQ25798 STAT (LOW = charging, [DS] Table 7-11) |

Two further properties of the BQ25798 realisation are part of the contract, because the fail-safe levels above depend on
them. First, the inhibit and hold pull-ups (R472/R472b, R452, R454, R471) and the release feed (Q403) are biased from the
charger's own rail REGN, so the inhibit is asserted whenever the charger can switch. A substitute IC needs an equivalent
internal rail that is present whenever its converter can run, or the charger interface block must supply one. Second, the
two pin senses compare against the IC's own pin thresholds (VIL_ILIM_HIZ 0.75 V, /CE VIH/VIL); a substitute IC needs the
sense thresholds re-derived from its datasheet (§5.9.1).

### 1.11 Input protection: eFuse and TVS (IC-independent)

#### 1.11.1 Carried over unchanged

U301 and its network carry over from [WD] B.4 with the same values: R301 8.06 kOhm (I_OL 2.05-2.41 A), R302/R303/R304
845 k / 66.5 k / 49.9 k 0.1 % (UVLO 9.91 V, OVP 23.12 V), C301 22 nF (dVdT), C302a 1.0 uF 100 V, C302b 4.7 uF 100 V,
C302c 100 nF 100 V, D307 SMAJ33A-class TVS, C303 1.0 uF 50 V, D303 >= 40 V Schottky, R305 27.4 kOhm IMON (C305 DNP),
R329/C329 IMON filter to F18, R306 DNP (FLT pulled up only by Teensy pin 35). MODE, SHDN, B_GATE, DRV and N.C. stay open;
PGTH and PGOOD stay on GND. The layout rule "VCHGIN copper from the pad-10 pin to U301 IN <= 5 mm, solder-masked, no
exposed test pad" carries over ([WD] A.8).

#### 1.11.2 What changes because the charger is on the same board

1. **The eFuse output drives the BQ25798 VBUS directly.** The VCHGOUT capacitance is C303 + C511-C514 + C529-C532 =
   51.3 uF nominal ([CALC]), equal to the round-3 51.4 uF ([WD] B.4). The dVdT inrush at 2.19 V/ms stays 0.11 A ([CALC]).
   The 50 V parts may retain more capacitance under bias than the EVM's 25 V parts, so the effective value is TODO(verify:
   DC-bias curve). The inrush cannot exceed the nominal-capacitance figure.
2. **D303 loses its main case.** D303 was sized for a hard short at the far end of the 0.3 m W1/W2 leads ([WD] B.4). The
   board has no leads, so the OUT loop inductance falls to the copper value. D303 stays fitted, because TI recommends a
   Schottky on OUT for any inductive interruption (SLVSE94G §9.5.1, §11, as cited in [WD] B.4). It may become DNP only if
   T-C-04 on the CCB shows OUT >= -0.3 V at a hard short. Its leakage criterion (IR <= 0.1 mA at 23.6 V and 60 C)
   needs re-checking at the board temperature next to the LM1084, TODO(measure: board temperature at D303).
3. **The input-path resistance falls.** R_PATH_RG 0.12-0.19 Ohm included W1/W2, EVM R2 (10 mOhm) and EVM JP3 ([STUDY]
   §3.1, finding input-path-ir-drop-omitted). The warm-response budget H.19 must be re-derived with the board copper.
   TODO(calc: H.19 with R_PATH_RG minus W1/W2, R2, JP3).
4. **The IN-side transient changes (r2).** The r1 statement "The IN-side transient is unchanged" is superseded (N-25).
   C302a/b/c and D307 still absorb the energy of the 50-150 nH MB VCHG-IN path, which is upstream of the board
   ([WD] B.4). However, the OUT loop sets the turn-off current. Without the 150 nH W1/W2 lead, 5-20 nH of OUT copper
   raises the ideal hard-short turn-off current from 65 A to 103-117 A. The ideal U301 IN peak then rises from 32.8 V
   to 35.5-40.0 V. At 10-20 nH the peak exceeds the D307 VBR minimum of 36.7 V, so D307 conducts ([TS] §(c)). The tall
   stack adds 0-0.3 V. The 60 V T-C-04 criterion, the 67 V U301 maximum and the MB end (about 20 V) keep their margins.
   The OUT copper inductance and the D307 energy are TODO(calc) (§6.7 item 5).

### 1.12 Interlock logic carried over (IC-independent unless marked)

#### 1.12.1 What carries over

Every round-3 CR function carries over with unchanged values and equations ([WD] B.1-B.3, B.5): the permit logic and its
truth table, the seven comparators (H1, UVB, BT_OK, BTB_OFF, FCC_OFF, FCC_ON, RGN_ON), the heartbeat monostable and ARM_OK,
the pack-OV term OVN from the BQ29200 OUT (T22), ARM_OK' = ARM_OK AND OVN, the FCI_OK option (DNP), the keep-alive option
(DNP), the tap field F01-F24, the readbacks to pins 16/23/33/34/7, the 3V3 feed limiter R375 and the BT_OK Kelvin. Table 1.12
maps each function to the new designators.

| Function | Round 3 | Custom board | Class |
|---|---|---|---|
| H1 (V-MOT > 1.089 x VBUS) | U102, R109-R113, C106, C107, D104, D105 | U302, R309-R313, C306, C307, D304, D305 | I |
| UVB (VBUS > 13.33/13.72 V) | U103, R114-R116, C108, D106 | U303, R314-R316, C308, D306 | I |
| BT_OK (INA253 BT < 19.75 mV) | U104, R140-R144, C140 | U304, R340-R344, C340 | I |
| BTB_OFF | U115, R117-R120, C109 | U315, R317-R320, C309 | I |
| FCC_OFF (= FCCN), FCC_ON, RGN_ON | U119-U121, R184-R191, C130 | U319-U321, R384-R391, C330 | I |
| Tap inputs RGN, FCC | R121, R133; R122, R134 DNP | R321, R333; R322, R334 DNP | I |
| FCI_OK option (DNP) / link | U117, R160-R163, C124, C127 / R137 | U317, R360-R363, C324, C327 / R337 | I |
| Pack-OV input OVN | R178, D108, R179, U123 | R378, D308, R379, U323 | I |
| ARM_OK' | U122 | U322 | I |
| P5N inverter | U105 | U305 | I |
| Permit gates UF, W, X, Y1, H2c, H1q, H1R, GATE, ILIM_PRE, CE_DRV, ILIM_REL, RFC_OFF | U106-U110, U114, U116, U118 | U306-U310, U314, U316, U318 | I (the FCCEIL meaning is S) |
| Heartbeat monostable ARM_OK | U113, R151, C151, R135, R136 | U313, R351, C351, R335, R336 | I |
| QUAL one-shot QQ, QQF | U111, R150, C150, R147, R123; U118B | U311, R350, C350, R347, R323; U318B | **S** (exists for the BQ25798 ILIM_HIZ POR ADC read, [DS] §7.3.4.3) |
| CHG_ARM pull-down, FCCEIL pull-down | R108, R124 | R308, R324 | I |
| Readbacks H1, H2c, BT_OK | R126, R127, R128 | R326, R327, R328 | I |
| Pin-sense outputs to taps | R125 (pin 33), R148 (pin 7) | R325, R348 | S |
| STAT pull-up | R107 | R307 | I |
| 3V3 feed limiter, rail bulk | R175, C125 | R375, C325 | I |
| I2C pull-up footprints | R145, R146 DNP | R345, R346 DNP | I |
| eFuse FLT pull-up | R106 DNP | R306 DNP | I |
| Keep-alive option (DNP) | U112, D101, R_KA, C152 | U312, D301, R392, C352 | I |
| Decoupling | C110-C123, C126, C131-C135 | C310-C323, C326, C331-C335 | I |

#### 1.12.2 What changes in the logic block

1. **The ribbon damping resistors are deleted:** R130 (CE_DRV), R131A/R131B (ILIM_REL), R132 (RFC_OFF). They damped a
   0.30 m flat cable ([WD] B.3). The three outputs now reach U401/U402 over on-board traces.
2. **J101, R176 and R177 are deleted.** The ex-EIB stages share the one 3V3 rail behind R375.
3. **The W1-W4 holes and the W6/W7 pads are deleted.** TS_EXT, SCL and SDA run from header pins 13, 7 and 8 straight to
   U501 (via R526 for TS_EXT).
4. **The tap field stays.** The flying taps T1-T22 to the MB remain, so every tap-related rule and finding stays open
   ([STUDY] §3.1, N set). Their placement on the board is a layout item.

### 1.13 Ground scheme

#### 1.13.1 One ground net (IC-independent principle, BQ25798-specific placement)

The board has one ground net, GND, on a continuous inner plane. A separate AGND and a net tie are not used: [UG] §3 item 7
states that two grounds are not required, provided the ground terminals of sensitive parts connect away from the
high-current return paths. The pack negative is PCB GND by design (operator, 2026-11-04, [WD] A.6), and the BQ25798 senses
input and charge current high-side internally ([DS] Table 5-1), so the requirement R-GND (VIN- = VBAT-) is met ([WD] A.6).

#### 1.13.2 Where the grounds meet

1. **Power return, input side:** the eFuse PAD/GND, C302a/b/c, D307, C303, D303, C511-C514 and C529-C532 return to header
   pad 4 (VIN-) through a power pour on the outer layer, stitched to the plane. Pad 4 is in the x 46.0 column with pad 10
   (VIN+), 15.2 mm away ([MECH] §1: pad 4 at y 46.704, pad 10 at y 61.944).
2. **Power return, battery side:** C518-C523 (SYS), C538/C539 (BAT) and U501 GND (pin 27) return to header pads 14/15 through
   a power pour, stitched to the plane. Pads 14/15 are in the x 21.0 column, 7.6-12.7 mm from pads 18/19 ([MECH] §1).
3. **The U501 high-frequency loops** (PMID cap - Q1 - Q2 and Q3 - Q4 - SYS cap, [DS] Fig 8-20) close on the outer layer at
   the IC ([DS] §8.4.1 items 1-2). They do not route through the header pins.
4. **Quiet returns:** R301, R304, R305, C301 (eFuse settings), R523, R456, C452, R461, R463 (ILIM_HIZ and senses), R524,
   R525, R529 (TS, PROG), the comparator divider bottoms (R310, R312, R315, R318, R385, R389, R391), R343 and every logic IC
   ground. They connect to the plane in a region that carries no power-return current ([UG] §3 item 7).
5. **MB connection:** the board GND meets the MB GND only through header pads 4, 14 and 15. The 11 anchor pads are isolated
   on both boards ([WD] A.2), so they cannot carry ground current without MB rework. The MB pads 4/14/15 are solid to both MB
   pours with no thermal relief ([STUDY] §4.2).
6. **Shields and Kelvin:** T7b (F02) and T17r (F19) are bonded at the board end only; R342 returns to the T9 Kelvin wire
   (F10) with R343 100 Ohm to the plane ([WD] A.6). These rules are unchanged.

#### 1.13.3 Header-pin currents

Table 1.13 gives the current per pin. The battery-side basis is ICHG 3.21 A ([WD] A.3, r5); the 60/40 sharing assumption
between paired pins is from [WD] A.8 (r6).

| Pin(s) | Net | Current | Basis | Required pin rating |
|---|---|---|---|---|
| 10 | VCHGIN | <= 1.76 A normal; <= 2.41 A for <= 202 ms | ILIM regen clamp max ([WD] H.4); eFuse I_OL and tCL_PLIM ([WD] B.4) | >= 3 A ([WD] A.8) |
| 4 | GND (input return) | as pin 10 | - | >= 3 A (this section: same as pin 10, since it carries the same current) |
| 18, 19 | VCHG | 3.21 A total; 1.93 A / 1.28 A at 60/40 ([CALC]) | [WD] A.3, A.8 r6 | >= 2.0 A each ([WD] A.8) |
| 14, 15 | GND (battery return) | as 18/19 | - | >= 2.0 A each ([WD] A.8) |

- **Three of the 22 header pins are GND** (4, 14, 15).
- The board plane joins the input and battery returns. The net current that crosses into the MB GND is about I_BAT - I_IN,
  for example 3.21 - 1.76 = 1.45 A ([CALC]). The split among pads 4, 14 and 15 depends on the MB copper, so each pin keeps
  the rating of its own path.
- The CCB plane also joins pad 4 (x 46.0) and pads 14/15 (x 21.0) in parallel with the MB GND pour. MB return current,
  for example from a 12 A brake, can therefore divert through the header pins and the CCB plane. This current is not
  modelled, because the MB copper weight and the pin contact resistance are not in the library. T-K-17 step (4) measures
  the pin currents.
- The current rating of the Samtec TSW-1xx-07-G-S pin is not in the library: TODO(verify: Samtec TSW datasheet or test
  report, T-A-05). T-F-16 logs one VBAT+ joint (rise < 20 C) ([WD] A.8).

#### 1.13.4 Offsets that change and offsets that remain

1. **Removed:** the I2C and TS offset through the lead returns (<= ~20 mV at 3.1 A, [WD] H.11) and the EIB single-ground
   issues (R273, E8). SDA, SCL, STAT and TS now reference the board plane, which is bonded to the MB at pads 4/14/15.
2. **Remaining:** IMON (pin 22) and the V_chg divider (pin 38) still ride the MB-GND drop between pads 4/14/15 and the
   Teensy AGND (1.31 A per volt on pin 22, [WD] A.6 r5). T-F-15 still applies.
3. **New:** the charger's switching return now sits on the same board as the comparators. The comparator dividers see the
   plane offset only as a common term (about 0.07 x delta for H1, [WD] A.6). TODO(measure: plane noise at the U302/U303
   divider bottoms during 1.5 MHz switching, T-C-07 / S4-n class).

### 1.14 Interface contract for a replacement charger IC (IC-independent)

#### 1.14.1 Purpose

The parallel IC search may replace the BQ25798. A replacement IC keeps every block of section 1 unchanged only if it meets
the contract of Table 1.14. Where a row fails, the named block must be redesigned. Sections 2.2 and 2.3 (the charger
interface block) and the whole of section 2.1 (the power stage) are always redesigned for a new IC. Section 5.9 gives the
firmware side of the same contract.

#### 1.14.2 Contract

Table 1.14 lists the signal and electrical requirements. The right-hand column gives the BQ25798 realisation as the
reference case.

| # | Item | Requirement on a replacement IC | BQ25798 realisation | Source |
|---|---|---|---|---|
| 1 | Charge-inhibit input (`CE_DRV`) | An inhibit pin that inhibits charging when it is undriven and when its open-drain driver is unpowered | /CE (pin 13), held HIGH by R472/R472b to REGN; U401 ch1 sinks it | §1.10.2; §2.2.1 |
| 2 | Converter-off input (`ILIM_REL`) | A pin that stops switching independent of the registers and keeps the IC's bias rail on | ILIM_HIZ (pin 17) below VIL_ILIM_HIZ 0.75 V; hold Q401, release Q403 + R455 | §2.2.1; [DS] §7.3.4.3, EC p.16 |
| 3 | FC current clamp (`RFC_OFF`) | A pin-set input-current limit, or a hardware FC-current shed (the U317 option) | Q402 + R457 leg on ILIM_HIZ, FC clamp 0.65-0.95 A | §2.2.1; [WD] H.4 |
| 4 | Pin senses (`ILIM_SENSE`, `CE_SENSE`) | Sense thresholds re-derived from the IC's own pin thresholds; a dead sense source must read "held" or announce the inhibit | U403 threshold 0.587-0.650 V; U404 threshold about 2.5 V | §1.10.2; §2.3.1; [WD] B.6 |
| 5 | Internal bias rail | A rail that is present whenever the converter can run, to bias the inhibit and hold pull-ups, or a rail that the charger interface block supplies | REGN | §1.10.2 |
| 6 | Status and fault output (`STAT`) | An open-drain status output with a documented encoding that tolerates a 3.3 V pull-up and a 3.3 mA sink through R475 | STAT (pin 1): LOW = charging, 1 Hz blink = fault; 6 V and 6 mA absolute maximum | §2.2.1; [DS] Table 7-11, §6.1 |
| 7 | I2C | A free address on the Teensy bus (pins 18/19), operation at 400 kHz with the 2.7 kOhm MB pull-ups, logic thresholds compatible with 3.3 V, and a register watchdog that reverts to safe limits | Address 0x6B; VIH 1.3 V minimum; WATCHDOG 0.5 s | §2.2.1; §5.5; [DS] §7.3.14 |
| 8 | Power-good | An input-present or power-good indication that firmware can read, as a pin or a register | No PG pin; PG_STAT and VBUS_PRESENT_STAT over I2C (FR-23) | §2.2.1; [DS] Table 4-1 |
| 9 | Input voltage | IC input pins that tolerate the eFuse OVP maximum of 23.63 V inside their recommended range; every external input-side part rated 35 V or more | VBUS 30 V absolute maximum, 24 V recommended maximum | §2.1.4; [DS] §6.1, §6.3; [WD] B.4 |
| 10 | Charge current | 3.10 A continuous at 2S in the regen image (3.21 A with the +3.5 % tolerance) | ICHG 3.10 A regen image | [WD] A.3, G.1 |
| 11 | Battery | 2S, 7.4-8.4 V; VREG 8.40 V (8.32 V interim, FR-40) | PROG strap for 2S | §5.5.2 |
| 12 | Ground | Operation with the pack negative on PCB GND: current sense that needs no separate VIN- and VBAT- returns (requirement R-GND) | High-side internal current sense | §1.13.1; [WD] A.6 |
| 13 | Input qualification | If the IC needs an input-qualification window, the QUAL one-shot U311 stays; otherwise U311 and Teensy pin 10 are removed | ILIM POR ADC read | Table 1.12; §5.9.1 |
| 14 | Readings for FR-50 and FR-51 | Die temperature and battery voltage readable over I2C; otherwise a board thermistor and an analog input, for which no spare Teensy pin exists | REG41_TDIE_ADC; VBAT ADC | §5.6; §5.4.1 |
| 15 | Physical | A power stage that fits zone Z-P (x 22.4-37.5, y 50.4-67.4) and dissipates about 2.7 W or less at the regen point, or a new thermal design | RQM VQFN-HR 4 x 4 mm; about 2.7 W board loss | §3.2.2; §3.7.1 |

A replacement IC that meets rows 1-15 keeps the header, the eFuse, the comparators, the permit logic, the heartbeat, the
pack-OV term, the taps, the ground scheme, the outline and the feet unchanged. The interface contract of §1.10.2 then
binds the new charger interface block.

## 2. BQ25798-specific design

This section gives the schematic-level design of the BQ25798 power stage (§2.1) and of the charger control pins (§2.2). It
then gives the disposition of every EIB part (§2.3) and of every EVM modification (§2.4), the complete pin-level netlist
(§2.5) and the power-up and reset states (§2.6). The design follows the EVM schematic ([UG] Figs 4-5 to 4-7) and the
round-3 values ([WD] B.1-B.8) unless a reason is given.

The netlist of §2.5 is complete in one place. Subsections 2.5.2, 2.5.3 and 2.5.6 to 2.5.9 therefore also hold the
IC-independent parts of the board (header, eFuse, comparators, logic, keep-alive option and taps); each subsection carries
its label.

### 2.1 Power stage (BQ25798-specific)

#### 2.1.1 Design decisions

Table 2.1 records the power-stage decisions. Each decision follows the EVM ([UG] Fig 4-5/4-6) unless a reason is given.

| # | Decision | Choice | Reason and source |
|---|---|---|---|
| D1 | Inputs | **Single input.** VAC1 and VAC2 tied to VBUS (= VCHGOUT); ACDRV1 and ACDRV2 tied to GND | [DS] Table 5-1: tie VACx to VBUS and ACDRVx to GND when the FET pair is absent; POR then sets DIS_ACDRV = 1 ([DS] §7.3.5, [TID] §2.8). The round-3 image already writes REG13 = 0x01, ACDRV off ([WD] G.1) |
| D2 | ACFET/RBFET pair (EVM Q1/Q2, ACDRV1) | **Omitted; the eFuse U301 is kept** | (a) Reverse blocking already exists upstream in the MB RT1987 switches D-BC-FC and D-BC-RG ([STUDY] §1.4, RT1987 DS-00 §17.6). (b) The eFuse OVP cuts at 22.61-23.63 V ([WD] B.4), below the BQ25798 VBUS recommended maximum 24 V and the 30 V absolute maximum ([DS] §6.1, §6.3). VAC_OVP cannot add a second barrier below 24 V: its 26 V setting trips at 25.2-26.8 V and VBUS_OVP trips at 25.2-26.2 V ([DS] EC), both above the 24 V recommended maximum. The 18 V setting (17.4-18.6 V) would trip at the measured V-MOT of 21.5 V (§5.5.2 item 5). The eFuse OVP is therefore the only protection between 23.63 V and the IC's own 25.2 V thresholds (O-3). (c) The EVM FETs CSD17581Q3A are 30 V parts ([UG] Table 4-1), below the 35 V rule. (d) The pair adds series resistance in the regen path, whose budget is already tight ([WD] r3-11, R_PATH_RG). Residual: an eFuse FET short together with a V-MOT excursion above 30 V is a double fault (open item O-3, §8.3.1) |
| D3 | eFuse | **Kept unchanged** (TPS26630RGER, I_OL 2.23 A, OVP 23.12 V, UVLO 9.91 V) | The eFuse is the only current limit on VCHG-IN in Run ([WD] B.4 "unprotected segment"); it is IC-independent. §1.11 |
| D4 | Switching frequency | **1.5 MHz, PROG = 6.04 kOhm 1 %** (2S) | Identical to the EVM build and to the round-3 register image (REG13 PWM_FREQ 0, [WD] G.1), so the T-B bench results transfer. [DS] Table 7-1 p.25. 750 kHz (PROG 8.2 kOhm, 2.2 uH) is the documented alternate (§2.1.3) |
| D5 | Inductor | **1.0 uH, Isat >= 6.5 A over temperature ([DS] Eq 4; saturation criterion L >= 0.70 uH at 6.5 A, §2.1.3)**; SPM6530T-1R0M120 only until O-4 closes; EVM part TDK SPM6530T-1R0M120 (11.1 A, 7.8 mOhm, 7.1 x 6.5 x 3.0 mm, [UG] Table 4-1) | [DS] §8.2.2.2: "the 1.5 MHz switching frequency only works with the 1µH inductor". Worst-case peak 5.51 A (§2.1.3). TODO(verify: TDK SPM6530T datasheet, that 11.1 A is the saturation rating and its temperature basis) |
| D6 | Ship FET (BATFET via SDRV) | **Omitted.** SDRV -> 1 nF 50 V 0402 C0G -> GND | [DS] Table 5-1 rev C: "Connect a 1nF, 50V rated, 0402 package, ceramic capacitor from SDRV to GND when the ship FET is not used". The pack is permanently on PCB GND and D-BT-SQ already isolates the pack from VCHG in reverse ([WD] B.5). Rev C deleted the SDRV-to-BAT option that round-3 EM13 used ([TID] §7 item 1) |
| D7 | SYS vs BAT | **SYS is local only** (converter output decoupling, no external load, no wire terminal). **BAT -> net VCHG -> header pins 18/19 -> MB VCHG -> D-BT-SQ -> pack VBT** | Same topology as round 3: EVM J3 (SYS) was capped, the battery path ran BAT -> JP5 -> J5 -> W3 -> CR VCHG -> pins 18/19 ([WD] A.1, EM7, EM12). The internal BATFET (11 mOhm typ, [DS] EC) connects SYS to BAT during charge. VSYSMIN register image 0x04 unchanged ([WD] G.1) |
| D8 | BATP sense point | **BATP -> R515 100 Ohm -> BAT pins of U501** | [DS] Table 5-1: 100 Ohm series resistance. Round-3 EM9 sensed at the BAT pin so that BATP never floats; on-board copper keeps that property. A remote sense at pins 18/19 would add only the pour drop and is not adopted |
| D9 | Input RC snubber (2 Ohm + 2.2 uF) | **DNP footprint** | [DS] Fig 8-1 Note 1 applies to hot-plugged adapters > 15 V. VCHGOUT is ramped by the eFuse dVdT (2.19 V/ms, [WD] B.4) behind the RT1987 soft start (round-3 EM21) |
| D10 | SW1/SW2 RC snubbers, PMID/SW/SYS clamp Schottkys | **Snubber footprints DNP; clamp diodes omitted** | EVM fits none of them (R7/C5, R10/C7, D3/D4/D7/D8 DNP, [UG] Table 4-1) |
| D11 | BAT TVS | **Omitted** | [DS] Fig 8-1 Note 2 applies to 4S packs with long leads; this is 2S on-board copper |
| D12 | Backup mode / PMID POSCAP | **Omitted** | Backup mode requires the ACFET pair ([DS] §8.1); EN_BACKUP stays 0 ([WD] G.1) |

#### 2.1.2 Power-stage parts

Table 2.2 lists every power-stage part. "Input side" means the part sees VCHGOUT or PMID and must be rated >= 35 V (task
rule; V-MOT measured 21.2-21.5 V, clamp 21.98-22.28 V). All parts in this table are **BQ25798-specific (S)**.

| Ref | Was (EVM) | Value | Voltage rating | Package | Candidate MPN (to check in T-A-05) | Reason |
|---|---|---|---|---|---|---|
| U501 | U1 | BQ25798 | VBUS/PMID/VAC/SW1 30 V abs max; SW2/SYS 23 V; BAT 20 V ([DS] §6.1) | RQM VQFN-HR 29 pins, 4 x 4 x 1.0 mm, no exposed pad ([DS] pp.146-149) | BQ25798RQMR ([DS] p.146) | Charger |
| L501 | L2 | 1.0 uH, Isat >= 6.5 A ([DS] Eq 4; L >= 0.70 uH at 6.5 A and T_max, §2.1.3); SPM6530T-1R0M120 only until O-4 closes | - | 7.1 x 6.5 x 3.0 mm class | TDK SPM6530T-1R0M120 ([UG] Table 4-1) | §2.1.3 |
| C511, C512 | C11, C12 | 10 uF X7R | **50 V** (input side) | 1210 preferred, 1206 acceptable | TODO(verify: 50 V 10 uF X7R MPN and DC-bias curve at 23.6 V); no 0805 fallback (§4.1.2 item 3) | VBUS bulk, 2 x 10 uF ([DS] Table 5-1); effective C_VBUS >= 2 uF at 23.6 V ([DS] §6.3) |
| C513 | C13 | 0.1 uF X7R | 50 V | 0402 | TDK C1005X7R1H104K050BE ([UG]) | VBUS HF, closest to pins 2/3 ([DS] §8.4.1 item 4) |
| C514 | C14 (+C15 merged) | 0.1 uF X7R | 50 V | 0402 | C1005X7R1H104K050BE | VAC1/VAC2 decoupling at pins 8/9 |
| C529, C530, C531 | C29-C31 | 10 uF X7R | **50 V** (input side) | 1210 / 1206 | as C511 | PMID bulk, 3 x 10 uF; effective C_PMID >= 4 uF at 23.6 V ([DS] §6.3); ripple current up to 1.61 A rms total (0.54 A per capacitor at equal sharing) at ICHG 3.21 A; this is the D = 0.5 maximum ICHG/2 at VBUS = 2 x VSYS = 16.8-17.6 V, inside the operating range ([DS] §8.2.2.3, Eq 7, [CALC]) |
| C532 | C32 | 0.1 uF X7R | **50 V** (input side; TDK code 1H, TODO(verify: TDK DS)) | 0402 | C1005X7R1H104K050BE | PMID HF, same layer as U501, on top of the IC ([DS] §8.4.1 item 1) |
| C518 | C18 | 0.1 uF X7R | 50 V | 0402 | C1005X7R1H104K050BE | SYS HF ([DS] §8.4.1 item 1) |
| C519-C523 | C19-C23 | 10 uF X5R | 25 V (output side; [DS] §8.2.2.4 asks >= 16 V for 2S) | 0805 | TDK C2012X5R1E106K125AB ([UG]) | SYS bulk, 5 x 10 uF; effective C_SYS >= 6 uF ([DS] §6.3), TODO(verify: DC-bias at 8.8 V) |
| C538, C539 | C38, C39 | 10 uF X5R | 25 V | 0603 | Murata GRT188R61E106ME13D ([UG]) | BAT, 2 x 10 uF; effective C_BAT >= 3 uF ([DS] §6.3) |
| C506, C508 | C6, C8 | 47 nF X7R | 25 V (>= 10 V required, [DS] Table 5-1) | 0402 | Murata GRM155R71E473KA88D ([UG]) | BTST1-SW1, BTST2-SW2 |
| C535 | C35 | 4.7 uF X5R | 16 V (>= 10 V required) | 0603 | Murata GRM188R61C475KAAJD ([UG]) | REGN ([DS] Table 5-1) |
| C536 | C36 (re-wired) | 1.0 nF C0G | 50 V | 0402 | Murata GRM1555C1H102JA01D ([UG]) | SDRV to **GND** ([DS] Table 5-1 rev C) |
| R515 | R15 | 100 Ohm 1 % | - | 0603 | Yageo RC0603FR-07100RL ([UG]) | BATP series ([DS] Table 5-1) |
| R529 | R29 | **6.04 kOhm 1 %** | - | 0603 | TODO(verify: MPN; the EVM BOM lists 6.20 kOhm RC0603FR-076K2L, the EVM schematic and [DS] Table 7-1 give 6.04 kOhm) | PROG 2S / 1.5 MHz |
| R507 + C505 (DNP) | R7 + C5 | 2.0 Ohm + 2.2 nF C0G | 50 V | 0603 | CRCW06032R00JNEA + GRM1885C1H222JA01D ([UG]) | SW1 snubber footprint |
| R510 + C507 (DNP) | R10 + C7 | 2.0 Ohm + 2.2 nF C0G | 50 V | 0603 | as R507/C505 | SW2 snubber footprint |
| R541 + C541 (DNP) | RSNUB1/CSNUB1 (no EVM footprint) | 2.0 Ohm + 2.2 uF | **>= 50 V** (input side) | 1206 / 1210 | TODO(verify) | Input RC snubber footprint (D9) |

#### 2.1.3 Inductor current and frequency (calc, [DS] Eq 4 and Eq 5)

The charger draws power only while VBUS >= VINDPM. The register images set VINDPM to 14.5 V (FC) or 18.2-19.0 V (regen)
([WD] G.1), so charge power always flows in buck mode (VBUS > VSYS). The boost case of [DS] Eq 6 is not reached in
operation: the eFuse UVLO keeps VCHGOUT dark below 9.70 V rising ([WD] B.4), which is above VSYS max 8.82 V (VBAT_OVP
105 % of 8.40 V, [DS] EC p.12). In any boost or buck-boost interval the inductor current equals the input current, which the
ILIM_HIZ clamp bounds at 1.76 A ([WD] H.4); that is below the buck peak.

Table 2.3 gives the buck ripple ([DS] Eq 5) and peak ([DS] Eq 4) at ICHG 3.21 A (the regen image 3.10 A + 3.5 % upper
tolerance, [WD] A.3), VSYS 8.82 V, with the nominal inductance and with -20 % (the "M" tolerance code of the EVM part;
TODO(verify: TDK datasheet)). [DS] EC p.14 gives only the typical fsw; the fsw tolerance is TODO(verify: TI).

| VIN | 1.5 MHz, 1.0 uH: ripple / peak | 1.5 MHz, 0.8 uH: ripple / peak | 750 kHz, 2.2 uH: ripple / peak | 750 kHz, 1.76 uH: ripple / peak |
|---|---|---|---|---|
| 16.0 V (VBUS nominal) | 2.64 / 4.53 A | 3.30 / 4.86 A | 2.40 / 4.41 A | 3.00 / 4.71 A |
| 22.28 V (V-MOT clamp max) | 3.55 / 4.99 A | 4.44 / 5.43 A | 3.23 / 4.83 A | 4.04 / 5.23 A |
| 23.63 V (eFuse OVP max) | 3.69 / 5.05 A | 4.61 / **5.51 A** | 3.35 / 4.89 A | 4.19 / 5.30 A |

- The worst case is 5.51 A. The requirement **Isat >= 6.5 A at the maximum inductor temperature** keeps an 18 % margin
  over the [DS] Eq 4 peak (6.5 / 5.513 = 1.179). The PFM peak (3.3 A with OOA disabled, 2 A with OOA enabled, [DS]
  §7.3.6.4) and the [DS] §8.2.2.2 floor of 2 A are below it.
- Eq 4 covers steady-state operation only. Below VSYS_SHORT (2.1-2.3 V, [DS] EC) the converter limits its output to
  < 1 A ([DS] §7.3.13.1.5). In a fault transient before that limit acts, only the converter cycle-by-cycle limit
  (Q1_OCP/Q4_OCP, [DS] block diagram; CONV_OCP_FLAG, REG26 bit 2) bounds the inductor current. [DS] does not publish
  that threshold. TODO(verify: TI, O-4).
- IBUS_OCP (7.0-9.0 A, [DS] EC) is an input current. In buck mode the average inductor current is I_IN / D, so the
  threshold corresponds to >= 11.5 A of inductor current at VBUS 14.5 V (D = 0.608). IBAT_OCP (9.3 A, [DS] §7.3.13.1.7)
  acts only with a ship FET fitted (omitted, D6), and its discharge current does not flow through L501. Neither
  threshold bounds the L501 current.
- **Saturation criterion.** L501 qualifies when the vendor L-versus-I curve at the maximum inductor temperature gives
  L >= 0.70 uH at 6.5 A at the -20 % tolerance limit. On a 1.0 uH typical curve, this is an inductance drop <= 12.5 % at
  6.5 A. Eq 4 at 0.70 uH gives 5.84 A, so the operating range stays above 0.70 uH with an 11 % margin (6.5 / 5.842).
  A bare "Isat 6.5 A at -30 %" rating is not sufficient: at the -20 % limit the part has 0.56 uH at 6.5 A, and Eq 4
  at 0.56 uH gives 6.50 A, which leaves no margin. The 750 kHz alternate uses the same rule scaled by 2.2: L >= 1.54 uH
  at 6.5 A (Eq 4 peak 5.60 A) ([CALC], section "L501 current requirement").
- Until O-4 closes, L501 is restricted to the EVM part SPM6530T-1R0M120. A substitute part also requires
  Isat >= the confirmed cycle-by-cycle limit at its maximum temperature. Whether SPM6530T-1R0M120 meets the saturation
  criterion is TODO(verify: TDK datasheet L-I curve at T_max) (O-2). The 750 kHz part has the same restriction
  (TODO(verify)).
- [DS] §6.3 lists ISW 5 A ("Output current (SW)"). Whether it is a DC or a peak figure is not stated; the 5.51 A worst-case
  peak exceeds it while the DC value 3.21 A does not. TODO(verify: TI E2E, meaning of ISW in [DS] §6.3). TI's own design example
  is 2S, 3.0 A, VBUS to 20 V at 1.5 MHz with 1 uH ([DS] Table 8-1), so the operating point is inside TI's intent.
- 750 kHz lowers the peak by only 0.2 A, because the inductance rises by 2.2 x while the frequency halves. Its benefit is
  lower switching loss near the hot LM1084. **1.5 MHz is the baseline**; 750 kHz is a BOM alternate (R529 8.2 kOhm, L501
  2.2 uH) if the thermal test T-B-16 fails. The 2.2 uH part and its footprint fit are TODO(verify: candidate datasheet).
- The inductor RMS current is about ICHG (3.21 A) plus a small ripple term; its heating rating must exceed 4 A.
  TODO(verify: TDK SPM6530T heating-current rating).

#### 2.1.4 The 35 V rule on the input side (IC-independent rule, part check S/I)

Table 2.4 checks every part that sees the input voltage.

| Node | Parts | Rating | Pass? |
|---|---|---|---|
| VCHGIN (upstream of the eFuse) | U301 IN/IN_SYS | 60 V part, IN abs max 67 V ([WD] B.4, SLVSE94G §6.1) | yes |
| VCHGIN | C302a / C302b / C302c | 100 V / 100 V / 100 V ([WD] B.4) | yes |
| VCHGIN | D307 TVS | VRWM >= 30 V, VBR(min) >= 36 V ([WD] B.4) | yes (clamp device) |
| VCHGIN | R302 845 kOhm 0805 | TODO(verify: Vishay TNPW0805 limiting element voltage) | TODO |
| VCHGOUT | C303 | 50 V ([WD] E) | yes |
| VCHGOUT | D303 Schottky | >= 40 V ([WD] B.4) | yes |
| VCHGOUT | C511, C512, C513, C514, C541 | 50 V | yes |
| VCHGOUT | U501 VBUS, VAC1, VAC2 | 30 V abs max ([DS] §6.1) | IC pins are 30 V parts; protected by the eFuse OVP <= 23.63 V |
| PMID | C529-C531 (10 uF bulk), C532 (0.1 uF HF) | 50 V (Table 2.2); node maximum 23.63 V (eFuse OVP; PMID follows VBUS through the internal RBFET) | yes |
| PMID / SW1 | U501 PMID, SW1 | 30 V abs max | as above |
| BTST1 | C506 | sees BTST1-SW1 <= 6 V ([DS] §6.1); rated 25 V | yes |
| ACDRV1/2 | tied to GND | - | n/a |
| T1_VMOT (F01), T2C (F03) | R309 487 kOhm, R311 442 kOhm, R314 1.00 MOhm (0.1 % 0805 divider tops behind MB R170/R171 10.0 kOhm); each sees up to the V-MOT clamp 22.28 V | TODO(verify: Vishay TNPW0805 limiting element voltage) | TODO; the divided nodes (N_H1P, N_H1M, N_UVP) are clamped to 3V3 by D304-D306 |
| VCHGIN | H301 pad 10 header pin (and the option-K socket contact) | TODO(verify: Samtec TSW / socket rated voltage) | TODO |

Note that the IC itself cannot meet a 35 V rule. The rule is met by the external parts, and the IC is protected by the eFuse
OVP and by the round-3 TVS D307. A V-MOT excursion above the eFuse OVP opens the eFuse ([WD] B.4).

### 2.2 Charger control pins (BQ25798-specific)

#### 2.2.1 Pin decisions

Table 2.5 states how each BQ25798 control pin is wired.

| Pin | Wiring | Parts | Reason |
|---|---|---|---|
| ILIM_HIZ (17) | Round-3 network, all on board: R523 49.9 kOhm and R456 200 kOhm + C452 2.2 nF C0G to quiet GND; hold Q401 (on by default); FC leg Q402 + R457 59.0 kOhm (on by default); release feed Q403 + R455 48.7 kOhm from REGN (off by default); sense U403 through its own trace from the pin pad | Q401-Q403, R452, R454, R455, R456, R457, R471, R523, C452, U403, R458-R461 | Same values as [WD] B.6 and EM4/EM5, so the H.4 levels carry over: regen clamp 1.33-1.76 A, FC clamp 0.65-0.95 A, held <= 0.11 V. TODO(calc: re-run r3_calc H.4 with the CCB leakage list) |
| /CE (13) | Open-drain U401 ch1 sinks /CE; two independent pull-ups R472, R472b 47.0 kOhm to REGN; sense U404 through R462/R463 | U401, R472, R472b, U404, R462, R463 | /CE "must be pulled HIGH or LOW, do not leave floating" ([DS] Table 5-1); two pull-ups keep /CE HIGH with either one open ([WD] EM2, H.19) |
| STAT (1) | R475 1.00 kOhm in series to net STAT; R307 10.0 kOhm to 3V3; header pin 3 to Teensy 6 | R475, R307 | STAT abs max 6 V, 6 mA sink ([DS] §6.1). R475 is re-justified: if Teensy pin 6 is ever driven HIGH by a firmware fault, the STAT sink is held to 3.3 mA ([CALC]). STAT LOW reads 0.31 V at pin 6 ([WD] H.21) |
| /INT (21) | Test pad TP508; R521 10.0 kOhm to 3V3 **DNP** | R521 | No Teensy pin is free for /INT: the only spare pins are 2 and 8, both on encoder nets ([WD] A.4). An open-drain output may stay open. If /INT is ever used, its pull-up goes to 3V3, never to REGN ([DS] §7.3.4.1; [WD] EM15) |
| /QON (12) | Test pad TP509 only | - | Internal pull-up RQON ([DS] EC p.16). A LOW for tRST (10 s typ) resets system power ([DS] §7.3.12); no ship FET is fitted, so the pin has no function here |
| PG | none | - | The BQ25798 has no PG pin ([DS] Table 4-1); power-good is PG_STAT over I2C, used by FR-23 ([WD] G.2) |
| SCL (14), SDA (15) | Direct copper to header pins 7 and 8 | R345, R346 footprints **DNP** | The MB RSDA/RSCL 2.7 kOhm to the Teensy 3V3 (PM9) are the only pull-ups, so the board rail is never fed through I2C ([WD] A.2, EM6). VIH 1.3 V min ([DS] EC p.15) |
| TS (16) | R518 5.23 kOhm REGN-TS, R524 30.1 kOhm TS-GND; **either** R525 10.0 kOhm TS-GND (NTC simulator, no pack NTC) **or** R526 0 Ohm TS -> TS_EXT -> header pin 13 -> J-NTC (pack NTC fitted). Never both | R518, R524, R525, R526 | EVM values ([UG] Table 4-1; [DS] p.46 gives 5.24/30.31 kOhm). The choice follows T-E-09 ([WD] EM18). A missing thermistor disables charging ([DS] §7.3.6 item 1); TS_IGNORE is never relied on ([WD] EM18). TODO(verify: the NTC type at J-NTC, 103AT-class assumed) |
| PROG (20) | R529 6.04 kOhm 1 % to quiet GND | R529 | 2S, 1.5 MHz ([DS] Table 7-1). The PROG detection window is not published, TODO(verify: TI) |
| D+ (6), D- (7) | Unconnected; R506 0 Ohm D+ to D- footprint **DNP** | R506 | No USB input. REG11 = 0x00 (AUTO_INDET_EN 0) is written before detection starts ([WD] G.1). TODO(verify: SLUSDV2C §7.3.4.5 / TI E2E on unused D+/D- handling) |
| SDRV (24) | C536 1 nF 50 V C0G to GND | C536 | D6 |
| BATP (18) | R515 100 Ohm to BAT | R515 | D8 |
| ACDRV1 (11), ACDRV2 (10) | GND | - | D1 |
| VAC1 (9), VAC2 (8) | VCHGOUT, C514 | C514 | D1 |
| REGN (5) | C535 4.7 uF; loads R518 (TS), R452/R454/R471 (gate pull-ups), R472/R472b (/CE), Q403 + R455 (release feed) | - | [DS] §7.3.4.1 does not recommend REGN for loads other than ILIM_HIZ, TS and STAT pull-ups. The round-3 design already uses REGN for the /CE and gate pull-ups ([WD] B.6, H.15); the total is below 1 mA against the >= 30 mA REGN limit ([DS] EC p.15). This deviation is inherited and recorded (open item O-6, §8.3.1) |

#### 2.2.2 Layout rules that replace EVM modifications (BQ25798-specific)

1. **No part has one terminal on REGN and the other on ILIM_HIZ.** The only REGN-to-ILIM_HIZ path is Q403 + R455
   (replaces EM3: R21, R20, JP13, JP14 have no footprint).
2. **No part has one terminal on /CE and the other on GND,** except U401 1Y and the 2 MOhm sense chain R462 + R463
   (replaces EM1: JP17 has no footprint). The DNP C453 sits at the chain midpoint, not on /CE. A shorted C453 leaves /CE
   at 0.977 x REGN through R462 and makes CE_SENSE read LOW; FR-08(b) reports this while P5 is LOW.
3. R472 and R472b use separate pads and separate vias to REGN (replaces the two links L1/L2 of EM2).
4. The U403 sense trace (via R458) leaves the U501 pin-17 pad on its own trace; the U404 sense trace (via R462) leaves the
   pin-13 pad on its own trace. A cracked driver trace then shows at the sense ([WD] A.5 "separate joint" rule).
5. The ground terminals of R523, R456, C452, R524, R525, R529 and the U403/U404 dividers connect to the plane away from the
   power-return paths ([UG] §3 item 7).
6. BATP and TS route away from SW1 and SW2 ([DS] §8.4.1 item 7).

### 2.3 EIB stages on the single board

#### 2.3.1 Principle

The rule is: delete only what existed to compensate for the 0.30 m leads, the ribbon or the EVM; keep every part that
serves single-fault safety. Table 2.6 gives the verdict for every EIB part ([WD] B.6, B.8).

| EIB part | New ref | Verdict | Reason |
|---|---|---|---|
| U201 SN74LVC3G06 (ch1 /CE, ch2 Q203 gate, ch3 Q202 gate) | U401 | **Kept, now a local driver** | Open drain is required: the driven nodes are referenced to REGN (up to 5.2 V, [DS] EC p.15), above the 3.3 V logic rail. Outputs float when unpowered, which gives /CE HIGH, Q403 off and Q402 on (the fail-safe set) |
| U202 SN74LVC1G06 (Q201 gate) | U402 | **Kept** | A separate driver for the hold-down switch, so one stuck driver output cannot both feed and un-hold ILIM_HIZ |
| Q203 BSS84 (release feed) + R255 48.7 kOhm | Q403 + R455 | **Kept** | Two-switch release (feed and hold): a Q403 short is held by Q401, a Q401 open is held by Q403 off ([WD] B.6 single-fault table) |
| R271 47 kOhm (Q203 gate-source) | R471 | Kept | Q403 off by default |
| Q201 2N7002K (hold) + R252 47 kOhm | Q401 + R452 | **Kept** | Holds ILIM_HIZ < 0.75 V (converter off, REGN on) unless released ([DS] §7.3.4.3) |
| Q202 2N7002K (FC leg) + R254 47 kOhm + R257 59.0 kOhm | Q402 + R454 + R457 | **Kept** | Hardware FC clamp 0.65-0.95 A ([WD] H.4), on by default |
| U203 TLV3012B ILIM sense + R258-R261 | U403 + R458-R461 | **Kept, simplified role** (pin sense, no longer far-end) | A direct Teensy read cannot replace it: the sense must prove the pin is below VIL_ILIM_HIZ 0.75 V ([DS] EC p.16) with a 0.587-0.650 V threshold ([WD] B.6); a GPIO input threshold (i.MX VIL 0.99 V, [WD] H.21) does not prove that |
| U204 TLV3012B /CE sense + R262/R263 | U404 + R462/R463 | **Kept, simplified role** | /CE swings to REGN (up to 5.2 V); a Teensy 4.1 pad is a 3.3 V input, TODO(verify: i.MX RT1060 datasheet absolute maximum). The 2.5 V threshold and the "dead source reads /CE LOW" property feed FR-08(b) unchanged |
| R264, R265 470 Ohm (sense output series) | - | **Deleted** | They limited a ribbon conductor short to GND to 6.7 mA ([WD] B.6, r4). The outputs now reach the taps F13/F20 through R325/R348 1.00 kOhm alone: a tap-wire short to GND then draws 3.3 mA, inside the TLV3012B 10 mA output-short absolute maximum (SBOS300C §6.2, as cited in [WD] B.6) |
| R250, R251, R253, R266 1 kOhm (driver input series) | - | **Deleted** | Input damping for ribbon conductors ([WD] B.6); on-board traces need none. SN74LVC inputs see CMOS edges from U314/U306 ([WD] B.3) |
| R267-R270 47 kOhm (driver input pull-downs) | R467-R470 | **Kept, re-justified** | Each sits at its receiver input pin. On the testbench, handling, repeated insertion and thermal cycling make a cracked trace or joint credible (the r1 basis was a moving vehicle); an open input then reads LOW, which is the safe state ([WD] B.6 table). R468 (U401 pin 3) and R470 (U402 pin 2) protect the two ILIM_REL branches separately |
| R272, R272b 47.0 kOhm (/CE pull-ups to REGN, on the EVM) | R472, R472b | **Kept** | Single-fault tolerance of the inhibit ([WD] EM2, H.19). The links L1/L2 disappear; separate pads and vias replace them (§2.2.2 rule 3) |
| R256 200 kOhm + C252 2.2 nF C0G (on the EVM) | R456 + C452 | **Kept** | R523-open guard (<= 0.57 V) and release-glitch filter ([WD] EM5, H.13) |
| R273 10 Ohm (ribbon GND to EIB AGND) | - | **Deleted** | Single DC ground link of a separate board ([WD] A.6). The CCB has one ground plane |
| R274 10 kOhm (3V3 bleed) | R474 | **Kept, re-justified** | The merged rail still has the BAV199 back-feed path from the live H1/UVB dividers (<= ~50 uA). [WD] B.7 holds the rail at 0.3-0.45 V across R274, below every logic minimum; without a bleed the rail could float higher |
| R275 1.00 kOhm (STAT series) | R475 | **Kept, re-justified** | The ribbon 4-5 short is gone, but a Teensy pin-6 misconfiguration (OUTPUT HIGH) is a credible firmware fault; R475 holds the STAT sink to 3.3 mA against the 6 mA absolute maximum |
| C201-C204 100 nF | C401-C404 | Kept | VCC decoupling |
| C205 100 nF (REGN at the Q203 source) | - | **Deleted** | REGN is decoupled by C535 4.7 uF within millimetres; the 0.30 m E1 lead no longer exists |
| J201 header, W5 ribbon, E1-E8 leads, R176/R177 (ribbon 3V3 feed) | - | **Deleted** | Inter-board wiring |
| EVM R23 (49.9 kOhm after EM4) | R523 | Kept | ILIM_HIZ bottom resistor |

#### 2.3.2 Single-fault coverage after the merge (IC-independent statement, S implementation)

All B.6 single-fault rows that concern parts (Q401-Q403, U401-U404, R472/R472b, R523) keep their outcome and their
detection, because topology and values are unchanged. The rows that concerned leads E2-E6, the ribbon conductors and the
EVM jumpers no longer apply. Two new fault classes arise:

1. A cracked on-board trace between a driver and its receiver input reads LOW at the receiver through R467-R470, so it
   fails safe.
2. A solder bridge between adjacent U501 pins is credible, because the RQM package has hidden joints at 0.4 mm pitch
   (§4.4.3; N-03). On the EVM this risk sat with the factory build. Table 2.6b gives the safety-relevant pairs, from the
   pin order of [DS] Fig 5-1 and the absolute maxima of [DS] §6.1.

Table 2.6b gives the outcome and the detection of each safety-relevant bridge. The networks are those of Table 2.5. The
figures come from the Table 2.5 values: R523 parallel R456 = 39.94 kOhm; the TS Thevenin source is R518 parallel
(R524 parallel R525) = 3.08 kOhm at 0.589 x REGN (option B); REGN 4.6-5.2 V ([DS] EC).

**Table 2.6b. Solder bridges between adjacent U501 pins.**

| Pins | Nets | Outcome | Detection |
|---|---|---|---|
| 17-18 | ILIM_HIZ - BATP | With REGN off, BATP (VBAT through R515 100 Ohm) puts 0.9975 x VBAT = 7.38-8.38 V on ILIM_HIZ, above its 6 V absolute maximum. With REGN on and Q401 holding, 74-84 mA flows through R515, which dissipates 0.55-0.71 W in an 0603 and opens; BATP then floats onto the ILIM_HIZ network. The U403 sense still reads "held" | No interlock or firmware detection. Pre-power resistance only (T-K-06 step 1). Without that step, the first battery connection (T-K-06 step 2) is the first exposure |
| 16-17 | TS - ILIM_HIZ | Held: TS is pulled to about 0 V, a TS hot fault, and charging is suspended. Released (Q402 and Q403 on): ILIM_HIZ sits at 2.52-2.85 V, an IINDPM clamp of 1.90-2.31 A; the FC clamp (0.65-0.95 A) and the regen clamp (1.33-1.76 A) are lost | [WD] I-3 reads REG19 ICO_ILIM before P5 rises in each charger power cycle; 1.90-2.31 A is outside both bands, so T1 refuses to arm (FR-30). Pre-power resistance (T-K-06 step 1) |
| 18-19 | BATP - BTST2 | The bootstrap node is tied to a DC source. BTST2-SW2 leaves its -0.3 to 6 V range ([DS] §6.1) whenever SW2 departs from VBAT; the high-side drive of Q4 fails, and power-stage damage is possible | Pre-power resistance only (T-K-06 step 1) |
| 4-5 | BTST1 - REGN | The bootstrap node is tied to REGN. When SW1 rises to VBUS (up to 23.63 V), BTST1-SW1 falls far below -0.3 V; power-stage damage is possible | Pre-power resistance only (T-K-06 step 1) |
| 1-2 | STAT - VBUS | The STAT pin sits at VCHGOUT (<= 23.63 V) against its 6 V absolute maximum. About 20 mA flows into Teensy pin 6 through R475 (0.40 W at 23.63 V; 12.4 mA, 0.15 W at 16 V), assuming a 3.6 V pad clamp. Teensy pad damage is a hypothesis, TODO(verify: i.MX RT1062 injection limit) | Pre-power resistance (T-K-06 step 1); the input current of T-K-06 step 3 |
| 12-13 | /QON - /CE | When U401 sinks /CE for longer than tRST (10 s typ, [DS] §7.3.12), /QON resets system power and the charger enters HIZ. This is the safe direction | The "Charger POR" row of Table 2.8; pre-power resistance (T-K-06 step 1) |
| 13-14 | /CE - SCL | Idle: the node sits at 3.43-3.50 V (MB 2.7 kOhm to 3V3 against 23.5 kOhm to REGN at 4.6-5.2 V), so /CE reads HIGH. While U401 sinks /CE, SCL is held LOW and I2C is lost (FR-23 class). SCL clocks pulse /CE LOW | U404 reads LOW while P5 is LOW: FR-08(b). Pre-power resistance (T-K-06 step 1) |

A bridge forms at assembly, so Table 2.6b is mainly a bring-up gate. For that reason, T-K-06 step (1) measures every pair
of Table 2.6b before any source is connected. In addition, §4.4.3 makes U501 joint inspection a gate for both assembly
options.

### 2.4 EVM modifications on the CCB

#### 2.4.1 Count

The study lists 11 EVM modifications, [EVAL] §4.2 M1-M11. The round-3 design supersedes them with EM1-EM25
([WD] C). Table 2.7 covers EM1-EM25 and gives the [EVAL] M-number in its second column.

#### 2.4.2 Disposition

| EM | [EVAL] M | EVM change | Custom board | Class |
|---|---|---|---|---|
| EM1 | M1 | JP17 shunt and pin 2 removed (/CE no longer grounded) | **Disappears.** No JP17 footprint; §2.2.2 rule 2 | S |
| EM2 | M2, M2b | R42 removed; R272/R272b 47.0 kOhm to REGN | **BOM choice:** R472 and R472b 47.0 kOhm to REGN; no PULLUP rail | S |
| EM3 | M3 | R21 -> 0 Ohm, JP14 and JP13 pin 1 and R20 removed; release only through Q203 + R255 | **Disappears.** No R21, R20, JP13, JP14 footprints; §2.2.2 rule 1 | S |
| EM4 | M3 | R23 100 kOhm -> 49.9 kOhm | **BOM choice:** R523 49.9 kOhm 1 % | S |
| EM5 | - | R256 200 kOhm + C252 2.2 nF across JP21 | **BOM choice:** R456 + C452 at the ILIM_HIZ pin to quiet GND | S |
| EM6 | M4 | R39/R40 I2C pull-ups removed | **BOM choice:** R345/R346 DNP; no other I2C pull-up | I |
| EM7 | M5 | J2/J3/J4 terminals removed or capped | **Disappears.** No terminals; SYS reached only by the TP510 probe pad | S |
| EM8 | M4 | JP32 (STAT LED) removed | **Disappears.** STAT via R475 to the STAT net, R307 to 3V3 | S |
| EM9 | M6 | JP9 2-3 (BATP at the BAT pin) | **BOM choice:** R515 100 Ohm to the BAT pins | S |
| EM10 | M5 | JP1/JP2 2-3 (ACDRV to GND) | **Disappears** into copper: ACDRV1/2 tied to GND | S |
| EM11 | M5 | JP3 soldered link (input current), JP4 shunt (VAC2) | **Disappears** into copper: VAC1/VAC2 on VCHGOUT; the input path is a pour rated >= 2.41 A | S |
| EM12 | M6 | JP5 soldered link (BAT to BATTERY, ship FET bypassed) | **Disappears.** No ship FET, no R13 shunt; BAT pins to the VCHG pour | S |
| EM13 | M6 | JP8 1-2 (SDRV through 1 nF to BAT) | **BOM choice, corrected:** C536 1 nF 50 V 0402 SDRV to **GND** ([DS] rev C). Flag to the round-3 owner: EM13 follows the deleted option | S |
| EM14 | M7 | C11/C12/C29-C31 -> 10 uF >= 35 V | **BOM choice:** C511, C512, C529-C531 10 uF 50 V X7R | S |
| EM15 | - | JP30 removed (PULLUP LDO U2 off) | **Disappears.** No U2, D11/D12, C43/C44, R35/R36 | S |
| EM16 | M11 | JP6/JP10/JP11 removed (no D+/D-) | **Disappears;** D+/D- unconnected, R506 DNP; REG11 0x00 | S |
| EM17 | - | JP7 removed (USB VBUS) | **Disappears.** No USB connector | S |
| EM18 | M9 | JP18 kept, or J7 wired if a pack NTC is fitted | **BOM choice by T-E-09:** R525 10.0 kOhm fitted XOR R526 0 Ohm fitted | S |
| EM19 | M10 | JP24 kept (2S, 1.5 MHz) | **BOM choice:** R529 6.04 kOhm 1 %; no other PROG resistor | S |
| EM20 | - | JP31/JP33 open | **Disappears** | S |
| EM21 | - | RSNUB1/CSNUB1 not fitted | **BOM choice:** R541/C541 footprint DNP | S |
| EM22 | - | S1 (QON) not pressed | **Disappears.** /QON to TP509 only | S |
| EM23 | - | Bumpons removed; nylon standoffs | **Disappears.** Mounting by the header and support feet (layout section) | I |
| EM24 | - | No input capacitor added (ceramic only, 50.4 uF nominal) | **Rule kept:** VCHGOUT is ceramic only, 51.3 uF nominal; no electrolytic (Death-5 class) | I |
| EM25 | - | Bring-up: confirm TP41 (PULLUP) dark | **Replaced:** confirm REGN (TP503) < 0.1 V with VCHG-IN off and no D-BT-SQ short | S |
| - | M8 | 1.0 kOhm VBT -> VCHG keep-alive proposal | Superseded by the round-3 keep-alive option B.5, carried as U312/D301/R392 DNP | I |

### 2.5 Pin-level netlist

#### 2.5.1 Format and pin sources

The format follows [WD] B.8: each row lists "pin number pin name -> net". Pin tables: BQ25798 RQM ([DS] Table 5-1);
TPS26630 RGE ([WD] B.8, SLVSE94G Table 5-1); TLV3012 DBV (1 OUT, 2 V-, 3 IN+, 4 IN-, 5 REF, 6 V+); SN74LVC3G04/3G06 DCT
(1 1A, 2 3Y, 3 2A, 4 GND, 5 2Y, 6 3A, 7 1Y, 8 VCC); SN74LVC2G32/2G08 DCT (1 1A, 2 1B, 3 2Y, 4 GND, 5 2A, 6 2B, 7 1Y, 8 VCC);
SN74LVC1G11 DCK (1 A, 2 GND, 3 B, 4 Y, 5 VCC, 6 C); SN74LVC1G123 DCT (1 A, 2 B, 3 CLR, 4 GND, 5 Q, 6 Cext, 7 Rext/Cext, 8 VCC);
SN74LVC1G06 DCK (1 NC, 2 A, 3 GND, 4 Y, 5 VCC); SN74LVC1G08 DCK (1 A, 2 B, 3 GND, 4 Y, 5 VCC); SN74LVC1G14 DCK (1 NC, 2 A,
3 GND, 4 Y, 5 VCC); TPS22810 DBV (1 VIN, 2 GND, 3 EN/UVLO, 4 CT, 5 QOD, 6 VOUT); all as quoted in [WD] B.8.
Unverified pinnings carried from [WD] B.8: SOT-23 MOSFETs 1 G, 2 S, 3 D (TODO(verify: chosen MPN datasheet)); BAV199 1 =
lower-diode anode (GND), 2 = upper-diode cathode (3V3), 3 = common node (TODO(verify: Nexperia BAV199 datasheet)).
The BQ25798 land pattern has 29 pads for 29 pins; pins 1, 9, 16 and 24 are L-shaped, so the drawing counts 33 lead
segments ([DS] pp.148-149). Table 3.8c of §3.4.6 gives the pad-to-pin map. Two-terminal parts are written "1 -> net; 2 -> net".

#### 2.5.2 Header H301 (IC-independent)

H301 is the AG105 footprint copied from the imported `.brd` (PM0 rule, [WD] D.1), fitted with Samtec TSW-110-07-G-S (pads
1-10) and TSW-112-07-G-S (pads 11-22) ([WD] E). MB nets from [MECH] §1.

| Pad | Ag105 name | MB net | Board net | Function |
|---|---|---|---|---|
| 1, 2, 5, 6, 9, 12, 16, 17, 20, 21, 22 | VSEL, CSEL, NC1, NC2, NC3, MPPTSEL, VLOAD-1, VLOAD-2, LDIS, VLOAD+1, VLOAD+2 | none | none (isolated pad) | Mechanical anchors, soldered |
| 3 | STAT | CHRG-STAT (Teensy 6) | `STAT` | Charger status |
| 4 | VIN- | GND | `GND` | Input return |
| 7 | SCL | SCL (Teensy 19, RSCL) | `SCL` | I2C |
| 8 | SDA | SDA (Teensy 18, RSDA) | `SDA` | I2C |
| 10 | VIN+ | VCHG-IN | `VCHGIN` | Charger input (the only input path) |
| 11 | MPPTD | MPPT-DISABLE (Teensy 5) | `CHG_ARM` | P5 |
| 13 | THERM | N$34 (J-NTC pin 1) | `TS_EXT` | Pack NTC, only if fitted |
| 14, 15 | VBAT-1, VBAT-2 | GND | `GND` | Battery return |
| 18, 19 | VBAT+1, VBAT+2 | VCHG (C-D11, D-BT-SQ VIN) | `VCHG` | Charger output to the pack path |

#### 2.5.3 Input protection (IC-independent; replaces CR U101 network)

| Ref | Part / value | Pins -> nets | Was |
|---|---|---|---|
| U301 | TPS26630RGER | 1 IN, 2 IN -> VCHGIN; 3 B_GATE nc; 4 DRV nc; 5 IN_SYS -> VCHGIN; 6 UVLO -> N_UV; 7 OVP -> N_OV; 8 GND -> GND; 9 dVdT -> N_DVDT; 10 ILIM -> N_ILIMF; 11 MODE nc; 12 SHDN nc; 13 IMON -> N_IMON; 14 FLT -> CHG_EFUSE_FLT; 15 PGTH -> GND; 16 PGOOD -> GND; 17 OUT, 18 OUT -> VCHGOUT; 19-24 N.C. nc; PAD -> GND (>= 9 vias) | U101 |
| R301 | 8.06 kOhm 1 % 0402 | 1 -> N_ILIMF; 2 -> GND | R101 |
| C301 | 22 nF 50 V X7R 0402 | 1 -> N_DVDT; 2 -> GND | C101 |
| R302 | 845 kOhm 0.1 % 0805 | 1 -> VCHGIN (at IN_SYS); 2 -> N_UV | R102 |
| R303 | 66.5 kOhm 0.1 % 0402 | 1 -> N_UV; 2 -> N_OV | R103 |
| R304 | 49.9 kOhm 0.1 % 0402 | 1 -> N_OV; 2 -> GND | R104 |
| C302a | 1.0 uF 100 V X7R 1206 | 1 -> VCHGIN; 2 -> GND | C102a |
| C302b | 4.7 uF 100 V X7R/X7S 1210 | 1 -> VCHGIN; 2 -> GND | C102b |
| C302c | 100 nF 100 V X7R 0603 | 1 -> VCHGIN; 2 -> GND | C102c |
| D307 | TVS SMAJ33A class, SMA | K -> VCHGIN; A -> GND | D107 |
| C303 | 1.0 uF 50 V X7R 0805 | 1 -> VCHGOUT; 2 -> GND | C103 |
| D303 | Schottky >= 40 V, SMA | K -> VCHGOUT; A -> GND | D103 |
| R305 | 27.4 kOhm 1 % 0402 | 1 -> N_IMON; 2 -> GND | R105 |
| C305 | DNP (footprint) | 1 -> N_IMON; 2 -> GND | C105 |
| R329 | 10.0 kOhm 1 % 0603 | 1 -> N_IMON; 2 -> CHG_IIN | R129 |
| C329 | 1.0 nF 50 V C0G 0603 | 1 -> CHG_IIN; 2 -> GND | C129 |
| R306 | DNP (footprint) | 1 -> CHG_EFUSE_FLT; 2 -> 3V3 | R106 |

#### 2.5.4 Power stage (BQ25798-specific; replaces the EVM)

| Ref | Part / value | Pins -> nets | Was (EVM) |
|---|---|---|---|
| U501 | BQ25798RQMR | 1 STAT -> STAT_IC; 2 VBUS, 3 VBUS -> VCHGOUT; 4 BTST1 -> N_BTST1; 5 REGN -> REGN; 6 D+ -> N_DP; 7 D- -> N_DM; 8 VAC2 -> VCHGOUT; 9 VAC1 -> VCHGOUT; 10 ACDRV2 -> GND; 11 ACDRV1 -> GND; 12 /QON -> NQON; 13 /CE -> NCE; 14 SCL -> SCL; 15 SDA -> SDA; 16 TS -> TS; 17 ILIM_HIZ -> ILIM_HIZ; 18 BATP -> N_BATP; 19 BTST2 -> N_BTST2; 20 PROG -> N_PROG; 21 /INT -> NINT; 22 BAT, 23 BAT -> VCHG; 24 SDRV -> N_SDRV; 25 SYS -> CHG_SYS; 26 SW2 -> SW2; 27 GND -> GND; 28 SW1 -> SW1; 29 PMID -> PMID | U1 |
| L501 | 1.0 uH, Isat >= 6.5 A (criterion §2.1.3) | 1 -> SW1; 2 -> SW2 | L2 |
| C506 | 47 nF 25 V X7R 0402 | 1 -> N_BTST1; 2 -> SW1 | C6 |
| C508 | 47 nF 25 V X7R 0402 | 1 -> N_BTST2; 2 -> SW2 | C8 |
| C511, C512 | 10 uF 50 V X7R 1210 | 1 -> VCHGOUT; 2 -> GND | C11, C12 |
| C513 | 0.1 uF 50 V X7R 0402 | 1 -> VCHGOUT (pins 2/3); 2 -> GND | C13 |
| C514 | 0.1 uF 50 V X7R 0402 | 1 -> VCHGOUT (pins 8/9); 2 -> GND | C14, C15 |
| C529, C530, C531 | 10 uF 50 V X7R 1210 | 1 -> PMID; 2 -> GND | C29-C31 |
| C532 | 0.1 uF 50 V X7R 0402 | 1 -> PMID; 2 -> GND | C32 |
| C518 | 0.1 uF 50 V X7R 0402 | 1 -> CHG_SYS; 2 -> GND | C18 |
| C519-C523 | 10 uF 25 V X5R 0805 | 1 -> CHG_SYS; 2 -> GND | C19-C23 |
| C538, C539 | 10 uF 25 V X5R 0603 | 1 -> VCHG (at pins 22/23); 2 -> GND | C38, C39 |
| C535 | 4.7 uF 16 V X5R 0603 | 1 -> REGN; 2 -> GND (>= 2 vias, [DS] §8.4.1 item 3) | C35 |
| C536 | 1.0 nF 50 V C0G 0402 | 1 -> N_SDRV; 2 -> GND | C36 (far side was BAT) |
| R515 | 100 Ohm 1 % 0603 | 1 -> N_BATP; 2 -> VCHG (at pins 22/23) | R15 |
| R529 | 6.04 kOhm 1 % 0603 | 1 -> N_PROG; 2 -> GND (quiet) | R29 |
| R506 | 0 Ohm 0402, DNP | 1 -> N_DP; 2 -> N_DM | - (new) |
| R507, C505 | 2.0 Ohm / 2.2 nF, DNP | R507 1 -> SW1, 2 -> N_SN1; C505 1 -> N_SN1, 2 -> GND | R7, C5 |
| R510, C507 | 2.0 Ohm / 2.2 nF, DNP | R510 1 -> SW2, 2 -> N_SN2; C507 1 -> N_SN2, 2 -> GND | R10, C7 |
| R541, C541 | 2.0 Ohm / 2.2 uF >= 50 V, DNP | R541 1 -> VCHGOUT, 2 -> N_SNIN; C541 1 -> N_SNIN, 2 -> GND | RSNUB1, CSNUB1 |

#### 2.5.5 Charger control-pin network (BQ25798-specific; replaces EIB + EVM ILIM/TS/CE parts)

| Ref | Part / value | Pins -> nets | Was |
|---|---|---|---|
| R518 | 5.23 kOhm 1 % 0402 | 1 -> REGN; 2 -> TS | EVM R18 |
| R524 | 30.1 kOhm 1 % 0402 | 1 -> TS; 2 -> GND (quiet) | EVM R24 |
| R525 | 10.0 kOhm 1 % 0402 (fit only if no pack NTC, T-E-09) | 1 -> TS; 2 -> GND (quiet) | EVM R25 via JP18 (TODO(verify: SLUUCB5E Fig 4-6 jumper-to-resistor mapping)) |
| R526 | 0 Ohm 0603 (fit only if a pack NTC is fitted; never with R525) | 1 -> TS; 2 -> TS_EXT | EVM J7 / lead W6 |
| R523 | 49.9 kOhm 1 % 0603 | 1 -> ILIM_HIZ; 2 -> GND (quiet) | EVM R23 (EM4) |
| R456 | 200 kOhm 1 % 0603 | 1 -> ILIM_HIZ; 2 -> GND (quiet) | R256 (EM5) |
| C452 | 2.2 nF 50 V C0G 0603 | 1 -> ILIM_HIZ; 2 -> GND (quiet) | C252 (EM5) |
| Q401 | 2N7002KT1G | 1 G -> Q401_G; 2 S -> GND; 3 D -> ILIM_HIZ | Q201 |
| R452 | 47.0 kOhm 1 % 0603 | 1 -> Q401_G; 2 -> REGN | R252 |
| Q402 | 2N7002KT1G | 1 G -> Q402_G; 2 S -> GND; 3 D -> N_FCLEG | Q202 |
| R457 | 59.0 kOhm 1 % 0603 | 1 -> N_FCLEG; 2 -> ILIM_HIZ | R257 |
| R454 | 47.0 kOhm 1 % 0603 | 1 -> Q402_G; 2 -> REGN | R254 |
| Q403 | BSS84LT1G | 1 G -> Q403_G; 2 S -> REGN; 3 D -> ILIM_FEED | Q203 |
| R471 | 47.0 kOhm 1 % 0603 | 1 -> Q403_G; 2 -> REGN | R271 |
| R455 | 48.7 kOhm 1 % 0603 | 1 -> ILIM_FEED; 2 -> ILIM_HIZ | R255 |
| U401 | SN74LVC3G06DCTR | 1 1A <- CE_DRV; 2 3Y -> Q402_G; 3 2A <- ILIM_REL; 4 GND -> GND; 5 2Y -> Q403_G; 6 3A <- RFC_OFF; 7 1Y -> NCE; 8 VCC -> 3V3 | U201 |
| U402 | SN74LVC1G06DCKR | 1 NC nc; 2 A <- ILIM_REL; 3 GND -> GND; 4 Y -> Q401_G; 5 VCC -> 3V3 | U202 |
| R467 | 47.0 kOhm 1 % 0603 | 1 -> CE_DRV (at U401 pin 1); 2 -> GND | R267 |
| R468 | 47.0 kOhm 1 % 0603 | 1 -> ILIM_REL (at U401 pin 3); 2 -> GND | R268 |
| R469 | 47.0 kOhm 1 % 0603 | 1 -> RFC_OFF (at U401 pin 6); 2 -> GND | R269 |
| R470 | 47.0 kOhm 1 % 0603 | 1 -> ILIM_REL (at U402 pin 2); 2 -> GND | R270 |
| R472 | 47.0 kOhm 1 % 0603 | 1 -> NCE; 2 -> REGN (own via) | R272 |
| R472b | 47.0 kOhm 1 % 0603 | 1 -> NCE; 2 -> REGN (own via) | R272b |
| U403 | TLV3012BIDBVR | 1 OUT -> ILIM_SENSE; 2 V- -> GND; 3 IN+ -> N_ISP; 4 IN- -> N_ISM; 5 REF -> REF403; 6 V+ -> 3V3 | U203 |
| R458 | 10.0 kOhm 1 % 0603 | 1 -> ILIM_HIZ (own trace from U501 pin 17); 2 -> N_ISP | R258 |
| R459 | 10.0 MOhm 1 % 0603 | 1 -> N_ISP; 2 -> 3V3 | R259 |
| R460 | 10.0 kOhm 1 % 0603 | 1 -> REF403; 2 -> N_ISM | R260 |
| R461 | 10.0 kOhm 1 % 0603 | 1 -> N_ISM; 2 -> GND (quiet) | R261 |
| R325 | 1.00 kOhm 1 % 0603 | 1 -> ILIM_SENSE; 2 -> CHG_ILIM_RB (F13) | R125 (+ R265 deleted) |
| U404 | TLV3012BIDBVR | 1 OUT -> CE_SENSE; 2 V- -> GND; 3 IN+ -> N_CSP; 4 IN- -> REF404; 5 REF -> REF404; 6 V+ -> 3V3 | U204 |
| R462 | 1.00 MOhm 1 % 0603 | 1 -> NCE (own trace from U501 pin 13); 2 -> N_CSP | R262 |
| R463 | 1.00 MOhm 1 % 0603 | 1 -> N_CSP; 2 -> GND (quiet) | R263 |
| C453 (DNP) | 100 pF C0G 50 V 0603 | 1 -> N_CSP; 2 -> GND (quiet) | - (new; fit per T-K-09 step 5) |
| R348 | 1.00 kOhm 1 % 0603 | 1 -> CE_SENSE; 2 -> CHG_CE_RB (F20) | R148 (+ R264 deleted) |
| R475 | 1.00 kOhm 1 % 0603 | 1 -> STAT_IC; 2 -> STAT | R275 |
| R307 | 10.0 kOhm 1 % 0603 | 1 -> STAT; 2 -> 3V3 | R107 |
| R521 | 10.0 kOhm 1 % 0603, DNP | 1 -> NINT; 2 -> 3V3 | - (new) |
| R474 | 10.0 kOhm 1 % 0603 | 1 -> 3V3; 2 -> GND | R274 |
| C401, C402, C403, C404 | 100 nF 50 V X7R 0603 | 1 -> 3V3 (at U401/U402/U403/U404 VCC/V+); 2 -> GND | C201-C204 |

#### 2.5.6 Comparators (IC-independent; replaces CR B.2)

| Ref | Part / value | Pins -> nets | Was |
|---|---|---|---|
| U302 (H1) | TLV3012BIDBVR | 1 OUT -> H1; 2 V- -> GND; 3 IN+ -> N_H1P; 4 IN- -> N_H1M; 5 REF nc; 6 V+ -> 3V3 | U102 |
| R309 | 487 kOhm 0.1 % 0805 | 1 -> T1_VMOT (F01); 2 -> N_H1P | R109 |
| R310 | 56.2 kOhm 0.1 % 0603 | 1 -> N_H1P; 2 -> GND | R110 |
| C306 | 470 pF C0G 0603 | 1 -> N_H1P; 2 -> GND | C106 |
| R313 | 6.49 MOhm 1 % 0603 | 1 -> H1; 2 -> N_H1P | R113 |
| D304 | BAV199 | 1 -> GND; 2 -> 3V3; 3 -> N_H1P | D104 |
| R311 | 442 kOhm 0.1 % 0805 | 1 -> T2C (F03); 2 -> N_H1M | R111 |
| R312 | 56.2 kOhm 0.1 % 0603 | 1 -> N_H1M; 2 -> GND | R112 |
| C307 | 470 pF C0G 0603 | 1 -> N_H1M; 2 -> GND | C107 |
| D305 | BAV199 | 1 -> GND; 2 -> 3V3; 3 -> N_H1M | D105 |
| U303 (UVB) | TLV3012BIDBVR | 1 OUT -> UVB; 2 V- -> GND; 3 IN+ -> N_UVP; 4 IN- -> REF303; 5 REF -> REF303; 6 V+ -> 3V3 | U103 |
| R314 | 1.00 MOhm 0.1 % 0805 | 1 -> T2C; 2 -> N_UVP | R114 |
| R315 | 104 kOhm 0.1 % 0603 | 1 -> N_UVP; 2 -> GND | R115 |
| C308 | 1.0 nF C0G 0603 | 1 -> N_UVP; 2 -> GND | C108 |
| R316 | 10.0 MOhm 1 % 0603 | 1 -> UVB; 2 -> N_UVP | R116 |
| D306 | BAV199 | 1 -> GND; 2 -> 3V3; 3 -> N_UVP | D106 |
| U304 (BT_OK) | TLV3012BIDBVR | 1 OUT -> BT_OK; 2 V- -> GND; 3 IN+ -> N_BTP; 4 IN- -> N_BTM; 5 REF -> REF304; 6 V+ -> 3V3 | U104 |
| R341 | 61.9 kOhm 1 % 0603 | 1 -> REF304; 2 -> N_BTP | R141 |
| R342 | select-on-test 0.604-1.40 kOhm 1 % 0603 | 1 -> N_BTP; 2 -> KELVIN (F10) | R142 |
| R343 | 100 Ohm 1 % 0603 | 1 -> KELVIN; 2 -> GND | R143 |
| R340 | 10.0 kOhm 1 % 0603 | 1 -> BT_CURR (F09); 2 -> N_BTM | R140 |
| C340 | 10 nF 50 V X7R 0603 | 1 -> N_BTM; 2 -> GND | C140 |
| R344 | 1.00 MOhm 1 % 0603 | 1 -> BT_CURR; 2 -> 3V3 | R144 |
| U315 (BTB_OFF) | TLV3012BIDBVR | 1 OUT -> BTB_OFF; 2 V- -> GND; 3 IN+ -> N_BBP; 4 IN- -> N_BBM; 5 REF -> REF315; 6 V+ -> 3V3 | U115 |
| R317 | 20.0 kOhm 1 % 0603 | 1 -> REF315; 2 -> N_BBP | R117 |
| R318 | 10.0 kOhm 1 % 0603 | 1 -> N_BBP; 2 -> GND | R118 |
| C309 | 100 nF 50 V X7R 0603 | 1 -> N_BBP; 2 -> GND | C109 |
| R320 | 10.0 kOhm 1 % 0603 | 1 -> BTB (F04); 2 -> N_BBM | R120 |
| R319 | 10.0 MOhm 1 % 0603 | 1 -> N_BBM; 2 -> 3V3 | R119 |
| R321 | 1.00 kOhm 1 % 0603 | 1 -> RGN_TAP (F05); 2 -> RGN | R121 |
| R333 | 100 kOhm 1 % 0603 | 1 -> RGN; 2 -> GND | R133 |
| R322 | 1.00 kOhm 1 % 0603 | 1 -> FCC_TAP (F06); 2 -> FCC | R122 |
| R334 | DNP (footprint) | 1 -> FCC; 2 -> GND | R134 |
| U319 (FCC_OFF) | TLV3012BIDBVR | 1 OUT -> FCCN; 2 V- -> GND; 3 IN+ -> N_FOP; 4 IN- -> N_FOM; 5 REF -> REF319; 6 V+ -> 3V3 | U119 |
| R384 | 20.0 kOhm 1 % 0603 | 1 -> REF319; 2 -> N_FOP | R184 |
| R385 | 10.0 kOhm 1 % 0603 | 1 -> N_FOP; 2 -> GND | R185 |
| C330 | 100 nF 50 V X7R 0603 | 1 -> N_FOP; 2 -> GND | C130 |
| R386 | 10.0 kOhm 1 % 0603 | 1 -> FCC; 2 -> N_FOM | R186 |
| R387 | 3.30 MOhm 1 % 0603 | 1 -> N_FOM; 2 -> 3V3 | R187 |
| U320 (FCC_ON) | TLV3012BIDBVR | 1 OUT -> FCC_ON; 2 V- -> GND; 3 IN+ -> N_FNP; 4 IN- -> REF320; 5 REF -> REF320; 6 V+ -> 3V3 | U120 |
| R388 | 453 kOhm 1 % 0603 | 1 -> FCC; 2 -> N_FNP | R188 |
| R389 | 1.00 MOhm 1 % 0603 | 1 -> N_FNP; 2 -> GND | R189 |
| C336 (DNP) | 100 pF C0G 50 V 0603 | 1 -> N_FNP; 2 -> GND (quiet) | - (new; fit per T-K-09 step 5) |
| U321 (RGN_ON) | TLV3012BIDBVR | 1 OUT -> RGN_ON; 2 V- -> GND; 3 IN+ -> N_RNP; 4 IN- -> REF321; 5 REF -> REF321; 6 V+ -> 3V3 | U121 |
| R390 | 453 kOhm 1 % 0603 | 1 -> RGN; 2 -> N_RNP | R190 |
| R391 | 1.00 MOhm 1 % 0603 | 1 -> N_RNP; 2 -> GND | R191 |
| C337 (DNP) | 100 pF C0G 50 V 0603 | 1 -> N_RNP; 2 -> GND (quiet) | - (new; fit per T-K-09 step 5) |
| U317 (FCI_OK, DNP) | TLV3012BIDBVR | 1 OUT -> FCI_OK; 2 V- -> GND; 3 IN+ -> N_FCP; 4 IN- -> N_FCM; 5 REF -> REF317; 6 V+ -> 3V3 | U117 |
| R362, C327 (DNP) | 10.0 kOhm; 10 nF | R362 1 -> FC_CURR (F23), 2 -> N_FCM; C327 1 -> N_FCM, 2 -> GND | R162, C127 |
| R360, R361, R363 (DNP) | 10.0 kOhm; 1.18 kOhm select-on-test; 1.00 MOhm | R360 REF317 - N_FCP; R361 N_FCP - GND; R363 FCI_OK - N_FCP | R160, R161, R163 |
| C324 (DNP) | 100 nF | 1 -> 3V3 (U317 V+); 2 -> GND | C124 |
| R337 | 0 Ohm 0603 (fitted while U317 is not) | 1 -> FCI_OK; 2 -> 3V3 | R137 |

The DNP filter footprints C336, C337 and C453 cover the three unfiltered high-impedance comparator inputs. The Thevenin
impedance at N_FNP and N_RNP is 312.2 kOhm ((453 kOhm + 1 kOhm) parallel 1.00 MOhm). At N_CSP it is 505.8 kOhm
((1.00 MOhm + 23.5 kOhm) parallel 1.00 MOhm). Without a filter, the time constant is 0.94-5.06 us for a 3-10 pF node.
With 100 pF and a 10 pF node, the time constant is 34.3 us (N_FNP, N_RNP) and 55.6 us (N_CSP). The FCC_ON and RGN_ON
permits then lag by <= 33.4 us rising and <= 21.6 us falling; the N_CSP sense lags by <= 47.1 us. The fall lag is 1.1 %
of the 2 ms spacing between steps A and D of [WD] F.4. A fall lag of 10 % of that spacing gives the ceiling
C_f + C_node <= 1016 pF. A false LOW-state trip needs 0.16-0.88 pF of stray coupling from SW1 without a filter. With
100 pF it needs 5.5-9.7 pF ([CALC], section "High-impedance comparator inputs"). The node capacitance is
TODO(verify: SBOS300C input capacitance).

#### 2.5.7 Logic (IC-independent except U311 and the QUAL inputs, S)

| Ref | Part / value | Pins -> nets | Was |
|---|---|---|---|
| R378 | 100 kOhm 1 % 0603 | 1 -> BAL_TAP (F08); 2 -> N_BAL | R178 |
| D308 | BAV199 | 1 -> GND; 2 -> 3V3; 3 -> N_BAL | D108 |
| R379 | 1.00 MOhm 1 % 0603 | 1 -> N_BAL; 2 -> 3V3 | R179 |
| U323 | SN74LVC1G14DCKR | 1 NC -> GND; 2 A <- N_BAL; 3 GND -> GND; 4 Y -> OVN; 5 VCC -> 3V3 | U123 |
| U322 | SN74LVC1G08DCKR | 1 A <- ARM_OK; 2 B <- OVN; 3 GND -> GND; 4 Y -> ARM_OKP; 5 VCC -> 3V3 | U122 |
| R308 | 47.0 kOhm 1 % 0603 | 1 -> CHG_ARM; 2 -> GND | R108 |
| U305 | SN74LVC3G04DCTR | 1 1A -> GND; 2 3Y nc; 3 2A <- CHG_ARM; 4 GND -> GND; 5 2Y -> P5N; 6 3A -> GND; 7 1Y nc; 8 VCC -> 3V3 | U105 |
| U306 | SN74LVC2G32DCTR | 1 1A <- UF; 2 1B <- H1R; 3 2Y -> RFC_OFF; 4 GND -> GND; 5 2A <- FCCN; 6 2B <- H1R; 7 1Y -> X; 8 VCC -> 3V3 | U106 |
| U307 | SN74LVC1G11DCKR | 1 A <- BT_OK; 2 GND -> GND; 3 B <- X; 4 Y -> Y1; 5 VCC -> 3V3; 6 C <- FCI_OK | U107 |
| U308 | SN74LVC1G11DCKR | 1 A <- FCC_ON; 2 GND -> GND; 3 B <- BTB_OFF; 4 Y -> H2C; 5 VCC -> 3V3; 6 C <- Y1 | U108 |
| U309 | SN74LVC1G11DCKR | 1 A <- H1; 2 GND -> GND; 3 B <- RGN_ON; 4 Y -> H1Q; 5 VCC -> 3V3; 6 C <- W | U109 |
| U310 | SN74LVC2G32DCTR | 1 1A <- H1Q; 2 1B <- H2C; 3 2Y -> ILIM_PRE; 4 GND -> GND; 5 2A <- GATE; 6 2B <- QQF; 7 1Y -> GATE; 8 VCC -> 3V3 | U110 |
| U311 (S) | SN74LVC1G123DCTR | 1 A -> GND; 2 B <- QUAL; 3 CLR <- P5N; 4 GND -> GND; 5 Q -> QQ; 6 Cext -> N_CX311; 7 Rext/Cext -> N_RC311; 8 VCC -> 3V3 | U111 |
| C350 (S) | 3.3 uF 16 V X7R 0805 | 1 -> N_CX311; 2 -> N_RC311 | C150 |
| R350 (S) | 100 kOhm 1 % 0603 | 1 -> N_RC311; 2 -> 3V3 | R150 |
| R347 (S) | 1.00 kOhm 1 % 0603 | 1 -> QUAL_TAP (F11); 2 -> QUAL | R147 |
| R323 (S) | 47.0 kOhm 1 % 0603 | 1 -> QUAL; 2 -> GND | R123 |
| U313 | SN74LVC1G123DCTR | 1 A -> GND; 2 B <- HB; 3 CLR -> 3V3; 4 GND -> GND; 5 Q -> ARM_OK; 6 Cext -> N_CX313; 7 Rext/Cext -> N_RC313; 8 VCC -> 3V3 | U113 |
| C351 | 330 nF 16 V X7R 0603 | 1 -> N_CX313; 2 -> N_RC313 | C151 |
| R351 | 100 kOhm 1 % 0603 | 1 -> N_RC313; 2 -> 3V3 | R151 |
| R335 | 1.00 kOhm 1 % 0603 | 1 -> HB_TAP (F21); 2 -> HB | R135 |
| R336 | 100 kOhm 1 % 0603 | 1 -> HB; 2 -> GND | R136 |
| R324 | 47.0 kOhm 1 % 0603 | 1 -> FCCEIL (F12); 2 -> GND | R124 |
| U314 | SN74LVC2G08DCTR | 1 1A <- CHG_ARM; 2 1B <- ARM_OKP; 3 2Y -> ILIM_REL; 4 GND -> GND; 5 2A <- ILIM_PRE; 6 2B <- ARM_OKP; 7 1Y -> CE_DRV; 8 VCC -> 3V3 | U114 |
| U316 | SN74LVC2G08DCTR | 1 1A <- UVB; 2 1B <- FCCEIL; 3 2Y -> W; 4 GND -> GND; 5 2A <- FCCN; 6 2B <- UVB; 7 1Y -> UF; 8 VCC -> 3V3 | U116 |
| U318 | SN74LVC2G08DCTR | 1 1A <- H1; 2 1B <- RGN_ON; 3 2Y -> QQF; 4 GND -> GND; 5 2A <- QQ; 6 2B <- FCCN; 7 1Y -> H1R; 8 VCC -> 3V3 | U118 |
| R326 | 1.00 kOhm 1 % 0603 | 1 -> H1; 2 -> CHG_H1_RB (F14) | R126 |
| R327 | 1.00 kOhm 1 % 0603 | 1 -> H2C; 2 -> CHG_H2_RB (F15) | R127 |
| R328 | 1.00 kOhm 1 % 0603 | 1 -> BT_OK; 2 -> CHG_BTOK_RB (F16) | R128 |
| R375 | 68.0 Ohm 1 % 0.25 W 1206 | 1 -> T6_3V3 (F07); 2 -> 3V3 | R175 |
| C325 | 10 uF 10 V X7R 0805 | 1 -> 3V3 (downstream of R375); 2 -> GND | C125 |
| R345, R346 | DNP (footprints) | R345 1 -> SDA, 2 -> 3V3; R346 1 -> SCL, 2 -> 3V3 | R145, R146 |
| C310-C323, C326, C331-C335 | 100 nF 50 V X7R 0603 | 1 -> 3V3 at the VCC/V+ pin of U302 (C310), U303 (C311), U304 (C312), U315 (C313), U305 (C314), U306 (C315), U307 (C316), U308 (C317), U309 (C318), U310 (C319), U311 (C320), U313 (C321), U314 (C322), U316 (C323), U318 (C326), U319 (C331), U320 (C332), U321 (C333), U322 (C334), U323 (C335); 2 -> GND | C110-C123, C126, C131-C135 |

#### 2.5.8 Keep-alive option (IC-independent, all DNP; [WD] B.5)

| Ref | Part / value | Pins -> nets | Was |
|---|---|---|---|
| U312 | TPS22810DBVR | 1 VIN <- KA_5V (F22); 2 GND -> GND; 3 EN/UVLO <- RGN; 4 CT -> N_CT312; 5 QOD open; 6 VOUT -> N_KA | U112 |
| C352 | 2.2 nF C0G 0603 | 1 -> N_CT312; 2 -> GND | C152 |
| D301 | BAT54HT1G | A -> N_KA; K -> N_KAK (pin numbers TODO(verify: onsemi BAT54HT1G datasheet)) | D101 |
| R392 | 680 Ohm 0.25 W 1206 | 1 -> N_KAK; 2 -> VCHG | R_KA |

The MB-side parts of this option (F101 fuse and R172 33 Ohm at CO-5V pad 1) remain MB rework ([WD] B.8).

#### 2.5.9 Tap field (IC-independent; [WD] A.4)

| Pad | Tap | Board net | Board-side part | MB point |
|---|---|---|---|---|
| F01 | T1 | T1_VMOT | R309 | C-D6 pad 1 via R170 (MB) |
| F02 | T7b | GND (shield, bonded at the board end only) | - | C-D6 pad 2, insulated |
| F03 | T2 | T2C | R311, R314 | C-D2 pad 1 via R171 (MB) |
| F04 | T3 | BTB | R320 | J1.39 (pin 28 EN net) |
| F05 | T4 | RGN_TAP | R321 | J1.43 (pin 30 EN net) |
| F06 | T5 | FCC_TAP | R322 | J1.45 (pin 31 EN net) |
| F07 | T6 | T6_3V3 | R375 | J1.29 (3V3) |
| F08 | T22 | BAL_TAP | R378 | BQ29200 pin 8 (BAL-NOK) |
| F09 | T8 | BT_CURR | R340, R344 | J2.31 (pin 41) |
| F10 | T9 | KELVIN | R342, R343 | SNS-BT GND/REF1 pad |
| F11 | T10 | QUAL_TAP | R347 | J1.23 (pin 10) |
| F12 | T11 | FCCEIL | R324 | J2.19 (pin 17) |
| F13 | T12 | CHG_ILIM_RB | R325 | J2.47 (pin 33) |
| F14 | T13 | CHG_H1_RB | R326 | J2.45 (pin 34) |
| F15 | T14 | CHG_H2_RB | R327 | J2.21 (pin 16) |
| F16 | T15 | CHG_BTOK_RB | R328 | J2.07 (pin 23) |
| F17 | T16 | CHG_EFUSE_FLT | U301 pin 14 | J2.43 (pin 35) |
| F18 | T17 | CHG_IIN | R329, C329 | J2.09 (pin 22) |
| F19 | T17r | GND (shield, board end only) | - | J2.29, insulated |
| F20 | T20 | CHG_CE_RB | R348 | MB ROS pad 2 (pin 7) |
| F21 | T21 | HB_TAP | R335 | J2.11 (pin 21) |
| F22 | T18 (DNP) | KA_5V | U312 | CO-5V pad 1 via F101 + R172 (MB) |
| F23 | T19 (DNP) | FC_CURR | R362 | J2.33 (pin 40) |
| F24 | spare | none | - | J1.07 (pin 2) only if T-A-01b clears it |

#### 2.5.10 Test points

| Ref | Net | Class | Note |
|---|---|---|---|
| TP301 | 3V3 | I | |
| TP302 | GATE | I | |
| TP303 | ARM_OKP | I | |
| TP304 | ILIM_REL | I | |
| TP305 | CE_DRV | I | |
| TP306 | GND (quiet) | I | |
| TP501 | VCHGOUT | S | SMD probe pad, solder-masked surround |
| TP502 | VCHG | S | |
| TP503 | REGN | S | |
| TP504 | ILIM_HIZ | S | Probe only; no part may land here (§2.2.2 rule 1) |
| TP505 | NCE | S | |
| TP506 | TS | S | |
| TP508 | NINT | S | |
| TP509 | NQON | S | A LOW for 10 s resets system power ([DS] §7.3.12) |
| TP510 | CHG_SYS | S | |
| TP511 | GND (power) | I | |

No test point is placed on VCHGIN ([WD] A.8 "no exposed test pad"), PMID, SW1 or SW2 ([DS] §8.4.1 item 2: minimise
switch-node copper). Bench probes use the C511/C529 and L501 pads.

#### 2.5.11 Net classification

| Class | Nets |
|---|---|
| IC-independent | VCHGIN, VCHGOUT (as the eFuse output), VCHG, GND, 3V3, T6_3V3, STAT (board side), CHG_ARM, P5N, SCL, SDA, TS_EXT, H1, UVB, BT_OK, BTB_OFF, FCC, FCCN, FCC_ON, RGN, RGN_ON, OVN, ARM_OK, ARM_OKP, UF, W, X, Y1, H2C, H1Q, H1R, GATE, ILIM_PRE, CE_DRV, ILIM_REL, RFC_OFF, FCI_OK, HB, FCCEIL (wire), all N_* comparator nodes, REF3xx, every F-pad net, N_UV, N_OV, N_DVDT, N_ILIMF, N_IMON, CHG_IIN, CHG_EFUSE_FLT, KA_5V, N_KA, N_KAK, N_CT312 |
| BQ25798-specific | PMID, SW1, SW2, N_BTST1, N_BTST2, CHG_SYS, REGN, N_BATP, N_PROG, N_SDRV, N_DP, N_DM, NQON, NINT, STAT_IC, NCE, ILIM_HIZ, ILIM_FEED, N_FCLEG, Q401_G, Q402_G, Q403_G, TS, ILIM_SENSE, CE_SENSE, N_ISP, N_ISM, REF403, N_CSP, REF404, QUAL, QQ, QQF, N_CX311, N_RC311, N_SN1, N_SN2, N_SNIN |

#### 2.5.12 Part count

The fitted parts number about 174: the power stage 24 (§2.5.4), the eFuse network 15 (§2.5.3), the charger interface 39
(§2.5.5, including the TS network), the comparators 45 (§2.5.6) and the logic 51 (§2.5.7, including 20 decouplers). The 16 test
points and the 22-pin header come on top. DNP footprints add about 28, including the filter footprints C336, C337 and C453
(§2.5.5, §2.5.6). The layout section uses this count for the area budget. The count is a hand count of this netlist; the capture produces the exact one.

### 2.6 Power-up and reset states

#### 2.6.1 Mixed table (IC-independent logic columns, BQ25798-specific pin columns)

Table 2.8 extends [WD] B.7 to the single board. "Held" means ILIM_HIZ below 0.75 V (converter off, REGN on, [DS]
§7.3.4.3). With an input source, REGN rises about 150 ms after VBUS_PRESENT ([DS] §7.3.4 step 5). From battery only,
REGN stays off at POR ([DS] §7.3.3). It turns on in OTG mode, or when VBAT exceeds 3.2 V with the TS ADC channel on
(ADC_EN = 1, TS_ADC_DIS = 0) ([DS] §7.3.4.1). TS_ADC_DIS resets to 0 and the image leaves REG2F at reset (FR-50). FR-48
and the continuous scan set ADC_EN, so REGN is on while they run from a battery above 3.2 V.

| Condition | P5 | QQ | ARM_OK | Comparators | GATE | REGN | ILIM_HIZ (U501.17) | /CE (U501.13) | Charger |
|---|---|---|---|---|---|---|---|---|---|
| Board and Teensy unpowered, pack connected | - | - | - | unpowered (outputs LOW) | - | off | 0 V (R523, R456) | 0 V (R463 via R462) | no input power: every RT1987 EN LOW |
| Teensy reset / boot (pins high-Z) | LOW (R308) | 0 | 0 after tw (no HB edges) | valid | 0 (RGN = FCC = 0) | off | 0 V | 0 V | unpowered (EN pull-downs) |
| VCHG-IN arrives (eFuse soft start, UVLO 9.91 V rising) | per firmware | 0 | per HB | valid | per mode | rises ~150 ms after VBUS_PRESENT ([DS] §7.3.4 step 5) | held: Q401 gate follows REGN through R452; Q403 off (R471); no feed | rises with REGN through R472/R472b, unless U401 1Y sinks | POR image: EN_CHG 1, ICHG 1 A, VINDPM = VBUS0 - 1.4 V ([DS] §7.3.4.4); no conversion while held |
| Monostable power-up | any | 0 (glitch-free reset) | 0 until the first HB edge | - | - | - | held | HIGH | - |
| Comparator POR (<= 1.9 ms) | any | any | any | LOW (incl. FCC_OFF, FCC_ON, RGN_ON) | H1q = H2c = 0; QQF = 0 | - | held | P5 AND ARM_OK' | inhibited |
| T22 open, BQ29200 unpowered (J-BL unplugged) or cell OV | any | any | running | valid | per mode | on | held (ARM_OK' = 0) | HIGH | inhibited in every mode; FR-47 latches CHG_PACK_OV |
| FCC or RGN EN at an intermediate level | any | any | any | FCC_OFF = FCC_ON = 0 (or RGN_ON = 0) | 0 | on | held unless QQ | per P5 | converter off; FR-49 refuses arming |
| Board 3V3 lost while armed (T6 open) | Teensy may drive; LVC Ioff blocks back-feed | - | - | unpowered | - | on | held: U401/U402 outputs float, Q401 on (R452), Q403 off (R471), Q402 on (R454) | HIGH (R472/R472b) | off, FC clamp; rail held at 0.3-0.45 V across R474 by the BAV199 back-feed ([WD] B.7); pin 7 reads LOW -> FR-08(b) |
| eFuse latched off (VCHGIN valid, VCHGOUT 0 V) | any | any | any | valid | per mode | off | 0 V | 0 V | unpowered; FLT LOW on pin 35, `regnExpected` false (FR-23) |
| Charger POR (input glitch) | as before | as before | running | valid | per mode | restarts | per mode (held if GATE = 0) | per P5 | POR image; firmware re-images ([WD] G.1) |
| Teensy hang, or stalled 1 kHz monitor | frozen | ends after tw_QQ | 0 within 20-46 ms | valid | hardware | on | held | HIGH (either pull-up intact) | inhibited, converter off in every mode |
| D-BT-SQ shorted (pack on VCHG), VCHG-IN off, ADC_EN = 0 | any | any | any | valid | per mode | off (battery-only, [DS] §7.3.3) | 0 V | 0 V | battery-only quiescent |
| D-BT-SQ shorted (pack on VCHG), VCHG-IN off, ADC_EN = 1 (FR-48 one-shot or scan) | any | any | any | valid | per mode | on ([DS] §7.3.4.1; VBAT 7.4-8.4 V > 3.2 V) | held (Q401 gate via R452) | HIGH (R472/R472b); U404 reads HIGH | inhibited; CHG_CE_RB not evaluated because `regnExpected` is false (FR-23); FR-48 latches the short from REG3B ([WD] B.5) |
| R392 keep-alive fitted, D-BT-SQ healthy, VCHG-IN off (Idle) | any | any | any | valid | per mode | on during each FR-48(a) one-shot (BAT <= 4.46 V > 3.2 V, [WD] B.5); otherwise off | held during the one-shot; otherwise 0 V | HIGH during the one-shot; otherwise 0 V | battery-only quiescent; CHG_CE_RB not evaluated (`regnExpected` false) |

#### 2.6.2 Differences from round 3

1. The CR rail and the EIB rail are one rail, so "CR 3V3 lost" and "EIB 3V3 lost" are one row.
2. The rows for E-lead and ribbon faults are deleted; the trace-crack case fails safe through R467-R470 (§2.3.2).
3. The eFuse-latched row is new as a pin-level statement: with VCHGOUT at 0 V both pins read 0 V, and U404 reports /CE LOW.
   FR-23 gates FR-08(b) on FLT HIGH, so this state causes no false trip ([WD] G.2 FR-23).

## 3. Layout plan

This section plans the printed-circuit layout of the CCB defined in sections 1 and 2. It fixes the stack, the zones, the
power-loop placement and the copper rules. It does not replace the courtyard placement check (T-A-06 class) of a real
capture. Each subsection carries a label of §0.4.

Coordinates are MB board coordinates (§0.7). "Cell coordinates" are local to U501, with the origin at the IC centre, in
the TI orientation of [DS] Fig 8-21 (power-pad edge at +y). The renders cited as [DS] figures are pages of SLUSDV2C: Fig
8-21 on p.140, the package outline on p.148, the land pattern on p.149, the stencil on p.150, and Figs 6-3 and 6-4 on
p.18. TIDA-050047 positions come from its PCB file and Gerbers through [TLP], in the same cell coordinates.

### 3.1 Layer stack (M)

#### 3.1.1 Layer count and assignment

The CCB uses **four copper layers**. Two facts force this. [DS] §8.4.2 routes SW1 and SW2 "to vias placed under the IC and
then back out on an inner PCB layer". §1.5 requires a solid ground layer between any switch node and the MB logic
traces MPPT-DISABLE (y 64.484) and CB-DISABLE ([MECH] §4) that run under the CCB.

Table 3.1 gives the assignment. It follows the EVM layer use ([UG] Figs 4-1 to 4-4; [TID] §4.3, Interp.), with one change
for the MB below.

| Layer | Assignment | Rules |
|---|---|---|
| L1 (top) | All ICs, the power cell, the eFuse, the tap pads F01-F24, all test points. Power pours VCHGIN, VCHGOUT, PMID, SYS, VCHG (BAT), PGND | Power-loop parts on L1 only ([DS] §8.4.1 items 1, 2). Short logic fan-out |
| L2 | **Solid GND plane.** No traces | One void only: under the L501 terminal footprint, as TIDA-050047 voids L2 under its inductor footprint ([TLP] §5; 3.4.3 item 5). L2 stays solid over the L3 strips, as in TIDA-050047. The EVM layer 2 appears to void L2 over the strips instead ([TID] §4.3, Interp.) |
| L3 | SW1 and SW2 strips from the vias under U501 to the L501 pads, inside the power cell only. Outside the cell: logic and sense routing, GND fill | No signal within 2.0 mm of SW copper on L3; a stitched GND guard pour separates them (3.6.3) |
| L4 (bottom) | **GND pour under the whole power cell** (shield toward the MB). Outside the cell: the VCHG battery path (3.2.2), logic routing, bottom passives (3.9) | Only exception inside the cell: the BTST capacitor pads C506/C508 under U501 (3.4.4) |

Note that the shield rule of §1.5 binds L4, not L2. In a standard 4-layer build, L3 lies one thin prepreg above L4 and
one core below L2. TIDA-050047 uses this structure: 0.305 mm prepreg, 0.660 mm core, 0.305 mm prepreg ([TLP] §1). The
CCB fab stack is TODO(verify: fab stack drawing). The L3 strips therefore couple mainly to L4, so L4 must be GND under them.

The parasitic capacitance of one SW strip to L4 is small. A 1.5 x 6 mm strip over 0.2 mm of FR-4 (εr about 4.4) gives
about 1.8 pF. At 22 V and 1.5 MHz this costs about C V² f = 1.3 mW. An L2 void over the strips is therefore not a loss
lever, and the CCB follows TIDA-050047 in keeping L2 solid there.

#### 3.1.2 Thickness and dielectrics (I)

- Finished thickness: **1.6 mm**, the value assumed by §1.3 for H_u and the header tail lengths.
- L1-L2 prepreg: the thinnest the fab offers in a 1.6 mm build (about 0.1-0.2 mm). A thin L1-L2 gap lowers the inductance
  of the PMID and SYS loops, which return on L2. TODO(verify: fab stack table).
- Material: standard FR-4, Tg 150 C or higher, because the copper near U501 can exceed 100 C (3.7). TODO(verify: fab
  material options).

#### 3.1.3 Copper weights (M)

Table 3.2 compares the two candidate stacks. The battery-side and input-side widths come from the IPC-2221 chart fit
I = k ΔT^0.44 A^0.725 (k 0.048 external, 0.024 internal; [LC] §1). The same fit reproduces the round-3 H.22 values: 2.5 mm
at 2 oz external carries 7.7 A at 10 C rise, and 2.0 mm at 1 oz carries 4.0 A ([WD] H.22(c)).

| Stack | Outer / inner | Advantage | Disadvantage | Decision |
|---|---|---|---|---|
| ST1 | 1 oz finished / 1 oz | Standard at every fab; 0.2 mm gaps of the RQM land pattern ([DS] p.149) are inside normal 1 oz capability | Battery path needs 2.5 mm on L1 (vs 2.5 mm at 2 oz in round 3) | **Baseline** |
| ST2 | 1 oz / 2 oz | L2 spreads heat with half the sheet resistance; an L3 SW strip of 1.4 mm meets 20 C rise at 3.37 A | Inner 2 oz availability at a prototype fab is TODO(verify) | **Preferred if available** |
| ST3 | 2 oz / 1 oz (the round-3 CR stack, [WD] A.7) | Narrow power pours | The RQM pads are 0.2 mm wide at 0.4 mm pitch ([DS] p.149), so the copper gap is 0.2 mm. A 2 oz outer layer may not etch that gap at the chosen fab. TODO(verify: fab minimum space at 2 oz outer) | **Not chosen for rev A** unless the fab confirms 0.2 mm space at 2 oz |
| ST4 | 2 oz / 2 oz (the TIDA-050047 stack, [TLP] §1) | TI fabricated this land pattern in 2 oz outer copper; L3 SW strips of 1.1 mm match TIDA-050047 directly | Same fab confirmation as ST3; highest cost | **Reference only**; candidate if the fab confirms 0.2 mm space at 2 oz outer |

The round-3 CR could use 2 oz outer copper because its finest part was the 0.5 mm pitch TPS26630. The BQ25798 land pattern
is finer, so the CCB moves the current capacity from copper weight to copper width. TIDA-050047 shows that 2 oz outer
copper with the 0.2 mm gaps is buildable at a fab that TI used. This does not show that every prototype fab can build it.

#### 3.1.4 Conductor widths per current class (M)

Table 3.3 gives the minimum widths. The design current follows round 3: the battery side is ICHG 3.10 A + 3.5 % = 3.21 A,
designed to 3.5 A ([WD] A.7); the input side is the eFuse I_OL maximum 2.41 A ([WD] B.4).

| Net class | Design current | IPC-2221 minimum (1 oz external, 10 C rise) | Rule on the CCB (ST1) | Round-3 CR rule ([WD] A.7, H.22) |
|---|---|---|---|---|
| VCHG (BAT to pins 18/19), GND battery return to pins 14/15 (I) | 3.5 A | 1.69 mm ([LC] §1) | **Pours >= 2.5 mm** on L1 or L4 (4.65 A at 10 C rise, [LC] §1); both layers in parallel where the cell allows | >= 2.5 mm at 2 oz (7.7 A); 1 oz fallback >= 2.0 mm (4.0 A) |
| VCHGIN, VCHGOUT, VBUS, PMID (I/S) | 2.41 A for <= 202 ms; 1.76 A continuous ([WD] H.4) | 1.01 mm at 2.41 A | **Pours >= 1.5 mm** (3.21 A at 10 C rise); VCHGIN <= 5 mm from pad 10 ([WD] A.8) | >= 2.5 mm at 2 oz |
| SYS pour (S) | Inductor RMS 3.37 A ([LC] §3) | 1.60 mm | Pour, not a trace; >= 2.5 mm at every neck | - |
| SW1, SW2 on L3 (S) | 3.37 A RMS, 4.99 A peak at 22.28 V ([LC] §3) | Internal: 2.74 mm at 1 oz / 1.37 mm at 2 oz, 20 C rise | **>= 1.5 mm and <= 2.5 mm wide, as short as the cell allows** (3.4.3). The IPC-2221 chart describes long conductors; a 5-7 mm strip between two via fields runs cooler | - |
| REGN, BTST (S) | < 50 mA | - | 0.3 mm | - |
| Logic, sense, high-impedance analog (I) | < 10 mA | - | 0.15-0.2 mm | - |

Clearance: every net above 16 V (VCHGIN, VCHGOUT, VBUS, PMID, SW1, BTST1) keeps >= 0.2 mm to other nets on L1/L4. This is
probably above the IPC-2221B value for the 16-30 V band, TODO(verify: IPC-2221B Table 6-1).

#### 3.1.5 Vias (M)

[LC] §2 gives the via figures for 25 µm barrel plating (assumed; TODO(verify: fab plating)):

| Drill | IPC-2221 at 10 C rise (internal k) | Thermal resistance through 1.6 mm, unfilled |
|---|---|---|
| 0.2 mm | 0.73 A | 235 C/W |
| 0.3 mm | 0.95 A | 163 C/W |

The rules are:

1. Every layer transition of a 3.5 A path uses **>= 5 vias of 0.3 mm** (4.8 A at the internal k).
2. Every 2.41 A transition uses >= 3 vias of 0.3 mm.
3. Every bypass-capacitor ground uses >= 2 vias to L2 ([DS] §8.4.1 items 3 and 4; [UG] §3 item 4).
4. Vias inside the U501 outline sit under the package body between the pad rows, never in a pad: four of 0.254 mm drill
   (0.508 mm land) per SW node and three of 0.381 mm (0.762 mm land) plus one of 0.254 mm on the GND island, tented and
   unfilled (3.4.3; TIDA-050047, [TLP] §3, §4). The land pattern shows no in-pad via ([DS] p.149). The TIDA-050047 fab
   notes do not specify via fill (GM10, [TLP] §1). TODO(verify: fab minimum land-to-pad space of 0.12-0.15 mm, 3.4.3 item 6).

#### 3.1.6 Fabrication class and fab houses (I)

| Item | Value | Reason |
|---|---|---|
| Acceptance class | IPC-6012 class 2 | Prototype on a vehicle; class 3 is not required by any source |
| Minimum trace / space | 0.10 / 0.10 mm (fan-out of U501 at 0.15 / 0.2 mm) | RQM land pattern, 0.4 mm pitch, 0.2 mm pads ([DS] p.149). TIDA-050047 draws 0.152 mm traces with a 0.127 mm clearance rule and 0.121 mm via-land-to-pad space ([TLP] §4, §6) |
| Pad definition | Non-solder-mask-defined, mask expansion <= 0.05 mm | [DS] p.149 detail; TIDA-050047 uses 0.05 mm ([TLP] §3) |
| Solder-mask web between U501 pads | about 0.1 mm (0.2 mm gap minus 2 x 0.05 mm) | TODO(verify: fab minimum mask dam) |
| Minimum drill | 0.254 mm under the U501 body (tented, unfilled); 0.3 mm elsewhere | 3.1.5 rule 4 |
| Header holes | Per the chosen strip drawing (0.64 mm pin) | TODO(verify: Samtec TSW / socket drawing) |
| Finish | ENIG | Flat pads for the 0.4 mm pitch part; the round-3 CR used ENIG ([WD] E) |
| Impedance control | Not required | No controlled-impedance net |

Fab houses: JLCPCB, PCBWay and OSH Park all offer 4-layer boards. This plan did not check their capabilities. Each item is
TODO(verify: fab capability page): 0.1 mm trace/space at 1 oz, 2 oz inner layers (ST2), 0.254 mm vias with 0.508 mm
lands at 0.12-0.15 mm from a pad, the 0.1 mm mask dam, the stack drawing (prepreg thickness) and ENIG. Choose the fab
that meets ST2. Filled via-in-pad is not required (3.1.5 rule 4).

### 3.2 Floor plan on the board outline (M)

#### 3.2.1 Outline and fixed features (I)

The outline is the §1.8 L-shape: body x 17.70-48.70, y 34.14-67.14; high-y tab x 17.70-38.90, y 67.14-76.40. Fixed
features take space before any part is placed:

- Header pads: left column x 20.998, pins 11-22 at y 36.544-64.484; right column x 45.998, pins 1-10 at y 39.084-61.944
  ([MECH] §1). Part courtyards stay outside x 19.67-22.33 and x 44.67-47.33 over the column lengths (1.65 mm pad + 0.5 mm).
- Foot holes at (23.20, 70.64) and (32.20, 70.64), §1.4. Each needs a part-free circle of radius 3.0 mm on both sides
  for the screw head and spacer. TODO(verify: screw head and spacer diameters).
- Tap field F01-F24 at x 23.90 + k x 2.54 (k = 0-7), y 35.80 / 38.34 / 40.88 ([WD] A.8), kept unchanged so the MB rework
  documents stay valid (§0.5).

#### 3.2.2 Zones (Figure 3.1)

Figure 3.1 shows the zones in MB coordinates. The power cell sits inside the pin field, in the upper half of the body,
next to the tab and on the side away from the LM1084.

```
 Figure 3.1  CCB floor plan, top view, MB coordinates (mm). Not to scale.
 y
76.40 +-----------------------------------------+ . . . . . . . . . . . +
      | Z-C tab: charger-pin passives (S)        | rect A' (reserve,     .
      |   ( foot 1 )   [/CE,TS]   ( foot 2 )     | H_u >= 2.75 mm,       .
      |  (23.20,70.64)           (32.20,70.64)   | passives only) §1.3   .
67.14 +--+--------------------------------+------+------+-------+-------+ (48.70)
      |11|  Z-P  POWER CELL (S)           | Z-E  eFuse U301 (I)| pocket|
      |  |  U501 at ~(28.2, 65.0), 180 deg| U301 (41.8, 64.1)  |       |
      |13|  L501 below U501               +--------------------+   10  |
      |14|  PMID bulk +x, SYS bulk -x     | Z-D  drivers and   |    8  |
      |15|  x 22.4-37.5, y 50.4-67.4      |  pin senses U401-  |    7  |
      |  |                                |  U404, Q401-Q403(*)|       |
50.40 |17+--------------------------------+--------------------+    5  |
      |18|  Z-Q  comparators, permit logic, monostables,       |    4  |
      |19|       pack-OV input (I)  x 22.4-44.6, y 42.1-50.4   |    3  |
42.13 |  +-----------------------------------------------------+       |
      |21|  Z-T  tap field F01-F24 (I)  x 23.15-42.43          |    1  |
34.14 +--+-----------------------------------------------------+-------+
    17.70 21.0                                                 46.0  48.70   x
 Left column = header pins 11-22 (VBAT+ 18/19, GND 14/15, THERM 13, MPPTD 11).
 Right column = pins 1-10 (STAT 3, GND 4, SCL 7, SDA 8, VIN+ 10).
 LM1084 courtyard starts at x 50.947 (right of the outline); J-BL / J-NTC are left of x 17.70.
 (*) Q401-Q403 may move to Z-C beside ILIM_HIZ (3.6.2).
```

Table 3.4 lists the zone contents and the reason for each position.

| Zone | Extent (MB mm) | Contents | Label | Reason |
|---|---|---|---|---|
| Z-P power cell | x 22.4-37.5, y 50.4-67.4 | U501, L501, C529-C532, C518-C523, C538/C539, C513/C514, C535, C506/C508 (L4), R515, R529, SW snubber footprints | S | §1.6.1 rule 1 power zone (x 17.70-38.90, y >= 50); the power cell edge x 37.5 is 13.4 mm from the LM1084 courtyard; U501 centre about 25.7 mm from the LM1084 body |
| Z-E input | U301 and +x pocket per [WD] A.8 (U301 centre (41.8, 64.1), pocket x 44.3-48.2, y 63.4-66.64); IN-side parts below U301 | U301, R301-R305, C301, C302a/b/c, D307, C303, D303, R329/C329, C511/C512 on the VCHGOUT run | I | VCHGIN <= 5 mm from pad 10 ([WD] A.8); §1.6.1 rule 5 |
| Z-D drivers | x 37.5-44.6, y 50.4-61.6 | U401, U402, U403, U404, R467-R470, R458-R463 dividers, R325/R348, C401-C404 | S (topology I) | Between the logic that drives them (Z-Q) and U501; §1.6.1 rule 3 low-dissipation strip beside the LM1084 |
| Z-Q logic | x 25.4-44.6, y 42.1-50.4 (top; x 22.4-25.4 is the VCHG corridor of 3.3.3 item 4) and the bottom side outside the keep-outs | U302-U323, their dividers, R3xx, C3xx | I | Next to the taps that feed them; separation regions Q10-T, Q10-B and Q5 of Table 3.9b (3.6.1) |
| Z-T taps | x 23.15-42.43, y 35.05-41.63 | F01-F24 | I | Unchanged from [WD] A.8 |
| Z-C tab | x 17.7-38.9, y 67.14-76.40 minus the foot circles | R523, R456, C452, R518, R524, R525/R526, R472/R472b, R462 (pin side), R529 if not in Z-P, TP503-TP506, TP508, TP509 | S | Beside the U501 control-pin edge (pins 10-17 after rotation, 3.4.5); over bare MB GND pour (§1.2.1) |

The comparators U302-U304, U315, U319-U321, U403, U404 and the 0.1 % dividers stay at x <= 43.7, 5 mm inside the right edge
(§1.6.1 rule 4). The zone extents of Table 3.4 are bounding boxes: Z-D and Z-Q reach x 44.6, but the listed parts stay
at x <= 43.7. TODO(measure: M11 air temperature at x 48.7 confirms the 5 mm).

#### 3.2.3 Area budget (M)

[LC] §6 books the courtyard area with the round-3 courtyard sizes ([WD] A.8 r5: 0402 1.9 x 1.0, 0603 3.0 x 1.45, 0805
3.4 x 1.8, 1206 4.75 x 2.3, 1210 4.75 x 3.2, SMA 6.6 x 3.1 mm). IC courtyards for the new parts are estimates of this plan. Table 3.5
gives the result.

| Item | Area (mm²) | Source |
|---|---|---|
| Round-3 CR, r6 | 1082 | [WD] H.22(k) |
| Deleted: J101, R130-R132, R176/R177 | -63 | §1.12.2 |
| Power stage, fitted | +219 | §2.5.4 |
| Power stage, DNP footprints (R507/C505, R510/C507, R541/C541) | +44 | §2.5.4 |
| Ex-EIB stages (U401-U404, Q401-Q403, 26 x 0603) | +196 | §2.5.5 |
| TS / PROG / /INT passives, new test points | +54 | §2.5.5, §2.5.10 |
| **CCB total** | **1532** | [LC] §6 |
| Not booked in [LC] §6: DNP filter footprints C336, C337, C453 (3 x 0603; about 6 mm² as 0402) | +13 | §2.5.5, §2.5.6 |
| CCB total with the filter footprints | 1545 | This table |
| Usable: CR top 881 + tab 120; CR bottom 591 + tab 120 - 199 reserved under the cell (3.4.4) | 1514 | [WD] H.18; [LC] §6 |
| Reserved on the top side: the L-12 battery-path corridor, x 22.4-25.4, y 42.13-50.4 | -25 | 3.3.3 item 4 |
| Usable with the corridor reserved | 1489 | This table |

The utilisation is 101 %, against 74 % for the round-3 CR. With the corridor reserved on the top side, it is 103 %.
The filter footprints C336, C337 and C453 raise these figures to 102 % and 104 % (1545 / 1514 and 1545 / 1489). After
the remedies of Table 3.6, with the filter footprints in 0402, the range is 79-86 % (80-87 % with the corridor). The
bottom share of the corridor lies mostly under the MB VCHG pour, where §1.3.5 already bars underside parts. Whether the
591 mm² bottom figure already excludes it is TODO(verify: [WD] H.18). The plan as drawn therefore does not fit. Table 3.6
lists the remedies in order of preference.

| Step | Remedy | Utilisation after the step (without / with the corridor reserved) | Cost |
|---|---|---|---|
| 1 | Change the 96 fitted logic 0603 passives (§2.5.5-2.5.7, scripted count) to 0402; keep 0.1 % divider parts in their rated size | 86 % / 87 % | Hand rework harder; 0.1 % range in 0402 TODO(verify: Vishay TNPW0402) |
| 2 | Use rect A' (x 38.9-48.7, y 67.14-76.40, +86 mm², passives only) | 81 % / 82 % | Requires H_u >= 2.75 mm (§1.3.2) |
| 3 | Omit the three DNP power-stage snubber footprints | 78 % / 80 % | No footprint for a snubber if T-B tests show ringing |
| 4 | Omit the DNP option groups (FCI_OK U317 set, keep-alive U312 set) | about 74 % (not computed in [LC]) | Operator decision; reverses round-3 options |

A utilisation near 75-80 % is the round-3 level. The gate is the courtyard DRC of the capture. TODO(verify: T-A-06 class
placement DRC on the CCB outline). Table 3.5 books area only. The separation classes of 3.6.1 also restrict where the
parts may sit: the 10 mm class needs the bottom side (L-13). The most congested region is x 33-41, y 56-67. There the
PMID bulk row, the VCHGOUT run with C511/C512 and the U301 output side meet.

### 3.3 Header pins: current, parallel pins and copper (I)

#### 3.3.1 Current per pin

Only six of the 22 header pins carry power, because the 11 anchor pads are isolated on the MB (§2.5.2, §1.13.2 item 5).
Table 3.7 gives the currents; the 60/40 sharing assumption between paired pins is from [WD] A.8 r6.

| Pins | Net | Parallel pins | Current | Basis |
|---|---|---|---|---|
| 10 | VCHGIN | 1 | <= 1.76 A continuous; <= 2.41 A for <= 202 ms | [WD] H.4, B.4 |
| 4 | GND, input return | 1 | as pin 10 | §1.13.3 |
| 18, 19 | VCHG | 2 | 3.21 A total; 1.93 A / 1.28 A at 60/40 | §1.13.3 |
| 14, 15 | GND, battery return | 2 | as 18/19 | §1.13.3 |

The single VIN+ pin and the single input-return pin are the weakest points. The required rating is >= 3 A for pins 4
and 10 and >= 2.0 A for pins 14, 15, 18 and 19 ([WD] A.8). TODO(verify: Samtec TSW and socket current rating, T-A-05).

#### 3.3.2 Pin self-heating

[LC] §7 estimates the pin body at about 1.6 mΩ (0.64 mm square, 6 mm long, phosphor-bronze resistivity assumed;
TODO(verify: Samtec pin alloy)). At 1.93 A the pin body dissipates about 6 mW. A socket contact adds more: at an assumed
20 mΩ contact the loss is about 74 mW per contact at 1.93 A and 116 mW at 2.41 A. TODO(verify: socket contact resistance).
Each socket contact also adds thermal resistance in series with its pin: 166-417 C/W for an electrical contact resistance
of 2-20 mΩ ([LC] §5.1; §3.7.2). Option K of §1.3.4 therefore needs the contact resistance before its board resistance and
its pin-joint temperature can be predicted. T-F-16 uses an absolute joint-temperature limit on the CCB (§3.7.6).

**Tall pins (r2).** The fan channel sets H_u 5.1-8.1 mm (§1.3.2 rule 3), so each power pin is longer than the r1 6 mm
body. Over the r1 H_u of 2.54 mm, H_u 5 mm and 8 mm add 2.46 mm and 5.46 mm of pin. That is 0.661 mΩ and 1.466 mΩ
per pin (0.269 mΩ per mm, same alloy assumption; [TS] §(a)). The pin body then totals 2.27-3.08 mΩ, and at H_u 12 mm
4.15 mΩ. The extra continuous loss is 2.46-5.46 mW on pin 18 at 1.93 A, and 11.2-24.8 mW over the six power pins at
H_u 5-8 mm (43.0 mW at 12 mm). This is at most 1.6 % of the 2.7 W board loss. The pin body at 1.93 A dissipates
8.5-11.5 mW in total at H_u 5-8 mm. A pin with both ends held at the board temperatures and uniform heating rises at its
midpoint by P x R_th / 8. With R_th 230-335 C/W (k 70 W/mK, [TS] §(a)), the rise is 0.24-0.48 C (calculation of this
subsection). The socket-contact loss of option K stays the larger term. The required pin ratings of §3.3.1 and T-A-05
do not change.

The longer pins also weaken the pin conduction path to the MB: the pin thermal resistance rises from 144 C/W (r1) to
230-335 C/W at H_u 5-8 mm ([TS] §(a)). The forced-air model of §3.7.2a includes this path at the r2 length. The weaker
path matters only in the fan-off case (§3.7.2a item 5).

#### 3.3.3 Copper at the header

1. Connect pins 4, 14, 15, 18 and 19 to their pours on all four layers. Use a solid connection or four spokes of >= 0.5 mm.
   The solid connection is the better heat path into the MB GND and VCHG pours (3.7.4). However, it needs preheat when the
   strips are hand-soldered.
2. Connect pin 10 on L1 only, with VCHGIN copper <= 5 mm to U301 IN/IN_SYS and no exposed test pad ([WD] A.8).
3. Leave the 11 anchor pads unconnected on every layer (§2.5.2).
4. Run the VCHG path from the BAT capacitors to pins 18/19 as a >= 2.5 mm pour on L4, paralleled on L1 wherever the
   SYS capacitor row leaves room. Use >= 5 vias of 0.3 mm at each layer change (3.1.5).
   **Corridor (open, L-12).** The BAT pins sit at about (26, 63) after the rotation of 3.4.5, and pins 18/19 sit at x 21.0,
   y 44.16-46.70, so the path is about 17-20 mm long. Three rules of this plan block every direct route: L4 is the GND
   shield under the whole cell (3.1.1); on L1 the gap between the header keep-out (x 22.33) and L501 (left edge about x 24.65
   at a U501 centre of x 28.2) is about 2.3 mm, below the 2.5 mm width rule; and below y 50.4 the path enters Z-Q. The
   capture must choose one of two options:
   (a) an L1 neck of >= 1.8 mm between the header keep-out and L501 over y 50.4-58.0 (the IPC-2221 minimum at 3.5 A and
   10 C rise is 1.69 mm at 1 oz external, [LC] §1), as a stated exception to the 2.5 mm rule, with L4 paralleled only
   outside the cell (y < 50.4);
   (b) U501 and L501 moved by about +1.3 mm in x (centre about x 29.5), so that a 2.5 mm L1 pour fits beside L501. This
   reduces the U501 courtyard clearance to foot circle 2 from about 0.6 mm to about 0.2 mm (3.4.5).
   In both options, reserve x 22.4-25.4 below y 50.4 for the pour on L1 and L4 and start Z-Q at x 25.4. The MB VCHG pour
   (x 20.14-28.65, y 43.31-49.96, §1.5) lies under the corridor end, so no underside part may sit there (§1.3.5).
5. Join the battery-return GND (pins 14/15) to the cell PGND through the L2 plane and an L1 pour >= 2.5 mm. Keep this
   return outside the divider bottoms of Z-Q ([WD] A.6 r6 rule).

### 3.4 Power-loop placement copied from TI (S)

This section places the power cell of U501 from three TI sources. [DS] §8.4 and Fig 8-21 give the rules and the priority
order. [DS] pp.148-150 give the RQM0029A package, land pattern and stencil (3.4.6). The TIDA-050047 reference design
gives a fabricated 4-layer layout of the same power stage, read from its Gerbers and Altium PCB file (3.4.7; [TIDA],
[TLP]). Subsections 3.4.1-3.4.5 state the CCB plan; subsection 3.4.8 records which TIDA-050047 practices the plan copies.

#### 3.4.1 Priority list

The cell follows [DS] §8.4.1 in its stated priority order, which TI calls "essential". [UG] §3 repeats it. Note that the
labels in [DS] Fig 8-21 do not match the numbered list in rev C; the text governs ([TID] §7 item 9). The order is:

1. C532 (PMID 0.1 µF) and C518 (SYS 0.1 µF), 0402, on L1, against the PMID-GND and SYS-GND pads, no vias in the loop.
2. One PMID 10 µF (C529) and one SYS 10 µF (C519) beside them on L1; the other bulk parts on L1 with wide copper.
3. SW1 and SW2 through vias under U501 to L3, then to L501 ([DS] §8.4.2).
4. C535 (REGN) at pin 5 with a short trace, >= 2 ground vias.
5. C513 (VBUS 0.1 µF) at pins 2/3 with >= 2 ground vias; C511/C512 further away.
6. C538/C539 (BAT) at pins 22/23.
7. BATP and TS away from SW1 and SW2.

TIDA-050047 implements items 1, 2, 3 and 6 as listed. It places the REGN capacitor centre about 3.0 mm from the pin-5
pad and the VBUS 0.1 µF capacitor centre about 1.5 mm from the pin-2/3 pads (Table 3.8b). The CCB keeps the [DS] wording
for items 4 and 5.

#### 3.4.2 Cell sketch (Figure 3.2)

Figure 3.2 shows the cell in cell coordinates, in the TI orientation. The pad positions are the [DS] p.149 land pattern
(3.4.6). The capacitor, via and strip positions are the TIDA-050047 positions of Table 3.8b, with the CCB parts and
values. Positions marked "~" are planning values of this document; the capture sets them.

```
 Figure 3.2  Power cell, cell coordinates (mm), TI orientation: power-pad edge at +y.
 On the CCB the cell is rotated 180 degrees (3.4.5). L1 parts in [ ], L4 parts in { }.

   x:  -11      -8      -5     -2  0  2      5       8      11
 ~+13.5          +------------------------------------+
                 |  L501  1.0 uH  7.1 x 6.5 x 3.0 mm   |  L1, body y ~ +7.0 .. +13.5
                 |  SW1 terminal        SW2 terminal   |  terminals: TODO(verify: TDK drawing)
  ~+7.0          +------------------------------------+  >= 3 vias 0.38 mm per terminal to L3
  ~+6.3   o o o o o  GND vias            GND vias  o o o o o      rows of 5 x 0.25 mm
  ~+5.8 [C531][C530][C529]   GND    [C519][C520][C521] -> C522, C523
         PMID 10 uF 50 V 1210 neck  SYS 10 uF 25 V 0805     bulk vertical: PMID or SYS end
  +3.95               o   o   o                             at y ~+3.4, GND end in the GND pour
                    3 GND vias 0.38 mm in the neck
  +3.15        [C532 0402]   GND   [C518 0402]   horizontal; GND ends at x -0.77 / +0.77
  +2.2  ===== 29 PMID | 28 SW1 | 27 GND | 26 SW2 | 25 SYS =====  power-pad edge (pads y +1.2..+2.2)
  +0.85          o o  SW1 vias           SW2 vias  o o      4 x 0.25 mm per node, under the body,
  +0.30          o o  {C506 at x -1.9}  {C508 at x +1.9} o o  tented; L3 strips start here
  -0.55               ( GND island: 3 x 0.38 mm + 1 x 0.25 mm vias )
         [C513] VBUS 2,3 at y +1.2/+0.8           BAT 22,23 at y +0.8/+1.2 [C538][C539]
         [C535] REGN 5 at y 0                     BATP 18 at y -0.8 -> R515 (100 R)
         BTST1 4 at y +0.4 -> via -> {C506}        BTST2 19 at y -0.4 -> via -> {C508}
  -2.2  ======== control edge: 10 ACDRV2 .. 15 SDA (/CE 13, SCL 14) at y -1.6..-2.2 ========
         VBUS pour (-x) with C511/C512 further out    BAT pour (+x); SDRV 24 -> C536
```

Table 3.8a gives the relative placements that the sketch encodes.

| Item | Placement in cell coordinates | Source |
|---|---|---|
| C532, C518 | 0402, horizontal, centres (-1.27, +3.15) and (+1.28, +3.15); GND terminals inward on a common GND neck at x -0.77..+0.77, PMID and SYS terminals outward on the PMID and SYS pours | TIDA C11, C12 ([TLP] §2) |
| GND neck | L1 copper from pin 27 up between the PMID and SYS pours; 3 vias of 0.381 mm drill at y +3.95, x -0.8, 0, +0.8 | [TLP] §4; render of GTL (Interp.) |
| PMID bulk (C529-C531) | Row of three, vertical, centres y about +4.2, first part at x about -3.2; GND ends in the L1 GND pour above, stitched by a row of five 0.254 mm vias at y +5.75 | TIDA C8-C10 (0603) |
| SYS bulk (C519-C523) | Row of three on L1, vertical, centres y +4.47 from x +3.53; TIDA puts the other two on L4 under the row; GND row of five 0.254 mm vias at y +6.5 | TIDA C13-C17 (0805) |
| SW via groups | Four 0.254 mm vias per node, 2 x 2 at x -1.15/-0.59 (SW1) and +0.58/+1.13 (SW2), y +0.30/+0.85, under the package body, tented | [TLP] §4 |
| GND under the body | L1 island from pin 27 with three 0.381 mm vias at (-0.58, -0.55), (+0.58, -0.55), (0, -1.11) and one 0.254 mm via at (0, -0.16) | [TLP] §4 |
| C506, C508 (BTST) | L4, 0402, vertical, at (-1.9, +0.6) and (+1.9, +0.6), beside the SW via groups | TIDA C1, C7 |
| L501 | L1 on the CCB (TIDA: L4, centre (0, +7.0), pads at x -1.75 and +1.75 with three 0.381 mm vias each) | 3.4.8 item 5 |
| C513, C535 | Left of U501, at pins 2/3 and pin 5, >= 2 ground vias each | [DS] Fig 8-21 "C3", "C7"; TIDA C6 at (-3.70, +0.40), C18 at (-4.27, -2.13) |
| C538, C539 | Right of U501 at pins 22/23 with their own PGND | TIDA C20, C21 at (+4.60, +0.65), (+6.10, +0.65) |

The CCB departs from TIDA-050047 in the part sizes. The PMID bulk parts are 1210 50 V instead of 0603 25 V (Table 2.2
C529-C531), so the left row is about 3 x 3.0 mm wide instead of 3 x 1.4 mm. The VBUS bulk C511/C512 moves out of the
cell to the VCHGOUT run (3.5), which [DS] §8.4.1 item 4 permits ("can be placed further away").

**Fit check of the sketch against zone Z-P (open, L-11).** At the TIDA-050047 pitches (about 2.0 mm for 0805, 3.0 mm for
the CCB 1210 parts), the first bulk rows of Figure 3.2 span about x -10.5 to +8.2 in cell coordinates. With the 180
degree rotation and the U501 centre at x 28.2 (3.4.5), the SYS row maps to about x 20.0-25.2 and the PMID row to about
x 30.2-38.7. The SYS row then overlaps the header-column keep-out x 19.67-22.33 beside pads 12 (y 61.944) and 13 (y 59.404),
and the PMID row passes the Z-P edge x 37.5 into Z-E. The sketch therefore does not fit Z-P as drawn. The capture must
place the bulk capacitors in two-deep arrays inside x 22.4-37.5 (for example the SYS 0805s as 2 + 3 and the PMID 1210s as
2 + 1), with C532/C518 and the nearest 10 µF part of each row kept as in the [DS] §8.4.1 priority order. TIDA-050047 shows a
second remedy for the SYS row: two of its five SYS capacitors sit on L4 under the L1 row. On the CCB this needs underside
clearance for an 0805 part in the cell reserve (§1.3.5, 3.4.4). TODO(verify: §1.3.2 H_u against a 1.25 mm 0805 body).
Both remedies leave the loop-inductance ranking of 3.4.1 unchanged but lengthen the far-row connections; the area effect
enters L-1.

#### 3.4.3 SW1 and SW2 routing on L3

1. Use **four vias of 0.254 mm drill (0.508 mm land) per SW node**, as a 2 x 2 group under the package body at the
   positions of Table 3.8a ([TLP] §4). No via sits in a pad (3.4.6). Join the SW pad to its group on L1 with a 0.254 mm
   trace from the inner pad end (TIDA practice, Interp. of the GTL render).
2. Use three vias of 0.381 mm drill (0.762 mm land) at each L501 terminal, as TIDA-050047 does at its inductor pads.
3. Run each strip on L3 at about 1.1 mm width from the via group to y about +2.6, then at 0.76 mm or wider to the L501
   via column (TIDA-050047 dimensions at 2 oz, Interp. of the G2 render). At 1 oz inner copper (ST1) double these widths to
   keep the TIDA sheet resistance: about 2.2 mm and 1.5 mm. The Table 3.3 rule of 1.5-2.5 mm meets this; ST2 meets it at the
   TIDA widths.
4. Surround the strips with an L3 GND pour at the 0.254 mm polygon clearance of TIDA-050047 ([TLP] §6, Clearance_Poly 10
   mil). Leave L3 empty between the two strips under L501, as TIDA does. Stitch the L3 GND pour to L2/L4 every <= 3 mm.
5. Keep L2 solid GND over the strips. Void L2 only under the L501 terminal footprint, as TIDA-050047 voids L1 and L2 over
   its bottom-side inductor footprint ([TLP] §5, G1 void x -2.45..+2.40, y +5.45..+8.55). The antipads of the two SW via
   groups also merge into one L2 clearance of about 3.3 x 1.6 mm under the body (x -1.69..+1.64, y -0.22..+1.37). Keep L4
   solid GND under the strips (3.1.1).
6. Keep >= 0.15 mm between an SW via land and any pad of another net. TIDA-050047 holds 0.154-0.221 mm from its SW via
   lands to the SYS, PMID, VBUS, BTST1, /INT and PROG pads ([TLP] §4). Its central 0.381 mm GND via sits 0.121 mm from the
   /CE and /QON pads; the CCB may copy that or move the via 0.03 mm toward +y.

#### 3.4.4 Bottom side under the cell

Only C506 and C508 (0402, about 0.5 mm tall) sit on L4 under U501, beside the SW via groups (Table 3.8a). Their SW-side
pads and the L4 lands of the SW vias are the only switch-node copper on the underside. A 0.5 mm² pad 2.54 mm above an MB
trace couples about 2 fF (ε0 A / d), which is negligible. The position under U501 is outside the MB bottom keep-out
(x 24.5-36.0, y 48.5-53.5) and outside the MB power-copper shadows (§1.3.5). No other bottom part is placed in the reserved
area (x 22.4-36.0, y 52.8-67.4, the 199 mm² of 3.2.3), unless the SYS-row remedy of 3.4.2 is chosen.

Note that UG §3 item 3 also permits BTST capacitors on L1 with a via on one side. That alternative removes the underside
switch-node pads. It is the fallback if the BTST loop on L1 fits. TIDA-050047 uses the L4 position.

#### 3.4.5 Orientation on the CCB

U501 is rotated **180 degrees** from Figure 3.2, with its centre at about (28.2, 65.0). TIDA-050047 also places U1 at 180
degrees, with the power edge toward its inductor ([TLP] §2). Table 3.8 gives the result on the CCB.

| Side of U501 on the CCB | Pins ([DS] Fig 5-1) | What it faces | Why this is correct |
|---|---|---|---|
| -y (toward the logic zone) | Power edge 25-29 at y about 62.8; L501 below it, y about 51.5-58.0 (body edge about 4.8 mm from the power edge, Figure 3.2) | Z-Q at y <= 50.4 | Switch nodes face away from the tab and the control pins |
| +x (toward the eFuse) | 1 STAT, 2/3 VBUS, 4 BTST1, 5 REGN, 8/9 VAC | Z-E, U301 at x 41.8 | Shortest VCHGOUT run; PMID bulk row on the +x side |
| -x (toward pins 13-19) | 22/23 BAT, 24 SDRV, 18 BATP, 17 ILIM_HIZ, 16 TS | Pins 18/19 (VBAT+), 13 (THERM) | Shortest battery path; TS_EXT short |
| +y (toward the tab) | 10-15 (/CE 13, SCL 14, SDA 15) | Z-C | Control network beside its pins, away from SW |

The other orientations fail. The TI orientation puts VBUS on the -x side, away from the eFuse, and BAT on the +x side, away
from pins 18/19. A 90 degree rotation points the inductor at either the eFuse and the LM1084 side or the header column.

The courtyard of U501 (about 4.9 mm square) clears foot circle 1 by about 1.1 mm and foot circle 2 by about 0.6 mm at
this centre. TODO(verify: capture DRC).

#### 3.4.6 RQM0029A land pattern and stencil ([DS] pp.148-150)

The package drawing RQM0029A (4225253/A, 11/2019) has **29 pins and 33 lead segments**. Pins 1, 9, 16 and 24 are
L-shaped corner leads, each counted as two segments of the "33X" callout ([DS] p.148). The land pattern therefore has 29
copper pads, four of them L-shaped. All land-pattern dimensions on [DS] p.149 are reference values in parentheses.

Table 3.8c gives the pad-to-pin map in cell coordinates (top view, power edge at +y, pin 1 at the upper left). Pin names
are those of [DS] Table 5-1.

| Pins | Edge | Pad (x by y, mm) | Centres (mm) | Pitch |
|---|---|---|---|---|
| 29 PMID | Power, +y | 0.20 x 0.95, y +1.25..+2.20 | x -0.90 | 0.45 mm |
| 28 SW1, 27 GND, 26 SW2, 25 SYS | Power, +y | 0.20 x 1.00, y +1.20..+2.20 | x -0.45, 0, +0.45, +0.90 | 0.45 mm |
| 1 STAT, 24 SDRV | Corners, +y | L: leg 0.95 x 0.20 at y +1.60 (x -2.20..-1.25, mirrored for 24) plus leg 0.20 x 0.70 at x -1.35 / +1.35 up to y +2.20 | - | - |
| 2 VBUS, 3 VBUS, 4 BTST1, 5 REGN, 6 D+, 7 D-, 8 VAC2 | Left, -x | 0.60 x 0.20, x -2.20..-1.60 | y +1.2, +0.8, +0.4, 0, -0.4, -0.8, -1.2 | 0.40 mm |
| 23 BAT, 22 BAT, 21 /INT, 20 PROG | Right, +x | 0.60 x 0.20, x +1.60..+2.20 | y +1.2, +0.8, +0.4, 0 | 0.40 mm |
| 19 BTST2, 18 BATP, 17 ILIM_HIZ | Right, +x | 0.68, 0.65 and 0.70 x 0.20, outer edge x +2.20 | y -0.4, -0.8, -1.2 | 0.40 mm |
| 9 VAC1, 16 TS | Corners, -y | L: leg 0.90 x 0.20 at y -1.60 (x -2.20..-1.30, mirrored for 16) plus leg 0.20 x 0.70 at x -1.40 / +1.40 down to y -2.20 | - | - |
| 10 ACDRV2, 11 ACDRV1, 12 /QON, 13 /CE, 14 SCL, 15 SDA | Control, -y | 0.20 x 0.60, y -2.20..-1.60 | x -1.0, -0.6, -0.2, +0.2, +0.6, +1.0 | 0.40 mm |

The common rules of the land pattern are:

1. Pad width 0.20 mm on all 33 segments, corner radius 0.05 mm, overall copper extent 4.40 x 4.40 mm ([DS] p.149).
2. Copper gap 0.20 mm between side and control pads at 0.40 mm pitch, and 0.25 mm between power pads at 0.45 mm pitch.
3. Non-solder-mask-defined pads are preferred, with a mask expansion of 0.05 mm maximum all round ([DS] p.149 detail).
   The solder-mask web between 0.4 mm-pitch pads is then 0.10 mm. [DS] p.149 note 4 states that the mask tolerance
   depends on the fab.
4. The land pattern has no thermal pad and no via in any pad. [DS] p.149 shows no via positions.
5. The stencil apertures are equal to the pads in size and position, for a 0.1 mm thick stencil ([DS] p.150). Note 5
   permits trapezoidal walls and rounded corners for paste release.

TIDA-050047 draws this land pattern exactly. Its Top Layer pads deviate from Table 3.8c by at most 0.0006 mm in centre and
size ([TLP] §3). Its mask openings are the pads plus 0.05 mm all round (0.30 x 0.70 mm for a 0.20 x 0.60 mm pad), its
paste openings equal the pads, and its under-body vias are tented ([TLP] §3). This confirms the reading of [DS] p.149
and p.150 above. The shorter PMID pad (0.95 mm) keeps 0.175 mm between pin 29 and the land of the nearest SW1 via
([TLP] §4).

#### 3.4.7 The TIDA-050047 power stage as built ([TIDA], [TLP])

TIDA-050047 (TIDUEY1C) is a USB Type-C PD sink and source with a BQ2579x charger for 2- to 4-cell packs and a 5-20 V input
([TIDA] TIDUEY1C p.1). Its Altium project TIDM752 REV_A1 (2020) holds the PCB file, the Gerbers and the drill file. The
assembly drawings TIDM750 and the layer plots TIDM751 carry the same board number BMS046, revision A1, in their title blocks.

The schematic library part of REV_A1 is BQ25792RQM, while the TIDM749 BOM and the TIDM748 schematic name BQ25798RQM. The
two parts are interchangeable on this layout for three reasons:

1. The 29 pin numbers and names of the BQ25792RQM library part equal [DS] Table 5-1 ([TLP] §5b).
2. One EVM board, BMS034, carries either the BQ25792 or the BQ25798 ([UG] §1, Figs 4-5 and 4-6).
3. TIDUEY1C rev C (June 2025) changed the schematic from BQ25792 to BQ25798 ([TIDA] TIDUEY1C p.20), while the published
   layout files remain REV_A1 of 2020.

The electrical differences between the two ICs are outside the scope of this layout section. TODO(verify: BQ25792 data
sheet SLUSDG1, only if a TIDA value is reused in §2).

Table 3.8b lists the facts that the CCB plan uses. Positions are in cell coordinates; "Interp." marks a reading of a
render made from the Gerbers by [TLP].

| Item | TIDA-050047 (REV_A1) | Source |
|---|---|---|
| Layer stack | Four layers, all 2.80 mil (71 µm, 2 oz) copper; L1-L2 prepreg 12 mil (0.305 mm), L2-L3 core 26 mil (0.660 mm), L3-L4 prepreg 12 mil (0.305 mm), FR-4 High Tg, εr 4.2; solder resist 0.40 mil | PcbDoc layer records; GM12 stack-up ([TLP] §1) |
| Board | 62 mil (1.6 mm) +/- 10 %, IPC-6012 type 3 class 2, PTH copper 20-30 µm, ENIG, IPC-A-600F class 2, bare-board test; via fill not specified | GM10 fab notes |
| Rules | Fab notes: minimum track 8 mil, minimum clearance 0.2 mm, minimum via pad 24 mil, annular ring 0.05 mm. Rule export: width 6 mil, clearance 5 mil, polygon clearance 10 mil, mask expansion 1.97 mil | GM10; `.RUL` ([TLP] §6) |
| Drawn minimum | 0.152 mm (6 mil) traces on L1, L3 and L4, below the 8 mil fab note; via lands 0.508 mm (20 mil), below the 24 mil fab note | [TLP] §4, §5 |
| Drills | 0.254 mm (448 holes) is the via size; 0.381 mm (12 holes) for the power vias; 0.2 mm (10) and 0.3 mm (24) elsewhere on the board; lands 0.508 mm and 0.762 mm | Drill file and `.DRR` ([TLP] §4) |
| U1 | RQM0029A-MFG, L1, rotated 180 degrees; land pattern = [DS] p.149 | [TLP] §2, §3 |
| Layer use in the cell | L1: pads, 0.1 µF and bulk capacitors, PMID and SYS pours, GND neck and pours. L2: solid GND, voided under the inductor footprint and around the SW via groups. L3: SW1 and SW2 strips in a GND pour. L4: inductor, BTST capacitors, GND pour | Renders of GTL, G1, G2, GBL (Interp.) |
| SW connection | Pad -> 0.254 mm L1 trace -> four 0.254 mm vias under the body -> L3 strip about 1.1 mm wide, then 0.76 mm, about 7 mm long -> three 0.381 mm vias -> inductor pad on L4 | [TLP] §4, §5 (widths Interp.) |
| Inductor L1 | Vishay IHLP2020BZER1R0M11, 1.0 µH, 7 A, 0.0181 Ω, 5.49 x 5.18 x 2.0 mm, on L4 at (0, +7.0) | BOM `.xlsx`; [TLP] §2 |
| PMID, SYS 0.1 µF (C11, C12) | 0402 50 V X7R, L1 at (-1.27, +3.15) and (+1.28, +3.15) | BOM; [TLP] §2 |
| PMID bulk (C8-C10) | 3 x 10 µF 25 V X5R 0603, L1, y +4.17, x -3.15, -4.55, -5.92 | BOM; [TLP] §2 |
| SYS bulk (C13-C17) | 5 x 10 µF 25 V X5R 0805: C13-C15 on L1 at y +4.47; C16, C17 on L4 at y +4.48 | BOM; [TLP] §2 |
| BTST (C1, C7) | 47 nF 25 V 0402, L4, (-1.92, +0.60) and (+1.88, +0.60) | BOM; [TLP] §2 |
| REGN (C18) | 4.7 µF 16 V 0603, L1, (-4.27, -2.13) | BOM; [TLP] §2 |
| VBUS (C6; C2-C5) | 0.1 µF 0402 at (-3.70, +0.40); 10 µF 0603 row at y +0.10, x -4.92 to -9.02 (C2, C3 marked DNP in TIDM748) | BOM; [TLP] §2 |
| BAT (C19; C20, C21) | 0.1 µF 0402 at (+3.35, +0.75); 2 x 10 µF 0603 at (+4.60, +0.65) and (+6.10, +0.65) | BOM; [TLP] §2 |
| SDRV, BATP | C22 1 nF on L4 at (+3.38, +0.95); R1 100 Ω on L4 at (+7.85, +0.60) | BOM; [TLP] §2 |
| Ground split | Net tie NT1 between GND and AGND on L3 at (0, -2.41), under the control edge | TIDM748; [TLP] §2 |

#### 3.4.8 Practices copied from TIDA-050047 and differences that matter

The TIDA-050047 application differs from the CCB in four respects. Its input is USB PD at 5-20 V, against VCHGOUT up to
22.28 V on the CCB. It charges 2- to 4-cell packs and runs reverse (OTG) mode, which the CCB does not use. Its PMID parts
are 25 V, against the 50 V rule of §2.1.4. Its board is not mounted over another board, so its underside is free.

The CCB copies the following practices:

1. **Land pattern and stencil** exactly as Table 3.8c and [DS] pp.149-150, with 0.05 mm mask expansion and 1:1 paste
   apertures in a 0.1 mm stencil. TIDA-050047 confirms this geometry in a fabricated board.
2. **No via-in-pad.** The SW and GND vias sit under the package body between the pad rows, tented and unfilled (3.4.3 item
   1; 3.1.5 rule 4). The CCB therefore needs no filled-and-capped via-in-pad.
3. **0.1 µF orientation.** C532 and C518 lie horizontal about 0.95 mm above the power edge, with their GND ends on a GND
   neck from pin 27 (Table 3.8a).
4. **SW routing** on L3 between a solid L2 and a solid L4 GND, with 4 vias at the IC and 3 at each inductor terminal
   (3.4.3; L4 under the strips read as GND pour, Interp.). TIDA-050047 has the layer order planned for the CCB: L3 sits
   0.305 mm above L4 and 0.660 mm below L2.
5. **Inductor side: not copied.** TIDA-050047 puts its 2.0 mm tall inductor on L4. The CCB underside faces the MB within the
   header gap of §1.3, so L501 (3.0 mm) stays on L1 above the bulk rows. The L3 strips then run about 1-3 mm longer than
   in TIDA-050047. TODO(verify: TDK SPM6530T terminal positions, L-4).
6. **Copper weight.** TIDA-050047 uses 2 oz on all layers with the 0.2 mm gaps of this land pattern. This removes the
   etch argument against 2 oz outer copper only as far as the chosen fab confirms it (3.1.3, L-2).
7. **AGND net tie: optional.** TIDA-050047 separates AGND from power GND with one net tie under the control edge. The CCB
   keeps one GND net (§1.13.1); the net tie is a capture option only. TODO(decision: schematic owner).

Two TIDA-050047 placements are looser than [DS] §8.4.1 items 4 and 5: the REGN capacitor centre sits about 3.0 mm and the
VBUS 0.1 µF centre about 1.5 mm from their pads. The CCB keeps the tighter [DS] wording.

### 3.5 Input path and eFuse (I)

1. Keep the [WD] A.8 placement of U301, its +x pocket and the IN-side parts (C302a/b/c, D307, R302), with the r5
   loop-inductance rules. These parts are upstream of the charger and do not change (§1.11.2 item 4).
2. Replace the round-3 OUT strip (C103/D103 toward W1) with a VCHGOUT pour >= 1.5 mm on L1 from U301 OUT (pins 17/18)
   to the U501 VBUS pins. Place C303 within 3 mm of OUT ([WD] A.8 rule kept) and C511/C512 along the run.
3. Place D303 (SMA) at the U301 OUT end. If the corridor of 3.2.3 is full, put D303 and C541/R541 in rect A' (step 2 of
   Table 3.6).
4. Return R301, R304, R305 and C301 to the U301 GND pin and thermal pad locally. IMON (R305) references the eFuse ground.
5. Tie the U301 thermal pad to L2 with >= 9 vias (§2.5.3). At 1.76 A and 31 mΩ the eFuse dissipates about 96 mW
   ([LC] §4; RON from [WD] B.4 device row).

### 3.6 Separation of the analog and logic parts from the switch nodes (I, with S distances)

#### 3.6.1 Zoning and distances

Table 3.9 gives the separation rules. The distances are planning values; no TI or round-3 source gives a number.
TODO(measure: plane noise at the U302/U303 divider bottoms during switching, T-C-07 / S4-n class, §1.13.4 item 3).

Every distance of Table 3.9 is measured in plan view from the **SW envelope (E-SW)**. E-SW is the union of the rectangles
of Table 3.9a, in MB coordinates after the rotation of 3.4.5. All SW1 and SW2 copper on every layer stays inside E-SW.

| Part of E-SW | Extent (MB mm) | Derivation |
|---|---|---|
| L501 body, terminals and terminal vias | x 24.65-31.75, y 51.5-58.0 | Cell body y +7.0 to +13.5, 7.1 mm wide (Table 3.8a, Figure 3.2), rotated about (28.2, 65.0). The terminal positions and the land-pattern extent are TODO(verify: TDK SPM6530T drawing, L-4); the land pattern must stay inside the body outline |
| L3 SW1 and SW2 strips, U501 SW pads and via groups, C506/C508 SW-side pads (L4) | x 24.65-31.75, y 58.0-65.35 | Strips from the via groups to the L501 terminal vias (3.4.3 items 1-4). Pads 26 and 28 at cell y +1.2 to +2.2 (Table 3.8c); via lands x 26.82-29.60, y 63.90-64.95; C506/C508 union x 25.80-30.60, y 63.45-65.35 ([LC] §5) |
| SW snubber footprints R507/C505, R510/C507 (DNP, D10) | Inside the two rectangles above, or omitted | Rule 4 below |

Table 3.9 lists the victim classes and their distances from E-SW.

| Victim class | Members | Minimum distance from E-SW, and qualifying region (Table 3.9b) | Layer of the sensitive trace |
|---|---|---|---|
| MΩ nodes | N_H1P/N_H1M (R313 6.49 MΩ), N_UVP (R316 10 MΩ), N_BBM (R319 10 MΩ), N_FOM (R387 3.3 MΩ), N_ISP (R459 10 MΩ), N_CSP (R462/R463 1 MΩ, 506 kΩ Thevenin, unfiltered unless C453 is fitted), N_FNP and N_RNP (R388-R391 453 kΩ / 1 MΩ, 312 kΩ Thevenin, unfiltered unless C336/C337 are fitted), N_BAL (R379 1 MΩ) | **>= 10 mm**; Q10-T, Q10-D (U403/U404 nodes N_ISP and N_CSP only) or Q10-B | L1 only (L4 in Q10-B), <= 5 mm long, over an unbroken GND layer (L2; under Q10-B, an L3 GND fill without traces) |
| Comparator references and 0.1 % dividers | REF3xx, R309-R316, R340-R343 | >= 10 mm and x <= 43.7; Q10-T or Q10-B | L1 (L4 in Q10-B) |
| Logic gates and monostables | U305-U323, U311/U313 timing nodes N_CX/N_RC | >= 5 mm; Q5 | L1/L3; timing nodes L1 only |
| Charger control pins | ILIM_HIZ, TS, /CE, PROG, BATP | Leave U501 on the control or -x side (3.4.5); never cross the cell | L1 at the pin; L3 outside the cell |
| Taps | F01-F24 | Pads fixed at the [WD] A.8 positions; every tap trace >= 10 mm (rule 3) | L1 pads; routing L1/L3 |

Table 3.9b names the regions that meet each distance. The boundaries follow from the E-SW corner at (31.75, 51.5).

| Region | Side | Extent (MB mm) | Area that qualifies |
|---|---|---|---|
| Q10-T | Top | Z-Q at x >= 31.75 + sqrt(100 - (51.5 - y)²): x >= 35.24 at y 42.13, x >= 40.68 at y 47.0, x >= 41.69 at y 50.4 | 32.7 mm² up to x 43.7; 40.2 mm² up to x 44.6 (of 151.3 mm² of top Z-Q up to x 43.7) |
| Q10-D | Top | Z-D at x >= 41.75 | 21.9 mm² up to x 43.7, shared with U401-U404, R458-R463, R467-R470 and C401-C404 |
| Q10-B | Bottom | y <= 41.5, under Z-T, outside the §1.3.5 keep-outs | TODO(verify: capture DRC, L-13) |
| Q5 | Top | Z-Q at y <= 46.5; above y 46.5, x >= 31.75 + sqrt(25 - (51.5 - y)²): x >= 33.93 at y 47.0, x >= 36.63 at y 50.4. All of Z-D | 112.4 mm² of top Z-Q up to x 43.7; 69.4 mm² of Z-D up to x 43.7 |

The areas come from a 0.01 mm grid over the Table 3.4 zones. Option (b) of 3.3.3 item 4 moves E-SW by +1.3 mm in x. Q10-T
then falls to 22.0 mm² and Q10-D to 7.3 mm² (x >= 43.05). Q10-B does not change, because its bound is in y only.

The rules below apply Table 3.9 at capture.

1. Measure each distance from the nearest E-SW edge to the nearest copper of the victim net, on any layer.
2. Place the 10 mm class in Q10-T first, then in Q10-B. The 12 parts R309-R316 and R340-R343 stay 0603 (Table 3.6 step
   1) and need 12 x 4.35 = 52.2 mm² of courtyard. Q10-T holds 32.7 mm², so at least 19.5 mm² goes to Q10-B, before
   REF3xx and the MΩ-node parts. Put the U403/U404 MΩ nodes in Q10-D or Q10-B.
   The DNP filter footprints C336 (N_FNP), C337 (N_RNP) and C453 (N_CSP) belong to the MΩ-node class, because each sits
   on its node. They add 3 x 4.35 = 13.05 mm² to the 10 mm class: C336 and C337 in Q10-T or Q10-B, C453 in Q10-D or
   Q10-B.
3. **Taps.** Keep the tap pads at the [WD] A.8 positions, because the MB rework is fixed. The nearest pads of the rows at
   y 35.80, 38.34 and 40.88 are 15.70, 13.16 and 10.62 mm from E-SW. Ten of the 24 pads are 15 mm or more from E-SW: the
   y 35.80 row and the pads at (39.14, 38.34) and (41.68, 38.34). Route each tap trace >= 10 mm from E-SW over its full
   length, on L1 or L3 over unbroken L2. Leave each pad in -y or +x, toward its divider-top part in Q10-T or Q10-B.
   TODO(measure: tap-node noise, T-K-09).
4. **Snubbers.** Place R507/C505 and R510/C507 inside E-SW. Figure 3.2 leaves about 0.4 mm between the L501 body and the
   PMID bulk courtyards (1210, cell centre (-3.2, +4.2), Table 3.8a), so no place is free as drawn. If the two-deep bulk
   arrays of 3.4.2 do not free a place inside E-SW, omit the footprints (Table 3.6 step 3; operator decision, L-13). A
   placement beside the L501 +x end (x 31.75-34.75, y 52.0-58.0) removes all of Q10-D and reduces Q10-T to 13.1 mm².
5. **Gate.** The capture DRC of T-A-06 checks every distance of Table 3.9 against the captured E-SW. When the capture
   puts SW copper outside Table 3.9a, recompute Table 3.9b before the order.

#### 3.6.2 Charger control network (S)

1. Place every part with a terminal on ILIM_HIZ (R523, R456, C452, R457, R455, Q401 drain) within 5 mm of pin 17. Put C452
   closest: at 1.5 MHz its 2.2 nF is about 48 Ω, which holds the node against coupling.
2. Run the U403 sense trace (R458) from the pin-17 pad on its own trace, and the U404 sense trace (R462) from the pin-13
   pad on its own trace (§2.2.2 rule 4).
3. Give R472 and R472b separate pads and separate vias to REGN (§2.2.2 rule 3).
4. Put no part with one end on REGN and the other on ILIM_HIZ, and no part between /CE and GND except U401 1Y and the
   R462/R463 chain (§2.2.2 rules 1, 2). A footprint review checks both rules.
5. If Q401-Q403 sit in Z-D, their gate nets travel to Z-C. The gate pull-ups R452/R454/R471 then sit at the FETs, so the
   long trace is the driven, low-impedance driver output.
6. Return R523, R456, C452, R524, R525, R529 and the U403/U404 divider bottoms to L2 through their own vias in Z-C, away
   from the PGND pours ([UG] §3 item 7; §1.13.2 item 4).

#### 3.6.3 Ground plane continuity

1. Keep L2 continuous under Z-Q, Z-D, Z-T and Z-C. The only L2 void is the L501 terminal-footprint void inside the cell
   (3.4.3 item 5).
2. Route no L3 or L4 trace across the L2 void outline.
3. On L3, separate the cell from the routing channels by a GND guard pour >= 1.0 mm wide, stitched every <= 3 mm. Keep
   >= 2.0 mm between SW copper and any other L3 signal.
4. Keep the power returns of the cell (PGND, the C511/C512 and C302 grounds) out of Z-Q. The battery return reaches pins
   14/15 along the -x edge; the input return reaches pin 4 through the plane under Z-E and Z-D, not under Z-Q.

#### 3.6.4 Kelvin and sense routing

| Sense | Rule | Source |
|---|---|---|
| BATP | R515 within 2 mm of pin 18; the BATP trace starts at the pin-22/23 pad, not on the VCHG pour after C538; <= 4 mm; L1 on the -x side of U501 | decision D8 (§2.1.1); [DS] §8.4.1 item 7 |
| T9 Kelvin (BT_OK reference) | F10 -> R342 bottom on its own L1 trace; R343 (100 Ω) to L2 at one quiet via; U304, R340-R344 beside F09/F10 at the low-y edge | [WD] A.6; §2.5.6 |
| BT_CURR (F09), FC_CURR (F23) | Inputs to U304 / U317 directly from the tap pads, L1, <= 10 mm | §2.5.6 |
| TS / TS_EXT | Pin 13 -> R526 -> pin 16 along the -x edge, on L3 in the left channel, >= 2.0 mm from the SW2 strip | [DS] §8.4.1 item 7 |
| IMON | R305 at U301, its ground at U301; R329/C329 beside F18 | §2.5.3 |
| H1/UVB dividers | Divider bottoms on L2 in Z-Q at a via shared with no power return | [WD] A.6 |

### 3.7 Thermal path (M)

#### 3.7.1 Loss estimate (S numbers)

[LC] §4 derives the losses from readings of [DS] Fig 6-4 (1.5 MHz) and Fig 6-3 (750 kHz), VBAT 8 V, PFM disabled. The
curves include the inductor (the measurement used the SPM6530T, [DS] §6.7). The readings carry about +/-1 percentage point.

| Case | Efficiency (read) | P_out | P_loss (charger + inductor) | I_in |
|---|---|---|---|---|
| 1.5 MHz, VBUS 20 V, ICHG 3.10 A | 90.7 % | 24.8 W | **2.54 W** | 1.37 A |
| 1.5 MHz, VBUS 15 V, ICHG 3.10 A | 92.8 % | 24.8 W | 1.92 W | 1.78 A |
| 1.5 MHz, VBUS 20 V, ICHG 2.50 A | 91.2 % | 20.0 W | 1.93 W | 1.10 A |
| 750 kHz, VBUS 20 V, ICHG 3.10 A | 92.4 % | 24.8 W | 2.04 W | 1.34 A |

The curves stop at VBUS 20 V, and V-MOT reaches 21.2-21.5 V. The loss at 21.5-22.3 V is TODO(measure: rev-A bench
efficiency). The 15 V row at 3.10 A is not an operating point. Regen charging runs at VINDPM 18.2-19.0 V, and in FC
mode the hardware clamp limits the input to 0.65-0.95 A (§2.1.3; [WD] H.4). The 20 V rows are the design cases.

[LC] §4 splits the 20 V / 3.10 A case with the typical RDS(on) values ([DS] EC pp.14-15: RSNS 8, Q1 24, Q2 35, Q4 17,
BATFET 11 mΩ). Q4 conducts all the time in buck mode. This split is a calculation of this plan, not a TI figure.

| Element | Loss at 25 C | At 100 C (RDS(on) x 1.3, assumed) |
|---|---|---|
| Q1, Q2, Q4, RSNS, BATFET conduction | 0.62 W | 0.80 W |
| L501 DCR 7.8 mΩ ([UG] Table 4-1), I_L rms 3.35 A | 0.08 W | 0.11 W |
| Residual: switching, gate drive, core loss, capacitor ESR | - | about 1.6 W |
| **Total (from the curve)** | | **2.54 W** |

The IC therefore carries about 2.3 W of the 2.54 W, and L501 about 0.1 W plus its core loss. TODO(verify: TDK SPM6530T core
loss at 1.5 MHz, 3.3 A peak-to-peak). Add the eFuse (0.06-0.10 W) and the logic (estimated < 0.05 W): the CCB dissipates
about **2.7 W** at the regen operating point.

#### 3.7.2 Lumped board model

This subsection is the r1 still-air model. In r2 it is the fan-off record at the r1 gap of 2.415 mm, and §3.7.2a gives
the forced-air model of the design case (operator statement, 2026-11-10). [LC] §5.1-5.9 gives an order-of-magnitude model. Its parameters are general values, not data for this board. [LC] §5.0
keeps the superseded model, which credited all six pins with copper on both boards and held the MB at a fixed
temperature.

The model uses these terms:

- **T_MB,0**: the MB surface temperature under the cell (x 25-35, y 55-75), with the Ag105 fitted and idle and no CCB.
  T-K-02 measures it (M12).
- **P_MB**: the part of the CCB loss that enters the MB through the pins, the air layer and the gap pad.
- **R_MB**: the resistance from the MB under the cell to the ambient, for the heat P_MB.
- **T_MB,local**: the MB surface temperature under the cell with the CCB dissipating. It is computed as
  T_MB,local = T_MB,0 + P_MB x R_MB, because it cannot be measured before the CCB is built.

The heat leaves the CCB by three paths:

- Top-side convection and radiation, h = 10 W/m²K over 1219 mm² (§1.8): R_top = 82 C/W.
- Conduction across the closed air layer of H_u - 0.125 mm (the polyimide sheet) to the MB: 2.415 mm and 76 C/W for
  option S, 5.415 mm and about 171 C/W for option K at h_k = 3.0 mm. The layer is heated from above, so it stays
  conduction-only. When a gap pad is fitted, the air area excludes the pad area.
- Six header pins (4, 10, 14, 15, 18, 19), 0.64 mm square, k = 70-110 W/mK, over a path of H_u + 1.6 mm: 4.14 mm for
  option S, 7.14 mm for option K at h_k = 3.0 mm.

The MB landings of the six pins differ ([LC] §5.1, from the [MECH] board file):

1. Pins 4, 14 and 15 land on GND pads that are solid to both MB GND pours.
2. Pin 10 lands at the end of the 1.524 mm 1 oz VCHG-IN trace, which conducts 48 C/W per mm along its length. Its path to
   the bottom GND pour adds a fin resistance of 282 C/W.
3. Pins 18 and 19 land on the VCHG top pour (x 20.14-28.65, y 43.31-49.96, 56.6 mm²), which is isolated from GND. The pour
   reaches the bottom GND through 1.5 mm of FR-4, which adds 61-88 C/W shared by both pins.

With these landings the six pins give 22.4-34.1 C/W for option S ([LC] §5.2). The pins still carry the largest share of
the heat, because the top surface and the air layer give 82 and 76 C/W. With the MB held fixed, the parallel result for
option S is **R_board = 14.3-18.3 C/W**.

For option K, each socket contact adds 166-417 C/W in series with its pin ([LC] §5.1). This is a Wiedemann-Franz estimate
on an electrical contact resistance of 2-20 mΩ, bypassed by a 0.05 mm air film over the engagement length.
TODO(verify: socket datasheet, contact resistance and engagement length). At h_k = 3.0 mm, option K without the gap pad
has R_board 21.6-27.3 C/W before the contact term and 30.0-38.5 C/W with it.

The MB is not an isothermal sink. [LC] §5.1 models it as an infinite convecting fin: two 1 oz pours (kt = 0.0273 W/K),
h = 10-15 W/m²K on both faces, and a heat source of radius 10-19.7 mm. This gives R_MB = 5.5-9.2 C/W. The whole-board
convective floor is 3.9 C/W. The finite board and the off-centre cell raise R_MB above the infinite-fin value.
TODO(measure: R_MB by the heater step of T-K-02).

The junction adds its own rise. The IC share of a CCB loss P is (2.3 / 2.54) x (P - 0.15 W) ([LC] §5.7), that is 2.31 W
at 2.7 W. With RθJB = 9.7 C/W ([DS] §6.4), the junction sits about 22.4 C above the board under U501. This uses a JEDEC
metric on a non-JEDEC board and is indicative only. Hence:

T_J ≈ T_MB,0 + 2.7 W x R_total + 22.4 C,

where R_total is the resistance from the CCB to the T_MB,0 reference, including the MB self-heating ([LC] §5.5). For
option S without the gap pad, R_total = 18.0-23.6 C/W, so T_J ≈ T_MB,0 + 71-86 C. Referred to the computed T_MB,local,
T_J ≈ T_MB,local + 61-72 C ([LC] §5.6).

Table 3.9c gives the results at 2.7 W for each option ([LC] §5.5). The bands span k_pin 70-110 W/mK, R_MB 5.5-9.2 C/W
and, for option K, a socket contact resistance of 0-20 mΩ. The pad rows use the 114 mm² area and the compressed thickness
of §3.7.4.

| Option and pad | R_board, MB fixed (C/W) | P_MB share | MB self-heating | CCB rise over T_MB,0 | T_J - T_MB,0 |
|---|---|---|---|---|---|
| S, no pad | 14.3-18.3 | 72-79 % | 11-19 C | 49-64 C | 71-86 C |
| S, pad k 1 | 10.2-12.1 | 79-84 % | 12-20 C | 38-49 C | 61-72 C |
| S, pad k 3 | 7.9-8.9 | 82-86 % | 13-21 C | 33-42 C | 55-65 C |
| K (h_k 3.0 mm), no pad | 21.6-38.5 | 57-71 % | 9-17 C | 66-118 C | 89-141 C |
| K (h_k 3.0 mm), pad k 1 | 16.0-23.8 | 70-78 % | 11-19 C | 53-81 C | 75-104 C |
| K (h_k 3.0 mm), pad k 3 | 11.8-15.6 | 77-87 % | 12-21 C | 42-62 C | 65-84 C |
| K (h_k 5.0 mm), no pad | 25.4-42.2 | 53-67 % | 8-16 C | 76-128 C | 98-150 C |
| K (h_k 5.0 mm), pad k 3 | 14.1-18.2 | 74-84 % | 11-20 C | 48-68 C | 70-90 C |

Table 3.9c shows that option K needs the compressed gap pad: without it, T_J exceeds T_MB,0 by 89-141 C at h_k = 3.0 mm.
For option S without the pad, [LC] §5.7 gives T_J - T_MB,0 of 52-64, 66-80, 71-86 and 76-93 C at 2.0, 2.5, 2.7 and
2.9 W.

The model ignores spreading inside the CCB, so the copper near U501 runs hotter than this mean. It also omits the header
plastic body (140 mm², k 0.25 W/mK assumed, 73 C/W before its two dry interfaces), which is conservative ([LC] §5.9).
The D-BT-SQ path from the VCHG pour to VBT is also omitted, which is conservative for the pin-18 joint.

#### 3.7.2a Forced-air model: design case and fault case (M, r2)

The CCB sits on a testbench, a fan may blow through the underside gap and over the top, and the CCB has no height
restriction (operator statement, 2026-11-10). [LC] §8 extends the network of §3.7.2 for this case. With the fan off,
radiation off and g 2.415 mm, [LC] §8 reproduces the r1 option-S CCB rise exactly: 58.350, 63.704, 48.526 and 54.526 C
at the four corners of k_pin and R_MB ([LC] §8.3).

The model differs from §3.7.2 in these terms ([LC] §8):

1. **Reference.** The reference is the room air at the fan inlet, T_air. The MB idle offset dT_MB0 = T_MB,0 - T_air
   enters only at the far end of R_MB (5.49-9.21 C/W, [LC] §5.1).
2. **Pins.** The six pins have the r1 landings and fin terms, over a path of H_u + 1.6 mm with H_u = g + 0.125 mm
   (k_pin 70-110 W/mK; socket contacts 2-20 mΩ for option K).
3. **Radiation across the gap.** Solder mask to polyimide, emissivity 0.90 each, gives h_rad 6.67 W/m²K. r1 omitted
   this term, which was conservative. TODO(verify: solder-mask and polyimide emissivity).
4. **Top surface.** Fan on: laminar flat plate, Nu = 0.664 Re^0.5 Pr^(1/3), plus h_rad 6.69 W/m²K. Fan off: the r1
   value h = 10 W/m²K.
5. **Underside gap.** Fan on: a parallel-plate channel with D_h = 2g and simultaneously developing laminar flow
   (Stephan correlation, Shah and London 1978; fully developed limit Nu 7.54). The low end of each band scales Nu by
   4.86/7.54 (one wall heated, one adiabatic). The CCB wall and the sheet wall couple through the air by the lumped NTU
   relation, so the air temperature rise is inside the result. Fan off: conduction only, plus radiation.
6. **Channel.** The flow runs along +y from the low-y inlet (§1.2.3). The channel is 22.34 mm wide (x 22.33-44.67),
   with 891 mm² of the 1219 mm² underside in the flow and a mean flow length of 39.9 mm ([LC] §8.1). The other 328 mm²
   gets still-air conduction only. The model does not credit the mixing or the pressure drop of the obstacles.
   TODO(measure: M15).
7. **Air properties.** Handbook values at 1 atm (Incropera and DeWitt, Table A.4): film at about 40 C, k 0.0271 W/mK,
   ν 1.70e-5 m²/s, Pr 0.705; inlet at 25 C, ρ 1.184 kg/m³, c_p 1007 J/kgK.
8. **Junction.** T_J = T_CCB + 9.7 C/W x P_IC, with P_IC = (2.3/2.54)(P - 0.15 W) as in §3.7.2. The IC term is 16.2,
   20.6, 22.4 and 24.2 C at 2.0, 2.5, 2.7 and 2.9 W. The model ignores spreading inside the CCB, as r1 does.

The results are the following:

1. **Channel.** Table 3.9e gives the gap flow ([LC] §8.2). Δp = (96/Re x L/D_h + 0.674 + 0.5 + 1.0) x ρv²/2, without
   the duct and obstacle losses. Re_Dh above 2800 is transitional; the laminar Nu is kept, which is conservative.

   | g (mm) | v (m/s) | Re_Dh | h per wall (W/m²K) | Channel flow (CFM) | Δp channel (Pa) |
   |---|---|---|---|---|---|
   | 3 | 2 | 706 | 28.2-43.8 | 0.28 | 7.3 |
   | 5 | 2 | 1176 | 22.3-34.6 | 0.47 | 5.9 |
   | 5 | 3 | 1765 | 25.7-39.9 | 0.71 | 12.7 |
   | 8 | 2 | 1882 | 19.9-30.9 | 0.76 | 5.4 |
   | 8 | 3 | 2824 | 23.8-36.9 | 1.14 | 12.0 |
   | 10 | 2 | 2353 | 19.4-30.1 | 0.95 | 5.3 |
   | 12 | 2 | 2824 | 19.1-29.6 | 1.14 | 5.3 |

2. **Design case: both sides forced.** Table 3.9f gives R_total from the CCB to room air and T_J - T_air at 2.7 W,
   with the gap and the top at the same velocity ([LC] §8.6). Each cell gives R_total (C/W); T_J - T_air (C).

   | g (mm) | 1 m/s | 2 m/s | 3 m/s | 4 m/s |
   |---|---|---|---|---|
   | 3 | 10.2-15.9; 50-65 | 8.7-13.2; 46-58 | 7.9-11.7; 44-54 | 7.3-10.7; 42-51 |
   | 5 | 11.6-17.3; 54-69 | 9.8-14.2; 49-61 | 8.7-12.4; 46-56 | 8.0-11.3; 44-53 |
   | 8 | 12.9-18.3; 57-72 | 10.7-14.7; 51-62 | 9.4-12.8; 48-57 | 8.5-11.5; 45-54 |
   | 10 | 13.5-18.6; 59-73 | 11.0-14.9; 52-63 | 9.7-13.0; 48-57 | 8.7-11.7; 46-54 |
   | 12 | 13.9-18.9; 60-73 | 11.3-15.1; 53-63 | 9.9-13.1; 49-58 | 8.9-11.7; 46-54 |

3. **Load sweep.** Table 3.9g gives T_J - T_air and T_J on a 25 C bench ([LC] §8.6). Each cell gives T_J - T_air;
   T_J at 25 C (C).

   | Configuration | 2.0 W | 2.5 W | 2.7 W | 2.9 W |
   |---|---|---|---|---|
   | Both sides, g 5 mm, 2 m/s | 36-45; 61-70 | 45-56; 70-81 | 49-61; 74-86 | 53-65; 78-90 |
   | Both sides, g 5 mm, 3 m/s | 34-42; 59-67 | 42-52; 67-77 | 46-56; 71-81 | 49-60; 74-85 |
   | Both sides, g 8 mm, 2 m/s | 38-46; 63-71 | 47-58; 72-83 | 51-62; 76-87 | 55-67; 80-92 |
   | Both sides, g 8 mm, 3 m/s | 35-42; 60-67 | 44-53; 69-78 | 48-57; 73-82 | 51-61; 76-86 |
   | Gap only, g 5 mm, 2 m/s | 43-63; 68-88 | 55-78; 80-103 | 59-84; 84-109 | 63-90; 88-115 |
   | Gap only, g 8 mm, 2 m/s | 47-66; 72-91 | 59-82; 84-107 | 64-88; 89-113 | 69-94; 94-119 |

4. **Partial cases.** Air through the gap only, with a still top, gives R_total 13.6-22.8 C/W at g 5 mm and 2 m/s
   (59-84 C at 2.7 W). The MB far-field share is then 28-48 % ([LC] §8.5). The gap path alone, without the pins, the MB
   and the top, is 34.3-52.3 C/W at g 5 mm and 2 m/s ([LC] §8.5b). Air over the top only, with a still gap, gives
   13.2-18.1 C/W at g 5 mm and 2 m/s (58-71 C) ([LC] §8.4). The top alone over 1219 mm² is 22.8 C/W at 2 m/s
   (L 35 mm, Re_L 4118, h_conv 29.4 W/m²K) and 24.6 C/W over the 42.3 mm path. Neither partial case meets the design
   case, so the duct covers both sides (§1.2.3 rule 2).
5. **Fault case: fan off.** Table 3.9h gives the still-air result with radiation for each gap ([LC] §8.7). The 2.08 W
   column is the FR-50 2.50 A derate image (1.93 W charger and 0.15 W eFuse and logic, [LC] §5.8). A taller gap is
   worse with the fan off. Radiation, which r1 omitted, lowers T_J - T_air by 4-34 C.

   | g (mm) | R_total (C/W) | T_J - T_air at 2.7 W | T_J at 25 C, 2.08 W | T_J at 25 C, 2.7 W | T_J at 25 C, 2.9 W |
   |---|---|---|---|---|---|
   | 2.415 | 16.7-30.0 | 67-104 C | - | - | - |
   | 5 | 21.1-34.9 | 79-117 C | 86-116 C | 104-142 C | 110-150 C |
   | 8 | 24.7-37.7 | 89-124 C | - | - | - |
   | 10 | 26.6-39.0 | 94-128 C | 97-125 C | 119-153 C | 126-162 C |
   | 12 | 28.2-40.0 | 99-131 C | 101-127 C | 124-156 C | 131-165 C |

   The CCB node has a heat capacity of about 7.8 J/K (laminate 3.6 g, copper 2.3 g, L501 1.1 g, pins 0.9 g and parts
   3 g from Table 1.7, with general specific heats). At g 5 mm its time constant is 164-271 s fan-off and 106-178 s with air through the gap
   at 2 m/s. At g 10 mm it is 207-303 s fan-off ([LC] §8.7). The MB adds capacity, so these are lower bounds.
6. **MB idle offset.** Table 3.9i gives the effect of dT_MB0 at 2.7 W ([LC] §8.6, §8.6b). With the fan on over both
   sides, T_MB,0 is not decisive.

   | Configuration | dT_MB0 0 C | 10 C | 20 C | dT_J / dT_MB0 |
   |---|---|---|---|---|
   | Both sides, g 5 mm, 2 m/s | 49-61 C | 52-63 C | 55-64 C | 0.15-0.30 |
   | Gap only, g 10 mm, 2 m/s | 66-90 C | 69-92 C | 73-95 C | 0.25-0.35 |
   | Fan off, g 10 mm | 94-128 C | 101-133 C | 108-139 C | 0.55-0.70 |

7. **Duct air.** With all 2.7 W into the duct air, the outlet air is at most 10.1 C above the inlet at g 5 mm and
   2 m/s, and 6.3 C at g 8 mm ([LC] §8.6c). The outlet air leaves at y 67.14 and y 76.40, away from the LM1084 (§1.2.3).

A taller gap does not improve the fan-on result. At a fixed velocity of 2 m/s through the gap, R_total rises from
11.6-20.4 C/W at g 3 mm to 16.7-25.3 C/W at g 12 mm. At a fixed channel flow of 1.0 CFM, T_J - T_air rises from 48-67 C
to 69-92 C ([LC] §8.9). The developing-flow h falls as D_h grows, and the pin and gap-conduction paths to the MB weaken.
The gap is therefore set by obstacle clearance and pressure drop: g 5 mm minimum and 5-8 mm recommended (§1.3.2 rule 3).

#### 3.7.3 Copper needed for a junction target

The design target is **T_J <= 100 C at ICHG 3.10 A**, which leaves 20 C to the default TREG of 120 C ([DS] REG16). At the
target, U501 does not fold back the charge current. The target is unchanged in r2. The T_MB,local and T_MB,0 rows below
are the r1 still-air record; they do not decide the r2 design, which uses the fan-on case of §3.7.3a. With the MB as a
fixed boundary at T_MB,local, the required board resistance is:

R_board <= (100 - T_MB,local - 22.4) / 2.7 W, with T_MB,local = T_MB,0 + P_MB x R_MB (§3.7.2).

The table below gives the rows for option S ([LC] §5.8). P_MB is 1.9-2.35 W for option S at 2.7 W ([LC] §5.5).

| T_MB,local | Required R_board | Met by |
|---|---|---|
| 40 C | <= 13.9 C/W | Not met without the gap pad. The six pins alone give 22.4-34.1 C/W. Pins, top and air layer together give 14.3-18.3 C/W, which meets 13.9 C/W only for k_pin >= 116 W/mK, outside the 70-110 W/mK range. The compressed gap pad of 3.7.4 meets it at any k_pin (7.9-12.1 C/W) |
| 50 C | <= 10.2 C/W | A compressed k 3 gap pad (7.9-8.9 C/W). A k 1 pad (10.2-12.1 C/W) meets it only at k_pin 110 W/mK |
| 60 C | <= 6.5 C/W | Not met by any option. At 750 kHz (2.19 W, 1.85 W in the IC) the limit becomes <= 10.1 C/W, met only with a k 3 pad. At ICHG 2.50 A (2.08 W, 1.75 W in the IC) it becomes <= 11.1 C/W: met with a k 3 pad, with a k 1 pad only at k_pin 110 W/mK, never without a pad. The combination of 750 kHz and 2.50 A has no efficiency curve: TODO(measure: T-B-19) |

With a k 3 pad, option K at h_k = 3.0 mm admits a T_MB,local of 36-40 C. With a k 1 pad, it admits 13-23 C. Without a
pad, it admits -26 to -3 C ([LC] §5.6).

T_MB,local cannot be measured before the CCB is built, because the CCB heats the MB. The decision quantity is therefore
the admissible T_MB,0, which includes the MB self-heating. Table 3.9d gives it for T_J <= 100 C at 2.7 W ([LC] §5.5). The
bands span k_pin 70-110 W/mK, R_MB 5.5-9.2 C/W and, for option K, a socket contact resistance of 0-20 mΩ. The pad area is
114 mm² (§3.7.4).

| Option | No pad | Compressed pad, k 1 | Compressed pad, k 3 |
|---|---|---|---|
| S | 14-29 C | 28-39 C | 35-45 C |
| K, h_k 3.0 mm | -41 to 11 C | -4 to 25 C | 16-35 C |
| K, h_k 5.0 mm | -50 to 2 C | -13 to 17 C | 10-30 C |

Table 3.9d shows that only a compressed gap pad gives option K a usable T_MB,0. With the full 132 mm² pad (C506/C508 on
L1, §3.4.4), the option S values rise to 30-40 C (k 1) and 37-46 C (k 3). For option S, the remedies of the 60 C row
give an admissible T_MB,0 of 30-43 C without the pad and 42-55 C with it at 750 kHz. At ICHG 2.50 A they give 34-46 C and
45-58 C ([LC] §5.8).

T-K-02 measures T_MB,0 (M12 of §1.9, at the worst vehicle load). The MB self-heating P_MB x R_MB is computed (R_MB
5.5-9.2 C/W, 11-21 C at 2.7 W) until the heater step of T-K-02 measures R_MB. The LM1084 sets part of T_MB,0 (3.7.5).
In r2, T_MB,0 and R_MB are record only, because the fan-on T_J moves by 0.15-0.30 C per C of dT_MB0 (Table 3.9i).

The copper rules that serve this target are:

1. Make the GND net the heat spreader: the L2 plane, the L4 pour under the cell and the L1 PGND pour, joined by the via
   fields of 3.1.5. About 40 GND vias of 0.3 mm in and around the cell give about 4 C/W from L1 to L2/L4 (163 C/W each,
   [LC] §2).
2. Give the PMID, SYS and VCHG pours on L1 their full zone width. These pours carry the heat from the power pads, because
   the RQM package has no exposed pad ([DS] pp.146-149).
3. Connect pins 4, 14, 15, 18, 19 solidly (3.3.3 item 1). The MB pads of pins 4/14/15 are solid to both MB GND pours
   ([MECH] §1), so these pins reach the largest copper area on the vehicle. Pins 18/19 land on the isolated VCHG pour and
   pin 10 on the VCHG-IN trace, so these three pins spread less heat into the MB (3.7.2).
4. Prefer stack ST2 (2 oz inner), which halves the lateral resistance of L2.

#### 3.7.3a Junction target with forced air (M, r2)

The design case meets the 100 C target without a gap pad. At g 5 mm with 2 m/s over both sides, T_J is 74-86 C at 2.7 W
and 78-90 C at 2.9 W on a 25 C bench (Table 3.9g). At g 8 mm it is 76-87 C and 80-92 C. On a 25 C bench, the margin to 100 C at
2.9 W is therefore 10-22 C at g 5 mm and 8-20 C at g 8 mm. At g 5 mm the target holds up to a room air of 35 C at the
upper end of the band.

The copper rules 1-4 of §3.7.3 stay, because they lower the CCB rise in every case. The pass criterion of the build is
the fan-on and fan-off soak (M16; T-K-20, with its fan-on leg T-K-14):

1. With the fan on, TDIE is 100 C or less at the 2.9 W point, at the measured room air (M17). The measured gap and top
   velocities are 2 m/s or more (M15). Air through the gap only gives 88-115 C at 2.9 W ([LC] §8.6).
2. With the fan stopped at the 2.7 W point and at the 2.08 W derate image, the FR-50 trip acts before TREG_STAT
   (REG1D bit 2, [DS] Table 7-38) sets. The derate alone does not hold 100 C ([LC] §8.7).
3. The measured fan-on h and gap velocity are recorded against Table 3.9e and Table 3.9f.

The soak also measures the real h and gap flow. The model has these unknowns: the obstacle effect in the channel, the
emissivities, the duct capture fraction and the spreading inside the CCB (§3.7.2a).

#### 3.7.4 Thermal gap pad option

**Superseded (r2).** With forced air on the testbench (operator statement, 2026-11-10), the design case meets the 100 C
target without a pad (§3.7.3a). The pad is therefore not fitted, and the BOM carries it as a not-fitted line only. The pad
would also block the fan channel under the power cell. The text below is the r1 record, kept for traceability; L-6 is
not applicable in r2.

A thermally conductive, electrically insulating gap pad can join the CCB underside under the cell to the MB GND pour. The
pad must be compressed. An uncompressed pad loads neither face, so its interface resistances dominate and no conductance
can be credited ([LC] §5.9).

The compressed thickness equals the gap, H_u - 0.125 mm. The gap is 2.415 mm for option S. For option K it is 5.415 mm at
h_k = 3.0 mm and 7.415 mm at h_k = 5.0 mm. For 10-30 % compression, the free thickness is 2.68-3.45 mm, 6.02-7.74 mm and 8.24-10.59 mm
([LC] §5.4).

The pad area must clear these parts:

1. the MB parts under the footprint (up to 1.10 mm, x 24.5-36.0, y 48.5-53.5);
2. BAL and RB1A on the MB;
3. the CCB underside parts of §3.4.4: C508 at (26.3, 64.4), C506 at (30.1, 64.4) and the SW via lands at x 26.82-29.60,
   y 63.90-64.95.

The candidate area is x 25-36, y 54-66 less a notch at x 25.30-31.10, y 62.95-66.00 (17.7 mm², 0.5 mm clearance). This
leaves 114.3 mm² ([LC] §5.4). The full 132 mm² applies only if C506/C508 move to L1 (§3.4.4). With the SYS-row remedy on
L4 (§3.4.2), the pad edge moves to x >= 25.7.

For option S, the compressed pad gives 16.2-30.2 C/W in bulk (114 mm², 2.415 mm, k = 3-1 W/mK, in series with the
0.125 mm polyimide sheet). With two interfaces of 0.5-2.0 K·cm²/W each, the pad gives 17.0-33.7 C/W ([LC] §5.9). The
interface values are assumptions. TODO(verify: gap-pad datasheet, interface resistance against compression).

With the pad and the MB held fixed, option S has **R_board = 7.9-12.1 C/W** at 114 mm² (7.3-11.4 C/W at 132 mm²). The CCB
rise at 2.7 W is then 33-49 C over T_MB,0 (Table 3.9c). Option K at h_k = 3.0 mm has 11.8-15.6 C/W with a k 3 pad.

The pad raises the share of the loss that enters the MB to 79-87 % (2.1-2.35 W), and the MB self-heating to 12-21 C.
The pad therefore raises the admissible T_MB,0 of option S by 10-14 C (k 1) or 16-21 C (k 3). On the MB-fixed basis the
gains would be 11-17 C and 17-26 C.

The pad benefits the junction margin. However, a compressed pad presses the CCB upward against the header, so the foot
screws must carry its compression force F_pad (§1.7.2; T-K-18). At a typical 10-50 psi (69-345 kPa), a 114 mm² pad
presses with 7.9-39.4 N, or 3.9-19.7 N per foot. TODO(verify: gap-pad datasheet, compression force at the fitted
thickness). The pad also couples the CCB to any MB heat from the LM1084. TODO(verify: gap-pad datasheet for conductivity
and outgassing). TODO(measure: M12 and a rev-A thermocouple on U501 copper with and without the pad).

#### 3.7.4a Optional top-side heatsink on U501 (S, r2)

With no height restriction (operator statement, 2026-11-10), a heatsink on the U501 top is possible. [LC] §8.8 uses a
two-resistor model: RθJB 9.7 C/W to the board path, and RθJC(top) 20.9 C/W + R_TIM + R_sa to room air ([DS] §6.4). R_TIM
over the 4.0 x 4.0 mm top is 3.1 C/W at 0.5 K·cm²/W and 12.5 C/W at 2.0 K·cm²/W. Table 3.9j gives T_J - T_air at
2.7 W ([LC] §8.8).

| Configuration | No heatsink | R_sa 120 C/W | 60 C/W | 40 C/W | 20 C/W | 10 C/W |
|---|---|---|---|---|---|---|
| Both sides, g 5 mm, 2 m/s | 49-61 C | 43-53 C | 40-49 C | 37-46 C | 34-42 C | 31-40 C |
| Gap only, g 10 mm, 2 m/s | 66-90 C | 56-74 C | 50-66 C | 47-62 C | 42-55 C | 37-51 C |
| Fan off, g 5 mm | 79-117 C | 65-91 C | 58-80 C | 54-74 C | 47-65 C | 42-59 C |
| Fan off, g 10 mm | 94-128 C | 75-98 C | 66-85 C | 60-78 C | 52-68 C | 46-62 C |

With the fan on, a heatsink of R_sa 60 C/W or less lowers T_J by 9-12 C. With the fan off, R_sa 120 C/W already lowers it
by 14-26 C at g 5 mm. At R_sa 40 C/W, the fan-off T_J is 79-99 C on a 25 C bench at g 5 mm, so the fan-off case also
meets 100 C. The heatsink is therefore mainly a fan-off backstop. It is a DNP option in r2.

The model treats JEDEC metrics as network resistances, so these figures are indicative. The row order of the [DS] §6.4
extract (RθJA 44.2, RθJC(top) 20.9, RθJB 9.7, ψJT 0.5, ψJB 9.7) comes from a text extraction that lost the column
alignment. TODO(verify: [DS] §6.4 row order). The heatsink rules are the following:

1. Fit the heatsink on the U501 mould compound only. It then carries no switch-node voltage.
2. Keep it clear of L501 (3.0 mm tall, beside U501) and of the C511/C512 input capacitors.
3. Attach it with a thermal adhesive or a clip. Its mass on a 4 x 4 mm package needs a positive attachment.
4. Keep the ψJT reading valid: put the U501 thermocouple of M16 on the package edge when a heatsink is fitted.

The heatsink part, its R_sa at the measured air velocity and the adhesive are TODO(verify: heatsink and thermal-adhesive
datasheets).

#### 3.7.5 Influence of the LM1084

The LM1084 courtyard starts at x 50.947 ([MECH] table 2.1). The power cell edge (x 37.5) is 13.4 mm from it, and the U501
centre about 25.7 mm from the LM1084 body. The LM1084 tab pours into the MB 5V pour (x 49.78-61.98), not into GND, so its
heat reaches the CCB mainly through the MB laminate and the air. Its dissipation and case temperature are unmeasured
(TODO(measure: M11)).

In the other direction, a 2.7 W source 13.4 mm (power cell edge to courtyard) to 25.7 mm (U501 centre to body) away
raises the LM1084 ambient. The round-3 EVM sat 20 mm or more away
on standoffs (§1.6.2). The CCB adds this coupling; it is the one thermal risk the CCB adds over Path A.

The bench fan (r2) changes the coupling in two ways. First, the flow runs along +y and leaves at y 67.14 and y 76.40,
away from the LM1084. The warm duct air is at most 10.1 C above the inlet at g 5 mm and 2 m/s, and it does not pass
the LM1084 ([LC] §8.1, §8.6c). Second, the fan must not load the LM1084. The LM1084 carries 0.15-0.25 A of logic load
and dissipates 0.36-0.60 W at VBT 7.4 V and 0.51-0.85 W at 8.4 V. [LC] §8.10 assumes a fan current of 0.05-0.20 A at
5 V, because no fan MPN is chosen (TODO(verify: fan datasheet)). Such a fan would add 0.12-0.68 W, that is +20 to
+133 %, and about +5 to +27 C of junction rise at RθJA 40.4 C/W ([LC] §8.10; LM1084 data sheet, thermal information,
KTT, JEDEC board). The fan therefore takes its power from the bench supply or its own regulator (§1.2.3 rule 7; §1.6.3).

#### 3.7.6 Temperature at the header pins

Pins 18/19 and 14/15 sit 8-20 mm from U501 at the -x edge. The MB-side joint of pin 18 is the worst case, because pins
18/19 land on the isolated VCHG pour and not on GND (3.7.2). For option S, [LC] §5.5 puts that joint at T_MB,local +
20-26 C without the gap pad and at T_MB,local + 10-17 C with it. Referred to T_MB,0, the values are + 33-43 C and
+ 24-36 C. For option K at h_k = 3.0 mm, the joint is at T_MB,local + 20-30 C without the pad and + 10-14 C with a k 3 pad.

The round-3 T-F-16 limit is a joint rise below 20 C ([WD] A.8). That limit was written for the I²R self-heating of a
carrier with the converter off the board. On the CCB, each power pin conducts converter heat into its MB joint, and this
heat sets the joint temperature. Without the pad, the < 20 C rise therefore fails on a sound joint at every point of the
band. A temperature reading also cannot find a degraded joint: a 20 mΩ contact adds only 74 mW at 1.93 A ([LC] §7).

T-F-16, T-B-16 and T-K-14 therefore use an absolute joint-temperature limit and refer the trace rise to T_MB,local
(§6.3.5). T-K-17 decides the joint condition by the 4-wire contact resistance. TODO(measure: T-F-16 on the CCB, with a
thermocouple on pin 18 and on the U501 PGND pour).

The joint values above are the r1 still-air record. [LC] §8 does not compute the pin-18 joint with forced air. With the
fan on, the CCB rise falls from 49-64 C (r1, option S, Table 3.9c) to 26-38 C at g 5 mm and 2 m/s over both sides
([LC] §8.6). The joint temperature therefore falls too. The longer r2 pins (230-335 C/W, §3.3.2) carry less converter heat
into the joint. TODO(calc: pin-18 joint with forced air). TODO(measure: pin-18 thermocouple in the M16 soak).

### 3.8 Test points and probe access (M)

All test points are top-side SMT pads, so they are reachable with the CCB mounted. Table 3.10 places the test points of
§2.5.10.

| Test point | Net | Location | Label |
|---|---|---|---|
| TP501 | VCHGOUT | Beside C511, Z-E/Z-P boundary | S |
| TP502 | VCHG | Beside C538, -x edge of the cell | S |
| TP503 | REGN | Beside C535 | S |
| TP504 | ILIM_HIZ | Z-C, within 5 mm of pin 17; no part lands on it (§2.2.2 rule 1) | S |
| TP505, TP506 | NCE, TS | Z-C | S |
| TP508, TP509 | NINT, NQON | Z-C | S |
| TP510 | CHG_SYS | Beside C522/C523 | S |
| TP511 | GND (power) | Cell PGND pour, -x side | I |
| TP301-TP305 | 3V3, GATE, ARM_OKP, ILIM_REL, CE_DRV | Z-Q / Z-D | I |
| TP306 | GND (quiet) | Z-Q | I |

The probe rules are:

1. Give every power test point a GND pad within 5 mm for a ground spring. TODO(verify: probe ground-spring length).
2. Put no test point on VCHGIN, PMID, SW1 or SW2 (§2.5.10; [WD] A.8; [DS] §8.4.1 item 2).
3. Probe SW1 and SW2 across the DNP snubber footprints: R507 pad 1 is SW1 and C505 pad 2 is GND; R510/C507 serve SW2. These
   footprints double as tip-and-barrel probe points.
4. Leave the tap pads F01-F24 and the test points uncoated until the bench gates pass (§1.7.3 item 3).
5. Note that the CCB covers the MB under the footprint. MB probe points under rect A and the footprint are reachable only
   with the CCB removed.

### 3.9 Assembly sides and conformal coating (I)

#### 3.9.1 Top side

The top carries every IC, L501, the SMA diodes, all 1206/1210 parts, the 0805 10 µF capacitors, the tap pads and the test
points. The tallest top part is L501 at 3.0 mm ([UG] Table 4-1), so the CCB top reaches H_u + 1.6 + 3.0 mm (§1.3.2). This
is 7.14 mm for option S, 6.0 mm below the nominal Ag105 envelope. For option K it is 7.14 + h_k mm, 6.0 - h_k mm below.

#### 3.9.2 Underside

The underside faces the MB at H_u = 2.54 mm for option S, or h_k + 2.54 mm for option K. The rules of §1.3.5 apply, with
these additions:

1. Fit only parts <= 1.0 mm tall. This probably excludes the 10 µF 0805 SYS capacitors (TDK C2012X5R1E106K125AB; the
   suffix 125 suggests 1.25 mm). TODO(verify: TDK datasheet thickness, and the thickness of every bottom MPN).
2. Fit no part in the MB bottom keep-out x 24.5-36.0, y 48.5-53.5.
3. Fit no part over the MB power copper (VBT, VBT pour, VCHG pour, VCHG-IN) grown by 1 mm (§1.3.5).
4. Fit no part in the cell reserve (x 22.4-36.0, y 52.8-67.4) except C506/C508 (3.4.4).
5. Fit no part under rect A', because its MB part (OP-FC) leaves only 1.0 mm of air at H_u = 2.75 mm.
6. Fit no part within 3.0 mm of a foot hole.
7. Tent every via on the underside (§1.5 rule 1).

Assemble in this order: underside reflow, top reflow, then the header strips by hand or selective solder with preheat
(3.3.3 item 1), then cleaning and coating.

#### 3.9.3 Conformal coating zones

The §1.7.3 zones apply. The layout adds:

1. Coat Z-Q and Z-D first in priority. The MΩ nodes of 3.6.1 depend on surface insulation, and the coating protects them
   from condensation on the testbench MB (r1: on a vehicle).
2. Mask the header pins, the foot holes, the test points, the tap pads and the SW probe footprints (3.8 item 3).
3. If the gap pad of 3.7.4 is fitted, coat the CCB underside under it. The thin film adds little thermal resistance.
   TODO(verify: coating thickness and conductivity).
   r2: not applicable, because the gap pad is not fitted (3.7.4, superseded by the testbench facts, operator statement,
   2026-11-10).
4. Choose a coating rated above the U501 copper temperature (> 100 C at the 3.7.3 target). TODO(verify: coating datasheet).

## 4. Bill of materials

This section gives the bill of materials (BOM) of the CCB, with stock, unit prices, fabrication and assembly cost, and a
cost comparison with Path A. Nothing is ordered. The machine-readable BOM is `bom.csv` in the review folder: 111 part lines
plus the PCB line. The generator `make_bom.py` regenerates it and the cost roll-up `bom_cost.json` ([BOMGEN]). r2 adds
eight lines for the testbench (operator statement, 2026-11-10):

- the fan;
- the fan lead and its connector;
- the fan mount and duct;
- a DNP fan regulator;
- the soak thermocouples;
- the anemometer (tool);
- a DNP U501 heatsink;
- the not-fitted r1 gap pad.

r2 also re-classes the H301 headers and the option-K sockets as tall-stack parts (§1.3.2).

Each CSV line carries the label of §0.4 in the column `class_IC`. The column `carried_over_from_round3_refdes` names the
round-3 or EVM designator, or "new". The part list of section 2 is the source of every designator, value and rating.

### 4.0 Conventions

#### 4.0.1 Price classes

Every price carries one of five bases. Only class V is a verified price.

| Class | Meaning |
|---|---|
| **V** | Verified TI store price, 2026-11-10, the 1-99 tier ([TI-PD]). One tier covers both the 1-board and the 5-board quantities of every TI line |
| **V\*** | TI store price of a sibling orderable (TPS26630RGERG4), because TPS26630RGER has no part-details page. TODO(verify: TPS26630RGER price) |
| **A3** | Round-3 recorded budget allowance ([WD] E); [WD] E states that non-EVM prices are not verified |
| **AL** | Budget allowance set in this section. It is not a quote and must be replaced by a quote before any order |
| **T** | No figure: TODO(verify: price). The roll-up in §4.5 covers these lines with a stated per-placement allowance |

#### 4.0.2 Distributor access on 2026-11-10

1. The TI store answered every request; its stock and price figures are in §4.2.
2. DigiKey returned HTTP 403 to one plain-curl request.
3. Mouser returned an "Access to this page has been denied" page to one request.

No site was retried. Every non-TI stock figure is therefore TODO(verify: stock). The same block occurred
in round 2 ([EVAL] §7 line 969: "DigiKey 403", Mouser DNS-blocked).

### 4.1 BOM summary by block

#### 4.1.1 Placement count (mixed)

Table 4.1 gives the fitted placements per board, from the CSV `qty_per_board` column. The total of 176 agrees with the
§2.5.12 hand count of about 174 plus the two header strips.

| Block | Class | Fitted placements | DNP footprints | Source |
|---|---|---|---|---|
| Power stage U501, L501 and passives | S | 24 | R507, R510, C505, C507, R541, C541, R506 | §2.5.4 |
| Input protection (eFuse U301 network) | I | 15 | C305, R306 | §2.5.3 |
| Charger interface (drivers, ILIM_HIZ switches, pin senses, TS, /CE) | S | 39 | R521, R526 or R525 (XOR), C453 | §2.5.5 |
| Comparators | I (U403/U404 in the interface row) | 45 | U317 group, R334, C336, C337 | §2.5.6 |
| Logic, heartbeat, QUAL one-shot | I (U311 group S) | 51 | R345, R346 | §2.5.7 |
| Keep-alive option | I | 0 | U312, C352, D301, R392 | §2.5.8 |
| Header H301 (two strips) | I | 2 | - | §2.5.2 |
| **Total** | | **176** | about 28 | |

The 16 test points of §2.5.10 are copper probe pads, not purchased parts. They have no BOM line. The r2 fan parts
(§1.6.3) are bench items with the scope `build` in the CSV, not board placements, so Table 4.1 does not change.

#### 4.1.2 Lines of note (mixed)

1. **U501 BQ25798RQMR (S):** 415 146 in TI stock; USD 5.038 each at 1-99 ([TI-INV], [TI-PD]).
2. **L501 TDK SPM6530T-1R0M120 (S):** the EVM part ([UG] Table 4-1). Its stock and price are TODO(verify: stock, price).
   The O-2 rating questions (Isat basis, heating current, the §2.1.3 saturation criterion) stay open. No substitute is
   allowed until O-4 gives the cycle-by-cycle limit (§2.1.3).
3. **C511, C512, C529-C531, 10 uF 50 V X7R 1210 (S):** O-1 leaves the MPN open. This section names Murata
   GRM32ER71H106KA12L as a candidate only. TODO(verify: Murata datasheet, rating and DC-bias curve at 23.6 V, T-A-04).
   No 0805 fallback is allowed: an 0805 part is outside the 1210/1206 footprint and area plan, and its DC-bias case at
   23.6 V (C_VBUS >= 2 uF, C_PMID >= 4 uF, [DS] §6.3) has not been made. The round-3 EM14 part GRM21BR6YA106KE43L
   (35 V X5R 0805) stays only on the MB C-D8/C-D10 rework line (PM2).
4. **R529 6.04 kOhm (S):** candidate CRCW06036K04FKEA. The EVM BOM lists 6.20 kOhm (RC0603FR-076K2L) against 6.04 kOhm in
   the EVM schematic and SLUSDV2C Table 7-1 (§2.1.2). Order the 6.04 kOhm value.
5. **U314, U316, U318 SN74LVC2G08 (I):** the round-3 orderable SN74LVC2G08DCTR had **zero** TI stock on 2026-11-10.
   SN74LVC2G08DCTRE4 (same DCT package, 142 215 in stock) and DCTRG4 (5 103) were in stock at USD 0.861 ([TI-PD]).
   The BOM names DCTRE4. TODO(verify: SCES198N ordering addendum, that E4 is a DCTR finish variant with the same pinout).
6. **U301 TPS26630RGER (I):** 53 000 in TI stock. The TI site has no part-details page for RGER, so the price is the
   RGERG4 page figure, USD 4.812 (class V\*). [WD] E recorded 40 units on the TPS2663 page on 2026-11-05; the endpoints
   differ, so the two figures are not comparable. TODO(verify: TPS26630RGER price and stock at order time).
7. **Low-stock TI lines:** SN74LVC1G06DCKR 874, SN74LVC2G32DCTR 1 801, SN74LVC1G11DCKR 2 547, SN74LVC1G123DCTR 2 735,
   TPS22810DBVR 105 (DNP). Each exceeds a 5-board build by more than ten times, but each can fall to zero as DCTR did.

### 4.2 TI parts: verified stock and price (mixed)

Table 4.2 lists every TI line. Stock is from [TI-INV] at 18:26 UTC; prices are the [TI-PD] 1-99 tier. The qty-5 column
is the unit price at a 5-board build, which stays in the 1-99 tier for every line (largest: TLV3012B, 45 + 2 spares).

| Ref | OPN | Qty / board | Stock 2026-11-10 | USD unit, qty 1 | USD unit, qty 5 boards | Class | Round 3 recorded |
|---|---|---|---|---|---|---|---|
| U501 | BQ25798RQMR | 1 | 415 146 | 5.038 | 5.038 | S | - (EVM only) |
| U301 | TPS26630RGER | 1 | 53 000 | 4.812 (V\*) | 4.812 (V\*) | I | 40 (TPS2663 page), allowance USD 4 |
| U302-U304, U315, U319-U321, U403, U404 | TLV3012BIDBVR | 9 | 29 409 | 2.079 | 2.079 | 7 I, 2 S | 27 694, allowance USD 1 |
| U305 | SN74LVC3G04DCTR | 1 | 21 705 | 0.818 | 0.818 | I | allowance USD 0.5 |
| U306, U310 | SN74LVC2G32DCTR | 2 | 1 801 | 0.761 | 0.761 | I | allowance USD 0.5 |
| U307-U309 | SN74LVC1G11DCKR | 3 | 2 547 | 0.161 | 0.161 | I | allowance USD 0.5 |
| U311, U313 | SN74LVC1G123DCTR | 2 | 2 735 | 1.703 | 1.703 | U311 S, U313 I | allowance USD 0.6 |
| U314, U316, U318 | SN74LVC2G08DCTRE4 (DCTR: 0) | 3 | 142 215 | 0.861 | 0.861 | I | DCTR, allowance USD 0.5 |
| U322 | SN74LVC1G08DCKR | 1 | 734 408 | 0.069 | 0.069 | I | allowance USD 0.3 |
| U323 | SN74LVC1G14DCKR | 1 | 596 127 | 0.108 | 0.108 | I | allowance USD 0.3 |
| U401 | SN74LVC3G06DCTR | 1 | 43 837 | 0.830 | 0.830 | S | allowance USD 0.5 |
| U402 | SN74LVC1G06DCKR | 1 | 874 | 0.109 | 0.109 | S | allowance USD 0.3 |
| U312 (DNP) | TPS22810DBVR | 0 | 105 | 0.492 | 0.492 | I | allowance USD 1 |
| (Path A only) | BQ25798EVM | - | 161 | 156.45 | 156.45 | S | 162, USD 156.45 |

The TI silicon on one board costs **USD 38.49** (V and V\*). Of this, USD 26.65 is IC-independent (U301, seven TLV3012B,
the logic) and USD 11.84 is BQ25798-specific (U501, U401-U404, U311).

### 4.3 Non-TI parts (mixed)

#### 4.3.1 Carried-over candidates

The non-TI candidates carry over from [WD] E with their round-3 designators renumbered per §0.5. They include the
0.1 % Vishay TNPW dividers, the CRCW 1 % resistors, the Murata/TDK capacitors, onsemi 2N7002KT1G and BSS84LT1G, Nexperia
BAV199, D303 and D307. [WD] E states that "every MPN below is a candidate that T-A-05 checks". The same rule applies here.

#### 4.3.2 New candidates (BQ25798-specific)

The power-stage passives take the EVM MPNs from [UG] Table 4-1, except the input-side 10 uF parts (§4.1.2 item 3).
The EVM 25 V X5R 0805 parts C2012X5R1E106K125AB stay on SYS only, where §2.1.2 shows a 25 V rating is sufficient.

#### 4.3.3 Unresolved MPNs

| Line | Status | Gate |
|---|---|---|
| D303 Schottky, D307 TVS | Selected by datasheet in T-A-05 ([WD] E); B340A-13-F is a bench-only fallback for D303 | T-A-05 |
| C511, C512, C529-C531 | Candidate only (§4.1.2 item 3) | T-A-04, T-A-05 |
| R541/C541 input snubber (DNP) | No MPN (§2.1.2) | only if fitted |
| Socket strips (header option K) | r2: elevated class for h_k = H_u - 2.54 mm (2.6-5.6 mm): Samtec ESQ-110 / ESQ-112 (K2) or a Harwin M20 female with a long-pin male (K3), candidates only. The r1 SSW-110 / SSW-112 class gives H_u about 11.05 mm, above the r2 band. Tail diameter for the 1.10 mm MB drill, seat height and accepted pin range TODO(verify: Samtec, Harwin drawings) | §1.3.4 conditions 1-3; §1.3.2 Table 1.3a |
| H301 header strips (r2) | Tall-stack class for H_u 5.1-8.1 mm: Samtec TSW-110 / TSW-112 with a long-post lead style (S1) or MTSW-110 / MTSW-112 with a movable body (S2); pin length 10.8-13.8 mm or more. Lead style TODO(verify: Samtec drawing) | §1.3.2 Table 1.3a |
| Fan (r2) | Axial DC fan, 25-30 mm frame class, 3.9-11.8 CFM rating; static pressure above the bare-channel 5.4-12.7 Pa by the duct and obstacle losses ([LC] §8.9). TODO(verify: fan MPN, airflow and static-pressure curve, current) | §1.6.3; M15 |
| Fan lead connector (r2) | Inline 2-pin connector to the bench supply. TODO(verify: connector MPN) | §1.6.3 item 3 |
| U501 heatsink (r2, DNP) | R_sa 60 C/W or less at the measured air velocity, clear of L501. TODO(verify: heatsink and thermal-adhesive datasheets) | §3.7.4a |
| Header pin current rating | TODO(verify: Samtec TSW datasheet) | O-10 |
| Support-foot spacer length | Equal to H_u from the dry fit | §1.4 rule 2, measurement M3 |
| Foot adhesive (epoxy); no threadlocker on the foot screws; foot-screw torque T_s | TODO(verify: adhesive datasheet, MB solder-mask adhesion, nylon M3 screw datasheet) | §1.4 rule 4, §1.7.2 rule 2, T-K-18 |

### 4.4 Fabrication, stencil and assembly (mixed)

#### 4.4.1 Bare PCB (IC-independent outline, BQ25798-specific stack demand)

The CCB is L-shaped: a 31.0 x 33.0 mm body and a 21.2 x 9.26 mm tab, about 1219 mm² per side (§1.8). The bounding
box is 31.0 x 42.26 mm (1310 mm²). The stack is the choice of §3.1.3, not the CR stack: 4 layers, 1.6 mm, ENIG,
**1 oz outer / 1 oz inner (stack ST1, baseline) or 1 oz outer / 2 oz inner (stack ST2, preferred if the fab offers it)**
(§3.1.3). The round-3 CR stack (2 oz outer, 1 oz inner, [WD] E "CR PCB") is not chosen for rev A, because
the 0.2 mm copper gaps of the U501 land pattern at 0.4 mm pitch may not etch in 2 oz outer copper at the chosen fab
(§3.1.3, stack ST3). TIDA-050047 is built in 2 oz on all layers (stack ST4), so a fab that confirms 0.2 mm space at
2 oz outer reopens that option. A 4-layer stack also meets the §1 rule of a solid GND layer next to the underside.

1. **Published reference (does not meet the stack):** OSH Park 4-layer costs USD 10 per square inch per three copies, with
   1 oz outer and 0.5 oz inner copper ([OSH]). Five boards need two lots of three: USD 37.78 on the outline area, or USD
   40.61 on the bounding box. The billing basis is TODO(verify: OSH Park).
2. **Round-3 allowance:** USD 70 for five 31 x 33 mm 4-layer 2 oz CR boards, with the EIB in the same panel ([WD] E).
3. **This section's allowance:** USD 70-120 per lot of five, stack ST1 or ST2. TODO(verify: quote from a fab that offers
   4-layer 1 oz outer with 1 oz or 2 oz inner, 0.1/0.1 mm trace/space, 0.254 mm tented vias and ENIG at this outline;
   L-2). The upper end covers the 19 % larger area and the 2 oz inner option. No via-in-pad surcharge applies, because
   the U501 vias sit under the body, not in the pads (§3.1.5 rule 4).

#### 4.4.2 Stencil (mixed)

A stencil is required. U501 is a VQFN-HR with 29 pads (33 lead segments) of 0.20 mm width at 0.40 and 0.45 mm pitch
and no exposed pad ([DS] pp.148-149; §3.4.6). U301 is a 4 x 4 mm QFN with a thermal pad (§2.5.3). The U501 apertures
equal the pads in a 0.1 mm thick stencil ([DS] p.150; §3.4.6 rule 5), as in the TIDA-050047 paste layer ([TLP] §3).
Allowance USD 25 (class AL), TODO(verify: fab quote for a framed or frameless stainless top stencil, 0.1 mm thick).

#### 4.4.3 Assembly options (mixed)

Table 4.3 compares the two assembly options. Neither has a quote.

| Option | Method | Cash cost | Risk | Class |
|---|---|---|---|---|
| **H: hand assembly** | Stencil print, reflow on a hot plate or in an oven, hand-solder the TH headers and tap pins | Stencil only (§4.4.2). Tooling availability (hot plate, hot-air station, stereo microscope) is TODO(verify: operator) | U501 joints are hidden under a flip-chip body; they cannot be inspected optically. Bridging on 0.4 mm pitch is likely without paste control | U501 S; rest I |
| **P: PCBA service** | Turnkey or consigned top-side SMT; the operator fits the TH headers, the tap pins, R342 and the R525/R526 choice | TODO(verify: quote). This section's allowance: USD 100-250 for a 2-5 board order (setup, stencil, part fees). The stencil is part of this allowance, so Table 4.4 nets the USD 25 stencil of the AL line | Part availability in the assembler's library is unknown; TI parts may need consignment. X-ray inspection of U501 is TODO(verify: assembler) | I |

**Recommendation:** use option P for the top side of the first lot. The reason is U501: its hidden 0.15-0.25 mm joints carry
the 3.21 A battery current, and a defective joint is a safety fault, not a cosmetic one. However, option P adds a quote
cycle and a part-sourcing dependency. Option H is acceptable for a later lot once one P-built board has passed the bench
gates. Fit two spare U501 per lot either way (CSV `spares_for_5_board_build`).

U501 joint inspection is a gate in both options. Use X-ray where the assembler or a local service offers it
(TODO(verify: X-ray availability, B-7)). In every case, the pin-to-pin list of T-K-06 step (1) must pass before any
source is connected. A bridge between adjacent U501 pins can destroy the IC at the first battery connection (§2.3.2,
Table 2.6b).

Hand-fitted parts in both options:

1. the H301 strips (tall-stack TSW-110 / TSW-112 or MTSW class, §1.3.2), soldered per the §1.3.5 tail rules;
2. the F01-F24 tap pins and their wires;
3. R342 from the select-on-test kit, after T-C-03/T-E-10;
4. R525 or R526, after T-E-09 (never both, §2.2.1).

#### 4.4.4 Mechanical and installation items (IC-independent)

| Item | Qty | Basis | Cost class |
|---|---|---|---|
| Socket strips in the MB holes (option K), elevated class (r2) | 1 set (1x10 + 1x12) per vehicle MB | §1.3.4; Table 1.3a | AL USD 6 each (r1: USD 4) |
| Nylon M3 spacer + nylon M3 screw | 2 per board (+2) | §1.4 option B, feet at (23.20, 70.64) and (32.20, 70.64) | AL USD 1 each |
| Foot epoxy (no threadlocker, §1.7.2 rule 2) | 1 per build | §1.4 rule 4, §1.7.2 rule 2 | AL USD 15 |
| Polyimide sheet (extended over rect A) | 1 per installation (+1) | §1.5 rule 3; [WD] E r5 | A3 USD 10 |
| Neutral-cure RTV (tap strain relief, inductor staking) | 1 tube | §1.7.2 rules 3-4; [WD] E r5 | A3 USD 15 |
| Type-K thermocouple | 1 | [WD] E r6, T-F-16; also serves T-B-16 | A3 USD 15 |
| Bench fan (r2) | 1 per bench installation | §1.6.3 item 1 | AL USD 10 |
| Fan lead and inline connector (r2) | 1 | §1.6.3 item 3 | AL USD 3 |
| Fan mount and duct (r2) | 1 | §1.2.3 rules 1-5; §1.6.3 item 5 | AL USD 5 |
| Fan regulator (r2, DNP option) | 0 | §1.6.3 item 2; only if the bench supply voltage does not match the fan | T |
| Soak thermocouples (r2) | 1 lot of 6 | M16; §3.7.3a | AL USD 20 |
| Anemometer (r2, tool, not in the roll-up) | 0 | M15 | T |
| Gap pad (r1 option, not fitted in r2) | 0 | §3.7.4 superseded | - |
| Wire (taps only; no 18/20 AWG lead wire) | 1 lot | [WD] E wire line less W1-W4 and W6 | AL USD 10 |

### 4.5 Cost roll-up (mixed)

#### 4.5.1 Build definitions

Four builds are priced. Every build includes one set of MB rework parts and one set of consumables.

1. **Build 1:** one populated board, no spares. This is the minimum material for one vehicle.
2. **Build 2:** two populated boards with the CSV spares. It matches Path A's two EVMs, one installed and one spare ([EVAL] §7).
3. **Build 4:** four populated boards with the CSV spares: the vehicle board, a spare, FI1 and LOOP1 (§6.1.4). This is the
   build that the test plan needs. It does not include a separate lot for the LOOP1 layout variant (§7.1.3).
4. **Build 5:** five populated boards with the CSV spares. It uses the whole fab lot.

The 124 placements per board without a price figure (`bom_cost.json`, build 1) (class T) are covered by an allowance of USD 0.15 per placement
(class AL), spares included. TODO(verify: distributor prices for the CRCW, GRM, TDK and Yageo lines).

#### 4.5.2 Totals

Table 4.4 gives the roll-up from `make_bom.py` (`bom_cost.json`). All figures are USD.

| Component | Build 1 | Build 2 | Build 4 | Build 5 | Basis |
|---|---|---|---|---|---|
| TI silicon (V, V\*) | 38.49 | 101.94 | 178.91 | 217.40 | §4.2 |
| Round-3 allowances (A3) | 50.00 | 77.50 | 93.50 | 101.50 | [WD] E |
| This section's allowances (AL): L501, 50 V caps, tall-stack headers, elevated sockets, 21 tap pins, feet, adhesive, wire, stencil; r2 bench fan, fan lead, fan mount, soak thermocouples | 126.50 | 172.00 | 225.00 | 251.50 | §4.1.2, §4.4 |
| Unpriced chip passives at USD 0.15 per placement (AL) | 18.60 (124) | 48.15 (321) | 84.75 (565) | 103.05 (687) | §4.5.1 |
| Bare PCB, one lot of five (AL) | 70-120 | 70-120 | 70-120 | 70-120 | §4.4.1 |
| **Subtotal, hand assembly (option H)** | **304-354** | **470-520** | **652-702** | **743-793** | |
| PCBA service (option P, AL): USD 100-250 including the stencil, less the USD 25 stencil of the AL row | +75-225 | +75-225 | +75-225 | +75-225 | §4.4.3 |
| **Total, option P** | **379-579** | **545-745** | **727-927** | **818-1018** | |

Only USD 38.49 / 101.94 / 178.91 / 217.40 of these totals are verified prices. Everything else is an allowance and must be replaced
by quotes before an order. The PCBA range is the largest single uncertainty. The option-P totals count the stencil once,
because the PCBA allowance includes it (§4.4.3). `make_bom.py` nets the USD 25 stencil out of option P, so
`bom_cost.json` gives the same option-P figures as Table 4.4.

r2 raises the AL row by USD 44.00 (build 1) to USD 54.00 (build 5) over r1. Of this, USD 38.00 per build is the bench fan,
its lead, its mount and the soak thermocouples. The rest is the tall-stack header allowance (USD 3.00 per strip in place of
USD 2.00) and the elevated-socket allowance (USD 6.00 per strip in place of USD 4.00). The r1 totals were USD 260-310,
422-472, 600-650 and 689-739 (option H) and USD 335-535, 497-697, 675-875 and 764-964 (option P).

#### 4.5.3 Comparison with round-3 Path A (mixed)

Table 4.5 compares build 2 with Path A. Path A is two BQ25798EVMs at the verified USD 156.45 each, plus the CR, the EIB, parts,
wire and hardware at the round-3 allowance of USD 190-225 ([WD] E "Cost").

| Item | Path A (round 3) | CCB, build 2 |
|---|---|---|
| Charger hardware | 2 x BQ25798EVM: USD 312.90 (verified; 161 in stock on 2026-11-10) | 2 boards + spares; U501 silicon USD 20.15 (4 x 5.038: 2 boards and 2 CSV spares) |
| Boards | CR + EIB in one panel: allowance USD 70 | CCB lot of five: allowance USD 70-120 |
| Parts, wire, hardware | allowance USD 120-155 (USD 190-225 less the USD 70 PCB) | V + A3 + AL + passives: USD 399.59 (r2, with the bench fan) |
| **Total** | **about USD 505-540** | **about USD 470-520 (option H); 545-745 (option P)** |

With hand assembly, two CCBs are between USD 70 below and USD 15 above Path A on these allowances (full span, §7.0.4
item 5). With a PCBA service they are USD 5-240 above Path A. The test plan needs build 4, which is USD 112-197 (option
H) or USD 187-422 (option P) above Path A (§7.1.3). The Path A figures carry no bench fan; a Path A EVM on the bench
would need its own cooling decision, which is outside the scope of this document. The cost case for the CCB is therefore weak. Its case rests on the
removed leads, ribbon and EVM modifications (§2.3-2.4), not on price.

### 4.6 Round-3 BOM lines: removed, moved and carried over (mixed)

#### 4.6.1 Lines that disappear

Table 4.6 lists the [WD] E lines that have no CCB counterpart, with the [WD] E cost where one was recorded.

| [WD] E line | Reason | [WD] E cost |
|---|---|---|
| EVM x 2 | Power stage on the CCB | USD 312.90 (verified) |
| EIB PCB | EIB stages on the CCB (§2.3.1) | in the CR panel |
| J101, J201 (2x7 1.27 mm headers), W5 cable assembly, W5 key | No ribbon (§1.12.2 item 2) | W5 allowance USD 25 |
| W7 mate (Molex KK 254 housing + crimps) | No EVM I2C lead | - |
| R130, R131A, R131B, R132 (100 Ohm ribbon damping) | §1.12.2 item 1 | - |
| R176, R177 (200 Ohm ribbon 3V3 feed) | §1.12.2 item 2 | - |
| R250, R251, R253, R266 (1 kOhm driver input series) | §2.3.1 | - |
| R264, R265 (470 Ohm sense output series) | §2.3.1 | - |
| R273 (10 Ohm EIB ground link), C205 (REGN at Q203) | §2.3.1 | - |
| EVM JP4 shunt; JP3 and JP5 soldered links; EVM R21 0 Ohm link | EVM modifications disappear (§2.4.2 EM3, EM11, EM12) | - |
| C (EVM) 10 uF 35 V x 5 (+3) | Replaced by C511, C512, C529-C531 at 50 V (§2.4.2 EM14) | allowance USD 0.5 each |
| 18 and 20 AWG lead wire (W1-W4), W6 wire share | No 0.3 m leads | - |
| 6 x M3 x 10 mm nylon standoffs | Replaced by two bonded feet (§1.4) | - |

#### 4.6.2 Lines that move onto the CCB

The EVM-mounted round-3 parts become CCB parts with new designators: EVM R23 -> R523, R256 -> R456, C252 -> C452,
R272/R272b -> R472/R472b (§2.3.1, §7.2 EM2, EM4, EM5). The EIB stages U201-U204, Q201-Q203 and their kept resistors and
capacitors become the 4xx parts.

#### 4.6.3 Lines that carry over unchanged (IC-independent)

1. Every CR integrated circuit and passive, renumbered 1xx -> 3xx (§1.12.1, Table 1.12).
2. The MB rework parts: C-D8/C-D10 10 uF 35 V (PM2), R170/R171 (PM3), RSDA/RSCL 2.70 kOhm (PM9) ([WD] D.1).
3. The DNP options: keep-alive (U312, D301, R392, C352; MB R172, F101), FCI_OK (U317 group), the fallback-2 fused link.
4. The CHG header strips (TSW-110, TSW-112) and the tap pins (TSW-101).
5. The polyimide sheet, the RTV, the thermocouple and the PM4 overlay wire.

#### 4.6.4 Lines that are new

1. The BQ25798 power stage: U501, L501 and 22 passives (§2.5.4). All are BQ25798-specific.
2. The R518, R524, R525/R526 TS network and R529 PROG (§2.5.5). All are BQ25798-specific.
3. The stencil, the socket strips (option K), the two support feet and their adhesive. These are IC-independent.

### 4.7 Separation for an alternative charger IC (mixed)

A different charger IC replaces only the S lines. Table 4.7 splits the per-board cost on the verified and recorded figures.

| Part set | Lines | Per-board cost basis |
|---|---|---|
| IC-independent (I) | eFuse network, H1/UVB/BT_OK/BTB_OFF/FCC/RGN comparators, permit logic, heartbeat, pack-OV input, header, taps, feet, sheet, MB rework | TI silicon USD 26.65 (V/V\*) plus the I lines of the CSV |
| BQ25798-specific (S) | U501 and power stage, U401-U404 drivers and senses, Q401-Q403, ILIM_HIZ and /CE networks, TS and PROG, U311 QUAL one-shot, the stencil apertures for U501 | TI silicon USD 11.84 plus the S lines of the CSV |

The fab lot, the stencil and the assembly cost depend on the replacement IC's package and placement count. A replacement
with an exposed pad or a larger pitch may make option H viable on the first lot.

## 5. Firmware and IO CSV impact (proposals only)

This section states how the round-3 firmware requirements (FR) and the IO CSV amendments change when the CCB replaces the
round-3 assembly of CR, EIB, BQ25798EVM and leads. Every item is a proposal. No firmware, CSV, CLAUDE.md or WORK_QUEUE.md
text has been edited. Section 5.10 lists every change that other repository files need.

The section uses these sources:

- **[WD]** is the round-3 wiring design. Bare section letters (B.1, D.2, D.3, D.4, G.1, G.2, G.3) refer to it.
- **ino** is `teensy_controller/teensy_controller.ino` at commit `330344c`: 17 212 lines, `FW_VERSION 37` at ino 4281,
  `BENCH_TEST` default 1 at ino 4284, `HIL_SIM` 0 at ino 4315.
- **CSV** is `references/Scale Car Teensy IO - IO.csv` as committed at `330344c`. It is the Ag105-era map; the D.3
  amendments have not been applied.
- **DS** is TI SLUSDV2C (BQ25798 data sheet, rev C), as transcribed in [TID].

Each subsection and table row is labelled IC-independent or BQ25798-specific. With another charger IC, the IC-independent
rows carry over without change.

### 5.1 Baseline: what the firmware contains today (IC-independent context)

The worktree firmware is the Ag105-era fw v37 rev 2. The charger-related anchors that the round-3 FRs modify are listed
below, so that the line references in this section are verifiable.

| Symbol / site | ino line(s) | Current role | Round-3 FR that removes or changes it |
|---|---|---|---|
| `#define MPPT_DISABLE 5` | 1984 | Ag105 MPPT disable, active-LOW | FR-01 (renamed `CHG_ARM`) |
| `#define CHARGER_STAT 6` | 1985 | Ag105 STAT, HIGH = charging | FR-01, FR-44 (polarity inverts) |
| pin 7 comment ("FREE ... deliberately left UNDRIVEN") | 1986-1989 | retired ENC_ENABLE | FR-01 (becomes `CHG_CE_RB`) |
| `#define SDA 18` / `SCL 19` ("I2C Ag105 charger") | 2000-2001 | Ag105 bus | FR-01 (comment), FR-07 |
| `REGEN_ENABLE 30`, `FC_CHARGE_ENABLE 31` | 2008-2009 | RT1987 EN pins | FR-06, FR-49 |
| `CHG_VOLTAGE 38`, `RGN_VOLTAGE 39` | 2013-2014 | charger input and regen node ADC | FR-23, FR-49 |
| `AG105_ADDR 0x30` and register constants | 2462-2477 | Ag105 Table 7 map | FR-02 (removed) |
| `AG105_SETTLE_MS 500u` | 2484 | Ag105 boot window | FR-02, FR-23 (replaced by `T_REGN_MAX`) |
| `FC_CHARGE_ALLOWED 0` | 2616 | gates the cruise-branch `assertFcChargeEnable(true)` | FR-05 |
| `AG105_VBATN_ISOLATED` / `ag105VbatnIsolatedFlag` | 5078-5085 | regen/charger-feed gate (VBat- tied to GND) | FR-02 (renamed `CHG_RETURN_VERIFIED`) |
| `setup()` pin defaults | 6706-6729 | pin 6 `INPUT`; pins 27-32 `OUTPUT` LOW; pin 5 `OUTPUT` LOW; pin 9 `INPUT_PULLUP` then `OUTPUT` LOW | FR-01, FR-49 |
| `FAULT_SWITCH_CONFLICT` check | 7413-7418 | latches on FC_CHARGE with BT_BUS **or** REGEN | FR-13 (REGEN term removed) |
| Ag105 GENSTAT 5/6/7 fault latch | 7438-7449 | `ERR_CHARGER_STAT` | FR-02 (replaced by REG20/21 faults, FR-13 G3) |
| State 98 `'4'` (REGEN raw toggle, guarded by `ag105ChargerFeedRefused()`) | 8689-8701, 11542 | bench REGEN | FR-18 |
| State 98 `'5'` (FC_CHARGE through the guard) | 8702 | bench FC charge | FR-18 (routed through T2) |
| State 98 `'N'` (Ag105 MPPT threshold) | 8846 | fw v24 tool | FR-02 (removed) |
| State 98 `'J'` (Ag105 commissioning; `parseJLine()`) | 8855, 12097 | fw v37 tool; `J 4` toggles pin 5 raw at 12153 | FR-18 (new `J` = FC-window bench session) |
| `assertFcChargeEnable()` | 12743 | FC_CHARGE guard; forces REGEN LOW | FR-06 |
| `chargingControl()` | 15289 (MPPT writes 15304-15554) | Ag105 MPPT release logic | FR-05 |
| `initAg105Charger()`, `pollAg105()`, `ag105IsReady()` | 15648, 16064, 16232 | Ag105 driver | FR-02 |
| `chargerHasPower()` | 16244 | FC_CHARGE OR (REGEN AND MOT_PWR) | FR-23 (becomes V_chg > 10.2 V AND FLT HIGH) |
| `initChargerI2cPins()` (`Wire.begin()`) | 16289-16293 | blocking Wire | FR-07 (interrupt-driven LPI2C) |
| `I_charge` | 3803 | Ag105 reg 0x06 | FR-20 (latest BQ25798 IBAT) |

Two facts from this baseline matter for every later item. First, the string `INPUT_PULLDOWN` and `INPUT_DISABLE` occur
nowhere in the ino (grep at `330344c`), so FR-01's pad modes are new code on either path. Second, D.2 says "fw v37 State 98
`4` toggles pin 5 raw"; the raw pin-5 toggle is the `J` sub-command `4` at ino 12148-12153, not the top-level `'4'` key,
which toggles REGEN (ino 8689). The hazard D.2 names is real; only the key reference is imprecise.

### 5.2 Firmware requirements that carry over unchanged

The CCB keeps the round-3 permit network, the eFuse, the monostables, the comparator taps and the MB rework. The
firmware therefore sees the same pins, the same signals and the same failure directions. Table 5.1 lists every FR of
G.2 that carries over with no change of text or scope.

**Table 5.1. FRs unchanged on the CCB.**

| FR | Topic | Label | Why it is unchanged |
|---|---|---|---|
| FR-02 | Remove the Ag105 driver; `AG105_VBATN_ISOLATED` -> `CHG_RETURN_VERIFIED` | IC-independent | The Ag105 is removed on both paths. The gate keeps its function: it is set only after the build check of the charger return (A.6: VIN- = VBAT- = GND is acceptable because the BQ25798 senses current high side) |
| FR-03 | BQ25798 driver, images, never-write list incl. REG14 | BQ25798-specific | The register map does not depend on the packaging (§5.5). Board-dependent image constants are listed in §5.5.2 |
| FR-04 | `chargerModeTick()`, T1-T9, I-1..I-9 | BQ25798-specific (mixed) | Same sequence. The T1 step-6 and step-8b proofs now read IC-pin senses on the same board (wording only) |
| FR-05 | `chargingControl()` gates | IC-independent | System rule, no packaging term |
| FR-06 | `assertFcChargeEnable()`; window latch owns BT_BUS LOW / FC_BUS HIGH | IC-independent | RT1987 sequencing on the MB |
| FR-07 | Single interrupt-driven LPI2C engine, transaction caps, bus clear | BQ25798-specific (numbers), IC-independent (engine) | The normative caps (0.35 ms at 400 kHz, 0.5 ms at 100 kHz, edge to write <= 1.5 ms) are firmware budgets. The shorter on-board bus can only add margin |
| FR-09 | FCCEIL consistency | BQ25798-specific | Same register semantics |
| FR-10 | I_BT trip while BT_BUS is commanded LOW | IC-independent | MB INA253 |
| FR-11 | FC-window power balance with the T-F-15 ground offset | IC-independent | The charger input and battery returns still enter MB GND at CHG pads 4/14/15 (A.6), so the pin-22 offset term stays |
| FR-12 | Two-part boot self-test | IC-independent | Same taps and comparators |
| FR-13 | Port the fw v37 rev 2 `J` guards; switch-conflict term (ino 7413-7418) drops REGEN | IC-independent (G1, G2), BQ25798-specific (G3 = REG20/21) | Guards act on MB currents and on the charger fault flags |
| FR-14, FR-15, FR-15b, FR-16, FR-17 | FC-window governor, purge scheduler, pre-emption, early purge | IC-independent (IINDPM write BQ25798-specific) | Purge ruling of 2026-11-08 applies unchanged |
| FR-19 | State 99 per T7 | IC-independent | |
| FR-23 | `chargerHasPower()` and `regnExpected` | BQ25798-specific (REGN) | REGN timing and EN_HIZ behaviour are IC properties. The eFuse still removes the IC's VBUS while pin 38 (board side of the eFuse) stays high. `regnExpected` stays false in battery-only mode even when REGN is up from the TS ADC channel ([DS] §7.3.4.1, Table 2.8), so CHG_CE_RB is ignored there |
| FR-25 | Regen derate near CV | BQ25798-specific | |
| FR-26 | `purgeRescueOk()` | IC-independent | |
| FR-27 | `loop()` budget <= tw_HB,min / 4 | IC-independent | |
| FR-28 | Heartbeat as a completion token | IC-independent | |
| FR-29 | Pin 34 stays GPIO; WDOG1_B on pin 20 | IC-independent | |
| FR-30 | FC-window POR detection | BQ25798-specific | The expected REG19 ICO_ILIM band is a board constant (§5.5.2, item 4) |
| FR-32 | Flagged protocol extension (Pi-commanded IINDPM ceiling) | mixed | |
| FR-33 | Slow STAT backstop | BQ25798-specific | Decided by T-B-18 on the IC, not on the EVM |
| FR-34, FR-35 | BT_OK cross-check; UVB plausibility | IC-independent | |
| FR-36 | REG14 guard | BQ25798-specific | |
| FR-38 | BT sense plausibility | IC-independent | |
| FR-39 | Window intent and termination | mixed | On the CHG_STAT 111b edge, `chgFull` waits for the FR-51 termination-edge check (§5.6, FR-51 item 4) |
| FR-40 | `BT_CAL_GAIN`, interim VREG 8.32 V | IC-independent (gain), BQ25798-specific (VREG image) | |
| FR-41, FR-42, FR-43 | Brake feed-forward, pre-emption backstop, flash gate and watchdog windowing | IC-independent (IINDPM ramp BQ25798-specific) | |
| FR-45, FR-46 | 1 kHz timer domain; same-transaction limit read-back | IC-independent; BQ25798-specific | |
| FR-48 | D-BT-SQ short check | BQ25798-specific detection, IC-independent hazard | D-BT-SQ is an MB part. The battery-only VBAT ADC validity threshold is 3.2 V with the TS channel on ([DS] §7.3.10, §7.3.4.1). The 2.9 V of [WD] FR-48(a) and [WD] B.5 applies only with TS_ADC_DIS = 1, which the image never writes (FR-50). The pack (7.4-8.4 V) and the keep-alive (<= 4.46 V) clear it, but the keep-alive margin is 1.26 V, not 1.56 V. Each one-shot powers REGN and raises /CE (Table 2.8, T-D-15) |
| FR-49 | EN pad check, pins 38/39 over-range | IC-independent | |

The G.3 watchdog specification (R5, 50 ms RTWDOG fed by the FR-28 token, WDOG1_B on pin 20 only) carries over
unchanged. It is IC-independent. T-W-01 still gates every FC-charge window (G.3 r4).

### 5.3 Firmware requirements that change because the EVM, the EIB and the leads are gone

Table 5.2 lists every FR whose text or scope changes. No FR gains a new safety obligation from the change of packaging,
and none is deleted. The changes remove failure modes that existed only in the ribbon, the E-leads and W1-W7.

**Table 5.2. FRs that change scope on the CCB.**

| FR | Round-3 text that changes | Proposed custom-board text | Label |
|---|---|---|---|
| FR-01 | Readback senses are "far-end" (EIB U203/U204 at the EVM pin); pin 22 note cites "37 kOhm source" | Same pad modes (pins 7, 16, 23, 33, 34 `INPUT_PULLDOWN`; 35 `INPUT_PULLUP`; 22 `INPUT_DISABLE`; 27-32 driven `OUTPUT`). Replace "far-end" by "IC-pin sense" in comments and in the CSV notes (§5.4). The IMON source network is unchanged on the CCB (R305 27.4 kOhm, R329 10.0 kOhm, C329 1.0 nF; §2.5.3), so the round-3 "37 kOhm source" (27.4 + 10.0 kOhm) note stays | IC-independent |
| FR-08 | (a) and (b) evaluate the "far-end" ILIM and /CE senses; the fault catalogue includes E4/E6 lead-off and ribbon conductor faults | Identical logic and gating. The senses still sit on their own trace to the IC pin (separate from the drive trace), so a cracked drive joint is still observed. The constants TW_HB_MAX and TW_QQ_MAX are re-measured on the CCB monostables (T-C-10); the provisional 47 ms / 464 ms stay until then. The lead-off rows of the B.6 fault table become open-joint rows of the CCB fault table | IC-independent (logic), BQ25798-specific (ILIM/REGN gating) |
| FR-18 | `V` prints "readbacks (incl. far-end senses)" | `V` prints the IC-pin senses and, in addition, the BQ25798 TDIE ADC reading (new FR-50) | mixed |
| FR-20 | `chg_ctrl` bits "ILIM rb (far end)", "CE rb (far end)" | Bit names "ILIM rb (IC pin)", "CE rb (IC pin)". Bit positions unchanged. Optional TDIE byte: decide in the v5 `protocol-bump` round (§5.7, WQ item 6) | mixed |
| FR-21 | HIL plant models EIB/ribbon faults | Remove the ribbon and E-lead fault injections; keep the permit-logic model, the heartbeat and the one-shot | mixed |
| FR-22 | Tests include ribbon 3-4 / 4-5 shorts (via FR-44) and E-lead faults | Replace those cases with "pin 6 stuck LOW" and "pin 6 follows CE_DRV" (adjacent-trace or solder-bridge short), and with open-joint cases on the sense traces. All other cases stay | IC-independent |
| FR-31 | TODO-to-test map names EVM tests (T-A-02, EVM rows of T-F-12) | Map the same TODOs to the CCB tests (bare-board net check instead of T-A-02; T-B-16/T-B-19 re-scoped to the on-board power stage, §6.3) | mixed |
| FR-37 | Diagnostic label "carrier rail lost" via EIB evidence | Label "CCB 3V3 rail lost"; the rail is fed only through T6/R175 (A.4). The EIB rail-loss row of B.6 (both ribbon 3V3 conductors open) no longer exists | IC-independent |
| FR-44 | STAT plausibility motivated by ribbon shorts 3-4 / 4-5 and EIB R275 | Keep the rule (pin 6 against REG1C CHG_STAT and P5 for > 2 s refuses QUAL). Its motivation becomes a stuck or bridged pin-6 net and a pin-6 firmware misconfiguration (OUTPUT HIGH). The CCB schematic keeps the series resistor as R475 1.00 kOhm (Table 2.5 and Table 2.6), so STAT LOW still reads about 0.31 V at pin 6 (D.3 row 6, [WD] H.21); the threshold logic is unaffected (i.MX VIL 0.99 V) | BQ25798-specific (STAT encoding), IC-independent (rule) |
| FR-47 | Cause list "OVN, an E5 lead-off or a U201 1Y stuck open" | Cause list "OVN, an open /CE drive joint or the open-drain /CE driver stuck open". Latching behaviour unchanged | IC-independent (rule), BQ25798-specific (/CE) |

Three round-3 timing margins were set by lead length and disappear as constraints. None of them is a firmware
constant, so no firmware value changes:

1. The W7 I2C ground offset of <= ~20 mV at 3.1 A (A.6, H.11) against the 0.4 V VIL margin. On the CCB the I2C
   reference is the board plane. The 2.7 kOhm MB pull-ups (PM9) stay, because the 400 kHz budget in FR-07 assumes them;
   whether 10 kOhm would now suffice is TODO(measure: SCL rise time on the CCB, T-D-03).
2. The E-lead maxima (A.5, 20-85 mm) and the ribbon length (0.30 m). Their only firmware effect was through the U203/U204
   thresholds that FR-08 relies on; those thresholds are re-derived for the CCB divider values (§5.4, row 33).
3. The W5 adjacent-conductor short analysis (A.3). Its firmware consequences were FR-44 and the FR-08 trip directions; both
   remain correct for on-board shorts.

### 5.4 Pins: new, freed and changed (IO CSV proposals)

#### 5.4.1 Pin budget (IC-independent)

The CCB needs **no new Teensy pin** beyond the round-3 set and **frees none**. The reason is structural. The 22 CHG
holes carry only pins 5, 6, 18 and 19 to the Teensy (A.2: CHG pads 11, 3, 8, 7); the other header pins are mechanical
anchors with no MB copper (A.2 pins 1, 2, 5, 6, 9, 12, 16, 17, 20, 21, 22). Every other Teensy signal therefore still
needs a flying tap (A.4, T1-T22), whatever the charger packaging is.

Candidates considered and rejected:

| Candidate | Purpose | Decision | Reason | Label |
|---|---|---|---|---|
| `CHG_INT` (BQ25798 /INT) | interrupt on fault flags | Not assigned | The only spare pins are 2 and 8, both on encoder nets (A.4); pin 20 is reserved for WDOG1_B (G.3). The 20 ms I2C poll (G.1 slot 0) already reads the flag registers | BQ25798-specific |
| CCB temperature input | thermal guard next to the LM1084 | Not assigned | The BQ25798 TDIE ADC is already in the continuous scan (G.1 REG2E-0x30 row); new FR-50 reads it over I2C | BQ25798-specific |
| Drop pin 33 or pin 7 | the senses are now on the same board as the IC | Rejected | Both prove the state at the IC pin; an open drive joint or a stuck driver is still possible on a single board (B.6 fault table, re-scoped) | IC-independent |
| Fan tachometer or fan enable (r2) | bench fan supervision (§1.6.3) | Not assigned | The fan runs from the bench supply or its own regulator, not from a Teensy-controlled source. With the fan stopped, the FR-50 TDIE trip acts (the derate alone does not hold 100 C), and the CCB node time constant of 164-303 s gives it minutes to act ([LC] §8.7). A tachometer would need one of the spare pins 2 and 8 | IC-independent |
| `PURGE_SENSE` on pin 2 | H-20 purge-valve sense | Conditional, unchanged | Only if T-E-02 adopts it and T-A-01b clears pin 2 (D.3 conditional row) | IC-independent |

#### 5.4.2 Proposed CSV diff (IC-independent unless marked)

The diff below is against the committed CSV (Ag105 era). A row marked "= D.3" is the D.3 text verbatim. A row marked
"D.3 + edit" differs from D.3 only in the words that name the EVM, the EIB, the carrier or the ribbon. Refdes in notes are
replaced by function names, because the CCB refdes are not yet assigned. The CSV is authoritative: amend it first,
in the same commit as the firmware pin map and the host tests.

```diff
# row 5  (D.3 + edit; BQ25798-specific meaning: /CE)
-5,Output,Digital,Charger MPPT disable,MPPT_DISABLE,
+5,Output,Digital,Charger arm (BQ25798 /CE on the charger board),CHG_ARM,"HIGH = charging allowed (the charger board ANDs it with the heartbeat and OVN; an open-drain driver pulls /CE LOW). LOW or high-Z = inhibited (47 kOhm pull-down on the charger board). Was MPPT_DISABLE (Ag105 removed)"
# row 6  (D.3 + edit; BQ25798-specific encoding)
-6,Input,Digital,Charger status,CHARGER_STAT,
+6,Input,Digital,Charger status (BQ25798 STAT),CHARGER_STAT,"Open drain: LOW = charging, HIGH = complete/disabled/HIZ, 1 Hz blink = fault (SLUSDV2C Table 7-11). 10 kOhm pull-up to 3V3 on the charger board; 1.00 kOhm in series on the charger board (STAT LOW reads ~0.31 V; limits the STAT sink to 3.3 mA if pin 6 is driven HIGH). Plausibility-checked against REG1C CHG_STAT and CHG_ARM (FR-44)"
# row 7  (D.3 + edit)
-7,Output,Digital,Enable optical sensor,ENC_ENABLE,No longer in use
+7,Input,Digital,Charger /CE readback,CHG_CE_RB,"HIGH = /CE HIGH at the BQ25798 pin (charging inhibited). Comparator on the charger board on its own sense trace; reaches the Teensy via the vacated MB ROS pad 2 (ROS removed; ENC_ENABLE retired 2026-08-16). INPUT_PULLDOWN, no pull-up on the net: a dead source reads LOW = /CE LOW. Evaluated only while regnExpected (FR-23)"
# row 10 (new; D.3 + edit; BQ25798-specific: ILIM POR qualification)
+10,Output,Digital,Charger input-qualification trigger,CHG_QUAL,"Rising edge starts a hardware one-shot (0.20-0.46 s, TODO(calibrate: T-C-10 on the charger board)) that releases ILIM_HIZ only while FC_CHARGE is LOW; cleared while CHG_ARM is HIGH. Raise only after EN_CHG = 0 is read back; LOW whenever CHG_ARM changes. 47 kOhm pull-down"
# row 16 (new; = D.3)
+16,Input,Digital,Charger FC-window permit readback,CHG_H2_RB,"H2c = FC_CHARGE AND BTB_OFF AND BT_OK AND FCI_OK (= 1 unless the U117 option is fitted) AND ((UVB AND CHG_FCCEIL) OR (H1 AND REGEN_ENABLE)); FC_CHARGE and REGEN_ENABLE are read by comparators as on only above 1.75-1.88 V (r6). INPUT_PULLDOWN"
# row 17 (new; = D.3; BQ25798-specific: IINDPM/ICHG)
+17,Output,Digital,Charger FC ceiling confirmed,CHG_FCCEIL,"HIGH only while the BQ25798 IINDPM/ICHG registers hold verified FC-window values. LOW blanks the converter in an FC window whenever V-MOT is not above 1.089 x VBUS with REGEN on. 47 kOhm pull-down"
# row 18 (edit not in D.3; proposed for consistency)
-18,Communication,I2C,SDA,SDA,Used for battery charger
+18,Communication,I2C,SDA,SDA,"Used for battery charger (BQ25798 on the charger board, I2C 0x6B; MB RSDA/RSCL 2.7 kOhm; no pull-ups on the charger board)"
# row 19 (D.3 + edit)
-19,Communication,I2C,SCL,SCL,Used for battery charger
+19,Communication,I2C,SCL,SCL,"Used for battery charger (BQ25798 on the charger board, I2C 0x6B; MB RSDA/RSCL 2.7 kOhm; no pull-ups on the charger board). Never route WDOG1_B here (AD_B1_00 ALT4): WDOG1_B goes to pin 20 only"
# row 20 (new; = D.3)
+20,Reserved,Digital,MCU watchdog output (WDOG1_B; R5 future work),WDOG1_B_RSVD,"Do not assign. WDOG1_B is routed only here (AD_B1_10 ALT1); never to pin 19 (SCL) or pin 34 (CHG_H1_RB). Left unconfigured until the R5 watchdog lands"
# row 21 (new; = D.3)
+21,Output,Digital,Charger heartbeat,CHG_HB,"Completion token: toggle only from the 1 kHz monitor tick after the FR-08 evaluation, the timed detectFaults() checks and a fresh ADC set have all completed; never from an ISR or once per loop(). No rising edge for TW_HB (20-46 ms, set by T-C-10) drops the charge enable and holds ILIM_HIZ in hardware. 100 kOhm pull-down"
# row 22 (new; D.3 + edit: eFuse part kept, IMON scaling per the charger-board resistor)
+22,Input,Analog,Charger input current (eFuse IMON),CHG_IIN,"eFuse IMON into the charger-board IMON resistor (TPS26630 27.9 uA/A into 27.4 kOhm = 0.764 V/A, as in round 3; the charger board keeps R305 27.4 kOhm); 10 kOhm + 1 nF to the pin. pinMode INPUT_DISABLE (pad keeper off) before the first analogRead"
# row 23 (new; = D.3)
+23,Input,Digital,BT boost current below the FC-window threshold,CHG_BTOK_RB,"HIGH = INA253 BT output below 19.75 mV (0.06-0.34 A worst case). INPUT_PULLDOWN"
# rows 27, 29, 32 (= D.3 r6 notes)
-27,Output,Digital,Fuel cell bus enable,FC_BUS_ENABLE,Allow fuel cell regulator to contribute to Vbus
+27,Output,Digital,Fuel cell bus enable,FC_BUS_ENABLE,"Allow fuel cell regulator to contribute to Vbus. Driven OUTPUT LOW early in setup(); never INPUT_PULLUP, never a pad keeper (RT1987 EN may turn on anywhere up to 1.4 V)"
-29,Output,Digital,Motor power enable,MOT_PWR_ENABLE,Allow power to flow to VESC / motor
+29,Output,Digital,Motor power enable,MOT_PWR_ENABLE,"Allow power to flow to VESC / motor. Driven OUTPUT early in setup(); never INPUT_PULLUP, never a pad keeper (RT1987 EN band up to 1.4 V)"
-32,Output,Digital,Battery sequencing enable,BT_SEQUENCE_ENABLE,"Must initialize in off state, turn on once system is powered up and does not need to be turned off after"
+32,Output,Digital,Battery sequencing enable,BT_SEQUENCE_ENABLE,"Must initialize in off state, turn on once system is powered up and does not need to be turned off after. Driven OUTPUT LOW early in setup(); never INPUT_PULLUP, never a pad keeper"
# row 28 (D.3 + edit: "CHG carrier U115 ... R120/R119" -> function names)
-28,Output,Digital,Battery bus enable,BT_BUS_ENABLE,Allow battery regulator to contribute to Vbus
+28,Output,Digital,Battery bus enable,BT_BUS_ENABLE,"Allow battery regulator to contribute to Vbus. EN net also read by the charger-board BTB_OFF comparator (10 kOhm series, 10 MOhm pull-up to 3V3). Never INPUT_PULLUP (that lifts the EN net to ~1.02 V, inside the RT1987 enable band). LOW is the FC-window loop barrier; never HIGH together with FC_CHARGE_ENABLE"
# row 30 (D.3 + edit)
-30,Output,Digital,Regen charging enable,REGEN_ENABLE,Allow regen power to flow to the battery charger
+30,Output,Digital,Regen charging enable,REGEN_ENABLE,"Allow regen power to flow to the battery charger. Also read by the charger-board RGN_ON comparator (1 kOhm series, divider 453k/1.00M, trip 1.75-1.88 V; 100 kOhm pull-down). Held HIGH through Run in the always-powered regen design (operator ruling 2026-11-05). Never INPUT_PULLUP, never a pad keeper (~0.95 V, inside the RT1987 enable band)"
# row 31 (D.3 + edit)
-31,Output,Digital,Fuel cell charging enable,FC_CHARGE_ENABLE,Allow Vbus (fuel cell) to flow to the battery charger. BT_BUS_ENABLE and REGEN_ENABLE *must* be turned off before this is turned on
+31,Output,Digital,Fuel cell charging enable,FC_CHARGE_ENABLE,"Allow Vbus (fuel cell) to flow to the battery charger. BT_BUS_ENABLE *must* be off before this is turned on, and the two are never on together. REGEN_ENABLE MAY stay on (operator ruling 2026-11-05, R7); requires the charger-board permit logic (FCC_OFF comparator below 0.39-0.44 V, FCC_ON comparator above 1.75-1.88 V). Never INPUT_PULLUP, never a pad keeper (~1.02 V, inside the RT1987 enable band)"
# row 33 (new; D.3 + edit; BQ25798-specific: ILIM_HIZ threshold)
+33,Input,Digital,Charger ILIM_HIZ readback,CHG_ILIM_RB,"HIGH = ILIM_HIZ above the comparator threshold at the BQ25798 pin (0.587-0.650 V, below VIL 0.75 V; the charger board keeps the round-3 divider and sense pull-up values; TODO(calibrate: confirm with the H.4 leakage re-run)). Comparator on the charger board on its own sense trace; an open sense trace reads HIGH; INPUT_PULLDOWN"
# row 34 (new; = D.3)
+34,Input,Digital,V-MOT above bus comparator readback,CHG_H1_RB,"HIGH = V-MOT > 1.089 x VBUS (+0.30 V hysteresis). Pad GPIO_B1_13: keep it GPIO, never WDOG1_B (ALT0). INPUT_PULLDOWN"
# row 35 (new; D.3 + edit)
+35,Input,Digital,Charger input eFuse fault,CHG_EFUSE_FLT,"Open drain, LOW = fault. INPUT_PULLUP (the Teensy pad is the only pull-up; no pull-up on the charger board), so an open tap reads no fault and keeps the interlock monitors armed. Plausibility-checked against the charger VBUS_PRESENT_STAT"
# row 41 (D.3 + edit)
-41,Input,Analog,Battery current measurement,BT_CURRENT,
+41,Input,Analog,Battery current measurement,BT_CURRENT,"INA253 BT output; also feeds the charger-board BT_OK comparator (10 kOhm series, 1 MOhm pull-up to 3V3) and MDAC-BT IOUT1"
```

Rows 0-4, 9, 11-15, 24-26, 36-40 are unchanged. Pin 8 stays unlisted and unconfigured (A.4: encoder net ENC_B with
RENC2). The D.3 conditional row for pin 2 (`PURGE_SENSE`) is unchanged.

Row 6 replaces the D.3 phrase "1.00 kOhm in series at the EIB" by "on the charger board". R275 was a ribbon limiter (B.6); the
CCB schematic keeps the same 1.00 kOhm part as R475 for a new reason (a pin-6 firmware misconfiguration,
Table 2.6), so the 0.31 V LOW level stays in the note.

### 5.5 Register map in use

#### 5.5.1 G.1 applies unchanged (BQ25798-specific)

G.1 is a property of the BQ25798, not of the EVM. The static image, the read-only REG14 verify, the mode images (regen,
raised, FC), the never-write list (REG0A, REG16, REG09 bit 6, REG0B-0D, REG47, REG14), the 20 ms I2C poll schedule and the
POR/WD detection carry over word for word. The I2C address stays 0x6B (DS §7.3.14). No register address or field changes.
One value changes: the ADC channel mask enables VBAT in every scan and the poll reads REG3B in every frame, for FR-51
(§5.6, FR-51 item 1).

#### 5.5.2 Board-dependent constants inside the register map (BQ25798-specific)

The following image values or checks depend on parts that the CCB, not the IC, fixes. The EVM fixed them through
jumpers and modifications (section C, EM1-EM25); the CCB fixes them by construction. Each is a firmware constant that
the CCB schematic must confirm.

1. **PROG strap and the VREG self-check.** G.1 checks REG01:02 = 0x03 0x48 (8.40 V, the 2S POR value) at the first read.
   This holds only if PROG selects 2S. DS Table 7-1 gives 6.04 kOhm for 2S at 1.5 MHz ([TID] §2.5). The EVM
   BOM lists R29 = 6.20 kOhm while its schematic shows 6.04 kOhm ([TID] line 265). The CCB fits
   6.04 kOhm 1 %. A wrong strap shows as a self-check failure, so the firmware check stays mandatory.
2. **Switching frequency.** G.1 writes REG13 = 0x01 (PWM_FREQ 0 = 1.5 MHz). PWM_FREQ is REG13 bit 5 and its POR value
   follows PROG ([TID] line 191). TI permits 1.5 MHz only with 1 uH and 750 kHz only with 2.2 uH
   ([TID] item 4). If the CCB chooses 750 kHz, the PROG value changes per DS Table 7-1
   (8.2 kOhm, see below) and the REG13 image becomes bit 5 = 1 (0x21). The firmware image
   and the PROG strap must agree; a mismatch is a VREG/inductor hazard, not only an efficiency loss. DS Table 7-1 (p.25)
   gives 8.2 kOhm for 2S at 750 kHz, which §2.1.3 names as the alternate.
3. **TS.** G.1 writes REG18 = 0x54 (TS active, TS_IGNORE 0) and allows "TS fixed through JP18 (EM18)". The CCB
   replaces JP18 by a build choice. Option A: pack NTC from J-NTC through header pin 13 with the DS bias network
   (RT1 5.24 kOhm REGN-TS, RT2 30.31 kOhm TS-GND for a 103AT NTC, DS p.46). Option B: a fixed divider that reads as a
   normal temperature. A missing thermistor disables charging (DS §7.3.6 item 1), so the firmware needs to know which
   option is fitted. The choice is T-E-09; until then the image stays 0x54 with option B fitted. The CCB schematic
   implements the choice as a population option: R525 10.0 kOhm TS-GND (option B) XOR R526 0 Ohm TS-TS_EXT (option A),
   with the EVM bias values R518 5.23 kOhm and R524 30.1 kOhm (Table 2.5, §2.5.5).
4. **ILIM_HIZ network and the REG19 band.** T1 qualification and FR-30 compare REG19 ICO_ILIM against the regen band and
   the FC clamp derived in H.4 from the EVM resistors (R21 = 0 ohm, R23 49.9 kOhm, R255 48.7 kOhm, R257 59.0 kOhm, R256
   200 kOhm). The CCB keeps the same values: R523 49.9 kOhm, R455 48.7 kOhm, R457 59.0 kOhm, R456 200 kOhm, and the
   same sense divider R458-R461 (§2.2.1, §2.5.5). R21 has no counterpart: Q403 drives R455 directly from
   REGN. The round-3 bands (regen 1.33-1.76 A, FC 0.65-0.95 A, held <= 0.11 V) therefore carry over as the starting
   constants of the board variant. Only the leakage list changes. TODO(calibrate: H.4 recomputed with the CCB
   leakage list, O-11).
5. **VAC inputs and ACDRV.** REG13 keeps ACDRV off and VAC_OVP stays at 26 V (REG10 VAC_OVP field 0h, which is also the
   POR value: REG10 reset = 85h, SLUSDV2C §7.5.1.13; rising threshold 25.2-26.8 V, EC), because 18 V (17.4-18.6 V) would trip
   at the measured V-MOT of 21.5 V ([TID] line 473). The CCB fits no ACFETs. SLUSDV2C Table 5-1 states for
   both VAC1 and VAC2: "Connect to VBUS if the ACFET1 and RBFET1 [ACFET2 and RBFET2] are not installed", and "Tie ACDRVx to
   GND" when no FET pair is installed. The CCB schematic follows this (decision D1 (§2.1.1)).
6. **D+/D-, /QON, SDRV.** REG11 = 0x00 stays (no BC1.2 or HVDCP detection). SDRV gets 1 nF to GND (DS rev C deleted the
   SDRV-to-BAT option; round-3 EM13 still used it, [TID] item 13). /QON has an internal pull-up and no
   firmware role. None of these changes a register image.
7. **Watchdog and REGN.** REG10 WATCHDOG 0.5 s and the 50 ms MCU watchdog of G.3 are unchanged. REGN still biases the
   /CE and ILIM_HIZ stages; the REGN delay T_REGN_MAX (FR-23) is re-measured on the CCB (T-B-20, T-B-11).

#### 5.5.3 Proposed variant constant (IC-independent mechanism)

Path A (EVM + CR + EIB) and the CCB share all FR logic. They differ only in the constants of §5.5.2 items 1-4 and in
the monostable widths of FR-08. The proposal is one compile-time selector, for example `CHG_HW_VARIANT` with the values
`CHG_HW_EVM_CR_EIB` and `CHG_HW_CUSTOM`. Each variant pins its own constant block, and a host test asserts each block. The
selector carries no default for a real-board build, so a build without it fails to compile. This follows the
`AG105_VBATN_ISOLATED` pattern (ino 5078-5085) and the project rule that the `.ino` is committed as flashed.

### 5.6 New firmware requirements proposed for the CCB

The integration of the power stage onto one board adds two risks that the round-3 FRs do not cover. They are listed as
FR-50 and FR-51 so that they extend G.2 without renumbering.

**FR-50. CCB temperature guard (BQ25798-specific detection, IC-independent hazard).** The CCB places the power
stage beside the LM1084 (4.83 mm tall, runs hot) and CO-5V. The power cell edge is 13.4 mm from the LM1084 courtyard,
and the CHG silk outline is 1.75 mm from it (§1.6.1; [MECH] items 6, 11). Read the
TDIE ADC in the existing slot-10 extended read (G.1 lists the TDIE conversion as interleaved in the continuous scan). When
TDIE exceeds `CHG_TDIE_DERATE_C`, lower ICHG to the 2.50 A image and close FC windows through T5. When it exceeds
`CHG_TDIE_TRIP_C`, drop P5 through T7 and latch until Idle. Both thresholds are TODO(measure: T-B-16 re-scoped, CCB
mounted on the MB with the LM1084 at its Run dissipation). The reading is REG41_TDIE_ADC (offset 41h, 16 bits, two's
complement, 0.5 C per LSB, fixed offset 0 C, range -40 to 150 C, POR value 0 C; SLUSDV2C §7.5.1.53, Table 7-66, p.124;
EC TDIE_ADC LSB 0.5 C). Because the POR value reads 0 C, the guard must ignore TDIE until the first completed conversion
after each charger POR. The conversion is disabled by TDIE_ADC_DIS, bit 1 of REG2F_ADC_Function_Disable_0 (offset 2Fh,
reset 0h, SLUSDV2C §7.5.1.43), which the image must leave at 0. The IC's own thermal regulation stays at its POR value; REG16 remains on the never-write list.

*FR-50 on the testbench (r2, proposal).* The bench fan cools the CCB in the design case, and FR-50 is the guard for a
stopped fan (operator statement, 2026-11-10; §1.6.3). The fan is not supervised: it has no tachometer and no Teensy pin
(§5.4.1). The model gives these figures ([LC] §8.7; §3.7.2a):

1. With the fan off at g 5 mm on a 25 C bench, T_J is 104-142 C at 2.7 W and 86-116 C at the 2.08 W derate image. The
   derate alone therefore does not hold T_J under 100 C at the upper end of the band, so the trip must act.
2. TREG (default 120 C, [DS] REG16) folds back the charge current by itself before TSHUT (150 C). FR-50 must act below
   TREG so that the firmware, not TREG, owns the response.
3. The CCB node time constant is 164-303 s fan-off. A stopped fan therefore takes minutes to reach the thresholds, far
   longer than the TDIE refresh, so the fan need not be proven on.

The proposed starting values are `CHG_TDIE_DERATE_C` about 95 C and `CHG_TDIE_TRIP_C` about 105-110 C, both
TODO(calibrate: fan-on and fan-off soak, M16 and T-K-20). The fan-on 2.9 W point (model 78-90 C at 25 C room air) must
stay below `CHG_TDIE_DERATE_C` with margin, so the soak sets the final values. With the fan on, the derate must not act
at 2.9 W. With the fan stopped, the trip must act before TREG_STAT (REG1D bit 2, [DS] Table 7-38) sets (item 1).

**FR-51. Battery-path continuity check (BQ25798-specific detection, IC-independent hazard).** The CCB carries the
3.21 A battery current through header pins 18/19 and 14/15 (A.2, A.8). On the testbench, handling and repeated
insertion can fret a socket contact (the r1 basis was a moving vehicle). A fretting header joint opens
the charger BAT node while the converter runs. FR-51 uses the BQ25798 VBAT ADC (REG3B, at the BATP sense, D8) and pin-25
V_batt (pack side of D-BT-SQ). The FR-48 Idle comparison uses the same two readings, so the code path is shared.

1. **VBAT refresh.** G.1 gives no VBAT refresh period ([WD] G.1 ADC row: "VBUS/VBAT/TS/TDIE interleaved at a lower
   rate"). The CCB image enables VBAT in every scan with IBAT and IBUS (3 x 6 ms = 18 ms at ADC_SAMPLE 10, [DS] §6.5
   tADC_CONV). VBUS, TS and TDIE stay interleaved, one channel per scan. The VBAT refresh period T_VBAT is therefore
   <= 24 ms, and IBAT and IBUS refresh in 18-24 ms instead of 12 ms (TODO(verify: T-B-14b timing)). Firmware reads REG3B in
   every 20 ms frame, in slot 10 with REG35-REG36 and REG41.
2. **Criterion (a), path drop.** While CHG_STAT reports trickle, pre-charge, CC, CV or top-off, compare REG3B with
   V_batt in each frame. The healthy difference at 3.21 A is 139-150 mV (RT1987 20 mOhm, pins 18/19 and the 14/15 return
   20 mOhm each, MB pour 3.4-6.8 mOhm), before the pin-25 gain error. `CHG_VBAT_AGREE_V` is therefore >= 0.15 V plus the
   T-E-13 residual and the measured T-K-17 drop (TODO(calibrate)). The VBAT_ADC accuracy is TODO(verify: DS EC).
3. **Criterion (b), open-path signature.** An open path drives the BAT node (C538/C539, 20 uF) to VREG within about
   6.5 us per volt at 3.1 A, and IBAT falls to about 0 A. Fault when REG3B >= VREG - 50 mV, IBAT_ADC < ITERM (200 mA,
   [WD] G.1 REG09) and V_batt < VREG - `CHG_VBAT_OPEN_V`, while charging is commanded. The IBAT term prevents a false trip
   on a healthy pack in CV, whose current exceeds ITERM until termination. `CHG_VBAT_OPEN_V` covers the ADC errors only:
   TODO(calibrate: T-E-13), 50 mV as the planning value.
4. **Termination edge.** An open path also makes the IC terminate (CHG_STAT 111b, [DS] §7.3.9.1). FR-39 would then
   declare `chgFull` and close the window within one 20 ms poll ([WD] FR-39), before the 100 ms persistence of
   criterion (a). On the 111b edge, FR-39 therefore defers `chgFull` until FR-51 has evaluated criterion (b) on the first
   REG3B read taken at least T_VBAT after the edge (<= 44 ms). If criterion (b) holds, FR-51 sets the fault instead of
   `chgFull`. A healthy termination at ITERM leaves V_batt within 200 mA x 47 mOhm = 9 mV of REG3B.
5. **Action.** When criterion (a) holds for 100 ms (at least four fresh conversions), or criterion (b) holds on one fresh
   read, drop P5, set `chg_flags.bat_path_fault` and refuse charging until Idle. The worst-case latency of criterion (a)
   is T_VBAT + 6 ms + 20 ms + 100 ms = 150 ms.
6. **Published blind band.** Criterion (a) alone is blind for a pack OCV above VREG - `CHG_VBAT_AGREE_V` (8.20 V at
   VREG 8.40 V and 0.20 V; 8.12 V at the interim 8.32 V). Criterion (b) narrows the band to OCV above
   VREG - `CHG_VBAT_OPEN_V` (8.35 V and 8.27 V at 50 mV). Inside that band, a fretting joint that closes carries at most
   0.05 V / (43.4 mOhm + 10 mOhm) = 0.94 A (healthy path plus the minimum pack DCIR, [WD] H.21).

Neither FR needs a new pin or a new register. FR-51 changes the G.1 ADC channel mask values (REG2F/REG30) and adds a
deferral to FR-39. Both add flag bits to the v5 `chg_flags` field (FR-20).

### 5.7 Bodge record text for CLAUDE.md (proposal, not an edit)

The text below adapts D.4 to the CCB. It belongs under the never-rotated hardware records once the board is fitted.
Bracketed fields are filled at build time.

```
### Hardware bodge record (20XX-XX-XX): Ag105 removed, custom BQ25798 charger board fitted in the CHG holes

- The Silvertel Ag105 (`CHG`) is desoldered. A custom 4-layer charger board [revision, fab, copper weight] carries the BQ25798
  (I2C 0x6B) and its power stage, the input eFuse [TPS26630 or substitute] with output Schottky, the comparators
  H1/UVB/BT_OK/BTB_OFF/FCC_OFF/FCC_ON/RGN_ON, the permit logic, the QUAL one-shot and heartbeat monostables, the open-drain
  /CE driver with two independent /CE pull-ups to REGN, the two-switch ILIM_HIZ release from REGN, the FC clamp leg, and the
  /CE and ILIM_HIZ senses on their own traces at the IC pins. It sits in the 22 CHG holes on one 1x10 and one 1x12
  header strip [soldered (option S) | plugged into 1x10 + 1x12 socket strips soldered once into the MB holes (option K)]
  and extends past the footprint toward +y [overhang region, foot positions (23.20, 70.64) and (32.20, 70.64), foot type]. No off-board EVM, no
  EVM interface board, no ribbon, no W1-W8 leads.
- PROG = 6.04 kOhm (2S, 1.5 MHz) [or the 750 kHz value with the 2.2 uH inductor]; firmware REG13 image and the
  `CHG_HW_CUSTOM` constant block match it. TS = [pack NTC via J-NTC | fixed divider]. SDRV = 1 nF to GND. No ACFETs,
  no ship FET.
- C-D8 and C-D10 are 10 uF >= 35 V 0805 (were 25 V GRM21BZ71E106KE15L).
- MB RSDA/RSCL are 2.7 kOhm (were 10 kOhm). MB ROS is removed; Teensy pin 7 (ex ENC_ENABLE) is the /CE readback, tapped at ROS
  pad 2. Pin 8, RENC2 and the encoder nets are untouched. Teensy pin 20 is reserved for WDOG1_B.
- [Insulation and tail rules under the charger board, from §1.3.5 and §1.5 of the design document.] A thermocouple sits on the MB
  VBT trace [yes | no].
- BQ29200 (BAL) pin 8 OUT (net BAL-NOK) is tapped with a 30 AWG wire to the charger board (T22) and gates the charger in
  hardware (cell > 4.35 V for 1.6-4.9 s, an open tap or an unplugged balance lead -> /CE HIGH and ILIM_HIZ held); there is
  still no firmware BAL-NOK input. Charging needs the balance lead (J-BL) plugged. Every RT1987 EN pin is a driven output,
  never INPUT_PULLUP.
- Bodge parts and wires: R170/R171 10.0 kOhm at C-D6 pad 1 (V-MOT) and C-D2 pad 1 (VBUS) feeding the charger-board dividers; a
  Kelvin wire from the SNS-BT GND/REF1 pad; taps into the J1/J2 breakout for the EN nets of pins 28/30/31, 3V3 (through a
  68 ohm limiter), BT-CURR and pins 10/16/17/21/22/23/33/34/35; T1 and T17 twisted with GND shields bonded at the charger board
  only. No W8, no trace cut.
- Keep-alive: [not fitted | fitted] (decided by T-B-09).
- Charger VREG: [8.32 V interim | 8.40 V after T-E-13, BT_CAL_GAIN = ...]. FC-charge windows: [disabled until T-W-01 |
  enabled after T-W-01 on <date>].
- IO CSV rows 5, 6, 7, 10, 16, 17, 18, 19, 20, 21, 22, 23, 27, 28, 29, 30, 31, 32, 33, 34, 35, 41 amended in lockstep.
  Any rework that removes the charger board must revert firmware, CSV and tests together.
```

The record differs from D.4 in four places: the CCB paragraph replaces the carrier, EVM and ribbon paragraphs; the
section-C EVM modification list is deleted; the PROG/TS/SDRV line is new; and row 18 joins the amended-row list.

### 5.8 WORK_QUEUE.md items (proposal, not an edit)

The newest WORK_QUEUE section is `0l` (fw v37 noise round, 2026-11-05). The proposal is a new section `0m`.

```
## 0m. Custom BQ25798 charger board (opened 2026-11-10, planning only) - firmware and CSV deltas against round-3 Path A

Design record: docs/charger_bq25798_custom_board_2026-11-10.md. Nothing below is started; every item waits for the operator's choice
between Path A, Path B and the charger board, and for the parallel charger-IC search.

1. CSV amendment (IC-independent): apply the section-5.4.2 diff in the same commit as the firmware pin map and the
   host tests. Gate: the charger board is built and passes its bare-board net check. Run the pinmap-audit skill after it.
2. Firmware round spec (orchestrated-feature): G.2 FR-01..FR-49 with the section-5.3 deltas, plus FR-50 (TDIE guard)
   and FR-51 (battery-path continuity). Same round for Path A and the charger board.
3. Variant selector `CHG_HW_VARIANT` (IC-independent mechanism): one constant block per hardware variant (PROG/REG13,
   TS option, ILIM_HIZ bands for T1/FR-30, TW_HB_MAX, TW_QQ_MAX, U203-equivalent threshold); no default on real-board
   builds; host tests pin each block.
4. Host tests (FR-22 delta): drop the ribbon 3-4/4-5 and E-lead cases; add pin-6 stuck-LOW, pin-6-follows-CE_DRV,
   open sense-joint cases, FR-50 and FR-51 cases.
5. HIL plant (FR-21 delta): remove ribbon/E-lead fault injection; add TDIE and a battery-path open event.
6. Telemetry v5 (protocol-bump): rename the two "far end" chg_ctrl bits; decide whether a TDIE byte joins v5;
   add bat_path_fault and the TDIE derate flag to chg_flags. Pi bridge in lockstep.
7. Test registry deltas: drop T-A-02, T-C-13; re-scope T-C-05, T-C-07, T-F-11, T-B-16, T-B-19; keep T-C-10 and run it
   on the charger-board monostables before TW_HB_MAX / TW_QQ_MAX are fixed.
8. Thermal measurement (TODO(measure)): charger board on the MB with the LM1084 at Run dissipation; sets CHG_TDIE_DERATE_C
   and CHG_TDIE_TRIP_C (FR-50). r2: the measurement is the fan-on and fan-off soak (M16, T-K-20 with its fan-on leg T-K-14); starting values about
   95 C and 105-110 C (§5.6, FR-50).
9. I2C pull-up check (TODO(measure)): SCL/SDA rise time at 400 kHz on the charger board with the 2.7 kOhm MB pull-ups.
10. Coordination with the charger-IC search: if another IC is chosen, keep items 1, 3 (mechanism), 4 (IC-independent
    cases), 7 (IC-independent tests), 8, 9 and replace the BQ25798-specific FRs per the section-5.9 interface table.
11. Record-keeping: the D.2 statement that "State 98 4 toggles pin 5 raw" means the J sub-command 4 (ino 12148-12153);
    correct it when the wiring design is next revised.
```

### 5.9 Effect of a different charger IC

#### 5.9.1 The IC-independent interface (IC-independent)

The round-3 permit network reduces to a small set of signals between the Teensy, the MB and the charger
([WD] B.1). Table 5.3 classifies each one. A substitute IC that provides the
listed hardware properties keeps every IC-independent Teensy pin, CSV row and FR unchanged.

**Table 5.3. Interface signals and their dependence on the charger IC.**

| Signal / function | Teensy pin | Stays with another IC? | Requirement on a substitute IC |
|---|---|---|---|
| CHG_ARM (charge enable, ANDed with heartbeat and OVN) | 5 | Yes (signal); meaning re-bound to the IC's inhibit pin | A charge-inhibit pin that inhibits when undriven or when its driver is unpowered |
| Converter release / hard converter-off (ILIM_HIZ hold + release in round 3) | none (hardware) | Function stays; circuit is IC-specific | A pin that stops switching independent of registers (round 3 asks T-B-21 for the BQ25798) and keeps the IC's bias rail on |
| FC current clamp select (RFC_OFF) | none (hardware) | Function stays if the IC has a pin-set input limit | Pin-programmable input current limit, or a hardware FC-current shed (U117 option) |
| CHG_HB heartbeat | 21 | Yes | None (monostable on the board) |
| CHG_QUAL one-shot | 10 | **No**: BQ25798 ILIM POR qualification | Drop if the substitute IC needs no input-qualification window; free pin 10 |
| CHG_FCCEIL (FC register image verified) | 17 | Yes, if the IC sets its limits by register | Register-programmable IINDPM/ICHG with read-back |
| /CE and ILIM readbacks at the IC pin | 7, 33 | Yes (renamed to the substitute's inhibit and hard-off pins) | Thresholds re-derived from the substitute's VIL/VIH |
| H1, H2c, BT_OK readbacks | 34, 16, 23 | Yes | None |
| eFuse IMON and FLT | 22, 35 | Yes | Input-side parts rated >= 35 V (§2.1.4) |
| RT1987 EN pins and pad rules | 27-32 | Yes | None |
| STAT | 6 | Pin stays; encoding and FR-33/FR-44 are IC-specific | An open-drain status output, or drop FR-33 |
| I2C | 18, 19 | Pins stay; driver, address and register map are IC-specific | Address free on the bus; a watchdog that reverts to safe limits |
| OVN (BQ29200 hardware pack-OV permit) | none | Yes | None |
| MCU watchdog (WDOG1_B) | 20 (reserved) | Yes | None |

#### 5.9.2 What is replaced with another IC (BQ25798-specific)

The following round-3 content is bound to the BQ25798 and must be rewritten for any substitute IC:

1. FR-03, FR-46 and the whole of G.1: the driver, the static and mode images, the never-write list, the REG14 guard
   (FR-36) and the byte-order self-check.
2. FR-23 `regnExpected` and every REGN-anchored gate (FR-08(b) gating, T1 step 5). The substitute needs an equivalent
   proof that its internal bias rail is on before an inhibit-pin sense is trusted.
3. FR-04 T1 steps that depend on the ILIM POR qualification (QUAL, REG19 band), FR-09 and FR-30.
4. FR-25 (CV detection through CHG_STAT), FR-33 and FR-44 (STAT encoding), FR-48 detection method (VBAT ADC in
   battery-only mode).
5. FR-50 and FR-51 detection methods (TDIE and VBAT ADC). Their hazards stay and need the substitute's equivalent readings,
   or a board thermistor and an analog input, for which no spare Teensy pin exists (§5.4.1).
6. The image constants of §5.5.2 and the variant block of §5.5.3.

The IC-independent remainder (pin map rows 7, 16, 21-23, 27-35, 41; FR-01, FR-05, FR-06, FR-10-FR-17, FR-19, FR-26-FR-29,
FR-34, FR-35, FR-38, FR-42, FR-43, FR-45, FR-49; G.3) carries over without change.

### 5.10 Changes required in files that this document does not edit

Table 5.4 lists every change that the CCB path needs in existing repository files. None of these changes is applied. Each
change waits for the operator's choice of the CCB path, except rows 7 and 8, which also apply to Path A.

| # | File | Change | Trigger | Label |
|---|---|---|---|---|
| 1 | `references/Scale Car Teensy IO - IO.csv` | Apply the diff of §5.4.2 (rows 5, 6, 7, 10, 16-23, 27-35, 41) in the same commit as the firmware pin map and the host tests; run the pinmap-audit skill after it | The CCB is built and passes T-K-03 | IC-independent (rows 5, 6, 10, 17, 33 BQ25798-specific) |
| 2 | `teensy_controller/teensy_controller.ino` | Firmware round per [WD] G.2 FR-01 to FR-49 with the deltas of §5.3, the new FR-50 and FR-51 (§5.6), and the variant selector `CHG_HW_VARIANT` (§5.5.3) | Same commit as row 1 | Mixed |
| 3 | `test/` (host-native suite) | Drop the ribbon and E-lead cases; add pin-6 stuck-LOW, pin-6-follows-CE_DRV, open sense-joint, FR-50 and FR-51 cases; pin each `CHG_HW_VARIANT` block (§5.8 items 3-4) | With row 2 | Mixed |
| 4 | `CLAUDE.md` | Add the bodge record of §5.7 under the never-rotated hardware records. The pin-map table of CLAUDE.md §1 follows the CSV amendment of row 1 | The CCB is fitted to the vehicle | IC-independent |
| 5 | `WORK_QUEUE.md` | Add section `0m` as proposed in §5.8 | Operator choice of the CCB path | IC-independent |
| 6 | `PLAN.md` §6b and the Pi bridge | Telemetry v5 through the protocol-bump skill: rename the two "far end" `chg_ctrl` bits, add `bat_path_fault` and the TDIE derate flag to `chg_flags`, decide on a TDIE byte (§5.3 FR-20, §5.8 item 6) | With the firmware round | Mixed |
| 7 | `docs/charger_bq25798_wiring_design_2026-11-05.md` | (a) EM13 uses the SDRV-to-BAT option that SLUSDV2C rev C deleted; correct it to 1 nF 50 V from SDRV to GND (O-14). (b) D.2 says "State 98 `4` toggles pin 5 raw"; the raw toggle is the `J` sub-command `4` (ino 12148-12153) (§5.8 item 11). (c) Add a cross-reference to this document as a third path. (d) FR-48(a) and B.5 cite 2.9 V for battery-only ADC validity (SLUSDV2C §7.3.10); with the TS channel on, the threshold is 3.2 V, and REGN then turns on (§7.3.4.1); state the REGN pulse and the 1.26 V keep-alive margin (§2.6.1, FR-48 row of §5.2). (e) The G.1 ADC row gives no VBAT refresh; state the FR-51 mask (§5.6, FR-51 item 1). (f) Only if T-K-09 step (5) fits C336/C337 on the CCB: F.4 step A says "H2c = 0 within the U120 propagation delay" (2-4 us). With 100 pF fitted, the FCC_ON fall lags by up to 21.6 us more, so step A then reads "within 25.6 us" (§2.5.6). The lag is 1.1 % of the 2 ms step A to D spacing | Next revision of the wiring design; item (f) when C336/C337 are fitted | BQ25798-specific (a, d, e); IC-independent (b, c, f) |
| 8 | `docs/charger_replacement_evaluation_2026-11-05.md` | Add the CCB as a path option in the round-3 summary 0.1a and in the comparison of §7, with a cross-reference to this document | Next revision of the study | IC-independent |
| 9 | `docs/firmware-versions.md` | A ledger row for the firmware round of row 2 | When that firmware is built | IC-independent |

## 6. Test-registry delta against the round-3 registry

### 6.1 Scope, sources and conventions

#### 6.1.1 Scope

This section states what happens to each of the 112 test IDs of the round-3 registry when the BQ25798EVM, the carrier (CR)
and the EVM interface board (EIB) are replaced by one custom charger board (CCB) in the 22 CHG holes. It then defines the
new tests that the CCB needs, with the T-K prefix. Test execution, firmware changes and part orders are outside the scope of
this section.

#### 6.1.2 Sources

The citation keys of this section are defined in section 9. [PIC] is the pin-identity script of round 3; it was run on 2026-11-10 without arguments and returned exit 0, 22 pads, both columns centred on y 50.514.

#### 6.1.3 Classification rules

Each round-3 test receives one disposition:

- **RETIRES:** the test checks only an EVM lead, an EVM modification, the EIB ribbon or another inter-board artefact. No
  part or behaviour that it checks exists on the CCB.
- **CARRIES OVER UNCHANGED:** the question, the pass criterion and the fail action stay. Only the global substitutions G1-G5
  below apply.
- **CARRIES OVER MODIFIED:** the question stays, but the setup steps, the object, the pass criterion or the scope change
  beyond G1-G5. The row states the change.

The global substitutions G1-G5 apply to every carried test and do not count as a modification:

1. **G1 (object):** "EVM", "EVM + EIB" and "CR + EIB" read "CCB". A bench test uses the CCB on the fixture FIX1 (6.1.4). A
   vehicle test uses the CCB fitted to the vehicle motherboard (MB).
2. **G2 (designators):** CR X1nn reads X3nn, EIB X2nn reads X4nn, EVM Xnn reads X5nn (U1 -> U501, L2 -> L501), R256/C252
   read R456/C452, R272/R272b read R472/R472b (§0.5). D103/D107 read D303/D307.
3. **G3 (probe points):** EVM TP27 (REGN) reads TP503; TP33 (ILIM_HIZ) reads TP504; TP36 (/CE) reads TP505; TP49 (AGND)
   reads TP306; TP42/TP43 (SCL/SDA) read header pins 7/8; EVM J1 (VBUS in) reads header pad 10 or TP501 (VCHGOUT); EVM J5
   (BAT) reads header pins 18/19 or TP502 (VCHG) (§2.5.10). A current probe "on the input lead" or "on W1" sits on the
   FIX1 feed wire to pad 10. A current probe or shunt "on W3" sits on the FIX1 battery wire from pins 18/19.
4. **G4 (input-path resistor):** the 0.19 ohm series resistor of T-B-09, T-B-10, T-B-12 and T-B-24 represents R_path,max
   with W1/W2, EVM R2 and EVM JP3 included ([WD] H.19). The CCB path is shorter, and its R_path is not yet computed
   (TODO(calc: H.19 with the CCB path), O-11). Keep 0.19 ohm. The V-MOT peak is scored at the source side, so a larger
   series resistance only raises the measured peak, and a pass at 0.19 ohm covers the CCB for every V-MOT-peak criterion.
   It does not cover a criterion on input current, inrush or ringing, which a lower R_path can raise; those criteria need a
   repeat at the CCB minimum R_path (TODO(calc: H.19 with the CCB path)).
5. **G5 (temperatures):** the 0 C, 25 C and 60 C corners stay. Whether 60 C bounds the CCB logic region is decided by the
   new test T-K-14. r2: T-K-14 runs as the fan-on leg of T-K-20, and T-K-20 also records the fan-off case (6.4.4).

r2 adds two marks for the T-K tests. The vehicle is a stationary testbench that drives flywheels, a fan may be mounted on
the CCB, and the CCB has no height restriction (operator statement, 2026-11-10). These facts supersede some r1 test content:

- **Not applicable (testbench):** the test or step checks a road or vibration condition that the testbench does not have.
  The ID stays in the registry, and the r1 content stays in its row as a record.
- **Record only:** the test or step still runs, but its result no longer decides a design value or a gate.

#### 6.1.4 Equipment added to the round-3 list

The round-3 equipment codes (PSU1, PSU2, BATSIM, RT-SI, SCOPE, CP, DMM, LA, LCR, HG, THERM; [WD] section I line 2227) stay.
The CCB adds the following codes:

| Code | Description | Used by |
|---|---|---|
| FIX1 | Bench header fixture: the 1x10 and 1x12 receptacle strips of the chosen header option (§1.3.4) on a carrier at the 22-hole pattern. Pad 10 is fed from PSU1 through the G4 resistor; pins 18/19 go to BATSIM through a shunt; pins 4/14/15 go to one star point; pins 3, 7, 8 and 11 go to the bench Teensy as on the MB; pin 13 (THERM, TS_EXT) goes to a 103AT-class NTC only when R526 is fitted and is otherwise left open (Table 2.5); with 2.7 kOhm I2C pull-ups to the Teensy 3V3 as on the MB (PM9). The taps F01-F24 go to the T-C rig | T-B group, T-C group, T-K-05 to T-K-11, T-K-15, T-K-16 |
| FI1 | Fault-injection unit: a second populated CCB on which pins and parts are lifted for the open-joint tests. FI1 is never fitted to the vehicle | T-C-05, T-D-03, T-D-06, T-D-11 |
| LOOP1 | A CCB built with a current-probe wire loop in series with L501. The layout variant is TODO(layout: split L501 pad with a wire-bridge option). LOOP1 is never fitted to the vehicle | T-K-08 |
| SCOPE-HF | Oscilloscope and probe with >= 500 MHz bandwidth, tip-and-barrel or <= 5 mm ground spring; a differential probe for BTST-SW. The 500 MHz figure is a proposal: the registry SCOPE (>= 100 MHz) resolves the 1.5 MHz waveform but not the edge ringing. TODO(verify: bench equipment available) | T-K-07, T-K-09, T-K-10 |
| MOHM | 4-wire milliohm measurement (1 A source and mV meter, as in T-A-06c) | T-K-17, T-K-19 (r2: not applicable, testbench) |
| SCALE | Spring scale >= 20 N (as in T-F-12) | T-K-17, T-K-18 |
| GAUGE | Feeler gauges, pin gauges 1.05/1.10/1.15 mm, caliper with depth rod (§1.9) | T-K-01, T-K-03, T-K-04 |
| IMU | Accelerometer or IMU logger on the MB (§1.9 item 14). TODO(measure: availability); the post-drive inspection replaces it if absent. r2: not needed; the testbench does not move (operator statement, 2026-11-10) | T-K-19 (r2: not applicable, testbench) |
| FAN (r2) | The bench fan with its mount and duct at the low-y inlet edge (§1.2.3, §1.6.3), powered from the bench supply or its own regulator, never from the LM1084 / CO-5V rail. MPN, airflow and static-pressure curve TODO(verify: fan datasheet) | T-K-14, T-K-20 |
| ANEMO (r2) | Vane or hot-wire anemometer with a probe that fits the 5-8 mm gap; precision 0.2 m/s (§1.9 item 15). TODO(verify: instrument) | T-K-20 |
| TC6 (r2) | A lot of six or more type-K thermocouples with a logger, 1 C resolution, for the soak points of §1.9 item 16 (the THERM code covers one thermocouple) | T-K-14, T-K-20 |

### 6.2 Counts

Table 6.1 gives the disposition counts per round-3 group. The 112 IDs were counted from [WD] lines 2234-2345.

| Group | IDs | Retires | Carries over unchanged | Carries over modified |
|---|---|---|---|---|
| T-A parts and incoming | 12 | 1 | 7 | 4 |
| T-B charger standalone | 26 | 0 | 20 | 6 |
| T-C logic and bench rig | 17 | 1 | 13 | 3 |
| T-D failure injection | 15 | 0 | 11 | 4 |
| T-E vehicle measurements | 14 | 0 | 14 | 0 |
| T-F board integration | 19 | 0 | 15 | 4 |
| T-G road (r2: drive cycles on the testbench, §6.4.4) | 7 | 0 | 7 | 0 |
| T-W watchdog | 2 | 0 | 2 | 0 |
| **Total** | **112** | **2** | **89** | **21** |

The CCB adds **20 new tests**, T-K-01 to T-K-20 (section 6.4). Revision r1 defined T-K-01 to T-K-19. Revision r2 adds
T-K-20 (fan-on and fan-off thermal soak). On the testbench (operator statement, 2026-11-10), T-K-19 is not applicable,
T-K-02 is record only, and the envelope items of T-K-01 are record only. The IDs stay. Therefore 18 T-K tests gate the
design or a phase in r2.

The count of only two retirements has a reason. Most round-3 tests check charger behaviour, carrier logic or MB facts, and
these stay on a single board. The lead, ribbon and EVM-modification content sits mostly inside multi-purpose tests, so those
tests carry over modified rather than retire.

### 6.3 Disposition of every round-3 test

#### 6.3.1 T-A: parts and incoming checks

| ID | Disposition | Reason or modification | Label |
|---|---|---|---|
| T-A-01 | Unchanged | Tests MB J1/J2 tap positions. The flying taps T1-T22 remain on the CCB (§1.12.2 item 4) | IC-independent |
| T-A-01b | Unchanged | Pin-7 tap and encoder-net occupancy are MB facts | IC-independent |
| T-A-01c | Unchanged | T22 lands on the MB BQ29200 pad 8; unchanged | IC-independent |
| T-A-02 | **Retires** | Tests EVM nets, EVM modifications EM1-EM4, EVM jumper posts, the R272/R272b links, the EVM corner holes and the E-lead lengths. None exists on the CCB (§2.4.2). Its intent (values and structural isolation of the ILIM_HIZ and /CE networks) moves to T-K-05; the board-level net check moves to T-K-03 | BQ25798-specific |
| T-A-03 | Unchanged | Q401-Q403 are the same 2N7002K/BSS84 parts with the same 47 kOhm pull-ups (Table 2.6). "Populated EIB" reads "populated CCB" (G1) | BQ25798-specific |
| T-A-04 | Modified | **Object:** C511, C512 and C529-C531 are 10 uF 50 V X7R 1210/1206 parts, not 35 V 0805 parts (Table 2.2). **Added:** SYS bulk C519-C523 effective >= 6 uF at 8.82 V and BAT C538/C539 effective >= 3 uF ([DS] §6.3 via Table 2.2). MB C-D8/C-D10 and C302a/b (ex C102a/b) are unchanged. Pass thresholds for VBUS (>= 2 uF) and PMID (>= 4 uF) at 23.6 V are unchanged | BQ25798-specific (VBUS/PMID/SYS/BAT); IC-independent (C-D8, C-D10, C302) |
| T-A-05 | Modified | **Deleted items:** J101/J201/W5 parts, the polarising plug, the mated-socket envelope, R176/R177, the HTSW-102 rating for JP3/JP5 links, the TSW post option for the CR stack, the W8-fallback fuse I2t. **Kept:** D303/D307 limits, the BAV199 pinning, the 0402 pocket parts, the polyimide sheet, the RTV statement, U319-U323, D308, R387/R388/R390 (ex R187/R188/R190), 30 AWG Kynar for T22, the overlay wire, fallback-2 items. **Added:** the U501 footprint of the capture against Table 3.8c and [DS] pp.149-150 (O-8 closed on paper, §3.4.6); L501 L >= 0.70 uH at 6.5 A and maximum temperature, and heating current > 4 A (§2.1.3, O-2); the 50 V 10 uF DC-bias curve (O-1); R529 6.04 kOhm (the EVM BOM lists 6.20 kOhm, Table 2.2); C536 1 nF 50 V C0G; the socket or header strip of §1.3.4 (tail section in the 1.10 mm drill, accepted pin range, contact resistance, retention force, mating cycles); the nylon spacers and screws, the structural adhesive with a shear-strength datasheet, the thread-lock compatibility and the conformal-coating temperature (§1.4, §1.7); header pin ratings >= 3 A on pins 4 and 10 and >= 2.0 A on pins 14, 15, 18 and 19 (Table 1.13) | Mixed |
| T-A-05b | Unchanged | D307 is D107 with the same limits; D-BC-RG is an MB part | IC-independent |
| T-A-05c | Unchanged | Fallback 2 is an MB rework; run only if T-B-09 fails | IC-independent |
| T-A-06 | Modified | **Object:** one board replaces CR + EIB. The netlist diff runs against §2.5, not [WD] B.8. **Deleted rows:** EIB placement and outline, E-lead lengths, the J101 region, W1-W4 hole spacing and wire insertion, the mated-socket dry fit, the bare-EIB isolation set. **Changed outline:** the L-shaped body plus the rect-A tab, x 17.70-48.70, about 1219 mm2 per side (§1.8). **Changed step 0:** run [PIC] with `--csv <export> --kicad-y-down` unchanged, but the punch-through print and the board check look for the pin-11 marker at (38.90, 76.40), not at (17.70, 67.14) (§1.8; TODO(verify: rerun [PIC] with the new outline)). **Added review items:** the power stage inside x 17.70-38.90, y 50-76.40 (§1.6.1 rule 1); the [DS] §8.4 power-loop rules; the §2.2.2 rules 1-6 (no REGN-ILIM_HIZ part other than Q403 + R455; no /CE-GND part other than U401 1Y and R462 + R463; separate R472/R472b pads and vias; sense traces on their own trace from the IC pad); a solid GND layer next to the underside under every switch node (§1.5); underside rules of §1.3.5; foot holes at (23.20, 70.64) and (32.20, 70.64); the separation check of §3.6.1 (all SW copper inside E-SW of Table 3.9a; every member of Table 3.9 at its distance from E-SW, measured on the capture; rules 1-5). Pass criteria of the kept rows are unchanged | Mixed (outline, pin identity and underside rules IC-independent; power-loop and pin-network rules BQ25798-specific) |
| T-A-06c | Unchanged | MB VBT copper; still before the CCB is fitted | IC-independent |
| T-A-07 | Modified | **Temperature basis:** the round-3 test used the CR temperature beside the LM1084 with no charger power stage on the board. The CCB places a 1.5-2.5 W charger loss on the same board (Table 1.6; about 2.7 W with the eFuse and logic, §3.7.1). Measure BAV199 and D303 leakage also at the T-K-14 maximum at their sites plus 10 C. Pass limits unchanged (§1.11.2 item 2, O-12) | IC-independent |

#### 6.3.2 T-B: charger standalone (all on FIX1 by G1)

Every T-B test checks BQ25798 behaviour. For another charger IC, the whole T-B group is re-specified from that IC's
datasheet; only the method (current-limited bench supply, BATSIM, the G4 resistor) carries over.

| ID | Disposition | Reason or modification | Label |
|---|---|---|---|
| T-B-01 | Modified | **Retired part:** the TP41 (PULLUP) dark check and its fail action (JP30, U2, D11, D12); the CCB has no PULLUP rail (EM15 disappears, §2.4.2). **Replacement:** REGN (TP503) < 0.1 V with VCHG-IN off and no D-BT-SQ short (§2.4.2 EM25 row). **Order:** runs after T-K-06, at 16 V then 21 V as before. Register checks and pass values unchanged | BQ25798-specific |
| T-B-02 | Unchanged | Register timing before D+/D- detection | BQ25798-specific |
| T-B-03 | Modified | **Retired part:** the r3 stray-shunt check on JP13 pin 2 and JP14 pin 2; the footprints do not exist (§2.2.2 rule 1). T-K-05 checks the structural rule instead. **Probe points:** TP504 and TP505 with ground springs. **Levels:** /CE >= 3.0 V not armed; held <= 0.25 V; released 2.06-2.40 V (regen) and 1.52-1.76 V (FC); U403 transition 0.587-0.650 V. Replace these numbers by the O-11 re-run of H.4 if the on-board leakage list moves them (TODO(calc: r3_calc.py H.4 with the CCB leakage list), O-11) | BQ25798-specific |
| T-B-04 | Modified | **Apportioning method:** the round-3 test lifted JP18, R254 and R272. On the CCB, lift R525 (TS simulator), R454 and R472 on FI1, or compute the share from the measured total and the part values. **Load list:** eFuse U301, U501, the TS divider R518/R524/R525, the REGN pull-ups R452/R454/R471/R472/R472b, D303 and the MB CHG divider. Pass unchanged (inhibited <= 5 mA, released <= 6 mA) | BQ25798-specific |
| T-B-05 | Unchanged | VINDPM retention | BQ25798-specific |
| T-B-06 | Unchanged | Inhibit latency; CP on the FIX1 feed (G3); "EIB input" reads the U401/U402 inputs | BQ25798-specific |
| T-B-07 | Unchanged | ILIM_HIZ sampling; Q402 for Q202 | BQ25798-specific |
| T-B-08 | Unchanged | Charger watchdog | BQ25798-specific |
| T-B-09 | Unchanged | Keep-alive decision; G4 keeps 0.19 ohm. "Run T-E-04 first" is kept | BQ25798-specific |
| T-B-10 | Unchanged | Warm response; G4 | BQ25798-specific |
| T-B-11 | Unchanged | Poor-source recovery; REGN delay | BQ25798-specific |
| T-B-22 | Unchanged | IBUS_OCP HIZ | BQ25798-specific |
| T-B-23 | Unchanged | ILIM POR conversion error. The on-board leakage may shift the result; the test records it either way | BQ25798-specific |
| T-B-24 | Unchanged | IINDPM step response; G4 | BQ25798-specific |
| T-B-25 | Unchanged | VREG corruption read-back (firmware + IC) | BQ25798-specific |
| T-B-12 | Unchanged | Concurrent mode and staged raise; G4; RT-SI unchanged | BQ25798-specific |
| T-B-13 | Unchanged | VINDPM accuracy | BQ25798-specific |
| T-B-14 | Unchanged | ADC and IMON accuracy; C305 for C105 | Mixed (IMON is the eFuse, IC-independent) |
| T-B-14b | Modified | **Reference point:** the shunt and integrating DMM sit in the FIX1 battery wire (pins 18/19 to BATSIM), not on W3. The CCB has no wire between the charger and the MB, so the accounting check is bench-only. Pass unchanged | BQ25798-specific |
| T-B-15 | Unchanged | CV and termination | BQ25798-specific |
| T-B-16 | Modified | **Object:** the CCB's own power stage on FIX1 in still air, without the LM1084. **Retired items:** the JP5/JP3 link-joint temperatures and the fallback "link soldered into the plated holes (EM11/EM12)". **Replaced by:** the header joints of pins 10 and 18/19. **Added fail lever:** the 750 kHz alternate (R529 8.2 kOhm, L501 2.2 uH, §2.1.3). The in-situ soak beside the LM1084 is the new T-K-14. **Pass:** TDIE < 100 C and TREG_STAT 0 (unchanged). **Changed pass item:** the round-3 "joint rise < 20 C" is replaced, because on FIX1 the pin joints sit near the board temperature (§3.7.6). The CCB-side joints of pins 10 and 18/19 must stay at or below the header rating minus 20 C (TODO(verify: Samtec TSW datasheet, operating temperature)); their rise over ambient is recorded as the T-K-14 input. **r2 (testbench, fan):** the r2 thermal design relies on the bench fan (§3.7.3a), so the gating run uses FAN at the M15 velocities over the top and through a FIX1 gap of the chosen g. The still-air run is record only; it is the fan-off image for the FR-50 thresholds of T-K-20 | BQ25798-specific |
| T-B-17 | Unchanged | Unpowered I2C clamp; R345/R346 are DNP, so the MB pull-ups (PM9) alone are the bus pull-ups | BQ25798-specific |
| T-B-18 | Unchanged | STAT/CHG_STAT with ILIM forced; Q401 for Q201 | BQ25798-specific |
| T-B-19 | Modified | **Object:** the CCB power stage. Its layout differs from the EVM, so the round-3 efficiency basis (eta_max 0.93) is re-measured. **Added points:** VBUS 21.5 V and 22.6 V, because the [DS] efficiency curves stop at 20 V (§1.6.2). **Added record:** the U501 and L501 case temperatures at each point, as input to T-K-14. Pass unchanged (P_in >= 20.8 W at 7.4 V with ICHG 3.10 A) | BQ25798-specific |
| T-B-20 | Unchanged | REGN and ILIM ADC timing; C350 for C150 | BQ25798-specific |
| T-B-21 | Unchanged | Register-independence of the HIZ stop | BQ25798-specific |

#### 6.3.3 T-C: logic and bench rig

| ID | Disposition | Reason or modification | Label |
|---|---|---|---|
| T-C-01 | Unchanged | Truth table, monostables, power-up states. Runs on the stage-1 board (no power stage, T-K-05); T-K-11 repeats the converter-relevant vectors on stage 2 | IC-independent |
| T-C-01b | Unchanged | BTB_OFF vs RT1987 conduction | IC-independent |
| T-C-01c | Unchanged | U315 POR | IC-independent |
| T-C-02 | Unchanged | H1 trip points | IC-independent |
| T-C-03 | Unchanged | UVB and BT_OK thresholds; R342 select-on-test. The 60 C corner is valid only if T-K-14 shows the comparator region <= 60 C (G5) | IC-independent |
| T-C-04 | Modified | **Retired part:** the OUT excursion "with the real 0.30 m W1/W2 lead" (§1.11.2 item 2). **Changed step (2):** the hard short is applied at the C511/C512 pads (the U501 VBUS input) through on-board copper only. **Added decision:** D303 may become DNP only if step (2) shows OUT >= -0.3 V (§1.11.2 item 2, O-12). **Added record:** the U501 VBUS pin voltage during step (2) against the [DS] §6.1 minimum (-2 V, converter not switching, [DS] §6.1 p.7). Steps (1) and (3), the IN-side spike criteria and the r6 vehicle MB-end step are unchanged; the reduced-voltage order (8 V, 12 V, then full voltage) is unchanged. **r2 (tall stack and on-board OUT copper, [TS] §(c)-(d)):** the IN-side peak is no longer the round-3 value. Without the 150 nH W1/W2 lead, the ideal model gives 35.5-40.0 V at U301 IN for 5-20 nH of OUT copper, and the r2 stack (H_u 5.1-8.1 mm, up to +10.8 nH on the pad-10 / pad-4 loop) raises this by 0-0.3 V, to at most 40.3 V. The MB end stays at 19.8-20.0 V. **Added records:** (a) the U301 IN and MB-end peaks against these values; (b) whether D307 conducts (the ideal peak exceeds its 36.7 V VBR minimum at 10-20 nH), with its current or clamp voltage where the probe allows; (c) the CCB-GND-to-MB-GND voltage across pad 4 during step (2), against the [TS] §(d) estimate of 0.08-1.34 V (three pins) to 0.24-4.02 V (one pin) at 65 A falling in 0.1-1.0 us. The pass criteria (60 V at IN, U301 67 V, MB end 35 V and 40 V) are unchanged. D307 energy and the OUT copper inductance are TODO(calc) (N-25) | IC-independent (eFuse); the VBUS-pin record is BQ25798-specific |
| T-C-05 | Modified | **Deleted fault cases:** opens of E1-E8, of each W5 conductor and of the links L1/L2; R273 open; each 3V3 ribbon conductor open; all adjacent ribbon-pair shorts (3-4, 4-5, 11-12 and the rest); the T-C-13 cross-references. **Kept fault cases (G2):** R455, R452, R471, R472, R472b open singly and R472 + R472b together; Q401 drain open; Q403 D-S short; Q401 D-S short; T16 (F17) open. **Added fault cases, on FI1:** an open joint on each sense trace (lift R458 at U403 and R462 at U404); an open joint on each drive trace (lift U401 pin 7, U401 2Y and 3Y outputs, U402 pin 4); each driver input open, which R467-R470 must pull LOW (§2.3.2); pin 6 stuck LOW and pin 6 shorted to CE_DRV (FR-22/FR-44 re-scope, Table 5.2); pin 6 driven HIGH by firmware with the STAT sink <= 3.3 mA through R475 (Table 2.5). **Pass:** the [WD] B.6 outcomes for the kept part rows, unchanged; the added rows fail safe (converter held or /CE HIGH) and FR-08 or FR-44 flags them, except the pull-down-protected input opens, which read LOW and need no flag | Mixed (method IC-independent; the fault list is BQ25798-specific) |
| T-C-06 | Unchanged | Firmware sequences on emulated supplies | IC-independent |
| T-C-07 | Modified | **Deleted:** each W5 conductor open, the ribbon-pair shorts (1-3, 2-3, 3-4, 4-5, 11-12) and the "one W5 3V3 conductor open" case. **Changed:** the CR and EIB rails are one rail behind R375 (§2.6.2 item 1), so "CR and EIB rails < 0.8 V" reads "the 3V3 rail < 0.8 V" (held at 0.3-0.45 V across R474 by the BAV199 back-feed, Table 2.8), and ">= 3.05 V in normal operation" applies to the merged load U302-U323 plus U401-U404 (U301 is fed from VCHGIN, not from 3V3). **Kept:** tap opens T2-T6, T8-T11, T21 with the bus energised and the Teensy driving; the shorts of C325, of one decoupler (C401) and of the rail to GND with the MCU-reset check | IC-independent |
| T-C-08 | Unchanged | R344 effect on BT-CURR | IC-independent |
| T-C-09 | Unchanged | Loop period | IC-independent |
| T-C-10 | Unchanged | Monostable widths; C350/C351. The 60 C corner follows G5 | IC-independent (QQ is BQ25798-specific) |
| T-C-11 | Unchanged | Early-purge misclassification | IC-independent |
| T-C-12 | Unchanged | BTB_OFF stuck HIGH; FCC/RGN intermediate levels; repeat every rebuild and every 6 months | IC-independent |
| T-C-13 | **Retires** | Tests the J101 ribbon orientation and the R176/R177 ribbon feed. The CCB has no ribbon, J101, R176 or R177 (§1.12.2 item 2). The first-power intent (3.3 V, 20 mA limit) moves to T-K-05 step 6 | IC-independent |
| T-C-14 | Unchanged | FR-42 backstop | IC-independent |
| T-C-15 | Unchanged | Pins 38/39 over range (MB dividers) | IC-independent |

#### 6.3.4 T-D: bench failure injection

| ID | Disposition | Reason or modification | Label |
|---|---|---|---|
| T-D-01 | Unchanged | Teensy reset and boot | IC-independent |
| T-D-02 | Unchanged | Teensy hang with P5 HIGH; (a) only after T-W-01 | IC-independent |
| T-D-03 | Modified | **Changed step (2):** "TP36 (E5) lifted" reads "U401 pin 7 (1Y) lifted on FI1"; R472/R472b then hold /CE HIGH, which is the same condition. Steps (1) and (3) and the pass criteria are unchanged | Mixed |
| T-D-04 | Unchanged | Comparator single faults | IC-independent |
| T-D-05 | Unchanged | REG05 fault key | BQ25798-specific |
| T-D-06 | Modified | **Changed setup:** "TP36 lifted" reads "U401 pin 7 lifted on FI1". Pass unchanged | Mixed |
| T-D-07 | Unchanged | D-BT-EN short | IC-independent |
| T-D-08 | Unchanged | Brake with D-BT-EN short | IC-independent |
| T-D-09 | Unchanged | FCCEIL stuck HIGH | Mixed |
| T-D-10 | Unchanged | Input short and input-to-output short downstream of the eFuse; the short points are now CCB copper (C511 pads; U501 VBUS to the VCHG pour) | IC-independent |
| T-D-11 | Modified | **Fault map on FI1:** E3 lifted reads Q401 drain lifted from ILIM_HIZ; Q201 removed reads Q401 removed; R252 removed reads R452 removed; U202 Y held LOW reads U402 pin 4 held LOW; E5 lifted reads U401 pin 7 lifted; U201 1Y held LOW reads U401 pin 7 to GND through 100 ohm; R272 + R272b removed reads R472 + R472b removed; E6 lifted at Run entry reads R462 lifted at Run entry. The T10 cases (r4, r5) and all pass criteria are unchanged | Mixed |
| T-D-12 | Unchanged | False restore | BQ25798-specific |
| T-D-13 | Unchanged | QUAL stuck HIGH | BQ25798-specific |
| T-D-14 | Unchanged | Hang across a purge (bench) | IC-independent |
| T-D-15 | Modified | D-BT-SQ short detection. **Added expectation, case (1) healthy:** with R392 fitted, each FR-48(a) one-shot raises REGN and /CE (BAT <= 4.46 V > 3.2 V, [DS] §7.3.4.1); U404 reads /CE HIGH for the conversion and no FR-08(b) or FR-47 latch follows, because `regnExpected` is false (Table 2.8). **Added expectation, case (2) shorted:** during the one-shot REGN is on, ILIM_HIZ held and /CE HIGH (Table 2.8); the latch comes from REG3B only | Mixed |

#### 6.3.5 T-E, T-F, T-G and T-W

All 14 T-E tests (T-E-01, T-E-02, T-E-03, T-E-04, T-E-05, T-E-05b, T-E-06, T-E-07, T-E-08, T-E-09, T-E-10, T-E-11, T-E-12,
T-E-13) carry over unchanged. They measure the vehicle, the H-20, the VESC, the pack or MB parts, and none depends on the
charger packaging. T-E-09 now decides a population choice (R525 fitted XOR R526 fitted, Table 2.5) before CCB
assembly.

All 7 T-G tests and both T-W tests carry over unchanged. They test the system, the firmware and the watchdog. In r2
the T-G tests run as drive cycles on the stationary testbench, with "drive" as §6.4.4 defines it (operator statement,
2026-11-10).

| ID | Disposition | Reason or modification | Label |
|---|---|---|---|
| T-F-01 | Unchanged | MB state after Ag105 removal | IC-independent |
| T-F-02 | Unchanged | Boot self-test FR-12 | IC-independent |
| T-F-03 | Unchanged | Run entry, inrush <= 0.5 A, T1 steps 5, 6 and 8 | Mixed |
| T-F-04 | Unchanged | FC windows at standstill | IC-independent |
| T-F-04b | Unchanged | FC windows in cruise | IC-independent |
| T-F-04c | Unchanged | INA253 FC offset from charger return currents; the return path is now pads 4/14/15 of the CCB | IC-independent |
| T-F-05 | Unchanged | Switching noise on the readbacks on the vehicle; the bench precursor is T-K-09 | IC-independent |
| T-F-06 | Unchanged | FC windows on a running H-20 | IC-independent |
| T-F-07 | Unchanged | Early purge | IC-independent |
| T-F-07b | Unchanged | Rescue close transient | IC-independent |
| T-F-08 | Unchanged | BT_BUS close transient | IC-independent |
| T-F-09 | Unchanged | Early purge during a brake | IC-independent |
| T-F-11 | Modified | **Deleted:** the ribbon GND bundle at R273 and the W7 GND (both gone, Table 2.6, §5.2 item 3). **Kept:** T7b (F02) and T17r (F19) shield currents < 20 mA DC. **Changed:** "V(TP49 - NT1) < 2 mV" reads "V(TP306 quiet GND - TP511 power GND) < 2 mV during a 3.1 A burst and a 12 A brake", which tests the §1.13.2 one-plane partition | IC-independent |
| T-F-12 | Modified | **Deleted:** W1-W4 underside heights, the W1-W4 pull check, EVM J2/J3/J4 insulation, and the W3/W4/J5/JP5 fallback-2 inspection (the link-fuse joint stays). **Changed:** "CR underside" reads "CCB underside"; the polyimide sheet now extends over rect A with holes at the two foot spots (§1.5 rule 3). **Added:** the foot bonds, the socket seating (option K) and the staked parts in the visual inspection. Pass criteria for the kept items unchanged | IC-independent |
| T-F-13 | Modified | **Changed step (1):** Kelvin from V-MOT to the C511/C512 pads (CCB VBUS) and from MB GND at D-BC-RG to TP511. **Changed pass:** the H.19 band 0.117-0.193 ohm included W1/W2, EVM R2 and EVM JP3, so a CCB reading below 0.117 ohm is expected and is not a failure. The pass becomes "R_path within the re-derived CCB band" (TODO(calc), O-11), and the warm budget still clears the measured t_d + tau. Step (2) on the MB VCHG-IN vias is unchanged | IC-independent |
| T-F-14 | Unchanged | CV hold with the calibrated scale | IC-independent |
| T-F-15 | Unchanged | IMON and CHG_VOLTAGE ground offset; R305 for R105 (§1.13.4 item 2) | IC-independent |
| T-F-16 | Modified | **Object:** the MB VBT trace under the CCB and the MB-side joint of pin 18. **Changed reference:** every rise is measured against T_MB,local, a thermocouple on the MB surface at x 25-35, y 55-75, away from the VBT trace and the header. On the CCB the pins conduct converter heat into their joints (§3.7.6), so ambient is not a valid reference. **Changed pass:** VBT trace rise over T_MB,local < 20 C (IPC-2221 predicts <= 10 C at 3.21 A on 1 oz, [WD] A.8); pin-18 joint absolute temperature at or below the header or socket rated operating temperature minus 20 C (TODO(verify: Samtec TSW or socket datasheet, T-A-05)). The expected joint level (T_MB,local + 20-26 C without the gap pad, + 10-17 C with it, option S, §3.7.6) is recorded, not gated. **Joint condition:** decided by T-K-17 (4-wire contact resistance), not by temperature. **Changed fail branch:** a trace rise >= 20 C caps the regen ICHG image at 2.50 A until the overlay rework (unchanged). A joint above its absolute limit points to the gap pad (§3.7.4), H_u, 750 kHz or ICHG 2.50 A, not to the MB overlay. **r2:** the gap pad is superseded by the bench fan (§3.7.4); a joint above its limit points to the fan velocity (M15), H_u, 750 kHz or ICHG 2.50 A. The pin-18 joint with forced air is TODO(calc) and is measured in T-K-20 | IC-independent |
| T-F-17 | Unchanged | BQ29200 pack-OV permit | IC-independent |

### 6.4 New tests (T-K)

#### 6.4.1 Pre-layout and incoming

| ID | Purpose | Setup and steps | Pass | Decides | Order | Label |
|---|---|---|---|---|---|---|
| T-K-01 | Measure the mechanical envelope before the Ag105 is removed and before the capture freezes | Vehicle MB, Ag105 fitted, power off, pack unplugged; GAUGE. Steps: M1, M5-M10 and M13 of §1.9: Ag105 standoff h_s at four corners (gate D-2), module top and pin length below the MB; LM1084 and CO-5V heights; free height H_env above the footprint and rect A; heights of L-FC, OP-FC, MDAC-FC, ROP1-FC; J-BL wire and screwdriver envelope; foot-spot access and surface; MB thickness. Optional (M3 on a coupon): a dry fit of the chosen strips in a 1.66 mm FR-4 coupon drilled 1.10 mm, for an early seat height. M2, M3 on the MB and M4 need the empty holes and run in T-K-04 | Every value recorded at the §1.9 precision. The planned stack (H_u + t_pcb + 3.0 mm: 7.14 mm for option S, 7.14 + h_k mm for option K, with t_pcb 1.6 mm, §1.3.2) is at least 1 mm below H_env (the 1 mm margin is a proposal for operator ruling); for option K, h_k <= 5.0 mm against the nominal 13.14 mm Ag105 envelope. CO-5V top < H_u (2.10 mm vs 2.54 mm planned). OP-FC height confirms the rect-A' condition H_u >= 2.75 mm. **r2 (testbench):** the CCB has no height restriction (operator statement, 2026-11-10). The H_env criterion and the h_k <= 5.0 mm limit are therefore record only (M6), and gate D-2 does not constrain the stack. Still gating: M5 (LM1084 and CO-5V positions, against the right-edge rule at the chosen H_u, §1.2.2), M7, M8 (J-BL pluggability with the taller CCB) and M9-M10 (foot spots, with the fan and its mount in place) | The header option S or K (§1.3.4), with H_u taken from the planned stack until T-K-04 measures the seat height; the top-part height limit (r2: none); use of rect A only or rect A'; the foot length; the part-height limit within 5 mm of the left edge | Before T-A-06 and before PM1. h_s can be measured only while the Ag105 is fitted | IC-independent |
| T-K-02 | Measure the LM1084 thermal environment as an input to the charger thermal design | Vehicle in Run at the worst available load, Ag105 fitted and idle, no CCB; THERM on the LM1084 tab, in air at x 48.7 / z 4 mm beside CHG pins 4-8, and on the MB surface at x 25-35, y 55-75 (§1.9 items 11-12); ambient logged; 30 min to steady state. Heater step (M12): bond a heater of about 400 mm² at or beside x 25-35, y 55-75, inject 2.3 W (the option-S P_MB at 2.7 W, §3.7.2), and wait for steady state again | Temperatures recorded at 1 C; steady state reached (rise < 1 C in the last 5 min); T_MB,0 recorded; R_MB = MB surface rise beside the heater / 2.3 W recorded | Ambient for the CCB thermal design (§1.6.2); the admissible T_MB,0 of §3.7.3 with the measured R_MB (r1 verdict condition 3); the keep-out distance of §1.6.1 rule 4; starting values for the FR-50 thresholds (§5.6); whether 1.5 MHz stays the baseline. **r2: record only.** With the bench fan on, T_J moves by 0.15-0.30 C per C of MB idle offset ([LC] §8.6b), so T_MB,0 and R_MB no longer decide verdict condition 3. T-K-20 replaces the heater-step gate. The LM1084 tab and air temperatures (M11) stay as the baseline for T-K-14. The heater step is optional and record only | Before T-A-06 and before PM1 | IC-independent |
| T-K-03 | Confirm that the fabricated bare CCB matches the capture before any part is soldered | All bare boards of the order; fab electrical-test report; DMM; GAUGE; the MB with loose header pins. Steps: (1) fab flying-probe or netlist-test result against the capture netlist, or DMM isolation between each pair of VCHGIN, VCHGOUT, PMID, SW1, SW2, VCHG, CHG_SYS, REGN, 3V3 and GND; (2) caliper on outline, thickness and foot holes against §1.8; (3) export the header drill positions from the fab drill file to CSV and run [PIC] `--csv <file> --kicad-y-down` (with `--dx/--dy`); (4) lay the bare CCB on loose pins in the MB and meter from CCB net copper to MB parts: pad 10 copper to C-D8 pad 1, pads 18/19 copper to C-D11 pad 1, pads 4/14/15 to MB GND, pad 11 copper to Teensy pin 5 ([WD] T-A-06 step 0(c)); (5) loupe on the underside; (6) stack-up and copper weight from the fab record | Zero netlist errors; each power-net pair > 10 MOhm; dimensions within 0.1 mm; [PIC] exit 0 with no mirror reported; every punch-through reading as listed; pin-11 marker at the planned corner; every underside via tented and no exposed copper other than header and foot pads (§1.5 rule 1) | Release of the boards to assembly | After fabrication; gates T-K-05 and every later test | IC-independent |
| T-K-04 | Confirm the seated clearances on the vehicle MB after Ag105 removal | Vehicle MB after PM1 and T-F-01; polyimide sheet bonded (§1.5 rule 3); GAUGE. Steps: (1) hole condition of all 22 holes with pin gauges and a loupe (§1.9 item 2); (2) seat a bare or stage-1 CCB, unsoldered and unscrewed; (3) feeler gauge between the lowest CCB feature and D-BT-SQ, C-D11, C-D12, C-DC11, C-DC12, ROP1-FC and (rect A' only) OP-FC; (4) gaps from the CCB right edge to CO-5V and to the LM1084 body; left edge to the J-BL courtyard; (5) screwdriver trial on the J-BL position-3 screw and on both foot screws; (6) seat height (M3); (7) hole positions against a 1:1 print of the pin field and a caliper across the 25.0 mm row spacing (M4) | g_air >= 1.0 mm at every part, target 1.4 mm under the 1.10 mm parts (§1.3.2); CCB right edge <= x 48.70 with no contact to CO-5V; LM1084 gap recorded against the planned 2.86 mm (§1.2.2); J-BL and foot screws reachable; CCB top <= H_env minus the T-K-01 margin; hole positions within 0.1 mm of the A.8 table (the M4 precision). **r2 (testbench):** the H_env item is record only (no height restriction, operator statement, 2026-11-10). Added pass item: the seated channel gap g = H_u - 0.125 mm is 5 mm or more at the inlet edge (y 34.14), at mid-body and at the tab, and preferably 5-8 mm (§1.3.2 rule 3; M3) | Socket or solder for the vehicle; final foot length (r2: spacer length = H_u, §1.4); release to fitting | After PM1, T-F-01 and T-A-06c; before the CCB is soldered or screwed; gates T-K-17 and T-K-18 | IC-independent |

Note that gate D-2 (the fitted Ag105 standoff) is not a pass/fail gate for the CCB. The CCB clears the MB parts through
g_air, which does not contain h_s (§1.3.3). T-K-01 records h_s only as the proven envelope and as the reversibility
datum for option K.

#### 6.4.2 Staged assembly and power-stage bring-up

The CCB is assembled in two stages, so the interlock logic is proven before any energy source can switch. **Stage 1** fits
the eFuse block, the interlock block and the charger-interface block. **Stage 2** adds U501, L501 and the power-stage
capacitors of Table 2.2.

| ID | Purpose | Setup and steps | Pass | Decides | Order | Label |
|---|---|---|---|---|---|---|
| T-K-05 | Prove the stage-1 values and the structural pin-network rules, then apply first power. Replaces the intent of T-A-02 and of T-C-13 | Stage-1 CCB; DMM, power off; then a 3.3 V supply with a 20 mA limit into F07 (T6) in place of the Teensy feed. Steps: (1) inspect the placement against §2.2.2 rules 1-3: no fitted part on a REGN-ILIM_HIZ pair other than Q403 + R455, none on a /CE-GND pair other than U401 1Y and R462 + R463; (2) NCE to REGN (TP505 to TP503) reads R472 parallel R472b; (3) TP504 to TP306 reads the ILIM_HIZ network; (4) R475 and R307 in circuit; (5) R525 XOR R526 fitted per T-E-09; (6) first power at F07; (7) PSU1 12 V with a 50 mA limit into pad 10: VCHGOUT rises (C303 only), UVLO and IMON zero recorded | (1) no violation; (2) the parallel value, expected about 23.5 kOhm (exact value with the U404 sense chain TODO(calc: extend sch_calc.py)); a reading near 47 kOhm means one pull-up is open; (3) within 2 % of the computed value (TODO(calc); R523 parallel R456 alone gives 39.9 kOhm); (4) 1.00 kOhm and 10.0 kOhm within 1 %; (6) draw within the merged logic quiescent budget (TODO(calc: H.15 logic share for U302-U323 + U401-U404); the round-3 EIB share was 1.82 mA, [WD] T-C-13) and TP301 >= 3.05 V; no part warm; (7) UVLO rising 9.7-10.1 V ([WD] T-C-04) | Release of stage 1 to the T-C bench group | After T-K-03, T-A-03, T-A-04 and T-A-05; gates T-C-01, T-C-01b, T-C-01c, T-C-02, T-C-03, T-C-10, T-C-12 (stage 1) and the stage-2 assembly | Mixed |
| T-K-06 | Bring up the integrated power stage at reduced voltage with every source current-limited | Stage-2 CCB on FIX1; PSU1 current-limited; BATSIM at 7.4 V (or a fused 2S pack, TODO(operator)); SCOPE on SW1 at the L501 pad with a ground spring, on TP501, TP502 and TP503; LA on I2C; THERM on U501 and L501; DMM. Steps: (1) power off: resistance of VCHGOUT, PMID, SW1, VCHG and REGN to GND not below the netlist value (TODO(calc)); then the U501 pin-to-pin list of Table 2.6b: TP504 to the R515 pin-1 pad (ILIM_HIZ-BATP), TP504 to TP506 (ILIM_HIZ-TS), TP505 to header pin 7 (NCE-SCL), TP505 to TP509 (NCE-NQON), R475 pin 1 to TP501 (STAT-VBUS), the C506 BTST1 pad to TP503 (BTST1-REGN), the R515 pin-1 pad to the C508 BTST2 pad (BATP-BTST2); (2) BATSIM only, VCHG-IN off: REGN < 0.1 V, battery quiescent current recorded; (3) VCHG-IN 12 V, limit 0.2 A, ILIM held, CHG_ARM LOW: no SW1 activity, input <= 5 mA; (4) read REG48, REG0A, REG13 as in T-B-01; (5) a bench token build sets ICHG 0.5 A and IINDPM 0.5 A and runs the permit sequence on the bench Teensy, limit 0.6 A; (6) raise VCHG-IN 12 -> 16 -> 19.0 -> 21.5 V and ICHG 1.0 -> 2.5 -> 3.10 A, with the PSU1 limit at the expected input current + 20 % at each step. Stop on a PSU1 limit event, TDIE >= 100 C or a T-K-07 limit exceeded | (1) each pin-to-pin reading not below its netlist value: > 1 MOhm where the netlist gives no path between the two nets; the computed value where a path exists through the ground returns, for example ILIM_HIZ-TS about 47.4 kOhm with option B (39.9 kOhm + 7.5 kOhm) (TODO(calc) for each pair). A bridge reads < 1 Ohm; a 17-18 bridge does not change the TP504-TP306 reading of T-K-05 step (3), so only this step can see it. Any failed pair stops the test before step (2); (2)-(3) as listed; (4) as T-B-01 (CELL 1h, PWM_FREQ 0); (5)-(6) IBAT within the [DS] ICHG accuracy at each step (TODO(verify: DS EC ICHG tolerance)); no stop event; SW1 within the T-K-07 limits at each step | Release to T-B-01 and the full-voltage T-B group | After T-K-05 and the stage-1 T-C group; gates T-B-01, T-K-07, T-K-08 and every later stage-2 test. The eFuse UVLO (9.7-10.1 V) sets 12 V as the lowest useful input | BQ25798-specific |
| T-K-07 | Check the switching nodes and the bootstrap supplies at the IC | Stage-2 CCB on FIX1; SCOPE-HF on SW1, SW2, PMID and VCHGOUT at the U501 pads, ground spring to the nearest PMID capacitor ground; differential probe on BTST1-SW1 and BTST2-SW2. Conditions: VBUS 12, 16, 19, 21.5 and 22.6 V (eFuse OVP lower edge); ICHG 0.5, 2.5 and 3.10 A; also PFM at light load | SW1 never below -2 V and never above 30 V; SW2 never below -2 V and never above 23 V ([DS] §6.1 p.7 lists the SW1 and SW2 minimum as "-2 (50ns)", that is -2 V for at most 50 ns; record the duration of every excursion below 0 V and treat one longer than 50 ns as a fail until TI states the DC minimum, TODO(verify: TI)); BTST-SW within -0.3 to 6 V ([TID] lines 28, 43); a design margin of 10 % below the absolute maxima is proposed (SW1 peak <= 27 V), TODO(operator ruling on the margin); fsw recorded (1.5 MHz typical; tolerance TODO(verify: TI), O-5); PMID ripple recorded | Population of the SW snubbers R507/C505 and R510/C507 (decision D10 (§2.1.1)); 1.5 MHz vs the 750 kHz alternate; a layout re-spin | During and after T-K-06; gates T-K-09, T-K-10 and T-K-12 | BQ25798-specific |
| T-K-08 | Measure the inductor peak current and confirm no saturation | LOOP1 on FIX1; CP (>= 20 A) on the loop; THERM on L501. Conditions: VBUS 16 V and 22.6 V; ICHG 3.10 A image; L501 cold and after 10 min at 3.10 A | Peak <= the Table 2.3 value for the test point plus 10 % (worst case 5.51 A at 23.63 V and 0.8 uH); the current ramps are linear up to the peak (no saturation knee); the slope at the peak is within 12.5 % of the slope at the valley (the §2.1.3 criterion; di/dt = (VBUS - VSYS)/L) | The L501 part (Isat >= 6.5 A rule and the §2.1.3 saturation criterion, O-2); evidence for the TI query on ISW 5 A (O-4) | After T-K-07; before T-B-16 and T-B-19. LOOP1 changes the SW-node ringing, so T-K-07 is not measured on LOOP1 | BQ25798-specific |

#### 6.4.3 Same-board coupling and the integrated safety chain

On round 3 the converter sat on the EVM, 0.3 m from the comparators. On the CCB the converter shares the ground plane with
U302-U323 and U401-U404. Tests T-K-09 to T-K-11 cover that change.

| ID | Purpose | Setup and steps | Pass | Decides | Order | Label |
|---|---|---|---|---|---|---|
| T-K-09 | Prove that converter switching on the same board causes no false comparator, logic or monostable transition | Stage-2 CCB on FIX1 with the T-C rig (bench Teensy, PSUs on T1/T2); LA on H1q, H2c, GATE, ARM_OK, QQ, BT_OK rb, UVB, BTB_OFF, FCC_ON, RGN_ON and TP302-TP305; SCOPE (20 MHz and full bandwidth) at the divider bottoms R310, R312, R315, R318, R385, R389, R391 and R463 (N_CSP) against TP306. Converter at ICHG 3.10 A, VBUS 19 V and 21.5 V. Steps: (1) inputs at the nominal operating point, 10 min in the regen image and 10 min in the FC image; (2) each comparator input held at the [WD] H.1-H.3 worst-case margin from its trip, 2 min each; (3) stop the heartbeat edges with the hang key while switching at full current; (4) hold QUAL LOW while switching; (5) record divider-bottom noise | (1)-(2) zero spurious output transitions; (3) zero U313 trigger edges after the last HB edge, ARM_OK falls within the T-C-10 measured width (20-46 ms) and IBAT < 10 mA within TW_HB_MAX (the T-D-02 criterion); (4) zero QQ edges; (5) divider-bottom noise referred to each comparator input below its hysteresis margin (TODO(calc: B.2 margins)), which answers the §1.13.4 item 3 TODO. U320, U321 and U404 have no feedback resistor, so their 2-8 mV internal hysteresis is not a noise margin; their limit is 50 % of the static margin at IN+ (the factor is TODO(operator ruling)): at R389 / R391, 0.60 V peak with FCC / RGN LOW (static margin 1.202 V, the unsafe direction) and 0.39 V peak with them HIGH (0.781 V); at R463, 0.48 V peak with /CE HIGH (0.962 V); the /CE LOW margin is TODO(measure: T-K-10) ([CALC]) | Acceptance of the logic/power partition in the layout; added filter capacitance (the C336, C337 and C453 fit decision, §2.5.6); release to T-F-05 on the vehicle | After T-K-07 and the stage-1 T-C group; gates the stage-2 runs of T-C-04, T-C-05 and T-C-07, and T-K-11 | IC-independent (method); the stimulus is BQ25798-specific |
| T-K-10 | Prove the charger control pins hold their levels under switching | As T-K-09; probes with ground springs on TP504 (ILIM_HIZ), TP505 (/CE), TP503 (REGN), TP506 (TS) and the STAT net. Modes: ILIM held, regen release, FC release, /CE HIGH and LOW, each with the converter running where the mode allows; VBUS 12 V (lowest REGN headroom) and 21.5 V | Held ILIM_HIZ plus peak noise below the U403 minimum trip 0.587 V and below VIL_ILIM_HIZ 0.75 V (Table 2.6, [WD] T-B-03); released levels including noise within 2.06-2.40 V (regen) and 1.52-1.76 V (FC); /CE >= 3.0 V when not armed, including dips; zero spurious U403/U404 output transitions; REGN within the [DS] EC range (TODO(verify: DS EC REGN)) and its ripple recorded | Adequacy of R456/C452 as the ILIM_HIZ filter; local REGN decoupling at the pull-ups; evidence for O-6 (REGN loading) | With T-K-09; gates T-B-03, T-B-07 and T-B-23 (the POR ADC samples the ILIM_HIZ pin) | BQ25798-specific |
| T-K-11 | Re-run the safety chain with REGN generated by U501 and the converter switching (the T-C group ran on stage 1) | Stage-2 CCB on FIX1 with the T-C rig. Steps: (1) the T-C-01 vectors that release or hold the converter (GATE, ILIM_REL, CE_DRV, RFC_OFF), with the real ILIM_HIZ and /CE pin response; (2) 20 Teensy resets with the converter running (T-D-01 method); (3) T6 (F07) opened while charging at 1.76 A input; (4) VCHG-IN removed while charging; (5) an eFuse latch from the T-C-04 step (1) overload | Each state matches its Table 2.8 row: (1) converter stops or releases as the truth table says; (2) the T-D-01 pass; (3) the converter stops within 20 ms (Q401 on through R452, /CE HIGH), pin 7 reads LOW and FR-08(b) trips; (4) U404 reports /CE LOW and FR-23 holds FR-08(b) quiet; (5) FLT LOW on pin 35 and no FR-08 trip (§2.6.2 item 3); IBAT < 10 mA wherever the row says inhibited. r2: in step (5), also record the CCB-GND-to-MB-GND voltage across pad 4 during the turn-off; the tall stack raises the [TS] §(d) estimate to 0.08-1.34 V (three pins) at H_u 5-8 mm, and no spurious comparator or logic transition may follow it | Release of stage 2 to the T-D bench group and to PM1 | After T-K-09 and T-K-10; gates the T-D group and PM1 | Mixed |

#### 6.4.4 On the vehicle motherboard

In r2, "vehicle" means the vehicle MB on the stationary testbench that drives the flywheels (operator statement,
2026-11-10). "Drive" means a drive cycle on that testbench. The bench fan (FAN) runs in every T-K test on the MB unless
the row states the fan-off case. T-K-12 and T-K-13 run with the fan on and again with the fan off. The difference
separates the fan-motor conducted and radiated noise from the charger contribution. The fan lead returns to the bench
supply and does not use MB copper as its return (§1.6.3 item 3). The fan noise at the MB analog nets is TODO(measure:
T-K-12, T-K-13). T-K-20 is the decisive thermal test in r2. T-K-14 is its fan-on leg with the
additional records of the round-3 neighbourhood (LM1084, CO-5V, comparator area).

| ID | Purpose | Setup and steps | Pass | Decides | Order | Label |
|---|---|---|---|---|---|---|
| T-K-12 | Measure the conducted charger ripple that now enters the MB at pad 10 without the W1/W2 lead inductance | Vehicle MB with the CCB fitted; VESC unpowered; charger running from a bench current source into V-MOT (regen image, as in T-F-15) and through D-BC-FC (FC image); SCOPE at 20 MHz and full bandwidth on C-D8 pad 1 (VCHG-IN), C-D6 pad 1 (H1 tap via R170), C-D2 pad 1 (T2 tap via R171) and pin 38, against MB GND | V-MOT ripple at the H1 tap within the H.1 limits (the T-E-07 criterion), with the charger contribution included; VCHG-IN and pin-38 ripple recorded | Population of the input RC snubber R541/C541 (decision D9 (§2.1.1)); C302 values | After the CCB is fitted (after T-K-04, T-K-17, T-K-18); before T-K-13 and T-F-03 | Mixed |
| T-K-13 | Prove that charger switching does not disturb the Teensy analog inputs or the MB nets under the CCB | Vehicle MB with the CCB fitted; Teensy on a bench build that logs pins 22, 24, 25, 26, 38, 39, 40 and 41 at the production ADC settings; charger off, then converting at 0.3, 1.0 and 1.76 A input in the regen and FC images; SCOPE on MPPT-DISABLE (pin 5, header pin 11; runs at y 64.48 under the CCB) and CB-DISABLE (pin 9; runs at x 33.27 and x 41.40) at the CCB position (§1.5); SCOPE on the OP-FC output (FC droop chain under rect A') | Per channel: mean shift <= 2 LSB and standard-deviation increase <= 2 LSB against charger off (the T-C-15 cross-channel criterion); FR-49 never triggered by noise on pins 38/39; the pin-5 and pin-9 nets never cross the SN74LVC VIL 0.8 V / VIH 2.0 V band from their static level ([WD] B.3); CB-DISABLE never crosses the BQ29200 input threshold (TODO(verify: BQ29200 DS)); I_fc and I_batt unchanged within 50 mA in the share loop (the T-F-03 criterion) | Acceptance of the CCB ground layer next to the underside (§1.5); filter changes; use of rect A' | After T-K-12; before T-F-03 and before any FC window | IC-independent |
| T-K-14 | Thermal soak of the CCB in situ beside a hot LM1084 | Vehicle MB, CCB fitted, vehicle in Run with the T-K-02 LM1084 load; charger from a bench current source into V-MOT (regen image) and in the FC image; THERM on U501 top, L501, D303, D304/D305 (BAV199), the U302-U304 area, the LM1084 tab, the CO-5V body, the pin-18/19 header joint (MB side), the MB surface at the T-K-02 point (fitted before the CCB) and the air under the tab; TDIE over I2C. Profiles: 30 min at 2.5 A continuous; the T-B-16 burst profile at max(measured ICHG from T-B-19, 3.21 A) | TDIE < 100 C and TREG_STAT 0 (the T-B-16 criterion); comparator and logic area <= 60 C, else re-run T-C-03, T-C-10 and T-A-07 at the measured maximum + 10 C; LM1084 tab rise over the T-K-02 baseline recorded, with the junction estimate inside the [LM] §5.3 range (TODO(verify: LM1084 DS §5.3 control vs output section rows and the KTT thermal metrics)); CO-5V within its rating (TODO(verify: CO-5V datasheet)); pin-18/19 MB-side joint at or below the header or socket rating minus 20 C, with its rise over T_MB,local recorded (the modified T-F-16 criterion, §6.3.5); the MB surface rise over the T-K-02 T_MB,0 recorded, which checks P_MB x R_MB and R_total of §3.7.2. **r2 (testbench, fan):** T-K-14 runs as the fan-on leg of T-K-20, with FAN at the M15 velocities and the TC6 points of T-K-20 added. The pass items above stay and apply with the fan on. The T-K-02 T_MB,0 comparison is record only. The fan-off case and the FR-50 thresholds move to T-K-20 | FR-50 `CHG_TDIE_DERATE_C` and `CHG_TDIE_TRIP_C` (§5.6; r2: decided by T-K-20); the regen ICHG image (3.10 A or 2.50 A); the 750 kHz alternate; forced air (r2: fitted by design, §1.6.3); the T-A-07 temperature basis | After T-B-16 (bench) and T-K-13; before T-K-15, T-F-04 and the T-G group. r2: together with T-K-20 | Mixed (method IC-independent; TDIE and loss BQ25798-specific) |
| T-K-15 | Verify the FR-50 temperature guard | FIX1; HG on U501 with THERM; firmware with FR-50 and the T-K-14 thresholds (r2: the T-K-20 thresholds). Steps: heat until TDIE crosses `CHG_TDIE_DERATE_C`, then `CHG_TDIE_TRIP_C`; cool | At the derate threshold ICHG falls to the 2.50 A image and FC windows close through T5; at the trip threshold P5 goes LOW and stays latched until Idle (§5.6); TDIE against THERM recorded (REG41_TDIE_ADC, two's complement, 0.5 C per LSB, POR value 0 C; [DS] §7.5.1.53 Table 7-66) | Acceptance of FR-50 | After T-K-14 (r2: after T-K-20); before T-G-01 | BQ25798-specific (detection); IC-independent (hazard) |
| T-K-16 | Verify the FR-51 battery-path check and bound the transient of a BAT-path opening | FIX1 with a relay or MOSFET switch in the battery wire between pins 18/19 and BATSIM; SCOPE on TP502 (VCHG), TP510 (CHG_SYS) and SW2; firmware with FR-51. Steps: (1) with BATSIM at 7.4 V, open the battery wire while charging at 0.5 A first, then 1.0 A and 3.10 A, 10 events each; then a 10 ms on/off chatter; (2) repeat the 3.10 A events with BATSIM at 7.8 V, 8.2 V and 8.3 V (above VREG - `CHG_VBAT_AGREE_V`); (3) at 8.3 V, open the wire and hold it open until the IC terminates (CHG_STAT 111b); (4) at 8.37 V, inside the published blind band, record the outcome | VCHG and CHG_SYS peaks below the [DS] §6.1 absolute maxima (BAT 20 V, SYS 23 V, Table 2.2); at every BATSIM setting of steps (1)-(2), P5 LOW and `chg_flags.bat_path_fault` set within 150 ms (FR-51 item 5); at 8.2 V and 8.3 V the trip comes from criterion (b); in step (3) the fault is set and `chgFull` is not (FR-51 item 4); step (4) is recorded only, against the FR-51 item 6 band; no part damage; charging stays refused until Idle | `CHG_VBAT_AGREE_V` (with the T-E-13 gain and the T-K-17 header drop); whether the omitted BAT TVS (decision D11 (§2.1.1)) must be fitted | After T-B-19 and T-K-17 (header drop); before T-F-03 | Mixed |
| T-K-17 | Measure the header contact resistance and the retention of the CCB | CCB on the vehicle MB (option K or S); MOHM; SCALE. Steps: (1) 4-wire from the MB pad to the CCB pad on pins 4, 10, 14, 15, 18 and 19; (2) option K only, foot screws removed: axial pull-out force by SCALE, then re-seat; (3) mating cycles logged; (4) apply the T-F-11 12 A brake and the 3.1 A burst; measure the MB-pad-to-CCB-pad voltage on pins 4, 14 and 15; divide each voltage by the step-(1) resistance of that pin | Each power contact <= the socket or header datasheet contact resistance (TODO(verify: chosen part datasheet)); within each pair (18/19, 14/15) the resistance ratio <= 1.5, which is the 60/40 sharing basis of the >= 2.0 A per-pin rating (Table 1.13, [WD] A.8 r6); pull-out force recorded (retention is credited to the foot screws, §1.7.2 item 1); step (4): pin 4 <= 3 A and pins 14 and 15 <= 2.0 A each, including MB ground current that the CCB plane carries (Table 1.13, §1.13.3) | Option S or K for the vehicle; the header drop that enters the FR-51 threshold | After T-K-04; repeated after each T-K-19 interval. r2: T-K-19 is not applicable (testbench); repeat step (1) after every 10 mating cycles and after each removal of the CCB, with the 20 % drift record of T-K-19 as the proposed limit (OT-1). The r2 tall pins add 0.66-1.47 mOhm per pin at H_u 5-8 mm ([TS] §(a)), which the step-(1) reading includes | IC-independent |
| T-K-18 | Verify the overhang support | Two nylon M3 spacers bonded at (23.20, 70.64) and (32.20, 70.64) (§1.4), cured per the adhesive datasheet; one sacrificial spacer bonded with the same adhesive and cure to a scrap FR-4 board with solder mask (TODO(verify: mask equivalent to the MB)); torque driver; SCALE; feeler gauge; no threadlocker (§1.7.2 rule 2). Steps: (1) on the sacrificial spacer, increase the torque on the hex in steps until the bond breaks, and record the breakaway torque T_b; (2) set T_s at or below T_b / 2 (proposed, TODO(operator ruling)) and within the screw rating (TODO(verify: nylon M3 screw datasheet)); (3) on the MB feet, ten fit-and-remove cycles of each foot screw at T_s, with the spacer hex held; (4) with the screw removed, T_s applied to each spacer hex by the torque driver for 10 s; (5) with both screws tight at T_s and the gap pad fitted if used, feeler between the header body and its seat; (6) axial pull for 10 s on each foot of max(20 N, F_pad), where F_pad is the gap-pad compression force at the fitted thickness (§3.7.4; 0 N without a pad); (7) deflection of the tab corner (38.90, 76.40) under 1.2 N | (1)-(2) T_b and T_s recorded; (3)-(4) no bond movement, no mask lift and no crack after the cycles and the torsion hold; (5) header still seated (no gap > 0.05 mm, proposed); (6) no bond movement and no crack; the pull is at least 2 x the per-foot gap-pad load (F_pad / 2) and about 16 x the 1.2 N load of a 12 g board at 10 g (§1.7.1); the 20 N floor is the T-F-12 pull-check value and is provisional pending an operator ruling; (7) deflection recorded. **r2 (testbench, tall stack):** the load case is handling, probing and repeated insertion, not vibration (operator statement, 2026-11-10); the 1.2 N case of a 12 g board at 10 g is a record. The spacers are of length H_u (5.1-8.1 mm, §1.4), so steps (1)-(4) use a spacer of the chosen H_u; a lateral force F at the CCB gives a bond moment F x H_u, 2.0-3.2 times the r1 value at H_u 5-8 mm ([TS] §(e)). Step (5) has no gap pad (§3.7.4 superseded), so F_pad = 0 N in step (6). The 20 N floor is about 1.8-2.2 x the 9.3-11.1 N per-foot reaction of a 10 N upward pull at the tab edge ([TS] §(e): 18.6-22.1 N on the two feet, both clamp lines). Added step (8): with both screws tight, a 10 N force at the tab edge (38.90, 76.40), up, down and sideways; pass: no bond movement, header still seated, deflection recorded against the [TS] §(e) value of 0.0104-0.0133 mm with the feet | T_s; bonded foot (option B) or drilled foot (option D, operator approval, §1.4); r2: the spacer length | After T-K-04; before T-K-19 and any drive (r2: before T-K-12 and any drive cycle) | IC-independent |
| T-K-19 | Check retention on the road, where no vibration specification exists (§1.7, item 14). **r2: T-K-19 is not applicable (testbench).** The vehicle does not move, so no road vibration acts on the CCB (operator statement, 2026-11-10). The row above is the r1 record. Retention matters only for handling and repeated insertion, which T-K-17 (repeat after mating cycles) and T-K-18 step (8) cover. The visual items (foot bonds, staked L501, tap-lead strain relief, polyimide chafe, coating) stay in the 6-month T-C-12 / T-F-17 inspection class | Vehicle; IMU if available; MOHM. Steps: baseline T-K-17 and photographs; a first attended 10 min drive with P5 held LOW (charger inhibited), to separate mechanical from electrical effects; then inspections after 1 h and 5 h of cumulative driving: header joints or socket seating, foot bonds (loupe on the bond edge for a mask lift or a crack; each foot screw checked at T_s without loosening, and it must not turn), staked L501, tap-lead strain relief, polyimide chafe and coating cracks (the T-F-12 items); re-run T-K-17; read the FR-51 event count | Contact resistance within 20 % of the baseline (proposed, TODO(operator ruling)); zero `bat_path_fault` events; no visible movement, chafe or crack; no mask lift at a foot bond and no foot screw that turns at T_s | Retention adequacy; option S for a frozen revision; the inspection interval (the 6-month class of T-C-12 and T-F-17) | After T-K-17, T-K-18 and T-F-12; the first drive before T-G-01; repeats at the chosen interval | IC-independent |
| T-K-20 | Decide the r2 thermal design: the fan-on junction temperature and the fan-off guard; measure the real h and gap flow (r2, new) | Vehicle MB on the testbench, CCB fitted at the chosen H_u (M3), FAN at the low-y inlet (§1.2.3), ANEMO, TC6, firmware with FR-50 and the starting thresholds of §5.6. Thermocouples (M16): U501 top (T_J is about T_top + psiJT 0.5 C/W x P_IC, about +1.2 C at 2.31 W, [DS] §6.4), the PGND pour beside U501, L501, the MB surface under the cell, the pin-18 MB-side joint, the inlet air, the outlet air at y 67.14 and at the tab end y 76.40; TDIE over I2C. Charger from a bench current source in the regen image. Steps: (1) fan on: air velocity at the inlet edge, in the gap at the inlet, at mid-body and at both outlets, and about 5 mm above the CCB top (M15); fan voltage and current; (2) fan on: 2.7 W and 2.9 W points to steady state (rise < 1 C in the last 5 min); (3) stop the fan at the 2.7 W point; log TDIE, the derate and trip instants and the CCB heating curve; continue for 30 min or more, or until the FR-50 trip (30 min is about 6-11 x the 164-303 s lower-bound time constant, [LC] §8.7); (4) repeat step (3) at the 2.08 W derate image (ICHG 2.50 A); (5) restart the fan and log the recovery | (2) TDIE <= 100 C at 2.9 W with the fan on, at the measured room air (M17) and with 2 m/s or more in the gap and over the top (M15), and TREG_STAT 0 ([DS] Table 7-38); gap-only flow gives 88-115 C at 2.9 W ([LC] §8.6); the [LC] §8.6 model gives 78-90 C on a 25 C bench at g 5 mm and 2 m/s over both sides; (1)-(2) the measured R_total = (T_CCB - T_air) / P and the derived h are recorded against the [LC] §8.6 band (9.8-14.2 C/W at g 5 mm, 2 m/s), and the outlet air rise against the 10.1 C upper bound at g 5 mm, 2 m/s ([LC] §8.6c); (3)-(4) FR-50 derates and then trips before TREG_STAT sets (TREG default 120 C) and before TSHUT (150 C) ([DS] §6.5); the model gives 104-142 C at 2.7 W and 86-116 C at 2.08 W fan-off at g 5 mm on a 25 C bench ([LC] §8.7), so the trip, not the derate, must act; (5) charging resumes only by the FR-50 latch rules (§5.6) | `CHG_TDIE_DERATE_C` (starting value about 95 C) and `CHG_TDIE_TRIP_C` (about 105-110 C), TODO(calibrate); the fan, its duct and the capture fraction (30-50 % assumed, [LC] §8.9); H_u within 5-8 mm (§1.3.2 rule 3); the U501 heatsink (DNP, §3.7.4a), fitted if the fan-off case exceeds the trip margin or the fan-on case fails; verdict condition 3 | After T-K-13; with T-K-14 (its fan-on leg); before T-K-15, T-F-04 and the T-G group. An optional pre-run on FIX1 with FAN gives early values | Mixed (method IC-independent; TDIE, TREG and loss BQ25798-specific) |

### 6.5 Ordering

#### 6.5.1 Round-3 gates that stay

Every round-3 ordering rule of [WD] §0.2 and D.1 stays in force. Table 6.2 lists them with their CCB form.

| Gate | Precedes | Source | CCB note |
|---|---|---|---|
| T-W-01 (and T-C-14, FR-42) | Every FC-charge window, attended or not; T-D-02 case (a) | [WD] R5, §0.2 item 10, T-C-14 | Unchanged |
| T-E-04 | T-B-09, T-B-10, T-B-12 | [WD] T-B-09 | Unchanged |
| T-B-09 fails | T-A-05c, then fallback 2 | [WD] T-A-05c | Unchanged |
| T-A-01, T-A-01b, T-A-01c | Tap fitting (PM6), T22 (PM11), P24 `PURGE_SENSE` | [WD] D.1 | Unchanged |
| T-A-06 (step 0 included) | PCB order | [WD] D.1 PM0 | Netlist from §2.5 |
| T-A-06c | Sheet bonding and CCB fitting (PM4 class) | [WD] D.1 PM4 | Unchanged |
| T-B and T-C bench gates | PM1 (Ag105 removal) | [WD] D.1 PM1, study condition 13 | T-K-05 to T-K-11 join this set |
| T-C-04 at 8 V and 12 V | T-C-04 at full voltage | [WD] T-C-04 | Unchanged |
| T-C-10 | TW_HB_MAX and TW_QQ_MAX constants | [WD] T-C-10 | Measured on the CCB monostables |
| T-B-20 | T_REGN_MAX | [WD] T-B-20 | Unchanged |
| T-F-08 | Any FC window with traction load | [WD] §0.2 item 6 | Unchanged |
| T-E-01, T-F-07, T-F-07b | `PURGE_RESCUE_ENABLED 1` | [WD] §0.2 item 5 | Unchanged |
| T-E-13 | T-F-14 and VREG 8.40 V | [WD] T-E-13 | Unchanged |
| T-B-19 and T-E-11 | ICHG 3.10 A image | [WD] §0.2 item 4 | T-K-14 also bounds it; r2: T-K-20 with the fan on |
| T-C-12, T-F-17 | Repeat every rebuild and every 6 months | [WD] T-C-12, T-F-17 | Unchanged |

#### 6.5.2 Sequence

The CCB adds three ordering facts. First, T-K-01 and T-K-02 must run while the Ag105 is still fitted. Second, the interlock
logic is proven on stage 1 before the power stage is fitted. Third, the same-board coupling tests gate the vehicle.

r2 changes the sequence in three places (operator statement, 2026-11-10). First, T-K-02 is record only, so phase 0 no
longer holds a thermal gate; the h_s, M5, M7 and M8 records of T-K-01 still need the fitted Ag105. Second, M15 (fan
delivery) runs on the 1:1 template before layout and again on the built CCB; T-K-20 and T-K-14 run together in phase 5
and gate T-K-15. Third, T-K-19 is not applicable, so phase 6 has no road-retention step; T-K-17 repeats after mating
cycles instead.

1. **Phase 0, vehicle as it is (Ag105 fitted):** T-K-01, T-K-02, T-A-01, T-A-01b, T-A-01c, T-A-06c and the T-E group
   (T-E-04 first among the T-B prerequisites; T-E-09 decides R525 or R526; T-E-11).
2. **Phase 1, design:** T-A-05, then T-A-06 with step 0. Order the PCB only after both pass.
3. **Phase 2, incoming:** T-K-03, T-A-03, T-A-04, and T-A-07 at 25 C and 60 C (the hot-site point waits for T-K-14).
4. **Phase 3, stage 1 on FIX1:** T-K-05, then T-C-01, T-C-01b, T-C-01c, T-C-02, T-C-03, T-C-10 and T-C-12.
5. **Phase 4, stage 2 on FIX1:** T-K-06, T-B-01, T-K-07, T-K-08, T-K-09 with T-K-10, then the T-B group (T-B-19 before
   T-B-16), T-C-04, T-C-05 and T-C-07 (FI1 for the open joints), T-C-06, T-C-09, T-C-11, T-C-14, T-C-15, then T-K-11, the
   T-D group (FI1 for T-D-03, T-D-06 and T-D-11; T-D-02 case (a) only after T-W-01), T-K-16, and the bench parts of T-W-01
   and T-W-02.
6. **Phase 5, vehicle fit:** PM1 only after phases 3-4 pass; T-F-01; T-K-04; fitting; T-K-17; T-K-18; T-F-12; T-K-12;
   T-K-13; T-K-14 with T-K-20 (r2); T-K-15; T-A-07 hot-site point; T-F-02; T-F-03; T-F-04c; T-F-05; T-F-11; T-F-13 to T-F-17.
7. **Phase 6, FC windows and road:** T-K-19 first drive (P5 LOW); T-W-01 on the vehicle; T-F-08; then T-F-04, T-F-04b,
   T-F-06, T-F-07, T-F-07b, T-F-09 and the T-G group in the round-3 order; T-K-19 repeats at its interval. r2: phase 6
   runs on the testbench, and its drives are drive cycles (§6.4.4). T-K-19 is not applicable (testbench). Its two
   positions in this list are records only.

#### 6.5.3 Option: early IC-behaviour tests on a stock EVM

Several T-B tests ask only how the BQ25798 behaves: T-B-02, T-B-05, T-B-08, T-B-11, T-B-13, T-B-15, T-B-17, T-B-20, T-B-21,
T-B-22 and T-B-25. They could run on an unmodified BQ25798EVM before the CCB is ordered, so that a disqualifying IC result
arrives before the fab cost. However, this reintroduces an EVM purchase (USD 156.45 recorded in [WD] E), and the results
must be repeated on the CCB where they depend on the ILIM_HIZ or /CE network. This is a scheduling choice for the operator,
not a requirement.

### 6.6 Separation for an alternative charger IC

Table 6.3 groups the new tests by label, so that the parallel IC search can take the IC-independent set as it is.

| Label | New tests |
|---|---|
| IC-independent | T-K-01, T-K-02, T-K-03, T-K-04, T-K-13, T-K-17, T-K-18, T-K-19 (r2: not applicable, testbench); the methods of T-K-09, T-K-14 and T-K-20 (r2) |
| BQ25798-specific | T-K-06, T-K-07, T-K-08, T-K-10; the TDIE detection of T-K-15; the TDIE and TREG criteria of T-K-20 (r2) |
| Mixed | T-K-05 (values are BQ25798-specific, the method is not), T-K-11, T-K-12, T-K-16 |

For another IC, T-K-07 keeps its method with that IC's switch-node and bootstrap absolute maxima. T-K-08 keeps its method if
the IC uses one external inductor. T-K-10 is rewritten for that IC's control pins. The T-B group is rewritten in full.

### 6.7 Requests to the schematic, the layout, the firmware and the calculations

1. **Schematic (§2):** confirm that FI1 needs no extra footprint. The open-joint injections of T-C-05, T-D-03, T-D-06 and
   T-D-11 lift R458, R462, R472/R472b, Q401, U401 pin 7, U401 2Y/3Y and U402 pin 4. A 0402 0 ohm link in the U401 1Y-to-/CE
   trace would make the T-D-03/T-D-06 injection reversible; it adds a joint in a fail-safe direction (open = /CE HIGH).
   TODO(decision: schematic owner).
2. **Layout:** LOOP1 needs an L501 pad option for a wire bridge. SW1 and SW2 need a probe landing with a ground point within
   5 mm (no test point is allowed on SW1/SW2 by §2.5.10, so the L501 and C529 pads serve).
3. **Firmware (§5):** bench token builds are needed for T-K-06 step 5 (ICHG 0.5 A), T-K-15 (FR-50) and T-K-16 (FR-51).
4. **Calculations:** the TODO(calc) items of T-K-05 (expected in-circuit resistances, logic quiescent budget), T-K-06 step
   (1), T-K-09 step (5), T-B-03 (H.4 levels) and T-F-13 (CCB R_path band) all come from one re-run of `r3_calc.py` and
   [CALC] with the CCB values (O-11).
5. **Calculations (r2):** the T-C-04 records need the OUT copper inductance from U301 OUT to the C511/C512 short. It
   comes from the capture. They also need the D307 energy at the ideal turn-off current of up to 117 A ([TS] §(c); N-25). T-F-16 and T-K-20 need
   the pin-18 joint temperature with forced air ([LC] §8 does not compute it). TODO(calc).

## 7. Comparison with Path A and Path B, and the review-finding ledger

### 7.0 Scope, names, sources and conventions

#### 7.0.1 Scope (IC-independent)

This section compares three ways to replace the Silvertel Ag105 (BOM designator CHG) on the motherboard (MB) rev 20260622.
It gives (a) an effort, cost, schedule and risk comparison, (b) a ledger of the round 1-6 review findings against the custom
board, with the new findings that the CCB opens, and (c) a recommendation stated as a trade-off. It is a planning
document. Nothing is ordered, no firmware is changed and no capture is made.

#### 7.0.2 Names (IC-independent)

The names below are used verbatim in this section.

| Name | Definition | Source |
|---|---|---|
| **Path A** | Round-3 r6 design: an off-board BQ25798EVM with 25 listed modifications EM1-EM25 (17 physical), 0.3 m leads W1-W8, a 4-layer carrier (CR) in the 22 CHG holes and a 2-layer EVM interface board (EIB) on a ribbon | [WD] A.1, C; [EVAL] 0.1a |
| **Path A-C: custom charger board** | One 4-layer board (the **CCB**) in the 22 CHG holes that carries the BQ25798 power stage, the CR interlock logic and the EIB stages. Sideways tab over rect A | Sections 1-6 of this document |
| **Path B1** | Minimal MB re-spin: the charger IC on a new MB, all bodges folded in; under the round-2 rulings it must also carry the H1/H2 interlock | [PB] 2; [EVAL] line 961 |
| **Path B2** | MB re-spin with a bidirectional pack-to-bus converter in place of the BT boost and the charger | [PB] 3 |

The count of "11 EVM modifications" refers to [EVAL] §4.2 M1-M11; round 3 superseded them with EM1-EM25 (§2.4.1).

#### 7.0.3 Sources

The citation keys of this section are defined in section 9.

#### 7.0.4 Conventions (IC-independent)

1. Each subsection and table row carries a label: **IC-independent (I)**, **BQ25798-specific (S)** or **Mixed (M)**.
2. **ESTIMATE** marks a figure that this section derives from a stated basis. No source records CR, EIB or CCB design hours.
3. One engineer-day is 8 h and one engineer-week is 40 h. One engineer (the operator) does all work, as [EVAL] 7 assumes.
4. Only the TI store prices of 2026-11-10 are verified (§4.0.1 class V). Every other cash figure is an allowance or an
   estimate from its source.
5. An effort or schedule range pairs the low figure of every row with the low figures of the other rows, and the high
   with the high. For example, the Path A-C design range 98-204 h of Table 7.1 is (60 - 10) + 24 + 8 + 8 + 8 h and
   (120 - 20) + 48 + 16 + 24 + 16 h. Interval arithmetic would give 88-214 h. A cost difference between two paths is a
   full span: the lowest total of one path against the highest total of the other, and the reverse.

### 7.1 Comparison of effort, cost, schedule and risk

#### 7.1.1 Assumptions (Mixed)

| ID | Assumption | Basis |
|---|---|---|
| AS-1 | Paths A and A-C use the same IC, register image, interlock logic, firmware requirements FR-01 to FR-49 and test registry | §1.12.1; §5.2-5.3; §6.2 |
| AS-2 | Firmware effort for Path A is 30-45 engineer-days, as [EVAL] 7 estimates (marked UNVERIFIED there) | [EVAL] 7 |
| AS-3 | Path A-C adds FR-50, FR-51 and the scope edits of §5.3: 1-3 engineer-days (ESTIMATE) | §5.3, 5.6 |
| AS-4 | Path A bench effort is at least the round-2 plan: S1 4-6, S2-S3 3-4, S4 2-3, S4-H20/S5 2-3 days, total 11-16 days. Round 3 grew the registry to 112 tests and recorded no new figure, so 11-16 days is a floor | [EVAL] 7; [WD] I |
| AS-5 | Path A-C adds 19 T-K tests and modifies 21 round-3 tests: +4-8 bench days (ESTIMATE). r2: 20 T-K tests (T-K-20 added; T-K-19 not applicable on the testbench; T-K-02 record only); the bench-day figure is unchanged (7.1.2, r2 note) | §6.2, 6.4 |
| AS-6 | The B1 design figure of 2-4 engineer-weeks covers the charger block only; the round-2 rulings add the interlock, which this section books at the CR design figure of AS-7 | [PB] 2.6; [EVAL] line 961 |
| AS-7 | CR capture and layout 50-90 h, EIB 10-20 h, review preparation 0-10 h (ESTIMATE). The netlist exists ([WD] B.8), so the work is capture, placement and routing of a double-sided 4-layer logic board at 74 % courtyard use | [WD] H.18b, PM0 |
| AS-8 | The PCB fab-plus-ship time is 2-3 weeks for every path, and turnkey assembly adds 1-3 weeks. These are the only lead-time figures in the sources; they are round-1 estimates | [PB] 2.6 |
| AS-9 | No source gives the probability of a first-pass layout failure. This section books one re-spin of the CCB as a planning contingency, not as a prediction. The contingency is outside the base figures: 3-6 weeks (AS-8 fab plus the PCBA cycle), USD 95-370 plus parts (Table 7.2) and about 26-62 h (ESTIMATE: re-assembly 10-22 h, layout correction 8-24 h, stage-1 and stage-2 re-bring-up T-K-05 to T-K-08 8-16 h). Tables 7.1 and 7.3 and the 7.1.8 summary list it in a separate row | 7.1.6 |
| AS-10 | r2: the vehicle is a stationary testbench that drives flywheels, a fan may be mounted on the CCB, and the CCB has no height restriction (operator statement, 2026-11-10). Path A has the same testbench; its EVM, CR and EIB need no fan decision in the sources, and none is priced here | §0.9 r2; §1.6.3 |

#### 7.1.2 Effort (Mixed)

Table 7.1 gives the effort in hours. Every row is an ESTIMATE unless a source is named in the basis column.

| Item | Path A | Path A-C | Path B1 | Path B2 | Basis |
|---|---|---|---|---|---|
| Design: capture, layout, review preparation | 60-120 h (CR + EIB) | 98-204 h | 130-250 h | 320-560 h | A: AS-7. A-C: AS-7 less the EIB (-10-20 h), plus the power cell 24-48 h, the interface stages 8-16 h, the area reduction from 101 % to 78-86 % 8-24 h (§3.2.3), outline, feet and thermal 8-16 h. B1: [PB] 2.6 80-160 h plus AS-6. B2: [PB] 3.3 8-14 engineer-weeks |
| Assembly (boards) | 21-42 h | 10-22 h (PCBA, option P) or 26-52 h (hand, option H) | 2-6 h | 2-6 h | A: EVM modifications 4-8 h, CR hand build 10-20 h ([WD] J.2 item 17: VQFN-24 by hot air), EIB 3-6 h, leads, ribbon and standoffs 4-8 h. A-C: hand-fitted headers, taps, R342 and R525/R526 4-8 h (§4.4.3); fixture and test boards FIX1, FI1, LOOP1 6-14 h (§6.1.4); option H adds 16-30 h for 176 placements. B: turnkey, through-hole parts only |
| MB rework on the existing board | 8-16 h | 10-20 h | 0 h | 0 h | PM0-PM11 ([WD] D.1). A-C adds socket strips and two bonded feet (§1.3.4, 1.4) and removes the chassis standoffs. B: the existing board is not modified ([PB] 5.1) |
| Bring-up and bench gates | >= 88-128 h | 120-192 h | 168-368 h | about 160-400 h plus campaigns | A: AS-4. A-C: AS-4 plus AS-5. B1: [PB] 2.6 board bring-up 2-6 weeks (80-240 h) plus the charger and interlock gates of AS-4. B2: [PB] 3.3 1-2.5 months |
| Firmware, HIL, EMS | 240-360 h | 248-384 h | 264-424 h | 504-760 h | A: AS-2. A-C: AS-3. B1: AS-2 plus re-spin housekeeping 3-8 days ([PB] 2.6); the [PB] figure of 23-37 days predates the interlock. B2: [PB] 3.3 63-95 days |
| **Total** | **417-666 h** | **486-822 h** (option P) | **564-1048 h** | **about 990-1730 h** | Sum of the rows |
| Total in engineer-weeks | 10.4-16.7 | 12.2-20.6 | 14.1-26.2 | about 25-43 | / 40 h |
| Re-spin contingency (AS-9), not in the total | CR re-spin about 14-32 h | about 26-62 h | in the [PB] range | in the [PB] range | A: CR hand build 10-20 h (row 2) plus layout correction 4-12 h (ESTIMATE: logic board without a power stage). A-C: AS-9 |
| Total with one re-spin | 431-698 h | 512-884 h | as above | as above | Total plus the contingency row |

Path A-C costs about 70-155 h more than Path A. The power cell, the area reduction and the T-K tests account for the
difference.

r2 changes the Path A-C rows by the deltas below. Each delta is an ESTIMATE without a source, like the hours of
Table 7.1 (C-1):

- the fan bracket, the duct and the gap rule add about 4-8 h of design;
- T-K-20 and the M15 velocity survey add about 8-16 h of bench work;
- T-K-19 (a first drive and two inspections, about 6-12 h) is not applicable, so its hours are removed;
- the T-K-02 heater step (about 4-8 h) becomes optional.

By interval arithmetic, the net change is -8 to +14 h if the heater step is dropped, and 0 to +18 h if it is kept.
The largest value, +18 h, is 3.7 % of the 486 h lower total. This is inside the spread of the r1 estimates, so the
totals of Table 7.1, the 7.1.8 summary and Table 7.3a stay as in r1. The firmware dominates every path: it is about 54-58 % of the Path A total and 47-51 % of the Path A-C total.

#### 7.1.3 Cost (Mixed)

Table 7.2 compares the cash cost. The figures come from section 4 and the recorded round-3 and round-1 estimates.

| Item | Path A | Path A-C | Path B1 | Path B2 |
|---|---|---|---|---|
| Recorded parts total | about USD 505-540, including 2 x BQ25798EVM at the verified USD 156.45 ([EVAL] 0.1a; [WD] E) | Two populated boards (build 2): USD 470-520 hand, USD 545-745 with PCBA, including the r2 bench fan (§4.5.2) | about USD 1-2k for 5 boards ([PB] 2.6, ESTIMATE, round 1) | about USD 2-4k over 1-2 spins ([PB] 3.3, ESTIMATE) |
| Representative build for the test plan | One CR + EIB build; a fault-injection build is not priced, TODO(verify: [WD] T-C-05 build count) | Four populated boards (vehicle, spare, FI1, LOOP1, §6.1.4), build 4: USD 652-702 hand, USD 727-927 PCBA (§4.5.2). The LOOP1 layout variant is not included: a separate fab lot adds USD 70-120 (§4.4.1); a wire-bridge pad option on every board adds SW-node copper and a joint in the L501 path, TODO(analysis: SW-node area, T-K-07 ringing on the production board). The choice is A-4 (§6.7 item 2) | as above | as above |
| Verified share | USD 312.90 (EVMs) | USD 101.94 of build 2 (TI silicon) (§4.5.2) | none | none |
| Re-spin contingency (AS-9) | CR/EIB lot: allowance USD 70 ([WD] E) plus logic parts | USD 95-370 (PCB 70-120, plus the stencil 25 by hand or PCBA 100-250 including the stencil, §4.4.1-4.4.3) plus parts | included in the [PB] range | included in the [PB] range |
| Optional IC-behaviour EVM (§6.5.3) | already present | USD 156.45 (161 in TI stock on 2026-11-10, §4.2) | optional | optional |

On the recorded allowances, Path A-C at two boards is between USD 70 below and USD 15 above Path A with hand assembly.
With PCBA it is USD 5-240 above Path A (§4.5.3; full spans, §7.0.4 item 5). The test plan needs four boards (build 4). At
four boards, Path A-C is USD 112-197 above Path A with hand assembly and USD 187-422 above it with PCBA. These deltas exclude
the LOOP1 lot and the unpriced fault-injection build of Path A. The cost case for Path A-C is therefore weak, as §4.5.3
also concludes. Path B1 costs about two to four times Path A, but it yields five
new boards and leaves the existing board as a bench and HIL reference ([PB] 5.1).

#### 7.1.4 Schedule and lead times (Mixed)

Table 7.3 gives the lead-time chain for each path. Durations convert the hours of Table 7.1 at 40 h per week.

| Step | Path A | Path A-C | Path B1 | Basis |
|---|---|---|---|---|
| Charger hardware in hand | EVM in TI stock (161, 2026-11-10); ship days to about 2 weeks | U501 in TI stock (415 146); SN74LVC2G08DCTR at zero stock, DCTRE4 named (§4.1.2 item 5); non-TI stock TODO(verify) | as A-C | §4.2; [PB] line 345 |
| Design | CR + EIB: 1.5-3.0 weeks | 2.5-5.1 weeks | 3.25-6.25 weeks | Table 7.1 |
| PCB fab and shipping | 2-3 weeks (CR 4-layer, EIB) | 2-3 weeks; 0.1/0.1 mm may lengthen it, TODO(verify: fab quote, L-2) | 2-3 weeks | AS-8 |
| Assembly | Hand, about 1 week | PCBA 1-3 weeks plus a quote cycle, TODO(verify: quote, B-7) | Turnkey 1-3 weeks | AS-8; §4.4.3 |
| First bench charge on the path's own charger hardware | about 1-3 weeks (modified EVM, [EVAL] 7: Track 1 in week 3) | about 7-13 weeks (after stage 1 and T-K-06, §6.5.2) | about 10-15 weeks ([PB] 2.6 8-13 weeks plus the interlock design of AS-6) | sums of the rows above |
| First bench charge with one re-spin (AS-9), not in the row above | unchanged on the modified EVM; a CR re-spin adds about 3-4 weeks before the CR-dependent gates (fab 2-3 weeks plus hand assembly 1 week) | about 10-19 weeks (7-13 weeks plus 3-6 weeks) | not separated in [PB] 2.6 | AS-8; AS-9 |
| Bench gates complete | round-2 plan: S5 by week 6-7; round 3 adds a CR/EIB fab cycle with no revised date ([EVAL] 0.1a) | about 3-5 weeks after the first charge (AS-4, AS-5) | 2-6 weeks of board bring-up ([PB] 2.6) plus the charger gates | [EVAL] 7; [PB] 2.6 |
| First FC-charge window on the vehicle | Gated on T-W-01 and the firmware (6-9 weeks of work) on every path ([WD] R5; §6.5.1) | as A | as A | AS-2 |

Path A-C delays the first bench charge by about 6-10 weeks against Path A. The cause is the design-fab-assembly cycle in
front of the charger. However, the firmware (6-9 weeks for one engineer) and T-W-01 gate every FC window on every path. Firmware
work during the fab wait therefore hides part of that delay at vehicle level. A stock EVM bought for the IC-behaviour subset
(§6.5.3) would move the first IC data of Path A-C to about 1-3 weeks.

r2 adds the bench fan, its mount and the tall-stack headers and spacers to the Path A-C parts list (§4.5.2). They are
catalogue parts, and their stock and lead time are TODO(verify: distributor). They are not expected to lengthen the
critical path, because the PCB fab and assembly take 3-6 weeks (Table 7.3). The M15 velocity survey on the 1:1 template
runs during the design step.

#### 7.1.5 Risk (Mixed)

Table 7.4 lists the technical risks that separate the paths. Risks common to all paths (purge timing, VESC cut-off, watchdog,
INA253 floor) are in [WD] J and in the ledger of 7.2; they do not discriminate and are not repeated.

| Risk | Path A | Path A-C | Path B1 | Path B2 | Label |
|---|---|---|---|---|---|
| Power-stage layout | TI's 4-layer EVM, factory built; the SLUSDV2C efficiency curves were measured with the EVM inductor (§3.7.1) | Own first-pass 4-layer cell (7.1.6) | Own first-pass cell on a whole board ([PB] 2.6: "moderate") | Two new power stages ([PB] 3.3: "high") | S |
| Hand-built inter-board wiring | 0.3 m leads, a 0.30 m ribbon, 17 physical EVM changes; [EVAL] 6.4 item 5 lists coupled glitches or ground shifts in the hand-wired carrier as a re-spin trigger | None inside the charger chain; taps remain | None | None | I |
| Assembly of the charger IC | Done by TI | U501: 29 pads (33 lead segments), 0.4 mm pitch, no exposed pad, hidden joints carrying 3.21 A (§4.4.3); PCBA recommended | Turnkey | Turnkey | S |
| Area | CR 74 % ([WD] H.18b) | 101 % as drawn; 78-86 % after the remedies (§3.2.3) | Free to choose | Free to choose | M |
| Thermal coupling to the LM1084 | EVM 20 mm or more from the LM1084 on standoffs (§1.6.2) | r1 record: 2.7 W at 13.4 mm from the LM1084 courtyard over a closed air layer (2.415 mm for option S); T_J about T_MB,0 + 71-86 C (option S, no gap pad) or + 55-72 C (option S, gap pad), including 11-21 C of MB self-heating; option K needs the gap pad (§3.7.2). r2 (testbench, fan): the bench fan blows over the top and through the 5-8 mm gap; T_J - T_air is 49-61 C at 2.7 W (g 5 mm, 2 m/s both sides), that is 74-86 C on a 25 C bench, without a gap pad; T_J moves by 0.15-0.30 C per C of MB idle offset ([LC] §8.6, §8.6b; §3.7.3a). The outlet air leaves away from the LM1084 (§1.2.3) | Placement by design | Placement by design | M |
| Battery current through header pins | CR pins 18/19 and 14/15 carry 3.21 A ([WD] A.8) | Same pins, same current; pin rating TODO(verify); option-K socket contacts add an estimated 74-116 mW each at an assumed 20 mOhm (§3.3.2) | Copper on the MB | Copper on the MB | I |
| Retention (r1 title: on a moving vehicle; r2: handling and repeated insertion on the testbench) | EVM on chassis standoffs, leads strain-relieved; CR soldered | r1 record: 8-12 g cantilever on a socket and two bonded feet; no vibration specification exists (§1.7). r2: not applicable as a road risk (testbench, operator statement, 2026-11-10). Retention remains a handling and repeated-insertion item: a 10 N tab-edge force puts 18.6-22.1 N on the two feet, and the bond moment grows by H_u / 2.54 ([TS] §(e)); T-K-17 and T-K-18 step (8) | Board mounting as today | as B1 | I |
| Bench fan (r2) | No fan decision in the sources (AS-10) | The design case needs forced air on both sides: fan-off, T_J - T_air is 79-117 C at 2.7 W (g 5 mm), so the FR-50 trip, not the derate, protects U501 ([LC] §8.7). The CCB node time constant of 164-303 s gives the guard minutes to act. The fan supply must not load the LM1084 / CO-5V rail ([LC] §8.10). Fan MPN and curve TODO(verify) | Placement by design; a fan only if needed | as B1 | M |
| Tall header stack (r2) | CR at the r1 stack height | H_u 5.1-8.1 mm for the fan channel: +0.66-1.47 mOhm per pin; up to +10.8 nH on the pad-10 / pad-4 loop, which moves the hard-short IN peak by 0-0.3 V; a CCB-to-MB ground shift of up to 1.34 V (three pins) during a hard-short turn-off at 8 mm ([TS] §(a)-(d)); header, socket and spacer MPNs TODO(verify) | Not applicable | Not applicable | I |
| Switching noise next to the interlock | Converter 0.3 m from the comparators | Same ground plane as MOhm comparator nodes; 10 mm separation rule is unsourced (§3.6.1) | Same as A-C, on one board | Same as A-C | M |
| Risk to the only working board | Ag105 desolder (PM1): solid GND pads on a 1.66 mm board ([PB] 5.1: "Real") | Same desolder; option K then removes all later soldering on the MB | None; creates spares | None | I |
| Reversibility to the Ag105 | CR soldered in the holes (PM4) | Option K accepts the Ag105 again if the socket takes its 0.64 mm pin, TODO(verify) (§1.3.3) | Old board unchanged | Old board unchanged | I |
| IC substitution by the parallel IC search | New EVM, new EVM modifications, new EIB | New power stage and interface block on a new CCB; the IC-independent blocks keep their layout only if the outline allows (§1.10.2) | New re-spin | New re-spin | M |

#### 7.1.6 First-pass layout risk (BQ25798-specific)

Path A-C replaces a validated layout with a first-pass layout. The facts below set the size of that risk.

1. The RQM package has 29 pads (33 lead segments) of 0.20 mm width at 0.40 and 0.45 mm pitch and no exposed pad ([DS]
   pp.148-149; §3.4.6). Heat leaves through the power pads only, so the power-pad copper is both the electrical and the
   thermal design (§3.7.3).
2. TI calls the placement order "essential" (§3.4.1). In rev C, the labels of Figure 8-21 do not match the numbered list
   ([TID] 7 item 9; 4.4). The land pattern and the stencil apertures of SLUSDV2C pp.149-150 are transcribed in §3.4.6.
3. TI publishes no EVM layout files ([TID] 8), but the TIDA-050047 reference design publishes an Altium project and
   4-layer Gerbers of a BQ2579x power stage in the same RQM package ([TIDA]). §3.4.7 transcribes that layout, and
   Figure 3.2 follows it. The CCB still departs from it in the inductor side, the part sizes and the outline (§3.4.8),
   so the CCB layout remains a first-pass layout.
4. The project's own first layout lost about two weeks to boost deaths before the hot-loop cause was found (Death 1 on
   2026-06-24 to the fix on 2026-07-07; [PB] 2.6). That event concerned the TPS61288 boosts, not a charger. However, it shows
   that a hot-loop error on this vehicle presents as part failures, not as a soft performance loss.
5. The staged bring-up of §6.4.2 (logic first, power stage second, current-limited sources, T-K-06 to T-K-08) bounds the
   damage of a layout error. It does not remove the re-spin.

No source quantifies the probability of a rev-A failure. This section books one re-spin (AS-9) as a contingency outside
the base figures: 3-6 weeks, USD 95-370 plus parts and about 26-62 h. Tables 7.1, 7.2 and 7.3 and the 7.1.8 summary list
it in separate rows. Path B1 carries the same class of risk on a whole board, and Path B2 carries it twice ([PB] 3.3: 50 % chance of a
rev-2 fix, ESTIMATE).

#### 7.1.7 MB rework per path (IC-independent)

| Rework | Path A | Path A-C | Path B1 / B2 |
|---|---|---|---|
| PM1 remove the Ag105 | Yes | Yes | No (new board) |
| PM2 C-D8/C-D10 to 10 uF >= 35 V | Yes | Yes | Folded into the new board |
| PM3 R170/R171, PM6 taps, PM10 ROS removal, PM11 tap T22 on BQ29200 pin 8 | Yes | Yes (the tap field stays, §1.12.2 item 4) | Folded into the new board |
| PM4 polyimide sheet, then the CR soldered | Yes | Sheet yes; option-K socket strips soldered once; two bonded nylon feet at (23.20, 70.64) and (32.20, 70.64) (§1.4) | No |
| PM9 RSDA/RSCL 2.7 kOhm | Yes | Yes (§5.3 item 1) | Folded in |
| Chassis mounting | EVM on 6 nylon standoffs, EIB on the chassis ([WD] E) | None | None |

Paths A and A-C need the same MB rework apart from the mounting. The desolder of the Ag105 is the single irreversible step in
both.

#### 7.1.8 Summary (Mixed)

| Dimension | Path A | Path A-C | Path B1 | Path B2 |
|---|---|---|---|---|
| Effort (Table 7.1) | 417-666 h | 486-822 h | 564-1048 h | about 990-1730 h |
| Effort with one re-spin (AS-9, Table 7.1) | 431-698 h | 512-884 h | in the [PB] range | in the [PB] range |
| Parts cost (Table 7.2) | USD 505-540; fault-injection build not priced | USD 470-745 (2 boards); USD 652-927 (test plan, build 4, without the LOOP1 lot) | USD 1-2k (5 boards) | USD 2-4k |
| Re-spin contingency cash (AS-9, Table 7.2) | USD 70 plus logic parts | USD 95-370 plus parts | in the [PB] range | in the [PB] range |
| First bench charge (Table 7.3) | about 1-3 weeks | about 7-13 weeks | about 10-15 weeks | about 4-6 months ([PB]) |
| First bench charge with one re-spin (Table 7.3) | unchanged on the modified EVM | about 10-19 weeks | not separated | not separated |
| Round-3 findings removed at the root (7.2) | - | 29 of 203 | not assessed | not assessed |
| Dominant hardware risk | Hand-wired leads, ribbon and EVM changes | First-pass power layout, heat beside the LM1084, header current, retention (r2: first-pass power layout, header current, dependence on the bench fan with the FR-50 trip as the fan-off guard) | First-pass power layout on a whole board | Two new power stages |
| Board risk | Ag105 desolder | Ag105 desolder | None | None |

The Path A-C column is the path alone. The sequence that verdict condition 1 requires is in §7.1.9.

#### 7.1.9 Sequence for verdict condition 1: Path A gates, then Path A-C (Mixed)

Verdict condition 1 (§0.3) requires T-B-06, T-B-09, T-B-10, T-B-12 and T-B-21 to pass before the CCB is chosen. Only
T-B-21 runs on a stock EVM; the other four need the modified EVM, the EIB and the CR (§7.3.3). The route that the verdict
recommends therefore builds the Path A rig before the CCB. Table 7.3a gives the effort, cost and schedule of that route.
Every figure is a sum of rows of Tables 7.1-7.3 and [EVAL] 7, paired as §7.0.4 item 5 states.

| Item | Path A-C alone | Path A gates, then Path A-C | Basis |
|---|---|---|---|
| Effort | 486-822 h | 599-1032 h (15.0-25.8 engineer-weeks) | Path A-C total plus the Path A CR + EIB design 60-120 h, assembly 21-42 h and the S1 regen gates 4-6 bench days, that is 32-48 h ([EVAL] 7) |
| Effort with one re-spin (AS-9) | 512-884 h | 625-1094 h | plus 26-62 h (AS-9) |
| Parts cost | USD 470-745 (2 boards); USD 652-927 (4 boards) | USD 975-1285 (2 boards); USD 1157-1467 (4 boards) | Path A USD 505-540 in full plus the CCB build (§4.5.2) |
| Cash with one re-spin | plus USD 95-370 | USD 1070-1655 (2 boards); USD 1252-1837 (4 boards) | Table 7.2; r2 parts totals with the bench fan (§4.5.2). The r1 figures were USD 1022-1607 and USD 1200-1785 |
| First CCB bench charge | about 7-13 weeks | about 12.5-21 weeks; about 10-17 weeks if the CCB design runs during the Path A fab and assembly wait | Path A CR/EIB cycle 4.5-7 weeks (Table 7.3: design 1.5-3.0, fab 2-3, hand assembly 1), plus the S1 gates about 1 week, plus 7-13 weeks. The overlap subtracts the shorter of the CCB design (2.5-5.1 weeks) and the Path A fab and assembly wait (3-4 weeks) |
| First CCB bench charge with one re-spin | about 10-19 weeks | about 15.5-27 weeks | plus 3-6 weeks (AS-9) |

The sequence needs 113-210 h more than Path A-C alone, that is 23-26 %, and 182-366 h more than Path A. Its effort lies
inside the Path B1 band of 564-1048 h (Table 7.1). A CCB design that runs during the Path A wait is at risk. A failed gate,
or an IC change by the parallel IC search, discards it.

In Table 7.3, the Path A figure of about 1-3 weeks to the first bench charge applies to the tests on the modified EVM with
a hand carrier. T-B-06 reads the EIB input, and T-B-12 executes the real T3 through the carrier comparators ([WD] I). These
gates, and T-B-09 and T-B-10 on the T-B-12 rig, therefore follow the CR/EIB cycle of about 4.5-7 weeks.

### 7.2 Review findings ledger

#### 7.2.1 Meaning of the status (IC-independent)

Every one of the 203 finding keys of rounds 1-6 was verified real and dispositioned in the round-3 design; none was rejected
([STUDY] 3; [LOOP] closing passes). The status below therefore does not mean "open in round 3". It states whether the
finding and its applied fix still bind the CCB design:

- **CLOSED:** the root cause does not exist on the CCB (an EVM part, a lead, the ribbon, the EIB or an inter-board joint).
  The applied fix is not needed. Where a successor rule exists, the reason names it.
- **KEPT:** the finding applies to the CCB unchanged. Its round-3 fix must be carried into the CCB capture, firmware or tests.
- **CHANGED:** the finding applies in an altered form. The fix must be re-derived or re-verified for the CCB.

The generator [LEDG] takes the CB column of [STUDY] §3 as the default (Y = CLOSED, N = KEPT, P = CHANGED). This
section departs from it on 23 keys after reading sections 1-6. Each departure except `h15-3v3-load-understated` (CHANGED,
digest N) is marked "Digest CB:" in its reason. TODO(edit: add the marker to that key in [LEDG]).

#### 7.2.2 Counts (Mixed)

Table 7.5 gives the counts from [LEDG].

| Round | Keys | CLOSED | CHANGED | KEPT |
|---|---|---|---|---|
| 1 | 53 | 7 | 8 | 38 |
| 2 | 44 | 6 | 10 | 28 |
| 3 | 34 | 6 | 4 | 24 |
| 4 | 32 | 6 | 4 | 22 |
| 5 | 24 | 2 | 8 | 14 |
| 6 | 16 | 2 | 4 | 10 |
| **Total** | **203** | **29** | **38** | **136** |

By severity, the one blocker (`evm-jp14-feed-joint-floating`) is CLOSED. Of the 93 majors, 11 are CLOSED, 18 CHANGED and 64
KEPT. Of the 109 minors, 17 are CLOSED, 20 CHANGED and 72 KEPT.

The CLOSED set is the EVM-modification, ribbon, EIB and lead keys. It includes `eib-wireoff-releases-converter`,
`readback-misses-evm-side`, `w8-unfused-hot-lead`, `j101-unkeyed-ribbon-reversal`, every `evm-*` key except
`evm-input-cap-figure`, and `ribbon-adjacent-short-ilimrelb-rfcoff`. The other two `ribbon-*` keys are CHANGED: the on-board
STAT-to-CE_DRV short and the pin-6 firmware fault keep their R475 fix (§7.2.4 item 2). The KEPT set is the loop proof, the purge and pre-emption firmware, the MB and system facts, the BQ25798 behaviour
unknowns and the carried-over comparator logic. The CHANGED set is mainly layout: area, copper, the eFuse output transient,
the input-path resistance, the I2C margin and the header mechanics.

#### 7.2.3 Round 6, finding by finding (Mixed)

Table 7.6 states the status of each round-6 finding.

| # | Key | Sev. | Status | Reason | Label |
|---|---|---|---|---|---|
| 1 | `vreg-corruption-no-fixed-pack-ovp` | major | KEPT | The BQ29200 OUT -> U323 -> OVN term and ARM_OK' (U322) carry over; tap T22 and PM11 stay (§1.12.1) | I |
| 2 | `dbtsq-short-unfused-pack-on-vchg` | minor | KEPT | D-BT-SQ stays on the MB; a short still puts the pack on VCHG, now on CCB copper; FR-48 stays | I |
| 3 | `cr-and-mb-battery-path-copper-sized-below-ichg` | major (uncert.) | CHANGED | The CCB side is re-sized for 1 oz outer copper: pours >= 2.5 mm, >= 5 vias of 0.3 mm per transition (§3.1.3-3.1.5). The MB VBT part stays (T-A-06c, T-F-16) | M |
| 4 | `tc04-in-spike-criterion-omits-mb-vchgin-ratings` | major (uncert.) | KEPT | The eFuse IN side (C302a/b/c, D307) and the MB VCHG-IN end are unchanged; the three-point T-C-04 scope stays (§1.11.1) | I |
| 5 | `imon-bypass-cap-against-datasheet` | minor | KEPT | C305 stays DNP on the same eFuse network (§1.11.1) | I |
| 6 | `fcc-rgn-lvc-threshold-vs-rt1987-en-band` | major | KEPT | U319-U321 (FCC_OFF, FCC_ON, RGN_ON) carry over on the same MB EN taps (§1.12.1) | I |
| 7 | `pin38-39-adc-overvoltage-on-vmot-excursion` | minor (uncert.) | KEPT | Pins 38/39 sense the same MB nodes; FR-49 stays (§5.2) | I |
| 8 | `loop-budget-5ms-breaks-1ms-tick-deadlines` | major | KEPT | FR-45 timer domain is firmware; the CCB does not change it (§5.2) | I |
| 9 | `purge-fc-only-ridethrough-bag-evidence-reopen` | major | KEPT | Purge and rescue logic is firmware and system behaviour (§5.2) | I |
| 10 | `chg-src-misattributes-subh1-regen-reopen` | major | KEPT | The `chg_src` attribution uses the same IBAT and V_rgn data (§5.2) | M |
| 11 | `ff-headroom-admission-contradicts-single-g-test` | major | KEPT | Window admission is firmware (§5.2) | I |
| 12 | `ff-reversal-hold-unattainable-at-100khz` | minor | CHANGED | Without W7 the 100 kHz fallback is less likely; the SCL rise time on the CCB decides it, TODO(measure) (§5.3 item 1) | M |
| 13 | `cr-coordinate-convention-mirror-ambiguity` | major | CHANGED | The tab removes the CR pin-11 chamfer corner; the marker moves to (38.90, 76.40); `pin_identity_check.py` must run again (§1.8; OT-7) | I |
| 14 | `eib-e-lead-max-lengths-geometrically-infeasible` | minor | CLOSED | No E-leads (§2.3.1) | I |
| 15 | `t-a-05-stale-j101-region-dims` | minor | CLOSED | No J101 (§1.12.2 item 2) | I |
| 16 | `a6-w2-not-beside-star-pads` | minor | CHANGED | No W2; the battery return reaches pads 14/15 through the plane, in parallel with the MB GND pour, as `ground-loops-parallel-returns`; T-K-17 step (4) measures the pin currents (§1.13.2 item 2; §1.13.3) | I |

r2 note on key 4 (`tc04-in-spike-criterion-omits-mb-vchgin-ratings`). The tall-stack check found that the IN-side
transient changes on the CCB, because the 150 nH W1/W2 lead is gone (N-25; [TS] §(c)). The eFuse IN-side parts and the MB
VCHG-IN end are unchanged, but the criterion must be re-verified with the CCB values. By the rule of 7.2.1, the status of
this key is therefore CHANGED. Revision r2 proposes the change and does not apply it. Table 7.6, the counts of Table 7.5
and Appendix 7.A keep the r1 status until the next review round confirms it and [LEDG] regenerates the ledger.
TODO(edit: [LEDG], key 4 of round 6 to CHANGED). The change would move one major from KEPT to CHANGED (totals 29 / 39 /
135). No other ledger status changes in r2. The testbench facts remove no root cause of a round 1-6 finding: they act on
the CCB-specific items N-05, N-08, N-09 and N-24 and on the tests.

#### 7.2.4 Rounds 1-5 (Mixed)

The full table of all 203 keys, with the status and the reason for each, is Appendix 7.A. The items below are the rounds 1-5
keys whose status differs from the [STUDY] CB column or that carry most of the CCB design work.

1. **Re-opened by the CCB (CHANGED):** `carrier-no-buildable-layout` and its reopen (101 % area as drawn),
   `efuse-cluster-no-room-at-pad10` and its reopen, `carrier-copper-unspecified` (stack ST1/ST2 in place of 2 oz outer),
   `pm4-header-solder-sequence-ambiguous` and its reopen (option K and the feet replace the solder sequence).
2. **Fix kept for a new cause:** `open-input-failsafe` (R467-R470 now guard cracked traces), `ribbon-4-5-stat-sink-abs-max`
   (R475 now guards a pin-6 firmware fault and an on-board STAT-to-CE_DRV or STAT-to-3V3 short; it holds the STAT sink to
   3.06-3.30 mA against the 6 mA abs max, and 41 mA flows without it), `eib-pin8-backpower-unpowered-outputs` (R474 on the
   merged rail). All three keys are CHANGED.
3. **Re-derivation needed (CHANGED):** `input-path-ir-drop-omitted`, `ilim-band-leakage-omitted`, `efuse-out-schottky-missing`
   and its reopen, `tc04-out-spike-criterion-unattainable`, `run-quiescent-draw-unaccounted` and its reopen,
   `h15-3v3-load-understated`, `u203-threshold-ignores-sense-offset`. All draw on one re-run of `r3_calc.py` and `sch_calc.py`
   with the CCB values (O-11; §6.7 item 4).
4. **Digest P judged KEPT:** `cr-3v3-single-tap-backpower`, `tb03-ce-pass-criterion`, `ilim-sense-threshold-above-hiz-vil`,
   `u203-stuck-held-latent-no-entry-test`, `imon-vchg-ground-offset-under-charge-current`. The parts or paths these keys
   protect are unchanged on the CCB.
5. **Digest Y judged CHANGED:** `eib-e6-e7-ce-stat-bridge` (an adjacent-trace short replaces the lead bridge, §5.3 FR-22),
   `t-a-04-criterion-not-datasheet` (the CCB's own capacitors), `bom-26awg-wire-quantity` (taps only),
   `ribbon-4-5-stat-sink-abs-max` and `ribbon-adjacent-short-stat-cedrv` (item 2), `tlv3012-ribbon-driver-short-current`
   (the tap wires F13/F20 replace the ribbon as the off-board conductor; R325/R348 limit a short to 3.18-3.30 mA),
   `ground-loops-parallel-returns` and `a6-w2-not-beside-star-pads` (the CCB plane joins pads 4 and 14/15 in parallel with
   the MB GND pour, §1.13.3).

#### 7.2.5 Review-process items that stay open (IC-independent)

1. The round-3 loop did not converge (53, 44, 34, 32, 24, 16 findings) and the final independent audit was not run
   ([EVAL] 0.1a). This is KEPT for every part of the CCB that carries round-3 content.
2. Review run 001 found 22 verified findings in sections 0-9 (8 major, 12 minor, 2 nit; no blocker), and revision r1
   applies them (§0.9). One round does not show convergence: the round-3 history found 16 verified findings in its sixth
   round. A further review round on revision r1 is therefore required before any order. Revision r2 (§0.9) applies the
   testbench facts of the operator statement, 2026-11-10, and is not reviewed; the further round applies to r2. The number of rounds it needs is
   not predictable from the sources.
3. Of the pre-round-1 self-review passes, P2-1 (LVC edge rate behind EIB RC filters), P3-1 (designator collisions with the EVM)
   and P3-6 (EVM JP7 on micro-USB) are CLOSED by the CCB. The other passes are KEPT ([STUDY] 3.2).

#### 7.2.6 New findings and risks opened by the CCB (Mixed)

Table 7.7 lists the findings that the CCB opens. The severity is this section's proposal; it is not a verified review
result. Each row names the test or open item that decides it.

| ID | Finding | Proposed severity | Decided by | Label |
|---|---|---|---|---|
| N-01 | First-pass 4-layer power-cell layout. TI publishes no EVM layout files; the cell follows the TIDA-050047 Gerbers (§3.4.7) but moves the inductor to L1 and uses larger PMID parts (§3.4.8); Fig 8-21 labels inconsistent in rev C | major | T-K-06, T-K-07; 7.1.6 | S |
| N-02 | Loss of TI's validated EVM: the SLUSDV2C efficiency and thermal behaviour apply to the CCB only as far as its layout matches; the loss above VBUS 20 V is unmeasured | major | L-8; T-K-14 | S |
| N-03 | Hand or PCBA assembly of the RQM package: hidden joints at 0.4 mm pitch carry 3.21 A; X-ray availability unknown; a bridge between adjacent pins can overstress ILIM_HIZ (7.38-8.38 V against 6 V) or the bootstrap pins (Table 2.6b) | major | §2.3.2, §4.4.3, B-7; T-K-06 step (1) gate in both assembly options | S |
| N-04 | Area: 1532 mm² against 1514 mm² usable (101 %; 103 % with the battery-path corridor reserved); the remedies need 0402 logic passives, rect A' (H_u >= 2.75 mm) or the deletion of DNP options. In addition, the power-cell sketch overlaps the header keep-out and Z-E when rotated into place. The route of the 3.5 A VCHG path to pins 18/19 past L501 is not chosen; Table 3.5 books its area only. The DNP filter footprints C336, C337 and C453 add 13 mm² (about 6 mm² as 0402), which [LC] §6 does not book. With them, the utilisation is 102 % as drawn and 104 % with the corridor (§3.2.3). The 10 mm separation class does not fit the top side (§3.6.1) | major | L-1, L-11, L-12, L-13; capture DRC | M |
| N-05 | Thermal coupling (r1 record, superseded in r2 by the bench fan): about 2.7 W at 13.4 mm from the LM1084 courtyard; T_J about T_MB,0 + 71-86 C (option S, no gap pad), including 11-19 C of MB self-heating; the 100 C target fails above T_MB,0 of about 14-29 C without the gap pad and 28-45 C with it (option S); option K needs the compressed gap pad (16-35 C at h_k 3.0 mm, k 3) and h_k <= 5.0 mm. r2: with forced air over the top and through the 5-8 mm gap, T_J - T_air is 49-61 C at 2.7 W (g 5 mm, 2 m/s), that is 74-86 C at 2.7 W and 78-90 C at 2.9 W on a 25 C bench, without a gap pad; T_MB,0 is record only ([LC] §8.6; §3.7.3a). The fan-off case is N-26 | major | r2: T-K-20 with T-K-14; FR-50; §3.7.3a (r1: T-K-02 with the heater step, T-K-14; §3.7.3) | M |
| N-06 | The LM1084 ambient rises because of the CCB; its junction margin is unmeasured. r2: the fan air flows along +y and leaves away from the LM1084 (§1.2.3); a fan powered from the LM1084 rail would add 0.12-0.68 W and +5 to +27 C to its junction, so the fan has its own supply ([LC] §8.10) | major (uncert.) | T-K-02 (r2: record only), T-K-14; OT-4 | I |
| N-07 | Header and socket current: one VIN+ pin and one input-return pin at <= 2.41 A; pins 18/19 at 1.93 A / 1.28 A on a 60/40 split; pin and socket ratings unverified; the round-3 pin-18 joint rise limit < 20 C fails without a gap pad (T_MB,local + 20-26 C, option S), so the modified T-F-16 uses an absolute joint limit. r2: the tall pins add 0.66-1.47 mOhm and up to 5.5 mW per pin at H_u 5-8 mm ([TS] §(a)); the pin-18 joint with forced air is TODO(calc) | major | O-10; §3.7.6; T-A-05, T-K-17, T-F-16 | I |
| N-08 | Retention (r1 title: on a moving vehicle; r2: the road and vibration part is not applicable on the testbench, operator statement, 2026-11-10; socket fretting from repeated insertion and the FR-51 items stay): no vibration specification; socket fretting; FR-51 detects an open battery path but does not prevent it; FR-51 is blind for a pack OCV within `CHG_VBAT_OPEN_V` of VREG (FR-51 item 6) | major (r2: minor, proposed) | T-K-17 to T-K-19 (r2: T-K-17, T-K-18 step (8); T-K-19 not applicable); FR-51 | I |
| N-09 | Overhang support: two nylon feet bonded to solder mask; adhesive shear strength and the solder-mask-to-copper adhesion unverified; foot-screw torque T_s unset and no threadlocker permitted (§1.7.2 rule 2); torsion, refit-cycle and gap-pad load cases added to T-K-18; option D needs a new MB hole and operator approval. r2: the feet are tall spacers of length H_u (5.1-8.1 mm); a lateral force gives a bond moment 2.0-3.2 times the r1 value, and a 10 N tab-edge pull puts 18.6-22.1 N on the two feet ([TS] §(e)); the gap-pad load case is gone; handling replaces vibration | minor | T-K-18 (r2: with step (8)), T-K-19 (r2: not applicable); §1.4 | I |
| N-10 | Switching noise on the shared plane at high-impedance comparator nodes (6.49-10 MOhm, and the unfiltered 312 kOhm N_FNP / N_RNP and 506 kOhm N_CSP with DNP filters C336, C337 and C453), the heartbeat monostable and the QUAL one-shot; the 10 mm rule is unsourced, and only 32.7 mm² of top-side Z-Q meets it (§3.6.1) | major | T-K-09, T-K-10; L-9, L-13; T-A-06 | M |
| N-11 | Charger control pins (ILIM_HIZ, /CE, TS) beside the switch nodes: a coupled glitch could release the converter | major | T-K-10 | S |
| N-12 | Switch-node coupling into MB nets under the CCB (MPPT-DISABLE pin 5 at y 64.48, CB-DISABLE pin 9) and into the OP-FC droop chain | major | T-K-13; L4 shield rule (§3.1.1) | M |
| N-13 | Conducted charger ripple enters the MB at pad 10 without the damping of the W1/W2 lead inductance; input snubber is DNP | minor | T-K-12 | M |
| N-14 | Inductor stray field: the L-FC courtyard is 0.55 mm beyond the rect-A edge (y 76.40), and L501 is 18.4 mm from that edge (y 51.5-58.0); a shielded L501 is required, TODO(verify: TDK drawing) | minor | §1.6.1; T-K-13 | S |
| N-15 | Inductor peak 5.51 A at the worst corner against the SLUSDV2C ISW 5 A figure; Isat basis of SPM6530T unverified; the cycle-by-cycle limit that bounds a fault transient is unpublished, so L501 is restricted to SPM6530T-1R0M120 (§2.1.3) | major (uncert.) | O-2, O-4; T-K-08 | S |
| N-16 | 50 V X7R 1210 input capacitors: MPN and DC-bias curve at 23.6 V open | minor | O-1; T-A-04 | S |
| N-17 | ACFET pair omitted: an eFuse FET short together with a V-MOT excursion above 30 V reaches U501 VBUS (double fault) | minor | O-3 | M |
| N-18 | SDRV: rev C deleted the SDRV-to-BAT option that round-3 EM13 used; the CCB uses 1 nF to GND. This also affects Path A | minor | O-14 | S |
| N-19 | Fab capability: 0.1/0.1 mm trace and space, 0.254 mm via lands at 0.12-0.15 mm from a pad, 0.1 mm mask dam, 2 oz inner copper unverified | minor | L-2; T-K-03 | M |
| N-20 | Common board for power and interlock: a power-stage thermal or short event can damage the interlock on the same board. The logic fails safe when unpowered, but a partial failure is not analysed | minor (uncert.) | TODO(analysis: F.3 single-fault table extended to board-level events) | I |
| N-21 | Re-spin coupling: a power-stage error forces a re-fab of the interlock logic too; Path A could re-spin the CR alone | minor | 7.1.6 | I |
| N-22 | Test infrastructure: FIX1, FI1, LOOP1 (a layout variant) and a >= 500 MHz scope probe set | minor | §6.1.4, OT-2 | M |
| N-23 | Conformal coating over copper above 100 C; MB probe points under the CCB lost while it is fitted | minor | §3.8 item 5, 3.9.3 | I |
| N-24 | Envelope and reversibility: H_env above rect A unmeasured; the Ag105 plug-back depends on the socket's accepted pin range. r2: the envelope part is not applicable (no height restriction, operator statement, 2026-11-10); the reversibility part stays, now with an elevated socket of h_k 2.6-5.6 mm (§1.3.4) | minor | T-K-01 (r2: record only), T-K-04; §1.3.3 | I |
| N-25 | r2: the IN-side transient is not unchanged on the CCB (§1.11.2 item 4 of r1 is incorrect). Without the 150 nH W1/W2 lead, 5-20 nH of OUT copper raises the ideal hard-short turn-off current from 65 A to 103-117 A and the ideal U301 IN peak from 32.8 V to 35.5-40.0 V; at 10-20 nH it exceeds the D307 VBR minimum of 36.7 V, so D307 conducts. The margins to the 60 V T-C-04 criterion and the 67 V U301 maximum stay; the MB end stays at about 20 V. The tall stack adds 0-0.3 V. D307 energy and the OUT copper inductance are TODO(calc); the real TPS26630 hot-short current is TODO(verify: SLVSE94G) ([TS] §(c)) | minor (uncert.) | T-C-04 records (a)-(b); T-A-05 (D307 energy); §6.7 item 5 | I |
| N-26 | r2: the thermal design depends on the bench fan. With the fan off at g 5 mm on a 25 C bench, T_J is 104-142 C at 2.7 W and 86-116 C at the 2.08 W derate image, so the FR-50 trip, not the derate, must act before TREG (120 C) and TSHUT (150 C) ([LC] §8.7; [DS] §6.5). The fan MPN, airflow curve, duct capture (30-50 % assumed) and the real gap velocity are unknown; the fan must not load the LM1084 / CO-5V rail; the fan-motor noise at the MB analog nets is TODO(measure) | major | T-K-20, M15, M16; T-K-15; FR-50; §1.6.3; T-K-12 and T-K-13 fan-on / fan-off (§6.4.4) | M |
| N-27 | r2: the tall header stack. Header, socket and spacer classes for H_u 5.1-8.1 mm have no verified MPN, seat height or withdrawal force; the CCB-to-MB ground shift at a hard-short turn-off rises to 0.08-1.34 V (three pins) at H_u 5-8 mm ([TS] §(d)); a taller cantilever flexes when cables are plugged or the board is probed | minor | T-C-04 record (c); T-K-11 step (5); T-K-17; T-K-18 step (8); O-10, B-8 | I |

Note that N-11 also exists in part on Path A. Path A has the same control pins, but on the EVM, 0.3 m from the comparators,
inside TI's layout.

### 7.3 Recommendation

#### 7.3.1 Trade-off (Mixed)

Path A-C removes the root cause of 29 of the 203 round-3 findings, including the one blocker and 11 majors. It deletes the 17
physical EVM modifications, the 0.3 m leads, the ribbon and the EIB. It gives a compact installation that plugs into the MB
and can be withdrawn without heat on the MB.

However, Path A-C keeps 136 findings and changes 38, and it opens about 27 new items (N-01 to N-27; r2 adds N-25 to
N-27). It replaces a TI-built power stage with a
first-pass layout of a 0.4 mm-pitch package at 101 % area use as drawn. It dissipates about 2.7 W at 13.4 mm (power cell edge) from the courtyard of the hot
LM1084. In r2 a bench fan cools it over the top and through the 5-8 mm gap (§1.6.3), so the design depends on the fan,
and the FR-50 trip is the fan-off guard (N-26). It carries 3.21 A through tall header pins of unverified rating. The
testbench does not move, so road vibration does not apply (operator statement, 2026-11-10). It costs about 70-155 h more effort than Path A and delays the first bench charge from about 1-3 weeks to about
7-13 weeks. One re-spin (AS-9) adds about 26-62 h and 3-6 weeks to these figures. On the recorded allowances, two boards cost
USD 470-745 against USD 505-540 for Path A. The four boards that the test plan needs cost USD 652-927, which is USD 112-422
above Path A before the LOOP1 lot is priced (§7.1.3). Cost therefore does not favour Path A-C. The route through verdict
condition 1 adds the Path A rig before the CCB. That route needs about 599-1032 h and USD 1157-1467 with four CCBs, and the
first CCB bench charge comes after about 12.5-21 weeks (§7.1.9). None of the three paths is shown to be feasible: the round-3 design is feasible on paper only and was not audited
([EVAL] 0.1a).

#### 7.3.2 Conditions for each path (Mixed)

Table 7.8 states when each path is preferred. The conditions are the measurable outcomes that would move the choice.

| Path | Preferred when | Label |
|---|---|---|
| Path A | The BQ25798 behaviour gates are still open (warm response T-B-09/T-B-10, inhibit latency T-B-06, VINDPM reload T-B-12, EN_EXTILIM T-B-21; [WD] 0.2); the parallel IC search may still change the IC; or the earliest charger data is the priority | M |
| Path A-C | The IC is fixed by bench evidence; r2: the seated gap g is 5 mm or more, preferably 5-8 mm (T-K-04, M3), and T-K-20 shows TDIE <= 100 C at 2.9 W with the fan on and an FR-50 trip before TREG_STAT with the fan off (verdict conditions 2 and 3, §0.3); a PCBA service with U501 inspection is available (verdict condition 4); and the T-G drive cycles must run on the testbench with a durable installation in place of chassis-mounted leads. r1 record, superseded by the testbench facts (operator statement, 2026-11-10): T-K-01 shows the envelope (planned stack 7.14 mm for option S or 7.14 + h_k mm for option K, plus 1 mm margin; h_k <= 5.0 mm); T-K-02 shows T_MB,0 at or below the admissible value of §3.7.3 with the measured R_MB (option K at h_k 3.0 mm with a compressed k 3 gap pad: 16-35 C on the modelled R_MB); and the vehicle must run the road and drive-cycle tests (T-G group) with a durable installation in place of chassis-mounted leads | M |
| Path B1 | A re-spin is needed anyway (the S0 board-health check fails, an [EVAL] 6.4 re-spin trigger fires, or the bodge list is to be folded in); or T-K-02, T-K-17 or T-K-19 fail, since B1 places the charger by design and carries the battery current in copper. r2: or T-K-20 or T-K-17 fail; T-K-02 is record only and T-K-19 is not applicable (testbench) | I |
| Path B2 | Full regen capture by construction becomes the research goal, at about 5-9 months ([PB] 3.3) | I |

#### 7.3.3 Sequencing option (Mixed)

One sequence that this comparison supports is a hybrid. Buy one stock BQ25798EVM (USD 156.45) and run the IC-behaviour subset
of §6.5.3 on it while the CCB is designed and fabricated. A disqualifying IC result then arrives before the fab cost,
and the parallel IC search gets bench data. However, this adds the EVM cost, and the results that depend on the ILIM_HIZ or
/CE network must be repeated on the CCB. This is a scheduling choice for the operator.

The hybrid does not replace the Path A rig for verdict condition 1. Of the five gates of that condition, only T-B-21 runs on
a stock EVM (§6.5.3). T-B-06 scopes the EIB input and the /CE and ILIM_HIZ networks that EM2, EM4 and EM5 alter. T-B-12
executes the real T3 through the carrier comparators and the firmware, with two RT-SI stand-ins and the 0.19 ohm R_path
resistor. T-B-09 and T-B-10 run on the T-B-12 rig ([WD] I rows T-B-06, T-B-09, T-B-10, T-B-12). Condition 1 therefore needs
the modified EVM, the EIB and the CR, as §7.1.9 books.

### 7.4 Separation for an alternative charger IC (Mixed)

Table 7.9 marks which parts of this comparison change if the parallel IC search substitutes another IC.

| Item | Label | Effect of another IC |
|---|---|---|
| MB rework (7.1.7), header, feet, outline, retention, tap field | I | Unchanged if the IC fits the same outline |
| Interlock design hours (AS-7 share) and the T-K mechanical tests (T-K-01 to T-K-04, T-K-17 to T-K-19) | I | Unchanged (r2: T-K-19 not applicable on the testbench) |
| Bench fan, tall header stack and the T-K-20 soak method (r2), N-25 to N-27 | I / M | Method unchanged; the loss figures and the TDIE and TREG thresholds change with the IC |
| Power-cell hours, first-pass layout risk (7.1.6), N-01 to N-03, N-11, N-14 to N-16, N-18 | S | Re-assessed for the new package and power stage; a package with an exposed pad or a larger pitch may make hand assembly viable (§4.7) |
| Thermal rows (N-05, N-06; r2: N-26) | M | Method unchanged; the loss figures change |
| Ledger KEPT keys with tag e (25 tag occurrences, [STUDY] 3) | S | Replaced by the new IC's behaviour unknowns |
| Firmware hours | M | The IC-independent FRs stay; the register map, G.1 image and FR-50/FR-51 detection change (§5.9) |

### 7.A Appendix: all 203 finding keys (Mixed)

The table is generated by [LEDG] from [STUDY] 3. Severity and tag are as recorded in [LOOP] and [STUDY]. Tags: (a) off-board
EVM leads, (b) EIB and ribbon, (c) EVM modifications, (d) carrier logic, d-mech carrier mechanics, (e) BQ25798 behaviour,
(f) firmware, (g) MB or system, doc documentation.

| Rnd | # | Key | Severity | Tag | Path A-C status | Reason (source) |
|---|---|---|---|---|---|---|
| 1 | 1 | `preempt-fcc-btb-overlap` | major | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 1 | 2 | `eib-wireoff-releases-converter` | major | b,c | **CLOSED** | No lead can lift; the two-switch release Q403 + Q401 is kept, and a cracked on-board trace reads LOW through R467-R470 (§2.3.1, §2.3.2) |
| 1 | 3 | `qual-window-single-barrier` | major | d,e | **KEPT** | The QUAL one-shot carries over as U311 (BQ25798-specific) (§1.12.1) |
| 1 | 4 | `p5-static-arm-hang` | major | d,f | **KEPT** | Heartbeat monostable U313 and ARM_OK carry over (§1.12.1); T-K-09 step 3 re-proves them with the converter switching |
| 1 | 5 | `permit-tap-failsafe-and-en-threshold` | minor | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 1 | 6 | `comparator-divider-open-faults` | minor | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 1 | 7 | `uvb-blocks-raised-regen` | minor | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values (§1.12.1) |
| 1 | 8 | `btok-sense-wire-open` | minor | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 1 | 9 | `regen-capability-ichg-bound` | major | e | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image (§5.5.1) |
| 1 | 10 | `btbus-reclose-inrush-unquantified` | major (uncert.) | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 1 | 11 | `efuse-out-schottky-missing` | major | a,d | **CHANGED** | D303 loses its main case (far-end short on 0.3 m leads) but stays fitted; fit or DNP and its leakage beside the LM1084 are open (§1.11.2 item 2, O-12) |
| 1 | 12 | `ocfc-margin-traction-transient-fc-window` | major (uncert.) | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 1 | 13 | `ilim-band-leakage-omitted` | minor | e,c | **CHANGED** | R523 49.9 kOhm stays as a BOM choice; the H.4 band is re-derived with on-board leakage (O-11) |
| 1 | 14 | `evm-c43-25v-vbus-ldo` | minor | c | **CLOSED** | There is no EVM; the modified part has no CCB footprint (§2.4.2) |
| 1 | 15 | `btok-kelvin-wrong-reference` | minor (uncert.) | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 1 | 16 | `run-quiescent-draw-unaccounted` | minor | e,d | **CHANGED** | The 55-78 mW Run budget is re-booked for the merged rail and the deleted series parts (TODO(calc), T-K-05) |
| 1 | 17 | `efuse-ovp-above-bq-rating` | minor | d,e | **KEPT** | eFuse OVP 22.61-23.63 V stays and is now the only input OV device in front of U501, since the ACFET pair is omitted (§2.1.1 D2) |
| 1 | 18 | `carrier-copper-unspecified` | minor | d-mech | **CHANGED** | Stack moves from 2 oz outer to 1 oz outer (ST1) or 2 oz inner (ST2), because the RQM land pattern has 0.2 mm gaps; current capacity moves to width (§3.1.3). Digest CB: N |
| 1 | 19 | `btb-sense-threshold-gap` | major | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 1 | 20 | `open-input-failsafe` | major | b,d | **CHANGED** | No removable conductor inside the charger chain; R467-R470 stay for cracked traces and joints from handling, repeated insertion and thermal cycling on the testbench (r1: a moving vehicle; §2.3.1). Tap inputs keep their biases |
| 1 | 21 | `readback-misses-evm-side` | major | b | **CLOSED** | U403/U404 sense the U501 ILIM_HIZ and /CE pins on their own traces (§2.3.1; §3.6.2 item 2) |
| 1 | 22 | `raise-latency-i2c-budget` | major | a,f | **CHANGED** | FR-07 caps stay; the on-board bus (no W7) can only add margin (§5.2 FR-07, 5.3 item 1) |
| 1 | 23 | `latent-comparator-faults` | minor | d,f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 1 | 24 | `uvb-ref-drift-margin` | minor (uncert.) | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values (§1.12.1) |
| 1 | 25 | `imon-clamp-leakage` | minor (uncert.) | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values (§1.12.1) |
| 1 | 26 | `btok-kelvin-reference` | minor (uncert.) | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 1 | 27 | `efuse-flt-unpowered-state` | minor (uncert.) | d,f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 1 | 28 | `tb03-ce-pass-criterion` | minor | c,e | **KEPT** | R472/R472b 47.0 kOhm and the /CE >= 3.0 V criterion are unchanged (§2.3.1; T-K-10). Digest CB: P |
| 1 | 29 | `stale-designators-in-fixes` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 1 | 30 | `pin34-wdog1b-pad` | minor | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 1 | 31 | `preempt-switch-conflict-latch` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 1 | 32 | `preempt-bt-trcb-conduction` | major (uncert.) | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 1 | 33 | `early-purge-refusal-band` | major | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 1 | 34 | `restore-threshold-vindpm-band` | major | e,f | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image (§5.5.1) |
| 1 | 35 | `regen-capability-ignores-ichg` | major (uncert.) | e | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image (§5.5.1) |
| 1 | 36 | `fr08-uvb-unobservable` | major | d,f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 1 | 37 | `raise-vindpm-unload-transient` | major (uncert.) | e | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image (§5.5.1) |
| 1 | 38 | `purge-interval-load-dependence` | minor (uncert.) | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 1 | 39 | `fc-window-por-latches-fc-clamp` | minor (uncert.) | e | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image (§5.5.1) |
| 1 | 40 | `t3-latency-blocking-i2c` | minor | a,f | **CHANGED** | As raise-latency-i2c-budget |
| 1 | 41 | `t2-bt-bus-ownership` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 1 | 42 | `telemetry-ems-gaps` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 1 | 43 | `carrier-no-buildable-layout` | major | d-mech,doc | **CHANGED** | Re-opened: the CCB books 1532 mm2 against 1514 mm2 usable (101 %); the remedies reach 78-86 % (§3.2.3). Digest CB: N |
| 1 | 44 | `eib-mounting-and-tp-placement` | major | b | **CLOSED** | The EIB, the W5 ribbon and the E-leads do not exist; the stages sit on the CCB (§2.3.1) |
| 1 | 45 | `stale-designators-collide-with-evm` | major | c,doc | **CLOSED** | There is no EVM; the modified part has no CCB footprint (§2.4.2) |
| 1 | 46 | `evm-c43-25v-on-input` | major | c | **CLOSED** | There is no EVM; the modified part has no CCB footprint (§2.4.2) |
| 1 | 47 | `bom-mpns-incomplete` | major | doc | **KEPT** | Re-opened on the CCB BOM: C511/C512/C529-C531, socket strips, adhesive and the snubber have candidate or no MPNs (§4.3.3) |
| 1 | 48 | `rb2-designator-collides-with-mb` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 1 | 49 | `duplicate-em-ids` | minor | c,doc | **CLOSED** | There is no EVM; the modified part has no CCB footprint (§2.4.2) |
| 1 | 50 | `tap-twisted-gnd-unterminated` | minor | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 1 | 51 | `registry-missing-pass-fail` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 1 | 52 | `t1-t2-unprotected-power-taps` | minor | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 1 | 53 | `doc-svg-number-mismatches` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 2 | 1 | `evm-jp14-feed-joint-floating` | blocker | c | **CLOSED** | No R21, JP13 or JP14 footprint; rule 4.2.1 allows only Q403 + R455 between REGN and ILIM_HIZ (§2.4.2 EM3) |
| 2 | 2 | `reg14-write-reopens-extilim` | major | e,f | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image (§5.5.1) |
| 2 | 3 | `efuse-out-schottky-missing-reopen` | major | a,d | **CHANGED** | As efuse-out-schottky-missing; T-C-04 runs again on the CCB (O-12) |
| 2 | 4 | `w8-unfused-hot-lead` | major | a | **CLOSED** | The 0.3 m EVM leads W1-W8 do not exist on the CCB (§1.12.2 item 3) |
| 2 | 5 | `fr08-hb-latency-false-trip` | major | d,f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 2 | 6 | `eib-pin8-backpower-unpowered-outputs` | major | b,g | **CHANGED** | No separate EIB rail; the BAV199 back-feed into the merged rail remains and R474 holds it at 0.3-0.45 V (§2.3.1) |
| 2 | 7 | `cr-3v3-single-tap-backpower` | major | b,c,g | **KEPT** | The CCB rail is still fed from one tap T6 through R375; I2C still runs on the MB pull-ups RSDA/RSCL 2.7 kOhm (PM9), R345/R346 DNP (§2.4.2 EM6). Digest CB: P |
| 2 | 8 | `pin8-encoder-net-occupancy` | major | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 2 | 9 | `pin8-tap-on-encoder-net` | major | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 2 | 10 | `preempt-drops-subh1-regen` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 2 | 11 | `preempt-p5-low-drops-brake-absorption` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 2 | 12 | `rescue-predicate-checked-before-tdon` | major | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 2 | 13 | `setpoint-hold-conduction-deadlock` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 2 | 14 | `t2-btbus-open-without-fc-conduction` | major | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 2 | 15 | `warm-response-pass-criteria-inconsistent` | major | e,doc | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image (§5.5.1) |
| 2 | 16 | `telemetry-ems-gaps-reopen` | major | e,f | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image (§5.5.1) |
| 2 | 17 | `window-reopen-rule-limits-fc-duty` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 2 | 18 | `chg-header-strips-10-12` | major | d-mech | **KEPT** | The CCB uses the same 1x10 + 1x12 strips; option K adds matching socket strips (§1.3.4) |
| 2 | 19 | `carrier-no-buildable-layout-reopen` | major | d-mech | **CHANGED** | As carrier-no-buildable-layout; the courtyard DRC of the capture is the gate (L-1) |
| 2 | 20 | `bom-resistor-mpns-out-of-range` | major | doc,d | **KEPT** | Carrier logic; it carries over with unchanged topology and values (§1.12.1) |
| 2 | 21 | `evm-tp42-is-scl` | major | c | **CLOSED** | There is no EVM; the modified part has no CCB footprint (§2.4.2) |
| 2 | 22 | `tc04-out-spike-criterion-unattainable` | major | a,d | **CHANGED** | The OUT loop inductance falls to the copper value; the T-C-04 OUT criterion is re-derived for the CCB (§1.11.2 item 2) |
| 2 | 23 | `btb-pullup-backdrives-en` | minor | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 2 | 24 | `h2c-h1-term-not-rgn-qualified` | minor | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values (§1.12.1) |
| 2 | 25 | `qual-clr-edge-bypasses-gate` | minor | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values (§1.12.1) |
| 2 | 26 | `ground-loops-parallel-returns` | minor | a,b | **CHANGED** | The lead and ribbon returns are gone, but the CCB plane joins pads 4 and 14/15 in parallel with the MB GND pour, and the split depends on the MB copper (§1.13.1; §1.13.2 item 5; §1.13.3). T-F-11 is re-scoped to the one-plane partition; T-K-17 measures the pin 4/14/15 currents. Tap shields stay bonded at the board end. Digest CB: Y |
| 2 | 27 | `evm-agnd-parallel-return` | minor | a,b,c | **CLOSED** | The 0.3 m EVM leads W1-W8 do not exist on the CCB (§1.12.2 item 3) |
| 2 | 28 | `run-quiescent-draw-unaccounted-reopen` | minor | e,b,d | **CHANGED** | As run-quiescent-draw-unaccounted |
| 2 | 29 | `evm-power-shunts-unsourced` | minor | c | **CLOSED** | There is no EVM; the modified part has no CCB footprint (§2.4.2) |
| 2 | 30 | `ina253-adc-offset-from-charger-return` | minor | a,g | **CHANGED** | The return moves from W2 to pads 4/14/15; the MB-GND drop that shifts the ADC remains (T-F-04c, T-F-15) |
| 2 | 31 | `t-a-04-criterion-not-datasheet` | minor | c,doc | **CHANGED** | T-A-04 now checks the CCB's own 50 V X7R parts against the SLUSDV2C effective-capacitance minima at 23.6 V (O-1; B-4). Digest CB: Y |
| 2 | 32 | `ilim-sense-threshold-above-hiz-vil` | minor | b | **KEPT** | U403 keeps the 0.587-0.650 V threshold below VIL_ILIM_HIZ 0.75 V (§2.3.1). Digest CB: P |
| 2 | 33 | `lvc-slow-edges-reset` | minor | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values (§1.12.1) |
| 2 | 34 | `i2c-bus-recovery-missing` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 2 | 35 | `csv-h2-text-omits-fciok` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 2 | 36 | `csv-row16-omits-fciok` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 2 | 37 | `early-purge-trigger-misattribution` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 2 | 38 | `fc-window-budget-vs-h20-pmax` | minor | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 2 | 39 | `todo-outside-registry` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 2 | 40 | `evm-input-cap-figure` | minor | c,e | **CHANGED** | The VCHGOUT ceramic total is the CCB's own, 51.3 uF nominal; the no-electrolytic rule stays (§2.4.2 EM24) |
| 2 | 41 | `w7-gnd-termination` | minor | a | **CLOSED** | The 0.3 m EVM leads W1-W8 do not exist on the CCB (§1.12.2 item 3) |
| 2 | 42 | `p5-name-collision` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 2 | 43 | `svg-netlist-designator-gaps` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 2 | 44 | `h15-3v3-load-understated` | minor | d | **CHANGED** | The 1.82 mA EIB share and the CR load merge onto R375; the logic quiescent budget is re-computed (T-K-05 TODO(calc)) |
| 3 | 1 | `t1-ce-check-before-regn` | major | e,f | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image (§5.5.1) |
| 3 | 2 | `fr08-powered-predicate-ignores-regn` | major | e,f | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image (§5.5.1) |
| 3 | 3 | `ce-sense-gating-before-regn` | major | e,b | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image (§5.5.1) |
| 3 | 4 | `ce-pullup-link-sense-divider-fails-low` | major | c,b | **CHANGED** | Links L1/L2 disappear; R472/R472b keep separate pads and vias (§2 rule 4.2.3; §3.6.2 item 3) |
| 3 | 5 | `heartbeat-proves-loop-not-monitor` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 3 | 6 | `btb-off-stuck-high-undetectable` | minor | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values (§1.12.1) |
| 3 | 7 | `u203-stuck-held-latent-no-entry-test` | minor | b | **KEPT** | U403 is kept, so its stuck-held latent fault and the T1 step-6 pin-33 proof remain (§2.3.1). Digest CB: P |
| 3 | 8 | `early-purge-sag-asserts-h1` | minor (uncert.) | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 3 | 9 | `t3-t4-fcceil-race` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 3 | 10 | `ina253-bt-common-cause` | minor | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 3 | 11 | `efuse-in-spike-c102-undersized` | major | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 3 | 12 | `cr-bottom-over-mb-power-traces` | major | d-mech,g | **KEPT** | Flush tails, no underside parts over MB power copper + 1 mm, polyimide sheet; L4 must now also shield the switch nodes (§1.3.5, 1.5; §3.1.1) |
| 3 | 13 | `input-path-ir-drop-omitted` | major | a,c | **CHANGED** | R_PATH_RG loses W1/W2, EVM R2 and JP3; the CCB value is TODO(calc: H.19); tests keep 0.19 ohm as a bound (§1.11.2 item 3; §6 G4) |
| 3 | 14 | `mb-vchgin-vias-current-rating` | minor (uncert.) | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 3 | 15 | `t18-5v-tap-unprotected` | minor | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 3 | 16 | `btok-selftest-floor-overlap` | major | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 3 | 17 | `u203-threshold-ignores-sense-offset` | minor | b | **CHANGED** | U403 threshold re-derived for the CCB divider values (§5.4 row 33) |
| 3 | 18 | `csv-pin20-reservation-missing` | minor | doc,f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 3 | 19 | `early-purge-fc-ridethrough-infeasible` | major | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 3 | 20 | `window-ignores-ems-intent-and-termination` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 3 | 21 | `scheduler-unlock-on-load-starves-windows` | major (uncert.) | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 3 | 22 | `h1-asserts-on-bus-sag` | minor | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values (§1.12.1) |
| 3 | 23 | `cr-power-pad-coords-on-pin-column` | major | a,d-mech | **CLOSED** | The W1/W2 power-lead pads are deleted; pad 10 and pins 18/19 connect by copper (§1.12.2 item 3; §3.3.3). Digest CB: P |
| 3 | 24 | `evm-jp13-regn-pin-stray-shunt` | major | c | **CLOSED** | There is no EVM; the modified part has no CCB footprint (§2.4.2) |
| 3 | 25 | `j101-unkeyed-ribbon-reversal` | major | b | **CLOSED** | The EIB, the W5 ribbon and the E-leads do not exist; the stages sit on the CCB (§2.3.1) |
| 3 | 26 | `tps26630-pwp-alternate-nonexistent` | minor | d | **KEPT** | Resolved in round 3; the CCB uses the same TPS26630RGER (§4.2) |
| 3 | 27 | `todo-outside-registry-reopen` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 3 | 28 | `fr08b-label-collision` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 3 | 29 | `bav199-clamps-backfeed-cr-rail` | minor | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values (§1.12.1) |
| 3 | 30 | `r256-c252-agnd-landing-unspecified` | minor | c,b | **CLOSED** | There is no EVM; the modified part has no CCB footprint (§2.4.2) |
| 3 | 31 | `evm-j3-j4-live-terminals` | minor | c | **CLOSED** | There is no EVM; the modified part has no CCB footprint (§2.4.2) |
| 3 | 32 | `d103-fallback-contradicts-criteria` | minor | d | **CHANGED** | D303 criteria stay; whether D303 is fitted at all is re-opened (O-12). Digest CB: N |
| 3 | 33 | `eib-layout-unbudgeted` | minor (uncert.) | b | **CLOSED** | The EIB, the W5 ribbon and the E-leads do not exist; the stages sit on the CCB (§2.3.1) |
| 3 | 34 | `u117-option-values-missing` | minor | d | **KEPT** | Carrier logic; it carries over with unchanged topology and values (§1.12.1) |
| 4 | 1 | `hang-fc-window-r5-gates-r1` | major | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 4 | 2 | `hang-fc-window-purge-reclose-death5` | major (uncert.) | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 4 | 3 | `i2-vs-preempt-stepb-failure-branch` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 4 | 4 | `i4-blocks-state99-under-h1` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 4 | 5 | `fr12-idle-selftests-need-motpwr-btbus-low` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 4 | 6 | `charger-trip-in-window-leaves-bt-bus-open` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 4 | 7 | `hb-selftest-skips-ilim-leg` | minor | d,f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 4 | 8 | `pin35-flt-floats-on-open-tap` | minor | g,f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 4 | 9 | `eib-e1-regn-adjacent-to-ilim-feed` | minor | b | **CLOSED** | No E-pad row; the successor is §3.6.2 item 4 (no part between REGN and ILIM_HIZ except Q403 + R455) |
| 4 | 10 | `i2-btboff-precondition-unobservable` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 4 | 11 | `fallback2-dbtsq-disconnect-claim` | minor | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 4 | 12 | `d107-tvs-crowbars-vmot-regen` | major | d,g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 4 | 13 | `ov-batt-cv-margin-ignores-adc-error` | major | e,g | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image (§5.5.1) |
| 4 | 14 | `ilim-clamp-por-adc-error-omitted` | minor (uncert.) | e | **KEPT** | T-B-23 stays; T-K-10 gates it because the POR ADC samples the ILIM_HIZ pin under switching |
| 4 | 15 | `r172-0805-short-dissipation` | minor | g,d | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 4 | 16 | `cr-eib-3v3-feed-unprotected-short` | major | b,d | **CLOSED** | No CR-to-EIB 3V3 feed exists; the ex-EIB stages share the one rail behind R375 (§1.12.2 item 2). Digest CB: P |
| 4 | 17 | `ribbon-adjacent-short-ilimrelb-rfcoff` | minor | b | **CLOSED** | The EIB, the W5 ribbon and the E-leads do not exist; the stages sit on the CCB (§2.3.1) |
| 4 | 18 | `tlv3012-ribbon-driver-short-current` | minor | b | **CHANGED** | R264/R265 deleted; the off-board conductor is now the tap wire F13/F20, and a short to GND draws 3.18-3.30 mA through R325/R348 1.00 kOhm alone, inside the TLV3012B 10 mA limit (§2.3.1). Digest CB: Y |
| 4 | 19 | `pin22-adc-keeper-imon-error` | minor | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 4 | 20 | `fc-window-raise-ignores-governor-floor` | major | f,e | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image (§5.5.1) |
| 4 | 21 | `purge-lock-tolerance-exceeds-tlead` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 4 | 22 | `preempt-btbus-not-owned-through-purge` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 4 | 23 | `fr11-trips-on-concurrent-regen` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 4 | 24 | `preempt-vindpm-failure-blocks-step-d` | minor | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 4 | 25 | `sag-path-no-return-to-raise` | minor (uncert.) | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 4 | 26 | `chg-src-misattributes-subh1-regen` | minor | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 4 | 27 | `efuse-cluster-no-room-at-pad10` | major | d-mech | **CHANGED** | The eFuse cluster now competes with the power stage; utilisation is 101 % as drawn (§3.2.3, L-1) |
| 4 | 28 | `svg-w5-pin6-legend-gnd` | minor | doc,b | **CLOSED** | The EIB, the W5 ribbon and the E-leads do not exist; the stages sit on the CCB (§2.3.1) |
| 4 | 29 | `bom-26awg-wire-quantity` | minor | a,doc | **CHANGED** | The lead wire disappears; the wire line shrinks to the taps only (§4.4.4). Digest CB: Y |
| 4 | 30 | `w3w4-hole-vs-18awg-silicone` | minor | a | **CLOSED** | The 0.3 m EVM leads W1-W8 do not exist on the CCB (§1.12.2 item 3) |
| 4 | 31 | `evm-jp3-jp5-link-pin-rating` | minor (uncert.) | c | **CLOSED** | There is no EVM; the modified part has no CCB footprint (§2.4.2) |
| 4 | 32 | `pm4-header-solder-sequence-ambiguous` | minor | d-mech | **CHANGED** | Option K (socket strips in the MB) and the bonded feet replace the PM4 solder sequence; seat heights move to T-K-04 (§1.3.4, 1.4). Digest CB: N |
| 5 | 1 | `ff-brake-edge-clears-peakhold-on-ripple` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 5 | 2 | `preempt-deadline-outside-completion-token` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 5 | 3 | `rtwdog-50ms-vs-blocking-flash-ops` | major (uncert.) | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 5 | 4 | `t10-fr08b-proof-relies-on-slow-decay` | minor | f,e | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image (§5.5.1) |
| 5 | 5 | `rt1987-ovp-otp-restart-contradiction` | minor (uncert.) | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 5 | 6 | `fallback2-pack-unfused-on-w3-and-bridge-rating` | major | a,g | **CHANGED** | W3 is gone; the fallback-2 fused MB link C-D12 -> C-D11 remains, with VCHG now on CCB copper |
| 5 | 7 | `rt1987-ovp-latch-vs-autorestart-contradiction` | minor (uncert.) | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 5 | 8 | `imon-vchg-ground-offset-under-charge-current` | minor (uncert.) | a,g | **KEPT** | IMON (pin 22) and V_chg (pin 38) still ride the MB-GND drop; T-F-15 still applies (§1.13.4 item 2). Digest CB: P |
| 5 | 9 | `ichg-upper-tolerance-omitted-in-ratings` | minor | e | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image (§5.5.1) |
| 5 | 10 | `ribbon-4-5-stat-sink-abs-max` | major | b | **CHANGED** | No ribbon; the on-CCB causes are a STAT-to-CE_DRV or STAT-to-3V3 trace or solder-bridge short (FR-22, T-C-05) and a pin-6 OUTPUT HIGH firmware fault. R475 1.00 kOhm is kept and holds the STAT sink to 3.06-3.30 mA against the 6 mA abs max; 41 mA without it (§2.3.1). Digest CB: Y |
| 5 | 11 | `eib-e6-e7-ce-stat-bridge` | minor | b | **CHANGED** | The lead bridge is gone; an adjacent-trace or solder-bridge short between the pin-6 and CE nets replaces it as an FR-22 case (§5.3 FR-22). Digest CB: Y |
| 5 | 12 | `gov-cmd-proxy-abs-closes-window-on-brake` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 5 | 13 | `ff-iindpm-step-overlaps-traction-ocfc` | major (uncert.) | f,e | **KEPT** | BQ25798 behaviour; the CCB uses the same IC and the same register image (§5.5.1) |
| 5 | 14 | `flash-commit-stalls-hb-and-wdt-in-run` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 5 | 15 | `purge-fc-only-ridethrough-bag-evidence` | major (uncert.) | g | **KEPT** | MB or system fact; the CCB connects to the same MB nets through the same taps (§1.12.2 item 4) |
| 5 | 16 | `efuse-cluster-no-room-at-pad10-reopen` | major | d-mech | **CHANGED** | As efuse-cluster-no-room-at-pad10; the congested region is x 33-41, y 56-67 (§3.2.3) |
| 5 | 17 | `pm4-header-solder-sequence-ambiguous-reopen` | major | d-mech,a | **CHANGED** | As pm4-header-solder-sequence-ambiguous |
| 5 | 18 | `ribbon-adjacent-short-stat-cedrv` | major | b | **CHANGED** | As ribbon-4-5-stat-sink-abs-max; the pin-6-to-CE_DRV short case is kept in FR-22 and T-C-05 (§2.3.1). Digest CB: Y |
| 5 | 19 | `j101-mated-socket-envelope` | minor (uncert.) | b | **CLOSED** | No J101; the option-K socket envelope is the new item N-24 (T-K-04) |
| 5 | 20 | `evm-jp17-stray-shunt` | minor | c | **CLOSED** | There is no EVM; the modified part has no CCB footprint (§2.4.2) |
| 5 | 21 | `b8-netlist-omits-cr-holes-pads` | minor | doc,d | **CHANGED** | A new pin-level netlist replaces B.8 (§2.5); BAV199 and SOT-23 pinnings are still TODO(verify) (O-9). Digest CB: N |
| 5 | 22 | `bom-polyimide-adhesive-unspecified` | minor | d-mech | **KEPT** | Header and MB-interface mechanics; any board in the 22 holes inherits them (§1.3) |
| 5 | 23 | `cr-end-strain-relief-anchor` | minor | a | **CHANGED** | W1-W4 strain relief disappears; tap-lead strain relief within 30 mm stays (§1.7.2 item 4) |
| 5 | 24 | `layout-table-dimension-gaps` | minor | doc | **KEPT** | Documentation rule; it applies to the CCB documents in the same way |
| 6 | 1 | `vreg-corruption-no-fixed-pack-ovp` | major | d,e,g | **KEPT** | The BQ29200 OUT -> U323 -> OVN term and ARM_OK' (U322) carry over; tap T22 and PM11 stay (§1.12.1) |
| 6 | 2 | `dbtsq-short-unfused-pack-on-vchg` | minor | g | **KEPT** | D-BT-SQ stays on the MB; a short still puts the pack on VCHG, now on CCB copper; FR-48 stays |
| 6 | 3 | `cr-and-mb-battery-path-copper-sized-below-ichg` | major (uncert.; verifier minor) | d-mech,g | **CHANGED** | CCB side re-sized: >= 2.5 mm pours at 1 oz, >= 5 vias of 0.3 mm per transition (§3.1.4-3.1.5). The MB VBT part stays (T-A-06c, T-F-16). Digest CB: N |
| 6 | 4 | `tc04-in-spike-criterion-omits-mb-vchgin-ratings` | major (uncert.) | d,g | **KEPT** | The eFuse IN side (C302a/b/c, D307) and the MB VCHG-IN end are unchanged; the three-point T-C-04 scope stays (§1.11.1) |
| 6 | 5 | `imon-bypass-cap-against-datasheet` | minor | d | **KEPT** | C305 stays DNP on the same eFuse network (§1.11.1; §4.1.1) |
| 6 | 6 | `fcc-rgn-lvc-threshold-vs-rt1987-en-band` | major | d,g | **KEPT** | Comparators U319-U321 (FCC_OFF, FCC_ON, RGN_ON) carry over on the same MB EN taps (§1.12.1) |
| 6 | 7 | `pin38-39-adc-overvoltage-on-vmot-excursion` | minor (uncert.) | g | **KEPT** | Pins 38/39 sense the same MB nodes; FR-49 stays (§5.2) |
| 6 | 8 | `loop-budget-5ms-breaks-1ms-tick-deadlines` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 6 | 9 | `purge-fc-only-ridethrough-bag-evidence-reopen` | major | f,g | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 6 | 10 | `chg-src-misattributes-subh1-regen-reopen` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 6 | 11 | `ff-headroom-admission-contradicts-single-g-test` | major | f | **KEPT** | Firmware requirement; the CCB removes no FR obligation (§5.3) |
| 6 | 12 | `ff-reversal-hold-unattainable-at-100khz` | minor | f,a | **CHANGED** | The 100 kHz fallback is less likely without W7; the SCL rise time on the CCB decides it (TODO(measure), §5.3 item 1) |
| 6 | 13 | `cr-coordinate-convention-mirror-ambiguity` | major | d-mech | **CHANGED** | The tab removes the CR pin-11 chamfer corner; the marker moves to (38.90, 76.40) and pin_identity_check.py must run again (§1.8; OT-7). Digest CB: N |
| 6 | 14 | `eib-e-lead-max-lengths-geometrically-infeasible` | minor | b,a | **CLOSED** | The EIB, the W5 ribbon and the E-leads do not exist; the stages sit on the CCB (§2.3.1) |
| 6 | 15 | `t-a-05-stale-j101-region-dims` | minor | b,doc | **CLOSED** | The EIB, the W5 ribbon and the E-leads do not exist; the stages sit on the CCB (§2.3.1) |
| 6 | 16 | `a6-w2-not-beside-star-pads` | minor | a | **CHANGED** | No W2; the battery return reaches pads 14/15 through the plane, in parallel with the MB GND pour, as ground-loops-parallel-returns (§1.13.2 item 2; §1.13.3). Digest CB: Y |

## 8. Open items and the operator measurement list

### 8.1 Consolidated open items, ranked

The list below merges the open-item registers of §8.3 and ranks them by their effect on the path decision and on the PCB
order. Items 1-6 gate the decision or the order. Items 7-16 gate the capture or the bring-up. Items 17-30 are clarifications
and records. Each item names its register IDs. Revision r2 appends items 31-36 without renumbering the r1 items. Item 31
ranks with items 1-6, items 32-34 rank with items 7-16, and items 35-36 rank with items 17-30. Items 4, 25 and 27 are
re-stated for the testbench facts (operator statement, 2026-11-10).

1. **Review of this document.** Review run 001 has run, and revision r1 applies its 22 findings (§0.9). Run a further
   round on revision r1 before any order. The ledger statuses and the severity of N-01 to N-27 stay proposals until that
   round confirms them (C-4, C-5; §7.2.5 item 2). In r2, the round covers revision r2, which is not reviewed. It also covers the
   proposed status change of key `tc04-in-spike-criterion-omits-mb-vchgin-ratings` (§7.2.3).
2. **Path and IC decision.** Close the BQ25798 behaviour gates T-B-06, T-B-09, T-B-10, T-B-12 and T-B-21, and wait for the
   result of the parallel IC search before the CCB is chosen (§0.3; §7.3.2).
3. **Board area and power-cell fit.** The plan books 101 % of the usable courtyard area as drawn, and 103 % with the
   battery-path corridor reserved on the top side (L-1). The power-cell sketch overlaps the header keep-out and zone Z-E
   when rotated into place (L-11). Table 3.5 books the area of the 3.5 A VCHG corridor to pins 18/19, but its route past
   L501 is not chosen (L-12). The DNP filter footprints C336, C337 and C453 add 13 mm² (L-1). The 10 mm
   separation class needs 52.2 mm² or more of courtyard, but only 32.7 mm² of top-side Z-Q meets 10 mm from the switch
   nodes. The rest goes to the bottom side at y <= 41.5, and the SW snubber footprints have no place as drawn (L-13,
   §3.6.1). The capture DRC (T-A-06) decides all four, and remedies 2-4 of Table 3.6 need an operator decision.
4. **Thermal margin beside the LM1084.** T_MB,0, the MB resistance R_MB, the LM1084 tab temperature and the LM1084 junction margin decide
   whether the 100 C junction target holds (L-5, O-16, OT-4; N-05, N-06). Efficiency above VBUS 20 V is unmeasured (L-8).
   r2: superseded in part. With the bench fan, the fan-on and fan-off soak T-K-20 decides the 100 C target and the FR-50
   thresholds (item 31). T_MB,0 and R_MB are record only (L-5). The LM1084 tab temperature and junction margin stay open
   (OT-4, N-06), and L-8 stays open.
5. **Header and socket current rating.** Pins 4 and 10 need 3 A or more; pins 14, 15, 18 and 19 need 2.0 A or more. The
   rating, the contact resistance, the retention force and the socket MPN for option K are unverified (O-10, L-7, B-8, B-9).
   r2: the rating applies to the tall-stack classes of §1.3.2 (pins of 10.8-13.8 mm, elevated sockets of h_k 2.6-5.6 mm),
   whose MPNs are also unverified (B-13).
6. **Supply and cost.** Obtain two fab quotes (4-layer, stack ST1 or ST2, 0.254 mm tented vias, 0.1/0.1 mm), a stencil
   quote and a PCBA quote with an inspection method for U501 (L-2, B-5, B-6, B-7, C-2). Obtain the non-TI stock and prices,
   the TPS26630RGER price and the SN74LVC2G08DCTRE4 equivalence (B-1, B-2, B-3).
7. **BQ25798 land pattern.** Closed on paper: §3.4.6 transcribes the land pattern, the pad-to-pin map and the stencil of
   SLUSDV2C pp.148-150, and the TIDA-050047 footprint matches it to 0.0006 mm (O-8, L-3). The stencil quote stays open
   (B-6). The capture must still check its footprint against Table 3.8c (T-A-05).
8. **TI reference layout.** Closed: §3.4.7-3.4.8 compare the TIDA-050047 layout with the power cell (A-1). Two items
   remain: the SYS-row remedy on L4 needs the underside clearance of §1.3.2, and the AGND net tie is a schematic decision.
9. **Inductor L501.** Confirm the Isat basis and temperature, the heating current, the -20 % tolerance, the core loss at
   1.5 MHz, the terminal positions and the mass (O-2, L-4). Check the L-I curve against the §2.1.3 saturation criterion
   (L >= 0.70 uH at 6.5 A). Ask TI whether the ISW 5 A figure is a DC or a peak value against the 5.51 A worst-case
   peak, and ask for the Q1_OCP / Q4_OCP cycle-by-cycle threshold (O-4).
10. **Input capacitors.** Select the 50 V 10 uF X7R MPN for C511, C512 and C529-C531 and check its DC-bias curve at 23.6 V
    (O-1, B-4).
11. **Round-3 calculations with CCB values.** Re-run `r3_calc.py` and [CALC] for the H.4 ILIM levels, the H.19 warm budget
    with the reduced R_PATH_RG, the T-K-05 in-circuit resistances, the logic quiescent budget and the T-F-13 R_path band
    (O-11; §6.7 item 4).
12. **Pin-11 marker.** Choose the chamfer corner and re-run [PIC] with the new outline before T-A-06 step 0 (OT-7, A-2).
13. **Switching noise at the comparators.** Measure the plane noise at the comparator divider bottoms during 1.5 MHz
    switching (L-9; T-K-09).
14. **D303 fit.** Decide whether D303 stays fitted, and check its leakage at the board temperature beside the LM1084 (O-12;
    T-C-04).
15. **Pack NTC.** T-E-09 decides between R525 (NTC simulator) and R526 (pack NTC) (O-13).
16. **Test infrastructure.** Decide the reversible FI1 link (A-3) and the LOOP1 layout variant (A-4); confirm a SCOPE-HF
    probe set (OT-2); decide BATSIM or a fused 2S pack for T-K-06 (OT-6).
17. **Input-side voltage ratings.** Confirm the limiting element voltage of R302 and of the divider tops R309, R311 and
    R314, and the rated voltage of the pad-10 header pin and socket contact (Table 2.4).
18. **TI clarifications.** Obtain the fsw tolerance and the PROG detection window (O-5), a ruling on the REGN loading by the
    pull-ups (O-6), the handling of unused D+/D- (O-7), the ICHG accuracy and the REGN range (OT-3).
19. **Small-part pinnings.** Confirm the SOT-23 MOSFET, BAV199 and BAT54HT1G pinnings (O-9).
20. **Teensy pad limit.** Confirm the i.MX RT1060 absolute maximum input voltage, the basis for keeping U404 (O-15).
21. **Residual double fault.** Record in the risk register that an eFuse FET short together with a V-MOT excursion above
    30 V reaches U501 VBUS (O-3; N-17).
22. **Board-level single faults.** Extend the round-3 single-fault table to power-stage events that can damage the
    interlock on the same board (N-20).
23. **Round-3 document correction.** EM13 uses the deleted SDRV-to-BAT option; flag it to the round-3 owner (O-14;
    §5.10 row 7).
24. **IPC-2221B clearance.** Confirm the clearance for the 16-30 V band (L-10).
25. **Gap pad.** Select the material, the compression force and the effect on retention (L-6). r2: not applicable
    (testbench with the bench fan). The fan-on design case meets the 100 C target without a pad (§3.7.4). The item stays
    as a record.
26. **Neighbour ratings.** Confirm the CO-5V temperature rating and the BQ29200 input threshold for CB-DISABLE (OT-5).
27. **Proposed margins.** Rule on the margins proposed without a source: the 1 mm envelope margin, 10 % below the SW
    absolute maxima, the 0.05 mm header seat gap, the 20 N foot pull and the 20 % contact-resistance drift (OT-1). In r2, the
    1 mm envelope margin is record only (no height restriction). The 20 % drift now applies to the T-K-17 repeat after
    mating cycles, not to T-K-19.
28. **BOM tap-pin quantity.** Closed: the BOM books 21 tap pins, and Table 4.4 includes them (B-11).
29. **Operator tooling.** Confirm the tooling for hand assembly: hot plate or oven, hot-air station, stereo microscope
    (B-10).
30. **Estimates.** Replace the design, assembly and bench hours by the operator's own estimate (C-1). Re-estimate Path B if
    it becomes a candidate (C-3). Confirm the Path A fault-injection build count (C-6).
31. **Bench fan and fan-off guard (r2).** Select the fan, its duct and its supply. The fan needs an MPN, an airflow
    and static-pressure curve and a current; [LC] §8.10 assumes 0.05-0.20 A. Its rating is 3.9-11.8 CFM at 30-50 % duct
    capture. Its static pressure exceeds the bare-channel 5.4-12.7 Pa by the duct losses ([LC] §8.9). The supply must
    not be the LM1084 / CO-5V rail. Measure the gap and top velocities (M15). Run T-K-20 (M16) to set
    `CHG_TDIE_DERATE_C` and `CHG_TDIE_TRIP_C` (starting values about 95 C and 105-110 C, TODO(calibrate)) (B-12, L-14;
    N-26).
32. **IN-side transient without the W1/W2 lead (r2).** Compute the OUT copper inductance from the capture. Compute
    the D307 energy at the ideal turn-off current of up to 117 A. Obtain the real TPS26630 hot-short current and fall
    time (L-15; N-25; [TS] §(c)). §1.11.2 item 4 gives the r2 statement.
33. **Tall header stack (r2).** Select the header, socket and spacer classes for the chosen H_u; obtain the seat heights,
    lead styles, pin alloy and socket withdrawal force (B-13; N-27; [TS] §(e)).
34. **Pin-18 joint with forced air (r2).** Compute the joint temperature with the fan on; measure it in T-K-20 (L-14;
    §3.7.6).
35. **Thermal model inputs (r2).** Confirm the solder-mask and polyimide emissivity (0.90 assumed), the [DS] §6.4 row
    order of the thermal table, and the spreading inside the CCB, which the lumped model omits (L-14).
36. **U501 heatsink option (r2).** Select a heatsink of R_sa 60 C/W or less that fits the 4 x 4 mm package beside L501,
    and its adhesive or clip, if T-K-20 requires it (B-12; §3.7.4a).

### 8.2 Operator measurement list

The list below consolidates every measurement that no source can close. It is ordered by when the measurement is possible.
Items 1-10 need the vehicle as it is, with the Ag105 still fitted (phase 0 of §6.5.2). Items 11-13 follow the Ag105
removal. Items 14-21 need a built CCB. Revision r2 appends items 22-24 for the bench fan without renumbering. Item 22
runs first on the 1:1 template before layout and again on the built CCB; items 23-24 need a built CCB. Items 3, 4, 10
and 19 are re-stated for the testbench facts (operator statement, 2026-11-10).

1. **Ag105 standoff h_s (gate D-2), module top height and pin length below the MB**, at all four module corners, before the
   module is removed (M1; T-K-01).
2. **LM1084 thermal state**: tab temperature and air temperature at x 48.7, z 4 mm beside pins 4-8, at the worst vehicle
   load (M11; T-K-02).
3. **MB surface temperature T_MB,0 and the MB resistance R_MB** under the planned power cell, x 25-35, y 55-75, at the
   worst vehicle load, with the Ag105 fitted and idle and no CCB. R_MB comes from the heater step of T-K-02. T_MB,local
   with the CCB dissipating is computed as T_MB,0 + P_MB x R_MB (§3.7.2). These values decide the 100 C junction target
   (M12; T-K-02). r2: **record only.** With the fan on, T_J moves by 0.15-0.30 C per C of MB idle offset ([LC] §8.6b).
   Item 23 decides the 100 C target. The heater step is optional.
4. **Free height H_env** above the CHG footprint and above rect A, to the lowest chassis part, cable or body panel (M6;
   T-K-01). r2: **record only (testbench).** The CCB has no height restriction (operator statement, 2026-11-10).
5. **Heights of the parts near rect A**: L-FC (with the gap from its body to the tab edge y 76.40), OP-FC, MDAC-FC and
   ROP1-FC (M7; T-K-01).
6. **LM1084 and CO-5V heights and positions** (M5; T-K-01).
7. **J-BL, J-NTC and J-FC wire and screwdriver envelope**, including the path to the J-BL position-3 screw (M8; T-K-01).
8. **Foot-spot access and surface** at (23.20, 70.64) and (32.20, 70.64) (M9, M10; T-K-01).
9. **MB thickness and copper weight** (M13; T-K-01).
10. **Vibration level** at the MB mounting point during a drive, if an accelerometer or an IMU log is available (M14).
    r2: **not applicable (testbench).** The vehicle does not move (operator statement, 2026-11-10).
11. **Hole condition** of all 22 CHG holes after the module removal (M2; T-K-04).
12. **Header and socket seat height** on a dry fit (M3; T-K-04; an optional early value on a drilled FR-4 coupon in
    T-K-01). r2: it also sets the channel gap g = H_u - 0.125 mm (5 mm minimum, 5-8 mm recommended, §1.3.2 rule 3) and
    the spacer length. Measure it at the inlet edge, at mid-body and at the tab.
13. **Hole positions** against a 1:1 print of the pin field (M4; T-K-04).
14. **Efficiency above VBUS 20 V**, at 21.5 V and 22.6 V (L-8; T-B-19).
15. **SCL and SDA rise time at 400 kHz** on the CCB with the 2.7 kOhm MB pull-ups (§5.3 item 1; §5.8 item 9). r2: the
    tall stack adds at most 0.47 pF per line and 1.08 ns of rise time at H_u 8 mm ([TS] §(d)). The bus capacitance
    itself remains unmeasured.
16. **Plane noise at the comparator divider bottoms** during 1.5 MHz switching (L-9; T-K-09 step 5).
17. **D303 board temperature and leakage** beside the LM1084 (O-12; T-A-07).
18. **Header contact resistance and pull-out force** on pins 4, 10, 14, 15, 18 and 19 (T-K-17).
19. **In-situ temperatures of the CCB** beside the running LM1084, which set `CHG_TDIE_DERATE_C` and `CHG_TDIE_TRIP_C`
    (T-K-14; FR-50). r2: measured with the fan on, as the fan-on leg of item 23; the thresholds come from item 23.
20. **Monostable widths on the CCB**, which set TW_HB_MAX and TW_QQ_MAX (T-C-10).
21. **REGN delay on the CCB**, which sets T_REGN_MAX (T-B-20, T-B-11).
22. **Fan delivery and gap velocity (r2)** at the inlet edge, in the gap at the inlet, at mid-body, at both outlets and
    about 5 mm above the CCB top (M15; T-K-20 step (1)). Also the fan voltage and current, and a check that the fan
    supply is not the LM1084 / CO-5V rail. First on the 1:1 template at the chosen H_u, then on the built CCB.
23. **Fan-on and fan-off thermal soak (r2)** at the 2.7 W and 2.9 W points and at the 2.08 W derate image, with
    thermocouples at the M16 points and TDIE over I2C. It sets the real h and gap flow, the fan-on T_J against the 100 C
    target and the FR-50 thresholds (M16; T-K-20).
24. **Bench room air (r2)** at the fan inlet over a bench session, the T_air of the forced-air model (M17; T-K-20).

### 8.3 Open-item registers by section

The registers below keep the IDs that the other sections cite. Section 8.1 ranks their content.

#### 8.3.1 Schematic (O-1 to O-16)

| ID | Item | Class | Action |
|---|---|---|---|
| O-1 | 50 V 10 uF X7R MPN for C511, C512, C529-C531 and its DC-bias curve at 23.6 V (C_VBUS >= 2 uF, C_PMID >= 4 uF effective) | S | TODO(verify: manufacturer DC-bias data), T-A-04 |
| O-2 | L501: confirm 11.1 A is Isat, its saturation definition and temperature basis, the heating current, and the -20 % tolerance; and confirm that L >= 0.70 uH at 6.5 A at T_max and the -20 % limit (§2.1.3 criterion) | S | TODO(verify: TDK SPM6530T datasheet) |
| O-3 | Residual double fault: eFuse FET short together with a V-MOT excursion above 30 V reaches U501 VBUS (D307 VBR >= 36 V). No IC-side barrier exists below 25.2 V: VAC_OVP (26 V setting) trips at 25.2-26.8 V and VBUS_OVP at 25.2-26.2 V ([DS] EC), so the eFuse OVP (22.61-23.63 V) is the only protection in the 23.63-25.2 V window (D2 reason b) | I | Record in the risk register; no ACFET pair (D2) |
| O-4 | Meaning of [DS] §6.3 ISW 5 A against the 5.51 A worst-case inductor peak; and the Q1_OCP / Q4_OCP cycle-by-cycle current-limit threshold (minimum and maximum) for L501 substitution (§2.1.3) | S | TODO(verify: TI E2E) |
| O-5 | fsw tolerance; PROG detection window | S | TODO(verify: TI) |
| O-6 | REGN loaded by the /CE and gate pull-ups (inherited deviation from [DS] §7.3.4.1) | S | Accept or ask TI E2E |
| O-7 | Unused D+/D- handling (open vs R506 short) | S | TODO(verify: SLUSDV2C §7.3.4.5, TI E2E) |
| O-8 | BQ25798 land pattern (29 pads, 33 lead segments) and pad-to-pin map; stencil p.150 | S | **Closed on paper:** §3.4.6 Table 3.8c from SLUSDV2C pp.148-150; TIDA-050047 footprint identical ([TLP] §3). Capture footprint check in T-A-05 |
| O-9 | SOT-23 MOSFET, BAV199 and BAT54HT1G pinnings | I/S | TODO(verify: manufacturer datasheets), T-A-05 |
| O-10 | Header pin current rating (>= 3 A pins 4/10, >= 2.0 A pins 14/15/18/19) | I | TODO(verify: Samtec TSW datasheet), T-A-05 |
| O-11 | H.4 ILIM levels and H.19 warm budget re-derived for on-board leakage and the reduced R_PATH_RG | S / I | TODO(calc: round3/calc/r3_calc.py with the CCB values) |
| O-12 | D303 fitted or DNP; its leakage at the board temperature beside the LM1084 | I | T-C-04 on the CCB; TODO(measure) |
| O-13 | NTC type at J-NTC (T-E-09) decides R525 vs R526 | S | T-E-09 |
| O-14 | Round-3 EM13 uses the SDRV-to-BAT option deleted in [DS] rev C | S | Flag to the round-3 owner |
| O-15 | Teensy 4.1 pad absolute maximum (basis for keeping U404) | I | TODO(verify: i.MX RT1060 datasheet) |
| O-16 | Thermal: 2 W class charger loss ([STUDY] §1.6) beside the LM1084, ambient maximum 85 C ([DS] §6.3) | S | Layout/thermal section; T-B-16, T-B-19 re-specified |

#### 8.3.2 Layout (L-1 to L-15)

| ID | Item | Label | Action |
|---|---|---|---|
| L-1 | Area utilisation 101 % as drawn (103 % with the L-12 corridor reserved on the top side); 78-86 % after the remedies of Table 3.6 (80-87 % with the corridor). The DNP filter footprints C336, C337 and C453 add 13 mm² (about 6 mm² as 0402): 102 % and 104 % as drawn, 79-86 % and 80-87 % after the remedies (§3.2.3) | M | Courtyard DRC of the capture (T-A-06 class); operator decision on steps 2-4 |
| L-2 | Fab capability: 0.1 mm trace/space, 2 oz inner, 0.254 mm vias with 0.508 mm lands at 0.12-0.15 mm from a pad, 0.1 mm mask dam, stack drawing; 0.2 mm space at 2 oz outer for ST3/ST4. Filled via-in-pad is not required (3.1.5 rule 4) | I | TODO(verify: JLCPCB / PCBWay / OSH Park capability pages) |
| L-3 | RQM pad-to-pin map; which power pads take in-pad vias | S | **Closed:** map in Table 3.8c; no pad takes a via. The SW and GND vias sit under the body (3.4.3 item 1, [TLP] §4) |
| L-4 | L501 terminal positions, core loss at 1.5 MHz, mass | S | TODO(verify: TDK SPM6530T datasheet) |
| L-5 | T_MB,0 and R_MB under the cell, and the LM1084 state | I | TODO(measure: M11, M12 with the T-K-02 heater step). r2: T_MB,0 and R_MB are record only (fan on, [LC] §8.6b); the LM1084 state (M11) stays open |
| L-6 | Gap pad: material, interface resistance, compression force at the fitted thickness (H_u - 0.125 mm, 10-30 % compression), area 114.3 mm² around C506/C508, effect on retention. r2: not applicable (testbench with the bench fan, §3.7.4); kept as a record | I | TODO(verify: gap-pad datasheet); T-K-18 pull at F_pad; rev-A thermocouple test |
| L-7 | Header and socket current rating and contact resistance | I | TODO(verify: Samtec TSW / socket datasheet), T-A-05 |
| L-8 | Efficiency above VBUS 20 V | S | TODO(measure: rev-A bench efficiency at 21.5-22.3 V) |
| L-9 | Noise at the comparator divider bottoms during 1.5 MHz switching | I/S | TODO(measure: T-C-07 / S4-n class) |
| L-10 | IPC-2221B clearance for the 16-30 V band | I | TODO(verify: IPC-2221B Table 6-1) |
| L-11 | The first bulk rows of the Figure 3.2 cell span about 19 mm (x -10.5 to +8.2); rotated at x 28.2 they overlap the header keep-out (SYS row) and Z-E (PMID row) | S | Two-deep bulk-capacitor arrays inside x 22.4-37.5 (3.4.2); capture DRC |
| L-12 | The route of the 3.5 A VCHG path from the U501 BAT pins to pins 18/19 past L501 is not chosen. Table 3.5 books its top-side area below y 50.4 (25 mm²), but option (a) or (b) must be decided at capture | M | Option (a) 1.8 mm L1 neck beside L501 or option (b) U501/L501 +1.3 mm in x; in both, x 22.4-25.4 below y 50.4 reserved and Z-Q from x 25.4 (3.3.3 item 4) |
| L-13 | Separation from the switch nodes (Tables 3.9-3.9b). The 10 mm class needs >= 52.2 mm² (R309-R316, R340-R343 alone; 65.3 mm² with the DNP filter footprints C336, C337 and C453) against 32.7 mm² in Q10-T, so part goes to Q10-B (bottom, y <= 41.5), whose free area is unknown. The SW snubber footprints have no place inside E-SW as drawn. Option (b) of L-12 cuts Q10-T to 22.0 mm² and Q10-D to 7.3 mm² | M | Separation check in the T-A-06 capture DRC (§3.6.1 rule 5); operator decision: snubber footprints inside E-SW or omitted (Table 3.6 step 3); TODO(verify: Q10-B area); TODO(verify: TDK SPM6530T land pattern, L-4) |
| L-14 | Forced air (r2): the real gap and top velocities and h with the MB parts, the CCB underside parts and the foot spacers in the channel; the duct capture fraction (30-50 % assumed); solder-mask and polyimide emissivity (0.90 assumed); spreading inside the CCB; the pin-18 joint temperature with the fan on; the [DS] §6.4 row order of the thermal table ([LC] §8) | M | TODO(measure: M15, M16; T-K-20). TODO(calc: pin-18 joint with forced air). TODO(verify: emissivity data; [DS] §6.4) |
| L-15 | IN-side transient without the W1/W2 lead (r2): the OUT copper inductance from U301 OUT to the C511/C512 short; D307 energy at the ideal turn-off current of up to 117 A; the real TPS26630 hot-short current and fall time ([TS] §(c)-(d); N-25) | I | TODO(calc: L_OUT from the capture; D307 energy). TODO(verify: SLVSE94G). T-C-04 records (a)-(c) |

#### 8.3.3 Bill of materials (B-1 to B-13)

| ID | Item | Class | Action |
|---|---|---|---|
| B-1 | Non-TI stock and prices for every CSV line marked TODO(verify) | I/S | Query DigiKey or Mouser interactively (both blocked plain curl on 2026-11-10) |
| B-2 | TPS26630RGER price (no part-details page) | I | TI store cart or TI sales |
| B-3 | SN74LVC2G08DCTRE4 equivalence to DCTR | I | TODO(verify: SCES198N ordering addendum) |
| B-4 | 50 V 10 uF X7R 1210 MPN and DC-bias curve | S | O-1; T-A-04 |
| B-5 | Fab quote: 4-layer, 1 oz outer with 1 oz (ST1) or 2 oz (ST2) inner, 0.254 mm tented vias, ENIG, 1219 mm² L-outline, lot of five | I | Two quotes before the order |
| B-6 | Stencil quote and U501 apertures per SLUSDV2C p.150 | S | **Narrowed:** apertures = pads, 0.1 mm stencil (§3.4.6 rule 5). Quote still open |
| B-7 | PCBA quote, library stock, consignment of TI parts, X-ray of U501 (an inspection gate in options H and P, §4.4.3) | I/S | Before choosing option P; X-ray availability before the first stage-2 assembly |
| B-8 | Socket strip MPN (option K): tail for the 1.10 mm drill, accepted pin range, retention force | I | §1.3.4, §1.7.1 |
| B-9 | Header pin current rating | I | O-10 |
| B-10 | Operator tooling for option H (hot plate or oven, hot air, stereo microscope) | S | TODO(verify: operator) |
| B-11 | Tap-pin quantity: the CSV line "F01-F24 tap pins" books 20 pins, while §2.5.9 has 21 fitted tap pads (F01-F21; F22 and F23 DNP; F24 spare). The roll-up of §4.5 is one pin short, USD 0.50 per board at the allowance; the 10 spares cover a build | I | **Closed:** `make_bom.py` books 21 pins; `bom.csv` and `bom_cost.json` are regenerated (Table 4.4) |
| B-12 | Bench fan (r2): MPN, airflow and static-pressure curve, current at 5 V or its own supply voltage, frame size and mount; fan lead connector; the DNP fan regulator; the DNP U501 heatsink (R_sa <= 60 C/W, fits beside L501) and its adhesive or clip | I / S | TODO(verify: fan, connector, heatsink and adhesive datasheets); §1.6.3, §3.7.4a; M15 |
| B-13 | Tall-stack parts (r2): header class S1-S3 (pins 10.8-13.8 mm), elevated socket class K2-K3 (h_k 2.6-5.6 mm), nylon M3 spacers of length H_u (5.1-8.1 mm); seat heights, lead styles, pin alloy and modulus, socket withdrawal force per contact | I | TODO(verify: Samtec, Harwin and spacer drawings); §1.3.2 Table 1.3a, §1.4; [TS] §(e) |

#### 8.3.4 Tests (OT-1 to OT-8)

| ID | Item | Action |
|---|---|---|
| OT-1 | Margins proposed in section 6 without a source: the 1 mm envelope margin (T-K-01), 10 % below the SW absolute maxima (T-K-07), 0.05 mm header seat gap and 20 N foot pull (T-K-18), 20 % contact-resistance drift (T-K-19). r2: the envelope margin is record only; the 20 % drift applies to the T-K-17 repeat after mating cycles; the 10 N handling force of T-K-18 step (8) is also a proposal | Operator ruling |
| OT-2 | SCOPE-HF availability (>= 500 MHz with a tip-and-barrel probe) | TODO(verify: bench equipment) |
| OT-3 | [DS] values not yet transcribed: ICHG accuracy, REGN range. (Resolved: VBUS absolute minimum -2 V, [DS] §6.1 p.7; TDIE in REG41, 0.5 C per LSB, [DS] §7.5.1.53) | TODO(verify: SLUSDV2C EC) |
| OT-4 | LM1084 junction limit and KTT thermal metrics (the [LM] §5.3 text extract does not show the column assignment) | TODO(verify: LM1084 DS §5.3, §5.4) |
| OT-5 | CO-5V temperature rating; BQ29200 input threshold for CB-DISABLE | TODO(verify: CO-5V datasheet; BQ29200 DS) |
| OT-6 | Whether T-K-06 uses BATSIM or a fused 2S pack | TODO(operator) |
| OT-7 | The re-run of [PIC] with the new pin-11 marker position (§1.8) | TODO(verify) before T-A-06 step 0 |
| OT-8 | T-K-20 equipment and limits (r2): an anemometer probe that fits the 5-8 mm gap (ANEMO); the TC6 logger; the soak duration and the FR-50 starting thresholds (about 95 C and 105-110 C) | TODO(verify: bench equipment); TODO(calibrate: T-K-20) |

#### 8.3.5 Comparison (C-1 to C-6)

| ID | Item | Label | Action |
|---|---|---|---|
| C-1 | Design, assembly and bench hours are estimates without a recorded basis for CR, EIB or CCB | I | Replace with the operator's own estimate before the decision |
| C-2 | Fab and PCBA lead times are round-1 estimates | I | TODO(verify: two fab quotes and one PCBA quote, B-5, B-7) |
| C-3 | Path B1 and B2 figures predate the round-2 rulings and the interlock | I | Re-estimate if Path B becomes a candidate ([EVAL] line 961) |
| C-4 | The ledger statuses are this section's judgement on sections 1-6 | I | Review run 001 corrected five statuses (§7.2.2); confirm the revision-r1 statuses in the next review round. r2: confirm also the proposed CHANGED status of `tc04-in-spike-criterion-omits-mb-vchgin-ratings` (§7.2.3) and regenerate [LEDG] if it is confirmed |
| C-5 | The severity of N-01 to N-27 is proposed, not verified (r2 adds N-25 to N-27 and re-states N-05, N-06, N-08, N-09 and N-24) | M | Same review round |
| C-6 | Path A fault-injection build count | I | TODO(verify: [WD] T-C-05, T-D group setups) |

#### 8.3.6 Items raised at assembly (A-1 to A-4)

| ID | Item | Label | Action |
|---|---|---|---|
| A-1 | The TIDA-050047 reference design (TIDUEY1C) supplies an Altium project REV_A1 with 4-layer Gerbers ([TIDA]). Its schematic part is BQ25792RQM and its BOM lists BQ25798RQM. The 29 pin numbers and names of the library part equal [DS] Table 5-1 ([TLP] §5b) | S | **Closed:** §3.4.7 transcribes the layout and §3.4.8 lists the copied practices. Residual: the BQ25792 electrical differences are TODO(verify: SLUSDG1) only if a TIDA value is reused |
| A-2 | The pin-11 chamfer at (38.90, 76.40) is about 18 mm from pin 11. The tab corner nearest pin 11 is (17.70, 76.40). The L-shaped outline already breaks the mirror symmetry | I | Operator choice of the corner; re-run [PIC] either way (OT-7) |
| A-3 | A 0402 0 Ohm link in the U401 1Y-to-/CE trace would make the T-D-03 and T-D-06 injections on FI1 reversible. Open = /CE HIGH, which is the fail-safe direction | S | TODO(decision: schematic owner) (§6.7 item 1) |
| A-4 | LOOP1 needs an L501 pad option for a wire bridge; SW1 and SW2 need probe landings with a ground point within 5 mm (the L501 and C529 pads) | S | Layout variant before the capture freezes (§6.7 item 2) |

## 9. Sources

### 9.1 Citation keys

Table 9.1 defines every citation key of this document. "Review folder" means
`docs/reviews/charger_bq25798_custom_board_2026-11-10/`.

| Key | Source |
|---|---|
| [AG] | Silvertel Ag105 data sheet V1.1, `references/Datasheets/AG105_Silvertel.pdf`; Figure 11 (p.21) for the module outline, pin section and standoff |
| [BOMGEN] | Review folder: `make_bom.py` (BOM generator) and its outputs `bom.csv` and `bom_cost.json` |
| [CALC] | Review folder: `sch_calc.py` and `sch_calc_out.txt` (inductor ripple and peak from [DS] Eq 4-6, the L501 current requirement, VCHGOUT capacitance, inrush, PMID ripple current and voltage ([DS] Eq 7-8) on a VBUS sweep 12-23.63 V including D = 0.5, the high-impedance comparator inputs, pin currents) |
| [DD] | The detailed design of `docs/battery_isolation_feasibility_2026-11-07.md` (post-drive inspection C-4), as quoted in [STUDY] §4 |
| [DS] | TI SLUSDV2C, BQ25798 data sheet, revised June 2026, `references/TI_BQ25798_design_files/BQ25798_SLUSDV2C.pdf`; cited by section, table, figure or page. Equations are cited by their printed labels (Eq 4-8, pp.133-134); the [DS] prose numbers them one lower |
| [EVAL] | `docs/charger_replacement_evaluation_2026-11-05.md` (round 2 and the round-3 summary 0.1a; §4.2 EVM modifications M1-M11; §7 schedule and cost) |
| [LC] | Review folder: `layout_calc.py` and `layout_calc_out.txt` (conductor widths, vias, losses, lumped thermal model, area budget, pin heating; section 8, r2: forced air on the testbench, fan-off case, heatsink option, gap selection, fan flow and fan supply) |
| [LEDG] | Review folder: `make_ledger.py` and `ledger_table.md` (the 203-key ledger of §7.A; the generator asserts 203 keys) |
| [LM] | LM1084 data sheet, `references/Datasheets/LM1084ISX-5p0.pdf` |
| [LOOP] | `docs/reviews/charger_eval_2026-11-05/round3/review_loop.md` (review rounds 1-6 and the closing passes) |
| [MECH] | `references/Scale Car Board PCB 20260625.brd` (EAGLE XML), parsed by `mech_parse.py`; output `mech_parse_out.txt` and `mech_parse_out.json`, and the extracted facts in `digest_mechanics.md` (all in the review folder) |
| [OSH] | `https://docs.oshpark.com/services/four-layer/`, fetched 2026-11-10 (published 4-layer price and stack) |
| [PB] | `docs/reviews/charger_eval_2026-11-05/path_b_respin.md` (round-1 Path B estimates: §2.6 B1, §3.3 B2, comparison table lines 345-355) |
| [PIC] | `docs/reviews/charger_eval_2026-11-05/round3/calc/pin_identity_check.py` (pin-identity and mirror check of the 22-pad field) |
| [STUDY] | Review folder: `digest_study_reviews.md` (operator rulings, requirements HR1-HR5, the round 1-6 finding table with tags, gate D-2 and the mechanical unknowns), compiled from [EVAL], [WD], [LOOP] and `docs/battery_isolation_feasibility_2026-11-07.md` |
| [TI-EVM] | `https://www.ti.com/tool/BQ25798EVM`, `data-price` attribute, 2026-11-10 |
| [TI-INV] | TI store inventory endpoint `https://www.ti.com/storeservices/cart/opninventory?opn=<OPN>`, 2026-11-10 18:26 UTC |
| [TI-PD] | TI part-details pages `https://www.ti.com/product/<family>/part-details/<OPN>`, 2026-11-10 18:27 UTC; parsed prices in the review folder `ti_prices.json` |
| [TID] | Review folder: [TID] (transcribed facts of SLUSDV2C and SLUUCB5E: pin table, EVM designator table, layer reading, rev-C changes); cited by section or line |
| [TIDA] | `references/TI_BQ25798_design_files/` (fetched 2026-11-10), described in its `README.md`: SLUSDV2C, SLUUCB5E and the TIDA-050047 reference design (design guide TIDUEY1C rev C, schematic TIDM748, BOM TIDM749, assembly drawings TIDM750, layer plots TIDM751, Altium project TIDM752 REV_A1 with its PCB file, BOM `.xlsx`, Gerbers, fab notes GM10, stack-up GM12 and NC drill files) |
| [TLP] | Review folder: `tida_layout_parse.py` and `tida_layout_parse_out.txt` (parse of the TIDA-050047 PCB file, Gerbers, drill file, rule export and schematic pin records around U1; positions in cell coordinates); cited by output section |
| [TS] | Review folder: `tall_stack_calc.py` and `tall_stack_calc_out.txt` (r2 tall header stack checks: pin resistance and I2R, input-loop inductance, eFuse hard-short spike, signal loading, mechanical loads); cited by output section (a)-(e) |
| [UG] | TI SLUUCB5E, BQ2579xEVM user guide, `references/TI_BQ25798_design_files/BQ2579xEVM_SLUUCB5E.pdf`: schematic Figs 4-5 to 4-7, BOM Table 4-1, layer Figs 4-1 to 4-4, layout guidelines §3 |
| [WD] | `docs/charger_bq25798_wiring_design_2026-11-05.md`, round 3 r6 (Path A): sections A-L, cited by section letter and number |

### 9.2 Other repository sources

1. `references/Scale Car Teensy IO - IO.csv`: the authoritative Teensy pin map (Ag105 era at commit `330344c`).
2. `references/Scale Car Design PCB BOM 20260622.csv`: the MB parts list (designator CHG for the Ag105).
3. `references/Scale_Car_Board_20260624.sch`: the MB schematic in EAGLE XML.
4. `teensy_controller/teensy_controller.ino` at commit `330344c` (fw v37 rev 2), cited as "ino <line>" in section 5.
5. `docs/reviews/charger_eval_2026-11-05/round3/calc/r3_calc.py`: the round-3 calculations (H.4, H.18, H.19, H.22).

### 9.3 Component data sheets cited by name

The following data sheets are cited by their document number in the text: TPS26630 (SLVSE94G), TLV3012 (SBOS300C),
SN74LVC2G08 (SCES198N), RT1987 (DS-00, `references/Datasheets/RT1987_DS-00.pdf`) and BQ29200
(`references/Datasheets/BQ29200_TI.pdf`). Data sheets marked TODO(verify) in the text (TDK SPM6530T, Samtec TSW and SSW,
Murata GRM32ER71H106KA12L, Vishay TNPW, Nexperia BAV199, onsemi BAT54HT1G and 2N7002K, the i.MX RT1060) were not read for
this document.
