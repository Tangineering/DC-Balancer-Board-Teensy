# Snapshot before the 2026-11-14 review and simulation update round

This folder holds the CR and EIB design state at commit `014c745` (D-69), saved before the overnight update round of
2026-11-14. The same state is also tagged in git as `charger-r8-pre-review-2026-11-14` (local tag, not pushed).

| Folder | Content |
|---|---|
| `cr/` | CR schematic, board, rules, netlists, reports, footprint and symbol libraries |
| `eib/` | EIB schematic, board, rules, netlists, reports, footprint and symbol libraries |
| `gen/` | Generator scripts |
| `bom_2026-11-13/` | BOMs and order files |
| `fab/cr_2026-11-13f/`, `fab/eib_2026-11-13c/` | Fab packages of that state |
| `cr_RTbackup_untracked/` | The untracked `cr/cr.kicad_pcb_RTbackup.*` files (2026-11-13 13:38), which were never committed |

To restore the design, check out the tag (`git checkout charger-r8-pre-review-2026-11-14 -- hardware/charger_evm_r8`)
or copy the files from this folder back into place.
