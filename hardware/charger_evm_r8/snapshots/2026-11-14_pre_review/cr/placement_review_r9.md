# CR placement review, variant B (r9, D-54)

## 1. Scope and method

This document reviews the live CR placement `cr/cr.kicad_pcb` (variant B of `gen/layout_cr.py`, power-pour stage, no
signal routing) against design document sections A.4, A.7, A.8 and A.9 and against `LAYOUT_DECISIONS.md` D-03 to D-54.
The review is read-only. The board, the netlist and the generator are unchanged.

The measurements come from a scripted pcbnew read of the board (KiCad 9.0, the `tools/pcb/.venv` interpreter), with the
MB geometry from `gen/cr_geometry.py` and `gen/mb_brd.py`. Every coordinate is in the MB frame (KiCad Y = 100 - y). A
distance named "centre to centre" is between pad centres; every other distance is edge to edge. The review scripts are
outside the repository and are not part of the design record.

Severity uses three levels:

- **Blocker:** the placement cannot be routed to a working board, or it breaks a binding A.8 electrical rule.
- **Major:** a binding rule or a fabrication or assembly requirement fails, but a local fix exists.
- **Minor:** a preference, a margin or a process item.

## 2. Findings

### 2.1 Blocker

**B-1. The +x pocket is empty, and the U101 programming and monitor parts are packed across the CHG pin column.**
A.8 places R101, C101, R103, R104 and R105 in the +x pocket (x 44.3-48.2, y 63.40-66.64, top only) and keeps the
ILIM, dVdT, OVP and IMON nodes within 5 mm of U101 pins 7-13. A.8 (r9-3) also places R106s as near to U101 pin 14 as the
courtyard check allows. No part lies in the pocket. Table 1 gives the placed positions.

Table 1. U101 network parts on the live board (centre-to-centre distance from the part pad to the U101 pin it serves).

| Part | Net at the pad | Placed centre | Side of the CHG column | Distance to the U101 pin | A.8 limit |
|---|---|---|---|---|---|
| R101 | N_ILIM | (45.334, 67.950) | over the column top | 4.14 mm to pin 10 | <= 5 mm |
| C101 | N_DVDT | (42.234, 67.550) | west, over pins 13-16 | 4.70 mm to pin 9 | <= 5 mm |
| R103 | N_OV / N_UV | (48.084, 60.950) | east | 4.47 mm to pin 7; 5.37 mm to pin 6 | <= 5 mm |
| R104 | N_OV | (49.684, 62.400) | east | 6.08 mm to pin 7 | <= 5 mm |
| R105 | N_IMON | (48.834, 51.050) | east | 15.42 mm to pin 13 | <= 5 mm |
| R129 | N_IMON | (48.084, 44.300) | east | 22.73 mm to pin 13 | IMON node <= 5 mm |
| R106s | N_FLT | (48.084, 47.400) | east | 19.85 mm to pin 14 | as near to pin 14 as possible |

The root cause is in `gen/layout_cr.py`. `INTERIOR` subtracts `POCKET.buffer(0.5)`, and no region and no phase owns the
pocket. `region_name()` therefore returns `int_logic` for the pocket parts, and the packer places them by connectivity
outside the pocket. The module docstring states the intent ("packed toward U101 pins 7-13 by connectivity"), but the
region table prevents it.

The consequences are as follows:

- Six ratsnest connections cross the CHG pin column (x 45.998, y 38.1-62.9): N_UV, N_OV, N_IMON, N_FLT, J3V3_2 and
  3V3. Five of them come from Table 1. The column gaps are 0.64 mm on L1, so each gap passes one track.
- N_UV and N_OV must cross at pads 9-10, where the VCHGIN L1 pour (to x 47.05) and the VCHGIN L3 strap (to x 47.10,
  y 60.15-62.75) occupy both signal layers. This explains the `/N_OV` (U101.7) connection that stays open at every
  probe seed (D-54 open item 5).
- The IMON node (U101 pin 13 to R105 and R129) runs about 23 mm across the board, against the 5 mm rule.
- R105 overlaps the MB 5V copper rim in plan (0.00 mm) and lies 0.64 mm from the REG-5V box.

Recommended fix (generator change, no netlist change):

1. Add a pocket region on the plug-on outline. The A.8 upper bound y 66.64 was the r6 +y edge, and D-09 records that
   the new +y edge (y 94) makes the A.8 targets reachable again. A start value is x 44.40-50.50, y 63.40-69.00. Keep
   every courtyard >= 0.5 mm from the J1 pad-10 annulus (pad top y 62.894).
2. Add a north strip over the U101 +y edge for the pin 13/14 parts. A start value is x 39.20-44.40, y 66.90-70.00,
   clear of the VCHGOUT L1 pour (x <= 41.15, y <= 66.64).
3. Assign R101, C101, R103 and R104 to the pocket, and R105, R129 and R106s to the north strip. Pack them in their own
   phase directly after J-TAP, with the U101 pin of each part as its target.
4. Add check rows to `gen/check_constraints.py`: pad-to-pin distance <= 5 mm for the pocket nodes (A.8), the R106s
   distance to pin 14 (A.8 r9-3), and a count of ratsnest crossings of the CHG column.

With R129 next to U101, the CHG_IIN line runs from R129 to C129 at J102 pad 2. This keeps the IMON node short and makes
the R129 part of D-54 open item 1 moot. R103 and R104 then stay about 8.6 mm from the MB 5V rim, so they need a listed
D-20 exemption like R102 (finding m-2).

### 2.2 Major

**M-1. The U101 exposed-pad stencil apertures overlap all nine thermal-via drills.** A.8 (U101 thermal pad, r9-3)
requires a window-pane aperture that keeps paste off the via barrels. The footprint has four 1.17 x 1.17 mm apertures
centred at (41.025 / 42.375, 62.975 / 64.325). The nine 0.3 mm vias sit on a 1.1 mm grid at x 40.6 / 41.7 / 42.8 and
y 62.55 / 63.65 / 64.75. Every drill overlaps an aperture; the gap between the apertures is 0.18 mm, less than the
0.3 mm drill. Paste can therefore flow into every barrel and starve the exposed-pad joint.
Fix: redraw the paste layer of the U101 footprint in `gen/fplib.py`. One option keeps the 3 x 3 via grid and places
four 0.50 x 0.50 mm apertures at the cell centres (+/-0.55 mm from the pad centre); each aperture then clears each drill
by 0.15 mm, at about 14 % paste coverage. A coverage target above that needs a different via pattern. The coverage
target is TODO(verify: SLVSE94G section 11, stencil vendor).

**M-2. Two VCHGIN pre-vias overlap the C102b pad and its mask opening (D-37).** The vias at (40.35, 51.62) and
(40.95, 51.62) (`gen/route_cr.py` `PRE_VIAS`) overlap the C102b pad-1 copper by 0.13 mm. The cause is the D-09 shift of
C102b from y 53.65 to 53.14, which moved the pad onto the vias. `check_constraints.py` reports 0 vias in SMD pads,
because it tests only the via centre (`HitTest`), not the via annulus against the pad and its mask opening.
Fix: re-site the two vias clear of the pad by at least the mask expansion, for example one via at (39.45, 51.80) beside
the existing x 39.45 column. Then re-count the C102b-end vias against the A.8 IN-strip row ("6 vias each end") and
D-21 ("five vias at C102b"). Change the D-37 check to intersect the via annulus with the pad plus its mask expansion.

**M-3. The L1 VCHGIN pour does not reach J1 pad 10.** The DRC reports a starved thermal at J1.10: its two spokes reach
an isolated island of zone `VCHGIN_L1`. The neck between the C102c GND pad (top edge y 60.745) and U101 pins 6/7 is
narrower than the 0.2 mm zone clearance allows. The pad-10 current (<= 2.41 A, A.8) therefore flows only through the
L3 strap on 0.5 oz copper, and the IPC-2152 inner-layer check of D-29 stays open.
Fix (design-owner choice): either accept the L3 strap as the only pad-10 path, close the IPC-2152 check and remove the
L1 island at pad 10, or re-shape the L1 pour so that it reaches pad 10 with at least two spokes. D-21 already notes
that the N_UV escape must cross the L1 corridor, so the first option matches the D-21 intent.

**M-4. `gen/make_board.sh` copies the shared OSH Park/PCBWay rule file.** The amended D-29 and
`decisions_2026-11-12/stackup_fabrules_decisions_2026-11-12.md` section 3 require an OSH Park-only CR rule file. The
live `cr/cr.kicad_dru` is that file, identical to `cr/variants_r9/B/cr.kicad_dru`, but it was copied by hand. A full
`make_board.sh cr` run copies `fab_4layer_5mil_oshpark_pcbway.kicad_dru` and reverts it. In addition, the board Default
net class is 0.127 / 0.127 mm, whereas the amended D-29 sets the router default to 0.1524 / 0.1524 mm.
Fix: add the OSH Park-only file under `tools/pcb/fab_rules/`, point `make_board.sh` at it, and set the Default net class
to 0.1524 / 0.1524 mm in the CR board setup (D-54 open item for the rule file).

### 2.3 Minor

**m-1. W1/W2 courtyards overlap, and the pads are 0.307 mm apart.** W1 (VCHGOUT) and W2 (GND) keep the A.8 r5
coordinates at 2.6 mm pitch with 2.3 mm pads. The DRC counts the overlap twice. A hand-solder bridge shorts the eFuse
output to GND. D-08 and D-45 call for the W positions to be re-derived on the new outline.
Fix: move W2 to x 27.20 (pad gap 0.81 mm; W2 courtyard 0.85 mm from W6) and move the `GND_L1_star_1` zone with it.

**m-2. R103 and R104 (0.1 % eFuse UV/OV divider) are not covered by the D-20 rows.** They lie 5.25 mm and 6.13 mm from
the MB 5V copper rim, below the 10 mm window rule, and `check_constraints.py` lists only R102 as an exemption. After the
B-1 fix they stay below 10 mm. Fix: add R103 and R104 to the D-20 rows as listed exemptions, with the same reason as
R102 (U101's own network under the A.8 <= 5 mm rule).

**m-3. The W3 pad (VCHG, 18 AWG hand-solder joint) is 0.781 mm from R110 pad 1 (N_H1P).** R110 is the 0.1 % bottom of
the H1 IN+ divider, the only hardware check of the gate. The courtyard meets the 0.5 mm W3 exclusion of the divider
strip, but the iron and the flux of a large joint act on a 0603 part 0.78 mm away.
Fix: shift the six dividers +0.7 mm in x; the strip has 0.90 mm of slack at its +x end (R114 courtyard to x 35.60,
strip to x 36.50). The pad gap then becomes about 1.48 mm.

**m-4. R177 sits east of the CHG column.** R177 (J101 pin 2 to the CR 3V3) lies at (50.434, 49.450), on the REG-5V box
edge (0.00 mm). Its two nets, J3V3_2 and 3V3, both cross the column. R107 (STAT pull-up) also takes its 3V3 across the
column. Fix: place R177 west of the column near J101 pin 2 (for example in the ribbon-resistor row under J101), and
place R107 beside J101 pin 4 (STAT). With B-1, the column crossings then fall from six to none.

**m-5. C102b and J101 courtyards overlap by 0.04 mm.** Fix: C102b y 53.14 to 53.19, inside the D-09 allowance. The
C102b-C102a courtyard gap falls from 0.11 to 0.06 mm. Apply this together with M-2.

**m-6. The U101 footprint carries a B.Cu copy of pad 25** (the single D-44 FAIL). The pad is copper only, with no mask
opening and no paste, and the L4 GND pour already joins the nine vias. Fix: remove the B.Cu pad from the footprint in
`gen/fplib.py`. Pad 25 stays on F.Cu, so the netlist does not change.

**m-7. Silkscreen.** The DRC reports 75 silk-over-copper, 47 silk-overlap and 2 silk-to-edge items (the J1 "11" mark at
x 19.10). Fix: run `gen/silk_fix.py` before the fab package and move the J1 "11" mark inside the outline.

**m-8. The divider-top nets cross the logic box.** T1_VMOT and T2C run from J102 pads 7 and 1 (x 48.6-51.6,
y 20-23) to the divider strip (x 26-34, y 43). The straight lines cross the gate ICs and the comparator row. No logic
pad lies within 3.2 mm (centre to centre) of a divider-top pad, so the placement metric is 0. The route still decides
the A.8 2 mm rule. Fix: give the route-race a guide corridor for T1_VMOT and T2C along the free south edge
(y < 19) and the -x side, clear of the logic box.

**m-9. `plane_vias.py` places a GND via inside U101.25 at every probe seed** (D-54 open item 6). Fix: add the U101
exposed pad, grown by the mask expansion, as a keep-out for the plane-via step.

### 2.4 Items checked with no finding

- **CHG header J1:** the 22 pins match the A.8 table and the `.brd` CHG package to 0.0000 mm; J1 is on F.Cu; the
  pad-to-edge distance is 1.464 mm; the TSW-112 body courtyard has 0.394 mm of inset margin.
- **Outline and side:** the D-39 rectangle; 78 parts inside it; no part flipped; every footprint on the 0.25 mm basis.
- **Fixed coordinates:** J1, W1-W4, U101, C102a, C102b, C102c, R102, D107, C103, D103 and J101 sit at their A.8 / D-09
  values. U101 has pins 1-6 facing -y; the VCHGIN pad of C102a, the N_UV pad of R102, the D107 cathode and the
  VCHGOUT pad of C103 face +y; the D103 cathode is at +x. The IN- and OUT-strip distances are 0.53, 2.09, 2.43 and
  1.52 mm, all <= 3 mm.
- **J102 (J-TAP):** courtyard x 45.86-55.12, y 16.18-35.82, inside the +x half. Pad 1 (T2C, roundrect) is at
  (48.579, 20.000). Pads 1-5 (row A) lie on x 48.579 and pads 6-10 (row B) on x 51.579, with column 1 at -y; the
  pad nets match the D-46 r9-13 map and the D-53 pin assignment. In the stock footprint the latch lies on the row-B
  side at column 3, which faces +x. The plan area x 55.1-67.0, y 22.3-36.0 is free for finger access; R175 is the only
  part on that side, at y 17.7-22.3. Which Molex row is row A, relative to the latch and to the 43025 cavity numbers,
  stays TODO(verify: Molex 43045 header and 43025 housing drawings). A mirrored reading would exchange columns 1 and 5
  in each row.
- **J101:** pin 1 is at the +y end of the -x column (D-10).
- **THT tails:** no J102, W1-W4, W6 or W7 tail lies within the L-FC, L-BT or REG-5V box + 1 mm (A.7). The J102 row-B
  tails stand over the SNS-BT box; D-51 takes the air gap as met.
- **W6/W7:** plated through-hole placeholders (D-45). W6 lies beside J1 pin 13 (THERM), W7 beside pins 7/8 (SCL/SDA).
- **Clearance and creepage:** the smallest F.Cu pad gap from a VCHGIN, VCHGOUT or VCHG pad to another net is 0.154 mm
  (inside the U101 land pattern), then 0.307 mm (W1-W2, m-1) and 0.547 mm (C102c-U101.3). IPC-2221B Table 6-1 B2
  (external, uncoated) asks 0.1 mm up to 30 V; the C102b-C102a gap of 0.600 mm meets the 0.6 mm figure for 31-50 V
  (transient at the D107 clamp). The power pours keep 0.2 mm.
- **D-20 window:** 13 of 13 comparators, clamps and dividers inside the strict window; they keep >= 8.37 mm from the
  boost L/REG/VSW boxes, >= 11.57 mm from SNS-BT and >= 15.99 mm from the U101 courtyard. The divider-top metric is 0.
- **Stack-up:** L4 carries the GND pour and the no-track rule area and has no track; the VCHGOUT strap is on L3.
- **D-51:** the -x edge clears the J-BL, J-FC and J-BT bodies by 2.454, 2.454 and 2.200 mm.
- **Density:** the top courtyard booking is 22.4 %. Most neighbouring courtyards are 0.16 mm apart; the divider strip
  is at 0.06 mm (the D-15 deviation of step 5), which leaves about 0.56 mm between pads, one 6/6 mil track.

## 3. Netlist

No finding needs a netlist change. B-1, m-4 and the other fixes change the generator, the footprint library or the
pre-via list only.
