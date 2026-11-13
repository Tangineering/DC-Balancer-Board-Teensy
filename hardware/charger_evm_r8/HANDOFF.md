# Charger EVM r8 capture: handoff (2026-11-11, updated 2026-11-13)

**Status (2026-11-13, current, D-62: CR routed, trimmed to the D-62 outline, stitched and straightened; both fab
packages exported, not ordered; one VCHGOUT item open for the operator).** D-62 (operator ruling 2026-11-13 to the
routing session, route-race change request R9-04: "Keep the trim rectilinear, or with 30, 45, or 60deg angles.
Fillets on corners is good though.") redoes the D-60 trim. Every outline edge runs at 0, 30, 45, 60, 90, 120, 135 or
150 degrees (`TRIM_ANGLES` in `gen/cr_geometry.py`), every slanted edge is at least 2.0 mm long (`TRIM_MIN_EDGE`), and
every corner carries a 1.0 mm fillet drawn as an Edge.Cuts arc (`FILLET`). `FINAL_OUTLINE` has 10 corners before the
fillets: (58.600, 71.043), (55.835, 72.640), (25.266, 72.640), (22.564, 71.079), (18.584, 67.100), (18.584, 28.193),
(21.845, 22.545), (47.332, 7.830), (56.928, 7.830) and (58.600, 10.726), MB frame. The filleted area is 2327.7 mm²
(55 % of the D-39 rectangle); the bounding box stays 40.02 x 64.81 mm, MB frame x 18.584-58.60, y 7.83-72.64, and the
-x vertices sit exactly on x 18.584. The holes are MH1 (26.23, 69.04), MH2 (54.85, 68.79), MH3 (54.85, 11.43) and
MH4 (24.48, 25.18); only MH2 moves. A CR rotated 180 degrees lands on J-BL (7.73 mm of x overlap) and J-FC (7.73 mm),
so the D-41 key holds. `gen/trim_cr.py` passes `--angles`, `--min-edge` and `--fillet` and reproduces the outline from
the routed board `621fb28`; `gen/silk_refs.py` and `gen/check_constraints.py` read the filleted outline with
`GetBoardPolygonOutlines`. The corner fillet at (58.6, 71.04) clips 0.027 mm² off the D-60 key-ear box, so the ear row
is checked against the corners before the fillets, and the D-41 key row is the functional check.

The routing session re-ran the D-61 finish order on the trimmed board: `plane_vias.py --stitch 2.5` placed 279 grid
stitching vias, `straighten.py` reduced the track segments from 1791 to 769 and the track length from 830.8 to
824.5 mm, and `stitch_gaps.py` added /GND vias at (36.04, 26.88), (34.29, 33.53) and (33.54, 59.53). The board has
288 /GND vias: 279 grid stitching vias, 3 gap-fill vias, and the pre-vias and plane vias. Then `gen/silk_refs.py`
placed 60 references on F.Silkscreen (27 of them over another courtyard) and 18 on F.Fab only (C107, C115, C130, C132,
D105, D106, R122, R130, R131B, R147, R184-R189, U110, W3; C110 is back on the silkscreen), and `gen/sync_fields.py`
wrote the J102 part number 43045-1012 and the cable 2147561101. On this board, ERC reports 0 messages, DRC
(`--severity-all --schematic-parity`) reports 0 violations, 0 unconnected items and 0 parity issues, and the constraint
check gives 109 pass rows, 0 FAIL and 3 exemption rows. The D-20 stitching row passes: with 306 stitch points, the
largest distance over the filled L4 pour is 3.51 mm at (43.0, 44.8), against 3.54 mm. The CR fab package
`fab/cr_2026-11-13/` and the figures `figures/cr_routed_2026-11-13/` were re-exported from this board in `89c2d72`; the
size row of the package README describes the D-62 outline, and its OSH Park row states the confirmed stack-up and that
OSH Park sells boards in multiples of 3 (the quantity stays "5 (E BOM)" until the operator rules). Reversal: restore
`cr/cr.kicad_pcb` and the `gen/cr_geometry.py` outline and hole data of the D-61 board (`437d2d7`, lineage `b8e3762`)
and run `gen/export.sh` and `gen/fab_readme.py` again. `LAYOUT_DECISIONS.md` D-62 is the record.

The VCHGOUT current check R9.H26 (`docs/reviews/charger_eval_2026-11-05/round4/calc/r9_calc.py`, output
`r9_calc_out.txt`) is new and open; section 3a item 8 gives it. Two short F.Cu-only necks on the VCHGOUT path from
U101 OUT to W1 (U101 OUT pins to C103, x 39.25-41.00; C103 ground pad and D-56 /GND via notch, x 37.50-38.75) fail the
IPC-2152 long-conductor basis at 3.21 A, and the operator chooses between acceptance, wider copper and a bench
measurement. **The next action is operator check-in 4: the pre-order review of the routed CR and the two packages,
with the VCHGOUT ruling** (section 3a).

**Status (2026-11-13, Review 2/2: the operator-review order blockers are disposed of).** Operator ruling 2026-11-13 (Review
2/2: BAV199, strap, OSH Park (fab checks), local_6e36c3a4-f328-44cd-8c31-05ea2fa7bfa3, chat 2026-11-13) closes
`LAYOUT_DECISIONS.md` section 11 items 2, 5, 9 and 10 and the OSH Park solder-mask expansion, and closes item 7 (the
quote) as outside the scope of the project. Item 2 is closed for the VCHGIN strap only; its VCHGOUT half stays open
(section 3a item 8). Item 3 stays an assumption that is checked when the board is submitted.
Section 3a gives the record and the questions that the operator has not answered. (**Superseded 2026-11-13, D-62:**
the heading "no operator-review order blocker remains"; "A further outline trim, D-62 ... is committed in `89c2d72`
...; its design record is pending, and the D-61 figures below are superseded by it"; see the current status above.)
(**Superseded 2026-11-13:** "two open questions"; "is in progress and not committed. The status below describes the
committed D-61 board.")

**Status (2026-11-13, D-61: CR routed, trimmed, stitched and straightened; both fab packages exported, not
ordered).** (**Superseded 2026-11-13, D-62:** "current" in this heading; every value of this status is the D-61
board's, see the current status above.) D-61 sets the finish order of the routed CR: route, plane vias, `gen/trim_cr.py`, /GND stitching vias on a
2.5 mm grid inside the trimmed GND fill (`tools/pcb/corridor_route/plane_vias.py --stitch 2.5`), the straightening pass
(`straighten.py`), the stitching gap fill (`tools/pcb/corridor_route/stitch_gaps.py`), then `gen/silk_refs.py`
(operator requests 2026-11-13, relayed by the routing session). The D-60 outline (18 vertices, 2241.6 mm²) and the
holes MH1 (26.23, 69.04), MH2 (54.85, 63.79), MH3 (54.85, 11.43) and MH4 (24.48, 25.18) do not change. The D-58 to D-60
board had only 6 /GND vias, because the `ROUTE_SKIP_FR=1` build skips `route.py stitch()`. The D-20 rule (L4 stitched
to L2 at a pitch of at most 5 mm) was therefore not met, and no check measured it.

The D-61 board has 278 /GND vias: 269 grid stitching vias, 3 gap-fill vias, and the pre-vias and plane vias. The grid
stitching left a 4.08 mm gap at (36.0, 26.7); the gap fill added /GND vias at (36.04, 26.87), (34.34, 33.62) and
(34.04, 59.52) (`cr/stitch_gaps.md`; routing request R9-03, closed). The gap-fill report samples the pour at 0.50 mm
and gives 4.09 mm before and 3.43 mm after; the constraint-check row (4.08 mm, 3.47 mm) is the measure of record. A new
constraint-check row measures D-20: with 296 stitch points (/GND vias and /GND plated holes), the largest distance over
the filled L4 pour is 3.47 mm at (31.0, 34.7), against 3.54 mm for a 5 mm square pitch, and the row passes.
Straightening reduces the track segments from 1791 to 768 and the track length from 830.8 to 823.9 mm; vias, pads and
locked pre-tracks do not move. The references do not change (59 on F.Silkscreen, 19 on F.Fab only).

On this board, ERC reports 0 messages, DRC (`--severity-all --schematic-parity`) reports 0 violations, 0 unconnected
items and 0 parity issues, and the constraint check gives 109 pass rows, 0 FAIL and 3 exemption rows. The CR fab
package `fab/cr_2026-11-13/` and the figures `figures/cr_routed_2026-11-13/` were re-exported from this board in
`437d2d7`; the EIB fab package is `fab/eib_2026-11-13/`; neither is ordered. The D-20 stitching does not block the
order. The intermediate board `8521bf8` (stitching before the trim, 19-vertex outline of 2248.3 mm²) is superseded, and
its values are not current. **The next action is operator check-in 4: the pre-order review of the routed CR and the
two packages** (section 3a lists the items that block the order).

**Status (2026-11-13, D-60: CR routed and trimmed, both fab packages exported, not ordered).** D-60 trims the
routed CR to a convex 18-vertex outline inside the D-39 rectangle: 2241.6 mm² (was 4212.2 mm², 53 %), bounding box
40.02 x 64.81 mm, MB frame x 18.58-58.60, y 7.83-72.64. The outline keeps a +x key ear for the D-41 key. D-60 also
adds four NPTH 3.70 mm holes (6-32 free fit): MH1 (26.23, 69.04), MH2 (54.85, 63.79), MH3 (54.85, 11.43) and MH4
(24.48, 25.18). Each hole has an all-layer copper keep-out of radius 4.0 mm. The holes hold a 3D-printed support. The
D-39 rectangle stays the placement frame, and no part, track or via moved. After the trim, `gen/silk_refs.py`
re-placed the references, and 19 references are on F.Fab only. On the trimmed board, ERC reports 0 messages, DRC
(`--severity-all --schematic-parity`) reports 0 violations, 0 unconnected items and 0 parity issues, and the
constraint check gives 108 pass rows and 0 FAIL, with 3 exemption rows (R102 under D-20; R103 and R129 as listed
U101-network exemptions, D-55 and D-56). The CR fab package `fab/cr_2026-11-13/` was re-exported from the trimmed
board (`779c419`); the EIB fab package is `fab/eib_2026-11-13/`; neither is ordered. **The next action is operator
check-in 4: the pre-order review of the routed CR and the two packages** (section 3a lists the items that block the
order). (**Superseded 2026-11-13, D-61:** "current: CR routed and trimmed" in the heading; "the constraint check
gives 108 pass rows and 0 FAIL" (the D-60 board had no D-20 stitching row and 6 /GND vias); "The CR fab package
`fab/cr_2026-11-13/` was re-exported from the trimmed board (`779c419`)"; see the current status above.)

**Status (2026-11-13, D-57 to D-59: CR routed, both fab packages exported, not ordered).** The CR board
`cr/cr.kicad_pcb` is placed, poured and routed. D-57 adds a /GND pre-via at (42.30, 59.30) for C102c pad 2 and
extends the VCHGIN L3 strap (`VIN_L3`; minimum section 4.174 mm against 3.221 mm required by R9.H25; 2.75 A at a 10 degC rise
against the 2.41 A basis). D-58 routes the signal nets with the corridor router (route-race r9, plan softum, seed 1;
committed as `621fb28`). D-59 places the reference designators with `gen/silk_refs.py`. On the final board, ERC reports
0 messages, DRC (`--severity-all --schematic-parity`) reports 0 violations, 0 unconnected items and 0 parity issues,
and the constraint check (`cr/constraint_check.md`) gives 98 pass, 0 FAIL and 2 listed exemptions. The CR fab package
is `fab/cr_2026-11-13/` and the EIB fab package is `fab/eib_2026-11-13/`; neither is ordered. The current-state record
for the operator is `MORNING_REVIEW_2026-11-13.md` (decisions with reversal paths, items for the operator). The
operator authorized the design owner to continue without a stop to the end of the PCB design (2026-11-12/13
overnight), so check-in 3 (placement images) was not held separately. The next action is operator check-in 4: the
pre-order review of the routed CR and the two packages (section 3a lists the items that block the order).
(**Superseded 2026-11-13, D-60:** "On the final board" (the D-59 board is the routed board before the D-60 trim); "the
constraint check (`cr/constraint_check.md`) gives 98 pass, 0 FAIL and 2 listed
exemptions" and the package `fab/cr_2026-11-13/` as exported from the untrimmed D-59 board; see the current status
above.)

**Status (2026-11-12, end of D-50 steps 2-4).** Steps 1 to 4 of the D-50 round order are done, and check-in 1 has
passed. Step 2 is the section H re-run (`docs/reviews/charger_eval_2026-11-05/round4/calc/r9_calc.py`, design change
row r9-9). Step 3 is audit run 002, adjudicated in `docs/reviews/charger-design/run-002-2026-11-12.md` (r9-10): 29
findings, 0 blocker, 8 major and 21 minor after verification, with no fix applied. Step 4 is the new-outline
generator (D-51, D-52; `cr/geometry_check.md`). The D.3 rows are applied to `references/Scale Car Teensy IO - IO - 2026-11-12.csv`
(r9-11). Check-in 2 is closed (2026-11-12, later): the operator approved all 29 audit fixes, and design change row r9-12
applies them with rulings R1 to R6 as orchestrator defaults (README section 11 items 15 to 21). The netlist step is
done: R132 and R131B are 4.99 kOhm and the CR netlist is frozen (LAYOUT_DECISIONS D-53). The verify pass of the
r9-12 fixes is clean (run-002 record, section "Fix round r9-12 verification"). Design change row r9-13 re-maps four
J-TAP cavities (an orchestrator default that the operator may revert), and the netlist is re-frozen (D-53 amendment).

**Status (2026-11-13, D-50 step 5 done).** The CR is placed on the plug-on outline (LAYOUT_DECISIONS D-54). The live
board `cr/cr.kicad_pcb` is variant B of `gen/layout_cr.py` (now the default) at the power-pour stage. A two-seed
routability probe ranked B above variant A: both close 106 of 107 connections, and B needs 860-897 mm of track
against 1342-1391 mm and 161-162 vias against 181-185. The next action is **operator check-in 3** on
`cr/placement_F.png` and `cr/placement_B.png`, then the full route-race (step 6) on variant B. (**Superseded
2026-11-13:** check-in 3 was not held separately; see the current status above.)

**Status (2026-11-13, later, D-55).** The placement review of variant B (`cr/placement_review_r9.md`: 1 blocker, 4
major, 9 minor) is applied in the generator, and the live board is rebuilt (LAYOUT_DECISIONS D-55, Table D-55). The
U101 network sits in the +x pocket and the north strip, each part within 5 mm of its pin, and no ratsnest line crosses
the CHG pin column. Constraint check: 88 pass, 0 FAIL, 3 listed D-20 exemptions (R102, R104, R129). DRC: 124
silkscreen reference-field items only, 109 unconnected, 0 parity. The netlist is unchanged. The next action is still
operator check-in 3, on the new images. (**Superseded 2026-11-13:** D-56 to D-59 follow; the next action is check-in 4,
see the current status above.)

This note gives the starting point for the next session. `LAYOUT_DECISIONS.md` is the full record (D-01 to D-62).
The 2026-11-12 decisions are D-39 to D-50 there, the 2026-11-12 and 2026-11-13 board decisions are D-51 to D-62, and
every older entry carries its 2026-11-12 classification (retired, re-derive, amended or kept). (**Superseded
2026-11-13, D-62:** "D-01 to D-61"; "D-51 to D-61".)

## 1. State

| Item | State |
|---|---|
| EIB (2 layers, 24 x 38 mm) | complete: ERC 0, DRC 0 with schematic parity; fab package `fab/eib_2026-11-13/`, **not ordered**. Copper unchanged; U203, U204, C203, C204 and R258-R265 DNP, E4/E6 leads not fitted (D-49). The `dnp=True` set of `gen/netlist.py` (14 items) now drives the package: `eib/eib.kicad_sch` regenerated by `gen/sch.py` (only the 14 `dnp` flags change), the 14 board footprints set DNP and exclude-from-position-files in place (no re-route), and `bash gen/export.sh eib 2026-11-13` + `python gen/fab_readme.py eib 2026-11-13 fab/eib_2026-11-11` regenerate the BOM, position, KiKit and iBOM files (`export.sh` now passes `--dnp-field kicad_dnp`, so the iBOM leaves them out of its BOM table). Every Gerber and Excellon file is identical to `fab/eib_2026-11-11/` apart from the creation dates (package README section 6). `fab/eib_2026-11-11/` (hand-edited assembly files) stays as the record. The operator reviews the package before an order |
| CR outline | **plug-on placement frame x 18.584-67, y 7-94 (MB frame), 48.416 x 87 mm, stencil and reflow assembly (D-39); final board outline: the D-62 trim, 2327.7 mm², 40.02 x 64.81 mm; applied to the documents** (`LAYOUT_DECISIONS.md`, `OUTLINE_CHANGE_REASSESSMENT_2026-11-12.md`). The generator is built on it (D-52: `gen/mb_brd.py`, `gen/cr_geometry.py`, `gen/layout_cr.py`, `gen/check_constraints.py`); `cr/geometry_check.md` passes every check. The height survey is closed by D-51. The CR board file is built and routed on the outline (CR board file row). **After routing, the board is trimmed to the D-62 outline:** 10 corners before the fillets, edges at 0, 30, 45, 60, 90, 120, 135 or 150 degrees, every slanted edge at least 2.0 mm long, 1.0 mm fillets at every corner, inside the D-39 rectangle; filleted area 2327.7 mm² (the rectangle is 4212.2 mm²; 55 %), bounding box 40.02 x 64.81 mm, MB frame x 18.584-58.60, y 7.83-72.64, with the D-60 +x key ear for the D-41 key and four 6-32 holes (CR board file row). The D-39 rectangle stays the placement frame. `gen/cr_geometry.py` holds `FINAL_OUTLINE`, `TRIM_ANGLES`, `TRIM_MIN_EDGE`, `FILLET`, `KEY_EAR` and `MOUNTING_HOLES`; `gen/trim_cr.py` applies them through `tools/pcb/corridor_route/trim_outline.py` (with `--angles`, `--min-edge` and `--fillet`) and refuses when the result differs by more than 0.01 mm. (**Superseded 2026-11-13:** "No board file is built on the outline yet".) (**Superseded 2026-11-13, D-62:** "final board outline: the D-60 trim, 2241.6 mm²"; "a convex 18-vertex outline inside the D-39 rectangle, 2241.6 mm² (the rectangle is 4212.2 mm²; 53 %) ... x 18.58-58.60".) |
| 2026-11-12 decisions | first round (`DESIGN_STATE_2026-11-12.md` Table 1) and second round (`decisions_2026-11-12/round2/`, digest `orchestrator_digest.md`) **recorded**; LAYOUT_DECISIONS D-39 to D-50 and the classification of D-01 to D-38 applied this round |
| CR netlist | regenerated from `gen/netlist.py` on the reduced design (D-47, D-31, D-44): 78 parts (r8: 145). W6 and W7 carry the through-hole placeholder footprints of D-45 (placeholder status closed by operator ruling 2026-11-13 (Review 1/2), section 3a gives the record; the footprint names keep the `_Placeholder` suffix). `cr/charger_r8_cr.pretty` was rebuilt with `gen/fplib.py` and now holds the J102 Micro-Fit footprint, so ERC reports 0 errors and 0 warnings. The netlist export reports "schematic has annotation errors"; the cause is the six letter-suffix references C102a, C102b, C102c, R106s, R131A and R131B (the message disappears when all six are renamed to numeric references in a scratch copy). These references are the B.8 designators and are accepted. The generator applies the 0.25 mm courtyard basis (`_CrtYd0.25`, D-52). **Frozen 2026-11-12 (D-53):** R132 and R131B are 4.99 kOhm (r9-12, ruling R2); `cr/charger_r8_cr.pretty`, `cr/cr.kicad_sch` and `cr/cr.net` were regenerated without placement; 78 parts, 79 nets, connectivity unchanged, ERC 0 errors and 0 warnings, sha256 `e98f4e49e22f60cab729c1db3f93439ce24fda5507423080c31d613b8f340833` (superseded in r9-13). **Re-frozen 2026-11-12 (D-53 amendment, r9-13):** the J-TAP re-map changes connectivity only at J102 pins 1, 2, 7 and 8; `cr/cr.kicad_sch`, `cr/charger_r8_cr.kicad_sym` and `cr/cr.net` regenerated, ERC 0 errors and 0 warnings, sha256 `608bbf977803bc40118baf7a9f7635c60a9d3da6e1ca88ca0b95b1db1f64909b` |
| CR board file | **Plug-on outline, variant B, placed, poured, routed, trimmed to the D-62 outline, stitched and straightened (2026-11-13, D-57 to D-62).** 78 parts, all on the top, 0 outside the outline. D-62 (`89c2d72`; operator ruling 2026-11-13 to the routing session, route-race change request R9-04): `gen/trim_cr.py` trims the routed board `621fb28` to the 10-corner `FINAL_OUTLINE` with edges in `TRIM_ANGLES`, slanted edges of at least 2.0 mm and 1.0 mm fillets drawn as Edge.Cuts arcs (2327.7 mm², bounding box 40.02 x 64.81 mm, MB frame x 18.584-58.60, y 7.83-72.64); MH2 moves to (54.85, 68.79), and MH1, MH3 and MH4 do not move. A CR rotated 180 degrees lands on J-BL (7.73 mm of x overlap) and J-FC (7.73 mm). The routing session re-ran the D-61 finish on the trimmed board: 279 grid stitching vias, 769 track segments and 824.5 mm after straightening, and 3 gap-fill vias at (36.04, 26.88), (34.29, 33.53) and (33.54, 59.53); the board has 288 /GND vias. Then `gen/silk_refs.py` put 60 of 78 references on F.Silkscreen, 27 of them over another courtyard, and 18 on F.Fab only (C107, C115, C130, C132, D105, D106, R122, R130, R131B, R147, R184-R189, U110, W3; C110 is back on the silkscreen), and `gen/sync_fields.py` wrote the J102 and cable part numbers. Checks on the D-62 board: ERC 0; DRC (`--severity-all --schematic-parity`, OSH Park-only rule file) 0 violations, 0 unconnected items, 0 parity issues; constraint check 109 pass rows, 0 FAIL, 3 exemption rows; the D-20 stitching row passes with 306 stitch points and a largest distance of 3.51 mm at (43.0, 44.8), against 3.54 mm. The figures in `figures/cr_routed_2026-11-13/` are regenerated from the D-62 board. The D-61 and D-60 values that follow are history. D-61 (routing session `07a6181`, merged as `b8e3762`; gap fill merged as `437d2d7`; operator requests 2026-11-13, relayed by the routing session): after `gen/trim_cr.py`, `tools/pcb/corridor_route/plane_vias.py --stitch 2.5` places /GND stitching vias on a 2.5 mm grid inside the trimmed GND fill, `straighten.py` replaces staircase runs of unlocked signal tracks by straight or 45-degree runs, `tools/pcb/corridor_route/stitch_gaps.py` adds /GND vias where the filled L4 pour is more than 3.54 mm from a stitch point, and `gen/silk_refs.py` runs last. The D-60 outline and holes do not change. The board has 278 /GND vias: 269 grid stitching vias, 3 gap-fill vias at (36.04, 26.87), (34.34, 33.62) and (34.04, 59.52), and the pre-vias and plane vias (the D-58 to D-60 board had 6, because the `ROUTE_SKIP_FR=1` build skips `route.py stitch()`). Straightening reduces the track segments from 1791 to 768 and the track length from 830.8 to 823.9 mm; vias, pads and locked pre-tracks do not move, and the references do not change (59 on F.Silkscreen, 19 on F.Fab only). Checks on the D-61 board: ERC 0; DRC (`--severity-all --schematic-parity`, OSH Park-only rule file) 0 violations, 0 unconnected items, 0 parity issues; constraint check 109 pass rows, 0 FAIL, 3 exemption rows. The new D-20 stitching row measures 296 stitch points (/GND vias and /GND plated holes); the largest distance to the nearest one over the filled L4 pour is 3.47 mm at (31.0, 34.7), against 3.54 mm for a 5 mm square pitch, so the row passes. Before the gap fill the row read FAIL (293 stitch points, 4.08 mm at (36.0, 26.7)); routing request R9-03 closed it. The figures in `figures/cr_routed_2026-11-13/` are regenerated from the D-61 board. The intermediate board `8521bf8` (stitching before the trim, 19-vertex outline of 2248.3 mm²) is superseded; do not use its values. D-60 (`779c419`; operator rulings 2026-11-13, route-race change request R9-02): after routing, `gen/trim_cr.py` trims the board to the convex 18-vertex `FINAL_OUTLINE` of `gen/cr_geometry.py` (2241.6 mm², bounding box 40.02 x 64.81 mm, MB frame x 18.58-58.60, y 7.83-72.64, +x key ear kept) and adds four NPTH 3.70 mm holes for 6-32 screws that hold a 3D-printed support: MH1 (26.23, 69.04), MH2 (54.85, 63.79), MH3 (54.85, 11.43), MH4 (24.48, 25.18), each with an all-layer copper keep-out of radius 4.0 mm and a 3.6 mm head disc on the board. No part, track or via moved. A CR rotated 180 degrees now lands on J-BL (7.73 mm of x overlap) and J-FC (7.63 mm), not on J-BT (D-41 amended). After the trim, `gen/silk_refs.py` puts 59 of 78 references on F.Silkscreen, 27 of them over another courtyard; C110 moved to F.Fab, so 19 are on F.Fab only (C107, C110, C115, C130, C132, D105, D106, R122, R130, R131B, R147, R184-R189, U110, W3); `cr/silk_refs.md` lists them. Checks on the trimmed board: ERC 0; DRC (`--severity-all --schematic-parity`, OSH Park-only rule file) 0 violations, 0 unconnected items, 0 parity issues; constraint check 108 pass rows, 0 FAIL, 3 exemption rows (R102 under D-20; R103 and R129 as listed U101-network exemptions, D-55 and D-56). The figures in `figures/cr_routed_2026-11-13/` (3D views and layer images) are regenerated from the trimmed board. D-57 (`0e7f22b`): /GND pre-via at (42.30, 59.30) for C102c pad 2 and the extension of the VCHGIN L3 strap (`VIN_L3`); strap minimum section 4.174 mm against 3.221 mm required (R9.H25), 2.75 A at a 10 degC rise against the 2.41 A basis. D-58 (route-race r9, plan softum = plan softu with `mask_margin` 0.075 mm, seed 1; committed as `621fb28`): 107 of 107 connections, 148 router vias, 830.8 mm of router track, every router track 0.1524 mm, vias 0.6 / 0.3 mm only, 0 vias on SMD pads, divider-top same-layer metric 0.00 mm, 0.7 mm of logic track and 1 logic via (/CE_DRV_J) in the divider zone; U101 high-impedance via counts /N_UV 2, /N_OV 0, /N_DVDT 2, /N_ILIM 2, /N_IMON 3, /N_FLT 2. Tools commit `114ad04` (merged as `a919337`) makes the router and its score script ban vias from the square-cornered mask opening of SMD pads, so new plans do not need `mask_margin` 0.075 mm; the routed board is unchanged. D-59 (`6ae73df`) first placed the references with `gen/silk_refs.py` (1.0 / 0.8 mm text, 0.15 mm stroke; counts superseded by D-60 and D-62). The smallest via-annulus gap to a pad plus its mask opening is 0.027 mm and is same-net (a pad's own escape via); the smallest different-net gap, measured on the D-60 board and not re-measured on the D-62 board, is 0.115 mm (C116.1 /3V3 to a /QUAL via), about 0.094 mm with square-cornered openings. Rebuild procedure: section 4. (**Superseded 2026-11-13, D-62:** "Plug-on outline, variant B, placed, poured, routed, trimmed, stitched and straightened (2026-11-13, D-57 to D-61)"; the D-61 board values "278 /GND vias", "768 ... 823.9 mm", "59 on F.Silkscreen, 19 on F.Fab only", "296 stitch points ... 3.47 mm at (31.0, 34.7)" and "regenerated from the D-61 board" as the current state.) (**Superseded 2026-11-13, D-61:** "Plug-on outline, variant B, placed, poured, routed and trimmed (2026-11-13, D-57 to D-60)"; the D-60 checks "constraint check 108 pass rows, 0 FAIL, 3 exemption rows" (no D-20 stitching row existed); "The figures in `figures/cr_routed_2026-11-13/` ... are regenerated from the trimmed board" (the D-60 board, 6 /GND vias). The D-61 board gives the same DRC result and reference counts as the D-60 board.) (**Superseded 2026-11-13, D-60:** "Plug-on outline, variant B, placed, poured and routed (2026-11-13, D-57 to D-59)"; the D-59 reference placement "60 of 78 references on F.Silkscreen ..., 26 of them over another courtyard; 18 are on F.Fab only"; "constraint check 98 pass, 0 FAIL, 2 listed exemptions"; the figures as made from the untrimmed board.) (**Superseded 2026-11-13, D-57 to D-59:** "Plug-on outline, variant B, pour stage, after the D-56 fix round on the r9b re-review (2026-11-13). ... Constraint check 97 pass, 0 FAIL, 3 listed D-20 exemptions (R102, R103, R129) ... J1.10 is fed through the L3 VCHGIN strap alone (3.645 mm narrowest section ...) ... DRC ...: 124 violations ..., 107 unconnected, 0 parity issues. Next: the 4-seed probe re-run (step 6 entry)".) (**Superseded 2026-11-13, D-56:** "after the D-55 fix round ... 88 pass ... (R102, R104, R129) ... 109 unconnected".) Pour-stage rebuild (the D-56 record; section 4 is the current procedure) from `hardware/charger_evm_r8`: the placement half of `gen/make_board.sh` (`gen/pcbbuild.py cr ../cr` from `gen/`, copy `tools/pcb/fab_rules/fab_4layer_oshpark_only.kicad_dru` to `cr/cr.kicad_dru`, `apply_board_setup.py`, the OSH Park minima and the 0.1524 mm Default net class, `gen/silk_fix.py`), then `ROUTE_SKIP_FR=1 route.py cr ../cr` from `gen/`, `check_constraints.py cr ../cr > ../cr/constraint_check.md`, `kicad-cli pcb drc --severity-all --schematic-parity -o cr/drc_place.rpt`, `plot_place.py dump` (venv) and `plot_place.py plot` (miniforge). **Pitfalls:** `route.py` without `ROUTE_SKIP_FR=1` runs Freerouting into the live board; `check_constraints.py` prints to stdout; a full `make_board.sh cr` still rewrites the `cr/cr.net` date line and 13 library files (stamp-only; restore them, or build `gen/fplib.py` into a scratch folder and copy only the changed footprints, as D-55 did). Variant A: `LAYOUT_VARIANT=A`, record in `cr/variants_r9/A/` (predates D-55). (**Superseded 2026-11-13, D-55:** the D-54 row "constraint check 74 pass, 1 FAIL (D-44: U101.25); DRC 131 violations, 3 courtyard overlaps, 4 starved thermals; rebuild with `cr/variants_r9/B/cr.kicad_dru`; a full `make_board.sh cr` copies the shared OSH Park/PCBWay rule file back in".) |
| CR fab package | `fab/cr_2026-11-13/`, re-exported by `gen/export.sh cr 2026-11-13` from the D-62 board (trimmed, stitched, straightened and gap-filled; `89c2d72`); **not ordered**. The package README section 1 size row gives the D-62 outline (10 corners, 1.0 mm fillets, 2327.7 mm², 40.02 x 64.81 mm), its OSH Park row states the confirmed 4-layer stack-up and that OSH Park sells boards in multiples of 3, and its quantity stays "5 (E BOM)" until the operator rules (section 3a). The NPTH drill file has tool T2, 3.70 mm, for the four 6-32 holes. The status line of the package README, written by `gen/fab_readme.py`, still names the D-60 trim and 19 F.Fab references; the size row of the package README and this document give the current values. (**Superseded 2026-11-13, D-62:** "from the D-61 board (trimmed, stitched, straightened and gap-filled; `437d2d7`)"; "The package README section 1 size row gives the D-60 outline (2241.6 mm²)".) (**Superseded 2026-11-13, D-61:** "from the trimmed D-60 board (`779c419`)".) (**Superseded 2026-11-13, D-60:** "`fab/cr_2026-11-13/` (`cb1def6`; README corrected in `c16313b`), written by `gen/export.sh cr 2026-11-13` on the D-59 board".) The fab is OSH Park (bare board); the rule file is `tools/pcb/fab_rules/fab_4layer_oshpark_only.kicad_dru`. The KiKit `jlcpcb` and `pcbway` presets with `--assembly` wrote no `bom.csv` (an `int()` parse error, probably on the letter-suffix references such as R131B and C102a); this does not affect an OSH Park bare-board order, and `assembly/cr-bom.csv` is the assembly BOM. The EIB package `fab/eib_2026-11-13/` (EIB row) is 2-layer, so at OSH Park it is a separate order and is not on the CR panel |
| Current-state record | `MORNING_REVIEW_2026-11-13.md`: the check results (Table 1), the decisions of the overnight round with reversal paths (Table 2) and the items for the operator (section 3) |
| CR interactive pass (2026-11-12) | **superseded** by the new outline and the route-race (D-36, D-50). The project is archived at `archive_r7_outline/cr/interactive/` (move staged this round; KiCad must not hold the old path open) |
| r7 layout work | archived in `archive_r7_outline/` (variants, attempts, images, routability study); reference only |
| Best partial CR routing (r7) | `archive_r7_outline/cr/attempts/cr_pathfinder_0p1mm_partial.kicad_pcb` (reference only; 516 clearance violations) |
| Ordering BOM | `bom_2026-11-11/ordering_bom.csv`: r9 rows applied on the reduced part list (TSW/SSQ, J-TAP and cable assembly, 0603 and DBV rows; README section 8); the r9-5 mechanical rows are applied as well (feet, bed RTV and bond coupon rows deleted, 467MP re-scoped to the B1R wedge, CR PCB row on the plug-on outline with 1 oz / 0.5 oz copper, stencil and paste row added). No price, stock or SKU read on a live page (bot checks). The B1R wedge, posts and off-CR support rows wait for the A.3 lead route on the new outline |
| Section H re-run (step 2) | done: `round4/calc/r9_calc.py` with `r9_calc_out.txt` and `.json`; design change row r9-9; H.24(a)-(c) new; R9.H25 (VCHGIN L3 strap as the only J1.10 feed) added in change row r9-15 (D-56). R9.H26 (VCHGOUT path from U101 OUT to W1 at 3.21 A, necks measured on the D-62 board) is added after Review 2/2; two necks fail on the long-conductor basis (section 3a item 8). The IPC-2221 rows now print as comparisons; the "-> pass" that earlier followed an IPC-2221 figure was the IPC-2152 verdict |
| Audit run 002 (step 3) | adjudicated: `docs/reviews/charger-design/run-002-2026-11-12.md`; L.9 and Table L.9-1 final; 0 blocker, 8 major, 21 minor; check-in 2 closed and all 29 fixes applied in r9-12; verify pass clean (run-002 record, section "Fix round r9-12 verification") |
| IO CSV | done: D.3 rows applied to `references/Scale Car Teensy IO - IO - 2026-11-12.csv` under the operator's delegation; the undated CSV is deleted; freed pins named FREE_10, FREE_16, FREE_17, FREE_21, FREE_23 (r9-11) |
| Netlist audit (r8) | three independent reviewers, 216 parts against B.8/E: no discrepancy. About 18 section-L dispositions rest on removed parts, so L.8 no longer certifies the design; the r9 audit (L.9) replaces it |

## 2. Rulings in force

CR board and assembly:

- Plug-on outline x 18.584-67, y 7-94; KiCad Y 6.00-93.00 (D-01, D-39).
- All SMT on the top side, one stencil and one reflow, no bottom fallback; escalate to the operator if a placement
  does not fit (D-44).
- Courtyards on the IPC-7351 nominal basis, 0.25 mm; reference designators on the silkscreen (D-03, D-12a), except
  the 18 references that are on F.Fab only after the D-62 re-placement (`cr/silk_refs.md`). (**Superseded
  2026-11-13, D-60:** "the 18 references that D-59 moves to F.Fab only"; C110 is the added reference.)
  (**Superseded 2026-11-13, D-62:** "the 19 references that are on F.Fab only after the D-60 re-placement"; C110 is
  back on the silkscreen.)
- After routing, the CR is trimmed to the D-62 outline (10 corners, edges at 0, 30, 45, 60, 90, 120, 135 or
  150 degrees, slanted edges of at least 2.0 mm, 1.0 mm fillets; 2327.7 mm²) inside the D-39 rectangle; the rectangle
  stays the placement frame (D-60 amended by D-62, D-39 amended). (**Superseded 2026-11-13, D-62:** "trimmed to the
  D-60 convex outline (2241.6 mm²)".)
- R101, R103, R104, R105, R106s and C101 in 0603; single-gate logic in SOT-23 (DBV), so U107 is SN74LVC1G11DBVR;
  U105, U106, U110 and U118 stay DCT (D-44).
- U101 stays TPS26630RGER, the one 0.5 mm exception; its exposed-pad vias are exempt from D-37, with window-pane
  stencil apertures and L4 tenting (D-40).
- Vias: no via on an SMD pad first; plain unfilled via-in-pad only as a listed last resort (D-37, D-36). 0.6 / 0.3 mm
  is the only via size (D-29).

Mechanics and leads:

- Mating stack: SSQ-110/112-01-L-S sockets on the MB, TSW-110/112-07-L-S pins on the CR (bodies on the underside);
  hard stop with the CR underside 11.05 mm above the MB; all 22 positions; no key; engagement-start height below
  21.70 mm; CR pins soldered while plugged (D-41). A CR rotated 180 degrees lands on J-BL and J-FC, not on J-BT
  (D-41 amended by D-60); on the D-62 outline the x overlap is 7.73 mm at each of J-BL and J-FC.
- No standoffs on the MB; the CR is held by the 22-pin friction fit. Four 6-32 holes in the CR (MH1 to MH4) hold a
  3D-printed support (D-42 amended by D-60). (**Superseded 2026-11-13, D-60:** "No standoffs; the CR is held by the
  22-pin friction fit (D-42)".)
- Taps go to one CR connector, J-TAP; the W leads stay soldered on the CR as through-hole leads and unplug at the
  existing EVM terminals (D-45).
- J-TAP: Molex Micro-Fit 3.0 2 x 5 THT, Molex 43045-1012, hand-soldered last, cable Molex 2147561101 (operator ruling
  2026-11-13 (Review 1/2), section 3a; **Superseded 2026-11-13:** "cable 2147581101"); cavity map (r9-13) row A T2 T17 T17r T5
  T13, row B T6 T1 T7b T16 T10 (superseded in r9-13: row A T1 T7b T17r T5 T13, row B T6 T2 T17 T16 T10); placement
  constraints in D-46. The re-map is an orchestrator default that the operator may revert.

Stack-up and fab rules:

- L4 solid GND over the whole CR, no signals and no straps, stitched to L2 at <= 5 mm, masked; air gap >= 1.5 mm to
  the tallest MB part, THT tails included; sensitive-part window y 30.8-66.86 preferred, not hard (D-20).
- VCHGOUT routing is the design owner's call on L1 and, if needed, L3 (D-22). The current capacity of two short F.Cu-only
  necks on the VCHGOUT path from U101 OUT to W1 (U101 OUT pins to C103, x 39.25-41.00; C103 ground pad and D-56 /GND
  via notch, x 37.50-38.75) is open for an operator ruling (section 3a item 8).
- OSH Park-only CR rule file (`tools/pcb/fab_rules/fab_4layer_oshpark_only.kicad_dru`, D-55); router default and
  board Default net class 6/6 mil (0.1524 mm), 5/5 mil (0.127 mm) only at necks; 1 oz outer / 0.5 oz inner; unused
  inner pads removed on every THT pad (D-29, D-30). The EIB stays at 6/6 mil.
- No polyimide sheet and no thermocouple (D-43). T-F-16 is retired (operator ruling 2026-11-12); the MB VBT trace rise
  under the CR is accepted unmeasured (design document J.1 item 25), so no T-F-16 open item remains.

Circuit:

- Ten taps (T1, T7b, T2, T5, T6, T10, T13, T16, T17, T17r); gate release = (H1·UVB) + FCC_ON·¬FCC_OFF +
  (QUAL·FCC_OFF·¬P5); /CE = ¬P5; RFC_OFF = FCC_OFF + (H1·UVB); 5-LVC mapping U105, U106, U107, U110, U118; CE_DRV
  buffered by U106A; R108 47 kOhm (D-47).
- No DNP option re-admitted; B.5 retired; the F22, F23 and F24 pads removed (D-31).
- Tap T22 and the BQ29200 pack-OV permit removed; pack OV is firmware-only (D-38).
- CHG_QUAL on Teensy pin 33; pin 10 is a freed pin (D-48). The IO CSV is amended in `references/Scale Car Teensy IO - IO - 2026-11-12.csv` (2026-11-12).
- EIB sense branch DNP; J101 pins 11 and 13 NC (D-49).

Firmware preconditions (design-document requirements; no firmware is edited in this round):

- The R5 MCU watchdog firmware is built with the rest of the new-charger firmware, in the handoff after the PCB
  design. No charging of any kind before R5 and T-W-01a pass; FC windows also need the full T-W-01
  (`decisions_2026-11-12/round2/dec2_hang_defence_2026-11-12.md`).
- The remaining second-round firmware rules (T_QUAL_MAX, QUAL before P5, the pin-34 edges, the CHG_IIN cross-check,
  the freed-pin rule, the new FR-08(b) and the new State 98 `J`) are in
  `decisions_2026-11-12/round2/dec2_firmware_rules_2026-11-12.md`.

## 3. Next steps (D-50)

Items 1 to 5 below are done (2026-11-12). Check-in 1 passed (operator ruling (b)); item 2 became the new script
`round4/calc/r9_calc.py`, and the earlier scripts stay unmodified as the r8 record. Items 6, 8 and 9 and the fab
package of item 10 are done (2026-11-13). The list numbers include the operator check-ins; D-50 steps 5 to 8 are
items 6, 8, 9 and 10. As part of item 9, the routed CR was trimmed to the D-60 outline with four 6-32 holes (operator
rulings 2026-11-13), and the fab package of item 10 was re-exported from the trimmed board (`779c419`). After the
trim, D-61 added /GND stitching vias, straightened the tracks and filled the last stitching gap (operator requests
2026-11-13); the fab package was re-exported from that board (`437d2d7`). D-62 then redid the trim with edges at
limited angles and 1.0 mm fillets (operator ruling 2026-11-13), the D-61 finish was re-run on the D-62 outline, and
the fab package and figures were re-exported from the D-62 board (`89c2d72`). The D-20 stitching row of the
constraint check passes on the D-62 board. (**Superseded 2026-11-13, D-61:** "the fab package of item 10 was
re-exported from the trimmed board (`779c419`)" as the current package.) (**Superseded 2026-11-13, D-62:** "the fab
package was re-exported from that board (`437d2d7`)" as the current package.)
Item 7 (check-in 3) was not held separately, because the operator authorized the design owner to continue without a
stop to the end of the PCB design (2026-11-12/13 overnight). The open item is check-in 4 (item 10). Section 3a
records the operator review items. Operator ruling 2026-11-13 (Review 2/2) disposes of the items that blocked the
order; the VCHGOUT necks of R9.H26 (section 3a item 8) are open for an operator ruling. (**Superseded 2026-11-13:**
"and section 3a lists the items that block the order".) (**Superseded 2026-11-13, R9.H26:** "of which none still
blocks the order (operator ruling 2026-11-13 (Review 2/2))".)

1. **Operator check-in 1:** a diff summary of the design-document and netlist update (done).
2. Re-derive H.4, H.19, H.20, H.22 and every row that rests on a removed part, and mark the r7-outline H.23 rows
   retired. This step runs before the audit. (Done, r9-9: the new script `round4/calc/r9_calc.py` does the re-run;
   `round3/calc/r3_calc.py` and `round4/calc/r7_calc.py` stay unmodified as the r8 record. Superseded: "Strip the
   removed parts from `round3/calc/r3_calc.py` and `round4/calc/r7_calc.py`, re-run both".)
3. The r9 audit (hybrid: adversarial-doc-review on B.1, F.3, F.5, G.3, J.1 and the reopened section-L items;
   self-review on B.3, B.6, B.7, F.2, F.4, G.2 and the A.8 adjacent-pair short table for the J-TAP order). The result
   is L.9, which replaces L.8 (done, r9-10).
4. In parallel with step 3: the new-outline generator. Replace every r7 construct listed in
   `outline_change_2026-11-12/retired.md` section 4 (outline, `GRID_BOUNDS`, `PARK`, `RIM_X`, `LFC_Y`,
   `mb_bottom_clearance()`, tab regions, feet, the r7 power geometry), add the TSW, J-TAP and W-pad footprints, the
   region table, the side flags and the new `check_constraints.py` rows, and add the H.23 successor geometry calc.
   Re-base every courtyard on the D-03 0.25 mm rule in `gen/fplib.py` and rename the `*_CrtYd0.10` footprints
   (open until done; the W6/W7 placeholders already use 0.25 mm), and replace the W6/W7 placeholder geometry
   once the 26/28 AWG OD is verified. (**Superseded 2026-11-13:** the W6/W7 geometry is kept and the placeholder
   status is closed by operator ruling 2026-11-13 (Review 1/2); section 3a.) Regenerate the EIB schematic, board and fab exports so that the
   `dnp=True` set in `gen/netlist.py` drives `eib-bom.csv`, `eib-pos.csv`, the kikit files and `eib_ibom.html`.
   (Done for the CR generator, D-51, D-52. The EIB export regeneration from the `dnp=True` set is closed
   2026-11-13: `fab/eib_2026-11-13/`, copper identical (section 1, EIB row). Open placeholders: the MS4 rim distance. The Molex 43045 drawing, the TSW pad and drill
   and the W6/W7 holes are closed by operator ruling 2026-11-13 (Review 1/2; section 3a). (**Superseded 2026-11-13:**
   "Open placeholders: the Molex 43045 drawing, the TSW pad and drill, the W6/W7 holes and the MS4 rim distance.") For steps 5 and 6: `gen/make_cr_all.sh` must drop B.Cu from the PathFinder layer set, and
   `gen/route_cr.py` TRACK is 0.127 mm against the D-29 0.1524 mm default; closed in D-55: TRACK and CLEAR are
   0.1524 mm.) (**Superseded 2026-11-13:** the plug-on CR is routed by the corridor router, D-58; `gen/make_cr_all.sh`
   and PathFinder are not used, so the B.Cu item is moot.)
5. **Operator check-in 2 (closed 2026-11-12):** all fixes approved; r9-12 applies them with rulings R1 to R6 (README
   section 11 items 15 to 21). The netlist step is done and the netlist is frozen (D-53). The verify pass is clean.
6. Placement on the frozen netlist, all SMT on the top side. (Done, D-54: variant B at the pour stage.)
7. **Operator check-in 3:** placement images (`cr/placement_F.png`, `cr/placement_B.png`), before routing. Items for
   the operator: the D-55 fix round (Table D-55), the R104 and R129 D-20 exemptions (A.8 <= 5 mm binds; C129 is
   now inside the window), the W2 move to x 27.2 and the D-54 open items that remain (J102 latch (closed 2026-11-13 by
   operator ruling 2026-11-13 (Review 1/2), section 3a) and THT-tail clearance, /N_OV at the route-race, the stale variant-A J102 target, the make_board stamp churn). The OSH Park-only
   rule file is in `tools/pcb/fab_rules/` and `gen/make_board.sh` names it (D-55; not committed). (**Superseded 2026-11-13:** the rule file is committed, `8b68044`.) (**Superseded:**
   "the R129/C129 deviation from the D-20 window (D-54 item 7) ... the U101.25 D-44 row, the fixed-coordinate
   courtyard overlaps. Before step 8, commit the OSH Park-only rule file under `tools/pcb/fab_rules/` and point
   `gen/make_board.sh` at it.") (Not held separately, 2026-11-13: the operator authorized continuing to the end of the
   PCB design. The D-55 and D-56 fix rounds, the D-20 exemptions and the D-54 open items are in the operator's
   pre-order review of item 10.)
8. The full route-race (`route-race` skill: reference at four or more seeds, diagnosis, tested change requests, one
   design-owner batch). (Done, D-57 and D-58: change request R9-01 applied as D-57; plan softum, seed 1, 107 of 107
   connections.)
9. DRC and the constraint check. (Done, D-58 to D-62: constraint check 109 pass rows, 0 FAIL, 3 exemption rows
   (R102 under D-20; R103 and R129 as listed U101-network exemptions, D-55 and D-56); the D-20 stitching row reads
   3.51 mm against 3.54 mm and passes; DRC 0 violations, 0 unconnected items, 0 parity issues. The outline was trimmed
   and the four 6-32 holes added by `gen/trim_cr.py` (D-60, outline redone by D-62); `plane_vias.py --stitch 2.5`,
   `straighten.py` and `stitch_gaps.py` then ran, and `gen/silk_refs.py` re-placed the reference designators (D-61
   order), followed by `gen/sync_fields.py` on the D-62 board.)
   (**Superseded 2026-11-13, D-62:** "Done, D-58 to D-61: ... the D-20 stitching row reads 3.47 mm against 3.54 mm",
   the D-61 board.)
   (**Superseded 2026-11-13, D-61:** "Done, D-58 to D-60: ... constraint check 108 pass rows, 0 FAIL, 3 exemption
   rows" as the current result; the D-60 board had no D-20 stitching row.)
   (**Superseded 2026-11-13, D-60:** "Done, D-58 and D-59: ... constraint check 98 pass, 0 FAIL, 2 listed
   exemptions".)
10. **Operator check-in 4:** the pre-order review of the routed CR and the two fab packages, before any order. The fab
    packages are exported (`fab/cr_2026-11-13/`, re-exported from the D-62 board in `89c2d72`;
    `fab/eib_2026-11-13/`) and not ordered. The check-in includes the VCHGOUT ruling of section 3a item 8.
    (**Superseded 2026-11-13, D-61:** "re-exported from the trimmed D-60 board in `779c419`".) (**Superseded
    2026-11-13, D-62:** "re-exported from the D-61 board in `437d2d7`".) The packages were exported before this check-in under the same overnight authorization; D-50
    placed the check-in before the fab package. (**Superseded 2026-11-13:**
    "before the fab package and any order. Then the fab package (`gen/export.sh`, `gen/fab_readme.py`)".)

Check-in 2 items (README section 11 items 15 to 21) are closed under r9-12; rulings R1 to R6 are defaults the operator
may override. The EIB package review before an order (D-49) stays open. The check-in 1 items are closed: the T5-T10 diagonal was accepted (D-46), and the section 6 survey was
closed by D-51.

## 3a. Items that block the CR bare-board order

Besides the operator's review (check-in 4), the items below blocked the order of the CR bare board. Section 11 of
`LAYOUT_DECISIONS.md` holds the numbered items. Operator ruling 2026-11-13 (Review 2/2: BAV199, strap, OSH Park (fab
checks), local_6e36c3a4-f328-44cd-8c31-05ea2fa7bfa3, chat 2026-11-13) disposes of each of them (items 1 to 7
below). Item 8, the VCHGOUT half of `LAYOUT_DECISIONS.md` section 11 item 2, was outside that ruling and is open; it
needs an operator ruling, and only one of its options changes the board. (**Superseded 2026-11-13, R9.H26:** "No
bare-board order blocker remains from the operator review items.")

1. Closed 2026-11-13: BAV199 D104 to D106 pinout (item 9). Nexperia BAV199 product data sheet v.4 (1 April 2023;
   supersedes v.3 of 2020-09-01, whose only change is "Product changed to non automotive", Table 8), section 5 Table
   2: pin 1 A1 (anode, diode 1), pin 2 K2 (cathode, diode 2), pin 3 K1 and A2. The board matches: pad 1 /GND, pad 2
   /3V3, pad 3 /N_H1P (D104), /N_H1M (D105) and /N_UVP (D106). Operator: "Yes".
2. Closed 2026-11-13: the SOT-23 reflow footprint of D104 to D106 (item 10). `SOT-23_CrtYd0.25` has 1.475 x 0.6 mm
   pads at 1.9 mm pitch, with the pad rows 1.875 mm apart (pads 0.20 to 1.675 mm from the centre line). The
   data-sheet Fig. 8 lead width is 0.38 to 0.48 mm, below the 0.6 mm pad width, and the lead tips lie 1.05 to
   1.25 mm from the centre line, which leaves a toe pad of 0.43 mm or more. The Fig. 9 reflow lands are about
   0.6 x 0.7 mm, with the rows about 2.0 mm apart. The KiCad pads are longer toward the body; this is a fillet
   difference, not a connectivity difference. The land-pattern refinement is dropped. Operator: "Close, no need to
   refine if the current footprint is verified compatible".
3. Closed 2026-11-13 on IPC-2152: the In2.Cu VCHGIN strap (item 2). The required section is 87.4 mil², which is
   3.221 mm at 17.5 µm. The 4.174 mm strap (113.2 mil²) gives 2.75 A at a 10 degC rise, and a 7.4 degC rise at the
   2.41 A basis. The OSH Park 4-layer page (`docs.oshpark.com/services/four-layer/`, read 2026-11-13) gives the inner
   layers as "0.68 mil (0.0175mm) 0.5 oz copper clad"; clad copper is not plated, so the finished thickness is
   17.5 µm (at 17.3 µm the result is 2.73 A). The IPC-2221 internal formula gives 2.04 A, below the 2.41 A basis,
   and needs 5.258 mm (`docs/reviews/charger_eval_2026-11-05/round4/calc/r9_calc_out.txt`); it does not pass, and the
   closure rests on IPC-2152 alone. Operator: "Accept, use IPC-2152"; on 0.5 oz inner copper, "Yes".
4. Closed 2026-11-13: the OSH Park 4-layer stack-up (item 5). The OSH Park 4-layer page (read 2026-11-13) gives
   63 mil (1.6 mm), 1 oz outer copper (clad and plated), 0.5 oz inner copper, FR408-HR at 190 degC Tg, ENIG, purple
   SMOBC on both sides, and via tenting "Yes (filled hole and flat surface not guaranteed)". The alternate-stack-up
   notices are commented out in the page source, so none is active. Operator: "Yes".
5. Closed 2026-11-13 as out of scope: the OSH Park quote (item 7). Operator: "Quote is outside the scope of the
   project".
6. Closed 2026-11-13: the OSH Park solder-mask expansion of 0.0508 mm (the TODO(verify) of the rule file). The OSH
   Park KiCad design-rules page gives "Solder Mask Expansion should usually be set to 2mil (0.0508mm)". The 4-layer
   page gives a maximum mask alignment error of 3 mil (0.0762 mm) and a minimum mask web of 4 mil (0.1016 mm), which
   is the board setting. The smallest different-net via-to-mask gap, 0.115 mm (about 0.094 mm with square-cornered
   openings), is larger than the 0.0762 mm alignment error. Operator: "Yes".
7. Amended 2026-11-13: the non-functional inner pads at connector holes (item 3) stay open as an assumption that is
   checked at submission; they do not block the order. The OSH Park page states nothing on non-functional pads. Its
   plated-drill-to-internal-copper rule of 10 mil (0.254 mm) is met: the inner pours keep 0.27 mm against the
   0.254 mm rule, and DRC reports 0 violations. All vias keep their inner pads; only J1 (22 pads), J102 (10 pads),
   W1 to W4, W6 and W7 have their unused inner pads removed. Operator: "Let's assume they will accept it. I will find
   out later when I submit the board if not."; on the decision, "We will decide once that time comes".
8. Open, new 2026-11-13: the VCHGOUT path from U101 OUT to W1 (the VCHGOUT half of item 2, kept open by Review 2/2).
   Calculation R9.H26 (`docs/reviews/charger_eval_2026-11-05/round4/calc/r9_calc.py`, output `r9_calc_out.txt`)
   uses a 3.21 A basis, a 10 degC rise and 1 oz outer copper counted as the 35 µm clad only (plating not credited).
   On that basis the IPC-2152 baseline fit needs 153.4 mil², that is 2.828 mm on F.Cu alone. The necks were measured
   on the D-62 board as vertical chords of the filled /VCHGOUT copper, pads not counted:
   - U101 OUT pins to C103, x 39.25-41.00: F.Cu only, 1.469 mm over about 1.75 mm (79.7 mil²); 2.30 A at a 10 degC
     rise, a 21.9 degC rise at 3.21 A; FAIL on the long-conductor basis;
   - C103 ground pad and D-56 /GND via notch, x 37.50-38.75: F.Cu only, 2.082 mm over about 1.25 mm (112.9 mil²);
     2.75 A, a 14.3 degC rise at 3.21 A; FAIL on the long-conductor basis;
   - D103 belt, x 31.75-33.25: F.Cu 3.80 mm and In2.Cu 1.80 mm (255.0 mil²); 4.16 A, a 5.6 degC rise at 3.21 A;
     pass;
   - W1 approach, x 31.50: F.Cu 2.249 mm and In2.Cu 2.450 mm (188.5 mil²); 3.56 A, a 7.9 degC rise at 3.21 A; pass.

   The In2.Cu `VCHGOUT_L3_strap` ends at x 36.90, so the two failing necks are on L1 only. The IPC-2152 chart is a
   long-conductor basis. A neck of 1 to 2 mm spreads heat into the wide pour on both sides, so the chart is
   conservative for these necks; however, no short-neck method is on record, so the margin is not quantified. The
   operator chooses one of three options: accept the two short necks; widen the copper at the necks (a routing change,
   followed by DRC, the constraint check and a package re-export before the order); or measure the rise on the bench
   at 3.21 A. Only the second option changes the board. The bench measurement needs an assembled board, so this
   option orders the board as it is and accepts a re-spin if the measured rise exceeds 10 degC. The IPC-2221 rows of `r9_calc_out.txt` now print as
   comparisons; the "-> pass" that earlier followed an IPC-2221 figure was the IPC-2152 verdict.

(**Superseded 2026-11-13:** "these items block the order of the CR bare board"; list items "1. BAV199 D104 to D106:
the SOT-23 pinout comes from a secondary source only (item 9). 2. The IPC-2152 chart reading for the In2 VCHGIN strap
(item 2); the curve fit gives about 30 % width margin. 3. The OSH Park quote and the 4-layer stack-up (items 5 and 7).
The quote input is the D-60 outline area, 2241.6 mm² (bounding box 40.02 x 64.81 mm). 4. The OSH Park policy on
non-functional inner pads at connector holes (item 3)."; "These are the order blockers of `LAYOUT_DECISIONS.md`
section 1: section 11 items 2, 3, 5, 7 and 9. Review 2/2 of the operator is in progress on them.") (**Superseded
2026-11-13:** "section 11 items 2, 3, 5, 7, 9, 14, 16 and 25, and the W6/W7 lead pads of D-45".)

The Review 2/2 session raised two questions that the operator has not answered. The first stays open; the D-62
re-export in `89c2d72` made the second moot:

- The CR fab package README (`fab/cr_2026-11-13/README.md`, section 1) gives a quantity of 5, but OSH Park sells
  boards in multiples of 3. Amended 2026-11-13: the package README as re-exported in `89c2d72` still gives a quantity
  of 5, and its OSH Park row now states that order quantities come in multiples of 3. The question stays open.
- Amended 2026-11-13: moot. The D-62 re-export in `89c2d72` replaced the OSH Park row of that README; the row now
  states the confirmed 4-layer stack-up (1.6 mm, 1 oz outer / 0.5 oz inner clad, ENIG, FR408-HR), which matches
  section 1 of that README. (**Superseded 2026-11-13:** "The OSH Park row of that README says that a 4-layer order at
  OSH Park "uses the 1 oz fallback of the Copper row above". The OSH Park 4-layer stack-up already is 1 oz outer and
  0.5 oz inner, which is the D-29 copper of the Copper row, so the sentence is stale.")

(**Superseded 2026-11-13:** "Both stay open, and no file is changed".)

The figures in this section are those of the D-62 board (`89c2d72`; outline 2327.7 mm², DRC 0, constraint check
109 pass, D-20 stitching 3.51 mm; fab package re-exported; `LAYOUT_DECISIONS.md` D-62). (**Superseded 2026-11-13,
D-62:** "A further outline trim, D-62 ..., is committed in `89c2d72` ...; its design record is pending, and the D-61
figures in this section are superseded by it.") (**Superseded 2026-11-13:** "is in progress and not committed. The
figures in this section are those of the committed D-61 board.")

The D-20 L2-L4 GND stitching is not an order blocker: on the D-62 board, the largest distance over the filled L4 pour
to the nearest of the 306 stitch points is 3.51 mm at (43.0, 44.8), against the 3.54 mm limit for a 5 mm square pitch
(`cr/constraint_check.md`). (**Superseded 2026-11-13, D-62:** "on the D-61 board, the largest distance over the
filled L4 pour to the nearest of the 296 stitch points is 3.47 mm, against the 3.54 mm limit for a 5 mm square pitch
(routing request R9-03, closed by the D-61 gap fill)".)

Three former items of this list are closed by operator ruling 2026-11-13 (Review 1/2: J102, J1-TSW, W6-W7 (connector
and lead-pad geometry), local_923ffa1c-f985-43ad-8510-7faea2e5f5d7, chat 2026-11-13):

- J102 (J-TAP), items 16 (the header half) and 25. The header is Molex 43045-1012 ("That was a typo, I meant
  43045-1012"). The Molex 43045 PCB layout matches the footprint (1.02 mm holes and pegs, 3.00 mm grid, pegs at
  (-3, 3.94) and (15, 3.94)). The footprint is the drawing rotated 180 degrees, not mirrored, so the D-46 cavity map
  is physically correct. The latch is on the peg edge, facing +x. On the D-61 board the latch nub is at about MB x
  53.5-54.9, y 25.3-26.7; the trimmed edge is about 3.6 mm past it, R175 about 3 mm toward -y and MH3 about 14 mm
  toward -y. The operator ruled this sufficient: "That is enough room". On the D-62 board the +x edge runs straight
  at x 58.60 from y 10.73 to y 71.04; the edge at x 58.60 is about 3.7 mm past the nub +x end (x 54.9), and the
  operator's ruling was given on the D-61 figure of about 3.6 mm. J102, R175 and MH3 do not move.
- CR J1 (TSW-110/112-07-L-S), item 14. The 1.1 mm drill is kept ("Keep 1.1 mm"), and the 1.9 mm pad and the
  D-41 stack of 11.05 mm are confirmed ("Confirm both"; operator confirmation of the D-41 record, not checked against
  a Samtec print). The Samtec layout gives a 1.02 mm hole without tolerance; the 0.08 mm excess is kept on purpose for plug-in alignment.
  The OSH Park drilled-versus-finished question stays with item 5. The footprint description still reads "pad/drill
  PLACEHOLDER"; it changes only at the next footprint-library regeneration.
- W6 and W7 lead pads (D-45). The 1.0 mm hole, 1.8 mm pad and 2.54 mm pitch are kept and the placeholder status is
  closed ("Approve, close it"). The footprint names keep the `_Placeholder` suffix.

(**Superseded 2026-11-13:** list items "1. J102 (J-TAP, Molex 43045): header P/N, pegs, pin numbering and latch side
against the Molex drawing (items 16 and 25). 2. CR J1 (TSW-110/112-07-L-S): the placeholder pad and drill, 1.9 mm pad
and 1.1 mm drill (item 14). 3. W6 and W7 lead pads: the placeholder geometry, 1.0 mm hole, 1.8 mm pad, 2.54 mm pitch
(D-45)."; "The D-46 J-TAP latch finger access stays open and is not on this list. It is now relevant to the trimmed
board: MH3 and R175 are on the +x/-y side of J102.")

The following items do not block the bare-board order; they belong to the parts order and the assembly. (**Superseded
2026-11-13:** "A wrong drill or pitch on items 1 to 3 cannot be repaired on a fabricated board.")

- every SKU, price, stock figure and MOQ of the ordering BOM (`bom_2026-11-11/README.md` section 7);
- the T-A-05 datasheet checks for D103, D107, J101, J201 and W5;
- the DC bias of C102a and C102b, the C101 Murata part and the BSS84 VGS(th);
- the U101 window-pane stencil apertures (item 22);
- the wire gauge and insulation of the Molex 2147561101 cable, TODO(verify: Molex 2147561101) (Micro-Fit 3.0
  female-to-pigtail, dual row, 10 circuits, 150 mm, confirmed on the Molex page) (**Superseded 2026-11-13:** "the Molex
  2147581101 cable details");
- the W1/W2 stranding ruling;
- the four-powered-pin derating of the TSW/SSQ pair (item 15);
- the W3/W4 1.5 mm hole against the Alpha 5857 conductor diameter;
- the workshop and consumable BOM items.

Two section 11 items are closed by verification. Item 18 (SN74LVC1G11DBVR DBV pinout): TI SCES487I (revision November
2024) Figure 4-1 and Table 4-1 give one pinout for the DBV and DCK packages (A 1, GND 2, B 3, Y 4, VCC 5, C 6), and the
U107 copper matches it (pad 1 /QUAL, 2 /GND, 3 /FCCN, 4 /QF, 5 /3V3, 6 /P5N). Item 24 (TODO(calc: B.6 9-10 short)) is
closed in substance by r9-12 ruling R2: with R132 and R131B at 4.99 kOhm, the short current is at most 0.687 mA and
the rail stays at 3.024 V or more (D-49, r9-12 bullet).

## 4. How to run (plug-on CR, 2026-11-13)

From `hardware/charger_evm_r8` in Git Bash (set `MSYS_NO_PATHCONV=1`, or net names such as `/GND` become paths).
`$PY` is the pcbnew venv Python (path below). The sequence below built the 2026-11-13 board, the D-62 board included
(D-61 finish order: route, plane vias, trim, stitching vias, straightening, stitching gap fill, references; D-62 trims
the routed board `621fb28` to the D-62 outline in step 5 and adds `gen/sync_fields.py` in step 9). (**Superseded
2026-11-13, D-62:** "trimmed, stitched and straightened board included".)
(**Superseded 2026-11-13, D-61:** "The sequence below built the 2026-11-13 board, trimmed board included."; the D-60
sequence had eight steps; the stitching, straightening and gap-fill steps 6 to 8 are new; the old steps 6 to 8 are
now 9 to 11.)
(**Superseded 2026-11-13, D-60:** "The sequence below built the 2026-11-13 board."; the sequence had seven steps and
no outline trim, step 5 is new, and the old steps 5 to 7 are now 6 to 8.)

1. Placement: run the placement half of `gen/make_board.sh`, that is `cd gen && "$PY" pcbbuild.py cr ../cr`, then from
   `hardware/charger_evm_r8` copy `../../tools/pcb/fab_rules/fab_4layer_oshpark_only.kicad_dru` to
   `cr/cr.kicad_dru`, run `"$PY" ../../tools/pcb/fab_rules/apply_board_setup.py cr/cr.kicad_pcb`, the inline step that
   sets the OSH Park minimums and the 0.1524 mm Default net class, and `"$PY" gen/silk_fix.py cr/cr.kicad_pcb`.
   A full `bash gen/make_board.sh cr` also regenerates the libraries, the schematic, ERC and the netlist; it rewrites
   the `cr/cr.net` date line and 13 library files (stamp-only), so restore those files from git afterwards.
2. Power copper and pours: `cd gen && ROUTE_SKIP_FR=1 "$PY" route.py cr ../cr`. Without `ROUTE_SKIP_FR=1`,
   `route.py` runs Freerouting into the live board.
3. **Pitfall after step 2:** `route.py` resets the board minimums in `cr/cr.kicad_pro` (hole clearance 0.25 mm instead
   of 0.254 mm), so its zone fill leaves the J102 NPTH pegs 0.2505 mm from the GND pours (six DRC items). Restore
   `cr/cr.kicad_pro` from git and refill the zones with the board loaded as `cr/cr.kicad_pcb` (D-57 verification note).
4. Signal routing: the corridor router in `tools/pcb/corridor_route/`, run by the `board-routing` skill (board model,
   `seeds.py run`, `apply_routes.py`, `plane_vias.py`, `score.py`). D-58 used plan softum, seed 1; the plan file
   (`plan_softum.json`) and the per-seed tables are in the routing session's notes (`routing_r9_cr/`). Since tools
   commit `114ad04`, plan softu at the default 0.05 mm mask margin gives the same via ban; a board model built before
   `114ad04` needs a rebuild. Use `plane_vias.py` for plane vias, not `gen/finish.sh` (section 8).
5. Outline trim and holes: `"$PY" gen/trim_cr.py <work dir>` on the routed board (D-60, D-62). The script applies
   `FINAL_OUTLINE`, `KEY_EAR` and `MOUNTING_HOLES` of `gen/cr_geometry.py` through
   `tools/pcb/corridor_route/trim_outline.py`, with `--angles`, `--min-edge` and `--fillet` from `TRIM_ANGLES`,
   `TRIM_MIN_EDGE` and `FILLET` (D-62). It refuses when the result differs from that data by more than 0.01 mm.
   The work dir receives the tool output. The script copies the trimmed board back over `cr/cr.kicad_pcb`; it does not
   change `cr/cr.kicad_pro`. `--check-only` checks without applying. Run it after step 4 and before step 6, because
   the stitching vias, the straightening pass, the gap fill and the reference placement depend on the final edge and
   holes. The script refuses a board that is already trimmed, so rebuild from the routed, untrimmed board.
   (**Superseded 2026-11-13, D-61:** "Run it after step 4 and before step 6, because the reference placement depends
   on the final edge and holes.")
6. GND stitching vias: `"$PY" ../../tools/pcb/corridor_route/plane_vias.py <model> <plan> <routes> cr/cr.kicad_pcb
   <out routes> --stitch 2.5` on the trimmed board (D-61; the routing session holds the model, plan and routes files).
   It places /GND stitching vias on a 2.5 mm grid inside the trimmed GND fill and applies the plane-via site rules
   (routed copper, holes, SMD pads and mask openings, unflashed pads, keep-outs). The script writes a routes file, not
   a board; `"$PY" ../../tools/pcb/corridor_route/apply_routes.py cr/cr.kicad_pcb <out routes> <out dir>` writes
   the board as `<out dir>/cr.kicad_pcb` (zones refilled). Copy the output board back over `cr/cr.kicad_pcb` before
   the next step. On the routed CR, this step replaces `route.py stitch()` of the generator. Do not run both on one
   board. Keep `ROUTE_SKIP_FR=1` in step 2: that build skips `route.py stitch()`.
7. Straightening: `"$PY" ../../tools/pcb/corridor_route/straighten.py cr/cr.kicad_pcb <out dir>` (D-61) replaces
   staircase runs of unlocked signal tracks by straight or 45-degree runs. Vias, pads and locked pre-tracks do not
   move. The script writes `<out dir>/cr.kicad_pcb`. Copy the output board back over `cr/cr.kicad_pcb` before the
   next step.
8. Stitching gap fill: `"$PY" ../../tools/pcb/corridor_route/stitch_gaps.py cr/cr.kicad_pcb <out dir>
   --y-flip-offset 100` (D-61). While a point of the filled L4 /GND pour lies more than 3.54 mm from a /GND via or /GND plated hole, the
   script adds a /GND via at the nearest legal site to the worst point. The script writes `<out dir>/cr.kicad_pcb`
   (zones refilled) and `<out dir>/STITCH_GAPS.md` (the current record is `cr/stitch_gaps.md`: 3 vias added). Copy
   the output board back over `cr/cr.kicad_pcb` before the next step.
9. Reference designators: `"$PY" gen/silk_refs.py cr/cr.kicad_pcb cr/silk_refs.md` (D-59, re-run after D-60, D-61
   and D-62). On a board routed before the Review 1/2 part-number change, such as `621fb28`, then run
   `"$PY" gen/sync_fields.py cr/cr.kicad_pcb cr/cr.net`; it copies the MPN and Note fields of the netlist onto the
   footprints and changes no geometry (D-62). These are the last steps on the board. (**Superseded 2026-11-13,
   D-62:** "(D-59, re-run after D-60 and D-61). This step runs last on the board.")
10. Checks: `cd gen && "$PY" check_constraints.py cr ../cr > ../cr/constraint_check.md` (the script prints to stdout),
    and `kicad-cli pcb drc --severity-all --schematic-parity` on `cr/cr.kicad_pcb`. The constraint check includes
    the D-20 stitching row (D-61); on the current board it passes at 3.51 mm against 3.54 mm. (**Superseded
    2026-11-13, D-62:** "passes at 3.47 mm", the D-61 board.)
11. Fab package, once DRC is clean: `bash gen/export.sh cr <date>`, then `"$PY" gen/fab_readme.py cr <date>
    [<reference package dir>]`. `export.sh` runs ERC and DRC first and writes the package only from a board that
    passes both.

(**Superseded 2026-11-13:** the r7-outline sequence "`bash gen/make_board.sh cr` ...; `ROUTE_SKIP_FR=1 route.py cr
../cr` ...; copy the result to `cr/cr_pours.kicad_pcb`; `PF_ITERS=60 bash gen/route_cr_pf.sh` (PathFinder, finishing
router, stitching); `bash gen/export.sh cr 2026-11-11` and `python gen/fab_readme.py cr 2026-11-11`". PathFinder and
`gen/route_cr_pf.sh` are not used on the plug-on CR.)

The venv is `C:\Life Ops\School\Thesis\DC-Balancer-round4\tools\pcb\.venv\Scripts\python.exe` (pcbnew, kiutils, shapely).
Every pcbnew script calls `wx.DisableAsserts()`: a KiCad debug assert otherwise opens a modal dialog that blocks an
unattended run. On the r7 outline (history), `pathfinder.py` wrote a `conflict_report` (net, cells, sample positions in the KiCad frame).

## 5. Routing results on the r7 outline (history)

See `LAYOUT_DECISIONS.md` section 8. The best trajectory is PathFinder on the 0.05 mm grid with tiers 1-2: 73 nets in
conflict at iteration 0, 29 at iteration 11, 30-35 at iterations 12-15 (stopped). The 0.1 mm grid plateaus at
about 47-53. Conflicts are spread over the interior; the CR lacks capacity rather than having one choke point.

## 6. Candidate methods for the r7 outline (superseded 2026-11-12)

The new outline and the route-race of D-50 supersede this list. It is kept as a record.

1. DNP tier 3 (applied 2026-11-11), then PathFinder at 0.05 mm with 60+ iterations.
2. PathFinder tuning: slower present-cost growth, larger history increment, 6 mm search window, rip-up of only the conflicting branch.
3. Placement relief: a larger packer routing margin where area allows; tab X series resistors re-sited so fewer nets cross the CHG pin-1..10 wall; U105/U118 back to tab Y with a better tab Y packing (A.8 set).
4. Interactive push-and-shove routing in the KiCad GUI by a person, keeping the scripted placement, pours, rule areas, DRC and exports.
5. Only after these: an operator ruling on a tab X extension or a 6-layer stack (A.7 rejected the obvious outline extensions for non-height reasons).

## 7. Pitfalls found

- Git Bash path conversion turns `/GND` into `C:/Program Files/Git/GND`; set `MSYS_NO_PATHCONV=1`.
- pcbnew `FootprintLoad` returns unwrapped objects after a `PCB_IO_KICAD_SEXPR` instance exists; use kiutils for derived footprints.
- `PCB_VIA::GetWidth()` needs a layer argument in KiCad 9.
- Freerouting ignores the fab copper-to-edge rule; the router keep-out band (`EDGE_BAND`) handles it.
- Fixed power vias must be placement keep-outs (D-33), and the U101 top-edge pins need the +y channel (D-09, r7 outline).
- `mb_bottom_clearance()` covers the whole MB; on the new rectangle it would forbid parts over both boosts. Remove it; do not re-run it (D-17).

## 8. Operator rulings (2026-11-11, after this handoff)

- **Fab.** The CR is built at OSH Park (4-layer: 1 oz outer, 0.5 oz inner). OSH Park does not offer filled and
  capped vias, so via in pad is not available. The D-20 via rule ("no via on an SMD pad or in its mask opening")
  stays in force without exception, J101 included. Rule file: `tools/pcb/fab_rules/fab_4layer_5mil_oshpark_pcbway.kicad_dru`.
- **Superseded 2026-11-12 (D-36):** plain unfilled vias inside SMD pads are acceptable; only filled and capped
  vias are excluded. **Superseded 2026-11-12 (D-37):** no via in an SMD pad first; plain via-in-pad only as a listed
  last resort. **Superseded 2026-11-12 (D-29):** the rule file becomes an OSH Park-only CR file.
- **/3V3.** The choice of tracks, a fill or a rail for /3V3 belongs to the PCB design session that orchestrates the
  routing attempts. On the new outline L4 is solid GND (D-20), so /3V3 runs on L1 or L3.
- **Routing skills.** `route-race` and `board-routing` (`.claude/skills/`) and the tools in `tools/pcb/corridor_route/`
  are merged to main. `tools/pcb/corridor_route/reference/design-intake.md` describes the change-request intake.
  The routing study measured 42, 39, 40, 39 open connections of 210 at seeds 1 to 4 on a copy of commit 71ecdef
  under D-20; with tier 3 DNP and /3V3 held out, 20 to 23 (r7 outline). The U101 +x pocket has one F.Cu lane for
  /N_UV, /N_OV and /N_DVDT; relief needs R105 about 0.3 mm and R101 about 0.6 mm further in +y, with the /N_UV via out
  of the lane (r7 outline; the pocket is re-derived on the new outline, D-09).
- **Finishing scripts.** In a scratch test, `gen/finish.sh` ripped up routed nets and added DRC violations on the
  corridor router's output. Use `tools/pcb/corridor_route/plane_vias.py` for plane vias with that router.
