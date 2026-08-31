# HIL result conventions — the anti-artifact block for agent briefs

Single source of truth for facts every HIL-analysis agent brief depends on. Paste the
items the specific round needs; tell agents to Read this file for the rest. The tooling
(`tools/run_hil_suite.py`, `tools/hil_plant_sim.py`, `tools/hil_replay_suite.py`) is the
authority over this file if they disagree — update this file when they diverge.

## Report-folder layout (`HIL Results/hil_report_<ts>/`)

- `plan.json` — `{out, teensy_ip, port, runs[]}`; `runs[].name` lists the planned
  scenarios + replay log ids. Written at suite start; the authority on what was planned
  (a scenario absent here was excluded by the operator, not lost).
- `results.json` — rewritten after EVERY run (Ctrl-C keeps completed runs).
  `meta.partial == false` marks suite completion. Per-run records carry `kind`
  (scenario/replay), `passed`, `skipped`, `inconclusive`, `checks[]` (name/passed/detail),
  `metrics` (incl. `fault_bits_seen`, `fault_bits_post_grace`, `fault_first_t` keyed by
  fault NAME, `n_obs_post_grace`, `last_obs_t`), `notes`. Read verdicts from
  results.json, not REPORT.md — the MD is a rendering.
- Per run: `hil_scenario_<name>_<mode>.csv` / `hil_replay_<LOG>.csv` (1 kHz rows),
  `<csv>.meta.json` sidecar, `<csv>.events.jsonl` (hifi only), `run_<kind>_<name>.log`.
- `REPORT.md` — human rendering; under `--dashboard` the rate gate is SKIPPED-and-labeled.

## Sidecar (`<csv>.meta.json`)

Written TWICE: at start with `results: null` ("running"), finalized atomically at exit
(completed/interrupted/error). **A watcher must be finalization-aware — the file EXISTS
before the run ends and is rewritten in place.** Fields: scenario, argv, resolved config
(incl. `chg_i_ceiling_a`, `replay_preamble_s`, `replay_i_fc_clamp_a`), model-constants
sha256 fingerprint, git rev+dirty, results (warm_resets_observed / warm_resets_mid_run /
warm_reset_times_s, tx/rx frames, send_errors, achieved_hz, final_state,
final_fault_flags). The constants fingerprint moves whenever stimulus constants change —
hash-different does not strictly imply model-different; check the commit.

## CSV reading discipline

- Interpreter: `.venv_hil\Scripts\python.exe` (stdlib only — NO numpy/pandas). Stream
  row-by-row with `csv.DictReader`; CSVs run 1–95 MB — never Read them directly.
- Observation columns (`state`, `switch`, `aux`, `fault_flags`, `current`, `mdac_*`) are
  BLANK on ticks before the first observation frame. Parse with `int(x, 0)` (decimal or
  0x-prefixed both occur).
- `seq` is uint8 — wrap-aware gap detection (mod 256, NOT mod 65536; 255→0 is normal).
- `mdac_fc`/`mdac_bt` carry the 0x1000 LOAD_UPDATE command nibble: 5316 = 0x1000|1220 →
  gain 1220/4095 = 0.298. Mask before reading the code.
- Switch/aux bit definitions: read the SW_*/AUX_* constants from the tools — never guess.
  Reference values seen in campaigns: 0x27 = FC_BUS|BT_BUS|MOT_PWR|BT_SEQ (normal Idle/Run),
  0x2F adds REGEN, 0x35/0x39 during bring-up phases, 0x20/0x28/0x34 teardown phases.
- `elec_substep_hz` is the hifi solver rate (healthy ≈ 55–80 kHz; single-tick dips to
  ~2–10 kHz on host descheduling are normal; the convergence bound is ~8 kHz).
- Replay CSVs: `replay_rec` is -1 during the synthetic preamble (2.5 s,
  `REPLAY_PREAMBLE_S`), 0.. afterward; timestamps are sim-relative (log time = sim −
  preamble), EXCEPT `skip_preamble` entries (ML0217) which are unshifted.

## Fault/scoring semantics (fw v22+ / tooling commit 7802466+)

- `triggerFault()` always ORs FAULT_ERROR 0x8000; a bare latch is observed as
  0x8010-family, never 0x0010 alone. Fault bit values: read FAULT_NAMES in
  hil_replay_suite.py (OC_FC 0x0001, UV_BATT 0x0002, UV_BUS 0x0100, PI_TIMEOUT/HIL_LINK
  0x0010, INIT_FAIL 0x2000-family → observed 0xA000 — VERIFY from source, do not trust
  this list).
- **Carried-in signature (systematic):** every run after the first opens latched with
  `carried == predecessor_final_fault_flags | 0x0010` (the inter-run settle gap latches
  the link-stale bit on top of whatever the predecessor ended with). The fw v22/v23
  recovery warm-resets it at t ≈ 0.500 s (HIL_RECOVER_DEBOUNCE_MS after the run's frames
  start). Predecessor-clean → 0x8010; predecessor OC → 0x8011; predecessor INIT_FAIL →
  0xA010; etc.
- **Grace scoring:** fault checks judge the POST-GRACE union (t ≥ WARM_RESET_GRACE_S =
  2.0 s, inclusive at the boundary); carried-in bits (pre-grace-only) are excused and
  named in check details. Self-guarding: a board still latched shows its bits post-grace.
  A fault that fires in-grace and LATCHES persists post-grace (detectFaults freezes in
  State 99) and still fails.
- `fault_flags` publishes TRANSIENT indications (e.g. UV dwell accumulation) before a
  latch; the LATCH is bit ∧ FAULT_ERROR (or state == 99). Transient pulses can precede
  the true latch by 100s of ms — never report the first bare-bit sample as the latch time.
- Mid-run warm resets (mainState 99→non-99 after the 2.0 s grace) mark a run INCONCLUSIVE
  unless the scenario declares `warm_resets_expected` (comm-loss = 1). The sidecar's
  counts are the authority.
- FAULT_EXPECTATIONS (run_hil_suite.py) is declarative: require / allow_only /
  not_before_s / survive_to / events_require / signals_require, each entry with a source
  citation. Replay entries carry declarative checks in REPLAY_SUITE; `docs/HIL_REPLAY_LOGS.md`
  is the maintained ledger.
- Replay-half purpose is TWO CLASSES since 2026-08-30 — check which one a run is before
  reading its current-shape checks:
  - **Opt-in (`replay_commands`)**: the log's own recorded `v_sp`/`share_sp` are replayed
    as 22-byte Pi command packets at 50 Hz (`--replay-commands`), so the board DOES reach
    State 2 and both loops step. Its current-shape checks judge the live controller's
    reaction, and a `drive_loop_stepped` check asserts the loop actually moved. 14 of 26
    entries.
  - **Non-opt-in**: no commander is constructed, `current ≡ 0`, no State 2. Current-shape
    checks assert only "the firmware did not drive on an uncommanded stimulus".
  **Discriminators, in order of reliability:** the per-run `replay_commands` boolean in
  `results.json`; `"(commands replayed)"` in that run's `key_metrics`; and a check detail
  beginning `NOT EXERCISED (no command replay)` (the sharpened form of the older trailing
  "(vacuous — no commander)" tag, which now survives only for an opt-in entry whose command
  came back flat). `key_metrics`' non-evidence reason is three-way: "no command replay" /
  "commands replayed, loop never stepped" / "no commander".
  ⚠️ Command replay does NOT close the loop — the injected `v_actual` never responds to what
  the firmware commands. An opt-in run is a REACTION test, and the drive loop is EXPECTED to
  fight the recorded trajectory where the recorded and flashed laws differ. Do not report
  that divergence as a board finding.

## Known model-fidelity boundaries (do not report as board findings)

- The plant floors regen power at zero — I_charge during braking windows is
  boost-sourced; SOC falling during "charging" is the tell. Path validation only.
- The hifi engine implements the DESIGN droop chain (fitted 0.316 Ω shared / 0.633 Ω
  single, ratio exactly 2.000) — ~4× the bench-measured K_DROOP_BUS 0.074/0.16 V/A.
  Hifi sag depths are conservative and NOT comparable to bench logs.
- sw_ring events are analytic-only (never stamped into the node solution); the firmware
  cannot see them. over_absmax=True is the Death-5 signature; sub-absmax rings above
  LIMIT_V_BUS_MAX are recorded but informational.
- Under HIL_SIM, pollAg105() is mirrored by fiat — I2C config writes are NOT exercised;
  Ag105 lazy re-config claims need real hardware.
- The Ag105 charger input-draw stamping and MPPT input-power limiting have known gaps —
  check HIL_PLANT.md's current state before treating FC-draw magnitudes as physical.

## Live-suite discipline

- While the suite runs in the operator's terminal: the report folder is READ-ONLY (no
  writes, renames, locks); NEVER run the suite or simulator yourself; and **tools/*.py is
  edit-frozen** — suite children import hil_plant_sim.py fresh per run, so a mid-suite
  edit mixes code versions across runs. Queue fixes; apply after `meta.partial: false`.
- Reading a CSV mid-write is safe (append-only) but its tail is partial — a small file
  size mid-run is NOT a truncation finding (a prior campaign false-alarmed on a
  partially-flushed 285 KB read of what finalized at 8.5 MB).
- Finalization-aware watcher pattern (background Bash, one shot per event, re-arm after
  handling; baseline file lists FINALIZED sidecars, not existing files):

```bash
cd "<repo>/HIL Results/hil_report_<ts>" && \
for f in *.meta.json; do grep -q '"results"' "$f" && ! grep -q '"results": *null' "$f" && echo "$f"; done > /tmp/hil_finalized.txt
# then loop: sleep 45; flag any meta.json newly finalized (present + results non-null +
# not in the baseline); append it to the baseline and exit 0 to notify.
# Separate long-poll: exit when results.json contains '"partial": false' (suite complete).
```

## Statistics hygiene

- Recompute everything the suite self-reports that a verdict rests on — the standard is
  "PASS for the right reason", proven by independent bit-exact recomputation of the fault
  unions and timings from the raw CSV.
- Counter/rate math: divide by (t_last − t_first), never t_last (t can be
  session-relative or shifted by the replay preamble).
- Cross-campaign baselines: cite the previous campaign's HIL_FINDINGS.md section numbers
  verbatim in the brief; drift > ~20% in any repeated metric is a finding; sub-1% repeats
  are ALSO a finding (repeatability is evidence).
