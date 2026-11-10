# Round 4 (r7) minimal-change proposal: CHG carrier with two short tabs

## 0. Scope, conventions and sources

### 0.1 Scope

This note proposes the round-4 (r7) change to the CHG carrier (CR) of the BQ25798EVM path on motherboard (MB) rev
20260622. It answers questions Q1 to Q6 of the round-4 brief and gives the BOM, cost and test-registry deltas. The
approach is minimal change: the smallest sideways extension that removes round-3 burdens, with the EVM and the EVM
interface board (EIB) left where r6 puts them, and the least mechanical risk on a moving vehicle. The EVM stays the
power stage. A custom BQ25798 board is outside the scope of this note.

### 0.2 Conventions

Every coordinate is an Eagle `.brd` board coordinate in mm, top view, origin at the MB origin, +x right, +y up
(design A.2, A.8). EVM points use the EVM frame of `work/evm_geometry.md` section 2.3 (origin at the lower-left corner of
the EVM outline, top view). A **tab** is one rectangle added to the r6 CR outline. **Rule B** is the bottom-part
placement rule defined in section 5.3. Utilisation **U** is courtyard area divided by usable area
(`work/stackup_area.md` section 2.3).

### 0.3 Sources

The design is `docs/charger_bq25798_wiring_design_2026-11-05.md` r6 (the **design**). The round-4 fact-finding notes are
`work/evm_geometry.md`, `work/mb_mechanical.md`, `work/eib_merge_failsafe.md` and `work/stackup_area.md`. The
computations of this note are in `work/minimal_calc/` (section 11). Each number states its source; a value without a
source is marked `TODO(measure: ...)` or `TODO(verify: ...)`, and an assumed input is marked ASSUMPTION.

## 1. Summary

Table 1 gives the answer to each question of the brief.

**Table 1. Answers**

| Q | Answer | Confidence |
|---|---|---|
| Q1 | Add tab X (x 48.70-65.00, y 56.30-68.30) toward the Teensy and tab Y (x 17.70-39.72, y 67.14-76.51) toward L-FC: +401.9 mm² gross, total 1424.9 mm². Keep the TSW 2.54 mm body seated on the MB (no spacer, no sheet): CR underside 2.54 mm, CR top 4.14 mm above the MB. No far-end support is fitted; a foot position is reserved in tab X and fitted only if T-F-19 requires it. | High for geometry (`.brd`); medium for resonance (estimate, M5 decides) |
| Q2 | The EVM cannot mount on the CR or directly beside it on the MB. It stays on the chassis, now on an insulating plate with corner clamps (it has no mounting holes); the EIB moves onto the same plate. W1-W7 stay at <= 0.30 m. E-lead build maxima re-derived on vector positions: E1 85 -> 90 mm and E5 60 -> 65 mm, others unchanged. Add R276 10 ohm in series with E1. | High |
| Q3 | No merge. With the EVM off-board the CR-to-EVM distance is 0.10-0.30 m (geometry G2), where a merge is not acceptable (`work/eib_merge_failsafe.md` section 1.2), and the merged courtyard would raise the r7 top utilisation from 69 % to 88 %. | High |
| Q4 | 4-layer, 1.6 mm, double-sided with passives only on the bottom (<= 1.0 mm), bottom parts under rule B. Single-sided needs U 100-108 % on the r7 outline; a 2-layer CR needs 36.5 mm of loop-to-comparator separation, and no point of the r7 outline is more than 25.7 mm from the commutation loop. | High for the layer count; medium for the area margin (+-50 % routing estimate) |
| Q5 | Retired: footprint confinement, the 84 %/103 % area overrun, the polyimide sheet, the bottom keep-out rectangle, the power-only MB-copper shadow rule (replaced by the stricter rule B), the pin-11 chamfer, the A.7 overhang option. Kept: 4 layers, passives-only bottom <= 1.0 mm, flush-cut W1-W4 tails, top-side SMT tap pads, every U101 loop rule and the A.6 ground scheme. | High |
| Q6 | No EVM or MB modification becomes unnecessary. EM23 is rewritten (no corner holes), EM5 gets the JP21 pin-1 correction, PM4 loses its sheet step and PM6 relocates 18 tap pads to tab X. | High |

## 2. Q1: outline, header stack-up and support

### 2.1 Selection of the sides

The candidate zones of `work/mb_mechanical.md` Table 1 are scored here against the minimal-change aim. Four zones are
rejected.

- **-x and off-board past x = 0:** J-BL and J-FC are 21.70 mm tall and J-NTC 13.90 mm (`TB005-762_CUI.pdf` p.2; Würth
  691411410002 p.1); a 2.54 mm body cannot pass over them, and the zone sits in the J-BL wire-entry path. J-BL must stay
  pluggable.
- **-y usable:** the zone covers BAL pad 8 (T22, PM11), RB1A and CBL2, which the battery-isolation gates name as check or
  rework points, and lies 2.96 mm from the VSW-BT pour.
- **+y wide and both edge-reaching zones:** these need >= 2.75 mm (OP-FC 1.75 mm) or >= 6.0 mm (L-FC/L-BT 5.0 mm) of
  body, and they cover the FC droop analog or a boost switching node.
- **+x usable beyond x 65.00:** the extension to x 80.23 is a 34.2 mm cantilever with an estimated first mode of
  0.51-0.73 kHz (`work/mb_mechanical.md` 6.4) that needs a bonded far-end foot, and its underside beyond x 65.53 lies over
  the 16 V VBUS L1 pour.

The two zones that need no support and no raised stack are kept, each trimmed. Tab X is the +x core of
`work/mb_mechanical.md` with its low edge raised from y 55.01 to y 56.30. That edge then keeps 1.79 mm of plan clearance
to the REG-5V (LM1084) body top at y 54.51, the same clearance that the r6 outline keeps on its +x side (design A.7: LM1084
1.8 mm right). Tab X stops at x 65.00, 0.53 mm before the VBUS L1 pour (x 65.53). Tab Y is the +y usable zone unchanged.

### 2.2 Outline

The r7 outline is the r6 rectangle (x 17.70-48.70, y 34.14-67.14, design A.7) plus the two tabs. Table 2 lists its ten
vertices in counter-clockwise order.

**Table 2. r7 CR outline vertices (board mm, top view, +y up)**

| # | x | y | Corner |
|---|---|---|---|
| 1 | 17.70 | 34.14 | convex (r6 corner) |
| 2 | 48.70 | 34.14 | convex (r6 corner) |
| 3 | 48.70 | 56.30 | concave (tab X root) |
| 4 | 65.00 | 56.30 | convex |
| 5 | 65.00 | 68.30 | convex |
| 6 | 48.70 | 68.30 | convex |
| 7 | 48.70 | 67.14 | concave |
| 8 | 39.72 | 67.14 | concave (tab Y root) |
| 9 | 39.72 | 76.51 | convex |
| 10 | 17.70 | 76.51 | convex |

The gross area is 1424.9 mm² (r6 1023.0 + tab X 195.6 + tab Y 206.3), and the bounding box is x 17.70-65.00,
y 34.14-76.51 (47.30 x 42.37 mm). The three concave corners take the fab router radius; no part sits within 0.5 mm of
them. `TODO(verify: fab minimum inside-corner radius)`.

Table 3 gives the plan clearance of each tab to its MB neighbours (`.brd` element boxes from
`round4/calc/mb_neighbours_out.txt`; copper from `work/minimal_calc/r7_minimal_calc_out.txt`).

**Table 3. Tab clearances in plan**

| Tab edge | Neighbour (height) | Clearance |
|---|---|---|
| Tab X low edge y 56.30 | REG-5V body top y 54.51 (4.83 mm) | 1.79 mm |
| Tab X low edge | 5V pour rim, y ~54.86 (0.15 mm below the +x usable edge, `work/mb_mechanical.md` 4.1) | ~1.44 mm |
| Tab X right edge x 65.00 | VBUS L1 pour x 65.53 (copper only) | 0.53 mm |
| Tab X corner (65.00, 68.30) | C-D2 x 67.12-70.04, y 68.80-70.90 (1.10 mm; R171 joint, PM3) | 2.18 mm |
| Tab X top edge y 68.30 | MDAC-FC y 70.00 (1.10 mm) | 1.70 mm |
| Tab Y right edge x 39.72 | OP-FC x 40.22 (1.75 mm) | 0.50 mm |
| Tab Y top edge y 76.51 | L-FC y 77.01 (5.0 mm) | 0.50 mm |
| Tab Y left edge x 17.70 | J-FC rear face x 16.13 (21.70 mm; `work/mb_mechanical.md` 3.2) | 1.57 mm |
| Tab Y corner (17.70, 67.14) | J-NTC box corner (16.25, 67.35) (13.90 mm) | 1.45 mm |
| Tab Y underside | ROP1-FC (0.60 mm), ROP2-FC box corner overlap 0.55 x 0.09 mm (0.60 mm) | 1.94 mm air under the CR |

No MB part lies under tab X, and only ROP1-FC and ROP2-FC (0603, 0.60 mm) lie under tab Y. Neither tab covers a named
rework point: the R171/T2 joint, RENC2, BAL pad 8, RB1A, CBL2, CO-5V and the T18 point all stay open from above. J-BL
screws (axis x ~9.4) and the -x wire entries of J-BL, J-NTC and J-FC are untouched.

### 2.3 Header stack-up and post length

The CR keeps the r6 header parts: Samtec TSW-110-07-G-S (column x 45.998, pins 1-10) and TSW-112-07-G-S (column
x 20.998, pins 11-22), 2.54 mm PBT body, 0.64 mm square phosphor-bronze post (design E; Samtec F-226). No spacer is
added. With the polyimide sheet retired (section 6), the body rests on the MB top surface, so the CR underside is
2.54 mm above the MB (r6: 2.665 mm on the sheet) and the CR top is 4.14 mm above the MB (CR 1.6 mm, ASSUMPTION of PM4,
`TODO(verify: CR fab stack-up)`).

Table 4 gives the post arithmetic of the -07 lead style (B 2.54 mm below the body, C 5.84 mm above it; `work/mb_mechanical.md`
Table 7) with the MB and CR both 1.6 mm thick (ASSUMPTION; `TODO(measure: MB thickness at the CHG holes)`).

**Table 4. TSW-1xx-07 post arithmetic (`work/minimal_calc/r7_minimal_calc_out.txt`)**

| Orientation (PM4 step 2) | CR-top protrusion | MB-bottom protrusion | Verdict |
|---|---|---|---|
| short end B (2.54 mm) up through the CR | 0.94 mm (>= 0.5 mm fillet rule, PM4) | 4.24 mm, cut to <= 1.0 mm in PM4 step 4 | adopted |
| long end C (5.84 mm) up through the CR | 4.24 mm (trim needed) | 0.94 mm | allowed; T-A-05 decides |

The stack height over the footprint is unchanged from r6 except for the 0.125 mm sheet. The tallest item stays the
mated W5 IDC socket and its ribbon fold at >= 8 mm above the CR top (design A.3), about 12.1-12.3 mm above the MB plus
the cable. The nominal Ag105 envelope is 13.14 mm above the MB (`AG105_Silvertel.pdf` Figure 11 p.21; gate D-2 not
measured). Over tab X the top items are SMT tap pads with 26 AWG wires and an RTV bead (bead height
`TODO(measure: T-A-09)`); over tab Y they are SSOP-8, SC70 and 0603 parts (`TODO(verify: TI DCT/DCK package heights)`).
The lid clearance over both tabs is not recorded (M2).

### 2.4 Mechanical check and support decision

The elastic pin-group model of `work/mb_pinload.py` was re-run for the two tabs together (main CR 5-10 g and a populated
areal mass of 0.6-0.8 g/cm², both ASSUMPTION). Table 5 gives the result.

**Table 5. Pin load and first-mode estimate (ORDER OF MAGNITUDE; `work/minimal_calc/r7_minimal_calc_out.txt`, `r7_handling_out.txt`)**

| Case | r7 (tab X + tab Y) | r6 CR alone | Note |
|---|---|---|---|
| Worst axial pin load, 10 g normal shock | 0.074-0.113 N | 0.022-0.045 N | x2.2-4.1 |
| Worst axial pin load, 30 g normal shock (30 g ASSUMED, M5) | 0.221-0.339 N | 0.067-0.134 N | pin section ~141 N at an assumed 345 MPa yield: >= 400x margin |
| 10 N handling push at the tab X tip (65.00, 62.30) | 2.69 N on pin 10 | - | |
| 10 N handling push at the tab Y tip (28.71, 76.51) | 3.07 N on pin 11 | - | |
| f1, tab X (19.0 mm from the x 45.998 column) | 1.66-2.35 kHz unpropped | - | E 20 GPa, t 1.6 mm ASSUMED; clamped-root upper estimate |
| f1, tab Y (12.0 mm from pin 11) | 4.16-5.88 kHz unpropped | - | as above |

Static strength does not decide the support: the worst pin load stays more than two orders of magnitude below the pin
section capacity. The estimated first modes are 3.2 times (tab X) and 8.1 times (tab Y) those of the rejected 34.2 mm
extension. However, the vehicle spectrum is not measured (M5), and the real root is compliant, so the true modes are lower
than the estimates.

The proposal therefore fits no support and reserves one. A 4 x 4 mm bottom-side keep-out at x 60.70-64.70,
y 59.26-63.26 (centred on the `work/mb_support_spots_out.txt` off-pour spot (62.7, 61.26)) holds no part and no exposed
copper. If T-F-19 requires it, a nylon spacer of the measured body height is bonded to the CR underside there and rests on
the MB solder mask without adhesive. That foot leaves the MB mask intact on removal, which the MB-bonded foot of
`work/mb_mechanical.md` Table 5 does not. The square costs 0.3 mm² of rule-B area; it lies over 4.9 mm² of MB signal
traces under solder mask and over no via (`work/minimal_calc/r7_foot_check_out.txt`).

### 2.5 LM1084 proximity

Tab X spans distances of 1.44 mm (low edge) to 13.44 mm (top edge) from the 5V pour rim. The estimated MB surface rise
at 0.40-1.08 W is 4.5-23.5 C at 1 mm, 3.3-17.0 C at 5 mm and 2.4-11.9 C at 10 mm (`work/mb_mechanical.md` Table 4,
ESTIMATE). The proposal fills tab X with temperature-insensitive features only: the tap-field pads, R175 and 1 % logic
passives on the underside. The comparators, 0.1 % dividers, BAV199 clamps and monostable timing parts stay on the
footprint, where the nearest of them can sit >= 10 mm from the pour rim. M4 replaces the estimate.

### 2.6 Measurements before the outline is frozen

The operator makes the following measurements before PM0 freezes the outline. Each item names the decision it controls.

1. **M3, tab footprints (gate for PM0):** inspect x 48.70-65.50, y 55.80-68.80 and x 17.20-40.22, y 66.64-77.01 for
   unrecorded items: the OPA197 5 V bodge wire (OP-FC is 0.50 mm from tab Y), the 10 kOhm EN bodge resistors, the
   74HC14 and the encoder reroute wires; record each position and height. Any item inside a tab outline + 0.5 mm trims
   that tab, and `r7_minimal_calc.py` is re-run.
2. **M1, gate D-2 (before PM1):** the Ag105 standoff (MB top to module underside) at four corners, the module top height
   above the MB and the module mass. The CR stack top (about 12.1-12.3 mm plus the cable) is compared with the measured
   module top height.
3. **M2, enclosure:** the lid clearance over the footprint and over both tabs, the lid profile, and the chassis clearance
   under the MB for the 22 MB-bottom tails (<= 1.0 mm after PM4 step 4). It also fixes the EVM plate position (section 3.2).
4. **MB and CR thickness:** caliper the MB at the CHG holes; obtain the CR thickness from the chosen fab stack-up. Both
   enter Table 4 and the f1 estimate.
5. **M4, LM1084 thermal survey:** tab, pour rim and MB surface at 1, 5, 10 mm along x = 57 into tab X (y 55.9, 59.9,
   64.9), closed enclosure, Run with Ethernet and SD active, V_batt 8.4 V and 7.4 V, 30 min soak (`work/mb_mechanical.md`
   5.4). It confirms the section 2.5 split.
6. **M5, vibration:** an accelerometer log on the MB near pin 10 in a representative run, spectrum 0.1-8 kHz. It decides
   the reserved foot (T-F-19).
7. **EVM as received:** thickness, as-built outline and mass with shunts fitted (`work/evm_geometry.md` section 10). They
   size the corner clamps of section 3.2.

## 3. Q2: EVM mount and lead lengths

### 3.1 EVM on or beside the CR

The EVM cannot mount on the CR extension. The EVM is 88.90 x 88.90 mm (7903 mm²; `work/evm_geometry.md` section 3),
5.5 times the r7 CR gross area, and it has no mounting holes. On the 22 pins its weight would add 0.066-0.084 N per gram of
EVM to the worst pin at 30 g, for a centre of gravity 44.5-60 mm from the pin centroid (`r7_minimal_calc_out.txt`; EVM
mass `TODO(measure)`). The Ag105 precedent put its centre of gravity on the pin centroid and gives no support for such a
moment.

The EVM also cannot sit directly beside the CR on the MB. No part-free MB region of 89 x 89 mm exists: the EVM would cover
J-BL (21.70 mm), whose screws must stay reachable, or the Teensy and the boosts. The MB has only two plain holes, both at
x 3.30 behind the 21.70 mm terminal blocks (`round4/calc/mb_neighbours_out.txt`). A mezzanine plate above the whole MB on
chassis posts would shorten every lead but would cover the J-BL screws and needs the unrecorded lid height (M2). It is
outside the minimal approach and is recorded as an alternative for the orchestrator.

### 3.2 EVM mount (EM23 rewritten)

The r6 mount (four M3 standoffs in the corner holes, EM23, A.7) cannot be built, because the corner circles are
fiducials (`work/evm_geometry.md` finding 1). A drilled hole at a bumpon centre cuts the board-wide ground pour and 7-17
vias. The proposal keeps the four stock bumpons H1-H4 (3M SJ-5303, 11.18 mm diameter, 5.08 mm tall) as the underside
standoffs on an insulating plate fixed to the chassis. Four insulating L-brackets, screwed to the plate, press the top
surface at the corners and preload the bumpons. Each lip reaches <= 2.0 mm inboard of both edges at one corner. That
area lies outside every terminal-block body and the J8 mating side (`work/evm_geometry.md` Table 2), inside the 2.03 mm
edge strip that the bumpon footprints leave free, and clear of TP49. The lip may rest on a fiducial dot.
`TODO(verify: TP48 centre from SLUUCB5E Fig 4-1)`. The bumpons clear the through-hole tails (terminal-block lead 4.0 mm
minus the board thickness, `TODO(measure)`).

The EIB moves from the chassis onto the same plate, on its two M3 nylon standoffs, with the r6 placement rule (pad column
7 mm off the EVM right edge, E3 5 mm above the TP33 level). The EVM and the EIB then form one rigid body, so the E-leads see
no relative motion. The plate keeps the EVM >= 20 mm from the LM1084 side of the MB (A.1). The plate and clamp geometry is
`TODO(design: from M2 and the EVM thickness)`.

### 3.3 W1-W7

W1-W7 do not shorten. Their CR ends stay at the r6 positions: W1 (30.3, 61.2), W2 (27.7, 61.2), W3 (24.3, 45.4), W4
(24.3, 55.6), the W7 pads at y 57.5 (x 27.0/29.0/31.0) and the W6 pads at (33.0, 57.5)/(35.0, 57.5) (A.8). Their EVM ends are
unchanged (J1, J5, J7, J8). The maximum length stays 0.30 m each; the actual route is set by the plate position (M2).

### 3.4 E1-E8 and the re-derived H.22(i) maxima

The EIB placement is unchanged, so the r6 rule (straight distance x 1.25 for routing around parts, rounded up to 5 mm) is
re-run on the vector EVM positions of `work/evm_geometry.md` Table 6. JP21 pin 1 (ILIM_HIZ) is the lower square post at
(75.312, 64.769) EVM mm; the A.5 pixel point (902, 408) is the AGND post. Table 6 gives the maxima together with the pickup
criterion of `work/eib_merge_failsafe.md` Table 9 (sustained EMF <= 10 % of the smallest margin the lead serves).

**Table 6. E-lead maxima (r7)**

| Lead | EVM point | Straight (mm) | r6 build max | **r7 build max** | Pickup-criterion limit | Build max / limit |
|---|---|---|---|---|---|---|
| E8 | TP49 (83.440, 79.120) | 13.6 | 20 | **20** | runs with E3/E4 | - |
| E3 | TP33 (80.011, 63.499) | 16.7 | 25 | **25** | 92 mm untwisted at s 5 mm; 206 mm at s 2 mm | 0.27 |
| E4 | JP21 pin 1, lower post (75.312, 64.769) | 20.6 | 30 | **30** | 59 mm at s 5 mm; 131 mm within 2 mm of E8 | 0.51 |
| E2 | JP14 pin 2 (71.375, 64.769) | 24.6 | 35 | **35** | none (48.7 kOhm feed) | - |
| E7 | TP38 (66.041, 59.689) | 29.9 | 40 | **40** | none (static) | - |
| E1 | JP12 pin 1 (39.370, 13.741) | 69.0 | 85 | **90** | none (static); R276 required | - |
| E5 | TP36 (55.874, 19.710) | 49.1 | 60 | **65** | none (static, open drain) | - |
| E6 | JP17 pin 1 (54.611, 26.796) | 45.4 | 60 | **60** | 196 mm at s 5 mm | 0.31 |

The geometric maximum stays the T-A-02 gate, because the criterion limits rest on assumed loop areas and aggressor classes
(medium confidence). The criterion documents the margin of that gate: every length-critical build maximum is at most
0.51 of its criterion limit, and E4 is the tightest. A length-critical lead found over its build maximum but under its
criterion limit is re-dressed and re-measured; its safety argument is not void.

E1 needs a series damper at 90 mm. E1 with its E8 return and C205 (100 nF) forms a series LC that resonates at 1.47 MHz at
85 mm and 1.43 MHz at 90 mm (1/sqrt(L) scaling from `work/eib_merge_failsafe.md` 3.4). The BQ25798 switches at 1.5 MHz
(JP24 kept, EM19), and the undamped Q is about 19-20. A 10.0 ohm resistor R276 in series with E1 at the EIB pad reduces Q to
about 0.1 and shifts the release level by 1.6 mV (2 mA of ILIM clamp; same source). The gate nodes are already protected
by the 68 kHz R252 x Ciss low-pass; R276 removes the unbounded circulating current in E1/E8.

## 4. Q3: EIB merge

The EIB stays a separate board, and the W5 ribbon stays. Three facts decide it.

1. With the EVM on the chassis, the CR-edge-to-EVM-pin distance is 0.10-0.30 m (geometry G2). Over that distance the
   merge exports the unbuffered ILIM_HIZ node, REGN, /CE and STAT, and a single E-bundle short E1 to the ILIM group removes
   the hardware input clamp undetected (`work/eib_merge_failsafe.md` sections 1.2, 3.6).
2. The re-proof for G2 needs EVM-end parts and shielded cables, which re-create the EIB (`work/eib_merge_failsafe.md`
   section 8).
3. The merged courtyard adds ~253 mm² and removes J101 (37 mm²). On the r7 outline the top utilisation with the r3 bottom
   set would rise from 68.7 % to about 88 %, above the 75 % budget.

Because nothing about the EIB moves, every r6 fail-safe argument holds as is: r1-2 (two series switches, drivers at the EVM
pins), the /CE pull-ups R272/R272b on separate EVM joints, the far-end senses U203/U204, the E8/R273 single DC ground and
the full W5 adjacent-short list. Three round-4 facts change the EIB documentation without touching an argument: the JP21
pin-1 coordinate, the E1/E5 maxima of Table 6 and R276. For the record, a G2 merge would need re-proof of the r1-2
two-switch argument, the U203/U204 lead-off detection (chatter against the FR-08 2 ms / 1 ms persistence), the E1
exposure, the E6-E7 bridge and the B.6 rows "Q203 D-S short" and "E4/E6 lead off" (`work/eib_merge_failsafe.md` Tables 6
and 7). A G1 merge (EVM within 10-60 mm) would be acceptable under ten conditions, but G1 needs the EVM beside the CR,
which section 3.1 rules out here.

## 5. Q4: layer count, placement sides and stack-up

### 5.1 Decision

The CR stays 4-layer, 1.6 mm, double-sided with passives only on the bottom. Three results decide it.

1. **Area:** single-sided placement on the r7 outline needs U = 100.4-108.3 % (all DNP footprints removed / all footprints
   kept; strict basis), against the 0.75 budget (`r7_minimal_calc_out.txt`). Single-sided needs +800 to +920 mm² of
   extension (`work/stackup_area.md` section 4); the viable zones offer at most about +622 mm².
2. **Separation:** a 2-layer CR couples 46-53 times more strongly into the comparator inputs and needs 36.5 mm of
   separation to match the 4-layer coupling at 5 mm (`work/stackup_area.md` 5.2). The farthest point of the r7 outline from
   the U101/C102/D103 loop region is (17.70, 34.14) at 25.7 mm; no point reaches 36.5 mm (`r7_minimal_calc_out.txt`).
3. **Commutation loop:** 2-layer raises the loop inductance 4-7 times per mm (0.734-0.769 against 0.101 nH/mm at 2.5 mm
   width) and adds 0.45-3.0 V to the OUT-side excursion at 45 A, against 0.11-0.43 V on 4-layer (`work/stackup_area.md`
   5.1).

The 3.21 A battery copper does not decide the layer count: W3/W4 stay at the pin columns, and both layer counts carry
3.5 A in the >= 2.5 mm external pours (4.6 A on 1 oz, 7.7 A on 2 oz at 10 C rise; H.22(c)).

### 5.2 Area booking

The booking uses the strict basis of `work/stackup_area.md` (footprint top 732 mm²; demand 1188 mm² = 1128 mm² of
courtyards + 60 mm² of L1 pours). Table 7 gives the r7 figures.

**Table 7. Area booking, strict basis (`r7_minimal_calc_out.txt`, `r7_footprint_underside_out.txt`)**

| Item | r6 | r7 |
|---|---|---|
| Top usable (mm²) | 732 | 1096.6 (+ tab X 173.8, tab Y 185.9, tab X root strip 4.9) |
| Top U with the r3 bottom set (435 mm²) | 103 % (95 % without the pours) | **68.7 %** |
| Bottom area under rule B (mm²) | not applicable (r3 shadow basis 591) | 618.9 = footprint 383.9 + tab X 57.0 + tab Y 177.9 |
| Bottom U with the r3 bottom set | 74 % (435 of 591, r3 shadow basis) | **70.3 %** (435 of 618.9) |
| Bottom set needed for top U 0.70 / 0.75 / 0.80 | 638 at 0.75 | 420 / 366 / 311 mm² |
| Rule-B capacity at the same U | - | 433 / 464 / 495 mm² (margin +13 / +98 / +184) |
| Single-sided U | 162 % | 100.4-108.3 % |

Both sides land near 70 % against the 75 % budget. The narrowest case is the 0.70 end of the budget, with 13 mm² (3 %) of
margin. If the T-A-06 placement DRC fails there, the five footprints of parts the design forbids to fit (R106, R134,
R145, R146, C105: 19.3 mm²) are deleted first; a deleted footprint also removes the chance of fitting a forbidden part.

### 5.3 Bottom-part rule B

Every bottom-side part keeps its courtyard >= 1.0 mm in plan from every MB layer-1 (top) feature that is not GND: traces,
pours, vias of any net and MB part pads; MB parts are excluded with +1.0 mm on their boxes. The rule holds on the
footprint and on both tabs. In addition, no bottom-side part carries VCHGIN, VCHGOUT or VCHG; the power-path parts stay
on the top side, as in r6 (A.8). Rule B replaces the r3 power-copper shadow (VBT, VBT pour, VCHG pour and VCHG-IN, +1 mm) and
the named bottom keep-out (x 24.5-36.0, y 48.5-53.5), because the five MB parts in that keep-out are excluded by the same
rule. Under rule B, the only MB copper under a bottom-part terminal is the GND pour.

Rule B is also what retires the polyimide sheet (section 6, item 4). The sheet was a secondary barrier between exposed
bottom-part terminals at 1.54 mm of air and MB power copper with no current limit in Run (A.7, finding
cr-bottom-over-mb-power-traces). Under rule B a chafed terminal can only meet MB GND. Every CR net that a bottom part
carries is then held by an existing limiter: R175 (68 ohm) on the CR 3V3 rail, the R170/R171 10 kOhm joints on the
divider tops, and series resistors on the logic nets. The fault then equals a CR-internal short to GND, which the H.1
(tap short, 2.2 mA), H.20 (rail short, 48.5 mA) and B.7 rows already bound.

### 5.4 Stack-up

The stack-up is the one of `work/stackup_area.md` 7.2, unchanged from r6. Table 8 lists it.

**Table 8. CR stack-up (1.6 mm 4-layer, symmetric)**

| Layer | Copper | Dielectric below | Content |
|---|---|---|---|
| L1 top | 2 oz (1 oz allowed by the PM0 DFM check, then pours >= 2.5 mm battery side, >= 2.0 mm input side) | prepreg 0.2 mm | every IC, the power pours VCHGIN/VCHGOUT/VCHG and the GND star, signals |
| L2 | 1 oz | core ~1.0-1.1 mm | solid GND reference plane, antipads only, continuous into both tabs |
| L3 | 1 oz | prepreg 0.2 mm | signals: I2C, TS, tap-to-logic runs from tab X, readbacks, logic mesh, the C102b link if it stays off L1 |
| L4 bottom | 2 oz (1 oz allowed) | - | GND pour stitched to L2 at <= 5 mm, around the bottom passives; solder mask over every via (tented); no exposed copper except the W1-W4 pads and the 22 header rings inside the bodies |

Only the two 0.2 mm prepregs enter the 2 nH loop budgets of A.8 and H.21(k). `TODO(verify: chosen fab 1.6 mm 4-layer
stack-up table, via plating 25 um, tenting on L4)`.

### 5.5 Placement allocation

The tabs change where part groups go; the T-A-06 placement DRC decides the final positions. Table 9 gives the
allocation and its reason.

**Table 9. Placement allocation**

| Region | Content | Reason |
|---|---|---|
| Tab X top | Tap field: 21 SMT pads 1.5 x 1.5 mm in a 6 x 4 grid at 2.54 mm, centres x 50.73-63.43, y 57.80-65.42 (F01-F07, F11-F24; envelope x 49.98-64.18, y 57.05-66.17); R175 1206 beside F07 | temperature-insensitive; nearest to J1, J2, C-D2 and the ROS pad; field low edge 2.19 mm from the 5V pour rim |
| Tab X bottom | rule-B passives (57.0 mm²): 1 % series resistors and pull-downs of the tap-to-logic nets; the reserved foot keep-out | rule B; temperature-insensitive |
| Footprint low-y band (the freed r3 tap-field area, x 23.15-42.43, y 35.05-41.63, ~150 mm²) | residual pads F08 (T22) at (26.44, 35.80), F09 (T8) at (28.98, 35.80), F10 (T9) at (31.52, 35.80); comparators U102-U104, U115, U119-U121 with their 0.1 % dividers and filter caps moved from the bottom to the top | 10.4 mm from the commutation-loop band (y >= 52.03) and 8.5-27.8 mm from the LM1084 body (x 50.97); stackup_area 7.1 moves precision analog to the top first |
| Footprint high-y band | U101, C102a/b/c, D107, C103, D103, R102 and the +x pocket, W1/W2 | A.8 r5 table unchanged |
| Footprint interior | J101 (r5 region x 37.0-44.5, y 42.13-51.53), U122/U123/D108 near F08, monostables U111/U113 with R150/C150/R151/C151, W3/W4, W6/W7 pads | A.8 unchanged; RC timing nodes >= 10 mm from L-FC |
| Tab Y top | LVC gates U105-U110, U114, U116, U118 with their decouplers | driven logic nodes only; the whole tab lies within 9.87 mm of L-FC (y 77.01), so no comparator input or timing node goes there |
| Tab Y bottom | rule-B passives (177.9 mm² available): logic pull-downs, series resistors, decouplers | clean copper (one N$8 trace, one GND via) |

The three twisted tap pairs land on adjacent pads (T1/T7b, T17/T17r in tab X; T8/T9 in the residual row). The straight
sum of the 20 tap lengths falls from 1308.9 mm to 892.8 mm (-32 %): T2 47.0 -> 13.4 mm, T20 58.0 -> 25.8 mm, the J1 taps
54-60 -> 30-40 mm, the J2 taps 77-90 -> 53-60 mm; T8 rises from 78.6 to 82.8 mm (`r7_minimal_calc_out.txt`). The A.4 maximum
lengths stay valid upper bounds. Tap wires from tab X are dressed in +y of y 56 until x > 63, so none lies on the
LM1084 body.

## 6. Q5: round-3 constraints retired and kept

Table 10 takes each round-3 constraint in turn. "Retires" means the constraint is removed from the design; "stays" means
it applies unchanged; "changes" means it applies in the stated new form.

**Table 10. Round-3 constraints under r7**

| # | Constraint (design section) | r7 | Reason |
|---|---|---|---|
| 1 | CR confined to the 31 x 33 mm footprint (A.1, A.7) | **retires** | tabs X and Y, +401.9 mm² (section 2.2) |
| 2 | Area budget: top ~678 of ~881 mm² (H.18, H.22(k)), strict basis 95-103 % | **retires** | top 68.7 %, bottom 70.3 % (Table 7) |
| 3 | 4-layer build (A.1, H.18) | **stays** | electrical: separation and loop inductance (section 5.1) |
| 4 | Polyimide sheet over the MB under the CR (A.7, PM4 step 1, E) | **retires** | rule B removes the exposed-terminal-over-power-copper case that the sheet guarded; conditions: rule B on every bottom part, all L4 vias tented, W1-W4 tails <= 0.5 mm measured, W1/W2/W4 over the MB GND pour and W3 over the same-net VCHG pour (`r7_footprint_underside_out.txt`); a PM4 step 1a overlay (bare VBT copper) and the step 1b thermocouple joint get one layer of Kapton tape instead |
| 5 | Passives-only bottom, <= 1.0 mm (A.7) | **stays** | single-sided U 100-108 %; the 2.54 mm body leaves 1.54 mm of air over a 1.0 mm part |
| 6 | Bottom keep-out x 24.5-36.0, y 48.5-53.5 (A.7) | **retires as a named rectangle** | rule B excludes the five MB parts in it (+1 mm) |
| 7 | MB power-copper shadow +1 mm (A.7, H.18) | **changes** to rule B | stricter: every non-GND MB L1 feature, on the footprint and the tabs; it still applies where the CR sits over MB VBT, VCHG and VCHG-IN |
| 8 | Flush-cut tails <= 0.5 mm "everywhere" (A.7, PM4 step 2b) | **stays, for W1-W4** | W1-W4 are the only CR through-hole parts with a tail on the CR underside (the header bodies cover the pin rings); a tail must stay below the 2.54 mm gap; the cut must precede seating |
| 9 | No bottom-side tap tails; top-side SMT tap pads F01-F24 (A.4, A.7) | **stays** | tab X lies over MB MPPT-DISABLE (CHG_ARM), CB-DISABLE, CHRG-STAT, SCL, SDA and 3V3 traces; a tap tail would face them |
| 10 | Pin-11 chamfer as the mirror marker (A.7 r6) | **retires** | a y-mirrored CR puts tab X at y 32.73-44.73 over REG-5V (4.83 mm) and CO-5V, so it cannot seat (`r7_handling_out.txt`); pin-1/pin-11 silkscreen marks stay |
| 11 | A.7 "overhang only if the capture needs it" (low-y over C4A/B-BT, high-y over OP-FC) | **retires** | replaced by the defined tabs; the -y and +y-wide overhangs stay excluded |
| 12 | EVM on four M3 standoffs in the corner holes (A.7, EM23) | **retires** | the holes do not exist (section 3.2) |
| 13 | EIB on two M3 standoffs on the chassis (A.1, A.7) | **changes** | same standoffs, on the EVM plate |
| 14 | U101 at pad 10, VCHG-IN <= 5 mm, C102/C103/D103/D107 placement, <= 2 nH loop rules (A.8, H.21(k)) | **stays** | unchanged geometry |
| 15 | A.6 ground scheme (star at pads 4/14/15, W2 pour, Kelvin T9, shields bonded at the CR end) | **stays** | the L2 plane extends into the tabs; no new DC path |
| 16 | W1-W4 hole sizes and positions; W3/W4 at the pin columns (A.8) | **stays** | the 3.21 A battery current stays out of the tabs and away from the comparators |
| 17 | Header strips 1x10 + 1x12, pin ratings (pad 10 >= 3 A, VBAT+/GND >= 2.0 A) (A.8, T-A-05) | **stays** | unchanged |
| 18 | Courtyards >= 0.5 mm from the outline and from the header, W1, W2, W6, W7 pads (A.7, A.8) | **stays** | applied to the r7 outline |
| 19 | MB battery path under the CR: T-A-06c Kelvin check, PM4 step 1a overlay option, T-F-16 thermocouple (A.8 r6) | **stays** | the CR still sits over the MB VBT trace; the overlay stays reachable only before the CR is seated |

## 7. Q6: EVM and MB modifications

### 7.1 Study M1-M11 against design EM1-EM25

Table 11 maps the study modifications (`docs/charger_replacement_evaluation_2026-11-05.md` section 4.2) to the design
list (design C) and states the r7 status of each.

**Table 11. EVM modifications**

| Study | Design | r7 status |
|---|---|---|
| M1 (remove JP17) | EM1 (shunt and JP17 pin 2 removed) | needed |
| M2 (stage A NMOS on /CE) | superseded by EIB U201 ch1 (B.6) | - |
| M2b (/CE pull-up from REGN) | EM2 (R42 -> R272/R272b to REGN) | needed |
| M3 (stage B ILIM network) | EM3 (R21 0 ohm, JP14/JP13 pin 1 and R20 removed), EM4 (R23 49.9k), EM5 (R256/C252 at JP21) + EIB Q201-Q203 | needed; EM5 text corrected: JP21 pin 1 is the lower square post (75.312, 64.769) |
| M4 (R39/R40, JP32) | EM6, EM8 | needed |
| M5 (JP1-JP4, J2) | EM10, EM11, EM7 (J2, plus J3/J4 in r3) | needed |
| M6 (JP5, JP8, JP9) | EM12, EM13, EM9 | needed |
| M7 (input caps >= 35 V) | EM14 (+ PM2 on the MB) | needed |
| M8 (1 kOhm VBT -> VCHG proposal) | not an EVM change; became the B.5 keep-alive option and PM7 | option |
| M9 (TS via J7) | EM18 (+ W6) | needed per T-E-09 |
| M10 (keep JP24) | EM19 | needed |
| M11 (JP6, JP10, JP11) | EM16 | needed |
| - | EM15, EM17, EM20, EM21, EM22, EM24, EM25 (design-only) | needed |
| - | EM23 (bumpons removed, M3 standoffs) | **rewritten**: bumpons kept; plate and corner clamps (section 3.2) |

No EVM modification becomes unnecessary. Every EM item serves the electrical function of the EVM, which the r7 carrier
change does not touch.

### 7.2 MB modifications PM0-PM11

No MB modification becomes unnecessary. Four change content.

- **PM0:** capture on the Table 2 outline; rule B in the bottom-side DRC; tap field split per Table 9; no chamfer.
- **PM1:** M1 (gate D-2) is recorded before the Ag105 is removed. After removal, the 22 MB top pads are wicked flat, because
  the header bodies now rest on the MB surface and not on the sheet.
- **PM4:** step 1 (bond the sheet) is deleted. Steps 1a and 1b stay before seating, with Kapton tape over the overlay and the
  thermocouple joint. Step 2 uses the Table 4 orientation. Step 2b (W1-W4 cut to <= 0.5 mm before seating) stays. Step 3
  supports the CR under both tabs while the MB joints are soldered.
- **PM6:** 18 taps land on the tab X field and three (T22, T8, T9) on the residual pads F08-F10.

PM2, PM3, PM5 (deleted), PM7, PM8, PM9, PM10 and PM11 are unchanged. The D.4 bodge-record sentence on the polyimide sheet
becomes "the carrier underside carries passives only, each >= 1 mm from every non-GND MB copper feature; no sheet".

## 8. BOM and cost delta

Table 12 lists the BOM lines that change. Every cost is a budget allowance, not a verified price, as in design E.

**Table 12. BOM delta**

| Line | r6 | r7 | Cost delta |
|---|---|---|---|
| CR PCB (5 pcs) | 31.0 x 33.0 mm, 4-layer, 2/1/1/2 oz, ENIG | Table 2 outline, bounding box 47.30 x 42.37 mm (area x1.39, box x1.96), same stack-up | allowance USD 70 -> 70-100 (`TODO(verify: fab quote)`) |
| Polyimide sheet | 0.125 mm film, silicone PSA, 1 sheet (+1) | deleted | -USD 10 |
| R276 (new, EIB) | - | 10.0 ohm 1 % 0603, CRCW060310R0FKEA (same MPN as R273), 1 (+1) | negligible |
| EVM mounting | M3 x 10 nylon standoffs x 4 for the EVM | insulating plate + four corner clamps (`TODO(design)`); EVM standoffs deleted; the EIB keeps its two | allowance +USD 0-15 |
| Reserved tab X foot | - | nylon spacer cut to the measured body height, DNP until T-F-19 | +USD 0-2 |
| 26 AWG wire | >= 5 m in two colours | unchanged order (the cut lengths fall by about 32 %) | 0 |
| Header strips, EVMs, all other parts | as design E | unchanged | 0 |

The net change is about -USD 10 to +USD 37 on the USD 505-540 r6 total, i.e. about USD 495-577 (not verified).

## 9. Test-registry delta

### 9.1 Retired

No whole test retires. The following steps leave their tests:

- T-A-02: "corner-hole diameter", "M3 rod through a corner hole" and the "M2.5 or adhesive standoffs" fallback;
- T-A-05: the polyimide sheet line (thickness, adhesive, dielectric strength, temperature);
- T-A-06: the 1:1 print of the polyimide sheet (outline + 1 mm, pad holes, five cut-outs);
- T-F-12: "inspect the polyimide sheet for chafe" (replaced in 9.2).

### 9.2 Changed

- **T-A-02:** E-lead lengths against Table 6 (E1 90 mm, E5 65 mm); E4 on the lower JP21 post; R276 fitted and measured
  10.0 ohm +-1 %; EVM plate and clamp fit, clamps clear of TP48/TP49 and the terminal-block wire faces; EVM copper (TP49,
  J1 pin 1) to the plate and chassis > 1 MOhm with W1-W7 disconnected; the EIB on the EVM plate.
- **T-A-05:** add R276 and the clamp material temperature rating; the TSW-1xx-07 orientation of Table 4 (CR-top
  protrusion >= 0.5 mm); delete the sheet line.
- **T-A-06:** placement DRC on the Table 2 outline; the rule-B overlay of every bottom courtyard on the MB layer-1 copper of
  the `.brd` (all nets, +1.0 mm; pass: no bottom courtyard within 1.0 mm of non-GND copper, a non-GND via or an MB part box);
  an L4 solder-mask Gerber check (no opening except W1-W4 and the 22 header rings); the reserved foot keep-out free; the
  y-mirror check by the tab X dry fit (a mirrored CR does not seat); E-lead lengths per Table 6.
- **T-A-06c:** "before the sheet is bonded" reads "before the CR is seated".
- **T-F-12:** chafe inspection of the CR underside and of the MB mask beneath it by mirror or borescope through the 2.54 mm
  gap after the road run; Kapton over a fitted overlay intact; the tab X tap wires clear of the LM1084 body.
- **T-F-16:** the thermocouple is bonded with Kapton (no sheet); limits unchanged.
- **Calculation rows:** H.18 and H.22(k) are re-booked on the strict basis (Table 7); H.22(i) takes Table 6.

### 9.3 New

The IDs below avoid T-A-08, T-C-16 and T-F-18, which `work/eib_merge_failsafe.md` proposes with other content.

- **T-A-09 Pre-capture survey (gate for PM0 and PM1).** M3 over both tab footprints + 0.5 mm, M1 (gate D-2), M2, the MB and
  CR thickness, and the EVM thickness and mass (section 2.6). Pass: no unrecorded item inside a tab outline + 0.5 mm, the
  CR stack top <= the measured Ag105 top height or inside the M2 lid clearance, Table 4 protrusions >= 0.5 mm. Fail: trim
  the tab and re-run `work/minimal_calc/r7_minimal_calc.py`, or lower the W5 fold.
- **T-C-17 E1/C205 ring.** Charger converting at the regen image (ICHG 3.10 A); scope REGN at C205 against E8 on the EIB
  and at TP27 against TP49 on the EVM, with R276 bridged by a temporary link and with R276 in circuit. Pass with R276: the
  ring amplitude at C205 does not exceed the REGN ripple at TP27 (no amplification by the lead).
- **T-F-19 Tab vibration and joint integrity.** Accelerometers on the MB near pin 10 and on the tab X top at (63.0, 62.0)
  during a representative run (M5), spectrum 0.1-8 kHz, transmissibility tab/MB; then a loupe inspection of the 22 header
  joints and W1-W4, and the T-F-12 resistance checks. Pass: no cracked joint and no T-F-12 change. The reserved foot is
  fitted if the transmissibility exceeds 3 at any frequency where the MB excitation is above the logger noise floor
  (proposed criterion, operator to confirm).

## 10. Risks and open items

### 10.1 Risks

1. **Tab resonance is estimated, not measured.** f1 is 1.66-2.35 kHz for tab X and 4.16-5.88 kHz for tab Y on an assumed
   20 GPa laminate and a clamped root, both upper estimates. T-F-19 measures it; the reserved foot is the fallback.
2. **Unrecorded bodges may lie under a tab.** The OPA197 5 V wire, the EN bodge resistors and the encoder reroute are not
   in the `.brd`. T-A-09 gates the outline.
3. **The sheet retirement depends on rule B and on L4 tenting.** One bottom courtyard placed within 1 mm of non-GND MB
   copper, or one untented L4 via, restores the r3 hazard without the barrier. T-A-06 checks both as pass/fail.
4. **The area margin is an estimate.** The routing-overhead model carries about +-50 % on track demand (+-100 mm² on a
   break-even); at the 0.70 budget the rule-B margin is 13 mm². T-A-06 decides; the first fallback deletes the five
   forbidden-part footprints.
5. **Tab X sits beside the LM1084.** The MB rise estimate at tab X is 3.3-17 C at 5 mm (envelope). The tab carries only
   temperature-insensitive features; M4 confirms.
6. **Handling loads grow.** A 10 N push at a tab tip puts 2.7-3.1 N on one pin (1/52-1/46 of the assumed capacity). PM4
   step 3 supports the CR under the tabs while the 22 MB joints are soldered.
7. **The EVM mount is unbuilt.** The plate and clamps depend on M2 and the EVM thickness; the clamp must not bond EVM copper
   to the chassis.
8. **A mirrored fab is scrap.** The tab X collision makes a y-mirrored CR unseatable, which catches the error but costs the
   board; T-A-06 step 0 still catches it before ordering.

### 10.2 Open items

- `TODO(measure)`: M1 (D-2), M2, M3, M4, M5; the MB thickness at the CHG holes; the EVM thickness, outline and mass; the
  RTV bead height on the tab X field.
- `TODO(verify)`: the fab 4-layer 1.6 mm stack-up, L4 tenting and minimum inside-corner radius; the TP48 centre (SLUUCB5E
  Fig 4-1); the TI DCT/DCK package heights; the CR laminate modulus (f1); a fab quote for the r7 outline.
- `TODO(design)`: the EVM plate and corner clamps.
- Operator ruling: the T-F-19 transmissibility criterion; whether a mezzanine EVM mount (section 3.1) should be studied in a
  later round.

## 11. Files

| File | Content |
|---|---|
| `work/minimal_calc/r7_minimal_calc.py`, `r7_minimal_calc_out.txt` | outline, tab copper, booking, pin load, f1, tap lengths, loop separation, E-lead maxima, post arithmetic |
| `work/minimal_calc/r7_footprint_underside.py`, `r7_footprint_underside_out.txt` | footprint underside under rules A and B; MB copper under W1-W4 |
| `work/minimal_calc/r7_handling.py`, `r7_handling_out.txt` | 10 N tip pushes; y-mirror collision check |
| `work/minimal_calc/r7_foot_check.py`, `r7_foot_check_out.txt` | rule-B area and MB copper under the reserved foot square |

Each script runs with `/c/Users/ricky/miniforge3/python.exe -I <script>` from `round4/work/minimal_calc/` (numpy) and
reads `references/Scale Car Board PCB 20260625.brd` through `round4/calc/mb_neighbours.py`.
