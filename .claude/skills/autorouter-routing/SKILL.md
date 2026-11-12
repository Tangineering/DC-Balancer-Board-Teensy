---
name: autorouter-routing
description: Route the signal nets of a placed KiCad board with batch autorouters and no manual plan - Freerouting first, then the negotiated-congestion grid router on the nets that Freerouting left open, with a recovery pass. Use it when the user asks to "autoroute", "run Freerouting", "use the autorouter pipeline", for a quick first result on a new board, or as one method of the route-race skill. Do not use it for placement or for power pours.
---

# Autorouter routing

This is the batch method: no regions, no corridors. It gives the reference result that the planned methods must
beat, and on an easy board it is the fastest way to a complete route.

Read `tools/pcb/corridor_route/reference/common.md` first.

## 1. Inputs and outputs

- Input: a work folder `W` with a copy of a placed board whose power copper is in place. The board needs a
  keep-out band along its edge if the fab has a copper-to-edge rule; Freerouting does not know that rule.
- Output in `W`: one sub-folder for each variant with the routed board and `score.md`; `STATUS.md`;
  `REQUESTS.md`; `REVIEW.md`.

## 2. Procedure

Run the three variants. They are independent; run A and B at the same time when the machine allows it.

### Variant A. Congestion router alone

1. `"$PY" board_model.py W/<board>.kicad_pcb W/model --layers <routing layers> [--y-flip-offset Y0]`.
2. Read `W/model/model_summary.md`. Write `W/plan_free.json`:
   `{"frame": {...}, "rules": {...}, "keep_nets": [...], "plane_net": "...", "default": {"mode": "free", "priority": 5}}`.
   A net flagged NO POUR goes into a group with `"mode": "free", "priority": 1`.
3. `"$PY" capacity.py W/model/model.json W/plan_free.json W/capacity_free.md`. Sealed pads become requests.
4. `"$PY" -u route_plan.py W/model/model.json W/plan_free.json W/a/routes.json --iters 30 --report W/a/route_report.md`.
5. `"$PY" apply_routes.py W/<board>.kicad_pcb W/a/routes.json W/a/board`.
6. Score `W/a/board/<board>.kicad_pcb` (label `auto-A`).

### Variant B. Freerouting alone

1. `"$PY" autoroute.py W/<board>.kicad_pcb W/b --passes 40 --plane-nets <plane nets> --track T --clear C [--y-flip-offset Y0]`.
   The routed board is `W/b/<board>.kicad_pcb`; `W/b/freerouting.log` holds the router log.
2. Score it (label `auto-B`).

### Variant C. Freerouting, then the congestion router on the open nets

1. `autoroute.py` wrote `W/b/plan_leftover.json`: the nets that Freerouting left open route free, every other
   net is kept as Freerouting left it.
2. `"$PY" board_model.py W/b/<board>.kicad_pcb W/c/model --layers <routing layers> [--y-flip-offset Y0]`.
3. `"$PY" -u route_plan.py W/c/model/model.json W/b/plan_leftover.json W/c/routes.json --report W/c/route_report.md`.
4. `"$PY" apply_routes.py W/b/<board>.kicad_pcb W/c/routes.json W/c/board`.
5. Score `W/c/board/<board>.kicad_pcb` against the unrouted `W/<board>.kicad_pcb` (label `auto-C`).

### Tuning (at most three further attempts)

Tune the best variant. Record each attempt in `STATUS.md`.

| Sign | Change |
|---|---|
| Variant A conflict count still falling at the last iteration | `--iters 60` |
| Variant A conflict count flat from the first iterations | No tuning closes it. Report the bottleneck with `reference/failure-repair.md`, last rows. |
| Many open nets lost to one large net | Priority 1 group for that net |
| Freerouting stops early with many nets open | `--passes 100`; then variant C |
| New edge or keep-out violations in variant B | They come from Freerouting. Variant C keeps them. Report them; prefer variant A. |

This method does not draw corridors or set layer directions. If the board does not close, the result of this
method is the reference for the planned methods, together with the report of where the nets are lost.

### Review

Fill `W/REVIEW.md` from `reference/review-checklist.md` for the variant that is reported.

## 3. Limits

- Freerouting does not know the board's keep-out rules for vias inside footprints, the copper-to-edge rule or
  the design's constraints on analog nets. Every constrained net must be checked after routing.
- Freerouting 2.5.0 needs the JDK at `C:\Tools\jdk-25.0.5+8`; paths are options of `autoroute.py`.
- This skill was written for small mixed-signal power boards without high-speed nets. Revise it when the
  tools or the models change.
