#!/usr/bin/env python3
"""
run_hil_suite.py — run EVERY HIL scenario and the whole replay suite against a
flashed board, then package the results into one report directory.

    python3 tools/run_hil_suite.py --teensy-ip 192.168.1.50

This is the wrapper the bench operator runs once; everything under it is already
built:

  * tools/hil_plant_sim.py   — the plant simulator (SCENARIOS registry, replay mode)
  * tools/hil_replay_suite.py — the 26-entry recorded-log suite + its declarative
                                per-entry checks (evaluate_replay_csv)

WHAT THIS SCRIPT ADDS
  1. A run plan over both halves (scenarios, then replays), with --only/--skip.
  2. Child-process execution (NOT in-process main()): every run is a separate
     `sys.executable tools/hil_plant_sim.py ...` with a hard timeout, so a wedged
     run is killable and recorded as TIMEOUT instead of hanging the bench session.
  3. Health checks for the SCENARIO half, which — unlike the replay entries — has
     no declarative checks of its own: observation-frame presence, faults vs the
     declarative FAULT_EXPECTATIONS table (required bits, allow-only masks,
     stimulus-time and survive-to gates, required electrical events), achieved
     rate, hi-fi substep stats, and event counts from the .events.jsonl sidecar.

GRACE-AWARE FAULT SCORING (2026-08-30)
  Every fault judgement — both halves — is made on observations at
  t >= WARM_RESET_GRACE_S (imported from hil_plant_sim, the same bound the
  warm-reset tripwire already used).  From fw v23 the board warm-resets out of the
  previous run's ERR_HIL_STALE settle latch at t ~= 0.5 s, so EVERY run after the
  first opens showing 0x8010 — or 0x8011 / 0xA010 when its predecessor latched
  something of its own — through no fault of its own.  Scoring the whole-run union
  made 23 of 33 FAILs in the first fw v23 pass artefacts of run ORDER.  REPORT.md
  still prints the full union, with the carried-in bits named separately.  The
  rule is self-guarding: a board that STAYS latched shows its bits after the bound
  and still fails.
  4. REPORT.md + results.json in a timestamped report directory, with every
     child's stdout/stderr captured to a per-run .log.

BOARD-STATE ASSUMPTION BETWEEN RUNS
  Each run opens its own UDP socket and the firmware learns its host from the
  FIRST accepted injection frame. Between runs this script sleeps
  --settle-s (default 5 s), which is >> the firmware's HIL_ZERO_MS 250 ms link-loss
  window: the board force-zeros the injected rails, unbinds the host, and latches
  ERR_HIL_STALE, so the next run starts from a known (State 99, latched) board
  rather than from whatever the previous scenario left behind. That latch is
  EXPECTED and is why a per-run "final fault" is judged against the run's own
  stimulus, not against a clean-boot assumption. If you want a clean State-1 board
  for a particular run, power-cycle between runs and pass --settle-s 0.

  fw v23+ ADDS AUTO-RECOVERY, and it has a MINIMUM: the board warm-resets that
  ERR_HIL_STALE latch back to State 0 only after the injection link has been
  continuously dead for >= 1 s, which is what marks a RUN BOUNDARY. A --settle-s
  below SETTLE_MIN_RECOVER_S (1.5 s) is therefore warned about at plan time,
  because the boundary MAY NOT be crossed reliably. Note that the boundary is
  anchored at the board's LAST ACCEPTED FRAME, so the dead window is this pause
  PLUS the previous child's teardown PLUS the next child's startup — the true
  gap is longer than --settle-s by an unmeasured margin, which is exactly why
  the wording is "may not" and not "will not". When it is not crossed, every run
  after the first starts from a board that never recovered and each of those
  results is an artifact of the pause length rather than of the scenario. The
  warning is NOT a floor: --settle-s 0 combined with a power-cycle between runs
  remains the deliberate way to give each run a clean-boot board.

PER-RUN ARTIFACTS
  Each child gets an explicit absolute --csv inside this run's fresh report
  directory, so hil_plant_sim.py's auto-naming and its overwrite refusal never
  apply here. Each CSV also gets a "<csv>.meta.json" sidecar written by the
  child (scenario/mode, resolved config, model-constants hash, git rev, results).

MID-RUN WARM-RESET TRIPWIRE
  From fw v23 the board recovers from its latched State 99 on its own after a run
  boundary. A host stall of >= 1 s mid-run looks exactly like one, so the board
  warm-resets. The damage is NOT "a latched fault silently vanishes" — the union
  and fault_latched checks look at the whole run and would fail loudly on that.
  It is that after the reset the board runs State 0 -> bring-up -> Idle, so the
  REST OF THE RUN IS NOT THE SCENARIO its checks assume: the stimulus timeline
  keeps playing against a board that restarted underneath it, a fault that fires
  again afterwards reads as having fired once (any dwell/timing conclusion from
  it is wrong), and a check keyed to the FINAL state or flags reads the clean
  post-recovery board. Each child counts the mainState transitions out of State
  99 it observed and reports them in its exit summary and its .meta.json
  sidecar; a run with a nonzero MID-RUN count is marked INCONCLUSIVE here, not
  PASS and not FAIL — nothing was disproved, the evidence was destroyed. A run
  that is inconclusive AND had other check failures is labelled as both. The one
  whitelisted scenario is `comm-loss`, whose 2 s gap exists to cross the
  boundary: it REQUIRES exactly one
  (SCENARIOS["comm-loss"]["warm_resets_expected"]); MORE than expected is
  inconclusive there too, FEWER is a plain failure.

EXIT CODES
  0  every run passed
  1  at least one run failed (an INCONCLUSIVE run counts here — re-run it)
  2  the board never answered on the first run (aborted early; --keep-going
     overrides and grinds through the whole plan anyway)
"""

from __future__ import annotations

import argparse
import csv
import datetime
import fnmatch
import json
import os
import platform
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
# Repo-root home for every HIL artifact (report dirs here, hil_plant_sim.py's
# relative --csv paths there too).  Operator-created; created on demand anyway.
HIL_RESULTS_DIR = os.path.join(_REPO, "HIL Results")
sys.path.insert(0, _HERE)

# Firmware constants for the fw v26 source current-ceiling governor. Imported
# from the port, never re-typed: `governor_model.GOV_CONST` is scraped against
# the .ino by tools/test_governor_model.py, so a ceiling retune reaches every
# bound written against it.
import governor_model as gov_mod                                   # noqa: E402
# The MPC's own share band, so the `ems-mpc*` ladder bounds below are DERIVED
# from the ladder rather than typed beside it (campaign 20260902_220604,
# `signal_mpc_share_floor`). Stdlib-only, like every other import in this file.
import mpc_ems                                                     # noqa: E402

from hil_plant_sim import (                                        # noqa: E402
    SCENARIOS, TEENSY_PORT_DEFAULT, WARM_RESET_GRACE_S, REPLAY_PREAMBLE_S,
    # switch_state bit masks, for FAULT_EXPECTATIONS' signals_require specs.
    # Imported, never re-declared: they mirror the firmware's switch_state packing
    # and a second copy here would be a silent divergence waiting to happen.
    SW_FC_BUS, SW_BT_BUS, SW_REGEN, SW_FC_CHARGE,
    # ErrorCode_t values + renderer (fw v25 observation-frame byte 16).  Imported,
    # never re-declared, for the same reason as the switch masks: the enum is the
    # firmware's and a second copy here would drift.
    ERR_PI_TIMEOUT, ERR_HIL_STALE, error_code_name,
    # aux-byte bit masks, for the `aux_bit` specs.  Same rule as the switch masks:
    # imported, never re-declared (.ino:2823 packs this byte).  The two fw v26
    # ceiling bits are spare bits in the same byte, so HIL_OUTPUT_SIZE stays 18
    # and the checksum span is unchanged.
    AUX_MPPT_DISABLE, AUX_FC_CEILING, AUX_BT_CEILING,
    # The `ems-y-*` profile geometry, so the signal windows below are DERIVED
    # from the same constants the stimulus is (EMS_Y_START_S and the region
    # table), not re-typed. A table edit that moves a region boundary must move
    # these windows, and importing them is what makes that visible.
    EMS_Y_START_S, COMBINED_PROFILE,
    # fw v26 clamp-sweep geometry, imported for the same reason: the
    # region table IS the stimulus, and the checks are generated from it.
    FW26_CLAMP_SWEEP_REGIONS, FW26_CLAMP_SWEEP_REGION_S,
    FW26_CLAMP_SWEEP_PRELOAD_A, FW26_CLAMP_SWEEP_BRIDGE_S, I_AUX_A,
    # fw26-clamp-joint's acceptance bound, imported for the same reason:
    # the stimulus and the check that judges it quote ONE number.
    FW26_CLAMP_JOINT_ACCEPT_PEAK_A,
    # `v-bus-sense-offset` stimulus geometry — imported so the windows below are
    # DERIVED from the same constants the stimulus is, never re-typed. Moving an
    # excursion in the simulator moves the checks that judge it.
    V_BUS_UV_PROBE_1, V_BUS_UV_PROBE_2, V_BUS_UV_PROBE_DEPTH_V,
    # Ag105 Table 6 status values + flag bits, for the `value_mask` specs.
    # Imported from the ONE place they are transcribed from
    # references/Datasheets/Ag105_Table6_I2C_Status_Byte.json.
    AG105_ST_LOW_POWER, AG105_ST_FULL, AG105_FLAG_MPPT_EN, AG105_FLAG_PWR_TRACK,
    AG105_FLAG_CV,
    # Ag105 reg-0x02 (MPPT threshold) encoding + the firmware's clamp band, for
    # the `mppt_thresh_cnt` column specs (fw v24).  Imported for the same reason
    # the status bits are: hil_plant_sim mirrors them from .ino:1671-1690, and a
    # second transcription here would be a silent divergence.
    AG105_MPPT_N_FLOOR, AG105_MPPT_N_CEIL, AG105_MPPT_N_RESISTOR,
    ag105_mppt_volts,
    # `mppt-tracking` / `share-staircase` stimulus geometry, so the windows below
    # are DERIVED from the same constants the stimulus is.
    EMS_REGEN_BRAKE_WINDOWS, EMS_MPPT_CRUISE_WINDOWS,
    EMS_MPPT_CRUISE_LEAD_IN_S, EMS_MPPT_CRUISE_LEAD_OUT_S,
    # The Ag105 bring-up window (AG105_SETTLE_MS in the .ino), for the
    # mirror-live left edge of the MPPT threshold tripwire's cruise window.
    AG105_SETTLE_S,
    # The emulated Pi's command cadence, for the `strictly_decreases_by` window
    # guard below.  Imported (not re-typed) for the same reason every other
    # stimulus constant here is: moving PI_CMD_HZ must move the guard with it.
    PiCommander,
    # EMS strategy ROLES (2026-09-01).  Imported, never re-declared: the roles
    # are a property of the strategies, and a second copy here would let a
    # demonstration strategy be scored on the frontier after somebody moved the
    # role and not this file.
    EMS_STRATEGY_META, ems_frontier_eligible,
    # WP-E: the droop realization modes, so `--droop`'s choices cannot drift
    # from the engine's.
    DROOP_MODES, DROOP_SCALE, DROOP_MODE_DEFAULT,
    # PART A (C1): the converter-asymmetry modes, imported for the same reason
    # as the droop modes -- `--asymmetry`'s choices cannot drift from the
    # engine's.
    ASYMMETRY_MODES, ASYMMETRY_MODE_DEFAULT,
)
# One emulated-Pi command period.
#
# ── WHAT THE `cmd_*` CSV COLUMNS ACTUALLY ARE (corrected 2026-08-31, ledger
#    fix queue, "contract/doc") ────────────────────────────────────────────────
# They are the 1 kHz ZOH of the commander's INTENDED state at the NOMINAL
# timeline instant — NOT of the last command actually SENT.  PiCommander.tick()
# walks the timeline (`while ... timeline[idx][0] <= t: state.update(...)`) on
# EVERY 1 kHz tick, BEFORE the `t < self.next_tx` send gate returns
# (hil_plant_sim.py, PiCommander.tick), and the CSV row is written from
# `commander.state`.  So the column steps within one 1 ms tick of the timeline
# entry time, while the 22-byte packet carrying that value leaves up to one
# command period (20 ms) later, and its consequence appears in the OBSERVED
# columns a further ~1.9 ms of observation round trip after that.
#
# CONSEQUENCE FOR A LATENCY READER: a switch/current edge measured against a
# `cmd_*` edge INCLUDES the command-arrival phase.  Reading the columns as
# "when the packet left" attributes that phase to zero and under-reports the
# board's own latency budget by up to 20 ms — which is exactly the [0, 20) ms
# spread `share-staircase` and the handoff-sag tracker measure.
PI_CMD_PERIOD_S = 1.0 / PiCommander.PI_CMD_HZ
# GENSTAT occupies bits 0-2 of the Table 6 status byte; the flags are bits 3-7.
# Declared here (not in the sim) because it is a MASK for the value_mask specs,
# not a device constant.
AG105_GENSTAT_MASK = 0x07
# MPPT_EN | PWR_TRACK — the two tracking flags, read as a pair.
AG105_TRACK_MASK = AG105_FLAG_MPPT_EN | AG105_FLAG_PWR_TRACK
# The hi-fi engine's abs-max ring threshold, for the event checks and the report
# banner.  Imported, never re-declared.
from hil_electrical import V_ABSMAX as V_ABSMAX_V              # noqa: E402

# fw v25 share-cut guard constants, transcribed from the firmware.
#   SHARE_CUT_MAX_HANDOFF_A     .ino:2237 — the doomed channel's current ceiling
#                               for a share cut, on BOTH cut paths from fw v25.
#   SHARE_CUT_SURVIVOR_BLANK_MS .ino:3353 — a cut is refused while the SURVIVOR's
#                               bus switch rose less than this long ago
#                               (RT1987 t_D_ON ~8 ms + the 100 nF CSS soft-start
#                               ramp, ~19.8 ms at 16 V, rounded up).
# Used by the suite-wide `share_cut_load_hazard` tripwire in judge_scenario().
SHARE_CUT_MAX_HANDOFF_A = 0.5
SHARE_CUT_SURVIVOR_BLANK_MS = 30

# ── HI-FI SUBSTEP RESOLUTION GATE (2026-09-02, review PLANT-R1-F6) ──────────
# ElectricalSim sizes its substep count from an EWMA of the measured per-substep
# cost, so the node ODE's resolution is a property of THE HOST, not of the
# scenario: a loaded machine silently integrates coarser and the trace never
# said so.  The review measured the consequence and found it small (99.98 %
# agreement at a 50 us step; 2 event-free ticks over 125 us), so this is a
# TRIPWIRE, not a correctness bound — it exists so a run whose electrical
# resolution collapsed is visible rather than inferred.
# 8 substeps at the 1 kHz tick is a 125 us step, 2.5x the DT_SUB_MAX ceiling
# ElectricalSim prefers (50 us / N_SUB_MAX 100 -> 20 per tick at 1 kHz on an
# unloaded host, measured 100 on this rig).
SUBSTEP_N_MIN_GATE = 8

# What makes a sub-gate reading a VERDICT rather than a note (2026-09-02,
# review M1).  The first version of the check failed a whole run on its single
# coarsest tick, which is a verdict about the host's scheduler and not about the
# board: the quantity is wall-clock adaptive, so an OS scheduling hiccup on one
# tick of 310 000 is expected behaviour, and the review that ASKED for the check
# refuted that consequence itself.  A sustained collapse is different — it means
# every sub-millisecond number in the run was integrated coarsely — so the check
# now WARNS on isolated ticks and FAILS only when the sub-gate ticks exceed this
# fraction of the run.  0.1 % is 310 ticks on a 350 s FTP-75 leg and 15 ticks on
# a 15 s scenario; campaign 20260902_041414 measured ZERO sub-gate ticks across
# 20 hi-fi runs (minimum n = 11 against the gate of 8), so the threshold is
# above every observed value rather than fitted to one.
# ⚠️ The only sub-gate reading ever cited — "two ticks at h = 142.9 us" over
# campaign 20260902_011926 (docs/HIL_PLANT.md §2) — was RECONSTRUCTED from
# `elec_substep_hz`, a wall-clock RATE, not read off the count. The direct
# `elec_substep_n` column now contradicts it, so that figure should not be used
# to size this threshold or to argue the gate has ever been approached.
SUBSTEP_COLLAPSE_FRACTION = 0.001

# Teardown-discrimination lead window for the same tripwire.  A State-99
# teardown (safeAllSwitches()) opens a LOADED bus switch and emits the same
# sw_ring shape as a share-path hazard, so the two are separated TEMPORALLY: a
# sw_ring event is attributed to teardown when it lands within
# TEARDOWN_LEAD_MS of (i.e. no earlier than that before) the run's first
# POST-GRACE fault sighting.
#
# DERIVATION, from campaign 20260901_080905's measured events:
#   * teardown cuts lead their own OBSERVED latch by 0.04-0.55 ms only.  The
#     lead is not physical — it is the solver clock reading the switch open
#     before the board's latch comes back over the ~1.9 ms observation
#     round-trip (L), and the CSV timestamps the latch at the tick the
#     observation arrived.  So the lead is bounded by L plus scheduling jitter.
#     BAND WIDENED 2026-09-02 (campaign C item 5): 080905 measured
#     0.095-0.117 ms and a later reading reached 0.541 ms; campaign
#     20260902_041414's four teardown cuts over 0.5 A measured 0.044-0.086 ms.
#     ⚠️ THE EMPIRICAL BAND IS RETIRED (2026-09-03) IN FAVOUR OF THE
#     STRUCTURAL STATEMENT IT WAS APPROXIMATING: the lead is STRICTLY UNDER
#     1 ms, because the event stamps are QUANTIZED TO 1 ms (the 1 kHz CSV
#     tick) and a teardown cut and the latch it precedes are the same tick
#     or adjacent ones. Campaign 20260902_220604 measured 0.500 / 0.513 /
#     0.500 / 0.595 ms, which sits OUTSIDE the 0.04-0.55 ms envelope while
#     being entirely unremarkable under the structural bound -- i.e. the
#     band was fitting quantization noise. Quote '< 1 ms, quantized',
#     never an envelope.
#   * genuine share-path hazards lead their (caused) latch by >= 13.8 ms.
# 5.0 ms sits 5x above the structural 1 ms quantization bound and ~2.8x below
# the smallest genuine hazard lead (13.8 ms) — comfortable on both sides.
# TEARDOWN_LEAD_MS is UNCHANGED and does not move with the re-statement.
#
# WHY THE ANCHOR EXCLUDES CARRIED-IN LATCHES: every real run carries a latch in
# from its predecessor at ~1.3 ms, so an unfiltered whole-run cutoff excludes
# the entire run and the tripwire is vacuous.
TEARDOWN_LEAD_MS = 5.0

# Anchor filter for the same tripwire.  A fault whose FIRST whole-run sighting
# is this early is the predecessor run's latch, inherited through the fw v23
# warm reset — it is present in the run's very first observation (~1.3 ms) and
# cannot be a fault this run caused, because the board must finish its staged
# bring-up (P0-P3, hundreds of ms) before any load exists to fault on.
#
# ⚠️ NOT WARM_RESET_GRACE_S (2.0 s).  The post-grace fault map is the right
# scope for JUDGING expectations, but it is the wrong ANCHOR here: a genuine
# in-grace latch (scp-inrush's designed OC_FC at t = 0.717) is reported by the
# post-grace map at the grace bound, 1.28 s LATE, which would drag the teardown
# cutoff past its own teardown cuts and false-FAIL them.  Anchoring on the
# whole-run map minus the carried-in window reproduces the measured teardown
# leads exactly (0.095 / 0.105 / 0.117 ms across campaign 20260901_080905's
# four teardowns, and 0.044-0.086 ms across campaign 20260902_041414's) where
# the post-grace anchor does not.
CARRIED_IN_LATCH_MAX_S = 0.10

# ═════════════════════════════════════════════════════════════════════════════
# fw v25 EXPECTATION-IMPACT REVIEW — WHICH MEASURED PINS SURVIVE
#
# The guards can only make a cut LATER (blanking) or NOT HAPPEN (load guard), so
# every entry that pins a cut instant or a cut/restore tick count had to be
# re-derived before this round could claim the table still means what it says.
# CONCLUSION: NO PIN MOVES. Each case, with the arithmetic:
#
#   share-staircase (_SS_* below, latency tripwires + Phase-B cut/restore ticks)
#     BLANKING — irrelevant, by two orders of magnitude. Its cuts are 3 s apart
#       (BT cut 33.0 / restore 36.0 / FC cut 39.0 / restore 42.0) against a
#       30 ms window, and each cut's SURVIVOR is the channel that has been HIGH
#       since bring-up, not one just re-commanded: the BT cut at 33.0 survives on
#       FC_BUS (HIGH since ~t=0), and the FC cut at 39.0 survives on BT_BUS,
#       restored at 36.0 — 3000 ms, i.e. 100x the blanking window.
#     LOAD GUARD — no change AT ALL, and not merely satisfied: these cuts go
#       through updateShareSetpointCutoff(), the SETPOINT-LATCH path, which has
#       carried SHARE_CUT_MAX_HANDOFF_A since fw v6. fw v25 added the guard to
#       the r-BASED twin, which this scenario does not use. (It would pass
#       anyway: Phase B runs at STAIRCASE_LOAD_B ~ 0.55 A with the doomed
#       channel at a 0.05 setpoint, ~0.028 A, 18x under the 0.5 A ceiling.)
#     => the four measured latencies (16/15/4/17 ms) and the tick floors stand
#        as measured. NOT marked provisional.
#
#   ems-y-b00-* (_Y_BT_RESTORE_W / _Y_FC_RESTORE_W)
#     Measured BT cut 22.021 / restore 23.503, FC cut 34.311 / restore 36.51.
#     The tightest cut-after-restore spacing is the FC cut at 34.311 against the
#     BT restore at 23.503 = 10.8 s, 360x the blanking window. The b00 variants
#     also run UNLOADED (Y_AUX_LOAD_A is the b30 budget), so the doomed channel
#     is far under the load ceiling. => unaffected.
#
#   ems-sdp-braking
#     This is the scenario the guards were WRITTEN for, and its expectation is
#     already `allow_only: 0`. The fw v25 change makes that expectation
#     REACHABLE rather than changing it — see the note on that entry.
#
# WHAT WOULD CHANGE THIS: a scenario that cuts one bus switch within 30 ms of
# restoring the other, or that cuts with the doomed channel above 0.5 A. Neither
# exists in the table today; a new entry doing either must re-run this review.
# The `share_cut_load_hazard` tripwire in judge_scenario() is the standing
# backstop for the second case.
from hil_replay_suite import (                                      # noqa: E402
    REPLAY_SUITE, FAULT_NAMES, TARGET_FW_VERSION,
    build_sim_argv, evaluate_replay_csv, replay_csv_path, verify_suite_logs,
    entry_preamble_s,
    # Fault bits — imported rather than re-declared so there is ONE table.  Values
    # are cited against teensy_controller.ino:1149-1166 at their definitions there.
    FAULT_OC_FC, FAULT_UV_BATT, FAULT_UV_BUS, FAULT_MOT_HOTPLUG,
    FAULT_PI_TIMEOUT, FAULT_ERROR,
    # .ino:1305 — the firmware's own bus OV limit (V_BUS_NOMINAL + 1.5 = 17.5 V).
    # Used only to decide whether a sub-abs-max ring is still worth reporting.
    LIMIT_V_BUS_MAX_V,
    # .ino:1434 — the firmware's bus UV limit (12.0 V), the threshold the
    # `v-bus-sense-offset` scenario walks the sensed rail across.
    LIMIT_V_BUS_MIN_V,
    # .ino:1425 / :1476 — the two channel overcurrent limits, imported rather
    # than re-typed for the same reason as the bus pair.  `LIMIT_I_FC_MAX_A` is
    # what `_ALPHA_FC_CEIL` is a margin under.
    LIMIT_I_FC_MAX_A,
    # .ino:2237 again — the replay half transcribes it for its own share-cut
    # census (2026-09-02).  Imported here only to ASSERT the two copies agree:
    # one number in two modules, and a campaign whose replay-side census used a
    # different ceiling than its scenario-side `share_cut_load_hazard` tripwire
    # would be reporting two incomparable censuses under one name.  The import
    # runs this way (run_hil_suite -> hil_replay_suite), which is why the
    # transcription lives there and the assertion here.
    SHARE_CUT_MAX_HANDOFF_A as _RS_SHARE_CUT_MAX_HANDOFF_A,
)

assert _RS_SHARE_CUT_MAX_HANDOFF_A == SHARE_CUT_MAX_HANDOFF_A, (
    "hil_replay_suite.SHARE_CUT_MAX_HANDOFF_A (%r) and this module's (%r) "
    "disagree; both transcribe .ino:2237 and must move together."
    % (_RS_SHARE_CUT_MAX_HANDOFF_A, SHARE_CUT_MAX_HANDOFF_A))

SIM_SCRIPT = os.path.join(_HERE, "hil_plant_sim.py")
# L10: named TIMEOUT_GRACE_S, not GRACE_S. It is the slack added to a child's
# expected duration before the wrapper kills it, and has NOTHING to do with
# WARM_RESET_GRACE_S (the fault-scoring grace window imported above). Two unrelated
# "grace" concepts in one module is exactly the confusion this rename removes.
TIMEOUT_GRACE_S = 30.0         # timeout = expected duration + this
DEFAULT_SETTLE_S = 5.0         # >> HIL_ZERO_MS (250 ms); see module docstring
# Shortest settle pause that still marks a RUN BOUNDARY for the fw v23+ HIL
# auto-recovery (the firmware needs the link continuously dead for >= 1 s; 1.5 s
# is that bound plus margin for host jitter).  Warned about, never enforced —
# --settle-s 0 with a power-cycle between runs stays a valid workflow.
SETTLE_MIN_RECOVER_S = 1.5

# ── Long-cycle scenarios, opt-in behind --with-ftp75 ────────────────────────
# The two EPA FTP-75 study-segment scenarios run 350 s each. That is ~11.7 min
# for the pair against a ~34 min default campaign (measured 2026-08-31 after the
# wave-2 scenarios; --list prints the current estimate), so they are gated on RUN TIME
# alone — not on any board, link or coverage concern. build_plan() renders them
# as SKIPPED records with that reason (the operator_required mechanism), so the
# report shows the gap rather than quietly shortening the plan.
#
# A SET, not a name-prefix test: a prefix would silently capture a future
# `ems-ftp75-`-named scenario that was short enough to belong in the default
# campaign, and gating a scenario out of every campaign by accident is exactly
# the kind of coverage loss that leaves no symptom.
# `ems-ftp75-sdp` joined 2026-08-31: same 350 s cycle, same cost argument.
# `ems-ftp75-dp` joined 2026-09-01 (WP-E): same 350 s cycle, same cost
# argument, and it is the drive-cycle frontier's BOUND leg — gating it
# differently from the legs it bounds would produce a frontier that can never
# assemble.
# `ems-ftp75-mpc` joined 2026-09-02: same 350 s cycle, same cost argument, and
# it is the `ftp75-mpc` frontier's CANDIDATE leg — gating it differently from
# the reference and bound it is ranked against would produce a frontier that can
# never assemble, which is the argument that admitted `ems-ftp75-dp`.
FTP75_SCENARIOS = frozenset({"ems-ftp75-5050", "ems-ftp75-socband",
                             "ems-ftp75-sdp", "ems-ftp75-dp",
                             "ems-ftp75-mpc"})

# ── The five COMPRESSED FTP-75 legs, opt-in behind --with-ftp75c ────────────
# A SEPARATE SET AND A SEPARATE FLAG, not an extension of the pair above, for
# two independent reasons.
#   COST, the same argument FTP75_SCENARIOS makes: five 180 s legs are 15.4 min
#   on top of a ~23 min campaign.
#   AND A PLANT CONFIGURATION.  These five run `--drag scaled-air`, a
#   ROAD-LOAD-COMPENSATED plant that CANNOT be replicated on this bench with
#   the single motor now fitted (docs/modeling/
#   ftp75c_regen_cycle_design_20260902.md section 7).  Folding them into
#   --with-ftp75 would make one flag mean "run a longer cycle" AND "run a
#   different plant", and an operator asking for the first would silently get
#   the second.
# A SET, not a name prefix, for the reason spelled out above FTP75_SCENARIOS -
# and here the prefix test would also be WRONG, because `ems-ftp75c-*` starts
# with `ems-ftp75`.
FTP75C_SCENARIOS = frozenset({"ems-ftp75c-5050", "ems-ftp75c-socband",
                              "ems-ftp75c-sdp", "ems-ftp75c-dp",
                              "ems-ftp75c-mpc"})
assert not (FTP75_SCENARIOS & FTP75C_SCENARIOS)

# ── The three SDP alpha-sweep legs, opt-in behind --with-alpha ──────────────
# Same MECHANISM as FTP75_SCENARIOS (a skip record with a reason, so the report
# shows the gap) and a DIFFERENT reason: these three are not long, they are a
# one-off EXPERIMENT.  They replay three points of the eta-era alpha sweep
# (tools/sdp_policies/sweep_20260902_eta088/, one per behaviour leg) on the
# `ems-sdp` stimulus, so a default campaign would spend their runtime measuring
# a question only the alpha round asks.  They belong to campaign D, not to the
# regression campaign.
#
# A SET, not a name prefix, for the reason spelled out above FTP75_SCENARIOS.
ALPHA_SCENARIOS = frozenset({"ems-sdp-alpha-greedy", "ems-sdp-alpha-cal",
                             "ems-sdp-alpha-charge"})

# ── The charger-era provisional qualifier ───────────────────────────────────
# WP-1C (2026-09-02).  Every band below that depends on the charger's BUS DRAW,
# on hydrogen burnt during a charge window, or on the split of braking power
# between the chopper and the Ag105 was re-derived for the ETA_CHG = 0.88
# energy-conserving charger (docs/HIL_PLANT.md §4.6.1-4.6.2, commit 390f554).
# The mechanism, once, so the per-check comments can cite it:
#   * FC-fed charging.  The charger's bus current was `i_charge`; it is now
#     `i_charge * V_pack / (ETA_CHG * V_bus)` = 0.5565 x i_charge at the probe
#     point.  Every I_fc figure measured INSIDE a charge window falls, and the
#     hydrogen billed for that window falls with it.
#   * Regen-fed charging.  The cap is now OUTPUT-referred, so the pack current
#     rises (x ~2.05 at V_chg 18.1 V / V_pack 7.77 V) and the chopper, which is
#     a residual absorber, burns correspondingly less.
#   * Pack current on an FC-fed path is UNCHANGED: eta moves what the charger
#     COSTS, never what the pack RECEIVES at a given ceiling.
# NONE of these bands has been measured on the board under the new plant. The
# first eta-era campaign is the calibration source; delete the note when pinning.
_ETA_ERA_PROVISIONAL = (
    "post-eta charger era (ETA_CHG 0.88, docs/HIL_PLANT.md §4.6.1): this bound "
    "was re-derived offline (governor walk / plant probe / stated arithmetic), "
    "not measured on the board. Campaigns <= 20260901_151156 ran the 1:1 "
    "charger and their numbers are NOT comparable. Re-derive from the first "
    "eta-era campaign that runs this scenario")

# ── The bleed-era provisional qualifier ─────────────────────────────────────
# The DP-bound round (2026-09-02).  `hil_electrical.R_NODE_BLEED` (one 2 kOhm
# value on every node) split into `R_NODE_BLEED_BUS` 30 kOhm and
# `R_NODE_BLEED_OTHER` 60 kOhm, and `hil_plant_sim.R_BUS_BLEED` followed.  That
# is a STATIC LOAD the sources carried on every tick of every run, so unlike
# the charger era it moves EVERY band, on charging and non-charging scenarios
# alike.  See docs/HIL_PLANT.md section 4.8 for the physics and the reversal
# path, and the BLEED-ERA note in the anchors block below for the per-anchor
# predictions.
_BLEED_ERA_PROVISIONAL = (
    "post-bleed era (R_NODE_BLEED_BUS 30 kOhm / R_NODE_BLEED_OTHER 60 kOhm, "
    "docs/HIL_PLANT.md section 4.8): this bound was re-derived offline, not "
    "measured on the board. Campaigns <= 20260902_041414 ran the uniform "
    "2 kOhm bleed and their numbers are NOT comparable. The bleed values are "
    "themselves TODO(calibrate) - the operator's 30-60 s dark-bus decay "
    "recollection - so expect a SECOND move after the bench decay capture; do "
    "not spend a tightening pass here before it")

# ── RUN-ERA FIELDS, the list an analyst reads before any cross-campaign
#    comparison.  FIVE, not four, since 2026-09-02.  Kept HERE as well as in
#    .claude/skills/hil-agent-analysis/references/hil-conventions.md because
#    this is the file whose bands the eras invalidate.
#      1. `scenario.eta_chg`          the charger era; ABSENT is the 1:1
#                                     sentinel, not "unknown"
#      2. `config.droop_mode`         `design` or `measured`; every campaign
#                                     since the flag existed has run `design`,
#                                     and the DP's static-loss map is a
#                                     `design` fit that resolves to NO MAP in
#                                     any other mode
#      3. `constants.*_PRELOAD_A`     the auxiliary preload era
#      4. `config.asymmetry` + its    the converter-asymmetry era
#         `_dv0_v` / `_droop_scale_fc`
#      5. `config` bleed constants    the node-bleed era (2026-09-02); a
#                                     sidecar from the uniform-2 kOhm era
#                                     carries the old values in its
#                                     `constants` block

# ─────────────────────────────────────────────────────────────────────────────
# BLEED-ERA REPEATABILITY ANCHORS (re-pinned 2026-09-03 from campaign
# hil_report_20260902_220604, the FIRST campaign of the era)
#
# The suite's repeatability record is kept in the campaign ledgers, but the
# numbers a future round compares against are read HERE, next to the bounds they
# justify. Every figure below is MEASURED on that campaign, which ran fw v26,
# `R_NODE_BLEED_BUS` 30 kOhm / `R_NODE_BLEED_OTHER` 60 kOhm,
# `hil_plant_sim.R_BUS_BLEED` 30 kOhm, ETA_CHG 0.88, asymmetry `measured`
# (dv0 0.013522 V, droop_scale_fc 0.9434) and `--droop design`.
#
#   scp-inrush      MOT_PWR i_cut 6.360327 A at 0.602 s. ⚠️ BIT-EXACTNESS IS
#                   RETIRED, as the era change predicted: the asymmetry-era
#                   record 6.362274641096594 A held to 16 digits over two
#                   campaigns, and the bleed moved it by -0.031 %. Compare
#                   against a +-0.5 % BAND ([6.328, 6.392] A), not against the
#                   digits. Its own OC_FC latch: 0.715500 s.
#   handoff-sag     cut 0.370455804372 A at 6.019 s (asymmetry era 0.377928765310
#                   at 6.005 s; -1.98 %). Same rule: band, not digits.
#   comm-loss       warm MOT_PWR re-close I_fc 0.1088 A / I_batt 0.0816 A at
#                   7.601060 s, and the PI_TIMEOUT latch is UNMOVED at
#                   5.251066 s. ⚠️ THE INRUSH COLLAPSED -71/-76 % against the
#                   asymmetry era's 0.3801 / 0.3379 A, and the mechanism is the
#                   bleed itself: the 970 uF V-MOT node (470 uF + 0.5 mF VESC)
#                   now RETAINS 95.15 % of its charge across the 2.323 s teardown
#                   (hi-fi tau 1.94 -> 58.20 s; run 002 F2 corrected the earlier
#                   470 uF / 92 % / 28.2 s figures), so
#                   the re-close is a 0.040 A step onto a nearly-full node
#                   rather than a charge-up. The COLD bring-up peak, which
#                   starts from 0 V, moved only -1.5 % (0.4906 vs 0.4983 A) --
#                   which is the control that identifies the mechanism.
#                   ⚠️ REPORT BOTH CHANNELS. They have not been equal since the
#                   asymmetry era; a single "A/ch" figure compares across eras.
#   soc-depletion   UV_BATT latch at 273.593513 s (asymmetry era 270.976079;
#                   +2.6174 s against a PREDICTED +1.5 s, i.e. the latch-shift
#                   model is ~70 % optimistic). Teardown BT_BUS i_cut 2.350718 A.
#   share-staircase FC high step 0.9008 A / redistribution 0.5981 A (asymmetry
#                   era 0.9155 / 0.6128); latencies 6.44 / 10.02 / 18.43 /
#                   5.05 ms, all command-phase jitter and all <= 40 ms.
#   h2 totals       ems-sdp 0.0123897811 g +-50 ppm; ems-dp-replay
#                   0.0114663632 g; ems-soc-band 0.0118423093 g;
#                   ems-ftp75-5050 0.0290697451 g; ems-ftp75-socband
#                   0.0407628763 g.
#   ems-y quartet   b30-v1 0.00764561286 g, b30-v3 0.00908186759,
#                   b00-v1 0.00186021222, b00-v3 0.00315531053, each +-0.5 %.
#                   ⚠️ THE +-800 ppm PIN IS RETIRED ON THIS FAMILY. All four
#                   legs moved -1.17 to -6.12 % across the bleed boundary, and
#                   the fw v26 clamp accounts for 0.054 % of the b30-v3 delta
#                   (5.78e-08 g of -1.076e-04 g) -- i.e. >= 99.9 % of it is the
#                   PLANT. A +-800 ppm band cannot survive an era change and
#                   asserting one again would fail a correct board.
#
# ⚠️ THE SAME-CONFIG h2 REPEATABILITY FLOOR IS ~50 ppm, NOT 8 ppm. The 8 ppm
# figure quoted in the ledgers is a bit-exactness record between two runs of ONE
# artifact, not a noise floor. Three campaigns now bound it: `alpha-cal` against
# `ems-sdp` -- identical policy block, same campaign -- reads 0.79 ppm, 44.5 ppm
# and -23.7 ppm. Do not open a finding on an h2 difference under ~50 ppm, do not
# size a band on the 8 ppm figure, and do not resolve a frontier margin under
# ~0.1 %.
#
# ⚠️ THE ERA'S OWN MOVE, measured against the asymmetry era and matching both
# walk predictions: loaded 61 s legs -1.2 to -2.0 % (predicted -1.7),
# ems-ftp75-5050 -2.88 % (predicted -2.9). LOW-CURRENT runs move ~-8 % (sag
# -7.96, v-bus-sense-offset -8.01, comm-loss -8.54, bringup -8.02,
# soc-depletion -7.86) because the removed static bleed is a larger FRACTION of
# their draw -- the correct direction, and the reason a single era percentage
# must not be applied across scenario classes.
#
# The bleed values are `TODO(calibrate)` -- the operator's recollection, not a
# measurement -- so the first campaign after the bench decay capture
# (`hil_electrical.R_NODE_BLEED_BUS`) will move every anchor above AGAIN. Do not
# spend a tightening pass on these bands until that capture exists.

# ─────────────────────────────────────────────────────────────────────────────
# Which scenarios EXPECT the board to latch a fault.
#
# Sources, per entry (do not extend this table from intuition — cite a source):
#   sag           docs/HIL_MODE.md test H2: "mainState 99 and fault_flags with the
#                 UV bit set, latched" for the -5 V / 1 s dip past LIMIT_V_BUS_MIN.
#   comm-loss     The scenario stops transmitting for 2 s, which is past the
#                 firmware's 250 ms zero stage: CLAUDE.md fw v21 addendum and
#                 docs/HIL_MODE.md "Link-loss behaviour" — ">250 ms force zeros,
#                 unbind the host, and latch FAULT_HIL_LINK / ERR_HIL_STALE".
#                 FAULT_HIL_LINK ALIASES FAULT_PI_TIMEOUT (0x0010).
#   soc-depletion SCENARIOS description (hil_plant_sim.py): V_batt walks down the
#                 OCV curve toward LIMIT_V_BATT_MIN — "the honest UV_BATT path".
#                 Whether it ARRIVES inside the run depends on --soc0/--capacity-ah,
#                 so this one is "allowed", not "required" (see ALLOWED below).
# Everything else is expected fault-free; a fault there is a finding.
# ─────────────────────────────────────────────────────────────────────────────
#
# --pi-live NOTE (verified from source, do not "fix" this):
#   The comm-loss expectation is UNCHANGED under --pi-live.  The HIL stale clock
#   keys on ACCEPTED INJECTION FRAMES ONLY: hilLastFrameMs is stamped in
#   receiveCommands()'s commit block (.ino:4970-4976), which runs only for a
#   40-byte frame that passed hilParseInjectFrame() and the host lock; and
#   updateSensors() ages exactly that stamp (.ino:4379-4431).  A 22-byte Pi
#   command takes the other branch (processPiCommandPacket(), .ino:4835) and
#   touches only last_rx_ms / pi_ever_connected (.ino:4884-4885), which belong to
#   the SEPARATE Pi watchdog (checkPiWatchdog(), .ino:4817-4826).  So a real Pi's
#   command traffic does NOT keep the HIL link alive: when this simulator stops
#   injecting for 1 s, ERR_HIL_STALE latches exactly as it does without a Pi.
# ─────────────────────────────────────────────────────────────────────────────
# FAULT_EXPECTATIONS — one declarative entry per scenario that expects anything
# other than "no fault at all".
#
# REPLACES the old FAULT_REQUIRED / FAULT_ALLOWED pair (2026-08-30).  FAULT_ALLOWED
# was free text and its check ALWAYS passed: it never compared the observed bits
# against anything, so it rubber-stamped three runs whose objectives were never
# reached (HIL_FINDINGS: charge-fault latched OC_FC 14 s before its own stimulus;
# soc-depletion latched OC_FC instead of the promised UV_BATT and sat dark for
# 645 s; handoff-sag latched OC_FC 2.2 ms into its perturbation, 1.05 V above the
# UV floor).  Every field below is CHECKED.
#
# Every fault judgement is made on the POST-GRACE union (see analyze_scenario_csv)
# — bits observed only before WARM_RESET_GRACE_S are the PREVIOUS run's inherited
# settle latch, which fw v23's between-run recovery clears at t ~= 0.5 s.  This is
# self-guarding: a board that STAYS latched keeps showing its bits after the grace
# bound and still fails.
#
# Fields (all optional except `source`):
#   require       bit mask that MUST appear in the post-grace union
#   allow_only    bit mask of everything that MAY appear; any other post-grace bit
#                 fails.  Omitted -> only `require` (plus FAULT_ERROR) may appear.
#   not_before_s  a required bit appearing BEFORE this time did not come from the
#                 stimulus and fails
#   survive_to    {"t": X, "states": {...}} — the board must still be un-latched at
#                 t = X and in one of those mainStates, i.e. it actually reached
#                 its own stimulus
#   events_require  event kinds that must appear in the hi-fi .events.jsonl sidecar
#   events_any_of   a list of GROUPS, each {"name", "branches": [...]}, where a
#                 branch is {"name", "label", "why", "events": [spec, ...]} and is
#                 satisfied when ALL of its event specs pass. The group passes if
#                 ANY branch does, and the check NAMES the winning branch. For a
#                 scenario whose result is decided by a race with two legal
#                 orderings. ⚠️ CURRENTLY UNUSED: its founding (and only) user,
#                 scp-inrush, MIGRATED OFF IT 2026-08-31 when its stimulus was
#                 redesigned to win the race outright, so the mechanism is kept for
#                 future races rather than retired. Any new user must carry the
#                 not-check-laundering argument that entry used to: enumerate
#                 ALTERNATIVE legal outcomes of ONE stimulus, never a strict and a
#                 lenient reading of the same result. Prefer fixing the stimulus.
#   signals_require POSITIVE evidence from the CSV that the objective was actually
#                 reached — a list of specs, see judge_signals()
#   source        citation.  Do not extend this table from intuition.
#
# WHY signals_require EXISTS (review M2).  Every other field here constrains FAULTS,
# i.e. what must NOT happen.  A scenario can satisfy all of them and still do
# nothing at all: charge-regen with no braking window ever entered, charge-fault
# with the charger never actually charging, soc-depletion against a flat SoC.  That
# is the same rubber-stamp class the old FAULT_ALLOWED table produced, arriving
# through a different door — and the scenarios redesigned in this round are exactly
# the ones that could regress into it without a symptom.  A signals_require spec
# asserts a POSITIVE trace fact, so a scenario that quietly stops exercising its own
# objective fails instead of passing.
# ─────────────────────────────────────────────────────────────────────────────
#
# --pi-live NOTE (verified from source, do not "fix" this):
#   The comm-loss expectation is UNCHANGED under --pi-live.  The HIL stale clock
#   keys on ACCEPTED INJECTION FRAMES ONLY: hilLastFrameMs is stamped in
#   receiveCommands()'s commit block (.ino:4970-4976), which runs only for a
#   40-byte frame that passed hilParseInjectFrame() and the host lock; and
#   updateSensors() ages exactly that stamp (.ino:4379-4431).  A 22-byte Pi
#   command takes the other branch (processPiCommandPacket(), .ino:4835) and
#   touches only last_rx_ms / pi_ever_connected (.ino:4884-4885), which belong to
#   the SEPARATE Pi watchdog (checkPiWatchdog(), .ino:4817-4826).  So a real Pi's
#   command traffic does NOT keep the HIL link alive: when this simulator stops
#   injecting for 1 s, ERR_HIL_STALE latches exactly as it does without a Pi.

FAULT_EXPECTATIONS = {
    "sag": {
        # REGEN-TEARDOWN EVENT CLASSIFICATION: SETTLED, 2026-09-01.  Campaign
        # 20260831_222036 raised a LOW against this scenario's State-99 teardown
        # — its electrical-event sidecar classified the teardown as an
        # FC_CHARGE `sw_ring` plus a REGEN `reverse_block`, where the `comm-loss`
        # reference run of the same teardown produced a single REGEN `sw_ring`,
        # and the hypothesis was sub-millisecond timing nondeterminism (the
        # scp-inrush L-race class, on the REGEN-teardown path).  Campaign
        # 20260901_000816 REFUTED it: sag's teardown reproduced the comm-loss
        # reference's four-event pattern BIT-IDENTICALLY to 16 significant
        # digits, 2-for-2.  The residual is ULP-level numeric noise in the
        # solver, not a race, and no check keys on the classification.
        # Reopen only on a THIRD pattern, or on a numeric difference above ULP.
        # ⚠️ WP-C BOUNDARY (2026-09-01): the strict_forward change (regen-fidelity
        # round) is EXPECTED to trigger that reopen condition on the NEXT
        # campaign, for a KNOWN reason — this scenario's State-99 teardown is
        # exactly the "bus collapse with MOT_PWR closed" regime the WP-C ON-stamp
        # fix touches (see HIL_PLANT.md's M1 note: up to 2.30 V of ON-stamp
        # deviation and 2 new reverse_block events in that regime). When the next
        # analysis pass sees the classification move, RE-CLASSIFY IT ONCE and
        # record the new pattern here — do not chase it as if it were a fresh
        # regression; it is the expected, understood consequence of this round.
        "source": "docs/HIL_MODE.md test H2 — 'mainState 99 and fault_flags with "
                  "the UV bit set, latched' for the -5 V / 1 s dip past "
                  "LIMIT_V_BUS_MIN. Measured on hardware at 19.887 ms of dwell vs "
                  "the 20.0 ms design (HIL_FINDINGS 'sag').",
        "require": FAULT_UV_BUS,
        "allow_only": FAULT_UV_BUS | FAULT_ERROR,
        "not_before_s": 5.0,          # the dip starts at t = 5.0 (apply_scenario)
    },
    # ═════════════════════════════════════════════════════════════════════════
    # v-bus-sense-offset — THE UV DWELL THRESHOLD, FROM BOTH SIDES
    #
    # THE OBJECTIVE, and why it needed a scenario of its own. UV_BUS_DWELL_LATCH_MS
    # (.ino:1460) is 20 ms of NET accumulated under-limit dwell, and until now
    # nothing in the suite bounded it from BELOW. `sag` holds the bus under the
    # limit for a full second and latches — which a 5 ms threshold, or no filter
    # at all, would also do. `handoff-sag` carried the objective on paper and
    # could never deliver it: its bus floor is reached on the BT rail behind an
    # OC_BT latch, and the two must-NOT-latch replay entries (TP0178/TP0201) do
    # not cross the limit at all, so they accumulate 0.0 ms and are a VOLTAGE
    # margin, not a dwell one. The filter's defining number was unasserted.
    #
    # WHAT THIS RUN PROVES that a one-sided test cannot: an 8 ms excursion does
    # NOT latch and a 60 ms one DOES, in the same run, on the same board, 3 s
    # apart. Together they bracket the threshold in (8, 60] ms and — more
    # usefully — they falsify BOTH failure directions: a filter that latched too
    # eagerly fails the first assertion, one that never latched fails the second.
    # The bracket still falsifies a 5 ms threshold (a 5 ms filter latches on the
    # first probe) and any no-filter implementation. Probe 1 was 12 ms until
    # 2026-09-01 (B-M2); it was shortened to 8 to widen the margin against a
    # host stall, which the firmware's 50 ms hold-last turns into extra DELIVERED
    # dwell — see V_BUS_UV_PROBE_1 in hil_plant_sim.py and `uv_probe1_cadence`
    # below.
    #
    # STIMULUS: sensed-rail-only, hifi (see the SCENARIOS comment in
    # hil_plant_sim.py for why the mode is the experiment design). -5.0 V takes
    # the measured rail to ~10.9 V, 1.1 V clear of LIMIT_V_BUS_MIN 12.0, so no
    # tick sits on the boundary and the dwell accrues at the full 1 ms/tick.
    #
    # PROVISIONAL: the latch INSTANT is derived (excursion 2 opens at t = 8.000
    # and 20 ms of dwell accrues by ~8.020, with the observation round trip
    # L ~= 1.9 ms on top), not yet measured on this board. `sag`'s measured
    # 19.887 ms vs its 20.0 ms design is the closest datapoint and is what the
    # band below is sized against; calibrate from the first green run.
    "v-bus-sense-offset": {
        "source": (".ino:1460 UV_BUS_DWELL_LATCH_MS 20.0 ms + :1461 "
                   "UV_BUS_DWELL_LEAK 0.05 + :1434 LIMIT_V_BUS_MIN 12.0 V, "
                   "against hil_plant_sim.py's V_BUS_UV_PROBE_* geometry. "
                   "Sizing datapoint: `sag` measured 19.887 ms of dwell vs the "
                   "20.0 ms design (HIL_FINDINGS 'sag'). MOVED HERE from "
                   "handoff-sag, whose bus floor sits behind an OC_BT latch and "
                   "could never exercise the dwell decision."),
        "require": FAULT_UV_BUS,
        "allow_only": FAULT_UV_BUS | FAULT_ERROR,
        # THE FIRST HALF OF THE ASSERTION, and it is carried by `not_before_s`
        # rather than by a signal spec: excursion 1 ends at t = 5.008, and a
        # latch attributable to it could only appear before excursion 2 opens.
        # Anchored at 7.0 — comfortably after excursion 1 and its 240 ms of
        # leak-drain, comfortably before excursion 2 — so a board that latched
        # on 8 ms of dwell FAILS here rather than passing as "it latched".
        "not_before_s": 7.0,
        # ── PART B1 (C1 round, 2026-09-01): DE-PROVISIONALIZED ──────────────
        # Campaign 20260901_151156 measured both arms on this board: probe 1's
        # realized dwell of 8.3 ms did NOT latch against the 20 ms threshold,
        # and probe 2 latched 19.90 ms after its opening edge. The derived band
        # is therefore replaced by the measured one at
        # `uv_latched_on_excursion_2` below, and the `provisional_note` is
        # removed rather than merely reworded.
        "signals_require": [
            # 1. The STIMULUS was actually applied. Without this the entry could
            #    pass on a run whose offset never reached the rail, and the
            #    fault would then be attributed to a sag that did not happen —
            #    the same de-vacuation `v_bus_min_in_band` does on the replay
            #    side. A CEILING on V_bus is the assertion: some sample must sit
            #    below the limit, which `max_value` cannot say... so the floor
            #    is expressed the other way round, on the excursion window only,
            #    where EVERY sample is below it.
            {"name": "uv_stimulus_applied", "column": "V_bus",
             "max_value": LIMIT_V_BUS_MIN_V,
             "t_window": (V_BUS_UV_PROBE_2[0] + 0.002, V_BUS_UV_PROBE_2[1] - 0.002),
             "label": "the sensed V_bus was genuinely below LIMIT_V_BUS_MIN "
                      "%.1f V for the whole of excursion 2 (offset %.1f V takes "
                      "the ~15.9 V rail to ~10.9 V) — the stimulus this entry's "
                      "fault is attributed to"
                      % (LIMIT_V_BUS_MIN_V, V_BUS_UV_PROBE_DEPTH_V)},
            # 1b. THE SUB-THRESHOLD PROBE WAS DELIVERED AS SPECIFIED (B-M2).
            #    De-vacuates `not_before_s`, which is an ABSENCE assertion and
            #    therefore passes for free on a probe that never happened.
            #    WHY A ROW CENSUS IS THE RIGHT INSTRUMENT: the firmware HOLDS
            #    the last injected value for HIL_STALE_MS = 50 ms, so a host
            #    stall inside probe 1 does not pause the stimulus — the board
            #    keeps integrating the sagged rail and the realized dwell is the
            #    probe's WALL-CLOCK length, stall included. Probe 1 is 8 ms
            #    against a 20 ms threshold (12 ms of margin), so a >= 12 ms
            #    stall would latch and render as a firmware regression. The
            #    1 kHz t axis makes the stall directly visible instead: a probe
            #    delivered without a gap contributes 8 rows.
            #    FLOOR 7, NOT 8: one row of slack absorbs the window's own
            #    boundary phase (the probe edges need not align with a tick),
            #    while still failing any stall of ~2 ms or more — an order of
            #    magnitude below the 12 ms that could corrupt the verdict.
            {"name": "uv_probe1_cadence", "min_rows": 7,
             "t_window": V_BUS_UV_PROBE_1,
             "label": "the sub-threshold probe was delivered at full 1 kHz "
                      "cadence (no host stall inside its %d ms window; the "
                      "realized dwell MEASURED 8.3 ms against the 20 ms "
                      "threshold, campaign 20260901_151156), so "
                      "`not_before_s` is judging a probe that actually "
                      "happened"
                      % round((V_BUS_UV_PROBE_1[1] - V_BUS_UV_PROBE_1[0]) * 1000)},
            # 2. ... and the bus RECOVERED between the excursions, which is what
            #    makes them two independent probes rather than one long sag with
            #    a notch in it. The leak needs 8/0.05 = 160 ms of healthy bus to
            #    drain excursion 1; this window is 2.5 s of it.
            {"name": "uv_bus_recovered_between", "column": "V_bus",
             "floor_min_value": LIMIT_V_BUS_MIN_V + 1.0,
             "t_window": (V_BUS_UV_PROBE_1[1] + 0.3, V_BUS_UV_PROBE_2[0] - 0.2),
             "label": "the bus sat clear of the limit for the whole 3 s gap — "
                      "so excursion 2 latched on its OWN 60 ms and not on a "
                      "residue the leaky integrator never drained"},
            # 3. The LATCH, timed. `fault_latch_bit` requires the bit AND
            #    FAULT_ERROR (a transient bare bit is not a latch), at or after
            #    excursion 2 opens.
            #    PART B1 (2026-09-01): the check is now TWO-SIDED. `after_t`
            #    keeps the lower edge at the opening of excursion 2; the
            #    `t_window` adds the upper edge the measurement earned. MEASURED
            #    19.90 ms after that edge (campaign 20260901_151156) against the
            #    20.0 ms design threshold. The +/-6 ms band around the
            #    measurement is stated, not tuned: it is about three times the
            #    ~1.9 ms observation round-trip plus one 1 kHz tick of phase on
            #    each of the injection and observation legs, which are the only
            #    mechanisms that can move the instant on a correct board. A
            #    board needing 30 ms of dwell, or latching on the first sagged
            #    sample, now FAILS instead of passing.
            {"name": "uv_latched_on_excursion_2", "fault_latch_bit": FAULT_UV_BUS,
             "after_t": V_BUS_UV_PROBE_2[0],
             "t_window": (V_BUS_UV_PROBE_2[0] + 0.0139,
                          V_BUS_UV_PROBE_2[0] + 0.0259),
             "label": "FAULT_UV_BUS latched between %.4f and %.4f s: the "
                      "MEASURED 19.90 ms of dwell after excursion 2 opened "
                      "(t = %.3f s), plus or minus 6 ms of round-trip and tick "
                      "phase"
                      % (V_BUS_UV_PROBE_2[0] + 0.0139,
                         V_BUS_UV_PROBE_2[0] + 0.0259, V_BUS_UV_PROBE_2[0])},
        ],
    },
    "comm-loss": {
        "source": "docs/HIL_MODE.md link-loss — 2 s gap > the 250 ms zero stage, "
                  "ERR_HIL_STALE (FAULT_HIL_LINK ALIASES FAULT_PI_TIMEOUT 0x0010). "
                  "Measured latch at 5.251 s vs 5.249 predicted (HIL_FINDINGS "
                  "'comm-loss'). Unchanged under --pi-live — see the note above.",
        "require": FAULT_PI_TIMEOUT,
        "allow_only": FAULT_PI_TIMEOUT | FAULT_ERROR,
        "not_before_s": 5.0,          # transmission stops at t = 5.0
    },
    "charge-cruise": {
        # OPERATOR RULING (b), 2026-08-30: FC-path charging and hard acceleration
        # are mutually incompatible on this hardware BY DESIGN — assertFcChargeEnable()
        # drops BT off the bus (.ino:10046), so a single source carries the whole
        # cruise load plus the charger.  LIMIT_I_FC_MAX stays 1.4 A (ruling (a): it
        # is already slightly above the H-20's theoretical maximum).  The OC_FC
        # latch is therefore the CORRECT validation of that incompatibility, not a
        # failure — and requiring it makes the scenario assert the design boundary
        # instead of merely surviving.
        # ⚠️ CHARGER ERA (WP-1C, 2026-09-02). The LATCH SURVIVES the ETA_CHG
        # change but its TIMING does not, and the source string below is the
        # 1:1-era measurement. Arithmetic: the charger's bus draw falls to
        # 0.5565 x its pack current, so I_fc climbs the same ramp more slowly
        # and crosses LIMIT_I_FC_MAX 1.4 A LATER — the WP-1A physics review put
        # the crossing at ~9.1 s against the measured 8.7221 s (+0.40 s).
        # Nothing numeric in this entry moves: `not_before_s` 8.0 is the
        # charge_goal step and `survive_to` 8.0 is the same instant, so both
        # bracket the later crossing with more margin than before, and the
        # scenario's 15 s duration leaves ~5.9 s past it. What IS at stake is
        # the WHOLE latch: if the eta-era campaign shows I_fc peaking under
        # 1.4 A, this entry's `require` becomes unreachable and the scenario
        # needs a ceiling or a load, not a relaxed expectation. That is the
        # finding to open, not to absorb.
        "provisional_note": _ETA_ERA_PROVISIONAL + " (the LATCH TIME, and "
                            "whether the latch happens at all: predicted "
                            "~9.1 s vs the 1:1-era 8.7221 s)",
        "source": "operator ruling (b) 2026-08-30 + HIL_FINDINGS 'charge-cruise': "
                  "measured OC_FC at t = 8.7221 s, I_fc 1.4065 A on a smooth "
                  "190 ms charger ramp, bus bookkeeping closing to 9 mA — "
                  "1:1-CHARGER ERA; under ETA_CHG 0.88 the predicted crossing "
                  "is ~9.1 s (WP-1A physics review item 7a)",
        # ⚠️ FLAGGED FOR OPERATOR RE-ADJUDICATION (fw v26 tools round,
        # 2026-09-02; docs/fw26_current_ceiling_governor.md section 8.7).
        # THE EXPECTATION IS CORRECT AS WRITTEN AND fw v26 CANNOT CHANGE IT.
        # This scenario reaches the overcurrent condition SINGLE-SOURCE:
        # `assertFcChargeEnable()` holds BT_BUS low for the whole window, so
        # I_fc equals I_tot, the share ratio is pinned at DROOP_R_MIN and there
        # is no second channel to move load onto. The fw v26 current-ceiling
        # clamp is structurally inert here, and it could not help if it were
        # not, because the load has nowhere else to go. What needs a DECISION
        # rather than a fix is the registered INTENT: a scenario whose pass
        # condition is an overcurrent latch now sits beside a mechanism whose
        # whole purpose is to prevent that class of latch elsewhere. The
        # question for the operator is whether `charge-cruise` should keep
        # asserting the design boundary or be re-pointed at a ceiling or a load.
        # This is a decision, not a defect, and nothing here was changed for it.
        "require": FAULT_OC_FC,
        "allow_only": FAULT_OC_FC | FAULT_UV_BUS | FAULT_ERROR,
        # The charge_goal step is at t = 8.0 (SCENARIOS['charge-cruise']). An OC_FC
        # before that did NOT come from the charging ramp and is a different defect.
        "not_before_s": 8.0,
        # ... and it must get there in Run, not by dying during the cruise ramp.
        "survive_to": {"t": 8.0, "states": {2, 3}},
    },
    "charge-regen": {
        # ⚠️ BASELINE ERA (WP-C, 2026-09-01): the regen floor is gone, so this
        # scenario's braking FORCE is now clipped at K_F*VESC_REGEN_I_MAX_A and
        # the charge current inside a braking window is HARVESTED rather than
        # bus-sourced.  Its trace is NOT comparable with campaigns <=
        # 20260831_080905, and one signal floor was re-derived (below).
        # ⚠️ CHOPPER ERA BASELINE (2026-09-02, campaign hil_report_20260902_011926,
        # the first ETA_CHG 0.88 run): this scenario NOW CLAMPS THE CHOPPER,
        # ~0.48 J per window, where the 1:1 era measured 0.0000 J. Nothing here
        # scores it — it is recorded so the next campaign reads a chopper
        # episode on `charge-regen` as the era's baseline and not as a new
        # event. Harvest doubled in the same step: 75.06 / 73.51 / 74.73 mC per
        # window against the 1:1 era's 38.96 / 40.31 / 40.17 (x1.87, the full
        # ETA_CHG * V_chg / V_pack output referral), peak I_charge 0.0785 A.
        "provisional_note": "the WP-C-re-derived charge_current floor is from an "
                            "offline walk, not a campaign; re-derive after the "
                            "first post-WP-C live run. " + _ETA_ERA_PROVISIONAL,
        "source": "hil_plant_sim.py SCENARIOS['charge-regen'] (redesigned "
                  "2026-08-30): charge_goal is asserted ONLY inside a braking "
                  "window, so the charger is fed through REGEN + MOT_PWR and the "
                  "single-source FC_CHARGE path never opens. Per-channel budget "
                  "(0.15 + 1.6)/2 = 0.88 A vs LIMIT_I_FC_MAX 1.4 A.",
        "allow_only": 0,              # expected completely fault-free
        # The braking windows start at t = 14.0; reaching the first one in Run is
        # the whole point (the old design died at 5.585 s, 6.4 s before it).
        "survive_to": {"t": 14.0, "states": {2, 3}},
        # M2 — POSITIVE evidence, because "no fault" is satisfied by a run that
        # simply never brakes. Both of the never-yet-observed regen signals are
        # asserted directly, inside the first braking window:
        #   REGEN_ENABLE set  -> chargingControl() actually took its regen branch
        #                        (.ino:10033), i.e. the commanded current really
        #                        went below -0.1 A. 500 ticks = 0.5 s of the ~2.1 s
        #                        window, a floor well clear of edge effects.
        #   I_charge > 0.5 A  -> the Ag105 was genuinely powered THROUGH that path
        #                        (REGEN + MOT_PWR) and charging, not merely enabled.
        #                        0.5 A is well under the 1.6 A ceiling and well over
        #                        the 0 A an unpowered charger reports.
        "signals_require": [
            {"name": "regen_switch", "switch_bit": SW_REGEN, "min_ticks": 500,
             "t_window": (14.0, 16.1),
             "label": "REGEN_ENABLE asserted during braking window 1"},
            # ⚠️ RE-DERIVED FOR WP-C (2026-09-01), and LOWERED 0.5 -> 0.03 A.
            # Under the old floor this current was BUS-sourced through the closed
            # REGEN + MOT_PWR pair, so it ran up to the 1.6 A ceiling and 0.5 A
            # was a comfortable floor.  It is now HARVESTED, and additionally
            # capped by the power actually available at VCHG-IN.  This scenario's
            # 1.000 m/s^2 command is only 5 % over the coast rate, so the captured
            # force is m*(a_cmd - a_coast) = 3.5*0.047 = 0.16 N and the harvest is
            # ~0.16 * 2.5 * 0.80 = 0.32 W -> ~0.02 A at VCHG-IN.
            # ⚠️ RE-DERIVED FOR THE CHARGER ERA (WP-1C, 2026-09-02) — the FLOOR
            # DOES NOT MOVE, and the reason is that the expectation moved AWAY
            # from it. The cap is now OUTPUT-referred: the column measures pack
            # current, so the same 0.32 W of harvest delivers
            # ETA_CHG * p_regen / V_pack = 0.88 * 0.32 / 7.77 = 0.036 A instead
            # of the input-referred 0.32/18.1 = 0.018 A. The floor is therefore
            # ~83 % of the new expectation where it was ~1.7x it, so it is
            # STRICTLY MORE conservative than when it was written and raising it
            # would be pinning an unmeasured figure. 0.03 A is a
            # PROVISIONAL floor: it still distinguishes "the path carried current"
            # from an unpowered charger's exact 0, which is what this check is
            # for, but it is NOT a harvest figure -- `regen-harvest-true` is the
            # scenario sized for that.  Re-derive after the first post-WP-C run;
            # never widen it to absorb an artifact.
            {"name": "charge_current", "column": "I_charge", "min_value": 0.03,
             "t_window": (14.0, 16.1),
             "label": "I_charge delivered through the REGEN path in window 1 "
                      "(harvested, WP-C-rederived floor)"},
        ],
    },
    # ── WP-C, 2026-09-01 ─────────────────────────────────────────────────────
    # ⚠️ BASELINE ERA. Every regen-path trace recorded in campaign 20260831_080905
    # or earlier was taken while the plant FLOORED regen power at zero. Post-WP-C
    # regen-affected scenarios (MEASURED, reviewer H1, 2026-09-01 — offline walk of
    # every EMS objective + all 27 replay entries against the -1.5 A regen clip):
    #   regen-harvest-true, charge-regen, mppt-tracking,
    #   ems-y-b00-v1, ems-y-b00-v3, ems-y-b30-v1, ems-y-b30-v3
    # (the four ems-y-* runs brake to -12 A for 328-971 ticks past the clip;
    # braking force drops 9.05 N -> 1.13 N, i.e. deceleration is 2.7x less at
    # 3 m/s) are NOT comparable with those campaigns: the braking FORCE is now
    # clipped at K_F * VESC_REGEN_I_MAX_A instead of being applied unclipped, so
    # even the velocity trace differs.
    # ⚠️ `ems-sdp-braking` is explicitly DROPPED from the above list: measured
    # ZERO ticks below the -1.5 A regen clip (its charge windows are FC-fed
    # through FC_CHARGE on the decel plateaus, not regen harvest — see its own
    # HONEST CAPTION in HIL_PLANT.md) — it behaves as a non-regen scenario here.
    # POSITIVE finding (reviewer H1): the rest of the EMS objective set —
    # ems-ftp75-* (all variants), ems-sdp, ems-soc-band, ems-dp-replay,
    # ems-sdp-cross, ems-drive-cycle, soc-depletion, charge-to-full — and all 27
    # replay entries measured 0 ticks past the regen clip, so their H2/SoC
    # totals and the EMS frontier comparison are UNAFFECTED by the WP-C change.
    # For those, and for every other non-regen-affected scenario: the plant's
    # drive direction is byte-identical (the i_cmd >= 0 identity branch is
    # unchanged, pinned by test); see the M1 note further down (and in
    # HIL_PLANT.md) for the precise, bounded exceptions on the hifi ON-state
    # stamp (SOFT->ON handover transients and a State-99 bus-collapse regime).
    # ⚠️ STRUCTURAL REPAIR (fix round, 2026-09-01). The C1 round's PART B2
    # patch spliced on a `signals_require` anchor that matched `charge-regen`'s
    # block first, which merged the two entries and left a SECOND, stale
    # `regen-harvest-true` key further down. A dict literal keeps the LAST
    # value for a repeated key, so the re-derived entry was dead and the suite
    # would have run the retired WP-C offline-walk bands (0.01/0.3 J,
    # I_charge 0.04, V_rgn 17.0) plus their provisional note. Both entries are
    # restored to one apiece here: `charge-regen` verbatim as committed, and
    # `regen-harvest-true` with the measured whole-episode bands. Python cannot
    # guard a repeated key at import -- it is resolved before any assertion
    # could see it -- so the defence is that ONE scenario owns ONE entry, and a
    # test now asserts exactly that over the whole table.
    "regen-harvest-true": {
        "source": "hil_plant_sim.py SCENARIOS['regen-harvest-true'] + "
                  "ems_regen_harvest_hard(). WP-C regen-fidelity scenario: hard "
                  "braking on the VESC regen clip with REGEN + MOT_PWR open, so "
                  "kinetic energy genuinely reaches the chopper and the Ag105.",
        "allow_only": 0,                      # expected completely fault-free
        # The first braking window opens at t = 14.0; reaching it in Run is the
        # whole point (charge-regen's predecessor died 6.4 s before its own).
        "survive_to": {"t": 14.0, "states": {2, 3}},
        # -- PART B2 (C1 round, 2026-09-01): MEASURED BANDS ------------------
        # The provisional WP-C offline-walk bands are retired. Campaign
        # 20260901_151156 ran this scenario on the board and, with the chopper
        # event-coalescing defect fixed (the sidecar used to serialize each
        # episode carrying only its first partial tick), the harvest path
        # measures:
        #   total chopper energy      6.9 - 8.6 J per run, 2.3 - 2.9 J per window
        #   largest single episode    >= 2.3 J (one braking window)
        #   I_charge peak             0.0677 A
        #   charge delivered          33.2 mC per window
        #   V_rgn at the clamp        18.1687 V
        #   clamp dwell               1148 ms per window
        # The walk's 1.298 J/window and ~0.08 A figures are superseded: they
        # were computed against the partial-tick energy the old event stream
        # reported, so they were never comparable with a whole episode.
        #
        # Every band below is the measurement with a stated margin. The floors
        # sit ~30 % under the low end of the observed spread (wide enough that
        # the run-to-run spread the campaign itself showed cannot fail a correct
        # board, narrow enough that a halved harvest does), and the ceilings
        # ~30 % over the high end.
        "events_require": [
            "chopper_clamp",  # at least one episode occurred (bare-kind form)
            # ALL: every coalesced episode cleared a loose sanity floor.
            # ⚠️ F4 (fix round, 2026-09-01) — WHY THIS ONE DOES NOT MOVE. Every
            # other floor on this entry was calibrated against the TRUNCATED
            # events the coalescing defect emitted (each episode carrying only
            # its first 0.25-0.9 ms tick) and is re-derived below from
            # whole-episode magnitudes. This floor is the exception: it is an
            # ALL quantifier over every coalesced episode INCLUDING the short
            # tail ones, and a genuine 5 ms tail episode at the measured
            # ~2.4 W/ms clamp rate carries ~0.012 J. Raising it toward a
            # window-sized figure would fail a correct board on its tail. It is
            # a shape check ("no episode is empty"), not a harvest figure, and
            # 0.01 J is the right order for that whether the stream is
            # truncated or whole.
            {"kind": "chopper_clamp", "field": "energy_j", "min_value": 0.01},
            # ANY (the `max_of` quantifier): at least one episode was a REAL
            # braking window. F4: re-derived from WHOLE-EPISODE magnitudes.
            # Campaign 20260901_151156 measures 2.3 - 2.9 J per window; the
            # 1.0 J floor is 57 % under the low end, so it cannot be cleared by
            # an accumulation of flickers, which is precisely what the SUM form
            # below cannot rule out on its own.
            # ⚠️ The retired 0.3 J figure was NOT a whole-episode number: it was
            # the offline walk's 1.298 J/window scaled down against energies the
            # truncated stream reported, so it was never comparable with either.
            # ⚠️ RE-DERIVED FOR THE CHARGER ERA 1.0 -> 0.65 J (WP-1C,
            # 2026-09-02) on an OFFLINE PLANT PROBE, then RESTORED TO 1.0 J FROM
            # THE BOARD (campaign hil_report_20260902_011926, the first eta-era
            # run of this scenario). THE PROBE UNDER-PREDICTED BY ~1.6x: it
            # measured 1.3043 J per window against the run's MEASURED
            # 1.5810 J max episode / 2.109-2.133 J per window, so the halving it
            # predicted did not materialise on the scenario's own geometry
            # (probe: hi-fi, 1.5 s, v0 3.0 m/s, i_cmd -12 A, chg_i_ceiling_a
            # 1.6; the scenario's braking window is longer and its charger
            # ceiling lower, and the chopper is a RESIDUAL absorber, so the
            # charger displaces less of it than the probe's operating point
            # suggested). 1.0 J is 37 % under the measured max_of and, as
            # before, unreachable by an accumulation of flickers. Do not lower
            # it again on a probe alone.
            # ⚠️ WHAT THIS BOUND ACTUALLY BOUNDS (L6, review 2026-09-02): the
            # LARGEST SINGLE COALESCED EPISODE, not the per-window sum. A
            # braking window is not one episode — the clamp stops and restarts
            # within it, so 20260902_011926's 2.109 J window is 1.5738 +
            # 0.5354 J and its largest episode is 1.5810 J; campaign
            # 20260902_041414 measures 1.5938 J max episode against 6.3578 J
            # total. The per-window figures quoted above are the physics being
            # described; the 1.0 J number is compared against the max EPISODE,
            # which is what `max_of` measures, and its 37 % margin is stated on
            # that basis. Bounding the per-window sum would need an episode
            # grouper the event stream does not carry.
            # ── BLEED-ERA RE-PIN (campaign hil_report_20260902_220604) ───────
            # `R_NODE_BLEED` 2 kOhm -> 30/60 kOhm removed ~18 mA of node load
            # against a ~76 mA charger draw, so the residual clamp no longer
            # drops out mid-window: the run coalesced 3 episodes where campaign
            # 20260902_041414 had 6, and the max EPISODE rose 1.5938 -> 2.6707 J
            # (+67.6 %). THE FLOOR IS UNCHANGED AT 1.0 J and deliberately so:
            # the observed spread is now 1.5938-2.6707 J across two eras, and
            # 1.0 J is 37 % under the LOW end of it, the margin class this bound
            # has always carried. Raising it to the bleed-era measurement would
            # pin one era's episode coalescing into a cross-era bound.
            {"max_of": "chopper_clamp", "field": "energy_j", "min_value": 1.0},
            # SUM: the run's whole harvest. Measured 6.9 - 8.6 J; floor 3.0 J,
            # 57 % under the low end for the same reason. F4: also a
            # whole-episode figure, and it replaces a 0.3 J total that a single
            # truncated episode could satisfy.
            # ⚠️ RE-DERIVED FOR THE CHARGER ERA 3.0 -> 1.9 J (WP-1C,
            # 2026-09-02) on the same probe, then RESTORED TO 3.0 J FROM THE
            # BOARD alongside the `max_of` bound above: campaign
            # hil_report_20260902_011926 measured 6.3525 J over the run
            # (2.109 + 2.110 + 2.133 J per window) against the probe's ~3.9 J
            # prediction — the same ~1.6x under-prediction. 3.0 J is 53 % under
            # the measurement, the margin class this bound has always carried.
            # Unlike the `max_of` arm this one IS a per-window quantity summed:
            # it totals every episode in the run, so the window split above does
            # not affect it (campaign 20260902_041414: 6.3578 J).
            # ── BLEED-ERA RE-PIN (campaign hil_report_20260902_220604): 7.9741 J
            # over the run, +25.4 % on campaign 20260902_041414's 6.3578 J, for
            # the mechanism recorded on the `max_of` arm above. The 3.0 J floor
            # is UNCHANGED: it is 53 % under the low end of the 6.3525-7.9741 J
            # spread that three campaigns now describe.
            {"total_of": "chopper_clamp", "field": "energy_j", "min_value": 3.0},
        ],
        # ⚠️ CHARGER ERA (WP-1C): the two chopper-energy bounds above are
        # re-derived from an offline plant probe, not from a board run, and
        # the three signal bounds below are 1:1-era MEASUREMENTS re-checked
        # against that probe rather than re-derived (each says how). The first
        # eta-era campaign is the calibration source for all five.
        # ⚠️ THE `sw_ring` VERDICT AND THE CLAMP THIS SCENARIO REQUIRES ARE IN
        # STRUCTURAL CONFLICT BY 50 mV, and the conflict is recorded here rather
        # than papered over.  `Rt1987._open()` adds a FIXED 1.95 V load-dump ring
        # allowance to the node at every cut above 50 mA, so its implied node
        # ceiling is `V_ABSMAX - 1.95` = 18.050 V — 50 mV BELOW the
        # forward-conduction state of the chopper clamp
        # (`V_CHOPPER_TRIP - RT_V_FWD` = 18.065 V) that
        # `signal_regen_clamp_dwell` below REQUIRES for >= 800 ticks.  Every
        # commanded REGEN open at the end of a braking window therefore lands on
        # the clamp, and in campaign 20260902_220604 all three (i_cut 0.065 A,
        # v_node 18.0639 V, estimated peak 20.0139 V) raised `over_absmax` on a
        # correct board — over by 13.9 mV, against a PHYSICAL ring of 0.80 mV.
        # The verdict is now gated on the load-dump class
        # (`hil_electrical.SW_RING_LOAD_DUMP_I_A` = the firmware's own
        # `SHARE_CUT_MAX_HANDOFF_A` 0.5 A); the events and their `peak_v` are
        # still emitted.  V_ABSMAX is NOT relaxed.  Physics review run 002 (F5):
        # the i*sqrt(L/C) node ring is the WRONG loop for the recorded mechanism
        # (the boost output-cap hot loop, boost-bringup-debug.md:1572-1573); the
        # defensible current-scaled form is peak = v_node + 0.130 V/A * i_cut
        # (1.95 V / 15 A), verdict-invariant over every recorded event, and the
        # 0.5 A load-dump gate stands.
        "provisional_note": _ETA_ERA_PROVISIONAL + " (the two chopper-energy "
                            "bounds are re-derived; the I_charge, V_rgn and "
                            "clamp-dwell bounds are unchanged 1:1-era "
                            "measurements that the probe confirms are still "
                            "cleared)",
        "signals_require": [
            {"name": "regen_switch", "switch_bit": SW_REGEN, "min_ticks": 500,
             "t_window": (14.0, 15.5),
             "label": "REGEN_ENABLE asserted during braking window 1"},
            # PART B2: MEASURED (campaign 20260901_151156) at a 0.0677 A peak.
            # Floor 0.045 A is 34 % under it.
            # ⚠️ CHARGER ERA (WP-1C, 2026-09-02) — UNCHANGED, AND MORE
            # CONSERVATIVE THAN WHEN WRITTEN. The regen cap became
            # output-referred, so the SAME braking window now delivers roughly
            # twice the pack current: the plant probe measures a 0.1469 A peak
            # against the 1:1 era's 0.0677 A (x2.17, close to the
            # ETA_CHG*V_chg/V_pack = 0.88*18.1/7.77 = 2.05 arithmetic). The
            # floor is therefore 69 % under the new expectation where it was
            # 34 % under the old one. Raising it would pin an unmeasured
            # figure; the first eta-era campaign is where it gets re-pinned.
            {"name": "regen_harvest", "column": "I_charge", "min_value": 0.045,
             "t_window": (14.0, 15.5),
             "label": "harvested current delivered through REGEN + MOT_PWR "
                      "(kinetic energy, not bus energy: the WP-C objective); "
                      "measured peak 0.0677 A"},
            # PART B2: MEASURED 18.1687 V at the clamp. The floor is raised from
            # 17.0 to 17.9 V -- still 0.27 V under the measurement, and now
            # close enough to the 18.1 V clamp that a node merely drifting up
            # cannot satisfy it.
            {"name": "regen_node_lift", "column": "V_rgn", "min_value": 17.9,
             "t_window": (14.0, 15.5),
             "label": "V-MOT lifted onto the 18.1 V chopper clamp: the bench "
                      "signature (V_rgn 13.3 -> 18.1 V, V_bus unmoved); "
                      "measured 18.1687 V"},
            # PART B2: the clamp DWELL, measured 1148 ms per window. min_ticks
            # is a 1 kHz row count, so 800 ticks is 800 ms -- 30 % under the
            # measurement. This is the check that distinguishes a window that
            # HELD the clamp from one that merely touched it.
            # ⚠️ CHARGER ERA (WP-1C, 2026-09-02) — UNCHANGED, and this is the
            # band that shows why DWELL and ENERGY had to be re-derived
            # SEPARATELY. The clamp is a VOLTAGE clamp: the charger taking
            # twice the current lowers the chopper's residual current, not the
            # node voltage, so the energy halves while the dwell barely moves.
            # The plant probe measures 1026 ms of clamp in a 1500 ms window
            # against the 1:1 era's 1148 ms (-11 %), leaving the 800-tick floor
            # 22 % under the new expectation.
            # ⚠️ BLEED-ERA RE-PIN (campaign hil_report_20260902_220604):
            # MEASURED 1418 ticks against campaign 20260902_041414's 1227
            # (+15.6 %) — the 30/60 kOhm bleed no longer pulls the node off the
            # clamp mid-window, which is the same mechanism that raised the two
            # chopper-energy figures above. The 800-tick floor is UNCHANGED and
            # is now 35 % under the low end of the 1227-1418 spread.
            {"name": "regen_clamp_dwell", "column": "V_rgn", "min_value": 17.9,
             "min_ticks": 800, "t_window": (14.0, 15.5),
             "label": "V-MOT held on the chopper clamp for at least 800 ms of "
                      "braking window 1 (measured 1148 ms in the 1:1 era, "
                      "1227 ticks in campaign 20260902_041414 and 1418 in the "
                      "bleed-era campaign 20260902_220604)"},
        ],
    },
    "charge-fault": {
        # HIL_FINDINGS 'charge-fault': the PASS was a rubber-stamp — the run
        # latched OC_FC at 5.758 s, 14.25 s before its own t = 20 s stimulus, and
        # `fault_allowed` accepted the unrelated latch.  The survive_to gate is the
        # fix: the board must still be alive and in Run when the charger input
        # actually collapses.
        #
        # WHAT HAPPENS AFTER THE COLLAPSE, and why nothing is REQUIRED here:
        # apply_scenario() sets plant.chg_fault at t = 20, so the Ag105 goes dark
        # and reports GENSTAT 000 (Battery Disconnect, 0x00) with I_charge -> 0 —
        # exactly what the firmware's own failed-read path leaves behind.  Reading
        # pollAg105()/detectFaults(): FAULT_I2C_CHARGER is not reachable under
        # HIL_SIM (the I2C transport is skipped entirely and the injected status is
        # mirrored, CLAUDE.md fw v21/HIL addendum), and 0x00 is a NON-error GENSTAT,
        # so FAULT_CHARGER_STAT does not fire either.  The correct firmware
        # response is therefore to drop ag105IsReady(), re-inhibit MPPT and carry
        # on WITHOUT latching.  A clean run is the expected outcome; the check that
        # earns its keep is survive_to plus allow_only.
        #
        # ⚠️ CROSS-CAMPAIGN PIN EXPECTATIONS: everything on this run repeats to
        # sub-0.01 s EXCEPT the post-collapse MPPT_DISABLE release, which is NOT
        # BIT-EXACT BY DESIGN.  Do not open a finding on it.
        #   REPEATABLE (treat a move as real):  GENSTAT collapse at t = 20.0001
        #     (57 us across campaigns), the I_charge ceiling hold at 0.8000 A
        #     exact, the ceiling window to sub-0.01 s.
        #   NOT REPEATABLE (a ~2x spread is the healthy reading): the delay
        #     from the collapse to MPPT_DISABLE going high — MEASURED 20.36 /
        #     26 / 30.16 ms across campaigns 20260830_203006 / 20260831_191509 /
        #     20260831_222036, and 14.86 ms in the first ETA_CHG 0.88 campaign
        #     (20260902_011926). SPREAD 14.9-30.2 ms. The eta-era reading is
        #     BELOW the previously recorded band and is still not a finding:
        #     the charger change alters the V_chg tail slope, which is exactly
        #     the quantity the mechanism note below says the crossing time is a
        #     poor observable of.
        #   MECHANISM: the firmware releases on a V_chg condition, and after the
        #   input collapses V_chg decays onto a near-asymptote settling tail
        #   (~0.1 mV/tick at the crossing). A quantity crossing a threshold at
        #   0.1 mV/tick moves ~10 ms for a 1 uV numerical difference, so the
        #   crossing TIME is a poor observable while the DECISION it reports is
        #   robust. Nothing here scores it; it is recorded so a campaign
        #   analysis reads the spread as the asymptote and not as drift.
        #   If a future check ever needs this instant, the fix is sim-side
        #   (widen the release condition's margin), not a band on the timing.
        "source": "hil_plant_sim.py SCENARIOS['charge-fault'] + apply_scenario() "
                  "(chg_fault at t = 20); HIL_FINDINGS 'charge-fault' for why the "
                  "old permissive check rubber-stamped a dead board",
        "allow_only": 0,
        "survive_to": {"t": 20.0, "states": {2, 3}},
        # M2: surviving to t = 20 is necessary but not sufficient — the charger must
        # actually have been CHARGING before the input collapses, or the collapse
        # tests nothing. Asserted on the window between the charge_goal step (t = 8)
        # and the fault injection (t = 20). 0.5 A is comfortably under the 0.8 A
        # de-rated ceiling and unmistakably above an unpowered charger's 0 A.
        "signals_require": [
            {"name": "charging_established", "column": "I_charge", "min_value": 0.5,
             "t_window": (8.0, 20.0),
             "label": "charging established before the input collapse"},
        ],
    },
    "soc-depletion": {
        # HIL_FINDINGS 'soc-depletion': the old check never compared the observed
        # bit against UV_BATT, so an OC_FC latch at t = 5.001 PASSed while the
        # endurance objective went unreached for the remaining 645 s.
        # NOTE the bit value: FAULT_UV_BATT is 0x0002 (.ino:1150), NOT 0x0400 —
        # 0x0400 is FAULT_OV_CHG.
        "source": "hil_plant_sim.py SCENARIOS['soc-depletion'] — 'V_batt walks "
                  "DOWN the OCV curve toward LIMIT_V_BATT_MIN, the honest UV_BATT "
                  "path'. Whether it ARRIVES inside the run depends on "
                  "--soc0/--capacity-ah, so UV_BATT is ALLOWED, not required; no "
                  "fault at all is a PASS and the endurance value stands.",
        "allow_only": FAULT_UV_BATT | FAULT_ERROR,
        # The load ramp finishes at t = 13 (apply_scenario: 3 s ramp from t = 10);
        # anything before that is a transient, not depletion.
        "survive_to": {"t": 13.0, "states": {2, 3}},
        # M2: the objective is DEPLETION, and "no fault" is satisfied by a run that
        # never drew anything, so a positive trace assertion is required.
        #
        # A1 — REWRITTEN 2026-08-30 (campaign 20260830_214819, HIL_FINDINGS
        # 'soc-depletion').  The old single-arm 0.05 threshold was PHYSICALLY
        # UNREACHABLE at --soc0 0.15, and its budget comment was wrong twice:
        #   * It used the 2.2 A BUS-side load as the coulomb current.  The pack
        #     sits behind the boost, which steps 6.46 -> 14.37 V, so the PACK-SIDE
        #     current is ~2.8x larger.  F4 (2026-08-31): it is a RANGE, not the
        #     single 6.19 A point once quoted here — measured 5.72-6.45 A, mean
        #     6.03 A (round-1 campaign 20260831_000518). It RISES as the pack
        #     drains: the bus load is constant POWER, so a falling V_batt must be
        #     met with more pack current for the same delivered watts.
        #   * It assumed ~870 s of load.  The UV_BATT latch is a STATE condition,
        #     not a time one: OCV(soc) - I*(Rs(soc)+R1) = 6.2 V solves at
        #     soc_latch ~= 0.1130, so the run ENDS there.  From soc0 0.15 the
        #     maximum possible fall is 0.15 - 0.113 = 0.0370 — below the 0.05
        #     threshold no matter how long the run is.
        # At the corrected --soc0 0.20 (see the plan builder) the ceiling is
        # 0.20 - 0.113 = 0.087, i.e. 1.74x the 0.05 threshold, and the latch is
        # expected at ~13 + 0.087*18000/6.03 ~= 273 s on the measured mean pack
        # current.  MEASURED 270.704 s (round-1 campaign 20260831_000518; the
        # ASYMMETRY-ERA reading is 270.976 s, +0.10 %; the BLEED-ERA reading is
        # 273.593513 s, campaign 20260902_220604, +2.6174 s against a predicted
        # +1.5 s — the latch-shift model is ~70 % optimistic) — 0.8 %
        # under the mean-based estimate, and 1.7 % over the older 6.19 A point
        # estimate's ~266 s.  Both estimates are close enough that the 400 s
        # duration is comfortable either way.
        #
        # DISJUNCTIVE because the two proofs FORECLOSE EACH OTHER: a UV_BATT latch
        # ends the run and caps the observable fall, while a run that never latches
        # is the one that can accumulate the fall.  A UV_BATT latch after the ramp
        # transient is the STRONGER evidence of depletion — the pack demonstrably
        # walked all the way to its UV floor — so either satisfies the objective.
        # `after_t` = survive_to.t = 13.0 s, the end of the load ramp; a latch
        # before that would be a transient, not depletion.
        "signals_require": [
            {"name": "soc_depleted",
             "label": "the pack demonstrably depleted under the endurance load",
             "any_of": [
                 {"column": "soc", "strictly_decreases_by": 0.05,
                  "label": "SoC fell >= 0.05"},
                 {"fault_latch_bit": FAULT_UV_BATT, "after_t": 13.0,
                  "label": "UV_BATT latched after the load ramp"},
             ]},
        ],
    },
    "ems-soc-band": {
        # The DP-informed charge-sustaining EMS scenario (2026-08-31).  Its
        # objective is NOT a fault: it is that the `soc-band` policy's three
        # branches actually execute, and that the H2 metric accumulates.  "No
        # fault" alone is satisfied by a run that cruises at 50/50 and never
        # charges — the same rubber-stamp class signals_require exists for — so
        # all four assertions below are POSITIVE.
        #
        # THE --pi-live TRADE-OFF IS FREE HERE.  Every scenario with an entry in
        # this table loses judge_scenario()'s --pi-live PI_TIMEOUT excusal (see
        # the `bringup` entry's note).  This scenario is EMS-driven, so under
        # --pi-live build_plan() renders it SKIPPED outright (the emulated EMS
        # layer IS its whole stimulus, and a real Pi replaces it) — it is never
        # judged in that mode at all, so there is no excusal to forgo.
        # ── THE CHARGE WINDOW SAGS THE BUS, AND THE 0.8 A DE-RATE IS WHAT KEEPS
        #    IT LEGAL (measured, campaign 20260831_191509) ─────────────────────
        # Opening FC_CHARGE takes BT off the bus (assertFcChargeEnable), so the
        # window runs SINGLE-SOURCE, and hi-fi's single-source droop drops V_bus
        # to 13.435 V — 12 % above LIMIT_V_BUS_MIN 12.0 V. That is real margin,
        # but it is not much, and it is the reason the inherited 0.8 A ceiling is
        # LOAD-BEARING rather than cosmetic: the sag scales with the charger
        # current, so restoring the Ag105's 2.5 A capability here would put the
        # rail through the UV limit and latch the scenario. Any future change to
        # `chg_i_ceiling_a` on this scenario must re-derive the sag first.
        #
        # ⚠️ DO NOT READ 13.435 V AS A HARDWARE PREDICTION. The hi-fi engine
        # implements the DESIGN droop chain (0.316/0.633 ohm, ratio exactly
        # 2.000), which is ~4x the MEASURED bench K_DROOP_BUS (0.074 shared /
        # 0.16 single) — the standing open finding recorded at K_DROOP_BUS in
        # hil_plant_sim.py and in every campaign REPORT.md. On the real board the
        # same window would sag roughly a quarter as far. The number above is a
        # WORST-CASE bound within the design chain and is the right one for
        # sizing the ceiling; it is the wrong one for predicting a bench trace,
        # and sag DEPTHS are not comparable between the two engines at all.
        "source": "hil_plant_sim.py SCENARIOS['ems-soc-band'] + the SocBandStrategy "
                  "docstring and the SOC_BAND_* constants (band half, share span, "
                  "charge admission) + SOC_BAND_DRAIN_LOAD_A for the SoC-rate and "
                  "LIMIT_I_FC_MAX budgets. Charge-window budget copied from "
                  "charge-fault (same 1.0 m/s single-source operating point, same "
                  "0.8 A de-rated ceiling, 19 % margin on LIMIT_I_FC_MAX); the "
                  "de-rate is load-bearing for the 13.435 V single-source sag "
                  "under the hi-fi DESIGN droop (~4x the measured bench chain — "
                  "not a hardware prediction; see the block above).",
        "allow_only": 0,              # expected completely fault-free
        # The charge window opens at t = 41 (deceleration ends, trailing slope
        # window fills by 42.0). Reaching it in Run is the precondition for the
        # I_charge assertion below meaning anything.
        "survive_to": {"t": 41.0, "states": {2, 3}},
        "signals_require": [
            # 1. The EMS ACTUALLY BIASED the split. Nominal is 0.50 and the
            #    policy's ceiling is 0.75 (SOC_BAND_SHARE_NOMINAL +
            #    SOC_BAND_SHARE_SPAN); 0.60 is unreachable without the SoC
            #    leaving the band, and unmistakable if it did. Window opens at
            #    the drain's full-load point (t = 13) and runs to the end of the
            #    charge cruise — deliberately WIDE, because the crossing time
            #    (t = 24.30) is a MODELLED number, not a measured one: if a
            #    campaign shows the crossing later than modelled, the fix is the
            #    SCENARIO's drain magnitude (SOC_BAND_DRAIN_LOAD_A), never this
            #    threshold.
            #    ⚠️ ONE SOURCE for 24.30 and for the 34.90 / 41.70 figures used
            #    below and in the docs: the GENERATOR's matched-model `soc-band`
            #    walk (`gen_dp_ems_table.py --scenario ems-dp-replay --dry-run`,
            #    the `band exit t= / share saturation t= / first charge t=`
            #    line). It is the same model the DP is solved against, so the
            #    benchmark comparison and these windows cannot drift apart.
            {"name": "share_biased_to_fc", "column": "cmd_share_sp",
             "min_value": 0.60, "t_window": (13.0, 54.0),
             "label": "soc-band commanded a share bias toward the fuel cell"},
            # 2. ... and the FIRMWARE acted on it. cmd_share_sp is only what the
            #    host asked for; I_fc is what the board's share loop delivered.
            #    At the drain phase's ~1.45 A bus total, a 0.50 split is 0.72 A
            #    and the policy's 0.75 ceiling is 1.09 A, so 0.85 A sits
            #    unambiguously between the two (and 22 % under LIMIT_I_FC_MAX).
            #    L1 (review, 2026-08-31) — the SAME caveat as signal #1, which
            #    it inherits and which was previously stated only there: the
            #    0.85 A threshold is derived from a MODELLED bus total, and the
            #    window's start is tied to the same modelled band-exit time
            #    (t = 24.30). If a campaign misses this check, the fix is the
            #    SCENARIO's drain magnitude (SOC_BAND_DRAIN_LOAD_A) — which
            #    moves both the crossing time and the bus total together —
            #    NEVER this threshold. Lowering it to make a run pass would
            #    quietly redefine "biased toward FC" as "not quite 50/50".
            #    L3 (review 2026-08-31) — WHAT A PASS ACTUALLY PROVES. The
            #    plant splits the bus current in proportion to the MDAC CODE
            #    RATIO (HIL_PLANT.md §4.7: sign- and monotonicity-preserving,
            #    WRONG GAIN), so this floor asserts the firmware->MDAC
            #    arithmetic — that the board read the command, moved the codes
            #    the right way, and moved them far enough. It is NOT share-loop
            #    GAIN validation: the amps here are the model's response to the
            #    codes, not the board's real droop chain (see also the
            #    K_DROOP_BUS design-vs-measured x4 finding).
            {"name": "fc_current_biased", "column": "I_fc",
             "min_value": 0.85, "t_window": (13.0, 38.0),
             "label": "the board's share loop moved current onto FC beyond the "
                      "nominal split"},
            # 3. The opportunistic charge window actually charged. Same form and
            #    same 0.5 A threshold as charge-fault's check: comfortably under
            #    the 0.8 A de-rated ceiling, unmistakably above an unpowered
            #    charger's 0 A. Window starts at 44.0 — charge_goal is asserted
            #    at ~42.0, then AG105_SETTLE_S 0.5 s + ~0.38 s of the
            #    AG105_TAU_S ramp puts I_charge over 0.5 A by ~42.9.
            #    ⚠️ CHARGER ERA (WP-1C, 2026-09-02) — CONFIRMED UNAFFECTED, and
            #    the confirmation is structural rather than empirical: this
            #    column is the PACK current, and ETA_CHG moves only what the
            #    charger COSTS the bus, never what the pack receives at a given
            #    ceiling. The de-rated 0.8 A ceiling and the AG105_TAU_S ramp
            #    that set this window are both untouched. What DID move on this
            #    scenario is the hydrogen: the governor walk falls 0.013677 ->
            #    0.012264 g (-10.3 %) because the FC channel no longer pays
            #    V_bus x i_charge for the window. `h2_accounted`'s 1e-3 floor
            #    keeps a ~12x margin on that, so it does not move either. The
            #    same argument covers `fc_current_biased`: its window
            #    (13.0-38.0) closes 4 s before charge_goal is asserted, so no
            #    charger current is inside it at all.
            {"name": "charge_window", "column": "I_charge", "min_value": 0.5,
             "t_window": (44.0, 54.0),
             "label": "opportunistic FC-path charging established in the low "
                      "cruise window"},
            # 4. The H2 metric ran end to end. h2_cum_g is monotone, so the peak
            #    IS the final value. Budget: the drain phase alone holds the FC
            #    channel near 0.72-1.09 A of bus current, i.e. ~11-17 W of stack
            #    power, for ~25 s; at the model's 1.7638e-5 g/s/W DC gain that is
            #    ~5e-3 g, so 1e-3 g is a ~5x-margin floor that still fails a run
            #    where the column is absent, zero, or frozen.
            #    ⚠️ The figure is the Gfc MODEL'S ESTIMATE: the map is
            #    scale-portable, but the stack is not identified against this
            #    rig (TODO(calibrate) — H2Consumption banner in
            #    hil_plant_sim.py). This check asserts that the accounting RAN,
            #    not that the absolute mass is calibrated.
            {"name": "h2_accounted", "column": "h2_cum_g", "min_value": 1.0e-3,
             "label": "the H2 consumption metric accumulated over the run"},
        ],
    },
    "ems-dp-replay": {
        # The NON-CAUSAL offline-optimal benchmark run (2026-08-31): the same
        # cycle and the same drain as `ems-soc-band`, driven by a setpoint table
        # that tools/gen_dp_ems_table.py computed by backward dynamic
        # programming with full foreknowledge.  Its objective is that the TABLE
        # WAS ACTUALLY PLAYED and the run stayed clean, so — exactly as for
        # ems-soc-band — every assertion below is POSITIVE.  "No fault" alone
        # would be satisfied by a run that never left the 0.50 default.
        #
        # --pi-live: EMS-driven, so build_plan() renders it SKIPPED and it is
        # never judged in that mode; the excusal this table forgoes costs
        # nothing (see the `bringup` entry's note).
        "source": "hil_plant_sim.py SCENARIOS['ems-dp-replay'] (a DERIVED entry "
                  "sharing ems-soc-band's ems_v_profile object and drain load) + "
                  "the DpReplayStrategy docstring + the SHIPPED TABLE "
                  "tools/dp_tables/dp_ems_table_ems-dp-replay.csv, whose own "
                  "header carries the DP-predicted totals. Every threshold below "
                  "is READ OFF THAT TABLE (share trajectory measured 2026-08-31, "
                  "`--charger-accounting physical`: 0.2500 at standstill, ramping "
                  "from t=4.0, at the 0.7500 rail continuously over t=10.6-40.1, "
                  "~0.5250 through the low cruise, back to 0.2500 by t=55.5; "
                  "charge_goal is 0 for the ENTIRE run — see the note below).",
        "allow_only": 0,              # expected completely fault-free
        # Deep inside the Run window (the strategy hands back MODE_SAFE at
        # SOC_BAND_RUN_EXIT_S = 58.0), so this asserts the run reached the low
        # cruise fault-free rather than merely surviving the drain phase.
        "survive_to": {"t": 50.0, "states": {2, 3}},
        # WHY THERE IS NO CHARGE CHECK, where `ems-soc-band` has one. It is a
        # FINDING, not an omission: the DP opens the charger path on ZERO
        # stages of this cycle. Shifting the split toward the fuel cell buys
        # 0.405 SoC per gram; running the Ag105 buys 0.169, so opportunistic
        # charging is simply the worse lever at this rig's numbers. Asserting a
        # charge window here would assert something the optimum deliberately
        # does not do.
        "signals_require": [
            # 1. THE DP-SPECIFIC assertion, and the sharpest one available:
            #    the table is at the 0.7500 rail from t = 10.6, whereas the
            #    causal `soc-band` policy cannot reach 0.75 before its SoC
            #    deficit saturates at t = 34.90 (the generator's matched-model
            #    walk — the same single source as the ems-soc-band entry's
            #    24.30, see the note there). A >= 0.74 command inside t = 12-20 s is
            #    therefore reachable by the DP TABLE and by nothing else this
            #    scenario could accidentally be running — the firmware's own
            #    default is 0.50 and the table's floor is 0.25. This is the
            #    "is this actually the DP's table?" check.
            {"name": "dp_early_fc_rail", "column": "cmd_share_sp",
             "min_value": 0.74, "t_window": (12.0, 20.0),
             "label": "the DP table's early fuel-cell rail (0.7500 from "
                      "t=10.6) was commanded — a value soc-band cannot reach "
                      "before t=34.90"},
            # 2. ... and the FIRMWARE acted on it. cmd_share_sp is only what
            #    the host asked for; I_fc is what the board's share loop
            #    delivered. At the drain phase's ~1.462 A bus total a 0.50
            #    split is 0.73 A and the table's 0.75 rail is 1.10 A, so
            #    0.95 A sits unambiguously between the two — and 32 % under
            #    LIMIT_I_FC_MAX 1.4 A, the same budget the generator's charge
            #    mask and the ems-soc-band entry both work against.
            #    L3 (review 2026-08-31) — WHAT A PASS ACTUALLY PROVES. The
            #    plant splits the bus current in proportion to the MDAC CODE
            #    RATIO (HIL_PLANT.md §4.7: sign- and monotonicity-preserving,
            #    WRONG GAIN), so this floor asserts the firmware->MDAC
            #    arithmetic — that the board read the command, moved the codes
            #    the right way, and moved them far enough. It is NOT share-loop
            #    GAIN validation: the amps here are the model's response to the
            #    codes, not the board's real droop chain (see also the
            #    K_DROOP_BUS design-vs-measured x4 finding).
            {"name": "dp_fc_current_railed", "column": "I_fc",
             "min_value": 0.95, "t_window": (14.0, 37.5),
             "label": "the board's share loop moved current onto FC to the "
                      "table's commanded rail"},
            # 3. The H2 metric ran end to end, so the comparison against
            #    `ems-soc-band` has both halves. h2_cum_g is monotone, so the
            #    peak IS the final value. Budget: the table's own header
            #    predicts h2_g_physical = 1.176e-2 g for this cycle, so 2e-3 g
            #    is a ~6x-margin floor that still fails a run where the column
            #    is absent, zero or frozen.
            #    ⚠️ The figure is the Gfc MODEL'S ESTIMATE: scale-portable
            #    map, stack not identified against this rig (TODO(calibrate) —
            #    H2Consumption banner in hil_plant_sim.py). This asserts that
            #    the accounting RAN, not that the absolute mass is calibrated;
            #    the DP-vs-soc-band RANKING is robust either way.
            {"name": "dp_h2_accounted", "column": "h2_cum_g", "min_value": 2.0e-3,
             "label": "the H2 consumption metric accumulated over the run"},
        ],
    },
    "ems-sdp": {
        # ═══ REBOUND TO `sdp-v3`, THE CALIBRATED BENCHMARK (2026-09-01) ══════
        # THE RULING (OVERNIGHT_LOG.md, "SDP charge-economics adjudication").
        # Campaign 20260901_000816 measured this leg OFF the EMS frontier: it
        # burned +12.78 % over the DP bound and 1.54 % more than the `soc-band`
        # heuristic at matched delta_soc, and the cause was its CHARGE ACTION.
        # Two independent agents closed the arithmetic: v2's stage cost prices
        # SoC at a shadow price alpha/(1-gamma) = 5.139 g/SoC, i.e. an
        # ABSOLUTE admission threshold of 0.1946 SoC/g, while the campaign
        # measures the Ag105 charge lever at 0.2364 SoC/g and the SHARE lever
        # at 0.409-0.415. Every lever priced inside (0.1946, 0.41) is TAKEN by
        # the solver and SCORED AS A LOSS — and the Ag105 sits exactly there.
        # The ported alpha had preserved a share-axis invariant from a source
        # (SDP_EnergyManagement2.m) that HAS NO CHARGE CONTROL.
        #
        # THE FIX, and it is in the ARTIFACT, not in this table: alpha was
        # re-derived by two-sided lever calibration
        # (alpha = (1-gamma)/sqrt(L_share * L_chg) = 0.1629624), and the charge
        # action is then rejected ENDOGENOUSLY — sdp_policy_v3.json's
        # `policy.charge_goal` is ZERO in all 101 x 25 cells with
        # `actions.forbid_charge_all` FALSE. Nothing was masked; the optimizer
        # declined. It self-revises: charging returns if the charger's measured
        # lever ever exceeds (1-gamma)/alpha = 0.30682 SoC/g (post-R1 / fw v24
        # is the plausible route).
        #
        # WHAT MOVED IN THIS ENTRY, and it is exactly one axis:
        #   * `sdp_charge_window_opened` is DELETED. Under v3 that check is a
        #     GUARANTEED FAIL, not a vacuous pass — the policy has no charge
        #     cell to command — so keeping it would fail a correct board.
        #   * `charge_path_never_opens` REPLACES it, asserting the opposite and
        #     for the same reason: the endogenous rejection is this artifact's
        #     defining behaviour and must be OBSERVED, not assumed.
        #   * THE SHARE AXIS IS UNCHANGED. v2 and v3 differ in `policy.share`
        #     on SoC rows 1-2 ONLY (30 cells of 2525), and this scenario's
        #     trajectory starts ON the target node (row 50) and falls ~0.0017,
        #     so checks 1-4 and 6-8 below are arithmetically the same
        #     assertions against the same table values. ⚠️ They were CALIBRATED
        #     on v2 campaigns; the first v3 campaign is expected to REPEAT them
        #     (in particular `sdp_clamped_rail_commanded`'s 0.84 floor and the
        #     0.95/1.00 raw pair), and a miss there is a finding about the
        #     rebinding, not a threshold to relax.
        #   * PROVENANCE: policy-block sha256 0443febf… (recipe
        #     sha256(json.dumps(doc["policy"], sort_keys=True)); the FILE sha
        #     moves on every regeneration and lives in the CSV meta sidecar's
        #     `config.sdp_policy` instead). v2's 740c802e… is now the DYNAMICS
        #     DEMONSTRATION artifact, kept byte-frozen for `ems-sdp-cross` /
        #     `ems-sdp-braking` (see EMS_STRATEGY_META).
        #   * SCORING: this leg is `frontier_eligible` and is one of the three
        #     runs the EMS_FRONTIER cross-run check compares — the scoring gap
        #     the campaign found (a 9.9 pp policy regression passed clean).
        #
        # Everything below this line predates the rebinding and is the v2-era
        # derivation, kept because it is what the share thresholds are read off.
        # ─────────────────────────────────────────────────────────────────────
        # The CAUSAL stochastic-DP leg (2026-08-31): the same cycle and the same
        # drain as `ems-soc-band` and `ems-dp-replay` (all three share ONE
        # ems_v_profile object and the SOC_BAND_DRAIN_* branch), driven by a
        # STATE-indexed policy baked by tools/sdp_ems_solver.py.
        #
        # ⚠️ RE-DERIVED 2026-08-31 FOR THE v2 DEMAND MAP.  The entry's own
        # contract is that thresholds are READ OFF THE SHIPPED ARTIFACT and
        # RE-DERIVED, never relaxed, when the solver regenerates it — and it
        # just did.  WHAT MOVED, in one paragraph, because a v1 campaign trace
        # and a v2 one are two different decision laws:
        #     v1 (POLICY-BLOCK sha256 dbe42d1b…) was solved against the TPM
        #     sidecar's IDEAL-SCALING demand span, -1.125 .. +1.640 W.  This
        #     rig's measured bus power is 0 .. 22.887 W, so campaign
        #     hil_report_20260831_191509 clamped ~98 % of decisions into the top
        #     bin: the demand axis carried NO information and the strategy
        #     emitted one constant clamped share for the whole run.  The
        #     plumbing was validated; the policy interior was never addressed.
        #     v2 (POLICY-BLOCK sha256 740c802e…, the SHIPPED artifact
        #     tools/sdp_policies/sdp_policy_v2.json) is the SAME TPM re-solved
        #     against a [0.0, 25.0] W consumer demand map (solver D11).
        # The three checks that used to assert the constant-0.85 emission are
        # therefore no longer the artifact's discriminator — 0.85 is STILL what
        # is emitted (see the clamp note below), so the old check would pass
        # identically under both artifacts and prove nothing about the re-map.
        # The interior-actuation evidence moved to `cmd_share_sp_raw` and to the
        # charge window, both below.
        #
        # ALL v2 THRESHOLDS COME FROM ONE OFFLINE WALK (2026-08-31): the
        # strategy's own decision path — soc0 capture, soc_relative(),
        # demand_bin(), the table lookup, clamp_share() — stepped at the
        # artifact's 1 s cadence over the RECORDED P_dem and SoC trace of the
        # campaign's `ems-sdp` run.  Its results, which every number below is
        # read off:
        #     61 decisions, ZERO clamps either way, 13 distinct demand bins
        #       (0, 2-7, 9, 10, 12, 16, 17, 22) vs v1's single bin 24;
        #     TABLE request 0.95 for t = 13..38 (bin 22, the drain plateau) and
        #       1.00 everywhere else — the demand axis moving the action;
        #     EMITTED share 0.8500 for all 61 decisions (every one of the
        #       table's values 0.90/0.95/1.00 is above SOC_BAND_SHARE_MAX);
        #     charge_goal = 1 for t = 41.0 .. 58.0 (the post-drain 1.0 m/s low
        #       cruise; bins 2-5, P_dem 2.62 .. 5.59 W).
        # ⚠️ THE WALK IS OPEN LOOP.  It steps a v1 run's recorded trace, so it
        # cannot contain the plant's response to a command v2 issues and v1 did
        # not — which is precisely the charge window.  The chatter note on
        # `sdp_charge_window_opened` is DERIVED, not measured, and the first v2
        # campaign is what turns it into a fact.
        #
        # ⚠️ CURRENT BUDGET, RE-CHECKED FOR v2, both operating points:
        #   * SHARE.  Unchanged from v1, because the emitted value is unchanged:
        #     an in-band 0.85 is clipped by the firmware's own governor to
        #     [I_min/I_tot, 1 - I_min/I_tot] = [0.202, 0.798] at this scenario's
        #     measured 1.4866 A drain peak, so I_fc = 1.1866 A — 15.2 % under
        #     LIMIT_I_FC_MAX 1.4 A — with the BT minority at exactly
        #     SHARE_MINORITY_I_MIN_A 0.30 A, governed rather than starved.
        #     (⚠️ DI-LOW-3: 1.4866 / 1.1866 A / 15.2 % are the campaign
        #     20260831_191509 MEASURED peaks over the t = 20..38 plateau; the
        #     1.462 / 1.162 A / 17 % this block used to quote were the
        #     pre-campaign ESTIMATE.)  No
        #     cut is attempted, so SHARE_CUT_MAX_HANDOFF_A never enters.
        #   * CHARGING (NEW under v2).  With FC_CHARGE_ENABLE open,
        #     assertFcChargeEnable() has dropped BT off the bus and the FC
        #     channel alone carries the load plus the charger:
        #         5.593 W / 15.95 V = 0.351 A + chg_i_ceiling_a 0.800 A
        #                                      = 1.151 A  -> 18 % margin
        #     which is `ems-soc-band`'s own validated charge-window budget at
        #     the same operating point (its 1.139 A / 19 %).  The solver's
        #     charge mask bounds the general case at the bin's UPPER edge too:
        #     6.0 W / 15.95 + 0.8 = 1.176 A, under its CHARGE_FC_MARGIN * 1.4 =
        #     1.19 A ceiling.  So `allow_only: 0` still holds and an OC_FC here
        #     remains a REAL finding.
        #
        # RETIRED, deliberately: the queued BT_BUS switch_transitions / cut-
        # latency check.  It was raised against v1's 3.8 ms self-heal at
        # t ~ 10.38 s, which came from the SETPOINT-LATCH path
        # (updateShareSetpointCutoff()).  Under v2 the emitted share is 0.8500
        # throughout — inside [DROOP_R_MIN, DROOP_R_MAX], strict `<`/`>` — so
        # that path is never entered and the check would assert a mechanism that
        # cannot fire.  BT_BUS *does* still get cut and restored here, but by
        # assertFcChargeEnable() on the charge window, at a cadence the walk
        # cannot predict (see the chatter note); calibrating a count or a
        # latency for it is the FIRST v2 CAMPAIGN's job, not a guess made here.
        "source": "hil_plant_sim.py SCENARIOS['ems-sdp'] (a DERIVED entry sharing "
                  "ems-soc-band's ems_v_profile object and SOC_BAND_DRAIN_* load) "
                  "+ the SdpStrategy banner (SoC0-relative regulation, the v1->v2 "
                  "demand re-map, the decision cadence, the clamp_share() "
                  "hardware-envelope clamp, and its PREDICTED BEHAVIOUR block, "
                  "which is where the 0.8500 emission, the raw-request span and "
                  "the charge window below are derived) + the SHIPPED artifact "
                  "tools/sdp_policies/sdp_policy_v3.json (policy-block sha256 "
                  "0443febf…, THE CALIBRATED BENCHMARK — the v2 artifact "
                  "740c802e… the share thresholds were measured on is now the "
                  "frozen DYNAMICS DEMONSTRATION for ems-sdp-cross/-braking; "
                  "the two share maps differ on SoC rows 1-2 only, which this "
                  "trajectory does not reach) + OVERNIGHT_LOG.md 'SDP "
                  "charge-economics adjudication' (the rebinding ruling) "
                  "+ tools/sdp_ems_solver.py D11 (the demand map). "
                  "Current budgets from SOC_BAND_DRAIN_LOAD_A's LIMIT_I_FC_MAX "
                  "arithmetic, the firmware's own setpoint governor "
                  "(.ino:9556-9568), and the solver's charge mask.",
        # FAULT-FREE, mirroring `ems-soc-band` and `ems-dp-replay` — and the
        # budgets above are re-checked for BOTH of v2's operating points, so
        # nothing is allowed.
        "allow_only": 0,
        # CALIBRATED 2026-08-31 and the `provisional_note` DELETED — campaign
        # 20260831_222036 was the first live sdp_policy_v2 run and measured all
        # three of the previously-provisional checks
        # (`sdp_table_interior_at_high_demand`, `sdp_table_rail_at_low_demand`,
        # `sdp_charge_window_opened`). Every offline-walk prediction was
        # confirmed to the digit: raw requests exactly {0.95, 1.00}, the 0.95
        # plateau at 13.077-38.262 s against a predicted 13-38, charge_goal at
        # t = 41.306 against a predicted ~41. The bands below are now read off
        # MEASUREMENT; each carries its measured value and its margin. Same
        # precedent as scp-inrush, whose note was removed once its i_cut band
        # was measured live.
        # Deep inside the Run window (the strategy hands back MODE_SAFE at
        # SDP_RUN_EXIT_S = SOC_BAND_RUN_EXIT_S = 58.0), the same depth
        # `ems-dp-replay` asserts: the run must reach the low cruise fault-free,
        # not merely survive the drain phase.  Under v2 this is also what makes
        # the charge window reachable at all — it opens at t = 41.
        "survive_to": {"t": 50.0, "states": {2, 3}},
        "signals_require": [
            # 1. THE EMS LAYER ACTUALLY COMMANDED. The v_setpoint axis comes
            #    straight from the scenario's ems_v_profile, which holds 1.5 m/s
            #    over t = 8..38. A run where the policy failed to bind, or where
            #    the 50 Hz stream never carried its setpoints, cannot reach 1.45.
            #    Measured on the HOST's command column: it asserts the EMS
            #    layer's own output, independently of anything the board does
            #    with it (check 6, `sdp_fc_current_biased`, is the board-side
            #    half).
            #    UNCHANGED by the v2 re-map — the drive axis is scenario script,
            #    not policy output.
            {"name": "sdp_drive_commanded", "column": "cmd_v_sp",
             "min_value": 1.45, "t_window": (12.0, 30.0),
             "label": "the SDP policy commanded the profile's 1.5 m/s cruise"},
            # 2. THE ACTUATED LEVEL. The artifact's action at
            #    (soc_rel <= target) is the FC rail, emitted at the
            #    hardware-envelope clamp as 0.8500 — a value NOTHING else driving
            #    this cycle commands: the firmware's own default is 0.50,
            #    `soc-band`'s ceiling is 0.75 (SOC_BAND_SHARE_NOMINAL +
            #    SOC_BAND_SHARE_SPAN) and the DP table's rail is 0.75 as well.
            #    Floor 0.84 sits just under the emitted value and a clear 0.09
            #    above the nearest thing any sibling strategy can reach.
            #    Window 5.0-54.0: from Run entry (3.0) plus a decision cadence to
            #    the end of the low cruise — the command is expected to be HELD
            #    for the whole run, so a wide window is honest here (unlike the
            #    sibling entries, whose commands are trajectories).
            #    ⚠️ WHAT THIS CHECK CANNOT SEE, and it is now the POINT rather
            #    than a footnote: every table value in (0.85, 1.0] emits the SAME
            #    clamped 0.8500, so this check passes IDENTICALLY under v1 and
            #    v2 and says nothing about which demand map is in force. It
            #    asserts the ACTUATED LEVEL only. Checks 3 and 4 are the ones
            #    that discriminate the artifact; `config.sdp_policy` in the CSV's
            #    meta sidecar (file + policy-block sha256) is its identity.
            #    ⚠️ If a campaign measures a RAW 1.0000 in THIS column, the clamp
            #    is not being applied — a defect in SdpStrategy.clamp_share(),
            #    not a board finding, and the run would also latch OC_FC.
            {"name": "sdp_clamped_rail_commanded", "column": "cmd_share_sp",
             "min_value": 0.84, "t_window": (5.0, 54.0),
             "label": "the SDP policy's fuel-cell rail, emitted at the 0.8500 "
                      "hardware-envelope clamp — a level neither soc-band nor "
                      "the DP table (both 0.75) can reach"},
            # 3. THE POLICY INTERIOR ACTUATED, HALF ONE — the demand axis moved
            #    the TABLE's request off its rail on the drain plateau.
            #    `cmd_share_sp_raw` is the PRE-clamp column added in this same
            #    round for exactly this purpose: the emitted column cannot show
            #    it, because 0.95 and 1.00 both clamp to 0.8500.
            #    DERIVATION. On t = 13..38 the walk's measured P_dem is
            #    22.87 W, which normalizes to x = 0.9150 and lands in bin 22
            #    ([0.88, 0.92) = [22.0, 23.0) W). The v2 table's action there is
            #    the interior 0.95 (bins 22-23; bin 24 is 0.90), against 1.00 in
            #    every lower bin. Ceiling 0.97 is the midpoint of that 0.05 gap.
            #    A CEILING, not a floor: `max_value` fails if ANY sample in the
            #    window exceeds it, so a run whose demand fell back into bin 21
            #    or below — or a v1 artifact, whose top-bin action is 1.00
            #    everywhere — FAILS here. That is the intent.
            #    ROBUSTNESS: the check tolerates bins 22, 23 and 24 (0.95, 0.95,
            #    0.90), so it survives the plateau drifting UP by any amount; it
            #    needs P_dem to fall below 22.0 W (3.8 % under the measured
            #    22.87) to fail spuriously. Window 20.0-36.0 is the settled
            #    interior of the plateau — after the drain ramp completes at
            #    13.0 with margin, before the ramp-out at 38.0.
            #
            #    ⚠️ CALIBRATED, AND MADE TWO-SIDED (campaign 20260831_222036).
            #    MEASURED: cmd_share_sp_raw is EXACTLY 0.950000 on all 16000
            #    in-window samples — min and max identical, the plateau is one
            #    bin throughout. The ceiling alone was one-sided and VACUITY-
            #    PRONE in one specific direction: a run whose demand axis
            #    collapsed DOWNWARD (a lower bin, whose action is smaller, or a
            #    column that went blank-then-parsed-low) satisfies "peak <=
            #    0.97" while asserting nothing about the interior. The added
            #    floor spec closes it. Both bands are +/-0.010 around the
            #    measured 0.950, which is 5x the 0.002 gap to the next ladder
            #    step down (0.90 -> the 0.05 gap is what the ceiling separates)
            #    and far wider than any float32 round trip.
            #    TWO SPECS, not one: _judge_signal_leaf() tests min_value FIRST
            #    and returns, so a single spec carrying both keys drops the
            #    ceiling silently (the import-time guard refuses the shape).
            {"name": "sdp_table_interior_at_high_demand",
             "column": "cmd_share_sp_raw", "max_value": 0.960,
             "t_window": (20.0, 36.0),
             "label": "the v2 demand axis moved the table off its rail on the "
                      "drain plateau — the pre-clamp request is the interior "
                      "0.95, which a v1 (ideal-scaling map) artifact cannot "
                      "produce"},
            #    3b. The floor half of the same band — see the calibration note
            #    on 3. Peak-based like every value spec here, so it asserts that
            #    the in-window MAXIMUM reached 0.940: a run whose raw request
            #    fell to a lower ladder step for the whole window fails here,
            #    which is the one-sided gap the ceiling could not see.
            {"name": "sdp_table_interior_floor",
             "column": "cmd_share_sp_raw", "min_value": 0.940,
             "t_window": (20.0, 36.0),
             "label": "... and did not collapse BELOW the interior 0.95 either "
                      "— the floor half of the measured two-sided band"},
            # 4. THE POLICY INTERIOR ACTUATED, HALF TWO — and the request comes
            #    BACK to the rail when the demand falls. Paired with check 3
            #    this asserts a SPAN in the table's request across the run,
            #    which is the whole claim the re-map makes.
            #    DERIVATION: over the post-drain 1.0 m/s cruise the walk's
            #    P_dem is 5.59 W -> bin 5, whose action is 1.00 at every SoC
            #    node below the relative target. Floor 0.999 sits between 1.00
            #    and the next ladder step down (0.95). Window 44.0-54.0 is
            #    `ems-soc-band`'s own charge-window window, chosen for the same
            #    reason: the drain has fully ramped out and the cruise is
            #    settled.
            #    ⚠️ This check is INSENSITIVE to the chatter described on check
            #    5: whether the charger path is open (bin ~18) or closed
            #    (bin 5), the table's action at a sub-target SoC node is 1.00 in
            #    both, so neither state can fail it.
            #    ⚠️ CALIBRATED (campaign 20260831_222036). MEASURED: exactly
            #    1.000000 on all 10000 in-window samples. Floor tightened
            #    0.99 -> 0.999, which is still 0.049 clear of the 0.95 ladder
            #    step it must exclude and 0.001 under the measured value — a
            #    float32 UDP round trip of 1.0 is exact, so no round-trip
            #    allowance is needed here (unlike the ems-y `share_hi_clip`
            #    band, whose value is not representable).
            {"name": "sdp_table_rail_at_low_demand",
             "column": "cmd_share_sp_raw", "min_value": 0.999,
             "t_window": (44.0, 54.0),
             "label": "the table's request returns to the 1.00 rail at low "
                      "demand — with check 3, a measured span across the "
                      "demand axis"},
            # 5. THE CHARGE ACTION IS DECLINED, AND THE BOARD NEVER SEES ONE.
            #    ⚠️ THIS CHECK IS THE INVERSE OF THE ONE IT REPLACES.  Until
            #    2026-09-01 this slot held `sdp_charge_window_opened`
            #    (FC_CHARGE_ENABLE high for >= 4000 ticks over t = 41..58),
            #    which was the strongest v1/v2 discriminator in the entry.
            #    Under the CALIBRATED v3 artifact that check is a GUARANTEED
            #    FAIL rather than a vacuous pass: `policy.charge_goal` is zero
            #    in all 101 x 25 cells, so there is no charge action for the
            #    policy to command and no window for the firmware to open.
            #    Deleting it and asserting the opposite is therefore the only
            #    honest move — the endogenous rejection is what this artifact
            #    IS, and an artifact's defining behaviour must be observed.
            #    DERIVATION OF `max_ticks: 0` — EXACT, NOT LENIENT.  The
            #    firmware opens FC_CHARGE_ENABLE only from chargingControl()'s
            #    charge branch, which requires `charge_goal > 0` on the wire
            #    (.ino:10034).  The policy emits `charge_goal` straight from
            #    the table (SdpStrategy.decide(); the dwell latch can only HOLD
            #    an intent the table already raised), and the table's charge
            #    map is identically zero — so a SINGLE tick of FC_CHARGE high
            #    on this run means either the artifact is not the one the
            #    strategy claims, or a command the policy never issued reached
            #    the board.  Both are findings, and neither has a tolerance.
            #    NO `t_window`: the assertion is over the WHOLE post-grace run
            #    (scan_signals() already starts at WARM_RESET_GRACE_S), because
            #    "never" is the claim.  The v2-era 41..58 s window was the
            #    window the ACTION was predicted in; there is no such window
            #    now, and scoping a "never" assertion to one would leave the
            #    rest of the run unasserted.
            #    ⚠️ WHAT THIS CANNOT SEE — the HOST side.  There is no
            #    `cmd_charge_goal` CSV column (hil_plant_sim.py's simulated
            #    schema carries `cmd_v_sp`/`cmd_share_sp`/`cmd_share_sp_raw`
            #    only), so the commanded intent is not observable offline and
            #    the companion "the policy never ASKED" assertion cannot be
            #    written today.  What IS asserted is the board-side outcome,
            #    which is the one that matters for the harvest accounting; the
            #    host-side intent is covered by the SdpStrategy exit summary's
            #    `charge dwell latches 0`.  Adding the column is an append-only
            #    schema change and is the natural follow-up if a campaign ever
            #    needs to separate "the policy asked and the board refused"
            #    from "the policy never asked".
            {"name": "charge_path_never_opens", "switch_bit": SW_FC_CHARGE,
             "max_ticks": 0,
             "vacuity_note":
                 "the `switch` column cannot be blank on a run that reaches "
                 "State 2: every other check in this entry (survive_to, "
                 "sdp_fc_current_biased, the cmd_* floors) fails on a run with "
                 "no observation frames, so a zero tick count here cannot be "
                 "'the column was never written'. There is deliberately no "
                 "companion positive bound on SW_FC_CHARGE — a positive bound "
                 "is exactly what this artifact must NOT produce.",
             # ⚠️ THE PREMISE WAS RE-DERIVED FOR THE CHARGER ERA (WP-1C,
             # 2026-09-02) AND THE CHECK IS UNCHANGED. The retired sentence
             # named the 1:1-era measured lever (0.2364 SoC/g) against
             # sdp_policy_v3's admission threshold. Under ETA_CHG 0.88 the
             # modelled charge lever RISES to eta x L_share = 0.3964 SoC/g
             # (WP-1B1), which is exactly why alpha had to be re-calibrated:
             # sdp_policy_v4 solves at alpha 0.118326 and STILL reports zero
             # charge cells, so the endogenous rejection — and this check's
             # `max_ticks: 0` — survive the era change on a re-derived premise
             # rather than on the old arithmetic. Verified offline: the
             # governor walk on this scenario opens zero charge windows under
             # the v4 artifact in BOTH eras.
             "label": "the CALIBRATED policy never opened the charger path — "
                      "the charge action is declined ENDOGENOUSLY by the "
                      "artifact (zero charge cells, forbid_charge_all False), "
                      "at the eta-era alpha the solver re-calibrated to"},
            # 6. ... AND THE FIRMWARE ACTED ON THE SHARE — the "cmd_share_sp is
            #    only what the host asked for" half both sibling entries carry.
            #    Derivation, and it is the GOVERNED value rather than the
            #    commanded one: an in-band 0.85 is clipped by the firmware's own
            #    setpoint governor to 1 - I_min/I_tot (.ino:9556-9568), which at
            #    the drain plateau's measured 1.4866 A total is 0.798, so the
            #    delivered I_fc is 1.1866 A (campaign 20260831_191509; DI-LOW-3
            #    — 1.462 A / ~1.16 A here was the pre-campaign estimate).
            #    Against the firmware's default 0.50 split at the same load
            #    (0.743 A) the two are far apart, and 1.00 A sits between them
            #    with 15.7 % of margin below the measured value — while staying
            #    28.6 % under LIMIT_I_FC_MAX 1.4 A, so
            #    a pass can never be confused with an overcurrent.
            #    Window 20.0-38.0 is the drain plateau: after the ramp completes
            #    at 13.0 (plus settling) and before the ramp-out at 38.0. The v2
            #    charge window opens at 41.0, OUTSIDE this window, so the
            #    single-source charging operating point never enters it.
            #    L3 (inherited from both sibling entries) — WHAT A PASS PROVES.
            #    The plant splits bus current in proportion to the MDAC CODE
            #    RATIO (HIL_PLANT.md §4.7: sign- and monotonicity-preserving,
            #    WRONG GAIN), so this floor asserts the firmware->MDAC
            #    arithmetic, NOT share-loop gain validation.
            {"name": "sdp_fc_current_biased", "column": "I_fc",
             "min_value": 1.00, "t_window": (20.0, 38.0),
             "label": "the board's share loop moved current onto FC to the "
                      "governed level of the commanded 0.85"},
            # 7. ... and the accounting saw it. h2_cum_g is monotone, so the peak
            #    IS the final value. Budget for the FULL 61 s run (this scenario
            #    is expected to complete, not to truncate): over the ~25 s drain
            #    plateau the FC channel carries ~0.795 x 1.46 A = 1.16 A at
            #    V_bus ~15.85 -> ~18.4 W of bus power, ~21.6 W at the stack
            #    through ETA_BOOST 0.85, i.e. ~3.8e-4 g/s at the model's
            #    1.7638e-5 g/s/W DC gain and ~9.5e-3 g over the plateau alone;
            #    the accel, ramp and low-cruise segments add a few e-3 more.
            #    UNMOVED by the v2 re-map: the drain plateau's delivered split is
            #    the governed 0.795 under both artifacts, so the dominant term of
            #    this budget is identical. The v2 charge window ADDS fuel-cell
            #    burn (the charger's draw is billed to FC), which moves the total
            #    UP and away from a floor.
            #    1.0e-3 g is therefore the same threshold and the same ~10x
            #    margin class as the ems-soc-band entry's h2_accounted, and it
            #    still fails a run where the column is absent, zero or frozen.
            #    ⚠️ The figure is the Gfc MODEL'S ESTIMATE (scale-portable map,
            #    stack not identified against this rig — H2Consumption banner).
            #    This asserts that the accounting RAN, not that the mass is
            #    calibrated.
            {"name": "sdp_h2_accounted", "column": "h2_cum_g",
             "min_value": 1.0e-3,
             "label": "the H2 consumption metric accumulated over the run"},
            # 8. THE STUDENT'S AXIS WAS PLUMBED. `min_value: 0.0` is a DELIBERATE
            #    plumbing assertion, not a magnitude one: an absent or unparseable
            #    column measures "peak unmeasured" and FAILS (_judge_signal_leaf),
            #    while any parseable sample passes. It therefore asserts that
            #    h2_sdp_cum_g exists and is being written on this run, WITHOUT
            #    duplicating check 7's magnitude budget on a second model of the
            #    same quantity (which would fail twice for one cause).
            #    ⚠️ h2_sdp_cum_g is a SECOND MODEL of h2_cum_g's quantity on the
            #    SAME P_fc input (the student's static proxy, eta_fc 0.5). It
            #    under-reads Gfc by ~5.5 % at steady state by construction; the
            #    gap between the two columns is arithmetic, never a finding.
            {"name": "sdp_student_h2_axis", "column": "h2_sdp_cum_g",
             "min_value": 0.0,
             "label": "the student's static-proxy H2 column was written"},
        ],
    },
    "handoff-sag": {
        # F2 (kept): this is a live simulation of the TP0178/TP0201 class, whose
        # RECORDED margin above LIMIT_V_BUS_MIN was only 0.15-0.185 V with a ~10 ms
        # dwell (half the 20 ms latch window) — see hil_replay_suite.py's TP0178/
        # TP0201 entries.  A legitimately deeper sag on this scenario's own load
        # step would correctly latch UV_BUS.
        #
        # CORRECTED 2026-08-30c (campaign follow-up (1), and the round-2 reviewer
        # found the same staleness independently): this comment used to describe a
        # "+0.8 A step (~1.14 A on the FC-only channel)". That was an intermediate
        # design that never shipped. The SHIPPED scenario rails share to 0.0 so
        # **BT survives** and steps +1.5 A against it — measured on hardware at
        # I_batt 2.2709 A vs LIMIT_I_BT_MAX 3.0 A (24.3 % margin, against the 25 %
        # designed). An OC_FC here would still mean the perturbation budget is
        # wrong, but the channel at risk is BT, not FC; OC_BT is the fault this
        # operating point can actually reach, and allow_only refuses both.
        #
        # ⚠️ UV_BUS IS NOT REACHABLE AT THIS OPERATING POINT (measured, campaign
        # 20260830_203006): min V_bus was 14.4300 V, 2.43 V above the floor, and at
        # the fitted single-source hifi droop (0.633 ohm) reaching 12.0 V needs
        # ~6.1 A — at which OC_BT always wins first. `allow_only: UV_BUS` is
        # therefore PERMISSIVE BUT NEVER EXERCISED here. It is kept because the
        # scenario models a class whose recorded members did sag that far, not
        # because this run can.
        # ✅ THE UV OBJECTIVE NOW HAS ITS OWN HOME (2026-09-01, operator
        # ruling): the `v-bus-sense-offset` scenario, which walks the SENSED
        # V_bus below the limit for a controlled 12 ms and then 60 ms and so
        # asserts UV_BUS_DWELL_LATCH_MS from BOTH sides. It is no longer an open
        # item, and nothing about the UV threshold should be read off THIS
        # scenario, whose bus floor is reached on the BT rail behind an OC_BT.
        # RECORD CORRECTED 2026-08-31 (ledger fix queue): the "~10 ms dwell vs
        # the 20 ms latch" this line used to quote did not survive replay. Both
        # recorded floors (12.1489 / 12.1853 V) stay ABOVE LIMIT_V_BUS_MIN, so
        # the leaky integrator accumulates 0.0 ms — the margin is a VOLTAGE
        # margin, not a dwell one.
        "source": "hil_replay_suite.py TP0178/TP0201 entries (0.149-0.185 V of "
                  "recorded margin ABOVE the limit, hence 0.0 ms of "
                  "accumulated dwell against the 20 ms latch) + "
                  "HIL_FINDINGS 'handoff-sag' for the OC_FC pre-emption + "
                  "the operating-point derivation in hil_plant_sim.py's "
                  "SCENARIOS['handoff-sag'] comment (review M3)",
        "allow_only": FAULT_UV_BUS | FAULT_ERROR,
        "survive_to": {"t": 20.0, "states": {2, 3}},
        # M3: the review's concern was that the scenario might never actually take
        # a source off the bus, in which case every fault expectation above is
        # satisfied by a run that tested nothing. VERIFIED MECHANISM: the setpoint
        # latch in updateShareSetpointCutoff() drives FC_BUS_ENABLE LOW when the
        # commanded share falls below DROOP_R_MIN 0.15 (.ino:9231-9243) — and it
        # runs BEFORE the governor (.ino:9377-9385), so the 0.60 A closed-loop entry
        # gate does not block it. Assert the switch bit is CLEAR for essentially the
        # whole post-rail window: the rail is commanded at t = 6, and at 1 kHz the
        # 8-20 s window is ~12000 ticks, so allowing 200 covers the handful of
        # samples around the transition without admitting a run where the cut never
        # happened or was re-closed.
        "signals_require": [
            {"name": "fc_bus_open", "switch_bit": SW_FC_BUS, "max_ticks": 200,
             "t_window": (8.0, 20.0),
             # L4 (review 2026-08-31): this is the suite's ONE max_ticks-only
             # spec with no same-signal companion, so the vacuity escape is
             # taken explicitly. It is sound here because the entry's OWN
             # `survive_to` {t: 20.0, states: {2, 3}} reads the same observation
             # rows and fails unless a frame at t = 20 reports State 2 or 3 —
             # which cannot happen on a blank or absent switch column. The
             # observable is therefore proven present by a bound already in
             # this entry, just not by one written on the switch column itself.
             "vacuity_note": "survive_to {t: 20.0, states: {2, 3}} proves the "
                             "observation rows (and so the switch column) are "
                             "populated over this window",
             "label": "FC_BUS_ENABLE opened by the share setpoint latch and held "
                      "open until the perturbation"},
        ],
    },
    "scp-inrush": {
        # ── DETERMINISTIC SINGLE-OUTCOME EXPECTATION (2026-08-31 redesign) ──────
        # This entry was TWO-OUTCOME (events_any_of) for exactly one round, because
        # the flat 5.0 A load could not win the one-tick race against the firmware's
        # OC teardown and the check was scoring a coin flip. The STIMULUS was fixed
        # instead: hil_plant_sim.py's scp-inrush branch is now three-phase — the
        # motor node ramps UNLOADED, a 6.5 A pulse lands once V-MOT is above the H1
        # Norton floor, and the fold binds and cuts INSIDE that same 1 kHz tick.
        # The firmware sees nothing anomalous until the pulse tick (I_fc is
        # ~0.63 A through the whole ramp — headless bench 2026-08-31, same harness
        # as the i_cut provenance below), so its reaction cannot land earlier than
        # pulse+L for any L >= 1 — the race is not won, it is not entered. The
        # expectation is single-outcome again. Full derivation at
        # SCP_INRUSH_ARM_V / SCP_INRUSH_FOLD_LOAD_A in hil_plant_sim.py.
        #
        # The scenario's objective is unchanged: gate on the EVENTS sidecar
        # containing scp_cut rather than on fault flags. (The pre-2026-08-30
        # stimulus put the load on an already-ON switch and produced ZERO fold
        # events — the foldback branch exists only in the SOFT state.)
        #
        # NO fault is REQUIRED — but the OC_FC latch IS now a designed part of the
        # sequence rather than an incidental one. The phase-3 run load
        # (SCP_INRUSH_RUN_LOAD_A 5.0 A, applied SCP_INRUSH_RUN_S 110 ms after the
        # pulse, i.e. after the 64 ms foldback retry has completed to ON) drives
        # I_fc/I_bt to 2.07-2.25 A each against LIMIT_I_FC_MAX 1.4 A. It is left
        # ALLOWED rather than REQUIRED because FAULT_MOT_HOTPLUG (.ino:8832-8834)
        # is the equally-correct firmware outcome if the P3 gate times out first,
        # and this table must not force one of two correct behaviours.
        # See the SCP_INRUSH_* block in hil_plant_sim.py for why an scp_cut cannot
        # be separated from an OC fault in this model.
        #
        # RETRY CADENCE IS NOW REACHED, unlike under the flat load. The old note
        # here read "zero retry cycles are observable with firmware attached — the
        # State-99 teardown pulls MOT_PWR LOW 54 ms before the 64 ms re-arm"; that
        # was true when the OC latched ~1 ms after the cut. It no longer is: the
        # fold now fires BEFORE the firmware has any reason to react, so the switch
        # is still enabled through the retry, and the sequence runs
        # cut -> re-arm (+64 ms) -> ON (+91 ms) -> run load (+110 ms) -> OC_FC.
        # The count == 1 pin below is therefore load-timing evidence, not an
        # artefact of the teardown truncating the cadence.
        "source": "HIL_FINDINGS 'scp-inrush' recommendation 3 + "
                  "hil_electrical.py Rt1987._soft_operating_point()/SCP branch "
                  "(RT_SCP_BLANK_S 250 us, RT_SCP_RETRY_S 64 ms) + "
                  "hil_plant_sim.py SCP_INRUSH_ARM_V / SCP_INRUSH_FOLD_LOAD_A / "
                  "SCP_INRUSH_RUN_S for the three-phase stimulus derivation "
                  "(2026-08-31 deterministic redesign)",
        "allow_only": FAULT_OC_FC | FAULT_MOT_HOTPLUG | FAULT_ERROR,
        # NO `not_before_s` AND NO `survive_to`, and this is a derivation, not an
        # omission (figures corrected 2026-08-31 review H1 — an earlier draft cited
        # a 0.7 s grace window; the constant is WARM_RESET_GRACE_S 2.0). The whole
        # stimulus completes ~1.3 s BEFORE the grace bound:
        #     P3 close ~0.590 -> TD_ON +8 ms -> ramp ~2 ms -> CUT ~0.601
        #     retry +64 ms -> ON ~0.692 -> run load ~0.711 -> OC_FC ~0.712
        # so the only thing the post-grace fault scoring ever sees is the
        # PERSISTING latch, which `allow_only` above covers. `not_before_s` is
        # unusable here twice over: it is evaluated only under a `require` (inert
        # without one), and if a `require` were added, the post-grace-scoped
        # `fault_first_t` reports the GRACE BOUND (2.0) as the onset for an
        # in-grace latch while the import assert floors any legal `not_before_s`
        # strictly above 2.0 — the bound would sit after its own evidence and
        # FAIL, misleadingly. `survive_to` is unusable because by any legal probe
        # time the board has already, correctly, latched. The evidence this
        # scenario can carry is therefore the EVENT sidecar (below), which is not
        # grace-filtered — that is why the objective was moved onto events in the
        # first place.
        # ⚠️ These times MOVED with the redesign: under the flat load the OC
        # latched ~1 ms after the cut (~0.601), not ~110 ms after it.
        # ⚠️ RE-VERIFIED 2026-08-30d against the TRCB-in-SOFT change, because that
        # change could in principle have stolen this scenario's event: a reverse
        # trip removes the switch from SOFT, and fold/SCP is a SOFT-only mechanism,
        # so a reverse trip before the fold would mean no scp_cut ever fires.
        # A headless reproduction of the SHIPPED sequence — real Plant, real
        # ElectricalSim at this scenario's own vesc_cap_f, real apply_scenario(),
        # and the actuator word stepped through the firmware's own bring-up gates
        # (busBringupTick(), .ino:8723-8845) evaluated against the plant's rails —
        # settles it. AT THE P3 CLOSE THE MOTOR NODE IS DARK, and under the
        # three-phase stimulus it stays FORWARD-biased throughout the ramp
        # (v_in 15.47 V, v_out 0.73 -> 1.54 V). There is no reverse condition to
        # trip, and the measured outcome is a single MOT_PWR scp_cut.
        # A reverse trip during soft-start needs a PRE-CHARGED node (the comm-loss
        # warm-recovery shape), which P3 never presents — the two cases are
        # structurally different and do not compete.
        # (One NEW reverse_block does appear in a hi-fi run, on BT_BUS at ~62 ms,
        # dv = -50.4 mV: the diode-OR blocking whichever boost is momentarily lower,
        # which is the RT1987's advertised function. Verified INERT — cut counts and
        # both bring-up current pins are byte-identical with the branch disabled.)
        #
        # WHAT IS PINNED, and why each pin is evidence rather than decoration:
        #   count == 1        exactly one cut. Under the three-phase stimulus the
        #                     fold pulse is a ONE-SHOT (withdrawn on the next
        #                     apply_scenario() call), so the 64 ms retry soft-starts
        #                     into a clean node and completes to ON. A SECOND cut
        #                     would mean the pulse was not withdrawn or the run load
        #                     landed while the switch was still in SOFT — both real
        #                     stimulus regressions. Zero cuts means the fold never
        #                     engaged, which is the whole objective missing.
        #                     ⚠️ This pin CHANGED MEANING on 2026-08-31: it used to
        #                     read "more would mean the retry cadence became
        #                     reachable (it is not, with firmware attached)". The
        #                     cadence IS reachable now — see the entry header.
        #   where MOT_PWR     the same run carries FC_BUS/BT_BUS rings; without the
        #                     `where` pin a foreign event could satisfy the band by
        #                     accident. (Kept from the 2026-08-30c tightening,
        #                     which introduced it on the outcome-B ring.)
        #   over_absmax == 0  no ring above the 20 V abs-max: this scenario must
        #                     exercise the foldback WITHOUT producing the Death-5
        #                     boost-kill signature. Measured over_absmax False on
        #                     the cut ring at every swept substep count.
        #
        # i_cut BAND [6.15, 6.55] A — DERIVED FROM LIVE RUNS, 2026-08-31.
        # Three live board runs under this stimulus (fw v23, HIL build,
        # HIL Results/HIL Results/scp_band_rederive_{1,2,3}.csv.events.jsonl)
        # ⚠️ RE-ANCHORED FOR THE ASYMMETRY ERA (2026-09-02): the two
        # 2026-09-02 campaigns measure i_cut = 6.362274641096594 A, again
        # BIT-EXACT across both. The band is unchanged — it contains both era
        # values with margin — and the 6.3797373 A below is the PRE-ASYMMETRY
        # record, kept for the provenance of the band's derivation.
        # measured i_cut = 6.3797373 A BIT-IDENTICAL across all three — the cut
        # value is set by the deterministic substep sequence and does not jitter
        # with host phase, which is itself a validation of the redesign. The band
        # brackets the headless substep-count sweep envelope (6.256-6.398 A over
        # n_sub 8-100, implementer bench 2026-08-31) with ~0.1 A of margin on
        # each side, and still rejects the retired outcome-B approach-ring class
        # (3.5-5.5 A) and any low-current spurious cut.
        # History: the band shipped provisional at [5.5, 6.7] for a few hours
        # because the FEASIBILITY bench's rig had reproduced 5.79-5.88 A — that
        # figure is now attributed to that rig's own bring-up emulation (it also
        # could not reproduce the old stimulus's live 6.285-6.290 A); the
        # implementer's fuller harness and the live board agree.
        # NOTE the cut TIME varies legitimately: ~0.102 s on a fresh boot,
        # ~0.602 s when a prior run's latch makes the fw v23 recovery debounce
        # (500 ms) precede the bring-up. Nothing here pins the time.
        "events_require": [
            {"kind": "scp_cut", "where": {"switch": "MOT_PWR"}, "count": 1,
             "field": "i_cut", "min_value": 6.15, "max_value": 6.55},
        ],
        # (`provisional_note` deleted 2026-08-31 same-day: the band above is now
        # measured, not provisional. The mechanism stays available for future
        # not-yet-derived thresholds — see the events_require judge loop.)
        "events_forbid_over_absmax": True,
    },
    "bringup": {
        # L2 (2026-08-30): this scenario's WHOLE POINT is that the staged bring-up
        # completes against the real RT1987 delays, and until now it asserted that
        # only NEGATIVELY — "no fault appeared" — which a board that never left
        # State 0 also satisfies. `survive_to` is the positive form: at t = 4.0 the
        # board must be un-latched AND in Idle (or Run).
        #
        # t = 4.0 is derived, not round: fw v22+ HIL auto bring-up completes at
        # ~0.62 s measured (HIL_RECOVER_DEBOUNCE_MS + ~0.12 s of staging,
        # HIL_FINDINGS "bringup"), and the probe must land after WARM_RESET_GRACE_S
        # (2.0 s) because `state_at_survive` is only collected on post-grace rows
        # (analyze_scenario_csv). 4.0 is ~6x the measured completion and 2 s clear
        # of the grace bound, inside the trimmed 8 s duration.
        #
        # STATES {1, 2}: unattended this scenario has no pi_timeline and no ems, so
        # the board settles in Idle (1). Run (2) is admitted because the scenario is
        # also the one an operator drives by hand, and reaching Run is a STRONGER
        # demonstration that bring-up completed, not a weaker one.
        #
        # NO `require`, and `allow_only` stated EXPLICITLY rather than left to the
        # default: with no `require` the default resolves to FAULT_ERROR alone,
        # which is the same value — writing it out means a future reader does not
        # have to re-derive that "clean" is what is being asserted.
        #
        # KNOWN TRADE-OFF, accepted: having ANY entry here moves this scenario from
        # judge_scenario()'s `else` branch to its `if expect is not None` branch, so
        # it loses the --pi-live PI_TIMEOUT excusal (an operator Pi that drives the
        # board to Run and then stops commanding would now fail it rather than be
        # excused). That is the table's existing contract — every scenario with an
        # expectations entry already forgoes that excusal — and the positive
        # bring-up assertion is worth more than an excusal for a Pi behaviour this
        # scenario does not script.
        "source": "SCENARIOS['bringup'] — 'from dark: the firmware's staged "
                  "bring-up (P0-P3) against the real RT1987 t_D(ON) + soft-start "
                  "delays'. Measured completion ~0.62 s (HIL_FINDINGS 'bringup'/"
                  "'comm-loss'); the probe at t = 4.0 s is ~6x that and 2 s clear "
                  "of WARM_RESET_GRACE_S.",
        "allow_only": FAULT_ERROR,
        "survive_to": {"t": 4.0, "states": {1, 2}},
    },
}


# ═════════════════════════════════════════════════════════════════════════════
# ems-y-*  —  the firmware's own 'Y' combined profile, driven from the EMS layer
#
# FOUR ENTRIES, GENERATED FROM THE PROFILE'S OWN GEOMETRY.  Every window below
# is expressed as an offset from a REGION BOUNDARY of the imported
# COMBINED_PROFILE table, never as a literal second: the table is a verbatim
# copy of teensy_controller.ino:3162-3179, and a firmware-side region-duration
# edit reconciled into hil_plant_sim.py must move these windows with it. Writing
# "22.2" here would silently survive that edit and then measure the wrong region.
#
# WHY EVERY ASSERTION IS POSITIVE.  "No fault" is satisfied by a run that idles
# for 49 s. These four scenarios each name a specific thing the profile is for,
# and assert it from the trace:
#   b30 (bounded share, +Y_AUX_LOAD_A preload) — CLOSED-LOOP SHARE TRACKING.
#       The share axis reaches its clip, sweeps back down, the motor axis
#       reaches its own peak, and the BOARD moves current onto FC in response.
#   b00 (unbounded share, no preload)          — CUT-AND-RESTORE TOPOLOGY.
#       The same two axis assertions PLUS four switch assertions: BT_BUS cut at
#       the hi bound and RESTORED after it, FC_BUS cut at the lo bound and
#       RESTORED after it. The two RESTORE assertions are novel coverage —
#       nothing in this suite has ever checked that updateShareSetpointCutoff()
#       releases a latch, only that it takes one (handoff-sag asserts the cut
#       and then perturbs; it never comes back).
#
# SOURCE for all four: teensy_controller.ino:3162-3179 (the region table),
# :7806-7836 (advanceComboRegion(), the walk these windows are read off),
# PLAN.md Sec 9h; the load and margin derivations are at Y_AUX_LOAD_A in
# hil_plant_sim.py.

def _y_region_bounds():
    """[(t_start_abs, t_end_abs)] for every COMBINED_PROFILE region, in the
    scenario's own time base (the table starts at EMS_Y_START_S)."""
    out, t = [], float(EMS_Y_START_S)
    for row in COMBINED_PROFILE:
        dur = row[0] / 1000.0
        out.append((t, t + dur))
        t += dur
    return out


_YR = _y_region_bounds()
# The regions each window reads, named so the offsets below are checkable:
#   R3  share steps to 0.65 at a 0.6*Vmax hold      (13.0-16.0 s)
#   R4  BOTH axes ramp, v up / s down               (16.0-20.0 s)
#   R6  share steps to the HI bound (1.00), brief   (22.0-23.5 s)
#   R7  share steps back to 0.35, then v ramps to Vmax (23.5-27.0 s)
#   R10 share ramps down to the LO bound (0.00)     (32.0-35.0 s)
#   R11 lo-bound check, share held at 0.00, brief   (35.0-36.5 s)
#   R12 share steps back up to 0.50                 (36.5-38.0 s)
#   R13 v steps down, share stays 0.50              (38.0-40.0 s)
# Windows are INSET from the boundaries they straddle by EDGE_S, so the 20 ms
# command staircase and the board's own reaction latency cannot decide a check.
_Y_EDGE_S = 0.2
_Y_HI_BOUND_W = (_YR[6][0] + _Y_EDGE_S, _YR[6][1] - _Y_EDGE_S)     # 22.2-23.3
_Y_SWEEP_DOWN_W = (_YR[10][0], _YR[11][0] + 0.9)                   # 32.0-35.9
_Y_V_PEAK_W = (_YR[7][1] - 0.5, _YR[7][1])                         # 26.5-27.0
_Y_FC_BIAS_W = (_YR[3][0], _YR[3][1])                              # 13.0-16.0
_Y_BT_RESTORE_W = (_YR[7][0] + 0.5, _YR[7][1])                     # 24.0-27.0
_Y_LO_BOUND_W = (_YR[10][1] - 0.4, _YR[11][1] - 0.2)               # 34.6-36.3
_Y_FC_RESTORE_W = (_YR[12][0] + 0.5, _YR[13][0] + 1.0)             # 37.0-39.0
# Survive to the end of the table's last MOVING region (R14, the coast-down)
# rather than to the run's end: the trailing hold proves nothing and the
# import-time assert wants a bound strictly inside the duration anyway.
_Y_SURVIVE_T = _YR[14][1]                                          # 43.0

# Per-variant I_fc floors for the b30 closed-loop check, over _Y_FC_BIAS_W.
#
# ⚠️ WINDOW NARROWED 2026-08-31 (DI-MED-2): (13.0, 20.0) -> R3 ALONE
# (13.0, 16.0), and the floors RE-DERIVED FROM MEASURED DATA with it.
# R3 holds v constant at 0.6*Vmax with share commanded 0.65, so within it the
# only thing that moves I_fc is the share command — which is what the check
# claims to prove. The old window also swallowed R4, where BOTH axes ramp
# (v up, share DOWN): the load rises fast enough there that a 0.50 split alone
# reaches 0.4915 A / 0.9217 A, ABOVE the Vmax-1 floor and above any Vmax-3
# floor the true run could carry — so over (13, 20) the "above the 0.50-split"
# claim below was not literally true. Confined to R3 it is.
#
# MEASURED, campaign 20260831_191509 (ems-y-b30-v1 / -v3, hifi), over R3:
#
#                 peak I_fc    peak 0.50-split   floor    below   above
#                 (true run)   (same window)     here     peak    split
#     Vmax 1      0.5659 A     0.4353 A          0.50     11.6 %  14.9 %
#     Vmax 3      0.7606 A     0.5850 A          0.66     13.2 %  12.8 %
#
# Each floor is placed at the geometric mean of the pair it separates, so the
# margin against a false PASS (a run that ignored the command) and against a
# false FAIL (the true run) are balanced. The previous pair (0.58 / 0.80) was
# MODELLED at Y_AUX_LOAD_A 0.85 A and reads ABOVE the true run's own R3 peaks —
# it survived only because the old window included R4's ramp. The model
# over-predicts these currents by ~15-20 %; the measured numbers supersede it.
#
# A campaign that misses this should move Y_AUX_LOAD_A (which moves the totals)
# or the profile, NEVER this floor: lowering it to go green redefines "biased
# toward FC" as "not quite 50/50", and the split column above is the bound.
#
# ⚠️ RE-DERIVED 2026-08-31 (campaign 20260831_222036) — the FIRST campaign at
# Y_AUX_LOAD_A 0.85 A, i.e. the first whose b30 numbers are the shipped
# stimulus's.  The pair above (0.50 / 0.66) was fitted to campaign
# 20260831_191509, which ran the RETIRED 0.60 A preload; against the 0.85 A
# stimulus it is loose by ~30 %.  MEASURED over R3, campaign 20260831_222036:
#
#                 peak I_fc    floor here    margin below the peak
#     Vmax 1      0.7289 A     0.65          10.9 %
#     Vmax 3      0.9243 A     0.85           8.9 %
#
# The margins are deliberately tighter than the 191509 pair's ~12-15 %: with
# the share_act band added below, THIS check is no longer the only thing
# asserting the share bias, so it can afford to be a real regression tripwire
# on the current magnitude rather than a wide sanity bound.  The same rule
# still applies — a campaign that misses this moves the LOAD or the profile,
# never the floor.
#
# ⚠️ PROVISIONAL / NEEDS RE-DERIVATION (reviewer H1, 2026-09-01): both pins
# above (and the "R3 peak" measurements they are fitted to, campaigns
# 20260831_222036 and 20260831_191509) predate the WP-C regen-fidelity fix,
# and `ems-y-b30-*` IS regen-affected (see the H1 enumeration in
# FAULT_EXPECTATIONS above). Do NOT change the numeric values on this basis
# alone — re-derive them from the first post-WP-C campaign's own R3 peaks.
_Y_FC_FLOOR = {1.0: 0.65, 3.0: 0.85}

# ── b30 share-clip bands, campaign 20260831_222036 ──────────────────────────
# The b30 pair exists to prove the runtime clip [b, 1-b] is DELIVERED, and
# until this campaign nothing asserted the delivered value: `fc_current_biased`
# asserts an AMPERE floor, which moves with the load and cannot distinguish
# "the share loop delivered 0.70" from "the bus drew more".
#
# MEASURED share_act = I_fc / (I_fc + I_batt) — the delivered split, derived
# from the CSV's own current columns via the `ratio_of` value source:
#     hi window (region 6, share commanded 1.00 -> clipped to 0.70)
#         b30-v1  0.69985 .. 0.70027      b30-v3  0.69991 .. 0.70012
#     lo window (regions 10/11, 0.00 -> clipped to 0.30)
#         b30-v1  0.29986 .. 0.30016      b30-v3  0.29996 .. 0.30004
# Both bounds are DELIVERED EXACTLY, both variants — so the band is +/-0.005
# around each clip level, ~12x the widest observed excursion (0.00027) and
# still an order of magnitude inside the 0.40 gap between the two clip levels.
#
# ⚠️ PEAK-BASED, like every value bound in this table: `min_value` and
# `max_value` both test the in-window MAXIMUM, so the pair asserts that the
# maximum LANDED in the band. A run that reached the clip and then collapsed is
# not caught by these two (the b30 entry's other checks and the fault gate
# cover that); a run that never reached the clip, or overshot it, is.
_Y_SHARE_CLIP_TOL = 0.005
# Y_AUX_LOAD_A must keep the SOURCE TOTAL above the firmware's closed-loop
# governor gate (SHARE_MINORITY_I_MIN_A 0.30 A on each side => break-even
# I_tot 1.000 A at the 0.70/0.30 clip), or the governor re-engages and clips
# the delivered share BEFORE the setpoint latch does — silently turning the
# bands above into assertions about the governor instead.
# MEASURED, campaign 20260831_222036, over the hi window: I_tot 1.0644 A min
# (b30-v1, the tighter variant — only 6.4 % of headroom) and 1.1837 A (b30-v3).
# The 1.02 A floor sits 2 % above break-even and 4.2 % under the v1 minimum, so
# a preload cut below ~1.0 A fails HERE, loudly, instead of quietly re-routing
# what the share bands are measuring.
#
# ⚠️ NOW ON BOTH b30 VARIANTS (2026-09-01, campaign 20260901_000816 fix queue
# item 4 — SYMMETRY).  The check originally ran on b30-v1 alone, on the
# argument that one tripwire on the tighter of two variants sharing one
# Y_AUX_LOAD_A is enough to catch a preload cut.  That argument holds for a cut
# in the SHARED constant and fails for anything that moves the two variants
# apart — a per-variant load change, a Vmax retune shifting the motor's own
# contribution, or a governor change biting at one speed and not the other.
# The v3 variant's own minimum was MEASURED at 1.1836 A across both campaigns
# (bit-stable), which clears the same 1.02 A floor by 16.0 % (against v1's
# 4.4 %), so the ONE floor is honest on both and no second constant is needed:
# the floor is derived from the GOVERNOR's break-even (2 * SHARE_MINORITY_I_MIN_A
# / (1 - b) = 1.000 A at the 0.70/0.30 clip), which is a property of the clip
# and not of Vmax.  The two variants differ only in how much margin they carry
# over it, and both margins are now stated rather than one being assumed.
_Y_ITOT_FLOOR_A = 1.02
# The MEASURED per-variant minima over the hi window, campaigns 20260831_222036
# and 20260901_000816 (bit-stable across both).  Carried as data so the margin
# each variant actually has is in the check's own detail line rather than only
# in a ledger.
_Y_ITOT_MEASURED_MIN_A = {1.0: 1.0644, 3.0: 1.1836}

for _vmax, _b in ((1.0, 0.30), (3.0, 0.30), (1.0, 0.00), (3.0, 0.00)):
    _n = "ems-y-b%02d-v%g" % (round(_b * 100), _vmax)
    # The share clip level the hi-bound region actually reaches: 1 - b.
    _hi = 1.0 - _b
    _sig = [
        # 1. The share axis REACHED ITS CLIP. Region 6 commands 1.00 and the
        #    runtime clip is [b, 1-b], so the observed ceiling is 1-b exactly.
        #    The floor is set 1 mLSB under it rather than at it: the command
        #    round-trips through a float32 UDP field.
        {"name": "share_hi_clip", "column": "cmd_share_sp",
         "min_value": _hi - 0.001, "t_window": _Y_HI_BOUND_W,
         "label": "the share axis reached its high clip (%.2f) in region 6"
                  % _hi},
        # 2. ... and SWEPT BACK DOWN. Region 10 ramps 0.65 -> 0.00 at the
        #    normal slope and then FLATTENS at the clip (the intended kink,
        #    .ino:7830-7835), so the realised fall is 0.65 - b: 0.35 at b=0.30
        #    and 0.65 at b=0.00. 0.30 is a floor under BOTH, so one threshold
        #    covers both bands and neither is knife-edged.
        {"name": "share_swept_down", "column": "cmd_share_sp",
         "strictly_decreases_by": 0.30, "t_window": _Y_SWEEP_DOWN_W,
         "label": "the share axis swept down to its low clip across region 10"},
        # 3. The MOTOR axis reached its own peak. Region 7 ramps 0.3 -> 1.0 of
        #    Vmax; a region's END value is never emitted (the walk's tau is in
        #    [0,1)), so the last commanded value inside the window is
        #    ~0.996*Vmax at 50 Hz. 0.95*Vmax is a floor clear of that and of
        #    any 20 ms staircase effect.
        {"name": "v_axis_swept", "column": "cmd_v_sp",
         "min_value": 0.95 * _vmax, "t_window": _Y_V_PEAK_W,
         "label": "the motor axis reached %.2f m/s (0.95*Vmax) at the region-7 "
                  "ramp top" % (0.95 * _vmax)},
    ]
    if _b:
        # 4 (b30 only). ... and the BOARD ACTED on the share command.
        # cmd_share_sp is only what the host asked for; I_fc is what the
        # firmware's share loop delivered. Only meaningful with the preload
        # holding the source total above the 0.60 A governor gate — which is
        # exactly why the b00 variants, which carry no preload and run the
        # share loop open-loop, do NOT get this check.
        _sig.append(
            #    L3 (review 2026-08-31) — WHAT A PASS ACTUALLY PROVES. The
            #    plant splits the bus current in proportion to the MDAC CODE
            #    RATIO (HIL_PLANT.md §4.7: sign- and monotonicity-preserving,
            #    WRONG GAIN), so this floor asserts the firmware->MDAC
            #    arithmetic — that the board read the command, moved the codes
            #    the right way, and moved them far enough. It is NOT share-loop
            #    GAIN validation: the amps here are the model's response to the
            #    codes, not the board's real droop chain (see also the
            #    K_DROOP_BUS design-vs-measured x4 finding).
            {"name": "fc_current_biased", "column": "I_fc",
             "min_value": _Y_FC_FLOOR[_vmax], "t_window": _Y_FC_BIAS_W,
             "label": "the board's share loop moved current onto FC beyond the "
                      "nominal split (>= %.2f A)" % _Y_FC_FLOOR[_vmax]})
        # 5-8 (b30 only). THE CLIP LEVELS, DELIVERED — see _Y_SHARE_CLIP_TOL.
        # These are what `fc_current_biased` cannot say: a RATIO is invariant
        # to the load, so it separates "the share loop delivered 0.70" from
        # "the bus drew more current at a 0.50 split".
        _sig += [
            {"name": "share_hi_delivered", "ratio_of": ["I_fc", "I_batt"],
             "min_value": _hi - _Y_SHARE_CLIP_TOL, "t_window": _Y_HI_BOUND_W,
             "label": "the DELIVERED share reached the high clip (%.2f) in "
                      "region 6" % _hi},
            {"name": "share_hi_not_overshot", "ratio_of": ["I_fc", "I_batt"],
             "max_value": _hi + _Y_SHARE_CLIP_TOL, "t_window": _Y_HI_BOUND_W,
             "label": "... and did not exceed it — the runtime clip held at "
                      "%.2f, not the commanded 1.00" % _hi},
            {"name": "share_lo_delivered", "ratio_of": ["I_fc", "I_batt"],
             "max_value": _b + _Y_SHARE_CLIP_TOL, "t_window": _Y_LO_BOUND_W,
             "label": "the DELIVERED share came down to the low clip (%.2f) in "
                      "regions 10/11" % _b},
            {"name": "share_lo_not_undershot", "ratio_of": ["I_fc", "I_batt"],
             "min_value": _b - _Y_SHARE_CLIP_TOL, "t_window": _Y_LO_BOUND_W,
             "label": "... and did not go under it — the runtime clip held at "
                      "%.2f, not the commanded 0.00" % _b},
        ]
        # 9 (BOTH b30 variants since 2026-09-01). THE PRELOAD BUDGET — see
        # _Y_ITOT_FLOOR_A for the derivation and for why the symmetry argument
        # replaced the old "one tripwire on the tighter variant" one.
        _sig.append(
            {"name": "itot_above_governor_break_even",
             "sum_of": ["I_fc", "I_batt"],
             "min_value": _Y_ITOT_FLOOR_A, "t_window": _Y_HI_BOUND_W,
             "label": "the source total stayed above the closed-loop "
                      "governor's break-even (>= %.2f A; this variant "
                      "measured %.4f A, %.1f %% of margin), so the share "
                      "bands above measure the setpoint clip and not the "
                      "governor"
                      % (_Y_ITOT_FLOOR_A, _Y_ITOT_MEASURED_MIN_A[_vmax],
                         100.0 * (_Y_ITOT_MEASURED_MIN_A[_vmax]
                                  / _Y_ITOT_FLOOR_A - 1.0))})
    if _b and _vmax == 3.0:
        # 10-11 (b30-v3 ONLY). THE fw v26 CURRENT CEILING, ON A REGISTERED
        # STIMULUS.
        #
        # ⚠️ THIS IS THE ONLY REGISTERED SCENARIO THE CLAMP REACHES, and the
        # fw v26 tools round shipped saying no registered scenario did. That
        # claim was written from the EMS legs alone and against the RAW total;
        # `tools/probes/probe_fw26_clamp_reachability.py` reconstructs the
        # governor's own filtered total and minority clip from a campaign CSV
        # and finds b30-v3 over the ceiling. RECONSTRUCTED, both campaigns of
        # 2026-09-02, on fw v25 traces:
        #
        #     campaign      filtered I_tot   commanded I_fc   ticks   window
        #     C (041414)        2.3355 A        1.5180 A        11    27.020-27.029
        #     B (011926)        2.3343 A        1.5173 A         9    27.007-27.015
        #
        # The next-highest run on the whole registered set is `ems-sdp` at a
        # commanded 1.1861 A, 5.1 % under the ceiling.
        #
        # THE BAND IS DELIBERATELY WIDE. The reconstruction is open-loop: on
        # fw v26 the clamp moves the delivered share, which moves I_fc and
        # I_batt, which moves the filtered total the clamp is evaluated on. The
        # duration is therefore a prediction and the check asserts the
        # MECHANISM (it engaged at all, and it did not latch on) rather than the
        # count. Re-derive the band from the first fw v26 campaign.
        #
        # NO h2 BAND MOVES FOR THIS. The leg carries no h2 anchor -- its checks
        # are share, current and switch bounds -- and it has no offline walk at
        # all (`ems-y-b30-v3` defines no `ems_v_profile`, so `ems_walk` refuses
        # it; the stimulus is the firmware's own COMBINED_PROFILE). The size of
        # what the clamp withholds is stated instead: 0.268 A of bus-side fuel
        # cell for 11 ms, 2.9 mC, worth 9.7e-07 g of hydrogen -- about 77 ppm of
        # a typical EMS leg's total, and above the ~50 ppm same-config
        # repeatability floor, so it would be visible if this leg had an anchor.
        _Y_CEIL_W = (_YR[8][0] - 0.2, _YR[8][0] + 0.4)             # 26.8-27.4
        _sig += [
            {"name": "fw26_ceiling_engaged", "aux_bit": "fc_ceiling_active",
             "min_ticks": 1, "t_window": _Y_CEIL_W,
             "label": "the fw v26 FC current ceiling BOUND at the region-7/8 "
                      "boundary (reconstruction: 9-11 ticks at a commanded "
                      "1.517-1.518 A against the 1.25 A ceiling; MEASURED 12 "
                      "ticks at t = 27.009-27.020 s in campaign "
                      "20260902_220604 and 13 in campaign E "
                      "20260903_031220) - the only registered EMS stimulus "
                      "that reaches the clamp"},
            {"name": "fw26_ceiling_transient", "aux_bit": "fc_ceiling_active",
             "max_ticks": 60, "t_window": _Y_CEIL_W,
             "label": "... and released again inside the window (<= 60 ticks; "
                      "the reconstruction gives 9-11 and the two live "
                      "engagements MEASURED 12 (campaign 20260902_220604) and "
                      "13 (campaign E), so the band stands as "
                      "written on two readings; a clamp that latches on is a "
                      "hysteresis defect, not a load reading)"},
        ]
    if not _b:
        # 4-7 (b00 only). THE CUT-AND-RESTORE TOPOLOGY, both directions and
        # both channels. Region 6 commands share 1.00, above DROOP_R_MAX 0.85,
        # so updateShareSetpointCutoff() (.ino:9231-9257) drives BT_BUS_ENABLE
        # LOW; region 7 returns to 0.35, inside the band, and it must come
        # back. Regions 10/11 do the mirror image to FC_BUS_ENABLE at
        # DROOP_R_MIN 0.15, and region 12's step to 0.50 must restore it.
        #
        # TICK BUDGETS, at the CSV's 1 kHz row rate:
        #   cut windows are ~1.1 s and ~1.7 s -> max_ticks 100 (0.1 s) allows
        #     the handful of samples around the transition without admitting a
        #     run where the cut never happened or was re-closed;
        #   restore windows are 3.0 s and 2.0 s -> min_ticks 2000 / 1000, i.e.
        #     two thirds and one half of the window, so a late release still
        #     passes but an absent one cannot.
        _sig += [
            {"name": "bt_bus_cut", "switch_bit": SW_BT_BUS, "max_ticks": 100,
             "t_window": _Y_HI_BOUND_W,
             "label": "BT_BUS_ENABLE cut by the share setpoint latch at the "
                      "high bound (region 6)"},
            {"name": "bt_bus_restored", "switch_bit": SW_BT_BUS,
             "min_ticks": 2000, "t_window": _Y_BT_RESTORE_W,
             "label": "BT_BUS_ENABLE RESTORED once the share returned inside "
                      "[DROOP_R_MIN, DROOP_R_MAX] (region 7)"},
            {"name": "fc_bus_cut", "switch_bit": SW_FC_BUS, "max_ticks": 100,
             "t_window": _Y_LO_BOUND_W,
             "label": "FC_BUS_ENABLE cut by the share setpoint latch at the "
                      "low bound (regions 10/11)"},
            {"name": "fc_bus_restored", "switch_bit": SW_FC_BUS,
             "min_ticks": 1000, "t_window": _Y_FC_RESTORE_W,
             "label": "FC_BUS_ENABLE RESTORED once the share stepped back to "
                      "0.50 (regions 12/13)"},
        ]
    FAULT_EXPECTATIONS[_n] = {
        "source": ("teensy_controller.ino:3162-3179 (COMBINED_PROFILE, copied "
                   "verbatim into hil_plant_sim.COMBINED_PROFILE) + :7806-7836 "
                   "(advanceComboRegion) + PLAN.md Sec 9h; load and margin "
                   "derivations at hil_plant_sim.Y_AUX_LOAD_A. Windows are "
                   "DERIVED from the imported region table, not literals."),
        # Fault-free is the expectation for BOTH bands. The b00 variants take
        # a source off the bus twice, but at their own (unpreloaded) load — the
        # totals span 0.150-1.407 A — so no channel approaches LIMIT_I_FC_MAX
        # 1.4 A or LIMIT_I_BT_MAX 3.0 A even single-sourced, and the bus never
        # approaches LIMIT_V_BUS_MIN.  The b30 variants carry Y_AUX_LOAD_A on
        # top: at 0.85 A their worst channel currents are 0.999 A on FC (28.7 %
        # under the limit) and 1.475 A on BT (51 % under), so fault-free is the
        # expectation there too — derivation at Y_AUX_LOAD_A.
        #
        # ⚠️ b30 STIMULUS CHANGED 2026-08-31 (Y_AUX_LOAD_A 0.60 -> 0.85 A, to
        # make the hi bound deliverable at all).  b30 currents, governor rails
        # and the _Y_FC_FLOOR pair below all moved with it, so b30 results from
        # campaign 20260831_191509 and earlier are NOT comparable with later
        # ones.  b00 carries no preload and is unaffected.
        #
        # ⚠️ BASELINE-ERA / NEEDS RE-DERIVATION (reviewer H1, 2026-09-01): this
        # scenario IS regen-affected (see the H1 enumeration above — it brakes
        # to -12 A for 328-971 ticks past the -1.5 A clip). Every threshold in
        # `_sig` above (the share/motor axis windows, `_Y_FC_FLOOR`,
        # `_Y_ITOT_FLOOR_A`/`_Y_ITOT_MEASURED_MIN_A`, the cut/restore tick
        # budgets) was measured on campaigns that predate the WP-C
        # regen-fidelity fix. Re-derive all of them from the first post-WP-C
        # campaign before trusting a marginal PASS/FAIL here.
        "allow_only": 0,
        "survive_to": {"t": _Y_SURVIVE_T, "states": {2, 3}},
        "signals_require": _sig,
        "provisional_note": ("baseline-era thresholds (pre-WP-C regen-fidelity "
                             "fix) — re-derive after the first post-WP-C "
                             "campaign; this scenario brakes past the regen "
                             "clip (reviewer H1, 2026-09-01)"
                             + (". The two fw26_ceiling_* checks are "
                                "RECONSTRUCTED from fw v25 traces (probe "
                                "tools/probes/probe_fw26_clamp_reachability.py)"
                                ", never measured on fw v26: the clamp is "
                                "closed-loop, so its duration on the board is "
                                "a prediction. Re-derive the tick band from "
                                "the first fw v26 campaign."
                                if (_b and _vmax == 3.0) else "")),
    }
del _vmax, _b, _n, _hi, _sig


# ═════════════════════════════════════════════════════════════════════════════
# ems-ftp75-*  —  the EPA FTP-75 study segment (raw t = 0..340 s inclusive,
#                 341 samples at 1 Hz)
#
# GATED behind --with-ftp75 (build_plan()): 350 s each, ~11.7 min for the pair
# on a campaign that is otherwise ~34 min. Rendered SKIPPED by default with a
# reason, the same mechanism `drive`'s operator_required skip uses.
#
# ALL BUDGETS BELOW are the Plant/droop model's currents over the emitted
# profile (hil_plant_sim.FTP75_PRELOAD_A carries the derivation and the
# measurement command); they are MODELLED, not measured on hardware.
_FTP_PEAK_W = (240.0, 250.0)      # the cycle peak, emitted t = 245.0 s
# Deep inside Run (the strategies hand back MODE_SAFE at t = 346.0) and well
# past the peak, so this asserts the run actually got through the cycle's
# hardest part rather than merely starting it.
_FTP_SURVIVE_T = 300.0
# h2_cum_g is monotone, so a peak IS the final value.
#
# ── MEASURED (campaign 20260831_191509), replacing the modelled predictions ──
# The block used to quote the model's 5.46e-2 g (hold-5050) / 8.19e-2 g
# (soc-band) and assert a single 5e-3 g floor against them — a ~11x margin that
# only ever said "the column is not absent, zero or frozen". The campaign
# measured:
#       ems-ftp75-5050      6.47e-2 g      (model 5.46e-2, +18.5 %)
#       ems-ftp75-socband   9.16e-2 g      (model 8.19e-2, +11.8 %)
# Both above the model in the same direction, consistent with the +2.6 %
# current-budget offset recorded at FTP75_PRELOAD_A plus the share bias sitting
# at its ceiling for longer than the steady-state walk assumes. The measured
# numbers are now the reference; the modelled ones are superseded.
#
# ⚠️ TWO SPECS PER BAND, NOT ONE. `min_value` and `max_value` are evaluated by a
# chain of `if ... return` in _judge_signal_leaf(), and `min_value` is tested
# FIRST — so a single spec carrying both keys silently drops the ceiling. Each
# band below is therefore written as a floor spec plus a separate ceiling spec.
#
# ⚠️ Gfc MODEL ESTIMATE, unchanged: the map is scale-portable, the stack is NOT
# identified against this rig (TODO(calibrate) — the H2Consumption banner in
# hil_plant_sim.py). A band on this column asserts that the accounting ran AND
# that it landed where two campaigns of the same model say it should; it is not
# a claim about grams of real hydrogen.
#
# ⚠️ RE-DERIVED 2026-09-01 FOR THE ZERO-PRELOAD ERA, AND PROVISIONAL.
# Removing FTP75_PRELOAD_A takes ~0.65 A x ~16 V x ~340 s of bus energy out of
# the cycle, roughly half of it off the fuel-cell channel at the 0.50 split, so
# every h2 total on these scenarios falls by a factor of order two.  The bands
# below come from tools/ems_walk.py, invoked as
#     C:/Users/ricky/miniforge3/python.exe -c "import sys; sys.path.insert(
#         0,'tools'); import ems_walk as W;
#         print(W.walk('<strategy>','<scenario>',governor=True).summary())"
# and the walk is TRUSTED HERE because it was validated against the era it
# replaces: re-run at the OLD preloads it reproduces campaign 20260901_151156
# to within 1.8 % on every leg (5050 0.064918 g vs 0.0647 measured; socband
# 0.091559 vs 0.09159; sdp 0.061096 vs 0.0622; flip 196.0 s vs 198.537 s).
# Each band is the walk's prediction +/-25 %, i.e. ~14x that demonstrated
# disagreement — wide on purpose for a first campaign, and narrow enough that a
# factor-of-two scale or accumulation error still fails.
#
# LAST PRELOADED-ERA VALUES, for the record (campaign hil_report_20260901_
# 151156, the baseline-era boundary): 5050 0.0647 g / dSoC -0.02648; socband
# 0.09159 / -0.01533; sdp 0.0622 / -0.01845; dp 0.09291 / -0.01478.  Do not
# compare any of those with a post-2026-09-01 total.
#
# ── PART C (C1 round, 2026-09-01): TWO ERA BOUNDARIES, NOT ONE ────────────
# Every band in this block now carries BOTH of the boundaries that separate
# it from the campaign record, and campaign 20260901_151156 is the last
# campaign on the far side of both:
#   1. THE PRELOAD boundary (operator ruling 2026-09-01): aux_preload_a
#      0.65/0.45 -> 0.0. This is the one the block already carried.
#   2. THE ASYMMETRY boundary (the C1 round, PART A): the plant's converter
#      asymmetry is DEFAULT-ON from this round, so the FC chain regulates
#      DeltaV0 = +0.0444 V high and over-delivers current at every load. The
#      bands below are therefore walked with `dv0_v=0.0444`, which is the
#      walk's own static law for the same effect.
# A run from either side of either boundary is not comparable with a band
# here. Do NOT quote a pre-2026-09-01 total against one.
#
# ⚠️ RE-WALKED AT THE M2 CONSISTENT PAIR (fix round F1, 2026-09-01). The first
# cut of these bands was walked at dv0 = 0.0444, the M1 value the plant no
# longer injects.
#
# HOW THE WALK IS DRIVEN, stated because it is not exact. `ems_walk.py` takes a
# `dv0_v` and has NO rho: its static law is M1's, so it cannot represent the
# droop-ratio half of the M2 pair at all. The walks below therefore use the
# dv0 that REPRODUCES THE PLANT'S OWN alpha at the calibration point --
# r = 0.5, I_tot = 1.0155 A, where the hi-fi engine delivers alpha = 0.5248 --
# which is dv0_eff = (alpha - 0.5)*k_d*I_tot/0.25 = 0.030223 V. RESIDUAL: the
# two laws agree exactly at that point and diverge away from it, because M1's
# term goes as 1/I_tot while the plant's rho contribution is flat in I_tot.
# Over the FTP-75's 0.15-0.96 A span the walk therefore OVER-states the
# asymmetry at light load and under-states it at heavy load. That error is
# inside the +/-25 % band by a wide margin and is not worth a second walker;
# it is recorded so nobody reads the walk as the plant.
#
# WALK DELTAS, symmetric -> M2-equivalent (Gfc plant accounting, governor=True,
# the shipped registry):
#   ems-ftp75-5050    0.028090 -> 0.029888 g  (+6.40 %), dSoC -0.011355 -> -0.010629
#   ems-ftp75-socband 0.035562 -> 0.036706 g  (+3.22 %), dSoC -0.008177 -> -0.007716
#   ems-ftp75-sdp     0.019347 -> 0.019918 g  (+2.95 %), dSoC -0.014922 -> -0.014691
#   ems-ftp75-dp      0.035889 -> 0.037441 g  (+4.32 %), dSoC -0.008180 -> -0.007555
# The direction is the one the asymmetry predicts: the FC chain carries more
# of every load, so more hydrogen is burned and the pack is drained less. The
# magnitudes are ROUGHLY TWO THIRDS of the M1-era figures this block first
# carried (+9.40 / +4.53 / +4.40 / +6.35 %), because the M2 partition puts most
# of the mismatch in the droop ratio, which is the weaker hydrogen lever.
#
# hold-5050: M2-equivalent walk 0.029888 g / dSoC -0.010629 -> [0.022, 0.037].
# ⚠️ CHARGER ERA (WP-1C, 2026-09-02) — UNCHANGED, by construction rather than
# by tolerance: the governor walk on this scenario opens ZERO charge windows,
# so no term in its hydrogen total passes through the charger and the 1:1 and
# 0.88 eras give bit-identical totals (verified: 0.028089711 g symmetric,
# both eras). The same holds for `ems-ftp75-sdp`, `ems-ftp75-dp`,
# `ems-dp-replay` and `ems-sdp`.
# ⚠️ RE-WALKED FOR THE LOSS-MAP AND BLEED ERA (2026-09-02) AND HELD. The
# same M2-equivalent walk with `loss_map=hil_plant_sim.plant_loss_map()` reads
# 0.029807 g / dSoC -0.010612, i.e. -0.27 % on the hydrogen, and +/-25 % of
# that is [0.022355, 0.037259] -> [0.022, 0.037] at this rounding. The band is
# therefore UNCHANGED, and it is unchanged because the walk moved by a quarter
# of a percent against a band that is 50 % wide, not because it was not
# re-derived.
# ⚠️ THE BOARD IS PREDICTED TO MOVE FURTHER THAN THE WALK DID, and in the
# other direction: the per-node bleed removes a static load the sources were
# carrying on every tick, worth about -2.9 % of h2 on a 340 s cycle (computed
# from campaign 20260902_041414's own bleed integral). That is still well
# inside the band. Re-derive both from the first bleed-era campaign.
# ⚠️ RE-PINNED ON THE BOARD (2026-09-03, campaign hil_report_20260902_220604 —
# the first bleed-era campaign). MEASURED h2 0.0290697451 g against the
# asymmetry era's 0.0299327016 (-2.88 %, against a predicted -2.9 %: the walk's
# bleed prediction is confirmed to a tenth of a percent). The band is now +-25 %
# of the MEASUREMENT rather than of the walk: [0.0218, 0.0363]. It is narrower
# than the walk-derived pair on the ceiling side because the walk's own
# hydrogen sat 2.7 % above the board's; the shape (+-25 %, a scale and
# accumulation tripwire rather than a model tolerance) is unchanged.
_FTP_H2_BAND_5050 = (0.0218, 0.0363)
# soc-band: a TWO-SIDED band, [0.070, 0.115] around the measured 9.159e-2
# (-24 % / +26 %, the same shape as the 5050 band above).
#
# ⚠️ THE ASYMMETRY IS RETIRED (operator ruling, 2026-09-01), and the floor is
# now applied. It was held at a conservative 5e-3 ("the accounting ran") for ONE
# reason: `ems-ftp75-socband` ALLOWED OC_FC, an OC_FC latch STOPS the run
# (State 99, cycle unfinished, h2_cum_g frozen where it got to), and a latch at
# t = 200 leaves ~4e-2 g — so a 0.070 floor would have failed a run for doing
# exactly what the entry said was correct. Retiring the allowance removes that
# outcome: the run now always reaches t = 345 and the total is always the whole
# cycle's, which is precisely the precondition the 5050 band relies on.
#
# MEASURED BASIS: 9.159e-2 g, BIT-IDENTICAL across all six campaigns that have
# run this scenario (REPORT.md rows, 20260831_191509 through 20260901_080905).
# A quantity that repeats to five significant figures over six runs supports a
# +/-25 % band comfortably; the band is deliberately no tighter, because it is a
# scale/accumulation tripwire on the metric, not a tolerance on the model.
_FTP_H2_PROVISIONAL = _BLEED_ERA_PROVISIONAL + ". " + (
    "first zero-preload campaign (aux_preload_a 0.65/0.45 -> 0.0, operator "
    "ruling 2026-09-01) AND first ETA_CHG 0.88 charger era (WP-1C, "
    "2026-09-02); the band is a governor-walk prediction +/-25 %, not a "
    "measurement — re-derive it from the first campaign that runs it. Only "
    "the `socband` leg's band actually moved: every other FTP-75 leg walks "
    "zero charge windows and is eta-invariant by construction")
_FTP_H2_FLOOR = 5.0e-3          # the 5050 variant's own conservative floor
# soc-band: PART C (C1 round, 2026-09-01) — THE WALK FIGURES HERE WERE STALE.
# The 0.035456 g / dSoC -0.008358 pair this block used to quote predates the
# `chg_i_ceiling_a` 0.8 key the same round added to this scenario, and the
# "reported zero windows" claim went with it. Re-run against the SHIPPED
# registry (miniforge, governor=True):
#   symmetric   (dv0 0.0):      0.035562 g plant / 0.036381 physical, dSoC -0.008177
#   M2-equivalent (dv0 0.030223): 0.036706 g plant / 0.037526 physical, dSoC -0.007716
# (the retired M1-era walk at dv0 0.0444 gave 0.037208 plant / -0.007513)
# and the walk now reports TWO CHARGE WINDOWS, not zero:
#   191.700 .. 194.000 s  and  329.200 .. 330.000 s   (3.1 s in total)
# ⚠️ THOSE WINDOWS ARE THE DP MASK'S SCHEDULE, NOT THE STRATEGY'S. ems_walk.py
# gates charge admission on gen_dp_ems_table.charge_mask() (the DP's cruise +
# FC-budget test), never on SocBandStrategy's own enter/hold hysteresis, so
# the walk says WHETHER a window is admissible under the mask and says nothing
# about when the strategy would open one. The band is unaffected either way —
# 3.1 s of charging at the 0.8 A ceiling is ~0.3 % of the cycle's total — but
# the schedule must not be quoted as a prediction of the board's.
#
# BAND: M2-equivalent walk 0.036706 g +/-25 % -> [0.028, 0.046], the same shape
# as the 5050 band above.  PROVISIONAL.
#
# ⚠️ ONE EXTRA SOURCE OF SPREAD HERE, stated: the preload removal re-opens
# `soc-band`'s CHARGE branch on this cycle (source total 0.15 A at idle against
# SOC_BAND_CHARGE_ENTER_ITOT_A 0.60 A), and the walk's mask-driven schedule
# above is not the strategy's own.  Charging raises the fuel-cell draw while it
# runs, so the realized total may sit ABOVE the walk's figure.  The +25 %
# ceiling is the allowance for that; if the first campaign lands over it, the
# finding is the charge schedule and the fix is this band, not the scenario.
#
# CONTRACT-LOW (2026-09-01): the ceiling is stated as +25 % and IS +25 %.
# The retired pair was 0.026/0.045 against a 0.035456 walk, i.e. -26.7 %/
# +26.9 % — the numbers and the description had drifted apart. Both bounds
# below are computed from the walk rather than rounded to a nicer figure.
# ⚠️ RE-DERIVED FOR THE CHARGER ERA (WP-1C, 2026-09-02) — 0.028/0.046 ->
# 0.031/0.052, and the round found a SECOND defect in the retired pair while
# re-deriving it.
#
# 1. WHICH WALK FIGURE THE BAND IS AGAINST. `ems_walk.py` prints two totals:
#    `h2 (Gfc, physical)`, which bills the fuel cell for the charger's own bus
#    draw, and `h2 (Gfc, plant)`, which omits it (the dataclass field says so:
#    "the same, omitting the charger's own draw"). The live `h2_cum_g` column
#    integrates Gfc over the FC power the board actually draws, and the
#    charger's draw is ON that bus — so `physical` is the live column's
#    analogue and `plant` is a diagnostic. The retired pair was computed from
#    `plant` (0.046 = 1.25 x 0.036706). EVIDENCE, not preference: on the 61 s
#    cycle the frontier's measured vs-reference ratio was 0.9003 x (campaign
#    20260901_151156); the physical-walk prediction is 0.859 x and the
#    plant-walk prediction 1.127 x. Only one of those is in the same country as
#    the measurement.
# 2. WHAT ETA_CHG DID. Governor walk on `ems-ftp75-socband` at the
#    M2-equivalent dv0 0.030223, 1:1 era vs 0.88 era:
#      physical  0.037526 -> 0.041873 g  (+11.6 %)   <- the live analogue
#      plant     0.036706 -> 0.036807 g  (+0.28 %)   <- the diagnostic
#      dSoC     -0.007716 -> -0.006306
#      charge windows  2 -> 3
#    The total RISES on this leg, which is the opposite of the direction the
#    WP-1A review predicted for a charging leg, and the mechanism is that the
#    strategy CHARGES MORE: cheaper charging opens a third window and buys
#    0.0014 more SoC for the extra hydrogen. A leg whose charge SCHEDULE is
#    fixed (`ems-ftp75-5050`, both DP legs, both SDP legs — all zero-window)
#    does not move at all.
# 3. THE BAND. Walk +/-25 % on the physical figure gave [0.0314, 0.0523] ->
#    [0.031, 0.052].
# 4. RE-DERIVED FROM THE BOARD (2026-09-02, campaign hil_report_20260902_011926
#    — the first eta-era, zero-preload run of this leg, and the first campaign
#    in which it ever charged). MEASURED h2_cum_g = 0.042427323 g, against the
#    walk's 0.041873 (+1.3 %: the walk's own prediction is confirmed; the
#    +15.6 % figure in the ledger is against the STALE 0.03671 plant-basis
#    walk). The band tightens from the walk's +/-25 % to +/-20 % around the
#    MEASUREMENT: [0.033942, 0.050913] -> [0.034, 0.051]. Five charge windows,
#    42.726 s, 30.608 C (+0.00170 SoC) are inside that number, so a campaign
#    whose charge schedule collapses now fails the floor instead of passing it.
# 5. ⚠️ BLEED ERA (2026-09-02, the DP-bound round) — THE BAND IS HELD AND IS
#    THE LEAST TRUSTWORTHY IN THIS FILE UNTIL THE NEXT CAMPAIGN. It is +/-20 %
#    around a MEASUREMENT (0.042427 g) taken at the uniform 2 kOhm node bleed.
#    Two things move it, in opposite directions and by different amounts:
#      * the loss-map re-walk reads 0.041936 g against the pre-round 0.041873,
#        i.e. +0.15 %, which is a change of DEMAND MODEL and not a prediction
#        of the board;
#      * the per-node bleed removes a static load the sources carried on every
#        tick, worth about -2.9 % of h2 on this cycle.
#    Applying the second alone would recentre the band on ~0.041197 g and give
#    [0.033, 0.049]. It is NOT applied, deliberately: shifting a band that is
#    anchored on a measurement onto a prediction of that measurement trades a
#    known basis for an unknown one, and -2.9 % is a seventh of the band's own
#    half-width. The first bleed-era campaign that runs this leg RE-PINS it
#    from its own h2_cum_g, and until then a reading in the lower half of the
#    band is expected rather than a finding.
# 6. ⚠️ RE-PINNED ON THE BOARD (2026-09-03, campaign hil_report_20260902_220604,
#    the first bleed-era campaign to run this leg). MEASURED h2 0.0407628763 g
#    against the asymmetry era's 0.0423184751 (-3.68 %, which is the -2.9 %
#    bleed prediction plus this leg's own charge schedule). The band returns to
#    +-20 % of a MEASUREMENT, which is what item 5 above was waiting for:
#    [0.0326, 0.0489]. The "lower half of the band is expected" caveat is
#    RETIRED with it -- the band is centred again.
_FTP_H2_FLOOR_SOCBAND = 0.0326
_FTP_H2_CEILING_SOCBAND = 0.0489

FAULT_EXPECTATIONS["ems-ftp75-5050"] = {
    "source": ("hil_plant_sim.py SCENARIOS['ems-ftp75-5050'] + the generated "
               "tools/ftp75_profile.py (EPA ftpcol.txt, sha256-verified, first "
               "340 s per references/Systemic_Scaling_of_Powertrain_Models_"
               "with_Youla_Driver_Control.pdf) + the FTP75_PRELOAD_A budget."),
    # FAULT-FREE IS THE EXPECTATION, and the budget says it should be with far
    # more room than it used to: at FTP75_PRELOAD_A = 0.0 (2026-09-01) the
    # model's peak source total is 0.9603 A at t = 243.9, so hold-5050's fixed
    # 0.50 split puts 0.4801 A on a channel — 66 % under LIMIT_I_FC_MAX 1.4 A,
    # against the 42 % the 0.65 A preload left. The only way to spend that
    # margin is a drive-controller rail (MOTOR_I_CMD_MAX 12 A) AT high speed,
    # which maps to ~2.02 A of bus current at 3.0 m/s; this cycle's high-speed
    # segment is a PLATEAU (56.6 -> 56.7 mph), so the loop does not rail there,
    # and its sharp transitions are all at low speed where a rail costs little
    # bus current. If a campaign latches OC_FC here, the finding is that
    # coincidence — and the fix is NOT to reinstate the preload.
    #
    # ⚠️ THE SHARE LOOP IS NO LONGER CLOSED FOR THE WHOLE CYCLE, and every
    # check below is read in that light. The firmware runs OPEN-LOOP HOLD below
    # 2*SHARE_MINORITY_I_MIN_A - SHARE_GOV_OL_HYST_A = 0.55 A of source total,
    # and 64.5 % of this cycle's Run window sits under that line at preload 0.
    # The governor walk (tools/ems_walk.py, governor=True) apportions the run
    # open_hold 9.71 % / open_feedforward 57.12 % / closed 33.17 % of ticks,
    # against open_hold 0.00 % / closed 98.25 % at 0.65 A. Per the standing
    # walk rule, a check on this scenario must state the firmware mode of the
    # segment it lands in; the checks below are all placed in the cycle's PEAK
    # (t = 240..250 s, source total 0.9347..0.9603 A — closed loop) or are
    # whole-run accumulations that do not depend on the mode.
    "allow_only": 0,
    "survive_to": {"t": _FTP_SURVIVE_T, "states": {2}},
    "signals_require": [
        # 1. The CYCLE actually ran to its peak. The profile is scaled so the
        #    56.7 mph maximum lands on exactly 3.0 m/s at emitted t = 245.0;
        #    2.85 is 0.95 of that, clear of the 20 ms command staircase, and
        #    unreachable by any other part of the cycle.
        {"name": "ftp_peak_commanded", "column": "cmd_v_sp", "min_value": 2.85,
         "t_window": _FTP_PEAK_W,
         "label": "the FTP-75 peak (3.0 m/s at t = 245 s) was commanded"},
        # 2. ... and the BOARD carried the load at the commanded split.
        #    ⚠️ RE-DERIVED AT PRELOAD 0, PROVISIONAL. The model's peak source
        #    total is 0.9603 A, so the 0.50 split delivers 0.4801 A; on the
        #    measured ADDITIVE composition (I_AUX_A 0.15 + the cycle's own
        #    measured 0.8546 A peak) it is 0.5023 A. A 0.40 A floor sits 20 %
        #    under the modelled value and 6.7x above the ~0.06 A a 0.50 split
        #    of the 0.15 A standstill total gives, so an idling run that merely
        #    reached t = 245 still cannot satisfy it. The window is the cycle
        #    peak, where the source total is 0.9347..0.9603 A and the share
        #    loop is CLOSED — the one place on this cycle where a current floor
        #    can be read as a share-tracking statement at all.
        {"name": "ftp_fc_carried", "column": "I_fc", "min_value": 0.40,
         "provisional_note": "first zero-preload campaign; the 0.40 A floor is "
                             "a governor-walk prediction (0.4801 A model / "
                             "0.5023 A on the measured composition) — re-derive "
                             "it from the first campaign that runs it",
         "t_window": _FTP_PEAK_W,
         "label": "the FC channel carried its half of the peak load "
                  "(>= 0.40 A; model 0.4801 A at preload 0)"},
        # 3-4. The H2 metric ran end to end over a 345 s cycle — the longest
        #    accounting run in the suite, and the reason these scenarios exist —
        #    AND landed in its measured band. Two specs, because one spec cannot
        #    carry both bounds (see _FTP_H2_BAND_5050).
        {"name": "ftp_h2_accounted", "column": "h2_cum_g",
         "min_value": _FTP_H2_BAND_5050[0],
         "provisional_note": _FTP_H2_PROVISIONAL,
         "label": "the H2 consumption metric accumulated over the cycle "
                  "(>= %.3f g; governor walk 2.809e-2 at preload 0, against "
                  "6.47e-2 in the retired 0.65 A era)" % _FTP_H2_BAND_5050[0]},
        {"name": "ftp_h2_bounded", "column": "h2_cum_g",
         "max_value": _FTP_H2_BAND_5050[1],
         "provisional_note": _FTP_H2_PROVISIONAL,
         "label": "... and stayed under %.3f g — a ceiling the walk's 2.809e-2 "
                  "clears by 25 %%, so a scale or accumulation error in the "
                  "metric fails here instead of being read as a result"
                  % _FTP_H2_BAND_5050[1]},
    ],
}

FAULT_EXPECTATIONS["ems-ftp75-socband"] = {
    "source": ("hil_plant_sim.py SCENARIOS['ems-ftp75-socband'] + the "
               "SocBandStrategy docstring and SOC_BAND_* constants + the "
               "FTP75_PRELOAD_A budget. OC_FC allowance per OPERATOR RULING "
               "(b) 2026-08-30 (single-source FC operation is a design "
               "boundary, not a defect)."),
    # ── THE OC_FC ALLOWANCE IS RETIRED (operator ruling, 2026-09-01) ────────
    # WHAT IT SAID: soc-band biases the split toward the fuel cell as the SoC
    # deficit grows, saturating at SOC_BAND_SHARE_NOMINAL + SOC_BAND_SHARE_SPAN
    # = 0.75. At the cycle peak the model's source total is 1.613 A, so a 0.75
    # split is 1.210 A — 14 % under LIMIT_I_FC_MAX 1.4 A, against a 42 % margin
    # on the 5050 variant. A drive transient near the peak could spend that
    # margin, and the resulting OC_FC would be the CORRECT hardware response to
    # a single-channel overload rather than a defect.
    #
    # WHY IT GOES: the allowance was a hedge against an outcome that has never
    # occurred. SIX campaigns have run this scenario and the allowance went
    # UNUSED in every one; the peak I_fc is 1.2413 A, holding the 14 % margin
    # the derivation predicts rather than eroding it. An allowance nothing has
    # ever exercised is not protection, it is a hole: it silently excused the
    # ONE fault this scenario is most likely to produce, and it forced the h2
    # floor down to a vacuous 5e-3 (see _FTP_H2_FLOOR_SOCBAND).
    #
    # THE MECHANISM IS UNCHANGED AND SO IS THE RULING. Operator ruling (b) —
    # single-source FC operation is a design boundary, not a defect — still
    # stands, and `charge-cruise` still REQUIRES OC_FC under it. What changed is
    # only that this scenario is not the place to hedge: its budget says
    # fault-free, its record says fault-free, and if a campaign latches OC_FC
    # here the finding is a budget one (FTP75_PRELOAD_A, or the peak margin
    # eroding) and deserves to be SEEN rather than absorbed.
    #
    # ⚠️ THE CHARGE BRANCH IS BACK IN REACH (2026-09-01, the preload removal),
    # and the previous statement here — "out of reach by construction, nothing
    # here asserts one" — is RETIRED. `soc-band` admits a charge window below
    # SOC_BAND_CHARGE_ENTER_ITOT_A = 0.60 A of source total; FTP75_PRELOAD_A
    # used to put the floor at 0.800 A, and now puts it at I_AUX_A = 0.15 A.
    # 64.5 % of this cycle's Run window sits under the 0.55 A open-loop line,
    # so the admission condition is met over most of the cycle and this
    # scenario exercises BOTH of the policy's branches for the first time.
    # A charge-window check is added below (`socband_ftp_charge_opened`).
    #
    # ⚠️ WHAT THIS DOES TO THE OC_FC ARGUMENT: nothing that widens it. Charging
    # adds fuel-cell draw, but it is admitted only in the LOW-current segments
    # (below 0.60 A of source total) and capped at `chg_i_ceiling_a` 0.8 A,
    # which the entry now declares in lockstep with its siblings. The cycle
    # PEAK — where the OC margin is decided — is far above the admission gate,
    # so no charge window can be open there.
    #
    # ⚠️ THE SHARE LOOP IS NO LONGER CLOSED THROUGHOUT, per the standing walk
    # rule: governor walk at preload 0 gives open_hold 9.71 % /
    # open_feedforward 57.12 % / closed 33.17 % of ticks. Every current check
    # below is placed where the loop is CLOSED (the cycle peak) or is a
    # whole-window peak test that a closed segment supplies.
    #
    # B-L1 (2026-09-01): `allow_only` is 0, not FAULT_ERROR. The retirement
    # above removed the OC_FC bit but left the FAULT_ERROR umbrella behind,
    # which excused the "latched State 99" companion bit that triggerFault()
    # ORs onto EVERY latch — so any fault at all still passed silently. 0 is
    # what the 16 sibling fault-free entries carry and what the reasoning above
    # actually concludes.
    "allow_only": 0,
    "survive_to": {"t": _FTP_SURVIVE_T, "states": {2, 3}},
    "signals_require": [
        # 1. The policy ACTUALLY BIASED the split. Nominal is 0.50 and the
        #    ceiling is 0.75; 0.60 is unreachable without the SoC leaving the
        #    +/-SOC_BAND_HALF band, and unmistakable once it does. The window
        #    opens at t = 120. ⚠️ RE-DERIVED AT PRELOAD 0: the walk puts the command at a
        #    flat 0.50 until t = 78.4 s and at the 0.75 ceiling from t = 111.5 s
        #    (against t = 46.8 s measured at 0.65 A — the smaller load
        #    discharges the pack more slowly, so the deficit opens later). The
        #    window therefore OPENS AT t = 120, not 30: at 30 s the bias has
        #    provably not started and the check would fail a correct board.
        #    120 s is 7.6 % past the walk's saturation instant.
        {"name": "socband_share_biased", "column": "cmd_share_sp",
         "min_value": 0.60, "t_window": (120.0, 340.0),
         "provisional_note": "first zero-preload campaign; the window opening "
                             "is the governor walk's 111.5 s saturation instant "
                             "+7.6 % — re-derive it from the first campaign "
                             "that runs it",
         "label": "soc-band commanded a share bias toward the fuel cell "
                  "(walk: ceiling reached at t = 111.5 s at preload 0)"},
        # 2. ... and the BOARD acted on it.
        #    ⚠️ RE-DERIVED 2026-08-31 (ledger, "check derivation"): 0.55 -> 0.70.
        #    THE OLD DERIVATION WAS WRONG, and its arithmetic ignored the
        #    governor.  It read: "at the model's 0.800 A standstill total a 0.75
        #    split is 0.600 A and a 0.50 split is 0.400 A, so 0.55 A separates
        #    the two even in the cycle's idle segments".  It does not.  At
        #    I_tot = 0.800 A the firmware's minority-current governor clips the
        #    share to [SHARE_MINORITY_I_MIN_A/I_tot, 1 - SHARE_MINORITY_I_MIN_A/
        #    I_tot] = [0.375, 0.625], so a COMMANDED 0.75 DELIVERS 0.625 x 0.800
        #    = 0.500 A, not 0.600 A — and campaign 20260831_191509 measured the
        #    idle governed value at 0.516 A.  The old floor was therefore
        #    UNREACHABLE in exactly the segments it claimed to cover; the check
        #    only ever passed on moving ones, which nobody had written down.
        #
        #    ⚠️ RE-DERIVED AGAIN 2026-08-31 (DI-MED-1): 0.70 -> 0.95, and the
        #    discrimination claim restated in the terms the check is actually
        #    evaluated in.  `min_value` is a PEAK-over-window test: the run
        #    passes if ANY sample in (30, 340) clears the floor, so what the
        #    floor has to separate is the WINDOW PEAK of a commanding run from
        #    the WINDOW PEAK of a run that ignored the share command — not the
        #    two values at some chosen instant.  The old 0.70 could not do that.
        #
        #    NEW ARITHMETIC (campaign 20260831_191509, both FTP-75 runs; the
        #    ems-ftp75-5050 sibling IS the "ignored the command" control — same
        #    profile, same FTP75_PRELOAD_A, share held at a constant 0.50):
        #      ems-ftp75-5050    peak I_fc over (30, 340) = 0.8275 A @ t = 244.0
        #      ems-ftp75-socband peak I_fc over (30, 340) = 1.2414 A @ t = 244.0
        #    Any floor <= 0.8275 A is therefore satisfied by the 0.50 control
        #    and discriminates NOTHING.  0.95 A sits 15 % above the control peak
        #    and 23 % below the measured socband peak, so it cannot be reached
        #    without the share bias and is not knife-edged against it either.
        #    STILL DELIBERATELY NOT TIED TO A PEAK-ONLY WINDOW: an OC_FC latch
        #    is allowed here, and the window opens at t = 30, so a run that
        #    legitimately latched after clearing the floor still passes.  What
        #    the check does NOT claim is coverage of the idle segments; under
        #    the governor no floor above 0.516 A can have that, and pretending
        #    otherwise is what the previous correction removed.
        #    L3 (review 2026-08-31) — WHAT A PASS ACTUALLY PROVES. The
        #    plant splits the bus current in proportion to the MDAC CODE
        #    RATIO (HIL_PLANT.md §4.7: sign- and monotonicity-preserving,
        #    WRONG GAIN), so this floor asserts the firmware->MDAC
        #    arithmetic — that the board read the command, moved the codes
        #    the right way, and moved them far enough. It is NOT share-loop
        #    GAIN validation: the amps here are the model's response to the
        #    codes, not the board's real droop chain (see also the
        #    K_DROOP_BUS design-vs-measured x4 finding).
        #    ⚠️ RE-DERIVED AT PRELOAD 0 (2026-09-01), PROVISIONAL: 0.95 -> 0.56.
        #    The derivation SHAPE is unchanged — the floor must sit between the
        #    constant-0.50 sibling's window peak (the "ignored the command"
        #    control) and this scenario's own — and both moved with the load.
        #    Governor walk over t = (30, 340), model currents:
        #      ems-ftp75-5050    peak I_fc = 0.4801 A  (was 0.8275 measured)
        #      ems-ftp75-socband peak I_fc = 0.6602 A  (was 1.2414 measured)
        #    Both peaks land at the cycle peak, where the loop is CLOSED.
        #    0.56 A sits 16.6 % above the control and 15.2 % below this
        #    scenario's own prediction — the most symmetric split the two
        #    numbers allow, and still 2.3x wider than the walk's 1.8 %
        #    demonstrated error.
        #    ⚠️ RE-POINTED AT THE CHARGE-FREE PEAK (2026-09-02, fix-queue item
        #    5). Campaign 20260902_011926 passed this floor on a CONTAMINATED
        #    peak: the window maximum was 1.1370 A inside a charge window, which
        #    clears 0.56 A without the share loop having done anything. The
        #    discriminator only means what it says on charge-free ticks — where
        #    the measured peak is 0.6929 A against the constant-0.50 sibling's
        #    0.4967 A, a clean margin of 0.13 A over the control rather than the
        #    0.58 A the contaminated reading suggested. The FLOOR stays at 0.56
        #    (measured 0.6929, control 0.4967: it still sits between them).
        #    ⚠️ SETTLING HOLD ADDED (2026-09-02, review H1). The 0.6929 A
        #    calibration figure was computed WITH a post-close guard; the spec
        #    first shipped without one, so this floor was passing on a
        #    still-decaying 0.8628 A sample rather than on a charge-free one.
        #    `exclude_hold_ms` 10 restores the number the floor was derived
        #    against (a >= 5 ms guard already recovers 0.6929 A exactly).
        {"name": "socband_fc_carried", "column": "I_fc", "min_value": 0.56,
         "t_window": (30.0, 340.0),
         "exclude_when_switch_bit": SW_FC_CHARGE, "exclude_hold_ms": 10.0,
         "provisional_note": "the floor is a governor-walk prediction the "
                             "first zero-preload campaign then confirmed on "
                             "charge-free ticks (0.6929 A vs the 0.4967 A "
                             "constant-0.50 control); the margin over the "
                             "control is 0.13 A, so re-derive it if either "
                             "peak moves",
         "label": "the board's share loop moved current onto FC beyond the "
                  "nominal split (charge-free window PEAK >= 0.56 A; measured "
                  "0.6929 A, and the constant-0.50 ems-ftp75-5050 control peaks "
                  "at 0.4967 A over the same window at preload 0, so nothing "
                  "below that discriminates). Charge-window ticks are excluded, "
                  "plus a 10 ms settling hold after each close: the charger's "
                  "own bus draw clears this floor without the share loop "
                  "moving at all, and the FC current needs ~10 ms to decay "
                  "once the branch closes"},
        # 2a. THE CEILING THE PRELOAD REMOVAL LEFT MISSING (PART C, C1 round,
        #    2026-09-01). At preload 0 NO upper bound on I_fc survives on this
        #    entry: the OC_FC allowance was retired and LIMIT_I_FC_MAX is a
        #    firmware limit rather than a check, so a share loop that ran the
        #    FC channel far past its commanded split would pass every check
        #    here. 0.85 A is ~1.3x the governor walk's 0.6602 A peak and 39 %
        #    under LIMIT_I_FC_MAX 1.4 A, so it is a REGRESSION TRIPWIRE on the
        #    operating point, not a limit claim.
        #    ⚠️ The asymmetric walk does NOT move this peak (0.6602 A at both
        #    dv0 = 0.0 and dv0 = 0.0444): the asymmetry raises the FC share in
        #    the mid-load segments, while the peak lands where the commanded
        #    share is already at its own ceiling.
        #    ⚠️ SPLIT INTO TWO ARMS (2026-09-02, campaign 20260902_011926
        #    fix-queue item 5). The single 0.85 A ceiling FAILED on a correct
        #    board the first time this leg ever charged: peak I_fc 1.1370 A at
        #    t = 117.013 s with switch 0x35 (BT_BUS LOW — the
        #    assertFcChargeEnable() exclusion, so FC is single-source), which
        #    decomposes to 4 dp as
        #        motor 0.4359 A  (p_mot 5.964 W / 13.6829 V)
        #      + aux   0.1500 A  (I_AUX_A)
        #      + charger bus draw 0.5293 A  (0.8 A x 7.9390 V / (0.88 x 13.6366 V)
        #                                    — the ETA_CHG 0.88 referral)
        #      + path/storage 0.0218 A
        #      = 1.1370 A.
        #    None of that is the share loop: excluding the charge windows, the
        #    peak over the same window is 0.6929 A, 18 % under the old ceiling.
        #    The two arms therefore answer the two questions separately.
        #
        #    ARM 1 — the SHARE-LOOP tripwire, charge windows masked out. The
        #    0.85 A bound is UNCHANGED (~1.3x the governor walk's 0.6602 A peak,
        #    39 % under LIMIT_I_FC_MAX 1.4 A); the measured charge-free peak
        #    0.6929 A leaves it 18 % of margin.
        #    ⚠️ The asymmetric walk does NOT move this peak (0.6602 A at both
        #    dv0 = 0.0 and dv0 = 0.0444): the asymmetry raises the FC share in
        #    the mid-load segments, while the peak lands where the commanded
        #    share is already at its own ceiling.
        #    ⚠️ SETTLING HOLD (2026-09-02, review H1). Without it this arm
        #    FALSE-FAILS a correct board: the FC current decays over ~10 ms
        #    after FC_CHARGE_ENABLE clears, and campaign 20260902_041414's
        #    first charge-free samples after 3 of 5 closes read 0.8628 A
        #    (t = 88.506), 0.8417 A (185.566) and 0.8258 A (323.899) — all above
        #    0.85 or within a percent of it, none of them a share-loop
        #    excursion. `exclude_hold_ms` 10 masks the decay tail; the resulting
        #    charge-free peak is the 0.6929 A the ceiling was sized against.
        {"name": "socband_fc_peak_bounded", "column": "I_fc",
         "max_value": 0.85, "t_window": (30.0, 340.0),
         "exclude_when_switch_bit": SW_FC_CHARGE, "exclude_hold_ms": 10.0,
         "label": "the FC channel stayed bounded across the cycle OUTSIDE the "
                  "charge windows (<= 0.85 A, ~1.3x the walk's 0.6602 A peak "
                  "and 39 %% under LIMIT_I_FC_MAX 1.4 A; measured charge-free "
                  "peak 0.6929 A) — a share-loop regression tripwire, not a "
                  "limit claim. Ticks with FC_CHARGE_ENABLE set are "
                  "excluded, plus the 10 ms decay tail after each close, and "
                  "are judged by `socband_fc_peak_charging` instead"},
        #    ARM 2 — the CHARGE-WINDOW ceiling, whole-window (the charge peak IS
        #    the window peak, so no mask is needed and none is used: a mask
        #    keeping ONLY charge ticks would make the arm vacuous on a run whose
        #    charge branch never opened, and `socband_ftp_charge_opened` is what
        #    asserts that it did).
        #    THE ARITHMETIC, from the terms above: motor 0.4359 + aux 0.1500 +
        #    charger bus 0.5293 = 1.1152 A of sourced draw, measured 1.1370 A
        #    with path/storage. 1.25 A is +9.9 % on that measurement and 10.7 %
        #    under LIMIT_I_FC_MAX 1.4 A — so it still catches an FC channel
        #    running away, while a charge window at the declared 0.8 A ceiling
        #    on a single source at DROOP_R_MIN passes.
        {"name": "socband_fc_peak_charging", "column": "I_fc",
         "max_value": 1.25, "t_window": (30.0, 340.0),
         "label": "the FC channel stayed bounded INCLUDING its charge windows "
                  "(<= 1.25 A; measured peak 1.1370 A = motor 0.4359 + aux "
                  "0.1500 + charger bus 0.5293 (0.8 A at eta 0.88, referred "
                  "through V_batt/V_bus) + path 0.0218, on a single FC source "
                  "at DROOP_R_MIN with BT_BUS excluded by "
                  "assertFcChargeEnable()) — 10.7 %% of headroom under "
                  "LIMIT_I_FC_MAX 1.4 A"},
        # 2b. THE RE-OPENED CHARGE BRANCH (new, 2026-09-01). The preload
        #    removal is what makes this assertable: the source total falls to
        #    I_AUX_A = 0.15 A in every idle segment, a factor of four under
        #    SOC_BAND_CHARGE_ENTER_ITOT_A = 0.60 A, so `soc-band`'s charging
        #    branch is admissible over most of the cycle for the first time.
        #    Without this check the branch is exercised and unobserved, which
        #    is the hole the preload removal exists to close.
        #    ⚠️ THE FLOOR IS DELIBERATELY WEAK AND IT IS SAID SO. The window
        #    SCHEDULE is UNMODELLED: ems_walk.py gates charge admission on
        #    gen_dp_ems_table.charge_mask() (the DP's cruise + FC-budget test),
        #    not on SocBandStrategy's own enter/hold hysteresis, so its two
        #    reported windows (191.7-194.0 s and 329.2-330.0 s, 3.1 s total)
        #    are the MASK's schedule and cannot be used to size a floor.
        #    ⚠️ PART C (C1 round, 2026-09-01): 3000 -> 200 TICKS. 3000 ticks =
        #    3.0 s is a 3.2 % margin under the walk's only model of the
        #    duration (3.1 s), which is not a floor at all — a CORRECT board
        #    opening ONE 2 s window would fail it, and the entry is not
        #    entitled to a duration claim it has no model for. 200 ticks =
        #    0.2 s = ten command periods at PI_CMD_HZ 50, which is long
        #    enough that a single dropped frame cannot satisfy it and short
        #    enough that any real window does.
        #    WHAT THE CHECK ASSERTS IS EXISTENCE. Admission needs BOTH an SoC
        #    deficit AND the strategy's trailing-window cruise test, and the
        #    walk models NEITHER of those — so the schedule, the count and the
        #    duration all stay unpredicted until a campaign measures them.
        {"name": "socband_ftp_charge_opened", "switch_bit": SW_FC_CHARGE,
         "min_ticks": 200, "t_window": (30.0, 340.0),
         "provisional_note": "EXISTENCE ONLY, first zero-preload campaign; the "
                             "charge-window schedule on this cycle is "
                             "unmodelled (ems_walk.py gates admission on the "
                             "DP mask, not on the strategy's hysteresis) — "
                             "re-derive the floor from the first measurement",
         "label": "the re-opened `soc-band` CHARGE branch reached the board — "
                  "FC_CHARGE_ENABLE open for >= 0.2 s across the cycle "
                  "(EXISTENCE only; admission needs an SoC deficit AND the "
                  "strategy's trailing-window cruise test, neither of which "
                  "the walk models. Unreachable before the 2026-09-01 "
                  "preload removal)"},
        # 3-4. The H2 metric ran end to end, and landed in its measured band.
        #    TWO-SIDED from 2026-09-01: retiring the OC_FC allowance above makes
        #    a truncated run an expectation FAILURE rather than an allowed
        #    outcome, so the floor no longer has to survive one and can finally
        #    say what it means. Two specs, because one spec cannot carry both
        #    bounds (the import guard refuses that pairing — _judge_signal_leaf
        #    tests min before max and would drop the ceiling silently).
        #    ⚠️ PART C (C1 round, 2026-09-01) — WHAT THESE TWO DO NOT DO.
        #    They are SCALE / ACCUMULATION tripwires on the metric and nothing
        #    more. They do not discriminate a degraded share loop: a board
        #    stuck at a constant 0.50 split produces 0.028090 g, which sits
        #    INSIDE this band and inside the 5050 band too. The share-loop
        #    discriminators on this entry are `socband_fc_carried` (and its
        #    new ceiling above); on the SDP sibling they are
        #    `sdpftp_fc_floored_early` and `sdpftp_h2_bounded`. The names
        #    DEVIATION from the review's literal fix (renaming the two checks
        #    `h2_scale_*`): the NAMES ARE KEPT. This file's own standing rule is
        #    that a check name is a cross-campaign identity -- see the
        #    `child_tx_healthy` note, where a check's meaning was changed
        #    outright and the name deliberately preserved "so campaign ledgers
        #    stay comparable". Six campaigns' REPORT.md rows carry
        #    `ftp_h2_accounted`/`ftp_h2_bounded`, and renaming them would break
        #    that comparability to fix a labelling problem the labels below now
        #    state outright.
        # MEASURED, no longer provisional (2026-09-02): campaign
        # hil_report_20260902_011926 ran this leg in the eta era at preload 0
        # and read 0.042427323 g. The band is +/-20 % on that, not +/-25 % on a
        # walk, so `_FTP_H2_PROVISIONAL` no longer applies to these two.
        {"name": "ftp_h2_accounted", "column": "h2_cum_g",
         "min_value": _FTP_H2_FLOOR_SOCBAND,
         "label": "the H2 consumption metric accumulated over the cycle "
                  "(>= %.3f g; MEASURED 0.042427 g in campaign 20260902_011926, "
                  "walk 0.041873). A SCALE/ACCUMULATION tripwire — it does not "
                  "discriminate a degraded share loop" % _FTP_H2_FLOOR_SOCBAND},
        {"name": "ftp_h2_bounded", "column": "h2_cum_g",
         "max_value": _FTP_H2_CEILING_SOCBAND,
         "label": "... and stayed under %.3f g — 20 %% above the measured "
                  "0.042427 g, so a scale or accumulation error in the metric "
                  "fails here instead of being read as a result (a "
                  "constant-0.50 board passes this band: see "
                  "`socband_fc_carried`)"
                  % _FTP_H2_CEILING_SOCBAND},
    ],
}


# ═════════════════════════════════════════════════════════════════════════════
# THE THREE SDP-INTERIOR SCENARIOS (2026-08-31)
#
# WHAT THEY ARE FOR, in one paragraph.  Every `ems-sdp` run before this round
# started EXACTLY on the policy's target node and could only discharge, so the
# bang-bang table sat on its fuel-cell branch and the wire carried ONE constant
# clamped 0.8500 for the whole run.  The three scenarios below use the new
# `sdp_soc_ref_offset` scenario key (SdpStrategy.set_soc_ref_offset()) to place
# the run's starting SoC on a CHOSEN side of the switching node, so the
# policy's own decision surfaces become observable:
#   ems-ftp75-sdp    starts ABOVE the node on the 340 s FTP-75 cycle: the wire
#                    carries the battery-heavy branch (0.15) for ~200 s, then
#                    ONE sharp step to 0.85 as the cycle's drain crosses the
#                    boundary.  Pure share axis — no charge stage is reachable.
#   ems-sdp-cross    starts ABOVE the node at a LOW-DEMAND operating point: the
#                    same downward share crossing, then the CHARGE threshold's
#                    minimum-dwell limit cycle.
#   ems-sdp-braking  starts BELOW the node: the share is pinned at 0.85 all run
#                    BY DESIGN, so every charge transition is attributable to
#                    the DEMAND axis — charging on each low-speed plateau, off
#                    on each cruise.
#
# ⚠️ ALL THREE ARE NOW CALIBRATED — campaign 20260901_024231, the first campaign
# to run them.  Every threshold below was re-derived against that campaign's
# measured trace and the `provisional_note` on all three entries was DELETED
# (the ems-sdp and scp-inrush precedent).  Each moved bound carries its measured
# value and the campaign id in place.  What the walks got right and wrong, since
# it decides how much to trust the next one:
#   * ems-ftp75-sdp   flip 195.9 walked vs 198.537 measured (+1.35 %).
#   * ems-sdp-braking DEMAND-driven windows, so they land on the profile's own
#                     instants: 50.1 s walked vs 52.479 s measured (+4.7 %),
#                     four windows of four, zero cruise ticks, five early drops.
#   * ems-sdp-cross   the ONE FAILURE. Flip 43.85 walked vs 42.292 measured
#                     (-3.5 %), but the CHARGE LIMIT CYCLE's period was walked
#                     at ~52 s against a measured 16.13 s — wrong by 5.7x,
#                     because the walk applied the closed-loop minority governor
#                     at an operating point the firmware runs in OPEN-LOOP HOLD.
#                     Root cause and the standing lesson for anyone writing a
#                     walk: the strategy-authoring note in hil_plant_sim.py.
# THE STRUCTURAL LESSON, and it now has its own check kind: the failing check
# asserted the ABSENCE of a window at a MODELLED INSTANT.  Phase-locked absence
# assertions fail correct boards whenever the walk's period is wrong; prefer
# `max_continuous_ticks` / `edge_count_between` (see the signals_require kind
# table) which bound the same property without claiming to know the phase.
# The walks use the gen_dp_ems_table.py reduced
# demand model — the same model the DP benchmark is solved against — and the
# ems-ftp75-sdp one is additionally cross-checked against the MEASURED
# `ems-ftp75-5050` trace of campaign 20260901_000816, which runs +2.6 % hot
# against the model (the documented FTP75_PRELOAD_A gain offset).
#
# ⚠️ AND ONE STRUCTURAL FINDING THEY ENCODE: an UPWARD share crossing is not
# attempted on this rig.  Raising SoC through the 1e-3-wide dead band around
# the target node inside one SDP_CHG_MIN_DWELL_S latch needs a PACK-SIDE charge
# ceiling above 2.25 A.  ⚠️ The "immediate OC_FC" this note used to assert is a
# SIMULATOR-referencing statement: the sim's charger takes the same number of
# amps from the bus as it puts into the pack (it does not conserve power), so
# 2.25 A reads straight against the bus-side LIMIT_I_FC_MAX 1.4 A.  On hardware
# the Ag105 converts — 2.25 A into a 2S pack is a bus-side draw nearer 1.25 A —
# so the real margin is on the order of 10-15 %, not the factor the sim shows.
# Nothing below asserts a return to the battery-heavy branch.  A future retune
# that wants one must re-derive the HARDWARE-side current budget first (see the
# referencing note at the ems-sdp-cross block in hil_plant_sim.py); it is a
# narrow exclusion, not an impossible one.
# ═════════════════════════════════════════════════════════════════════════════

# The share command's two emitted levels, and the bands around them.  ONE
# source for all three entries: the clamp is SOC_BAND_SHARE_MIN/MAX (0.15/0.85)
# and both values are exactly representable through the float32 UDP round trip,
# so +/-0.01 is pure margin rather than a rounding allowance.
# Shared PROVISIONAL note for every `ems-ftp75-sdp` threshold re-derived at
# aux_preload_a = 0.0 (operator ruling 2026-09-01).  Every one of them is a
# governor-walk prediction; no campaign has run this scenario at preload 0.
_SDPFTP_PROVISIONAL = (
    "first zero-preload campaign (aux_preload_a 0.45 -> 0.0, operator "
    "ruling 2026-09-01); the bound is a governor-walk prediction, not a "
    "measurement — re-derive it from the first campaign that runs it. "
    "ETA_CHG 0.88 (WP-1C, 2026-09-02) does NOT move any bound on this entry: "
    "the artifact declines charging endogenously, so the walk opens zero "
    "charge windows and its totals are bit-identical across the two charger "
    "eras (verified for the sdp_policy_v4 artifact this scenario rebinds to)")
_SDP_LOW_RAIL_CEIL = 0.16       # "the battery-heavy branch, sustained"
_SDP_HIGH_RAIL_FLOOR = 0.84     # "the fuel-cell branch was reached"
# The RAW (pre-clamp) table request on each branch.  0.00 above the node;
# 1.00 below it, except 0.95 in demand bins 22-23 and 0.90 in DEMAND BIN 24,
# the top bin of the [0, 25] W consumer map.
#
# ⚠️ THE FLOOR IS 0.89, NOT 0.94, AND BIN 24 IS THE WHOLE REASON.  The earlier
# 0.94 was written as "separates the branches whatever bin the run is in",
# which is not true of bin 24: that bin's raw request IS 0.90 and would fail a
# 0.94 floor.  The exposure is not hypothetical — the FTP-75 walk's peak demand
# is only ~4 % below the bin-24 lower edge (22.4 W model, ~23.0 W at the
# measured +2.6 % offset, against a 24.0 W edge), so a model error well inside
# this entry's own +/-20 % sensitivity band puts a sample in bin 24.  0.89
# clears every value the FUEL-CELL branch can request (0.90 / 0.95 / 1.00) and
# is still 0.88 above the battery branch's 0.00, so the two branches remain
# separated by nearly the whole axis.  The 0.00 side keeps its 0.01 ceiling and
# is a value NO other scenario in this suite can put on the wire.
_SDP_RAW_LOW_CEIL = 0.01
_SDP_RAW_HIGH_FLOOR = 0.89

FAULT_EXPECTATIONS["ems-ftp75-sdp"] = {
    "source": ("hil_plant_sim.py SCENARIOS['ems-ftp75-sdp'] and its offline "
               "walk (the FTP75_SDP_* constants carry the full derivation: "
               "flip time and its +/-10 %/+/-20 % drain sensitivity, both "
               "branches' governed currents, and the 2026-09-01 removal of "
               "the preload that once made this leg's stimulus differ from "
               "its siblings') + "
               "SdpStrategy.set_soc_ref_offset() for what the offset does + "
               "the PLAYED artifact tools/sdp_policies/sdp_policy_v3.json "
               "(policy-block sha256 0443febf…, THE CALIBRATED BENCHMARK; the "
               "actions below were read off v2 (740c802e…), which is identical "
               "on SoC rows 3+ — the two differ in 30 cells on rows 1-2 and "
               "this trajectory spans rows ~63 down to ~44; see the row-diff "
               "test) read directly for the two "
               "branches' actions. Current budgets against LIMIT_I_FC_MAX 1.4 "
               "A / LIMIT_I_BT_MAX 3.0 A through the firmware's minority "
               "governor (.ino:9556-9568)."),
    # FAULT-FREE. ⚠️ THE OC ARGUMENT THAT USED TO MAKE THIS ENTRY SPECIAL IS
    # MOOT (2026-09-01, the preload removal). It read: this leg commands the
    # 0.85 rail, so its preload had to be solved DOWN to 0.45 A to keep 17.5 %
    # of margin at the cycle peak, because an OC_FC latch would truncate the
    # run at the point the scenario exists to observe. At preload 0 the
    # governed FC peak on that branch is I_tot - 0.300 = 0.6603 A model /
    # 0.7046 A on the measured composition — 50 % under LIMIT_I_FC_MAX 1.4 A.
    # The expectation stays fault-free and an OC_FC here is still a real
    # finding; what is retired is the claim that this leg runs closer to the
    # limit than its siblings. It no longer does, and it no longer runs a
    # different stimulus from them either.
    "allow_only": 0,
    # Past the whole flip band, fault-free: the run must reach its own
    # post-flip half, not merely survive the low-rail phase.
    # ⚠️ RAISED 260 -> 300 with the preload removal: the flip itself moved from
    # a measured 198.5 s to a predicted 272.0 s (the flip is a drain integral
    # and the drain shrank), so 260 s now lands BEFORE the transition and would
    # have asserted nothing about the post-flip half.
    "survive_to": {"t": 300.0, "states": {2, 3}},
    "signals_require": [
        # 1. THE EMS LAYER ACTUALLY COMMANDED THE CYCLE. The v_setpoint axis is
        #    scenario script, not policy output, so this is the same "did the
        #    50 Hz stream carry the profile" check the sibling entries make —
        #    placed on the cycle's own 3.0 m/s peak at t = 245.
        {"name": "sdpftp_drive_commanded", "column": "cmd_v_sp",
         "min_value": 2.90, "t_window": (230.0, 260.0),
         "label": "the SDP policy commanded the FTP-75 cycle's 3.0 m/s peak"},
        # 2. THE BATTERY-HEAVY BRANCH, SUSTAINED — a CEILING, so it asserts
        #    that NO in-window sample exceeded the low rail. This is the first
        #    time anything in this suite has put 0.15 on the wire from the SDP
        #    policy, and it is only reachable by starting above the node.
        #    The window closes at 150 s, the bottom of the flip band.
        #    ⚠️ RE-PROVISIONALIZED 2026-09-01, THE PRELOAD REMOVAL. The flip is
        #    an INTEGRAL of the pack drain, so removing 0.45 A of housekeeping
        #    load moves it LATE. Governor walk at preload 0:
        #        C:/Users/ricky/miniforge3/python.exe -c "import sys;
        #            sys.path.insert(0,'tools'); import ems_walk as W;
        #            print(W.walk('sdp-v3','ems-ftp75-sdp',governor=True)
        #                  .summary())"
        #    (bind_scenario() applies the scenario's own sdp_soc_ref_offset, so
        #    no strategy_kwargs are needed) gives ONE transition, 0.15 -> 0.85,
        #    at t = 272.0 s — 39 % later than the 195.9 s the 0.45 A walk gave.
        #    Scaling by the measured/walk ratio the last era established
        #    (198.537/196.0 = 1.0129) puts the expected board flip at 275.5 s.
        #    THE BAND IS (240, 295), i.e. -12.9 %/+7.1 % around that prediction
        #    — deliberately asymmetric, because the low-rail side has the whole
        #    early cycle to spare while the high-rail side must still leave a
        #    usable post-flip window inside a 340 s profile. Both arms are
        #    >= 5x the 1.35 % walk-vs-board disagreement the previous era
        #    measured. Re-derive from the first zero-preload campaign.
        {"name": "sdpftp_low_rail_early", "column": "cmd_share_sp",
         "max_value": _SDP_LOW_RAIL_CEIL, "t_window": (20.0, 240.0),
         "provisional_note": _SDPFTP_PROVISIONAL,
         "label": "the SDP policy commanded its BATTERY-HEAVY branch for the "
                  "whole pre-flip phase (no sample above the 0.15 clamp; walk "
                  "flip 272.0 s at preload 0)"},
        # 3. ... AND THE FUEL-CELL BRANCH AFTER THE BAND. With check 2 this
        #    pins the transition inside (150, 250) s without needing a
        #    transition-detecting check kind: the command is provably at one
        #    rail before the band and provably reaches the other after it.
        {"name": "sdpftp_high_rail_late", "column": "cmd_share_sp",
         "min_value": _SDP_HIGH_RAIL_FLOOR, "t_window": (295.0, 340.0),
         "provisional_note": _SDPFTP_PROVISIONAL,
         "label": "... and switched to the FUEL-CELL branch (0.85) after the "
                  "flip band — with the check above, a crossing inside "
                  "t = 240..295 s (governor walk 272.0 s at preload 0)"},
        # 4-5. THE SAME SPAN ON THE PRE-CLAMP COLUMN, which is where the
        #    TABLE's own request is visible. 0.00 is a value the clamp hides
        #    entirely from `cmd_share_sp` (it emits 0.15 either way if the
        #    policy ever railed low for another reason), so these two are the
        #    checks that identify the ARTIFACT's branch rather than the
        #    emitted level.
        {"name": "sdpftp_raw_battery_branch", "column": "cmd_share_sp_raw",
         "max_value": _SDP_RAW_LOW_CEIL, "t_window": (20.0, 240.0),
         "provisional_note": _SDPFTP_PROVISIONAL,
         "label": "the table's PRE-CLAMP request was its 0.00 battery rail — "
                  "a value no other scenario in this suite can produce"},
        # ⚠️ THE 0.89 FLOOR IS KEPT AT ITS BOUNDARY-CASE VALUE, deliberately,
        # even though campaign 20260901_024231 measured a post-flip MINIMUM of
        # 0.95 and a peak of 1.00 — demand BIN 24 was never entered on that run.
        # The floor guards the boundary case, not the measurement: the cycle's
        # peak demand sits ~4 % below the bin-24 lower edge, so a model or load
        # change well inside this entry's own sensitivity puts a sample in the
        # bin whose request IS 0.90. Tightening to the measured 0.95 would fail
        # a correct board the first time that happens. See _SDP_RAW_HIGH_FLOOR.
        {"name": "sdpftp_raw_fc_branch", "column": "cmd_share_sp_raw",
         "min_value": _SDP_RAW_HIGH_FLOOR, "t_window": (295.0, 340.0),
         "provisional_note": _SDPFTP_PROVISIONAL,
         "label": "... and returned to its fuel-cell rail (1.00/0.95, or 0.90 "
                  "in demand bin 24) after the flip (measured post-flip "
                  "minimum 0.95, campaign 024231)"},
        # 6. THE BOARD ACTED ON THE BATTERY-HEAVY BRANCH. A CEILING on I_fc,
        #    and the derivation is the governor rather than the command: the
        #    commanded 0.15 is always below SHARE_MINORITY_I_MIN_A / I_tot at
        #    this cycle's currents (I_tot peaks at 1.41 A -> floor 0.213), so
        #    the DELIVERED FC current is pinned at the 0.300 A minority floor
        #    for the whole pre-flip phase.
        #    (PART C, 2026-09-01: the 0.65 A-era arithmetic that used to close
        #    this paragraph — a 0.8275 A control peak, a 1.11 A branch and a
        #    0.45 A ceiling — is DELETED rather than corrected. It described a
        #    stimulus this entry no longer runs and it contradicted the
        #    replacement derivation immediately below, which is the one in
        #    force.)
        #    ⚠️ WHAT A PASS PROVES (inherited from every sibling entry): the
        #    plant splits bus current in proportion to the MDAC CODE RATIO
        #    (HIL_PLANT.md 4.7 — sign- and monotonicity-preserving, WRONG
        #    GAIN), so this asserts the firmware->MDAC arithmetic, not
        #    share-loop gain.
        #    ⚠️ THE GOVERNOR-FLOOR DERIVATION ABOVE NO LONGER APPLIES IN THIS
        #    WINDOW, and the replacement is stated rather than the number
        #    quietly moved. At preload 0 the source total over t = (30, 150)
        #    peaks at 0.5253 A — BELOW the 0.55 A open-loop exit threshold —
        #    so the share loop is OPEN through the whole window and the
        #    minority governor is not clipping anything. The delivered split is
        #    the commanded 0.15 itself, and the governor walk gives a window
        #    peak I_fc of 0.0788 A (against the constant-0.50 sibling's
        #    0.2626 A over the same window).
        #    A 0.18 A ceiling is 2.3x the prediction and 31 % under the
        #    sibling's control peak, so it still separates the battery-heavy
        #    branch from a run that ignored the command — but it is now a
        #    statement about the OPEN-LOOP delivered ratio, not about the
        #    0.300 A floor. PROVISIONAL: re-derive from the first campaign.
        {"name": "sdpftp_fc_floored_early", "column": "I_fc",
         "max_value": 0.18, "t_window": (30.0, 150.0),
         "provisional_note": _SDPFTP_PROVISIONAL,
         "label": "the board delivered the battery-heavy split — I_fc under "
                  "0.18 A through an OPEN-LOOP window whose source total never "
                  "reaches 0.55 A (walk peak 0.0788 A; the constant-0.50 "
                  "sibling reaches 0.2626 A there)"},
        # 7. ... AND ON THE FUEL-CELL BRANCH.
        #    ⚠️ THE WINDOW MOVED, AND IT HAD TO. This check used to sit on the
        #    cycle peak, t = (235, 260) — which at preload 0 is BEFORE the
        #    predicted 272.0 s flip, so it would have measured the
        #    battery-heavy branch and failed a correct board. It is moved to
        #    (295, 340), the same post-flip window the rail checks use.
        #    The cost is stated: the cycle peak is not in that window, so the
        #    governed FC current there is smaller. Governor walk over
        #    (295, 340): peak I_fc 0.5402 A (the loop is CLOSED at that peak —
        #    source total ~0.84 A).
        #    ⚠️ PART C (C1 round, 2026-09-01): 0.42 -> 0.46 A. THE OLD FLOOR
        #    DID NOT REJECT A STUCK-0.5 BOARD, which is the failure this check
        #    exists to catch. A board ignoring the command and holding a
        #    constant 0.50 split delivers 0.4198 A over this window (0.4307 A
        #    with the documented +2.6 % FTP75 gain offset) — both ABOVE 0.42.
        #    0.46 A is 15 % under the 0.5402 A walk prediction and 6.8 % above
        #    the worst-case stuck-0.5 figure, so the check now separates the
        #    fuel-cell branch from the control it names.
        {"name": "sdpftp_fc_carried_late", "column": "I_fc",
         "min_value": 0.46, "t_window": (295.0, 340.0),
         "provisional_note": _SDPFTP_PROVISIONAL,
         "label": "the board delivered the fuel-cell split after the flip "
                  "(>= 0.46 A; governor walk peak 0.5402 A over "
                  "t = 295..340 s at preload 0, against 0.4198-0.4307 A for "
                  "a board stuck at a constant 0.50 split)"},
        # 7b. THE BATTERY CHANNEL'S OWN CEILING (new, campaign 024231). The
        #    scenario's whole-run peak I_batt is 0.7117 A and it lands AT THE
        #    FLIP (t = 198.53), where the branch hands over: 76 % under
        #    LIMIT_I_BT_MAX 3.0 A. A run-wide ceiling of 0.90 A is 26 % above
        #    the measurement, so it is a REGRESSION TRIPWIRE on the handover
        #    transient rather than a limit claim — the BT channel has never been
        #    bounded on this entry at all, and a share-loop or governor change
        #    that pushed current onto it would previously have gone unseen.
        #    ⚠️ RE-DERIVED AT PRELOAD 0: the governor walk's whole-run peak
        #    I_batt is 0.6602 A (at the cycle peak, on the pre-flip
        #    battery-heavy branch, where the loop is closed and the minority
        #    governor puts I_tot - 0.300 on the battery). 0.90 A is 36 % above
        #    that and 3.3x under LIMIT_I_BT_MAX 3.0 A, so the ceiling is KEPT
        #    at its value — it was already a regression tripwire rather than a
        #    limit claim, and it retains that role with more margin.
        {"name": "sdpftp_bt_peak_bounded", "column": "I_batt",
         "max_value": 0.90, "t_window": (5.0, 340.0),
         "provisional_note": _SDPFTP_PROVISIONAL,
         "label": "the battery channel stayed bounded through the branch "
                  "handover (governor walk whole-run peak 0.6602 A at "
                  "preload 0, vs LIMIT_I_BT_MAX 3.0 A)"},
        # 8-9. THE H2 ACCOUNTING RAN, AND STAYED BOUNDED. Budget from the walk:
        #    ~0.30 A on FC for the ~190 s pre-flip phase (4.7 W bus, 5.5 W
        #    stack) and ~0.8 A for the ~150 s after it (12.5 W bus, 14.7 W
        #    stack), at the model's 1.7638e-5 g/s/W DC gain -> ~1.8e-2 +
        #    ~3.9e-2 = ~5.7e-2 g.
        #    ⚠️ MEASURED (campaign 20260901_024231): 0.0621749 g, 9.1 % above
        #    the walk. The band is DE-PROVISIONALIZED from the walk-era
        #    [0.020, 0.120] (2.85x below / 2.1x above, which could not fail
        #    anything) to [0.056, 0.070] — -10 %/+13 % of the measurement, wide
        #    enough for the flip time's own +/-7 % band (the flip decides the
        #    split of the run between a ~4.7 W and a ~12.5 W branch) and narrow
        #    enough that a scale error of 2x fails.
        #    ⚠️ Gfc is scale-portable by design but not identified against this
        #    stack (TODO(calibrate), H2Consumption banner), so this asserts the
        #    accounting RAN and REPEATED, not an absolute mass.
        #    ⚠️ RE-PROVISIONALIZED AT PRELOAD 0: the governor walk gives
        #    0.019918 g / dSoC -0.014691 at the plant-equivalent dv0 0.030223
        #    (F1, 2026-09-01 — RE-WALKED at the M2 consistent pair; the retired
        #    M1-era walk gave 0.019347 / -0.014922), against the 0.0621749 g
        #    measured in the 0.45 A era (campaign 024231). Band = walk +/-25 %,
        #    the same shape as the two sibling entries' — [0.0149, 0.0249].
        {"name": "sdpftp_h2_accounted", "column": "h2_cum_g",
         "min_value": 1.49e-2, "provisional_note": _FTP_H2_PROVISIONAL,
         "label": "the H2 consumption metric accumulated over the cycle "
                  "(M2-equivalent governor walk 0.019918 g at preload 0; "
                  "0.0621749 g in the retired 0.45 A era)"},
        {"name": "sdpftp_h2_bounded", "column": "h2_cum_g",
         "max_value": 2.49e-2, "provisional_note": _FTP_H2_PROVISIONAL,
         "label": "... and stayed under 0.0249 g, so a scale or accumulation "
                  "error in the metric fails here instead of reading as a "
                  "result"},
    ],
}


# ── ems-ftp75-dp — the drive-cycle NON-CAUSAL BOUND (WP-E, 2026-09-01) ───────
#
# Shape mirrors `ems-ftp75-5050`'s, because the STIMULUS is that scenario's
# term for term (the same FTP75_PROFILE list object, the same
# FTP75_RUN_EXIT_S, the same FTP75_PRELOAD_A — 0.0 A since 2026-09-01, and now
# also the same as `ems-ftp75-sdp`'s). What differs is the commanding: an
# offline DP table rather than a constant 0.50 split.
#
# ⚠️ THE TABLE WAS RE-SOLVED for the zero-preload demand (2026-09-01).
# `aux_preload_a` is in DP_FINGERPRINT_META_KEYS, so a table solved against the
# 0.65 A demand is REFUSED at load rather than played — the era boundary is
# enforced by the fingerprint, not by this comment.
#
# FAULT-FREE IS THE EXPECTATION, and at preload 0 the table's own control grid
# says so with room to spare. Its share span is [0.15, 0.85] (n_share 57,
# recorded in the header and drift-checked at load; widened from [0.25, 0.75]
# at 41 on 2026-09-02), so the worst single-channel loading it can command is
# 0.85 of the source total. At the cycle peak (model 0.9603 A, and the
# `ems-ftp75-5050` trace runs +2.6 % hot against that) 0.85 is ~0.838 A — 40 %
# under LIMIT_I_FC_MAX 1.4 A, against
# the ~1.24 A / 11.3 % margin the 0.65 A preload left. The OC_FC concern that
# made this the entry's least-supported expectation is therefore RETIRED; if a
# campaign latches OC_FC here it is a real finding and the trace should be read
# against the table.
#
# ⚠️ EVERY THRESHOLD BELOW IS PROVISIONAL — no campaign has run this scenario.
# PART C (C1 round, 2026-09-01): the union MOVES WITH ITS TWO SOURCES, and
# it is now DERIVED from them rather than transcribed -- a hand-copied union
# is exactly the kind of constant that goes stale the next time one of the
# siblings' bands is re-walked, which is what happened this round.
# Today: [0.023, 0.038] (5050) union [0.028, 0.047] (socband).
# The DP's own re-solved optimum, 0.0396922 g at a matched terminal SoC,
# lands inside it -- asserted by test, not assumed.
_FTP75_DP_H2_BAND = (min(_FTP_H2_BAND_5050[0], _FTP_H2_FLOOR_SOCBAND),
                     max(_FTP_H2_BAND_5050[1], _FTP_H2_CEILING_SOCBAND))
# WHY THIS BAND, and why it is NOT the DP's own predicted total. The solver
# reports an h2_g_physical for the re-solved table (see the regenerated
# header), but that number is the REDUCED MODEL's open-loop optimum at a
# matched terminal SoC and is not the quantity a live run's `h2_cum_g` column
# measures. Banding a live metric on it would import the whole reduced model's
# error budget.
#
# The band is taken from the two SIBLING legs instead, on a structural
# argument that the preload removal does not disturb: this leg runs their
# stimulus, and its realized split lies BETWEEN theirs by construction —
# `ems-ftp75-5050` holds 0.50 for the whole cycle and `ems-ftp75-socband`
# saturates at 0.75, while the table moves inside [0.25, 0.75]. Hydrogen
# tracks the FC channel's share of one fixed demand, so this leg's total must
# land inside the union of the two siblings' bands.
#
# ⚠️ RE-DERIVED AT PRELOAD 0 (2026-09-01) — union of the two governor-walk
# bands: [0.021, 0.035] (5050, walk 2.809e-2) and [0.026, 0.045] (socband,
# walk 3.546e-2). Union floor 0.021, union ceiling 0.045. Expect the realized
# value near the socband end, since the table sits at its 0.75 rail for most
# of its stages. LAST PRELOADED-ERA MEASUREMENT, not comparable: 0.09291 g /
# dSoC -0.01478 (campaign hil_report_20260901_151156).
FAULT_EXPECTATIONS["ems-ftp75-dp"] = {
    "source": ("hil_plant_sim.py SCENARIOS['ems-ftp75-dp'] + the generated "
               "tools/dp_tables/dp_ems_table_ems-ftp75-dp.csv (its header "
               "records every consumed tunable and is drift-checked against "
               "the live engine at startup) + the FTP75_PRELOAD_A budget and "
               "the two measured FTP-75 siblings' h2 bands."),
    "allow_only": 0,
    "survive_to": {"t": _FTP_SURVIVE_T, "states": {2}},
    "signals_require": [
        # 1. The CYCLE ran to its peak — identical to the 5050 sibling's, and
        #    deliberately so: the legs share one stimulus, and this is the
        #    check that says the stimulus happened.
        {"name": "ftpdp_peak_commanded", "column": "cmd_v_sp", "min_value": 2.85,
         "t_window": _FTP_PEAK_W,
         "label": "the FTP-75 peak (3.0 m/s at t = 245 s) was commanded"},
        # 2. ... and the BOARD carried the load. The table's grid floors the FC
        #    share at 0.25, so the weakest peak loading it can command is
        #    0.25 x 0.9603 = 0.240 A at preload 0. 0.20 A sits under that and
        #    16x above the ~0.0375 A a 0.25 split of the 0.15 A standstill
        #    total would give, so an idling run that merely reached t = 245
        #    cannot satisfy it. Deliberately LOOSER than the sibling's 0.40 A:
        #    that leg's split is pinned at 0.50, this one's is chosen by the
        #    table. The window is the cycle peak, where the share loop is
        #    CLOSED (source total 0.9347..0.9603 A).
        {"name": "ftpdp_fc_carried", "column": "I_fc", "min_value": 0.20,
         "t_window": _FTP_PEAK_W,
         "provisional_note": "first zero-preload campaign; the floor is the "
                             "table's own 0.25 share rail applied to the "
                             "governor-walk peak source total 0.9603 A — "
                             "re-derive from the first campaign that runs it",
         "label": "the FC channel carried its DP-commanded share of the peak "
                  "(floor = the table's own 0.25 share rail at preload 0)"},
        # 3. THE DP ACTUALLY DROVE THE RUN. Without this the scenario passes
        #    identically whether the table reached the wire or a constant 0.50
        #    split did — and a bound leg that was silently un-driven makes the
        #    whole frontier verdict meaningless while every per-run check
        #    stays green. The table holds 0.75 on 2058 of 3501 stages, so a
        #    0.70 peak is reached with enormous margin and is unreachable by
        #    any constant-0.50 fallback.
        #    SCOPE OF CHECKS 3 AND 4 (E-L3): both read `cmd_share_sp`, the
        #    SIM-SIDE wire quantity — they assert the table reached the wire,
        #    not that the board acted on it. The board-side coupling is
        #    check 2's `I_fc` floor.
        {"name": "ftpdp_table_commanded", "column": "cmd_share_sp",
         "min_value": 0.70, "t_window": (5.0, 340.0),
         "label": "the DP table's own share command reached the wire (it "
                  "holds 0.75 on 59 % of its stages; a constant-0.50 fallback "
                  "cannot produce this)"},
        # 4. ... and it OPENED on the other end of its span. The table spends
        #    51 stages at the 0.25 rail — and MEASURED FROM THE TABLE ITSELF
        #    (dp_ems_table_ems-ftp75-dp.csv, share <= 0.30), every one of them
        #    sits in t = [0.0, 5.0] contiguously at the 0.1 s stage pitch. The
        #    rail is the table's OPENING, not an excursion inside the cycle.
        #    ⚠️ WINDOW CORRECTED 2026-09-01 (WP-E H1). This check previously
        #    carried check 3's window, (5.0, 340.0), which contains NO low-rail
        #    stage at all: `max_value` judges the window's PEAK, and over
        #    (5.0, 340.0) the peak is check 3's own 0.75, so checks 3 and 4
        #    were mutually exclusive and check 4 could only ever fail.
        #    WINDOW CHOICE — (0.0, 5.0), not (3.0, 5.0): `cmd_share_sp` is the
        #    SIM-SIDE wire quantity, which DpReplayStrategy emits on every
        #    commander tick regardless of mode (only `charge_goal` and
        #    `mode_cmd` are gated on EMS_RUN_ENTRY_S = 3.0), so the pre-Run
        #    stages are genuinely on the wire and are the thing this check
        #    asserts reached it. scan_signals() already floors every window at
        #    WARM_RESET_GRACE_S = 2.0 s, so the effective window is (2.0, 5.0]
        #    — ~31 of the 51 rail stages, ample margin.
        #    ⚠️ PART C (C1 round, 2026-09-01): 0.30 -> 0.32. The table's own
        #    minimum share on this cycle is 0.2875, so a 0.30 ceiling left
        #    4.2 % of margin on a DETERMINISTIC checked-in file — tight
        #    enough that a float32 wire round trip plus one re-solve of the
        #    table could fail a correct run, and the quantity has no physical
        #    spread to justify a knife edge. 0.32 is 11 % above the table
        #    value and still far below the 0.70 the upper-rail check requires,
        #    so the two remain mutually exclusive by a wide margin.
        {"name": "ftpdp_table_low_rail", "column": "cmd_share_sp",
         "max_value": 0.32, "t_window": (0.0, 5.0),
         "provisional_note": "first zero-preload campaign; the ceiling is the "
                             "re-solved table's own 0.2875 minimum plus 11 %, "
                             "not a measurement — re-derive it from the first "
                             "campaign that runs it",
         "label": "... and the table's OPENING low rail reached the wire "
                  "(<= 0.32 against the table's own 0.2875 minimum; t <= 5 s, "
                  "where every one of its 51 low-rail stages lives), so the "
                  "run replayed the table from its start and not just its "
                  "upper half"},
        # 5-6. The H2 metric ran end to end and landed in the siblings' union
        #    band. Two specs, because one spec cannot carry both bounds (the
        #    import guard refuses min_value+max_value on a single leaf —
        #    `_judge_signal_leaf` tests min before max and drops the ceiling).
        {"name": "ftpdp_h2_accounted", "column": "h2_cum_g",
         "min_value": _FTP75_DP_H2_BAND[0],
         "provisional_note": _FTP_H2_PROVISIONAL,
         "label": "the H2 consumption metric accumulated over the cycle "
                  "(>= %.3f g, the `ems-ftp75-5050` floor at preload 0)"
                  % _FTP75_DP_H2_BAND[0]},
        {"name": "ftpdp_h2_bounded", "column": "h2_cum_g",
         "max_value": _FTP75_DP_H2_BAND[1],
         "provisional_note": _FTP_H2_PROVISIONAL,
         "label": "... and stayed under %.3f g (the `ems-ftp75-socband` "
                  "ceiling at preload 0), so a scale or accumulation error "
                  "fails here instead of reading as a result"
                  % _FTP75_DP_H2_BAND[1]},
    ],
}

FAULT_EXPECTATIONS["ems-sdp-cross"] = {
    "source": ("hil_plant_sim.py SCENARIOS['ems-sdp-cross'] and the SDP_CROSS_* "
               "constants (the two cruise levels and why each one is where it "
               "is, the MEASURED flip time and charge-window schedule of "
               "campaign 20260901_024231, and the single-source charge budget; "
               "the retired walk and why it was wrong are recorded there too) "
               "+ the shared derivation block "
               "above the two SDP_CROSS/SDP_BRAKE scenarios in hil_plant_sim.py "
               "for why an UPWARD share crossing is unreachable + "
               "SdpStrategy.set_soc_ref_offset() and the SDP_CHG_* "
               "minimum-dwell block."),
    "allow_only": 0,
    # Deep enough to contain the LATER passes of the charge limit cycle: the
    # cycle, not merely its first window, is what the scenario is for. (The
    # walk's "third window at 172.9-180.9 s" this line used to cite was part of
    # the retired ~52 s period; the board runs 9 windows at 16.13 s — the
    # measured schedule is in the `sdpx_charge_*` derivations below.)
    "survive_to": {"t": 180.0, "states": {2, 3}},
    "signals_require": [
        # 1-2. THE DOWNWARD SHARE CROSSING, pinned by the same two-window
        #    construction as ems-ftp75-sdp's: a ceiling before the band and a
        #    floor after it.
        #    ⚠️ MEASURED (campaign 20260901_024231): the flip landed at
        #    t = 42.292 s (walk 43.85, -3.5 %). The band is DE-PROVISIONALIZED
        #    from the walk's +/-50 % (25, 65) to (35, 50) — 17 % of slack below
        #    the measurement and 18 % above it, which covers the walk-vs-board
        #    disagreement itself with margin to spare.
        {"name": "sdpx_low_rail_early", "column": "cmd_share_sp",
         "max_value": _SDP_LOW_RAIL_CEIL, "t_window": (5.0, 35.0),
         "label": "the run opened on the SDP table's battery-heavy branch "
                  "(commanded share at the 0.15 clamp)"},
        {"name": "sdpx_high_rail_late", "column": "cmd_share_sp",
         "min_value": _SDP_HIGH_RAIL_FLOOR, "t_window": (50.0, 190.0),
         "label": "... and crossed the SHARE threshold to the fuel-cell branch "
                  "(0.85) — with the check above, a crossing inside "
                  "t = 35..50 s (measured 42.292 s, campaign 024231)"},
        # 3. The pre-clamp column on the opening branch, for ems-ftp75-sdp's
        #    reason: 0.00 identifies the ARTIFACT's branch, which the clamped
        #    column cannot.
        {"name": "sdpx_raw_battery_branch", "column": "cmd_share_sp_raw",
         "max_value": _SDP_RAW_LOW_CEIL, "t_window": (5.0, 35.0),
         "label": "the table's PRE-CLAMP request was its 0.00 battery rail"},
        # 4. THE CHARGE LIMIT CYCLE REACHED THE BOARD.
        #    ⚠️ MEASURED (campaign 20260901_024231): 64103 ticks of
        #    FC_CHARGE_ENABLE over t = 70..190 s — 9 windows at a 16.13 s
        #    period, 53.4 % of the window. The walk predicted 3 windows /
        #    ~25200 ticks; its 12000-tick floor was therefore 19 % of the truth
        #    and COULD NOT FAIL. Raised to 45000 = 70 % of the measurement,
        #    which still survives losing three whole windows to timing.
        {"name": "sdpx_charge_cycled", "switch_bit": SW_FC_CHARGE,
         "min_ticks": 45000, "t_window": (70.0, 190.0),
         "label": "the policy's SoC-driven charge action reached the board — "
                  "FC_CHARGE_ENABLE open for >= 45 s across the low cruise "
                  "(measured 64.103 s, campaign 024231)"},
        # 5. ... AND IT IS A CYCLE, NOT ONE LONG WINDOW — asserted PHASE-FREE.
        #    ⚠️ THIS REPLACES `sdpx_charge_released_between`, THE ONE FAIL OF
        #    CAMPAIGN 20260901_024231. That check asserted the ABSENCE of a
        #    charge window over t = 90..108 s, an instant taken from the walk's
        #    ~52 s limit-cycle period. The board's period is 16.13 s — the walk
        #    was wrong by 5.7x (root cause in the SDP_CROSS_* block in
        #    hil_plant_sim.py: it applied the closed-loop minority governor at a
        #    cruise the firmware runs in OPEN-LOOP HOLD) — so the window sat on
        #    top of a charge window and failed a CORRECT board.
        #    The objective is unchanged: "the dwell latch is a hysteresis, not a
        #    hold-forever". The three checks below express it without a phase
        #    claim, so a period change moves the numbers, not the verdict.
        #    (a) LONGEST CONTINUOUS HOLD. SDP_CHG_MIN_DWELL_S is 8.0 s and the
        #    measured longest hold is 8.085 s (dwell + 1.1 %, i.e. the dwell
        #    plus the decision quantum). 9000 ticks = 9.0 s = dwell + 12.5 %,
        #    so a latch that failed to release is caught at the first extra
        #    decision stage while decision-phase jitter is not.
        #    ⚠️ THREE CAMPAIGNS, AND THE HOLD IS THE ERA-INVARIANT HALF
        #    (2026-09-03). Measured longest hold 8.0640 s (20260902_041414),
        #    8.0647 s (20260902_220604, bleed era) against 8.085 s (024231) —
        #    invariant to under 0.3 %, because the 8 s dwell hysteresis sets
        #    it and not charge economics. THE PERIOD IS NOT INVARIANT: see
        #    `sdpx_charge_window_count` below.
        {"name": "sdpx_charge_max_hold", "switch_bit": SW_FC_CHARGE,
         "max_continuous_ticks": 9000, "t_window": (70.0, 190.0),
         "label": "... and no single charge window outlasted the 8.0 s "
                  "minimum dwell by more than one decision stage — the latch "
                  "is a hysteresis, not a hold-forever (measured longest hold "
                  "8.085 s, campaign 024231)"},
        # 6. (b) THE RELEASED FRACTION. The complement of check 4's count over
        #    the same window: released = 1 - ticks/120000. Measured 0.466, and
        #    the objective band is [0.30, 0.70] released — i.e. FC_CHARGE set
        #    on 36000..84000 of the window's 120000 ticks. The FLOOR of that
        #    band is carried by check 4 at the stricter 45000 (released
        #    <= 0.625), so this spec is the CEILING half: a run that charged
        #    for more than 70 % of the low cruise has stopped cycling, which no
        #    total-tick floor can see.
        {"name": "sdpx_charge_released_fraction", "switch_bit": SW_FC_CHARGE,
         "max_ticks": 84000, "t_window": (70.0, 190.0),
         "label": "... and the charger was RELEASED for at least 30 % of the "
                  "low cruise (measured released fraction 0.466 — 64103 of "
                  "120000 ticks set, campaign 024231)"},
        # 7. (c) THE WINDOW COUNT, straight off the switch trace. 9 rising
        #    edges measured over t = 70..190 s; [6, 12] is -33 %/+33 % of that,
        #    which brackets a period anywhere in 10..20 s. This is the check
        #    that distinguishes "one long window" (1 edge) from "the limit
        #    cycle" without naming an instant.
        #    ⚠️ "ERA-INVARIANT" IS WRONG FOR THE PERIOD (2026-09-03). Three
        #    campaigns all measure 9 windows, but the period band is
        #    16.10-17.12 s, not a single figure: campaign 20260902_220604
        #    measures periods ALTERNATING 16.105 / 17.105 s where
        #    20260902_041414 measured 16.084-16.122 s. The [6, 12] edge band
        #    brackets both and does not move; what moves is the claim in the
        #    prose. MEDIUM confidence on the alternation — one campaign.
        {"name": "sdpx_charge_window_count", "switch_bit": SW_FC_CHARGE,
         "edge_count_between": (6, 12), "edge": "rise",
         "t_window": (70.0, 190.0),
         "label": "... across 6-12 distinct charge windows (measured 9 in "
                  "each of three campaigns, at a period of 16.13 s in "
                  "campaign 024231 and 16.10-17.12 s in the bleed-era "
                  "campaign 20260902_220604)"},
        # 8. THE CHARGER ACTUALLY CHARGED. Peak-over-window, so any one window
        #    satisfies it. Each is SDP_CHG_MIN_DWELL_S = 8 s long against
        #    AG105_SETTLE_S 0.5 s + AG105_TAU_S 0.4 s, so I_charge reaches the
        #    0.8 A ceiling with room to spare.
        #    ⚠️ MEASURED 0.8000 A exactly (the scenario's own chg_i_ceiling_a),
        #    so the walk-era 0.5 A floor was 37 % low. Raised to 0.75 A = 94 %
        #    of the ceiling: it still cannot be met by an unpowered charger or
        #    by a window too short to settle, and it now also fails a run whose
        #    charger only reached a fraction of its programmed ceiling.
        {"name": "sdpx_charging_established", "column": "I_charge",
         "min_value": 0.75, "t_window": (78.0, 190.0),
         "label": "the Ag105 delivered its full 0.8 A ceiling inside the dwell "
                  "windows (measured 0.8000 A, campaign 024231)"},
        # 9. THE SINGLE-SOURCE CHARGE BUDGET, now measured rather than argued.
        #    With FC_CHARGE_ENABLE open, assertFcChargeEnable() drops BT off the
        #    bus and the FC channel alone carries the ~0.34 A load plus the
        #    0.8 A charger. MEASURED peak I_fc 1.1920 A at t = 79.90 —
        #    14.9 % under LIMIT_I_FC_MAX 1.4 A, and equal to `ems-soc-band`'s
        #    own validated 1.1920 A at the same operating point. The ceiling
        #    1.28 A is 7.4 % above the measurement and 8.6 % under the limit, so
        #    it trips BEFORE an OC_FC latch would and names the cause.
        # ⚠️ CHARGER ERA (WP-1C, 2026-09-02) — THE CEILING IS HELD AT 1.28 AND
        # THE MEASUREMENT UNDER IT IS NOW STALE. The charger's bus draw falls
        # to V_pack/(ETA_CHG*V_bus) ~ 0.56 of its pack current, so a 0.8 A
        # charge window costs the FC channel ~0.355 A less and the peak is
        # PREDICTED at ~0.84 A against the measured 1.1920 A. Two reasons the
        # ceiling does not follow it down: it is an OC BUDGET bound against
        # LIMIT_I_FC_MAX 1.4 A, which has not moved; and tightening it to an
        # offline prediction would fail a correct board if the prediction is
        # wrong in the safe direction. The cost is honest and stated — until
        # the first eta-era campaign re-pins it, this check has ~0.44 A of
        # slack and is a budget bound rather than a tripwire.
        {"name": "sdpx_fc_peak_bounded", "column": "I_fc",
         "max_value": 1.28, "t_window": (5.0, 190.0),
         "label": "the single-source FC channel stayed inside its charge-window "
                  "budget (measured peak 1.1920 A vs LIMIT_I_FC_MAX 1.4 A, "
                  "campaign 024231)"},
        # 10. NO SHARE-BRANCH DISCRIMINATION FROM I_fc, and it is a stated gap
        #    rather than an omission: at this scenario's 0.67 A high-cruise
        #    total the governor's minority floor clips BOTH branches to within
        #    0.07 A of each other (0.300 A on FC at the low rail, 0.367 A at
        #    the high one), so no I_fc threshold can tell them apart. Check 9
        #    above is a BUDGET ceiling, not a branch discriminator. The
        #    board-side evidence for the share command is ems-ftp75-sdp's.
        #    ⚠️ AND THE DELIVERED SPLIT HERE IS NOT THE COMMANDED ONE: the low
        #    cruise runs at I_tot ~ 0.355 A, below the firmware's 0.55 A
        #    open-loop drop-out (.ino:9933), so the board holds its last
        #    converged split (measured delivered share 0.1656 against the
        #    commanded 0.85) instead of tracking. That is designed behaviour and
        #    it is exactly what the retired walk failed to model — see the
        #    strategy-authoring note in hil_plant_sim.py.
    ],
}

FAULT_EXPECTATIONS["ems-sdp-braking"] = {
    "source": ("hil_plant_sim.py SCENARIOS['ems-sdp-braking'] and the "
               "SDP_BRAKE_* constants — in particular SDP_BRAKE_ACCEL_S and "
               "SDP_BRAKE_CHG_CEILING_A, which are BOTH current-budget "
               "constants sized against the one-decision charge overhang into "
               "the acceleration out of each low plateau + the shared "
               "derivation block above the two scenarios."),
    # ⚠️ THE fw v25 GUARD ROUND CAME OUT OF THIS SCENARIO, and the FAIL on
    # record for it is a fw <= 24 result. Campaign 20260901_080905 latched OC_BT
    # here at t = 65.485: applyShareRatio()'s r-based bus cutoff opened FC_BUS —
    # the only CONDUCTING source, i_cut 0.6371 A — 5 ms after BT_BUS was
    # commanded HIGH, inside the survivor's ~8 ms RT1987 t_D_ON. The board's
    # response was CORRECT (latch, teardown, motor zeroed); the defect was the
    # unguarded cut, not the fault.
    #
    # `allow_only: 0` IS UNCHANGED AND IS DELIBERATELY NOT WEAKENED. Under
    # fw >= 25 the fatal cut is REFUSED — on the load guard (0.6371 > 0.5 A) and
    # on the survivor blanking (5 ms < 30 ms), either of which alone forecloses
    # it — so the fault-free expectation this entry has always carried becomes
    # REACHABLE again rather than aspirational. A refused cut sets no flag and
    # is not a fault: it falls through to the band-edge droop clip with the
    # ratio slew limiter re-armed, and is retried every tick. So the expected
    # fw v25 signature here is a CLEAN RUN, with the refusal visible only in the
    # firmware's own shareCutRefusedLoad / shareCutRefusedBlank counters (State-
    # 98 'S' dump; NOT on the observation frame, so this suite cannot score them
    # — carrying them would be a frame extension, future protocol work).
    #
    # IF THIS FAILS ON A fw v25 CAMPAIGN it is a guard regression and the
    # suite-wide `share_cut_load_hazard` tripwire should name it in the same
    # run. Do not relax this entry to accommodate it.
    #
    # ── GUARD ANCHORS AT THIS SCENARIO'S OWN OPERATING POINT ───────────────
    # Three campaigns have now read the guard here; the bleed-era figures
    # (campaign 20260902_220604) are the ones to compare against.
    #   sw_ring events        19 (20260902_041414: 19)
    #   max i_cut             0.4517172287 A (041414: 0.4517 class; every
    #                         cut UNDER the 0.5 A load guard, so none is a
    #                         hazard cut and none is in the load-dump class)
    #   peak I_batt at the    0.4511 / 0.4625 / 0.4177 A
    #   three heavy BT        (041414: 0.4687 / 0.4791 / 0.4324;
    #   restores               20260902_011926: 0.52; PRE-GUARD fw v24
    #                          campaign 080905: 4.64 A)
    # At each restore `r` pins at 0.14987 = DROOP_R_MIN and the refused-cut
    # slew carries it back over ~300 ms; V_bus dips to ~14 V and RISES.
    # Campaign-wide in 20260902_220604: 112 sw_ring events, 0 hazard cuts,
    # max non-teardown FC_BUS/BT_BUS `en_low` 0.3705 A (handoff-sag).
    "allow_only": 0,
    # Past the third of four braking cycles.
    "survive_to": {"t": 100.0, "states": {2, 3}},
    "signals_require": [
        # 1-2. THE SHARE AXIS IS HELD STILL, asserted from BOTH sides. This is
        #    what licenses the attribution in checks 3-5: with the commanded
        #    share provably constant at the 0.85 clamp, every FC_CHARGE
        #    transition in the trace was decided by the DEMAND axis. Two specs
        #    rather than one because a single spec carrying min_value and
        #    max_value silently drops the ceiling (the import-time guard
        #    refuses that shape).
        {"name": "sdpb_share_rail_held", "column": "cmd_share_sp",
         "min_value": _SDP_HIGH_RAIL_FLOOR, "t_window": (5.0, 125.0),
         "label": "the policy commanded its fuel-cell branch (0.85 clamp)"},
        {"name": "sdpb_share_never_crossed", "column": "cmd_share_sp",
         "max_value": 0.86, "t_window": (5.0, 125.0),
         "label": "... and NEVER crossed to the battery-heavy branch — which "
                  "is what makes every charge transition below attributable "
                  "to the demand axis alone"},
        # 3. CHARGING HAPPENED, ACROSS THE LOW PLATEAUS. Walk: four windows of
        #    ~12.5 s, 50.1 s in total.
        #    ⚠️ MEASURED (campaign 20260901_024231): 52479 ticks over this
        #    window, four windows, longest 13.108 s — the walk to within 4.7 %,
        #    which is what "DEMAND-driven, so it lands on the profile's own
        #    fixed instants" was predicting. Floor raised 25000 -> 45000 = 86 %
        #    of the measurement: it still absorbs one shortened plateau (a whole
        #    lost plateau now fails, which is the point — losing one of four is
        #    a finding, not tolerance).
        {"name": "sdpb_charge_in_low_windows", "switch_bit": SW_FC_CHARGE,
         "min_ticks": 45000, "t_window": (10.0, 125.0),
         "label": "the policy opened FC_CHARGE across the low-speed plateaus "
                  "(>= 45 s; measured 52.479 s over four windows, campaign "
                  "024231)"},
        # 4-5. ... AND NOT DURING THE CRUISES. Two of the four 2.2 m/s holds,
        #    inset by 2 s at each end so a deceleration's own admit-then-drop
        #    blip (see the scenario comment) cannot leak in. The walk shows
        #    ZERO charge ticks inside either.
        #    ⚠️ MEASURED (campaign 20260901_024231): 0 ticks in BOTH windows,
        #    exactly as walked. The walk-era 500-tick allowance (0.5 s of a
        #    7-8 s window) was slack nothing has ever used, so it is tightened
        #    to 100 ticks = 0.1 s. That still admits a single late release
        #    landing inside the window's opening tick or two, and it is far
        #    below anything the Ag105 could act on (AG105_SETTLE_S is 0.5 s).
        #    Both have check 3 as their positive companion on the same switch
        #    bit, so a blank column cannot satisfy them vacuously.
        #    ⚠️ THE CORRELATION IS THE OBJECTIVE: charge ON in the low windows
        #    (check 3) and OFF in the cruises (these two) is what "the demand
        #    axis decided it" means in a trace.
        {"name": "sdpb_charge_off_in_cruise_2", "switch_bit": SW_FC_CHARGE,
         "max_ticks": 100, "t_window": (41.0, 48.0),
         "label": "FC_CHARGE closed through the second 2.2 m/s cruise "
                  "(P_dem ~10.6 W = bin 10, charge-forbidden; measured 0 "
                  "ticks, campaign 024231)"},
        {"name": "sdpb_charge_off_in_cruise_3", "switch_bit": SW_FC_CHARGE,
         "max_ticks": 100, "t_window": (72.0, 79.0),
         "label": "... and through the third one (measured 0 ticks, campaign "
                  "024231)"},
        # 6. THE CHARGER ACTUALLY CHARGED. Ceiling here is
        #    SDP_BRAKE_CHG_CEILING_A = 0.7 A (de-rated for the acceleration
        #    overhang), and each window is ~12.5 s against 0.9 s of settle plus
        #    ramp, so I_charge reaches it.
        #    ⚠️ MEASURED (campaign 20260901_024231): 0.7000 A exactly, i.e. the
        #    programmed ceiling, reached by t = 25.52 s. Floor raised 0.4 ->
        #    0.65 A = 93 % of the ceiling, so the check now also fails a run
        #    whose charger reached only a fraction of what it was told to.
        {"name": "sdpb_charging_established", "column": "I_charge",
         "min_value": 0.65, "t_window": (25.0, 125.0),
         "label": "the Ag105 delivered its full 0.7 A de-rated ceiling inside "
                  "the low-plateau windows (measured 0.7000 A, campaign "
                  "024231)"},
        # 7. THE TIGHTEST OC MARGIN IN THE SUITE, now asserted (new, campaign
        #    20260901_024231). MEASURED peak I_fc 1.2617 A at t = 65.51 — in
        #    the ONE-DECISION CHARGE OVERHANG into the acceleration out of a low
        #    plateau, which is exactly the transient SDP_BRAKE_ACCEL_S (6.0 s)
        #    and SDP_BRAKE_CHG_CEILING_A (0.7 A) were both sized against. That
        #    is 9.9 % under LIMIT_I_FC_MAX 1.4 A, the smallest margin any
        #    scenario in this suite runs at, and until now it was UNASSERTED:
        #    an OC_FC would have been caught by `allow_only: 0`, but a retune
        #    that ate the margin down to 1 % without tripping would not.
        #    The ceiling 1.32 A is 4.6 % above the measurement and 5.7 % under
        #    the limit, so it trips BEFORE the board faults and names the cause.
        #    ⚠️ NEVER raise it to make a run green: the margin outgrowing this
        #    bound IS the finding, and the two knobs that move it are named
        #    above.
        # ⚠️ CHARGER ERA (WP-1C, 2026-09-02) — CEILING HELD AT 1.32, AND THE
        # 9.9 % MARGIN THE COMMENT ABOVE CALLS "the smallest in this suite" IS
        # NO LONGER THE 1:1-era number. The charge overhang costs the FC
        # channel ~0.56 of what it did (see the `sdpx_fc_peak_bounded` note),
        # so at SDP_BRAKE_CHG_CEILING_A 0.7 A the peak is PREDICTED at ~0.95 A
        # against the measured 1.2617 A, i.e. a ~32 % margin rather than 9.9 %.
        # The suite's tightest-margin claim moves with it and must be
        # re-measured before being quoted again. The bound is NOT lowered onto
        # the prediction, for the reason given at `sdpx_fc_peak_bounded`.
        {"name": "sdpb_fc_peak_bounded", "column": "I_fc",
         "max_value": 1.32, "t_window": (5.0, 130.0),
         "label": "the single-source FC channel stayed inside the charge "
                  "overhang budget (measured peak 1.2617 A, 9.9 % under "
                  "LIMIT_I_FC_MAX 1.4 A, campaign 024231)"},
        # 8. THE CRUISE-GUARD EARLY-DROP BRANCH, censused. The walk predicted
        #    five ~1.05 s admit-then-drop blips (Run entry, plus one per
        #    deceleration) on top of the four sustained plateau windows, and
        #    campaign 20260901_024231 MEASURED exactly that: 9 rising edges of
        #    FC_CHARGE over t = 2.5..130 s, at 3.008 / 19.175 / 50.390 / 81.624
        #    / 112.842 (drops) and 21.195 / 52.411 / 83.644 / 114.862 (windows).
        #    Until this campaign the early-drop branch had NEVER been exercised
        #    on hardware, and it is still nothing else's business to observe it.
        #    ⚠️ THIS IS A CENSUS, NOT A DROP COUNTER. The edge kind cannot tell
        #    a 1 s blip from a 13 s window, so the band is composed:
        #        4 sustained windows (pinned by checks 3-5) + [4, 6] early drops
        #        = [8, 10] rising edges.
        #    Read it WITH check 3: if the tick total and the two cruise windows
        #    are right, the four sustained windows are accounted for and the
        #    remainder of this count IS the drop count.
        {"name": "sdpb_charge_edge_census", "switch_bit": SW_FC_CHARGE,
         "edge_count_between": (8, 10), "edge": "rise",
         "t_window": (2.5, 130.0),
         "label": "FC_CHARGE opened 8-10 times — the four plateau windows plus "
                  "4-6 cruise-guard early drops (measured 9 = 4 + 5, campaign "
                  "024231)"},
    ],
}


# ═════════════════════════════════════════════════════════════════════════════
# THE FOUR MPC LEGS (2026-09-02) — the governor-aware receding-horizon EMS
#
# Design: docs/modeling/mpc_design_20260901.md (section 7.3 for these checks);
# adjudication: docs/modeling/mpc_design_20260901/adjudication.md section 2.6.
#
# ⚠️ EVERY BAND BELOW IS PROVISIONAL AND EVERY ONE IS FROM AN OFFLINE WALK, not
# from a board.  The walk is `ems_walk.walk(..., governor=True, dv0_v=0.030223)`
# at soc0 0.7 — the same method, the same plant-equivalent asymmetry offset and
# the same +/-25 % band shape the FTP-75 sibling entries use.  Gate 2 of the
# design's evaluation plan, run 2026-09-02:
#
# ⚠️ RE-DERIVED 2026-09-02 (the DP-bound round), and TWO things moved at once.
# First, the DEMAND MODEL: every walk below carries the static-loss map
# (`hil_plant_sim.plant_loss_map()`, passed as `ems_walk.walk(loss_map=...)`)
# and the per-node bleed, so the walks predict the board's NEW plant. Second,
# the STRATEGY BINDINGS: `mpc-sto` is now the default MPC and `ems-mpc`,
# `ems-mpc-cross` and `ems-ftp75-mpc` bind it, while the scenario formerly
# named `ems-mpc-sto` is `ems-mpc-det` and binds `mpc-det` as the ablation.
# A row below is therefore NOT comparable with the pre-round row of the same
# scenario name on either axis.
#
#   leg                  strategy   h2 (g)     dSoC        eq-H2 (lambda 0.41)
#   ems-soc-band         soc-band   0.012051   -0.001975   0.016868   (reference)
#   ems-dp-replay        dp-replay  0.011680   -0.001913   0.016346   (bound)
#   ems-sdp              sdp-v4     0.012522   -0.001571   0.016354
#   ems-mpc              mpc-sto    0.007588   -0.003591   0.016347
#   ems-mpc-det          mpc-det    0.009728   -0.002708   0.016333
#   ems-mpc-cross        mpc-sto    0.010835   -0.007318   0.028684
#   ems-ftp75-socband    soc-band   0.041936   -0.006231   0.057134   (reference)
#   ems-ftp75-sdp        sdp-v4     0.019813   -0.014684   0.055628
#   ems-ftp75-mpc        mpc-sto    0.021983   -0.013792   0.055622
#   ems-ftp75-dp         dp-replay  0.037504   -0.007479   0.055746   (bound)
#   ems-ftp75-5050       hold-5050  0.029807   -0.010612   0.055690
#
# The PRE-ROUND table, kept because every band shipped before this round was
# sized on it:
#   ems-soc-band   0.012264 / -0.002002 / 0.017146 ; ems-dp-replay 0.011900 /
#   -0.001936 / 0.016622 ; ems-sdp 0.012729 / -0.001600 / 0.016631 ;
#   ems-mpc (then mpc-det) 0.010429 / -0.002537 / 0.016616 ; ems-mpc-sto (then
#   mpc-sto) 0.009313 / -0.002998 / 0.016625 ; ems-mpc-cross (then mpc-det)
#   0.014134 / -0.006007 / 0.028786 ; ems-ftp75-socband 0.041873 / -0.006306 /
#   0.057254 ; ems-ftp75-sdp 0.019918 / -0.014691 / 0.055750 ; ems-ftp75-mpc
#   (then mpc-det) 0.023771 / -0.013112 / 0.055751.
#
# ⚠️ THE PAIR IS THE RESULT, NOT THE HYDROGEN, and on this controller that is
# not a stylistic preference. Three repeats of each walk reproduce the totals
# above to six decimals, but raising the search budget from the shipped 12 ms to
# 1e5 ms moves `ems-mpc-cross`'s hydrogen by −21 % (0.014134 -> 0.011163) while
# its EQUIVALENT hydrogen moves by 0.13 % (0.028786 -> 0.028750). A deeper
# search buys hydrogen with state of charge. Every h2 band below is therefore a
# SCALE AND ACCUMULATION tripwire and cannot discriminate a policy; the
# equivalent-hydrogen total, which the frontier check computes across runs, is
# the search-invariant quantity.
#
# ⚠️ THE WALK CANNOT SCORE THE MPC.  Its plant IS the controller's prediction
# model, which is the inverse-crime condition (design section 7.1).  Every h2
# band below therefore asserts that the ACCOUNTING RAN AND REPEATED at the right
# scale — the same claim the FTP-75 h2 bands make — and NOT that the policy is
# good.  The live campaign against the high-fidelity plant is the evaluation.
#
# ⚠️ AN MPC RUN IS NOT BIT-REPRODUCIBLE AND MUST NEVER ENTER A REPEATABILITY
# LEDGER.  The planner's search is bounded by WALL CLOCK (`--mpc-budget-ms`,
# `--mpc-roll-budget-ms`), so a loaded campaign host can return a different —
# still feasible, still validated — command.  Each of the four legs declares
# `mpc_max_candidates` = `hil_plant_sim.MPC_CAMPAIGN_MAX_CANDIDATES` (1029, the
# FULL enumeration at the shipped ladder INCLUDING the charge axis — 7**3 share
# plans times the three charge plans a decision offers; it was 343, one charge
# option's worth, through campaign 20260902_011926, which truncated every capped
# decision before the charge axis) to take
# the clock out of the candidate COUNT; the roll-table slicing and the board's
# own timing remain non-deterministic.  Compare an MPC leg against its own band
# and against the frontier tuple; do NOT compare two MPC runs digit for digit
# the way the `scp` i_cut and `ems-sdp` h2 records are compared.
#
# The degenerate-constant guard of section 7.3 (`column_range_at_least`) is on
# ALL FOUR legs.  Every walk moves the commanded share — ranges 0.417, 0.333,
# 0.250 and 0.333 — and each threshold below is set at roughly HALF its leg's
# measured range, so a controller that emitted one constant cannot pass while
# ordinary walk-versus-board disagreement can.

# Shared qualifiers, so the claim cannot drift between the four entries.
_MPC_PROVISIONAL = (
    "PROVISIONAL, first registration (2026-09-02) — the band is from the "
    "OFFLINE GOVERNOR WALK of Gate 2, not from a board, and the walk's plant is "
    "the controller's own prediction model (the inverse-crime condition, design "
    "section 7.1). It asserts scale and accumulation, never policy quality. "
    "Re-derive from the first campaign that evaluates this leg")
_MPC_TIMING_PROVISIONAL = (
    "PROVISIONAL, first registration (2026-09-02) — the decision-timing and "
    "budget-expiry bands are WALL-CLOCK quantities and are therefore a property "
    "of the campaign host as much as of the controller. They are regression "
    "tripwires on the search depth, NOT assertions about the command: on expiry "
    "the planner returns the shifted incumbent, which is feasible and was "
    "validated one second earlier. Never raise one to make a run go green; a "
    "budget that outgrew its bound is the finding. Re-derive from the first "
    "campaign, and re-derive again if a deterministic candidate cap is adopted")
_MPC_PRED_PROVISIONAL = (
    "PROVISIONAL, first registration (2026-09-02), and it is a band derived "
    "from an OFFLINE MEASUREMENT rather than a widened pin. ⚠️ GATE 1 OF THE "
    "DESIGN'S EVALUATION PLAN FAILS OFFLINE: with the governor roll table "
    "actually consulted, the surrogate's delivered-share error on the "
    "`ems-soc-band` stimulus is mean 0.0097 / max 0.25000 against the design's "
    "5e-03 acceptance. The worst stages are `open_feedforward` — every 1 Hz "
    "re-command that lands in an open-loop stage triggers a governor "
    "feedforward slew that NEITHER model represents. The MPC ships with that "
    "recorded: the first campaign IS the calibration reading for this column, "
    "and the fallback of section 7.1 (rolling the full governor on open stages "
    "with a reduced candidate set) is the decision that reading informs. The "
    "0.30 ceiling clears the offline max with margin and still fails a "
    "prediction that has stopped tracking. A mean-side bound would be the "
    "better assertion — the mean is 26x under the max — but this file has no "
    "column-mean check kind and a registration round is not where one is "
    "added. Second-order and pointing the other way: the walk's feedback view "
    "carries no MDAC words, so its shadow governor is corrected only from the "
    "measured current split (valid only above the 0.60 A gate), while a "
    "campaign feeds `mdac_fc`/`mdac_bt` and reads the applied ratio directly "
    "in every mode")

# The share ladder's structural bounds, DERIVED FROM THE LADDER'S OWN BAND.
# The command is quantized ONTO the closed interval `mpc_ems.SHARE_BAND_DP`, so
# a sample outside it is a plumbing defect (a clamp applied to the wrong
# quantity, a ladder built from the wrong band) rather than a policy result.
# The 0.01 margins absorb the 4-decimal CSV rendering.
#
# ⚠️ IMPORTED, NEVER TYPED (campaign 20260902_220604, `signal_mpc_share_floor`).
# The pair was hand-written as 0.24/0.76 against a (0.25, 0.75) band, and the
# ca2d084 widening to (DROOP_R_MIN, DROOP_R_MAX) = (0.15, 0.85) left it behind:
# `ems-ftp75c-mpc` railed at ladder rung 1 (0.1500) for the whole cycle and
# `ems-mpc-cross` touched rung 2 (0.2375), and BOTH were failed by a bound that
# no longer described the ladder they ran on. Deriving the pair means the next
# widening moves it, and the CEILING arm — which at 0.76 would have failed the
# first leg to select rung 8 or 9 — moves with it.
_MPC_SHARE_BAND = tuple(float(_v) for _v in mpc_ems.SHARE_BAND_DP)
_MPC_SHARE_FLOOR = round(_MPC_SHARE_BAND[0] - 0.01, 6)
_MPC_SHARE_CEIL = round(_MPC_SHARE_BAND[1] + 0.01, 6)
# The overcurrent budget the planner itself enforces (mpc_ems.I_FC_MAX_A =
# 0.85 * LIMIT_I_FC_MAX 1.4 A).  Asserted as a CEILING on the FC channel rather
# than as a longest-run bound: the suite has no numeric-threshold run kind
# (`max_continuous_ticks` needs a bit or a masked integer), and a peak ceiling
# expresses the same budget claim without one.  Walk peaks are far under it —
# RE-MEASURED 2026-09-02 on the shipped bindings and the loss-map demand
# era: 0.7357 A (ems-mpc, mpc-sto), 0.9809 A (ems-mpc-det, mpc-det),
# 0.3016 A (cross), 0.4886 A (ftp75). The ablation leg is the one that
# moved, and it moved because `mpc-det` commands a wider share band on
# this stimulus than `mpc-sto` does; at 0.9809 A it still sits 18 % under
# the ceiling. So this remains a budget bound with slack, not a tripwire,
# and it says so. The pre-swap figures were 0.7310 A (ems-mpc /
# ems-mpc-sto), 0.3015 A (cross), 0.4801 A (ftp75).
_MPC_I_FC_CEIL = 1.19


# ── THE SINGLE-SOURCE COMMANDS (2026-09-03) ────────────────────────────────
# `ems-mpc-single` may command a share of exactly 0.0 or exactly 1.0, which is
# a LEGAL command and not a band excursion: the firmware constrains the received
# setpoint to [0, 1] (.ino:5663) and `updateShareSetpointCutoff()` takes the
# out-of-band value as a topology instruction.  The two band checks therefore
# EXEMPT those two values on that leg and report the exempt COUNT, so "the share
# left the ladder's band" and "the controller went single-source N times" stay
# distinguishable in the verdict text.  Every other MPC leg keeps the plain
# bound - a 0.0 sample there IS a defect.
_MPC_SINGLE_SOURCE_VALUES = (0.0, 1.0)

# The two reasons an MPC leg's h2 FLOOR is reported without a verdict.  Passed
# to `_mpc_expectation(h2_informational_note=...)`; the first is the default,
# because it was the first leg to need one.
_MPC_H2_INFORMATIONAL_SPREAD = (
    " — INFORMATIONAL: this floor sits INSIDE the leg's measured "
    "run-to-run spread (campaign 20260902_011926 -0.13 % of the band edge, "
    "campaign 20260902_041414 +0.10 %), so a verdict here would score noise. "
    "It is reported, with a WARNING when the bound is missed, until the "
    "cap-lifted walk re-band lands")
# 2026-09-03, review MED-2.  `ems-mpc-single`'s walk ran at `budget_ms` 1e5 -
# an UNBOUNDED search - while the leg runs at a 15 ms campaign budget, and the
# single-source columns sort LAST in the enumeration, so they are the first
# thing an expiry drops.  A leg that expires on many decisions therefore commits
# fewer single-source stages than the walk did and lands nearer `ems-mpc-det`'s
# 0.009353 g, i.e. ABOVE this band's ceiling and far above its floor.  Both arms
# stay as the walk PREDICTION; the floor is reported without a verdict for the
# first campaign, which is what measures the expiry fraction.
_MPC_H2_INFORMATIONAL_UNBOUNDED_WALK = (
    " — INFORMATIONAL for the first campaign: the walk this band comes "
    "from ran an UNBOUNDED search (budget_ms 1e5, full-search median 11.04 ms "
    "against a 15 ms campaign budget) and the single-source columns are the "
    "first an expiry drops, so a live leg that expires commits fewer "
    "single-source stages than the walk and moves toward ems-mpc-det's "
    "0.009353 g. Read `mpc_budget_hit` and the census fragment FIRST, then "
    "re-band from the measured expiry fraction")


def _mpc_expectation(*, scenario, walk_h2, duration_s, survive_t,
                     run_window, share_range_min=None, pred_err_max,
                     budget_hit_max_ticks, charge_edges, min_rows, extra_note,
                     h2_floor_informational=False,
                     h2_informational_note=None, single_source=False):
    """One MPC leg's expectation entry.  PURE.

    ONE BUILDER for all four, for `_alpha_expectation()`'s reason: the four legs
    assert the SAME properties and only their numbers differ, so a hand-written
    fourth copy is a place for one of them to drift."""
    lo, hi = round(walk_h2 * 0.75, 6), round(walk_h2 * 1.25, 6)
    # The band exemption, applied to BOTH arms or to neither.  A dict spread so
    # a leg without the feature produces the identical spec dict it always did.
    _ss = ({"exempt_values": list(_MPC_SINGLE_SOURCE_VALUES)}
           if single_source else {})
    _ss_label = ("" if not single_source else
                 " Exactly 0.0 and 1.0 are EXEMPT and COUNTED on this leg: "
                 "they are the single-source commands, which the firmware "
                 "constrains to [0, 1] and reads as a topology instruction, "
                 "not band excursions.")
    sigs = [
        # 1. CADENCE — de-vacuates every window-scoped check below.  A run whose
        #    CSV is short (a child that died early, a link that never came up)
        #    would otherwise satisfy the ceilings with no rows at all.
        {"name": "mpc_cadence", "min_rows": min_rows,
         "t_window": run_window,
         "label": "the Run window carries at least %d CSV rows, so the "
                  "window-scoped bounds below are judged on a real run"
                  % min_rows},
        # 2-3. THE COMMANDED SHARE STAYED ON ITS OWN LADDER.  Two specs, floor
        #    and ceiling, because a single spec carrying both bounds silently
        #    drops one (see the min/max guard above).
        # ⚠️ `floor_min_value`, NOT `min_value` (2026-09-03). `min_value` judges
        #    the in-window PEAK, so the floor arm asserted "the share reached
        #    0.24 at least once" — satisfied by any run whose maximum clears the
        #    bound, including one that spent the rest of the window below it.
        #    The claim is an INVARIANT ("no sample left the ladder's band
        #    downward"), which is the in-window MINIMUM. The ceiling arm keeps
        #    `max_value`, which is already the peak-side invariant.
        dict({"name": "mpc_share_floor", "column": "cmd_share_sp",
              "floor_min_value": _MPC_SHARE_FLOOR, "t_window": run_window,
              "provisional_note": _MPC_PROVISIONAL,
              "label": "the commanded share never left the ladder's own "
                       "interval [%.2f, %.2f] downward - a sample below %.2f "
                       "means the ladder was built from the wrong band.%s"
                       % (_MPC_SHARE_BAND[0], _MPC_SHARE_BAND[1],
                          _MPC_SHARE_FLOOR, _ss_label)}, **_ss),
        dict({"name": "mpc_share_ceiling", "column": "cmd_share_sp",
              "max_value": _MPC_SHARE_CEIL, "t_window": run_window,
              "provisional_note": _MPC_PROVISIONAL,
              "label": "... and never left it upward (peak <= %.2f)"
                       % _MPC_SHARE_CEIL}, **_ss),
    ] + ([] if not single_source else [
        # 3b. DID THE FEATURE FIRE AT ALL (2026-09-03, review LOW-4)?  The two
        #     band arms above exempt 0.0/1.0; this one puts a FLOOR under the
        #     tally, so a leg that committed no single-source stage is
        #     self-describing rather than silently indistinguishable from one
        #     that committed 24.  INFORMATIONAL on the first campaign - the
        #     rollout-time cut guard declining every candidate is a legitimate
        #     result, and the walk's 24 commitments were measured on an
        #     unbounded search.
        {"name": "mpc_single_source_exercised", "column": "cmd_share_sp",
         "exempt_values": list(_MPC_SINGLE_SOURCE_VALUES),
         "exempt_min_count": 1, "t_window": run_window,
         "provisional_note": _MPC_PROVISIONAL, "informational": True,
         "label": "the single-source command was actually issued at least once "
                  "(a sample at exactly 0.0 or exactly 1.0) — "
                  "INFORMATIONAL: a run that admits nothing is the cut guard "
                  "doing its job, but it makes every other number on this leg "
                  "a two-source number, so the count is reported either way"},
    ]) + [
        # 4. THE OVERCURRENT BUDGET the planner enforces on its own plan.
        {"name": "mpc_fc_peak_bounded", "column": "I_fc",
         "max_value": _MPC_I_FC_CEIL, "t_window": run_window,
         "provisional_note": _MPC_PROVISIONAL,
         "label": "the fuel-cell channel stayed inside the planner's own "
                  "overcurrent margin (%.2f A = 0.85 x LIMIT_I_FC_MAX 1.4 A). "
                  "A BUDGET bound with wide slack against the walk's peak, not "
                  "a tripwire" % _MPC_I_FC_CEIL},
        # 5. THE CHARGE DECISION did not chatter.  An edge CENSUS with a floor
        #    of 0 rather than a window: the MPC's charge intent is a genuine
        #    decision variable, so its schedule is not knowable in advance, but
        #    a controller cycling the Ag105 tens of times has stopped deciding
        #    and started oscillating.  The walk opens ZERO windows on every one
        #    of the four legs, so the floor is deliberately 0 — an absence here
        #    is the PREDICTED outcome and must not fail.
        {"name": "mpc_charge_edge_census", "switch_bit": SW_FC_CHARGE,
         "edge_count_between": (0, charge_edges), "edge": "rise",
         "t_window": run_window, "provisional_note": _MPC_PROVISIONAL,
         "label": "FC_CHARGE opened at most %d times — the offline walk opens "
                  "ZERO windows on this leg, so this is an ANTI-CHATTER "
                  "ceiling, not an existence claim" % charge_edges},
        # 6-7. THE HYDROGEN ACCOUNTING, the sibling entries' two-sided shape.
        # `h2_floor_informational` (2026-09-02, campaign C): the floor is
        # EVALUATED and REPORTED but never fails the run on a leg where the
        # band edge has been shown to sit inside the quantity's own
        # run-to-run spread. See the leg's own note for the two readings.
        {"name": "mpc_h2_accounted", "column": "h2_cum_g",
         "min_value": lo, "t_window": run_window,
         "provisional_note": _MPC_PROVISIONAL,
         "informational": bool(h2_floor_informational),
         "label": "the H2 consumption metric accumulated over the cycle "
                  "(>= %.6f g = governor walk %.6f g -25 %%)%s"
                  % (lo, walk_h2,
                     "" if not h2_floor_informational else
                     (h2_informational_note or _MPC_H2_INFORMATIONAL_SPREAD))},
        {"name": "mpc_h2_bounded", "column": "h2_cum_g",
         "max_value": hi, "t_window": run_window,
         "provisional_note": _MPC_PROVISIONAL,
         "label": "... and stayed under %.6f g (walk +25 %%), so a scale or "
                  "accumulation error fails here instead of reading as a "
                  "result" % hi},
        # 8. THE DECISION ACTUALLY RAN, and inside its budget.  This is the one
        #    check that distinguishes an MPC run from any other: `mpc_solve_ms`
        #    is BLANK for every other strategy, so an unmeasured column here
        #    means the strategy was not the MPC at all.
        {"name": "mpc_solve_bounded", "column": "mpc_solve_ms",
         "max_value": 20.0, "t_window": run_window,
         "provisional_note": _MPC_TIMING_PROVISIONAL,
         "label": "every decision returned within 20 ms — the 12 ms budget "
                  "plus the slack a loaded campaign host needs. UNMEASURED "
                  "fails, which is also the check that the MPC drove this run"},
        # 9. THE SHADOW GOVERNOR'S OWN SCORE.  The strategy plans DELIVERED
        #    splits, so this column is the claim it makes; see the qualifier.
        {"name": "mpc_share_prediction", "column": "mpc_share_pred_err",
         "max_value": pred_err_max, "t_window": run_window,
         "provisional_note": _MPC_PRED_PROVISIONAL,
         "label": "the governor-aware model predicted the DELIVERED stage "
                  "share to within %.2f (walk peak, MDAC-blind)"
                  % pred_err_max},
        # 10. THE SEARCH DEPTH.  A ceiling on the ticks spent holding a
        #    budget-expired decision, i.e. on the fraction of the run commanded
        #    by a shifted incumbent rather than by a fresh plan.
        {"name": "mpc_budget_expiry_bounded", "column": "mpc_budget_hit",
         "value_mask": 0x1, "value_equals": 0x1,
         "max_ticks": budget_hit_max_ticks, "t_window": run_window,
         "provisional_note": _MPC_TIMING_PROVISIONAL,
         "vacuity_note": (
             "`mpc_budget_hit` is written on EVERY tick of an MPC run from the "
             "first decision onward, and the `mpc_solve_bounded` check above "
             "fails outright on an unmeasured MPC diagnostic column, so a "
             "blank column cannot pass this entry silently."),
         "label": "at most %d ticks were commanded by a BUDGET-EXPIRED "
                  "decision (a shifted incumbent — feasible, and validated one "
                  "second earlier)" % budget_hit_max_ticks},
    ]
    if share_range_min is not None:
        # THE DEGENERATE-CONSTANT GUARD (design section 7.3).  Applied only
        # where the walk predicts motion — see the block above for why the two
        # 61 s legs do not carry it.
        sigs.insert(3, {
            "name": "mpc_share_moved", "column": "cmd_share_sp",
            "column_range_at_least": share_range_min, "t_window": run_window,
            "provisional_note": _MPC_PROVISIONAL,
            "label": "the commanded share MOVED by at least %.2f across the "
                     "run, so a controller emitting one constant cannot pass "
                     "(roughly half the Gate-2 walk's own range)"
                     % (share_range_min,)})
    return {
        "source": ("hil_plant_sim.py SCENARIOS[%r] + "
                   "docs/modeling/mpc_design_20260901.md sections 7.1-7.3 "
                   "(the evaluation plan and the phase-free check list) + the "
                   "Gate-2 governor walk table in the block above. %s"
                   % (scenario, extra_note)),
        "allow_only": 0,
        "survive_to": {"t": survive_t, "states": {2, 3}},
        "signals_require": sigs,
    }


# ── ems-mpc: the frontier candidate ─────────────────────────────────────────
FAULT_EXPECTATIONS["ems-mpc"] = _mpc_expectation(
    scenario="ems-mpc", walk_h2=0.007162, duration_s=61.0, survive_t=50.0,
    # RE-DERIVED 2026-09-02: the leg binds `mpc-sto`, whose walk commands a
    # 0.2500 share range on this stimulus (the pre-swap `mpc-det` walk was
    # wider). The floor is ~0.6x that, which is a degenerate-constant guard
    # with room, not a tolerance on the plan.
    run_window=(5.0, 58.0), share_range_min=0.15,
    pred_err_max=0.30, budget_hit_max_ticks=52000, charge_edges=4,
    min_rows=40000,
    extra_note=("The CANDIDATE leg of the `cycle61-mpc` frontier tuple, and "
                "since 2026-09-02 it runs `mpc-sto` — the stochastic law is "
                "THE MPC and `mpc-det` is the ablation on `ems-mpc-det`. The "
                "loss-map-era walk lands eq-H2 0.016347 against the "
                "`soc-band` reference's 0.016868 (0.9691x) and the "
                "`dp-replay` bound's 0.016346 (1.0001x) — and note that the "
                "vs-bound arm is STRUCTURALLY near 1.0 for a charge-free "
                "candidate (design section 7.4.1), so it detects lever-class "
                "deviations and does not measure optimality. ⚠️ The "
                "delta-SoC-matched DP bound for this walk's terminal state "
                "is NOT YET PREFILLED: the stored 0.010418 g (tools/dp_db, "
                "key 62151bd59b9cd787) was matched to the `mpc-det` walk in "
                "the loss-map-free era and applies to neither leg as it "
                "stands."))

# ── ems-mpc-det: the stochastic variant, NOT a frontier leg ─────────────────
FAULT_EXPECTATIONS["ems-mpc-det"] = _mpc_expectation(
    scenario="ems-mpc-det", walk_h2=0.009427, duration_s=61.0, survive_t=50.0,
    # RE-DERIVED 2026-09-02: the leg binds `mpc-det`, whose walk commands a
    # 0.4167 share range here — the widest of the four legs, because the
    # deterministic law reads the stimulus it is driving. Floor ~0.6x.
    run_window=(5.0, 58.0), share_range_min=0.25,
    pred_err_max=0.30, budget_hit_max_ticks=52000, charge_edges=4,
    min_rows=40000,
    extra_note=("NOT a frontier leg — EMS_STRATEGY_META's role note says why. "
                "FIRST LIVE RESULT (campaign hil_report_20260902_011926): "
                "measured h2 0.00808750 g, -13.2 %% of this walk — INSIDE the "
                "+/-25 %% band, so it passed and never surfaced. Read it beside "
                "`ems-mpc-cross`'s -25.09 %% miss on the same law: `mpc-det` "
                "matched its own walks to +0.05 %% and -0.42 %%, so the two "
                "under-shoots point at the sto/cross WALKS rather than at the "
                "board. Both walks are to be re-derived with the candidate cap "
                "lifted (343 -> 1029, 2026-09-02) before either band moves; the "
                "fix round that found this deliberately did NOT re-derive them, "
                "because a walk re-derivation without the cap-lifted run "
                "replaces one unvalidated number with another. "
                "Its Gate-2 pair differs from `mpc-det`'s on the SAME stimulus "
                "(h2 0.009313 / dSoC -0.002998 against 0.010429 / -0.002537) "
                "while the two equivalent-hydrogen totals agree to 0.05 %: the "
                "certainty-equivalent demand path and the 90 % overcurrent "
                "quantile move the plan along the share lever without moving "
                "its value, which is the expected outcome on a stimulus that "
                "is not a draw from the matrix. Its open-loop hold fraction is "
                "0.338 against `mpc-det`'s 0.223 on the identical cycle — the "
                "two plans spend materially different fractions of the run "
                "below the 0.55 A line — so the two runs are NOT "
                "interchangeable evidence about the governor."))

# ── ems-mpc-single: the single-source (0/1) demonstration ──────────────────
#
# PROVISIONAL, and every number below is from ONE offline walk (soc0 0.7,
# loss-map era, dv0 0, unbounded search) - the same status the four MPC legs
# carried at their own first registration.  Re-pin from the first campaign that
# runs it.
#
# THE WALK: h2 0.004770 g, dSoC -0.004710, share range 0.0 .. 0.6750, 24 of 61
# decisions committed BT-only (share 0.0), 0 committed FC-only.  Against
# `ems-mpc-det`, the SAME stimulus and law with the feature off: h2 0.009353,
# dSoC -0.002859, range 0.15 .. 0.6750.
#
# ⚠️ THE h2 BAND IS THE WIDE ONE THE FEATURE FORCES.  Single-source moves the
# operating point along the SoC lever, not along a loss, so the HYDROGEN swings
# by 49 % between the two legs while the EQUIVALENT hydrogen moves 0.43 %.  A
# +/-25 % band on a quantity that halves with one decision is a plumbing check
# and nothing more, and it is labelled as one.
FAULT_EXPECTATIONS["ems-mpc-single"] = _mpc_expectation(
    scenario="ems-mpc-single", walk_h2=0.004770, duration_s=61.0,
    survive_t=50.0, run_window=(5.0, 58.0),
    # The walk's commanded range is 0.675 here against `ems-mpc-det`'s 0.525:
    # the low rail is now 0.0, not 0.15.  Floor ~0.6x, the family's rule.
    share_range_min=0.40,
    pred_err_max=0.30, budget_hit_max_ticks=52000, charge_edges=4,
    min_rows=40000, single_source=True,
    h2_floor_informational=True,
    h2_informational_note=_MPC_H2_INFORMATIONAL_UNBOUNDED_WALK,
    extra_note=("THE SINGLE-SOURCE (0/1) LEG, and the only registered "
                "scenario that arms `mpc_single_source`. Run it BESIDE "
                "`ems-mpc-det`, which is the identical stimulus and law with "
                "the feature OFF - the pair is a controlled A/B on one "
                "scenario key. The two band checks EXEMPT exactly 0.0 and 1.0 "
                "and report the exempt sample count; a share outside "
                "[0.15, 0.85] that is NOT one of those two values still "
                "fails, so the exemption cannot hide a real excursion. "
                "WHAT TO READ FIRST on the first campaign: the "
                "`single-source 0/1 candidates ARMED` fragment of the summary "
                "line, which carries offered / admitted / committed and the "
                "refusal reason census. A leg that admits nothing is not a "
                "failure - it is the rollout-time cut guard doing its job - "
                "but it makes every other number here a two-source number. "
                "⚠️ The equivalent hydrogen is the result and this h2 band is "
                "NOT: the offline pair reads eq-H2 0.016257 against "
                "`ems-mpc-det`'s 0.016327 at lambda 0.41, a 0.43 % gain, "
                "while the hydrogen alone falls 49 %."))

# ── ems-mpc-cross: the switching-surface stimulus ───────────────────────────
FAULT_EXPECTATIONS["ems-mpc-cross"] = _mpc_expectation(
    scenario="ems-mpc-cross", walk_h2=0.008782, duration_s=200.0,
    # ⚠️ RE-DERIVED 2026-09-02 AND LOWERED, 0.12 -> 0.05. The leg binds
    # `mpc-sto` now, and the stochastic law walks a share range of only
    # 0.0875 on this two-level cruise — BELOW the pre-swap 0.12 floor, which
    # would have failed a correct run. (0.0833 before the band widening of
    # the same date; it is ONE LADDER STEP either way, and the widening moved
    # the operating point down onto the 0.15 rail rather than widening the
    # walk — the range is a step, not a span.) The mechanism is the demand model,
    # not the plant: `mpc-sto` plans against the TPM's conditional mean,
    # which smooths the two cruise levels this stimulus exists to separate,
    # so it commands a narrower walk across the same operating region.
    # 0.05 is ~0.6x the walk and still refuses a constant command.
    # ⚠️ RE-DERIVED FROM A POST-WIDENING WALK AND HELD AT 0.05 (2026-09-03,
    # campaign 20260902_220604 F6). The walk at the shipped ladder commands
    # min 0.1500 / max 0.2375, i.e. a range of EXACTLY 0.0875 = one ladder
    # step, and the live run reproduced it (0.1500 on 99.45 % of ticks,
    # 0.2375 on 1010 ticks - one 1.01 s excursion). 0.05 is 0.57x that.
    # NOT RAISED: the walk's range IS one ladder step, so any floor above
    # 0.0875 asserts a second step this stimulus does not produce, and a
    # floor just under it would be decided by whether that single excursion
    # happens to land inside the window.
    survive_t=180.0, run_window=(5.0, 190.0), share_range_min=0.05,
    pred_err_max=0.30, budget_hit_max_ticks=190000, charge_edges=6,
    min_rows=150000, h2_floor_informational=True,
    extra_note=("The `ems-sdp-cross` stimulus with the MPC's own "
                "`mpc_soc_ref_offset` at that scenario's +0.0025. PHASE-FREE "
                "CHECKS ONLY: the 1 Hz decision clock is not locked to the "
                "stimulus, and a phase-locked check has already failed a "
                "correct board on this very scenario (campaign "
                "20260901_024231). The walk's commanded share walks CONTINUOUSLY "
                "over a 0.25 range, unlike the SDP's single sharp flip, so the "
                "degenerate-constant guard is set at half of that. This leg is "
                "also the round's SEARCH-DEPTH evidence: a 1e5 ms budget moves "
                "its hydrogen -21 %% while its equivalent hydrogen moves 0.13 "
                "%%, so its h2 band is the widest claim the quantity supports. "
                "Note the walk's open-loop hold fraction here is 0.629, the "
                "highest of the four legs: most of this run is share-blind by "
                "construction (design section 7.4.3), so an improvement or a "
                "regression confined to it is invisible. The delta-SoC-matched "
                "DP bound at the walk's terminal state is stored in "
                "tools/dp_db. "
                "FIRST LIVE RESULT (campaign hil_report_20260902_011926): this "
                "leg FAILED its h2 floor by 0.13 %% of the band edge — windowed "
                "h2 0.0105875032 g against the 0.010601 floor, i.e. -25.09 %% "
                "of the walk where the band allows -25.00 %%. THE BAND IS "
                "DELIBERATELY NOT WIDENED: `mpc-det` matched its walk to "
                "+0.05 %% on `ems-mpc` and -0.42 %% on the FTP-75, so a -25 %% "
                "miss on THIS stimulus is a real divergence of the live MPC "
                "from its walk, not band noise. The live run stepped the share "
                "monotonically 0.50 -> 0.25 with zero upward moves and zero "
                "charge windows — but no 'the MPC declined to charge' reading "
                "follows, because MPC_CAMPAIGN_MAX_CANDIDATES was 343 (ONE "
                "charge option's enumeration) and every capped decision was "
                "truncated BEFORE the charge axis. The cap is 1029 from "
                "2026-09-02; RE-RUN THIS LEG CAP-LIFTED and re-derive the walk "
                "before touching the band. `ems-mpc-det` carries the twin "
                "reading (-13.2 %% of its walk, inside the band and therefore "
                "never surfaced) — the two together point at the WALK. "
                "SECOND LIVE RESULT (campaign hil_report_20260902_041414, "
                "cap-lifted): the same floor was cleared by +0.10 %% of the "
                "band edge. The two campaigns therefore straddle the edge by "
                "~0.1 %% in each direction, i.e. THE BAND EDGE SITS INSIDE THIS "
                "LEG'S RUN-TO-RUN SPREAD and a verdict on it scores noise. The "
                "floor is INFORMATIONAL from 2026-09-02 (evaluated, reported, "
                "WARNING on a miss, never a failure) until the cap-lifted walk "
                "re-band lands; the CEILING is untouched and still fails."))

# ═══════════════════════════════════════════════════════════════════════════
# ems-ftp75c-*: THE COMPRESSED CYCLE ON THE COMPENSATED ROAD LOAD
#     (2026-09-02; docs/modeling/ftp75c_regen_cycle_design_20260902.md)
#
# ⚠️ EVERY BAND IN THIS SECTION IS PROVISIONAL AND EVERY NUMBER IS A WALK
# PREDICTION.  No campaign has run any of these five legs, the plant
# configuration they run on has never been exercised, and two of the constants
# the whole harvest column is linear in - ETA_REGEN 0.80 and
# VESC_REGEN_I_MAX_A 1.5 - remain TODO(verify).  A first-campaign miss here is
# a calibration event by default; treat it as a defect only after the walk has
# been re-derived against the measured trace.
#
# ⚠️ THE `I_fc` BANDS ARE RE-DERIVED DOWNWARD, NOT CARRIED OVER.  Road-load
# compensation cuts the tractive demand by roughly 4.5x: the compensated cycle's
# PEAK source total is 0.3311 A against 0.9603 A on the uncompressed rig cycle,
# so the `ems-ftp75-*` floors are unreachable here by construction.  Carrying
# `ftp_fc_carried`'s 0.40 A floor across, for instance, would fail a correct
# board on every tick of every leg.  LIMIT_I_FC_MAX 1.4 A is never approached -
# the worst case is 21 % of it, on the `sdp-v6` leg's 0.85 share rail.
#
# ⚠️ DO NOT ASSERT SoC DIRECTION ON THESE LEGS.  docs/HIL_SCENARIOS.md already
# states this for `regen-harvest-true`, and it applies with more force here: the
# whole regen credit is +1.173 C, a SoC gain near +6.5e-5, against a cycle drain
# near -0.0019.  The credit is 1.4 % of the drain and is invisible in the SoC
# trace.
# ═══════════════════════════════════════════════════════════════════════════

# The Run window, and the survive bound inside it.  RUN_EXIT is 176.0 s and the
# table's last point is 175.0 s, so 150.0 leaves the whole high-speed half of
# the cycle behind the assertion while staying clear of the Finish transition.
_FTP75C_RUN_W = (5.0, 175.0)
_FTP75C_SURVIVE_T = 150.0
# WINDOW 5 of the nine commanded regen windows, 62.200 .. 67.299 s.  The FIRST
# LONG one (5.1 s), which matters because the Ag105 burns roughly the first
# 0.9 s of every window in the chopper (AG105_SETTLE_S 0.5 s plus the
# AG105_TAU_S 0.4 s ramp): windows 3 and 4 are 0.6 s each and deliver
# essentially nothing, and are retained only so the switch and path coverage
# exists.  The check window is opened 0.2 s either side of the commanded one so
# a sub-tick phase offset cannot decide the verdict.
_FTP75C_W5 = (62.5, 68.0)
_FTP75C_PROVISIONAL = (
    "ONE CAMPAIGN (hil_report_20260902_220604, the first on a "
    "road-load-compensated plant). The bands were governor-walk predictions and "
    "the campaign confirmed the SHAPE of the model: 6 REGEN windows carrying "
    "19.21-19.25 s against a modelled 6 / 19.6 s, chopper 5.4558-5.4911 J "
    "against a 2.5 J floor, drive-peak I_fc within +1.6 to +4.3 % of the walk "
    "on all four legs. The harvest column is LINEAR in ETA_REGEN (0.80, "
    "TODO(verify)) and roughly linear in VESC_REGEN_I_MAX_A (1.5 A, "
    "TODO(verify)). ONE MODELLED FIGURE DID NOT HOLD: the walk BANKS the credit "
    "from the first tick of a window while the plant burns ~0.9 s of every "
    "window in the chopper, and the realizable fraction MEASURED 0.63 against "
    "the modelled 70.7 % -- 0.734-0.737 C to the pack per cycle against the "
    "walk's ~1.17 C. The cause is the WINDOW-LENGTH DISTRIBUTION (four windows "
    "of 1.0-1.6 s against the ~0.9 s dead time), not either TODO(verify) "
    "constant. A second campaign settles whether these are pins or a spread.")


def _ftp75c_regen_signals():
    """The four checks that make the REGEN PATH observable.  PURE.

    ONE BUILDER for all five legs, for `_mpc_expectation()`'s reason: the regen
    path is driven by the COMMON regen manager and is therefore
    STRATEGY-INDEPENDENT by construction, so every leg must assert exactly the
    same four things.  Five hand-written copies would be five places for one of
    them to drift, and a drift here would read as a strategy difference that
    the design explicitly says cannot exist."""
    return [
        # 1. THE REGEN PATH WAS ACTUALLY OPEN, as an AGGREGATE duty rather than
        #    a phase-locked window assertion (the standing guidance: the
        #    decision and stimulus clocks are not locked, and a phase-locked
        #    check has failed a correct board before). 20 000 ticks is 20 s
        #    against a modelled 19.6 s of commanded duty across six windows, a
        #    31 % margin.
        {"name": "ftp75c_regen_duty", "switch_bit": SW_REGEN,
         "min_ticks": 15000, "t_window": _FTP75C_RUN_W,
         "provisional_note": _FTP75C_PROVISIONAL,
         "label": "REGEN_ENABLE was open for at least 15 s of the cycle "
                  "(modelled 19.6 s over six windows, a 30 % margin). The "
                  "FIRST drive-cycle leg on this rig that opens the regen "
                  "path at all. RE-DERIVED (H1, 2026-09-02): the windows are "
                  "trimmed against the FIRMWARE's own regen test with a 2x "
                  "margin, not against `force < 0`, which cost 28.4 -> 19.6 s "
                  "of commanded duty and removed three windows"},
        # 2. ... AND ENERGY ACTUALLY REACHED THE PACK THROUGH IT. A closed
        #    switch with no current behind it satisfies check 1 and nothing
        #    else, which is why this one is separate.
        {"name": "ftp75c_regen_charge", "column": "I_charge",
         "min_value": 0.06, "t_window": _FTP75C_W5,
         "provisional_note": _FTP75C_PROVISIONAL,
         "label": "the Ag105 delivered charge current inside the cycle's "
                  "first long regen window (>= 0.06 A; modelled peak 0.124 A, "
                  "so the floor carries a factor of two)"},
        # 3. THE CHOPPER TOOK THE RESIDUAL — moved OUT of this list on
        #    2026-09-03; see `_ftp75c_regen_events()` below.
        # 4. V-MOT ACTUALLY LIFTED ONTO THE CLAMP. This is what distinguishes
        #    real energy capture from a closed switch with a dark node, and it
        #    is the one check here that cannot be satisfied by bookkeeping.
        {"name": "ftp75c_node_lift", "column": "V_rgn", "min_value": 17.9,
         "min_ticks": 400, "t_window": _FTP75C_W5,
         "provisional_note": _FTP75C_PROVISIONAL,
         "label": "V-MOT lifted onto the 18.1 V chopper clamp for at least "
                  "400 ms of the first long regen window"},
    ]


def _ftp75c_regen_events():
    """The chopper-energy aggregator every ftp75c leg carries.  PURE.

    ⚠️ THIS LIVES IN `events_require`, NOT IN `signals_require`, AND THE
    SEPARATION IS THE WHOLE POINT OF THE FUNCTION (campaign
    hil_report_20260902_220604, `signal_the`).  The spec was written into
    `_ftp75c_regen_signals()` and could not pass on any run on any board:
    `scan_signals()` reads columns, so an aggregator with no `column` records
    nothing and `min_value` then fails an unmeasured peak by design; with no
    `name` key `judge_signals()` named the check from the label's first word
    ("the"); and the `total_of`/`max_of` shape guard iterated `events_require`
    only, so no import guard saw it.  The physics cleared the floor 2.2x on all
    five legs (measured 5.4558-5.4911 J against the 2.5 J floor), so the FLOOR
    IS UNCHANGED — only the list it sits in.  The import guards added in the
    same round refuse both halves of the mistake for good.

    The `regen-harvest-true` sibling carries the identical spec shape in the
    right list; that entry is what this one should have been copied from.

    ⚠️ THE MOVE COUPLES THESE LEGS TO THE HI-FI ENGINE, and the coupling is
    stated rather than left to be discovered.  Only the hi-fi engine emits
    `events.jsonl`, so under `--electrical-pref simple` this check has no
    stream to aggregate.  Four of the five legs declare `electrical: any`
    (`ems-ftp75c-dp` declares `hifi`), and the suite's default preference IS
    `hifi`, so a normal campaign is unaffected; a deliberate simple-engine run
    of this family will fail here.  That is the same trade `regen-harvest-true`
    already makes and documents ("hi-fi is REQUIRED, not preferred"), and it is
    strictly better than the alternative, which was a check that failed on
    EVERY engine."""
    return [
        # `total_of` and not `max_of`: the latter bounds the largest single
        # COALESCED episode rather than a per-window sum, which on a nine-window
        # cycle is the weaker of the two statements.
        {"total_of": "chopper_clamp", "field": "energy_j", "min_value": 2.5,
         "provisional_note": _FTP75C_PROVISIONAL,
         "label": "the braking chopper burned at least 2.5 J of residual "
                  "(modelled 4.2 J in-window plus 0.5 J outside; MEASURED "
                  "5.4558-5.4911 J across the five legs in campaign "
                  "20260902_220604 and 5.24-5.49 J in campaign E "
                  "20260903_031220 - two campaigns, one band, floor cleared "
                  "2.1x on the worse of them - of which 1.60-1.63 J fell "
                  "OUTSIDE the "
                  "windows — the bleed-era shift, 3.2x the 0.5 J model, "
                  "because with R_NODE_BLEED_OTHER 60 kOhm the RGN node parks "
                  "at 18.10 V between windows and the chopper trickles "
                  "~11 mW). The chopper is a RESIDUAL absorber, not a prior "
                  "claimant, so this is evidence of harvest and not of loss"},
    ]


def _ftp75c_expectation(*, scenario, ems, i_fc_peak_walk, extra=(), note=""):
    """One `ems-ftp75c-*` leg's expectation entry.  PURE.

    `i_fc_peak_walk` is the leg's OWN modelled peak FC current - the four legs
    command four different splits of one 0.3311 A source total, so a single
    shared ceiling would be either vacuous on the `mpc-sto` leg (walk 0.0912 A)
    or a tripwire on the `sdp-v6` one (0.2872 A; walked on `sdp-v4`, which
    agrees with `sdp-v6` on every row this leg traverses). The ceiling is set
    at 2x the leg's walk peak, which is a BUDGET bound with wide slack rather than a
    tracking assertion; the tracking statement on this family is the frontier's,
    not a current floor's."""
    ceil = round(2.0 * i_fc_peak_walk, 4)
    sigs = [
        # CADENCE first, so every window-scoped bound below is judged on a real
        # run rather than satisfied vacuously by a CSV that stops early.
        {"name": "ftp75c_cadence", "min_rows": 140000,
         "t_window": _FTP75C_RUN_W,
         "label": "the Run window carries at least 140 000 CSV rows (170 s at "
                  "1 kHz is ~170 000), so the bounds below are judged on a "
                  "complete cycle"},
        # THE CYCLE RAN TO ITS PEAK. The compressed profile puts the 56.7 mph
        # maximum on exactly 3.0 m/s at emitted t = 125.0 s; 2.85 is 0.95 of
        # that and unreachable by any other part of the cycle.
        {"name": "ftp75c_peak_commanded", "column": "cmd_v_sp",
         "min_value": 2.85, "t_window": (120.0, 130.0),
         "label": "the compressed FTP-75 peak (3.0 m/s at t = 125 s) was "
                  "commanded"},
        # THE FC CHANNEL STAYED INSIDE ITS BUDGET. A CEILING and not a floor:
        # on this plant the whole cycle sits at ~20 % of LIMIT_I_FC_MAX, so a
        # floor would assert a share the compensated demand cannot produce.
        #
        # ⚠️ SPLIT INTO TWO ARMS (2026-09-03, campaign 20260902_220604), the
        # `socband_fc_peak_bounded` shape applied to this family for the same
        # reason.  The single 2x-walk ceiling FAILED `-5050` (+4.58 %) and
        # `-socband` (+2.86 %) on a correct board and a correct plant: on ALL
        # FIVE legs the in-window `I_fc` maximum is a CHARGE-HANDOFF TRANSIENT
        # at t ~ 171.31 s with switch 0x35 (BT_BUS LOW — the
        # `assertFcChargeEnable()` exclusion, so the FC carries the load
        # single-source) and the vehicle STOPPED (v 0.090 m/s, p_mot 0), i.e.
        # aux 2.27-2.36 W plus the charger's bus draw at `I_charge` 0.38-0.40 A.
        # It is not the drive peak and the 2x-walk ceiling never described it.
        # Only two legs failed because their walk peaks are the lowest, which
        # makes the old check a threshold-ordering accident rather than a test.
        #
        # THE WALK'S DRIVE-PEAK MODEL IS ACCURATE and the arm that tests it is
        # unchanged: with `SW_FC_CHARGE` masked the drive peaks are 0.1844 /
        # 0.1898 / 0.2917 / 0.2536 A at t ~ 143.7 s (v 2.87 m/s) against walk
        # 0.1768 / 0.1856 / 0.2872 / 0.2490 (+4.3 / +2.3 / +1.6 / +1.8 %),
        # 47-95 % under their own ceilings.
        #
        # ARM 1 — the DRIVE budget, charge windows masked out. The 2x-walk bound
        # is UNCHANGED. `exclude_hold_ms` is 300 rather than the socband
        # family's 10 because the DECAY TAIL here is long: the charger's bus
        # draw does not stop at the instant `FC_CHARGE_ENABLE` clears.
        # ⚠️ RATIONALE CORRECTED 2026-09-03 (review finding L4). It previously
        # read "the handoff windows are 0.08-0.28 s long and the longest
        # measured is 281 ms, so the hold has to cover the WHOLE transient".
        # Both halves were wrong. The hold runs AFTER the bit clears — the bit
        # itself is already masked, however long it stays set — and the longest
        # measured window is `ems-ftp75c-socband`'s 460.1 ms at
        # 163.5763-164.0364 s, not 281 ms (campaign 20260902_220604 FC_CHARGE
        # high spans: 79.8-100.1 ms at ~67.22 s, 200.0-281.2 ms at
        # ~171.05 s, plus that leg's two extra windows). 300 ms STANDS: it is a
        # settling allowance on the tail, and 460 > 300 does not weaken it.
        {"name": "ftp75c_fc_bounded", "column": "I_fc", "max_value": ceil,
         "t_window": _FTP75C_RUN_W,
         "exclude_when_switch_bit": SW_FC_CHARGE, "exclude_hold_ms": 300.0,
         "provisional_note": _FTP75C_PROVISIONAL,
         "label": "the FC channel stayed under %.4f A OUTSIDE the charge "
                  "windows - 2x this leg's own modelled peak of %.4f A, and "
                  "%.0f %% of LIMIT_I_FC_MAX 1.4 A. A BUDGET bound; the "
                  "compensated cycle's whole peak source total is 0.3311 A. "
                  "Ticks with FC_CHARGE_ENABLE set are excluded, plus a 300 ms "
                  "settling hold after each close (a tail allowance; the "
                  "measured charge windows themselves were 0.08-0.46 s long "
                  "in campaign 20260902_220604 and COLLAPSED to 18-20 ms - "
                  "one commander period, 0.38-0.47 mC - in campaign E after "
                  "the two-level regen release shipped, with the sdp leg "
                  "suppressing the 171 s window entirely; they are masked in "
                  "full either way), and are judged by "
                  "`ftp75c_fc_bounded_charging` instead"
                  % (ceil, i_fc_peak_walk, 100.0 * ceil / 1.4)},
        # ARM 2 — the CHARGE-WINDOW ceiling, whole-window and unmasked, exactly
        # as `socband_fc_peak_charging` is: a mask keeping ONLY charge ticks
        # would make the arm vacuous on a leg whose charge branch never opened.
        # A FIXED 0.60 A rather than a multiple of the walk peak, because the
        # quantity it bounds has nothing to do with the leg's commanded split -
        # it is aux plus the charger's own referred bus draw carried
        # single-source, and it is therefore the SAME on all five legs
        # (measured maximum 0.3818 A across them). 0.60 A is +57 % on that
        # measurement and 43 % under LIMIT_I_FC_MAX 1.4 A, so an FC channel
        # running away in a handoff still fails here.
        {"name": "ftp75c_fc_bounded_charging", "column": "I_fc",
         "max_value": 0.60, "t_window": _FTP75C_RUN_W,
         "provisional_note": (
             "TWO CAMPAIGNS (20260902_220604 and E, 20260903_031220). The "
             "bound is a fixed 0.60 A against a measured maximum of 0.3818 A "
             "over five legs, and the "
             "quantity is aux plus the charger's referred bus draw carried "
             "single-source after assertFcChargeEnable() drops BT - so it "
             "moves with ETA_CHG, with the Ag105 charge ceiling and with the "
             "bus voltage at the handoff, none of which this bound tracks. "
             "Re-derive it if any of the three moves."),
         "label": "the FC channel stayed under 0.60 A across the whole cycle, "
                  "INCLUDING the charge-handoff transients that arm 1 masks "
                  "out (measured maximum 0.3818 A over the five legs; 43 %% "
                  "under LIMIT_I_FC_MAX 1.4 A). The transient is aux plus the "
                  "charger's referred bus draw carried single-source, not the "
                  "share loop"},
    ]
    sigs.extend(_ftp75c_regen_signals())
    sigs.extend(extra)
    return {
        # `note` IS FOLDED INTO `source`, not carried as a field of its own.
        # An entry-level `note` key is DEAD: nothing in this module reads one -
        # not the judge, not the report renderer, not the schema - so five
        # blocks of expectation prose would have been written into the data
        # structure and rendered nowhere.  `_alpha_expectation()` below already
        # handles the same argument this way, and
        # `test_fault_expectations_schema_only_known_fields` is what refuses
        # the alternative.
        "source": ("hil_plant_sim.py SCENARIOS[%r] + the generated "
                   "tools/ftp75c_profile.py (EPA ftpcol.txt, sha256-verified, "
                   "raw t = 0..340 s at --time-factor 0.5) + the "
                   "`--drag scaled-air` road load + "
                   "docs/modeling/ftp75c_regen_cycle_design_20260902.md. %s"
                   % (scenario, note)),
        # FAULT-FREE IS THE EXPECTATION, with far more margin than any rig-drag
        # leg has: the peak source total is 0.3311 A against LIMIT_I_FC_MAX
        # 1.4 A. THE SPECIFIC LATCH TO WATCH is FAULT_SWITCH_CONFLICT (0x0008),
        # which would mean the regen manager provoked chargingControl()'s
        # CRUISE branch inside a braking window - i.e. asserted charge_goal
        # while the commanded motor current was still positive, which calls
        # assertFcChargeEnable(true), drops BT off the bus and creates the
        # single-source condition that has latched OC_FC before. It should
        # never fire; if it does, the window derivation
        # (hil_plant_sim.derive_regen_windows) is the first thing to re-derive.
        "allow_only": 0,
        "survive_to": {"t": _FTP75C_SURVIVE_T, "states": {2}},
        "signals_require": sigs,
        # The chopper aggregator is an EVENTS check; see
        # `_ftp75c_regen_events()` for why it is not in `sigs`.
        "events_require": list(_ftp75c_regen_events()),
    }


FAULT_EXPECTATIONS["ems-ftp75c-5050"] = _ftp75c_expectation(
    scenario="ems-ftp75c-5050", ems="hold-5050", i_fc_peak_walk=0.1768,
    note=("The constant-50/50 leg: any share deviation belongs to the "
          "firmware's share loop and the plant, never to the EMS. On THIS "
          "family it is also the cleanest read of the regen path, because "
          "`hold-5050` commands no charge_goal of its own at all - every "
          "assertion of it comes from the COMMON regen manager. Walk: h2 "
          "0.006288839 g, dSoC -0.001926, 1.1729 C to the pack."))

FAULT_EXPECTATIONS["ems-ftp75c-socband"] = _ftp75c_expectation(
    scenario="ems-ftp75c-socband", ems="soc-band", i_fc_peak_walk=0.1856,
    extra=[
        # THE CHARGE BRANCH MUST NOT SATURATE. This is the check the
        # per-scenario threshold override exists for, and it is the one place
        # this leg can fail in a way that invalidates the frontier rather than
        # merely reporting a number: the tuple's REFERENCE must be the policy,
        # not a charge-saturated control.
        {"name": "ftp75c_socband_charged_at_all", "switch_bit": SW_FC_CHARGE,
         "min_ticks": 200, "t_window": _FTP75C_RUN_W,
         "provisional_note": _FTP75C_PROVISIONAL,
         "label": "the FC charge path opened AT ALL (>= 200 ms). ⚠️ THE "
                  "COMPANION OF THE CEILING BELOW, and the half that was "
                  "missing (H2, 2026-09-02): a ceiling alone is satisfied by "
                  "NEVER CHARGING, which is exactly what the first threshold "
                  "override produced - it put ENTER at 0.13373 A, BELOW this "
                  "cycle's own minimum source total of 0.15079 A, so the leg "
                  "opened ZERO windows against the rig leg's four and the "
                  "frontier's REFERENCE never exercised the soc-band "
                  "mechanism. A FAIL here means the thresholds are too LOW"},
        {"name": "ftp75c_socband_not_saturated", "switch_bit": SW_FC_CHARGE,
         "max_ticks": 120000, "t_window": _FTP75C_RUN_W,
         "provisional_note": _FTP75C_PROVISIONAL,
         "vacuity_note": (
             "DE-VACUATED BY `ftp75c_regen_duty` ON THE SAME COLUMN. Both "
             "specs read `switch_state`, and that one asserts at least 20 000 "
             "ticks with SW_REGEN SET over the same Run window, so a blank or "
             "absent switch column fails there before this ceiling can be "
             "satisfied by having no ticks at all. `ftp75c_cadence` closes the "
             "remaining case (a CSV that stops early)."),
         "label": "the FC charge path was NOT open for more than 120 s of the "
                  "170 s cycle. The shipped SOC_BAND_CHARGE_ENTER_ITOT_A "
                  "0.60 A sits ABOVE this cycle's entire source total (peak "
                  "0.3311 A), so without the per-scenario override (0.18074 A "
                  "enter / 0.33107 A exit) this leg would admit a window at "
                  "the first cruise sample and never exit it by current - "
                  "which would make it useless as the frontier's reference. "
                  "A FAIL here means the thresholds are too HIGH. The pair is "
                  "PERCENTILE-MATCHED against the rig leg (0.18074 A enter / "
                  "0.33107 A exit), not scaled by the drag ratio - the 0.15 A "
                  "auxiliary floor does not scale with the road load, and "
                  "dividing through it is what produced the zero-window "
                  "defect the companion check above now catches"},
    ],
    note=("The causal charge-sustaining policy and the frontier's REFERENCE "
          "leg, running PER-SCENARIO charge thresholds re-derived for the "
          "compensated demand: 0.60/1.30 A percentile-matched against the "
          "rig leg to 0.18074/0.33107 A. Walk: h2 0.006455604 g, dSoC -0.001859, "
          "zero charge windows under the DP mask. "
          "ACCEPTED CHARGE-FREE BY DESIGN (operator ruling 2026-09-03): the "
          "two genuine charge windows this leg opens on the board (0.20 s "
          "and 0.48 s) are shorter than the Ag105 settle and harvest "
          "nothing, so the reference is charge-free in energy terms. That is "
          "accepted as-is - no minimum charge dwell and no widened exit "
          "threshold will be added, because constraining how a policy pulls "
          "OUT of charge mode would change the reference's decision law."))

FAULT_EXPECTATIONS["ems-ftp75c-sdp"] = _ftp75c_expectation(
    scenario="ems-ftp75c-sdp", ems="sdp-v6", i_fc_peak_walk=0.2872,
    note=("The `sdp-v6` policy on the compressed cycle, and the frontier's "
          "CANDIDATE leg. ⚠️ NO NEW SDP ARTIFACT WAS SOLVED FOR THIS "
          "STIMULUS, deliberately: the regen credit enters through the PLANT "
          "and the pack, not through the policy's decision law, and the "
          "artifact's own axes (relative SoC and a demand bin) are stimulus- "
          "independent by construction. Re-solving it would have produced a "
          "second artifact that differs from the shipped one only in the "
          "demand map it was fitted on, with no campaign able to tell the two "
          "apart. Walk: h2 0.009897751 g, dSoC -0.000476 - the policy holds "
          "its 0.85 share rail through the cycle, which is why it burns more "
          "hydrogen AND drains far less pack than the reference. "
          "⚠️ THE MATCHED-DP BASELINE IS NOT A BOUND ON THIS LEG, and the "
          "reason is structural rather than numerical: `sdp-v6` commands a "
          "CONSTANT 0.8500, which is 0.10 OUTSIDE the DP's own control grid "
          "[0.25, 0.75] (`gen_dp_ems_table.DP_SHARE_MIN/MAX`), so the solve "
          "cannot reproduce the policy's operating point and must hold the "
          "same terminal SoC more expensively, so the causal run BEATS its "
          "own 'lower bound' by ABOUT 3 % - and that figure must be "
          "RECOMPUTED FROM ONE TREE STATE before it is quoted, because the "
          "two sides were measured at different points in the round and a "
          "recomputation moved it. The stored record also did not converge "
          "(residual 2.49e-06 against 2.0e-06). The effect is PRE-EXISTING "
          "and is present on `ems-sdp` too; it is magnified here because "
          "this leg's near-zero drain pins the DP against the grid edge for "
          "the whole run. ⚠️ IT ALSO REACHES THE FRONTIER'S vs_bound "
          "ARM: the CANDIDATE commands 0.85 while the bound it is divided by "
          "was solved over [0.25, 0.75], so a vs_bound at or just above 1.0 "
          "on an SDP candidate is EXPECTED and is not evidence about the "
          "policy. See the finding and the operator TODO at DP_SHARE_MIN."))

FAULT_EXPECTATIONS["ems-ftp75c-dp"] = _ftp75c_expectation(
    scenario="ems-ftp75c-dp", ems="dp-replay", i_fc_peak_walk=0.2490,
    note=("The NON-CAUSAL lower bound, and the FIRST DP table ever solved "
          "WITH THE BRAKING CREDIT IN THE DEMAND MODEL "
          "(`--drag scaled-air --eta-regen 0.8`). That is the whole point of "
          "this leg: a credit-free table must buy with hydrogen the SoC the "
          "run gets back from braking, so its total is INFLATED and the run's "
          "deviation against it is flattered - the `regen_bound` correction "
          "`hil_report_analysis.matched_dp_for_run()` prices per run goes to "
          "zero here. ⚠️ THE BOUND IS NOT STRICTLY BELOW THE CAUSAL "
          "REFERENCE ON THIS STIMULUS: the offline solve reads the DP +0.06 % "
          "above the `soc-band` walk at matched terminal SoC (0.00598238 g "
          "against 0.00597881 g, residual +1.82e-06 SoC). That is the "
          "discrete control grid - LAMBDA_TERM to terminal SoC is monotone "
          "but not continuous - and it is why the tuple's vs-bound arm reads "
          "~1.01. Walk: h2 0.006619509 g, dSoC -0.001793."))

# ── ems-ftp75c-mpc: the compressed-cycle MPC candidate, behind --with-ftp75c
FAULT_EXPECTATIONS["ems-ftp75c-mpc"] = _mpc_expectation(
    scenario="ems-ftp75c-mpc", walk_h2=0.002028, duration_s=180.0,
    survive_t=150.0, run_window=(5.0, 175.0),
    # NO DEGENERATE-CONSTANT GUARD, and the absence is deliberate rather than
    # an omission.  The walk commands a CONSTANT 0.1500 for the whole cycle -
    # range exactly 0.0000 - because the compensated demand is low enough that
    # the planner rails to the battery-heavy end of its ladder and stays there.
    # (0.2500 before the 2026-09-02 band widening; the rail moved with the
    # band, which is the widening working rather than a change of behaviour.)
    # That is the metric working, not a controller that has stopped deciding:
    # this leg drains the pack hardest (dSoC -0.003115 against the reference's
    # -0.001850) and burns the least hydrogen, and its eq-H2 is the lowest of
    # the four legs precisely because the two move together.  A
    # `share_range_min` here would fail a correct board on its first run.
    # ⚠️ IF A CAMPAIGN SHOWS THE SHARE MOVING, that is the finding - it would
    # mean the live plant's demand is materially above the walk's.
    share_range_min=None,
    pred_err_max=0.30, budget_hit_max_ticks=126000, charge_edges=6,
    min_rows=140000,
    extra_note=("The CANDIDATE leg of the `ftp75c-mpc` frontier tuple, gated "
                "behind --with-ftp75c. ⚠️ THE ONE THING THAT IS NEW ABOUT "
                "THIS MPC LEG and is true of no other: the planner's "
                "prediction model carries the REGEN CREDIT, so its charge "
                "enumeration runs against a mask that excludes every "
                "regen-capable stage (the exclusivity term - a stage cannot "
                "both FC-charge and regen-charge, which is the host-side "
                "image of assertFcChargeEnable()). The credit is "
                "SHARE-INDEPENDENT, so it cannot change which candidate the "
                "search prefers on a braking stage; what it CAN change is the "
                "terminal SoC the Huber cost is priced against. Read "
                "`mpc_share_pred_err` on this leg before reading its ratios. "
                "Walk: h2 0.003311646 g, dSoC -0.003127, zero charge windows, "
                "peak I_fc 0.0912 A - the lowest FC current of any registered "
                "drive-cycle leg."))
# THE FOUR REGEN OBSERVABLES, appended rather than built in: the regen path is
# driven by the COMMON manager and is strategy-independent by construction, so
# this leg must assert exactly what its four siblings do.  `_mpc_expectation()`
# takes no extra-signal argument (its four callers before this one needed
# none), and giving it one would change a builder four other legs depend on for
# a single caller's benefit.
FAULT_EXPECTATIONS["ems-ftp75c-mpc"]["signals_require"].extend(
    _ftp75c_regen_signals())
# ── THE RAIL, MADE OBSERVABLE (2026-09-03, campaign 20260902_220604) ──────
# This leg carries no `share_range_min` (see the block above: the walk
# commands a CONSTANT 0.1500 for the whole cycle, range exactly 0.0000, and a
# motion floor would fail a correct board on its first run). The campaign
# then measured exactly that -- `cmd_share_sp` 0.1500 on 175 000 of 175 000
# ticks -- and NOTHING IN THE ENTRY SAID SO, so the only check that mentioned
# the rail was the stale floor that failed it.
#
# THE MARKER IS INFORMATIONAL, and deliberately: it is EVALUATED and REPORTED
# and WARNS on a miss, but never fails the run. The entry's own note already
# says that a moving share here IS the finding (it would mean the live
# plant's demand is materially above the walk's), and a finding is something
# an analyst reads, not something a correct board is failed for.
# THE BOUND is the low rail plus HALF a ladder step (0.15 + 0.0875/2), so it
# is missed by the first rung the planner could move to and by nothing less.
# It evaluates to 0.1937 (L5, 2026-09-03 — an earlier note quoted 0.194); the
# value is pinned in `test_run_hil_suite.py` so the band or the ladder cannot
# move it silently.
FAULT_EXPECTATIONS["ems-ftp75c-mpc"]["signals_require"].append(
    {"name": "ftp75c_mpc_share_railed_low", "column": "cmd_share_sp",
     "max_value": round(_MPC_SHARE_BAND[0]
                       + 0.5 * (_MPC_SHARE_BAND[1] - _MPC_SHARE_BAND[0]) / 8.0,
                       4),
     "t_window": (5.0, 175.0),
     "informational": True,
     "provisional_note": _MPC_PROVISIONAL,
     "label": "OBSERVABILITY MARKER, never a failure: the commanded share "
              "stayed on the ladder's LOW RAIL for the whole cycle, which "
              "is what the walk predicts (a constant 0.1500, range 0.0000; "
              "campaign 20260902_220604 measured 0.1500 on 175 000 of "
              "175 000 ticks). A WARNING here means the share MOVED, i.e. "
              "the live plant's demand is materially above the walk's - "
              "which is a finding to read, not a board defect"})
# ... and the chopper aggregator, into the list it belongs in.  `_mpc_expectation()`
# builds no `events_require`, so this leg gets one here.
FAULT_EXPECTATIONS["ems-ftp75c-mpc"].setdefault("events_require", []).extend(
    _ftp75c_regen_events())

# ── ems-ftp75-mpc: the drive-cycle candidate, behind --with-ftp75 ───────────
FAULT_EXPECTATIONS["ems-ftp75-mpc"] = _mpc_expectation(
    scenario="ems-ftp75-mpc", walk_h2=0.018762, duration_s=350.0,
    # RE-DERIVED 2026-09-02 for the `mpc-sto` binding: walk range 0.2500,
    # floor ~0.6x.
    survive_t=330.0, run_window=(10.0, 340.0), share_range_min=0.15,
    pred_err_max=0.30, budget_hit_max_ticks=245000, charge_edges=8,
    min_rows=280000,
    extra_note=("The CANDIDATE leg of the `ftp75-mpc` frontier tuple, gated "
                "behind --with-ftp75. The walk lands eq-H2 0.055751 against "
                "the `ems-ftp75-socband` reference's 0.057254 (0.974x) and "
                "within 2e-6 g of `ems-ftp75-sdp`'s 0.055750 — the two "
                "controllers reach the same value on this stimulus by "
                "different pairs, which is what the eq-H2 metric is for. The "
                "`ems-ftp75-dp` bound is PENDING a table regeneration (its "
                "shipped table's stimulus fingerprint is stale), so the "
                "vs-bound arm of this tuple has no offline prediction yet, and "
                "no dp_db entry is prefilled for this leg. 64.5 %% of this "
                "cycle's Run window sits below the 0.55 A open-loop line, "
                "where the delivered split does not follow the command at "
                "all."))


# ═════════════════════════════════════════════════════════════════════════════
# THE THREE ALPHA-SWEEP LEGS (WP-1C, 2026-09-02) — opt-in behind --with-alpha
#
# One run per BEHAVIOUR LEG of the eta-era alpha sweep
# (tools/sdp_policies/sweep_20260902_eta088/, picks in its live_picks.json),
# all three on the `ems-sdp` stimulus so the only difference between them — and
# between them and `ems-sdp` itself — is the artifact's alpha:
#
#   greedy  idx 3,  alpha 0.073936  0 charge cells, share map DEGENERATE
#                   (alpha under the share lever's admission threshold
#                   0.111000013, so the policy asks for the battery rail
#                   everywhere and the SoC axis carries no information)
#   cal     idx 7,  alpha 0.118326  0 charge cells; its POLICY BLOCK IS
#                   sdp_policy_v4's, so this leg is a same-stimulus repeat of
#                   `ems-sdp` and its value is exactly that: a second reading
#                   of one law, which is what the other two are measured against
#   charge  idx 14, alpha 0.248413  591 charge cells (alpha past the charge
#                   lever's admission threshold 0.239249990), so this is the
#                   only leg of the three that opens the charger path
#
# ⚠️ EVERY BOUND HERE IS PROVISIONAL AND OFFLINE. No campaign has run any of
# the three. The h2 bands are the sweep's own governor-walk totals +/- 25 %
# (live_picks.json `walk_h2_g["ems-sdp"]`, walked with the governor at the
# symmetric dv0); every other bound is inherited from `ems-sdp`, which shares
# the stimulus and the charge ceiling, with its derivation cited.
#
# WHY THE CHECKS ARE SHAPED THIS WAY. The campaign-024231 S2 FAIL is the
# precedent: a position/absence assertion at a model-predicted instant fails on
# MODEL error while the mechanism works. So the discriminating checks here are
# phase-free — a level band on the commanded share over a wide window, an edge
# COUNT band on the charge path, and a two-sided total — and none of them names
# an instant. The `ems-sdp` open-loop-hold caveat applies unchanged: below the
# firmware's 0.55 A drop-out the delivered split is whatever stood, so nothing
# below asserts a DELIVERED share.
_ALPHA_PROVISIONAL = (
    "no campaign has run this scenario. The h2 band is the alpha sweep's own "
    "governor-walk total +/- 25 % (tools/sdp_policies/sweep_20260902_eta088/"
    "live_picks.json, eta 0.88 era); every other bound is inherited from "
    "`ems-sdp`, which shares this stimulus and its 0.8 A charge ceiling. "
    "Re-derive all of them from the first campaign that runs the alpha legs")

# The shared OC budget. `ems-sdp-cross` MEASURED 1.1920 A at this stimulus's
# single-source charge operating point. Two of these three legs never open the
# charger at all and the third opens it at the same 0.8 A ceiling, so one bound
# serves all three. See `sdpx_fc_peak_bounded` for the charger-era note:
# post-eta the expected peak is ~0.84 A, so this is a budget bound with slack,
# not a tripwire.
#
# -- RE-DERIVED 2026-09-02, AND FROM THE FAULT LIMIT ------------------------
# The value was a hand-typed 1.28 A. It is now DERIVED, at
# LIMIT_I_FC_MAX - _ALPHA_FC_MARGIN_A = 1.4 - 0.10 = 1.30 A.
#
# WHY THE FAULT LIMIT AND NOT THE fw v26 CEILING. An earlier form of this
# re-derivation wrote SHARE_GOV_I_FC_CEIL_A + SHARE_GOV_CEIL_HYST_A, which is
# also 1.30 A but says the wrong thing. These three legs reach their fuel-cell
# peak inside a SINGLE-SOURCE charge window, where `assertFcChargeEnable()` has
# dropped BT off the bus: I_fc equals I_tot, the ratio is pinned at
# DROOP_R_MIN, and the fw v26 clamp is STRUCTURALLY INERT. Tying the bound to
# the clamp's constants would make a ceiling retune move a check the ceiling
# does not govern. LIMIT_I_FC_MAX is what the hardware enforces here, and it is
# what this bound is a margin under.
#
# THE MARGIN. 0.10 A, chosen against the two measurements that bracket this
# operating point: `ems-sdp-cross` MEASURED 1.1920 A at the single-source charge
# peak, and `ems-sdp`'s own governed peak is 1.1866 A (campaign
# 20260831_191509). 1.30 A is 9.1 % above the governing 1.1920 A and 7.1 % under
# the fault limit -- a budget bound with slack rather than a tripwire, which is
# what the trio needs. Post-eta the expected peak is ~0.84 A, so the slack is
# larger than the numbers above suggest.
_ALPHA_FC_MARGIN_A = 0.10
_ALPHA_FC_CEIL = LIMIT_I_FC_MAX_A - _ALPHA_FC_MARGIN_A            # 1.30 A


def _alpha_expectation(walk_h2_g, share_spec, charge_edges, note):
    """One alpha-leg entry.  PURE.

    Built from a helper rather than written out three times so the three legs
    cannot drift apart on the bounds they are supposed to SHARE — the whole
    point of the trio is that only alpha differs. `share_spec` and
    `charge_edges` are the two per-leg discriminators; `walk_h2_g` sets the
    +/- 25 % band."""
    lo, hi = 0.75 * walk_h2_g, 1.25 * walk_h2_g
    return {
        "source": ("hil_plant_sim.py SCENARIOS[...] (the `ems-sdp` stimulus "
                   "object, drain and 0.8 A charge ceiling) + the `sdp-sweep` "
                   "strategy playing one alpha point of "
                   "tools/sdp_policies/sweep_20260902_eta088/; bands from that "
                   "sweep's governor walk (docs/modeling/"
                   "sdp_alpha_sweep_eta088_20260902.md). " + note),
        "provisional_note": _ALPHA_PROVISIONAL,
        "allow_only": 0,              # expected completely fault-free
        # Same gate as `ems-sdp`: the run must still be in Run/Finish at t = 50,
        # past the drain plateau and into the low cruise, or the totals below
        # measure a truncated cycle.
        "survive_to": {"t": 50.0, "states": {2, 3}},
        "signals_require": [
            # 0. THE CADENCE CENSUS, so nothing below can pass on a run whose
            #    observation stream stalled. Its own spec: `min_rows` returns
            #    before every value and tick bound.
            {"name": "alpha_cadence", "min_rows": 1000,
             "t_window": (10.0, 50.0),
             "label": "the run streamed at full cadence across the drain and "
                      "cruise segments (>= 1000 rows in a 40 s window)"},
            # 1. THE STIMULUS WAS DELIVERED — inherited verbatim from
            #    `ems-sdp`'s `sdp_drive_commanded`. It asserts the SHARED half
            #    of the trio, so a leg that differs here differs in something
            #    other than alpha and none of the comparisons are valid.
            {"name": "alpha_drive_commanded", "column": "cmd_v_sp",
             "min_value": 1.45, "t_window": (12.0, 30.0),
             "label": "the shared `ems-sdp` drive cycle was commanded (the "
                      "trio's controlled variable is alpha and nothing else)"},
            # 2. THE PER-LEG SHARE SIGNATURE (see each call site).
            share_spec,
            # 3. THE OC BUDGET, as a named bound rather than an OC_FC latch.
            {"name": "alpha_fc_peak_bounded", "column": "I_fc",
             "max_value": _ALPHA_FC_CEIL, "t_window": (5.0, 54.0),
             "label": "the FC channel stayed inside the single-source charge "
                      "budget (<= %.2f A = LIMIT_I_FC_MAX - %.2f A; "
                      "`ems-sdp-cross` measured 1.1920 A at this operating "
                      "point and `ems-sdp`'s governed peak is 1.1866 A. The "
                      "fw v26 clamp is INERT here - the window is "
                      "single-source - so the fault limit is the only bound "
                      "the hardware enforces)"
                      % (_ALPHA_FC_CEIL, _ALPHA_FC_MARGIN_A)},
            # 4. THE CHARGE-PATH CENSUS — the trio's headline discriminator,
            #    and a COUNT rather than a window so a model error in WHEN the
            #    window opens cannot fail a run in which the mechanism worked.
            {"name": "alpha_charge_edge_census", "switch_bit": SW_FC_CHARGE,
             "edge_count_between": charge_edges, "edge": "rise",
             "t_window": (2.5, 54.0),
             "label": "FC_CHARGE opened %d-%d times — the artifact's own charge "
                      "map, observed on the board" % charge_edges},
            # 5-6. THE HYDROGEN TOTAL, two-sided. Two specs, because one spec
            #    cannot carry both bounds (`_judge_signal_leaf` returns on the
            #    first it matches and the import guard refuses the pairing).
            #    h2_cum_g is monotone, so the peak IS the final value.
            {"name": "alpha_h2_accounted", "column": "h2_cum_g",
             "min_value": lo,
             "label": "the H2 total accumulated to the walk's band "
                      "(>= %.5f g; governor walk %.5f g)" % (lo, walk_h2_g)},
            {"name": "alpha_h2_bounded", "column": "h2_cum_g",
             "max_value": hi,
             "label": "... and stayed under %.5f g, so a scale or accumulation "
                      "error fails here instead of reading as an alpha result"
                      % hi},
        ],
    }


FAULT_EXPECTATIONS["ems-sdp-alpha-greedy"] = _alpha_expectation(
    walk_h2_g=0.004093022760826734,
    # THE DEGENERACY, asserted as a CEILING over the whole post-command span.
    # At alpha 0.073936 the sweep's share map is 0 in every cell, so the policy
    # requests the battery rail everywhere and `cmd_share_sp` must never reach
    # the FC branch. 0.16 is `_SDP_LOW_RAIL_CEIL`, the same "battery-heavy
    # branch, sustained" figure the ftp75-sdp entry uses.
    # ⚠️ THE WINDOW STARTS AT 10.0, NOT AT 0. Before the first policy command
    # lands the board holds the firmware default 0.50, which a ceiling would
    # read as a violation. 10 s is ~100 decision stages in.
    share_spec={"name": "alpha_share_degenerate", "column": "cmd_share_sp",
                "max_value": _SDP_LOW_RAIL_CEIL, "t_window": (10.0, 54.0),
                "label": "the commanded share never left the battery rail — "
                         "the share map is degenerate at alpha 0.073936 (below "
                         "the 0.111000013 admission threshold), which is what "
                         "this leg exists to show"},
    charge_edges=(0, 0),
    note=("GREEDY leg, sweep index 3, alpha 0.073936, 0 charge cells."))

FAULT_EXPECTATIONS["ems-sdp-alpha-cal"] = _alpha_expectation(
    walk_h2_g=0.012602735460289607,
    # The FC rail IS reached: same 0.84 floor and same window as `ems-sdp`'s
    # `sdp_clamped_rail_commanded`, because this leg's policy block IS
    # sdp_policy_v4's. A disagreement between this check and `ems-sdp`'s is
    # therefore a finding about the RUN, not about the artifact.
    share_spec={"name": "alpha_share_high_rail", "column": "cmd_share_sp",
                "min_value": _SDP_HIGH_RAIL_FLOOR, "t_window": (5.0, 54.0),
                "label": "the commanded share reached the fuel-cell rail — the "
                         "calibrated point's law, identical to `ems-sdp`'s"},
    charge_edges=(0, 0),
    note=("CALIBRATED leg, sweep index 7, alpha 0.118326, 0 charge cells; its "
          "policy block is byte-identical to tools/sdp_policies/"
          "sdp_policy_v4.json's, so this is a same-stimulus repeat of "
          "`ems-sdp` and the two runs' h2 totals should agree."))

FAULT_EXPECTATIONS["ems-sdp-alpha-charge"] = _alpha_expectation(
    walk_h2_g=0.015064731516112779,
    # A HIGHER alpha prices SoC more dearly, so this leg asks for at least as
    # much fuel cell as the calibrated one: the same rail floor holds.
    share_spec={"name": "alpha_share_high_rail", "column": "cmd_share_sp",
                "min_value": _SDP_HIGH_RAIL_FLOOR, "t_window": (5.0, 54.0),
                "label": "the commanded share reached the fuel-cell rail (a "
                         "larger alpha prices SoC more dearly, so this leg "
                         "cannot ask for LESS fuel cell than the calibrated "
                         "one)"},
    # THE ONE LEG THAT CHARGES. The governor walk opens exactly ONE window on
    # this stimulus. The band is [1, 4], not [1, 1]: the firmware's cruise-guard
    # early-drop branch adds admit-then-drop blips that a rising-edge census
    # cannot tell from a sustained window — `ems-sdp-braking` measured five of
    # them on a four-window run — so the FLOOR is the assertion ("the charge
    # action reached the board at all") and the ceiling is a sanity bound.
    charge_edges=(1, 4),
    note=("CHARGE-ADMITTING leg, sweep index 14, alpha 0.248413, 591 charge "
          "cells; the only leg of the three whose artifact admits charging, "
          "and the governor walk opens one window on this stimulus. "
          "LEDGER (campaign hil_report_20260902_011926, first live run): the "
          "FC_CHARGE window-CLOSE at t = 55.348 s cut at i_cut 0.5093 A — the "
          "campaign's tightest reading against SHARE_CUT_MAX_HANDOFF_A 0.5 A, "
          "and it is on the CHARGER switch, which is outside "
          "`share_cut_load_hazard`'s FC_BUS/BT_BUS scope by design. Not a "
          "guard failure and not scored: assertFcChargeEnable() owns that "
          "switch and the fw v25 load guard is on the two BUS switches. "
          "Recorded so a future campaign reading 0.5x A there knows it is a "
          "repeat, not a new event. Three windows: 40.261-41.261 and "
          "56.348-57.348 (the 1 s decel blips the SDP_CHG_CRUISE_DELTA_MPS "
          "guard withdraws) plus the 13.09 s cruise window."))


# ══════════════════════════════════════════════════════════════════════════════
# mppt-tracking  —  the Ag105 MPPT input-voltage threshold, closed-loop
#
# ⚠️ THE OBJECTIVE INVERTED AT fw v24 (2026-09-01).  Read this before comparing
# any mppt-tracking result across the fw v23/v24 boundary.
#
# fw v23 AND EARLIER.  The module sat at its factory 18 V threshold (MPPTS open,
# AG105_Silvertel.pdf p.10); the FC path feeds it from the ~15.95 V bus, so the
# threshold BOUND; and because the firmware releases tracking only once the
# charger reports ready (ag105IsReady(), .ino:10249-10255), releasing it stopped
# the charging that made it ready and the two HUNTED.  Campaign 20260831_191509
# measured that on hardware: 138 MPPT_DISABLE toggles, ~40.05 ms median period.
# This entry's old checks ASSERTED that hunt — a tick CEILING of 2200 proving the
# pin toggled, and a FLOOR of 50 ticks of GENSTAT "Low Power" proving the module
# refused.
#
# fw v24.  ag105ManageMpptThreshold() writes reg 0x02 to (windowed-minimum V_chg
# − AG105_MPPT_MARGIN_V 3.0), quantized DOWN and clamped IN COUNTS to
# [AG105_MPPT_N_FLOOR 15, AG105_MPPT_N_CEIL 27] = 12.320-13.376 V
# (.ino:1671-1690).  The clamp CEILING is static_asserted below
# V_BUS_CHARGED_THRESH less the VBUS→VCHG-IN ideal-diode drop, so a threshold in
# force can never exceed a bus the staged bring-up called "up".  The module
# therefore stops refusing, ag105IsReady() holds, and the pin stays released for
# the rest of each charge window.
#
# ⇒ THE HUNT IS NOW THE FAILURE SIGNATURE.  Every check below that asserted its
#   PRESENCE is replaced by one that bounds its ABSENCE, and the positive
#   evidence moves to the new observation-frame field: `mppt_thresh_cnt`, the
#   reg-0x02 count the firmware reports it believes is in force (frame byte 15,
#   .ino:3115 / :3371; the HIL mirror that computes it, .ino:9066-9075).
#
# R1 IS NO LONGER A CONTINGENCY.  Table 7 encodes reg 0x02 values 0-250 as
# REGISTER mode and >=251 as the external MPPTS resistor, so a firmware write
# OVERRIDES any fitted resistor.  Whether the board fits one now only decides the
# threshold BEFORE the first write, which is the window the count checks below
# deliberately start after.
#
# WINDOWS ARE DERIVED from the imported stimulus geometry, never typed: the
# braking windows come from EMS_REGEN_BRAKE_WINDOWS and the charge-on-cruise
# windows from EMS_MPPT_CRUISE_WINDOWS inset by the strategy's own lead times.
_MPPT_BRAKE_W = EMS_REGEN_BRAKE_WINDOWS[0]                     # 14.0-16.1
# The FIRST cruise-charge window, inset the way the strategy insets it, then
# pulled in a further 0.1 s at each end so the command staircase and the board's
# reaction cannot decide a check at the boundary.
_MPPT_CRUISE_W = (EMS_MPPT_CRUISE_WINDOWS[0][0] + EMS_MPPT_CRUISE_LEAD_IN_S + 0.1,
                  EMS_MPPT_CRUISE_WINDOWS[0][1] - EMS_MPPT_CRUISE_LEAD_OUT_S - 0.1)
# ALL THREE cruise-charge windows, for the tick-counting checks: one 1.5 s window
# is thin once AG105_SETTLE_S (0.5 s) is spent, and the statistics are better read
# across all three.
_MPPT_ALL_CRUISE_W = (EMS_MPPT_CRUISE_WINDOWS[0][0],
                      EMS_MPPT_CRUISE_WINDOWS[-1][1])          # 16.1-41.0
# THE POST-FIRST-WRITE WINDOW, for the `mppt_thresh_cnt` specs.  The count is
# 0xFF (AG105_MPPT_N_RESISTOR — external-resistor mode / never written) from boot
# until the first tick on which the charger is both POWERED and SETTLED, which is
# ~AG105_SETTLE_S after the first cruise window's charge_goal.  Judging the count
# from the SECOND cruise window onward puts ~11 s of margin on that instant and
# keeps these specs from asserting anything about the pre-write value — which is
# legitimately 0xFF and must not read as a failure.  The count PERSISTS across the
# unpowered gaps between windows (EPROM semantics: the !powered path re-arms the
# session but deliberately KEEPS ag105MpptRegCnt, .ino:11410-11432), so the whole
# span carries a value, not just the charge windows.
_MPPT_THRESH_W = (EMS_MPPT_CRUISE_WINDOWS[1][0], _MPPT_ALL_CRUISE_W[1])   # 28.1-41.0
# ── PART B3 (C1 round, 2026-09-01) ──────────────────────────────────────────
# CRUISE-ONLY window for the OPERATING-POINT tripwire, and the braking window
# it deliberately excludes.
#
# WHY THE SPLIT.  `_MPPT_THRESH_W` runs to 41.0 s and therefore spans the
# 37.732-38.529 s BRAKING window.  Since the WP-C regen model landed, braking
# lifts V-MOT (and with it V_chg) onto the 18.1 V chopper clamp, so the HIL
# mirror's threshold count clamps to AG105_MPPT_N_CEIL 27 for the whole of it.
# That is 27 > 21 and it fails the tripwire on a CORRECT board.
#
# THE 27 IS A MIRROR ARTIFACT, NOT A BOARD READING.  Under HIL_SIM the .ino
# short-circuits the reg-0x02 write path and mirrors the count onto the
# observation frame directly (.ino:9066-9075).  The real manager EXCLUDES
# regen from its V_chg window sampling (.ino:11461-11467 and :11531-11534 via
# fcChargePathIsPowering(), .ino:11950; pinned by test_mppt_regen_excluded_from_window — the window minimum
# is sampled only while FC_CHARGE powers the charger), so a real board would
# never track the braking node's lift into its threshold at all. The mirror has
# no such exclusion, which is why the artifact exists only in emulation.
#
# The tripwire is therefore scoped to cruise, and the braking window gets its
# own pin ASSERTING the artifact at exactly 27 — so the day the mirror is
# taught the regen exclusion, this entry fails and gets rewritten rather than
# the change landing unobserved.
#
# ── THE LEFT EDGE MOVED (campaign 20260902_220604, `mppt_threshold_peak_tripwire`)
# The window used to open AT `EMS_MPPT_CRUISE_WINDOWS[1][0]` = 28.1 s, which
# excluded the BRAKING WINDOW but not the value the mirror CARRIES OUT OF IT.
# The HIL mirror is the INSTANTANEOUS V_chg recomputed on every settled POWERED
# tick and FROZEN across unpowered spans (EPROM semantics: the !powered path
# re-arms the session and deliberately KEEPS `ag105MpptRegCnt`). Between the
# braking window closing and the cruise charger settling there is a DARK GAP:
# REGEN closes, FC_CHARGE opens `EMS_MPPT_CRUISE_LEAD_IN_S` into the cruise
# window, and the count cannot move until `AG105_SETTLE_S` after that plus a
# poll. Campaign 20260902_220604 measured the frozen braking value 27 carried
# 849 ticks into the window (REGEN closes 28.0063 s, FC_CHARGE opens 28.4268 s,
# first mirror-live tick 28.9494 s) and the tripwire failed a correct board on a
# value the window was written to exclude.
#
# The left edge is now DERIVED from that geometry — lead-in, settle, and 0.2 s
# of poll/phase margin — so it opens after the mirror is demonstrably live. On
# mirror-live ticks the campaign's peak is 19, so the <= 21 band survives BOTH
# bleed eras UNCHANGED. In campaign 20260902_041414 the 2 kOhm bleed released
# the clamp mid-window and the carried value happened to be a benign 19; the
# leak existed there too and carried a number that did not fail.
_MPPT_THRESH_CRUISE_W = (EMS_MPPT_CRUISE_WINDOWS[1][0]
                         + EMS_MPPT_CRUISE_LEAD_IN_S + AG105_SETTLE_S + 0.2,
                         37.0)                                    # 29.1-37.0
# TRIMMED TO THE MEASURED PLATEAU (2026-09-02, campaign C item 3): the old
# right edge 38.529 overhung the clamp by ~62 ms, which is what made a per-tick
# floor unsatisfiable in the first place. Measured plateaus: 37.719-38.432
# (campaign 20260902_041414) and 37.729-38.463 (20260902_011926); (37.75,
# 38.44) sits inside BOTH with ~20 ms of lead-in margin and still contains
# 690 (011926) / 683 (041414) in-window ticks against the `min_ticks` 600
# dwell, both scored offline through scan_signals on the campaigns' own CSVs.
#
# BLEED-ERA ANCHORS for this scenario (campaign 20260902_220604, recorded so a
# later reader can tell an era shift from a regression): the braking window's
# clamp dwell is 1962 of 2100 ticks against campaign 20260902_041414's 1035 —
# with the 30/60 kOhm bleed the residual clamp no longer releases mid-window —
# the chopper burns 0.9132 J per window against 0.4908, and the FULL-RUN count
# of ticks at 27 is 6635 against 2164 (the intermediate ratchet bins 21-26
# vanish because the mirror never leaves the clamp mid-braking). The harvest
# operating point is UNMOVED at [15, 19].
_MPPT_THRESH_BRAKE_W = (37.75, 38.44)
# ~12.9 s of rows at the CSV's 1 kHz rate; 9000 is 70 % of them, leaving room for
# dropped observation frames while still FAILING LOUDLY on a run whose column is
# entirely blank — which is exactly what a campaign against a fw v21-v23 flash
# produces (16-byte frame, no byte 15, parse_output -> mppt_cnt None -> blank
# cell).  That failure mode is the point of the floor: a legacy run must not pass
# this entry by carrying no data.
# CALIBRATED 2026-09-01: measured 12900 of 12900 rows carried a value (the
# count PERSISTS, so every row in the span has one).  12600 is 97.7 % of
# that, keeping ~300 rows of dropped-observation-frame slack while still
# failing an entirely-blank fw v21-v23 run loudly.
_MPPT_THRESH_MIN_TICKS = 12600
# RELEASE FLOOR, RE-DERIVED FOR fw v24 AND DELIBERATELY UNCHANGED AT 300.
# Expected HIGH ticks are now ~3000, not ~1500: 3 windows x (1.5 s of charge_goal
# − 0.5 s AG105_SETTLE_S) = 3.0 s, HELD rather than chopped at 50 % duty.  The
# 1 s MPPT_RELEASE_HOLDOFF_MS does NOT eat into that: it arms only where a
# release is WITHDRAWN inside the cruise branch (.ino:10609-10616), and in the
# healthy case no release is ever withdrawn — each window ends through the
# charge_goal==0 branch, which clears mpptReleased WITHOUT arming the holdoff
# (.ino:10517-10518).  300 is therefore 10 % of the expectation, with the whole
# settle window and a full holdoff period of slack on top.
# WHY NOT RAISE IT.  A floor near 3000 would double as a hunt detector (a hunt
# yields ~1500), but that assertion now lives in the PHASE-FREE edge census
# below, which does not depend on duty, on the poll cadence, or on where in a
# window the release lands.  Keeping this one as the bare "it released at all"
# proof is the campaign-024231 lesson applied: do not encode a modelled phase in
# a bound that only has to prove existence.
_MPPT_TOGGLE_MIN_TICKS = 300
# EDGE CENSUS BAND — the replacement for the retired _MPPT_TOGGLE_MAX_TICKS 2200.
#
# DERIVATION, counting RISES (0 -> 1 on AUX_MPPT_DISABLE) inside
# _MPPT_ALL_CRUISE_W = 16.1-41.0 s:
#   * The three cruise-charge windows are EMS_MPPT_CRUISE_WINDOWS inset by
#     EMS_MPPT_CRUISE_LEAD_IN_S/_OUT_S -> [16.4, 17.9), [28.4, 29.9),
#     [39.4, 40.9).  Each contributes EXACTLY ONE rise: the pin is LOW at the
#     window's start (charge_goal is still 0 through the plateau's lead-in, and
#     the charger is dark for the first AG105_SETTLE_S after FC_CHARGE opens, so
#     ag105IsReady() is false either way), goes HIGH once the module reports
#     charging, and stays HIGH until charge_goal drops at the window's end.
#   * The two braking windows inside the span (26.0-28.1, 37.0-39.1) contribute
#     NONE: chargingControl()'s regen branch drives MPPT_DISABLE LOW
#     unconditionally (.ino:10550-10551).
#   * The census window OPENS with the pin LOW, and the first in-window sample
#     only ESTABLISHES the level, so no phantom edge is counted.
# => 3 rises.  The band's FLOOR is that exact prediction: a window that never
# releases is a real failure, and `mppt_released` is the other half of the same
# assertion.  The CEILING of 8 admits up to five extra readiness flaps — a
# GENSTAT transient, one holdoff-bounded re-assert per window — while sitting
# ~9x below the fw v23 hunt, whose 138 toggles are ~69 rises.  A regression to
# the hunt cannot pass this band at any duty cycle.
# CALIBRATED 2026-09-01 from campaign hil_report_20260901_080905 (measured 3
# rises, exactly the structural prediction above).  The provisional (3, 8)
# ceiling admitted five phantom flaps that never occurred; 5 keeps two of
# them as slack while sitting ~14x below the fw v23 hunt's ~69 rises.
_MPPT_RISE_BAND = (3, 5)
# ⚠️ WP-C (2026-09-01) — REVIEWED, NO THRESHOLD CHANGE NEEDED.  This scenario's
# braking windows now genuinely harvest (the regen floor is gone), but every
# I_charge check here is scoped to `_MPPT_CRUISE_W`, i.e. the FC-PATH cruise
# plateaus, and the FC path is fed from the bus and is NOT subject to the new
# harvest cap.  What DOES change is the braking windows' I_charge, which nothing
# here scores.  Baseline era still applies: this run's regen segments are not
# comparable with campaigns <= 20260831_080905.
FAULT_EXPECTATIONS["mppt-tracking"] = {
    "source": ("AG105_Silvertel.pdf p.10 (MPPT is an INPUT-VOLTAGE THRESHOLD, "
               "11-33 V settable, 18 V default with MPPTS open) + Table 7 "
               "(reg 0x02: 0-250 = register mode, >=251 = external resistor — "
               "which is why a firmware write overrides any fitted MPPTS "
               "resistor and R1 is no longer a contingency) + .ino:1671-1690 "
               "(fw v24 clamp band [15, 27] = 12.320-13.376 V), :2911-2938 "
               "(observation-frame byte 15), :11185-11201 (the HIL mirror that "
               "computes it), :10586-10622 (chargingControl's cruise else-block) "
               "and :11284 (ag105IsReady). ⚠️ THE fw v23 HUNT IS NOW THE "
               "FAILURE SIGNATURE, not the expectation."),
    # Fault-free.  Budget at the 0.4 m/s charge plateaus, where the FC path is
    # SINGLE-SOURCE: I_AUX_A 0.15 + motor ~0.06 + chg_i_ceiling_a 1.0 = 1.21 A
    # against LIMIT_I_FC_MAX 1.4 A, a 14 % margin.
    # ⚠️ THE REALIZED MARGIN NARROWS UNDER fw v24, and this is the one place the
    # flipped objective costs something: the hunt used to hold the mean charge
    # current near HALF the ceiling, so the budgeted 1.21 A was never actually
    # drawn.  A charger that now harvests continuously draws the full ceiling —
    # which IS the number budgeted, so the derivation stands, but the run no
    # longer has the hunt's accidental headroom.  A first fw v24 campaign that
    # latches FAULT_OC_FC here is a BUDGET finding (lower chg_i_ceiling_a), not a
    # firmware defect.
    "allow_only": 0,
    "survive_to": {"t": EMS_MPPT_CRUISE_WINDOWS[-1][0], "states": {2}},   # 39.1
    # CALIBRATED 2026-09-01 from campaign hil_report_20260901_080905 (the first
    # fw v24 run, 15/15 PASS, every verdict recomputed).  The provisional_note is
    # DELETED because every bound below is now measured rather than derived;
    # each carries its own measurement in its comment.  Measured highlights:
    # 3 rises, 2902 tracking ticks, I_charge peak 0.8815 A, 12900/12900 threshold
    # rows, count band [15, 19], GENSTAT-001 refusal ticks 0, peak I_fc 1.1638 A.
    # ONE bound is still provisional and the note is scoped to it by name
    # (`provisional_note` is an ENTRY-level key — it qualifies every check in the
    # entry — so it says which one it is about rather than re-provisionalising
    # the nine that are now measured).
    # ── CHARGER ERA (WP-1C): THE RE-PROVISIONALISATION IS RETIRED, MEASURED ──
    # (2026-09-02, campaign 20260902_011926 fix-queue item 4 / review N2.)
    # The prediction was that ETA_CHG 0.88 would lift the observed count band
    # from campaign 080905's [15, 19] to [15, 21-22] and make
    # `mppt_threshold_peak_tripwire` (<= 21) the calibration point. THE
    # CALIBRATION EVENT DID NOT HAPPEN, and the reason is worth keeping:
    #   * Cruise V_chg DID rise, and by MORE than predicted — +0.487 V mean and
    #     +0.774 V minimum (2.2x the +0.22 V forecast).
    #   * The peak count nonetheless stayed at 19, because THE FLOOR BINDS: the
    #     manager writes (windowed-minimum V_chg - 3.0 V), and even at the lifted
    #     minimum that target is ~11.27 V — still below AG105_MPPT_N_FLOOR's
    #     12.320 V, so the clamp decides the count, not V_chg.
    # Consequence: a V_chg shift of this size moves NOTHING in this entry while
    # the floor binds. All five mppt_thresh_cnt pins are measured across two
    # charger eras and are no longer provisional on that account.
    "provisional_note": ("mppt_threshold_moved's range bound (1) is measured "
                         "on four hifi campaigns (range 2 on the first "
                         "three, 3 on campaign E); the "
                         "ratchet span "
                         "depends on how far V_chg sags under charge and the "
                         "simple engine's sag is unmeasured. Every other bound "
                         "in this entry is measured, now across BOTH charger "
                         "eras (campaigns 080905 and 20260902_011926): the "
                         "eta-era cruise V_chg rose +0.487 V mean / +0.774 V "
                         "min and the count band did not move, because the "
                         "AG105_MPPT_N_FLOOR clamp binds (target ~11.27 V vs "
                         "the 12.320 V floor) — peak 19 in both eras"),
    "signals_require": [
        # 1. MPPT_DISABLE ASSERTED (pin LOW) throughout a braking window.  Two
        #    firmware paths hold it low there and they agree: charge_goal is 0 at
        #    the window edges (.ino:10516-10518) and the regen branch drives it low
        #    inside (.ino:10550-10551).  max_ticks 0 is therefore exact, not lenient.
        #    UNCHANGED at fw v24 — the regen path never presents the threshold,
        #    so nothing this round did touches it.
        {"name": "mppt_asserted", "aux_bit": AUX_MPPT_DISABLE, "max_ticks": 0,
         "t_window": _MPPT_BRAKE_W,
         "label": "MPPT_DISABLE held LOW (inhibited) across the first braking "
                  "window — the regen path never presents the threshold"},
        # 2. ... and RELEASED across the cruise-charge windows.  The floor proves
        #    the firmware reached ag105IsReady() and let the module track; see
        #    _MPPT_TOGGLE_MIN_TICKS for why it stays at 300 rather than rising to
        #    match the now-larger expectation.
        {"name": "mppt_released", "aux_bit": AUX_MPPT_DISABLE,
         "min_ticks": _MPPT_TOGGLE_MIN_TICKS, "t_window": _MPPT_ALL_CRUISE_W,
         "label": "MPPT_DISABLE was RELEASED (pin HIGH) during cruise charging — "
                  "the firmware reached ag105IsReady()"},
        # 3. THE HUNT IS GONE — the replacement for `mppt_not_stuck_high`, whose
        #    MEANING inverted rather than its threshold.  A PHASE-FREE edge
        #    census: one release per charge window and no more.  See
        #    _MPPT_RISE_BAND for the count.
        {"name": "mppt_no_hunt", "aux_bit": AUX_MPPT_DISABLE,
         "edge_count_between": _MPPT_RISE_BAND, "edge": "rise",
         "t_window": _MPPT_ALL_CRUISE_W,
         "label": "MPPT_DISABLE rose once per cruise-charge window and did NOT "
                  "hunt — the fw v23 release/re-assert cycle (~69 rises) is the "
                  "failure signature this bounds"},
        # 4. Charging occurred on the FC path.
        #    ⚠️ FLOOR UNCHANGED AT 0.25 A, AND DELIBERATELY NOT RAISED.  Under
        #    fw v23 it was half the HUNT equilibrium (~0.5 A); under fw v24 the
        #    charger should hold near the full 1.0 A ceiling, so 0.25 is now a
        #    quarter of the expectation and correspondingly slack.  Raising it
        #    would re-encode a modelled equilibrium in a check whose objective is
        #    "the FC path delivered charge at all"; the harvest MAGNITUDE is the
        #    campaign's measurement to report, and the first fw v24 peak is what
        #    a tighter floor should be derived from.
        # 4. Charging occurred on the FC path.
        #    CALIBRATED 0.25 -> 0.70 A (campaign 080905: measured peak 0.8815 A).
        #    0.70 is chosen ABOVE the fw v23 hunt equilibrium's own peak
        #    (0.4848 A), so the check is now also a hunt-regression detector: a
        #    board that reverts to release/re-assert cannot reach it. 0.8815 is
        #    26 % above the bound, which is the slack a load or engine change
        #    gets before this needs re-deriving.
        {"name": "charging_occurred", "column": "I_charge", "min_value": 0.70,
         "t_window": _MPPT_CRUISE_W,
         "label": "the FC path delivered charge current (>= 0.70 A, measured "
                  "peak 0.8815 A; 0.70 is above the fw v23 hunt's 0.4848 A "
                  "peak, so a hunt regression also fails here)"},
        # 4b. F4 (2026-09-01): the OC BUDGET, asserted rather than left to the
        #     fault path.  At the single-source FC charge plateaus the budget is
        #     I_AUX_A 0.15 + motor ~0.06 + chg_i_ceiling_a 1.0 = 1.21 A against
        #     LIMIT_I_FC_MAX 1.4 A, and campaign 080905 measured a 1.1638 A peak
        #     — 16.9 % margin, the TIGHTEST margin in this scenario and, until
        #     now, unasserted until a latch. 1.30 sits between the measurement
        #     (+11.7 %) and the limit (−7.1 %), so a budget drift is caught as a
        #     named check rather than as an OC_FC teardown.
        #     ⚠️ CHARGER ERA (WP-1C, 2026-09-02) — CEILING HELD AT 1.30. This
        #     scenario runs the LARGEST charge ceiling in the suite
        #     (chg_i_ceiling_a 1.0 A), so it sheds the most: the charger's bus
        #     draw falls to ~0.56 of its pack current, i.e. ~0.44 A off the FC
        #     channel, and the peak is PREDICTED at ~0.72 A against the
        #     measured 1.1638 A. The 16.9 % margin quoted above is a 1:1-era
        #     figure. Not lowered onto the prediction — see
        #     `sdpx_fc_peak_bounded`.
        {"name": "mppt_fc_headroom", "column": "I_fc", "max_value": 1.30,
         "t_window": _MPPT_ALL_CRUISE_W,
         "label": "I_fc stayed under 1.30 A across the cruise-charge span "
                  "(measured peak 1.1638 A; LIMIT_I_FC_MAX is 1.4 A) — the "
                  "single-source FC budget, asserted before it can latch"},
        # 5. THE REFUSAL IS ABSENT.  Inversion of the old `low_power_seen`, which
        #    REQUIRED >= 50 ticks of GENSTAT 001 as proof the gate bound.  With
        #    the threshold clamped under the rail the module must never report
        #    Low Power; 50 ticks (50 ms) is allowed for a transient at a release
        #    edge, where the pin and the model's inhibit latch can disagree for a
        #    tick or two.  Vacuity companion: `tracking_engaged` below carries a
        #    positive bound on the same column.
        {"name": "refusal_absent", "column": "ag105_status",
         "value_mask": AG105_GENSTAT_MASK, "value_equals": AG105_ST_LOW_POWER,
         # CALIBRATED 50 -> 20 (campaign 080905 measured ZERO refusal ticks;
         # fw v23 measured 1481).  20 ms still covers a release-edge transient
         # where the pin and the model's inhibit latch disagree for a tick or
         # two, without leaving 50 ms of unearned room.
         "max_ticks": 20, "t_window": _MPPT_ALL_CRUISE_W,
         "label": "the Ag105 did NOT report GENSTAT 001 (Low Power) — the "
                  "input-voltage threshold gate never bound, because fw v24 "
                  "lowered it under the bus"},
        # 6. ... and the module TRACKED, which is the positive form.
        #    ⚠️ THIS PATTERN WAS UNREACHABLE UNDER fw v23, and the old entry said
        #    so explicitly: MPPT_EN|PWR_TRACK (0x18) is set only on the CHARGING
        #    branch with the pin HIGH, and under a binding threshold the pin
        #    going HIGH is exactly what moved the model off that branch within
        #    one tick.  fw v24 makes it the STEADY STATE, which is why the old
        #    entry asserted the COMPLEMENT (MPPT_EN with PWR_TRACK clear) and
        #    this one asserts the pair.  Floor 1500 is ~55 % of the realistic
        #    ~2700-tick expectation, not half of 3000: each window yields
        #    ~0.9 s of released, settled charging (1.0 s of released time less
        #    two 20 ms charger-poll cadence propagation lags at the window
        #    edges), so 3 windows x 0.9 s = 2.7 s.  The floor also tolerates
        #    exactly ONE full 1 s MPPT_RELEASE_HOLDOFF_MS arming inside the
        #    span, not two.  The 1500 VALUE is unchanged; only this derivation
        #    was wrong.
        {"name": "tracking_engaged", "column": "ag105_status",
         "value_mask": AG105_TRACK_MASK,
         "value_equals": AG105_FLAG_MPPT_EN | AG105_FLAG_PWR_TRACK,
         # CALIBRATED 1500 -> 2400 (campaign 080905 measured 2902 ticks).
         # ⚠️ F3, and the reason this floor is now a HOLDOFF DETECTOR rather
         # than a second independent witness: the measured 2902 equals
         # `mppt_released`'s tick count EXACTLY, because the plant model sets
         # both status flags synchronously with the pin. The two checks are
         # therefore NOT independent, and the derivation comment above (which
         # reasoned from charger-poll cadence lags) is FALSIFIED for the
         # simulated charger — it would still hold against a real Ag105.
         # What 2400 buys: it is 82.7 % of the measurement, so it still
         # tolerates ONE full 1 s MPPT_RELEASE_HOLDOFF_MS arming inside the
         # span and fails on two, which is the property worth keeping.
         "min_ticks": 2400, "t_window": _MPPT_ALL_CRUISE_W,
         "label": "MPPT_EN and PWR_TRACK both set — tracking released AND the "
                  "module actually tracking (measured 2902 ticks; the plant "
                  "sets these flags with the pin, so this bounds the release "
                  "HOLD, it is not an independent witness of it)"},
        # 7. THE THRESHOLD MANAGER RAN, read straight off the wire.  This is the
        #    round's load-bearing new evidence and the only check that separates
        #    "the hunt is absent because fw v24 fixed it" from "the hunt is
        #    absent because the charge windows never opened".
        #    Bit 7 CLEAR is exactly "a written I2C threshold": the clamp band is
        #    [15, 27] and the not-written sentinel is 0xFF, so masking 0x80
        #    separates them without pinning a value the campaign has not measured
        #    yet (the count follows V_chg, which differs between the simple and
        #    hi-fi engines — and this scenario runs "any").
        {"name": "mppt_threshold_written", "column": "mppt_thresh_cnt",
         "value_mask": 0x80, "value_equals": 0x00,
         "min_ticks": _MPPT_THRESH_MIN_TICKS, "t_window": _MPPT_THRESH_W,
         # RELABELLED 2026-09-02 (review PLANT-R1-F1). The old label said "the
         # fw v24 threshold manager ran", which is FALSE under HIL_SIM: the
         # .ino short-circuits the write path and mirrors a count computed from
         # V_chg onto the frame (.ino:11185-11201), so the manager is never
         # called at all. What the column witnesses is the MIRROR carrying a
         # written-mode count instead of the resistor sentinel — a frame-format
         # and fw-version fact, not evidence about the write policy. The write
         # policy, the deadband, the session ratchet and the EPROM budget remain
         # BENCH-ONLY unvalidated.
         "label": "the mirror carried a WRITTEN-MODE reg-0x02 count (bit 7 "
                  "clear, i.e. not the 0x%02X external-resistor sentinel) — the "
                  "fw v24 frame carries byte 15. A fw v21-v23 flash leaves this "
                  "column blank and FAILS here. NOTE: under HIL_SIM the count "
                  "is a mirror of V_chg, NOT a witness that the threshold "
                  "manager executed." % AG105_MPPT_N_RESISTOR},
        # 7b. F1 (2026-09-01) — THE MANAGER ACTUALLY RAN IN *THIS* RUN.
        #     Check 7 above is a LEVEL assertion, and campaign 080905 showed
        #     what that costs: the count carried in at 15 from the PREDECESSOR
        #     run (hilWarmReset preserves ag105MpptRegCnt, and the Ag105's EPROM
        #     preserves the register — the board was never power-cycled), so a
        #     run in which the manager never executed would have passed check 7
        #     on inherited state. A RANGE cannot be inherited: a carried-in
        #     constant has range 0.
        #     BOUND: measured range 4 (the count ratchets 15 <-> 19, a 5-step
        #     ratchet per power session, 31 transitions). 2 is half of that —
        #     enough that a single quantization step still passes if V_chg sags
        #     less in a future engine, and far enough above 0 that a frozen
        #     column fails.
        #     PROVISIONAL: 4 is ONE campaign's measurement of a quantity that
        #     depends on how far V_chg sags under charge, which differs between
        #     the simple and hi-fi engines — and this scenario runs "any".
        #     ⚠️ WINDOW RE-DERIVED 2026-09-03 onto `_MPPT_THRESH_CRUISE_W`,
        #     the same mirror-live cruise window the peak tripwire now uses.
        #     On `_MPPT_THRESH_W` (28.1-41.0) this check read a range of 12 in
        #     BOTH 2026-09-02 campaigns — and read it for the WRONG REASON: the
        #     span opened on the frozen braking value 27 carried out of the
        #     preceding braking window, so 12 was the distance from that
        #     artifact down to the harvest floor, not motion of the live
        #     mirror. Re-pointing the window makes the check assert what its
        #     label claims.
        #     ⚠️ BOUND LOWERED 2 -> 1 ON MEASUREMENT (2026-09-03, review
        #     finding M2).  The "measured 4" above was read on the OLD window;
        #     on `_MPPT_THRESH_CRUISE_W` the range is EXACTLY 2 in all three
        #     campaigns that carry the column (011926, 041414, 220604 — bins
        #     15/16/17 only, the 18/19 bins falling in 28.949-29.100 s inside
        #     the 0.2 s settle pad), so a bound of 2 passed with ZERO margin and
        #     one fewer ratchet step would have failed a correct board.  The
        #     check's CLAIM is "the column is LIVE", and one count of motion
        #     establishes that; the harvest operating point is asserted by the
        #     min/max pins below, not here.
        {"name": "mppt_threshold_moved", "column": "mppt_thresh_cnt",
         "column_range_at_least": 1, "t_window": _MPPT_THRESH_CRUISE_W,
         # RELABELLED 2026-09-02 (review PLANT-R1-F1), same reason as the pin
         # above: a moving count proves the column is LIVE in this run, not that
         # the threshold manager ran — under HIL_SIM it never does.
         "label": "the mirrored reg-0x02 count MOVED inside this run "
                  "(range >= 1 count; measured 2 on this window in campaigns "
                  "011926, 041414 and 220604, and 3 in campaign E "
                  "20260903_031220 on the post-A4 window: min 15, max 18, "
                  "histogram 15:7599 16:147 17:147 18:7, peak 18) — the "
                  "column tracked THIS "
                  "run's V_chg rather than carrying a predecessor's value. "
                  "Under HIL_SIM this is the MIRROR moving, not the manager"},
        # 8-9. ... and the count it reported sits inside the firmware's own clamp
        #    band.  TWO specs, not one: min_value and max_value on a single spec
        #    silently drop one bound (the import guard refuses that pairing), and
        #    the two prove different things.  The CEILING is the sharper of the
        #    two — it is what excludes the 0xFF sentinel and any unclamped write,
        #    and it is the bound the .ino's own static_assert pins against
        #    V_BUS_CHARGED_THRESH.  BOTH fail on an UNMEASURED column ("peak
        #    unmeasured"), so neither can pass a blank run vacuously.
        {"name": "mppt_threshold_ceiling", "column": "mppt_thresh_cnt",
         "max_value": AG105_MPPT_N_CEIL, "t_window": _MPPT_THRESH_W,
         "label": "reg-0x02 count never exceeded AG105_MPPT_N_CEIL %d (%.3f V) — "
                  "the clamp the .ino static_asserts below V_BUS_CHARGED_THRESH"
                  % (AG105_MPPT_N_CEIL, ag105_mppt_volts(AG105_MPPT_N_CEIL))},
        # F2 (2026-09-01): `min_value` was the WRONG KIND here.  It judges the
        # PEAK, so "the count reached the floor at least once" — vacuously true
        # for any run whose maximum clears 15, INCLUDING one that spent the
        # whole window below the clamp.  The objective is an INVARIANT ("the
        # manager never wrote under the bus-min guard"), so it wants the
        # in-window MINIMUM.  `floor_min_value` fails on a single excursion.
        # Campaign 080905 measured a band of [15, 19] with the floor binding
        # ~85 % of harvest time, so this is the bound the run actually rides.
        {"name": "mppt_threshold_floor", "column": "mppt_thresh_cnt",
         "floor_min_value": AG105_MPPT_N_FLOOR, "t_window": _MPPT_THRESH_W,
         "label": "reg-0x02 count NEVER fell below AG105_MPPT_N_FLOOR %d "
                  "(%.3f V) — the manager clamped rather than writing a "
                  "threshold under the bus-min guard (measured minimum 15, and "
                  "the floor binds ~85%% of harvest time)"
                  % (AG105_MPPT_N_FLOOR, ag105_mppt_volts(AG105_MPPT_N_FLOOR))},
        # 10. PEAK TRIPWIRE, separate from the invariant ceiling above.
        #     AG105_MPPT_N_CEIL (27) is the FIRMWARE'S OWN CLAMP and must stay
        #     as the invariant — it is what the .ino static_asserts against
        #     V_BUS_CHARGED_THRESH, and relaxing it would be relaxing a safety
        #     bound.  This second, TIGHTER bound is a regression tripwire on the
        #     OPERATING POINT: campaign 080905 measured a peak of 19, so 21 is
        #     +2 counts (0.176 V) of slack.  A run that suddenly ratchets toward
        #     the clamp is a V_chg change worth investigating, and without this
        #     it would sit silently anywhere in [15, 27].
        #     ⚠️ RAISE THIS ONLY WITH A MEASUREMENT.  It is NOT the safety
        #     bound; the safety bound is `mppt_threshold_ceiling` and that one
        #     never moves.
        #     PART B3 (2026-09-01): the WINDOW is now cruise-only. The band
        #     (<= 21) is UNCHANGED. See the _MPPT_THRESH_CRUISE_W banner for
        #     why the braking window had to come out, and for the pin that
        #     replaces it.
        {"name": "mppt_threshold_peak_tripwire", "column": "mppt_thresh_cnt",
         "max_value": 21, "t_window": _MPPT_THRESH_CRUISE_W,
         "label": "reg-0x02 count stayed at or under 21 (%.3f V) through the "
                  "CRUISE window %.1f-%.1f s — the OPERATING-POINT tripwire "
                  "(measured peak 19), distinct from the firmware clamp at %d "
                  "which is the invariant"
                  % (ag105_mppt_volts(21), _MPPT_THRESH_CRUISE_W[0],
                     _MPPT_THRESH_CRUISE_W[1], AG105_MPPT_N_CEIL)},
        # 11. THE BRAKING WINDOW, pinned as a MIRROR ARTIFACT (PART B3).
        #     Both bounds are AG105_MPPT_N_CEIL, i.e. the count is asserted to
        #     sit at exactly 27 for the whole window. They are TWO SPECS, not
        #     one: `_judge_signal_leaf()` returns on the first bound it matches
        #     and tests `floor_min_value` first, so a spec carrying both would
        #     silently drop the ceiling (the import guard refuses it).
        #     ⚠️ THIS IS NOT A BOARD BEHAVIOUR. It records that the HIL mirror
        #     tracks the regen-lifted V_chg into the threshold, which the real
        #     manager cannot do (.ino:11090-11095 excludes regen from the V_chg
        #     window sampling). If the mirror is ever taught that exclusion this
        #     check FAILS, which is the intent: the artifact should not be able
        #     to disappear silently.
        {"name": "mppt_threshold_braking_mirror_artifact_ceiling",
         "column": "mppt_thresh_cnt",
         "max_value": AG105_MPPT_N_CEIL,
         "t_window": _MPPT_THRESH_BRAKE_W,
         "label": "reg-0x02 count never exceeded AG105_MPPT_N_CEIL %d through "
                  "the braking window %.3f-%.3f s (the mirror-artifact pin's "
                  "ceiling arm)"
                  % (AG105_MPPT_N_CEIL, _MPPT_THRESH_BRAKE_W[0],
                     _MPPT_THRESH_BRAKE_W[1])},
        # RE-SPECIFIED 2026-09-02 (review PLANT-R1-F1, campaign 20260902_011926
        # fix-queue item 4): a PEAK-REACHING bound, not a floor.
        #     `floor_min_value: 27` asserted that the count sat at 27 for EVERY
        # tick of the window, and the window's right edge OVERHANGS the plateau
        # by ~62 ms in BOTH campaigns (measured plateau 37.7290-38.4631 s here,
        # 37.7324-38.4673 s in 080905; the ratchet tail then descends). The pin
        # was therefore unsatisfiable on data that shows the artifact perfectly
        # — it read 19 and 23 respectively, and the run FAILED on a correct
        # board. The claim worth pinning is that the mirror REACHES the clamp
        # inside the braking window; the `_ceiling` arm above still bounds it
        # from the other side, so the pair remains "reached 27 and never
        # exceeded it" without asserting a phase the window edges cannot know.
        # STRENGTHENED 2026-09-02 (review L1): `min_ticks` 600 alongside the
        #     peak. The numeric tick counter added this round counts samples on
        #     the right side of the spec's own `min_value`, so the pair now
        #     reads "reached 27 and HELD it for >= 600 ticks" — strictly
        #     stronger than the bare peak, which one spurious sample would
        #     satisfy, and still free of the phase claim the window edges cannot
        #     support. 600 ticks is 0.6 s against measured plateaus of 735
        #     ticks (20260902_011926), 730 (080905) and 701 (20260902_041414):
        #     14 % of margin under the shortest of the three. Under the TRIMMED
        #     window (item 3, same round) the two 2026-09-02 campaigns score
        #     690 and 683 IN-WINDOW ticks when scanned offline, so the dwell
        #     keeps 12 % of margin there too.
        {"name": "mppt_threshold_braking_mirror_artifact",
         "column": "mppt_thresh_cnt",
         "min_value": AG105_MPPT_N_CEIL,
         "min_ticks": 600,
         "t_window": _MPPT_THRESH_BRAKE_W,
         "label": "reg-0x02 count REACHED AG105_MPPT_N_CEIL %d inside the "
                  "braking window %.3f-%.3f s and HELD it for >= 600 ticks "
                  "(measured plateau 735 / 730 / 701 ticks over three "
                  "campaigns) "
                  "— a HIL MIRROR ARTIFACT "
                  "(regen lifts V_chg onto the 18.1 V chopper clamp and the "
                  "mirror clamps; the real manager excludes regen from its "
                  "V_chg sampling, .ino:11090-11095), asserted so it cannot "
                  "change unnoticed. A dwell COUNT, not a per-tick floor: the "
                  "plateau measured 37.729-38.463 s, so the window's right "
                  "edge overhangs it by ~62 ms and `floor_min_value` is "
                  "unsatisfiable on correct data"
                  % (AG105_MPPT_N_CEIL, _MPPT_THRESH_BRAKE_W[0],
                     _MPPT_THRESH_BRAKE_W[1])},
    ],
}


# ═════════════════════════════════════════════════════════════════════════════
# charge-to-full  —  the Ag105 Fully-Charged / CV path, and the firmware's
#                    deliberate NO-ACTION response to it
#
# FIRST RUN IN THIS SUITE TO REACH GENSTAT 011.  The branch has existed since the
# SoC model landed (2026-08-27) and has never been entered: the largest SoC RISE
# on record is ~0.0009 against the ~0.29 that soc0 0.70 would need.  build_plan()
# overrides --soc0 to 0.990 (the soc-depletion mechanism), leaving 0.005 to the
# 0.995 threshold = 90 A·s = 90 s at the 1.0 A ceiling.  Charging is established
# ~t = 9 (charge_goal at t = 8 + AG105_SETTLE_S), so FULL is expected ~t = 100.
# MEASURED against the model (offline probe, 2026-08-31): FULL at t = 98.90 s,
# CV set, I_charge under 0.05 A by t = 100.09 s.  Every window below has >= 24 s
# of margin on those numbers.
#
# ⚠️ THE PREDICTED TIME IS MODEL ARITHMETIC.  Its inputs are the coulomb count
# (exact) and the charge current (a first-order ramp to a scenario-set ceiling —
# also exact in this model), so the estimate is tight; but the SoC->OCV curve is
# still `TODO(calibrate)`, and if a future calibration changes the 0.995 branch
# condition this whole entry's windows move with it.
#
# WHAT THE FIRMWARE DOES ON FULL: NOTHING, deliberately, and that no-action
# baseline is asserted POSITIVELY (fc_charge_still_open) rather than left as an
# absence.  Verified from source: ag105IsReady() ACCEPTS FULL (.ino:10249-10255),
# so MPPT stays released; chargingControl() never reads GENSTAT at all
# (.ino:10004-10053), so FC_CHARGE_ENABLE stays open on `charge_goal` alone; FULL
# is not an error GENSTAT in detectFaults() (.ino:4952-4960); LIMIT_V_BATT_MAX
# 10.0 V is not approached by an 8.4 V pack.  If a future round makes the
# firmware close the path on FULL, THIS CHECK IS THE ONE THAT WILL FAIL — which
# is the intent: the baseline should have to be changed on purpose.
#
# OUT OF SCOPE: CHARGER_STAT (pin 6).  It is on NEITHER HIL frame (the aux byte
# carries only MPPT_DISABLE and CBAL_DISABLE, .ino:2823) and chargingControl()
# does not read it, so its Fully-Charged blink signature (50 % duty / 2 s,
# Ag105_Table5_Status_Output.json) is unobservable here.  Carrying it would be a
# frame extension — future protocol work.
FAULT_EXPECTATIONS["charge-to-full"] = {
    "source": ("hil_plant_sim.py SCENARIOS['charge-to-full'] + Plant.step()'s "
               "soc >= 0.995 Fully-Charged branch + "
               "references/Datasheets/Ag105_Table6_I2C_Status_Byte.json "
               "(GENSTAT 011 = Fully Charged, bit 5 = CV). Firmware no-action "
               "baseline verified at .ino:10004-10053 (chargingControl never "
               "reads GENSTAT), :10249-10255 (ag105IsReady accepts FULL) and "
               ":4952-4960 (FULL is not an error GENSTAT)."),
    # Fault-free.  Budget: the FC charge path is single-source, and the run is at
    # STANDSTILL (v_setpoint 0 < V_SP_ZERO_THRESH 0.07, so 0 A to the motor), so
    # the channel carries I_AUX_A 0.15 + chg_i_ceiling_a 1.0 = 1.15 A against
    # LIMIT_I_FC_MAX 1.4 A — an 18 % margin held for ~120 s.
    "allow_only": 0,
    # Deep into the CC phase and well before the predicted FULL at ~100 s, so
    # this proves the run got to its own stimulus rather than merely started.
    "survive_to": {"t": 60.0, "states": {2}},
    "signals_require": [
        # 1. CC charging was actually established.  0.8 is 80 % of the 1.0 A
        #    ceiling, which a first-order ramp at AG105_TAU_S = 0.4 s reaches
        #    ~0.6 s after settle — i.e. by t ~ 10, deep inside the window.
        {"name": "cc_established", "column": "I_charge", "min_value": 0.8,
         "t_window": (10.0, 60.0),
         "label": "constant-current charging established on the FC path"},
        # 2. FULLY CHARGED reached and HELD.  500 ticks = 0.5 s at the CSV's
        #    1 kHz row rate — a floor, not the expectation: once soc crosses
        #    0.995 the branch is absorbing (the taper delivers no more charge),
        #    so the real count is ~30000.  A run that merely GRAZED the state
        #    would be a model finding, and 500 is low enough to catch that
        #    without admitting a single-tick flicker.
        #    The window opens at 60 — before the predicted ~100 — so a FULL that
        #    arrives early still counts; the arithmetic is model-derived and
        #    should not be pinned harder than it is known.
        {"name": "reached_full", "column": "ag105_status",
         "value_mask": AG105_GENSTAT_MASK, "value_equals": AG105_ST_FULL,
         "min_ticks": 500, "t_window": (60.0, None),
         "label": "the Ag105 reached GENSTAT 011 (Fully Charged) — never observed "
                  "in any prior campaign"},
        # 3. ... with the CV flag, which is the OTHER half of the Table 6 report
        #    and is set by the same branch.  Asserted separately so a model change
        #    that set one without the other is visible.
        {"name": "cv_flag", "column": "ag105_status",
         "value_mask": AG105_FLAG_CV, "value_equals": AG105_FLAG_CV,
         "min_ticks": 500, "t_window": (60.0, None),
         "label": "the constant-voltage flag (Table 6 bit 5) accompanied it"},
        # 4. The current TAPERED.  This is the new `max_value` CEILING kind: a
        #    floor cannot express "and then it stopped".  0.05 A is 5 % of the
        #    ceiling; the taper is first-order at AG105_TAU_S = 0.4 s, so from
        #    1.0 A it is under 0.05 A within ~1.2 s of the FULL transition —
        #    t = 125 gives ~25 s of margin on the ~100 s predicted transition.
        {"name": "current_tapered", "column": "I_charge", "max_value": 0.05,
         "t_window": (125.0, None),
         "label": "charge current tapered to <= 0.05 A after Fully Charged"},
        # 5. THE NO-ACTION BASELINE, made visible.  1000 ticks = 1 s of the ~20 s
        #    window; the expectation is that it is open for ALL of it.  A low
        #    floor deliberately: this check exists to catch a POLICY CHANGE (the
        #    firmware learning to close the path on FULL), which would show as
        #    zero, not as a reduced count.
        {"name": "fc_charge_still_open", "switch_bit": SW_FC_CHARGE,
         "min_ticks": 1000, "t_window": (110.0, None),
         "label": "FC_CHARGE_ENABLE STILL OPEN after Fully Charged — the "
                  "firmware's deliberate no-action baseline (chargingControl "
                  "never reads GENSTAT)"},
    ],
}


# ═════════════════════════════════════════════════════════════════════════════
# pi-silence  —  the firmware's Pi watchdog, isolated from the HIL link
#
# A VERIFIED COVERAGE GAP.  checkPiWatchdog() (.ino:4976-4985) has never been
# exercisable by this suite: its clock is stamped ONLY by the 22-byte command
# branch (:5043-5044), and every stimulus that stopped commands also stopped
# injection (apply_scenario's `tx_enabled` gates both, :4172/:4192), which trips
# the HIL staleness path instead.  `pi_mute_after_s` mutes the COMMANDER alone.
#
# ⚠️ THE 0x8010 AMBIGUITY IS THE WHOLE DIFFICULTY.  FAULT_PI_TIMEOUT and
# FAULT_HIL_LINK are the SAME BIT (the deliberate alias, .ino:1240-1248; the
# `#define FAULT_HIL_LINK FAULT_PI_TIMEOUT` itself is :1265), so the fault union
# alone cannot say which fired.  The `child_tx_healthy` check is the
# discriminator, via attribute_shared_0x8010().
# CLOSED ON THE WIRE (fw v25, 2026-09-01): observation-frame byte 16 carries the
# LATCHED FIRST CAUSE (.ino:2968-2978), so on a fw v25 board this scenario's
# attribution is a DIRECT READ — ERR_PI_TIMEOUT 0x05 vs ERR_HIL_STALE 0x10.  On a
# fw v21-v24 board the old inference by elimination still applies (a continuous
# injection stream makes a HIL-link explanation implausible) and the check's
# detail line says which of the two decided.
#
# ⚠️ fw v23 RECOVERY INTERPLAY (verified, and why `warm_resets_expected` is
# ABSENT).  Injection never stops, so no HIL RUN BOUNDARY (1000 ms of link
# silence anchored at hilLastFrameMs) can form and the latch persists to the end
# of the run.  A mid-run warm reset here would prove the stimulus was
# contaminated — and would also destroy the test, because hilWarmReset() clears
# `pi_ever_connected` (:5610), disarming the watchdog under test.  Leaving the
# key absent means the suite's tripwire marks such a run INCONCLUSIVE, which is
# exactly the right verdict.
FAULT_EXPECTATIONS["pi-silence"] = {
    "source": (".ino:4976-4985 (checkPiWatchdog, PI_TIMEOUT_MS 500, armed in "
               "State 2/3 once pi_ever_connected) + :5043-5044 (last_rx_ms is "
               "stamped ONLY by the 22-byte command branch) + :5132 "
               "(hilLastFrameMs is a separate clock). Stimulus: "
               "hil_plant_sim.SCENARIOS['pi-silence'] pi_mute_after_s = 8.0."),
    "require": FAULT_PI_TIMEOUT,
    "allow_only": FAULT_PI_TIMEOUT | FAULT_ERROR,
    # The latch must come FROM the mute, not from anything earlier.  8.0 is the
    # mute instant itself; the fault is expected ~0.5 s later (PI_TIMEOUT_MS).
    "not_before_s": 8.0,
    # In State 2 half a second before the Pi goes quiet: the watchdog is only
    # armed in State 2/3, so a run that was not in Run has not tested it.
    "survive_to": {"t": 7.5, "states": {2}},
    # The honest attribution: the 0x0010 bit is shared with FAULT_HIL_LINK, and
    # only a continuous injection stream rules that alias out.
    "child_tx_healthy": True,
    "signals_require": [
        # THE MOTOR ACTUALLY STOPPED.  The fault's consequence, not just its
        # flag.  hold-5050 cruises at EMS_DEFAULT_CRUISE_MPS = 1.2 m/s, where the
        # model's hold current is ~3.5 A, so the fall to 0 A is unmistakable.
        # 2.0 A is a floor well under that and well over any cruise ripple.
        # The window straddles the latch (7.0 -> 13.0): `strictly_decreases_by`
        # compares the FIRST and LAST samples in the window, so it needs the
        # pre-fault hold on one side and the post-fault zero on the other.
        {"name": "motor_halted", "column": "current",
         "strictly_decreases_by": 2.0, "t_window": (7.0, 13.0),
         "label": "the commanded motor current fell by >= 2.0 A across the "
                  "watchdog latch — the fault's consequence, not just its flag"},
    ],
}


# ═════════════════════════════════════════════════════════════════════════════
# share-staircase  —  the governor's rails, and the cut/restore LATENCY
#
# TWO PHASES AT TWO LOADS, because the two objectives are mutually exclusive at
# any single load (derivation at SCENARIOS["share-staircase"] and at
# STAIRCASE_LOAD_A/_B):
#   PHASE A, I_tot ~ 1.20 A — the governor's rails are
#       SHARE_MINORITY_I_MIN_A/I_tot = [0.25, 0.75], and the staircase steps
#       0.80 -> 0.20 straddles both.  The clip band campaign TP0170-0180 measured
#       incidentally is now a DESIGNED observable, swept in both directions.
#   PHASE B, I_tot ~ 0.55 A — the setpoint excursions 0.95 / 0.05 are outside
#       [DROOP_R_MIN 0.15, DROOP_R_MAX 0.85], so updateShareSetpointCutoff()
#       (.ino:9231-9257) cuts BT_BUS then FC_BUS.  The latch needs the DOOMED
#       channel under SHARE_CUT_MAX_HANDOFF_A = 0.5 A (.ino:9234, :9250); at
#       Phase A's 1.20 A a 50/50 split is 0.60 A and the cut would DEFER.
#
# ⚠️ CORRECTED PREMISE ON THE LATENCY (campaign rounds 3/4, CLAUDE.md
# 2026-08-31b).  The [0, 20) ms spread five campaigns measured is COMMAND-ARRIVAL
# PHASE — the emulated Pi's PI_CMD_HZ = 50 cadence — NOT a firmware tick.
# powerBalance() and its cutoff run at POWER_BAL_PERIOD_US = 1000 us
# (SHARE_CTRL_TS_US is also 1000 us), contributing ~1 ms.  Changing PI_CMD_HZ
# would move this distribution; changing a firmware tick would barely touch it.
# THE BOUND BELOW IS A REGRESSION TRIPWIRE, and the MEASURED VALUE IS THE
# DELIVERABLE — it is printed into the check detail on pass and on fail.  Do not
# raise it to make a run go green.
_SS_LATENCY_MAX_MS = 40.0     # 20 (command phase) + 1 (share tick)
                              # + ~2 (observation round trip) + margin
# L2 (review 2026-08-31): 40 ms is ~1.7x the 23 ms those three terms sum to, and
# the margin is deliberately generous because NO distribution of this quantity
# has been measured on THIS stimulus yet. The first campaign's four datapoints
# are CALIBRATION DATA, not a pass/fail result: record them, and tighten this
# bound toward the observed spread once there are enough runs to see its shape.
# (The handoff-sag tracker is the precedent — five campaigns were needed there
# before the [0, 20) command-phase window was correctly identified.)
# Each excursion holds for 3 s.  The latency windows OPEN 1 s EARLY so the
# pre-edge level is established (the import-time assert enforces this), and close
# 2 s after the stimulus — five times the tripwire.
_SS_BT_CUT_T, _SS_BT_RESTORE_T = 33.0, 36.0
_SS_FC_CUT_T, _SS_FC_RESTORE_T = 39.0, 42.0
# ─────────────────────────────────────────────────────────────────────────────
# fw26-clamp-cruise — the fw v26 source current-ceiling clamp
#
# THE FIRST STIMULUS THAT EXERCISES THE FEATURE UNDER CONTROL.
#
# ⚠️ CORRECTED 2026-09-02: this said "the first stimulus that reaches the
# feature at all", which is false. `ems-y-b30-v3` reaches the ceiling too --
# reconstructed commanded I_fc 1.5180 A for 11 ticks at t = 27.020 s (campaign
# B: 1.5173 A / 9 ticks), by
# `tools/probes/probe_fw26_clamp_reachability.py`. It is an 11 ms transient at a
# region boundary and cannot bound a held current or a release, which is what
# this pair is for. Nothing ELSE on the registered set gets there: the
# next-highest commanded fuel-cell current is `ems-sdp`'s 1.1861 A.
#
# Derivation of the load and
# of the two phases is at SCENARIOS["fw26-clamp-cruise"]; the reachability argument
# is docs/fw26_current_ceiling_governor.md section 4.1.1 and the acceptance
# criteria are its section 8.3.
#
# ⚠️ EVERY BOUND BELOW IS A WALK, NOT A MEASUREMENT. The numbers come from an
# offline walk of this stimulus through tools/governor_model.py at the plant's
# measured asymmetry (dv0 0.013522 V) and at dv0 = 0; the two agree on every
# current to four decimals, because the clamp pins the fuel-cell current rather
# than the ratio and the asymmetry moves only the ratio that delivers it
# (0.6197 against 0.6250). The walk, at the shipped 2.00 A total:
#
#   phase A, share 0.75, t = 8..24
#       first engagement on the FIRST tick after the setpoint step (the
#       governor enters phase A converged at r = 0.4944 from the timeline's
#       own 0.50 pre-phase), clamp duty 1.0000 of the phase
#       I_fc  1.2500 A held, whole-phase peak 1.2500 A - NO overshoot
#       I_batt 0.7500 A, |I_tot - I_fc - I_batt| identically 0
#       applied ratio 0.6197, inside [DROOP_R_MIN, DROOP_R_MAX]
#       0 cut refusals, 0 switch edges, both bus switches high throughout
#   phase B, share 0.40, t = 26..34
#       clamp duty 0.0000, I_fc 0.8000 A
#
# THE FIRST CAMPAIGN THAT RUNS THIS SCENARIO RE-DERIVES ALL OF IT. A miss on the
# duty floor or on the I_fc window is a calibration event and is read against
# the ceiling's own TODO(calibrate) (design note section 8.7), not absorbed by
# widening a bound.
# The phase A command instant, and the window the two step pins judge. Those
# two judge the TRANSIENT, so they are written against the command instant
# itself rather than as an offset from the steady-state inset.
_CEILING_STEP_T = 8.0                    # SCENARIOS[...]["pi_timeline"]
_CEILING_STEP_WIN_S = 0.1
_CEILING_A0, _CEILING_A1 = 8.5, 24.0     # phase A, inset from the 8.0 command
_CEILING_B0, _CEILING_B1 = 27.0, 34.0    # phase B, inset from the 26.0 command
# ⚠️ THE CADENCE GATE AND THE TICK FLOORS ARE ONE NUMBER (M8, 2026-09-02).
# The entry's tick floors assume near-full 1 kHz coverage; its cadence gate
# originally admitted 3.9 % of it. A stream defect then failed a TOPOLOGY check
# instead of the cadence check. `_CEILING_CADENCE_COVER` is the coverage this
# entry requires, everything else is derived from it, and a lossy stream now
# fails `ceiling_cadence` by name.
#
# ── CAMPAIGN E (hil_report_20260903_031220): MEASURED, 20 of 20 ─────────────
# This leg PASSED and is now the calibration source for the whole feature. The
# walk above is reproduced on every axis it predicted:
#
#   engagement            +3.32 ms after the commanded step, and the latency is
#                         PI-CADENCE-LIMITED rather than clamp-limited - the
#                         clamp engages on the first tick that carries the new
#                         setpoint. Across both fw26 legs the figure ranges
#                         3.3 ms (here) to 17.7 ms (the sweep's region 5 -> 6
#                         boundary), which is the 48.7 Hz command phase.
#   reference slew        ~6 ticks to walk the droop ratio onto the bound
#   settling              35 ms to the ceiling band
#   overshoot             0.016 % - peak I_fc 1.2502 A against the 1.2500 A
#                         ceiling, at a SETTLED total of 2.0007 A
#   phase A duty          15500 of 15500 ticks
#   phase A currents      I_fc 1.2499-1.2502 A, I_batt 0.7505-0.7508 A,
#                         |I_tot - I_fc - I_batt| <= 0.0008 A
#   phase B               0 clamped ticks, I_fc 0.8003 A
#   BT ceiling            0 ticks
#
# ⚠️ THE 0.016 % OVERSHOOT IS A PROPERTY OF THE SETTLED TOTAL, NOT OF THE CLAMP.
# The same mechanism, stepped while the total was RISING, delivered 1.4890 A on
# `fw26-clamp-sweep` and latched OC_FC. See design note section 8.6; the two
# numbers together are the hazard statement.
_CEILING_CADENCE_COVER = 0.98
_CEILING_CADENCE_ROWS = int(1000.0 * (_CEILING_B1 - _CEILING_A0)
                            * _CEILING_CADENCE_COVER)          # 24990
_CEILING_BUS_HOLD_TICKS = int(0.98 * _CEILING_CADENCE_ROWS)    # 24490

FAULT_EXPECTATIONS["fw26-clamp-cruise"] = {
    "source": ("applyShareCurrentCeilings() (.ino:10273-10313) with "
               "SHARE_GOV_I_FC_CEIL_A 1.25 A, SHARE_GOV_I_BT_CEIL_A 2.70 A and "
               "SHARE_GOV_CEIL_HYST_A 0.05 A (.ino:2406/:2424/:2430), against "
               "LIMIT_I_FC_MAX 1.4 A (.ino:1425). Load derivation at "
               "hil_plant_sim.FW26_CLAMP_CRUISE_LOAD_A; bounds from the offline "
               "governor_model walk recorded above; design note "
               "docs/fw26_current_ceiling_governor.md sections 4.1.1 and 8.3."),
    "provisional_note": ("MEASURED (campaign E, 2026-09-03, 20 of 20). The "
                         "bounds were WALKED and the campaign reproduced every "
                         "one of them - see the calibration block above. The "
                         "two step pins are pinned on ONE reading each "
                         "(1.2502 A and 35 ms), so they are provisional on "
                         "that account and on nothing else. Read a miss "
                         "against the ceiling's own TODO(calibrate) rather "
                         "than by widening a bound."),
    # FAULT-FREE, and that is half the claim. The whole point of the clamp is
    # that the fuel cell is held at 1.25 A instead of climbing to the 1.4 A
    # latch; a run that latches OC_FC here has not merely failed a check, it has
    # falsified the mechanism.
    "allow_only": 0,
    # Past the release and into the negative control: a run that latched during
    # phase A never reached the half of the scenario that discriminates.
    "survive_to": {"t": 30.0, "states": {2, 3}},
    "signals_require": [
        # 0. THE CADENCE CENSUS, so nothing below can pass on a run whose
        #    observation stream stalled. Its own spec: `min_rows` returns before
        #    every value and tick bound.
        {"name": "ceiling_cadence", "min_rows": _CEILING_CADENCE_ROWS,
         "t_window": (_CEILING_A0, _CEILING_B1),
         "label": "the run streamed at full cadence across both phases "
                  "(>= %d rows in a %.1f s window = %.0f %% of the 1 kHz "
                  "nominal)" % (_CEILING_CADENCE_ROWS,
                                _CEILING_B1 - _CEILING_A0,
                                100.0 * _CEILING_CADENCE_COVER)},
        # 1. THE STIMULUS WAS DELIVERED. 0.74 rather than 0.75: the value
        #    round-trips through a float32 UDP field.
        {"name": "ceiling_share_commanded", "column": "cmd_share_sp",
         "min_value": 0.74, "t_window": (_CEILING_A0, _CEILING_A1),
         "label": "phase A commanded share 0.75 (unclamped FC demand 1.50 A at "
                  "the 2.00 A total, 0.25 A over the 1.25 A ceiling)"},
        # 2. THE CLAMP ENGAGED, and held. The phase A window is 15.5 s; the walk
        #    puts the duty at 1.0000, so 12000 ticks is a floor at 77 % of the
        #    window - loose enough for a slow engagement, and unreachable by a
        #    run in which the clamp merely chattered.
        {"name": "fc_ceiling_active_duty", "aux_bit": "fc_ceiling_active",
         "min_ticks": 12000, "t_window": (_CEILING_A0, _CEILING_A1),
         "label": "the FC current ceiling was BINDING for >= 12000 ticks of "
                  "phase A (walk: 1.0000 duty) - the only evidence the "
                  "mechanism acted, since a reference-side bound cannot be "
                  "told from a load that happened to stop there"},
        # 3. THE NEGATIVE CONTROL, same run and same load. At share 0.40 the
        #    demand is 0.80 A, 0.45 A under the ceiling and well past the 0.05 A
        #    release hysteresis, so the flag must be down for the WHOLE window.
        {"name": "fc_ceiling_released", "aux_bit": "fc_ceiling_active",
         "max_ticks": 0, "t_window": (_CEILING_B0, _CEILING_B1),
         "label": "the FC ceiling released on the setpoint step and stayed "
                  "released through the control phase (0 ticks)"},
        # 4. THE BATTERY CEILING IS NOT EXERCISED, and must not fire. It would
        #    need 2.70 A on one channel; the whole bus carries 2.00 A.
        {"name": "bt_ceiling_never", "aux_bit": "bt_ceiling_active",
         "max_ticks": 0, "t_window": (2.5, _CEILING_B1),
         "vacuity_note": ("the aux column cannot be blank across this window: "
                          "`fc_ceiling_active_duty` above asserts >= 12000 "
                          "ticks with an aux bit SET inside it, which is only "
                          "reachable if the same byte streamed and parsed. A "
                          "zero count here is therefore a read of the BT bit, "
                          "not an absent column."),
         "label": "the BT ceiling never bound (it would need 2.70 A on one "
                  "channel against a 2.00 A bus)"},
        # 5-6. I_fc INSIDE THE ACCEPTANCE BAND, two-sided. Two specs, because
        #    one spec cannot carry both bounds. The band is the ceiling plus and
        #    minus the hysteresis, [1.20, 1.30] A, exactly as the design note's
        #    section 8.3 states it; the walk sits at 1.2500 exactly, with no
        #    overshoot, so both edges have margin.
        # ⚠️ `floor_min_value`, NOT `min_value` (H2, 2026-09-02). `min_value`
        #    tests the in-window MAXIMUM, i.e. "it reached 1.20 A at least
        #    once", which any run that touches the ceiling for one tick
        #    satisfies. The claim here is an INVARIANT -- the current was HELD
        #    at the ceiling for the whole phase -- so it wants the in-window
        #    MINIMUM, which is what `floor_min_value` tests.
        {"name": "ceiling_fc_at_the_ceiling", "column": "I_fc",
         "floor_min_value": 1.20, "t_window": (_CEILING_A0, _CEILING_A1),
         "label": "FC current NEVER fell below the ceiling band through phase "
                  "A (>= 1.20 A = SHARE_GOV_I_FC_CEIL_A - "
                  "SHARE_GOV_CEIL_HYST_A, on every sample)"},
        {"name": "ceiling_fc_under_the_limit", "column": "I_fc",
         "max_value": 1.30, "t_window": (_CEILING_A0, _CEILING_A1),
         "label": "FC current never left the acceptance band (<= 1.30 A, "
                  "against LIMIT_I_FC_MAX 1.4 A - the clamp's whole purpose). "
                  "HEADROOM: the walk pins I_fc at 1.2500 A with no "
                  "overshoot, so this bound sits 4.0 % above the value it is "
                  "judging - it is a tripwire, not a budget, and a miss is a "
                  "calibration event"},
        # 7-8. THE BALANCE CLOSED ONTO THE BATTERY. The scenario is motor-free
        #    and its total is one constant, so |I_tot - I_fc - I_batt| <= 0.10 A
        #    is exactly a two-sided bound on I_batt around 2.00 - 1.25 = 0.75 A.
        #    This is the check that confirms the current the fuel cell did not
        #    supply actually WENT somewhere, rather than the load having fallen.
        # `floor_min_value` for the same reason as the check above: the claim
        # is that the battery carried the surplus THROUGHOUT, not once.
        {"name": "ceiling_batt_took_the_rest", "column": "I_batt",
         "floor_min_value": 0.65, "t_window": (_CEILING_A0, _CEILING_A1),
         "label": "the battery carried the amps the ceiling refused the fuel "
                  "cell on every sample (>= 0.65 A; walk 0.7500 A, balance "
                  "bound 0.10 A)"},
        {"name": "ceiling_batt_bounded", "column": "I_batt",
         "max_value": 0.85, "t_window": (_CEILING_A0, _CEILING_A1),
         "label": "and no more than that (<= 0.85 A) - the two bounds together "
                  "are |I_tot - I_fc - I_batt| <= 0.10 A at a 2.00 A total"},
        # 9. THE CONTROL PHASE'S OWN CURRENT. At share 0.40 the fuel cell must
        #    fall to 0.80 A; 0.95 is a ceiling under the 1.20 A phase-A floor by
        #    a wide margin, so a run that never released fails here as well as
        #    on check 3.
        {"name": "ceiling_control_fc", "column": "I_fc", "max_value": 0.95,
         "t_window": (_CEILING_B0, _CEILING_B1),
         "label": "FC current fell to the commanded 0.40 split in the control "
                  "phase (<= 0.95 A; walk 0.8000 A)"},
        # 10-11. THE CLAMP NEVER OPENED A BUS SWITCH. A reference outside the
        #    droop band IS the channel-cutoff signal, so the band constraint at
        #    the tail of applyShareCurrentCeilings() is structural rather than
        #    arithmetical - and this is what asserts it on the board. Both
        #    switches must be high for essentially the whole of both phases;
        #    25000 ticks is 98 % of the 25.5 s span.
        # ⚠️ DERIVED FROM THE CADENCE GATE (M8, 2026-09-02). These floors were
        #    a hand-typed 25000 ticks, 98 % of the window's 1 kHz nominal,
        #    while `ceiling_cadence` above admitted a run with 1000 rows in the
        #    same window - 3.9 % coverage. A run streaming at half cadence
        #    would have passed the cadence gate and then failed HERE, reporting
        #    "a bus switch opened" for a stream defect. The two are now one
        #    number: the cadence gate guarantees `_CEILING_CADENCE_ROWS` rows,
        #    and these floors ask for 98 % of THAT, so a miss is a topology
        #    finding and a stream stall is reported by the check that means it.
        {"name": "ceiling_fc_bus_held", "switch_bit": SW_FC_BUS,
         "min_ticks": _CEILING_BUS_HOLD_TICKS,
         "t_window": (_CEILING_A0, _CEILING_B1),
         "label": "FC_BUS_ENABLE stayed high across both phases (>= %d ticks = "
                  "98 %% of the rows `ceiling_cadence` guarantees) - a current "
                  "ceiling must never open a bus switch"
                  % _CEILING_BUS_HOLD_TICKS},
        {"name": "ceiling_bt_bus_held", "switch_bit": SW_BT_BUS,
         "min_ticks": _CEILING_BUS_HOLD_TICKS,
         "t_window": (_CEILING_A0, _CEILING_B1),
         "label": "BT_BUS_ENABLE stayed high across both phases (>= %d ticks) "
                  "- the split is genuinely two-source, which is what makes "
                  "the clamp reachable at all" % _CEILING_BUS_HOLD_TICKS},
        # 12. AND NO CUT WAS EVEN ATTEMPTED. Zero rising edges on either bus
        #    switch: a cut followed by a restore would satisfy the two tick
        #    floors above and is exactly the failure they cannot see.
        {"name": "ceiling_no_switch_ring", "switch_bit": SW_FC_BUS,
         "edge_count_between": (0, 0), "edge": "rise",
         "t_window": (_CEILING_A0, _CEILING_B1),
         "label": "no FC_BUS rising edge in either phase - no cut, and "
                  "therefore no sw_ring"},
        # ── 13-14. THE STEP ITSELF (campaign E fix round, 2026-09-03) ────────
        # Every check above is INSET past the step, so the transient the clamp
        # actually has to survive was unscored - and the transient is where the
        # sweep leg latched. These two pin it, and they are the ONLY measured
        # bounds in this entry.
        #
        # WHY THIS LEG AND NOT THE SWEEP: here the total is SETTLED at the step
        # (2.0007 A, motor-free), so the load EMA is accurate and the figures
        # are the clamp's own. On the sweep's region 5 -> 6 boundary the total
        # was RISING and the same mechanism read 1.4890 A. The difference
        # between the two numbers IS the hazard of design note section 8.6.
        {"name": "ceiling_step_overshoot", "column": "I_fc",
         "max_value": 1.30, "t_window": (_CEILING_STEP_T,
                      _CEILING_STEP_T + _CEILING_STEP_WIN_S),
         "label": "the commanded share step at t = 8.0 s did not overshoot the "
                  "acceptance band in its first 100 ms (<= 1.30 A; MEASURED "
                  "1.2502 A in campaign E = 0.016 % over the 1.2500 A "
                  "ceiling). A tripwire on the transient, not a budget"},
        {"name": "ceiling_step_settling", "column": "I_fc",
         "min_value": 1.2450, "aux_bit": "fc_ceiling_active",
         "reach_within_ms": 60.0,
         "t_window": (_CEILING_STEP_T, _CEILING_STEP_T + 0.5),
         "label": "I_fc reached the ceiling band within 60 ms of the clamp "
                  "ENGAGING (MEASURED 35 ms in campaign E). Measured from the "
                  "aux bit's own rising edge, so the figure is the clamp's "
                  "settling and not the 3.3 - 17.7 ms Pi command cadence"},
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# fw26-clamp-sweep — the clamp's engagement and release, six times each way
#
# THE ENTRY IS BUILT FROM THE STIMULUS TABLE, not written out region by region.
# `FW26_CLAMP_SWEEP_REGIONS` carries each region's velocity, commanded share and
# expected classification, so a table edit that moves a boundary moves the checks
# with it. Writing twelve regions out by hand is exactly how a check window and
# the stimulus it judges drift apart.
#
# ⚠️ EVERY BOUND IS A WALK, NOT A MEASUREMENT, and one input to it is a
# prediction: the region totals are the HOST demand model's, while in a HIL run
# the board's own drive loop sets the VESC current and therefore the total. The
# margins are what absorbs that (sub-threshold regions clear the clamp boundary
# by 0.20 A to 0.29 A of fuel-cell demand, clamped ones exceed it by 0.29 A to
# 0.45 A). The first campaign that runs this scenario re-derives all of it.
#
# ⚠️ THE CLAMP IS NOT EXPECTED TO ACT IN AN FC-CHARGE WINDOW, and this scenario
# opens none. That regime is single-source by construction and `OC_FC` there is
# DESIGN INTENT, read by the EMS as feedback about a charge window it should not
# have opened - see FAULT_EXPECTATIONS["charge-cruise"]. fw v26 does not change
# it and is not meant to.
#
# ── CAMPAIGN E (hil_report_20260903_031220): THE FIRST RUN, AND THE SCENARIO
#    DEFECT IT FOUND ─────────────────────────────────────────────────────────
# The run LATCHED `OC_FC` at t = 38.029241 s, I_fc 1.4890 A. The board was
# CORRECT and the stimulus was wrong: the region 5 -> 6 boundary stepped
# v_setpoint 2.5 -> 3.0 m/s AND the commanded share 0.40 -> 0.84 in the SAME Pi
# packet, so the drive controller railed at its 12 A clamp (I_tot 1.8418 ->
# 2.9895 A) while the share loop was slewing its reference upward. The clamp
# engaged on the first tick it saw the new share - zero engagement delay - but
# its ~20 ms load EMA under-read the total by 25.6 % against the clamp's 12 %
# design headroom, so it held what it believed was 1.2500 A while the board
# delivered 1.4890 A. Decomposition of the +0.2390 A error: filter under-read
# +0.4298 A, plant lagging the reference -0.1910 A. Region 10 -> 11 is the same
# defect. FIXED by the bridging sub-region at hil_plant_sim
# FW26_CLAMP_SWEEP_BRIDGE_S; hazard statement at
# docs/fw26_current_ceiling_governor.md section 8.6.
#
# ⚠️ TRAP FOR THE NEXT ANALYST. Ten of this entry's checks PASSED on that run
# and every one of them is NON-EVIDENCE: after the State-99 latch the aux byte
# and the MDAC mirrors FREEZE, so `sweep_r06/r09/r11_clamped` passed on a frozen
# bit, the `*_fc_under_limit` bounds passed at 0.0000 A on a dark bus, and four
# MDAC pins passed on frozen words. Only regions 1-5 and the pre-latch
# aggregates were real.
#
# ── FIRST CALIBRATION OF THE CLAMP (campaign E, the numbers this entry's future
#    bounds are read against) ────────────────────────────────────────────────
#   engagement latency   3.3 - 17.7 ms, and it is PI-CADENCE-LIMITED, not
#                        clamp-limited: the 48.7 Hz command cadence sets the
#                        phase (17.7 ms at the sweep's region 5 -> 6 boundary,
#                        3.3 ms on `fw26-clamp-cruise`). The clamp itself
#                        engages on the first tick it sees the new setpoint.
#   reference slew       ~6 ticks to walk the droop ratio onto the bound
#                        (DROOP_RATIO_SLEW_PER_TICK 0.02)
#   settling             35 ms to the ceiling band, measured on
#                        `fw26-clamp-cruise` at a settled total
#   overshoot, settled   0.016 % (1.2502 A against the 1.2500 A ceiling)
#   overshoot, load step +0.031 A (region 1 -> 2, 1.2811 A) to +0.045 A
#                        (region 3 -> 4, 1.2954 A) on a PURE upward load step at
#                        an already-clamped share - 7.5 % clear of the 1.4 A
#                        limit at the worse of the two
#
# Walked with tools/governor_model.py at the plant's measured asymmetry
# (dv0 0.013522 V) and at zero; the two agree on every current to four decimals.
# REGENERATED 2026-09-03 with the corrected split law - run
#     C:/Users/ricky/miniforge3/python.exe tools/probes/probe_fw26_clamp_walk.py
# and paste; `test_fw26_sweep_walk_regenerates_the_region_table` fails if this
# table and that probe disagree. The CURRENTS did not move (the clamp pins the
# fuel-cell current and the law moves only the RATIO that delivers it); every
# mdac column did, by up to +4.5 % on the code. See
# docs/modeling/governor_split_law_20260903.md.
# Per region, over the settled window (region start + 2.5 s to region end):
#
#   reg   v    sp    I_tot    I_fc    I_batt   duty   mdac_fc  mdac_bt  clamp?
#    1   0.0  0.84   1.200   0.9000   0.3000  0.000     4917     6464   no
#    2   3.0  0.84   2.016   1.2500   0.7663  1.000     5100     5648   YES
#    3   0.5  0.84   1.284   0.9844   0.3000  0.000     4898     6641   no
#    4   2.5  0.84   1.827   1.2500   0.5775  1.000     5000     5972   YES
#    5   2.5  0.40   1.827   0.7310   1.0965  0.000     5723     5072   no
#    6   3.0  0.84   2.016   1.2500   0.7663  1.000     5100     5648   YES
#    7   3.0  0.20   2.016   0.4033   1.6130  0.000     7527     4838   no
#    8   0.0  0.84   1.200   0.9000   0.3000  0.000     4917     6464   no
#    9   3.0  0.84   2.016   1.2500   0.7663  1.000     5100     5648   YES
#   10   0.5  0.50   1.284   0.6422   0.6422  0.000     5376     5261   no
#   11   2.5  0.84   1.827   1.2500   0.5775  1.000     5000     5972   YES
#   12   0.0  0.50   1.200   0.6000   0.6000  0.000     5378     5259   no
#
# Whole run: 29996 clamped ticks of 80000, zero cut refusals, zero BT-clamp
# ticks, |I_tot - I_fc - I_batt| identically zero.
#
# THE CAMPAIGN-F BOARD PAIRS, beside the walk that now predicts them (mean over
# each region's scored window, campaign hil_report_20260903_063659):
#
#   reg   board mdac_fc/bt   walk         old-law walk   board alpha   walk r
#    1      4917 / 6463      4917 / 6464  4917 / 6468    0.750162      0.7426
#    3      4898 / 6643      4898 / 6641  4898 / 6638    0.766980      0.7606
#    5      5723 / 5072      5723 / 5072  5644 / 5102    0.399996      0.3750
#    7      7525 / 4838      7527 / 4838  7201 / 4855    0.200010      0.1778
#   10      5376 / 5261      5376 / 5261  5337 / 5295    0.500001      0.4764
#   12      5378 / 5260      5378 / 5259  5339 / 5293    0.500005      0.4758
#
# Every sub-threshold region now agrees with the board to within 2 codes; the
# old law missed region 12 by 3.1 % against its own 2 % band (an adjudicated
# campaign-F FAIL) and region 7 by 4.5 %.
#
# THE BIT-IDENTITY EVIDENCE. The same walk with the ceilings pinned out of reach
# - the fw v25 arithmetic - reproduces the mdac pair EXACTLY on all seven
# sub-threshold regions and differs on all five clamped ones (region 2, for
# instance, reads (4822, 7895) with the clamp absent against (5100, 5648) with
# it). Regions 1, 8 and 12 are commanded at standstill, so their total is the
# aux load alone and carries none of the drive loop's uncertainty; those three
# are where the codes are PINNED on the board, joined since 2026-09-03 by
# region 10 (0.5 m/s), the only sub-threshold region commanded at share 0.50. That is the on-board statement of
# "below the ceiling, fw v26 is arithmetically identical to fw v25" - the host
# suite asserts it as an equality, and this asserts it against the hardware.
# WARNING - SETTLE RAISED 1.5 -> 2.5 s (H3, 2026-09-02). Regions 2 and 9 step
# the velocity setpoint from standstill to 3.0 m/s, which RAILS the drive
# controller at its 12 A current clamp for about 1.69 s:
# v(t) = 13.19 (1 - exp(-0.1526 t)) at K_F 0.7538, F_COULOMB 2.00 N,
# B_EFF 0.534 and M_EFF 3.5 kg. A 1.5 s inset therefore opened every such
# window while the drive loop was still saturated, so the first ~190 ms of the
# "settled" window carried a moving total and a moving clamp boundary. 2.5 s
# clears the rail by 0.81 s.
_FW26_SWEEP_SETTLE_S = 2.5
# THE BRIDGE MUST BE UNSCORED (campaign E, 2026-09-03). Two boundaries carry a
# bridging sub-region that holds the previous region's share for
# FW26_CLAMP_SWEEP_BRIDGE_S after the velocity step, so a region window that
# opened before the bridge closed would score the PREVIOUS share against THIS
# region's classification. The settle inset already excludes it; this asserts
# the relation instead of leaving it to be noticed.
assert FW26_CLAMP_SWEEP_BRIDGE_S < _FW26_SWEEP_SETTLE_S, (
    "the fw26 sweep bridge (%.3f s) must close before the settle inset "
    "(%.3f s) opens each region's scored window"
    % (FW26_CLAMP_SWEEP_BRIDGE_S, _FW26_SWEEP_SETTLE_S))
_FW26_SWEEP_SPAN_TICKS = int(1000.0 * (FW26_CLAMP_SWEEP_REGION_S
                                       - _FW26_SWEEP_SETTLE_S))       # 3500
_FW26_SWEEP_DUTY_TICKS = int(0.78 * _FW26_SWEEP_SPAN_TICKS)           # 2730
# The cadence gate this entry's tick floors are derived from (M8). It was 4000
# rows in a 72 s window, 5.6 % coverage, while the switch floors below assumed
# 94 %; a half-cadence stream then failed a TOPOLOGY check instead of the
# cadence check.
_FW26_SWEEP_CADENCE_COVER = 0.94
_FW26_SWEEP_CADENCE_ROWS = int(1000.0 * 72.0 * _FW26_SWEEP_CADENCE_COVER)
_FW26_SWEEP_BUS_HOLD_TICKS = int(0.98 * _FW26_SWEEP_CADENCE_ROWS)

# -- THE MDAC PIN (M1, corrected 2026-09-02) ---------------------------------
# TWO CORRECTIONS, and the second changes what the arm claims.
#
# 1. THE TOLERANCE WAS APPLIED TO THE WRONG NUMBER. `mdac_fc` / `mdac_bt` carry
#    the RAW AD5443 command word, which is MDAC_CMD_LOAD_UPDATE (0x1000) OR'd
#    with the 12-bit gain code. A +/- 6 % band on the WORD is a +/- 36 % band
#    on the CODE at region 1 (word 4917 = 0x1000 | 821), because the constant
#    4096 offset dilutes it. The nibble is now stripped, the band is applied to
#    the code, and the bound is offset back into word space.
#
# 2. THE SUB-THRESHOLD ARM IS NOT A BIT-IDENTITY DISCRIMINATOR. At every
#    sub-threshold region the fuel-cell bound 1.25/I_tot EXCEEDS DROOP_R_MAX,
#    so `applyShareCurrentCeilings()` is the identity BY CONSTRUCTION and the
#    arm cannot fail from a clamp defect however it is tuned. What it does pin
#    is MODEL FIDELITY: the board's droop codes at a known standstill total
#    against the walk's. It is kept, and relabelled to say so.
#
#    THE ACTUAL v25-vs-v26 DISCRIMINATOR IS A CLAMPED REGION'S PAIR. Region 2
#    reads (4822, 7895) with the clamp absent and (5100, 5648) with it present:
#    codes 726 against 1004 on FC (+38 %) and 3799 against 1552 on BT (-59 %).
#    That pin is added below. It sits on a DRIVEN region, so it carries the
#    drive loop's own uncertainty and takes a wider band - still an order of
#    magnitude inside the gap it has to resolve.
_FW26_MDAC_NIBBLE = gov_mod.GOV_CONST["MDAC_CMD_LOAD_UPDATE"]     # 0x1000
_FW26_SWEEP_MDAC_TOL = 0.02          # standstill regions, code-space
_FW26_SWEEP_MDAC_TOL_DRIVEN = 0.10   # clamped regions, code-space
# Walked (mdac_fc, mdac_bt) raw words at each SUB-THRESHOLD region, clamp
# ABSENT and clamp present alike - they are identical there.
#
# RE-WALKED 2026-09-03 (review run-002, PLANT-R2-F3). `governor_model`'s split
# law carried only the dV0 half of the M2 asymmetry fit and no series floor, so
# every one of these words was an output of a wrong law:
#
#   region 1/8   (4917, 6468) -> (4917, 6464)   board 4917 / 6463
#   region 12    (5339, 5293) -> (5378, 5259)   board 5378 / 5260
#
# Region 12 is why this is a re-pin and not a refinement: its old pair sat
# 3.1 % from the board on a +/- 2 % band and FAILED in campaign F. Regions 1
# and 8 moved by 4 codes (0.17 %) because their r ~ 0.743 is close to where the
# rho and R_f terms cancel - the same reason they passed all along.
_FW26_SWEEP_MDAC_PIN = {1: (4917, 6464), 8: (4917, 6464),
                        10: (5376, 5261), 12: (5378, 5259)}
# ── REGION 10, ADDED 2026-09-03 ─────────────────────────────────────────────
# THE ONLY PINNED REGION THAT IS NOT AT STANDSTILL, and it is added
# deliberately: it is the sweep's only sub-threshold region commanded at share
# 0.50, i.e. at the ratio where the corrected law's correction is LARGEST
# (+3.1 % of r) while regions 1/8 sit where it nearly vanishes. A pin table
# made only of standstill regions therefore cannot see the defect this round
# fixed.
#
# Its total carries a drive-loop term - 0.0844 A of 1.284 A at 0.5 m/s - so it
# takes its own wider band rather than the standstill 2 %. The band is set at
# 5 %: the walk reproduces the board's region-10 pair EXACTLY (5376 / 5261 on
# both), and the neighbouring 0.5 m/s region 3 to within 2 codes (0.03 %), so
# 5 % is ~150x the observed model error and still 3x tighter than the driven
# clamped band.
_FW26_SWEEP_MDAC_TOL_R10 = 0.05
_FW26_SWEEP_MDAC_TOL_BY_REGION = {10: _FW26_SWEEP_MDAC_TOL_R10}
# Walked (mdac_fc, mdac_bt) raw words at a CLAMPED region, clamp PRESENT, with
# the clamp-absent pair recorded beside it as the value this pin refuses.
# RE-WALKED 2026-09-03 with the corrected law: present (5088, 5679) ->
# (5100, 5648), absent (4824, 7837) -> (4822, 7895). The board read
# (5110, 5626), so the re-walked pair is 1.0 % / 1.4 % from it where the old
# one was 2.2 % / 3.5 %.
_FW26_SWEEP_MDAC_CLAMPED_PIN = {2: ((5100, 5648), (4822, 7895))}


def _fw26_mdac_band(word, tol):
    """[lo, hi] raw-word bounds for a walked word at `tol` in CODE space.

    The nibble is stripped, the tolerance applied to the 12-bit gain code, and
    the result offset back into word space -- so a 2 % band is 2 % of the
    quantity that actually moves (M1)."""
    code = int(word) & 0x0FFF
    lo = _FW26_MDAC_NIBBLE + int(code * (1.0 - tol))
    hi = _FW26_MDAC_NIBBLE + int(code * (1.0 + tol)) + 1
    return lo, hi


def _fw26_sweep_signals():
    """The twelve regions' checks, generated from the stimulus table."""
    out = [
        # 0. THE CADENCE CENSUS, so nothing below can pass on a run whose
        #    observation stream stalled.
        # Its floor is the one every tick floor in this entry is derived
        # from (M8): a lossy stream must fail HERE, by name, and not as a
        # spurious "a bus switch opened" or "the clamp never engaged".
        {"name": "sweep_cadence", "min_rows": _FW26_SWEEP_CADENCE_ROWS,
         "t_window": (8.0, 80.0),
         "label": "the run streamed at full cadence across the whole region "
                  "table (>= %d rows in a 72 s window = %.0f %% of the 1 kHz "
                  "nominal)" % (_FW26_SWEEP_CADENCE_ROWS,
                                100.0 * _FW26_SWEEP_CADENCE_COVER)},
    ]
    for i, (t0, v, sp, clamped) in enumerate(FW26_CLAMP_SWEEP_REGIONS,
                                             start=1):
        w = (t0 + _FW26_SWEEP_SETTLE_S, t0 + FW26_CLAMP_SWEEP_REGION_S)
        if clamped:
            # THE CLAMP BOUND, and held for essentially the whole settled
            # window. 78 % of it is a floor loose enough for a slow engagement
            # and unreachable by a run in which the clamp merely chattered.
            out.append(
                {"name": "sweep_r%02d_clamped" % i,
                 "aux_bit": "fc_ceiling_active",
                 "min_ticks": _FW26_SWEEP_DUTY_TICKS,
                 "t_window": w,
                 "label": "region %d (v %.1f m/s, share %.2f, walked total "
                          "%.3f A - the HOST demand model's, not the board's): "
                          "the FC ceiling BOUND for >= %d of the settled "
                          "window's %d ticks"
                          % (i, v, sp, _fw26_region_total(v),
                             _FW26_SWEEP_DUTY_TICKS, _FW26_SWEEP_SPAN_TICKS)})
            # ... and the acceptance band on the delivered current, two-sided.
            out.append(
                # `floor_min_value`: the claim is that I_fc was HELD at the
                # ceiling for the whole settled window, which is the in-window
                # MINIMUM. `min_value` tests the maximum and would pass on a
                # single tick (H2).
                {"name": "sweep_r%02d_fc_at_ceiling" % i, "column": "I_fc",
                 "floor_min_value": 1.20, "t_window": w,
                 "label": "region %d: I_fc never fell below the ceiling band "
                          "(>= 1.20 A on every sample)" % i})
            out.append(
                {"name": "sweep_r%02d_fc_under_limit" % i, "column": "I_fc",
                 "max_value": 1.30, "t_window": w,
                 "label": "region %d: I_fc inside the acceptance band "
                          "(<= 1.30 A, against LIMIT_I_FC_MAX 1.4 A)" % i})
        else:
            # THE CLAMP DID NOTHING. Below the ceiling fw v26 is arithmetically
            # identical to fw v25, and the aux bit is the board's own statement
            # of that.
            out.append(
                {"name": "sweep_r%02d_inert" % i,
                 "aux_bit": "fc_ceiling_active", "max_ticks": 0, "t_window": w,
                 "vacuity_note": ("the aux column cannot be blank here: the "
                                  "clamped regions' `min_ticks` checks assert "
                                  "the same byte streamed and parsed with a "
                                  "bit SET, so a zero count is a read of the "
                                  "bit and not an absent column"),
                 "label": "region %d (v %.1f m/s, share %.2f, walked total "
                          "%.3f A): the FC ceiling did NOT bind - below it "
                          "fw v26 is fw v25"
                          % (i, v, sp, _fw26_region_total(v))})
        if i in _FW26_SWEEP_MDAC_PIN:
            # THE MODEL-FIDELITY PIN, on the board (M1, relabelled 2026-09-02).
            # NOT a clamp discriminator: at a sub-threshold region the
            # fuel-cell bound 1.25/I_tot exceeds DROOP_R_MAX, so the clamp is
            # the identity BY CONSTRUCTION and this pair cannot move whether
            # the clamp is present or not. What it pins is the board's droop
            # codes against the walk's at a known standstill total, where the
            # total is the aux load alone and carries none of the drive loop's
            # uncertainty. REGION 10 IS THE ONE EXCEPTION (2026-09-03): it is
            # commanded at 0.5 m/s and at share 0.50, which is where the split
            # law's correction is largest, and it takes its own wider band -
            # see _FW26_SWEEP_MDAC_TOL_BY_REGION.
            _tol = _FW26_SWEEP_MDAC_TOL_BY_REGION.get(i,
                                                      _FW26_SWEEP_MDAC_TOL)
            for col, want in zip(("mdac_fc", "mdac_bt"),
                                 _FW26_SWEEP_MDAC_PIN[i]):
                lo, hi = _fw26_mdac_band(want, _tol)
                out.append(
                    {"name": "sweep_r%02d_%s_lo" % (i, col), "column": col,
                     "floor_min_value": lo, "t_window": w,
                     "label": "region %d: %s tracks the walk on every sample "
                              "(>= %d; walked %d = 0x1000 | %d, +/- %.0f %% on "
                              "the 12-bit CODE). MODEL FIDELITY, not clamp "
                              "evidence - the clamp is the identity here by "
                              "construction"
                              % (i, col, lo, want, want & 0x0FFF,
                                 100.0 * _tol)})
                out.append(
                    {"name": "sweep_r%02d_%s_hi" % (i, col), "column": col,
                     "max_value": hi, "t_window": w,
                     "label": "region %d: %s tracks the walk (<= %d)"
                              % (i, col, hi)})
        if i in _FW26_SWEEP_MDAC_CLAMPED_PIN:
            # THE fw v25 / fw v26 DISCRIMINATOR (M1, new 2026-09-02). A CLAMPED
            # region's droop pair is the only mdac observable the clamp
            # actually moves. Region 2 walks to (5100, 5648) with the clamp
            # present and (4822, 7895) without it - codes 1004 against 726 on
            # FC and 1552 against 3799 on BT. The band is +/- 10 % in code space
            # because this is a DRIVEN region and the board's own drive loop
            # sets the total; the gap it has to resolve is 38 % and 59 %.
            _present, _absent = _FW26_SWEEP_MDAC_CLAMPED_PIN[i]
            for col, want, refuse in zip(("mdac_fc", "mdac_bt"),
                                         _present, _absent):
                lo, hi = _fw26_mdac_band(want, _FW26_SWEEP_MDAC_TOL_DRIVEN)
                assert not (lo <= refuse <= hi), (
                    "region %d %s: the +/- %.0f %% band [%d, %d] admits the "
                    "CLAMP-ABSENT value %d, so this pin cannot discriminate "
                    "fw v25 from fw v26"
                    % (i, col, 100.0 * _FW26_SWEEP_MDAC_TOL_DRIVEN, lo, hi,
                       refuse))
                out.append(
                    {"name": "sweep_r%02d_%s_clamped_lo" % (i, col),
                     "column": col, "floor_min_value": lo, "t_window": w,
                     "label": "region %d: %s matches the CLAMP-PRESENT walk on "
                              "every sample (>= %d; walked %d, the "
                              "clamp-ABSENT value is %d and is refused by this "
                              "band) - THE fw v25/v26 DISCRIMINATOR"
                              % (i, col, lo, want, refuse)})
                out.append(
                    {"name": "sweep_r%02d_%s_clamped_hi" % (i, col),
                     "column": col, "max_value": hi, "t_window": w,
                     "label": "region %d: %s matches the CLAMP-PRESENT walk "
                              "(<= %d; clamp-absent %d)"
                              % (i, col, hi, refuse)})
    # ── whole-run structure ─────────────────────────────────────────────────
    out += [
        # THE BATTERY CEILING IS NOT EXERCISED at any region's total.
        {"name": "sweep_bt_ceiling_never", "aux_bit": "bt_ceiling_active",
         "max_ticks": 0, "t_window": (8.0, 80.0),
         "vacuity_note": ("the aux column cannot be blank across this window: "
                          "the clamped regions assert the same byte with a bit "
                          "SET inside it"),
         "label": "the BT ceiling never bound (it would need 2.70 A on one "
                  "channel against a 2.02 A worst-case bus)"},
        # THE CLAMP NEVER OPENED A BUS SWITCH. A reference outside the droop
        # band IS the channel-cutoff signal, so the band constraint at the tail
        # of applyShareCurrentCeilings() is structural; this asserts it on the
        # board. Zero rising edges: a cut followed by a restore would satisfy a
        # tick floor and is exactly the failure a tick floor cannot see.
        {"name": "sweep_no_switch_ring", "switch_bit": SW_FC_BUS,
         "edge_count_between": (0, 0), "edge": "rise", "t_window": (8.0, 80.0),
         "label": "no FC_BUS rising edge anywhere in the table - no cut, and "
                  "therefore no sw_ring"},
        {"name": "sweep_bt_bus_held", "switch_bit": SW_BT_BUS,
         "min_ticks": _FW26_SWEEP_BUS_HOLD_TICKS, "t_window": (8.0, 80.0),
         "label": "BT_BUS_ENABLE stayed high across the whole table (>= %d "
                  "ticks = 98 %% of the rows `sweep_cadence` guarantees) - the "
                  "split is genuinely two-source, which is what makes the "
                  "clamp reachable at all" % _FW26_SWEEP_BUS_HOLD_TICKS},
        # -- WHOLE-TABLE CURRENT BOUNDS (H3, 2026-09-02) --------------------
        # The per-region checks bound the FUEL CELL only, and only inside the
        # settled windows. The clamp's whole action is to move current onto the
        # BATTERY, so the quantity the mechanism can run away in was
        # unbounded, and the region transitions - where the drive controller
        # rails at 12 A for ~1.69 s - were outside every window. These two
        # bounds cover the whole table, transitions included.
        #
        # The walked worst case is region 7's 1.6130 A of battery and region
        # 2/6/9's 2.016 A of total. LIMIT_I_BT_MAX is 3.0 A. 2.4 A gives the
        # battery 49 % over its walked worst case and 20 % under the fault
        # limit; 3.6 A gives the total 79 % over its walked worst case and sits
        # under the FC + BT fault pair (4.4 A).
        {"name": "sweep_batt_bounded", "column": "I_batt",
         "max_value": 2.4, "t_window": (8.0, 80.0),
         "label": "the battery never carried more than 2.4 A anywhere in the "
                  "table, transitions included (walked worst case 1.6130 A in "
                  "region 7; LIMIT_I_BT_MAX is 3.0 A) - the clamp's own "
                  "liability, since what it takes off the fuel cell goes here"},
        {"name": "sweep_total_bounded", "sum_of": ["I_fc", "I_batt"],
         "max_value": 3.6, "t_window": (8.0, 80.0),
         "label": "the two-source total never exceeded 3.6 A anywhere in the "
                  "table (walked worst case 2.016 A) - the drive controller "
                  "rails at 12 A for ~1.69 s on the standstill-to-3.0 m/s "
                  "steps of regions 2 and 9, and this is the bound on what "
                  "that puts on the bus"},
    ]
    return out


def _fw26_region_total(v):
    """The walked two-source total at a region's velocity setpoint [A].

    The motor terms are the demand model's at a constant setpoint; the floor is
    the aux load. Stated here rather than re-typed into twelve labels."""
    motor = {0.0: 0.0, 0.5: 0.0844, 1.5: 0.3143, 2.5: 0.6275, 3.0: 0.8163}
    return I_AUX_A + FW26_CLAMP_SWEEP_PRELOAD_A + motor[v]


FAULT_EXPECTATIONS["fw26-clamp-sweep"] = {
    "source": ("applyShareCurrentCeilings() (.ino:10273-10313) with "
               "SHARE_GOV_I_FC_CEIL_A 1.25 A and SHARE_GOV_CEIL_HYST_A 0.05 A "
               "(.ino:2406/:2430), against LIMIT_I_FC_MAX 1.4 A (.ino:1425). "
               "Region table and load derivation at "
               "hil_plant_sim.FW26_CLAMP_SWEEP_REGIONS; bounds from the "
               "offline governor_model walk recorded above, including the "
               "clamp-absent arm the mdac pins come from."),
    "provisional_note": ("EVERY BOUND IN THIS ENTRY IS WALKED, NOT MEASURED - "
                         "regions 6-12 have still never been SCORED on the "
                         "board: campaign E (2026-09-03) latched OC_FC at the "
                         "then-unbridged region 5 -> 6 boundary and every "
                         "later check passed on a frozen aux byte and frozen "
                         "MDAC mirrors. Regions 1-5 and the pre-latch "
                         "aggregates ARE measured, and the settled region "
                         "totals matched the host demand model to within "
                         "1.5 %. Re-derive the rest from the first campaign "
                         "that runs the BRIDGED table."),
    # FAULT-FREE, and OC_FC in particular: the whole point of the clamp is that
    # the fuel cell is held at 1.25 A instead of climbing to the 1.4 A latch. A
    # run that latches OC_FC here has not failed a check, it has falsified the
    # mechanism.
    "allow_only": 0,
    # Past the last clamped region and into the closing sub-threshold one.
    "survive_to": {"t": 74.0, "states": {2, 3}},
    "signals_require": _fw26_sweep_signals(),
}


# ─────────────────────────────────────────────────────────────────────────────
# fw26-clamp-joint — the JOINT transient, as a number
#
# THE THIRD fw v26 LEG, ruled in by the operator on 2026-09-03. It pins, at a
# total the fault limit cannot be reached from, the coincidence that latched
# OC_FC on `fw26-clamp-sweep` in campaign E: an upward commanded share step
# landing in the same instant as an upward demand step. Design
# docs/fw26_current_ceiling_governor.md section 8.6.5; stimulus derivation at
# SCENARIOS["fw26-clamp-joint"].
#
# WHY THIS LEG IS SAFE WHERE THE SWEEP WAS NOT. The necessary condition for the
# hazard is a two-source total above LIMIT_I_FC_MAX / DROOP_R_MAX = 1.647 A
# (1.645 A under the corrected split law). This leg steps to 1.65 A, which is
# 0.10 A above the 1.55 A reachability threshold and 0.003 A above the
# condition. The sweep reached 2.99 A.
#
# WHAT SETS THE PEAK, AND IT IS NOT THE CEILING. Through the transient the
# governor's ~20 ms load EMA still reads the OLD total, so the clamp's rail
# SHARE_GOV_I_FC_CEIL_A / filt sits ABOVE the minority clip's rail
# 1 - SHARE_MINORITY_I_MIN_A / filt and the CLIP binds. The two cross at
# filt = 1.25 + 0.30 = 1.55 A, and the delivered current is largest there. The
# structural bound is
#
#     (I_tot - SHARE_MINORITY_I_MIN_A) - SHARE_GOV_I_FC_CEIL_A = 0.10 A
#
# over the ceiling, i.e. 1.35 A; the acceptance bound is 1.36 A, 0.4 % above
# the walk and 2.9 % under LIMIT_I_FC_MAX.
#
# ⚠️ EVERY BOUND BELOW IS A WALK, NOT A MEASUREMENT, through
# tools/probes/probe_fw26_clamp_walk.joint() at the plant's measured asymmetry
# and the CORRECTED split law (rho 0.9434, R_f 0.033 ohm):
#
#   pre-step, share 0.40, total 1.20 A, t = 9..15.9
#       clamp duty 0.0000 (unclamped demand 0.48 A, 62 % under the ceiling)
#       I_fc 0.4800 A, I_batt 0.7200 A, mdac (5736, 5067)
#   THE JOINT STEP at t = 16.0, to share 0.84 and total 1.65 A
#       peak delivered I_fc      1.3303 A   <- the acceptance bound judges this
#       first clamp engagement   +29 ms
#       I_fc into the band       +82 ms, i.e. 53 ms after engagement
#       clamp duty, post-step    0.9976
#   post-step settled, t = 17..26.5
#       clamp duty 1.0000, I_fc 1.2500 A, I_batt 0.4000 A,
#       balance residual 5.6e-17, applied ratio 0.7524, mdac (4906, 6560)
#
# THE CLAMP-ABSENT ARM, walked the same way with the ceilings pinned out of
# reach - fw v25's arithmetic. It is what makes this leg a DISCRIMINATOR rather
# than a description: the settled current is 1.3500 A (the clip rail) against
# 1.2500 A, I_batt 0.3000 A against 0.4000 A, and mdac (4843, 7413) against
# (4906, 6560). The settled I_fc band below refuses 1.3500 A by 0.05 A.
#
# THE WALK IS SPLIT-LAW INVARIANT, and that is worth recording rather than
# assuming. Re-run with rho = 1 and R_f = 0 (the pre-2026-09-03 law) the peak is
# 1.3303 A and the codes are (4906, 6560) to the digit: the firmware pins the
# applied RATIO on its own rails, and the split law only re-inverts the ratio
# that delivers it. The design record's section 8.6.5 table carries both rows.
#
# THE COMMANDER-CADENCE SKEW IS BOUNDED AND HARMLESS. The share step arrives on
# the Pi's own ~50 Hz packet while apply_scenario() steps the load at 1 kHz, so
# the two land up to one commander period apart in either order. Walked at
# +/- 20 ms the peak is 1.3303 A (share first, or simultaneous) or 1.2931 A
# (load first) - the order cannot make it worse than simultaneous, because the
# peak is set by the rail crossing and the reference has reached 0.84 long
# before the filtered total passes 1.55 A. The transient window below is 300 ms
# wide, so it contains the peak under every skew.
_JOINT_STEP_T = 16.0                  # SCENARIOS[...]["pi_timeline"] and the
                                      # second aux_preload_step entry
_JOINT_STEP_WIN_S = 0.30              # the transient window, > the 20 ms skew
_JOINT_A0, _JOINT_A1 = 9.0, 15.9      # pre-step, inset past the load plateau
_JOINT_B0, _JOINT_B1 = 17.0, 26.5     # post-step settled, inset past the step
# THE CADENCE GATE AND THE TICK FLOORS ARE ONE NUMBER, the `fw26-clamp-cruise`
# M8 rule: a lossy stream must fail HERE by name and not as a spurious "a bus
# switch opened" or "the clamp never engaged".
_JOINT_CADENCE_COVER = 0.98
_JOINT_CADENCE_ROWS = int(1000.0 * (_JOINT_B1 - _JOINT_A0)
                          * _JOINT_CADENCE_COVER)              # 17150
_JOINT_BUS_HOLD_TICKS = int(0.98 * _JOINT_CADENCE_ROWS)        # 16807
# 78 % of the settled window, the `fw26-clamp-sweep` duty rule: loose enough for
# a slow engagement, unreachable by a clamp that merely chattered.
_JOINT_SETTLED_DUTY_TICKS = int(0.78 * 1000.0 * (_JOINT_B1 - _JOINT_B0))  # 7410
# THE ACCEPTANCE BOUND on the transient peak. Named once.
_JOINT_ACCEPT_PEAK_A = FW26_CLAMP_JOINT_ACCEPT_PEAK_A          # 1.36
_JOINT_PROVISIONAL = (
    "PROVISIONAL - EVERY BOUND IN THIS ENTRY IS WALKED AND NONE HAS BEEN "
    "SCORED ON THE BOARD. The scenario is registered as of 2026-09-03 "
    "(operator ruling) and has never run. The walk carries no drive-loop "
    "uncertainty - the leg is motor-free, so the two-source total is the "
    "scripted aux load alone - and the MDAC pins are walked at the corrected "
    "split law (fe92a50, which closed campaign F's region-12 code-mapping gap "
    "to <= 0.05 % on every settled window); their band is wider than the "
    "currents' only because this leg has never been executed. The first "
    "campaign that runs this leg "
    "re-derives all of it; read a miss against the ceiling's own "
    "TODO(calibrate) rather than by widening a bound.")



# ── fw26-clamp-joint: the settled droop-code pins ────────────────────────────
# Walked (mdac_fc, mdac_bt) raw words over the post-step settled window, clamp
# PRESENT, with the clamp-ABSENT pair recorded beside each as the value the pin
# refuses. Both from probe_fw26_clamp_walk.joint() at the corrected split law.
#
# ⚠️ ONLY `mdac_bt` DISCRIMINATES, and the entry says so rather than implying
# both do. Clamp-present (4906, 6560) against clamp-absent (4843, 7413): the BT
# code moves 11.5 % and the FC code only 1.3 %, because the clamp and the clip
# rails differ mainly in how much load they push onto the BATTERY. The FC pin is
# therefore a MODEL-FIDELITY pin, in `fw26-clamp-sweep`'s standstill sense.
#
# THE BAND IS 8 %, wider than the sweep's standstill 2 %, for one stated reason:
# the leg has never been executed. The code-mapping gap campaign F measured
# (exact at share 0.84, +3.1 % at 0.50) was CLOSED by the corrected split law
# (fe92a50: rho + the 0.033 ohm floor; board windows reproduced to <= 1.1e-4),
# and this walk uses that law, so the residual model error at the settled
# ratio 0.7524 is expected at the sweep's 2 % level. The 8 % is first-execution
# headroom, to be tightened to the sweep's band once a campaign has scored it.
# 8 % still refuses the clamp-absent BT code by 26.6 % of the code (band
# (6362, 6758) against 7413; 9.7 % of the raw word), which is asserted below
# rather than asserted by eye.
_FW26_JOINT_MDAC_TOL = 0.08
_FW26_JOINT_MDAC_PIN = ((4906, 6560), (4843, 7413))   # (present, absent)


def _fw26_joint_mdac_signals():
    """The two settled droop-code pins, generated so the band arithmetic and
    the discrimination assertion cannot drift from the walked pair."""
    out = []
    present, absent = _FW26_JOINT_MDAC_PIN
    for col, want, refuse, kind in zip(
            ("mdac_fc", "mdac_bt"), present, absent,
            ("MODEL FIDELITY - the clamp moves this code only 1.3 %, so it "
             "cannot discriminate fw v25 from fw v26",
             "THE fw v25/v26 DISCRIMINATOR in code space - the clamp-absent "
             "value is refused by this band")):
        lo, hi = _fw26_mdac_band(want, _FW26_JOINT_MDAC_TOL)
        discriminates = not (lo <= refuse <= hi)
        if col == "mdac_bt":
            assert discriminates, (
                "fw26-clamp-joint mdac_bt: the +/- %.0f %% band [%d, %d] "
                "admits the CLAMP-ABSENT value %d, so this pin cannot "
                "discriminate fw v25 from fw v26"
                % (100.0 * _FW26_JOINT_MDAC_TOL, lo, hi, refuse))
        out.append(
            {"name": "joint_%s_lo" % col, "column": col,
             "floor_min_value": lo, "t_window": (_JOINT_B0, _JOINT_B1),
             "provisional_note": _JOINT_PROVISIONAL,
             "label": "settled %s tracks the walk on every sample (>= %d; "
                      "walked %d = 0x1000 | %d, +/- %.0f %% on the 12-bit "
                      "CODE; clamp-absent %d). %s"
                      % (col, lo, want, want & 0x0FFF,
                         100.0 * _FW26_JOINT_MDAC_TOL, refuse, kind)})
        out.append(
            {"name": "joint_%s_hi" % col, "column": col,
             "max_value": hi, "t_window": (_JOINT_B0, _JOINT_B1),
             "provisional_note": _JOINT_PROVISIONAL,
             "label": "settled %s tracks the walk (<= %d; clamp-absent %d)"
                      % (col, hi, refuse)})
    return out


FAULT_EXPECTATIONS["fw26-clamp-joint"] = {
    "source": ("applyShareCurrentCeilings() (.ino:10273-10313) with "
               "SHARE_GOV_I_FC_CEIL_A 1.25 A and SHARE_GOV_CEIL_HYST_A 0.05 A "
               "(.ino:2406/:2430) and the minority clip SHARE_MINORITY_I_MIN_A "
               "0.30 A (.ino:2002), against LIMIT_I_FC_MAX 1.4 A (.ino:1425). "
               "Stimulus derivation at hil_plant_sim.SCENARIOS"
               "['fw26-clamp-joint']; bounds from "
               "tools/probes/probe_fw26_clamp_walk.joint(), including the "
               "clamp-absent arm the discriminating bounds refuse. Design "
               "docs/fw26_current_ceiling_governor.md section 8.6.5."),
    "provisional_note": _JOINT_PROVISIONAL,
    # FAULT-FREE, and OC_FC in particular. This leg exists because the same
    # coincidence latched OC_FC on the sweep at a 2.99 A total; at 1.65 A the
    # clip bounds the peak 0.05 A under the limit. A latch here is not a failed
    # check, it is a falsified bound.
    "allow_only": 0,
    # Past the settled window: a run that latched on the step never reached the
    # half of the scenario that shows the clamp holding.
    "survive_to": {"t": 26.0, "states": {2, 3}},
    "signals_require": [
        # 0. THE CADENCE CENSUS, so nothing below can pass on a stalled stream.
        {"name": "joint_cadence", "min_rows": _JOINT_CADENCE_ROWS,
         "t_window": (_JOINT_A0, _JOINT_B1),
         "provisional_note": _JOINT_PROVISIONAL,
         "label": "the run streamed at full cadence across both phases "
                  "(>= %d rows in a %.1f s window = %.0f %% of the 1 kHz "
                  "nominal)" % (_JOINT_CADENCE_ROWS, _JOINT_B1 - _JOINT_A0,
                                100.0 * _JOINT_CADENCE_COVER)},
        # 1-2. THE STIMULUS WAS DELIVERED, on both axes. 0.83 and 0.41 rather
        #    than 0.84 and 0.40: the value round-trips through a float32 UDP
        #    field.
        {"name": "joint_share_pre", "column": "cmd_share_sp",
         "max_value": 0.41, "t_window": (_JOINT_A0, _JOINT_A1),
         "provisional_note": _JOINT_PROVISIONAL,
         "label": "the pre-step share 0.40 was commanded and held (unclamped "
                  "FC demand 0.48 A at the 1.20 A total, 62 % under the "
                  "ceiling)"},
        {"name": "joint_share_stepped", "column": "cmd_share_sp",
         "min_value": 0.83, "t_window": (_JOINT_B0, _JOINT_B1),
         "provisional_note": _JOINT_PROVISIONAL,
         "label": "the share step to 0.84 landed (unclamped FC demand 1.386 A "
                  "at the stepped 1.65 A total, 0.136 A over the ceiling)"},
        # 3. THE DEMAND STEPPED TOO, which is the other half of the stimulus
        #    and the half no share column can show. I_fc + I_batt is the
        #    two-source total; a run whose aux load did not step is a
        #    `fw26-clamp-cruise` at a different share, not this leg.
        {"name": "joint_total_pre", "column": "I_batt",
         "floor_min_value": 0.62, "t_window": (_JOINT_A0, _JOINT_A1),
         "provisional_note": _JOINT_PROVISIONAL,
         "label": "the pre-step battery current is the 1.20 A total's 0.60 "
                  "share (>= 0.62 A on every sample; walk 0.7200 A) - the "
                  "witness that the load plateau stood before the step"},
        # 4. THE ACCEPTANCE BOUND, and the headline of the whole leg. The peak
        #    delivered fuel-cell current across the joint step. 1.36 A is
        #    0.4 % above the 1.3303 A walk and 2.9 % under LIMIT_I_FC_MAX.
        {"name": "joint_transient_peak", "column": "I_fc",
         "max_value": _JOINT_ACCEPT_PEAK_A,
         "t_window": (_JOINT_STEP_T, _JOINT_STEP_T + _JOINT_STEP_WIN_S),
         "provisional_note": _JOINT_PROVISIONAL,
         "label": "THE ACCEPTANCE BOUND: the joint share-and-demand step at "
                  "t = %.1f s did not drive I_fc above %.2f A in its first "
                  "%.0f ms (walk 1.3303 A; the structural bound is the "
                  "minority clip's (I_tot - 0.30) = 1.35 A, and "
                  "LIMIT_I_FC_MAX is 1.40 A). The same coincidence at a "
                  "2.99 A total delivered 1.4890 A and latched OC_FC on "
                  "`fw26-clamp-sweep` in campaign E"
                  % (_JOINT_STEP_T, _JOINT_ACCEPT_PEAK_A,
                     1e3 * _JOINT_STEP_WIN_S)},
        # 5. ... and it never came back up. The same bound over the whole
        #    post-step span, which a late excursion would fail and check 4
        #    could not see.
        {"name": "joint_peak_held_down", "column": "I_fc",
         "max_value": _JOINT_ACCEPT_PEAK_A,
         "t_window": (_JOINT_STEP_T, _JOINT_B1),
         "provisional_note": _JOINT_PROVISIONAL,
         "label": "I_fc stayed under %.2f A for the whole post-step span, not "
                  "only across the transient" % _JOINT_ACCEPT_PEAK_A},
        # 6. THE CLAMP ENGAGED INSIDE THE TRANSIENT. The walk engages at
        #    +29 ms of the 300 ms window, i.e. 271 ticks; 150 is a floor with
        #    an 81 % margin that a run engaging as late as +150 ms still meets.
        {"name": "joint_clamp_engaged", "aux_bit": "fc_ceiling_active",
         "min_ticks": 150,
         "t_window": (_JOINT_STEP_T, _JOINT_STEP_T + _JOINT_STEP_WIN_S),
         "provisional_note": _JOINT_PROVISIONAL,
         "label": "the FC ceiling BOUND inside the transient window (>= 150 "
                  "of %.0f ticks; walk: first engagement +29 ms, duty 0.9976 "
                  "post-step)" % (1e3 * _JOINT_STEP_WIN_S)},
        # 7. AND SETTLED, measured from the aux bit's own rising edge so the
        #    figure is the clamp's and not the Pi command cadence's.
        {"name": "joint_clamp_settling", "column": "I_fc",
         "min_value": 1.2450, "aux_bit": "fc_ceiling_active",
         "reach_within_ms": 120.0,
         "t_window": (_JOINT_STEP_T, _JOINT_STEP_T + 0.6),
         "provisional_note": _JOINT_PROVISIONAL,
         "label": "I_fc reached the ceiling band within 120 ms of the clamp "
                  "ENGAGING (walk 53 ms). Longer than "
                  "`fw26-clamp-cruise`'s 60 ms on purpose: there the total was "
                  "SETTLED at the step, here the load EMA has 0.45 A to walk "
                  "through first, and that lag IS the hazard"},
        # 8. THE CLAMP HELD through the settled window.
        {"name": "joint_clamp_duty", "aux_bit": "fc_ceiling_active",
         "min_ticks": _JOINT_SETTLED_DUTY_TICKS,
         "t_window": (_JOINT_B0, _JOINT_B1),
         "provisional_note": _JOINT_PROVISIONAL,
         "label": "the FC ceiling was BINDING for >= %d of the settled "
                  "window's %.0f ticks (walk: 1.0000 duty)"
                  % (_JOINT_SETTLED_DUTY_TICKS,
                     1000.0 * (_JOINT_B1 - _JOINT_B0))},
        # 9. THE PRE-STEP NEGATIVE CONTROL, same run and same governor. At
        #    share 0.40 on a 1.20 A total the demand is 0.48 A, 0.77 A under
        #    the ceiling, so the flag must be down for the WHOLE window.
        {"name": "joint_clamp_inert_pre", "aux_bit": "fc_ceiling_active",
         "max_ticks": 0, "t_window": (_JOINT_A0, _JOINT_A1),
         "provisional_note": _JOINT_PROVISIONAL,
         "vacuity_note": ("the aux column cannot be blank across this window: "
                          "`joint_clamp_duty` asserts >= %d ticks with the "
                          "same bit SET later in the same run, which is only "
                          "reachable if the byte streamed and parsed. A zero "
                          "count here is a read of the bit, not an absent "
                          "column." % _JOINT_SETTLED_DUTY_TICKS),
         "label": "the FC ceiling did NOT bind before the step (0 ticks; "
                  "below the ceiling fw v26 is fw v25)"},
        # 10-11. THE SETTLED CURRENT, two-sided - AND THE DISCRIMINATOR. The
        #    clamp-absent walk settles at 1.3500 A, which the upper bound
        #    refuses by 0.05 A. `floor_min_value` on the lower bound because
        #    the claim is that the current was HELD at the ceiling throughout,
        #    which is the in-window MINIMUM (`min_value` tests the maximum and
        #    passes on one tick - the H2 lesson).
        {"name": "joint_fc_at_the_ceiling", "column": "I_fc",
         "floor_min_value": 1.20, "t_window": (_JOINT_B0, _JOINT_B1),
         "provisional_note": _JOINT_PROVISIONAL,
         "label": "I_fc never fell below the ceiling band after the step "
                  "(>= 1.20 A = SHARE_GOV_I_FC_CEIL_A - SHARE_GOV_CEIL_HYST_A, "
                  "on every sample; walk 1.2500 A)"},
        {"name": "joint_fc_under_the_band", "column": "I_fc",
         "max_value": 1.30, "t_window": (_JOINT_B0, _JOINT_B1),
         "provisional_note": _JOINT_PROVISIONAL,
         "label": "and I_fc settled INSIDE the band (<= 1.30 A; walk "
                  "1.2500 A). THE fw v25/v26 DISCRIMINATOR: without the clamp "
                  "the minority clip alone settles this stimulus at 1.3500 A, "
                  "which this bound refuses by 0.05 A"},
        # 12-13. THE BALANCE CLOSED ONTO THE BATTERY. Motor-free with a
        #    constant post-step total, so this is a two-sided bound on I_batt
        #    around 1.65 - 1.25 = 0.40 A. It confirms the amps the ceiling
        #    refused the fuel cell WENT somewhere. The clamp-absent value is
        #    0.3000 A and the lower bound refuses it.
        {"name": "joint_batt_took_the_rest", "column": "I_batt",
         "floor_min_value": 0.34, "t_window": (_JOINT_B0, _JOINT_B1),
         "provisional_note": _JOINT_PROVISIONAL,
         "label": "the battery carried the amps the ceiling refused the fuel "
                  "cell on every sample (>= 0.34 A; walk 0.4000 A, "
                  "clamp-absent 0.3000 A)"},
        {"name": "joint_batt_bounded", "column": "I_batt",
         "max_value": 0.46, "t_window": (_JOINT_B0, _JOINT_B1),
         "provisional_note": _JOINT_PROVISIONAL,
         "label": "and no more than that (<= 0.46 A) - the pair is "
                  "|I_tot - I_fc - I_batt| <= 0.06 A at a 1.65 A total"},
        # 14. THE BATTERY CEILING IS NOT EXERCISED and must not fire: it would
        #    need 2.70 A on one channel against a 1.65 A bus.
        {"name": "joint_bt_ceiling_never", "aux_bit": "bt_ceiling_active",
         "max_ticks": 0, "t_window": (_JOINT_A0, _JOINT_B1),
         "provisional_note": _JOINT_PROVISIONAL,
         "vacuity_note": ("`joint_clamp_duty` asserts >= %d ticks with the FC "
                          "bit SET in the same column, so a zero count here "
                          "reads the BT bit rather than an absent column."
                          % _JOINT_SETTLED_DUTY_TICKS),
         "label": "the BT ceiling never bound (it would need 2.70 A on one "
                  "channel against a 1.65 A bus)"},
        # 15-17. THE CLAMP NEVER OPENED A BUS SWITCH. A reference outside the
        #    droop band IS the channel-cutoff signal, so the band constraint at
        #    the tail of applyShareCurrentCeilings() is structural rather than
        #    arithmetical, and this is what asserts it on the board. The tick
        #    floors are derived from the cadence gate (the M8 rule), and the
        #    edge count closes the cut-then-restore case the floors cannot see.
        {"name": "joint_fc_bus_held", "switch_bit": SW_FC_BUS,
         "min_ticks": _JOINT_BUS_HOLD_TICKS,
         "t_window": (_JOINT_A0, _JOINT_B1),
         "provisional_note": _JOINT_PROVISIONAL,
         "label": "FC_BUS_ENABLE stayed high across both phases (>= %d ticks "
                  "= 98 %% of the rows `joint_cadence` guarantees) - a current "
                  "ceiling must never open a bus switch"
                  % _JOINT_BUS_HOLD_TICKS},
        {"name": "joint_bt_bus_held", "switch_bit": SW_BT_BUS,
         "min_ticks": _JOINT_BUS_HOLD_TICKS,
         "t_window": (_JOINT_A0, _JOINT_B1),
         "provisional_note": _JOINT_PROVISIONAL,
         "label": "BT_BUS_ENABLE stayed high across both phases (>= %d ticks) "
                  "- the split is genuinely two-source, which is what makes "
                  "the clamp reachable at all" % _JOINT_BUS_HOLD_TICKS},
        {"name": "joint_no_switch_ring", "switch_bit": SW_FC_BUS,
         "edge_count_between": (0, 0), "edge": "rise",
         "t_window": (_JOINT_A0, _JOINT_B1),
         "provisional_note": _JOINT_PROVISIONAL,
         "label": "no FC_BUS rising edge in either phase - no cut, and "
                  "therefore no sw_ring"},
    ] + _fw26_joint_mdac_signals(),
}


FAULT_EXPECTATIONS["share-staircase"] = {
    "source": (".ino:9231-9257 (updateShareSetpointCutoff, DROOP_R_MIN 0.15 / "
               "DROOP_R_MAX 0.85, SHARE_CUT_MAX_HANDOFF_A 0.5 A at :9234/:9250) + "
               ":2002 (SHARE_MINORITY_I_MIN_A 0.30 A, the governor rails) + "
               ":2236 (POWER_BAL_PERIOD_US 1000 us) and share_controller_coeffs.h "
               "(SHARE_CTRL_TS_US 1000 us). Load derivations at "
               "hil_plant_sim.STAIRCASE_LOAD_A / _B."),
    # Fault-free.  Worst per-channel current is Phase A at the 0.75 rail:
    # 0.75*1.20 = 0.90 A vs LIMIT_I_FC_MAX 1.4 A (36 % margin).  In Phase B the
    # surviving channel carries the whole 0.55 A, well under either limit.
    "allow_only": 0,
    # Past the load drop and into Phase B's first excursion: a run that latched
    # during the staircase never reached the cut half at all.
    "survive_to": {"t": 32.0, "states": {2, 3}},
    "signals_require": [
        # ── PHASE A: the governor rails ──────────────────────────────────────
        # 1. The staircase's TOP step was commanded.  0.79 rather than 0.80: the
        #    value round-trips through a float32 UDP field.
        {"name": "staircase_top", "column": "cmd_share_sp", "min_value": 0.79,
         "t_window": (6.0, 9.0),
         "label": "the staircase commanded its 0.80 top step (outside the "
                  "governor's 0.75 rail at I_tot ~ 1.2 A)"},
        # 2. ... and SWEPT the whole range down to 0.20.  0.80 - 0.20 = 0.60
        #    commanded; 0.55 is a floor clear of the float32 round trip and of
        #    the 20 ms staircase, and unreachable by a partial sweep.
        #    ⚠️ THE WINDOW OPENS AT 6.5, NOT AT 6.0.  `strictly_decreases_by`
        #    compares the LAST in-window sample against the FIRST, and the 0.80
        #    step is commanded at t = 6.0, so the opening edge decides which
        #    level the fall is measured FROM.  Opening at 6.5 (the 0.80 step
        #    holds until t = 9.0) makes the first sample 0.80 with a 0.5 s
        #    margin and the fall 0.60, 9 % over the floor.
        #    ⚠️ CORRECTED MECHANISM (2026-08-31, ledger "contract/doc").  The
        #    original note here justified the offset with a probability: it
        #    claimed the `cmd_*` columns are the ZOH of the last command SENT,
        #    so the row at t = 6.000 would still carry 0.50 on ~19 runs in 20 —
        #    "a chronic FAIL of a correct board".  THAT MECHANISM IS WRONG, and
        #    the chronic-FAIL claim with it: the columns step at the NOMINAL
        #    timeline instant (see PI_CMD_PERIOD_S above — the timeline walk
        #    runs before the 50 Hz send gate), so a window opening at 6.0 would
        #    sample 0.80 within one 1 ms tick and measure the full 0.60 fall.
        #    The 6.5 opening is KEPT: half a second of margin against tick
        #    phase, float rounding on the wall-clock `t` axis, and any future
        #    change to when the walk runs, at zero cost to what is asserted.
        #    The general rule is still enforced at import below.
        {"name": "staircase_swept", "column": "cmd_share_sp",
         "strictly_decreases_by": 0.55, "t_window": (6.5, 26.9),
         "label": "the staircase swept 0.80 -> 0.20, crossing BOTH governor rails"},
        # 3. THE BOARD ACTED at the top step.  At the 0.75 rail on a 1.20 A total
        #    the FC channel carries 0.90 A; a run that ignored the command and
        #    held 0.50 would show 0.60 A.  0.80 sits between them, 11 % under the
        #    railed value and 33 % over the ignored one.
        #    ⚠️ MODEL current (I_AUX_A + STAIRCASE_LOAD_A through the droop bus),
        #    not a measurement.  A campaign that misses it should move
        #    STAIRCASE_LOAD_A, never this floor.
        #    L3 (review 2026-08-31) — WHAT A PASS ACTUALLY PROVES. The
        #    plant splits the bus current in proportion to the MDAC CODE
        #    RATIO (HIL_PLANT.md §4.7: sign- and monotonicity-preserving,
        #    WRONG GAIN), so this floor asserts the firmware->MDAC
        #    arithmetic — that the board read the command, moved the codes
        #    the right way, and moved them far enough. It is NOT share-loop
        #    GAIN validation: the amps here are the model's response to the
        #    codes, not the board's real droop chain (see also the
        #    K_DROOP_BUS design-vs-measured x4 finding).
        {"name": "fc_high_step", "column": "I_fc", "min_value": 0.80,
         "t_window": (7.0, 9.0),
         "label": "the board's share loop railed FC to the governor's upper clip "
                  "(>= 0.80 A of a ~1.20 A total)"},
        # 4. ... and REDISTRIBUTED as the staircase came down.  At the 0.25 rail
        #    FC carries 0.30 A, so the fall from 0.90 is ~0.60 A; 0.50 is a floor
        #    under that with margin for the governor's own filtering.
        {"name": "fc_redistributed", "column": "I_fc",
         "strictly_decreases_by": 0.50, "t_window": (7.0, 26.9),
         "label": "FC current fell by >= 0.50 A across the staircase — the loop "
                  "tracked the sweep rather than holding one split"},
        # ── PHASE B: the cut, the RESTORE, and both latencies ────────────────
        # 5-6. BT_BUS cut at the high excursion, and back.  The cut window is
        #      inset from the 3 s excursion; max_ticks 100 (0.1 s) admits the
        #      samples around the transition without admitting a run where the
        #      cut never happened.  The restore window is 2.5 s -> min_ticks 1500
        #      (60 % of it), so a late release still passes but an absent one
        #      cannot.
        #      ⚠️ 60 % IS THE STANDARD FOR EVERY RESTORE FLOOR IN THIS SUITE,
        #      and it is a MARGIN rule, not a tuning knob: the observation
        #      stream drops ~1 frame per run, so a floor at 100 % of its window
        #      fails a correct board on a dropped frame.  BT's 1500/2500 already
        #      followed it; FC's did not until 2026-08-31 (see its comment
        #      below).  `ems-y-b00-*`'s two restore floors sit at 67 % and 50 %
        #      of their windows and were checked at the same time — both already
        #      clear of the rule, both left alone.
        {"name": "bt_bus_cut", "switch_bit": SW_BT_BUS, "max_ticks": 100,
         "t_window": (_SS_BT_CUT_T + 0.5, _SS_BT_RESTORE_T - 0.2),
         "label": "BT_BUS_ENABLE cut by the setpoint latch at share 0.95 "
                  "(> DROOP_R_MAX)"},
        {"name": "bt_bus_restored", "switch_bit": SW_BT_BUS, "min_ticks": 1500,
         "t_window": (_SS_BT_RESTORE_T + 0.5, _SS_FC_CUT_T),
         "label": "BT_BUS_ENABLE RESTORED once the setpoint returned to 0.50"},
        # 7-8. FC_BUS, the mirror image at the low excursion.
        {"name": "fc_bus_cut", "switch_bit": SW_FC_BUS, "max_ticks": 100,
         "t_window": (_SS_FC_CUT_T + 0.5, _SS_FC_RESTORE_T - 0.2),
         "label": "FC_BUS_ENABLE cut by the setpoint latch at share 0.05 "
                  "(< DROOP_R_MIN)"},
        # ⚠️ 1500 -> 900 (2026-08-31, ledger "knife-edge threshold").  This
        # window is (_SS_FC_RESTORE_T + 0.5, 44.0) = (42.5, 44.0) = 1.5 s, i.e.
        # 1500 rows at the CSV's 1 kHz rate, and the floor was ALSO 1500 —
        # 100 % of the window, not the 60 % its sibling `bt_bus_restored`
        # documents and uses (1500 of a 2.5 s / 2500-row window).  Campaign
        # 20260831_191509 measured exactly 1500/1500 here, which is a PASS with
        # ZERO margin: one dropped observation frame in-window fails a correct
        # board, and each run drops ~1 frame.  900 is 60 % of 1500, restoring
        # the sibling's stated intent — still far above anything an absent
        # restore could produce (0 ticks) or a very late one (a release at
        # t = 43.5 leaves 500).
        {"name": "fc_bus_restored", "switch_bit": SW_FC_BUS, "min_ticks": 900,
         "t_window": (_SS_FC_RESTORE_T + 0.5, 44.0),
         "label": "FC_BUS_ENABLE RESTORED once the setpoint returned to 0.50"},
        # 9-12. THE FOUR LATENCIES.  The `edge` field carries the RISE variant:
        #      the original spec measured falls only and would have left the two
        #      restores asserted by tick count alone, which cannot distinguish a
        #      2 ms release from a 900 ms one.  Adding "rise" to the same kind was
        #      cheaper than a second kind and keeps one implementation for both
        #      directions.  All four windows open 1 s before their stimulus so the
        #      pre-edge level is known.
        {"name": "bt_cut_latency", "switch_bit": SW_BT_BUS, "edge": "fall",
         "after_t": _SS_BT_CUT_T, "max_ms": _SS_LATENCY_MAX_MS,
         "t_window": (_SS_BT_CUT_T - 1.0, _SS_BT_RESTORE_T - 0.2),
         "label": "BT_BUS cut latency from the 0.95 command"},
        {"name": "bt_restore_latency", "switch_bit": SW_BT_BUS, "edge": "rise",
         "after_t": _SS_BT_RESTORE_T, "max_ms": _SS_LATENCY_MAX_MS,
         "t_window": (_SS_BT_RESTORE_T - 1.0, _SS_FC_CUT_T),
         "label": "BT_BUS restore latency from the 0.50 command"},
        {"name": "fc_cut_latency", "switch_bit": SW_FC_BUS, "edge": "fall",
         "after_t": _SS_FC_CUT_T, "max_ms": _SS_LATENCY_MAX_MS,
         "t_window": (_SS_FC_CUT_T - 1.0, _SS_FC_RESTORE_T - 0.2),
         "label": "FC_BUS cut latency from the 0.05 command"},
        {"name": "fc_restore_latency", "switch_bit": SW_FC_BUS, "edge": "rise",
         "after_t": _SS_FC_RESTORE_T, "max_ms": _SS_LATENCY_MAX_MS,
         "t_window": (_SS_FC_RESTORE_T - 1.0, 44.0),
         "label": "FC_BUS restore latency from the 0.50 command"},
    ],
}

def assert_derived_source_shape(scenario, tag, spec):
    """Import-time shape guard for the `sum_of` / `ratio_of` value sources.

    A FUNCTION rather than inline in the guard loop below, unlike its
    neighbours, because every malformed spelling it refuses fails SILENTLY at
    score time and the negative cases therefore need direct test coverage:
      * `sum_of` AND `ratio_of` — two value sources, one slot;
      * a `column` beside either — the derived source wins in scan_signals(),
        so the column reads as an assertion and is ignored;
      * a one-column `ratio_of` — identically 1.0, a tautology dressed as a
        share assertion (and an empty list is a divide by zero);
      * no value bound at all — a measurement with nothing asserted;
      * `ratio_min_den` on a spec with no `ratio_of` to read it.
    Raises AssertionError, naming the scenario and the spec."""
    where = "FAULT_EXPECTATIONS[%r].signals_require[%r]" % (scenario, tag)
    if "sum_of" in spec or "ratio_of" in spec:
        assert not ("sum_of" in spec and "ratio_of" in spec), (
            "%s carries both `sum_of` and `ratio_of`; they are alternative "
            "value sources." % where)
        assert "column" not in spec, (
            "%s carries a `column` beside a derived value source. The derived "
            "one wins in the scanner, so the `column` would read as an "
            "assertion and be ignored." % where)
        cols = spec.get("sum_of") or spec.get("ratio_of")
        assert isinstance(cols, (list, tuple)) and len(cols) >= 2, (
            "%s: a derived value source needs at least two columns; got %r. A "
            "one-column ratio is identically 1.0." % (where, cols))
        assert any(k in spec for k in ("min_value", "max_value",
                                       "strictly_decreases_by",
                                       "column_range_at_least",
                                       "floor_min_value")), (
            "%s: a derived value source needs a value bound to assert." % where)
    assert not ("ratio_min_den" in spec and "ratio_of" not in spec), (
        "%s: `ratio_min_den` is read only by `ratio_of`." % where)


# Everything not listed is expected fault-free (post-grace); a fault there is a
# finding: steady, step-load, ems-drive-cycle, drive.
#
# `bringup` LEFT that group on 2026-08-30 (L2): it is listed above with no
# `require` and an explicit `allow_only = FAULT_ERROR`, i.e. the same "expected
# clean" expectation the unlisted scenarios get, PLUS a `survive_to` positive
# assertion that the bring-up actually completed. The three still unlisted have no
# comparable completion event to assert — steady has no stimulus at all, step-load's
# is a plant-side load step with no state consequence, and `drive` is whatever the
# operator does by hand — so giving them entries would buy nothing and would cost
# them the --pi-live PI_TIMEOUT excusal that only the `else` branch offers. They
# stay unlisted deliberately.

# L3 — LOAD-TIME CONSISTENCY, asserted rather than trusted.
# Both `not_before_s` and `survive_to.t` are compared against times taken from the
# POST-GRACE window, so a value at or below WARM_RESET_GRACE_S is not a stricter
# check — it is a VACUOUS one. `not_before_s` would be trivially satisfied (nothing
# post-grace can precede the grace bound) and `survive_to` would probe a moment the
# fault scan never reaches, silently reporting "no observation frame at or after
# t=X". Neither failure has a symptom at the point of use, so it is caught here, at
# import, where the table is written.
#
# The 2026-08-30 duration trim added the OTHER side of the same sandwich: a bound
# taken from the post-grace window is equally useless if it sits at or beyond the
# END of the run.  `not_before_s` past the duration can never be crossed;
# `survive_to.t` past it probes a moment no row exists for, reporting "no
# observation frame at or after t=X" — which reads as a board failure rather than
# as a scenario mis-specification; a `signals_require` t_window whose UPPER bound
# is past it silently shrinks (the window is clipped by where the CSV ends, so a
# spec asking for evidence in (8, 40) on a 24 s run is judged on (8, 24) with no
# symptom anywhere); and a disjunctive arm's `after_t` past it can never latch.
# Trimming a scenario's duration below its own timing bounds is exactly the
# mistake this half catches, at import, for free — EVERY time-valued field in the
# table is covered, so a new field is the only way to reintroduce the gap.
# NOTE the one deliberate divergence: soc-depletion's SCENARIOS duration_s (120 s)
# is the STANDALONE default; the suite overrides it to 400 s in build_plan().  The
# assert uses the smaller of the two, so it is conservative either way.
def _expectation_time_bounds(entry):
    """(label, t) for every time-valued field in one FAULT_EXPECTATIONS entry.

    A `t_window` upper bound of None means "to the end of the run" and is
    deliberately NOT yielded — it cannot be past the duration by construction."""
    yield "not_before_s", entry.get("not_before_s")
    yield "survive_to.t", (entry.get("survive_to") or {}).get("t")
    for _i, _spec in enumerate(entry.get("signals_require") or ()):
        _tag = _spec.get("name") or _spec.get("label") or "signal[%d]" % _i
        for _leaf, _sub in ([(_tag, _spec)] +
                            [("%s.any_of[%d]" % (_tag, _j), _a)
                             for _j, _a in enumerate(_spec.get("any_of") or ())]):
            _w = _sub.get("t_window")
            if _w and _w[1] is not None:
                yield "signals_require[%s].t_window[1]" % _leaf, _w[1]
            if _sub.get("after_t") is not None:
                yield "signals_require[%s].after_t" % _leaf, _sub["after_t"]


# -----------------------------------------------------------------------------
# NAMED AUX-BYTE MASKS (fw v26).
#
# `aux_bit` has always taken a numeric mask. The fw v26 clamp bits are the first
# aux bits an expectation is likely to want to name in prose as well as to test,
# and a bare 0x10 in a check is unreadable and unsearchable, so a STRING is
# accepted as well and resolved here.
#
# THE MASK VALUES ARE NOT DECLARED HERE. They are the AUX_* constants imported
# from `hil_plant_sim`, which mirror the firmware's own packing of the aux byte.
# Only the LABELS are written out, and they are the same strings
# `hil_report_analysis.aux_bits()` draws its figure bit-lanes from, so a check
# and a figure lane cannot disagree about which bit is which. They are not
# imported from there because that module requires numpy and this one must stay
# importable under the stdlib-only interpreter; `test_run_hil_suite.py` asserts
# the two maps agree, which is what keeps the duplication honest.
#
# An unknown name raises at resolution rather than silently masking with 0 - a
# zero mask reads as "the bit was never set", which is a PASS on a
# `max_ticks: 0` spec and therefore the worst possible failure mode.
#
# WARNING - DECLARED ABOVE THE SPEC-VALIDATION LOOP (M6, 2026-09-02). It used to
# sit beside `scan_signals()`, so the only thing that checked a name was the
# per-row scan, mid-campaign, on the runs that reach the spec. A typo in an
# `aux_bit` name therefore survived import and every dry run, and surfaced as a
# KeyError partway through a scenario. The validation loop below now resolves
# every `aux_bit` name at IMPORT, which is where every other malformed spec in
# this table fails.
_AUX_BIT_NAMES = {
    "fc_ceiling_active": AUX_FC_CEILING,
    "bt_ceiling_active": AUX_BT_CEILING,
}


def _resolve_bit_mask(spec):
    """The numeric mask a `switch_bit` / `aux_bit` spec names."""
    if "switch_bit" in spec:
        return int(spec["switch_bit"])
    v = spec.get("aux_bit", 0)
    if isinstance(v, str):
        try:
            return int(_AUX_BIT_NAMES[v])
        except KeyError:
            raise KeyError(
                "unknown aux_bit name %r (known: %s). The names are "
                "hil_report_analysis.aux_bits()' labels; an unknown one must "
                "raise, because a zero mask would read as 'the bit was never "
                "set' and PASS a max_ticks: 0 check."
                % (v, ", ".join(sorted(_AUX_BIT_NAMES))))
    return int(v)


# events_any_of shape, asserted at import for the same reason every other bound
# here is: a malformed branch would silently never match and the group would fail
# as "NO outcome matched", which reads as a board finding rather than as a table
# defect.  A one-branch group is refused outright — a group with nothing to choose
# between is an events_require spelled the long way, and using any_of for it would
# hide a single expectation behind a mechanism that exists to name alternatives.
for _n, _e in FAULT_EXPECTATIONS.items():
    for _g in _e.get("events_any_of", ()):
        _brs = _g.get("branches") or []
        assert _g.get("name"), (
            "FAULT_EXPECTATIONS[%r]: an events_any_of group needs a `name` — it "
            "becomes the check name." % _n)
        assert len(_brs) >= 2, (
            "FAULT_EXPECTATIONS[%r].events_any_of[%r] has %d branch(es). Use "
            "events_require for a single expectation; any_of exists to enumerate "
            "ALTERNATIVE legal outcomes and must name at least two."
            % (_n, _g.get("name"), len(_brs)))
        for _b in _brs:
            assert _b.get("name") and _b.get("events"), (
                "FAULT_EXPECTATIONS[%r].events_any_of[%r]: every branch needs a "
                "`name` (it is reported as the winning outcome) and a non-empty "
                "`events` list." % (_n, _g.get("name")))
            for _s in _b["events"]:
                assert (isinstance(_s, str) or "kind" in _s
                        or "total_of" in _s or "max_of" in _s), (
                    "FAULT_EXPECTATIONS[%r].events_any_of[%r].%s: every event "
                    "spec needs a `kind`, `total_of` or `max_of`."
                    % (_n, _g.get("name"), _b["name"]))

# ── DUPLICATE-KEY TRIPWIRE (fix round, 2026-09-01) ──────────────────────────
# A repeated key in the FAULT_EXPECTATIONS literal is resolved by Python before
# any assertion here could see it, so this cannot detect the duplicate itself.
# It detects the DAMAGE the one that occurred left behind: a `regen-harvest-true`
# entry that carries `charge-regen`'s signals, or vice versa. Each entry's
# signal names must belong to its own scenario, which is cheap to state and is
# exactly what a mis-anchored splice breaks.
for _n, _names in (("regen-harvest-true",
                    {"regen_switch", "regen_harvest", "regen_node_lift",
                     "regen_clamp_dwell"}),
                   ("charge-regen", {"regen_switch", "charge_current"})):
    _got = {_s["name"] for _s in FAULT_EXPECTATIONS[_n].get("signals_require", ())
            if "name" in _s}
    assert _got == _names, (
        "FAULT_EXPECTATIONS[%r].signals_require carries %s, expected %s. A "
        "scenario wearing another scenario's checks is the signature of a "
        "mis-anchored edit or a duplicated dict key -- see the structural-repair "
        "note above the two entries." % (_n, sorted(_got), sorted(_names)))
del _n, _names, _got

# `total_of` / `max_of` shape (M3 2026-09-01; `max_of` added by PART B2 of the
# C1 round, 2026-09-01): each needs a `field` to aggregate and at least one of
# `min_value`/`max_value` to compare it against, or the spec aggregates nothing
# meaningful and always passes -- the same failure-shape the other guards in
# this section exist to catch at import instead of mid-campaign.
# A FUNCTION rather than an inline loop (2026-09-03, review finding M3), for the
# reason `_assert_signal_spec_shapes()` already carries: a guard is the only
# thing between a malformed spec and a campaign that measures nothing, so it
# needs coverage of its own, and a test that re-implements it would drift.
def _assert_event_spec_shapes(_n, _e):
    """Assert the shape of every events_require aggregator in ONE entry.

    Raises AssertionError naming the entry and the aggregator. Pure: reads the
    entry and SCENARIOS, writes nothing."""
    for _s in _e.get("events_require", ()):
        if not isinstance(_s, dict):
            continue
        for _agg_key in ("total_of", "max_of"):
            if _agg_key not in _s:
                continue
            assert "kind" not in _s, (
                "FAULT_EXPECTATIONS[%r]: an events_require spec must not mix "
                "`kind` and `%s` -- they are two different judging paths."
                % (_n, _agg_key))
            assert not ("total_of" in _s and "max_of" in _s), (
                "FAULT_EXPECTATIONS[%r]: an events_require spec must not carry "
                "both `total_of` and `max_of` -- they are two aggregators and "
                "only one verdict is rendered." % _n)
            assert _s.get("field"), (
                "FAULT_EXPECTATIONS[%r]: a `%s` spec needs a `field` to "
                "aggregate." % (_n, _agg_key))
            assert _s.get("min_value") is not None or _s.get("max_value") is not None, (
                "FAULT_EXPECTATIONS[%r]: a `%s` spec with neither "
                "`min_value` nor `max_value` compares nothing and always "
                "passes." % (_n, _agg_key))
            # ── (d) AN AGGREGATOR NEEDS THE ENGINE THAT EMITS THE EVENTS ─────
            # (review finding M3, 2026-09-03.)  The plant's event stream is a
            # HI-FI product: the simple engine emits none.  `_judge_event_spec`
            # aggregates an empty stream to 0.0 rather than to "not measured",
            # so a `min_value` floor on a scenario running the simple engine
            # fails a correct board on a run that measured nothing at all —
            # which is what four `ems-ftp75c-*` legs did for a whole campaign
            # while declaring `electrical: "any"`.  A `max_value` ceiling is no
            # better: it PASSES vacuously on the same empty stream.  The
            # scenario must therefore pin the engine.
            assert (SCENARIOS.get(_n) or {}).get("electrical") == "hifi", (
                "FAULT_EXPECTATIONS[%r] carries a `%s` events aggregator but "
                "SCENARIOS[%r]['electrical'] is %r, not 'hifi'. Plant events "
                "are emitted by the hi-fi engine ONLY; under the simple engine "
                "the stream is empty, an aggregate reads 0.0, and the bound "
                "then judges a quantity the run never measured. Declare "
                "`electrical: \"hifi\"` on the scenario, or move the claim to "
                "a signals check that reads a column."
                % (_n, _agg_key, _n, (SCENARIOS.get(_n) or {}).get("electrical")))


for _n, _e in FAULT_EXPECTATIONS.items():
    _assert_event_spec_shapes(_n, _e)
del _n, _e

# Shape of the 2026-08-31 signal kinds, asserted at import for the same reason
# every bound here is: each of them fails SILENTLY when malformed.  A `value_mask`
# with no `value_equals` would raise KeyError deep in the scanner mid-campaign; a
# `switch_fall_latency_ms` whose window opens at or after its own `after_t` has no
# pre-edge level to compare against, so it can only ever report "no transition" —
# which reads as a board finding rather than as a table defect.
#
def _is_tick_counting_spec(spec):
    """True when a spec's verdict is a TICK COUNT (min_ticks / max_ticks /
    max_continuous_ticks), i.e. when scan_signals() must maintain a counter for
    it.  One definition, read by the scanner, the judge and the import guard."""
    return any(k in spec for k in
               ("min_ticks", "max_ticks", "max_continuous_ticks"))


def _threshold_of(spec):
    """('min_value'|'max_value', bound) for a NUMERIC-THRESHOLD tick spec, else
    None.

    A numeric spec that counts ticks needs a predicate saying which samples
    count, and the only one it can carry is its own value bound.  The bound is
    NOT judged separately in that case — _judge_signal_leaf() returns on the
    tick bound first, deliberately: "V_rgn held at or above 17.9 V for at least
    800 ticks" is ONE claim, and reporting it as two verdicts would let the
    weaker one carry the check."""
    if not _is_tick_counting_spec(spec):
        return None
    if any(k in spec for k in ("switch_bit", "aux_bit", "value_mask")):
        return None                     # a bit/mask predicate already exists
    for key in ("min_value", "max_value"):
        if key in spec:
            return key, float(spec[key])
    return None


# A FUNCTION rather than an inline loop (2026-09-01) so a test can drive the
# guard over ONE synthetic spec.  The guards are the only thing standing between
# a malformed spec and a campaign that measures nothing, so they need coverage of
# their own — and duplicating them in the test file would let the two drift.
def _assert_signal_spec_shapes(_n, _e):
    """Assert the shape of every signals_require spec in ONE expectation entry.

    Raises AssertionError with a message naming the entry and the spec.  Pure:
    reads the entry, SCENARIOS, and module constants, and writes nothing."""
    for _i, _spec in enumerate(_e.get("signals_require") or ()):
        # ── 2026-09-03: THE THREE GUARDS THAT WOULD HAVE CAUGHT `signal_the` ──
        # An `events_require` aggregator was written into a `signals_require`
        # list on five `ems-ftp75c-*` entries and shipped a whole campaign,
        # failing every one of them on a check that could not pass on any board.
        # Nothing refused it: the aggregator shape guard iterates
        # `events_require` only, and the scanner's silence on a spec with no
        # observable is indistinguishable from "the observable was never seen".
        #
        # (a) AN AGGREGATOR IS NEVER A SIGNAL. `total_of`/`max_of` are judged by
        #     the events path, which iterates `events_require`; in this list they
        #     are inert keys beside a value bound with no measurement behind it.
        for _agg in ("total_of", "max_of"):
            assert _agg not in _spec, (
                "FAULT_EXPECTATIONS[%r].signals_require[%d]: `%s` is an EVENTS "
                "aggregator and is judged only from `events_require`. In a "
                "signals list it measures nothing and the spec fails on every "
                "run (campaign 20260902_220604, `signal_the`). Move the spec "
                "into this entry's `events_require`." % (_n, _i, _agg))
        # (b) EVERY signals_require SPEC MUST NAME AN OBSERVABLE. `scan_signals()`
        #     reads a numeric `column` (or a `sum_of`/`ratio_of` derived from
        #     columns), a `switch_bit`/`aux_bit` of the bit words, the cadence
        #     census (`min_rows`), or the fault word (`fault_latch_bit`). A spec
        #     declaring none of those is measured against nothing.
        assert (any(_k in _spec for _k in
                    ("column", "switch_bit", "aux_bit", "min_rows",
                     "fault_latch_bit", "sum_of", "ratio_of"))
                or _spec.get("any_of")), (
            "FAULT_EXPECTATIONS[%r].signals_require[%d] (%r) declares no "
            "observable. scan_signals() measures a `column` (or a `sum_of`/"
            "`ratio_of` derived from columns), a `switch_bit`/`aux_bit`, "
            "`min_rows`, or a `fault_latch_bit`; a spec carrying none of those "
            "is scanned against nothing and its value bound then fails an "
            "UNMEASURED quantity on every run. If the spec aggregates plant "
            "EVENTS (`total_of`/`max_of`), it belongs in `events_require`."
            % (_n, _i, _spec.get("name") or _spec.get("label", "")[:40]))
        # (c) A SIGNAL SPEC IS NAMED BY ITS AUTHOR, never by its prose.
        #     judge_signals() falls back to the label's first word, which is how
        #     five identical checks came to be reported as `signal_the` — a name
        #     that names nothing, is not greppable, and collides across entries.
        assert _spec.get("name"), (
            "FAULT_EXPECTATIONS[%r].signals_require[%d]: every signals_require "
            "spec needs an explicit `name`; the check is reported under it and "
            "a label-derived name is neither greppable nor unique."
            % (_n, _i))
        for _sub in [_spec] + list(_spec.get("any_of") or ()):
            _tag = _sub.get("name") or _spec.get("name") or "signal[%d]" % _i
            if "value_mask" in _sub:
                assert "value_equals" in _sub and _sub.get("column"), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: a `value_mask` "
                    "spec needs both a `column` and a `value_equals`." % (_n, _tag))
                assert ("min_ticks" in _sub) or ("max_ticks" in _sub), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: a `value_mask` "
                    "spec counts MATCHING TICKS, so it needs a min_ticks or a "
                    "max_ticks bound." % (_n, _tag))
            # ── H2 (review 2026-08-31): `strictly_decreases_by` window phase ──
            # The kind compares the LAST in-window sample against the FIRST, so
            # its window's OPENING EDGE is load-bearing in a way a min_value
            # window's is not.  Require the opening edge to clear every entry
            # time of THAT scenario's timeline by at least one command period.
            # A spec with no t_window is exempt (it scans the whole run, so
            # there is no opening edge to mis-phase), and so is a scenario with
            # no pi_timeline (EMS-driven scenarios command from a policy, not a
            # stepped table).
            #
            # ⚠️ CORRECTED RATIONALE (2026-08-31, ledger "contract/doc"), and
            # the rule is KEPT rather than dropped.  This guard was originally
            # justified by the claim that the `cmd_*` columns are the ZOH of the
            # last command SENT, so a window opening AT an entry time would
            # sample the PREVIOUS value "with probability ~19/20".  That is not
            # how the columns work — they step at the NOMINAL entry instant (see
            # PI_CMD_PERIOD_S at the top of this file), so the real exposure is
            # ONE 1 kHz TICK of walk/write phase plus float rounding on the
            # wall-clock `t` axis, not a whole command period.  The rule stays
            # because the margin it buys is free, because it also protects the
            # OBSERVED-side columns (whose response genuinely does lag the
            # nominal instant by the command phase plus the observation round
            # trip), and because a table entry authored ON a step edge is
            # fragile regardless of which mechanism is doing the biting.  The
            # assertion message below is worded accordingly.
            if "strictly_decreases_by" in _sub:
                _w = _sub.get("t_window")
                _tl = (SCENARIOS.get(_n) or {}).get("pi_timeline") or ()
                if _w:
                    for _et, _ in _tl:
                        assert abs(float(_w[0]) - float(_et)) >= PI_CMD_PERIOD_S, (
                            "FAULT_EXPECTATIONS[%r].signals_require[%r]: a "
                            "`strictly_decreases_by` t_window opening at %r is "
                            "within one command period (%.3f s at "
                            "PI_CMD_HZ = %.0f) of the pi_timeline entry at %r. "
                            "The first in-window sample is then decided by "
                            "tick phase against the step edge, so the measured "
                            "fall can be short by a whole step. Open the "
                            "window clear of the entry (inside the step's own "
                            "hold)."
                            % (_n, _tag, _w[0], PI_CMD_PERIOD_S,
                               PiCommander.PI_CMD_HZ, _et))
            # ── 2026-08-31: min_value + max_value in ONE spec is a SILENT DROP ─
            # _judge_signal_leaf() dispatches through a chain of
            # `if ... return`, and `min_value` is tested BEFORE `max_value`, so a
            # spec carrying both keys evaluates the FLOOR ONLY and the ceiling
            # never runs — a bound that reads as asserted and is not. Found while
            # banding the FTP-75 h2_cum_g checks (which are written as two specs
            # for exactly this reason). Refuse the shape rather than reorder the
            # dispatcher: two specs also give the report two named verdicts
            # instead of one, which is what a reader of a band wants.
            # ── 2026-09-01: the two MINIMUM-side kinds (F1/F2) ───────────────
            # Same silent-drop hazard as the min/max pair above: the dispatcher
            # is a chain of `if ... return`, and BOTH new kinds are tested
            # BEFORE min_value/max_value, so pairing either with a peak bound
            # would silently discard the peak bound.  Refuse the shape.
            for _mk in ("column_range_at_least", "floor_min_value"):
                if _mk in _sub:
                    assert _sub.get("column") or "sum_of" in _sub or "ratio_of" in _sub, (
                        "FAULT_EXPECTATIONS[%r].signals_require[%r]: `%s` reads "
                        "a numeric column, so it needs a `column` or a derived "
                        "value source." % (_n, _tag, _mk))
                    assert not any(k in _sub for k in
                                   ("min_value", "max_value", "min_ticks",
                                    "max_ticks", "strictly_decreases_by")), (
                        "FAULT_EXPECTATIONS[%r].signals_require[%r] pairs `%s` "
                        "with another assertion kind. _judge_signal_leaf() "
                        "returns on the first bound it matches and tests `%s` "
                        "first, so the other bound would be silently ignored. "
                        "Split them into two specs." % (_n, _tag, _mk, _mk))
            assert not ("column_range_at_least" in _sub
                        and "floor_min_value" in _sub), (
                "FAULT_EXPECTATIONS[%r].signals_require[%r] carries both "
                "minimum-side kinds; they are alternatives, not a pair."
                % (_n, _tag))
            assert not ("min_value" in _sub and "max_value" in _sub), (
                "FAULT_EXPECTATIONS[%r].signals_require[%r] carries BOTH "
                "`min_value` and `max_value`. _judge_signal_leaf() returns on "
                "the first bound it matches and tests min_value first, so the "
                "ceiling would be silently ignored. Split the band into two "
                "specs (a floor and a ceiling) on the same column." % (_n, _tag))
            # ── L4: a max_ticks-only bit/value spec is vacuity-prone ──────────
            # "the signal was LOW/absent for at most N ticks" is satisfied by a
            # column that is BLANK or missing entirely (zero matching ticks), so
            # such a spec can pass a run in which the observable was never
            # recorded at all.  Require either a COMPANION spec in the same entry
            # placing a positive bound on the SAME signal (which cannot pass on a
            # blank column), or an explicit `vacuity_note` stating why the column
            # cannot be blank here.  Cheapest sound form: companions are matched
            # on the watched signal's identity, not on their semantics.
            # ── 2026-09-01 kinds: max_continuous_ticks / edge_count_between ───
            # Same rule as every other bound here: a malformed spec must fail at
            # IMPORT, not silently measure nothing mid-campaign.
            if "max_continuous_ticks" in _sub:
                assert not ({"min_ticks", "max_ticks", "max_ms",
                             "edge_count_between"} & set(_sub)), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: "
                    "`max_continuous_ticks` is its own assertion kind and "
                    "_judge_signal_leaf() returns on it BEFORE the tick and "
                    "latency bounds, so anything written beside it is silently "
                    "dropped. Split it into two specs." % (_n, _tag))
                assert ("switch_bit" in _sub) or ("aux_bit" in _sub) \
                    or ("value_mask" in _sub) or (_threshold_of(_sub) is not None), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: "
                    "`max_continuous_ticks` counts a run of SET/MATCHING/"
                    "IN-THRESHOLD ticks, so it needs a `switch_bit`, an "
                    "`aux_bit`, a `value_mask`, or a numeric `column` with a "
                    "`min_value`/`max_value` threshold to watch." % (_n, _tag))
                assert int(_sub["max_continuous_ticks"]) >= 0, (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: a negative "
                    "`max_continuous_ticks` can never be satisfied." % (_n, _tag))
            # ── B-M2 (2026-09-01): `min_rows`, the cadence census ────────────
            # Same silent-drop rule as every other kind: _judge_signal_leaf()
            # tests it BEFORE the tick and value bounds, so anything paired with
            # it would be dropped.  It reads no column by design.
            # -- M6: an `aux_bit` NAME is resolved at IMPORT ------------
            # `_resolve_bit_mask()` raises on an unknown name, but it only ran
            # inside the per-row scan, so a typo survived import and every dry
            # run and surfaced mid-campaign. Resolving here makes a bad name a
            # table defect at load time, like every other malformed spec.
            if isinstance(_sub.get("aux_bit"), str):
                try:
                    _resolve_bit_mask(_sub)
                except KeyError as _exc:
                    raise AssertionError(
                        "FAULT_EXPECTATIONS[%r].signals_require[%r]: %s"
                        % (_n, _tag, _exc.args[0]))
            if "min_rows" in _sub:
                assert not ({"min_ticks", "max_ticks", "max_ms",
                             "max_continuous_ticks", "edge_count_between",
                             "min_value", "max_value", "floor_min_value",
                             "column_range_at_least",
                             "strictly_decreases_by"} & set(_sub)), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: `min_rows` is "
                    "its own assertion kind and _judge_signal_leaf() returns on "
                    "it before every value and tick bound, so anything written "
                    "beside it is silently dropped. Split it into two specs."
                    % (_n, _tag))
                assert int(_sub["min_rows"]) > 0, (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: a `min_rows` "
                    "of %r is vacuous — every window has at least zero rows, "
                    "and a leaf with no rows at all already fails."
                    % (_n, _tag, _sub["min_rows"]))
            if "edge_count_between" in _sub:
                assert not ({"min_ticks", "max_ticks", "max_ms",
                             "max_continuous_ticks"} & set(_sub)), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: "
                    "`edge_count_between` is its own assertion kind; a tick or "
                    "latency bound written beside it is silently dropped. Split "
                    "it into two specs." % (_n, _tag))
                assert ("switch_bit" in _sub) or ("aux_bit" in _sub), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: "
                    "`edge_count_between` counts transitions of a BIT, so it "
                    "needs a `switch_bit` or an `aux_bit`." % (_n, _tag))
                _band = tuple(_sub["edge_count_between"])
                assert len(_band) == 2, (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: "
                    "`edge_count_between` is an INCLUSIVE (lo, hi) pair."
                    % (_n, _tag))
                assert 0 <= int(_band[0]) <= int(_band[1]), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: "
                    "`edge_count_between` needs 0 <= lo <= hi; %r is empty or "
                    "negative and can never be satisfied." % (_n, _tag, _band))
                assert _sub.get("edge", "rise") in ("rise", "fall"), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: `edge` must be "
                    "'rise' or 'fall'." % (_n, _tag))
            _bound_keys = ("min_ticks", "min_value", "strictly_decreases_by",
                           "max_ms", "fault_latch_bit", "any_of",
                           "edge_count_between")
            # `max_continuous_ticks` joins `max_ticks` in the vacuity family: a
            # blank or absent column has a longest run of ZERO and satisfies it
            # without the observable ever having been recorded.
            if any(_k in _sub for _k in ("max_ticks", "max_continuous_ticks")) \
                    and not any(_k in _sub for _k in _bound_keys):
                _sig_id = ("switch_bit", _sub["switch_bit"]) if "switch_bit" in _sub \
                    else ("aux_bit", _sub["aux_bit"]) if "aux_bit" in _sub \
                    else ("column", _sub.get("column"))
                _companion = False
                for _o in (_e.get("signals_require") or ()):
                    for _osub in [_o] + list(_o.get("any_of") or ()):
                        if _osub is _sub:
                            continue
                        if _osub.get(_sig_id[0]) != _sig_id[1]:
                            continue
                        if any(_k in _osub for _k in _bound_keys):
                            _companion = True
                _kind = ("max_continuous_ticks" if "max_continuous_ticks" in _sub
                         else "max_ticks")
                assert _companion or _sub.get("vacuity_note"), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: `%s` is "
                    "its only assertion, and a blank or absent %s=%r column "
                    "satisfies it with zero matching ticks. Add a companion "
                    "spec on the same signal carrying a positive bound "
                    "(min_ticks/min_value/max_ms/...), or a `vacuity_note` "
                    "saying why the column cannot be blank in this run."
                    % (_n, _tag, _kind, _sig_id[0], _sig_id[1]))
            # ── 2026-09-02 (fix-queue item 2): A TICK BOUND THE SCANNER CANNOT
            # HONOUR.  `regen_clamp_dwell` paired a numeric `min_value` with
            # `min_ticks` and the scanner had no counter on the float path at
            # all, so the check read a structurally-zero tick count and failed a
            # run whose physics passed with 30 % margin — for a whole campaign,
            # in both charger eras, with wording ("bit set on 0 ticks") that
            # named a bit the spec never mentioned.  The counter now exists for
            # numeric thresholds; what remains impossible is a tick bound with
            # NO predicate at all, and that must fail at import rather than
            # measure zero mid-campaign.
            if _is_tick_counting_spec(_sub):
                assert any(_k in _sub for _k in ("switch_bit", "aux_bit",
                                                 "value_mask")) \
                    or _threshold_of(_sub) is not None, (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r] declares a tick "
                    "bound but no predicate saying WHICH ticks count. "
                    "scan_signals() counts a tick when a `switch_bit`/`aux_bit` "
                    "is set, when a `value_mask` matches, or when a numeric "
                    "column is on the right side of its own `min_value`/"
                    "`max_value` threshold. Add one of those, or use a value "
                    "kind instead of a tick kind." % (_n, _tag))
                assert _sub.get("column") or "sum_of" in _sub or "ratio_of" in _sub \
                    or any(_k in _sub for _k in ("switch_bit", "aux_bit")), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: a tick bound on "
                    "a value predicate needs a `column` or a derived value "
                    "source to read." % (_n, _tag))
            # `exclude_when_switch_bit` (2026-09-02) masks ROWS out of a NUMERIC
            # measurement; on a bit spec the mask and the watched bit would be
            # two predicates on the same row and the reader could not tell which
            # one the verdict came from.
            if "exclude_when_switch_bit" in _sub:
                assert _sub.get("column") or "sum_of" in _sub or "ratio_of" in _sub, (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: "
                    "`exclude_when_switch_bit` masks rows out of a NUMERIC "
                    "measurement, so the spec needs a `column` or a derived "
                    "value source." % (_n, _tag))
                assert not ({"switch_bit", "aux_bit"} & set(_sub)), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: "
                    "`exclude_when_switch_bit` cannot be combined with a bit "
                    "spec — the mask and the watched bit would be two "
                    "predicates on one row." % (_n, _tag))
                assert int(_sub["exclude_when_switch_bit"]) > 0, (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: an empty "
                    "`exclude_when_switch_bit` mask excludes nothing."
                    % (_n, _tag))
                assert float(_sub.get("exclude_hold_ms", 0.0)) >= 0.0, (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: a negative "
                    "`exclude_hold_ms` would UN-exclude rows." % (_n, _tag))
            # A settling hold is meaningless without the mask it holds open —
            # written alone it would be read as an exclusion and enforce none.
            assert "exclude_hold_ms" not in _sub or "exclude_when_switch_bit" in _sub, (
                "FAULT_EXPECTATIONS[%r].signals_require[%r]: `exclude_hold_ms` "
                "extends `exclude_when_switch_bit` past the bit's fall and has "
                "no meaning without it." % (_n, _tag))
            assert_derived_source_shape(_n, _tag, _sub)
            if "reach_within_ms" in _sub:
                # THE SETTLING KIND (2026-09-03). It reads TWO columns on one
                # row — a bit to find the reference instant, a numeric column to
                # find the crossing — so its shape is fully pinned here rather
                # than left to be discovered by a silent misread.
                assert ("aux_bit" in _sub) or ("switch_bit" in _sub), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: "
                    "`reach_within_ms` needs an `aux_bit` or `switch_bit` whose "
                    "RISING edge is the instant the settling is measured from."
                    % (_n, _tag))
                assert _sub.get("column") and _sub.get("min_value") is not None, (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: "
                    "`reach_within_ms` needs a `column` and the `min_value` "
                    "that column has to reach." % (_n, _tag))
                assert not ({"min_ticks", "max_ticks", "max_value", "max_ms",
                             "floor_min_value", "max_continuous_ticks",
                             "edge_count_between"} & set(_sub)), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: a "
                    "`reach_within_ms` spec carries a bound the settling kind "
                    "never reads, so the author asked for two assertions and "
                    "got one. Split it into two specs." % (_n, _tag))
                assert _sub.get("t_window"), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: "
                    "`reach_within_ms` needs a `t_window` that OPENS BEFORE the "
                    "bit rises, or the pre-edge level is unknown and the check "
                    "can only report 'the bit never rose'." % (_n, _tag))
            if "max_ms" in _sub:
                # L5: the latency kind is SELECTED by `max_ms` and ignores tick
                # bounds entirely, so a tick bound written beside it is silently
                # dropped — the author asked for two assertions and got one.
                assert not ({"min_ticks", "max_ticks"} & set(_sub)), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: a `max_ms` "
                    "latency spec carries min_ticks/max_ticks, which the latency "
                    "kind never reads. Split it into two specs." % (_n, _tag))
                assert ("switch_bit" in _sub) or ("aux_bit" in _sub), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: "
                    "switch_fall_latency_ms needs a `switch_bit` or `aux_bit` to "
                    "watch." % (_n, _tag))
                assert _sub.get("max_ms") is not None and _sub.get("after_t") is not None, (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: "
                    "switch_fall_latency_ms needs `after_t` (the stimulus the "
                    "latency is measured FROM) and `max_ms` (the regression "
                    "tripwire)." % (_n, _tag))
                assert _sub.get("edge", "fall") in ("fall", "rise"), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: `edge` must be "
                    "'fall' or 'rise'." % (_n, _tag))
                _w = _sub.get("t_window")
                assert _w and _w[0] < float(_sub["after_t"]), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: the t_window "
                    "must OPEN BEFORE after_t (%r), or the pre-edge level is "
                    "unknown and the check can only report 'no transition'."
                    % (_n, _tag, _sub.get("after_t")))
    assert isinstance(_e.get("child_tx_healthy", False), bool), (
        "FAULT_EXPECTATIONS[%r].child_tx_healthy must be a bool." % _n)


for _n, _e in FAULT_EXPECTATIONS.items():
    _assert_signal_spec_shapes(_n, _e)
del _n, _e

for _n, _e in FAULT_EXPECTATIONS.items():
    _dur = (SCENARIOS.get(_n) or {}).get("duration_s")
    for _key, _t in _expectation_time_bounds(_e):
        assert _dur is None or _t is None or _t < _dur, (
            "FAULT_EXPECTATIONS[%r].%s = %r must be < SCENARIOS[%r]['duration_s'] "
            "(%.1f): a bound at or past the end of the run is never crossed, so "
            "the check is vacuous (not_before_s / after_t), probes a row that does "
            "not exist (survive_to.t), or is silently clipped (t_window upper "
            "bound). Re-derive the duration or the bound."
            % (_n, _key, _t, _n, _dur))
    _nb = _e.get("not_before_s")
    assert _nb is None or _nb > WARM_RESET_GRACE_S, (
        "FAULT_EXPECTATIONS[%r].not_before_s = %r must be > WARM_RESET_GRACE_S "
        "(%.1f): faults are judged on the post-grace window, so an earlier bound "
        "is vacuously satisfied rather than stricter." % (_n, _nb, WARM_RESET_GRACE_S))
    _sv = (_e.get("survive_to") or {}).get("t")
    assert _sv is None or _sv > WARM_RESET_GRACE_S, (
        "FAULT_EXPECTATIONS[%r].survive_to.t = %r must be > WARM_RESET_GRACE_S "
        "(%.1f): the survive probe reads the post-grace scan, so an earlier time "
        "is never observed and the check degrades to 'no observation frame'."
        % (_n, _sv, WARM_RESET_GRACE_S))
del _n, _e, _nb, _sv

# Always-reported open findings (report section 'Known open findings').
K_DROOP_FINDING = (
    "K_DROOP_BUS design-vs-measured x4 discrepancy: tools/hil_plant_sim.py's "
    "constant comment records that the measured shared-source droop is "
    "0.074 V/A while the MDAC droop-chain DESIGN value is R_e = RE_MAX*g = "
    "2.014*0.298 = 0.60 ohm/channel = 0.30 V/A shared — four times higher. "
    "Nothing in the repo explains the gap. The hi-fi engine (hil_electrical.py) "
    "reproduces the DESIGN value by construction, so the same scenario run in "
    "both electrical modes shows the gap directly; treat any bus-droop number "
    "in this report as mode-dependent until the discrepancy is closed."
)

# WP-E (2026-09-01): WHICH droop realization THIS campaign's scenario half ran.
# Appended to the finding above so a reader cannot take a sag figure out of the
# report without also reading the mode it was produced in — which is the whole
# hazard the finding describes.
K_DROOP_MODE_NOTE = {
    "design": (
        "**This campaign's scenario half ran `--droop design`** (the default, "
        "and what every campaign on record ran): the hi-fi engine realizes the "
        "DESIGNED chain, ~0.316 ohm shared / 0.633 single, so its bus sags are "
        "~4x DEEPER than a bench log's. Sag-based results are CONSERVATIVE and "
        "are not comparable with a recorded bench trace."),
    "measured": (
        "⚠️ **This campaign's scenario half ran `--droop measured`** — the "
        "hi-fi engine's droop was rescaled to the BENCH fit (0.16 V/A "
        "single-source, the anchor; 0.080 V/A shared, +8.1 % over the measured "
        "0.074 because the network's shared/single ratio is structurally 2.000 "
        "and the fit's is 2.182). Sags here ARE comparable with a bench log and "
        "are NOT comparable with any other campaign in the archive. The mode is "
        "an empirical rescale and EXPLAINS NOTHING about the finding above. "
        "The REPLAY half still ran `design` — its bands are design-calibrated."),
}
assert set(K_DROOP_MODE_NOTE) == set(DROOP_MODES), (
    "a droop mode exists that the report has no standing-finding note for")


def _suite_mode(args):
    """The suite's command-source mode, recorded in meta and every run record.

    'pi-live'  — a REAL Pi owns the 22-byte command packet (--pi-live)
    'scripted' — the default: each scenario's own pi_timeline (or, for a scenario
                 that declares one, its emulated-EMS strategy inside the child)"""
    return "pi-live" if getattr(args, "pi_live", False) else "scripted"


def _split_bits(bits):
    """Iterate the individual set bits of a mask, low to high."""
    b = 1
    while b <= bits:
        if bits & b:
            yield b
        b <<= 1


def fault_names(bits):
    """'UV_BUS|OC_FC' style rendering of a fault_flags word."""
    if not bits:
        return "none"
    names = [n for b, n in sorted(FAULT_NAMES.items()) if bits & b]
    unknown = bits & ~sum(FAULT_NAMES)
    if unknown:
        names.append("0x%04X" % unknown)
    return "|".join(names)


# ─────────────────────────────────────────────────────────────────────────────
# Run plan
# ─────────────────────────────────────────────────────────────────────────────

def blg_duration_estimate_s(path, preamble_s=REPLAY_PREAMBLE_S):
    """Rough replay duration from a BLG's size: (bytes - 32 B header)/rec_size at
    1 kHz. Header layout per tools/decode_benchlog.py (HEADER_SIZE 32, record_size
    at byte 5). Used ONLY to size the child's timeout — never reported as fact."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            head = fh.read(8)
        if len(head) < 8 or head[:4] != b"BLG1":
            return None
        rec = head[5]
        if rec <= 0:
            return None
        # + the synthetic bring-up preamble hil_plant_sim prepends to this replay,
        # or the timeout would be short by that much. `preamble_s` is PER ENTRY: a
        # skip_preamble entry replays raw and adds nothing.
        return preamble_s + max(0.0, (size - 32) / rec / 1000.0)
    except OSError:
        return None


def build_plan(args):
    """Return the full ordered run plan as a list of plain dicts.

    Pure w.r.t. the board: safe to call for --list / --dry-run with no hardware."""
    plan = []

    pi_live = getattr(args, "pi_live", False)

    if not args.replay_only:
        with_operator = getattr(args, "with_operator", False)
        with_ftp75 = getattr(args, "with_ftp75", False)
        with_ftp75c = getattr(args, "with_ftp75c", False)
        for name, meta in SCENARIOS.items():
            need = meta.get("electrical", "any")
            if meta.get("operator_required") and not with_operator:
                # SKIPPED, not scored (HIL_FINDINGS 'drive'): this scenario's
                # stimulus is an operator at the USB serial console. Run
                # unattended it commands nothing at all — the board sits in Idle,
                # `current` is 0.000 A for the whole run, and the loop the
                # scenario names is never exercised. Scoring that clean advertises
                # coverage the run does not have. Same skip-record mechanism as
                # the --pi-live skips below.
                plan.append({
                    "kind": "scenario", "name": name,
                    "mode": need if need in ("simple", "hifi") else args.electrical_pref,
                    "electrical_required": need,
                    "description": meta.get("description", ""),
                    "duration_s": 0.0, "csv": None, "events": None, "log": None,
                    "argv": None, "timeout_s": 0.0,
                    "skip_reason": (
                        "OPERATOR-REQUIRED: this scenario's stimulus is an "
                        "operator driving the firmware over USB serial. Run "
                        "unattended it commands nothing (no pi_timeline, no ems "
                        "strategy) and proves only that the board idles and the "
                        "link is healthy. Pass --with-operator to run it anyway, "
                        "with a human at the console."),
                })
                continue
            if pi_live and (meta.get("pi_timeline") or meta.get("ems")):
                # SKIPPED, not failed: under --pi-live the real Pi owns the 22-byte
                # command packet, and hil_plant_sim.py refuses a scenario carrying
                # its own timeline (two command sources would overwrite each other
                # at 50 Hz). Recorded with a reason so the report shows the gap.
                plan.append({
                    "kind": "scenario", "name": name,
                    "mode": need if need in ("simple", "hifi") else args.electrical_pref,
                    "electrical_required": need,
                    "description": meta.get("description", ""),
                    "duration_s": 0.0, "csv": None, "events": None, "log": None,
                    "argv": None, "timeout_s": 0.0,
                    "skip_reason": (
                        ("--pi-live: this scenario carries its own pi_timeline "
                         "(%d entries); the real Pi owns the command link"
                         % len(meta["pi_timeline"])) if meta.get("pi_timeline") else
                        ("--pi-live: this scenario's whole stimulus IS the emulated "
                         "EMS layer (strategy '%s'); with a real Pi commanding there "
                         "is nothing left for it to drive" % meta["ems"])),
                })
                continue
            if name in ALPHA_SCENARIOS and not getattr(args, "with_alpha",
                                                       False):
                # SKIPPED, not scored, for an EXPERIMENT reason rather than a
                # cost or coverage one — see the ALPHA_SCENARIOS banner. Same
                # skip-record mechanism as the gates around it, so the report
                # shows the gap instead of quietly shortening the plan.
                #
                # ORDERED AFTER the --pi-live gate for the same reason
                # --with-ftp75 is: all three are EMS-driven, so under --pi-live
                # they are skipped whatever this flag says and the honest
                # reason is the pi-live one.
                plan.append({
                    "kind": "scenario", "name": name,
                    "mode": need if need in ("simple", "hifi") else args.electrical_pref,
                    "electrical_required": need,
                    "description": meta.get("description", ""),
                    "duration_s": 0.0, "csv": None, "events": None, "log": None,
                    "argv": None, "timeout_s": 0.0,
                    "skip_reason": (
                        "ALPHA SWEEP: this leg replays one point of the "
                        "eta-era SDP alpha sweep and answers a question only "
                        "the alpha round asks, so it is not part of the "
                        "regression campaign. The set adds ~%.1f min. Nothing "
                        "about the board or the link blocks it — pass "
                        "--with-alpha to run them."
                        % (sum(float((SCENARIOS.get(n) or {}).get("duration_s", 0.0))
                               for n in ALPHA_SCENARIOS) / 60.0)),
                })
                continue
            if name in FTP75C_SCENARIOS and not with_ftp75c:
                # SKIPPED, not scored, for a COST reason AND a PLANT-
                # CONFIGURATION one - see the FTP75C_SCENARIOS banner.  Ordered
                # with the other opt-in gates and AFTER the --pi-live gate, for
                # the reason the --with-ftp75 gate below states.
                plan.append({
                    "kind": "scenario", "name": name,
                    "mode": need if need in ("simple", "hifi") else args.electrical_pref,
                    "electrical_required": need,
                    "description": meta.get("description", ""),
                    "duration_s": 0.0, "csv": None, "events": None, "log": None,
                    "argv": None, "timeout_s": 0.0,
                    "skip_reason": (
                        "COMPRESSED CYCLE ON A COMPENSATED PLANT: the ftp75c "
                        "legs run %.0f s each (~%.1f min for the set) on "
                        "`--drag scaled-air`, a road-load-compensated plant "
                        "that is HIL-ONLY - it needs a second road-load motor "
                        "to replicate on the bench. They are the only "
                        "drive-cycle legs on this rig that regenerate at all. "
                        "Nothing about the board or the link blocks them - "
                        "pass --with-ftp75c to run them."
                        % (float(meta.get("duration_s", 0.0)),
                           sum(float((SCENARIOS.get(n) or {}).get("duration_s", 0.0))
                               for n in FTP75C_SCENARIOS) / 60.0)),
                })
                continue
            if name in FTP75_SCENARIOS and not with_ftp75:
                # SKIPPED, not scored, and for a COST reason rather than a
                # coverage one: these are 350 s each — ~17.5 min for the three
                # against a ~23 min campaign — so they are opt-in. Same
                # skip-record mechanism as the two gates above, so the report
                # shows the gap instead of quietly shortening the plan.
                #
                # ORDERED AFTER the --pi-live gate deliberately: all three
                # scenarios are EMS-driven, so under --pi-live they are skipped
                # WHATEVER --with-ftp75 says, and the honest reason is the
                # pi-live one. Reporting "pass --with-ftp75 to run them" there
                # would name a flag that could not make the run happen.
                plan.append({
                    "kind": "scenario", "name": name,
                    "mode": need if need in ("simple", "hifi") else args.electrical_pref,
                    "electrical_required": need,
                    "description": meta.get("description", ""),
                    "duration_s": 0.0, "csv": None, "events": None, "log": None,
                    "argv": None, "timeout_s": 0.0,
                    "skip_reason": (
                        "LONG-CYCLE: the EPA FTP-75 study segment runs %.0f s, "
                        "and the set adds ~%.1f min to the campaign. Nothing "
                        "about the board or the link blocks it — pass "
                        "--with-ftp75 to run them."
                        % (float(meta.get("duration_s", 0.0)),
                           sum(float((SCENARIOS.get(n) or {}).get("duration_s", 0.0))
                               for n in FTP75_SCENARIOS) / 60.0)),
                })
                continue
            mode = need if need in ("simple", "hifi") else args.electrical_pref
            dur = float(meta.get("duration_s", 30.0))
            csv_name = "hil_scenario_%s_%s.csv" % (name, mode)
            argv = [
                "--scenario", name,
                "--electrical", mode,
                "--duration", "%g" % dur,
                "--csv", os.path.join(args.out, csv_name),
            ]
            if meta.get("vesc_cap_f") is not None and mode == "hifi":
                argv += ["--vesc-cap-uf", "%g" % (meta["vesc_cap_f"] * 1e6)]
            if name == "soc-depletion":
                # RE-DERIVED 2026-08-30 (campaign 20260830_214819, HIL_FINDINGS
                # 'soc-depletion').  The previous derivation — --soc0 0.15 for
                # 880 s, aiming at "~4.4 % SOC" — was wrong on both of its inputs,
                # and the run it produced could not satisfy its own signal check:
                #
                #  1. COULOMB CURRENT.  It used the 2.2 A SOC_ENDURANCE_LOAD_A
                #     figure, which is a BUS-SIDE load.  The pack sits behind the
                #     boost (6.46 -> 14.37 V), so the PACK-SIDE current that
                #     actually depletes it is ~2.8x larger.
                #     F4 (2026-08-31): that current is a RANGE, not a point —
                #     measured 5.72-6.45 A, MEAN 6.03 A (round-1 campaign
                #     20260831_000518), rising as the pack drains because the bus
                #     load is constant POWER and a falling V_batt must be met with
                #     more pack current. The estimate below therefore uses a mean,
                #     which is why the predicted latch time is approximate.
                #  2. WINDOW.  It assumed the load simply runs for ~870 s.  It does
                #     not: the UV_BATT latch is a STATE condition —
                #     OCV(soc) - I*(Rs(soc)+R1) = 6.2 V solves at soc_latch ~=
                #     0.1130 — so the run is FORECLOSED there, at ~105.5 s from
                #     soc0 0.15.  The remaining ~775 s were spent latched.
                #
                # Consequence: from soc0 0.15 the maximum observable fall is
                # 0.15 - 0.113 = 0.0370, BELOW the 0.05 signal threshold, for any
                # duration.  Corrected here and in FAULT_EXPECTATIONS together:
                #   --soc0 0.20  -> ceiling 0.20 - 0.113 = 0.087 = 1.74x the
                #                   threshold, and the run STARTS above the
                #                   Rs(SOC) knee, so "walks down the OCV curve"
                #                   is literally true for the early window.
                #   --duration 400 -> estimated latch at
                #                   13 + 0.087*18000/6.03 ~= 273 s (the 6.19 A
                #                   point estimate gave ~266 s), plus ~127 s of
                #                   margin and tail.  480 s CHEAPER than the old
                #                   880 s, and the objective is now reachable.
                #                   MEASURED 270.704 s (round-1 campaign
                #                   20260831_000518), so the tail actually ran
                #                   ~129 s — the uncertainty budget below was not
                #                   needed this time, but see why it stays.
                # The signal check is disjunctive (see FAULT_EXPECTATIONS): either
                # the 0.05 fall OR a post-ramp UV_BATT latch proves the depletion.
                #
                # SOC_ENDURANCE_LOAD_A stays 2.2 A (review M4, hardware-validated
                # 21.19 % BT margin) — only soc0 and the duration move.
                #
                # THE ~3 s POST-EVENT TRIM RULE (2026-08-30) DELIBERATELY DOES NOT
                # APPLY HERE. Every other scenario's last event is at a SCRIPTED
                # time, so the tail can be cut to a few seconds with certainty.
                # This one's last event — the UV_BATT latch — is at a MODELLED
                # time: ~266 s, from an Rs(SOC) curve that is still
                # `TODO(calibrate)` (hil_plant_sim BatterySource). The ~134 s of
                # tail is not dead time, it is the uncertainty budget on that
                # estimate; trimming it to ~269 s would turn any model error into
                # a run that ends before its own objective. Re-derive this only
                # once the OCV/Rs curve is measured.
                dur = 400.0
                argv = [
                    "--scenario", name,
                    "--electrical", mode,
                    "--duration", "%g" % dur,
                    "--soc0", "0.20",
                    "--csv", os.path.join(args.out, csv_name),
                ]
            elif name == "charge-to-full":
                # The SECOND --soc0 override, and the mirror image of the one
                # above: soc-depletion starts LOW to reach a UV latch, this one
                # starts NEXT TO FULL to reach the Ag105's Fully-Charged branch.
                #
                # WHY IT IS NECESSARY AT ALL.  The branch condition is
                # soc >= 0.995 (Plant.step()).  The largest SoC RISE any campaign
                # has produced is ~0.0009, against the ~0.29 that the default
                # --soc0 0.70 would need — roughly 14 hours at this scenario's
                # 1.0 A ceiling.  Starting at 0.990 leaves 0.005 of a 5 Ah pack =
                # 0.005 * 18000 = 90 A·s = 90 s of charging, so FULL is expected
                # around t = 100 (charge_goal at t = 8 + AG105_SETTLE_S + ramp)
                # and the 130 s duration leaves ~30 s to observe the taper and
                # the firmware's deliberate no-action response.
                #
                # NOT a scenario constant: --soc0 is a RUN ARGUMENT (the same
                # class the DP fingerprint calls out), and the standalone
                # SCENARIOS default stays 0.7 so a hand-run of this scenario at
                # some other SoC is still a legal thing to do.
                argv = [
                    "--scenario", name,
                    "--electrical", mode,
                    "--duration", "%g" % dur,
                    "--soc0", "0.990",
                    "--csv", os.path.join(args.out, csv_name),
                ]
            # ── WP-E: droop realization mode ─────────────────────────────────
            # Appended AFTER the per-scenario branches above, because two of
            # them REBUILD `argv` wholesale and an earlier append would be
            # silently discarded on exactly those two runs.
            #
            # Added only when NON-DEFAULT, deliberately: every campaign on
            # record ran the design chain, and stamping an explicit
            # `--droop design` into every child's argv would make this
            # campaign's recorded command lines differ from theirs for no
            # behavioural reason. Provenance does not depend on the flag —
            # hil_plant_sim writes `config.droop_mode` into every CSV's meta
            # sidecar unconditionally, default included.
            #
            # THE REPLAY HALF IS NOT PASSED THIS FLAG. Every replay entry's
            # thresholds were calibrated against design-mode sag depths, and
            # `--droop measured` would move the bus rail under checks that
            # were derived from it. A measured-mode replay campaign needs its
            # bands re-derived first; that is an operator decision, not a
            # side effect of a scenario-side flag.
            if getattr(args, "droop", "design") != "design":
                argv += ["--droop", getattr(args, "droop", "design")]
            # -- PART A (C1, 2026-09-01): converter-asymmetry mode ------------
            # Appended here for the same reason as `--droop` (two branches
            # above rebuild `argv` wholesale).  Passed only when NON-DEFAULT,
            # again for the same reason: the child's own default is
            # ASYMMETRY_MODE_DEFAULT and provenance rides `config.asymmetry`
            # in every CSV meta sidecar, so an explicit flag on every command
            # line would buy nothing.
            #
            # THE REPLAY HALF IS NOT PASSED THIS FLAG EITHER -- and it does not
            # need to be: a replay run drives the rails from a log and
            # constructs no hi-fi engine, so no asymmetry is realized on that
            # half in either mode.
            if getattr(args, "asymmetry",
                       ASYMMETRY_MODE_DEFAULT) != ASYMMETRY_MODE_DEFAULT:
                argv += ["--asymmetry", getattr(args, "asymmetry",
                                                ASYMMETRY_MODE_DEFAULT)]
            plan.append({
                "kind": "scenario", "name": name, "mode": mode,
                "electrical_required": need,
                "description": meta.get("description", ""),
                "duration_s": dur,
                "csv": os.path.join(args.out, csv_name),
                "events": os.path.join(args.out, csv_name) + ".events.jsonl",
                "log": os.path.join(args.out, "run_scenario_%s.log" % name),
                "argv": argv,
                "timeout_s": dur + TIMEOUT_GRACE_S,
            })

    if not args.scenarios_only:
        for entry in REPLAY_SUITE:
            if pi_live:
                # F5: skip the ENTIRE replay half under --pi-live, per-entry
                # (same skip-record mechanism as the pi_timeline/ems scenario
                # skips above) rather than silently letting a real Pi command
                # over a replayed trajectory it was never part of recording.
                plan.append({
                    "kind": "replay", "name": entry["log"], "mode": entry["mode"],
                    "description": entry.get("classification", ""),
                    "duration_s": 0.0, "csv": None, "events": None, "log": None,
                    "argv": None, "timeout_s": 0.0, "entry": entry,
                    "skip_reason": (
                        "--pi-live: replay mode plays a RECORDED trajectory "
                        "regardless of what a live Pi commands, so the Pi would "
                        "be an uncontrolled second stimulus over a run that "
                        "cannot react to it — the whole replay half is skipped "
                        "under --pi-live"),
                })
                continue
            csv_path = replay_csv_path(entry, args.out)
            argv = build_sim_argv(entry, args.out)
            est = blg_duration_estimate_s(os.path.join(_REPO, entry["path"]),
                                          preamble_s=entry_preamble_s(entry))
            plan.append({
                "kind": "replay", "name": entry["log"], "mode": entry["mode"],
                "description": entry.get("classification", ""),
                "duration_s": est,
                "csv": csv_path,
                "events": None,
                "log": os.path.join(args.out, "run_replay_%s.log" % entry["log"]),
                "argv": argv,
                "timeout_s": (est if est else 120.0) + TIMEOUT_GRACE_S,
                "entry": entry,
            })
        if pi_live:
            print("[suite] --pi-live: skipping the entire replay half (%d entries) — "
                  "a live Pi would be an uncontrolled second stimulus over a "
                  "replayed trajectory" % len(REPLAY_SUITE))

    return filter_plan(plan, args.only, args.skip)


def filter_plan(plan, only, skip):
    """--only/--skip are shell-glob patterns matched against the run name."""
    out = []
    for p in plan:
        if only and not any(fnmatch.fnmatch(p["name"], pat) for pat in only):
            continue
        if skip and any(fnmatch.fnmatch(p["name"], pat) for pat in skip):
            continue
        out.append(p)
    return out


def full_argv(plan_item, args):
    """The child's complete argv, transport flags appended (build_sim_argv and the
    scenario builder both deliberately omit them — the wrapper owns transport)."""
    if plan_item.get("skip_reason"):
        return []          # nothing is launched for a skipped run
    # D1/K1: --force on EVERY child, both halves.  hil_plant_sim.py refuses an
    # explicit --csv whose CSV or either sidecar already exists (exit 2), and a
    # child cannot be asked interactively.  The default report directory is
    # fresh per run so nothing is there — but an operator-supplied --out, a
    # re-run into the same directory, or a partially-completed plan resumed into
    # it all collide, and the run would die at startup with a refusal nobody is
    # present to answer.  Deduplicated because hil_replay_suite.build_sim_argv()
    # also emits it (for operators using --argv-for by hand).
    force = [] if "--force" in plan_item["argv"] else ["--force"]
    return ([sys.executable, SIM_SCRIPT] + plan_item["argv"] + force
            + ["--teensy-ip", args.teensy_ip, "--port", str(args.port)]
            + (["--dash"] if getattr(args, "dashboard", False) else [])
            # --pi-live applies to the SCENARIO half only: replay mode creates no
            # commander anyway, and hil_plant_sim.py refuses the combination.
            + (["--pi-live"] if getattr(args, "pi_live", False)
               and plan_item["kind"] == "scenario" else []))


# ─────────────────────────────────────────────────────────────────────────────
# Execution + health checks
# ─────────────────────────────────────────────────────────────────────────────

def parse_child_summary(text):
    """Pull the numbers out of hil_plant_sim's own exit summary lines."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[hil] done:"):
            # "[hil] done: N ticks in X s -> Y Hz achieved (target Z Hz), max overrun W ms"
            try:
                out["ticks"] = int(line.split("done:")[1].split("ticks")[0])
                out["achieved_hz"] = float(line.split("->")[1].split("Hz")[0])
                out["max_overrun_ms"] = float(line.split("max overrun")[1].split("ms")[0])
            except (IndexError, ValueError):
                pass
        elif line.startswith("[hil] tx="):
            try:
                out["tx_frames"] = int(line.split("tx=")[1].split()[0])
                out["rx_frames"] = int(line.split("rx=")[1].split()[0])
                out["rx_bad"] = int(line.split("frames,")[-1].split()[0])
            except (IndexError, ValueError):
                pass
            try:
                # F2: absent on an older sim build (pre-fix) -- treated as
                # "unknown", not "zero", by the judge below.
                out["send_errors"] = int(line.split("send_errors=")[1].split()[0])
            except (IndexError, ValueError):
                pass
        elif line.startswith("[hil] warm resets:"):
            # "[hil] warm resets: N observed, M mid-run (after 2.0s)[ at t=...]"
            try:
                out["warm_resets"] = int(line.split("resets:")[1].split("observed")[0])
                out["warm_resets_mid_run"] = int(
                    line.split("observed,")[1].split("mid-run")[0])
            except (IndexError, ValueError):
                pass
        elif line.startswith("[hil] electrical(hifi):"):
            try:
                out["substep_khz"] = float(line.split(":")[1].split("kHz")[0])
                out["elec_events"] = int(line.split("),")[1].split("events")[0])
            except (IndexError, ValueError):
                pass
        elif "ABOVE the 20 V abs-max" in line:
            out["over_absmax_line"] = line
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Injection-stream continuity, from the child's own exit summary.
#
# EXTRACTED (2026-08-31) from the --pi-live PI_TIMEOUT excusal, which invented
# this test inline.  It now has a SECOND consumer: the `child_tx_healthy` signal
# check, which any scenario may declare.  ONE implementation, because the two
# consumers must agree about what "the stream was continuous" means — a scenario
# asserting it and the excusal excusing on it would otherwise be two different
# thresholds with one name.
#
# THE TEST: tx_frames >= 98 % of the frames a full-rate run would have sent, and
# ZERO sendto() errors.  Both must be MEASURED — an older sim build emits no
# `send_errors=` field, and that is "unknown", never "zero" (F2).
STREAM_CONTINUITY_FRAC = 0.98


def child_stream_continuity(child, duration_s):
    """(ok, detail) for THIS process's own injection stream over the run.

    `ok` is None when the numbers were not measured — the caller must render that
    as UNVERIFIED rather than as either verdict.  Pure over its inputs."""
    summary = (child or {}).get("summary") or {}
    tx = summary.get("tx_frames")
    send_errors = summary.get("send_errors")
    expected = (HIL_DEFAULT_RATE_HZ * duration_s) if duration_s else None
    if tx is None or send_errors is None or expected is None:
        return None, ("injection-stream continuity UNMEASURED (tx=%s, "
                      "send_errors=%s, expected=%s) — an older sim build emits no "
                      "send_errors field, and a missing number is not a zero"
                      % (tx, send_errors,
                         "%.0f" % expected if expected else None))
    ok = tx >= STREAM_CONTINUITY_FRAC * expected and send_errors == 0
    return ok, ("tx=%d/%.0f frames (%.1f%%, need >= %.0f%%), %d send error(s)"
                % (tx, expected, 100.0 * tx / expected if expected else 0.0,
                   100.0 * STREAM_CONTINUITY_FRAC, send_errors))


# ─────────────────────────────────────────────────────────────────────────────
# 0x8010 ATTRIBUTION — the wire first, inference only as a fallback (fw v25).
#
# FAULT_PI_TIMEOUT and FAULT_HIL_LINK share fault bit 0x0010 (the alias is
# deliberate, .ino:1240-1248; the #define is :1265), and fault_flags is
# protocol-frozen with no free bit.  Until fw v25 the harness could only INFER
# which of the two fired, from its own transmit statistics: a continuous
# injection stream makes a HIL-link explanation implausible, leaving PI_TIMEOUT.
#
# fw v25 appends error_code to the observation frame (.ino:2968-2978) — the
# LATCHED FIRST CAUSE, which triggerFault() records exactly once while it only
# ORs bits into fault_flags.  ERR_PI_TIMEOUT (0x05) and ERR_HIL_STALE (0x10) are
# distinct values there, so on a fw v25 board the question is READ, not inferred.
#
# PRECEDENCE IS DELIBERATE: the wire wins whenever it spoke.  A board that says
# ERR_HIL_STALE while this process's own tx counters look perfect is reporting
# something real (the datagrams left this host but did not arrive), and the
# inference would have got it wrong — which is exactly the failure the frame
# extension exists to prevent.  The inference stays for 16/17-byte boards and is
# LABELLED as an inference wherever it is used.
ATTRIB_WIRE, ATTRIB_INFERRED, ATTRIB_UNKNOWN = "wire", "inferred", "unknown"


def attribute_shared_0x8010(metrics, child, duration_s):
    """Which of the two 0x0010 causes latched?  (cause, source, detail).

    `cause` is "pi", "hil", or None (undecided).  `source` is ATTRIB_WIRE when a
    fw v25 error_code decided it, ATTRIB_INFERRED when stream health did, and
    ATTRIB_UNKNOWN when neither could.  Pure over its inputs."""
    ec = (metrics or {}).get("error_code_post_grace")
    if ec is not None:
        if ec == ERR_PI_TIMEOUT:
            return "pi", ATTRIB_WIRE, ("board reports error_code %s — the Pi "
                                       "watchdog latched first (read off the "
                                       "wire, fw v25 frame byte 16)"
                                       % error_code_name(ec))
        if ec == ERR_HIL_STALE:
            return "hil", ATTRIB_WIRE, ("board reports error_code %s — the "
                                        "injection link went stale (read off "
                                        "the wire, fw v25 frame byte 16)"
                                        % error_code_name(ec))
        # A third code means something ELSE latched first and the 0x0010 bit,
        # if set at all, was a later OR.  Neither attribution is available, and
        # inventing one from stream health would be worse than saying so.
        return None, ATTRIB_WIRE, ("board reports error_code %s — the first "
                                   "latched cause was neither PI_TIMEOUT nor "
                                   "HIL_STALE, so the shared 0x0010 bit cannot "
                                   "be attributed to either" % error_code_name(ec))
    cont_ok, cont_detail = child_stream_continuity(child, duration_s)
    if cont_ok is None:
        return None, ATTRIB_UNKNOWN, ("no error_code on the wire (fw v21-v24 "
                                      "board) and %s" % cont_detail)
    if cont_ok:
        return "pi", ATTRIB_INFERRED, ("no error_code on the wire (fw v21-v24 "
                                       "board); INFERRED by elimination — %s, "
                                       "so a HIL-link explanation is "
                                       "implausible" % cont_detail)
    return None, ATTRIB_INFERRED, ("no error_code on the wire (fw v21-v24 "
                                   "board) and the stream was not continuous "
                                   "(%s) — cannot attribute" % cont_detail)


def analyze_scenario_csv(csv_path, grace_s=WARM_RESET_GRACE_S, survive_to_t=None):
    """Health metrics from a simulated-mode CSV.

    Observation columns are BLANK on every tick before the first observation
    frame arrives (hil_plant_sim's row writer), so 'n_obs' counts rows with a
    non-blank fault_flags — i.e. ticks the board actually answered.

    TWO FAULT UNIONS (2026-08-30, HIL_FINDINGS 'step-load'):

      fault_bits_seen        every bit observed anywhere in the run.  Kept, and
                             still reported verbatim in REPORT.md.
      fault_bits_post_grace  bits observed at t >= `grace_s` only.

    The distinction exists because from fw v23 the board WARM-RESETS out of the
    previous run's settle latch at t ~= 0.5 s (HIL_RECOVER_DEBOUNCE_MS), so every
    run after the first opens with 0x8010 — or 0x8011 / 0xA010 when its
    predecessor latched something of its own — through no fault of its own.  The
    whole-run union folded that in and 23 of 33 FAILs in the first fw v23 suite
    pass were that artefact.  `grace_s` is imported from hil_plant_sim
    (WARM_RESET_GRACE_S), the SAME bound judge_warm_resets() already used, so the
    two checks can no longer disagree by construction.

    SELF-GUARDING, deliberately: this excuses only bits that STOPPED.  A board
    that stays latched keeps reporting its flags after the grace bound and still
    fails — the exclusion is on the observation WINDOW, never on the bit values.

    `survive_to_t` (a scenario's FAULT_EXPECTATIONS['survive_to']['t']) adds two
    probes that need a single pass over the rows: `fault_bits_before_survive`
    (post-grace bits observed strictly before that time) and `state_at_survive`
    (mainState on the first observed row at or after it).

    TWO FIRST-SIGHTING MAPS, and they answer different questions (F1, 2026-08-31):

      fault_first_t            POST-GRACE first sighting. This is what
                               `not_before_s` is judged against, so it MUST be
                               post-grace-scoped. Consequence: for a fault that
                               latched inside the grace window and persisted, it
                               reports the GRACE BOUND, not the onset.
      fault_first_t_whole_run  first sighting anywhere in the run. Report-only —
                               no check reads it — and the honest answer to "when
                               did this actually happen?".

    Measured example, round-1 campaign 20260831_000518 (PRE-redesign stimulus —
    the timings moved on 2026-08-31, the illustration did not): scp-inrush's OC_FC
    cut is stamped t = 0.600 by its own `scp_cut` event, `fault_first_t` says 2.000371,
    and `fault_first_t_whole_run` says 0.600-ish. Quote the whole-run one to a
    reader; quote the post-grace one only when explaining a `not_before_s`
    verdict."""
    m = {"csv": csv_path, "rows": 0, "n_obs": 0, "final_fault_flags": None,
         "fault_bits_seen": 0, "fault_bits_post_grace": 0,
         "fault_first_t": {}, "fault_first_t_whole_run": {},
         # ── PART B1 (C1 round, 2026-09-01) ──────────────────────────────────
         # POST-GRACE first sighting of each bit ON A LATCHED ROW, i.e. with
         # FAULT_ERROR also set. This is the map `not_before_s` is judged
         # against. `fault_first_t` records the first BARE bit, which a
         # single-tick indication can set without any fault being declared, so
         # judging an absence assertion on it charges a stimulus with a
         # transient that triggerFault() never latched. The predicate here is
         # the same one the `fault_latch_bit` signal uses (`bits & FAULT_ERROR`
         # on the same row), so the two cannot drift.
         "fault_first_latch_t": {},
         "n_obs_post_grace": 0, "last_obs_t": None,
         "grace_s": grace_s, "survive_to_t": survive_to_t,
         "fault_bits_before_survive": 0, "state_at_survive": None,
         "final_state": None, "duration_s": None,
         "substep_hz_min": None, "substep_hz_mean": None, "error": None,
         # ── EMS COMPARISON SURFACE (2026-08-31) ─────────────────────────────
         # Two energy-accounting summaries, collected for ANY scenario whose CSV
         # carries the columns and left None for every scenario that does not.
         # Deliberately GENERIC and blank-tolerant rather than keyed to a
         # scenario name: `h2_cum_g` / `soc` are appended by hil_plant_sim.py in
         # simulated-plant mode, so every simulated scenario gets them for free
         # and a replay run (whose CSV has neither) gets None.
         #   final_h2_cum_g  last non-blank h2_cum_g. The column is a monotone
         #                   cumulative integral, so the last row IS the total.
         #                   ⚠️ This is the Gfc MODEL'S ESTIMATE of hydrogen
         #                   mass. The map is scale-portable; the stack is NOT
         #                   identified against this rig, TODO(calibrate)
         #                   (H2Consumption banner in hil_plant_sim.py). Quote
         #                   an absolute value with that caveat; a RANKING of
         #                   two runs on this rig is robust regardless.
         #   final_h2_sdp_cum_g  last non-blank h2_sdp_cum_g — the SAME total on
         #                   the STUDENT'S static-proxy model (P_fc/(0.5*120000),
         #                   SDP_EnergyManagement2.m), computed by
         #                   hil_plant_sim.py from the SAME P_fc input as
         #                   h2_cum_g. It exists so a number from this rig can be
         #                   read next to the student's SDP/DP work without
         #                   either side re-deriving the other's model.
         #                   ⚠️ IT IS A SECOND MODEL, NOT A SECOND MEASUREMENT:
         #                   the proxy under-reads Gfc by ~5.5 % at steady state
         #                   BY CONSTRUCTION (47.25 % vs 50 % assumed
         #                   efficiency), so the gap between the two columns is
         #                   arithmetic, never a finding. Rank runs on ONE axis.
         #   delta_soc       last soc minus first soc, i.e. how much charge the
         #                   run actually spent.
         # They exist so `ems-soc-band` (causal) and `ems-dp-replay` (the
         # NON-CAUSAL DP benchmark) can be read side by side in REPORT.md. Read
         # them as a PAIR: any strategy burns less hydrogen by discharging the
         # pack harder, so a hydrogen ranking is only valid at matched
         # delta_soc.
         "final_h2_cum_g": None, "final_h2_sdp_cum_g": None,
         # Hi-fi substep resolution (2026-09-02). None on a simple-engine run
         # and on every CSV that predates the `elec_substep_n` column.
         "substep_n_min": None, "substep_n_mean": None,
         "substep_n_below_gate": None, "substep_n_rows": None,
         "soc_first": None, "soc_last": None,
         "delta_soc": None,
         # ── LATCHED FIRST CAUSE, off the wire (fw v25, 2026-09-01) ──────────
         # `error_code` is observation-frame byte 16 (.ino:2968-2978): the
         # ErrorCode_t the board latched FIRST, which fault_flags structurally
         # cannot give, because triggerFault() only ORs bits there while bit
         # 0x0010 is shared by FAULT_PI_TIMEOUT and its alias FAULT_HIL_LINK.
         #   error_code_final       last non-blank value anywhere in the run.
         #   error_code_post_grace  last non-blank value at t >= grace_s. THIS
         #                          is what the discrimination reads, because
         #                          the fault union it accompanies is
         #                          post-grace-scoped too: a carried-in settle
         #                          latch clears on the warm reset, so a value
         #                          from inside the grace window belongs to the
         #                          PREVIOUS run.
         # BOTH are None on a fw v21-v24 board (whose 16/17-byte frame has no
         # such byte) and on a CSV written before the column existed. None means
         # UNKNOWN — never ERR_NONE, which is the legal value 0.
         "error_code_final": None, "error_code_post_grace": None}
    if not os.path.isfile(csv_path):
        m["error"] = "CSV not written"
        return m
    subs = []
    # `elec_substep_n` (2026-09-02, review PLANT-R1-F6): the SUBSTEP COUNT per
    # tick, which the rate column cannot substitute for. The count is wall-clock
    # adaptive, so a loaded host runs the node ODE coarser and nothing in the
    # trace said so; `substep_resolution` below judges the minimum.
    sub_n = []
    t_first = t_last = None
    # F1: separate accumulator for the whole-run first-sighting map — the
    # post-grace union cannot serve, since it is empty for every pre-grace row.
    _seen_for_first = 0
    try:
        with open(csv_path, newline="") as fh:
            for row in csv.DictReader(fh):
                m["rows"] += 1
                t = None
                try:
                    tv = float(row.get("t") or "nan")
                    if tv == tv:
                        t = tv
                        t_first = t if t_first is None else t_first
                        t_last = t
                except ValueError:
                    pass
                ff = (row.get("fault_flags") or "").strip()
                if ff:
                    m["n_obs"] += 1
                    try:
                        bits = int(ff, 0)
                    except ValueError:
                        continue
                    m["final_fault_flags"] = bits
                    m["fault_bits_seen"] |= bits
                    if t is not None:
                        m["last_obs_t"] = t
                    st = (row.get("state") or "").strip()
                    state = None
                    if st:
                        try:
                            state = int(st, 0)
                            m["final_state"] = state
                        except ValueError:
                            pass
                    # A row with no parseable `t` cannot be placed relative to the
                    # grace bound; treat it as PRE-grace (the conservative side —
                    # it is excluded from the post-grace union and so can never
                    # excuse a real in-run fault, only fail to accuse on one).
                    # F1 (2026-08-31): the WHOLE-RUN first sighting of each bit,
                    # unfiltered by the grace bound. `fault_first_t` below is
                    # post-grace-scoped by design (it feeds `not_before_s`, which
                    # judges the post-grace window), but that makes it report the
                    # GRACE BOUND as the onset time for any fault that latched
                    # inside the window and persisted: scp-inrush's OC_FC cut was
                    # measured at t = 0.600 by its own scp_cut event (PRE-redesign
                    # stimulus, 2026-08-31 — kept as the illustration), and
                    # `fault_first_t` says 2.000371 (round-1 campaign
                    # 20260831_000518). Both numbers are correct for their own
                    # question; only reporting the first one is what misleads.
                    if t is not None:
                        for b in _split_bits(bits & ~_seen_for_first):
                            m["fault_first_t_whole_run"].setdefault(fault_names(b), t)
                        _seen_for_first |= bits
                    post = t is not None and t >= grace_s
                    if post:
                        m["n_obs_post_grace"] += 1
                        new = bits & ~m["fault_bits_post_grace"]
                        m["fault_bits_post_grace"] |= bits
                        for b in _split_bits(new):
                            # L4: keyed by fault NAME, not by the raw int. This dict
                            # is serialized into results.json, where json.dump would
                            # stringify an int key to "1"/"256" — unreadable, and
                            # not round-trippable by a consumer that expects ints.
                            m["fault_first_t"].setdefault(fault_names(b), t)
                        # PART B1: the LATCHED first sighting. Populated only on
                        # a row that also carries FAULT_ERROR, and iterated over
                        # `bits` rather than `new` — a bit whose first BARE
                        # sighting was a transient must still be able to record
                        # its later latch.
                        if bits & FAULT_ERROR:
                            for b in _split_bits(bits & ~FAULT_ERROR):
                                m["fault_first_latch_t"].setdefault(
                                    fault_names(b), t)
                        if survive_to_t is not None:
                            if t < survive_to_t:
                                m["fault_bits_before_survive"] |= bits
                            elif m["state_at_survive"] is None and state is not None:
                                m["state_at_survive"] = state
                # fw v25 latched first cause. Read OUTSIDE the `if ff:` block
                # above on purpose: it is its own column with its own blankness,
                # and coupling it to fault_flags' presence would silently drop it
                # if the two ever diverge. Blank-tolerant like every observation
                # column; an unparseable cell is skipped, never zero-filled.
                ec = (row.get("error_code") or "").strip()
                if ec:
                    try:
                        ecv = int(ec, 0)
                        m["error_code_final"] = ecv
                        if t is not None and t >= grace_s:
                            m["error_code_post_grace"] = ecv
                    except ValueError:
                        pass
                s = (row.get("elec_substep_hz") or "").strip()
                if s:
                    try:
                        subs.append(float(s))
                    except ValueError:
                        pass
                sn = (row.get("elec_substep_n") or "").strip()
                if sn:
                    try:
                        sub_n.append(int(float(sn)))
                    except ValueError:
                        pass
                # EMS comparison surface. Blank-tolerant on purpose: a scenario
                # CSV without these columns leaves the metrics None, and a
                # single unparseable cell is skipped rather than aborting the
                # scan — these are REPORTING figures, and no check reads them,
                # so a malformed cell must never cost a run its verdict.
                h2 = (row.get("h2_cum_g") or "").strip()
                if h2:
                    try:
                        m["final_h2_cum_g"] = float(h2)
                    except ValueError:
                        pass
                # Same treatment for the student's-axis total: blank-tolerant,
                # absent on any CSV that predates the column (and on every
                # replay CSV), and read by NO check — a malformed cell must
                # never cost a run its verdict.
                h2s = (row.get("h2_sdp_cum_g") or "").strip()
                if h2s:
                    try:
                        m["final_h2_sdp_cum_g"] = float(h2s)
                    except ValueError:
                        pass
                sc = (row.get("soc") or "").strip()
                if sc:
                    try:
                        val = float(sc)
                        if m["soc_first"] is None:
                            m["soc_first"] = val
                        m["soc_last"] = val
                    except ValueError:
                        pass
    except OSError as exc:
        m["error"] = str(exc)
        return m
    if t_first is not None and t_last is not None:
        m["duration_s"] = t_last - t_first
    if m["soc_first"] is not None and m["soc_last"] is not None:
        m["delta_soc"] = m["soc_last"] - m["soc_first"]
    if subs:
        m["substep_hz_min"] = min(subs)
        m["substep_hz_mean"] = sum(subs) / len(subs)
    if sub_n:
        m["substep_n_min"] = min(sub_n)
        m["substep_n_mean"] = sum(sub_n) / float(len(sub_n))
        # How many ticks ran below the gate, so a single coarse tick reads
        # differently from a host that was loaded throughout.
        m["substep_n_below_gate"] = sum(1 for n in sub_n
                                        if n < SUBSTEP_N_MIN_GATE)
        # The denominator the SUSTAINED-collapse test needs (2026-09-02, review
        # M1): "below the gate on 2 of 310 000 ticks" and "below the gate
        # throughout" are different findings, and only the second one is a
        # verdict about the run.
        m["substep_n_rows"] = len(sub_n)
    return m


# ─────────────────────────────────────────────────────────────────────────────
# signals_require — POSITIVE trace assertions (review M2)
#
# Each spec is a dict.  Exactly one assertion kind per spec:
#
#   {"switch_bit": MASK, "min_ticks": N}   the switch_state bit must be SET on at
#                                          least N observed ticks
#   {"switch_bit": MASK, "max_ticks": N}   ... on at most N (used to assert a
#                                          switch was OPENED and stayed open)
#   {"column": "I_charge", "min_value": X} some sample must reach >= X
#   {"column": "V_bus", "max_value": X}    NO sample may exceed X — a CEILING
#                                          (2026-08-31; the events spec has had
#                                          one since the scp band, the signals
#                                          side had only floors, so "the current
#                                          tapered" was unassertable)
#   {"column": "soc", "strictly_decreases_by": X}  last - first <= -X
#   {"fault_latch_bit": MASK, "after_t": T}  some row at t >= T shows
#                                          fault_flags & MASK AND & FAULT_ERROR
#                                          (the LATCH rule — a transient bare bit
#                                          does not count, matching the replay
#                                          half's latch semantics)
#
# ── 2026-08-31 additions ────────────────────────────────────────────────────
#   {"aux_bit": MASK, "min_ticks"/"max_ticks": N}
#       The `aux` column's exact analogue of switch_bit.  The aux byte carries
#       FC_REG_ENABLE / BT_REG_ENABLE / MPPT_DISABLE / CBAL_DISABLE (.ino:2823),
#       and MPPT_DISABLE (AUX_MPPT_DISABLE 0x04) had no way to be asserted at all
#       before this kind existed.
#
#   {"column": "ag105_status", "value_mask": M, "value_equals": V,
#    "min_ticks"/"max_ticks": N}
#       Masked-INTEGER equality: count ticks where (int(cell, 0) & M) == V.
#       ⚠️ THE TRAP THIS CLOSES, documented because it was latent rather than
#       hypothetical: `ag105_status` is written as a HEX STRING ("0x42"), so the
#       generic column path's float() raises ValueError and the sample is
#       skipped — SILENTLY.  A `min_value` spec on that column therefore measured
#       nothing at all and reported "peak unmeasured", which reads as a board
#       finding.  Any masked field (GENSTAT bits 0-2, the flag bits 3-7) needs
#       this kind, not min_value.
#
#   {"switch_bit"|"aux_bit": MASK, "after_t": T, "max_ms": X, "edge": "fall"}
#       switch_fall_latency_ms — LATENCY MEASUREMENT.  `max_ms` is the kind's
#       DISCRIMINATOR (no other kind carries it); there is no key literally named
#       switch_fall_latency_ms.  Records the first
#       1 -> 0 transition at or after T (or 0 -> 1 with "edge": "rise") and
#       asserts (t_edge - T)*1000 <= X.
#       ⚠️ THE MEASURED LATENCY IS THE DELIVERABLE; the gate is a REGRESSION
#       TRIPWIRE.  The value is printed into the check detail on pass AND on
#       fail, so a campaign can track the distribution.  NEVER raise `max_ms` to
#       make a run go green — a latency that outgrew its bound is the finding.
#       The window must OPEN BEFORE T so the pre-edge level is established; an
#       edge before T is ignored (`prev_bit` still tracks it, so a switch that
#       was already low at T yields "no transition", not a spurious 0 ms).
#
# ── 2026-09-01 additions (campaign 024231 calibration round) ────────────────
#   {"switch_bit"|"aux_bit"|"column"+value_mask: ..., "max_continuous_ticks": N}
#       The LONGEST CONTINUOUS RUN of set/matching ticks in the window must be
#       <= N.  ⚠️ WHY IT EXISTS, because it is the lesson of the one FAIL of
#       campaign 20260901_024231: `sdpx_charge_released_between` asserted the
#       ABSENCE of a charge window over a MODELLED instant (t = 90..108 s, from
#       an offline walk's ~52 s limit-cycle period).  The board's real period is
#       16.13 s, so the assertion sat on top of a window and failed a correct
#       run.  A longest-run bound expresses the same objective — "the dwell
#       latch is a hysteresis, not a hold-forever" — WITHOUT claiming to know
#       the phase.  Prefer it over any windowed absence assertion whenever the
#       property is "no single episode may last longer than X".
#       A BLANK row neither extends nor breaks a run (it carries no level), so a
#       dropped observation frame cannot split one hold into two.
#       Vacuity-prone in the same way `max_ticks` is (a blank column has a
#       longest run of zero), so it obeys the same companion rule below.
#
#   {"switch_bit"|"aux_bit": MASK, "edge_count_between": (LO, HI),
#    "edge": "rise"|"fall"}
#       EDGE CENSUS — the number of qualifying transitions in the window must be
#       in the INCLUSIVE band [LO, HI].  The band is ONE key on purpose: a spec
#       carrying two bound keys silently drops one (see the min_value+max_value
#       guard), and a count deserves one verdict.  Default edge is "rise".
#       The first in-window sample only ESTABLISHES the level, so a window that
#       opens with the bit already set does not count a phantom edge — the count
#       is of transitions observed, never of windows inferred.
#
# ── 2026-09-01 additions (campaign 080905 fix batch) ────────────────────────
#   {"column": C, "column_range_at_least": N}
#       COLUMN MOTION: (max - min) over the window must be >= N.  PHASE-FREE and,
#       critically, NOT INHERITABLE.
#       ⚠️ WHY IT EXISTS (F1).  `mppt_threshold_written` asserted a LEVEL — "bit
#       7 of mppt_thresh_cnt was clear for N ticks" — on a value the board
#       CARRIES ACROSS RUNS: ag105MpptRegCnt and the Ag105's own EPROM both
#       persist through the unpowered gaps (.ino:10769-10775).  A run in which
#       the threshold manager never executed therefore passed on the PREVIOUS
#       run's written count.  A RANGE cannot be inherited: a carried-in constant
#       has range 0, and only a write inside this window moves it.  Use this
#       kind for any assertion of the form "the firmware ACTED", where the
#       observable is a persistent state rather than an event.
#       UNMEASURED (fewer than one parseable sample) fails.
#
#   {"column": C, "floor_min_value": X}
#       FLOOR ON THE IN-WINDOW MINIMUM, the mirror of `max_value`.
#       ⚠️ WHY IT EXISTS (F2).  `min_value` judges the PEAK, i.e. "some sample
#       reached X".  That is right for an EVENT and wrong for an INVARIANT:
#       `mppt_threshold_floor` asked "the count never went below the clamp
#       floor" and was written with `min_value`, so it passed on a single sample
#       at or above the floor while every other sample sat under it — vacuously
#       true for any column whose peak clears the bound.  This kind fails on a
#       single excursion below X.  Choose by the question: `min_value` for "did
#       it ever reach", `floor_min_value` for "did it never fall below".
#       UNMEASURED fails, same rule as `max_value`.
#
# ── ENTRY-LEVEL (not a signals_require spec) ────────────────────────────────
#   FAULT_EXPECTATIONS[name]["child_tx_healthy"] = True
#       Asserts the shared 0x0010 bit is attributable to the PI WATCHDOG, for
#       scenarios whose OBJECTIVE is a command-side fault.  Judged by
#       attribute_shared_0x8010(): on a fw v25 board it READS the latched
#       first cause off observation-frame byte 16 (ERR_PI_TIMEOUT 0x05 vs
#       ERR_HIL_STALE 0x10); on a fw v21-v24 board it falls back to the
#       pre-v25 inference by elimination — child_stream_continuity() (tx >=
#       98 % of full rate, zero send errors) — and the detail line says which
#       decided.  UNMEASURED and UNATTRIBUTABLE both render as a FAILED check
#       with an explicit reason, never as a silent pass.  The check name
#       predates the wire reading and is kept so campaign ledgers compare.
#
# DISJUNCTIVE SPEC (A1, 2026-08-30):
#   {"name": ..., "any_of": [<subspec>, <subspec>, ...], "label": ...}
# passes when ANY arm passes, and its detail reports EVERY arm's measurement plus
# which one satisfied it.  Introduced because soc-depletion's objective —
# "the pack demonstrably walked down" — has two mutually-exclusive-in-practice
# proofs: a large enough SoC fall, OR a UV_BATT latch, which is the stronger
# evidence but FORECLOSES the fall by ending the run.  A single-arm spec had to
# pick one and was unreachable either way.
#
# Optional on any spec (including each arm): "t_window": (t0, t1) — restrict to
# that SIM-time window (t1 may be None for "to the end"), and "label": human text
# for the report.  Every spec is judged only on rows at or after the grace bound,
# for the same reason the fault checks are: the pre-grace window belongs to the
# previous run.
#
# scan_signals() and judge_signals() are and must stay PURE over their inputs
# (scan reads the CSV; judge does no I/O at all).
# ─────────────────────────────────────────────────────────────────────────────

def _flatten_signal_specs(specs):
    """(spec, arms) per top-level spec, where `arms` is its `any_of` list or [].

    The scanner needs a FLAT list of leaf specs to measure in one pass; the judge
    needs the tree back.  One helper so the two cannot disagree about the shape."""
    return [(s, list(s.get("any_of") or [])) for s in specs]


def _leaf_signal_specs(specs):
    """Every leaf spec, in the order scan_signals() measures them."""
    leaves = []
    for spec, arms in _flatten_signal_specs(specs):
        leaves.extend(arms or [spec])
    return leaves


def scan_signals(csv_path, specs, grace_s=WARM_RESET_GRACE_S):
    """One pass over the CSV collecting exactly what `specs` needs.

    Returns a list parallel to `specs` of measurement dicts; judge_signals() turns
    those into checks.  A DISJUNCTIVE spec (`any_of`) measures each arm and returns
    {"any_of": [<arm measurement>, ...]} in that spec's slot, so the return value
    stays parallel to `specs` either way.  Kept separate from
    analyze_scenario_csv() so a scenario with no signals_require pays nothing."""
    def _blank():
        return {"ticks": 0, "peak": None, "first": None, "last": None, "rows": 0,
                "latch_t": None,
                # `trough` is the in-window MINIMUM, the mirror of `peak`
                # (2026-09-01, F1/F2).  Two kinds read it: `floor_min_value`
                # (which judges the minimum, where `min_value` judges the peak
                # and is therefore vacuously true for any column that touches
                # its floor once) and `column_range_at_least` (peak - trough).
                "trough": None,
                # switch_fall_latency_ms state: the last observed level of the
                # watched bit (None until a non-blank row is seen — so an edge is
                # only ever recorded against a KNOWN previous level) and the sim
                # time of the first qualifying transition.
                "prev_bit": None, "edge_t": None,
                # `max_continuous_ticks` state (2026-09-01): `run` is the run
                # LENGTH in progress, `max_run` the longest one seen.  A BLANK
                # row neither extends nor breaks a run — it carries no level, so
                # treating it as a break would report a hold as two shorter ones
                # every time an observation frame was dropped.
                "run": 0, "max_run": 0,
                # `exempt_values` state (2026-09-03, the MPC 0/1 round): how
                # many samples were EXCLUDED from the value bounds because they
                # matched a declared exempt value exactly.  Reported on every
                # verdict of a spec that declares them, so an exemption can
                # never quietly hide a population.
                "exempt": 0,
                # `edge_count_between` state: how many qualifying transitions the
                # window contained.  Counted against `prev_bit`, exactly as the
                # latency kind does, so a blank row cannot forge an edge.
                "edges": 0,
                # `exclude_hold_ms` state (2026-09-02, review H1): the sim time
                # of the LAST row on which the `exclude_when_switch_bit` mask
                # was set.  The settling hold is measured from it, so the mask
                # keeps excluding rows for `exclude_hold_ms` after the bit
                # clears.  None until the bit has been seen set at all — a run
                # whose masked branch never opened gets no exclusion.
                "mask_last_set_t": None,
                # `reach_within_ms` state (2026-09-03): the sim time of the
                # first sample at or above the spec's `min_value` at or after
                # the watched bit's rising edge (`edge_t`).  None until that
                # happens, which is what "never reached the band" reports.
                "reach_t": None}

    _thr_cache = {}

    def _record_value(spec, m, v):
        """Fold ONE numeric sample into a leaf measurement.

        Peak/trough/first/last, and — new 2026-09-02, fix-queue item 2 — the
        THRESHOLD TICK COUNTER.  `ticks`/`run`/`max_run` used to be touched only
        by the switch_bit / aux_bit / value_mask paths, so a spec pairing a
        numeric `min_value` with `min_ticks` (the `regen_clamp_dwell` dwell
        check) read a counter that was structurally zero and failed a run whose
        physics passed with 1173 continuous ticks against a floor of 800.  The
        threshold is the spec's own value bound: `min_value` counts samples at
        or above it, `max_value` samples at or below it.  A spec with neither
        counts nothing, and the import guard refuses that pairing."""
        if m["peak"] is None or v > m["peak"]:
            m["peak"] = v
        if m["trough"] is None or v < m["trough"]:
            m["trough"] = v
        if m["first"] is None:
            m["first"] = v
        m["last"] = v
        # Resolved ONCE per leaf (`_thr_cache`), not per row: this runs on every
        # sample of every spec, and a 350 s FTP-75 CSV is ~350 000 rows.
        thr = _thr_cache.get(id(spec), False)
        if thr is False:
            thr = _threshold_of(spec)
            _thr_cache[id(spec)] = thr
        if thr is None:
            return
        kind, bound = thr
        hit = (v >= bound) if kind == "min_value" else (v <= bound)
        if hit:
            m["ticks"] += 1
            m["run"] += 1
            if m["run"] > m["max_run"]:
                m["max_run"] = m["run"]
        else:
            m["run"] = 0

    tree = _flatten_signal_specs(specs)
    leaves = _leaf_signal_specs(specs)
    leaf_m = [_blank() for _ in leaves]

    def _nest():
        out, i = [], 0
        for spec, arms in tree:
            if arms:
                out.append({"any_of": leaf_m[i:i + len(arms)]})
                i += len(arms)
            else:
                out.append(leaf_m[i])
                i += 1
        return out

    if not specs or not os.path.isfile(csv_path):
        return _nest()
    try:
        with open(csv_path, newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    t = float(row.get("t") or "nan")
                except ValueError:
                    continue
                if t != t or t < grace_s:
                    continue
                for spec, m in zip(leaves, leaf_m):
                    w = spec.get("t_window")
                    if w and (t < w[0] or (w[1] is not None and t > w[1])):
                        continue
                    if "fault_latch_bit" in spec:
                        # A1: the LATCH rule — the named bit AND FAULT_ERROR, on
                        # the SAME row, at or after `after_t`.  A bare transient
                        # indication is deliberately not enough; this mirrors
                        # hil_replay_suite's check_fault_latched semantics.  Rows
                        # before `after_t` are counted in `rows` (so "no rows to
                        # judge" still means what it says) but never latch.
                        m["rows"] += 1
                        if t < float(spec.get("after_t", 0.0)):
                            continue
                        cell = (row.get("fault_flags") or "").strip()
                        if not cell:
                            continue
                        try:
                            bits = int(cell, 0)
                        except ValueError:
                            continue
                        if (bits & int(spec["fault_latch_bit"])) and (bits & FAULT_ERROR):
                            if m["latch_t"] is None:
                                m["latch_t"] = t
                        continue
                    m["rows"] += 1
                    # ── SETTLING MEASUREMENT: `reach_within_ms` ──────────────
                    # (2026-09-03, campaign E fix round, item 2.)  THE ONLY
                    # KIND THAT READS TWO COLUMNS ON ONE ROW, and it has to:
                    # the question is "how long after the mechanism ENGAGED did
                    # the current reach its band", and the engagement instant is
                    # the aux bit's rising edge, not the commanded step.  The
                    # two are different numbers on this board - the commanded
                    # step reaches the firmware a Pi cadence period late
                    # (3.3 - 17.7 ms measured, campaign E), and folding that
                    # into the settling figure measures the LINK, not the clamp.
                    # The reference instant is therefore MEASURED, not assumed.
                    if "reach_within_ms" in spec:
                        bcol = ("switch" if "switch_bit" in spec else "aux")
                        cell = (row.get(bcol) or "").strip()
                        if cell:
                            try:
                                bits = int(cell, 0)
                            except ValueError:
                                bits = None
                            if bits is not None:
                                cur = 1 if (bits & _resolve_bit_mask(spec)) else 0
                                if (m["edge_t"] is None
                                        and m["prev_bit"] is not None
                                        and m["prev_bit"] == 0 and cur == 1):
                                    m["edge_t"] = t
                                m["prev_bit"] = cur
                        if m["edge_t"] is not None and m["reach_t"] is None:
                            raw = (row.get(spec["column"]) or "").strip()
                            if raw:
                                try:
                                    val = float(raw)
                                except ValueError:
                                    val = None
                                if val is not None:
                                    if val >= float(spec["min_value"]):
                                        m["reach_t"] = t
                                    if m["peak"] is None or val > m["peak"]:
                                        m["peak"] = val
                        continue
                    # ── bit-valued specs: switch_state or the aux byte ────────
                    # ONE source resolution for all three bit kinds, so a spec
                    # cannot mean a different column depending on which
                    # assertion it carries.
                    bit_col = ("switch" if "switch_bit" in spec else
                               "aux" if "aux_bit" in spec else None)
                    if bit_col is not None:
                        cell = (row.get(bit_col) or "").strip()
                        if not cell:
                            # Pre-observation tick: no level to read.  Do NOT
                            # touch prev_bit — a blank must not look like a level
                            # change to the latency kind.
                            continue
                        try:
                            bits = int(cell, 0)
                        except ValueError:
                            continue
                        mask = _resolve_bit_mask(spec)
                        cur = 1 if (bits & mask) else 0
                        # The latency kind is selected by `max_ms`, which no other
                        # kind carries.  (There is no "switch_fall_latency_ms"
                        # KEY — that is the kind's NAME; `max_ms` is what a spec
                        # actually declares, and it is the field that makes the
                        # spec a latency measurement rather than a tick count.)
                        if "max_ms" in spec:
                            want = 0 if spec.get("edge", "fall") == "fall" else 1
                            if (m["edge_t"] is None and m["prev_bit"] is not None
                                    and m["prev_bit"] != cur and cur == want
                                    and t >= float(spec.get("after_t", 0.0))):
                                m["edge_t"] = t
                            m["prev_bit"] = cur
                        elif "edge_count_between" in spec:
                            # EDGE CENSUS (2026-09-01).  Counts qualifying
                            # transitions inside the window; the FIRST in-window
                            # sample establishes the level and can never be an
                            # edge, so a window that opens with the bit already
                            # set counts that window, not a phantom edge.
                            want = 1 if spec.get("edge", "rise") == "rise" else 0
                            if (m["prev_bit"] is not None
                                    and m["prev_bit"] != cur and cur == want):
                                m["edges"] += 1
                            m["prev_bit"] = cur
                        else:
                            m["ticks"] += cur
                            if cur:
                                m["run"] += 1
                                if m["run"] > m["max_run"]:
                                    m["max_run"] = m["run"]
                            else:
                                m["run"] = 0
                        continue
                    # ── TICK MASK (2026-09-02): `exclude_when_switch_bit` ────
                    # Drops rows on which a named switch bit is SET, before any
                    # value is read.  It exists because a single peak bound on
                    # I_fc has to answer two different questions on the FTP-75
                    # `soc-band` leg: what the SHARE LOOP does (a tripwire on the
                    # operating point) and what the FC channel carries while it
                    # is ALSO feeding the charger (a much larger, sourced
                    # number).  One ceiling cannot do both — campaign
                    # 20260902_011926 failed the 0.85 A tripwire on a 1.1370 A
                    # peak that decomposed exactly into motor + aux + charger bus
                    # draw, i.e. on correct behaviour.
                    # A row whose switch cell is BLANK or unparseable is dropped
                    # too: the mask cannot be evaluated there, and counting the
                    # row would be asserting the bit was clear.
                    # ── SETTLING HOLD (2026-09-02, review H1) ────────────────
                    # `exclude_hold_ms` (default 0) keeps excluding rows until
                    # the masked bit has been clear for that long.  The bit is a
                    # COMMAND edge, the current it gates is a PHYSICAL decay: on
                    # the FTP-75 `soc-band` leg the FC channel is still carrying
                    # the charger's bus draw ~10 ms after FC_CHARGE_ENABLE
                    # clears, so the first charge-free sample after a close is
                    # 0.83-0.86 A on 3 of 5 closes — contaminated in exactly the
                    # way the mask exists to prevent, and enough to false-fail
                    # the 0.85 A tripwire on a correct board.  The hold is
                    # measured from the LAST row the bit was set on, so a
                    # chattering branch never leaks a partially-decayed sample.
                    if "exclude_when_switch_bit" in spec:
                        _sw_cell = (row.get("switch") or "").strip()
                        if not _sw_cell:
                            continue
                        try:
                            _sw = int(_sw_cell, 0)
                        except ValueError:
                            continue
                        if _sw & int(spec["exclude_when_switch_bit"]):
                            m["mask_last_set_t"] = t
                            continue
                        _hold = float(spec.get("exclude_hold_ms", 0.0))
                        if (_hold > 0.0 and m["mask_last_set_t"] is not None
                                and (t - m["mask_last_set_t"]) <= _hold / 1000.0):
                            continue
                    # ── DERIVED SCALARS (2026-08-31): `sum_of` / `ratio_of` ──
                    # Some quantities the campaign reasons in are not CSV
                    # columns: the source total I_tot = I_fc + I_batt, and the
                    # DELIVERED share share_act = I_fc / I_tot. Both were being
                    # asserted only indirectly, through per-channel current
                    # floors that move whenever the load does — so a check
                    # written to pin "the board delivered 0.70" had to be
                    # written as "I_fc exceeded 0.74 A", which a load change
                    # falsifies for reasons that have nothing to do with the
                    # share loop.
                    #   sum_of:   [c0, c1, ...]  -> sum of the columns
                    #   ratio_of: [c0, c1, ...]  -> c0 / sum(all of them)
                    # Both feed the ordinary peak/first/last machinery, so
                    # min_value / max_value / strictly_decreases_by all apply
                    # unchanged. A row with ANY named column blank or
                    # unparseable is skipped whole — a partial sum is not a
                    # smaller sum, it is a different quantity.
                    # `ratio_min_den` (default 0.05 A) skips rows whose
                    # denominator is too small for the ratio to mean anything;
                    # it is the same 50 mA mask hil_report_analysis.py uses to
                    # derive share_act, kept identical on purpose.
                    if "sum_of" in spec or "ratio_of" in spec:
                        cols = spec.get("sum_of") or spec["ratio_of"]
                        vals = []
                        for c in cols:
                            cell = (row.get(c) or "").strip()
                            if not cell:
                                break
                            try:
                                vals.append(float(cell))
                            except ValueError:
                                break
                        if len(vals) != len(cols):
                            continue
                        if "sum_of" in spec:
                            v = sum(vals)
                        else:
                            den = sum(vals)
                            if abs(den) < float(spec.get("ratio_min_den", 0.05)):
                                continue
                            v = vals[0] / den
                        _record_value(spec, m, v)
                        continue
                    cell = (row.get(spec.get("column", "")) or "").strip()
                    if not cell:
                        continue
                    if "value_mask" in spec:
                        # Masked-INTEGER equality (e.g. ag105_status GENSTAT).
                        # int(cell, 0) so the column's "0x42" hex form parses;
                        # a decimal column parses identically.
                        try:
                            iv = int(cell, 0)
                        except ValueError:
                            continue
                        if (iv & int(spec["value_mask"])) == int(spec["value_equals"]):
                            m["ticks"] += 1
                            m["run"] += 1
                            if m["run"] > m["max_run"]:
                                m["max_run"] = m["run"]
                        else:
                            m["run"] = 0
                        continue
                    try:
                        v = float(cell)
                    except ValueError:
                        continue
                    # ── `exempt_values` (2026-09-03) ─────────────────────────
                    # A list of values a numeric bound does NOT apply to,
                    # matched within `exempt_tol` (default 1e-9).  It exists for
                    # one situation: a column whose legal alphabet is an
                    # INTERVAL plus a few DISCRETE points outside it.  The MPC's
                    # commanded share is that column - the ladder spans
                    # [0.15, 0.85] and the single-source candidates command
                    # exactly 0.0 or exactly 1.0, which are legal commands and
                    # not band excursions.  The exempt sample is counted and
                    # reported, so "the share left the band" and "the controller
                    # went single-source N times" stay distinguishable.
                    _ex = spec.get("exempt_values")
                    if _ex:
                        _tol = float(spec.get("exempt_tol", 1e-9))
                        if any(abs(v - float(x)) <= _tol for x in _ex):
                            m["exempt"] += 1
                            continue
                    _record_value(spec, m, v)
    except OSError as exc:
        for m in leaf_m:
            m["error"] = str(exc)
    return _nest()


def _judge_signal_leaf(spec, m):
    """(passed, measurement_text) for ONE leaf spec.  Pure.

    The text is the measurement without the surrounding label/`why`, so a
    disjunctive spec can report every arm's number in one detail line."""
    win = ("" if not spec.get("t_window") else
           " in t=[%s, %s]s" % (spec["t_window"][0],
                                spec["t_window"][1]
                                if spec["t_window"][1] is not None else "end"))
    if m.get("error"):
        return False, "could not read the CSV: %s" % m["error"]
    # `exempt_values` (2026-09-03): appended to whatever measurement text the
    # kind below produces, so a reader always sees how many samples the bound
    # was NOT applied to.  Empty when the spec declares no exemptions.
    _exn = m.get("exempt", 0) if spec.get("exempt_values") else 0
    _extx = ("" if not spec.get("exempt_values") else
             " [%d sample(s) exempt at %s]"
             % (_exn, "/".join("%g" % float(x)
                               for x in spec["exempt_values"])))
    if not m["rows"]:
        return False, ("no observed rows%s — the window this arm lives in was "
                       "never reached" % win)
    if "exempt_min_count" in spec:
        # `exempt_min_count` (2026-09-03, review LOW-4): a FLOOR on the exempt
        # tally itself.  `exempt_values` alone bounds nothing - a leg could
        # exempt zero samples and every band arm would still pass, so a run in
        # which the feature never fired would read exactly like one in which it
        # fired constantly.  This arm makes that difference legible.  It is
        # registered INFORMATIONAL on its first leg: a controller declining
        # every single-source candidate is a legitimate outcome of the
        # rollout-time guard, not a board defect.
        need = int(spec["exempt_min_count"])
        return (_exn >= need,
                "%d sample(s) at %s%s, need >= %d"
                % (_exn, "/".join("%g" % float(x)
                                  for x in spec.get("exempt_values", ())),
                   win, need))
    if "reach_within_ms" in spec:
        # SETTLING MEASUREMENT (2026-09-03).  Like the latency kind, the NUMBER
        # is the deliverable and is printed on both outcomes so a campaign can
        # track its distribution; the bound is a regression tripwire and must
        # never be raised to make a run pass.  Unlike the latency kind, the
        # reference instant is MEASURED (the watched bit's rising edge) rather
        # than declared, so the figure is the mechanism's own settling and does
        # not carry the Pi command cadence.
        lim = float(spec["reach_within_ms"])
        t_edge, t_reach = m.get("edge_t"), m.get("reach_t")
        if t_edge is None:
            return False, ("the watched bit never rose%s, so there is no "
                           "instant to measure the settling FROM" % win)
        if t_reach is None:
            return False, ("%s never reached %g after the bit rose at "
                           "t=%.4f s%s (peak %s) — tripwire <= %g ms"
                           % (spec.get("column"), float(spec["min_value"]),
                              t_edge, win,
                              "n/a" if m.get("peak") is None
                              else "%.4f" % m["peak"], lim))
        ms = (t_reach - t_edge) * 1000.0
        return (ms <= lim,
                "MEASURED settling %.2f ms (%s reached %g at t=%.4f s, bit rose "
                "at t=%.4f s)%s, tripwire <= %g ms"
                % (ms, spec.get("column"), float(spec["min_value"]), t_reach,
                   t_edge, win, lim))
    if "max_ms" in spec:
        # LATENCY MEASUREMENT (the "switch_fall_latency_ms" kind; `max_ms` is its
        # discriminator — no other kind carries it).  The number is the
        # deliverable and is printed on BOTH outcomes so a campaign can track its
        # distribution; the bound is a regression tripwire and must never be
        # raised to make a run pass.
        after = float(spec.get("after_t", 0.0))
        want = spec.get("edge", "fall")
        lim = float(spec["max_ms"])
        t_edge = m.get("edge_t")
        if t_edge is None:
            return False, ("no %s transition at or after t=%g s%s (last observed "
                           "level: %s) — need one within %g ms"
                           % (want, after, win,
                              "unknown" if m.get("prev_bit") is None
                              else ("HIGH" if m["prev_bit"] else "LOW"), lim))
        lat_ms = (t_edge - after) * 1000.0
        return (lat_ms <= lim,
                "MEASURED %s latency %.2f ms (edge at t=%.4f s, stimulus t=%g s)"
                "%s, tripwire <= %g ms" % (want, lat_ms, t_edge, after, win, lim))
    # Wording follows the KIND: a bit spec counts ticks the bit was SET, a
    # value_mask spec counts ticks the masked field MATCHED.  Same arithmetic,
    # and saying "bit set" about a GENSTAT equality would be wrong.
    # A NUMERIC THRESHOLD spec (2026-09-02) counts samples on the right side of
    # its own value bound, so it must say the bound — "bit set on 0 ticks" was
    # the wording the structurally-zero counter printed for `regen_clamp_dwell`,
    # and it named neither the column nor the threshold that was actually meant.
    _thr = _threshold_of(spec)
    if _thr is not None:
        what = ("value %s %g on"
                % (">=" if _thr[0] == "min_value" else "<=", _thr[1]))
    elif "value_mask" in spec:
        what = "masked value matched on"
    else:
        what = "bit set on"
    if "max_continuous_ticks" in spec:
        # LONGEST CONTINUOUS RUN (2026-09-01).  A TOTAL tick bound cannot tell a
        # limit cycle from one long hold, and a windowed absence assertion —
        # `sdpx_charge_released_between`, the check this kind replaces — pins a
        # release to a MODELLED INSTANT and fails a correct board the moment the
        # walk's period is wrong (campaign 024231: the walk was wrong by 5.7x).
        # The longest run is PHASE-FREE: it bounds the hold without claiming to
        # know when the releases happen.
        lim = int(spec["max_continuous_ticks"])
        have = int(m.get("max_run", 0))
        kind = ("in-threshold" if _thr is not None
                else "matching" if "value_mask" in spec else "set")
        return (have <= lim,
                "longest CONTINUOUS run %d %s tick(s)%s (%d %s in total), "
                "need <= %d" % (have, kind, win, m["ticks"], kind, lim))
    if "edge_count_between" in spec:
        # EDGE CENSUS, an INCLUSIVE band in ONE spec.  Written as a single
        # `(lo, hi)` key rather than min/max siblings for the reason the
        # min_value+max_value guard exists: two bound keys in one spec silently
        # drop one of them, and a count wants ONE verdict, not two.
        lo, hi = (int(v) for v in spec["edge_count_between"])
        which = spec.get("edge", "rise")
        n = int(m.get("edges", 0))
        return (lo <= n <= hi,
                "counted %d %s edge(s)%s, need %d..%d inclusive"
                % (n, which, win, lo, hi))
    if "min_rows" in spec:
        # CADENCE / SAMPLE CENSUS (B-M2, 2026-09-01).  Counts OBSERVED ROWS in
        # the window, not matching ticks — it asserts the run produced samples
        # there at all, i.e. that the 1 kHz injection loop did not stall.
        #
        # It exists because a stalled host is INVISIBLE to every value kind: the
        # firmware holds the last injected value for HIL_STALE_MS (50 ms), so a
        # stall inside a short stimulus window silently LENGTHENS the delivered
        # stimulus while the CSV simply has fewer rows.  The resulting verdict
        # then reads as a board finding.  A row census turns that into
        # "stimulus not delivered", which is what it is.
        #
        # No column is needed and none is read: `rows` is incremented for every
        # in-window row before any column is touched.
        return (m["rows"] >= int(spec["min_rows"]),
                "observed %d row(s)%s, need >= %d (a shortfall means the 1 kHz "
                "injection loop stalled, so the stimulus this window carries "
                "was not delivered as specified)"
                % (m["rows"], win, int(spec["min_rows"])))
    if "min_ticks" in spec:
        return (m["ticks"] >= int(spec["min_ticks"]),
                "%s %d tick(s)%s, need >= %d"
                % (what, m["ticks"], win, int(spec["min_ticks"])))
    if "max_ticks" in spec:
        return (m["ticks"] <= int(spec["max_ticks"]),
                "%s %d tick(s)%s, need <= %d"
                % (what, m["ticks"], win, int(spec["max_ticks"])))
    if "column_range_at_least" in spec:
        # COLUMN MOTION, PHASE-FREE (F1, 2026-09-01).  peak - trough over the
        # window.  It exists because a LEVEL check on a value the board CARRIES
        # ACROSS RUNS passes on a carried-in reading: mppt_thresh_cnt persists
        # in the Ag105's EPROM and in ag105MpptRegCnt across the unpowered gaps
        # (.ino:10769-10775), so "bit 7 was clear for N ticks" is satisfied by a
        # threshold the PREVIOUS run wrote and this one never touched.  A RANGE
        # cannot be inherited: it is zero unless the column actually moved
        # inside this window, which only the manager writing can do.
        need = float(spec["column_range_at_least"])
        # .get(): a hand-built measurement dict from before this kind existed
        # has no `trough`, and "unmeasured" is the right reading of its absence.
        hi, lo = m.get("peak"), m.get("trough")
        rng = None if (hi is None or lo is None) else hi - lo
        return (rng is not None and rng >= need,
                "range %s%s (min %s, max %s), need >= %g"
                % ("unmeasured" if rng is None else "%.4f" % rng, win,
                   "n/a" if lo is None else "%.4f" % lo,
                   "n/a" if hi is None else "%.4f" % hi, need))
    if "floor_min_value" in spec:
        # FLOOR ON THE MINIMUM (F2, 2026-09-01).  `min_value` judges the PEAK —
        # "the column reached X at least once" — which is the right question for
        # an event ("charge current was delivered") and the WRONG one for an
        # invariant ("the count never went below the clamp floor").  A column
        # whose peak clears the bound is scored as passing even while it spends
        # the whole window under it.  This kind judges the in-window MINIMUM, so
        # a single excursion below the bound fails.  UNMEASURED fails, same rule
        # as max_value: a window with no parseable samples has proved nothing.
        lo = m.get("trough")   # absent == unmeasured, see column_range_at_least
        return (lo is not None and lo >= float(spec["floor_min_value"]),
                "minimum %s%s, need >= %g%s"
                % ("unmeasured" if lo is None else "%.4f" % lo, win,
                   float(spec["floor_min_value"]), _extx))
    if "min_value" in spec:
        peak = m["peak"]
        return (peak is not None and peak >= float(spec["min_value"]),
                "peak %s%s, need >= %g"
                % ("unmeasured" if peak is None else "%.4f" % peak, win,
                   float(spec["min_value"])))
    if "max_value" in spec:
        # CEILING.  An UNMEASURED column fails: a spec asserting "nothing exceeded
        # X" over a window with no parseable samples has proved nothing, and the
        # whole point of this table is that gaps must not read as passes.
        peak = m["peak"]
        return (peak is not None and peak <= float(spec["max_value"]),
                "peak %s%s, need <= %g%s"
                % ("unmeasured" if peak is None else "%.4f" % peak, win,
                   float(spec["max_value"]), _extx))
    if "strictly_decreases_by" in spec:
        need = float(spec["strictly_decreases_by"])
        have = (None if m["first"] is None or m["last"] is None
                else m["first"] - m["last"])
        return (have is not None and have >= need,
                "fell by %s%s, need >= %g"
                % ("unmeasured" if have is None else "%.6f" % have, win, need))
    if "fault_latch_bit" in spec:
        after = float(spec.get("after_t", 0.0))
        t = m.get("latch_t")
        return (t is not None,
                "%s LATCHED (bit + FAULT_ERROR) %s%s, need a latch at t >= %g s"
                % (fault_names(int(spec["fault_latch_bit"])),
                   "at t=%.3f s" % t if t is not None else "never",
                   win, after))
    return False, ("suite error: signal spec %r declares no assertion kind"
                   % (spec,))


def judge_signals(specs, measured, why):
    """Turn scan_signals() output into checks.  Pure over its inputs."""
    checks = []
    for spec, m in zip(specs, measured):
        label = spec.get("label") or "signal"
        name = "signal_%s" % spec.get("name", label.split()[0].lower())
        arms = list(spec.get("any_of") or [])
        if arms:
            # A1 disjunction: pass when ANY arm passes, and report EVERY arm's
            # measurement plus which one satisfied it. Reporting all arms is the
            # point — a reader must be able to see that the arm that failed was
            # physically foreclosed by the arm that passed, not that a check was
            # weakened until it went green.
            arm_ms = m.get("any_of") or []
            results = [_judge_signal_leaf(a, am) for a, am in zip(arms, arm_ms)]
            ok = any(p for p, _ in results)
            won = next((i for i, (p, _) in enumerate(results) if p), None)
            parts = []
            for i, ((p, text), a) in enumerate(zip(results, arms)):
                parts.append("[%s] %s: %s"
                             % ("OK" if p else "no",
                                a.get("label") or a.get("name") or "arm %d" % (i + 1),
                                text))
            checks.append({
                "name": name, "passed": ok,
                "detail": ("%s: %s (%s) — %s"
                           % (label,
                              ("satisfied by arm %d" % (won + 1)) if ok
                              else "NO arm satisfied",
                              "; ".join(parts), why))})
            continue
        ok, text = _judge_signal_leaf(spec, m)
        if spec.get("informational"):
            # INFORMATIONAL SPECS (2026-09-02): the measurement is reported and
            # the bound is EVALUATED, but the verdict is never a failure.  It
            # exists for a band that is known to sit inside the quantity's own
            # run-to-run spread: failing a run on it would be scoring noise,
            # and deleting the spec would lose the reading. A missed bound is
            # said out loud as a WARNING so it cannot pass unnoticed.
            checks.append({
                "name": name, "passed": True,
                "detail": "INFORMATIONAL (reports, never fails)%s — %s: %s (%s)"
                          % ("" if ok else
                             " ** WARNING: the bound was NOT met **",
                             label, text, why)})
            continue
        checks.append({"name": name, "passed": ok,
                       "detail": "%s: %s (%s)" % (label, text, why)})
    return checks


def read_run_meta(csv_path, launched_at=None):
    """Load the child's '<csv>.meta.json' sidecar; {} if absent/stale/unreadable.

    Preferred over the stdout summary for the warm-reset tripwire: under
    --dashboard the child's stdout goes to the terminal and is never captured,
    so the sidecar is the only surviving record of the count.

    D2 — THIS ATTEMPT'S sidecar, or nothing.  A sidecar sitting at that path may
    belong to a PREVIOUS run (the suite now passes --force, so a re-run into a
    non-fresh --out overwrites the CSV but reads the old sidecar until the child
    rewrites it), and reading a stale one would report a stale warm-reset count
    against a fresh run.  Three guards, in increasing strength:

      1. `results` must not be None.  The sidecar is written twice — "running"
         with results=None before the loop, then again at exit.  results=None
         means the child died before finalizing, which is genuinely UNMEASURED,
         not zero.
      2. `doc["csv"]` must equal the path we asked for.  Cheap, and catches a
         sidecar copied or renamed into place.
      3. `created` must be at or after the child's launch time, when the caller
         supplies one.  Timestamps are the child's local ISO-8601 with offset and
         this host's clock, so they are comparable; anything unparseable is
         treated as "cannot verify" and passes this guard rather than discarding
         a sidecar that is probably fine (guards 1-2 are the load-bearing pair).
    """
    if not csv_path:
        return {}
    try:
        with open(csv_path + ".meta.json", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict):
        return {}
    if doc.get("results") is None:
        return {}                          # guard 1: never finalized
    if os.path.normcase(os.path.abspath(str(doc.get("csv") or ""))) != \
            os.path.normcase(os.path.abspath(csv_path)):
        return {}                          # guard 2: not this run's CSV
    if launched_at is not None:
        created = doc.get("created")
        try:
            if datetime.datetime.fromisoformat(str(created)) < launched_at:
                return {}                  # guard 3: predates this attempt
        except (TypeError, ValueError):
            pass                           # unparseable -> cannot verify, allow
    return doc


def child_launched_at(child):
    """The child's launch timestamp as a datetime, or None if unparseable."""
    raw_launch = (child or {}).get("launched_at")
    if not raw_launch:
        return None
    try:
        return datetime.datetime.fromisoformat(str(raw_launch))
    except (TypeError, ValueError):
        return None


def run_ems_strategy(csv_path, child):
    """The EMS strategy name the CHILD RECORDED for this run, or None.

    L7: read from the run's own meta sidecar rather than inferred from the
    scenario registry, because `--ems` can override the registry's default and
    the report must describe the strategy that actually ran. Falls back to None
    (not to the default) when the sidecar is absent or stale — the caller then
    uses the registry, which is the honest "we only know the default" answer.
    """
    meta = read_run_meta(csv_path, child_launched_at(child))
    name = meta.get("ems_strategy")
    return name if isinstance(name, str) and name else None


def run_eta_chg(csv_path, child):
    """The CHARGER ERA this run's plant ran in, read from its own sidecar.

    Returns the float `scenario.eta_chg` the child recorded, or None.

    ⚠️ `None` IS A VALUE, NOT A FAILURE, and it means the 1:1 current-transfer
    era (every campaign up to and including 20260901_151156).  It is the same
    sentinel convention `hil_plant_sim.dp_eta_chg()` uses, and for the same
    reason: that era billed the charger at the BUS voltage where this model
    bills it at the PACK voltage, so no efficiency number reproduces it.  A
    sidecar that is absent or stale also reads None, which is honest for the
    frontier's purposes — a run whose era cannot be established must not be
    silently ranked against one whose era can.
    """
    meta = read_run_meta(csv_path, child_launched_at(child))
    scen = meta.get("scenario")
    if not isinstance(scen, dict):
        return None
    val = scen.get("eta_chg")
    return float(val) if isinstance(val, (int, float)) else None


def warm_reset_count(csv_path, child):
    """Mid-run warm resets for one run: (dict, source).

    The dict carries "mid_run", "observed" and "times" (any of them None when
    that field is unavailable).  A None `mid_run` means UNMEASURED — an older
    simulator build, a child that died before finalizing its sidecar, or a run
    whose sidecar and stdout are both unusable.  Unmeasured must never render as
    zero: the whole point of the tripwire is that the damage it detects does not
    show up in the run's own outcome."""
    meta = read_run_meta(csv_path, child_launched_at(child))
    res = meta.get("results") or {}
    if isinstance(res.get("warm_resets_mid_run"), int):
        return ({"mid_run": res["warm_resets_mid_run"],
                 "observed": res.get("warm_resets_observed"),
                 "times": res.get("warm_reset_times_s")},
                "meta.json")
    summary = (child or {}).get("summary") or {}
    if isinstance(summary.get("warm_resets_mid_run"), int):
        # D4: the stdout line carries both counts but no timestamps.
        return ({"mid_run": summary["warm_resets_mid_run"],
                 "observed": summary.get("warm_resets"), "times": None},
                "child stdout")
    return ({"mid_run": None, "observed": None, "times": None}, "unmeasured")


# D8: the damage a mid-run warm reset does, stated once and reused, because the
# loose version ("a latched fault silently disappears") is WRONG for the checks
# that actually exist -- judge_scenario()'s union check and the replay suite's
# fault_latched both look at the whole run and would FAIL loudly on a fault that
# fired and then vanished.
WARM_RESET_DAMAGE = (
    "after the reset the board runs State 0 -> bring-up -> Idle, so the REST OF "
    "THE RUN IS NOT THE SCENARIO the checks assume: the stimulus timeline kept "
    "playing against a board that restarted underneath it, a fault that fires "
    "again afterwards reads as having fired once (so any dwell or timing "
    "conclusion is wrong), and a check keyed to the FINAL state or flags reads "
    "the clean post-recovery board")


def judge_warm_resets(name, kind, counts, source):
    """The warm-reset tripwire check. Returns (check, note|None, inconclusive|None).

    HAZARD (safety finding S2): from fw v23 the board leaves its latched State 99
    on its own once the injection link has been dead for a run boundary
    (1000 ms) and fresh again for 500 ms.  A host stall of that length MID-RUN is
    indistinguishable from a run boundary, so the board warm-resets.  What that
    costs is WARM_RESET_DAMAGE above — the run is unusable rather than wrong, so
    it is marked INCONCLUSIVE and must be re-run.

    The exception is a scenario whose declared point IS the recovery:
    SCENARIOS[name]["warm_resets_expected"] (comm-loss = 1, whose 2 s gap exists
    precisely to cross the boundary).  D16: only a SCENARIO run may consult that
    registry — a replay entry's name is a log id (ML0151), and a collision with a
    scenario name would silently whitelist a replay.

    Returns a third value, `note`: a non-failing observation (D4) about
    grace-window transitions."""
    expected = ((SCENARIOS.get(name) or {}).get("warm_resets_expected")
                if kind == "scenario" else None)
    count = counts.get("mid_run")
    observed = counts.get("observed")
    times = counts.get("times")

    # D4: transitions inside the grace window are the expected start-of-run
    # recovery from the previous run's settle pause.  Never failing, never
    # inconclusive — but worth saying, because on the FIRST run of a plan
    # against a freshly powered board there is no previous run to recover from,
    # so a transition there means the board was ALREADY latched at power-on and
    # deserves a look before the rest of the plan is believed.
    note = None
    if isinstance(observed, int) and isinstance(count, int) and observed > count:
        # ITEM 10: render ONLY the in-grace timestamps here.  `times` is every
        # observed transition, mid-run ones included, so printing all of them
        # against a count of in-grace resets reads as a contradiction — comm-loss
        # showed "1 warm reset inside the grace window at t=0.5, 7.5" where 7.5 is
        # its designed MID-run recovery, which this sentence is not about.
        in_grace = [x for x in (times or [])
                    if isinstance(x, (int, float)) and x < WARM_RESET_GRACE_S]
        when = ""
        if in_grace:
            when = " at t=%s s" % ", ".join("%g" % x for x in in_grace)
        elif times:
            # Timestamps exist but none is in-grace: the list is capped
            # (WARM_RESET_TIMES_MAX) or the clocks disagree.  Say so rather than
            # printing mid-run times under an in-grace heading.
            when = (" (no in-grace timestamp available; the recorded times %s are "
                    "all at or after the %.1fs bound)"
                    % (", ".join("%g" % x for x in times), WARM_RESET_GRACE_S))
        note = ("%d warm reset(s) inside the start-of-run grace window%s: "
                "normally the expected recovery from the previous run's settle "
                "pause, and not counted against this run. On the FIRST run of a "
                "plan against a freshly powered board there is no previous run "
                "to recover from — a transition there means the board was "
                "already latched at power-on, which is worth investigating."
                % (observed - count, when))

    if count is None:
        if expected is not None:
            # K7: on a whitelisted scenario the count is a REQUIREMENT, so
            # "unmeasured" is not a quiet pass — the requirement is UNVERIFIED.
            return ({"name": "warm_reset_expected", "passed": True,
                     "detail": "UNVERIFIED (%s) — this scenario REQUIRES exactly "
                               "%d mid-run warm reset(s) (the recovery IS the "
                               "test), but no count was available from this "
                               "child, so the requirement was not checked. Not "
                               "failed, not confirmed." % (source, expected)},
                    note, None)
        return ({"name": "warm_reset_tripwire", "passed": True,
                 "detail": "not measurable (%s) — no mid-run warm-reset count "
                           "available from this child, so a mid-run restart "
                           "would be invisible here" % source},
                note, None)

    if expected is not None:
        if count == expected:
            return ({"name": "warm_reset_expected", "passed": True,
                     "detail": "%d mid-run warm reset(s) observed via %s; this "
                               "scenario REQUIRES exactly %d (the recovery is "
                               "the point of the run, not an artifact)"
                               % (count, source, expected)},
                    note, None)
        if count > expected:
            # D15: an EXTRA reset destroys evidence exactly as it does anywhere
            # else -- the whitelist licenses the ONE the scenario provokes, not
            # a host stall on top of it.
            reason = ("%d mid-run warm reset(s) observed (%s) but this scenario "
                      "provokes only %d: the extra one(s) are unexplained, and "
                      "%s. Re-run it on an unloaded host."
                      % (count, source, expected, WARM_RESET_DAMAGE))
            return ({"name": "warm_reset_expected", "passed": False,
                     "detail": reason}, note, reason)
        # count < expected: the recovery this scenario exists to test did not
        # happen. A genuine FAIL -- nothing was destroyed, something is missing.
        return ({"name": "warm_reset_expected", "passed": False,
                 "detail": "%d mid-run warm reset(s) observed via %s; this "
                           "scenario REQUIRES exactly %d — the recovery it "
                           "exists to test did not happen"
                           % (count, source, expected)},
                note, None)

    if count == 0:
        # WORDING (2026-08-31): this used to say "the board never left State 99
        # during the run", which is FALSE on the common case. `count` is the
        # MID-RUN count — transitions after WARM_RESET_GRACE_S — so it is zero
        # both when the board never left State 99 AND when it left it exactly as
        # intended, during the in-grace recovery from the previous run's
        # inherited latch (which is what nearly every run in a sequential campaign
        # does). Claiming the stronger fact from the weaker measurement invented a
        # board state on most passing runs. `warm_resets_observed` in the metrics
        # carries the whole-run count for anyone who wants it.
        return ({"name": "warm_reset_tripwire", "passed": True,
                 "detail": "no mid-run warm reset after the %.1f s grace bound "
                           "(%s); an in-grace recovery from the previous run's "
                           "inherited latch is normal and is not counted here"
                           % (WARM_RESET_GRACE_S, source)},
                note, None)
    reason = ("%d mid-run HIL warm reset(s) observed (%s): %s. Most likely a "
              "host stall of >= 1 s, which fw v23+ reads as a run boundary. "
              "Re-run it on an unloaded host."
              % (count, source, WARM_RESET_DAMAGE))
    return ({"name": "warm_reset_tripwire", "passed": False, "detail": reason},
            note, reason)


def result_label(r, bold_fail=False):
    """One verdict word for a result record, used by ALL render sites.

    D3: an INCONCLUSIVE run whose OTHER checks also failed must not read as a
    plain "re-run this one" — the tripwire destroyed the evidence for the rest
    of the run, but the failures already on the record are real and stay
    visible.  Centralized so the three render sites cannot drift apart."""
    if r.get("skipped"):
        return "SKIPPED"
    if r.get("inconclusive"):
        also = r.get("also_failed") or 0
        base = ("INCONCLUSIVE (also FAILED %d check(s))" % also) if also \
            else "INCONCLUSIVE"
        return ("**%s**" % base) if bold_fail else base
    if r["passed"]:
        return "PASS"
    return "**FAIL**" if bold_fail else "FAIL"


def _judge_event_spec(req, events):
    """Evaluate ONE event spec against analyze_events() output.

    Returns (passed, observed_text, problems[]).  Shared by `events_require` and
    every branch of `events_any_of`, so the two cannot drift apart.

    Spec forms:
      "kind"                                  at least one event of that kind
      {"kind": k, "count": n}                 exactly n
      {"kind": k, "field": f,
       "min_value": lo, "max_value": hi}      every f on a matching event in band
      {"kind": k, "where": {"switch": "MOT_PWR", "reason": "uvlo"}, ...}
                                              restrict to events matching ALL of
                                              those exact field values first
      {"total_of": k, "field": f,
      {"max_of": k, "field": f,
       "min_value": lo, "max_value": hi}      the ANY quantifier (PART B2,
                                              2026-09-01): the LARGEST f over
                                              every matching event of kind k.
                                              Asserts that at least ONE event
                                              cleared the floor, which neither
                                              the ALL form (a short tail episode
                                              fails it) nor `total_of` (a long
                                              tail of flickers passes it) can say.
      {"total_of": k, "field": f,
       "min_value": lo, "max_value": hi}      SUM of f over every matching
                                              event of kind k, compared once —
                                              M3 (2026-09-01): a per-episode ALL
                                              quantifier (the `{"kind": k,
                                              "field": f, "min_value": lo}` form
                                              above) fails a correctly-behaving
                                              board on a short tail episode that
                                              never needed to individually clear
                                              a "total energy" style floor;
                                              `total_of` carries that floor as an
                                              aggregate instead, leaving the
                                              per-episode form for a much looser
                                              "every episode cleared some small
                                              floor" sanity check.

    `where` exists because `field_values` pools every event of a kind together:
    an scp-inrush run carries three sw_ring events (MOT_PWR plus FC_BUS/BT_BUS),
    and that entry's expectation turns on telling them apart.  (It was introduced
    2026-08-31 for the two-outcome form of that entry; the entry is single-outcome
    again since the stimulus redesign, and still pins `where` on its scp_cut.)"""
    spec = {"kind": req} if isinstance(req, str) else dict(req)
    # PART B2 (C1 round, 2026-09-01): `max_of` is the ANY quantifier, and it is
    # the third of the three the coalesced `chopper_clamp` stream needs. The
    # bare-field form is ALL ("every episode cleared this"), `total_of` is SUM
    # ("the run harvested this much altogether"), and `max_of` is ANY ("at least
    # one episode was a real braking window, not a 5 ms flicker"). Only the last
    # can say that a run's energy came from a genuine window rather than from a
    # long tail of tiny ones, which is exactly what regen-harvest-true asserts.
    # It shares `total_of`'s code path because the two differ only in the
    # aggregator.
    if "total_of" in spec or "max_of" in spec:
        _agg = "total" if "total_of" in spec else "max"
        kind = spec.get("total_of", spec.get("max_of"))
        field = spec["field"]
        where = spec.get("where") or {}
        matching = [e for e in events.get("events_by_kind", {}).get(kind, [])
                    if all(e.get(k) == v for k, v in where.items())]
        vals = [float(e[field]) for e in matching
                if isinstance(e.get(field), (int, float))
                and not isinstance(e.get(field), bool)]
        # An empty `vals` is handled DIFFERENTLY by the two aggregators, and the
        # difference is arithmetic rather than a policy choice: a SUM over
        # nothing is 0.0 and is judged against the floor like any other total
        # (the long-standing `total_of` behaviour, pinned by test), while a MAX
        # over nothing has no value at all and is reported as such.
        problems = []
        lo, hi = spec.get("min_value"), spec.get("max_value")
        if not vals and _agg == "max":
            problems.append("no '%s' event carrying a numeric '%s' field to "
                            "aggregate" % (kind, field))
            return False, ("%s %s over 0 '%s' event(s): undefined"
                           % (_agg, field, kind)), problems
        total = sum(vals) if _agg == "total" else max(vals)  # max: vals non-empty
        if lo is not None and total < lo:
            problems.append("%s %s = %.4f, below min_value %g (over %d "
                            "'%s' event(s))" % (_agg, field, total, lo,
                                                len(vals), kind))
        if hi is not None and total > hi:
            problems.append("%s %s = %.4f, above max_value %g (over %d "
                            "'%s' event(s))" % (_agg, field, total, hi,
                                                len(vals), kind))
        observed = "%s %s over %d '%s' event(s) = %.4f" % (
            _agg, field, len(vals), kind, total)
        return (not problems), observed, problems
    kind = spec["kind"]
    where = spec.get("where") or {}
    field = spec.get("field")
    if where:
        matching = [e for e in events.get("events_by_kind", {}).get(kind, [])
                    if all(e.get(k) == v for k, v in where.items())]
        n = len(matching)
        vals = [float(e[field]) for e in matching
                if isinstance(e.get(field), (int, float))
                and not isinstance(e.get(field), bool)] if field else []
    else:
        n = events.get("kinds", {}).get(kind, 0)
        vals = (events.get("field_values", {}).get(kind, {}).get(field, [])
                if field else [])
    tag = kind if not where else "%s[%s]" % (
        kind, ", ".join("%s=%s" % (k, v) for k, v in sorted(where.items())))
    problems = []
    if "count" in spec:
        if n != int(spec["count"]):
            problems.append("count %d, expected exactly %d" % (n, int(spec["count"])))
    elif n == 0:
        problems.append("no such event")
    if field is not None:
        # A count-0 spec that PASSED asserts absence; there is then no field to
        # check and demanding one would contradict the spec's own expectation.
        if not vals and not (spec.get("count") == 0 and n == 0):
            problems.append("no '%s' field on any '%s' event to check" % (field, tag))
        elif vals:
            lo, hi = spec.get("min_value"), spec.get("max_value")
            bad = [v for v in vals
                   if (lo is not None and v < lo) or (hi is not None and v > hi)]
            if bad:
                problems.append(
                    "%s out of the [%s, %s] plausibility band: %s"
                    % (field,
                       "%g" % lo if lo is not None else "-inf",
                       "%g" % hi if hi is not None else "+inf",
                       ", ".join("%.3f" % v for v in bad)))
    observed = ("%d '%s' event(s)" % (n, tag)) + (
        "; %s = %s" % (field, ", ".join("%.3f" % v for v in vals)) if vals else "")
    return (not problems), observed, problems


def analyze_events(path):
    """Event counts by kind from a hi-fi .events.jsonl sidecar."""
    out = {"path": path, "total": 0, "kinds": {}, "over_absmax": 0,
           "worst_ring_v": None, "worst_over_absmax_ring_v": None,
           # A10 (campaign E, 2026-09-03): how many rings the estimator put in
           # the LOAD-DUMP class.  `over_absmax` is that class GATED on the
           # plausibility test and on the 20 V abs-max, so a run can carry
           # load-dump rings and still report zero over-abs-max ones - and the
           # unconditional check row below has to be able to say which.
           "load_dump_rings": 0,
           "field_values": {}, "events_by_kind": {}, "read_error": None}
    if not path or not os.path.isfile(path):
        return out
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                out["total"] += 1
                k = e.get("kind", "?")
                out["kinds"][k] = out["kinds"].get(k, 0) + 1
                # 2026-08-31: the whole event, per kind, so an events spec can
                # FILTER (`where`) instead of only counting. `field_values` below
                # pools every event of a kind together, which cannot separate the
                # MOT_PWR sw_ring from the FC_BUS/BT_BUS ones that share it — and
                # the scp-inrush expectation turns on exactly that distinction
                # (introduced for its two-outcome form; still load-bearing on the
                # single-outcome `where` pin it uses since the 2026-08-31 stimulus
                # redesign). Bounded by construction: these events are rare (3-4
                # in a whole scp-inrush run), and only scalars are kept.
                out["events_by_kind"].setdefault(k, []).append(
                    {fn: fv for fn, fv in e.items()
                     if isinstance(fv, (int, float, str, bool))})
                # Numeric fields, kept per kind so an events_require spec can pin a
                # plausibility band on one (scp_cut's i_cut).  Small by construction:
                # these events are rare.
                for fname, fval in e.items():
                    if fname in ("t", "kind", "switch") or isinstance(fval, bool):
                        continue
                    if isinstance(fval, (int, float)):
                        out["field_values"].setdefault(k, {}).setdefault(
                            fname, []).append(float(fval))
                if k == "sw_ring":
                    pv = e.get("peak_v")
                    # ITEM 9: record the worst ring UNCONDITIONALLY.  This used to be
                    # tracked only for rings already flagged over_absmax, so a ring
                    # BELOW the 20 V abs-max but above LIMIT_V_BUS_MAX appeared
                    # nowhere at all — campaign 20260830_203006's 17.578 V FC-open
                    # ring (0.078 V over LIMIT_V_BUS_MAX) was invisible in REPORT.md.
                    # The abs-max subset is kept separately so the Death-5 banner
                    # still reports the number it always did.
                    if pv is not None and (out["worst_ring_v"] is None
                                           or pv > out["worst_ring_v"]):
                        out["worst_ring_v"] = pv
                    if e.get("load_dump_class"):
                        out["load_dump_rings"] += 1
                    if e.get("over_absmax"):
                        out["over_absmax"] += 1
                        if pv is not None and (
                                out["worst_over_absmax_ring_v"] is None
                                or pv > out["worst_over_absmax_ring_v"]):
                            out["worst_over_absmax_ring_v"] = pv
    except OSError as exc:
        # L9(b): record the failure instead of silently swallowing it -- an
        # unreadable sidecar must not render in REPORT.md as "0 events, clean".
        out["read_error"] = str(exc)
    return out


# FAULT_ERROR (0x8000) is imported from hil_replay_suite above.  .ino:4501-4503 —
# triggerFault() ORs it into EVERY latched fault, so a lone PI_TIMEOUT/HIL_STALE
# latch is observed as 0x8010, never bare 0x0010.
HIL_DEFAULT_RATE_HZ = 1000.0   # the suite never overrides hil_plant_sim.py's
                                # --rate default (full_argv appends none)


def judge_scenario(name, metrics, events, child, pi_live=False, duration_s=None,
                   signals=None):
    """Scenario pass/fail. Returns (passed, checks[]) — pure over the inputs."""
    checks = []

    obs_ok = metrics["n_obs"] > 0
    checks.append({
        "name": "observation_frames", "passed": obs_ok,
        "detail": ("%d/%d ticks carry an observation frame" % (metrics["n_obs"], metrics["rows"]))
                  if obs_ok else
                  "NO observation frames — the board never answered. Flashed with "
                  "-DHIL_SIM=1 -DUSE_ETHERNET=1? Right IP/port? On the same L2?",
    })

    # M1: observation_frames alone cannot distinguish "the board answered all run"
    # from "the board answered for 0.4 s and went silent". The latter would leave an
    # EMPTY post-grace window, and every post-grace fault check would then pass
    # vacuously — a board that DIED mid-run reported as clean. The fault scoring is
    # only as good as the window it scores, so assert the window is non-empty.
    if obs_ok:
        post_ok = (metrics.get("n_obs_post_grace") or 0) > 0
        grace_for_msg = metrics.get("grace_s", WARM_RESET_GRACE_S)
        checks.append({
            "name": "observation_frames_post_grace", "passed": post_ok,
            "detail": ("%d ticks carry an observation frame at t >= %.1fs (the "
                       "window every fault check is judged on)"
                       % (metrics.get("n_obs_post_grace") or 0, grace_for_msg))
                      if post_ok else
                      ("the board answered %d tick(s) but NONE at or after t=%.1fs "
                       "— it went silent inside the grace window (last observed "
                       "t=%s s). The post-grace window is EMPTY, so every fault "
                       "check below passed on no evidence at all."
                       % (metrics["n_obs"], grace_for_msg,
                          "%.3f" % metrics["last_obs_t"]
                          if metrics.get("last_obs_t") is not None else "?")),
        })

    final = metrics["final_fault_flags"] or 0
    seen = metrics["fault_bits_seen"] or 0
    # POST-GRACE union: what this run itself produced.  Bits present ONLY before
    # the grace bound are the predecessor's settle latch, cleared by fw v23's
    # between-run warm recovery — see analyze_scenario_csv().
    post = metrics.get("fault_bits_post_grace") or 0
    carried = seen & ~post
    grace_s = metrics.get("grace_s", WARM_RESET_GRACE_S)
    # ⚠️ WORDING CORRECTED 2026-08-31 (campaign 20260831_222036; three analysis
    # agents flagged it independently).  This detail used to say "carried-in
    # from the PREDECESSOR'S SETTLE LATCH", which claims something the suite
    # does not know and which was FALSE on most runs it was printed for — in
    # batches 3 and 6 of that campaign, 7 of 8 predecessors ended CLEAN and the
    # sentence still named their settle latch.
    #
    # WHAT IS ACTUALLY OBSERVED, and all this line may claim: bits present
    # before the grace bound and absent after it.  The dominant contributor is
    # not inherited at all — the 0x8010 (HIL_STALE|ERROR) term is generated
    # FRESH by each child's own link handshake, because the board sees no
    # injection frames for the first moments after the simulator restarts.  A
    # genuinely inherited latch is ALSO possible (the fw v23 run-boundary warm
    # recovery clears one inside this same window, and campaign
    # 20260831_222036's ems-drive-cycle saw exactly that: 0x8012 =
    # soc-depletion's real UV_BATT latch | 0x8010).  The two are
    # INDISTINGUISHABLE from this run's CSV alone, so the wording names the
    # mechanism it can see and implies nothing about the predecessor.
    carried_note = ("" if not carried else
                    "; pre-grace reconnect transient: %s (excused — observed "
                    "only before t=%.1fs and gone after it; predecessor state "
                    "NOT implied, see judge_scenario)"
                    % (fault_names(carried), grace_s))
    first_t = metrics.get("fault_first_t") or {}
    # PART B1 (2026-09-01): `not_before_s` is judged against the LATCH map, not
    # against `first_t`. See the fault_first_latch_t comment in the metrics
    # builder for why. `first_t` is retained unchanged for REPORTING (it is
    # rendered in the detail strings and serialized into results.json), so no
    # consumer of the old field loses anything.
    #
    # This does NOT disturb the scp-inrush reasoning at FAULT_EXPECTATIONS
    # ["scp-inrush"]: that entry deliberately carries NEITHER `not_before_s`
    # NOR `survive_to`, precisely because its OC_FC latch lands INSIDE the
    # grace window and both maps here are post-grace-scoped. The change below
    # narrows which post-grace sightings count; it does not widen the window,
    # so an in-grace latch remains invisible to both and the entry's derivation
    # stands as written.
    first_latch_t = metrics.get("fault_first_latch_t") or {}
    expect = FAULT_EXPECTATIONS.get(name)

    if expect is not None:
        why = expect["source"]
        require = int(expect.get("require", 0))
        # `allow_only` defaults to "whatever is required, plus the FAULT_ERROR bit
        # triggerFault() always ORs in" — never to "anything goes".
        allow_only = expect.get("allow_only")
        allow_only = (require | FAULT_ERROR) if allow_only is None else int(allow_only)
        # L9: defensive and, with the current table, DEAD — every entry that sets
        # `require` also names FAULT_ERROR in its explicit `allow_only`. Kept so a
        # future entry cannot declare "require X" and then fail on the 0x8000 bit
        # triggerFault() unconditionally ORs in beside X (.ino:4501-4503), which is
        # a mistake with a confusing symptom. Deliberately NOT applied when there is
        # no `require`: an allow_only-only entry is asserting "clean", and
        # FAULT_ERROR appearing there is a real finding.
        allow_only |= FAULT_ERROR if require else 0

        if require:
            got = (post & require) == require
            detail = ("expected %s (%s); post-grace union %s (whole-run %s, final %s)%s"
                      % (fault_names(require), why, fault_names(post),
                         fault_names(seen), fault_names(final), carried_note))
            not_before = expect.get("not_before_s")
            if got and not_before is not None:
                # L4: first_t is keyed by fault NAME (json-friendly), so look each
                # required bit up by its own rendered name.
                early = sorted(b for b in _split_bits(require)
                               if first_latch_t.get(fault_names(b)) is not None
                               and first_latch_t[fault_names(b)] < not_before)
                if early:
                    got = False
                    detail += ("; but %s first LATCHED at t=%.3fs, BEFORE the "
                               "stimulus at t=%.1fs — it did not come from the "
                               "stimulus this check is about"
                               % (fault_names(sum(early)),
                                  first_latch_t[fault_names(early[0])], not_before))
                else:
                    detail += ("; first LATCHED at t=%s s, at or after the "
                               "t=%.1fs stimulus"
                               % (", ".join("%.3f" % first_latch_t[fault_names(b)]
                                            for b in _split_bits(require)
                                            if fault_names(b) in first_latch_t)
                                  or "?", not_before))
            checks.append({"name": "expected_fault", "passed": got, "detail": detail})

        extra = post & ~allow_only
        checks.append({
            "name": "fault_allow_only", "passed": extra == 0,
            "detail": ("post-grace union %s; permitted here: %s (%s)%s%s"
                       % (fault_names(post),
                          fault_names(allow_only) if allow_only else "none",
                          why, carried_note,
                          "" if extra == 0 else
                          "  -> UNEXPECTED: %s" % fault_names(extra)))})

        survive = expect.get("survive_to")
        if survive is not None:
            t_req = float(survive["t"])
            states = set(survive.get("states") or ())
            before = metrics.get("fault_bits_before_survive") or 0
            st = metrics.get("state_at_survive")
            ok = before == 0 and (st in states if states else st is not None)
            reasons = []
            if before:
                reasons.append("latched %s BEFORE t=%.1fs, so the run never "
                               "reached its own stimulus"
                               % (fault_names(before), t_req))
            if states and st not in states:
                reasons.append("mainState at t=%.1fs was %s, not one of %s"
                               % (t_req, st, sorted(states)))
            checks.append({
                "name": "survives_to_stimulus", "passed": ok,
                "detail": ("un-latched and in mainState %s at t=%.1fs"
                           % (st, t_req)) if ok
                          else ("; ".join(reasons) or
                                "no observation frame at or after t=%.1fs" % t_req)})

        # `provisional_note` (2026-08-31 review M3): a threshold in this entry has
        # not yet been derived from a live campaign. The note rides the check
        # detail (pass or fail) so results.json/REPORT.md carry the qualifier —
        # a first-campaign band miss must read as "threshold not yet derived",
        # never as a board/plant change. Remove the key when the band is pinned.
        # DI-MED-5: computed HERE rather than at the events loop, because
        # `signals_require` checks carry provisional thresholds too (ems-sdp's
        # first-campaign bands are signal checks, not event ones) and rendering
        # the qualifier onto only half the checks is how a provisional number
        # gets read as a derived one.
        prov = expect.get("provisional_note")
        prov_sfx = ("  [PROVISIONAL: %s]" % prov) if prov else ""

        sig_specs = expect.get("signals_require") or []
        if sig_specs:
            # `signals` is scan_signals()' output; None means the caller did not
            # measure. Never silently skip — an unmeasured positive assertion is a
            # gap, and this table exists because gaps read as passes.
            if signals is None:
                checks.append({
                    "name": "signals_require", "passed": False,
                    "detail": ("this scenario declares %d positive signal "
                               "assertion(s) but they were not measured — the "
                               "caller did not run scan_signals()" % len(sig_specs))
                              + prov_sfx})
            else:
                for _c in judge_signals(sig_specs, signals, why):
                    _c["detail"] = _c.get("detail", "") + prov_sfx
                    checks.append(_c)

        # child_tx_healthy: declared by a scenario whose objective is a
        # COMMAND-side fault, where the same 0x0010 bit could equally have come
        # from the HIL link going stale.  The check's JOB is the attribution,
        # and stream continuity was only ever the means.
        #
        # fw v25 (2026-09-01): the attribution now PREFERS THE WIRE — a fw v25
        # board states its latched first cause outright, and the stream-health
        # inference is the fallback for 16/17-byte boards.  On a pre-v25 board
        # the verdict is BIT-FOR-BIT the old one (pass iff the stream was
        # continuous; unmeasured FAILS, because an unverifiable attribution is
        # not a verified one).  On a fw v25 board an ERR_HIL_STALE reading now
        # FAILS the check even with perfect tx counters — which is the whole
        # point: the datagrams left this host, and the board still did not get
        # them.  The check name is kept so campaign ledgers stay comparable.
        if expect.get("child_tx_healthy"):
            cause, src, attr_detail = attribute_shared_0x8010(
                metrics, child, duration_s)
            checks.append({
                "name": "child_tx_healthy",
                "passed": cause == "pi",
                "detail": ("0x0010 attribution [%s]: %s (%s)"
                           % (src, attr_detail, why))})

        # events_require accepts EITHER a bare kind string (at least one such event)
        # or a dict pinning count and/or a numeric field's plausibility band. The
        # bare form is kept because most future entries will want nothing more.
        # `prov_sfx` (the `provisional_note` qualifier) is built above, next to
        # the signals block, and rides these details too.
        for req in expect.get("events_require", ()):
            ok, observed, problems = _judge_event_spec(req, events)
            if isinstance(req, str):
                kind = req
            elif "total_of" in req:
                kind = "total_%s" % req["total_of"]
            elif "max_of" in req:
                # PART B2: distinct check NAME, so a ledger reading two specs on
                # the same event kind can tell the SUM assertion from the ANY one.
                kind = "max_%s" % req["max_of"]
            else:
                kind = req["kind"]
            checks.append({
                "name": "events_require_%s" % kind, "passed": ok,
                "detail": (observed if ok else
                           "%s — %s (%s)" % (observed, "; ".join(problems), why))
                          + prov_sfx})

        # ── events_any_of: ONE stimulus, two legal orderings (2026-08-31) ────
        # A list of BRANCHES; each branch is {"name", "why", "events": [spec,...]}
        # and is satisfied when ALL of its specs pass. The check passes if ANY
        # branch does, and NAMES the branch that did — that label is the tracking
        # signal, so a race's distribution is visible across campaigns instead of
        # showing up as an intermittent FAIL.
        # ⚠️ NO TABLE ENTRY USES THIS TODAY. Its founding user, scp-inrush,
        # migrated back to a single-outcome events_require on 2026-08-31 when its
        # stimulus was redesigned to win the race outright. Kept for future races;
        # fixing the stimulus is the preferred answer.
        for grp in expect.get("events_any_of", ()):
            branches = list(grp.get("branches") or ())
            results = []
            for br in branches:
                probs, obs_parts = [], []
                for spec in br.get("events", ()):
                    ok_b, observed_b, problems_b = _judge_event_spec(spec, events)
                    obs_parts.append(observed_b)
                    if not ok_b:
                        probs.extend(problems_b)
                results.append((not probs, br, "; ".join(obs_parts), probs))
            won = next((i for i, r in enumerate(results) if r[0]), None)
            gname = grp.get("name", "events_any_of")
            if won is None:
                detail = ("NO outcome matched (%s). " % why) + " || ".join(
                    "[%s] %s — %s" % (r[1].get("name", "branch %d" % i),
                                      r[2], "; ".join(r[3]))
                    for i, r in enumerate(results))
                checks.append({"name": gname, "passed": False, "detail": detail})
            else:
                br = results[won][1]
                other = " || ".join(
                    "[%s] not matched: %s" % (r[1].get("name", "branch %d" % i),
                                              "; ".join(r[3]))
                    for i, r in enumerate(results) if i != won)
                checks.append({
                    "name": gname, "passed": True,
                    "detail": ("OUTCOME **%s**%s: %s (%s)%s"
                               % (br.get("name", "branch %d" % won),
                                  "" if not br.get("label") else
                                  " — %s" % br["label"],
                                  results[won][2],
                                  br.get("why") or why,
                                  "" if not other else "  || " + other))})

        if expect.get("events_forbid_over_absmax"):
            n_over = events.get("over_absmax", 0)
            checks.append({
                "name": "events_no_over_absmax", "passed": n_over == 0,
                "detail": ("no switching event rang above the %.0f V abs-max "
                           "(worst estimated peak %s V)"
                           % (V_ABSMAX_V,
                              "%.2f" % events["worst_ring_v"]
                              if events.get("worst_ring_v") is not None else "n/a"))
                          if n_over == 0 else
                          ("%d ring(s) above the %.0f V abs-max — the Death-5 "
                           "boost-kill signature; this scenario must exercise the "
                           "foldback WITHOUT producing it (%s)"
                           % (n_over, V_ABSMAX_V, why))})
    else:
        # F1/F2: under --pi-live the Pi watchdog is outside this harness's
        # control: an operator-driven Pi that stops commanding while the board
        # is in State 2/3 legitimately latches FAULT_PI_TIMEOUT (0x0010) after
        # PI_TIMEOUT_MS = 500 (.ino:2788, 4817-4826). That is an operator event,
        # not a firmware finding — but two things must be true before this
        # harness excuses it:
        #
        #   F1: triggerFault() ALWAYS ORs in FAULT_ERROR 0x8000 alongside any
        #       fault (.ino:4501-4503), so a bare PI_TIMEOUT latch is observed
        #       as 0x8010, never 0x0010 alone. The old `seen & ~0x0010` mask
        #       left 0x8000 in `unexpected` on every excusal, so the excusal
        #       NEVER actually passed anything — it printed "excused" and then
        #       failed the run anyway on the FAULT_ERROR bit it forgot to mask.
        #
        #   F2: 0x0010 is BOTH FAULT_PI_TIMEOUT and its alias FAULT_HIL_LINK
        #       (the deliberate alias, .ino:1240-1248; the #define is :1265), so
        #       excusing on the bit alone would also excuse a genuine
        #       injection-link failure. Narrowest defensible rule: excuse ONLY
        #       when (a) the fault union is EXACTLY 0x8010 — nothing else set,
        #       not even other latched bits alongside it — AND (b) the shared
        #       bit is attributed to the Pi by attribute_shared_0x8010().
        #
        # THE RESIDUAL IS CLOSED (fw v25, 2026-09-01). The observation frame now
        # carries error_code (.ino:2968-2978), the LATCHED FIRST CAUSE, so on a
        # fw v25 board ERR_PI_TIMEOUT (0x05) vs ERR_HIL_STALE (0x10) is READ off
        # the wire, not inferred. attribute_shared_0x8010() prefers that reading
        # and falls back to the pre-v25 stream-health inference (tx_frames >=
        # 98% of a full-rate run, zero sendto() errors) only for a 16/17-byte
        # board — and labels which of the two decided. A fw v25 board reporting
        # ERR_HIL_STALE is therefore NOT excused even with perfect tx counters,
        # where the old inference would have excused it.
        #
        # 2026-08-30: this whole block is now judged on the POST-GRACE union, not
        # the whole-run one, for the same reason every other fault check is (see
        # analyze_scenario_csv).  It matters HERE in particular: the inherited
        # settle latch is ITSELF 0x8010, so on the whole-run union the "exactly
        # 0x8010" test fired on every run after the first and the excusal was
        # deciding about a bit the previous run left behind.
        exactly_pi_timeout = post == (FAULT_ERROR | FAULT_PI_TIMEOUT)
        # 2026-08-31: the continuity test moved to child_stream_continuity() so
        # the `child_tx_healthy` signal check judges it identically.
        # 2026-09-01 (fw v25): BOTH now go through attribute_shared_0x8010(),
        # which reads the board's error_code when there is one and falls back to
        # that same continuity test otherwise.  One implementation, so the check
        # and the excusal can never disagree about who fired.
        cause, attr_src, attr_detail = (
            attribute_shared_0x8010(metrics, child, duration_s)
            if (pi_live and exactly_pi_timeout) else (None, ATTRIB_UNKNOWN, ""))
        attributed_to_pi = bool(pi_live and exactly_pi_timeout and cause == "pi")
        if pi_live and exactly_pi_timeout and not attributed_to_pi:
            unexpected = post   # do NOT excuse — attribution to the Pi is unsafe
            excuse_detail = ("  (0x%04X observed but NOT attributable to the Pi "
                             "[%s]: %s; NOT excused)" % (post, attr_src, attr_detail))
        elif attributed_to_pi:
            unexpected = 0
            excuse_detail = ("  (PI_TIMEOUT excused under --pi-live: post-grace "
                             "fault union is exactly 0x%04X "
                             "(FAULT_ERROR|PI_TIMEOUT) and the shared 0x0010 bit "
                             "is attributed to the Pi [%s]: %s — the operator's "
                             "Pi owns the command cadence.)"
                             % (post, attr_src, attr_detail))
        else:
            unexpected = post
            excuse_detail = ""
        checks.append({"name": "no_unexpected_fault", "passed": unexpected == 0,
                       "detail": "post-grace fault_flags union = %s "
                                 "(whole-run union %s)%s%s"
                                 % (fault_names(post), fault_names(seen),
                                    carried_note, excuse_detail)})

    rate = (child.get("summary") or {}).get("achieved_hz")
    if rate is not None:
        checks.append({"name": "achieved_rate", "passed": rate >= 900.0,
                       "detail": "%.1f Hz achieved (target 1000; host-stall gate 900)" % rate})
    elif child.get("stdout_passthrough"):
        # F3: with --dashboard the child's stdout was handed to the terminal
        # (run_child()'s TRADE-OFF), so there is no captured summary to parse
        # a rate from. Make that explicit instead of letting the rate gate
        # silently vanish -- an absent check here reads as "not applicable",
        # not "skipped for an operational reason".
        checks.append({"name": "achieved_rate", "passed": True,
                       "detail": "not measurable — --dashboard passed stdout through; "
                                 "rate gate SKIPPED"})

    # ── A10 (campaign E, 2026-09-03): ALWAYS EMIT THE ROW ───────────────────
    # This used to append only when `over_absmax` was non-zero, so a run whose
    # ring was GATED out of that class - by the plausibility test or by falling
    # under the 20 V abs-max - produced no row at all, and the check count
    # simply dropped (`regen-harvest-true`, 17 -> 16 between two campaigns). A
    # vanishing row reads as "not applicable" and is indistinguishable from a
    # scoring path that was never reached, which is the failure mode the whole
    # census vocabulary exists to prevent. The row now always states the worst
    # estimated peak and how many rings fell in the LOAD-DUMP class, so a
    # campaign can see the margin move before it crosses.
    # The row is emitted whenever there is a stream to aggregate, and ALWAYS
    # when the count is non-zero - a non-zero count must never be silent, even
    # on a measurement dict that carries no path.
    if events.get("over_absmax") or (events.get("path")
                                     and not events.get("read_error")):
        _n_over = events.get("over_absmax", 0)
        _worst = events.get("worst_ring_v")
        _ld = events.get("load_dump_rings", 0)
        # ⚠️ ITEM 9 STILL HOLDS ON THE FAILING BRANCH: it reports the
        # over-abs-max SUBSET's peak and must NOT quote `worst_ring_v`, which
        # can be a lower sub-abs-max ring from a cleaner switching event. The
        # unconditional worst-ring figure belongs to the PASSING branch, where
        # it is the whole point of emitting a row at all.
        checks.append({
            "name": "sw_ring_over_absmax", "passed": _n_over == 0,
            "detail": ("no switching event rang above the %.0f V abs-max "
                       "(worst estimated ring peak %s V, %d load-dump-class "
                       "ring(s))"
                       % (V_ABSMAX_V,
                          "n/a" if _worst is None else "%.2f" % _worst, _ld))
                      if _n_over == 0 else
                      ("%d switching event(s) with an estimated ring peak above "
                       "the %.0f V abs-max — the boost-death signature; worst "
                       "%s V, %d load-dump-class ring(s)"
                       % (_n_over, V_ABSMAX_V,
                          ("%.2f" % events["worst_over_absmax_ring_v"])
                          if events.get("worst_over_absmax_ring_v") is not None
                          else "?", _ld))})

    # ── SUITE-WIDE SHARE-CUT HAZARD TRIPWIRE (fw >= 25, 2026-09-01) ──────────
    # THE HAZARD, measured: campaign 20260901_080905's ems-sdp-braking latched
    # OC_BT because applyShareRatio()'s r-based bus cutoff opened FC_BUS — the
    # only CONDUCTING source, i_cut 0.6371 A — 5 ms after BT_BUS was commanded
    # HIGH, i.e. inside the survivor's ~8 ms RT1987 t_D_ON.  V_bus fell
    # 14.56 -> 12.40 V on capacitance in 3 ms and I_batt overshot to 4.64 A.
    # fw v25 closes it twice over: the r-based path gained the
    # SHARE_CUT_MAX_HANDOFF_A (0.5 A) load guard the setpoint-latch path has had
    # since fw v6, and BOTH paths now refuse a cut while the survivor's rising
    # edge is younger than SHARE_CUT_SURVIVOR_BLANK_MS (30 ms).
    #
    # SO ON fw >= 25 THIS EVENT MUST NOT OCCUR, and it is worth asserting
    # SUITE-WIDE rather than per-scenario: the event that exposed it was
    # incidental to a scenario about something else, and the next instance will
    # be too.  A regression that re-opens either guard shows up here as a named
    # check on whichever run happens to hit it.
    #
    # FW GATE.  fw <= 24 boards legitimately produce these — that is the defect
    # — so the tripwire is skipped there with an explicit SKIPPED check rather
    # than silently absent.  The gate is TWO conditions, both required:
    #   (1) TARGET_FW_VERSION >= 25 — the suite's declaration of what is flashed.
    #   (2) the run actually produced a per-run firmware readback, i.e.
    #       metrics["error_code_final"] is not None.  error_code arrived on the
    #       18-byte observation frame in fw v25, so its PRESENCE is positive
    #       evidence the board really is >= v25.  Note a clean v25 board reads
    #       0, not None — None means the field never arrived at all (a 17-byte
    #       frame, i.e. a pre-v25 board, or a run with no observations).
    # A declaration alone can be wrong (stale flash); requiring the readback
    # keeps the tripwire from asserting a v25-only guarantee against a v24 board.
    #
    # TEARDOWN DISCRIMINATION, and its honest limits.  A State-99 teardown
    # (safeAllSwitches()) legitimately opens a LOADED bus switch and emits
    # exactly this event shape.  The sw_ring event carries no state field
    # (hil_electrical.py emits t/kind/switch/reason/i_cut/peak_v/over_absmax),
    # so the discrimination is TEMPORAL, on a LEAD WINDOW:
    #
    #     cutoff = first_own_fault - TEARDOWN_LEAD_MS
    #
    # where `first_own_fault` is the earliest WHOLE-RUN fault sighting later
    # than CARRIED_IN_LATCH_MAX_S (i.e. the earliest fault this run caused, with
    # the predecessor's inherited latch filtered out).  Events at or after the
    # cutoff are attributed to the State-99 teardown that follows every latch in
    # this harness and are excluded; events before it are share-path cuts by
    # elimination — no other code path opens a bus switch under load while the
    # board is running.  See TEARDOWN_LEAD_MS and CARRIED_IN_LATCH_MAX_S above
    # for the 0.04-0.55 ms (teardown) vs >= 13.8 ms (hazard) measurement the
    # 5.0 ms window sits between, and for why the post-grace map is the wrong
    # anchor even though it is the right judging scope.
    #
    # WHY THE CUTOFF SITS BEFORE THE ANCHOR: a teardown cut is timestamped by
    # the solver up to one observation round-trip (~1.9 ms) earlier than the
    # latch it accompanies, so an exact-anchor cutoff would false-FAIL every
    # benign teardown.  The 080905 case that motivated the tripwire is still
    # caught: its share cut CAUSED the fault and leads it by 13.8 ms, well
    # outside the window.
    # ⚠️ Residual: a share cut arriving AFTER an unrelated fault is still
    # missed.  Adding a state field to the sw_ring event is the clean fix and
    # belongs to a future round.
    _fw_readback_ok = metrics.get("error_code_final") is not None
    if TARGET_FW_VERSION >= 25 and _fw_readback_ok:
        _first_fault_t = min(
            (t for t in (metrics.get("fault_first_t_whole_run") or {}).values()
             if t is not None and t > CARRIED_IN_LATCH_MAX_S), default=None)
        _cutoff_t = (None if _first_fault_t is None
                     else _first_fault_t - TEARDOWN_LEAD_MS / 1000.0)
        _hazard = [
            e for e in (events.get("events_by_kind") or {}).get("sw_ring", [])
            if e.get("reason") == "en_low"
            and e.get("switch") in ("FC_BUS", "BT_BUS")
            and abs(float(e.get("i_cut") or 0.0)) > SHARE_CUT_MAX_HANDOFF_A
            and (_cutoff_t is None or float(e.get("t", 0.0)) < _cutoff_t)]
        checks.append({
            "name": "share_cut_load_hazard",
            "passed": not _hazard,
            "detail": (("no loaded bus-switch cut outside teardown "
                        "(fw v25 guards: load <= %.1f A + %d ms survivor "
                        "blanking; teardown excluded at t >= %s, i.e. this "
                        "run's own first fault less TEARDOWN_LEAD_MS %.1f ms)"
                        % (SHARE_CUT_MAX_HANDOFF_A,
                           SHARE_CUT_SURVIVOR_BLANK_MS,
                           "%.4f s" % _cutoff_t if _cutoff_t is not None
                           else "n/a — this run latched no fault of its own",
                           TEARDOWN_LEAD_MS))
                       if not _hazard else
                       ("%d loaded bus-switch cut(s) on a share path — the fw v25 "
                        "guards should make this UNREACHABLE: %s. Worst i_cut "
                        "%.4f A against SHARE_CUT_MAX_HANDOFF_A %.1f A."
                        % (len(_hazard),
                           "; ".join("%s at t=%.4f s, i_cut %.4f A"
                                     % (e.get("switch"), float(e.get("t", 0.0)),
                                        float(e.get("i_cut") or 0.0))
                                     for e in _hazard[:4]),
                           max(abs(float(e.get("i_cut") or 0.0)) for e in _hazard),
                           SHARE_CUT_MAX_HANDOFF_A)))})
    else:
        checks.append({
            "name": "share_cut_load_hazard", "passed": True,
            "detail": ("SKIPPED (%s) — the share-cut guards landed in fw v25. "
                       "A pre-v25 board legitimately produces this event; that "
                       "is the defect the guards fix, not a regression."
                       % ("TARGET_FW_VERSION is %d, < 25" % TARGET_FW_VERSION
                          if TARGET_FW_VERSION < 25 else
                          "TARGET_FW_VERSION is %d but no per-run firmware "
                          "readback: metrics['error_code_final'] is None, so "
                          "the 18-byte fw-v25 observation frame was never "
                          "seen" % TARGET_FW_VERSION))})

    # ── HI-FI SUBSTEP RESOLUTION (2026-09-02, review PLANT-R1-F6) ──────────
    # The electrical engine's substep count is WALL-CLOCK ADAPTIVE, so the node
    # ODE's resolution is a property of the host that ran the campaign.  Every
    # verdict this suite reaches about a sub-millisecond event (a hot-plug ring,
    # an SCP inrush, a switching transient) is reached on a trace integrated at
    # whatever step the host could afford, and until now nothing recorded that
    # step.  SKIPPED, not failed, when the column is absent: a simple-engine run
    # has no substeps, and every CSV before this round has no column.
    _sub_n = metrics.get("substep_n_min")
    if _sub_n is None:
        checks.append({
            "name": "substep_resolution", "passed": True,
            "detail": ("SKIPPED — no `elec_substep_n` column (a simple-engine "
                       "run has no substeps; a hi-fi CSV from before "
                       "2026-09-02 predates the column)")})
    else:
        # M1 (2026-09-02): the verdict is on a SUSTAINED collapse, not on the
        # single coarsest tick — see SUBSTEP_COLLAPSE_FRACTION for why.  An
        # isolated sub-gate tick still gets said out loud, as a WARNING, because
        # it is exactly the provenance the column was added to carry.
        _below = metrics.get("substep_n_below_gate") or 0
        _rows = metrics.get("substep_n_rows") or 0
        _frac = (_below / float(_rows)) if _rows else 0.0
        _ok = _frac <= SUBSTEP_COLLAPSE_FRACTION
        if _ok and _below == 0:
            _verdict = ("The host sustained the electrical resolution this "
                        "run's sub-millisecond verdicts are read at.")
        elif _ok:
            _verdict = ("WARNING (not a failure): the host ran the node ODE "
                        "coarser than %d us on %.3f %% of ticks, under the "
                        "%.1f %% sustained-collapse threshold. The substep "
                        "count is WALL-CLOCK adaptive, so isolated coarse "
                        "ticks are the host's scheduler, not the board — but "
                        "a sub-millisecond number read at one of them is "
                        "host-limited."
                        % (1000 // SUBSTEP_N_MIN_GATE, 100.0 * _frac,
                           100.0 * SUBSTEP_COLLAPSE_FRACTION))
        else:
            _verdict = ("The host ran the node ODE coarser than %d us on "
                        "%.3f %% of ticks, past the %.1f %% "
                        "sustained-collapse threshold: treat this run's "
                        "switching-transient numbers (ring peaks, inrush, cut "
                        "currents) as host-limited, not as measurements."
                        % (1000 // SUBSTEP_N_MIN_GATE, 100.0 * _frac,
                           100.0 * SUBSTEP_COLLAPSE_FRACTION))
        checks.append({
            "name": "substep_resolution",
            "passed": _ok,
            "detail": "minimum %d substep(s)/tick (mean %.1f, %d of %d tick(s) "
                      "under the gate >= %d). %s"
                      % (_sub_n, metrics.get("substep_n_mean") or 0.0,
                         _below, _rows, SUBSTEP_N_MIN_GATE, _verdict)})

    n_chop = events["kinds"].get("chopper_over_power", 0)
    if n_chop:
        checks.append({"name": "chopper_over_power", "passed": False,
                       "detail": "%d excursion(s) where V_rgn^2/47 Ω exceeded the dump "
                                 "resistor's 20 W rating (the question the chopper model "
                                 "exists to answer — see hil_electrical.py P_CHOPPER_MAX_W)"
                                 % n_chop})

    if child.get("status") != "ok":
        checks.append({"name": "child_process", "passed": False,
                       "detail": "child %s (rc=%s)" % (child.get("status"), child.get("returncode"))})

    return all(c["passed"] for c in checks), checks


CHILD_TERM_GRACE_S = 5.0    # M3: SIGTERM grace period before an unconditional kill()


def run_child(item, args):
    """Execute one plan item. Returns the child record (never raises).

    M3: uses Popen + terminate() (not subprocess.run(..., timeout=...), which only
    ever escalates straight to SIGKILL on a timeout) so a wedged hil_plant_sim.py
    child gets a chance to run its own KeyboardInterrupt/finally cleanup (closing
    its CSV and events sidecar cleanly) before being killed outright."""
    argv = full_argv(item, args)
    rec = {"argv": argv, "status": "ok", "returncode": None,
           "wall_s": None, "log": item["log"], "summary": {}}
    # --dashboard TRADE-OFF: the dashboard writes ANSI to stdout, which is
    # useless (and log-bloating) inside a captured pipe — and the child's own
    # tty check would simply disable it, making the flag a no-op.  So with
    # --dashboard we hand the child the real terminal for stdout and capture
    # only stderr.  COST: the per-run summary is parsed from stdout, so the
    # summary columns in REPORT.md are empty for dashboard runs.  That is why
    # the flag is OFF by default: without it, behaviour is byte-identical to
    # before, and reports stay complete.
    dashboard = getattr(args, "dashboard", False)
    if dashboard:
        rec["stdout_passthrough"] = True
    t0 = time.time()
    # D2 guard 3: local wall-clock at launch, in the same ISO-8601-with-offset
    # form the child stamps into its sidecar's "created", so read_run_meta() can
    # reject a sidecar that predates this attempt.  Rounded DOWN to the second
    # (the child's timespec="seconds" truncates), so a child launched at
    # x.900 s stamping x.000 s is not falsely judged stale.
    rec["launched_at"] = (datetime.datetime.fromtimestamp(t0)
                          .replace(microsecond=0).astimezone()
                          .isoformat(timespec="seconds"))
    proc = None
    try:
        proc = subprocess.Popen(argv, cwd=_REPO,
                                stdout=None if dashboard else subprocess.PIPE,
                                stderr=subprocess.PIPE if dashboard
                                else subprocess.STDOUT)
        try:
            out_b, err_b = proc.communicate(timeout=item["timeout_s"])
            out_b = out_b if out_b is not None else (err_b or b"")
            rec["returncode"] = proc.returncode
            if proc.returncode != 0:
                rec["status"] = "nonzero-exit"
            out = out_b.decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            proc.terminate()          # SIGTERM: catchable, unlike SIGKILL
            try:
                out_b, err_b = proc.communicate(timeout=CHILD_TERM_GRACE_S)
                out_b = out_b if out_b is not None else (err_b or b"")
            except subprocess.TimeoutExpired:
                proc.kill()            # child ignored/missed SIGTERM -- last resort
                out_b, err_b = proc.communicate()
                out_b = out_b if out_b is not None else (err_b or b"")
            out = out_b.decode("utf-8", "replace")
            out += ("\n[run_hil_suite] *** TIMEOUT after %.1f s — child sent SIGTERM "
                    "(%.0fs grace, then SIGKILL if needed) ***\n"
                    % (item["timeout_s"], CHILD_TERM_GRACE_S))
            rec["status"] = "TIMEOUT"
            rec["returncode"] = proc.returncode
    except OSError as exc:
        out = "[run_hil_suite] could not launch child: %s\n" % exc
        rec["status"] = "launch-failed"
    rec["wall_s"] = time.time() - t0
    rec["summary"] = parse_child_summary(out)
    try:
        with open(item["log"], "w", encoding="utf-8") as fh:
            # L2: list2cmdline quotes the args, so the header line stays
            # copy-pasteable now that the default output path contains a space.
            fh.write(subprocess.list2cmdline(argv) + "\n\n")
            fh.write(out)
    except OSError as exc:
        # L9(b): record the failure instead of silently swallowing it -- the
        # REPORT.md link to this .log must not silently point at nothing.
        rec["log_write_error"] = str(exc)
    return rec


# ─────────────────────────────────────────────────────────────────────────────
# Report generation — PURE: results dicts in, text out. No I/O, no board.
# ─────────────────────────────────────────────────────────────────────────────

def _row(cells):
    return "| " + " | ".join(str(c) for c in cells) + " |"


# ═════════════════════════════════════════════════════════════════════════════
# THE EMS FRONTIER CHECK — a CROSS-RUN assertion (2026-09-01)
#
# WHY IT EXISTS.  Campaign 20260901_000816 shipped 53/53 PASS while the SDP leg
# had moved 12.78 % OFF the DP bound and 1.54 % WORSE than the `soc-band`
# heuristic — a 9.9 pp policy regression that passed clean, because every check
# in the suite is PER-RUN and an energy-management result is a COMPARISON.  No
# per-run threshold can express "this policy is no longer competitive"; the
# quantity only exists across three runs of one stimulus.
#
# THE COMPARISON, and it has to be at MATCHED SoC.  Any strategy burns less
# hydrogen by discharging the pack harder, so raw `h2_cum_g` ranks nothing.
# The suite's standing rule ("read it WITH delta_soc") is made arithmetic here
# by converting the SoC difference to its hydrogen equivalent at the measured
# exchange rate:
#
#     eq_H2(run) = h2(run) - (dSoC(run) - dSoC(reference)) / lambda
#
# with `soc-band` as the reference leg (dSoC(ref) - dSoC(ref) = 0, so its own
# eq-H2 is its raw h2).  SIGN, stated because it is the one thing a reader can
# get backwards: a leg that ENDS HIGHER than the reference (a smaller
# discharge, dSoC less negative) is CREDITED its surplus SoC — that charge is
# hydrogen it did not have to burn — and a leg that discharged harder is
# CHARGED for the difference.  On the campaign-2 numbers the SDP leg discharged
# 0.00129 SoC LESS than soc-band, worth 0.00315 g at lambda 0.41, so its
# 0.0161914 g total is credited down to 0.0130451 g — and it is still 1.54 %
# above the reference's 0.0128472 g, which is precisely the finding: the leg
# bought that SoC at the Ag105's 0.2364 SoC/g and is being scored at 0.41.
#
# LAMBDA: the SHARE lever, MEASURED, not modelled.  Campaign 20260831_191509
# priced share-shifting at 0.409-0.415 SoC/g on TWO independent stimuli (the
# 61 s cycle and the 340 s FTP-75, 2.3 % apart; the offline DP solve says
# 0.405).  0.41 is the round centre of that band.  It is the SHARE lever
# specifically because share-shifting is the exchange every leg on this
# frontier can actually make; the Ag105 charge lever (0.2364 SoC/g) is a
# DIFFERENT and worse rate, which is the whole finding the v3 artifact encodes.
EMS_EQ_H2_LAMBDA_SOC_PER_G = 0.41
# The measured band the verdict must be STABLE across.  A verdict that flips
# inside it is not a result — it is a coin flip on a constant we know only to
# ~1.5 % — so such a run renders KNIFE-EDGE: neither PASS nor FAIL, and NOT
# counted as passing.  Deliberately not a "pass if any lambda passes" rule.
EMS_EQ_H2_LAMBDA_BAND = (0.409, 0.415)

# The three legs, by role.  Keyed by role rather than listed, because each one
# means something different in the arithmetic and a bare list would let a
# reader mistake the bound for a competitor.
EMS_FRONTIER = {
    # The CAUSAL HEURISTIC, and the eq-H2 REFERENCE: every other leg's SoC
    # correction is measured against this run's delta_soc.
    "reference": "ems-soc-band",
    # The leg UNDER TEST — the causal optimal-by-construction policy.
    "candidate": "ems-sdp",
    # The NON-CAUSAL LOWER BOUND: not implementable, not a competitor, and the
    # candidate is allowed to sit above it by a stated margin.
    "bound": "ems-dp-replay",
}

# ═════════════════════════════════════════════════════════════════════════════
# THE SECOND FRONTIER — DRIVE-CYCLE SCALE (WP-E, 2026-09-01)
#
# The tuple above is a 61 s synthetic cycle. This one is the same three roles
# over the 340 s EPA FTP-75 segment, so a policy claim can be made at drive-
# cycle scale instead of being extrapolated from a short stimulus.
#
# ⚠️ THE BANDS DO NOT ASSUME THE DP WINS, and that is the substantive
# difference from the 61 s tuple. The offline solve at drive-cycle scale
# measured the DP at **-0.01 % vs `soc-band` at matched terminal SoC** — a TIE,
# not the -14.33 % the 61 s cycle shows. The DP's advantage lives on the
# low-demand synthetic cycle, where share-shifting has room to move; on a real
# drive cycle the demand trajectory leaves almost nothing on the table. So:
#
#   * vs_reference_max is 1.02, NOT 0.98. Demanding a 2 % improvement here
#     would fail a CORRECT candidate against a reference the OPTIMUM itself
#     only ties. 1.02 asks the candidate not to be materially WORSE than the
#     heuristic, which at this scale is the whole available claim.
#   * vs_bound_max is 1.06, unchanged: the bound's own margin argument does not
#     depend on the stimulus, and the lever-class detection the arm exists for
#     is scale-free.
#
# PROVISIONAL: no campaign has evaluated this tuple. 1.02 is derived from the
# offline tie plus the ~0.05 % run-to-run h2 repeat spread, not measured; the
# first campaign that evaluates it should re-derive it from the observed
# spread. Rendered with the qualifier so nobody quotes it as calibrated.
#
# ⚠️⚠️ BOTH STIMULUS SPLITS ARE RESOLVED (operator ruling, 2026-09-01), and
# the previous statement here — "IT CANNOT EVALUATE TODAY" — is RETIRED. The
# three legs are one experiment for the first time:
#
#                       aux_preload_a               chg_i_ceiling_a
#   ems-ftp75-socband   FTP75_PRELOAD_A     0.0 A   0.8 A
#   ems-ftp75-dp        FTP75_PRELOAD_A     0.0 A   0.8 A
#   ems-ftp75-sdp       FTP75_SDP_PRELOAD_A 0.0 A   0.8 A
#
# SPLIT 1 — the candidate leg used to carry 0.20 A less housekeeping load for
# the whole 340 s (~1.1 kJ of bus energy), and eq-H2 corrects for SoC, not for
# demand, so the verdict would have measured the preload rather than the
# policy. RESOLVED BY REMOVAL rather than by either of the two resolutions
# recorded here before: the operator's ruling took `aux_preload_a` to 0.0 on
# every drive-cycle scenario, so the two constants now hold the same value and
# the OC_FC margin that once forced them apart is no longer binding (the
# governed FC peak on the 0.85 branch is 0.7046 A against LIMIT_I_FC_MAX 1.4 A
# — see the FTP75_SDP_PRELOAD_A block in hil_plant_sim.py).
#
# SPLIT 2 — the reference leg declared no `chg_i_ceiling_a` and would have run
# at AG105_I_MAX 2.5 A while the two policy legs capped at 0.8 A. It was INERT
# only because the preload foreclosed `soc-band`'s charge branch, and the
# preload removal REOPENS that branch, so the split would have become live.
# RESOLVED by declaring the siblings' 0.8 A on `ems-ftp75-socband`
# (hil_plant_sim.py, immediately after the FTP-75 scenario loop).
# `ems-ftp75-5050` still declares nothing, and correctly: `hold-5050` never
# commands `charge_goal`, so it is not one of this tuple's legs.
#
# ⚠️ `stimulus_mismatch_exit_affecting` is DELIBERATELY still False below. The
# splits are resolved in the registry, but no campaign has yet evaluated this
# tuple; flipping the flag is the first zero-preload campaign's business, so a
# genuine REGRESSION into a split fails only once the tuple is known to score.
#
# The stimulus-coherence precondition below still refuses the comparison and
# names every disagreeing key with both values if one reappears.
EMS_FRONTIER_FTP75 = {
    "reference": "ems-ftp75-socband",
    "candidate": "ems-ftp75-sdp",
    "bound": "ems-ftp75-dp",
}

# ── The COMPRESSED cycle's own tuple (2026-09-02) ──────────────────────────
# A SEPARATE TUPLE, and it MUST be: `ftp75c` is a different `ems_v_profile`, a
# different `duration_s` and a different `drag`, so slotting an `ems-ftp75c-*`
# leg into EMS_FRONTIER_FTP75 would fail the stimulus-coherence precondition
# outright - correctly, because the two cycles are two vehicles.
# The roles mirror the FTP-75 tuple's exactly, so the three records read on one
# scale.
EMS_FRONTIER_FTP75C = {
    "reference": "ems-ftp75c-socband",
    "candidate": "ems-ftp75c-sdp",
    "bound": "ems-ftp75c-dp",
}

# The registry the runner iterates. Ordered: the 61 s tuple is the calibrated
# one and reads first.  Each entry carries its OWN thresholds — a single pair
# of module constants would have silently applied the 61 s cycle's 0.98 to a
# stimulus whose optimum ties, which is the trap this dict exists to avoid.
EMS_FRONTIERS = [
    {
        "id": "cycle61",
        "label": "61 s synthetic cycle",
        "roles": EMS_FRONTIER,
        "vs_reference_max": 0.98,
        "vs_bound_max": 1.06,
        # ⚠️ RE-PROVISIONALIZED FOR THE CHARGER ERA (WP-1C, 2026-09-02). Both
        # THRESHOLDS ARE HELD; what changed is the MARGIN behind the 0.98 ask,
        # and it changed a lot.
        # The reference leg (`ems-soc-band`) is the only one of the three that
        # charges, so ETA_CHG 0.88 makes ITS hydrogen cheaper while the
        # charge-free candidate and bound do not move at all. Governor walk,
        # 1:1 era -> 0.88 era:
        #     reference h2   0.013677 -> 0.012264 g  (-10.3 %), dSoC unmoved
        #     candidate/bound          unchanged (zero charge windows)
        #     vs_reference   0.8588   -> 0.9578
        #     vs_bound       1.0009   -> 1.0009
        # So the ask survives, with 2.3 % of headroom where it used to have
        # 14 %. IS 0.98 STILL HONEST? Yes, and deliberately so: 2 % is still
        # outside the ~0.05 % run-to-run repeat spread of the h2 totals, and
        # the offline eta-era result is a 4.2 % candidate win — an ask the
        # policy clears, not one it scrapes. But it is now a TIGHT ask, and the
        # measured campaign ratio (0.9003 x, campaign 20260901_151156) sat
        # 4.8 % below the contemporaneous walk prediction, so a first eta-era
        # reading anywhere in 0.93-0.98 is the expected outcome and a reading
        # just over 0.98 is a calibration question, not a policy failure.
        "provisional_note": (
            "GRID-WIDENING RE-DERIVATION (2026-09-02): with the DP grid and the MPC ladder spanning the full firmware band [0.15, 0.85], the governor walk gives this tuple vs_reference 0.9570-0.9582 and vs_bound 1.0012-1.0025 across lambda [0.409, 0.415]. ⚠️ THE OLD-GRID FIGURES ELSEWHERE IN THIS NOTE ARE PRE-WIDENING and are not comparable: the old control set could not reach the 0.85 the SDP rails at, so an SDP candidate was divided by a bound solved over a narrower set. "
            "PROVISIONAL for the ETA_CHG 0.88 charger era (WP-1C, 2026-09-02) "
            "— the THRESHOLDS are unchanged but the margin behind 0.98 is not. "
            "The reference leg is the tuple's only charging leg, so its "
            "hydrogen falls ~10 % while the charge-free candidate and bound do "
            "not move: the governor-walk vs_reference goes 0.859 -> 0.958. "
            "Re-derive both thresholds from the first eta-era campaign that "
            "evaluates this tuple; a reading just over 0.98 is a calibration "
            "event, not a policy failure. BLEED AND LOSS-MAP ERA "
            "(2026-09-02): re-walked with the static-loss map and the "
            "per-node bleed, this tuple reads vs_reference 0.9696 (candidate "
            "eq-H2 0.016354 g against the reference's 0.016868) and vs_bound "
            "1.0006 (bound 0.016346). Both thresholds HELD"),
        # A stimulus mismatch here would be a defect worth failing the run for:
        # the three legs are documented to share one stimulus object.
        "stimulus_mismatch_exit_affecting": True,
    },
    {
        "id": "ftp75",
        "label": "340 s EPA FTP-75 drive cycle",
        "roles": EMS_FRONTIER_FTP75,
        "vs_reference_max": 1.02,
        "vs_bound_max": 1.06,
        "provisional_note": (
            "GRID-WIDENING RE-DERIVATION (2026-09-02): with the DP grid and the MPC ladder spanning the full firmware band [0.15, 0.85], the governor walk gives this tuple vs_reference 0.9585-0.9656 and vs_bound 0.9921-0.9983 across lambda [0.409, 0.415]. ⚠️ THE OLD-GRID FIGURES ELSEWHERE IN THIS NOTE ARE PRE-WIDENING and are not comparable: the old control set could not reach the 0.85 the SDP rails at, so an SDP candidate was divided by a bound solved over a narrower set. "
            "PROVISIONAL — no campaign has evaluated this tuple. The "
            "vs-reference band 1.02 is derived from the OFFLINE solve's -0.01 % "
            "DP-vs-`soc-band` tie at matched terminal SoC plus the ~0.05 % "
            "run-to-run h2 spread; it is NOT measured, and it deliberately does "
            "NOT assume the DP wins at drive-cycle scale. Re-derive it from the "
            "first campaign that evaluates this frontier. CHARGER ERA (WP-1C, "
            "2026-09-02): the reference leg is the tuple's only charging leg, "
            "so the governor-walk vs_reference moves 0.984 -> 0.964 and "
            "vs_bound 0.9975 -> 0.9977 — both thresholds are cleared with MORE "
            "room than before and neither is changed. Note the -0.01 % offline "
            "DP-vs-`soc-band` tie that 1.02 was derived from is itself an "
            "old-era number: at eta 0.88 the DP's eq-H2 margin over `soc-band` "
            "on this stimulus is -3.4 %, so 1.02 is now conservative rather "
            "than knife-edge. BLEED AND LOSS-MAP ERA (2026-09-02): re-walked "
            "with the static-loss map and the per-node bleed, this tuple reads "
            "vs_reference 0.9737 (candidate eq-H2 0.055628 g against the "
            "reference's 0.057134) and vs_bound 0.9979 (bound 0.055746). Both "
            "thresholds HELD, again with more room; the bound leg's own table "
            "was regenerated as a loss-map-era solve in the same change"),
        # The preload split IS resolved (2026-09-01) — see the block above —
        # so the precondition is expected to PASS from here on. The flag stays
        # False for ONE campaign more: no campaign has evaluated this tuple, so
        # the first one to do so should confirm the precondition passes and the
        # thresholds hold before a mismatch is made exit-affecting. Flip it to
        # True after that campaign, so a REGRESSION into a split does fail.
        "stimulus_mismatch_exit_affecting": False,
    },
    # ── THE TWO MPC TUPLES (2026-09-02) ────────────────────────────────────
    # Each REUSES the sibling tuple's reference and bound and its thresholds
    # verbatim; only the CANDIDATE differs.  That is deliberate and is the whole
    # value of the comparison: `cycle61-mpc` and `cycle61` share one stimulus
    # object, one reference leg and one bound, so the difference between the two
    # records is the difference between the SDP leg and `mpc-sto` and nothing
    # else (`sdp-v4` when the figures below were taken; `sdp-v6` since
    # 2026-09-03, and the two agree on every traversed row).
    #
    # ⚠️ THE CANDIDATE STRATEGY CHANGED 2026-09-02 (operator ruling): both MPC
    # tuples' candidate legs now bind `mpc-sto`, the stochastic law, and
    # `mpc-det` is the ablation on `ems-mpc-det`. The OFFLINE figures in the
    # notes below were RE-WALKED under the new bindings and the loss-map demand
    # era in the same change, so they are post-swap. What is still PRE-SWAP is
    # every LIVE figure: campaigns 20260902_011926 and _041414 ran `mpc-det` on
    # these legs, so a measured number attributed to a campaign is a reading of
    # the deterministic law on a leg the stochastic one now drives.
    #
    # ⚠️ `stimulus_mismatch_exit_affecting` is False on BOTH for one campaign,
    # exactly as `ftp75` carries it: the stimulus keys agree in the registry by
    # construction (every one is the sibling's value, most of them the sibling's
    # OBJECT), but no campaign has evaluated either tuple, so a genuine
    # regression into a split should fail only once the tuple is known to score.
    # Flip both to True after the first campaign that evaluates them.
    #
    # ⚠️ THE VS-BOUND ARM IS STRUCTURALLY NEAR 1.0 HERE, and more so than for
    # the SDP tuples: `mpc-det` opens ZERO charge windows in every Gate-2 walk,
    # so it and the bound differ only along the share lever (`mpc-sto` opens
    # zero charge windows in the post-swap Gate-2 walk too) — and the eq-H2
    # exchange rate IS that lever's rate, which makes the two coincide by
    # construction (campaign 20260901_080905; design section 7.4.1).  The walk
    # reads 1.0007x on `cycle61-mpc`.  DO NOT TIGHTEN `vs_bound_max` on a
    # charge-free reading: the arm detects lever-class deviations and does not
    # measure optimality.
    {
        "id": "cycle61-mpc",
        "label": "61 s synthetic cycle, MPC candidate",
        "roles": {
            "reference": "ems-soc-band",
            "candidate": "ems-mpc",
            "bound": "ems-dp-replay",
        },
        # The `cycle61` tuple's thresholds verbatim — see the note above.
        "vs_reference_max": 0.98,
        "vs_bound_max": 1.06,
        "provisional_note": (
            "GRID-WIDENING RE-DERIVATION (2026-09-02): with the DP grid and the MPC ladder spanning the full firmware band [0.15, 0.85], the governor walk gives this tuple vs_reference 0.9519-0.9572 and vs_bound 0.9960-1.0013 across lambda [0.409, 0.415]. ⚠️ THE OLD-GRID FIGURES ELSEWHERE IN THIS NOTE ARE PRE-WIDENING and are not comparable: the old control set could not reach the 0.85 the SDP rails at, so an SDP candidate was divided by a bound solved over a narrower set. "
            "⚠️ THE CANDIDATE FAILS THE OFFLINE GATE 1. `mpc-sto`'s governor-aware stage model predicts the DELIVERED share on `ems-soc-band` to a mean of 0.00971 and a max of 0.25000 against a 5e-03 acceptance; `mpc-det` on the same gate reads 0.000323. The mechanism is known and is the same one EMS_STRATEGY_META's role note records: a 1 Hz re-command landing in an `open_feedforward` stage drops the governor into a feedforward slew the stage model does not represent. The leg ships because the LIVE prediction error is inside its 0.30 band (campaigns 20260902_011926 and _041414: closed-loop median 1e-5, open-loop max 0.219), but a frontier reading here carries that failing gate inside it. "
            "PROVISIONAL, AND RE-DERIVED 2026-09-02 FOR TWO SIMULTANEOUS "
            "CHANGES: the candidate now binds `mpc-sto`, not `mpc-det`, and "
            "every walk carries the static-loss map and the per-node bleed. "
            "The Gate-2 governor walk (dv0 0.030223, soc0 0.7, loss map on) "
            "gives eq-H2 0.016347 g against the reference's 0.016868 and the "
            "bound's 0.016346, i.e. vs_reference 0.9691 and vs_bound 1.0001, "
            "so both thresholds are cleared offline; BUT the walk's plant IS "
            "the MPC's own prediction model (the inverse-crime condition, "
            "design section 7.1), so that clearance is not evidence about the "
            "live plant. The pre-round `mpc-det` walk read 0.9701 / 1.0007. "
            "The thresholds are the `cycle61` tuple's, taken unchanged so the "
            "two records are read on one scale. Re-derive from the first "
            "campaign that evaluates this tuple, and read the vs-bound arm "
            "under the structural caveat above"),
        "stimulus_mismatch_exit_affecting": False,
    },
    {
        "id": "ftp75-mpc",
        "label": "340 s EPA FTP-75 drive cycle, MPC candidate",
        "roles": {
            "reference": "ems-ftp75-socband",
            "candidate": "ems-ftp75-mpc",
            "bound": "ems-ftp75-dp",
        },
        # The `ftp75` tuple's thresholds verbatim — including its 1.02
        # vs-reference ask, which deliberately does NOT assume a win at
        # drive-cycle scale (the offline DP-vs-`soc-band` result on this
        # stimulus is a tie).
        "vs_reference_max": 1.02,
        "vs_bound_max": 1.06,
        "provisional_note": (
            "GRID-WIDENING RE-DERIVATION (2026-09-02): with the DP grid and the MPC ladder spanning the full firmware band [0.15, 0.85], the governor walk gives this tuple vs_reference 0.9576-0.9650 and vs_bound 0.9912-0.9977 across lambda [0.409, 0.415]. ⚠️ THE OLD-GRID FIGURES ELSEWHERE IN THIS NOTE ARE PRE-WIDENING and are not comparable: the old control set could not reach the 0.85 the SDP rails at, so an SDP candidate was divided by a bound solved over a narrower set. "
            "⚠️ THE CANDIDATE FAILS THE OFFLINE GATE 1. `mpc-sto`'s governor-aware stage model predicts the DELIVERED share on `ems-soc-band` to a mean of 0.00971 and a max of 0.25000 against a 5e-03 acceptance; `mpc-det` on the same gate reads 0.000323. The mechanism is known and is the same one EMS_STRATEGY_META's role note records: a 1 Hz re-command landing in an `open_feedforward` stage drops the governor into a feedforward slew the stage model does not represent. The leg ships because the LIVE prediction error is inside its 0.30 band (campaigns 20260902_011926 and _041414: closed-loop median 1e-5, open-loop max 0.219), but a frontier reading here carries that failing gate inside it. "
            "PROVISIONAL, AND RE-DERIVED 2026-09-02 for the same two "
            "simultaneous changes as `cycle61-mpc`: the candidate binds "
            "`mpc-sto`, and every walk carries the static-loss map and the "
            "per-node bleed. The Gate-2 governor walk gives eq-H2 0.055622 g "
            "against the reference's 0.057134 and the bound's 0.055746, "
            "i.e. vs_reference 0.9735 and vs_bound 0.9978; the pre-round "
            "`mpc-det` reading was vs_reference 0.9748 with no vs-bound "
            "arm at all, because the shipped FTP-75 table then carried a "
            "stale stimulus fingerprint. It has been regenerated as a "
            "loss-map-era solve, so BOTH arms now have a prediction. "
            "The thresholds are the `ftp75` tuple's, unchanged. Re-derive from "
            "the first campaign, and note the walk's clearance is an "
            "inverse-crime result (design section 7.1)"),
        "stimulus_mismatch_exit_affecting": False,
    },
    # ── THE TWO COMPRESSED-CYCLE TUPLES (2026-09-02, the ftp75c round) ─────
    # THRESHOLDS ARE THE `ftp75` TUPLE'S, TAKEN UNCHANGED.  That is the honest
    # starting point rather than a derivation: the compensated cycle's optimum
    # has never been solved before this round, and inventing a tighter ask from
    # a single offline walk would be a number with no evidence behind it.
    #
    # ⚠️ WHY THE REGEN CREDIT DOES NOT MOVE THESE RATIOS.  The regen manager is
    # a COMMON layer over every strategy and the credit `i_regen[k]` is
    # SHARE-INDEPENDENT, so all three legs receive the SAME +1.17 C on the SAME
    # six windows.  The ratios move only through second-order coupling (a
    # slightly higher SoC changes the pack terminal voltage and hence the bus
    # current the battery branch supplies), and against a credit that is 1.4 %
    # of the cycle drain and a SoC that moves 5.5e-5 that coupling is far below
    # the ~50 ppm same-config h2 repeatability floor (campaign 20260902_041414).
    # THE CORRECT READING of these two tuples is that `ftp75c` VALIDATES THE
    # REGEN MODEL END TO END AND CLOSES THE DP'S REGEN DIVERGENCE.  It is NOT
    # expected to reorder the strategies, and a REORDERING HERE IS A DEFECT
    # SIGNAL RATHER THAN A RESULT.
    {
        "id": "ftp75c",
        "label": "170 s compressed FTP-75, compensated road load",
        "roles": EMS_FRONTIER_FTP75C,
        "vs_reference_max": 1.02,
        "vs_bound_max": 1.06,
        "provisional_note": (
            "GRID-WIDENING RE-DERIVATION (2026-09-02): with the DP grid and the MPC ladder spanning the full firmware band [0.15, 0.85], the governor walk gives this tuple vs_reference 1.0092-1.0168 and vs_bound 1.0090-1.0162 across lambda [0.409, 0.415]. ⚠️ THE OLD-GRID FIGURES ELSEWHERE IN THIS NOTE ARE PRE-WIDENING and are not comparable: the old control set could not reach the 0.85 the SDP rails at, so an SDP candidate was divided by a bound solved over a narrower set. "
            "PROVISIONAL - no campaign has evaluated this tuple. "
            "⚠️ ON THIS CYCLE THE CANDIDATE IS PREDICTED WORSE THAN THE "
            "REFERENCE, AND A PASS HERE ASSERTS 'NO MORE THAN 2 % WORSE', "
            "NOT 'BETTER'. The governor walk (loss map on, dv0 0.013522, "
            "soc0 0.7) gives reference h2 0.006455604 g / dSoC -0.001859, "
            "candidate 0.009897751 / -0.000476, bound 0.006619509 / "
            "-0.001793, i.e. vs_reference 1.0092-1.0168 and vs_bound "
            "1.0090-1.0162 across the whole lambda band [0.409, 0.415] - "
            "ABOVE 1.0 on BOTH arms at EVERY lambda. That is not a defect "
            "and it is not a surprise: the compensated cycle's demand is "
            "small enough that the SDP leg holds its 0.85 share rail "
            "throughout, spending hydrogen to hold SoC, and the eq-H2 "
            "correction prices that back to near parity rather than to a "
            "win. READ A PASS ACCORDINGLY. The 1.02 band is the `ftp75` "
            "tuple's, taken verbatim so the compressed and uncompressed "
            "records read on one scale, and it is NOT derived from this "
            "walk; the vs-reference arm sits within 0.4 % of it at the top "
            "of the lambda band, so a first campaign reading just over 1.02 "
            "is a calibration event rather than a policy failure. "
            "⚠️ THE BOUND IS NOT STRICTLY BELOW THE REFERENCE ON THIS "
            "STIMULUS: the offline solve reads the DP +0.06 % of hydrogen "
            "above the causal `soc-band` walk at matched terminal SoC "
            "(0.00598238 g against 0.00597881 g, match residual +1.82e-06 "
            "SoC). That is the discrete control grid, not a defect - "
            "LAMBDA_TERM to terminal SoC is monotone but NOT continuous - and "
            "it is why the vs-bound arm reads ~1.01 here rather than under 1. "
            "What IS new here and must be checked "
            "first is the REFERENCE leg: `ems-ftp75c-socband` runs "
            "PER-SCENARIO charge thresholds (0.18074 A enter / 0.33107 A exit) "
            "because the shipped 0.60 A entry threshold sits ABOVE the "
            "compensated cycle's entire source total (peak 0.330 A) and would "
            "have made the reference a charge-saturated control. If that leg "
            "reads as permanently charging, the thresholds are wrong and the "
            "tuple's ratios mean nothing. The regen credit is common to all "
            "three legs and share-independent, so it is NOT expected to move "
            "either ratio — see the block above. Re-derive both thresholds "
            "from the first campaign that evaluates this tuple"),
        # False for the same reason `ftp75` carries it: the stimulus keys agree
        # in the registry by construction (all five legs share one profile
        # OBJECT and one `drag` value), but no campaign has evaluated the tuple,
        # so a genuine regression into a split should fail only once it scores.
        "stimulus_mismatch_exit_affecting": False,
    },
    {
        "id": "ftp75c-mpc",
        "label": "170 s compressed FTP-75, compensated road load, MPC candidate",
        "roles": {
            "reference": "ems-ftp75c-socband",
            "candidate": "ems-ftp75c-mpc",
            "bound": "ems-ftp75c-dp",
        },
        # The `ftp75c` tuple's thresholds verbatim, on the reasoning the two
        # MPC tuples above use: reference and bound are the sibling's, so the
        # difference between the two records is the difference between the SDP
        # leg (`sdp-v6` since 2026-09-03) and `mpc-sto` and nothing else.
        "vs_reference_max": 1.02,
        "vs_bound_max": 1.06,
        "provisional_note": (
            "GRID-WIDENING RE-DERIVATION (2026-09-02): with the DP grid and the MPC ladder spanning the full firmware band [0.15, 0.85], the governor walk gives this tuple vs_reference 0.9808-0.9905 and vs_bound 0.9801-0.9903 across lambda [0.409, 0.415]. ⚠️ THE OLD-GRID FIGURES ELSEWHERE IN THIS NOTE ARE PRE-WIDENING and are not comparable: the old control set could not reach the 0.85 the SDP rails at, so an SDP candidate was divided by a bound solved over a narrower set. "
            "⚠️ THE CANDIDATE CARRIES THE SAME FAILING OFFLINE GATE 1 the two "
            "MPC tuples above record: `mpc-sto`'s governor-aware stage model "
            "predicts the delivered share on `ems-soc-band` to a mean of "
            "0.00971 against a 5e-03 acceptance, and the leg ships on its LIVE "
            "prediction error being inside the 0.30 band. "
            "PROVISIONAL — no campaign has evaluated this tuple. Thresholds "
            "are `ftp75c`'s, unchanged. THE GOVERNOR WALK gives candidate h2 "
            "0.003311646 g / dSoC -0.003127 against the same reference and "
            "bound, i.e. vs_reference 0.9860-0.9930 and vs_bound "
            "0.9854-0.9927 across the lambda band — both cleared with room, "
            "and BOTH BELOW 1.0, which is the opposite side of the bound from "
            "the SDP candidate. ⚠️ Read that under the inverse-crime "
            "caveat the other two MPC tuples carry: the walk's plant IS the "
            "MPC's own prediction model, so the clearance is evidence about "
            "the plumbing and not about the live plant. ⚠️ ONE THING IS "
            "GENUINELY UNTESTED "
            "HERE and is not true of any other MPC leg: the planner's "
            "prediction model now carries the REGEN CREDIT, so its charge "
            "enumeration runs against a mask that excludes every "
            "regen-capable stage. The credit is share-independent, so it "
            "cannot change which candidate the search prefers on a braking "
            "stage; what it CAN change is the terminal SoC the Huber cost is "
            "priced against. Read `mpc_share_pred_err` on this leg before "
            "reading its ratios"),
        "stimulus_mismatch_exit_affecting": False,
    },
]
assert len({f["id"] for f in EMS_FRONTIERS}) == len(EMS_FRONTIERS), \
    "duplicate frontier id"
assert all(set(f["roles"]) == {"reference", "candidate", "bound"}
           for f in EMS_FRONTIERS), \
    "every frontier needs exactly the three roles the arithmetic is written for"

# The scenario metadata keys that define a leg's STIMULUS. Two legs of one
# frontier must agree on all of them or their hydrogen totals measure the
# stimulus difference rather than the policy. `ems_v_profile` is compared by
# VALUE, not identity: the shipped scenarios deliberately share one list
# object, but a future leg built from an equal copy is still the same
# stimulus and must not be refused for it.
# `eta_chg` (WP-1C, 2026-09-02) is the CHARGER ERA, and it belongs here for
# exactly the reason `chg_i_ceiling_a` does: it sets what a coulomb of charge
# COSTS the fuel cell, so two legs run under different eras are ranked on the
# plant rather than on the policy. The 1:1 era over-drew the bus by ~1.8x while
# charging, which is a larger effect than any of the policy differences this
# frontier is trying to measure.
#
# ⚠️ IT IS NOT A REGISTRY KEY. No scenario declares `eta_chg` — it is a plant
# constant the child stamps into its own sidecar — so the registry lookup below
# yields None for every leg and the key can only fire through the RESOLVED
# override (`etas`), the same way `electrical_resolved` does. It is listed here
# rather than appended after the loop because, unlike the mode, it is a
# property of the STIMULUS in the same sense the preload is, and a reader
# looking for "what makes two legs comparable" should find it in this tuple.
# `drag` JOINED 2026-09-02 (the ftp75c round).  It is a REGISTRY key like the
# first five, not a resolved one like `eta_chg`, and it belongs here for the
# reason `ems_v_profile` does: the road-load profile changes the TRACTIVE
# DEMAND for a given speed profile - by roughly 4.5x between `rig` and
# `scaled-air` - so two legs on different profiles are not on one stimulus even
# when every other key agrees.  A frontier whose reference ran the rig road load
# and whose candidate ran the compensated one would compare two vehicles.
EMS_FRONTIER_STIMULUS_KEYS = ("ems_v_profile", "duration_s", "ems_run_exit_s",
                              "aux_preload_a", "chg_i_ceiling_a", "drag",
                              "eta_chg")


def ems_frontier_stimulus_mismatches(roles, modes=None, etas=None):
    """Keys on which the legs of one frontier disagree.  PURE.

    Returns a list of (key, {leg_name: value}) for every stimulus key the legs
    do not agree on, in EMS_FRONTIER_STIMULUS_KEYS order.  A leg this checkout
    does not register is skipped — `evaluate_ems_frontier` already reports a
    missing leg, and inventing a mismatch for it would double-count.

    The registry keys are read from SCENARIOS rather than from the run records
    because a stimulus is a property of the PLAN, so the mismatch is knowable
    before a single run starts — and must be, or a campaign spends 17 minutes
    producing numbers that cannot be compared.

    `modes` is the optional exception, and it is deliberately RESOLVED rather
    than registry-read (M3, 2026-09-01f).  Pass {leg_name: run record "mode"}
    and an extra `electrical_resolved` key is compared.  It CANNOT come from
    SCENARIOS: `ems-soc-band`, `ems-sdp` and the FTP-75 legs all declare
    `"electrical": "any"`, so the declared field agrees while the runs need not
    — a `--electrical-pref simple` campaign resolves an `"any"` leg to simple
    and a `"hifi"`-pinned leg (`ems-dp-replay`) to hifi.  That split is not
    cosmetic: SIMPLE MODE DOES NOT CHARGE THE SOURCES FOR THE Ag105
    (`hil_plant_sim.py:1448`), so a charging leg run there harvests FREE energy
    and would be ranked against a hi-fi DP bound that paid for every coulomb.
    Comparing the declared field instead would fire on every mixed
    `"any"`/`"hifi"` frontier even when both legs actually ran hifi, so the
    resolved value is the only correct one.  Omit `modes` (the default) and the
    function is registry-only exactly as before."""
    names = [n for n in roles.values() if n in SCENARIOS]
    out = []
    for key in EMS_FRONTIER_STIMULUS_KEYS:
        vals = {n: SCENARIOS[n].get(key) for n in names}
        if key == "eta_chg":
            # RESOLVED-ONLY, and it REPLACES the registry value rather than
            # being compared beside it: no scenario declares this key, so the
            # registry side is None for every leg and comparing it would be
            # vacuous.
            # ⚠️ ONLY LEGS THAT PRODUCED A RUN. `None` is the 1:1-era sentinel
            # here, so a leg that has not run yet cannot be given None — that
            # would read as "this leg ran under the old charger" and fire a
            # mismatch on every PARTIAL campaign, which for the cycle61 tuple
            # is exit-affecting. `etas` therefore carries an entry per leg WITH
            # a record, value possibly None, and legs absent from it are simply
            # not compared (`missing` already reports them).
            if not etas:
                continue
            vals = {n: etas[n] for n in names if n in etas}
        first = next(iter(vals.values()), None) if vals else None
        if any(v != first for v in vals.values()):
            out.append((key, vals))
    if modes:
        # Only legs that actually reported a mode: a leg with no record yet is
        # `missing`, and a None here would read as a mismatch against a real
        # mode.  Appended last so the established key order is untouched.
        vals = {n: modes[n] for n in names if modes.get(n)}
        first = next(iter(vals.values()), None) if vals else None
        if any(v != first for v in vals.values()):
            out.append(("electrical_resolved", vals))
    return out

# THE TWO ASSERTIONS, and why each number is what it is.
#
#   <= 0.98 x reference.  The candidate is an OPTIMAL-BY-CONSTRUCTION policy
#   against a causal heuristic; "no worse" is too weak a claim to be worth
#   running, and the campaign that motivated this check failed at 1.0154 x.
#   0.98 asks for a 2 % improvement — comfortably inside the 8.39 % the first
#   calibrated campaign measured, and outside the ~0.05 % run-to-run repeat
#   spread of the h2 totals.
EMS_FRONTIER_VS_REFERENCE_MAX = 0.98
#   <= 1.06 x bound.  The DP leg has full foreknowledge of the cycle, so the
#   causal leg CANNOT reach it and the bound is a proximity claim, not a
#   ranking. 6 % is anchored on campaign 20260831_222036's measured +1.79 %,
#   with room for the SoC-correction term's own uncertainty.
#
#   ⚠️ WHAT THIS ARM ACTUALLY DETECTS — re-described after its FIRST live
#   evaluation (campaign 20260901_024231, which returned 1.0000 x).  When BOTH
#   legs are CHARGE-FREE, the vs-bound ratio is STRUCTURALLY ~1.0 and is NOT
#   evidence of optimality.  The arithmetic: two charge-free runs differ only
#   along the SHARE lever, so their (h2, dSoC) pair moves along that lever's own
#   exchange line — and lambda IS that lever's rate.  eq-H2 subtracts the SoC
#   difference AT lambda, so it subtracts exactly the difference the two points
#   have, and the corrected totals coincide.  Campaign 024231 measured the
#   implied lever between candidate and bound at 0.41021 SoC/g against
#   lambda = 0.410: agreement to 0.05 %, which is the degeneracy, not a result.
#   That number is rendered as `implied_lever_soc_per_g` below so a reader can
#   see WHY the ratio is 1.0 rather than inferring a near-optimal policy.
#   So the arm is a LEVER-CLASS DETECTOR, not an optimality gate: it fires when
#   the candidate reaches its result through a lever priced DIFFERENTLY from
#   lambda — which is precisely what campaign 20260901_000816's failing SDP leg
#   did, buying SoC through the Ag105 at 0.2364 SoC/g and being scored at 0.41.
#   The DISCRIMINATING arm on a charge-free reading is vs-reference.
#
#   ⚠️ DO NOT TIGHTEN 1.06 -> 1.03 ON A CHARGE-FREE READING.  The earlier
#   "TIGHTEN TO 1.03 after two campaigns" intent is AMENDED, not carried: a
#   campaign in which the candidate never opens the charger measures the
#   degeneracy above and NOT the candidate's spread, so tightening on it would
#   buy no detection power and would make the arm fail on nothing but the
#   SoC-correction's own numerical noise.  Tighten only against campaigns whose
#   candidate leg USED a second lever (a non-zero charge-window count on the
#   candidate), and re-derive the number from the implied-lever spread those
#   campaigns show.
EMS_FRONTIER_VS_BOUND_MAX = 1.06
# MATCHED-dSoC PRECONDITION.  The eq-H2 correction is a LINEAR extrapolation at
# one exchange rate; it is credible over a small SoC gap and not over a large
# one.  0.010 SoC is ~5x the largest gap any campaign has produced (0.00129)
# and ~14 % of a 61 s run's total swing, so a run that exceeds it is not a
# leg to be corrected — it is a different experiment, and the check says
# UNVERIFIED rather than pretending the arithmetic still holds.
EMS_FRONTIER_DSOC_MATCH_MAX = 0.010


def ems_eq_h2(h2, dsoc, dsoc_ref, lam):
    """SoC-corrected hydrogen: h2 minus the SoC surplus priced at `lam`.

    Pure arithmetic, split out so a test can drive it on recorded campaign
    numbers without building result dicts."""
    return float(h2) - (float(dsoc) - float(dsoc_ref)) / float(lam)


def _ems_frontier_leg(results, name):
    """The one scenario result for `name`, or None."""
    for r in results:
        if r.get("kind") == "scenario" and r.get("name") == name:
            return r
    return None


def evaluate_ems_frontier(results, planned_names=None, spec=None):
    """Score the EMS frontier across `results`.  PURE.

    Returns None when NO frontier leg was planned at all (a scenarios-only
    subset, a replay-only run, `--pi-live`): there is nothing to say, and
    manufacturing an UNVERIFIED record for a plan that never intended the
    comparison would be noise.  Once ANY leg ran, a missing/faulted/skipped
    sibling is UNVERIFIED and NAMED — never silent, because a silently dropped
    leg is exactly how the regression this check exists for went unnoticed.

    `planned_names` (M4) is the set of run names the CURRENT plan contains.
    Supplying it lets a PARTIAL report distinguish "this leg is not in the
    plan" from "this leg is in the plan and has not run yet" — the second is
    what every intermediate rewrite of a full campaign's results.json says, and
    blaming the plan for it is simply wrong.

    Verdicts:
      PASS        both assertions hold at every lambda in the band.
      FAIL        at least one fails at every lambda in the band.
      KNIFE-EDGE  the verdict flips inside the measured lambda band — not a
                  result either way; counts as NOT passing.
      UNVERIFIED  a leg is missing, skipped, faulted, or lacks its energy
                  metrics; or the candidate's delta_soc is too far from the
                  reference's for the linear correction to be credible.

    `exit_affecting` (H1) splits the not-passing verdicts by whether the SUITE'S
    EXIT CODE should reflect them, because "UNVERIFIED" covers two different
    situations and only one of them is a defect:

      False  nothing RAN that is unusable — every absent leg is absent from the
             plan, or was explicitly SKIPPED (`--pi-live`, a filtered plan, a
             partial report's not-yet-run legs). The report still says
             UNVERIFIED, loudly and by name; the run is not failed for it.
             This is the documented `--pi-live` behaviour, which the exit path
             used to contradict by returning 1 on a clean skip-only campaign.
      True   a leg RAN and its numbers cannot be used (own checks failed, no
             energy metrics), the matched-dSoC precondition failed, an eq-H2
             came out non-positive, or the verdict itself is FAIL/KNIFE-EDGE.

    Rendering does NOT branch on the flag: an UNVERIFIED frontier reads the
    same either way, and the difference is only in what the exit code claims.
    """
    # WP-E: `spec` is the frontier registry entry (EMS_FRONTIERS). It defaults
    # to the 61 s tuple so every pre-existing caller and test keeps its exact
    # behaviour; the thresholds now come from the SPEC rather than from module
    # constants, because the drive-cycle frontier's optimum TIES its reference
    # and the 61 s cycle's 0.98 would fail a correct candidate there.
    if spec is None:
        spec = EMS_FRONTIERS[0]
    roles = spec["roles"]
    vs_ref_max = float(spec["vs_reference_max"])
    vs_bnd_max = float(spec["vs_bound_max"])
    legs, missing = {}, []
    exit_affecting = False
    any_planned = False
    planned = set(planned_names or ())
    for role, name in roles.items():
        r = _ems_frontier_leg(results, name)
        if r is None:
            # M4: a leg the plan CONTAINS but has not reached yet is a property
            # of the rewrite instant, not of the plan. Only a leg genuinely
            # absent from the plan gets blamed on the plan.
            if name in planned:
                missing.append("%s (%s): planned but not yet run (partial "
                               "report)" % (name, role))
            else:
                missing.append("%s (%s): not in this run's plan" % (name, role))
            continue
        any_planned = True
        m = r.get("metrics") or {}
        if r.get("skipped"):
            missing.append("%s (%s): SKIPPED — %s"
                           % (name, role, r.get("skip_reason") or "no reason"))
            continue
        if not r.get("passed"):
            # A leg that failed its own checks may have truncated, latched, or
            # run a different trajectory than the comparison assumes. Its
            # numbers are not comparable and must not be quietly used.
            missing.append("%s (%s): the run did NOT pass its own checks, so "
                           "its energy totals are not comparable"
                           % (name, role))
            exit_affecting = True
            continue
        if m.get("final_h2_cum_g") is None or m.get("delta_soc") is None:
            missing.append("%s (%s): no h2_cum_g / delta_soc in the CSV"
                           % (name, role))
            exit_affecting = True
            continue
        legs[role] = {"name": name, "h2": float(m["final_h2_cum_g"]),
                      "dsoc": float(m["delta_soc"])}
    if not any_planned:
        return None

    rec = {
        "id": spec.get("id", "cycle61"),
        "label": spec.get("label", "61 s synthetic cycle"),
        "provisional_note": spec.get("provisional_note"),
        "lambda_soc_per_g": EMS_EQ_H2_LAMBDA_SOC_PER_G,
        "lambda_band": list(EMS_EQ_H2_LAMBDA_BAND),
        "vs_reference_max": vs_ref_max,
        "vs_bound_max": vs_bnd_max,
        "roles": dict(roles),
        "legs": legs, "missing": missing,
        "exit_affecting": exit_affecting,
    }
    # ── STIMULUS COHERENCE (WP-E) ───────────────────────────────────────────
    # Checked BEFORE the legs are compared, and before `missing` is reported,
    # because it invalidates the comparison outright: eq-H2 corrects for SoC,
    # not for demand, so legs that ran different auxiliary loads or different
    # profiles would be ranked on the stimulus difference. Registry-derived, so
    # it fires even on a partial report — a campaign should not spend 17 minutes
    # producing numbers that were never comparable.
    # M3: the RESOLVED electrical mode joins the registry keys. Read off each
    # leg's own run record, so it reflects what ran rather than what the
    # scenario declared — see the function's docstring for why the declared
    # field cannot serve.
    _modes = {}
    _etas = {}
    for _name in roles.values():
        _r = _ems_frontier_leg(results, _name)
        if _r is None:
            continue
        if _r.get("mode"):
            _modes[_name] = _r["mode"]
        # WP-1C: recorded for EVERY leg that produced a run, INCLUDING the ones
        # whose era is None — None is the 1:1-charger sentinel, not "unknown",
        # so it must be able to disagree with a 0.88 sibling. Legs with no
        # record at all are left out; see the mismatch function.
        _etas[_name] = _r.get("eta_chg")
    stim = ems_frontier_stimulus_mismatches(roles, modes=_modes, etas=_etas)
    if stim:
        rec["stimulus_mismatch"] = [
            {"key": k, "values": {n: (list(v) if isinstance(v, list) else v)
                                  for n, v in vals.items()}}
            for k, vals in stim]
        rec.update(
            verdict="UNVERIFIED", passed=False,
            # OR, never assignment: `exit_affecting` may ALREADY be True from a
            # leg that ran and failed its own checks, or that carried no energy
            # metrics. A documented stimulus split is not a reason to fail a
            # campaign; it is also not a licence to swallow one that had a real
            # failure in it. `missing` is carried in the record either way, so
            # the report still names such a leg.
            exit_affecting=(exit_affecting
                            or bool(spec.get("stimulus_mismatch_exit_affecting",
                                             True))),
            reason=("the legs of this frontier did NOT run the same stimulus, "
                    "so their hydrogen totals differ by the STIMULUS and not "
                    "only by the policy — no eq-H2 comparison is made. "
                    "Disagreeing key(s): %s"
                    % "; ".join(
                        "%s = %s" % (k, ", ".join(
                            "%s:%s" % (n, ("<%d-point profile>" % len(v))
                                       if isinstance(v, list) else v)
                            for n, v in sorted(vals.items())))
                        for k, vals in stim)))
        return rec
    if missing:
        rec.update(verdict="UNVERIFIED", passed=False,
                   reason="the frontier needs all three legs; "
                          + "; ".join(missing))
        return rec

    ref, cand, bound = legs["reference"], legs["candidate"], legs["bound"]
    dsoc_ref = ref["dsoc"]
    gap = abs(cand["dsoc"] - dsoc_ref)
    gap_bound = abs(bound["dsoc"] - dsoc_ref)
    rec["dsoc_gap"] = gap
    rec["dsoc_gap_bound"] = gap_bound
    # THE IMPLIED LEVER between candidate and bound: d(dSoC)/d(h2) across the two
    # legs, in the same SoC/g units as lambda.  Rendered, not asserted — it is
    # the number that explains a vs-bound ratio rather than a bound on one.  A
    # value equal to lambda means the two legs differ only along the SHARE lever
    # and their eq-H2 totals MUST coincide (see the EMS_FRONTIER_VS_BOUND_MAX
    # banner); a value far from lambda means a second, differently-priced lever
    # is in play, which is what the vs-bound arm exists to catch.  None when the
    # two legs burnt indistinguishable hydrogen (the ratio is then undefined,
    # not infinite).
    _dh2 = cand["h2"] - bound["h2"]
    rec["implied_lever_soc_per_g"] = (
        None if abs(_dh2) < 1e-12 else (cand["dsoc"] - bound["dsoc"]) / _dh2)
    if max(gap, gap_bound) > EMS_FRONTIER_DSOC_MATCH_MAX:
        rec.update(
            verdict="UNVERIFIED", passed=False, exit_affecting=True,
            reason=("the SoC-correction is a LINEAR extrapolation and this "
                    "run's legs are %.5f / %.5f SoC apart from the reference, "
                    "over the %.3f matched-dSoC precondition — the legs are "
                    "not the same experiment, so no eq-H2 comparison is made"
                    % (gap, gap_bound, EMS_FRONTIER_DSOC_MATCH_MAX)))
        return rec

    # L5: a NON-POSITIVE eq-H2 on any leg makes the ratios meaningless (a
    # negative denominator flips the sense of every `<=` below, and a zero one
    # is a ZeroDivisionError dodged into a None that the FAIL branch's "%.4f"
    # then crashes on). It is reachable: the SoC correction is unbounded below,
    # so a leg that ended far enough ABOVE the reference is credited more
    # hydrogen than it burned. Refuse the comparison rather than publish a
    # sign-inverted one.
    lam_lo = min([EMS_EQ_H2_LAMBDA_SOC_PER_G] + list(EMS_EQ_H2_LAMBDA_BAND))
    lam_hi = max([EMS_EQ_H2_LAMBDA_SOC_PER_G] + list(EMS_EQ_H2_LAMBDA_BAND))
    nonpos = []
    for lam in (lam_lo, lam_hi):
        for role, v in legs.items():
            if ems_eq_h2(v["h2"], v["dsoc"], dsoc_ref, lam) <= 0.0:
                nonpos.append("%s (%s) at lambda %.3f" % (v["name"], role, lam))
    if nonpos:
        rec.update(
            verdict="UNVERIFIED", passed=False, exit_affecting=True,
            reason=("the SoC-corrected hydrogen is NOT POSITIVE for %s — the "
                    "correction credited a leg more hydrogen than it burned, "
                    "so the eq-H2 RATIOS carry no meaning and no comparison is "
                    "made. Read the raw h2_cum_g / delta_soc pairs directly."
                    % "; ".join(sorted(set(nonpos)))))
        return rec

    # Evaluate at the nominal lambda AND at both band edges. The nominal is
    # what gets reported; the edges decide whether the verdict is a result.
    lambdas = [EMS_EQ_H2_LAMBDA_SOC_PER_G] + list(EMS_EQ_H2_LAMBDA_BAND)
    per_lambda = []
    for lam in lambdas:
        eq = {role: ems_eq_h2(v["h2"], v["dsoc"], dsoc_ref, lam)
              for role, v in legs.items()}
        ok_ref = eq["candidate"] <= vs_ref_max * eq["reference"]
        ok_bnd = eq["candidate"] <= vs_bnd_max * eq["bound"]
        per_lambda.append({
            "lambda": lam, "eq_h2": eq,
            "vs_reference": (eq["candidate"] / eq["reference"]
                             if eq["reference"] else None),
            "vs_bound": (eq["candidate"] / eq["bound"]
                         if eq["bound"] else None),
            "passed_vs_reference": bool(ok_ref),
            "passed_vs_bound": bool(ok_bnd),
            "passed": bool(ok_ref and ok_bnd)})
    rec["per_lambda"] = per_lambda
    rec["eq_h2"] = per_lambda[0]["eq_h2"]
    rec["vs_reference"] = per_lambda[0]["vs_reference"]
    rec["vs_bound"] = per_lambda[0]["vs_bound"]

    verdicts = {p["passed"] for p in per_lambda}
    if len(verdicts) > 1:
        rec.update(
            verdict="KNIFE-EDGE", passed=False, exit_affecting=True,
            reason=("the verdict FLIPS inside the measured lambda band "
                    "[%.3f, %.3f] SoC/g (%s) — lambda is known to ~1.5 %%, so "
                    "a result that depends on where inside the band it is read "
                    "is not a result. Neither PASS nor FAIL; treat the legs as "
                    "tied and widen the stimulus or the campaign count."
                    % (EMS_EQ_H2_LAMBDA_BAND[0], EMS_EQ_H2_LAMBDA_BAND[1],
                       ", ".join("%.3f:%s" % (p["lambda"],
                                              "pass" if p["passed"] else "fail")
                                 for p in per_lambda))))
        return rec

    nom = per_lambda[0]
    if nom["passed"]:
        rec.update(verdict="PASS", passed=True,
                   reason=("eq-H2 %.7g g vs reference %.7g g (%.4f x, need "
                           "<= %.2f) and vs bound %.7g g (%.4f x, need "
                           "<= %.2f), stable across the lambda band"
                           % (nom["eq_h2"]["candidate"],
                              nom["eq_h2"]["reference"], nom["vs_reference"],
                              vs_ref_max,
                              nom["eq_h2"]["bound"], nom["vs_bound"],
                              vs_bnd_max)))
    else:
        broke = []
        if not nom["passed_vs_reference"]:
            broke.append("vs the `%s` heuristic %.4f x (need <= %.2f)"
                         % (ref["name"], nom["vs_reference"], vs_ref_max))
        if not nom["passed_vs_bound"]:
            broke.append("vs the `%s` bound %.4f x (need <= %.2f)"
                         % (bound["name"], nom["vs_bound"], vs_bnd_max))
        rec.update(verdict="FAIL", passed=False, exit_affecting=True,
                   reason=("the `%s` leg is OFF the frontier at matched "
                           "delta_soc: %s. This is a POLICY finding, not a "
                           "board one — no per-run check can see it."
                           % (cand["name"], "; ".join(broke))))
    return rec


def evaluate_ems_frontiers(results, planned_names=None):
    """Every registered frontier, in EMS_FRONTIERS order.  PURE.

    Returns a list of records; a frontier none of whose legs was planned
    contributes NOTHING (evaluate_ems_frontier returns None for it), for the
    same reason it always did — a scenarios-only or replay-only plan never
    intended the comparison, and an UNVERIFIED record for it is noise.  So a
    campaign without --with-ftp75 gets exactly one record, and one WITH it gets
    two."""
    out = []
    for spec in EMS_FRONTIERS:
        rec = evaluate_ems_frontier(results, planned_names, spec=spec)
        if rec is not None:
            out.append(rec)
    return out


# The two module constants are the CYCLE61 spec's thresholds, kept because the
# ledger, the tests and three campaigns' prose all name them. Pinned equal so
# they cannot drift into a second, disagreeing record of the same numbers.
assert EMS_FRONTIERS[0]["vs_reference_max"] == EMS_FRONTIER_VS_REFERENCE_MAX
assert EMS_FRONTIERS[0]["vs_bound_max"] == EMS_FRONTIER_VS_BOUND_MAX
assert EMS_FRONTIERS[0]["roles"] is EMS_FRONTIER


# The banner a NON-frontier EMS run carries in the report.  One text, so the
# claim cannot drift between the summary and the per-run block.
EMS_DEMONSTRATION_BANNER = (
    "**DYNAMICS DEMONSTRATION — not on the EMS frontier.** This run's strategy "
    "(`%s`) is registered `frontier_eligible: False` in "
    "`hil_plant_sim.EMS_STRATEGY_META`: it is exercised for the MECHANISM it "
    "puts on the wire, not as an energy-management result. Its `h2_cum_g` and "
    "`delta_soc` are measurements of that mechanism and must NOT be ranked "
    "against the frontier legs (`%s`) — the EMS frontier check excludes this "
    "run by construction.")

# L8: a strategy name the run RECORDED but this checkout does not register.
# It is neither eligible nor a registered demonstration, and the demonstration
# banner would assert a `frontier_eligible: False` entry that does not exist —
# so it gets its own honest text instead of being asserted into either camp.
EMS_UNCLASSIFIED_BANNER = (
    "**EMS role: unclassified (`%s` unknown to this checkout).** The run "
    "recorded a strategy name that is not in `hil_plant_sim.EMS_STRATEGY_META` "
    "here, so no role can be read off it. Its `h2_cum_g` / `delta_soc` are "
    "NOT scored on the EMS frontier — an unregistered strategy is one nobody "
    "has placed a role on.")


def ems_demonstration_banner(scenario_name, recorded_strategy=None):
    """The banner text for a scenario driven by a non-frontier EMS strategy, or
    None for a scenario that is not EMS-driven or whose strategy IS eligible.

    L7: `recorded_strategy` — the strategy the CHILD recorded in its meta
    sidecar — WINS over the scenario registry's default. The two disagree
    whenever a run was launched with an explicit `--ems`, and the banner must
    describe the strategy that actually ran, not the one the table defaults to.
    """
    strategy = recorded_strategy or (SCENARIOS.get(scenario_name) or {}).get("ems")
    if not strategy:
        return None
    meta = EMS_STRATEGY_META.get(strategy)
    if meta is None:
        return EMS_UNCLASSIFIED_BANNER % strategy
    if meta.get("frontier_eligible"):
        return None
    text = EMS_DEMONSTRATION_BANNER % (
        strategy, ", ".join("`%s`" % n for n in sorted(EMS_FRONTIER.values())))
    # L9: the per-strategy role note, rendered AFTER the shared banner. The
    # banner says "not on the frontier"; the note says WHICH KIND of
    # off-frontier run this is — a policy demonstration that is deliberately
    # loss-making is a different thing from a stimulus with no objective at all,
    # and a reader who cannot tell them apart mis-reads both.
    note = meta.get("role_note")
    if note:
        text += "\n>\n> %s" % note
    return text


CAMPAIGN_META_NAME = "campaign_meta.json"


def _iso_local(t):
    """A POSIX timestamp as ISO-8601 with a local UTC offset, seconds precision.

    Same convention (and the same truncation to the second) as run_child()'s
    "launched_at" stamp, so a campaign_meta.json time and a per-run time can be
    compared literally without re-parsing either into a different resolution."""
    return (datetime.datetime.fromtimestamp(t)
            .replace(microsecond=0).astimezone().isoformat(timespec="seconds"))


def _fmt_hms(seconds):
    """Seconds as h:mm:ss (hours unpadded). None/negative -> "?"."""
    if seconds is None:
        return "?"
    try:
        s = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "?"
    if s < 0:
        return "?"
    return "%d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60)


def build_campaign_meta(args, argv, plan, results, started_t, finished_t,
                        completed):
    """Campaign-level wall-clock metadata (the payload of campaign_meta.json).

    Pure function: every input is passed in, so a test can pin the arithmetic
    without a clock.  `wall_s_runs_sum` is the sum of the per-run `wall_s`
    values run_child() already records; `wall_s_overhead` is everything the
    campaign spent OUTSIDE a child — the settle pauses, the pre-run tool passes,
    board resets, and the report rendering itself.  A SKIPPED run launches no
    child, so it counts toward `n_runs_planned` but not `n_runs_executed`."""
    runs_sum = 0.0
    executed = 0
    for r in results:
        if r.get("skipped"):
            continue
        executed += 1
        runs_sum += (r.get("child") or {}).get("wall_s") or 0.0
    total = max(0.0, finished_t - started_t)
    return {
        "started_at": _iso_local(started_t),
        "finished_at": _iso_local(finished_t),
        "wall_s_total": total,
        "wall_hms_total": _fmt_hms(total),
        "wall_s_runs_sum": runs_sum,
        "wall_s_overhead": total - runs_sum,
        "n_runs_planned": len(plan),
        "n_runs_executed": executed,
        # False whenever the campaign did not reach the end of its plan (Ctrl-C,
        # an abort, or a short result list): the timestamps below are then the
        # times of the ABORT, not of a completed campaign, and nothing should
        # read them as a runtime figure for the full plan.
        "completed": bool(completed),
        "out": args.out,
        "argv": list(argv),
    }


def write_campaign_meta(out_dir, campaign):
    """Write campaign_meta.json into the report folder. Never raises on a
    rendering problem the campaign itself should survive -- an I/O error here
    must not turn a finished campaign into a crash, so the caller's finally
    path stays intact."""
    path = os.path.join(out_dir, CAMPAIGN_META_NAME)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(campaign, fh, indent=2, default=str)
    except OSError as exc:
        print("[suite] WARNING: could not write %s: %s" % (path, exc),
              file=sys.stderr)
    return path


def render_report(meta, results):
    """Build REPORT.md from the collected result dicts. Pure function."""
    L = []
    A = L.append
    A("# HIL suite report")
    A("")
    A("| | |")
    A("|---|---|")
    A(_row(["Date", meta.get("date", "?")]))
    A(_row(["Board IP:port", "%s:%s" % (meta.get("teensy_ip"), meta.get("port"))]))
    A(_row(["Firmware expectation", "fw v%s, built `-DHIL_SIM=1 -DUSE_ETHERNET=1`"
            % meta.get("target_fw", TARGET_FW_VERSION)]))
    A(_row(["Host", meta.get("host", "?")]))
    A(_row(["Python", meta.get("python", "?")]))
    A(_row(["Command source", {"pi-live": "MODE B — a REAL Pi owned the command link "
                               "(--pi-live); scenarios with their own pi_timeline "
                               "were SKIPPED",
                               "scripted": "scripted (scenario pi_timeline / emulated "
                               "EMS strategy)"}.get(meta.get("mode", "scripted"),
                                                    meta.get("mode"))]))
    A(_row(["Electrical preference", meta.get("electrical_pref", "?")]))
    # WP-E: in the header table, not only in the findings section, because it
    # qualifies every V_bus number in the report.
    A(_row(["Droop realization (scenario half)",
            "%s%s" % (meta.get("droop_mode", "design"),
                      "" if meta.get("droop_mode", "design") == "design"
                      else "  — ⚠️ sags NOT comparable with other campaigns")]))
    # PART A (C1): in the header table, because it qualifies every SHARE and
    # per-channel current figure in the report the way droop_mode qualifies
    # every V_bus figure.
    _asym = meta.get("asymmetry")
    A(_row(["Converter asymmetry (scenario half)",
            "not recorded (campaign predates the C1 round)" if _asym is None
            else "%s%s" % (_asym,
                           "  — FC/BT mismatch injected; shares NOT comparable "
                           "with a pre-2026-09-01 campaign"
                           if _asym == "measured" else
                           "  — symmetric plant (the pre-C1 baseline)")]))
    # WP-1C: the CHARGER ERA, beside the electrical mode and for the same
    # reason — it qualifies every hydrogen and charge-window number in the
    # report. Read from the FIRST scenario run that recorded one, because it is
    # a property of the plant the child ran, not of this checkout. `None` is
    # the 1:1 current-transfer sentinel, not "unknown": no efficiency value
    # reproduces that era, because it billed the charger at the BUS voltage
    # where the model bills it at the PACK voltage (docs/HIL_PLANT.md §4.6.1).
    _eta = None
    _eta_seen = False
    for _r in results or ():
        if _r.get("kind") == "scenario" and "eta_chg" in _r:
            _eta, _eta_seen = _r.get("eta_chg"), True
            break
    A(_row(["Charger era",
            "not recorded (no scenario run reported one)" if not _eta_seen
            else ("**1:1 current transfer** — the pre-2026-09-01 plant; "
                  "charging legs comparable with campaigns <= 20260901_151156"
                  if _eta is None else
                  "**energy-conserving, eta_chg = %g** — charging legs are NOT "
                  "comparable with campaigns <= 20260901_151156" % _eta)]))
    A(_row(["Settle pause between runs", "%s s" % meta.get("settle_s")]))
    # Campaign wall-clock. Present only on the FINAL rewrite (the intermediate
    # per-run rewrites have no finish time yet), so a partial REPORT.md simply
    # omits the row rather than carrying a runtime that is not one.
    _camp = meta.get("campaign_timing") or {}
    if _camp:
        A(_row(["Campaign runtime",
                "%s (%.0f s total; %.0f s in runs, %.0f s overhead — settle "
                "pauses, tool passes, board resets)%s"
                % (_fmt_hms(_camp.get("wall_s_total")),
                   _camp.get("wall_s_total") or 0.0,
                   _camp.get("wall_s_runs_sum") or 0.0,
                   _camp.get("wall_s_overhead") or 0.0,
                   "" if _camp.get("completed")
                   # Deliberately no emoji here: this row renders on the
                   # PARTIAL report, which the M4 regression test reads back
                   # with the platform default encoding (cp1252 on the bench
                   # PC) — a non-cp1252 glyph on an aborted report is an
                   # unreadable file on exactly the machine that aborts.
                   else "  — ABORTED campaign: this is the time to the abort, "
                        "not a full-plan runtime")]))
        A(_row(["Campaign window",
                "%s → %s (%d of %d planned run(s) executed)"
                % (_camp.get("started_at", "?"), _camp.get("finished_at", "?"),
                   _camp.get("n_runs_executed", 0),
                   _camp.get("n_runs_planned", 0))]))
    if meta.get("dashboard"):
        # F3: --dashboard hands children the real terminal for stdout, so the
        # per-run summary columns below (and the achieved-rate check) cannot
        # be parsed from a capture -- flag it here, once, instead of leaving
        # the reader to infer it from a wall of "?" cells.
        A(_row(["Dashboard mode", "ON — children ran with --dash; stdout summary "
                                  "columns below are unavailable (see the "
                                  "achieved_rate note on each scenario)"]))
    A(_row(["Runs", "%d (%d scenario, %d replay)"
            % (len(results),
               sum(1 for r in results if r["kind"] == "scenario"),
               sum(1 for r in results if r["kind"] == "replay"))]))
    rates = [r["child"]["summary"].get("achieved_hz") for r in results
             if r.get("child", {}).get("summary", {}).get("achieved_hz") is not None]
    if rates:
        A(_row(["Achieved tick rate", "min %.1f / mean %.1f / max %.1f Hz"
                % (min(rates), sum(rates) / len(rates), max(rates))]))
    npass = sum(1 for r in results if r["passed"])
    nskip = sum(1 for r in results if r.get("skipped"))
    # D3: an inconclusive run whose OTHER checks also failed is BOTH — it is not
    # eligible for the "these are not failures; re-run them" sentence, because
    # something did fail on the record before the evidence was destroyed.
    inc = [r for r in results if r.get("inconclusive")]
    ninc_clean = sum(1 for r in inc if not (r.get("also_failed") or 0))
    ninc_failed = len(inc) - ninc_clean
    A(_row(["Result", "%d/%d passed%s"
            % (npass, len(results),
               # Skipped runs count as passing (they are not board failures), but
               # saying so here stops "13/13 passed" reading as 13 runs executed.
               "  (%d of them SKIPPED, not executed)" % nskip if nskip else "")]))
    if inc:
        parts = []
        if ninc_clean:
            parts.append("%d run(s) saw a MID-RUN HIL warm reset: the board "
                         "restarted underneath the stimulus, so the rest of "
                         "each run was not the scenario its checks assume and "
                         "the verdict proves nothing either way. These are NOT "
                         "failures; re-run them on an unloaded host." % ninc_clean)
        if ninc_failed:
            parts.append("%d further run(s) saw a mid-run warm reset AND had "
                         "check failures of their own — those failures are real "
                         "and are listed per run; re-running clears only the "
                         "inconclusive part." % ninc_failed)
        A(_row(["INCONCLUSIVE", " ".join(parts)]))
    frontiers = evaluate_ems_frontiers(results)
    for _f in frontiers:
        A(_row(["EMS frontier (%s)" % _f["label"], "**%s** — %s"
                % (_f["verdict"], _f["reason"])]))
    if meta.get("aborted"):
        A(_row(["ABORTED", meta["aborted"]]))
    if meta.get("partial"):
        # M4: this report was written mid-run (or the run was interrupted before
        # the plan finished) -- results.json/REPORT.md are rewritten after every
        # run, so this file is never stale, but it may legitimately be incomplete.
        A(_row(["PARTIAL", "the plan did not run to completion -- this report "
                           "covers only the runs completed so far"]))
    A("")

    # ── Summary table ────────────────────────────────────────────────────────
    A("## Summary")
    A("")
    A(_row(["run", "kind", "mode", "duration", "result", "key metrics"]))
    A(_row(["---"] * 6))
    for r in results:
        dur = r.get("duration_s")
        # F6: a skipped run rendered as "PASS" here, indistinguishable from an
        # executed clean run, and paired with the fabricated-clean detail lines
        # below it looked like a run that had actually happened.
        result_cell = result_label(r, bold_fail=True)
        A(_row([r["name"], r["kind"], r.get("mode", ""),
                ("%.1f s" % dur) if dur else "—",
                result_cell,
                r.get("key_metrics", "")]))
    A("")

    # ── EMS frontier (cross-run) ─────────────────────────────────────────────
    for frontier in frontiers:
        # Verdict FIRST, stimulus label in parentheses: the heading was
        # "## EMS frontier — <verdict>" before the second tuple existed, and
        # keeping the verdict in that position keeps every reader (and every
        # grep) that learned the old shape working.
        A("## EMS frontier — %s  (%s)"
          % (frontier["verdict"], frontier["label"]))
        A("")
        if frontier.get("provisional_note"):
            A("> **[%s]**" % frontier["provisional_note"])
        if frontier.get("stimulus_mismatch"):
            A("> ⚠️ **STIMULUS SPLIT — the legs are not one experiment.** "
              "eq-H2 corrects for SoC, not for demand, so no comparison is "
              "made. Disagreeing scenario key(s):")
            for _m in frontier["stimulus_mismatch"]:
                A(">   - `%s`: %s" % (_m["key"], ", ".join(
                    "`%s` = %s" % (n, ("<%d-point profile>" % len(v))
                                   if isinstance(v, list) else v)
                    for n, v in sorted(_m["values"].items()))))
        A("")
        A("A CROSS-RUN check: an energy-management result is a COMPARISON, so no")
        A("per-run threshold can express it. Legs are compared on **SoC-corrected**")
        A("hydrogen, `eq_H2 = h2 - (dSoC - dSoC(reference)) / lambda`, with")
        A("`%s` as the reference." % frontier["roles"]["reference"])
        A("")
        A("> %s" % frontier["reason"])
        A("")
        if frontier.get("legs"):
            A(_row(["leg", "role", "h2_cum_g [g]", "delta_soc",
                    "eq-H2 [g]", "vs bound", "vs reference"]))
            A(_row(["---"] * 7))
            eq = frontier.get("eq_h2") or {}
            for role in ("reference", "candidate", "bound"):
                leg = frontier["legs"].get(role)
                if leg is None:
                    continue
                e = eq.get(role)
                eb = eq.get("bound")
                er = eq.get("reference")
                A(_row([
                    "`%s`" % leg["name"], role,
                    "%.7g" % leg["h2"], "%+.6f" % leg["dsoc"],
                    ("%.7g" % e) if e is not None else "—",
                    ("%.4f x" % (e / eb)) if (e is not None and eb) else "—",
                    ("%.4f x" % (e / er)) if (e is not None and er) else "—"]))
            A("")
        for miss in frontier.get("missing") or []:
            A("- UNVERIFIED leg: %s" % miss)
        if frontier.get("missing"):
            A("")
        if frontier.get("per_lambda"):
            A("Lambda sensitivity (the verdict must be stable across the "
              "measured band):")
            A("")
            A(_row(["lambda [SoC/g]", "eq-H2 candidate [g]", "vs reference",
                    "vs bound", "verdict"]))
            A(_row(["---"] * 5))
            for p in frontier["per_lambda"]:
                A(_row(["%.3f" % p["lambda"],
                        "%.7g" % p["eq_h2"]["candidate"],
                        ("%.4f x" % p["vs_reference"])
                        if p["vs_reference"] is not None else "—",
                        ("%.4f x" % p["vs_bound"])
                        if p["vs_bound"] is not None else "—",
                        "pass" if p["passed"] else "fail"]))
            A("")
        # The implied lever — rendered whenever both legs are present, because
        # it is what makes a vs-bound ratio READABLE (see the
        # EMS_FRONTIER_VS_BOUND_MAX banner).
        if frontier.get("implied_lever_soc_per_g") is not None:
            _il = frontier["implied_lever_soc_per_g"]
            A("**implied lever, candidate vs bound: %.5f SoC/g** "
              "(lambda = %.3f). This is d(delta_soc)/d(h2_cum_g) between the "
              "two legs. When it agrees with lambda, the two legs differ only "
              "along the SHARE lever and their SoC-corrected totals MUST "
              "coincide — a **vs bound** ratio near 1.00 is then STRUCTURAL, "
              "not a proximity-to-optimal result, and the discriminating arm "
              "is **vs reference**. The vs-bound arm detects a candidate that "
              "reached its result through a lever priced differently from "
              "lambda (e.g. the Ag105 charge lever at ~0.24 SoC/g), which is "
              "the regression it was built for."
              % (_il, EMS_EQ_H2_LAMBDA_SOC_PER_G))
            A("")
        A("**lambda provenance.** %.3f SoC/g is the MEASURED share lever: "
          "campaign 20260831_191509 priced share-shifting at 0.409-0.415 SoC/g "
          "on two independent stimuli (the 61 s cycle and the 340 s FTP-75, "
          "2.3 %% apart; the offline DP solve says 0.405). The band "
          "[%.3f, %.3f] is that measurement, and a verdict that flips inside it "
          "renders KNIFE-EDGE — neither PASS nor FAIL — rather than being read "
          "off the centre. Thresholds: candidate <= %.2f x reference and "
          "<= %.2f x bound; the second is a LEVER-CLASS detector rather than "
          "an optimality gate, and it is NOT to be tightened on a campaign "
          "whose candidate never opened the charger — on such a reading its "
          "ratio is structurally ~1.00, because both legs then move along the "
          "share lever alone and lambda is that lever's own rate."
          % (EMS_EQ_H2_LAMBDA_SOC_PER_G, EMS_EQ_H2_LAMBDA_BAND[0],
             EMS_EQ_H2_LAMBDA_BAND[1], frontier["vs_reference_max"],
             frontier["vs_bound_max"]))
        A("")
        A("⚠️ `h2_cum_g` is the Gfc **model's estimate** of hydrogen mass. The "
          "map is scale-portable, but the coefficients are **not identified "
          "against this rig's stack** (`TODO(calibrate)` — the H2Consumption "
          "banner in `hil_plant_sim.py`). Every number above is therefore a "
          "RANKING on one rig, which is robust, and not an absolute mass.")
        A("")
        A("Runs whose EMS strategy is `frontier_eligible: False` are excluded "
          "from this comparison by construction and carry a demonstration "
          "banner in their own block below.")
        A("")

    # ── Scenarios ────────────────────────────────────────────────────────────
    scen = [r for r in results if r["kind"] == "scenario"]
    if scen:
        A("## Scenario runs")
        A("")
        A("Scenario entries carry no declarative checks (unlike the replay suite), so")
        A("the checks below are this runner's health criteria: an observation frame must")
        A("have arrived, the fault outcome must match the expectation table, and the")
        A("host must have held the tick rate.")
        A("")
        for r in scen:
            A("### `%s` — %s" % (r["name"], result_label(r)))
            A("")
            if r.get("description"):
                A("*%s*" % r["description"])
                A("")
            # A run driven by a NON-frontier EMS strategy says so here, before
            # any of its numbers are read: its h2/delta_soc pair is a
            # measurement of a mechanism, not a competitive score.
            _demo = ems_demonstration_banner(r["name"], r.get("ems_strategy"))
            if _demo:
                A("> %s" % _demo)
                A("")
            if r.get("inconclusive_reason"):
                A("> **INCONCLUSIVE.** %s" % r["inconclusive_reason"])
                A("")
            if r.get("skipped"):
                # F6: no child was ever launched for a skipped run — there is no
                # CSV, no frames, no fault_flags to report. The old code fell
                # through to the metric/frame/fault lines below with empty
                # metrics/events dicts, which rendered as e.g. "final fault_flags
                # 0x0000 (none)" -- a FABRICATED clean result for a run that never
                # happened. Short-circuit entirely instead.
                A("- child: **not run** — %s" % r.get("skip_reason", "skipped"))
                A("")
                for c in r["checks"]:
                    A("  - [%s] **%s** — %s" % ("x" if c["passed"] else " ", c["name"], c["detail"]))
                A("")
                continue
            if r.get("child", {}).get("stdout_passthrough"):
                # F3: explain the '?' frame/rate cells below before the reader
                # hits them, not just in the summary-table header row.
                A("*(ran with `--dashboard`: stdout was passed through to the "
                  "terminal, so the frame/rate summary below is unavailable — "
                  "see the `achieved_rate` check.)*")
                A("")
            m = r.get("metrics", {})
            A("- electrical: **%s** (scenario requires `%s`)"
              % (r.get("mode"), r.get("electrical_required")))
            A("- CSV: `%s` — %d rows, %d with an observation frame"
              % (os.path.basename(m.get("csv", "")), m.get("rows", 0), m.get("n_obs", 0)))
            s = r["child"].get("summary", {})
            A("- frames: tx %s / rx %s (%s malformed); achieved %s Hz, max overrun %s ms"
              % (s.get("tx_frames", "?"), s.get("rx_frames", "?"), s.get("rx_bad", "?"),
                 ("%.1f" % s["achieved_hz"]) if "achieved_hz" in s else "?",
                 ("%.2f" % s["max_overrun_ms"]) if "max_overrun_ms" in s else "?"))
            # Both unions, always, with the carried-in bits named separately: the
            # whole-run union is what was OBSERVED, the post-grace union is what
            # this run PRODUCED, and every check above judges the latter.
            seen_b = m.get("fault_bits_seen") or 0
            post_b = m.get("fault_bits_post_grace") or 0
            carried_b = seen_b & ~post_b
            A("- final `fault_flags`: `0x%04X` (%s); union over the run: %s; "
              "POST-GRACE union (t >= %.1fs, what the checks judge): %s; "
              "final state: %s"
              % (m.get("final_fault_flags") or 0,
                 fault_names(m.get("final_fault_flags") or 0),
                 fault_names(seen_b), m.get("grace_s", WARM_RESET_GRACE_S),
                 fault_names(post_b), m.get("final_state")))
            if carried_b:
                # Wording matches judge_scenario()'s `carried_note` — see the
                # correction recorded there. These bits are observed pre-grace
                # and gone after it; the dominant contributor is each child's
                # own fresh link-handshake blip, NOT an inherited latch, and
                # the CSV cannot tell the two apart.
                A("  - pre-grace reconnect transient (seen only before "
                  "t=%.1fs and gone after it; a fresh link-handshake blip "
                  "and/or a predecessor latch cleared by the fw v23 warm "
                  "reset — not distinguishable here): %s"
                  % (m.get("grace_s", WARM_RESET_GRACE_S), fault_names(carried_b)))
            if m.get("substep_hz_mean") is not None:
                A("- hi-fi substep rate: mean %.0f Hz, min %.0f Hz"
                  % (m["substep_hz_mean"], m["substep_hz_min"]))
            # EMS comparison surface. Rendered for any run whose CSV carried the
            # columns, so `ems-soc-band` (causal) and `ems-dp-replay` (the
            # NON-CAUSAL DP benchmark) line up directly.
            if m.get("final_h2_cum_g") is not None or m.get("delta_soc") is not None:
                A("- EMS energy: h2_cum_g %s, delta_soc %s (SoC %s -> %s)"
                  % (("%.6g" % m["final_h2_cum_g"])
                     if m.get("final_h2_cum_g") is not None else "—",
                     ("%+.6f" % m["delta_soc"])
                     if m.get("delta_soc") is not None else "—",
                     ("%.6f" % m["soc_first"])
                     if m.get("soc_first") is not None else "—",
                     ("%.6f" % m["soc_last"])
                     if m.get("soc_last") is not None else "—"))
                if m.get("final_h2_sdp_cum_g") is not None:
                    A("  - student's static-proxy axis: h2_sdp_cum_g %.6g "
                      "(`P_fc/(0.5*120000)`, SDP_EnergyManagement2.m) — a "
                      "SECOND MODEL of the same quantity on the SAME `P_fc` "
                      "input, **not** a cross-check of h2_cum_g: the proxy "
                      "under-reads Gfc by ~5.5 %% at steady state by "
                      "construction. Rank runs on ONE axis; the gap between "
                      "the two columns is arithmetic."
                      % m["final_h2_sdp_cum_g"])
                A("  - ⚠️ h2_cum_g is the Gfc **model's estimate** of hydrogen "
                  "mass. The map is scale-portable (operator ruling "
                  "2026-08-31: `P_fc` in W and the g/s output both ride the "
                  "system's energy scaling factor), but the coefficients are "
                  "**not identified against this rig's stack** "
                  "(`TODO(calibrate)`) — see the H2Consumption banner in "
                  "`hil_plant_sim.py`. Quote an absolute figure with that "
                  "caveat; a ranking of two runs on this rig is robust "
                  "regardless. Read it WITH delta_soc either way: any strategy "
                  "burns less hydrogen by discharging the pack harder, so a "
                  "hydrogen ranking is only valid at matched delta_soc.")
            ev = r.get("events", {})
            if ev.get("read_error"):
                # L9(b): a sidecar that failed to READ must not render as a silent
                # "0 events, clean" — it means events on disk were never inspected.
                A("- electrical events: **could not read sidecar** (%s)" % ev["read_error"])
            elif ev.get("total"):
                kinds = ", ".join("%s=%d" % kv for kv in sorted(ev["kinds"].items()))
                A("- electrical events: %d (%s)%s"
                  % (ev["total"], kinds,
                     "; **%d over abs-max**" % ev["over_absmax"] if ev["over_absmax"] else ""))
                # ITEM 9: the worst ring, whether or not it crossed the abs-max. A
                # ring below 20 V but above LIMIT_V_BUS_MAX used to appear nowhere
                # in this report at all (campaign 20260830_203006's 17.578 V
                # FC-open ring, 0.078 V over the bus limit).
                if ev.get("worst_ring_v") is not None:
                    A("- worst estimated switching-ring peak: **%.3f V** (abs-max "
                      "%.0f V; `LIMIT_V_BUS_MAX` %.1f V). Analytic estimate only — "
                      "the nH-uF loop is not integrated (see `hil_electrical.py`'s "
                      "module docstring)."
                      % (ev["worst_ring_v"], V_ABSMAX_V, LIMIT_V_BUS_MAX_V))
            log_note = (" **(log write failed: %s)**" % r["child"]["log_write_error"]
                        if r["child"].get("log_write_error") else "")
            A("- child: %s (rc %s, %.1f s wall) — log `%s`%s"
              % (r["child"]["status"], r["child"]["returncode"],
                 r["child"]["wall_s"] or 0.0,
                 os.path.basename(r["child"]["log"]), log_note))
            A("")
            for c in r["checks"]:
                A("  - [%s] **%s** — %s" % ("x" if c["passed"] else " ", c["name"], c["detail"]))
            A("")
            # D4: non-failing observations (currently the grace-window
            # warm-reset note). The scenario half had no notes renderer at all
            # before, so these would have been written to results.json and shown
            # nowhere a human reads.
            for n in r.get("notes", []):
                A("  > NOTE: %s" % n)
            if r.get("notes"):
                A("")

    # ── Replays ──────────────────────────────────────────────────────────────
    rep = [r for r in results if r["kind"] == "replay"]
    if rep:
        A("## Replay suite")
        A("")
        A("Recorded bench logs replayed as OPEN-LOOP stimulus (the firmware's commands")
        A("cannot influence the replayed trajectory). Checks are the declarative ones in")
        A("`tools/hil_replay_suite.py`; the notes carry each entry's fw-delta caveat.")
        A("")
        # M1: the half is TWO CLASSES from 2026-08-30, and a blanket "no commander
        # exists" preamble would now be false for the entries that opt into command
        # replay — the ones whose current-shape checks actually carry evidence.
        # Counted from the records, not assumed, so this sentence cannot drift out
        # of step with the suite table.
        n_cmd = sum(1 for r in rep if r.get("replay_commands"))
        A("**What this half is:** a BRING-UP + FAULT-DECISION regression harness,")
        A("and — for the entries that opt in — a CONTROLLER-REACTION harness too.")
        if n_cmd:
            A("**%d of %d** replay entries set `replay_commands`: the log's own recorded"
              % (n_cmd, len(rep)))
            A("`v_sp`/`share_sp` are replayed as 22-byte Pi command packets at 50 Hz, so")
            A("the board DOES reach State 2 and both control loops step against the")
            A("recorded stimulus. Their current-shape checks judge the live controller's")
            A("reaction, and a `drive_loop_stepped` check asserts the loop actually moved.")
            A("")
            A("The remaining **%d** construct no commander at all: the board brings up,"
              % (len(rep) - n_cmd))
            A("sits in Idle, and the commanded current is 0 A throughout. Their")
            A("current-shape checks assert only that the firmware does not drive on an")
            A("uncommanded stimulus, and are tagged **NOT EXERCISED** below.")
        else:
            A("No entry in this run set `replay_commands`, so no commander was")
            A("constructed: no run reached State 2, the commanded current is 0 A")
            A("throughout, and every current-shape check asserts only that the firmware")
            A("does not drive on an uncommanded stimulus (tagged **NOT EXERCISED**).")
        A("")
        A("⚠️ Command replay does NOT close the loop — the injected `v_actual` still does")
        A("not respond to what the firmware commands, so even an opt-in entry is a")
        A("REACTION test, never a tracking test.")
        A("")
        A("Each run is preceded by a %.1f s synthetic bring-up preamble of healthy" % REPLAY_PREAMBLE_S)
        A("nominal rails, so times below are SIM-relative and log time = sim time − %.1f s."
          % REPLAY_PREAMBLE_S)
        A("")
        for group, title in (("conformance", "### Conformance"),
                             ("deviation", "### Deviation")):
            g = [r for r in rep if r.get("mode") == group]
            if not g:
                continue
            A(title)
            A("")
            for r in g:
                A("#### `%s` — %s" % (r["name"], result_label(r)))
                A("")
                if r.get("description"):
                    A("*%s*" % r["description"])
                    A("")
                if r.get("inconclusive_reason"):
                    A("> **INCONCLUSIVE.** %s" % r["inconclusive_reason"])
                    A("")
                if r.get("skipped"):
                    # F5/F6: --pi-live skips the whole replay half — no child, no
                    # CSV, nothing to report but why.
                    A("- child: **not run** — %s" % r.get("skip_reason", "skipped"))
                    A("")
                    for c in r["checks"]:
                        A("  - [%s] **%s** — %s" % ("x" if c["passed"] else " ", c["name"], c["detail"]))
                    A("")
                    continue
                log_note = (" **(log write failed: %s)**" % r["child"]["log_write_error"]
                            if r["child"].get("log_write_error") else "")
                A("- child: %s (rc %s, %.1f s wall) — log `%s`%s, CSV `%s`"
                  % (r["child"]["status"], r["child"]["returncode"],
                     r["child"]["wall_s"] or 0.0,
                     os.path.basename(r["child"]["log"]), log_note,
                     os.path.basename(r.get("csv", ""))))
                # M2: replay metrics have been in results.json since the A5 fix but
                # were never RENDERED, so REPORT.md — the artifact a reader actually
                # opens — still showed nothing about a replay's latched end state.
                # Same three facts the scenario section prints, and for the same
                # reason: the whole-run union is what was OBSERVED, the post-grace
                # union is what this run PRODUCED, and the final flags are what
                # carries into the NEXT run. Guarded on a populated metrics dict so
                # a load-failure record (which carries only csv/error) stays short.
                rm = r.get("metrics") or {}
                if rm.get("rows"):
                    seen_b = rm.get("fault_bits_seen") or 0
                    post_b = rm.get("fault_bits_post_grace") or 0
                    A("- CSV: %d rows, %d with an observation frame; final "
                      "`fault_flags` `0x%04X` (%s); union over the run: %s; "
                      "POST-GRACE union (t >= %.1fs, what the checks judge): %s; "
                      "final state: %s"
                      % (rm.get("rows", 0), rm.get("n_obs", 0),
                         rm.get("final_fault_flags") or 0,
                         fault_names(rm.get("final_fault_flags") or 0),
                         fault_names(seen_b),
                         rm.get("grace_s", WARM_RESET_GRACE_S),
                         fault_names(post_b), rm.get("final_state")))
                    carried_b = seen_b & ~post_b
                    if carried_b:
                        A("  - pre-grace reconnect transient (seen only "
                          "before t=%.1fs and gone after it; a fresh "
                          "link-handshake blip and/or a predecessor latch "
                          "cleared by the fw v23 warm reset — not "
                          "distinguishable here): %s"
                          % (rm.get("grace_s", WARM_RESET_GRACE_S),
                             fault_names(carried_b)))
                elif rm.get("error"):
                    A("- CSV: **could not be read** (%s)" % rm["error"])
                for c in r["checks"]:
                    A("  - [%s] **%s** — %s" % ("x" if c["passed"] else " ", c["name"], c["detail"]))
                for n in r.get("notes", []):
                    A("  - _note_: %s" % n)
                A("")

    # ── Known open findings ──────────────────────────────────────────────────
    A("## Known open findings")
    A("")
    A("1. **K_DROOP_BUS design-vs-measured x4 discrepancy.** %s"
      % K_DROOP_FINDING.split(": ", 1)[1])
    A("")
    A("   %s" % K_DROOP_MODE_NOTE.get(
        meta.get("droop_mode", "design"),
        "This campaign recorded droop mode %r, which this checkout does not "
        "know — the sag figures below cannot be placed on either side of the "
        "finding above." % meta.get("droop_mode")))
    over = [r for r in results if r.get("events", {}).get("over_absmax")]
    if over:
        A("")
        A("2. **`sw_ring` events above the 20 V abs-max observed in this run** — the")
        A("   boost-death signature (hil_plant_sim.py's exit banner):")
        for r in over:
            ev = r["events"]
            A("   - `%s`: %d event(s), worst estimated ring peak %s V"
              % (r["name"], ev["over_absmax"],
                 ("%.2f" % ev["worst_ring_v"]) if ev["worst_ring_v"] is not None else "?"))
    else:
        A("")
        A("2. No `sw_ring` event above the %.0f V abs-max was observed in this run."
          % V_ABSMAX_V)
        worst = [(r["name"], r["events"]["worst_ring_v"]) for r in results
                 if (r.get("events") or {}).get("worst_ring_v") is not None]
        over_bus = [(n, v) for n, v in worst if v > LIMIT_V_BUS_MAX_V]
        if over_bus:
            A("   Sub-abs-max rings above `LIMIT_V_BUS_MAX` (%.1f V) WERE observed, "
              "and are reported here because nothing else in this file would show "
              "them:" % LIMIT_V_BUS_MAX_V)
            for n, v in sorted(over_bus, key=lambda kv: -kv[1]):
                A("   - `%s`: worst estimated ring peak %.3f V" % (n, v))
    for extra in meta.get("extra_findings", []):
        A("")
        A("- %s" % extra)
    A("")

    # ── Appendix ─────────────────────────────────────────────────────────────
    A("## Appendix — artifacts")
    A("")
    A(_row(["file", "run", "kind"]))
    A(_row(["---"] * 3))
    for r in results:
        for key, label in (("csv", "CSV"), ("events_path", "electrical events"),
                           ("log_path", "child stdout/stderr")):
            p = r.get(key)
            if p:
                A(_row(["`%s`" % os.path.basename(p), r["name"], label]))
    A(_row(["`REPORT.md`", "—", "this report"]))
    A(_row(["`results.json`", "—", "machine-readable results"]))
    A(_row(["`plan.json`", "—", "the run plan (also written by --dry-run)"]))
    A(_row(["`%s`" % CAMPAIGN_META_NAME, "—",
            "campaign wall-clock metadata (start/finish, run vs overhead time)"]))
    A("")
    return "\n".join(L) + "\n"


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def warn_short_settle(args):
    """Warn when --settle-s is too short for the fw v23+ run-boundary rule.

    Deliberately a WARNING and not a floor: `--settle-s 0` plus a power-cycle
    between runs is a documented workflow (module docstring), and on pre-v23
    firmware a short settle is merely a shorter latch window.  What it must not
    be is silent — on fw v23+ every run after the first would start from a board
    that never recovered, and every failure after run 1 would be an artifact."""
    if args.settle_s >= SETTLE_MIN_RECOVER_S:
        return
    print("=" * 78)
    print("[suite] WARNING: --settle-s %.2f s may not reliably cross the fw v23+ "
          "RUN BOUNDARY" % args.settle_s)
    print("        (>= 1 s of continuously DEAD injection link) that gates the HIL "
          "warm recovery")
    print("        from State 99 -> State 0. 'May not' is exact: the boundary is "
          "anchored at the")
    print("        board's LAST ACCEPTED FRAME, so the previous child's teardown and "
          "the next")
    print("        child's startup also count toward the dead window — the true gap "
          "is this")
    print("        pause PLUS an unmeasured margin, and whether it clears 1 s is not "
          "decidable")
    print("        from here. When it does not, the board stays latched and every "
          "run after the")
    print("        first starts from a dead board and its result is an artifact.")
    print("        Use --settle-s >= %.1f for margin, or keep this value and "
          "POWER-CYCLE between runs." % SETTLE_MIN_RECOVER_S)
    print("=" * 78)


def print_plan(plan, args):
    print("HIL suite run plan — %d run(s)" % len(plan))
    print("%-14s %-9s %-12s %-9s %s" % ("run", "kind", "mode", "duration", "detail"))
    total = 0.0
    for p in plan:
        d = p.get("duration_s")
        # F14(a): a skipped run launches no child and gets no settle pause either
        # -- it was contributing a phantom settle_s to the wall-time estimate.
        if not p.get("skip_reason"):
            total += (d or 0.0) + args.settle_s
        print("%-14s %-9s %-12s %-9s %s"
              % (p["name"], p["kind"], p.get("mode", ""),
                 ("%.0f s" % d) if d else ("SKIP" if p.get("skip_reason") else "?"),
                 ("SKIPPED — " + p["skip_reason"]) if p.get("skip_reason")
                 else (p.get("description") or "")[:70]))
    print("\nestimated wall time incl. %.0f s settle pauses: %.0f s (%.1f min)"
          % (args.settle_s, total, total / 60.0))
    # The COST OF EACH OPT-IN SET, printed whether or not it was asked for, so
    # an operator sizing a campaign does not have to add the durations by hand
    # or discover the cost only after passing the flag.  `ftp75c` carries the
    # extra line because its cost is not only wall time: it is the only set
    # that changes the PLANT.
    for _flag, _set, _extra in (
            ("--with-ftp75", FTP75_SCENARIOS, ""),
            ("--with-ftp75c", FTP75C_SCENARIOS,
             "  (also selects `--drag scaled-air`, a HIL-ONLY "
             "road-load-compensated plant)"),
            ("--with-alpha", ALPHA_SCENARIOS, "")):
        _n = [n for n in _set if n in SCENARIOS]
        _d = sum(float(SCENARIOS[n].get("duration_s", 0.0)) for n in _n)
        _on = any(p["name"] in _set and not p.get("skip_reason") for p in plan)
        print("  %-14s %d leg(s), %.0f s + %.0f s settle = %.1f min  [%s]%s"
              % (_flag, len(_n), _d, args.settle_s * len(_n),
                 (_d + args.settle_s * len(_n)) / 60.0,
                 "IN THIS PLAN" if _on else "not requested", _extra))


def main(argv=None):
    # L6 (review 2026-08-31): PERMANENT cp1252 fix. This module's report text,
    # scenario labels and imported replay-entry descriptions carry non-ASCII
    # characters (the ⚠ marker, en/em dashes, ×, °). On a Windows console whose
    # code page is cp1252 — the default on the bench PC — printing any of them
    # raises UnicodeEncodeError and kills the campaign mid-plan, which is how
    # three separate agents have lost a run. Reconfigure both streams to UTF-8
    # with `errors="replace"` so an unencodable character degrades to a
    # replacement glyph instead of an exception. `hasattr` guards the call
    # because reconfigure() exists only on TextIOWrapper (Python 3.7+), and a
    # redirected/wrapped stream may be something else entirely.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                # Already-detached or non-reconfigurable stream: not worth
                # failing a campaign over. The belt-and-braces half of this fix
                # is that hil_replay_suite.py's descriptions are plain ASCII.
                pass
    ap = argparse.ArgumentParser(
        description="Run every HIL scenario + the replay suite and package a report.")
    ap.add_argument("--teensy-ip", default="192.168.1.50", help="board IP (default 192.168.1.50)")
    ap.add_argument("--port", type=int, default=TEENSY_PORT_DEFAULT,
                    help="board UDP port (default %d, the .ino local_port)" % TEENSY_PORT_DEFAULT)
    ap.add_argument("--out", default=None,
                    help="report directory (default "
                         "'<repo>/HIL Results/hil_report_<YYYYmmdd_HHMMSS>'). An "
                         "explicit relative path is taken relative to the CWD.")
    ap.add_argument("--only", action="append", default=[], metavar="PATTERN",
                    help="glob on the run name; repeatable")
    ap.add_argument("--skip", action="append", default=[], metavar="PATTERN",
                    help="glob on the run name; repeatable")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--replay-only", action="store_true", help="skip the scenario half")
    g.add_argument("--scenarios-only", action="store_true", help="skip the replay half")
    ap.add_argument("--electrical-pref", default="hifi", choices=["hifi", "simple"],
                    help="engine for scenarios whose requirement is 'any' (default hifi)")
    ap.add_argument("--asymmetry", default=ASYMMETRY_MODE_DEFAULT,
                    choices=list(ASYMMETRY_MODES),
                    help="converter asymmetry for the SCENARIO half: 'measured' "
                         "(default, from the C1 round 2026-09-01) injects the "
                         "fitted FC/BT mismatch; 'off' restores the symmetric "
                         "plant every campaign before this flag ran. The replay "
                         "half realizes no asymmetry in either mode.")
    ap.add_argument("--droop", default=DROOP_MODE_DEFAULT, choices=list(DROOP_MODES),
                    help="hi-fi droop realization for the SCENARIO half "
                         "(default 'design' — the chain as designed, and what "
                         "every campaign on record ran). 'measured' rescales it "
                         "to the bench fit (0.074/0.16 V/A). ⚠️ sag-depth "
                         "figures are NOT comparable across modes, the replay "
                         "half is never passed this flag (its bands are "
                         "design-calibrated), and the mode does NOT explain the "
                         "~4x design-vs-bench gap")
    ap.add_argument("--settle-s", type=float, default=DEFAULT_SETTLE_S,
                    help="pause between runs so the board unbinds the host (default %.0f s)"
                         % DEFAULT_SETTLE_S)
    ap.add_argument("--keep-going", action="store_true",
                    help="do not abort when the first run sees no observation frames")
    ap.add_argument("--dashboard", action="store_true",
                    help="run every child with the live dashboard (--dash). OFF by "
                         "default: it takes over the terminal, so children run with "
                         "stdout passed through instead of captured, and the "
                         "stdout-derived summary columns in REPORT.md are empty.")
    ap.add_argument("--pi-live", action="store_true",
                    help="MODE B: a REAL Pi drives the 22-byte command packet; the "
                         "children run with --pi-live and send injection frames only. "
                         "Scenarios carrying their own pi_timeline are SKIPPED (with a "
                         "reason) rather than run against a second command source.")
    ap.add_argument("--with-operator", action="store_true",
                    help="also run the scenarios marked operator_required in the "
                         "SCENARIOS registry ('drive'). They are SKIPPED by "
                         "default: their stimulus is a human driving the firmware "
                         "over USB serial, so unattended they command nothing and "
                         "a clean result proves only that the board idles.")
    ap.add_argument("--with-ftp75", action="store_true",
                    help="also run the long EPA FTP-75 cycle scenarios "
                         "(%s). They are SKIPPED by default purely on RUN TIME "
                         "— 350 s each, %.1f min for the SET of %d on a "
                         "campaign that is otherwise ~34 min. Nothing about "
                         "the board or the link blocks them."
                         % (", ".join(sorted(FTP75_SCENARIOS)),
                            sum(float((SCENARIOS.get(n) or {}).get("duration_s", 0.0))
                                for n in FTP75_SCENARIOS) / 60.0,
                            len(FTP75_SCENARIOS)))
    ap.add_argument("--with-ftp75c", action="store_true",
                    help="also run the COMPRESSED FTP-75 legs on the "
                         "ROAD-LOAD-COMPENSATED plant (%s), %.1f min for the "
                         "set of %d. They are SKIPPED by default on run time "
                         "AND because `--drag scaled-air` is a HIL-ONLY plant "
                         "configuration that needs a second road-load motor to "
                         "replicate on the bench. They are the only "
                         "drive-cycle legs on this rig that regenerate at all."
                         % (", ".join(sorted(FTP75C_SCENARIOS)),
                            sum(float((SCENARIOS.get(n) or {}).get("duration_s", 0.0))
                                for n in FTP75C_SCENARIOS) / 60.0,
                            len(FTP75C_SCENARIOS)))
    ap.add_argument("--with-alpha", action="store_true",
                    help="also run the three SDP alpha-sweep legs (%s). They "
                         "are SKIPPED by default because they are an "
                         "EXPERIMENT, not a regression: each replays one point "
                         "of the eta-era alpha sweep on the `ems-sdp` "
                         "stimulus. 61 s each."
                         % ", ".join(sorted(ALPHA_SCENARIOS)))
    ap.add_argument("--list", action="store_true", help="print the run plan and exit")
    ap.add_argument("--dry-run", action="store_true",
                    help="build every argv and write plan.json into the report dir; run nothing")
    args = ap.parse_args(argv)

    # F4: --dashboard hands the child the real stdout (see run_child()'s
    # TRADE-OFF comment) so it can draw ANSI directly -- but on a non-tty
    # stdout (piped into a file, captured by CI) that both fails to show a
    # dashboard AND throws away the captured stdout run_child() would
    # otherwise have parsed the per-run summary from. Refuse up front rather
    # than silently degrading both the dashboard and the report.
    if args.dashboard and not sys.stdout.isatty():
        ap.error("--dashboard requires a terminal (stdout is not a tty); "
                 "drop --dashboard or run this in an interactive terminal.")

    # F5: under --pi-live the operator's Pi is a second, uncontrolled stimulus
    # over whatever a replay run injects (replay mode plays recorded rails
    # regardless of what the Pi commands, and — unlike the scenario half — the
    # replay half is not skip-recorded per entry, so --pi-live would silently
    # run all 27 replays with a live Pi fighting the replayed trajectory).
    # --replay-only + --pi-live has NOTHING left to run once the whole replay
    # half is skipped for that reason, so refuse the combination up front
    # rather than producing an empty, confusing plan.
    if args.pi_live and args.replay_only:
        ap.error("--replay-only and --pi-live are mutually exclusive: under "
                 "--pi-live the entire replay half is skipped (a real Pi is an "
                 "uncontrolled second stimulus over a replayed trajectory), which "
                 "would leave --replay-only with nothing to run.")

    if args.out is None:
        # Default report directory lands in the repo-root "HIL Results" folder,
        # the shared home for every HIL artifact (hil_plant_sim.py resolves its
        # own relative --csv paths there too).
        args.out = os.path.join(
            HIL_RESULTS_DIR,
            "hil_report_%s" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        os.makedirs(HIL_RESULTS_DIR, exist_ok=True)
    # Children run with cwd = repo root, so every artifact path must be absolute
    # or a relative --out would scatter CSVs into the repo root.  An explicit
    # --out keeps its historical semantics: relative is relative to the CWD.
    # Per-run CSV paths below are built with os.path.join(args.out, ...) and are
    # therefore ABSOLUTE, which hil_plant_sim.resolve_output_path() honors
    # verbatim — the suite's artifacts never get redirected into HIL Results.
    args.out = os.path.abspath(args.out)

    plan = build_plan(args)
    warn_short_settle(args)

    if args.list:
        print_plan(plan, args)
        return 0

    # Campaign clock. Started here — the instant the report folder is claimed
    # and plan.json is stamped — so campaign_meta.json's window matches the
    # folder's own name and plan.json's mtime rather than starting somewhere
    # inside argument parsing.  --list returns above and never starts a clock.
    campaign_t0 = time.time()
    # The suite's own argv, as parsed: what would have to be re-run to reproduce
    # this campaign.  sys.argv[1:] when main() was entered from the CLI.
    suite_argv = list(argv) if argv is not None else list(sys.argv[1:])

    os.makedirs(args.out, exist_ok=True)
    plan_json = [{k: v for k, v in p.items() if k != "entry"} for p in plan]
    for p, pj in zip(plan, plan_json):
        pj["full_argv"] = full_argv(p, args)
    with open(os.path.join(args.out, "plan.json"), "w", encoding="utf-8") as fh:
        json.dump({"out": args.out, "teensy_ip": args.teensy_ip, "port": args.port,
                   "runs": plan_json}, fh, indent=2)

    if args.dry_run:
        print_plan(plan, args)
        print("\n[dry-run] plan written to %s" % os.path.join(args.out, "plan.json"))
        return 0

    # M4: what the plan CONTAINS, so an intermediate (partial) frontier record
    # can say "planned but not yet run" instead of blaming the plan for a leg
    # that simply has not been reached yet.
    planned_names = {p["name"] for p in plan}

    problems = verify_suite_logs(_REPO)
    if problems and not args.scenarios_only:
        print("[suite] WARNING: replay-suite log verification found %d problem(s):"
              % len(problems))
        for p in problems:
            print("  - %s" % p)

    def make_meta(aborted_now, partial_now):
        return {
            "date": datetime.datetime.now().isoformat(timespec="seconds"),
            "teensy_ip": args.teensy_ip, "port": args.port,
            "target_fw": TARGET_FW_VERSION,
            "host": "%s %s (%s)" % (platform.system(), platform.release(), platform.machine()),
            "python": platform.python_version(),
            "electrical_pref": args.electrical_pref,
            # WP-E: the SCENARIO half's droop realization (the replay half is
            # always "design"). Recorded unconditionally so a report reader
            # can place every sag figure on one side of the K_DROOP finding.
            "droop_mode": getattr(args, "droop", "design"),
            "droop_scale": DROOP_SCALE[getattr(args, "droop", "design")],
            # PART A (C1): the SCENARIO half's converter asymmetry.  Recorded
            # unconditionally so a report reader can place every share figure
            # on one side of the 2026-09-01 baseline boundary.
            "asymmetry": getattr(args, "asymmetry", ASYMMETRY_MODE_DEFAULT),
            "settle_s": args.settle_s,
            "out": args.out,
            "aborted": aborted_now,
            # M4: True whenever the plan did not run to completion for ANY reason
            # (Ctrl-C, an abort, or -- belt and suspenders -- a mismatched result
            # count), so a partial results.json/REPORT.md is never mistaken for a
            # clean, complete run.
            "partial": partial_now,
            "suite_log_problems": problems,
            "dashboard": args.dashboard,
            "mode": _suite_mode(args),
        }

    def write_outputs(meta_now, results_now):
        # M4: rewrite BOTH files after every run (not just once at the very end),
        # so a Ctrl-C or a hard kill loses at most the run in flight, never the
        # whole session's worth of already-completed results.
        # The cross-run EMS frontier verdict is recorded ALONGSIDE the per-run
        # results, not inside any of them: it is a property of the set. Written
        # on every rewrite so a partial report carries the honest UNVERIFIED
        # rather than nothing.
        payload = {"meta": meta_now, "results": results_now}
        frontiers_now = evaluate_ems_frontiers(results_now, planned_names)
        if frontiers_now:
            # `ems_frontiers` (plural) is the full list; `ems_frontier`
            # (singular) is kept pointing at the 61 s record so every existing
            # consumer of results.json keeps reading exactly what it read
            # before the second tuple existed.
            payload["ems_frontiers"] = frontiers_now
            for _f in frontiers_now:
                if _f.get("id") == EMS_FRONTIERS[0]["id"]:
                    payload["ems_frontier"] = _f
        with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
        with open(os.path.join(args.out, "REPORT.md"), "w", encoding="utf-8") as fh:
            fh.write(render_report(meta_now, results_now))

    results = []
    aborted = None
    interrupted = False
    try:
        results, aborted = _run_plan(plan, args, problems, results, write_outputs)
    except KeyboardInterrupt:
        interrupted = True
        print("\n[suite] interrupted (Ctrl-C) — writing partial results", file=sys.stderr)
    finally:
        partial = bool(interrupted or aborted or len(results) < len(plan))
        # Written from the SAME finally path that guarantees results.json and
        # REPORT.md, so an aborted campaign still records its window — with
        # completed=False and a finished_at that is the abort time.
        campaign = build_campaign_meta(args, suite_argv, plan, results,
                                       campaign_t0, time.time(),
                                       completed=not partial)
        write_campaign_meta(args.out, campaign)
        meta = make_meta(aborted, interrupted or len(results) < len(plan))
        # Carried on meta purely so render_report() stays a pure function of
        # (meta, results); it is not part of the results.json meta contract any
        # consumer parses by fixed key set.
        meta["campaign_timing"] = campaign
        write_outputs(meta, results)

    npass = sum(1 for r in results if r["passed"])
    inc = [r for r in results if r.get("inconclusive")]
    ninc_failed = sum(1 for r in inc if (r.get("also_failed") or 0))
    # An inconclusive run is not a failure of the board, so say so here rather
    # than letting it read as one in the headline number — but D3: one that ALSO
    # failed other checks must not be swept into "just re-run it".
    inc_note = ""
    if inc:
        inc_note = (", %d INCONCLUSIVE (mid-run warm reset — re-run those)"
                    % len(inc))
        if ninc_failed:
            inc_note += (" of which %d ALSO failed checks of their own"
                         % ninc_failed)
    print("\n[suite] %d/%d passed%s — report: %s"
          % (npass, len(results), inc_note,
             os.path.join(args.out, "REPORT.md")))

    # The cross-run EMS frontier verdict. Printed and SCORED separately from the
    # run tally: it is not a run, so folding it into "%d/%d passed" would make
    # the run count disagree with the plan. Anything but PASS is not-passing —
    # UNVERIFIED and KNIFE-EDGE included, because both mean the comparison the
    # campaign was run for was not made.
    frontiers = evaluate_ems_frontiers(results, planned_names)
    for _f in frontiers:
        print("[suite] EMS frontier (%s): %s — %s"
              % (_f["label"], _f["verdict"], _f["reason"]))

    if interrupted:
        return 130
    if aborted:
        return 2
    # F6: every planned run being skipped (e.g. --pi-live over a plan whose
    # scenario half is ALL pi_timeline/ems entries) is not a passing suite run —
    # nothing was ever actually exercised against the board. The old
    # `npass == len(results) and results` check let an all-skips run exit 0
    # because skipped runs count as "passed".
    if results and all(r.get("skipped") for r in results):
        print("[suite] every planned run was SKIPPED — nothing was exercised "
              "against the board; treating this as a failing suite run", file=sys.stderr)
        return 1
    # H1: only an EXIT-AFFECTING frontier verdict fails the run. A frontier that
    # is UNVERIFIED purely because its legs were never planned or were
    # explicitly SKIPPED (a `--pi-live` campaign, a filtered plan) is the
    # DOCUMENTED behaviour of those modes — failing them here contradicted this
    # function's own docstring and turned every clean `--pi-live` run into an
    # exit 1. The report still renders the UNVERIFIED verdict either way.
    _fail_frontier = False
    for _f in frontiers:
        if _f["passed"]:
            continue
        if _f.get("exit_affecting", True):
            print("[suite] the EMS frontier check (%s) did not pass (%s) — "
                  "treating this as a failing suite run"
                  % (_f["label"], _f["verdict"]), file=sys.stderr)
            _fail_frontier = True
        else:
            print("[suite] the EMS frontier (%s) is %s for a reason that is "
                  "not scored (no leg exercised, or a DOCUMENTED stimulus "
                  "split) — reported, not scored"
                  % (_f["label"], _f["verdict"]), file=sys.stderr)
    if _fail_frontier:
        return 1
    return 0 if npass == len(results) and results else 1


def _plus_tripwire(n, n_appended=1):
    """A replay entry's substantive-check count, INCLUDING the rows this file
    appends AFTER the replay half has finished counting.

    `n_appended` is 1 for the warm-reset tripwire alone, and 2 when a
    `child_process` failure row was appended beside it.

    ⚠️ L3 (2026-09-03): the `child_process` row used to reach the DENOMINATOR
    (`len(checks) + 1`) and never the substantive count, so every entry whose
    child failed reported one fewer substantive check than it had rows — on the
    one class of run where the reader most needs the census to be honest. That
    row is substantive by every test applied to the tripwire: it is scored, it
    can fail, and its failure is the finding.

    None in, None out: an entry whose counter never ran must not acquire a
    count here."""
    return None if n is None else int(n) + int(n_appended)


def _census_scalars(census):
    """The share-cut census WITHOUT its per-cut list (L4, 2026-09-02).

    None passes through as None (an entry that produced no census at all is not
    the same as one that produced an empty one)."""
    if not census:
        return census
    return {k: v for k, v in census.items() if k != "cuts"}


def _run_plan(plan, args, problems, results, write_outputs):
    """The per-run loop, factored out of main() so M4's try/except/finally around
    it can rewrite results.json/REPORT.md after every run without duplicating the
    run body. Mutates and returns `results`; returns (results, aborted)."""
    aborted = None
    for i, item in enumerate(plan):
        if item.get("skip_reason"):
            # Recorded as a PASSING, explicitly-skipped run: it is not a failure of
            # the board, and silently dropping it would make the report's run count
            # differ between modes with nothing to explain why.
            print("[suite] (%d/%d) %s %s ... SKIPPED (%s)"
                  % (i + 1, len(plan), item["kind"], item["name"], item["skip_reason"]),
                  flush=True)
            results.append({
                "kind": item["kind"], "name": item["name"], "mode": item.get("mode", ""),
                "electrical_required": item.get("electrical_required"),
                "description": item.get("description", ""), "duration_s": 0.0,
                "cmd_mode": _suite_mode(args),
                "passed": True, "skipped": True, "skip_reason": item["skip_reason"],
                "checks": [{"name": "skipped", "passed": True,
                            "detail": item["skip_reason"]}],
                "notes": [], "metrics": {}, "events": {},
                "child": {"status": "skipped", "summary": {}},
                "csv": None, "events_path": None, "log_path": None,
                "key_metrics": "skipped",
            })
            write_outputs(
                {"date": datetime.datetime.now().isoformat(timespec="seconds"),
                 "teensy_ip": args.teensy_ip, "port": args.port,
                 "target_fw": TARGET_FW_VERSION,
                 "host": "%s %s (%s)" % (platform.system(), platform.release(),
                                         platform.machine()),
                 "python": platform.python_version(),
                 "electrical_pref": args.electrical_pref, "settle_s": args.settle_s,
                 "droop_mode": getattr(args, "droop", "design"),
                 "asymmetry": getattr(args, "asymmetry", ASYMMETRY_MODE_DEFAULT),
                 "out": args.out, "aborted": aborted,
                 "partial": (i + 1) < len(plan),
                 "suite_log_problems": problems,
                 "mode": _suite_mode(args)},
                results)
            continue

        print("[suite] (%d/%d) %s %s ..." % (i + 1, len(plan), item["kind"], item["name"]),
              flush=True)
        child = run_child(item, args)

        # Mid-run warm-reset tripwire — applied to BOTH halves.  The replay half
        # needs it at least as much as the scenario half: its `fault_latched`
        # checks are exactly the ones a silently-cleared latch turns into a false
        # PASS.
        wr_counts, wr_source = warm_reset_count(item["csv"], child)
        wr_check, wr_note, wr_reason = judge_warm_resets(
            item["name"], item["kind"], wr_counts, wr_source)

        if item["kind"] == "scenario":
            expect = FAULT_EXPECTATIONS.get(item["name"]) or {}
            survive = expect.get("survive_to")
            metrics = analyze_scenario_csv(
                item["csv"], survive_to_t=(float(survive["t"]) if survive else None))
            events = analyze_events(item["events"])
            sig_specs = expect.get("signals_require") or []
            signals = scan_signals(item["csv"], sig_specs) if sig_specs else None
            passed, checks = judge_scenario(item["name"], metrics, events, child,
                                            pi_live=getattr(args, "pi_live", False),
                                            duration_s=item.get("duration_s"),
                                            signals=signals)
            key = "obs %d/%d, faults %s" % (
                metrics["n_obs"], metrics["rows"],
                fault_names(metrics.get("fault_bits_post_grace") or 0))
            # EMS comparison surface (2026-08-31): only appended when the run
            # actually produced both figures, so no scenario's summary row grows
            # a pair of em-dashes it has no use for. Present for every simulated
            # scenario, which is what lets `ems-soc-band` and `ems-dp-replay` be
            # compared straight off the summary table.
            if (metrics.get("final_h2_cum_g") is not None
                    and metrics.get("delta_soc") is not None):
                key += ", h2 %.4g g / dSoC %+.5f" % (
                    metrics["final_h2_cum_g"], metrics["delta_soc"])
            res = {"kind": "scenario", "name": item["name"], "mode": item["mode"],
                   "cmd_mode": _suite_mode(args),
                   "electrical_required": item["electrical_required"],
                   "description": item["description"], "duration_s": item["duration_s"],
                   "passed": passed, "checks": checks, "notes": [],
                   "metrics": metrics, "events": events, "child": child,
                   # L7: the strategy the CHILD recorded, so the demonstration
                   # banner describes what ran rather than the registry default.
                   "ems_strategy": run_ems_strategy(item["csv"], child),
                   # WP-1C: the CHARGER ERA this run's plant ran in. Read from
                   # the run's own sidecar for the same reason `ems_strategy`
                   # is — the era is a property of the process that produced
                   # the CSV, not of this checkout's constants. Feeds the
                   # frontier's stimulus-coherence check and the REPORT.md
                   # era banner.
                   "eta_chg": run_eta_chg(item["csv"], child),
                   "csv": item["csv"], "events_path": item["events"],
                   "log_path": item["log"], "key_metrics": key}
            no_obs = metrics["n_obs"] == 0
        else:
            ev = evaluate_replay_csv(item["entry"], item["csv"])
            checks = list(ev["checks"])
            if child["status"] != "ok":
                checks.append({"name": "child_process", "passed": False,
                               "detail": "child %s (rc=%s)" % (child["status"],
                                                               child["returncode"])})
            passed = ev["passed"] and child["status"] == "ok"
            npass = sum(1 for c in checks if c["passed"])
            # ── L3 (2026-09-03): ONE substantive count, used by results.json
            # and by key_metrics.  It counts the rows this file appends AFTER
            # the replay half finished counting: the warm-reset tripwire
            # always, and the `child_process` row when the child failed.  The
            # two sites used to compute it separately and BOTH omitted the
            # `child_process` row, which is in `len(checks)` and therefore in
            # the denominator — so a failed child under-reported the census by
            # one on exactly the runs a reader most needs it honest on.
            n_subst = _plus_tripwire(ev.get("n_checks_substantive"),
                                     1 + (0 if child["status"] == "ok" else 1))
            # L2/L3: THREE distinct reasons a replay check can carry no evidence,
            # and they mean different things to a reader. Branch on the ENTRY's own
            # `replay_commands` (the intent), not on the observed counters, so an
            # opt-in entry whose loop never actually stepped is named as the real
            # finding it is rather than lumped in with the entries that never asked
            # for a command in the first place.
            if not ev.get("replay_commands"):
                nonevidence_why = "no command replay"
            elif ev.get("n_checks_not_exercised"):
                # Defensive: NOT EXERCISED is only ever applied to a non-opt-in
                # entry, so this pairing should be unreachable. Named rather than
                # silently folded into the branch below.
                nonevidence_why = "opt-in entry tagged NOT EXERCISED (suite bug)"
            else:
                nonevidence_why = "commands replayed, loop never stepped"
            res = {"kind": "replay", "name": item["name"], "mode": item["mode"],
                   "cmd_mode": _suite_mode(args),
                   "description": item["description"], "duration_s": item["duration_s"],
                   "passed": passed, "checks": checks, "notes": ev.get("notes", []),
                   # A5 (campaign 20260830_214819): this used to be a hardcoded
                   # `{}`, so a replay run that ended LATCHED (0x8100 / 0x8001 in
                   # its own sidecar) had no fault record here at ALL — results.json
                   # carried none and REPORT.md's replay block printed none, so the
                   # end state that carries into the NEXT run was invisible.
                   # evaluate_replay_csv() now returns the metrics from its own
                   # single parse of the same CSV, with scenario-matching field
                   # names where the semantics match and the scenario-only fields
                   # OMITTED rather than faked (see ReplayCsv.metrics()); the
                   # replay per-entry block in render_report() renders them (M2).
                   "metrics": ev.get("metrics") or {},
                   "events": {}, "child": child,
                   "csv": item["csv"], "events_path": None, "log_path": item["log"],
                   "n_checks_vacuous": ev.get("n_checks_vacuous"),
                   # ── THE CENSUS DENOMINATOR (2026-09-03, campaign
                   # 20260902_220604 F4). `evaluate_replay_csv()` counted
                   # substantive-vs-total over the rows IT built, and the
                   # `warm_reset_tripwire` is appended one level up, AFTER
                   # the counter has run -- so the replay half reported its
                   # fractions over 111 rows while the report rendered 138.
                   # The tripwire IS substantive (it is scored, it can fail,
                   # and a silently-cleared latch is exactly what it catches),
                   # so it is COUNTED here rather than excluded, and both the
                   # totals and `key_metrics` below now describe every row.
                   # ...and the `child_process` row, when one was appended, on
                   # exactly the same reasoning (L3, 2026-09-03): `checks`
                   # already carries it, so it is in the denominator either way
                   # and must be in the numerator too.
                   "n_checks_substantive": n_subst,
                   "n_checks_total": len(checks) + 1,
                   "n_checks_not_exercised": ev.get("n_checks_not_exercised"),
                   "n_checks_stimulus_vacuous":
                       ev.get("n_checks_stimulus_vacuous"),
                   "n_checks_informational": ev.get("n_checks_informational"),
                   # The replay half's share-cut census (2026-09-02). Reported,
                   # never scored -- carried into results.json so a campaign can
                   # total it across entries instead of re-deriving it from 27
                   # CSVs, which is how the 163-cut finding was made.
                   # SCALARS ONLY (L4, 2026-09-02): the census also carries a
                   # per-cut list (up to 50 dicts per entry), which is ~27x50
                   # rows of duplicated per-tick data in a file nothing reads it
                   # from -- the totals are what a campaign sums. The full list
                   # stays in the replay half's own per-entry output, where the
                   # cut times are still available for a follow-up.
                   "share_cut_census": _census_scalars(
                       ev.get("share_cut_census")),
                   "replay_commands": ev.get("replay_commands"),
                   # Item 5: "%d/%d checks passed" counts vacuous checks alongside
                   # real ones. Say how many carried evidence, so a green replay
                   # entry cannot read stronger than it is. The parenthetical also
                   # says WHY there was no evidence — see `nonevidence_why` above
                   # for the three-way distinction.
                   "key_metrics": ("%d/%d checks passed" % (npass, len(checks)))
                                  + (" (commands replayed)"
                                     if ev.get("replay_commands") else "")
                                  + ("" if not ev.get("n_checks_vacuous") else
                                     " (%d substantive of %d, %d not evidence — %s)"
                                     % (n_subst,
                                        len(checks) + 1,
                                        ev["n_checks_vacuous"], nonevidence_why))}
            # L8: evaluate_replay_csv() now returns a structured "n_obs" (None if
            # the CSV itself could not be loaded/parsed at all) instead of forcing
            # this caller to substring-match a prose note from a different module.
            # Treat "unknown" the same as "zero" for the abort decision: a CSV that
            # never even parsed is at least as strong evidence the board never
            # answered as a CSV with zero observation rows.
            no_obs = ev.get("n_obs") in (0, None)

        # Fold the tripwire in AFTER the half-specific judging, so it applies
        # uniformly and cannot be forgotten by either branch.  An inconclusive
        # run is deliberately NOT counted as passing (it must be re-run), but it
        # is flagged separately so the report never renders it as a plain FAIL —
        # nothing was proven wrong about the board, the evidence was destroyed.
        # D3: whether any OTHER check failed is decided BEFORE the tripwire is
        # folded in, so an inconclusive verdict can never hide a real failure.
        other_failures = sum(1 for c in res["checks"] if not c["passed"])
        res["checks"] = list(res["checks"]) + [wr_check]
        res["warm_resets_mid_run"] = wr_counts.get("mid_run")
        res["warm_resets_observed"] = wr_counts.get("observed")
        res["warm_reset_times_s"] = wr_counts.get("times")
        res["warm_reset_source"] = wr_source
        if wr_note:
            res["notes"] = list(res.get("notes") or []) + [wr_note]
        if wr_reason is not None:
            res["inconclusive"] = True
            res["inconclusive_reason"] = wr_reason
            res["also_failed"] = other_failures
            res["passed"] = False
        elif not wr_check["passed"]:
            res["passed"] = False          # an EXPECTED recovery that never happened
        res["key_metrics"] += ", %s" % (
            ("INCONCLUSIVE — %s mid-run warm reset(s)%s"
             % (wr_counts.get("mid_run"),
                "; also FAILED %d check(s)" % other_failures if other_failures else ""))
            if wr_reason is not None else
            # LOW (2026-08-31 ledger fix queue) — LABEL, not semantics.  The
            # number rendered here has always been the MID-RUN count (resets
            # after WARM_RESET_GRACE_S), which is the one the tripwire scores;
            # `warm_resets_observed` is the whole-run count and is the one a
            # reader intuitively expects behind the words "warm resets".  Every
            # sequential-campaign run legitimately shows 1 observed / 0 mid-run,
            # so the bare label read as "no warm reset happened" on a board that
            # had just performed one.  Both numbers are now named.  The SCORED
            # quantity is unchanged: the tripwire, `passed`, and the
            # results.json fields all still key on mid_run alone.
            ("mid-run warm resets %s (of %s observed)"
             % ("?" if wr_counts.get("mid_run") is None
                else wr_counts["mid_run"],
                "?" if wr_counts.get("observed") is None
                else wr_counts["observed"])))

        results.append(res)
        print("    -> %s (%s)"
              % (result_label(res), res["key_metrics"]))
        if wr_note:
            print("       NOTE: %s" % wr_note)

        # M4: rewrite the report after every completed run (not just at the very
        # end), so an interruption below or later in the plan loses at most the
        # run in flight. `partial=True` here is provisional -- main()'s finally
        # block writes the authoritative final meta once the loop actually exits.
        write_outputs(
            {"date": datetime.datetime.now().isoformat(timespec="seconds"),
             "teensy_ip": args.teensy_ip, "port": args.port,
             "target_fw": TARGET_FW_VERSION,
             "host": "%s %s (%s)" % (platform.system(), platform.release(), platform.machine()),
             "python": platform.python_version(),
             "electrical_pref": args.electrical_pref, "settle_s": args.settle_s,
             "droop_mode": getattr(args, "droop", "design"),
             # Beside droop_mode on EVERY meta write, including this in-flight
             # one: a live-mode reader must not see "not recorded" for the
             # whole campaign and conclude the tool predates the C1 round.
             "asymmetry": getattr(args, "asymmetry", ASYMMETRY_MODE_DEFAULT),
             "out": args.out, "aborted": aborted,
             "partial": (i + 1) < len(plan),
             "suite_log_problems": problems,
             "mode": _suite_mode(args)},
            results)

        if i == 0 and no_obs and not args.keep_going:
            aborted = ("board unreachable: the first run (%s) saw ZERO observation "
                       "frames. Aborting rather than grinding through %d more dead run(s). "
                       "Check the flash flags (-DHIL_SIM=1 -DUSE_ETHERNET=1), the IP "
                       "(%s:%d) and that host and board share an L2 segment. "
                       "Pass --keep-going to run the whole plan anyway."
                       % (item["name"], len(plan) - 1, args.teensy_ip, args.port))
            print("[suite] " + aborted, file=sys.stderr)
            break

        if i + 1 < len(plan) and args.settle_s > 0:
            time.sleep(args.settle_s)

    return results, aborted


if __name__ == "__main__":
    sys.exit(main())
