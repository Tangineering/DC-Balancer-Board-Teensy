# Extended CHG carrier: area booking, layer count and stack-up (round 4, r7 input)

This note decides the layer count and the placement sides of the CHG carrier (CR) when the CR extends sideways past the
31 x 33 mm Ag105 footprint. The CR stays plugged into the 22 Ag105 holes. The note is parametric in the added outline area
(+250, +400, +600 and +900 mm²) and gives the stack-up and the A.7/A.8 rules that change or stay.

- Subject: `docs/charger_bq25798_wiring_design_2026-11-05.md` r6 (sections A.6, A.7, A.8, A.9, B.6, B.8, E, H.18, H.21(k),
  H.22(c)(k)); the BQ25798EVM stays the power stage.
- Calculation: `round4/calc/stackup_area.py` (stdlib), output `round4/calc/stackup_area_out.txt`. Every number below comes
  from that output unless a design-document section is named.
- Neighbours: `round4/calc/mb_neighbours_out.txt`.
- Coordinates: Eagle `.brd` board coordinates, top view, origin at the MB origin, +x right, +y up, mm.

## 1. Result

The CR stays 4-layer at every extension in the ladder. A 2-layer CR fits by area only from about +1160 to +1310 mm² of
extension, which is outside the ladder. In addition, a 2-layer CR raises the eFuse commutation-loop inductance by 4 to 7
times per millimetre and the near-field coupling into the comparators by 46 to 53 times at equal distance.

Single-sided placement (all parts on the top, bottom layer a continuous GND plane) needs about +920 mm² on a 4-layer CR
with every footprint kept, or about +800 mm² with the 87 mm² of DNP option footprints removed. Of the ladder, only
+900 mm² reaches it, at 76 % utilisation (70 % without the DNP footprints) against a 75 % budget. Below that, the CR stays
double-sided with passives on the bottom, as in round 3.

The extension is needed even for the double-sided build. On a strict usable-area basis, the r6 footprint build carries
693 mm² of top courtyards on 732 mm² of usable top area (95 %; 103 % with the power pours booked). The H.18 figure of
881 mm² counts the 0.5 mm courtyard clearance around the 22 header pads and two outboard strips where no courtyard fits.
From +319 mm² the round-3 double-sided split meets the 75 % budget on the top side.

The EIB stays a separate board. A merged CR + EIB needs +1205 mm² for single-sided 4-layer placement, and it moves the
E1-E8 leads 0.30 m from the EVM, against A.5 build maxima of 20 mm (E8), 25 mm (E3) and 30 mm (E4).

## 2. Method and bases

### 2.1 Courtyard booking

Every CR part in B.8 and every EIB part in B.6/B.8 is booked once, with its E package. The courtyards are the A.8 values
(IPC-7351 nominal land pattern + 0.25 mm): 0402 1.9 x 1.0, 0603 3.0 x 1.45, 0805 3.4 x 1.8, 1206 4.75 x 2.3, 1210 4.75 x
3.2 and SMA 6.6 x 3.1 mm. Packages without an A.8 courtyard keep the `r3_calc.py` H.18 bookings: VQFN-24 36 mm² (the
H.21(k) 5.0 x 5.0 mm courtyard plus a via allowance), SOT-23-6 10, SSOP-8 (DCT) 15, SC70-5/6 7, SOT-23 10, J101 3.9 x
9.4 mm, tap field 21 x 8 mm, W6/W7 pads 20 mm². The W1-W4 holes are booked as (pad + 1.0 mm)². SOD-323 (D101, DNP) is
booked as an 0805 courtyard (ASSUMPTION). The package land patterns for DBV, DCT, DCK, RGE and SOD-323 are not in the
library: TODO(verify: TI package drawings / IPC-7351B calculator).

DNP footprints are booked because the design keeps them (U112, U117, D101, R_KA, R106, R134, R145, R146, R160-R163, C105,
C124, C127, C152). The power pours on L1 outside every courtyard are booked separately as 60 mm² (ASSUMPTION; lengths from
the A.3/A.6/A.8 coordinates at the A.8 widths).

### 2.2 Usable top area

The usable top area is the courtyard limit (outline - 0.5 mm, A.7) minus the header-column keep-outs (1.9 mm pads + 0.5 mm,
A.8), minus the strips outboard of the columns where no courtyard fits, minus the pin-11 chamfer clearance (A.7).

| Item | Area (mm²) |
|---|---|
| Courtyard limit x 18.2-48.2, y 34.64-66.64 | 960.0 |
| 1x12 column keep-out (x 19.55-22.45, pins 22-11) | -89.4 |
| 1x10 column keep-out (x 44.55-47.45, pins 1-10) | -74.7 |
| Outboard strip right of the 1x10 column (0.75 mm wide) | -19.4 |
| Outboard strip left of the 1x12 column (1.35 mm wide, 0402-vertical only) | -43.1 |
| Chamfer clearance | -1.1 |
| **Usable, strict** | **732** (775 with the left strip counted; H.18 basis 881) |

An extension of area A adds A minus 1.0 mm x (A / 32 mm) of end margins, minus one far-end support keep-out of 38.5 mm²
(a 7 mm copper-free circle for an M3 nylon standoff, the A.9 convention; TODO(verify: support design), since a bonded foot
without a hole would not cost this area).

### 2.3 Routing overhead and utilisation budgets

The routing overhead comes from a wiring-demand estimate, since no routed layout exists. The CR has 448 connected pins,
of which about 75 are GND and 12 unconnected, on about 110 signal nets (hand count from B.8, +-15 %). This gives about
251 signal connections. They are split into 150 local connections (1 mm of track outside the courtyards), 70 medium runs
(10 mm: logic mesh, comparator outputs, series resistors to taps) and 30 long runs (20 mm: tap field to consumers, J101
drivers, pins 7/8/13 to W6/W7, the 3V3 tree). At a 0.4 mm track pitch the total track area is 580 mm².

- **4-layer, single-sided:** L1 carries the local tracks and 275 vias (75 GND, two per medium or long run to L3) at
  0.64 mm² each: 236 mm² of L1 overhead. L3 carries the medium and long runs.
- **2-layer, single-sided:** L1 carries every track except a 10 % cross-under allowance on L2, plus 75 GND vias: 576 mm².

The utilisation budget is U = 0.90 / (1 + L1 overhead / courtyard sum), with 0.90 as the packing efficiency
(ASSUMPTION). The result is U4 = 0.75 for 4-layer single-sided (0.74-0.77 for track demand x1.5 to x0.5) and U2 = 0.61
for 2-layer single-sided (0.53-0.71). The 4-layer value sits between the r3 EIB budget of 0.70 (A.9) and 0.80. The
verdicts below quote the break-even extension at 0.70, 0.75 and 0.80 so that the decision does not rest on one value.
The T-A-06 placement DRC on the captured board remains the gate.

### 2.4 Electrical method

Loop inductance uses the H.21(k) parallel-plate method L = mu0 h l / w, cross-checked with the Hammerstad microstrip
closed form (L' = mu0 / [w/h + 1.393 + 0.667 ln(w/h + 1.444)]; recalled from Pozar, not in the library). The
parallel-plate method overestimates when w/h is near 1, so the 2-layer values are given as a range. Coupling into the
comparators uses the image-theory mutual inductance M' = (mu0 / 4 pi) ln(1 + (2h/d)²) (derived in the script). Copper
widths use the IPC-2221 external fit of H.22(c).

## 3. Area booking

Table 1 lists the CR booking by package.

| Package | Footprints (DNP) | Area (mm²) |
|---|---|---|
| 0603 | 89 (11) | 387.2 |
| 0805 | 7 | 42.8 |
| 0402 | 6 (1) | 11.4 |
| 1206 | 3 (1) | 32.8 |
| 1210 | 1 | 15.2 |
| SMA (D103, D107) | 2 | 40.9 |
| VQFN-24 (U101) | 1 | 36.0 |
| SOT-23-6 (U102-U104, U115, U119-U121; U117, U112 DNP) | 9 (2) | 90.0 |
| SSOP-8 DCT (U105, U106, U110, U111, U113, U114, U116, U118) | 8 | 120.0 |
| SC70-6 (U107-U109) / SC70-5 (U122, U123) | 3 / 2 | 35.0 |
| SOT-23 (D104-D106, D108) | 4 | 40.0 |
| SOD-323 (D101) | 1 (1) | 6.1 |
| J101, tap field, W1-W4, W6/W7 | - | 271.0 |
| **CR courtyard total** | 136 parts (16 DNP) | **1128** (r6 H.22(k): ~1082) |
| L1 power pours outside courtyards (ASSUMPTION) | - | 60 |
| **CR demand** | | **1188** (1101 without the DNP footprints) |

With this booking the round-3 side split is top 693 mm² and bottom 435 mm² (H.22(k): ~678 and ~404).

Table 2 lists the EIB and the merged board.

| Board | Content | Area (mm²) |
|---|---|---|
| EIB, separate | 24 R + 5 C 0603, U201 SSOP-8, U202 SC70-5, U203/U204 SOT-23-6, Q201-Q203 SOT-23 (198); J201 2x7 1.27 mm (36.7); 8 E-pads (48); 2 M3 keep-outs (77) | **360** = 42 % of 36 x 24 mm |
| CR + EIB merged | CR minus J101, plus the EIB parts and the E-pad row; no J201, no ribbon, no EIB M3 holes | **1338** (1398 with pours) |

The r3 H.18b figure of 559 mm² (65 %) used the 2.54 mm J201 (25.4 x 9.0 mm); with the r4 1.27 mm J201 the EIB is at 42 %
of its 36 x 24 mm outline. The 36 mm edge is still needed for the 30.48 mm E-pad envelope (A.9).

## 4. Fit versus extension area

Table 3 gives the utilisation for single-sided placement and, for the double-sided 4-layer build, the top-side
utilisation with the round-3 bottom set kept. "Bottom still needed" is the courtyard area that cannot go on the top at
U4 = 0.75. Demand includes the 60 mm² of pours.

| Extension (mm²) | Usable top (mm²) | CR single-sided U (no DNP) | Merged single-sided U | Double-sided: top U with the r3 bottom set (435 mm²) | Double-sided: bottom still needed at U4 (mm²) |
|---|---|---|---|---|---|
| 0 | 732 | 162 % (150 %) | 191 % | 103 % | 638 |
| +250 | 936 | 127 % (118 %) | 149 % | 80 % | 485 |
| +400 | 1081 | 110 % (102 %) | 129 % | 70 % | 376 |
| +600 | 1275 | 93 % (86 %) | 110 % | 59 % | 231 |
| +900 | 1566 | 76 % (70 %) | 89 % | 48 % | 13 |

The break-even extensions on the strict basis are:

- CR, single-sided 4-layer: **+917 mm²** at U4 0.75 (+817 at 0.80, +1036 at 0.70); without the DNP footprints **+798 mm²**
  (+705 to +908);
- CR, single-sided 2-layer: **+1307 mm²** at U2 0.61 (+1005 at 0.71, +1610 at 0.53); without the DNP footprints +1160 mm²;
- CR + EIB merged: +1205 mm² (4-layer), +1664 mm² (2-layer);
- double-sided 4-layer with the top side at U4 0.75: **+319 mm²**.

With the left outboard strip counted (775 mm² base), the single-sided break-evens fall by about 44 mm² (+873 and
+1263 mm²); no verdict changes.

A 2-layer double-sided CR is not evaluated further. Its bottom parts would cut the only reference plane under the
comparator block, which is the reason round 3 chose 4 layers (A.7, H.18).

The extension is necessary, not sufficient. Table 4 gives the strip width for one full side and the room to the MB
outline. MB part heights are not in the `.brd`; every overhang is subject to TODO(measure: MB part heights under the
chosen extension) and to gate D-2.

| Extension | Strip width, 33 mm side (+-x) | Strip width, 31 mm side (+-y) |
|---|---|---|
| +250 mm² | 7.6 mm | 8.1 mm |
| +400 mm² | 12.1 mm | 12.9 mm |
| +600 mm² | 18.2 mm | 19.4 mm |
| +900 mm² | 27.3 mm | 29.0 mm |

The room to the MB edge is 17.7 mm on -x (J-BL and J-NTC occupy x 3.28-17.23), 30.9 mm on +y (OP-FC at y 67.30, L-FC at
y 77.01), 34.1 mm on -y (C4A/B-BT, BAL, L-BT) and 82.4 mm on +x (CO-5V 0.60 mm and LM1084 2.27 mm from the CR edge). A
+900 mm² extension along one side therefore leaves the MB on -x and uses almost all of the room on +-y; a split over two
sides is likely. Placement of the 0.1 % dividers stays away from the LM1084 side to limit thermal gradients across the
divider pairs.

## 5. Electrical comparison: 2-layer versus 4-layer

### 5.1 eFuse commutation loop

At a fast-trip turn-off the current in the loop C102 -> U101 IN -> FET -> OUT -> D103 -> GND -> C102 collapses. The loop
inductance then appears across the FET as an IN spike and a negative OUT step (H.5). Table 5 gives the inductance per
millimetre of pour over its return plane.

| Stack-up, return-plane spacing h | 2.5 mm pour: parallel plate / microstrip (nH/mm) | 4.0 mm pour (nH/mm) |
|---|---|---|
| 4-layer L1/L2 or L3/L4, h 0.20 mm | 0.101 / 0.080 | 0.063 / 0.054 |
| 4-layer L3 to L2 across the core, h 1.10 mm | 0.553 / 0.277 | 0.346 / 0.206 |
| 2-layer 1 oz, h 1.53 mm | 0.769 / 0.333 | 0.481 / 0.254 |
| 2-layer 2 oz, h 1.46 mm | 0.734 / 0.325 | 0.459 / 0.247 |

At the r5 geometry, the C102b link (8 x 2.5 mm) is 0.64-0.80 nH on 4-layer and 2.6-6.2 nH on 2-layer. The D103 cathode
run (4 x 2.5 mm) is 0.32-0.40 nH on 4-layer and 1.3-3.1 nH on 2-layer. A 2-layer CR meets the 2 nH budget per loop only
with runs of at most 2.6-6.2 mm at 2.5 mm width, or 4.2-8.1 mm at 4.0 mm width. On 4-layer the same budget allows 20 mm.
A through via on 1.6 mm is 1.30 nH; an L1-L2 via is 0.079 nH.

The overshoot added across the FET is dV = L x I_off / t_off, with I_off 45-65 A (H.5) and t_off swept over 50-200 ns
(TODO(verify: SLVSE94G fast-trip turn-off time); T-C-04 measures).

| Loop | L (nH) | dV at 45 A | dV at 65 A | OUT-side share at 45 A |
|---|---|---|---|---|
| 4-layer, r5 placement (0.8 + 0.4 + vias 0.2) | 1.4 | 0.3-1.3 V | 0.5-1.8 V | 0.11-0.43 V (0.48 nH) |
| 2-layer, r5 lengths (parallel plate) | 9.2 | 2.1-8.3 V | 3.0-12.0 V | 0.75-3.0 V (3.34 nH) |
| 2-layer, pin-adjacent, each loop at 2 nH | 4.0 | 0.9-3.6 V | 1.3-5.2 V | 0.45-1.8 V (2.0 nH) |

The IN side has 34 V of margin (33 V worst peak against the 67 V absolute maximum, H.5), so the IN spike is not the
limit on either stack-up. The OUT side is: H.5 already accepts -0.5 to -1 V against the -0.3 V absolute minimum, pending
TI E2E. A 2-layer CR adds 0.45-3.0 V to that excursion at 45 A, against 0.11-0.43 V on 4-layer.

### 5.2 Coupling into the comparator block

Table 6 gives the EMF induced in a 10 mm comparator-input run parallel to a commutation-loop conductor, at
di/dt = 65 A / 100 ns (scales linearly with di/dt).

| Distance d | 4-layer, h 0.20 mm | 2-layer, h 1.46 mm | Ratio |
|---|---|---|---|
| 2 mm | 25.5 mV | 742 mV | 29 |
| 5 mm | 4.1 mV | 191 mV | 46 |
| 10 mm | 1.0 mV | 53 mV | 51 |
| 20 mm | 0.3 mV | 13.7 mV | 53 |
| 30 mm | 0.1 mV | 6.1 mV | 53 |
| 40 mm | 0.1 mV | 3.5 mV | 53 |

In the far field M' scales as h²/d², so a 2-layer CR needs 36.5 mm of separation to match the 4-layer coupling at 5 mm.
The filtered comparator inputs tolerate the 2-layer case. At 5 mm the residual at the pin is 0.81 mV (H1, 470 pF at
~50 kOhm), 0.20 mV (UVB IN+, 1 nF at ~94 kOhm) and 0.19 mV (BT_OK IN-, 10 nF with R140 10 kOhm).

Four comparator inputs have no filter capacitor in B.8: U115 IN- (N_BBM), U119 IN- (N_FOM), U120 IN+ (N_FNP) and U121
IN+ (N_RNP). Their static margins are 0.16 V (BTB_OFF, H.3) and about 0.24 V at the U120/U121 node. On 4-layer the EMF at
5 mm is 4.1 mV; on 2-layer it is 191 mV for the duration of t_off. A 2-layer CR would rely on the TLV3012B propagation
delay to ignore that pulse (TODO(verify: SBOS300C tPD)), on 36 mm of separation, or on added filter capacitors. Added
capacitors would then need a check against the H.13 inhibit-latency allowance.

The capacitive coupling of VCHGIN/VCHGOUT dv/dt into the 1-10 MOhm nodes (R119, R116, R187, R179) follows the same field
confinement and is not quantified here. Only its scaling, 1 / (1 + (d/h)²), is used.

### 5.3 Ground scheme and plane integrity

The A.6 topology (CR plane bonded to MB GND at CHG pads 4/14/15, Kelvin T9, shields bonded at the CR end) is identical on
both stack-ups at DC. The plane sheet resistance is 0.49 mOhm/sq at 1 oz and 0.25 mOhm/sq at 2 oz. On 4-layer, L2 is the
analog reference and L4 shares the power-return current; on 2-layer, one plane carries both. The 2-layer CR keeps the
A.6 offsets only if the power-return corridor (W2/W4 to pads 4/14/15) and the commutation-loop vias stay outside the
comparator and divider ground vias, which the extension makes possible but does not enforce.

### 5.4 Copper widths

Table 7 gives the IPC-2221 external widths (both layers of a 2-layer CR, L1/L4 of a 4-layer CR).

| Current | 1 oz, 10 C / 20 C rise | 2 oz, 10 C / 20 C rise | Internal 1 oz, 10 C |
|---|---|---|---|
| 2.41 A, input side (eFuse I_OL, A.8) | 1.01 / 0.66 mm | 0.51 / 0.33 mm | 2.63 mm |
| 3.21 A, battery side (ICHG max, A.3) | 1.50 / 0.99 mm | 0.75 / 0.49 mm | 3.90 mm |
| 3.50 A, battery-side design target (A.8) | 1.69 / 1.11 mm | 0.85 / 0.56 mm | 4.40 mm |

The A.8 minimum pour of 2.5 mm carries 4.6 A on 1 oz and 7.7 A on 2 oz at 10 C rise; 2.0 mm carries 4.0 A and 6.5 A.
Both stack-ups therefore meet the 3.5 A design target with the existing widths. No DC power path goes on an inner layer.

The extension does not change the battery-side geometry. W3 at (24.3, 45.4) and W4 at (24.3, 55.6) tie to pins 18/19
and 14/15 through about 2.4 mm of pour outside the pads, wherever the extension goes. Relocating W3/W4 20 mm into an
extension would add 2.0 mOhm (2.5 mm, 2 oz) to 3.9 mOhm (2.5 mm, 1 oz) per conductor: 6-13 mV and 20-41 mW at 3.21 A,
against the 12.6 mOhm battery pair of H.11. The relocation is acceptable electrically. However, it would route 3.21 A
through the area that the comparator block should occupy, so W3/W4 stay at the pin columns.

### 5.5 U101 thermal pad

Nine 0.3 mm vias with 25 um plating (TODO(verify: fab plating)) through 1.6 mm give 163 K/W each, 18.1 K/W in
parallel. At the H.14 eFuse dissipation of 0.17 W the drop across the via field is 3.1 K. The thermal pad does not decide
the layer count. On 2-layer the vias land on the only plane, so the commutation-loop return enters that plane at U101.

### 5.6 Routing that has no 2-layer equivalent

The A.8 routing note runs SCL/SDA (pins 7/8 to W7) and TS_EXT (pin 13 to W6) on L3 under the IN strip, and joins the
C102b VCHGIN pad on L3 over L4. A 2-layer CR has neither layer. The I2C pair would need an L1 detour around the IN strip
or a cross-under that cuts the plane under the commutation loop, and C102b would have to sit pin-adjacent on L1. The
H.21(k) high-y band would be re-planned and re-checked in both cases.

## 6. Single-sided build

A single-sided build is possible on 4-layer from about +920 mm² (all footprints) or +800 mm² (DNP option footprints
removed), and on 2-layer from about +1160 to +1310 mm². The following items change when all parts go to the top:

- the bottom carries no parts; L4 (4-layer) or L2 (2-layer) is a continuous GND pour with antipads only at the 22 header
  pins and W1-W4, stitched to L2 at <= 5 mm on 4-layer;
- the bottom keep-out (x 24.5-36.0, y 48.5-53.5), the MB power-copper shadow (+1 mm) and the <= 1.0 mm bottom height cap
  stop being placement rules, because they constrain only bottom parts;
- the 16 r6 passives and every round-3 bottom passive move to the top, so the r6 interior block (x 24-36, y 42-56) and
  the H.21(k) high-y band are re-planned and re-checked;
- the +x pocket fallback (0603 R103/R104 on the bottom) is retired;
- the CR bottom faces the MB only as a GND pour under solder mask, so an overhang needs part-height clearance only, not
  part height plus bottom-part height (gate D-2);
- the flush-cut rule for W1-W4 and header tails (<= 0.5 mm) stays, and the polyimide sheet stays as a secondary barrier,
  extended to the new outline + 1 mm with cut-outs over the MB parts under the extension;
- hand assembly needs one hot-air or reflow side instead of two.

## 7. Recommendation

### 7.1 Layer count and placement sides

The CR stays 4-layer. The placement sides follow the extension that the geometry study adopts:

| Extension | Build | Note |
|---|---|---|
| 0 (footprint) | double-sided 4-layer (round 3) | top side 95-103 % of the strict usable area; T-A-06 DRC at risk |
| +250 mm² | double-sided 4-layer | top 80 % with the round-3 bottom set; acceptable only near the 0.80 end of the budget |
| +320 to +800 mm² (+400, +600) | double-sided 4-layer | top <= 75 %; the bottom set can shrink to 376 mm² (+400) or 231 mm² (+600) |
| >= +800 mm² (no DNP footprints) or >= +920 mm² (all footprints) | single-sided 4-layer | +900 mm² qualifies at 76 % (70 % without the DNP footprints) |
| >= +1160 to +1310 mm² | single-sided 2-layer possible by area | not recommended: sections 5.1, 5.2 and 5.6 |

Where the bottom set shrinks, the precision analog parts (0.1 % dividers, C106-C108, C140) move to the top beside their
comparators first, and logic pull-downs, series resistors and decouplers stay on the bottom.

### 7.2 Stack-up

The stack-up is a standard 1.6 mm 4-layer board with symmetric 0.2 mm prepregs, which is the H.21(k) basis of the 2 nH
loop rule:

| Layer | Copper | Dielectric below | Content |
|---|---|---|---|
| L1 top | 2 oz (1 oz alternative, 7.3) | prepreg 0.2 mm | every IC, the power pours (VCHGIN, VCHGOUT, VCHG, GND star), signals; all parts when single-sided |
| L2 | 1 oz | core ~1.0-1.1 mm | solid GND reference plane, no splits, antipads only |
| L3 | 1 oz | prepreg 0.2 mm | signals (I2C, TS, tap-to-logic, readbacks, logic mesh); the C102b link if it stays off L1 |
| L4 bottom | 2 oz (1 oz alternative) | - | GND pour stitched to L2 at <= 5 mm; continuous when single-sided, around the bottom passives otherwise |

The nominal thickness is 1.64 mm with 1 oz throughout and 1.71 mm with 2 oz outer layers at a 1.1 mm core; the fab trims
the core to about 1.0-1.06 mm for a 1.6 mm board. Only the 0.2 mm prepregs enter the loop budget.
TODO(verify: the chosen fab's 1.6 mm 4-layer stack-up table).

### 7.3 Copper weights

The r6 copper (2 oz outer, 1 oz inner) stays the baseline. The extension removes the width limit that made 2 oz
necessary, so 1 oz outer becomes an acceptable alternative. With 1 oz outer, the battery-side pours stay >= 2.5 mm
(4.6 A at 10 C rise) and the input side >= 2.0 mm (4.0 A). The choice depends on the PM0 fab DFM check of 2 oz spacing
at the U101 RGE 0.5 mm-pitch land pattern and the 0.65 mm SC70/SSOP pitch: TODO(verify: fab 2 oz outer minimum space).
1 oz outer doubles the CR copper resistance, which is mOhm-level on runs of a few millimetres.

## 8. Rules that change and rules that stay

### 8.1 Changed (A.1, A.7, A.8, A.9, E, H.18)

1. Placement sides become parametric in the extension (section 7.1): double-sided below about +800/+920 mm², single-sided
   above.
2. In the single-sided build, the bottom keep-out, the MB power-copper shadow (+1 mm) and the <= 1.0 mm bottom height cap
   are retired; L4 is a continuous GND pour. In a double-sided build that puts bottom passives into the extension, the
   shadow rule extends to the MB power copper under the extension and the height cap to the measured MB part heights.
3. The H.18/H.22(k) usable top area is restated on the strict basis (732-775 mm² for the footprint, not 881 mm²). The r6
   footprint build is at 95 % (103 % with pours) and passes the 75 % budget only from +319 mm².
4. C102b goes on L1 pin-adjacent to U101 when the extension frees room. The L3-over-L4 link stays as the fallback.
5. The +x pocket bottom fallback (0603 R103/R104) is retired in the single-sided build.
6. 1 oz outer copper becomes an allowed alternative (>= 2.5 mm battery side, >= 2.0 mm input side), selected by the PM0 DFM
   check.
7. The polyimide sheet is cut to the extended outline + 1 mm, with cut-outs over the MB parts under the extension.
8. The far-end support keep-out (7 mm, A.9 convention) is added to the CR outline; TODO(verify: support design).
9. The EIB re-booking becomes 42 % of 36 x 24 mm (H.18b quoted 65 % with the 2.54 mm J201). The EIB stays separate.
10. The E line "CR PCB 31.0 x 33.0 mm" takes the extended outline.

### 8.2 Kept

1. 4 layers, 1.6 mm, L2 a solid GND plane, 0.2 mm L1-L2 and L3-L4 spacing; no power-loop return across the core.
2. Added inductance <= 2 nH for the C102b loop and for the OUT 17/18 -> C103/D103 -> GND loop; C102a, C102c and the D107
   cathode within 3 mm of pins 1/2/5; C103 within 3 mm of OUT 17/18.
3. U101 at pad 10, VCHG-IN copper <= 5 mm, solder-masked both sides, no exposed test pad; R102 tapped at IN_SYS.
4. U101 thermal pad with >= 9 vias of 0.3 mm to GND.
5. Current bases 2.41 A (input) and 3.21 A (battery), designed to >= 3.5 A; pours >= 2.5 mm; IPC-2152 check
   TODO(verify: IPC-2152 chart) in T-A-06.
6. W1-W4 hole sizes and positions; W3/W4 at the pin columns, so the battery current stays out of the extension.
7. The A.6 ground scheme: star at pads 4/14/15, the W2 -> pads 14/15 pour outside the analog divider bottoms, the Kelvin
   T9 for BT_OK, shields bonded at the CR end.
8. Analog parts away from the U101 OUT/D103 loop; divider tops >= 2 mm from logic traces; the U104 divider bottom to F10.
9. Courtyards >= 0.5 mm from the outline and from the header, W1, W2, W6 and W7 pads; the pin-11 chamfer; the coordinate
   convention; the header strips and their pin ratings; the top-side SMT tap field; flush-cut tails <= 0.5 mm; J101 at
   1.27 mm.
10. The EIB as a separate 2-layer, 1 oz, single-sided board of 36 x 24 mm on the chassis beside the EVM.

## 9. Open items

1. TODO(measure: MB part heights under the chosen extension); the `.brd` holds no heights. This decides whether bottom
   passives may use the extension's bottom side and sets the stack-up height (gate D-2).
2. TODO(verify: fab 1.6 mm 4-layer stack-up table); the 0.2 mm prepregs are the basis of the 2 nH rule.
3. TODO(verify: fab 2 oz outer minimum space against the RGE 0.5 mm-pitch land pattern); this decides 2 oz or 1 oz outer.
4. TODO(verify: SLVSE94G fast-trip turn-off time); it scales every overshoot in section 5.1. T-C-04 measures it.
5. TODO(verify: TI package drawings / IPC-7351B for DBV, DCT, DCK, RGE, SOD-323); the bookings in 2.1 use the r3 values.
6. The routing-overhead model (section 2.3) is an estimate with confidence of about +-50 % on the track demand; the U4
   range it gives (0.74-0.77) is narrow because the via count dominates. The T-A-06 DRC on the captured board decides.
7. TODO(verify: SBOS300C tPD) is needed only if a 2-layer variant is reopened.
8. The support design (hole, standoff or bonded foot) belongs to the mechanical study; its keep-out changes the
   break-even by up to 38.5 mm².
