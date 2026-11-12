# Item 4.7: CR routability on the new outline

## 1. What was run and what is estimated

**Run (scratch only, nothing in the repo was changed):**

1. `measure.py` on `cr/interactive/cr.kicad_pcb` (the r2_A seed 1 board). It reports 156 parts (78 top, 78 bottom), 680.9 mmÂ² of top courtyard and 235.8 mmÂ² of bottom courtyard. It also reports 91 signal nets with 199 connections, a signal MST of 1639 mm and an HPWL of 1873 mm. The routed copper is 2045 mm (F 354, In2 1230, B 461) with 256 vias.
2. `obst.py` on `cr/cr.kicad_pcb` (placed board with pours). The 411 SMD pads take 580 mmÂ² including the 0.127 mm clearance, and the 35 PTH pads take 109 mmÂ². The power pours are F VCHGIN 36.3, VCHGOUT 56.3 and VCHG 23.6 mmÂ², In2 VCHGIN 45.6 mmÂ² and B VCHGOUT 19.6 mmÂ².
3. `pack_new.py`, a greedy repack in the connectivity order of the 153 placeable parts. It puts every part on the **top** side inside the new outline (0.5 mm inset) and uses the feasibility test of `gen/packer.py`. J1 stays on the fixed CHG holes. Assumed keep-outs: two 3.2 mm receptacle columns, and four 6 mm standoff discs at the CHG corners.

   | Routing channel per courtyard | Placed | Signal MST | HPWL |
   |---|---|---|---|
   | 0.3 mm | 153/153 | 1253 mm | 1304 mm |
   | 0.6 mm | 153/153 | 1549 mm | 1645 mm |
   | â‰¥ 1.0 mm | â€” | â€” | â€” |

   At 1.0 mm and above the greedy packer fragments the free area and leaves parts unplaced. This is a weakness of the greedy order, not a capacity limit: the courtyards book only 26.1 % of 3823 mmÂ².

   Scripts and outputs are in `C:\Users\ricky\AppData\Local\Temp\claude\3fe373bc8dcb48b3\88ddad5f-e7e9-4a73-b399-a08cdcf77486\scratchpad\outline\routing\`. The placements are in `placed_ch*.json`. No plot was made because the venv has no matplotlib.

**Not run:**

- `layout_cr.py`, `route_cr.py` and PathFinder on the new outline (reason in section 2).
- Section 4 is an **analytic estimate**, not a routed result.

## 2. The generator cannot be pointed at the new outline in the time box

- **Frame.** `layout_cr.py` already works in the MB (Eagle, A.8) frame, with `YOFF = 100.0` for the KiCad y flip (`gen/layout_cr.py:18`). J1 pin 1 is at (45.998, 39.084) (`:30`). The new rectangle needs no transform.
- **Outline.** `OUTLINE` (`:22-23`) is a one-line change. Everything else in the file encodes r7 geometry:
  - the regions `FP_RECT`, `BAND`, `DIV_STRIP`, `TAB_X`, `TAB_Y`, `FT1_KO`, `FT2_KO`, `SPOTS` and `B1R` (`:75-110`);
  - `RIM_X` and `LFC_Y` (`:167-168`);
  - the bottom-clearance rule areas from `r7_calc.py` (`mbk()`, `:121-150`);
  - the phase list, which assumes a bottom side (`:225-262`);
  - the tap-grid and comparator coordinates in `FIXED` (`:29-58`).
- **Board side.** The side comes from the `side="B"` fields in `netlist.py` (for example `:95, :103-117`), applied in `pcbbuild.py:195`.
- **Power copper.** The power geometry is hard-coded in `route_cr.py`: `VIN_L3` (`:19`), `VOUT_IN` (`:22`), `PRE_VIAS` (`:24`), `VIN_L1` (`:50`) and `VOUT_L1` (`:53`).
- **Effort.** A faithful run needs a new region table, side flags and a power-copper re-derivation. That is a design task, not a 40-minute run.

## 3. Findings

1. **Area.** The inset area is 47.416 x 86 = 4078 mmÂ². After the assumed J1 and standoff keep-outs, 3823 mmÂ² remain. All courtyards together take 917 mmÂ² (680.9 top + 235.8 bottom), which is 24 % of the free area on one side. Under r7 the bookings were top 73.55 % and bottom 69.04 % (design doc 0.3 row r7-5, `docs/charger_bq25798_wiring_design_2026-11-05.md:340`). **All SMT parts fit on the top side** with margin for 0402 â†’ 0603 upsizing and for the new lead connectors (CR Â§5.1 Table 3).
2. **Wire length.** At a 0.6 mm channel the top-only repack gives a signal MST 5.5 % below the current two-sided placement (1549 against 1639 mm). The greedy repack ignores the regional rules (analog window, thermal band, U101 loop), so the real figure will be higher. The capacity margin in section 4 covers a doubling.
3. **r7 bottlenecks.** The failure clusters of ROUTABILITY_OPTIONS Â§1 (`ROUTABILITY_OPTIONS_2026-11-12.md:23-28`) are r7 geometry:
   - the comparator band was squeezed between the low edge and J1;
   - the tab Y root;
   - the U101 +x pocket, with R104 forced to the bottom (D-32, `LAYOUT_DECISIONS.md:142`);
   - the x 38-40 column, blocked by `VIN_L3` and `VIN_L1` (`footprint_options.md:13`).

   None of these needs to recur on an 87 mm tall board.
4. **Standoff corners.** The CHG footprint silkscreen spans x 17.134-49.262, y 32.780-67.708. This was extracted with `mb_part_extents.py` from `Scale Car Board PCB 20260625.brd`, layer 21. The two -x corners lie 1.45 mm **outside** the new -x edge (18.584), so the -x standoffs cannot sit at the literal footprint corners and stay under the CR. Positions: TODO(measure: operator).
5. **Switching nodes.** The new outline covers the following MB parts (same extraction):
   - L-BT, x 20.2-35.5, y 8.1-20.8;
   - REG-BT, x 44.2-46.8, y 17.9-22.1;
   - L-FC, x 21.0-36.3, y 76.9-89.7;
   - REG-FC, x 42.9-45.5, y 83.5-87.7;
   - REG-5V, x 51.5-61.8, y 36.8-52.4.

   The band y â‰ˆ 30.8-66.9 lies â‰¥ 10 mm from both inductor bodies. It is the same band as the J1 span (y 36.5-64.5).
6. **Via-in-pad conflict.** `LAYOUT_DECISIONS.md:337-345` (D-37) already orders the two rulings: VR-1 first, plain via-in-pad (D-36) only as a listed fallback. This agrees with CR Â§5.6, so for routing no open conflict remains. It matters at one place: the U101 EP carries 9 footprint thermal vias of 0.30 mm (`LAYOUT_DECISIONS.md:75`; A.8 requires â‰¥ 9). These are vias in an SMD pad under stencil reflow. VR-1 needs an explicit exemption for them, and the stencil needs a window-pane EP aperture, TODO(verify: TPS2663 datasheet land/stencil recommendation).

## 4. Capacity estimate (analytic)

The estimate uses the following basis:

- track pitch 0.254 mm (5/5 mil, D-29);
- 0.6/0.3 mm vias, each blocking a 0.854 mm disc = 0.573 mmÂ² on every layer (`footprint_options.md:15`);
- full-completion demand on r7 extrapolated as 2045 mm x 199/173 â‰ˆ 2350 mm (ESTIMATE);
- new demand = 2350 x 1549/1639 â‰ˆ 2220 mm = 564 mmÂ² of track;
- via count held at 256.

| Case | Free area of the signal layers (mmÂ²) | Demand (mmÂ²) | Utilisation |
|---|---|---|---|
| r7 today, F/In2/B (measured 667/1154/909, `footprint_options.md:7`) | 2730 | 597 + 3 x 147 = 1038 | **38 %** (did not close: 162-182 of 199) |
| New, 3 signal layers (F â‰ˆ 3000, In2 â‰ˆ 3670, B â‰ˆ 3690) | 10 360 | 564 + 441 = 1005 | **9.7 %** |
| New, 2 signal layers (B.Cu a solid MB-facing GND, item 4.5) | 6670 | 564 + 294 = 858 | **12.9 %** |

The new F.Cu figure equals 3823 less all SMD pads (580), PTH pads (109) and power pours (â‰ˆ 136).

**Verdict.** The 4-layer stack with 0.6/0.3 mm vias and **no via in pad** should close. Geometric utilisation falls by a factor of 2.9 to 3.9 against the board that failed. This holds even with L4 given over to a solid GND shield above VSW-FC/VSW-BT, which leaves F.Cu and In2.Cu as the only signal layers.

The GND-connection shortfall also disappears:

- Under VR-1, 34 of 56 GND fill pieces had no via site on r7 (`MORNING_REVIEW_2026-11-12.md:95`).
- On a top-only board with In1 and L4 both GND, each GND pad gets a fan-out via beside it. The 0603 pads leave room for one.

Confidence is moderate to high, but this is **not verified by a routed run**. A route-race on the regenerated placement is the gate (item 4.7). The narrowest remaining cut is the J1 pin gap. Two tracks fit between 1.9 mm pads at 2.54 mm pitch (`ROUTABILITY_OPTIONS_2026-11-12.md:47`), and the inner gap is about 0.93 mm (D-30, `LAYOUT_DECISIONS.md:208`). The -x column (pad edge x 20.048) has about 0.96 mm to the 0.5 mm inset, so all its nets escape toward +x.

## 5. Proposed placement structure (MB frame)

1. **Power block, unchanged.** Keep the eFuse cluster (U101, C102a/b/c, R102, D103, D107, C103) on its A.8 coordinates beside the +x column, pins 10 and 14-19 (D-09, D-21, D-22). Keep the `route_cr.py` power copper. This keeps the validated C102b â‰¤ 2 nH loop. Put the +x pocket (R101-R105) on the **top** at x 44-50, y 62-67, which now lies inside the outline. D-32 retires.
2. **Analog block.** Put the comparators, the 0.1 % dividers and the references between the J1 columns, at x 22.6-39.5 and y 31-67. This window keeps `RIM_X` 39.53 (the A.7 thermal band against the 5 V copper, `layout_cr.py:167`). It also keeps â‰¥ 10 mm from L-BT (y â‰¤ 20.8) and from L-FC (y â‰¥ 76.9).
3. **Logic block.** Put the LVC gates, the one-shots and their decouplers in the +x strip, x 48-66 and y 22-75. They may sit over REG-5V, because logic tolerates the heat. Put the overflow in the +y band y 68-76.
4. **Edge bands, connectors only.** Use the end bands over the boost switching nodes for low-sensitivity content: the tap and W-lead connectors (item 4.3), J101 and the TVS parts. The bands are y 7-22 over L-BT/REG-BT and y 77-94 over L-FC/REG-FC. The EVM reference placement is past the MB +y edge (design doc `:435`), so the lead connectors go on the **+y edge**. Each W lead must still meet the H.23(l) 10 mm switched-conductor rule over L-FC, TODO(verify: H.23(l) re-check with the new CR height).
5. **Stack-up.** Use L1 for parts, signals and power pours, In1 as solid GND, In2 for signals and the VCHGIN strap, and L4 as a solid GND facing the MB. Allow L4 signal only in the middle band if a scripted run needs it.

## 6. Rows that change

- **LAYOUT_DECISIONS.md**
  - D-15 (`:177`): the packer regions and phases are rebuilt for one side.
  - D-17 (`:188`): the bottom-clearance rule areas retire.
  - D-20 (`:217`): L4 becomes the MB-facing GND shield, and the via tenting is re-assessed.
  - D-31 (`:98`): F22-F24 and the tap pads are replaced by a connector.
  - D-32 (`:142`): retires.
  - D-34 (`:279`): the bottom strap keep-out is moot.
  - D-37 (`:337`): add the U101 EP thermal-via exemption.
  - Â§5.2-5.4: rewritten.
  - D-09, D-21, D-22 and D-33: keep.
- **Design doc**
  - A.7 (`:769`): outline and mounting.
  - A.8 (`:1196`): the region table, the tab X/Y rows, the bottom-side rows, the feet and the stack-up.
  - 0.3 rows r7-1 (`:336`) and r7-5 (`:340`): booking.
  - H.23(e2) and H.23(l).

## 7. Operator questions

1. What are the standoff positions and diameter? The -x CHG corners lie outside the outline (finding 4). TODO(measure: operator)
2. Which receptacle (THT or SMT), and what is its body width per column? The 3.2 mm keep-out used here is an assumption.
3. Do the tap and W-lead connectors go on the +y edge, toward the EVM reference placement?
4. Is L4 approved as a solid GND layer facing the MB?
5. Is the U101 EP thermal-via exemption from VR-1 approved, together with the 0.5 mm VQFN pitch (CR Â§5.5)?

