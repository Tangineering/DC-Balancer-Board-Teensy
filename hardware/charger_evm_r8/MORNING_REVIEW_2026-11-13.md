# Charger EVM r9: overnight review (2026-11-12 to 2026-11-13)

This document records the overnight work that took the CR from a frozen netlist to a routed board and a fabrication
package, and lists the decisions and open items that the operator should review. It also records the D-60 outline
trim and the four 6-32 holes added on 2026-11-13 after the overnight round, and the package re-export that followed.
The D-61 /GND stitching vias, stitching gap fill and straightened tracks, added on operator requests of 2026-11-13,
and the package re-export from that board are recorded as well. `LAYOUT_DECISIONS.md` (D-53 to D-61) is the full
design record. Nothing was ordered, no firmware was changed, and nothing was pushed.

## 1. Result

The CR (`cr/cr.kicad_pcb`, branch `charger-evm-round4` at `437d2d7`) is placed, poured, routed, trimmed to its final
outline (D-60), stitched to /GND and straightened (D-61). Table 1 gives the check results on the final board. All
checks pass: 0 FAIL rows, with the three exemption rows of Table 1. (**Superseded 2026-11-13:** "The CR
(`cr/cr.kicad_pcb`, branch `charger-evm-round4` at `779c419`) is placed, poured, routed and trimmed to its final
outline (D-60)."; "The CR (`cr/cr.kicad_pcb`, branch `charger-evm-round4` at `cb1def6`) is placed, poured and routed.")

Table 1. Checks on the final CR board.

| Check | Result |
|---|---|
| ERC | 0 messages |
| DRC (`--severity-all --schematic-parity`) | 0 violations, 0 unconnected items, 0 parity issues |
| Constraint check (`cr/constraint_check.md`) | 109 pass, 0 FAIL, 3 exemption rows: 2 listed exemptions (R103, R129) and 1 D-20 exemption (R102); rows check the D-60 outline, key ear and holes and the D-20 stitching (D-61) (**Superseded 2026-11-13:** "98 pass"; "108 pass, 0 FAIL") |
| D-20 L2-L4 GND stitching (D-61) | pass: 296 stitch points (/GND vias and /GND plated holes); the largest distance to the nearest one over the filled L4 pour is 3.47 mm at (31.0, 34.7), against 3.54 mm for a 5 mm square pitch; the stitching gap fill (`stitch_gaps.py`) added 3 /GND vias at (36.04, 26.87), (34.34, 33.62) and (34.04, 59.52) after the grid stitching left a 4.08 mm gap at (36.0, 26.7) (request R9-03, closed) |
| Routing | 107 of 107 connections; 148 router vias; 278 /GND vias, of which 269 are grid stitching vias and 3 are gap-fill vias (D-61); 823.9 mm of track in 768 segments after straightening (D-61); every track 0.1524 mm; vias 0.6 / 0.3 mm only (**Superseded 2026-11-13:** "830.8 mm of track") |
| Vias on SMD pads | 0 (D-37 row "none"); the smallest annulus gap to a pad plus its mask opening is 0.027 mm |
| Outline and holes (D-60) | convex 18-vertex outline inside the D-39 rectangle, 2241.6 mm2 (was 4212.2 mm2, 53 %); bounding box 40.02 x 64.81 mm, MB frame x 18.58-58.60, y 7.83-72.64; four NPTH 3.70 mm holes (6-32 free fit) MH1 to MH4, each with an all-layer copper keep-out of radius 4.0 mm; MH1 (26.23, 69.04), MH2 (54.85, 63.79), MH3 (54.85, 11.43), MH4 (24.48, 25.18), MB frame, each keeping a 3.6 mm head disc on the board; a +x key ear keeps the D-41 overlap with J-BL (7.73 mm) and J-FC (7.63 mm) |
| Divider-top rule (A.8) | same-layer metric 0.00 mm; 0.7 mm of logic track and 1 logic via (the /CE_DRV_J escape) in the zone |
| VCHGIN In2 strap (R9.H25) | minimum section 4.174 mm against 3.221 mm required; 2.75 A at a 10 degC rise against 2.41 A |
| Fabrication package | `fab/cr_2026-11-13/`, re-exported from the stitched, gap-filled and straightened board in `437d2d7`, not ordered (**Superseded 2026-11-13:** "re-exported from the trimmed board in `779c419`"); the figures `figures/cr_routed_2026-11-13/` were re-exported from the same board; the NPTH drill file has tool T2 3.70 mm; the EIB package is `fab/eib_2026-11-13/` |

At `437d2d7` the branch is 53 commits ahead of `main`, and `main` is an ancestor of the branch. Each later commit adds
one more. To get the current count, run `git rev-list --count main..charger-evm-round4`. (**Superseded 2026-11-13:**
"With this review committed, the branch is 34 commits ahead of `main`"; "At `779c419` the branch is 45 commits ahead of
`main`".) To bring `main` level, run this command in the
primary checkout:

```bash
git merge --ff-only charger-evm-round4
```

## 2. Decisions to review

Table 2 lists the decisions of this round. Rows 1 to 5 and 7 are design-owner defaults that the operator may reverse.
Row 6 (D-60) implements operator rulings of 2026-11-13, and row 8 (D-61) implements operator requests of 2026-11-13.
The last column gives the reversal path.

Table 2. Decisions of the overnight round, D-60 and D-61.

| # | Decision | Basis | Reversal |
|---|---|---|---|
| 1 | D-54: CR placement variant B (`LAYOUT_VARIANT` default `B`) | a two-seed routability probe of both variants on the same plain plan | `LAYOUT_VARIANT=A`; the variant-A record in `cr/variants_r9/A/` predates the D-55 fixes and would need a re-run |
| 2 | D-55 and D-56: every finding of the two placement reviews applied (U101 network in the +x pocket, paste window panes, In2 VCHGIN strap widened, C103 ground via, pour seal removed) | `cr/placement_review_r9.md`, `cr/placement_review_r9b.md` | revert `8b68044` and `86cd19d` |
| 3 | D-57: a /GND via at (42.30, 59.30) for C102c pad 2, with a strap extension under R102 | the route race found C102c.2 open at every seed of every plan; the via changes no placement and no signal route | revert `0e7f22b`; C102c.2 is then open again |
| 4 | D-58: routing by plan softum (soft divider-top zones, via cost 200 on four U101 high-impedance nets, mask margin 0.075 mm), seed 1 | best of four seeds; all four seeds routed 107 of 107 | re-route from `0e7f22b` with another plan; the plans are in the routing session's notes |
| 5 | D-59: reference designators re-placed by `gen/silk_refs.py`; 19 references on F.Fab only after the D-60 re-placement (C110 added) (**Superseded 2026-11-13:** "18 references on F.Fab only") | the 124 silkscreen DRC items blocked `gen/export.sh` | restore the fields from `621fb28`, or move every small-part reference to F.Fab (D-12a as first written); on the D-60 trimmed board, re-run DRC afterwards, because restored fields can fall off the trimmed edge or over a hole mask opening |
| 6 | D-60: after routing, the CR is trimmed to a convex 18-vertex outline (2241.6 mm2) inside the D-39 rectangle, with a +x key ear and four 6-32 holes (MH1 to MH4) for a 3D-printed support; made by the design owner in the generator (`gen/cr_geometry.py`, `gen/trim_cr.py`) | operator rulings of 2026-11-13, relayed by the routing session (route-race change request R9-02): trim the unused area, a non-rectangular outline is acceptable, holes in the corners for 6-32 screws; no part, track or via moved | restore `cr/cr.kicad_pcb` from the D-59 commit `6ae73df` and run `gen/silk_refs.py` and `gen/export.sh` again, or change `FINAL_OUTLINE`, `KEY_EAR` or `MOUNTING_HOLES` and run `gen/trim_cr.py` on the routed board |
| 7 | KiKit JLCPCB and PCBWay assembly presets left failing for the CR | the CR fab is OSH Park (bare board); the package README states the failure | fix the reference parse in KiKit's input (likely the suffixed references such as R131B and C102a) |
| 8 | D-61: the finish order of the routed CR is route, plane vias, `gen/trim_cr.py`, /GND stitching vias on a 2.5 mm grid inside the trimmed fill (`tools/pcb/corridor_route/plane_vias.py --stitch 2.5`), `straighten.py`, the stitching gap fill (`tools/pcb/corridor_route/stitch_gaps.py <board> <out dir> --y-flip-offset 100`), then `gen/silk_refs.py`; the router's stitching replaces `route.py stitch()` (never both on one board), and `gen/trim_cr.py` refuses an already-trimmed board; the board is the routing session's `07a6181`, merged as `b8e3762`, with the 3 gap-fill vias added in `437d2d7`; the D-60 outline and holes do not change | operator requests of 2026-11-13, relayed by the routing session; the D-58 to D-60 board had only 6 /GND vias, because the `ROUTE_SKIP_FR=1` build skips `route.py stitch()`, so D-20 (L4 stitched to L2 at a pitch of at most 5 mm) was not met and no check measured it | restore `cr/cr.kicad_pcb` from `779c419` and run `gen/export.sh` and `gen/fab_readme.py` again; the D-20 stitching row then fails with 6 /GND vias |

## 3. Items that need the operator

### 3.1 Before the order

1. Review the reference-designator result of D-59, as re-placed after the D-60 trim. 59 of 78 references are on the
   silkscreen, 27 of them over another courtyard and hidden after assembly. These 19 references are on F.Fab only:
   C107, C110, C115, C130, C132, D105, D106, R122, R130, R131B, R147, R184 to R189, U110 and W3. (**Superseded
   2026-11-13:** "60 of 78 references are on the silkscreen, 26 of them over another part"; "These 18 references".)
   In the dense rows a reference can sit up to 3.0 mm from its part, so the interactive BOM (`assembly/cr_ibom.html`)
   is the assembly reference. The alternative is all small-part references on F.Fab, which gives a cleaner silkscreen
   and the same assembly method.
2. Confirm the placeholder footprints against their drawings before the order. The J-TAP header (Molex 43045, items 16
   and 25 of `LAYOUT_DECISIONS.md` section 11), the TSW-110/112-07-L-S pins (item 14) and the W6/W7 lead pads (D-45) use
   placeholder pad and drill geometry. A wrong drill or pitch on these parts is not repairable on a fabricated board.
   The D-46 J-TAP latch finger access stays open: the hole MH3 (54.85, 11.43) and R175 are on the +x/-y side of
   J102, so include them when you examine the latch access.
3. Confirm the OSH Park solder-mask expansion (0.0508 mm, TODO(verify) in the rule file). The 0.027 mm via-to-mask-
   opening gap of Table 1 is between a pad and its own same-net escape via, so a registration error can at most let
   solder wick onto that via. The smallest different-net gap is 0.115 mm (C116.1 /3V3 to a /QUAL via), about 0.094 mm
   with square-cornered openings. (**Superseded 2026-11-13:** "a registration error exposes part of a via annulus
   next to a pad of another net".)
4. Confirm the quote and the 4-layer stack-up (section 11 items 5 and 7). The quote input is the trimmed outline area,
   2241.6 mm2.

The D-20 stitching of D-61 is not an order item: its constraint-check row passes (Table 1). The order blockers remain
those of `LAYOUT_DECISIONS.md` section 1: section 11 items 2, 3, 5, 7, 9, 14, 16 and 25, and the W6/W7 lead pads of D-45.

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
and had a 19-vertex outline; it is superseded, and its values are not current. The CR run steps after routing are
`python gen/trim_cr.py <work dir>` (pcbnew venv), the router's stitching
(`tools/pcb/corridor_route/plane_vias.py --stitch 2.5`), `straighten.py`, the stitching gap fill
(`tools/pcb/corridor_route/stitch_gaps.py <board> <out dir> --y-flip-offset 100`), then `gen/silk_refs.py`, DRC,
`gen/check_constraints.py cr cr`, `gen/export.sh cr <date>` and `gen/fab_readme.py cr <date>`. The figures in
`figures/cr_routed_2026-11-13/` were regenerated from the trimmed, stitched, gap-filled and straightened board.
(**Superseded 2026-11-13:** "The CR run step after routing is `python gen/trim_cr.py <work dir>` (pcbnew venv), then
`gen/silk_refs.py`"; "regenerated from the trimmed board".)
