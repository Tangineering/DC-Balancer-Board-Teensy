# EVM on the carrier: round-4 (r7) proposal for the CHG carrier outline, the BQ25798EVM placement and the EIB merge

## 0. Scope, conventions and sources

### 0.1 Scope

This proposal answers questions Q1-Q6 of the round-4 brief for one approach: the BQ25798EVM mounts on, or directly beside,
an extension of the CHG carrier (CR), so that the EVM interface board (EIB) merges onto the CR and the E-leads stay short.
The CR still plugs into the 22 Ag105 holes on one 1x10 and one 1x12 header strip. The EVM stays the power stage; a custom
BQ25798 board is outside the scope of this proposal. The design document r6
(`docs/charger_bq25798_wiring_design_2026-11-05.md`) is the baseline and is not edited here.

### 0.2 Conventions

Every board coordinate is an Eagle `.brd` board coordinate in mm, top view, origin at the MB origin, +x right, +y up (design
A.2). EVM coordinates use the EVM frame of `work/evm_geometry.md` (origin at the lower-left corner of the EVM outline, top
view, +y up). A value marked `TODO(measure: ...)` or `TODO(verify: ...)` is not known; the text names what decides it. An
**ASSUMPTION** is a stated input that a named measurement replaces.

### 0.3 Sources and calculation

Every number in this proposal comes from `work/r7_evm_on_cr_calc.py` (output `work/r7_evm_on_cr_calc_out.txt`, figure
`work/r7_evm_on_cr_map.png`) unless a section names another source. The script reuses the round-4 work files:

- `work/mb_mech_calc.py` (MB elements, L1/L16 copper, vias and the height table with its sources) and
  `work/mb_mechanical.md` (zones, LM1084 estimate, pin-load and resonance method);
- `work/evm_geometry.md` and `work/evm_calc/evm_geom_out.txt` (vector EVM positions, outline 88.90 x 88.90 mm, no mounting
  holes, bumpons H1-H4, part heights);
- `work/eib_merge_failsafe.md` and `work/eib_merge_calc.py` (merge verdict G1/G2, conditions 1-10, pickup budgets and the
  dipole model);
- `round4/calc/stackup_area_out.txt` and `work/stackup_area.md` (area booking, strict usable basis, U4 = 0.75, stack-up).

Figure 1 (`work/r7_evm_on_cr_map.png`) shows the proposed CR outline, the EIB island, the head feet, the EVM on its bracket
and every lead route over the MB plan.

## 1. Summary

### 1.1 Verdict

The literal mezzanine (EVM above the MB on standoffs from the CR) is not feasible. The EVM mounts **beside** the MB +y edge
on a chassis bracket, and the CR reaches that edge as a **ring around L-FC** with a 12 mm off-board **tongue** that carries
the merged EIB section. With this arrangement the EIB merge meets the G1 conditions of `work/eib_merge_failsafe.md`. The
straight lengths of E8, E3, E4, E2 and E7 are within 1 mm of the r6 values, E6 is 2.8 mm longer and E1 4.9 mm shorter, and
every W lead becomes shorter than the r6 0.30 m. Confidence: high for the plan geometry and the electrical arguments; medium
for the mechanics (order-of-magnitude pin loads, unmeasured vibration). The whole approach depends on measurement M2 (room
beside the MB +y edge), which no repository record answers.

### 1.2 Answers at a glance

Table 1 gives the short answer to each question; sections 3-10 give the evidence.

Table 1. Short answers.

| Question | Answer |
|---|---|
| Q1 side and extent | +y. Ring around L-FC (window x 20.55-37.06, y 76.51-90.11), head x 10.00-48.70 to the MB edge, tongue to y 110.04 (12.0 mm off-board). Outline 2280 mm² (+1257 mm² over r6), bounding box 38.70 x 75.90 mm |
| Q1 header and support | Unchanged Samtec TSW-110-07-G-S / TSW-112-07-G-S, 2.54 mm body on the 0.125 mm sheet: CR underside 2.665 mm, CR top 4.265 mm. Two bonded feet (4 x 4 x 2.665 mm) at (14.0, 94.0) and (38.0, 95.0) on GND-only copper |
| Q2 EVM placement | Chassis bracket, EVM right edge (J5, TP33/TP49 cluster) facing the MB, 5 mm beyond the tongue; EVM outline x -26.00-62.90, y 115.04-203.94; stock bumpons kept, no drilling |
| Q2 leads | E8/E3/E4/E2/E7 13.1/15.8/19.9/23.8/29.2 mm, E6/E5/E1 48.2/49.8/64.1 mm straight; W3/W4 81/68 mm, W1/W2 206/202 mm, W7 163 mm routed (r6: 0.30 m each, plus the 0.30 m W5 ribbon) |
| Q3 EIB merge | Yes (G1). The open-conductor, dead-driver and rail-loss arguments hold; the island + R273, R276 10 ohm in E1, strain relief and T-F-18 are conditions; the W5 list, J101/J201, R176/R177 and T-C-13 retire |
| Q4 layers | 4-layer 1.6 mm, single-sided (all parts on L1, L4 continuous GND except the island): merged demand 1372 mm² on 1882 mm² strict usable = 73 % (68 % without DNP footprints) against U4 0.75. 2-layer rejected |
| Q5 constraints | Retire: footprint confinement, passives-only bottom, bottom keep-out, MB-copper shadow, <= 1.0 mm bottom cap, the 84 % budget. Stay (CR still over VBT/VCHG-IN on the footprint): polyimide sheet, flush-cut tails, top-side SMT tap pads. New: L4 solid under the lane and the band, island only off-board |
| Q6 modifications | No EM or PM becomes unnecessary. EM23 changes (bumpons kept, clamp bracket), EM7 changes (J3 desoldered, not capped), PM0/PM4 change. The pending FC-channel bench work must precede PM4 |

## 2. Options evaluated and rejected

### 2.1 EVM as a mezzanine over the MB

The MB holds no 88.90 mm span that is free of tall or unmeasured parts. Table 2 lists the parts that decide it (heights from
the `mb_mech_calc.py` table, each with its source).

Table 2. MB parts that block an 88.90 mm square mezzanine.

| Part | Plan (board mm) | Height | Source |
|---|---|---|---|
| J-BL, J-FC, J-BT (TB005-762) | x 3.28-17.48, y 7.88-87.88 | 21.70 mm | `TB005-762_CUI.pdf` p.2 |
| J-NTC (691411410002) | x 3.55-16.25, y 52.91-67.35 | 13.90 mm | Würth DS rev 001.004 p.1 |
| J1, J2 (87606-324LF) with tap pins | x 83.06-88.64 / 105.92-111.50, y 31.29-93.17 | unknown | `TODO(measure)` |
| U$1 Teensy 4.1 | x 88.39-106.17, y 31.50-93.73 | unknown | `TODO(measure)` |

The free x-span between the terminal-block rear faces (x 17.48) and J1 (x 83.06) is 65.58 mm, 23.32 mm short of the EVM.
J1 and the Teensy occupy y 31.29-93.73, so only 4.32 mm (high side) or 31.29 mm (low side) of MB depth stays uncovered.
A grid search (0.5 mm steps) finds that at most 10.4 % of the EVM plan can lie over the MB without covering one of the parts
in Table 2. That placement (x -5.9-83.0, y 88.1-177.0) is already an EVM beside the MB.

A mezzanine over J1/J2 must clear the receptacle height h_J1 plus the inserted tap pin. A TSW-101-07 pin leaves its 2.54 mm
body and its 2.54 mm tail above the receptacle when the 5.84 mm post is inserted (Samtec F-226, `mb_mechanical.md` Table 7).
The EVM top would then sit at h_J1 + 5.08 + 0.5 (clearance) + t_EVM (1.6 mm ASSUMED) + 13.0 mm (ED120 blocks, On-Shore
ED120/XDS) = h_J1 + 20.2 mm. The only recorded lid evidence is >= 21.70 mm (the TB005 blocks), so the mezzanine exceeds it
for any h_J1 above 1.5 mm. The mezzanine would also cover the Teensy USB and SD access and the J1/J2 tap field, and the EVM
has no mounting holes to carry it (`evm_geometry.md` section 3). The option is rejected.

### 2.2 Edge-reaching extensions other than the +y ring

Table 3 lists the other ways to bring the CR to an MB edge.

Table 3. Edge-reaching options not chosen.

| Option | Reason |
|---|---|
| Full-width CR to the +y edge over L-FC (x 17.70-48.70, y 67.14-98.04) | Needs >= 6.0 mm of header body over L-FC (5.0 mm, `TODO(verify: Eaton ELX1488)`), i.e. a DW stacker (non-standard, non-returnable, Samtec F-226) or a captured spacer; covers L-FC, so the inductor heat enters the CR. The ring reaches the same edge on the standard 2.54 mm body |
| -y edge | Covers BAL pad 8 (T22, PM11), RB1A, CBL2 and the PM4 step 1b thermocouple exit, and crosses L-BT (5.0 mm) and VSW-BT (`mb_mechanical.md` 4.3) |
| +x edge | The edge is 82.4 mm away behind J1, the Teensy and J2 (Table 2) |
| -x edge | The 21.70 mm terminal blocks and their -x wire entries (`mb_mechanical.md` section 3); J-BL must stay pluggable |

## 3. Q1: CR outline, header stack-up and overhang support

### 3.1 Outline

The r7 CR is the r6 footprint plus five regions. Table 4 gives them; the union is one board with an internal cut-out
(window) around L-FC.

Table 4. r7 CR outline regions (board mm).

| Region | x | y | Area (mm²) | Function |
|---|---|---|---|---|
| A footprint (r6) | 17.70-48.70 | 34.14-67.14 | 1023.0 | header strips, eFuse cluster, comparators, taps, W1-W4 |
| B +y band | 17.70-48.70 | 67.14-76.51 | 290.5 | logic and decoupling moved off the footprint; root of the ring |
| C lane (right of L-FC) | 37.06-48.70 | 76.51-90.11 | 158.2 | ring arm; L3 routes from the footprint to the island (L2/L4 solid) |
| D strip (left of L-FC) | 17.70-20.55 | 76.51-90.11 | 38.8 | ring arm (closes the ring) |
| E head (MB +y edge) | 10.00-48.70 | 90.11-98.04 | 307.0 | feet, W-lead exit corridors, non-island parts |
| F tongue (off-board) | 10.00-48.70 | 98.04-110.04 | 464.4 | EIB island, E-pad row at its +y edge |

The outer boundary runs (17.70, 34.14) - (48.70, 34.14) - (48.70, 110.04) - (10.00, 110.04) - (10.00, 90.11) - (17.70,
90.11) - (17.70, 34.14). The window is the internal cut-out x 20.55-37.06, y 76.51-90.11 (16.51 x 13.60 mm), which is the
L-FC body (x 21.05-36.56, y 77.01-89.61) plus 0.5 mm per side. L-FC (5.0 mm) passes through the window when the CR is
lowered and stands 0.73 mm above the CR top. The head starts at x 10.00, 4.8 mm from the edge of the MB fixing hole at
(3.30, 94.74), drill 3.80 mm; the fixing hardware envelope is `TODO(measure: M2)`. The outline is 2280 mm² (+1257 mm² over
r6) with a 38.70 x 75.90 mm bounding box. Its asymmetry (window and head on one side only) shows a mirrored capture on the
1:1 print, so the r6 pin-11 chamfer is no longer the only mirror marker; the pin-11 silkscreen marker and the
`pin_identity_check.py` gate stay.

### 3.2 What lies under the extension

Table 5 lists the MB parts under each region and the air above them with the 2.54 mm body seated on the 0.125 mm sheet (CR
underside 2.665 mm above the MB top). The design criterion is >= 0.3 mm vertical clearance over the tallest MB part
(T-A-06).

Table 5. MB parts and copper under the extension (`.brd` via `mb_mech_calc.py`).

| Region | Parts (height, air) | Non-GND copper |
|---|---|---|
| B | OP-FC 1.75 (0.92), MDAC-FC 1.10 (1.56), RD2-FC, RINJ-FC, ROP1-FC, ROP2-FC 0.60 (2.06) | VDROOP-FC, N$7, N$8, 3V3, CS-MDAC-FC, MISO traces (0.254 mm); no power copper |
| C | C4A-FC, C4B-FC 1.35 (1.31), C3-FC 1.10 (1.56), REG-FC 1.00 (1.67), C2/C5/C6/CC-FC 0.85 (1.81), RC-FC, RD1-FC, RD2-FC, RINJ-FC, ROP2-FC 0.60 (2.06) | **VSW-FC pour 22.1 mm² (switch node)**, VOUT-FC pour 14.8 mm², VFB-FC, VCOMP-FC, EN-REG-FC traces |
| D | C1-FC 1.10 (1.56) | VFC pour 21.8 mm², VFC trace |
| E | C4A-FC, C4B-FC 1.35 (1.31), C2-FC 0.85 (1.81), R1-FC, R2-FC 0.60 (2.06) | VFC and FC-V traces, VOUT-FC pour 0.6 mm² |
| F | none (off-board) | none |

Every via is tented (`mlViaStopLimit` 9999 mil). The lane C sits directly over the FC boost switch node, so the CR L2 and L4
planes stay solid over it and no island copper, plated hole or tail is allowed in C. The extension covers the FC droop and
compensation parts (OP-FC, part of MDAC-FC, RD1/RD2/RINJ/ROP-FC, RC/CC/C6-FC) and REG-FC; rework of any of them needs the CR
removed (22 joints). The pending DMM measurement of the AD5443/OPA197 block (CLAUDE.md bench items) and any FC-channel
rework must therefore precede PM4 (section 8.3). An unrecorded OPA197 5 V bodge wire near OP-FC (`mb_mechanical.md` 2.2)
would reduce the 0.92 mm air: `TODO(measure: M3)`.

### 3.3 Header stack-up

The header stack-up is the r6 stack-up without change. Table 6 gives the dimensions (Samtec F-226 TSW -07 lead style, A 10.92
/ B 2.54 / C 5.84 mm, as quoted in `mb_mechanical.md` Table 7).

Table 6. Header stack-up (TSW-110-07-G-S, TSW-112-07-G-S, BOM line "CHG header pins").

| Item | Value |
|---|---|
| Body | 2.54 mm PBT, against the CR underside, seated on the 0.125 mm polyimide sheet |
| CR underside / CR top above the MB top | 2.665 mm / 4.265 mm (CR 1.6 mm ASSUMED, `TODO(verify: fab stack-up)`) |
| CR-side end (B 2.54 mm) above the CR top | 0.94 mm (fillet; PM4 requires >= 0.5 mm) |
| MB-side end (C 5.84 mm) below the MB | 4.12 mm before the PM4 step 4 cut to <= 1.0 mm |
| Stack top over the footprint | 4.265 mm + the tallest CR part (C102b 1210 ~2.5 mm, A.7) + the W-lead bends (`TODO(measure)`); the W5 fold (>= 8 mm above the CR, A.3) retires, so the r7 stack top is at or below the r6 stack top |

No spacer and no DW stacker is needed, because the ring keeps the CR off L-FC. Gate D-2 (the Ag105 standoff,
`detailed_design_IC1.md` 15.2) therefore only certifies the envelope; it does not set a new header height. The lid profile
over the extension and the tongue is unrecorded (`TODO(measure: M2)`).

### 3.4 Overhang support

The extension tip is 45.6 mm beyond the pin-11 row (y 64.48 to 110.04). Two bonded feet support the head:

- positions (14.0, 94.0) and (38.0, 95.0); both qualify as a foot (4 x 4 mm, no part body + 0.25 mm, no via) and as a drill
  spot (no non-GND copper within 3.0 mm on L1 or L16), so a foot never rests on power copper;
- height 2.665 mm nominal, cut to the measured gap after seating (`TODO(measure)`), from a TSW body segment with the pins
  pulled (PBT) or a nylon block;
- bond: the BOM neutral-cure silicone RTV on both faces, applied with the CR seated, so the joint carries no preload; the bond
  strength on solder mask is `TODO(verify: RTV datasheet)`;
- fallback, only if M5 or T-F-20 shows a debond: a 2.5 mm NPTH at the same GND-only spots and an M2 nylon screw through a
  2.665 mm spacer (a new MB modification, PM12).

Table 7 gives the order-of-magnitude mechanics from a beam finite-element model along y (clamped at the pin-11 row; widths
31.0 mm (B), 14.49 mm (ring arms), 38.7 mm (head and tongue); E = 20 GPa, 1.6 mm, ASSUMED; areal mass 0.6-0.8 g/cm²,
ASSUMED; 30 g shock ASSUMED, as `mb_pinload.py`).

Table 7. Pin load and first bending mode (ORDER OF MAGNITUDE).

| Case | f1 unpropped | f1 with the feet | Worst pin load at 30 g | Feet reaction at 30 g |
|---|---|---|---|---|
| t = 12 mm (chosen), part-mass factor 1-2 | 233-330 Hz | 1158-1638 Hz | 1.06-1.46 N without feet; 0.14-0.23 N with feet | <= 2.63 N for both feet |
| t = 8 mm | 287-406 Hz | 1740-2461 Hz | - | - |
| r6 CR alone (`mb_mechanical.md` Table 6) | - | - | 0.067-0.134 N | - |

Pin strength does not decide the support: the worst unsupported load is about 1 % of the ~141 N section capacity of a 0.64 mm
pin at an assumed 345 MPa yield. The feet raise f1 by a factor of about 5 and cut the worst pin load by a factor of 6-8, to
1.5-2.5 times the r6 value at the same main-CR mass (0.140-0.165 N against 0.067 N at 5 g; 0.207-0.232 N against 0.134 N at
10 g). Whether 1.2-1.6 kHz clears the vehicle excitation is decided by M5.

### 3.5 Measurements before the outline is frozen

The operator makes these measurements before PM0 (they extend `mb_mechanical.md` section 8):

1. **M2 (decides the approach):** chassis room beside the MB +y edge for the 12 mm tongue, a 5 mm gap and the EVM plan x
   -26.0-62.9, y 115.0-203.9 (or x -0.5-88.4 in the constrained case of 4.2), plus the J8 mate to x -32.2 and its housing,
   the J1 wire bend above y 201, and >= 19.7 mm above the bracket plate (bumpon 5.08 + t_EVM + 13.0 mm blocks); the lid
   clearance over regions B-F; the MB fixing hardware at (3.30, 94.74); whether the MB and the EVM bracket can share one
   rigid sub-plate.
2. **M1 (D-2):** the Ag105 standoff, module top height and mass, as gate D-2 requires (envelope only).
3. **M3:** caliper heights of OP-FC (with any OPA197 bodge wire), C4A/C4B-FC, L-FC and the head gap after a dry seat; the
   EVM thickness, mass and every part within 2 mm of its top and bottom edges (clamp lips).
4. **M6 (new):** the L-FC body position against the CHG pin holes (+-0.1 mm), which sets the 0.5 mm window clearance.
5. **M5:** an accelerometer log at the MB +y edge in a representative run (spectrum to 3 kHz) and the MB-to-chassis
   relative motion at that edge, which sizes the E-lead service loop (10 mm ASSUMED).
6. **M4:** the LM1084 survey of `mb_mechanical.md` 5.4, extended with REG-FC and C4A-FC under a CR mock-up (T-F-19).

## 4. Q2: EVM placement and leads

### 4.1 EVM mount

The EVM has no mounting holes, and a hole at a bumpon centre cuts the ground pour; the (81.28, 81.28) zone overlaps TP49, the
E8 landing (`evm_geometry.md` sections 3 and 9). The proposed mount is therefore:

- a non-conductive bracket plate on the chassis (`TODO(verify: chassis fixing points, M2)`);
- the stock bumpons H1-H4 (3M SJ-5303, 5.08 mm) kept on the EVM as compliant feet on the plate;
- two nylon clamp bars with 0.5 mm silicone pads that press on 2 mm lips along the EVM top and bottom edges (EVM frame),
  notched at J8 (x 14.30-24.30); the parts within 2 mm of those edges are `TODO(verify: on the received EVM)`;
- no fastener, adhesive or bracket part that bonds EVM copper to the CR plane or the chassis (merge condition 7; T-A-08).

The EVM and the CR are therefore on two bodies (MB mounts and bracket), so every E-lead needs a strain relief at the tongue
and a service loop, and T-F-18 applies (merge condition 7).

### 4.2 Placement

The script places the EVM beside the MB +y edge in each of the four orientations and optimises the offset and the E-pad row
position. The Teensy USB end (board y 93.73, x 93.47-101.09, TEENSY41 package) keeps the EVM at x <= 88.5. Table 8 gives the
result for a 5 mm gap and no height difference.

Table 8. EVM orientation against straight lead lengths (mm, tongue t = 12 mm).

| EVM edge facing the MB | E8/E3/E4/E2 | E7 | E6/E5/E1 | W1/W2 (straight) | W3/W4 | W7 (straight) |
|---|---|---|---|---|---|---|
| **right (J5, TP33/TP49)** | **13/16/20/24** | **29** | **48/50/64** | 136/136 | **80/68** | 137 |
| top | 38/41/36/33 | 36 | 70/77/90 | 105/102 | 136/116 | 146 |
| bottom | 85/70/71/71 | 66 | 33/26/24 | 119/122 | 97/97 | 77 |
| left | 95/87/82/78 | 72 | 74/81/78 | 61/61 | 157/145 | 92 |

The right-edge orientation gives the shortest length-critical leads and the shortest battery pair; the cost is J1 on the far
side, so W1/W2 route around the EVM (4.4). In the chosen placement (offset X0 = -26.0) the EVM outline is x -26.00-62.90,
y 115.04-203.94; it overhangs the MB -x edge line by 26 mm. J5 faces the MB (wire face at y 117.45), J1 faces away (y
201.34), J8 mates from -x (pin tips at x -32.24). The EVM power stage (L2 at board x 23.8-30.6, y 152.9-160.3; U1 x
14.0-18.1, y 154.4-158.5) is >= 85 mm from the CR footprint, which holds the comparators (merge condition 10). The EVM
outline (y >= 115.04) is 60.5 mm from REG-5V (y <= 54.51), which meets the r6 ">= 20 mm from the LM1084 side" rule. If M2 confines the EVM to the MB x-range (X0 >= -0.5), the leads become E8/
E3/E4/E2 34/26/32/36, E7 40, E6/E5/E1 41/40/56 mm, all still in the G1 range.

### 4.3 E-pad row and E-lead lengths

The E-pad row runs along the tongue edge at y 108.79 with 1.0 mm plated holes at 2.54 mm pitch (A.9; the tongue is
off-board, so no tail faces MB copper). Its order, from +x to -x, is E8 (x 47.19), -, E3 (42.11), E4 (39.57), E2 (37.03), -,
E7 (31.95), -, E6 (26.87), E5 (24.33), -, E1 (19.25). The A.9 isolation pairs hold: E1 and E7 have an empty position on
each side, E8-E3 and E6-E7 are separated by an empty position, and the adjacent pairs (E3-E4, E4-E2, E6-E5) are same-node
pairs as in r6. The E1/E5/E6 block moves to the -x end because JP12, TP36 and JP17 lie at the -x side of the EVM in this
orientation; E1 is now two pitches from E5 (r6: two) and seven from E2 (r6: four).

Table 9 gives the leads. "r3 rule" is the round-3 rule (straight 3-D distance x 1.25, rounded up to 5 mm). The proposed
"r7 rule" is 1.25 x the horizontal straight distance + |dz| + a 10 mm service loop, rounded up to 5 mm. The r7 rule is
better justified for this geometry: each lead crosses a body-to-body gap, so it must absorb the height difference dz
(`TODO(measure: M2)`, 10 mm ASSUMED) and the relative motion (10 mm loop ASSUMED, M5).

Table 9. E-leads, EVM right edge facing the MB, X0 = -26.0, gap 5 mm (straight distances by the script).

| Lead | EVM point (board x, y) | Straight, dz 0 | r3 max, dz 0 | r7 max, dz 10 | r6 straight / max | Criterion limit (merge note Table 9) |
|---|---|---|---|---|---|---|
| E8 | TP49 (53.12, 120.50) | 13.1 | 20 | **40** | 13.6 / 20 | return of E3/E4/E6 |
| E3 | TP33 (37.50, 123.93) | 15.8 | 20 | **40** | 16.7 / 25 | 92 mm untwisted, s 5 mm, class B at 10 mm |
| E4 | JP21 pin 1, lower post (38.77, 128.63) | 19.9 | 25 | **45** | 20.6 / 30 | 59 mm untwisted; none within 2 mm of E8 |
| E2 | JP14 pin 2 (38.77, 132.57) | 23.8 | 30 | **50** | 24.6 / 35 | none (48.7 kOhm feed) |
| E7 | TP38 (33.69, 137.90) | 29.2 | 40 | **60** | 29.9 / 40 | none (static) |
| E6 | JP17 pin 1 (0.80, 149.33) | 48.2 | 65 | **85** | 45.4 / 60 | 196 mm untwisted |
| E5 | TP36 (-6.29, 148.07) | 49.8 | 65 | **85** | 49.1 / 65 | none (static) |
| E1 | JP12 pin 1 (-12.26, 164.57) | 64.1 | 85 | **105** | 69.0 / 90 | none with R276 10 ohm (E1 + C205 resonance ~1.3-1.5 MHz at 85-105 mm) |

The r6 straight values are the vector values of `evm_geometry.md` Table 6. Every r7 maximum lies inside its criterion limit,
so the r7 maxima are the build maxima that T-A-02 and T-A-06 check. With a 15 mm gap and dz 10 mm the r7 maxima rise by 10-15
mm (E4 60, E1 115 mm). E4 then exceeds its 59 mm untwisted limit by 1 mm, so the rule "E4 within 2 mm of E8" becomes
mandatory, not only recommended. JP21 pin 1 is the lower, square post at EVM (75.312, 64.769); the A.5
pixel coordinate names the AGND post (`evm_geometry.md` 7.2).

The dressing rules of merge condition 3 apply: E3 and E4 run within 2 mm of E8; E1 and E7 run apart from the ILIM group and
from each other; no E-lead runs with a W pair. The leads leave the tongue in +y and never pass over the MB. The EVM dipole
pickup stays <= 7.3 mV (merge note 6.2); the L-FC dipole bound at the row (25.5 mm from the L-FC centre, 7.27 A/us = 16.0
V / 2.2 uH, effective area 5-50 mm² ASSUMED) is 0.1-0.9 mV for a 5 mm pair, against the 48 mV E4 budget. E1, E5 and E6 are
routed over the vacated J3 footprint (board x 15.65-25.72, y 117.45-126.45), clear of the 13.0 mm J5 body (x -4.23-10.77),
so J3 is desoldered (EM7 change). They cross the W3/W4 pair near J5 at right angles (class A, E6 limit 1957 mm).

### 4.4 W-lead routes and lengths

The straight line from W1/W2 and W7 to their EVM terminals passes through the EVM, so these leads are given as routed
polylines. Table 10 gives the routes; the build maximum adds dz 10 mm and the 10 mm loop.

Table 10. W leads (routed in plan; r6 maximum 0.30 m each).

| Lead | Route (board mm) | Plan length | Build max |
|---|---|---|---|
| W1 -> J1 pin 2 | (30.3, 61.2) - (45.0, 92.0) - (52.0, 97.0) - (66.9, 115.0) - (66.9, 206.9) - (24.8, 206.9) - J1 face y 201.34 | 205.7 | 230 |
| W2 -> J1 pin 1 | from (27.7, 61.2), same corridor, to x 29.9 | 201.9 | 225 |
| W3 -> J5 pin 1 | (24.3, 45.4) - (19.1, 70.0) - (19.1, 90.0) - (9.0, 97.0) - J5 face (-1.8, 117.45) | 80.6 | 105 |
| W4 -> J5 pin 3 | from (24.3, 55.6), same corridor, to x 8.35 | 68.1 | 90 |
| W7 -> J8 pins 2/3 | (29.0, 57.5) - W3 corridor - (-34.2, 125.0) - (-34.2, 185.9) - pin tips x -32.2 | 162.6 | 185 |
| W6 -> J7 pin 1 (NTC only) | (33.0, 57.5) - W3 corridor - (-26.2, 130.0) - J7 face x -23.2 | 113.3 | 135 |

W3/W4/W6/W7 leave the CR left of the tongue (x < 10) and W1/W2 right of it (x > 48.7), so no W pair crosses the island. The
W1/W2 corridor passes over the lane and the head (not over the island). The KK 254 housing body beyond the J8 pin tips is
`TODO(verify: Molex 22-01-3047 drawing)`. With W1 at 0.230 m and W2 at 0.225 m the H.11 input pair falls from 20.0 to 15.2
mOhm (20 AWG 33.3 mOhm/m, the value H.11 implies; 65 -> 49 mW at 1.80 A), R_PATH_RG (H.19) from 0.117-0.193 to 0.112-0.188
ohm, and the H.7 warm-budget numerator rises by 5.3 mV. The battery pair falls from 12.5 to 4.1 mOhm (18 AWG 20.9 mOhm/m),
129 -> 42 mW at 3.21 A (calculation section 12; section 9 of the output uses straight lines and is superseded). The
shorter W1/W2 lead shortens the H.5 hard-short quarter period further below 1 us; the H.5 conclusion is unchanged, but
T-C-04 must use the r7 lead.

## 5. Q3: EIB merge

The EIB merges onto the tongue. The geometry is G1 of `work/eib_merge_failsafe.md` (CR edge to EVM pins 13-64 mm, every lead
within its criterion limit), and all ten G1 conditions are met as follows:

1. **Island:** the tongue (x 10.00-48.70, y 98.04-110.04) carries the EIB section on its own AGND island on all four layers,
   joined to EVM AGND by E8 only and to the CR plane by R273 10 ohm only. The island is off-board, so no MB copper lies under
   it; its edge is 10.0 mm from REG-FC, 10.5 mm from the VSW-FC pour, 8.4 mm from L-FC and 5.3 mm from C4A-FC. U203/U204,
   R258-R263 and the E3/E4/E6/E8 traces sit at y >= 103.0, which keeps them >= 10 mm from every FC-boost part.
2. **Pad row:** as 4.3 (order changed only by moving the E1/E5/E6 block; every A.9 isolation pair kept).
3. **Dressing:** as 4.3; the logic nets reach the island on L3 through the lane, between solid L2/L4 planes.
4. **Parts kept:** EM3, R256/C252 at the JP21 posts, R272/R272b on the EVM, R274 on the merged rail, R275 at the E7 pad,
   R258 10.0 kOhm, R267-R270; no /CE pull-up on the CR.
5. **Parts deleted:** W5, J101, J201, R176, R177, R130/R131A/R131B/R132; R264/R265 optional (kept fitted here).
6. **E1 damping:** R276 10.0 ohm 1 % 0603 in series with E1 at the CR pad (mandatory: the E1 build maximum of 85-105 mm
   puts the E1 + C205 resonance near the 1.5 MHz switching frequency, merge note 3.4).
7. **Mechanics:** two bodies, so an RTV bead over the E-lead jackets at the tongue, the service loop and T-F-18.
8. **Thermal:** the island is 43.5 mm from the LM1084 5V pour (estimated rise <= 6.3 C at 20 mm, `mb_mechanical.md` Table 4).
9. **Area:** the island needs 246 mm² of courtyard (198 parts + 48 E pads) / 0.70 = 351 mm²; the tongue gives 413 mm² of
   strict usable area at t = 12 mm (264 mm² at t = 8 mm, 212 mm² on the head alone). The minimum tongue is about 10.3 mm
   (linear interpolation). The E-pad row (y 108.79) is 19.2 mm from L-FC, 20.7 mm from REG-FC and 16.1 mm from C4A-FC.
10. **CR analog front ends:** the EVM power stage is >= 85 mm from U102-U104 and the T8/T9 landing.

Table 11 gives the status of each round-3 fail-safe argument under this placement; it follows the G1 column of the merge note
and adds only the placement-specific change.

Table 11. EIB fail-safe arguments under the r7 merge.

| Argument | Status | Change or reason |
|---|---|---|
| r1-2 two series switches, "drivers at the EVM pins" | holds with a stated change | becomes "switches and drivers together on the island; every E-lead open leaves HIZ" (merge note Table 2) |
| r2 evm-jp14-feed-joint-floating (EM3) | holds as is | EVM-side |
| /CE driver U201 1Y and R272/R272b | holds as is | no /CE pull-up on the CR |
| far-end senses U203 (E4) / U204 (E6), separate joints, lead-off reads dangerous | holds as is | routing rule met (no switched conductor within 10 mm; L-FC <= 0.9 mV) |
| REGN supply E1, C205 | holds with a stated change | R276 10 ohm; E1 isolation on the pad row |
| ground: E8 single DC ground, R273, A.6 graph | holds with a stated change | island + R273 replace the four ribbon GND conductors |
| W5 ribbon adjacent-short list, J101 keying | retires | no ribbon |
| R264/R265 470 ohm | holds with a stated change | optional; R125/R148 limit a tap short to <= 3.3 mA |
| 3V3 feed R176/R177, bleed R274 | holds with a stated change | R176/R177 retire; R175 covers the merged rail (48.5 mA); R274 stays |
| H.13 release-glitch filter | holds as is | C252 at the JP21 posts; leads add <= 2 pF |
| B.6 rows (E2/E3/E4/E5/E6 lead off, Q201/Q203, R272/R272b) | hold, as merge note Table 7 | "ribbon n open" becomes the corresponding CR trace with its pull-down |
| B.6 "3V3 lost on the EIB" | retires | folds into B.7 "CR 3V3 lost (T6 open)" |
| B.6 "ribbon conductor short" | retires | replaced by the pad-row bridge list |
| new row: E1 lead off | holds (new) | HIZ, permit stuck LOW |

No argument needs re-proof. The G2 re-proof items of the merge note (shielded bundles, EVM-end parts, IN+ filters) do not
apply, because no E-lead leaves the 13-64 mm G1 range.

## 6. Q4: layer count, placement sides and stack-up

The CR stays 4-layer and becomes single-sided. Table 12 gives the area basis (strict usable top area by raster, method check
730 mm² for the r6 footprint against 732 mm² in `stackup_area.py`; demand from the round-4 booking: merged CR + EIB 1398 mm²
minus 26.1 mm² of deleted R176/R177 and R130-R132 = 1372 mm²).

Table 12. Utilisation against the outline.

| Outline | Strict usable top | Single-sided U (no DNP) | Double-sided top U (r3 bottom set 435 mm²) |
|---|---|---|---|
| r6 footprint | 730 | 188 % (176 %) | 128 % |
| V1 footprint + B | 1013 | 135 % (127 %) | 92 % |
| V2 ring + head, no tongue | 1412 | 97 % (91 %) | 66 % |
| V3a ring + head + 8 mm tongue | 1733 | 79 % (74 %) | 54 % |
| **V3 ring + head + 12 mm tongue (chosen)** | **1882** | **73 % (68 %)** | 50 % |

The decision rests on three points:

1. **Area:** V3 meets U4 = 0.75 single-sided with every footprint kept (73 %); 2-layer single-sided would need +1664 mm² for the
   merged board against the +1257 mm² available (stackup note 4).
2. **Comparator versus power-pour separation:** the comparators (U102-U104, U115, U119-U121) stay in the footprint interior,
   >= 21 mm from L-FC (y 77.01) and outside the IN/OUT strips; the passives that r6 put on the bottom move to the top beside
   their ICs, and the logic gates and monostables move into band B and the head, behind L2/L4. A 4-layer board keeps the
   0.2 mm L1-L2 loop basis of H.21(k) (C102b and D103 loops <= 2 nH; 2-layer 4-7 times higher, 46-53 times the coupling at
   equal distance, stackup note 5) and gives the lane over VSW-FC a solid plane under every trace.
3. **3.21 A battery copper:** W3/W4 stay at (24.3, 45.4) and (24.3, 55.6) with >= 2.5 mm L1 pours (2 oz 7.7 A, 1 oz 4.6 A at
   10 C rise, H.22(c)); the battery current never enters the extension, and L4 is a continuous return plane under it.

Table 13 gives the stack-up (stackup note 7.2, unchanged; the island and the single-sided rules added).

Table 13. r7 CR stack-up (1.6 mm, symmetric; `TODO(verify: chosen fab 1.6 mm 4-layer table)`).

| Layer | Copper | Dielectric below | Content |
|---|---|---|---|
| L1 | 2 oz (1 oz allowed by the PM0 DFM check at the RGE 0.5 mm pitch) | prepreg 0.2 mm | every part; power pours VCHGIN, VCHGOUT, VCHG, GND star (>= 2.5 mm) |
| L2 | 1 oz | core ~1.0-1.1 mm | solid GND plane; cleared only under the island (island AGND pour there) |
| L3 | 1 oz | prepreg 0.2 mm | signals (I2C, TS, taps, readbacks, logic, the island nets through the lane) |
| L4 | 2 oz (or 1 oz) | - | continuous GND pour stitched to L2 at <= 5 mm, antipads only at the 22 header pins and W1-W4; island AGND pour on the tongue |

Fallbacks: with an 8 mm tongue the board is single-sided only with the 87 mm² of DNP option footprints removed (74 %), and
the island does not fit; with no tongue the merge is not available (section 11).

## 7. Q5: round-3 constraints

Table 14 lists each round-3 constraint with its r7 status. A constraint stays wherever the CR still sits over MB power copper
(VBT x 34.04-35.56, the VBT and VCHG pours and VCHG-IN under the footprint, A.7) or still carries a through-hole tail there.

Table 14. Round-3 constraints under r7.

| Constraint | r7 status | Reason |
|---|---|---|
| Footprint confinement (31 x 33 mm) | retires | operator change; the ring reaches the +y edge on the 2.54 mm body |
| Double-sided build, passives-only bottom (<= 1.0 mm) | retires | single-sided at 73 % (section 6); the CR bottom carries no part |
| Bottom keep-out x 24.5-36.0, y 48.5-53.5 | retires | it constrained bottom parts only |
| MB power-copper shadow (+1 mm) for bottom parts | retires | no bottom parts; the CR bottom is a masked L4 GND pour |
| 84 % area budget (H.18/H.22(k) "top ~678 of ~881 mm²") | retires | replaced by the strict-basis U4 0.75 rule (Table 12) |
| Polyimide sheet (0.125 mm, CR outline + 1 mm) | stays, footprint only (x 16.70-49.70, y 33.14-68.14, as r6) | the W1-W4 tails (W3 over the MB VCHG pour) and the 22 header bodies still sit over MB power copper; the extension has no tail and >= 0.92 mm air over masked parts, so the sheet is not extended |
| Flush-cut tails <= 0.5 mm (W1-W4) and MB-side cut <= 1.0 mm | stays | W1-W4 still sit over the MB VCHG pour and GND near VBT; E-pad tails are off-board and need no cut |
| Top-side SMT tap pads F01-F24 (no holes) | stays | the tap field (y 35.05-41.63) still lies over the MB VBT and VCHG-IN copper; the +y extension gives no tap-length gain |
| C102b on L3 over L4 | relaxed | band B frees room above the OUT strip, so C102b may sit pin-adjacent on L1; the <= 2 nH rule stays |
| +x pocket bottom fallback (0603 R103/R104) | retires | no bottom side |
| W3/W4 at the pin columns, A.6 star, 2 nH loops, U101 at pad 10 | stays | electrical rules independent of the outline |
| Air over MB parts (T-A-06: >= 0.3 mm) | stays, now over the FC parts | OP-FC 0.92 mm is the minimum (M3) |
| New: extension rules | added | L2/L4 solid under B, C, D and E; no island copper, plated hole or tail over the MB (the island and the E-pad holes stay on the off-board tongue); courtyards >= 0.5 mm from the window edge as from any outline edge; U203/U204 and the E3/E4/E6/E8 traces at y >= 103.0 |

## 8. Q6: EVM and MB modifications

### 8.1 Study M1-M11 against design EM1-EM25

Table 15 maps the study list (`docs/charger_replacement_evaluation_2026-11-05.md`, EVM modification table) onto the design
list and gives the r7 effect.

Table 15. Study modifications, design modifications and the r7 effect.

| Study | Design | r7 effect |
|---|---|---|
| M1 remove JP17 | EM1 (+ JP17 pin 2 removed) | unchanged |
| M2 /CE NMOS stage, M2b R42 from REGN | EM2 (R42 removed, R272/R272b with links L1/L2) + island U201 ch1 | unchanged (R272/R272b stay on the EVM, merge condition 4) |
| M3 ILIM stage | EM3 (R21 0 ohm, JP14/JP13 pin 1 and R20 removed), EM4 (R23 49.9k), EM5 (R256/C252 at JP21) + island Q201-Q203 | unchanged; mandatory |
| M4 R39/R40, JP32 | EM6, EM8 | unchanged |
| M5 JP3/JP4, JP1/JP2, J2 | EM10, EM11, EM7 (J2) | EM7 changes: J3 desoldered (not capped), because E1/E5/E6 pass over its footprint; J2 removed, J4 removed or capped as r6 |
| M6 JP5, JP8, JP9 | EM12, EM13, EM9 | unchanged |
| M7 input caps | EM14 (EVM), PM2 (MB) | unchanged |
| M8 VBT -> VCHG keep-alive | B.5 option, PM7 / T18 (not an EM) | unchanged |
| M9 TS | EM18 | unchanged (W6 135 mm if fitted) |
| M10 JP24 | EM19 | unchanged |
| M11 JP6/JP10/JP11 | EM16 | unchanged |
| - | EM15, EM17, EM20, EM21, EM22, EM24, EM25 | unchanged |
| - | EM23 bumpons removed, M3 standoffs in corner holes | **changes**: the EVM has no corner holes; H1-H4 stay as compliant feet in the clamp bracket (4.1) |

No EVM modification becomes unnecessary. The electrical modifications act at the EVM pins wherever the EIB sits, and the merge
keeps every one of them (merge condition 4).

### 8.2 MB modifications PM0-PM11

No MB modification becomes unnecessary. Table 16 lists the changes.

Table 16. MB modifications under r7.

| PM | r7 effect |
|---|---|
| PM0 | one board: capture the r7 CR (ring, window, head, tongue, island) single-sided; no EIB capture |
| PM1-PM3, PM5, PM7-PM11 | unchanged. PM9 stays: with 10 kOhm pull-ups 300 ns allows only 35 pF (300 ns / (0.8473 x 10 kOhm), the H.16 method), and a W7 shortened to <= 0.185 m removes only the W7 share of the 75 pF H.16 estimate; T-C-06 measures tr |
| PM4 | sheet unchanged (footprint + 1 mm); the CR is lowered over L-FC through the window; new step 3b: after the 22 MB joints, bond the two head feet with RTV at (14.0, 94.0) and (38.0, 95.0); E-leads fitted to the tongue after seating; step 1b thermocouple exit at y ~34 unchanged |
| PM6 | unchanged (tap destinations and the F01-F24 field do not move) |
| PM12 (new, fallback only) | two 2.5 mm NPTH at the foot spots with M2 nylon screws, only if T-F-20 fails |

### 8.3 Work that must precede PM4

The CR covers the FC droop amplifier and MDAC (OP-FC, part of MDAC-FC), the droop resistors, REG-FC and its compensation, and
C4A/C4B-FC. The pending DMM measurement of the AD5443/OPA197 block, the OP-FC bodge-wire height (M3) and any FC-channel
rework are completed before PM4 (new T-A-09).

## 9. BOM and cost delta

Table 17 lists the BOM changes against design section E.

Table 17. BOM delta.

| Line | r6 | r7 |
|---|---|---|
| CR PCB | 5 x 31.0 x 33.0 mm, 4-layer, allowance USD 70 | 5 x r7 outline (38.70 x 75.90 mm bounding box, 2280 mm², internal window 16.51 x 13.60 mm), 4-layer, 1.6 mm, single-sided assembly; area x 2.23; allowance `TODO(verify: fab quote)` |
| EIB PCB | 5 x 36 x 24 mm (in the CR panel) | removed |
| J101, J201, W5 key plugs | 1+1, 1+1, 2+2 | removed |
| W5 cable assembly | 1+1, allowance USD 25 | removed |
| R176, R177 (200 ohm) | 2+1 | removed |
| R130, R131A, R131B, R132 (100 ohm) | 4 | removed (merge note condition 5) |
| R264, R265 (470 ohm) | 2 | optional (kept fitted) |
| R276 (new) | - | 1 (+1) 10.0 ohm 1 % 0603, CRCW060310R0FKEA (as R273), E1 series at the CR pad |
| Head feet (new) | - | 2 (+2) blocks 4 x 4 x 2.665 mm (cut to the measured gap), PBT from a spare TSW body or nylon; RTV from the existing "Adhesive" line |
| EVM bracket (new) | - | 1 non-conductive plate + 2 nylon clamp bars with 0.5 mm silicone pads + nylon screws; no MPN, allowance `TODO(verify)` |
| Hardware | M3 x 10 mm nylon standoffs x 6 | removed (the EVM has no holes; no EIB) |
| Wire | 20 AWG and 18 AWG 1 m each | unchanged quantities (W1/W2 need <= 0.46 m, W3/W4 <= 0.20 m) |
| TSW-110-07-G-S, TSW-112-07-G-S, polyimide sheet, 28 AWG Kynar | as r6 | unchanged |

Cost: the EVMs stay USD 312.90 (verified TI price, design E). The W5 allowance (USD 25) leaves; J101, J201, the plugs, six
resistors and six standoffs leave the r6 lump allowance (USD 190-225, not itemised). The CR PCB area grows by a factor of
2.23 and the bracket is new; both are `TODO(verify: quote)`. The net change is therefore not determined to better than the
CR re-quote; no verified price is claimed.

## 10. Test-registry delta

### 10.1 Retired

- **T-C-13** (ribbon orientation and first power); its R275 metering and 20 mA-limited first power move to T-A-08.
- The ribbon parts of **T-C-05**, **T-C-07**, **T-A-05** and **T-A-06** (merge note 9.2/9.3), and the T-A-02 step "M3 rod
  through a corner hole" with its M2.5 fallback.
- Calculation rows **H.18b** and the **H.20** ribbon rows; **J.2** items 22 (EIB layout), 31 (1.27 mm ribbon) and the EIB-rail
  part of item 30.

### 10.2 Changed

- **T-A-02:** E-leads against the r7 maxima of Table 9 (E8 40, E3 40, E4 45, E2 50, E7 60, E6 85, E5 85, E1 105 mm at dz 10 mm;
  recomputed at the measured dz); JP21 pin 1 is the lower post; dressing rules of 4.3.
- **T-A-05:** remove J101/J201/W5/plugs/R176/R177/R130-R132; add R276, the foot material and the bracket material.
- **T-A-06:** placement DRC on the r7 outline (window clearance 0.5 mm, no bottom part, island netlist: R273 the only
  island-to-plane connection); 1:1 print over the MB including the window fit over L-FC; air over OP-FC/C4A-FC by calipers
  (>= 0.3 mm); E-pad order and isolation set; remove the EIB outline, J101 and mated-socket items.
- **T-C-04:** OUT excursion with the r7 W1/W2 lead (<= 0.23 m) instead of 0.30 m.
- **T-C-05, T-C-07, T-D-11, T-F-11:** as merge note 9.2 ("CR EIB section"; island; merged rail; R273/E8 currents).
- **T-F-12:** E-lead strain relief and pull check at the tongue edge; head-foot bond inspection; W corridors clear of the
  island.
- **T-F-13:** R_PATH_RG expected 0.112-0.188 ohm with the shorter W1/W2.
- **T-B-16:** EVM thermal in its bracket position (bumpons kept, no new cooling).

### 10.3 New

- **T-A-08** (merge note): island-to-plane = R273 10 ohm +-1 %, E8 to TP49 < 0.5 ohm, EVM copper to the CR plane and the
  chassis through the bracket > 1 MOhm, bare-tongue isolation pairs > 1 MOhm, E7 pad to TP38 = 1.00 kOhm, first power at 3.3 V /
  20 mA.
- **T-A-09 (mechanical fit and FC-access gate, before PM0 and PM4):** M2, M3 and M6 recorded; dry seat of a bare CR with L-FC
  in the window (>= 0.3 mm plan clearance all round); head gap measured for the feet; the AD5443/OPA197 DMM block measurement
  and any FC-channel rework done. Fail: re-place the window or drop strip D (J shape); no tongue room -> section 11 fallback.
- **T-C-16** (merge note): pickup at TP33, U203/U204 IN+ and /CE with the charger converting, now also with the MB FC boost at
  the window cap (1.20 A) because the island edge is 10.0 mm from REG-FC.
- **T-F-18** (merge note): E-lead integrity on the vehicle (LA on pins 7/33, continuity on E1-E8); applies because the EVM
  and the CR are on two bodies.
- **T-F-19 (FC boost under the lane):** REG-FC case, C4A-FC and L-FC temperature with the CR fitted and with a bare MB, FC
  channel at 1.20 A for 30 min, closed enclosure. Pass: rise increase <= 5 C (`TODO(calibrate)`). Fail: open the lane over
  REG-FC (slot) or move the lane.
- **T-F-20 (head support on the vehicle):** accelerometer on the head and on the MB edge (M5), road run; feet inspected after.
  Pass: no debond, head response below 2x the MB-edge input at every frequency up to 3 kHz (`TODO(calibrate)`). Fail: PM12.

## 11. Risks and fallbacks

The approach carries the following risks, ranked:

1. **Room beside the MB +y edge (M2) is unrecorded.** Without room for the 12 mm tongue and the EVM bracket, the merge is not
   available: on the head alone the island is 140 mm² short and 2.6 mm from the VSW-FC pour. The fallback is the r6 split
   (EIB at the EVM, W5 ribbon); the extension is then chosen for area only, outside this proposal.
2. **FC-channel access.** The CR covers the FC droop amplifier, the droop resistors, REG-FC and its compensation; rework or
   calibration there needs the 22 joints desoldered.
3. **FC boost thermal.** REG-FC sits under the lane with 1.67 mm of air; no measurement exists (T-F-19).
4. **Two bodies.** The 28 AWG E-leads span the MB-to-bracket gap; fatigue and relative motion are unmeasured (M5, T-F-18).
5. **Head feet.** RTV on solder mask can creep or peel; the ring arms still carry the head, and PM12 is the fallback.
6. **Window fit.** 0.5 mm per side around L-FC depends on L-FC placement tolerance (M6); dropping strip D (J shape) relaxes
   it at a 24 % loss of arm section.
7. **Unrecorded bodges.** An OPA197 5 V bodge wire near OP-FC could reduce the 0.92 mm air (M3).
8. **Larger, single-sided CR.** The r6 interior placement and the bottom set are re-planned on the top (T-A-06 is the gate);
   the CR PCB cost rises with 2.23 times the area.

## 12. Open items

- `TODO(measure: M2)` room beside the MB +y edge, lid profile over B-F, MB fixing hardware at (3.30, 94.74), dz between the
  EVM top and the CR top, shared sub-plate option.
- `TODO(measure: M3)` OP-FC (with any bodge wire), C4A/C4B-FC and L-FC heights; head gap after seating; EVM thickness, mass
  and edge strips.
- `TODO(measure: M5)` vibration spectrum at the MB +y edge and MB-to-chassis relative motion (service loop).
- `TODO(measure: M6)` L-FC body position against the CHG holes.
- `TODO(measure: M1 / D-2)` Ag105 standoff and module envelope.
- `TODO(verify: Eaton ELX1488)` L-FC height 5.0 mm; `TODO(verify: Molex 22-01-3047)` KK housing body; `TODO(verify: RTV
  datasheet)` bond strength on solder mask; `TODO(verify: fab)` 1.6 mm 4-layer stack-up, laminate modulus, CR quote.
- `TODO(verify: on the received EVM)` parts within 2 mm of the EVM top and bottom edges (clamp lips).

## 13. Files

| File | Content |
|---|---|
| `work/r7_evm_on_cr_calc.py` | every number in this proposal (stdlib + numpy/scipy/matplotlib; run with `python -I` from `round4/work/`) |
| `work/r7_evm_on_cr_calc_out.txt` | its output |
| `work/r7_evm_on_cr_map.png` | Figure 1: plan of the r7 CR, island, feet, EVM on its bracket and every lead |
