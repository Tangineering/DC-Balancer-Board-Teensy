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
     `costs.reserve` to 30. Put the exempt nets in groups whose `route` lists the zone corridors and one `BODY`
     region over the rest of the board (`reference/plan-format.md`). Measure the result with
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
5. `"$PY" capacity.py W/model/model.json W/plan.json W/capacity_report.md`. If check 1 prints a GRID message,
   set `rules.res` as it says. Sealed pads become requests.
6. Route at four seeds, in the background:
   `"$PY" -u seeds.py run W/model/model.json W/plan.json W/plain --seeds 1,2,3,4`.
   Read `W/plain/SEEDS.md`: mean, minimum, maximum, nets open at every seed, nets open at some seeds.
7. Finish each seed in this order: apply, score, plane vias, apply, score, constraint metrics. Finish the best
   seed always, and every seed when the plane nets or a constraint metric decide between plans. Run every step
   with the pcbnew venv `"$PY"`; shapely is in that venv, not in miniforge (`"$MPL"`).

   ```bash
   D=W/plain/s<N>; B=<board>.kicad_pcb; V="--allow-via-in-pad"   # V empty when the plan allows no via in a pad
   "$PY" apply_routes.py W/$B $D/routes.json $D/board
   "$PY" score.py $D/board/$B W/$B $D/score --plane-nets <nets> $V --label plain-s<N>
   "$PY" plane_vias.py W/model/model.json W/plan.json $D/routes.json $D/board/$B $D/plane_routes.json --report $D/plane_vias.md
   "$PY" apply_routes.py $D/board/$B $D/plane_routes.json $D/board_pv
   "$PY" score.py $D/board_pv/$B W/$B $D/score_pv --plane-nets <nets> $V --label plain-s<N>-pv
   "$PY" parallel_metric.py W/model/model.json $D/routes.json --zone-parts <refs> --analog-nets <nets> --json $D/parallel.json
   ```

   - Read "Result valid", the new violations and `vias_on_smd_pads` in both scores. The open connections of the
     plane nets in `score_pv.md` are the plane-via result.
   - `plane_vias.py` keeps each via off the unflashed layers of its own net's through-hole pads. Do not give
     `--no-respect-unflashed`. Without the rule, KiCad flashed GND pads J1.14 and J1.15 on In2.Cu onto routed
     tracks on the CR board, at 3 of 4 seeds.
   - Run `parallel_metric.py` only when a soft keep-away rule applies (step 4). Run the project's constraint
     check as well.
   - When `plane_vias.md` lists pieces without a via site, run `nosite_why.py` on `board_pv` with the inputs of
     `plane_vias.py`. A piece that routed copper on one layer blocks needs one track moved; on the CR board, an
     In2.Cu track by about 0.85 mm, in the GUI. A piece that obstacles or holes block becomes a request.
   - Before you use the numbers of a constraint checker, verify its frame on one pad whose position you know.
     `model.json` and `routes.json` are in the KiCad frame; a design-frame limit can use y = Y0 - y. Use
     `parallel_metric.py --check-pad REF.PAD [--y-flip-offset Y0]`, or print one pad from your own checker. A
     checker in the wrong frame gave wrong counts that went to the design owner (CR study, 2026-11-12).
8. `"$MPL" -I render.py W/model/model.json W/plain/img --plan W/plan.json --routes W/plain/s<N>/routes.json`.
   Open the images.

If every seed connects everything, the plain plan is the result. Go to section 5.

## 3. When the board does not close

1. Measure the channels: `"$PY" global_route.py W/model/model.json W/plan.json W/plan_g.json --report W/global.md`,
   at `--tile 2.0` and `--tile 1.0` (`reference/shared-options.md` section 5).
2. Classify each open net from `SEEDS.md` and the reports of all seeds:
   - open at every seed, at the same place: a limit of the board there. It becomes a request with evidence
     (section 4), or a hypothesis for a plan (below);
   - open at some seeds: not evidence. More iterations or another seed may close it.
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

## 7. Limits

- The router is a grid search at the fab pitch; tracks are staircases of 45-degree and straight steps. A
  result is a first pass. The last connections of a dense board may be faster to route by hand in the GUI.
- The capacity check counts parallel tracks; the global router does not count pin demand inside a tile.
- `autoroute.py` runs Freerouting as an outside reference. It completed fewer connections on every test board
  and its results were not valid (no edge rule, cuts pours, cannot hold nets out).
- This skill was written for small mixed-signal power boards without high-speed nets. Revise it when the
  tools or the models change.
