# Round 4 (r7) proposal T: tap-side carrier arm toward the Teensy breakout

Round 4 design proposal, one of several independent approaches. Subject: the BQ25798EVM path that replaces the Silvertel
Ag105 (MB designator CHG) on motherboard rev 20260622, design document
`docs/charger_bq25798_wiring_design_2026-11-05.md` revision r6 (the **design**). This file proposes changes; it does not
edit the design.

## 0. Scope, conventions, sources and verdict

### 0.1 Scope and conventions

This proposal extends the carrier (CR) sideways in +x, toward the Teensy J1/J2 breakout, while the CR stays plugged into
the 22 Ag105 holes on one 1x10 and one 1x12 TSW strip. The EVM stays the power stage and stays off-board. Every coordinate
is an Eagle `.brd` board coordinate in mm, top view, origin at the MB origin, +x right, +y up (design A.2, r6). EVM-frame
coordinates follow `work/evm_geometry.md` (origin at the lower-left corner of the EVM outline, top view). The **arm** is the
CR area added by this proposal; the **main footprint** is the r6 outline x 17.70-48.70, y 34.14-67.14.

### 0.2 Sources

Every number comes from one of the following, and the text names which.

- `work/tapside_calc.py` (stdlib Python, output `work/tapside_calc_out.txt`): outline, area booking, tap lengths, thermal
  bands, pin load, resonance, header stack, EVM placement and lead lengths, merged-EIB check.
- `calc/mb_neighbours.py --copper` queries on the `.brd` (copper and parts under the arm and under the tip foot).
- The four round-4 fact-finding notes: `work/evm_geometry.md`, `work/mb_mechanical.md`, `work/eib_merge_failsafe.md`,
  `work/stackup_area.md` (and `calc/stackup_area_out.txt`).
- Design sections A.3-A.9, B.6, C, D.1, E, H, I.

### 0.3 Verdict

The tap-side arm is feasible on paper and fixes a defect that r6 carries. On the strict usable-area basis of
`work/stackup_area.md`, the r6 top side is booked at 103 % (753 mm² of courtyard and pours on 732 mm²). With the arm, the
main top falls to 75 %, the arm runs at 71 % and the bottom stays at 74 % (section 1.4). The arm also cuts the summed tap
build length by 45 % (2770 mm to 1530 mm, section 1.3).

The arm does not make the CR single-sided, does not let the EVM sit on or beside the CR, and does not allow the EIB to merge
onto the CR. The EVM can move closer off-board (past the MB +y edge), which shortens W1-W7 by 33-63 %; the E-leads stay as in
r6 with the vector-corrected maxima. Confidence: high for geometry, area and lead routing (computed from the `.brd` and the
vector EVM data); medium for the thermal bands (an estimate until M4); low for the arm resonance against the vehicle (the
spectrum is unmeasured, M5), which is why the tip foot is mandatory.

## 1. Q1: side, outline, header and support

### 1.1 Side selection

Table 1 compares the candidate zones of `work/mb_mechanical.md` Table 1 against the purpose of this approach (tap length)
and the hard constraints of the brief.

Table 1. Zone selection.

| Zone | Tap gain (split-field straight sum, r3 field 1308.8 mm) | Blocking fact | Decision |
|---|---|---|---|
| +x (this arm) | 671.6 mm (-49 %) | LM1084 tab end 1.49 mm below the arm in plan; 34.2 mm cantilever | **chosen** |
| +x core only (x <= 65.00) | 885.3 mm (-32 %) | main top stays at 86 % (section 1.4) | fallback only |
| +y usable | 1279.3 mm (-2 %) | L-FC (5.0 mm, switching node) 0.50 mm from its top edge | rejected (no tap gain) |
| -y usable | 1299.3 mm (-1 %) | covers BAL pad 8 (T22, PM11), RB1A, CBL2; VSW-BT 2.96 mm away | rejected |
| -x / past x = 0 | not evaluated | J-BL 21.70 mm, J-NTC 13.90 mm, -x wire entries | excluded |

The +x zone is the only one that shortens the taps materially, and it is the only one with no MB part under it: the `.brd`
query of x 48.70-80.23, y 56.00-67.14 returns tented vias and traces only (`calc/mb_neighbours.py --copper`).

### 1.2 Outline

Table 2 gives the r7-T outline. The arm is a band 31.53 x 11.14 mm on the +x side of the main footprint.

Table 2. CR outline (board coordinates, mm).

| Item | Value | Source / check |
|---|---|---|
| Polygon (counter-clockwise) | (17.70, 34.14), (48.70, 34.14), (48.70, 56.00), (80.23, 56.00), (80.23, 67.14), (18.70, 67.14), (17.70, 66.14) | r6 main outline and pin-11 chamfer (A.7) kept; arm added |
| Inside corner at (48.70, 56.00) | 1.0 mm radius | stress relief at the arm root; router radius |
| Areas | main 1022.5 mm², arm 351.2 mm², total 1373.7 mm² (+34 %); bounding box 62.53 x 33.00 mm | calc section 1 |
| Arm low edge y 56.00 | 1.49 mm above the REG-5V body (y 54.51); 1.39 mm above the 5V L1 pour bbox (y 54.61); 0.42 mm above the tented 5V via at (59.39, 55.58) | `.brd` query |
| Arm top edge y 67.14 | 1.66 mm below the C-D2 body (y 68.80); same line as the main top edge | `.brd` |
| Arm tip x 80.23 | 0.50 mm left of RENC2 (x 80.73); 2.83 mm left of the J1 body (x 83.06) | `.brd` |
| Cantilever | 34.23 mm from the x 45.998 pin column to the tip | calc section 1 |

The arm passes beside the LM1084, never over it: the 4.83 mm TO-263 body is taller than the 2.54 mm header body, so an
overhang would need a raised stack. The low edge sits at y 56.00 instead of the 55.01 of the "+x usable" rectangle, which
adds 1.0 mm of plan clearance to the hot tab end for 31.5 mm² of area.

### 1.3 Arm content, tap fields and tap lengths

The arm carries the tap field, J101 and the passives that sit on tap nets. Everything temperature-sensitive stays on the main
footprint. Table 3 lists the placement regions.

Table 3. Arm placement (top side only; the arm bottom carries no part).

| Region | Content | Rule |
|---|---|---|
| Arm tap field, x 62.25-78.99, y 57.25-63.83 | 3 x 7 top-side SMT pads 1.5 x 1.5 mm at 2.54 mm, centres x 63.00 + 2.54k (k 0-6), y 58.00 / 60.54 / 63.08; 20 taps + 1 empty position | no holes (the field lies over the MB VBUS pour); adhesive bead per A.4; wires leave +x and +y |
| J101 at the arm root, courtyard x 49.70-59.10, y 62.74-66.64 | 2x7 1.27 mm SMT header lengthwise along x (r4 part); W5 socket exits vertically and folds +y at >= 8 mm above the CR top | near the root so the socket mating force and the ribbon load act close to the pin field |
| Root block, x 49.20-61.75, y 56.50-62.24 | R175 (68 ohm 1206, T6 3V3 limiter "at F07"), the readback series resistors R125-R128 and R148, C129 | temperature-insensitive parts only in y < 61.00 (band A) |
| Bottom (L4) | continuous GND pour under solder mask; vias tented on L4 | no part, no tail, no exposed copper over the MB VBUS pour and logic traces |

The four taps that must stay near the low-y edge keep single pads on the main footprint at y 35.80: F08 (T22, BAL pad 8;
the 30 AWG lead is limited to 0.05 m) at x 24.00, F09 (T8) at x 38.70, F10 (T9 Kelvin) at x 41.24, and F22 (T18 option,
CO-5V pad 1) at x 43.78. A suggested arm-grid map is row y 58.00: F01 T1, F02 T7b, F18 T17, F19 T17r, F23 T19 (option),
F24 spare, one empty; row y 60.54: F04 T3, F05 T4, F06 T5, F17 T16, F13 T12, F14 T13, F16 T15; row y 63.08: F03 T2,
F20 T20, F11 T10, F07 T6, F12 T11, F15 T14, F21 T21. Twisted pairs (T1/T7b, T17/T17r) stay on adjacent pads. The capture
may permute positions inside the grid.

Table 4 gives the tap lengths. The build rule is 1.5 x straight + 15 mm, rounded up to 10 mm; applied to the r6 straight
lengths it reproduces the A.4 build lengths within -10 mm (T22 40 vs 50, T2 90 vs 100, T8 140 vs 150, T12 140 vs 150 mm),
so it is not more aggressive than r6.

Table 4. Tap wire lengths (mm; calc section 3; destinations from `work/mb_mech_calc.py`).

| Tap | r6 straight | r7 straight | r6 build (A.4) | r7 build | Field |
|---|---|---|---|---|---|
| T1 C-D6 pad 1 (V-MOT) | 67.6 | 49.0 | 150 | 90 | arm |
| T7b C-D6 pad 2 (shield) | 68.7 | 52.2 | 150 | 100 | arm |
| T2 C-D2 pad 1 (VBUS) | 47.0 | 9.8 | 100 | 30 | arm |
| T3 / T4 / T5 J1.39 / .43 / .45 | 54.5 / 54.3 / 54.4 | 24.1 / 28.1 / 30.2 | 120 each | 60 / 60 / 70 | arm |
| T6 J1.29 (3V3) | 57.0 | 17.2 | 120 | 50 | arm |
| T10 J1.23 | 59.8 | 16.7 | 120 | 50 | arm |
| T11 / T14 / T17r J2.19 / .21 / .29 | 82.8 / 81.9 / 79.1 | 40.1 / 39.7 / 39.7 | 150 each | 80 each | arm |
| T12 / T13 / T16 J2.47 / .45 / .43 | 77.4 / 77.3 / 77.2 | 48.2 / 46.8 / 45.4 | 150 each | 90 each | arm |
| T15 / T17 / T21 J2.07 / .09 / .11 | 89.5 / 88.2 / 87.0 | 45.6 / 44.4 / 43.3 | 150 each | 90 / 90 / 80 | arm |
| T20 ROS pad 2 (pin 7) | 58.0 | 14.3 | 100 | 40 | arm |
| T22 BAL pad 8 | 10.5 | 5.7 | 50 | 30 | main F08 |
| T8 J2.31 | 78.6 | 73.3 | 150 | 130 | main F09 |
| T9 SNS-BT GND/REF1 | 26.7 | 18.5 | 120 | 50 | main F10 |
| **Sum** | **1378** | **732 (-47 %)** | **2770** | **1530 (-45 %)** | |

The J2 taps still cross the Teensy 4.1 (U$1, x 88.39-106.17), exactly as in r6; the seated Teensy height is
TODO(measure: M3). The T1/T2 and T8/T9 nets are high-impedance analog on the CR side, so their CR traces from the pads to the
H1/UVB divider tops and to U104 run as L3 striplines between the L2 and L4 GND layers, >= 2 mm from logic (A.8 analog rule
extended to the longer arm traces).

### 1.4 Area booking

Table 5 books the courtyards on the strict basis of `work/stackup_area.md` (732 mm² usable on the main top, r6 split 753 mm²
top including 60 mm² of pours and 435 mm² bottom, A.8 courtyards).

Table 5. Area booking (calc section 2).

| Side | Demand (mm²) | Usable (mm²) | Utilisation |
|---|---|---|---|
| Arm top: field 153.7 + J101 36.7 + R175 10.9 + six 0603 26.1 | 227.4 | 319.7 (31.53 x 10.14, 0.5 mm courtyard margin) | **71 %** |
| Main top: 753 - 168 (r6 field) - 36.7 - 10.9 - 26.1 + 25.0 (four single pads) + 15.2 (their bead, ASSUMPTION) | 551.6 | 732 | **75 %** (r6: 103 %) |
| Main bottom: r3 passive set | 435 | 591 (H.18) | **74 %** |
| Arm bottom | 0 | - | - |
| Whole CR | 1214 | 1643 | 74 % |

A single-sided CR needs +798 mm² (DNP footprints removed) to +917 mm² (all footprints) of extension on the strict basis
(`work/stackup_area.md` section 4); the arm adds 340 mm² of effective area. The CR therefore stays double-sided, with the
bottom passives on the main footprint only. The short "+x core" arm (x <= 65.00, 165 mm² courtyard) would leave the main top
at 86 %, which is why it is a fallback only (section 1.6.4).

### 1.5 Thermal bands

The arm's low edge is 1.39 mm from the 5V pour, so Table 6 assigns parts by distance from the pour (estimate of
`work/mb_mechanical.md` Table 4, rise above the local enclosure air).

Table 6. Arm thermal bands (calc section 4).

| Band | y range | Distance from the 5V pour | Estimated MB surface rise (0.63 W nominal; 1.08 W worst) | Allowed parts |
|---|---|---|---|---|
| A | 56.00-61.00 | 1.4-6.4 mm | 6.2-8.6 C nominal; up to 17.0-23.5 C worst | pads, wires, RTV bead, R175, 1 kOhm series resistors, C129 |
| B | 61.00-67.14 | 6.4-12.5 mm | 4.4-6.2 C nominal; up to 11.9-17.0 C worst | additionally J101 and logic passives |
| Main comparator block | x 24-36 | >= 13.8 mm | < 4.6 C nominal | comparators, references, 0.1 % dividers, BAV199, monostable RC |

No comparator, reference, 0.1 % divider, BAV199 or X7R timing capacitor goes on the arm. The freed r6 tap-field area on the
main footprint (x 23.15-42.43, y 35.05-41.63, minus the four single pads) is the preferred place for precision analog parts:
it is the farthest point from the U101 commutation loop (y 62-66), where the 4-layer coupling at 20 mm is 0.3 mV
(`work/stackup_area.md` Table 6). M4 replaces the estimate (section 1.7).

### 1.6 Header stack and far-end support

#### 1.6.1 Header

The header stays a Samtec TSW single-row strip with the 2.54 mm PBT body (`work/mb_mechanical.md` Table 7). The body sits on
the polyimide sheet, so the CR underside is 2.665 mm above the MB everywhere, including the arm, which has 2.665 mm of air
over traces and tented vias only. Table 7 gives the post options for a 1.6 mm MB (design PM4) and a 1.6 mm CR
(TODO(verify: fab stack-up, M7)).

Table 7. TSW lead styles (A - B - C from F-226 via `work/mb_mechanical.md`; calc section 6).

| Style | Orientation | CR-top protrusion | Below the MB | Note |
|---|---|---|---|---|
| -05 (8.51 - 3.30 - 2.67) | C (2.67) through the CR | 1.07 mm | 1.57 mm, cut to <= 1.0 mm in PM4 step 4 | **recommended**: fillet >= 0.5 mm without trimming at the CR top |
| -07 (10.92 - 2.54 - 5.84), r6 BOM | B (2.54) through the CR | 0.94 mm | 4.12 mm, cut | acceptable |
| -07 | C (5.84) through the CR | 4.24 mm | 0.81 mm | trimming at the CR top near J101 and the arm root; not preferred |

The letter mapping and the lead-style code are TODO(verify: Samtec TSW drawing, T-A-05). The stack top is 4.27 mm above the
MB plus the CR top parts; over the arm root J101, its mated socket and the W5 fold reach >= 12.3 mm, which lies outside the
Ag105 envelope and must be checked against the lid (M2).

#### 1.6.2 Tip foot

The arm gets one far-end support. The support is a 2-position segment cut from a TSW body (5.08 x 2.54 mm, 2.54 mm tall,
pins pulled out), bonded with the BOM neutral-cure RTV to the arm L4 solder mask at x 75.73-78.27, y 58.96-64.04 (centre
(77.0, 61.5)) and to a 7 x 8 mm polyimide patch (x 73.0-80.0, y 57.5-65.5) bonded on the MB. The foot is the same extrusion
as the header body and sits on the same 0.125 mm film, so its height matches the header standoff without preload. The patch
is a sacrificial interface: removing the CR peels the silicone-adhesive film instead of the MB solder mask, which at this
spot covers the VBUS pour and the D-FC-EN EN trace (`.brd` query).

The other support options of `work/mb_mechanical.md` Table 5 fail at the tip: the MB mounting holes are 52-69 mm away
behind the terminal blocks, no free through-hole exists, a drilled hole is an MB bodge and finds no 3 mm clearance to
non-GND copper, and a lid pad needs an unmeasured lid.

#### 1.6.3 Pin load and resonance

Table 8 gives the order-of-magnitude result with the assumptions of `work/mb_pinload.py` (main CR 5-10 g, arm 0.6-0.8
g/cm², E = 20 GPa, 30 g normal shock, ASSUMPTIONS; cable loads excluded).

Table 8. Arm mechanics (calc section 5).

| Quantity | Unpropped | With the tip foot |
|---|---|---|
| Worst axial pin load at 30 g | 0.175-0.278 N | 0.105-0.185 N |
| Foot reaction at 30 g; bond stress on 12.9 mm² | - | 0.31-0.41 N; 24-32 kPa |
| First bending mode | 513-725 Hz (L 34.2 mm, cantilever) | 2.74-3.88 kHz (L 31.0 mm, clamped-pinned) |
| 10 N handling push at the tip | 1.76 mm deflection against a 2.665 mm gap | about 0 |

Static strength does not decide the support: every case is two to three orders below the ~141 N pin section capacity of
`work/mb_mechanical.md` section 6.2. The foot is mandatory for two other reasons. The unpropped mode lies inside the
0.5-3.2 kHz band that M5 must clear, and an unpropped arm deflects to within 0.9 mm of the MB under a 10 N push. The bond
stress of 24-32 kPa must be compared with the strength of the chosen RTV, which is TODO(verify: its datasheet); T-A-08
therefore pull-tests the bond at 5 N (388 kPa, 12 times the 30 g foot reaction; calc section 9).

#### 1.6.4 Fallback

If M3 or M4 forbids the arm beyond x 65.00, the short arm (x 48.70-65.00, y 56.00-67.14) holds J101, R175 and a 2 x 5
field for the J1, C-D2 and ROS taps. The J2 taps then stay on a main-footprint field and the main top runs at about 86 %,
above the 75 % budget. The short arm needs no foot by resonance (1.7-2.4 kHz unpropped) but does not cure the r6 area
overflow, so it is not recommended.

### 1.7 Measurements before the outline is frozen

The operator makes these measurements first; each line names what it decides.

1. **M3a (heights and positions on the MB top along the arm):** R171 standing on C-D2 pad 1 after PM3, RENC2, the
   2026-08-16 encoder reroute wires and the fitted 74HC14, the 10 kOhm EN bodge resistor at D-FC-EN, and any wire crossing
   x 48.70-80.23, y 56.00-67.14. Decides the arm tip x (80.23 or shorter) and confirms the top edge.
2. **M4 (LM1084 thermal survey extended to the arm):** MB surface at y 55.5, 58, 61, 64 and 67 along x 55 and x 70, the
   tab and the pour rim; closed enclosure, Run with Ethernet and SD, 8.4 V and 7.4 V, 30 min soak. Decides the band A/B
   boundary and the RTV, J101 and wire-insulation ratings.
3. **M2 (enclosure):** lid clearance over the arm and the J101 fold (>= 12.3 mm plus the socket height), and chassis room
   for the EVM tray and the EIB past the MB +y edge (x 7.0-129.9, y 98.0-206.9, about 123 x 109 mm, section 2.2; calc
   section 9). Decides the EVM placement and the W
   lead maxima; without it the r6 0.30 m caps stay.
4. **M5 (vibration):** accelerometer on the MB near the CHG footprint in a representative run, 0.1-8 kHz. Sets the T-F-18
   criterion; it does not remove the foot.
5. **M7 and the MB thickness:** CR fab stack-up (1.6 mm, 0.2 mm prepregs, L4 via tenting), MB thickness by caliper.
   Decides the TSW lead style and the foot height check.
6. **EVM caliper and mass (`work/evm_geometry.md` open items):** as-built outline, thickness, mass, and the Molex
   22-01-3047 mating envelope at J8. Decide the tray pocket and the EVM gap g (20 mm assumed).
7. **M1 (D-2):** still recorded for the main footprint, but it no longer gates the arm, which lies outside the Ag105
   envelope; M2 governs the arm.

## 2. Q2: EVM placement and lead lengths

### 2.1 On or beside the arm

The EVM cannot mount on the CR or directly beside the arm. The EVM is 88.90 x 88.90 mm, 61.5 % of the MB area
(`work/evm_geometry.md` finding 2), and has no mounting holes. On the CR it would load 22 pins of 0.64 mm with an unmeasured
mass on a cantilever. On the MB the arm is boxed in by the LM1084 (-y), the FC droop and current-sense parts (+y), and J1
and the Teensy (+x); no 89 mm square exists there. A mezzanine over the MB would sit within 20 mm of the LM1084 or over the
Teensy, would block the J-BL and J-FC screws (driven from the top at x ~9.4) and would need an enclosure height of about
41.4 mm (21.70 mm block + 5.08 mm bumpon + 1.6 mm board + 13.0 mm terminal block; board thickness TODO; calc section 9),
which is unmeasured.

### 2.2 Closer off-board placement

The EVM moves to the chassis just past the MB +y edge, which is the only edge the leads reach without crossing a switching
node, the terminal blocks or the Teensy. Every EVM lead leaves the CR through a **corridor gate** at (56.0, 67.14) and runs
+y over x 56-80 to the MB edge; in that band no switched conductor lies within 10 mm (REG-FC ends at x 45.90, the VSW-FC pour
and L-FC further left), and the parts below are <= 1.2 mm tall (D-FC-EN, C-D1, C-D2, SNS-FC, VBUS-FC pour). Leads run at
>= 8 mm above the CR top, never resting on CR parts.

The reference placement is orientation R0: the EVM bottom edge faces the MB at a gap g = 20 mm (room for the J8 housing,
which mates from below; TODO(verify: Molex 22-01-3047 drawing)). In board coordinates the EVM occupies x 12.0-100.9,
y 118.0-206.9, and the EIB keeps its r6 position beside the EVM right edge (pad column 7 mm off the edge, E3 5 mm above the
TP33 level), at x 105.9-129.9, y 159.7-195.7. The EVM power stage is then >= 93 mm from the CR comparators and >= 63 mm from
the LM1084, against the 20 mm rules. The orientation with the EVM right edge toward the MB and the EIB in between (R90cw)
gives shorter W3/W4 (99-104 mm) and W5 (51 mm) but puts J1 and J8 on the far side (W1/W2 250-253 mm, W7 168 mm), and it
loses on the weighted sum (1405 against 1308; W3/W4 weight 2, W1/W2/W5 1.5, W7 1). The other two orientations put J5 or the
EIB on the far side by inspection.

### 2.3 Lead maxima

The r6 rule (straight distance x 1.25, rounded up to 5 mm) suits the short EIB leads in open space. For leads that cross the
MB it undercounts, because they must avoid the FC switching node and approach each terminal from its wire-entry face. This
proposal therefore uses the **route rule**: route = CR pad -> corridor gate -> MB edge -> terminal approach on the
wire-entry side -> terminal; build maximum = 1.25 x route, rounded up to 10 mm. Table 9 gives the result.

Table 9. EVM lead lengths (calc section 7; placement R0, g 20 mm, X0 12 mm).

| Lead | r6 maximum | Route | r7 build maximum | Change |
|---|---|---|---|---|
| W1 / W2 (input, 20 AWG pair, to EVM J1) | 300 | 153 / 156 | **200** | -33 % |
| W3 / W4 (battery, 18 AWG pair, to EVM J5) | 300 | 138 / 133 | **180** | -40 % |
| W5 (14-way ribbon, J101 to EIB J201) | 300 | 143 | **180** | -40 % |
| W6 (TS, only with an NTC) | 300 | 84 | **110** | -63 % |
| W7 (I2C triple to EVM J8) | 300 | 88 | **110** | -63 % |
| E1-E8 (EIB to EVM) | r6 A.5 | unchanged | E8 20, E3 25, E4 30, E2 35, E7 40, **E1 90**, **E5 65**, E6 60 | vector correction only |

The E maxima are the r6 rule re-run on the vector EVM positions (`work/evm_geometry.md` Table 6): E1 moves from 85 to 90 mm
and E5 from 60 to 65 mm, and the E4 target is the lower JP21 post at EVM (75.312, 64.769), not the A.5 pixel point, which is
the AGND post. The r6 0.30 m caps stay valid as the upper bound until M2 confirms the chassis room; a different measured
position re-runs calc section 7 with the same rule.

The shorter pairs lower the lead resistances computed with the AWG table that reproduces H.11 (0.30 m: 20.0 and 12.6 mOhm).
The input pair at 0.20 m is 13.3 mOhm, so R_PATH_RG (H.19) moves from 0.117-0.193 to 0.110-0.186 ohm and the regen-armed
warm budget (H.7) from 0.330 to 0.333 ms at 0.4 mF (0.800 to 0.807 ms at 0.97 mF): a 1 % gain, recorded but not relied on.
The battery pair at 0.18 m is 7.5 mOhm: 24 mV and 78 mW at 3.21 A (H.11 r5: 40 mV, 130 mW).

The r5 strain-relief rule "chassis cable tie within 30 mm of the CR edge" (A.3) is met on no side except through the 4.8 mm
gap between J-NTC (y <= 67.35) and J-FC (y >= 72.14) at -x; the corridor reaches the chassis at the MB +y edge 30.9 mm from
the CR top edge. This proposal sets the tie at <= 35 mm, at the MB +y edge.

### 2.4 EVM mounting

The EVM sits in an insulating tray screwed to the chassis: a pocket 0.25 mm larger than the measured outline on each side
(89.4 mm nominal), a floor carrying the four stock bumpons (H1-H4, 5.08 mm), and four insulating hold-down clips on the
board edges clear of J1, J5, J7, J8, the EIB lead points and the fiducials. The bumpons keep the underside SMT parts and the
through-hole tails (up to 2.4 mm at an assumed 1.6 mm board) clear of the floor by about 2.7 mm (TODO(measure: EVM
thickness)). No fastener touches EVM copper, so no hardware bonds EVM ground to the chassis or to the CR plane.

## 3. Q3: EIB merge

The EIB is not merged; the r6 split stays (EIB at the EVM pins, W5 ribbon to the CR). Calc section 8 places the EVM in the
most favourable position this approach allows (right edge toward the MB, 3 mm past the +y edge, nothing in between) and
measures from a pad row on the arm top edge. The straight lengths are E8 40-46, E3 43-44, E4 47-48, E2 51-52, E7 57,
E1 85-90, E5 68-73 and E6 68-71 mm; the x1.25 maxima are E3 55, E4 60-65, E2 65-70, E7 75, E1 110-115, E5 85-95 and E6 90 mm.
These exceed the G1 window of `work/eib_merge_failsafe.md` (10-60 mm, E1 up to 90 mm), and the leads would cross from the MB
to a separately mounted EVM, where they must be tied as a bundle. That makes the G2 single fault credible: an E1 short to the
ILIM group feeds REGN onto ILIM_HIZ and removes the hardware input-current clamp without detection
(`work/eib_merge_failsafe.md` Table 5). The merge study's verdict for that class is "not acceptable", and its re-proof would
put parts back at the EVM pins, which re-creates the EIB.

Because the EIB stays where it is, every round-3 EIB argument holds as is. Table 10 lists them.

Table 10. EIB fail-safe arguments under this proposal.

| Argument | Status | Reason |
|---|---|---|
| r1-2 two series switches (Q203 feed + Q201 hold-down) with separate drivers at the EVM pins | holds as is | topology and E-lead class unchanged |
| r2 evm-jp14-feed-joint-floating (EM3) | holds as is | EVM-side |
| /CE driver U201 1Y open drain, R272/R272b on separate EVM joints (r3) | holds as is | unchanged |
| Far-end senses U203 (E4, R258 10.0 kOhm) and U204 (E6) | holds as is | unchanged; E4 lands on the lower JP21 post |
| E1 REGN supply and pad isolation (r4) | holds with a stated change | add **R276 10.0 ohm 0603 in series with E1 at the EIB E1 pad**: E1 at 85-90 mm with C205 resonates at about 1.47 MHz, on the 1.5 MHz switching frequency, with Q about 19-20; 10 ohm brings Q to about 0.1 and shifts the release level by 1.6 mV (2 mA of clamp) (`work/eib_merge_failsafe.md` section 3.4, recommended there for r6 too) |
| Single DC ground E8/TP49, R273, A.6 scheme (r2) | holds as is | unchanged |
| W5 ribbon adjacent-short list, keying, R176/R177, R264/R265, R275 (r3-r5) | holds as is | the same 14 conductors in the same order; only the length falls from 0.30 m to <= 0.18 m, which shortens the crush exposure |
| B.6 single-fault rows, H.13 glitch analysis | hold as is | unchanged |

## 4. Q4: layer count and stack-up

The CR stays a 4-layer board: double-sided on the main footprint, single-sided on the arm. Three facts decide it.

1. **Area.** Single-sided needs +798 to +917 mm² of extension; the arm gives 340 mm² (section 1.4). A 2-layer single-sided
   CR needs +1160 to +1307 mm² (`work/stackup_area.md` section 4).
2. **Comparator against power loop.** On 2 layers the commutation-loop inductance rises 4-7 times per millimetre and the
   coupling into a comparator input rises 46-53 times at equal distance; the four unfiltered comparator inputs (U115 IN-,
   U119 IN-, U120 IN+, U121 IN+) would see 191 mV at 5 mm instead of 4.1 mV (`work/stackup_area.md` sections 5.1-5.2). The
   A.8 L3 routes (SCL/SDA/TS under the IN strip, the C102b link) have no 2-layer equivalent.
3. **Battery copper.** The 3.21 A path is unchanged: W3/W4 stay at the pin columns and the arm carries no power current (the
   largest arm current is the R175 3V3 feed, <= 1.86 mA in service and 48.5 mA into a short, H.20). The >= 2.5 mm L1 pours
   meet 3.5 A on 2 oz (7.7 A) or 1 oz (4.6 A) at a 10 C rise (H.22(c)).

The stack-up is the r6 one, restated in Table 11 (`work/stackup_area.md` section 7.2).

Table 11. CR stack-up.

| Layer | Copper | Dielectric below | Main footprint | Arm |
|---|---|---|---|---|
| L1 | 2 oz (1 oz allowed after the PM0 DFM check at the RGE 0.5 mm pitch) | prepreg 0.2 mm | ICs, power pours, signals | tap field, J101, root block, signals |
| L2 | 1 oz | core ~1.0-1.1 mm | solid GND plane | solid GND plane |
| L3 | 1 oz | prepreg 0.2 mm | signals, I2C/TS under the IN strip, C102b link | T1/T2 divider-top runs and the long tap-to-logic runs as striplines |
| L4 | 2 oz (or 1 oz) | - | GND pour around the bottom passives, stitched <= 5 mm | continuous GND pour, tented vias, no parts |

The arm's L4 faces the MB VBUS pour (139 mm² under the arm tip) across 2.665 mm of air; the coupling capacitance is about
0.46 pF (eps0 x 139 mm² / 2.665 mm), which is negligible against the CR plane. TODO(verify: fab 1.6 mm 4-layer stack-up
table and L4 via tenting).

## 5. Q5: round-3 constraints

Table 12 gives the status of each round-3 constraint, with its reason.

Table 12. Constraints retired, kept and changed.

| Round-3 constraint | Status | Reason |
|---|---|---|
| CR confined to the 31 x 33 mm footprint inside the CHG silkscreen (A.7) | **retired** | the arm adds 351 mm² in +x |
| A.7 "overhang only if the capture needs it" (low-y over C4A/B-BT, high-y over OP-FC) | **retired** | replaced by the arm, which covers no MB part |
| Passives-only bottom, <= 1.0 mm (A.7, H.18) | **kept on the main footprint**; the arm bottom carries nothing | the main top needs the 435 mm² bottom set to stay at 75 % |
| Bottom keep-out x 24.5-36.0, y 48.5-53.5 | **kept** | D-BT-SQ, C-D11, C-D12, C-DC11, C-DC12 are still under the footprint |
| MB-copper shadow (+1 mm) for bottom parts | **kept on the main footprint**; void on the arm | VBT, the VBT and VCHG pours and VCHG-IN still run under the main footprint |
| 0.125 mm polyimide sheet under the CR (PM4 step 1) | **kept** under the main footprint (r6 cut, x 16.70-49.70, y 33.14-68.14); **not extended** under the arm; **new** 7 x 8 mm patch under the tip foot | the main footprint still has bottom parts and W1-W4 tails over power copper; the arm has no bottom feature |
| Flush-cut tails <= 0.5 mm, PM4 step 2b | **kept** | W1-W4 holes stay on the main footprint over VBT / VCHG-IN / VCHG copper |
| Top-side SMT tap pads, no tap tails (A.4) | **kept** for both fields | the arm field lies over the 16 V VBUS pour; a hole there would put a tail over bus copper |
| Area budget H.18 / H.22(k) (~881 mm² top basis) | **restated** on the strict basis | r6 is at 103 %; r7-T main top 75 %, arm 71 %, bottom 74 % |
| J101 region x 37.0-44.5, y 42.13-51.53 and its mated-socket overhang check (r5) | **retired / moved** | J101 moves to the arm root; the socket envelope is re-checked there (T-A-06) |
| +x pocket 0402-only, bottom 0603 fallback for R103/R104 | **relaxed** | the pocket may extend to x 50.70 into the arm root, so R103/R104 may be 0603 on the top; the bottom fallback retires |
| CR never over the LM1084, CO-5V or the J-NTC/J-BL side | **kept** | the arm passes beside the LM1084 at 1.49 mm, never over it |
| Pin-11 chamfer, Eagle coordinate convention, pin-identity gate | **kept** | the arm adds a second asymmetry, which a y-mirrored capture also exposes |
| Courtyards >= 0.5 mm from the outline and the header, W1, W2, W6, W7 pads | **kept** on the new outline | - |
| W1-W4 positions, hole sizes, U101 placement, <= 2 nH loop rules, VCHG-IN <= 5 mm, analog distances | **kept** | the courtyard-checked high-y band (H.21(k)) is not touched |
| EVM >= 20 mm from the LM1084 side | **kept** | >= 63 mm in the reference placement |
| Leads <= 0.30 m | **tightened** to the Table 9 maxima once M2 confirms the placement | shorter routes; the cap stays as the fallback |
| Chassis tie within 30 mm of the CR edge (A.3 r5) | **changed** to <= 35 mm at the MB +y edge | 30 mm is reachable only through the J-NTC/J-FC gap |

## 6. Q6: EVM and MB modifications

### 6.1 EVM

No EVM modification becomes unnecessary: the EVM stays electrically the same and the EIB stays at its pins. EM23 changes,
because the corner holes it assumes do not exist (`work/evm_geometry.md` finding 1): the EVM goes into the insulating tray of
section 2.4 and the stock bumpons stay fitted, so the "remove the bumpons" step of EM23 becomes unnecessary. The EVM line of
A.7 ("4 M3 nylon standoffs in the corner holes") changes the same way. Table 13 maps the study list to the design list.

Table 13. Study M1-M11 against design EM1-EM25.

| Study | Design | Status under r7-T |
|---|---|---|
| M1 remove JP17 | EM1 (shunt and pin 2 removed) | needed |
| M2 NMOS stage on /CE | superseded by EIB U201 1Y (B.6) | needed in its B.6 form |
| M2b R42 re-biased from REGN | EM2 (R272 / R272b to REGN on separate links) | needed |
| M3 ILIM stages, R21 | EM3 (R21 0 ohm, JP14 / JP13 pin 1 and R20 removed), EM4 (R23 49.9 k), EM5 (R256/C252 at JP21) + EIB Q201-Q203 | needed |
| M4 R39/R40, JP32 | EM6, EM8 | needed |
| M5 JP1-JP4, J2 | EM10, EM11, EM7 (with J3 / J4) | needed |
| M6 JP5, JP8, JP9 | EM12, EM13, EM9 | needed |
| M7 input caps >= 35 V | EM14 (+ MB PM2) | needed |
| M8 keep-alive (proposal) | B.5 DNP option, T18 / PM7 | unchanged (T-B-09 decides) |
| M9 TS | EM18 | needed |
| M10 JP24 2S | EM19 | needed |
| M11 D+/D- jumpers | EM16 | needed |
| (design only) | EM15 JP30, EM17 JP7, EM20-EM22, EM24, EM25 | needed |
| (design only) | EM23 bumpons -> standoffs | **rewritten**: tray, bumpons kept |

### 6.2 MB

No MB modification becomes unnecessary. Table 14 lists the changes.

Table 14. MB modifications under r7-T.

| ID | Change |
|---|---|
| PM0 | capture the L-shaped outline of Table 2 (inside-corner radius, chamfer kept), the two tap fields, J101 at the arm root, the arm L4 rules; T-A-06 runs on the new outline |
| PM1-PM3, PM5, PM7-PM11 | unchanged |
| PM4 | steps 1a, 1b, 1, 2, 2b, 3, 4 unchanged; **new step 1c**: bond the 7 x 8 mm foot patch at x 73.0-80.0, y 57.5-65.5; **new step 3b**: after seating, bond the tip foot to the arm L4 and the patch with the BOM RTV, cure, and check the foot height against the header body (T-A-08) |
| PM6 | tap build lengths per Table 4 (summed 1.53 m, r6 2.77 m); taps leave the arm +x and +y |

## 7. BOM and cost delta

Table 15 lists the BOM changes against design section E. Prices are budget allowances, not verified.

Table 15. BOM delta.

| Line | r6 | r7-T | Cost delta (allowance) |
|---|---|---|---|
| CR PCB | 31.0 x 33.0 mm, 4-layer, 5 pcs, USD 70 | L-outline, bounding box 62.53 x 33.00 mm, 1373.7 mm², 4-layer, tented vias on L4 | +USD 10-30 |
| Tip foot | - | 2-position segment of a spare TSW strip body (pins pulled), + 1 spare TSW-110 strip | +USD 2 |
| Foot patch | - | cut from the existing polyimide sheet line | 0 |
| R276 (EIB, E1 damping) | - | 10.0 ohm 1 % 0603, CRCW060310R0FKEA (same MPN as R273) | < USD 0.1 |
| W5 cable assembly | FFSD-07-D-12.00 class, 0.30 m | same class, the shortest stock length >= 160 mm and <= 180 mm (TODO(verify: Samtec FFSD length increments), T-A-05) | about 0 |
| Wire | 26 AWG >= 5 m | fitted taps 1.53 m (r6 2.72 m), W6 0.11 m: keep >= 3 m in two colours | -USD 0-3 |
| EVM mounting | M3 x 10 nylon standoffs x 6 | insulating tray with edge clips for the EVM (material rating TODO), 2 standoffs kept for the EIB | +USD 5-15 |
| **Net** | total about USD 505-540 | | **+USD 15-45; total about USD 520-585** |

## 8. Test registry delta

The new IDs are provisional. `work/eib_merge_failsafe.md` proposed T-A-08, T-C-16 and T-F-18 for merge-only content that
this proposal does not adopt, so the IDs below must be renumbered if both sets are integrated.

### 8.1 New

- **T-A-08 Arm fit, clearance and tip foot (before PM4 step 3 and again after 3b).** Before ordering: 1:1 print of the
  L-outline over the bare MB with the M3a items in place; plan clearance >= 0.5 mm to RENC2, C-D2 and R171, the REG-5V body
  and every M3a item. After fabrication: the arm L4 mask Gerber shows no via annulus and no copper opening. Dry fit on loose
  pins: arm underside >= 2.4 mm above every MB feature under it. After 3b: foot height within +-0.05 mm of the header body;
  5 N upward pull at the foot for 10 s with no bond crack (spring scale, after the RTV cure; 12 times the 30 g reaction).
  Fail: shorten the arm per M3a, re-bond, or move the foot inboard and re-run calc section 5.
- **T-F-18 Arm vibration on the vehicle.** Accelerometers on the arm tip and on the MB beside the footprint during the M5 run
  and a tap test of the fitted arm. Pass: arm-tip transmissibility peak above the band that holds 90 % of the measured MB
  vibration energy; no FR-08 trip and no uncommanded pin 7 / pin 33 transition; after the run no crack at the 22 joints or
  the foot bond (loupe), and T-F-12 tap-net resistances unchanged. Fail: stiffen (second foot at about x 62.7, y 61.3, the
  farthest foot spot off the power pours) or shorten the arm.
- **T-F-19 Arm and main-footprint temperature.** Thermocouples on the arm at y 56.5 and y 64 (x 60 and x 75), at J101 and at
  the main comparator block; closed enclosure, Run with Ethernet and SD, 8.4 V, 30 min, enclosure air logged. Pass: every
  comparator, reference, 0.1 % divider and BAV199 location <= 45 C (the H.2 REF-drift basis, 0-45 C) at the highest measured
  enclosure air; band A <= the RTV and wire-insulation ratings. Fail: move the offending part inboard or to band B.

### 8.2 Changed

- **T-A-02:** the corner-hole step ("M3 rod through a corner hole", M2.5 fallback) is replaced by the tray fit and an
  insulation check (TP49 and J1 pin 1 to the tray screws > 1 MOhm); E-lead maxima per Table 9 (E1 90, E5 65); E4 on the lower
  JP21 post (75.312, 64.769); R276 metered 10.0 ohm +-1 % in the E1 path.
- **T-A-05:** J101 region at the arm root (x 49.70-59.10, y 62.74-66.64) and its mated-socket envelope there; W5 assembly
  length; TSW lead style -05 (or the r6 -07) against the measured MB and CR thickness; RTV temperature rating against T-F-19;
  tray material; R276.
- **T-A-06:** placement DRC on the L-outline; two tap fields; J101 at the arm root; the MB layer-1 copper overlay now covers
  the arm (no CR bottom feature over it); polyimide print = r6 sheet plus the foot patch; the A.7 overhang items removed.
- **T-A-07:** board temperature taken at the arm bands and the main right edge as well as beside the LM1084.
- **T-C-05:** add a scope step on REGN at C205 (EIB) with the charger converting, with and without R276, recording the
  1.5 MHz ring.
- **T-C-13:** W5 conductor-1 check unchanged; length per T-A-05.
- **T-F-12:** pull check extended to the arm tap bead; W1-W7 chassis tie <= 35 mm at the MB +y edge; inspect the foot bond
  and the MB mask around the patch after the vibration or road run.

### 8.3 Retired

No test retires. The retired steps are the T-A-02 corner-hole step, the T-A-05/T-A-06 J101 region checks at x 37.0-44.5,
y 42.13-51.53, the 31 x 33 mm outline DRC and the A.7 overhang height checks over OP-FC and C4A/B-BT.

## 9. Risks

1. **Heat at the arm's low edge.** Band A is 1.4-6.4 mm from the 5V pour; the worst estimate is a 23.5 C rise at 1 mm with
   1.08 W in the LM1084. Mitigation: band rule, T-F-19, M4 first. Confidence in the estimate: medium (two-layer fin model,
   `work/mb_mechanical.md` section 5).
2. **Arm resonance and bond durability.** The unpropped mode (0.51-0.73 kHz) is inside the unmeasured vehicle band; the
   foot moves it to 2.7-3.9 kHz but adds a bond that can creep or peel. Mitigation: T-A-08 pull, T-F-18; a second foot is
   the fallback.
3. **Arm over the VBUS pour.** A short needs two independent defects (an exposed arm L4 feature and a breached MB mask) plus
   contact across 2.665 mm; the foot removes the flexing that could make contact. Consequence if it happens: VBUS onto the
   CR GND, an OC_FC-class event on the FC channel. Mitigation: tented L4 vias, featureless arm bottom, T-A-08 Gerber check.
4. **EVM placement depends on chassis room past the +y edge (about 124 x 109 mm).** If M2 finds none, the r6 0.30 m caps and
   placement rule stay; no safety argument changes.
5. **Removal of the CR now also needs the foot debonded,** and the arm tip sits 0.5 mm from RENC2, a gate P8 rework point.
   RENC2 stays reachable from above and from +x, but a soldering iron at RENC2 is 0.5 mm from the arm edge.
6. **Unrecorded bodge items near the arm tip** (encoder reroute wires, 74HC14, EN bodge resistors) may collide with the
   outline; M3a is the gate.
7. **J2 taps still cross the Teensy,** as in r6; their wires lie over an unmeasured Teensy height.
8. **The area model is an estimate** (+-50 % routing demand in `work/stackup_area.md`); the arm runs at 71 % and absorbs
   some overflow, but the T-A-06 placement DRC on the captured board remains the gate.

## 10. Open items

- TODO(measure: M3a) MB top items along x 48.70-84, y 55-72; TODO(measure: M4) arm thermal survey; TODO(measure: M2)
  enclosure lid over the arm and chassis room past the +y edge; TODO(measure: M5) vehicle vibration; TODO(measure) MB and EVM
  thickness, EVM outline and mass.
- TODO(verify: Samtec TSW drawing) lead-style letters and the -05 code; TODO(verify: Samtec FFSD length increments);
  TODO(verify: Molex 22-01-3047 drawing) J8 mating envelope (sets g); TODO(verify: chosen RTV datasheet) strength and
  temperature rating; TODO(verify: fab stack-up, via tenting); TODO(verify: B.8) that R276 is a free designator in the
  capture (it is unused in r6).
- The C-D6 pad-2 position for T7b is an assumption (pad 1 offset 3.8 mm in -y); it only sets T7b, which runs twisted with
  T1.
- `work/evm_geometry.md` follow-ups that apply to every approach: A.5/H.22(i) JP21 pin 1 coordinate, the 2.2-2.5 % high
  round-3 render scale, the corner holes in A.7/EM23/T-A-02.

## 11. Files

| File | Content |
|---|---|
| `work/tapside_calc.py`, `work/tapside_calc_out.txt` | every number of this proposal (run with `python -I tapside_calc.py` from `round4/work/`) |
| `calc/mb_neighbours.py` | `.brd` copper and part queries for the arm (x 48.70-80.23, y 56.00-67.14), the pour rim and the foot site |
| `work/mb_mechanical.md`, `work/mb_pinload.py`, `work/mb_support_spots_out.txt` | zone map, heights, LM1084 estimate, pin-load and resonance method, foot spots |
| `work/evm_geometry.md`, `work/evm_calc/evm_geom_out.txt` | EVM outline, points, no mounting holes, vector E-lead maxima |
| `work/eib_merge_failsafe.md` | G1/G2 merge criteria, R276 (E1 damping) basis |
| `work/stackup_area.md`, `calc/stackup_area_out.txt` | strict area basis, single-sided break-even, 2-layer comparison, stack-up |
