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
  for each attempt, images, `STATUS.md`, `REQUESTS.md`, `REVIEW.md`.

## 2. Procedure

### Step 0. Model the board

1. `"$PY" board_model.py W/<board>.kicad_pcb W/model --layers <routing layers> [--y-flip-offset Y0]`.
2. `"$MPL" -I render.py W/model/model.json W/img --labels`. Open every layer image.
3. Read `W/model/model_summary.md` and `reference/four-layer.md` or `reference/two-layer.md`.

### Step 1. Choose the directions

1. Add `regions` to a draft plan and run `"$PY" flows.py W/model/model.json W/plan.json W/flows.md`.
2. Find the dominant direction of the long flows (the axis along which most flow nets travel) and the direction
   in which the walls let tracks pass (a through-hole column passes tracks across it, between its pads).
3. Assign directions:
   - 4-layer board (routing layers L1, L3, L4): the inner layer takes the dominant direction of the long
     flows. The outer layer with fewer parts takes the other direction. The third layer is `any` and serves
     the local nets.
   - 2-layer board: the signal layer is `any`; the pour layer takes the direction of the long axis of the pour
     and a `layer_cost` of 3 to 5, so that bridges are short and parallel (`reference/two-layer.md`).
4. Classify the nets (`reference/net-classes.md`). Constrained nets: priority 1, `mode: local`, small margin,
   `directions` override `any` for their group. Rail without a pour: priority 1, `mode: free`.
5. Default group: `{"mode": "free", "priority": 5}`.
6. Write `W/plan.json`. Start with `"costs": {"via": 10, "direction": 3}`.

### Step 2. Check and route

1. `"$PY" capacity.py W/model/model.json W/plan.json W/capacity_report.md`. Sealed pads become requests.
   Read check 6 (congestion): a cell above 0.6 is where the directions matter most.
2. `"$PY" -u route_plan.py W/model/model.json W/plan.json W/routes.json --report W/route_report.md`.
3. Apply and score as in `reference/common.md` section 4 (attempt folder `W/vN`, label `direction-vN`).

### Step 3. Tune

Change one thing for each attempt and record it in `STATUS.md`.

| Sign in `route_report.md` and the images | Change |
|---|---|
| Open nets cluster where two flows cross on one layer | Swap the directions of the two layers that serve that area, or give the group of one flow a `directions` override |
| Many vias, short stubs between them | Raise `costs.via` (15 to 25) |
| Nets detour far to stay on a layer | Lower `costs.via` (5 to 8) or lower `costs.direction` (2) |
| A dense block has no via sites left | `layer_cost` above 1 on the layer that the block's parts occupy, for the long nets only (a group) |
| Local nets block the long nets | A group for the local nets of that area with `mode: local`, a `margin` of 1.5 and priority 3 |
| One rail is in conflict with many nets | Priority 1 for the rail; a request for a pour |
| Conflict count flat from the first iterations | `reference/failure-repair.md`, last rows: capacity, not direction |

Use the repair classes of `reference/failure-repair.md` for single nets. Stop when every connection is made,
or when two consecutive attempts do not reduce the open connections. Try at least the two direction
assignments (dominant direction on the inner layer, and the swap) before stopping.

### Step 4. Review

Fill `W/REVIEW.md` from `reference/review-checklist.md` for the attempt that is reported.

## 3. Limits

- The direction is a cost, not a rule. Near pads every net moves in any direction.
- The method has no capacity check for a bottleneck. If `capacity.py` check 6 or the report shows one channel
  that is full, the corridor method diagnoses it better.
- This skill was written for small mixed-signal power boards without high-speed nets. Revise it when the
  tools or the models change.
