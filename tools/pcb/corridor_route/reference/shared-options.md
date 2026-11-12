# Shared routing options

These options work with every method, because they act on the plan or on the router, not on the method's own
decisions. Each one targets one observed failure. Use an option when its sign is present; record it in
`STATUS.md` like any other attempt, and score the result the same way.

| Option | Sign | Section |
|---|---|---|
| Routing order | Open connections differ much between two seeds | 1 |
| Staged routing | Constrained nets come out long or with many vias; a plan change loses unrelated nets | 2 |
| Finishing pass | A few connections are open (up to about 10 % of the total) after the best attempt | 3 |
| Layer assignment from crossings | Many crossings on one layer; many pour islands on a 2-layer board | 4 |
| Global routing | The agent needs measured channel capacities, or corridors that are not guesses | 5 |

`$PY`, `W` and the commands for apply and score are in `common.md`.

## 1. Routing order

`route_plan.py ... --order cross|short|long` sets the order of the first iteration inside each priority class:
fewest crossings first (default), shortest net first, or longest net first.

- Run the same plan with `--order short` and `--order long`.
- If the open connections differ by more than the noise band, the failure depends on the order. Keep the
  better order and give the nets that the worse order lost a lower priority number.
- If both orders lose the same nets at the same places, the failure is a capacity failure. No order closes
  it; write the request.

## 2. Staged routing

`"$PY" -u staged.py staged W/model/model.json W/plan.json W/vN [--seed S] [--iters 20] [--order cross]`

The priority classes of the plan are routed in sequence. Each class is routed against the locked result of
the classes before it. Output: `W/vN/routes.json`, `W/vN/route_report.md`, `W/vN/STAGED.md`.

- Put the constrained nets and the rails without a pour in priority 1, long constrained nets in priority 2.
- The first stage shows the constrained nets with the board to themselves. Check the priority-1 table of
  `W/vN/stage_1.md` against the design rows before the later stages matter.
- A locked net cannot be moved by a later net. If an ordinary net is BLOCKED by a locked net, either give the
  locked net a `layers` or `via_cost` entry that takes it out of the way, or accept the open connection and
  write the request. Do not raise the priority of every net: one class is an ordinary run.
- The run time is the sum of the stages.

## 3. Finishing pass

`"$PY" -u staged.py finish W/model/model.json W/plan.json W/vN_fin --start W/vN/routes.json [--radius 2.0] [--seeds 1,2]`

The complete nets of the start result are kept. The nets (priority above 1) that pass within `--radius` mm of an
open pad are routed again together with the open nets. Each seed is one trial.

- `W/vN_fin/routes.json` is the best trial only if it has more connections than the start; otherwise it is the
  start result. `FINISH.md` states which.
- Apply and score `W/vN_fin/routes.json` as a new attempt. The gain counts only if the result is valid.
- Try `--radius 4` when radius 2 gives no gain. A larger radius approaches a full run and loses the benefit.
- A finishing pass that gives no gain at two radii is evidence that the open connections are a capacity
  failure at that place. Name the place in the request.

## 4. Layer assignment from crossings

`"$PY" layer_assign.py W/model/model.json W/plan.json W/plan_la.json --report W/layer_assign.md [--layer-weight L:w]`

The script gives each long net a preferred layer so that nets whose straight-line trees cross sit on different
layers. It writes `net_layer_cost` into a copy of the plan: a preference, not a limit.

- 4-layer board: run it without `--layer-weight`.
- 2-layer board with a ground pour on one layer: add `--layer-weight <pour layer>:0.3`, so that only the nets
  that must cross go to the pour layer. Compare the pour islands of `score.md` with the attempt before.
- Read "Crossings that remain on one layer" in the report. Each row needs a bridge; many rows on one layer at
  one place mark a spot for a request.
- `--cost` (default 2.5) is the strength of the preference. Raise it to 4 when the routed length by layer in
  `route_report.md` does not follow the assignment; lower it to 1.5 when connections are lost.
- Do not combine it with a `directions` entry on the first attempt: test one lever at a time.

## 5. Global routing

`"$PY" global_route.py W/model/model.json W/plan.json W/plan_g.json --report W/global.md [--tile 2.0] [--mode guide|hold] [--no-corridors]`

The script routes every net over square tiles with measured border capacities, by negotiated congestion.

**The report is capacity evidence.**
- "Borders and tiles above capacity" lists the places where no assignment of nets to channels fits, with the
  nets. Use the rows as evidence in a request (`capacity`, `demand`).
- Overflow 0 means that the channels are sufficient at this resolution. Open connections of the detailed
  router are then local: a pad escape, a pocket between parts, a via site. Run it again with `--tile 1.0` to
  look closer. If the overflow is still 0, corridors will not close the board; relief at the named pockets
  will.

**The plan copy carries corridors from the coarse paths.**
- `--mode guide` (default): each net may leave its corridors at a cost (`costs.guide`, default 3). Use this
  mode for a full run.
- `--mode hold`: each net is held inside its corridors. On the test boards this lost a quarter of the
  connections. Use it only to test one channel.
- Route `W/plan_g.json` like any plan. It beats the plan without corridors only if it is better at two seeds.
- The groups of the plan stay as they are. A net that the plan already holds in corridors keeps them.

## 6. Combination

Use at most one new option for each attempt, so that the effect of each is known. A reasonable order on a board
that does not close: routing order (section 1) to tell ordering from capacity; staged routing (section 2) if
constrained nets are at stake; layer assignment (section 4) or global routing (section 5) as plans; then a
finishing pass (section 3) on the best valid attempt.
