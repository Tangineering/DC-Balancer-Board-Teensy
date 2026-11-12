# Placement relief

Placement relief is a stage that follows routing with any method. It tests small part moves at a place where
routing lost connections, on a scratch copy, and reports the moves that help as a placement diff. It never
edits the board that it was given, and it never applies a move to the project: the design owner does that.

Use it when a routed result has CONGESTED nets at a named place and the repair guide gives no plan remedy (two
nets need one lane; a channel at capacity with no second layer). In a race the orchestrator starts one relief
worker for each site (`route-race`, relief phase). Outside a race, the agent that routed runs it itself after
its stop rule.

## 1. Inputs

- The site: a place (x, y, layer), the open nets there, the nets they lost to, and the candidate parts
  (from `requests.json` or `change_requests.json`).
- The start result: the board copy, its `model.json`, the plan and the `routes.json` of the best valid attempt.
- The move limits of the task. Defaults:
  - translation of one part by at most 0.5 mm in total;
  - rotation by 90 or 180 degrees;
  - swap of two parts with the same footprint;
  - only parts without fixed coordinates in the design document. Never a connector, a wire pad, a test pad, a
    mounting hole, a part that the brief lists as fixed, or a keep-out.
  - a part outside these limits is not moved; the need is written as a request.
- The project's constraint check, if the brief names one (for this project:
  `python check_constraints.py <board name> <project folder>` from the design session's `gen` folder, read-only).

## 2. Procedure

Work in `W/relief/<site>/`. One move for each trial; keep each trial in its own folder `mN`.

1. State the hypothesis in `STATUS.md`: which lane or via site is missing, and which move would open it.
   Look at the image window of the site first
   (`render.py ... --routes <routes.json> --window x0 y0 x1 y1 --labels`).
2. Make the move on a copy:
   `"$PY" whatif.py move W/<board>.kicad_pcb W/relief/<site>/mN --part REF --dx DX --dy DY [--rot R] [--y-flip-offset Y0]`.
   If the output says the move is not legal, discard the trial. Do not route it.
3. Run the constraint check on the copy. A row that passed before and fails now rejects the move.
4. Model the copy: `board_model.py W/relief/<site>/mN/<board>.kicad_pcb W/relief/<site>/mN/model ...`.
5. Route with the earlier routes kept:
   `route_plan.py .../mN/model/model.json W/plan.json .../mN/routes.json --report .../mN/route_report.md --keep-routes <start routes.json>`.
   Nets whose old copper is still legal on the moved board stay as they were; the nets at the moved part and the
   open nets are routed.
6. **Acceptance test.** The move is accepted when both hold:
   - the open nets named for the site are complete in `mN/route_report.md`;
   - no net that was complete in the start result is open now.
   Do not judge a move by the total of open connections alone: the noise of a full run is 2 to 4 connections, and
   one site is worth 1 or 2.
7. Confirm an accepted move: `apply_routes.py mN/<board>.kicad_pcb mN/routes.json mN/board`, then `score.py
   mN/board/<board>.kicad_pcb mN/<board>.kicad_pcb mN/score ...` (the moved copy without routes is the
   baseline). The result must be valid.
8. If the move is rejected, try the next candidate (another part, the other direction, a rotation). At most 5
   trials for a site. If none is accepted, the site stays a request with the trials as evidence.
9. For a second site in the same folder, start from the accepted trial of the first site.

## 3. Output

`W/relief/<site>/placement_diff.json` and a table in `W/relief/<site>/RELIEF.md`:

```json
[{"ref": "R101", "old": {"x": 44.10, "y": 62.80, "rot": 0}, "new": {"x": 44.10, "y": 63.20, "rot": 0},
  "move": "dy +0.40", "drc_added": {}, "constraint_check": "pass (all rows that passed before)",
  "site": [44.4, 63.4], "nets_closed": ["/N_OV"], "nets_lost": [], "trial": "m3", "valid": true}]
```

Report the rejected trials too (move, reason). A diff is a tested request, not a change: the design owner
checks the design rows and applies it in the project's own generator.

## 4. Limits

- The test proves that the named nets route after the move with the rest of the board held as it was. It does
  not prove that a full new run closes more connections; the next race round on the new placement shows that.
- A move changes thermal, loop-area and assembly properties that this procedure does not see. The constraint
  check and the design owner cover those.
- Removing parts (DNP) and adding pours are not placement relief. Test them with `whatif.py holdout` and send
  them as requests.
