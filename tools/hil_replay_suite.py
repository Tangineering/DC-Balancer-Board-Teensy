#!/usr/bin/env python3
"""
hil_replay_suite.py — the replay-based scenario class for the Teensy HIL rig.

A curated set of REAL bench logs (logs/*.BLG) is replayed at the firmware through
`tools/hil_plant_sim.py --replay`, and the resulting per-tick CSV is evaluated
here against declarative, firmware-version-aware checks.

WHAT THIS HALF ACTUALLY IS (relabelled 2026-08-30, HIL_FINDINGS "Replay half"):
a **bring-up + fault-decision regression harness**, not a control-response suite.
Replay mode constructs NO commander, so no replayed run ever reaches State 2: the
board brings up, sits in Idle, and `current` is 0.000 A for the whole run.  Every
current-shape check below is therefore vacuously true on a healthy board — they
are retained as "no SPURIOUS command" assertions (the firmware must not drive on
an injected stimulus it was never commanded to follow), and they are annotated as
such in the report, not advertised as controller coverage.  What the half really
tests is: does the fw v22+ staged bring-up complete on this stimulus, and does the
fault machinery make the right LATCH decision on it.

Two evaluation MODES (see docs/HIL_REPLAY_LOGS.md for the full policy):

  conformance — the log was recorded on firmware whose control semantics match
                the current flashed target (fw v21 = the fw v18 control law +
                the v19 share handoff slew + v20/v21 observability/HIL), or the
                delta is functionally unimportant for the property under test.
                The firmware's LIVE response is expected to be well-behaved on
                the recorded stimulus (no faults, bounded command, no windup).
                For pre-v18 logs, "conformance" means STABLE AND FAULT-FREE, not
                a trace match — the wheel geometry and the control law both
                changed (see FW_DELTA_NOTES).

  deviation   — the log was recorded on older firmware with a KNOWN defect.  The
                modern firmware must NOT reproduce the recorded failure mode.

⚠️ Replay is OPEN LOOP (docs/HIL_MODE.md "Fidelity caveat"): the plant integrator
is bypassed, so the firmware's commands do not influence the replayed trajectory,
and the encoder/estimator path is bypassed entirely (v_actual is INJECTED).  Every
check below is therefore a check on the firmware's RESPONSE to a fixed stimulus.

Firmware-sourced constants used by the checks are cited at their definitions.

Standalone use (running the board is the wrapper's job, not this module's):

    python3 tools/hil_replay_suite.py --list
    python3 tools/hil_replay_suite.py --evaluate ML0151 hil_replay_ML0151.csv

Stdlib only (argparse, csv, json, os).
"""

import argparse
import csv
import json
import os
import sys

# Suite entry "path" values are repo-root-relative ("logs/XXXX.BLG").  Resolve
# them against the repo root derived from this file's location, NOT the CWD —
# invoking the module from inside tools/ used to report all 26 logs missing.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The two host-side timing constants this module has to agree with, imported from
# the simulator rather than duplicated (there must be ONE definition of each, or
# the checks here and the suite's drift apart silently).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hil_plant_sim import (                                        # noqa: E402
    REPLAY_PREAMBLE_S, WARM_RESET_GRACE_S,
)

# M7 — LOAD-BEARING ORDERING, asserted at import rather than trusted.
# Fault checks exclude observations before WARM_RESET_GRACE_S (the previous run's
# inherited settle latch).  If the preamble were SHORTER than that bound, the first
# (WARM_RESET_GRACE_S - REPLAY_PREAMBLE_S) seconds of every RECORDED trajectory
# would fall inside the excluded window and any fault the log's own opening samples
# provoked would be silently dropped — a false PASS with no symptom anywhere.
# Shortening the preamble without re-deriving the grace bound is exactly the change
# this catches.
assert REPLAY_PREAMBLE_S >= WARM_RESET_GRACE_S, (
    "REPLAY_PREAMBLE_S (%.3f s) must be >= WARM_RESET_GRACE_S (%.3f s): the fault "
    "checks exclude everything before the grace bound, so a shorter preamble would "
    "put the start of every recorded trajectory inside the excluded window and drop "
    "real early faults without a symptom."
    % (REPLAY_PREAMBLE_S, WARM_RESET_GRACE_S))

# ─────────────────────────────────────────────────────────────────────────────
# Firmware-sourced constants.  VERIFIED against the cited sources — do not
# change one of these without re-reading the citation.
# ─────────────────────────────────────────────────────────────────────────────

# teensy_controller/teensy_controller.ino:2048
#   constexpr float MOTOR_I_CMD_MAX = 12.0f;
# (line 2052 static_asserts it equals DRIVE_CTRL_I_MAX / -DRIVE_CTRL_I_MIN, so
#  the drive controller's clamp and the command chokepoint are the same number.)
MOTOR_I_CMD_MAX_A = 12.0

# Tolerance on the post-clamp observation-frame `current` field: the firmware
# clamps in float32 and the CSV prints 4 decimals, so an exact-rail sample can
# read 12.0000 ± ~1e-4.  Anything beyond this is a real clamp escape.
I_CMD_EPS_A = 0.01

# "On the rail" for episode detection.  Deliberately just inside the clamp so a
# genuine saturation sample is caught even after float32 + %.4f rounding.
RAIL_LEVEL_A = 11.9

# teensy_controller/teensy_controller.ino:1155
#   #define FAULT_UV_BUS 0x0100   // V_bus undervoltage: source-feed loss / bus collapse
FAULT_UV_BUS = 0x0100
# teensy_controller/teensy_controller.ino:1149-1166 (full bitmask block)
FAULT_OC_FC = 0x0001
FAULT_UV_BATT = 0x0002
FAULT_OV_BUS = 0x0004
FAULT_SWITCH_CONFLICT = 0x0008
FAULT_PI_TIMEOUT = 0x0010          # ALIASED by FAULT_HIL_LINK (fw v21, .ino:1168)
FAULT_OV_BATT = 0x0020
FAULT_UV_FC = 0x0040
FAULT_OC_BT = 0x0080
FAULT_OV_RGN = 0x0200
FAULT_OV_CHG = 0x0400
FAULT_I2C_CHARGER = 0x0800
FAULT_CHARGER_STAT = 0x1000
FAULT_INIT_FAIL = 0x2000
FAULT_MOT_HOTPLUG = 0x4000
FAULT_ERROR = 0x8000

FAULT_NAMES = {
    FAULT_OC_FC: "OC_FC", FAULT_UV_BATT: "UV_BATT", FAULT_OV_BUS: "OV_BUS",
    FAULT_SWITCH_CONFLICT: "SWITCH_CONFLICT", FAULT_PI_TIMEOUT: "PI_TIMEOUT/HIL_LINK",
    FAULT_OV_BATT: "OV_BATT", FAULT_UV_FC: "UV_FC", FAULT_OC_BT: "OC_BT",
    FAULT_UV_BUS: "UV_BUS", FAULT_OV_RGN: "OV_RGN", FAULT_OV_CHG: "OV_CHG",
    FAULT_I2C_CHARGER: "I2C_CHARGER", FAULT_CHARGER_STAT: "CHARGER_STAT",
    FAULT_INIT_FAIL: "INIT_FAIL", FAULT_MOT_HOTPLUG: "MOT_HOTPLUG",
    FAULT_ERROR: "ERROR(latched State 99)",
}

# teensy_controller/teensy_controller.ino:1258
#   #define LIMIT_V_BUS_MIN  12.0f   // V — minimum VBUS while the bus is armed
LIMIT_V_BUS_MIN_V = 12.0
# teensy_controller/teensy_controller.ino:1284
#   #define UV_BUS_DWELL_LATCH_MS 20.0f  // ms of accumulated net under-dwell → latch
UV_BUS_DWELL_LATCH_MS = 20.0
# teensy_controller/teensy_controller.ino:1285, :1288 — the leaky-integrator shape.
# The UV filter is NOT a plain window: dwell accumulates under the limit and leaks
# back at UV_BUS_DWELL_LEAK × dt above it, per-tick dt capped at
# UV_BUS_DWELL_DT_CAP_MS.  `fault_latched` reproduces this to decide whether the
# recorded stimulus SHOULD have latched, so a repetitive dropout (the TP0053
# class, which evaded the old window filter) is scored correctly.
UV_BUS_DWELL_LEAK = 0.05
UV_BUS_DWELL_DT_CAP_MS = 5.0

# teensy_controller/teensy_controller.ino:1300
#   #define LIMIT_I_FC_MAX   1.4f   // A (BUS-SIDE) — H-20 2.6 A referred through the boost
# OPERATOR RULING (a), 2026-08-30: this value STAYS at 1.4 A. It is already
# slightly above the H-20 fuel cell's theoretical maximum. Recorded bench traces
# that exceed it did so only because DC bench supplies stood in for the fuel cell,
# and BENCH_TEST compiles the OC check out — so an OC_FC latch when those traces
# are replayed at a production build is CORRECT hardware replication, not a
# regression. Four suite entries are classified on exactly that basis.
LIMIT_I_FC_MAX_A = 1.4

# teensy_controller/teensy_controller.ino:1363
#   #define V_BUS_CHARGED_THRESH (V_BUS_NOMINAL - 2.5f)   // 16.0 → 13.5 V
# The UV fault is ARMED BY THE BUS, not by a state: the injected V_bus must have
# reached this before an under-limit dwell can latch anything.
V_BUS_CHARGED_THRESH_V = 13.5

# ── Check thresholds (suite policy, not firmware) ────────────────────────────
# A "sustained rail" long enough to be a windup/limit-cycle symptom rather than
# a legitimate large-signal transient.  1.0 s is ~17 crossover periods at the
# fw v18 17.25 rad/s design crossover.
SUSTAINED_RAIL_S = 1.0
# Rail-to-rail sign alternations per second above which the command is called a
# limit cycle.  The ML0137 boxcar defect ran 2.3–2.6 Hz, i.e. ~5 alternations/s;
# 2.0/s sits below that and above any legitimate large-signal manoeuvre rate.
LIMIT_CYCLE_ALT_PER_S = 2.0
# `returns_off_rail`: after a rail episode ENDS, the command must fall below this
# level within this time.  A controller that stays pinned is winding up.
OFF_RAIL_LEVEL_A = 10.0
OFF_RAIL_WITHIN_S = 1.0
# `near_zero_current`: the V_SP_ZERO_THRESH-class expectation — with no velocity
# setpoint commanded over the HIL link, the firmware must not be driving.
NEAR_ZERO_I_A = 0.5

# ── Grace window ────────────────────────────────────────────────────────────
# Every fault check below judges observations at t >= this bound only.  A replay
# CSV carries the SAME inherited settle latch every scenario CSV does: from fw v23
# the board warm-resets out of the previous run's ERR_HIL_STALE latch at t ~= 0.5 s,
# so a run that had nothing to do with it opens showing 0x8010 (or 0x8011 / 0xA010
# when its predecessor latched something of its own).  19 of the 26 replays in the
# first fw v23 suite pass FAILed on nothing but that.  Value imported from
# hil_plant_sim (WARM_RESET_GRACE_S) so this and run_hil_suite.py cannot diverge.
#
# Self-guarding, and worth stating: this excludes an observation WINDOW, never a
# bit value.  A board that stays latched keeps reporting its flags after the bound
# and still fails.
REPLAY_GRACE_S = WARM_RESET_GRACE_S

# ── Bring-up gate ───────────────────────────────────────────────────────────
# Before any substantive check runs, the board must have REACHED Idle (mainState
# 1).  Without this, a board that never brought up fails every check for the same
# single reason and the report reads as N independent findings instead of one.
# Budget: warm-reset recovery at ~0.50 s (HIL_RECOVER_DEBOUNCE_MS) + ~0.12 s of
# staged bring-up = ~0.62 s measured (HIL_FINDINGS "comm-loss"/"bringup"), and the
# synthetic preamble (REPLAY_PREAMBLE_S = 2.5 s) holds healthy rails over all of
# it.  3.5 s is that plus ~1 s of margin, and still well inside the shortest log
# in the suite (TP0053, ~5 s).  An entry whose POINT is that bring-up fails sets
# `skip_bringup_gate`.
BRINGUP_DEADLINE_S = 3.5
BRINGUP_STATE_IDLE = 1

# ── Time base ───────────────────────────────────────────────────────────────
# All times in this module — check details, thresholds, the constants above — are
# SIM-relative, i.e. the `t` column of the CSV verbatim.  The recorded log starts
# entry_preamble_s(entry) seconds into that axis, so
#     log time = sim time - entry_preamble_s(entry)
# and a CSV row with replay_rec == -1 is a preamble row with no source record.
# No check currently takes a log-relative time window; a future one MUST convert
# explicitly rather than assume the two axes coincide.
#
# The bound is PER ENTRY, not global: an entry with `skip_preamble` replays raw, so
# its preamble bound is 0.0 and its two axes DO coincide.  Everything that needs to
# separate "synthetic preamble" from "recorded stimulus" — the stimulus guards (M5)
# and the rate-based checks (M6) — resolves it through this one function.


def entry_preamble_s(entry):
    """Seconds of synthetic bring-up preamble prepended to THIS entry's replay.

    0.0 for an entry carrying `skip_preamble` (which also passes
    --replay-no-preamble to the simulator, see build_sim_argv)."""
    return 0.0 if (entry or {}).get("skip_preamble") else REPLAY_PREAMBLE_S

# ─────────────────────────────────────────────────────────────────────────────
# Firmware-version deltas that matter when reading a replay result.
# ─────────────────────────────────────────────────────────────────────────────
FW_DELTA_NOTES = {
    None: "pre-versioning (BLG v1, fw 0): earliest bring-up firmware — bus-collapse "
          "stimulus only; nothing about its control law is comparable.",
    0:    "pre-versioning bring-up firmware; bus-collapse stimulus only.",
    3:    "fw v3: pre-UV-rework; bus collapses did not latch any fault at all.",
    4:    "fw v4: UV_BUS window filter (evaded by duty cycle) — replaced by the "
          "fw v5 leaky dwell integrator.",
    5:    "fw v5: UV_BUS dwell filter introduced; still the old motor PI, old wheel.",
    11:   "fw v11: motor PI + BOXCAR wheel-speed estimator — the 2.3–2.6 Hz "
          "rail-to-rail limit cycle lives here.",
    12:   "fw v12: edge-period estimator, first re-synthesis; blind-hold and "
          "v_sp=0 relay defects still present.",
    13:   "fw v13: adaptive period filter (T/2 basin) + V_SP_ZERO_THRESH cutoff.",
    14:   "fw v14: K_F force-axis correction — coefficients only; 120-slot wheel, "
          "pre-Youla-v18 saturated-mode behaviour.",
    16:   "fw v16: BLG v6 encoder diagnostics; x2 rounding basin still live; "
          "120-slot wheel and the pre-v18 anti-windup form.",
    17:   "fw v17: fractional-pitch ledger + TOCTOU reset fix; still the 120-slot "
          "wheel and the pre-v18 anti-windup form.",
    18:   "fw v18: 90-slot wheel + general-Hanus anti-windup + re-synthesis — the "
          "CONTROL LAW currently flashed. Directly comparable to fw v21.",
    19:   "fw v19: fw v18 law plus the share handoff slew; drive channel unchanged.",
    20:   "fw v20: observability only (BLG v7 encoder counters/phase/duty).",
    21:   "fw v21: HIL mode; no control-semantics change vs v18/v19.",
}

# The firmware version currently flashed / targeted by this suite.
TARGET_FW_VERSION = 21
# Logs at or above this fw version share the current control law AND wheel.
COMPARABLE_FW_MIN = 18

# ─────────────────────────────────────────────────────────────────────────────
# The suite.
# ─────────────────────────────────────────────────────────────────────────────
# ── The OC_FC reclassification (2026-08-30, operator ruling (a)) ────────────
# Four entries moved conformance -> deviation this round.  They were classified
# "clean" from their BENCH behaviour, but they were recorded with DC bench
# supplies standing in for the H-20 fuel cell AND with BENCH_TEST compiling the OC
# check out, so their recorded I_fc routinely exceeded LIMIT_I_FC_MAX with nothing
# on the board to notice.  Replayed at a production (OC-live) build, an OC_FC latch
# is CORRECT hardware replication — the operator's ruling is explicit that the
# 1.4 A limit stays, being already slightly above the H-20's theoretical maximum.
# Scoring them as "must not fault" asserted the opposite of the hardware.
# Each entry carries an OC stimulus guard (require_stimulus): if the injected I_fc
# no longer crosses 1.4 A, the entry is reported INCONCLUSIVE rather than passing,
# the same discipline as the UV trio's.
# ── The UV pair's injected-I_fc clamp (H1, 2026-08-30) ─────────────────────
# Both UV-pair logs cross LIMIT_I_FC_MAX 1.4 A BEFORE their bus collapse accumulates
# the 20 ms of dwell the UV filter needs.  Measured (log time): TP0010 I_fc > 1.4 A
# at 4.770 s vs UV qualifying at 4.797 s; TP0053 3.929 s vs 4.462 s.  Replayed raw at
# a production build the board therefore latches OC_FC first, and State 99 FREEZES
# fault_flags — the UV bit can never be set afterwards, so the UV-latch regression
# these two logs exist for is destroyed by a fault that is itself correct.
#
# The clamp is the resolution, and it is honest under operator ruling (a): those
# currents came from a DC BENCH SUPPLY standing in for the H-20, which could never
# source them.  Clamping the injected FC channel to 1.3 A (7 % under the limit)
# removes a stimulus the real hardware could not produce, and delivers the bus
# collapse the entries were kept for.  It is DECLARED at every scoring site — the
# simulator banner, the entry note, this table and the ledger — because it is a
# deliberate modification of a recorded trajectory: nothing about FC current may be
# concluded from these two runs.
#
# Post-clamp verification (both logs): the UV dwell still qualifies (the clamp
# touches only I_fc, never V_bus, and _uv_stimulus_qualifies() reads V_bus alone),
# and no sample can reach 1.4 A, so OC_FC is unreachable by construction.
UV_PAIR_I_FC_CLAMP_A = 1.3
# Formatted with (log_name, t_oc_s, t_uv_s); the clamp value is substituted here so
# an entry cannot quote a number the plumbing does not use.
UV_PAIR_CLAMP_WHY = (
    " *** INJECTED I_fc CLAMPED to " + ("%.1f" % UV_PAIR_I_FC_CLAMP_A) + " A *** "
    "(H1, 2026-08-30): raw, %s's recorded I_fc crosses LIMIT_I_FC_MAX at log "
    "t=%.3fs while the UV dwell does not qualify until t=%.3fs, so the board latches "
    "OC_FC first and State 99 freezes fault_flags — UV could never be set and this "
    "entry's whole purpose was lost. The recorded current came from a DC bench "
    "supply the real H-20 could never source (operator ruling (a)), so the clamp "
    "removes an unphysical stimulus rather than excusing the firmware. NO conclusion "
    "about FC current may be drawn from this run.")

OC_FC_RECLASS_WHY = (
    "RECLASSIFIED conformance -> deviation (2026-08-30, operator ruling (a), "
    "HIL_FINDINGS 'Replay half' Class B): %s's recorded I_fc peaks at %.2f A, above "
    "LIMIT_I_FC_MAX 1.4 A. The bench run did not fault because a DC supply replaced "
    "the fuel cell and BENCH_TEST compiles FAULT_OC_FC out; a production build "
    "replicating this hardware MUST latch it. The deviation asserted here is "
    "exactly that: modern firmware catches what the recording never could.")

# Each entry:
#   log            short log name (matches the .BLG basename)
#   path           repo-relative path to the .BLG
#   mode           "conformance" | "deviation"
#   fw_version     BLG header fw_version (offset 18; None for BLG v1 pre-versioning)
#   blg_version    BLG record format version (header byte 4)
#   classification one-line "what this run is"
#   why            why it is in the suite
#   provisional    True = selection not yet confirmed against a full analysis pass
#   checks         list of declarative check specs (see CHECK_KINDS)
REPLAY_SUITE = [
    # ── CONFORMANCE — current wheel + control law (fw v18/v19) ───────────────
    {
        "log": "ML0203", "path": "logs/ML0203.BLG", "mode": "deviation",
        "fw_version": 18, "blg_version": 6,
        "classification": "'V' velocity run on the 90-slot wheel whose recorded "
                          "I_fc peaks at 2.11 A — above LIMIT_I_FC_MAX",
        "why": OC_FC_RECLASS_WHY % ("ML0203", 2.11),
        "provisional": False,
        "checks": [
            {"kind": "fault_latched", "name": "oc_fc_latched",
             "bit": FAULT_OC_FC, "require_stimulus": True},
            {"kind": "bounded_current", "name": "bounded_current"},
        ],
    },
    {
        "log": "YP0196", "path": "logs/YP0196.BLG", "mode": "conformance",
        "fw_version": 18, "blg_version": 6,
        "classification": "'Y' combined drive-cycle + power-share profile",
        "why": "Exercises both loops' stimulus together on the current law.",
        "provisional": False,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "WP0197", "path": "logs/WP0197.BLG", "mode": "conformance",
        "fw_version": 18, "blg_version": 6,
        "classification": "'W' combined current + power-share profile",
        "why": "The current-axis twin of 'Y' — encoder-less share-loop stimulus.",
        "provisional": False,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "TP0210", "path": "logs/TP0210.BLG", "mode": "conformance",
        "fw_version": 19, "blg_version": 6,
        "classification": "'T' share sweep on the fw v19 handoff-slew build",
        "why": "Most recent share-sweep stimulus; nearest to the flashed target.",
        "provisional": True,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        # RECLASSIFIED conformance -> deviation (2026-08-30, HIL_FINDINGS 'Replay
        # half' Class B).  The log was RECORDED WITH A DARK BUS — V_bus ~= 0 for
        # all 38 s — so it was never a soak case for anything: replayed, the
        # firmware's staged bring-up cannot pass P1 and times out at
        # BUS_CHARGE_TIMEOUT_MS into FAULT_INIT_FAIL (.ino:8784-8786).  That is
        # correct firmware behaviour and now the asserted expectation.
        #
        # REPLAYS RAW — `skip_preamble` (H2, 2026-08-30).  The first version of this
        # entry kept the synthetic preamble, and that made its own expectation
        # UNREACHABLE: the board completed bring-up on the healthy preamble rails and
        # then met the dark trajectory as a RUNNING board, which latches UV_BUS at
        # ~t=2.52 s.  FAULT_INIT_FAIL is raised ONLY by busBringupTick()'s phase
        # timeouts (.ino:8762-8765, :8784-8786), i.e. only from State 0's bring-up
        # machine — a running board can never produce it.  Replaying raw restores the
        # genuine cold-boot-into-darkness test: P0's gate never sees the bus reach
        # V_PRECHARGE_MIN, and PRECHARGE_TIMEOUT_MS (300 ms, .ino:1466) latches
        # INIT_FAIL.  ML0217 is a modern BLG v6 with all rail fields present, so it
        # needs no absent-rail substitution and loses nothing by skipping the
        # preamble.
        #
        # OBSERVABILITY OF THE LATCH (verified): INIT_FAIL fires ~300 ms after
        # bring-up starts, i.e. BEFORE the 2.0 s grace bound.  It is still scored,
        # because State 99 is latched and the simulator keeps streaming — no run
        # boundary, so the fw v23 warm recovery never arms — and fault_flags
        # therefore reads 0xA000 on every post-grace sample.  The grace filter ORs
        # over samples, not over edges, so a persistent bit survives it; the check
        # additionally prints the whole-run first-observation time so the ~0.3 s
        # event is not misreported as a 2.0 s one.
        #
        # Bring-up gate EXEMPT, necessarily: a failing bring-up is the point.
        # Timestamps are UNSHIFTED for this entry (sim time == log time); every
        # consumer resolves that through entry_preamble_s().
        "log": "ML0217", "path": "logs/ML0217.BLG", "mode": "deviation",
        "fw_version": 19, "blg_version": 6,
        "classification": "manual ('K') run RECORDED WITH A DARK BUS (V_bus ~ 0 "
                          "for all 38 s)",
        "why": "The dark-bus stimulus: the firmware must not accept a dead bus as "
               "a working one. Bring-up P1 times out at BUS_CHARGE_TIMEOUT_MS and "
               "FAULT_INIT_FAIL latches (.ino:8784-8786).",
        "provisional": True,
        "skip_bringup_gate": True,
        "skip_preamble": True,
        "checks": [{"kind": "fault_latched", "name": "init_fail_latched",
                    "bit": FAULT_INIT_FAIL, "require_stimulus": False},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "YP0214", "path": "logs/YP0214.BLG", "mode": "conformance",
        "fw_version": 19, "blg_version": 6,
        "classification": "'Y' combined profile on fw v19",
        "why": "Combined-profile stimulus with the handoff slew in the recording.",
        "provisional": True,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },

    # ── CONFORMANCE — older wheel/law: STABILITY conformance, not trace match ─
    {
        "log": "ML0146", "path": "logs/ML0146.BLG", "mode": "conformance",
        "fw_version": 14, "blg_version": 5,
        "classification": "clean 'V' step, 120-slot wheel, fw v14 law",
        "why": "First-flash fw v14 clean baseline. NOT a trace-match case: the "
               "wheel geometry and the control law both changed at fw v18. "
               "Conformance here means stable, fault-free, no limit cycle.",
        "provisional": False,
        "checks": [
            {"kind": "no_fault", "name": "no_fault"},
            {"kind": "bounded_current", "name": "bounded_current"},
            {"kind": "no_rail_limit_cycle", "name": "no_rail_limit_cycle",
             "max_alt_per_s": LIMIT_CYCLE_ALT_PER_S},
        ],
    },
    {
        "log": "ML0149", "path": "logs/ML0149.BLG", "mode": "conformance",
        "fw_version": 14, "blg_version": 5,
        "classification": "clean 'V' step (higher setpoint), fw v14",
        "why": "Second clean fw v14 point; same stability-only conformance meaning.",
        "provisional": False,
        "checks": [
            {"kind": "no_fault", "name": "no_fault"},
            {"kind": "bounded_current", "name": "bounded_current"},
            {"kind": "no_rail_limit_cycle", "name": "no_rail_limit_cycle",
             "max_alt_per_s": LIMIT_CYCLE_ALT_PER_S},
        ],
    },
    {
        "log": "ML0165", "path": "logs/ML0165.BLG", "mode": "deviation",
        "fw_version": 16, "blg_version": 6,
        "classification": "rung stepladder, fw v16; recorded I_fc peaks at 1.52 A "
                          "— above LIMIT_I_FC_MAX",
        "why": OC_FC_RECLASS_WHY % ("ML0165", 1.52),
        "provisional": False,
        "checks": [{"kind": "fault_latched", "name": "oc_fc_latched",
                    "bit": FAULT_OC_FC, "require_stimulus": True},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "ML0169", "path": "logs/ML0169.BLG", "mode": "deviation",
        "fw_version": 16, "blg_version": 6,
        "classification": "friction-disturbance rejection, ~2.2 s continuous "
                          "saturation; recorded I_fc peaks at 1.88 A — above "
                          "LIMIT_I_FC_MAX",
        "why": OC_FC_RECLASS_WHY % ("ML0169", 1.88) + (
            " NOTE what this costs: ML0169 was the suite's saturation-endurance "
            "case, and once OC_FC latches the board is in State 99 and the "
            "returns_off_rail assertion is meaningless, so that check is dropped "
            "here. Saturation endurance now has no replay representative — a "
            "recorded run whose I_fc stays under 1.4 A would be needed to restore "
            "it (see docs/HIL_REPLAY_LOGS.md)."),
        "provisional": False,
        "checks": [{"kind": "fault_latched", "name": "oc_fc_latched",
                    "bit": FAULT_OC_FC, "require_stimulus": True},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "TP0170", "path": "logs/TP0170.BLG", "mode": "conformance",
        "fw_version": 16, "blg_version": 6,
        "classification": "share sweep, share_sp = 0.5",
        "why": "The balanced-share operating point of the first genuine closed-loop "
               "share dataset.",
        "provisional": False,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "TP0176", "path": "logs/TP0176.BLG", "mode": "conformance",
        "fw_version": 16, "blg_version": 6,
        "classification": "share sweep at the FC rail (FC-only for 43–45 % of the run)",
        "why": "The share-rail extreme: one source carries the bus for a long stretch.",
        "provisional": False,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "YP0152", "path": "logs/YP0152.BLG", "mode": "conformance",
        "fw_version": 14, "blg_version": 5,
        "classification": "first 'Y' combined profile on the Youla drive controller",
        "why": "Combined-profile representative from the fw v14 era.",
        "provisional": False,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "ML0151", "path": "logs/ML0151.BLG", "mode": "conformance",
        "fw_version": 14, "blg_version": 5,
        "classification": "H6 FLAGSHIP — 56 s stepladder with the VESC ~428 ms dead "
                          "window, the drag step-change and ~90 saturation episodes",
        "why": "The richest recorded incident in the archive, and the intended H6 "
               "regression: many saturation entries/exits back to back is exactly "
               "the stimulus class the fw v18 general-Hanus fix targets. "
               "L6 KNIFE-EDGE NOTE (measured 2026-08-30): its recorded I_fc PEAKS "
               "AT 1.354 A — 96.7 % of LIMIT_I_FC_MAX 1.4 A. It stays a conformance entry "
               "because it does not cross (unlike the four reclassified in §4a of "
               "the ledger), and it is deliberately NOT moved. But it sits 46 mA "
               "from flipping class: any re-derivation of the FC limit downward, or "
               "any change to how the injected I_fc is scaled, turns this entry's "
               "`no_fault` into a FAIL for a reason that has nothing to do with the "
               "saturation behaviour it exists to test. Check this number first if "
               "ML0151 ever starts failing.",
        "provisional": False,
        "checks": [
            {"kind": "no_fault", "name": "no_fault"},
            {"kind": "bounded_current", "name": "bounded_current"},
            {"kind": "returns_off_rail", "name": "returns_off_rail",
             "level_a": OFF_RAIL_LEVEL_A, "within_s": OFF_RAIL_WITHIN_S},
            {"kind": "no_rail_limit_cycle", "name": "no_rail_limit_cycle",
             "max_alt_per_s": LIMIT_CYCLE_ALT_PER_S},
        ],
    },
    {
        "log": "TP0178", "path": "logs/TP0178.BLG", "mode": "conformance",
        "fw_version": 16, "blg_version": 6,
        "classification": "handoff bus sag to 12.15 V — 0.15 V above LIMIT_V_BUS_MIN, "
                          "10 ms dwell (half the 20 ms latch)",
        "why": "The NEGATIVE UV case: the recorded dip must NOT latch UV_BUS. Pairs "
               "with the legacy UV trio, which must.",
        "provisional": False,
        "checks": [
            {"kind": "no_fault", "name": "no_fault"},
            {"kind": "fault_not_latched", "name": "uv_not_latched", "bit": FAULT_UV_BUS},
        ],
    },

    # ── DEVIATION — older firmware defects the modern build must not reproduce ─
    {
        "log": "ML0137", "path": "logs/ML0137.BLG", "mode": "deviation",
        "fw_version": 11, "blg_version": 5,
        "classification": "boxcar-estimator ±12 A rail-to-rail limit cycle, 2.3–2.6 Hz",
        "why": "The canonical limit-cycle defect. CAVEAT: replay injects the "
               "RECORDED v_act, so this tests the CONTROLLER's reaction to that "
               "stimulus, NOT the estimator fix that actually removed the cycle.",
        "provisional": False,
        "checks": [
            {"kind": "no_rail_limit_cycle", "name": "no_rail_limit_cycle",
             "max_alt_per_s": LIMIT_CYCLE_ALT_PER_S},
            {"kind": "bounded_current", "name": "bounded_current"},
            {"kind": "no_fault", "name": "no_fault"},
        ],
    },
    {
        "log": "ML0140", "path": "logs/ML0140.BLG", "mode": "deviation",
        "fw_version": 12, "blg_version": 5,
        "classification": "estimator blind holds, 120–560 ms, under direction dither",
        "why": "A long frozen-velocity stimulus: the command must stay bounded and "
               "no fault may latch while the injected velocity is stale.",
        "provisional": False,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "bounded_current", "name": "bounded_current"},
                   {"kind": "returns_off_rail", "name": "returns_off_rail",
                    "level_a": OFF_RAIL_LEVEL_A, "within_s": OFF_RAIL_WITHIN_S}],
    },
    {
        "log": "ML0144", "path": "logs/ML0144.BLG", "mode": "deviation",
        "fw_version": 12, "blg_version": 5,
        "classification": "v_sp = 0 relay — 90 % rail bang-bang closing the loop below "
                          "the estimator's own floor",
        "why": "V_SP_ZERO_THRESH (fw v13) is the fix. HONEST LIMIT: replay does not "
               "set v_setpoint — the HIL injection frame carries sensors only — so "
               "the board sits at whatever setpoint it was left at (0 in Idle). What "
               "IS checkable, and what this entry checks, is that with v_sp = 0 and "
               "the log's v_actual injected, the firmware commands ~0 A instead of "
               "bang-banging. The v_sp≠0 relay itself is NOT reproducible here.",
        "provisional": False,
        "checks": [
            {"kind": "no_fault", "name": "no_fault"},
            {"kind": "near_zero_current", "name": "near_zero_current",
             "max_abs_a": NEAR_ZERO_I_A},
        ],
    },
    {
        "log": "ML0153", "path": "logs/ML0153.BLG", "mode": "deviation",
        "fw_version": 14, "blg_version": 5,
        "classification": "T/2 basin — v_act corrupted to ~2× true",
        "why": "A corrupted-velocity stimulus. Deviation meaning: the firmware must "
               "accept the injected values without latching a fault and keep its "
               "command bounded. CAVEAT: the basin fix itself lives in the ESTIMATOR, "
               "which replay bypasses — it is NOT testable open-loop.",
        "provisional": False,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "ML0164", "path": "logs/ML0164.BLG", "mode": "deviation",
        "fw_version": 16, "blg_version": 6,
        "classification": "x2 ROUNDING basin, locked breakaway-to-stop",
        "why": "Same class as ML0153 with the fw v15 rounding path; same caveat — "
               "the basin fix is in the estimator, which replay bypasses.",
        "provisional": False,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "TP0171", "path": "logs/TP0171.BLG", "mode": "deviation",
        "fw_version": 16, "blg_version": 6,
        "classification": "reset re-seeded INTO the x2 basin (~15 ms recovery)",
        "why": "The reset-into-basin stimulus. Same open-loop caveat as ML0153/0164.",
        "provisional": False,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "YP0166", "path": "logs/YP0166.BLG", "mode": "deviation",
        "fw_version": 16, "blg_version": 6,
        "classification": "mid-run v = 0 injection at true 1.49 m/s → ±12 A rail pair "
                          "within 12 ms (the fw v17 TOCTOU race)",
        "why": "A full-scale velocity step straight into the ~454 A/(m/s) LF gain. The "
               "modern firmware must produce a BOUNDED transient that comes back off "
               "the rail, and must not fault.",
        "provisional": False,
        "checks": [
            {"kind": "no_fault", "name": "no_fault"},
            {"kind": "bounded_current", "name": "bounded_current"},
            {"kind": "returns_off_rail", "name": "returns_off_rail",
             "level_a": OFF_RAIL_LEVEL_A, "within_s": OFF_RAIL_WITHIN_S},
        ],
    },
    {
        "log": "TP0201", "path": "logs/TP0201.BLG", "mode": "deviation",
        "fw_version": 18, "blg_version": 6,
        "classification": "share-rail handoff gap, bus 15.86 → 12.185 V",
        "why": "The deepest recorded handoff sag. It stays 0.185 V above "
               "LIMIT_V_BUS_MIN for ~10 ms, i.e. inside the 20 ms dwell, so the "
               "firmware must NOT latch UV. CAVEAT: the fw v19 handoff SLEW that "
               "mitigates the gap acts on the plant, which replay bypasses — the "
               "mitigation is not exercisable open-loop, only the fault decision is.",
        "provisional": False,
        "checks": [
            {"kind": "no_fault", "name": "no_fault"},
            {"kind": "fault_not_latched", "name": "uv_not_latched", "bit": FAULT_UV_BUS},
        ],
    },

    # ── DEVIATION — the legacy UV PAIR: the modern firmware MUST latch ──────
    # Was a "trio"; WP0097 was retired from it 2026-08-30 (see its entry below).
    # Both members are BLG v1/v2 and carry no V_fc/V_batt/V_rgn field at all;
    # before the synthetic bring-up preamble + absent-rail substitution (2026-08-30,
    # hil_plant_sim.py) they injected 0 V for those rails, the staged bring-up's P3
    # gate never saw V_rgn track V_bus, and both latched FAULT_MOT_HOTPLUG at
    # ~1.09 s — dark and un-armable long before the recorded collapse arrived.
    {
        "log": "TP0010", "path": "logs/TP0010.BLG", "mode": "deviation",
        "fw_version": None, "blg_version": 1,
        "classification": "pre-versioning bus collapse; the old firmware died without faulting",
        "why": "UV pair member. The fw v5 leaky-dwell UV filter must latch UV_BUS on "
               "this recorded collapse — that is the whole point of the rework."
               + UV_PAIR_CLAMP_WHY % ("TP0010", 4.770, 4.797),
        "provisional": False,
        "i_fc_clamp_a": UV_PAIR_I_FC_CLAMP_A,
        "checks": [{"kind": "fault_latched", "name": "uv_bus_latched",
                    "bit": FAULT_UV_BUS, "require_stimulus": True}],
    },
    {
        "log": "TP0053", "path": "logs/TP0053.BLG", "mode": "deviation",
        "fw_version": 4, "blg_version": 2,
        "classification": "repetitive source-commutation dropout (~9 ms under / ~51 ms "
                          "over per ~60 ms cycle) that EVADED the fw v4 window filter",
        "why": "UV pair member and the exact case the dwell integrator was designed "
               "for: net +6.45 ms per cycle, so it must latch within a few cycles."
               + UV_PAIR_CLAMP_WHY % ("TP0053", 3.929, 4.462),
        "provisional": False,
        "i_fc_clamp_a": UV_PAIR_I_FC_CLAMP_A,
        "checks": [{"kind": "fault_latched", "name": "uv_bus_latched",
                    "bit": FAULT_UV_BUS, "require_stimulus": True}],
    },
    {
        # RETIRED FROM THE UV TRIO (2026-08-30, HIL_FINDINGS 'Replay half'): the
        # recorded dip supplies only ~18 ms of dwell against the 20 ms
        # UV_BUS_DWELL_LATCH_MS, and the log ENDS mid-dip — so it is not a valid UV
        # stimulus for the current filter and the uv_bus_latched check could only
        # ever report INCONCLUSIVE. The trio is now the PAIR TP0010 + TP0053.
        # RECLASSIFIED to the OC_FC family instead, where its recorded 3.60 A I_fc
        # peak — the largest in the archive — makes it the strongest member.
        "log": "WP0097", "path": "logs/WP0097.BLG", "mode": "deviation",
        "fw_version": 5, "blg_version": 3,
        "classification": "fw v5-era bus collapse; recorded I_fc peaks at 3.60 A "
                          "— the archive's largest, far above LIMIT_I_FC_MAX",
        "why": OC_FC_RECLASS_WHY % ("WP0097", 3.60) + (
            " L5 CAVEAT — this entry is TIGHT IN TIME (measured 2026-08-30): the "
            "recorded I_fc crosses 1.4 A only at log t=16.964 s and the log ENDS at "
            "17.006 s, so the whole OC stimulus is the last 40 ms of the recording. "
            "There is no margin in current (the peak is 3.60 A, 2.6x the limit) but "
            "almost none in time: anything that shortens the replay, shifts its "
            "time base, or trims the tail pushes the crossing off the end and this "
            "becomes an INCONCLUSIVE stimulus report. That report is the DESIGNED "
            "failure mode (require_stimulus), so the entry degrades loudly rather "
            "than silently — but treat any timing change here as fragile."
            " Retired from the UV pair: its recorded dip gives ~18 ms of dwell "
            "against the 20 ms latch and the log ends mid-dip, so it was never a "
            "qualifying UV stimulus (the suite already worded that honestly, but "
            "kept scoring it). TP0010 and TP0053 remain the UV pair."),
        "provisional": False,
        "checks": [{"kind": "fault_latched", "name": "oc_fc_latched",
                    "bit": FAULT_OC_FC, "require_stimulus": True},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# Excluded logs — kept in the module so the reasoning travels with the suite.
# The prose version lives in docs/HIL_REPLAY_LOGS.md.
# ─────────────────────────────────────────────────────────────────────────────
REPLAY_EXCLUSIONS = [
    ("ML0182, ML0183",
     "Encoder-diagnostic runs on a DEFECTIVE 120-slot thin-tooth wheel (~92 % blind). "
     "The stimulus characterises a sensor mount that no longer exists."),
    ("ML0135",
     "Obsolete PI control law plus a reverse-direction diagnostic — neither the law "
     "nor the manoeuvre maps onto anything the current build does."),
    ("fw v3–v8 bulk campaigns (TP0014–TP0134, WP0039–WP0124, PS000x, TEST0001)",
     "Superseded control law and superseded fault logic; replaying dozens of them adds "
     "runtime, not coverage. Three representatives are kept: TP0010 and TP0053 as "
     "the UV PAIR (two different collapse shapes), and WP0097, which was retired "
     "from that group on 2026-08-30 — its dip gives only ~18 ms of dwell against "
     "the 20 ms latch and the log ends mid-dip — and now serves as the largest "
     "OC_FC stimulus in the archive (3.60 A)."),
    ("hand-spin / manual-wheel diagnostics generally",
     "Stimulus is an operator's hand, not a control scenario: no repeatable property "
     "to assert."),
]


def suite_index():
    """Map log name -> suite entry."""
    return {e["log"]: e for e in REPLAY_SUITE}


# ─────────────────────────────────────────────────────────────────────────────
# CSV parsing.
#
# A replay CSV is hil_plant_sim's simulated schema plus an appended `replay_rec`
# column (tools/hil_plant_sim.py, the `if replay:` branch of the header/row
# writers).  The observation columns — state, switch, aux, current, mdac_fc,
# mdac_bt, fault_flags — are BLANK on every tick before the first observation
# frame arrives, so every reader below skips blanks rather than assuming zero.
# ─────────────────────────────────────────────────────────────────────────────
OBS_COLUMNS = ("state", "switch", "aux", "current", "mdac_fc", "mdac_bt", "fault_flags")
REQUIRED_COLUMNS = ("t", "V_bus", "current", "fault_flags")


class ReplayCsv:
    """Parsed replay CSV: parallel lists, blanks dropped per-series."""

    def __init__(self, rows, columns, grace_s=REPLAY_GRACE_S,
                 preamble_s=REPLAY_PREAMBLE_S):
        self.columns = columns
        self.rows = rows
        self.grace_s = grace_s
        # M5/M6: where the RECORDED trajectory starts on the sim clock.  Distinct
        # from grace_s and never interchangeable with it: grace_s is about the
        # BOARD (the previous run's inherited latch), preamble_s is about the
        # STIMULUS (rails this module synthesized rather than recorded).
        self.preamble_s = preamble_s
        # (t, value) series with blanks removed.
        self.current = _series(rows, "t", "current", float)
        # M6: the command series restricted to the RECORDED window.  Rate-based
        # checks must not dilute their denominator with preamble seconds during
        # which no recorded stimulus existed — a 2.5 s preamble on a 4 s log
        # (ML0137) would understate an alternation rate by 1.6x.
        self.current_recorded = [(t, i) for t, i in self.current if t >= preamble_s]
        # `faults_all` is every observed fault sample; `faults` is the GRACE-FILTERED
        # view and is what every check below reads.  The two are separate attributes
        # rather than a flag so a check cannot silently pick the wrong one: the
        # unfiltered series is only for reporting what was carried in.
        self.faults_all = _series(rows, "t", "fault_flags", _int_any)
        self.faults = [(t, f) for t, f in self.faults_all if t >= grace_s]
        self.faults_pre_grace = [(t, f) for t, f in self.faults_all if t < grace_s]
        self.v_bus = _series(rows, "t", "V_bus", float)
        # Injected FC current — the stimulus side, never blank.  Used by
        # check_fault_latched's OC stimulus guard.
        self.i_fc = _series(rows, "t", "I_fc", float)
        self.state = _series(rows, "t", "state", _int_any)
        self.n_rows = len(rows)
        self.n_obs = len(self.current)
        self.duration_s = (float(rows[-1]["t"]) - float(rows[0]["t"])) if rows else 0.0

    def first_fault_t(self, bit=None):
        """L1: WHOLE-RUN first time a fault (or `bit`) was observed, or None.

        Distinct from the times the checks print, which are necessarily the first
        POST-GRACE observation.  A fault that latches before the grace bound and
        persists — ML0217's INIT_FAIL at ~0.3 s is the standing example — is
        correctly scored on its post-grace samples, but reporting 2.0 s as "when it
        happened" would be wrong; both numbers are shown."""
        for t, f in self.faults_all:
            if (f & bit) if bit is not None else f:
                return t
        return None

    def carried_in_bits(self):
        """Fault bits seen ONLY before the grace bound — the predecessor's latch."""
        pre = 0
        for _t, f in self.faults_pre_grace:
            pre |= f
        post = 0
        for _t, f in self.faults:
            post |= f
        return pre & ~post

    def reached_idle_t(self, deadline_s=BRINGUP_DEADLINE_S):
        """Sim time the board first reported mainState 1, or None within deadline."""
        for t, st in self.state:
            if st == BRINGUP_STATE_IDLE:
                return t if t <= deadline_s else None
        return None


def _int_any(cell):
    """fault_flags / state may be printed decimal or 0x-prefixed."""
    cell = cell.strip()
    return int(cell, 16) if cell.lower().startswith("0x") else int(cell)


def _series(rows, t_key, key, conv):
    out = []
    for r in rows:
        cell = r.get(key, "")
        if cell is None or cell == "":
            continue          # tick before the first observation frame
        try:
            out.append((float(r[t_key]), conv(cell)))
        except (ValueError, KeyError):
            continue
    return out


def load_replay_csv(csv_path, preamble_s=REPLAY_PREAMBLE_S):
    with open(csv_path, "r", newline="") as fh:
        reader = csv.DictReader(fh)
        columns = list(reader.fieldnames or [])
        rows = [r for r in reader if r.get("t") not in (None, "")]
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    if missing:
        raise ValueError(
            f"{csv_path} is missing column(s) {missing} — is it a hil_plant_sim CSV?")
    if not rows:
        raise ValueError(f"{csv_path} has no data rows")
    return ReplayCsv(rows, columns, preamble_s=preamble_s)


# ─────────────────────────────────────────────────────────────────────────────
# Check implementations — small pure functions over a ReplayCsv.
# Each returns (passed: bool, detail: str).
# ─────────────────────────────────────────────────────────────────────────────

def _fault_names(bits):
    if bits == 0:
        return "none"
    names = [n for b, n in sorted(FAULT_NAMES.items()) if bits & b]
    unknown = bits & ~sum(FAULT_NAMES)
    if unknown:
        names.append(f"0x{unknown:04X}")
    return "|".join(names)


def _whole_run_first_note(data, bit=None):
    """L1: name the WHOLE-RUN first observation when it precedes the grace bound.

    Every time a check prints is necessarily a first POST-GRACE observation.  For a
    fault that latched earlier and persisted (ML0217's INIT_FAIL at ~0.3 s), that
    number describes the filter, not the event — so the real one is shown beside
    it.  Silent when the two coincide."""
    t0 = data.first_fault_t(bit)
    if t0 is None or t0 >= data.grace_s:
        return ""
    return (f" (whole-run first observation t={t0:.3f}s — it latched BEFORE the "
            f"{data.grace_s:.1f}s grace bound and PERSISTED, which is why the "
            f"grace filter still sees it)")


def _carried_in_note(data):
    """Report-only sentence naming the excluded pre-grace bits, or ''."""
    carried = data.carried_in_bits()
    if not carried:
        return ""
    return (f"; carried-in from the predecessor's settle latch and EXCLUDED: "
            f"{_fault_names(carried)} (seen only before t={data.grace_s:.1f}s, "
            f"cleared by the fw v23 grace-window warm reset)")


def check_no_fault(data, spec):
    """fault_flags stays 0 for every observed tick AT OR AFTER the grace bound.

    `ignore_bits` lets an entry tolerate a specific bit (none do today; the knob
    exists so a future entry does not need a new check kind)."""
    ignore = int(spec.get("ignore_bits", 0))
    if not data.faults:
        return False, (f"no observation frames at or after t={data.grace_s:.1f}s "
                       f"— nothing was observed")
    worst, worst_t = 0, None
    for t, f in data.faults:
        f &= ~ignore
        if f and worst == 0:
            worst, worst_t = f, t
        worst |= f
    if worst:
        return False, (f"faults raised: 0x{worst:04X} ({_fault_names(worst)}), "
                       f"first POST-GRACE observation at t={worst_t:.3f}s"
                       f"{_whole_run_first_note(data, worst)}"
                       f"{_carried_in_note(data)}")
    return True, (f"fault_flags == 0 across {len(data.faults)} observed ticks at "
                  f"t >= {data.grace_s:.1f}s{_carried_in_note(data)}")


def check_fault_not_latched(data, spec):
    """A specific bit must never appear post-grace (the negative UV cases)."""
    bit = int(spec["bit"])
    hits = [(t, f) for t, f in data.faults if f & bit]
    if not data.faults:
        return False, (f"no observation frames at or after t={data.grace_s:.1f}s")
    if hits:
        return False, (f"{_fault_names(bit)} set at t={hits[0][0]:.3f}s "
                       f"({len(hits)} ticks) — the recorded dip should NOT latch it")
    return True, (f"{_fault_names(bit)} never set across {len(data.faults)} ticks "
                  f"at t >= {data.grace_s:.1f}s{_carried_in_note(data)}")


def check_fault_latched(data, spec):
    """A specific bit must be set, and still set at the end of the run.

    With `require_stimulus` (default True) the INJECTED stimulus is first checked
    against the firmware's own latch criterion for that bit, so a suite entry whose
    recorded trajectory no longer qualifies FAILS LOUDLY as inconclusive rather
    than passing, or silently excusing the firmware.  Two stimulus models:

      FAULT_UV_BUS  the V_bus series replayed through the leaky-dwell filter
                    (LIMIT_V_BUS_MIN / UV_BUS_DWELL_*).
      FAULT_OC_FC   the I_fc series must actually exceed LIMIT_I_FC_MAX.  The OC
                    check is a single-sample comparison in the firmware, so this
                    mirrors it exactly rather than approximating it.

    Anything else with require_stimulus set is a suite authoring error and is
    reported as such — silently skipping the guard is how an entry's stimulus rots
    unnoticed."""
    bit = int(spec["bit"])
    if not data.faults:
        return False, (f"no observation frames at or after t={data.grace_s:.1f}s")
    stim_t = None
    if spec.get("require_stimulus", True):
        if bit == FAULT_UV_BUS:
            qualifies, when, peak = _uv_stimulus_qualifies(data)
            if not qualifies:
                return False, (
                    f"INCONCLUSIVE: the injected V_bus never accumulates "
                    f"{UV_BUS_DWELL_LATCH_MS:.0f} ms of net dwell below "
                    f"{LIMIT_V_BUS_MIN_V:.1f} V while armed (peak dwell {peak:.1f} ms) — "
                    f"this log is not a UV stimulus for the current filter")
            stim_t = when
        elif bit == FAULT_OC_FC:
            qualifies, when, peak = _oc_fc_stimulus_qualifies(data)
            if not qualifies:
                return False, (
                    f"INCONCLUSIVE: the injected I_fc never exceeds "
                    f"LIMIT_I_FC_MAX {LIMIT_I_FC_MAX_A:.2f} A (peak "
                    f"{peak:.3f} A) — this log is not an OC_FC stimulus, so the "
                    f"entry's classification no longer matches its own log")
            stim_t = when
        else:
            # L8: no bare fall-through. `bit` is mandatory in the spec (read at the
            # top of this function), so reaching here means require_stimulus was set
            # for a bit that has no stimulus model — a suite authoring error, and
            # silently skipping the guard is how an entry's stimulus rots unnoticed.
            return False, (f"suite error: require_stimulus is set for "
                           f"{_fault_names(bit)}, which has no stimulus model here. "
                           f"Add one, or set require_stimulus: False deliberately.")
    hits = [t for t, f in data.faults if f & bit]
    end_flags = data.faults[-1][1]
    if not hits:
        extra = f" (stimulus qualifies from t={stim_t:.3f}s)" if stim_t is not None else ""
        return False, f"{_fault_names(bit)} was never set{extra}"
    if not (end_flags & bit):
        return False, (f"{_fault_names(bit)} set at t={hits[0]:.3f}s but CLEARED by the "
                       f"end of the run (final 0x{end_flags:04X}) — it must LATCH")
    return True, (f"{_fault_names(bit)} latched; first POST-GRACE observation at "
                  f"t={hits[0]:.3f}s"
                  + _whole_run_first_note(data, bit)
                  + (f", stimulus qualified from t={stim_t:.3f}s" if stim_t is not None else ""))


def _oc_fc_stimulus_qualifies(data):
    """Does the INJECTED I_fc series actually cross LIMIT_I_FC_MAX?

    Returns (qualifies, t_at_first_crossing, peak_a).  Mirrors the firmware's OC
    check exactly: detectFaults() compares the single most recent sample against
    LIMIT_I_FC_MAX, with no dwell filter (unlike the UV path), so a single sample
    over the limit both latches on the board and qualifies here.

    M5/L2: samples are filtered from `data.preamble_s`, NOT from the grace bound.
    The two are different questions and the earlier code conflated them: the grace
    bound is about the BOARD (whose latch is this?), while a stimulus guard asks
    whether the RECORDED LOG contains the stimulus.  Preamble rails are synthesized
    by this harness, so letting them arm or qualify anything would be the harness
    scoring its own input."""
    peak = 0.0
    when = None
    for t, i in data.i_fc:
        if t < data.preamble_s:
            continue
        if i > peak:
            peak = i
        if when is None and i > LIMIT_I_FC_MAX_A:
            when = t
    return when is not None, when, peak


def _uv_stimulus_qualifies(data):
    """Replay the firmware's UV_BUS leaky dwell integrator over the INJECTED
    V_bus series.  Returns (qualifies, t_at_latch, peak_dwell_ms).

    Mirrors teensy_controller.ino:4690-4735: +dt under LIMIT_V_BUS_MIN,
    -UV_BUS_DWELL_LEAK*dt at/above it, per-tick dt capped at
    UV_BUS_DWELL_DT_CAP_MS, latch at UV_BUS_DWELL_LATCH_MS.  Arming is
    approximated by the bus having reached V_BUS_CHARGED_THRESH at least once
    (.ino:1363) — the switch-state half of the real arming condition is not
    reconstructible from the injected rails alone, which is why this is a
    stimulus SANITY check and not a firmware model.

    M5: samples before `data.preamble_s` are SKIPPED.  The synthetic preamble holds
    a healthy 15.95 V, which would ARM the filter on rails this harness invented
    rather than on anything the log recorded — the arming half of a stimulus guard
    must come from the stimulus."""
    dwell = 0.0
    peak = 0.0
    armed = False
    prev_t = None
    for t, v in data.v_bus:
        if t < data.preamble_s:
            continue
        if v >= V_BUS_CHARGED_THRESH_V:
            armed = True
        if prev_t is None:
            prev_t = t
            continue
        dt_ms = min((t - prev_t) * 1000.0, UV_BUS_DWELL_DT_CAP_MS)
        prev_t = t
        if not armed:
            continue
        if v < LIMIT_V_BUS_MIN_V:
            dwell += dt_ms
        else:
            dwell = max(0.0, dwell - UV_BUS_DWELL_LEAK * dt_ms)
        peak = max(peak, dwell)
        if dwell >= UV_BUS_DWELL_LATCH_MS:
            return True, t, peak
    return False, None, peak


def check_bounded_current(data, spec):
    """|current| never exceeds the firmware's own clamp."""
    limit = float(spec.get("limit_a", MOTOR_I_CMD_MAX_A)) + I_CMD_EPS_A
    if not data.current:
        return False, "no observation frames in the CSV"
    worst_t, worst = max(data.current, key=lambda tv: abs(tv[1]))
    if abs(worst) > limit:
        return False, f"|I_cmd| reached {worst:+.4f} A at t={worst_t:.3f}s (limit {limit:.2f} A)"
    return True, f"peak |I_cmd| {worst:+.4f} A at t={worst_t:.3f}s, within ±{limit:.2f} A"


def _rail_episodes(series, level):
    """Contiguous runs of |I| >= level, as (t_start, t_end, sign)."""
    episodes = []
    start = None
    sign = 0
    prev_t = None
    for t, i in series:
        s = 1 if i >= level else (-1 if i <= -level else 0)
        if s != sign:
            if sign != 0 and start is not None:
                episodes.append((start, prev_t if prev_t is not None else t, sign))
            start = t if s != 0 else None
            sign = s
        prev_t = t
    if sign != 0 and start is not None:
        episodes.append((start, prev_t, sign))
    return episodes


def check_no_sustained_rail(data, spec):
    """No single rail episode lasts longer than max_episode_s."""
    max_s = float(spec.get("max_episode_s", SUSTAINED_RAIL_S))
    level = float(spec.get("level_a", RAIL_LEVEL_A))
    if not data.current:
        return False, "no observation frames in the CSV"
    eps = _rail_episodes(data.current, level)
    longest = max(((b - a), a, s) for a, b, s in eps) if eps else (0.0, None, 0)
    if longest[0] > max_s:
        return False, (f"rail episode of {longest[0]:.3f}s at t={longest[1]:.3f}s "
                       f"(sign {longest[2]:+d}) exceeds {max_s:.2f}s")
    return True, (f"{len(eps)} rail episode(s), longest {longest[0]:.3f}s "
                  f"(limit {max_s:.2f}s)")


def check_no_rail_limit_cycle(data, spec):
    """Rail-to-rail SIGN ALTERNATIONS per second stay below max_alt_per_s.

    An alternation is consecutive rail episodes of opposite sign — the ML0137
    signature.  Rate is over the observed span, not the whole CSV, so ticks
    before the first observation frame do not dilute it.

    M6: and the span is the RECORDED window only (`data.current_recorded`,
    t >= preamble_s).  This is the one check whose verdict is a RATE, so the
    synthetic preamble goes straight into its denominator: 2.5 s of preamble on
    ML0137's ~4 s log would understate the alternation rate by ~1.6x and could
    pass a genuine limit cycle.  The other command checks are extremal
    (bounded_current, no_sustained_rail) or per-episode (returns_off_rail) and are
    unaffected — a quiet preamble adds no episodes and cannot lower a maximum."""
    max_rate = float(spec.get("max_alt_per_s", LIMIT_CYCLE_ALT_PER_S))
    level = float(spec.get("level_a", RAIL_LEVEL_A))
    if not data.current_recorded:
        return False, ("no observation frames in the recorded window "
                       "(t >= %.1fs)" % data.preamble_s)
    span = data.current_recorded[-1][0] - data.current_recorded[0][0]
    eps = _rail_episodes(data.current_recorded, level)
    alts = sum(1 for a, b in zip(eps, eps[1:]) if a[2] != b[2])
    rate = alts / span if span > 0 else float(alts)
    if rate > max_rate:
        return False, (f"{alts} rail-to-rail alternations over {span:.2f}s = "
                       f"{rate:.2f}/s (limit {max_rate:.2f}/s) — looks like a limit cycle")
    return True, (f"{alts} rail-to-rail alternations over {span:.2f}s = {rate:.2f}/s "
                  f"(limit {max_rate:.2f}/s)")


def check_returns_off_rail(data, spec):
    """After every rail episode the command must fall below level_a within
    within_s.

    A trailing episode still on the rail when the CSV ends is exempt ONLY if the
    episode itself is no longer than within_s — a brief rail at the moment the
    stimulus runs out is not evidence of anything, but a run that ends PINNED for
    seconds is exactly the windup signature this check exists to catch.  (The
    naive "the run ended, so excuse it" rule silently passed a synthetic 6 s pin
    during bring-up of this module.)"""
    level = float(spec.get("level_a", OFF_RAIL_LEVEL_A))
    within = float(spec.get("within_s", OFF_RAIL_WITHIN_S))
    rail_level = float(spec.get("rail_level_a", RAIL_LEVEL_A))
    if not data.current:
        return False, "no observation frames in the CSV"
    eps = _rail_episodes(data.current, rail_level)
    if not eps:
        return True, "no rail episodes to return from"
    t_end_csv = data.current[-1][0]
    worst = None
    pinned_to_end = None
    # L7: SINGLE forward walk over data.current with a cursor shared across
    # episodes, instead of rescanning the whole series from the start for every
    # episode (was O(episodes * samples) -- ~5M iterations on a log like ML0151).
    # Episodes come out of _rail_episodes() in ascending time order (itself a
    # single forward scan) and data.current is already time-ordered, so the
    # cursor only ever needs to move forward -- behavior-identical to the old
    # per-episode full rescan.
    cursor = 0
    n = len(data.current)
    for a, b, _s in eps:
        while cursor < n and data.current[cursor][0] <= b:
            cursor += 1
        rec = None
        j = cursor
        while j < n:
            t, i = data.current[j]
            if abs(i) < level:
                rec = t - b
                break
            j += 1
        if rec is None:
            # Episode never released within the CSV.
            if (b - a) <= within and (t_end_csv - b) <= within:
                continue        # short rail at the very end of the stimulus — exempt
            pinned_to_end = (a, b - a)
            rec = float("inf")
        if worst is None or rec > worst[0]:
            worst = (rec, b)
    if pinned_to_end is not None:
        return False, (f"run ends still on the rail: episode from t={pinned_to_end[0]:.3f}s "
                       f"lasted {pinned_to_end[1]:.3f}s and never fell below "
                       f"{level:.1f} A — unbounded windup signature")
    if worst is None:
        return True, f"{len(eps)} rail episode(s), all released before the run ended"
    if worst[0] > within:
        s = "never" if worst[0] == float("inf") else f"{worst[0]:.3f}s"
        return False, (f"after the rail episode ending at t={worst[1]:.3f}s, |I_cmd| "
                       f"took {s} to fall below {level:.1f} A (limit {within:.2f}s) "
                       f"— unbounded windup signature")
    return True, (f"{len(eps)} rail episode(s); worst release {worst[0]:.3f}s "
                  f"below {level:.1f} A (limit {within:.2f}s)")


def check_near_zero_current(data, spec):
    """|current| stays within max_abs_a — the "not driving" expectation."""
    max_abs = float(spec.get("max_abs_a", NEAR_ZERO_I_A))
    if not data.current:
        return False, "no observation frames in the CSV"
    worst_t, worst = max(data.current, key=lambda tv: abs(tv[1]))
    if abs(worst) > max_abs:
        return False, (f"|I_cmd| reached {worst:+.4f} A at t={worst_t:.3f}s, above the "
                       f"{max_abs:.2f} A 'not driving' bound")
    return True, f"peak |I_cmd| {worst:+.4f} A, within ±{max_abs:.2f} A"


CHECK_KINDS = {
    "no_fault": check_no_fault,
    "fault_latched": check_fault_latched,
    "fault_not_latched": check_fault_not_latched,
    "bounded_current": check_bounded_current,
    "no_sustained_rail": check_no_sustained_rail,
    "no_rail_limit_cycle": check_no_rail_limit_cycle,
    "returns_off_rail": check_returns_off_rail,
    "near_zero_current": check_near_zero_current,
}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_replay_csv(entry, csv_path):
    """Run `entry["checks"]` against a hil_plant_sim replay CSV.

    Returns {"log", "mode", "passed", "checks": [{"name","passed","detail"}],
             "notes": [...]}.  A missing/unparseable CSV, or a check kind that
    does not exist, is reported as a failure — never raised past the caller."""
    result = {
        "log": entry.get("log"),
        "mode": entry.get("mode"),
        "csv": csv_path,
        "passed": False,
        "checks": [],
        "notes": [],
        # L8: structured, additive field so a caller (run_hil_suite.py) can detect
        # "the board never answered" numerically instead of substring-matching a
        # prose note from this module.  None until a CSV is actually parsed below.
        "n_obs": None,
    }

    fw = entry.get("fw_version")
    note = FW_DELTA_NOTES.get(fw)
    if note:
        result["notes"].append(f"fw {fw if fw is not None else 'pre-versioning'}: {note}")
    if fw is None or fw < COMPARABLE_FW_MIN:
        result["notes"].append(
            f"Recorded on fw {fw if fw is not None else 'pre-versioning'} < v{COMPARABLE_FW_MIN}: "
            f"different wheel geometry and/or control law than the flashed fw "
            f"v{TARGET_FW_VERSION}. Judge STABILITY and FAULT BEHAVIOUR, never trace match.")
    if entry.get("provisional"):
        result["notes"].append("PROVISIONAL selection — not yet confirmed by a full analysis pass.")
    result["notes"].append(
        "Replay is OPEN LOOP: the plant integrator and the encoder estimator are "
        "bypassed, and I_charge/ag105_status inject as 0.0 A / 0x00 for every BLG "
        "format v1-v7.")
    pre_s = entry_preamble_s(entry)
    if pre_s > 0.0:
        result["notes"].append(
            f"Time base: a {pre_s:.1f} s synthetic bring-up preamble "
            f"(healthy nominal rails) precedes the recorded trajectory, so every "
            f"time below is SIM-relative and log time = sim time - {pre_s:.1f}s "
            f"(preamble rows carry replay_rec = -1). Stimulus guards and "
            f"rate-based checks use the recorded window only.")
    else:
        result["notes"].append(
            "Time base: this entry replays RAW (skip_preamble / "
            "--replay-no-preamble), so sim time == log time and the board boots "
            "into the recording's own first samples. A bring-up failure is an "
            "expected outcome for such an entry, not an artefact.")
    result["notes"].append(
        f"Fault checks judge observations at t >= {REPLAY_GRACE_S:.1f}s only — "
        f"earlier bits are the previous run's inherited settle latch. A fault that "
        f"latched earlier and PERSISTS is still seen (State 99 is latched and the "
        f"simulator keeps streaming, so nothing clears it); its whole-run first "
        f"time is reported alongside the post-grace one.")
    clamp = entry.get("i_fc_clamp_a")
    if clamp is not None:
        result["notes"].append(
            f"*** INJECTED I_fc CLAMPED to {clamp:.2f} A *** — this entry's "
            f"recorded trajectory is DELIBERATELY MODIFIED on the FC channel. See "
            f"the entry's `why` and docs/HIL_REPLAY_LOGS.md for the justification "
            f"(operator ruling (a)); no conclusion about FC current may be drawn "
            f"from this run.")
    result["notes"].append(
        "PURPOSE: this half is a BRING-UP + FAULT-DECISION regression harness. No "
        "commander exists in replay mode, so the board never leaves Idle and the "
        "commanded current is 0 A throughout; the current-shape checks assert only "
        "that the firmware does NOT drive on an uncommanded stimulus.")

    try:
        data = load_replay_csv(csv_path, preamble_s=entry_preamble_s(entry))
    except (OSError, ValueError) as exc:
        result["checks"].append({"name": "csv", "passed": False, "detail": str(exc)})
        return result

    result["n_obs"] = data.n_obs
    if data.n_obs == 0:
        result["notes"].append(
            "No observation frames in the CSV — the board never answered. Is it "
            "flashed with -DHIL_SIM=1 -DUSE_ETHERNET=1 and on the right IP?")
    else:
        result["notes"].append(
            f"{data.n_obs}/{data.n_rows} ticks carry an observation frame; "
            f"{data.duration_s:.2f}s of replay.")

    # ── Bring-up gate ────────────────────────────────────────────────────────
    # Runs BEFORE the entry's own checks and, on failure, INSTEAD of them.  A board
    # that never reached Idle fails every downstream check for one single reason,
    # and reporting that as N independent findings is how the first fw v23 pass
    # produced 19 identically-shaped false failures.  Report the one true cause and
    # mark the rest not-run.
    all_passed = True
    if not entry.get("skip_bringup_gate"):
        idle_t = data.reached_idle_t()
        if idle_t is None:
            last_state = data.state[-1][1] if data.state else None
            faults_post = 0
            for _t, f in data.faults:
                faults_post |= f
            result["checks"].append({
                "name": "bringup_reached_idle", "passed": False,
                "detail": (f"the board never reported mainState "
                           f"{BRINGUP_STATE_IDLE} (Idle) within "
                           f"{BRINGUP_DEADLINE_S:.1f}s — BRING-UP FAILED. Last "
                           f"observed mainState {last_state}, post-grace fault "
                           f"union {_fault_names(faults_post)}. The entry's own "
                           f"checks are NOT run: on a board that never came up "
                           f"they would all fail for this one reason.")})
            result["notes"].append(
                "Entry checks SKIPPED — the bring-up gate failed, so nothing "
                "downstream would have been evidence about the recorded stimulus.")
            return result
        result["checks"].append({
            "name": "bringup_reached_idle", "passed": True,
            "detail": (f"mainState {BRINGUP_STATE_IDLE} (Idle) first observed at "
                       f"t={idle_t:.3f}s, inside the {BRINGUP_DEADLINE_S:.1f}s "
                       f"deadline")})
    else:
        result["notes"].append(
            "Bring-up gate SKIPPED for this entry (skip_bringup_gate): a failing "
            "bring-up is what it is testing.")

    for spec in entry.get("checks", []):
        name = spec.get("name", spec.get("kind", "?"))
        fn = CHECK_KINDS.get(spec.get("kind"))
        if fn is None:
            passed, detail = False, f"unknown check kind {spec.get('kind')!r}"
        else:
            try:
                passed, detail = fn(data, spec)
            except Exception as exc:                      # never let one check kill the run
                passed, detail = False, f"check raised {type(exc).__name__}: {exc}"
        all_passed = all_passed and passed
        result["checks"].append({"name": name, "passed": passed, "detail": detail})

    result["passed"] = all_passed and bool(entry.get("checks"))
    if not entry.get("checks"):
        result["checks"].append({"name": "checks", "passed": False,
                                 "detail": "suite entry defines no checks"})
    return result


def build_sim_argv(entry, csv_dir):
    """argv for tools/hil_plant_sim.py main(): replay this entry's log, CSV here.

    Deliberately omits --teensy-ip/--port: the wrapper owns the transport and
    appends them.  The CSV name is derived from the log so a batch run leaves an
    unambiguous artifact per entry.

    --force is included because the CSV name is DERIVED, not chosen: it is the
    same name on every replay of the same entry.  hil_plant_sim.py refuses an
    explicit --csv whose CSV or either sidecar already exists (exit 2), so
    without --force the second replay of an entry into the same directory —
    including the default `--argv-for --csv-dir .` form — would die at startup
    instead of running.  Overwriting a same-entry artifact is the intended
    behaviour here; keep the old one by pointing --csv-dir somewhere else."""
    csv_path = os.path.join(csv_dir, f"hil_replay_{entry['log']}.csv")
    argv = ["--replay", os.path.join(REPO_ROOT, entry["path"]),
            "--csv", csv_path, "--force"]
    # Per-entry stimulus modifiers. Both are declared in the entry table and BOTH
    # must be mirrored here, or a hand-run replay would silently differ from a
    # suite-run one and the checks (which resolve the same fields) would be
    # scoring a different stimulus than the one that was injected.
    if entry.get("skip_preamble"):
        argv.append("--replay-no-preamble")
    if entry.get("i_fc_clamp_a") is not None:
        argv += ["--replay-i-fc-clamp", "%g" % float(entry["i_fc_clamp_a"])]
    return argv


def replay_csv_path(entry, csv_dir):
    """The CSV path build_sim_argv() will ask hil_plant_sim to write."""
    return os.path.join(csv_dir, f"hil_replay_{entry['log']}.csv")


def verify_suite_logs(repo_root=REPO_ROOT):
    """Check every entry's .BLG exists and that its header agrees with the table.

    Reads the header directly (magic 'BLG1', format version at byte 4, fw_version
    u16 at offset 18 — v1 files predate the field, decode_benchlog.py:425) so this
    stays a cheap stdlib check.  Returns a list of problem strings; empty == clean."""
    import struct
    problems = []
    for e in REPLAY_SUITE:
        path = os.path.join(repo_root, e["path"])
        if not os.path.isfile(path):
            problems.append(f"{e['log']}: missing file {e['path']}")
            continue
        with open(path, "rb") as fh:
            head = fh.read(24)
        if len(head) < 24 or head[:4] != b"BLG1":
            problems.append(f"{e['log']}: not a BLG1 file")
            continue
        blg = head[4]
        fw = struct.unpack_from("<H", head, 18)[0] if blg >= 2 else None
        if blg != e["blg_version"]:
            problems.append(f"{e['log']}: BLG format v{blg} on disk, table says "
                            f"v{e['blg_version']}")
        if fw != e["fw_version"]:
            problems.append(f"{e['log']}: header fw_version {fw}, table says "
                            f"{e['fw_version']}")
    return problems


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _print_suite():
    print(f"{'log':8} {'fw':>4} {'blg':>3}  {'mode':11} checks")
    print("-" * 78)
    for e in REPLAY_SUITE:
        fw = "-" if e["fw_version"] is None else str(e["fw_version"])
        prov = " *" if e["provisional"] else ""
        checks = ",".join(c["name"] for c in e["checks"])
        print(f"{e['log']:8} {fw:>4} {e['blg_version']:>3}  {e['mode']:11} {checks}{prov}")
    print("-" * 78)
    print(f"{len(REPLAY_SUITE)} entries "
          f"({sum(1 for e in REPLAY_SUITE if e['mode'] == 'conformance')} conformance, "
          f"{sum(1 for e in REPLAY_SUITE if e['mode'] == 'deviation')} deviation); "
          f"* = provisional")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Replay-based HIL scenario suite: selection table + CSV evaluation. "
                    "Running the board is the wrapper's job — this module lists the "
                    "suite and scores an existing replay CSV.")
    ap.add_argument("--list", action="store_true", help="print the suite table")
    ap.add_argument("--evaluate", nargs=2, metavar=("LOG", "CSV"),
                    help="evaluate an existing replay CSV against LOG's suite entry")
    ap.add_argument("--argv-for", metavar="LOG",
                    help="print the hil_plant_sim argv for LOG")
    ap.add_argument("--csv-dir", default=".", help="CSV directory for --argv-for")
    ap.add_argument("--verify-logs", action="store_true",
                    help="check every suite .BLG exists and its header matches the table")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    if not (args.list or args.evaluate or args.argv_for or args.verify_logs):
        ap.error("nothing to do — pass --list, --evaluate, --argv-for or --verify-logs")

    index = suite_index()
    rc = 0

    if args.list:
        if args.json:
            print(json.dumps(REPLAY_SUITE, indent=2))
        else:
            _print_suite()

    if args.verify_logs:
        problems = verify_suite_logs()
        if problems:
            rc = 1
            for p in problems:
                print(f"[suite] MISMATCH {p}", file=sys.stderr)
        else:
            print(f"[suite] all {len(REPLAY_SUITE)} logs present, headers match the table")

    if args.argv_for:
        entry = index.get(args.argv_for)
        if entry is None:
            print(f"[suite] no suite entry for {args.argv_for}", file=sys.stderr)
            return 2
        print(" ".join(build_sim_argv(entry, args.csv_dir)))

    if args.evaluate:
        log, csv_path = args.evaluate
        entry = index.get(log)
        if entry is None:
            print(f"[suite] no suite entry for {log}", file=sys.stderr)
            return 2
        res = evaluate_replay_csv(entry, csv_path)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"{res['log']}  [{res['mode']}]  "
                  f"{'PASS' if res['passed'] else 'FAIL'}")
            for c in res["checks"]:
                print(f"  {'ok  ' if c['passed'] else 'FAIL'} {c['name']}: {c['detail']}")
            for n in res["notes"]:
                print(f"  note: {n}")
        if not res["passed"]:
            rc = 1

    return rc


if __name__ == "__main__":
    sys.exit(main())
