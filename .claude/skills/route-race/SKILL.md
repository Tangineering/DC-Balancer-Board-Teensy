---
name: route-race
description: Orchestrate a routing race - run several routing methods (corridor-routing, direction-layer-routing, autorouter-routing) in parallel worker agents on separate copies of a placed KiCad board, score every attempt with one script, rank them and hand the winner back. Use it when the user asks to "race the routing methods", "try the routing approaches in parallel", "see which routing method wins", or when a board must be routed and no single method is known to close it. The orchestrator never routes and the workers never touch the real board.
---

# Routing race

One board, several methods, one score. Each worker agent gets its own copy of the board and one method skill.
The orchestrator prepares the folders, starts the workers at the same time, ranks the scored attempts and
reports. Only the orchestrator, after the owner of the board agrees, copies a winning board anywhere.

Read `tools/pcb/corridor_route/reference/common.md` first.

## 1. Inputs

- The placed board (power copper in place) and its project files.
- The routing layers, the plane nets, the frame offset, the fab rule set (`reference/fab-limits.md`).
- The design rows that constrain nets (file and section), for the workers.
- Optional: placement variants of the same board. Each variant is one more set of entries.

## 2. Procedure

### Step 1. Prepare

1. Choose an empty race folder `RACE` outside the board's folder.
2. `python race.py init <board.kicad_pcb> RACE --entries corridor,direction,auto`.
   For placement variants, run `init` once for each variant with entry names such as `corridor-pA`.
3. Write `RACE/BRIEF.md`: board name, routing layers, plane nets, `--y-flip-offset`, rule values, the fab
   limit, the constrained nets with their design rows, the time limit and the attempt limit for each worker.
   Every worker gets the same brief.

### Step 2. Start the workers, all in one message

Start one worker agent for each entry, in a single message so that they run in parallel. Each prompt states:

- the method skill to follow, by name, and that it is the only method the worker uses;
- the work folder `W = RACE/<entry>`, and that the worker writes nowhere else;
- the path of `RACE/BRIEF.md`;
- the limits: wall time (default 60 minutes), routed attempts (default 6);
- the deliverables: `STATUS.md`, `REQUESTS.md`, `REVIEW.md`, and a `score.json` for every attempt;
- that the final message is a short summary: the best attempt's folder, its rank vector, the open nets with
  their classes, and the requests.

Do not give one worker the findings of another during the race. Do not route yourself.

Run long commands in the background. The machine runs about three 4-layer routing jobs at a time without
slowing each one much; with more entries, start them in batches of three.

### Step 3. Rank

1. When all workers have reported: `python race.py rank RACE`. Read `RACE/RANKING.md`.
2. Check the winner yourself, do not trust the worker's summary:
   - `score.md` of the winning attempt: open connections, the column New, parity run;
   - `REVIEW.md` rows 6, 10, 11 and 12 (the checks that the score does not see); open the images;
   - the constrained nets of the brief against the routed board.
3. If the winner fails a review row, take the next attempt in the ranking that passes.

### Step 4. Second round (optional, at most one)

A second round is useful when no entry closed the board and the reports agree on a cause.

1. Merge the findings: the open nets that every method lost, the bottlenecks with numbers, the requests.
2. Requests that need the design owner (placement, pours, rules, DNP removal, layers, outline) go to the
   owner. The race stops here until the owner rules.
3. Changes inside the plan (priorities, a corridor that one worker found, a direction assignment) may be
   given to all workers as a new brief. Start round two in new folders (`RACE/r2/<entry>`).

### Step 5. Report

Report to the owner of the board:

- the ranking table and the winner, with its rank vector;
- whether the board is closed (open connections 0, new DRC 0, review passed);
- if not closed: the bottlenecks as numbers and the requests, ordered by the connections each would close;
- what each method contributed (one line each), so that the next race can drop a method that never wins.

The winning board stays in its race folder. Copying it into the project is the owner's step: one writer for the
real board.

## 3. Rules

- One score for all: `score.py` against the same unrouted board. A method is not allowed its own measure.
- Completion is counted in connections, not nets.
- An attempt with new DRC violations never wins over an attempt without them at the same completion.
- Workers do not change placement, pours, rules or the netlist. They write requests.
- A race folder is never reused.

## 4. Limits

- The race finds the best plan for a given placement. It does not fix a placement that lacks capacity; it
  reports that with evidence.
- Plane nets are connected by the project's plane-via step after the race.
- This skill was written for small mixed-signal power boards. Revise it when the tools or the models change.
