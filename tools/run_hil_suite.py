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
    # `mppt-tracking` / `share-staircase` stimulus geometry, so the windows below
    # are DERIVED from the same constants the stimulus is.
    EMS_REGEN_BRAKE_WINDOWS, EMS_MPPT_CRUISE_WINDOWS,
    EMS_MPPT_CRUISE_LEAD_IN_S, EMS_MPPT_CRUISE_LEAD_OUT_S,
    # The emulated Pi's command cadence, for the `strictly_decreases_by` window
    # guard below.  Imported (not re-typed) for the same reason every other
    # stimulus constant here is: moving PI_CMD_HZ must move the guard with it.
    PiCommander,
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
FTP75_SCENARIOS = frozenset({"ems-ftp75-5050", "ems-ftp75-socband"})

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
                  "tools/sdp_policies/sdp_policy_v2.json (policy-block sha256 "
                  "740c802e…) + tools/sdp_ems_solver.py D11 (the demand map). "
                  "Current budgets from SOC_BAND_DRAIN_LOAD_A's LIMIT_I_FC_MAX "
                  "arithmetic, the firmware's own setpoint governor "
                  "(.ino:9556-9568), and the solver's charge mask.",
        # FAULT-FREE, mirroring `ems-soc-band` and `ems-dp-replay` — and the
        # budgets above are re-checked for BOTH of v2's operating points, so
        # nothing is allowed.
        "allow_only": 0,
        # DI-MED-5 — FIRST-CAMPAIGN THRESHOLDS, declared as such. Three of the
        # signal checks below carry bands that no v2 campaign has ever produced:
        # `sdp_table_interior_at_high_demand` and `sdp_table_rail_at_low_demand`
        # are read off the OPEN-LOOP offline walk over a v1 run's recorded
        # trace (header above), and `sdp_charge_window_opened` additionally
        # rides the PREDICTED ~1 Hz open/close chatter, which the walk cannot
        # contain because the walk has no plant response to a command v1 never
        # issued. A miss on any of the three must read as "threshold not yet
        # derived", never as a board or plant change.
        # DELETE THIS KEY after the first v2 campaign pins the bands from
        # measurement — the scp-inrush precedent (its `provisional_note` was
        # removed same-day once the i_cut band was measured live).
        "provisional_note":
            "first-campaign thresholds: sdp_table_interior_at_high_demand, "
            "sdp_table_rail_at_low_demand and sdp_charge_window_opened are "
            "derived from an OPEN-LOOP offline walk over a v1 trace (the "
            "charge-window tick count additionally from the PREDICTED ~1 Hz "
            "chatter), not from a measured v2 run",
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
             "label": "the sdp-v2 policy commanded the profile's 1.5 m/s cruise"},
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
            {"name": "sdp_table_interior_at_high_demand",
             "column": "cmd_share_sp_raw", "max_value": 0.97,
             "t_window": (20.0, 36.0),
             "label": "the v2 demand axis moved the table off its rail on the "
                      "drain plateau — the pre-clamp request is the interior "
                      "0.95, which a v1 (ideal-scaling map) artifact cannot "
                      "produce"},
            # 4. THE POLICY INTERIOR ACTUATED, HALF TWO — and the request comes
            #    BACK to the rail when the demand falls. Paired with check 3
            #    this asserts a SPAN in the table's request across the run,
            #    which is the whole claim the re-map makes.
            #    DERIVATION: over the post-drain 1.0 m/s cruise the walk's
            #    P_dem is 5.59 W -> bin 5, whose action is 1.00 at every SoC
            #    node below the relative target. Floor 0.99 sits between 1.00
            #    and the next ladder step down (0.95). Window 44.0-54.0 is
            #    `ems-soc-band`'s own charge-window window, chosen for the same
            #    reason: the drain has fully ramped out and the cruise is
            #    settled.
            #    ⚠️ This check is INSENSITIVE to the chatter described on check
            #    5: whether the charger path is open (bin ~18) or closed
            #    (bin 5), the table's action at a sub-target SoC node is 1.00 in
            #    both, so neither state can fail it.
            {"name": "sdp_table_rail_at_low_demand",
             "column": "cmd_share_sp_raw", "min_value": 0.99,
             "t_window": (44.0, 54.0),
             "label": "the table's request returns to the 1.00 rail at low "
                      "demand — with check 3, a measured span across the "
                      "demand axis"},
            # 5. THE INTERIOR ACTUATED ON THE OTHER CONTROL — A CHARGE WINDOW,
            #    which v1 could not reach BY CONSTRUCTION (its clamp pinned every
            #    decision into bin 24, and the solver forbids charging there).
            #    This is the strongest v1/v2 discriminator in the entry: it is a
            #    different ACTION selected by the demand axis, visible on the
            #    BOARD's own switch word rather than on a host column.
            #    DERIVATION. Under the 25 W map the solver's FC-current budget
            #    (its rule (b)) forbids charging above bin 5 and the dwell rule
            #    forbids bins 12+, so `charge_goal` = 1 exactly in bins 0-5
            #    (P_dem < 6.0 W) below the relative target. The walk lands that
            #    on t = 41.0..58.0 — the same post-drain low cruise
            #    `ems-soc-band` charges in, arrived at from a different rule.
            #    THRESHOLD. min_ticks 500 = 0.5 s of FC_CHARGE_ENABLE high
            #    anywhere in the window. Deliberately loose: a SINGLE 1 s
            #    decision already gives ~1000 ticks, so the floor carries 2x
            #    margin against the worst case the chatter below can produce.
            #    ⚠️ PREDICTED 1 Hz CHATTER, derived not measured. Opening the
            #    charger path adds its ~0.8 A to I_fc, so the measured P_dem
            #    jumps ~5.6 W -> ~18.3 W = bin 18, which is charge-FORBIDDEN, so
            #    the next 1 s decision withdraws the intent and the path closes.
            #    The policy is memoryless in the demand bin and has no
            #    hysteresis (`soc-band` avoids exactly this with its dual i_tot
            #    gate), so ~8 open/close cycles are expected over the window,
            #    each costing a BT_BUS cut and restore through
            #    assertFcChargeEnable(). Neither state exceeds a current limit
            #    (budget in the header), and `ems-y-b00` exercises the same cut
            #    and restore fault-free at a heavier load.
            #    ⚠️ WHY THIS IS A SWITCH CHECK AND NOT `ems-soc-band`'s
            #    I_charge >= 0.5 A: the Ag105 may never reach chargerReady
            #    inside a 1 s open window, so an I_charge floor could fail a
            #    perfectly correct board. What is asserted is that the POLICY
            #    commanded the path open and the FIRMWARE opened it.
            {"name": "sdp_charge_window_opened", "switch_bit": SW_FC_CHARGE,
             "min_ticks": 500, "t_window": (41.0, 58.0),
             "label": "the v2 policy's low-demand charge action reached the "
                      "board — FC_CHARGE_ENABLE opened in the post-drain "
                      "cruise, which the v1 artifact could not command"},
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
_Y_FC_FLOOR = {1.0: 0.50, 3.0: 0.66}

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
# mppt-tracking  —  the Ag105 MPPT input-voltage threshold, closed-loop
#
# ⚠️ THIS ENTRY ASSERTS A MODEL PREDICTION, and says so.  With `mppt_emulation`
# on, the plant refuses to charge while tracking is RELEASED and the input rail
# is under AG105_MPPT_V_THRESH (18 V default with MPPTS open, datasheet p.10 —
# NOT perturb-and-observe).  The bus is ~15.95 V, so on the FC path the threshold
# BINDS, and because the firmware releases tracking only once the charger reports
# ready (ag105IsReady(), .ino:10249-10255), the two HUNT at the charger's own
# 50 Hz cadence.  The full loop trace is in ems_mppt_harvest()'s docstring.
#
# CONTINGENT ON R1 (does this board fit an MPPTS resistor setting a threshold
# below the bus?).  A campaign that does not see the hunt is EVIDENCE ABOUT R1,
# not a scenario defect — record it as a hardware finding and move the constant
# and this entry together.
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
# is thin once AG105_SETTLE_S (0.5 s) is spent, and the hunt's statistics are
# better read across all three.
_MPPT_ALL_CRUISE_W = (EMS_MPPT_CRUISE_WINDOWS[0][0],
                      EMS_MPPT_CRUISE_WINDOWS[-1][1])          # 16.1-41.0
# TICK BUDGETS, all MODELLED from the loop trace above and stated as such.
#
# ⚠️ RE-DERIVED 2026-08-31 (review M1).  The earlier derivation used the three
# cruise PLATEAUS (3 x 1.9 s = 5.7 s) as the budget, but MPPT_DISABLE can only
# be HIGH inside the windows the STRATEGY actually asserts charge_goal on, which
# are the plateaus INSET by EMS_MPPT_CRUISE_LEAD_IN_S/_OUT_S:
#     3 x (1.9 - 0.30 - 0.10) = 3 x 1.5 s = 4.5 s of charge-goal time,
#     minus 3 x AG105_SETTLE_S (0.5 s)    = 3.0 s in which the pin can be HIGH.
# Everywhere else in the run the firmware holds it LOW, so the CEILING is 3.0 s
# = ~3000 ticks at the CSV's 1 kHz row rate, NOT the ~24900-row window span the
# old note reasoned from.  That is why the old 10000 could never bind: BOTH the
# hunting outcome and the stuck-high outcome passed it, and the check was inert.
_MPPT_TOGGLE_MIN_TICKS = 300
# THE TWO OUTCOMES THIS CEILING MUST SEPARATE, both re-measured on the offline
# probe (2026-08-31; the plant's charger branch verbatim against the firmware's
# 20 ms poll with its one-poll lag, 15.95 V rail, 1.0 A ceiling):
#     HUNT       pin HIGH 50.0 % of post-settle ticks
#                -> ~1500 ticks    (i_charge equilibrium 0.472-0.525 A)
#                ⚠️ RECORD CORRECTED 2026-08-31 (ledger, "record correction"):
#                this line quoted a full hunt period of 80.0 ms from the offline
#                probe.  The MEASURED median on hardware is 40.05 ms — campaign
#                20260831_191509, and the 138 MPPT_DISABLE toggles it counted
#                over the cruise windows ARITHMETICALLY REQUIRE it (80 ms would
#                give about half that many).  THE CEILING BELOW IS UNAFFECTED
#                and was NOT re-derived: this budget counts HIGH TICKS, which
#                depend only on the DUTY (50 %), not on the period.  A faster
#                hunt at the same duty lands on the same ~1500 ticks.  The
#                period only matters where it sets the charger's ramp average,
#                and the I_charge floor below already quotes the correct ~40 ms.
#     STUCK HIGH pin released and never withdrawn
#                -> ~3000 ticks    (the whole post-settle budget above)
# 2200 sits between them: 1.47x the modelled hunt and 0.73x the stuck-high
# outcome, so a hunt slower than modelled by up to ~45 % still passes and a pin
# that simply SAT high cannot.  Move it only with a measurement of the hunt in
# hand — this ceiling is the entire "it toggled" assertion.
_MPPT_TOGGLE_MAX_TICKS = 2200
FAULT_EXPECTATIONS["mppt-tracking"] = {
    "source": ("AG105_Silvertel.pdf p.10 (MPPT is an INPUT-VOLTAGE THRESHOLD, "
               "11-33 V settable, 18 V default with MPPTS open) + "
               "hil_plant_sim.AG105_MPPT_V_THRESH and ems_mppt_harvest() + "
               ".ino:10037-10050 (chargingControl's cruise else-block) and "
               ":10249-10255 (ag105IsReady). ⚠️ MODEL PREDICTION, contingent on "
               "open question R1 (MPPTS resistor unconfirmed)."),
    # Fault-free.  Budget at the 0.4 m/s charge plateaus, where the FC path is
    # SINGLE-SOURCE: I_AUX_A 0.15 + motor ~0.06 + chg_i_ceiling_a 1.0 = 1.21 A
    # against LIMIT_I_FC_MAX 1.4 A, a 14 % margin.  The hunt REDUCES the mean
    # charge current below the ceiling, so the margin can only widen.
    "allow_only": 0,
    "survive_to": {"t": EMS_MPPT_CRUISE_WINDOWS[-1][0], "states": {2}},   # 39.1
    "signals_require": [
        # 1. MPPT_DISABLE ASSERTED (pin LOW) throughout a braking window.  Two
        #    firmware paths hold it low there and they agree: charge_goal is 0 at
        #    the window edges (.ino:10007) and the regen branch drives it low
        #    inside (.ino:10034).  max_ticks 0 is therefore exact, not lenient.
        {"name": "mppt_asserted", "aux_bit": AUX_MPPT_DISABLE, "max_ticks": 0,
         "t_window": _MPPT_BRAKE_W,
         "label": "MPPT_DISABLE held LOW (inhibited) across the first braking "
                  "window — the regen path never presents the threshold"},
        # 2. ... and TOGGLED across the cruise-charge windows.  TWO bounds on one
        #    quantity, which is the whole assertion: a floor proves the pin was
        #    RELEASED at all (the firmware got the charger to ready), and a
        #    ceiling proves it did not simply STAY released — i.e. it hunted.
        #    Either bound alone is satisfiable by a run that disproves the point.
        {"name": "mppt_released", "aux_bit": AUX_MPPT_DISABLE,
         "min_ticks": _MPPT_TOGGLE_MIN_TICKS, "t_window": _MPPT_ALL_CRUISE_W,
         "label": "MPPT_DISABLE was RELEASED (pin HIGH) during cruise charging — "
                  "the firmware reached ag105IsReady()"},
        {"name": "mppt_not_stuck_high", "aux_bit": AUX_MPPT_DISABLE,
         "max_ticks": _MPPT_TOGGLE_MAX_TICKS, "t_window": _MPPT_ALL_CRUISE_W,
         "label": "... and did NOT stay released — the pin toggled, which is the "
                  "hunt signature (~1500 ticks; a stuck-high pin shows ~3000)"},
        # 3. Charging DID occur on the FC path despite the gate.
        #    ⚠️ THE FLOOR IS DERIVED FROM THE HUNT, NOT FROM THE CEILING.  At a
        #    ~40 ms period and ~50 % duty against AG105_TAU_S = 0.4 s, I_charge
        #    equilibrates near HALF the 1.0 A ceiling — roughly 0.5 A, which is
        #    exactly where a 0.5 floor would be knife-edged.  0.25 is half of the
        #    modelled equilibrium: clear of zero by a wide margin, and clear of
        #    the equilibrium by 2x.  A campaign that lands under it is reporting
        #    a FASTER hunt than modelled, which is a finding about the firmware's
        #    charger cadence — move this number only with that finding in hand.
        {"name": "charging_occurred", "column": "I_charge", "min_value": 0.25,
         "t_window": _MPPT_CRUISE_W,
         "label": "the FC path delivered charge current despite the threshold "
                  "gate (>= 0.25 A; ~half the modelled hunt equilibrium)"},
        # 4. THE LOAD-BEARING NEW BEHAVIOUR: the threshold gate actually BOUND.
        #    GENSTAT 001 "Low Power" is reachable from NO other path in this
        #    model, so this check is what separates "MPPT emulation is on" from
        #    "MPPT emulation did something".  50 ticks = 50 ms, a tenth of one
        #    hunt half-cycle budget across three windows.
        {"name": "low_power_seen", "column": "ag105_status",
         "value_mask": AG105_GENSTAT_MASK, "value_equals": AG105_ST_LOW_POWER,
         "min_ticks": 50, "t_window": _MPPT_ALL_CRUISE_W,
         "label": "the Ag105 reported GENSTAT 001 (Low Power) — the input-voltage "
                  "threshold gate BOUND, which no other path in this model can "
                  "produce"},
        # 5. ... and the tracking FLAGS followed the pin, in the specific pattern
        #    the threshold produces.
        #    ⚠️ DEVIATION FROM THE ORIGINAL SPEC, and the reason is causal: the
        #    pair MPPT_EN|PWR_TRACK (0x18) is NOT reachable in this scenario.
        #    PWR_TRACK is set only on the CHARGING branch with the pin HIGH — but
        #    the pin going HIGH is precisely what moves the model off that branch
        #    within one plant tick.  What the gate DOES produce is MPPT_EN set
        #    with PWR_TRACK CLEAR: tracking was released, and the module is
        #    refusing to track because the rail is under threshold.  That pattern
        #    is the honest observable and is asserted instead.
        {"name": "tracking_released_not_tracking", "column": "ag105_status",
         "value_mask": AG105_TRACK_MASK, "value_equals": AG105_FLAG_MPPT_EN,
         "min_ticks": 50, "t_window": _MPPT_ALL_CRUISE_W,
         "label": "MPPT_EN set with PWR_TRACK CLEAR — tracking released, and the "
                  "module refusing to track below the threshold"},
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
for _n, _e in FAULT_EXPECTATIONS.items():
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
            _bound_keys = ("min_ticks", "min_value", "strictly_decreases_by",
                           "max_ms", "fault_latch_bit", "any_of")
            if "max_ticks" in _sub and not any(_k in _sub for _k in _bound_keys):
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
                assert _companion or _sub.get("vacuity_note"), (
                    "FAULT_EXPECTATIONS[%r].signals_require[%r]: `max_ticks` is "
                    "its only assertion, and a blank or absent %s=%r column "
                    "satisfies it with zero matching ticks. Add a companion "
                    "spec on the same signal carrying a positive bound "
                    "(min_ticks/min_value/max_ms/...), or a `vacuity_note` "
                    "saying why the column cannot be blank in this run."
                    % (_n, _tag, _sig_id[0], _sig_id[1]))
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
                # coverage one: these two are 350 s each — ~11.7 min for the
                # pair against a ~34 min campaign — so they are opt-in. Same
                # skip-record mechanism as the two gates above, so the report
                # shows the gap instead of quietly shortening the plan.
                #
                # ORDERED AFTER the --pi-live gate deliberately: both scenarios
                # are EMS-driven, so under --pi-live they are skipped WHATEVER
                # --with-ftp75 says, and the honest reason is the pi-live one.
                # Reporting "pass --with-ftp75 to run both" there would name a
                # flag that could not make the run happen.
                plan.append({
                    "kind": "scenario", "name": name,
                    "mode": need if need in ("simple", "hifi") else args.electrical_pref,
                    "electrical_required": need,
                    "description": meta.get("description", ""),
                    "duration_s": 0.0, "csv": None, "events": None, "log": None,
                    "argv": None, "timeout_s": 0.0,
                    "skip_reason": (
                        "LONG-CYCLE: the EPA FTP-75 study segment runs %.0f s, "
                        "and the pair adds ~%.1f min to the campaign. Nothing "
                        "about the board or the link blocks it — pass "
                        "--with-ftp75 to run both."
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
                "prev_bit": None, "edge_t": None}

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
                        else:
                            m["ticks"] += cur
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


def warm_reset_count(csv_path, child):
    """Mid-run warm resets for one run: (dict, source).

    The dict carries "mid_run", "observed" and "times" (any of them None when
    that field is unavailable).  A None `mid_run` means UNMEASURED — an older
    simulator build, a child that died before finalizing its sidecar, or a run
    whose sidecar and stdout are both unusable.  Unmeasured must never render as
    zero: the whole point of the tripwire is that the damage it detects does not
    show up in the run's own outcome."""
    launched_at = None
    raw_launch = (child or {}).get("launched_at")
    if raw_launch:
        try:
            launched_at = datetime.datetime.fromisoformat(str(raw_launch))
        except (TypeError, ValueError):
            launched_at = None
    meta = read_run_meta(csv_path, launched_at)
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
    carried_note = ("" if not carried else
                    "; carried-in from the predecessor's settle latch: %s "
                    "(excused — observed only before t=%.1fs and cleared by the "
                    "grace-window warm reset)" % (fault_names(carried), grace_s))
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
#       the 16-byte observation frame carries no
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
                A("  - carried in from the predecessor's settle latch (seen only "
                  "before t=%.1fs, cleared by the fw v23 grace-window warm "
                  "reset): %s"
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
                        A("  - carried in from the predecessor's settle latch "
                          "(seen only before t=%.1fs, cleared by the fw v23 "
                          "grace-window warm reset): %s"
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
        with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": meta_now, "results": results_now}, fh, indent=2, default=str)
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
