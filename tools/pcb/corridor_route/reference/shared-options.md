# Shared routing options

These options work with every method, because they act on the plan or on the router, not on the method's own
decisions. Each one targets one observed failure. Use an option when its sign is present; record it in
`STATUS.md` like any other attempt, and score the result the same way.

| Option | Sign | Section |
|---|---|---|
| Routing order | The open connections differ much between seeds | 1 |
| Staged routing | A diagnostic only: do the constrained nets route when the board is theirs alone? | 2 |
| Finishing pass | At most 10 pads are open after the best attempt | 3 |
| Layer assignment from crossings | Many crossings on one layer; many pour islands on a 2-layer board | 4 |
| Global routing | The agent needs measured channel capacities, or corridors that are not guesses | 5 |

`$PY`, `W` and the commands for apply and score are in `common.md`. An option is a hypothesis: it counts as a
gain only when `seeds.py compare` says so at 4 or more seeds (`common.md` section 5).

Test record (CR board, 4 layers; router before the schedule change): layer assignment and guide corridors were
not separated from the plain plan; corridors in mode hold lost a quarter of the connections; staged routing
lost 13 to 17 connections and made the constrained nets longer; the finishing pass gave no gain with 26 or more
open connections.

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

- Use it as a diagnostic, not as the routing of record. In the dry test it made fewer connections than the
  plain run and longer constrained nets, because a rail routed first and alone spread over the signal layer and
  was then locked.
- Never put a rail without a pour (a net with 12 or more pads) in the first class.
- The first stage shows the constrained nets with the board to themselves (`W/vN/stage_1.md`). A constrained
  net that is open even there is limited by the placement of its own parts: evidence for a request.
- A locked net cannot be moved by a later net. If an ordinary net is BLOCKED by a locked net, either give the
  locked net a `layers` or `via_cost` entry that takes it out of the way, or accept the open connection and
  write the request. Do not raise the priority of every net: one class is an ordinary run.
- The run time is the sum of the stages.

## 3. Finishing pass

`"$PY" -u staged.py finish W/model/model.json W/plan.json W/vN_fin --start W/vN/routes.json [--radius 2.0] [--seeds 1,2]`

The complete nets of the start result are kept. The nets (priority above 1) that pass within `--radius` mm of an
open pad are routed again together with the open nets. Each seed is one trial.

- Use it only when at most 10 pads are open. With more, the rip-up covers most of the board (79 of 95 nets
  in the dry test) and the pass is a shorter full run that loses connections.
- `W/vN_fin/routes.json` is the best trial only if it has more connections than the start; otherwise it is the
  start result. `FINISH.md` states which.
- Apply and score `W/vN_fin/routes.json` as a new attempt. The gain counts only if the result is valid.
- `--radius 1` when the log line "finishing pass: ... N kept nets ... routed again" shows more than a third
  of the nets.

## 4. Layer assignment from crossings

`"$PY" layer_assign.py W/model/model.json W/plan.json W/plan_la.json --report W/layer_assign.md [--layer-weight L:w]`

The script gives each long net a preferred layer so that nets whose straight-line trees cross sit on different
layers. It writes `net_layer_cost` into a copy of the plan: a preference, not a limit.

- 4-layer board: run it without `--layer-weight`.
- 2-layer board with a ground pour on one layer: add `--layer-weight <pour layer>:0.3`, so that only the nets
  that must cross go to the pour layer. Compare the pour islands of `score.md` with the attempt before.
- Read "Crossings that remain on one layer" in the report. Each row needs a bridge; many rows on one layer at
  one place mark a spot for a request.
- `--cost` (default 2.5) is the strength of the preference. In the dry test the routed length did not follow
  the assignment at 2.5 (35 to 38 % of the length on the assigned layer, against 34 to 36 % without it), and
  cost 4 lost connections. The script assigns constrained nets too; exclude them by giving their group a
  single-layer `layers` entry, or delete their rows from `net_layer_cost`.
- Do not combine it with a `directions` entry on the first attempt: test one lever at a time.

## 5. Global routing

`"$PY" global_route.py W/model/model.json W/plan.json W/plan_g.json --report W/global.md [--tile 2.0] [--mode guide|hold] [--no-corridors]`

The script routes every net over square tiles with measured border capacities, by negotiated congestion.

**The report is capacity evidence.**
- "Borders and tiles above capacity" lists the places where no assignment of nets to channels fits, with the
  nets. Use the rows as evidence in a request (`capacity`, `demand`).
- Overflow 0 means that an assignment of nets to channels exists at this resolution. It does not show that
  the board routes: the model does not count the pin demand inside a tile, and a channel at exactly its
  capacity (4 of 4) leaves no room for the detailed router. Run it again with `--tile 1.0`, and list the
  borders at capacity beside the places where nets are open at every seed.

**The plan copy carries corridors from the coarse paths.**
- `--mode guide` (default): each net may leave its corridors at a cost (`costs.guide`, default 3). Use this
  mode for a full run.
- `--mode hold`: each net is held inside its corridors. On the test boards this lost a quarter of the
  connections. Use it only to test one channel.
- Route `W/plan_g.json` like any plan, with `seeds.py run`, and compare it with the plain plan.
- The groups of the plan stay as they are. A net that the plan already holds in corridors keeps them.

## 6. Combination

Use at most one new option for each attempt, so that the effect of each is known. On a board that does not
close: global routing for the capacity report (section 5); layer assignment or guide corridors as plans, each
compared at 4 seeds; a finishing pass (section 3) only when few pads are open.
