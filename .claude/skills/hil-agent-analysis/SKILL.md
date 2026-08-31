---
name: hil-agent-analysis
description: Fan out parallel read-only analysis agents over a run_hil_suite.py campaign (HIL Results/hil_report_<ts>/), one agent per run or run family, maintaining a live HIL_FINDINGS.md ledger and closing with a HIL_SUMMARY.md headline digest. Works in two modes — LIVE (the suite is running in the operator's terminal; watch the folder and dispatch agents as runs land) and POST-HOC (the folder is complete; dispatch in waves). Use when the operator starts a suite and asks for monitoring/investigation, or drops a finished report folder for analysis. Analysis-only — tool/sim/suite fixes go to the orchestrated-feature skill afterward.
---

# HIL campaign agent analysis

Multi-agent analysis pipeline for `run_hil_suite.py` campaigns, the HIL sibling of
`benchlog-agent-analysis`. Distilled from the two real fw v23 campaigns
(hil_report_20260830_181426: 39 runs, 13 agents, found the grace-union suite defect
behind 23 false FAILs; hil_report_20260830_203006: 38 runs, 12 agents live-dispatched,
root-caused a sim SOFT-start artifact 3 ms after a validated recovery and adversarially
audited a 26/26 replay PASS). The structure is the point: per-run agents recompute the
suite's own scoring from the raw CSVs — a PASS is only accepted "for the right reason",
and a FAIL is classified scoring-defect vs sim-artifact vs board-real before anyone
proposes a fix.

## Trigger shape and mode selection

- **LIVE mode** — the operator says the suite is running and names the report folder
  ("running the suite now, report at HIL Results/hil_report_<ts>; investigate as the
  logs drop"). Constraints in force: the folder is READ-ONLY, `tools/*.py` is
  edit-frozen until `results.json` reports `"partial": false` (children import the sim
  fresh per run), and any fixes discovered are QUEUED, not applied. If another
  workstream (e.g. an orchestrated round's reviewer) is also running, follow the
  operator's stated priority for whose completion pauses what.
- **POST-HOC mode** — the folder exists and `meta.partial` is false. Same analysis, no
  watcher; dispatch in 2–3 waves sized by verdict class.
- Out-of-band operator facts (what was skipped and why, hardware state, which commit the
  tooling ran, standing rulings) go verbatim into the relevant briefs — the operator
  does not supply fw/tooling versions; read them from the sidecars (`git.rev`,
  `constants_hash`) and `results.json` meta, per run, never assuming homogeneity.

## Stage 0 — Orchestrator scout (never skipped)

1. Read this skill's `references/hil-conventions.md` (the anti-artifact block) and the
   PREVIOUS campaign's `HIL_FINDINGS.md` — it is the baseline every regression brief
   cites. The two examples in `references/` show the expected ledger shape.
2. Inventory the folder: `plan.json` (what was planned; an absent scenario = operator
   exclusion, not loss), `results.json` (verdicts + check details — the authority;
   REPORT.md is a rendering), the sidecar census. A one-screen verdict table via a
   stdlib script under `.venv_hil\Scripts\python.exe` (see conventions file).
3. **Start the ledger immediately**: `HIL_FINDINGS.md` in the report folder — header
   (campaign identity, fw + tooling commit, purpose), a live "Suite verdict snapshot"
   table (one row per run: verdict, failed checks, one-phrase status), and an empty
   "Per-run findings" section. Update the snapshot row when a run's analysis lands
   ("analyzed: <one-line conclusion>"). Writing YOUR files (HIL_FINDINGS.md,
   HIL_SUMMARY.md) into the folder is fine even in LIVE mode — only suite-owned files
   are untouchable.
4. Grep the tooling/firmware for the exact mechanisms under test in this campaign
   (FAULT_EXPECTATIONS entries, scenario stimulus constants, the fault-bit values) and
   verify every number that will enter a brief.
5. LIVE mode: arm the **finalization-aware watcher** (pattern in the conventions file —
   sidecars exist with `results: null` before the run ends and are rewritten in place;
   a new-file watcher misses them). One-shot per event, re-armed after each dispatch;
   a second long-poll fires on `"partial": false`. Never poll in the foreground.

## Stage 1 — Dispatch policy

- **One agent per run** for scenarios (a pair of closely-related clean runs may share
  one agent); **one consolidated agent for the whole replay half** at the end — its job
  is adversarial ("26/26 PASS is either the rework working or new rubber-stamping —
  decide which"), deep-verifying the high-stakes entries and spot-checking the rest.
- **Model policy:** Opus for FAILs, INCONCLUSIVEs, first-executions of a redesigned
  scenario, first-of-kind physics (a mechanism never before observed), and the replay
  audit. Sonnet for PASS regression confirmations against a prior-campaign baseline.
- LIVE mode: dispatch the moment a run's sidecar finalizes — do not batch. Check
  `results.json` at each watcher event; more runs than the event named may have
  finalized (the suite outruns the watcher; a stale `ls` is not the truth).
- A FAIL on a check this session's own tooling round introduced gets an Opus agent
  IMMEDIATELY with an explicit "scoring defect vs real finding" question — the answer
  gates whether the campaign's other verdicts can be trusted.

## Stage 2 — The per-run brief

Self-contained, ~3–5 kB. Parts, in order:

1. **Role + campaign one-liner** (repo root, which campaign, which commit/fw).
2. **Sandbox**: report-folder READ-ONLY (LIVE: "the suite is running in the operator's
   terminal — no writes/locks, never run the suite or simulator"); scratch scripts in
   the agent's scratchpad; "your final message IS the report".
3. **Interpreter + data discipline**: `.venv_hil\Scripts\python.exe`, stdlib streaming
   only, CSV sizes, and "Read `references/hil-conventions.md` items pasted below" —
   include at minimum: blank-pre-first-frame columns, `int(x,0)`, uint8 seq wrap, the
   mdac 0x1000 nibble, the carried-in signature, grace semantics, transient-vs-latch.
4. **What this run is / what changed**: the scenario's stimulus design (constants,
   timings, the expectation entry with its require/allow_only/signals), and — for
   redesigned scenarios — WHY it was redesigned, with the design arithmetic to check
   against.
5. **Baseline**: the previous campaign's section for this run, with its exact numbers
   pasted ("dwell 19.887 ms, teardown ~9–10 ms gaps, 3 benign sw_ring") — diffing
   against them is a task, and sub-1% repeatability is itself a finding.
6. **Questions, numbered, discriminator-first**: (a) scoring validation — recompute the
   fault timeline and unions from the raw CSV and compare to the suite's reported
   metrics bit-for-bit; confirm carried-in bits match the predecessor signature; state
   whether the verdict is right FOR THE RIGHT REASON; (b) the run's own objective,
   measured with timings; (c) anomalies vs baseline; (d) recommended fix
   (suite/scenario/sim/firmware/none) — flagged, not applied.
7. **Report skeleton**: verdict line FIRST ("PASS confirmed correct" / "FALSE FAIL —
   scoring defect X" / "REAL — mechanism Y"), evidence with numbers, explicit
   scoring-correctness statement, follow-ups, stated confidence. Written to be pasted
   nearly verbatim into the ledger.

## Stage 3 — Streaming synthesis + ledger maintenance

- After each agent lands: append its section to `HIL_FINDINGS.md` (condensed but
  faithful — keep every number that carries a claim), update the snapshot table row,
  and post one short interim note to the operator naming anything load-bearing.
- **Cross-run reconciliation is the orchestrator's job**, not the agents': name
  tensions the moment they appear and resolve them with arithmetic (e.g. one agent's
  "anomalous 0.49 V droop" and another's "hifi droop = 0.316 Ω design value" are the
  same fact — 1.54 A × 0.316 Ω; the reconciliation goes in the ledger with a
  cross-reference).
- Classify every FAIL into: scoring defect / sim-model artifact / scenario-design gap /
  board-real. A sim artifact scored FAIL stays FAIL — widening an expectation to pass
  it launders the artifact and masks the only observable of its defect class.
- Maintain a running **fix queue** in the ledger (adjudicated severity, file, one-line
  mechanism) and a separate **operator-decision list** (items needing a ruling or real
  hardware). Analysis rounds do not edit the tools.
- Spot-check at least one load-bearing agent claim yourself against the raw CSV.

## Stage 4 — Close-out: FINAL SUMMARY + HIL_SUMMARY.md

When the suite completes (`partial: false`) and all agents have reported:

1. Append a **FINAL SUMMARY** section to `HIL_FINDINGS.md`: corrected scoreboard (with
   the suite's own tally if they differ), hardware firsts, repeatability results, the
   FAIL classifications, cross-cutting discoveries, the ranked fix queue, and the
   operator items.
2. Write **`HIL_SUMMARY.md`** in the same folder — the headline digest
   (`references/example_HIL_SUMMARY_20260830_203006.md` is the template): scoreboard
   paragraph; one-line-per-headline bullets; a **"Worth reviewing manually"** section
   listing the specific runs (with time windows and files) a human should eyeball —
   first-of-kind physics traces, knife-edge/fragile passes, anything whose entire test
   lives in a few milliseconds, and any run carrying an open question; and the operator
   open-items list. Every claim in the summary must be traceable to a ledger section;
   the summary carries NO numbers that are not in the ledger.
3. Deliver the operator-facing chat summary: scoreboard → what was validated (with
   numbers) → the FAILs and their classifications → lessons → ranked fixes, ending with
   the handoff question ("run the fixes as an orchestrated round?").
4. Routing: tool/sim/suite fixes → `orchestrated-feature` (the fix queue is its Stage-0
   spec seed); firmware-relevant observations → CLAUDE.md addendum / ledger row if a
   version was judged; new conventions or traps discovered this campaign → fold into
   `references/hil-conventions.md` so the next round's briefs inherit them.

## Known failure modes this pipeline exists to catch

| Failure mode | Guard | Instance |
|---|---|---|
| Trusting the suite's self-reported verdicts | agents recompute unions/timings from raw CSVs | grace-union defect: 23 false FAILs, campaign 181426 |
| Rubber-stamp PASS read as validation | "right reason" standard + objective-reached checks | charge-fault/soc-depletion/handoff-sag permissive PASSes |
| Watcher misses in-place sidecar finalization | finalization-aware watcher (results non-null) | new-file watcher missed charge-cruise, campaign 203006 |
| Partial-flush file size read as truncation | append-only caveat; wait for finalized sidecar | 285 KB false alarm on an 8.5 MB ems-drive-cycle CSV |
| Carried-in latch read as in-run fault | predecessor-signature check in every brief | `carried == predecessor_final \| 0x0010`, 26/26 |
| Transient indication reported as latch time | latch = bit ∧ FAULT_ERROR rule | TP0010 321 ms early, TP0053 536 ms |
| Sim artifact laundered into an expectation | FAIL-classification rule; never widen allow_only | comm-loss SOFT-start pre-charged-node artifact |
| Model-fidelity boundary read as board physics | fidelity-boundaries list in conventions | regen power floored → SOC fell during "charging" |
| Editing tools mid-suite mixes code versions | edit freeze until partial:false; queue fixes | fix round held ~40 min, campaign 203006 |
| Vacuous checks inflating a PASS count | substantive-vs-vacuous audit in the replay brief | 32/79 replay checks vacuous (current ≡ 0) |
| Stale run-order assumptions in briefs | verify predecessor from results.json order | bringup inherited from handoff-sag, not ems-drive-cycle |
| Self-confirming comparisons | compare against ground truth, not the derived quantity | encoder panel lesson inherited from benchlog rounds |
