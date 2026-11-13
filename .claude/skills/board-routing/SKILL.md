---
name: board-routing
description: Route the signal nets of a placed KiCad board without the GUI - a negotiated-congestion grid router driven by a small plan file, run at four seeds, scored by one script, with optional plans (layer assignment, guide corridors, a 2-layer ground-pour pattern, one hand corridor at a measured bottleneck) that are tested against the plain plan. Use it when the user asks to "route the board", "autoroute", "route by script", "plan corridors", "set layer directions", for a first routed result on a new board, or as the routing step of the route-race skill. Do not use it for placement or for power pours.
---

# Board routing

The agent writes a plan: rules, which nets are kept, priorities, costs. Scripts make every geometric decision.
The agent never writes a track coordinate. A routing failure is repaired by a change to the plan or becomes a
request to the design owner, never by a change to copper.

This skill replaces three earlier method skills (corridor, direction-per-layer, autorouter). Three rounds of
dry tests showed that the plain plan is the reference that every other idea must beat, and that most ideas do
not beat it (section 6).

Read `tools/pcb/corridor_route/reference/common.md` first (environment, commands, work folder, status file,
score, seeds, run time). Read the other reference files at the step that names them.

## 1. Inputs and outputs

- Input: a work folder `W` with a copy of a placed board whose power copper (pours, straps, locked tracks) is
  in place; the routing layers, the plane nets, the frame offset, the fab rule set; the constrained nets and
  their limits from the design owner.
- Output in `W`: the plan files, `capacity_report.md`, `SEEDS.md` and the runs of each plan, a routed board
  and `score.md` for the result that is reported, images, `STATUS.md`, `REQUESTS.md` with `requests.json`,
  `REVIEW.md`.

## 2. The plain plan (always first)

1. `"$PY" board_model.py W/<board>.kicad_pcb W/model --layers <routing layers> [--y-flip-offset Y0]`.
2. `"$MPL" -I render.py W/model/model.json W/img --labels`. Open every layer image.
3. Read `W/model/model_summary.md` (board rules, nets with their pads, NO POUR flags) and
   `reference/four-layer.md` or `reference/two-layer.md`.
4. Write `W/plan.json`:
   `{"frame": {...}, "rules": {...}, "keep_nets": [...], "plane_net": "...", "default": {"mode": "free", "priority": 5}}`.
   - A net flagged NO POUR (12 or more pads, no pour): a group with `"mode": "free", "priority": 1`.
   - Constrained nets: groups as in `reference/net-classes.md`, each with the design row that limits it. If the
     design gives no row, write "no design row" in `STATUS.md` and ask the design owner; do not invent limits.
   - A soft keep-away rule (a net class kept away from a zone, scored as a metric): the router has no per-net
     keep-out. Draw the zone as region corridors with `"reserve": true` on the layers of the rule. Set
     `costs.reserve` to 30. Put the exempt nets in groups whose `route` lists the zone corridors. Give each such
     group its `mode` (`free` or `local`) explicitly: the group then keeps its own area, and the `route` list only
     exempts it from the reserve cost. A group with `route` and no `mode` becomes a corridor group and needs one
     `BODY` region over the rest of the board (`reference/plan-format.md`). Measure the result with
     `parallel_metric.py` (step 7). Test the plan against the plain plan (section 3). If the rule is a hard limit,
     this plan does not meet it (section 6): write a request.
   - 2-layer board with a ground pour: the pattern of `reference/two-layer.md` section 2.
   - Vias: the router places no via on an SMD pad or in its mask opening. Set `rules.via_in_pad` only on a ruling
     of the design owner (`reference/plan-format.md`). It changes the completion much (section 6). The value
     `false` (default) allows no via in an SMD pad. A list of pads (`["U101.25"]`) allows it at those pads only;
     use the list when the ruling limits via-in-pad to a count, a part or a net. The value `true` is unlimited:
     the router puts no cost on a via in a pad and uses it freely (102 to 119 per seed on the CR board). Use
     `true` only when the ruling accepts any number. `plane_vias.py` reads the rule from the plan. Give
     `score.py` the option `--allow-via-in-pad` whenever the plan allows a via in any pad. With a list,
     `score.py` does not check the list: compare the vias on SMD pads that `score.md` lists with the list.
     Report `vias_on_smd_pads` of `score.json` for every seed.
   - The ban covers the mask opening: each pad grown by its own mask expansion (`mask_exp` in the model), at
     least `rules.mask_margin`, with square corners, plus the via radius. A model made before 2026-11-13 has no
     `mask_exp`, and in it an exposed pad whose number is shared with its thermal vias is not banned. Rebuild
     such a model (step 1).
   - High-impedance nets that should stay on one layer: give them their own group with `via_cost` 200. At the
     default cost the router prefers a via pair to a few millimetres of a soft ground fill, so every short net
     near a busy IC can take two vias (all six U101 nodes on the r9 CR board). Do not raise the cost on a net
     that must cross another net: the other net then cannot route (section 3, step 2).
5. `"$PY" capacity.py W/model/model.json W/plan.json W/capacity_report.md`. If check 1 prints a GRID message,
   set `rules.res` as it says. Sealed pads become requests. Then check the via ban:
   `"$PY" smd_ban_test.py W/model/model.json W/plan.json [--pad REF.PAD ...]`. It must print PASS. Name the
   exposed pads and every pad whose number is shared with holes.
6. Route at four seeds, in the background:
   `"$PY" -u seeds.py run W/model/model.json W/plan.json W/plain --seeds 1,2,3,4`.
   Read `W/plain/SEEDS.md`: mean, minimum, maximum, nets open at every seed, nets open at some seeds.
7. Finish each seed in this order: apply, score, plane vias (with stitching), apply, score, constraint metrics.
   For the seed that you deliver, add the straightening pass at the end (below). Finish the best
   seed always, and every seed when the plane nets or a constraint metric decide between plans. Run every step
   with the pcbnew venv `"$PY"`; shapely is in that venv, not in miniforge (`"$MPL"`).

   ```bash
   D=W/plain/s<N>; B=<board>.kicad_pcb; V="--allow-via-in-pad"   # V empty when the plan allows no via in a pad
   "$PY" apply_routes.py W/$B $D/routes.json $D/board
   "$PY" score.py $D/board/$B W/$B $D/score --plane-nets <nets> $V --label plain-s<N>
   "$PY" plane_vias.py W/model/model.json W/plan.json $D/routes.json $D/board/$B $D/plane_routes.json --report $D/plane_vias.md [--stitch 2.5]
   "$PY" apply_routes.py $D/board/$B $D/plane_routes.json $D/board_pv
   "$PY" score.py $D/board_pv/$B W/$B $D/score_pv --plane-nets <nets> $V --label plain-s<N>-pv
   "$PY" parallel_metric.py W/model/model.json $D/routes.json --zone-parts <refs> --analog-nets <nets> --json $D/parallel.json
   ```

   - Read "Result valid", the new violations and `vias_on_smd_pads` in both scores. The open connections of the
     plane nets in `score_pv.md` are the plane-via result.
   - `plane_vias.py` keeps each via off the unflashed layers of its own net's through-hole pads. Do not give
     `--no-respect-unflashed`. Without the rule, KiCad flashed GND pads J1.14 and J1.15 on In2.Cu onto routed
     tracks on the CR board, at 3 of 4 seeds.
   - Stitching: when the design asks for plane stitching (for example "L2 and L4 GND stitched at a pitch of at
     most 5 mm"), give `plane_vias.py --stitch PITCH`. It adds vias of the plane net on a grid of that pitch inside
     the plane net's fill, with the same site rules as the plane vias (routed copper, holes, SMD pads and their mask
     openings, unflashed pads, keep-outs), and reports the grid nodes without a legal site. On the r9 CR board,
     2.5 mm gave 585 vias over the untrimmed outline and 269 on the final trimmed outline, with no new DRC item.
     The grid places a via only within half a pitch of each node, so a dense area can keep a gap. On the final
     board (after straightening and any trim) run `"$PY" stitch_gaps.py <board> <out> --limit L`: it measures the
     distance from every point of the plane pour to the nearest via or plated hole of the net, and adds a via at
     the nearest legal site of the real board copper until the largest distance is at most L (default 3.54 mm, a
     5 mm square pitch). It works on the board geometry, so it is right after straightening, when the router's grid
     occupancy is out of date; do not run `plane_vias.py` on a straightened board. On the r9 CR board the project's
     stitching row failed at 3.80 mm in the comparator cluster; 4 added vias gave 3.44 mm, DRC 0.
   - Straightening, for the delivered seed: the router steps cell by cell, so free stretches come out as
     staircases. `"$PY" straighten.py $D/board_pv/$B $D/board_st --plan W/plan.json --routes-out
     $D/routes_st.json` replaces each run that it can by one straight or 45-degree segment, or by one 45-degree and
     one straight segment. It keeps the clearance to all other copper, the edge, keep-outs, thermal rings, the
     unflashed own pads and the reserved plan corridors, and makes no acute bend; hard spots stay as they are.
     Score `board_st` again: it must stay valid with no more plane-net opens, and run the constraint metrics on
     `routes_st.json`. On the r9 CR board it cut 1791 track segments to 762 and 830.8 mm to 824.4 mm, DRC
     unchanged, divider metric unchanged.
   - Run `parallel_metric.py` only when a soft keep-away rule applies (step 4).
   - Run the project's constraint check on the board that you report. It knows design rules that KiCad DRC and
     `score.py` do not: on the r9 CR board it found two router vias inside the corners of pad mask openings
     after DRC and the score had passed the board (the tools are fixed since).
   - Finish the seeds of one plan one after another. Four `apply_routes.py` jobs started at once, while routing
     runs used the cores, stalled at start-up with no CPU use; the sequential rerun took minutes.
   - When `plane_vias.md` lists pieces without a via site, run `nosite_why.py` on `board_pv` with the inputs of
     `plane_vias.py`. A piece that routed copper on one layer blocks needs one track moved; on the CR board, an
     In2.Cu track by about 0.85 mm, in the GUI. A piece that obstacles or holes block becomes a request.
   - Before you use the numbers of a constraint checker, verify its frame on one pad whose position you know.
     `model.json` and `routes.json` are in the KiCad frame; a design-frame limit can use y = Y0 - y. Use
     `parallel_metric.py --check-pad REF.PAD [--y-flip-offset Y0]`, or print one pad from your own checker. A
     checker in the wrong frame gave wrong counts that went to the design owner (CR study, 2026-11-12).
8. `"$MPL" -I render.py W/model/model.json W/plain/img --plan W/plan.json --routes W/plain/s<N>/routes.json`.
   Open the images.

If every seed connects everything, the plain plan is the result for completion. Plans can still improve a
quality measure: router vias, the vias of constrained nets, a keep-away metric, or the plane-net connections open
after the plane-via step. Judge each measure like completion: a plan is a gain on a measure only when it is lower
at every seed (finish every seed of both plans). Then go to section 5. To choose the seed that you apply, take
the seeds with 0 plane-net connections open after the plane-via step first, then the fewest vias.

## 3. When the board does not close

1. Measure the channels: `"$PY" global_route.py W/model/model.json W/plan.json W/plan_g.json --report W/global.md`,
   at `--tile 2.0` and `--tile 1.0` (`reference/shared-options.md` section 5).
2. Classify each open net from `SEEDS.md` and the reports of all seeds:
   - open at every seed, at the same place: a limit of the board there. It becomes a request with evidence
     (section 4), or a hypothesis for a plan (below);
   - open at some seeds: not evidence. More iterations or another seed may close it.
   - a plane-net pad open at every seed of every plan, whose piece `nosite_why.py` shows blocked by obstacles
     (pours, other-net pads) on every layer, not by routed copper: the fixed copper and one signal path that
     every route must take enclose the pad. No plan closes it; write the request at once (r9 CR: C102c.2 /GND,
     enclosed by the U101 pin escapes, the J1 column and the VCHGIN pour and strap; the owner closed it with a
     /GND pre-via and a strap change).
   - two nets that cross by topology: the pin order of an IC and the sides of the parts that its nets reach
     disagree, so one of the two nets needs a via pair. A higher via cost on one opens the other (r9 CR: /N_IMON
     at via cost 200 left /N_FLT open at every seed). Only a placement change removes such a crossing; test it
     with a swap or a move and the project's constraint check.
   - If the log says that tens of nets were still in conflict at the end, the "Lost to" places show where the
     router gave up, not proven capacity limits. Say so.
3. Try a plan only as a hypothesis, one at a time, each judged by
   `seeds.py run` and `seeds.py compare W/plain <plan folder>`:

   | Plan | When | How |
   |---|---|---|
   | Layer assignment | Many crossings on one layer; many pour islands on a 2-layer board | `layer_assign.py` (`reference/shared-options.md` section 4) |
   | Guide corridors | Borders at capacity in `global.md` | `W/plan_g.json`, mode guide (`reference/shared-options.md` section 5) |
   | Priority or `via_cost` for a group | Constrained nets long or with many vias; one net loses a lane to another at every seed | `reference/failure-repair.md` |
   | 2-layer pour pattern | More pour islands than the unrouted board | `reference/two-layer.md` section 2; compare the islands in `score.md` |
   | One hand corridor | A border above capacity in `global.md`, and a flow open there at every seed | `reference/plan-format.md`; reserve it; `capacity.py` margin 2 or more |

   Only a verdict "B better" is a gain. "Not separated" means: keep the plain plan.
4. Do not use, except as a diagnostic that the task names: corridors that hold nets (`mode: corridor`,
   `global_route.py --mode hold`), layer directions on a 4-layer board, staged routing, a finishing pass with
   more than 10 open pads. Each lost connections in the dry tests.
5. Stop when a plan closes the board, or when two hypotheses in a row are "not separated". What is still open
   goes to the requests.

## 4. Requests

Open connections that no plan closes are for the design owner. Write each as a request with report evidence in
`REQUESTS.md` and `requests.json` (`reference/common.md` section 7): the nets and whether they are open at every
seed, the place in the plan frame, the nets that hold the space, the kind of change, and the test that would
decide it. In a race, stop there: the orchestrator tests the requests (`route-race`). Outside a race, test
them yourself: `whatif.py holdout` for nets that would leave the task, `reference/placement-relief.md` for a
part move; the scripts give the verdict. A hold-out folder holds `base/SEEDS.json` and `held/SEEDS.json`;
`seeds.py compare` reads the folder as its held side. A hold-out folder made before 2026-11-12 has no
`SEEDS.json`; compare it by hand from its `WHATIF.md`.

## 5. Review and report

Fill `W/REVIEW.md` from `reference/review-checklist.md` for the result that is reported. Rows 6, 10, 11 and 12
need the images. Report:

- the plain plan: mean, minimum and maximum of n seeds, the iteration limit;
- the scored result: rank vector, "Result valid", open connections by net, new starved thermals;
- the via-in-pad rule of the plan and `vias_on_smd_pads` of each scored seed;
- the plane-via result: plane-net connections open after the step, pieces without a via site and what blocks
  them (`nosite_why.py`);
- each constraint metric with its frame check;
- each hypothesis with its verdict;
- that a valid result is not a finished board, until the finish-test rows of the review pass.

## 5a. Final step: trim the outline and add mounting holes

A board outline that was sized for routing room keeps empty area after routing. When the board is routed and the
review passes, propose a trimmed outline with corner mounting holes:

```bash
"$PY" trim_outline.py W/<board>.kicad_pcb W/trim --y-flip-offset Y0 [--ear X0,Y0,X1,Y1 ...] \
    [--flip-centre CX,CY --flip-block NAME:X0,Y0,X1,Y1 ...] --apply
```

1. Find the mechanical reasons for the present outline in the design record before you trim: an overhang that keys
   the board, a cover over parts below, a connector reach. Keep each such area as an `--ear` box (plan frame). A
   board that is keyed by landing on parts when it is turned the wrong way keeps the key only while its outline
   still covers them: give those parts as `--flip-block` with the turn centre, and compare the overlap of the
   present and the proposed outline in `TRIM.md`.
2. The tool never grows the outline: an edge that the design fixed (for example a clearance to parts beside the
   board) stays. The defaults suit 6-32 screws (drill 3.7 mm, head disc 3.6 mm, copper keep-out 4.0 mm); set
   `--hole-*` for another screw. Ask the owner what the holes hold: a standoff that rests on the board below needs a
   clear spot there as well, which the tool does not check.
3. Read `TRIM.md`: area before and after, hole sites, ears, flip overlap, warnings. Check each hole against the
   nearest courtyard and copper; the keep-out must clear them by the gap.
4. `--apply` writes a checked copy: the new edge, the holes and their keep-outs, the board-wide zones and the edge
   band moved to the new edge, a refill. Run DRC and the project's constraint check on the copy. A row that tests
   the old outline fails until the owner amends it.
5. The outline belongs to the project's generator. Send the proposal (`TRIM.md`, `trim.json`, the DRC of the copy)
   to the design owner as a request of kind `outline`; do not write the outline into the project board yourself.
   When the owner's commit comes back, run DRC and the constraint check on it.

On the r9 CR board the step proposed 2242 mm2 against 4212 mm2 (53 %), with four 6-32 holes, a +x ear that keeps
the board landing on two of the three terminal blocks when it is turned by 180 degrees (7.7 and 7.6 mm of overlap),
DRC unchanged (124 silk items, 0 unconnected) and one constraint row failing as expected (the old rectangle).

## 6. What the dry tests showed

Four boards, three rounds, Opus workers; 4-layer board "CR" with 210 connections at 5/5 mil, 2-layer board
"EIB" with 80 connections.

- No plan was separated from the plain plan on the 4-layer board: hand corridors, layer directions, layer
  assignment, guide corridors. One hand corridor gained its own flow and lost more elsewhere (179 against 184).
- Holding nets inside corridors lost a quarter of the connections. Staged routing lost 13 to 17.
- On the 2-layer board with a ground pour the plan changed the pour islands (1 against 18): the pour pattern
  is the one place where a plan choice was worth its time.
- The negotiation schedule matters: on the CR board the present schedule made 181 to 188 connections where the
  earlier one made 178 to 182 (4 seeds each, vias on pads allowed in both).
- The via rule matters more: earlier results had 70 to 110 vias on SMD pads. With the ban the CR plain plan
  made 169 to 174 connections of 199 (4 seeds). With `via_in_pad: true` it made 179 to 182 on the next
  placement (one part moved, not separated from the first under the ban), with 102 to 119 vias in SMD pads per
  seed. Decide the via rule with the design owner before the numbers are compared with anything.
- A soft keep-away zone (reserved corridors at `costs.reserve` 30, exempt groups routed through them) cut the
  logic track parallel to analog track in the CR divider zone from 7.2-12.1 mm to 0.0-1.8 mm (same layer) at
  every seed. The completion was not separated (179.5 against 180.5). However, it did not remove all logic
  vias from the zone: a cost of 300 still left 2 to 9 per seed. A hard per-net keep-out needs a router change.
- After the plane-via step, 11 to 19 GND connections stayed open on the CR board. In2.Cu tracks blocked most
  of the remaining via sites.
- Two seeds of one plan differed by up to 9 connections. One run is not a result.
- r9 CR board (107 connections, F.Cu and In2.Cu, solid GND on In1.Cu and B.Cu, no via in a pad): the plain plan
  closed at 4 of 4 seeds, so the race compared quality. Soft divider-top zones plus via cost 200 on four U101
  nodes gave 143-148 router vias against 149-155, 0.1-0.2 mm of logic track in the zone against 7.3-24.4 mm,
  and 9 U101 vias against 13-14, each at every seed. Guide corridors for two long tap nets cut 1-5 vias but made
  those nets 10-25 mm longer, and added nothing to the zones.

## 7. Limits

- The router is a grid search at the fab pitch; tracks are staircases of 45-degree and straight steps. A
  result is a first pass. The last connections of a dense board may be faster to route by hand in the GUI.
- The capacity check counts parallel tracks; the global router does not count pin demand inside a tile.
- `autoroute.py` runs Freerouting as an outside reference. It completed fewer connections on every test board
  and its results were not valid (no edge rule, cuts pours, cannot hold nets out).
- This skill was written for small mixed-signal power boards without high-speed nets. Revise it when the
  tools or the models change.
