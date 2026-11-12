# Repair guide for open connections

`route_report.md` lists every open net with a class, the nets that it lost to, and the place. Use this guide
after every routing run. Apply the first remedy that fits; a later remedy costs more.

## 1. Procedure

1. Read the class of each open net (BLOCKED or CONGESTED).
2. State the spatial pattern in one sentence in `STATUS.md` ("7 of 9 open nets cross the header wall at gaps
   6 to 10 on In2.Cu"). Open nets that share a place share a cause.
3. Choose one remedy from the table. Change the plan entry that the pattern names.
4. Run `capacity.py`. Run `route_plan.py` again. Use `--only-groups` when only one group changed and the
   other groups do not use the same space.
5. Diagnose again. The class of a net often changes after a repair.
6. Stop when two consecutive repairs do not reduce the open connections. Then report (section 3).

## 2. Classes and remedies

| Class and sign | Cause | Remedies, most targeted first |
|---|---|---|
| BLOCKED, check 2 lists a sealed pad | Fixed copper, a pour or a keep-out closes the pad on every layer | None in the plan. Write a request: move the neighbour, notch the pour, smaller pad. If the pour may be cut, list it in `soft_pours` and state the reason. |
| BLOCKED, pad not sealed | The allowed region does not connect the pads | Extend the corridor to the pad. Raise `escape` until the disc contains a via site (B-side parts can cover every via site in a 2 mm disc). Add a layer to the corridor or to `layers`. Raise `margin` for a `local` net. |
| CONGESTED, lost to nets of its own group in a path corridor | The corridor is too narrow at the place named, or the nets enter in the wrong order | Widen the corridor at that station. Add a second layer. Split the group over two alternative corridors (`route: [["A", "B"]]`). |
| CONGESTED, lost to nets of another group | Two flows share one channel | Put the two flows on different layers. Mark the corridor `reserve`. Lower the priority number of the group that must win. Move one corridor to a free gap. |
| CONGESTED, lost to `(default)` nets | Unplanned local nets take the tracks | Give the local nets of that area their own group with `layers` that avoid the corridor layer, or a smaller `margin`. Mark the corridor `reserve`. |
| CONGESTED, crossing pattern (check 5 lists the pair) | Two nets held on one layer cross | Give one net of the pair a second layer (a bridge). On a 2-layer board, plan the bridge on the pour layer along the long axis of the pour. |
| CONGESTED, many nets lost to one large net | A rail with many pads and no pour competes everywhere | Priority 1 for the rail, so that the signals route around it. Write a request for a pour or an inner-layer rail. |
| Conflict count flat from the first iterations, no single place | The board lacks capacity for the nets | Lower `costs.via` so that nets change layer sooner. Then write requests: placement relief, DNP removal, finer rules within the fab limit, more layers, larger outline. Do not loosen a rule yourself. |
| CONGESTED at margin 0 to 1 in check 3 | The capacity check counts tracks, not the order of entry | Treat margin below 2 as over capacity; widen or split. |

Do not repair by removing a net from the plan, by lowering a clearance, or by editing copper.

## 3. Final report of an attempt that does not close

A result with open connections is valid when it states:

- the connections made and the total, and the score rank vector;
- each open net with its class and the place;
- the bottlenecks as numbers (channel, capacity, demand);
- the requests (`REQUESTS.md`) that would close them, each with the connections it would close.
