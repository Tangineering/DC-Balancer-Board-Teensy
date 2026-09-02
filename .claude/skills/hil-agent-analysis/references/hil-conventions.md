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

**RUN-ERA FIELDS AN ANALYST MUST READ BEFORE ANY CROSS-CAMPAIGN COMPARISON.** Four, not
three. `scenario.eta_chg` (charger era, absent = the 1:1 sentinel), the droop mode from
argv, `constants.*_PRELOAD_A` (the auxiliary preload era) — **and `config.asymmetry`,
`config.asymmetry_dv0_v`, `config.asymmetry_droop_scale_fc`** (converter asymmetry;
`measured`, ΔV₀ 0.013522 V, `droop_scale_fc` 0.9434 since the C1 default).
⚠️ **Campaign `20260901_151156` predates the asymmetry default and its sidecars carry
no `asymmetry` key at all**, so it is on the far side of TWO plant boundaries at once
(charger and asymmetry). **No comparison spanning 151156 is bit-identical, including a
leg that never charges.** Measured signature across that boundary: h2 **+15–16 %** on
every low-current run (steady +10.1, sag +15.9, comm-loss +15.9, soc-depletion +15.9,
v-bus-sense-offset +16.0), only +0.3–11 % on higher-current runs, `scp-inrush` i_cut
6.362275 vs 6.379737 A (−0.27 %), `comm-loss` re-close split 0.3802/0.3381 A about the
old 0.3591 A mean, `soc-depletion` latch +272.6 ms, `ems-sdp` +0.61 % on a commanded
share that is bit-identical over 61 000 rows.

## CSV reading discipline

- Interpreter: `.venv_hil\Scripts\python.exe` (stdlib only — NO numpy/pandas). Stream
  row-by-row with `csv.DictReader`; CSVs run 1–95 MB — never Read them directly.
- Observation columns (`state`, `switch`, `aux`, `fault_flags`, `current`, `mdac_*`,
  `mppt_thresh_cnt` [fw v24+], `error_code` [fw v25+]) are BLANK on ticks before the
  first observation frame — `mppt_thresh_cnt`/`error_code` are ALSO blank on any run
  against a pre-v24/pre-v25 frame (the field does not exist on the wire yet), which
  reads identically to "no frame received yet"; check the frame-length provenance line
  before treating a blank column as staleness. Parse with `int(x, 0)` (decimal or
  0x-prefixed both occur).
- `seq` is uint8 — wrap-aware gap detection (mod 256, NOT mod 65536; 255→0 is normal).
- `mdac_fc`/`mdac_bt` carry the 0x1000 LOAD_UPDATE command nibble: 5316 = 0x1000|1220 →
  gain 1220/4095 = 0.298. Mask before reading the code.
- Switch/aux bit definitions: read the SW_*/AUX_* constants from the tools — never guess.
  Reference values seen in campaigns: 0x27 = FC_BUS|BT_BUS|MOT_PWR|BT_SEQ (normal Idle/Run),
  0x2F adds REGEN, 0x35/0x39 during bring-up phases, 0x20/0x28/0x34 teardown phases.
- Masked signal specs (`exclude_when_switch_bit`, + `exclude_hold_ms`, 2026-09-02) drop
  rows on which a named switch bit is set, and for `exclude_hold_ms` milliseconds after
  it last was — the gated current decays after the command edge (~10 ms on the FC charge
  path), so the first charge-free samples are contaminated. **A row whose `switch` cell
  is BLANK or unparseable is dropped too**: the mask cannot be evaluated there, and
  keeping the row would assert the bit was clear. So a masked check reads NOTHING over a
  pre-observation stretch, and a run with no observation frames measures nothing and
  fails as "unmeasured" rather than passing vacuously. When you reproduce a masked
  check's number by hand, apply the same two drops or you will not get the suite's value.
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
- **PI_TIMEOUT vs HIL_LINK discrimination:** both share fault bit 0x0010, so a bare
  0x8010 union was wire-ambiguous on fw ≤ 24. **From fw v25, `error_code_final` is on
  the wire** (observation-frame offset 16 — see the observation-column list below) and
  is the authority: `ERR_PI_TIMEOUT` (0x05) vs `ERR_HIL_STALE` (0x10) settle it
  directly. ⚠️ **`error_code` names the PREDECESSOR'S cause during the carried-in
  window.** The board opens a run still latched from the previous run, and the latched
  `error_code` it reports until the fw v22/v23 recovery clears it at t ≈ 0.500 s belongs
  to that predecessor, not to this run's stimulus. Read `error_code` for attribution only
  after the carried-in latch has cleared, exactly as fault bits are read post-grace.
  On a pre-v25 board (no such byte present), fall back to stream-health
  *inference* (child tx continuity, send-error count) — the fallback the `--pi-live`
  excusal and `child_tx_healthy` check use.
- **Carried-in signature (systematic):** every run after the first opens latched with
  `carried == predecessor_final_fault_flags | 0x0010` (the inter-run settle gap latches
  the link-stale bit on top of whatever the predecessor ended with) — this anchor is
  `CARRIED_IN_LATCH_MAX_S` in the tooling. The fw v22/v23 recovery warm-resets it at
  t ≈ 0.500 s (HIL_RECOVER_DEBOUNCE_MS after the run's frames start). Predecessor-clean
  → 0x8010; predecessor OC → 0x8011; predecessor INIT_FAIL → 0xA010; etc.
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
- **comm-loss warm `MOT_PWR` re-close current — RE-BASELINED 0.3696 → 0.3591 A/ch**
  (campaign 20260901_151156). The 0.3696 A/ch figure was bit-exact across eight campaigns
  up to and including 20260901_080905; the WP-C regen-fidelity plant model (fw v25 round)
  moved the V-MOT node's energy accounting, and 0.3591 A/ch is the first reading after it.
  Treat 0.3591 as the current baseline and 0.3696 as the pre-WP-C one — quoting a run
  against the wrong era reads as a −2.8 % board drift that is not there. ⚠️ ONE reading;
  the second fw v25 campaign settles whether it is the new bit-exact value or a spread.
  Not pinned by any check — this is a ledger convention, not a threshold.
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

- **Regen is modelled end-to-end** since the regen-fidelity round (WP-C, shipped
  2026-09-01) — the zero-regen-power floor this section used to describe is gone, and
  "SOC falling during charging" is no longer a fidelity tell by itself. The surviving
  gap is the **uncharacterized VESC regen commanded-vs-delivered mapping**
  (`VESC_REGEN_I_MAX_A` / `ETA_REGEN` — see `WORK_QUEUE.md` §3), which is conservative
  on both axes; do not read a regen-bearing run against any baseline at or before
  campaign `hil_report_20260901_080905` (pre-dates the regen model).
- The hifi engine's DEFAULT droop chain implements the DESIGN values (fitted 0.316 Ω
  shared / 0.633 Ω single, ratio exactly 2.000) — ~4× the bench-measured K_DROOP_BUS
  0.074/0.16 V/A. **A `--droop measured` mode now exists** (anchor 0.16 Ω, +8.1% shared
  residual, ratio 2.182 vs the design's 2.000) — **agents must read the run's droop
  mode from its argv/sidecar before judging sag comparability**; the ~4× design-vs-bench
  finding is NOT closed just because the measured mode exists (it is opt-in, not
  default). Hifi sag depths under the DEFAULT (design) droop chain remain conservative
  and NOT comparable to bench logs.
- sw_ring events are analytic-only (never stamped into the node solution); the firmware
  cannot see them. over_absmax=True is the Death-5 signature; sub-absmax rings above
  LIMIT_V_BUS_MAX are recorded but informational.
- **`sw_ring.i_cut` is a DECISIVE observable, not colour** (F5, campaign 080905). It is
  the current the switch was carrying at the instant it opened, and it is what turned an
  ems-sdp-braking OC_BT from "a fault happened" into a located firmware defect in one
  reading. Read it on every sw_ring before reasoning about a bus event.
- **HAZARD SIGNATURE — `reason: en_low` on `FC_BUS`/`BT_BUS` with `i_cut` > 0.5 A**
  (SHARE_CUT_MAX_HANDOFF_A). That is a share cut opening a CONDUCTING source. On fw ≤ 24
  it is the known defect (campaign 080905: FC_BUS cut at 0.6371 A, 5 ms into BT_BUS's
  ~8 ms RT1987 t_D_ON; V_bus fell 14.56 → 12.40 V in 3 ms and I_batt overshot to 4.64 A).
  On **fw ≥ 25 it must not occur at all** — the r-based cut path gained the 0.5 A load
  guard and both paths gained 30 ms survivor-turn-on blanking — and `run_hil_suite`
  asserts its absence suite-wide as `share_cut_load_hazard`.
  ⚠️ DISCRIMINATE from a State-99 TEARDOWN cut, which legitimately opens a loaded bus
  switch and emits an identical event shape. The event carries no state field, so the
  discrimination is temporal, on a **LEAD WINDOW** — to apply it by hand:

      cutoff = first_own_fault − TEARDOWN_LEAD_MS        (TEARDOWN_LEAD_MS = 5.0 ms)
      event t ≥ cutoff  →  teardown (exclude)
      event t <  cutoff  →  share-path hazard

  where `first_own_fault` is the earliest **whole-run** fault sighting later than
  ~0.10 s. Both refinements are load-bearing:
  - **Not the post-grace map** as the anchor. It is the right scope for judging
    expectations, but a fault that latched inside WARM_RESET_GRACE_S (2.0 s) and
    persisted is reported at the grace bound — scp-inrush's designed OC_FC latches at
    t = 0.717 and the post-grace map says 2.000, 1.28 s late, which drags the cutoff past
    that run's own teardown cuts and false-FAILs them.
  - **Not the raw whole-run map** either: every real run inherits its predecessor's latch
    at ~1.3 ms, which would put the cutoff before everything and exclude the whole run.
  - **Not an exact anchor.** The lead window exists because the solver timestamps a cut
    slightly before the latch it accompanies (the latch comes back over the ~1.9 ms
    observation round-trip). MEASURED SEPARATION, campaigns 20260901_080905 and
    20260901_151156: teardown cuts lead their latch by **0.095–0.541 ms** (the upper end is
    the 151156 measurement, which widened the band from the 0.117 ms first recorded);
    genuine share-path hazards lead by **≥ 13.8 ms**.
    5.0 ms sits ~9× above the widest measured teardown lead and ~2.8× below the smallest
    real hazard.

  A share cut that CAUSED a fault still lands well before its own latch and is caught.
  Residual: a share cut arriving after an UNRELATED fault is still missed.
- **THE STANDING WALK RULE (restated 2026-09-02): an offline walk must model the
  sub-0.55 A OPEN-LOOP HOLD *and* the FEEDFORWARD SLEW.** Open loop is two submodes, not
  one. HOLD applies only when the closed loop has already run this profile, the setpoint
  has not moved by more than `SHARE_SP_CHANGE_EPS` 1e-4, and no isolation is outstanding;
  otherwise the firmware FEEDS THE SETPOINT FORWARD through the slew limiter
  (`DROOP_RATIO_SLEW_PER_TICK` 0.02/tick, or `DROOP_RATIO_SLEW_HANDOFF_PER_TICK`
  0.002/tick on a conduction handoff) and **writes the MDACs**. Measured on
  `ems-y-b00-v3`: 356 open-loop MDAC-write ticks in 8 episodes (campaign
  `20260902_011926`; 369 in `20260901_191509`). A walk that treats all sub-0.55 A
  operation as inert is wrong in the feedforward episodes — the earlier form of this rule,
  which named only the hold, is superseded. `tools/governor_model.py` implements both.
- **The replay half CANNOT SCORE `share_cut_load_hazard` but DOES EXERCISE the firmware's
  cut path.** No `sw_ring` events exist there (no electrical engine is constructed), so
  the check is structurally unreachable and its absence is not coverage — but campaign
  `20260902_011926` counted 163 in-Run FC_BUS/BT_BUS falling edges across six opt-in
  replays, 12 of them with a CSV-bounded |I| over 0.5 A (max 0.6608 A). Do not call those
  a guard failure: at the 1.9 ms round-trip and ~0.08 A tick noise, with currents climbing
  through the threshold, that is the decision the guard is specified to make.
- Under HIL_SIM, pollAg105() is mirrored by fiat — I2C config writes are NOT exercised;
  Ag105 lazy re-config claims need real hardware.
- **THE MPPT-THRESHOLD MIRROR BOUNDARY** (fw v24+). The HIL mirror computes
  `mppt_thresh_cnt` from the clamp arithmetic and publishes it on observation-frame byte
  15, bypassing the real write path entirely. What an HIL run VALIDATES: the arithmetic,
  the clamp band [15, 27], and the frame plumbing. What it does NOT touch: the write
  POLICY, the deadband, the ≤2-per-session ratchet, the ≤8-per-boot EPROM budget, and the
  read-verify-write handshake — **and the REGEN EXCLUSION**. The real manager samples only
  while `fcChargePathIsPowering()` (FC_CHARGE high AND REGEN low) and is NEVER CALLED
  under `HIL_SIM`; the mirror is gated only on `chargerHasPower()`, so it also runs on the
  REGEN path, where regen lifts `V_chg` toward the 18.1 V clamp. Measured on campaign
  `20260902_011926`: inside a braking window (switch 0x2f) the mirror reads 27 at `V_chg`
  18.08 V where the board would hold 15–19; whole-run 11.8 % of ticks differ, by at most
  12 counts (1.056 V). **A cruise tripwire on this count must be windowed clear of the
  braking windows and written as a PEAK-reaching bound, not a floor**; the eta era lifts
  `V_chg` by +0.487 V mean / +0.774 V minimum, but the measured cruise peak is still **19**
  because `AG105_MPPT_N_FLOOR` binds (windowed minimum − 3.0 V = 11.27 V < 12.320 V), so
  the earlier "band shifts up to about 21–22" prediction did not happen.
  So COUNT MOTION IS A MIRROR ARTIFACT — campaign 080905's
  5-step-per-second ratchet is not write-budget evidence and must never be cited as such.
  The count also PERSISTS across the unpowered gaps between charge windows and across
  runs (`hilWarmReset()` preserves `ag105MpptRegCnt`; EPROM preserves the register), so a
  reading present in a run is not evidence that THIS run wrote it — only a change in the
  value within the run is.
- The Ag105 charger input-draw stamping and MPPT input-power limiting have known gaps —
  check HIL_PLANT.md's current state before treating FC-draw magnitudes as physical.

## The charger era, and why h2 does not compare across it (2026-09-02)

- **THE ONE MECHANISM.** The simulated Ag105 was a 1:1 CURRENT-transfer element; since
  2026-09-01 (commit 390f554) it is an energy converter at `ETA_CHG` = 0.88. One rule,
  both engines: `i_in = i_charge·V_pack/(ETA_CHG·V_input)`, `i_out = i_charge` unchanged,
  `p_chg_loss = i_charge·V_pack·(1/ETA_CHG − 1)`.
- **What that does to a charge window,** which is the thing to have in hand before
  reading any charging run:
  - FC-fed (`FC_CHARGE_ENABLE` closed, input = VBUS): the charger's BUS current is now a
    FRACTION of `i_charge`. ⚠️ **That fraction is PROBE-POINT-SPECIFIC, not a constant** —
    it is `V_batt/(ETA_CHG·V_input)`, so it rises as the bus sags. The often-quoted
    **0.5565** belongs to a ~15.9 V bus; at a sagged **14.10 V** bus the measured ratio is
    **0.64** (campaign `20260902_011926`, `ems-soc-band`). Recompute it at the operating
    point before using it; do not carry 0.56 into a sagged window. So `I_fc` inside a
    charge window falls by (1 − that ratio) × the charge ceiling, and the hydrogen billed
    for that window falls with it. Every OC/`I_fc` margin measured inside a charge window
    before 2026-09-02 is stale in the SAFE direction.
  - Regen-fed (`REGEN_ENABLE` + `MOT_PWR_ENABLE`, input = V-MOT): the cap is now
    OUTPUT-referred, so the PACK current roughly DOUBLES (×`ETA_CHG·V_chg/V_pack` ≈ 2.05)
    and the chopper — a residual absorber, not a prior claimant — burns about half as
    much. Measured on the plant probe: chopper 1.3043 J/window vs the 1:1 era's 2.3–2.9,
    `I_charge` peak 0.1469 A vs 0.0677, clamp dwell 1026 ms vs 1148. Energy and dwell
    move by DIFFERENT factors because the clamp is a VOLTAGE clamp: the charger takes
    current, not volts.
  - `V_chg` rises ≈ +0.31 V at 1.4 A (≈ +0.22 V, ~2.5 reg-0x02 counts, at a 1.0 A
    ceiling), and the `mppt_thresh_cnt` band was predicted to shift UP by about two counts.
    ⚠️ **It did not** (measured 2026-09-02): the cruise peak stayed at **19** because
    `AG105_MPPT_N_FLOOR` binds — `V_chg` sags to ≈ 14.45 V under charge, so
    (windowed minimum − 3.0 V) = 11.27 V, below the floor's 12.320 V, over ~85 % of the
    harvest. The effective margin is ≈ 2.13 V, not 3.0 V.
  - PACK current on an FC-fed path is UNCHANGED. Eta moves what the charger COSTS, never
    what the pack RECEIVES at a given ceiling — so no `I_charge` band on an FC-fed
    scenario moved.
- **THE COMPARISON RULE.** Every campaign up to and including `20260901_151156` ran the
  1:1 charger. Do NOT compare `h2_cum_g`, eq-H2, a charge-window `I_fc`, a chopper
  energy or a `mppt_thresh_cnt` band across that boundary. A run's own era is on its
  `.meta.json` sidecar as `scenario.eta_chg`; REPORT.md's header table carries it as
  **Charger era**, and an ABSENT value is the 1:1 sentinel, not "unknown" (no efficiency
  number reproduces that era — it billed the BUS voltage where the model bills the PACK
  voltage). `eta_chg` is also a frontier stimulus key, so a mixed-era frontier is refused
  rather than ranked.
- **A leg that never charges is era-invariant with respect to the CHARGER boundary** —
  that covers `ems-sdp`, `ems-dp-replay`, `ems-ftp75-5050`, `ems-ftp75-sdp`,
  `ems-ftp75-dp` and all 27 replays. ⚠️ **CORRECTED 2026-09-02: that does NOT make it
  bit-identical across campaign `20260901_151156`**, which also predates the converter
  asymmetry default (see the run-era fields above). The **8 ppm `ems-sdp` h2 record is
  BROKEN** across that campaign — by the plant, not by the strategy: commanded share is
  bit-identical over 61 000 rows and h2 still moves +0.61 %, with `I_fc` first diverging
  at t = 0.540314 s (0.0790 → 0.0923 A, the +ΔV₀ FC-bias direction). The 27 replays are
  the surviving exception in the strict sense: their injection fidelity is bit-identical
  on all 27 × 6 channels because the replay half drives the rails from the log and never
  constructs the electrical engine the asymmetry lives in.
- **A charging leg can move UP.** `ems-ftp75-socband`'s walk h2 RISES 3.7526e-2 →
  4.1873e-2 g, because cheaper charging lets the heuristic open a third charge window and
  buy more SoC. "Charging got cheaper so hydrogen fell" is not a safe prior on a leg whose
  SCHEDULE is free to change.

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

## Power-balance columns and figure (2026-09-01f; seventh column 2026-09-02)

- Simulated CSVs written after 2026-09-01f carry append-only tail columns after `error_code`:
  `p_mot_w` (V-MOT node; + drawn, − regen), `p_fc_w` (V_bus·I_fc, bus side — NOT the stack power
  Gfc uses), `p_batt_w` (V_bus·I_batt − V_batt·i_charge; + sourcing, − charging), `p_chop_w`,
  `p_aux_w`, `p_bal_w`. Blank on replay rows.
- **A SEVENTH column, `p_chg_loss_w`, was appended 2026-09-02** with the charger-efficiency
  change: the Ag105 module's own dissipation, `i_charge·V_pack·(1/ETA_CHG − 1)`. It is a
  LOAD-SIDE term, so the residual identity is now

  ```
  p_mot + p_chg_loss = p_fc + p_batt + p_chop + p_bal
  ```

  i.e. `p_bal_w` = p_mot + p_chg_loss − (p_fc + p_batt + p_chop). A CSV with only six power
  columns and no `p_chg_loss_w` is a 1:1-charger-era file, and its `p_bal_w` still has the
  charger term buried in it — the figure detects the absence and annotates the residual panel.
- The identity is exact in simple-mode motoring (aux is the whole residual); in hi-fi the
  residual after aux is ≈ −0.4 W mean while motoring, and the ~11 W charge-window residual the
  1:1 element used to produce is GONE (it was the charger term, to two decimals). Two known
  residual components remain and are documented in HIL_PLANT.md §4.6.2: `p_chop` sits on the
  SOURCE side although it is a dissipation, so a braking residual is dominated by −2·p_chop
  (pre-existing, deliberately deferred); and `p_chg_loss_w` uses this tick's `i_charge` while
  the billing sites use last tick's, so the identity is off by Δi·V_batt·(1/η−1) during the
  0.4 s charger ramp.
- `hil_power_balance.png` renders those; on legacy CSVs (every campaign ≤ 151156) it shows source
  powers only — the `current` column is the VESC PHASE-current command, not bus current, so no
  motor proxy is drawn. Do not read a legacy figure as a balance.
- Files named `walk_*.png` (docs/modeling/sdp_alpha_sweep_20260901/plots/) are OFFLINE GOVERNOR
  WALKS synthesized through the report figure builders, never board runs; a campaign glob must
  match the unprefixed names only.
