# BQ25798EVM (BMS034A/B-003) physical geometry from SLUUCB5E

Round 4 work file. Subject: the TI BQ25798EVM that replaces the Silvertel Ag105 (MB designator CHG) on motherboard rev
20260622. This note establishes the EVM outline, mounting provisions, connector and test-point positions, part heights and
underside population, and checks the round-3 placement numbers (design doc A.5, H.22(i), `round3/calc/r3_calc.py` lines
1185-1204).

## 1 Sources

1. **[UG]** TI SLUUCB5E, *BQ25792EVM, BQ25798EVM and BQ25798BKUPEVM (BMS034) Evaluation Module*, June 2020, revised
   July 2022, 31 pages as served (25 content pages plus TI notices). Fetched from `https://www.ti.com/lit/ug/sluucb5e/sluucb5e.pdf`
   on 2026-11-10; SHA-256 `a653d3ba...bfbd`, 3 996 565 bytes, identical to the copy in
   `DC-Balancer-charger-custom/references/TI_BQ25798_design_files/`. Saved as `work/evm/sluucb5e.pdf`.
   Used: Table 1-2 (connections), Table 1-3 (shunts), Figures 4-1 to 4-4 (layer figures, pp. 15-18), Figures 4-5 and 4-6
   (schematic, pp. 19-20), Table 4-1 (BOM, pp. 22-24).
2. **[OST]** On-Shore Technology drawing ED120/XDS rev A (2017-09-11), "ED120DS series 5.08 mm, one piece wire protector",
   fetched from `https://www.on-shore.com/wp-content/uploads/ED120XDS.pdf` on 2026-11-10; saved as
   `work/evm/parts/onshore_ED120XDS.pdf` and rendered as `onshore_ED120XDS-1.png`.

## 2 Method

### 2.1 Vector extraction

The four layer figures of [UG] are vector Form XObjects; `pdfimages -list` reports no raster image on pp. 15-20. Every pad,
drill, silkscreen stroke and mechanical-layer stroke is therefore a PDF path with exact coordinates. The script
`work/evm_calc/evm_geom.py` interprets the figure content streams, converts the paths to millimetres and prints every value
in this note (`work/evm_calc/evm_geom_out.txt`). The values are not read from a raster render.

### 2.2 Scale calibration

The figure-to-board scale is set by part pitches that the parts themselves fix at 2.54 mm. The PDF export is slightly
anisotropic, so each axis has its own scale:

- x: J9 (3M N2510, 5 x 2) hole pitch over 4 pitches gives 4.054921 pt/mm; J8 (Molex 4 x 1) gives 4.054856 pt/mm
  (agreement 1.6e-5).
- y: J9 row pitch gives 4.067717 pt/mm; the JP22-JP29 two-pin pitch gives 4.067717 pt/mm (identical).
- The x/y ratio is 0.99685 (0.31 % anisotropy).

Two independent checks confirm the scale and the frame. First, the board outline scales to 3500.0 x 3500.0 mil on both
axes. Second, most feature centres land on a 0.0635 mm (2.5 mil) CAD grid within 0.002 mm (TP36 is the exception found,
0.006 mm off), for example TP33 at
(80.011, 63.499) mm = (3150.0, 2500.0) mil and J5 pin 1 at (82.487, 24.193) mm = (3247.5, 952.5) mil. The 5.08 mm terminal-block pitch
(J1, J5) and the 3.50 mm J7 pitch also come out at 5.080 mm and 3.500 mm.

### 2.3 Frame and error

**EVM frame:** origin at the lower-left corner of the board outline in top view, +x right, +y up, millimetres. The
bottom-layer figure (p. 18) is drawn mirrored (viewed from below); the script un-mirrors it, so every coordinate in this
note is in the top-view frame. A bottom view uses x' = 88.90 - x.

The coordinate quantization of the PDF is 0.001 pt (0.00025 mm), and the residual scale uncertainty is below 2e-5, so the
extraction error on a pad centre is below 0.01 mm relative to the CAD data. The limits on the physical board are elsewhere:
the fabricated outline and drill positions carry fabrication tolerance that [UG] does not state (TODO(measure: caliper on
the received EVM)), and part bodies are given as footprint or mechanical-layer outlines, not as measured bodies. Pin
identity was taken from the silkscreen, confirmed against the schematic (Figures 4-5, 4-6) and, for JP12, JP13, JP14 and
JP21, by following the copper on the four layer figures (`trace_all.py` method, Section 7.2).

## 3 Outline, layers and mounting provisions

The board outline is **88.90 x 88.90 mm** (3.500 x 3.500 in), identical on the top and bottom figures. The board has four
copper layers (Top, Signal Layer 1, Signal Layer 2, Bottom; [UG] Figures 4-1 to 4-4). The board thickness, the copper
weight and the stack-up are not given in [UG]: TODO(measure: caliper; verify against a TI fab drawing if one is obtained).

**The EVM has no mounting holes.** The drill census of the figures (unique centres) is 0.20 mm x 35, 0.254 mm x 729,
0.38 mm x 36, 1.02 mm x 128, 1.10 mm x 2 and 1.25 mm x 11; the largest drill is 1.25 mm (the J1-J5 terminal-block pins).
The 128 holes of 1.02 mm are exactly the 43 TH test points, 71 jumper-header pins, J8 (4) and J9 (10). The inner-layer
figures (pp. 16, 17) show no hole at any corner. The circles at three corners of Figure 4-1 are **fiducials**: a 1.000 mm
copper dot in a 2.000 mm opening, at (2.286, 86.613), (86.615, 86.613) and (2.286, 2.286) on both outer layers, and the BOM
lists FID1-FID6 as "Fiducial mark. There is nothing to buy or mount" ([UG] Table 4-1, p. 24). The fourth corner
(lower-right) carries the CE and WEEE marks.

The stock support is four adhesive feet on the underside, H1-H4, "Bumpon, Hemisphere, 0.44 X 0.20, Clear", 3M SJ-5303
([UG] Table 4-1, p. 22): 0.44 in (11.18 mm) diameter, 0.20 in (5.08 mm) tall. Their drawn outlines (bottom figure,
11.585 mm circles) are centred 7.620 mm (300 mil) in from both edges at each corner: (7.620, 7.620), (7.620, 81.279),
(81.281, 7.620) and (81.281, 81.279). Each bumpon zone (r = 5.79 mm) contains 7 to 17 stitching vias (0.254 mm drill) in
the board-wide ground pour of both outer layers, and the zones at (7.62, 7.62) and (81.28, 81.28) also overlap the SMT
pads of TP48 and TP49 (AGND). A hole drilled at a bumpon centre therefore cuts copper and vias; the corners are not a
keep-out.

## 4 Positions of the named points

Table 1 lists the requested points in the EVM frame. Pin numbers follow the schematic ([UG] Figures 4-5, 4-6); on this
board the square pad is pin 1 on every part checked (Section 7.2). Test-point and jumper drills are 1.016 mm; TH test-point
pads are 2.03 mm; jumper pads are 1.50 mm (pin 1 square).

**Table 1. EVM points (top view, origin lower-left board corner, mm)**

| Point | Net / function | x | y | Notes |
|---|---|---|---|---|
| J1 pin 1 (square) | PGND | 6.604 | 55.879 | ED120/2DS, 5.08 mm; silkscreen "PGND"; schematic J1 pin 1 GND |
| J1 pin 2 | VIN1 | 6.604 | 50.799 | silkscreen "VIN1"; [UG] Fig 4-5 "3.9V - 24V 5A" |
| J5 pin 1 (square) | BATTERY | 82.487 | 24.193 | ED120/3DS |
| J5 pin 2 | EXT_BATP (silkscreen "BATP") | 82.487 | 29.273 | Table 1-2 "SNS_BATP" |
| J5 pin 3 | PGND | 82.487 | 34.353 | |
| J7 pin 1 (square) | EXT_TS | 62.894 | 6.223 | Molex 0393570002, 3.5 mm pitch, 1.10 mm drill |
| J7 pin 2 | AGND | 66.394 | 6.223 | |
| J8 pin 1 (square) | AGND | 15.494 | 5.954 | Molex 0022053041, 4 x 1 R/A, 1.02 mm drill |
| J8 pin 2 | SCL | 18.034 | 5.954 | |
| J8 pin 3 | SDA | 20.574 | 5.954 | |
| J8 pin 4 | R37 10 ohm to JP31 pin 1 (EV2400 PULLUP) | 23.114 | 5.954 | |
| TP27 | REGN | 26.670 | 80.009 | orange, Keystone 5003 |
| TP33 | ILIM_HIZ | 80.011 | 63.499 | white, Keystone 5002 |
| TP35 | TS | 59.691 | 19.684 | |
| TP36 | /CE | 55.874 | 19.710 | |
| TP38 | STAT | 66.041 | 59.689 | |
| TP41 | PULLUP | 30.480 | 21.589 | silkscreen "PULLUP"; Fig 4-5 test-point row |
| TP49 | AGND | 83.440 | 79.120 | SMT Keystone 5016; pad 4.70 x 3.43 mm (copper bbox) |
| JP12 pin 1 (square) | REGN | 39.370 | 13.741 | "TS CONNECT"; copper reaches the TP27 net (Section 7.2) |
| JP12 pin 2 | TS divider top (R18, JP15/JP16) | 39.370 | 11.201 | |
| JP13 pin 1 (square) | REGN | 67.438 | 67.309 | "500mA" |
| JP13 pin 2 | R20 255 k to ILIM_HIZ | 67.438 | 64.769 | |
| JP14 pin 1 (square) | REGN | 71.375 | 67.309 | "1.5A" |
| JP14 pin 2 | R21 127 k to ILIM_HIZ | 71.375 | 64.769 | |
| JP17 pin 1 (square) | /CE | 54.611 | 26.796 | "CHARGE ENABLE" |
| JP17 pin 2 | AGND | 54.611 | 24.257 | |
| JP21 pin 1 (square, lower pad) | ILIM_HIZ | 75.312 | 64.769 | "EN HIZ"; bottom-layer trace to TP33 |
| JP21 pin 2 (round, upper pad) | AGND | 75.312 | 67.309 | no trace; pour-connected |
| L2 (centre) | 1 uH, SPM6530T-1R0M120 | 47.372 | 53.212 | outline x 43.672-51.072, y 49.812-56.612 (7.40 x 6.80); pads 1.85 x 3.40 at x 44.597 / 50.146 |
| U1 (centre) | BQ25798 RQM (VQFN-HR29) | 47.499 | 42.036 | mechanical outline x 45.448-49.549, y 39.986-44.086 (4.10 x 4.10) |
| Fiducials | - | 2.286 / 86.615 | 86.613 / 2.286 | three corners, both outer layers (Section 3) |
| H1-H4 bumpon centres | - | 7.620 / 81.281 | 7.620 / 81.279 | underside, 11.18 mm dia, 5.08 mm tall |

Figure `work/evm/fig4-1_annotated_300dpi.png` overlays these points (red) and the round-3 reads (blue crosses) on the
300 dpi render of Figure 4-1; every red marker lands on its pad.

## 5 Part bodies, heights and overhangs

### 5.1 Body outlines of the tall and edge parts

Table 2 gives the footprint body outlines from the mechanical layer (0.41 pt strokes) of Figure 4-1. The terminal-block
outlines are drawn 9.0 mm deep, which matches the 9 mm body depth of [OST].

**Table 2. Body outlines (top view, mm)**

| Part | x range | y range | Wire / mating face (inferred) |
|---|---|---|---|
| J1 (VIN1) | 2.604-11.604 | 48.224-58.299 | x = 2.60 (left edge side) |
| J2 (VIN2; EM7 removes) | 2.604-11.604 | 22.952-33.027 | x = 2.60 |
| J3 (SYSTEM; EM7 removes or caps) | 77.487-86.488 | 41.648-51.723 | x = 86.49 (right edge side) |
| J4 (VPMID; EM7 removes or caps) | 30.572-40.648 | 77.168-86.168 | y = 86.17 (top edge side) |
| J5 (BATTERY) | 77.487-86.488 | 21.773-36.773 | x = 86.49 (right edge side) |
| J7 (EXT THERMISTOR) | 61.144-68.144 | 2.773-10.063 | y = 2.77 (bottom edge side) |
| J8 (I2C, R/A) | 14.304-24.304 body; pins to y = -6.24 | 0.254-3.254 body | mates from -y, past the bottom edge |
| J9 (USB2ANY, shrouded 5 x 2) | 15.519-35.535 | 9.575-17.703 | vertical |
| J6 (micro-USB, R/A) | -1.003-4.428 | 36.740-44.539 | x = -1.00 (overhangs the left edge by 1.0 mm) |

The wire-entry face of each terminal block is inferred from the second mechanical line drawn 1.5 mm inside the face on the
edge side; every terminal block faces the nearest board edge. TODO(verify: on the received EVM).

### 5.2 Heights

Table 3 lists the heights that a source gives. A height that [UG] or [OST] does not give is a TODO.

**Table 3. Part heights above the board surface**

| Side | Part | Height | Source |
|---|---|---|---|
| Top | J1-J5 terminal blocks, ED120/2DS and ED120/3DS | **13.0 mm** (12.5 mm at the opposite face); pins 4.0 mm below the seating plane, 1.0 mm dia | [OST] |
| Top | L2 SPM6530T-1R0M120 | **3.0 mm** | [UG] BOM package "7.1x3.0x6.5mm"; the footprint plan (7.40 x 6.80) matches 7.1 x 6.5, so 3.0 mm is the height. TODO(verify: TDK SPM6530 datasheet) |
| Top | J6 Molex 47346-0001 | 2.45 mm | [UG] BOM "7.5x2.45x5mm"; plan 7.8 x 5.4 footprint matches 7.5 x 5 |
| Top | D13 LED | 0.8 mm | [UG] BOM "1.6x0.8x0.8mm" |
| Top | J7 (Molex 0393570002), J8 (Molex 0022053041 R/A), J9 (3M N2510-6002-RB), JP headers (Sullins PEC02SAAN / PEC03SAAN, Samtec HTSW-102-07-G-S) with SNT-100-BK-G shunts, TPs (Keystone 5000-5004, 5016), S1 (C&K KSR221GLFS) | not given | TODO(verify: manufacturer drawings) or TODO(measure: caliper) |
| Bottom | H1-H4 bumpons, 3M SJ-5303 | **5.08 mm** (0.20 in) | [UG] BOM |
| Bottom | Populated SMT: U2 TLV76033DBZR (SOT-23-3), D11/D12 BAT54HT1G (SOD-323), R35/R37/R43 (1206), R22 (Keystone 5106, 0805 jumper), 0402-0805 passives | not given | TODO(verify: TI DBZ0003A and part drawings) |
| Bottom | Through-hole tails (terminal blocks 4.0 mm lead; headers, TPs) | lead length minus board thickness | [OST] lead; board thickness TODO(measure) |

The tallest top-side parts are therefore the five terminal blocks at 13.0 mm. The tallest underside items are the bumpons
at 5.08 mm; on a 1.6 mm board the 4.0 mm terminal-block leads would protrude 2.4 mm below the underside if not trimmed, which
the bumpons clear (the 1.6 mm thickness is an assumption, not a measured value).

## 6 Underside population

The underside carries parts. Figure 4-4 shows SMT passives, D11/D12, U2 and the four bumpon outlines, plus the through-hole
tails and three fiducials. Table 4 lists the populated parts of the -003 variant whose bodies are the largest on the
underside; positions are footprint centres in the top-view frame.

**Table 4. Largest populated underside parts (BQ25798EVM -003)**

| Part | Package | Centre (x, y) mm |
|---|---|---|
| U2 TLV76033 LDO | SOT-23-3 (DBZ) | (13.66, 14.33) |
| R35 10.0 ohm | 1206 | (8.00, 14.61) |
| R37 10.0 ohm | 1206 | (25.40, 9.27) |
| R43 10.0 ohm | 1206 | (34.29, 10.67) |
| D11, D12 BAT54H | SOD-323 | (~8.5, 18.5) and (~8.5, 20.4) |

C33 and C34 (33 uF polymer, 7343-31) are "BQ25798BKUPEVM only" and C25 (7343-31 tantalum) has quantity 0 ([UG]
Table 4-1), so the 7343 footprints on the underside (C34 at (35.88, 50.99)) are empty on the -003 board. The PROG
resistors R27-R34, the TS divider R18-R26 and the bulk of the 0402/0603/0805 parts are also on the underside (Figure 4-4).
The bottom copper is a board-wide ground pour (88.12 x 88.12 mm polygon).

## 7 Cross-check against round 3

### 7.1 Scale and positions

Round 3 rendered Figure 4-1 at 150 dpi and used 8.66 px/mm (22 px per 2.54 mm read from the J8 pitch). The true scale of
that render is 8.448 px/mm in x and 8.474 px/mm in y (J8 pitch = 21.46 px), so the round-3 scale is 2.5 % (x) and 2.2 %
(y) high, and every round-3 millimetre distance is short by that amount. The round-3 right edge, x = 1017 px, is correct
(vector 1017.1 px). Table 5 compares the round-3 points with the vector positions mapped into the same render.

**Table 5. Round-3 reads (A.5, `r3_calc.py` line 1188) against the vector positions (150 dpi px, y down)**

| Round-3 point | r3 px | vector px | Delta (mm, x / y up) | Agreement |
|---|---|---|---|---|
| TP49 | (970, 308) | (971.0, 310.6) | -0.12 / +0.31 | yes |
| TP33 | (941, 441) | (942.0, 443.0) | -0.12 / +0.24 | yes |
| **JP21 pin 1** | (902, 408) | (902.3, 432.2) | -0.04 / **+2.86** | **no: r3 read the upper pad, which is pin 2 (AGND)** |
| JP14 pin 2 | (869, 432) | (869.1, 432.2) | -0.01 / +0.03 | yes |
| TP38 | (822, 474) | (824.0, 475.3) | -0.24 / +0.15 | yes |
| TP27 | (490, 300) | (491.4, 303.1) | -0.17 / +0.37 | yes |
| JP12 REGN pin | (598, 862) | (598.7, 864.7) | -0.08 / +0.32 | yes (pin 1, square, upper) |
| TP36 | (740, 812) | (738.1, 814.1) | +0.22 / +0.25 | yes |
| JP17 /CE pin | (727, 752) | (727.4, 754.0) | -0.05 / +0.24 | yes (pin 1, square, upper) |

Eight of the nine round-3 points agree within 0.37 mm, well inside the stated +-2 mm. The round-3 reads sit a consistent
~2 px high in y, which is a read bias, not a scale effect.

### 7.2 JP21 pin identity

JP21 pin 1 is the **lower** pad at (75.312, 64.769). Three independent observations support this:

1. The schematic connects JP21 pin 1 to ILIM_HIZ and pin 2 to AGND ([UG] Fig 4-6), and pin 1 is drawn with the square pad.
2. On the PCB the square pad of JP21 is the lower one, and the square pad is pin 1 on every part where the silkscreen or
   the copper confirms it: J1 (square = PGND = pin 1), J5 (square = BATTERY = pin 1), J7 (square = EXT_TS = pin 1),
   JP13 and JP14 (the two square pads are joined on the bottom layer and run to the REGN bus = pin 1).
3. The bottom-layer copper runs from the lower JP21 pad to TP33 (ILIM_HIZ) at (80.01, 63.50) and toward R20/R21; the upper
   pad has no trace on any layer, which is consistent with a pour-connected AGND pin.

Consequence: the A.5 placement and the H.22(i) table name "JP21 pin 1 (902, 408)", which is the AGND post. The pin naming
in EM5 (R256/C252 between pin 1 ILIM_HIZ and pin 2 AGND, E4 on pin 1) is correct; only the drawn coordinate is on the wrong
post. T-A-02 (meter every point by net before soldering) would catch it, but any 1:1 print or drawing built from the A.5
coordinate shows E4 on AGND. Confidence: high.

### 7.3 Straight distances re-computed with the true scale

The round-3 placement rule (EIB pad column 7 mm off the right edge, x = 95.90 mm; E3 5 mm above TP33, y = 68.50 mm; rows
2.54 mm apart downward) was re-run with the vector positions and the corrected JP21 pin 1 (`evm_geom.py`). Table 6 gives
the result. These numbers verify the round-3 arithmetic only; round 4 re-places the EVM and must re-derive the maxima.

**Table 6. EIB straight distances, r6 rule, vector positions**

| Lead | Target | Straight (mm) | r3 straight (mm) | x1.25 rounded-up max (mm) | r3 max (mm) |
|---|---|---|---|---|---|
| E8 | TP49 | 13.6 | 13.5 | 20 | 20 |
| E3 | TP33 | 16.7 | 16.5 | 25 | 25 |
| E4 | JP21 pin 1 (lower) | 20.6 | 20.3 | 30 | 30 |
| E2 | JP14 pin 2 | 24.6 | 24.1 | 35 | 35 |
| E7 | TP38 | 29.9 | 29.5 | 40 | 40 |
| E1 | JP12 pin 1 | 69.0 | 67.3 | **90** | 85 |
| E5 | TP36 | 49.1 | 47.7 | **65** | 60 |
| E6 | JP17 pin 1 | 45.4 | 44.3 | 60 | 60 |

The straight distances are 1.0 % to 3.0 % longer than round 3 computed. Under the r6 rule, two build maxima move up one
5 mm step (E1 85 to 90 mm, E5 60 to 65 mm); the six others are unchanged. The E4 distance is the same to either JP21 post
(20.6 mm) only because the E4 row lies between the two posts.

## 8 Mass

[UG] does not give the EVM mass. TODO(measure: scale, +-1 g, as received with shunts fitted, and again after EM7). No
other source was found in this round.

## 9 Findings for the round

1. **No mounting holes (affects A.7 line "EVM: 4 M3 nylon standoffs in the corner holes", EM23, T-A-02 "M3 rod through a
   corner hole" and its "M2.5" fallback).** The EVM is supported only by four adhesive bumpons; the corner circles are
   fiducials. Every mounting scheme must clamp the board edges, use the bumpon positions with adhesive standoffs or pads, or
   add drilled holes. A drilled hole at a bumpon centre cuts the ground pour and 7-17 vias, and two zones overlap the TP48
   and TP49 pads. Severity: high for the mechanical plan (the planned step cannot be executed); no electrical consequence.
2. **The EVM is 88.90 x 88.90 mm.** Its plan area (7903 mm²) is 61.5 % of the MB area (131.064 x 98.044 mm = 12 850 mm²)
   and 2.87 x 2.69 times the 31 x 33 mm CR footprint. An EVM mounted on an extended carrier above the MB would cover most
   of the MB; the 13.0 mm terminal blocks set its top envelope and the 5.08 mm bumpons (or the trimmed TH tails, board
   thickness TODO) set its bottom envelope.
3. **JP21 pin 1 coordinate in A.5 / H.22(i) is the AGND post** (Section 7.2). Correct point: (75.312, 64.769) EVM mm,
   (902.3, 432.2) px in the round-3 render.
4. **Round-3 render scale is 2.2-2.5 % high**; re-derived straight distances are 1-3 % longer and two r6 maxima move up one
   step (Section 7.3).
5. **Edge features that constrain a side-by-side placement:** J5 and J3 face the right edge (wire face x = 86.49, 2.41 mm in
   from the edge); J1/J2 face the left edge (x = 2.60); J4 faces the top edge; J7 faces the bottom edge; J8's mating pins
   overhang the bottom edge to y = -6.24 mm (cable mates from -y); J6 overhangs the left edge by 1.0 mm.

## 10 Open items

- TODO(measure: caliper) board thickness, as-built outline, heights of J7, J8, J9, the jumper headers with shunts, the
  test points and S1; the underside TH-tail protrusion; the EVM mass.
- TODO(verify: TDK SPM6530 datasheet) L2 height 3.0 mm (derived from the BOM package string and the footprint plan).
- TODO(verify: on the received EVM) the terminal-block wire-entry faces inferred in Table 2.
- TODO(verify: TI DBZ0003A and SOD-323 drawings) underside SMT heights.

## 11 Files

| File | Content |
|---|---|
| `work/evm/sluucb5e.pdf` | [UG] as fetched (SHA-256 `a653d3bae48cf0f0cc9f705968d309b90e1f003d50f51b53bee273e874bebfbd`) |
| `work/evm/sluucb5e.txt`, `work/evm/bom_raw.txt` | `pdftotext -layout` of [UG]; raw-order text of the BOM pages |
| `work/evm/p150-15.png` .. `p150-18.png` | Figures 4-1 to 4-4 at 150 dpi |
| `work/evm/p300-15.png`, `work/evm/p300-18.png` | Figures 4-1 and 4-4 at 300 dpi |
| `work/evm/sch200-19.png`, `work/evm/sch200-20.png` | Schematic pages at 200 dpi |
| `work/evm/fig4-1_annotated_300dpi.png` | Table 1 points (red) and round-3 reads (blue) on Figure 4-1 |
| `work/evm/parts/onshore_ED120XDS.pdf`, `onshore_ED120XDS-1.png` | [OST] |
| `work/evm_calc/evm_geom.py`, `work/evm_calc/evm_geom_out.txt` | Extraction, calibration, Table 1, Table 5 and Table 6 |
| `work/evm_calc/annotate.py` | Overlay generator |
