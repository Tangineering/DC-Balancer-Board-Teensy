#!/usr/bin/env python3
"""
hil_replay_suite.py — the replay-based scenario class for the Teensy HIL rig.

A curated set of REAL bench logs (logs/*.BLG) is replayed at the firmware through
`tools/hil_plant_sim.py --replay`, and the resulting per-tick CSV is evaluated
here against declarative, firmware-version-aware checks.

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
        "log": "ML0203", "path": "logs/ML0203.BLG", "mode": "conformance",
        "fw_version": 18, "blg_version": 6,
        "classification": "clean 'V' velocity run on the 90-slot wheel",
        "why": "The reference clean baseline on the currently flashed control law: "
               "if anything fails here, the failure is in the HIL path, not the log.",
        "provisional": False,
        "checks": [
            {"kind": "no_fault", "name": "no_fault"},
            {"kind": "bounded_current", "name": "bounded_current"},
            {"kind": "no_sustained_rail", "name": "no_sustained_rail",
             "max_episode_s": SUSTAINED_RAIL_S},
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
        "log": "ML0217", "path": "logs/ML0217.BLG", "mode": "conformance",
        "fw_version": 19, "blg_version": 6,
        "classification": "largest manual ('K') run on fw v19",
        "why": "Longest recent stimulus — a duration/soak case for the HIL link.",
        "provisional": True,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
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
        "log": "ML0165", "path": "logs/ML0165.BLG", "mode": "conformance",
        "fw_version": 16, "blg_version": 6,
        "classification": "rung stepladder, fw v16",
        "why": "Multi-level stimulus with clean transitions; stability-only conformance.",
        "provisional": False,
        "checks": [{"kind": "no_fault", "name": "no_fault"},
                   {"kind": "bounded_current", "name": "bounded_current"}],
    },
    {
        "log": "ML0169", "path": "logs/ML0169.BLG", "mode": "conformance",
        "fw_version": 16, "blg_version": 6,
        "classification": "friction-disturbance rejection, ~2.2 s continuous saturation",
        "why": "The saturation-endurance case: the firmware must ride the recorded "
               "saturation episodes out without faulting and come off the rail.",
        "provisional": False,
        "checks": [
            {"kind": "no_fault", "name": "no_fault"},
            {"kind": "bounded_current", "name": "bounded_current"},
            {"kind": "returns_off_rail", "name": "returns_off_rail",
             "level_a": OFF_RAIL_LEVEL_A, "within_s": OFF_RAIL_WITHIN_S},
        ],
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
               "the stimulus class the fw v18 general-Hanus fix targets.",
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

    # ── DEVIATION — the legacy UV trio: the modern firmware MUST latch ───────
    {
        "log": "TP0010", "path": "logs/TP0010.BLG", "mode": "deviation",
        "fw_version": None, "blg_version": 1,
        "classification": "pre-versioning bus collapse; the old firmware died without faulting",
        "why": "UV trio member. The fw v5 leaky-dwell UV filter must latch UV_BUS on "
               "this recorded collapse — that is the whole point of the rework.",
        "provisional": False,
        "checks": [{"kind": "fault_latched", "name": "uv_bus_latched",
                    "bit": FAULT_UV_BUS, "require_stimulus": True}],
    },
    {
        "log": "TP0053", "path": "logs/TP0053.BLG", "mode": "deviation",
        "fw_version": 4, "blg_version": 2,
        "classification": "repetitive source-commutation dropout (~9 ms under / ~51 ms "
                          "over per ~60 ms cycle) that EVADED the fw v4 window filter",
        "why": "UV trio member and the exact case the dwell integrator was designed "
               "for: net +6.45 ms per cycle, so it must latch within a few cycles.",
        "provisional": False,
        "checks": [{"kind": "fault_latched", "name": "uv_bus_latched",
                    "bit": FAULT_UV_BUS, "require_stimulus": True}],
    },
    {
        "log": "WP0097", "path": "logs/WP0097.BLG", "mode": "deviation",
        "fw_version": 5, "blg_version": 3,
        "classification": "fw v5-era bus collapse",
        "why": "UV trio member; third independent collapse shape.",
        "provisional": False,
        "checks": [{"kind": "fault_latched", "name": "uv_bus_latched",
                    "bit": FAULT_UV_BUS, "require_stimulus": True}],
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
     "runtime, not coverage. Three representatives are kept as the UV trio "
     "(TP0010, TP0053, WP0097), chosen for three DIFFERENT collapse shapes."),
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

    def __init__(self, rows, columns):
        self.columns = columns
        self.rows = rows
        # (t, value) series with blanks removed.
        self.current = _series(rows, "t", "current", float)
        self.faults = _series(rows, "t", "fault_flags", _int_any)
        self.v_bus = _series(rows, "t", "V_bus", float)
        self.state = _series(rows, "t", "state", _int_any)
        self.n_rows = len(rows)
        self.n_obs = len(self.current)
        self.duration_s = (float(rows[-1]["t"]) - float(rows[0]["t"])) if rows else 0.0


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


def load_replay_csv(csv_path):
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
    return ReplayCsv(rows, columns)


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


def check_no_fault(data, spec):
    """fault_flags stays 0 for every observed tick.

    `ignore_bits` lets an entry tolerate a specific bit (none do today; the knob
    exists so a future entry does not need a new check kind)."""
    ignore = int(spec.get("ignore_bits", 0))
    if not data.faults:
        return False, "no observation frames in the CSV — nothing was observed"
    worst, worst_t = 0, None
    for t, f in data.faults:
        f &= ~ignore
        if f and worst == 0:
            worst, worst_t = f, t
        worst |= f
    if worst:
        return False, (f"faults raised: 0x{worst:04X} ({_fault_names(worst)}), "
                       f"first at t={worst_t:.3f}s")
    return True, f"fault_flags == 0 across {len(data.faults)} observed ticks"


def check_fault_not_latched(data, spec):
    """A specific bit must never appear (the negative UV cases)."""
    bit = int(spec["bit"])
    hits = [(t, f) for t, f in data.faults if f & bit]
    if not data.faults:
        return False, "no observation frames in the CSV"
    if hits:
        return False, (f"{_fault_names(bit)} set at t={hits[0][0]:.3f}s "
                       f"({len(hits)} ticks) — the recorded dip should NOT latch it")
    return True, f"{_fault_names(bit)} never set across {len(data.faults)} ticks"


def check_fault_latched(data, spec):
    """A specific bit must be set, and still set at the end of the run.

    With `require_stimulus` (default True) the injected V_bus is first replayed
    through the firmware's OWN leaky-dwell filter (LIMIT_V_BUS_MIN /
    UV_BUS_DWELL_*) to confirm the stimulus actually qualifies.  If it does not,
    the check FAILS LOUDLY as inconclusive rather than passing or silently
    excusing the firmware — a suite entry whose stimulus no longer qualifies is
    a suite bug that must be seen."""
    bit = int(spec["bit"])
    if not data.faults:
        return False, "no observation frames in the CSV"
    if spec.get("require_stimulus", True) and bit == FAULT_UV_BUS:
        qualifies, when, peak = _uv_stimulus_qualifies(data)
        if not qualifies:
            return False, (
                f"INCONCLUSIVE: the injected V_bus never accumulates "
                f"{UV_BUS_DWELL_LATCH_MS:.0f} ms of net dwell below "
                f"{LIMIT_V_BUS_MIN_V:.1f} V while armed (peak dwell {peak:.1f} ms) — "
                f"this log is not a UV stimulus for the current filter")
        stim_t = when
    else:
        stim_t = None
    hits = [t for t, f in data.faults if f & bit]
    end_flags = data.faults[-1][1]
    if not hits:
        extra = f" (stimulus qualifies from t={stim_t:.3f}s)" if stim_t is not None else ""
        return False, f"{_fault_names(bit)} was never set{extra}"
    if not (end_flags & bit):
        return False, (f"{_fault_names(bit)} set at t={hits[0]:.3f}s but CLEARED by the "
                       f"end of the run (final 0x{end_flags:04X}) — it must LATCH")
    return True, (f"{_fault_names(bit)} latched at t={hits[0]:.3f}s"
                  + (f", stimulus qualified from t={stim_t:.3f}s" if stim_t is not None else ""))


def _uv_stimulus_qualifies(data):
    """Replay the firmware's UV_BUS leaky dwell integrator over the INJECTED
    V_bus series.  Returns (qualifies, t_at_latch, peak_dwell_ms).

    Mirrors teensy_controller.ino:4690-4735: +dt under LIMIT_V_BUS_MIN,
    -UV_BUS_DWELL_LEAK*dt at/above it, per-tick dt capped at
    UV_BUS_DWELL_DT_CAP_MS, latch at UV_BUS_DWELL_LATCH_MS.  Arming is
    approximated by the bus having reached V_BUS_CHARGED_THRESH at least once
    (.ino:1363) — the switch-state half of the real arming condition is not
    reconstructible from the injected rails alone, which is why this is a
    stimulus SANITY check and not a firmware model."""
    dwell = 0.0
    peak = 0.0
    armed = False
    prev_t = None
    for t, v in data.v_bus:
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
    before the first observation frame do not dilute it."""
    max_rate = float(spec.get("max_alt_per_s", LIMIT_CYCLE_ALT_PER_S))
    level = float(spec.get("level_a", RAIL_LEVEL_A))
    if not data.current:
        return False, "no observation frames in the CSV"
    span = data.current[-1][0] - data.current[0][0]
    eps = _rail_episodes(data.current, level)
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
    for a, b, _s in eps:
        rec = None
        for t, i in data.current:
            if t <= b:
                continue
            if abs(i) < level:
                rec = t - b
                break
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
        "format v1–v7.")

    try:
        data = load_replay_csv(csv_path)
    except (OSError, ValueError) as exc:
        result["checks"].append({"name": "csv", "passed": False, "detail": str(exc)})
        return result

    if data.n_obs == 0:
        result["notes"].append(
            "No observation frames in the CSV — the board never answered. Is it "
            "flashed with -DHIL_SIM=1 -DUSE_ETHERNET=1 and on the right IP?")
    else:
        result["notes"].append(
            f"{data.n_obs}/{data.n_rows} ticks carry an observation frame; "
            f"{data.duration_s:.2f}s of replay.")

    all_passed = True
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
    unambiguous artifact per entry."""
    csv_path = os.path.join(csv_dir, f"hil_replay_{entry['log']}.csv")
    return ["--replay", entry["path"], "--csv", csv_path]


def replay_csv_path(entry, csv_dir):
    """The CSV path build_sim_argv() will ask hil_plant_sim to write."""
    return os.path.join(csv_dir, f"hil_replay_{entry['log']}.csv")


def verify_suite_logs(repo_root="."):
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
