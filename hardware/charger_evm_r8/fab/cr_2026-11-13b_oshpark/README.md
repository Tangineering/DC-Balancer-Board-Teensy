# CR, carrier board: OSH Park Gerber and drill set after the routing cleanup (2026-11-13)

**Superseded 2026-11-13 (D-65) by `fab/cr_2026-11-13c/`; do not upload this zip.**

**Status: not ordered.** This folder holds the Gerber and drill files of `cr/cr.kicad_pcb` after the operator's
routing cleanup of 2026-11-13 (`547dc11`). It supersedes the copper of `fab/cr_2026-11-13/`, which was exported
before the cleanup. It holds no assembly files; re-export the full package with `gen/export.sh cr <date>` once the
board is final.

| Item | Value |
|---|---|
| Upload | `cr_oshpark_gerbers.zip` (OSH Park 4-layer) |
| Contents | F.Cu, In1.Cu, In2.Cu, B.Cu, both masks, silkscreens and paste layers, Edge.Cuts (Protel extensions); one merged Excellon drill file with the plated and non-plated holes, the 3.70 mm NPTH included; drill map PDF; Gerber job file |
| Export | kicad-cli 9.0.9, `pcb export gerbers` without `--subtract-soldermask`, `pcb export drill --format excellon --excellon-units mm` (merged PTH and NPTH), matching the KiKit OSH Park preset |
| DRC | 0 violations, 0 unconnected items, 0 parity issues (`drc.rpt`); zone fills current |
| Constraint check | 107 pass rows, 0 FAIL (`cr/constraint_check.md`); the D-37 row is "info": a /GND via at (37.50, 46.03), MB frame, overlaps J101 pad 9 by about 0.2 mm |
| Quantity | 6 (operator ruling 2026-11-13: "Use 6") |

The board and the stack-up are those of `fab/cr_2026-11-13/README.md` section 1. Settle the items of
`bom_2026-11-13/PREORDER_REVIEW.md` before the order.
