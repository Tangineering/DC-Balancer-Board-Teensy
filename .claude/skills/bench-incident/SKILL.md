---
name: bench-incident
description: Log a bench bring-up event, hardware failure, scope capture, or diagnosis change into docs/boost-bringup-debug.md using the project's established rigor (death numbering, datapoint format, explicit UNCONFIRMED hedging, superseding rather than deleting wrong theories). Use this whenever the user reports something that happened on the bench — a boost death, a surviving bring-up, a scope measurement, a bodge, a new or retired hypothesis — even if they just describe it conversationally without asking for documentation.
---

# Log a bench incident / bring-up datapoint

`docs/boost-bringup-debug.md` is the project's failure-analysis record, and its rigor has
directly paid off: two early theories (inrush; reverse conduction as the confirmed mechanism)
were wrong, and only because they were recorded with evidence and then *explicitly
superseded* did the code and docs stop repeating them. This skill keeps new entries at that
standard. Hardware context: five boost deaths so far; the thesis will cite this log.

## Before writing

Read the current end of `docs/boost-bringup-debug.md` — at minimum the "Failure datapoints",
"Ruled OUT (with evidence)", root-cause, and "Safety rules for further bench work" sections —
so the new entry uses the next death number, doesn't re-litigate settled points, and lands in
the right section.

**Scope-metrology rules are binding (added 2026-08-03 after two transcription errors — a
3.9× current unit slip and an inverted channel reading — survived into the log):** follow the
doc's "Scope-metrology conventions" section. In short: record readings as
`<divisions> div × <scale> = <value>` with probe/coupling/BW-limit and the zero-reference
noted; quote trace-centre levels, not edge-to-edge cursor spans; give peak AND ∫I dt with an
envelope for current events; file the capture (net name in the filename + a one-line
scope-state transcription) before building conclusions on it; keep sections chronological
with explicit "supersedes §X" pointers on corrections.

## Entry conventions (match the existing file exactly)

- **Placement:** new events go under `## Failure datapoints` as a dated `###` subsection.
  Marker prefixes: `☠️ Death N (<which part>) + <context> (YYYY-MM-DD)` for a destroyed
  part; `(PASS — <what it demonstrates>, YYYY-MM-DD)` for a survival/validation;
  `⭐ FIX VALIDATION` when a run validates an intervention.
- **Record the conditions, not just the outcome:** supply type and stiffness/current limit,
  which switches/boosts were on, `V_bus` state, firmware build (`BENCH_TEST` value, relevant
  commands like State-98 `G`), and what changed since the last datapoint. Single-variable
  tests are the gold standard here — say explicitly what the single variable was.
- **Hedge honestly.** Distinguish *observed* (measurements, what died, shorted pins) from
  *inferred* (mechanism). If the mechanism isn't scope-confirmed, write **UNCONFIRMED** and
  name the measurement that would settle it (e.g. "pending SW/VOUT capture"). Scope captures
  go in `references/scope_captures/` and get referenced by filename.
- **Supersede, never delete.** If the event changes the diagnosis, do not rewrite history:
  mark the old analysis superseded in place, add the new analysis, and move disproven
  theories into `## Ruled OUT (with evidence)` with the evidence that killed them.
- **Ripple the conclusions outward.** If the diagnosis, a safety rule, or a required bodge
  changed, update in the same pass:
  - `## Safety rules for further bench work` and `## Next steps` in the debug log;
  - the relevant CLAUDE.md status addendum (add a superseding note, matching how the
    inrush-framing correction was done);
  - any firmware comments that state the old theory (grep for it);
  - `docs/boost-diagnostics-summary.md` if the summary now disagrees with the log.

## After writing

Summarize for the user: the entry as logged, what (if anything) it supersedes, which safety
rules or firmware assumptions it touches, and any follow-up measurement now blocking. If the
event implies a firmware change (new guard, threshold, sequencing rule), flag it as a
separate task rather than bundling it into the doc edit.
