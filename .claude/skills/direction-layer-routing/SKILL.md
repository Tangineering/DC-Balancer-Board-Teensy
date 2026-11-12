---
name: direction-layer-routing
description: Route the signal nets of a placed KiCad board with the classic layer discipline - each routing layer gets a preferred direction, a net changes layer where it turns, and the agent tunes layer directions, layer costs, via cost and priorities instead of drawing corridors. Use it when the user asks for "direction per layer", "Manhattan routing", "H/V layers", or as one method of the route-race skill. Do not use it for placement or for power pours.
---

# Direction-per-layer routing

Crossing nets do not collide when one runs along x on one layer and the other runs along y on another layer.
This method plans no corridors. The agent chooses a direction for each layer, the cost of each layer, the cost
of a via and the priority of each net class; the router does the rest on the whole board.

Read `tools/pcb/corridor_route/reference/common.md` first. The plan format is in
`reference/plan-format.md` (keys `directions`, `layer_cost`, `costs`, group `layers`).

## 1. Inputs and outputs

- Input: a work folder `W` with a copy of a placed board whose power copper is in place.
- Output in `W`: `plan.json`, `flows.md`, `capacity_report.md`, `route_report.md`, a routed board and `score.md`
  for each attempt, images, `STATUS.md`, `REQUESTS.md` with `requests.json`, `REVIEW.md`.

## 2. Procedure

### Step 0. Model the board

1. `"$PY" board_model.py W/<board>.kicad_pcb W/model --layers <routing layers> [--y-flip-offset Y0]`.
2. `"$MPL" -I render.py W/model/model.json W/img --labels`. Open every layer image.
3. Read `W/model/model_summary.md` and `reference/four-layer.md` or `reference/two-layer.md`.

### Step 1. Choose the directions

1. Add `regions` to a draft plan and run `"$PY" flows.py W/model/model.json W/plan.json W/flows.md`.
2. Find the narrowest channel of the board (an outline neck, a gap row in a through-hole wall, the strip
   beside a strap) and the direction in which the flows pass it. That direction decides, not the count of long
   nets.
3. Assign directions:
   - 4-layer board (routing layers L1, L3, L4): the inner layer takes the direction of the flows through the
     narrowest channel. One outer layer takes the other direction. The third layer is `any` and serves the
     local nets. The second assignment to try ("the swap") exchanges the directions of the inner layer and
     that outer layer.
   - 2-layer board: both layers `any`, pour layer `layer_cost` 4 to 8 and `costs.via` 20
     (`reference/two-layer.md`). A preferred direction on the pour layer made more pour islands in the dry
     tests; do not set one. On a 2-layer board this method is cost tuning, and there is no swap.
4. Classify the nets (`reference/net-classes.md`). The groups of constrained nets set every layer to `any`
   (`"directions": {"F.Cu": "any", "In2.Cu": "any", "B.Cu": "any"}`). Rail without a pour: priority 1,
   `mode: free`.
5. Default group: `{"mode": "free", "priority": 5}`.
6. Write `W/plan.json`. Start with `"costs": {"via": 10, "direction": 3}`.

### Step 2. Check and route

1. `"$PY" capacity.py W/model/model.json W/plan.json W/capacity_report.md`. If check 1 prints a GRID message,
   set `rules.res` as it says. Sealed pads become requests. Read check 6 (congestion): a cell above 0.6 is
   where the directions matter most.
2. `"$PY" -u route_plan.py W/model/model.json W/plan.json W/routes.json --report W/route_report.md`.
3. Apply, score and render as in `reference/common.md` section 2 (attempt folder `W/vN`, label
   `direction-vN`). The first attempt is the unconstrained baseline (no `directions`), for comparison.

### Step 2a. Layer assignment from crossings

Run `layer_assign.py` on the baseline plan (`reference/shared-options.md` section 4) and route
`W/plan_la.json` as one attempt, without `directions`. On a 2-layer board add the `--layer-weight` of the pour
layer. Compare it with the baseline and with the direction plan: connections, and on a 2-layer board the pour
islands. A direction plan and a layer assignment may be combined only after each was tested alone.

### Step 3. Tune

Change one thing for each attempt and record it in `STATUS.md`.

| Sign in `route_report.md` and the images | Change |
|---|---|
| Open nets cluster where two flows cross on one layer | Swap the directions of the two layers that serve that area, or give the group of one flow a `directions` override |
| Many vias, short stubs between them | Raise `costs.via` (15 to 25) |
| Nets detour far to stay on a layer, and the inner layer is not the full one | Lower `costs.direction` (2). Do not lower `costs.via` when the inner layer is full: it sends more nets there |
| Open nets cluster on the inner layer, lost to priority-1 local nets | `layer_cost` 2 on the inner layer for the constrained groups |
| New `starved_thermal` items | `costs.thermal` 30 |
| More pour islands than the baseline | `reference/failure-repair.md` section 3 |
| A dense block has no via sites left | `layer_cost` above 1 on the layer that the block's parts occupy, for the long nets only (a group) |
| Local nets block the long nets | A group for the local nets of that area with `mode: local`, a `margin` of 1.5 and priority 3 |
| One rail is in conflict with many nets | Priority 1 for the rail; a request for a pour |
| Conflict count flat from the first iterations | `reference/failure-repair.md`, last rows: capacity, not direction |

Use the repair classes of `reference/failure-repair.md` for single nets. Stop when every connection is made,
or when two consecutive attempts do not reduce the open connections by more than the noise band
(`reference/common.md` section 5). On a 4-layer board try the swap once, unless `flows.md` shows one clearly
dominant direction through the narrowest channel. Report the baseline if no direction plan beats it. On the best attempt, run a finishing pass
(`reference/shared-options.md` section 3).

### Step 4. Review

Fill `W/REVIEW.md` from `reference/review-checklist.md` for the attempt that is reported.

## 3. When routing stops short

Open connections that the repair guide cannot close are placement limits. Write each as a request with report
evidence in `REQUESTS.md` and `requests.json` (`reference/common.md` section 7). In a race, stop there: the
relief phase tests the requests. Outside a race, test the placement requests yourself with
`reference/placement-relief.md` and report the placement diff; the design owner applies it.

## 4. Limits

- The direction is a cost, not a rule. Near pads every net moves in any direction.
- The method has no capacity check for a bottleneck. If `capacity.py` check 6 or the report shows one channel
  that is full, the corridor method diagnoses it better.
- This skill was written for small mixed-signal power boards without high-speed nets. Revise it when the
  tools or the models change.
