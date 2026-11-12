# Fab limits

These limits were stated by the operator on 2026-11-11. Check the fab's current capability page before an
order; the routing skills use these values as floors.

| Fab and service | Layers | Minimum track / space | Copper | Notes |
|---|---|---|---|---|
| OSH Park | 2 | 6 / 6 mil (0.1524 mm) | 1 oz | |
| OSH Park | 4 | 5 / 5 mil (0.127 mm) | 1 oz outer | |
| PCBWay, standard or low-cost | 2 or 4 | 6 / 6 mil (0.1524 mm) | 1 oz or 2 oz | |
| PCBWay, standard or low-cost | 2 or 4 | 5 / 5 mil (0.127 mm) | 1 oz only | 2 oz copper is not offered at 5 / 5 mil |

Consequences for routing:

- A board that must be buildable at both fabs uses the larger of the two limits for its layer count.
- 5 / 5 mil requires 1 oz outer copper. A power net that needs 2 oz copper cannot share a board with 5 / 5 mil
  signal routing at PCBWay.
- The board rule files are in `tools/pcb/fab_rules/`. The plan `rules` must not go below the rule file of the
  board. A request to change the rule set goes to the operator.
- Via: 0.6 mm pad with 0.3 mm drill is inside every service above. Smaller vias are a request.
