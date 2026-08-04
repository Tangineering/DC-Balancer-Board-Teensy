---
name: adversarial-doc-review
description: Run a Codex↔Claude adversarial review loop against a document, model, or firmware aspect — Codex challenges it, finding-verifier agents confirm/refute each finding against the authoritative hardware sources with recomputed bounds, a counter-review round settles severities, and the adjudication lands in the review ledger. Use when the user asks to adversarially review, codex-review, or red-team the firmware, the control model, a debug/incident doc, or a thesis chapter ("run the adversarial loop on the share-loop model", "have Codex challenge the boost-death analysis", "red-team the sequencing rules"). Review-only — ends at the adjudication table; fixes need explicit approval.
---

# Adversarial document/aspect review loop (review-only)

Orchestrates: Codex adversarial review → parallel `finding-verifier` agents → Codex
counter-review → adjudication → ledger update. Both rounds run **task-class** Codex
threads (the plugin's app-server review path is diff-scoped and its threads are not
resumable). This skill never applies fixes: it terminates at the adjudication table, and
approved findings go through the repo's normal fix discipline (implementation +
`self-review` skill, `/test` both builds, plus `pinmap-audit` / `protocol-bump` /
`regen-coeffs` / `bench-incident` as the change class demands).

## Review domains and their ground truth

Every finding in this repo is settled against an authority, in this order — never against
the reviewed text's own claims:

1. **Firmware** (`teensy_controller/teensy_controller.ino`, `test/`): the IO CSV wins over
   the code; then BOM, schematic PDF, `references/Datasheets/Ag105_Table*.json`, component
   datasheets. Safety claims (sequencing, back-feed, hot-plug) check against CLAUDE.md §2
   and the bench record.
2. **Systems & control modeling** (`controller_design/`): `system_model.md` is the plant
   source of truth; `controller_synthesis.md` the design record. Quantitative claims are
   recomputable — the Python toolchain (`uv venv` + numpy/scipy, never system pip) can
   re-run `synthesize_controller.py` gates, `validate_model.py`, `tps61288_full_model.py`.
   `share_controller_coeffs.h` is generated; a finding proposing to hand-edit it is
   automatically wrong.
3. **Circuit board debugging** (`docs/boost-bringup-debug.md`, `docs/boost-diagnostics-
   summary.md`, scope captures in `references/scope_captures/`): the death record is
   append-only bench truth. A finding may challenge a *hypothesis* (anything marked
   UNCONFIRMED) but not a recorded datapoint; conversely, the reviewed doc citing an
   UNCONFIRMED hypothesis as settled fact **is** a valid finding.
4. **Report/thesis writing** (`docs/*.md`, `controller_design/*.md`, PLAN.md): claims must
   trace to the sources above or to committed results files (`synthesis_metrics.txt`,
   `fullorder_metrics.txt`, `MATLAB_*.txt`, `figures/`). Numbers that appear in prose but
   in no results file are findings.

Companion runtime: `node "<plugin-root>/scripts/codex-companion.mjs"` where plugin-root is
the newest version under `~/.claude/plugins/cache/openai-codex/codex/`. Its stdout mixes
progress lines and a DEP0190 warning with the payload — slice from the first markdown
header when parsing.

## Step 0 — Preflight and ledger resolution

1. `codex login status` must show logged in; `codex-companion.mjs status` must show no
   active jobs. Abort with instructions (`/codex:setup`) if not.
2. Resolve the **review project** in `docs/reviews/README.md` (create the registry file on
   first ever run). If the target has no project yet, register it: add the registry row
   (slug, unique uppercase prefix — e.g. `FW`, `CTRL`, `BOOST`, `RPT` — target path),
   create `docs/reviews/<slug>/ledger.md` with an empty active-findings table. Same target
   reviewed again = same project, next run number — never a second project.
3. Determine run number `R<n>` from existing `run-*` files; create
   `docs/reviews/<slug>/run-<NNN>-<date>.md` as you go (append-only record of both
   rounds, verdicts, adjudication).
4. Build the **ledger digest**: every row's ID, status, one-line finding, one-line
   rationale — from this project's ledger *and* any other project whose scope overlaps
   the target (firmware and control-model reviews overlap heavily via
   `share_controller.h`; boost-debug and firmware reviews overlap via the sequencing
   rules). Include the re-raise rule verbatim: settled items reopen only with new
   evidence, stated explicitly.

## Step 1 — Codex round 1 (task-class, background)

Compose the round-1 prompt file in the scratchpad. Before writing it, read
`codex:gpt-5-4-prompting` (Skill tool) for composition guidance, and reuse the
adversarial *stance* language from the plugin's `prompts/adversarial-review.md` template —
but frame the target as the document/aspect itself, not a diff. The prompt must contain:

- the target file path(s) and an instruction to read them fully;
- numbered challenge areas (from the user's focus text, or derived from the target's
  section map — enumerate its major claims). Domain defaults when the user gives none:
  - *firmware*: switch-sequencing/back-feed/hot-plug safety, polarity and register values
    vs datasheets, fault coverage and state-machine reachability, telemetry/protocol
    consistency, test coverage of the claimed behaviors;
  - *control model*: plant assumptions (symmetric τ_r, corner coverage, neglected
    dynamics), synthesis gate validity, discrete-implementation fidelity, calibration
    TODOs presented as settled;
  - *debug docs*: does the evidence actually support the stated mechanism, are
    UNCONFIRMED/confirmed boundaries honest, do the remediation steps follow from the
    diagnosis;
  - *reports*: number traceability, internal consistency across documents, superseded
    claims still stated as current;
- the ledger digest with the re-raise rule;
- the severity contract: **a severity claim must cite a computed bound, a reachability
  argument, or an exposure path — risk language alone is not a severity.** In this repo
  the top exposure classes are hardware destruction (boost/VESC/charger kill paths),
  unsafe motor or switch states, silently wrong published numbers (thesis/model), and
  Pi-bridge protocol desync;
- the required output shape: verdict line, then findings each with severity, file:line,
  what-can-go-wrong, and a concrete recommendation;
- permission to consult the implementation, datasheets, and design files to check the
  document's claims against them — with the authority order from "Review domains" above
  stated explicitly (the CSV wins over the code; the death record is bench truth).

Launch in a backgrounded Bash, prompt via stdin, read-only (never `--write`):

```
cd <repo> && node "<plugin-root>/scripts/codex-companion.mjs" task < <prompt-file>
```

Immediately capture from the output file: the `Thread ready (<id>)` line and, on
completion, the verbatim findings — both go into the run record before anything else
happens. Tell the user the review is running and which models the verification round
will use (cost transparency).

## Step 2 — Verification fan-out

Parse the findings into ledger IDs `<PREFIX>-R<n>-<seq>`. **Strip Codex's severity labels
from the briefs** — severity is assigned by verification, not negotiated down from the
reviewer's label. Route each finding by class and say so in the kickoff message:

- quantitative / source-verification (scale factors, register values, divider math,
  synthesis margins, plant constants, telemetry byte arithmetic) → **opus**
- open-ended adjudication (scope, process, model-assumption validity, overlaps prior
  reviews, incident-analysis reasoning) → **fable**
- mechanical / wording / citation-label / doc-drift → **sonnet**

Launch all `finding-verifier` agents (subagent type from `.claude/agents/`) in one
message. Each brief contains, pre-digested by you so agents don't re-derive it:

1. the finding verbatim (minus severity);
2. the relevant target excerpt pasted in (not "go find it in a 3,000-line file");
3. pre-grepped entry points (files + line ranges) — code, datasheet JSON, or model script
   as the finding demands;
4. the ledger digest;
5. pointers to the committed results the finding could impact
   (`controller_design/*_metrics.txt`, `reference_vectors.h`, PLAN.md §6b layout, the
   death record) for published-number and safety-claim impact checks.

The agent definition already carries the output contract (VERDICT / EVIDENCE /
QUANTIFICATION / SOURCE / DUPLICATION / SEVERITY-ASSESSMENT / MINIMAL-FIX /
ADJACENT-FINDINGS), the recompute-don't-read rule, the authority order, and the
prove-your-fix rule. Remind agents with build/run needs of the toolchain quirks: no
`make` on this machine (MSYS2 `mingw32-make` or direct g++; the `test` skill's invocation
is canonical), and Python only via `uv venv` in `controller_design/`.

**Optional `--deep`:** additionally launch one independent first-pass reviewer (fable) on
the same target with the same ledger digest but *without* Codex's findings, running
concurrently. Its yield feeds the adjudication as `claude-review`-sourced findings, and
the adjudication must include a coverage comparison (what each reviewer found that the
other missed).

## Step 3 — Codex round 2 (counter-review)

Summarize — do not forward — the verdicts: per finding, the verdict, the specific
quantitative refutation or confirmation, the proposed minimal fix, plus all adjacent
findings as new items. State the response contract: CONCEDE / DEFEND / REFINE per
finding, and **defending a severity requires rebutting the quantitative bound, not
restating risk language**. Ask for a ranked final adjustment list.

Send by resuming the round-1 thread:

```
cd <repo> && node "<plugin-root>/scripts/codex-companion.mjs" task --resume-last < <rebuttal-file>
```

(`--resume-last` works because round 1 was task-class.) If resume fails anyway,
reconstruct: fresh task with the round-1 output verbatim + the rebuttal. Append the
response verbatim to the run record.

If round 2 produces a genuinely new defensible position, verify it yourself if small, or
send it to one more finding-verifier if substantial — do not iterate the Codex loop
further unless the user asked for more rounds.

## Step 4 — Adjudicate, ledger, stop

1. Merge both rounds into the adjudication table, most severe first:
   `ID | alias/source | final severity | status | finding | agreed fix | rejected parts`.
   Final severity comes from the verification round as modified by any conceded round-2
   arguments. Disagreements that survive round 2 are presented as disagreements — you
   adjudicate with stated reasoning, you don't paper over them.
2. Update `ledger.md`: new rows for every finding (including adjacent and `--deep`
   findings), statuses `accepted`/`rejected`/`settled-caveat` with one-line rationales;
   update any legacy rows the run touched (e.g., an open theme partially discharged).
3. Finish the run record. Present the table plus the rejected-recommendations list with
   rationales, and remind that a clean review is a valid result.
4. **Stop.** No edits to the target, code, or configs. Tell the user approved findings
   proceed via the normal fix discipline, and name the follow-on skills the fix class
   triggers: firmware changes → `self-review` + `test` (both BENCH_TEST builds) and
   `pinmap-audit` before any flash; packet-layout changes → `protocol-bump`; plant-model
   or calibration-constant changes → `regen-coeffs` (never hand-edit
   `share_controller_coeffs.h`); anything learned about/from the bench →
   `bench-incident`.

## Failure handling

- Codex nonzero exit / empty findings: read the task output file for the error; auth
  errors → `/codex:setup`; do not silently retry more than once.
- An agent dying or returning off-contract output: relaunch that one finding, not the
  batch.
- Findings > ~8, or the user asks for exhaustive multi-round sweeps: propose the Workflow
  tool (pipeline over findings with schema-forced verdicts) instead of hand fan-out, and
  get the user's opt-in first.
