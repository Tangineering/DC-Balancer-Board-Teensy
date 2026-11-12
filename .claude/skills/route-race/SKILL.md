---
name: route-race
description: Run a routability study on a placed KiCad board - a scripted reference at four or more seeds, one diagnosis of where and why connections stay open, scripted tests of every proposed change (plans, nets held out, part moves) against an equal control, and one batch of tested change requests to the design owner; the study repeats on the placement variants that come back. Use it when the user asks to "race the routing methods", "run the routing race", "run a routability study", "try the routing approaches in parallel", or when a board must be routed and a single run does not close it. The orchestrator never edits the real board.
---

# Routing race (routability study)

One board, one score, and no claim without four seeds. The study has three stages and a loop:

1. **Reference.** Scripts route the board at four or more seeds with the plain plan. The result is the
   completion that the board gives without any idea, and its spread.
2. **Diagnosis.** One agent reads the reference runs and writes hypotheses: plans, nets to hold out, pours,
   part moves, each with report evidence.
3. **Tests.** Scripts test each hypothesis against an equal control at four or more seeds. Agents propose;
   scripts judge. No agent judges its own trial.
4. **Batch to the design owner**, who is the only writer of the real board, and the **next round** on the
   placement variants that come back.

Read `tools/pcb/corridor_route/reference/common.md` first. The scripts are in `tools/pcb/corridor_route`.

## 1. Inputs

- The placed board (power copper in place) and its project files; or the placement variants of a later round.
- The routing layers, the plane nets, the frame offset, the fab rule set (`reference/fab-limits.md`).
- **The constrained nets and their limits, from the design owner** (length, layer, vias, pairing). If the design
  gives none, ask for them before the study; without them the score has no quality term and workers class nets
  by name.
- The list of fixed parts and the project's constraint check command.
- The move limits for scratch tests (`reference/placement-relief.md` section 1).
- The design owner (a session or the user) and where the batch goes.
- `RACE/history.json`: the decisions of earlier rounds, if any. Changes that are already approved are applied
  by the design owner before the study starts: do not study a board that still contains them.

## 2. Stage 1: reference (scripts, no agents)

1. Choose an empty folder `RACE/rN` for round N, outside the board's folder.
   `python race.py init <board.kicad_pcb> RACE/rN --entries ref`.
2. Model the board and write the plain plan `RACE/rN/ref/plan.json` (`autorouter-routing` skill, variant A,
   steps 1 to 3). Run `capacity.py`; follow a GRID message.
3. `"$PY" -u seeds.py run RACE/rN/ref/model/model.json RACE/rN/ref/plan.json RACE/rN/ref/seeds --seeds 1,2,3,4`
   (in the background; `reference/common.md` section 6 for the run time and the number of jobs).
4. Read `SEEDS.md`: mean, minimum, maximum, the nets open at every seed and the nets open at some seeds.
5. Apply and score the best seed (`reference/common.md` section 2). If the board is closed (0 open
   connections, valid, review passed), go to section 6.
6. `"$PY" global_route.py ... --no-corridors --report RACE/rN/ref/global.md`, at tile 2.0 and 1.0.

## 3. Stage 2: diagnosis (one agent)

Start one agent. Its prompt: the paths of `SEEDS.md`, the `route_report.md` of every seed, both `global.md`
files, the images of the best seed, the constrained nets, the fixed parts; and the output format below. It does
not route.

The agent writes `RACE/rN/diagnosis/requests.json` and `REQUESTS.md` (`reference/common.md` section 7). Each
entry is a hypothesis with:
- the nets it concerns, and whether they are open at every seed or at some seeds;
- the place in the plan frame, the layer, the nets that take the space there;
- the proposed change and its kind (`plan`, `placement`, `pin_swap`, `dnp`, `pour_or_rail`, `rule`, `layers`);
- the test that would decide it (section 4), with the nets to hold out or the part and the move.

Rules for the diagnosis:
- A net open at one seed only is noise. Do not build a request on it.
- With tens of nets still in conflict at the end of a run, the "Lost to" places show where the router gave
  up, not where the board lacks capacity. A capacity claim needs the same nets at the same place at every seed,
  and a border at or above capacity in `global.md` or a lane count from the image.
- One request is one decision: one place, the smallest set of parts.

## 4. Stage 3: tests (scripts; agents only where named)

Run the tests of all hypotheses in parallel, within the job limit. Every test has a control with the same
options, and uses the seeds of stage 1.

| Hypothesis | Test | Judged by |
|---|---|---|
| A plan (layer assignment, guide corridors, a priority, a direction, a hand corridor) | `seeds.py run` on the plan, then `seeds.py compare RACE/rN/ref/seeds <plan seeds>` | `compare` verdict |
| Nets leave the task (DNP removal; a pour or rail for a net) | `whatif.py holdout ... --nets <nets>` | its verdict line |
| A part move, rotation or swap at one site | `whatif.py move`, the constraint check, `board_model.py`, then `relief_trial.py` | its verdict |
| A larger re-placement of a named block; a pour change; a rule or via-size change | The orchestrator builds the variant on a scratch copy (or asks the design owner for it), models it, `seeds.py run`, `seeds.py compare` | `compare` verdict |

- Plans come from the diagnosis, or from a method skill run by a worker agent (`corridor-routing`,
  `direction-layer-routing`, the layer assignment and guide corridors of `reference/shared-options.md`). A worker
  delivers a plan and a `capacity.py` PASS; the orchestrator runs the seeds.
- A **relief worker** (`reference/placement-relief.md`) is started only for a site that the diagnosis names as
  a lane of at most 3 nets. Start one worker first. Start the others after the first has finished one trial,
  so that a tool fault is found once.
- A verdict of "not separated" is a result: the change does nothing that four seeds can show. Record it.
- Bias of a hold-out figure, to state in the batch: a DNP hold-out understates the gain (the parts stay on the
  board); a pour or rail hold-out overstates it (the pour takes layer space that the test does not charge).
- Test the combination of the two strongest changes as well: effects on a congested board do not add.

When all tests have finished, write `RACE/rN/tested.json` from the `tested.json` and `trial.json` files (add
the `match` field), and run `python merge_requests.py RACE/rN --round N --tested RACE/rN/tested.json
[--history RACE/history.json]`.

## 5. Batch to the design owner, and the next round

1. Check `CHANGE_REQUESTS.md`: each row has evidence, a verdict (gain, not separated, refuted) or the word
   "untested", its tier and its design rows. A refuted request stays in the list as refuted.
2. For each accepted move, check `placement_diff.json`: frame, old and new coordinates, rotation, the commit of
   the board it was tested on (`reference/placement-relief.md` section 3).
3. Put the batch where the design owner reads it (the shared notes folder that the task names):
   `CHANGE_REQUESTS.md`, `change_requests.json`, every `placement_diff.json`, `SEEDS.md` of the reference, and
   `reference/design-intake.md`.
4. Send one message to the design owner that names the folder and the three strongest rows. Requests of tier
   `ruling` are for the operator; say so.
5. Stop and wait. Do not apply a change yourself, and do not send a second batch for the same round.
6. The design owner returns `decisions.json` and the variants. Append the decisions to `RACE/history.json` and
   run the study on the variants (`RACE/r(N+1)`).
7. Stop the loop when a variant is closed and passes review, when a round has no change with a "gain" verdict,
   or after 3 rounds. If the best variant is within a few connections of closed, report that finishing by hand
   in the KiCad GUI is the shorter way.

## 6. Report

Report to the owner of the board:

- the reference: mean, minimum and maximum of n seeds, and the scored best seed with its validity;
- whether the board is closed (open connections 0, valid, review passed, finish test of
  `reference/review-checklist.md` passed);
- every test with its verdict and its n, the "not separated" ones included;
- the batch that was sent, and what the remaining open connections need.

State every number with its n, its iteration limit and its plan. Do not report the best of several attempts as
the result of a method.

The best board stays in its race folder. Copying it into the project is the owner's step.

## 7. Rules

- One score for all: `score.py` against the unrouted board of the same variant.
- Completion is counted in connections, not nets.
- A difference is a result only with 4 or more seeds and the same sign at every seed (`seeds.py compare`,
  `whatif.py holdout`, `relief_trial.py` print the verdict).
- "Valid" means that the routing added no defect: no new DRC violation other than `starved_thermal`, no via
  on an SMD pad. A valid result is not a finished board.
- Agents propose, scripts judge. Scratch copies only. A race folder is never reused.
- A request is sent with a verdict or marked "untested". An estimate is never sent as a fact.

## 8. What the dry tests showed (three rounds, four boards, Opus workers)

- No plan-level method (hand corridors, layer directions, layer assignment, guide corridors) was separated from
  the plain router on a 4-layer board at the seeds that were run. Treat plans as hypotheses.
- Corridors that hold nets inside them lost connections in every test. Staged routing lost 13 to 17
  connections on the CR board.
- On a 2-layer board with a ground pour, the plan choice changed the number of pour islands (1 against 18).
- Part moves of up to 0.5 mm, rotations and swaps gave no accepted change at four sites of the CR board.
- A fresh agent ran this skill's earlier form end to end on a 2-layer board and closed it.
- The router was changed after these tests (negotiation schedule, via rule, reproducible seeds); numbers from
  before the change are not comparable with numbers after it.

## 9. Limits

- A relief trial shows the effect of a move with the rest of the board held. Only the next round on the new
  placement shows the effect of a full run.
- Plane nets are connected by the project's plane-via step after the study; the finish test covers it.
- This skill was written for small mixed-signal power boards. Revise it when the tools or the models change.
