---
name: corridor-routing
description: Route a placed KiCad board the way a person routes by hand — plan regions and corridors first, check their capacity, assign nets to corridors, then let a script produce the copper inside those corridors. Use this when a board must be routed without the KiCad GUI and a batch autorouter (Freerouting, an unconstrained grid router) stalls or leaves many connections unrouted, when the user says "route by hand", "plan corridors", "corridor routing", or asks why a board will not route. Do not use it for placement, for power pours, or for a board that an autorouter already completes cleanly.
---

# Corridor routing

This skill routes the signal nets of a placed board in two levels. The agent makes the global decisions that a
person makes with a pencil: which regions exchange signals, which corridor carries them, on which layer, and
with what priority. Scripts make every geometric decision: capacity, track coordinates, clearances. The agent
never writes a track coordinate.

The plan is the product. Copper is compiled from the plan, and every routing failure is repaired by a change to
a plan entry, never by a change to the copper.

## 1. Scope and inputs

- Input: a placed `.kicad_pcb` with its power copper (pours, straps, locked tracks and vias) already in place.
- Kept nets: every net that has a pour (zone) and every net in `keep_nets` is not routed. The plane net (for
  example GND on a board with a solid plane layer) is connected by the project's own plane-via step.
- Output: `plan.json`, `capacity_report.md`, `route_report.md`, `routes.json`, plan images, and a routed copy of
  the board. The skill never overwrites the input board.
- Tools: `tools/pcb/corridor_route/` (`board_model.py`, `capacity.py`, `route_plan.py`, `apply_routes.py`,
  `render.py`, `core.py`). Read `tools/pcb/TOOLCHAIN.md` for the interpreters.

```bash
PY="/c/Life Ops/School/Thesis/DC-Balancer-round4/tools/pcb/.venv/Scripts/python.exe"   # pcbnew + numpy + shapely
MPL="/c/Users/ricky/miniforge3/python.exe"                                              # matplotlib (render.py)
T=tools/pcb/corridor_route
```

Run the scripts from the `tools/pcb/corridor_route` folder (they import `core.py`). Work in a scratch folder
`W` that holds a copy of the board; set `export MSYS_NO_PATHCONV=1` in Git Bash when a net name such as `/GND`
appears on a command line.

## 2. Procedure

### Step 0. Model the board

1. Copy the board and its project files to the work folder `W`.
2. Run `"$PY" board_model.py W/board.kicad_pcb W/model --layers <routing layers> [--y-flip-offset Y0]`.
   Give `--y-flip-offset` when the design documents use a y-up frame (KiCad y = Y0 - design y). The plan then
   uses design coordinates.
3. Run `"$MPL" -I render.py W/model/model.json W/img --labels` and look at every layer image.
4. Read `W/model/model_summary.md`: the nets with their pads, and the parts.

### Step 1. Plan regions and corridors

1. Name the regions of the board: each cluster of parts that exchanges signals with another cluster.
2. List the signal flows between regions and count the nets in each flow from the net table.
3. Find the walls: rows of through-hole pads, pours of kept nets, keep-outs, dense part rows. A wall has gaps;
   each gap passes a fixed number of tracks per layer.
4. Draw one corridor for each flow: a polyline with a width, on one layer (or a list of layers). Put the
   corridor where the layer is open in the image. Keep a corridor on one layer from end to end where possible;
   change layers at a corridor end, inside an escape disc.
5. Give two flows that cross different layers. Give two flows that run side by side one shared corridor or two
   parallel corridors on one layer.
6. Leave short nets (both pads within a few millimetres: decouplers, dividers, feedback parts) to the default
   mode `local`. Do not draw corridors for them.
7. Write `W/plan.json` (section 3).

### Step 2. Check the plan

1. Run `"$PY" capacity.py W/model/model.json W/plan.json W/capacity_report.md`.
2. If section 2 of the report lists sealed pads, stop. A sealed pad needs a placement change, a smaller pad
   or pour, or a finer rule set. Report it; do not route.
3. If a corridor is over capacity, change the plan: widen it, move it, add a second layer, or split the flow
   over two corridors. Do not lower the demand by leaving nets out.
4. If section 4 lists a pad that does not reach its corridor, extend the corridor to the pad or raise the
   group's `escape`.
5. Run `render.py` with `--plan W/plan.json` and look at the corridors on each layer.
6. Do steps 1 to 5 again until the report says PASS. Prefer a capacity margin of 2 or more.

### Step 3. Route

1. Run `"$PY" -u route_plan.py W/model/model.json W/plan.json W/routes.json --report W/route_report.md`.
   Use `--only-groups a,b` to route some groups first when you tune one corridor.
2. Read `W/route_report.md`. A net with "no path" has an allowed region that does not connect its pads. A
   "dropped" net lost a contested corridor; the report names the corridor and the location.
3. Repair the plan entry that the report names: move or widen the corridor, move a group to another corridor
   or layer, raise the priority of the group that must win, or raise `escape`. Then do Step 2 and Step 3
   again.
4. Stop when every net is routed, or when two consecutive plan repairs do not reduce the unrouted count. In the
   second case report the unrouted nets, the contested corridors and the change that would be needed
   (placement, rules, layer count, outline). That report is a valid result.

### Step 4. Apply and verify

1. Run `"$PY" apply_routes.py W/board.kicad_pcb W/routes.json W/board_routed.kicad_pcb`.
2. Run the project's plane-via and stitching step if the board has a plane net.
3. Run DRC: `kicad-cli pcb drc --severity-all --schematic-parity --exit-code-violations`.
4. For each violation, find the plan entry that caused it and change that entry. Do not edit tracks.
5. Run `render.py` with `--plan` and `--routes` and show the images to the operator.
6. Record the final plan and the reports with the board. Record each corridor in the layout decision log.

## 3. Plan file

```json
{
  "frame": {"y_flip_offset": 100.0},
  "rules": {"track": 0.127, "clear": 0.127, "via": 0.6, "drill": 0.3, "res": 0.1},
  "keep_nets": ["/GND"],
  "plane_net": "/GND",
  "corridors": [
    {"id": "TAPS_L3", "layer": "In2.Cu", "path": [[52.0, 62.0], [44.0, 50.0], [30.0, 50.0]], "width": 3.0,
     "note": "tab X taps to the interior, through the header wall"},
    {"id": "LOGIC", "layers": ["F.Cu", "B.Cu"], "polygon": [[18, 67], [37, 67], [37, 76], [18, 76]]}
  ],
  "groups": [
    {"name": "taps", "nets": ["/H1_RB", "/H2C_RB"], "route": ["TAPS_L3"], "escape": 2.5, "priority": 2},
    {"name": "analog", "nets": ["/N_H1P"], "mode": "local", "margin": 1.5, "priority": 1}
  ],
  "default": {"mode": "local", "margin": 2.5, "escape": 1.5, "priority": 5}
}
```

- `frame.y_flip_offset`: omit it to write the plan in the KiCad frame.
- `rules`: track width, clearance, via diameter and drill, grid pitch (mm). Use the fab rule values.
- A **path corridor** (`path` + `width`) gets a capacity check. A **region corridor** (`polygon`) does not; use
  it for an area where a group may route freely on the listed layers.
- A group's `route` lists the corridors its nets may use. Mode `corridor` is implied. The nets may also use an
  escape disc of radius `escape` around each of their pads, on every routing layer.
- Mode `local`: the bounding box of the net's pads plus `margin`, every layer. Mode `free`: the whole board.
- `priority`: a lower number routes first and is dropped last. Use 1 for the nets that the design constrains
  (Kelvin, high-impedance, short-loop nets), 5 for ordinary logic.

## 4. Rules for the planner

- Count before you draw. The demand of a corridor is known from the net table before any geometry exists.
- A through-hole wall is planned as gaps. State which gap and which layer each corridor uses.
- Do not send two flows through one bottleneck when another gap is free.
- Keep constrained nets out of shared corridors. Give them `local` mode with a small margin, or their own
  corridor, and priority 1.
- When the design document places a limit on a net (length, layer, distance from a noisy region), encode the
  limit in the corridor geometry and cite the design row in the corridor `note`.
- Never change the placement, the pours, the rules or the netlist from inside this skill. Report the need and
  stop.

## 5. Limits

- The capacity check counts parallel tracks across a corridor. It does not model the order in which nets enter
  and leave, so a corridor at margin 0 can still fail in routing.
- The coverage check is two-dimensional. It does not prove that a via fits where a net changes layer.
- The detailed router is a grid search. Its tracks follow the grid; a fine grid (`res` 0.05) costs four times
  the run time of 0.1.
