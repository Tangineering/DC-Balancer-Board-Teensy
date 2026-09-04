---
name: overnight-autonomous-session
description: Run an unattended multi-campaign HIL work session — WORK_QUEUE execution, campaign/analysis/fix cycles, dual-agent decision pairs, decision logging with reversal paths, and a morning digest. Invoke when the operator authorizes overnight/away autonomous work.
---

# Overnight autonomous session

Process for running this project unattended for hours: working WORK_QUEUE.md, running
up to N HIL campaigns with analysis and fix rounds between them, resolving judgment
calls without the operator, and leaving a reviewable record. Distilled from the
2026-08-31/09-01 session (4 campaigns, ~218 runs, 2 decision pairs, 5 commits, zero
board defects, zero destructive actions) and its retrospective (OVERNIGHT_LOG.md,
same date — read it; every rule below cites a failure or a win from that night).

## Trigger and mandate

The operator explicitly authorizes autonomous work ("overnight plan", "while I'm
away") with: a scope (usually WORK_QUEUE.md), a campaign budget ("up to five"), a
judgment-call protocol (see Decision pairs), and any hard constraints (e.g. "firmware
ready but NOT flashed"). Absent an explicit budget or protocol, ask before the
operator leaves — do not infer a mandate.

## Standing guardrails (non-negotiable, in EVERY agent brief)

- The two `.ino` build-flag lines (BENCH_TEST/HIL_SIM operator flip) are never
  committed and never git-restored. Committing the `.ino` = flip to repo defaults →
  commit → flip back, then verify the worktree diff is exactly the two lines.
- `PSCAD/` (and anything provenance-unconfirmed) stays uncommitted. `HIL Results/`
  is gitignored — ledgers live there, never in a commit.
- **No tree-wide git operations by ANY subagent** (stash/reset/checkout — the stash
  incident). State it in every implementer brief. Truly overlapping file sets are
  sequenced, never parallelized; disjoint sets (firmware vs tools/) may run in
  parallel and that is the biggest wall-clock win.
- During a live campaign `tools/*.py` is edit-frozen (children import fresh per
  run). Firmware, docs, CLAUDE.md, new data files are safe.
- Background work only via harness-tracked backgrounding — never an inline `&`
  (untracked, output lost, duplicate races).
- Nothing destructive, nothing flashed, no protocol/wire changes unless the mandate
  names them. When in doubt whether an action is in-mandate: log it as a decision
  with a reversal path, or defer it to the morning list.

## Session skeleton

1. **Init:** append a session header to OVERNIGHT_LOG.md (mandate verbatim, start
   commit); verify board reachability; confirm the tree is committed/pushed before
   the first campaign.
2. **The cycle** (repeat within the campaign budget):
   a. Launch the full suite (background, tracked). Note the report folder.
   b. While it runs: parallel orchestrated rounds on DISJOINT files only
      (firmware during a campaign is ideal); otherwise draft docs/specs.
   c. On completion: **tool pass (hil_report_analysis.py) FIRST, always** — then
      dispatch analysis against the stable subfolders (the C3 race).
   d. Analysis effort scales with novelty: first campaign on new scoring/scenarios
      → per-batch agents + the adversarial replay audit (the hil-agent-analysis
      skill, LIVE dispatch); validation campaigns → one consolidated agent, light
      pass, still recomputing everything it asserts. The right-for-the-right-reason
      standard never relaxes; the agent count does.
   e. Ledger (HIL_FINDINGS.md) + digest in the report folder; adjudicate the fix
      queue; run the fix round (streamlined orchestration below); rerun both
      interpreter suites yourself; commit + push in logical chunks.
   f. Next campaign validates the fixes. Stop early when a campaign is clean AND
      the marginal campaign would only add repeat datapoints — log the stop
      decision with reasoning (the stop-at-four precedent).
3. **Close-out:** CLAUDE.md addenda (per the addendum-rotation convention),
   WORK_QUEUE.md refresh (mark shipped/blocked, add discovered prerequisites),
   the MORNING DIGEST, final commit/push, then the retrospective.

## Streamlined orchestration (away-mode variant of orchestrated-feature)

Implementer (Opus, writes its own tests) → combined or two-lens review → fix agent →
orchestrator rerun of every affected suite. What is NOT streamlined away: the review
stage (it caught one HIGH per round all night), the deviation license (reviewer fix
text was wrong twice; implementers must be free to deviate with documentation), the
orchestrator's own rerun-and-verify, and the adversarial audit after any
scoring-semantics change (the ML0217 lesson: a fix round shipped a wrong record
attribution that only the next audit caught). Fix rounds that edit RECORDS or
attributions meet the analysis evidence standard — recomputed from raw data, never
from adjacent comments.

## Decision pairs (operator-prescribed judgment protocol)

For a genuine judgment call: two independent agents on different models (Fable +
Opus), identical decision prompt carrying every measured number and the artifacts to
consult; the orchestrator adjudicates. Adjudicate by SYNTHESIS, not winner-picking —
and treat disagreements as data (opposite readings of the MPPTD semantics exposed an
unverified hardware assumption, which itself shaped the ruling). Skip the pair only
when measurement has already answered the question decisively (the chatter-hysteresis
ruling); say so in the log either way. Every ruling gets an OVERNIGHT_LOG entry with:
the evidence, the ruling, and the REVERSAL PATH (a one-commit undo the operator can
take in the morning).

## Scenario/check design rules (paid for in failures)

- First-campaign checks prefer PHASE-FREE properties: max continuous hold,
  fractions, counts, bands on levels. A position/absence assertion at a
  model-predicted instant fails on model error while the mechanism works (the S2
  FAIL: walk period wrong 5.7×).
- Offline walks must state which firmware MODE they assume per segment, and must
  model BOTH sub-0.55 A open-loop submodes: the HOLD (which broke two walks the same
  way) AND the slew-limited FEEDFORWARD that writes the MDACs on a changed setpoint
  (which failed the MPC's Gate 1, 2026-09-02). The strategy-authoring notes are
  required walk inputs.
- provisional_note on every unmeasured band; the first campaign is the calibration
  source; delete the note when pinning. Never widen a threshold to pass a known
  artifact.
- Cross-run/frontier metrics: state what the metric structurally CANNOT distinguish
  (the vs-bound arm is ~1.0 for any charge-free candidate) before anyone reads a
  1.0000 as optimality.

## Failure modes added 2026-09-02 (second overnight session: 2 campaigns, 30+ agents)

- **The bench console is cp1252.** Any non-cp1252 glyph in a simulator/suite/strategy print
  kills the child (five of 66 runs). Subagent smoke runs never catch it (UTF-8 pipes). Tool-side
  prints stay ASCII; `hil_plant_sim.main()` now reconfigures stdout lossless and finalizes the
  sidecar in a `finally`, but a new print path needs the same care. Memory:
  `windows-console-encoding-trap`.
- **A campaign can cross TWO plant eras at once.** Every brief must state every run-era field
  that moved since the baseline campaign (charger era, `asymmetry`, preload, droop mode), read
  from the sidecars — "same as baseline" written from memory was wrong for 16 runs and would have
  mis-attributed every drift to the charger change.
- **A new scoring spec needs the judge to support it.** A `column` + `min_ticks` pairing was
  structurally unimplemented and failed a correct board; the import guard now refuses any pairing
  the judge cannot honour. Calibrate a pin against the campaign it cites (the mppt pin failed its
  own calibration data). A mask on a switch bit needs a settling hold for currents that decay
  after the bit clears.
- **A fix round that changes scoring semantics gets its own review BEFORE the validating
  campaign when board time allows, and always before the ledger reads its verdicts** — the
  review here predicted campaign C's one false FAIL in advance, which turned it from a finding
  into a known artefact.
- **Long shell heredocs break the tool wrapper** (two launches lost). Write files with the Write
  tool and keep Bash heredocs short and free of nested quoting.
- **Decision pairs pay off on design, not only on rulings**: the MPC pair disagreed on the
  prediction architecture and the real-time model, and the synthesis (plus its review) found the
  adjudicated mechanism inert in the first implementation. Ship a failing gate with the number
  recorded rather than a passing one measured on an inert path.
- **Read a verifier's "consequence" separately from its "mechanism"**: three of eight
  adversarial findings had a correct mechanism and a refuted consequence; severity follows the
  measured consequence.

## Logging discipline

OVERNIGHT_LOG.md gets, as they happen: decisions (with reversal paths), incidents
(with the correction adopted), campaign headlines, adjudications. The MORNING DIGEST
is written last but placed prominently: what was asked vs delivered, headline
findings with pointers, the reversible-decisions list, and the operator's bench list
for today. The digest cites; it never contains numbers absent from a ledger.

## Close the loop

End with a retrospective in OVERNIGHT_LOG.md (what worked with evidence, what failed
with the correction, economics) — and fold any NEW failure mode into this skill so
the next session inherits it.

## Additions from the 2026-09-02/03 session (fw v26 campaigns D, E, F)

- **Isolate every campaign from concurrent tooling work.** Run the suite from a detached
  `git worktree` at the committed tooling with `--out` into the main tree's `HIL Results/`, and
  run tooling rounds during a campaign in `isolation: worktree` agents; merge after the campaign.
  Traps: `core.autocrlf` turns generated modules CRLF in a fresh worktree (`.gitattributes -text`);
  worktree suites skip tests that need gitignored artifacts.
- **Stage from `git status`, never from the implementer's file list**, and smoke the CLIs
  (`--help`) of every module a round touched before committing: one round left a file unstaged
  and a stray edit of unknown provenance broke a CLI no test imports through `main()`.
- **Never put backticks in a `python -c` string under bash** — command substitution mangles it
  and half-applies multi-file edits. Write scripts to the scratchpad and run them by path.
- **When a reviewer dies to an API error, re-dispatch a narrower brief on another model** and run
  the suites yourself in parallel so the commit does not wait on the reviewer's test run.
- **Stepped stimulus tables need a shape test (one axis per boundary) and an EMA-lag
  reconstruction bound**; a walk without the governor's filter lag cannot see a step-transient
  latch. The firmware's own profiles interpolate for this reason.
- **Any sidecar counter the run loop updates must be refreshed in `finalize_meta()`**; a field
  written at construction reads its initial value forever. Validation briefs compare the sidecar
  value against the trace.
- **After a State-99 latch, every aux-bit and mirror check reads the frozen value**: downstream
  PASSes are non-evidence and the successor inherits the bits until its warm reset. Window such
  checks post-grace and say so in the ledger.
- **Classify FAILs live, per run, while the campaign runs** (read-only agents on the finalized
  sidecars): the fix round is then ready at completion and the next campaign validates it within
  the same night.

## Additions from the 2026-09-03/04 session

- **Opt-in legs:** the HIL suite hides its long-cycle and alpha legs behind flags (`--with-ftp75
  --with-ftp75c --with-alpha`); a bare launch runs 61 of 75 and reports the rest as vacuous PASSes. Read the
  `--list` footer ("[IN THIS PLAN]") before every launch; the launch script carries the flags.
- **Watchers are harness-tracked or nothing:** never `nohup ... &` / `& disown`; they lose their output and
  linger. A tracked watcher that exits on each event and is re-armed is the only pattern.
- **Never chain a stdin-reading command in a Bash call** (`cat > path` without a heredoc hangs to the timeout).
  Scripts go through the Write tool and run by path with `</dev/null`.
- **First-sighting anchors must exclude the carried-in window** (a predecessor's latch bit can shadow a run's
  own later fault and disable a teardown exclusion, fail-open).
- **Era re-pins enumerate every quantised axis each strategy reads** (demand bins, gates, thresholds), not
  only the h2 anchors; h2 is blind to a raw request the firmware clamps.
- **A stimulus expressed as a designed total is re-derived at every governor-constant change** with its
  structural bound stated (the joint leg's 1.65 A step exceeded the fault limit at I_min 0.15).
- **Pre-classify the next pass from the current one:** when a mechanism is found on one leg, name the legs
  it must also hit before they run; the analysis then needs one agent per mechanism, not per run.
- **A sim fix is closed only by a re-executed PASS**, never by the model's own before/after numbers.
