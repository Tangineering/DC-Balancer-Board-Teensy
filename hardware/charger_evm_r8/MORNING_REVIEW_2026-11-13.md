# Charger EVM r9: overnight review (2026-11-12 to 2026-11-13)

This document records the overnight work that took the CR from a frozen netlist to a routed board and a fabrication
package, and lists the decisions and open items that the operator should review. It also records the D-60 outline
trim and the four 6-32 holes added on 2026-11-13 after the overnight round, and the package re-export that followed.
The D-61 /GND stitching vias, stitching gap fill and straightened tracks, added on operator requests of 2026-11-13,
and the package re-export from that board are recorded as well. The D-62 outline (edges at limited angles and 1.0 mm
fillets, operator ruling 2026-11-13), the D-61 finish re-run on that outline and the package re-export from the D-62
board are recorded last; the D-62 board is the current board. The VCHGOUT current check of R9.H26 found two short
necks below the IPC-2152 basis; operator ruling 2026-11-13 accepts them as they are (section 3.1 item 5), so no
operator-review item blocks the bare-board order. (**Superseded 2026-11-13, VCHGOUT ruling:** "which found two short
necks below the IPC-2152 basis, is the new open item for the operator (section 3.1 item 5)".)
`LAYOUT_DECISIONS.md` (D-53 to D-62) is the full design record. Nothing was ordered, no firmware was changed, and
nothing was pushed. (**Superseded 2026-11-13, D-62:** "`LAYOUT_DECISIONS.md` (D-53 to D-61) is the full design
record".)

## 1. Result

The CR (`cr/cr.kicad_pcb`, branch `charger-evm-round4` at `89c2d72`) is placed, poured and routed (D-58), trimmed to
its final outline (D-62, which redoes the D-60 trim), stitched to /GND and straightened (the D-61 finish order, re-run
on the D-62 outline). Table 1 gives the check results on the D-62 board. All rows of the constraint check pass: 0 FAIL
rows, with the three exemption rows of Table 1. The VCHGOUT current check (R9.H26) is a calculation outside the
constraint check; two of its necks fail on the long-conductor IPC-2152 basis, and operator ruling 2026-11-13 accepts
them as they are (section 3.1 item 5). (**Superseded 2026-11-13, VCHGOUT ruling:** "and the operator rules on them".)
(**Superseded 2026-11-13, D-62:** "The CR (`cr/cr.kicad_pcb`, branch `charger-evm-round4` at `437d2d7`)
is placed, poured, routed, trimmed to its final outline (D-60), stitched to /GND and straightened (D-61). Table 1
gives the check results on the final board. All checks pass"; "A further outline trim, D-62 ... is committed in
`89c2d72` with its finish re-run and the fab package re-export; its design record is pending. Table 1 gives the D-61
checks, which the D-62 re-run supersedes".) (**Superseded
2026-11-13:** "is in progress and not committed; Table 1 describes the committed D-61 board".) (**Superseded
2026-11-13:** "The CR
(`cr/cr.kicad_pcb`, branch `charger-evm-round4` at `779c419`) is placed, poured, routed and trimmed to its final
outline (D-60)."; "The CR (`cr/cr.kicad_pcb`, branch `charger-evm-round4` at `cb1def6`) is placed, poured and routed.")

Table 1. Checks on the final CR board (D-62).

| Check | Result |
|---|---|
| ERC | 0 messages |
| DRC (`--severity-all --schematic-parity`) | 0 violations, 0 unconnected items, 0 parity issues |
| Constraint check (`cr/constraint_check.md`) | 109 pass, 0 FAIL, 3 exemption rows: 2 listed exemptions (R103, R129) and 1 D-20 exemption (R102); rows check the D-62 outline (edge angles, minimum slanted edge, fillet arcs), the D-60 key ear (against the corners before the fillets) and holes, the D-41 key and the D-20 stitching (D-61) (**Superseded 2026-11-13:** "98 pass"; "108 pass, 0 FAIL"; **Superseded 2026-11-13, D-62:** "rows check the D-60 outline, key ear and holes and the D-20 stitching (D-61)") |
| D-20 L2-L4 GND stitching (D-61 order, D-62 board) | pass: 306 stitch points (/GND vias and /GND plated holes); the largest distance to the nearest one over the filled L4 pour is 3.51 mm at (43.0, 44.8), against 3.54 mm for a 5 mm square pitch; the stitching gap fill (`stitch_gaps.py`) added 3 /GND vias at (36.04, 26.88), (34.29, 33.53) and (33.54, 59.53); its report (0.50 mm samples, `cr/stitch_gaps.md`) gives 4.19 mm before and 3.52 mm after, and the constraint-check row is the measure of record (**Superseded 2026-11-13, D-62:** "296 stitch points ... 3.47 mm at (31.0, 34.7) ... added 3 /GND vias at (36.04, 26.87), (34.34, 33.62) and (34.04, 59.52) after the grid stitching left a 4.08 mm gap at (36.0, 26.7) (request R9-03, closed)", the D-61 board) |
| Routing | 107 of 107 connections; 148 router vias; 288 /GND vias, of which 279 are grid stitching vias and 3 are gap-fill vias (D-62 re-run of the D-61 finish); 824.5 mm of track in 769 segments after straightening (1791 segments and 830.8 mm before); every track 0.1524 mm; vias 0.6 / 0.3 mm only (**Superseded 2026-11-13:** "830.8 mm of track"; **Superseded 2026-11-13, D-62:** "278 /GND vias, of which 269 are grid stitching vias"; "823.9 mm of track in 768 segments", the D-61 board) |
| Vias on SMD pads | 0 (D-37 row "none"); the smallest annulus gap to a pad plus its mask opening is 0.027 mm |
| Outline and holes (D-62, holes D-60) | 10 corners before the fillets, edges at 0, 30, 45, 60, 90, 120, 135 or 150 degrees, every slanted edge at least 2.0 mm long, 1.0 mm fillets drawn as Edge.Cuts arcs; inside the D-39 rectangle; filleted area 2327.7 mm2 (55 % of the 4212.2 mm2 rectangle); bounding box 40.02 x 64.81 mm, MB frame x 18.584-58.60, y 7.83-72.64; the -x vertices sit on x 18.584; four NPTH 3.70 mm holes (6-32 free fit) MH1 to MH4, each with an all-layer copper keep-out of radius 4.0 mm; MH1 (26.23, 69.04), MH2 (54.85, 68.79), MH3 (54.85, 11.43), MH4 (24.48, 25.18), MB frame, each keeping a 3.6 mm head disc on the board; a CR rotated 180 degrees lands on J-BL (7.73 mm of x overlap) and J-FC (7.73 mm), so the D-41 key holds (**Superseded 2026-11-13, D-62:** "convex 18-vertex outline inside the D-39 rectangle, 2241.6 mm2 (was 4212.2 mm2, 53 %) ... x 18.58-58.60"; "MH2 (54.85, 63.79)"; "J-FC (7.63 mm)", the D-60 outline) |
| Divider-top rule (A.8) | same-layer metric 0.00 mm; 0.7 mm of logic track and 1 logic via (the /CE_DRV_J escape) in the zone (D-58 router score) |
| VCHGIN In2 strap (R9.H25) | minimum section 4.174 mm against 3.221 mm required; 2.75 A at a 10 degC rise against 2.41 A |
| VCHGOUT path, U101 OUT to W1 (R9.H26) | accepted by operator ruling 2026-11-13, "Accept short necks" (section 3.1 item 5); the acceptance rests on the ruling, not on a pass. At the 3.21 A basis, 10 degC rise, 35 um outer copper (clad only), IPC-2152 needs 2.828 mm on F.Cu alone; two F.Cu-only necks fail on the long-conductor basis (1.469 mm: 2.30 A, 21.9 degC at 3.21 A; 2.082 mm: 2.75 A, 14.3 degC); the D103 belt (4.16 A) and the W1 approach (3.56 A) pass (**Superseded 2026-11-13, VCHGOUT ruling:** "open for the operator (section 3.1 item 5)") |
| Fabrication package | `fab/cr_2026-11-13/`, re-exported from the D-62 board in `89c2d72`, not ordered; the size row of its README describes the D-62 outline (**Superseded 2026-11-13:** "re-exported from the trimmed board in `779c419`"; **Superseded 2026-11-13, D-62:** "re-exported from the stitched, gap-filled and straightened board in `437d2d7`"); the figures `figures/cr_routed_2026-11-13/` were re-exported from the same board; the NPTH drill file has tool T2 3.70 mm; the EIB package is `fab/eib_2026-11-13/` |

At `89c2d72` the branch is 62 commits ahead of `main`, and `main` is an ancestor of the branch. Each later commit adds
one more. To get the current count, run `git rev-list --count main..charger-evm-round4`. (**Superseded 2026-11-13:**
"With this review committed, the branch is 34 commits ahead of `main`"; "At `779c419` the branch is 45 commits ahead of
`main`"; "At `437d2d7` the branch is 53 commits ahead of `main`".) To bring `main` level, run this command in the
primary checkout:

```bash
git merge --ff-only charger-evm-round4
```

## 2. Decisions to review

Table 2 lists the decisions of this round. Rows 1 to 5 and 7 are design-owner defaults that the operator may reverse.
Row 6 (D-60) implements operator rulings of 2026-11-13, row 8 (D-61) implements operator requests of 2026-11-13, and
row 9 (D-62) implements an operator ruling of 2026-11-13. The last column gives the reversal path. (**Superseded
2026-11-13, D-62:** "Row 6 (D-60) implements operator rulings of 2026-11-13, and row 8 (D-61) implements operator
requests of 2026-11-13.")

Table 2. Decisions of the overnight round, D-60, D-61 and D-62.

| # | Decision | Basis | Reversal |
|---|---|---|---|
| 1 | D-54: CR placement variant B (`LAYOUT_VARIANT` default `B`) | a two-seed routability probe of both variants on the same plain plan | `LAYOUT_VARIANT=A`; the variant-A record in `cr/variants_r9/A/` predates the D-55 fixes and would need a re-run |
| 2 | D-55 and D-56: every finding of the two placement reviews applied (U101 network in the +x pocket, paste window panes, In2 VCHGIN strap widened, C103 ground via, pour seal removed) | `cr/placement_review_r9.md`, `cr/placement_review_r9b.md` | revert `8b68044` and `86cd19d` |
| 3 | D-57: a /GND via at (42.30, 59.30) for C102c pad 2, with a strap extension under R102 | the route race found C102c.2 open at every seed of every plan; the via changes no placement and no signal route | revert `0e7f22b`; C102c.2 is then open again |
| 4 | D-58: routing by plan softum (soft divider-top zones, via cost 200 on four U101 high-impedance nets, mask margin 0.075 mm), seed 1 | best of four seeds; all four seeds routed 107 of 107 | re-route from `0e7f22b` with another plan; the plans are in the routing session's notes |
| 5 | D-59: reference designators re-placed by `gen/silk_refs.py`; 18 references on F.Fab only after the D-62 re-placement (C110 is back on the silkscreen) (**Superseded 2026-11-13:** "18 references on F.Fab only", the D-59 count; **Superseded 2026-11-13, D-62:** "19 references on F.Fab only after the D-60 re-placement (C110 added)") | the 124 silkscreen DRC items blocked `gen/export.sh` | restore the fields from `621fb28`, or move every small-part reference to F.Fab (D-12a as first written); on the trimmed board, re-run DRC afterwards, because restored fields can fall off the trimmed edge or over a hole mask opening |
| 6 | D-60: after routing, the CR is trimmed to a convex 18-vertex outline (2241.6 mm2) inside the D-39 rectangle, with a +x key ear and four 6-32 holes (MH1 to MH4) for a 3D-printed support; made by the design owner in the generator (`gen/cr_geometry.py`, `gen/trim_cr.py`). Amended by D-62 (row 9): the outline and MH2 are replaced; the D-60 values are history | operator rulings of 2026-11-13, relayed by the routing session (route-race change request R9-02): trim the unused area, a non-rectangular outline is acceptable, holes in the corners for 6-32 screws; no part, track or via moved | restore `cr/cr.kicad_pcb` from the D-59 commit `6ae73df` and run `gen/silk_refs.py` and `gen/export.sh` again, or change `FINAL_OUTLINE`, `KEY_EAR` or `MOUNTING_HOLES` and run `gen/trim_cr.py` on the routed board |
| 7 | KiKit JLCPCB and PCBWay assembly presets left failing for the CR | the CR fab is OSH Park (bare board); the package README states the failure | fix the reference parse in KiKit's input (likely the suffixed references such as R131B and C102a) |
| 8 | D-61: the finish order of the routed CR is route, plane vias, `gen/trim_cr.py`, /GND stitching vias on a 2.5 mm grid inside the trimmed fill (`tools/pcb/corridor_route/plane_vias.py --stitch 2.5`), `straighten.py`, the stitching gap fill (`tools/pcb/corridor_route/stitch_gaps.py <board> <out dir> --y-flip-offset 100`), then `gen/silk_refs.py`; the router's stitching replaces `route.py stitch()` (never both on one board), and `gen/trim_cr.py` refuses an already-trimmed board; the board is the routing session's `07a6181`, merged as `b8e3762`, with the 3 gap-fill vias added in `437d2d7`; the D-60 outline and holes do not change. Amended by D-62 (row 9): the same finish order was re-run on the D-62 outline, and the D-61 board values are history | operator requests of 2026-11-13, relayed by the routing session; the D-58 to D-60 board had only 6 /GND vias, because the `ROUTE_SKIP_FR=1` build skips `route.py stitch()`, so D-20 (L4 stitched to L2 at a pitch of at most 5 mm) was not met and no check measured it | restore `cr/cr.kicad_pcb` from `779c419` and run `gen/export.sh` and `gen/fab_readme.py` again; the D-20 stitching row then fails with 6 /GND vias |
| 9 | D-62: the D-60 trim is redone with every outline edge at 0, 30, 45, 60, 90, 120, 135 or 150 degrees (`TRIM_ANGLES`), every slanted edge at least 2.0 mm long (`TRIM_MIN_EDGE`) and a 1.0 mm fillet drawn as an Edge.Cuts arc at every corner (`FILLET`); `FINAL_OUTLINE` has 10 corners before the fillets, filleted area 2327.7 mm2, bounding box 40.02 x 64.81 mm unchanged; MH2 moves to (54.85, 68.79), the other holes do not move; `gen/trim_cr.py` passes `--angles`, `--min-edge` and `--fillet` and reproduces the outline from the routed board `621fb28`; `gen/silk_refs.py` and `gen/check_constraints.py` read the filleted outline; the routing session re-ran the D-61 finish on the trimmed board (279 grid stitching vias, 769 segments and 824.5 mm after straightening, 3 gap-fill vias), then `gen/silk_refs.py` (60 references on silk, 18 on F.Fab only) and `gen/sync_fields.py` (J102 43045-1012, cable 2147561101) ran; ERC 0, DRC 0 / 0 / 0, constraint check 109 pass and 0 FAIL, D-20 stitching 3.51 mm; package and figures re-exported in `89c2d72` | operator ruling of 2026-11-13 to the routing session (route-race change request R9-04): "Keep the trim rectilinear, or with 30, 45, or 60deg angles. Fillets on corners is good though." The operator noted that a fab charges for the enclosing rectangle, so trimming is generally unnecessary, and that more exposed MB area underneath is a small benefit. D-62 does not change the enclosing rectangle (40.02 x 64.81 mm); no part, track or via moved in the trim | restore `cr/cr.kicad_pcb` and the `gen/cr_geometry.py` outline and hole data of the D-61 board (`437d2d7`, lineage `b8e3762`) and run `gen/export.sh` and `gen/fab_readme.py` again |

## 3. Items that need the operator

### 3.1 Before the order

1. Review the reference-designator result of D-59, as re-placed after the D-62 trim. 60 of 78 references are on the
   silkscreen, 27 of them over another courtyard and hidden after assembly. These 18 references are on F.Fab only:
   C107, C115, C130, C132, D105, D106, R122, R130, R131B, R147, R184 to R189, U110 and W3; C110 is back on the
   silkscreen. (**Superseded 2026-11-13:** "60 of 78 references are on the silkscreen, 26 of them over another part";
   "These 18 references", the D-59 result.) (**Superseded 2026-11-13, D-62:** "as re-placed after the D-60 trim. 59 of
   78 references are on the silkscreen ... These 19 references are on F.Fab only: C107, C110, ...".)
   In the dense rows a reference can sit up to 3.0 mm from its part, so the interactive BOM (`assembly/cr_ibom.html`)
   is the assembly reference. The alternative is all small-part references on F.Fab, which gives a cleaner silkscreen
   and the same assembly method.
2. Closed 2026-11-13: the placeholder footprints of J102, CR J1 and W6/W7, by operator ruling 2026-11-13 (Review 1/2:
   J102, J1-TSW, W6-W7 (connector and lead-pad geometry), local_923ffa1c-f985-43ad-8510-7faea2e5f5d7, chat
   2026-11-13).
   - J102 (`LAYOUT_DECISIONS.md` section 11 items 16 (the header half) and 25): the header is Molex 43045-1012 ("That was a typo, I meant
     43045-1012"). The Molex 43045 PCB layout matches the footprint: 1.02 mm holes and pegs, 3.00 mm pitch and row
     spacing, pegs 3.00 mm outboard of the end columns and 0.94 mm beyond the last-circuit row. The footprint is the
     drawing rotated 180 degrees, not mirrored, so the D-46 cavity map is physically correct. The latch is on the peg
     edge, facing +x; the operator ruled the finger access sufficient ("That is enough room"). The cable is Molex
     2147561101 ("(A). 2147561101 is the correct cable and is in stock at Digikey"). Its wire gauge and insulation stay
     open as a parts check.
   - CR J1 TSW-110/112-07-L-S (item 14): the 1.1 mm drill is kept ("Keep 1.1 mm"), and the 1.9 mm pad
     and the D-41 stack of 11.05 mm are confirmed ("Confirm both"; operator confirmation of the D-41 record, not
     checked against a Samtec print). The Samtec layout gives a 1.02 mm hole; the 0.08 mm excess is kept on purpose for plug-in alignment. The OSH Park
     drilled-versus-finished question stays with item 5.
   - W6/W7 lead pads (D-45): the 1.0 mm hole, 1.8 mm pad and 2.54 mm pitch are kept, and the placeholder status is
     closed ("Approve, close it"). The footprint names keep the `_Placeholder` suffix.

   (**Superseded 2026-11-13:** "Confirm the placeholder footprints against their drawings before the order. The J-TAP
   header (Molex 43045, items 16 and 25 of `LAYOUT_DECISIONS.md` section 11), the TSW-110/112-07-L-S pins (item 14)
   and the W6/W7 lead pads (D-45) use placeholder pad and drill geometry. ... The D-46 J-TAP latch finger access stays
   open".)
3. Closed 2026-11-13: the OSH Park solder-mask expansion of 0.0508 mm (the TODO(verify) in the rule file is closed),
   by operator ruling 2026-11-13 (Review 2/2: BAV199, strap, OSH Park (fab checks),
   local_6e36c3a4-f328-44cd-8c31-05ea2fa7bfa3, chat 2026-11-13). Operator: "Yes". The OSH Park KiCad design-rules
   page gives "Solder Mask Expansion should usually be set to 2mil (0.0508mm)". The OSH Park 4-layer page gives a
   maximum mask alignment error of 3 mil (0.0762 mm) and a minimum mask web of 4 mil (0.1016 mm), which is the board
   setting. The 0.027 mm via-to-mask-opening gap of Table 1 is between a pad and its own same-net escape via, so a
   registration error can at most let solder wick onto that via. The smallest different-net gap is 0.115 mm (C116.1
   /3V3 to a /QUAL via), about 0.094 mm with square-cornered openings, which is larger than the 0.0762 mm alignment
   error. (**Superseded 2026-11-13:** "Confirm the OSH Park solder-mask expansion (0.0508 mm, TODO(verify) in the rule file)."; "a
   registration error exposes part of a via annulus next to a pad of another net".)
4. Closed 2026-11-13: the 4-layer stack-up (section 11 item 5), and the quote (section 11 item 7) as outside the
   scope of the project, by operator ruling 2026-11-13 (Review 2/2). Operator, on the stack-up: "Yes"; on the quote:
   "Quote is outside the scope of the project". The OSH Park 4-layer page (`docs.oshpark.com/services/four-layer/`,
   read 2026-11-13) gives 63 mil (1.6 mm), 1 oz outer copper (clad and plated), 0.5 oz inner copper, FR408-HR at
   190 degC Tg, ENIG, purple SMOBC on both sides, and via tenting "Yes (filled hole and flat surface not
   guaranteed)"; the alternate-stack-up notices are commented out in the page source, so none is active.
   (**Superseded 2026-11-13:** "Confirm the quote and the 4-layer stack-up (section 11 items 5 and 7). The quote input
   is the trimmed outline area, 2241.6 mm2.")
5. Closed 2026-11-13 by acceptance: the two short F.Cu-only necks on the VCHGOUT path from U101 OUT to W1 (U101 OUT
   pins to C103, x 39.25-41.00; C103 ground pad and D-56 /GND via notch, x 37.50-38.75) (the VCHGOUT half of
   `LAYOUT_DECISIONS.md` section 11 item 2, which Review 2/2 kept open). Operator ruling 2026-11-13 (design session,
   chat 2026-11-13), asked "How should the two short VCHGOUT necks be handled?" with the options accept, widen and
   measure on the bench: "Accept short necks". The two necks stay as they are (1.469 mm over about 1.75 mm, a
   21.9 degC rise at 3.21 A; 2.082 mm over about 1.25 mm, 14.3 degC), and the board does not change. The
   long-conductor chart is expected to be conservative for necks this short, because heat spreads into the wider pour;
   however, no short-neck calculation is on record, so the acceptance rests on the ruling, not on a pass. (**Superseded
   2026-11-13, VCHGOUT ruling:** "Open, new 2026-11-13: rule on the two short F.Cu-only necks".) Calculation R9.H26
   (`docs/reviews/charger_eval_2026-11-05/round4/calc/r9_calc.py`, output `r9_calc_out.txt`) uses a 3.21 A basis, a
   10 degC rise and 1 oz outer copper counted as the 35 um clad only (plating not credited). On that basis the
   IPC-2152 baseline fit needs 153.4 mil2, that is 2.828 mm on F.Cu alone. The necks were measured on the D-62 board
   as vertical chords of the filled /VCHGOUT copper, pads not counted. Table 4 gives the result. The In2.Cu
   `VCHGOUT_L3_strap` ends at x 36.90, so the two necks that fail are on L1 only. The IPC-2152 chart is a long-conductor basis. A neck of
   1 to 2 mm spreads heat into the wide pour on both sides, so the chart is expected to be conservative for these
   necks; however, no short-neck method is on record, so the margin is not quantified. (**Superseded 2026-11-13,
   VCHGOUT ruling:** "so the chart is conservative for these necks"; "The operator chooses one of three options:
   accept the two short necks as they are; widen the VCHGOUT copper at the two necks, which is a routing change and
   needs DRC, the constraint check and a package re-export before the order; measure the temperature rise on the
   bench at 3.21 A. Whether this item blocks the bare-board order depends on the option: only the second option
   changes the board. The bench measurement needs an assembled board, so this option orders the board as it is and
   accepts a re-spin if the measured rise exceeds 10 degC.")

Table 4. VCHGOUT necks from U101 OUT to W1 on the D-62 board (R9.H26; IPC-2152, 10 degC rise, 3.21 A basis).

| Neck | Copper section | IPC-2152 current at 10 degC | Rise at 3.21 A | Result on the long-conductor basis |
|---|---|---|---|---|
| U101 OUT pins to C103, x 39.25-41.00 | F.Cu only, 1.469 mm over about 1.75 mm (79.7 mil2) | 2.30 A | 21.9 degC | FAIL |
| C103 ground pad and D-56 /GND via notch, x 37.50-38.75 | F.Cu only, 2.082 mm over about 1.25 mm (112.9 mil2) | 2.75 A | 14.3 degC | FAIL |
| D103 belt, x 31.75-33.25 | F.Cu 3.80 mm + In2.Cu 1.80 mm (255.0 mil2) | 4.16 A | 5.6 degC | pass |
| W1 approach, x 31.50 | F.Cu 2.249 mm + In2.Cu 2.450 mm (188.5 mil2) | 3.56 A | 7.9 degC | pass |

The r9_calc IPC-2221 rows now print as comparisons only. In the earlier output, the "-> pass" after an IPC-2221
figure was the IPC-2152 verdict, not an IPC-2221 result.

The D-20 stitching of D-61, re-run on the D-62 board, is not an order item: its constraint-check row passes (Table 1).
The order blockers of `LAYOUT_DECISIONS.md` section 1, section 11 items 2, 3, 5, 7 and 9, are disposed of by operator
ruling 2026-11-13 (Review 2/2: BAV199, strap, OSH Park (fab checks), local_6e36c3a4-f328-44cd-8c31-05ea2fa7bfa3, chat
2026-11-13), and item 10 (the SOT-23 reflow footprint) is closed with them. The VCHGIN half of item 2 is closed; the
VCHGOUT half is item 5 above and is closed by acceptance. No operator-review item blocks the bare-board order. Section
11 item 3 (non-functional inner pads, checked at submission), the drilled-versus-finished TSW hole question under
section 11 item 5 and the order quantity below stay open and do not block the order. Table 3 gives the disposition of
each item. (**Superseded 2026-11-13, VCHGOUT ruling:** "The VCHGOUT half is item 5 above and stays open. Apart from item
5, no bare-board order blocker remains from the operator review items.") (**Superseded 2026-11-13, R9.H26:** "The D-20
stitching of D-61 is not an order item"; "No bare-board order blocker remains from the operator review items.")
(**Superseded 2026-11-13:** "The order blockers remain those of `LAYOUT_DECISIONS.md` section 1: section 11 items 2, 3,
5, 7 and 9. Review 2/2 of the operator is in progress on them.") Items 14, 16 (the header half) and 25 and the W6/W7
lead pads of D-45 are closed by the operator ruling of 2026-11-13 (Review 1/2; item 2 above). (**Superseded
2026-11-13:** "section 11 items 2, 3, 5, 7, 9, 14, 16 and 25, and the W6/W7 lead pads of D-45".)

Table 3. Disposition of the order blockers by operator ruling 2026-11-13 (Review 2/2; the VCHGOUT row by operator ruling 2026-11-13, design session).

| Item (`LAYOUT_DECISIONS.md` section 11) | Disposition | Operator's words |
|---|---|---|
| 9: BAV199 D104 to D106 pinout | Closed. Nexperia BAV199 product data sheet v.4 (1 April 2023; supersedes v.3 of 2020-09-01, whose only change is "Product changed to non automotive", Table 8), section 5 Table 2: pin 1 A1 (anode, diode 1), pin 2 K2 (cathode, diode 2), pin 3 K1 and A2. The board matches: pad 1 /GND, pad 2 /3V3, pad 3 /N_H1P (D104), /N_H1M (D105) and /N_UVP (D106) | "Yes" |
| 10: SOT-23 reflow footprint | Closed. `SOT-23_CrtYd0.25` has 1.475 x 0.6 mm pads at 1.9 mm pitch, with the rows 1.875 mm apart (pads 0.20 to 1.675 mm from the centre line). The Fig. 8 lead width is 0.38 to 0.48 mm, below the 0.6 mm pad width, and the lead tips lie 1.05 to 1.25 mm from the centre line (toe pad 0.43 mm or more). The Fig. 9 reflow lands are about 0.6 x 0.7 mm, with the rows about 2.0 mm apart. The KiCad pads are longer toward the body, a fillet difference, not a connectivity difference. The land-pattern refinement is dropped | "Close, no need to refine if the current footprint is verified compatible" |
| 2: In2.Cu VCHGIN strap | Closed on IPC-2152. Required section 87.4 mil2 = 3.221 mm at 17.5 um; the 4.174 mm strap (113.2 mil2) gives 2.75 A at a 10 degC rise (7.4 degC rise at 2.41 A). OSH Park gives the inner layers as "0.68 mil (0.0175mm) 0.5 oz copper clad" (not plated, so 17.5 um finished; 2.73 A at 17.3 um). The IPC-2221 internal formula gives 2.04 A, below the 2.41 A basis, and needs 5.258 mm (`docs/reviews/charger_eval_2026-11-05/round4/calc/r9_calc_out.txt`); it does not pass | "Accept, use IPC-2152"; on 0.5 oz inner copper, "Yes" |
| 2: VCHGOUT path, U101 OUT to W1 (the half of item 2 outside the Review 2/2 ruling) | Closed by acceptance (operator ruling 2026-11-13, design session). R9.H26 finds two F.Cu-only necks below the IPC-2152 long-conductor basis at 3.21 A (Table 4); they stay as they are, and the board does not change; the acceptance rests on the ruling, not on a pass (item 5 of this section) (**Superseded 2026-11-13, VCHGOUT ruling:** "Open"; "the operator chooses acceptance, wider copper or a bench measurement"; operator's words "none yet") | "Accept short necks" |
| 5: OSH Park 4-layer stack-up | Closed (item 4 of this section) | "Yes" |
| 7: OSH Park quote | Closed as out of scope | "Quote is outside the scope of the project" |
| 3: non-functional inner pads at connector holes | Amended: open as an assumption that is checked at submission; not an order blocker. The OSH Park page states nothing on non-functional pads. The plated-drill-to-internal-copper rule of 10 mil (0.254 mm) is met (inner pours 0.27 mm, DRC 0). All vias keep their inner pads; only J1 (22 pads), J102 (10 pads), W1 to W4, W6 and W7 have their unused inner pads removed | "Let's assume they will accept it. I will find out later when I submit the board if not."; on the decision, "We will decide once that time comes" |

The Review 2/2 session raised two questions that the operator has not answered. The first stays open for the
operator; the D-62 re-export in `89c2d72` made the second moot:

- Decide the CR order quantity. The CR fab package README (`fab/cr_2026-11-13/README.md`, section 1) gives a quantity
  of 5, but OSH Park sells boards in multiples of 3. Amended 2026-11-13: the package README as re-exported in
  `89c2d72` still gives a quantity of 5, and its OSH Park row now states that order quantities come in multiples of 3.
  The question stays open; it does not block the bare-board order.
- Amended 2026-11-13: moot. The D-62 re-export in `89c2d72` replaced the OSH Park row of the CR fab package README;
  the row now states the confirmed 4-layer stack-up (1.6 mm, 1 oz outer / 0.5 oz inner clad, ENIG, FR408-HR), which
  matches section 1 of that README. (**Superseded 2026-11-13:** "Decide whether to correct the OSH Park row of the CR
  fab package README. The row says that a 4-layer order at OSH Park "uses the 1 oz fallback of the Copper row above",
  but the OSH Park 4-layer stack-up already is 1 oz outer and 0.5 oz inner, which is the D-29 copper of the Copper
  row.")

(**Superseded 2026-11-13:** "Both stay open for the operator, and no file is changed"; the list items were numbered 5
and 6.)

### 3.2 Standing defaults from 2026-11-12

1. The check-in 2 rulings R1 to R6 stay as orchestrator defaults (`DESIGN_STATE_2026-11-12.md`).
2. The J-TAP cavity map keeps one severity-3 diagonal pair, T7b-T17 (r9-13). No 2 x 5 map has zero severity-3 pairs;
   FR-11 guards this pair.

### 3.3 Records and tools

1. `gen/route.py` resets the board minimums in `cr/cr.kicad_pro` on a rebuild, so its zone fill leaves six J102 peg
   items. Restore the file from git and refill (D-57 verification note). The generator itself is not changed.
2. Tools commit `114ad04` (merged as `a919337`) makes the router and its score script ban vias from a pad's
   square-cornered mask opening, so plans no longer need `mask_margin` 0.075 mm. Board models built before it need a
   rebuild (D-58). The routed board is unchanged.
3. The D-57 strap extension takes about 3.1 mm2 of In2.Cu area under R102 and C102a. The route race measured no
   routing cost from it.

## 4. Process

The routing session (branch `charger-evm-r9-route`) ran two route-race rounds on the D-56 and D-57 boards and fixed
the router's SMD via ban (`ce47d93`). Its result was merged by fast-forward (`621fb28`). The routing session's notes
(`REVIEW_r2.md`, `TABLE_r2.md`, `plan_softum.json`) hold the per-seed tables. The design owner then placed the
reference designators, exported the package and wrote this review. On the operator rulings of 2026-11-13, the design
owner trimmed the outline and added the four holes in the generator (D-60). On operator requests of 2026-11-13, the
routing session then added the /GND stitching vias and straightened the tracks on the trimmed board (`07a6181`). The
design owner merged that board as `b8e3762`. The routing session then wrote `stitch_gaps.py` (request R9-03). In
`437d2d7` the design owner merged the tool, ran it on `b8e3762`, which added three /GND vias that close the 4.08 mm
stitching gap, and re-exported the package and the figures (D-61). The routing session's own gap-fill board is on the
`8521bf8` lineage and was not taken. An intermediate board, `8521bf8`, was stitched and straightened before the trim
and had a 19-vertex outline; it is superseded, and its values are not current. On an operator ruling of 2026-11-13 to
the routing session (request R9-04), the routing session wrote the angle, minimum-edge and fillet options of
`trim_outline.py` (merged as `b1b1e81`). The D-62 outline data in `gen/cr_geometry.py` reproduce that outline from
the routed board `621fb28`, and the routing session re-ran the D-61 finish order on the trimmed board. Then
`gen/silk_refs.py` and `gen/sync_fields.py` ran, and the checks and the re-export followed; all are committed in
`89c2d72` (D-62). The CR run steps after routing are `python gen/trim_cr.py <work dir>` (pcbnew venv), the router's stitching
(`tools/pcb/corridor_route/plane_vias.py --stitch 2.5`), `straighten.py`, the stitching gap fill
(`tools/pcb/corridor_route/stitch_gaps.py <board> <out dir> --y-flip-offset 100`), then `gen/silk_refs.py`, DRC,
`gen/check_constraints.py cr cr`, `gen/export.sh cr <date>` and `gen/fab_readme.py cr <date>`. On a board routed
before the Review 1/2 part-number change, such as `621fb28`, `gen/sync_fields.py cr/cr.kicad_pcb cr/cr.net` also runs
after `gen/silk_refs.py`; it copies the MPN and Note fields and changes no geometry. The figures in
`figures/cr_routed_2026-11-13/` were regenerated from the D-62 board. (**Superseded 2026-11-13:** "The CR run step
after routing is `python gen/trim_cr.py <work dir>` (pcbnew venv), then `gen/silk_refs.py`"; "regenerated from the
trimmed board".) (**Superseded 2026-11-13, D-62:** "regenerated from the trimmed, stitched, gap-filled and
straightened board", the D-61 board of `437d2d7`.)
