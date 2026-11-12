# Repair guide for open connections and new violations

`route_report.md` lists every open net with a class, the nets that it lost to, and the place. `score.md` lists
each new DRC violation with its position. Use this guide after every routing run. Apply the first remedy that
fits; a later remedy costs more.

## 1. Procedure

1. Read the class of each open net (BLOCKED or CONGESTED).
2. State the spatial pattern in one sentence in `STATUS.md` ("7 of 9 open nets cross the header wall at gaps
   6 to 10 on In2.Cu"). Open nets that share a place share a cause.
3. Choose one remedy from the table. Change the plan entry that the pattern names.
4. Run `capacity.py`. Run `route_plan.py` again with `--keep-routes <routes.json of the best attempt>`: the nets
   that were complete stay as they were, and only the open nets are routed. Use a full run (no `--keep-routes`)
   when the change moves a whole flow.
5. Diagnose again. The class of a net often changes after a repair.
6. Stop when two consecutive repairs do not reduce the open connections by more than the noise band
   (`common.md` section 5). Then report (section 4).

## 2. Open connections

| Class and sign | Cause | Remedies, most targeted first |
|---|---|---|
| `capacity.py` check 1 prints GRID | The pad pitch is too fine for the grid; a pad has no legal track start | Set `rules.res` to the value that the message gives. This is the one accepted reason to set `res`. Run time rises about fourfold. |
| BLOCKED, check 2 lists a sealed pad (no GRID message) | Fixed copper, a pour or a keep-out closes the pad on every layer | None in the plan. Write a request: move the neighbour, notch the pour, smaller pad. If the pour may be cut, list it in `soft_pours` and state the reason. |
| BLOCKED, pad not sealed | The allowed region does not connect the pads | Read check 4: it names the gap between corridor pieces. Corridors join only where they overlap. Extend the corridor to the pad. Raise `escape` until the disc contains a via site. Add a layer. Add a region corridor for the rest of the net's way to the group's `route`. |
| CONGESTED, lost to nets of its own group in a path corridor | The corridor is too narrow at the place named | Widen the corridor at that station. Add a second layer. Split the group over two alternative corridors (`route: [["A", "B"]]`). |
| CONGESTED, lost to nets of another group | Two flows share one channel | Put the two flows on different layers. Mark the corridor `reserve`. Lower the priority number of the group that must win. |
| CONGESTED, lost to `(default)` nets | Unplanned local nets take the tracks | Give the local nets of that area their own group with a `layer_cost` above 1 on the contested layer. Mark the corridor `reserve`. |
| Many open nets on one layer in one area, lost to priority-1 nets | Constrained local nets took the layer that the long flows need | `layer_cost` 2 on that layer for the constrained groups. A constrained net whose pads span more than 10 mm is a flow net with priority 2, not a local net. |
| CONGESTED, crossing pattern (check 5 lists the pair) | Two nets held on one layer cross | Give one net of the pair a second layer (a bridge). |
| Two nets lose the same place to each other in alternate attempts | One lane, two nets | No plan closes both. Give the constrained one the higher priority, and write a placement request with the place. |
| The open nets change identity from attempt to attempt | Noise, or each repair moves the conflict to a neighbour | Use `--keep-routes` so that routed nets stay. Compare at a second seed. Stop adding corridors. |
| Many nets lost to one large net | A rail with many pads and no pour competes everywhere | Priority 1 for the rail. Write a request for a pour or an inner-layer rail. |
| Conflict count flat after iteration 12, no single place | The board lacks capacity | Write requests: placement relief, DNP removal, a rail pour, more layers, larger outline. Do not loosen a rule. |
| Corridor at margin 0 to 1 in check 3 | The check counts tracks, not the order of entry | Treat margin below 2 as over capacity; widen or split. |

Do not repair by removing a net from the plan, by lowering a clearance, or by editing copper.

## 3. New DRC violations and pour damage

| Sign in `score.md` | Cause | Remedy |
|---|---|---|
| `clearance`, `shorting_items`, `hole_to_hole`, `copper_edge_clearance`, `items_not_allowed` | A tool defect, not a plan choice | The attempt is not valid. Record the positions in `SKILL_FEEDBACK.md` or the report. If a GRID message was printed, set `rules.res` first. |
| `starved_thermal` | A track beside a through-hole pad of a poured net | `costs.thermal` 30. If it remains, the net has no other lane: report the pad and the net as a placement request. |
| `track_dangling`, `via_dangling` | A partly routed net | Expected for a net with open pads. For a complete net it is a tool defect; report it. |
| Hard pour with more islands | A signal track or via cut the pour | Find the net at the position in `score.md`. Raise `layer_cost` on that layer for its group, or list a via-free route in a corridor. |
| Trial pour with more islands (2-layer) | Bridges on the pour layer enclose a pocket, or two parallel bridges leave a strip | `score.md` lists each piece with its position. Raise the pour-layer `layer_cost` for the nets that bridge there, so that a bridge moves or two bridges merge; do not set a preferred direction on the pour layer for that area. |
| Long signal length on the pour layer | Cheap vias | `costs.via` 20 and pour-layer `layer_cost` 4 to 8. |

## 4. Final report of an attempt that does not close

A result with open connections is valid when it states:

- the connections made and the total, the rank vector, and "Result valid: yes";
- each open net with its class and the place;
- the bottlenecks as numbers (channel, capacity, demand) or as the named lane that two nets need;
- the requests (`REQUESTS.md`) that would close them, each with the connections it would close.
