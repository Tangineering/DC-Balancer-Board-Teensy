---
name: corridor-routing
description: Route the signal nets of a placed KiCad board the way a person routes by hand - name regions, count the flows between them, draw corridors on chosen layers, check their capacity, then let a script make the copper inside them. Use it when a board must be routed without the KiCad GUI, when the user says "route by hand", "plan corridors", "corridor routing", or as one method of the route-race skill. Do not use it for placement or for power pours.
---

# Corridor routing

The agent makes the global decisions: which regions exchange signals, which corridor carries each flow, on
which layer, with which priority. Scripts make every geometric decision. The agent never writes a track
coordinate. The plan is the product: a routing failure is repaired by a change to a plan entry, never by a
change to copper.

Read `tools/pcb/corridor_route/reference/common.md` first (environment, commands, work folder, status file,
score, noise). Read
the other reference files at the step that names them.

## 1. Inputs and outputs

- Input: a work folder `W` with a copy of a placed board whose power copper (pours, straps, locked tracks) is
  in place, and the design document rows that constrain nets.
- Output in `W`: `plan.json`, `flows.md`, `capacity_report.md`, `route_report.md`, a routed board and
  `score.md` for each attempt, images, `STATUS.md`, `REQUESTS.md` with `requests.json`, `REVIEW.md`.

## 2. Procedure

### Step 0. Model the board and run the baseline

1. `"$PY" board_model.py W/<board>.kicad_pcb W/model --layers <routing layers> [--y-flip-offset Y0]`.
   Give `--y-flip-offset` when the design documents use a y-up frame. The plan then uses design coordinates.
2. `"$MPL" -I render.py W/model/model.json W/img --labels`. Open every layer image.
3. Read `W/model/model_summary.md`: board rules, nets with their pads, NO POUR flags, parts.
4. Read `reference/four-layer.md` or `reference/two-layer.md` for the board.
5. Write `W/plan_free.json` with `rules`, `keep_nets`, `plane_net`, `"default": {"mode": "free"}`, and one
   group at priority 1 for each NO POUR rail. Run `capacity.py` on it; if check 1 prints a GRID message, set
   `rules.res` as it says. Route it (Step 3 and Step 4 commands, attempt folder `W/base`). This is the baseline.
   Its `route_report.md` shows which nets fail without a plan and where.
6. While the baseline runs, do Step 1.1 to 1.3.
7. If the baseline connects everything, the plan is judged on quality (vias, length, pour integrity on a
   2-layer board), not on completion. On such a board the plan has few levers; say so if no plan beats the
   baseline.

### Step 1. Classify, then plan

1. Classify every net with `reference/net-classes.md`.
2. Add `regions` to a draft plan: each cluster of parts that exchanges signals with another cluster.
   `"$PY" flows.py W/model/model.json W/plan.json W/flows.md`. Read the nets of each flow and the crossings
   between flows.
3. Find the walls: through-hole rows, hard pours, keep-outs, the outline neck. Each wall has gaps; each gap
   passes a number of tracks on each layer.
4. Draw a path corridor only for a flow that the baseline left open at a wall or a neck. State the gap and
   the layer in the corridor `note`. Do not draw a corridor for a flow that the baseline routed, even through a
   wall: in the dry tests such a corridor lost 6 of the 10 nets of its own group. Start with one corridor at
   the worst bottleneck; add the next one only after the first one gained connections.
5. Give flows that cross different layers. Give flows that run side by side one corridor on one layer.
   Overlapping corridors on one layer are one channel; their demand adds.
6. Constrained nets: `reference/net-classes.md` (short ones priority 1 and `local`; long ones priority 2).
7. Local nets near a corridor: give them a group with `layers` that exclude the corridor layer, or mark the
   corridor `reserve`. Unplanned local nets caused half of the conflicts in the dry tests.
8. Write `W/plan.json` (`reference/plan-format.md`).

### Step 2. Check the plan

1. `"$PY" capacity.py W/model/model.json W/plan.json W/capacity_report.md`.
2. Sealed pads (check 2): write a request for each. Continue with the other nets.
3. Corridor capacity (check 3): margin 2 or more at every path corridor. If lower: widen, move, add a layer, or
   split the flow over alternatives. Do not leave nets out to lower the demand.
4. Solo routability (check 4): repair each net listed (corridor to the pad, larger `escape`, another layer).
5. Crossings (check 5) and congestion (check 6): move a flow to another layer where the report shows the need.
6. `"$MPL" -I render.py W/model/model.json W/img --plan W/plan.json --tag plan`. Open the images.
7. Repeat until the report says PASS.

### Step 3. Route

1. `"$PY" -u route_plan.py W/model/model.json W/plan.json W/vN/routes.json --report W/vN/route_report.md`
   (in the background on a 4-layer board; `reference/common.md` section 6). A new folder `W/vN` for each attempt.
2. Read `W/vN/route_report.md`. Repair with `reference/failure-repair.md`. Go back to Step 2. Use
   `--keep-routes` of the best attempt for a repair, so that nets that routed are not lost.
3. Stop when every connection is made, or when two consecutive repairs do not reduce the open connections by
   more than the noise band (`reference/common.md` section 5).

### Step 4. Apply, score, review

1. `"$PY" apply_routes.py W/<board>.kicad_pcb W/vN/routes.json W/vN/board`.
2. `"$PY" score.py W/vN/board/<board>.kicad_pcb W/<board>.kicad_pcb W/vN/score --plane-nets <plane nets> --label corridor-vN`
   (add `--test-pour <ground net>:<pour layer>` on a 2-layer board). `W/vN/score` is a file prefix.
3. Read "Result valid" and the new violations in `W/vN/score.md`; use `reference/failure-repair.md` section 3.
   Do not edit tracks.
4. `"$MPL" -I render.py W/model/model.json W/vN/img --plan W/plan.json --routes W/vN/routes.json`. Open the
   images.
5. Add the attempt to `STATUS.md`. Compare its rank vector with the baseline. Report the better valid one.
   If the plan beats the baseline by less than 5 connections, run both at `--seed 2` before the claim.
6. Fill `W/REVIEW.md` from `reference/review-checklist.md` for the attempt that is reported.

## 3. Rules for the planner

- Count before you draw. `flows.md` gives the demand of every flow before any corridor exists.
- A corridor is justified by a baseline failure, a wall, or a design constraint. More corridors than that make
  the result worse: in the dry tests narrow corridors for every flow routed fewer nets than no plan.
- One layer for all long nets fails: every crossing then collides.
- Priority decides who is removed. Give a rail without a pour priority 1.
- When the design document limits a net, encode the limit in the plan and cite the design row.
- Never change the placement, the pours, the rules or the netlist. Write a request.

## 4. When routing stops short

Open connections that the repair guide cannot close are placement limits. Write each as a request with report
evidence in `REQUESTS.md` and `requests.json` (`reference/common.md` section 7). In a race, stop there: the
relief phase tests the requests. Outside a race, test the placement requests yourself with
`reference/placement-relief.md` and report the placement diff; the design owner applies it.

## 5. Limits

- The capacity check counts parallel tracks. It does not model the order in which nets enter a corridor.
- On the boards tested, the unconstrained router was the best or tied result on three of four boards. One
  corridor at a measured bottleneck gained 6 connections on the fourth. Expect a small gain, not a rescue.
- Region corridors have no capacity check.
- The router is a grid search at the fab pitch; tracks are staircases of 45-degree and straight steps.
- This skill was written for small mixed-signal power boards without high-speed nets. Revise it when the
  tools or the models change.
