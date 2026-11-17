# REVIEW: routed CR r9 board (D-57 base, plan softum, seed 1)

## 1. Scope

This review covers the routed CR board applied on branch `charger-evm-r9-route`: the D-57 board (commit 0e7f22b,
sha256 12f5b9a1...) routed with `plan_softum.json` at seed 1 and finished with the plane-via step. The rows follow
`tools/pcb/corridor_route/reference/review-checklist.md`.

The plan is `plan_softu` of round 1 with `rules.mask_margin` 0.075 mm. With the default 0.05 mm round margin, seed 2
of `plan_softu` placed two router vias 0.0045 mm inside the square-cornered solder-mask opening of U106.1 and U118.8
(rectangular pads, mask expansion 0.0508 mm; the opening corner lies 0.072 mm from the copper corner). DRC and
`score.py` do not report this; `gen/check_constraints.py` row D-37 does. The 0.075 mm margin removes it.

## 2. Result of the four seeds (plan_softum, seeds 1-4, 60-iteration limit, no conflict left at any seed)

| Seed | Made | Valid | Router vias | Length mm | /GND open after plane vias | Divider same-layer mm | Logic in zone mm | U101 hi-Z vias |
|---|---|---|---|---|---|---|---|---|
| 1 | 107/107 | yes | 148 | 830.8 | 0 | 0.00 | 0.7 | 11 |
| 2 | 107/107 | yes | 149 | 861.4 | 0 | 0.00 | 0.7 | 11 |
| 3 | 107/107 | yes | 149 | 828.7 | 1 | 0.00 | 0.7 | 9 |
| 4 | 107/107 | yes | 150 | 843.5 | 0 | 0.00 | 0.7 | 11 |

C102c.2 is joined at every seed (R9-01 closed by D-57). Seed 3 leaves one GND_L1_fill piece that In2.Cu routing
blocks. Seed 1 is applied: /GND closed, fewest vias among the closed seeds.

## 3. Checklist (seed 1 as applied)

| # | Check | Result |
|---|---|---|
| 1 | Completion | 0 of 107 non-plane connections open |
| 2 | Plane nets (finish test) | /GND 0 open after the plane-via step and refill; DRC 0 unconnected items |
| 3 | New DRC violations (finish test) | none; 0 new starved thermals; DRC 124 = 75 silk_over_copper + 49 silk_overlap (reference fields, as D-56) |
| 4 | Schematic parity | 0 issues |
| 5 | Pour integrity | hard pours unchanged in island count (GND_L1_star_0 3/3, GND_L1_star_1 1/1, VCHGIN_L1 1/1, VCHGIN_L3_strap 1/1, VCHGOUT_L1 2/2) |
| 6 | Constrained nets | divider-top metric 0.00 mm same layer, 0.7 mm logic length in the zone, 1 logic via in the zone (/CE_DRV_J escape); U101 hi-Z vias 11 (/N_UV 2, /N_DVDT 2, /N_IMON 3, /N_FLT 2, /N_OV 0, /N_ILIM 2); /N_FLT 2 vias, /N_IMON 3 vias (topological crossing); no other design row limits routed length or vias |
| 7 | Track width | every net at 0.1524 mm (net-class default); /3V3 has no design width row |
| 8 | Vias | 0 on an SMD pad; D-37 row "none", smallest annulus gap to pad plus mask 0.027 mm; 0.6 / 0.3 mm only |
| 9 | Board edge and keep-outs | 0 copper_edge_clearance, 0 items_not_allowed |
| 10 | Return path | signal routing on F.Cu and In2.Cu over the solid In1.Cu GND plane; no split under any signal |
| 11 | Dead copper | no stub or unconnected island seen in the layer images |
| 12 | Connector and test access | no track or via on the J1, J102, J101 or W pads beyond their own nets |
| 13 | Fab limits | track and clearance 0.1524 mm (rule 0.127), via 0.6 / 0.3 mm (rule 0.4572 / 0.254) |

Constraint check (`gen/check_constraints.py cr ../cr`): 98 pass, 0 FAIL, 2 listed exemptions, 16 information rows.
`cr/cr.kicad_pro` and `cr/cr.kicad_dru` are unchanged.

## 4. Open items

- Tool: the router's SMD via ban and `score.py` use a round margin around pad copper; a rectangular pad's mask
  opening has square corners. A mitred mask-expansion ban in `core.py` and `score.py` would make the 0.075 mm plan
  margin unnecessary.
- The 124 reference-designator silk items stay for the fab step (design owner).
