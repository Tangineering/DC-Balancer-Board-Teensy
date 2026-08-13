---
name: orchestrated-feature
description: Implement a code feature round through orchestrated subagents — spec with verified anchors, Opus implementer, independent Sonnet test-writer, parallel two-lens first-pass reviews (firmware safety/sequencing + correctness/test-fidelity, or the data-integrity/contract lens pair for tooling), fixes routed back to the original agents, then the orchestrator's own final review and test runs. Use for any multi-part code change in this repo — teensy_controller.ino (new feature, fault rework, control-semantics change) or the Python tooling (analysis pipeline, decoder, GUI, controller-design scripts) — especially when the user asks to "use agents", "orchestrate", or names Opus/Sonnet for the edits. Takes an argument for the planning gate — "plan-approval" (present the plan in plan mode and wait for user approval) or "direct" (plan inline and proceed immediately; the default).
---

# Orchestrated feature round

Multi-agent implementation pipeline for code changes in this repo — firmware
(`teensy_controller/teensy_controller.ino`) or Python tooling (stages written
firmware-first; the "Non-firmware rounds" section says what swaps).
Distilled from the fw v4 round (2026-08-12), where the pipeline caught 4 HIGH-severity
integration bugs and one vacuous-test class that a single-pass implementation would have
shipped, then corrected and extended against the transcripts of five earlier orchestrated
rounds (2026-07-31 → 2026-08-11). The stage structure is the point: the safety reviewer
found what the implementer missed *because* its lens was "who else touches this state",
not "is this function correct".

## Argument: planning gate

- `plan-approval` — draft the plan, enter plan mode (EnterPlanMode), and present it for
  explicit user approval before any agent is dispatched. Use when the change is
  architecture-shaping, touches "What NOT to change" items, or the user asked to see the
  plan first.
- `direct` (default) — plan inline and proceed straight to dispatch. Use when the design
  was already settled in discussion with the user.

Either way, the plan is mandatory, and **even in `direct` mode post a short plan summary
to the user before Stage-1 dispatch** — one earlier round fanned out three agents with the
plan existing only inside their prompts, despite the user having asked to "plan out the
work". The plan must be user-visible, not prompt-embedded.

## Stage 0.5 (optional) — Research fan-out

For open-ended rounds where the design depends on facts not yet in hand (datasheets,
external tools, cross-domain constraints), fan out parallel domain-scoped research agents
*before* writing the spec — one self-contained prompt per domain, background, while the
orchestrator keeps working (baseline test runs, independent fixes). Synthesize selectively:
extract the findings that change the spec; do not reconcile full transcripts. A research
agent that hits a question outside its brief may spawn one follow-up agent. Skip this stage
for well-scoped feature rounds.

## Stage 0 — Spec with verified anchors (orchestrator, before any dispatch)

1. Grep/read the firmware yourself and pin down: the exact constants, functions, line
   anchors, **and enum/encoding/mapping values** each change touches; existing mechanisms
   to mirror (e.g. the OV persistence filter as the template for a new filtered fault);
   and which state machines / callers interact with the touched state. Verify every such
   fact against source before it enters a prompt — an orchestrator brief once carried a
   wrong `trap_phase` mapping (1/2/3 vs the firmware's 0/1/2) that only the agent's own
   source check caught.
2. **Enumerate the integration surface explicitly** — for every pin, flag, or arming term
   the feature reads or writes, grep for EVERY OTHER writer and reader and put the list in
   the spec. The fw v4 HIGHs (S1–S4) were all "another path writes this switch / feeds
   this arming term" bugs; the spec described the new mechanism perfectly and its
   neighbours not at all.
3. **Cross-feature interaction check**: when the round changes more than one feature
   sharing a code path, state in the spec which existing tests' or behaviors' inputs cross
   into the OTHER new feature's domain. The fw v4 vacuous-test HIGH came from exactly this
   gap — governor tests were renumbered for feature 1 at setpoints that feature 2's new
   latch now intercepts.
4. **Operator-interface conventions**: list the State-98 conventions any new mode must
   obey — universal `X` stop, single-line command parsing, the 500 ms status readout, `Q`
   exit semantics, logging lifecycle. The trapezoid round's only shipped gap (profile
   ignored `X`) was a convention miss the user caught, not any review.
5. State the invariants the change must preserve by name: §2 sequencing rules, back-feed
   rule, last-source guard, one-shot actuation exactness, non-blocking fault path,
   never-touch list (PIs, `share_controller_coeffs.h`).
6. License judgment calls: tell the implementer to deviate where the spec conflicts with
   an invariant, and to document every deviation with reasoning. (Two fw v4 spec errors —
   the completion-restore gap and the State-99 drain conflict — were caught only because
   the implementer was allowed to think, not transcribe.)

## Stage 1 — Implementation (Opus agent, synchronous)

One Opus `general-purpose` agent implements the firmware change. Prompt contents: the full
spec with anchors, the integration-surface list, the invariants, the deviation license, the
scope fence ("modify ONLY these files"), and "do not run tests" (a later stage owns that).
A syntax-check via the test TU is welcome: from `test/`,
`g++ -std=c++17 -Wall -Wextra -fsyntax-only -I. -I../teensy_controller
-I../controller_design -DBENCH_TEST=0 -DNO_ETH_WARNING test_main.cpp`, and again with
`-DBENCH_TEST=1 -Wno-unused-function`. Add a **scope-extension rule**: if the agent spots a
closely-related feature that fits the same control surface, it flags it to the orchestrator
instead of implementing unbidden (one round grew two unplanned profiles and two extra
review/fix cycles this way). Require a report with file:line anchors and a deviations
section. Keep the agent's ID — fixes go back to it.

## Stage 2 — Tests (Sonnet agent, synchronous, after Stage 1)

A separate Sonnet agent writes the host-native tests — independence from the implementer is
deliberate (it reads the firmware fresh and cannot inherit the implementer's blind spots).
Prompt: the feature semantics with anchors, the exact test list (per-behavior, including
the negative/guard cases), `reset_test_state()` obligations for every new global, which
build section each test belongs in (production vs bench), and the scope fence. The
enumerated list is a **floor, not a ceiling** — instruct the agent to report perceived
gaps or redundancies in the list before closing, not to silently write exactly N. Warn it
about the recurring traps:

- **Vacuous probes**: when a feature changes which code path OWNS an input region, any
  existing test probing that region may now pass for the wrong reason (fw v4: governor
  tests with sp < DROOP_R_MIN became latch-owned and asserted only that a frozen loop
  doesn't move). Tests must assert the mechanism fired, not merely that nothing changed.
  Pass along the Stage-0 cross-feature interaction list — that is where these hide.
- **Fixture preconditions**: new guards ripple into fixtures. Predict the ripple in the
  prompt; prefer per-test setup over changing `reset_test_state()` defaults when existing
  tests deliberately exercise the default.

## Stage 3 — Two-lens first-pass review (parallel background agents)

Dispatch two reviewers in parallel against the uncommitted `git diff`, read-only:

- **Opus, safety/sequencing lens**: bus-darkening, last-source, back-feed, hot-plug,
  boot-lock, fault-path liveness, latch/flag lifecycle (enumerate every set/clear site),
  frozen-path staleness, operator-convention conformance (Stage 0 item 4 — who else stops
  or owns the motor?), and — critically — the interaction of the new code with every OTHER
  writer of the same pins/state. Require it to list hazards checked and found CLEAN, not
  just findings.
- **Sonnet, correctness/test-fidelity lens**: boundary/off-by-one, copy-paste divergence
  from mirrored mechanisms, state-machine holes, stale comments/references, and per-test
  vacuity ("would this test pass if the feature were broken?") plus an enumeration of
  untested behaviors.

The two-lens pass is the default shape. For high-risk rounds the Codex adversarial loop
(`adversarial-doc-review` + finding-verifier agents) is a valid substitute or augment —
one round ran it in place of the two-lens pass successfully.

While reviewers run, the orchestrator builds and runs both suites (invoke the `test`
skill) for an empirical baseline — do not sit idle, and do not duplicate the reviewers'
reading.

## Stage 4 — Adjudicate and route fixes back

Adjudicate every finding yourself — an explicit ACCEPT / REJECT / PARTIAL per finding with
reasoning; verify claims against the code before accepting a HIGH. Route firmware fixes to
the implementer role and test fixes to the test role, referencing findings by ID. Either
continuation mechanism works: SendMessage to the original agent, or a fresh Agent call
with the finding list and needed context embedded (fw v4 used the latter). The orchestrator
may apply small/subtle fixes directly, but must say so in the report — never silently
substitute itself for the fix route.

- **The deviation license applies to reviewer fix text too.** A reviewer's literal S2 fix
  in fw v4 would have re-energized the bus during the State-99 drain; the fix agent
  deviated (scoped the restore) and documented it. Tell the fix agent: the finding can be
  right while its suggested fix is wrong — deviate and document.
- **Expect fixture breakage.** A fix round that adds a new guard predicate should be
  expected to break double-digit fixture counts (fw v4: 39 failures from one
  `boostEnabled` term at four sites). Itemize it to the test agent as an expected cost —
  it is normal, not a bad-fix signal.
- The test-fix prompt includes: fixture repairs, de-vacuating flagged tests, and new
  coverage for every review-round firmware change. Instruct the test agent to iterate to
  0 failures but to STOP and report if a failure looks like a firmware defect — never let
  the test agent edit the `.ino`.

## Stage 5 — Orchestrator final review

Not optional, and not a rubber stamp of the reports:

1. Read the critical new firmware sections yourself (the state machine, the guard
   predicates, the ordering-sensitive writes) and check them against the spec and the
   accepted findings.
2. Trace at least one subtle interaction end-to-end that no reviewer explicitly claimed
   (fw v4: self-heal → same-tick re-latch against external closers).
3. Rebuild and rerun both suites yourself via the `test` skill — timestamps checked, counts
   reported from the run output.
4. Doc ripples: FW_VERSION bump + `docs/firmware-versions.md` row (implementer usually does
   these — verify), CLAUDE.md status addendum, and any whitepaper/debug-log entries the
   change's evidence trail requires.
5. Report to the user: what was built, every accepted finding and its fix, the judgment
   calls, final test counts, and what remains (flash, bench validation).

## Non-firmware rounds (Python tooling, scripts)

The pipeline transfers; two things change and one does not:

- **Swap the lens pair**: safety/sequencing has no meaning off-board. Use
  data-integrity/atomicity/packaging (uninitialized buffers, non-atomic writes, exception
  swallowing, frozen-exe/import paths) vs contract-checklist (API signatures, CLI
  contracts, README claims). Scope reviewers by file ownership if the lenses overlap.
- **Add an interface contract for parallel siblings**: when two Stage-1 agents run in
  parallel and one consumes a file the other is still writing, put the exact
  signature/contract in both prompts, with "code against it via lazy import; do NOT
  create or edit the sibling's files".
- **The test-writer stage stays mandatory.** The one tooling round that dropped it shipped
  an entirely untested API surface — both reviewers flagged it. "It's not firmware" is not
  an exemption.

## Known failure modes this pipeline exists to catch

| Failure mode | Caught by | Instance |
|---|---|---|
| Integration-surface bugs (other writers of the same state) | Stage 3 safety lens | fw v4 S1: `chargingControl()` re-closed a latched switch in ≤20 ms |
| Spec errors that violate an invariant | Stage 1/4 deviation license | fw v4 completion-restore gap; reviewer's S2 fix vs State-99 drain |
| Boot-lock from new fault arming | Stage 3 safety lens | fw v4 S3 (bring-up P3 sag), S4 (boosts-off collapse) |
| Vacuous tests after ownership changes | Stage 3 correctness lens | governor probes below DROOP_R_MIN |
| Cross-feature test-domain collisions | Stage 0 item 3 | governor test setpoints inside the latch's domain |
| Operator-convention misses | Stage 0 item 4 / safety lens | trapezoid profile ignored the universal `X` stop |
| Wrong facts in orchestrator briefs | Stage 0 item 1 (verify enums) | `trap_phase` 1/2/3 vs firmware 0/1/2 |
| Fixture rot from new guard preconditions | Stage 2 warning + Stage 4 | 39 failures from the `boostEnabled` term |
| Stale-binary green runs | `test` skill discipline | timestamps checked at Stages 3 and 5 |
