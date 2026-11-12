---
name: route-race
description: Orchestrate a two-phase routing race on a placed KiCad board - a routing phase in which parallel worker agents route separate copies with different methods and seeds and are scored by one script, then a relief phase in which parallel workers test small part moves at the places where routing lost connections; the tested requests go to the design owner as one ranked batch, and the race repeats on the placement variants that come back. Use it when the user asks to "race the routing methods", "run the routing race", "try the routing approaches in parallel", or when a board must be routed and no single run closes it. The orchestrator never routes a race entry and never edits the real board.
---

# Routing race

One board, one score. The race has two phases and a loop:

1. **Routing phase.** Workers route copies of the board on the fixed placement. The result is comparable
   between workers.
2. **Relief phase.** Where routing lost connections to the placement, workers test changes on scratch copies:
   part moves at each site, and nets held out for requests that remove nets.
3. **Batch to the design owner.** The tested requests go out as one ranked batch. The design owner is the only
   writer of the real board and returns placement variants.
4. **Next round** on the variants, up to the round limit.

Read `tools/pcb/corridor_route/reference/common.md` first. The scripts are in `tools/pcb/corridor_route`.

## 1. Inputs

- The placed board (power copper in place) and its project files; or the placement variants of a later round.
- The routing layers, the plane nets, the frame offset, the fab rule set (`reference/fab-limits.md`).
- The design rows that constrain nets, the list of fixed parts, and the project's constraint check command.
- The move limits for the relief phase (`reference/placement-relief.md` section 1 gives the defaults).
- The design owner (a session or the user) and where the batch goes.
- `RACE/history.json`: the decisions of earlier rounds, if any.

## 2. Routing phase

### Step 1. Prepare

1. Choose an empty folder `RACE/rN` for round N, outside the board's folder.
2. Choose the entries. The default set for one board:
   - `auto-s1`, `auto-s2`: the `autorouter-routing` skill (the priority-tuned congestion router), at seeds 1 and
     2. This is the reference; two seeds measure the noise.
   - `corridor`: the `corridor-routing` skill.
   - `direction`: the `direction-layer-routing` skill.
   With several placement variants, give each variant the two `auto` entries, and add `corridor` and
   `direction` only for the variant that the design owner marks as the main one. Entry names end in the variant
   name (`auto-s1-B`).
3. `python race.py init <board.kicad_pcb> RACE/rN --entries auto-s1,auto-s2,corridor,direction`.
4. Write `RACE/rN/BRIEF.md`: board name, routing layers, plane nets, `--y-flip-offset`, rule values, the fab
   limit, the constrained nets with their design rows (or where to find them), the fixed parts, the limits
   (wall time, attempts), the deliverables. Every worker gets the same brief.

### Step 2. Start the workers, all in one message

Start one worker agent for each entry, in a single message so that they run in parallel. Each prompt states:

- the method skill to follow, by file path, and that it is the only method the worker uses;
- the work folder `W = RACE/rN/<entry>`, and that the worker writes nowhere else;
- the seed for an `auto` entry (every routing run of that worker uses it);
- the path of `BRIEF.md`;
- the limits: wall time (default 75 minutes on a 4-layer board, 30 on a 2-layer board), routed attempts
  (default 5), one routing run at a time;
- the deliverables: `STATUS.md`, `REQUESTS.md` and `requests.json` (`reference/common.md` section 7),
  `REVIEW.md`, and a score for every attempt;
- that workers do not move parts in this phase;
- that the final message is a short summary: the best valid attempt, its rank vector, the open nets with their
  classes and places, the requests.

Do not give one worker the findings of another during the phase. Do not route an entry yourself.
The machine runs about six 4-layer routing jobs at a time; with more entries, start them in batches.

### Step 3. Rank

1. `python race.py rank RACE/rN`. Read `RANKING.md`. An attempt that `score.md` marks "Result valid: NO" is not a
   candidate.
2. Noise: the two `auto` seeds give the band. A planned method beats the reference only when its result is
   better than both seeds. If it is better than one seed only, run its plan at a second seed yourself and
   compare the means.
3. Check the best attempt yourself, do not trust the worker's summary: `score.md` (open connections, validity,
   parity run), `REVIEW.md` rows 6, 10, 11 and 12, the images, the constrained nets of the brief.
4. If the board is closed (0 open connections, valid, review passed), go to section 5.

## 3. Relief phase

### Step 4. Merge the requests

1. `python merge_requests.py RACE/rN --round N [--history RACE/history.json]`. Read `CHANGE_REQUESTS.md`.
2. Requests of tier `plan` (a priority, a corridor that one worker found): note them for the brief of the next
   round. They are not sent.
3. Choose the sites to test: every merged request of tier `placement` that two or more workers support, and any
   single-worker placement request with an estimate of 3 connections or more. At most 6 sites for a round.
4. Choose the hold-out tests: every request of kind `dnp` or `pour_or_rail`.

### Step 5. Test, in parallel

Start in one message:

- one **relief worker** for each site. Its prompt: follow `reference/placement-relief.md`; work folder
  `RACE/rN/relief/<site>`; the site entry from `change_requests.json`; the start result (the best valid attempt:
  board copy, `model.json`, plan, `routes.json`); the move limits; the fixed parts; the constraint check command;
  at most 5 trials. Sites that share a candidate part go to one worker, one after the other.
- the **hold-out tests**, which you run yourself as background commands (they are tests, not race entries):
  `"$PY" whatif.py holdout <model.json> <best plan.json> RACE/rN/holdout/<name> --nets <nets> --seeds 1,2`.
  The nets of a DNP request are the nets that exist only because of the parts (they disappear with them). The net
  of a pour-or-rail request is the net that gets the pour.

When all have finished, write `RACE/rN/tested.json` from the `placement_diff.json` and `WHATIF.md` files (format
in the docstring of `merge_requests.py`) and run `merge_requests.py` again with `--tested RACE/rN/tested.json`.

Bias of the hold-out figure, to state in the batch:
- DNP removal: the test understates the gain, because the parts stay on the board and still take space.
- A new pour or rail: the test overstates the gain, because the pour takes layer space that the test does not
  charge.

## 4. Batch to the design owner

### Step 6. Send one batch

1. Check `CHANGE_REQUESTS.md`: each row has evidence, a tested gain or the word "untested", its tier and its
   design rows. Remove nothing that the script held back from the "Held back" list.
2. Put the batch where the design owner reads it (the shared notes folder that the task names):
   `CHANGE_REQUESTS.md`, `change_requests.json`, every `placement_diff.json`, and `reference/design-intake.md`.
3. Send one message to the design owner that names the folder and the three strongest rows. Requests of tier
   `ruling` are for the operator; say so.
4. Stop and wait. Do not apply a change yourself, and do not send a second batch for the same round.

### Step 7. Next round

1. The design owner returns `decisions.json` and the variants. Append the decisions to `RACE/history.json`.
2. Run the routing phase on the variants (`RACE/r(N+1)`), with the plan-tier notes in the brief.
3. Stop the loop when a variant is closed and passes review, when a round has no accepted change, or after
   3 rounds.

## 5. Report

Report to the owner of the board:

- the ranking table and the best attempt, with its rank vector and validity;
- whether the board is closed (open connections 0, valid, review passed);
- if not closed: the batch that was sent, the tested gains, and what the remaining open connections need;
- for each method, one line on what it contributed, so that the next race can drop a method that never wins.

The winning board stays in its race folder. Copying it into the project is the owner's step: one writer for the
real board.

## 6. Rules

- One score for all: `score.py` against the unrouted board of the same variant.
- Completion is counted in connections, not nets.
- An attempt with a new DRC violation other than `starved_thermal` is not valid and cannot win.
- Routing workers do not change placement, pours, rules or the netlist. Relief workers move parts only on
  scratch copies and only inside the move limits.
- A request is sent with a tested gain or marked "untested". A worker's estimate is never sent as a fact.
- A race folder is never reused.

## 7. Limits

- A relief test proves that the named nets route after a move with the rest of the board held. Only the next
  round on the new placement shows the gain of a full run.
- Plane nets are connected by the project's plane-via step after the race.
- This skill was written for small mixed-signal power boards. Revise it when the tools or the models change.
