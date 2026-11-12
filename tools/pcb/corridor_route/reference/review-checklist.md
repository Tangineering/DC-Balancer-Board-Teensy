# Review of a routed board

Do this review on the attempt that is reported. Write the table into `W/REVIEW.md`. A row without evidence is
"not checked", not "pass".

| # | Check | Evidence | Pass when |
|---|---|---|---|
| 1 | Completion | `score.md`: open connections, non-plane nets | 0, or each open connection listed with class and request |
| 2 | Plane nets | `score.md`: open connections, plane nets, after the project's plane-via step | 0 after the plane-via step. In a routing-only task the step is not run: write "not run" and the count |
| 3 | New DRC violations | `score.md`: "Result valid" and column New | Result valid: yes. Each `starved_thermal` item listed with its pad |
| 4 | Schematic parity | `score.md` | Run, and no issue |
| 5 | Pour integrity | `score.md`: pour islands, trial pour | No hard pour and no trial pour with more islands than on the unrouted board. Soft fills are information |
| 6 | Constrained nets | Design rows against the "Priority-1 nets" table of `route_report.md` (routed length, straight-line length, vias, layers) and an image window | Each limit of the design document holds. Without a design row: routed length under twice the straight-line length and at most 2 vias, or the net is reported |
| 7 | Track width for current | `routes.json` widths against `net-classes.md` section 2 | No net below its width |
| 8 | Vias | `score.md`; image | No via under a part pad that is not its own; no via in a keep-out |
| 9 | Board edge and keep-outs | New `copper_edge_clearance` and `items_not_allowed` | 0 |
| 10 | Return path | Image of the plane layer and of the signal layers | No signal crosses a split of its reference plane or pour; ground stitching vias exist next to layer changes of fast edges where the design asks for them |
| 11 | Dead copper | Images | No stub that ends in open space; no unconnected island of a kept pour |
| 12 | Connector and test access | Images, part outlines | No track or via blocks a connector, a test pad or a mounting-hole keep-out |
| 13 | Fab limits | Plan `rules` against `fab-limits.md` and the board rule file | Every value at or above the limit |

Checks 6, 10, 11 and 12 need the images; open them. The score does not see these.
