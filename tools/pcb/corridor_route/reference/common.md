# Common rules for the routing skills

This file applies to every routing method skill (`corridor-routing`, `direction-layer-routing`,
`autorouter-routing`) and to the orchestrator (`route-race`). Read it once before the first command.

## 1. Environment

```bash
export MSYS_NO_PATHCONV=1            # net names such as /GND are not paths
export PYTHONDONTWRITEBYTECODE=1     # the scripts write nothing into the repository
PY="C:/Life Ops/School/Thesis/DC-Balancer-round4/tools/pcb/.venv/Scripts/python.exe"   # pcbnew, numpy, shapely
MPL="C:/Users/ricky/miniforge3/python.exe"                                             # matplotlib (render.py only)
T="<repository root>/tools/pcb/corridor_route"
```

- Write every path as `C:/...`. With `MSYS_NO_PATHCONV=1` a path written as `/c/...` reaches Python unchanged
  and the board does not load.
- Run the scripts with `cd "$T"` first; they import `core.py` and `engine.py` from that folder.
- The interpreter `PY` belongs to another checkout. If it does not exist, read `tools/pcb/TOOLCHAIN.md`
  section 2 and stop; do not install packages.
- Every pcbnew script prints four "Adding duplicate image handler" lines; ignore them (`2>&1 | grep -v duplicate`).

## 2. Commands

| Step | Command |
|---|---|
| Model | `"$PY" board_model.py W/<board>.kicad_pcb W/model --layers F.Cu,In2.Cu,B.Cu [--y-flip-offset Y0]` |
| Images | `"$MPL" -I render.py W/model/model.json W/img --labels [--plan P.json] [--routes R.json] [--tag NAME] [--window x0 y0 x1 y1]` |
| Flows | `"$PY" flows.py W/model/model.json W/plan.json W/flows.md` |
| Plan check | `"$PY" capacity.py W/model/model.json W/plan.json W/capacity_report.md` |
| Route | `"$PY" -u route_plan.py W/model/model.json W/plan.json W/vN/routes.json --report W/vN/route_report.md [--iters 20] [--seed 1] [--max-seconds S] [--keep-routes W/vM/routes.json]` |
| Apply | `"$PY" apply_routes.py W/<board>.kicad_pcb W/vN/routes.json W/vN/board` |
| Score | `"$PY" score.py W/vN/board/<board>.kicad_pcb W/<board>.kicad_pcb W/vN/score --plane-nets <nets> [--test-pour NET:LAYER] --label <method>-vN` |

- `render.py` takes the file `model.json`, not the folder. With `--routes` give the plan of the same attempt.
- `apply_routes.py` takes an output folder; the routed board keeps the input's file name inside it.
- `score.py` takes an output prefix: `W/vN/score` writes `W/vN/score.md`, `score.json` and `score_drc.json`.

## 3. Work folder and file safety

- Work only in the work folder `W` that the task names. `W` holds a copy of the board with its project files
  (`.kicad_pro`, `.kicad_sch`, `.kicad_dru`, library tables, local libraries). The copy keeps the base name of
  the original board; kicad-cli finds the rules and the schematic by that name.
- Never write the original board. Never write outside `W`.
- One writer for each board file. Two agents never write the same folder.
- Keep each attempt in its own sub-folder (`W/v1`, `W/v2`, ...); do not overwrite an earlier attempt.
- Do not change the placement, the pours, the netlist, the schematic or the board rules. When routing needs
  such a change, write it in `W/REQUESTS.md` (section 7) and continue with what can be routed.
- Take the rule values from the board (`model_summary.md` prints the board setup and the custom rule file) and
  from the fab rule file that the task names. A plan value below a board minimum is a plan error. Do not loosen
  a rule to make a net route.

## 4. Status file

Keep `W/STATUS.md` current. A second agent must be able to resume from it alone.

```markdown
# Status
Method: <skill name>            Board: <file>            Updated: <date time>
Resume here: <the next command or decision>
Constrained nets: <net: design row or "no design row; classed from name and parts">
| Attempt | Plan | Seed | Connections made / total | New DRC | Valid | Vias | Note |
```

Add a row for every routed attempt. Write "Resume here" before every long command.

## 5. Score, validity and noise

- Completion is counted in connections (one pad-to-pad link), not in nets. A 59-pad net has 58 connections.
- Plane nets are the nets that a plane layer or a later pour connects; they are counted separately. Their open
  count rises when tracks cut a soft ground fill; that is expected before the project's plane-via step.
- DRC is compared with the unrouted board by violation type. Only an increase is a routing defect. `score.md`
  lists each new violation with its position; `score_drc.json` is the full report.
- **Validity.** An attempt with a new violation of any type other than `starved_thermal` is not a valid result.
  It cannot be reported as the best attempt, whatever its completion.
- `starved_thermal` items come from tracks that pass beside a through-hole pad on a pour. The router adds a cost
  (`costs.thermal`, default 8) in a ring of `rules.thermal_keepout` (default 0.35 mm) around such pads, so a
  track enters the ring only when it has no other way. Raise `costs.thermal` to 30 if such items remain. An
  item that remains marks a lane that a net needs: report it with the net.
- Islands: only hard pours and the trial pour count, and only pieces of at least 0.5 mm2. Islands of soft ground
  fills are listed for information.
- The rank vector is: open connections on non-plane nets, new DRC violations, extra pour islands, vias that are
  not on plane or pour nets, track length. Lower is better, compared left to right.
- **Noise.** The router reroutes in a random order after the first iteration. Two seeds of one plan differ by
  about 2 to 4 connections on a board that does not close, and by a few vias on one that does. A difference
  inside that band is not a result. Before one plan is reported as better than another by less than 5
  connections, run both at a second seed (`--seed 2`) and compare the means.

## 6. Run time and stopping

- `route_plan.py` runs 20 iterations by default. It stops earlier when no conflict is left, or when the best
  conflict count has not improved for 8 iterations (after iteration 10). `--max-seconds` sets a time limit;
  the run then still legalises and writes a valid result.
- The conflict count normally stays near flat for the first 6 to 8 iterations and falls after that. Do not stop a
  run because the first iterations are flat.
- Time for 20 iterations: 45 x 40 mm 4-layer board with 95 nets at a 0.127 mm grid, 8 to 16 minutes (longer when
  other jobs run); 24 x 38 mm 2-layer board with 34 nets, 5 to 30 seconds at the default grid, minutes at a
  quarter of it. Run a command that can exceed 2 minutes in the background and follow its log.
- On a 4-layer board, draft the next plan while a run is in progress.

## 7. Requests for design changes

The routing agent does not move parts, swap pins or change pours. It records the need:

```markdown
# Requests
| # | Kind (placement / pin swap / pour / rule / layer / outline) | What | Why (evidence: report section, numbers) | Connections it would close |
```

A request states evidence from a report (a sealed pad, a channel with capacity 14 and demand 16, two nets that
need the one lane at a named place in every attempt). The session that owns the design decides.

## 8. Steps that agents skip

Check each line before the task is reported as complete.

- The attempt that is reported was scored, and `score.md` says "Result valid: yes".
- Every open connection is listed with its class (BLOCKED or CONGESTED), the place, and the request that would
  close it.
- Every constrained net was checked after routing against its design row, with the routed length, layers and via
  count from the "Priority-1 nets" table of `route_report.md`. If the design gives no row, say so and report
  the numbers.
- A hard pour was not cut into islands (score, "Pour islands").
- The images of the reported attempt were opened, layer by layer.
- A claim that one plan beats another rests on more than the noise band (section 5).
- `STATUS.md`, `REQUESTS.md` and `REVIEW.md` are current.
