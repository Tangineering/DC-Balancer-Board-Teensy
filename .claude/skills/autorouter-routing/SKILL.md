---
name: autorouter-routing
description: Route the signal nets of a placed KiCad board with batch autorouters and no manual plan - the negotiated-congestion grid router with priorities and a recovery pass, and Freerouting as an optional reference. Use it when the user asks to "autoroute", "run Freerouting", "use the autorouter pipeline", for a quick first result on a new board, or as one method of the route-race skill. Do not use it for placement or for power pours.
---

# Autorouter routing

This is the batch method: no regions, no corridors. It gives the reference result that the planned methods must
beat, and on an easy board it is the fastest way to a complete route.

Read `tools/pcb/corridor_route/reference/common.md` first.

## 1. Inputs and outputs

- Input: a work folder `W` with a copy of a placed board whose power copper is in place.
- Output in `W`: one sub-folder for each attempt with the routed board and `score.md`; `STATUS.md`;
  `REQUESTS.md` with `requests.json`; `REVIEW.md`.

## 2. Procedure

### Variant A. Congestion router (the main variant)

1. `"$PY" board_model.py W/<board>.kicad_pcb W/model --layers <routing layers> [--y-flip-offset Y0]`.
2. Read `W/model/model_summary.md`. Write `W/plan_a.json`:
   `{"frame": {...}, "rules": {...}, "keep_nets": [...], "plane_net": "...", "default": {"mode": "free", "priority": 5}}`.
   - 4-layer board: a net flagged NO POUR goes into a group with `"mode": "free", "priority": 1`.
   - 2-layer board: use `reference/two-layer.md` section 2 (pour-layer `layer_cost`, `costs.via` 20, the ground
     net at priority 9). This method may set costs and priorities; it does not draw corridors or directions.
   - Constrained nets: one group, `reference/net-classes.md`.
3. `"$PY" capacity.py W/model/model.json W/plan_a.json W/capacity_a.md`. If check 1 prints a GRID message, set
   `rules.res` as it says. Sealed pads become requests.
4. Route at 4 seeds: `"$PY" -u seeds.py run W/model/model.json W/plan_a.json W/a --seeds 1,2,3,4` (in the
   background). Read `W/a/SEEDS.md`. Apply and score the best seed (`reference/common.md` section 2), label
   `auto-A`. If the task gives one seed, run that seed only and say that the result is one run.

### Variant S. Staged (a diagnostic, only when the task names it)

`staged.py staged` (`reference/shared-options.md` section 2) routes the priority classes in sequence. In the dry
test it lost 13 to 17 connections against variant A and made the constrained nets longer. Use it to see whether
the constrained nets route with the board to themselves (`W/s/stage_1.md`); never put a rail in class 1; do not
report its result as the routing of the board.

### Variant B. Freerouting (a reference, optional)

Freerouting completed fewer connections than variant A on every test board and its results were not valid: it
does not know the copper-to-edge rule, it cuts pours, and it routes every net it is given (it cannot hold nets
out). Run it once when the task asks for it or when variant A is far from complete.

1. `"$PY" autoroute.py W/<board>.kicad_pcb W/b --passes 40 --plane-nets <plane nets> --track T --clear C --via V --drill D [--y-flip-offset Y0]`.
   The routed board is `W/b/<board>.kicad_pcb`; `W/b/freerouting.log` holds the router log.
2. Score it (label `auto-B`). If `score.md` says "Result valid: NO", the variant is a reference only.
3. Variant C (the congestion router on the nets that Freerouting left open, plan `W/b/plan_leftover.json`,
   model built from `W/b/<board>.kicad_pcb`, applied to `W/b/<board>.kicad_pcb`) keeps every defect of variant
   B. Run it only when variant B is valid.

### Tuning variant A

Record each attempt in `STATUS.md`. Use `--keep-routes` of the best attempt when only a few nets are open.

| Sign | Change |
|---|---|
| Conflict count still falling at the last iteration | `--iters 100` (the same seed repeats the first 60) |
| Tens of nets in conflict when the run ends | The result comes from the legalisation. Report it as such; name the nets open at every seed. |
| Many open nets lost to one large net | Priority 1 group for that net |
| Constrained nets come out long or with many vias | Their group gets `via_cost` 40 and priority 1 (short) or 2 (long) |
| Two nets lose one lane to each other in alternate attempts | Priority for the constrained one; a placement request for the lane |
| New `starved_thermal` items | `costs.thermal` 30 |
| More pour islands or long signal length on the pour layer (2-layer) | `reference/failure-repair.md` section 3 |
| Two plans differ | `seeds.py compare`; only a "B better" verdict is a result |
| At most 10 pads open after the best attempt | Finishing pass (`reference/shared-options.md` section 3) |

If the board does not close, the result of this method is the reference for the planned methods, together with
the report of where the nets are lost.

### Review

Fill `W/REVIEW.md` from `reference/review-checklist.md` for the attempt that is reported.

## 3. When routing stops short

Open connections that the repair guide cannot close are placement limits. Write each as a request with report
evidence in `REQUESTS.md` and `requests.json` (`reference/common.md` section 7). In a race, stop there: the
relief phase tests the requests. Outside a race, test the placement requests yourself with
`reference/placement-relief.md` and report the placement diff; the design owner applies it.

## 4. Limits

- Freerouting does not know the board's keep-out rules for vias inside footprints, the copper-to-edge rule or
  the design's constraints on analog nets. Every constrained net must be checked after routing.
- Freerouting 2.5.0 needs the JDK at `C:\Tools\jdk-25.0.5+8`; paths are options of `autoroute.py`.
- This skill was written for small mixed-signal power boards without high-speed nets. Revise it when the
  tools or the models change.
