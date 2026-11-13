---
name: route-race
description: Run a routability study on a placed KiCad board - a scripted reference at four or more seeds, one diagnosis of where and why connections stay open, scripted tests of every proposed change (plans, nets held out, part moves) against an equal control, and one batch of tested change requests to the design owner; the study repeats on the placement variants that come back. Use it when the user asks to "race the routing methods", "run the routing race", "run a routability study", "try the routing approaches in parallel", or when a board must be routed and a single run does not close it. The orchestrator never edits the real board, except to commit the chosen routed board on a branch of its own when the design owner asks for it.
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
- The via-in-pad ruling: none, a list of pads, or unlimited (`board-routing` section 2, step 4).
- Soft rules that are scored as metrics, not limits (for example a keep-away zone), with their exempt nets.
- The list of fixed parts and the project's constraint check command.
- The move limits for scratch tests (`reference/placement-relief.md` section 1).
- The design owner (a session or the user) and where the batch goes.
- `RACE/history.json`: the decisions of earlier rounds, if any. Changes that are already approved are applied
  by the design owner before the study starts: do not study a board that still contains them.

## 2. Stage 1: reference (scripts, no agents)

1. Choose an empty folder `RACE/rN` for round N, outside the board's folder.
   `python race.py init <board.kicad_pcb> RACE/rN --entries ref`.
   When the base board is new (a new commit, or a variant that comes back), compare it with the previous base:
   `"$PY" cmp_place.py <previous base> <new base>`. If placement, pad nets and zones are equal, do not route
   the reference again. Use the earlier runs as the control and write the comparison in `STATUS.md`. Run the
   new seeds only for the changes that the round tests (a new plan rule, for example).
2. Model the board and write the plain plan `RACE/rN/ref/plan.json` (`board-routing` skill, section 2,
   steps 1 to 5). Run `capacity.py`; follow a GRID message.
3. `"$PY" -u seeds.py run RACE/rN/ref/model/model.json RACE/rN/ref/plan.json RACE/rN/ref/seeds --seeds 1,2,3,4`
   (in the background; `reference/common.md` section 6 for the run time and the number of jobs).
4. Read `SEEDS.md`: mean, minimum, maximum, the nets open at every seed and the nets open at some seeds.
5. Finish every seed with the pipeline of `board-routing` section 2, step 7: apply, score, plane vias, apply,
   score, constraint metrics. Read the plane-net result and `vias_on_smd_pads` of each seed. If the board is
   closed (0 open connections, valid, review passed), go to section 6.
6. `"$PY" global_route.py ... --no-corridors --report RACE/rN/ref/global.md`, at tile 2.0 and 1.0.

## 3. Stage 2: diagnosis (one agent)

Start one agent. Its prompt: the paths of `SEEDS.md`, the `route_report.md` of every seed, both `global.md`
files, the images of the best seed, the constrained nets, the fixed parts, the `plane_vias.md` and
`nosite_why.py` output of each seed; and the output format below. It does not route.

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
- One request is one decision: one place, the smallest set of parts. A placement request states the move
  (old and new position and rotation of each part, the frame, the board commit).
- If the request asks for more than a relief trial can test (a block of parts), say that it is a re-placement
  variant for the design owner, and state what is untested.

## 4. Stage 3: tests (scripts; agents only where named)

Run the tests of all hypotheses in parallel, within the job limit. Every test has a control with the same
options, and uses the seeds of stage 1.

| Hypothesis | Test | Judged by |
|---|---|---|
| A plan (layer assignment, guide corridors, a priority, a direction, a hand corridor) | `seeds.py run` on the plan, then `seeds.py compare RACE/rN/ref/seeds <plan seeds>` | `compare` verdict |
| Nets leave the task (DNP removal; a pour or rail for a net) | `whatif.py holdout ... --nets <nets>`; `seeds.py compare` reads the folder as its held side | its verdict line |
| A soft keep-away rule | A plan with reserved zone corridors at `costs.reserve` 30 and exempt groups (`board-routing` section 2, step 4); `seeds.py run`, `seeds.py compare`; `parallel_metric.py` on every seed of both runs | `compare` verdict for completion; the metric at every seed |
| A part move, rotation or swap at one site | `whatif.py move`, the constraint check, `board_model.py`, then `relief_trial.py` | its verdict |
| A larger re-placement of a named block; a pour change; a rule or via-size change | The orchestrator builds the variant on a scratch copy (or asks the design owner for it), models it, `seeds.py run`, `seeds.py compare` | `compare` verdict |

- Plans come from the diagnosis, or from a worker agent that follows `board-routing` section 3 (layer
  assignment, guide corridors, a priority, the 2-layer pour pattern, one hand corridor). A worker delivers a plan
  and a `capacity.py` PASS; the orchestrator runs the seeds.
- A **relief worker** (`reference/placement-relief.md`) is started only for a site that the diagnosis names as
  a lane of at most 3 nets. Start one worker first. Start the others after the first has finished one trial,
  so that a tool fault is found once.
- A verdict of "not separated" is a result: the change does nothing that four seeds can show. Record it.
- Bias of a hold-out figure, to state in the batch: a DNP hold-out understates the gain (the parts stay on the
  board); a pour or rail hold-out overstates it (the pour takes layer space that the test does not charge).
- Test the combination of the two strongest changes as well: effects on a congested board do not add.
- Finish the seeds of a test with the same pipeline as the reference (stage 1, step 5) when the plane nets or
  a constraint metric are part of the hypothesis.
- When the reference closes at every seed, the tests compare quality: router vias, the vias of constrained nets,
  the soft-rule metrics and the plane-net connections open after the plane-via step (`board-routing` section 2,
  end). Finish every seed of every test. `seeds.py compare` judges connections only; compare the other measures
  seed by seed from the scores, with the same rule: lower at every seed.
- A plane-net pad open at every seed of every plan, with no via site because of obstacles, is a request at once
  (`board-routing` section 3, step 2). Send it in the batch; no test can close it.

When all tests have finished, write `RACE/rN/tested.json` from the `tested.json` and `trial.json` files (add
the `match` field), and run `python merge_requests.py RACE/rN --round N --tested RACE/rN/tested.json
[--history RACE/history.json]`.

## 5. Batch to the design owner, and the next round

1. Check `CHANGE_REQUESTS.md`: each row has evidence, a verdict (gain, not separated, refuted) or the word
   "untested", its tier and its design rows. A refuted request stays in the list as refuted.
   Before you send a number from a constraint checker, verify the checker on one pad whose position you know
   (`board-routing` section 2, step 7). In the CR study a scratch checker used the wrong frame, and its wrong
   counts went to the design owner.
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
- the via-in-pad rule and `vias_on_smd_pads` of each seed; with `via_in_pad: true`, say that the count is not
  limited;
- the plane-net connections open after the plane-via step, per seed, and what blocks the pieces without a via
  site;
- whether the board is closed (open connections 0, valid, review passed, finish test of
  `reference/review-checklist.md` passed);
- every test with its verdict and its n, the "not separated" ones included;
- the batch that was sent, and what the remaining open connections need.

State every number with its n, its iteration limit and its plan. Do not report the best of several attempts as
the result of a method.

The best board stays in its race folder. Copying it into the project is the owner's step, unless the owner asks the
orchestrator for the routed board on a branch. Then:

1. Create a worktree of your own on a new branch from the owner's commit. Never write the owner's worktree.
2. When the owner sends a new commit (an approved request), merge it into your branch, archive its board into a new
   round folder, compare it with `cmp_place.py`, model it and route the chosen plan at four seeds.
3. Finish the chosen seed for delivery: plane vias with `--stitch` when the design asks for stitching, then the
   straightening pass (`board-routing` section 2, step 7). Copy `board_st/<board>.kicad_pcb` over the board in your
   worktree. Check with `git status` that
   only the board file changed; the project file and the rule file must stay byte-identical.
4. Run `kicad-cli pcb drc --severity-all --schematic-parity` (`tools/pcb/TOOLCHAIN.md` gives the path) and the
   project's constraint check on that file. Only the violations that the owner accepts (for example silk) may remain.
5. Commit with the plan, the seed, the DRC and the constraint figures in the message. Do not push. Report the branch
   tip to the owner.
6. Run the final step of `board-routing` section 5a on the committed board: a trimmed outline with mounting holes,
   proposed to the owner as one request. When the owner's commit with the new outline comes back, merge it and run
   DRC and the constraint check again. Trimming removes only empty area, so no re-route is needed unless the owner
   moved parts or copper.
7. The finish order (r9 CR record, D-61) is: route, plane vias, the trim (the owner's generator), plane vias with
   `--stitch` on the trimmed board, straightening, `stitch_gaps.py`, then the project's reference and silk step and
   its checks. `plane_vias.py` needs the router's grid occupancy, so it runs before straightening; `stitch_gaps.py`
   reads the real copper, so it closes the stitching gaps last. Run the project's stitching check after it. If the owner trims a board that lacks a step, take the owner's
   board in the merge and run the missing steps on it; do not merge two different boards line by line.

## 7. Rules

- One score for all: `score.py` against the unrouted board of the same variant.
- Completion is counted in connections, not nets.
- A difference is a result only with 4 or more seeds and the same sign at every seed (`seeds.py compare`,
  `whatif.py holdout`, `relief_trial.py` print the verdict).
- "Valid" means that the routing added no defect: no new DRC violation other than `starved_thermal`, no via
  on an SMD pad. A valid result is not a finished board.
- Agents propose, scripts judge. Scratch copies only. A race folder is never reused.
- A request is sent with a verdict or marked "untested". An estimate is never sent as a fact.
- A checker's number is sent only after its frame check on a known pad.

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
- The CR study of 2026-11-12 (three rounds, after the change): the plane-via step without the unflashed-pad
  rule shorted GND pads to In2.Cu tracks at 3 of 4 seeds; `plane_vias.py` now applies the rule by default.
  `via_in_pad: true` gave 102 to 119 vias in SMD pads per seed. A soft keep-away zone at reserve 30 cut the
  parallel logic length in the zone sharply at no separated completion cost, but did not clear all logic vias.
  The round-3 base had the same placement as a round-2 variant; `cmp_place.py` finds such a case before a
  reference is routed again. `board-routing` section 6 has the figures.
- The r9 CR race of 2026-11-13 (one round, one request, a re-route on the owner's fix): the plain plan closed at
  every seed, so the race compared quality, and a combined plan (soft zones plus a high via cost on four nets) was
  better at every seed. One /GND pad was enclosed at every seed of every plan; the owner closed it with a pre-via.
  Two tool faults came to light: an exposed pad escaped the via ban because its thermal vias shared its number,
  and the ban used a round margin where a rectangular pad's mask opening has square corners. Both are fixed; the
  project's constraint check found the second after DRC and `score.py` had passed the board.

## 9. Limits

- A relief trial shows the effect of a move with the rest of the board held. Only the next round on the new
  placement shows the effect of a full run.
- Plane nets are connected by `plane_vias.py` in the finish pipeline of each seed. Pieces without a via site
  stay open; a track move in the GUI or a request closes them. The finish test covers the result.
- This skill was written for small mixed-signal power boards. Revise it when the tools or the models change.
