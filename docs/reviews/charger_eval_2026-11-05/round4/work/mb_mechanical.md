# MB mechanical, thermal and copper map for a CHG carrier that extends past the Ag105 footprint (round 4 work note)

## 0. Scope, conventions and sources

### 0.1 Scope

This note maps the motherboard (MB, rev 20260622, `.brd` 20260625) around the CHG footprint so that the side and the
length of a sideways carrier (CR) extension can be chosen with evidence. The CR still plugs into the 22 Ag105 holes on
one 1x10 and one 1x12 header strip. The note scores each candidate side; it does not select the final outline. The
EVM stays the power stage; a custom BQ25798 board is outside the scope of this note.

### 0.2 Conventions

Every coordinate is an Eagle `.brd` board coordinate in mm, top view, origin at the MB origin, +x right, +y up. The
round-3 r6 CR outline is x 17.70-48.70, y 34.14-67.14 (design A.7). A **zone** is a rectangle that the CR could add on
one side. A **usable zone** is the same rectangle trimmed so that it keeps 0.5 mm plan clearance to every MB part that
it must not cover. "Air" means the vertical gap between the top of an MB part and the CR underside.

### 0.3 Sources and status markers

The geometry comes from the `.brd` through `round4/calc/mb_neighbours.py` and the scripts of section 9. Heights come
from IPC-7351 package names (the name carries the maximum body height), from local datasheets in
`references/Datasheets/`, or from manufacturer pages; each row states which. A value marked `TODO(measure)` or
`TODO(verify: <doc>)` is not known. Sections 5 and 6 contain estimates and order-of-magnitude checks; each states its
inputs and the measurement that replaces it.

## 1. Results at a glance

### 1.1 Zone table

Table 1 scores every candidate zone against the criteria of the brief. The straight tap sum is the sum of the 20 A.4
tap destinations measured as straight lines (T7b follows T1 to C-D6, T18/T19 are options and F24 is a spare);
it is 1308.8 mm from the r3 tap field (centre (32.79, 38.34)). A "split
field" keeps T22, T9 and the other low-y taps on the r3 field and moves every tap that becomes shorter to a second
field on the extension.

Table 1. Candidate extension zones (computed by `work/mb_mech_calc.py`, output `work/mb_mech_calc_out.txt`).

| Zone | Rect x0-x1, y0-y1 | Area / part-free (mm²) | Tallest MB part under | Header body for >= 1.0 mm air | MB copper under (power class) | Switching node / 5V pour distance | Straight tap sum (split field) | Access blocked | Extension f1 estimate | Assessment |
|---|---|---|---|---|---|---|---|---|---|---|
| +x raw (brief) | 48.70-82.00, 55.00-69.00 | 466.2 / 462.5 | C-D2 1.10 (edge), RENC2 0.60 | 2.10 mm | VBUS pour 142 mm², logic | VSW-FC 13.7 mm / 0.14 mm | as +x usable | C-D2 pad 1 (R171, T2 joint), RENC2, J1 tap pins 1.1 mm beyond the edge | as +x usable | Trim to the usable rectangle |
| **+x usable** | 48.70-80.23, 55.01-68.30 | 419.0 / 419.0 | none (traces and tented vias only) | 1.0 mm + any CR bottom part | VBUS pour 139.2 mm² (x 65.5-79.6, 16 V bus), 5V 0.508 mm trace (L16) 16.6 mm + via, 3V3, 8 logic nets, 23 tented vias | L-FC 14.9, REG-FC 15.5, VSW-FC 14.3 mm / 0.15 mm (REG-5V body 0.50 mm) | 729.9 mm (split 671.6 mm, -49 %) | none covered; C-D2/R171 0.5 mm above, RENC2 0.5 mm right | 0.51-0.73 kHz unpropped; 2.2-3.2 kHz with a tip prop | Largest free area and shortest taps; hottest edge; needs a far-end support |
| +x core | 48.70-65.00, 55.01-67.14 | 197.7 / 197.2 | none | 1.0 mm + any CR bottom part | no power pour; 5V trace (L16) + via, 3V3, logic | VSW-FC 15.4 mm / 0.15 mm | 928.4 mm (split 885.3 mm, -32 %) | none | 1.7-2.4 kHz unpropped | Short, no bus copper; same hot edge |
| +y usable | 17.70-39.72, 67.14-76.51 | 206.3 / 202.9 | ROP1-FC, ROP2-FC 0.60 | 1.6 mm | N$8 trace only, 1 GND via; no power copper | L-FC 0.50, VSW-FC 5.1, REG-FC 7.6 mm / 15.7 mm | 1451.6 mm (split 1279.3 mm, -2 %) | none; J-FC rear face 1.57 mm left (screws and wire entry unaffected) | 4.2-5.9 kHz unpropped | Clean and cool; switching-node neighbour; no tap gain |
| +y wide | 17.70-48.70, 67.14-76.51 | 290.5 / 242.1 | OP-FC 1.75 (SOIC), MDAC-FC 1.10 | 2.75 mm (TSW 2.54 mm too low) | droop analog nets (VDROOP-FC, N$7, N$8), 3V3 | as +y usable / 12.3 mm | as +y usable | OP-FC, MDAC-FC, RD/RINJ droop resistors | as +y usable | Needs a raised stack (DW, section 7) |
| -y usable | 17.70-48.70, 26.00-34.14 | 252.3 / 196.4 | C4A-BT, C4B-BT 1.35; BAL 1.00 | 2.35 mm | VBT 2.54 / 1.524 / 1.016 mm traces (charge path <= 3.21 A + LM1084 input), VOUT-BT pour 21.3 mm², VBAL+ 0.406 mm, VCHG-IN 1.524 mm (L16), BAL cell nets | VSW-BT 2.96, REG-BT 3.48, L-BT 5.22 mm / 3.55 mm | 1340.7 mm (split 1299.3 mm, -1 %) | BAL pad 8 (T22, PM11), RB1A/RB1B/CBL1-3/CBLD, PM4 step 1b thermocouple exit at y ~34 | 5.4-7.6 kHz unpropped | Covers rework points and the noisiest copper |
| -x | 3.28-17.70, 26.42-67.35 | 590.2 / 80.2 | J-BL 21.70, J-NTC 13.90 | 22.7 mm | VBAL+, VMID, N$34 (NTC) traces | L-BT 6.2 mm / 31.8 mm | not evaluated | J-BL screws and wire entry, J-NTC push buttons | - | Excluded (section 3) |
| Off-board past x = 0 | -20.0-0.0, 26.42-67.35 | 818.6 off-board | must clear J-BL 21.70 | >= 22.7 mm | none on the MB | - | not evaluated | sits in the wire-entry path of J-BL, J-NTC | - | Excluded (section 3) |
| +y to MB edge | 17.70-48.70, 67.14-98.04 | 957.9 / 630.5 | L-FC 5.0 | 6.0 mm | VFC pour 70.9 mm², VSW-FC pour 30.6 mm², VOUT-FC 16.7 mm² | over L-FC, REG-FC, VSW-FC / 12.3 mm | not evaluated | FC boost and droop parts | - | Not recommended |
| -y to MB edge | 17.70-48.70, 0.00-34.14 | 1058.3 / 686.1 | L-BT 5.0 | 6.0 mm | VBT pour 121.8 mm², VSW-BT pour 44.3 mm², VOUT-BT 35.6 mm², VCHG-IN (L16) | over L-BT, REG-BT, VSW-BT / 3.55 mm | not evaluated | BT boost, BAL network | - | Not recommended |

The two zones that survive every hard constraint with the standard 2.54 mm header body are +x usable (or its +x core
part) and +y usable. The -y usable zone is feasible with the 2.54 mm body, but it covers rework points and sits
3-5 mm from the BT boost switching node. Section 4 gives the evidence row by row.

### 1.2 Area consequence

The r6 courtyard estimate is ~1082 mm², placed on ~881 mm² of top area and ~591 mm² of bottom area (design H.22(k)).
A single-sided CR needs the whole ~1082 mm² on the top side. Table 2 lists the top area that each extension adds,
trimmed by the 0.5 mm courtyard limit on its free edges.

Table 2. Indicative single-sided utilisation (courtyard total ~1082 mm² from design H.22(k)).

| Extension | Added top area (courtyard-usable, mm²) | Top area total (mm²) | Single-sided utilisation |
|---|---|---|---|
| none (r6) | 0 | 881 | 123 % (double-sided required) |
| +x usable | 31.03 x 12.29 = 381 | 1262 | 86 % |
| +x core | 15.80 x 11.13 = 176 | 1057 | 102 % |
| +y usable | 21.02 x 8.87 = 186 | 1067 | 101 % |
| -y usable | 30.00 x 7.64 = 229 | 1110 | 97 % |
| +x usable and +y usable | 567 | 1448 | 75 % |

The r6 top side ran at 77 % (678 of 881 mm²). Only +x usable, alone or combined with +y usable, brings a single-sided
CR near that density. A single-sided CR would remove the bottom-side passives and with them the bottom keep-out and
power-copper-shadow rules of A.7; the flush-cut rule for the 22 header tails would remain.

## 2. Heights of the MB parts within 40 mm of the CHG footprint

### 2.1 Height table

Table 3 gives the seated height of every MB part within 40 mm of the CHG pad envelope (the list of
`round4/calc/mb_neighbours_out.txt`). An IPC-7351 name gives the maximum body height in hundredths of a mm
(CAPC3225X135 = 1.35 mm).

Table 3. MB part heights (generated in `work/heights_40mm.txt`).

| Parts | Package | Height (mm) | Source |
|---|---|---|---|
| J-BL | CUI_TB005_-762-03BE (TB005-762-03BE) | 21.70 | `TB005-762_CUI.pdf` p.2, side view |
| J-FC, J-BT | CUI_TB005-762-02BE (TB005-762-02BE) | 21.70 | `TB005-762_CUI.pdf` p.2 |
| J-NTC | 691411410002 (Würth WR-TBL 4114, push-in) | 13.90 to the push-button top; body 9.20 | Würth 691411410002 datasheet rev 001.004 p.1 (13.9 +-0.1, 9.2 +-0.1) |
| L-FC, L-BT | HCM1A1305V3-2R2-R | 5.0 | Eaton catalogue listing 13.8 x 12.9 x 5.0 mm (web); `TODO(verify: Eaton ELX1488 datasheet)` (download failed) |
| REG-5V (LM1084) | TO254P1524X483-4N (KTT TO-263) | 4.83 | IPC-7351 name |
| CO-5V | CAPM3528X210 (tantalum 3528) | 2.10 | IPC-7351 name |
| OP-FC, OP-BT | D0008A (SOIC-8) | 1.75 | `OPA197IDR.pdf`, "SOIC - 1.75 mm max height" |
| C-D7, C-D9 | CAPC3216X135 | 1.35 | IPC-7351 name |
| C4A/B/C-FC, C4A/B/C-BT | CAPC3225X135 | 1.35 | IPC-7351 name |
| SNS-FC, SNS-BT | SOP65P640X120-20N (TSSOP-20) | 1.20 | IPC-7351 name; `INA253A1IPWR.pdf` "TSSOP - 1.2 mm max height" |
| MDAC-FC, MDAC-BT | RM_10_ADI (MSOP-10) | 1.10 | `ad5426_5432_5443.pdf` RM-10 outline "1.10 MAX" |
| CIN-5V, C-D1..C-D5, C-D8, C-D10..C-D12, C1-FC, C3-FC, C1-BT, C3-BT | CAPC2012X110 (0805) | 1.10 | IPC-7351 name |
| D-FC-EN, D-BT-EN, D-BC-RG, D-MT-EN, D-BC-FC, D-BT-SQ | IC_RT1987N-A (VDFN-12) | 1.00 | `RT1987_DS-00.pdf` section 19, dimension A 0.800-1.000 |
| REG-FC, REG-BT | CONV_TPS61288LRQQR (VQFN-HR) | 1.00 | `TPS61288LRQQR.pdf` "VQFN-HR - 1 mm max height" |
| BAL | DRB8 (VSON-8) | 1.00 | `BQ29200_TI.pdf` "VSON - 1 mm max height" |
| CSNS-*, C2/C5/C6/CC-*, CBL1-3, CBLD | CAPC1608X85 (0603) | 0.85 | IPC-7351 name |
| 0603 resistors (R1/R2-BUS, RENC1/2, ROS, R2-CHG, ROP*, RD*, RINJ*, RC*, R1/R2-FC, R1/R2-BT) | RESC1608X60 | 0.60 | IPC-7351 name |
| C-DC1..C-DC12 | CAPC1005X60 (0402) | 0.60 | IPC-7351 name |
| R1-CHG, RB1A, RB1B, RB2, RB3 | RESC1005X40 (0402) | 0.40 | IPC-7351 name |
| J1 (and J2) | Amphenol 87606-324LF receptacle | unknown | `TODO(measure)`; the vendor drawing returned HTTP 403 |
| U$1 | Teensy 4.1 on two PREC024SAAN-RC headers | unknown | `TODO(measure)` seated top height |
| J3 | Würth 61302021821 receptacle | unknown | `TODO(verify: Würth 61302021821 drawing)` |
| CHG (Ag105, to be removed) | DIL module | header body 2.54, module PCB 1.60, parts <= 9 above the PCB top, pins 3.00 below the body, 0.64 mm square | `AG105_Silvertel.pdf` Figure 11 (p.21); tolerance +-0.5 unless stated |

### 2.2 Items without a sourced height

Some fitted items are not in the `.brd` and have no recorded height or position. These items are the 10 kOhm
EN-to-GND bodge resistors on the RT1987 enable nets (one is inside the CHG footprint at D-BT-SQ, gate B2), the fitted
74HC14 Schmitt buffer and the 2026-08-16 encoder reroute wires (pins 2/8 to 14/15, which pass near RENC1/RENC2 at the
+x end of the brief zone), R171 after PM3 (an 0805 standing on C-D2 pad 1 with Kapton) and any OPA197 5 V bodge wire
near OP-FC. Each is `TODO(measure)` before an outline is frozen (section 8).

## 3. Terminal blocks J-BL, J-NTC, J-FC, J-BT

### 3.1 Orientation from the footprints

The TB005-762 package places the body from -7.90 mm to +4.70 mm across the pin row (`.brd` silkscreen layer 21), and
the datasheet section A-A puts the pins 4.70 mm from the rear face and the clamp opening on the far face. With the
R270 rotation on the MB this puts the wire-entry face of J-BL, J-FC and J-BT at x 3.53 (J-BT 3.78), facing -x toward
the MB edge. The rear faces are at x 16.13 (J-BT 16.38) and the pin-1 dots are on the rear side. The M3 clamp screws
(TB005 wire assembly table: M3, 0.5 N·m) are driven vertically from the top of the 21.70 mm body. A scaled reading of
section A-A (about 9.7 px/mm, +-0.5 mm) puts the screw axis about 2.0 mm from the pin row toward the wire face, i.e.
near x 9.4 on the MB.

J-NTC (Würth 691411410002, WR-TBL 4114 screwless push-in, "horizontal cable entry") has its body at x 3.65-16.15,
y 53.01-67.25, with two pin rows at x 7.152 and x 12.152 (`.brd` package, R90). The push buttons sit on top (13.90 mm).
The entry face is inferred to face -x like the TB005 blocks, because the body is at the MB edge; the datasheet drawing
does not settle the face. `TODO(verify: inspection of the fitted J-NTC)`.

### 3.2 Effect of an overhang

The CR left edge at x 17.70 is 1.57 mm from the J-BL and J-FC rear faces, 1.32 mm from the J-BL keep-out (layer 39,
x 16.38) and 1.55 mm from the J-NTC body. A -x extension would have to pass over a 21.70 mm body; a pin-header stack
cannot reach that height, and a CR above the blocks would cover the J-BL and J-FC screw tops and the J-NTC push
buttons. An off-board extension past x = 0 would additionally sit in the wire path that leaves the -x faces. J-BL
therefore stays pluggable (screw access from the top, wires from -x) for every zone except -x and past-x = 0, and those
two are excluded. The +y and -y zones keep x >= 17.70 and leave J-FC and J-BL untouched.

## 4. Zone evidence

### 4.1 +x zone (toward Teensy J1)

The brief zone x 48.70-82.00, y 55.00-69.00 holds C-D2 (0805, 1.10 mm) at its top edge (y 68.80-70.90) and RENC2
(0603, 0.60 mm) at its right edge (x 80.73-82.33). C-D2 pad 1 carries the R171/T2 joint (PM3), and RENC2 is a named
rework point of gate P8 ("remove RENC2"). The J1 body starts at x 83.06, and the tap pins stand in its x 84.58 and
x 87.12 position columns. The usable rectangle x 48.70-80.23, y 55.01-68.30 keeps 0.5 mm from C-D2, RENC2 and the
REG-5V body (y 54.51) and contains no MB part at all (419.0 mm², all part-free).

The copper under +x usable is the following:

- the **VBUS L1 pour** (139.2 mm² of the polygon x 65.53-79.55, y 19.56-72.64), which carries the FC-channel bus
  current from D-FC-EN (just above the zone) toward the bus node; OC_FC is 1.4 A (design H.12) and the per-channel
  bound is ~3 A (CLAUDE.md bodge record of 2026-07-10);
- a 0.254 mm VBUS trace (17.8 mm) that feeds the R1-BUS divider (signal current);
- the **5V** 0.508 mm trace on layer 16 (16.6 mm, the LM1084 output to the Teensy, <= 0.30 A by section 5.1) with a
  tented via at (59.39, 55.58);
- 3V3 0.508 mm traces and eight logic nets (CB-DISABLE, CHRG-STAT, CS-MDAC-FC, D-FC-EN, EN-REG-BT, MPPT-DISABLE,
  SCL, SDA), all 0.254 mm;
- 23 vias, all tented: the `.brd` design rule `mlViaStopLimit` is 9999 mil, so no via drill gets a stop-mask opening,
  and the `.brd` has no plain stop-mask shapes.

The nearest switching nodes are on the FC boost: L-FC 14.9 mm, the VSW-FC pour 14.3 mm and REG-FC 15.5 mm away. The BT
boost is more than 32 mm away. The zone edge is 0.15 mm from the 5V pour rim and 0.50 mm from the REG-5V body, at the
tab end of the LM1084 (tab pad y 46.65-54.26), so it is the hottest edge of any candidate (section 5). The +x core
rectangle (x <= 65.00) avoids the VBUS pour and halves the cantilever length.

The +x extension shortens the taps more than any other zone. A split field at about (70, 62) takes 18 of the 20 taps:
T2 (C-D2) 47.0 -> 8.2 mm, T20 (ROS pad 2) 58.0 -> 13.9 mm, the J1 taps 54-60 -> 17-32 mm, the J2 taps 77-90 ->
40-50 mm and T1 (C-D6) 67.6 -> 50.5 mm. T22 (BAL pad 8) and T9 (SNS-BT) stay on the r3 field. The straight sum falls
from 1308.8 mm to 671.6 mm (-49 %). The extension also reaches pad 10 (VIN+, (46.00, 61.94)), which lies at its root.

The +x usable extension is a 34.2 mm cantilever beyond the x 45.998 pin column. Its first bending mode is estimated at
0.51-0.73 kHz without a far support and 2.2-3.2 kHz with a tip prop (section 6.4). It covers nothing that needs
rework; CO-5V, the LM1084 and the CO-5V pad 1 tap point (T18 option) remain open from above.

### 4.2 +y zone (between the CR top edge and L-FC)

The brief zone starts at the CHG silkscreen (y 67.60); the CR outline already ends at y 67.14, so the usable
rectangle is x 17.70-39.72, y 67.14-76.51. It stops 0.5 mm below L-FC (y 77.01) and 0.5 mm left of OP-FC
(x 40.22, y 67.30-75.28). Under it are only ROP1-FC and ROP2-FC (0603, 0.60 mm), one 0.254 mm N$8 trace and one GND
via; there is no power copper. With the 2.54 mm body the air over the resistors is 1.94 mm.

The zone is the coolest on-board option (15.7 mm from the 5V pour) and the cantilever is short (12.0 mm from pin 11;
f1 4.2-5.9 kHz unpropped), so a far support is not needed. Its cost is the FC boost: L-FC (5.0 mm, shielded molded) is
0.50 mm from the top edge, the VSW-FC pour 5.1 mm and REG-FC 7.6 mm. Comparator parts with mV-level thresholds (H1,
UVB, BT_OK, design B.2) are better kept at least 10 mm from L-FC, so the band suits power, logic and connector parts
(J101, W pads). Tap lengths gain nothing (split sum 1279.3 mm, -2 %). Covering OP-FC and MDAC-FC ("+y wide") needs
>= 2.75 mm of body (OP-FC 1.75 mm), which the TSW 2.54 mm body does not give; the overhang also sits over the FC
droop analog nets.

### 4.3 -y zone (BAL / BQ29200 and the BT boost output caps)

The rectangle x 17.70-48.70, y 26.00-34.14 covers BAL (1.00 mm), CBL1-3 and CBLD (0.85 mm), RB1A, RB1B, RB2, RB3
(0.40 mm) and C4A-BT, C4B-BT (1.35 mm). The 2.54 mm body leaves 1.19 mm of air over C4A/C4B-BT and 1.54 mm over BAL,
so no CR bottom part may sit over those parts. The copper is the noisiest and highest-current of the on-board zones:

- the VBT 2.54 mm trace (28.19, 25.15)-(34.80, 31.75) and the 1.016/1.524 mm VBT traces, which carry the charge
  current (<= 3.21 A, design A.8) and the LM1084 input;
- the VOUT-BT pour (21.3 mm²) and the C4 output capacitors of the BT boost;
- VBAL+ (0.406 mm, pack top through J-BL) and the BAL cell nets VC1, VC2, VC1_CB, VMID;
- VCHG-IN 1.524 mm on layer 16 at x 39.62 (MB underside; it matters only for a drilled hole).

The VSW-BT pour is 2.96 mm, REG-BT 3.48 mm and L-BT 5.22 mm from the zone. The 5V pour is 3.55 mm away. The zone
covers BAL pad 8 (T22, PM11), so the T22 joint must be made before the CR is fitted and cannot be reworked without
desoldering 22 joints. The same applies to RB1A (gates BG-17b and B-PKN of the battery-isolation design) and CBL2
(gate C-1 of that design), which those gates name as check or rework points. The PM4 step 1b thermocouple lead exits under the CR low-y edge at y ~34 and would have to move.
Tap lengths gain nothing (split sum 1299.3 mm, -1 %; T22 10.5 -> 7.2 mm). The cantilever is short (10.5 mm,
f1 5.4-7.6 kHz).

### 4.4 Off-board options past an MB edge

The CR is 17.70 mm from the -x edge, 30.90 mm from the +y edge (98.04) and 34.14 mm from the -y edge. The -x edge is
behind the 21.70 mm terminal blocks (section 3). Reaching the +y or -y edge means crossing L-FC or L-BT (5.0 mm), so the
stack needs >= 6.0 mm of body, and the extension then lies over a VSW pour (30.6 or 44.3 mm²) and a boost IC. The MB
has only two plain mounting holes, (3.30, 3.30) and (3.30, 94.74), drill 3.80 mm, both at the -x edge behind J-BT and
J-FC. No off-board path is free of these costs.

## 5. LM1084 dissipation and board temperature (ESTIMATE)

### 5.1 Dissipation

The `.sch` 5V net feeds U$1 VIN (the Teensy 4.1, which also supplies the MB 3V3 loads), J2.01/02 (the same Teensy VIN
position) and OP-FC/OP-BT V+. REG-5V input is VBT, i.e. the pack. Equation (1) is the dissipation model of SNVS037H
section 7.4.1.1.

P_D = (V_IN - 5.0 V) x I_L + V_IN x I_G (1)

The inputs are the logic baseline of 0.15-0.25 A (repository figure "Teensy + Ethernet PHY ≈ 150-250 mA", AGENTS.md
and `docs/modeling/bond-graph.md`; "~0.25 A" in `controller_design/bench_calibration_manual.md`), 2 x 1.3 mA for the
OPA197 (OPA197IDR.pdf, IQ max per amplifier), 0-40 mA for the encoder emitters (their rail after the 2026-08-16 bodge is
unrecorded, `TODO(measure)`), I_G = 5 mA typical and 10 mA maximum (SNVS037H section 7 text and section 5.5), and
V_IN = 7.4-8.4 V (the 2S pack band, CLAUDE.md fw v30 limits). Equation (1) then gives P_D = 0.40 W (7.4 V, 0.153 A,
5 mA), 0.63 W nominal (7.9 V, 0.203 A, 5 mA) and 1.08 W (8.4 V, 0.293 A, 10 mA).

### 5.2 Temperature model

The datasheet values are RθJA = 40.4 °C/W on the JEDEC high-K board, ψJB = 22.0 °C/W and RθJC(bot) = 0.65/2.7 °C/W
(control/output section) for the KTT package (SNVS037H section 5.4). Figure 7-14 of SNVS037H gives about 70 °C/W of
PCB heat-sink resistance at ~400 mm² of copper (read from the plot) and more below that area. The MB 5V island under the
tab is 153.1 mm² (polygon outline, `.brd`), so Figure 7-14 alone would predict a pour rise of at least 28-76 °C. The
MB, however, has board-wide GND pours on both layers under and around the island.

The estimate therefore uses a two-layer radial fin. The island (equivalent radius 7.64 mm) couples to the GND copper
through the FR4 under it (27 K/W, k 0.3 W/m·K, 1.5 mm) in parallel with the lateral path across the isolation gap
(R_couple 12-27 K/W). The GND copper spreads as a fin with 0.7-1.5 layer-equivalents of continuous 1 oz copper and a
total surface coefficient of 18-28 W/m²K on both faces (characteristic length 23-27 mm, spreading resistance
12-24 K/W). The temperature at distance d from the pour edge is P_D x R_spread x K0((a + d)/Lc)/K0(a/Lc). The model
omits the boosts, the Teensy and the enclosure air rise; "ambient" means the local air in the enclosure.

### 5.3 Estimated rise above the local ambient

Table 4 gives the estimated rise of the 5V pour and of the MB surface at 1, 5, 10 and 20 mm from the pour edge. The
three columns per power level are the best, nominal and worst parameter sets of section 5.2.

Table 4. LM1084 temperature-rise ESTIMATE (`work/mb_mech_calc.py`, function `lm1084`).

| P_D | 5V pour / tab | 1 mm | 5 mm | 10 mm | 20 mm |
|---|---|---|---|---|---|
| 0.40 W | 9.7 / 13.3 / 20.6 °C | 4.5 / 5.5 / 8.8 °C | 3.3 / 4.1 / 6.3 °C | 2.4 / 3.0 / 4.5 °C | 1.4 / 1.7 / 2.4 °C |
| 0.63 W (nominal) | 15.1 / 20.6 / 32.0 °C | 7.0 / 8.6 / 13.6 °C | 5.2 / 6.4 / 9.9 °C | 3.8 / 4.6 / 6.9 °C | 2.2 / 2.6 / 3.7 °C |
| 1.08 W | 26.0 / 35.5 / 55.0 °C | 12.0 / 14.8 / 23.5 °C | 9.0 / 10.9 / 17.0 °C | 6.5 / 7.9 / 11.9 °C | 3.7 / 4.4 / 6.3 °C |

The junction sits a further P_D x RθJC(bot) = 0.3-2.9 °C above the pour, so the junction rise is about 10-58 °C. On
the JEDEC high-K board (two internal planes) the same powers give 16-44 °C (RθJA); that is a lower bound for this
two-layer MB. The
operator's "runs hot" report is consistent with the nominal row. The +x zone edge is at d ≈ 0.15 mm, so its first
millimetre runs at roughly the d = 1 mm column, and the LM1084 tab-end side face (4.83 mm tall) views that edge
directly across 0.50 mm. The +y usable zone starts at d = 15.7 mm and the -y zone at d = 3.55 mm. The r6 CR body itself
already sits 0.83 mm from the pour rim at its right edge (x 48.70), with CO-5V 0.60 mm away.

A practical reading of Table 4 is a 5 mm band along the +x extension's low-y edge (y 55.0-60.0) for parts that do not
care about temperature (tap pads, wire holes, connectors), and the comparators, references, BAV199 clamps and
dividers at d >= 10 mm. T-A-07 already needs the board temperature near the LM1084 for the BAV199 and D103 leakage.

### 5.4 Measurement that replaces the estimate

The estimate is replaced by one thermal survey (section 8, item M4): thermocouples or an IR camera with emissivity
tape on the LM1084 tab, on the pour rim, and on the MB surface at 1, 5, 10 and 20 mm from the pour edge along the
centre lines of the +x, +y and -y zones; the MB in its enclosure with the lid closed; Run with Ethernet and SD logging
active; V_batt 8.4 V and 7.4 V; a 30 min soak; the LM1084 input current logged to fix P_D; the enclosure air temperature
logged as the ambient.

## 6. Far-end support and pin-field load (ORDER OF MAGNITUDE)

### 6.1 Support options

Table 5 lists the far-end support options with what each needs and how it fails. The spot search of
`work/mb_support_spots.py` (4 x 4 mm foot, part bodies + 0.25 mm and vias excluded, the 5V island + 1 mm excluded)
supplies the locations.

Table 5. Far-end support options.

| Option | Availability per zone | What it needs | Failure mode |
|---|---|---|---|
| Standoff to an MB mounting hole | Only (3.30, 3.30) and (3.30, 94.74), drill 3.80 mm, both at the -x edge behind J-BT/J-FC (21.70 mm); 52.5-68.8 mm from +x usable, 23.2 mm from +y usable, 26.9 mm from -y usable | an arm from the CR to a male-female M3 standoff stacked on the MB mounting screw; the arm must pass L-FC/L-BT and the terminal blocks; the MB mounting scheme is unrecorded (`TODO(measure)`) | a long arm with its own resonance; the CR load enters through the MB screw preload; blocks J-FC/J-BT access |
| Bonded foot on solder mask (a height-matched spacer, e.g. a cut TSW body segment with pins removed, 2.54 mm, or a nylon spacer) | +x usable: 1795 grid points qualify; the farthest is (78.2, 66.3), 32.3 mm from the pin field, on mask over the VBUS pour; off every power pour the farthest is (62.7, 61.3), 16.7 mm out. +x core: (62.95, 65.0). +y usable: 93 % of the zone. -y usable: 5 % of the zone, farthest (31.2, 29.8) | a flat masked area free of parts; a non-conductive adhesive rated for the local temperature (Table 4); a height equal to the header body (+0.125 mm if the polyimide sheet lies under the body) so the pins are not preloaded; a removal method that does not scrape the mask | adhesive peel or creep under vibration and thermal cycling; a height mismatch preloads the joints; mask damage over the VBUS pour exposes 16 V bus copper on removal; heat softening within 5 mm of the pour |
| Extra soldered pins into unused MB through-holes | None. The unconnected through-hole pads on the MB are the 11 CHG NC holes (already anchors) and Teensy U$1 option pads under the Teensy (x 92-102). All vias are 0.35 mm drill and tented; a 0.64 mm pin cannot enter | a new drilled hole, which is an MB modification; no foot-qualified spot in +x, +x core or -y has 3 mm of clearance to non-GND copper on both layers; +y usable has GND-only spots (e.g. (19.7, 74.4)) | a drilled hole perforates both GND pours and must be recorded as a bodge; a mis-located hole cuts a trace |
| Chassis post past an MB edge | Only after crossing the terminal blocks (-x) or L-FC/L-BT (±y, >= 6.0 mm body); no candidate zone reaches an edge | the enclosure/chassis geometry (`TODO(measure)`) | the longest cantilever of all options; noise exposure of section 4.4 |
| Lid-side compression pad on the CR top | Any zone, if the enclosure lid sits a known height above the CR | a measured lid clearance and a compliant pad | lid tolerance either leaves a gap (no support) or preloads the CR into the pins |

### 6.2 Pin-field load check

The check treats the CR as a rigid plate on 22 equal axial springs (pin group: column A at x 20.998, 12 pins;
column B at x 45.998, 10 pins; centroid (32.36, 50.51) mm; Σ(x - x_c)² = 3409 mm², Σ(y - y_c)² = 1455 mm²). Equation (2)
gives the worst pin load for a shock a normal to the MB.

F_pin = (m_CR + m_ext) a / 22 + m_ext a r_cg r_max / Σ r² (2)

The assumed inputs are a main CR of 5-10 g, a populated areal mass of 0.6-0.8 g/cm² for the extension, 10 g and 30 g
of shock (30 g is an assumed RC-vehicle bump class, `TODO(measure)`), and a tip prop that carries half the extension
load. Table 6 gives the results.

Table 6. Worst axial pin load (ORDER OF MAGNITUDE; `work/mb_pinload.py`).

| Extension | m_ext (g) | CG arm r_cg (mm) | 10 g: no support / tip prop (N) | 30 g: no support / tip prop (N) | Tip-prop reaction at 30 g (N) |
|---|---|---|---|---|---|
| none (r6 CR alone, 5-10 g) | 0 | 0 | 0.022-0.045 | 0.067-0.134 | - |
| +x usable | 2.51-3.35 | 32.1 | 0.065-0.102 / 0.035-0.062 | 0.196-0.305 / 0.106-0.186 | 0.370-0.493 |
| +x core | 1.19-1.58 | 24.5 | 0.039-0.067 / 0.028-0.053 | 0.117-0.201 / 0.085-0.158 | 0.175-0.233 |
| +y usable | 1.24-1.65 | 21.3 | 0.053-0.085 / 0.034-0.060 | 0.158-0.255 / 0.102-0.180 | 0.182-0.243 |
| -y usable | 1.51-2.02 | 20.4 | 0.058-0.092 / 0.036-0.064 | 0.175-0.277 / 0.109-0.191 | 0.223-0.297 |

An in-plane shock puts 0.045-0.27 N of shear on each pin (10-20 g of CR, 10-30 g). With the TSW body clamped between
the boards the free pin length is zero; if 2.54 or 5.08 mm of pin were unsupported, the bending stress would be
1.3-15.6 MPa. A 0.64 mm square pin has a cross-section of 0.41 mm², i.e. ~141 N at an assumed 345 MPa yield
(phosphor bronze per Samtec F-226; temper and yield not stated, `TODO(verify)`). A handling push of 10 N at the +x
usable tip (47.9 mm from the pin centroid) gives about 2.4 N on the worst pin.

The +x usable extension raises the worst pin load by a factor of about 2.0-3.6 against the r6 CR of the same main mass,
but every shock case stays two to three orders of magnitude below the pin section capacity. Static strength therefore does not decide the
support. The deciding quantities are the extension's resonance against the vehicle spectrum, the cable loads that
land on the extension (W1-W4, W5 mating force, `TODO(verify: socket insertion force)`) and the handling loads. The
Ag105 precedent does not cover them: its centre of gravity sat on the pin-field centroid, so it put no moment on the
pins.

### 6.3 Extension strip stress

A 30 g shock bends the +x usable strip (1.6 mm FR4, E = 20 GPa assumed, mass factor 1-2) with a root stress of
1.2-2.4 MPa and a tip deflection of 22-44 um. The +y strip gives 0.15-0.30 MPa. These values are negligible against
FR4 strength.

### 6.4 Extension resonance

Equation (3) gives the first bending mode of a uniform strip clamped at the pin column, with β1L = 1.875 (cantilever)
or 3.927 (clamped with a tip prop).

f1 = (β1L)² / (2π L²) x sqrt(E t² / (12 ρ m_f)) (3)

With E = 20 GPa (assumed, `TODO(verify: fab laminate datasheet)`), ρ = 1850 kg/m³, t = 1.6 mm and a part mass factor
m_f = 1-2, the estimates are: +x usable (L 34.2 mm) 0.51-0.73 kHz unpropped and 2.2-3.2 kHz propped; +x core (19.0 mm)
1.7-2.4 kHz; +y usable (12.0 mm) 4.2-5.9 kHz; -y usable (10.5 mm) 5.4-7.6 kHz. The real root is compliant, so these are
upper estimates. The vehicle spectrum is not measured (item M5). The +x usable extension without a prop is the only
candidate with an estimated mode below 1 kHz; whether the drivetrain excites that band is decided by M5.

## 7. Header stack-up and the D-2 envelope

### 7.1 What the Ag105 occupied

Figure 11 of `AG105_Silvertel.pdf` (p.21) gives a 2.54 mm header body under the module PCB, a 1.60 mm module PCB, a
keep-out of 9 mm above the PCB top (the "9" is underlined in the drawing, which by drawing convention marks a value not
to scale or a maximum), pins 3.00 mm long below the body and 0.64 mm square, a 32 x 37 mm keep-out in plan and a module
outline of 28.6 +-1.5 x 33.1 +-1.5 mm (nominal +-0.5 mm unless stated). The nominal Ag105 envelope is therefore
2.54 + 1.60 + 9 = 13.14 mm above the MB over the footprint. The module mass is not stated (`TODO(measure)`: weigh the
module after PM1).

Gate D-2 (`docs/reviews/battery_isolation_2026-11-07/detailed_design_IC1.md`, section 15.2) asks for the measured module
standoff; it has not been measured. The tallest part on the fitted module is also unmeasured. The as-built envelope that
is known to fit the enclosure is s_Ag + 1.60 + h_Ag over the 32 x 37 mm footprint, where s_Ag is the D-2 standoff
(nominal 2.54 mm) and h_Ag the module part height (<= 9 mm by the keep-out).

### 7.2 Header options

Table 7 lists the header options that fit the 1.1 mm MB holes and the 0.64 mm square post.

Table 7. Header and stacking options.

| Option | Body / stack height | Source | Remarks |
|---|---|---|---|
| Samtec TSW (all straight lead styles) | 2.54 mm body | Samtec F-226 TSW/HTSW catalogue page: A - B - C = 2.54 mm for styles -05 (8.51 - 3.30 - 2.67), -07 (10.92 - 2.54 - 5.84), -14 (13.46 - 2.79 - 8.13), -18 (23.62 - 2.79 - 18.29) | the body seats on the MB, so the standoff is fixed at 2.54 mm (2.665 mm on the 0.125 mm polyimide sheet); tails B 2.41-22.86 mm; insulator PBT, terminal phosphor bronze; recommended hole 1.02 +-0.03 mm (MB holes are 1.10 mm, Ag105 DS 1.1 +-0.05); per-pin rating 4.3-6.3 A mated, 2 positions powered |
| Samtec DW / EW / ZW Flex Stack board stacker | two bodies; stacker height specified in 0.001 in, 0.200 in (5.08 mm) minimum, body position in 0.005 in (0.13 mm) steps | Samtec F-226 DW/EW/ZW page; Samtec .100 in terminals overview | tails DW 2.79 mm, EW 8.38 mm, ZW custom >= 1.40 mm; non-standard, non-returnable; the catalogue recommends mechanical board spacers "for added mechanical stability" |
| Samtec MTSW / HMTSW | variable post height (Flex Stack, 0.13 mm steps; 14 terminal lengths) | Samtec .100 in terminals overview | body height not confirmed, `TODO(verify: Samtec MTSW drawing)` |
| TSW with an added spacer under the body | any height | - | a loose spacer must be captured by the pins; tail length B must reach through the MB |
| Samtec ESW / ESQ elevated socket on the MB, TSW on the CR | socket body + mating height | F-226 lists ESW, ESQ as TSW board mates; heights `TODO(verify: Samtec ESQ drawing)` | makes the CR removable (T22, BAL and LM1084-adjacent rework); adds height and a contact interface in the 3.21 A battery path |

### 7.3 Relation to D-2 and the enclosure

With the TSW 2.54 mm body the CR stack top is 2.54 + 0.125 (sheet) + t_CR (1.6 mm assumed in PM4, `TODO(verify: CR
fab stack-up)`) + the W5 ribbon fold, which A.3 places at >= 8 mm above the CR top. That is about 12.3 mm plus the
cable, within ~1 mm of the nominal Ag105 envelope of 13.14 mm. Any stack raise (DW, >= 5.08 mm) adds >= 2.54 mm and
exceeds the nominal Ag105 envelope unless the ribbon fold height falls by the same amount (for example a right-angle
J101 at an extension edge). The extension zones are outside the Ag105 footprint, so the Ag105 precedent gives no
vertical envelope there. The tallest MB parts, the TB005 blocks at 21.70 mm, show that a flat lid over the whole MB
already clears >= 21.70 mm; the lid profile over the zones is not recorded (`TODO(measure)`, item M2).

Every zone except +y wide and the edge-reaching options needs no more than the 2.54 mm TSW body (Table 1). A raised
stack is therefore a lever for covering OP-FC/MDAC-FC (2.75 mm) or the inductors (6.0 mm), not a requirement of the
+x, +y or -y usable zones.

## 8. Measurements and verifications needed

The following items replace every `TODO` of this note.

- **M1 (D-2):** before PM1, the Ag105 standoff (MB top to module PCB underside) at the four corners, the seated state
  of its header bodies, the module top height above the MB, and the module mass after removal.
- **M2 (enclosure):** the lid clearance above the MB over the CHG footprint and over each candidate zone; the lid
  profile; the MB mounting scheme on the chassis (only two holes, both at x 3.3); the chassis clearance under the MB
  for the header tails.
- **M3 (heights not sourced):** J1/J2 87606-324LF with the tap pins inserted; the Teensy 4.1 seated top; J3; R171
  after PM3 (orient it away from y < 68.8); the 10 kOhm EN bodge resistors; the 74HC14 and the encoder reroute wires;
  any OPA197 5 V bodge wire; L-FC/L-BT by calipers (Eaton ELX1488 not retrieved).
- **M4 (thermal):** the LM1084 survey of section 5.4, including the LM1084 input current.
- **M5 (vibration):** an accelerometer log on the MB near the CHG footprint in a representative run: peak shock and
  the spectrum around the 0.5-3.2 kHz band of section 6.4.
- **M6 (connectors):** the J-NTC entry face by inspection; the W5 IDC socket insertion force if J101 moves to an
  extension tip.
- **M7 (materials):** the CR laminate flexural modulus and finished thickness from the chosen fab; the Samtec MTSW and
  ESQ drawings if those options are pursued.

## 9. Files

- `work/mb_mech_calc.py`: zone metrics, tap lengths, LM1084 estimate, plan map; output `work/mb_mech_calc_out.txt`,
  `work/mb_mech_calc_out.json`, `work/mb_mech_map.png`.
- `work/mb_pinload.py`: pin-group load, strip stress and resonance estimates (imported by `mb_mech_calc.py`).
- `work/mb_support_spots.py`: bonded-foot and drill-spot search; output `work/mb_support_spots_out.txt`.
- `work/heights_40mm.txt`: the height table of every part within 40 mm.
- Run each with `/c/Users/ricky/miniforge3/python.exe -I <script>` from `round4/work/` (numpy, scipy, matplotlib).
