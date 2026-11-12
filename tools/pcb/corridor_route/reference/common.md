# Common rules for the routing skills

This file applies to the routing skill (`board-routing`) and to the study orchestrator (`route-race`). Read it once before the first command.

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
- Always start a script with `"$PY"` (or `"$MPL"` for `render.py`). The bare command `python` is a Windows
  Store alias on this machine and does not run.
- Frames: the plan, the reports, the images and the requests use the plan frame (design coordinates, y up, when
  the plan has `frame.y_flip_offset`). `model.json`, `routes.json` and `score.md` use the KiCad frame (y down).
- Every pcbnew script prints four "Adding duplicate image handler" lines; ignore them (`2>&1 | grep -v duplicate`).

## 2. Commands

| Step | Command |
|---|---|
| Model | `"$PY" board_model.py W/<board>.kicad_pcb W/model --layers F.Cu,In2.Cu,B.Cu [--y-flip-offset Y0]` |
| Images | `"$MPL" -I render.py W/model/model.json W/img --labels [--plan P.json] [--routes R.json] [--tag NAME] [--window x0 y0 x1 y1]` |
| Flows | `"$PY" flows.py W/model/model.json W/plan.json W/flows.md` |
| Plan check | `"$PY" capacity.py W/model/model.json W/plan.json W/capacity_report.md` |
| Route | `"$PY" -u route_plan.py W/model/model.json W/plan.json W/vN/routes.json --report W/vN/route_report.md [--iters 20] [--seed 1] [--max-seconds S] [--keep-routes W/vM/routes.json] [--order cross|short|long]` |
| Staged route | `"$PY" -u staged.py staged W/model/model.json W/plan.json W/vN [--seed S]` |
| Finishing pass | `"$PY" -u staged.py finish W/model/model.json W/plan.json W/vN_fin --start W/vN/routes.json [--radius 2.0]` |
| Layer assignment | `"$PY" layer_assign.py W/model/model.json W/plan.json W/plan_la.json --report W/layer_assign.md` |
| Global routing | `"$PY" global_route.py W/model/model.json W/plan.json W/plan_g.json --report W/global.md [--tile 2.0]` |
| Seeds | `"$PY" -u seeds.py run W/model/model.json W/plan.json W/vN_seeds --seeds 1,2,3,4` and `"$PY" seeds.py compare W/A_seeds W/B_seeds` |
| Apply | `"$PY" apply_routes.py W/<board>.kicad_pcb W/vN/routes.json W/vN/board` |
| Score | `"$PY" score.py W/vN/board/<board>.kicad_pcb W/<board>.kicad_pcb W/vN/score --plane-nets <nets> [--test-pour NET:LAYER] --label <method>-vN` |

- The last four rows are the shared options of `reference/shared-options.md`. Every method may use them.
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
- DRC is compared with the unrouted board violation by violation (type, items and position). A violation that
  the unrouted board does not have is new. `score.md` lists each new violation with its position;
  `score_drc.json` is the full report.
- **Vias on SMD pads.** The router places no via on an SMD pad or inside its solder-mask opening, also not for
  the pad's own net: solder runs into the hole, and KiCad DRC does not report it. `rules.via_in_pad` in the plan
  allows it for named pads (`["U101.25"]`) or for all (`true`) when the design uses filled vias. `score.py` counts
  the added vias on SMD pads.
- **Validity.** An attempt with a new violation of any type other than `starved_thermal`, or with an added via
  on an SMD pad, is not a valid result. It cannot be reported as the best attempt, whatever its completion.
- **Valid is not finished.** A valid result still has the plane nets open and may have new starved thermals.
  A board is finished only after the finish test (`review-checklist.md`, rows 2 and 3).
- `starved_thermal` items come from tracks that pass beside a through-hole pad on a pour. The router adds a cost
  (`costs.thermal`, default 8) in a ring of `rules.thermal_keepout` (default 0.35 mm) around such pads, so a
  track enters the ring only when it has no other way. Raise `costs.thermal` to 30 if such items remain. An
  item that remains marks a lane that a net needs: report it with the net.
- Islands: only hard pours and the trial pour count, and only pieces of at least 0.5 mm2. Islands of soft ground
  fills are listed for information.
- The rank vector is: open connections on non-plane nets, new DRC violations, extra pour islands, vias that are
  not on plane or pour nets, track length. Lower is better, compared left to right.
- **Seeds.** The router reroutes in a random order after the first iteration. The same plan, model, options
  and seed give the same result. Two seeds of one plan differed by up to 9 connections on the 4-layer test
  board. One run is therefore never a result.
  - Report a plan as the mean, minimum and maximum of 4 or more seeds (`seeds.py run`), with the iteration
    limit.
  - Plan B is better than plan A only when it has fewer open connections at every one of 4 or more seeds
    (`seeds.py compare`). Anything else is "not separated".
  - Compare like with like: the same model, the same seeds, the same iteration limit, no time cap on one side.
  - A net that is open at every seed is evidence about the board. A net that is open at one seed is not.

## 6. Run time and stopping

- `route_plan.py` runs up to 60 iterations by default. It stops earlier when no conflict is left, or when the
  best conflict count has not improved for 15 iterations (after iteration 20). It then legalises the iteration
  with the fewest nets in conflict. `--max-seconds` sets a time limit; the run then still legalises and writes a
  result. Do not cap one side of a comparison.
- The same seed repeats the same iterations: `--iters 80` at the same seed repeats the first 60 and adds 20.
- The conflict count normally stays near flat for the first iterations and falls after that. Do not stop a
  run because the first iterations are flat.
- If many nets are still in conflict when the run ends ("legalising iteration N (M nets in conflict)" in the
  log), the result comes from the legalisation, not from a negotiated solution. Say so with the result.
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

A placement or pin-swap request states the move itself: for each part the old and the new position and
rotation, the frame, and the board commit (`"moves": [{"ref": "R130", "old": [29.30, 67.80, 180], "new": [24.75,
69.85, 90]}], "frame": "plan (y up, y_flip_offset 100)", "board": "cr.kicad_pcb of commit 71ecdef"`). A request
that asks for "more room at" a place, without a move, is not a placement request: file it as evidence for the
diagnosis. If a move was tested, the request describes the tested move, not a different one.

A request states evidence from a report (a sealed pad, a channel with capacity 14 and demand 16, two nets that
need the one lane at a named place in every attempt). The session that owns the design decides.

Write the same requests as data in `W/requests.json`, one entry for each row. A race merges these files.

```json
[{"id": "R-auto-s1-03",
  "kind": "placement",
  "parts": ["R101", "C101"], "pour": null, "at": [44.4, 63.4], "layer": "F.Cu",
  "what": "open a second F.Cu lane in the U101 +x pocket",
  "evidence": {"open_nets": ["/N_OV", "/N_DVDT"], "lost_to": ["/N_UV"], "capacity": 1, "demand": 2,
               "report": "v3/route_report.md, Open nets rows 3-4"},
  "closes_estimate": 2, "design_rows": ["D-09", "D-32"]}]
```

- `kind`: `plan` (a priority, corridor or direction for the next round), `placement` (move, rotate or swap
  parts), `pin_swap`, `dnp` (remove parts that are not fitted), `pour_or_rail` (`pour` names the net),
  `rule`, `layers`, `outline`.
- `parts`: the candidate parts to move, or the parts to remove. `at`: the place in plan coordinates.
- `evidence.report` is required, with `open_nets` or `capacity` and `demand`. A request without report evidence
  is not filed.
- `closes_estimate` is an estimate. It is never passed on as a fact; the race tests the request.
- `design_rows`: the rows that the design owner must check for this change.

The routing agent may test a placement request itself after its stop rule, outside a race, with
`reference/placement-relief.md`. In a race, relief runs in its own phase; routing workers do not move parts.

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
- `STATUS.md`, `REQUESTS.md`, `requests.json` and `REVIEW.md` are current, and every request has report
  evidence.
