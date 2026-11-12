# Placement relief

Placement relief tests part moves at one place where routing lost connections, on scratch copies, and reports
the moves that a script accepts as a placement diff. It never edits the board that it was given, and it never
applies a move to the project: the design owner does that.

Use it for a site that the diagnosis names as a lane of at most 3 nets (two nets need one lane; a pad row with
one escape). A site with many nets, or a net that is open at several places, is not a relief site: test it with
a hold-out or a re-placement variant (`route-race` section 4).

## 1. Inputs

- The site: a place (x, y, layer) in the plan frame, the nets that are open there at every seed, the nets that
  take the space, and the candidate parts.
- The start result: the board copy, its `model.json`, the plan and the `routes.json` of one scored seed.
  **Refresh the site from this result first**: a net that the request names but that is complete in
  `route_report.md` of the start result is not part of the site.
- The move limits of the task. Defaults for scratch tests (operator ruling of 2026-11-11):
  - translation of one part by at most 2.0 mm;
  - rotation by 90 or 180 degrees;
  - swap of two parts with the same footprint;
  - only parts without fixed coordinates in the design document. Never a connector, a wire pad, a test pad, a
    mounting hole, a part that the brief lists as fixed, or a keep-out.
  - A re-pack of a block of parts is not a relief move. It is a re-placement variant.
- The project's constraint check, if the brief names one.

## 2. Frames

- The plan, the reports (`route_report.md`, `capacity_report.md`, `global.md`), the images and the requests
  use the **plan frame**: design coordinates with y up when the plan states `frame.y_flip_offset` (y = offset −
  KiCad y).
- `model.json`, `routes.json`, `score.md` and KiCad itself use the **KiCad frame** (y down).
- `whatif.py move --dx --dy` and `relief_trial.py --site` take plan-frame values when `--y-flip-offset` is
  given to `whatif.py move`. State the frame beside every coordinate that you write.

## 3. Procedure

Work in `W/relief/<site>/`. One move for each trial; each trial in its own folder `mN`. At most 5 trials.

1. State the hypothesis in `STATUS.md`: which lane or via site is missing, and which move would open it. Look
   at the image window of the site first
   (`render.py ... --routes <routes.json> --window x0 y0 x1 y1 --labels`).
2. Make the move on a copy:
   `"$PY" whatif.py move W/<board>.kicad_pcb W/relief/<site>/mN --part REF --dx DX --dy DY [--rot R] [--y-flip-offset Y0]`.
   The script compares the DRC of the moved copy with a refilled copy of the start board. If it says that the
   move is not legal, discard the trial. Do not route it.
3. Run the constraint check on the copy. A row that passed on the start board and fails now rejects the move.
4. Model the copy: `"$PY" board_model.py W/relief/<site>/mN/<board>.kicad_pcb W/relief/<site>/mN/model ...`.
5. Let the script judge the move:
   `"$PY" -u relief_trial.py W/model/model.json W/relief/<site>/mN/model/model.json W/plan.json <start routes.json> W/relief/<site>/mN/trial --site X,Y,R --nets <site nets>`.
   - `R` is the radius around the site inside which kept nets are routed again (1.5 to 3 mm: enough to free the
     nets that hold the lane, not more).
   - The script routes a control (no move) and the trial with the same options at 4 seeds, and prints
     ACCEPTED or REJECTED with the rule that failed (`TRIAL.md`). Do not accept or reject a move by your own
     reading of the counts.
6. Confirm an accepted move: apply and score the trial routes of one seed
   (`apply_routes.py mN/<board>.kicad_pcb mN/trial/trial_s1/routes.json mN/board`, then `score.py
   mN/board/<board>.kicad_pcb mN/<board>.kicad_pcb mN/score ...`). The result must be valid.
7. If the move is rejected, try the next candidate (another part, the other direction, a rotation).
8. "Gain without closure" is reported as its own request (a gain elsewhere on the board), not as relief of
   the site.

## 4. Output

`W/relief/<site>/placement_diff.json` (accepted moves only; an empty list if none) and a table of all trials
in `W/relief/<site>/RELIEF.md`.

```json
[{"ref": "R101", "frame": "plan (y up, y_flip_offset 100)",
  "old": {"x": 44.10, "y": 62.80, "rot": 0}, "new": {"x": 44.10, "y": 63.10, "rot": 0}, "move": "dy +0.30",
  "tested_on": "cr.kicad_pcb of commit 71ecdef", "drc_added": {}, "constraint_check": "41 rows pass, as before",
  "site": [44.9, 63.4, 1.5], "nets_closed": ["/N_DVDT"], "nets_lost": [], "trial": "m3/trial/TRIAL.md",
  "verdict": "ACCEPTED", "valid": true}]
```

A diff is a tested request, not a change: the design owner checks the design rows and applies it in the
project's own generator. A site without an accepted move stays a request, with the trials as evidence and a
statement of what the site needs (a larger move, a re-pack, a pour change).

## 5. Limits

- The trial shows the effect of the move with the rest of the board held. Only the next round on the new
  placement shows the effect of a full run.
- A move changes thermal, loop-area and assembly properties that this procedure does not see. The constraint
  check and the design owner cover those.
- In the dry test on the CR board, with a limit of 0.5 mm, moves, rotations and swaps gave no accepted change
  at four sites. Three of the four sites needed a change of another kind. The limit was raised to 2.0 mm after
  that test.
- Removing parts (DNP) and adding pours are not placement relief. Test them with `whatif.py holdout` and send
  them as requests.
