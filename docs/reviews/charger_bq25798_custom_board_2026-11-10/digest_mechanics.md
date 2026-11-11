# Digest: MB mechanics around the CHG (Ag105) footprint for a custom charger board

Source: `references/Scale Car Board PCB 20260625.brd` (EAGLE XML), parsed by
`scratchpad/cb/mech_parse.py` (stdlib, run with miniforge `python -I mech_parse.py --json mech_parse_out.json`).
Full output: `scratchpad/cb/mech_parse_out.txt` and `mech_parse_out.json`. Every number below comes from that output
unless another source is named.

**Coordinate convention.** Eagle board coordinates, top view, origin at the MB lower-left dimension corner, +x right,
+y UP, mm. This is the convention of `round3/calc/pin_identity_check.py` and wiring design A.8. In KiCad (+y down) enter
y as -y. "Right" = +x, "left" = -x, "high-y" = +y, "low-y" = -y.

**Board facts.** Outline (layer 20) x 0-131.064, y 0-98.044 mm. Two-layer board: signal copper exists on layers 1
(Top) and 16 (Bottom) only (`layerSetup (1*16)`); core 1.5 mm (`mtIsolate`), copper 0.035 mm (`mtCopper`, 1 oz; the fab
weight is not recorded, wiring design A.8). GND is poured on both layers over the whole board
(polygons x 0.09-130.48, y 0.33-97.46/97.71, rank 3).

## 1. The CHG element

- Library `Silvertel Ag105`, package `AG105`, origin (47.498, 34.544), rotation R180, top side.
  Transform: board = (47.498 - px, 34.544 - py).
- The package holds **only a tPlace (layer 21) rectangle and 22 pads**: no tDocu, no tKeepout/courtyard.
- Silk rectangle (line centre): **x 17.198-49.199, y 32.843-67.644 (32.001 x 34.801 mm)**; line width 0.127 mm, so
  the outer edge is x 17.134-49.262, y 32.780-67.708. All distances below are from the silk line centre (the
  "footprint rectangle") unless stated.
- Pads: all 22 are square, drill 1.10 mm, no explicit diameter, so the DRU sets the pad: 1.10 + 2 x 0.275 = **1.65 mm**
  (rvPadTop 0.25, rlMinPadTop 10 mil, rlMaxPadTop 20 mil). Ag105 DS V1.1 Fig 11 recommends a 1.1 +/- 0.05 mm hole for
  the 0.64 mm pins.

| Pin | Pad | x | y | MB net | Pin | Pad | x | y | MB net |
|---|---|---|---|---|---|---|---|---|---|
| 1 | VSEL | 45.998 | 39.084 | none | 12 | MPPTSEL | 20.998 | 61.944 | none |
| 2 | CSEL | 45.998 | 41.624 | none | 13 | THERM | 20.998 | 59.404 | N$34 (0.61 mm trace to J-NTC) |
| 3 | STAT | 45.998 | 44.164 | CHRG-STAT | 14 | VBAT-1 | 20.998 | 56.864 | GND |
| 4 | VIN- | 45.998 | 46.704 | GND | 15 | VBAT-2 | 20.998 | 54.324 | GND |
| 5 | NC1 | 45.998 | 49.244 | none | 16 | VLOAD-1 | 20.998 | 51.784 | none |
| 6 | NC2 | 45.998 | 51.784 | none | 17 | VLOAD-2 | 20.998 | 49.244 | none |
| 7 | SCL | 45.998 | 54.324 | SCL | 18 | VBAT+1 | 20.998 | 46.704 | VCHG |
| 8 | SDA | 45.998 | 56.864 | SDA | 19 | VBAT+2 | 20.998 | 44.164 | VCHG |
| 9 | NC3 | 45.998 | 59.404 | none | 20 | LDIS | 20.998 | 41.624 | none |
| 10 | VIN+ | 45.998 | 61.944 | VCHG-IN | 21 | VLOAD+1 | 20.998 | 39.084 | none |
| 11 | MPPTD | 20.998 | 64.484 | MPPT-DISABLE | 22 | VLOAD+2 | 20.998 | 36.544 | none |

The pad positions equal the A.8 table and `pin_identity_check.py` to 0.001 mm.

- Module envelope from the Ag105 DS V1.1 Fig 11 (p.21, +/-0.5 mm unless stated): module PCB 28.6 +/- 1.5 x
  33.1 +/- 1.5 mm; header standoff 2.54 mm; module PCB 1.60 mm; component keep-out 9 mm above the module PCB; pins
  3.00 mm below the standoff; keep-out plan 32 x 37 mm. In board coordinates the nominal module PCB is x 18.90-47.50,
  y 34.54-67.64 (package corner at the pin-1 edge, 1.5 mm from the pin column, 4.54 mm from pin 1). Nominal top of the
  module above the MB: 2.54 + 1.60 + 9 = **13.14 mm**. **Disagreement:** the DS keep-out length 37 mm exceeds the silk
  length 34.8 mm by 2.2 mm; the silk width 32.0 mm equals the DS keep-out width.

## 2. Neighbours within 25 mm of the footprint edge

Heights: IPC-7351 package names carry the maximum height (e.g. `CAPC3225X135` = 1.35 mm); other heights from the
datasheets named. The full list (about 80 parts) is in `mech_parse_out.txt` sections 2 and 6.

### 2.1 Parts that matter for the overhang decision

| Ref | Part / package | Position, rot | Extent (x0, y0, x1, y1) | Height | Free distance from footprint edge |
|---|---|---|---|---|---|
| REG-5V (LM1084) | LM1084ISX-5.0, TO254P1524X483-4N (TO-263 KTT) | (56.642, 45.974) R90 | courtyard 50.947-62.337, 37.404-54.539; tab pad 51.222-62.062, 46.644-54.264; leads at y 39.574 | 4.83 (LM1084 DS KTT0003B "TO-263 - 4.83 mm max height") | **+x: 1.748 to courtyard**, 2.023 to tab pad, 2.363 to body (docu x 51.562). Tab faces +y, leads face -y |
| 5V pour (LM1084 tab heatsink) | Top polygon | - | 49.784-61.976, 37.846-54.610 | copper | **+x: 0.585** |
| CO-5V | 10 uF tantalum, CAPM3528X210 | (50.800, 39.624) R270 | silk 49.236-52.363, 37.711-41.538; pads x >= 49.698, y 37.266-41.982 | 2.10 | **+x: silk outer edges touch (-0.026 mm)**, pad copper 0.499 |
| C4C-BT | 22 uF 1210 | (52.324, 30.480) R90 | 50.589-54.056, 27.527-33.433 | 1.35 | +x/-y corner, 1.39 |
| J-BL | TB005-762-03BE, 3-pole 7.62 mm | (11.430, 45.720) R270 | courtyard 3.255-16.405, 26.395-49.805; silk to x 17.330 | 21.70 (TB005-762 DS p.2) | **-x: silk overlaps the CHG silk by 0.132 mm; courtyard 0.793** |
| J-NTC | Wurth 691411410002 (BOM: 2-pos terminal block, 7.62 mm, horizontal) | (9.652, 59.944) R90 | courtyard 3.352-16.452, 52.714-67.554 | TODO(verify: Wurth 691411410002 datasheet, not in references) | **-x: 0.745 to courtyard** |
| J-FC | TB005-762-02BE | (11.430, 83.820) R270 | courtyard 3.255-16.405, 72.115-87.905 | 21.70 | -x/+y corner, 4.47 (x 0.79, y 4.47) |
| J-BT | TB005-762-02BE | (11.684, 19.558) R270 | 3.509-17.584, 7.853-23.643 | 21.70 | -x/-y corner, 9.20 |
| C4A-BT, C4B-BT | 22 uF 1210 (BT boost output) | (44.704 / 48.514, 30.480) R90 | 42.969-50.246, 27.527-33.433 | 1.35 | **-y: overlap 0.59** (under the silk line) |
| OP-FC | OPA197, D0008A SOIC-8 | (42.672, 71.628) R90 | silk 40.143-45.201, 67.18-72.38; body docu y 69.60-73.65; lead tips y 68.53-74.72 | 1.75 (OPA197 DS D0008A) | **+y: silk overlap 0.46**; lead tip 0.89 outside |
| MDAC-FC | AD5443 RM-10 (MSOP) | (50.038, 71.628) R180 | 46.599-52.986, 69.855-73.401 | TODO(verify: AD5443 RM-10 outline) | +y, 2.21 |
| BAL (BQ29200) | DRB8 VSON | (24.384, 29.464) R0 | 22.449-26.319, 27.813-31.115 | 1.00 (BQ29200 DS "VSON - 1 mm max height") | **-y: 1.73** |
| RB1A, RB1B, RB2, RB3, CBL1-3, CBLD | balance network 0402/0603 | y 24.7-32.7 | see output | 0.40 / 0.85 | -y: 0.17-5.24 |
| D-BT-SQ (RT1987) | IC_RT1987N-A | (29.718, 50.038) R180 | 27.543-32.418, 48.263-51.813 | 1.00 (RT1987 DS s19, A max) | **under the footprint** |
| C-D11, C-D12, C-DC11, C-DC12 | 0805 / 0402 | y 48.2-53.3 | see output | 1.10 / 0.60 | under the footprint |
| L-FC | Eaton HCM1A1305V3 (FC boost inductor) | (29.464, 83.312) R0 | 20.987-37.544, 76.948-89.675 | TODO(verify: Eaton HCM1A1305V3 datasheet) | +y, 9.30 |
| L-BT | Eaton HCM1A1305V3 (BT boost inductor) | (28.702, 14.478) R0 | 20.225-36.782, 8.115-20.841 | TODO(verify) | -y, 12.00 |
| REG-FC / REG-BT | TPS61288 VQFN-HR | (44.196, 86.106) / (45.466, 20.574) | see output | 1.00 (TPS61288 DS) | +y 15.82 / -y 10.29 |
| Other RT1987 | D-BT-EN (63.754, 22.860), D-FC-EN (68.834, 74.168), D-MT-EN (93.218, 19.050), D-BC-RG (82.550, 4.064), D-BC-FC (92.456, 8.382) | | | 1.00 | 14.85, 18.27, 43.5, 40.9, 47.1 |
| J1 (Teensy socket) | Amphenol 87606-324LF | (85.852, 61.976) R90 | 83.037-88.667, 31.261-93.266 | TODO(verify) | +x, 33.84 |
| CAL (470 uF electrolytic) | EEE-FN1V471UP | (105.156, 15.240) | 99.7-110.6, 7.8-21.9 | TODO(verify) | 51.7 |

No electrolytic capacitor and no inductor lies within 9 mm of the footprint. The tall parts within 25 mm are the four
terminal blocks (21.70 mm), the LM1084 (4.83 mm), the two boost inductors (height unknown) and CO-5V (2.10 mm).

### 2.2 J-BL service envelope (TB005-762 DS p.2)

J-BL is a screw terminal block, not a plug-and-socket connector; "pluggable" means its wires must stay removable.
From the drawing: housing depth 12.60 mm, height 21.70 mm, pins 4.70 mm from the back face. With the pins at
x 11.430 the back face is at x 16.13 and the wire-entry face at x 3.53 (silk x 3.466), so **wires enter from the -x
board edge**, 8 mm strip length, 26-10 AWG. The M3 screws (0.5 N m) are driven from **above** the housing, over x
3.5-16.1, y 26.6-49.6. The overhang therefore must not cover J-BL at any height. The same applies to J-NTC, J-FC and
J-BT. The battery-isolation gate JBL ("J-BL position-3 screw removable",
`docs/battery_isolation_feasibility_2026-11-07.md` line 788) needs this access.

## 3. Board edges

| Side | Footprint edge | Board edge | Free distance |
|---|---|---|---|
| Left (-x) | 17.198 | 0 | 17.198 (fully taken by J-BL, J-NTC and their wire entries) |
| Right (+x) | 49.199 | 131.064 | 81.865 |
| Low-y (-y) | 32.843 | 0 | 32.843 |
| High-y (+y) | 67.644 | 98.044 | 30.400 |

## 4. MB copper under and around the footprint

### 4.1 Under the footprint (x 17.198-49.199, y 32.843-67.644)

The parse reproduces the wiring design A.7 copper list:

- **VBT** (battery positive, Top): 1.524 mm trace (34.798, 31.75) to (34.798, 48.655) to (34.29, 49.163); 1.016 mm run
  at y 34.544 from x 39.116 to 46.99, then on Bottom from (46.99, 34.544) to (57.658, 34.544) (VBT via at (46.99, 34.54)).
  VBT pour (Top) x 30.81-34.98, y 48.34-49.76.
- **VCHG-IN** (Ag105 input, 1.524 mm): Bottom x 39.624 from y 11.43 up to 34.544 (via at (39.62, 34.54)); Top
  (39.624, 34.798) diagonal to (43.18, 38.354), x 43.18 up to y 61.214, then to pad 10 (45.998, 61.944).
- **VCHG** pour (Top, pins 18/19): x 20.14-28.65, y 43.31-49.96.
- Logic: MPPT-DISABLE (Top, y 64.484 across the full width to x 62.4), CB-DISABLE (Top and Bottom, x 31.6-41.5), D-BT-SQ
  EN (Top x 31-37, y 40.8-54.0; Bottom y 35.9-41.0), CHRG-STAT, SCL, SDA (to the +x column), N$31-N$33 (D-BT-SQ
  local), N$34 THERM 0.61 mm, VBAL+ 0.406 mm (low-y-left corner).
- Vias: 23 inside the silk rectangle (18 GND, 2 CB-DISABLE, 1 D-BT-SQ, 1 VBT, 1 VCHG-IN); all 0.35 mm drill,
  0.756 mm auto diameter. Inside the A.7 CR outline (x 17.70-48.70, y 34.14-67.14): 19 vias, **14 GND** (A.7 states 16;
  see section 7).

### 4.2 Candidate overhang bands (out to 30 mm, clipped to the board)

| Band | Power copper | Other copper | Vias |
|---|---|---|---|
| Left x 0-17.2 | none | N$34 0.61 mm (THERM to J-NTC), VBAL+ / VMID 0.406 mm (J-BL to BAL) | 2 GND, 1 S$3 |
| Right x 49.2-79.2 | **5V tab pour** x 49.78-61.98, y 37.85-54.61; **VBUS pour** x 65.53-79.55, y 19.56-72.64; VBT 1.016 mm (Bottom y 34.54, Top x 57-62); 3V3 0.508 mm; 5V 0.406-0.508 mm | SCL, SDA, CHRG-STAT, CB-DISABLE, MPPT-DISABLE, CS-MDAC-FC, EN-REG-BT, D-BT-SQ, D-BT-EN, BT-V | 42 (27 GND) |
| Low-y y 2.8-32.8 | **VBT** traces 0.254-2.540 mm and VBT pour x 7.87-28.19, y 12.7-23.62; **VSW-BT switch-node pour** x 32.84-44.63, y 16.33-23.04; **VOUT-BT** pour x 43.18-53.59, y 21.34-29.72; VCHG-IN 1.524 mm Bottom at x 39.6 | balance network VBAL+, VMID, VC1, VC1_CB, VC2 (0.406 mm), CB-DISABLE, BT-V, EN-REG-BT, BT boost compensation and feedback, MDAC-BT SPI | 40 (37 GND) |
| High-y y 67.6-97.6 | **VSW-FC switch-node pour** x 35.64-43.36, y 81.61-87.55; **VOUT-FC** pour x 44.27-55.93, y 84.66-90.35; VFC pour x 9.22-27.36, y 80.34-87.81; VFC traces 0.305-0.406 mm | OP-FC / MDAC-FC droop nets (N$7, N$8, VDROOP-FC, 3V3, MISO, CS-MDAC-FC) at x 38.7-51.7, y 67.2-79; FC boost feedback | 23 (17 GND) |

Within 9 mm of the high-y edge and left of x 38.9 the only copper is the two GND pours, one 0.254 mm N$8 trace at
x 38.7-42.2 and one GND via at (38.75, 72.65).

## 5. Holes and support-foot spots

- **Existing holes:** the board has only two non-plated holes, (3.302, 3.302) and (3.302, 94.742), drill 3.797 mm,
  32.65 mm and 30.45 mm from the footprint. No element carries a hole; no plated hole >= 2.5 mm exists. **No existing
  hole can take a standoff for an overhang.**
- **Free spots** (grid 0.5 mm; a 6.0 mm diameter circle, for an M3 nylon hex standoff, clear of every Top AND Bottom
  signal wire, every via, every pad and every top-side part extent; only the GND pours lie beneath):

| Side | Spot (x, y) | Clearance radius | Nearest object | From footprint edge |
|---|---|---|---|---|
| High-y | **(23.20, 70.64)** | 6.03 | MPPT-DISABLE trace | 3.0 |
| High-y | **(27.70, 70.64)** | 6.03 | MPPT-DISABLE trace | 3.0 |
| High-y | **(32.20, 70.64)** | 6.03 | MPPT-DISABLE trace | 3.0 |
| Right (beyond the LM1084) | (68.20, 44.84), (68.20, 51.84), (70.20, 48.34), (70.70, 55.34) | 3.15-3.53 | CS-MDAC-FC trace, GND vias | 19.0-21.5 |
| Low-y | none | - | - | - |
| Left | none | - | - | - |

A foot at a high-y spot sits on solder mask over the GND pour. A bonded foot needs no MB change; a drilled M3 hole
would cut both GND pours (no trace) and is an MB modification for the operator to approve.

## 6. Overhang direction: ranked recommendation

Board-underside height needed = tallest MB part under the overhang. A board raised on a 2.54 mm header body (the
Ag105's own standoff, DS Fig 11; gate D-2 has not measured the fitted value) has its underside at about 2.54 mm.

| Rank | Side and usable rectangle (board mm) | Area | Tallest MB part under it | Reasons |
|---|---|---|---|---|
| **1** | **High-y, x 17.50-38.90, y 67.64-76.40** (rect A) | 21.4 x 8.8 = 187 mm2 | ROP1-FC 0603, 0.60 mm, only at x >= 38.0; otherwise bare GND pour | No part, no power copper, three 6 mm foot spots; 12 mm left of and 13 mm above the LM1084 courtyard, so away from its heat; the y 76.4 limit stays 0.55 mm short of L-FC (FC boost inductor, height unknown) and 5.2 mm short of the VSW-FC switch node; the x 17.5 limit clears J-FC (silk x 17.33, screws on top). 21.6 mm of board remains above it. |
| 1a | Extension of rank 1 to x 49.20 (rect A', y 67.64-76.40) | 31.7 x 8.8 = 278 mm2 | OP-FC 1.75 mm; MDAC-FC height unknown (from x 46.6) | Mechanically possible above a 2.54 mm standoff (0.79 mm air over OP-FC), but it covers the FC droop amplifier, the FC MDAC and their SPI/3V3 traces: a switching charger above the droop chain is a noise risk. Use only for passive, low-noise parts; prefer to stop at x 38.9. |
| 2 | Low-y, x 17.60-49.20, y 26.00-32.84 (rect B') | 31.6 x 6.8 = 215 mm2 | C4A-BT / C4B-BT 1.35 mm | Covers BAL (BQ29200) and the balance network: RB1A is the lift site and BAL OUT the probe point of the battery-isolation gates BG-17a/b and B-PKN, so an overhang would block bench access. VBT traces up to 2.54 mm, the VOUT-BT pour and 12 GND vias lie beneath; no foot spot exists. Below y 23.6 the band reaches the BT boost switch node (VSW-BT pour), REG-BT and, at y <= 20.84, L-BT; x must stay >= 17.6 because of J-BT. |
| Reject | Right (+x) | 0 mm | CO-5V 2.10 mm at 0 mm, LM1084 4.83 mm at 1.75 mm | CO-5V silk touches the footprint silk and its pad is 0.50 mm away; the 5V tab pour is 0.585 mm away; the hot LM1084 tab faces the pins 4-8 column. The free area beyond (x 63-79) is reachable only by bridging the LM1084, which traps its heat. The board edge must stay at x <= 49.2 (the CR uses 48.70). |
| Reject | Left (-x) | 0 mm | J-BL / J-NTC / J-FC 21.70 mm (J-NTC unknown) | J-BL silk already overlaps the footprint silk by 0.13 mm and its courtyard is 0.79 mm away; J-NTC courtyard 0.75 mm. Screws are driven from above and wires enter at x 3.5, so nothing may cover the blocks. The board edge must stay at x >= 17.2 (the CR uses 17.70). |

For a moving vehicle: rank 1 is an 8.8 mm cantilever beyond the 34.8 mm pin span; a bonded foot at (23.20, 70.64) and
(32.20, 70.64) carries it without an MB hole. Pin-header retention and the foot material are TODO(verify) at the
board design stage.

## 7. Consistency with the existing documents

| Item | Document value | Parse value | Verdict |
|---|---|---|---|
| CHG silk size | A.7: 32.0 x 34.8 mm | 32.001 x 34.801 | Agrees |
| CR outline | A.7: x 17.70-48.70, y 34.14-67.14 (0.5 mm in on left, right, high-y; 1.3 mm in on low-y) | silk line centre 17.198 / 49.199 / 67.644 / 32.843 gives exactly 17.698 / 48.699 / 67.144 / 34.143 | Agrees |
| Pin coordinates | A.8 table | identical to 0.001 mm | Agrees |
| LM1084 distance | A.7: 1.8 mm right | 1.748 to the courtyard (2.023 to the tab pad, 2.363 to the body) | Agrees if read as courtyard |
| CO-5V distance | A.7: 0.1 mm right | silk outer edges touch (-0.026 mm); pad 0.499 mm | Agrees within the silk resolution |
| OP-FC overlap | A.7: the CR "still overlaps the outline by 0.3 mm" on the OP-FC side | OP-FC silk y0 67.18 overlaps the CHG silk line by 0.46 mm and lies 0.04 mm outside the CR edge 67.14; OP-FC lead tips (D0008A 6.19 mm max span) reach y 68.53, 1.39 mm outside the CR edge | **Not reproduced**; the 0.3 mm figure needs its source stated |
| MB copper under the CR | A.7 list (VBT, VCHG-IN, VCHG pour, VBT pour, logic traces) | identical coordinates | Agrees |
| GND vias under the CR | A.7: 16 tented GND vias | 14 GND vias inside the CR outline, 18 inside the silk rectangle | **Disagrees** (count rule or outline not stated in A.7) |
| Overhang options | A.7: low-y over C4A/B-BT (1.35 mm) or high-y over OP-FC (~1.75 mm, UNVERIFIED); never left or right | C4A/B-BT 1.35 mm (IPC name); OP-FC 1.75 mm confirmed (OPA197 DS D0008A); the high-y band left of OP-FC (x 17.5-38.9) has no part at all | Agrees; the parse adds the part-free high-y rectangle and removes the UNVERIFIED tag |
| Ag105 standoff (gate D-2) | `battery_isolation_feasibility_2026-11-07.md` lines 116, 246, 785: standoff and cut gap unmeasured; `concept_IC1...md` line 890: pass = solderable stub >= 1 mm | DS Fig 11: 2.54 mm nominal standoff (+/-0.5 mm), 3.00 mm pins below it, module top 13.14 mm nominal | No conflict; the fitted standoff stays TODO(measure) (D-2). For the custom board D-2 matters only if the Ag105 pins are cut rather than the module removed; the custom board plugs into the empty holes |
| Ag105 keep-out | silk 34.8 mm long | DS Fig 11 keep-out 37 mm long | **Disagreement**, 2.2 mm; affects only how much of the silk the module itself claims |

## 8. Open items

- TODO(verify: Eaton HCM1A1305V3 datasheet) height of L-FC and L-BT.
- TODO(verify: Wurth 691411410002 datasheet) height and wire-entry side of J-NTC.
- TODO(verify: AD5443 RM-10 package outline) height of MDAC-FC (matters only for rect A').
- TODO(measure) the fitted Ag105 standoff (gate D-2) and the fab copper weight.
- TODO(measure) LM1084 case temperature and the air temperature at the high-y band, to confirm the thermal ranking.
