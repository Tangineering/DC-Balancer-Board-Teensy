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
    SW_FC_BUS, SW_REGEN,
)
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
        # never drew anything. The `soc` column is the coulomb count itself, so a
        # monotone fall of at least 0.05 (5 % SoC) is direct evidence the endurance
        # walk happened. Budget at SOC_ENDURANCE_LOAD_A 2.2 A over the suite's ~870 s
        # of load: 1914 A*s / 18000 A*s = 0.106, so 0.05 is a floor with 2x margin
        # and survives a shortened --duration without becoming unachievable.
        "signals_require": [
            {"name": "soc_fell", "column": "soc", "strictly_decreases_by": 0.05,
             "label": "battery SoC walked down under the endurance load"},
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
        "source": "hil_replay_suite.py TP0178/TP0201 entries (0.15-0.185 V of "
                  "recorded margin, ~10 ms dwell vs the 20 ms latch) + "
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
             "label": "FC_BUS_ENABLE opened by the share setpoint latch and held "
                      "open until the perturbation"},
        ],
    },
    "scp-inrush": {
        # HIL_FINDINGS 'scp-inrush' recommends gating this scenario on the EVENTS
        # sidecar containing scp_cut rather than on fault flags, because the old
        # run produced ZERO fold/scp_cut events — MOT_PWR was already ON when the
        # load arrived, and the foldback branch exists only in the SOFT state.
        # The load now sits behind MOT_PWR from t = 0, so the P3 close ramps into
        # it while still in SOFT.
        #
        # NO fault is REQUIRED, but NOT for the reason first written here.
        #
        # THE ORIGINAL DERIVATION WAS WRONG IN PREMISE (corrected 2026-08-30c from
        # the measured campaign trace). It claimed the over-limit current exists
        # only inside the 250 us SCP blanking window, giving ~250 us / 72 ms per
        # retry cycle (~0.35 %) and "~1.75 expected hits" over the 500 ms
        # MOT_CONNECT_TIMEOUT_MS — i.e. a coin-flip. That is not what happens: the
        # over-limit current spans the WHOLE SOFT conduction interval, not just the
        # blanking window. Measured: I_fc carried 1.966 A (> the 1.4 A limit) for
        # ~0.95 ms, which is >= one 1 kHz sample period, so the firmware's
        # single-sample OC check is hit on the FIRST fold cycle. OC_FC is
        # NEAR-DETERMINISTIC, not a race — and the campaign observed exactly that,
        # with a single cut and no retries.
        #
        # The consequence for this table is unchanged, which is why the entry still
        # requires no fault: FAULT_MOT_HOTPLUG (.ino:8832-8834) remains the outcome
        # if the OC is ever missed, and both are correct firmware behaviour. What
        # DID change is the honest reading of the scenario — the sim mechanism fires
        # roughly 1 ms before the firmware protects itself, and that 1 ms is the
        # entire margin. Zero retry cycles are observable with firmware attached:
        # the State-99 teardown pulls MOT_PWR LOW ~10 ms after the fault, 54 ms
        # before the 64 ms re-arm, so retry-cadence coverage needs a firmware-free
        # hil_electrical bench, not this scenario.
        # See SCP_INRUSH_MOT_LOAD_A in hil_plant_sim.py for why an scp_cut cannot
        # be separated from an OC fault in this model.
        "source": "HIL_FINDINGS 'scp-inrush' recommendation 3 + "
                  "hil_electrical.py Rt1987._soft_operating_point()/SCP branch "
                  "(RT_SCP_BLANK_S 250 us, RT_SCP_RETRY_S 64 ms) + "
                  "hil_plant_sim.py SCP_INRUSH_MOT_LOAD_A for the 5.0 A derivation",
        "allow_only": FAULT_OC_FC | FAULT_MOT_HOTPLUG | FAULT_ERROR,
        # ⚠️ RE-VERIFIED 2026-08-30d against the TRCB-in-SOFT change, because that
        # change could in principle have stolen this scenario's event: a reverse
        # trip removes the switch from SOFT, and fold/SCP is a SOFT-only mechanism,
        # so a reverse trip before the fold would mean no scp_cut ever fires.
        # A headless reproduction of the SHIPPED sequence — real Plant, real
        # ElectricalSim at this scenario's own vesc_cap_f, real apply_scenario(),
        # and the actuator word stepped through the firmware's own bring-up gates
        # (busBringupTick(), .ino:8723-8845) evaluated against the plant's rails —
        # settles it. AT THE P3 CLOSE THE MOTOR NODE IS DARK: the 5 A load holds it
        # at 0 V, so the differential is
        #     v_in 15.79 V, v_out 0.00 -> 0.67 V, dv = +13.89 V
        # i.e. massively FORWARD. There is no reverse condition to trip, and the
        # measured outcome is exactly the expected one: a single MOT_PWR scp_cut
        # with i_cut = 6.2852 A, which is 0.07 % from the campaign's on-hardware
        # 6.290 A and comfortably inside the band below.
        # A reverse trip during soft-start needs a PRE-CHARGED node (the comm-loss
        # warm-recovery shape), which P3 never presents — the two cases are
        # structurally different and do not compete.
        # (One NEW reverse_block does appear in a hi-fi run, on BT_BUS at ~62 ms,
        # dv = -50.4 mV: the diode-OR blocking whichever boost is momentarily lower,
        # which is the RT1987's advertised function. Verified INERT — cut counts and
        # both bring-up current pins are byte-identical with the branch disabled.)
        #
        # TIGHTENED 2026-08-30c (campaign follow-up (1)). "at least one scp_cut"
        # was too loose to be evidence: a 0.3 A cut would have passed it, and so
        # would a run that cut repeatedly for the wrong reason. All three facts
        # below were measured on hardware in campaign 20260830_203006 and are
        # pinned so a drift in any of them is visible:
        #   count == 1        one cut, at t = 0.600000. More would mean the retry
        #                     cadence became reachable (it is not, with firmware
        #                     attached — the State-99 teardown opens MOT_PWR 54 ms
        #                     before the 64 ms re-arm), so >1 is a real change.
        #   over_absmax == 0  no ring above the 20 V abs-max: this scenario must
        #                     exercise the foldback WITHOUT producing the Death-5
        #                     boost-kill signature. The two 17.72 V rings observed
        #                     are the teardown's own EN-low openings at ~0.1 A.
        #   i_cut 5.0-8.0 A   the fold plausibility band. Measured 6.290 A =
        #                     5.0 A load + ~1.11 A CSS ramp current + blank-window
        #                     lag growth, against a fold limit of 5.36 A at
        #                     dv ~ 15.15 V. The band's floor is the fold limit's own
        #                     lower reach and its ceiling is RT_I_FOLD_HIGH, so a
        #                     cut outside it is not a foldback event at all.
        "events_require": [
            {"kind": "scp_cut", "count": 1,
             "field": "i_cut", "min_value": 5.0, "max_value": 8.0},
        ],
        "events_forbid_over_absmax": True,
    },
}
# Everything not listed is expected fault-free (post-grace); a fault there is a
# finding: steady, step-load, bringup, ems-drive-cycle, drive.

# L3 — LOAD-TIME CONSISTENCY, asserted rather than trusted.
# Both `not_before_s` and `survive_to.t` are compared against times taken from the
# POST-GRACE window, so a value at or below WARM_RESET_GRACE_S is not a stricter
# check — it is a VACUOUS one. `not_before_s` would be trivially satisfied (nothing
# post-grace can precede the grace bound) and `survive_to` would probe a moment the
# fault scan never reaches, silently reporting "no observation frame at or after
# t=X". Neither failure has a symptom at the point of use, so it is caught here, at
# import, where the table is written.
for _n, _e in FAULT_EXPECTATIONS.items():
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
                # L9(c): at the DEFAULT --soc0 0.7 / 5 Ah / this scenario's stock
                # 120 s duration, the run cannot reach LIMIT_V_BATT_MIN at all:
                # ~115 s of the +3.0 A load step is ~345 A*s against an 18000 A*s
                # (5 Ah) pack, i.e. ~1.9% SOC -- nowhere near the UV floor.  Even at
                # --soc0 0.15 alone, 120 s only reaches ~13% SOC (V_batt ~6.9 V,
                # still above the 6.2 V limit per the BatterySource OCV/Rs(SOC)
                # curve).  Reaching LIMIT_V_BATT_MIN (~6.2 V) needs SOC to fall to
                # roughly 0.05 (where the fitted model's Rs(SOC) knee below 15%
                # steepens the sag enough to cross 6.2 V), i.e. a further ~0.10 of
                # SOC = 1800 A*s at 3 A = 600 s beyond the ramp-up -- so this entry
                # is bumped to --soc0 0.15 and a long duration.
                #
                # RE-DERIVED 2026-08-30 (review M4).  The endurance load was reduced
                # 3.0 -> SOC_ENDURANCE_LOAD_A 2.2 A because at 3.0 A the surviving
                # BT channel carried 3.15 A against LIMIT_I_BT_MAX 3.0 A -- over the
                # limit outright, for 645 s, with nobody having written the number
                # down (the FC budgets elsewhere had this discipline; this one did
                # not).  The DURATION is extended in lockstep so the delivered
                # charge, and therefore the depletion depth, is preserved:
                #     old:  645 s x 3.0 A = 1935 A*s
                #     new:  870 s x 2.2 A = 1914 A*s   (-1.1%)
                # 880 s total = 10 s before the load ramp + 870 s of load, landing
                # at ~4.4% SOC, still past the ~5% crossing point.
                # COST: +230 s (~3.8 min) of suite wall time.  Paid deliberately --
                # the alternative was keeping the run short and quietly abandoning
                # the endurance objective the scenario exists for.
                dur = 880.0
                argv = [
                    "--scenario", name,
                    "--electrical", mode,
                    "--duration", "%g" % dur,
                    "--soc0", "0.15",
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
    (mainState on the first observed row at or after it)."""
    m = {"csv": csv_path, "rows": 0, "n_obs": 0, "final_fault_flags": None,
         "fault_bits_seen": 0, "fault_bits_post_grace": 0,
         "fault_first_t": {}, "n_obs_post_grace": 0, "last_obs_t": None,
         "grace_s": grace_s, "survive_to_t": survive_to_t,
         "fault_bits_before_survive": 0, "state_at_survive": None,
         "final_state": None, "duration_s": None,
         "substep_hz_min": None, "substep_hz_mean": None, "error": None}
    if not os.path.isfile(csv_path):
        m["error"] = "CSV not written"
        return m
    subs = []
    t_first = t_last = None
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
    except OSError as exc:
        m["error"] = str(exc)
        return m
    if t_first is not None and t_last is not None:
        m["duration_s"] = t_last - t_first
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
#   {"column": "soc", "strictly_decreases_by": X}  last - first <= -X
#
# Optional on any spec: "t_window": (t0, t1) — restrict to that SIM-time window
# (t1 may be None for "to the end"), and "label": human text for the report.
# Every spec is judged only on rows at or after the grace bound, for the same
# reason the fault checks are: the pre-grace window belongs to the previous run.
# ─────────────────────────────────────────────────────────────────────────────

def scan_signals(csv_path, specs, grace_s=WARM_RESET_GRACE_S):
    """One pass over the CSV collecting exactly what `specs` needs.

    Returns a list parallel to `specs` of measurement dicts; judge_signals() turns
    those into checks.  Kept separate from analyze_scenario_csv() so a scenario
    with no signals_require pays nothing."""
    out = [{"ticks": 0, "peak": None, "first": None, "last": None, "rows": 0}
           for _ in specs]
    if not specs or not os.path.isfile(csv_path):
        return out
    try:
        with open(csv_path, newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    t = float(row.get("t") or "nan")
                except ValueError:
                    continue
                if t != t or t < grace_s:
                    continue
                for spec, m in zip(specs, out):
                    w = spec.get("t_window")
                    if w and (t < w[0] or (w[1] is not None and t > w[1])):
                        continue
                    m["rows"] += 1
                    if "switch_bit" in spec:
                        cell = (row.get("switch") or "").strip()
                        if not cell:
                            continue
                        try:
                            if int(cell, 0) & int(spec["switch_bit"]):
                                m["ticks"] += 1
                        except ValueError:
                            pass
                        continue
                    cell = (row.get(spec.get("column", "")) or "").strip()
                    if not cell:
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
        for m in out:
            m["error"] = str(exc)
    return out


def judge_signals(specs, measured, why):
    """Turn scan_signals() output into checks.  Pure over its inputs."""
    checks = []
    for spec, m in zip(specs, measured):
        label = spec.get("label") or "signal"
        name = "signal_%s" % spec.get("name", label.split()[0].lower())
        win = ("" if not spec.get("t_window") else
               " in t=[%s, %s]s" % (spec["t_window"][0],
                                    spec["t_window"][1]
                                    if spec["t_window"][1] is not None else "end"))
        if m.get("error"):
            checks.append({"name": name, "passed": False,
                           "detail": "could not read the CSV: %s" % m["error"]})
            continue
        if not m["rows"]:
            checks.append({
                "name": name, "passed": False,
                "detail": ("no observed rows%s to judge '%s' — the window the "
                           "objective lives in was never reached (%s)"
                           % (win, label, why))})
            continue
        if "min_ticks" in spec:
            ok = m["ticks"] >= int(spec["min_ticks"])
            checks.append({"name": name, "passed": ok,
                           "detail": ("%s: bit set on %d tick(s)%s, need >= %d (%s)"
                                      % (label, m["ticks"], win,
                                         int(spec["min_ticks"]), why))})
        elif "max_ticks" in spec:
            ok = m["ticks"] <= int(spec["max_ticks"])
            checks.append({"name": name, "passed": ok,
                           "detail": ("%s: bit set on %d tick(s)%s, need <= %d (%s)"
                                      % (label, m["ticks"], win,
                                         int(spec["max_ticks"]), why))})
        elif "min_value" in spec:
            peak = m["peak"]
            ok = peak is not None and peak >= float(spec["min_value"])
            checks.append({"name": name, "passed": ok,
                           "detail": ("%s: peak %s%s, need >= %g (%s)"
                                      % (label,
                                         "unmeasured" if peak is None else "%.4f" % peak,
                                         win, float(spec["min_value"]), why))})
        elif "strictly_decreases_by" in spec:
            need = float(spec["strictly_decreases_by"])
            have = (None if m["first"] is None or m["last"] is None
                    else m["first"] - m["last"])
            ok = have is not None and have >= need
            checks.append({"name": name, "passed": ok,
                           "detail": ("%s: fell by %s%s, need >= %g (%s)"
                                      % (label,
                                         "unmeasured" if have is None else "%.6f" % have,
                                         win, need, why))})
        else:
            checks.append({"name": name, "passed": False,
                           "detail": "suite error: signal spec %r declares no "
                                     "assertion kind" % (spec,)})
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
        return ({"name": "warm_reset_tripwire", "passed": True,
                 "detail": "no mid-run warm reset (%s) — the board never left "
                           "State 99 during the run" % source},
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


def analyze_events(path):
    """Event counts by kind from a hi-fi .events.jsonl sidecar."""
    out = {"path": path, "total": 0, "kinds": {}, "over_absmax": 0,
           "worst_ring_v": None, "worst_over_absmax_ring_v": None,
           "field_values": {}, "read_error": None}
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
                               "caller did not run scan_signals()" % len(sig_specs))})
            else:
                checks.extend(judge_signals(sig_specs, signals, why))

        # events_require accepts EITHER a bare kind string (at least one such event)
        # or a dict pinning count and/or a numeric field's plausibility band. The
        # bare form is kept because most future entries will want nothing more.
        for req in expect.get("events_require", ()):
            spec = {"kind": req} if isinstance(req, str) else dict(req)
            kind = spec["kind"]
            n = events.get("kinds", {}).get(kind, 0)
            vals = (events.get("field_values", {}).get(kind, {})
                    .get(spec.get("field"), []))
            problems = []
            if "count" in spec:
                if n != int(spec["count"]):
                    problems.append("count %d, expected exactly %d"
                                    % (n, int(spec["count"])))
            elif n == 0:
                problems.append("no such event")
            if spec.get("field") is not None:
                if not vals:
                    problems.append("no '%s' field on any '%s' event to check"
                                    % (spec["field"], kind))
                else:
                    lo, hi = spec.get("min_value"), spec.get("max_value")
                    bad = [v for v in vals
                           if (lo is not None and v < lo)
                           or (hi is not None and v > hi)]
                    if bad:
                        problems.append(
                            "%s out of the [%s, %s] plausibility band: %s"
                            % (spec["field"],
                               "%g" % lo if lo is not None else "-inf",
                               "%g" % hi if hi is not None else "+inf",
                               ", ".join("%.3f" % v for v in bad)))
            observed = ("%d '%s' event(s)" % (n, kind)) + (
                "; %s = %s" % (spec["field"], ", ".join("%.3f" % v for v in vals))
                if vals else "")
            checks.append({
                "name": "events_require_%s" % kind, "passed": not problems,
                "detail": (observed if not problems else
                           "%s — %s (%s)" % (observed, "; ".join(problems), why))})

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
        #       (.ino:1193), and the 16-byte observation frame carries no
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
        summary = child.get("summary") or {}
        tx = summary.get("tx_frames")
        send_errors = summary.get("send_errors")
        expected_tx = (HIL_DEFAULT_RATE_HZ * duration_s) if duration_s else None
        stream_continuous = (
            pi_live and exactly_pi_timeout
            and tx is not None and send_errors is not None
            and expected_tx is not None
            and tx >= 0.98 * expected_tx
            and send_errors == 0
        )
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
                              "(tx=%d/%s frames, %d send errors) — the operator's "
                              "Pi owns the command cadence. Residual: the "
                              "observation frame carries no error_code, so "
                              "PI_TIMEOUT vs the aliased HIL_STALE is inferred by "
                              "elimination, not read directly.)"
                              % (post, tx, ("%.0f" % expected_tx) if expected_tx
                                 else "?", send_errors))
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
        A("**What this half is:** a BRING-UP + FAULT-DECISION regression harness.")
        A("Replay mode constructs no commander, so no run reaches State 2 and the")
        A("commanded current is 0 A throughout — the current-shape checks assert only")
        A("that the firmware does not drive on an uncommanded stimulus. Each run is")
        A("preceded by a %.1f s synthetic bring-up preamble of healthy nominal rails," % REPLAY_PREAMBLE_S)
        A("so times below are SIM-relative and log time = sim time − %.1f s." % REPLAY_PREAMBLE_S)
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
    # run all 26 replays with a live Pi fighting the replayed trajectory).
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
            res = {"kind": "replay", "name": item["name"], "mode": item["mode"],
                   "cmd_mode": _suite_mode(args),
                   "description": item["description"], "duration_s": item["duration_s"],
                   "passed": passed, "checks": checks, "notes": ev.get("notes", []),
                   "metrics": {}, "events": {}, "child": child,
                   "csv": item["csv"], "events_path": None, "log_path": item["log"],
                   "n_checks_vacuous": ev.get("n_checks_vacuous"),
                   "n_checks_substantive": ev.get("n_checks_substantive"),
                   # Item 5: "%d/%d checks passed" counts vacuous checks alongside
                   # real ones. Say how many carried evidence, so a green replay
                   # entry cannot read stronger than it is.
                   "key_metrics": ("%d/%d checks passed" % (npass, len(checks)))
                                  + ("" if not ev.get("n_checks_vacuous") else
                                     " (%d substantive, %d vacuous — no commander)"
                                     % (ev.get("n_checks_substantive") or 0,
                                        ev["n_checks_vacuous"]))}
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
            ("warm resets %s" % ("?" if wr_counts.get("mid_run") is None
                                 else wr_counts["mid_run"])))

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
