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

from hil_plant_sim import (                                        # noqa: E402
    SCENARIOS, TEENSY_PORT_DEFAULT, WARM_RESET_GRACE_S, REPLAY_PREAMBLE_S,
    # switch_state bit masks, for FAULT_EXPECTATIONS' signals_require specs.
    # Imported, never re-declared: they mirror the firmware's switch_state packing
    # and a second copy here would be a silent divergence waiting to happen.
    SW_FC_BUS, SW_BT_BUS, SW_REGEN, SW_FC_CHARGE,
    # aux-byte bit mask, for the `aux_bit` specs.  Same rule as the switch masks:
    # imported, never re-declared (.ino:2823 packs this byte).
    AUX_MPPT_DISABLE,
    # The `ems-y-*` profile geometry, so the signal windows below are DERIVED
    # from the same constants the stimulus is (EMS_Y_START_S and the region
    # table), not re-typed. A table edit that moves a region boundary must move
    # these windows, and importing them is what makes that visible.
    EMS_Y_START_S, COMBINED_PROFILE,
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
    # The emulated Pi's command cadence, for the `strictly_decreases_by` window
    # guard below.  Imported (not re-typed) for the same reason every other
    # stimulus constant here is: moving PI_CMD_HZ must move the guard with it.
    PiCommander,
    # EMS strategy ROLES (2026-09-01).  Imported, never re-declared: the roles
    # are a property of the strategies, and a second copy here would let a
    # demonstration strategy be scored on the frontier after somebody moved the
    # role and not this file.
    EMS_STRATEGY_META, ems_frontier_eligible,
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
)

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
FTP75_SCENARIOS = frozenset({"ems-ftp75-5050", "ems-ftp75-socband",
                             "ems-ftp75-sdp"})

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
        "source": "docs/HIL_MODE.md test H2 — 'mainState 99 and fault_flags with "
                  "the UV bit set, latched' for the -5 V / 1 s dip past "
                  "LIMIT_V_BUS_MIN. Measured on hardware at 19.887 ms of dwell vs "
                  "the 20.0 ms design (HIL_FINDINGS 'sag').",
        "require": FAULT_UV_BUS,
        "allow_only": FAULT_UV_BUS | FAULT_ERROR,
        "not_before_s": 5.0,          # the dip starts at t = 5.0 (apply_scenario)
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
        "source": "operator ruling (b) 2026-08-30 + HIL_FINDINGS 'charge-cruise': "
                  "measured OC_FC at t = 8.7221 s, I_fc 1.4065 A on a smooth "
                  "190 ms charger ramp, bus bookkeeping closing to 9 mA",
        "require": FAULT_OC_FC,
        "allow_only": FAULT_OC_FC | FAULT_UV_BUS | FAULT_ERROR,
        # The charge_goal step is at t = 8.0 (SCENARIOS['charge-cruise']). An OC_FC
        # before that did NOT come from the charging ramp and is a different defect.
        "not_before_s": 8.0,
        # ... and it must get there in Run, not by dying during the cruise ramp.
        "survive_to": {"t": 8.0, "states": {2, 3}},
    },
    "charge-regen": {
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
            {"name": "charge_current", "column": "I_charge", "min_value": 0.5,
             "t_window": (14.0, 16.1),
             "label": "I_charge delivered through the REGEN path in window 1"},
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
        #   NOT REPEATABLE (a ~35 % spread is the healthy reading): the delay
        #     from the collapse to MPPT_DISABLE going high — MEASURED 20.36 /
        #     26 / 30.16 ms across campaigns 20260830_203006 / 20260831_191509 /
        #     20260831_222036.
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
        # current.  MEASURED 270.704 s (round-1 campaign 20260831_000518) — 0.8 %
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
             "label": "the CALIBRATED policy never opened the charger path — "
                      "the Ag105 charge lever (0.2364 SoC/g) is below the "
                      "artifact's own 0.30682 SoC/g admission threshold, so "
                      "the action is declined ENDOGENOUSLY (zero charge cells, "
                      "forbid_charge_all False)"},
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
        # because this run can; the UV objective needs its own home (a
        # v_bus_sense_offset scenario), which is an open item, not a silent gap.
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
    else:
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
        "allow_only": 0,
        "survive_to": {"t": _Y_SURVIVE_T, "states": {2, 3}},
        "signals_require": _sig,
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
# hold-5050: [0.045, 0.085] around the measured 6.47e-2 — 30 % below, 31 % above.
# Safe as a two-sided band because this scenario is expected FAULT-FREE, so the
# run always reaches t = 345 and the total is always the whole cycle's.
_FTP_H2_BAND_5050 = (0.045, 0.085)
# soc-band: the ceiling only, at the ledger's 0.115 (26 % above the measured
# 9.16e-2).
#
# ⚠️ DELIBERATE ASYMMETRY — THE LEDGER'S 0.070 FLOOR IS NOT APPLIED, and the
# reason is in this scenario's own expectation. `ems-ftp75-socband` ALLOWS
# OC_FC (operator ruling (b)), and an OC_FC latch STOPS the run: the board goes
# to State 99, the cycle does not finish, and h2_cum_g freezes at whatever it
# had reached. A latch at t = 200 leaves ~4e-2 g and a floor of 0.070 would FAIL
# it — failing a run for doing exactly what the entry says is correct. A ceiling
# has no such problem: truncation can only make the total SMALLER, so the
# ceiling stays sound under every allowed outcome. The floor therefore stays at
# the old conservative 5e-3 ("the accounting ran"), and it stays there until
# either the OC_FC allowance is retired or the entry grows a
# completed-run-only branch. Stated rather than silently narrowed.
_FTP_H2_FLOOR = 5.0e-3
_FTP_H2_CEILING_SOCBAND = 0.115

FAULT_EXPECTATIONS["ems-ftp75-5050"] = {
    "source": ("hil_plant_sim.py SCENARIOS['ems-ftp75-5050'] + the generated "
               "tools/ftp75_profile.py (EPA ftpcol.txt, sha256-verified, first "
               "340 s per references/Systemic_Scaling_of_Powertrain_Models_"
               "with_Youla_Driver_Control.pdf) + the FTP75_PRELOAD_A budget."),
    # FAULT-FREE IS THE EXPECTATION, and the budget says it should be: the peak
    # source total is 1.613 A at t = 245, and hold-5050's fixed 0.50 split puts
    # 0.807 A on a channel — 42 % under LIMIT_I_FC_MAX 1.4 A. The only way to
    # spend that margin is a drive-controller rail (MOTOR_I_CMD_MAX 12 A) AT
    # high speed, which maps to ~2.02 A of bus current at 3.0 m/s and would
    # reach 1.41 A on the channel; this cycle's high-speed segment is a
    # PLATEAU (56.6 -> 56.7 mph), so the loop does not rail there, and its
    # sharp transitions are all at low speed where a rail costs little bus
    # current. If a campaign latches OC_FC here, the finding is that
    # coincidence, and the fix is FTP75_PRELOAD_A — not this field.
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
        # 2. ... and the BOARD carried the load at the commanded split. At the
        #    peak the model's source total is 1.613 A, so a 0.50 split is
        #    0.807 A; 0.70 is a floor under that and far above the ~0.40 A a
        #    0.50 split of the 0.800 A standstill total would give, so it
        #    cannot be satisfied by an idling run that merely reached t = 245.
        {"name": "ftp_fc_carried", "column": "I_fc", "min_value": 0.70,
         "t_window": _FTP_PEAK_W,
         "label": "the FC channel carried its half of the peak load"},
        # 3-4. The H2 metric ran end to end over a 345 s cycle — the longest
        #    accounting run in the suite, and the reason these scenarios exist —
        #    AND landed in its measured band. Two specs, because one spec cannot
        #    carry both bounds (see _FTP_H2_BAND_5050).
        {"name": "ftp_h2_accounted", "column": "h2_cum_g",
         "min_value": _FTP_H2_BAND_5050[0],
         "label": "the H2 consumption metric accumulated over the cycle "
                  "(>= %.3f g; measured 6.47e-2)" % _FTP_H2_BAND_5050[0]},
        {"name": "ftp_h2_bounded", "column": "h2_cum_g",
         "max_value": _FTP_H2_BAND_5050[1],
         "label": "... and stayed under %.3f g — a ceiling the measured "
                  "6.47e-2 clears by 31 %%, so a scale or accumulation error "
                  "in the metric fails here instead of being read as a result"
                  % _FTP_H2_BAND_5050[1]},
    ],
}

FAULT_EXPECTATIONS["ems-ftp75-socband"] = {
    "source": ("hil_plant_sim.py SCENARIOS['ems-ftp75-socband'] + the "
               "SocBandStrategy docstring and SOC_BAND_* constants + the "
               "FTP75_PRELOAD_A budget. OC_FC allowance per OPERATOR RULING "
               "(b) 2026-08-30 (single-source FC operation is a design "
               "boundary, not a defect)."),
    # ── WHY OC_FC IS ALLOWED, AND WHY IT IS NOT REQUIRED ────────────────────
    # `soc-band` biases the split toward the fuel cell as the SoC deficit
    # grows, saturating at SOC_BAND_SHARE_NOMINAL + SOC_BAND_SHARE_SPAN = 0.75.
    # Over a 345 s cycle the deficit certainly saturates. At the cycle peak the
    # model's source total is 1.613 A, so a 0.75 split is 1.210 A — only 14 %
    # under LIMIT_I_FC_MAX 1.4 A, against a 42 % margin on the 5050 variant.
    # A drive-controller transient anywhere near the peak spends that margin,
    # and the resulting OC_FC is the CORRECT hardware response to a
    # single-channel overload, not a defect.
    #
    # NOT REQUIRED, because whether it happens depends on the SoC trajectory
    # (which sets when the bias saturates) and on transient tracking error —
    # neither of which this table should pretend to predict. A clean run is
    # equally correct.
    #
    # ⚠️ THE CHARGE BRANCH IS OUT OF REACH HERE, BY CONSTRUCTION, and that is
    # the second mechanism an OC_FC could have come from — so it is worth
    # stating that it cannot: `soc-band` admits a charge window only below
    # SOC_BAND_CHARGE_ENTER_ITOT_A = 0.60 A of source total, and
    # FTP75_PRELOAD_A puts the FLOOR at 0.800 A. `ems-soc-band` remains the
    # home of the charge-window assertion; nothing here asserts one.
    "allow_only": FAULT_OC_FC | FAULT_ERROR,
    "survive_to": {"t": _FTP_SURVIVE_T, "states": {2, 3}},
    "signals_require": [
        # 1. The policy ACTUALLY BIASED the split. Nominal is 0.50 and the
        #    ceiling is 0.75; 0.60 is unreachable without the SoC leaving the
        #    +/-SOC_BAND_HALF band, and unmistakable once it does. The window
        #    opens at t = 30 (the pack has ~25 s of load by then, far more than
        #    the ~15 s the 0.0015 band half needs at this cycle's pack current)
        #    and runs to the end of the profile.
        {"name": "socband_share_biased", "column": "cmd_share_sp",
         "min_value": 0.60, "t_window": (30.0, 340.0),
         "label": "soc-band commanded a share bias toward the fuel cell"},
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
        {"name": "socband_fc_carried", "column": "I_fc", "min_value": 0.95,
         "t_window": (30.0, 340.0),
         "label": "the board's share loop moved current onto FC beyond the "
                  "nominal split (window PEAK >= 0.95 A; the constant-0.50 "
                  "ems-ftp75-5050 control peaks at 0.8275 A over the same "
                  "window, so nothing below that discriminates)"},
        # 3-4. The H2 metric ran end to end, and stayed bounded. ASYMMETRIC BAND
        #    on purpose: the floor stays at the conservative 5e-3 because this
        #    entry ALLOWS OC_FC and a latch truncates the total, while the
        #    ceiling is the measured one. Full derivation at
        #    _FTP_H2_CEILING_SOCBAND.
        {"name": "ftp_h2_accounted", "column": "h2_cum_g",
         "min_value": _FTP_H2_FLOOR,
         "label": "the H2 consumption metric accumulated over the cycle "
                  "(conservative floor: an allowed OC_FC latch truncates it)"},
        {"name": "ftp_h2_bounded", "column": "h2_cum_g",
         "max_value": _FTP_H2_CEILING_SOCBAND,
         "label": "... and stayed under %.3f g — 26 %% above the measured "
                  "9.16e-2 g, and unreachable by a truncated run, so this "
                  "bound is sound under every outcome the entry allows"
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
               "branches' governed currents, and why the preload is 0.45 A "
               "here and 0.65 A on the two sibling FTP-75 scenarios) + "
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
    # FAULT-FREE, and this one is stricter than its FTP-75 siblings on purpose:
    # `ems-ftp75-socband` ALLOWS OC_FC because its 0.75 share ceiling leaves
    # only ~11 % of margin at the cycle peak. Here the preload was re-derived
    # DOWN to 0.45 A precisely so the 0.85 branch keeps 17.5 % at that peak
    # (the ADDITIVE composition of the measured span — see the FTP75_SDP
    # preload derivation in hil_plant_sim.py; the 18.5 % this line used to
    # quote scaled the model's FC branch instead, which understates the peak),
    # because an OC_FC latch would truncate the run at the point the scenario
    # exists to observe — the post-flip half. So an OC_FC here is a real
    # finding, not a design boundary.
    "allow_only": 0,
    # Past the whole flip band, fault-free: the run must reach its own
    # post-flip half, not merely survive the low-rail phase.
    "survive_to": {"t": 260.0, "states": {2, 3}},
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
        #    ⚠️ MEASURED (campaign 20260901_024231): the flip landed at
        #    t = 198.537 s (walk 195.9, +1.35 %) — ONE transition, both rails on
        #    the wire. The band is DE-PROVISIONALIZED from the walk's +/-20 %
        #    (150, 250) to (185, 212): 6.8 % of slack below the measurement and
        #    6.8 % above it, i.e. five times the walk-vs-board disagreement the
        #    campaign actually measured, and still far tighter than a band that
        #    admits a flip anywhere in the middle third of the cycle.
        {"name": "sdpftp_low_rail_early", "column": "cmd_share_sp",
         "max_value": _SDP_LOW_RAIL_CEIL, "t_window": (20.0, 185.0),
         "label": "the SDP policy commanded its BATTERY-HEAVY branch for the "
                  "whole pre-flip phase (no sample above the 0.15 clamp)"},
        # 3. ... AND THE FUEL-CELL BRANCH AFTER THE BAND. With check 2 this
        #    pins the transition inside (150, 250) s without needing a
        #    transition-detecting check kind: the command is provably at one
        #    rail before the band and provably reaches the other after it.
        {"name": "sdpftp_high_rail_late", "column": "cmd_share_sp",
         "min_value": _SDP_HIGH_RAIL_FLOOR, "t_window": (212.0, 340.0),
         "label": "... and switched to the FUEL-CELL branch (0.85) after the "
                  "flip band — with the check above, a measured crossing "
                  "inside t = 185..212 s (measured 198.537 s, campaign "
                  "024231)"},
        # 4-5. THE SAME SPAN ON THE PRE-CLAMP COLUMN, which is where the
        #    TABLE's own request is visible. 0.00 is a value the clamp hides
        #    entirely from `cmd_share_sp` (it emits 0.15 either way if the
        #    policy ever railed low for another reason), so these two are the
        #    checks that identify the ARTIFACT's branch rather than the
        #    emitted level.
        {"name": "sdpftp_raw_battery_branch", "column": "cmd_share_sp_raw",
         "max_value": _SDP_RAW_LOW_CEIL, "t_window": (20.0, 185.0),
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
         "min_value": _SDP_RAW_HIGH_FLOOR, "t_window": (212.0, 340.0),
         "label": "... and returned to its fuel-cell rail (1.00/0.95, or 0.90 "
                  "in demand bin 24) after the flip (measured post-flip "
                  "minimum 0.95, campaign 024231)"},
        # 6. THE BOARD ACTED ON THE BATTERY-HEAVY BRANCH. A CEILING on I_fc,
        #    and the derivation is the governor rather than the command: the
        #    commanded 0.15 is always below SHARE_MINORITY_I_MIN_A / I_tot at
        #    this cycle's currents (I_tot peaks at 1.41 A -> floor 0.213), so
        #    the DELIVERED FC current is pinned at the 0.300 A minority floor
        #    for the whole pre-flip phase. The constant-0.50 `ems-ftp75-5050`
        #    control peaks at 0.8275 A over a comparable window and the 0.85
        #    branch reaches 1.11 A, so a 0.45 A ceiling separates the
        #    battery-heavy branch from anything else this cycle can do.
        #    ⚠️ WHAT A PASS PROVES (inherited from every sibling entry): the
        #    plant splits bus current in proportion to the MDAC CODE RATIO
        #    (HIL_PLANT.md 4.7 — sign- and monotonicity-preserving, WRONG
        #    GAIN), so this asserts the firmware->MDAC arithmetic, not
        #    share-loop gain.
        #    ⚠️ MEASURED (campaign 20260901_024231): peak I_fc 0.3039 A over
        #    this window — 1.3 % above the 0.300 A governor floor, i.e. the
        #    floor exactly. The walk-era 0.45 A ceiling had 48 % of unused
        #    headroom; 0.35 A is 15 % above the measurement and still 2.4x under
        #    the 0.8275 A the constant-0.50 sibling reaches, so it keeps its
        #    discriminating power and now also fails a run in which the governor
        #    floor itself moved.
        {"name": "sdpftp_fc_floored_early", "column": "I_fc",
         "max_value": 0.35, "t_window": (30.0, 150.0),
         "label": "the board delivered the battery-heavy split — I_fc held at "
                  "the 0.300 A minority-governor floor, never near the "
                  "0.8275 A the constant-0.50 sibling reaches (measured peak "
                  "0.3039 A, campaign 024231)"},
        # 7. ... AND ON THE FUEL-CELL BRANCH. The mirror image at the cycle
        #    peak: I_fc = I_tot - 0.300 = 1.112 A (model) / 1.141 A (at the
        #    measured +2.6 % offset).
        #    ⚠️ MEASURED (campaign 20260901_024231): peak 1.1516 A over this
        #    window (0.9 % above the offset-corrected model). Floor raised from
        #    1.00 to 1.08 A = 6.2 % under the measurement, still 3.6x what the
        #    battery-heavy branch can reach, and 23 % under LIMIT_I_FC_MAX so a
        #    pass can never be confused with an overcurrent.
        {"name": "sdpftp_fc_carried_late", "column": "I_fc",
         "min_value": 1.08, "t_window": (235.0, 260.0),
         "label": "the board delivered the fuel-cell split at the cycle peak "
                  "(governed I_tot - 0.300 A; measured peak 1.1516 A, campaign "
                  "024231)"},
        # 7b. THE BATTERY CHANNEL'S OWN CEILING (new, campaign 024231). The
        #    scenario's whole-run peak I_batt is 0.7117 A and it lands AT THE
        #    FLIP (t = 198.53), where the branch hands over: 76 % under
        #    LIMIT_I_BT_MAX 3.0 A. A run-wide ceiling of 0.90 A is 26 % above
        #    the measurement, so it is a REGRESSION TRIPWIRE on the handover
        #    transient rather than a limit claim — the BT channel has never been
        #    bounded on this entry at all, and a share-loop or governor change
        #    that pushed current onto it would previously have gone unseen.
        {"name": "sdpftp_bt_peak_bounded", "column": "I_batt",
         "max_value": 0.90, "t_window": (5.0, 340.0),
         "label": "the battery channel stayed bounded through the branch "
                  "handover (measured whole-run peak 0.7117 A at the flip, "
                  "vs LIMIT_I_BT_MAX 3.0 A, campaign 024231)"},
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
        {"name": "sdpftp_h2_accounted", "column": "h2_cum_g", "min_value": 5.6e-2,
         "label": "the H2 consumption metric accumulated over the cycle "
                  "(measured 0.0621749 g, campaign 024231)"},
        {"name": "sdpftp_h2_bounded", "column": "h2_cum_g", "max_value": 7.0e-2,
         "label": "... and stayed under 0.070 g, so a scale or accumulation "
                  "error in the metric fails here instead of reading as a "
                  "result"},
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
        {"name": "sdpx_charge_window_count", "switch_bit": SW_FC_CHARGE,
         "edge_count_between": (6, 12), "edge": "rise",
         "t_window": (70.0, 190.0),
         "label": "... across 6-12 distinct charge windows (measured 9, i.e. a "
                  "16.13 s period, campaign 024231)"},
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
#   .ino:2911-2938; the HIL mirror that computes it, .ino:11185-11201).
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
# session but deliberately KEEPS ag105MpptRegCnt, .ino:10769-10775), so the whole
# span carries a value, not just the charge windows.
_MPPT_THRESH_W = (EMS_MPPT_CRUISE_WINDOWS[1][0], _MPPT_ALL_CRUISE_W[1])   # 28.1-41.0
# ~12.9 s of rows at the CSV's 1 kHz rate; 9000 is 70 % of them, leaving room for
# dropped observation frames while still FAILING LOUDLY on a run whose column is
# entirely blank — which is exactly what a campaign against a fw v21-v23 flash
# produces (16-byte frame, no byte 15, parse_output -> mppt_cnt None -> blank
# cell).  That failure mode is the point of the floor: a legacy run must not pass
# this entry by carrying no data.
_MPPT_THRESH_MIN_TICKS = 9000
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
_MPPT_RISE_BAND = (3, 8)
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
    # FIRST CAMPAIGN AGAINST fw v24.  The reg-0x02 count's exact value, the edge
    # census band and the tracking-engaged floor have never been measured on this
    # firmware; they are derivations from the .ino clamp arithmetic and the
    # stimulus geometry.  Calibrate them from the first green run, per the
    # first-campaign convention, and delete this note when they are measured.
    "provisional_note": ("fw v24 first campaign — _MPPT_RISE_BAND, the "
                         "tracking_engaged floor and the mppt_thresh_cnt band "
                         "are DERIVED, not measured"),
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
        {"name": "charging_occurred", "column": "I_charge", "min_value": 0.25,
         "t_window": _MPPT_CRUISE_W,
         "label": "the FC path delivered charge current (>= 0.25 A; the fw v24 "
                  "expectation is near the 1.0 A ceiling — report the peak)"},
        # 5. THE REFUSAL IS ABSENT.  Inversion of the old `low_power_seen`, which
        #    REQUIRED >= 50 ticks of GENSTAT 001 as proof the gate bound.  With
        #    the threshold clamped under the rail the module must never report
        #    Low Power; 50 ticks (50 ms) is allowed for a transient at a release
        #    edge, where the pin and the model's inhibit latch can disagree for a
        #    tick or two.  Vacuity companion: `tracking_engaged` below carries a
        #    positive bound on the same column.
        {"name": "refusal_absent", "column": "ag105_status",
         "value_mask": AG105_GENSTAT_MASK, "value_equals": AG105_ST_LOW_POWER,
         "max_ticks": 50, "t_window": _MPPT_ALL_CRUISE_W,
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
         "min_ticks": 1500, "t_window": _MPPT_ALL_CRUISE_W,
         "label": "MPPT_EN and PWR_TRACK both set — tracking released AND the "
                  "module actually tracking, the pattern fw v23 could not reach"},
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
         "label": "the board reported a WRITTEN reg-0x02 count (bit 7 clear, "
                  "i.e. not the 0x%02X external-resistor sentinel) — the fw v24 "
                  "threshold manager ran. A fw v21-v23 flash leaves this column "
                  "blank and FAILS here." % AG105_MPPT_N_RESISTOR},
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
        {"name": "mppt_threshold_floor", "column": "mppt_thresh_cnt",
         "min_value": AG105_MPPT_N_FLOOR, "t_window": _MPPT_THRESH_W,
         "label": "reg-0x02 count reached AG105_MPPT_N_FLOOR %d (%.3f V) or "
                  "above — the manager clamped rather than writing a threshold "
                  "under the bus-min guard"
                  % (AG105_MPPT_N_FLOOR, ag105_mppt_volts(AG105_MPPT_N_FLOOR))},
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
# `#define FAULT_HIL_LINK FAULT_PI_TIMEOUT` itself is :1265) and the frame carries
# no error_code, so the fault union alone cannot say which fired.  The
# `child_tx_healthy` check is the discriminator: if this process's own injection
# stream was continuous over the whole run, a HIL-link explanation is
# implausible and PI_TIMEOUT is what is left.  That is an inference BY
# ELIMINATION, not a direct read — the same documented residual the --pi-live
# excusal carries, and a frame extension to carry error_code would close it.
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
                                       "strictly_decreases_by")), (
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
                assert isinstance(_s, str) or "kind" in _s, (
                    "FAULT_EXPECTATIONS[%r].events_any_of[%r].%s: every event "
                    "spec needs a `kind`." % (_n, _g.get("name"), _b["name"]))

# Shape of the 2026-08-31 signal kinds, asserted at import for the same reason
# every bound here is: each of them fails SILENTLY when malformed.  A `value_mask`
# with no `value_equals` would raise KeyError deep in the scanner mid-campaign; a
# `switch_fall_latency_ms` whose window opens at or after its own `after_t` has no
# pre-edge level to compare against, so it can only ever report "no transition" —
# which reads as a board finding rather than as a table defect.
#
# A FUNCTION rather than an inline loop (2026-09-01) so a test can drive the
# guard over ONE synthetic spec.  The guards are the only thing standing between
# a malformed spec and a campaign that measures nothing, so they need coverage of
# their own — and duplicating them in the test file would let the two drift.
def _assert_signal_spec_shapes(_n, _e):
    """Assert the shape of every signals_require spec in ONE expectation entry.

    Raises AssertionError with a message naming the entry and the spec.  Pure:
    reads the entry, SCENARIOS, and module constants, and writes nothing."""
    for _i, _spec in enumerate(_e.get("signals_require") or ()):
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
                    or ("value_mask" in _sub), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: "
                    "`max_continuous_ticks` counts a run of SET/MATCHING ticks, "
                    "so it needs a `switch_bit`, an `aux_bit`, or a `value_mask` "
                    "to watch." % (_n, _tag))
                assert int(_sub["max_continuous_ticks"]) >= 0, (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: a negative "
                    "`max_continuous_ticks` can never be satisfied." % (_n, _tag))
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
            assert_derived_source_shape(_n, _tag, _sub)
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
         "soc_first": None, "soc_last": None,
         "delta_soc": None}
    if not os.path.isfile(csv_path):
        m["error"] = "CSV not written"
        return m
    subs = []
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
                        if survive_to_t is not None:
                            if t < survive_to_t:
                                m["fault_bits_before_survive"] |= bits
                            elif m["state_at_survive"] is None and state is not None:
                                m["state_at_survive"] = state
                s = (row.get("elec_substep_hz") or "").strip()
                if s:
                    try:
                        subs.append(float(s))
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
# ── ENTRY-LEVEL (not a signals_require spec) ────────────────────────────────
#   FAULT_EXPECTATIONS[name]["child_tx_healthy"] = True
#       Asserts THIS process's own injection stream was continuous over the run
#       (child_stream_continuity(): tx >= 98 % of full rate, zero send errors).
#       For scenarios whose OBJECTIVE is a command-side fault: it is the honest
#       discriminator between the two causes that share bit 0x0010 —
#       FAULT_PI_TIMEOUT and its alias FAULT_HIL_LINK — because the observation
#       frame carries no error_code (documented residual; a frame extension is
#       future protocol work).  UNMEASURED renders as a FAILED check with an
#       explicit "unmeasured" reason, never as a silent pass.
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
                # `edge_count_between` state: how many qualifying transitions the
                # window contained.  Counted against `prev_bit`, exactly as the
                # latency kind does, so a blank row cannot forge an edge.
                "edges": 0}

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
                        mask = int(spec.get("switch_bit", spec.get("aux_bit", 0)))
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
                        if m["peak"] is None or v > m["peak"]:
                            m["peak"] = v
                        if m["first"] is None:
                            m["first"] = v
                        m["last"] = v
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
                    if m["peak"] is None or v > m["peak"]:
                        m["peak"] = v
                    if m["first"] is None:
                        m["first"] = v
                    m["last"] = v
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
    if not m["rows"]:
        return False, ("no observed rows%s — the window this arm lives in was "
                       "never reached" % win)
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
    what = "masked value matched on" if "value_mask" in spec else "bit set on"
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
        kind = "matching" if "value_mask" in spec else "set"
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
    if "min_ticks" in spec:
        return (m["ticks"] >= int(spec["min_ticks"]),
                "%s %d tick(s)%s, need >= %d"
                % (what, m["ticks"], win, int(spec["min_ticks"])))
    if "max_ticks" in spec:
        return (m["ticks"] <= int(spec["max_ticks"]),
                "%s %d tick(s)%s, need <= %d"
                % (what, m["ticks"], win, int(spec["max_ticks"])))
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
                "peak %s%s, need <= %g"
                % ("unmeasured" if peak is None else "%.4f" % peak, win,
                   float(spec["max_value"])))
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

    `where` exists because `field_values` pools every event of a kind together:
    an scp-inrush run carries three sw_ring events (MOT_PWR plus FC_BUS/BT_BUS),
    and that entry's expectation turns on telling them apart.  (It was introduced
    2026-08-31 for the two-outcome form of that entry; the entry is single-outcome
    again since the stimulus redesign, and still pins `where` on its scp_cut.)"""
    spec = {"kind": req} if isinstance(req, str) else dict(req)
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
                               if first_t.get(fault_names(b)) is not None
                               and first_t[fault_names(b)] < not_before)
                if early:
                    got = False
                    detail += ("; but %s first appeared at t=%.3fs, BEFORE the "
                               "stimulus at t=%.1fs — it did not come from the "
                               "stimulus this check is about"
                               % (fault_names(sum(early)),
                                  first_t[fault_names(early[0])], not_before))
                else:
                    detail += ("; first seen at t=%s s, at or after the t=%.1fs "
                               "stimulus"
                               % (", ".join("%.3f" % first_t[fault_names(b)]
                                            for b in _split_bits(require)
                                            if fault_names(b) in first_t) or "?",
                                  not_before))
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

        # child_tx_healthy (2026-08-31): THIS process's own injection stream was
        # continuous.  Declared by a scenario whose objective is a COMMAND-side
        # fault, where the same 0x0010 bit could equally have come from the HIL
        # link going stale — and the observation frame carries no error_code to
        # tell them apart.  Asserting the injection stream was healthy is what
        # makes the command-side attribution defensible.
        if expect.get("child_tx_healthy"):
            cont_ok, cont_detail = child_stream_continuity(child, duration_s)
            checks.append({
                "name": "child_tx_healthy",
                # None (unmeasured) FAILS: an unverifiable attribution is not a
                # verified one, and this check exists precisely to make the
                # attribution defensible.
                "passed": bool(cont_ok),
                "detail": ("this process's injection stream: %s (%s)"
                           % (cont_detail, why))})

        # events_require accepts EITHER a bare kind string (at least one such event)
        # or a dict pinning count and/or a numeric field's plausibility band. The
        # bare form is kept because most future entries will want nothing more.
        # `prov_sfx` (the `provisional_note` qualifier) is built above, next to
        # the signals block, and rides these details too.
        for req in expect.get("events_require", ()):
            ok, observed, problems = _judge_event_spec(req, events)
            kind = (req if isinstance(req, str) else req["kind"])
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
        #       (the deliberate alias, .ino:1240-1248; the #define is :1265), and
        #       the 16/17-byte observation frame carries no
        #       error_code to tell them apart (residual noted below and in the
        #       manual). Excusing on the bit alone would also excuse a genuine
        #       injection-link failure. Narrowest defensible rule: excuse ONLY
        #       when (a) the fault union is EXACTLY 0x8010 — nothing else set,
        #       not even other latched bits alongside it — AND (b) THIS
        #       process's own injection stream was continuous for the run (its
        #       sendto() calls landed and kept pace), so a HIL-link explanation
        #       is implausible and PI_TIMEOUT is the only fault-producing
        #       explanation left standing. Continuity is judged from the
        #       child's own parsed summary: tx_frames >= 98% of the frames a
        #       full-rate run would have sent, and zero sendto() errors.
        #
        # Residual (documented, not fixed here): the observation frame has no
        # error_code, so even a "continuous stream" verdict is an inference by
        # elimination, not a direct read of which of the two aliased causes
        # fired. A frame extension to carry error_code is future protocol work
        # (see docs/HIL_MODE.md and the manual).
        #
        # 2026-08-30: this whole block is now judged on the POST-GRACE union, not
        # the whole-run one, for the same reason every other fault check is (see
        # analyze_scenario_csv).  It matters HERE in particular: the inherited
        # settle latch is ITSELF 0x8010, so on the whole-run union the "exactly
        # 0x8010" test fired on every run after the first and the excusal was
        # deciding about a bit the previous run left behind.
        exactly_pi_timeout = post == (FAULT_ERROR | FAULT_PI_TIMEOUT)
        # 2026-08-31: the continuity test moved to child_stream_continuity() so
        # the `child_tx_healthy` signal check judges it identically.  Semantics
        # are unchanged — including that an UNMEASURED stream (ok is None) is not
        # continuous for excusal purposes.
        cont_ok, cont_detail = child_stream_continuity(child, duration_s)
        stream_continuous = bool(pi_live and exactly_pi_timeout and cont_ok)
        if pi_live and exactly_pi_timeout and not stream_continuous:
            unexpected = post   # do NOT excuse — attribution to the Pi is unsafe
            excuse_detail = ("  (0x%04X observed but the injection stream had "
                              "gaps or is unmeasured — cannot attribute to the "
                              "Pi; NOT excused)" % post)
        elif stream_continuous:
            unexpected = 0
            excuse_detail = ("  (PI_TIMEOUT excused under --pi-live: post-grace "
                              "fault union is exactly 0x%04X "
                              "(FAULT_ERROR|PI_TIMEOUT) and this "
                              "process's own injection stream was continuous "
                              "(%s) — the operator's "
                              "Pi owns the command cadence. Residual: the "
                              "observation frame carries no error_code, so "
                              "PI_TIMEOUT vs the aliased HIL_STALE is inferred by "
                              "elimination, not read directly.)"
                              % (post, cont_detail))
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

    if events["over_absmax"]:
        checks.append({"name": "sw_ring_over_absmax", "passed": False,
                       "detail": "%d switching event(s) with an estimated ring peak above "
                                 "the %.0f V abs-max — the boost-death signature; worst %s V"
                                 % (events["over_absmax"], V_ABSMAX_V,
                                    ("%.2f" % events["worst_over_absmax_ring_v"])
                                    if events.get("worst_over_absmax_ring_v") is not None
                                    else "?")})

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


def evaluate_ems_frontier(results, planned_names=None):
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
    legs, missing = {}, []
    exit_affecting = False
    any_planned = False
    planned = set(planned_names or ())
    for role, name in EMS_FRONTIER.items():
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
        "lambda_soc_per_g": EMS_EQ_H2_LAMBDA_SOC_PER_G,
        "lambda_band": list(EMS_EQ_H2_LAMBDA_BAND),
        "vs_reference_max": EMS_FRONTIER_VS_REFERENCE_MAX,
        "vs_bound_max": EMS_FRONTIER_VS_BOUND_MAX,
        "roles": dict(EMS_FRONTIER),
        "legs": legs, "missing": missing,
        "exit_affecting": exit_affecting,
    }
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
        ok_ref = eq["candidate"] <= EMS_FRONTIER_VS_REFERENCE_MAX * eq["reference"]
        ok_bnd = eq["candidate"] <= EMS_FRONTIER_VS_BOUND_MAX * eq["bound"]
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
                              EMS_FRONTIER_VS_REFERENCE_MAX,
                              nom["eq_h2"]["bound"], nom["vs_bound"],
                              EMS_FRONTIER_VS_BOUND_MAX)))
    else:
        broke = []
        if not nom["passed_vs_reference"]:
            broke.append("vs the `%s` heuristic %.4f x (need <= %.2f)"
                         % (ref["name"], nom["vs_reference"],
                            EMS_FRONTIER_VS_REFERENCE_MAX))
        if not nom["passed_vs_bound"]:
            broke.append("vs the `%s` bound %.4f x (need <= %.2f)"
                         % (bound["name"], nom["vs_bound"],
                            EMS_FRONTIER_VS_BOUND_MAX))
        rec.update(verdict="FAIL", passed=False, exit_affecting=True,
                   reason=("the `%s` leg is OFF the frontier at matched "
                           "delta_soc: %s. This is a POLICY finding, not a "
                           "board one — no per-run check can see it."
                           % (cand["name"], "; ".join(broke))))
    return rec


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
    A(_row(["Settle pause between runs", "%s s" % meta.get("settle_s")]))
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
    frontier = evaluate_ems_frontier(results)
    if frontier is not None:
        A(_row(["EMS frontier", "**%s** — %s"
                % (frontier["verdict"], frontier["reason"])]))
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
    if frontier is not None:
        A("## EMS frontier — %s" % frontier["verdict"])
        A("")
        A("A CROSS-RUN check: an energy-management result is a COMPARISON, so no")
        A("per-run threshold can express it. Legs are compared on **SoC-corrected**")
        A("hydrogen, `eq_H2 = h2 - (dSoC - dSoC(reference)) / lambda`, with")
        A("`%s` as the reference." % EMS_FRONTIER["reference"])
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
             EMS_EQ_H2_LAMBDA_BAND[1], EMS_FRONTIER_VS_REFERENCE_MAX,
             EMS_FRONTIER_VS_BOUND_MAX))
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
                         "— 350 s each, ~11.7 min for the pair on a campaign "
                         "that is otherwise ~34 min. Nothing about the board or "
                         "the link blocks them."
                         % ", ".join(sorted(FTP75_SCENARIOS)))
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
        frontier_now = evaluate_ems_frontier(results_now, planned_names)
        if frontier_now is not None:
            payload["ems_frontier"] = frontier_now
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
        meta = make_meta(aborted, interrupted or len(results) < len(plan))
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
    frontier = evaluate_ems_frontier(results, planned_names)
    if frontier is not None:
        print("[suite] EMS frontier: %s — %s"
              % (frontier["verdict"], frontier["reason"]))

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
    if frontier is not None and not frontier["passed"]:
        if frontier.get("exit_affecting", True):
            print("[suite] the EMS frontier check did not pass (%s) — treating "
                  "this as a failing suite run" % frontier["verdict"],
                  file=sys.stderr)
            return 1
        print("[suite] the EMS frontier is %s because no leg of it was "
              "exercised (not planned / explicitly skipped) — reported, not "
              "scored" % frontier["verdict"], file=sys.stderr)
    return 0 if npass == len(results) and results else 1


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
                   "n_checks_substantive": ev.get("n_checks_substantive"),
                   "n_checks_not_exercised": ev.get("n_checks_not_exercised"),
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
                                     " (%d substantive, %d not evidence — %s)"
                                     % (ev.get("n_checks_substantive") or 0,
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
