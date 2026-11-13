# Charger EVM r9: overnight review (2026-11-12 to 2026-11-13)

This document records the overnight work that took the CR from a frozen netlist to a routed board and a fabrication
package, and lists the decisions and open items that the operator should review. `LAYOUT_DECISIONS.md` (D-53 to D-59)
is the full design record. Nothing was ordered, no firmware was changed, and nothing was pushed.

## 1. Result

The CR (`cr/cr.kicad_pcb`, branch `charger-evm-round4` at `cb1def6`) is placed, poured and routed. Table 1 gives the
check results on the final board.

Table 1. Checks on the final CR board.

| Check | Result |
|---|---|
| ERC | 0 messages |
| DRC (`--severity-all --schematic-parity`) | 0 violations, 0 unconnected items, 0 parity issues |
| Constraint check (`cr/constraint_check.md`) | 98 pass, 0 FAIL, 2 listed exemptions |
| Routing | 107 of 107 connections; 148 router vias; 830.8 mm of track; every track 0.1524 mm; vias 0.6 / 0.3 mm only |
| Vias on SMD pads | 0 (D-37 row "none"); the smallest annulus gap to a pad plus its mask opening is 0.027 mm |
| Divider-top rule (A.8) | same-layer metric 0.00 mm; 0.7 mm of logic track and 1 logic via (the /CE_DRV_J escape) in the zone |
| VCHGIN In2 strap (R9.H25) | minimum section 4.174 mm against 3.221 mm required; 2.75 A at a 10 degC rise against 2.41 A |
| Fabrication package | `fab/cr_2026-11-13/`, not ordered; the EIB package is `fab/eib_2026-11-13/` |

With this review committed, the branch is 34 commits ahead of `main`, and `main` is an ancestor of the branch. To bring `main` level, run this
command in the primary checkout:

```bash
git merge --ff-only charger-evm-round4
```

## 2. Decisions to review

Table 2 lists the decisions of this round. Each one is a design-owner default that the operator may reverse; the
last column gives the reversal path.

Table 2. Decisions of the overnight round.

| # | Decision | Basis | Reversal |
|---|---|---|---|
| 1 | D-54: CR placement variant B (`LAYOUT_VARIANT` default `B`) | a two-seed routability probe of both variants on the same plain plan | `LAYOUT_VARIANT=A`; the variant-A record in `cr/variants_r9/A/` predates the D-55 fixes and would need a re-run |
| 2 | D-55 and D-56: every finding of the two placement reviews applied (U101 network in the +x pocket, paste window panes, In2 VCHGIN strap widened, C103 ground via, pour seal removed) | `cr/placement_review_r9.md`, `cr/placement_review_r9b.md` | revert `8b68044` and `86cd19d` |
| 3 | D-57: a /GND via at (42.30, 59.30) for C102c pad 2, with a strap extension under R102 | the route race found C102c.2 open at every seed of every plan; the via changes no placement and no signal route | revert `0e7f22b`; C102c.2 is then open again |
| 4 | D-58: routing by plan softum (soft divider-top zones, via cost 200 on four U101 high-impedance nets, mask margin 0.075 mm), seed 1 | best of four seeds; all four seeds routed 107 of 107 | re-route from `0e7f22b` with another plan; the plans are in the routing session's notes |
| 5 | D-59: reference designators re-placed by `gen/silk_refs.py`; 18 references on F.Fab only | the 124 silkscreen DRC items blocked `gen/export.sh` | restore the fields from `621fb28`, or move every small-part reference to F.Fab (D-12a as first written) |
| 6 | KiKit JLCPCB and PCBWay assembly presets left failing for the CR | the CR fab is OSH Park (bare board); the package README states the failure | fix the reference parse in KiKit's input (likely the suffixed references such as R131B and C102a) |

## 3. Items that need the operator

### 3.1 Before the order

1. Review the reference-designator result of D-59. 60 of 78 references are on the silkscreen, 26 of them over another
   part and hidden after assembly. These 18 references are on F.Fab only: C107, C115, C130, C132, D105, D106, R122,
   R130, R131B, R147, R184 to R189, U110 and W3. In the dense rows a reference can sit up to 3.0 mm from its part, so the
   interactive BOM (`assembly/cr_ibom.html`) is the assembly reference. The alternative is all small-part references on
   F.Fab, which gives a cleaner silkscreen and the same assembly method.
2. Confirm the placeholder footprints against their drawings before the order. The J-TAP header (Molex 43045, items 16
   and 25 of `LAYOUT_DECISIONS.md` section 11), the TSW-110/112-07-L-S pins (item 14) and the W6/W7 lead pads (D-45) use
   placeholder pad and drill geometry. A wrong drill or pitch on these parts is not repairable on a fabricated board.
3. Confirm the OSH Park solder-mask expansion (0.0508 mm, TODO(verify) in the rule file). The 0.027 mm via-to-mask-
   opening gap of Table 1 is between a pad and its own same-net escape via, so a registration error can at most let
   solder wick onto that via. The smallest different-net gap is 0.115 mm (C116.1 /3V3 to a /QUAL via), about 0.094 mm
   with square-cornered openings. Superseded: "a registration error exposes part of a via annulus next to a pad of
   another net".
4. Confirm the quote and the 4-layer stack-up (section 11 items 5 and 7).

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
reference designators, exported the package and wrote this review.
