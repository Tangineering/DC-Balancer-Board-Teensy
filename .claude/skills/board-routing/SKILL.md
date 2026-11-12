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
   - 2-layer board with a ground pour: the pattern of `reference/two-layer.md` section 2.
   - Vias: the router places no via on an SMD pad or in its mask opening. If the design uses filled vias, or
     accepts vias at named pads, set `rules.via_in_pad` (`reference/plan-format.md`). This is a decision of the
     design owner; it changes the completion much (section 6).
5. `"$PY" capacity.py W/model/model.json W/plan.json W/capacity_report.md`. If check 1 prints a GRID message,
   set `rules.res` as it says. Sealed pads become requests.
6. Route at four seeds, in the background:
   `"$PY" -u seeds.py run W/model/model.json W/plan.json W/plain --seeds 1,2,3,4`.
   Read `W/plain/SEEDS.md`: mean, minimum, maximum, nets open at every seed, nets open at some seeds.
7. Apply and score the best seed (`reference/common.md` section 2). Read "Result valid", the new violations,
   the added vias on SMD pads.
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
part move; the scripts give the verdict.

## 5. Review and report

Fill `W/REVIEW.md` from `reference/review-checklist.md` for the result that is reported. Rows 6, 10, 11 and 12
need the images. Report:

- the plain plan: mean, minimum and maximum of n seeds, the iteration limit;
- the scored result: rank vector, "Result valid", open connections by net, new starved thermals;
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
- The via rule matters more: earlier results had 70 to 110 vias on SMD pads. With the ban the same board
  makes fewer connections (see `STATUS` of the last test for the figure). Decide the via rule with the design
  owner before the numbers are compared with anything.
- Two seeds of one plan differed by up to 9 connections. One run is not a result.

## 7. Limits

- The router is a grid search at the fab pitch; tracks are staircases of 45-degree and straight steps. A
  result is a first pass. The last connections of a dense board may be faster to route by hand in the GUI.
- The capacity check counts parallel tracks; the global router does not count pin demand inside a tile.
- `autoroute.py` runs Freerouting as an outside reference. It completed fewer connections on every test board
  and its results were not valid (no edge rule, cuts pours, cannot hold nets out).
- This skill was written for small mixed-signal power boards without high-speed nets. Revise it when the
  tools or the models change.
