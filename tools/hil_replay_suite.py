#!/usr/bin/env python3
"""
hil_replay_suite.py — the replay-based scenario class for the Teensy HIL rig.

A curated set of bench logs (logs/*.BLG) is replayed at the firmware through
`tools/hil_plant_sim.py --replay`, and the resulting per-tick CSV is evaluated
here against declarative, firmware-version-aware checks.

All but one entry is a REAL recording written by the firmware's own SD logger.
The exception is SY0001, which is SYNTHETIC — authored by
tools/gen_fu4_replay_log.py because the property it covers (the Idle->Run
setpoint-arrival transient) is unreachable from any recording: every bench run
begins at standstill with the setpoint at or near zero.  The `SY` prefix marks
it, and nothing in it is a measurement.  See docs/HIL_REPLAY_LOGS.md §3f for the
honesty rules such a log has to follow.

WHAT THIS HALF ACTUALLY IS (relabelled 2026-08-30, HIL_FINDINGS "Replay half";
amended the same day when command replay landed): a **bring-up + fault-decision
regression harness**, and — for the entries that opt in — a **controller-reaction**
harness on top of it.

  Entries WITHOUT `replay_commands`: no commander is constructed, so the run never
  reaches State 2; the board brings up, sits in Idle, and `current` is 0.000 A for
  the whole run.  Every current-shape check is then vacuously true on a healthy
  board.  They are retained as "no SPURIOUS command" assertions (the firmware must
  not drive on an injected stimulus it was never commanded to follow) and are
  tagged NOT EXERCISED in the report, never advertised as controller coverage.

  Entries WITH `replay_commands: True`: the log's own recorded v_sp / share_sp are
  replayed as 22-byte Pi command packets at 50 Hz (hil_plant_sim
  --replay-commands), the board goes Idle -> Run, and the drive and share loops
  step against the recorded stimulus.  The current-shape checks then judge the
  LIVE controller's reaction, and a `drive_loop_stepped` check asserts the loop
  actually moved.  STILL OPEN LOOP on the plant side — see the caveat below.

Either way the half also tests: does the fw v22+ staged bring-up complete on this
stimulus, and does the fault machinery make the right LATCH decision on it.

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
`replay_commands` does NOT change this — it adds a second replayed channel (the
commands), it does not close the loop.  Expect a `replay_commands` entry's drive
loop to FIGHT the recorded trajectory wherever the recorded and flashed control
laws differ: that is the stimulus, not a defect.

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
# The same guard, per entry, for the case that VOIDS it (campaign F4 / round-2
# reviewer): a `skip_preamble` entry has NO preamble, so its recorded stimulus
# starts at t = 0 and its first WARM_RESET_GRACE_S seconds sit inside the excluded
# fault window by construction.  ML0217 is safe only because its INIT_FAIL latches
# at ~0.80 s and PERSISTS for the remaining 37.2 s, so the post-grace samples still
# carry it.  An entry whose expected fault were TRANSIENT and early would be
# scored on an empty window and pass on nothing at all.  Any skip_preamble entry
# must therefore assert that its expectation is persistent — see
# _assert_skip_preamble_entries() below, which runs at import.
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
# teensy_controller/teensy_controller.ino:1305
#   #define LIMIT_V_BUS_MAX (V_BUS_NOMINAL + 1.5f)   // 16.0 + 1.5 = 17.5 V
# (TPS61288 hardware OVP is 19 V; the 20 V abs-max above that is V_ABSMAX in
# hil_electrical.py.)  Re-exported for run_hil_suite.py's ring reporting.
LIMIT_V_BUS_MAX_V = 17.5
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

# ── `steps_onto_rail_within` thresholds (FU4, 2026-08-31) ───────────────────
# The Idle->Run setpoint-arrival assertion: after the recorded trajectory starts
# (i.e. after the preamble, when the commander switches to MODE_HYBRID and the
# board leaves Idle), a large commanded setpoint must actually drive the command
# up to the rail — promptly, and once.  This is the POSITIVE half of the FU4
# entry; `returns_off_rail` is the negative half.
#
# 11.0 A is deliberately BELOW RAIL_LEVEL_A (11.9): the question this check asks
# is "did the loop respond at full authority", not "did it touch the clamp to
# four decimals", and pinning it at the rail constant would make the verdict turn
# on the last 0.9 A of a 12 A command.
RESET_STEP_LEVEL_A = 11.0
# The latency budget, worst case, from the preamble boundary:
#     <= 20 ms   the first MODE_HYBRID packet arrives (50 Hz commander tick,
#                hil_plant_sim.py:2958-2975) and moves the board Idle -> Run
#     <= 20 ms   doState1() zeroed v_setpoint on that transition regardless of
#                payload (teensy_controller.ino:5382-5410), so the real setpoint
#                can only arrive on the NEXT packet
#     ~20-40 ms  the freshly reset drive controller rails on the resulting error
#                (the .ino:5399-5403 figure, for any error above ~26 mm/s)
#     +  2 ms    DRIVE_CTRL_TS_US gating, + 1 ms observation sampling
#   = ~83 ms worst case — ASSUMING no packet loss (review L5): each dropped
#     50 Hz UDP command adds 20 ms; the 1.8x headroom absorbs up to ~3 drops.
# 0.15 s is ~1.8x that.  DEVIATION FROM THE FU4 SPEC, which proposed 0.08 s: that
# figure counted the packet latency once and the rail time, but not the Run
# TRANSITION packet, so it lands exactly ON the worst-case budget with no margin —
# a knife-edge threshold of precisely the kind §3 of the doc warns against.  The
# first campaign measures the real value; tighten this then, from data.
RESET_STEP_WITHIN_S = 0.15

# ── Grace window ────────────────────────────────────────────────────────────
# Every fault check below judges observations at t >= this bound only.  A replay
# CSV carries the SAME inherited settle latch every scenario CSV does: from fw v23
# the board warm-resets out of the previous run's ERR_HIL_STALE latch at t ~= 0.5 s,
# so a run that had nothing to do with it opens showing 0x8010 (or 0x8011 / 0xA010
# when its predecessor latched something of its own).  19 of the 26 replays THEN
# IN THE SUITE (27 today) FAILed in the first fw v23 pass on nothing but that.  Value imported from
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
    22:   "fw v22: HIL sequential runs (State-0 injection-link wait gate + closed-loop "
          "staged bring-up under HIL_SIM); no control-semantics change.",
    23:   "fw v23: HIL any-fault run-boundary recovery; no control-semantics change.",
    24:   "fw v24: dynamic Ag105 MPPT threshold (reg 0x02) + charger-path UV backoff "
          "+ a 17-byte observation frame. SAME WHEEL AND SAME DRIVE LAW as v18-v23 "
          "(the round touched the charger, the MPPT pin policy and the HIL frame "
          "only — no encoder constant, no drive coefficient, no change to the "
          "sequencing GUARDS; one new automatic path action (the UV backoff) — see "
          "below), so v_act and every drive-channel comparison carries across "
          "unchanged. The one behaviour a replay could meet is the UV backoff: "
          "V_bus under 12.8 V for 15 ms now CLOSES FC_CHARGE_ENABLE, re-opening "
          "above 13.6 V — the backoff dwell (AG105_CHG_BACKOFF_DWELL_MS, .ino:1764) "
          "is 15 ms, kept under the 20 ms UV_BUS_DWELL_LATCH_MS so it cannot "
          "pre-empt the UV latch. It can only close a path that is already open, "
          "and the UV-collapse stimuli replay with charge_goal 0, so no entry's "
          "expectations move. THE FLASHED TARGET.",
}

# The firmware version currently flashed / targeted by this suite.
# 21 -> 23 (2026-08-30): never bumped when fw v22 (HIL sequential runs, closed-loop
# staged bring-up under HIL_SIM) and fw v23 (any-fault run-boundary recovery)
# shipped. Both are load-bearing for this suite — the whole replay half now depends
# on the v22 staged bring-up completing and on the v23 between-run recovery — so a
# report claiming "fw v21" was misdescribing what it ran against. Consumers checked:
# run_hil_suite.py uses it for the report header's firmware expectation only
# (meta["target_fw"], rendered in REPORT.md); COMPARABLE_FW_MIN (18) is a SEPARATE
# constant and is unchanged, so no entry's conformance/stability classification
# moves. FW_DELTA_NOTES gains v22/v23 rows below.
# 23 -> 24 (2026-09-01): fw v24 is flashed (dynamic Ag105 MPPT threshold + the
# 17-byte observation frame).  This constant feeds the REPORT header's firmware
# expectation only; COMPARABLE_FW_MIN stays 18 because v24 changed no encoder
# constant and no drive coefficient, so no entry's conformance/stability
# classification moves.
TARGET_FW_VERSION = 24
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
#   replay_commands  True = ALSO replay this log's recorded v_sp / share_sp as
#                  22-byte Pi command packets (--replay-commands), so the board
#                  reaches Run and both loops step. MIRRORED in build_sim_argv().
#
# ── Deciding `replay_commands` (2026-08-30) ─────────────────────────────────
# Three rules, applied per entry and stated in each entry's comment:
#
#  1. FAULT-PATH PURITY. An entry whose point is a fault DECISION (the UV pair
#     TP0010/TP0053, ML0217's INIT_FAIL, TP0178/TP0201's must-NOT-latch) stays
#     command-free. Its verdict must not be contaminated by a second stimulus, and
#     for the clamped UV pair (i_fc_clamp_a) commands could change the outcome
#     outright. These carry an explicit `replay_commands: False`.
#  2. THE RECORDED v_sp MUST BE REAL. The 'T'/'W' State-98 profiles command
#     CURRENT directly, never velocity: TP0010/0053/0170/0171/0176/0178/0201/0210,
#     WP0097 and WP0197 all record v_sp IDENTICALLY 0 (measured, 2026-08-30).
#     Replaying that commands nothing — the firmware's V_SP_ZERO_THRESH cutoff
#     yields 0 A — so `drive_loop_stepped` would FAIL on a stimulus that never
#     existed. Their share_sp axis IS live, but the Pi packet's share setpoint
#     alone does not move the motor, so there is nothing for a current-shape check
#     to judge. These stay command-free too.
#  3. THE ENTRY'S OWN EXPECTATION MUST SURVIVE IT. ML0144 asserts
#     `near_zero_current`; its recorded v_sp is nonzero for 3845 rows, so
#     replaying it would drive the motor and contradict the entry's own claim.
#     Command-free.
#
# ── AND CHECK THE SHARE AXIS, WHICH ACTUATES (L6, 2026-08-30) ───────────────
# `share_sp` is not a passive number: updateShareSetpointCutoff() (.ino:249-258)
# latches the STARVED CHANNEL OFF THE BUS — driving FC_BUS_ENABLE or
# BT_BUS_ENABLE — and FREEZES the share controller whenever the SETPOINT leaves
# [DROOP_R_MIN, DROOP_R_MAX] = [0.15, 0.85]. Replaying such a setpoint therefore
# commands a real switch transition, not just a ratio. Measure the recorded range
# before opting an entry in, and call it out in the entry when it leaves the band.
# Measured across the 14 opt-in entries (2026-08-30): thirteen stay inside it
# (0.500 constant, or 0.300-0.700 for the 'Y' profiles). ONE does not — ML0203,
# whose recorded share_sp sweeps the full 0.000-1.000 and so exercises the cutoff
# in both directions; see its entry. That is correct firmware behaviour on a
# genuinely out-of-band setpoint and none of ML0203's checks read switch state, so
# it is documented rather than refused — but an entry whose checks DID read
# switch_state, or whose purpose were a bus/sequencing decision, would have to
# weigh the cutoff as a second stimulus under rule 1.
#
# Everything else with a live recorded v_sp opts IN, and gains a
# `drive_loop_stepped` check ordered BEFORE its motor-response checks.
#
# ── A FOURTH BUCKET: THE COMMAND IS THE WHOLE STIMULUS (FU4, 2026-08-31) ────
# SY0001 is not covered by rules 1-3, which all decide whether a RECORDED
# trajectory should ALSO carry commands. SY0001's rails are constant by
# construction and assert nothing; its entire stimulus is the recorded v_sp, so
# `replay_commands: True` is MANDATORY there, not a judgement call — without the
# flag the entry injects a flat healthy bus and tests nothing at all. Rule 2 is
# satisfied trivially (the recorded v_sp is real and was authored to be), rule 1
# does not apply (no fault decision), and rule 3 is satisfied because every check
# on the entry presumes the loop is running. Any future SYNTHETIC entry inherits
# this: a generated log whose rails are nominal placeholders MUST replay commands
# or it is a 5-second run of nothing.
#
# ── WHY `no_sustained_rail` IS ABSENT FROM THIS HALF (FU5, 2026-08-31) ──────
# It is a deliberate omission, not a threshold that was quietly dropped because
# entries kept failing it. `no_sustained_rail` asserts that no single rail
# episode outlasts SUSTAINED_RAIL_S (1.0 s) — a windup symptom ON A CLOSED LOOP,
# where a healthy controller drives the error down and comes off the rail.
# Replay is OPEN LOOP: the injected `v_actual` cannot respond to the command, so
# a correct controller facing a standing error is SUPPOSED to sit on the rail
# for as long as the recorded trajectory keeps that error in front of it.
# Measured, round-1 campaign 20260831_000518: YP0166 holds a rail for 1.217 s
# with nothing wrong. Applying the check here would fail correct behaviour and
# the only way to keep it green would be to inflate the threshold until it
# asserted nothing — the classic fitted-threshold failure. The genuine windup
# question is instead covered by `returns_off_rail` (does the command RELEASE
# once the error goes away) and by the BLG `u_unsat` conditioning trace on
# hardware runs. The check kind stays in CHECK_KINDS for the scenario half and
# for any future closed-loop harness.
REPLAY_SUITE = [
    # ── CONFORMANCE — current wheel + control law (fw v18/v19) ───────────────
    {
        # ⚠️ THE ONLY SYNTHETIC ENTRY IN THE SUITE. logs/SY0001.BLG is AUTHORED
        # by tools/gen_fu4_replay_log.py, not recorded on hardware; the `SY`
        # prefix exists to keep it distinguishable from the ML/TP/WP/YP/PS
        # recordings it sits beside in logs/. Nothing in it is a measurement and
        # nothing in it may be cited as one.
        "log": "SY0001", "path": "logs/SY0001.BLG", "mode": "conformance",
        "fw_version": 23, "blg_version": 3,
        "classification": "SYNTHETIC — Idle->Run setpoint-arrival transient "
                          "(FU4): v_sp held at 2.0 m/s from record 0, released "
                          "to 0.0 at log t = 1.5 s, v_actual pinned at 0",
        "why":
            "The one operating condition no recorded log covers. doState1() "
            "zeroes v_setpoint on the Idle->Run transition UNCONDITIONALLY, "
            "ignoring the triggering packet's payload "
            "(teensy_controller.ino:5382-5410), so a large setpoint can only "
            "reach a freshly reset drive controller on the SECOND post-reset "
            "command packet, <= 20 ms later. Every bench recording in logs/ "
            "starts at standstill with the setpoint at or near zero, so "
            "replaying one delivers no such step and the transient is never "
            "exercised. A log holding 2.0 m/s from record 0 delivers it "
            "STRUCTURALLY — the firmware's own zeroing supplies the step edge, "
            "so nothing here has to be timed against an instant the host cannot "
            "observe. 2.0 m/s is ~77x the ~26 mm/s error at which the drive "
            "controller's 454.4 A/(m/s) LF gain rails the command, and inside "
            "the 0.5-3.0 m/s range the rest of the suite replays. The release "
            "leg exists so the entry can assert the command comes back OFF the "
            "rail against a DETERMINISTIC bound — with v_actual pinned at 0, "
            "dropping v_sp to 0 collapses the error through V_SP_ZERO_THRESH "
            "(.ino:8975), a zero-cutoff rather than a settling transient replay "
            "could not supply. CONFORMANCE means the usual thing here and no "
            "more: fw v23 is the flashed target, so no wheel/law caveat "
            "applies, but the log carries NO recorded response (I_cmd is 0.0 on "
            "every record, because a board holding v_act at exactly 0 while "
            "commanding 12 A is physically impossible) — the response under "
            "test is entirely the live board's, and any recorded-vs-observed "
            "overlay of this entry is meaningless by construction.",
        # DE-PROVISIONALIZED 2026-08-31 (ledger fix queue) — the entry has now
        # run. Campaign 20260831_191509 measured the rail step at 28.3 ms
        # (results.json `steps_onto_rail_within`: the rail edge at t = 2.528 s
        # against the t = 2.500 s stimulus start; DI-LOW-4 — the 27.92 ms this
        # line used to quote was an intermediate figure, and the 5.3x-margin
        # statement below is unchanged by the correction)
        # against the 150 ms budget (5.3x margin) and drive activity at 59.14 %
        # of the recorded window (predicted ~0.60). `drive_min_frac` is set from
        # that measurement below; RESET_STEP_WITHIN_S is DELIBERATELY held at
        # 0.15 s for one more campaign before tightening toward the ~0.06 s the
        # single datapoint suggests — one run does not establish the spread, and
        # the FU5 precedent is that a budget-derived bound stays until a
        # distribution replaces it, not until a first sample lands under it.
        "provisional": False,
        # MANDATORY, not a rule-1/2/3 judgement — see the fourth bucket in the
        # decision comment above. The recorded v_sp IS the entire stimulus; the
        # rails are constant nominals that assert nothing.
        "replay_commands": True,
        "checks": [
            {"kind": "no_fault", "name": "no_fault"},
            # Ordered before the motor-response checks, per the drive_loop_stepped
            # convention: if the commands never reached the board, the reader sees
            # that cause before three downstream checks report on a flat zero.
            # FU3: measured 0.5914 of the recorded window over threshold
            # (campaign 20260831_191509 — the first run of this entry, and within
            # 1.4 % of the ~0.60 predicted from the 1.5 s arrival leg of a 2.5 s
            # recorded window); floor set at ~half that, as every other opted-in
            # entry's is.
            {"kind": "drive_loop_stepped", "name": "drive_loop_stepped",
             "drive_min_frac": 0.30},
            # The positive half of the FU4 assertion. after_s is deliberately NOT
            # set: it defaults to data.preamble_s (2.5 s here), which is the same
            # bound everything else in the module resolves through
            # entry_preamble_s() instead of hard-coding.
            {"kind": "steps_onto_rail_within", "name": "steps_onto_rail_within",
             "level_a": RESET_STEP_LEVEL_A, "within_s": RESET_STEP_WITHIN_S},
            {"kind": "bounded_current", "name": "bounded_current"},
            # The negative half. Window arithmetic, because it is tight: the
            # release is at log t = 1.5 s = sim t = 4.0 s and the log ends at sim
            # t = 5.0 s, so OFF_RAIL_WITHIN_S (1.0 s) lands exactly ON the end of
            # the recorded window. That is sufficient and not marginal — the
            # V_SP_ZERO_THRESH cutoff is a branch, not a decay, so the observed
            # release is a few ms, not a few hundred — but any future shortening
            # of the release leg breaks it. Lengthen the leg, not the threshold.
            {"kind": "returns_off_rail", "name": "returns_off_rail",
             "level_a": OFF_RAIL_LEVEL_A, "within_s": OFF_RAIL_WITHIN_S},
        ],
        # NOT given a share_loop_actuated check: the authored share_sp is a
        # constant 0.5, so the MDAC ratio span is ~0 by construction and the
        # check would fail on a stimulus that was deliberately never applied.
        # The share axis is not what this entry is for.
    },
    {
        "log": "ML0203", "path": "logs/ML0203.BLG", "mode": "deviation",
        "fw_version": 18, "blg_version": 6,
        "classification": "'V' velocity run on the 90-slot wheel whose recorded "
                          "I_fc peaks at 2.11 A — above LIMIT_I_FC_MAX",
        "why": OC_FC_RECLASS_WHY % ("ML0203", 2.11),
        "provisional": False,
        # Rule 2 satisfied (32581 rows of nonzero recorded v_sp) and rule 1 does
        # not apply: OC_FC latches off the INJECTED I_fc, which command replay
        # cannot touch. Measured 2026-08-30: the crossing is at log t=33.548s of a
        # 43.8s log, so the loop has ~31s of Run before the latch — the
        # drive_loop_stepped window is not tight.
        #
        # L6 — THE ONE OPT-IN ENTRY WHOSE SHARE AXIS ACTUATES. Its recorded
        # share_sp sweeps the FULL 0.000-1.000 (measured 2026-08-30), so replaying
        # it drives the setpoint outside [DROOP_R_MIN, DROOP_R_MAX] = [0.15, 0.85]
        # in BOTH directions and updateShareSetpointCutoff() (.ino:249-258) latches
        # the starved channel off the bus and freezes the share controller. That is
        # CORRECT firmware behaviour on a genuinely recorded out-of-band setpoint,
        # and none of this entry's three checks reads switch_state, so it is
        # accepted and DECLARED rather than refused. Two things to know when reading
        # the trace: switch_state will show FC_BUS/BT_BUS transitions no other
        # replay entry produces, and the share controller is frozen for those
        # stretches. Neither affects oc_fc_latched — the OC comparison is against
        # the INJECTED I_fc, which command replay cannot touch.
        #
        # FU2 (2026-08-31) — WHAT THAT ACTUATION MEASURED, so a reader does not
        # rediscover it as an alarm. Round-1 campaign 20260831_000518:
        # switch_transitions = 222 for this entry against 0-50 for every other
        # replay, i.e. 3 FC-open and 107 BT-open events. The 106-event bulk is
        # CHATTER, and its mechanism is understood: under OPEN-LOOP replay the
        # share PI integrates against an error it can never null, winds to the
        # rail, and drives the setpoint back and forth across the
        # DROOP_R_MIN/DROOP_R_MAX boundary — so the cutoff opens and re-closes.
        # That is an ACCEPTED RESIDUAL of the fw v6-era open-loop share windup,
        # not a firmware defect and not a regression: on hardware the loop closes
        # and the setpoint does not oscillate across the boundary. The count is
        # now in results.json/REPORT.md via ReplayCsv.metrics() so it is visible
        # rather than silent; a LARGE change in it is the thing worth looking at.
        "replay_commands": True,
        "checks": [
            {"kind": "fault_latched", "name": "oc_fc_latched",
             "bit": FAULT_OC_FC, "require_stimulus": True},
            {"kind": "share_loop_actuated", "name": "share_loop_actuated",
                    # FU1: this entry's recorded share_sp varies over
                    # [0.000, 1.000], and the MDAC ratio r = BT/(FC+BT)
                    # measured a span of 0.699 (round-1 campaign
                    # 20260831_000518) against the 0.20 floor.
                    # ACTUATION ONLY - see check_share_loop_actuated:
                    # open-loop replay winds the share PI regardless,
                    # so setpoint TRACKING is deliberately not asserted.
                    },
                   {"kind": "drive_loop_stepped", "name": "drive_loop_stepped",
                    # FU3: measured 0.696 of the recorded window over
                    # threshold (round-1 campaign 20260831_000518);
                    # floor set at half that.
                    "drive_min_frac": 0.35},
            {"kind": "bounded_current", "name": "bounded_current"},
        ],
    },
    {
        "log": "YP0196", "path": "logs/YP0196.BLG", "mode": "conformance",
        "fw_version": 18, "blg_version": 6,
        "classification": "'Y' combined drive-cycle + power-share profile",
        "why": "Exercises both loops' stimulus together on the current law.",
        "provisional": False,
        # 'Y' records BOTH axes live (30697 nonzero v_sp rows, 19678 rows with
        # share_sp off 0.5) — the strongest command-replay candidate in the suite,
        # and the only class where the drive and share setpoints move together.
        "replay_commands": True,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "share_loop_actuated", "name": "share_loop_actuated",
                    # FU1: this entry's recorded share_sp varies over
                    # [0.300, 0.700], and the MDAC ratio r = BT/(FC+BT)
                    # measured a span of 0.695 (round-1 campaign
                    # 20260831_000518) against the 0.20 floor.
                    # ACTUATION ONLY - see check_share_loop_actuated:
                    # open-loop replay winds the share PI regardless,
                    # so setpoint TRACKING is deliberately not asserted.
                    },
                   {"kind": "drive_loop_stepped", "name": "drive_loop_stepped",
                    # FU3: measured 0.881 of the recorded window over
                    # threshold (round-1 campaign 20260831_000518);
                    # floor set at half that.
                    "drive_min_frac": 0.44},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "WP0197", "path": "logs/WP0197.BLG", "mode": "conformance",
        "fw_version": 18, "blg_version": 6,
        "classification": "'W' combined current + power-share profile",
        "why": "The current-axis twin of 'Y' — encoder-less share-loop stimulus.",
        "provisional": False,
        # RULE 2: 'W' is the CURRENT-mode twin, so its recorded v_sp is
        # IDENTICALLY 0 across all 34609 rows (measured 2026-08-30) — the motor
        # axis was commanded as amps by the State-98 profile, which the 22-byte Pi
        # packet cannot express. Replaying it would command nothing and
        # drive_loop_stepped would fail on an absent stimulus.
        "replay_commands": False,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "TP0210", "path": "logs/TP0210.BLG", "mode": "conformance",
        "fw_version": 19, "blg_version": 6,
        "classification": "'T' share sweep on the fw v19 handoff-slew build",
        "why": "Most recent share-sweep stimulus; nearest to the flashed target.",
        "provisional": True,
        # RULE 2: a 'T' share sweep records v_sp identically 0 (13107 rows,
        # measured 2026-08-30). Its share_sp axis IS live, but the share setpoint
        # alone does not move the motor, so there would be nothing for a
        # current-shape check to judge.
        "replay_commands": False,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        # RECLASSIFIED conformance -> deviation (2026-08-30, HIL_FINDINGS 'Replay
        # half' Class B).  The log was RECORDED WITH A DARK BUS — V_bus ~= 0 for
        # all 38 s — so it was never a soak case for anything: replayed, the
        # firmware's staged bring-up cannot pass P0 and times out at
        # PRECHARGE_TIMEOUT_MS into FAULT_INIT_FAIL (.ino:8762-8765).  That is
        # correct firmware behaviour and now the asserted expectation.
        #
        # REPLAYS RAW — `skip_preamble` (H2, 2026-08-30).  The first version of this
        # entry kept the synthetic preamble, and that made its own expectation
        # UNREACHABLE: the board completed bring-up on the healthy preamble rails and
        # then met the dark trajectory as a RUNNING board, which latches UV_BUS at
        # ~t=2.52 s.  FAULT_INIT_FAIL is raised ONLY by busBringupTick()'s phase
        # timeouts (.ino:8762-8765, :8784-8786), i.e. only from State 0's bring-up
        # machine — a running board can never produce it.  Replaying raw restores the
        # genuine cold-boot-into-darkness test.  ML0217 is a modern BLG v6 with all
        # rail fields present, so it needs no absent-rail substitution and loses
        # nothing by skipping the preamble.
        #
        # ⚠️ WHICH GATE FAILS — IT IS P0, AND THE ORIGINAL RECORD IS RESTORED.
        #
        # HISTORY, because this statement has now been reversed twice and a
        # reader deserves to know which way is settled.  The block originally
        # said P0 (PRECHARGE_TIMEOUT_MS 300 ms, .ino:1466).  The 20260831_191509
        # fix round overturned that to P1 (BUS_CHARGE_TIMEOUT_MS 800 ms,
        # .ino:1381) by reading an ABSOLUTE latch timestamp of 0.8015 s — and
        # that reasoning was wrong, as campaign 20260831_222036's replay audit
        # (F1) proved.  Two independent reasons:
        #   1. THE FRAME WAS WRONG.  Bring-up phase timeouts are measured from
        #      `bringupPhaseStart`, re-stamped on the State-0 entry, not from
        #      the sim clock's zero.  In this campaign the board enters State 0
        #      at t = 0.5001 s (the fw v23 run-boundary warm reset clearing the
        #      predecessor's latch) and latches at t = 0.8014 s: ELAPSED
        #      301.3 ms — P0's 300 ms gate, to 0.4 %.  Campaign 20260831_191509
        #      gives 301.1 ms by the same arithmetic, so the two campaigns never
        #      disagreed; only the frame did.
        #   2. P1 IS UNREACHABLE HERE ANYWAY.  P1 is entered only once phase 0
        #      passes, and phase 0's gate is the bus reaching V_PRECHARGE_MIN —
        #      which a dark bus (V_bus ~ 0 for all 38 s) can never meet.  The
        #      run cannot get past P0 to time out on P1.
        # And the absolute bound could not have caught either error: both
        # candidate gates land past 0.8 s absolute on a run whose State-0 entry
        # is itself at ~0.5 s, so `not_before_s: 0.5` discriminated NOTHING.
        # The check below pins the ELAPSED time instead
        # (`latch_elapsed_band_s`), which is the frame the firmware measures in.
        #
        # OBSERVABILITY OF THE LATCH (verified): INIT_FAIL fires at ~0.80 s,
        # i.e. BEFORE the 2.0 s grace bound.  It is still scored,
        # because State 99 is latched and the simulator keeps streaming — no run
        # boundary, so the fw v23 warm recovery never arms — and fault_flags
        # therefore reads 0xA000 on every post-grace sample.  The grace filter ORs
        # over samples, not over edges, so a persistent bit survives it; the check
        # additionally prints the whole-run first-observation time so the ~0.80 s
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
               "a working one. Bring-up P0 never sees V_PRECHARGE_MIN, so "
               "PRECHARGE_TIMEOUT_MS (300 ms) expires and FAULT_INIT_FAIL "
               "latches (.ino:8762-8765).",
        "provisional": True,
        "skip_bringup_gate": True,
        "skip_preamble": True,
        # RULE 1 (fault-path purity), explicit: this entry's whole verdict is a
        # bring-up FAULT DECISION on a dark bus. A second stimulus over it proves
        # nothing and could only confuse the attribution. Its recorded v_sp is
        # identically 0 in any case (33756 rows), so rule 2 refuses it too.
        "replay_commands": False,
        # Required alongside skip_preamble (see _assert_skip_preamble_entries()):
        # this entry's first 2.0 s of RECORDED stimulus sit inside the excluded
        # fault window, so it is only scorable because INIT_FAIL latches at ~0.80 s
        # and HOLDS for the remaining 37.2 s. Measured on hardware, campaign
        # 20260830_203006; absolute latch 0.8015 s in campaign 20260831_191509
        # and 0.8014 s in 20260831_222036 — but the MECHANISM is the elapsed
        # figure, see the P0-vs-P1 correction above.
        "persistent_fault": True,
        "checks": [{"kind": "fault_latched", "name": "init_fail_latched",
                    "bit": FAULT_INIT_FAIL, "require_stimulus": False,
                    # WHICH BRING-UP GATE, asserted in the firmware's own frame.
                    # FAULT_INIT_FAIL is raised by BOTH of busBringupTick()'s
                    # phase timeouts, so a bare latch check cannot say whether
                    # the dark bus failed P0's precharge gate
                    # (PRECHARGE_TIMEOUT_MS 300 ms, .ino:1466) or P1's charge
                    # gate (BUS_CHARGE_TIMEOUT_MS 800 ms, .ino:1381) — two
                    # different findings about the firmware, one bit.
                    #
                    # MEASURED, ELAPSED FROM THE STATE-0 ENTRY (the anchor at
                    # which the firmware itself re-stamps `bringupPhaseStart`):
                    #     campaign 20260831_222036   301.3 ms  (0.8014 - 0.5001)
                    #     campaign 20260831_191509   301.1 ms
                    # Both are P0's 300 ms gate to within 0.5 %.
                    #
                    # BAND [0.20, 0.45] s brackets 300 ms by -33 % / +50 % —
                    # orders of magnitude more than the 0.2 ms of campaign-to-
                    # campaign spread, and more than any plausible staging
                    # phase — while EXCLUDING P1's 800 ms outright, which is the
                    # whole point. The floor is not decoration: it excludes a
                    # latch raised before any bring-up gate could have expired.
                    "latch_elapsed_band_s": (0.20, 0.45),
                    # State 0 = Init. Written out rather than defaulted so the
                    # anchor is visible beside the band it scales.
                    "elapsed_from_state": 0},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "YP0214", "path": "logs/YP0214.BLG", "mode": "conformance",
        "fw_version": 19, "blg_version": 6,
        "classification": "'Y' combined profile on fw v19",
        "why": "Combined-profile stimulus with the handoff slew in the recording.",
        "provisional": True,
        # Same 'Y' class as YP0196/YP0152/YP0166: both command axes live
        # (30719 nonzero v_sp rows, 19697 rows with share_sp off 0.5).
        #
        # ⚠️ INCIDENTAL SHARE-CUTOFF TRANSITIONS ARE NOT SCORED here either —
        # this entry's count swung 8 -> 0 across the same two campaigns. Full
        # reasoning, and where cutoff coverage actually lives, at YP0166 below.
        "replay_commands": True,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "share_loop_actuated", "name": "share_loop_actuated",
                    # FU1: this entry's recorded share_sp varies over
                    # [0.300, 0.700], and the MDAC ratio r = BT/(FC+BT)
                    # measured a span of 0.552 (round-1 campaign
                    # 20260831_000518) against the 0.20 floor.
                    # ACTUATION ONLY - see check_share_loop_actuated:
                    # open-loop replay winds the share PI regardless,
                    # so setpoint TRACKING is deliberately not asserted.
                    },
                   {"kind": "drive_loop_stepped", "name": "drive_loop_stepped",
                    # FU3: measured 0.879 of the recorded window over
                    # threshold (round-1 campaign 20260831_000518);
                    # floor set at half that.
                    "drive_min_frac": 0.44},
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
        # A clean 'V' step with 8356 rows of nonzero recorded v_sp: replaying it
        # turns three previously-vacuous current-shape checks into a real
        # assertion about the flashed law's reaction to a clean step.
        "replay_commands": True,
        "checks": [
            {"kind": "no_fault", "name": "no_fault"},
            {"kind": "drive_loop_stepped", "name": "drive_loop_stepped",
                    # FU3: measured 0.686 of the recorded window over
                    # threshold (round-1 campaign 20260831_000518);
                    # floor set at half that.
                    "drive_min_frac": 0.34},
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
        # Same class as ML0146 (7261 rows of nonzero recorded v_sp).
        "replay_commands": True,
        "checks": [
            {"kind": "no_fault", "name": "no_fault"},
            {"kind": "drive_loop_stepped", "name": "drive_loop_stepped",
                    # FU3: measured 0.671 of the recorded window over
                    # threshold (round-1 campaign 20260831_000518);
                    # floor set at half that.
                    "drive_min_frac": 0.34},
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
        # Same reasoning as ML0203: 28826 rows of nonzero recorded v_sp, and the
        # OC crossing is at log t=17.979s of a 38.6s log, so ~18s of Run precede
        # the latch. OC_FC comes off the injected I_fc, untouched by commands.
        "replay_commands": True,
        "checks": [{"kind": "fault_latched", "name": "oc_fc_latched",
                    "bit": FAULT_OC_FC, "require_stimulus": True},
                   {"kind": "drive_loop_stepped", "name": "drive_loop_stepped",
                    # FU3: measured 0.404 of the recorded window over
                    # threshold (round-1 campaign 20260831_000518);
                    # floor set at half that.
                    "drive_min_frac": 0.20},
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
        # 11814 rows of nonzero recorded v_sp. TIGHTEST of the three OC entries:
        # the crossing is at log t=2.335s, so the drive loop has ~2.3s of Run
        # before the latch (~2300 samples at 1 kHz against the 50-sample
        # drive_loop_stepped floor — still ~45x margin, but this is the entry to
        # look at first if drive_loop_stepped ever starts failing here).
        "replay_commands": True,
        "checks": [{"kind": "fault_latched", "name": "oc_fc_latched",
                    "bit": FAULT_OC_FC, "require_stimulus": True},
                   {"kind": "drive_loop_stepped", "name": "drive_loop_stepped",
                    # FU3: measured 0.084 of the recorded window over
                    # threshold (round-1 campaign 20260831_000518);
                    # floor set at half that.
                    "drive_min_frac": 0.04},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "TP0170", "path": "logs/TP0170.BLG", "mode": "conformance",
        "fw_version": 16, "blg_version": 6,
        "classification": "share sweep, share_sp = 0.5",
        "why": "The balanced-share operating point of the first genuine closed-loop "
               "share dataset.",
        "provisional": False,
        # RULE 2: 'T' share sweep — recorded v_sp is identically 0 (13125 rows).
        "replay_commands": False,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "TP0176", "path": "logs/TP0176.BLG", "mode": "conformance",
        "fw_version": 16, "blg_version": 6,
        "classification": "share sweep at the FC rail (FC-only for 43–45 % of the run)",
        "why": "The share-rail extreme: one source carries the bus for a long stretch.",
        "provisional": False,
        # RULE 2: 'T' share sweep — recorded v_sp is identically 0 (13122 rows).
        "replay_commands": False,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "YP0152", "path": "logs/YP0152.BLG", "mode": "conformance",
        "fw_version": 14, "blg_version": 5,
        "classification": "first 'Y' combined profile on the Youla drive controller",
        "why": "Combined-profile representative from the fw v14 era.",
        "provisional": False,
        # 'Y' class, both axes live (30464 nonzero v_sp rows, 19593 off-0.5
        # share_sp rows).
        "replay_commands": True,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "share_loop_actuated", "name": "share_loop_actuated",
                    # FU1: this entry's recorded share_sp varies over
                    # [0.300, 0.700], and the MDAC ratio r = BT/(FC+BT)
                    # measured a span of 0.400 (round-1 campaign
                    # 20260831_000518) against the 0.20 floor.
                    # ACTUATION ONLY - see check_share_loop_actuated:
                    # open-loop replay winds the share PI regardless,
                    # so setpoint TRACKING is deliberately not asserted.
                    },
                   {"kind": "drive_loop_stepped", "name": "drive_loop_stepped",
                    # FU3: measured 0.877 of the recorded window over
                    # threshold (round-1 campaign 20260831_000518);
                    # floor set at half that.
                    "drive_min_frac": 0.44},
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
        # THE flagship command-replay entry: 44664 rows of nonzero recorded v_sp
        # over 56.6s, containing the ~90 saturation entries/exits this entry
        # exists for. Its returns_off_rail / no_rail_limit_cycle checks were the
        # most misleading vacuous passes in the half — the H6 anti-windup
        # regression asserted nothing at all while the command sat at 0 A. With
        # commands replayed they judge the live general-Hanus behaviour.
        "replay_commands": True,
        "checks": [
            {"kind": "no_fault", "name": "no_fault"},
            {"kind": "drive_loop_stepped", "name": "drive_loop_stepped",
                    # FU3: measured 0.899 of the recorded window over
                    # threshold (round-1 campaign 20260831_000518);
                    # floor set at half that.
                    "drive_min_frac": 0.45},
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
        # ⚠️ CLASSIFICATION CORRECTED 2026-08-31 (ledger fix queue).  This
        # entry used to read "10 ms dwell (half the 20 ms latch)", carried over
        # from the original bench note.  THAT DID NOT SURVIVE REPLAY: measured
        # over the recorded window, the floor is 12.1489 V — it never crosses
        # LIMIT_V_BUS_MIN 12.0 V at all, the leaky dwell integrator accumulates
        # 0.0 ms, and the sub-12.15 V excursion itself is only 1-3 ms wide.  The
        # "10 ms dwell" figure described a sub-threshold sag that does not exist
        # in this trace; do not reinstate it.
        "classification": "handoff bus sag to 12.1489 V — 0.1489 V (1.24 %) ABOVE "
                          "LIMIT_V_BUS_MIN, so 0.0 ms of accumulated UV dwell",
        "why": "The NEGATIVE UV case: the recorded dip must NOT latch UV_BUS. Pairs "
               "with the legacy UV pair, which must. ⚠️ The must-NOT-latch half is "
               "VACUOUS on this stimulus by construction (the floor stays above the "
               "limit, so no board could latch) — `v_bus_min_in_band` is what makes "
               "the entry bite, by pinning the floor into the near-miss band.",
        "provisional": False,
        # RULE 1 (fault-path purity) AND rule 2: this entry's verdict is a
        # must-NOT-latch fault DECISION, and its 'T'-profile recording has v_sp
        # identically 0 (12960 rows) anyway.
        "replay_commands": False,
        "checks": [
            {"kind": "no_fault", "name": "no_fault"},
            {"kind": "fault_not_latched", "name": "uv_not_latched", "bit": FAULT_UV_BUS},
            # THE DE-VACUATION PIN (required at import by
            # _assert_uv_not_latched_entries).  Band from the MEASURED floor,
            # campaign hil_report_20260831_191509: 12.1489 V.
            #   lower  12.0  = LIMIT_V_BUS_MIN, EXCLUSIVE — the moment the
            #          recorded floor reaches it this stops being a
            #          must-NOT-latch case and the entry needs re-deriving.
            #          Margin today: +0.1489 V (1.24 %).
            #   upper  12.30, INCLUSIVE — 0.151 V of headroom above the measured
            #          floor, i.e. as much room above as the limit is below, so
            #          ordinary decode/rescale noise cannot trip it while a
            #          stimulus that stopped being a near miss does.
            {"kind": "v_bus_min_in_band", "name": "uv_margin_pinned",
             "min_v": 12.0, "max_v": 12.30},
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
        # The canonical limit-cycle deviation, and the check that most needed a
        # live command: no_rail_limit_cycle on a flat-zero series proves nothing.
        # 2303 rows of nonzero recorded v_sp over a 4.8s log.
        "replay_commands": True,
        "checks": [
            {"kind": "drive_loop_stepped", "name": "drive_loop_stepped",
                    # FU3: measured 0.543 of the recorded window over
                    # threshold (round-1 campaign 20260831_000518);
                    # floor set at half that.
                    "drive_min_frac": 0.27},
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
        # "The command must stay bounded" is only an assertion if there IS a
        # command: 4017 rows of nonzero recorded v_sp over a 6.5s log.
        "replay_commands": True,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "drive_loop_stepped", "name": "drive_loop_stepped",
                    # FU3: measured 0.699 of the recorded window over
                    # threshold (round-1 campaign 20260831_000518);
                    # floor set at half that.
                    "drive_min_frac": 0.35},
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
        # RULE 3 (the entry's own expectation must survive it): near_zero_current
        # IS this entry's claim, and it is predicated on v_setpoint = 0. The
        # recording carries 3845 rows of NONZERO v_sp, so replaying the commands
        # would legitimately drive the motor and contradict the entry outright.
        # The v_sp != 0 relay would then be reproducible — but that is a DIFFERENT
        # entry with different checks, not this one. Left command-free deliberately;
        # see docs/HIL_REPLAY_LOGS.md if a relay entry is ever added.
        "replay_commands": False,
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
        # The deviation claim here is "the firmware keeps its command bounded on a
        # CORRUPTED velocity" — which needs a command to be meaningful. 5683 rows
        # of nonzero recorded v_sp. The basin fix itself remains untestable
        # open-loop; command replay does not change that, it just makes the
        # bounded-command half real.
        "replay_commands": True,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "drive_loop_stepped", "name": "drive_loop_stepped",
                    # FU3: measured 0.634 of the recorded window over
                    # threshold (round-1 campaign 20260831_000518);
                    # floor set at half that.
                    "drive_min_frac": 0.32},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "ML0164", "path": "logs/ML0164.BLG", "mode": "deviation",
        "fw_version": 16, "blg_version": 6,
        "classification": "x2 ROUNDING basin, locked breakaway-to-stop",
        "why": "Same class as ML0153 with the fw v15 rounding path; same caveat — "
               "the basin fix is in the estimator, which replay bypasses.",
        "provisional": False,
        # Same reasoning as ML0153 (16345 rows of nonzero recorded v_sp).
        "replay_commands": True,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "drive_loop_stepped", "name": "drive_loop_stepped",
                    # FU3: measured 0.706 of the recorded window over
                    # threshold (round-1 campaign 20260831_000518);
                    # floor set at half that.
                    "drive_min_frac": 0.35},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "TP0171", "path": "logs/TP0171.BLG", "mode": "deviation",
        "fw_version": 16, "blg_version": 6,
        "classification": "reset re-seeded INTO the x2 basin (~15 ms recovery)",
        "why": "The reset-into-basin stimulus. Same open-loop caveat as ML0153/0164.",
        "provisional": False,
        # RULE 2, and the reason this entry does NOT join its ML0153/ML0164
        # siblings: TP0171 is a 'T' CURRENT-mode profile, so its recorded v_sp is
        # identically 0 (13131 rows, measured 2026-08-30) even though the estimator
        # stimulus it carries is the same class. Replaying its commands would
        # command nothing.
        "replay_commands": False,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "YP0166", "path": "logs/YP0166.BLG", "mode": "deviation",
        "fw_version": 16, "blg_version": 6,
        "classification": "mid-run v = 0 injection at true 1.49 m/s -> +/-12 A rail pair "
                          "within 12 ms (the fw v17 TOCTOU race)",
        "why": "A full-scale velocity step straight into the ~454 A/(m/s) LF gain. The "
               "modern firmware must produce a BOUNDED transient that comes back off "
               "the rail, and must not fault.",
        "provisional": False,
        # "A BOUNDED transient that comes back off the rail" is the entry's whole
        # claim and needs the loop running to mean anything. 'Y' class: 30723
        # nonzero v_sp rows, 19606 rows with share_sp off 0.5.
        #
        # ⚠️ INCIDENTAL SHARE-CUTOFF TRANSITIONS HERE ARE NOT SCORED, and are not
        # a stable observable (F2, campaign 20260831_191509). This entry's
        # replayed share_sp wanders across DROOP_R_MIN/DROOP_R_MAX, so
        # updateShareSetpointCutoff() opens and closes a bus switch some number
        # of times as a SIDE EFFECT — and the count swung 46 -> 0 between round 4
        # and campaign 20260831_191509 with nothing changed. The boundary
        # crossing depends on where the open-loop share PI's windup happens to
        # sit when the setpoint arrives, which is command-arrival-phase
        # sensitive; a band around it would be fitting noise. Cutoff coverage is
        # DELIBERATE elsewhere — `share-staircase` (cut + restore + four
        # latencies at a designed load) and `ems-y-b00-*` (both channels, both
        # directions) — so nothing is lost by leaving it unscored here. Do not
        # add a transition-count check to this entry without first establishing
        # the distribution across several campaigns.
        "replay_commands": True,
        "checks": [
            {"kind": "no_fault", "name": "no_fault"},
            {"kind": "share_loop_actuated", "name": "share_loop_actuated",
                    # FU1: this entry's recorded share_sp varies over
                    # [0.300, 0.700], and the MDAC ratio r = BT/(FC+BT)
                    # measured a span of 0.546 (round-1 campaign
                    # 20260831_000518) against the 0.20 floor.
                    # ACTUATION ONLY - see check_share_loop_actuated:
                    # open-loop replay winds the share PI regardless,
                    # so setpoint TRACKING is deliberately not asserted.
                    #
                    # ⚠️ THE SPAN IS BIMODAL ON THIS ENTRY — do not band it, and
                    # do not read a move between the two values as a regression
                    # (F3, campaign 20260831_222036, second datapoint).
                    # Measured spans: 0.546/0.550 (campaigns 20260831_000518 /
                    # _222036) and 0.697 (20260831_191509). The two modes have
                    # DIFFERENT MECHANISMS, which is why no single band is
                    # honest:
                    #     ~0.55  the replayed share_sp's own profile rail (the
                    #            recording spans 0.300-0.700, i.e. 0.40 of
                    #            setpoint, which the open-loop PI's windup
                    #            carries a little past);
                    #     ~0.70  a run in which the wandering setpoint also
                    #            REACHED the firmware's cutoff clamp, so the
                    #            MDAC ratio is driven to a rail rather than
                    #            tracking, and the span is the clamp's, not the
                    #            profile's.
                    # Which mode a campaign lands in is decided by the same
                    # command-arrival-phase sensitivity that makes the cutoff
                    # TRANSITION COUNT unstable here (note above) — it is the
                    # same phenomenon read on a different observable. The 0.20
                    # floor is BELOW BOTH modes by a factor of ~2.7, which is
                    # exactly why it is the right assertion for this entry: it
                    # says the loop actuated, and declines to say how far.
                    # Clamp-reaching coverage is DELIBERATE elsewhere —
                    # `share-staircase` and `ems-y-b00-*` — so the bimodality
                    # costs the suite no coverage. (F3's band-vs-doc question is
                    # the operator's; the conservative doc option is in force.)
                    },
                   {"kind": "drive_loop_stepped", "name": "drive_loop_stepped",
                    # FU3: measured 0.887 of the recorded window over
                    # threshold (round-1 campaign 20260831_000518);
                    # floor set at half that.
                    "drive_min_frac": 0.44},
            {"kind": "bounded_current", "name": "bounded_current"},
            {"kind": "returns_off_rail", "name": "returns_off_rail",
             "level_a": OFF_RAIL_LEVEL_A, "within_s": OFF_RAIL_WITHIN_S},
        ],
    },
    {
        "log": "TP0201", "path": "logs/TP0201.BLG", "mode": "deviation",
        "fw_version": 18, "blg_version": 6,
        "classification": "share-rail handoff gap, bus 15.86 -> 12.1853 V",
        # ⚠️ WORDING CORRECTED 2026-08-31 alongside TP0178's (ledger fix queue):
        # the sag stays ABOVE the limit, so there is no dwell to be "inside".
        # Measured floor 12.1853 V, accumulated dwell 0.0 ms.
        "why": "The deepest recorded handoff sag. Its floor is 0.1853 V ABOVE "
               "LIMIT_V_BUS_MIN, so the leaky dwell integrator never accumulates "
               "and the firmware must NOT latch UV. CAVEAT: the fw v19 handoff SLEW "
               "that mitigates the gap acts on the plant, which replay bypasses — "
               "the mitigation is not exercisable open-loop, only the fault "
               "decision is. ⚠️ Like TP0178, the must-NOT-latch half is VACUOUS on "
               "this stimulus; `v_bus_min_in_band` is what makes the entry bite.",
        "provisional": False,
        # RULE 1 (fault-path purity) AND rule 2: a must-NOT-latch fault decision,
        # recorded by a 'T' profile whose v_sp is identically 0 (12961 rows).
        "replay_commands": False,
        "checks": [
            {"kind": "no_fault", "name": "no_fault"},
            {"kind": "fault_not_latched", "name": "uv_not_latched", "bit": FAULT_UV_BUS},
            # THE DE-VACUATION PIN — see TP0178 for the full derivation. Band
            # from the MEASURED floor, campaign hil_report_20260831_191509:
            # 12.1853 V, i.e. +0.1853 V (1.54 %) over LIMIT_V_BUS_MIN. The SAME
            # band as TP0178 deliberately: the two entries are the same claim on
            # two logs whose floors differ by 37 mV, and one band that brackets
            # both is easier to reason about than two nearly-identical ones.
            # Headroom above this floor is 0.115 V.
            {"kind": "v_bus_min_in_band", "name": "uv_margin_pinned",
             "min_v": 12.0, "max_v": 12.30},
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
        # RULE 1, and DELIBERATE for this pair specifically: the entry's whole
        # verdict is a UV fault DECISION on an ALREADY-MODIFIED trajectory
        # (i_fc_clamp_a). A replayed command stream is a second stimulus over that,
        # and driving the motor could change what the board does around the
        # collapse — turning a fault-latch regression into an unattributable
        # result. Its recorded v_sp is identically 0 in any case (12921 rows).
        "replay_commands": False,
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
        # ⚠️ REPEAT CLASS: ±~100 ms, BURST-QUANTIZED — do NOT read a shifted
        # latch instant here as a regression (F2, campaign 20260831_222036).
        # TP0053's collapse is REPETITIVE, not sustained: only 8.3 % of its
        # samples sit under LIMIT_V_BUS_MIN, arriving in short bursts of ~9 ms
        # under / ~51 ms over per ~60 ms cycle (the classification above). The
        # leaky dwell integrator therefore accumulates in steps and crosses
        # UV_BUS_DWELL_LATCH_MS *inside a burst*, so the latch instant SNAPS to
        # whichever burst carries it over — one burst of slack is a ~60 ms move
        # for a stimulus that has not changed at all. Campaign 20260831_222036
        # measured +59 ms against 20260831_191509, one burst period, exactly
        # this quantization.
        # ⚠️ NOT the class TP0010 is in. TP0010's collapse is CONTINUOUS, its
        # dwell crossing is a smooth ramp, and it moved ~0 ms across the same
        # campaign pair — treat ±3 ms as its band and ±~100 ms as this one's.
        # NO CHECK PINS THE INSTANT on either entry (the check asserts the LATCH,
        # not when), so this is a records fix: it exists so the next campaign's
        # analysis does not open a finding on a number that is behaving.
        # RULE 1, same reasoning as TP0010: clamped UV-latch stimulus stays PURE.
        # Recorded v_sp is identically 0 (4585 rows).
        "replay_commands": False,
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
        # RULE 1 and RULE 2. Fault-path entry, and a 'W' CURRENT-mode recording:
        # v_sp is identically 0 across all 14636 rows (measured 2026-08-30), so
        # command replay would command nothing. Its OC crossing is also the
        # tightest in the suite (last 40 ms of the log) — nothing that shifts the
        # time base belongs anywhere near this entry.
        "replay_commands": False,
        "checks": [{"kind": "fault_latched", "name": "oc_fc_latched",
                    "bit": FAULT_OC_FC, "require_stimulus": True},
                   # F4 (campaign 20260831_222036) — the RECLASSIFICATION's own
                   # premise, asserted. This entry left the UV pair because its
                   # dip peaks at 18.65 ms of dwell against the 20 ms latch, so
                   # the bus collapse is a near miss BEHIND an overcurrent, and
                   # the verdict is only attributable while the OC comes first.
                   # MEASURED, campaign 20260831_222036: OC latches at
                   # t=19.4654 s, the injected V_bus first goes under 12.0 V at
                   # t=19.4878 s — a 22.37 ms lead (19 sub-12 V samples, min
                   # 6.12 V).
                   # FLOOR 10 ms = 45 % of the measured lead. Loose on purpose:
                   # the lead is a property of the RECORDING (two fixed events
                   # in one log) and the only things that can move it are a
                   # time-base or clamp change, which would move it by far more
                   # than a millisecond. What must never pass is a lead that has
                   # collapsed or inverted.
                   {"kind": "latch_precedes_uv", "name": "oc_precedes_uv",
                    "bit": FAULT_OC_FC, "min_lead_ms": 10.0},
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


def _assert_skip_preamble_entries():
    """Import-time guard for the case that voids the preamble >= grace assertion.

    Campaign finding F4 (independently found by the round-2 reviewer): the global
    assertion buys nothing for an entry that has NO preamble.  Such an entry's
    recorded stimulus starts at t = 0, so its first WARM_RESET_GRACE_S seconds are
    inside the excluded fault window by construction, and only a PERSISTENT expected
    fault survives to be scored.  ML0217 is safe for exactly that reason and no
    other: INIT_FAIL latches at ~0.80 s and holds for the remaining 37.2 s.

    An entry added later whose expected fault is transient and early would be judged
    on an empty window and PASS on nothing.  So a skip_preamble entry must say, in
    the table, that it knows this: `persistent_fault: True` plus at least one
    `fault_latched` check (a latched fault is persistent by definition — State 99
    does not clear).  Fails loudly at import rather than quietly at score time."""
    for e in REPLAY_SUITE:
        if not e.get("skip_preamble"):
            continue
        log = e.get("log")
        assert e.get("persistent_fault") is True, (
            f"REPLAY_SUITE[{log!r}] sets skip_preamble, which places its first "
            f"{WARM_RESET_GRACE_S:.1f}s of RECORDED stimulus inside the excluded "
            f"fault-scoring window. That is only safe if the expected fault "
            f"PERSISTS past the bound. Declare `persistent_fault: True` (and say "
            f"why in `why`) if it does; if it does not, this entry cannot use "
            f"skip_preamble — it would be scored on an empty window.")
        assert any(c.get("kind") == "fault_latched" for c in e.get("checks", [])), (
            f"REPLAY_SUITE[{log!r}] declares persistent_fault with no "
            f"`fault_latched` check. Persistence is only established by a latch "
            f"(State 99 does not clear); a `no_fault`-style expectation on a "
            f"skip_preamble entry proves nothing about the excluded window.")


def _assert_uv_not_latched_entries():
    """Import-time guard: a must-NOT-latch UV entry must PIN ITS STIMULUS.

    MED (2026-08-31 ledger fix queue).  `fault_not_latched` on FAULT_UV_BUS is
    the one check kind in this module that can be VACUOUSLY TRUE without any
    tag saying so: if the recorded floor never reaches LIMIT_V_BUS_MIN, the
    firmware's dwell integrator accumulates 0.0 ms and no board could fail it.
    Campaign `hil_report_20260831_191509` found exactly that on TP0178 and
    TP0201 — two green ticks asserting nothing.

    The fix is structural rather than per-entry: any entry making the
    must-NOT-latch UV claim must ALSO carry a `v_bus_min_in_band` check, which
    pins the recorded floor into a near-miss band and so fails loudly the day
    the stimulus moves in either direction.  Enforced here so a future UV entry
    cannot be added without the pin.

    Deliberately scoped to FAULT_UV_BUS: it is the only bit whose firmware test
    is a DWELL over a threshold on a rail this CSV carries, and therefore the
    only one whose stimulus can be pinned this way from the trace alone."""
    for e in REPLAY_SUITE:
        checks = e.get("checks", [])
        if not any(c.get("kind") == "fault_not_latched"
                   and int(c.get("bit", 0)) == FAULT_UV_BUS for c in checks):
            continue
        log = e.get("log")
        pins = [c for c in checks if c.get("kind") == "v_bus_min_in_band"]
        assert pins, (
            f"REPLAY_SUITE[{log!r}] claims UV_BUS must NOT latch but does not "
            f"pin its own stimulus. That check is vacuously true whenever the "
            f"recorded V_bus floor stays above LIMIT_V_BUS_MIN "
            f"{LIMIT_V_BUS_MIN_V:.1f} V — which is the case for every such entry "
            f"in the suite today. Add a `v_bus_min_in_band` check with the "
            f"entry's measured floor so a stimulus change fails loudly.")
        for c in pins:
            assert "max_v" in c, (
                f"REPLAY_SUITE[{log!r}]: a `v_bus_min_in_band` check needs an "
                f"explicit `max_v` — the ceiling is what stops the entry "
                f"degenerating into 'any healthy bus also does not latch UV'.")
            assert float(c.get("min_v", LIMIT_V_BUS_MIN_V)) < float(c["max_v"]), (
                f"REPLAY_SUITE[{log!r}]: `v_bus_min_in_band` needs "
                f"min_v < max_v; got {c.get('min_v', LIMIT_V_BUS_MIN_V)!r} and "
                f"{c['max_v']!r}.")


def _assert_check_spec_shapes():
    """Import-time shape guard for the per-check spec fields.

    Cheap, and it catches the failure mode this module is most exposed to: a
    field typed onto the WRONG check kind reads as an assertion and is silently
    ignored, because every check reads its spec with `.get()`."""
    _KNOWN = {
        "no_fault": {"ignore_bits"},
        "fault_latched": {"bit", "require_stimulus", "not_before_s",
                          "latch_elapsed_band_s", "elapsed_from_state"},
        "fault_not_latched": {"bit"},
        "bounded_current": {"limit_a"},
        "no_sustained_rail": {"max_episode_s", "level_a"},
        "no_rail_limit_cycle": {"max_alt_per_s", "level_a"},
        "returns_off_rail": {"level_a", "within_s", "rail_level_a"},
        "near_zero_current": {"max_abs_a"},
        "drive_loop_stepped": {"min_abs_a", "min_samples", "drive_min_frac"},
        "share_loop_actuated": {"min_span", "min_samples"},
        "steps_onto_rail_within": {"level_a", "within_s", "after_s"},
        "v_bus_min_in_band": {"min_v", "max_v"},
        "latch_precedes_uv": {"bit", "min_lead_ms"},
    }
    for e in REPLAY_SUITE:
        log = e.get("log")
        for c in e.get("checks", []):
            kind = c.get("kind")
            assert kind in CHECK_KINDS, (
                f"REPLAY_SUITE[{log!r}]: unknown check kind {kind!r}.")
            extra = set(c) - {"kind", "name"} - _KNOWN.get(kind, set())
            assert not extra, (
                f"REPLAY_SUITE[{log!r}] check {c.get('name')!r} (kind {kind!r}) "
                f"carries field(s) {sorted(extra)} that this kind does not read. "
                f"Every check reads its spec with .get(), so a misplaced field "
                f"is silently ignored rather than rejected — which is exactly "
                f"how an entry comes to look like it asserts more than it does. "
                f"Move the field to a kind that reads it, or add it to "
                f"_assert_check_spec_shapes()._KNOWN if the kind now supports it.")
            # `not_before_s` is only meaningful once a latch time exists.
            if "not_before_s" in c:
                assert float(c["not_before_s"]) > 0.0, (
                    f"REPLAY_SUITE[{log!r}]: `not_before_s` must be positive; a "
                    f"bound at or below 0 asserts nothing.")
            # F1: the elapsed band is a TWO-SIDED mechanism discriminator, so a
            # degenerate or inverted pair would silently stop discriminating.
            if "latch_elapsed_band_s" in c:
                _b = c["latch_elapsed_band_s"]
                assert isinstance(_b, (tuple, list)) and len(_b) == 2, (
                    f"REPLAY_SUITE[{log!r}]: `latch_elapsed_band_s` must be a "
                    f"(lo, hi) pair in seconds; got {_b!r}.")
                assert 0.0 <= float(_b[0]) < float(_b[1]), (
                    f"REPLAY_SUITE[{log!r}]: `latch_elapsed_band_s` needs "
                    f"0 <= lo < hi; got {_b!r}. A one-sided or inverted band "
                    f"cannot separate an EARLIER gate from a LATER one, which "
                    f"is the only thing this bound is for.")
            assert not ("elapsed_from_state" in c
                        and "latch_elapsed_band_s" not in c), (
                f"REPLAY_SUITE[{log!r}]: `elapsed_from_state` names the anchor "
                f"for `latch_elapsed_band_s` and is read by nothing else.")
            # F4: an ordering check without a positive lead asserts only "not
            # strictly after", which every simultaneous-sample case satisfies.
            if kind == "latch_precedes_uv":
                assert float(c.get("min_lead_ms", 0.0)) > 0.0, (
                    f"REPLAY_SUITE[{log!r}]: `latch_precedes_uv` needs a "
                    f"positive `min_lead_ms`; a zero lead passes on a tie, "
                    f"which is the ambiguous case the check exists to refuse.")
                assert any(o.get("kind") == "fault_latched"
                           and int(o.get("bit", -1)) == int(c["bit"])
                           for o in e.get("checks", [])), (
                    f"REPLAY_SUITE[{log!r}]: `latch_precedes_uv` orders a latch "
                    f"it does not itself assert. Pair it with the "
                    f"`fault_latched` check on the same bit, or the entry can "
                    f"report an ordering for a fault nothing required.")


_assert_skip_preamble_entries()
_assert_uv_not_latched_entries()
# _assert_check_spec_shapes() reads CHECK_KINDS, which is built after the check
# functions further down; it is CALLED at the bottom of this module, not here.


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
        # FU2: the switch bitmask, and the MDAC command words, over the RECORDED
        # window.  Both are observation-frame columns and are blank before the
        # first frame arrives, so _series drops those rows for us.
        self.switch = _series(rows, "t", "switch", _int_any)
        self.switch_recorded = [(t, s) for t, s in self.switch if t >= preamble_s]
        self.mdac_fc = _series(rows, "t", "mdac_fc", _int_any)
        self.mdac_bt = _series(rows, "t", "mdac_bt", _int_any)
        self.n_rows = len(rows)
        self.n_obs = len(self.current)
        self.duration_s = (float(rows[-1]["t"]) - float(rows[0]["t"])) if rows else 0.0

    def first_fault_t(self, bit=None):
        """L1: WHOLE-RUN first time a fault (or `bit`) was observed, or None.

        Distinct from the times the checks print, which are necessarily the first
        POST-GRACE observation.  A fault that latches before the grace bound and
        persists — ML0217's INIT_FAIL at ~0.80 s is the standing example — is
        correctly scored on its post-grace samples, but reporting 2.0 s as "when it
        happened" would be wrong; both numbers are shown."""
        for t, f in self.faults_all:
            if (f & bit) if bit is not None else f:
                return t
        return None

    def command_is_identically_zero(self):
        """True when the observed motor command is 0 A on EVERY sample.

        Campaign finding F6: replay mode constructs no commander, so no replayed run
        ever reaches State 2 and `current` is 0.0000 A throughout — 32 of the half's
        79 checks (bounded_current, no_rail_limit_cycle, returns_off_rail,
        near_zero_current) are then VACUOUSLY TRUE.  They still assert something
        real ("the firmware did not drive on an uncommanded stimulus"), but they
        carry no evidence about the entry's own classification, and a reader
        counting green ticks cannot tell the difference.  Measured, not assumed, so
        the tag disappears by itself the day a commander is added."""
        return bool(self.current) and all(i == 0.0 for _t, i in self.current)


    def carried_in_bits(self):
        """Fault bits seen ONLY before the grace bound — the predecessor's latch."""
        pre = 0
        for _t, f in self.faults_pre_grace:
            pre |= f
        post = 0
        for _t, f in self.faults:
            post |= f
        return pre & ~post

    def metrics(self, csv_path=None):
        """Health metrics for results.json, from the SAME single parse.

        A5 (campaign 20260830_214819): `_run_plan`'s replay branch used to store
        `"metrics": {}`, so a replay run whose sidecar showed a latched 0x8100 /
        0x8001 rendered in results.json and REPORT.md as `final fault_flags
        0x0000 (none)` — the exact latched end-state that carries into the next
        run, hidden.

        Field names match run_hil_suite.analyze_scenario_csv() WHERE THE SEMANTICS
        MATCH, so one consumer can read both halves.  Fields whose semantics do
        NOT carry over are OMITTED rather than faked:
          survive_to_t / fault_bits_before_survive / state_at_survive
                              — scenario-only (FAULT_EXPECTATIONS['survive_to']).
          substep_hz_min/mean — replay mode runs no electrical engine.
          error               — set only on the load-failure path, by the caller.

        `n_obs` counts rows carrying a fault_flags cell, matching the scenario
        analyzer's definition (hil_plant_sim writes every observation column from
        the same decoded frame, so it equals len(self.current) in practice).
        `fault_first_t` is keyed by fault NAME and covers POST-GRACE first
        sightings only, again matching the scenario analyzer; `first_fault_t()`
        remains the whole-run view for the check details."""
        seen = 0
        for _t, f in self.faults_all:
            seen |= f
        post = 0
        first_t = {}
        for t, f in self.faults:
            new = f & ~post
            post |= f
            b = 1
            while new:
                if new & 1:
                    first_t.setdefault(_fault_names(b), t)
                new >>= 1
                b <<= 1
        return {
            "csv": csv_path,
            "rows": self.n_rows,
            # FU2 (2026-08-31): how many times the switch bitmask CHANGED VALUE
            # over the recorded window. Cheap (one pass over an already-parsed
            # series) and report-only — no check reads it — but without it a
            # replay entry's switch actuation is completely silent in
            # results.json and REPORT.md. ML0203 measured 222 changes in round-1
            # campaign 20260831_000518 against 0-50 for every other entry; that
            # gap is exactly the kind of thing that should not need a bespoke
            # analysis pass to notice. NOTE it counts CHANGES, so one open+close
            # of one switch is 2; it is a churn indicator, not an event count.
            "switch_transitions": sum(
                1 for a, b in zip(self.switch_recorded, self.switch_recorded[1:])
                if a[1] != b[1]),
            "n_obs": len(self.faults_all),
            "n_obs_post_grace": len(self.faults),
            "final_fault_flags": self.faults_all[-1][1] if self.faults_all else None,
            "fault_bits_seen": seen,
            "fault_bits_post_grace": post,
            "fault_first_t": first_t,
            "last_obs_t": self.faults_all[-1][0] if self.faults_all else None,
            "grace_s": self.grace_s,
            "final_state": self.state[-1][1] if self.state else None,
            "duration_s": self.duration_s,
        }

    def reached_idle_t(self, deadline_s=BRINGUP_DEADLINE_S):
        """Sim time the board first reported mainState 1, or None within deadline."""
        for t, st in self.state:
            if st == BRINGUP_STATE_IDLE:
                return t if t <= deadline_s else None
        return None

    def state_entry_t(self, want, before_t=None):
        """Sim time of the LAST observed ENTRY into mainState `want`, at or
        before `before_t` (whole run when None).  None if there is none.

        F1 (campaign 20260831_222036) — the ANCHOR for an elapsed-time bound.
        A bring-up phase timeout is measured by the firmware from
        `bringupPhaseStart`, which is re-stamped on the State-0 entry, so an
        ABSOLUTE timestamp on a suite run cannot say which phase timed out:
        every run in a campaign starts latched from the predecessor and only
        reaches State 0 when the fw v23 run-boundary warm reset fires, at a time
        that is a property of the HOST's inter-run gap, not of the firmware.
        The observed 99 -> 0 transition is that anchor, and it is already in the
        CSV's `state` column.

        ENTRY EDGE, i.e. a sample at `want` whose predecessor is not: the LAST
        one at or before `before_t` wins, so a run that reached State 0 more
        than once (a second warm reset) is anchored on the reset the latch
        actually followed.  A run whose FIRST observed sample is already at
        `want` counts as an entry there — there is no earlier evidence to
        distinguish "entered just now" from "has been here all along", and the
        caller prints the anchor time so the reader can see which it was."""
        out = None
        prev = None
        for t, st in self.state:
            if before_t is not None and t > before_t:
                break
            if st == want and prev != want:
                out = t
            prev = st
        return out


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
    """Name the WHOLE-RUN first observation when it precedes the grace bound.

    Every time a check prints is necessarily a first POST-GRACE observation, so when
    a bit was ALSO seen earlier the reader needs to know which story that earlier
    sighting tells.  There are two, and the campaign report (F1) caught the first
    version of this asserting the wrong one on ML0203/ML0169/TP0053:

      PERSISTED   the bit is still set on the LAST pre-grace sample, so it latched
                  early and the grace filter is looking at that same latch.
                  ML0217's INIT_FAIL at ~0.80 s is the standing example.
      CARRIED-IN  the bit was set early and is GONE by the end of the pre-grace
                  window — the predecessor run's settle latch, cleared by the fw v23
                  warm reset at t ~= 0.5 s.  The post-grace sighting is then a
                  SEPARATE, later event that merely shares a bit.

    Deciding on the LAST pre-grace sample rather than on "was it ever seen early" is
    exactly what separates the two; they are indistinguishable to a reader otherwise,
    and calling a carried-in latch "PERSISTED" invents a fault the run never had."""
    t0 = data.first_fault_t(bit)
    if t0 is None or t0 >= data.grace_s:
        return ""
    last_pre = data.faults_pre_grace[-1] if data.faults_pre_grace else None
    still_set = last_pre is not None and (
        (last_pre[1] & bit) if bit is not None else last_pre[1])
    if still_set:
        return (f" (whole-run first observation t={t0:.3f}s — it latched BEFORE the "
                f"{data.grace_s:.1f}s grace bound and was STILL SET on the last "
                f"pre-grace sample, i.e. it PERSISTED, which is why the grace filter "
                f"still sees it)")
    if last_pre is None:
        return f" (also seen at t={t0:.3f}s, before the grace bound)"
    return (f" (also seen at t={t0:.3f}s but CLEARED by t={last_pre[0]:.3f}s — that "
            f"earlier sighting is the predecessor run's carried-in settle latch, NOT "
            f"this one; the post-grace occurrence is a separate, later event)")


def _persisted_latch_t(data, bit):
    """WHOLE-RUN first LATCHED observation of `bit`, EXCLUDING a carried-in one.

    DI-MED-4.  `check_fault_latched`'s `not_before_s` and `latch_elapsed_band_s`
    bounds both need "when did THIS run latch", and the raw whole-run first
    sighting cannot answer that: a predecessor run's settle latch is still on
    the wire for the first ~0.5 s until the fw v23 warm reset clears it, so
    back-to-back suite runs would hand the bound a timestamp from the PREVIOUS
    run — and on ML0217, whose band separates P0's PRECHARGE_TIMEOUT_MS from
    P1's BUS_CHARGE_TIMEOUT_MS, that reads as "a different firmware path raised
    the same bit sooner" and FAILS a correct board with a wrong-mechanism
    message.  Under the elapsed band it is worse than wrong: a carried-in latch
    PRECEDES the State-0 entry it would be measured from, so the elapsed time
    comes out NEGATIVE and lands outside any band.

    ⚠️ STRUCTURALLY UNREACHABLE IN THE CURRENT PLAN ORDER, and kept anyway.  No
    run that ML0217 can follow in build_plan()'s order leaves a latched
    FAULT_INIT_FAIL behind, so this branch has never fired on a real campaign
    and is covered by UNIT TESTS ONLY.  It stays because the guard is free,
    because the plan order is not a contract, and because the failure it
    prevents is a confident wrong-mechanism verdict rather than a visible error.

    The classification rule is `_whole_run_first_note`'s, reused rather than
    re-invented so the two can never disagree: an early sighting is PERSISTED
    when the latch is STILL SET on the last pre-grace sample, and CARRIED-IN
    when it is gone by then.  A carried-in latch is skipped and the first
    post-grace latched observation is returned instead."""
    def latched(f):
        return bool(f & bit) and bool(f & FAULT_ERROR)
    first = next((t for t, f in data.faults_all if latched(f)), None)
    if first is None or first >= data.grace_s:
        return first
    last_pre = data.faults_pre_grace[-1] if data.faults_pre_grace else None
    if last_pre is not None and not latched(last_pre[1]):
        return next((t for t, f in data.faults if latched(f)), None)
    return first


def _carried_in_note(data):
    """Report-only sentence naming the excluded pre-grace bits, or ''.

    ⚠️ WORDING CORRECTED 2026-08-31 (campaign 20260831_222036), in lockstep
    with run_hil_suite.judge_scenario()'s copy — the two are read side by side
    in one REPORT.md and must not tell different stories.  The sentence used to
    assert "carried-in from the PREDECESSOR'S settle latch", which the CSV
    cannot support and which was false on most runs it printed for: the
    dominant pre-grace bit is 0x8010 (HIL_STALE|ERROR), generated FRESH by each
    child's own link handshake, not inherited.  An inherited latch IS also
    possible and looks identical here, so the note names what it observes."""
    carried = data.carried_in_bits()
    if not carried:
        return ""
    return (f"; pre-grace reconnect transient, EXCLUDED: "
            f"{_fault_names(carried)} (seen only before t={data.grace_s:.1f}s "
            f"and gone after it — a fresh link-handshake blip and/or a "
            f"predecessor latch cleared by the fw v23 warm reset; the two are "
            f"indistinguishable from this CSV, so neither is claimed)")


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


# ── TRANSIENT INDICATION vs LATCH — the contract both fault checks share ────
# The firmware PUBLISHES a fault bit as soon as the condition is indicated, and
# separately LATCHES it (State 99) by ORing in FAULT_ERROR 0x8000 once the
# condition survives its filter.  So `fault_flags & BIT` alone answers "was the
# condition ever indicated?", while `fault_flags & (BIT | FAULT_ERROR)` answers
# "did the board actually latch on it?".  Measured on this suite: TP0010 indicates
# UV_BUS 321 ms before it latches, TP0053 536 ms before — a real and reportable
# gap, not rounding.
#
# The two checks deliberately use DIFFERENT halves of that contract, and the
# asymmetry is the point:
#   check_fault_latched     -> LATCH semantics (bit AND FAULT_ERROR).  The entry
#                              promises the board latches; a transient indication
#                              that self-clears is not that promise kept.
#   check_fault_not_latched -> LATCH semantics too (its name is its contract): a
#                              sub-latch transient dip must NOT fail an entry that
#                              only ever promised "this dip does not latch UV".
# CONSEQUENCE, stated because it is a real seam (campaign finding F5): an entry
# pairing `no_fault` with `fault_not_latched` is NOT redundant. On a stimulus deep
# enough to produce a transient indication without a latch, `fault_not_latched`
# passes and `no_fault` FAILS — correctly, and by design. `no_fault` is the
# stronger claim ("nothing was even indicated"); if a future entry wants to permit
# a transient it must drop `no_fault`, not weaken this pair. TP0178/TP0201 pass
# today because their recorded minima (12.1489/12.1853 V) never cross
# LIMIT_V_BUS_MIN at all, so neither check is exercised near the seam.
def check_fault_not_latched(data, spec):
    """A specific bit must never LATCH post-grace (the negative UV cases).

    Latch semantics: bit AND FAULT_ERROR. See the contract note above for why a
    bare transient indication does not fail this check but does fail `no_fault`."""
    bit = int(spec["bit"])
    if not data.faults:
        return False, (f"no observation frames at or after t={data.grace_s:.1f}s")
    latched = [(t, f) for t, f in data.faults if (f & bit) and (f & FAULT_ERROR)]
    if latched:
        return False, (f"{_fault_names(bit)} LATCHED at t={latched[0][0]:.3f}s "
                       f"({len(latched)} ticks with FAULT_ERROR also set) — the "
                       f"recorded dip should NOT latch it")
    indicated = [t for t, f in data.faults if f & bit]
    note = ""
    if indicated:
        note = (f"; NOTE {_fault_names(bit)} was transiently INDICATED on "
                f"{len(indicated)} tick(s) from t={indicated[0]:.3f}s without ever "
                f"latching — allowed here (this check promises no LATCH), but a "
                f"`no_fault` check on the same entry will fail on it")
    margin = ""
    if bit == FAULT_UV_BUS:
        # MED (2026-08-31 ledger fix queue): SAY HOW CLOSE THE STIMULUS CAME.
        # On TP0178/TP0201 this check is VACUOUS — their recorded minima never
        # cross LIMIT_V_BUS_MIN at all, so the dwell integrator accumulates
        # 0.0 ms and no possible firmware could fail the check. That is not
        # visible from a green tick, so the margin is printed alongside it, and
        # the companion `v_bus_min_in_band` check (required at import for every
        # entry carrying this pair) is what makes a stimulus change LOUD.
        lo_t, lo = _v_bus_min_recorded(data)
        if lo is not None:
            _q, _w, peak = _uv_stimulus_qualifies(data)
            margin = (f"; STIMULUS MARGIN: min V_bus {lo:.4f} V at t={lo_t:.3f}s, "
                      f"{lo - LIMIT_V_BUS_MIN_V:+.4f} V vs LIMIT_V_BUS_MIN "
                      f"{LIMIT_V_BUS_MIN_V:.1f} V, peak accumulated dwell "
                      f"{peak:.1f} ms vs the {UV_BUS_DWELL_LATCH_MS:.0f} ms latch"
                      + (" — the recorded floor never crosses the limit, so this "
                         "check is VACUOUS on this stimulus (see "
                         "`v_bus_min_in_band`)" if lo >= LIMIT_V_BUS_MIN_V else ""))
    return True, (f"{_fault_names(bit)} never latched across {len(data.faults)} "
                  f"ticks at t >= {data.grace_s:.1f}s{note}{margin}"
                  f"{_carried_in_note(data)}")


def _v_bus_min_recorded(data):
    """(t, V_bus) at the RECORDED-window minimum, or (None, None).

    Restricted to t >= data.preamble_s for the M5 reason every stimulus reader
    in this module is: the synthetic preamble holds a healthy 15.95 V that this
    harness invented, and a question about the STIMULUS must be answered from
    the stimulus.  (A high preamble cannot move a minimum, but the restriction
    is stated so a future preamble change cannot silently move one.)"""
    window = [(t, v) for t, v in data.v_bus if t >= data.preamble_s]
    if not window:
        return None, None
    t, v = min(window, key=lambda tv: tv[1])
    return t, v


def check_v_bus_min_in_band(data, spec):
    """The recorded V_bus MINIMUM lands inside (min_v, max_v].

    MED (2026-08-31 ledger fix queue) — THE DE-VACUATION GUARD FOR THE
    must-NOT-latch UV ENTRIES.  `fault_not_latched` on TP0178/TP0201 asserts
    that a recorded sag does not latch UV_BUS, and campaign
    `hil_report_20260831_191509` found it cannot fail: those logs' minima are
    12.1489 V and 12.1853 V, which never cross LIMIT_V_BUS_MIN 12.0 V, so the
    firmware's dwell integrator accumulates 0.0 ms and no board could latch.
    The check was passing on a stimulus that was never applied.

    THIS check is the one that bites, and it bites in BOTH directions:

      LOWER bound, EXCLUSIVE at LIMIT_V_BUS_MIN — if a future decode, rescale
        or absent-rail substitution pushed the injected floor UNDER the limit,
        the entry would silently become a might-latch case and its `no_fault`
        companion would start failing for a reason nobody wrote down. Failing
        HERE names the cause.
      UPPER bound, INCLUSIVE — if the floor drifted well ABOVE the limit the
        entry would stop being a near-miss at all: a 15 V trace also "does not
        latch UV", and the entry would have quietly become a tautology.

    It asserts the STIMULUS, not the board, so it is deliberately a separate
    check rather than a tightening of `fault_not_latched`: the two answer
    different questions and a reader should see both verdicts.

    Spec fields: `min_v` (exclusive floor, default LIMIT_V_BUS_MIN_V), `max_v`
    (inclusive ceiling, required)."""
    lo_v = float(spec.get("min_v", LIMIT_V_BUS_MIN_V))
    hi_v = float(spec["max_v"])
    t, v = _v_bus_min_recorded(data)
    if v is None:
        return False, (f"no V_bus samples at or after t={data.preamble_s:.1f}s — "
                       f"the recorded stimulus is absent, so its floor cannot be "
                       f"pinned")
    where = (f"min V_bus {v:.4f} V at t={t:.3f}s ({v - LIMIT_V_BUS_MIN_V:+.4f} V "
             f"vs LIMIT_V_BUS_MIN {LIMIT_V_BUS_MIN_V:.1f} V)")
    if v <= lo_v:
        return False, (f"{where} is AT OR BELOW the {lo_v:.2f} V floor this entry "
                       f"pins: the recorded sag now crosses the UV limit, so this "
                       f"is no longer a must-NOT-latch stimulus and the entry's "
                       f"classification must be re-derived before its verdict "
                       f"means anything")
    if v > hi_v:
        return False, (f"{where} is ABOVE the {hi_v:.2f} V ceiling this entry pins: "
                       f"the recorded floor has drifted away from the limit, so the "
                       f"companion `fault_not_latched` check is no longer a "
                       f"near-miss assertion but a tautology any healthy bus "
                       f"satisfies")
    return True, (f"{where}, inside the pinned near-miss band "
                  f"({lo_v:.2f}, {hi_v:.2f}] V — the sag stays above the limit "
                  f"with {(v - LIMIT_V_BUS_MIN_V) / LIMIT_V_BUS_MIN_V * 100:.2f} % "
                  f"margin, which is what makes `fault_not_latched` a real "
                  f"near-miss case and not a tautology")


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
    # F2/F3: LATCH semantics — bit AND FAULT_ERROR, on both the reported time and
    # the end-of-run test.  Reporting the first sample with the bit alone reports
    # the TRANSIENT INDICATION, which on this suite is 321 ms (TP0010) / 536 ms
    # (TP0053) before the real latch; and an end test on the bare bit would accept
    # a run whose indication was still flapping at the last sample.
    hits = [t for t, f in data.faults if (f & bit) and (f & FAULT_ERROR)]
    indicated = [t for t, f in data.faults if f & bit]
    end_flags = data.faults[-1][1]
    if not hits:
        extra = f" (stimulus qualifies from t={stim_t:.3f}s)" if stim_t is not None else ""
        if indicated:
            return False, (f"{_fault_names(bit)} was INDICATED from "
                           f"t={indicated[0]:.3f}s but never LATCHED — FAULT_ERROR "
                           f"was never set alongside it{extra}")
        return False, f"{_fault_names(bit)} was never set{extra}"
    if not (end_flags & bit and end_flags & FAULT_ERROR):
        return False, (f"{_fault_names(bit)} latched at t={hits[0]:.3f}s but was "
                       f"CLEARED by the end of the run (final 0x{end_flags:04X}) — "
                       f"it must LATCH and hold")
    # ── TIMING BOUNDS: WHICH mechanism latched, not just that one did ───────
    # A bare `fault_latched` says the bit is set and holds; it cannot
    # distinguish two firmware paths that raise the SAME bit at different times.
    # ML0217 is the case: FAULT_INIT_FAIL is raised by busBringupTick()'s phase
    # timeouts, and P0's PRECHARGE_TIMEOUT_MS (300 ms) and P1's
    # BUS_CHARGE_TIMEOUT_MS (800 ms) both produce it — so "INIT_FAIL latched"
    # alone would pass whether the dark bus failed the precharge gate or the
    # charge gate, which are different findings about the firmware.
    #
    # TWO BOUNDS, and `latch_elapsed_band_s` is the one to reach for.
    #   latch_elapsed_band_s  ELAPSED from a named mainState entry — the frame
    #                         the firmware measures phase timeouts in.  Two
    #                         sided, so it excludes an earlier AND a later gate.
    #   not_before_s          ABSOLUTE floor on the sim clock.  Sound only where
    #                         the sim clock's zero and the board's own reference
    #                         for the mechanism coincide, which on a warm-reset
    #                         run they do not (F1, campaign 20260831_222036: the
    #                         board reaches State 0 at ~0.5 s, so BOTH candidate
    #                         gates land past a 0.5 s absolute floor and the
    #                         bound discriminated nothing).  No entry uses it
    #                         today; it is kept for a future mechanism whose
    #                         reference genuinely is the start of the run.
    #
    # Both are evaluated against the WHOLE-RUN first latched observation,
    # deliberately: `hits[0]` is the first POST-GRACE one, which on a
    # skip_preamble entry is just the grace bound and carries no information
    # about when the latch actually happened.
    #
    # ⚠️ But the whole-run first sighting is taken through _persisted_latch_t()
    # (DI-MED-4), which drops a CARRIED-IN latch — the predecessor run's, still
    # on the wire until the fw v23 warm reset clears it at t ~= 0.5 s.  See that
    # function for why, and for why the branch is unreachable in today's plan
    # order and kept regardless.
    #
    # NO CEILING ON `not_before_s`, and that is a considered omission rather
    # than an oversight: INIT_FAIL can only be raised from State 0's bring-up
    # machine, which runs once at the start of the run, so a "latched too late"
    # outcome has no mechanism.  A ceiling would assert something the firmware's
    # structure already guarantees.  `latch_elapsed_band_s` carries one anyway,
    # because in ITS frame the two gates are 300 ms and 800 ms after the SAME
    # anchor and a ceiling is the only thing that separates them.
    not_before = spec.get("not_before_s")
    band = spec.get("latch_elapsed_band_s")
    latch_t = _persisted_latch_t(data, bit)
    # ── `latch_elapsed_band_s`: the same question, asked in the right frame ──
    # F1, campaign 20260831_222036 (the audit of the 20260831_191509 fix round).
    # An ABSOLUTE bound on a bring-up latch is not a discriminator, and on
    # ML0217 it was asserted as one and got the mechanism backwards.  The
    # firmware measures every bring-up phase timeout from `bringupPhaseStart`,
    # re-stamped on the State-0 entry, so the quantity that NAMES the gate is
    # ELAPSED time from that entry — never the sim clock, whose zero is the
    # host's and not the board's.
    #
    # `elapsed_from_state` (default 0 = State 0 / Init) names the anchor state;
    # the band is (lo, hi) in seconds, both INCLUSIVE, and both ends are needed:
    # a floor alone cannot exclude a LATER gate and a ceiling alone cannot
    # exclude an EARLIER one, which is exactly the pair of confusions this bound
    # exists to prevent.
    #
    # `latch_t` comes through _persisted_latch_t() for the same reason
    # `not_before_s` does — and here a carried-in latch is worse than merely
    # wrong: it PRECEDES the anchor, so the elapsed time comes out NEGATIVE.
    elapsed_note = ""
    if band is not None:
        lo_s, hi_s = float(band[0]), float(band[1])
        if latch_t is None:
            return False, (f"{_fault_names(bit)} has a `latch_elapsed_band_s` "
                           f"bound but no whole-run latched observation was "
                           f"found — the check cannot say which mechanism fired")
        anchor_state = int(spec.get("elapsed_from_state", 0))
        anchor = data.state_entry_t(anchor_state, before_t=latch_t)
        if anchor is None:
            return False, (
                f"{_fault_names(bit)} latched at t={latch_t:.4f}s but the run "
                f"never reported an ENTRY into mainState {anchor_state} before "
                f"it, so the elapsed-time bound has no anchor. Either the board "
                f"never re-entered State {anchor_state} (no warm recovery — in "
                f"which case the latch is the PREDECESSOR's) or the `state` "
                f"column is absent")
        elapsed = latch_t - anchor
        if not (lo_s <= elapsed <= hi_s):
            return False, (
                f"{_fault_names(bit)} LATCHED {elapsed * 1000.0:.1f} ms after "
                f"the mainState {anchor_state} entry at t={anchor:.4f}s (latch "
                f"t={latch_t:.4f}s), OUTSIDE the "
                f"[{lo_s * 1000.0:.0f}, {hi_s * 1000.0:.0f}] ms band this entry "
                f"pins. The bit is right but the mechanism is not the one "
                f"classified — a different firmware timeout raised the same "
                f"bit, and the entry's `why` no longer describes what happened")
        elapsed_note = (
            f"; whole-run latch at t={latch_t:.4f}s, {elapsed * 1000.0:.1f} ms "
            f"after the mainState {anchor_state} entry at t={anchor:.4f}s, "
            f"inside the [{lo_s * 1000.0:.0f}, {hi_s * 1000.0:.0f}] ms "
            f"mechanism band")
    if not_before is not None:
        if latch_t is None:
            return False, (f"{_fault_names(bit)} has a `not_before_s` bound but no "
                           f"whole-run latched observation was found — the check "
                           f"cannot say which mechanism fired")
        if latch_t < float(not_before):
            return False, (
                f"{_fault_names(bit)} LATCHED at t={latch_t:.4f}s, EARLIER than "
                f"the {float(not_before):.3f}s this entry pins. The bit is right "
                f"but the mechanism is not the one classified — a different "
                f"firmware path raised the same bit sooner, and the entry's "
                f"`why` no longer describes what happened")
    lead = ""
    if indicated and indicated[0] < hits[0]:
        lead = (f" (transiently indicated {1000.0 * (hits[0] - indicated[0]):.0f} ms "
                f"earlier, at t={indicated[0]:.3f}s, before the filter latched)")
    return True, (f"{_fault_names(bit)} LATCHED (bit + FAULT_ERROR); first "
                  f"POST-GRACE latched observation at t={hits[0]:.3f}s{lead}"
                  + _whole_run_first_note(data, bit)
                  + (f", stimulus qualified from t={stim_t:.3f}s" if stim_t is not None else "")
                  + ("" if not_before is None else
                     f"; whole-run latch at t={latch_t:.4f}s, "
                     f"{latch_t - float(not_before):+.4f}s vs the "
                     f"{float(not_before):.3f}s mechanism bound")
                  + elapsed_note)


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


VACUOUS_TAG = (" **(vacuous — no commander in replay mode, so the command is "
               "identically 0 A; this check asserts only that the firmware did NOT "
               "drive on an uncommanded stimulus, and carries no evidence about "
               "this entry's own classification)**")

# The same condition, stated at the FRONT of the detail rather than appended, for
# the entries that could have replayed commands and did not.  Sharpened from the
# trailing VACUOUS_TAG (2026-08-30) because a reader scanning check details sees
# the first words, not the last: a motor-response check on a command-free entry
# is not a weak pass, it is a check that was never exercised.
#
# `passed` deliberately STAYS True.  The checks[] schema is boolean and the
# assertion the check actually made ("the firmware did not drive on an
# uncommanded stimulus") is true and worth keeping; failing every command-free
# entry would assert something nobody claimed.  The distinct result is the TAG
# plus the n_checks_not_exercised count, not a red tick.
NOT_EXERCISED_PREFIX = "NOT EXERCISED (no command replay)"
NOT_EXERCISED_TAG = (
    NOT_EXERCISED_PREFIX + ": this entry does not set `replay_commands`, so no "
    "22-byte Pi command packet was sent, the board never left Idle and the motor "
    "command is identically 0 A. The only thing asserted is that the firmware did "
    "NOT drive on an uncommanded stimulus — nothing about the controller's "
    "response to this log. Set `replay_commands: True` on the entry to exercise "
    "it. Measured detail follows — ")

# The check kinds whose verdict is read off `data.current`, i.e. the ones the
# tag above applies to.  Named explicitly rather than inferred, so adding a
# motor-response kind without deciding this question is a visible omission.
MOTOR_RESPONSE_KINDS = frozenset({
    "bounded_current", "no_sustained_rail", "no_rail_limit_cycle",
    "returns_off_rail", "near_zero_current",
    # FU4: `steps_onto_rail_within` reads its verdict off data.current and is
    # MEANINGLESS without command replay — with no commander the board never
    # leaves Idle, the command is identically 0 A, and the check would report a
    # confident "never crossed" FAIL about a stimulus that was never delivered.
    # It is in this set so that case carries the NOT EXERCISED explanation.
    # NOTE the asymmetry with the other members, and it is intended: the tag
    # never changes `passed`, and this kind FAILS on a flat-zero series where
    # they pass — so a misuse surfaces as a TAGGED FAIL ("not exercised, and
    # here is why it could not be"), which is the loud outcome, not a silent
    # green tick.  (Its own entry sets `replay_commands: True`, so the tag
    # should never fire there; the membership guards a future reuse.)
    "steps_onto_rail_within",
})

# ── drive_loop_stepped thresholds (suite policy, not firmware) ──────────────
# "The loop actually stepped" on a --replay-commands entry.  0.05 A is an order
# of magnitude above the CSV's %.4f print resolution and well under any
# meaningful command, so it separates "commanded something" from "commanded
# nothing"; 50 samples at the 1 kHz tick is 50 ms of it, long enough that a
# single spurious sample cannot satisfy the check.
DRIVE_STEPPED_MIN_A = 0.05
DRIVE_STEPPED_MIN_SAMPLES = 50


def _vacuous_suffix(data):
    """Item 5: tag a command-shape check whose series is identically zero."""
    return VACUOUS_TAG if data.command_is_identically_zero() else ""


# ── share_loop_actuated thresholds (suite policy, not firmware) ─────────────
# FU1 (2026-08-31). Measured MDAC-ratio spans over the recorded window, round-1
# campaign 20260831_000518, for the five entries whose recorded share_sp varies:
#   YP0152 0.400   YP0166 0.546   YP0196 0.695   YP0214 0.552   ML0203 0.699
# 0.20 is half the SMALLEST of those, so every current entry clears it ~2x and a
# path that half-died still fails.
SHARE_ACTUATED_MIN_SPAN = 0.20
# A ratio needs both codes; below this many usable samples the window is not
# evidence either way. 50 matches DRIVE_STEPPED_MIN_SAMPLES for the same reason.
SHARE_ACTUATED_MIN_SAMPLES = 50
# AD5443 command word: control nibble 0x1 = load-and-update, then a 12-bit code
# (hil_plant_sim.MDAC_CMD_LOAD_UPDATE / MDAC_RES). A word carrying any other
# nibble is not a code write and is skipped rather than read as zero.
MDAC_CMD_LOAD_UPDATE = 0x1000
MDAC_CODE_MASK = 0x0FFF


def _mdac_share_ratio_series(data):
    """(t, r) with r = BT_code / (FC_code + BT_code) over the RECORDED window.

    This is the DROOP-GAIN split the firmware actually wrote to the two MDACs —
    the share loop's actuator, and the only share-side observable the 16-byte
    observation frame carries. Samples are skipped when either word is blank,
    carries a non-load-update control nibble, or the codes sum to zero."""
    fc = dict(data.mdac_fc)
    out = []
    for t, bw in data.mdac_bt:
        if t < data.preamble_s:
            continue
        fw = fc.get(t)
        if fw is None:
            continue
        if (fw & 0xF000) != MDAC_CMD_LOAD_UPDATE or (bw & 0xF000) != MDAC_CMD_LOAD_UPDATE:
            continue
        a, b = fw & MDAC_CODE_MASK, bw & MDAC_CODE_MASK
        if a + b == 0:
            continue
        out.append((t, b / float(a + b)))
    return out


def check_share_loop_actuated(data, spec):
    """The MDAC droop split MOVED over the recorded window.

    WHAT THIS ASSERTS, precisely: that the share loop's ACTUATOR travelled — the
    firmware wrote a materially different FC/BT droop-gain split at some point
    than at another. That is the share axis's only observable here, and before
    this check existed the entire share axis was unasserted across all 122 checks
    in the half.

    WHAT IT DELIBERATELY DOES NOT ASSERT: that the split TRACKED the commanded
    setpoint. Replay is open loop, so the share PI integrates against an error it
    can never null and winds regardless — measured, round-1 campaign
    20260831_000518: entries whose recorded share_sp is CONSTANT at 0.500
    (ML0140, ML0151, ML0169, ...) still show a ratio span of ~0.35 from windup
    alone. A tracking assertion here would therefore be satisfied by windup and
    would be evidence of nothing. Movement is the honest claim; a tolerance-based
    tracking check belongs to a closed-loop harness, not to this one.

    Spec fields: `min_span` (default SHARE_ACTUATED_MIN_SPAN), `min_samples`
    (default SHARE_ACTUATED_MIN_SAMPLES)."""
    min_span = float(spec.get("min_span", SHARE_ACTUATED_MIN_SPAN))
    min_n = int(spec.get("min_samples", SHARE_ACTUATED_MIN_SAMPLES))
    series = _mdac_share_ratio_series(data)
    if len(series) < min_n:
        return False, (
            f"only {len(series)} usable MDAC sample(s) in the recorded window "
            f"(t >= {data.preamble_s:.1f}s, need >= {min_n}) — both mdac_fc and "
            f"mdac_bt must carry a 0x1nnn load-and-update word for a ratio to "
            f"exist, so this is 'not measured', not 'did not move'")
    lo_t, lo = min(series, key=lambda tv: tv[1])
    hi_t, hi = max(series, key=lambda tv: tv[1])
    span = hi - lo
    if span < min_span:
        return False, (
            f"the share actuator did not move: MDAC ratio r = BT/(FC+BT) spanned "
            f"only {span:.4f} over {len(series)} recorded-window samples "
            f"({lo:.4f} at t={lo_t:.3f}s .. {hi:.4f} at t={hi_t:.3f}s), need "
            f">= {min_span:.2f}. This entry's recorded share_sp varies, so a flat "
            f"split means the command did not reach the share loop or the MDAC "
            f"write path is broken")
    return True, (
        f"share actuator moved: MDAC ratio r = BT/(FC+BT) spanned {span:.4f} "
        f"({lo:.4f} at t={lo_t:.3f}s .. {hi:.4f} at t={hi_t:.3f}s) over "
        f"{len(series)} recorded-window samples, need >= {min_span:.2f}. "
        f"ACTUATION ONLY — open-loop replay winds the share PI regardless, so "
        f"this is NOT evidence the split tracked the commanded setpoint")


def check_drive_loop_stepped(data, spec):
    """The commanded current shows real drive activity in the recorded window.

    Only meaningful on a `replay_commands` entry: it is the assertion that the
    command replay ACTUALLY REACHED the board and moved it out of Idle. A FAIL
    here is a real failure (commands were sent and the loop never stepped), and it
    is ordered before the motor-response checks so a reader sees the cause first
    rather than N downstream checks passing on a flat zero.

    TWO FLOORS, and the second is what makes this check bite (FU3, 2026-08-31):

      min_samples   an ABSOLUTE floor (50 samples), the "did anything happen at
                    all" bound. Kept as the default so an entry without a
                    measurement still gets a check.
      drive_min_frac  optional, PER-ENTRY: the fraction of recorded-window
                    samples that must clear the threshold. Default None = the
                    absolute floor alone, i.e. previous behaviour exactly.

    Why the fraction was needed: the 50-sample floor sits 31-1017x BELOW measured
    activity (round-1 campaign 20260831_000518 — ML0151 ran 0.899 of its window
    over threshold, i.e. ~50 000 samples against a floor of 50). A command path
    that had DEGRADED to a few percent of its real duty would have sailed through.
    Each opted-in entry now carries a fraction at roughly HALF its own measured
    value, so a real halving of drive activity fails while ordinary run-to-run
    variation does not."""
    min_a = float(spec.get("min_abs_a", DRIVE_STEPPED_MIN_A))
    min_n = int(spec.get("min_samples", DRIVE_STEPPED_MIN_SAMPLES))
    min_frac = spec.get("drive_min_frac")
    series = data.current_recorded or data.current
    if not series:
        return False, ("no observation frames in the recorded window "
                       "(t >= %.1fs) — the board never answered" % data.preamble_s)
    n = sum(1 for _t, i in series if abs(i) >= min_a)
    frac = n / float(len(series))
    peak_t, peak = max(series, key=lambda tv: abs(tv[1]))
    need = f"need >= {min_n}"
    if min_frac is not None:
        need += f" AND >= {float(min_frac) * 100:.0f}% of the window"
    if n < min_n:
        return False, (
            f"the drive loop never stepped: only {n} of {len(series)} recorded-window "
            f"samples have |I_cmd| >= {min_a:.2f} A ({need}); peak "
            f"{peak:+.4f} A at t={peak_t:.3f}s. Commands WERE replayed for this "
            f"entry, so a flat command means they did not reach the board, the "
            f"board never left Idle, or the recorded v_sp/share_sp are themselves "
            f"identically zero")
    if min_frac is not None and frac < float(min_frac):
        return False, (
            f"the drive loop stepped but the command path looks DEGRADED: "
            f"{n} of {len(series)} recorded-window samples ({frac * 100:.1f}%) have "
            f"|I_cmd| >= {min_a:.2f} A, below this entry's own measured-and-halved "
            f"floor of {float(min_frac) * 100:.0f}%; peak {peak:+.4f} A at "
            f"t={peak_t:.3f}s. The absolute {min_n}-sample floor PASSED — that "
            f"floor sits orders of magnitude under normal activity and only "
            f"catches a dead path, not a dying one")
    return True, (f"drive loop stepped: {n} of {len(series)} recorded-window samples "
                  f"({frac * 100:.1f}%) have |I_cmd| >= {min_a:.2f} A ({need}); peak "
                  f"{peak:+.4f} A at t={peak_t:.3f}s")


def check_bounded_current(data, spec):
    """|current| never exceeds the firmware's own clamp."""
    limit = float(spec.get("limit_a", MOTOR_I_CMD_MAX_A)) + I_CMD_EPS_A
    if not data.current:
        return False, "no observation frames in the CSV"
    worst_t, worst = max(data.current, key=lambda tv: abs(tv[1]))
    if abs(worst) > limit:
        return False, f"|I_cmd| reached {worst:+.4f} A at t={worst_t:.3f}s (limit {limit:.2f} A)"
    return True, (f"peak |I_cmd| {worst:+.4f} A at t={worst_t:.3f}s, within "
                  f"±{limit:.2f} A{_vacuous_suffix(data)}")


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
                  f"(limit {max_s:.2f}s){_vacuous_suffix(data)}")


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
                  f"(limit {max_rate:.2f}/s){_vacuous_suffix(data)}")


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
        return True, "no rail episodes to return from" + _vacuous_suffix(data)
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
    return True, (f"peak |I_cmd| {worst:+.4f} A, within "
                  f"±{max_abs:.2f} A{_vacuous_suffix(data)}")


def check_steps_onto_rail_within(data, spec):
    """|I_cmd| must first reach level_a within within_s seconds after after_s.

    FU4 (2026-08-31). The POSITIVE half of the Idle->Run setpoint-arrival
    assertion: a large setpoint delivered across the Run transition must actually
    produce a full-authority command, and must produce it promptly. A slow first
    crossing means the setpoint took longer to land than the two-packet mechanic
    allows (doState1() zeroes v_setpoint on the transition,
    teensy_controller.ino:5382-5410, so the real value arrives on the SECOND
    packet); no crossing at all means the loop did not respond to it.

    `after_s` defaults to `data.preamble_s` rather than a literal 2.5, so a
    `skip_preamble` entry resolves it to 0.0 like everything else that needs the
    bound — nothing here hard-codes REPLAY_PREAMBLE_S.

    Boundary semantics (deliberate, review L4): both edges are INCLUSIVE — a
    crossing at exactly `after_s` passes (dt = 0), and one at exactly
    `after_s + within_s` passes (the test is `dt > within`). Tightening either
    edge is a semantics change; do not flip them incidentally.

    Deliberately asymmetric with `returns_off_rail`, which asks the opposite
    question about the SAME episode: this one says the command went UP on the
    arriving setpoint, that one says it came back DOWN when the setpoint left.
    Neither contradicts the suite's open-loop rail note (§"WHY
    `no_sustained_rail` IS ABSENT"): a sustained rail while the recorded error
    stands is expected here too, and nothing below bounds the episode's LENGTH."""
    level = float(spec.get("level_a", RESET_STEP_LEVEL_A))
    within = float(spec.get("within_s", RESET_STEP_WITHIN_S))
    after = float(spec.get("after_s", data.preamble_s))
    if not data.current:
        return False, "no observation frames in the CSV"
    window = [(t, i) for t, i in data.current if t >= after]
    if not window:
        return False, (f"no observation frames at or after t={after:.3f}s — "
                       f"the board never answered inside the stimulus window")
    for t, i in window:
        if abs(i) >= level:
            dt = t - after
            if dt > within:
                return False, (
                    f"|I_cmd| first reached {level:.1f} A at t={t:.3f}s, "
                    f"{dt * 1000:.1f} ms after the t={after:.3f}s stimulus start — "
                    f"later than the {within * 1000:.0f} ms budget. The setpoint "
                    f"took longer than the two-packet Idle->Run mechanic allows, "
                    f"or the drive loop responded slowly to it")
            return True, (
                f"|I_cmd| reached {level:.1f} A at t={t:.3f}s, {dt * 1000:.1f} ms "
                f"after the t={after:.3f}s stimulus start (budget "
                f"{within * 1000:.0f} ms); value {i:+.4f} A"
                f"{_vacuous_suffix(data)}")
    peak_t, peak = max(window, key=lambda tv: abs(tv[1]))
    return False, (
        f"|I_cmd| NEVER crossed {level:.1f} A after t={after:.3f}s: peak "
        f"{peak:+.4f} A at t={peak_t:.3f}s over {len(window)} samples. The "
        f"arriving setpoint produced no full-authority command"
        f"{_vacuous_suffix(data)}")


def check_latch_precedes_uv(data, spec):
    """The named fault LATCHED before the injected bus fell under LIMIT_V_BUS_MIN.

    F4 (campaign 20260831_222036).  WP0097 was reclassified out of the UV pair
    and into the OC_FC family because its recorded dip supplies only ~18.65 ms
    of dwell against UV_BUS_DWELL_LATCH_MS 20 ms — so it is an OC stimulus that
    happens to carry a near-miss bus collapse behind it.  That reclassification
    is only SAFE while the OC latch genuinely comes FIRST: if a future clamp,
    time-base change or filter retune let the bus collapse arrive first, the
    entry would still report "OC_FC latched" — off the wrong mechanism, with the
    same green verdict.  Nothing asserted the ordering; this does.

    Semantics.  `bit` names the fault; `min_lead_ms` is the required margin by
    which its latch must PRECEDE the first injected sample under
    LIMIT_V_BUS_MIN.  Samples before `data.preamble_s` are excluded — the
    preamble rails are this harness's own synthesis and must never decide a
    stimulus question (M5/L2, as in `_oc_fc_stimulus_qualifies`).

    A run whose injected bus NEVER goes under the limit passes and says so: the
    competing mechanism is absent entirely, which is strictly stronger than
    leading it.  A run with no latch FAILS — the companion `fault_latched` check
    reports the same thing, and an ordering assertion with nothing to order is
    not evidence."""
    bit = int(spec["bit"])
    lead_ms = float(spec.get("min_lead_ms", 0.0))
    latch_t = _persisted_latch_t(data, bit)
    below = [t for t, v in data.v_bus
             if t >= data.preamble_s and v < LIMIT_V_BUS_MIN_V]
    if latch_t is None:
        return False, (f"{_fault_names(bit)} never LATCHED, so there is no "
                       f"ordering to assert — see the companion latch check")
    if not below:
        return True, (
            f"{_fault_names(bit)} LATCHED at t={latch_t:.4f}s and the injected "
            f"V_bus never fell under LIMIT_V_BUS_MIN {LIMIT_V_BUS_MIN_V:.1f} V "
            f"after t={data.preamble_s:.1f}s (min "
            f"{min((v for t, v in data.v_bus if t >= data.preamble_s), default=float('nan')):.4f} V) "
            f"— the competing UV mechanism is absent, not merely later")
    lead = below[0] - latch_t
    where = (f"{_fault_names(bit)} LATCHED at t={latch_t:.4f}s; the injected "
             f"V_bus first fell under {LIMIT_V_BUS_MIN_V:.1f} V at "
             f"t={below[0]:.4f}s — a lead of {lead * 1000.0:+.2f} ms")
    if lead < lead_ms / 1000.0:
        return False, (
            f"{where}, SHORT of the {lead_ms:.0f} ms this entry requires. The "
            f"bus collapse now arrives with the overcurrent (or before it), so "
            f"a latch on this entry can no longer be attributed to the OC "
            f"stimulus its classification rests on — re-derive the entry before "
            f"reading its verdict")
    return True, (f"{where}, at or above the {lead_ms:.0f} ms this entry "
                  f"requires — the overcurrent is unambiguously the latching "
                  f"mechanism, not the bus collapse behind it")


CHECK_KINDS = {
    "no_fault": check_no_fault,
    "latch_precedes_uv": check_latch_precedes_uv,
    "fault_latched": check_fault_latched,
    "fault_not_latched": check_fault_not_latched,
    "bounded_current": check_bounded_current,
    "no_sustained_rail": check_no_sustained_rail,
    "no_rail_limit_cycle": check_no_rail_limit_cycle,
    "returns_off_rail": check_returns_off_rail,
    "near_zero_current": check_near_zero_current,
    "drive_loop_stepped": check_drive_loop_stepped,
    "share_loop_actuated": check_share_loop_actuated,
    "steps_onto_rail_within": check_steps_onto_rail_within,
    "v_bus_min_in_band": check_v_bus_min_in_band,
}

# Deferred from the guard block above: this one needs CHECK_KINDS, which only
# exists now.  Still import-time, so the failure mode it catches is still a
# refusal to load rather than a silently ignored field at score time.
_assert_check_spec_shapes()


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
        # A5: health metrics for results.json, filled from the SAME parse below.
        # Empty (not fabricated) until a CSV exists — see ReplayCsv.metrics().
        "metrics": {},
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
    # FU6 (2026-08-31): a fidelity boundary specific to the current-sense path.
    result["notes"].append(
        "FIDELITY: the injected rail currents are INDEPENDENT of the board's own "
        "switch state, so an OC fault latches on an injected current even in a "
        "switch topology where that current could not physically flow. Clean this "
        "campaign — ML0203's OC_FC latch had FC_BUS closed, so the current had a "
        "real path — but a future stimulus could latch OC on an OPEN path. Check "
        "switch_state at the latch time before reading any replay OC result as a "
        "hardware statement.")
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
    # PURPOSE is per-entry from 2026-08-30: an entry carrying `replay_commands`
    # DOES reach State 2 and DOES step both loops, so the blanket "no commander
    # exists in replay mode" sentence would be false for it.
    cmds_replayed = bool(entry.get("replay_commands"))
    # Set HERE, not with the check counters below: the bring-up gate can return
    # early, and a consumer asking "did this entry replay commands?" must get an
    # answer on that path too (the counters legitimately do not exist there —
    # no entry checks ran).
    result["replay_commands"] = cmds_replayed
    if cmds_replayed:
        result["notes"].append(
            "PURPOSE: bring-up + fault-decision regression AND controller "
            "reaction. This entry sets `replay_commands`, so the log's recorded "
            "v_sp / share_sp ARE replayed as 22-byte Pi command packets at 50 Hz "
            "(hil_plant_sim --replay-commands): the board goes Idle -> Run and the "
            "drive and share loops step against the recorded stimulus. The "
            "current-shape checks therefore judge the LIVE controller's reaction. "
            "Still OPEN LOOP on the plant side — the injected v_actual does not "
            "respond to the commands — so this is reaction, not tracking, and the "
            "loop is EXPECTED to fight the recorded trajectory wherever the "
            "recorded and flashed control laws differ.")
        result["notes"].append(
            "Idle -> Run zeroes v_setpoint and resets the drive controller "
            "(doState1, .ino:5382-5410), so the first real setpoint arrives on the "
            "next 50 Hz packet, <= 20 ms later. Once in Run the command stream is "
            "LOAD-BEARING: the Pi watchdog (PI_TIMEOUT_MS 500, .ino:2915) latches "
            "if it stops.")
    else:
        result["notes"].append(
            "PURPOSE: this half is a BRING-UP + FAULT-DECISION regression harness. "
            "This entry does NOT set `replay_commands`, so no commander exists, the "
            "board never leaves Idle and the commanded current is 0 A throughout; "
            "the current-shape checks assert only that the firmware does NOT drive "
            "on an uncommanded stimulus, and are tagged NOT EXERCISED.")

    try:
        data = load_replay_csv(csv_path, preamble_s=entry_preamble_s(entry))
    except (OSError, ValueError) as exc:
        result["checks"].append({"name": "csv", "passed": False, "detail": str(exc)})
        # A5: `error` is the one metrics field the scenario analyzer sets on a
        # CSV it could not read; mirror it rather than leaving a bare {}.
        result["metrics"] = {"csv": csv_path, "error": str(exc)}
        return result

    result["n_obs"] = data.n_obs
    result["metrics"] = data.metrics(csv_path)
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
        # NOT-EXERCISED tagging: a motor-response check on an entry that did NOT
        # replay commands, whose command series is measurably flat zero, is not a
        # weak pass — it was never exercised. Stated at the FRONT of the detail
        # (the trailing VACUOUS_TAG is what this replaced) and counted separately.
        if (cmds_replayed is False
                and spec.get("kind") in MOTOR_RESPONSE_KINDS
                and data.command_is_identically_zero()):
            detail = NOT_EXERCISED_TAG + detail.replace(VACUOUS_TAG, "")
        result["checks"].append({"name": name, "passed": passed, "detail": detail})

    # Item 5: substantive-vs-total counts, so a reader can see how much of a green
    # entry is actually evidence.  A check is "vacuous"/"not exercised" here only
    # in the precise, measured sense above: its detail carries the tag.
    #
    # The two tags are DISJOINT by construction — NOT_EXERCISED_TAG is applied
    # only after the VACUOUS_TAG has been stripped from the same detail — and both
    # count as non-substantive, so `n_checks_vacuous` keeps its established
    # meaning ("checks that carried no evidence") for run_hil_suite.py's
    # key_metrics rendering while the new counter says how many of those were the
    # sharper case.  Fields are additive; nothing was renamed.
    n_total = len(result["checks"])
    n_not_exercised = sum(1 for c in result["checks"]
                          if c["detail"].startswith(NOT_EXERCISED_PREFIX))
    n_vacuous = sum(1 for c in result["checks"]
                    if VACUOUS_TAG in c["detail"]) + n_not_exercised
    result["n_checks"] = n_total
    result["n_checks_vacuous"] = n_vacuous
    result["n_checks_not_exercised"] = n_not_exercised
    result["n_checks_substantive"] = n_total - n_vacuous
    if n_not_exercised:
        result["notes"].append(
            f"{n_not_exercised} of {n_total} checks were NOT EXERCISED: this entry "
            f"does not set `replay_commands`, so no Pi command packet was sent, the "
            f"board never left Idle and the motor command is identically 0 A. Those "
            f"checks assert only that the firmware did not drive on an uncommanded "
            f"stimulus.")
    if n_vacuous - n_not_exercised:
        result["notes"].append(
            f"{n_vacuous - n_not_exercised} of {n_total} checks are VACUOUS on this "
            f"run: the observed motor command is identically 0 A. SUBSTANTIVE "
            f"checks: {n_total - n_vacuous}.")
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
    # Per-entry stimulus modifiers. ALL THREE (skip_preamble, i_fc_clamp_a,
    # replay_commands) are declared in the entry table and ALL THREE must be
    # mirrored here, or a hand-run replay would silently differ from a suite-run
    # one and the checks (which resolve the same fields) would be scoring a
    # different stimulus than the one that was injected.
    if entry.get("skip_preamble"):
        argv.append("--replay-no-preamble")
    if entry.get("i_fc_clamp_a") is not None:
        argv += ["--replay-i-fc-clamp", "%g" % float(entry["i_fc_clamp_a"])]
    if entry.get("replay_commands"):
        # Third mirrored modifier: without it the entry's drive_loop_stepped check
        # would fail against a run that was never given commands, and its
        # motor-response checks would be scoring a flat zero the entry did not
        # expect.
        argv.append("--replay-commands")
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
    print(f"{'log':8} {'fw':>4} {'blg':>3}  {'mode':11} {'cmds':4} checks")
    print("-" * 84)
    for e in REPLAY_SUITE:
        fw = "-" if e["fw_version"] is None else str(e["fw_version"])
        prov = " *" if e["provisional"] else ""
        cmds = "yes" if e.get("replay_commands") else "no"
        checks = ",".join(c["name"] for c in e["checks"])
        print(f"{e['log']:8} {fw:>4} {e['blg_version']:>3}  {e['mode']:11} "
              f"{cmds:4} {checks}{prov}")
    print("-" * 84)
    n_cmds = sum(1 for e in REPLAY_SUITE if e.get("replay_commands"))
    print(f"{len(REPLAY_SUITE)} entries "
          f"({sum(1 for e in REPLAY_SUITE if e['mode'] == 'conformance')} conformance, "
          f"{sum(1 for e in REPLAY_SUITE if e['mode'] == 'deviation')} deviation); "
          f"* = provisional; cmds = replays the log's recorded v_sp/share_sp as Pi "
          f"command packets ({n_cmds} of {len(REPLAY_SUITE)})")


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
