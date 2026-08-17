---
name: benchlog-agent-analysis
description: Fan out parallel read-only analysis agents over a batch of bench logs (BLG runs in logs/), one hypothesis-directed brief per run family, then synthesize the reports in the main session. Use whenever the user drops new logs and asks to analyze them with agents ("I've added logs N–M — use agents / fan out agents / analyze the results"), or when a bench batch is too large or anomalous for inline analysis. Analysis-only — firmware fixes go to the orchestrated-feature skill afterward.
---

# Bench-log agent analysis round

Multi-agent analysis pipeline for batches of State-98 bench logs. Distilled from the
transcripts of eight real rounds (share-sweep logs 7–124 across fw v2–v6; drive-controller
rounds TP0125–134, ML0136–139, ML0140–145 across fw v8–v12), including the four-agent
round that found the boxcar-estimator limit cycle and the six-agent round that separated
three superposed defects the individual runs made look contradictory. The structure is the
point: per-run agents derive numbers independently; the orchestrator's synthesis earns its
conclusions from cross-agent convergence, not from averaging.

## Trigger shape

The operator's request is near-templated and carries facts the logs do not:

- Which logs arrived, and that the analysis pipeline **already ran** (if not, ingest is
  yours — see Stage 0 step 2).
- The operator does **not** supply the firmware version — fetch it from the logs
  themselves. The BLG header carries `fw_version` (since header v2); read it from each
  run's `decode_report.txt` (or via `decode_benchlog` as a library) in Stage 0, per log,
  and never assume a batch is homogeneous. It is a first-class caveat, because traces
  across fw versions can be different control laws (v11 vs v12 vs v14) even when `v_act`
  scale is comparable.
- Out-of-band operator facts (breakaway current, a direction change, a bodge, "still
  having issues", a scope/plotter photo). These go verbatim into the relevant agent brief.
- Usually a downstream deliverable: whitepaper update, next steps, or both.

## Stage 0 — Orchestrator scout (never skipped, before any dispatch)

1. Read the toolkit memory (`benchlog-analysis-toolkit.md`) and this skill's
   `references/log-conventions.md`, and inventory `logs/`: `ls -la logs/*.BLG` — an
   un-truncated full-preallocation file (~33.5 MB) is an MCU-stop signature; note it
   per run.
2. **Run the batch scout** — it does the folder-completeness check, the conditional
   pipeline run, the decode-report table, and the quick stats in one command:

   ```
   .venv_benchlog/Scripts/python.exe tools/benchlog_analysis/scout_batch.py --range ML 146 151 --fix
   ```

   (positional `.BLG` paths also accepted; mixed prefixes = two invocations). Per run
   it emits: folder state (complete/partial/missing), format version, `fw_version`,
   `profile_type`, records, `close_reason`, `error_code`, dropped, duration, median
   interval, actual rate Hz, `V_bus` min, |I_cmd| max, `v_act` max, and a gated
   share-tail mean±sd. `--fix` runs `make_figures.py` (ingest + all PNGs) on any
   incomplete run — skip-if-complete is automatic, and `analysis_config.json` is never
   overwritten. Truncated logs show `close=inferred:none` — infer the stop cause from
   the last records and say you inferred it. The table pastes directly into agent
   briefs (part 6).
3. If the scout's stats don't discriminate the batch's anomaly, run a deeper **quick
   scan** in-session (throwaway numpy script under `.venv_benchlog/Scripts/python.exe`,
   in the scratchpad — numpy/matplotlib, **no pandas**) targeted at the operator's
   complaint. This is what lets each agent brief carry an individualized hypothesis
   instead of a generic "analyze this".
4. Grep the firmware for the exact constants and mechanisms under test
   (thresholds, governor clips, fault arming) so briefs carry mechanism definitions, not
   paraphrases. Verify every number you put in a brief against source.
5. Announce the fan-out plan to the user in one short message: how many agents, split by
   what, before dispatching.

## Stage 1 — Fan-out design

- **Split by hypothesis / run family, not just by index.** Give the faulted or mystery
  cluster its own agent ("these faults at in-band setpoints are NEW versus fw vN — this is
  the batch's central mystery. Determine the mechanism."); clean bands get confirmation
  agents; a repeat-run pair gets a repeatability brief; a cross-direction or cross-firmware
  comparison gets its own agent with the reference numbers embedded.
- **Model policy:** Opus for faulted/anomalous/mystery runs, numeric deep dives, and
  first-of-kind controller runs (every ML-round agent was Opus); Sonnet for clean-band
  confirmation, baselines, and mechanical audits. 1–2 logs per agent for dense runs; up to
  ~12 for clean-band sweeps.
- **Target 4–6 agents per round regardless of batch size** (the real rounds ran 3–6 over
  batches of 4–27 logs). Scale by grouping clean runs into wider bands, not by adding
  agents — agent count should track the number of distinct hypotheses, not the log count.
- **Add one cross-cut lens on multi-mechanism batches:** a "mechanism audit" agent that
  does no per-run narrative — for each firmware mechanism under test, it finds every
  instance where the mechanism should have acted and issues a forced verdict from a fixed
  vocabulary: WORKED AS DESIGNED / WORKED BUT INSUFFICIENT / DID NOT FIRE (UNTESTED) /
  MISBEHAVED. Two rules travel with it: "a fault that never fired is untested, not
  validated", and "a mechanism that worked while the problem persisted anyway is the most
  important kind of finding". It reads the `.ino` implementations, not summaries.
- For drag/physics campaigns, add a separate **synthesis agent** (Opus) that re-derives the
  fit itself: give it your quick-scan table with "verify yourself, esp. hold detection",
  the model-doc sections that define the constant's convention ("check how the model
  constructs the DC gain so the fitted value lands in the model's convention, not a
  private one"), and "state which explanation the DATA supports, don't just list them;
  flag anything that smells inconsistent rather than averaging it away."
- Launch every agent of a wave **in one message** (parallel), background,
  `subagent_type: general-purpose`.

## Stage 2 — The per-agent brief (7-part template)

Each brief is self-contained (~4–6 kB). Parts, in order:

1. **Role + system one-liner.** "You are a per-log analyst for bench logs from a scale-car
   DC power-balancer board (Teensy 4.1, two boosts sharing a ~16 V bus via droop + Youla
   share controller). Repo root: …"
2. **Sandbox.** "READ-ONLY except scratch analysis scripts in a temp dir — never write
   into the repo or logs/. Your final message IS the report."
3. **Interpreter.** `.venv_benchlog/Scripts/python.exe` at repo root, numpy/matplotlib,
   **no pandas**. State it; do not make the agent hunt.
4. **Firmware-under-test context** with exact constants, including the logging caveats
   that prevent false findings (e.g. "the LOGGED share_sp is the RAW commanded setpoint;
   the clip is internal — apparent tracking error at low current is governor action, not a
   bug", with the reconstruction formula to compare against instead).
5. **Design expectations / prior-firmware baseline** — the numbers the run is judged
   against: predicted bandwidth, PM, settle time, overshoot, clamp behaviour ("u_unsat
   should hug the rail during saturation; divergence far beyond it indicates windup"), or
   the previous firmware's known-clean and known-failing setpoints.
6. **YOUR RUNS** — explicit list with the Stage-0 verified metadata pasted in (fw version,
   records, close_reason, error_code, Vmin) and the per-run hypothesis or anomaly flag
   from the quick scan.
7. **DATA + LOG CONVENTIONS** — the anti-artifact block, maintained as a single source
   of truth in this skill's `references/log-conventions.md` (column schemas per BLG
   format version, timing, signal semantics, the v5 `u_unsat`/`drive_x0` interpretation
   rules, statistics hygiene, provenance/comparability, environment). Tell the agent to
   Read that file, and paste inline only the items the specific round depends on plus
   any round-specific caveat (e.g. "reference trace is a different control law; sign
   convention may differ"). The decoder (`tools/decode_benchlog.py`) is the authority
   over the reference file if they disagree.

Then **TASKS**, numbered and hypothesis-directed, with a **falsifiable discriminator
first** when one exists ("FIRST: is v_act on the 0.0177 m/s quantization ladder or
timer-fine? — this determines whether the new estimator is actually running"), explicit
falsification instructions, and — if the orchestrator reasoned aloud in the brief —
"verify this from the data rather than trusting this reasoning."

Finally **REPORT** — a fixed skeleton, in this order, so synthesis can scan reports
uniformly and a skipped section is visible:

1. **Metadata echo** — per run: fw_version, records, close_reason, sample rate measured
   from `t_us` (one line each; confirms the agent analyzed the right files).
2. **Per-run summary table** with named columns (the brief specifies them).
3. **Discriminator answer** — the brief's falsifiable discriminator, answered first and
   explicitly, with the measurement that decides it.
4. **Mechanism / findings** — each with concrete numbers, timestamps, and which PNG best
   illustrates it.
5. **Verdict** — one paragraph: does the run validate the design expectation, what
   specifically deviates.
6. **Ranked root-cause hypotheses** (when the brief asks for causes).
7. **Open questions / anomalies not explained.**

Rules: "numbers over prose", "Read the PNGs (the Read tool renders images) AND derive all
numbers from the CSV — figures show shape, CSV gives numbers", "final message = the
report only, in exactly this skeleton".

Never hand an agent a paraphrased plot. Give it the CSV, or state the axis units
explicitly — a described Serial Plotter screenshot (x-axis is sample count, not seconds)
once produced a spurious 36× force discrepancy and a withdrawn "decoupled flywheel"
conclusion.

## Stage 3 — Streaming synthesis (main session)

- **Interim notes, not batch silence.** After each agent lands, post one short note: what
  it confirmed, what is new, what stays open ("corroborates ML0136 quantitatively — an
  independent derivation of the same root cause. Waiting for the other N before
  synthesizing."). Name cross-run tensions the moment they appear, before resolving them.
- **Convergence = independent derivation.** A root cause is earned when multiple agents
  derive it separately and the arithmetic chains agree (quantization ladder → window
  length → group delay → phase deficit vs design PM, confirmed by measured
  cross-correlation lag). State the chain in the synthesis.
- **Resolve contradictions; never average them.** Apparently conflicting runs (velocity
  low in one, high in another; growing oscillation vs decaying at the same setpoint)
  usually resolve into distinct superposed defects — separate, name, and **rank** them.
- **Verify before accepting.** Spot-check at least one load-bearing agent claim yourself
  against the CSV, and correct agents' stale claims in the synthesis explicitly ("one
  correction to ML0139's report: the VESC limits ARE set").
- **Report what validated, not only what failed** (e.g. "~150 rail episodes, u_unsat
  hugging the rail, clean releases — the anti-windup is confirmed on hardware").
- **Hedge honestly.** Unconfirmed items are labeled unconfirmed with the leading
  candidate; name the one measurement that would discriminate before proposing a fix.
- **Beware entangled constants.** When several derived quantities are coupled (K_F, m_eff,
  η_dt, gear ratio), a fleet told to fit one of them will confidently misattribute the
  error to it — the ML-round "m_eff ≈ 2.0 kg" conclusion was overruled by the operator and
  the error later proved to be K_F (×1.669). Present entangled alternatives as
  alternatives; let the operator arbitrate which constant moves.

Chat report structure: what the firmware fixed (validated, with numbers) → new failure
modes, each named and mechanised → diagnostic near-misses → unconfirmed items → ranked
recommended next steps split into firmware / model / hardware tracks, with a handoff
question ("run this as the next orchestrated round?").

## Stage 4 — Documentation routing

- Bench events (bus collapse, boost death, new bodge disclosed mid-synthesis) →
  `bench-incident` skill / `docs/boost-bringup-debug.md`, at the moment they surface.
- Campaign results → the relevant record: share-sweep whitepaper
  (`docs/share_sweep_whitepaper/`: edit `make_figs.py`, run it under the venv, edit
  `main.tex`, `pdflatex -interaction=nonstopmode`, grep `main.log` for errors/overfull),
  or the calibration record (`controller_design_MIMO/calibration/motor_id_20260815.md`).
- If the round produced or judged a firmware version: CLAUDE.md status addendum +
  `docs/firmware-versions.md` ledger row.
- Firmware changes the findings demand → hand the spec to the `orchestrated-feature`
  skill as the next round; model-constant changes → `regen-coeffs`. Analysis rounds do
  not edit the `.ino`.
- New log conventions or artifact traps discovered this round → fold into
  `references/log-conventions.md` (one-file edit) and the toolkit memory, so the next
  round's briefs inherit them. If a new BLG format version lands, update the reference
  file's schema section from `decode_benchlog.py` and teach `scout_batch.py` any new
  columns worth scouting.

## Known failure modes this pipeline exists to catch

| Failure mode | Guard | Instance |
|---|---|---|
| Phantom events from ADC noise | hysteresis rule in conventions block | naive dropout counters, share-sweep rounds |
| Governor action scored as tracking error | raw-vs-effective setpoint caveat + reconstruction | share_sp clip, fw v3–v6 rounds |
| Hz/settling numbers off by ~15% | actual-rate (~862–875 Hz) note | nominal-1 kHz assumption |
| Wrong axis units on described plots | "CSV or explicit units" rule | Serial Plotter sample-count axis → 36× error |
| Ill-conditioned ratios near zero | `I_tot > 0.3 A` gating | share_act blowups; `r_cmd` div-by-zero (gFC=gBT=0) |
| Cross-fw trace incomparability | fw provenance line per log in every brief | v11 vs v12 control-law change |
| Entangled-constant misattribution | present alternatives, operator arbitrates | m_eff-vs-K_F, resolved fw v14 |
| Orchestrator brief errors | verify constants against source; "verify, don't trust this reasoning" | live self-correction, fw v4 round |
| Stale hardware constants in briefs | ask about bodges; check bodge records | 4.7 kΩ vs fitted 2.2 kΩ pull-up |
| "Fault never fired" read as validated | mechanism-audit forced verdicts | fw v6 cross-cut audit |
| Missing trailer misread | infer error_code from last records, flag as inferred | truncated (MCU-stop) logs |
