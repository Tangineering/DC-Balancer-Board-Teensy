# Straightening pass (D-63)

Board: `eib/eib.kicad_pcb` as routed (D-28), two runs of `tools/pcb/corridor_route/straighten.py --clear 0.2`
(the EIB track clearance, D-28). The second run converged.

| Measure | Routed | After run 1 | After run 2 |
|---|---|---|---|
| Track segments (unlocked, signal nets) | 479 | 421 | 418 |
| Track length, mm | 608.4 | 604.0 | 604.0 |

Run 1: 209 chains, 16 nets changed. Run 2: 222 chains, 2 nets changed. Clearance 0.2020 mm, edge 0.381 mm,
thermal ring 0.35 mm, reserved corridors 0. The remaining short jogs are at pad entries where the clearance
blocks a straight run. DRC after both runs: 0 violations, 0 unconnected items, 0 parity issues.
