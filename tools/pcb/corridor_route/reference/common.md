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
- `render.py` runs as `"$MPL" -I render.py ...`.

## 2. Work folder and file safety

- Work only in the work folder `W` that the task names. `W` holds a copy of the board with its project files
  (`.kicad_pro`, `.kicad_sch`, `.kicad_dru`, library tables, local libraries). The copy keeps the base name of
  the original board; kicad-cli finds the rules and the schematic by that name.
- Never write the original board. Never write outside `W`.
- One writer for each board file. Two agents never write the same folder.
- `apply_routes.py` writes the routed board into a sub-folder of `W` (for example `W/v3/`). Keep each attempt in
  its own sub-folder; do not overwrite an earlier attempt.
- Do not change the placement, the pours, the netlist, the schematic or the board rules. When routing needs
  such a change, write it in `W/REQUESTS.md` (section 6) and continue with what can be routed.
- Take the rule values from the board (`model_summary.md` prints them) and from the fab rule file that the
  task names. A plan value below a board minimum is a plan error. Do not loosen a rule to make a net route.

## 3. Status file

Keep `W/STATUS.md` current. A second agent must be able to resume from it alone.

```markdown
# Status
Method: <skill name>            Board: <file>            Updated: <date time>
Resume here: <the next command or decision>
| Attempt | Plan | Connections made / total | New DRC | Vias | Note |
```

Add a row for every routed attempt. Write "Resume here" before every long command.

## 4. Score and DRC

Every attempt is scored by the same script, against the unrouted board:

```bash
"$PY" score.py W/vN/<board>.kicad_pcb W/<board>.kicad_pcb W/vN/score --plane-nets <plane nets> [--test-pour NET:LAYER] --label <method>-vN
```

- Completion is counted in connections (one pad-to-pad link), not in nets. A 59-pad net has 58 connections.
- Plane nets are the nets that a plane layer or a later pour connects; they are counted separately.
- DRC is compared with the unrouted board by violation type. Only an increase is a routing defect. The
  unrouted board normally has silkscreen and thermal items of its own.
- `kicad-cli` returns a non-zero exit code for those inherited items; read the score, not the exit code.
- The rank vector is: open connections on non-plane nets, new DRC violations, extra pour islands, vias, track
  length. Lower is better, compared left to right.

## 5. Steps that agents skip

Check each line before the task is reported as complete.

- The saved board was scored (`score.md` exists for the attempt that is reported).
- New DRC violations are zero, or each remaining one is listed with its cause.
- Every open connection is listed with its class (BLOCKED or CONGESTED) and the change that would close it.
- Every net that the design constrains (Kelvin sense pairs, high-impedance nodes, guard or keep-away rules,
  short-loop nets) was checked against its design row after routing, not only planned.
- A pour was not cut into islands by a signal track (zone islands in the score).
- The images of the final attempt were looked at, layer by layer.
- No track runs under a part where the design forbids copper; connectors keep their access.
- `STATUS.md` and `REQUESTS.md` are current.

## 6. Requests for design changes

The routing agent does not move parts, swap pins or change pours. It records the need:

```markdown
# Requests
| # | Kind (placement / pin swap / pour / rule / layer / outline) | What | Why (evidence: report section, numbers) | Connections it would close |
```

A request states evidence from a report (a sealed pad, a channel with capacity 14 and demand 16, a BLOCKED
net). The session that owns the design decides.

## 7. Run time

`route_plan.py` on a 45 x 40 mm 4-layer board with 95 nets takes 5 to 15 minutes at 20 iterations; on a
24 x 38 mm 2-layer board with 34 nets, under 10 seconds. Run a command that can exceed 2 minutes in the
background. A conflict count that stays flat for 5 iterations means a full channel; stop the run and change the
plan (`--iters` may be lowered to 12 for exploration).
