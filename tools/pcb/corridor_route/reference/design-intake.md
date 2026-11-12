# Intake of change requests by the design owner

This file is for the session that owns the board design (placement, pours, netlist, rules). A routing race sends
it one batch for each round: `CHANGE_REQUESTS.md` and `change_requests.json`, and for tested part moves a
`placement_diff.json`. The design owner is the only writer of the real board.

## 0. Before the first round

Apply every change that is already approved (for example an approved DNP removal) and commit the board before
the first study starts. A study on a board that still contains approved removals measures the wrong board, and
a hold-out test only approximates the removal.

Give the study the constrained nets with their limits (length, layer, vias, pairing), the fixed parts, and the
via rule of the design (for example "every via tented, no via in an SMD pad").

## 1. For each request

1. Read the evidence and the tested gain. An "untested" request carries only the workers' estimate.
2. Check the design rows that the request names, and any other row that the change touches.
3. Check how the generator places each part that the request moves: by fixed coordinates, or by a packer.
   Removing or moving a part that a packer places can move other parts. If so, report the placement diff of
   the whole board with the variant.
4. Read the verdict of the test. "gain" was measured at 4 or more seeds; "not separated" means that four seeds
   showed nothing; "refuted" means that the tested move did not help. A request may describe a larger move than
   the one that was tested; the verdict belongs to the tested move only.
5. Decide: accept, modify (state the change), reject (state the reason), refer to the operator (tier
   "ruling"), or note (tier "plan": no board change; the study applies it). A request of tier "ruling" (DNP
   removal that is not yet approved, a new pour or rail, the rule set, the layer count, the outline) goes to
   the operator; collect these into one question.
6. Apply accepted changes in the project's generator, not by editing the board file. Run the generator, ERC,
   the constraint check and DRC.

## 2. Variants

Return accepted changes as committed placement variants, not as one edit in place. Prefer two or three variants
for a round when the changes are independent, so that the next race runs them in parallel and shows which change
gave the gain. Example: A = the approved DNP removal only; B = A plus the tested part moves; C = B plus a rail
for the largest net without a pour.

Each variant is a board with its project files in its own folder, with a one-line description.

## 3. Decisions file

Write `decisions.json` for the round and return it with the variants:

```json
[{"id": "CR1-02", "key": "placement:C101,R101", "parts": ["R101"], "decision": "accepted",
  "reason": "D-09 and D-32 distances hold after the move (0.53 mm, 2.09 mm)", "variant": "B"},
 {"id": "CR1-05", "key": "placement:R130,R131A", "parts": [], "decision": "rejected",
  "reason": "moves the parts out of the A.8 comparator band"}]
```

`decision` is one of `accepted`, `modified`, `rejected`, `operator`, `noted`. For `modified`, add `"change"`
with the move as old and new coordinates in the generator's frame.

The race keeps this file as its history: a rejected request is not sent again, and a part that an accepted
change moved is not moved again without a new reason. Add an entry to the layout decision log for each accepted
change.

## 4. Stop

The loop ends when a variant closes and passes the review checklist, when a round has no accepted change, or
after three rounds. After that the remaining open connections need an operator ruling (layers, outline, rule
set) or interactive routing.
