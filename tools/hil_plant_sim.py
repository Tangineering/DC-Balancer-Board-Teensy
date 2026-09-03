#!/usr/bin/env python3
"""
hil_plant_sim.py — soft-real-time plant simulator for the Teensy HIL mode (fw v21).

The real Teensy, flashed with -DHIL_SIM=1 -DUSE_ETHERNET=1, is the device under
test.  This script is the PLANT: it integrates a simple mechanical + electrical
model of the scale-car balancer rig, injects the resulting sensor values into the
board over UDP as engineering units, and reads back the board's actuator state
(state machine, ideal-diode switch bitmask, motor-current command, droop MDAC
codes, fault flags) to close the loop.

Nothing about the firmware's control logic is stubbed: detectFaults(), the
sequencing guards, the Youla drive controller and the power-share loop all run
unmodified on the injected values.  That makes this a fault-INJECTION rig — the
`sag` scenario, for instance, exercises the real undervoltage path.

Wire protocol (mirrored from teensy_controller.ino, fw v21 — keep in lockstep):

  Injection frame (host -> Teensy), 40 bytes, little-endian
    0  u8    sync 0xB5
    1  u8    seq (wraps)
    2  f32   V_fc      [V]
    6  f32   V_batt    [V]
   10  f32   V_bus     [V]
   14  f32   V_chg     [V]
   18  f32   V_rgn     [V]
   22  f32   I_fc      [A]
   26  f32   I_batt    [A]
   30  f32   v_actual  [m/s]
   34  f32   I_charge  [A]  simulated Ag105 reg 0x06 reading, already in amps
   38  u8    ag105_status  raw Table 6 status byte
   39  u8    XOR checksum over bytes 1..38

  (The 35-byte fw v21 layout is RETIRED — it was never flashed.  A 35-byte frame
  no longer matches the firmware's length dispatch and is dropped unread, so an
  old simulator against a new flash shows accepts stuck at zero.)

  Observation frame (Teensy -> host), 18 bytes from fw v25, little-endian
    0  u8    sync 0xB6
    1  u8    seq echo (last accepted injection seq)
    2  u8    mainState
    3  u8    switch_state bitmask (see SW_* below)
    4  u8    aux: bit0 FC_REG_ENABLE, bit1 BT_REG_ENABLE,
                  bit2 MPPT_DISABLE,  bit3 CBAL_DISABLE,
                  bit4 FC ceiling clamp active  APPENDED fw v26,
                  bit5 BT ceiling clamp active  APPENDED fw v26 — the source
                  current-ceiling governor's per-channel clamp state, NOT pin
                  levels.  Spare bits in an existing byte, so HIL_OUTPUT_SIZE
                  stays 18 and the checksum span is unchanged.  A frame from
                  fw v21-v25 simply never sets them, and the CSV columns
                  `fc_ceil`/`bt_ceil` then read 0 rather than blank: absence of
                  the bit is a real observation ("not clamped"), unlike
                  mppt_thresh_cnt/error_code, whose BYTES are absent.
    5  f32   current [A] (post-clamp motor-current command)
    9  u16   last MDAC word, FC channel
   11  u16   last MDAC word, BT channel
   13  u16   fault_flags
   15  u8    mppt_thresh_count  APPENDED fw v24 (.ino:2911-2938) — the Ag105
                  reg-0x02 count the firmware BELIEVES is in force
                  (ag105MpptRegCnt).  0xFF = external-resistor mode / never
                  written (AG105_MPPT_N_RESISTOR, the boot value); 0..250 map
                  to 11.0 + 0.088*N volts (AG105_MPPT_VOLTS, .ino:1671-1677).
   16  u8    error_code  APPENDED fw v25 (.ino:2968-2978) — the LATCHED
                  first-cause ErrorCode_t (.ino:1645-1670), 0 = ERR_NONE.
                  triggerFault() latches the FIRST CAUSE here while it only ORs
                  bits into fault_flags, so this is what separates
                  ERR_PI_TIMEOUT (0x05) from ERR_HIL_STALE (0x10) on the shared
                  0x0010 fault bit.
   17  u8    XOR checksum over bytes 1..16

  ALL THREE LENGTHS ARE ACCEPTED.  16 bytes is fw v21-v23 (XOR over 1..14 at
  byte 15, no mppt_thresh_count, no error_code); 17 is fw v24 (XOR over 1..15 at
  byte 16, no error_code); 18 is fw v25+.  Every pre-existing offset is identical
  in all three, so the length alone selects the checksum span and whether the
  tail bytes are data or the checksum.  parse_output() prints a one-time
  provenance line naming the length the board is actually speaking, and prints
  again — loudly — if a single run ever sees more than one.

Stdlib only — socket, struct, time, argparse, csv.  No numpy.

Usage:
    python3 tools/hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario steady \
            --duration 30 --csv hil_run.csv

OUTPUT (see docs/HIL_USER_MANUAL.md Sec 2.5)
CSV logging is ON BY DEFAULT.  Without --csv the run names itself
`hil_<scenario>_<mode>_<YYYYmmdd_HHMMSS>.csv` under "<repo>/HIL Results";
--no-csv turns logging off entirely (CSV, .meta.json AND the hi-fi events
sidecar), and an explicit --csv whose CSV or either sidecar already exists is
REFUSED with EXIT CODE 2 unless --force.  Every CSV is accompanied by a `<csv>.meta.json`
sidecar naming the scenario, the command mode, the resolved configuration, a
sha256 over the model constants, the git rev, and the run's results.  The
sidecar is written before the loop starts (status "running") and rewritten at
exit, so even a killed run leaves a record of what was attempted.

REPLAY MODE (--replay PATH.BLG) swaps the simulated plant for a recorded bench
log: the .BLG's rail/current/velocity samples are streamed back at the board as
injection frames, turning a recorded bench incident into a repeatable stimulus.
The plant integrator is BYPASSED — replay is OPEN LOOP, the firmware's commands
do not influence the replayed trajectory.  See docs/HIL_MODE.md "Replay mode".
"""

import argparse
import bisect
import csv
import datetime
import hashlib
import json
import math
import os
import socket
import struct
import subprocess
import sys
import time

# ─────────────────────────────────────────────────────────────────────────────
# Protocol constants — must match teensy_controller.ino (fw v24)
# ─────────────────────────────────────────────────────────────────────────────
HIL_SYNC_INJECT = 0xB5
HIL_SYNC_OUTPUT = 0xB6
HIL_INJECT_SIZE = 40
# OBSERVATION FRAME LENGTH IS VERSIONED (fw v25, .ino:2955-2981 HIL_OUTPUT_SIZE).
# 18 is the current layout; 17 (fw v24) and 16 (fw v21-v23) are still decoded,
# because a simulator that silently drops every frame from an older flash
# presents as "the board is dead" rather than "the board is old".  The three
# differ ONLY in the tail — byte 15 is mppt_thresh_count from fw v24, byte 16 is
# error_code from fw v25 — so the checksum SPAN is length-derived and every
# field below the appended tail parses identically in all three.
HIL_OUTPUT_SIZE = 18            # fw v25 and later
HIL_OUTPUT_SIZE_V24 = 17        # fw v24
HIL_OUTPUT_SIZE_LEGACY = 16     # fw v21-v23
HIL_OUTPUT_SIZES = (HIL_OUTPUT_SIZE_LEGACY, HIL_OUTPUT_SIZE_V24, HIL_OUTPUT_SIZE)

# ErrorCode_t (.ino:1645-1670).  APPEND-ONLY by firmware contract, so an unknown
# value here means "newer firmware than this tool", never "corrupt" — consumers
# render the raw hex and say so rather than dropping the reading.
ERROR_CODE_NAMES = {
    0x00: "ERR_NONE",
    0x01: "ERR_OC_FC",
    0x02: "ERR_UV_BATT",
    0x03: "ERR_OV_BUS",
    0x04: "ERR_SWITCH_CONFLICT",
    0x05: "ERR_PI_TIMEOUT",
    0x06: "ERR_OV_BATT",
    0x07: "ERR_UV_FC",
    0x08: "ERR_OC_BT",
    0x09: "ERR_UV_BUS",
    0x0A: "ERR_OV_RGN",
    0x0B: "ERR_OV_CHG",
    0x0C: "ERR_I2C_CHARGER",
    0x0D: "ERR_CHARGER_STAT",
    0x0E: "ERR_INIT_FAIL",
    0x0F: "ERR_MOT_HOTPLUG",
    0x10: "ERR_HIL_STALE",
}
# The two codes that share fault bit 0x0010 and that fw v25's frame extension
# exists to separate.  Named here so every consumer (dashboard, suite excusal,
# pi-silence attribution) cites one definition.
ERR_PI_TIMEOUT = 0x05
ERR_HIL_STALE = 0x10


def error_code_name(code) -> str:
    """'ERR_UV_BUS (0x09)' — or '0x21 (unknown)' for a code newer than this tool."""
    if code is None:
        return "unknown"
    n = int(code) & 0xFF
    known = ERROR_CODE_NAMES.get(n)
    return ("%s (0x%02X)" % (known, n)) if known else ("0x%02X (unknown)" % n)


TEENSY_PORT_DEFAULT = 5001          # local_port in the .ino

SW_FC_BUS, SW_BT_BUS, SW_MOT_PWR = 0x01, 0x02, 0x04
SW_REGEN, SW_FC_CHARGE, SW_BT_SEQ = 0x08, 0x10, 0x20

AUX_FC_REG, AUX_BT_REG = 0x01, 0x02
AUX_MPPT_DISABLE, AUX_CBAL_DISABLE = 0x04, 0x08
# fw v26 (.ino readHilAuxState) — bits 4/5 are NOT pin levels like bits 0-3:
# they mirror the source current-ceiling governor's clamp state per channel.
# They live in the aux byte rather than in `switch_state` deliberately, because
# `switch_state` is the TOPOLOGY word this simulator solves the network from.
# Spare bits in an existing byte: HIL_OUTPUT_SIZE stays 18 and the checksum span
# is unchanged, so no protocol version moves and a host that does not know them
# masks them off exactly as before.
AUX_FC_CEILING, AUX_BT_CEILING = 0x10, 0x20

# ── Mid-run warm-reset tripwire ─────────────────────────────────────────────
# From fw v23 the board can leave its latched State 99 on its own: after a RUN
# BOUNDARY (the injection link continuously dead for HIL_RUN_BOUNDARY_MS =
# 1000 ms) plus 500 ms of continuously fresh link, it warm-resets to State 0 and
# brings the stage back up.  Between runs that is exactly what the suite wants.
# MID-RUN it is a hazard: a >= 1 s host stall (GC, a laptop sleeping a core, a
# blocked write) followed by resumed streaming looks identical to a run boundary,
# so the board recovers and clears a fault it had latched.
#
# WHAT THE HAZARD ACTUALLY IS — state it precisely, because the loose version
# ("a latched fault silently disappears") is wrong for the checks that exist:
# a check reading the fault UNION over the run, or the final latched flags, sees
# the fault fire and fails loudly.  The real damage is subtler and worse:
#   * after the reset the board is in State 0 -> bring-up -> Idle, so THE REST OF
#     THE RUN IS NOT THE SCENARIO the checks assume — the stimulus timeline keeps
#     playing against a board that restarted underneath it;
#   * a fault that fires again after the reset reads as having fired ONCE, so
#     "did it latch?" answers yes for the wrong reason and any dwell/timing
#     conclusion drawn from it is wrong;
#   * a check keyed to the FINAL state or FINAL flags reads the post-recovery
#     board, which is clean, and passes.
# None of that is recoverable after the fact, which is why the run is marked
# inconclusive rather than interpreted.  Every observed transition out of State
# 99 is counted here so the run can be judged, not trusted.
#
# The count is over 99 -> ANY other state, not literally 99 -> 0: State 99 is
# latched and the HIL warm reset is its ONLY exit, so this cannot false-positive,
# and it cannot false-NEGATIVE on a dropped observation frame that hid the brief
# State 0 (the board is in State 0 only for the bring-up).
WARM_RESET_GRACE_S = 2.0     # transitions before this are the START-OF-RUN
                             # recovery from the previous run's settle pause —
                             # expected, and not counted as mid-run.  Earliest a
                             # genuine mid-run one can land is ~1.5 s (1000 ms
                             # boundary + 500 ms fresh), so 2.0 s separates them.
WARM_RESET_TIMES_MAX = 16    # cap on the recorded transition times (the count
                             # itself is never capped)

# ─────────────────────────────────────────────────────────────────────────────
# Ag105 Table 6 status byte — authoritative values from
# references/Datasheets/Ag105_Table6_I2C_Status_Byte.json (Ag105 DS V1.1, Table 6).
# Bits 0-2 are the GENSTAT enum; bits 3-7 are independent flags.
# ─────────────────────────────────────────────────────────────────────────────
AG105_ST_DISCONNECT = 0x00      # GENSTAT 000 — Battery Disconnect
AG105_ST_LOW_POWER = 0x01       # GENSTAT 001 — Low Power
AG105_ST_CHARGING = 0x02        # GENSTAT 010 — Charging
AG105_ST_FULL = 0x03            # GENSTAT 011 — Fully Charged
AG105_ST_BRINGUP = 0x04         # GENSTAT 100 — Bring-Up Charge
AG105_ST_OC_ERR = 0x05          # GENSTAT 101 — OC/Regulation Error
AG105_ST_THERMAL_SD = 0x06      # GENSTAT 110 — Thermal Shutdown
AG105_ST_TIMEOUT_ERR = 0x07     # GENSTAT 111 — Timeout Error
AG105_FLAG_MPPT_EN = 0x08       # bit 3 — MPPT enabled
AG105_FLAG_PWR_TRACK = 0x10     # bit 4 — charge profile tracking input power
AG105_FLAG_CV = 0x20            # bit 5 — constant-voltage mode
AG105_FLAG_CC = 0x40            # bit 6 — constant-current mode
AG105_FLAG_THERM_LIM = 0x80     # bit 7 — thermal limiting

# Charger model.  The firmware configures the Ag105 for the 2.5 A profile
# (reg 0x00 = 0x01, Ag105_Table4_Charge_Current_Select.json) into a 2S/8.4 V pack.
AG105_I_MAX = 2.5            # A     configured charge-current ceiling
AG105_SETTLE_S = 0.5         # s     matches AG105_SETTLE_MS in the .ino
AG105_TAU_S = 0.4            # s     first-order ramp of the measured current
AG105_V_IN_MIN = 8.0         # V     input rail below which the module cannot charge

# ── MPPT input-voltage threshold (Layer 1 emulation, 2026-08-31) ────────────
# ⚠️ DATASHEET CORRECTION.  The Ag105's MPPT is an INPUT-VOLTAGE-THRESHOLD
# regulator, NOT a perturb-and-observe tracker.  AG105_Silvertel.pdf p.10:
# charging commences only when the input voltage exceeds a threshold, settable
# 11-33 V through an MPPTS resistor or I2C register 0x02, and DEFAULTING TO 18 V
# with MPPTS open.  The "perturb-and-observe" wording that appears in
# teensy_controller.ino's comments and in CLAUDE.md Sec 3 is repo lore with no
# datasheet backing; it is corrected in the tooling docs and in the Plant
# docstring below.  Nothing in the FIRMWARE depends on the distinction — it
# drives one GPIO either way — but a plant model that claims to emulate MPPT
# must emulate the mechanism the part actually has.
#
# ⚠️ THIS CONSTANT IS NOW ONLY THE FALLBACK (fw v24, 2026-09-01).  The threshold
# the model applies is whatever the BOARD says is in force: the observation
# frame's byte 15 (`mppt_cnt`) carries the reg-0x02 count the firmware believes
# it has written, and ag105_mppt_volts() converts it.  This 18.0 is used ONLY
# when there is no count to use —
#     * `mppt_cnt` is 0xFF / >250: external-resistor mode or never written, which
#       IS the datasheet default of 18 V with MPPTS open;
#     * `mppt_cnt` is None: a legacy 16-byte frame (fw v21-v23), whose firmware
#       had no threshold manager and therefore left the module at its default;
#     * no observation frame has arrived yet.
# In all three the module is genuinely at its factory threshold, so the fallback
# is the physical value, not a placeholder.
#
# R1 — RESOLVED AS A DESIGN DEPENDENCY (fw v24).  Table 7's own encoding settles
# it: reg 0x02 values 0-250 select REGISTER mode and >=251 selects the resistor,
# so a firmware write OVERRIDES any fitted MPPTS resistor.  Whether the board
# fits one is now documentation, not a contingency — once the firmware has
# written a count, the fitted resistor cannot decide the threshold.  It still
# matters for the pre-write window, which is exactly the fallback above.
AG105_MPPT_V_THRESH = 18.0   # V     FALLBACK threshold (module default, MPPTS open)
# Register 0x02 encoding, from Ag105_Table7_I2C_Parameters.json / AG105_Silvertel.pdf
# Table 7, mirrored from the firmware's own constants (.ino:1671-1677) so the two
# cannot drift: 11 V at count 0, 0.088 V/count, 0..250 = I2C threshold,
# >=251 = external-resistor mode (0xFF is the factory default).
AG105_MPPT_V_BASE = 11.0        # V     threshold at count 0
AG105_MPPT_V_PER_CNT = 0.088    # V/count
AG105_MPPT_N_MAX = 250          # highest count that still means "I2C threshold"
AG105_MPPT_N_RESISTOR = 0xFF    # >=251 = external-resistor mode
# The firmware's clamp band (.ino AG105_MPPT_N_FLOOR / _N_CEIL) — 12.320 V to
# 13.376 V.  Not used by the model (it applies whatever count the board reports,
# clamped or not); mirrored here so the suite's threshold-band expectation and
# the report figure have one source for the band.
AG105_MPPT_N_FLOOR = 15
AG105_MPPT_N_CEIL = 27
# TODO(verify): chatter guard on the threshold COMPARISON only (not on the pin).
# No datasheet hysteresis figure is published; 0.5 V is a modelling choice sized
# to be well above the simple engine's bus ripple and well below the gap between
# the bus and whichever threshold is in force, so it cannot decide the scenario's
# outcome either way.  It was sized against the ~2 V fw v23 gap (15.95 V bus vs
# the 18 V default); under fw v24's clamped 12.320 V the gap is ~3.6 V, so the
# same 0.5 V is if anything further from deciding anything.
AG105_MPPT_V_HYST = 0.5      # V

# MDAC word format (AD5443): control nibble 0x1 = load-and-update, then a 12-bit code.
MDAC_CMD_LOAD_UPDATE = 0x1000
MDAC_RES = 4095

# ─────────────────────────────────────────────────────────────────────────────
# Calibrated plant constants.
#
# Mechanical: from the fw v14 K_F force-axis correction — see
# controller_design_MIMO/calibration/motor_id_20260815.md and CLAUDE.md's
# fw v14 addendum.  m_eff was confirmed at 3.5 kg by that same round.
# ─────────────────────────────────────────────────────────────────────────────
M_EFF = 3.5          # kg      effective translational mass at the flywheel rim
K_F = 0.7538         # N/A     motor current -> tractive force (PHI 6.86, r_tire 0.033 m)
F_COULOMB = 2.00     # N       thermal Coulomb friction (2.00 +/- 0.42 N)
B_EFF = 0.534        # N*s/m   viscous drag
V_STICTION = 0.02    # m/s     |v| below which the Coulomb term is treated as static

# ── Regen / braking energy path (WP-C, 2026-09-01) ──────────────────────────
# BEFORE THIS ROUND the plant floored regen power at zero (`p_mech = max(0, F*v)`)
# while applying the UNCLIPPED braking force mechanically.  That was wrong on two
# counts at once: the braking force was overstated (the VESC's Battery Regen Max
# really does clip regen torque) and the energy it removed from the flywheel simply
# vanished from the model.  Braking now flows end to end: kinetic energy -> VESC
# regen -> V-MOT -> (chopper clamp burns the fast excess) -> D-BC-RG -> VCHG-IN ->
# Ag105 -> pack coulomb count.
#
# TODO(verify) — VESC_REGEN_I_MAX_A.  The bench setting is Battery Regen Max
# 1.5 A (operator, 2026-08-16), and logs 153-162 measured -12 A COMMANDED against
# ~6 % delivered (CLAUDE.md 2026-08-17b), i.e. ~0.7 A of the 12 A actually
# returned.  The commanded-vs-delivered MAPPING has never been characterized, and
# the setting is BATTERY-referred while `i_cmd` is MOTOR-referred; this model
# applies the number directly to the motor-side command.  M5 (reviewer,
# 2026-09-01) corrected the direction of this bias: it is CONSERVATIVE on BOTH
# the force axis AND the harvest axis, not "conservative-force /
# optimistic-harvest" as previously stated here.  At 3 m/s the motor-referred
# 1.5 A cap yields 2.71 W of motor-side regen power, which maps to only
# ~0.17 A on the battery side — well BELOW the ~0.7 A battery-side current
# bench logs 153-162 actually measured. Both directions of the mapping
# undercount versus what was observed. Closing it needs the queued "VESC
# regen-ceiling characterization" bench item.
VESC_REGEN_I_MAX_A = 1.5     # A   regen-side clip on the commanded motor current
# TODO(verify) — ETA_REGEN.  Round-trip mechanical->electrical efficiency of the
# regen path: motor copper + iron loss, inverter conduction/switching loss, and the
# 470 uF link ESR.  0.80 is the reciprocal-of-ETA_BOOST class figure the drive
# direction already uses (ETA_BOOST 0.85) de-rated for the harder braking corner;
# it is a modelling choice, not a measurement, and the same bench item closes it.
ETA_REGEN = 0.80             # -   mechanical braking power -> electrical, at V-MOT

# ── ROAD-LOAD DRAG PROFILES (2026-09-02, the ftp75c round) ──────────────────
# THE PROBLEM.  The rig road load is F_road(v) = F_COULOMB*sgn(v) + B_EFF*v,
# which exceeds 2.00 N at any speed above the stiction band.  Regeneration needs
# M_EFF*|a| > F_road(v), i.e. |a| > 0.571 + 0.153*v m/s^2 - and the FTP-75
# segment's peak deceleration is 0.175 m/s^2 (0.349 m/s^2 compressed).  THE RIG,
# AS INSTRUMENTED, REGENERATES NOTHING, and time compression alone does not
# change that.  Road-load COMPENSATION does, and it is the compensation and not
# the compression that creates the braking energy.
#
# THE DERIVATION (docs/modeling/ftp75c_regen_cycle_design_20260902.md §3.2).
# The paper vehicle's road load is taken as air drag alone,
#     F_d(v_v) = 0.5*rho*Cd*A_f*v_v^2 = 0.505313 * v_v^2   [N]
# and the scaling study's force scale is S_L^3 at the corresponding vehicle
# speed v_v = v/S_L, so the RIG drag collapses to a single quadratic constant:
#     k_air = 0.5*rho*Cd*A_f*S_L = 0.505313 * 0.1183563 = 0.0598069 N/(m/s)^2
# with S_L = 3.0/25.3472 the study's length scale.  The Coulomb term is ZERO in
# the compensated profiles: the compensation REPLACES the rig's friction rather
# than adding to it.
#
# ⚠️ Cd = 0.33 and A_f = 2.5 m^2 are NEXO-class ASSUMPTIONS - neither is in the
# extracted text of the scaling paper.  TODO(verify: operator).  k_air is LINEAR
# in their product, so an operator correction of Cd*A_f scales it and every
# drag-dependent figure proportionally.
#
# THE TWO COMPENSATED MODES, and why there are two.  `scaled-air` is the ruled
# derivation above and delivers 51.25 % of braking kinetic energy as shaft regen
# on `ftp75c`.  The FULL-SCALE vehicle on the same air-drag-only road load
# delivers 79.09 %.  The gap is exactly the residual drag-to-inertia ratio
#     (drag/inertia)_rig / (drag/inertia)_vehicle
#         = S_L^2 * 2242 kg * TIME_FACTOR / M_EFF = 4.4866
# - the rig is still 4.49x too light for the drag it has been given, even after
# compression halves the deficit.  Dividing k_air by that residual gives
# `scaled-air-matched`, which reproduces the full-scale share to five
# significant figures.  ⚠️ THE `ems-ftp75c-*` SCENARIOS RUN `scaled-air`
# (operator ruling, 2026-09-02); `scaled-air-matched` ships as a named profile
# so the choice between the two can be made on measurements rather than on a
# re-derivation.
#
# ⚠️ THE MEASURED RIG PROFILE REMAINS THE DEFAULT AND THE BENCH PROFILE.  It is
# what the hardware actually does, and §7 of the design note records why the
# compensation cannot be replicated on the bench with the single motor now
# fitted (a friction feedforward keeps the net motor force POSITIVE through a
# stop, so no current ever reverses; it needs a second, road-load motor).
DRAG_MODE_RIG = "rig"
DRAG_MODE_SCALED_AIR = "scaled-air"
DRAG_MODE_SCALED_AIR_MATCHED = "scaled-air-matched"
DRAG_MODES = (DRAG_MODE_RIG, DRAG_MODE_SCALED_AIR, DRAG_MODE_SCALED_AIR_MATCHED)
DRAG_MODE_DEFAULT = DRAG_MODE_RIG
# The scaling study's length scale, 3.0 m/s rig peak against the cycle's
# 25.3472 m/s (56.7 mph) vehicle peak.
DRAG_SCALE_LENGTH = 3.0 / 25.3472
# Residual drag-to-inertia ratio of the COMPRESSED rig against the vehicle, at
# the registered TIME_FACTOR of 0.5 (see the derivation above).
DRAG_INERTIA_RESIDUAL = DRAG_SCALE_LENGTH ** 2 * 2242.0 * 0.5 / M_EFF
K_AIR = 0.5 * 1.225 * 0.33 * 2.5 * DRAG_SCALE_LENGTH   # N/(m/s)^2, 0.0598069
K_AIR_MATCHED = K_AIR / DRAG_INERTIA_RESIDUAL          # N/(m/s)^2, 0.0133300


def drag_k_air(drag_mode):
    """The quadratic drag coefficient [N/(m/s)^2] a drag mode realizes.

    ZERO for `rig`, which carries no quadratic term at all - its road load is
    the Coulomb-plus-viscous pair.  A caller testing `k_air == 0.0` is testing
    "is this the measured rig profile", and that is the intended reading."""
    if drag_mode not in DRAG_MODES:
        raise ValueError("drag_mode must be one of %s, got %r"
                         % (DRAG_MODES, drag_mode))
    if drag_mode == DRAG_MODE_RIG:
        return 0.0
    return K_AIR if drag_mode == DRAG_MODE_SCALED_AIR else K_AIR_MATCHED


def drag_era_label(drag_mode):
    """A short, printable name for a drag profile - for headers and manifests."""
    if drag_mode == DRAG_MODE_RIG:
        return "measured rig road load (F_c + b_eff*v)"
    return "%s road-load compensation (k_air = %r N/(m/s)^2, F_c = 0)" % (
        drag_mode, drag_k_air(drag_mode))

# Lumped simple-mode motor-node model (hi-fi solves the real network instead).
# The RT1987 in MOT_PWR is an IDEAL DIODE: it conducts bus->motor, and its reverse
# comparator opens it once the motor node rises RT_V_REV (50 mV) above the bus.
# So regen current does NOT flow back into VBUS — it charges the motor node until
# the chopper clamps it, which is precisely the bench observation "V_rgn 13.3 ->
# 18.1 V held, V_bus unmoved" (CLAUDE.md 2026-08-17b).  The residual bus coupling
# through that 50 mV comparator band is the ~0.03-0.06 V the hi-fi engine's own
# banner predicts; simple mode does not resolve it and holds V_bus unmoved.
# (literal rather than C_VESC_DEFAULT: this block sits ABOVE the hil_electrical
#  import.  Same value, pinned equal by test.)
C_MOT_NODE_F = 500e-6           # F   V-MOT bulk (link + VESC input caps); this is
                                #     hil_electrical.C_VESC_DEFAULT, pinned by test

# Electrical.  V_BUS_NOMINAL and the rails below are the .ino's own constants
# (V_BUS_NOMINAL 16.0f; LIMIT_V_BUS_MIN 12.0f; LIMIT_V_BATT_MIN 6.2f; 2S pack
# 7.4-8.4 V; the H-20 fuel cell is a ~13 V-class source with LIMIT_V_FC_MIN 6.0f).
V_BUS_NOMINAL = 16.0     # V   the firmware's own constant; kept for reference

# ── MEASURED bus droop ──────────────────────────────────────────────────────
# Fit of V_bus against I_fc + I_batt over quasi-steady 200 ms blocks of TP0170-0180
# (TP0178 EXCLUDED — that is the handoff-sag log, not a steady operating point),
# ML0165 and ML0169, all fw v16.  Two clearly separated regimes:
#     both sources live   0.0740 +/- 0.004 V/A
#     exactly one live    0.1615 +/- 0.001 V/A   (FC and BT symmetric within 2 %)
# with no-load intercepts landing in 15.943-15.957 V, hence V_BUS_DROOP_V0 = 15.95
# rather than the firmware's nominal 16.0 (which stays above, for reference).
#
# OPEN FINDING, deliberately not hidden: the realized droop is ~4x BELOW the MDAC
# droop-chain design value.  The design predicts R_e = RE_MAX*g = 2.014*0.298
# = 0.60 ohm per channel, i.e. 0.30 V/A with both channels sharing — four times the
# measured 0.074 V/A.  Nothing in the repo explains the discrepancy yet; the hi-fi
# electrical engine (hil_electrical.py) reproduces the DESIGN value by construction,
# so running the same scenario in both modes shows the gap directly.
#
# ⚠️ MEASURED ON HARDWARE, 2026-08-30c (campaign 20260830_203006, handoff-sag trace,
# and it closes charge-regen's sag follow-up).  The hi-fi engine's realized droop
# was FITTED from a live HIL trace at **0.316 ohm shared / 0.633 ohm single, ratio
# exactly 2.000, V0 = 15.867 V** — i.e. the DESIGN chain (0.30 V/A at g = 0.298),
# +5%, confirmed rather than assumed.  So the two electrical modes differ by ~4x in
# BUS SAG DEPTH for the same load, by construction and not by defect:
#   * simple mode reproduces the BENCH-MEASURED droop and is what a bench log looks
#     like;
#   * hi-fi mode reproduces the DESIGNED droop and sags ~4x deeper.
# Consequences, both load-bearing when reading a hi-fi trace: sag figures are
# CONSERVATIVE (a UV/sag test that passes in hi-fi passes with margin on the real
# bus), and they are NOT COMPARABLE to a recorded bench log or to a simple-mode run.
# charge-regen's 0.49 V sag under 1.54 A is exactly 1.54 * 0.316 — arithmetic, not an
# anomaly.  Closing the gap means reconciling hil_electrical's FB-node superposition
# against the measured fit; until then this banner is the disclosure.
#
# ⚠️ MEASURED MODE AVAILABLE (2026-09-01, `--droop measured`) — AND IT DOES NOT
# CLOSE THIS FINDING.  The hi-fi engine can now be asked to realize the BENCH
# droop instead of the design one (hil_electrical.DROOP_SCALE, a single
# empirical scale factor on each channel's realized droop resistance).  That
# makes hi-fi sag depths comparable with a bench log, which is the whole point
# of the switch; it EXPLAINS NOTHING.  The 4x gap between the MDAC droop chain
# and the bench fit is exactly as open as it was, and the mode adds a second
# open detail of its own: the network's shared/single ratio is structurally
# 2.000 while the bench fit's is 2.182, so one scalar cannot land both regimes
# (the anchor and the residual are stated at DROOP_SCALE).  `--droop design`
# remains the DEFAULT, so every existing baseline and every recorded campaign
# number is unaffected.
K_DROOP_BUS_SHARED = 0.074   # V/A  both sources live
K_DROOP_BUS_SINGLE = 0.16    # V/A  exactly one source live
V_BUS_DROOP_V0 = 15.95       # V    measured no-load intercept
# Back-compatible alias: the shared-source value is the common case.
K_DROOP_BUS = K_DROOP_BUS_SHARED

ETA_BOOST = 0.85         # boost-stage efficiency, motor draw -> bus current
I_AUX_A = 0.15           # A     fixed housekeeping load on the bus
C_BUS_F = 470e-6         # F     bus bulk capacitance (decay when no source is closed)
# ohm   effective bleed across that capacitance.  2000 -> 30e3 on 2026-09-02
# (operator ruling, the DP-bound round): the physical bus decays full-to-near-
# zero in 30-60 s, and 2 kOhm against C_BUS_F emptied it in ~1 s.  Pinned to
# `hil_electrical.R_NODE_BLEED_BUS` by test so the simple engine's dark-bus
# decay and the hi-fi engine's N_BUS bleed cannot drift apart.  This constant
# reaches ONLY the no-source-closed decay branch below; the simple engine's
# LIVE bus law is K_DROOP_BUS_* / V_BUS_DROOP_V0 and is deliberately untouched.
# TODO(calibrate): see the bench decay-capture procedure at
# `hil_electrical.R_NODE_BLEED_BUS`.
R_BUS_BLEED = 30e3

# ── Source models ───────────────────────────────────────────────────────────
# The fuel-cell polarization model and the battery SOC/OCV model live in
# hil_electrical.py (SOURCE MODELS block) so BOTH electrical modes share one
# instance of each.  See docs/HIL_PLANT.md "Source models".
# (path insert so `python3 tools/hil_plant_sim.py` from the repo root and
#  `from hil_plant_sim import SCENARIOS` from a sibling both resolve the module.)
_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
from hil_electrical import (                                   # noqa: E402
    BatterySource, FuelCellSource, ElectricalSim, NoiseConfig,
    BATT_CAPACITY_AH, C_VESC_DEFAULT,
    # WP-C regen path: ONE definition of the chopper law and of the regen
    # source's bounds, shared by both electrical modes so they cannot drift.
    V_CHOPPER_TRIP, R_CHOPPER, chopper_dump_current,
    V_REGEN_OC_MAX, REGEN_I_SRC_MAX_A,
    # Ag105 charge efficiency (2026-09-01).  ONE literal, defined in
    # hil_electrical because that is where the hi-fi charger stamp lives and
    # because the dependency only ever runs electrical -> plant (hil_electrical
    # must not import hil_plant_sim).  Simple mode consumes the same constant
    # so the two engines cannot bill the charger differently; see the
    # "CHARGER BILLING" block in Plant.step().
    ETA_CHG, V_CHG_LOAD_FLOOR,
    # Per-node bleed (2026-09-02) and the RT1987 forward-conduction constants.
    # The DP's static-loss map is written in terms of exactly these, so the
    # bound and the plant it bounds cannot carry two different bleeds; see
    # `loss_map_for_config()` below.
    R_NODE_BLEED_BUS, R_NODE_BLEED_OTHER, node_bleed_conductances,
    N_BUS as _N_BUS, N_MOT as _N_MOT,
    RT_V_FWD, RT_R_ON,
    # WP-E droop realization mode.  DROOP_SCALE is the mode -> scale map and
    # DROOP_MODES its key tuple (the `--droop` choices); both live in
    # hil_electrical because that is where the droop chain is realized.
    # DROOP_MODE_DEFAULT is the `--droop` default, single-sourced there so the
    # flag's default and the "was --droop passed explicitly" test cannot drift.
    DROOP_SCALE, DROOP_MODES, DROOP_MODE_DEFAULT,
    # PART A (C1) converter asymmetry.  The constants live in hil_electrical
    # because that is where the two boost chains are realized; simple mode
    # consumes only the resolved DeltaV0 through asymmetry_dv0_v().
    ASYMMETRY_MODES, ASYMMETRY_MODE_DEFAULT, asymmetry_dv0_v,
    asymmetry_dv0_sense_v, ASYM_DV0_V, ASYM_K_DROOP_OHM, INA_ZERO_OFFSET_A,
    ASYM_DROOP_SCALE_FC, ASYM_DROOP_SCALE_BT,
)

# The shared regen chain (2026-09-02).  STDLIB ONLY, imported as a module so the
# era-label vocabulary reads the same here as it does in the DP generator, the
# walk and the MPC.  See tools/regen_power.py's docstring for why the chain is
# shared rather than written four times.
import regen_power                                             # noqa: E402

# ── PART A: simple-mode share-law constants ─────────────────────────────────
#: the firmware's droop design constant k_d, ohm (`K_DROOP`, .ino:2166-2167).
#: Simple mode needs it because the static asymmetry law is written in terms of
#: the COMMANDED droop resistance, not of any resistance this model realizes.
#: ⚠️ It is PINNED EQUAL to hil_electrical.ASYM_K_DROOP_OHM by the assert below
#: and by test: the fitted DeltaV0 is a lumped A*k_d at the DESIGN droop, so the
#: k_d used to convert it back to a share deviation must be the same k_d on both
#: sides of the plant or the two engines model different asymmetries.
K_DROOP_FW_OHM = 0.30
assert K_DROOP_FW_OHM == ASYM_K_DROOP_OHM
#: total bus current below which the static asymmetry correction is not applied.
#: The r(1-r)/I_tot term diverges at zero load, and below this current the share
#: is not a controlled quantity on the real board either (the firmware's own
#: closed-loop entry sits at 0.60 A).  The clip to [0, 1] still bounds the
#: result; this floor keeps the model from spending its whole authority on a
#: current that no observer cares about.
ASYM_SIMPLE_I_MIN_A = 0.10
# GENERATED module — tools/gen_ftp75_profile.py, from the committed EPA raw
# file references/drive_cycles/ftpcol.txt (sha256 verified at generation).
# Never hand-edited; regenerate instead.  See the `ems-ftp75-*` scenarios.
from ftp75_profile import (                                    # noqa: E402
    FTP75_PROFILE, FTP75_T_END, FTP75_RAW_SHA256, FTP75_SCALE_MPH_TO_MPS,
)
# ...and the GENERATOR, imported purely to BIND the generated module to it.
# gen_ftp75_profile's module scope is constants and pure functions only (its
# argparse surface is entirely inside main()), so importing it costs nothing and
# opens no files.  Without this binding a hand-edited or stale ftp75_profile.py
# is indistinguishable from a freshly generated one: the table would silently
# become "some numbers" rather than "the EPA bytes times one constant", which is
# the entire reason the generator exists (see its docstring, and the fw v8
# slot-count transcription lesson in CLAUDE.md).  Two equalities are enough to
# pin the chain end to end — the RAW INPUT (sha256 of ftpcol.txt) and the ONE
# TRANSFORM applied to it (the mph -> m/s scale).
import gen_ftp75_profile                                       # noqa: E402
if (FTP75_RAW_SHA256 != gen_ftp75_profile.RAW_SHA256
        or FTP75_SCALE_MPH_TO_MPS != gen_ftp75_profile.SCALE_MPH_TO_MPS):
    raise ImportError(
        "tools/ftp75_profile.py is STALE or HAND-EDITED - it does not match "
        "tools/gen_ftp75_profile.py.\n"
        "  raw sha256 : generated %s\n"
        "               generator %s\n"
        "  mph->m/s   : generated %r\n"
        "               generator %r\n"
        "Regenerate with:\n"
        "    .venv_hil/Scripts/python.exe tools/gen_ftp75_profile.py --force"
        % (FTP75_RAW_SHA256, gen_ftp75_profile.RAW_SHA256,
           FTP75_SCALE_MPH_TO_MPS, gen_ftp75_profile.SCALE_MPH_TO_MPS))

# THE COMPRESSED CYCLE (2026-09-02), from the SAME generator and the SAME EPA
# bytes at --time-factor 0.5.  See the `ems-ftp75c-*` scenarios and
# docs/modeling/ftp75c_regen_cycle_design_20260902.md.
from ftp75c_profile import (                                   # noqa: E402
    FTP75C_PROFILE, FTP75C_T_END, FTP75C_POINTS, FTP75C_RAW_SHA256,
    FTP75C_SCALE_MPH_TO_MPS, FTP75C_TIME_FACTOR,
)
# The same end-to-end binding the uncompressed table gets, plus ONE more
# equality that is specific to this table: the POINT COUNT.  The collinear
# decimation compares a RATIO of time differences and is therefore invariant
# under a uniform time scaling, so the compressed table must reduce to exactly
# the same 234 points as its sibling.  A divergence would mean the time-scaling
# change perturbed the decimation - a defect, not a stimulus choice - and it is
# the one failure the sha256 and the scale constant between them cannot see.
if (FTP75C_RAW_SHA256 != gen_ftp75_profile.RAW_SHA256
        or FTP75C_SCALE_MPH_TO_MPS != gen_ftp75_profile.SCALE_MPH_TO_MPS
        or FTP75C_POINTS != gen_ftp75_profile.POINTS_INVARIANT
        or len(FTP75C_PROFILE) != len(FTP75_PROFILE)):
    raise ImportError(
        "tools/ftp75c_profile.py is STALE or HAND-EDITED - it does not match "
        "tools/gen_ftp75_profile.py.\n"
        "  raw sha256 : generated %s\n"
        "               generator %s\n"
        "  mph->m/s   : generated %r\n"
        "               generator %r\n"
        "  points     : generated %d (table %d), invariant %d, ftp75 %d\n"
        "Regenerate with:\n"
        "    .venv_hil/Scripts/python.exe tools/gen_ftp75_profile.py "
        "--time-factor 0.5 --force"
        % (FTP75C_RAW_SHA256, gen_ftp75_profile.RAW_SHA256,
           FTP75C_SCALE_MPH_TO_MPS, gen_ftp75_profile.SCALE_MPH_TO_MPS,
           FTP75C_POINTS, len(FTP75C_PROFILE),
           gen_ftp75_profile.POINTS_INVARIANT, len(FTP75_PROFILE)))

# ── Output artifact convention ──────────────────────────────────────────────
# Every HIL artifact this tool writes lands under "<repo>/HIL Results" unless the
# operator gives an ABSOLUTE path.  run_hil_suite.py already hands its children
# absolute per-run CSV paths (os.path.join(args.out, ...)), so those are honored
# verbatim and the suite keeps full control of its own report directory.
HIL_RESULTS_DIR = os.path.join(REPO_ROOT, "HIL Results")


def resolve_output_path(path):
    """Resolve a user-supplied output path under the HIL Results convention.

    Absolute paths are returned unchanged.  A relative path (bare filename or
    with subdirectories) is resolved under HIL_RESULTS_DIR.  The containing
    directory — including any subdirectories of the resolved path — is created.
    """
    if os.path.isabs(path):
        resolved = path
    else:
        resolved = os.path.join(HIL_RESULTS_DIR, path)
    parent = os.path.dirname(resolved)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return resolved


# ── Self-describing runs: auto-named CSV + .meta.json sidecar ───────────────
# Every run that writes a CSV also writes "<csv>.meta.json" beside it, so a bare
# HIL Results\ directory is readable months later without the shell history that
# produced it.  This mirrors the BLG SD-logging workflow on the board: the log
# carries its own header (fw version, parameters) rather than depending on notes.
#
# The sidecar is written TWICE — once before the loop starts (status "running")
# so a killed run still leaves evidence, once at exit with the results.  NOTHING
# here runs per tick.
META_FORMAT_VERSION = 1
META_TOOL_NAME = "hil_plant_sim"


def sanitize_token(text) -> str:
    """Lowercase, filesystem-safe token for a filename component.

    Anything outside [a-z0-9.-] collapses to '-', runs of '-' collapse to one,
    and leading/trailing '-' are trimmed.  Empty input yields "none"."""
    s = str(text if text is not None else "").strip().lower()
    out = []
    for ch in s:
        out.append(ch if (ch.isalnum() and ch.isascii()) or ch in ".-" else "-")
    token = "".join(out)
    while "--" in token:
        token = token.replace("--", "-")
    token = token.strip("-.")
    return token or "none"


def run_mode_token(replay_path=None, pi_live=False, ems_name=None,
                   has_timeline=False, electrical="simple") -> str:
    """Short deterministic token naming WHAT drove this run.

    Ordered by exclusivity, matching main()'s own argument rules:
      replay-<blg stem>  --replay (no command source exists at all)
      pilive             --pi-live (a real Pi owns the 22-byte command packet)
      ems-<strategy>     an emulated EMS policy drives the command stream
      timeline           the scenario's own scripted pi_timeline drives it
      open               nothing commands the board from here (operator/USB)
    A hi-fi electrical engine appends "-hifi" (the simple droop node is the
    default and is left unmarked)."""
    if replay_path:
        stem = os.path.splitext(os.path.basename(replay_path))[0]
        token = "replay-" + sanitize_token(stem)
    elif pi_live:
        token = "pilive"
    elif ems_name:
        token = "ems-" + sanitize_token(ems_name)
    elif has_timeline:
        token = "timeline"
    else:
        token = "open"
    if electrical == "hifi":
        token += "-hifi"
    return token


def auto_csv_name(scenario, mode_token, stamp=None) -> str:
    """Default CSV filename: hil_<scenario>_<mode>_<YYYYmmdd_HHMMSS>.csv.

    In replay mode there is no scenario (the rails come from the log), so the
    scenario component is dropped and the mode token — which already names the
    log — carries the identity on its own."""
    stamp = stamp or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = ["hil"]
    if scenario:
        parts.append(sanitize_token(scenario))
    parts.append(sanitize_token(mode_token))
    parts.append(stamp)
    return "_".join(parts) + ".csv"


def run_artifact_paths(csv_path: str):
    """Every path a run derives from its CSV path: the CSV, its .meta.json
    sidecar, and the hi-fi electrical events sidecar.

    A CSV path is not free just because the CSV is missing — a previous run's
    sidecars sit alongside it under derived names, and clobbering those loses
    exactly the provenance the sidecar exists to provide."""
    return (csv_path, meta_path_for(csv_path), csv_path + ".events.jsonl")


def output_path_taken(csv_path: str) -> str:
    """The first of a run's artifact paths that already exists, or "".

    TOCTOU: this is a check, not a lock.  Two simulators racing on the same
    second can both see a free name and both proceed — the window is
    microseconds and the loser overwrites.  A file lock is not worth it here:
    the auto-named case is timestamped per second and the explicit case is a
    human typing one command."""
    for p in run_artifact_paths(csv_path):
        if os.path.exists(p):
            return p
    return ""


def unique_output_path(path: str) -> str:
    """Return `path` if free, else the first free '<stem>_N<ext>' (N = 1, 2, ...).

    "Free" means the CSV *and both of its sidecars* are absent
    (output_path_taken).  Only used for AUTO-named paths: two runs started
    inside the same second must not silently overwrite each other.  An
    explicitly-given --csv is refused instead (see main()), because a chosen
    name is a chosen name."""
    if not output_path_taken(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 1
    while output_path_taken("%s_%d%s" % (stem, n, ext)):
        n += 1
    return "%s_%d%s" % (stem, n, ext)


# Constant families that are NOT part of the plant/electrical MODEL and are
# therefore excluded from the fingerprint: wire-protocol sizes and sync bytes,
# the sidecar's own version, the warm-reset tripwire's tuning, socket ports, and
# the switch/aux bitmask definitions.  Without this filter a protocol edit or a
# tripwire retune moved `constants_hash` exactly as loudly as a K_F correction,
# which is precisely the confusion the fingerprint exists to prevent.
# `FW26_` joins them for the same reason (2026-09-02): FW26_CLAMP_CRUISE_LOAD_A
# and the two FW26_CLAMP_SWEEP_* constants are ONE SCENARIO'S STIMULUS SHAPE,
# not plant or electrical model values.  Leaving them in moved the fingerprint
# on a commit that changed no model coefficient, which is exactly the false
# alarm the filter exists to prevent: every pre-round sidecar would have read as
# "the model moved" against a checkout in which it had not.  A scenario's own
# numbers are already recorded per run in its sidecar.
CONSTANTS_EXCLUDE_PREFIXES = (
    "META_", "WARM_RESET_", "HIL_SYNC_", "HIL_INJECT_", "HIL_OUTPUT_",
    "TEENSY_PORT", "SW_", "AUX_", "MDAC_CMD_", "CONSTANTS_EXCLUDE",
    "UDP_", "PI_CMD_", "FB_", "FW26_",
)


def collect_model_constants() -> dict:
    """Module-level UPPERCASE numeric constants of the plant + electrical MODELS.

    Returned as {"<module>.<NAME>": repr(value)} so the dict is both hashable in
    a stable way and readable by a human auditing the sidecar.  This is the
    model-fingerprint record: a K_DROOP_BUS retune or a K_F correction moves
    `constants_hash`, so two runs can be compared without trusting anybody's
    memory of which constants were in the tree.

    Two deliberate narrowings keep that claim honest:
      * CONSTANTS_EXCLUDE_PREFIXES drops the non-model families (protocol sizes,
        ports, bitmasks, this file's own metadata and tripwire tuning).
      * A name re-exported from hil_electrical into this module (they share an
        import) is recorded ONCE, under its canonical `hil_electrical.` prefix,
        so a re-export churn cannot move the hash on its own.

    LIMITATION, stated rather than implied: hash-EQUAL is strong evidence the
    model constants match, but hash-DIFFERENT does not strictly imply the model
    changed — adding an unrelated module-level constant outside the excluded
    prefixes also moves it.  Compare the `constants` dict itself, which is
    included in the sidecar for exactly this reason, before concluding anything
    about a model change."""
    elec = sys.modules.get("hil_electrical")
    if elec is None:                      # only if it was never imported
        try:
            import hil_electrical as elec        # noqa: F811
        except Exception:
            elec = None
    # hil_electrical FIRST so its names are canonical: this module's `from
    # hil_electrical import ...` re-exports (BATT_CAPACITY_AH, C_VESC_DEFAULT,
    # ...) are then skipped as duplicates below rather than recorded twice.
    mods = [("hil_electrical", elec), ("hil_plant_sim", sys.modules.get(__name__))]
    out = {}
    seen = set()
    for mod_name, mod in mods:
        if mod is None:
            continue
        for name, value in vars(mod).items():
            if not name or not name[0].isupper() or name.startswith("_"):
                continue
            if not name.replace("_", "").isalnum() or name.upper() != name:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if name.startswith(CONSTANTS_EXCLUDE_PREFIXES):
                continue
            if name in seen:
                continue                  # re-export: keep the canonical module
            seen.add(name)
            out["%s.%s" % (mod_name, name)] = repr(value)
    return dict(sorted(out.items()))


def constants_hash(constants: dict) -> str:
    """sha256 over the canonical JSON dump of collect_model_constants().

    Equal hash => equal constant set.  Different hash => SOMETHING in the set
    moved, not necessarily a model value; see collect_model_constants()."""
    blob = json.dumps(constants, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def git_provenance() -> dict:
    """{'rev': <sha or None>, 'dirty': <bool or None>, 'error': <str or None>}.

    Provenance must never be able to fail a bench run: git missing, git failing,
    or a non-repo checkout all degrade to nulls plus a note."""
    info = {"rev": None, "dirty": None, "error": None}

    def note(msg):
        # APPEND, never overwrite: `rev-parse` failing and `status` failing are
        # two separate facts, and the old code silently dropped the first.
        info["error"] = msg if not info["error"] else info["error"] + "; " + msg

    # 5 s per call, not 10: this runs BEFORE the loop starts, so the operator is
    # sitting in front of a board waiting for the run to begin.  A hung git (a
    # network filesystem, an index.lock held by another process) must cost the
    # bench seconds, not tens of seconds.
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             timeout=5)
        if rev.returncode == 0:
            info["rev"] = rev.stdout.decode("utf-8", "replace").strip() or None
        else:
            note("rev-parse: "
                 + (rev.stderr.decode("utf-8", "replace").strip()[:200] or "failed"))
    except Exception as exc:              # FileNotFoundError, TimeoutExpired, ...
        note("rev-parse: %s: %s" % (type(exc).__name__, exc))
    try:
        st = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=5)
        if st.returncode == 0:
            info["dirty"] = bool(st.stdout.decode("utf-8", "replace").strip())
        else:
            note("status: "
                 + (st.stderr.decode("utf-8", "replace").strip()[:200] or "failed"))
    except Exception as exc:
        note("status: %s: %s" % (type(exc).__name__, exc))
    return info


def meta_path_for(csv_path: str) -> str:
    return csv_path + ".meta.json"


def write_meta_sidecar(csv_path: str, payload: dict) -> bool:
    """Write payload to '<csv>.meta.json' via temp-file + os.replace.

    Best effort by contract: a provenance file must never abort or crash a bench
    run, so EVERY failure is reported and swallowed (unlike the CSV itself,
    which is the deliverable and aborts the run at open time — see main()).

    The catch is `Exception`, not `OSError`: json.dump raises TypeError (and
    ValueError on a non-finite float) on any value it cannot serialize, and this
    payload contains values sourced from decode_benchlog's BLG header and from
    getattr() on the electrical engine — neither of which this function
    controls.  A TypeError here previously propagated out of an exit path and
    replaced whatever the run was actually doing."""
    path = meta_path_for(csv_path)
    tmp = path + ".tmp"
    ok = False
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=False, default=str)
            fh.write("\n")
        os.replace(tmp, path)
        ok = True
    except Exception as exc:
        print("[hil] could not write %s: %s: %s"
              % (path, type(exc).__name__, exc), file=sys.stderr)
    finally:
        # Clean up on EVERY failure path, including a partially-written temp
        # from a mid-dump TypeError (the old code only unlinked under OSError,
        # so a serialization failure left a stale .tmp behind).
        if not ok:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return ok


# ── `v-bus-sense-offset` stimulus geometry (2026-09-01) ─────────────────────
# Module-level so run_hil_suite.py's expectation windows are DERIVED from the
# same numbers the stimulus is, rather than re-typed. Moving an excursion here
# moves the checks that judge it.
V_BUS_UV_PROBE_DEPTH_V = -5.0
V_BUS_UV_PROBE_1 = (5.0, 5.008)     # 8 ms — under UV_BUS_DWELL_LATCH_MS 20
V_BUS_UV_PROBE_2 = (8.0, 8.060)     # 60 ms — over it, by 3x
#
# ⚠️ PROBE 1 IS 8 ms, NOT 12 (B-M2, 2026-09-01) — HOST-STALL ROBUSTNESS.
# The excursion is delivered by injection frames, and the firmware's stale
# handling HOLDS THE LAST VALUE for HIL_STALE_MS = 50 ms. So a host-side
# scheduling stall INSIDE the excursion does not pause the stimulus: the board
# keeps integrating the sagged rail it was last told about, and the realized
# dwell is the excursion's wall-clock length, stall included.
#   * at 12 ms the margin to the 20 ms latch threshold was 8 ms, and a >= 8 ms
#     stall inside a 12 ms window pushed the dwell over 20 ms and latched —
#     rendering as a FAILED sub-threshold probe, i.e. misread as a FIRMWARE
#     REGRESSION when the actual cause was the host.
#   * at 8 ms the margin is 12 ms, a 1.5x improvement, and the falsifying power
#     is unchanged: the pass bracket becomes (8, 60] ms, which still falsifies a
#     5 ms threshold (a 5 ms filter latches on this probe) and any no-filter
#     implementation.
# The residual is not eliminated, only bounded: a >= 12 ms stall still corrupts
# the probe. The de-vacuation check `uv_probe1_cadence` in run_hil_suite.py
# makes that case render as "stimulus not delivered" rather than as a UV
# verdict — see the FAULT_EXPECTATIONS["v-bus-sense-offset"] entry.


def xor_checksum(payload: bytes) -> int:
    """XOR over the given bytes (callers pass the span between sync and checksum)."""
    c = 0
    for b in payload:
        c ^= b
    return c


def pack_inject(seq, v_fc, v_batt, v_bus, v_chg, v_rgn, i_fc, i_batt, v_actual,
                i_charge=0.0, ag105_status=AG105_ST_DISCONNECT) -> bytes:
    body = struct.pack(
        "<B9fB", seq & 0xFF, v_fc, v_batt, v_bus, v_chg, v_rgn, i_fc, i_batt, v_actual,
        i_charge, ag105_status & 0xFF,
    )
    return bytes([HIL_SYNC_INJECT]) + body + bytes([xor_checksum(body)])


# One-time provenance state for parse_output().  Module-level rather than a
# closure so a test can reset it, and so the 1 kHz drain path pays exactly one
# set-membership test per accepted frame (the dashboard lightness contract: no
# I/O and no allocation on the hot path once the length has been announced).
_OBS_LENGTHS_SEEN = set()


def reset_output_provenance():
    """Forget which frame lengths have been announced (tests; a fresh run)."""
    _OBS_LENGTHS_SEEN.clear()


def _announce_output_length(n: int) -> None:
    """Print the board's observation-frame protocol once per length seen.

    A run that sees BOTH lengths saw the firmware CHANGE UNDER IT — a re-flash
    mid-run, or two boards answering one host.  That is never benign (the two
    layouts disagree about what byte 15 means), so the second announcement is
    explicitly a warning rather than another informational line.
    """
    if n in _OBS_LENGTHS_SEEN:
        return
    first = not _OBS_LENGTHS_SEEN
    _OBS_LENGTHS_SEEN.add(n)
    label = {
        HIL_OUTPUT_SIZE: "fw v25+ (mppt_thresh_count + error_code present)",
        HIL_OUTPUT_SIZE_V24: "fw v24 (mppt_thresh_count, NO error_code)",
        HIL_OUTPUT_SIZE_LEGACY: "fw v21-v23 LEGACY (no mppt_thresh_count, no error_code)",
    }.get(n, "UNRECOGNISED")
    if first:
        print("[hil] observation frame: %d bytes — %s" % (n, label))
    else:
        print("[hil] WARNING: observation frame length CHANGED mid-run to %d "
              "bytes — %s. Both %s have now been seen; the board was re-flashed "
              "under this run, or two boards are answering this host. Every "
              "mppt_thresh_cnt and error_code reading in this CSV is suspect."
              % (n, label, sorted(_OBS_LENGTHS_SEEN)), file=sys.stderr)


def parse_output(data: bytes):
    """Validate and decode a 16-, 17- or 18-byte observation frame; dict or None.

    18 bytes is the fw v25 layout (checksum over 1..16 at byte 17; byte 15 the
    Ag105 reg-0x02 count the firmware believes is in force, byte 16 the LATCHED
    first-cause error_code).  17 bytes is fw v24 (checksum over 1..15) and yields
    `error_code` None.  16 bytes is fw v21-v23 (checksum over 1..14) and yields
    both `mppt_cnt` and `error_code` None — the honest value for "this firmware
    cannot tell us".  Every other field sits at the same offset in all three.
    """
    n = len(data)
    if n not in HIL_OUTPUT_SIZES or data[0] != HIL_SYNC_OUTPUT:
        return None
    if xor_checksum(data[1:n - 1]) != data[n - 1]:
        return None
    seq, state, sw, aux = data[1], data[2], data[3], data[4]
    (current,) = struct.unpack_from("<f", data, 5)
    mdac_fc, mdac_bt, faults = struct.unpack_from("<HHH", data, 9)
    # Provenance costs ONE set-membership test per accepted frame once the
    # length has been announced -- the call is inside the branch, not before
    # it, so the steady-state 1 kHz path never enters a function for it
    # (the dashboard lightness contract).
    if n not in _OBS_LENGTHS_SEEN:
        _announce_output_length(n)
    return {
        "seq": seq,
        "state": state,
        "switch": sw,
        "aux": aux,
        "current": current,
        "mdac_fc": mdac_fc,
        "mdac_bt": mdac_bt,
        "fault_flags": faults,
        # int on a 17-byte frame, None on a legacy one.  Consumers MUST treat
        # None as "unknown", never as a count: 0 is a valid count (11.0 V).
        "mppt_cnt": data[15] if n >= HIL_OUTPUT_SIZE_V24 else None,
        # Same discipline: None is "this firmware cannot tell us", NOT ERR_NONE.
        # 0 is a legal value (no fault latched), so a 0-fill would read as
        # "the board is clean" on a board that never said so.
        "error_code": data[16] if n >= HIL_OUTPUT_SIZE else None,
    }


def pack_output(seq, state, sw, aux, current, mdac_fc, mdac_bt, faults,
                mppt_cnt=None, error_code=None) -> bytes:
    """Build an observation frame, mirroring hilPackOutputFrame().

    Length is chosen by which optional tail fields are supplied, longest-first:
      mppt_cnt None                     -> 16 bytes (fw v21-v23)
      mppt_cnt int, error_code None     -> 17 bytes (fw v24)
      mppt_cnt int, error_code int      -> 18 bytes (fw v25+)
    `error_code` without `mppt_cnt` is not a frame any firmware emits (the two
    bytes are adjacent and append-only), so it raises rather than fabricating a
    layout the board cannot produce.  Test/diagnostic helper — the simulator
    never sends observation frames, it only receives them.
    """
    if mppt_cnt is None and error_code is not None:
        raise ValueError("error_code requires mppt_cnt: no firmware emits a "
                         "frame with byte 16 present and byte 15 absent")
    body = struct.pack("<BBBBfHHH", seq & 0xFF, state & 0xFF, sw & 0xFF,
                       aux & 0xFF, current, mdac_fc & 0xFFFF,
                       mdac_bt & 0xFFFF, faults & 0xFFFF)
    if mppt_cnt is not None:
        body += bytes([int(mppt_cnt) & 0xFF])
    if error_code is not None:
        body += bytes([int(error_code) & 0xFF])
    return bytes([HIL_SYNC_OUTPUT]) + body + bytes([xor_checksum(body)])


def ag105_mppt_volts(count) -> float:
    """Ag105 reg-0x02 count -> threshold volts.  AG105_MPPT_VOLTS, .ino:1671-1677.

    11.0 V at count 0, 0.088 V/count, up to 33.0 V at the AG105_MPPT_N_MAX 250
    that still means "I2C threshold".  Counts >= 251 (AG105_MPPT_N_RESISTOR
    0xFF is the factory default) mean EXTERNAL-RESISTOR MODE and have no volts
    of their own — the caller must branch on that BEFORE calling here, which is
    why this raises rather than extrapolating a fictional threshold.
    """
    n = int(count)
    if not (0 <= n <= AG105_MPPT_N_MAX):
        raise ValueError(
            "reg-0x02 count %d is not an I2C threshold (0..%d); >=251 is "
            "external-resistor mode and has no volts value"
            % (n, AG105_MPPT_N_MAX))
    return AG105_MPPT_V_BASE + AG105_MPPT_V_PER_CNT * n


def mdac_fraction(word: int) -> float:
    """Recover the 0..1 droop-gain fraction from a raw AD5443 command word."""
    if (word & 0xF000) != MDAC_CMD_LOAD_UPDATE:
        return 0.0
    return (word & 0x0FFF) / float(MDAC_RES)


# ═════════════════════════════════════════════════════════════════════════════
# HYDROGEN-CONSUMPTION METRIC — the Gfc transfer function, discretized
#
# ⚠️ MANDATORY BANNER — READ BEFORE QUOTING ANY NUMBER THIS PRODUCES ⚠️
#
#   Gfc is a FULL-SCALE (106 kW) fuel-cell hydrogen-consumption model taken
#   VERBATIM from the PhD student's FCHEV dynamic-programming study.  It is the
#   commented-out `H2_tf` at references/EMS/DPtrial.m:51-52, with its two scalar
#   prefactors folded into the coefficients:
#       num = 2.016 * [2.733, 1.115e6, 1.234e9, 3.211e11]
#           =         [5.51,  2.248e6, 2.488e9, 6.473e11]
#       den = 720*1.45 * [1, 1.187e7, 1.948e10, 7.864e12, 3.515e13]
#           =        [1044, 1.239e10, 2.034e13, 8.21e15,  3.67e16]
#   Input  u = P_fc in WATTS.  Output y = hydrogen mass rate in g/s.
#
#   SCALE PORTABILITY — RESOLVED (operator ruling, 2026-08-31): the 720 in
#   den[0] = 1044 = 720 * 1.45 is the FULL-SIZE FUEL CELL's OCV (the earlier
#   reading of it as the battery pack's Em was wrong — both happen to be 720 V
#   in that model).  The transfer function needs NO adjustment for this rig:
#   its input (P_fc, W) and output (H2 mass rate, g/s) both ride the system's
#   energy scaling factor, so the g/s-per-W map is scale-invariant under the
#   systemic scaling methodology — see
#   references/Systemic_Scaling_of_Powertrain_Models_with_Youla_Driver_Control.pdf
#   (Tan, Yadav & Assadian).  H2 numbers from this path are therefore the
#   model's estimate proper, not merely relative figures.  Remaining caveats,
#   which are about the MODEL, not the scaling:
#
#     1. STACK IDENTIFICATION.  The coefficients were fit for the full-size
#        stack's consumption behaviour; they have NOT been identified against
#        THIS stack.  TODO(calibrate) — that is the surviving obligation.
#     2. EFFICIENCY DISAGREEMENT.  Its DC gain 1.7637602179836514e-05 g/s/W is
#        1.164x the DP's OWN static proxy `W_H2 = P_fc/(0.55*120000)`
#        (DPtrial.m:43), i.e. it implies eta = 47.25 % where the same script
#        assumes 55 % — a +16.4 % disagreement INSIDE one study.  A model
#        choice to be aware of when comparing against proxy-based numbers.
#     3. DYNAMICS.  Its dominant time constant is 0.2212 s.  That is a
#        CONSUMPTION-dynamics claim (fuel delivery / stack thermodynamics) and
#        is a DIFFERENT quantity from the ELECTRICAL FC_TAU_S = 0.020 s
#        double-layer lag modelled in hil_electrical.py (`FC_TAU_S`).  The two are not
#        alternatives and must not be reconciled with each other.  Whether the
#        full-size consumption lag transfers unchanged to a small stack is
#        part of caveat 1.
#
# ── Discretization: MEASURED, do not revisit ─────────────────────────────────
# A characterization round (scipy, 2026-08-31) established the CT system is
# stable and minimum-phase, then compared three discretizations at 1 kHz:
#   * ZOH modal / parallel-first-order  — max rel err 2.5e-9   ** CHOSEN **
#   * Tustin                            — REJECTED: maps the 1.887e6 rad/s pole
#                                         to z = -0.9997, i.e. a permanent
#                                         ringing mode at Nyquist
#   * tf2sos cascaded biquads           — REJECTED: 8.2e-3 err, WORSE than
#                                         Tustin
# The chosen form is four INDEPENDENT scalar first-order recursions summed.
# The fourth mode has lambda = 0: it is the ZOH image of the fastest CT pole,
# not a direct feedthrough (the CT system is strictly proper).
#
# DC check: sum(g_i / (1 - lam_i)) = 1.7637602179836473e-05, 4 ulp from the
# target DC gain above.
#
# ── Sample alignment (deviation from the round spec, stated) ─────────────────
# The spec sketched the tick body as "y = sum(x); then x_i = lam_i*x_i + g_i*u",
# which reports the state BEFORE this tick's input acts.  The validation vectors
# it also supplied are the other alignment — y[1] for a 10 W step at n = 0 is
# 1.4516e-06, not 0 — so step() UPDATES FIRST and then reads out, which
# reproduces the vectors EXACTLY (worst relative error 3.1e-16 over all ten
# pinned values).  The two orderings emit the SAME sequence shifted by one
# sample; this one has no dead tick, which is also the physically sensible
# reading of "the H2 rate during tick n".
#
# VALIDATION VECTORS — 10.0 W step applied from the first tick, zero initial
# state, Ts = 1e-3, h2_cum = rectangular sum of y*Ts (rtol 1e-9):
#     n=1     y=1.451648924521401e-06   cum=1.451648924521401e-09
#     n=10    y=8.825724871566303e-06   cum=5.300056759372415e-08
#     n=100   y=6.483139460046860e-05   cum=3.565983712066193e-06
#     n=1000  y=1.744684319758860e-04   cum=1.381066815913307e-04
#     n=2000  y=1.763552634860608e-04   cum=3.140662654327328e-04
# ═════════════════════════════════════════════════════════════════════════════
H2_GFC_TS_S = 1.0e-3              # s      discretization sample period (1 kHz)
H2_GFC_DC_GAIN_GPS_PER_W = 1.7637602179836514e-05   # g/s per W (CT DC gain)
H2_GFC_TAU_DOMINANT_S = 0.2212    # s      dominant CT time constant
# The DP's own static proxy, kept for the comparison in banner point 2 only —
# nothing computes with it (DPtrial.m:43, `W_H2 = P_fc/(0.55*120000)`).
H2_STATIC_PROXY_GPS_PER_W = 1.0 / (0.55 * 120000.0)
# Modal poles (z-plane) and input gains of the ZOH discretization.  TUPLES, so
# collect_model_constants() does not fingerprint them; the three scalars above
# do move the fingerprint, which is the intended signal for "the H2 model
# changed".  Never edit one list without the other — they are one artifact.
H2_GFC_LAMBDA = (0.9954895536622109, 0.4982126039712872,
                 0.390405727787838, 0.0)
H2_GFC_GAIN = (7.90674025708048e-08, -1.110462133471187e-09,
               6.677840850342943e-08, 4.2954351137707583e-10)

# M4 (review, 2026-08-31): the DC-gain identity that ties the two artifacts
# together, asserted AT IMPORT.  H2_GFC_DC_GAIN_GPS_PER_W is the number the DP
# generator imports for its stage cost (gen_dp_ems_table.py D4) while
# H2_GFC_LAMBDA/H2_GFC_GAIN are what the 1 kHz recursion actually integrates —
# so a hand-edit of either list that left the scalar alone would silently make
# the DP objective and the simulator's logged h2_cum_g DIFFERENT MODELS, and
# every "DP vs soc-band" percentage a comparison of unlike things.  Measured
# residual today is 4 ulp (2.3e-15 relative), so 1e-13 is a ~40x margin that
# still catches any real coefficient change.  Cheap: four divides, once.
_H2_DC_CHECK = sum(g / (1.0 - lam)
                   for g, lam in zip(H2_GFC_GAIN, H2_GFC_LAMBDA))
assert abs(_H2_DC_CHECK - H2_GFC_DC_GAIN_GPS_PER_W) \
       / H2_GFC_DC_GAIN_GPS_PER_W < 1e-13, (
    "H2 model inconsistency: sum(g/(1-lambda)) = %.17g disagrees with "
    "H2_GFC_DC_GAIN_GPS_PER_W = %.17g. The modal coefficients and the DC gain "
    "are ONE artifact (the DP generator imports the scalar, the 1 kHz tick "
    "runs the recursion); regenerate both together, never edit one."
    % (_H2_DC_CHECK, H2_GFC_DC_GAIN_GPS_PER_W))
del _H2_DC_CHECK

# ── The STUDENT'S STATIC PROXY (the SDP/DP stage cost), 2026-08-31 ───────────
#
# WHAT IT IS.  `W_H2 = P_fc / (eta_fc * Q_LHV_H2)` — the algebraic hydrogen
# model the PhD student's dynamic programs minimise
# (references/EMS/SDP_EnergyManagement2.m:12-13 and its `W_H2` stage cost;
# DPtrial.m:43 uses the same form at eta_fc = 0.55).  It is a CONSTANT-
# EFFICIENCY map: no dynamics, no memory, one multiply.
#
# WHY IT IS LOGGED ALONGSIDE Gfc RATHER THAN INSTEAD OF IT.  The two answer
# different questions and neither supersedes the other:
#   * `h2_cum_g` (Gfc) is the DYNAMIC map this simulator integrates and the one
#     `tools/gen_dp_ems_table.py` solves its stage cost against, so it is the
#     axis on which THIS repository's strategies are ranked.
#   * `h2_sdp_cum_g` (this proxy) is the axis the STUDENT's SDP/DP work is
#     stated on, so a number from a run here can be read next to a number from
#     that work without either side re-deriving the other's model.
# ⚠️ THEY ARE NOT INTERCHANGEABLE, and the offset is systematic rather than
# noise: Gfc's DC gain 1.7638e-5 g/s/W implies an efficiency of 47.25 %, while
# this proxy assumes 50 %, so the PROXY UNDER-READS by ~5.5 % relative to Gfc at
# steady state (1/(0.5*120000) = 1.6667e-5 g/s/W, i.e. 0.945x).  Both are model
# ESTIMATES against an UNIDENTIFIED stack (TODO(calibrate) — the H2Consumption
# banner applies verbatim to this column too).  Compare runs on ONE axis; never
# quote a difference between the two columns as a physical result.
#
# ⚠️ eta_fc = 0.5, NOT the 0.55 of H2_STATIC_PROXY_GPS_PER_W above.  The two
# constants are different studies' numbers (SDP vs DPtrial) and are deliberately
# kept apart rather than reconciled by this file — reconciling them would be a
# modelling decision neither study made.
H2_SDP_PROXY_ETA_FC = 0.5             # SDP_EnergyManagement2.m:12
H2_SDP_PROXY_Q_LHV_J_PER_G = 120000.0  # SDP_EnergyManagement2.m:13 (J/g)
H2_SDP_PROXY_GPS_PER_W = 1.0 / (H2_SDP_PROXY_ETA_FC * H2_SDP_PROXY_Q_LHV_J_PER_G)


class H2Consumption:
    """Discretized Gfc: P_fc [W] in, hydrogen rate [g/s] and cumulative [g] out.

    ⚠️ Read the BANNER above this class before using any value it returns.  The
    map is SCALE-PORTABLE (operator ruling 2026-08-31: input P_fc in W and
    output in g/s both ride the system's energy scaling factor), so what it
    returns is THE MODEL'S ESTIMATE of hydrogen mass — not merely a relative
    figure.  What it is NOT is identified against THIS stack: quote it with
    that TODO(calibrate) caveat.  Strategy RANKINGS on the same rig are robust
    regardless.

    Four independent scalar recursions, summed.  No numpy: this runs inside the
    1 kHz tick and must stay stdlib and allocation-free.
    """

    def __init__(self):
        self.x = [0.0, 0.0, 0.0, 0.0]
        self.rate_gps = 0.0       # g/s   this tick's output
        self.cum_g = 0.0          # g     rectangular integral of rate_gps
        # The student's static proxy, carried HERE rather than in a second
        # object so it is structurally impossible for the two models to be fed
        # different inputs: one step(), one clamped `u`, two accumulators.  See
        # the H2_SDP_PROXY_* banner above.
        self.proxy_rate_gps = 0.0   # g/s
        self.proxy_cum_g = 0.0      # g

    def reset(self):
        self.x = [0.0, 0.0, 0.0, 0.0]
        self.rate_gps = 0.0
        self.cum_g = 0.0
        self.proxy_rate_gps = 0.0
        self.proxy_cum_g = 0.0

    def step(self, p_fc_w, dt=H2_GFC_TS_S):
        """Advance one tick on P_fc [W]; return this tick's rate in g/s.

        `p_fc_w` is CLAMPED AT ZERO.  Reverse power into the fuel cell is not a
        physical operating point for this rig (the FC feeds the bus through an
        ideal-diode switch), and a negative input would produce a negative
        hydrogen rate — an unphysical CREDIT that would silently flatter any
        strategy that provoked it.  The clamp is a deliberate nonlinearity on
        an otherwise linear model, and it is the conservative direction.

        L4 (review, 2026-08-31): on the SHIPPED call path the clamp is
        BELT-AND-BRACES, not a live guard.  Plant.step() feeds it
        `FuelCellSource.v_terminal * FuelCellSource.i`, and that source already
        clamps BOTH factors non-negative, so the product cannot be negative
        today.  The clamp exists so a future caller — a different source model,
        a directly-injected P_fc, a test — cannot introduce the credit by
        accident.  Do not remove it on the strength of the current caller.

        `dt` scales the CUMULATIVE integral only.  The recursion coefficients
        are pinned to H2_GFC_TS_S = 1 ms; running the sim at another --rate
        does not re-discretize them, so the rate output would be wrong in the
        transient (the DC gain is unaffected).  1 kHz is the sim's tick.
        """
        u = p_fc_w if p_fc_w > 0.0 else 0.0
        x = self.x
        x[0] = H2_GFC_LAMBDA[0] * x[0] + H2_GFC_GAIN[0] * u
        x[1] = H2_GFC_LAMBDA[1] * x[1] + H2_GFC_GAIN[1] * u
        x[2] = H2_GFC_LAMBDA[2] * x[2] + H2_GFC_GAIN[2] * u
        # lam[3] == 0: this mode carries no memory, it is one tick of the
        # fastest ZOH pole.  Written out rather than folded into a feedthrough
        # so the four-mode structure stays visible against the coefficients.
        x[3] = H2_GFC_LAMBDA[3] * x[3] + H2_GFC_GAIN[3] * u
        self.rate_gps = x[0] + x[1] + x[2] + x[3]
        self.cum_g += self.rate_gps * dt
        # The student's static proxy on the SAME clamped `u` (two multiplies).
        # Deliberately fed from `u`, not from p_fc_w: the zero-clamp is part of
        # the input definition, and letting the two models see different inputs
        # is exactly the confound this shared step() exists to prevent.
        self.proxy_rate_gps = u * H2_SDP_PROXY_GPS_PER_W
        self.proxy_cum_g += self.proxy_rate_gps * dt
        return self.rate_gps


class Plant:
    """
    First-order plant model.

    Mechanical:
        m_eff * dv/dt = K_F*I_cmd - sign(v)*F_c - b_eff*v
      with a static-friction deadband around v = 0: below V_STICTION the Coulomb
      term opposes the applied force and cannot reverse the velocity within a tick,
      so the body simply stays put until |K_F*I| exceeds F_c.
      Motor force is developed only when MOT_PWR_ENABLE is closed AND the bus is up
      — a VESC with no bus makes no torque.

    Electrical (deliberately simple, and simplified in two places worth naming):
      * The bus is a single droop node: V_bus = V_BUS_NOMINAL - K_DROOP_BUS*I_total
        whenever at least one source is "live" (its ideal-diode bus switch closed AND
        its boost regulator enabled).  With no live source the node decays as an
        RC through R_BUS_BLEED*C_BUS_F.  This models neither the boost dynamics nor
        the RT1987 turn-on transient — HIL here is a controller/sequencing rig, not
        a converter simulator.
      * The FC/BT current split follows the ratio of the two droop MDAC codes.  The
        real split is set by the analog droop network's equivalent resistances, which
        the codes only parametrize; proportional-to-RECIPROCAL-code is a
        SIMPLIFICATION that preserves the sign and monotonicity of the share loop's
        authority without claiming the true gain.  SIGN, stated correctly (the
        C1 round, 2026-09-01, corrected the opposite claim here and the code
        under it): each channel's droop gain command is g = k_d/(RE_MAX * share),
        so RAISING THE FC CODE RAISES ITS DROOP RESISTANCE AND LOWERS ITS
        CURRENT.  On top of that ratio sits the static converter-asymmetry law
        of docs/modeling/converter_asymmetry_20260901.md §2 (voltage mismatch
        only, rho = 1), disabled by `--asymmetry off`.
      * The Ag105 charger is modelled at the STATUS level only: input power in ->
        settle delay -> "Charging" with a first-order current ramp toward the 2.5 A
        configured ceiling.  CV taper exists only as the SoC-triggered Fully-Charged
        branch.  The I2C transport and the config handshake are not modelled at all
        (the firmware skips them entirely under HIL).
      * MPPT: by DEFAULT (`mppt_emulation=False`) MPPT_DISABLE only clears the two
        tracking FLAGS in the status byte and has no effect on charging, which is
        why the pin has never been causally load-bearing in this rig.  With
        `mppt_emulation=True` the part's actual mechanism is modelled at LAYER 1:
        an INPUT-VOLTAGE THRESHOLD (datasheet p.10), NOT a perturb-and-observe
        tracker.  From fw v24 the threshold VALUE is the board's own: it is read
        off the observation frame's reg-0x02 count (`obs["mppt_cnt"]`) through
        ag105_mppt_volts(), and AG105_MPPT_V_THRESH is only the fallback for a
        frame that carries no count.  The tracking DYNAMICS (how the module walks
        its operating point once above the threshold) are still not modelled at
        all, and neither are the I2C WRITES that set the count — the firmware's
        own HIL mirror short-circuits those too (.ino:11185-11201).
    """

    def __init__(self, electrical=None, soc0=0.7, capacity_ah=BATT_CAPACITY_AH,
                 ag105_i_max=AG105_I_MAX, mppt_emulation=False,
                 asymmetry_mode=ASYMMETRY_MODE_DEFAULT,
                 ina_offset_fc=0.0, ina_offset_bt=0.0, noise_active=None,
                 drag_mode=DRAG_MODE_DEFAULT):
        # ── PART A (C1, 2026-09-01): converter asymmetry, SIMPLE MODE ────────
        # In hi-fi mode the asymmetry lives in the two Boost objects and this
        # plant never applies it.  Simple mode has no converter models at all,
        # so the same physics enters as the STATIC share law of
        # docs/modeling/converter_asymmetry_20260901.md §2 with rho = 1
        # (per-channel droop scales are a hi-fi concept: simple mode realizes no
        # per-channel droop resistance to scale).  Mode "off" is inert.
        if asymmetry_mode not in ASYMMETRY_MODES:
            raise ValueError("asymmetry_mode must be one of %s"
                             % (ASYMMETRY_MODES,))
        # ── THE ROAD-LOAD PROFILE (2026-09-02) ───────────────────────────────
        # `rig` is the DEFAULT and reproduces every recorded campaign byte for
        # byte: the force branch of step() below takes an explicit `rig` arm
        # that is the pre-2026-09-02 code verbatim.  The two compensated modes
        # replace the Coulomb-plus-viscous road load with a single quadratic
        # term and set F_c to zero, which is what makes braking regenerative on
        # this rig at all.  `k_air` is resolved ONCE here so the tick loop
        # neither re-dispatches on the mode string nor can read a mode the
        # constructor did not validate.
        self.drag_mode = drag_mode
        self.k_air = drag_k_air(drag_mode)      # raises on an unknown mode
        # F3 (fix round, 2026-09-01): discriminated on the INA offsets this run
        # actually injects, not on whether a NoiseConfig object exists.  Simple
        # mode NEVER constructs one (hil_plant_sim.py:8087-8094 vs :8163), so
        # these default to zero and a simple-mode run keeps the full voltage
        # term -- which is correct, because it injects no sense-arm offset to
        # double-count against.
        # NOT SCALED BY A DROOP MODE (unlike the hi-fi engine's, F2): `--droop`
        # has no effect under `--electrical simple`, which already uses the
        # bench-measured K_DROOP_BUS_* constants, and the static law below is
        # written in the COMMANDED k_d the fit itself uses.
        # `noise_active` is a CONVENIENCE ALIAS retained from the first cut of
        # this constructor, not a second mechanism: True resolves to the INA
        # offsets a default NoiseConfig would inject and False to zeros, which
        # is exactly what a caller meant by it.  The OFFSETS ARE AUTHORITATIVE
        # (F3) -- pass them directly whenever they are not the defaults, e.g.
        # NoiseConfig(ina_zero_offset=0.0), which `noise_active=True` cannot
        # express.  Explicit offsets win if both are given.
        if noise_active is not None and not (ina_offset_fc or ina_offset_bt):
            ina_offset_fc = INA_ZERO_OFFSET_A if noise_active else 0.0
            ina_offset_bt = 0.0
        self.asymmetry_mode = asymmetry_mode
        self.asym_ina_offset_fc = float(ina_offset_fc)
        self.asym_ina_offset_bt = float(ina_offset_bt)
        self.asym_dv0_v = (0.0 if asymmetry_mode == "off"
                           else asymmetry_dv0_v(ina_offset_fc, ina_offset_bt))
        # `ag105_i_max` is a SCENARIO PARAMETER (SCENARIOS[...]["chg_i_ceiling_a"]),
        # in the same class as `vesc_cap_f`: it does not model the firmware, it
        # sizes the stimulus.  The firmware always configures the 2.5 A profile
        # (reg 0x00 = 0x01), so AG105_I_MAX stays the default and any override is
        # a deliberate, documented de-rating for a scenario whose objective is
        # PATH coverage rather than ceiling validation.  See the charge-fault /
        # charge-regen entries for the per-scenario current budgets.
        self.ag105_i_max = float(ag105_i_max)
        # `mppt_emulation` is a SCENARIO PARAMETER in the same class as
        # `ag105_i_max` (SCENARIOS[...]["mppt_emulation"]).  DEFAULT FALSE, so
        # every scenario that predates it produces a byte-identical trace: the
        # threshold gate below is the only code it reaches, and it is skipped
        # entirely when the flag is clear.
        self.mppt_emulation = bool(mppt_emulation)
        # Latched inhibit state for the threshold comparison's hysteresis.  Only
        # meaningful when `mppt_emulation` is set; see the charger branch.
        self.mppt_inhibited = False
        self.v = 0.0          # m/s
        self.v_bus = 0.0      # V
        self.i_fc = 0.0
        self.i_batt = 0.0
        self.v_chg = 0.0
        self.v_rgn = 0.0
        self.i_aux = I_AUX_A
        self.v_bus_offset = 0.0   # scenario-injected bus disturbance [V]
        # ── Source models (shared by both electrical modes) ──────────────────
        # Plant OWNS the two source objects and hands them to the hi-fi engine, so
        # SOC and the fuel-cell double-layer state are integrated exactly once per
        # tick whichever mode is selected.
        self.battery = BatterySource(soc0=soc0, capacity_ah=capacity_ah)
        self.fuel_cell = FuelCellSource()
        # ── Hydrogen-consumption metric (2026-08-31) ─────────────────────────
        # SIMULATED MODE ONLY, by construction: it is stepped from Plant.step(),
        # and replay bypasses the plant integrator entirely.  It is a pure
        # OBSERVER — nothing in the plant, the electrical engine, the injected
        # frame or any policy reads it back, so it cannot change a trace.
        # Read the H2Consumption banner before quoting any value.
        self.h2 = H2Consumption()
        # ── Optional high-fidelity electrical engine ────────────────────────
        self.electrical = electrical
        if electrical is not None:
            electrical.fuel_cell = self.fuel_cell
            electrical.battery = self.battery
        # ── Ag105 charger model state ───────────────────────────────────────
        # ── WP-C regen accounting (both electrical modes) ───────────────────
        # p_regen_w is this tick's mechanical->electrical braking power at V-MOT;
        # the rest are cumulative energies, kept so a run can be audited against the
        # balance written out in Plant.step().  Nothing in the model READS them
        # back — they are observers, like h2.
        self.p_regen_w = 0.0              # W
        self.regen_energy_j = 0.0         # J  handed to the electrical side
        self.e_brake_mech_j = 0.0         # J  taken off the flywheel by the VESC
        self.regen_chopper_w = 0.0        # W  simple mode only (hi-fi: engine)
        self.regen_chopper_energy_j = 0.0 # J  simple mode only (hi-fi: engine)
        # ── Per-tick power balance (2026-09-01f) ────────────────────────────
        # Observers only; see the block at the end of step() for the identity
        # they express and the named residual terms.  Seeded to 0.0 so a Plant
        # that has never stepped reads as "no power anywhere", which is true.
        self.p_mot_w = 0.0
        self.p_fc_w = 0.0
        self.p_batt_w = 0.0
        self.p_chop_w = 0.0
        self.p_aux_w = 0.0
        self.p_bal_w = 0.0
        self.p_chg_loss_w = 0.0
        self.i_charge = 0.0           # A   measured charge current (reg 0x06 equivalent)
        self.chg_powered_s = 0.0      # s   time the charger input has been continuously live
        self.chg_fault = False        # scenario-driven charger-input collapse
        # Scenario-driven extra draw on the V-MOT node, i.e. BEHIND MOT_PWR.  This is
        # NOT i_aux (which sits on VBUS): only a load behind the switch loads the
        # switch, which is the whole point of the `scp-inrush` margin case.
        self.i_mot_extra = 0.0
        # `scp-inrush` scenario bookkeeping (2026-08-31 deterministic redesign).
        # SCENARIO STATE ONLY — no physics reads these; apply_scenario() owns them
        # end to end and Plant.step() never looks at them.  They live on the plant
        # because apply_scenario() is stateless apart from `t` and the plant object,
        # and the three-phase load needs to remember that the fold pulse already
        # fired (it must be a ONE-SHOT: the RT1987 retry has to come up clean).
        # Lifecycle (review M1, 2026-08-31): all three LATCH for the life of the
        # run and are cleared in exactly one place — the observed mainState
        # 99 -> non-99 edge in main() (the warm-reset tripwire site) — so a
        # forged-boundary warm reset that re-runs the bring-up gets a clean
        # phase-1 ramp instead of ramming the fresh ramp into a standing 5.0 A
        # run load (the pre-redesign configuration this stimulus exists to
        # eliminate). The `count == 1` scp_cut pin is per-bring-up; a legitimate
        # second bring-up produces its own single cut.
        self.scp_armed = False     # fold pulse applied (latches until reset)
        self.scp_fired = False     # ...and has since been withdrawn (latched)
        self.scp_fired_t = None    # sim time at which the pulse was withdrawn
        self.ag105_status = AG105_ST_DISCONNECT

    def _apply_simple_asymmetry(self, frac_fc, i_total):
        """Static converter-asymmetry law on the simple-mode FC share.

        alpha = r + DeltaV0 * r(1-r) / (k_d * I_tot), with r the commanded share
        recovered from the MDAC codes and k_d = K_DROOP_FW_OHM.  This is the M1
        model of the fit document (§2 with rho = 1), i.e. voltage mismatch only.
        The correction diverges as I_tot -> 0, so it is skipped below
        ASYM_SIMPLE_I_MIN_A, where no meaningful share exists anyway, and the
        result is clipped to [0, 1].
        """
        if self.asym_dv0_v == 0.0 or i_total < ASYM_SIMPLE_I_MIN_A:
            return frac_fc
        alpha = frac_fc + (self.asym_dv0_v * frac_fc * (1.0 - frac_fc)
                           / (K_DROOP_FW_OHM * i_total))
        return min(1.0, max(0.0, alpha))

    def step(self, dt, obs):
        """Advance one tick against the last observation frame (None = actuators unknown)."""
        sw = obs["switch"] if obs else 0
        aux = obs["aux"] if obs else 0
        i_cmd = obs["current"] if obs else 0.0
        code_fc = mdac_fraction(obs["mdac_fc"]) if obs else 0.5
        code_bt = mdac_fraction(obs["mdac_bt"]) if obs else 0.5

        fc_live = bool(sw & SW_FC_BUS) and bool(aux & AUX_FC_REG)
        bt_live = bool(sw & SW_BT_BUS) and bool(aux & AUX_BT_REG)
        mot_live = bool(sw & SW_MOT_PWR)

        # ── Mechanical ───────────────────────────────────────────────────────
        bus_up = self.v_bus > 5.0
        # WP-C: the REGEN side of the command is clipped by the VESC's Battery
        # Regen Max before it becomes force, so the braking force and the
        # electrical return are derived from ONE number.  The drive side is
        # untouched (`i_cmd >= 0` takes the identity branch), which is what keeps
        # every pre-WP-C drive trace bit-identical.
        i_cmd_eff = i_cmd if i_cmd >= 0.0 else max(i_cmd, -VESC_REGEN_I_MAX_A)
        f_drive = K_F * i_cmd_eff if (mot_live and bus_up) else 0.0
        if self.k_air == 0.0:
            # ── THE MEASURED RIG PROFILE (`--drag rig`, the default) ─────────
            # VERBATIM pre-2026-09-02 code.  Kept as its own arm rather than
            # generalized with a per-mode F_c, because the Coulomb SIGN LOGIC
            # DOES NOT DEGRADE at F_c = 0: the deadband test `abs(f_drive) <=
            # F_COULOMB` becomes `abs(f_drive) <= 0`, which is TRUE for a
            # coasting body under zero drive inside the stiction band, and the
            # branch would then set `self.v = 0.0` and delete its momentum.
            # One shared expression would have been a silent physics defect on
            # exactly the profile this round adds.
            if abs(self.v) < V_STICTION:
                # Static-friction deadband: no breakaway until the drive force exceeds F_c.
                if abs(f_drive) <= F_COULOMB:
                    f_net = 0.0
                    self.v = 0.0
                else:
                    f_net = f_drive - (F_COULOMB if f_drive > 0 else -F_COULOMB) - B_EFF * self.v
            else:
                f_sign = 1.0 if self.v > 0 else -1.0
                f_net = f_drive - f_sign * F_COULOMB - B_EFF * self.v
                # Do not let friction alone push the body through zero within one tick.
                v_try = self.v + (f_net / M_EFF) * dt
                if f_drive == 0.0 and (v_try * self.v) < 0.0:
                    self.v = 0.0
                    f_net = 0.0
        else:
            # ── ROAD-LOAD COMPENSATED (`scaled-air` / `scaled-air-matched`) ──
            # ONE quadratic term and NO Coulomb term (the compensation replaces
            # the rig's friction rather than adding to it), so there is no
            # breakaway to test and no stiction deadband: a body inside
            # V_STICTION is free to creep, which is the physically correct
            # behaviour for a road load that vanishes with speed.
            #
            # THE SIGNED FORM `v*|v|` IS LOAD-BEARING.  The rig profile's drag
            # always opposes motion through `f_sign`; a bare `v**2` term would
            # ACCELERATE the body in reverse.
            f_net = f_drive - self.k_air * self.v * abs(self.v)
            # The zero-crossing guard is KEPT.  Quadratic drag alone cannot push
            # the body through zero, so this arm is unreachable in exact
            # arithmetic; it is retained because its ABSENCE would be a silent
            # behavioural difference between the two profiles, and it costs one
            # comparison per tick.
            v_try = self.v + (f_net / M_EFF) * dt
            if f_drive == 0.0 and (v_try * self.v) < 0.0:
                self.v = 0.0
                f_net = 0.0
        self.v += (f_net / M_EFF) * dt

        # ── Electrical ───────────────────────────────────────────────────────
        # Motor bus draw from mechanical power, through the boost efficiency.
        #
        # ── WP-C ENERGY BALANCE (2026-09-01) ────────────────────────────────
        # Shaft power p_shaft = f_drive * v splits by SIGN, and the two halves are
        # different physics, not two cases of one formula:
        #   p_shaft >= 0  MOTORING.  Power is drawn from the bus through the boost
        #                 stage: i_motor = p_shaft / (ETA_BOOST * V_bus).  Verbatim
        #                 pre-WP-C behaviour, byte for byte.
        #   p_shaft <  0  BRAKING.  The flywheel gives up |p_shaft| of kinetic power,
        #                 of which ETA_REGEN reaches V-MOT electrically and the rest
        #                 is motor/inverter loss.  The mechanical half is ALREADY
        #                 accounted: f_drive carries the clipped braking force and the
        #                 velocity integration above has already applied it.
        # The balance this model asserts, and which test_regen_energy_balance pins:
        #     ΔKE = W_friction + ∫|p_shaft| dt
        #     ∫|p_shaft| dt * ETA_REGEN = E_regen_electrical
        #     E_regen_electrical = E_chopper + E_charger + ΔE(C_MOT_NODE)
        # i.e. nothing is created and nothing vanishes; the old floor violated the
        # second line by setting its right-hand side to zero.
        p_shaft = f_drive * self.v
        p_mech = p_shaft if p_shaft > 0.0 else 0.0
        self.p_regen_w = (-p_shaft) * ETA_REGEN if p_shaft < 0.0 else 0.0
        # Mode-independent accounting: what the mechanical side HANDED to the
        # electrical side.  Where it went is mode-specific (the chopper term below
        # in simple mode; ElectricalSim's own counters in hi-fi).
        self.regen_energy_j += self.p_regen_w * dt
        self.e_brake_mech_j += (-p_shaft) * dt if p_shaft < 0.0 else 0.0
        if mot_live and self.v_bus > 1.0:
            i_motor = p_mech / (ETA_BOOST * self.v_bus)
        else:
            i_motor = 0.0
        i_motor += self.i_mot_extra if mot_live else 0.0

        # ── CHARGER BILLING — ONE RULE, BOTH ENGINES (2026-09-01) ────────────
        # The Ag105 is an energy converter at a static efficiency ETA_CHG (the
        # constant carries the datasheet citation).  It is billed ON ITS INPUT
        # NODE, and the input current is always the output current referred
        # through the voltage ratio and the efficiency:
        #     i_in = i_charge * V_pack / (ETA_CHG * V_input)
        # The pack always receives exactly `i_charge`; efficiency never moves
        # the pack current, only the input draw.
        #
        # WHICH NODE IS THE INPUT is a switch question, and it is the SAME
        # question in both engines because both read chargerHasPower():
        #   * FC_CHARGE closed          -> the input is VBUS, so the SOURCES pay
        #                                  (hi-fi: the N_CHG stamp is fed from
        #                                  N_BUS through the FC_CHARGE link;
        #                                  simple: `i_chg_in` is added to
        #                                  `i_total` here).
        #   * REGEN + MOT_PWR only      -> the input is V-MOT, so the BRAKING
        #                                  POWER pays and the bus is untouched
        #                                  (hi-fi: the same stamp is fed from
        #                                  N_MOT through the REGEN link; simple:
        #                                  `i_sink` on the motor node, further
        #                                  down in this method).
        # The two sites below and hil_electrical.py's N_CHG stamp are the three
        # places that implement this rule; they must not diverge.
        #
        # BEFORE THIS ROUND the two engines held OPPOSITE errors: hi-fi drew
        # i_charge 1:1 from the input node (destroying i_charge*(V_chg-V_pack),
        # ~11 W on a 1.4 A window, and over-drawing the bus ~1.8x), while simple
        # mode never billed the sources for the charger at all and treated pack
        # charge as free energy.  Both are now the one rule above.
        #
        # `self.i_charge` here is last TICK's Ag105 current — this tick's value
        # is computed in the Ag105 state machine further down, after the
        # electrical section.  That is the same deliberate one-tick lag hi-fi
        # already accepts on `i_charge_into_pack` (L5), and it is negligible
        # against the 0.4 s AG105_TAU_S ramp.  `self.battery.v_terminal` is read
        # for the same reason: this tick's terminal voltage is not solved yet.
        # SO IS `self.v_bus` in the denominator below — the simple engine writes
        # the bus voltage from its own droop law further down in this method, so
        # every one of the three factors in this expression is last tick's.  All
        # three are slow against a 1 ms tick, so the lag is a consistent
        # one-tick delay of the whole term rather than a mix of eras.
        #
        # ONE-TICK CROSS-PATH MIS-BILLING, stated because it is a real (bounded)
        # artefact: the switch word `sw` is THIS tick's while `i_charge` is last
        # tick's, so on the single tick where the firmware closes FC_CHARGE and
        # opens REGEN (or the reverse) in one word, the charger's input draw is
        # billed to the path that is live NOW against a current that was drawn
        # from the OTHER path.  It is one tick of at most ~0.5 A on the wrong
        # node, it self-corrects on the next tick, and the alternative (latching
        # the path with the current) would misreport every genuine handover by
        # the same tick in the other direction.
        #
        # `i_total` is consumed by the SIMPLE branch only (hi-fi is handed
        # `i_motor` and `i_aux` separately and solves the charger draw inside
        # its own network), so adding the term here cannot bill it twice.
        i_chg_in = 0.0
        if self.electrical is None and self.i_charge and (sw & SW_FC_CHARGE):
            i_chg_in = (self.i_charge * self.battery.v_terminal
                        / (ETA_CHG * max(self.v_bus, V_CHG_LOAD_FLOOR)))
        i_total = i_motor + self.i_aux + i_chg_in

        if self.electrical is not None:
            # ── Hi-fi delegation ────────────────────────────────────────────
            # Only the ELECTRICAL section is delegated.  The mechanical model above
            # and the Ag105 status logic below stay here, so a scenario behaves the
            # same way in either mode apart from the electrical fidelity itself.
            self.electrical.i_aux = self.i_aux
            # M5 DEVIATION: hi-fi's v_bus_sense_offset is SENSED-RAIL-ONLY (added
            # only in ElectricalSim._rails(), never seen by the node/diode/chopper
            # network) -- an intentional asymmetry against simple mode, where the
            # same scenario offset IS a real algebraic disturbance on V_bus.  See
            # hil_electrical.py's ElectricalSim.__init__ comment and
            # docs/HIL_PLANT.md's scenario table for the full rationale.
            self.electrical.v_bus_sense_offset = self.v_bus_offset
            # L5: self.i_charge here is last TICK's Ag105 current -- this tick's
            # value is computed further down in the Ag105 state machine below,
            # after the electrical substeps have already run.  Deliberate and
            # harmless: one 1 ms tick of lag against a 0.4 s (AG105_TAU_S) charger
            # ramp is not an ordering bug to fix.
            self.electrical.i_charge_into_pack = self.i_charge
            rails = self.electrical.step(dt, {
                "sw": sw, "aux": aux, "i_motor_a": i_motor,
                "code_fc": code_fc, "code_bt": code_bt,
                "i_charge_a": self.i_charge,
                # WP-C: braking power, stamped as a bounded Norton source on N_MOT.
                # The plant owns the mechanical->electrical conversion (it owns
                # ETA_REGEN and the clip); the engine owns where the power goes.
                "p_regen_w": self.p_regen_w,
            })
            self.v_bus = rails["V_bus"]
            self.i_fc = rails["I_fc"]
            self.i_batt = rails["I_batt"]
            self.v_chg = rails["V_chg"]
            self.v_rgn = rails["V_rgn"]
            v_fc = rails["V_fc"]
            v_batt = rails["V_batt"]
            # Mirror the engine's chopper accounting onto the plant so both modes
            # expose the same two names to a test or a CSV consumer.
            self.regen_chopper_energy_j = self.electrical.chopper_energy_j
            self.regen_chopper_w = (self.v_rgn *
                                    chopper_dump_current(self.v_rgn))
        else:
            # ── Simple droop node ───────────────────────────────────────────
            if fc_live or bt_live:
                # MEASURED droop, mode-aware: the fit separates cleanly into a
                # both-sources-live regime and a single-source regime (see the
                # K_DROOP_BUS_* constants).  The old single source-agnostic
                # 0.35 V/A placeholder is retired.
                k = K_DROOP_BUS_SHARED if (fc_live and bt_live) else K_DROOP_BUS_SINGLE
                self.v_bus = V_BUS_DROOP_V0 - k * i_total + self.v_bus_offset
                # ── PART A (C1, 2026-09-01): split by droop code ratio ───────
                # SIGN FIX.  The firmware commands
                #     g_FC = K_DROOP/(RE_MAX * r),  g_BT = K_DROOP/(RE_MAX*(1-r))
                # (teensy_controller.ino:10534-10535), so each channel's droop
                # RESISTANCE is proportional to its code and its current is
                # proportional to the RECIPROCAL of that code.  The FC share is
                # therefore
                #     frac_fc = (1/code_fc)/((1/code_fc)+(1/code_bt))
                #             =  code_bt/(code_fc + code_bt)
                # The previous form used code_fc/(code_fc+code_bt), which has the
                # authority of the share loop INVERTED: raising the FC code
                # raises the FC droop resistance and LOWERS its current.  The
                # error was invisible to the suite because simple mode's split
                # is only ever read alongside a commanded ratio that the firmware
                # itself computes, so both ends moved together.
                if fc_live and bt_live:
                    denom = code_fc + code_bt
                    frac_fc = (code_bt / denom) if denom > 1e-9 else 0.5
                    frac_fc = self._apply_simple_asymmetry(frac_fc, i_total)
                elif fc_live:
                    frac_fc = 1.0
                else:
                    frac_fc = 0.0
                self.i_fc = i_total * frac_fc
                self.i_batt = i_total * (1.0 - frac_fc)
            else:
                # No source closed: the 470 uF bulk decays through its bleed path.
                tau = R_BUS_BLEED * C_BUS_F
                self.v_bus += (-self.v_bus / tau) * dt
                self.i_fc = 0.0
                self.i_batt = 0.0
            self.v_bus = max(0.0, self.v_bus)

            # Source terminals from the shared source models: the fuel cell's
            # polarization curve + double-layer lag, and the pack's OCV(SOC) with
            # its coulomb count.  Currents are referred to the source side.
            i_fc_src = ElectricalSim._source_current(
                self.i_fc, self.fuel_cell.v_terminal, self.v_bus)
            i_bt_src = ElectricalSim._source_current(
                self.i_batt, self.battery.v_terminal, self.v_bus)
            v_fc = self.fuel_cell.update(dt, i_fc_src)
            # Net pack current: boost draw minus the Ag105's charge current.
            v_batt = self.battery.update(dt, i_bt_src - self.i_charge)

            # TOPOLOGY FIX (2026-08-30, schematic sheet 4): V_rgn's divider sits
            # on V-MOT itself, UPSTREAM of the REGEN switch — in this bus-level
            # model the motor node tracks the bus whenever MOT_PWR is closed.
            # The firmware's staged-bring-up P3 gate reads V_rgn as its motor-node
            # proxy, so the old SW_REGEN gating made every bring-up fail P3.
            # V_chg is the shared VCHG-IN node, fed by EITHER path switch
            # (FC_CHARGE from the bus; REGEN from V-MOT, which needs MOT_PWR up).
            #
            # WP-C: with regen power present the motor node LEAVES the bus.  The
            # MOT_PWR RT1987 blocks reverse (see the C_MOT_NODE_F banner), so the
            # injected current charges C_MOT_NODE_F until the chopper clamps —
            # integrated as a genuine first-order node rather than snapped to the
            # clamp, so the model reproduces the bench RAMP (V_rgn 13.3 -> 18.1 V)
            # and not just its endpoint.  With no regen this reduces EXACTLY to the
            # pre-WP-C line above.
            mot_closed = bool(sw & SW_MOT_PWR)
            chg_fed = bool(sw & SW_FC_CHARGE) or (bool(sw & SW_REGEN) and mot_closed)
            if not mot_closed:
                self.v_rgn = 0.0
            elif self.p_regen_w <= 0.0:
                self.v_rgn = self.v_bus
            else:
                v_node = max(self.v_rgn, self.v_bus, 1.0)
                # Same bounded source law as the hi-fi stamp: capped current, and
                # zero delivery at the V_REGEN_OC_MAX open-circuit bound.
                i_reg = min(self.p_regen_w / v_node, REGEN_I_SRC_MAX_A)
                if v_node > V_CHOPPER_TRIP:
                    # Taper to zero at the open-circuit bound (the VESC's own
                    # DC-link cutback).  Below the clamp the source is unfolded,
                    # exactly as the hi-fi Norton is at its operating point.
                    span = V_REGEN_OC_MAX - V_CHOPPER_TRIP
                    i_reg *= max(0.0, min(1.0, (V_REGEN_OC_MAX - v_node) / span))
                # Sinks on the node: the charger (only when the REGEN path is the
                # one feeding it) and the chopper.
                #
                # The charger sink is INPUT-referred, per the CHARGER BILLING
                # rule above: the motor node gives up
                # i_charge*V_pack/(ETA_CHG*V_node), not `i_charge` itself.  Before
                # this round it gave up `i_charge` and the pack received the same
                # amperes at a third of the voltage, which manufactured energy on
                # the regen path exactly as the bus path destroyed it.
                i_sink = ((self.i_charge * self.battery.v_terminal
                           / (ETA_CHG * max(v_node, V_CHG_LOAD_FLOOR)))
                          if (bool(sw & SW_REGEN) and not (sw & SW_FC_CHARGE))
                          else 0.0)
                i_sink += chopper_dump_current(v_node)
                v_node += ((i_reg - i_sink) / C_MOT_NODE_F) * dt
                # The node cannot fall below the bus: MOT_PWR conducts FORWARD, so
                # the bus back-fills it the moment regen stops supporting it.
                self.v_rgn = max(self.v_bus, min(v_node, V_REGEN_OC_MAX))
            self.regen_chopper_w = (self.v_rgn * chopper_dump_current(self.v_rgn)
                                    if mot_closed else 0.0)
            self.regen_chopper_energy_j += self.regen_chopper_w * dt
            self.v_chg = self.v_rgn if (bool(sw & SW_REGEN) and mot_closed
                                        and not (sw & SW_FC_CHARGE)) else \
                (self.v_bus if chg_fed else 0.0)

        # ── Ag105 charger ────────────────────────────────────────────────────
        # Power gating mirrors the firmware's chargerHasPower(): FC_CHARGE closed, or
        # REGEN and MOT_PWR both closed.  The rail actually presented to the module has
        # to be up as well — a closed switch onto a collapsed bus charges nothing.
        chg_path = bool(sw & SW_FC_CHARGE) or (bool(sw & SW_REGEN) and bool(sw & SW_MOT_PWR))
        # v_chg is the shared VCHG-IN node and already reflects whichever path
        # feeds it (2026-08-30 topology fix), so it IS the module's input rail.
        v_chg_in = self.v_chg
        chg_powered = chg_path and v_chg_in >= AG105_V_IN_MIN and not self.chg_fault
        if chg_powered:
            self.chg_powered_s += dt
        else:
            self.chg_powered_s = 0.0

        # ── MPPT input-voltage threshold (Layer 1, opt-in) ───────────────────
        # THE PART'S ACTUAL MECHANISM (AG105_Silvertel.pdf p.10): charging
        # commences only above an input-voltage threshold, 18 V by default with
        # MPPTS open.  See the AG105_MPPT_V_THRESH banner, including R1.
        #
        # THE THRESHOLD IS DYNAMIC FROM fw v24.  The firmware writes reg 0x02 and
        # reports the count it believes is in force on observation-frame byte 15
        # (.ino:2911-2938; the HIL mirror that computes it is .ino:11185-11201).
        # `obs["mppt_cnt"]` is therefore the module's ACTUAL threshold as far as
        # this model is concerned, and the 18 V constant applies only when there
        # is no count (legacy frame / resistor mode / no frame yet).
        thresh_cnt = obs.get("mppt_cnt") if obs else None
        if thresh_cnt is None or int(thresh_cnt) > AG105_MPPT_N_MAX:
            mppt_v_thresh = AG105_MPPT_V_THRESH
        else:
            mppt_v_thresh = ag105_mppt_volts(thresh_cnt)
        #
        # THE ASYMMETRY IS THE DATASHEET'S OWN, not a modelling shortcut: the
        # threshold belongs to the MPPT regulator, so it binds only while
        # tracking is RELEASED.  MPPT_DISABLE is ACTIVE-LOW, so:
        #   pin HIGH (bit set) = tracking released -> the threshold applies;
        #   pin LOW            = tracking inhibited -> it does not, and the
        #                        existing constant-current behaviour is verbatim.
        # Hysteresis is on the VOLTAGE COMPARISON only (release needs
        # thresh + hyst, inhibit needs < thresh), never on the pin — the pin is
        # the firmware's output and this model must not filter it.
        if not (self.mppt_emulation and chg_powered and (aux & AUX_MPPT_DISABLE)):
            self.mppt_inhibited = False
        elif self.mppt_inhibited:
            if v_chg_in >= mppt_v_thresh + AG105_MPPT_V_HYST:
                self.mppt_inhibited = False
        elif v_chg_in < mppt_v_thresh:
            self.mppt_inhibited = True

        if not chg_powered:
            # Input removed: the module is dark.  0x00 is what the firmware's own failed-read
            # path leaves behind, and it decodes as GENSTAT "Battery Disconnect".
            self.i_charge = 0.0
            self.ag105_status = AG105_ST_DISCONNECT
        elif self.mppt_inhibited and self.chg_powered_s >= AG105_SETTLE_S:
            # Powered and settled, tracking RELEASED, but the input rail is below
            # the MPPT threshold: the module does not commence charging.  Current
            # decays on the same AG105_TAU_S the ramp uses, and GENSTAT reports
            # 001 "Low Power" — which is NOT one of ag105IsReady()'s accepted
            # states, so the firmware sees the charger drop out of readiness.
            #
            # MPPT_EN is set (the pin released it) but PWR_TRACK is CLEAR: the
            # module is not tracking input power, it is refusing to.  That flag
            # pair — 0x08 with bit 4 low — is the observable this whole gate adds,
            # and it cannot be produced by any other path in this model.
            #
            # The `chg_powered_s >= AG105_SETTLE_S` term keeps the bring-up window
            # ahead of this branch: a module still settling reports Bring-Up
            # Charge regardless of the pin, exactly as before.
            #
            # L1 (review 2026-08-31) — PRECEDENCE: this branch sits AHEAD of the
            # `soc >= 0.995` FULL branch, so a full pack whose input rail is
            # under the threshold with tracking released reports LOW_POWER, not
            # FULL.  That ordering is the physical one (a module refusing to
            # draw input power is not charging to full), and it is UNREACHABLE
            # in every shipped scenario: `mppt_emulation` is on only in
            # `mppt-tracking`, whose soc0 is nowhere near 0.995, and
            # `charge-to-full` deliberately leaves it off.
            self.i_charge += (0.0 - self.i_charge) * (dt / AG105_TAU_S)
            self.ag105_status = AG105_ST_LOW_POWER | AG105_FLAG_MPPT_EN
        elif self.chg_powered_s < AG105_SETTLE_S:
            # Bring-up window (AG105_SETTLE_MS in the .ino).  Report Bring-Up Charge with no
            # current yet, so ag105IsReady() stays false until the module is genuinely up —
            # which is what gates chargingControl()'s MPPT release.
            self.i_charge = 0.0
            self.ag105_status = AG105_ST_BRINGUP
        elif self.battery.soc >= 0.995:
            # The pack is full.  With the SOC model in place (scope extension,
            # 2026-08-27) the charger CAN now reach Fully Charged, which the old
            # SoC-free model never could.  Current tapers to zero and GENSTAT
            # reports 011 (Fully Charged) — the state the firmware's ag105IsReady()
            # and detectFaults() GENSTAT decode both have to handle.
            self.i_charge += (0.0 - self.i_charge) * (dt / AG105_TAU_S)
            self.ag105_status = AG105_ST_FULL | AG105_FLAG_CV
            if aux & AUX_MPPT_DISABLE:
                self.ag105_status |= AG105_FLAG_MPPT_EN | AG105_FLAG_PWR_TRACK
        else:
            # Constant-current charging into the 2S pack, ramped first-order toward
            # `self.ag105_i_max` (AG105_I_MAX 2.5 A unless the scenario de-rates it
            # via chg_i_ceiling_a).  The current is fed back into the pack's
            # coulomb count (BatterySource, negative = charge), so a long
            # `charge-cruise` run visibly walks V_batt up the OCV curve.
            #
            # WP-C: the ceiling is min(configured profile, INPUT POWER AVAILABLE).
            # It binds ONLY on the regen-fed path: with FC_CHARGE closed the bus
            # (fuel cell + pack) is the input and is effectively unlimited at these
            # currents, so that branch is verbatim pre-WP-C.  Fed through REGEN
            # alone, the input is the braking power and nothing else — a charger
            # that drew its 2.5 A profile from a 3 W brake would be manufacturing
            # energy.
            #
            # THE CAP IS NOW OUTPUT-REFERRED AND EXACT (2026-09-01).  It used to
            # be p_regen_w/v_in — an INPUT-referred current compared against an
            # OUTPUT-referred target, which understated the harvest by roughly
            # v_in/v_pack and was left standing only because no efficiency
            # figure was in the model.  With ETA_CHG the conversion is defined:
            # the braking power p_regen_w buys ETA_CHG*p_regen_w of pack power,
            # i.e. ETA_CHG*p_regen_w/V_pack amperes into the pack.  The pack
            # terminal voltage carries the same V_CHG_LOAD_FLOOR floor as every
            # other charger expression here.
            #
            # THE CHOPPER IS DELIBERATELY *NOT* NETTED OUT OF THIS CAP, and the
            # alternative was measured before that was decided (2026-09-01,
            # review round).  The proposal was
            # `p_avail = max(0, p_regen_w - regen_chopper_w)`, on the reading
            # that the shunt takes its share first and the charger may only have
            # the remainder.  MEASURED on a 2 s braking window (v0 = 3.0 m/s,
            # i_cmd -12 A, `--electrical` both):
            #
            #   engine   cap        charger input   chopper burnt   bus-sourced
            #   simple   as shipped   1.4388 J        1.7128 J       +0.0000 J
            #   simple   netted       0.0045 J        3.1314 J       +0.0000 J
            #   hi-fi    as shipped   1.4016 J        1.3046 J       +0.0915 J
            #   hi-fi    netted       0.7632 J        1.7950 J       +0.0318 J
            #
            # The netted form removes 0.06 J of bus-sourced leak and destroys
            # 0.64 J (hi-fi) to 1.43 J (simple) of genuine harvest.  The reason
            # is a modelling fact about the shunt: THE CHOPPER IS A RESIDUAL
            # ABSORBER, NOT A PRIOR CLAIMANT.  It is a voltage clamp, so a
            # charger that sinks current pulls the node down and the clamp backs
            # off — visible in the simple-mode row above, where the charger's
            # 1.4388 J of input is matched by the chopper burning 1.4230 J LESS
            # and the bus contributing exactly nothing.  Netting removes that
            # displacement and latches the charger off: the chopper burns
            # everything, so `p_avail` is ~0, so the hard clamp below slams
            # `i_charge` to ~0, so the chopper keeps burning everything.  The
            # pre-existing WP-C test
            # `test_charger_takes_its_share_once_powered_through_the_regen_path`
            # fails outright under the netted form (0.0015 A peak against its
            # 0.02 A floor), which is the independent evidence.
            #
            # WHAT IS LEFT UNFIXED, stated rather than papered over: the hi-fi
            # row shows 0.088059 J of the 1.4016 J charger input arriving from
            # the BUS through a closed MOT_PWR — 6.28 % of the window's harvest.
            # ⚠️ MECHANISM CORRECTED 2026-09-02 (review PLANT-R1-F2). This was
            # recorded as a TRANSIENT of the node solve; it is not. It is
            # POST-CLAMP-RELEASE BUS-FED CHARGING: while the chopper is clamping,
            # V_MOT sits at 18.135 V, MOT_PWR is strict-forward and therefore not
            # stamped at all, and the bus contributes EXACTLY zero (measured to
            # 1e-6 J, and deleting the link changes the total by 0 J). Once
            # braking ends the node falls, V_bus rises above it by more than
            # RT_V_FWD, and the charger — still ramping down through AG105_TAU_S
            # — is fed forward through the link at 0.118 W steady. Simple mode
            # leaks zero because it has no such link, not because it has no
            # transient.
            # The co-solved-split `TODO(verify)` that stood here is RETIRED: a
            # co-solve addresses a contention between the charger and the clamp
            # at one node voltage, and the two are never both active on the
            # leaking ticks. What would change the number is the AG105_TAU_S
            # ramp-down or a reverse-blocking rule on the charger's input, not
            # the solver. §4.6.2 carries the full record.
            i_target = self.ag105_i_max
            if (sw & SW_REGEN) and not (sw & SW_FC_CHARGE):
                i_target = min(i_target,
                               ETA_CHG * self.p_regen_w
                               / max(self.battery.v_terminal, V_CHG_LOAD_FLOOR))
            self.i_charge += (i_target - self.i_charge) * (dt / AG105_TAU_S)
            if i_target < self.ag105_i_max:
                # HARD clamp on top of the first-order ramp.  The ramp LAGS, so a
                # falling brake (which every braking window is) would leave the
                # charger drawing yesterday's current out of today's smaller
                # source — energy creation by discretization.  The ramp still owns
                # the RISING edge, which is the physical one (AG105_TAU_S).
                self.i_charge = min(self.i_charge, i_target)
            self.ag105_status = AG105_ST_CHARGING | AG105_FLAG_CC
            # MPPT_DISABLE is ACTIVE-LOW: pin HIGH releases the tracking loop, pin LOW
            # inhibits it.  Only the two tracking flags follow it; charging continues either
            # way (the firmware asserts it during regen precisely so charging is not disturbed).
            if aux & AUX_MPPT_DISABLE:
                self.ag105_status |= AG105_FLAG_MPPT_EN | AG105_FLAG_PWR_TRACK

        # ── Hydrogen consumption ─────────────────────────────────────────────
        # u = P_fc = STACK power, from plant truth: the FuelCellSource's own
        # terminal voltage and its own current, both already advanced for this
        # tick by whichever electrical branch ran (simple mode calls
        # fuel_cell.update() above; hi-fi mode owns the same object).
        #
        # WHY NOT `v_fc * self.i_fc` (which is what the CSV/injection frame
        # carry): self.i_fc is the BUS-SIDE channel current, i.e. the boost
        # OUTPUT, while v_fc is the SOURCE-SIDE terminal voltage.  Their product
        # is a mixed quantity and understates stack power by roughly
        # V_bus/(eta*V_fc).  Gfc's input is fuel-cell power, so the source-side
        # pair is the correct one.  CONSEQUENCE, stated because it costs
        # something: this metric is NOT reconstructible from the CSV's V_fc and
        # I_fc columns alone — h2_rate_gps/h2_cum_g are logged for exactly that
        # reason.
        self.h2.step(self.fuel_cell.v_terminal * self.fuel_cell.i, dt)

        # ── Per-tick power balance (2026-09-01f, both electrical modes) ──────
        # Pure OBSERVERS.  Nothing in the plant, the electrical engine, the
        # injection frame or any policy reads these back, so they cannot change a
        # trace — the same contract the h2 and regen-energy counters hold.
        #
        # THE IDENTITY THE OPERATOR ASKED FOR, and the honest form of it:
        #     p_mot + p_chg_loss = p_fc + p_batt + p_chop + p_bal
        # `p_bal` is written out so a consumer can test the identity per tick
        # without recomputing it.  It is NOT zero, and the named terms it
        # contains are, in descending magnitude:
        #   1. the auxiliary housekeeping load, -p_aux (I_AUX_A plus any scenario
        #      preload/drain, on VBUS).  It is the dominant component and is
        #      written out as its own column so a reader can subtract it.
        #   2. bulk-capacitor storage, d/dt(0.5*C*V^2) on the VBUS 470 uF and, in
        #      hi-fi, on the other node capacitances.
        #   3. the hi-fi motor stamp's own transient term.  The load is stamped
        #      as a conductance g_mot = i_motor/v_prev (hil_electrical.py, `g_mot`),
        #      so the solved tick actually draws i_motor*v_new^2/v_prev while
        #      p_mot books i_motor*v_new — a difference of
        #      i_motor*v_new*(v_new - v_prev)/v_prev.  With (2) this is what
        #      makes the motoring residual peak near 13 W during bring-up while
        #      its steady-state mean is under 0.4 W.
        #   4. RT1987 ideal-diode drops, i_motor*(V_bus - V_rgn): SMALL, <= 35 mW
        #      at 1 A (the servo holds ~35 mV, not a PN Vf).
        #   5. the chopper's sign in this identity form.  `p_chop` is a
        #      DISSIPATION but is grouped with the sources, so during a braking
        #      window it enters the residual twice over.  Pre-existing, not
        #      changed here, and stated so nobody reads the braking residual as
        #      a charger or storage effect: it is dominated by -2*p_chop.
        # A reader who wants only 2-5 reads `p_bal_w - p_aux_w`.
        #
        # ── THE CHARGER TERM IS NOW NAMED (2026-09-01) ──────────────────────
        # It used to be the largest unnamed component of this residual, and it
        # was not an efficiency term at all.  The model's Ag105 was a 1:1
        # CURRENT transfer element (hil_electrical.py stamped `J[N_CHG] -=
        # i_charge` and handed the pack THE SAME `i_charge`), so it destroyed
        # i_charge*(V_chg - V_batt) by construction — measured on the 6 s probe
        # at 1.4 A * 7.9 V = 11.06 W against a residual of 11.08 W, i.e. the
        # whole charge-window residual to two decimals.  Simple mode held the
        # OPPOSITE error: `i_total = i_motor + i_aux` never billed the sources
        # for the charger at all, so pack charge there was free energy.
        #
        # Both engines now run the CHARGER BILLING rule stated earlier in this
        # method: input power = output power / ETA_CHG, at a static 0.88 with a
        # datasheet anchor (see ETA_CHG in hil_electrical.py).  What is left is
        # the module's own dissipation, and it is written out as its own column
        # rather than left in the residual:
        #     p_chg_loss = i_charge * V_batt * (1/ETA_CHG - 1)
        # On the same 6 s probe that is 1.51 W where the unnamed term was
        # 11.06 W.  CONSEQUENCE, stated because it is load-bearing elsewhere:
        # the old over-draw billed the sources for hydrogen the real charger
        # would not cost, so this change bears directly on campaign
        # 20260901_000816's "Ag105 charging is loss-making at rig scale"
        # conclusion and on the measured charge lever L_chg = 0.2364 SoC/g
        # behind sdp_policy_v3's alpha calibration.  Both were measured under
        # the 1:1 era and must be re-measured before being quoted again.
        #
        # ONE TICK OF THE LOSS COLUMN IS NOT THE ONE THAT WAS BILLED.
        # `p_chg_loss_w` below is computed from THIS tick's `i_charge` (the Ag105
        # state machine has already run by then), while the two billing sites
        # draw last tick's.  The identity is therefore off by
        # d(i_charge)*V_batt*(1/eta - 1) on any tick where the charge current is
        # moving — bounded by the AG105_TAU_S ramp at ~0.004 A/tick, i.e. under
        # 5 mW, and identically zero at the steady state where every number in
        # this block was measured.
        #
        # WHY p_mot IS BOOKED AT V-MOT AND NOT AT VBUS: the REGEN SIGN, not the
        # diode drop.  Braking power enters the network at N_MOT and leaves
        # through REGEN to the charger, never back through MOT_PWR (the RT1987
        # blocks reverse).  A VBUS booking, V_bus*i_motor, is therefore
        # IDENTICALLY ZERO throughout every braking window — it would show no
        # returned energy at all.  The RT1987 drop that item 5 adds to the
        # residual is the price of that correctness, and it is negligible.
        #
        # MOTORING AND BRAKING NEVER OVERLAP: p_mech is p_shaft clipped at zero
        # and p_regen_w is (-p_shaft)*ETA_REGEN clipped at zero, from ONE
        # p_shaft, so at most one of the two is non-zero on any tick.  i_motor is
        # therefore zero whenever p_regen_w is positive, and the two branches of
        # p_mot_w below are exclusive by construction, not by convention.
        #   motoring: +i_motor * v_rgn  (the draw the V-MOT node presents)
        #   braking:  -p_regen_w        (electrical power returned at V-MOT)
        # i_motor also carries `i_mot_extra`, the scenario load BEHIND MOT_PWR,
        # which sits on the same node.
        self.p_mot_w = (i_motor * self.v_rgn) - self.p_regen_w
        # BUS-SIDE fuel-cell power.  This is NOT the stack power the Gfc
        # hydrogen metric integrates (that is v_terminal*i on the SOURCE side,
        # see the H2Consumption call above); the two differ by the boost
        # efficiency and the boost's voltage ratio.  Do not substitute one for
        # the other.
        self.p_fc_w = self.v_bus * self.i_fc
        # NET pack power: the bus-side draw of the battery boost, minus the power
        # the Ag105 delivers into the pack TERMINALS (the pack's own I^2*R sits
        # inside that boundary and is not separated out).  The charge term uses
        # `i_charge` and
        # the pack TERMINAL voltage — the same current the SoC integrator is
        # given in both engines (simple mode: battery.update(dt, i_bt_src -
        # i_charge); hi-fi: ElectricalSim's identical line with
        # i_charge_into_pack) — so this column and the `soc` column tell one
        # story.  Charging therefore drives p_batt_w negative.
        #
        # THE CHARGE TERM READS `battery.v_terminal`, NOT THE SENSED `v_batt`
        # (review fix, 2026-09-01).  `v_batt` is the rail as the BOARD would
        # measure it, and in hi-fi under `--noise` that is the plant truth plus
        # a sense perturbation.  The charger stamp bills the CLEAN terminal
        # voltage (hil_electrical.py's N_CHG stamp uses `v_bt_term`), so billing
        # this column off the sensed value left the identity failing to close by
        # the sense error alone.  The two V_bus*I terms deliberately stay on the
        # sensed side: they are the bus powers a consumer reconstructs from the
        # CSV's own rail and current columns, and moving them would break that
        # correspondence.
        v_bt_term = self.battery.v_terminal
        self.p_batt_w = self.v_bus * self.i_batt - v_bt_term * self.i_charge
        # Braking-shunt dissipation.  Both engines populate regen_chopper_w: hi-fi
        # mirrors it from the engine's own clamp above, simple mode integrates it
        # on the motor node.
        self.p_chop_w = self.regen_chopper_w
        # Auxiliary housekeeping load on VBUS, including any scenario preload or
        # drain.  The largest known residual component.
        self.p_aux_w = self.v_bus * self.i_aux
        # Ag105 dissipation, >= 0 by construction (i_charge is never negative;
        # the pack current sign convention lives in BatterySource).  APPENDED as
        # the seventh power column, 2026-09-01: the six columns above keep their
        # meanings and their positions exactly.  It reads the CLEAN terminal
        # voltage for the same reason the charge term above does.
        self.p_chg_loss_w = (self.i_charge * v_bt_term * (1.0 / ETA_CHG - 1.0)
                             if self.i_charge > 0.0 else 0.0)
        # `p_chg_loss_w` joins the LOAD side of the identity (it is a
        # dissipation, like the motor draw), so it leaves the residual.  The
        # other five terms are untouched; only `p_bal_w`'s content changes, and
        # it changes by exactly the named amount.
        self.p_bal_w = (self.p_mot_w + self.p_chg_loss_w
                        - (self.p_fc_w + self.p_batt_w + self.p_chop_w))

        return {
            "V_fc": v_fc,
            "V_batt": v_batt,
            "V_bus": self.v_bus,
            "V_chg": self.v_chg,
            "V_rgn": self.v_rgn,
            "I_fc": self.i_fc,
            "I_batt": self.i_batt,
            "v_actual": self.v,
            "I_charge": self.i_charge,
            "ag105_status": self.ag105_status,
            # Appended (never reordered) for the CSV's new `soc` column.
            "soc": self.battery.soc,
            # Appended (never reordered), 2026-08-31 — the H2 metric.  These are
            # NOT injected: pack_inject() takes its fields by name and never
            # sees them, so the wire protocol (40 B) is untouched.  Read the
            # H2Consumption banner before quoting either value.
            "h2_rate_gps": self.h2.rate_gps,
            "h2_cum_g": self.h2.cum_g,
            # Appended (never reordered), 2026-08-31 — the STUDENT'S STATIC
            # PROXY on the same P_fc input.  A SECOND MODEL of the same
            # quantity, not a second measurement: read one axis at a time (see
            # the H2_SDP_PROXY_* banner).
            "h2_sdp_cum_g": self.h2.proxy_cum_g,
            # Appended (never reordered), 2026-09-01f — the per-tick power
            # balance.  Also NOT injected: pack_inject() takes its fields by
            # name, so the 40-byte wire protocol is untouched.  Read the block
            # at the end of step() before quoting the residual.
            "p_mot_w": self.p_mot_w,
            "p_fc_w": self.p_fc_w,
            "p_batt_w": self.p_batt_w,
            "p_chop_w": self.p_chop_w,
            "p_aux_w": self.p_aux_w,
            "p_bal_w": self.p_bal_w,
            # Appended (never reordered), 2026-09-01 — the Ag105's own
            # dissipation, the term the eta model took OUT of `p_bal_w`.
            "p_chg_loss_w": self.p_chg_loss_w,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Replay source — a decoded .BLG bench log played back as injection frames.
# ─────────────────────────────────────────────────────────────────────────────
# BLG record field  ->  injection frame field.  The names on the left are the
# decoder's own CSV column names (tools/decode_benchlog.py CSV_FIELDS_V*), read
# from DecodeResult.csv_header at runtime — nothing here is guessed.
REPLAY_FIELD_MAP = [
    ("V_fc",   "V_fc"),
    ("V_batt", "V_batt"),
    ("V_bus",  "V_bus"),
    ("V_chg",  "V_chg"),
    ("V_rgn",  "V_rgn"),
    ("I_fc",   "I_fc"),
    ("I_batt", "I_batt"),
    ("v_act",  "v_actual"),
]

# ── Replayed COMMANDS (--replay-commands) ───────────────────────────────────
# The same decoder CSV columns, but these do NOT go into the injection frame:
# they are carried alongside the sensors and, when --replay-commands is given,
# drive the 22-byte Pi command packet so the firmware's drive/share loops
# actually STEP against the recorded stimulus instead of sitting in Idle.
# `v_sp` and `share_sp` exist in EVERY BLG format v1-v7 (decode_benchlog.py
# CSV_FIELDS*), and like REPLAY_FIELD_MAP they are resolved by NAME at runtime.
# The keys land in the same per-record sensors dict; the injection-frame packer
# reads its fields explicitly, so these extra keys are inert without the flag.
REPLAY_CMD_FIELD_MAP = [
    ("v_sp",     "cmd_v_sp"),
    ("share_sp", "cmd_share_sp"),
]
# Values used when the source column is absent or blank.  `v_sp` cells are BLANK
# when the record's velocity-valid flag (bit1) is clear — the same convention the
# sensor loop uses for v_act — so 0.0 m/s is the honest command.  `share_sp` is
# always numeric in every format, but 0.5 (balanced) is the neutral fallback.
REPLAY_CMD_DEFAULT = {"cmd_v_sp": 0.0, "cmd_share_sp": 0.5}

# The BLG record carries NO charge-current and NO Ag105 status field in any
# format version v1-v7 (see decode_benchlog's record tables), so these two
# injection-frame fields are replayed as zeros: I_charge = 0.0 A and
# ag105_status = 0x00, which decodes as GENSTAT "Battery Disconnect" — exactly
# what the firmware's own failed-read path leaves behind.
REPLAY_I_CHARGE = 0.0
REPLAY_AG105_STATUS = AG105_ST_DISCONNECT

# ── Absent-rail substitution (2026-08-30, HIL_FINDINGS "Replay half") ────────
# BLG v1/v2 records carry NO V_fc / V_batt / V_rgn field at all.  Injecting 0.0 V
# for them — the old behaviour — hands the firmware a DARK board: the staged
# bring-up's P3 gate reads V_rgn as its motor-node proxy, so it never tracked
# V_bus and every v1/v2 replay latched FAULT_MOT_HOTPLUG at ~1.09 s, long before
# the recorded stimulus (a bus collapse) ever arrived.  The zeros were an
# artefact of the record format, not a property of the recorded run: the bench
# board plainly had live rails while it was logging.
#
# Substituted values are HEALTHY NOMINALS, not measurements, and are only ever
# used for a field the record does not contain:
#   V_fc    12.9 V — the FuelCellSource fit's ~13 V-class open-circuit terminal
#                    (hil_electrical.py FC model; the `steady` scenario settles
#                    at 12.9156 V, HIL_FINDINGS "steady").
#   V_batt   7.9 V — 2S pack mid-charge, matching V_BT_OPEN 8.0 V / the `steady`
#                    scenario's 7.840 V.
#   V_chg    0.0 V — NOT substituted: an unpowered charger input is the honest
#                    value (no charger path is open on a bench 'V'/'T' run), and
#                    it is what the modern records themselves carry.
#   V_rgn        — DERIVED, not constant: V_rgn's divider sits on V-MOT, which
#                    follows the bus whenever MOT_PWR is closed (fw v22 topology
#                    fix, schematic sheet 4).  So an absent V_rgn is replayed as
#                    the injected V_bus while the board's own observation frame
#                    shows MOT_PWR closed, and 0 V otherwise.  APPROXIMATION: it
#                    ignores the ~35 mV RT1987 forward drop and the motor node's
#                    own RC, neither of which any check here resolves.
REPLAY_NOMINAL_V_FC = 12.9      # V
REPLAY_NOMINAL_V_BATT = 7.9     # V

# ── Synthetic bring-up preamble ─────────────────────────────────────────────
# fw v22+ runs a CLOSED-LOOP staged bring-up (P0-P3) at the start of every HIL
# run, and it needs healthy rails to complete.  A recorded log begins wherever
# the operator pressed record — for ML0217 that is a dark bus, and for the whole
# v1/v2 UV trio it is a run already in progress — so replaying a log RAW asks the
# bring-up machine to complete on a stimulus that was never designed to feed it.
# The preamble presents PREAMBLE_S seconds of healthy nominal rails first, then
# hands over to the recorded trajectory.
#
# WHAT IT IS NOT: it does not exercise the bring-up dynamics.  The bus is
# presented already in regulation, so P0/P1/P2 pass on their minimum dwells;
# the preamble exists solely so the recorded trajectory is delivered to a board
# sitting in Idle rather than to one stuck in State 0 or latched in State 99.
# The `bringup` SCENARIO is where bring-up dynamics are actually tested.
#
# LENGTH: 2.5 s, chosen against two bounds, not for round numbers —
#   * >= WARM_RESET_GRACE_S (2.0 s): the suite excludes faults observed before
#     the grace bound (they are the previous run's inherited settle latch), so a
#     shorter preamble would put the first 0.5 s of every RECORDED trajectory
#     inside the excluded window and silently drop real early stimulus.
#   * >= the measured warm-reset recovery + bring-up: recovery at ~0.50 s
#     (HIL_RECOVER_DEBOUNCE_MS) plus ~0.12 s of staged bring-up = ~0.62 s
#     (HIL_FINDINGS "comm-loss"/"bringup"), so 2.5 s carries ~4x margin.
# EVERY replay timestamp is shifted by this: sim time t corresponds to log time
# t - REPLAY_PREAMBLE_S, and `replay_rec` is -1 for every preamble row.
# PER-ENTRY OPT-OUT (`--replay-no-preamble`, H2): an entry whose POINT is that
# bring-up FAILS must replay RAW.  With the preamble the board completes bring-up on
# the synthetic rails and then reacts to the recorded trajectory as a RUNNING board,
# so a cold-boot-into-darkness fault (FAULT_INIT_FAIL, reachable only from State 0's
# bring-up machine, .ino:8762-8765) becomes unreachable and the log instead latches
# whatever the Run-state fault set catches first.  With the flag the timestamps are
# UNSHIFTED — log time == sim time — and every consumer must use the same per-entry
# bound (hil_replay_suite.py resolves it with entry_preamble_s()).
REPLAY_PREAMBLE_S = 2.5
REPLAY_PREAMBLE_REC = -1        # `replay_rec` sentinel: no source record
REPLAY_PREAMBLE_V_BUS = 15.95   # V — V_BUS_DROOP_V0, the measured no-load bus
REPLAY_PREAMBLE_I = 0.05        # A — token per-channel current, well under every
                                #     OC limit; the preamble asserts nothing about
                                #     current sharing.


def replay_preamble_sensors(t, mot_pwr_closed):
    """Healthy-rail sensor dict for a preamble tick (see REPLAY_PREAMBLE_S).

    Shaped exactly like Plant.step()'s return value so the transmit path does not
    care which source produced it."""
    return {
        "V_fc": REPLAY_NOMINAL_V_FC,
        "V_batt": REPLAY_NOMINAL_V_BATT,
        "V_bus": REPLAY_PREAMBLE_V_BUS,
        "V_chg": 0.0,
        "V_rgn": REPLAY_PREAMBLE_V_BUS if mot_pwr_closed else 0.0,
        "I_fc": REPLAY_PREAMBLE_I,
        "I_batt": REPLAY_PREAMBLE_I,
        "v_actual": 0.0,
        "I_charge": REPLAY_I_CHARGE,
        "ag105_status": REPLAY_AG105_STATUS,
        # --replay-commands: the preamble carries the SAFE/standstill command, so
        # a preamble tick can never KeyError on the commander update below.  The
        # values are only read when --replay-commands is given.
        "cmd_v_sp": REPLAY_CMD_DEFAULT["cmd_v_sp"],
        "cmd_share_sp": REPLAY_CMD_DEFAULT["cmd_share_sp"],
    }

# t_us in a BLG is micros() at sample time and wraps every ~71.58 min; the
# decoder already rejects records whose forward modular step is implausible, so
# a modular difference is the correct way to rebuild a monotonic time axis.
_U32 = 1 << 32


def load_replay(path):
    """Decode a .BLG into a replay source.

    Returns (records, header, warnings, derive_v_rgn) where records is a list of
    (t_seconds_from_start, sensors_dict) with sensors_dict shaped exactly like
    Plant.step()'s return value, and `derive_v_rgn` is True when the record format
    carries no V_rgn field and the caller must derive it per tick from the injected
    V_bus and the board's own MOT_PWR bit (see the absent-rail substitution block
    above).  Absent V_fc/V_batt are substituted with healthy nominals here, once,
    because they are constants; V_rgn cannot be, because it depends on a switch
    state only the caller can see.
    """
    # Lazy import: the decoder is only needed in replay mode, and it lives
    # beside this file rather than on the default path.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from decode_benchlog import decode_blg
    except ImportError as exc:
        raise SystemExit(
            f"[hil] cannot import tools/decode_benchlog.py ({exc}) — replay mode "
            f"needs it to parse the .BLG.  Run from the repo, or put tools/ on "
            f"PYTHONPATH.")

    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise SystemExit(f"[hil] cannot read {path}: {exc}")

    try:
        result = decode_blg(data)
    except ValueError as exc:
        raise SystemExit(f"[hil] {path} is not a decodable .BLG: {exc}")

    # R-LOW-3 (2026-09-01): stamp the SOURCE FILE's digest into the header the
    # caller records in the run sidecar.  Without it a replay artifact names its
    # source only by PATH, and a path is not evidence: a re-recorded or
    # re-generated .BLG at the same path makes every historical replay result
    # unreproducible with no symptom anywhere.  Computed over the raw bytes
    # already in hand, so it costs one hash of a file that was read regardless.
    result.header["file_sha256"] = hashlib.sha256(data).hexdigest()
    result.header["file_bytes"] = len(data)

    cols = result.csv_header.split(",")
    idx = {name: i for i, name in enumerate(cols)}
    missing = [src for src, _ in REPLAY_FIELD_MAP if src not in idx]
    # Healthy-nominal substitution for the rails a v1/v2 record simply does not
    # have.  Anything not named here still injects 0.0 when absent.
    absent_default = {"V_fc": REPLAY_NOMINAL_V_FC, "V_batt": REPLAY_NOMINAL_V_BATT}
    derive_v_rgn = "V_rgn" not in idx

    records = []
    prev_us = None
    t_us_accum = 0
    for row in result.csv_rows:
        cells = row.split(",")
        t_us = int(cells[idx["t_us"]])
        if prev_us is None:
            t_us_accum = 0
        else:
            t_us_accum += (t_us - prev_us) & (_U32 - 1)
        prev_us = t_us

        sensors = {}
        for src, dst in REPLAY_FIELD_MAP:
            if src in idx:
                cell = cells[idx[src]]
                # v_sp/v_act are blank when the record's velocity-valid flag
                # (bit1) is clear — the firmware had no trustworthy velocity,
                # so 0.0 m/s is the honest injection value.
                sensors[dst] = float(cell) if cell != "" else 0.0
            else:
                sensors[dst] = absent_default.get(dst, 0.0)
        sensors["I_charge"] = REPLAY_I_CHARGE
        sensors["ag105_status"] = REPLAY_AG105_STATUS
        # Recorded COMMANDS, carried alongside the sensors (see
        # REPLAY_CMD_FIELD_MAP).  Extra keys are inert unless --replay-commands
        # is given: pack_inject() reads its eight fields by name.
        for src, dst in REPLAY_CMD_FIELD_MAP:
            cell = cells[idx[src]] if src in idx else ""
            try:
                sensors[dst] = float(cell) if cell != "" else REPLAY_CMD_DEFAULT[dst]
            except ValueError:
                sensors[dst] = REPLAY_CMD_DEFAULT[dst]
        records.append((t_us_accum / 1e6, sensors))

    if not records:
        raise SystemExit(f"[hil] {path} decoded to zero records — nothing to replay")

    warnings = []
    if missing:
        subs = ", ".join(
            f"{m}={absent_default[m]:.2f} V" for m in missing if m in absent_default)
        rest = [m for m in missing
                if m not in absent_default and not (m == "V_rgn" and derive_v_rgn)]
        detail = []
        if subs:
            detail.append(f"substituted with healthy nominals ({subs})")
        if derive_v_rgn:
            detail.append("V_rgn DERIVED from the injected V_bus while the board's "
                          "own MOT_PWR bit is set")
        if rest:
            detail.append(f"injected as 0.0: {', '.join(rest)}")
        warnings.append(
            f"format v{result.header['version']} records carry no "
            f"{', '.join(missing)} field(s) — " + "; ".join(detail))
    warnings.extend(result.warnings)
    return records, result.header, warnings, derive_v_rgn


class ReplaySource:
    """Plays a decoded .BLG back on a wall-clock axis (zero-order hold)."""

    def __init__(self, records, speed=1.0, loop=False):
        self.records = records
        self.speed = speed
        self.loop = loop
        self.span = records[-1][0]      # log duration [s] at 1.0x
        self.i = 0
        self.laps = 0
        self.finished = False

    def sample(self, t):
        """Return (sensors, record_index) for wall-clock time t, or (None, None)
        once a non-looping log has run out."""
        if self.finished:
            return None, None
        tl = t * self.speed
        if self.span > 0:
            if tl > self.span:
                if not self.loop:
                    self.finished = True
                    return None, None
                laps = int(tl // self.span)
                if laps != self.laps:
                    self.laps = laps
                    self.i = 0          # restart the scan for the new lap
                tl -= laps * self.span
        elif tl > 0 and not self.loop:
            self.finished = True
            return None, None
        # Monotonic forward scan (zero-order hold on the most recent sample).
        while self.i + 1 < len(self.records) and self.records[self.i + 1][0] <= tl:
            self.i += 1
        return self.records[self.i][1], self.i


# ═════════════════════════════════════════════════════════════════════════════
# Pi COMMAND PACKET — the firmware's 22-byte command datagram
#
# Layout VERIFIED from teensy_controller/teensy_controller.ino
# processPiCommandPacket(), lines 4806-4852 (and SYNC_BYTE_RX at line 2528).
# Nothing here is guessed; the body of that function is byte-frozen because the Pi
# bridge parses fixed offsets.
#
#    0   u8    sync   SYNC_BYTE_RX = 0xBB                     (.ino:2528, :4810)
#    1   u32   timestamp                                      (.ino:4825-4826)
#    5   u16   pkt_counter_Pi                                 (.ino:4828-4829)
#    7   f32   v_setpoint            constrained +/-20 m/s    (.ino:4842, :4846)
#   11   f32   power_share_setpoint  constrained [0,1]        (.ino:4843, :4847)
#   15   f32   charge_goal                                    (.ino:4844, :4848)
#   19   u8    mode_cmd   0=HYBRID 1=FC_ONLY 2=BATT 3=CHARGE 4=SAFE  (.ino:4850,:4857)
#   20   u8    droop_enable — RESERVED, parsed and discarded  (.ino:4851-4852)
#   21   u8    XOR checksum over bytes 1..20                  (.ino:4812-4814)
#
# The firmware's receiveCommands() drains BOTH frame types off the same socket
# (fw v21 bounded drain loop), so these go to the same address/port as the
# injection frames.
# ═════════════════════════════════════════════════════════════════════════════
SYNC_BYTE_RX = 0xBB
PI_CMD_SIZE = 22

MODE_HYBRID, MODE_FC_ONLY, MODE_BATT, MODE_CHARGE, MODE_SAFE = 0, 1, 2, 3, 4


def pack_pi_command(timestamp_ms, counter, v_setpoint, power_share_setpoint,
                    charge_goal, mode_cmd, droop_enable=0) -> bytes:
    body = struct.pack("<IHfffBB", timestamp_ms & 0xFFFFFFFF, counter & 0xFFFF,
                       v_setpoint, power_share_setpoint, charge_goal,
                       mode_cmd & 0xFF, droop_enable & 0xFF)
    return bytes([SYNC_BYTE_RX]) + body + bytes([xor_checksum(body)])


# F10: the four fields an EMS policy may set — see PiCommander.tick(). Deliberately
# narrower than PiCommander.state's key set, which also carries droop_enable (the
# reserved/discarded byte, .ino:4880-4881).
POLICY_ALLOWED_FIELDS = frozenset(
    {"v_setpoint", "power_share_setpoint", "charge_goal", "mode_cmd"})


class PiCommander:
    """Plays a scenario's pi-command timeline onto the same socket as the injection
    frames, at a fixed rate.

    A timeline is a list of (t_seconds, fields) applied in order; `fields` may set
    any of v_setpoint / power_share_setpoint / charge_goal / mode_cmd /
    droop_enable, and unspecified fields HOLD their previous value — matching the
    firmware, which also holds a field it rejects (comment .ino:4869,
    code .ino:4874-4876).

    Rate: PI_CMD_HZ.  The firmware's Pi watchdog wants regular traffic, and a
    command packet is what marks the link alive (`last_rx_ms`, .ino:4854), so the
    commander keeps sending the held state even between timeline entries.
    """

    PI_CMD_HZ = 50.0

    def __init__(self, timeline, rate_hz=PI_CMD_HZ, policy=None, policy_name=None,
                 always_active=False, mute_after=None):
        self.timeline = sorted(timeline or [], key=lambda e: e[0])
        self.period = 1.0 / rate_hz
        self.next_tx = 0.0
        self.idx = 0
        self.counter = 0
        self.sent = 0
        self.state = {"v_setpoint": 0.0, "power_share_setpoint": 0.5,
                      "charge_goal": 0.0, "mode_cmd": MODE_SAFE, "droop_enable": 0}
        self.last_applied = None
        # ── Mode A: emulated Pi EMS ──────────────────────────────────────────
        # `policy` is an EMS_STRATEGIES callable; when set it SUBSTITUTES for the
        # timeline lookup below (the two are mutually exclusive by construction —
        # main() refuses --ems on a scenario whose timeline it would silently
        # replace without saying so).  Cadence, held-field semantics, packet
        # format and the watchdog-keepalive role are all unchanged: the policy
        # only decides WHAT the held state is, never WHEN a packet goes out.
        self.policy = policy
        self.policy_name = policy_name
        self.policy_calls = 0
        self.last_fb = None
        # ── --replay-commands: externally-driven state ───────────────────────
        # A third command source exists in replay mode: neither a timeline nor a
        # policy, but the RECORDED v_sp/share_sp of the log being replayed, which
        # the caller writes straight into `self.state` before each tick.  Such a
        # commander has an EMPTY timeline and NO policy, so active() would be
        # False and tick() would never transmit.  `always_active` is the explicit
        # opt-in for that case; it changes nothing else (cadence, packet, counters
        # and held-field semantics are identical) and defaults False, so every
        # existing construction behaves byte-for-byte as before.
        self.always_active = bool(always_active)
        # ── `pi-silence`: stop commanding at a scripted time ─────────────────
        # WHY THIS EXISTS.  The firmware's Pi watchdog (checkPiWatchdog,
        # .ino:4976-4985, called unconditionally from loop() at :4381) stamps
        # `last_rx_ms` ONLY in the 22-byte command branch (:5043-5044).  It is
        # therefore fully INDEPENDENT of the injection stream's own staleness
        # clock (`hilLastFrameMs`, :5132) — and until now nothing in this suite
        # could exercise it, because apply_scenario()'s `tx_enabled` gates BOTH
        # streams together (:4172 injection, :4192 commands) and `comm-loss`
        # kills both at once.  Muting the COMMANDER alone, with injection
        # continuing at full rate, is the only stimulus that isolates it.
        #
        # None (the default) means "never mute", so every existing construction
        # is byte-identical.  A muted tick returns None WITHOUT advancing
        # `next_tx`, `counter` or `sent` — the commander goes silent, it does not
        # accumulate a backlog to burst out later.
        self.mute_after = None if mute_after is None else float(mute_after)

    def muted(self, t):
        """True once this commander has gone permanently silent (`mute_after`)."""
        return self.mute_after is not None and t >= self.mute_after

    def active(self):
        """True if this commander will ever transmit (timeline, EMS policy, or an
        externally-driven state — see `always_active`)."""
        return (self.always_active or bool(self.timeline)
                or self.policy is not None)

    def tick(self, t, fb_factory=None):
        """Return a packet to send at time t, or None.

        `fb_factory` is a zero-argument callable returning the feedback view dict
        for an EMS policy.  It is invoked ONLY on a due commander tick (50 Hz), not
        on every 1 kHz sim tick — assembling the view is the caller's cost and there
        is no reason to pay it 20x over."""
        if self.muted(t):
            # `pi-silence`: the emulated Pi has stopped.  Return BEFORE the
            # timeline walk and before any counter moves — a dead Pi neither
            # advances its own script nor queues packets.  `self.state` freezes
            # at whatever it last sent, which is what the cmd_* CSV columns
            # should show ("what this process last commanded"), and `sent` stops
            # rising so the exit summary reports the real packet count.
            return None
        while self.idx < len(self.timeline) and self.timeline[self.idx][0] <= t:
            self.state.update(self.timeline[self.idx][1])
            self.last_applied = self.timeline[self.idx]
            self.idx += 1
        if not self.active() or t < self.next_tx:
            return None
        if self.policy is not None:
            fb = fb_factory() if fb_factory is not None else {"t": t}
            self.last_fb = fb
            self.policy_calls += 1
            out = self.policy(t, fb) or {}
            # UNSET FIELDS HOLD — the same contract as a timeline entry and as the
            # firmware itself (comment .ino:4869, code .ino:4874-4876 holds a
            # field it rejects).
            # F10: the documented policy-return contract is exactly the four
            # command fields a Pi actually decides. `self.state` also carries
            # `droop_enable` (the reserved/discarded byte, .ino:4880-4881) so a
            # policy CAN'T set it here — gate against the narrower allow-list,
            # not against self.state's keys, or droop_enable would silently be
            # accepted like a real field.
            for k, v in out.items():
                if k not in POLICY_ALLOWED_FIELDS:
                    raise KeyError("EMS policy returned unknown field %r "
                                   "(allowed: %s)"
                                   % (k, ", ".join(sorted(POLICY_ALLOWED_FIELDS))))
                self.state[k] = v
        self.next_tx = t + self.period
        self.counter = (self.counter + 1) & 0xFFFF
        self.sent += 1
        return pack_pi_command(
            int(t * 1000.0), self.counter, self.state["v_setpoint"],
            self.state["power_share_setpoint"], self.state["charge_goal"],
            self.state["mode_cmd"], self.state["droop_enable"])


# ═════════════════════════════════════════════════════════════════════════════
# MODE A — EMULATED PI EMS  (--ems STRATEGY)
#
# An energy-management STRATEGY sits where the real Raspberry Pi's supervisor
# would: it watches feedback and decides the four command fields the firmware
# consumes.  It is emulated on the HOST, inside this simulator, so a strategy can
# be developed and regression-run without the Pi in the loop at all.
#
#   policy(t, fb) -> dict   with any subset of
#                     {v_setpoint, power_share_setpoint, charge_goal, mode_cmd}
#   UNSET FIELDS HOLD.  Returning {} is legal and means "no change".
#   The policy is called at PiCommander.PI_CMD_HZ (50 Hz), NOT at the 1 kHz sim
#   tick, and its output is what the 50 Hz command packets carry.
#
# ── The feedback view `fb` ───────────────────────────────────────────────────
# `fb` is assembled once per commander tick.  It is deliberately RICHER than what
# a real Pi can see: the real Pi gets only the 58-byte v4 telemetry packet
# (.ino:4988-5069, PLAN.md §6b), whereas `fb` also carries PLANT TRUTH from the
# simulator's own state and fields from the 16-byte HIL observation frame, which
# no Pi ever receives.  A strategy that is meant to be portable to the real Pi
# MUST restrict itself to the telemetry-equivalent keys:
#
#   TELEMETRY-EQUIVALENT (a real Pi can compute these from the v4 packet):
#     t          — the Pi has its own clock; the packet also carries timestamp_ms
#     v_actual   (offset  7)      V_batt   (11)     I_batt  (15)
#     I_charge   (19)             V_fc     (23)     I_fc    (27)
#     V_bus      (31)             V_rgn    (35)     V_chg   (39)
#     ag105_status (51, raw Table-6 byte)  switch   (52, switch_state bitmask)
#     fault_flags  (53)
#
#   NOT TELEMETRY-EQUIVALENT — simulator/HIL-only, do NOT use in a portable policy:
#     soc        — PLANT TRUTH from BatterySource's coulomb count.  The real pack
#                  has no SoC output at all; the Pi would have to estimate it.
#     state      — mainState, from the HIL observation frame.  v4 telemetry
#                  carries only error_source_state (offset 56), i.e. the state at
#                  the time of the FIRST fault — not the live state.
#     aux        — HIL observation frame byte 4 (FC/BT_REG_ENABLE, MPPT_DISABLE,
#                  CBAL_DISABLE).  Not in v4 telemetry.
#     current    — post-clamp motor-current command, HIL observation frame.  Not
#                  in v4 telemetry.
#     v_profile  — this scenario's own scripted speed profile (see below).
#     obs_age_s  — F11: seconds since the last DECODED observation frame (None
#                  if none has ever arrived).  Observation-frame-derived keys
#                  above (state/switch/aux/current/fault_flags) are NOT
#                  themselves bounded by freshness — obs is not cleared on a
#                  stall — so a policy reading any of them should check
#                  obs_age_s and treat those keys as stale once it exceeds
#                  roughly HIL_ZERO_MS/1000 (0.25 s).  See manual Sec 3.3.
#
# Note also that v4 telemetry carries power_share_actual (offset 43) and the two
# droop-gain words (47/49), which `fb` does NOT expose — the observation frame
# does not carry them.  A portable policy must not depend on them either.
#
# F10: the policy RETURN contract is narrower than `fb` itself — a policy may
# only set the four documented command fields (v_setpoint, power_share_setpoint,
# charge_goal, mode_cmd; see POLICY_ALLOWED_FIELDS, defined just above
# PiCommander). It may
# NOT set droop_enable even though PiCommander.state carries that key
# internally — droop_enable is the reserved/discarded byte (.ino:4880-4881),
# not a real policy decision, and returning it now raises like any other
# unknown key.
#
# ── ⚠️ SHARE AUTHORITY DISAPPEARS BELOW 0.55 A (2026-09-01) ──────────────────
# READ THIS BEFORE WRITING A POLICY THAT COMMANDS AN FC-HEAVY OR BT-HEAVY SPLIT
# AT LOW LOAD, AND BEFORE WALKING ONE OFFLINE.
#
# The firmware's share loop is GATED ON SOURCE CURRENT.  It enters closed loop
# above 2 * SHARE_MINORITY_I_MIN_A = 0.60 A of source total and drops out below
# 0.60 - SHARE_GOV_OL_HYST_A = 0.55 A (.ino:2181/2205, gate at :9933).  In
# OPEN-LOOP mode the firmware does not write the MDACs at all: it HOLDS the last
# split the closed loop converged to (.ino:9937 onward, `droopSlew_prev`).  So
# below 0.55 A of total source current:
#
#     power_share_setpoint is ACCEPTED, LOGGED, and NOT ACTED ON.
#
# The command still appears on the wire and in `cmd_share_sp`; the DELIVERED
# split is whatever was standing when the load fell away.  This is DESIGNED
# behaviour — re-commanding a split during a coast-down slams the droop gains,
# which is the transient the whole open-loop family exists to remove — and it is
# not a defect to be worked around.
#
# WHAT IT MEANS FOR A POLICY: at low cruise your share decision does not change
# the pack's drain rate, so any policy whose regulation depends on share
# authority (an SoC band, an SDP table indexed on SoC) is running open loop in
# exactly the regime it thinks it is acting in.  Size the scenario's load — see
# `aux_preload_a` — if the policy needs authority, or accept the hold and say so.
#
# WHAT IT MEANS FOR A WALK: model the hold.  TWO offline walks in this codebase
# have now been wrong for this one reason, the second badly:
#   * campaign 20260901_024231, `ems-sdp-cross`: the walk applied the CLOSED-LOOP
#     minority governor at a 1.0 m/s cruise drawing I_tot ~ 0.355 A. The board
#     delivered share 0.1656 against the commanded 0.85, so the real drain was
#     -3.90e-5 SoC/s against the walk's ~6.9e-6, and the predicted charge-window
#     period of ~52 s was measured at 16.13 s — wrong by 5.7x. The suite check
#     built on that period asserted the ABSENCE of a window at a modelled
#     instant, and failed a CORRECT board.
#   * the `y-b00` variants: same cause, benign consequence (the note in
#     make_ems_y() records that those runs are open-loop feedforward and that
#     share AMPLITUDE must not be read off them).
# A walk that assumes the commanded split is the delivered one is measuring a
# firmware that does not exist. Compute I_tot at each step, compare it against
# the 0.55 A drop-out, and hold the split below it.
# ═════════════════════════════════════════════════════════════════════════════

# Promoted from the comment table above to a named, importable constant (test-
# writer recommendation, adjudicated ACCEPT) — the TELEMETRY-EQUIVALENT key set
# a portable EMS policy may depend on. `obs_age_s` (F11) is deliberately NOT a
# member: it is derived from the HIL observation frame, which a real Pi never
# receives, same as `state`/`aux`/`current` above.
FB_TELEMETRY_EQUIV_KEYS = frozenset({
    "t", "v_actual", "V_batt", "I_batt", "I_charge", "V_fc", "I_fc",
    "V_bus", "V_rgn", "V_chg", "ag105_status", "switch", "fault_flags",
})


def piecewise(profile, t):
    """Linear interpolation of a [(t, value), ...] profile, clamped at both ends."""
    if not profile:
        return None
    if t <= profile[0][0]:
        return float(profile[0][1])
    for (t0, v0), (t1, v1) in zip(profile, profile[1:]):
        if t <= t1:
            span = t1 - t0
            if span <= 0:
                return float(v1)
            return float(v0) + (float(v1) - float(v0)) * (t - t0) / span
    return float(profile[-1][1])


# Fallback cruise speed for a strategy asked to run on a scenario with no speed
# profile of its own.  Provenance: the `charge-cruise` scenario's own pi_timeline
# uses v_setpoint = 1.2 m/s as its "moderate cruise" (see SCENARIOS below) — the
# same number is reused here rather than inventing a second one.
EMS_DEFAULT_CRUISE_MPS = 1.2

# Time at which a strategy hands the firmware MODE_HYBRID (Idle -> Run, .ino:4858).
# Matches every existing pi_timeline in SCENARIOS, which all step to Run at 3.0 s
# after a MODE_SAFE settle — long enough for the staged bring-up to finish.
EMS_RUN_ENTRY_S = 3.0


# ── Per-scenario Run-exit override (2026-08-31) ─────────────────────────────
# Every strategy below carries its OWN Run-exit constant, derived against the
# ONE scenario it was written for (EMS_RUN_EXIT_S 55.0 against ems-drive-cycle,
# EMS_REGEN_RUN_EXIT_S 43.0 against charge-regen, SOC_BAND_RUN_EXIT_S 58.0
# against ems-soc-band).  That is fine while a strategy has one scenario and
# fatal the moment it has two: `hold-5050` on a 350 s FTP-75 cycle would hand
# back MODE_SAFE at t = 55 and spend the remaining 295 s parked in Idle,
# commanding a drive cycle nobody is driving.
#
# A scenario may therefore declare `ems_run_exit_s`, which reaches the policy
# through fb["ems_run_exit_s"].  A scenario that declares nothing puts None on
# the key and every strategy falls back to its own constant, so EVERY EXISTING
# SCENARIO IS BYTE-IDENTICAL — the override is opt-in per scenario, not a
# reinterpretation of the constants.
#
# It is deliberately NOT in FB_TELEMETRY_EQUIV_KEYS: like `v_profile`, it is a
# HOST-SIDE SCRIPT parameter and not feedback at all.  A real Pi decides its own
# mission length; it does not read one off a packet.
def ems_run_exit(fb, default):
    """The Run-exit time this policy should use: the scenario's override if it
    declared one, else the strategy's own constant.

    Explicit None test, not `or`: a scenario declaring 0.0 (a degenerate but
    legal "never enter Run") must not silently fall back to 55 s."""
    val = fb.get("ems_run_exit_s")
    return float(default) if val is None else float(val)


# F14(b): the time ems_hold_5050 hands the firmware back MODE_SAFE, closing the
# drive cycle out (Run -> Finish -> Idle) instead of ending the run parked in
# State 2. Chosen against ems-drive-cycle's own ems_v_profile, which reaches
# standstill (v_setpoint 0) at t=52.0 and holds it (piecewise() clamps past the
# profile's last point) — 55.0 gives 3 s of standstill margin before commanding
# MODE_SAFE, and still leaves 3 s inside the 58 s duration (trimmed from 60 s,
# 2026-08-30) for Finish -> Idle to actually complete.
EMS_RUN_EXIT_S = 55.0


def ems_hold_5050(t, fb):
    """hold-5050 — constant 50/50 power split.

    name       : hold-5050
    intent     : the trivial reference strategy and the TEMPLATE for real ones.
                 It makes no decisions: the split is pinned at 0.50 so any
                 observed share deviation belongs to the firmware's share loop
                 and the plant, never to the EMS.
    fields     : mode_cmd (SAFE -> HYBRID at EMS_RUN_ENTRY_S, back to SAFE at
                 EMS_RUN_EXIT_S so a drive cycle genuinely finishes
                 Run -> Finish -> Idle instead of ending parked in State 2 —
                 F14(b)),
                 power_share_setpoint (0.50 constant),
                 v_setpoint (the scenario's `ems_v_profile` if it defines one,
                 else EMS_DEFAULT_CRUISE_MPS),
                 charge_goal (0.0 — charging deliberately out of scope here).
    feedback   : uses NOTHING but `fb["t"]` and `fb["v_profile"]`.  It is therefore
                 trivially portable to the real Pi (see the telemetry-equivalence
                 list above).
    provenance : cruise value from the `charge-cruise` pi_timeline; Run-entry time
                 from the same timelines; 0.50 is the firmware's own default
                 power_share_setpoint; Run-exit time from ems-drive-cycle's own
                 ems_v_profile standstill segment (see EMS_RUN_EXIT_S).
    """
    v_sp = fb.get("v_profile")
    if v_sp is None:
        v_sp = EMS_DEFAULT_CRUISE_MPS
    in_run = EMS_RUN_ENTRY_S <= t < ems_run_exit(fb, EMS_RUN_EXIT_S)
    return {
        "mode_cmd": MODE_HYBRID if in_run else MODE_SAFE,
        "power_share_setpoint": 0.50,
        "v_setpoint": v_sp,
        "charge_goal": 0.0,
    }


# ── regen-harvest: braking windows ──────────────────────────────────────────
# (t_start, t_end) in seconds, matching the DESCENDING segments of the
# `charge-regen` scenario's ems_v_profile.  charge_goal is asserted INSIDE these
# windows only; see ems_regen_harvest() for why the edges are inset.
EMS_REGEN_BRAKE_WINDOWS = ((14.0, 16.1), (26.0, 28.1), (37.0, 39.1))
# Assert charge_goal this long AFTER a braking window opens.  The firmware's
# chargingControl() (.ino:10026) picks its branch on the COMMANDED motor current:
# `regenActive = (current < -0.1f)`.  At the instant a ramp starts, `current` is
# still the positive cruise hold, so charge_goal > 0 there would take the CRUISE
# branch and call assertFcChargeEnable(true) — opening the FC->charger path and
# dropping BT off the bus, the exact single-source condition that made the old
# charge-regen latch OC_FC.  200 ms is ~3 crossover periods at the fw v18 design
# crossover (17.25 rad/s), by which point the ramp has driven the command
# negative; measured cruise->brake command reversal is far faster than that.
EMS_REGEN_CHARGE_LEAD_IN_S = 0.20
# Release charge_goal this long BEFORE a braking window closes, so the command
# is still negative when charging stops — the symmetric guard against a cruise
# branch with charge_goal still high on the way back up.
EMS_REGEN_CHARGE_LEAD_OUT_S = 0.10
# Hand the firmware back MODE_SAFE here, so the run closes out Run -> Finish -> Idle
# instead of ending parked in State 2 (the same F14(b) fix ems_hold_5050 carries).
# Chosen against charge-regen's own ems_v_profile, which reaches standstill at
# t = 43.0 and holds it to the 45 s duration: 43.0 leaves 2 s inside the run for
# Finish -> Idle to complete.
EMS_REGEN_RUN_EXIT_S = 43.0


# ═════════════════════════════════════════════════════════════════════════════
# THE REGEN MANAGER (2026-09-02, the ftp75c round)
#
# WHAT IT IS.  A COMMON LAYER over every EMS strategy's returned command, not
# per-strategy logic.  Inside a commanded regen window it forces
# `charge_goal = 1.0` and leaves every other field exactly as the strategy
# returned it; outside every window it does nothing at all.
#
# WHY IT IS COMMON, and this is the design decision rather than a convenience:
#   * Regen admission is a function of the STIMULUS, not of the energy-
#     management decision.  Every strategy brakes at the same instants, because
#     every strategy follows the same `ems_v_profile`.
#   * Making it common makes regeneration STRATEGY-INDEPENDENT, which is what
#     lets a frontier comparison on `ftp75c` remain a comparison of share
#     policies rather than a comparison of which strategy remembered to close a
#     switch.
#   * Duplicating the lead-in / lead-out reasoning across six strategies is
#     exactly the failure `assertFcChargeEnable()`'s history warns about.
#
# WHAT THE FIRMWARE DOES WITH IT.  `chargingControl()` (.ino:10771-10893) takes
# its REGEN branch when `charge_goal > 0.05` AND `regenActive`, where
# `regenActive = (current < -0.1f)` reads the COMMANDED motor current.  That
# branch drives `assertFcChargeEnable(false)`, `REGEN_ENABLE` HIGH and
# `MPPT_DISABLE` LOW, and leaves BT on the bus; `MOT_PWR_ENABLE` is already
# closed throughout Run.  So the host commands ONE field and the firmware opens
# the path - the manager must not, and does not, try to sequence switches.
#
# THE MUTUAL EXCLUSION IS THE FIRMWARE'S.  `assertFcChargeEnable()` drives
# BT_BUS LOW, then REGEN LOW, waits 100 us, then raises FC_CHARGE, and
# `detectFaults()` latches FAULT_SWITCH_CONFLICT on the illegal combination.
# The host cannot make the board charge from both paths at once and does not
# need to enforce that invariant.  What it MUST avoid is provoking the WRONG
# BRANCH: asserting `charge_goal > 0` one tick before the commanded current has
# gone negative takes the CRUISE branch, which calls
# `assertFcChargeEnable(true)`, drops BT off the bus and creates the
# single-source condition that previously latched OC_FC
# (hil_plant_sim.py's own ems_regen_harvest() note).  That is what the lead-in
# below exists for.
#
# THE DWELL.  `SDP_CHG_MIN_DWELL_S` is a HOST construct governing the FC-path
# charge windows.  A regen window overlapping a latched FC window does not
# violate it - the firmware silently moves from the cruise branch to the regen
# branch and back - but the strategies' own charge bookkeeping must NOT count
# regen-window ticks as FC charge ticks, or the dwell accounting and the
# `chg_holds` census are both wrong.  The manager therefore sets
# `regen_commanded` on the FEEDBACK VIEW, before the strategy is called, and the
# charge bookkeeping excludes it.
# ═════════════════════════════════════════════════════════════════════════════

# Lead-in: identical to EMS_REGEN_CHARGE_LEAD_IN_S and for its reason exactly.
EMS_REGEN_MGR_LEAD_IN_S = 0.20
# Lead-out: LENGTHENED from ems_regen_harvest()'s 0.10 s.  A compressed drive
# cycle's decelerations end in immediate re-acceleration far more often than the
# hand-built regen scenarios do, and a late release would take the cruise branch
# with a still-negative bus.
EMS_REGEN_MGR_LEAD_OUT_S = 0.20
# Windows shorter than this AFTER trimming are dropped: below roughly half a
# second nothing reaches the pack anyway (AG105_SETTLE_S 0.5 s plus the
# AG105_TAU_S 0.4 s ramp cost ~0.9 s at the head of every window), and a
# sub-tick window is a switch transient rather than a harvest.
EMS_REGEN_MGR_MIN_WINDOW_S = 0.50
# -- THE FIRMWARE'S OWN REGEN THRESHOLD, MIRRORED (H1, 2026-09-02) -----------
# `chargingControl()` does NOT branch on "is the required force negative".  It
# branches on the COMMANDED MOTOR CURRENT against a literal:
#     bool regenActive = (current < -0.1f);        // .ino:10807
# so a stage whose required current sits in (-0.1, 0) A is BRAKING IN PHYSICS
# AND NOT-REGEN IN FIRMWARE.  Commanding `charge_goal` there takes the CRUISE
# branch, which calls `assertFcChargeEnable(true)`, drops BT off the bus and
# creates the single-source FC condition that has latched OC_FC before - and
# `FAULT_SWITCH_CONFLICT` does NOT catch it, because FC_CHARGE with BT open is
# a LEGAL combination.
#
# TRIMMING ON `force < 0` WAS THE DEFECT.  Measured on `ftp75c` under
# `scaled-air`: SEVEN of the nine windows the force rule produced contained
# 2.900 s in total where the required current was inside that dead band, and
# window 4 (57.200-57.800 s) was inside it for 100 % OF ITS LENGTH.
#
# THE MARGIN IS 2x AND IT IS DELIBERATE.  The host commands a v_setpoint; the
# CURRENT the firmware's drive controller then develops is not the host's to
# know exactly, so trimming AT the firmware's own threshold would put the
# window edge on the decision boundary.  2x puts the worst in-window required
# current at -0.2045 A, i.e. 2.05x the threshold.
REGEN_ACTIVE_I_A = 0.1          # A, the firmware's literal (.ino:10807)
EMS_REGEN_MGR_I_MARGIN = 2.0    # x, host-side margin on it


def derive_regen_windows(profile, drag_mode=None,
                         lead_in_s=EMS_REGEN_MGR_LEAD_IN_S,
                         lead_out_s=EMS_REGEN_MGR_LEAD_OUT_S,
                         min_window_s=EMS_REGEN_MGR_MIN_WINDOW_S,
                         i_active_a=REGEN_ACTIVE_I_A,
                         i_margin=EMS_REGEN_MGR_I_MARGIN):
    """Regen-capable windows of a piecewise-linear speed profile.

    DERIVED, NEVER HAND-TABULATED.  `EMS_REGEN_BRAKE_WINDOWS` and
    `EMS_REGENTRUE_BRAKE_WINDOWS` are hand-built tables for two hand-built
    stimuli; a 234-point drive cycle cannot be treated that way, and a table
    typed once would silently stop matching the profile the next time either
    moved.

    THE RULE IS THE FIRMWARE'S, NOT THE PHYSICS'.  An instant is admitted when
    the REQUIRED MOTOR CURRENT is at or below `-i_margin * i_active_a`, i.e.
    when the required force is at or below `-i_margin * i_active_a * K_F`.
    `chargingControl()` branches on `regenActive = (current < -0.1f)`
    (.ino:10807), so "the force is negative" and "the firmware calls this
    regen" are DIFFERENT STATEMENTS, and the gap between them is a hazard
    rather than a rounding detail - see the REGEN_ACTIVE_I_A block above.

    Within one segment of a piecewise-linear profile `a` is CONSTANT and `v` is
    affine and monotone, and `F_road` is monotone in `v` on the forward
    half-line (`k_air*v^2` and `F_c + b_eff*v` both are), so the force is
    MONOTONE IN TIME inside a segment and crosses ANY level at most once.  That
    crossing is located by bisection, which is exact to float precision and does
    not have to know which road-load law is in force.

    ⚠️ AN ENDPOINT TEST ALONE IS NOT ENOUGH, and this is a safety property
    rather than a refinement.  The design note's rule ("negative at either
    endpoint") ADMITS a segment that crosses the level inside it, and a window
    built on the whole segment then commands `charge_goal = 1.0` over an
    interval the firmware does not consider regen at all.  Measured on
    `ftp75c`: the whole-segment rule opened an FC charge window at t = 53.6 s.
    The sub-interval is therefore trimmed to the crossing, so EVERY instant of
    EVERY commanded window satisfies the firmware's own test with the margin.

    Regen-capable sub-intervals that meet at a segment boundary are merged, the
    lead times trim the merged interval, and anything shorter than
    `min_window_s` after trimming is dropped.  Returns a tuple of
    (t_start, t_end) pairs in profile time."""
    k_air = drag_k_air(DRAG_MODE_DEFAULT if drag_mode is None else drag_mode)

    def f_road(v):
        if k_air:
            return k_air * v * abs(v)
        f_c = F_COULOMB if v > V_STICTION else (
            -F_COULOMB if v < -V_STICTION else 0.0)
        return f_c + B_EFF * v

    # THE ADMISSION LEVEL, as a FORCE.  `force = K_F * i_cmd`, so the
    # firmware's current test maps onto a force test by one multiply, and the
    # margin is applied to the current because that is the quantity the
    # firmware compares.
    f_level = -float(i_margin) * float(i_active_a) * K_F

    def force_at(t0, v0, a, t):
        return M_EFF * a + f_road(v0 + a * (t - t0))

    def cross(t0, v0, a, t_in, t_out):
        """The time between `t_in` (force < f_level) and `t_out` (force >=
        f_level) at which the force reaches `f_level`.  60 bisections is
        float-exact over any interval this profile contains."""
        lo, hi = t_in, t_out
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if force_at(t0, v0, a, mid) < f_level:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    merged = []
    for (t0, v0), (t1, v1) in zip(profile, profile[1:]):
        if t1 <= t0:
            continue
        a = (v1 - v0) / (t1 - t0)
        f0 = force_at(t0, v0, a, t0)
        f1 = force_at(t0, v0, a, t1)
        if f0 >= f_level and f1 >= f_level:
            continue
        ta = t0 if f0 < f_level else cross(t0, v0, a, t1, t0)
        tb = t1 if f1 < f_level else cross(t0, v0, a, t0, t1)
        if tb <= ta:
            continue
        if merged and abs(merged[-1][1] - ta) <= 1e-9:
            merged[-1] = (merged[-1][0], tb)
        else:
            merged.append((ta, tb))
    out = []
    for t0, t1 in merged:
        w0, w1 = t0 + lead_in_s, t1 - lead_out_s
        if (w1 - w0) >= min_window_s:
            out.append((w0, w1))
    return tuple(out)


class RegenManager:
    """The common regen-command layer.  See the block comment above.

    Constructed by `main()` (and by `ems_walk`) for a scenario that declares
    `ems_regen_manager`, and applied by WRAPPING the strategy callable rather
    than by editing each strategy: the wrapper is the same layer that already
    validates POLICY_ALLOWED_FIELDS, it cannot be forgotten by a strategy added
    later, and a strategy under walk and the same strategy under the simulator
    are wrapped identically."""

    def __init__(self, windows, i_active_a=REGEN_ACTIVE_I_A,
                 i_margin=EMS_REGEN_MGR_I_MARGIN):
        self.windows = tuple((float(a), float(b)) for a, b in windows)
        # TWO LEVELS, NOT ONE.  `i_arm_a` is the level the windows were derived
        # at (`i_margin` x the firmware threshold); `i_release_a` is the
        # firmware's OWN `regenActive` exit.  The gap between them is the
        # hysteresis band.  See `_update()`.
        self.i_arm_a = -float(i_margin) * float(i_active_a)
        self.i_release_a = -float(i_active_a)
        # Observability, consumed by the run banner and the sidecar.  Counted
        # rather than derived so a window list and the ticks actually spent
        # inside it can be compared after the fact.
        self.calls = 0
        self.forced = 0
        # Trailing-edge bookkeeping, also observability: how many windows ended
        # on the CURRENT rule rather than on the wall clock.
        self.early_releases = 0
        # Per-window latch state: the index of the window the manager is in,
        # whether the firmware has been SEEN braking inside it, and whether it
        # has been released for the remainder of it.
        self._win_idx = None
        self._entered_braking = False
        self._released = False

    def duty_s(self):
        return sum(b - a for a, b in self.windows)

    def active(self, t):
        """Wall-clock window membership.  PURE, and deliberately NOT the
        command decision — see `_update()` for the trailing-edge rule."""
        return any(a <= t < b for a, b in self.windows)

    def window_index(self, t):
        """Index of the window containing `t`, or None.  PURE."""
        for i, (a, b) in enumerate(self.windows):
            if a <= t < b:
                return i
        return None

    # ── THE TRAILING EDGE (ruling D-4, 2026-09-03) ──────────────────────────
    # The manager used to command `charge_goal = 1.0` to a window's WALL-CLOCK
    # END.  Campaign 20260902_220604 measured what that costs on `ftp75c`: on
    # windows 3 and 6 the vehicle reaches standstill BEFORE the window ends, the
    # firmware's commanded motor current leaves the braking region (measured
    # -12.0 -> 0.0 A at t = 67.2051 s, window end 67.217 s), `regenActive` goes
    # FALSE while the host is still asserting charge intent, and
    # `chargingControl()` falls through to its CRUISE branch — which calls
    # `assertFcChargeEnable(true)`, drops BT off the bus and carries the whole
    # load single-source on the FC.  Measured handoffs: 0.08-0.10 s at 67.22 s
    # and 0.26-0.28 s at 171.04-171.06 s on EVERY leg, peak `I_fc` 0.37-0.38 A.
    # That is the recorded OC_FC topology, reached here at 27 % of
    # LIMIT_I_FC_MAX only because the compensated cycle is light.
    #
    # THE RULE IS A TWO-LEVEL COMPARATOR, NOT A SYMMETRIC ONE.  The window
    # OPENS on the required motor current entering the braking region at
    # `EMS_REGEN_MGR_I_MARGIN` x `REGEN_ACTIVE_I_A` = -0.2 A (that is what
    # `derive_regen_windows()` trims to, and the LEADING-EDGE TRIM IS
    # UNCHANGED), and it RELEASES on the commanded motor current reaching
    # `-REGEN_ACTIVE_I_A` = -0.1 A, THE FIRMWARE'S OWN `regenActive` EXIT
    # (.ino:10807), whichever comes first with the wall clock.
    #
    # ⚠️ A SINGLE LEVEL WAS A ZERO-HYSTERESIS COMPARATOR AND THAT WAS A DEFECT
    # (review of the 2026-09-03 round, finding H1).  Arming and releasing at the
    # SAME -0.2 A means any sample that grazes the level closes the window, and
    # because the release is LATCHED the window is then closed for good.  On
    # campaign 20260902_220604's `ems-ftp75c-5050` trace that fired on window 1
    # at t = 23.3854 s (`current` = -0.1999 A while the vehicle was still 200 ms
    # from a -1.55 A brake) and on window 6 at t = 167.1162 s (-0.1997 A, with
    # 3.94 s of -0.65...-8.09 A braking still to come).  `regen_commanded` then
    # read False THROUGH heavy braking, which is exactly the guard the three
    # consumers of that flag rely on to refuse an FC-charge dwell inside a
    # braking window - the hazard ruling D-4 exists to close.
    #
    # THE RELEASE LEVEL STRICTLY TRAILS THE FIRMWARE'S EXIT, so the host can
    # never drop regen intent while the firmware still calls the instant regen.
    # Measured on the same trace: the two spurious releases above disappear and
    # window 5's 0.14 s-early release (benign, but not a real standstill either)
    # goes with them, while BOTH genuine standstill releases survive - window 3
    # at t = 67.2041 s and window 6 at t = 171.0441 s, i.e.
    # `regen_early_releases` reads 2 of 6.
    #
    # TWO PROPERTIES THE LATCH BUYS.  (a) The release is ARMED only after the
    # firmware has actually been seen braking inside the window, so the lead-in
    # ramp cannot release the window before it starts.  (b) The release is
    # LATCHED for the remainder of that window, so a current chattering across
    # the release level cannot re-open the path; a new window re-arms it.  With
    # one level (a) and (b) COMPOUNDED the defect rather than containing it.
    #
    # ⚠️ THE SIGNAL IS THE OBSERVATION FRAME'S COMMANDED MOTOR CURRENT
    # (`fb["current"]`), which is NOT telemetry-equivalent and is NOT produced
    # by `ems_walk`'s reduced feedback view.  When the key is absent or None the
    # manager falls back to the wall-clock end, i.e. to the previous behaviour
    # EXACTLY — so a walk is bit-identical across this change and only a live
    # run (or a test that supplies the key) sees the new trailing edge.  The
    # asymmetry is recorded rather than hidden: a walk therefore models the
    # LONGER window, and its regen duty is an upper bound on the live one.
    def _update(self, t, fb):
        """Advance the per-window latch and return the command decision.

        NOT PURE — this is the one state advance per commander tick, and
        `wrap()` calls it exactly once."""
        idx = self.window_index(t)
        if idx != self._win_idx:
            self._win_idx = idx
            self._entered_braking = False
            self._released = False
        if idx is None:
            return False
        if self._released:
            return False
        i_cmd = fb.get("current") if isinstance(fb, dict) else None
        if i_cmd is None:
            return True                      # no live signal: wall-clock end
        i_cmd = float(i_cmd)
        if not self._entered_braking:
            if i_cmd <= self.i_arm_a:
                self._entered_braking = True
            return True
        if i_cmd >= self.i_release_a:
            self._released = True
            self.early_releases += 1
            return False
        return True

    def apply(self, t, fb, out, commanded=None):
        """Rules 1-3 of the design note, in order.

        1. Inside a window, force `charge_goal = 1.0` and touch nothing else.
        2. Outside every window, leave `charge_goal` exactly as returned.
        3. A strategy's own positive `charge_goal` at the start of a window does
           NOT win: the window does.  The firmware's `regenActive` branch takes
           precedence over the cruise branch anyway, so the host's model of
           WHICH PATH IS OPEN has to match, or the dwell accounting and the
           charge census describe a run that did not happen.

        `commanded` is the decision `wrap()` already advanced the latch for.
        A direct caller that passes nothing advances the latch here instead, so
        the state moves exactly once per call either way."""
        self.calls += 1
        if commanded is None:
            commanded = self._update(t, fb)
        if not commanded:
            return out
        self.forced += 1
        out = dict(out or {})
        out["charge_goal"] = 1.0
        return out

    def wrap(self, policy):
        """Return `policy` with the manager applied to every returned command.

        `regen_commanded` is written onto the FEEDBACK VIEW BEFORE the strategy
        is called, so a strategy's charge bookkeeping can exclude a regen tick
        from its FC-path dwell (see the dwell note in the block comment).  The
        key is always present - True or False - so a strategy cannot read
        "absent" as "no manager" on a run that has one.

        ⚠️ `regen_commanded` follows the SAME decision the command does, so a
        window released early stops counting as a regen tick at the same instant
        it stops being commanded; the dwell accounting and the charge census
        cannot disagree with the command stream."""
        mgr = self

        def wrapped(t, fb):
            commanded = mgr._update(t, fb)
            if isinstance(fb, dict):
                fb["regen_commanded"] = commanded
            return mgr.apply(t, fb, policy(t, fb), commanded=commanded)

        # Forward the binding hook and the diagnostics attributes main() and
        # ems_walk resolve BY TYPE (`sdp_raw_src`, `dp_table_src`, `mpc_src`),
        # so wrapping a strategy cannot blank a CSV column or a sidecar block.
        wrapped.__wrapped__ = policy
        wrapped.regen_manager = mgr
        return wrapped


def unwrap_policy(policy):
    """The underlying strategy object behind a possible RegenManager wrapper.

    `main()` resolves the SDP / DP / MPC diagnostics sources by TYPE, and a
    wrapped policy is a plain function; every such isinstance() test goes
    through this so a scenario that declares `ems_regen_manager` does not
    silently lose its `cmd_share_sp_raw` column or its `config.mpc` block."""
    return getattr(policy, "__wrapped__", policy)


def ems_regen_harvest(t, fb):
    """regen-harvest — cruise/brake cycling that harvests on the REGEN path only.

    name       : regen-harvest
    intent     : reach the four regen-path signals that had NEVER been observed on
                 hardware (HIL_FINDINGS "charge-regen"): REGEN_ENABLE high with
                 FC_CHARGE_ENABLE low, MPPT_DISABLE LOW during braking, chopper
                 activity, and I_charge nonzero fed through REGEN + MOT_PWR.
    fields     : mode_cmd (SAFE -> HYBRID at EMS_RUN_ENTRY_S, back to SAFE at
                 EMS_REGEN_RUN_EXIT_S), v_setpoint (the
                 scenario's ems_v_profile), power_share_setpoint (0.50 constant),
                 charge_goal (1.0 inside a braking window, 0.0 otherwise).
    feedback   : uses `fb["t"]` and `fb["v_profile"]` ONLY — trivially portable to
                 the real Pi (FB_TELEMETRY_EQUIV_KEYS).
    ⚠️ WHAT THE REGEN WINDOWS SHOW — REWRITTEN FOR WP-C (2026-09-01).  The
                 caption this replaces said the plant floored regen power at zero
                 and that the charge seen here was bus-sourced, not harvested.
                 THAT IS NO LONGER TRUE: braking energy now flows end to end
                 (VESC_REGEN_I_MAX_A / ETA_REGEN block at the top of this file), so
                 the I_charge in a braking window IS recovered kinetic energy,
                 capped by the power actually available at VCHG-IN.  What is still
                 true and still worth reading twice: the harvest is SMALL.  The
                 regen-side clip is 1.5 A, i.e. ~1.13 N of braking force, so a
                 2.5 -> 0.4 m/s window returns single-digit joules; most of the
                 flywheel's kinetic energy still leaves through friction, and most
                 of what the VESC does return is burnt in the TL431 chopper during
                 the Ag105's 0.5 s settle rather than reaching the pack.  Pack SoC
                 across a window is therefore still a NET FALL (the bus load
                 outweighs the harvest); the harvest is read off I_charge and the
                 energy counters, not off SoC.  ⚠️ BASELINE ERA: regen-path traces
                 from campaigns <= 20260831_080905 were taken under the floor and
                 are NOT comparable with post-WP-C runs.
    why not a timeline: a pi_timeline is a STEP function, and a step-down in
                 v_setpoint rails the drive controller to -12 A for only
                 ~(dv / 3.3 m/s^2) — 0.8 s even for a 2.7 m/s step — which never
                 outlasts the Ag105's 0.5 s settle.  Sustained regen needs a
                 CONTINUOUS commanded deceleration whose rate exceeds the coast
                 rate a_coast(v) = (F_c + b*v)/m; only an interpolated profile can
                 produce one, which is why this scenario is EMS-driven.
    provenance : the profile's 1.0 m/s^2 braking rate vs a_coast(2.5) = 0.953
                 m/s^2 (F_COULOMB 2.00, B_EFF 0.534, M_EFF 3.5 — the fw v14
                 constants at the top of this file); Run-entry time from
                 EMS_RUN_ENTRY_S; 0.50 share is the firmware's own default.
    """
    v_sp = fb.get("v_profile")
    if v_sp is None:
        v_sp = EMS_DEFAULT_CRUISE_MPS
    charging = any((a + EMS_REGEN_CHARGE_LEAD_IN_S) <= t
                   < (b - EMS_REGEN_CHARGE_LEAD_OUT_S)
                   for a, b in EMS_REGEN_BRAKE_WINDOWS)
    in_run = EMS_RUN_ENTRY_S <= t < ems_run_exit(fb, EMS_REGEN_RUN_EXIT_S)
    return {
        "mode_cmd": MODE_HYBRID if in_run else MODE_SAFE,
        "power_share_setpoint": 0.50,
        "v_setpoint": v_sp,
        "charge_goal": 1.0 if charging else 0.0,
    }


# ── regen-harvest-hard: HARD braking, for genuine energy capture (WP-C) ─────
#
# A SEPARATE policy from `ems_regen_harvest`, for the same reason mppt-harvest is
# separate: `charge-regen` has pinned measurements across five campaigns and must
# not move.  Everything about the shape is different anyway.
#
# WHY A NEW PROFILE.  charge-regen commands 1.000 m/s^2 against a coast rate of
# 0.953 m/s^2 — 5 % over — which is all it needs to hold the drive command
# NEGATIVE and take the firmware's regen branch.  But the FORCE that buys is
# m*(a_cmd - a_coast) = 3.5*0.047 = 0.16 N, so the CAPTURED POWER is ~0.5 W and
# the harvest is in the millijoules.  That was invisible while regen was floored;
# with WP-C it is the difference between a path test and an energy test.  This
# profile commands 2.5 m/s^2 from 3.0 m/s, which the rig CANNOT achieve: the
# regen clip caps the braking force at K_F * VESC_REGEN_I_MAX_A = 1.13 N, so the
# realized decel is (1.13 + F_c + B_EFF*v)/M_EFF ~ 1.35 m/s^2 and the drive
# controller sits on its negative rail — clipped to 1.5 A — for the whole window.
# THE COMMANDED RATE BEING UNACHIEVABLE IS THE DESIGN, not an oversight: it is
# what guarantees a full-clip regen for the whole window instead of a controller
# that trims back toward coast.
EMS_REGENTRUE_BRAKE_WINDOWS = ((14.0, 15.5), (26.0, 27.5), (38.0, 39.5))
EMS_REGENTRUE_HI_MPS = 3.0
EMS_REGENTRUE_LO_MPS = 0.4
EMS_REGENTRUE_RUN_EXIT_S = 44.0


def ems_regen_harvest_hard(t, fb):
    """regen-harvest-hard — hard-braking cycling that HARVESTS kinetic energy.

    name       : regen-harvest-hard
    intent     : the WP-C energy test.  Where `regen-harvest` proves the regen
                 POWER PATH exists, this one puts measurable joules through it:
                 the VESC sits on its regen clip for the whole braking window, the
                 TL431 chopper burns the harvest while the Ag105 settles, and the
                 Ag105 takes it afterwards.  Objectives are a chopper_clamp episode
                 and I_charge delivered through REGEN + MOT_PWR.
    fields     : mode_cmd, power_share_setpoint (0.50), v_setpoint (the scenario's
                 `ems_v_profile`), charge_goal (1.0 inside a braking window).
    feedback   : `fb["t"]` and `fb["v_profile"]` ONLY (FB_TELEMETRY_EQUIV_KEYS).
    firmware modes assumed, per segment — the sub-0.55 A open-loop-hold rule
                 (a walk that skips this has been wrong twice):
                   standstill 0-3 s   Idle/MODE_SAFE; v_setpoint 0 is under
                                      V_SP_ZERO_THRESH 0.07, so the firmware
                                      commands 0 A and holds the drive controller
                                      in reset.  No share loop, no regen.
                   accel/cruise       Run, drive controller closed-loop, share loop
                                      CLOSED (I_tot at 3.0 m/s cruise is
                                      (F_c + B_EFF*v)/K_F = 4.78 A of motor current
                                      -> ~0.90 A of bus current + 0.15 A aux, over
                                      the 0.55 A open-loop-hold gate).
                   braking windows    Run, drive controller on its NEGATIVE rail;
                                      motor bus draw is ZERO (no motoring term), so
                                      I_tot falls to ~0.15 A aux and the share loop
                                      drops into OPEN-LOOP HOLD.  The share command
                                      is still 0.50 and still logged; the DELIVERED
                                      split is frozen at whatever the preceding
                                      cruise left.  Nothing here scores the split.
                   low cruise 0.4 m/s Run, above V_SP_ZERO_THRESH; I_tot ~0.30 A,
                                      so still open-loop hold.
    """
    v_sp = fb.get("v_profile")
    if v_sp is None:
        v_sp = EMS_DEFAULT_CRUISE_MPS
    charging = any((a + EMS_REGEN_CHARGE_LEAD_IN_S) <= t
                   < (b - EMS_REGEN_CHARGE_LEAD_OUT_S)
                   for a, b in EMS_REGENTRUE_BRAKE_WINDOWS)
    in_run = EMS_RUN_ENTRY_S <= t < ems_run_exit(fb, EMS_REGENTRUE_RUN_EXIT_S)
    return {
        "mode_cmd": MODE_HYBRID if in_run else MODE_SAFE,
        "power_share_setpoint": 0.50,
        "v_setpoint": v_sp,
        "charge_goal": 1.0 if charging else 0.0,
    }


# ── mppt-harvest: regen-harvest PLUS low-cruise FC-path charge windows ──────
#
# A VARIANT of `regen-harvest`, sharing its profile and its braking windows.
# ⚠️ `ems_regen_harvest` is NOT modified and NOT called from here: `charge-regen`
# has pinned measurements across five campaigns, and a shared implementation
# would let a change made for this scenario move that scenario's stimulus.  The
# two policies share CONSTANTS (EMS_REGEN_BRAKE_WINDOWS and the two lead times)
# and the scenario shares the ems_v_profile LIST OBJECT, which is the level at
# which sharing is safe.
#
# WHAT IT ADDS: charge_goal is ALSO asserted on the profile's LOW-CRUISE
# PLATEAUS (0.4 m/s, between the braking windows).  There the commanded motor
# current is positive, so chargingControl() takes its CRUISE branch
# (the cruise else-block, .ino:10037-10050): FC_CHARGE_ENABLE opens, BT drops
# off the bus, and the
# charger is fed from VBUS — which is the ONLY path on this board that presents
# the MPPT threshold with a rail it can fail.  The regen path feeds the charger
# from V-MOT with MPPT_DISABLE held LOW, where the threshold does not apply by
# construction.
EMS_MPPT_CRUISE_WINDOWS = ((16.1, 18.0), (28.1, 30.0), (39.1, 41.0))
# Inset from the plateau edges.  IN: 0.3 s, longer than regen's 0.2 s lead-in,
# because the command must have gone POSITIVE again after a braking ramp before
# charge_goal may be asserted — asserting it while `current < -0.1` would take
# the regen branch and never open FC_CHARGE.  OUT: 0.1 s, released before the
# next acceleration ramp begins.
EMS_MPPT_CRUISE_LEAD_IN_S = 0.30
EMS_MPPT_CRUISE_LEAD_OUT_S = 0.10


def ems_mppt_harvest(t, fb):
    """mppt-harvest — regen-harvest plus FC-path charge windows at low cruise.

    name       : mppt-harvest
    intent     : make MPPT_DISABLE CAUSALLY LOAD-BEARING.  With `mppt_emulation`
                 on (SCENARIOS["mppt-tracking"]), the plant's Ag105 refuses to
                 charge while tracking is RELEASED and the input rail is below
                 the threshold IN FORCE — which from fw v24 is whatever count the
                 board reports on observation-frame byte 15, not a fixed 18 V.
                 The objective is therefore INVERTED from fw v23: the run must
                 show the firmware lowering the threshold under the bus and
                 harvesting, NOT hunting.
    fields     : mode_cmd (SAFE -> HYBRID at EMS_RUN_ENTRY_S, back to SAFE at the
                 scenario's ems_run_exit_s), v_setpoint (the scenario's
                 ems_v_profile), power_share_setpoint (0.50 constant), charge_goal
                 (1.0 inside a BRAKING window or a LOW-CRUISE window, else 0.0).
    feedback   : `fb["t"]`, `fb["v_profile"]` and the scenario's ems_run_exit_s
                 ONLY — portable to the real Pi (FB_TELEMETRY_EQUIV_KEYS).

    ⚠️ THE HUNT IS fw v23 HISTORY, AND IS NOW THE FAILURE SIGNATURE.  fw v24's
    threshold manager writes reg 0x02 to (windowed-minimum V_chg − 3.0 V),
    quantized DOWN and clamped in COUNTS to [15, 27] = 12.320-13.376 V
    (.ino:1671-1690).  Under this scenario's FC-charge windows the target tracks
    the charger input rail three volts down, and in BOTH engines it lands inside
    this band — below the rail either way, but the exact count follows V_chg
    (rigid ~15.95 V bus in SIMPLE mode vs a charger-draw-sagged ~13.3-13.5 V rail
    in HIFI mode) and differs between engines, which is why the suite's checks
    bound the [15, 27] band rather than a single value.  The threshold in force
    stays comfortably under the rail either way.  The module therefore never
    refuses, ag105IsReady() holds, and MPPT_DISABLE stays released for the rest
    of each charge window.
    The .ino's own AG105_MPPT_N_CEIL static_assert is what makes this structural
    rather than incidental: the ceiling is pinned below V_BUS_CHARGED_THRESH less
    the VBUS→VCHG-IN ideal-diode drop, so a released threshold can never exceed a
    bus the bring-up called "up".

    A CAMPAIGN THAT STILL SEES TOGGLING IS A FINDING, not a scenario defect: it
    means the manager did not run, did not write, or FAILED (in which case
    chargingControl() holds MPPT inhibited for the session, .ino:10613-10617 — a
    HELD-LOW pin, not a hunt).  The suite's edge census bounds it either way.

    THE fw v23 LOOP, KEPT FOR THE RECORD because the suite's tick budgets below
    were derived from it and a regression would reproduce it.  Under a threshold
    ABOVE the bus, at the firmware's 50 Hz charger cadence
    (CHARGING_CTRL_PERIOD_US 20000, and pollAg105() on the same 20 ms telemetry
    gate, .ino:4406-4412):
        charge_goal>0, charger dark  -> MPPT_DISABLE LOW (not ready)
        threshold does not apply     -> module settles (0.5 s), then CHARGING
        firmware sees CHARGING       -> ag105IsReady() -> MPPT_DISABLE HIGH
        threshold now applies, 15.95 < 18 -> LOW_POWER, current decays
        firmware sees LOW_POWER      -> not ready -> MPPT_DISABLE LOW
        ... and round again.
    chargingControl() acts on the PREVIOUS poll's status, so the firmware's
    decision LAGS the module by one poll in BOTH directions: the half-cycle is
    2 charger ticks (~40 ms) and the FULL PERIOD is 4 (~80 ms), at ~50 % duty.
    Against AG105_TAU_S = 0.4 s that is a ~5 % move per half-cycle, so I_charge
    does not collapse — it equilibrates near HALF the configured ceiling with
    visible ripple.  The scenario's signal checks are derived from that
    equilibrium, not from the ceiling.

    MEASURED against this model (offline probe, 2026-08-31, FC-charge branch on a
    15.95 V bus at a 1.0 A ceiling): full period 80.0 ms, pin HIGH 50.0 % of
    ticks, GENSTAT "Low Power" on 50.0 %, MPPT_EN-without-PWR_TRACK on 50.0 %,
    I_charge equilibrium 0.465-0.525 A.  Those are the numbers the suite's signal
    thresholds are set against.  ⚠️ They are the MODEL's, not hardware's.
    (Re-run 2026-08-31 review round, same harness: period 80.0 ms, duty 50.0 %,
    equilibrium 0.472-0.525 A — reproduced.)

    THE WINDOW BUDGET, because the suite's tick ceilings are derived from it and
    an earlier draft of them used the wrong figure.  MPPT_DISABLE can only be
    HIGH where THIS strategy asserts charge_goal on the cruise path, i.e. inside
    EMS_MPPT_CRUISE_WINDOWS INSET by the two lead times, not across the whole
    plateaus:
        3 x (1.9 - EMS_MPPT_CRUISE_LEAD_IN_S - EMS_MPPT_CRUISE_LEAD_OUT_S)
          = 3 x 1.5 s = 4.5 s of charge-goal time,
        minus 3 x AG105_SETTLE_S = 3.0 s in which the pin can be HIGH.
    So ~1500 ticks hunting at 50 % duty, against ~3000 if it released and stayed
    released.  (The retired figures were 5.7 s / 4.2 s, taken from the
    un-inset plateaus.)  ⚠️ UNDER fw v24 THE EXPECTED OUTCOME IS THE ~3000-TICK
    ONE — the number the fw v23 entry treated as the failure — which is precisely
    why the old ceiling had to be replaced rather than re-tuned.

    THE FINDING THIS NOW PREDICTS: cruise-time harvesting on the FC path HOLDS,
    because the firmware lowered the module's own threshold under the bus.  The
    proof obligations are the reg-0x02 count on the wire (landing in the
    [15, 27] = 12.320-13.376 V clamp band — the exact count follows V_chg and
    differs between engines, so the obligation is the band, not a value) and
    the ABSENCE of the refusal signature, not the presence of a hunt.
    """
    v_sp = fb.get("v_profile")
    if v_sp is None:
        v_sp = EMS_DEFAULT_CRUISE_MPS
    braking = any((a + EMS_REGEN_CHARGE_LEAD_IN_S) <= t
                  < (b - EMS_REGEN_CHARGE_LEAD_OUT_S)
                  for a, b in EMS_REGEN_BRAKE_WINDOWS)
    cruising = any((a + EMS_MPPT_CRUISE_LEAD_IN_S) <= t
                   < (b - EMS_MPPT_CRUISE_LEAD_OUT_S)
                   for a, b in EMS_MPPT_CRUISE_WINDOWS)
    in_run = EMS_RUN_ENTRY_S <= t < ems_run_exit(fb, EMS_REGEN_RUN_EXIT_S)
    return {
        "mode_cmd": MODE_HYBRID if in_run else MODE_SAFE,
        "power_share_setpoint": 0.50,
        "v_setpoint": v_sp,
        "charge_goal": 1.0 if (braking or cruising) else 0.0,
    }


# ── soc-band: causal charge-sustaining EMS ──────────────────────────────────
#
# ⚠️ SIM-ONLY STRATEGY — NOT PORTABLE TO THE REAL PI AS WRITTEN.
# It closes on `fb["soc"]`, which is PLANT TRUTH from BatterySource's coulomb
# count and is deliberately NOT in FB_TELEMETRY_EQUIV_KEYS (see the MODE A block
# above: the real 2S pack has no SoC output at all, and v4 telemetry carries no
# SoC field).  Everything else it reads — `t`, `v_profile`, `I_fc`, `I_batt` —
# IS telemetry-equivalent.  The portable path is a V_batt-based SoC ESTIMATOR
# on the Pi (OCV lookup plus coulomb counting off the telemetry `I_batt`),
# feeding this same law unchanged; that estimator is FUTURE WORK and does not
# exist in this repository.  Do not ship this policy to a Pi and assume the
# `soc` key will be there.
#
# WHAT IT MIRRORS, AND WHAT IT DOES NOT.  The DP study (references/EMS/DPtrial.m,
# references/EMS/DP_EnergyManagement2.m) minimises hydrogen subject to a
# charge-sustaining terminal constraint on SoC.  This policy mirrors that
# OBJECTIVE STRUCTURE — "keep SoC near where it started; when it drifts low,
# shift load to the fuel cell and recharge opportunistically" — and NOTHING
# ELSE.  It is CAUSAL (a DP solution is not), it imports no absolute watts and
# no lambda/co-state value from the MATLAB, and every constant below is in
# SCALE-CAR units derived from this rig's own numbers.  It is not a DP solution
# and not an approximation of one.  Its H2 numbers are the Gfc MODEL'S ESTIMATE
# (the map is scale-portable — H2Consumption banner); the surviving caveat is
# that the stack is not identified, TODO(calibrate), and rankings against
# another strategy on this same rig are robust regardless.
#
# ── Tunables ────────────────────────────────────────────────────────────────
# SoC deadband half-width, in SoC fraction.  ⚠️ BENCH-SCALED, deliberately.
# A vehicle-scale charge-sustaining band is ~0.02 (2 % SoC), and that is the
# value to restore for any vehicle-level study.  It is unusable on this rig:
# with a 5 Ah pack, the `ems-soc-band` scenario's drain phase moves SoC at
# ~1.0e-4 /s (see the scenario entry's budget), so 0.02 would take ~200 s to
# cross and the policy would sit at nominal share for the whole of a ≤60 s HIL
# run — i.e. the branch under test would never execute.  0.0015 is crossed
# ~11.9 s into that drain, leaving ~23 s of biased operation to observe.
# TODO(calibrate): restore ~0.02 once a pack-scale endurance scenario exists.
SOC_BAND_HALF = 0.0015
# Excess beyond the band edge, as a FRACTION of the band half-width, at which
# the share correction saturates.  0.5 -> full authority one half-band past the
# edge (0.00225 total deficit here), reached ~7 s after the crossing.
SOC_BAND_SAT_EXCESS_FRAC = 0.5
# Nominal split when SoC is inside the band.  0.50 is the firmware's own
# default power_share_setpoint, and the same value hold-5050 pins.
SOC_BAND_SHARE_NOMINAL = 0.50
# Maximum correction either way -> commanded share stays in [0.25, 0.75].
# Sized against TWO firmware limits, both with margin at the scenario's load:
#   * updateShareSetpointCutoff() (.ino:9377-9385, latch at .ino:9231-9257)
#     drives a channel's *_BUS_ENABLE LOW for a setpoint outside
#     [DROOP_R_MIN 0.15, DROOP_R_MAX 0.85].  Exercising THAT is handoff-sag's
#     job; this scenario must never trip it, so the span stops 0.10 short of
#     both rails.
#   * LIMIT_I_FC_MAX 1.4 A.  At the scenario's ~1.45 A drain-phase bus total,
#     0.75 puts 1.09 A on FC — 22 % margin.  A larger span would eat it.
SOC_BAND_SHARE_SPAN = 0.25
# HARD clamp, applied last and independently of the span above: the share-cut
# band itself.  Redundant with the span by construction, kept as the assertion
# that this policy can never command a cut, whatever the span is retuned to.
SOC_BAND_SHARE_MIN = 0.15
SOC_BAND_SHARE_MAX = 0.85
# ── Causal cruise detection ─────────────────────────────────────────────────
# The profile slope is measured over a TRAILING window of values this policy has
# ALREADY evaluated — never by looking ahead into `ems_v_profile`.  A real Pi
# has no future either, and OPERATOR RULING (b) (charging and acceleration are
# incompatible on this hardware) has to hold on the same information the Pi has.
SOC_BAND_CRUISE_WINDOW_S = 1.0
# |dv/dt| at or below this counts as cruise.  The scenario's gentlest RAMP is
# 0.167 m/s^2 (3.3x this bound) and its cruise segments are exactly flat, so the
# classification is not marginal.  50 Hz x 1.0 s = 50 samples, so profile noise
# is not an issue either (the profile is piecewise-linear and noise-free).
SOC_BAND_CRUISE_SLOPE_MAX = 0.05
# Below this speed "cruise" is not a meaningful operating point: it is the drive
# design's own validity floor (CLAUDE.md fw v12: gate-checked for v >= 0.5 m/s).
SOC_BAND_CRUISE_MIN_MPS = 0.5
# ── Charge-window admission, with hysteresis ────────────────────────────────
# Charging on the FC path is SINGLE-SOURCE by design: assertFcChargeEnable()
# drops BT off the bus (.ino:10046), so the whole bus load plus the charger
# lands on the FC channel against LIMIT_I_FC_MAX 1.4 A.  The policy therefore
# admits a charge window only when the measured source total is small.  Both
# thresholds read `fb["I_fc"] + fb["I_batt"]`, which ARE telemetry-equivalent.
#   ENTER 0.60 A — at the scenario's 1.0 m/s charge cruise the total is ~0.34 A
#                  (i_aux 0.15 + i_motor 0.19), so the window opens; during the
#                  drain phase it is ~1.45 A and stays shut.
#   EXIT  1.30 A — hysteresis, and a guard.  Once FC_CHARGE opens, the measured
#                  total JUMPS to the single-source value (~0.34 plus the
#                  charger's input draw), which is above ENTER: without
#                  hysteresis the policy would immediately withdraw charge_goal
#                  and chatter the path open/closed at 50 Hz.  1.30 A sits
#                  above that steady value and below LIMIT_I_FC_MAX 1.4 A, so
#                  the release doubles as an overcurrent backstop.
#   ⚠️ THE CHARGER'S STAMPED DRAW MOVED (2026-09-01).  Both engines now bill the
#   charger through ETA_CHG (see the CHARGER BILLING block in Plant.step()), so
#   its input current is i_charge*V_batt/(ETA_CHG*V_bus), not `i_charge`.  At
#   this scenario's 0.8 A ceiling that is ~0.46 A rather than 0.8 A, and the
#   measured total after the path opens is ~0.80 A rather than ~1.14 A.  Still
#   above ENTER (so the hysteresis is still required) and still below EXIT (so
#   the release is still reached only by an anomaly), but with more headroom
#   than the pre-eta figures showed.
#   ⚠️ L9 (review, 2026-08-31) IS RETIRED.  It recorded that only the hi-fi
#   engine stamped the charger on the bus, so the "overcurrent backstop"
#   reading held under `--electrical hifi` only.  Simple mode now bills the
#   charger too, and both engines use the one rule, so the reading holds in
#   both.  The FIRMWARE's own LIMIT_I_FC_MAX check is unaffected either way —
#   it reads the injected rails.
SOC_BAND_CHARGE_ENTER_ITOT_A = 0.60
SOC_BAND_CHARGE_EXIT_ITOT_A = 1.30
# charge_goal is an INTENT, not a current: the firmware maps any value > 0 onto
# "open the path and let the Ag105 run at its configured ceiling" (see the
# PiCommander field notes and .ino chargingControl()).  1.0 = full intent.
SOC_BAND_CHARGE_GOAL = 1.0
# Hand the firmware back MODE_SAFE here so the run closes out Run -> Finish ->
# Idle instead of ending parked in State 2 (the F14(b) fix the other two
# strategies carry).  Chosen against the `ems-soc-band` profile, which reaches
# standstill at t = 58.0 and holds it to the 61 s duration.
SOC_BAND_RUN_EXIT_S = 58.0


class SocBandStrategy:
    """soc-band — causal charge-sustaining split, with opportunistic charging.

    name       : soc-band
    intent     : mirror the DP study's OBJECTIVE STRUCTURE (minimise hydrogen
                 subject to charge sustenance) with a causal law, so the H2
                 metric has something to rank.  See the SIM-ONLY banner above.
    fields     : mode_cmd (SAFE -> HYBRID at EMS_RUN_ENTRY_S, back to SAFE at
                 SOC_BAND_RUN_EXIT_S), v_setpoint (the scenario's
                 `ems_v_profile`), power_share_setpoint (deadband-P law on the
                 SoC error), charge_goal (only in an admitted charge window).
    feedback   : `t`, `v_profile`, `I_fc`, `I_batt` (all telemetry-equivalent)
                 and `soc` (PLANT TRUTH — the non-portable term).
    law        : reference SoC0 is CAPTURED ON THE FIRST CALL, so the policy
                 sustains wherever the run started rather than chasing an
                 absolute target it has no business choosing.  Deficit
                 d = SoC0 - soc.  Inside +/-SOC_BAND_HALF the split is nominal.
                 Beyond the edge the correction is proportional to the EXCESS,
                 saturating at SOC_BAND_SHARE_SPAN once the excess reaches
                 SOC_BAND_SAT_EXCESS_FRAC * SOC_BAND_HALF:
                     d > +half  ->  share UP   (toward the fuel cell; the pack
                                    is low, so the FC carries more and the pack
                                    discharges more slowly)
                     d < -half  ->  share DOWN (toward the battery)
                 share = 1.0 is the FC rail and 0.0 the battery rail — the same
                 convention soc-depletion's timeline uses (`power_share_setpoint
                 0.0` = "all load onto the battery") and handoff-sag's cut
                 direction confirms.
    charging   : charge_goal > 0 requires ALL of — a genuine deficit (below the
                 band), CRUISE by the causal slope test, and a measured source
                 total under the admission threshold.  NEVER during
                 acceleration (operator ruling (b), 2026-08-30).

    STATE.  This is a class rather than a plain function because the law needs
    three pieces of state: the captured reference SoC, the trailing profile
    window, and the charge-window hysteresis latch.  EMS_STRATEGIES holds ONE
    instance, which is correct for the simulator (one policy, one process, one
    run) and is why reset() exists for anything that reuses it.  A rewind
    (t going backwards) auto-resets, so a second run in one process cannot
    inherit the first run's reference.
    """

    def __init__(self, charge_enter_itot_a=None, charge_exit_itot_a=None):
        # ── PER-SCENARIO CURRENT THRESHOLDS (2026-09-02) ─────────────────────
        # THE PROBLEM THEY SOLVE.  `SOC_BAND_CHARGE_ENTER_ITOT_A` (0.60 A) and
        # `SOC_BAND_CHARGE_EXIT_ITOT_A` (1.30 A) are ABSOLUTE currents,
        # calibrated against a plant carrying the measured rig road load.  Under
        # `--drag scaled-air` the compensated cycle's peak source total is
        # 0.330 A - BELOW THE ENTRY THRESHOLD AT EVERY INSTANT - so the strategy
        # would admit a charge window at the first cruise sample and never exit
        # it by current.  That is not a defect in the policy; it is a threshold
        # calibrated against a plant with 4.5x the drag, and a permanently-open
        # window would make the leg useless as a frontier REFERENCE.
        #
        # THE OVERRIDE IS SCENARIO-SCOPED, so the 61 s and `ftp75` legs are
        # untouched: `None` keeps the module constants and every existing
        # construction is byte-identical.  The `ems-ftp75c-socband` values are
        # derived at their registration site, not here - see
        # FTP75C_SOCBAND_CHARGE_ENTER_A.
        self.charge_enter_itot_a = (SOC_BAND_CHARGE_ENTER_ITOT_A
                                    if charge_enter_itot_a is None
                                    else float(charge_enter_itot_a))
        self.charge_exit_itot_a = (SOC_BAND_CHARGE_EXIT_ITOT_A
                                   if charge_exit_itot_a is None
                                   else float(charge_exit_itot_a))
        if self.charge_exit_itot_a < self.charge_enter_itot_a:
            raise ValueError(
                "soc-band charge EXIT threshold (%r A) must be at or above the "
                "ENTER threshold (%r A) - the pair is a hysteresis and an "
                "inverted one latches a window shut the instant it opens"
                % (self.charge_exit_itot_a, self.charge_enter_itot_a))
        self.reset()

    def bind_scenario(self, scenario, meta, electrical_mode=None, args=None,
                      droop_mode=None, asymmetry_mode=None, drag_mode=None):
        """Read the per-scenario threshold overrides.  Never refuses.

        The generic startup hook, in the shape `main()` calls it.  Unlike the
        DP and SDP binders this one validates nothing about an artifact - it has
        none - so it cannot refuse; what it does is make the override arrive
        through the SAME path a strategy's other scenario keys do, instead of
        through a constructor a scenario registry cannot reach."""
        enter = (meta or {}).get("soc_band_charge_enter_itot_a")
        exit_ = (meta or {}).get("soc_band_charge_exit_itot_a")
        if enter is not None:
            self.charge_enter_itot_a = float(enter)
        if exit_ is not None:
            self.charge_exit_itot_a = float(exit_)
        if self.charge_exit_itot_a < self.charge_enter_itot_a:
            raise ValueError(
                "scenario %r declares a soc-band charge EXIT threshold (%r A) "
                "below its ENTER threshold (%r A)"
                % (scenario, self.charge_exit_itot_a, self.charge_enter_itot_a))
        self.reset()
        return None

    def reset(self):
        self.soc_ref = None         # captured on the first call that sees a SoC
        self.window = []            # [(t, v_cmd)] trailing profile samples
        self.charging = False       # charge-window hysteresis latch
        self.last_t = None
        self.last_share = SOC_BAND_SHARE_NOMINAL
        self.last_deficit = 0.0

    # ── helpers, kept separate so a test can drive them directly ────────────
    def share_for_deficit(self, deficit):
        """Deadband-P share command for a SoC deficit (SoC0 - soc)."""
        half = SOC_BAND_HALF
        excess = abs(deficit) - half
        if excess <= 0.0:
            return SOC_BAND_SHARE_NOMINAL
        sat = SOC_BAND_SAT_EXCESS_FRAC * half
        frac = 1.0 if excess >= sat else (excess / sat)
        corr = SOC_BAND_SHARE_SPAN * frac
        share = SOC_BAND_SHARE_NOMINAL + (corr if deficit > 0.0 else -corr)
        # Hard clamp last — see SOC_BAND_SHARE_MIN/MAX.
        return min(SOC_BAND_SHARE_MAX, max(SOC_BAND_SHARE_MIN, share))

    def is_cruising(self, t, v_cmd):
        """Trailing-window slope test.  Causal: only already-seen samples."""
        self.window.append((t, v_cmd))
        while self.window and (t - self.window[0][0]) > SOC_BAND_CRUISE_WINDOW_S:
            self.window.pop(0)
        if len(self.window) < 2:
            return False
        t0, v0 = self.window[0]
        span = t - t0
        # A window that is not yet FULL cannot certify cruise: right after an
        # acceleration ends, the few samples available are all flat and would
        # read as cruise while the vehicle is still settling.  Require at least
        # 90 % of the nominal window.
        if span < 0.9 * SOC_BAND_CRUISE_WINDOW_S:
            return False
        if v_cmd < SOC_BAND_CRUISE_MIN_MPS:
            return False
        return abs(v_cmd - v0) / span <= SOC_BAND_CRUISE_SLOPE_MAX

    def __call__(self, t, fb):
        if self.last_t is not None and t < self.last_t:
            self.reset()            # rewind => a new run, not this one's tail
        self.last_t = t

        v_sp = fb.get("v_profile")
        if v_sp is None:
            v_sp = EMS_DEFAULT_CRUISE_MPS

        soc = fb.get("soc")
        if soc is None:
            # No SoC term available (a feedback view without plant truth): fall
            # back to the nominal split rather than inventing a reference.  The
            # policy degrades to hold-5050's share, loudly doing nothing.
            deficit = 0.0
        else:
            if self.soc_ref is None:
                self.soc_ref = float(soc)
            deficit = self.soc_ref - float(soc)
        self.last_deficit = deficit
        share = self.share_for_deficit(deficit)
        self.last_share = share

        cruising = self.is_cruising(t, v_sp)
        i_tot = (fb.get("I_fc") or 0.0) + (fb.get("I_batt") or 0.0)
        # Deficit gate: only a SoC genuinely BELOW the band justifies opening
        # the charger path at all.  Inside the band the pack is where it should
        # be and the path stays shut.
        #
        # M6 (review, 2026-08-31) — HYSTERESIS, for the same reason the i_tot
        # gate above has it.  The deficit is what CHARGING ITSELF drives back
        # toward zero, so a single threshold makes the gate its own release: at
        # deficit ~= SOC_BAND_HALF the window opens, the charger closes the
        # deficit, the gate falls below the threshold and the window shuts —
        # then the drain reopens it, at 50 Hz.  ENTER at `> SOC_BAND_HALF`
        # (band-edge crossing, unchanged); HOLD while `> 0.0`, i.e. release
        # only when the pack is back AT the reference, not merely back inside
        # the band.  Stated plainly: the SHIPPED `ems-soc-band` scenario cannot
        # reach the chatter (its charge window is 13 s long and the pack never
        # recovers the full deficit inside it), so this changes no trace today.
        # The law is reusable and must not carry a latent 50 Hz chatter mode
        # into the first scenario whose charge window IS long enough.
        deficit_gate = deficit > (0.0 if self.charging else SOC_BAND_HALF)
        if self.charging:
            self.charging = (deficit_gate and cruising
                             and i_tot <= self.charge_exit_itot_a)
        else:
            self.charging = (deficit_gate and cruising
                             and i_tot <= self.charge_enter_itot_a)
        # A REGEN WINDOW IS NOT AN FC CHARGE WINDOW (2026-09-02).  Inside one
        # the regen manager forces `charge_goal` to 1.0 and the FIRMWARE opens
        # the REGEN path, not the FC path; counting the tick as an FC charge
        # window would put a window in the census that never existed and would
        # let this latch hold through a braking event on the strength of a
        # current the charger was not drawing.  `regen_commanded` is written by
        # RegenManager.wrap() BEFORE this call and is absent on every run that
        # has no manager, which reads as False.
        if fb.get("regen_commanded"):
            self.charging = False

        in_run = EMS_RUN_ENTRY_S <= t < ems_run_exit(fb, SOC_BAND_RUN_EXIT_S)
        if not in_run:
            # Outside the Run window nothing may be commanded onto the charger
            # path: chargingControl() only runs in State 2 anyway, and leaving
            # the intent asserted across the Run exit would be a command the
            # firmware silently ignores — i.e. a lie in the CSV's cmd columns.
            self.charging = False
        return {
            "mode_cmd": MODE_HYBRID if in_run else MODE_SAFE,
            "power_share_setpoint": share,
            "v_setpoint": v_sp,
            "charge_goal": SOC_BAND_CHARGE_GOAL if self.charging else 0.0,
        }


# One instance, registered below.  See the SocBandStrategy STATE note.
ems_soc_band = SocBandStrategy()


# ── dp-replay: the NON-CAUSAL offline-optimal benchmark ─────────────────────
#
# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║ ⚠️  THIS IS NOT A CONTROLLER.  It plays back a setpoint table computed    ║
# ║ OFFLINE by tools/gen_dp_ems_table.py with FULL FOREKNOWLEDGE of the       ║
# ║ entire drive cycle and the entire auxiliary load, by backward dynamic     ║
# ║ programming.  It reads NO feedback, reacts to NOTHING, and is meaningless ║
# ║ against any profile or load other than the one its table was generated    ║
# ║ for.  Its purpose is to be a LOWER-BOUND REFERENCE that the causal        ║
# ║ strategies (hold-5050, soc-band) are ranked against — the "how much was   ║
# ║ left on the table?" axis.  It is not portable to the real Pi in any       ║
# ║ sense: a Pi has no future.                                                ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
#
# WHAT IT DOES READ.  Exactly one feedback key, `v_profile` — the scenario's own
# scripted speed profile, which is a HOST-SIDE SCRIPT and not feedback at all
# (see the MODE A block).  The two energy-management fields it commands
# (power_share_setpoint, charge_goal) come from the table, indexed by time
# alone.  It therefore uses NOTHING from FB_TELEMETRY_EQUIV_KEYS and nothing
# from plant truth; the open-loop-ness is the whole point, and it is why a
# realised run WILL diverge from the table's predicted SoC trajectory (the
# board's share loop, the Ag105's settle+ramp and the plant's own drag are all
# outside the generator's reduced model).
#
# THE PROFILE GUARD.  A table is pinned to its scenario by
# `dp_profile_fingerprint()` (below).  main() binds the active scenario into the
# strategy before the run starts (bind_scenario()), which is where BOTH failure
# modes are refused LOUDLY and EARLY:
#   * the table file is missing/unreadable/malformed  -> refusal at startup
#   * the active scenario's fingerprint does not match -> refusal at startup
# A strategy that was never bound raises on its FIRST call rather than silently
# commanding a 0.5 split, so no path can produce a trace labelled `dp-replay`
# that is not actually the DP's.
DP_TABLE_DIR = os.path.join(REPO_ROOT, "tools", "dp_tables")
DP_TABLE_NAME = "dp_ems_table_%s.csv"

# The scenario metadata fields the fingerprint covers.  Deliberately narrow:
# these are the inputs the DP's demand model reads (D7 in the generator).  A
# change to any of them invalidates the table; a change to, say, the
# description does not.
# `aux_preload_a` JOINED THIS TUPLE 2026-09-01 (WP-E), on the exact condition
# its own deferral note stated: "add it — and regenerate — when a SECOND DP
# scenario lands".  `ems-ftp75-dp` is that scenario, and it declares
# FTP75_PRELOAD_A, so the key had to become fingerprinted or the guard would
# have accepted a table solved against a different bus load.  Both tables in
# tools/dp_tables/ were regenerated in the same change; the import-time refusal
# that stood in for the coverage is retired.
#
# ⚠️ SCOPE OF THE COVERAGE (E-L4, 2026-09-01).  Between them the fingerprint and
# bind_scenario()'s drift guard cover the DECLARED keys — the ones named in this
# tuple and in the table header.  A demand-shaping key added to NEITHER set is
# still INVISIBLE to both: the fingerprint does not hash it, the guard does not
# compare it, and a table solved before it existed loads clean.  The guards make
# a KNOWN input's drift loud; they cannot make an UNDECLARED input's drift
# detectable.  Adding a scenario key that changes the demand therefore means
# adding it HERE (or to the header) in the same change — that is a rule about
# the author's discipline, not a property the mechanism enforces.
#
# `eta_chg` JOINED THIS TUPLE 2026-09-01 (the charger-efficiency round).  It is
# the first MODEL constant in the tuple rather than a scenario key: no scenario
# declares it, so `dp_profile_fingerprint()` hashes the ERA SENTINEL `None` for
# a live scenario — it does NOT substitute the module's current efficiency (see
# `dp_eta_chg()`, which owns that convention).  It belongs here because the DP's
# demand model now has to
# bill the charger's INPUT power, which is the output power divided by exactly
# this number — a table solved at one efficiency is not a table for another.
# ⚠️ CORRECTED 2026-09-02: adding it does NOT move any existing fingerprint.
# The key is OPTIONAL (DP_FINGERPRINT_OPTIONAL_KEYS below) — its old-era
# sentinel is written as an omitted line, not as `eta_chg=None` — so a live
# scenario, which declares nothing, hashes exactly as it did before the key
# existed. The first version of this key wrote the line unconditionally and
# did move every digest; that is what the note above used to record.
# `loss_map` JOINED THIS TUPLE 2026-09-02 (the DP-bound round), on the same
# terms as `eta_chg` and for the same reason: the DP's demand model now carries
# the plant's static losses, and a table solved with a map is not a table for a
# solve without one. It is OPTIONAL, so an old-era digest is bit-identical to
# its pre-key value; see DP_FINGERPRINT_OPTIONAL_KEYS.
# `drag` and `eta_regen` JOINED THIS TUPLE 2026-09-02 (the ftp75c round), on
# the same OPTIONAL terms as the two keys above and for the two halves of one
# reason.  `drag` changes the TRACTIVE DEMAND for a given speed profile - the
# compensated profiles cut the FTP-75 peak bus current by roughly 4.5x - which
# is exactly the class of change `eta_chg` was.  `eta_regen` changes what the
# demand model CREDITS on a braking stage.  They are TWO keys and not one
# because they are independent: a rig-drag run in the regen era is legitimate
# and earns (structurally) zero credit, and a compensated run in the pre-regen
# era is a defined, if pointless, configuration.  Both are OMITTED at their
# sentinels ("rig" and None), which is what keeps every committed DP table,
# every SDP policy artifact and every dp_db record reachable and byte-identical.
DP_FINGERPRINT_META_KEYS = ("ems_v_profile", "duration_s", "chg_i_ceiling_a",
                            "aux_preload_a", "eta_chg", "loss_map",
                            "drag", "eta_regen")

# Keys whose SENTINEL VALUE is written into the digest as an OMITTED LINE
# rather than as `key=None` (orchestrator ruling, 2026-09-02; the convention
# `tools/dp_results_db.py`'s OPTIONAL_KEY_FIELDS already uses).  `eta_chg` is
# the case: its sentinel names the ERA THAT PREDATES THE KEY, so writing a line
# for it would have moved every fingerprint computed before the key existed —
# every committed table and every stored DP result — while changing nothing
# about the problem any of them solved.  With the line omitted an old-era
# digest is bit-identical to its pre-key value, and only a run or sidecar that
# DECLARES an efficiency hashes differently.
DP_FINGERPRINT_OPTIONAL_KEYS = frozenset({"eta_chg", "loss_map",
                                          "drag", "eta_regen"})


def _dp_fp_resolve(key, meta):
    """The fingerprint's own resolution of one key, for the sentinel test."""
    if key == "eta_chg":
        return dp_eta_chg(meta)
    if key == "loss_map":
        return dp_loss_map(meta)
    if key == "drag":
        return dp_drag_mode(meta)
    if key == "eta_regen":
        return dp_eta_regen(meta)
    return meta.get(key)


def dp_drag_mode(meta):
    """The ROAD-LOAD PROFILE a DP table is solved / replayed against, or None.

    THE ERA SENTINEL is `None`, and it names the MEASURED RIG PROFILE - the
    only road load that existed before 2026-09-02 and the one the bench still
    runs.  An absent `drag` key and an explicit `"rig"` are the SAME statement
    and both resolve to None, so a scenario that predates the key fingerprints
    exactly as it did.

    Unlike `dp_eta_chg()` this key IS declared by scenarios (the `ems-ftp75c-*`
    family declares `"drag": "scaled-air"`), so the fingerprint separates a
    compensated table from a rig table by itself and no bind-time era guard is
    needed for it.  The guard that IS needed is the RUN's: `--drag` can override
    a scenario, which is what `DpReplayStrategy.bind_scenario()` checks."""
    v = meta.get("drag")
    if v in (None, DRAG_MODE_RIG):
        return None
    if v not in DRAG_MODES:
        raise ValueError("unknown drag profile %r (choices: %s)"
                         % (v, ", ".join(DRAG_MODES)))
    return v


def plant_drag_mode(drag_mode=None):
    """`dp_drag_mode()`'s vocabulary for a RESOLVED run configuration.

    `drag_mode` is the mode the run will actually apply (CLI, or the scenario's
    own key).  None means the caller is asking about the SHIPPED default, which
    is the rig profile.  Returns the sentinel None for `rig` and the mode string
    otherwise, so the value is directly comparable with a table header's."""
    if drag_mode is None:
        drag_mode = DRAG_MODE_DEFAULT
    if drag_mode not in DRAG_MODES:
        raise ValueError("drag_mode must be one of %s, got %r"
                         % (DRAG_MODES, drag_mode))
    return None if drag_mode == DRAG_MODE_RIG else drag_mode


def dp_eta_regen(meta):
    """The REGEN EFFICIENCY a DP table is solved / replayed against, or None.

    THE ERA SENTINEL is `None` and it names the PRE-REGEN DEMAND MODEL -
    `p_mech = max(0, F*v)` with no credit at all, which is what every DP table,
    SDP policy and dp_db record committed before 2026-09-02 was solved against.
    One convention, shared with `tools/regen_power.py`'s `resolve_eta_regen()`.

    A live SCENARIO declares nothing, so `dp_profile_fingerprint()` hashes the
    sentinel for both eras and CANNOT separate them - exactly as with `eta_chg`
    and `loss_map`.  The table's own `# eta_regen:` header line is the record,
    and `DpReplayStrategy.bind_scenario()` is where the eras are compared."""
    v = meta.get("eta_regen")
    return None if v is None else float(v)


def plant_eta_regen(drag_mode=None):
    """THE REGEN ERA A RUN'S DP BOUND MUST CARRY, in `dp_eta_regen()`'s terms.

    ⚠️ THIS IS NOT "does the plant regenerate".  The plant has returned braking
    energy to the pack since the WP-C round and does so under EVERY drag
    profile.  What this function answers is the question the bind-time guard
    actually asks: MUST THE DEMAND MODEL CARRY THE CREDIT FOR THIS RUN'S BOUND
    TO BE A BOUND?

    Under the MEASURED RIG PROFILE the answer is no, and it is no for a physical
    reason rather than by convention: the rig road load exceeds the inertial
    force at every deceleration in every registered cycle, so the braking energy
    that reaches the pack is 0.001 J over a 340 s FTP-75 segment (measured, and
    against a ~30.8 J braking kinetic energy).  A pre-regen table is a valid
    bound on such a run to well inside the ~50 ppm h2 repeatability floor, and
    treating it otherwise would orphan every committed table for a credit that
    does not exist.

    Under a COMPENSATED profile the answer is yes: 12.5 J reaches the V-MOT node
    on `ftp75c`, and a table solved without the credit must buy that SoC with
    hydrogen, which INFLATES the bound and flatters the run it is scored
    against.  That is the divergence this round closes."""
    return None if plant_drag_mode(drag_mode) is None else float(ETA_REGEN)


def dp_eta_chg(meta):
    """The Ag105 charge efficiency a DP table is solved / replayed against.

    ONE resolution, in the same shape as `dp_chg_ceiling_a()` above — but with
    the OPPOSITE default, and the difference is the point.

    THE ERA SENTINEL (operator ruling, 2026-09-01).  An ABSENT `eta_chg` means
    the run, sidecar or table it came from PREDATES the charger-efficiency
    model: its charger was the 1:1 current-transfer element, which billed the
    bus `V_bus*i_chg` and is NOT reproducible by any efficiency value (the new
    model bills `V_pack*i_chg/eta`).  That era is named `None`, here and in
    tools/charger_power.py's `resolve_eta_chg()`, so ONE convention crosses
    both modules.  A present numeric value means the energy-conserving era.

    Consequences, stated because they are easy to get backwards:
      * This function is NOT the plant's runtime billing.  The simulator bills
        every new run at `hil_electrical.ETA_CHG` (0.88) directly, and
        `main()` writes that number into the run sidecar, so a NEW run's
        metadata carries 0.88 explicitly and never relies on a default.
      * A live SCENARIO declares nothing, so `dp_profile_fingerprint()` hashes
        `eta_chg=None` for it.  A generated DP table and the `dp-replay`
        consumer therefore agree by construction, and the table's own era is
        recorded in its `# eta_chg:` header line (documentation, in the same
        way `aux_preload_a` is).
      * Where the sentinel DOES separate two problems is the archived-run
        path: a pre-era sidecar carries no key and a post-era one carries
        0.88, so `dp_results_db`'s era overrides key the two eras' baselines
        apart instead of colliding on one digest."""
    v = meta.get("eta_chg")
    return None if v is None else float(v)


def plant_eta_chg():
    """THE ERA THIS PROCESS'S PLANT RUNS IN, in `dp_eta_chg()`'s vocabulary.

    The simulator bills every charge stage at `hil_electrical.ETA_CHG`, so the
    plant's era is that constant — a float for the energy-conserving buck/boost
    era, and `None` for the 1:1 current-transfer era that preceded it.  There is
    no scenario key that overrides it today; when one is added, this is the ONE
    function that has to learn about it, and every consumer below follows.

    Read through the MODULE GLOBAL rather than captured at import so a test can
    place the process in either era (`monkeypatch.setattr(hil, "ETA_CHG", None)`)
    without a second copy of the convention."""
    return None if ETA_CHG is None else float(ETA_CHG)


def eta_chg_era_label(eta):
    """A short printable era name.  ONE text for every refusal and warning."""
    if eta is None:
        return "the 1:1 CURRENT-TRANSFER charger (bus power = V_bus*i_chg)"
    return ("an energy-conserving charger at eta_chg = %g "
            "(bus power = V_pack*i_chg/eta_chg)" % eta)


# ═════════════════════════════════════════════════════════════════════════════
# THE DP DEMAND MODEL'S STATIC-LOSS MAP (2026-09-02, the DP-bound round)
#
# WHY IT EXISTS.  The delta-SoC-matched DP is a LOWER BOUND on hydrogen: it is
# the best any causal policy could have done on the same demand.  A bound is
# only useful if it is priced against the SAME demand the board actually saw.
# Until this round the DP's demand model carried the motor draw and the
# housekeeping drain and NOTHING ELSE, while the hi-fi plant additionally bills
# the sources for every static loss on the energized path.  A decomposition of
# the two `dp-replay` legs (campaign 20260902_041414) attributed the residual
# term by term:
#
#   term                                     FTP-75      61 s cycle
#   node bleed on N_BUS and N_MOT            +4.90 %     +2.58 %
#   droop-mode mismatch in the bus law       -0.67 %     -2.73 %
#   ------------------------------------------------------------------
#   measured deviation of the run vs the DP  +4.346 %    -0.198 %
#
# BOTH DEFECTS ARE FIXED TOGETHER, and that is not a stylistic choice: they
# have OPPOSITE SIGNS and partially cancelled, so fixing one alone makes the
# deviation worse ON AT LEAST ONE LEG.  The three partials, measured:
#
#   configuration                          ems-dp-replay   ems-ftp75-dp
#   today (no map, 2 kOhm bleed)             -0.1979 %       +4.3463 %
#   bleed only (no map, per-node bleed)      -2.6273 %       -0.2999 %
#   bus law only (no bleed term, per-node)   -0.1723 %       +0.2722 %
#   BOTH (the shipped map and bleed)         -0.3031 %       +0.0294 %
#
# The bleed-only row is the one that makes the case: it is worse than today on
# `ems-dp-replay` by an order of magnitude.  The bus-law-only row is NOT worse
# on that leg (-0.1723 % against -0.1979 %, and it is the best of the four
# there), so "either alone is worse" is not literally true and is not the
# argument.  It IS worse than the full map on `ems-ftp75-dp` (+0.2722 %
# against +0.0294 %), so no single partial wins on both legs.  THE ARGUMENT IS BLEED-INVARIANCE:
# with only the bus law fixed, the bound still bills no node bleed, so every
# future bleed retune moves the run without moving its bound and the deviation
# is a function of a `TODO(calibrate)` constant.  With both fixed the two move
# together, which is the property the round exists to buy.
#
# DEFECT 1 — the bleed was not billed.  `hil_electrical` stamps a bleed
# conductance on every node.  N_BUS's and N_MOT's are billed to the sources
# (N_MOT sits behind a closed MOT_PWR for the whole run); N_OFC's and N_OBT's
# are NOT, because the stack current is referred at v[N_BUS] by
# `ElectricalSim._source_current`; N_CHG's contributes only while FC_CHARGE or
# REGEN is closed.
#
# DEFECT 2 — the bus law was the WRONG DROOP REALIZATION.  `V_BUS_DROOP_V0 -
# K_DROOP_BUS_SHARED*I` is 15.95 - 0.074 I, which is the `--droop measured`
# realization.  Every campaign runs `--droop design`, whose realized bus law
# regresses at 15.865 - 0.3015 I over 345 000 rows of `ems-ftp75-dp`.  A 0.074
# V/A slope against a realized 0.30 V/A under-states the bus sag and therefore
# mis-prices every stage.
#
# THE MAP.  Fitted on a 120-point static probe of the hi-fi engine at
# `--droop design --asymmetry measured`, c_vesc 0.5 mF, substep count PINNED at
# 20, 1500-tick warm-up and 400-tick averaging (the probe procedure is recorded
# in docs/modeling/dp_loss_map_20260902.md).  Solved by Picard iteration inside
# `gen_dp_ems_table.build_demand()`:
#
#   i_motor = p_mech / (ETA_BOOST * V_bus)
#   V_MOT   = (V_bus - RT_V_FWD - RT_R_ON*i_motor) / (1 + RT_R_ON*g_node_other)
#   i_par   = V_bus*g_node_bus + V_MOT*g_node_other
#   I_total = i_motor + i_aux + i_par
#   V_bus   = V0_EFF - (R_FIX + K_G*g_par) * I_total
#   p_dem   = V_bus * I_total
#
# Each coefficient has a MECHANISM, which is why this is a map and not a curve
# fit: V0_EFF is the boost pair's no-load intercept, R_FIX the share-independent
# series resistance of the two switch links and their INA shunts, K_G the
# conversion from the firmware's PARALLEL droop code to ohms, and g_par that
# code.  The two node conductances are `hil_electrical`'s own, imported rather
# than restated.
#
# THE SEPARABILITY ARGUMENT, and it is load-bearing.  `p_dem` must not depend
# on the control, or the DP's stage cost is not separable and the whole solve
# is invalid.  It does not, because THE FIRMWARE HOLDS THE PARALLEL DROOP CODE
# CONSTANT while it trades the split: measured over campaign 20260902_041414,
# g_par = g_fc*g_bt/(g_fc+g_bt) has mean 0.148922 and sigma 2.79e-05 across
# 343 001 Run-state rows of `ems-ftp75-dp` whose individual codes range over
# 0.198-0.518 and 0.209-0.598.  `test_gen_dp_ems_table.py` carries that
# constancy as a TRIPWIRE: if a firmware or governor change ever lets g_par
# move with the share, the map's control-independence is gone and the DP must
# be re-derived, not re-fitted.
#
# ⚠️ STATED APPROXIMATION.  Under `--asymmetry measured` the realized slope is
# not a pure function of g_par: the two mirror-image code pairs 0.22/0.46 and
# 0.46/0.22 share g_par = 0.148824 but realize K = 0.30673 and 0.31215, a
# +/-0.9 % share dependence the map does not represent.  The fit's residual
# over the whole 120-point grid is 3.48 mV rms and 10.3 mV max, which is
# 0.067 % of V_bus.  K_EFF at the firmware-held g_par is 0.308502 V/A against
# the board's regressed 0.3015-0.3057 V/A.
#
# ⚠️ SCOPE.  The map is a STATIC map.  It carries no regen term of its
# own and no charger-node arm.  ⚠️ THE REGEN HALF OF THIS SCOPE NOTE IS
# CLOSED (2026-09-02, the ftp75c round): the DP's demand DOES carry a
# braking credit in the regen era, through `build_demand`'s `eta_regen`
# argument and `tools/regen_power.py`.  It is not part of THIS map,
# because the credit is a pack CURRENT and the map prices BUS losses -
# two different nodes - so the two compose rather than overlap.  The
# charger-node arm below is still deferred.  The charger arm was PROBED and its coefficients hold to
# 2.3e-04 A -- the N_CHG bleed adds `V_CHG*g_node_other` and V_CHG follows
# `V_bus - RT_V_FWD - RT_R_ON*i_chg_in` to 4.8e-06 V -- but it is deliberately
# NOT applied to the charge stage cost in this round.
# THE REASON IS ROUND SCOPE, NOT SEPARABILITY, and the distinction matters
# because the separability argument is the load-bearing one above.  A
# charge-gated term is NOT a separability blocker: the charge control is
# already a column of the DP's control set, so a cost that depends on it is
# priced inside `step_charge()` exactly as the charger's own bus draw already
# is, and the stage cost stays separable.  What defers it is that the term
# belongs with the REGEN term, which is the next round's work, and that
# landing half of a two-term correction is how the two defects above came to
# cancel in the first place.  Its omission understates the cost of a charge
# stage by ~0.26 mA of bus current, which is 0.02 % of a charging stage's
# demand.
DP_BUS_V0_EFF = 15.871722    # V         no-load bus intercept of the boost pair
DP_BUS_R_FIX = 0.017986      # ohm       share-independent series resistance
DP_BUS_K_G = 1.95079         # ohm/unit  parallel droop code -> source resistance
DP_DROOP_G_PAR = 0.148922    # -         the firmware-held parallel droop code

# ── THE SINGLE-SOURCE BUS LAW (2026-09-02, the MPC 0/1 round) ───────────────
# WHAT IT IS FOR.  The MPC gains SINGLE-SOURCE candidates (share 0 and 1),
# which take one channel off the bus through the setpoint latch.  The bus law
# above was fitted TWO-SOURCE: its `g_par` is the PARALLEL droop code
# `g_fc*g_bt/(g_fc+g_bt)`, and with one channel gone that parallel combination
# does not exist.  Planning a single-source stage on the two-source law would
# under-state the droop by about a factor of two and over-state the bus voltage
# by ~0.5 V at 1.6 A.
#
# ⚠️ THESE ARE MPC-ONLY AND ARE DELIBERATELY *NOT* IN THE LOSS MAP.  The map is
# a fingerprinted era key (`DP_FINGERPRINT_OPTIONAL_KEYS`), so adding fields to
# it would move `loss_map_canonical()` and orphan every committed DP table and
# every stored `dp_db` record.  The DP and the SDP do NOT get single-source
# candidates (operator ruling, 2026-09-02), so nothing that consumes the map
# needs these, and keeping them out of it costs nothing.
#
# MEASURED on the hi-fi engine at `--droop design --asymmetry measured`, by
# sweeping the auxiliary load 0.15-1.6 A with the motor idle and regressing
# V_bus against the source total.  The fit is EXACT to the printed precision
# (max residual under 0.005 mV over four points), because the engine solves a
# linear network at steady state.  Probed at THREE droop codes (0.35, 0.50,
# 0.70) to establish that the RATIO is a property of the topology and not of
# the operating point:
#
#     code    K_both     K_fc (ratio)      K_bt (ratio)
#     0.3499  0.35857    0.69775 (1.9459)  0.73764 (2.0572)
#     0.4999  0.50513    0.98258 (1.9452)  1.03955 (2.0580)
#     0.6999  0.70062    1.36249 (1.9447)  1.44225 (2.0585)
#
# The ratios hold to +/-0.03 % across a 2x code range, so the single-source law
# is the two-source law with ONE SCALE FACTOR on its slope and its own no-load
# intercept.  The two ratios are NOT both 2.000 because the channels are not
# identical under `--asymmetry measured`; that asymmetry is the whole 5.8 %
# spread between them, and using a nominal 2.0 for both would misprice the
# BT-only arm by 2.9 %.
DP_BUS_SINGLE_K_SCALE_FC = 1.9453   # -   K_EFF(FC only) / K_EFF(both)
DP_BUS_SINGLE_K_SCALE_BT = 2.0579   # -   K_EFF(BT only) / K_EFF(both)
DP_BUS_SINGLE_V0_FC = 15.87821      # V   no-load intercept, FC only
DP_BUS_SINGLE_V0_BT = 15.86468      # V   no-load intercept, BT only


def single_source_bus_law(loss_map, source_mode):
    """(v0_eff, k_eff) for a source topology.  PURE.

    `source_mode` is "both", "fc" or "bt".  "both" returns the loss map's own
    two-source law unchanged, so a caller that never plans a single-source
    stage is bit-identical to one that predates this function."""
    if loss_map is None:
        raise ValueError("single_source_bus_law needs a loss map")
    k_both = loss_map["r_fix"] + loss_map["k_g"] * loss_map["g_par"]
    if source_mode == "both":
        return float(loss_map["v0_eff"]), float(k_both)
    if source_mode == "fc":
        return DP_BUS_SINGLE_V0_FC, k_both * DP_BUS_SINGLE_K_SCALE_FC
    if source_mode == "bt":
        return DP_BUS_SINGLE_V0_BT, k_both * DP_BUS_SINGLE_K_SCALE_BT
    raise ValueError("source_mode must be 'both', 'fc' or 'bt', got %r"
                     % (source_mode,))
# Picard iterations for the demand solve.  The old two-term model contracted at
# ~0.7 %/step and used 4; the loss map adds two coupled unknowns (V_MOT and
# i_par) and a ~4x steeper bus slope, so it is iterated to convergence instead
# of to a contraction argument.  30 is ~1e-12 on every stage of both tables.
DP_LOSS_MAP_PICARD_ITERS = 30

# The ONE plant configuration the map above was fitted at.  A run in any other
# configuration resolves to `None` = NO MAP, which is the pre-round era.
DP_LOSS_MAP_ELECTRICAL = "hifi"
DP_LOSS_MAP_DROOP_MODE = "design"
DP_LOSS_MAP_ASYMMETRY_MODE = "measured"

#: The map's field names, in the FIXED order the fingerprint serializes them.
DP_LOSS_MAP_KEYS = ("v0_eff", "r_fix", "k_g", "g_par",
                    "g_node_bus", "g_node_other", "rt_v_fwd", "rt_r_on")


def loss_map_for_config(electrical, droop_mode, asymmetry_mode):
    """The DP static-loss map for one plant configuration, or None.

    `None` means NO MAP, and it names the pre-2026-09-02 demand model (motor
    draw plus housekeeping drain, priced on `V_BUS_DROOP_V0 -
    K_DROOP_BUS_SHARED*I`).  It is the answer for:

      * `electrical == "simple"`.  The simple engine has no node network and no
        bleed to bill; its bus law IS `K_DROOP_BUS_*` / `V_BUS_DROOP_V0`, which
        this round deliberately does NOT move.  Pricing a simple-mode run
        against a hi-fi map would bound it with losses its plant never took.
      * any droop or asymmetry mode other than the one the map was fitted at.
        The map's K_EFF is a `--droop design` number; applying it to a
        `--droop measured` run would repeat DEFECT 2 with the sign reversed.

    Returns a plain dict of floats over DP_LOSS_MAP_KEYS.  The two node
    conductances come from `hil_electrical.node_bleed_conductances()` at call
    time, so a monkeypatched bleed era reaches the DP and the plant together."""
    if electrical != DP_LOSS_MAP_ELECTRICAL:
        return None
    if droop_mode != DP_LOSS_MAP_DROOP_MODE:
        return None
    if asymmetry_mode != DP_LOSS_MAP_ASYMMETRY_MODE:
        return None
    g = node_bleed_conductances()
    return {
        "v0_eff": float(DP_BUS_V0_EFF),
        "r_fix": float(DP_BUS_R_FIX),
        "k_g": float(DP_BUS_K_G),
        "g_par": float(DP_DROOP_G_PAR),
        "g_node_bus": float(g[_N_BUS]),
        "g_node_other": float(g[_N_MOT]),
        "rt_v_fwd": float(RT_V_FWD),
        "rt_r_on": float(RT_R_ON),
    }


def plant_loss_map():
    """THE MAP THIS PROCESS'S PLANT RUNS AT, in `dp_loss_map()`'s vocabulary.

    The mirror of `plant_eta_chg()`: it answers for the DEFAULT configuration
    the tools solve against, which is the hi-fi engine at `--droop design
    --asymmetry measured` — the configuration every campaign since 2026-09-01
    has run.  A tool that knows the actual configuration (the suite, the
    report analyzer) must call `loss_map_for_config()` with it instead."""
    return loss_map_for_config(DP_LOSS_MAP_ELECTRICAL, DP_LOSS_MAP_DROOP_MODE,
                               DP_LOSS_MAP_ASYMMETRY_MODE)


def dp_loss_map(meta):
    """The static-loss map a DP table is solved / replayed against.

    THE ERA SENTINEL, in the shape `dp_eta_chg()` established.  An ABSENT
    `loss_map` key means the run, sidecar or table PREDATES the loss map: its
    demand was the two-term model, which is NOT reproducible by any set of
    coefficients.  That era is named `None`.

    Consequences, in the same order `dp_eta_chg()` states them:
      * This is NOT the plant's runtime accounting.  The plant bills its own
        losses through the node network; the map is the DP's REDUCED model of
        that billing.
      * A live SCENARIO declares nothing, so `dp_profile_fingerprint()` hashes
        the sentinel for it, and a generated table agrees with its `dp-replay`
        consumer by construction.  The table's own map is recorded in its
        `# loss_map:` header line, as documentation.
      * Where the sentinel DOES separate two problems is the archived-run path
        in `dp_results_db`, whose era overrides carry the map explicitly."""
    lm = meta.get("loss_map")
    if lm is None:
        return None
    return {k: float(lm[k]) for k in DP_LOSS_MAP_KEYS}


def check_loss_map(loss_map):
    """Validate a loss map and return it NORMALIZED to plain floats, or None.

    The mirror of `charger_power.check_eta_chg()`: every consumer of the map
    validates through ONE function, so a partially-populated dict fails LOUDLY
    at the top of a solve rather than raising a KeyError 300 stages in, or
    worse, silently pricing a stage with a numpy scalar of the wrong dtype."""
    if loss_map is None:
        return None
    if not isinstance(loss_map, dict):
        raise TypeError("loss_map must be a dict over %s or None, got %r"
                        % (list(DP_LOSS_MAP_KEYS), type(loss_map).__name__))
    missing = [k for k in DP_LOSS_MAP_KEYS if k not in loss_map]
    if missing:
        raise ValueError("loss_map is missing %s - build it with "
                         "hil_plant_sim.loss_map_for_config()" % (missing,))
    extra = [k for k in loss_map if k not in DP_LOSS_MAP_KEYS]
    if extra:
        raise ValueError("loss_map carries unknown keys %s; the map's fields "
                         "are exactly %s" % (extra, list(DP_LOSS_MAP_KEYS)))
    out = {}
    for k in DP_LOSS_MAP_KEYS:
        v = float(loss_map[k])
        if not math.isfinite(v):
            raise ValueError("loss_map[%r] is not finite (%r)" % (k, v))
        out[k] = v
    if out["g_node_bus"] < 0.0 or out["g_node_other"] < 0.0:
        raise ValueError("loss_map node conductances must be >= 0, got "
                         "bus %r other %r"
                         % (out["g_node_bus"], out["g_node_other"]))
    if out["v0_eff"] <= 0.0:
        raise ValueError("loss_map v0_eff must be > 0, got %r" % out["v0_eff"])
    return out


def loss_map_canonical(loss_map):
    """The map as ONE canonical string, for fingerprints and table headers.

    Fixed key order, `repr()` of plain floats — the convention
    `dp_profile_fingerprint()` already uses for every other value."""
    if loss_map is None:
        return "none"
    return ",".join("%s=%r" % (k, float(loss_map[k])) for k in DP_LOSS_MAP_KEYS)


def loss_map_from_canonical(text):
    """The inverse of `loss_map_canonical()`: a map dict, or None.

    A generated table records its demand era as a `# loss_map:` header line,
    and a reader that wants to REPRODUCE that table's solve needs the map back
    as a dict.  Kept next to the renderer so the two cannot drift, and routed
    through `check_loss_map()` so a hand-edited header fails loudly."""
    if text is None:
        return None
    text = str(text).strip()
    if text in ("", "none", "None"):
        return None
    out = {}
    for part in text.split(","):
        key, _, val = part.partition("=")
        out[key.strip()] = float(val)
    return check_loss_map(out)


def loss_map_era_label(loss_map):
    """A short printable era name.  ONE text for every refusal and warning."""
    if loss_map is None:
        return ("the LOSS-MAP-FREE demand model (motor draw + drain only, "
                "priced on V_BUS_DROOP_V0 - K_DROOP_BUS_SHARED*I)")
    return ("a static-loss-map demand model (V0_EFF = %g V, K_EFF = %g V/A, "
            "bus bleed %g S, other-node bleed %g S)"
            % (loss_map["v0_eff"],
               loss_map["r_fix"] + loss_map["k_g"] * loss_map["g_par"],
               loss_map["g_node_bus"], loss_map["g_node_other"]))


def dp_chg_ceiling_a(meta):
    """The Ag105 charge-current ceiling a DP table is solved / replayed against.

    ONE resolution of `chg_i_ceiling_a`'s default (E-L1, 2026-09-01), used at
    all THREE sites that need it: gen_dp_ems_table.py's `render_table()` header
    line, its `main()` solve, and DpReplayStrategy.bind_scenario()'s drift
    guard.  A scenario that declares no ceiling gets AG105_I_MAX — the value the
    firmware configures.

    It is a function rather than a bare constant because the resolution takes
    the scenario metadata; the DEFAULT is the shared part, and it is the part
    that already drifted once.  Until 2026-09-01 `render_table()` wrote a 0.0
    default while `main()` solved with AG105_I_MAX for the same absent key, so
    the header said "no charging was available" over a solution in which 2.5 A
    was — and the drift guard, comparing the two, refused the table at startup.
    Three call sites reading one expression cannot reproduce that."""
    v = meta.get("chg_i_ceiling_a")
    return AG105_I_MAX if v is None else float(v)



def dp_profile_fingerprint(scenario, meta):
    """sha256 over the scenario inputs a DP table depends on.

    ONE function, used by tools/gen_dp_ems_table.py when it writes a table and
    by DpReplayStrategy when it loads one — so the generator and the consumer
    cannot disagree about what "the same profile" means.

    Covers the scenario NAME, the metadata keys in DP_FINGERPRINT_META_KEYS,
    and the drain-load constants apply_scenario() applies to this scenario
    (SOC_BAND_DRAIN_*, SOC_LOAD_RAMP_S, I_AUX_A) — retuning the drain changes
    the demand the DP solved against just as surely as moving a profile point
    does, and must invalidate the table too.

    The canonical string is built with repr() of plain floats in a FIXED key
    order, so the digest is stable across runs and platforms."""
    parts = ["scenario=%s" % scenario]
    for key in DP_FINGERPRINT_META_KEYS:
        val = meta.get(key)
        if key in DP_FINGERPRINT_OPTIONAL_KEYS and _dp_fp_resolve(key, meta) is None:
            # THE OLD ERA IS THE ABSENCE OF THE TERM (orchestrator ruling,
            # 2026-09-02), the same convention `dp_results_db`'s
            # OPTIONAL_KEY_FIELDS already uses. Hashing `eta_chg=None` as a
            # LINE would have moved every pre-existing fingerprint — every
            # committed table, and all 16 stored dp_db records — for a key
            # whose value had not changed. Omitting it instead leaves an
            # old-era digest exactly where it was, while a post-era run (whose
            # SIDECAR carries eta_chg = 0.88) still fingerprints differently
            # from a pre-era one, which is the separation the key was added
            # for.
            continue
        if key == "loss_map":
            # ERA SENTINEL, resolved through `dp_loss_map()` and rendered by
            # `loss_map_canonical()` so the digest carries the COEFFICIENTS and
            # not a dict's repr (whose key order is an implementation detail).
            val = loss_map_canonical(dp_loss_map(meta))
        if key == "eta_chg":
            # ERA SENTINEL, resolved through the one function that owns the
            # convention (see dp_eta_chg): an ABSENT key hashes as `None`, the
            # 1:1 current-transfer era, and a declared value hashes as itself.
            # A live scenario declares nothing, so the generator and the
            # `dp-replay` consumer agree on `None` by construction; what the
            # key separates is an ARCHIVED run's era, which its sidecar
            # carries explicitly.
            val = dp_eta_chg(meta)
        if key == "drag":
            # ERA SENTINEL, resolved through `dp_drag_mode()`: an absent key
            # and an explicit "rig" are the SAME statement and both omit the
            # line above, so a rig table's digest is exactly its pre-key value.
            # A compensated mode hashes as its own STRING - it is a named
            # profile, not a number.
            val = dp_drag_mode(meta)
        if key == "eta_regen":
            val = dp_eta_regen(meta)
        if key == "ems_v_profile" and val:
            val = [(float(a), float(b)) for a, b in val]
        elif key in ("loss_map", "drag"):
            pass                 # already canonical text, not a scalar
        elif val is not None:
            val = float(val)
        parts.append("%s=%r" % (key, val))
    for name, val in (("I_AUX_A", I_AUX_A),
                      ("SOC_LOAD_RAMP_S", SOC_LOAD_RAMP_S),
                      ("SOC_BAND_DRAIN_LOAD_A", SOC_BAND_DRAIN_LOAD_A),
                      ("SOC_BAND_DRAIN_START_S", SOC_BAND_DRAIN_START_S),
                      ("SOC_BAND_DRAIN_END_S", SOC_BAND_DRAIN_END_S)):
        parts.append("%s=%r" % (name, float(val)))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def load_dp_table(path):
    """Parse a generated DP table.  Returns (meta_dict, times, shares, goals).

    Format: '#'-comment metadata lines of the form '# key: value', then a
    't,power_share_setpoint,charge_goal' header and the rows.  Raises
    ValueError with a pointed message on anything malformed — this runs at
    startup, where a loud failure is free."""
    meta = {}
    times, shares, goals = [], [], []
    header_seen = False
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                body = line[1:].strip()
                if ":" in body:
                    k, _, v = body.partition(":")
                    k = k.strip()
                    # Only the first occurrence wins, so a banner line that
                    # happens to contain a colon cannot shadow a real key.
                    if k and k not in meta:
                        meta[k] = v.strip()
                continue
            if not header_seen:
                if line.replace(" ", "") != "t,power_share_setpoint,charge_goal":
                    raise ValueError(
                        "%s:%d: expected the column header "
                        "'t,power_share_setpoint,charge_goal', got %r"
                        % (path, lineno, line))
                header_seen = True
                continue
            cols = line.split(",")
            if len(cols) != 3:
                raise ValueError("%s:%d: expected 3 columns, got %d"
                                 % (path, lineno, len(cols)))
            try:
                t, s, g = (float(cols[0]), float(cols[1]), float(cols[2]))
            except ValueError:
                raise ValueError("%s:%d: non-numeric row %r"
                                 % (path, lineno, line))
            if times and t <= times[-1]:
                raise ValueError("%s:%d: table times must strictly increase "
                                 "(%r after %r)" % (path, lineno, t, times[-1]))
            times.append(t)
            shares.append(s)
            goals.append(g)
    if not header_seen:
        raise ValueError("%s: no column header found — is this a DP table?" % path)
    if not times:
        raise ValueError("%s: table has a header but no rows" % path)
    return meta, times, shares, goals


def dp_table_digests(path):
    """(file_sha256, table_sha256) for a generated DP table.

    TWO digests, for the same reason SdpStrategy records two (file_sha256 +
    policy_sha256):

      file_sha256   byte identity of the artifact ON DISK, AS CHECKED OUT.
                    Moves whenever ANY byte moves — including a regenerated
                    banner, a reworded comment or a re-emitted `command:` line —
                    so it answers "is this the same file?" and nothing more.
                    ⚠️ DI-LOW-1: it is CHECKOUT-SENSITIVE. It is reproducible
                    across machines only because tools/dp_tables/.gitattributes
                    pins `*.csv -text`, so git hands every checkout LF endings;
                    remove that pin (or copy the table through a CRLF-rewriting
                    tool) and this digest moves without the table changing.
                    `table_sha256` is the checkout-INVARIANT identity and is the
                    one to compare across machines and campaigns.
      table_sha256  the SETPOINT LAW: sha256 over the DATA ROWS ALONE, with the
                    '#' metadata block and the column header excluded and line
                    endings normalised to '\\n'.  This is the DP table's
                    equivalent of the SDP's `policy_sha256` — it is STABLE
                    across a regeneration that changed only the header, and it
                    is the digest to compare ACROSS CAMPAIGNS when asking
                    whether two runs were commanded by the same table.

    Both are computed here rather than in load_dp_table() so the parser stays a
    parser: a caller that only wants the setpoints does not pay a second read.
    Raises OSError for a missing/unreadable file, like every other loader in
    this module — bind_scenario() already converts that to a startup refusal."""
    h_file = hashlib.sha256()
    h_rows = hashlib.sha256()
    with open(path, "rb") as fh:
        raw = fh.read()
    h_file.update(raw)
    # DI-LOW-2: the column header is excluded POSITIONALLY — the FIRST non-'#',
    # non-blank line, whatever it says — rather than by matching its literal
    # text. The literal match ("t,power_share_setpoint,charge_goal") silently
    # stopped excluding anything the moment a generator renamed a column, which
    # would have folded a header string into the SETPOINT-LAW digest and moved
    # it without a single setpoint changing. The generator always emits exactly
    # one header line ahead of the data, so position is the reliable rule.
    header_seen = False
    for line in raw.decode("utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if not header_seen:
            header_seen = True
            continue
        h_rows.update((s + "\n").encode("utf-8"))
    return h_file.hexdigest(), h_rows.hexdigest()


class DpReplayStrategy:
    """dp-replay — NON-CAUSAL / OFFLINE-OPTIMAL BENCHMARK.  Read the banner above.

    name       : dp-replay
    intent     : play back tools/dp_tables/dp_ems_table_<scenario>.csv, produced
                 by tools/gen_dp_ems_table.py's backward dynamic program, so a
                 campaign can measure how far a CAUSAL strategy sits from the
                 offline optimum on the same profile.  Compare on three axes:
                 h2_cum_g, delta_soc, and share tracking — and only ever read
                 the first two as a PAIR (any strategy burns less hydrogen by
                 discharging the pack harder).
    fields     : mode_cmd (SAFE -> HYBRID at EMS_RUN_ENTRY_S, back to SAFE at
                 the table's own run_exit_s — the same entry/exit shape
                 hold-5050 uses so the run closes Run -> Finish -> Idle),
                 v_setpoint (the scenario's `ems_v_profile`, exactly as
                 hold-5050 takes it), power_share_setpoint and charge_goal
                 (ZERO-ORDER HOLD lookup in the table at t).
    feedback   : `t` and `v_profile` only.  NOTHING else — see the banner.
    """

    def __init__(self, table_dir=None):
        # NO I/O here: EMS_STRATEGIES is built at import time and constructing
        # the registry must not touch the disk (or fail because a table has not
        # been generated yet).  Loading happens in bind_scenario().
        self.table_dir = table_dir or DP_TABLE_DIR
        self.reset()

    def reset(self):
        self.scenario = None
        self.path = None
        self.meta = {}
        self.times = []
        self.shares = []
        self.goals = []
        self.run_exit_s = None
        self.last_idx = None
        # Filled by bind_scenario(); None for a strategy that was only ever
        # called directly (a test, a probe), which is also how main() decides
        # whether there is anything to write into the meta sidecar.  Same
        # contract as SdpStrategy.provenance.
        self.provenance = None

    # ── startup binding / refusal ────────────────────────────────────────────
    #
    # M1/M2 (review, 2026-08-31): WHAT THIS CHECKS, AND WHY THERE ARE FOUR
    # CLASSES OF CHECK RATHER THAN ONE FINGERPRINT.
    #
    # `profile_fingerprint` (D9) covers the DEMAND — the scenario name, its
    # speed profile and its drain constants.  It is deliberately narrow, and
    # three other things can invalidate a table without moving it:
    #
    #   (a) THE ACCOUNTING (M1).  `--charger-accounting` selects which of the
    #       two hydrogen totals the DP MINIMISED, and it must match the
    #       electrical engine the table is replayed under (generator D11).  A
    #       `physical` table replayed under `--electrical simple` is not a
    #       lower bound at all — the causal `soc-band` strategy measurably
    #       BEATS it on the logged column, because simple mode does not stamp
    #       the charger's draw on the bus and the metric gives pack charge away
    #       free.  A "benchmark" the referent beats is worse than none, and it
    #       fails SILENTLY: the run is clean, the numbers are plausible, and
    #       the conclusion is backwards.  So the mode is passed in and checked.
    #   (b) MODEL CONSTANTS (M2).  The generator solves against imported
    #       simulator constants; the header records each one it used.  If a
    #       constant is retuned here and the table is not regenerated, the DP
    #       is the optimum of a DIFFERENT plant than the one being run.
    #   (c) RUN-TIME ARGUMENTS (M2).  soc0 and capacity are CLI, not constants,
    #       and the DP's whole trajectory is conditioned on them.  A `--soc0
    #       0.5` run against a table solved at 0.7 is a meaningless benchmark.
    #
    # All of them REFUSE rather than warn, and every message names WHICH value
    # drifted and the exact regeneration command — the failure mode being
    # avoided is a run that looks fine and means nothing.
    def bind_scenario(self, scenario, meta, electrical_mode=None,
                      args=None, droop_mode=None,
                      asymmetry_mode=None, drag_mode=None):
        """Load and validate this scenario's table.  Raises ValueError to refuse.

        main() calls this before the run starts (the generic `bind_scenario`
        hook), so every failure mode surfaces as a startup refusal rather than a
        mid-run crash or, worse, a silently wrong trace.

        `electrical_mode` is the RESOLVED engine ("simple" / "hifi"), not the
        requested one, `droop_mode` and `asymmetry_mode` the RESOLVED plant
        modes (a scenario may override the CLI default for either), and `args`
        the parsed CLI namespace.  All four are optional so a caller that only
        wants the profile check (a test, a future tool) keeps working; main()
        passes all four.

        A caller that omits the two mode arguments is treated as asking about
        THE SHIPPED CONFIGURATION (`plant_loss_map()`), not as asking for the
        check to be skipped: an omitted mode is missing information, and the
        era guard's whole purpose is that missing information must not read as
        agreement.  See block (0b)."""
        path = os.path.join(self.table_dir, DP_TABLE_NAME % scenario)
        if not os.path.isfile(path):
            raise ValueError(
                "the `dp-replay` strategy needs a generated DP table for "
                "scenario %r and none exists at %s.\n"
                "  Generate it first (numpy is required, so use miniforge — "
                "`.venv_hil` is stdlib-only):\n"
                "      C:/Users/ricky/miniforge3/python.exe "
                "tools/gen_dp_ems_table.py --scenario %s"
                % (scenario, path, scenario))
        table_meta, times, shares, goals = load_dp_table(path)

        # The regeneration recipe, hoisted above the first check that quotes it
        # (the charger-era check, block (0) below).
        regen = ("      C:/Users/ricky/miniforge3/python.exe "
                 "tools/gen_dp_ems_table.py --scenario %s --force" % scenario)

        # ── (0) THE CHARGER ERA (2026-09-02) ────────────────────────────────
        # FIRST, BEFORE THE FINGERPRINT, deliberately.  A live scenario declares
        # no `eta_chg` (see dp_eta_chg()), so `dp_profile_fingerprint()` hashes
        # the sentinel None for BOTH eras and cannot separate them: an old-era
        # table and a new-era one for the same scenario carry the SAME
        # fingerprint whenever nothing else moved.  The table's own
        # `# eta_chg:` header line is the only record of which charger it was
        # solved against, and a DP bound solved against a charger the run does
        # not have is not a bound on this run at all — under the old model the
        # Ag105's bus draw is billed ~1.9x too dearly, so the table's charge
        # stages are the optimum of a different problem.
        # An ABSENT header line means the OLD era (the operator's 2026-09-01
        # sentinel ruling), which is why this cannot be a soft check: "the table
        # does not say" and "the table says 1:1" are the same statement.
        want_eta = plant_eta_chg()
        got_eta = dp_eta_chg(table_meta)
        eta_same = (want_eta is None and got_eta is None) or (
            want_eta is not None and got_eta is not None
            and abs(want_eta - got_eta) <= 1e-12 * max(1.0, abs(want_eta)))
        if not eta_same:
            raise ValueError(
                "DP table %s was solved against %s, but this run's plant bills "
                "the charger as %s.\n"
                "  table  eta_chg=%s%s\n"
                "  plant  eta_chg=%s   [hil_electrical.ETA_CHG]\n"
                "  The two charger models are not related by any efficiency "
                "value (one bills the BUS voltage, the other the PACK voltage "
                "over eta), so the table's charge stages minimise a DIFFERENT "
                "demand than this run will log and replaying it bounds "
                "nothing. NOTE the profile fingerprint CANNOT catch this: a "
                "live scenario declares no `eta_chg`, so both eras hash the "
                "same sentinel.\n"
                "  Regenerate for this era:\n%s%s"
                % (path, eta_chg_era_label(got_eta),
                   eta_chg_era_label(want_eta), got_eta,
                   "" if "eta_chg" in table_meta
                   else " (no `# eta_chg:` header line — a table that predates "
                        "the charger-efficiency model)",
                   want_eta, regen,
                   "" if want_eta is None
                   else " --eta-chg %g" % want_eta))

        # ── (0b) THE DEMAND-MODEL ERA (2026-09-02, the DP-bound round) ─────
        # SECOND, AND STILL BEFORE THE FINGERPRINT, for exactly the reason
        # block (0) is: a live scenario declares no `loss_map` either, so
        # `dp_profile_fingerprint()` hashes the sentinel None for BOTH eras and
        # the shipped loss-map tables therefore still carry their PRE-round
        # digests (`ems-dp-replay` 02683031..., `ems-ftp75-dp` 403c5e71...).
        # The fingerprint cannot see this and is not intended to.
        #
        # WHAT GOES WRONG WITHOUT THE GUARD, concretely.  `--loss-map` defaults
        # to `none`, so a regeneration for ANY unrelated reason -- a retuned
        # drain, a moved run-exit, a fresh checkout -- silently produces a
        # loss-map-FREE table that binds clean against a loss-map-era plant.
        # The bound is then priced on a demand model that bills no node bleed
        # and solves the `--droop measured` bus law, which is the exact defect
        # this round removed: the run-versus-table deviation on `ems-ftp75-dp`
        # returns to +4.35 %, and it returns INVISIBLY, because every other
        # check passes.
        # An ABSENT `# loss_map:` header line means the pre-round era, so this
        # cannot be a soft check either: "the table does not say" and "the
        # table says loss-map-free" are the same statement.
        want_lm = (plant_loss_map() if electrical_mode is None
                   else loss_map_for_config(
                       electrical_mode,
                       droop_mode if droop_mode is not None
                       else DP_LOSS_MAP_DROOP_MODE,
                       asymmetry_mode if asymmetry_mode is not None
                       else DP_LOSS_MAP_ASYMMETRY_MODE))
        got_lm = loss_map_from_canonical(table_meta.get("loss_map"))
        if want_lm != got_lm:
            raise ValueError(
                "DP table %s was solved against %s, but this run's demand "
                "model is %s.\n"
                "  table  loss_map=%s%s\n"
                "  run    loss_map=%s\n"
                "  The two demand models differ by the plant's STATIC LOSSES "
                "(the per-node bleed on N_BUS and N_MOT) and by which droop "
                "realization the bus law carries, so the table's stage costs "
                "minimise a DIFFERENT demand than this run will draw and "
                "replaying it bounds nothing. Measured when the map landed: "
                "+4.35 %% on `ems-ftp75-dp` and -0.20 %% on `ems-dp-replay`. "
                "NOTE the profile fingerprint CANNOT catch this: a live "
                "scenario declares no `loss_map`, so both eras hash the same "
                "sentinel.\n"
                "  Regenerate for this era:\n%s%s"
                % (path, loss_map_era_label(got_lm),
                   loss_map_era_label(want_lm),
                   loss_map_canonical(got_lm),
                   "" if "loss_map" in table_meta
                   else " (no `# loss_map:` header line - a table that "
                        "predates the static-loss map)",
                   loss_map_canonical(want_lm), regen,
                   "" if want_lm is None else " --loss-map plant"))

        # ── (0c) THE ROAD-LOAD AND REGEN ERAS (2026-09-02, the ftp75c round) ─
        # THIRD, AND STILL BEFORE THE FINGERPRINT, and for ONE of the two keys
        # the fingerprint genuinely cannot help.
        #
        # `drag` IS a scenario key, so the fingerprint separates a compensated
        # table from a rig table by itself - but ONLY when the scenario declares
        # it.  `--drag` OVERRIDES a scenario key, and an operator running an
        # `ems-ftp75c-*` leg at `--drag rig` as a zero-regen control would
        # otherwise replay a table solved against 4.5x less tractive demand
        # while every other check passed.  The guard compares the table against
        # the mode the run WILL ACTUALLY APPLY, which is the only claim worth
        # making.
        #
        # `eta_regen` is a pure era sentinel like `eta_chg`: a live scenario
        # declares none, so both eras hash the same and the table's own
        # `# eta_regen:` header line is the only record.  A table solved WITHOUT
        # the credit must supply with hydrogen the SoC a regen-bearing run gets
        # back from braking, so its total is INFLATED and the run's deviation
        # against it is correspondingly optimistic - the divergence this round
        # closes, and re-opening it silently is worse than never having closed
        # it.  Under the rig profile `plant_eta_regen()` returns the sentinel
        # (the credit is 0.001 J of 30.8 J - see that function), so every
        # committed rig-drag table binds clean.
        want_drag = plant_drag_mode(drag_mode)
        got_drag = dp_drag_mode(table_meta)
        want_er = plant_eta_regen(drag_mode)
        got_er = dp_eta_regen(table_meta)
        er_same = (want_er is None and got_er is None) or (
            want_er is not None and got_er is not None
            and abs(want_er - got_er) <= 1e-12 * max(1.0, abs(want_er)))
        if want_drag != got_drag or not er_same:
            raise ValueError(
                "DP table %s was solved against %s with %s, but this run's "
                "plant carries %s with %s.\n"
                "  table  drag=%r  eta_regen=%s%s\n"
                "  run    drag=%r  eta_regen=%s\n"
                "  The road-load profile sets the TRACTIVE DEMAND (the "
                "compensated profiles cut the peak bus current by roughly "
                "4.5x) and the regen era sets what a braking stage is "
                "CREDITED, so a mismatch on either means the table's stage "
                "costs minimise a different problem and replaying it bounds "
                "nothing. NOTE the profile fingerprint cannot catch the "
                "`eta_regen` half at all, and catches the `drag` half only "
                "when the scenario declares the key - `--drag` overrides it.\n"
                "  Regenerate for this era:\n%s%s%s"
                % (path, drag_era_label(got_drag or DRAG_MODE_RIG),
                   regen_power.era_label(got_er),
                   drag_era_label(want_drag or DRAG_MODE_RIG),
                   regen_power.era_label(want_er),
                   got_drag, got_er,
                   "" if "eta_regen" in table_meta
                   else " (no `# eta_regen:` header line - a table that "
                        "predates the regen demand term)",
                   want_drag, want_er, regen,
                   "" if want_drag is None else " --drag %s" % want_drag,
                   "" if want_er is None else " --eta-regen %g" % want_er))

        want = dp_profile_fingerprint(scenario, meta)
        got = table_meta.get("profile_fingerprint")
        if got != want:
            raise ValueError(
                "DP table %s was generated for a DIFFERENT profile than the "
                "scenario now being run.\n"
                "  table  scenario=%r fingerprint=%s\n"
                "  active scenario=%r fingerprint=%s\n"
                "  A DP table is a NON-CAUSAL solution of ONE specific drive "
                "cycle and auxiliary load; replaying it against another "
                "profile is not a benchmark, it is noise. Regenerate:\n"
                "      C:/Users/ricky/miniforge3/python.exe "
                "tools/gen_dp_ems_table.py --scenario %s --force"
                % (path, table_meta.get("scenario"), got, scenario, want,
                   scenario))

        # ── (a) M1: accounting vs the RESOLVED electrical engine ─────────────
        if electrical_mode is not None:
            want_acc = "physical" if electrical_mode == "hifi" else "simple"
            got_acc = table_meta.get("charger_accounting")
            if got_acc != want_acc:
                raise ValueError(
                    "DP table %s was solved with --charger-accounting %r, but "
                    "this run's electrical engine is %r, which needs %r.\n"
                    "  The two hydrogen accountings differ by whether the "
                    "Ag105's bus draw is charged to the fuel cell; hi-fi "
                    "stamps it and simple does not. A table solved for the "
                    "OTHER one is not a lower bound on the metric this run "
                    "will log - under the mismatched pairing the causal "
                    "`soc-band` strategy beats it, which ranks nothing.\n"
                    "  Regenerate for this engine:\n"
                    "%s --charger-accounting %s"
                    % (path, got_acc, electrical_mode, want_acc,
                       regen, want_acc))

        # ── (b)/(c) M2: header-recorded values vs the live ones ──────────────
        if args is not None:
            # (name in header, live value, kind).  FLOATS are compared with a
            # tiny relative tolerance: the header round-trips through %r/%.9g
            # text, so an exact == would fail on formatting alone.
            checks = [
                ("soc0", float(args.soc0), "run argument --soc0"),
                ("capacity_ah", float(args.capacity_ah),
                 "run argument --capacity-ah"),
                ("chg_ceiling_a", dp_chg_ceiling_a(meta),
                 "scenario constant chg_i_ceiling_a"),
                ("eta_boost", float(ETA_BOOST), "model constant ETA_BOOST"),
                ("gfc_dc_gain_gps_per_w", float(H2_GFC_DC_GAIN_GPS_PER_W),
                 "model constant H2_GFC_DC_GAIN_GPS_PER_W"),
                # NOT CHECKED: `limit_i_fc_max_a`.  The review asked for it,
                # and there is nothing here to check it against — 1.4 A is a
                # FIRMWARE limit that gen_dp_ems_table.py mirrors as its own
                # module constant; hil_plant_sim has no copy, and minting one
                # would both duplicate the firmware value a third time and move
                # `constants_hash` for a value the simulator never uses.  The
                # generator's literal is the single record of it.
                # ⚠️ THE DP'S CHARGE SHARE IS ITS GRID'S TOP, NOT THE
                # soc-band SPAN (2026-09-02, the band widening).  This used to
                # read `SOC_BAND_SHARE_NOMINAL + SOC_BAND_SHARE_SPAN` = 0.75,
                # which happened to equal `gen_dp_ems_table.DP_SHARE_MAX` while
                # the DP grid was the soc-band span.  It is no longer the same
                # quantity: the grid spans the firmware band and
                # `DP_CHARGE_SHARE` follows `DP_SHARE_MAX` = 0.85.  Comparing
                # against the span refused every freshly generated table.  The
                # live value is `SOC_BAND_SHARE_MAX`, which is the band's top
                # and the same constant the generator's grid is built from.
                ("charge_share_value",
                 float(SOC_BAND_SHARE_MAX),
                 "DP charge-stage share (= DP_SHARE_MAX = SOC_BAND_SHARE_MAX, "
                 "the top of the firmware command band)"),
                # RESOLVED per-scenario value, not the bare model constant: a
                # scenario may override the Run exit with `ems_run_exit_s`
                # (2026-08-31), and the DP's own stage grid is solved against
                # whatever the run will actually use. Comparing against the
                # constant would pass a table solved for a DIFFERENT mission
                # length on any scenario that declares an override.
                ("run_exit_s",
                 float(SOC_BAND_RUN_EXIT_S if meta.get("ems_run_exit_s") is None
                       else meta["ems_run_exit_s"]),
                 "scenario key `ems_run_exit_s` (default: model constant "
                 "SOC_BAND_RUN_EXIT_S)"),
                # Added by render_table() in the same review round: these three
                # shape the DP's control grid and its charge mask, so a retune
                # of any of them invalidates a table that says nothing about it.
                ("share_span", float(SOC_BAND_SHARE_SPAN),
                 "model constant SOC_BAND_SHARE_SPAN"),
                ("cruise_slope_max", float(SOC_BAND_CRUISE_SLOPE_MAX),
                 "model constant SOC_BAND_CRUISE_SLOPE_MAX"),
                ("cruise_min_mps", float(SOC_BAND_CRUISE_MIN_MPS),
                 "model constant SOC_BAND_CRUISE_MIN_MPS"),
            ]
            # ── THE REGEN-ERA CONSTANTS (2026-09-02) ────────────────────────
            # `gen_dp_ems_table.py` pre-committed to this in 2026-09-01: "If a
            # future generator ever gives the demand model a regen term, BOTH
            # [ETA_REGEN and VESC_REGEN_I_MAX_A] must move into this header and
            # into the guard."  This is the guard half.  Appended CONDITIONALLY,
            # because in the pre-regen era neither constant enters the solve and
            # demanding the lines would refuse every committed table.
            if want_er is not None:
                checks.append(
                    ("eta_regen", float(ETA_REGEN), "model constant ETA_REGEN"))
                checks.append(
                    ("vesc_regen_i_max_a", float(VESC_REGEN_I_MAX_A),
                     "model constant VESC_REGEN_I_MAX_A"))
                checks.append(
                    ("drag_k_air", float(drag_k_air(want_drag)),
                     "resolved road-load coefficient (--drag %s)" % want_drag))
            drift = []
            for key, live, what in checks:
                raw = table_meta.get(key)
                if raw is None:
                    # An OLDER table predating this header line. Refuse rather
                    # than skip: "the table does not record it" is exactly the
                    # state in which a drift is invisible.
                    drift.append("  %-22s table: (absent - table predates this "
                                 "check)  live: %r   [%s]" % (key, live, what))
                    continue
                try:
                    tv = float(raw)
                except ValueError:
                    drift.append("  %-22s table: %r (unparseable)  live: %r   "
                                 "[%s]" % (key, raw, live, what))
                    continue
                scale = max(abs(tv), abs(live), 1e-30)
                if abs(tv - live) / scale > 1e-9:
                    drift.append("  %-22s table: %.12g   live: %.12g   [%s]"
                                 % (key, tv, live, what))
            if drift:
                raise ValueError(
                    "DP table %s was solved against values that no longer "
                    "match this run.  The table is the optimum of a DIFFERENT "
                    "problem, so replaying it ranks nothing:\n%s\n"
                    "  Regenerate (and pass --soc0/--capacity-ah matching the "
                    "run if those are what drifted):\n%s"
                    % (path, "\n".join(drift), regen))

        self.scenario = scenario
        self.path = path
        self.meta = table_meta
        self.times = times
        self.shares = shares
        self.goals = goals
        try:
            self.run_exit_s = float(table_meta["run_exit_s"])
        except (KeyError, ValueError):
            raise ValueError("DP table %s carries no usable `run_exit_s` "
                             "metadata line" % path)
        # ── MED (2026-08-31 ledger fix queue): WHICH TABLE DROVE THIS RUN ────
        # PROVENANCE ASYMMETRY, closed.  `ems-sdp` runs record their artifact in
        # the CSV's meta sidecar (`config.sdp_policy`) and `ems-dp-replay` runs
        # recorded NOTHING — campaign 20260831_191509 could not verify the DP
        # table's sha from the report folder at all.  The checks above already
        # REFUSE a mismatched table, but they compare the table against the LIVE
        # values; they cannot tell a later reader WHICH table passed, and a
        # regenerated table changes every command in the run while leaving
        # `constants_hash` (module constants only) and the whole rest of the
        # sidecar identical.
        #
        # WHAT IS RECORDED AND WHY:
        #   path/file_sha256/table_sha256  identity — see dp_table_digests().
        #   profile_fingerprint            the D9 demand fingerprint the binder
        #                                  matched.  Recorded because it is the
        #                                  one field that names WHICH profile
        #                                  the table is an optimum OF.
        #   charger_accounting             the M1 axis: which of the two
        #                                  hydrogen totals the DP minimised, and
        #                                  therefore which electrical engine the
        #                                  numbers are a bound for.
        #   command                        the generator invocation, verbatim —
        #                                  the regeneration recipe, so a reader
        #                                  can reproduce the artifact without
        #                                  reverse-engineering the CLI from the
        #                                  other fields.
        #   n_rows/stage_dt_s/run_exit_s   the stage grid, i.e. the resolution
        #                                  the benchmark was solved at.
        # Header values are recorded AS TEXT, exactly as the generator wrote
        # them: this is a provenance record of the file, not a re-parse of it,
        # and a float round-trip here would make the sidecar disagree with the
        # artifact it is describing.  There is no `generated_utc` — the DP
        # generator does not emit one (unlike the SDP solver); `command` plus
        # the two digests are what the file offers.
        file_sha, table_sha = dp_table_digests(path)
        self.provenance = {
            "path": path,
            "file_sha256": file_sha,
            "table_sha256": table_sha,
            "table_sha256_recipe":
                "sha256 of the CSV data rows only ('#' metadata and the column "
                "header excluded, line endings normalised to \\n)",
            "scenario": table_meta.get("scenario"),
            "profile_fingerprint": table_meta.get("profile_fingerprint"),
            "charger_accounting": table_meta.get("charger_accounting"),
            # THE CHARGER ERA the table was solved in (2026-09-02). Recorded
            # because the profile fingerprint cannot carry it (block (0)
            # above): without this field a report reader comparing two
            # campaigns' DP bounds has no way to tell that one of them priced
            # the Ag105 under the 1:1 model.
            "eta_chg": dp_eta_chg(table_meta),
            "command": table_meta.get("command"),
            "n_rows": len(times),
            "stage_dt_s": table_meta.get("stage_dt_s"),
            "run_exit_s": table_meta.get("run_exit_s"),
        }
        print("[hil] DP table: %s (%d stages, stage_dt %s s, run exit %s s, "
              "accounting %s)"
              % (path, len(times), table_meta.get("stage_dt_s", "?"),
                 table_meta.get("run_exit_s", "?"),
                 table_meta.get("charger_accounting", "?")))
        print("[hil]   table sha256 %s (the SETPOINT LAW; stable across a "
              "regeneration that changed only the header), file sha256 %s"
              % (table_sha, file_sha[:16] + "…"))
        return self

    # ── ZOH lookup ───────────────────────────────────────────────────────────
    def lookup(self, t):
        """(share, charge_goal) held from the last table row at or before t.

        bisect on the times list rather than dividing by an assumed stage
        length: the table's spacing is metadata, not a contract, and a
        generator run with a different --stage-dt must still play back."""
        i = bisect.bisect_right(self.times, t) - 1
        if i < 0:
            i = 0                       # before the first row: hold row 0
        self.last_idx = i
        return self.shares[i], self.goals[i]

    def __call__(self, t, fb):
        if self.path is None:
            raise RuntimeError(
                "the `dp-replay` strategy was called without a bound table. "
                "It is a NON-CAUSAL playback of a scenario-specific DP "
                "solution and has no meaningful default; bind_scenario() must "
                "run first (main() does this at startup).")
        v_sp = fb.get("v_profile")
        if v_sp is None:
            v_sp = EMS_DEFAULT_CRUISE_MPS
        share, goal = self.lookup(t)
        in_run = EMS_RUN_ENTRY_S <= t < self.run_exit_s
        return {
            "mode_cmd": MODE_HYBRID if in_run else MODE_SAFE,
            "power_share_setpoint": share,
            # Outside the Run window nothing may be commanded onto the charger
            # path — chargingControl() only runs in State 2, so leaving the
            # intent asserted across the Run exit would be a command the
            # firmware silently ignores (soc-band's reasoning, verbatim).
            "charge_goal": goal if in_run else 0.0,
            "v_setpoint": v_sp,
        }


# One instance, registered below.  Construction does NO I/O — see __init__.
ems_dp_replay = DpReplayStrategy()


# ── sdp-v2 / sdp-v3: the ONLINE stochastic-DP policy (causal, state-feedback)
#
# ⚠️ TWO REGISTERED INSTANCES OF ONE CLASS since 2026-09-01.  Everything below
# describes the MECHANISM and is true of both; what differs is the baked
# artifact and the role — `sdp-v3` is the calibrated BENCHMARK (frontier-scored)
# and `sdp-v2` is the byte-frozen DYNAMICS DEMONSTRATION.  The block at
# SDP_POLICY_FILE_V2/V3 has that split, and EMS_STRATEGY_META carries the roles.
# Where the prose below says "sdp-v2" it is quoting a v2-era measurement; the
# per-artifact differences are called out at each such site.
#
# ⚠️ SIM-ONLY STRATEGY — NOT PORTABLE TO THE REAL PI AS WRITTEN, for exactly
# `soc-band`'s reason: it closes on `fb["soc"]`, which is PLANT TRUTH from
# BatterySource's coulomb count and is deliberately NOT in
# FB_TELEMETRY_EQUIV_KEYS (the real 2S pack has no SoC output, and v4 telemetry
# carries no SoC field).  Its OTHER input — bus power from `V_bus`, `I_fc` and
# `I_batt` — IS telemetry-equivalent.  The portable path is the same one named
# above the SocBandStrategy: a V_batt-based SoC ESTIMATOR on the Pi feeding this
# same lookup unchanged.  That estimator is FUTURE WORK and does not exist here.
#
# WHAT IT IS, AND HOW IT DIFFERS FROM `dp-replay`.  `dp-replay` plays a table
# indexed by TIME, computed with full foreknowledge of ONE cycle; it is a
# non-causal lower-bound reference and is meaningless on any other profile.
# THIS strategy plays a table indexed by STATE — (SoC, demand bin) — computed
# offline by tools/sdp_ems_solver.py over a stochastic demand model.  The
# offline solve is not causal, but the RESULTING POLICY IS: at run time it reads
# only the present state, has no clock-indexed schedule, and is therefore
# defined on any profile.  That is the whole point of carrying it alongside the
# other two: hold-5050 (trivial) < soc-band (causal heuristic) <= sdp-v2 (causal
# optimal-by-construction) <= dp-replay (non-causal bound).
#
# ── DESIGN DECISION: SoC0-RELATIVE REGULATION (read this before comparing) ───
# The baked policy regulates around `soc.target` (0.6 — the SDP study's own
# target, SDP_EnergyManagement2.m:56 `SOC_penalty = alpha*abs(SOC_next - 0.6)`),
# while every EMS scenario in this suite starts at --soc0 0.7.  Applied
# absolutely, the policy would spend the whole run trying to WALK THE PACK DOWN
# 0.10 SoC — an operating mode nothing else in the suite is doing, and one that
# makes an h2_cum_g comparison against soc-band meaningless (a strategy that
# deliberately discharges burns less hydrogen; see the "read it WITH delta_soc"
# rule everywhere in this file).
#
# So the SoC axis is SHIFTED, not the policy: on the first call the strategy
# CAPTURES soc0 exactly as SocBandStrategy captures its reference, and thereafter
# looks the table up at
#     soc_rel = soc_target + (soc - soc0),  clamped to [grid_min, grid_max]
# i.e. the policy charge-sustains around WHERE THIS RUN STARTED.  Consequences,
# stated rather than buried:
#   * `ems-sdp`, `ems-soc-band` and `ems-dp-replay` are three-way comparable on
#     the identical stimulus at the default --soc0, because all three sustain
#     around the same captured/actual start point.
#   * The mapping is a pure TRANSLATION, so the policy's SHAPE (its deadband,
#     its bias direction, its saturation) is preserved exactly; what is lost is
#     any absolute-SoC meaning the solver's grid edges carried (e.g. a table
#     that biases harder near an absolute 0.55 floor now does so 0.10 above it).
#   * A study that WANTS absolute regulation must not use this strategy as-is —
#     it is a deliberate reinterpretation of the artifact, not a transparent
#     replay of it.
#
# ── DEMAND AXIS: THE v1 -> v2 RE-MAP (operator-ruled, 2026-08-31) ────────────
# HISTORY, because a v1 trace and a v2 trace are two different decision laws and
# nobody should have to rediscover why.  sdp_policy_v1.json was solved against
# the TPM sidecar's IDEAL-SCALING demand span (-1.125 .. +1.640 W): the
# full-size cycles' range carried through the systemic-scaling ratio.  This
# consumer measures P_dem = V_bus * (I_fc + I_batt) on the real rig, which
# campaign hil_report_20260831_191509 measured at 0 .. 22.887 W — an order of
# magnitude above that span.  Every decision therefore clamped into the TOP bin
# (~98 % of them), the demand axis carried no information, and the strategy
# emitted ONE constant clamped share for a whole run.  The plumbing was
# validated; the policy interior was never addressed.
#
# The unitless-TPM contract puts the watt map on the CONSUMER, so the fix was a
# re-map plus a re-solve of the SAME matrix: sdp_policy_v2.json is solved on
# [0.0, 25.0] W (the measured maximum + ~9 % headroom — tools/sdp_ems_solver.py
# D11 has the derivation).  This file does not rescale anything at run time; it
# reads `normalization` out of the artifact exactly as it always did, and the
# artifact now carries a map that matches the rig.
#
# THE CLAMP IS NOT REMOVED, it is moved out to the edge of the measured
# envelope: a demand above 25.0 W still folds into bin 24, and
# `clamped_high`/`clamped_low` still count it in the exit summary.  What the
# counters MEAN has changed — under v1 a ~100 % high-clamp rate was the expected
# reading, under v2 a high clamp rate is a SIGNAL that this rig has moved
# outside the map the shipped policy was solved for, and the answer is a
# re-solve at a wider map, not a wider tolerance.
# MEASURED OFFLINE against the campaign's own P_dem trace (see PREDICTED
# BEHAVIOUR below): 61 decisions, ZERO clamps either way, 13 distinct bins.
#
# ── PREDICTED BEHAVIOUR ON `ems-sdp`, measured offline against the SHIPPED
#    artifact — POLICY-BLOCK sha256 740c802e… (recipe:
#    sha256(json.dumps(doc["policy"], sort_keys=True)); the FILE sha is NOT
#    quoted anywhere, because `generated_utc` moves it on every regeneration
#    even when the decision law is byte-identical — the per-run file sha lives
#    in the CSV's meta sidecar instead), 101 SoC nodes x 25 bins, 2026-08-31.
#
#    HOW IT WAS MEASURED, so the numbers below can be reproduced or challenged:
#    an OFFLINE WALK of this strategy's own decision path — soc0 capture,
#    soc_relative(), demand_bin(), the table lookup, clamp_share() — over the
#    RECORDED P_dem and SoC trace of campaign hil_report_20260831_191509's
#    `ems-sdp` run, at the artifact's 1 s cadence.  ⚠️ THE WALK IS OPEN LOOP:
#    the recorded trace is a v1 run, so it does not contain the plant's response
#    to any command v2 issues that v1 did not.  Point 3 is exactly where that
#    matters and says so.
#
#   1. THE POLICY IS BANG-BANG IN THE SHARE, AND THE RUN STARTS ON ITS
#      SWITCHING BOUNDARY.  This is structural, not a tuning artefact: the stage
#      cost is PIECEWISE-LINEAR in the share (hydrogen is linear in s, the SoC
#      penalty is linear in s on each side of the node where SOC_next lands on
#      the target), so its minimum over [0, 1] is at a vertex — a rail, or the
#      kink.  The table's whole value set is {0.00, 0.90, 0.95, 1.00}.  Above
#      the (relative) target the action is 0.00; at or below it 1.00, except in
#      the top three demand bins where the kink moves inside the ladder and the
#      action is 0.95 (bins 22-23) or 0.90 (bin 24).  The grid-FLOOR node 0.550
#      reads 0.00 — a solver-side clamp-tie degeneracy (its D3/D8), not a second
#      switching point, and UNREACHABLE in `ems-sdp` (it needs SoC to fall 0.05
#      below the captured soc0 against this run's ~0.0017).
#      The SoC0-relative mapping puts a run's FIRST decision precisely on the
#      target node.  Benign here in one direction only — this scenario's SoC
#      falls monotonically, so soc_rel stays on the 1.00 side — but a scenario
#      that CHARGES would walk soc_rel back across the boundary and the
#      commanded share would flip at the decision cadence.  BOUNDED, not
#      removed, by the emission clamp in point 4: such a flip runs between 0.85
#      and 0.15, never between the rails, so it can never cut a source off the
#      bus — but it is still a 0.70-wide setpoint step every second.
#   2. THE DEMAND AXIS IS NOW LIVE, AND IT IS VISIBLE IN THE RAW COLUMN, NOT IN
#      THE EMITTED ONE.  Walk result: 61 decisions, 13 distinct demand bins
#      (0, 2-7, 9, 10, 12, 16, 17, 22), ZERO clamps in either direction.  The
#      TABLE's request moves with the demand — 0.95 on the whole drain plateau
#      (bin 22, t = 13..38) and 1.00 elsewhere — but BOTH sit above
#      SOC_BAND_SHARE_MAX, so point 4's clamp emits a constant 0.8500 either
#      way.  ⚠️ CONSEQUENCE FOR ANY READER OF `cmd_share_sp`: that column alone
#      CANNOT distinguish v1 from v2, or a live demand axis from a clamped one.
#      The `cmd_share_sp_raw` column (added in the same round, for exactly this)
#      is the one that shows the table's actual request.
#   3. ⚠️ A CHARGE WINDOW IS NOW REACHABLE — the largest behavioural change from
#      v1, where charging was unreachable by construction.  Under the 25 W map
#      the solver's own FC-current budget (its rule (b)) forbids charging above
#      bin 5 and the dwell rule forbids bins 12+, so `charge_goal` = 1 exactly
#      in bins 0-5 (P_dem < 6.0 W) at any SoC node below the relative target.
#      The walk lands it on t = 41.0 .. 58.0 — the profile's post-drain 1.0 m/s
#      low cruise, which is the SAME window `soc-band`'s heuristic charges in,
#      arrived at from a completely different rule.  CURRENT BUDGET, and it is
#      `ems-soc-band`'s own validated one: with FC_CHARGE_ENABLE open,
#      assertFcChargeEnable() drops BT off the bus and the FC channel alone
#      carries the load plus the charger — 5.593 W / 15.95 V = 0.351 A plus the
#      scenario's `chg_i_ceiling_a` 0.8 A = 1.151 A, 18 % under LIMIT_I_FC_MAX
#      1.4 A.  The solver's rule (b) bounds the general case at the bin's upper
#      edge too: 6.0 W / 15.95 + 0.8 = 1.176 A, under its own
#      CHARGE_FC_MARGIN * 1.4 = 1.19 A ceiling.
#      ⚠️ THE 1 Hz CHATTER OF FC_CHARGE_ENABLE — PREDICTED HERE, THEN MEASURED,
#      THEN FIXED CONSUMER-SIDE.  Opening the charger path ADDS its ~0.8 A to
#      I_fc, so the measured P_dem jumps from ~5.6 W to ~18.3 W, which is bin 18
#      — charge-FORBIDDEN — so the NEXT 1 s decision withdraws `charge_goal`,
#      the path closes, the demand falls back into bin 5, and the window
#      re-opens.  Campaign 20260831_222036 measured exactly that: 9 windows over
#      t = 41..58, period 2.0125 s, at a 4.63x harvest-efficiency cost and 9x a
#      >17.5 V BT_BUS restore ring.
#      The MINIMUM-DWELL HYSTERESIS in the SDP_CHG_* block above now suppresses
#      it — a latch on the emitted intent plus subtraction of the charger's own
#      draw from the measured demand, both ACTUATION-side, with the artifact
#      untouched.  Expected behaviour is now ONE continuous window t ~ 41..58.
#      Neither state exceeds a current limit (the budget above holds in the open
#      state and the closed state is the ordinary split; `soc-band` holds this
#      same point open for 12.5 s with 14.9 % margin), and the same cut and
#      restore is exercised fault-free by `ems-y-b00` at a heavier load — but
#      the Ag105 may never reach `chargerReady` promptly, so DO NOT assert
#      `I_charge` on this scenario the way `ems-soc-band`'s entry does.
#   4. THE TABLE'S RAIL IS EMITTED AS 0.85 — the HARDWARE-ENVELOPE CLAMP in
#      clamp_share(), which is soc-band's own clamp applied for soc-band's own
#      reason, and unchanged by the re-map.  1.00 is outside
#      [DROOP_R_MIN 0.15, DROOP_R_MAX 0.85], where
#      updateShareSetpointCutoff() (.ino:9231-9257) opens BT_BUS_ENABLE and the
#      FC channel would go single-source into this scenario's ~1.45 A drain —
#      above LIMIT_I_FC_MAX 1.4 A, i.e. an OC_FC latch part-way through the
#      drain ramp, which would TRUNCATE the run and with it the three-way
#      hydrogen comparison the scenario exists for.  At the clamp the run is
#      instead a sustained FC-heavy but LEGAL split: 0.85 x 1.45 = 1.23 A on FC
#      (12 % under the limit), tightened further by the firmware's own governor,
#      which clips an in-band setpoint to [I_min/I_tot, 1 - I_min/I_tot] =
#      [0.207, 0.793] at that load (.ino:9556-9568) — so the DELIVERED split is
#      ~0.793 and I_fc ~1.16 A, 17 % of margin, with the BT minority at exactly
#      SHARE_MINORITY_I_MIN_A 0.30 A.  Every table value the walk produces
#      (0.90, 0.95, 1.00) clamps to the same 0.8500, so this margin covers the
#      whole run.  The rail the table asked for is not hidden: `last_share_raw`
#      keeps it, `clamped_share` counts it, the exit summary prints both, and
#      the `cmd_share_sp_raw` CSV column carries it per tick.
SDP_POLICY_DIR = os.path.join(REPO_ROOT, "tools", "sdp_policies")
# ── TWO ARTIFACTS, TWO ROLES (2026-09-01, the charge-economics ruling) ──────
# There is no longer ONE shipped SDP artifact, so there is no longer a module
# global naming it: each SdpStrategy instance is PARAMETERIZED by its file, and
# EMS_STRATEGY_META records which role that file plays.  The two roles are not
# interchangeable and the difference is not cosmetic:
#
#   sdp_policy_v3.json  THE CALIBRATED BENCHMARK, `sdp-v3`, frontier_eligible.
#     alpha re-derived by two-sided lever calibration
#     (alpha = (1-gamma)/sqrt(L_share * L_chg) = 0.1629624 from the solver's own
#     model constants), which makes the Ag105 charge action UNPROFITABLE AT THIS
#     RIG'S SCALE and therefore rejects it ENDOGENOUSLY: the baked
#     `policy.charge_goal` is ZERO in every one of its 101 x 25 cells, and
#     `actions.forbid_charge_all` is FALSE — nothing masked the action, the
#     optimizer declined it.  Charging returns to the policy on its own if the
#     charger's measured lever ever exceeds (1-gamma)/alpha = 0.30682 SoC/g
#     (the physics-anchored revisit condition, e.g. post-R1 / fw v24).
#     POLICY-BLOCK sha256 0443febf… (recipe below; the FILE sha moves on every
#     regeneration and is recorded per run in the CSV meta sidecar instead).
#     ⚠️ The share map is IDENTICAL to v2's at every SoC row from 3 upward —
#     the two artifacts differ in the share only on rows 1-2 (30 cells), which
#     no shipped scenario's trajectory reaches.  That is why every v2-derived
#     offline walk transfers to a v3 leg verbatim; see the ems-ftp75-sdp entry.
#
#   sdp_policy_v2.json  THE DYNAMICS DEMONSTRATION, `sdp-v2`, NOT
#     frontier_eligible.  BYTE-FROZEN: it is kept exactly as shipped so the
#     `ems-sdp-cross` / `ems-sdp-braking` scenarios — which exist to put the
#     policy's CHARGE threshold on the wire — keep a policy that has charge
#     cells to command.  Its alpha (0.2569444, the "marginal" scaling) prices
#     SoC at a shadow price of 5.139 g/SoC, i.e. an admission threshold of
#     0.1946 SoC/g that the Ag105's 0.2364 clears — so it charges, and the
#     charging is measurably LOSS-MAKING against the campaign-measured 0.41
#     SoC/g share lever.  A run on this artifact demonstrates the mechanism; it
#     does NOT rank as an energy-management result, which is exactly what
#     `frontier_eligible: False` says and what run_hil_suite.py's demonstration
#     banner repeats to the reader.
#
#   sdp_policy_v4.json  THE SHIPPED CALIBRATED BENCHMARK from 2026-09-02,
#     `sdp-v4`, frontier_eligible — and the reason v3 is no longer it.  v3 was
#     solved against the 1:1 CURRENT-TRANSFER charger (bus power = V_bus*i_chg);
#     the plant is now an energy-conserving buck/boost at
#     `hil_electrical.ETA_CHG` = 0.88, under which the charge lever moves
#     0.2090 -> 0.3964 SoC/g (exactly eta * L_share) and the two-sided lever
#     calibration re-lands alpha at 0.118326398, mode `lever`, still 0 charge
#     cells — charging is STILL declined endogenously, but by a policy that was
#     priced against the charger the run actually has.  Operator rule
#     (2026-09-01): alpha follows the eta-era matched DP, and the eta-era DP
#     charges on ZERO stages on both `ems-sdp` and `ems-ftp75-dp`.
#     ⚠️ v3 vs v4, MEASURED (not assumed): the two charge maps are IDENTICAL
#     (both all-zero, 0 differing cells) and the share maps differ on exactly
#     FOUR SoC rows — 2, 3, 4, 5 (SoC 0.552-0.555), 76 cells — i.e. 45-48 grid
#     nodes BELOW the target node 0.600.  No shipped scenario's trajectory
#     reaches within 0.03 SoC of them (the largest |soc_ref_offset| is 0.013 and
#     the largest run |delta_soc| is ~0.016), so every v3-era offline walk and
#     every walk-derived expectation transfers to a v4 leg VERBATIM.  The
#     row-diff is pinned by test_sdp_v3_v4_share_maps_agree_on_traversed_rows().
#
#   sdp_policy_v3.json is KEPT REGISTERED but is now `frontier_eligible: False`:
#     it is the OLD-ERA (1:1 charger) calibration, retained for comparability
#     with campaigns <= 20260901_151156, not a candidate to be scored beside a
#     run whose charger is a different device.
SDP_POLICY_FILE_V2 = "sdp_policy_v2.json"
SDP_POLICY_FILE_V3 = "sdp_policy_v3.json"
SDP_POLICY_FILE_V4 = "sdp_policy_v4.json"
SDP_POLICY_SCHEMA = "sdp-policy-v1"

# ── THE SCENARIO-SUPPLIED ARTIFACT (2026-09-02) ─────────────────────────────
# A sentinel `policy_file`, NOT a path: the `sdp-sweep` strategy plays whatever
# artifact its SCENARIO names in `sdp_policy_file`, and has no default of its
# own.  Written as a bracketed phrase rather than None so it reads correctly
# everywhere a file name is printed (the startup banner, EMS_STRATEGY_META, a
# refusal message) and so `os.path.join` can never turn it into a plausible
# path that silently loads the wrong policy.  SdpStrategy.load() refuses it.
SDP_POLICY_FROM_SCENARIO = "<supplied by the scenario's sdp_policy_file>"

# ── THE ALPHA-SWEEP LIVE PICKS (2026-09-02) ─────────────────────────────────
# The alpha sweep (tools/sdp_alpha_sweep.py, WP-1B2a) bakes 41 artifacts and
# records THREE of them — one per behaviour leg — in this manifest.  A scenario
# names a pick with `sdp_policy_file: "live-picks:<key>"` and the path is
# resolved AT BIND TIME, for two reasons:
#   * the manifest is generated alongside the artifacts, so a hard-coded path
#     here would go stale the moment the sweep is re-run with a different
#     leg midpoint — and would go stale SILENTLY, playing an artifact nobody
#     selected under a scenario name that claims a leg;
#   * the manifest carries the SELECTED artifact's `policy_sha`, so the bind can
#     verify that the file on disk is still the decision law the offline walk
#     was run against.  A path alone cannot be checked against anything.
# Absent at run time = a startup refusal naming the generator, exactly as a
# missing policy artifact is.
SDP_LIVE_PICKS_PATH = os.path.join(
    SDP_POLICY_DIR, "sweep_20260902_eta088", "live_picks.json")
SDP_LIVE_PICK_PREFIX = "live-picks:"
# Hand the firmware back MODE_SAFE at the same time `soc-band` does.  DERIVED,
# not a literal: `ems-sdp` shares `ems-soc-band`'s profile object, so its
# standstill is at the same instant and a different exit time would make the two
# runs different missions.
SDP_RUN_EXIT_S = SOC_BAND_RUN_EXIT_S
# Decision cadence FALLBACK, in seconds, used only if the artifact omits
# `decision_dt_s`.  The artifact is the authority; this exists so the failure
# mode of an older sidecar is a documented 1 Hz rather than a KeyError deep in
# the run.  1.0 s is the study's own stage length.
SDP_DEFAULT_DECISION_DT_S = 1.0

# ── Charge-window minimum-dwell hysteresis (2026-08-31, ruled) ──────────────
# ⚠️ CONSUMER-SIDE ONLY.  The baked artifact is UNTOUCHED — no table value, no
# solver input and no policy sha moves with this block.  What is added is a
# hold on the ACTUATION of `charge_goal`, in exactly the place `soc-band`
# carries its own dual-i_tot hysteresis, and for the identical reason.
#
# THE DEFECT IT FIXES (PREDICTED at v2 design time, then MEASURED — campaign
# 20260831_222036, the first live sdp_policy_v2 run).  The policy is memoryless
# in the demand bin, so opening the charger path feeds back into its own input:
# FC_CHARGE_ENABLE high adds the Ag105's ~0.8 A to I_fc, the measured
# P_dem = V_bus*(I_fc + I_batt) jumps ~5.6 W -> ~18.3 W, that bin is
# charge-FORBIDDEN, the next 1 s decision withdraws the intent, the path closes,
# the demand falls back, and the window re-opens.  A single-tick ZOH hunt.
# Measured: 9 FC_CHARGE windows over t = 41..58, period 2.0125 s (sigma 10 ms).
#
# WHAT THE CHATTER COSTS, measured rather than argued:
#   * HARVEST.  The Ag105 spends ~540 ms of each ~1 s open window on detect +
#     settle, so it harvests 0.1603 A per open-second against `soc-band`'s
#     sustained 0.7421 — a 4.63x efficiency loss (1.39 vs 9.30 A*s banked).
#   * TRANSIENTS.  Each cycle costs a BT_BUS cut and restore through
#     assertFcChargeEnable(), and each restore rings the bus to 17.70-17.76 V —
#     over LIMIT_V_BUS_MAX 17.5 V, under the 19 V TPS61288 OVP.  The chatter
#     multiplies a near-limit transient NINE times for 13 % of soc-band's
#     charging SoC.
# The safety objection to holding the path open instead was REFUTED by
# measurement in the same campaign: `soc-band` holds this exact operating point
# open for 12.5 s continuously with I_fc peaking at 1.1920 A, 14.9 % under
# LIMIT_I_FC_MAX — and `ems-sdp`'s own governed peak is 1.1866 A.
#
# THE MECHANISM, and why it is the simplest sound one.  Two parts:
#   1. LATCH.  Once a decision emits charge_goal = 1, hold it for
#      SDP_CHG_MIN_DWELL_S regardless of what the bin says next.
#   2. SELF-LOAD SUBTRACTION.  During the hold, the bin is recomputed on
#      P_dem_ex_chg = P_dem - V_bus*I_charge (floored at 0) — the demand the
#      LOAD presents, with the charger's own draw removed.  Without this the
#      hold would merely defer the hunt: at expiry the policy would still be
#      reading its own charger as demand and would still withdraw.  With it,
#      the post-expiry decision sees bin ~5 again and re-latches, so the
#      window is CONTINUOUS rather than merely slower.
# The share axis is untouched by both parts on this scenario's trajectory (every
# table value it produces clamps to the same 0.8500), so the hold changes the
# charge actuation and nothing else.
#
# EARLY DROP, deliberately narrow — a fault, or the drive leaving the cruise the
# window was admitted on.  Both are conditions under which the ADMISSION itself
# is no longer valid, which is different from the bin moving because of the
# charger.  A demand rise from the LOAD does not drop the hold: at
# SDP_CHG_MIN_DWELL_S = 8 s the exposure is bounded, and this scenario's charge
# window is a flat 1.0 m/s cruise whose only load excursion IS the charger.
#
# MEASURED BEHAVIOUR under this block — `ems-sdp-cross`, campaign
# 20260901_024231.  ⚠️ THIS PARAGRAPH USED TO PREDICT `ems-sdp` AND IS RETARGETED:
# `ems-sdp` was rebound to the `sdp-v3` artifact, which has no charge cell to
# command at all (endogenous never-charge, validated live), so that scenario can
# no longer exercise this block.  `ems-sdp-cross` and `ems-sdp-braking` are the
# two scenarios that still play a charging artifact, and the first one is where
# the hysteresis was actually observed:
#     NINE windows over t = 70..190 s, period 16.13 s (gaps 8.04-8.08 s,
#     sigma 17 ms), 64103 ticks set of 120000, longest continuous hold 8.085 s
#     = SDP_CHG_MIN_DWELL_S + 1.1 %.
# ⚠️ AND THE WINDOW-ENDING MECHANISM THERE IS THE SoC SURFACE, NOT THE SELF-LOAD
# SUBTRACTION.  On `ems-sdp` the hunt was a demand-bin feedback loop and part 2
# of this block (the subtraction) is what made the window continuous.  On
# `ems-sdp-cross` the policy is regulating ACROSS the charge switching surface
# at SoC 0.69700: a dwell banks 3.6e-4 SoC, that carries soc_rel back above the
# surface, the table stops asking to charge, the node-50 decay gives it back in
# 8.08 s, and the next decision re-admits.  Each window therefore ends because
# the STATE crossed a surface — the longest hold is the dwell plus one decision
# quantum, i.e. the latch is not even the binding constraint — and the observed
# period is set by the DRAIN RATE at the low cruise, which is why walking that
# drain wrongly cost a check (see the SDP_CROSS_* block).
# The suite checks that carry these numbers are `sdpx_charge_cycled`,
# `sdpx_charge_max_hold`, `sdpx_charge_released_fraction` and
# `sdpx_charge_window_count` (ems-sdp-cross) and `sdpb_charge_in_low_windows`
# (ems-sdp-braking), all in run_hil_suite.py.
#
# The ORIGINAL `ems-sdp` walk, kept because it is what sized the constant: over
# campaign 20260831_222036's own recorded ems-sdp trace, stepped at the
# artifact's 1 s cadence,
#     WITHOUT this block (the shipped v2 behaviour)   9 windows,  8968 ticks
#     WITH it                                         2 windows, 14972 ticks
# and the baseline row reproduced that campaign's measured nine windows and
# their 2.0125 s period EXACTLY.  Campaign 20260901_000816 then measured 2
# latches over 15086 continuous FC_CHARGE ticks on the real board, inside the
# walk's predicted range.
#
# ⚠️ THE LATCH COUNTER IS NOT A WINDOW COUNTER (ledger note, campaign
# 20260901_000816).  `chg_holds` in the exit summary counts LATCHES — every
# rising-edge admission, including one taken on the tick a previous dwell
# expired.  The BOARD's FC_CHARGE_ENABLE window count is what the switch word
# shows, and a hold that expires and immediately re-latches on the corrected
# demand is 2 latches and ONE continuous window.  That is the mechanism working,
# not a discrepancy: campaign 20260901_000816 measured 2 latches over 15086
# continuous FC_CHARGE ticks against 9 windows / 8652 ticks without the block.
# Never quote `chg_holds` as a window count, and never derive a chatter rate
# from it; read the switch trace for that.
#
# 8.0 s = 3.98x the MEASURED 2.0125 s chatter cycle, so a hold cannot be a
# longer version of the same hunt, and 47 % of the ~17 s window, so the window
# still contains at least one full re-decision.  A round 8 rather than a fitted
# 8.05: the quantity it must clear is an order of magnitude away in both
# directions, so a spuriously precise constant would imply a precision the
# derivation does not have.
SDP_CHG_MIN_DWELL_S = 8.0
# The drive has "left cruise" when the commanded profile speed has moved this
# far from its value when the window was admitted.  0.10 m/s is twice
# SOC_BAND_CRUISE_SLOPE_MAX * 1 s, i.e. a move no cruise-classified segment can
# make within one decision stage — so a genuine flat hold never trips it while
# the profile's gentlest ramp (0.167 m/s^2) clears it in 0.6 s.
SDP_CHG_CRUISE_DELTA_MPS = 0.10
# FAULT_ERROR (.ino) — triggerFault() ORs it into fault_flags on every latch, so
# it is the one bit that means "the board is in State 99" regardless of cause.
SDP_CHG_ABORT_FAULT_MASK = 0x8000


# ═════════════════════════════════════════════════════════════════════════════
# THE ARTIFACT CONTRACT — tools/sdp_policies/<policy_file>
#
# ⚠️ `schema` IS THE FILE FORMAT, NOT THE ARTIFACT VERSION.  The shipped file
# is sdp_policy_v2.json and it declares schema "sdp-policy-v1", because v2
# changed the demand MAP (solver D11), not the shape of the document — so this
# loader parses v1 and v2 identically and BOTH files remain readable.  What
# distinguishes them at run time is `normalization` (the map) and the
# policy-block sha256, both recorded per run in the CSV's meta sidecar.
#
# Produced by tools/sdp_ems_solver.py; consumed ONLY here.  Written out in full
# because the producer and the consumer are separate programs and a schema that
# lives in neither one's head is a schema that drifts.
#
#   {
#     "schema": "sdp-policy-v1",          REQUIRED, exact match
#     "decision_dt_s": 1.0,               stage length the policy was solved for
#     "soc": {                            the SoC axis
#        "target":   0.60,                the value the policy regulates toward
#        "grid_min": 0.55,                inclusive low edge of the SoC grid
#        "grid_max": 0.65,                inclusive high edge
#        "grid":     [...]                OPTIONAL explicit grid; when absent a
#     },                                  uniform linspace(min, max, n_soc) is
#                                         reconstructed from the array height
#     "normalization": {                  demand normalization range, in WATTS
#        "p_dem_min_w":  0.0,              (v2's shipped map; v1's was the TPM
#        "p_dem_max_w": 25.0               sidecar's -1.1248 .. +1.6398 span)
#        ...                               the solver also records
#     },                                   `demand_map_source` and the sidecar's
#                                          own numbers here; both are CARRIED,
#                                          NOT CONSUMED (see below)
#     "demand_bins": {
#        "edges": [0.0, ..., 1.0],        n_bins+1 NORMALIZED bin edges in
#                                         [0, 1] (see the space note below)
#        "convention": "matlab-discretize-last-closed"
#     },
#     "policy": {
#        "share":       [[...], ...],     n_soc x n_bins  power_share_setpoint
#        "charge_goal": [[...], ...]      n_soc x n_bins  charge_goal
#     }
#   }
#
# Everything else the solver writes — provenance, the TPM hashes, the alpha
# derivation, the action ladder, the solver's convergence record — is CARRIED,
# NOT CONSUMED.  This loader reads only the keys above, so the solver stays free
# to record whatever it likes without breaking playback.
#
# EDGE SPACE.  `edges` are in the NORMALIZED demand coordinate
# x = (P_dem - p_dem_min_w)/(p_dem_max_w - p_dem_min_w), i.e. they must start at
# 0.0 and end at 1.0.  Normalized rather than watts on purpose: the watt range
# is already carried by `normalization`, and two independent copies of it would
# be two things to keep in step.  The loader REFUSES edges that do not span
# [0, 1] rather than guessing which space they are in.
#
# BINNING.  MATLAB `discretize` convention (the artifact declares it as
# `demand_bins.convention`, and the loader REFUSES any other value rather than
# silently applying this one): bin i is [e_i, e_{i+1}) for every i but the last,
# which is CLOSED [e_n-1, e_n].  x is clamped into [0, 1] first, so a demand
# outside the modelled range lands in an end bin by construction (the fidelity
# boundary above).
#
# ARRAY ORIENTATION.  Row = SoC index (ascending SoC), column = demand bin
# (ascending demand).  Both arrays must be the SAME shape; the loader checks it.
# ═════════════════════════════════════════════════════════════════════════════

# The one binning convention this consumer implements (sdp_bin_index()).  The
# artifact declares its own; a mismatch is refused rather than assumed, because
# the two plausible alternatives (first-closed, or a bin-centre nearest rule)
# differ ONLY at the edges — i.e. exactly where this rig's clamped demand always
# lands, so a wrong assumption would be invisible in every trace.
SDP_BIN_CONVENTION = "matlab-discretize-last-closed"


def _sdp_require(obj, key, path, kind=None):
    """Fetch a required artifact key or raise ValueError naming its location."""
    if not isinstance(obj, dict) or key not in obj:
        raise ValueError(
            "SDP policy artifact %s is missing the required key %r%s. See THE "
            "ARTIFACT CONTRACT block in hil_plant_sim.py (above SdpStrategy) "
            "for the full schema, and regenerate with "
            "tools/sdp_ems_solver.py." % (path, key, kind or ""))
    return obj[key]


def load_sdp_policy(path, name="sdp-v2"):
    """Parse and VALIDATE a baked SDP policy.  Returns a plain dict.

    `name` is the STRATEGY name this artifact is being loaded for, and it only
    ever appears in error text — two strategies now load two different files
    (see the SDP_POLICY_FILE_V2/V3 block), so a refusal that named a fixed
    strategy would point the reader at the wrong run.

    Every failure raises ValueError with a pointed message: this runs at
    startup, where a loud failure is free, and the alternative — a strategy that
    silently degrades to a 0.5 split — would produce a trace labelled with a
    policy name that is not the policy's.  Same discipline as load_dp_table()."""
    try:
        # Read BYTES, then parse: the same single read gives the file-identity
        # digest for the run's provenance record (MED-2) without a second pass
        # over the file at startup.
        with open(path, "rb") as fh:
            blob = fh.read()
        doc = json.loads(blob.decode("utf-8"))
    except OSError as exc:
        raise ValueError(
            "the `%s` strategy needs its baked policy at %s and it could "
            "not be read (%s).\n"
            "  Generate it first (numpy is required, so use miniforge — "
            "`.venv_hil` is stdlib-only):\n"
            "      C:/Users/ricky/miniforge3/python.exe "
            "tools/sdp_ems_solver.py" % (name, path, exc))
    except ValueError as exc:               # json.JSONDecodeError subclasses it
        raise ValueError("SDP policy artifact %s is not valid JSON: %s"
                         % (path, exc))
    if not isinstance(doc, dict):
        raise ValueError("SDP policy artifact %s must be a JSON object, got %s"
                         % (path, type(doc).__name__))

    schema = doc.get("schema")
    if schema != SDP_POLICY_SCHEMA:
        raise ValueError(
            "SDP policy artifact %s declares schema %r; this consumer "
            "implements %r ONLY. A schema bump is a contract change and must "
            "be made in tools/sdp_ems_solver.py and here TOGETHER — replaying "
            "an unknown schema would be a trace labelled `%s` whose "
            "semantics nobody has checked."
            % (path, schema, SDP_POLICY_SCHEMA, name))

    soc = _sdp_require(doc, "soc", path)
    if not isinstance(soc, dict):
        raise ValueError("SDP policy artifact %s: `soc` must be an object "
                         "carrying target/grid_min/grid_max" % path)
    target = float(_sdp_require(soc, "target", path, " (inside `soc`)"))
    gmin = float(_sdp_require(soc, "grid_min", path, " (inside `soc`)"))
    gmax = float(_sdp_require(soc, "grid_max", path, " (inside `soc`)"))
    if not (gmax > gmin):
        raise ValueError("SDP policy artifact %s: soc.grid_max (%r) must "
                         "exceed soc.grid_min (%r)" % (path, gmax, gmin))
    if not (gmin <= target <= gmax):
        raise ValueError("SDP policy artifact %s: soc.target %r lies outside "
                         "the grid [%r, %r] — the policy could never regulate "
                         "to it" % (path, target, gmin, gmax))

    norm = _sdp_require(doc, "normalization", path)
    p_min = float(_sdp_require(norm, "p_dem_min_w", path,
                               " (inside `normalization`)"))
    p_max = float(_sdp_require(norm, "p_dem_max_w", path,
                               " (inside `normalization`)"))
    if not (p_max > p_min):
        raise ValueError("SDP policy artifact %s: normalization.p_dem_max_w "
                         "(%r) must exceed p_dem_min_w (%r)"
                         % (path, p_max, p_min))

    bins = _sdp_require(doc, "demand_bins", path)
    convention = bins.get("convention")
    if convention != SDP_BIN_CONVENTION:
        raise ValueError(
            "SDP policy artifact %s declares demand_bins.convention %r; this "
            "consumer implements %r ONLY. The conventions differ only at the "
            "bin EDGES — which is exactly where this rig's clamped demand "
            "always lands — so assuming one would be invisible in every trace."
            % (path, convention, SDP_BIN_CONVENTION))
    edges = [float(e) for e in _sdp_require(bins, "edges", path,
                                            " (inside `demand_bins`)")]
    if len(edges) < 2:
        raise ValueError("SDP policy artifact %s: `edges` needs at least 2 "
                         "entries, got %d" % (path, len(edges)))
    if any(b <= a for a, b in zip(edges, edges[1:])):
        raise ValueError("SDP policy artifact %s: `edges` must strictly "
                         "increase" % path)
    # The [0, 1] span IS the declaration that these are normalized edges. A
    # tolerance rather than == because the artifact round-trips through JSON
    # text; anything looser would silently accept a watt-space grid.
    if abs(edges[0]) > 1e-9 or abs(edges[-1] - 1.0) > 1e-9:
        raise ValueError(
            "SDP policy artifact %s: demand_bins.edges must span the "
            "NORMALIZED demand coordinate [0.0, 1.0] (got [%.6g, %.6g]). The "
            "watt range belongs in `normalization` — see THE ARTIFACT "
            "CONTRACT block." % (path, edges[0], edges[-1]))
    n_bins = len(edges) - 1

    policy = _sdp_require(doc, "policy", path)

    # MED-4 (review, 2026-08-31) — VALUE VALIDATION, AND WHY IT IS AT LOAD.
    # Both arrays reach the wire, and a bad cell is SILENT in both directions:
    #   * a non-finite SHARE passes clamp_share() as 0.15 (Python's max/min
    #     return the non-NaN operand), so it books as an ordinary
    #     hardware-envelope clamp and the trace looks like a deliberate
    #     battery-heavy command;
    #   * a non-finite or out-of-range CHARGE_GOAL is emitted RAW — the field
    #     has no clamp — and the firmware's own isfinite guard HOLDS the
    #     previous value, so the logged `cmd_*` column and the board's actual
    #     state diverge with nothing anywhere saying so.
    # Refusing at load costs one startup pass and removes both.
    # DELIBERATELY NOT CHECKED: membership in the solver's own action ladder
    # (`actions.share_ladder`). The ladder is the solver's search grid, not a
    # contract on the emitted value, and pinning to it would refuse a future
    # artifact that legitimately interpolates or re-grids.
    def _grid_2d(key, lo=None, hi=None, allowed=None):
        raw = _sdp_require(policy, key, path, " (inside `policy`)")
        if not isinstance(raw, list) or not raw:
            raise ValueError("SDP policy artifact %s: policy.%s must be a "
                             "non-empty list of rows" % (path, key))
        out = []
        for i, row in enumerate(raw):
            if not isinstance(row, list) or len(row) != n_bins:
                raise ValueError(
                    "SDP policy artifact %s: policy.%s row %d has %s entries; "
                    "every row must have exactly n_bins = %d (len(edges) - 1)"
                    % (path, key, i,
                       len(row) if isinstance(row, list) else "non-list",
                       n_bins))
            vals = []
            for j, v in enumerate(row):
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    raise ValueError(
                        "SDP policy artifact %s: policy.%s[%d][%d] is %r, "
                        "which is not a number" % (path, key, i, j, v))
                if not math.isfinite(fv):
                    raise ValueError(
                        "SDP policy artifact %s: policy.%s[%d][%d] is %r "
                        "(non-finite). A NaN/Inf action reaches the command "
                        "packet: a share would clamp to %.2f and read as a "
                        "deliberate command, and a charge_goal is emitted raw "
                        "and HELD by the firmware's isfinite guard, so the "
                        "logged command and the board's state would silently "
                        "disagree." % (path, key, i, j, fv,
                                       SOC_BAND_SHARE_MIN))
                if lo is not None and not (lo <= fv <= hi):
                    raise ValueError(
                        "SDP policy artifact %s: policy.%s[%d][%d] is %r, "
                        "outside the legal range [%g, %g]"
                        % (path, key, i, j, fv, lo, hi))
                if allowed is not None and fv not in allowed:
                    raise ValueError(
                        "SDP policy artifact %s: policy.%s[%d][%d] is %r; this "
                        "field is an INTENT and the only legal values are %s "
                        "(the firmware maps any value > 0 onto 'open the path "
                        "and let the Ag105 run at its configured ceiling', so "
                        "an intermediate number is not a smaller charge — it "
                        "is an unchecked value on the wire)."
                        % (path, key, i, j, fv,
                           " / ".join("%g" % a for a in sorted(allowed))))
            vals = [float(v) for v in row]
            out.append(vals)
        return out

    # share is a RATIO in [0, 1]; charge_goal is a two-valued INTENT.
    share = _grid_2d("share", lo=0.0, hi=1.0)
    goal = _grid_2d("charge_goal", allowed=(0.0, 1.0))
    if len(share) != len(goal):
        raise ValueError("SDP policy artifact %s: policy.share has %d rows and "
                         "policy.charge_goal has %d — they index the same SoC "
                         "grid and must match" % (path, len(share), len(goal)))
    n_soc = len(share)

    grid = soc.get("grid")
    if grid is None:
        # Uniform reconstruction. n_soc == 1 is degenerate but legal (a
        # SoC-independent policy); the single node sits at grid_min.
        if n_soc == 1:
            grid = [gmin]
        else:
            step = (gmax - gmin) / (n_soc - 1)
            grid = [gmin + step * i for i in range(n_soc)]
    else:
        grid = [float(v) for v in grid]
        if len(grid) != n_soc:
            raise ValueError("SDP policy artifact %s: soc.grid has %d entries "
                             "but the policy arrays have %d rows"
                             % (path, len(grid), n_soc))
        if any(b <= a for a, b in zip(grid, grid[1:])):
            raise ValueError("SDP policy artifact %s: soc.grid must strictly "
                             "increase" % path)

    # ── Two digests, because they answer two different questions (MED-2) ─────
    # file_sha256   IDENTITY OF THIS FILE. Moves on every regeneration, since
    #               the artifact carries `generated_utc` and the solver's own
    #               prose — so it answers "exactly which bytes produced this
    #               run" and nothing else. Recorded per run in the meta sidecar.
    # policy_sha256 IDENTITY OF THE DECISION LAW. sha256 over
    #               json.dumps(doc["policy"], sort_keys=True) — the two action
    #               grids and nothing else — so it is STABLE across a --force
    #               regeneration that did not change the policy. This is the
    #               digest to QUOTE in a comment or a doc; a byte sha quoted
    #               there goes stale the next time anyone re-runs the solver.
    return {
        "path": path, "schema": schema,
        "file_sha256": hashlib.sha256(blob).hexdigest(),
        "policy_sha256": hashlib.sha256(
            json.dumps(doc["policy"], sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "generated_utc": doc.get("generated_utc"),
        "tpm_sha256": (doc.get("tpm") or {}).get("sha256")
                      if isinstance(doc.get("tpm"), dict) else None,
        "decision_dt_s": float(doc.get("decision_dt_s",
                                       SDP_DEFAULT_DECISION_DT_S)),
        "soc_target": target, "soc_min": gmin, "soc_max": gmax,
        "soc_grid": grid, "n_soc": n_soc, "n_bins": n_bins,
        "p_dem_min_w": p_min, "p_dem_max_w": p_max,
        # CARRIED (not consumed): the solver's prose description of where the
        # watt range came from. Surfaced through the loader so the per-run
        # provenance record can name the demand map in words, not just by two
        # numbers that a reader has to recognise. Absent in older artifacts.
        "demand_map_source": norm.get("demand_map_source"),
        "edges": edges, "share": share, "charge_goal": goal,
        "convention": convention,
        # CARRIED, NOT CONSUMED — the solver's own provenance record (TPM hash,
        # the alpha derivation, the action ladder, convergence), kept so the
        # startup banner and any future sidecar can quote it without this
        # loader having to know what is in it.
        "raw": doc,
    }


def _sdp_doc_alpha(pol):
    """The artifact's shipped alpha, or None.  CARRIED, not consumed."""
    val = ((pol.get("raw") or {}).get("alpha") or {}).get("value")
    return None if val is None else float(val)


def _sdp_doc_eta_chg(pol):
    """The CHARGER ERA an SDP artifact was solved in, or None for the old one.

    Same sentinel convention as `dp_eta_chg()` and tools/charger_power.py: an
    artifact with no `charger.eta_chg` block was solved against the 1:1
    current-transfer charger, and that is a statement, not a gap."""
    chg = (pol.get("raw") or {}).get("charger")
    if not isinstance(chg, dict):
        return None
    val = chg.get("eta_chg")
    return None if val is None else float(val)


def resolve_sdp_policy_file(value, scenario=None, picks_path=None):
    """Resolve a scenario's `sdp_policy_file` to (repo-relative path, source).

    TWO FORMS, and the second exists because a hard-coded sweep path cannot be
    checked against anything (see SDP_LIVE_PICKS_PATH):

      "tools/sdp_policies/…json"   a path, used as written.
      "live-picks:<key>"           the artifact `<key>` names in the alpha
                                   sweep's live-picks manifest.  Resolved at
                                   BIND TIME, and the manifest's recorded
                                   `policy_sha` is returned with it so the
                                   caller can verify that the file on disk is
                                   still the decision law the offline walk was
                                   run against.

    `source` is a dict recorded in the run's provenance: it is the answer to
    "why is this run playing THIS artifact", which a bare path cannot give.
    Raises ValueError — every failure here is a startup refusal."""
    text = str(value)
    if not text.startswith(SDP_LIVE_PICK_PREFIX):
        return text, {"kind": "scenario_path", "declared": text}
    key = text[len(SDP_LIVE_PICK_PREFIX):].strip() or (scenario or "")
    path = picks_path or SDP_LIVE_PICKS_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except OSError as exc:
        raise ValueError(
            "scenario %r names the alpha-sweep pick %r, and the live-picks "
            "manifest it is recorded in could not be read at %s (%s).\n"
            "  It is written by the sweep that bakes the artifacts:\n"
            "      C:/Users/ricky/miniforge3/python.exe "
            "tools/sdp_alpha_sweep.py\n"
            "  Refusing rather than falling back to a default artifact: a run "
            "labelled %r that played the shipped benchmark instead of its "
            "sweep point would be a leg of an alpha sweep with no alpha in it."
            % (scenario, key, path, exc, scenario))
    except ValueError as exc:
        raise ValueError("the live-picks manifest %s is not valid JSON: %s"
                         % (path, exc))
    picks = (doc.get("picks") or {}) if isinstance(doc, dict) else {}
    pick = picks.get(key)
    if not isinstance(pick, dict) or not pick.get("policy_file"):
        raise ValueError(
            "the live-picks manifest %s has no `policy_file` for the pick %r "
            "(it records %s). A scenario cannot name a pick the sweep did not "
            "select." % (path, key, sorted(picks) or "no picks at all"))
    source = {
        "kind": "live_picks",
        "manifest": os.path.relpath(path, REPO_ROOT).replace(os.sep, "/"),
        "pick": key,
        "leg": pick.get("leg"),
        "alpha": pick.get("alpha"),
        "index": pick.get("index"),
        # The sha the SWEEP recorded for the artifact it selected. Checked
        # against the loaded file in bind_scenario(): if the artifact was
        # regenerated after the pick was made, the run would be playing a law
        # the offline walk never saw.
        "expect_policy_sha256": pick.get("policy_sha"),
        "expect_file_sha256": pick.get("file_sha256"),
    }
    return str(pick["policy_file"]), source


def sdp_assert_calibrated_benchmark(pol, name):
    """Refuse an artifact that is not THE CALIBRATED BENCHMARK.  Raises.

    Returns the list of certificate clauses that were WAIVED under an
    era-scoped allowance (empty for an artifact that meets every clause
    outright).  The caller prints them; see the allowance block below.

    THE CERTIFICATE, and it is a QUADRUPLE because no single field carries the
    claim (2026-09-01 ruling, OVERNIGHT_LOG.md "SDP charge-economics
    adjudication"):

      alpha.mode == "lever"          the SoC price was set by TWO-SIDED LEVER
                                     CALIBRATION, not by a scaling argument
                                     that never met the charge action.
      alpha.admission.in_window_model      the shipped alpha lies strictly
      alpha.admission.in_window_measured   inside BOTH admission windows — the
                                     tripwire that would have caught v2, whose
                                     alpha prices SoC at 5.139 g/SoC and takes
                                     every lever above 0.1946 SoC/g, the Ag105
                                     (0.2364) included.
      actions.forbid_charge_all is False   the zero charge map is ENDOGENOUS.
                                     If a future artifact is generated with the
                                     `--forbid-charge` MASK instead, its zero
                                     charge cells prove nothing about the
                                     economics, and a leg carrying it must not
                                     be presented as the calibrated benchmark.

    WHY AT LOAD, CONSUMER-SIDE.  The solver is free to emit any artifact it
    likes; what must never happen is a run LABELLED `sdp-v3` — and scored on
    the EMS frontier — that is playing a policy nobody calibrated.  Every
    symptom of that mistake is invisible in the trace: the share map is
    identical outside SoC rows 1-2, so the only observable difference is a
    charge window that either appears or does not, and "no window" is also what
    a correct benchmark run looks like on a scenario that never admits one.
    """
    doc = (pol.get("raw") or {})
    alpha = doc.get("alpha") or {}
    admission = alpha.get("admission") or {}
    actions = doc.get("actions") or {}
    problems = []
    # Certificate clauses that were WAIVED rather than met.  Returned (not
    # swallowed) so the caller can print them: an allowance that nobody sees is
    # indistinguishable from a clause that passed.
    allowances = []
    if alpha.get("mode") != "lever":
        problems.append("alpha.mode is %r, not 'lever'" % (alpha.get("mode"),))
    if admission.get("in_window_model") is not True:
        problems.append("alpha.admission.in_window_model is %r, not True"
                        % (admission.get("in_window_model"),))
    # ── THE MEASURED-WINDOW ALLOWANCE (2026-09-02, ERA-SCOPED) ──────────────
    # `in_window_measured` is null on sdp_policy_v4.json, and NOT because the
    # calibration is weaker: the eta era made the measured pair UNDECIDABLE.
    # The only measured charge lever this rig has (0.2364 SoC/g, campaigns
    # 20260831_222036 / 20260901_000816) was measured under the 1:1 charger;
    # projected onto the new billing it becomes 0.4484 SoC/g, which is ABOVE
    # the measured share lever 0.412 — the OPPOSITE of the model's ordering
    # (the model says charging is worse than sharing by exactly 1/eta). Two
    # contradicting orderings do not make a window, so the solver records the
    # measured window as null rather than asserting one it cannot defend. No
    # alpha decision rests on it: `alpha.value` comes from the MODEL levers.
    # TODO(verify): the first eta-era campaign re-measures the charge lever;
    # when it does, this artifact must be regenerated with a real measured
    # window and the allowance stops applying to it.
    #
    # WHAT THE ALLOWANCE COSTS, and why it is not a hole: a null is accepted
    # ONLY when the artifact also states an INTENT (`alpha.window_intent`) and
    # a REASON (`alpha.admission.measured_window_undecidable`). A bare null —
    # the shape an OLD artifact or a truncated solve produces — still fails,
    # so "the field is missing" and "the field is deliberately undecidable"
    # cannot be confused.
    # THE THREE FIELDS THE ALLOWANCE READS, named here so a future artifact
    # cannot satisfy it by accident:
    #   alpha.admission.window_intent                 the INTENT — what the
    #       shipped alpha is supposed to admit and reject ("admit share, reject
    #       charge"). Absent on every pre-2026-09-02 artifact.
    #   alpha.levers_soc_per_g.charge_measured_is_projection  the REASON — the
    #       measured charge lever in this document is a PROJECTION of an
    #       old-era measurement onto the new billing, not a measurement, so
    #       there is no measured pair from which a window could be formed.
    #   charger.eta_chg                               the ERA SCOPE — the
    #       allowance exists because the charger model changed; an artifact
    #       that does not say which charger it was solved against is not
    #       inside the era the allowance is scoped to.
    measured = admission.get("in_window_measured")
    intent = admission.get("window_intent")
    projected = (alpha.get("levers_soc_per_g") or {}).get(
        "charge_measured_is_projection")
    era = (doc.get("charger") or {}).get("eta_chg")
    if measured is not True:
        if (measured is None and admission.get("window_measured") is None
                and isinstance(intent, str) and intent.strip()
                and projected is True and era is not None):
            allowances.append(
                "alpha.admission.in_window_measured is null — ACCEPTED under "
                "the ERA-SCOPED allowance (2026-09-02). Intent: %s. Reason: "
                "the measured charge lever in this artifact is a PROJECTION "
                "of an old-era measurement (%r SoC/g measured -> %r projected) "
                "onto the eta_chg = %g billing, and it lands ABOVE the "
                "measured share lever, i.e. the OPPOSITE of the model's "
                "ordering — so the measured pair is UNDECIDABLE and no window "
                "is asserted. `alpha.value` rests on the MODEL levers, which "
                "are checked (in_window_model True). "
                "TODO(verify): re-measure the charge lever in the first "
                "eta-era campaign and regenerate this artifact; the allowance "
                "then stops applying to it."
                % (intent,
                   (alpha.get("levers_soc_per_g") or {}).get(
                       "charge_measured_as_measured"),
                   (alpha.get("levers_soc_per_g") or {}).get(
                       "charge_measured"),
                   float(era)))
        else:
            problems.append(
                "alpha.admission.in_window_measured is %r, not True%s"
                % (measured,
                   "" if measured is not None else
                   " — a null is accepted ONLY by the era-scoped allowance, "
                   "which needs alpha.admission.window_intent (got %r), "
                   "alpha.levers_soc_per_g.charge_measured_is_projection "
                   "(got %r) and charger.eta_chg (got %r) all present"
                   % (intent, projected, era)))
    if actions.get("forbid_charge_all"):
        problems.append("actions.forbid_charge_all is %r — the charge map was "
                        "MASKED, not declined by the optimizer"
                        % (actions.get("forbid_charge_all"),))
    if problems:
        raise ValueError(
            "SDP policy artifact %s is bound to `%s`, which run_hil_suite.py "
            "scores on the EMS FRONTIER and therefore requires THE CALIBRATED "
            "BENCHMARK certificate — and this artifact does not carry it:\n"
            "    %s\n"
            "Regenerate with the calibrated alpha — and, in the eta era, with "
            "the era the plant runs in (an artifact solved without --eta-chg "
            "is priced against the retired 1:1 charger):\n"
            "    C:/Users/ricky/miniforge3/python.exe tools/sdp_ems_solver.py "
            "--alpha-mode lever --eta-chg 0.88 --out %s --force\n"
            "NOTE an eta-era `lever` artifact carries "
            "`alpha.admission.in_window_measured` NULL, not True: the measured "
            "charge lever was measured under the old charger and its "
            "projection contradicts the model's ordering, so the measured "
            "window is UNDECIDABLE. That null IS the certificate in this era "
            "and is accepted by the era-scoped allowance above — it needs "
            "`alpha.admission.window_intent`, "
            "`alpha.levers_soc_per_g.charge_measured_is_projection` and "
            "`charger.eta_chg` present, which the solver writes.\n"
            "or bind this strategy to a NON-frontier role in "
            "EMS_STRATEGY_META (see `sdp-v2`, the dynamics demonstration)."
            % (pol.get("path"), name, "\n    ".join(problems),
               pol.get("path")))
    return allowances


def sdp_bin_index(x, edges):
    """MATLAB `discretize` bin for x in the NORMALIZED demand coordinate.

    Written out rather than reached for bisect: the half-open/closed asymmetry
    at the top edge is the whole subtlety, and it is worth being able to read
    it.  `x` is assumed already clamped into [edges[0], edges[-1]] by the
    caller, which is where the clamp is COUNTED (see SdpStrategy)."""
    n = len(edges) - 1
    # bisect_right gives the first edge strictly greater than x, so index-1 is
    # the half-open bin [e_i, e_{i+1}).  The final bin is CLOSED, so x exactly
    # at the top edge folds back into it instead of running off the end.
    i = bisect.bisect_right(edges, x) - 1
    if i < 0:
        return 0
    if i >= n:
        return n - 1
    return i


class SdpStrategy:
    """ONLINE stochastic-DP policy lookup.  Read the banner above.

    name       : `sdp-v3` (the calibrated BENCHMARK, frontier-scored) or
                 `sdp-v2` (the byte-frozen DYNAMICS DEMONSTRATION) — ONE class,
                 two registered instances differing only in their artifact and
                 their role.  See the SDP_POLICY_FILE_V2/V3 block and
                 EMS_STRATEGY_META.
    intent     : a CAUSAL state-feedback policy computed offline over a
                 stochastic demand model, so a campaign can rank a causal
                 optimal-by-construction law between the causal heuristic
                 (`soc-band`) and the non-causal bound (`dp-replay`) on one
                 stimulus.
    fields     : mode_cmd (SAFE -> HYBRID at EMS_RUN_ENTRY_S, back to SAFE at
                 the scenario's ems_run_exit_s / SDP_RUN_EXIT_S),
                 v_setpoint (the scenario's `ems_v_profile`, exactly as
                 hold-5050 and soc-band take it), power_share_setpoint and
                 charge_goal (table lookup on (SoC, demand bin), recomputed at
                 the artifact's `decision_dt_s` and HELD between decisions, with
                 a MINIMUM-DWELL hysteresis on the charge intent — see the
                 SDP_CHG_* block; the
                 share is CLAMPED to the hardware envelope
                 [SOC_BAND_SHARE_MIN, SOC_BAND_SHARE_MAX] on emission — see
                 clamp_share(), and note the raw table value is kept and
                 counted, not erased).
    feedback   : `t`, `v_profile`, `V_bus`, `I_fc`, `I_batt` (all
                 telemetry-equivalent) and `soc` (PLANT TRUTH — the non-portable
                 term; see the SIM-ONLY banner).
    ⚠️ SIM-ONLY, and the demand axis clamps — both are in the banner above the
       class.  The clamp counters are reported in the exit summary.

    STATE.  A class for SocBandStrategy's reasons and one more: the loaded
    artifact.  EMS_STRATEGIES holds ONE instance; reset() clears the per-run
    state and DELIBERATELY KEEPS the loaded policy (the artifact is a property
    of the file, not of the run — reloading it per run would be I/O for
    nothing).  A rewind (t going backwards) auto-resets, so a second run in one
    process cannot inherit the first run's captured SoC reference.
    `soc_ref_offset` is a BINDING, not run state, and survives reset() for the
    same reason the artifact does — see set_soc_ref_offset().
    """

    def __init__(self, name="sdp-v2", policy_file=None, policy_dir=None,
                 require_calibrated_benchmark=False):
        # NO I/O here: EMS_STRATEGIES is built at import time and constructing
        # the registry must not touch the disk (or fail because the policy has
        # not been generated yet).  Loading happens in bind_scenario(), or
        # lazily on the first call for a direct caller — ONCE either way.
        #
        # PARAMETERIZED BY ITS ARTIFACT (2026-09-01).  There is no module-level
        # "the SDP policy file" any more: two instances play two different
        # artifacts in two different roles, and a global would make the role a
        # property of the process rather than of the strategy.  `name` is the
        # registry key and appears in every message and summary line, so a
        # trace can never be labelled with a strategy it did not run.
        self.name = name
        self.policy_file = policy_file or SDP_POLICY_FILE_V2
        # THE ARTIFACT THIS INSTANCE WAS REGISTERED WITH, kept so a scenario's
        # `sdp_policy_file` override (2026-09-02) can be UNDONE: EMS_STRATEGIES
        # holds ONE instance per name and a process runs one scenario, but a
        # test binds many, and an override that leaked from one bind into the
        # next would play an artifact the second scenario never named.
        self.default_policy_file = self.policy_file
        self.require_calibrated_benchmark = bool(require_calibrated_benchmark)
        self.policy_dir = policy_dir or SDP_POLICY_DIR
        self.policy = None
        # The scenario's resolved override, for the provenance record: None
        # when the instance is playing its registered artifact.
        self.policy_file_source = None
        # Certificate clauses waived under an era-scoped allowance (see
        # sdp_assert_calibrated_benchmark()); [] until the artifact is loaded.
        self.certificate_allowances = []
        # Filled by bind_scenario(); None for a strategy that was only ever
        # called directly (a test, a probe), which is also how main() decides
        # whether there is anything to write into the meta sidecar.
        self.provenance = None
        # ── soc_ref_offset (delta), 2026-08-31 ──────────────────────────────
        # NOT run state: it is set once by bind_scenario() from the scenario's
        # `sdp_soc_ref_offset` key and must survive reset(), exactly as the
        # loaded artifact does. 0.0 reproduces every pre-2026-08-31 run
        # bit-identically. See set_soc_ref_offset() for what it means.
        self.soc_ref_offset = 0.0
        self.reset()

    @property
    def path(self):
        """The artifact's absolute path.

        A BARE FILE NAME (the registered case) resolves inside `policy_dir`,
        which is what keeps `policy_dir=tmp_path` working for every test that
        writes a synthetic artifact.  A name carrying a separator — which is
        what a scenario's `sdp_policy_file` gives, since a sweep artifact lives
        in a SUBDIRECTORY — resolves against REPO_ROOT (or is used as-is when
        already absolute), so a scenario can name any artifact in the tree
        without the strategy having to guess a directory."""
        name = self.policy_file
        if os.path.isabs(name):
            return name
        if os.sep in name or "/" in name:
            return os.path.normpath(os.path.join(REPO_ROOT, name))
        return os.path.join(self.policy_dir, name)

    def set_policy_file(self, name, source=None):
        """Play `name` instead of the registered artifact.  Idempotent.

        Clears the cached policy whenever the file actually changes, so a
        re-bind cannot serve the previous scenario's decision law.  `name` None
        restores the registered artifact — the state every bind starts from."""
        new = self.default_policy_file if name is None else str(name)
        if new != self.policy_file:
            self.policy = None
        self.policy_file = new
        self.policy_file_source = None if name is None else source

    def set_soc_ref_offset(self, delta):
        """Place the run's STARTING SoC `delta` ABOVE the policy's target node.

        WHAT IT DOES.  The SoC0-relative mapping (banner above) captures
        `soc_ref = soc0` on the first decision and looks the table up at
        `soc_target + (soc - soc_ref)`, so a run's FIRST decision lands exactly
        ON the target node.  With an offset the capture becomes
            soc_ref = soc0 - delta   ==>   soc_rel(t=0) = soc_target + delta
        i.e. a POSITIVE delta starts the run `delta` ABOVE the target and a
        negative one starts it below.  Nothing else in the lookup changes: the
        mapping stays a pure translation of the SoC axis.

        WHY IT EXISTS.  The table is BANG-BANG in the share about the target
        node (point 1 of the PREDICTED BEHAVIOUR block), and a run that starts
        ON that node and only discharges never leaves the FC-rail side — every
        `ems-sdp` campaign to date emitted ONE constant clamped 0.8500 for the
        whole run.  Starting above the node puts the policy on its OTHER branch
        (table 0.00, emitted at the SOC_BAND_SHARE_MIN clamp as 0.15), and the
        run's own discharge then walks it across the switching boundary — so
        the switching law itself becomes observable on the wire, once, at a
        time the scenario's drain sets.  Starting BELOW the node instead pins
        the share at the rail so that every charge transition in the trace is
        attributable to the DEMAND axis alone.

        VALIDATION, and it is a REFUSAL rather than a clamp.  |delta| may not
        exceed the shorter side of the grid about the target,
        `min(target - grid_min, grid_max - target)` — 0.05 for the shipped
        artifact, whose target is centred, i.e. half the grid span.  Beyond
        that the FIRST decision would already be clamped onto a grid EDGE by
        soc_relative(), so the run would start at whatever action the edge node
        carries (for the shipped artifact the floor node 0.550 is the solver's
        clamp-tie degeneracy, 0.00) and the requested offset would not be the
        operating point at all.  Silently clamping would produce a trace
        labelled with an offset it never had."""
        pol = self.load()
        # A NUMBER, not something float() happens to parse: the value comes
        # from a registry literal, and a string "0.01" there would be a
        # scenario key nobody meant to write as text.
        if isinstance(delta, bool) or not isinstance(delta, (int, float)):
            raise ValueError("sdp_soc_ref_offset must be a number, got %r"
                             % (delta,))
        d = float(delta)
        if not math.isfinite(d):
            raise ValueError("sdp_soc_ref_offset must be finite, got %r" % (d,))
        lim = min(pol["soc_target"] - pol["soc_min"],
                  pol["soc_max"] - pol["soc_target"])
        # The tolerance is a FLOATING-POINT allowance, not slack in the rule:
        # the shipped artifact's own half-span evaluates to 0.049999999999999934,
        # so an offset written as exactly 0.05 would be refused by an equality
        # test that is arithmetically satisfied.
        if abs(d) > lim + 1e-9:
            raise ValueError(
                "sdp_soc_ref_offset %.6g exceeds the usable half-span of this "
                "artifact's SoC grid (%.6g = min(target %.3f - grid_min %.3f, "
                "grid_max %.3f - target %.3f)). The first decision would be "
                "clamped onto a grid EDGE by soc_relative(), so the run would "
                "not start at the requested offset at all — refused rather "
                "than clamped, because a clamped start is invisible in the "
                "trace." % (d, lim, pol["soc_target"], pol["soc_min"],
                            pol["soc_max"], pol["soc_target"]))
        self.soc_ref_offset = d
        return d

    def reset(self):
        """Per-RUN state.  The loaded artifact is not run state and survives."""
        self.soc_ref = None         # captured on the first call that sees a SoC
        self.last_t = None
        self.next_decision_t = None
        self.decisions = 0
        self.clamped_high = 0       # decisions whose demand exceeded the model
        self.clamped_low = 0        # ... or fell below it
        self.clamped_share = 0      # decisions whose table action was outside
                                     # the hardware envelope — see clamp_share()
        self.last_share = SOC_BAND_SHARE_NOMINAL
        # DI-LOW-6: None, NOT a seed value. This is the PRE-CLAMP TABLE REQUEST,
        # and before the first decision the table has requested nothing — a
        # seeded SOC_BAND_SHARE_NOMINAL would be written into `cmd_share_sp_raw`
        # as if the policy had asked for 0.50, which is a value it can never
        # ask for (its whole action set is {0.00, 0.90, 0.95, 1.00}). The CSV
        # writer renders None as BLANK, matching the column's own header doc.
        # `last_share` above IS seeded, and correctly so: it is what gets
        # EMITTED on the wire, and something must be.
        self.last_share_raw = None
        self.last_goal = 0.0
        self.last_bin = None
        self.last_soc_rel = None
        # ── minimum-dwell charge hysteresis (see the SDP_CHG_* block) ───────
        # `chg_hold_until` is the decision-clock time the latch expires (None =
        # not holding); `chg_hold_v_ref` is the commanded profile speed the
        # window was admitted on, against which the early-drop test measures.
        self.chg_hold_until = None
        self.chg_hold_v_ref = None
        # Diagnostics only, reported in the exit summary. `chg_holds` counts
        # LATCHES, not physical windows: a hold that expires and immediately
        # re-latches on the corrected demand is 2 here and ONE continuous
        # FC_CHARGE window on the board — which is the whole intent, so the two
        # numbers are supposed to differ.
        self.chg_holds = 0
        self.chg_hold_drops = 0
        self.chg_hold_drop_reason = None

    # ── loading / startup refusal ───────────────────────────────────────────
    def load(self):
        """Load the artifact ONCE.  Raises ValueError to refuse."""
        if self.policy_file == SDP_POLICY_FROM_SCENARIO:
            raise ValueError(
                "the `%s` strategy has NO artifact of its own: it plays the "
                "one its SCENARIO names in `sdp_policy_file`, and nothing has "
                "named one for this run.\n"
                "  Either run it under a scenario that declares "
                "`sdp_policy_file` (see SCENARIOS['ems-sdp-alpha-cal']), or "
                "use a strategy with a registered artifact (`sdp-v4` is the "
                "shipped calibrated benchmark)." % self.name)
        if self.policy is None:
            pol = load_sdp_policy(self.path, self.name)
            # The certificate is checked ON THE LOAD, not in bind_scenario():
            # a direct caller (a test, a probe) that never binds must not be
            # able to drive an uncertified artifact through a frontier-scored
            # strategy either.
            if self.require_calibrated_benchmark:
                self.certificate_allowances = sdp_assert_calibrated_benchmark(
                    pol, self.name)
            self.policy = pol
        return self.policy

    def _verify_pick(self, pol, source):
        """A sweep pick must still BE the artifact the sweep selected.

        REFUSES on a policy-sha mismatch: the offline walk that chose this
        point, and every expectation derived from it, describe THAT decision
        law. An artifact regenerated after the pick was made is a different
        law under a scenario name that claims the pick's leg — a substitution
        with no symptom in the trace. The FILE sha is only warned about: it
        moves on any --force regeneration that changed nothing but the
        timestamp, which is not a change of law."""
        want = source.get("expect_policy_sha256")
        if want and want != pol["policy_sha256"]:
            raise ValueError(
                "the alpha-sweep pick %r in %s selected the policy law "
                "%s, but %s now carries %s.\n"
                "  The artifact was regenerated after the pick was made, so "
                "this run would play a DIFFERENT decision law under a "
                "scenario name that claims the pick's leg — and every "
                "expectation derived from the pick's offline walk would be "
                "measuring the wrong policy.\n"
                "  Re-run the sweep (which rewrites the manifest), or point "
                "the scenario at the artifact directly."
                % (source.get("pick"), source.get("manifest"), want,
                   pol["path"], pol["policy_sha256"]))
        want_file = source.get("expect_file_sha256")
        if want_file and want_file != pol["file_sha256"]:
            print("[hil]   NOTE: the live-picks manifest recorded file sha "
                  "%s… for this pick and the file on disk is %s… — the "
                  "DECISION LAW is unchanged (policy sha matches), so this is "
                  "a regeneration that moved only provenance."
                  % (want_file[:16], pol["file_sha256"][:16]))

    def bind_scenario(self, scenario, meta, electrical_mode=None,
                      args=None, droop_mode=None,
                      asymmetry_mode=None, drag_mode=None):
        """Generic startup hook (see main()).  Loads and validates the policy.

        Unlike DpReplayStrategy's binder this does NOT check the scenario: an
        SDP policy is indexed by STATE, not by time, so it is defined on any
        profile and there is nothing here that could go stale against one.  The
        hook is still implemented so a missing or malformed artifact is refused
        BEFORE a frame is sent rather than mid-run.

        The trailing arguments are part of the hook contract and are accepted
        and ignored deliberately: `--electrical` and `--soc0` do not change
        which policy is correct (the SoC0-relative mapping is what makes the
        second one true — see the banner)."""
        # ── THE SCENARIO-SUPPLIED ARTIFACT (2026-09-02) ─────────────────────
        # `sdp_policy_file` lets a scenario play a DIFFERENT artifact through
        # the same decision code — the mechanism the three alpha-sweep
        # scenarios use. It is restricted at IMPORT to strategies that are NOT
        # frontier-eligible (see the guard below SCENARIOS), so it can never
        # swap the artifact under a leg the frontier scores.
        # Reset FIRST and unconditionally: a scenario that names nothing must
        # get the registered artifact even if a previous bind overrode it.
        self.set_policy_file(None)
        declared = meta.get("sdp_policy_file")
        if declared:
            name, source = resolve_sdp_policy_file(declared, scenario=scenario)
            self.set_policy_file(name, source)
        pol = self.load()
        if self.policy_file_source:
            self._verify_pick(pol, self.policy_file_source)
        self.reset()
        # The scenario's SoC-axis placement (2026-08-31).  Read AFTER reset()
        # because the offset is a BINDING, not run state — reset() must not
        # clear it, and a scenario that declares nothing gets 0.0, i.e. the
        # pre-2026-08-31 behaviour byte for byte.  A malformed value raises,
        # which main() turns into a startup refusal.
        self.set_soc_ref_offset(meta.get("sdp_soc_ref_offset") or 0.0)
        # MED-2: the run's provenance record for THIS artifact, stashed here and
        # copied into the CSV's meta sidecar by main(). It is the answer to
        # "which policy produced these numbers" — a question the CSV alone
        # cannot answer, because a regenerated artifact changes the commands
        # without changing the schema, the scenario or any constant the model
        # fingerprint covers.
        self.provenance = {
            "path": pol["path"],
            "file_sha256": pol["file_sha256"],
            "policy_sha256": pol["policy_sha256"],
            "policy_sha256_recipe":
                "sha256(json.dumps(doc['policy'], sort_keys=True))",
            "generated_utc": pol["generated_utc"],
            "n_soc": pol["n_soc"],
            "n_bins": pol["n_bins"],
            "decision_dt_s": pol["decision_dt_s"],
            "tpm_sha256": pol["tpm_sha256"],
            # DI-MED-3 — THE DEMAND MAP, recorded in the trace itself. v1 and
            # v2 declare the same `schema` and differ chiefly in this range
            # (v1: the TPM sidecar's -1.1248..+1.6398 W; v2: 0..25 W), so
            # without these three fields the sidecar's claim to identify the
            # demand map rested on the reader recognising a sha. Carried, not
            # consumed. `demand_map_source` is None for artifacts that predate
            # the solver recording it.
            "p_dem_min_w": pol["p_dem_min_w"],
            "p_dem_max_w": pol["p_dem_max_w"],
            "demand_map_source": pol["demand_map_source"],
            # The scenario's SoC-axis placement. Recorded because it decides
            # WHICH BRANCH of a bang-bang policy the run starts on, so two
            # traces of the same artifact at different offsets are two
            # different experiments — and the CSV carries no other trace of it.
            "soc_ref_offset": self.soc_ref_offset,
            # ── WP-1B2b (2026-09-02): THE ARTIFACT'S OWN ECONOMICS ──────────
            # A policy sha identifies the decision law but says nothing about
            # WHY it decides that way. These four fields are what a report
            # reader needs to compare two SDP legs without opening either
            # artifact: which alpha priced SoC, how that alpha was derived,
            # and which CHARGER the solve was billed against. `eta_chg` is
            # None for an artifact solved in the 1:1 current-transfer era.
            "alpha": _sdp_doc_alpha(pol),
            "alpha_mode": ((pol.get("raw") or {}).get("alpha") or {}).get("mode"),
            "eta_chg": _sdp_doc_eta_chg(pol),
            "charge_cells": sum(1 for row in pol["charge_goal"]
                                for v in row if v > 0.0),
            # WHICH FILE, and why this one. `policy_file` is the artifact the
            # run played (a scenario override shows up here, not only in the
            # path); `policy_file_source` says whether it came from the
            # strategy's registration, a scenario path, or an alpha-sweep pick.
            "policy_file": self.policy_file,
            "policy_file_source": self.policy_file_source,
            # Certificate clauses waived under an era-scoped allowance. [] on
            # an artifact that met every clause outright, and absent-as-empty
            # is the honest reading for a strategy that demands no certificate.
            "certificate_allowances": list(self.certificate_allowances),
        }
        # ── THE ARTIFACT'S ERA vs THE PLANT'S (2026-09-02) ──────────────────
        # A WARNING, not a refusal, and the asymmetry with the DP table's era
        # check is deliberate. A DP table is the OPTIMUM OF a demand model, so
        # a table from the wrong era bounds nothing and must be refused. An SDP
        # artifact is a CONTROL LAW: it is defined on any plant, it will command
        # a legal share on any plant, and running an old-era law against the new
        # charger is a legitimate — and, for the retained `sdp-v3`, an
        # intended — comparability experiment. What must never happen is that
        # the mismatch goes unrecorded, so it is printed at bind and carried in
        # the sidecar.
        art_eta = _sdp_doc_eta_chg(pol)
        plant_eta = plant_eta_chg()
        self.provenance["plant_eta_chg"] = plant_eta
        self.provenance["era_match"] = (art_eta == plant_eta)
        print("[hil] SDP policy: %s (%d SoC nodes x %d demand bins, target "
              "SoC %.3f on [%.3f, %.3f], demand %.3f..%.3f W, decisions every "
              "%.3g s)"
              % (pol["path"], pol["n_soc"], pol["n_bins"], pol["soc_target"],
                 pol["soc_min"], pol["soc_max"], pol["p_dem_min_w"],
                 pol["p_dem_max_w"], pol["decision_dt_s"]))
        print("[hil]   policy sha256 %s (the DECISION LAW; stable across a "
              "regeneration that did not change it), file sha256 %s, generated "
              "%s"
              % (pol["policy_sha256"], pol["file_sha256"][:16] + "…",
                 pol["generated_utc"] or "(not recorded)"))
        print("[hil] NOTE: `%s` is SIM-ONLY (it closes on plant-truth SoC, "
              "not telemetry) and regulates around the CAPTURED soc0, not the "
              "artifact's absolute target — see the banner above SdpStrategy."
              % self.name)
        if self.require_calibrated_benchmark:
            print("[hil]   role: CALIBRATED BENCHMARK — frontier_eligible, "
                  "scored by run_hil_suite.py's EMS frontier check. Charge "
                  "cells in this artifact: %d (0 = the charge action was "
                  "declined ENDOGENOUSLY, forbid_charge_all False)."
                  % sum(1 for row in pol["charge_goal"] for v in row if v > 0.0))
        else:
            # READ FROM THE REGISTRY (2026-09-02), not written out: there are
            # three non-frontier SDP roles now and they are different claims —
            # a loss-making demonstration (`sdp-v2`), an old-era calibration
            # kept for comparability (`sdp-v3`) and a policy-parameter sweep
            # point (`sdp-sweep`). One hard-coded sentence described the first
            # and was WRONG about the other two, which is exactly the drift
            # EMS_STRATEGY_META's `role_note` exists to prevent.
            note = (EMS_STRATEGY_META.get(self.name) or {}).get("role_note")
            print("[hil]   role: NOT frontier_eligible — this run's "
                  "h2/delta_soc pair is not scored on the EMS frontier.%s"
                  % ("" if not note else "\n[hil]     %s" % note))
        for waived in self.certificate_allowances:
            print("[hil]   CERTIFICATE ALLOWANCE: %s" % waived)
        if self.policy_file_source:
            src = self.policy_file_source
            if src.get("kind") == "live_picks":
                print("[hil]   artifact SUPPLIED BY THE SCENARIO from the "
                      "alpha-sweep live picks: pick %r (leg %s, index %s, "
                      "alpha %s) via %s"
                      % (src.get("pick"), src.get("leg"), src.get("index"),
                         src.get("alpha"), src.get("manifest")))
            else:
                print("[hil]   artifact SUPPLIED BY THE SCENARIO: %s"
                      % src.get("declared"))
        if not self.provenance["era_match"]:
            # ASCII "(!)" deliberately (2026-09-02): this exact string, with a
            # U+26A0 U+FE0F pair in it, raised UnicodeEncodeError on the cp1252
            # console and — because UnicodeEncodeError subclasses ValueError —
            # was caught by main()'s binder guard and reported as "cannot run
            # scenario", so ems-sdp-cross and ems-sdp-braking never launched.
            # Keep every operator-facing string in this file ASCII.
            print("[hil]   (!) CHARGER-ERA MISMATCH: this artifact was solved "
                  "against %s, and this run's plant bills %s. The policy is "
                  "still a valid control law and the run proceeds — an SDP "
                  "artifact is defined on any plant — but its alpha was "
                  "calibrated against a charger this run does not have, so its "
                  "h2/delta_soc pair is a COMPARABILITY measurement, not a "
                  "result about this plant's economics."
                  % (eta_chg_era_label(self.provenance["eta_chg"]),
                     eta_chg_era_label(self.provenance["plant_eta_chg"])))
        if self.soc_ref_offset:
            print("[hil]   soc_ref_offset %+.4f — the run STARTS %.4f %s the "
                  "policy's target node, so its first decisions are on the "
                  "%s branch of the bang-bang law (see set_soc_ref_offset())"
                  % (self.soc_ref_offset, abs(self.soc_ref_offset),
                     "ABOVE" if self.soc_ref_offset > 0 else "BELOW",
                     "battery-heavy 0.00->0.15" if self.soc_ref_offset > 0
                     else "fuel-cell 1.00->0.85"))
        return self

    # ── helpers, kept separate so a test can drive them directly ────────────
    def soc_relative(self, soc):
        """Table-space SoC for a measured one: target + (soc - soc0), clamped."""
        pol = self.policy
        rel = pol["soc_target"] + (float(soc) - float(self.soc_ref))
        return min(pol["soc_max"], max(pol["soc_min"], rel))

    def soc_index(self, soc_rel):
        """NEAREST grid node.  Nearest, not interpolated, is correct for a
        LOOKUP: the policy is a piecewise-constant control law and blending two
        neighbouring actions would command a split neither one chose.  (The
        interpolation requirement in the DP work is SOLVER-side, on the
        cost-to-go J, and is a different question.)  Linear scan is fine at
        ~101 nodes and once per decision_dt_s."""
        grid = self.policy["soc_grid"]
        best, best_d = 0, abs(grid[0] - soc_rel)
        for i in range(1, len(grid)):
            d = abs(grid[i] - soc_rel)
            if d < best_d:
                best, best_d = i, d
        return best

    def demand_bin(self, p_dem_w, count=True):
        """Normalized-and-clamped demand bin for a bus power, in watts.

        `count` drives the clamp diagnostics, so a test (or a caller probing
        the map) can look a value up without polluting the run's counters."""
        pol = self.policy
        span = pol["p_dem_max_w"] - pol["p_dem_min_w"]
        x = (float(p_dem_w) - pol["p_dem_min_w"]) / span
        if x < 0.0:
            x = 0.0
            if count:
                self.clamped_low += 1
        elif x > 1.0:
            x = 1.0
            if count:
                self.clamped_high += 1
        return sdp_bin_index(x, pol["edges"])

    def clamp_share(self, raw, count=True):
        """HARDWARE-ENVELOPE CLAMP on the emitted share.  ACTUATION-SIDE ONLY.

        SocBandStrategy applies exactly this clamp
        (SOC_BAND_SHARE_MIN/MAX = 0.15/0.85), described there as "the assertion
        that this policy can never command a cut, whatever the span is retuned
        to".  The same reasoning binds harder here, because this policy's action
        ladder INCLUDES both rails: a commanded share outside
        [DROOP_R_MIN 0.15, DROOP_R_MAX 0.85] makes
        updateShareSetpointCutoff() (.ino:9231-9257, strict `<`/`>` — 0.15 and
        0.85 themselves are IN band) open the minority channel's bus switch, and
        the surviving channel then carries the WHOLE bus against its own OC
        limit.

        WHY IT IS NOT A POLICY CHANGE.  The baked table is untouched and stays
        faithful to the MATLAB; what is clamped is the SETPOINT THIS RIG CAN
        PHYSICALLY ACTUATE.  The solver's model has no bus-switch topology and
        no per-channel current limit, so its rails are legal in ITS problem and
        illegal in this one — the clamp is where those two envelopes meet, and
        nothing else about the lookup is altered.  The raw value stays visible:
        `last_share_raw` holds it and `clamped_share` counts how often the rails
        were commanded, both reported in the exit summary, so "the policy wants
        the rail" remains a readable finding rather than being erased.

        MARGIN AT THE CLAMP (this rig, `ems-sdp`'s own drain peak ~1.45 A):
          * FC at 0.85          -> 1.23 A, 12 % under LIMIT_I_FC_MAX 1.4 A. The
            firmware's own governor tightens it further — for an IN-BAND
            setpoint it clips to [I_min/I_tot, 1 - I_min/I_tot] =
            [0.207, 0.793] at that load (.ino:9556-9568) — so the DELIVERED
            split is ~0.793 and I_fc ~1.16 A, 17 % of margin.
          * BT minority at the same point: 0.207 x 1.45 = 0.30 A, i.e. exactly
            SHARE_MINORITY_I_MIN_A by construction — the minority channel is
            governed, not floored off.
          * SHARE_CUT_MAX_HANDOFF_A (0.5 A) never enters: it gates the CUT, and
            an in-band setpoint never attempts one.
        """
        lo, hi = SOC_BAND_SHARE_MIN, SOC_BAND_SHARE_MAX
        out = min(hi, max(lo, float(raw)))
        if count and out != float(raw):
            self.clamped_share += 1
        return out

    def charge_hold_status(self, t, fb):
        """State of the minimum-dwell charge latch at `t`, dropping it if due.

        Returns one of:
          None        no latch was in force.
          "active"    the latch holds; the intent is pinned high.
          "expired"   the dwell ran out; the table decides again THIS tick, on
                      the corrected demand, and may re-arm.
          "dropped"   an early exit (fault, or the drive left the admitted
                      cruise); the intent is withdrawn and may NOT re-arm on
                      the same tick.
        Three outcomes rather than a bool because "expired" and "dropped" need
        opposite treatment and collapsing them costs the mechanism its point:
        an EXPIRY must still see the self-load-subtracted demand, or the
        re-decision reads the charger's own draw as load, withdraws, and the
        hold has merely made the chatter slower — which is precisely the
        outcome the offline walk showed at its one residual window boundary.
        A DROP must not, because a drop is a deliberate withdrawal and
        subtracting would help it re-admit the window it just refused.

        Pure decision logic, split out so a test can drive every exit without
        stepping a run.  Called ONCE per decision, from decide()."""
        if self.chg_hold_until is None or t is None:
            return None
        flags = fb.get("fault_flags")
        if flags is not None and (int(flags) & SDP_CHG_ABORT_FAULT_MASK):
            # The board is latched. Holding an intent into State 99 asserts a
            # command chargingControl() will never see, and the window's
            # admission (a healthy cruise) is plainly no longer true.
            # Tested BEFORE expiry: a fault landing on an expiry tick is a
            # withdrawal, not a re-decision.
            self._drop_charge_hold("board faulted")
            return "dropped"
        v_now = fb.get("v_profile")
        if (v_now is not None and self.chg_hold_v_ref is not None
                and abs(float(v_now) - self.chg_hold_v_ref)
                > SDP_CHG_CRUISE_DELTA_MPS):
            # OPERATOR RULING (b), the same one `soc-band`'s causal cruise gate
            # enforces: charging and acceleration are incompatible on this
            # hardware. A window admitted on a cruise does not survive the
            # drive leaving it.
            self._drop_charge_hold("drive left the admitted cruise")
            return "dropped"
        if t >= self.chg_hold_until:
            self._drop_charge_hold("dwell expired")
            return "expired"
        return "active"

    def _drop_charge_hold(self, reason):
        self.chg_hold_until = None
        self.chg_hold_v_ref = None
        self.chg_hold_drop_reason = reason
        if reason != "dwell expired":
            self.chg_hold_drops += 1

    def decide(self, fb, t=None):
        """One decision: measure, look up, latch.  Returns (share, goal).

        `t` is the decision-clock time, used ONLY by the charge hysteresis.
        __call__ passes it; a direct caller may omit it and falls back to
        fb["t"] (telemetry-equivalent), which is what the 50 Hz commander puts
        there.  With neither, the hold is inert and the policy behaves exactly
        as it did before this block — an honest degradation, not a silent one:
        a feedback view with no clock cannot support a dwell."""
        pol = self.policy
        if t is None:
            t = fb.get("t")
        soc = fb.get("soc")
        if soc is None:
            # No SoC term available (a feedback view without plant truth). The
            # SoC axis is HALF this policy's state, so rather than invent a
            # reference the strategy holds at the middle of the grid — the
            # honest "I cannot see this axis" position — and the run's own
            # trace shows a flat command. Same degradation philosophy as
            # SocBandStrategy's deficit = 0.0 fallback.
            soc_rel = pol["soc_target"]
        else:
            if self.soc_ref is None:
                # The captured reference, SHIFTED DOWN by the binding's offset:
                # soc_rel(first decision) = soc_target + soc_ref_offset. The
                # default 0.0 reproduces the original capture exactly. See
                # set_soc_ref_offset().
                self.soc_ref = float(soc) - self.soc_ref_offset
            soc_rel = self.soc_relative(soc)
        # DEMAND = bus power, from TELEMETRY-EQUIVALENT keys only (V_bus, I_fc,
        # I_batt are all in FB_TELEMETRY_EQUIV_KEYS). NOT the fuel cell's stack
        # power and not the motor's mechanical power: the study's P_dem is the
        # load the two sources between them have to meet, which on this board is
        # the bus node.
        p_dem = ((fb.get("V_bus") or 0.0)
                 * ((fb.get("I_fc") or 0.0) + (fb.get("I_batt") or 0.0)))
        # ── minimum-dwell hysteresis, part 2: SELF-LOAD SUBTRACTION ─────────
        # While a charge latch is in force the policy must not read its own
        # charger as demand — that feedback IS the chatter (see the SDP_CHG_*
        # block). V_bus * I_charge is the charger's draw at the bus node, the
        # same node p_dem is measured on; both terms are telemetry-equivalent.
        # Floored at the ARTIFACT'S OWN p_dem_min_w, not at 0: the two products
        # are measured independently, so a sub-milliwatt negative residue would
        # otherwise clamp LOW inside demand_bin() and be counted as a demand-map
        # excursion it is not. (For the shipped v2 artifact the two are the same
        # number — its map starts at 0.0 W — but a map with a negative floor
        # would be distorted by a hard 0, so the domain is what bounds this.)
        hold = self.charge_hold_status(t, fb)
        if hold in ("active", "expired"):
            p_chg = ((fb.get("V_bus") or 0.0) * (fb.get("I_charge") or 0.0))
            p_dem = max(pol["p_dem_min_w"], p_dem - p_chg)
        i_soc = self.soc_index(soc_rel)
        i_bin = self.demand_bin(p_dem)
        self.decisions += 1
        self.last_soc_rel = soc_rel
        self.last_bin = i_bin
        # RAW table action kept alongside the emitted one — see clamp_share().
        self.last_share_raw = pol["share"][i_soc][i_bin]
        self.last_share = self.clamp_share(self.last_share_raw)
        goal = pol["charge_goal"][i_soc][i_bin]
        # ── minimum-dwell hysteresis, part 1: THE LATCH ─────────────────────
        # A hold in force pins the intent HIGH whatever the table now says; a
        # fresh table request opens a new one. Note the asymmetry, and it is
        # deliberate: only a rising edge arms a dwell, so the policy can still
        # decline to charge for as long as it likes.
        if hold == "active":
            goal = SOC_BAND_CHARGE_GOAL
        elif hold == "dropped":
            # An early drop is a deliberate withdrawal. Letting the table
            # re-admit on the same tick would make the fault and cruise exits
            # no-ops whenever the (uncorrected) demand still reads low.
            goal = 0.0
        elif goal > 0.0 and t is not None and not fb.get("regen_commanded"):
            # A REGEN WINDOW MUST NOT ARM AN FC DWELL (2026-09-02).  The dwell
            # is a HOST construct governing the FC-PATH charge windows; inside a
            # regen window the firmware's `regenActive` branch owns the charger
            # and the FC path is shut, so arming a latch here would put a window
            # in `chg_holds` that never existed and would pin the intent high
            # for 8 s after the braking ended.  `regen_commanded` is written by
            # RegenManager.wrap() before this call; it is absent, i.e. False, on
            # every run without a manager, so no existing trace moves.
            self.chg_hold_until = float(t) + SDP_CHG_MIN_DWELL_S
            self.chg_hold_v_ref = (None if fb.get("v_profile") is None
                                   else float(fb["v_profile"]))
            self.chg_holds += 1
        self.last_goal = goal
        return self.last_share, self.last_goal

    def __call__(self, t, fb):
        if self.policy is None:
            # A direct caller (a test, a future tool) that never went through
            # bind_scenario(). Load ONCE, here — and still LOUDLY: a missing or
            # malformed artifact raises rather than defaulting to a 0.5 split,
            # so no path can produce a trace labelled with this strategy's
            # policy's. main() binds at startup, so a bench run never reaches
            # this branch.
            self.load()
        if self.last_t is not None and t < self.last_t:
            self.reset()            # rewind => a new run, not this one's tail
        self.last_t = t

        v_sp = fb.get("v_profile")
        if v_sp is None:
            v_sp = EMS_DEFAULT_CRUISE_MPS

        # DECISION CADENCE. The policy callable runs at PiCommander.PI_CMD_HZ
        # (50 Hz) but the table was solved for stages of `decision_dt_s`, so the
        # lookup is recomputed only on a stage boundary and the two commanded
        # ENERGY fields are HELD in between — which is what a stage-based policy
        # means. mode_cmd and v_setpoint are recomputed EVERY tick regardless:
        # they are not policy outputs (the profile and the Run window are
        # host-side script), and holding them would quantize the drive setpoint
        # to 1 s steps for no reason.
        if self.next_decision_t is None or t >= self.next_decision_t:
            self.decide(fb, t)
            dt = self.policy["decision_dt_s"]
            # Anchor on `t`, not on the previous boundary: a late first call (or
            # a 50 Hz tick that lands just past a boundary) must not accumulate
            # a backlog of missed stages to fire back-to-back.
            self.next_decision_t = t + dt

        in_run = EMS_RUN_ENTRY_S <= t < ems_run_exit(fb, SDP_RUN_EXIT_S)
        if not in_run and self.chg_hold_until is not None:
            # Outside Run the intent is zeroed on emission below, so a surviving
            # latch would be invisible state that could re-assert charge_goal on
            # a Run RE-entry it was never admitted for. Cleared here rather than
            # in decide(), which does not know the Run window.
            self._drop_charge_hold("outside the Run window")
        return {
            "mode_cmd": MODE_HYBRID if in_run else MODE_SAFE,
            "power_share_setpoint": self.last_share,
            "v_setpoint": v_sp,
            # Outside the Run window nothing may be commanded onto the charger
            # path — chargingControl() only runs in State 2, so leaving the
            # intent asserted across the Run exit would be a command the
            # firmware silently ignores (soc-band's and dp-replay's reasoning,
            # verbatim).
            "charge_goal": self.last_goal if in_run else 0.0,
        }

    def summary_line(self):
        """One line for the exit summary, or None if the policy never ran.

        The clamp counters are the point: they are the only place a reader
        learns that the demand axis was saturated for the run.  Under the v2
        demand map (banner above) a HIGH clamp rate is no longer the expected
        reading — it means this rig has moved outside the map the shipped
        policy was solved for, and the answer is a re-solve at a wider map."""
        if not self.decisions:
            return None
        n = self.decisions
        return ("[hil] " + self.name + ": %d decisions, demand bin clamped HIGH on %d "
                "(%.1f %%) and LOW on %d (%.1f %%) — a high clamp rate means "
                "the bench's bus power sat above the artifact's modelled "
                "demand range, so only the SoC axis carried information; under "
                "the shipped 0..25 W consumer map that is a SIGNAL to re-solve "
                "at a wider map, not the contract it was under the retired v1 "
                "ideal-scaling map; SHARE clamped to the "
                "hardware envelope [%.2f, %.2f] on %d decision(s) (%.1f %%) — "
                "the table asked for a rail there and a rail cuts the minority "
                "source off the bus, so the emitted value is clipped; soc_ref "
                "%s (offset %+.4f), final share %.4f (table asked %.4f), "
                "charge_goal %.4f; "
                "charge dwell latches %d (%.1f s each, self-load subtracted), "
                "early drops %d%s"
                % (n, self.clamped_high, 100.0 * self.clamped_high / n,
                   self.clamped_low, 100.0 * self.clamped_low / n,
                   SOC_BAND_SHARE_MIN, SOC_BAND_SHARE_MAX, self.clamped_share,
                   100.0 * self.clamped_share / n,
                   ("%.6f" % self.soc_ref) if self.soc_ref is not None
                   else "(never seen)", self.soc_ref_offset,
                   self.last_share, self.last_share_raw, self.last_goal,
                   self.chg_holds, SDP_CHG_MIN_DWELL_S, self.chg_hold_drops,
                   ("" if self.chg_hold_drop_reason is None
                    else " (last: %s)" % self.chg_hold_drop_reason)))


# TWO instances, registered below.  Construction does NO I/O — see __init__ —
# so having two costs nothing at import, and each loads its own artifact the
# first time it is actually bound or called.  They share every line of logic;
# what differs is the artifact and the ROLE (EMS_STRATEGY_META).
ems_sdp_v2 = SdpStrategy("sdp-v2", SDP_POLICY_FILE_V2)
# DEMOTED 2026-09-02 (the eta era): `sdp-v3` keeps its artifact and its code
# path but is no longer the frontier leg, so it no longer DEMANDS the
# calibrated-benchmark certificate — the certificate is the frontier's
# admission ticket (see sdp_assert_calibrated_benchmark()'s "WHY AT LOAD"), and
# demanding it of a comparability leg would claim a role the leg does not have.
# v3 does still carry the certificate; nothing about the artifact changed.
ems_sdp_v3 = SdpStrategy("sdp-v3", SDP_POLICY_FILE_V3)
# THE SHIPPED CALIBRATED BENCHMARK from 2026-09-02 — see SDP_POLICY_FILE_V4.
ems_sdp_v4 = SdpStrategy("sdp-v4", SDP_POLICY_FILE_V4,
                         require_calibrated_benchmark=True)
# THE SCENARIO-SUPPLIED ROLE: one strategy, no artifact of its own, playing
# whatever its scenario names in `sdp_policy_file`. It exists so an artifact
# that is deliberately OUTSIDE the lever windows (an alpha-sweep point) has a
# registered NON-frontier home, instead of being smuggled through a
# frontier-eligible name whose certificate it could not pass.
ems_sdp_sweep = SdpStrategy("sdp-sweep", SDP_POLICY_FROM_SCENARIO)


# ═════════════════════════════════════════════════════════════════════════════
# ── y-*: the firmware's own 'Y' combined profile, driven from the EMS layer ──
#
# WHAT THIS IS.  A HOST-SIDE re-implementation of the firmware's State-98 'Y'
# combined drive-cycle + power-share profile (PLAN.md Sec 9h,
# teensy_controller.ino:3162-3179 for the table and :7806-7836 for the region
# walk), commanded through the ordinary 22-byte Pi command packet instead of
# the USB serial console.
#
# WHY REBUILD IT ON THE HOST.  The firmware's 'Y' needs an operator at a serial
# console, so it is `operator_required` territory and cannot run in an
# unattended HIL campaign at all.  Driving the same 16-region table from the
# EMS layer makes the profile's cross-coupling excitation — the whole reason
# the table exists — available to `run_hil_suite.py`.
#
# ⚠️ WHAT IS AND IS NOT THE SAME AS A FIRMWARE 'Y' RUN.
#   SAME: the table, verbatim; the interpolation; the clip-AFTER-interpolation
#         rule and its intended kink; the region boundaries.
#   NOT THE SAME: the RATE.  The firmware walks the table on its main loop
#         (~1 kHz) and assigns v_setpoint/power_share_setpoint directly; here
#         the walk is evaluated at PiCommander.PI_CMD_HZ = 50 Hz and the values
#         travel over UDP, so both axes are 20 ms staircases.
#         * The motor axis: the table's steepest ramp is region 4, 0.4 of Vmax
#           over 4.0 s = 0.1*Vmax per second, so one 20 ms step is 0.002*Vmax —
#           2 mm/s at Vmax 1, 6 mm/s at Vmax 3, against the drive loop's
#           e_sat ~= 26.4 mm/s (CLAUDE.md fw v18). Region 7's step at its own
#           entry is a genuine STEP in the firmware too, so nothing is lost
#           there. Worst-case quantisation is ~12 mm/s at Vmax 3 across a
#           boundary where the firmware would also step.
#         * The share axis: the firmware's share loop ticks at 50 Hz
#           (SHARE_CTRL_PERIOD_US 20000), so a 50 Hz command staircase is at
#           the loop's own rate — the share axis is not degraded at all.
#   NOT THE SAME: the firmware's 'Y' also logs to SD and owns the motor through
#         haltMotorOutput(); none of that applies to a Pi-commanded run.
#
# ONE TABLE, ONE WALK.  The firmware keeps ONE table and ONE region walk for
# 'Y' and 'W' precisely so their shapes cannot drift (.ino:7845-7850). The same
# discipline applies across the language boundary: this module has ONE table
# and ONE `y_profile_at()`, and the four registered strategies are closures
# over (vmax, b) produced by ONE factory. A second copy of the table here would
# be a shape that drifts from the firmware's silently.
# ═════════════════════════════════════════════════════════════════════════════

# EXTRACTED VERBATIM from teensy_controller.ino:3162-3179 (COMBINED_PROFILE[]).
# (duration_ms, v_start, v_end, s_start, s_end); v normalised [0..1] and scaled
# by Vmax at runtime, s an ABSOLUTE FC share clipped to [b, 1-b] at runtime.
# Steps land at region ENTRY: a region whose start differs from the previous
# region's end IS the step.
COMBINED_PROFILE = (
    (2000, 0.0, 0.0, 0.50, 0.50),   #  0: settle
    (4000, 0.0, 0.6, 0.50, 0.50),   #  1: v ramp up (solo)
    (2000, 0.6, 0.6, 0.50, 0.50),   #  2: buffer
    (3000, 0.6, 0.6, 0.65, 0.65),   #  3: s step up (solo, intermediate)
    (4000, 0.6, 1.0, 0.65, 0.35),   #  4: BOTH ramp (v up, s down) — interaction
    (2000, 1.0, 0.3, 0.35, 0.35),   #  5: buffer + v ramp DOWN to excursion load
    (1500, 0.3, 0.3, 1.00, 1.00),   #  6: s step to the hi bound (brief)
    (3500, 0.3, 1.0, 0.35, 0.35),   #  7: s step down at LOW load, then v ramps
    (3000, 0.5, 0.5, 0.65, 0.65),   #  8: BOTH step (v down, s up) — interaction
    (2000, 0.5, 0.5, 0.65, 0.65),   #  9: buffer
    (3000, 0.5, 0.5, 0.65, 0.00),   # 10: s ramp down to the lo bound (solo)
    (1500, 0.5, 0.5, 0.00, 0.00),   # 11: lo-bound check (brief)
    (1500, 0.5, 0.5, 0.50, 0.50),   # 12: s step up, recovery to mid
    (2000, 0.2, 0.2, 0.50, 0.50),   # 13: v step down (solo)
    (3000, 0.2, 0.0, 0.50, 0.50),   # 14: v coast-down ramp
    (2000, 0.0, 0.0, 0.50, 0.50),   # 15: end hold -> natural completion
)
COMBINED_PROFILE_MS = sum(r[0] for r in COMBINED_PROFILE)
# The firmware's own documented total (PLAN.md Sec 9h: "a 16-region, 40 s
# table").  Pinned rather than trusted: a mistyped duration is invisible in a
# trace but moves every signal window in the suite entries downstream.
assert COMBINED_PROFILE_MS == 40000, (
    "COMBINED_PROFILE durations sum to %d ms, not the firmware's 40000 — the "
    "table was mistranscribed from teensy_controller.ino:3162-3179"
    % COMBINED_PROFILE_MS)
COMBINED_PROFILE_S = COMBINED_PROFILE_MS / 1000.0


def y_profile_at(t_rel, vmax, b):
    """(v_setpoint, share_setpoint) for the 'Y' table at `t_rel` seconds in.

    Reproduces advanceComboRegion() (.ino:7806-7836) exactly:
      * `tau = elapsed / duration` inside the region, in [0, 1) — a region's END
        value is NEVER emitted; the next region's START value supplies it, which
        is how a step is encoded (start != previous end) and why the walk needs
        no special case for one.
      * BOTH axes interpolate linearly on the same tau.
      * The share is CLIPPED AFTER interpolation, to [b, 1-b].  Never before: a
        ramp crossing the bound must run at its normal slope and then FLATTEN
        there.  Pre-scaling the waypoints into the band would change every slope
        in the table.  The resulting kink is intended behaviour.

    Outside the table: before it, region 0's start (standstill, 0.50 share);
    at or after COMBINED_PROFILE_S, region 15's start — which IS standstill at
    0.50 share, i.e. the same values the firmware's natural completion leaves
    behind.

    DELIBERATE DIFFERENCE from the firmware, and it is invisible at this
    resolution: the firmware SKIPS one tick at each region boundary (it returns
    COMBO_TICK_BOUNDARY and emits nothing).  That is one 1 ms main-loop tick
    there and would be one 20 ms command here; reproducing it would hold a
    stale setpoint for 20 ms at 15 boundaries for no benefit.  This function is
    total: every t_rel yields a value."""
    ms = t_rel * 1000.0
    if ms <= 0.0:
        rg = COMBINED_PROFILE[0]
        return rg[1] * vmax, min(max(rg[3], b), 1.0 - b)
    cum = 0.0
    for dur, v0, v1, s0, s1 in COMBINED_PROFILE:
        if ms < cum + dur:
            tau = (ms - cum) / dur
            v = (v0 + tau * (v1 - v0)) * vmax
            s_abs = s0 + tau * (s1 - s0)
            return v, min(max(s_abs, b), 1.0 - b)
        cum += dur
    rg = COMBINED_PROFILE[-1]
    return rg[1] * vmax, min(max(rg[3], b), 1.0 - b)


# The 'Y' table starts this many seconds into the run: EMS_RUN_ENTRY_S (3.0)
# plus 2 s inside Run before anything moves.  The table's own region 0 is a 2 s
# settle as well, so the board sees 4 s of standstill after entering Run before
# the first ramp — ample for the drive controller's Idle->Run reset to land.
EMS_Y_START_S = 5.0
# Absolute times the table occupies: 5.0 .. 45.0 s.
EMS_Y_END_S = EMS_Y_START_S + COMBINED_PROFILE_S
# MODE_SAFE 1 s after the table completes (it ends at standstill, so there is
# nothing to wind down), leaving the scenario duration's remaining 3 s for
# Run -> Finish -> Idle.  Declared per-scenario as `ems_run_exit_s`.
EMS_Y_RUN_EXIT_S = EMS_Y_END_S + 1.0        # 46.0
EMS_Y_DURATION_S = EMS_Y_RUN_EXIT_S + 3.0   # 49.0

# The bus preload the CLOSED-LOOP ('b30') variants carry, in amps, on top of
# I_AUX_A.
#
# ⚠️ 0.60 -> 0.85 A on 2026-08-31 (ledger fix queue, "scenario tuning").  THIS
# IS A STIMULUS CHANGE: every b30 current, governor bound and margin below moves
# with it, so the campaign-20260831_191509 b30 numbers are NOT comparable with
# any run after this change.  Compare b30 across the boundary only through this
# constant.
#
# WHY IT HAD TO MOVE — THE HI BOUND WAS STRUCTURALLY UNDELIVERABLE.  The b30
# variants clip the share to [0.30, 0.70], and region 6 exists to drive the axis
# ONTO the 0.70 clip.  But the firmware's minority-current governor clips again,
# to [SHARE_MINORITY_I_MIN_A/I_tot, 1 - SHARE_MINORITY_I_MIN_A/I_tot] with
# I_min = 0.30 A, and at region 6's load the second clip was TIGHTER than the
# first.  Model walk at region 6 (v held at 0.3*Vmax, no acceleration):
#
#           preload   I_tot     governor hi bound   0.70 reachable?
#   Vmax 1   0.60 A   0.798 A   1 - 0.30/0.798 = 0.6241   NO
#   Vmax 3   0.60 A   0.915 A   1 - 0.30/0.915 = 0.6723   NO
#   Vmax 1   0.85 A   1.048 A   1 - 0.30/1.048 = 0.7137   yes (+1.9 %)
#   Vmax 3   0.85 A   1.166 A   1 - 0.30/1.166 = 0.7426   yes (+6.1 %)
#
# The campaign measured the two governor rails at 0.632 and 0.679 — the 0.6241
# and 0.6723 rows above, to within the model's error.  So the profile commanded
# a bound the hardware could never deliver, and every b30 run silently
# characterised the GOVERNOR instead of the share clip.  Same story at the low
# bound: at 0.60 A the Vmax-1 governor floor is 0.3597, ABOVE the table's 0.30
# clip, so that bound was undeliverable too; at 0.85 A the floor is 0.2767 and
# both bounds are reachable at both speeds.
#
# WHY 0.85 AND NOT MORE.  The governor bound moves as 1 - I_min/I_tot, so
# reaching 0.70 needs I_tot > 0.30/0.30 = 1.000 A at region 6.  Region 6 is the
# LIGHTEST loaded assertion point in the table (v = 0.3*Vmax, no accel), so it
# binds:  I_AUX_A 0.15 + preload + i_motor(0.3*Vmax) >= 1.000 A.  At Vmax 1 the
# motor contributes 0.048 A there, so preload >= 0.802 A.  0.85 A gives 1.048 A,
# i.e. 4.8 % over the 1.000 A break-even — enough that model error cannot put
# the bound back out of reach, and no more than that.
#
# THE REST OF THE BUDGET at 0.85 A (same model walk, whole table, both speeds):
#   * GATE.  The governor arms the closed share loop only above
#     2*SHARE_MINORITY_I_MIN_A = 0.60 A of source total.  The total now spans
#     1.000-2.274 A (was 0.750-2.023), so the binding standstill case is
#     I_AUX_A 0.15 + 0.85 = 1.000 A, 67 % clear of the gate (was 25 %).
#   * HEADROOM.  Worst per-channel current is FC at region 4's entry, where the
#     table commands share 0.65 on a Vmax-3 load: 0.9986 A against
#     LIMIT_I_FC_MAX 1.4 A, a 28.7 % margin (was 0.836 A / 40 %).  At Vmax 1 the
#     same point is 0.727 A.  Worst BT is 1.475 A against LIMIT_I_BT_MAX 3.0 A,
#     a 51 % margin.  Nothing approaches a limit.
#   * ⚠️ THE PRELOAD RAMP LEAVES THE TABLE'S FIRST FRACTION OF A SECOND BELOW
#     THE GATE, and always did.  scenario_aux_preload_a() ramps the load in
#     linearly over SOC_LOAD_RAMP_S = 3.0 s from AUX_PRELOAD_START_S = 4.0 s,
#     while the table starts at EMS_Y_START_S = 5.0 s.  The gate is crossed when
#     I_AUX_A + preload*ramp >= 0.60 A: at 0.60 A that is t = 6.25 s, i.e. 1.25 s
#     INTO the table; at 0.85 A it is t = 5.59 s, 0.59 s in.  Both fall inside
#     region 0's 2 s settle, so no assertion window is affected — but a reader
#     looking at the trace's opening should expect an open-loop start, and the
#     0.85 A change halves it rather than removing it.
#
# ⚠️ These are the MODEL's currents (M_EFF/K_F/F_COULOMB/B_EFF + the droop bus,
# constants at the top of this file), not measurements. A campaign that misses
# the fc_current_biased check should move THIS number, never the check.
Y_AUX_LOAD_A = 0.85


def make_ems_y(vmax, b):
    """Build a `y-*` policy closure for one (Vmax, share bound) pair.

    ONE factory, for the firmware's own reason (.ino:7845-7850): four
    hand-written policies over one table would be four shapes that drift."""
    def _policy(t, fb):
        v_sp, share = y_profile_at(t - EMS_Y_START_S, vmax, b)
        in_run = EMS_RUN_ENTRY_S <= t < ems_run_exit(fb, EMS_Y_RUN_EXIT_S)
        return {
            "mode_cmd": MODE_HYBRID if in_run else MODE_SAFE,
            "power_share_setpoint": share,
            "v_setpoint": v_sp,
            # Charging is out of scope for this profile: the table rails the
            # share to both bounds, and assertFcChargeEnable() drops BT off the
            # bus, so a charge window here would collide with the cut the
            # profile is deliberately exercising.
            "charge_goal": 0.0,
        }
    _policy.__doc__ = (
        "y-b%02d-v%g — the firmware's 'Y' combined profile (16 regions, %g s) "
        "at Vmax %g m/s and share bound b = %.2f, commanded from the EMS "
        "layer.\n\n"
        "    fields   : mode_cmd (SAFE -> HYBRID at EMS_RUN_ENTRY_S, back to "
        "SAFE at the scenario's ems_run_exit_s), v_setpoint and "
        "power_share_setpoint (both from y_profile_at()), charge_goal (0.0).\n"
        "    feedback : reads ONLY fb['t'] and the scenario's ems_run_exit_s. "
        "It is therefore trivially portable to the real Pi — it depends on "
        "nothing outside FB_TELEMETRY_EQUIV_KEYS.\n"
        "    source   : teensy_controller.ino:3162-3179 (table), :7806-7836 "
        "(walk), PLAN.md Sec 9h."
        % (round(b * 100), vmax, COMBINED_PROFILE_S, vmax, b))
    return _policy


# The four registered variants.  TWO AXES, one objective each:
#   b = 0.30  the firmware's own documented 'Y' bound.  The share never leaves
#             [0.30, 0.70], so it never crosses DROOP_R_MIN/MAX and NO cut can
#             occur; paired with Y_AUX_LOAD_A the share loop is closed for the
#             whole table, and the objective is closed-loop SHARE TRACKING.
#   b = 0.00  no bound: the table's regions 6 and 11 command 1.00 and 0.00
#             outright, which is outside [DROOP_R_MIN 0.15, DROOP_R_MAX 0.85]
#             and DOES trip updateShareSetpointCutoff().  The objective is the
#             CUT-AND-RESTORE topology, so these variants carry NO preload —
#             the cut's own SHARE_CUT_MAX_HANDOFF_A 0.5 A per-channel guard
#             REFUSES the latch above that current, and a preload would put the
#             load exactly where the latch is refused.
#             ⚠️ CONSEQUENCE, stated rather than hidden: without the preload the
#             Vmax-1 variant's source total NEVER reaches the 0.60 A governor
#             gate (model walk: 0.0 % of the table), so its share loop runs
#             OPEN-LOOP FEEDFORWARD for the whole run. That is correct for a
#             topology test and wrong for a tracking one — do not read
#             share-tracking numbers off a b00 run.
#             ⚠️ AND THE Vmax-3 VARIANT IS MOSTLY OPEN-LOOP TOO, which is less
#             obvious and worth a number: campaign 20260831_191509 measured only
#             20.6 % of the run above the gate. (The model walk over the TABLE
#             alone gives 12.7 % — a different denominator, and the two were not
#             reconciled; take 20.6 % as the measurement and 12.7 % as an
#             independent order-of-magnitude agreement, not as a discrepancy
#             anyone has explained.) Either way b00-v3 spends ~4/5 of its run
#             feedforward, so its cut/restore verdicts are sound and any share
#             AMPLITUDE read off it is not.
#   Vmax 1 / 3  the low and high ends of the drive channel's exercised range
#             (3.0 m/s is ML0169's measured hold, CLAUDE.md fw v16).
ems_y_b30_v1 = make_ems_y(1.0, 0.30)
ems_y_b30_v3 = make_ems_y(3.0, 0.30)
ems_y_b00_v1 = make_ems_y(1.0, 0.00)
ems_y_b00_v3 = make_ems_y(3.0, 0.00)


# ═════════════════════════════════════════════════════════════════════════════
# ── mpc-det / mpc-sto: the governor-aware receding-horizon EMS ──────────────
#
# WHAT THIS IS.  `tools/mpc_ems.py` implements a 20-stage, 1 Hz receding-horizon
# controller over the pack SoC whose PREDICTION MODEL carries the firmware's own
# share governor, so the plan it optimises is a plan of DELIVERED splits rather
# than of commanded ones.  Design and adjudication:
#   docs/modeling/mpc_design_20260901.md
#   docs/modeling/mpc_design_20260901/adjudication.md
#
# WHY A LAZY PROXY AND NOT AN INSTANCE.  Every other strategy in the registry is
# constructed at import time because its constructor does no I/O.  `mpc_ems`
# imports `governor_model`, `gen_dp_ems_table` and `charger_model`, and the
# `mpc-sto` variant reads a MATLAB TPM off disk; importing it HERE would create
# an import cycle (mpc_ems imports THIS module through `_load_sim()`) and would
# put file I/O on every `import hil_plant_sim`.  The proxy therefore imports
# inside `bind_scenario()` / `__call__()` — the registration step list of the
# design document, item 1 — and is otherwise a transparent forwarder: `main()`
# reads `.provenance`, `.summary_line()` and the three CSV attributes off it
# exactly as it reads them off an `SdpStrategy`.
#
# ⚠️ `mpc-det` IS A PREVIEW STRATEGY, NOT A CAUSAL ONE.  It reconstructs the
# demand from the scenario's own `ems_v_profile`, which no Raspberry Pi has.
# Its commands are the 22-byte packet's two energy fields and nothing else, so
# the CONTROL is portable; the PREVIEW is not.  Design document section 1.2.
#
# ⚠️ THE INVERSE-CRIME CONDITION.  An offline `ems_walk` of this strategy runs
# the controller's own prediction model as the plant, so a walk can only show
# that the plumbing works and that the plan is self-consistent.  Only the live
# high-fidelity campaign scores it.  Design document section 7.1, Gate 2.
class _MpcProxy:
    """Lazy, import-cycle-free stand-in for `mpc_ems.MpcStrategy`.

    Constructing one does NO import and NO I/O, so it is safe at module import.
    The real strategy is built on the first `bind_scenario()` (or, for a caller
    that never binds, on the first `__call__()`, which then raises the
    strategy's own "bound scenario required" error — the honest failure)."""

    def __init__(self, name):
        self.name = name
        self.impl = None
        # Constructor overrides from the command line (`--mpc-*`).  Applied at
        # BUILD time, so `main()` can set them after this module is imported.
        self.kwargs = {}
        # The forwarded surface, pre-declared so a reader of a CSV row or a
        # sidecar can see what exists before a run has bound anything.
        self.provenance = None

    # -- construction -------------------------------------------------------
    def _build(self):
        if self.impl is None:
            import mpc_ems                      # noqa: F401  (lazy by design)
            self.impl = mpc_ems.make_mpc(self.name, **self.kwargs)
        return self.impl

    def configure(self, **kwargs):
        """Record constructor overrides.  Refuses after the strategy is built:
        a half-configured planner is worse than a loud failure."""
        if self.impl is not None:
            raise RuntimeError("%s is already built; configure() must run "
                               "before bind_scenario()" % self.name)
        self.kwargs.update({k: v for k, v in kwargs.items() if v is not None})
        return self.kwargs

    # -- the strategy surface ----------------------------------------------
    def bind_scenario(self, scenario, meta, electrical_mode=None,
                      args=None, droop_mode=None,
                      asymmetry_mode=None, drag_mode=None):
        """The generic startup hook, FORWARDED (2026-09-02, fix M1).

        `electrical_mode`, `droop_mode` and `asymmetry_mode` used to be dropped
        here on the argument that the MPC's prediction model is the scenario's
        demand preview and no plant mode changes it.  That stopped being true
        when the preview gained a demand-model era: the four MPC scenarios are
        `electrical: "any"`, so the same scenario key would have made the
        planner predict on the hi-fi static-loss map during a `--electrical
        simple` or `--droop measured` run, while the sidecar and
        `hil_report_analysis.matched_dp_for_run()` both resolve the era from
        the run's own configuration and would record `None`. Plan and bound on
        two different demand models is precisely what this round removed, so
        the modes are forwarded and MpcStrategy.bind_scenario() reconciles
        them. `args` is still dropped.

        `drag_mode` (2026-09-02) is forwarded for the identical reason one step
        further on: the road-load profile changes the DEMAND PREVIEW itself, and
        `--drag` can override the scenario key, so a planner reading the key
        alone would predict on a cycle the run is not driving."""
        impl = self._build()
        self.provenance = impl.bind_scenario(
            scenario, meta, electrical_mode=electrical_mode,
            droop_mode=droop_mode, asymmetry_mode=asymmetry_mode,
            drag_mode=drag_mode)
        return self.provenance

    def reset(self):
        if self.impl is not None:
            self.impl.reset()

    def __call__(self, t, fb):
        return self._build()(t, fb)

    def summary_line(self):
        return None if self.impl is None else self.impl.summary_line()

    def timing(self):
        return None if self.impl is None else self.impl.timing()

    # -- the three CSV columns (design document section 8, item 5) ----------
    # Read through `getattr` at the row site, exactly as `cmd_share_sp_raw` is,
    # so a non-MPC run writes a BLANK rather than a fabricated 0.
    @property
    def solve_ms_last(self):
        return None if self.impl is None else self.impl.solve_ms_last

    @property
    def share_pred_err(self):
        return None if self.impl is None else self.impl.share_pred_err

    @property
    def budget_hit_last(self):
        """The LAST DECISION's budget flag, held until the next decision.

        `mpc_ems.MpcStrategy` keeps a cumulative `budget_hits` counter and the
        per-decision flag lives on the `Decision` object, which does not
        survive `decide()`.  Deriving the flag from the counter's motion is
        exact — the counter increments once per budget-expired decision and
        never otherwise — and needs no change to that module."""
        return None if self.impl is None else self._budget_hit_held

    # Held state for the derivation above.  None until the first decision, so
    # the column is BLANK before the controller has decided anything — never 0,
    # which would read as "the budget was met" on a run that had not solved yet.
    _budget_hit_held = None
    _hits_seen = 0
    _decisions_seen = 0

    def observe_decision(self):
        """Called once per simulated tick by the CSV row site.  Cheap: two
        integer reads and a comparison.  When the DECISION counter has moved
        since the last tick, the held flag becomes 1 if the BUDGET-HIT counter
        moved with it and 0 otherwise; between decisions the flag stands."""
        if self.impl is None:
            return
        d, n = self.impl.decisions, self.impl.budget_hits
        if d < self._decisions_seen:            # a reset(): a new run
            self._budget_hit_held = None
            self._hits_seen = 0
        elif d > self._decisions_seen:
            self._budget_hit_held = 1 if n > self._hits_seen else 0
            self._hits_seen = n
        self._decisions_seen = d


ems_mpc_det = _MpcProxy("mpc-det")
ems_mpc_sto = _MpcProxy("mpc-sto")

# ── THE DETERMINISTIC CANDIDATE CAP FOR A CAMPAIGN LEG (2026-09-02) ─────────
# THE PROBLEM IT SOLVES.  The planner's search is bounded by WALL CLOCK
# (`budget_ms`), so a loaded campaign host evaluates fewer candidates than an
# idle one and can return a different — still feasible, still validated —
# command.  `max_candidates` is a SECOND, deterministic bound: the search stops
# after this many evaluations whatever the clock says, so two runs of one leg
# explore the same set.
#
# WHY 1029 AND NOT A ROUND NUMBER.  It is the full enumeration at the shipped
# ladder and move-block structure (7 share levels over 3 move blocks, 7**3 =
# 343) TIMES the maximum number of charge plans a decision offers
# (`mpc_ems.MAX_CHARGE_OPTIONS` = 3: no-charge, the 8 s minimum dwell, and the
# full admissible segment).  The cap is therefore EXHAUSTIVE at the shipped
# configuration and constrains nothing — it removes the clock's influence
# without removing any candidate.
#
# ⚠️ IT WAS 343 UNTIL 2026-09-02, AND THAT COST A CAMPAIGN'S CHARGE READING.
# 343 is ONE charge option's worth of candidates, and the planner enumerates the
# share ladder once per charge plan with the no-charge plan FIRST — so every
# capped decision was truncated BEFORE the charge axis was reached (13 of 61
# decisions on `ems-mpc-det`).  "The MPC chose not to charge" was not a
# supported reading of any leg of campaign 20260902_011926.  Any future change
# to the ladder, the move blocks or the charge-option count must move this
# constant with it; `test_mpc_campaign_cap_is_the_full_enumeration` pins it
# against `mpc_ems.enumeration_size()` (the modules cannot import each other —
# mpc_ems imports THIS one — so the pin is a test, not an assert here).
#
# ⚠️ A `--mpc-share-levels` or `--mpc-horizon` override changes the enumeration
# size and this constant does NOT follow it; a leg run with either flag is
# capped below its own enumeration and is a different experiment. State that
# when you use one.
#
# ⚠️ IT DOES NOT MAKE AN MPC RUN BIT-REPRODUCIBLE END TO END. The cap bounds the
# candidate COUNT; the roll-table slicing (`roll_budget_ms`) is still wall-clock
# bounded, and the board's own timing is not deterministic either. An MPC run
# must never enter a repeatability ledger beside the `scp` i_cut or `ems-sdp` h2
# records.
# ⚠️ 1029 -> 2187 (2026-09-02, the grid-widening round).  The cap is the FULL
# enumeration at the shipped ladder, which is what makes it remove the wall
# clock from the candidate count without dropping a candidate: 9 ladder points
# over three move blocks is 9**3 = 729, times the three charge options, is
# 2187.  Measured at 0 % budget expiry over 183 decisions x 3 repeats.
MPC_CAMPAIGN_MAX_CANDIDATES = 2187


def resolve_asymmetry_dv0_v(asymmetry_mode, electrical=None, plant=None):
    """The converter-asymmetry DeltaV0 the run ACTUALLY injects, in volts.

    ONE OWNER FOR ONE QUANTITY.  The banner, the sidecar's `config.asymmetry`
    block and the MPC's plant model must all quote the same number, and before
    this helper each site recomputed it: the banner from `electrical` or the
    mode, the sidecar from `plant` or `electrical`.  A reader comparing a
    banner against a sidecar was comparing two derivations.

    Resolution order, and why it is this order:

    - a HI-FI engine, when one exists, is the authority.  It holds the two
      Boost objects that carry the offset, and its `asym_dv0_v` is already net
      of the sense-arm subtraction `--noise` forces (`asymmetry_dv0_v()`).
    - the PLANT, in simple mode, for the same reason: the static asymmetry law
      of `_apply_simple_asymmetry()` reads `plant.asym_dv0_v` directly.
    - failing both (the banner runs BEFORE the plant is constructed), the mode
      alone: `off` injects nothing, and anything else injects the fitted value
      at zero INA offsets.

    PURE.  `--asymmetry off` resolves to exactly 0.0 on every branch, which is
    the property the MPC's `dv0_v=0.0` shipped default has to keep meaning."""
    if electrical is not None:
        return float(electrical.asym_dv0_v)
    if plant is not None:
        return float(plant.asym_dv0_v)
    if asymmetry_mode == "off":
        return 0.0
    return float(asymmetry_dv0_v(0.0, 0.0))


def parse_share_band(text):
    """`"LO,HI"` -> (lo, hi), refusing anything a ladder cannot be built on.

    PURE, and it raises ValueError rather than returning a sentinel: an
    unparseable band silently falling back to the default would run a campaign
    under the shipped controller while the operator believed otherwise."""
    parts = [p.strip() for p in str(text).split(",")]
    if len(parts) != 2:
        raise ValueError("--mpc-share-band takes LO,HI; got %r" % (text,))
    lo, hi = float(parts[0]), float(parts[1])
    if not (0.0 <= lo < hi <= 1.0):
        raise ValueError("--mpc-share-band needs 0 <= LO < HI <= 1; got %r"
                         % (text,))
    return (lo, hi)


def mpc_configure_kwargs(args, meta, dv0_v=None):
    """The `--mpc-*` flags and the scenario's own MPC keys, as constructor
    kwargs.  PURE.  Every flag defaults to None and every None is DROPPED, so
    an untouched command line reproduces the shipped controller — with ONE
    exception, `dv0_v`, which is always resolved and always passed (see below).

    `dv0_v` names the converter-asymmetry offset the PLANT injects.  A caller
    that has the run's engines resolves it once and hands it in; `None` means
    "resolve it from `args` alone", which is what a test or an ad-hoc caller
    without an engine gets."""
    out = {}
    for flag, kw in (("mpc_horizon", "horizon"),
                     ("mpc_share_levels", "share_levels"),
                     ("mpc_budget_ms", "budget_ms"),
                     ("mpc_roll_budget_ms", "roll_budget_ms"),
                     ("mpc_terminal_price", "terminal_price_mode"),
                     ("mpc_h2_map", "h2_map")):
        v = getattr(args, flag, None)
        if v is not None:
            out[kw] = v
    # SCENARIO-LEVEL SOLVE BUDGET (2026-09-02, campaign C).  The command line
    # still wins; a scenario key is the fallback, and its absence leaves
    # `BUDGET_MS_DEFAULT` exactly as the design ships it.  It exists because
    # the budget is a per-STIMULUS quantity: the same search on a stimulus with
    # more reachable states spends longer, and `ems-mpc-cross` expired on
    # 57.4 % of its decisions after the candidate cap was lifted while
    # `ems-mpc` expired on 6.6 %. Raising the budget for that leg is the only
    # response that does not change the SEARCH itself.
    if out.get("budget_ms") is None:
        _sb = (meta or {}).get("mpc_budget_ms")
        if _sb is not None:
            out["budget_ms"] = float(_sb)
    band = getattr(args, "mpc_share_band", None)
    if band is not None:
        out["share_band"] = parse_share_band(band)
    # A DETERMINISTIC candidate cap, when the strategy offers one.  It is the
    # only lever that makes an MPC run reproducible — the search is otherwise
    # bounded by WALL CLOCK, so a loaded campaign host explores fewer candidates
    # than an idle one.  Passed only if the constructor accepts it, so this
    # module works against a `mpc_ems` that predates the cap; refused loudly if
    # the operator asked for one and the strategy has none, because silently
    # dropping it would leave the run non-reproducible while the command line
    # said otherwise.
    cap = getattr(args, "mpc_max_candidates", None)
    if cap is None:
        # SCENARIO DEFAULT.  Every registered MPC leg declares it, so a campaign
        # run is deterministic without an operator remembering a flag; an
        # ad-hoc `--ems mpc-det` on some other scenario keeps the constructor's
        # own default (no cap), which is the shipped controller.
        cap = (meta or {}).get("mpc_max_candidates")
    if cap is not None:
        if not mpc_supports_kwarg("max_candidates"):
            raise ValueError(
                "--mpc-max-candidates was given but this checkout's "
                "mpc_ems.MpcStrategy has no `max_candidates` argument; the run "
                "would be wall-clock bounded and NOT reproducible")
        out["max_candidates"] = int(cap)
    # ── THE CONVERTER ASYMMETRY, MODELLED (2026-09-02) ─────────────────────
    # THE ONE KWARG THAT IS ALWAYS PASSED, and deliberately not a flag.  It is
    # not a controller tuning choice; it is a PROPERTY OF THE PLANT THIS RUN
    # DRIVES, and the planner maps the open-loop droop ratio through
    # `GovernorModel.delivered_share()` with it.  Left at the shipped 0.0 the
    # MPC's open-stage share prediction error measures 0.016211 against the
    # plant's own dV0 of 0.013522 V, and 0.000323 with it passed — the largest
    # remaining prediction-error term, and the operator's standing ruling is
    # that the MPC must model as many firmware/plant nonlinearities as it can.
    #
    # ⚠️ IT MUST BE THE VALUE THE RUN INJECTS, NOT THE FITTED CONSTANT.  Under
    # `--noise` the sense-arm equivalent is subtracted (`asymmetry_dv0_v()`),
    # so the injected residual is near zero; a planner handed ASYM_DV0_V there
    # would model an asymmetry the plant does not have.  `main()` therefore
    # hands in the engine-resolved value and this fallback is used only by a
    # caller that has no engine.
    #
    # A CHECKOUT WHOSE `mpc_ems` PREDATES THE ARGUMENT is tolerated only while
    # the asymmetry is OFF, where dropping the kwarg changes nothing.  With a
    # live asymmetry it is refused loudly: running a plant-unaware planner
    # against an asymmetric plant is the defect this key exists to close.
    if dv0_v is None:
        dv0_v = resolve_asymmetry_dv0_v(
            getattr(args, "asymmetry", ASYMMETRY_MODE_DEFAULT))
    dv0_v = float(dv0_v)
    if mpc_supports_kwarg("dv0_v"):
        out["dv0_v"] = dv0_v
    elif dv0_v != 0.0:
        raise ValueError(
            "this run injects a converter asymmetry of %+.6f V but this "
            "checkout's mpc_ems.MpcStrategy has no `dv0_v` argument; the "
            "planner would predict the delivered share on a symmetric plant"
            % dv0_v)
    # NOT read here: `mpc_soc_ref_offset`.  MpcStrategy.bind_scenario() reads it
    # off `meta` itself (it is a BINDING, applied after reset()), exactly as
    # SdpStrategy.bind_scenario() reads `sdp_soc_ref_offset`.  Passing it as a
    # constructor kwarg as well would give one quantity two owners.
    return out


def mpc_supports_kwarg(name):
    """Whether this checkout's `mpc_ems.MpcStrategy` accepts `name`.  Imports
    lazily, for _MpcProxy's reasons, and returns False if the module is absent
    (a checkout without the MPC still imports this one)."""
    try:
        import inspect
        import mpc_ems
        return name in inspect.signature(mpc_ems.MpcStrategy).parameters
    except Exception:
        return False


# ⚠️ BEFORE ADDING ONE: read the SHARE AUTHORITY DISAPPEARS BELOW 0.55 A note in
# the MODE A block above.  A policy commanding an FC-heavy or BT-heavy split at a
# source total under 0.55 A gets the LAST CONVERGED split, not its command — the
# firmware holds in open-loop mode by design — and an offline walk that assumes
# otherwise has been wrong twice, most recently by 5.7x on `ems-sdp-cross`
# (campaign 20260901_024231).
EMS_STRATEGIES = {
    "hold-5050": ems_hold_5050,
    "regen-harvest": ems_regen_harvest,
    # `regen-harvest` plus FC-path charge windows at low cruise, for the
    # `mppt-tracking` scenario.  A SEPARATE function, deliberately: charge-regen's
    # measurements are pinned across five campaigns and must not move because
    # this scenario's windows did.  See ems_mppt_harvest().
    "mppt-harvest": ems_mppt_harvest,
    # WP-C: hard braking for genuine energy capture — see ems_regen_harvest_hard().
    "regen-harvest-hard": ems_regen_harvest_hard,
    # ⚠️ SIM-ONLY: soc-band closes on fb["soc"], which is PLANT TRUTH and is NOT
    # in FB_TELEMETRY_EQUIV_KEYS — it is not portable to a real Pi without a
    # V_batt-based SoC estimator (future work).  See the banner above the class.
    "soc-band": ems_soc_band,
    # ⚠️ NON-CAUSAL / OFFLINE-OPTIMAL BENCHMARK, not a controller and not
    # portable to any Pi: it replays a table computed offline with full
    # foreknowledge of ONE drive cycle.  Refuses at startup against any other
    # profile.  See the banner above DpReplayStrategy.
    "dp-replay": ems_dp_replay,
    # ⚠️ SIM-ONLY: sdp-v2 closes on fb["soc"] (PLANT TRUTH, not in
    # FB_TELEMETRY_EQUIV_KEYS) exactly as soc-band does, so it is not portable
    # to a real Pi without a V_batt-based SoC estimator (future work).  CAUSAL,
    # unlike dp-replay: the table is indexed by STATE, not by time, so it is
    # defined on any profile.  Refuses at startup if its baked policy is
    # missing or malformed.  See the banner above SdpStrategy — in particular
    # the SoC0-RELATIVE regulation decision and the demand-axis clamp.
    # ⚠️ TWO ROLES since 2026-09-01, and the names are not interchangeable:
    # `sdp-v3` is THE CALIBRATED BENCHMARK (frontier-scored, zero charge cells
    # by ENDOGENOUS rejection) and `sdp-v2` is the byte-frozen DYNAMICS
    # DEMONSTRATION whose charge cells the `ems-sdp-cross`/`ems-sdp-braking`
    # scenarios exist to actuate.  EMS_STRATEGY_META below carries the roles.
    # ⚠️ FOUR SDP NAMES since 2026-09-02, and they are not interchangeable:
    # `sdp-v4` is THE CALIBRATED BENCHMARK for the eta_chg = 0.88 charger
    # (frontier-scored), `sdp-v3` the SAME calibration for the retired 1:1
    # charger (kept for comparability, off the frontier), `sdp-v2` the
    # byte-frozen DYNAMICS DEMONSTRATION whose charge cells the
    # `ems-sdp-cross`/`ems-sdp-braking` scenarios exist to actuate, and
    # `sdp-sweep` the artifact-less role that plays whatever its scenario
    # names.  EMS_STRATEGY_META below carries the roles.
    "sdp-v2": ems_sdp_v2,
    "sdp-v3": ems_sdp_v3,
    "sdp-v4": ems_sdp_v4,
    "sdp-sweep": ems_sdp_sweep,
    # The firmware's own 'Y' combined drive-cycle + power-share table (16
    # regions, 40 s), commanded from the EMS layer instead of the USB console.
    # All four read ONLY fb["t"] and the scenario's ems_run_exit_s, so all four
    # are portable to a real Pi.  See make_ems_y() and the banner above it.
    "y-b30-v1": ems_y_b30_v1,
    "y-b30-v3": ems_y_b30_v3,
    "y-b00-v1": ems_y_b00_v1,
    "y-b00-v3": ems_y_b00_v3,
    # ⚠️ SIM-ONLY for the same reason `soc-band` and the SDP family are: the
    # planner closes on fb["soc"], which is PLANT TRUTH.  `mpc-det` additionally
    # reads the scenario's own speed profile as PREVIEW — see the _MpcProxy
    # banner.  Both are LAZY PROXIES, not instances.
    "mpc-det": ems_mpc_det,
    "mpc-sto": ems_mpc_sto,
}

EMS_NAMES = list(EMS_STRATEGIES)


# ═════════════════════════════════════════════════════════════════════════════
# EMS STRATEGY ROLES (2026-09-01)
#
# A SIBLING registry keyed by the same names rather than a change of
# EMS_STRATEGIES' value type: `--ems` dispatch, every scenario's `ems` key and
# every test call site consume EMS_STRATEGIES[name] AS A CALLABLE, and turning
# it into a dict would touch all of them for metadata none of them read.  The
# import assert below pins the two registries to the same key set, which is the
# property a single dict would have given for free.
#
#   policy_file        the baked artifact this strategy plays, or None for a
#                      strategy that computes its own commands.  Recorded so a
#                      reader can see WHICH file a name binds without opening
#                      the class, and so a future artifact swap has one place
#                      to be reviewed.  (`dp-replay` is None here: its table is
#                      selected PER SCENARIO by fingerprint, not by a fixed
#                      file, and naming one would be a lie about the binding.)
#   frontier_eligible  whether a run of this strategy may be scored on the EMS
#                      FRONTIER (run_hil_suite.py's EMS_FRONTIER / eq-H2 check).
#
# WHAT `frontier_eligible: False` MEANS, because it is a claim about the RUN and
# not about the code: the strategy is exercised for the MECHANISM it puts on
# the wire, and its hydrogen/SoC pair is not an energy-management result that
# belongs in a ranking.  `sdp-v2` is the case that forced the field — its alpha
# admits an Ag105 charge lever the campaign-measured exchange rate prices as
# loss-making, so its h2 total is a demonstration of the charge threshold, not
# a competitive score.  The frontier check EXCLUDES such runs by construction
# and the report renders them under a demonstration banner rather than silently
# omitting them.
# L9: `role_note` — WHY a strategy is off the frontier, per strategy.  The
# shared demonstration banner says "not on the frontier"; this says which KIND
# of off-frontier run it is, and the two kinds are not interchangeable:
#   * a POLICY DEMONSTRATION (sdp-v2) has an energy objective and pursues it —
#     its h2/delta_soc pair is a real, measurable, and deliberately LOSS-MAKING
#     result, kept because the mechanism it exercises is the point;
#   * a STIMULUS (hold-5050, the y-* replays, regen-/mppt-harvest) has NO
#     objective at all — its h2/delta_soc pair is an artefact of a fixed
#     command profile and ranking it against anything is a category error.
# Optional: a strategy with no note renders the shared banner alone.
_Y_PROFILE_ROLE_NOTE = (
    "ROLE: a STIMULUS WITH NO OBJECTIVE — the firmware's own State-98 'Y' "
    "table replayed from the EMS layer. It commands a fixed setpoint pair on a "
    "schedule and optimizes nothing; its energy totals describe the table.")
EMS_STRATEGY_META = {
    "hold-5050":     {"policy_file": None, "frontier_eligible": False,
                      "role_note": "ROLE: a STIMULUS WITH NO OBJECTIVE — a "
                                   "constant 0.5 split. It optimizes nothing, "
                                   "so its energy totals are a property of the "
                                   "cycle, not of a policy."},
    "regen-harvest": {"policy_file": None, "frontier_eligible": False,
                      "role_note": "ROLE: a STIMULUS WITH NO OBJECTIVE — it "
                                   "opens the charge path inside scripted "
                                   "braking windows to exercise the path, and "
                                   "makes no energy claim."},
    "regen-harvest-hard": {"policy_file": None, "frontier_eligible": False,
                           "role_note": "ROLE: a STIMULUS WITH NO OBJECTIVE — it "
                                        "brakes hard enough to put measurable "
                                        "joules through the regen path, and makes "
                                        "no energy-management claim."},
    "mppt-harvest":  {"policy_file": None, "frontier_eligible": False,
                      "role_note": "ROLE: a STIMULUS WITH NO OBJECTIVE — it "
                                   "exists to provoke the Ag105 MPPT "
                                   "release/re-assert hunt, and makes no "
                                   "energy claim."},
    # The causal HEURISTIC leg — the frontier's reference point (the eq-H2
    # arithmetic is anchored on its delta_soc).
    "soc-band":      {"policy_file": None, "frontier_eligible": True},
    # The NON-CAUSAL lower bound.  On the frontier as the bound, not as a
    # controller: it is not implementable and the check compares AGAINST it.
    "dp-replay":     {"policy_file": None, "frontier_eligible": True},
    # THE DYNAMICS DEMONSTRATION — see the banner above and
    # SDP_POLICY_FILE_V2's block.
    "sdp-v2":        {"policy_file": SDP_POLICY_FILE_V2,
                      "frontier_eligible": False,
                      "role_note": "ROLE: a LOSS-MAKING POLICY DEMONSTRATION — "
                                   "unlike the stimulus legs this one DOES "
                                   "optimize an objective, and its objective's "
                                   "alpha prices SoC low enough that it opens "
                                   "the Ag105 charger. That charging is "
                                   "measurably loss-making at this rig's scale "
                                   "(campaign 20260901_000816 measured the leg "
                                   "9.9 pp off the frontier), which is exactly "
                                   "the mechanism the run exists to show. Its "
                                   "h2/delta_soc pair is a real result about a "
                                   "policy that was NOT calibrated for this "
                                   "rig — not a competitive score, and not an "
                                   "artefact either."},
    # THE OLD-ERA CALIBRATION, demoted 2026-09-02 — see SDP_POLICY_FILE_V4.
    "sdp-v3":        {"policy_file": SDP_POLICY_FILE_V3,
                      "frontier_eligible": False,
                      "role_note":
                          "ROLE: an OLD-ERA CALIBRATION retained for "
                          "COMPARABILITY — this artifact's alpha "
                          "(0.1629624) was calibrated against the 1:1 "
                          "current-transfer charger the plant no longer "
                          "models. It is a real, correctly calibrated "
                          "policy for a charger this run does not have, "
                          "so its h2/delta_soc pair belongs beside a "
                          "campaign of the same era (<= 20260901_151156), "
                          "not beside an eta_chg = 0.88 run. `sdp-v4` is "
                          "the same calibration re-solved for the current "
                          "charger and is the frontier leg."},
    # THE CALIBRATED BENCHMARK for the eta_chg = 0.88 charger.
    "sdp-v4":        {"policy_file": SDP_POLICY_FILE_V4,
                      "frontier_eligible": True},
    # THE SCENARIO-SUPPLIED ROLE — the alpha-sweep legs' home.
    "sdp-sweep":     {"policy_file": SDP_POLICY_FROM_SCENARIO,
                      "frontier_eligible": False,
                      "role_note":
                          "ROLE: a POLICY-PARAMETER SWEEP POINT — the run "
                          "plays an artifact its SCENARIO names, taken from "
                          "the alpha sweep, and the sweep's points sit "
                          "OUTSIDE the two admission windows by design. Like "
                          "`sdp-v2` it optimizes a real objective and its "
                          "h2/delta_soc pair is a real measurement OF THAT "
                          "OBJECTIVE — it is the alpha sweep's live evidence, "
                          "not a competitive score, and it must not be ranked "
                          "against the calibrated leg."},
    # The firmware's 'Y' table replayed from the EMS layer: a STIMULUS, not an
    # energy-management law — it commands a fixed profile and has no objective.
    "y-b30-v1":      {"policy_file": None, "frontier_eligible": False,
                      "role_note": _Y_PROFILE_ROLE_NOTE},
    "y-b30-v3":      {"policy_file": None, "frontier_eligible": False,
                      "role_note": _Y_PROFILE_ROLE_NOTE},
    "y-b00-v1":      {"policy_file": None, "frontier_eligible": False,
                      "role_note": _Y_PROFILE_ROLE_NOTE},
    "y-b00-v3":      {"policy_file": None, "frontier_eligible": False,
                      "role_note": _Y_PROFILE_ROLE_NOTE},
    # THE GOVERNOR-AWARE RECEDING-HORIZON CONTROLLER (2026-09-02).
    # `policy_file` is None: `mpc-det` bakes no artifact at all, and `mpc-sto`
    # reads a TPM rather than a policy table — the key names the POLICY FILE a
    # strategy plays, and a transition-probability matrix is a model input, not
    # a decision law.  Its path is recorded in the sidecar's `config.mpc`
    # (`tpm_path`), which is where a reader of a `mpc-sto` run looks.
    # ⚠️ THE ROLES SWAPPED 2026-09-02 (operator ruling). `mpc-sto` is now THE
    # MPC: it is the frontier candidate of the `cycle61-mpc` and `ftp75-mpc`
    # tuples, and `ems-mpc`, `ems-mpc-cross` and `ems-ftp75-mpc` bind it.
    # `mpc-det` is the ABLATION, run on `ems-mpc-det` (the scenario formerly
    # named `ems-mpc-sto`) against `ems-mpc`'s identical stimulus, so the pair
    # measures THE VALUE OF PREVIEW and nothing else.
    "mpc-det":       {"policy_file": None,
                      "frontier_eligible": False,
                      "role_note":
                          "ROLE: THE DETERMINISTIC ABLATION, NOT A FRONTIER "
                          "CANDIDATE. It optimizes the same objective as "
                          "`mpc-sto` but reads its demand off the scenario's "
                          "own speed profile instead of the demand TPM's "
                          "conditional mean, and leaves the overcurrent bound "
                          "at its nominal value. That preview is the stimulus "
                          "it is scored on, so a frontier ranking would credit "
                          "the policy for foreknowledge no causal controller "
                          "has. Its value is the DIFFERENCE against `mpc-sto` "
                          "on the same stimulus (`ems-mpc-det` against "
                          "`ems-mpc`), which is the value of preview: campaign "
                          "20260902_011926 measured it at -22.5 % hydrogen for "
                          "+38.7 % drain, i.e. 0.36 % of equivalent hydrogen. "
                          "Do not register a frontier tuple on it."},
    "mpc-sto":       {"policy_file": None,
                      "frontier_eligible": True,
                      "role_note":
                          "ROLE: THE FRONTIER MPC since 2026-09-02. It "
                          "replaces the scenario preview with the demand TPM's "
                          "conditional mean and tightens the overcurrent bound "
                          "to that distribution's 90 % quantile (adjudication "
                          "section 2.5), so it is causal in its demand where "
                          "`mpc-det` is not. ⚠️ STATED LIMIT, and it is a "
                          "FAILING GATE, not a caveat: offline Gate 1 fails on "
                          "`ems-soc-band` with a share-prediction error of "
                          "mean 0.00971 and max 0.25000 against a 5e-03 "
                          "acceptance. The mechanism is known — a 1 Hz "
                          "re-command landing in an `open_feedforward` stage "
                          "drops the governor into a feedforward slew the "
                          "stage model does not represent, and 50.6 % of that "
                          "stimulus is open-loop. Campaigns 20260902_011926 "
                          "and _041414 measured the board-side error at "
                          "closed-loop median 1e-5 and open-loop max 0.219, "
                          "inside the 0.30 provisional band, which is why the "
                          "leg ships. ⚠️ ALSO STATED: the demand TPM is a road "
                          "vehicle's and its 0.762 diagonal makes "
                          "short-horizon prediction near-persistence, so no "
                          "stimulus in this suite is a draw from that matrix "
                          "and a frontier reading here carries the "
                          "stimulus-matrix mismatch inside it."},
}

# The property a single registry would have given for free.  A strategy added
# to one dict and not the other is either a nameless role (the frontier check
# would silently treat it as ineligible) or a role with no strategy.
assert set(EMS_STRATEGY_META) == set(EMS_STRATEGIES), (
    "EMS_STRATEGY_META and EMS_STRATEGIES must cover the SAME strategy names; "
    "meta-only %r, strategy-only %r"
    % (sorted(set(EMS_STRATEGY_META) - set(EMS_STRATEGIES)),
       sorted(set(EMS_STRATEGIES) - set(EMS_STRATEGY_META))))
for _mn, _mm in EMS_STRATEGY_META.items():
    assert isinstance(_mm.get("frontier_eligible"), bool), (
        "EMS_STRATEGY_META[%r] must declare `frontier_eligible` as a bool — "
        "a missing/None value would read as 'not on the frontier' by accident "
        "rather than by decision." % (_mn,))
    # A strategy that plays a baked artifact must NAME it, so the role table is
    # the one place a reader checks which file a name binds.
    _inst = EMS_STRATEGIES[_mn]
    if isinstance(_inst, SdpStrategy):
        assert _mm.get("policy_file") == _inst.policy_file, (
            "EMS_STRATEGY_META[%r].policy_file is %r but the registered "
            "strategy plays %r — the role table would name the wrong artifact."
            % (_mn, _mm.get("policy_file"), _inst.policy_file))
        # A frontier-scored SDP leg MUST demand the calibrated-benchmark
        # certificate: without it, an uncertified artifact could be scored on
        # the frontier and nothing in the trace would show it (see
        # sdp_assert_calibrated_benchmark()).
        assert _mm["frontier_eligible"] == _inst.require_calibrated_benchmark, (
            "EMS_STRATEGY_META[%r]: frontier_eligible %r disagrees with the "
            "strategy's require_calibrated_benchmark %r. A frontier-scored SDP "
            "leg must carry the certificate, and a demonstration leg must not "
            "claim it." % (_mn, _mm["frontier_eligible"],
                           _inst.require_calibrated_benchmark))
del _mn, _mm, _inst

# The strategy names backed by an SdpStrategy instance — i.e. the ones whose
# bind_scenario() reads `sdp_soc_ref_offset`.  Derived from the registry rather
# than written out, so registering a third SDP artifact cannot leave the
# scenario-key guard below silently narrow.
SDP_STRATEGY_NAMES = frozenset(
    n for n, f in EMS_STRATEGIES.items() if isinstance(f, SdpStrategy))


def ems_frontier_eligible(strategy_name):
    """Whether a run of `strategy_name` may be scored on the EMS frontier.

    Unknown names are NOT eligible: an unregistered strategy is one nobody has
    placed a role on, and admitting it to a ranking by default is exactly the
    failure this table exists to prevent."""
    return bool((EMS_STRATEGY_META.get(strategy_name) or {})
                .get("frontier_eligible"))


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO REGISTRY
#
# The CLI and (by contract) tools/run_hil_suite.py consume this via
#     from hil_plant_sim import SCENARIOS
# apply_scenario() remains the behaviour dispatcher; this dict is metadata only.
#
#   electrical : "simple" | "hifi" | "any" — which engine the scenario NEEDS.
#                A "hifi" scenario is refused under --electrical simple rather than
#                silently producing a meaningless trace.
#   duration_s : default --duration for this scenario
#   pi_timeline: optional [(t, {field: value})] fed to PiCommander
#   vesc_cap_f : optional override of the VESC input capacitance (hi-fi only)
#   ems        : optional default --ems strategy name for this scenario
#   ems_v_profile : optional [(t, v_setpoint)] speed profile an EMS strategy may
#                consume via fb["v_profile"] (piecewise-linear, clamped)
#   ems_run_exit_s : optional float — the time the EMS strategy hands the
#                firmware back MODE_SAFE, reaching the policy as
#                fb["ems_run_exit_s"].  ABSENT means the strategy uses its own
#                constant (EMS_RUN_EXIT_S / EMS_REGEN_RUN_EXIT_S /
#                SOC_BAND_RUN_EXIT_S), which is why every pre-2026-08-31
#                scenario is unaffected.  See ems_run_exit().
#   aux_preload_a : optional float — a constant bus load in amps added to
#                I_AUX_A, ramped in over SOC_LOAD_RAMP_S from
#                AUX_PRELOAD_START_S.  Applied generically by
#                apply_scenario()'s fall-through branch (and mirrored by
#                gen_dp_ems_table.scenario_drain_a()); the three bespoke loads
#                that predate it — handoff-sag, soc-depletion, ems-soc-band —
#                keep their own branches.  See scenario_aux_preload_a().
#   mppt_emulation : optional bool — model the Ag105's MPPT INPUT-VOLTAGE
#                THRESHOLD (datasheet p.10) so MPPT_DISABLE becomes causally
#                load-bearing instead of a flag-only control.  The threshold
#                VALUE comes from the board (observation-frame reg-0x02 count,
#                fw v24); AG105_MPPT_V_THRESH is only the no-count fallback.
#                ABSENT/False is the default and leaves the charger branch
#                byte-identical, which is why every pre-2026-08-31 scenario is
#                unaffected.  See Plant.__init__ and the constant's banner.
#   sdp_soc_ref_offset : optional float — SDP strategies ONLY (any name in
#                SDP_STRATEGY_NAMES).  Places the run's
#                STARTING SoC this far ABOVE the policy's target node (negative
#                = below), so the scenario chooses WHICH BRANCH of the
#                bang-bang table the run begins on.  ABSENT means 0.0, i.e. the
#                original "start exactly on the target node" behaviour.  Refused
#                at startup beyond the grid's usable half-span, and refused AT
#                IMPORT on a scenario whose strategy is not an SdpStrategy
#                (where it would be read by nobody).  See
#                SdpStrategy.set_soc_ref_offset().
#   sdp_policy_file : optional str — SDP strategies ONLY, and only ones that
#                are NOT `frontier_eligible` (both refused at import). The
#                baked artifact this scenario plays INSTEAD of the strategy's
#                registered one, as either a repo-relative path or
#                "live-picks:<key>", which resolves through the alpha sweep's
#                live-picks manifest at bind time. ABSENT means the strategy
#                plays what EMS_STRATEGY_META says it plays. See
#                resolve_sdp_policy_file() and the `ems-sdp-alpha-*` block.
#   pi_mute_after_s : optional float — the emulated Pi commander goes
#                PERMANENTLY SILENT at this time while the injection stream keeps
#                running at full rate, isolating the firmware's Pi watchdog from
#                the HIL link's own staleness clock.  ABSENT means "never mute".
#                See PiCommander.mute_after.
#   warm_resets_expected : optional int — how many MID-RUN HIL warm resets
#                (mainState 99 -> 0) this scenario legitimately produces.  Absent
#                means zero, and run_hil_suite.py marks any run that shows one
#                INCONCLUSIVE (a host stall can warm-reset the board mid-run and
#                erase a latched fault, which would read as a false PASS).
# ═════════════════════════════════════════════════════════════════════════════
SCENARIOS = {
    "steady": {
        "description": "fixed aux load; the quiescent baseline (H1)",
        # DURATION 30 -> 10 (2026-08-30 trim): no stimulus event at all. Bring-up
        # completes ~0.6 s and WARM_RESET_GRACE_S is 2.0 s, so 10 s leaves ~8 s of
        # post-grace steady baseline for the statistics this scenario exists for.
        "electrical": "any", "duration_s": 10.0,
    },
    "step-load": {
        "description": "+1.2 A aux load step at t = 5 s — a bus disturbance the "
                       "share loop must reject",
        # DURATION 30 -> 10 (2026-08-30 trim): last event t=5.0 (the aux step); the
        # share loop's rejection transient is ~1 s, so 10 s is last event + ~4 s.
        # Deliberately looser than the ~3 s rule: the post-step SETTLED window is
        # itself the observable here, not just the transient.
        "electrical": "any", "duration_s": 10.0,
    },
    "sag": {
        "description": "-5 V bus disturbance for 1 s at t = 5 s, crossing "
                       "LIMIT_V_BUS_MIN (12.0 V) — the real UV path (H2)",
        # DURATION 30 -> 9 (2026-08-30 trim): last event t=6.0 (end of the 1 s dip);
        # the UV dwell decision lands +20 ms after the crossing at t~5.02, and the
        # latch then persists. 9 s = last event + 3 s of latched observation, all
        # post-grace (not_before_s 5.0 > WARM_RESET_GRACE_S 2.0).
        "electrical": "any", "duration_s": 9.0,
    },
    # ── THE UV-DWELL OBJECTIVE'S HOME (2026-09-01, operator ruling) ─────────
    # MOVED OUT OF `handoff-sag`, which could never deliver it: its bus floor is
    # reached on the BT rail behind an OC_BT latch, so the dwell decision was
    # never the thing being measured there.
    #
    # OBJECTIVE: assert UV_BUS_DWELL_LATCH_MS (20 ms, .ino:1460) FROM BOTH
    # SIDES in one run — a sub-threshold excursion that must NOT latch, then a
    # supra-threshold one that MUST. A one-sided test cannot tell a correct
    # 20 ms threshold from a 5 ms one or from no filter at all.
    #
    # WHY hifi, and it is the load-bearing choice: `v_bus_offset` is
    # SENSE-PATH-ONLY under the hi-fi engine (ElectricalSim.v_bus_sense_offset,
    # added in _rails() and never seen by the node/diode/chopper network),
    # whereas in simple mode the same offset is a REAL algebraic disturbance on
    # V_bus that the sources then respond to. The firmware's dwell integrator
    # reads the MEASURED rail either way, so both modes deliver the excursion —
    # but only hifi perturbs NOTHING ELSE. In simple mode the sag would move the
    # source currents, the droop split and the charger gate at the same time,
    # and a dwell-threshold measurement would be confounded by every one of
    # them. "any" is therefore wrong here: the mode IS the experiment design.
    #
    # TIMING, and why the two excursions are 3 s apart. The filter is LEAKY:
    # time at or above the limit drains the accumulator at UV_BUS_DWELL_LEAK
    # (0.05) x dt, so the 8 ms left by excursion 1 needs 8/0.05 = 160 ms of
    # healthy bus to drain. 3 s is 18.7x that, so excursion 2 starts from a
    # genuinely empty accumulator and latches on its OWN 60 ms rather than on
    # the pair's sum. Without the gap the run would still latch, but it would
    # prove nothing about the threshold.
    "v-bus-sense-offset": {
        "description": "two sensed-V_bus excursions below LIMIT_V_BUS_MIN — "
                       "8 ms (must NOT latch) then 60 ms (must latch): the "
                       "UV_BUS_DWELL_LATCH_MS 20 ms threshold from both sides",
        # hifi is REQUIRED, not preferred — see above.
        "electrical": "hifi", "duration_s": 12.0,
    },
    "comm-loss": {
        "description": "stops transmitting for 2 s at t = 5 s — hold-then-zero, "
                       "then the fw v23+ run-boundary warm recovery (H3)",
        # DURATION 30 -> 12 (2026-08-30 trim): last event is the fw v23 warm recovery,
        # complete ~7.6 s (gap ends 7.0 + HIL_RECOVER_DEBOUNCE_MS 0.5 + ~0.12 s of
        # staged bring-up). 12 s = last event + ~4.4 s, which keeps the mid-run
        # warm-reset tripwire (warm_resets_expected 1, transition at ~7.5 s) and the
        # post-grace fault union (2.0-12.0 s, containing the 5.251 s latch) intact.
        "electrical": "any", "duration_s": 12.0,
        # This scenario's whole point after the gap is that the board RECOVERS:
        # the 2 s silence satisfies fw v23's HIL_RUN_BOUNDARY_MS = 1000 ms, so
        # exactly one mainState 99 -> 0 warm reset is EXPECTED mid-run.  Every
        # other scenario treats a mid-run warm reset as evidence that a host
        # stall erased a latched fault (see run_hil_suite.py's tripwire), so the
        # whitelist has to be declared here rather than inferred.
        "warm_resets_expected": 1,
    },
    "drive": {
        "description": "plant only; the operator drives the firmware by hand "
                       "('V', 'D', 'Y') over USB (H4)",
        "electrical": "any", "duration_s": 30.0,
        # HIL_FINDINGS "drive": run UNATTENDED this scenario commands NOTHING —
        # pi_timeline_entries == 0 and no ems strategy, so the board sits in Idle,
        # `current` is 0.000 A for all 30,000 rows and the Youla drive loop is
        # never exercised.  Scoring that as a PASS advertised drive-loop coverage
        # the run does not have.  run_hil_suite.py renders it SKIPPED unless
        # --with-operator is given; unattended drive-loop coverage belongs to
        # `ems-drive-cycle`.
        "operator_required": True,
    },
    # ── Charging-path scenarios (the firmware's charging path had NO coverage) ──
    "charge-cruise": {
        "description": "Run state, moderate cruise, charge_goal > 0: FC_CHARGE opens "
                       "on intent, the Ag105 settles to Charging, MPPT released",
        # DURATION 40 -> 15 (2026-08-30 trim): last event is the REQUIRED OC_FC latch,
        # measured t=8.7221 s off the charge_goal step at t=8.0. 15 s = last event +
        # ~6 s. not_before_s 8.0 and survive_to.t 8.0 are both well inside it.
        "electrical": "any", "duration_s": 15.0,
        "pi_timeline": [
            (0.5,  {"mode_cmd": MODE_SAFE, "charge_goal": 0.0}),
            (3.0,  {"mode_cmd": MODE_HYBRID}),            # Idle -> Run (.ino:4858)
            (5.0,  {"v_setpoint": 1.2, "power_share_setpoint": 0.5}),
            (8.0,  {"charge_goal": 1.0}),                 # open FC_CHARGE on INTENT
        ],
    },
    # ── charge-regen: REDESIGNED 2026-08-30 (HIL_FINDINGS "charge-regen") ──────
    # The old timeline commanded v_setpoint 1.5 AND charge_goal 1.0 at the SAME
    # t = 5.0 tick.  Two independent defects followed:
    #   1. charge_goal > 0 while `current` is still positive takes
    #      chargingControl()'s CRUISE branch (.ino:10037-10050), which calls
    #      assertFcChargeEnable(true) and drops BT off the bus by design — so the
    #      FC channel alone carried the +12 A acceleration ramp PLUS the Ag105
    #      bring-up, and OC_FC latched at t = 5.585 s, 6.4 s before the first
    #      braking entry.  100 % of the regen objectives were unreached.
    #   2. Even without the OC, its brake steps commanded v_setpoint = 0.0, which
    #      is BELOW V_SP_ZERO_THRESH (0.07 m/s, fw v13): the firmware commands
    #      0 A and holds the drive controller in reset, so `current` never goes
    #      negative and regenActive is never true.  Those "brake" segments COAST.
    # Both are fixed by driving this scenario from an EMS policy instead:
    # `regen-harvest` supplies a CONTINUOUS deceleration ramp (a step cannot hold
    # a negative command past the Ag105's 0.5 s settle — see ems_regen_harvest())
    # and asserts charge_goal only INSIDE a braking window, so the charger is
    # powered through REGEN + MOT_PWR and FC_CHARGE never opens.
    "charge-regen": {
        "description": "cruise/brake cycling driven by the regen-harvest EMS "
                       "strategy: charge_goal is asserted ONLY while braking, so "
                       "the Ag105 is fed through REGEN (never FC_CHARGE) and "
                       "MPPT_DISABLE is asserted LOW during regen",
        "electrical": "any", "duration_s": 45.0,
        "ems": "regen-harvest",
        # De-rated charge ceiling.  During regen chargingControl() keeps BT on the
        # bus (.ino:10036), so the charger draw is SHARED: at share 0.50 the FC
        # channel carries (I_AUX 0.15 + i_charge)/2.  i_motor is ~0 while braking
        # (WP-C 2026-09-01: i_motor is zero while braking because the MOTORING
        # term is zero, not because regen is floored — regen power now leaves on
        # the V-MOT node instead, and never appears as bus draw, so this budget is
        # unchanged.  It is if anything more conservative now: the regen-fed
        # charger is additionally capped by the harvest available at VCHG-IN, so
        # the 1.6 A ceiling is an upper bound the run no longer reaches.)
        # Budget against LIMIT_I_FC_MAX
        # 1.4 A:  (0.15 + 1.6)/2 = 0.88 A per channel -> 37 % margin.
        # At the firmware's real 2.5 A profile it would be (0.15 + 2.5)/2 =
        # 1.33 A, only 5 % under the limit and hostage to any share deviation —
        # too thin for a scenario whose objective is PATH coverage, not ceiling
        # validation.  Ceiling validation is charge-cruise's job (which is
        # EXPECTED to latch OC_FC, per operator ruling (b)).
        "chg_i_ceiling_a": 1.6,
        # Piecewise-linear v_setpoint consumed by the strategy via fb["v_profile"].
        # BRAKING SEGMENTS are the load-bearing part: the commanded deceleration
        # must EXCEED the coast deceleration a_coast(v) = (F_COULOMB + B_EFF*v)/M_EFF
        # or the drive controller commands POSITIVE current and there is no regen.
        #   a_coast(2.5) = (2.00 + 0.534*2.5)/3.5 = 0.953 m/s^2
        #   commanded    = (2.5 - 0.4)/2.1 s      = 1.000 m/s^2   -> 5 % over
        # Longer windows are not available: the maximum sustainable braking time
        # is (v_hi - v_lo)/a_coast(v_hi), i.e. ~2.2 s from 2.5 m/s.  2.1 s of
        # continuous regen minus the 0.5 s AG105_SETTLE_S leaves 1.6 s of
        # charging, which is 4 x AG105_TAU_S — enough for I_charge to reach ~98 %
        # of the ceiling.  Braking windows: 14.0-16.1, 26.0-28.1, 37.0-39.1
        # (EMS_REGEN_BRAKE_WINDOWS must match these).
        #   0.0- 3.0   standstill (MODE_SAFE settle; below V_SP_ZERO_THRESH)
        #   3.0-10.0   accelerate to 2.5 m/s (0.357 m/s^2)
        #  10.0-14.0   cruise 2.5 m/s
        #  14.0-16.1   BRAKE 1 -> 0.4 m/s (1.000 m/s^2)
        #  16.1-18.0   low cruise 0.4 m/s (above V_SP_ZERO_THRESH 0.07)
        #  18.0-23.0   accelerate to 2.5 m/s (0.42 m/s^2)
        #  23.0-26.0   cruise
        #  26.0-28.1   BRAKE 2
        #  28.1-30.0   low cruise
        #  30.0-35.0   accelerate
        #  35.0-37.0   cruise
        #  37.0-39.1   BRAKE 3
        #  39.1-41.0   low cruise
        #  41.0-43.0   ramp to standstill; 43.0-45.0 standstill
        "ems_v_profile": [
            (0.0, 0.0), (3.0, 0.0), (10.0, 2.5), (14.0, 2.5),
            (16.1, 0.4), (18.0, 0.4), (23.0, 2.5), (26.0, 2.5),
            (28.1, 0.4), (30.0, 0.4), (35.0, 2.5), (37.0, 2.5),
            (39.1, 0.4), (41.0, 0.4), (43.0, 0.0), (45.0, 0.0),
        ],
    },
    # ── regen-harvest-true: WP-C, the tabled S3-full, un-tabled 2026-09-01 ────
    # The energy counterpart of `charge-regen`.  Same shape, three differences,
    # each load-bearing:
    #   1. HARD braking (2.5 m/s^2 commanded from 3.0 m/s, unachievable by design)
    #      so the VESC sits on its regen clip for the whole window — see
    #      ems_regen_harvest_hard() for the force arithmetic.
    #   2. `electrical: hifi` is REQUIRED, not preferred: the chopper objective is
    #      an events.jsonl `chopper_clamp` episode, and only the hi-fi engine emits
    #      events.  Simple mode models the same clamp (Plant.step's lumped node)
    #      but has nowhere to report an episode.
    #   3. soc0 is left at the run default: the harvest is single-digit joules
    #      against a pack that is simultaneously carrying the bus, so pack SoC
    #      still FALLS across the run.  Nothing here scores SoC direction; the
    #      harvest is read off I_charge, chopper_clamp energy_j and the plant's
    #      regen_energy_j counter.
    "regen-harvest-true": {
        "description": "hard cyclic braking with the REGEN + MOT_PWR path open: "
                       "genuine kinetic-energy capture — the TL431 chopper clamps "
                       "V-MOT at 18.1 V while the Ag105 settles, then the Ag105 "
                       "takes what is left. WP-C regen-fidelity scenario",
        "electrical": "hifi", "duration_s": 46.0,
        "ems": "regen-harvest-hard",
        # Same de-rating rationale as charge-regen (per-channel budget against
        # LIMIT_I_FC_MAX 1.4 A).  It is an upper bound the run cannot reach: the
        # regen-fed charger is additionally capped by the harvest available at
        # VCHG-IN, which peaks around 0.2 A.
        "chg_i_ceiling_a": 1.6,
        # Windows must match EMS_REGENTRUE_BRAKE_WINDOWS (14-15.5, 26-27.5,
        # 38-39.5) — pinned by test, because a profile and a policy window
        # drifting apart has cost two rounds already.
        # WINDOW LENGTH IS DERIVED, not round: the commanded rate must EXCEED the
        # rate the rig can actually achieve, or the drive controller trims back
        # toward coast instead of sitting on its regen rail.  Achievable decel is
        # (K_F*VESC_REGEN_I_MAX_A + F_c + B_EFF*v)/M_EFF = (1.13 + 2.00 + 1.60)/3.5
        # = 1.352 m/s^2 at 3.0 m/s.  1.5 s commands (3.0-0.4)/1.5 = 1.733 m/s^2,
        # 28 % over.  (2.0 s would command 1.300 — 4 % UNDER, i.e. achievable, and
        # the whole objective would evaporate.  This is the arithmetic the pin
        # protects.)  The realized deceleration therefore OVERRUNS its window by
        # ~0.4 s into the low-cruise segment, which is harmless: regen simply
        # lasts longer than the charge window that sits inside it.
        #   0.0- 3.0  standstill      3.0-11.0 accelerate to 3.0 m/s
        #  11.0-14.0  cruise 3.0     14.0-15.5 BRAKE 1 (1.733 m/s^2 commanded)
        #  15.5-18.0  low cruise 0.4 18.0-23.0 accelerate
        #  23.0-26.0  cruise         26.0-27.5 BRAKE 2
        #  27.5-30.0  low cruise     30.0-35.0 accelerate
        #  35.0-38.0  cruise         38.0-39.5 BRAKE 3
        #  39.5-42.0  low cruise     42.0-44.0 ramp down; 44.0-46.0 standstill
        "ems_v_profile": [
            (0.0, 0.0), (3.0, 0.0), (11.0, 3.0), (14.0, 3.0),
            (15.5, 0.4), (18.0, 0.4), (23.0, 3.0), (26.0, 3.0),
            (27.5, 0.4), (30.0, 0.4), (35.0, 3.0), (38.0, 3.0),
            (39.5, 0.4), (42.0, 0.4), (44.0, 0.0), (46.0, 0.0),
        ],
        "ems_run_exit_s": EMS_REGENTRUE_RUN_EXIT_S,
    },
    "charge-fault": {
        "description": "charging established, then the charger input rail collapses "
                       "— exercises the GENSTAT decode / charger-loss path",
        # DURATION 40 -> 25 (2026-08-30 trim): last event t=20.0 (the charger input
        # collapse); the GENSTAT / chargerHasPower() reaction is ~1 s. 25 s = last
        # event + 5 s. survive_to.t 20.0 and the signals window (8, 20) both fit.
        "electrical": "any", "duration_s": 25.0,
        # De-rated charge ceiling so the run SURVIVES to its own t = 20 s stimulus.
        # HIL_FINDINGS "charge-fault": the run latched OC_FC at t = 5.758 s — 14.25 s
        # BEFORE the scripted charger-input collapse — so the GENSTAT/charger-loss
        # path it exists to test was never reached, and the suite PASSed it anyway.
        # FC-path charging is SINGLE-SOURCE by design (assertFcChargeEnable() drops
        # BT off the bus, .ino:10046), so the whole bus current lands on FC.
        # Budget against LIMIT_I_FC_MAX 1.4 A at the 1.0 m/s cruise this scenario
        # commands:
        #     i_aux                                     0.150 A
        #     motor: i_cmd = (F_c + b*v)/K_F = 3.36 A
        #            p_mech = K_F*i_cmd*v   = 2.53 W
        #            i_motor = p/(ETA_BOOST*V_bus 15.8) 0.189 A
        #     charger INPUT draw at the 0.800 A ceiling  0.452 A
        #            = 0.800 * V_pack 7.86 / (ETA_CHG 0.88 * V_bus 15.8)
        #                                        total  0.791 A  -> 44 % margin
        # RE-DERIVED 2026-09-01 (charger-efficiency round).  The charger term
        # used to be budgeted at the ceiling itself, 0.800 A, because the sim
        # stamped the Ag105 OUTPUT current on the VCHG node — a 1:1 current
        # repeater, ~1.77x the physical input draw at this operating point.  The
        # model now bills the INPUT (see the CHARGER BILLING block in
        # Plant.step()), so the budgeted total falls 1.139 -> 0.791 A and the
        # margin against LIMIT_I_FC_MAX 1.4 A widens 19 % -> 44 %.  The de-rated
        # ceiling is KEPT at 0.8 A: it was chosen to make the run survive to its
        # t = 20 s stimulus, and widening it would only put the OC_FC latch back
        # in play for no gain in what this scenario tests.
        "chg_i_ceiling_a": 0.8,
        "pi_timeline": [
            (0.5,  {"mode_cmd": MODE_SAFE, "charge_goal": 0.0}),
            (3.0,  {"mode_cmd": MODE_HYBRID}),
            (5.0,  {"v_setpoint": 1.0}),
            # charge_goal STAGGERED to t = 8.0, after cruise is established: at
            # t = 5.0 the drive controller rails to +12 A for the acceleration, and
            # at 1.0 m/s that rail alone is 0.67 A of bus current on top of the
            # charger draw.  Same fix family as charge-regen's, and it matches
            # charge-cruise's own 3 s stagger.
            (8.0,  {"charge_goal": 1.0}),
        ],
    },
    # ── Source-model scenarios ─────────────────────────────────────────────────
    "soc-depletion": {
        "description": "sustained battery-heavy load: V_batt walks DOWN the OCV "
                       "curve toward LIMIT_V_BATT_MIN — the honest UV_BATT path",
        # 120 s is the STANDALONE default and does NOT reach the UV floor from the
        # default --soc0 0.7. run_hil_suite.py overrides both: --soc0 0.20 and
        # --duration 400 (re-derived 2026-08-30 — the pack-side coulomb current is
        # ~6.19 A, not the 2.2 A bus-side load, and the UV_BATT latch forecloses
        # the run at soc ~= 0.113). Run it standalone with those two flags to
        # reproduce a suite run.
        "electrical": "any", "duration_s": 120.0,
        "pi_timeline": [
            (0.5,  {"mode_cmd": MODE_SAFE}),
            (3.0,  {"mode_cmd": MODE_HYBRID}),
            # STAGGERED from the aux step (HIL_FINDINGS "soc-depletion"): the share
            # rail and the scenario's own load step (then +3.0 A, now
            # SOC_ENDURANCE_LOAD_A) were authored independently and both landed on
            # t = 5.0.  The new ~3.15 A draw split
            # EVENLY across both boosts for one 1 ms tick before the droop could
            # reapportion, and 1.4705 A — 5 mA over LIMIT_I_FC_MAX — latched OC_FC
            # on a single sample.  The board then sat dark for the rest of the run
            # and the endurance objective (V_batt walking down the OCV curve) was
            # never reached.  The share rail now settles first; the load ramps in
            # from t = 10.0 (see apply_scenario).
            (5.0,  {"power_share_setpoint": 0.0}),   # all load onto the battery
        ],
    },
    # ── Mode A: emulated-EMS scenarios ─────────────────────────────────────────
    "ems-drive-cycle": {
        "description": "58 s drive cycle (accelerate / cruise / decelerate / stop, "
                       "then Run -> Finish -> Idle via ems_hold_5050's "
                       "EMS_RUN_EXIT_S) commanded by the emulated Pi EMS layer "
                       "(--ems, default hold-5050) instead of a scripted "
                       "pi_timeline",
        # DURATION 60 -> 58 (2026-08-30 trim): last event is EMS_RUN_EXIT_S = 55.0,
        # where hold-5050 commands MODE_SAFE and the board goes Run -> Finish ->
        # Idle within a tick. 58 s = last event + 3 s. ORDERING VERIFIED:
        # ems_v_profile reaches standstill at t=52.0 < EMS_RUN_EXIT_S 55.0 < 58.0,
        # and piecewise() clamps past its last point, so dropping the profile's
        # trailing (60.0, 0.0) sample from the run changes no commanded value.
        "electrical": "any", "duration_s": 58.0,
        # NOTE: deliberately NO pi_timeline. The commands come from the EMS policy;
        # a timeline here would be silently replaced by --ems (main() prints a
        # notice when that happens) and would only confuse the provenance.
        "ems": "hold-5050",
        # F8: comment corrected to match the table exactly — it previously (a)
        # omitted the 30.0-32.0 ramp segment entirely (jumping straight from
        # "30.0-40.0 cruise 2.0" to describing only the 1.5 m/s cruise) and
        # (b) conflated two different numbers under one "the last ~0.4 s" claim:
        # the setpoint crosses the design's 0.5 m/s VALIDITY FLOOR at t=49.0
        # (3.0 s before reaching zero at t=52.0, not "the last ~0.4 s"), while
        # 0.42 s is separately the time the setpoint spends below
        # V_SP_ZERO_THRESH (0.07 m/s) before t=52.0 -- two distinct thresholds,
        # two distinct durations.
        #
        # Piecewise-linear v_setpoint. Segments, and why these numbers:
        #   0.0- 3.0  standstill  (below V_SP_ZERO_THRESH 0.07 m/s the firmware
        #                          commands 0 A and holds the drive controller in
        #                          reset — CLAUDE.md fw v13; also covers the
        #                          MODE_SAFE settle before EMS_RUN_ENTRY_S)
        #   3.0-10.0  accelerate to 1.5 m/s  (0.214 m/s^2 — far inside the
        #                          rail-acceleration bound ~2.0 m/s^2, so the
        #                          drive controller is not saturation-limited)
        #  10.0-30.0  cruise 1.5 m/s   (inside the design's v >= 0.5 m/s validity
        #                          floor, CLAUDE.md fw v12)
        #  30.0-32.0  accelerate 1.5 -> 2.0 m/s  (0.25 m/s^2; the ramp BETWEEN
        #                          the two cruise levels below)
        #  32.0-40.0  cruise 2.0 m/s   (a second cruise level: an incremental
        #                          dv/dI datapoint without leaving the floor)
        #  40.0-52.0  decelerate to 0  (0.167 m/s^2). Crosses the 0.5 m/s
        #                          VALIDITY FLOOR at t=49.0 (3.0 s before
        #                          reaching zero — the honest end of a drive
        #                          cycle) and separately spends the LAST 0.42 s
        #                          (t=51.58-52.0) below V_SP_ZERO_THRESH 0.07 m/s
        #  52.0-60.0  standstill
        "ems_v_profile": [
            (0.0, 0.0), (3.0, 0.0), (10.0, 1.5), (30.0, 1.5),
            (32.0, 2.0), (40.0, 2.0), (52.0, 0.0), (60.0, 0.0),
        ],
    },
    # ── ems-soc-band: the DP-informed charge-sustaining EMS ────────────────────
    "ems-soc-band": {
        "description": "61 s drive cycle driven by the `soc-band` EMS strategy: a "
                       "sustained drain phase walks SoC out of the policy's band so "
                       "the split biases toward the fuel cell, then a quiet low "
                       "cruise admits an opportunistic FC-path charge window. "
                       "Exercises the H2 metric end to end.",
        # DURATION: last event is SOC_BAND_RUN_EXIT_S = 58.0, where the strategy
        # commands MODE_SAFE and the board goes Run -> Finish -> Idle within a
        # tick.  61 s = last event + 3 s, the standing trim rule.  ORDERING:
        # the profile reaches standstill at t = 58.0 = SOC_BAND_RUN_EXIT_S, and
        # piecewise() clamps past its last point.
        "electrical": "any", "duration_s": 61.0,
        # NO pi_timeline, for ems-drive-cycle's reason: the commands come from
        # the policy and a timeline here would be silently replaced.
        "ems": "soc-band",
        # De-rated charge ceiling, taken from charge-fault's budget verbatim
        # because the charge window is the same operating point (1.0 m/s cruise,
        # single-source FC after assertFcChargeEnable() drops BT off the bus):
        #     i_aux                                     0.150 A
        #     motor: i_cmd = (F_c + b*v)/K_F = 3.36 A
        #            p_mech = K_F*i_cmd*v   = 2.53 W
        #            i_motor = p/(ETA_BOOST*V_bus 15.8) 0.189 A
        #     charger ceiling                           0.800 A
        #                                        total  1.139 A  -> 19 % margin
        #                                        on LIMIT_I_FC_MAX 1.4 A
        # As in charge-fault, the charger term is the SIM's stamped draw (the
        # Ag105 OUTPUT current on the VCHG node, ~1.47x the physical input
        # draw), so the budget errs conservative.
        "chg_i_ceiling_a": 0.8,
        # Piecewise-linear v_setpoint.  DESIGNED so the policy's three branches
        # are separable in the trace, not copied from ems-drive-cycle:
        #   0.0- 3.0  standstill (MODE_SAFE settle; below V_SP_ZERO_THRESH 0.07)
        #   3.0- 8.0  ACCELERATE to 1.5 m/s (0.30 m/s^2).  The cruise test must
        #             reject this segment — operator ruling (b): charge_goal is
        #             never asserted during acceleration.
        #   8.0-38.0  cruise 1.5 m/s.  The DRAIN phase (SOC_BAND_DRAIN_* in
        #             apply_scenario) covers all of it — it ramps in from t = 10
        #             and only ramps out from t = 38, over the deceleration.
        #             MEASURED: SoC leaves the band at t = 24.30 and the FC
        #             bias saturates at t = 34.90.  ⚠️ ONE SOURCE for these
        #             three timings and the charge onset below, everywhere they
        #             appear (here, SOC_BAND_DRAIN_LOAD_A's budget, the
        #             run_hil_suite.py entry, HIL_PLANT.md §6, the user
        #             manual's §3.2.2 table): the GENERATOR's matched-model
        #             `soc-band` walk, printed by
        #               miniforge python tools/gen_dp_ems_table.py \
        #                   --scenario ems-dp-replay --dry-run
        #             as `band exit t= / share saturation t= / first charge t=`.
        #             That walk is the same model the DP is solved against, so
        #             it is also the walk the benchmark comparison uses; a
        #             second offline walk would be a second answer.  Charging
        #             is blocked here by the current-admission threshold
        #             (~1.45 A total vs the 0.60 A gate), NOT by the cruise
        #             test — the two gates are deliberately exercised apart.
        #  38.0-41.0  decelerate 1.5 -> 1.0 m/s (0.167 m/s^2).  GENTLER than the
        #             coast rate a_coast(1.5) = (2.00 + 0.534*1.5)/3.5 = 0.80
        #             m/s^2, so the drive command stays POSITIVE and no regen
        #             branch is entered — this scenario is about the FC path.
        #  41.0-54.0  cruise 1.0 m/s, drain off: the CHARGE WINDOW.  Measured in
        #             the same matched-model walk: charge_goal asserts at
        #             t = 41.70 (the trailing slope window clears the gentle
        #             deceleration a little before it is fully flushed), then the
        #             Ag105 settles (AG105_SETTLE_S 0.5 s) and ramps
        #             (AG105_TAU_S 0.4 s), so I_charge passes 0.5 A by
        #             t ~= 42.6.  The suite's check window opens at 44.0.
        #  54.0-58.0  decelerate to 0 (0.25 m/s^2); 58.0-61.0 standstill.
        "ems_v_profile": [
            (0.0, 0.0), (3.0, 0.0), (8.0, 1.5), (38.0, 1.5),
            (41.0, 1.0), (54.0, 1.0), (58.0, 0.0), (61.0, 0.0),
        ],
    },
    # ── Hi-fi-only scenarios ───────────────────────────────────────────────────
    # ── handoff-sag: OPERATING POINT REDESIGNED 2026-08-30 (review M3) ─────────
    # VERIFIED FROM SOURCE — what actually opens the standby bus switch:
    #   powerBalance() calls updateShareSetpointCutoff() FIRST, explicitly "BEFORE
    #   the minimum-load gate and before the governor" (.ino:9377-9385).  At a
    #   setpoint outside [DROOP_R_MIN 0.15, DROOP_R_MAX 0.85] that latch drives the
    #   doomed channel's *_BUS_ENABLE LOW (.ino:9231-9257) and freezes the whole
    #   share loop.  So the 0.60 A (2 * SHARE_MINORITY_I_MIN_A) CLOSED-LOOP entry
    #   gate governs the CONTROLLER, not the cut — the review's stated mechanism is
    #   not the one that fires, and the recorded run bears that out (HIL_FINDINGS
    #   handoff-sag: BT_BUS opened at I_batt = 0.083 A, far under the gate).
    # Two REAL constraints do bind, and they bracket the operating point:
    #   (a) the cut is refused unless the DOOMED channel's measured current is
    #       <= SHARE_CUT_MAX_HANDOFF_A = 0.5 A (.ino:2018, :9235/:9252) — it is a
    #       one-tick transfer of that whole current onto the survivor.  So the
    #       pre-rail total must be <= ~1.0 A at a 0.5 split;
    #   (b) the share loop must be in CLOSED-LOOP mode for the run to mean anything
    #       as a share test at all, which needs the filtered total > 0.60 A.
    # Window: pre-rail total in (0.60, 1.00) A.  Chosen 0.74 A:
    #     I_AUX_A 0.15 + HANDOFF_PRELOAD_A 0.40 + i_motor 0.19 (1.0 m/s cruise)
    #   -> 0.37 A per channel: 23 % over the governor gate, 26 % under the cut guard.
    #
    # RAIL DIRECTION FLIPPED to share 0.0 (BT survives, FC is cut).  At the FC rail
    # the surviving channel is bounded by LIMIT_I_FC_MAX 1.4 A, which leaves only
    # ~0.66 A of perturbation budget over the 0.74 A pre-load — too small to excite
    # the sag the scenario exists for, and the previous +1.5 A step is exactly what
    # latched OC_FC at +2.2 ms with the bus still 1.05 V above the UV floor.  At the
    # BT rail the survivor is bounded by LIMIT_I_BT_MAX 3.0 A:
    #     0.74 + 1.5 = 2.24 A  ->  25 % margin.
    # The two RT1987 instances are identical in the hi-fi model (same CSS, same
    # reverse comparator; FC/BT droop symmetric within 2 %), so the MECHANISM under
    # test is unchanged — only its handedness, which TP0178 does not privilege.
    #
    # HONEST SCOPE (verified, and the old description overclaimed): a setpoint-
    # latched cut drives the switch's ENABLE low, and an EN-low RT1987 does not
    # conduct at all — there is no reverse-blocked-but-enabled standby state to pick
    # up from.  The firmware's own re-closers gate on !shareSpCut* (.ino:5423,
    # :10011, :10036), so they will not re-close it either.  A REACTIVE PICKUP is
    # therefore NOT reachable from this stimulus in either the firmware or the
    # model.  What this scenario does test: the cut's load guard, the single-source
    # sag depth after the handoff, and the UV dwell decision on it.
    "handoff-sag": {
        "description": "TP0178/TP0201 class: the share setpoint latch cuts one "
                       "source off the bus, then a load step probes the "
                       "single-source sag and the UV dwell decision. NOTE: a "
                       "reactive standby pickup is NOT reachable from a "
                       "setpoint-latched cut (the switch is EN-low) — see the "
                       "scenario comment",
        # DURATION 40 -> 24 (2026-08-30 trim): last event t=20.0 (HANDOFF_STEP_A); the
        # share-cut latch and the UV dwell decision both resolve within ~50 ms.
        # 24 s = last event + 4 s of single-source observation. survive_to.t 20.0
        # and the fc_bus_open signals window (8, 20) are unaffected.
        "electrical": "hifi", "duration_s": 24.0,
        # ⚠️ THE 2 s GAP BETWEEN t = 4.0 AND t = 6.0 IS LOAD-BEARING (measured,
        # campaign 20260830_203006 — it was undocumented and nearly lost).  The
        # t = 4.0 v_setpoint step rails the drive controller, and that transient
        # pushes I_fc to 0.623 A — ABOVE the SHARE_CUT_MAX_HANDOFF_A 0.5 A guard
        # (.ino:2018) — for 233 ticks, until t = 4.573.  A rail command issued in
        # that window is REFUSED on load: updateShareSetpointCutoff() takes its
        # `shareCutDeferredFC` branch (.ino:9241-9247) instead of cutting, and the
        # scenario's entire objective (an actually-opened bus switch) silently does
        # not happen.  The commanded rail must therefore wait for the drive
        # transient to settle.  Margin as shipped: 1.43 s, i.e. ~3.5x the 0.573 s
        # the transient actually takes.  DO NOT close this gap, and do not move
        # either entry toward the other, without re-measuring I_fc through the
        # v_setpoint step.
        "pi_timeline": [
            (0.5,  {"mode_cmd": MODE_SAFE}),
            (3.0,  {"mode_cmd": MODE_HYBRID}),
            (4.0,  {"v_setpoint": 1.0}),          # cruise first, then the pre-load
            (6.0,  {"power_share_setpoint": 0.0}),   # BT-only rail: FC is cut
        ],
    },
    "bringup": {
        "description": "from dark: the firmware's staged bring-up (P0-P3) against the "
                       "real RT1987 t_D(ON) + soft-start delays",
        # DURATION 30 -> 8 (2026-08-30 trim): last event is the end of the staged
        # bring-up, ~2 s under fw v22+ HIL auto bring-up. 8 s = last event + ~6 s,
        # of which 6 s is post-grace. This scenario carries no FAULT_EXPECTATIONS
        # entry (expected fault-free) and therefore no events_require to land.
        "electrical": "hifi", "duration_s": 8.0,
    },
    "scp-inrush": {
        "description": "RT1987 soft-start foldback + SCP cut: MOT_PWR ramps up "
                       "unloaded during bring-up P3, then a 6.5 A V-MOT pulse binds "
                       "the foldback in one substep; a 5.0 A run load follows the "
                       "64 ms retry. VESC input envelope 0.9 mF + 470 uF local bulk",
        # DURATION 6.0, RE-DERIVED 2026-08-31 for the three-phase stimulus (was
        # derived for the flat load, where the last event was the cut at t = 0.600
        # and the State-99 teardown right behind it). The sequence is now longer by
        # design — the 64 ms foldback retry IS reached, because the fold fires
        # before the firmware can react and the switch is therefore still enabled:
        #     cut          ~0.600 s   (bring-up P3 close + TD_ON + ~2 ms of ramp)
        #     retry re-arm  +0.064
        #     ON            +0.091    (second soft-start into a pre-charged node;
        #                              measured, headless bench 2026-08-31)
        #     run load      +0.110    -> OC_FC on the next 1 kHz sample, ~0.711 s
        #     teardown      +~0.01    -> State 99 latched by ~0.72 s
        # 6.0 s = last event + ~5.3 s, of which ~4.0 s is post-grace
        # (WARM_RESET_GRACE_S 2.0) — well past the >= 3 s post-stimulus margin the
        # trim convention asks for, so the duration does not move.
        "electrical": "hifi", "duration_s": 6.0,
        "vesc_cap_f": 0.9e-3,
    },
}

# ── ems-dp-replay: the same cycle, driven by the OFFLINE-OPTIMAL table ──────
#
# DERIVED, not copied.  Every field that defines the stimulus is taken from the
# `ems-soc-band` entry BY REFERENCE — `ems_v_profile` is literally the SAME list
# object, so the two scenarios cannot drift apart and a retune of one is a
# retune of both.  That is a hard requirement here and not a tidiness
# preference: the DP table is a solution of ONE profile + ONE auxiliary load,
# and the whole point of running this scenario is to compare its result against
# `ems-soc-band` on identical conditions.  apply_scenario() applies the same
# SOC_BAND_DRAIN_* load to both names for the same reason.
#
# ⚠️ The strategy is NON-CAUSAL — see the DpReplayStrategy banner.  It refuses
# at startup unless tools/dp_tables/dp_ems_table_ems-dp-replay.csv exists and
# its `profile_fingerprint` matches this entry, so a stale table cannot be
# replayed silently.  Generate it with:
#     C:/Users/ricky/miniforge3/python.exe tools/gen_dp_ems_table.py \
#         --scenario ems-dp-replay
#
# DP-PREDICTED TOTALS for the shipped table (the generator's own reduced
# model, open loop — quoted here as the comparison anchor; the realised run
# WILL differ, since the board's share loop, the Ag105 settle+ramp and the
# plant's own drag are outside that model).  The shipped table is generated
# with `--charger-accounting physical`, which is the accounting a
# `--electrical hifi` run logs — and run_hil_suite.py's --electrical-pref
# defaults to hifi, so that is what a default campaign runs.  Both strategies'
# terminal SoC is MATCHED by construction (the generator bisects LAMBDA_TERM
# until it is), which is what makes the hydrogen difference readable at all:
#     h2 (physical)   1.17564e-02 g   vs soc-band 1.37227e-02 g   (-14.33 %)
#     terminal SoC    0.698006        vs soc-band 0.698005
# Read the two as a PAIR: a hydrogen comparison is only valid at matched
# terminal SoC, and any strategy burns less hydrogen by discharging harder.
# ⚠️ Gfc is scale-portable by design (operator ruling 2026-08-31, systemic
# scaling paper — see the H2Consumption banner) but not yet identified against
# THIS stack, so treat absolute grams as the model's estimate pending
# TODO(calibrate).
#
# NOTE, and it is a finding rather than a gap: the DP opens the charger path on
# ZERO stages of this cycle.  Shifting the split toward the fuel cell buys
# 0.405 SoC per gram of hydrogen; running the Ag105 buys 0.169.  Opportunistic
# charging is simply the worse lever at this rig's numbers, which is why the
# suite entry for this scenario asserts no charge window while `ems-soc-band`'s
# does.
SCENARIOS["ems-dp-replay"] = {
    "description": "The `ems-soc-band` drive cycle and drain load, driven by the "
                   "NON-CAUSAL `dp-replay` benchmark: a setpoint table computed "
                   "offline by backward dynamic programming with full "
                   "foreknowledge of the whole cycle. Not a controller — the "
                   "offline-optimal reference the causal strategies are ranked "
                   "against on h2_cum_g, delta_soc and share tracking.",
    # "hifi", NOT inherited from ems-soc-band's "any" (2026-08-31 review follow-
    # up): the shipped table is generated with --charger-accounting physical, and
    # bind_scenario() refuses an accounting/engine mismatch at startup.  Leaving
    # this "any" made `run_hil_suite.py --electrical-pref simple` a hard child
    # failure; declaring hifi makes the suite run it hifi under EITHER
    # preference (the bringup/scp-inrush pattern), which is the engine the table
    # is derived for.  A simple-engine benchmark needs its own table
    # (--charger-accounting simple) AND this key widened, together.
    "electrical": "hifi",
    "duration_s": SCENARIOS["ems-soc-band"]["duration_s"],
    "chg_i_ceiling_a": SCENARIOS["ems-soc-band"]["chg_i_ceiling_a"],
    # THE SAME LIST OBJECT — see the note above.
    "ems_v_profile": SCENARIOS["ems-soc-band"]["ems_v_profile"],
    "ems": "dp-replay",
}

# ── ems-sdp: the same cycle, driven by the ONLINE stochastic-DP policy ──────
#
# DERIVED FROM `ems-soc-band` BY REFERENCE, exactly as `ems-dp-replay` is and
# for the same hard reason: the three scenarios exist to be COMPARED, and a
# comparison on different stimuli is not one.  `ems_v_profile` is literally the
# SAME LIST OBJECT all three share, `duration_s` and `chg_i_ceiling_a` are read
# off the soc-band entry rather than retyped, and apply_scenario() applies the
# SAME SOC_BAND_DRAIN_* load to this name (the drain branch matches all three
# names, and this scenario is listed in _AUX_PRELOAD_BESPOKE so a preload
# declared here could not be silently ignored).  Retuning one retunes all three.
#
# THE THREE-WAY COMPARISON, and what each leg is for:
#   ems-soc-band   causal heuristic        (SocBandStrategy)
#   ems-sdp        causal, optimal by construction over a stochastic demand
#                  model, computed offline and played by STATE  (SdpStrategy)
#   ems-dp-replay  NON-CAUSAL lower bound, computed offline with full
#                  foreknowledge and played by TIME  (DpReplayStrategy)
# Read h2_cum_g WITH delta_soc in all three: any strategy burns less hydrogen by
# discharging the pack harder.  Note the DP leg's terminal SoC is MATCHED to
# soc-band's by construction (the generator bisects for it) while THIS leg's is
# not — its charge sustenance is whatever the policy delivers, which is part of
# what the run measures.
#
# `electrical: "any"`, NOT "hifi".  `ems-dp-replay` is hifi-only because its
# table's hydrogen ACCOUNTING must match the engine (bind_scenario() refuses a
# mismatch).  Nothing equivalent binds here: `sdp-v3` is causal state feedback
# with no offline objective to agree with, so both engines are legal and running
# it under either preference is a free cross-check.
#
# ⚠️ SIM-ONLY strategy (plant-truth SoC) and its demand axis clamps to the end
# bins for much of this cycle — both are the SdpStrategy banner's business, and
# the exit summary's clamp counters are how a run reports it.
# ── REBOUND TO `sdp-v4` 2026-09-02 (the eta era) ────────────────────────────
# The block below records the 2026-09-01 move from v2 to v3, which is still the
# reason every expectation on this leg reads the way it does.  What the eta era
# changed is WHICH calibrated artifact plays it: `sdp_policy_v4.json` is the
# same two-sided lever calibration re-solved against the energy-conserving
# charger the plant now models (hil_electrical.ETA_CHG = 0.88), and v3 is the
# same calibration for a charger this run no longer has.
#   * WHAT CHANGED: nothing this scenario observes.  v3 and v4 carry the SAME
#     all-zero charge map (0 differing cells), so `charge_path_never_opens`
#     stands unchanged, and their share maps differ on FOUR rows only — 2, 3, 4
#     and 5, i.e. SoC 0.552-0.555, which is 45-48 grid nodes BELOW the target
#     node this scenario starts on and falls ~0.0017 from.  Pinned by
#     test_sdp_v3_v4_share_maps_agree_on_traversed_rows().
#   * WHAT DID CHANGE: the economics the leg REPORTS.  v4's alpha (0.118326)
#     was priced against the charger the run bills, so its h2/delta_soc pair is
#     a result about this plant; v3's was not.  That is the whole reason for
#     the rebinding, and it is why v3 is now `frontier_eligible: False`.
#
# ── BOUND TO `sdp-v3` SINCE 2026-09-01 (the charge-economics ruling) ────────
# This is THE BENCHMARK LEG of the three-way comparison, so it must play the
# CALIBRATED artifact.  What changed and what did not:
#   * WHAT CHANGED: the charge action.  v2 charged in bins 0-5 below the
#     relative target (the t = 41..58 window every threshold in the suite entry
#     was calibrated against); v3's charge map is ZERO everywhere, by ENDOGENOUS
#     rejection — the calibrated alpha prices the Ag105's 0.2364 SoC/g lever
#     below its own 0.30682 SoC/g admission threshold.  This leg therefore now
#     asserts that FC_CHARGE NEVER opens (run_hil_suite.py's
#     `charge_path_never_opens`), which is the exact opposite check and is a
#     GUARANTEED FAIL under v2 — the binding and the expectation move together
#     or not at all.
#   * WHAT DID NOT: the share axis.  v2 and v3 differ in `policy.share` only on
#     SoC rows 1-2 (30 cells of 2525), which this scenario's trajectory
#     (soc_rel starts ON the target node, row 50, and falls ~0.0017) does not
#     come near.  Every share threshold in the suite entry is unmoved.
SCENARIOS["ems-sdp"] = {
    "description": "The `ems-soc-band` drive cycle and drain load, driven by "
                   "the CAUSAL `sdp-v4` policy: a state-indexed setpoint table "
                   "computed offline by stochastic dynamic programming and "
                   "looked up at run time on (SoC, demand bin). The causal "
                   "optimal-by-construction leg between the `soc-band` "
                   "heuristic and the non-causal `dp-replay` bound.",
    "electrical": "any",
    "duration_s": SCENARIOS["ems-soc-band"]["duration_s"],
    "chg_i_ceiling_a": SCENARIOS["ems-soc-band"]["chg_i_ceiling_a"],
    # THE SAME LIST OBJECT — see the note above.
    "ems_v_profile": SCENARIOS["ems-soc-band"]["ems_v_profile"],
    # THE CALIBRATED BENCHMARK artifact for the eta_chg = 0.88 charger — see
    # the two blocks above this entry.  Rebound from `sdp-v3` 2026-09-02.
    "ems": "sdp-v4",
}

# ═════════════════════════════════════════════════════════════════════════════
# ── ems-sdp-alpha-*: THE ALPHA SWEEP'S THREE LIVE POINTS (2026-09-02) ───────
#
# WHAT THESE ARE.  The `ems-sdp` stimulus — the SAME profile object, the SAME
# drain, the SAME charge ceiling, the SAME Run exit — driven by three DIFFERENT
# SDP artifacts taken from the eta-era alpha sweep, one per behaviour leg:
#
#   ems-sdp-alpha-greedy   a point on the GREEDY leg (alpha below the share
#                          lever's admission threshold): the SoC axis is priced
#                          so low that the policy takes hydrogen greedily.
#   ems-sdp-alpha-cal      the CALIBRATED point — the sweep's anchor, whose
#                          policy block is the shipped `sdp_policy_v4.json`.
#                          It exists so the sweep has an in-family control
#                          measured under the same scenario name as its
#                          neighbours, not because the law differs from
#                          `ems-sdp`'s.
#   ems-sdp-alpha-charge   a point on the CHARGE-ADMITTING leg (alpha above the
#                          charge lever's threshold): the policy opens the
#                          Ag105, which the eta-era model prices as the worse
#                          lever by exactly 1/eta.
#
# WHY ONE STIMULUS.  The sweep varies ONE quantity — alpha — and three runs on
# three different cycles would vary two.  Sharing `ems-sdp`'s objects (not
# copies of them) is the same discipline the frontier legs follow, and for the
# same reason: a comparison across them is only about the policy.
#
# WHY NOT ON THE FRONTIER.  Two of the three artifacts sit OUTSIDE the two
# admission windows BY DESIGN — that is what makes them sweep points — so none
# of them can carry the calibrated-benchmark certificate and none of their
# h2/delta_soc pairs is a competitive score.  They run under `sdp-sweep`, whose
# EMS_STRATEGY_META entry is `frontier_eligible: False` with a role note, so a
# report renders them under the demonstration banner rather than ranking them.
# The alternative — binding them to `sdp-v4` and overriding its artifact —
# would make the ROLE a property of the scenario while the registry still said
# "frontier leg", which is exactly the confusion EMS_STRATEGY_META exists to
# prevent.  The import guard below refuses that arrangement outright.
#
# WHICH ARTIFACT.  Not a hard-coded path: each names its sweep PICK, and
# `resolve_sdp_policy_file()` reads the path AND the selected policy sha out of
# the sweep's own live-picks manifest at bind time (see SDP_LIVE_PICKS_PATH).
# A sweep re-run that moves a leg midpoint moves these scenarios with it; a
# regenerated artifact that changes the decision law is REFUSED rather than
# played under a name that claims the pick.
#
# CAMPAIGN COST.  Three more 61 s runs (~3 min).  `run_hil_suite.py` builds its
# plan from every entry in SCENARIOS, so these are ORDINARY runs unless gated
# there — see SDP_ALPHA_SCENARIOS below.
for _leg, _why in (
        ("greedy", "the GREEDY leg — alpha below the share lever's admission "
                   "threshold, so the SoC axis is priced too low to defend and "
                   "the policy runs the fuel cell"),
        ("cal", "the CALIBRATED point — the sweep anchor, whose policy block "
                "IS the shipped sdp_policy_v4.json; the sweep's in-family "
                "control"),
        ("charge", "the CHARGE-ADMITTING leg — alpha above the charge lever's "
                   "threshold, so the policy opens the Ag105 that the eta-era "
                   "model prices as the worse lever by 1/eta")):
    _name = "ems-sdp-alpha-" + _leg
    SCENARIOS[_name] = {
        "description": ("The `ems-sdp` stimulus (same profile object, drain "
                        "and charge ceiling) driven by the alpha sweep's %s "
                        "point: %s. A POLICY-PARAMETER SWEEP LEG, not a "
                        "frontier candidate." % (_leg, _why)),
        "electrical": "any",
        # THE SAME OBJECTS as `ems-sdp` — see the block above.
        "duration_s": SCENARIOS["ems-sdp"]["duration_s"],
        "chg_i_ceiling_a": SCENARIOS["ems-sdp"]["chg_i_ceiling_a"],
        "ems_v_profile": SCENARIOS["ems-sdp"]["ems_v_profile"],
        "ems": "sdp-sweep",
        "sdp_policy_file": SDP_LIVE_PICK_PREFIX + _name,
    }
del _leg, _why, _name

# The alpha-sweep legs, as a set, for a caller that wants to gate them.
# DERIVED from the registry rather than written out, so a fourth sweep point
# cannot be added to SCENARIOS and left out of a gate.  run_hil_suite.py has no
# opt-in flag for them today (its only cost gates are `--with-ftp75` /
# FTP75_SCENARIOS and `operator_required`), so as registered here they are
# ORDINARY runs and every campaign pays their ~3 min.  Gating them belongs in
# run_hil_suite.py's build_plan(), against this name.
SDP_ALPHA_SCENARIOS = tuple(sorted(
    n for n in SCENARIOS if n.startswith("ems-sdp-alpha-")))

# ── THE SHARED SOC-BAND DRAIN STIMULUS, as ONE list ─────────────────────────
# apply_scenario() used to spell these names inline.  They are a set now
# because the alpha-sweep legs must carry the SAME drain as `ems-sdp` (they are
# the same stimulus by construction) and a second inline tuple would be a
# second place for the list to go stale.
# ⚠️ TWO OFFLINE MIRRORS of this list exist and are NOT updated by this file:
#   tools/gen_dp_ems_table.py  SOC_BAND_DRAIN_SCENARIOS
#   tools/ems_walk.py          _SIM_SOC_BAND_DRAIN_SCENARIOS
# Neither needs the alpha legs today — no DP table is solved for them and no
# walk is run on them — but an offline walk of an `ems-sdp-alpha-*` scenario
# would model HALF its demand until they are extended.  ems_walk.py already
# reports the coverage gap rather than assuming it away.
# `ems-mpc` / `ems-mpc-det` (2026-09-02) share `ems-soc-band`'s stimulus OBJECT
# and are ranked against `ems-soc-band` and `ems-dp-replay` on the `cycle61-mpc`
# frontier tuple, so they MUST carry the identical load — the B2 defect of
# 2026-09-01 was this omission for `ems-sdp`, and it halved that scenario's
# modelled demand.  `ems-mpc-cross` is deliberately absent, exactly as
# `ems-sdp-cross` is: its two cruise levels ARE the stimulus.  BOTH offline
# mirrors named above carry these two names as well.
SOC_BAND_DRAIN_SCENARIO_NAMES = ("ems-soc-band", "ems-dp-replay",
                                 "ems-sdp", "ems-mpc",
                                 "ems-mpc-det") + SDP_ALPHA_SCENARIOS

# ── ems-y-*: the firmware's 'Y' combined profile, four variants ─────────────
#
# DERIVED, not hand-written: every one of the four is built from the SAME
# (vmax, b) pair its strategy is, and every timing field comes from the
# EMS_Y_* constants next to make_ems_y().  Editing a duration here without
# moving those constants would be a scenario that ends before its own table
# does, which is why nothing below is a literal.
#
# THE TWO BANDS ARE DIFFERENT EXPERIMENTS, and the load split follows from that
# (operator adjudication, 2026-08-31) — see the make_ems_y() registration block
# for the full argument:
#   b30  + Y_AUX_LOAD_A preload -> CLOSED-LOOP SHARE TRACKING.  Share stays in
#        [0.30, 0.70], no cut is possible, and the preload holds the source
#        total above the 0.60 A governor gate for the whole table.
#   b00  + NO preload           -> CUT-AND-RESTORE TOPOLOGY.  Regions 6 and 11
#        command 1.00 and 0.00, outside [DROOP_R_MIN, DROOP_R_MAX], so
#        updateShareSetpointCutoff() opens BT_BUS and then FC_BUS.  A preload
#        would put the per-channel current above the cut's own
#        SHARE_CUT_MAX_HANDOFF_A 0.5 A guard and the latch would be REFUSED.
#        The price, stated: the Vmax-1 variant runs open-loop feedforward.
for _vmax, _b in ((1.0, 0.30), (3.0, 0.30), (1.0, 0.00), (3.0, 0.00)):
    _tag = "y-b%02d-v%g" % (round(_b * 100), _vmax)
    SCENARIOS["ems-" + _tag] = {
        "description": (
            "%.0f s: the firmware's own 'Y' combined drive-cycle + power-share "
            "table (16 regions, %.0f s, .ino:3162-3179) commanded from the EMS "
            "layer at Vmax %g m/s, share bound b = %.2f. %s"
            % (EMS_Y_DURATION_S, COMBINED_PROFILE_S, _vmax, _b,
               ("Closed-loop share tracking: the +%.2f A preload holds the "
                "source total above the 0.60 A governor gate and the bound "
                "keeps the share inside [DROOP_R_MIN, DROOP_R_MAX], so no cut "
                "occurs." % Y_AUX_LOAD_A) if _b else
               ("Cut-and-restore topology: regions 6 and 11 command share 1.00 "
                "and 0.00, tripping updateShareSetpointCutoff() both ways. NO "
                "preload (the cut's 0.5 A/channel guard would refuse the "
                "latch), so the share loop runs open-loop feedforward."))),
        # "any": the profile exercises the SETPOINT-side cut latch and the share
        # loop, neither of which needs the ideal-diode dynamics. Running it in
        # both engines is a free cross-check.
        "electrical": "any",
        "duration_s": EMS_Y_DURATION_S,
        "ems": _tag,
        # Per-scenario Run exit: the table ends at t = EMS_Y_END_S, well before
        # any strategy's own constant would fire. See ems_run_exit().
        "ems_run_exit_s": EMS_Y_RUN_EXIT_S,
        # NO ems_v_profile: this profile's strategy generates BOTH axes from the
        # firmware's table. fb["v_profile"] is None and the policy never reads it.
        **({"aux_preload_a": Y_AUX_LOAD_A} if _b else {}),
    }
del _vmax, _b, _tag

# ── ems-ftp75-*: the EPA FTP-75 study segment ───────────────────────────────
#
# THE PROFILE.  `tools/ftp75_profile.py` is GENERATED by
# `tools/gen_ftp75_profile.py` from the committed EPA raw file
# `references/drive_cycles/ftpcol.txt` (sha256 verified at generation time).
# It is the cycle's FIRST 340 SECONDS — the segment of the scaled-vehicle study
# references/Systemic_Scaling_of_Powertrain_Models_with_Youla_Driver_Control.pdf
# (operator direction, 2026-08-31), not a trim of Phase 1 chosen for run length
# — rescaled by ONE constant (3.0/56.7 m/s per mph, so the 56.7 mph peak at raw
# t = 240 s lands on 3.0 m/s) and shifted to start at t = 5.0 s.  t = 340 falls
# in a NATIVE idle segment (0 mph from raw t = 333), so the table ends at rest
# and carries no synthetic ramp-down tail.  No dynamic-similarity claim is made
# by the scaling: it is a range map onto the speeds this bench has driven
# (3.0 m/s is ML0169's measured hold, CLAUDE.md fw v16).
#
# WHAT THESE TWO SCENARIOS ARE FOR.  Every EMS scenario before them runs a
# hand-authored 8-point profile.  A standard cycle is the first stimulus long
# enough and varied enough to be an ENDURANCE test of the EMS layer rather than
# a transient one: 345 s of continuous 50 Hz commanding, ~30 accelerate/cruise/
# decelerate/idle cycles, and an H2 total accumulated over something a reader
# outside this project recognises.
#
# COST, stated up front: 350 s each, so the pair adds ~11.7 min to a campaign
# that is otherwise ~34 min. That is why run_hil_suite.py gates them behind
# --with-ftp75 and renders them SKIPPED by default.
#
# THE AUXILIARY PRELOAD IS REMOVED — 0.65 A -> 0.0 A (operator ruling,
# 2026-09-01).  The constant is KEPT, at zero, because it is inside
# collect_model_constants() and inside DP_FINGERPRINT_META_KEYS: deleting the
# key would silently un-cover the fingerprint, and zero is a legal value that
# every truthiness guard below already accepts.
#
# WHY IT WAS THERE (history, so a reader does not reintroduce it by accident).
# The preload existed to hold the source total above the firmware's
# closed-loop share gate, 2*SHARE_MINORITY_I_MIN_A = 0.60 A, through the
# cycle's idle segments.  The FTP-75 is roughly a third idle and its own load
# leaves the total at I_AUX_A = 0.15 A there, so +0.65 A put the standstill
# total at 0.800 A and made 100.00 % of the post-ramp run closed-loop.  The
# cost was stated at the time and is what the ruling acts on:
#   * it FORECLOSED `soc-band`'s charge branch on this cycle
#     (SOC_BAND_CHARGE_ENTER_ITOT_A = 0.60 A against a 0.800 A floor), so the
#     socband leg exercised the share-bias branch and nothing else;
#   * it spent current margin at the cycle peak, which is why the sdp leg had
#     to run a DIFFERENT preload (0.45 A) and why the drive-cycle EMS frontier
#     could not evaluate — its three legs were not one experiment;
#   * and it removed the open-loop-hold behaviour from the test set entirely.
#
# WHY ZERO IS THE RIGHT VALUE NOW.  The sub-0.55 A stretches are TEST CONTENT,
# not a defect to be loaded away: the firmware runs OPEN-LOOP HOLD below
# 2*SHARE_MINORITY_I_MIN_A - SHARE_GOV_OL_HYST_A = 0.55 A, and a drive-cycle
# scenario that never enters that mode never exercises it.  The governor walk
# (tools/ems_walk.py, governor=True) puts the FTP-75 at preload 0 in
#     open_hold 9.71 %,  open_feedforward 57.12 %,  closed 33.17 %
# of governor ticks, against open_hold 0.00 % / closed 98.25 % at 0.65 A.  Any
# check on these scenarios whose derivation assumed "the loop is closed for the
# whole cycle" is therefore FALSE from this commit and is re-derived in
# run_hil_suite.py per segment, per the standing walk rule (:2179-2219).
#
# CURRENT BUDGET AT PRELOAD 0, from gen_dp_ems_table.build_demand():
#     peak source total   0.9603 A at t = 243.9 s  (was 1.6128 A model /
#                         1.6551 A measured at 0.65 A)
#     idle source total   0.1500 A  (= I_AUX_A; was 0.800 A)
# The measured GAIN OFFSET of +2.6 % (campaign 20260831_191509 — one offset,
# not three independent errors) still applies, so the hardware peak is expected
# near 0.9853 A.  Every channel margin therefore WIDENS: hold-5050's 0.50 split
# is ~0.493 A and soc-band's 0.75 ceiling is ~0.739 A, both far under
# LIMIT_I_FC_MAX 1.4 A, and the OC_FC exposure the sdp preload was sized
# against is gone.
#
# ⚠️ TWO BASELINE-ERA BOUNDARIES, AND CAMPAIGN 20260901_151156 IS THE LAST
# CAMPAIGN ON THE FAR SIDE OF BOTH.  Read them together — a total from that
# campaign differs from a current one for two independent reasons:
#   1. THE PRELOAD (this block): the FTP-75 legs ran at 0.65 A (0.45 A on the
#      sdp leg) up to and including that campaign; they run at 0.0 after it.
#   2. THE CONVERTER ASYMMETRY (the C1 round, 2026-09-01): the plant ran two
#      IDENTICAL boost chains up to and including that campaign, and runs the
#      fitted FC/BT mismatch (DeltaV0 +0.0444 V, droop_scale_fc 0.930) after
#      it, by default.  The FC chain then carries more of every load, so every
#      hydrogen total rises and every SoC fall shrinks.  MEASURED on the
#      governor walk, symmetric -> asymmetric: 5050 +9.40 %, socband +4.53 %,
#      sdp +4.40 %, dp +6.35 % of hydrogen.  `--asymmetry off` restores the
#      symmetric plant for a deliberate comparison.
# The 0.65 A-era totals, for the record, are NOT comparable with anything
# after this commit:
#     ems-ftp75-5050    0.0647   g / dSoC -0.02648
#     ems-ftp75-socband 0.09159  g / dSoC -0.01533
#     ems-ftp75-sdp     0.0622   g / dSoC -0.01845
#     ems-ftp75-dp      0.09291  g / dSoC -0.01478
# constants_hash moves with this commit, and so does the ems-ftp75-dp table's
# profile_fingerprint (aux_preload_a is a fingerprinted key).
#
# ⚠️ `Y_AUX_LOAD_A` IS UNCHANGED at 0.85 A (operator ruling, 2026-09-01): on
# the ems-y-b30-* scenarios the auxiliary load CONSTRUCTS the stimulus — it is
# what makes those scenarios' share bounds deliverable at all — rather than
# masking a mode the way it did here.
#
# ⚠️ These are the MODEL's currents (M_EFF/K_F/F_COULOMB/B_EFF + the droop
# bus), not measurements.  A campaign that misses a share-tracking check should
# re-derive the check, not reinstate this load.
FTP75_PRELOAD_A = 0.0
# MODE_SAFE 1 s after the table's last point (t = 345.0), then 4 s for
# Run -> Finish -> Idle.  The table already ends at rest — raw t = 333 onward is
# 0 mph, so the last 7 s of it are a native idle — which is why 1 s of margin
# is enough here rather than the usual 3 s after a moving stimulus.  Both
# declared per-scenario; without `ems_run_exit_s` hold-5050 would hand back
# MODE_SAFE at t = 55 and idle for the other 295 s.
FTP75_RUN_EXIT_S = FTP75_T_END + 1.0        # 346.0
FTP75_DURATION_S = FTP75_RUN_EXIT_S + 4.0   # 350.0

for _name, _ems, _what in (
    ("ems-ftp75-5050", "hold-5050",
     "constant 50/50 split, so any share deviation belongs to the firmware's "
     "share loop and the plant and never to the EMS"),
    # ⚠️ WHAT THE socband VARIANT EXERCISES AT PRELOAD 0 — RE-DERIVED
    # 2026-09-01, when the preload was removed.  The previous statement here
    # ("saturates at 0.75 by t = 46.8 s and NEVER comes back, because the
    # charge branch is foreclosed by the preload") was true of the 0.65 A era
    # and is FALSE now, in both of its clauses:
    #   * THE BIAS SATURATES LATER.  The governor walk at preload 0
    #     (tools/ems_walk.py, soc-band, governor=True) puts the share command
    #     at 0.50 until t = 78.4 s, ramping to the 0.75 ceiling at t = 111.5 s
    #     and holding it for 68.1 % of the run — against t = 46.8 s measured at
    #     0.65 A.  The pack is discharged more slowly because the load is
    #     smaller, so the deficit takes longer to open.
    #   * THE CHARGE BRANCH IS REACHABLE AGAIN.  `soc-band` admits a charge
    #     window below SOC_BAND_CHARGE_ENTER_ITOT_A = 0.60 A of source total,
    #     and the idle source total is now I_AUX_A = 0.15 A — a factor of four
    #     under the gate, in every one of the cycle's idle segments.  The
    #     scenario therefore exercises BOTH of the policy's branches for the
    #     first time.
    #   ⚠️ WHAT THE WALK CANNOT PREDICT, stated: ems_walk.py gates charge
    #     admission on gen_dp_ems_table.charge_mask() (the DP's cruise +
    #     FC-budget test), NOT on the firmware/strategy pair's own
    #     enter/hold hysteresis, so whatever it reports is the MASK's
    #     schedule and never the strategy's.  The window SCHEDULE on this
    #     cycle is unmodelled and must come from the first zero-preload
    #     campaign; the run_hil_suite.py entry asserts only that a window
    #     opens, with a deliberately wide existence bound.
    #     ⚠️ PART C (C1 round, 2026-09-01): the "0 charge windows" figure
    #     this note used to quote was STALE — it predates the
    #     `chg_i_ceiling_a` 0.8 key added to this scenario in the same
    #     round.  Against the SHIPPED registry the walk reports TWO windows,
    #     191.700-194.000 s and 329.200-330.000 s (3.1 s in total).  That
    #     changes nothing structural: they are still the DP mask's windows,
    #     not the strategy's, and 3.1 s at the 0.8 A ceiling is ~0.3 % of
    #     the cycle's hydrogen total.
    ("ems-ftp75-socband", "soc-band",
     "the causal charge-sustaining policy over a long cycle: the SoC deficit "
     "walks the split toward the fuel cell, reaching the 0.75 ceiling at "
     "t = 111.5 s (governor walk, preload 0) and holding it for ~68 % of the "
     "run, while the cycle's idle segments drop the source total to 0.15 A "
     "and open its CHARGING branch"),
    # Governor walk against the SHIPPED registry (PART C, 2026-09-01):
    #   symmetric  plant 0.035562 g / physical 0.036381 / dSoC -0.008177
    #   asymmetric plant 0.037208 g / physical 0.038028 / dSoC -0.007513
    # The run_hil_suite.py bands are taken from the ASYMMETRIC pair, because
    # the plant's converter asymmetry is default-on from the C1 round.
):
    SCENARIOS[_name] = {
        "description": ("%.0f s EPA FTP-75 study segment (raw t = 0..340 s "
                        "inclusive, 341 samples at 1 Hz; scaled "
                        "to a 3.0 m/s peak) driven by the `%s` EMS strategy: %s. "
                        "Gated behind run_hil_suite.py --with-ftp75."
                        % (FTP75_DURATION_S, _ems, _what)),
        "electrical": "any",
        "duration_s": FTP75_DURATION_S,
        "ems": _ems,
        # THE SAME LIST OBJECT for both, as ems-dp-replay shares ems-soc-band's:
        # the two scenarios differ only in the strategy driving them, and a
        # comparison between them is meaningless on different stimuli.
        "ems_v_profile": FTP75_PROFILE,
        "ems_run_exit_s": FTP75_RUN_EXIT_S,
        "aux_preload_a": FTP75_PRELOAD_A,
    }
del _name, _ems, _what

# THE CHARGER CEILING ON THE socband LEG (added 2026-09-01 with the preload
# removal).  Two reasons, and both are consequences of that removal:
#   * The charge branch is REACHABLE now (see the block above), so an
#     undeclared ceiling would no longer be inert — the leg would run the
#     Ag105 at AG105_I_MAX 2.5 A while `ems-ftp75-sdp` and `ems-ftp75-dp` cap
#     it at 0.8 A.
#   * That 3x disagreement is EMS_FRONTIER_FTP75's stimulus-coherence split 2
#     (run_hil_suite.py).  Declaring the siblings' value resolves it by
#     construction rather than by whitelist.
# `ems-ftp75-5050` deliberately does NOT get the key: `hold-5050` never
# commands `charge_goal`, so the ceiling there would be dead declaration.
SCENARIOS["ems-ftp75-socband"]["chg_i_ceiling_a"] = (
    SCENARIOS["ems-soc-band"]["chg_i_ceiling_a"])

# ── ems-ftp75-mpc: the FTP-75 segment driven by the MPC (2026-09-02) ────────
# Registered HERE rather than inside the loop above because the loop's three
# legs predate it and their tuple is quoted in the ledger; appending a fourth
# element to it would move nothing but would make the diff read as a change to
# the three. Every stimulus key is the siblings' BY REFERENCE — the same
# profile object, the same Run exit, the same zero preload, the same 0.8 A
# ceiling — because `ftp75-mpc`'s whole purpose is a comparison against them.
# Gated behind run_hil_suite.py --with-ftp75 (FTP75_SCENARIOS).
SCENARIOS["ems-ftp75-mpc"] = {
    "description": ("%.0f s EPA FTP-75 study segment (raw t = 0..340 s "
                    "inclusive, 341 samples at 1 Hz; scaled to a 3.0 m/s peak) "
                    "driven by the governor-aware `mpc-sto` receding-horizon "
                    "controller: a 20-stage, 1 Hz plan over the pack SoC whose "
                    "prediction model carries the firmware's share governor. "
                    "Its demand comes from the TPM's conditional mean, not "
                    "from this profile. The candidate leg of the `ftp75-mpc` "
                    "frontier tuple. Gated behind run_hil_suite.py "
                    "--with-ftp75." % FTP75_DURATION_S),
    "electrical": "any",
    "duration_s": FTP75_DURATION_S,
    "ems": "mpc-sto",
    # THE SAME LIST OBJECT as the three sibling legs.
    "ems_v_profile": FTP75_PROFILE,
    "ems_run_exit_s": FTP75_RUN_EXIT_S,
    "aux_preload_a": FTP75_PRELOAD_A,
    # By reference off the leg assigned immediately above — `ems-ftp75-sdp` and
    # `ems-ftp75-dp` are registered further down this file and are not yet in
    # the registry at this point; all three carry the same 0.8 A, and the
    # frontier's stimulus-coherence precondition asserts that they do.
    "chg_i_ceiling_a": SCENARIOS["ems-ftp75-socband"]["chg_i_ceiling_a"],
    # DETERMINISTIC CANDIDATE CAP — see MPC_CAMPAIGN_MAX_CANDIDATES.
    "mpc_max_candidates": MPC_CAMPAIGN_MAX_CANDIDATES,
    # THE DEMAND-MODEL ERA THE PLANNER PREDICTS ON — see `ems-mpc`.
    "mpc_loss_map": plant_loss_map(),
}

# ── ems-ftp75-sdp: the FTP-75 segment with the SDP policy STARTED ABOVE ITS
#    TARGET, so the bang-bang share law switches once, mid-cycle ────────────
#
# WHAT IS NEW HERE, and it is one thing.  Every `ems-sdp`-family run before this
# one started EXACTLY on the policy's target node and could only discharge, so
# the table sat on its fuel-cell branch for the whole run and the wire carried
# ONE constant clamped 0.8500 (SdpStrategy's PREDICTED BEHAVIOUR block, point
# 1).  This scenario declares `sdp_soc_ref_offset` (see
# SdpStrategy.set_soc_ref_offset()), which starts the run FTP75_SDP_SOC_REF_
# OFFSET above the node — on the table's OTHER branch, action 0.00, emitted at
# the SOC_BAND_SHARE_MIN clamp as 0.15 — and lets the cycle's own drain walk it
# across the switching boundary.  The observable is a SINGLE, SHARP transition
# of `cmd_share_sp` from 0.15 to 0.85 part-way through the cycle: the policy's
# switching law itself, which nothing in the suite has ever put on the wire.
#
# THE OFFLINE WALK (2026-08-31) that every number below comes from.  The
# strategy's own decision path (soc0 capture with the offset, soc_relative(),
# demand_bin(), the table lookup, clamp_share()) stepped at 20 Hz over the
# gen_dp_ems_table.py demand model of THIS profile and preload — the same
# reduced model the DP benchmark is solved against — with the pack integrated
# through hil_electrical.BatterySource and the firmware's minority-current
# governor applied to the delivered split.  Cross-checked against the MEASURED
# `ems-ftp75-5050` trace of campaign 20260901_000816: the model's peak source
# total is 1.613 A against a measured 1.6551 A, the documented +2.6 % gain
# offset of the FTP75_PRELOAD_A block, and nothing below depends on which of
# the two is used except by that ratio.
#
#   FLIP TIME:            t = 195.9 s (model, 0.45 A preload); MEASURED
#     t = 198.537 s (campaign 20260901_024231, +1.35 % on the walk).  The flip
#     time is an INTEGRAL of the drain, so it moves with the load: a +/-10 %
#     error in the pack current moved it to 180 s / 205 s and +/-20 % to
#     158 s / 216 s, which is how the suite's original (150, 250) band was set
#     and how the later (185, 212) band was tightened.
#     ⚠️ RE-PREDICTED AT PRELOAD 0 (2026-09-01, the preload removal):
#         C:/Users/ricky/miniforge3/python.exe -c "import sys; sys.path.insert(
#             0,'tools'); import ems_walk as W;
#             print(W.walk('sdp-v3','ems-ftp75-sdp',governor=True).summary())"
#         (the scenario's `sdp_soc_ref_offset` is applied by bind_scenario(),
#          so no strategy_kwargs are needed)
#     gives ONE transition, 0.15 -> 0.85, at t = 272.0 s — the drain is
#     smaller without the 0.45 A preload, so the state takes 39 % longer to
#     reach the switching surface.  The SAME walk reproduces the 0.45 A era to
#     within 1.8 % on every measured quantity (flip 196.0 s vs 198.537
#     measured; h2 0.061096 g vs 0.0622 measured; dSoC -0.018712 vs -0.01845),
#     which is the basis for trusting the 272.0 s figure at ~+/-2 %.  Scaling
#     by the measured/walk flip ratio 198.537/196.0 gives an expected board
#     flip near t = 275.5 s.  The suite band is re-opened PROVISIONALLY around
#     it and must be re-derived from the first zero-preload campaign.
#   RAW TABLE REQUESTS:   {0.00} before the flip, {1.00, 0.95} after (0.95 in
#     bin 22, the cycle's own peak).  EMITTED: {0.15, 0.85}.
#     ⚠️ MEASURED (campaign 20260901_024231): raw 0.00 flat pre-flip, 1.00 with
#     0.95 dips post-flip — bin 24 was NOT entered on that run.  The suite's raw
#     floor stays at 0.89 anyway, because it guards the bin-24 boundary case the
#     cycle's peak demand sits ~4 % below; see `sdpftp_raw_fc_branch`.
#   CHARGING:             NONE, by construction — the walk's demand never falls
#     below bin 9 inside the Run window (P_dem 9.6..22.4 W) and the solver
#     forbids charging above bin 5.  This scenario is a PURE share-axis test.
#
# ⚠️ CURRENT BUDGETS, both branches, RE-DERIVED AT PRELOAD 0 (2026-09-01).
# The source total is now I_AUX_A + the cycle's own draw, so the model peak is
# 0.9603 A at t = 243.9 s and the measured-composition peak is 0.15 + 0.8546 =
# 1.0046 A (the measured span of the cycle's own contribution is unchanged by
# the preload; it is an ADDITIVE term).
#   * BATTERY-HEAVY branch (commanded 0.15).  The commanded value is still
#     ALWAYS below the governor's minority floor SHARE_MINORITY_I_MIN_A / I_tot
#     — at the peak that floor is 0.300/1.0046 = 0.299, and the idle floor is
#     larger still — so the DELIVERED split is the floor and I_fc is pinned at
#     exactly 0.300 A wherever the loop is closed.  Peak I_bt is
#     I_tot - 0.300 = 0.705 A, 77 % under LIMIT_I_BT_MAX 3.0 A.
#   * FUEL-CELL branch (commanded 0.85).  Mirror image: the governor clips to
#     1 - I_min/I_tot, so I_fc = I_tot - 0.300 and its peak is at the CYCLE
#     PEAK — 0.6603 A model, 0.7046 A on the measured composition, i.e. 50 %
#     under LIMIT_I_FC_MAX 1.4 A (it was 17.5 % at the 0.45 A preload).
#     ⚠️ Do NOT scale the model's FC branch by the +2.6 % gain offset instead:
#     that would apply the offset to the 0.300 A governor floor, which is a
#     firmware constant and does not move with the drive model.
#   * ⚠️ THE OC_FC CONSTRAINT NO LONGER BINDS ANYTHING.  Half the FC limit is
#     free at the cycle peak, so the reason this scenario once needed its OWN
#     preload is gone.  Do not treat the 50 % margin as licence to reintroduce
#     a load: the mode content (open-loop hold in the idle segments) is the
#     test content now — see the FTP75_PRELOAD_A block.
#   * ⚠️ THE LOOP IS NO LONGER CLOSED THROUGHOUT.  At 0.45 A the honest
#     claim was "closed after the first acceleration"; at preload 0 the idle
#     source total is 0.15 A, far below the 0.55 A open-loop exit threshold,
#     so the share loop OPENS in every idle segment.  The governor walk puts
#     the run at open_hold 9.71 % / open_feedforward 57.12 % / closed 33.17 %
#     of ticks.  Any check that assumed a closed loop in an idle segment is
#     false and is re-derived in run_hil_suite.py.
# ── ARTIFACT: `sdp-v3`, AND THE WALK TRANSFERS VERBATIM (2026-09-01) ────────
# The walk above was measured against `sdp_policy_v2.json`.  This entry was
# rebound to the CALIBRATED BENCHMARK artifact in the charge-economics round,
# and the walk was NOT re-run — because a direct row-by-row diff of the two
# baked tables shows it does not need to be.  VERIFIED, not assumed:
#
#   SHARE MAP.  `policy.share` is byte-identical between v2 and v3 at EVERY SoC
#   row from index 3 upward; the two artifacts differ in 30 cells, all on rows
#   1 and 2.  This scenario's trajectory spans rows 63 (soc_rel = target +
#   0.013 at t = 0) down to ~44 (target + 0.013 - 0.0187 at the cycle end), so
#   it never comes within 41 rows of a differing cell.  Every number in the
#   walk — the 0.15/0.85 emitted pair, the {0.00} / {1.00, 0.95} raw requests,
#   the t = 195.9 s flip and its (150, 250) s band — is therefore the SAME
#   under v3, arithmetically and not merely approximately.
#
#   CHARGE MAP.  v2 carries charge cells on rows 1-49 in demand bins 0-5 only;
#   v3 carries none anywhere.  This scenario's walk shows the demand never
#   falling below bin 9 inside the Run window (P_dem 9.6..22.4 W), so it reached
#   no charge cell under v2 either — the rebinding removes cells the trajectory
#   could not visit.  "NO charge stage is reachable" was already this entry's
#   claim; under v3 it is additionally true by construction.
#
# CONSEQUENCE: this scenario stays a PURE SHARE-AXIS test, its FAULT_EXPECTATIONS
# thresholds are unmoved, and it is frontier-eligible by strategy — though the
# frontier CHECK scores only the three legs of the one shared stimulus
# (`ems-sdp` / `ems-soc-band` / `ems-dp-replay`), not this cycle.
FTP75_SDP_SOC_REF_OFFSET = 0.013
# THE PRELOAD IS REMOVED — 0.45 A -> 0.0 A (operator ruling, 2026-09-01), in
# lockstep with FTP75_PRELOAD_A.  The constant is KEPT at zero for that block's
# reasons (fingerprint coverage and the truthiness guards).
#
# WHY IT WAS 0.45 AND NOT 0.65 (history).  This leg commands the 0.85 share
# rail, and at 0.65 A the governed FC peak was I_tot - 0.300 = 1.355 A on the
# measured composition — 3.2 % under LIMIT_I_FC_MAX.  An OC_FC latch would have
# truncated the run at exactly the point the scenario exists to observe (the
# post-flip half), so the preload was solved DOWN to the value that left 17.5 %
# of margin.  That derivation was sound and it is simply moot now: at preload 0
# the same branch peaks at 0.7046 A, 50 % under the limit.
#
# WHAT REMOVING IT COSTS AND BUYS.  It moves the flip LATE — t = 272.0 s
# (governor walk) against 198.537 s measured — because the flip is a drain
# integral; the suite's transition band is re-opened provisionally around the
# new prediction.  It also OPENS the share loop through the cycle's idle
# segments, which is the point of the ruling: open-loop hold is test content.
# And it makes this leg's stimulus identical to its two FTP-75 siblings' for
# the first time, which is what resolves EMS_FRONTIER_FTP75's split 1 — the
# drive-cycle EMS frontier can now evaluate.
#
# ⚠️ BASELINE-ERA BOUNDARY: this leg measured 0.0622 g / dSoC -0.01845 at the
# 0.45 A preload (campaigns up to hil_report_20260901_151156).  Not comparable
# with anything after this commit; the walk predicts 0.019347 g / -0.014922.
FTP75_SDP_PRELOAD_A = 0.0
SCENARIOS["ems-ftp75-sdp"] = {
    "description": ("%.0f s EPA FTP-75 study segment (the SAME profile object "
                    "as the other two FTP-75 scenarios) driven by the causal "
                    "`sdp-v4` policy started %+.3f SoC ABOVE its target node: "
                    "the table begins on its battery-heavy branch (commanded "
                    "share 0.15), the cycle's own drain walks the state across "
                    "the switching boundary, and `cmd_share_sp` steps ONCE to "
                    "0.85 mid-cycle. The first scenario in which the SDP "
                    "policy's bang-bang share law is visible on the wire. "
                    "Gated behind run_hil_suite.py --with-ftp75."
                    % (FTP75_DURATION_S, FTP75_SDP_SOC_REF_OFFSET)),
    # "any": nothing here needs the ideal-diode dynamics — the observable is a
    # commanded setpoint and the governed split that follows it.  Running it
    # under either engine is a free cross-check, as on `ems-sdp`.
    "electrical": "any",
    "duration_s": FTP75_DURATION_S,
    # THE CALIBRATED BENCHMARK artifact for the eta_chg = 0.88 charger
    # (rebound from `sdp-v3` 2026-09-02).  The v2-derived offline walk above
    # transfers VERBATIM — see the row-diff verification at
    # FTP75_SDP_SOC_REF_OFFSET, extended to v4 there.
    "ems": "sdp-v4",
    # THE SAME LIST OBJECT as the other two FTP-75 scenarios: the three differ
    # only in the strategy driving them, and a comparison between them is
    # meaningless on different stimuli.
    "ems_v_profile": FTP75_PROFILE,
    "ems_run_exit_s": FTP75_RUN_EXIT_S,
    "aux_preload_a": FTP75_SDP_PRELOAD_A,
    "sdp_soc_ref_offset": FTP75_SDP_SOC_REF_OFFSET,
    # Inherited from `ems-sdp`, and INERT here: the walk shows no charge-
    # admissible stage anywhere in the Run window (see above).  Declared so a
    # future profile change that DOES admit one cannot silently run the charger
    # at AG105_I_MAX.
    "chg_i_ceiling_a": SCENARIOS["ems-soc-band"]["chg_i_ceiling_a"],
}

# ── ems-ftp75-dp: the FTP-75 segment's NON-CAUSAL LOWER BOUND ───────────────
#
# The deferral note that stood here ("a DP table for an FTP-75 scenario is
# FUTURE WORK ... ~21 min offline") is CLOSED, 2026-09-01 (WP-E).  This is the
# drive-cycle twin of `ems-dp-replay`: the same 340 s stimulus the other three
# `ems-ftp75-*` scenarios run, driven by a table computed offline with full
# foreknowledge of the whole cycle and of the auxiliary load.
#
# THE STIMULUS IS `ems-ftp75-5050`/`-socband`'s, TERM FOR TERM — the same
# FTP75_PROFILE list object, the same FTP75_RUN_EXIT_S, and the same
# FTP75_PRELOAD_A.
#
# ⚠️ AND AS OF 2026-09-01 IT IS ALSO `ems-ftp75-sdp`'s, term for term: the
# preload removal set FTP75_PRELOAD_A and FTP75_SDP_PRELOAD_A both to 0.0, so
# all four FTP-75 legs now carry one stimulus.  That is what resolves
# EMS_FRONTIER_FTP75's split 1 (run_hil_suite.py); the previous statement here
# — "the drive-cycle EMS frontier does NOT currently evaluate" — is retired.
#
# ⚠️ THE TABLE WAS RE-SOLVED for the zero-preload demand.  `aux_preload_a` is
# in DP_FINGERPRINT_META_KEYS, so the shipped table's profile_fingerprint moves
# with the constant and a stale table is REFUSED at load rather than played.
# WHY `chg_i_ceiling_a` IS DECLARED HERE and not on the 5050/socband siblings:
# on `ems-ftp75-5050` the charger is unreachable by construction (hold-5050
# never commands `charge_goal`), so the ceiling is inert there and its absence
# costs nothing.  `ems-ftp75-socband` DOES declare it as of 2026-09-01: the
# preload removal re-opened its charge branch, so an undeclared ceiling would
# have handed the reference leg a 2.5 A lever the candidates never had.  A DP
# table needs the declaration for the same reason from the other side — the
# solver decides charging for itself.  0.8 A is the value all three carry, and
# it is fingerprinted, so it cannot drift silently.
#
# THE TABLE: tools/dp_tables/dp_ems_table_ems-ftp75-dp.csv, ~21 min to solve
# (stage-count-dominated; ~6x `ems-dp-replay`'s cycle).  Regenerate with
#     C:/Users/ricky/miniforge3/python.exe tools/gen_dp_ems_table.py \
#         --scenario ems-ftp75-dp --force
# "hifi", for `ems-dp-replay`'s reason exactly: the shipped table is solved
# --charger-accounting physical and bind_scenario() refuses the mismatch.
#
# ⚠️ `tools/dp_tables/dp_ems_table_ems-ftp75-5050.csv` IS NOW ORPHANED and can
# never load: its `profile_fingerprint` is keyed to the scenario name
# `ems-ftp75-5050`, which is not a dp-replay scenario, and it was computed
# under the pre-WP-E key tuple that did not cover `aux_preload_a`. Nothing is
# lost by deleting it — the new table's DATA ROWS were verified BYTE-IDENTICAL
# to it (3501 rows, independently re-solved 2026-09-01), so it is the same
# solution under a covered fingerprint. It is left in place rather than
# deleted here because removing a committed artifact is an operator decision.
SCENARIOS["ems-ftp75-dp"] = {
    "description": ("%.0f s EPA FTP-75 study segment (the SAME profile object "
                    "and the SAME %.2f A preload as `ems-ftp75-5050` and "
                    "`ems-ftp75-socband`) driven by the NON-CAUSAL "
                    "`dp-replay` benchmark: a setpoint table computed offline "
                    "by backward dynamic programming with full foreknowledge "
                    "of the cycle. Not a controller — the offline-optimal "
                    "lower bound the causal drive-cycle strategies are ranked "
                    "against. Gated behind run_hil_suite.py --with-ftp75."
                    % (FTP75_DURATION_S, FTP75_PRELOAD_A)),
    "electrical": "hifi",
    "duration_s": FTP75_DURATION_S,
    "ems": "dp-replay",
    # THE SAME LIST OBJECT as the other three FTP-75 scenarios.
    "ems_v_profile": FTP75_PROFILE,
    "ems_run_exit_s": FTP75_RUN_EXIT_S,
    "aux_preload_a": FTP75_PRELOAD_A,
    "chg_i_ceiling_a": SCENARIOS["ems-soc-band"]["chg_i_ceiling_a"],
}

# ═════════════════════════════════════════════════════════════════════════════
# ems-ftp75c-*: THE COMPRESSED FTP-75 SEGMENT ON A COMPENSATED ROAD LOAD
#     (2026-09-02; docs/modeling/ftp75c_regen_cycle_design_20260902.md)
#
# WHY THIS FAMILY EXISTS.  THE RIG, AS INSTRUMENTED, REGENERATES NOTHING.  Its
# road load exceeds the inertial force at every deceleration the FTP-75 segment
# contains, so the measured regen share of braking kinetic energy is 0.00 % on
# `ftp75` AND 0.00 % on the compressed cycle at rig drag (0.001 J of 30.82 J).
# The regen path, the Ag105's regen branch and the DP's braking credit have
# therefore never been exercised by a drive cycle at all.
#
# WHAT THE TWO CHANGES DO, separately.  TIME COMPRESSION (factor 0.5, velocity
# untouched) doubles every acceleration, which brings the required regen current
# into the same decade as the VESC clip and halves the rig's inertia deficit
# against dynamic similarity.  ROAD-LOAD COMPENSATION (`--drag scaled-air`)
# replaces the measured Coulomb-plus-viscous load with the scaled air drag of
# the study vehicle, and it is THIS that creates the regenerative energy.  On
# the compensated compressed cycle 51.25 % of braking kinetic energy is
# available at the shaft, 15.66 J survives the 1.5 A VESC clip and 12.53 J
# reaches the V-MOT node.
#
# ⚠️ NO DYNAMIC-SIMILARITY CLAIM.  The compressed rig is still 4.49x more
# drag-dominated than the vehicle it stands for (DRAG_INERTIA_RESIDUAL), which
# is exactly why the ruled `scaled-air` profile reaches 51.25 % where the
# full-scale vehicle reaches 79.09 %.  `ftp75c` is a stimulus chosen so the
# regenerative mechanism is exercised at currents the hardware can produce.  It
# does not amend the published scaling study, which deliberately did not
# time-scale its cycle.
#
# ⚠️ THE CREDIT IS SMALL AGAINST THE DRAIN, and no frontier conclusion may rest
# on it being otherwise.  0.99 C reaches the pack per cycle against roughly
# 96.8 A s of pack draw - 1.4 %, a SoC gain near +5.5e-5 against a -0.0054
# excursion.  Because the regen manager is COMMON and the credit is
# share-independent, EVERY strategy receives the same credit on the same
# windows: `ftp75c` validates the regen model end to end and closes the DP's
# regen divergence, and it is NOT expected to reorder the strategies.  A
# reordering on this stimulus is a DEFECT SIGNAL, not a result.
#
# ⚠️ NOT BENCH-REPLICABLE.  Road-load compensation needs a SECOND motor acting
# as a road-load brake on the flywheel (~3.1 N, 0.24 N m, 400 rpm, under 10 W,
# four-quadrant).  A friction feedforward through the traction motor keeps the
# net motor force POSITIVE through a stop, so no current reverses and there is
# nothing to measure.  On the bench the rig profile remains the only physically
# honest configuration, and it regenerates nothing.  Design note section 7.
# ═════════════════════════════════════════════════════════════════════════════
FTP75C_PRELOAD_A = 0.0
# The same derivation as the FTP-75 pair, term for term: MODE_SAFE 1 s after the
# table's last point, then 4 s for Run -> Finish -> Idle.  The 1 s margin rather
# than the usual 3 s is justified for the same reason and by the same evidence -
# raw t = 333 onward is 0 mph, which compresses to a 3.5 s idle tail, so the
# table already ends at rest.
FTP75C_RUN_EXIT_S = FTP75C_T_END + 1.0        # 176.0
FTP75C_DURATION_S = FTP75C_RUN_EXIT_S + 4.0   # 180.0
# THE COMMANDED REGEN WINDOWS, derived from the profile and the drag profile at
# module scope rather than hand-tabulated - see derive_regen_windows().  Bound
# to the SCENARIOS entries so a reader can see them, and re-derived at run time
# from whatever `--drag` actually resolves to, so a rig-drag control run of the
# same scenario gets the (empty) window list its own physics implies.
FTP75C_REGEN_WINDOWS = derive_regen_windows(FTP75C_PROFILE,
                                            DRAG_MODE_SCALED_AIR)
# ── THE soc-band CURRENT THRESHOLDS ON THIS PROFILE ─────────────────────────
# `SOC_BAND_CHARGE_ENTER_ITOT_A` is 0.60 A and the compensated cycle's PEAK
# source total is 0.331 A, so the shipped threshold sits above the whole cycle:
# the strategy would admit a charge window at the first cruise sample and never
# exit it by current, and a charge-saturated leg is useless as the frontier's
# REFERENCE.  Both thresholds therefore need a per-scenario override.
#
# ⚠️ DIVIDING BY `DRAG_INERTIA_RESIDUAL` WAS WRONG, AND IT FAILED SILENTLY
# (H2, 2026-09-02).  The source total is `I_AUX_A + i_motor + i_par`, and the
# 0.15 A auxiliary floor DOES NOT SCALE with the road load - only the motor term
# does.  Scaling the whole threshold put ENTER at 0.13373 A, BELOW the walk's
# own minimum source total of 0.15079 A, so `ems-ftp75c-socband` opened ZERO
# charge windows against the rig leg's four.  The reference leg did not exercise
# the soc-band mechanism at all, and `ftp75c_socband_not_saturated` bounded only
# `max_ticks`, so never charging passed it silently.
#
# THE SHIPPED PAIR IS PERCENTILE-MATCHED against the rig leg, so the threshold
# occupies the same POSITION IN THE DEMAND DISTRIBUTION on both cycles rather
# than the same absolute current.  That is the right invariant: what the
# threshold selects is "a low-demand cruise", which is a statement about the
# cycle's own distribution.
#     ENTER 0.18074 A - the 57.9th percentile of this leg's Run-window source
#                       total, the position 0.60 A occupies on the rig leg.
#     EXIT  0.33107 A - this cycle's MAXIMUM source total, which is where
#                       1.30 A lands: it is above the rig leg's own maximum
#                       (0.977 A), so on both cycles the exit threshold is
#                       "never exit by current alone".
#
# ⚠️ THE CONVENTION IS NOT UNIQUE, and the alternative is recorded rather than
# hidden.  Matching on the rig leg's Run-window percentile of 0.60 A (66.6th)
# rather than on this leg's own gives ENTER 0.20715 A.  Both clear the 0.15079 A
# floor and both open windows; 0.18074 is the ruled value and is the more
# conservative of the two.  A re-derivation must state which convention it used.
#
# ⚠️ REJECTED: THE AUX-PRESERVING PAIR.  Scaling only the motor term,
# `I_AUX_A + (thresh - I_AUX_A)/DRAG_INERTIA_RESIDUAL`, gives 0.25030 A enter /
# 0.40632 A exit.  It is the most principled-looking of the three and it is
# UNUSABLE: 0.40632 A is above this cycle's maximum source total of 0.33107 A,
# so the exit threshold is unreachable and the hysteresis has no upper arm at
# all.  The enter value would also admit ~97 % of the cycle.
#
# Scenario-scoped: the 61 s and `ftp75` legs read the module constants and are
# untouched.  Literals rather than a computed expression because deriving them
# needs numpy and a full demand build, which this module must not do at import.
FTP75C_SOCBAND_CHARGE_ENTER_A = 0.18074
FTP75C_SOCBAND_CHARGE_EXIT_A = 0.33107

_FTP75C_COMMON = {
    "electrical": "any",
    "duration_s": FTP75C_DURATION_S,
    # THE SAME LIST OBJECT for all five, as the FTP-75 family shares one: the
    # legs differ only in the strategy driving them, and a comparison between
    # them is meaningless on different stimuli.
    "ems_v_profile": FTP75C_PROFILE,
    "ems_run_exit_s": FTP75C_RUN_EXIT_S,
    "aux_preload_a": FTP75C_PRELOAD_A,
    # THE ROAD-LOAD PROFILE.  Declared as a scenario key so the operator does
    # not have to remember `--drag scaled-air`, and FINGERPRINTED
    # (DP_FINGERPRINT_META_KEYS) because it changes the tractive demand.
    "drag": DRAG_MODE_SCALED_AIR,
    # THE REGEN MANAGER.  A common layer over every strategy's command - see the
    # RegenManager block.  Windows are derived at bind time from this
    # scenario's own profile and the RESOLVED drag mode.
    "ems_regen_manager": True,
}

for _name, _ems, _what in (
    ("ems-ftp75c-5050", "hold-5050",
     "constant 50/50 split, so any share deviation belongs to the firmware's "
     "share loop and the plant and never to the EMS"),
    ("ems-ftp75c-socband", "soc-band",
     "the causal charge-sustaining policy, on charge thresholds re-derived for "
     "the compensated demand (%.4f A enter / %.4f A exit)"
     % (FTP75C_SOCBAND_CHARGE_ENTER_A, FTP75C_SOCBAND_CHARGE_EXIT_A)),
    ("ems-ftp75c-sdp", "sdp-v4",
     "the causal SDP policy, which earns the braking credit through the PLANT "
     "rather than through a re-solved artifact"),
    ("ems-ftp75c-dp", "dp-replay",
     "the NON-CAUSAL lower bound, solved with the regen credit in the demand "
     "model so the bound stops being inflated by the energy the run gets back"),
    ("ems-ftp75c-mpc", "mpc-sto",
     "the governor-aware receding-horizon controller, whose prediction model "
     "carries the same braking credit the bound does"),
):
    SCENARIOS[_name] = dict(_FTP75C_COMMON)
    SCENARIOS[_name]["ems"] = _ems
    SCENARIOS[_name]["description"] = (
        "%.0f s EPA FTP-75 study segment TIME-COMPRESSED by %r (raw t = 0..340 s "
        "inclusive; velocity axis untouched, so every acceleration doubles) on "
        "the `%s` ROAD-LOAD COMPENSATED plant, driven by the `%s` EMS strategy: "
        "%s. The first drive-cycle family on this rig that regenerates at all. "
        "Gated behind run_hil_suite.py --with-ftp75c."
        % (FTP75C_DURATION_S, FTP75C_TIME_FACTOR, DRAG_MODE_SCALED_AIR,
           _ems, _what))
del _name, _ems, _what

# The charger ceiling, declared on every leg that can command `charge_goal`.
# `ems-ftp75c-5050` is deliberately excluded on the FTP-75 family's reasoning:
# `hold-5050` never commands it, so the key would be dead declaration - EXCEPT
# that on this family the REGEN MANAGER commands `charge_goal` for it, so the
# ceiling is live here and IS declared.  All five carry one value, which is what
# the frontier's stimulus-coherence precondition asserts.
for _name in ("ems-ftp75c-5050", "ems-ftp75c-socband", "ems-ftp75c-sdp",
              "ems-ftp75c-dp", "ems-ftp75c-mpc"):
    SCENARIOS[_name]["chg_i_ceiling_a"] = (
        SCENARIOS["ems-soc-band"]["chg_i_ceiling_a"])
del _name

SCENARIOS["ems-ftp75c-socband"]["soc_band_charge_enter_itot_a"] = \
    FTP75C_SOCBAND_CHARGE_ENTER_A
SCENARIOS["ems-ftp75c-socband"]["soc_band_charge_exit_itot_a"] = \
    FTP75C_SOCBAND_CHARGE_EXIT_A
# `ems-ftp75c-dp` needs the hi-fi engine for `ems-dp-replay`'s reason exactly:
# the shipped table is solved `--charger-accounting physical`, and
# bind_scenario() refuses the mismatch.
SCENARIOS["ems-ftp75c-dp"]["electrical"] = "hifi"
# ⚠️ THE OTHER FOUR LEGS ARE HI-FI TOO, FOR A DIFFERENT REASON (review finding
# M3, 2026-09-03).  Each carries a `chopper_clamp` `total_of` aggregator in its
# `events_require`, and the plant emits `chopper_clamp` events from the HI-FI
# engine only.  Under `--electrical-pref simple` the event stream is EMPTY, an
# empty `total_of` sums to 0.0, and the 2.5 J floor then fails a correct board
# on a run that measured nothing.  Declaring `hifi` is what makes the check a
# measurement; the import guard in run_hil_suite.py refuses the `any` shape so a
# leg added later cannot re-open the hole.
for _name in ("ems-ftp75c-5050", "ems-ftp75c-socband", "ems-ftp75c-sdp",
              "ems-ftp75c-mpc"):
    SCENARIOS[_name]["electrical"] = "hifi"
del _name
# The MPC leg's two planner keys, by reference off the FTP-75 twin.
SCENARIOS["ems-ftp75c-mpc"]["mpc_max_candidates"] = MPC_CAMPAIGN_MAX_CANDIDATES
SCENARIOS["ems-ftp75c-mpc"]["mpc_loss_map"] = plant_loss_map()

# ── ems-sdp-cross / ems-sdp-braking: the SDP policy's two thresholds ────────
#
# THE ARTIFACT HAS TWO SWITCHING SURFACES ON THE SoC AXIS, one node apart, and
# they are what these two scenarios separate.  Read off the shipped
# sdp_policy_v2.json directly (101 nodes, spacing 1e-3, target node 50 =
# 0.600), at every demand bin:
#     node >= 51  (soc_rel > 0.6005)   share 0.00 -> emitted 0.15,  charge 0
#     node == 50  (0.5995 .. 0.6005)   share 1.00 -> emitted 0.85,  charge 0
#     node <= 49  (soc_rel < 0.5995)   share 1.00 -> emitted 0.85,  charge 1
#                                      in the charge-admissible bins 0-5 only
# So the SHARE threshold and the CHARGE threshold are DIFFERENT surfaces, and
# node 50 is a 1e-3-wide dead band that carries the fuel-cell share with NO
# charging.
#
# ⚠️ AN UPWARD SHARE CROSSING IS NOT REACHABLE ON THIS RIG, and the scenarios
# below are shaped by that finding rather than around it.  A share flip back to
# the battery-heavy branch needs soc_rel to rise through the WHOLE of node 50,
# and the only mechanism that raises SoC is the charger — which the table
# switches OFF the moment soc_rel enters node 50.  The most a single charge
# admission can bank is one SDP_CHG_MIN_DWELL_S latch:
#     8.0 s * chg_i_ceiling_a / (5 Ah * 3600) SoC
# which clears the 1e-3 node width only for a ceiling above 2.25 A.
#
# ⚠️ REFERENCING, stated because the two sides of that comparison are measured
# at DIFFERENT NODES and an earlier version of this block compared them
# directly.  `chg_i_ceiling_a` is a PACK-SIDE current: it is what the Ag105
# pushes into the 2S pack, and it is the current the SoC integral above
# consumes (BatterySource coulomb-counts `i_bt_src - i_charge`).
# LIMIT_I_FC_MAX 1.4 A is a BUS-SIDE current: the firmware reads the INA253 on
# the fuel-cell boost's output at ~15.95 V.
#   * IN THE SIMULATOR the two are the same number.  Plant.step() puts
#     `i_charge` amps into the pack AND (in hi-fi) draws `i_charge` amps at the
#     charger node, so the model's charger does NOT conserve power: at a ~7.4 V
#     pack against a 15.95 V bus it burns ~2.16x the energy it banks.  The
#     "I_aux 0.15 + 2.25 = 2.4 A against 1.4 A" arithmetic is that model's
#     referencing, and it is why the exclusion LOOKS enormous here.
#   * ON HARDWARE the Ag105 is a converter.  2.25 A into a 2S pack at ~8.4 V is
#     ~18.9 W, which at 15.95 V and a realistic conversion efficiency is a
#     BUS-side draw of ~1.25 A, not 2.25 A.  Against LIMIT_I_FC_MAX that is a
#     margin of order 10-15 % (~14 % at the efficiency the datasheet supports),
#     and adding the ~0.15 A aux load closes most of it.
# So the upward crossing IS still excluded on hardware — but NARROWLY, by
# roughly the width of the conversion-efficiency assumption, not by the 71 %
# the sim-side comparison suggests.  A future retune that wants the upward
# crossing therefore needs the HARDWARE-side budget re-derived first (and the
# sim's charger power model fixed, or the sim will refuse a case the board
# would accept); it is not the flatly-impossible thing this block used to
# claim.  Nothing below asserts an upward crossing, and none of the shipped
# scenarios attempts one: the share axis crosses ONCE, downward.
#
# WHAT EACH OF THE TWO DOES, and why they are not one scenario:
#   ems-sdp-cross    starts ABOVE the target (positive offset) at a LOW-DEMAND
#                    operating point.  It gets the downward SHARE crossing AND
#                    then the CHARGE threshold's own limit cycle — charge on,
#                    dwell, off, decay, on — with the share pinned at the rail
#                    after the flip.  The mechanism under test is the SoC axis.
#   ems-sdp-braking  starts BELOW the target (negative offset) and NEVER
#                    crosses back, so the share command is a constant 0.85 for
#                    the whole run BY DESIGN.  With the SoC axis held still,
#                    every charge transition in the trace is attributable to
#                    the DEMAND axis alone — which is the point: the profile's
#                    braking / low-speed windows admit charging and its cruise
#                    segments forbid it.
#
# ⚠️ HONEST CAPTION, and it applies to BOTH but especially to the braking one:
# THE SoC RISE IS FC-FED.  Not because regen is floored — WP-C (2026-09-01)
# removed that floor and braking energy now flows end to end — but because the
# charge path THESE scenarios open is FC_CHARGE_ENABLE, fed from the bus by the
# fuel cell.  The policy never opens REGEN, so no harvested joule can reach the
# pack here whatever the plant models.  What is validated is the POLICY'S CHARGE
# DECISION in the low-demand windows a deceleration produces, NOT regen capture;
# `regen-harvest-true` is the scenario that exercises capture.
#
# BOTH walks are the ems-ftp75-sdp walk's method (see there): the strategy's
# own decision path over the gen_dp_ems_table demand model of the declared
# profile, pack integrated through BatterySource, the firmware's minority
# governor applied to the delivered split, 20 Hz, 2026-08-31.  Campaign
# 20260901_024231 has since MEASURED both, and each walk block below now carries
# its measurement beside its prediction.
#
# ⚠️ AND THE METHOD HAS ONE KNOWN DEFECT, found by that campaign: "the firmware's
# minority governor applied to the delivered split" is only the right model
# ABOVE the firmware's 0.55 A open-loop drop-out.  Below it the board holds the
# last converged split and the commanded share is not acted on at all — which is
# why the `ems-sdp-cross` charge period came out 5.7x wrong while the
# demand-driven `ems-sdp-braking` schedule came out right to 4.7 %.  Any future
# walk must model the hold; see the SHARE AUTHORITY note in the MODE A block.

# ── ems-sdp-cross ───────────────────────────────────────────────────────────
# +0.0025 places the start 2.5 nodes above the target: the run opens on the
# battery-heavy branch, and the drain there is fast (the commanded 0.15 puts
# ~0.85 of the total on the battery) so the flip does not eat the run.
SDP_CROSS_SOC_REF_OFFSET = 0.0025
# The profile is TWO CRUISE LEVELS and the split is load-bearing:
#   * 2.2 m/s until SDP_CROSS_DECEL_S.  Source total ~0.67 A, so P_dem ~10.6 W
#     = bin 10 — CHARGE-FORBIDDEN, and above the 0.60 A closed-loop entry gate,
#     which matters because the governor's minority floor then keeps 0.30 A on
#     the standby channel.  That floor is what makes BOTH the pre-flip drain
#     and the post-flip node-50 traverse fast enough to fit in a bench run: at
#     the low-demand level alone the traverse takes ~145 s, and the scenario
#     would be a 5-minute run for one charge window.
#   * 1.0 m/s afterwards.  Source total ~0.34 A -> P_dem 5.37 W = bin 5, the
#     top charge-admissible bin, and `ems-soc-band`'s own validated charge
#     operating point (its measured 5.593 W).  Margin to the bin-6 edge is
#     11 %; a demand above it simply forbids charging, which the run would show
#     as a missing window rather than as a hazard.
SDP_CROSS_CRUISE_HI_MPS = 2.2
SDP_CROSS_CRUISE_LO_MPS = 1.0
SDP_CROSS_DECEL_S = 70.0          # 2.2 -> 1.0 over the next 5 s (0.24 m/s^2)
SDP_CROSS_RUN_EXIT_S = 196.0
SDP_CROSS_DURATION_S = 200.0
# ⚠️ MEASURED, campaign 20260901_024231 (the first campaign to run this
# scenario).  The walk below it is kept because ONE of its two predictions was
# right and the other one's failure is the round's standing lesson.
#     share 0.15 -> 0.85 at t = 42.292 (the only share transition of the run;
#       walk 43.85, -3.5 %)
#     charge windows: NINE over t = 70..190, period 16.13 s, gaps 8.04-8.08 s
#       (sigma 17 ms); 64103 of the window's 120000 ticks set (released
#       fraction 0.466); longest continuous hold 8.085 s = SDP_CHG_MIN_DWELL_S
#       + 1.1 %, i.e. the dwell plus one decision quantum.  Whole run: 9
#       windows, ~65.5 k ticks.
#     peak I_fc 1.1920 A at t = 79.90 (14.9 % under LIMIT_I_FC_MAX 1.4 A) —
#       equal to `ems-soc-band`'s own validated peak at the same operating
#       point.  I_charge reached its full 0.8000 A ceiling.
#     the two switching surfaces, measured for the first time: share surface at
#       SoC 0.69800 (flip at 0.69798), charge surface at 0.69700 (windows open
#       0.696980-0.697000, close 0.697300-0.697320) — both on the predicted
#       grid nodes.
#
# ⚠️ THE WALK'S CHARGE PERIOD WAS WRONG BY 5.7x, AND THE REASON IS REUSABLE.
# It predicted three windows at a ~50-57 s period; the board runs nine at
# 16.13 s.  The period is the dwell PLUS the time the node-50 decay takes to
# give back what the dwell banked (8 s * 0.8 A / 18000 = 3.6e-4 SoC), so it is
# set entirely by the DRAIN RATE at the low cruise — and the walk modelled that
# drain with the firmware's CLOSED-LOOP minority governor applied to the
# commanded 0.85.  The firmware does not run closed-loop there: the 1.0 m/s
# cruise draws I_tot ~ 0.355 A, below the 0.55 A open-loop drop-out
# (.ino:9933), so the share loop HOLDS its last converged split and the board
# DELIVERED 0.1656 against the commanded 0.85.  The pack therefore drains at
# -3.90e-5 SoC/s, not the walk's ~6.9e-6, and 3.6e-4 SoC is given back in
# 8.08 s rather than in ~45.  The arithmetic closes exactly.  This is the
# SECOND walk error from this one cause; the standing note for policy and walk
# authors is at the end of the MODE A block above.
#
# ⚠️ WALK RESULT (SUPERSEDED, 2026-08-31, kept for the record):
#     share 0.15 -> 0.85 at t = 43.85 (the only share transition of the run)
#     charge windows, sustained: 75.4-83.8, 115.3-123.7, 172.9-180.9 s
#       — three, each one SDP_CHG_MIN_DWELL_S long, period ~50-57 s.  RETIRED:
#       see the measurement and the root cause above.
#     ONE 1.05 s admit-then-drop at t = 73.3, INSIDE the deceleration: the
#       demand falls into bin 5 before the ramp finishes, the table admits, and
#       charge_hold_status()'s SDP_CHG_CRUISE_DELTA_MPS guard withdraws it on
#       the next decision because the drive has left the admitted cruise.  That
#       is the guard doing exactly its job and it is EXPECTED, not a defect —
#       it is also the only live exercise the early-drop branch has ever had.
#       Not asserted: its existence depends on where the SoC crossing lands
#       relative to the ramp, which is model-timing.
#     peak I_fc 1.1372 A at t = 83.7 (single-source FC carrying the 0.337 A
#       load plus the 0.8 A ceiling) -> 18.8 % under LIMIT_I_FC_MAX 1.4 A, i.e.
#       `ems-soc-band`'s validated 1.139 A operating point to three digits.
#     peak I_bt 0.6087 A (the accel to 2.2 m/s) -> 80 % under LIMIT_I_BT_MAX.
#     SoC 0.700000 -> 0.697195.
SCENARIOS["ems-sdp-cross"] = {
    "description": ("%.0f s two-level cruise driven by the causal `sdp-v2` "
                    "policy started %+.4f SoC ABOVE its target node: the run "
                    "opens on the table's battery-heavy branch (commanded "
                    "share 0.15), crosses the SHARE threshold downward to 0.85 "
                    "at t = 42.3 s, then settles into the CHARGE threshold's "
                    "own limit cycle — nine minimum-dwell charge windows at a "
                    "16.13 s period across the low cruise (measured, campaign "
                    "20260901_024231). The upward share crossing is not "
                    "attempted on "
                    "this rig (it would need a >2.25 A PACK-side charge "
                    "ceiling, whose bus-side draw leaves only ~10-15 %% under "
                    "LIMIT_I_FC_MAX); see the scenario comment for the "
                    "pack-vs-bus referencing."
                    % (SDP_CROSS_DURATION_S, SDP_CROSS_SOC_REF_OFFSET)),
    "electrical": "any",
    "duration_s": SDP_CROSS_DURATION_S,
    "ems": "sdp-v2",
    "sdp_soc_ref_offset": SDP_CROSS_SOC_REF_OFFSET,
    # `ems-soc-band`'s de-rated ceiling, and for its reason: the charge window
    # is the SAME single-source 1.0 m/s operating point (see the budget above).
    "chg_i_ceiling_a": SCENARIOS["ems-soc-band"]["chg_i_ceiling_a"],
    "ems_run_exit_s": SDP_CROSS_RUN_EXIT_S,
    # No `aux_preload_a`: the low cruise must stay inside charge-admissible
    # bin 5 (P_dem < 6.0 W = 0.376 A of source total), and I_AUX_A alone plus
    # the 1.0 m/s motor draw is already 0.337 A of that.  A preload here would
    # forbid the charge window the scenario exists for.
    "ems_v_profile": [
        (0.0, 0.0), (3.0, 0.0),
        (8.0, SDP_CROSS_CRUISE_HI_MPS),
        (SDP_CROSS_DECEL_S, SDP_CROSS_CRUISE_HI_MPS),
        (SDP_CROSS_DECEL_S + 5.0, SDP_CROSS_CRUISE_LO_MPS),
        (SDP_CROSS_RUN_EXIT_S, SDP_CROSS_CRUISE_LO_MPS),
        (SDP_CROSS_DURATION_S, 0.0),
    ],
}

# ── ems-sdp-braking ─────────────────────────────────────────────────────────
# -0.005 = five nodes below the target.  Sized against the walk's own net SoC
# rise: the four charge windows bank ~2.0e-3 and the cruise segments give back
# ~1.7e-3, so soc_rel ends ~3.4e-4 above where it started and stays 4.2e-3
# clear of the node-50 boundary.  A smaller offset would let a long campaign
# drift into the dead band and lose the last window; a much larger one buys
# nothing and walks toward the grid floor's clamp-tie degeneracy at 0.550.
SDP_BRAKE_SOC_REF_OFFSET = -0.005
SDP_BRAKE_CRUISE_HI_MPS = 2.2     # P_dem ~10.6 W = bin 10, charge FORBIDDEN
SDP_BRAKE_CRUISE_LO_MPS = 1.0     # P_dem  ~5.4 W = bin 5,  charge admissible
SDP_BRAKE_HI_HOLD_S = 10.0
SDP_BRAKE_DECEL_S = 3.0           # 2.2 -> 1.0, 0.40 m/s^2
SDP_BRAKE_LO_HOLD_S = 12.0        # >= SDP_CHG_MIN_DWELL_S + AG105 settle+ramp
# THE ACCELERATION OUT OF THE LOW PLATEAU IS A CURRENT-BUDGET CONSTANT, not a
# drive-cycle preference.  The charge latch is withdrawn by the cruise guard
# only at the NEXT decision, so the charger can still be open for up to one
# decision_dt_s (1 s) INTO the acceleration, and the accel current adds to the
# charger's on the single-source FC channel.  At 0.40 m/s^2 the walk's worst
# case is I_tot 0.58 + 0.8 = 1.379 A — 1.5 % under LIMIT_I_FC_MAX, i.e. an
# OC_FC coin flip.  At SDP_BRAKE_ACCEL_S = 6.0 s (0.20 m/s^2) AND the de-rated
# ceiling below the same worst case is 1.1671 A, 16.6 % under the limit.  Both
# knobs move that peak; neither alone is enough.
SDP_BRAKE_ACCEL_S = 6.0
SDP_BRAKE_CYCLES = 4
SDP_BRAKE_CHG_CEILING_A = 0.7
# Cycle = hold + decel + low hold + accel, minus the last cycle's accel.
SDP_BRAKE_RUN_EXIT_S = (8.0 + SDP_BRAKE_CYCLES * (
    SDP_BRAKE_HI_HOLD_S + SDP_BRAKE_DECEL_S + SDP_BRAKE_LO_HOLD_S
    + SDP_BRAKE_ACCEL_S) - SDP_BRAKE_ACCEL_S)          # 126.0
SDP_BRAKE_DURATION_S = SDP_BRAKE_RUN_EXIT_S + 8.0      # 134.0


def _sdp_brake_profile():
    """The braking profile, BUILT from the SDP_BRAKE_* constants.

    A literal table would let a constant and the profile drift apart, and the
    per-segment slopes are exactly what the current budget above is derived
    against."""
    prof = [(0.0, 0.0), (3.0, 0.0), (8.0, SDP_BRAKE_CRUISE_HI_MPS)]
    t = 8.0
    for i in range(SDP_BRAKE_CYCLES):
        t += SDP_BRAKE_HI_HOLD_S
        prof.append((t, SDP_BRAKE_CRUISE_HI_MPS))
        t += SDP_BRAKE_DECEL_S
        prof.append((t, SDP_BRAKE_CRUISE_LO_MPS))
        t += SDP_BRAKE_LO_HOLD_S
        prof.append((t, SDP_BRAKE_CRUISE_LO_MPS))
        if i < SDP_BRAKE_CYCLES - 1:
            t += SDP_BRAKE_ACCEL_S
            prof.append((t, SDP_BRAKE_CRUISE_HI_MPS))
    # The last low plateau ends exactly at the Run exit, so MODE_SAFE lands on
    # a flat segment and no charge window is cut mid-dwell by the handback.
    assert abs(t - SDP_BRAKE_RUN_EXIT_S) < 1e-9, (
        "the SDP_BRAKE_* constants and SDP_BRAKE_RUN_EXIT_S disagree: the "
        "profile ends at %.3f s, the Run exit is %.3f s" % (t, SDP_BRAKE_RUN_EXIT_S))
    prof.append((t + 4.0, 0.0))
    prof.append((SDP_BRAKE_DURATION_S, 0.0))
    return prof


# ⚠️ MEASURED, campaign 20260901_024231 — THE WALK BELOW WAS RIGHT, and it is
# right for a stated reason: these charge windows are DEMAND-driven, so they
# land on the profile's own fixed instants rather than on an integrated drain
# (contrast `ems-sdp-cross`, whose SoC-driven period the same walk missed by
# 5.7x).  Measured against the walk:
#     four sustained windows of four, 52.479 s of FC_CHARGE over t = 10..125
#       (walk 50.1 s, +4.7 %), longest 13.108 s; ZERO ticks inside both
#       asserted 2.2 m/s cruise windows, as walked
#     FIVE cruise-guard early drops, at t = 3.008 / 19.175 / 50.390 / 81.624 /
#       112.842 — the walk's five, to the instant.  FIRST live exercise of that
#       branch; the census is `sdpb_charge_edge_census` (9 rising edges = 4 + 5)
#     peak I_fc 1.2617 A at t = 65.51 in the one-decision overhang — 9.9 %
#       under LIMIT_I_FC_MAX 1.4 A, the tightest margin in the suite (walk
#       1.1671 A, so the real overhang costs 8.1 % more than modelled).  Now
#       asserted by `sdpb_fc_peak_bounded` at 1.32 A.
#     I_charge reached its full 0.7000 A de-rated ceiling.
#
# ⚠️ WALK RESULT (2026-08-31, CONFIRMED by the campaign above):
#     share command CONSTANT 0.8500 for the whole run (by design — see above),
#       raw table request constant 1.00
#     charge windows, sustained: 21.3-34.4, 52.2-64.8, 83.7-96.3, 114.2-126.0 s
#       — one per low plateau, four of four, ~12.5 s each, 50.1 s of charging
#       in total; ZERO charge ticks inside the four 2.2 m/s cruise holds
#     five ~1.05 s admit-then-drop blips (t = 3.05, 19.3, 50.2, 81.7, 112.1):
#       one at Run entry (standstill is bin 2, admissible, and the accel then
#       trips the cruise guard) and one per deceleration, same SDP_CHG_CRUISE_
#       DELTA_MPS mechanism as `ems-sdp-cross`'s.  Expected, harmless (each is
#       shorter than AG105_SETTLE_S, so no charge is actually delivered), and
#       not asserted.
#     peak I_fc 1.1671 A at t = 34.4 (the one-decision overhang into the
#       accel — see SDP_BRAKE_ACCEL_S) -> 16.6 % under LIMIT_I_FC_MAX
#     peak I_bt 0.3000 A (the governor's minority floor, all run) -> 90 % under
#       LIMIT_I_BT_MAX
#     SoC 0.700000 -> 0.699662, i.e. very nearly charge-sustained.
SCENARIOS["ems-sdp-braking"] = {
    "description": ("%.0f s of %d braking cycles (%.1f -> %.1f m/s and back) "
                    "driven by the causal `sdp-v2` policy started %+.4f SoC "
                    "BELOW its target node, so the share command is a constant "
                    "0.85 and every charge transition is attributable to the "
                    "DEMAND axis alone: the policy opens FC_CHARGE on each "
                    "low-speed plateau and closes it on each cruise. NOTE the "
                    "SoC rise is FUEL-CELL-FED through FC_CHARGE, not regen "
                    "harvest — this policy never opens the REGEN path."
                    % (SDP_BRAKE_DURATION_S, SDP_BRAKE_CYCLES,
                       SDP_BRAKE_CRUISE_HI_MPS, SDP_BRAKE_CRUISE_LO_MPS,
                       SDP_BRAKE_SOC_REF_OFFSET)),
    "electrical": "any",
    "duration_s": SDP_BRAKE_DURATION_S,
    "ems": "sdp-v2",
    "sdp_soc_ref_offset": SDP_BRAKE_SOC_REF_OFFSET,
    # DE-RATED below `ems-soc-band`'s 0.8 A: half of the SDP_BRAKE_ACCEL_S
    # budget (see there).  The other half is the acceleration rate.
    "chg_i_ceiling_a": SDP_BRAKE_CHG_CEILING_A,
    "ems_run_exit_s": SDP_BRAKE_RUN_EXIT_S,
    # No preload, for `ems-sdp-cross`'s reason: the low plateaus must stay
    # inside charge-admissible bin 5.
    "ems_v_profile": _sdp_brake_profile(),
}

# ═════════════════════════════════════════════════════════════════════════════
# ── ems-mpc / ems-mpc-det / ems-mpc-cross: THE MPC's LIVE SCENARIOS ─────────
#    (2026-09-02; `ems-ftp75-mpc` is registered with the FTP-75 family above)
#
# ONE RULE GOVERNS ALL FOUR, and it is the reason none of them declares a
# profile of its own: EVERY leg REUSES AN EXISTING STIMULUS OBJECT, so no new
# stimulus is validated in the same campaign as a new controller.  Design
# document section 7.2, adjudication section 2.6.
#
# ⚠️ THE BINDINGS BELOW WERE STATED BACKWARDS between the 2026-09-02 operator
# ruling and this correction, and so was the off-frontier ARGUMENT: the text
# gave `mpc-sto`'s "no stimulus here is a draw from the TPM" as the reason the
# ablation leg is not ranked, which was the PRE-swap reason and is not the
# post-swap one.  `mpc-sto` is now THE MPC and is ranked; `mpc-det` is the
# ablation, and it is off-frontier because it reads its demand off the very
# stimulus it is scored on.
#
#   ems-mpc          the `ems-soc-band` 61 s cycle and drain, driven by
#                    `mpc-sto`.  This is the FRONTIER CANDIDATE: the
#                    `cycle61-mpc` tuple ranks it against `ems-soc-band`
#                    (reference) and `ems-dp-replay` (bound), which are the
#                    SAME three objects `ems-sdp` is ranked on.
#   ems-mpc-det      the same 61 s stimulus driven by `mpc-det`.  NOT a
#                    frontier leg — see EMS_STRATEGY_META's role note: it plans
#                    against this scenario's own speed profile, so ranking it
#                    would credit the policy for foreknowledge no causal
#                    controller has.  Its value is the DIFFERENCE against
#                    `ems-mpc` on one stimulus, which is the value of preview.
#   ems-mpc-cross    the `ems-sdp-cross` two-level cruise, driven by `mpc-sto`.
#                    It reuses that scenario's `soc_ref_offset` MECHANISM: the
#                    MPC has its own `soc_ref_offset` constructor argument with
#                    the same meaning (where the run starts relative to the SoC
#                    reference the controller regulates to), so the same
#                    +0.0025 places the run on the same side of the same
#                    surface.  What the two scenarios do with that placement is
#                    NOT the same: the SDP's is a table lookup that flips, the
#                    MPC's is a terminal price that biases a plan, so the
#                    observable here is a CONTINUOUS walk of the commanded
#                    share rather than a single sharp flip.
#
# ⚠️⚠️ THE WIDE WALK ACROSS THE SWITCHING REGION IS NOT AVAILABLE FROM ANY
# REGISTERED LEG, and it was already unavailable BEFORE the 2026-09-02
# promotion.  This is recorded here because the cross stimulus was built to
# show that walk and its registry entry still says so.
#
# MEASURED (fix round, 2026-09-02).  On the cross stimulus BOTH laws command a
# share range of exactly 0.0833, over [0.2500, 0.3333], and their traces are
# bit-identical in hydrogen as well (h2 0.010942 loss-map-free, 0.010835 under
# the static-loss map).  That holds in BOTH demand eras and for BOTH
# strategies, so it is not a consequence of the promotion and not a
# consequence of the loss map.  It reproduces on the PRE-ROUND TREE at commit
# 8dc180d, where `ems-mpc-cross` still bound `mpc-det`: 0.0833 there too.
#
# Two shipped numbers were therefore ALREADY WRONG at 8dc180d, independently of
# this round:
#   * `share_range_min` 0.12 on `ems-mpc-cross` is UNSATISFIABLE — the plan's
#     own span is 0.0833 — so the check could only ever have failed a correct
#     run.  It is 0.05 now (~0.6x the measured walk).
#   * `walk_h2` 0.014134 for that leg is stale by +29 %; the true pre-round
#     walk is 0.010942.  It is 0.010835 now, re-measured under the shipped
#     bindings and the loss-map era.
#
# WHY THERE IS NO `ems-mpc-det-cross`.  The fix round proposed one, to keep the
# wide-walk observable alive under `mpc-det`.  It was BUILT, MEASURED AND
# WITHDRAWN: `mpc-det` walks the same 0.0833 on this stimulus, so the leg
# reproduced `ems-mpc-cross`'s trace bit for bit and would have spent ~200 s of
# every campaign restating a known-null comparison under a note claiming an
# observable it does not have.  The wide walk is a question about the MPC's
# candidate ladder and its terminal economics on a two-level cruise — the
# 8dc180d ladder coarsening is the first thing to look at — and it is not
# recoverable by registering a scenario.  `test_run_hil_suite.py` pins the
# 0.0833 coincidence so a ladder change that restores the wide walk is
# VISIBLE rather than silent.
#
# ⚠️ WHY NO BRAKING LEG.  `governor_model` does not license its fidelity claim
# over `ems-sdp-braking`'s post-window transients, and the MPC's plan is only as
# good as that model.  A braking stimulus is registered after the post-window
# prediction is validated, not before.  Design document section 7.2.
#
# ⚠️ ALL FOUR ARE `electrical: "any"`.  Nothing in the MPC's decision path needs
# the ideal-diode dynamics — the planner reads currents, voltages and SoC, all
# of which both engines produce — so running under either preference is a free
# cross-check, exactly as `ems-sdp` is.  Note the CONSEQUENCE the frontier check
# already enforces: the simple engine does not charge the sources for the Ag105,
# so a frontier comparison must resolve to the SAME engine on all three legs
# (`ems_frontier_stimulus_mismatches`'s `electrical_resolved` key).
#
# ⚠️ THE DRAIN.  `ems-mpc` and `ems-mpc-det` share `ems-soc-band`'s stimulus,
# which INCLUDES the SoC-band drain — so both are in SOC_BAND_DRAIN_SCENARIO_
# NAMES above and in the two offline mirrors named there.  `ems-mpc-cross` is
# NOT, for exactly the reason `ems-sdp-cross` is not: its two cruise levels are
# the stimulus, and adding a 1.0 A drain would put the low cruise above the
# charge-admissible demand bin the scenario exists to sit in.
SCENARIOS["ems-mpc"] = {
    "description": "The `ems-soc-band` drive cycle and drain load, driven by "
                   "the governor-aware `mpc-sto` receding-horizon controller: "
                   "a 20-stage, 1 Hz plan over the pack SoC whose prediction "
                   "model carries the firmware's own share governor, so it "
                   "plans DELIVERED splits rather than commanded ones. "
                   "THE DEFAULT MPC since 2026-09-02 (operator ruling): the "
                   "stochastic law is the frontier candidate of the "
                   "`cycle61-mpc` tuple and `mpc-det` is its ablation, run on "
                   "the same stimulus as `ems-mpc-det`. "
                   "⚠️ CAUSAL IN ITS DEMAND, unlike `mpc-det`: the plan is "
                   "built from the demand TPM's conditional mean rather than "
                   "from this scenario's own speed profile.",
    "electrical": "any",
    "duration_s": SCENARIOS["ems-soc-band"]["duration_s"],
    "chg_i_ceiling_a": SCENARIOS["ems-soc-band"]["chg_i_ceiling_a"],
    # THE SAME LIST OBJECT — see `ems-dp-replay`'s note.
    "ems_v_profile": SCENARIOS["ems-soc-band"]["ems_v_profile"],
    # DETERMINISTIC CANDIDATE CAP — see MPC_CAMPAIGN_MAX_CANDIDATES.
    "mpc_max_candidates": MPC_CAMPAIGN_MAX_CANDIDATES,
    # THE DEMAND-MODEL ERA THE PLANNER PREDICTS ON (2026-09-02).  It must be
    # the era the bound this leg is scored against was solved in, or the
    # frontier compares a plan built on one demand model with a bound built on
    # another.  `ems-dp-replay`'s table is a loss-map-era solve, so this is
    # the map.  Read by MpcStrategy.bind_scenario(), like `mpc_soc_ref_offset`.
    # ⚠️ RESOLVED AT IMPORT, so it does NOT follow a later monkeypatch of the
    # bleed constants: a test that rebinds `R_NODE_BLEED_BUS` and then reads
    # this key gets the value the module was imported with. That is deliberate
    # (a scenario key is a static declaration, and pinning it makes a campaign
    # reproducible), and it is also why `bind_scenario()` treats the key as an
    # INTENT and reconciles it against the run's resolved configuration rather
    # than applying it blind - see the M1 block in mpc_ems.py.
    "mpc_loss_map": plant_loss_map(),
    "ems": "mpc-sto",
}

SCENARIOS["ems-mpc-det"] = {
    "description": "The `ems-soc-band` drive cycle and drain load, driven by "
                   "the DETERMINISTIC `mpc-det` variant: the same horizon "
                   "objective with the demand TPM's conditional mean replaced "
                   "by this scenario's own speed profile, and the overcurrent "
                   "bound left at its nominal value. THE ABLATION LEG since "
                   "2026-09-02 — it measures the VALUE OF PREVIEW against "
                   "`ems-mpc`, and it is NOT a frontier leg, because its "
                   "demand is read off the stimulus it is scored on.",
    "electrical": "any",
    "duration_s": SCENARIOS["ems-soc-band"]["duration_s"],
    "chg_i_ceiling_a": SCENARIOS["ems-soc-band"]["chg_i_ceiling_a"],
    "ems_v_profile": SCENARIOS["ems-soc-band"]["ems_v_profile"],
    # DETERMINISTIC CANDIDATE CAP — see MPC_CAMPAIGN_MAX_CANDIDATES.
    "mpc_max_candidates": MPC_CAMPAIGN_MAX_CANDIDATES,
    # THE DEMAND-MODEL ERA THE PLANNER PREDICTS ON — see `ems-mpc`.
    "mpc_loss_map": plant_loss_map(),
    "ems": "mpc-det",
}

SCENARIOS["ems-mpc-cross"] = {
    "description": ("%.0f s two-level cruise — the `ems-sdp-cross` stimulus — "
                    "driven by `mpc-sto` started %+.4f SoC above the reference "
                    "it regulates to. The SDP's table flips sharply across its "
                    "switching surface; the MPC's terminal price biases a plan, "
                    "so the observable is a CONTINUOUS walk of the commanded "
                    "share across the same operating region. Phase-free checks "
                    "only: the decision clock is not locked to the stimulus. "
                    "⚠️ NARROWER SINCE THE 2026-09-02 PROMOTION, and "
                    "deliberately reported rather than hidden: on `mpc-sto` "
                    "the walk spans only 0.0833 of share against `mpc-det`'s "
                    "wider band, because the stochastic law plans against the "
                    "demand TPM's conditional mean and that mean smooths the "
                    "two cruise levels this stimulus exists to separate. The "
                    "share-motion floor was lowered from 0.12 to 0.05 for that "
                    "reason (run_hil_suite.py); if a campaign wants the WIDE "
                    "walk back, the leg to read is `ems-mpc-det`'s law, not "
                    "this scenario."
                    % (SDP_CROSS_DURATION_S, SDP_CROSS_SOC_REF_OFFSET)),
    "electrical": "any",
    "duration_s": SDP_CROSS_DURATION_S,
    "ems": "mpc-sto",
    # ⚠️ A DIFFERENT KEY FROM `ems-sdp-cross`'s `sdp_soc_ref_offset`, and
    # deliberately so: that key is read ONLY by SdpStrategy.bind_scenario()
    # (there is an import-time assert to that effect), so declaring it here
    # would be a silently-dead key. `mpc_soc_ref_offset` is read by
    # MpcStrategy.bind_scenario() off this dict, exactly as its SDP twin is —
    # it is a BINDING, applied after reset(), not a constructor argument and
    # not a command-line one. The VALUE is the SDP scenario's, by reference,
    # because the two scenarios place the run at the same point of the same
    # axis.
    "mpc_soc_ref_offset": SDP_CROSS_SOC_REF_OFFSET,
    # THE DEMAND-MODEL ERA THE PLANNER PREDICTS ON — see `ems-mpc`.
    "mpc_loss_map": plant_loss_map(),
    "chg_i_ceiling_a": SCENARIOS["ems-sdp-cross"]["chg_i_ceiling_a"],
    "ems_run_exit_s": SDP_CROSS_RUN_EXIT_S,
    # No `aux_preload_a` and NOT in the SoC-band drain list — see the block
    # above and `ems-sdp-cross`'s own note.
    # THE SAME LIST OBJECT as `ems-sdp-cross`'s profile.
    "ems_v_profile": SCENARIOS["ems-sdp-cross"]["ems_v_profile"],
    # DETERMINISTIC CANDIDATE CAP — see MPC_CAMPAIGN_MAX_CANDIDATES.
    "mpc_max_candidates": MPC_CAMPAIGN_MAX_CANDIDATES,
    # NO `mpc_budget_ms` KEY ANY MORE (removed 2026-09-02, nonlinearity round).
    # This leg carried 15.0 ms because at the 10 ms default it expired on
    # 57.4 % of its decisions once the candidate cap was lifted to 1029. The
    # ADAPTIVE budget and the ladder coarsening removed that expiry AT THE
    # DEFAULT: 0 % expiry at a 7.41 ms median solve. A scenario key that no
    # longer changes anything is worse than an absent one, because it reads as
    # a still-measured need. The KEY MECHANISM itself is unchanged and still
    # tested (`mpc_configure_kwargs()`); only this leg's declaration is gone.
}

# ── mppt-tracking: the Ag105 MPPT input-voltage threshold, closed-loop ──────
#
# THE FIRST SCENARIO IN WHICH MPPT_DISABLE DOES ANYTHING.  Everywhere else in
# this suite the pin only sets two flags in the status byte, so nothing the
# firmware does with it can be validated.  Here `mppt_emulation` turns on the
# part's real mechanism — an INPUT-VOLTAGE THRESHOLD (AG105_Silvertel.pdf p.10;
# NOT perturb-and-observe) — and the pin becomes causal.
#
# ⚠️ THE OBJECTIVE INVERTED AT fw v24 (2026-09-01).  Under fw v23 the module sat
# at its 18 V default, the ~15.95 V bus could never clear it, and the firmware
# and the module HUNTED — 138 MPPT_DISABLE toggles at a ~40 ms period, measured
# on hardware in campaign 20260831_191509.  fw v24 writes reg 0x02 to a threshold
# BELOW the bus (target = windowed-min V_chg − 3.0 V, clamped in COUNTS to
# [15, 27] = 12.320-13.376 V, .ino:1671-1690), so the module stops refusing.
# THE HUNT IS NOW THE FAILURE SIGNATURE, and the reg-0x02 count the board reports
# on observation-frame byte 15 (CSV `mppt_thresh_cnt`) is the positive evidence
# that the manager ran.  R1 is no longer a contingency: Table 7 encodes 0-250 as
# REGISTER mode and >=251 as the resistor, so a firmware write OVERRIDES any
# fitted MPPTS resistor.  The fw v23 loop is kept for regression reference in
# ems_mppt_harvest()'s docstring.
#
# WHY THE LOW-CRUISE PLATEAUS ONLY.  The threshold can only bind on the FC path
# (charger fed from the ~15.95 V bus with tracking released); the regen path
# holds MPPT_DISABLE LOW by construction, where the threshold does not apply.
# The FC path is SINGLE-SOURCE — assertFcChargeEnable() drops BT off the bus —
# so the whole load lands on FC.  Budget at the 0.4 m/s plateau against
# LIMIT_I_FC_MAX 1.4 A:
#       I_AUX_A 0.15 + motor ~0.06 + chg_i_ceiling_a 1.0  =  1.21 A   (14 % margin)
# The 2.5 m/s cruise segments would add ~0.6 A of motor draw and latch OC_FC,
# which is why the charge windows are on the LOW plateaus and the ceiling is
# de-rated to 1.0 A.  ⚠️ MODEL currents (M_EFF/K_F/F_COULOMB/B_EFF + the droop
# bus), not measurements.
SCENARIOS["mppt-tracking"] = {
    "description": ("45 s cruise/brake cycling with the Ag105's MPPT "
                    "INPUT-VOLTAGE THRESHOLD emulated at the count the BOARD "
                    "reports (fw v24 reg 0x02; 18 V default only until it "
                    "writes): charge_goal is asserted on the braking windows "
                    "(regen path, MPPT inhibited) AND on the low-cruise plateaus "
                    "(FC path, MPPT released) — where fw v24's threshold clamps "
                    "into [15, 27] = 12.320-13.376 V, under the bus, so harvest "
                    "HOLDS and the fw v23 hunt must NOT reappear."),
    # "any": the threshold gate is a comparison against the charger's input rail,
    # which both engines produce.  ⚠️ In SIMPLE mode V_chg is rigidly V_bus
    # whenever a charger path is closed (no series impedance, no charger draw
    # pulling the rail down), so the threshold sees a stiffer rail than the hi-fi
    # engine's.  Under fw v24 the threshold in force lands in the [15, 27] band
    # (12.320-13.376 V; exact count differs by engine) and BOTH engines' rails
    # sit above it, so the verdict is the same either way — but the MARGIN
    # differs (the hi-fi rail sags under charger draw and is the one to quote),
    # and do not read a margin to the threshold off a simple-mode run.
    "electrical": "any",
    "duration_s": 45.0,
    "ems": "mppt-harvest",
    "mppt_emulation": True,
    "chg_i_ceiling_a": 1.0,
    # Declared explicitly even though it equals the strategy's own constant: the
    # scenario's Run window is a property of the scenario, and `ems-y-*` set the
    # precedent that an EMS scenario states its own.
    "ems_run_exit_s": EMS_REGEN_RUN_EXIT_S,
    # THE SAME LIST OBJECT as `charge-regen`: the braking windows in
    # EMS_REGEN_BRAKE_WINDOWS and the cruise plateaus in EMS_MPPT_CRUISE_WINDOWS
    # are both read off THIS profile, and a second copy here would let one drift.
    "ems_v_profile": SCENARIOS["charge-regen"]["ems_v_profile"],
}

# ── charge-to-full: the Ag105 Fully-Charged / CV path, and the firmware's
#    deliberate NO-ACTION response to it ───────────────────────────────────────
#
# NOTHING IN THIS SUITE HAS EVER REACHED AG105_ST_FULL.  The branch exists
# (Plant.step(), `soc >= 0.995`) but the largest SoC RISE any campaign has
# produced is ~0.0009, against the 0.29 that soc0 0.70 would need.  The only way
# to reach it in a bench-length run is to START next to it, which is what the
# suite's --soc0 0.990 override does (mirroring soc-depletion's).
#
# ARITHMETIC.  0.995 - 0.990 = 0.005 of a 5 Ah pack = 0.005 * 18000 A·s = 90 A·s.
# At the 1.0 A ceiling below that is 90 s of charging, so FULL is expected at
# roughly t = 100 (charging established ~t = 9 after the timeline's charge_goal
# at t = 8 plus AG105_SETTLE_S).  MEASURED against this model (offline probe,
# 2026-08-31): FULL at t = 98.90 s, CV flag set, I_charge under 0.05 A by
# t = 100.09 s.  The 130 s duration leaves ~30 s to observe the taper and the
# firmware's response.
#
# WHY STANDSTILL, AND WHAT IT COSTS.  v_setpoint is 0.0 throughout, below
# V_SP_ZERO_THRESH (0.07 m/s), so the firmware commands 0 A and the drive loop is
# held in reset.  That is what makes the FC-path budget work — the charge path is
# single-source, so the budget is I_AUX_A 0.15 + 0 motor + 1.0 ceiling = 1.15 A
# against LIMIT_I_FC_MAX 1.4 A, an 18 % margin, sustained for 120 s.  THE COST,
# stated rather than discovered: this run exercises the DRIVE channel not at all.
#
# ⚠️ mppt_emulation IS DELIBERATELY OFF HERE, and it STAYS off under fw v24.
# The two scenarios test different things and must not be merged: `mppt-tracking`
# owns the threshold gate, this one owns the FULL/CV path.  Under fw v23 leaving
# it on would have blocked charging outright (18 V default over a 15.95 V bus)
# and the run could never have reached FULL.  Under fw v24 the clamped ~12.320 V
# threshold would no longer block it — but this scenario runs at STANDSTILL with
# the charger fed continuously, so it would spend the whole run above threshold
# and the gate would still be inert here.  Off is the honest configuration.
#
# WHAT THE FIRMWARE DOES ON FULL: deliberately NOTHING, and that is asserted
# POSITIVELY rather than assumed.  ag105IsReady() ACCEPTS FULL (.ino:10249-10255)
# so MPPT stays released; chargingControl() never reads GENSTAT at all, so
# FC_CHARGE_ENABLE stays open; FULL is not an error GENSTAT in detectFaults()
# (.ino:4952-4960); and LIMIT_V_BATT_MAX 10.0 V is not approached by an 8.4 V
# pack.  The suite's `fc_charge_still_open` check pins that no-action baseline so
# a future policy change to it is visible as a diff rather than as a surprise.
#
# OUT OF SCOPE: the CHARGER_STAT pin (6).  It is on NEITHER HIL frame — the aux
# byte carries only MPPT_DISABLE and CBAL_DISABLE (.ino:2823) — and
# chargingControl() does not read it.  Its Fully-Charged signature (50 % duty,
# 2 s period, Ag105_Table5_Status_Output.json) is therefore unobservable here.
# Carrying it would be a frame extension, i.e. future protocol work.
SCENARIOS["charge-to-full"] = {
    "description": ("130 s standstill FC-path charge from --soc0 0.990: the "
                    "first run in this suite to reach Ag105 GENSTAT 011 (Fully "
                    "Charged) with the CV flag, and to pin the firmware's "
                    "deliberate no-action response to it. No drive-channel "
                    "coverage — v_setpoint is 0 throughout."),
    "electrical": "any",
    "duration_s": 130.0,
    # De-rated for the single-source FC-path budget above; ceiling validation is
    # charge-cruise's job.
    "chg_i_ceiling_a": 1.0,
    "pi_timeline": [
        (0.5, {"mode_cmd": MODE_SAFE}),
        (3.0, {"mode_cmd": MODE_HYBRID}),
        # Standstill and the firmware's own default split.  The share loop is not
        # under test here (the source total never reaches the 0.60 A governor
        # gate at this load, so it runs open-loop feedforward — stated, not
        # discovered from a trace).
        (5.0, {"v_setpoint": 0.0, "power_share_setpoint": 0.5}),
        # Charging on intent.  chargingControl() opens FC_CHARGE on charge_goal
        # alone (never on readiness — the charger cannot become ready until it is
        # powered), so this is the whole stimulus.
        (8.0, {"charge_goal": 1.0}),
    ],
}

# ── fw26-clamp-cruise: the fw v26 source current-ceiling clamp ───────────────────
#
# THE ONLY STIMULUS THAT EXERCISES fw v26 DELIBERATELY.  The clamp bounds the
# COMMANDED fuel-cell fraction at SHARE_GOV_I_FC_CEIL_A / I_tot, and the
# minority-current clip runs first, so the largest fuel-cell current the loop
# can command is min(DROOP_R_MAX, 1 - SHARE_MINORITY_I_MIN_A/I_tot) * I_tot.
# The ceiling is therefore reachable only above
#     SHARE_GOV_I_FC_CEIL_A + SHARE_MINORITY_I_MIN_A = 1.55 A
# of TWO-SOURCE total.
#
# ⚠️ CORRECTED 2026-09-02.  This block said no registered scenario reached the
# ceiling, quoting `ems-soc-band`'s 1.462 A as the set maximum.  That figure is
# the EMS legs' maximum and it is the RAW total, not the governor's own filtered
# total after the minority clip.  Reconstructing what the governor actually
# commands (`tools/probes/probe_fw26_clamp_reachability.py`, over both campaigns
# of 2026-09-02) gives one registered scenario over the ceiling:
#
#     `ems-y-b30-v3`   filtered I_tot 2.3355 A, commanded I_fc 1.5180 A,
#                      11 ticks over the ceiling at t = 27.020..27.029 s
#                      (campaign B: 2.3343 A / 1.5173 A / 9 ticks at 27.007 s)
#
# and nothing else: the next-highest commanded fuel-cell current on the whole
# registered set is `ems-sdp`'s 1.1861 A, 5.1 % under the ceiling. The
# `ems-y-b30-v3` engagement is an 11 ms transient at one region boundary, so it
# proves the mechanism is live but cannot hold it, bound it, or release it under
# control. Without THIS scenario a campaign still cannot exercise the feature.
#
# WHY MOTOR-FREE, against the design note's sketch (deviation, stated).
# `docs/fw26_current_ceiling_governor.md` section 8.2.2 sketches "an auxiliary
# preload plus a steady drive command".  This scenario carries the preload and
# holds `v_setpoint` at 0.0 for the whole run instead, for the reason
# `share-staircase` is motor-free: the acceptance criteria bound I_fc inside a
# 0.10 A window and bound the balance residual, and a drive transient moves
# I_tot, which moves BOTH the clamp's engagement boundary and the window the
# criteria are written against.  With the motor held in reset by
# V_SP_ZERO_THRESH every amp on the bus is the scripted aux load, so the total
# is ONE constant and the clamp window is deterministic.
#
# THE LOAD.  FW26_CLAMP_CRUISE_LOAD_A + I_AUX_A puts the two-source total at 2.00 A,
# which sits in the design note's 1.8 A to 2.4 A band and 29 % clear of the
# 1.55 A threshold.  At a commanded share of 0.75 the UNCLAMPED fuel-cell demand
# is 1.50 A, above the 1.25 A ceiling by 0.25 A — twenty times the per-channel
# post-averaging idle noise implied by SHARE_I_TOT_MIN_A, so the clamp's action
# is not a noise-floor reading.
#
# TWO PHASES, and the second is the negative control.
#   PHASE A (t = 8..24, share 0.75) — THE CLAMP BINDS.  Offline walk through
#       `tools/governor_model.py` at the measured asymmetry: first engagement
#       on the FIRST tick after the setpoint step - the governor enters the
#       phase converged at r = 0.4944 from the timeline's own 0.50 pre-phase -
#       clamp duty 1.000 of the phase, delivered I_fc pinned at 1.2500 A with
#       NO overshoot (whole-phase peak 1.2500 A),
#       I_batt 0.7500 A, balance residual identically zero, applied ratio
#       0.6197, both bus switches high, no cut and no refusal.
#   PHASE B (t = 26..34, share 0.40) — THE CLAMP RELEASES, SAME RUN, SAME LOAD.
#       The unclamped demand is 0.80 A, well under the ceiling, so the flags
#       must fall on the setpoint step and I_fc must sit at 0.80 A.  This is the
#       control that separates "the governor held the fuel cell at 1.25 A" from
#       "the load happened to stop there", which the currents alone cannot.
#
# The BATTERY ceiling is NOT exercised: it would need 2.70 A on one channel,
# i.e. a total the platform's validated budget does not admit at a share this
# scenario could command.  That ceiling has never been exercised on hardware
# and is not expected to bind (design note section 8.6).
#
# ⚠️ THE CLAMP IS NOT EXPECTED TO ACT IN AN FC-CHARGE WINDOW, AND THIS SCENARIO
# OPENS NONE.  `assertFcChargeEnable()` holds BT_BUS low for the whole of such a
# window, so the fuel cell is the single source, I_fc equals I_tot and there is
# no second channel to move load onto.  Every overcurrent-class fuel-cell
# excursion measured on this board is of that kind, and `OC_FC` there is DESIGN
# INTENT — the EMS reads the latch as feedback about a charge window it should
# not have opened (see FAULT_EXPECTATIONS["charge-cruise"], operator ruling (b)
# of 2026-08-30).  fw v26 does not change that and is not meant to.
FW26_CLAMP_CRUISE_LOAD_A = 1.85

SCENARIOS["fw26-clamp-cruise"] = {
    "description": ("38 s motor-free two-source high-total run that is the "
                    "only stimulus reaching the fw v26 source current-ceiling "
                    "clamp: a 2.00 A two-source total held across a commanded "
                    "share of 0.75 (unclamped FC demand 1.50 A, clamped to the "
                    "1.25 A ceiling with the remainder forced onto the "
                    "battery) and then 0.40 in the same run, which releases "
                    "the clamp and gives a same-run negative control."),
    # "any": the clamp is firmware arithmetic on a filtered total and the split
    # is the droop network's; neither needs ideal-diode dynamics, so the
    # scenario is valid under either engine. A campaign runs it under ONE, so
    # "a free cross-check" was not a property of running it -- it would take a
    # second run, at this scenario's own 38 s, and nothing schedules one.
    "electrical": "any",
    "duration_s": 38.0,
    # Generic preload branch: ramped in over SOC_LOAD_RAMP_S from
    # AUX_PRELOAD_START_S = 4.0 s, so the plateau stands from t = 7.0 and
    # Phase A starts a full second after it.
    "aux_preload_a": FW26_CLAMP_CRUISE_LOAD_A,
    "pi_timeline": [
        (0.5, {"mode_cmd": MODE_SAFE}),
        (3.0, {"mode_cmd": MODE_HYBRID}),
        # Standstill for the whole run; 0.50 is the firmware's own default
        # split and is below the ceiling at this total (1.00 A of 2.00 A).
        (5.0, {"v_setpoint": 0.0, "power_share_setpoint": 0.50}),
        # PHASE A. 16 s, against the >= 10 s the design note asks for.
        (8.0, {"power_share_setpoint": 0.75}),
        # PHASE B, the in-run release and the negative control. 8 s.
        (26.0, {"power_share_setpoint": 0.40}),
        # Close the run out Run -> Finish -> Idle, leaving 3 s.
        (35.0, {"mode_cmd": MODE_SAFE}),
    ],
}

# ── fw26-clamp-sweep: the clamp's engagement and release, repeatedly ─────────
#
# THE SECOND HALF OF THE fw v26 VALIDATION PAIR, and the one that separates the
# two ways the clamp can release.  `fw26-clamp-cruise` holds ONE total and steps
# the share once; this leg is shaped like the firmware's own 'Y' table — velocity
# setpoint segments against a commanded share sweep — and crosses the clamp
# boundary on BOTH axes, five times up and five times down, in one run.
#
# THE TWO AXES, and why both are needed.  A clamp that released only when the
# share fell could be a share-loop artefact; one that released only when the load
# fell could be a load artefact.  The table therefore carries:
#   * regions that cross by TOTAL   — same commanded share 0.84, the two-source
#     total stepped between 1.20 A and 2.02 A by the velocity setpoint;
#   * regions that cross by SHARE   — same total, the commanded share stepped
#     between 0.84 and 0.40 or 0.20.
#
# THE LOAD.  FW26_CLAMP_SWEEP_PRELOAD_A + I_AUX_A is a 1.20 A floor; the motor
# adds 0.0844 A at 0.5 m/s, 0.6275 A at 2.5 m/s and 0.8163 A at 3.0 m/s on the
# demand model, giving region totals of 1.200 / 1.284 / 1.827 / 2.016 A.  The
# 1.55 A reachability threshold is crossed between the second and the third, and
# the clamp boundary at the commanded 0.84 share is 1.25/0.84 = 1.488 A, so the
# sub-threshold regions clear it by 0.20 A to 0.29 A and the high regions exceed
# it by 0.29 A to 0.45 A of fuel-cell demand.
#
# ⚠️ THOSE MOTOR NUMBERS ARE THE HOST DEMAND MODEL'S, not the board's.  In a HIL
# run the BOARD's drive loop sets the VESC current and therefore the total, so
# the region totals are a prediction and the margins above are what absorbs the
# difference.  The first campaign that runs this scenario re-derives them.
#
# WHY 0.84 AND NOT DROOP_R_MAX 0.85.  The commanded share round-trips through a
# float32 UDP field, and 0.85 is the band EDGE: a round-trip landing at
# 0.850000024 is OUTSIDE the band, which is the channel-cutoff signal and would
# make `updateShareSetpointCutoff()` open BT_BUS.  This scenario must never cut,
# so every commanded share sits strictly inside the band.  0.20 rather than 0.15
# at the bottom, for the same reason.
#
# ⚠️ THE CLAMP IS NOT EXPECTED TO ACT IN AN FC-CHARGE WINDOW, AND THIS SCENARIO
# OPENS NONE.  `assertFcChargeEnable()` holds BT_BUS low for the whole of such a
# window, so the fuel cell is the single source, I_fc equals I_tot and there is
# no second channel to move load onto.  Every overcurrent-class fuel-cell
# excursion measured on this board is of that kind, and `OC_FC` there is DESIGN
# INTENT — the EMS reads the latch as feedback about a charge window it should
# not have opened (see FAULT_EXPECTATIONS["charge-cruise"], operator ruling (b)
# of 2026-08-30).  fw v26 does not change that and is not meant to.
FW26_CLAMP_SWEEP_PRELOAD_A = 1.05
FW26_CLAMP_SWEEP_REGION_S = 6.0

# (t_start, v_setpoint, commanded share, expected to clamp).  The fourth field
# is DOCUMENTATION consumed by run_hil_suite.py's expectation builder, so the
# check windows and this table cannot drift apart: a region's classification is
# written once, here, beside the stimulus that produces it.
FW26_CLAMP_SWEEP_REGIONS = (
    ( 8.0, 0.0, 0.84, False),   # 1.200 A — sub-threshold, bit-identity region
    (14.0, 3.0, 0.84, True),    # 2.016 A — clamped
    (20.0, 0.5, 0.84, False),   # 1.284 A — released BY TOTAL
    (26.0, 2.5, 0.84, True),    # 1.827 A — clamped
    (32.0, 2.5, 0.40, False),   # 1.827 A — released BY SHARE, same total
    (38.0, 3.0, 0.84, True),    # 2.016 A — clamped
    (44.0, 3.0, 0.20, False),   # 2.016 A — released at the band's lower rail
    (50.0, 0.0, 0.84, False),   # 1.200 A — sub-threshold, bit-identity region
    (56.0, 3.0, 0.84, True),    # 2.016 A — clamped
    (62.0, 0.5, 0.50, False),   # 1.284 A — sub-threshold
    (68.0, 2.5, 0.84, True),    # 1.827 A — clamped
    (74.0, 0.0, 0.50, False),   # 1.200 A — sub-threshold, closes the run
)

SCENARIOS["fw26-clamp-sweep"] = {
    "description": ("84 s 'Y'-shaped sweep that crosses the fw v26 current "
                    "ceiling five times in each direction, on BOTH axes: the "
                    "two-source total is stepped 1.20 -> 2.02 A by the velocity "
                    "setpoint at a fixed commanded share, and the commanded "
                    "share is stepped 0.84 -> 0.40/0.20 at a fixed total. "
                    "Five regions clamp and SEVEN are sub-threshold; the three "
                    "STANDSTILL ones among those seven carry the model-fidelity "
                    "droop-code pin: "
                    "below the ceiling fw v26 is arithmetically identical to "
                    "fw v25, and their droop codes are pinned to the "
                    "clamp-absent walk."),
    # "any": the clamp is firmware arithmetic on a filtered total; the split is
    # the droop network's. Neither needs ideal-diode dynamics, so the scenario
    # is valid under either engine. A campaign runs it under ONE; a comparison
    # across the two would cost a second 84 s run and nothing schedules one.
    "electrical": "any",
    "duration_s": 84.0,
    "aux_preload_a": FW26_CLAMP_SWEEP_PRELOAD_A,
    "pi_timeline": (
        [(0.5, {"mode_cmd": MODE_SAFE}),
         (3.0, {"mode_cmd": MODE_HYBRID}),
         # Standstill and the firmware's own default split while the preload
         # ramps in (AUX_PRELOAD_START_S 4.0 + SOC_LOAD_RAMP_S 3.0 = 7.0 s), so
         # region 1 opens a full second after the load has settled.
         (5.0, {"v_setpoint": 0.0, "power_share_setpoint": 0.50})]
        + [(_t, {"v_setpoint": _v, "power_share_setpoint": _sp})
           for _t, _v, _sp, _c in FW26_CLAMP_SWEEP_REGIONS]
        # Close the run out Run -> Finish -> Idle, leaving 4 s.
        + [(80.0, {"v_setpoint": 0.0, "mode_cmd": MODE_SAFE})]),
}

# ── pi-silence: the firmware's Pi watchdog, isolated from the HIL link ───────
#
# A VERIFIED COVERAGE GAP, closed.  checkPiWatchdog() (.ino:4976-4985, called
# unconditionally from loop() at :4381) latches FAULT_PI_TIMEOUT after
# PI_TIMEOUT_MS = 500 in State 2/3 once a Pi has ever connected.  Its clock,
# `last_rx_ms`, is stamped ONLY by the 22-byte command branch (:5043-5044) and is
# fully independent of the injection stream's `hilLastFrameMs` (:5132).  Nothing
# in this suite could exercise it: apply_scenario()'s `tx_enabled` gates BOTH
# streams (:4172 injection, :4192 commands), and `comm-loss` kills both together
# — which trips the HIL staleness path, not the Pi watchdog.  `pi_mute_after_s`
# stops the COMMANDER alone.
#
# WHY hold-5050 AT ITS 1.2 m/s DEFAULT CRUISE: the halt must be OBSERVABLE.  At
# 1.2 m/s the model's hold current is ~3.5 A, so the fault's motor cut-off is a
# multi-amp fall in `current` rather than a change from zero to zero.  The
# scenario declares no ems_v_profile, so the strategy falls back to
# EMS_DEFAULT_CRUISE_MPS — that fallback IS the setpoint here, not an accident.
#
# ⚠️ fw v23 RECOVERY INTERPLAY (verified).  The INJECTION stream keeps running at
# full rate, so no HIL RUN BOUNDARY (HIL_RUN_BOUNDARY_MS 1000 of link silence,
# anchored at hilLastFrameMs) is ever formed and the State-99 latch persists to
# the end of the run.  `warm_resets_expected` is therefore deliberately OMITTED:
# a mid-run warm reset here would prove the stimulus was contaminated — and it
# would also DESTROY the test, because hilWarmReset() clears `pi_ever_connected`
# (:5610), which disarms the very watchdog under test.
SCENARIOS["pi-silence"] = {
    "description": ("14 s cruise at 1.2 m/s in which the emulated Pi stops "
                    "commanding at t = 8.0 while the injection stream keeps "
                    "running at full rate — the only stimulus that isolates the "
                    "firmware's Pi watchdog (PI_TIMEOUT_MS 500) from the HIL "
                    "link's own staleness clock. FAULT_PI_TIMEOUT is REQUIRED."),
    # "any": a command-stream timeout is a firmware-side timer; neither engine's
    # electrical detail participates.
    "electrical": "any",
    "duration_s": 14.0,
    "ems": "hold-5050",
    # NO ems_run_exit_s: hold-5050's own EMS_RUN_EXIT_S (55.0) is past this run's
    # end, which is exactly what is wanted — the board must still be in State 2
    # when the Pi goes quiet, or the watchdog is not armed.
    "pi_mute_after_s": 8.0,
}

# ── share-staircase: the share governor's rails, and the cut/restore latency ──
#
# TWO PHASES, AT TWO DIFFERENT LOADS, and the split is forced rather than chosen.
# The two objectives are mutually exclusive at any single load:
#   PHASE A (t = 6..28, I_tot ~ 1.2 A) — GOVERNOR CHARACTERISATION.  The closed
#       share loop needs the source total above 2*SHARE_MINORITY_I_MIN_A = 0.60 A,
#       and at 1.2 A the governor's rails sit at SHARE_MINORITY_I_MIN_A/I_tot =
#       [0.25, 0.75].  The staircase steps 0.80 -> 0.20 in 0.10 increments, so its
#       two ENDS are outside those rails and its middle is inside: the clip band
#       that campaign TP0170-0180 measured incidentally becomes a DESIGNED
#       observable, swept in both directions in one run.
#   PHASE B (t = 33..44, I_tot ~ 0.55 A) — THE CUT AND ITS RESTORE.  The setpoint
#       excursions 0.95 and 0.05 are outside [DROOP_R_MIN 0.15, DROOP_R_MAX 0.85],
#       so updateShareSetpointCutoff() (.ino:9231-9257) opens BT_BUS and then
#       FC_BUS.  The latch is REFUSED unless the DOOMED channel carries
#       <= SHARE_CUT_MAX_HANDOFF_A = 0.5 A (.ino:9234, :9250), and at Phase A's
#       1.2 A a 50/50 split is 0.60 A — over the guard, so the cut would DEFER.
#       At 0.55 A the worst case is 0.275 A, clear by 45 %.
# Hence the load DROP at t = 29: the governor cannot be characterised at a load
# where the cut fires, and the cut cannot fire at a load where the governor is
# best characterised.
#
# MOTOR-FREE BY CONSTRUCTION: v_setpoint is 0.0 for the whole run, below
# V_SP_ZERO_THRESH (0.07 m/s), so the drive loop is held in reset and every amp
# on the bus is the scripted aux load.  A drive transient would move I_tot and
# therefore move the governor rails mid-staircase, which would make every step's
# clip level a different number.
#
# ⚠️ CORRECTED PREMISE on the cut LATENCY (campaign round 3/4, CLAUDE.md
# 2026-08-31b).  The observed [0, 20) ms spread is COMMAND-ARRIVAL PHASE — the
# 50 Hz PiCommander cadence (PI_CMD_HZ) — NOT a firmware tick.  powerBalance()
# and its cutoff run at POWER_BAL_PERIOD_US = 1000 us (SHARE_CTRL_TS_US is also
# 1000 us), so the firmware contributes ~1 ms, not ~20.  Changing PI_CMD_HZ would
# move this distribution; changing a firmware tick would barely touch it.
SCENARIOS["share-staircase"] = {
    "description": ("47 s two-phase, motor-free share sweep: a 0.80 -> 0.20 "
                    "staircase at I_tot ~ 1.2 A (the governor's [0.25, 0.75] "
                    "rails become a designed observable), then a load drop to "
                    "~0.55 A and four out-of-band excursions that cut and RESTORE "
                    "BT_BUS and FC_BUS — with the cut/restore latency measured."),
    # "any": the setpoint-latched cutoff is firmware logic and the governor rails
    # are firmware arithmetic; neither needs ideal-diode dynamics.  Running it in
    # both engines is a free cross-check.  (The hi-fi engine's own reactive
    # pick-up is handoff-sag's subject, not this one's.)
    "electrical": "any",
    "duration_s": 47.0,
    "pi_timeline": [
        (0.5, {"mode_cmd": MODE_SAFE}),
        (3.0, {"mode_cmd": MODE_HYBRID}),
        # Standstill for the whole run; 0.50 is the firmware's own default split.
        (5.0, {"v_setpoint": 0.0, "power_share_setpoint": 0.50}),
        # PHASE A staircase: 0.10 every 3 s.  3 s is ~150 share-loop ticks at
        # SHARE_CTRL_TS_US 1000 us and 150 command periods at PI_CMD_HZ — long
        # enough that each step's settled value, not its transient, is what the
        # trace shows.
        (6.0, {"power_share_setpoint": 0.80}),    # above the 0.75 rail
        (9.0, {"power_share_setpoint": 0.70}),
        (12.0, {"power_share_setpoint": 0.60}),
        (15.0, {"power_share_setpoint": 0.50}),
        (18.0, {"power_share_setpoint": 0.40}),
        (21.0, {"power_share_setpoint": 0.30}),
        (24.0, {"power_share_setpoint": 0.20}),   # below the 0.25 rail
        (27.0, {"power_share_setpoint": 0.50}),   # recentre before the load drop
        # (t = 29: STAIRCASE_LOAD_A drops to STAIRCASE_LOAD_B, ramped over
        #  SOC_LOAD_RAMP_S by apply_scenario() — see the branch there.)
        # PHASE B excursions, 3 s apart so each cut and each restore is measured
        # in isolation.  33 -> BT_BUS cut (sp > DROOP_R_MAX); 36 -> restore;
        # 39 -> FC_BUS cut (sp < DROOP_R_MIN); 42 -> restore.
        (33.0, {"power_share_setpoint": 0.95}),
        (36.0, {"power_share_setpoint": 0.50}),
        (39.0, {"power_share_setpoint": 0.05}),
        (42.0, {"power_share_setpoint": 0.50}),
        # Close the run out Run -> Finish -> Idle, leaving 3 s.
        (44.0, {"mode_cmd": MODE_SAFE}),
    ],
}

# ── M4 (review 2026-08-31), CLOSED 2026-09-01 (WP-E) ────────────────────────
# `aux_preload_a` is applied by apply_scenario()'s generic fall-through branch
# and changes the bus load the DP solved against just as surely as
# `ems_v_profile` does.  It used to be absent from DP_FINGERPRINT_META_KEYS,
# and the gap was held shut by an import-time refusal of the COMBINATION
# (dp-replay scenario + declared preload) rather than by coverage.
#
# `ems-ftp75-dp` is the second DP scenario the deferral note named, and it
# declares FTP75_PRELOAD_A, so the refusal would have blocked it.  The key is
# now IN the fingerprint and both tables in tools/dp_tables/ were regenerated,
# which is the fix the note prescribed.  The assertion is deliberately NOT
# replaced by a weaker one: coverage in dp_profile_fingerprint() is strictly
# stronger than a registry-shape check, because it catches a preload RETUNE as
# well as a preload declaration.
#
# The inverse guard below (`_DP_FINGERPRINT_KEYS_COVER_DEMAND`) pins that
# every demand key a dp-replay scenario may declare IS fingerprinted, so a
# future demand key added to a DP scenario cannot silently repeat the gap.
_DP_DEMAND_META_KEYS = frozenset({"ems_v_profile", "duration_s",
                                  "chg_i_ceiling_a", "aux_preload_a",
                                  "ems_run_exit_s"})
_uncovered = ()
for _dpn, _dpm in SCENARIOS.items():
    if _dpm.get("ems") == "dp-replay":
        _uncovered = sorted((_DP_DEMAND_META_KEYS & set(_dpm))
                            - set(DP_FINGERPRINT_META_KEYS)
                            # `ems_run_exit_s` is covered by the drift guard's
                            # own `run_exit_s` header check rather than by the
                            # fingerprint, which is equally binding.
                            - {"ems_run_exit_s"})
        assert not _uncovered, (
            "SCENARIOS[%r] is a dp-replay scenario and declares the DEMAND "
            "key(s) %s, which DP_FINGERPRINT_META_KEYS does not cover — the "
            "table guard would not notice a change to them. Add them to "
            "DP_FINGERPRINT_META_KEYS and REGENERATE every table in "
            "tools/dp_tables/." % (_dpn, ", ".join(_uncovered)))
del _dpn, _dpm, _uncovered

# `sdp_soc_ref_offset` is read ONLY by SdpStrategy.bind_scenario(), so on any
# other scenario it is a stimulus that is not what the registry says it is —
# the same failure mode `_AUX_PRELOAD_BESPOKE` guards below, and with the same
# absence of any symptom at the point of use.  Refuse at import.
for _sn, _sm in SCENARIOS.items():
    # ROLE-BASED, not name-based (2026-09-01): the key is read by
    # SdpStrategy.bind_scenario(), so what matters is whether the scenario's
    # strategy IS an SdpStrategy — not which of the registered SDP artifacts it
    # plays.  A name test went stale the moment a second SDP name existed.
    assert (("sdp_soc_ref_offset" not in _sm)
            or _sm.get("ems") in SDP_STRATEGY_NAMES), (
        "SCENARIOS[%r] declares `sdp_soc_ref_offset` but its `ems` is %r. The "
        "key is read only by SdpStrategy.bind_scenario(), so it would be "
        "silently ignored — the run would start ON the policy's target node "
        "and the trace would carry no sign of the difference." % (_sn, _sm.get("ems")))
del _sn, _sm

# `mpc_soc_ref_offset` (2026-09-02) is the MPC's exact analogue, and it gets the
# same guard for the same reason: it is read only by mpc_configure_kwargs(),
# which main() calls only for an `_MpcProxy` strategy, so on any other scenario
# it is a silently-dead key and the run would start ON the reference rather than
# beside it — with nothing in the trace to say so.
MPC_STRATEGY_NAMES = frozenset(
    n for n, f in EMS_STRATEGIES.items() if isinstance(f, _MpcProxy))
for _sn, _sm in SCENARIOS.items():
    for _mk in ("mpc_soc_ref_offset", "mpc_max_candidates", "mpc_budget_ms"):
        assert ((_mk not in _sm) or _sm.get("ems") in MPC_STRATEGY_NAMES), (
            "SCENARIOS[%r] declares `%s` but its `ems` is %r. The key is read "
            "only on an MPC strategy, so it would be silently ignored."
            % (_sn, _mk, _sm.get("ems")))
    # ...and the converse, which is the one that costs a campaign: an MPC leg
    # WITHOUT the cap is wall-clock bounded, so two runs of it explore
    # different candidate sets and the leg is not even self-comparable.
    assert ((_sm.get("ems") not in MPC_STRATEGY_NAMES)
            or _sm.get("mpc_max_candidates") is not None), (
        "SCENARIOS[%r] drives an MPC strategy but declares no "
        "`mpc_max_candidates`; a campaign leg must carry the deterministic cap "
        "(see MPC_CAMPAIGN_MAX_CANDIDATES)." % (_sn,))
del _sn, _sm, _mk

# `sdp_policy_file` (2026-09-02) is read by the same binder, and carries a
# SECOND restriction the offset does not: it may not override the artifact of a
# FRONTIER-ELIGIBLE strategy.  The frontier's admission ticket is the
# calibrated-benchmark certificate, which is checked against the artifact a
# strategy PLAYS; a scenario that swapped that artifact would be scored as the
# calibrated leg while running a policy nobody calibrated, and the run's own
# summary line would still say `sdp-v4`.  Non-frontier strategies (`sdp-sweep`,
# `sdp-v2`, `sdp-v3`) may be overridden freely — that is the mechanism's point.
for _pn, _pm in SCENARIOS.items():
    if "sdp_policy_file" not in _pm:
        continue
    assert _pm.get("ems") in SDP_STRATEGY_NAMES, (
        "SCENARIOS[%r] declares `sdp_policy_file` but its `ems` is %r. The key "
        "is read only by SdpStrategy.bind_scenario(), so the named artifact "
        "would never be loaded and the run would silently play whatever the "
        "strategy computes for itself." % (_pn, _pm.get("ems")))
    assert not EMS_STRATEGY_META[_pm["ems"]]["frontier_eligible"], (
        "SCENARIOS[%r] overrides the artifact of `%s`, which is "
        "`frontier_eligible: True`. A frontier leg is scored on the strength "
        "of the CALIBRATED artifact its registry entry names; swapping that "
        "artifact per scenario would rank a policy nobody calibrated under a "
        "name that claims the calibration. Bind it to a non-frontier SDP "
        "strategy instead (`sdp-sweep` exists for exactly this)."
        % (_pn, _pm["ems"]))
del _pn, _pm

# `droop_mode` (WP-E) is read only when a HI-FI engine is constructed, so on a
# scenario that declares `electrical: "simple"` it would be silently ignored —
# a stimulus that is not what the registry says it is, with no symptom
# anywhere, which is the failure mode `_AUX_PRELOAD_BESPOKE` and the
# `sdp_soc_ref_offset` guard below both exist to close. An invalid VALUE is
# refused at run time by main(), but at import is where a typo is cheapest.
# No shipped scenario declares the key; the guard is here so the first one
# that does cannot declare it wrongly.
for _drn, _drm in SCENARIOS.items():
    if "droop_mode" in _drm:
        assert _drm["droop_mode"] in DROOP_SCALE, (
            "SCENARIOS[%r] declares droop_mode=%r, which is not one of %s"
            % (_drn, _drm["droop_mode"], list(DROOP_MODES)))
        assert _drm.get("electrical") != "simple", (
            "SCENARIOS[%r] declares `droop_mode` but is `electrical: simple`. "
            "The key is read only when a hi-fi ElectricalSim is constructed, "
            "so it would be silently ignored — the simple model has no droop "
            "chain to rescale and already uses the BENCH-measured "
            "K_DROOP_BUS_* constants." % _drn)
del _drn, _drm

SCENARIO_NAMES = list(SCENARIOS)

# `aux_preload_a` is applied ONLY by apply_scenario()'s generic fall-through
# branch, so declaring it on a scenario that has a bespoke branch of its own
# would be silently ignored — a stimulus that is not what the registry says it
# is, with no symptom anywhere. Refuse at import instead. The list is every
# scenario name apply_scenario() matches explicitly; extending that dispatch
# without extending this list is the one way to reintroduce the gap.
_AUX_PRELOAD_BESPOKE = frozenset({
    "steady", "step-load", "sag", "comm-loss", "drive", "charge-cruise",
    "charge-regen", "ems-drive-cycle", "ems-soc-band", "ems-dp-replay",
    # 2026-08-31: `ems-sdp` shares the SOC_BAND_DRAIN_* bespoke branch with the
    # two entries above (identical stimulus is the whole point), so a preload
    # declared on it would be silently ignored — it belongs in this list.
    # 2026-09-02: and so do the three `ems-sdp-alpha-*` sweep legs, folded in
    # from SOC_BAND_DRAIN_SCENARIO_NAMES rather than listed by hand.
    *SOC_BAND_DRAIN_SCENARIO_NAMES,
    "charge-fault", "soc-depletion", "handoff-sag", "bringup", "scp-inrush",
    # 2026-08-31 wave 2: `mppt-tracking` and `charge-to-full` carry the plain
    # I_AUX_A load and take the GENERIC branch, so they are NOT listed.
    # `share-staircase` needs a load that DROPS mid-run (the generic
    # `aux_preload_a` ramps in once and stays), so it has a bespoke branch and
    # must be listed here or a preload declared on it would be silently ignored.
    "share-staircase",
})
for _n, _m in SCENARIOS.items():
    assert not (_m.get("aux_preload_a") and _n in _AUX_PRELOAD_BESPOKE), (
        "SCENARIOS[%r] declares aux_preload_a, but apply_scenario() dispatches "
        "%r to a bespoke branch that never reads it — the load would be "
        "silently absent from the run. Fold the preload into that branch, or "
        "remove the bespoke branch." % (_n, _n))
del _n, _m

# `soc-depletion`: seconds over which the SOC_ENDURANCE_LOAD_A bus-side endurance
# load ramps in from t = 10.0.  3 s is ~150 share-loop ticks (SHARE_CTRL_PERIOD_US
# 20000 = 50 Hz) — slow enough that the closed share loop tracks the load rather
# than being stepped by it, and negligible against the 400 s the suite runs this
# scenario for (re-derived 2026-08-30; was 880 s).  See apply_scenario().
SOC_LOAD_RAMP_S = 3.0

# `soc-depletion`: the endurance load, in amps, ramped in from t = 10.
# BT-SIDE BUDGET (M4 — the FC budgets elsewhere in this file had this discipline
# and this scenario did not).  The pi_timeline commands power_share_setpoint = 0.0,
# which is BELOW DROOP_R_MIN 0.15, so updateShareSetpointCutoff() (.ino:9231-9243)
# does not merely bias the split — it OPENS FC_BUS_ENABLE and hands the whole bus
# to BT.  There is no SHARE_MINORITY_I_MIN_A floor keeping current on FC; FC is off.
# So BT alone carries:
#     I_AUX_A 0.15 + SOC_ENDURANCE_LOAD_A 2.2 = 2.35 A
# against LIMIT_I_BT_MAX 3.0 A -> 21.7 % margin, held for the whole ~880 s run.
# At the previous 3.0 A the figure was 3.15 A... no: 0.15 + 3.0 = 3.15 A, ABOVE the
# 3.0 A limit outright, and even discounting model error it sat at 88-105 % of the
# limit for 645 s with nobody having written the number down.  2.2 A is the largest
# value that keeps a stated double-digit margin.
# The cut itself is gated on the DOOMED channel's measured current
# (SHARE_CUT_MAX_HANDOFF_A = 0.5 A, .ino:2018): at t = 5 the total is only I_AUX_A,
# i.e. 0.075 A per channel, so the cut fires immediately and cleanly — which is why
# the load must ramp in AFTER it (t = 10), not with it.
# run_hil_suite.py's per-scenario duration override was extended in lockstep so the
# delivered charge (and therefore the depletion depth) is preserved.
SOC_ENDURANCE_LOAD_A = 2.2

# ── `ems-soc-band`: the SoC drain load ──────────────────────────────────────
# A bus-side load whose ONLY job is to move the coulomb count far enough, fast
# enough, that the soc-band policy's out-of-band branch executes inside a
# ~60 s HIL run.  Two constraints bound it, and they are tight:
#
#   UPPER — LIMIT_I_FC_MAX 1.4 A.  The drain phase cruises at 1.5 m/s, so the
#   bus total is I_AUX_A 0.15 + i_motor 0.30 + drain.  Once the SoC leaves the
#   band the policy biases the split to SOC_BAND_SHARE_NOMINAL +
#   SOC_BAND_SHARE_SPAN = 0.75, and
#   the FC channel then carries 0.75 x total.  At drain = 1.0 A:
#       total = 1.45 A  ->  FC 1.09 A  ->  22 % margin on 1.4 A.
#   (Also checked the other way: BT carries 0.36 A, above the
#   SHARE_MINORITY_I_MIN_A 0.30 A governor floor, so the minority channel is
#   controlled rather than floored.)
#
#   LOWER — the SoC must actually cross the band.  Pack-side coulomb current at
#   the nominal 0.5 split, before the bias engages:
#       BT bus-side 0.725 A x V_bus 15.8 V = 11.5 W
#       pack current = 11.5 / (ETA_BOOST 0.85 x V_batt ~7.4 V) = 1.82 A
#       dSoC/dt = 1.82 / (5 Ah x 3600) = 1.01e-4 /s
#   so SOC_BAND_HALF 0.0015 is crossed ~11.9 s into the full drain and full
#   share authority (one more half-band, 0.00075 at the post-bias ~5e-5 /s) is
#   reached ~7 s after that.  A smaller drain does not cross inside the run.
#   MEASURED (2026-08-31) in the generator's matched-model `soc-band` walk —
#   the ONE source for these timings, see the scenario entry's note: band exit
#   t = 24.30, saturation t = 34.90, peak bus total 1.462 A.  The hand estimate
#   above brackets the band exit to within ~1 s but runs early on saturation,
#   because it ignores the ramp-in and the OCV droop; use the walk's figures.
#
# Ramped in over SOC_LOAD_RAMP_S for exactly soc-depletion's reason: a stepped
# multi-amp load splits 50/50 for one tick before the droop reapportions, and
# that single sample is what latched OC_FC there.  Ramped OUT before the
# deceleration at t = 38 so the charge window that follows sees a quiet bus.
SOC_BAND_DRAIN_LOAD_A = 1.0
SOC_BAND_DRAIN_START_S = 10.0     # ramp in from here (full at +SOC_LOAD_RAMP_S)
# RAMP-OUT START, and it is load-bearing at exactly this value.  It must NOT be
# earlier: an offline walk of this scenario (2026-08-31) with the ramp-out at
# t = 35 admitted a charge window at t = 37.59 — the residual drain had fallen
# through SOC_BAND_CHARGE_ENTER_ITOT_A while the profile was still at the 1.5 m/s
# cruise, so the cruise test correctly said "cruise" and the policy opened
# FC_CHARGE at the WRONG operating point: single-source FC would then carry
# i_aux 0.15 + residual 0.17 + i_motor 0.30 + charger 0.8 = 1.42 A, OVER
# LIMIT_I_FC_MAX 1.4 A.  Starting the ramp-out at the deceleration instead keeps
# the bus loaded through the whole 1.5 m/s cruise (I_total ~1.45 A, far above the
# 0.60 A admission gate) and empties it during the deceleration, where the cruise
# test blocks charging anyway.  The window then opens in the 1.0 m/s cruise it
# was designed for, at the budgeted 0.34 A pre-charge total.
SOC_BAND_DRAIN_END_S = 38.0       # ramp out from here, off at +SOC_LOAD_RAMP_S
                                   # = t 41.0, exactly where the low cruise (and
                                   # the intended charge window) begins

# `handoff-sag`: the two VBUS loads. Derivations live in the SCENARIOS entry and at
# the apply_scenario() site; the numbers are named here so both can cite one source.
HANDOFF_PRELOAD_A = 0.40    # from t = 4.0 — puts the pre-rail total at ~0.74 A
HANDOFF_STEP_A = 1.5        # at t = 20.0 — the perturbation, against BT's 3.0 A limit

# ── `scp-inrush`: the three-phase V-MOT load ────────────────────────────────
#
# HISTORY, compressed (the full narrative is in the git log and in HIL_FINDINGS
# for campaigns 20260830_203006 and 20260831_{000518,010145,015024,021553}).
# 2026-08-30: the load moved to t = 0 so MOT_PWR would ramp INTO it during
# bring-up P3 — the RT1987 foldback/SCP branch exists only in the SOFT state, and
# the previous "+6 A at t = 8 s" stimulus arrived when the switch had been ON for
# 7.4 s, so ZERO fold events could ever fire.  A flat 5.0 A load was derived from
# the fold threshold and shipped.  2026-08-31: campaign round 2 scored zero cuts
# on a plant trace otherwise bit-identical to round 1's.  Root cause was a
# ONE-TICK RACE — the fold's cut landed one tick after switch admission
# (S = MOT_PWR close + RT_TD_ON_S) while the firmware's OC_FC teardown landed at
# S+L, L = the observation round trip = 1 or 2 ticks of sub-millisecond host/board
# phase, and the simulator applies the board's switch word BEFORE stepping the
# solver, so a tie goes to the firmware.  The check was made TWO-OUTCOME
# (events_any_of) as an interim measure so a coin flip stopped being scored as a
# board finding.  THAT INTERIM IS NOW RETIRED: the stimulus below wins the race
# outright, and run_hil_suite.py's expectation is single-outcome again.
#
# WHY THE FLAT LOAD COULD NOT WIN THE RACE (bench-measured 2026-08-31).  The
# scenario load reaches the solver through the H1 bounded Norton stamp,
#     g_mot = i_motor / max(v[N_MOT], V_MOT_LOAD_FLOOR)     (hil_electrical.py
#     :1467-1470, floor 1.0 V at :197)
# so at SOFT entry, with the motor node DARK, the "5.0 A load" is not 5.0 A: the
# node solve governs it and only the CSS ramp current c_load*rate = 1.106 A
# actually flows.  The declared load fades in over the ~1.24 ms the node needs to
# climb past the floor, which pushed fold engagement + the 250 us SCP blanking
# window out to ~1550-1600 us — one 1 kHz tick PAST the admission tick.  Raising
# the flat load does not fix this (the ramp is node-governed, not load-governed):
# the bench bisected the tick-S threshold to ~12.7 A = 1.49x RT_I_FOLD_HIGH 8.5 A,
# which can never be regulated into at any dV and is a hard short, not the
# SCP-MARGIN case this scenario is defined to be.
#
# THE DETERMINISTIC STIMULUS (bench-validated 2026-08-31, 24/24 runs across the
# swept substep counts — phase-INDEPENDENT).  Do not load the node during the
# ramp at all; load it ONCE the node is above the Norton floor, so the full
# current appears in a SINGLE substep instead of fading in:
#   Phase 1 (ramp)       i_mot_extra = 0 while V-MOT < SCP_INRUSH_ARM_V.
#   Phase 2 (fold pulse) at the first tick with V-MOT >= SCP_INRUSH_ARM_V, apply
#                        SCP_INRUSH_FOLD_LOAD_A.  The node is already above the
#                        floor, so the Norton conductance carries the whole load
#                        immediately, the fold binds on the first substep, and the
#                        250 us blanking window expires ~275-400 us into the SAME
#                        1 kHz tick — >= 600 us before any board word can arrive.
#                        The race is not won by a margin, it is not entered.
#   Phase 3 (run load)   SCP_INRUSH_RUN_LOAD_A from SCP_INRUSH_RUN_S after the
#                        pulse, i.e. after the 64 ms foldback retry has re-armed
#                        and the second soft-start has completed to ON.  This
#                        restores the OC_FC coverage the flat-load design had.
# The fold pulse is a ONE-SHOT: it is withdrawn on the next apply_scenario() call
# (the switch is already cut by then), because the retry must soft-start into a
# clean node or it would simply fold again and the scenario would become a retry
# oscillator instead of a single measured cut.
#
# NOTHING HERE MASKS OR SHAPES SENSOR TRUTH.  This is a plant-side LOAD schedule;
# the injected rails remain whatever the solver computes from it, the RX-before-
# step ordering is untouched, and no RT1987 constant moved.

# Arming threshold for the fold pulse, in volts on V-MOT.
# 20 % above V_MOT_LOAD_FLOOR (hil_electrical.py, 1.0 V) — high enough that
# the bounded Norton stamp is in its linear region and the declared load is the
# load that flows, low enough to land early in the ~19.8 ms CSS ramp while the
# switch is still deep in SOFT.  The arming test is evaluated once per 1 kHz tick
# against the PREVIOUS tick's rails, and the ramp advances 808 V/s * 1 ms =
# 0.807 V/tick, so the ACTUAL step lands at v_step in [1.2, 2.01] V.  Both ends
# of that band are carried through the SCP_INRUSH_FOLD_LOAD_A derivation below —
# the design must hold at the worst corner, not at the nominal.
SCP_INRUSH_ARM_V = 1.2

# The fold pulse, in amps on V-MOT.  DERIVED AT THE WORST ARMING CORNER.
# The RT1987 fold engages when the soft-start pass current exceeds
#     rt1987_fold_limit(dv) = max(2.5, 8.5 - 0.2909*(dv - 5))   for dv > 5 V
# with dv = v_in - v_out.  At the pulse the pass current is c_load*rate + I where
# c_load*rate = 1.106 A (see the flat-load arithmetic below), so folding needs
#     8.5 - 0.2909*(v_in - v_step - 5) < 1.106 + I
#  -> v_in > v_step + 5 + (8.5 - 1.106 - I)/0.2909.
# At I = 6.5 A and the WORST corner v_step = 2.01 V that is v_in > 10.08 V,
# against the bring-up P3 gate's guaranteed V_BUS_CHARGED_THRESH 13.5 V
# (.ino:1452) — a 3.4 V margin, and the measured bus at P3 is ~15.8 V.
# At the OLD 5.0 A the same requirement is v_in > 15.23 V, which the P3 gate does
# NOT guarantee: that is WHY the value moves, not a re-margin for its own sake.
# 6.5 A is 76 % of RT_I_FOLD_HIGH 8.5 A — an overload the switch could still
# regulate into at a small enough dV, i.e. a legitimate SCP-margin case and not a
# hard short (the >= 8.5 A region is unregulatable at ANY dV).
SCP_INRUSH_FOLD_LOAD_A = 6.5

# The post-retry run load, in amps on V-MOT.  This is the OLD flat-load value,
# kept deliberately: it is the number whose OC coverage this scenario has always
# carried.  Split by the droop it drives I_fc/I_bt to 2.07-2.25 A each on the
# first loaded sample (headless bench 2026-08-31, substep counts 8-100), so
# LIMIT_I_FC_MAX 1.4 A is exceeded by 48-61 % and OC_FC latches deterministically
# on that sample.  (LIMIT_I_FC_MAX + LIMIT_I_BT_MAX = 4.4 A, so 5.0 A cannot be
# carried at any share split — the OC is a property of the load, not of the split.)
SCP_INRUSH_RUN_LOAD_A = 5.0

# Delay from the fold pulse to the run load, in seconds.
#   RT_SCP_RETRY_S            64 ms   foldback re-arm after the cut
# + RT_TD_ON_S                 8 ms   re-admission
# + the second soft-start     ~19 ms  (the node is still pre-charged to ~v_step,
#                                      so the ramp completes inside the 19.8 ms
#                                      t_ON rather than taking all of it)
# = ON at D+91 ms MEASURED (headless bench 2026-08-31: cut at t = 0.102, ON at
# t = 0.193, identical for substep counts 8-100).  0.110 s leaves ~19 ms of
# margin so the run load lands on a switch that is fully ON, not on one still in
# SOFT — a second fold would break the count == 1 pin in run_hil_suite.py.
# NOTE (review L2): the delay is anchored at scp_fired_t, the WITHDRAWAL tick —
# one 1 kHz tick after the pulse the derivation above measures from.  1 ms
# against the ~19 ms margin; absorbed, stated here so nobody re-derives it.
SCP_INRUSH_RUN_S = 0.110

# ── Flat-load arithmetic, KEPT: the ramp-current term above is taken from it ──
# The RT1987 foldback in hil_electrical.py only engages when the soft-start pass
# current exceeds rt1987_fold_limit(dV):
#     rt1987_fold_limit(dv) = max(2.5, 8.5 - 0.2909*(dv - 5))  for dv > 5 V
#   -> at dv = 16 V (MOT_PWR closing onto a node held down by its own load) the
#      limit is its MINIMUM over the reachable dV range: 5.30 A.
#      (RT_I_FOLD_LOW = 2.5 A is unreachable: it would need dv > 25.6 V.)
# The soft-start pass current is  i_phys = c_load*rate + i_load  with
#     t_ON  = (16/35)*(100/0.0023 - 100) us = 19.8 ms   (CSS_NF["MOT_PWR"] 100 nF)
#     rate  = 16 V / 19.8 ms                = 808 V/s
#     c_load = C_MOT_LOCAL 470 uF + c_vesc 900 uF = 1.37 mF
#     c_load*rate                           = 1.11 A
#   -> a FLAT load would have to exceed 5.30 - 1.11 = 4.19 A to fold at all.
# The 1.11 A ramp term is the piece the phase-2 derivation above reuses; the
# 4.19 A flat threshold itself is now historical (the pulse does not ramp into
# a dark node, so it is not the binding condition).
#
# TWO CONSEQUENCES THAT SURVIVE THE REDESIGN, both still true:
#   * An scp_cut and an OC fault are INSEPARABLE in this model.  Any load able to
#     fold is above what the board's own limits allow on the bus
#     (LIMIT_I_FC_MAX 1.4 + LIMIT_I_BT_MAX 3.0 = 4.4 A), so "fold without
#     faulting" is not a reachable operating point.  The phase-3 run load makes
#     that OC explicit and deterministic rather than incidental.
#   * "Fold without cutting" is not reachable either: once the clamp engages,
#     v_out falls behind the ramp target at ~224 V/s while the fold limit rises
#     only ~0.29 A/V, so i_lag grows ~2.7 A within the 250 us SCP blanking
#     window — every fold reaches RT_SCP_BLANK_S and CUTS.
#
# ⚠️ PROVISIONAL i_cut BAND.  The flat-load campaigns measured i_cut 6.2852 A
# (20260830_203006) and 6.290013 A (round 1, 20260831_000518, hardware-
# corroborated 6.290 A), but those are the OLD stimulus and do not carry over.
# The feasibility bench for THIS design reproduced i_cut 5.79-5.88 A on its own
# rig and 5.62-6.61 A analytically across the corners, and could NOT reproduce
# the live 6.285-6.290 A figures under the old stimulus either — an unresolved
# emulation offset between the bench harness and the shipped path (documented
# 2026-08-31).  run_hil_suite.py's band is therefore deliberately wide and must
# be RE-DERIVED from the first live campaign under this stimulus, then tightened.


# ── Generic per-scenario auxiliary preload (2026-08-31) ─────────────────────
# Three scenarios grew their own bespoke bus load — HANDOFF_PRELOAD_A,
# SOC_BAND_DRAIN_LOAD_A, SOC_ENDURANCE_LOAD_A — each with its own hardcoded
# branch in apply_scenario().  A fourth kind of scenario (the `ems-y-*` and
# `ems-ftp75-*` EMS runs) needs the same thing for a stated reason: the
# firmware's share loop only CLOSES above 2*SHARE_MINORITY_I_MIN_A = 0.60 A of
# source total, and an EMS cycle at this rig's motor currents sits below that
# for much of its length, so a share-tracking objective without a preload
# measures feedforward.
#
# Rather than a fifth hardcoded branch, a scenario may declare `aux_preload_a`
# and get the same treatment generically.
#
# RAMPED, NOT STEPPED, and that is the soc-depletion lesson rather than a
# preference: a stepped multi-amp bus load splits 50/50 for the one tick before
# the droop reapportions it, and a single sample at that split is enough to
# latch OC_FC (campaign 20260830_214819 — 1.4705 A on FC, 5 mA over
# LIMIT_I_FC_MAX, killing a run 645 s before its objective).  The ramp reuses
# SOC_LOAD_RAMP_S, and starts at AUX_PRELOAD_START_S for handoff-sag's reason:
# bring-up P0 pre-charges the bus through the source switches' body-diode path,
# and extra load inside that window risks failing the P0 voltage gate for
# reasons that have nothing to do with the scenario under test.
AUX_PRELOAD_START_S = 4.0


# ── `share-staircase`: the two-phase bus load ───────────────────────────────
# BESPOKE rather than `aux_preload_a`, for one reason: the generic key ramps a
# load IN once and holds it, and this scenario needs the load to come DOWN
# mid-run.  The two phases' loads and the reason they cannot be one load are
# derived in full at SCENARIOS["share-staircase"].
#
# PHASE A, 1.05 A on top of I_AUX_A 0.15 -> I_tot ~ 1.20 A.  Chosen so the
# governor's rails, SHARE_MINORITY_I_MIN_A / I_tot = 0.30/1.20, land on the round
# numbers 0.25 and 0.75 — the staircase's 0.10 steps then straddle them cleanly
# instead of clipping halfway through a step.  It is also 2.0x the closed-loop
# entry gate (2*SHARE_MINORITY_I_MIN_A = 0.60 A), so the loop cannot drop back to
# open-loop feedforward on a transient.  Per-channel worst case at the 0.80
# command is the 0.75 rail: 0.90 A vs LIMIT_I_FC_MAX 1.4 A, 36 % margin.
STAIRCASE_LOAD_A = 1.05
# PHASE B, 0.40 A -> I_tot ~ 0.55 A.  Two constraints, and only a narrow band
# satisfies both:
#   * BELOW the cut's SHARE_CUT_MAX_HANDOFF_A 0.5 A per-channel guard even at a
#     50/50 split (0.275 A, 45 % clear), or the latch is REFUSED and the scenario
#     measures a deferral instead of a cut;
#   * ABOVE the closed-loop EXIT hysteresis (SHARE_GOV_OL_HYST_A -> 0.55 A of
#     filtered total) only MARGINALLY — 0.55 A sits ON it, so Phase B is expected
#     to run at or just under the open-loop boundary.  THAT IS ACCEPTED AND
#     STATED: Phase B's objective is the SETPOINT-latched cutoff, which is
#     evaluated from the commanded setpoint (.ino:9231) and does not require the
#     closed loop at all.  Do not read share-TRACKING numbers off Phase B; Phase A
#     is where the loop is unambiguously closed.
STAIRCASE_LOAD_B = 0.40
# The load transition.  Placed at t = 29, between the staircase's recentre at
# t = 27 and the first excursion at t = 33, and RAMPED over SOC_LOAD_RAMP_S for
# soc-depletion's reason: a stepped multi-amp change splits 50/50 for the one
# tick before the droop reapportions it.  Ramping DOWN is the benign direction,
# but the ramp costs nothing and keeps the two directions symmetric.
STAIRCASE_DROP_S = 29.0


def scenario_aux_preload_a(scenario, t):
    """The scenario's declared `aux_preload_a`, ramped in, at time t [A].

    0.0 for a scenario that declares none — which is EVERY scenario that
    predates this key, so the existing hardcoded branches in apply_scenario()
    are untouched and their traces are byte-identical.

    Read by apply_scenario() and, so the offline DP solves against the same
    demand the run will see, by gen_dp_ems_table.scenario_drain_a()."""
    preload = (SCENARIOS.get(scenario) or {}).get("aux_preload_a")
    if not preload:
        return 0.0
    ramp = (t - AUX_PRELOAD_START_S) / SOC_LOAD_RAMP_S
    return float(preload) * max(0.0, min(1.0, ramp))


def apply_scenario(plant, scenario, t):
    """
    Mutate the plant for the active scenario at time t and return this tick's
    transmit-enable flag.

    The gate is recomputed statelessly from `t` on every call (only "comm-loss"
    ever clears it), so it is a RETURN value, not an in/out parameter — the old
    `tx_enabled` argument was always passed True and immediately overwritten,
    which read as if the flag were latched across ticks. It is not.
    """
    tx_enabled = True
    if scenario == "steady":
        plant.i_aux = I_AUX_A
    elif scenario == "step-load":
        # Aux load step at t = 5 s: a bus-current disturbance the share loop must reject.
        plant.i_aux = I_AUX_A + (1.2 if t >= 5.0 else 0.0)
    elif scenario == "sag":
        # Bus disturbance dip at t = 5 s, 1 s long, deep enough to cross
        # LIMIT_V_BUS_MIN (12.0 V) and exercise the real UV fault path.
        plant.v_bus_offset = -5.0 if 5.0 <= t < 6.0 else 0.0
    elif scenario == "v-bus-sense-offset":
        # TWO excursions, both -5.0 V (the same depth `sag` uses: ~15.9 - 5.0 =
        # ~10.9 V measured, 1.1 V clear of LIMIT_V_BUS_MIN 12.0, so the
        # crossing is unambiguous and no tick sits on the boundary).
        #   #1  t = [5.000, 5.008)  =   8 ms  -> dwell reaches ~8 ms, 60 % under
        #                                       UV_BUS_DWELL_LATCH_MS 20. NO latch.
        #                                       (12 ms until 2026-09-01; shortened
        #                                       for host-stall margin — see the
        #                                       V_BUS_UV_PROBE_1 note.)
        #   #2  t = [8.000, 8.060)  =  60 ms  -> dwell crosses 20 ms at ~8.020
        #                                       and the board latches FAULT_UV_BUS.
        # The 3 s gap lets the leak drain excursion 1 completely (see the
        # SCENARIOS comment). Excursion 2 is held 3x longer than the threshold
        # so the latch instant is decided by the FILTER, not by the excursion
        # ending underneath it.
        if V_BUS_UV_PROBE_1[0] <= t < V_BUS_UV_PROBE_1[1]:
            plant.v_bus_offset = V_BUS_UV_PROBE_DEPTH_V
        elif V_BUS_UV_PROBE_2[0] <= t < V_BUS_UV_PROBE_2[1]:
            plant.v_bus_offset = V_BUS_UV_PROBE_DEPTH_V
        else:
            plant.v_bus_offset = 0.0
    elif scenario == "comm-loss":
        # Stop transmitting for 2 s at t = 5 s: exercises the firmware's two-stage
        # hold-then-zero (HIL_STALE_MS 50, HIL_ZERO_MS 250) AND, on fw v23+, the
        # RUN BOUNDARY that gates the HIL warm-recovery.
        #
        # WHY 2 s AND NOT 1 s: fw v23 anchors the boundary at the LAST ACCEPTED
        # FRAME and requires the link to be continuously dead for
        # HIL_RUN_BOUNDARY_MS = 1000 ms.  The old 1.0 s gap therefore cleared the
        # bound by at most one tick — a single late frame, one scheduling
        # overrun, or the board's own millis() granularity decided whether the
        # board recovered, so the same scenario passed or failed at random.  2 s
        # gives a 1000 ms margin on a 1000 ms requirement, and the 12 s duration
        # (trimmed from 30 s, 2026-08-30) leaves 5 s after the gap — the recovery
        # completes at ~7.6 s, so ~4.4 s of it is observed.
        tx_enabled = not (5.0 <= t < 7.0)
    elif scenario == "drive":
        # Plant only.  The operator drives the firmware by hand ('V', 'D', 'Y' ...)
        # over USB serial; this scenario just keeps the plant honest underneath.
        plant.i_aux = I_AUX_A
    elif scenario in ("charge-cruise", "charge-regen"):
        # Nothing to perturb: the stimulus is the pi-command timeline (mode -> Run,
        # a cruise setpoint, charge_goal > 0).  The plant just carries the load.
        plant.i_aux = I_AUX_A
    elif scenario == "ems-drive-cycle":
        # Plant carries the ordinary aux load; the whole stimulus is the EMS
        # layer's 50 Hz command stream (see EMS_STRATEGIES / ems_v_profile).
        plant.i_aux = I_AUX_A
    elif scenario in SOC_BAND_DRAIN_SCENARIO_NAMES:
        # ALL THREE names, deliberately: `ems-dp-replay` is the same cycle and
        # the same drain driven by the offline-optimal table instead of the
        # causal policy, and `ems-sdp` (2026-08-31) is the same again driven by
        # the causal state-indexed SDP policy.  The three-way comparison is only
        # meaningful if the load is bit-identical.  The three
        # `ems-sdp-alpha-*` sweep legs joined the set 2026-09-02 for the same
        # reason: they ARE the `ems-sdp` stimulus, driven by a different
        # artifact.  See the
        # SCENARIOS["ems-dp-replay"] and SCENARIOS["ems-sdp"] notes.
        # The stimulus is TWO things: the EMS layer's 50 Hz command stream (the
        # `soc-band` strategy) and this drain load, whose only job is to move the
        # coulomb count out of the policy's band inside a ~60 s run.  Ramped in
        # and out over SOC_LOAD_RAMP_S (soc-depletion's lesson: a stepped
        # multi-amp load splits 50/50 for one tick before the droop reapportions,
        # and that single sample is enough to latch OC).  Full budget and the
        # SoC-rate arithmetic are at SOC_BAND_DRAIN_LOAD_A.
        ramp_in = max(0.0, min(1.0, (t - SOC_BAND_DRAIN_START_S) / SOC_LOAD_RAMP_S))
        ramp_out = max(0.0, min(1.0, (t - SOC_BAND_DRAIN_END_S) / SOC_LOAD_RAMP_S))
        plant.i_aux = I_AUX_A + SOC_BAND_DRAIN_LOAD_A * (ramp_in - ramp_out)
    elif scenario == "charge-fault":
        # Charging is established by the timeline; at t = 20 s the charger's INPUT
        # rail collapses (a connector, the FC path browning out).  The Ag105 goes
        # dark -> GENSTAT "Battery Disconnect", ag105IsReady() drops, and the
        # firmware's charger-loss handling is what is under test.
        plant.chg_fault = t >= 20.0
    elif scenario == "soc-depletion":
        # A heavy sustained bus load so the coulomb count actually moves.  NOTE: at
        # 5 Ah a 3 A draw is a ~100 min run — use --soc0 (e.g. 0.15) and/or
        # --capacity-ah to bring it inside a bench session.  The model is honest
        # rather than accelerated on purpose: an artificially fast SOC ramp would
        # also fake the RC-pair and Rs(SOC) dynamics the UV path sees.
        #
        # STAGGERED + RAMPED (2026-08-30, HIL_FINDINGS "soc-depletion"): the step
        # used to land on t = 5.0, the same tick as the pi_timeline's
        # power_share_setpoint = 0.0 rail.  For one tick the ~3.15 A draw split
        # 50/50 and put 1.4705 A on FC — 5 mA over LIMIT_I_FC_MAX — latching OC_FC
        # and killing the run 645 s before its objective.  Now the share rail gets
        # 5 s to settle (so the droop has already put the load on BT, with only
        # SHARE_MINORITY_I_MIN_A = 0.30 A left on FC), and the load itself ramps in
        # over SOC_LOAD_RAMP_S instead of stepping, so no single tick can hand a
        # transient split a full 3 A.
        plant.i_aux = I_AUX_A + SOC_ENDURANCE_LOAD_A * max(
            0.0, min(1.0, (t - 10.0) / SOC_LOAD_RAMP_S))
    elif scenario == "handoff-sag":
        # The share rail is commanded by the timeline; the perturbation is a load
        # step at t = 20 s, large enough that the FC channel alone cannot hold the
        # bus.  Whether the standby BT diode picks up cleanly or only after a
        # measurable unsourced gap is the whole observation (hi-fi only — the simple
        # droop node has no ideal-diode dynamics and cannot show it).
        #
        # TWO loads, both on VBUS (see the SCENARIOS entry for the full derivation):
        #   HANDOFF_PRELOAD_A from t = 4.0 — raises the pre-rail total into the
        #     (0.60, 1.00) A window: above the closed-loop governor gate
        #     (2*SHARE_MINORITY_I_MIN_A) so the share loop is genuinely closed, and
        #     below the cut's own SHARE_CUT_MAX_HANDOFF_A 0.5 A per-channel guard so
        #     the latch is not REFUSED.  Applied at t = 4.0, not t = 0: bring-up P0
        #     pre-charges the bus through the source switches' body-diode path, and
        #     an extra 0.4 A of load in that window risks failing the P0 voltage
        #     gate for reasons that have nothing to do with this test.
        #   HANDOFF_STEP_A at t = 20.0 — the perturbation.  1.5 A against the
        #     SURVIVING BT channel: 0.74 + 1.5 = 2.24 A vs LIMIT_I_BT_MAX 3.0 A,
        #     25 % margin.  (At the FC rail this same step latched OC_FC at +2.2 ms;
        #     the direction flip is what buys the headroom back — see the entry.)
        plant.i_aux = (I_AUX_A
                       + (HANDOFF_PRELOAD_A if t >= 4.0 else 0.0)
                       + (HANDOFF_STEP_A if t >= 20.0 else 0.0))
    elif scenario == "share-staircase":
        # TWO-PHASE bus load: STAIRCASE_LOAD_A ramped in from AUX_PRELOAD_START_S,
        # then DROPPED to STAIRCASE_LOAD_B from STAIRCASE_DROP_S.  Both edges ramp
        # over SOC_LOAD_RAMP_S.  The full derivation — including why one load
        # cannot serve both objectives — is at the two constants and at
        # SCENARIOS["share-staircase"].
        #
        # BESPOKE rather than `aux_preload_a` because that key ramps a load in
        # ONCE and holds it; there is no generic way to express a drop, and
        # inventing one for a single scenario would be a second mechanism to keep
        # correct.  `share-staircase` is therefore listed in
        # _AUX_PRELOAD_BESPOKE, so declaring `aux_preload_a` on it is refused at
        # import rather than silently ignored.
        ramp_in = max(0.0, min(1.0, (t - AUX_PRELOAD_START_S) / SOC_LOAD_RAMP_S))
        ramp_dn = max(0.0, min(1.0, (t - STAIRCASE_DROP_S) / SOC_LOAD_RAMP_S))
        plant.i_aux = I_AUX_A + (STAIRCASE_LOAD_A * ramp_in
                                 - (STAIRCASE_LOAD_A - STAIRCASE_LOAD_B) * ramp_dn)
    elif scenario == "bringup":
        # Plant only, from dark.  The operator runs the staged bring-up ('G') and
        # watches P0-P3 against the RT1987 delays.
        plant.i_aux = I_AUX_A
    elif scenario == "scp-inrush":
        # A legitimate SCP-MARGIN case, not the Death-5 stimulus.  Death-5 was a
        # full-bus hot-plug onto a discharged node; that exact case is no longer
        # reproducible, because MOT_PWR carries a 100 nF CSS (~19.8 ms ramp) and the
        # firmware pre-charges the node during bring-up (CLAUDE.md §2, Death 5).
        # What CAN still bind the foldback is MOT_PWR ramping into the TOP of the
        # VESC input envelope (0.9 mF + the 470 uF local bulk) while the node is
        # already drawing: the ramp current is C*dV/dt on ~1.37 mF, and the load —
        # which must sit BEHIND the switch, on V-MOT, not on VBUS — adds directly
        # to it.  The event log's scp_cut / sw_ring entries are the observable; an
        # sw_ring with over_absmax True is the boost-death signature.
        #
        # THREE-PHASE LOAD (2026-08-31 deterministic redesign; the full derivation
        # and the history it replaces are at SCP_INRUSH_ARM_V / _FOLD_LOAD_A above).
        # `i_mot_extra` is applied by Plant.step() ONLY while MOT_PWR is closed, so
        # every phase below is inert until the bring-up P3 close.
        #
        # V-MOT is read from plant.v_rgn: the RGN-V divider sits ON the motor node,
        # upstream of D-BC-RG (schematic sheet 4, 2026-08-30 topology fix), so v_rgn
        # IS N_MOT in both electrical modes.  It carries the PREVIOUS tick's solve —
        # apply_scenario() runs immediately before plant.step() in main() — which is
        # exactly the intent: the arming test is a 1 kHz observation of the ramp, and
        # the 0.807 V/tick advance is carried through the SCP_INRUSH_FOLD_LOAD_A
        # derivation as the [1.2, 2.01] V arming corner.
        if plant.scp_armed and not plant.scp_fired:
            # ONE-SHOT withdrawal, the tick after the pulse: the switch has already
            # cut, and the 64 ms foldback retry must soft-start into a CLEAN node or
            # the scenario degenerates into a retry oscillator instead of the single
            # measured cut that run_hil_suite.py pins at count == 1.
            plant.scp_fired = True
            plant.scp_fired_t = t
            plant.i_mot_extra = 0.0
        elif plant.scp_fired:
            # Phase 3: the run load, once the retry has completed to ON.  Restores
            # the OC_FC coverage the flat-load design carried.
            plant.i_mot_extra = (SCP_INRUSH_RUN_LOAD_A
                                 if (t - plant.scp_fired_t) >= SCP_INRUSH_RUN_S
                                 else 0.0)
        elif plant.v_rgn >= SCP_INRUSH_ARM_V:
            # Phase 2: the fold pulse.  The node is above the H1 Norton floor, so
            # the full current appears in ONE substep, the fold binds immediately,
            # and the 250 us blanking window expires ~275-400 us into THIS 1 kHz
            # tick — before any board word can arrive.  The one-tick race that made
            # this scenario's verdict a coin flip is not won here, it is not entered.
            plant.i_mot_extra = SCP_INRUSH_FOLD_LOAD_A
            plant.scp_armed = True
        else:
            # Phase 1: ramp.  The node must climb UNLOADED — a load declared here
            # fades in through the bounded Norton stamp and pushes the fold past the
            # admission tick, which is precisely the defect being fixed.
            plant.i_mot_extra = 0.0
    else:
        # GENERIC branch, reached only by a scenario with no bespoke behaviour
        # of its own — today the `ems-y-*` and `ems-ftp75-*` EMS scenarios.
        # Every scenario named above takes an earlier branch, so adding this
        # changed none of their traces.  A scenario that declares no
        # `aux_preload_a` gets exactly I_AUX_A, which is what the fall-through
        # left behind before this branch existed.
        plant.i_aux = I_AUX_A + scenario_aux_preload_a(scenario, t)
    return tx_enabled


def _make_console_lossless(streams=None):
    """Make stdout/stderr never raise UnicodeEncodeError.  Returns the names
    reconfigured (for tests).

    THE DEFECT THIS CLOSES (campaign 20260902_011926, fix-queue item 1): the
    Windows console encoding is cp1252, and a single un-encodable glyph in a
    banner or a summary line raised UnicodeEncodeError out of `print()`.  Two
    whole failure classes followed from it — two EMS legs never launched (the
    bind-time warning below raised inside a binder whose `except ValueError`
    turned it into an argparse error, because UnicodeEncodeError IS a
    ValueError), and three MPC legs completed 61 000 ticks and then died
    printing their summary BEFORE the sidecar was finalized, losing the
    provenance of a complete run.

    `errors="backslashreplace"` is chosen over `"replace"` so the escape names
    the codepoint that could not be printed instead of hiding it behind '?'.
    The offending TEXT is fixed at the source too (ASCII labels); this is the
    belt-and-braces layer, because the next un-encodable glyph will be added by
    someone who never saw this campaign.

    Guarded: a stream may not be reconfigurable at all (a pipe replaced by a
    test's StringIO, a stream detached by a harness), and a console fix must
    never itself be the thing that kills the run."""
    done = []
    for name in ("stdout", "stderr") if streams is None else streams:
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="backslashreplace")
            done.append(name)
        except (ValueError, OSError, AttributeError, TypeError):
            # Not reconfigurable (detached, or a non-TextIOWrapper stand-in).
            continue
    return done


def main(argv=None):
    # cp1252 (2026-09-02): FIRST statement in main(), before any banner can be
    # printed. See _make_console_lossless().
    _make_console_lossless()
    # LOW-5 (fw v24 tooling-lockstep review): defence in depth for same-process
    # reuse (e.g. a test harness calling main() more than once) -- without this
    # a second run would inherit _OBS_LENGTHS_SEEN from the first and could
    # silently skip the observation-frame-length announcement (and, if the two
    # runs' boards disagree, the both-lengths-seen warning below).
    reset_output_provenance()
    ap = argparse.ArgumentParser(description="HIL plant simulator for the Teensy balancer board")
    ap.add_argument("--teensy-ip", default="192.168.1.50", help="board IP (default 192.168.1.50)")
    ap.add_argument("--port", type=int, default=TEENSY_PORT_DEFAULT,
                    help=f"board UDP port (default {TEENSY_PORT_DEFAULT})")
    ap.add_argument("--bind-port", type=int, default=0,
                    help="local UDP port to bind (0 = ephemeral; the board learns it from us)")
    ap.add_argument("--scenario", default=None, choices=SCENARIO_NAMES,
                    help="simulated-plant scenario (default steady; not with --replay). "
                         "Use --list-scenarios for descriptions.")
    ap.add_argument("--list-scenarios", action="store_true",
                    help="print the scenario registry and exit")
    ap.add_argument("--ems", default=None, choices=EMS_NAMES,
                    help="MODE A: drive the Pi command stream from an emulated EMS "
                         "strategy instead of the scenario's scripted pi_timeline "
                         "(requires --scenario; not with --replay or --pi-live)")
    ap.add_argument("--pi-live", action="store_true",
                    help="MODE B: a REAL Pi owns the command link. This process sends "
                         "injection frames and receives observation frames only — no "
                         "PiCommander is created. Not with --ems, and refused on a "
                         "scenario that carries its own pi_timeline.")
    ap.add_argument("--electrical", default="simple", choices=["simple", "hifi"],
                    help="electrical engine: 'simple' droop node (default) or 'hifi' "
                         "(tools/hil_electrical.py — TPS61288 average model, RT1987 "
                         "switch state machines, node ODE at an adaptive substep rate)")
    ap.add_argument("--droop", default=DROOP_MODE_DEFAULT,
                    choices=list(DROOP_MODES),
                    help="hi-fi droop realization: 'design' (default) realizes "
                         "the MDAC droop chain as designed (~0.316 ohm shared / "
                         "0.633 single); 'measured' rescales it to the BENCH fit "
                         "(0.074 / 0.16 V/A). Opt-in, and it does NOT explain "
                         "the ~4x gap between them — see the K_DROOP_BUS banner. "
                         "Ignored under --electrical simple, which already uses "
                         "the measured constants")
    # ── PART A (C1, 2026-09-01) ─────────────────────────────────────────────
    ap.add_argument("--asymmetry", default=ASYMMETRY_MODE_DEFAULT,
                    choices=list(ASYMMETRY_MODES),
                    help="converter asymmetry between the FC and BT chains: "
                         "'measured' (DEFAULT) injects the fitted static "
                         "mismatch (DeltaV0 +0.0444 V, or +0.0324 V under "
                         "--noise, plus droop_scale_fc 0.930); 'off' runs two "
                         "identical chains and is byte-identical to every "
                         "campaign recorded before this flag existed. Applies "
                         "to BOTH electrical engines")
    # ── ROAD-LOAD PROFILE (2026-09-02, the ftp75c round) ────────────────────
    # Shaped like --asymmetry: a mode choice with a stated default that is
    # BYTE-IDENTICAL to every campaign recorded before the flag existed.  A
    # scenario meta key `drag` supplies the mode when the flag is absent, on
    # --droop's default-vs-explicit rule, so the `ems-ftp75c-*` scenarios need
    # no flag from the operator and an operator asking for a comparison is not
    # silently overruled by the registry.
    ap.add_argument("--drag", default=DRAG_MODE_DEFAULT,
                    choices=list(DRAG_MODES),
                    help="mechanical road load: 'rig' (DEFAULT) is the "
                         "MEASURED F_c + b_eff*v of this bench and regenerates "
                         "nothing on any registered cycle; 'scaled-air' "
                         "replaces it with the study vehicle's scaled air drag "
                         "(k_air 0.0598 N/(m/s)^2, F_c 0) and delivers 51 %% of "
                         "braking energy to the shaft; 'scaled-air-matched' "
                         "divides k_air by the rig's residual drag-to-inertia "
                         "ratio and reproduces the FULL-SCALE 79 %% share. The "
                         "two compensated modes are HIL-ONLY - they need a "
                         "second road-load motor to replicate on the bench")
    ap.add_argument("--trace-config", default="short", choices=["long", "short"],
                    help="hi-fi parasitic-inductance set: 'long' = as-manufactured "
                         "FastHenry extraction (FC 1.538 nH / BT 3.480 nH), 'short' = "
                         "post-bodge routing (default; TODO(verify) — never extracted)")
    ap.add_argument("--vesc-cap-uf", type=float, default=None,
                    help="hi-fi VESC input capacitance in uF (envelope 200-900, "
                         "default 500; some scenarios override it)")
    ap.add_argument("--soc0", type=float, default=0.7,
                    help="initial battery state of charge, 0-1 (default 0.7)")
    ap.add_argument("--capacity-ah", type=float, default=BATT_CAPACITY_AH,
                    help=f"battery capacity in Ah (default {BATT_CAPACITY_AH})")
    ap.add_argument("--noise", action="store_true",
                    help="hi-fi: apply ADC quantization (and any configured sigmas) to "
                         "the injected values")
    # ── MPC strategy overrides (2026-09-02) ─────────────────────────────────
    # EVERY ONE DEFAULTS TO None, and None means "use the constructor's own
    # default", which is the shipped design.  That is the property the design
    # document's registration item 7 asks for: a scenario's `ems` key ALONE
    # reproduces the shipped controller, and any deviation from it is visible
    # on the command line AND in the sidecar's `config.mpc` (which is written
    # from the strategy's own provenance, so it records the RESOLVED value
    # whether it came from a flag or from the default).
    # Ignored, with no error, on a run whose strategy is not an MPC — the same
    # treatment `--vesc-cap-uf` gets under `--electrical simple`.
    ap.add_argument("--mpc-horizon", type=int, default=None,
                    help="MPC: decision stages in the horizon (default 20 at "
                         "1.0 s per stage)")
    ap.add_argument("--mpc-share-band", default=None, metavar="LO,HI",
                    help="MPC: the share ladder's closed interval, e.g. "
                         "'0.25,0.75' (default: the DP's band)")
    ap.add_argument("--mpc-share-levels", type=int, default=None,
                    help="MPC: how many share levels the ladder carries "
                         "(default 7)")
    ap.add_argument("--mpc-budget-ms", type=float, default=None,
                    help="MPC: per-decision search budget in ms (default 12.0). "
                         "On expiry the planner returns the SHIFTED INCUMBENT, "
                         "which is feasible and was validated one second "
                         "earlier — an expiry is a warning about search depth, "
                         "not about the command")
    ap.add_argument("--mpc-roll-budget-ms", type=float, default=None,
                    help="MPC: per-decision budget in ms for the SLICED "
                         "governor transition rolls (default 2.0)")
    ap.add_argument("--mpc-terminal-price", default=None,
                    help="MPC: terminal SoC price mode (default 'metric'; the "
                         "alternative prices the terminal state on the SDP's "
                         "own shadow price)")
    ap.add_argument("--mpc-max-candidates", type=int, default=None,
                    help="MPC: cap the per-decision candidate count, making the "
                         "search DETERMINISTIC and the run reproducible. "
                         "Without it the search is bounded by wall clock and "
                         "an MPC run must never enter a repeatability ledger. "
                         "Refused if this checkout's mpc_ems has no such "
                         "argument")
    ap.add_argument("--mpc-h2-map", default=None,
                    help="MPC: stage hydrogen map, 'proxy' (default, the "
                         "operator-ruled eta_fc 0.40 online proxy) or 'convex' "
                         "(REFUSED unless its three stack coefficients are "
                         "supplied)")
    ap.add_argument("--replay", default=None, metavar="PATH.BLG",
                    help="replay a recorded bench log as injection frames "
                         "(bypasses the plant integrator; open-loop stimulus)")
    ap.add_argument("--replay-speed", type=float, default=1.0,
                    help="replay pacing multiplier (default 1.0 = true wall clock). "
                         "NOTE for --replay-commands: the command stream runs at "
                         "50 Hz of WALL clock, not of log time, so a speed of X "
                         "under-samples the recorded setpoint by X — use 1.0 when "
                         "command fidelity matters.")
    ap.add_argument("--replay-no-preamble", action="store_true",
                    help="replay: SKIP the synthetic bring-up preamble and play the "
                         "log raw from t = 0. For an entry whose point is that "
                         "bring-up FAILS (a log recorded with a dark bus): with the "
                         "preamble the board comes up on the synthetic rails first, "
                         "so FAULT_INIT_FAIL — reachable only from State 0's "
                         "bring-up machine — can never fire. Timestamps are "
                         "UNSHIFTED with this flag.")
    ap.add_argument("--replay-commands", action="store_true",
                    help="replay: ALSO replay the log's recorded commands "
                         "(v_sp / share_sp) as 22-byte Pi command packets at "
                         "50 Hz, so the drive and share loops actually STEP "
                         "against the recorded stimulus instead of holding 0 A "
                         "in Idle. STILL OPEN LOOP on the plant side: the "
                         "injected v_actual does NOT respond to what the "
                         "firmware commands, so this tests the controller's "
                         "REACTION to a recorded trajectory, not closed-loop "
                         "behaviour. Requires --replay.")
    ap.add_argument("--replay-i-fc-clamp", type=float, default=None,
                    metavar="AMPS",
                    help="replay: clamp the injected I_fc to at most AMPS. The "
                         "recorded currents in the legacy logs came from a DC BENCH "
                         "SUPPLY standing in for the H-20 fuel cell, which could "
                         "never source them; a production build replaying them raw "
                         "latches OC_FC before the recorded stimulus arrives. "
                         "Clamping delivers the stimulus the log was kept for. "
                         "DECLARE IT wherever the run is scored — it is a deliberate "
                         "modification of a recorded trajectory.")
    ap.add_argument("--replay-i-bt-clamp", type=float, default=None,
                    metavar="AMPS",
                    help="replay: clamp the injected I_batt to at most AMPS. The "
                         "BT twin of --replay-i-fc-clamp, and it exists for the "
                         "same reason: TP0010's recorded I_batt peaks at 3.586 A, "
                         "above LIMIT_I_BT_MAX 3.0 A, from a DC bench supply "
                         "standing in for the pack. Replayed raw at a production "
                         "build the board latches OC_BT before the recorded UV "
                         "collapse arrives, and State 99 freezes fault_flags. "
                         "DECLARE IT wherever the run is scored.")
    ap.add_argument("--loop", action="store_true",
                    help="replay: repeat the log until --duration elapses")
    ap.add_argument("--duration", type=float, default=None,
                    help="run length in seconds (default 30; replay default = log length)")
    ap.add_argument("--rate", type=float, default=1000.0, help="tick rate in Hz (default 1000)")
    ap.add_argument("--csv", default=None,
                    help="write a per-tick CSV log here. A relative path (bare "
                         "filename or with subdirs) is resolved under "
                         "'<repo>/HIL Results'; an absolute path is used verbatim. "
                         "The electrical events sidecar follows the resolved path. "
                         "OMIT IT and a name is generated: "
                         "hil_<scenario>_<mode>_<YYYYmmdd_HHMMSS>.csv under "
                         "'<repo>/HIL Results'. An explicit path that already "
                         "exists is REFUSED unless --force.")
    ap.add_argument("--no-csv", action="store_true",
                    help="write no CSV, no .meta.json sidecar AND no hi-fi "
                         "electrical events sidecar (all three derive from the "
                         "CSV path). CSV logging is ON by default; use this for "
                         "throughput probes or repeated replays you do not want "
                         "on disk.")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an explicitly-given --csv that already "
                         "exists (auto-named paths never need this — they get a "
                         "'_1', '_2', ... suffix instead)")
    ap.add_argument("--dash", action="store_true",
                    help="live terminal dashboard (5 Hz sampled view; suppresses the "
                         "1 Hz status lines while running). Off by default. Requires a tty.")
    args = ap.parse_args(argv)

    if args.list_scenarios:
        # Column widened 16 -> 20 for the `ems-ftp75-socband` / `ems-y-b30-v1`
        # families; the longest name is 17 characters.
        print(f"{'scenario':<20} {'engine':<7} {'dur':>6}  description")
        for name, meta in SCENARIOS.items():
            print(f"{name:<20} {meta['electrical']:<7} {meta['duration_s']:>5.0f}s  "
                  f"{meta['description']}")
        return 0
    if args.replay and args.scenario:
        ap.error("--replay and --scenario are mutually exclusive")
    if args.replay_speed <= 0.0:
        ap.error("--replay-speed must be > 0")
    if args.loop and not args.replay:
        ap.error("--loop only applies to --replay")
    if args.no_csv and args.csv:
        ap.error("--no-csv and --csv are mutually exclusive: pick a path or pick "
                 "no log")
    if args.force and not args.csv:
        ap.error("--force only applies to an explicit --csv (an auto-named path "
                 "is uniquified with a '_N' suffix and never overwrites)")

    # ── Mode A / Mode B interaction rules ────────────────────────────────────
    # The firmware holds an unrejected command field forever, so two command
    # sources on one link do not "blend" — they overwrite each other at 50 Hz and
    # the board follows whichever wrote last. Every combination that would create
    # a second source is refused here rather than producing a trace nobody can
    # attribute.
    if args.ems and args.pi_live:
        ap.error("--ems and --pi-live are mutually exclusive: --ems IS an emulated "
                 "Pi, so with a real Pi attached two sources would fight over the "
                 "same 22-byte command packet")
    if args.ems and args.replay:
        ap.error("--ems needs a simulated plant (--scenario); in --replay mode the "
                 "plant integrator is bypassed and the rails come from the log")
    # F9: the --ems help text says "(requires --scenario)" but nothing enforced
    # it -- omitting --scenario silently fell back to 'steady', which has no
    # ems_v_profile, so an EMS strategy expecting one (e.g. ems_hold_5050 on
    # ems-drive-cycle) ran against a scenario it was never meant to drive.
    if args.ems and not args.scenario:
        ap.error("--ems requires --scenario (e.g. --scenario ems-drive-cycle): "
                 "without it, --ems would silently fall back to the 'steady' "
                 "scenario, which has no ems_v_profile for the strategy to read")
    if args.pi_live and args.replay:
        ap.error("--pi-live has no effect with --replay: replay mode already creates "
                 "no PiCommander, and the replayed rails ignore the Pi's commands")
    if args.replay_no_preamble and not args.replay:
        ap.error("--replay-no-preamble only applies to --replay")
    # --replay-commands is a REPLAY-mode flag, and its exclusivity against the
    # other two command sources is TRANSITIVE rather than restated here: --ems
    # and --pi-live are each already refused with --replay above, so neither can
    # coexist with a flag that requires --replay.  There is therefore no path on
    # which two sources write the 22-byte command packet.
    if args.replay_commands and not args.replay:
        ap.error("--replay-commands only applies to --replay (in simulated-plant "
                 "mode the commands come from the scenario's pi_timeline, an "
                 "--ems strategy, or a real Pi under --pi-live)")
    if args.replay_i_fc_clamp is not None:
        if not args.replay:
            ap.error("--replay-i-fc-clamp only applies to --replay")
        if args.replay_i_fc_clamp <= 0.0:
            ap.error("--replay-i-fc-clamp must be > 0")
    if args.replay_i_bt_clamp is not None:
        if not args.replay:
            ap.error("--replay-i-bt-clamp only applies to --replay")
        if args.replay_i_bt_clamp <= 0.0:
            ap.error("--replay-i-bt-clamp must be > 0")

    scenario = args.scenario or "steady"
    meta = SCENARIOS[scenario]

    # F3: the pi_timeline guard originally missed ems-driven scenarios (those with
    # meta["ems"] but no meta["pi_timeline"]) — an ems-driven scenario run under
    # --pi-live silently ran as a 60 s no-op (no commander is created for either
    # pi_timeline or ems under --pi-live, so nothing ever commands the board).
    # Both are "this scenario's whole stimulus comes from a command source
    # --pi-live disables", so both must refuse.
    if args.pi_live and not args.replay and meta.get("pi_timeline"):
        ap.error(f"scenario '{scenario}' carries its own pi_timeline, which --pi-live "
                 f"cannot honour: the real Pi owns the command link. Pick a scenario "
                 f"without a timeline (e.g. 'steady', 'drive', 'sag', 'comm-loss') "
                 f"and let the Pi supply the commands.")
    if args.pi_live and not args.replay and meta.get("ems"):
        ap.error(f"scenario '{scenario}' IS the emulated-EMS layer (strategy "
                 f"'{meta['ems']}'); with a real Pi attached under --pi-live there "
                 f"is nothing left for it to drive — the emulated EMS commander is "
                 f"never created under --pi-live, so this would silently run as a "
                 f"no-op. Pick a scenario without an ems strategy (e.g. 'steady', "
                 f"'drive', 'sag', 'comm-loss') and let the Pi supply the commands.")

    ems_name = args.ems
    if not args.replay and ems_name is None and not args.pi_live and meta.get("ems"):
        ems_name = meta["ems"]      # scenario's own default strategy
    if not args.replay:
        if meta["electrical"] == "hifi" and args.electrical != "hifi":
            ap.error(f"scenario '{scenario}' requires --electrical hifi "
                     f"(the simple droop node has no ideal-diode/converter dynamics, "
                     f"so the trace it would produce is meaningless for this test)")
        if args.duration is None:
            args.duration = meta["duration_s"]
    if args.electrical == "hifi" and args.replay:
        ap.error("--electrical hifi has no effect with --replay (the plant integrator "
                 "is bypassed); drop one of them")
    if not 0.0 <= args.soc0 <= 1.0:
        ap.error("--soc0 must be in [0, 1]")
    if args.capacity_ah <= 0.0:
        ap.error("--capacity-ah must be > 0")

    replay = None
    replay_derive_v_rgn = False
    # Effective preamble length for THIS run: the per-entry opt-out collapses it to
    # zero and leaves every replay timestamp unshifted.
    replay_preamble_s = 0.0 if args.replay_no_preamble else REPLAY_PREAMBLE_S
    if args.replay:
        records, blg_header, blg_warnings, replay_derive_v_rgn = load_replay(args.replay)
        replay = ReplaySource(records, speed=args.replay_speed, loop=args.loop)
        fw = blg_header.get("fw_version")
        fw_str = "pre-versioning" if fw is None else str(fw)
        print(f"[hil] replay {args.replay}: BLG format v{blg_header['version']}, "
              f"fw_version={fw_str}, {len(records)} records, "
              f"{replay.span:.3f} s of log, speed={args.replay_speed:g}x"
              f"{', looping' if args.loop else ''}")
        print("[hil] WARNING: replay is an OPEN-LOOP stimulus — the firmware's "
              "commands do NOT influence the replayed trajectory.")
        if args.replay_commands:
            print("[hil] replay: --replay-commands — the log's recorded v_sp / "
                  "share_sp are replayed as 22-byte Pi command packets at "
                  f"{PiCommander.PI_CMD_HZ:.0f} Hz (MODE_SAFE while the preamble "
                  "runs, MODE_HYBRID after it), so the drive and share loops "
                  "STEP instead of holding 0 A in Idle.")
            print("[hil] WARNING: the commands are replayed but THE PLANT SIDE "
                  "STAYS OPEN LOOP — the injected v_actual does not respond to "
                  "what the firmware commands. This tests the controller's "
                  "REACTION to a recorded stimulus, NOT closed-loop behaviour. "
                  "Expect the drive loop to FIGHT the recorded trajectory "
                  "wherever the recorded and flashed control laws differ: that "
                  "is the stimulus, not a defect.")
        print(f"[hil] WARNING: this log was recorded under fw_version {fw_str}; "
              "the flashed firmware's control law may differ (e.g. a v14 'V' "
              "trace is a different control law than v13 — new coefficients and "
              "a x1.34 DC plant gain), so responses will NOT match the log.")
        if replay_preamble_s > 0.0:
            print(f"[hil] replay: {replay_preamble_s:.1f} s synthetic bring-up preamble "
                  f"prepended (healthy nominal rails) — sim time t maps to LOG time "
                  f"t - {replay_preamble_s:.1f}; replay_rec = {REPLAY_PREAMBLE_REC} "
                  f"while the preamble runs")
        else:
            print("[hil] replay: --replay-no-preamble — the log plays RAW from t = 0 "
                  "(sim time == LOG time). The board boots into whatever the "
                  "recording's first samples present, which is the point of this "
                  "mode; a bring-up failure is an EXPECTED outcome here.")
        if args.replay_i_fc_clamp is not None:
            print(f"[hil] replay: *** INJECTED I_fc CLAMPED to "
                  f"{args.replay_i_fc_clamp:.3f} A *** — the recorded trajectory is "
                  f"DELIBERATELY MODIFIED on this channel. The recorded currents "
                  f"came from a DC bench supply the real H-20 could never source; "
                  f"without the clamp a production build latches OC_FC before the "
                  f"stimulus this log is kept for arrives.")
        if args.replay_i_bt_clamp is not None:
            print(f"[hil] replay: *** INJECTED I_batt CLAMPED to "
                  f"{args.replay_i_bt_clamp:.3f} A *** — the recorded trajectory "
                  f"is DELIBERATELY MODIFIED on this channel. Same justification "
                  f"as the FC clamp: the recorded pack current came from a DC "
                  f"bench supply, and without the clamp a production build "
                  f"latches OC_BT before the recorded stimulus arrives.")
        for w in blg_warnings:
            print(f"[hil] replay note: {w}")
        if args.duration is None:
            args.duration = replay_preamble_s + replay.span / args.replay_speed
    if args.duration is None:
        args.duration = 30.0

    dt = 1.0 / args.rate
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.bind(("", args.bind_port))
    dest = (args.teensy_ip, args.port)

    # ── Droop realization mode (WP-E) ────────────────────────────────────────
    # Resolution order: a scenario may declare `droop_mode` and it WINS over the
    # CLI DEFAULT, but an EXPLICIT --droop on the command line wins over the
    # scenario (an operator asking for a comparison must not be silently
    # overruled by a registry key).  No shipped scenario declares the key today
    # — the hook exists so a future measured-vs-design comparison scenario needs
    # no plumbing.
    #
    # E-L5 (2026-09-01): this comment used to claim it mirrored
    # `mppt_emulation`'s pattern.  It does not — `mppt_emulation` is a scenario
    # key with NO CLI flag at all, so there is no default-vs-explicit interplay
    # to mirror.  The pattern below is new here.
    #
    # E-M3 (2026-09-01): "explicit" is decided by comparing the parsed value
    # against the parser's DECLARED DEFAULT, not by sniffing argv for the exact
    # token "--droop".  The old sniff missed every prefix form argparse accepts
    # — `--droop=measured`, and the unambiguous abbreviations `--droo`,
    # `--dro` — so an operator using any of them was silently overruled by the
    # scenario key, which is precisely the outcome this branch exists to
    # prevent.  The comparison has one benign corner: passing the default value
    # explicitly (`--droop design`) is indistinguishable from not passing it,
    # so a scenario key would win.  That is the safe direction — it selects the
    # scenario's declared mode over a request for the mode that is already the
    # default — and it cannot silently discard a non-default request.
    droop_mode = args.droop
    _droop_from = "--droop"
    _droop_default = DROOP_MODE_DEFAULT
    if not args.replay and meta.get("droop_mode") and args.droop == _droop_default:
        droop_mode = str(meta["droop_mode"])
        _droop_from = "scenario key droop_mode"
        if droop_mode not in DROOP_SCALE:
            raise SystemExit("[hil] SCENARIOS[%r] declares droop_mode=%r, "
                             "which is not one of %s"
                             % (scenario, droop_mode, list(DROOP_MODES)))

    # ── PART A (C1, 2026-09-01): converter-asymmetry mode ────────────────────
    # No scenario key and no default-vs-explicit interplay: unlike `--droop`,
    # this is not an opt-in comparison switch but the plant's new baseline, so
    # the CLI value is used as parsed.  A scenario that ever needs the symmetric
    # plant asks for it on the command line, and the sidecar records which was
    # used on EVERY run (see `config.asymmetry` below).
    asymmetry_mode = args.asymmetry

    # ── ROAD-LOAD PROFILE (2026-09-02) ───────────────────────────────────────
    # Resolution order is `--droop`'s, term for term, and for its reason: a
    # scenario may declare `drag` and it WINS over the CLI DEFAULT, but an
    # EXPLICIT --drag wins over the scenario, so an operator running the
    # `ems-ftp75c-*` family at `--drag rig` as a ZERO-REGEN CONTROL is not
    # silently overruled by the registry.  Passing the default explicitly
    # (`--drag rig`) is indistinguishable from not passing it and the scenario
    # key wins; that is the safe direction, for the same reason it is there.
    drag_mode = args.drag
    _drag_from = "--drag"
    if not args.replay and meta.get("drag") and args.drag == DRAG_MODE_DEFAULT:
        drag_mode = str(meta["drag"])
        _drag_from = "scenario key drag"
        if drag_mode not in DRAG_MODES:
            raise SystemExit("[hil] SCENARIOS[%r] declares drag=%r, which is "
                             "not one of %s"
                             % (scenario, drag_mode, list(DRAG_MODES)))
    if drag_mode != DRAG_MODE_DEFAULT:
        # ASCII only: this stream is cp1252 on the bench PC's console.
        print("[hil] drag=%s (k_air %.7f N/(m/s)^2, F_c 0, from %s)"
              % (drag_mode, drag_k_air(drag_mode), _drag_from))
        print("[hil] WARNING: road-load COMPENSATION is a HIL-ONLY plant "
              "configuration. It cannot be replicated on this bench with the "
              "single motor now fitted (a friction feedforward keeps the net "
              "motor force POSITIVE through a stop, so no current reverses); "
              "it needs a second road-load motor. Traces are NOT comparable "
              "with any rig-drag run - the tractive demand falls by roughly "
              "4.5x and braking becomes regenerative.")

    electrical = None
    if args.electrical == "hifi" and not args.replay:
        c_vesc = (args.vesc_cap_uf * 1e-6) if args.vesc_cap_uf is not None \
            else meta.get("vesc_cap_f", C_VESC_DEFAULT)
        electrical = ElectricalSim(
            trace_config=args.trace_config,
            noise=NoiseConfig() if args.noise else None,
            c_vesc_f=c_vesc,
            droop_mode=droop_mode,
            asymmetry_mode=asymmetry_mode)
        print(f"[hil] electrical=hifi trace={args.trace_config} "
              f"C_vesc={c_vesc * 1e6:.0f} uF noise={'on' if args.noise else 'off'} "
              f"droop={droop_mode} (x{DROOP_SCALE[droop_mode]:.5f}, "
              f"from {_droop_from})")
        if droop_mode == "measured":
            # ASCII only: this stream is cp1252 on the bench PC's console.
            print("[hil] WARNING: droop=measured RESCALES the realized droop to the "
                  "BENCH fit (0.074 V/A shared / 0.16 single). Sag depths are "
                  "then comparable with a bench log and NOT with any campaign "
                  "run in the default `design` mode. The ~4x design-vs-bench "
                  "gap is NOT explained by this switch - see the K_DROOP_BUS "
                  "banner in hil_plant_sim.py.")
    elif droop_mode != "design":
        # Loud rather than silently ignored: --droop measured on a simple-mode
        # run reads as a request that was honoured, and it was not (the simple
        # model ALREADY uses the measured constants, so there is nothing to
        # rescale). Recorded in the sidecar as `applied: false` below.
        print("[hil] NOTE: --droop %s has no effect under --electrical %s — "
              "the simple model already uses the BENCH-measured "
              "K_DROOP_BUS_* constants." % (droop_mode, args.electrical))
    # PART A: one banner on EVERY run, both engines, so no trace is ambiguous.
    # ASCII only: this stream is cp1252 on the bench PC's console.
    if not args.replay:
        # Resolved from the SAME inputs the engines use, and computed here
        # rather than read off `plant` because the banner precedes its
        # construction.  Hi-fi carries the F2 droop scaling; simple mode does
        # not (see the Plant asymmetry block for why).
        _asym_dv0 = resolve_asymmetry_dv0_v(asymmetry_mode, electrical)
        print("[hil] asymmetry=%s (injected dV0 %+.6f V, droop_scale_fc %.4f, "
              "noise=%s)"
              % (asymmetry_mode, _asym_dv0, ASYM_DROOP_SCALE_FC
                 if asymmetry_mode == "measured" else 1.0,
                 "on" if args.noise else "off"))
        if asymmetry_mode == "measured":
            print("[hil] NOTE: asymmetry=measured is the DEFAULT from the C1 "
                  "round (2026-09-01) and opens a NEW BASELINE ERA. Shares, "
                  "per-channel currents and every EMS total are NOT comparable "
                  "with a campaign run before it; pass --asymmetry off to "
                  "reproduce the symmetric plant. The droop_scale_fc 0.930 "
                  "figure's CI includes 1.000 - it is a best estimate, not a "
                  "significant one, and it explains neither the +8.1 percent "
                  "shared/single residual nor the ~4x K_DROOP gap. The two "
                  "parameters are the M2 CONSISTENT PAIR (dV0 0.013522 V at "
                  "s_B=1, rho 0.9434) and must not be mixed with a value from "
                  "another fit - see the constants banner in hil_electrical.py.")
    # Scenario-level Ag105 charge-current ceiling (SCENARIOS[...]["chg_i_ceiling_a"],
    # same class of knob as vesc_cap_f).  Absent -> the firmware's configured
    # AG105_I_MAX.  Replay mode has no scenario and no charger model at all.
    chg_ceiling = AG105_I_MAX if args.replay else float(
        meta.get("chg_i_ceiling_a", AG105_I_MAX))
    if chg_ceiling != AG105_I_MAX:
        print(f"[hil] Ag105 charge-current ceiling DE-RATED to {chg_ceiling:.2f} A "
              f"for scenario '{scenario}' (firmware configures {AG105_I_MAX:.2f} A; "
              f"scenario parameter chg_i_ceiling_a — see SCENARIOS)")
    # Scenario-level MPPT threshold emulation (SCENARIOS[...]["mppt_emulation"]),
    # same plumbing class as chg_i_ceiling_a.  Absent/False -> the charger branch
    # behaves exactly as it did before the key existed.  Replay mode has no
    # scenario and no charger model at all.
    mppt_emu = bool(meta.get("mppt_emulation")) and not args.replay
    if mppt_emu:
        print(f"[hil] Ag105 MPPT INPUT-VOLTAGE THRESHOLD emulated for scenario "
              f"'{scenario}': charging is inhibited while MPPT_DISABLE is HIGH "
              f"(tracking released) and V_chg is under the threshold IN FORCE "
              f"(+{AG105_MPPT_V_HYST:.1f} V hysteresis). From fw v24 that is the "
              f"reg-0x02 count the board reports on observation-frame byte 15 "
              f"(clamp band {ag105_mppt_volts(AG105_MPPT_N_FLOOR):.3f}"
              f"-{ag105_mppt_volts(AG105_MPPT_N_CEIL):.3f} V); "
              f"{AG105_MPPT_V_THRESH:.1f} V is used only until a count arrives "
              f"or if the board reports external-resistor mode.")
    plant = Plant(electrical=electrical, soc0=args.soc0,
                  capacity_ah=args.capacity_ah, ag105_i_max=chg_ceiling,
                  mppt_emulation=mppt_emu,
                  # PART A: the plant applies the asymmetry only in SIMPLE mode;
                  # with a hi-fi engine present the two Boost objects already
                  # carry it and this is inert.  Both are handed the SAME
                  # resolved mode so a sidecar reader cannot be misled.
                  asymmetry_mode=asymmetry_mode,
                  # F3: the offsets a NoiseConfig would inject, or zeros.  The
                  # plant applies the asymmetry only in SIMPLE mode, where no
                  # NoiseConfig is ever constructed -- but the value is passed
                  # from the same resolved source either way so the two engines
                  # cannot silently disagree.
                  ina_offset_fc=(electrical.asym_ina_offset_fc
                                 if electrical is not None else 0.0),
                  ina_offset_bt=(electrical.asym_ina_offset_bt
                                 if electrical is not None else 0.0),
                  # THE RESOLVED ROAD-LOAD PROFILE (2026-09-02).  Mechanical
                  # only, so unlike the asymmetry it has no hi-fi counterpart to
                  # keep in step: the electrical engines never see it.
                  drag_mode=drag_mode)
    # Scenario-level Pi-commander mute (SCENARIOS[...]["pi_mute_after_s"]).  Read
    # ONCE here and handed to whichever commander is constructed below; None (the
    # default, and every scenario but `pi-silence`) means "never mute".  Not
    # applicable in replay mode, which has no scenario.
    pi_mute_after = None if args.replay else meta.get("pi_mute_after_s")
    # ── Command source ───────────────────────────────────────────────────────
    # replay             : no commander (the rails come from a log)
    # replay + --replay-commands : commander driven by the LOG's recorded
    #                      v_sp/share_sp, written into commander.state per tick
    # pi-live : no commander — a REAL Pi owns the 22-byte command packet
    # ems     : commander driven by an EMS policy (REPLACES any pi_timeline)
    # default : commander driven by the scenario's pi_timeline (unchanged)
    commander = None
    ems_policy = None
    regen_mgr = None            # RegenManager, or None on every other run
    if args.replay and args.replay_commands:
        # Empty timeline, no policy: every field of `state` is written by the
        # main loop from THIS tick's replay record before commander.tick() runs,
        # so `always_active` is what makes it transmit at all (see PiCommander).
        commander = PiCommander(None, always_active=True)
        print(f"[hil] replay commands: recorded v_sp/share_sp at "
              f"{PiCommander.PI_CMD_HZ:.0f} Hz")
    if not args.replay and not args.pi_live:
        if ems_name:
            ems_policy = EMS_STRATEGIES[ems_name]
            # MPC constructor overrides, applied BEFORE the binding hook below
            # because bind_scenario() is what BUILDS the strategy (and the
            # planner it configures).  `mpc_configure_kwargs()` drops every
            # None, so an untouched command line reproduces the shipped design
            # exactly; a scenario may also declare `mpc_soc_ref_offset`, which
            # a command-line flag does not override because there is no flag
            # for it (it is a placement on the SoC axis, i.e. a property of the
            # scenario, exactly as `sdp_soc_ref_offset` is).
            if isinstance(ems_policy, _MpcProxy):
                # The asymmetry the PLANT of this run injects, resolved off the
                # engines that were just constructed (never off the fitted
                # constant — `--noise` moves it) and handed to the planner so
                # its open-loop share prediction is made on the plant it drives.
                _mk = mpc_configure_kwargs(
                    args, meta,
                    dv0_v=resolve_asymmetry_dv0_v(asymmetry_mode, electrical,
                                                  plant))
                ems_policy.configure(**_mk)
                if _mk:
                    print("[hil] MPC overrides: "
                          + ", ".join("%s=%r" % kv
                                      for kv in sorted(_mk.items())))
            # Generic startup binding hook.  A strategy that needs to VALIDATE
            # itself against the scenario it is about to drive (currently only
            # `dp-replay`, whose offline table is a solution of ONE specific
            # profile) implements
            #     bind_scenario(name, meta, electrical_mode=None, args=None)
            # and raises to refuse.  The two trailing arguments are part of the
            # hook contract (M1/M2, 2026-08-31) and are always passed by name.  Refusing HERE means the operator sees the reason before
            # a single frame is sent, instead of a mid-run crash or — far
            # worse — a run labelled `dp-replay` whose commands are not the
            # DP's.  Strategies without the hook are unaffected.
            binder = getattr(ems_policy, "bind_scenario", None)
            if binder is not None:
                try:
                    # M1: pass the RESOLVED engine, not args.electrical. `hifi`
                    # is downgraded for --replay (and the local `electrical`
                    # object is None whenever the simple bus model is what will
                    # actually run), so the resolved value is what the table's
                    # charger accounting has to agree with. `args` carries the
                    # run's --soc0/--capacity-ah for the M2 checks.
                    binder(scenario, meta,
                           electrical_mode=("hifi" if electrical is not None
                                            else "simple"),
                           args=args,
                           # The RESOLVED modes, not `args.droop` /
                           # `args.asymmetry`: a scenario may override either,
                           # and the DEMAND-MODEL ERA guard (block 0b of
                           # DpReplayStrategy.bind_scenario, and M1's
                           # reconciliation in MpcStrategy's) is a claim about
                           # the plant that will actually run.
                           droop_mode=droop_mode,
                           asymmetry_mode=asymmetry_mode,
                           # The RESOLVED road-load profile, for the same
                           # reason the two above are resolved: `--drag` can
                           # override a scenario key, and the REGEN-ERA guard
                           # (block 0c) is a claim about the plant that will
                           # actually run.
                           drag_mode=drag_mode)
                except UnicodeEncodeError:
                    # NOT a bind refusal (2026-09-02).  UnicodeEncodeError is a
                    # ValueError subclass, so the clause below used to convert a
                    # CONSOLE problem into "this strategy cannot run this
                    # scenario" and exit rc=2 before a frame was sent — the
                    # campaign-20260902 defect that cost two legs.  With
                    # _make_console_lossless() in place this is unreachable in
                    # normal operation; if it fires anyway (a stream that
                    # refused reconfiguration), say so honestly and let the run
                    # proceed, because the strategy did not REFUSE the
                    # scenario — a console encoding is not a bind verdict.
                    # M2 (2026-09-02): the message DELIBERATELY does not claim
                    # the binding succeeded. It is true for the strategies that
                    # print their banner last, but a binder that prints midway
                    # through its checks is abandoned AT the failing print, so
                    # the steps after it never ran. What is known is where it
                    # stopped and that it was not a refusal.
                    print("[hil] WARNING: a bind-time print could not be "
                          "encoded for this console (%s). This is NOT a bind "
                          "refusal and the run continues, but the binder was "
                          "interrupted AT the failing print — check the bind "
                          "order before trusting any check that follows it."
                          % sys.stdout.encoding, file=sys.stderr)
                except (ValueError, OSError) as exc:
                    ap.error("--ems %s cannot run scenario '%s':\n%s"
                             % (ems_name, scenario, exc))
            # ── THE REGEN MANAGER (2026-09-02) ──────────────────────────────
            # Applied AFTER bind_scenario(), so a strategy still binds against
            # the scenario itself and never against a wrapper, and BEFORE the
            # commander is constructed, so the wrapped callable is what runs.
            # Windows are derived from the scenario's own profile and the
            # RESOLVED drag mode, so a `--drag rig` control run of an
            # `ems-ftp75c-*` leg gets the empty window list its own physics
            # implies rather than the compensated profile's nine.
            if meta.get("ems_regen_manager") and meta.get("ems_v_profile"):
                regen_mgr = RegenManager(
                    derive_regen_windows(meta["ems_v_profile"], drag_mode))
                ems_policy = regen_mgr.wrap(ems_policy)
                print("[hil] regen manager: %d window(s), %.3f s of commanded "
                      "duty (%.1f %% of the cycle), drag=%s. charge_goal is "
                      "forced to 1.0 inside a window; the FIRMWARE picks its "
                      "REGEN branch off the commanded motor current "
                      "(regenActive) and opens REGEN_ENABLE with FC_CHARGE shut."
                      % (len(regen_mgr.windows), regen_mgr.duty_s(),
                         100.0 * regen_mgr.duty_s()
                         / max(1e-9, float(meta.get("duration_s") or 1.0)),
                         drag_mode))
                if not regen_mgr.windows:
                    print("[hil] NOTE: NO regen window is derivable on this "
                          "profile and drag profile - the road load exceeds "
                          "the inertial force at every deceleration, so the "
                          "manager is inert and this leg is a ZERO-REGEN "
                          "CONTROL.")
            if meta.get("pi_timeline"):
                print(f"[hil] NOTICE: --ems {ems_name} REPLACES scenario "
                      f"'{scenario}''s pi_timeline ({len(meta['pi_timeline'])} "
                      f"entries) — the timeline is not played at all")
            commander = PiCommander(None, policy=ems_policy, policy_name=ems_name,
                                    mute_after=pi_mute_after)
            print(f"[hil] EMS strategy: {ems_name} at "
                  f"{PiCommander.PI_CMD_HZ:.0f} Hz"
                  + (f", v_setpoint profile: {len(meta['ems_v_profile'])} points"
                     if meta.get("ems_v_profile") else
                     f", no ems_v_profile (a strategy that reads one falls back "
                     f"to a constant {EMS_DEFAULT_CRUISE_MPS:g} m/s cruise; the "
                     f"`y-*` strategies generate their own v_setpoint)")
                  + (f", Run exit t={meta['ems_run_exit_s']:g}s"
                     if meta.get("ems_run_exit_s") is not None else "")
                  + (f", aux preload +{meta['aux_preload_a']:g}A"
                     if meta.get("aux_preload_a") else ""))
        else:
            commander = PiCommander(meta.get("pi_timeline"),
                                    mute_after=pi_mute_after)

            if commander.timeline:
                print(f"[hil] pi-command timeline: {len(commander.timeline)} entries, "
                      f"{PiCommander.PI_CMD_HZ:.0f} Hz")

    # MED-1: the source of the `cmd_share_sp_raw` CSV column (see its header
    # comment).  Resolved ONCE here rather than tested per tick, and by TYPE
    # rather than by strategy NAME: a future artifact played by this same class
    # under another name must still populate the column, and a name test would
    # silently blank it.  None on every other run -> the column is written
    # blank, which is the honest reading of "no table request exists".
    # UNWRAPPED, because the regen manager wraps the strategy in a plain
    # function: a scenario that declares `ems_regen_manager` must not silently
    # lose its `cmd_share_sp_raw` column, its DP provenance or its `config.mpc`
    # block, and an isinstance() test against the wrapper would blank all three.
    _ems_impl = unwrap_policy(ems_policy)
    sdp_raw_src = _ems_impl if isinstance(_ems_impl, SdpStrategy) else None
    # The DP table's provenance source, resolved the same way and for the same
    # reason (by TYPE, not by strategy NAME: a future table played by this same
    # class under another name must still record its artifact).  Consumed ONLY
    # by the meta sidecar below — there is no DP equivalent of the
    # `cmd_share_sp_raw` column, because dp-replay emits its table value
    # unclamped.
    dp_table_src = _ems_impl if isinstance(_ems_impl, DpReplayStrategy) else None
    # The MPC's diagnostics source, resolved by TYPE for the same reason the two
    # above are.  Consumed by the three CSV columns and by `config.mpc` in the
    # sidecar; None on every other run, which blanks all three columns.
    mpc_src = _ems_impl if isinstance(_ems_impl, _MpcProxy) else None
    if commander is not None and commander.mute_after is not None:
        print(f"[hil] Pi commander MUTES at t={commander.mute_after:g}s "
              f"(scenario key pi_mute_after_s): the 22-byte command stream stops "
              f"PERMANENTLY while the injection stream keeps running at full "
              f"rate. The board's Pi watchdog (PI_TIMEOUT_MS 500, armed in "
              f"State 2/3) is the thing under test.")
    if args.pi_live:
        print("[hil] PI-LIVE: no commands are sent by this process. A real Pi must "
              "drive the 22-byte command packet, or the board stays in Idle "
              "(and, once it has ever seen a Pi, faults PI_TIMEOUT after "
              "500 ms of command silence in State 2/3 — .ino:2788, 4817-4826).")
    pi_frames = 0
    obs = None
    obs_last_t = None      # F11: sim-clock time of the last DECODED observation
                            # frame (None = never decoded one yet)
    seq = 0
    rx_frames = 0
    rx_bad = 0
    warm_resets = 0             # observed exits from the latched State 99
    warm_resets_mid_run = 0     # ... after WARM_RESET_GRACE_S (the hazard)
    warm_reset_times = []       # sim-clock t of each, capped for the record
    tx_frames = 0
    send_errors = 0     # F2: sendto() OSError count, parsed by run_hil_suite's
                        # pi-live fault-attribution judge as a continuity signal
    max_overrun = 0.0
    # D10: t0/ticks are predeclared so finalize_meta() is callable from the
    # moment the sidecar exists — including from the setup code BETWEEN the
    # "running" write and the loop (the dashboard bring-up), which could
    # otherwise raise and leave the sidecar frozen at "running" forever.
    # t0 is None until the run clock actually starts; elapsed reads 0.0 then.
    t0 = None
    ticks = 0

    # ── CSV path resolution: ON by default, auto-named ───────────────────────
    # A run with no record is a run nobody can check afterwards, so logging is the
    # default and --no-csv is the opt-out.  Two naming regimes, deliberately
    # asymmetric:
    #   explicit --csv : the operator chose the name -> an existing file is a
    #                    REFUSAL (exit 2) unless --force.  Never silently clobber
    #                    a bench record.
    #   auto-named     : nobody chose the name -> a collision (two runs inside the
    #                    same second) just takes the next free '_N' suffix.
    # run_hil_suite.py passes an explicit --csv into a FRESH timestamped report
    # directory AND passes --force, so a re-run into an operator-supplied --out
    # (the one case where the directory is not fresh) cannot stall the plan on a
    # refusal it has no way to answer.
    csv_auto = False
    if args.no_csv:
        args.csv = None
        if args.electrical == "hifi" and not args.replay:
            # The events sidecar derives from the CSV path, so --no-csv silently
            # disables it too.  On a hi-fi run that is the RT1987/chopper event
            # record — say so rather than let the operator discover it missing.
            print("[hil] NOTE: --no-csv also suppresses the hi-fi electrical "
                  "events sidecar (<csv>.events.jsonl) — scp_cut / sw_ring / "
                  "chopper events will not be recorded anywhere.")
    elif args.csv:
        args.csv = resolve_output_path(args.csv)
        taken = output_path_taken(args.csv)
        if taken and not args.force:
            print("[hil] refusing to overwrite an existing run artifact: %s\n"
                  "      (a run owns its CSV, its .meta.json sidecar and its "
                  "events sidecar — any one of them existing means a previous "
                  "run's record is there)\n"
                  "      pass --force to overwrite it, or omit --csv for an "
                  "auto-named log." % taken, file=sys.stderr)
            sys.exit(2)
    else:
        csv_auto = True
        mode_token_pre = run_mode_token(
            replay_path=args.replay, pi_live=args.pi_live, ems_name=ems_name,
            has_timeline=bool(meta.get("pi_timeline")) and not args.replay,
            electrical=args.electrical)
        args.csv = unique_output_path(resolve_output_path(auto_csv_name(
            None if args.replay else scenario, mode_token_pre)))

    # Mode token as recorded in the sidecar (and, for an auto-named run, embedded
    # in the filename verbatim).
    mode_token = run_mode_token(
        replay_path=args.replay, pi_live=args.pi_live, ems_name=ems_name,
        has_timeline=bool(meta.get("pi_timeline")) and not args.replay,
        electrical=args.electrical)

    csv_file = None
    writer = None
    if args.csv:
        # Relative paths land in "<repo>/HIL Results"; absolute paths (including the
        # ones run_hil_suite.py hands its children) are honored verbatim.  The
        # events sidecar below derives from this RESOLVED path, so it follows.
        print("[hil] CSV log: %s%s" % (args.csv, " (auto-named)" if csv_auto else ""))
        # L1: a CSV the operator explicitly asked for is a run REQUIREMENT -- if it
        # cannot be opened, abort before the run starts rather than limp through a
        # run whose record is silently missing.  The asymmetry with the events
        # sidecar below (best-effort, warn and continue) is deliberate: the sidecar
        # is diagnostic extra, the CSV is the deliverable.
        try:
            csv_file = open(args.csv, "w", newline="")
        except OSError as exc:
            print(f"[hil] could not open CSV log {args.csv}: {exc}", file=sys.stderr)
            sys.exit(2)
        writer = csv.writer(csv_file)
        header_row = [
            "t", "seq", "V_fc", "V_batt", "V_bus", "V_chg", "V_rgn", "I_fc", "I_batt",
            "v_actual", "I_charge", "ag105_status",
            "state", "switch", "aux", "current", "mdac_fc", "mdac_bt",
            "fault_flags",
        ]
        if replay:
            # Existing schema kept byte-for-byte; replay APPENDS one column so a
            # replay CSV stays parseable by anything that reads the simulated
            # schema, while still naming the source record each row came from.
            # NOTE: `soc` and the hi-fi columns are deliberately NOT added in replay
            # mode — the plant integrator is bypassed, so they would be meaningless,
            # and leaving them out keeps replay_rec at its established column index.
            header_row.append("replay_rec")
            # APPEND-only, and UNCONDITIONAL in replay mode — the same principle
            # the simulated branch states below: column presence must not vary
            # with a flag inside one mode, or nothing downstream can parse "a
            # replay-mode CSV" without first knowing which flags produced it.
            # BLANK under a plain --replay (no commander), populated under
            # --replay-commands. `replay_rec` keeps its established index.
            header_row += ["cmd_v_sp", "cmd_share_sp"]
        else:
            header_row.append("soc")            # APPEND-only (scope extension)
            if electrical is not None:
                # `elec_substep_n` (2026-09-02, review PLANT-R1-F6) is the
                # SUBSTEP COUNT this tick actually ran, appended after the
                # two established columns so no offset moves. The rate
                # column alone cannot answer "was this tick resolved finely
                # enough": the substep count is wall-clock ADAPTIVE
                # (ElectricalSim._n_sub follows an EWMA of the per-substep
                # cost), so a loaded host silently runs coarser and the
                # trace does not say so. `substep_resolution` in
                # run_hil_suite.py judges this column.
                header_row += ["elec_substep_hz", "elec_events",
                               "elec_substep_n"]
            # APPEND-only, and UNCONDITIONAL in simulated-plant mode: the two
            # command columns are present for EVERY simulated run, not only under
            # --ems. Column presence must not vary with a flag inside one mode, or
            # nothing downstream can parse "a simulated-mode CSV" without first
            # knowing which flags produced it. They are BLANK when no commander
            # exists (--pi-live: the real Pi's commands are not observable here).
            # Replay mode's schema is untouched — `replay_rec` keeps its index.
            #
            # ⚠️ WHAT THEY TIME (stated 2026-08-31, ledger "contract/doc" — a
            # downstream comment had them wrong).  The row is written from
            # `commander.state`, and PiCommander.tick() walks the timeline
            # (`while timeline[idx][0] <= t`) on EVERY 1 kHz tick, BEFORE the
            # `t < self.next_tx` send gate.  So these columns step at the
            # NOMINAL command instant, not when a packet left: the 22-byte
            # packet carrying the value goes out up to one command period
            # (1/PI_CMD_HZ = 20 ms) later, and its effect reaches the observed
            # columns a further ~1.9 ms of observation round trip after that.
            # A latency measured from a `cmd_*` edge to a switch/current edge
            # therefore INCLUDES the command-arrival phase — which is exactly
            # the [0, 20) ms spread the share-cut latency trackers report.  For
            # an EMS-driven run the two instants coincide (a policy is only
            # called on a due 50 Hz tick), so this distinction is a
            # pi_timeline-mode one.  There is deliberately no `cmd_sent_*`
            # column; add one only if latency decomposition becomes a
            # deliverable.
            header_row += ["cmd_v_sp", "cmd_share_sp"]
            # APPEND-only, and UNCONDITIONAL in simulated-plant mode, same rule
            # as the pair above: the H2 metric is computed by Plant.step() on
            # every simulated tick, so the two columns are always present and
            # always populated.  They are NOT added in replay mode — the plant
            # integrator is bypassed there, so there is no P_fc to consume and a
            # column of zeros would read as "this run burned no hydrogen".
            # ⚠️ These are the Gfc MODEL'S ESTIMATE of hydrogen mass. The map
            # is scale-portable; the stack is NOT identified against this rig
            # (TODO(calibrate)). Read the H2Consumption banner before quoting
            # either column, and read h2_cum_g WITH delta_soc.
            header_row += ["h2_rate_gps", "h2_cum_g"]
            # APPEND-only, unconditional in simulated mode, same rule again:
            # the STUDENT'S STATIC PROXY (P_fc/(0.5*120000)) on the SAME P_fc
            # input h2_cum_g integrates — a SECOND MODEL of one quantity, so
            # the two columns are comparable to their own axes and NOT to each
            # other (the proxy under-reads Gfc by ~5.5 % at steady state by
            # construction).  See the H2_SDP_PROXY_* banner.  No rate column:
            # the rate is `h2_sdp_cum_g` differentiated and the proxy is
            # memoryless, so it would carry no information the cumulative does
            # not — unlike Gfc, whose rate is a dynamic state.
            header_row += ["h2_sdp_cum_g"]
            # MED-1 (2026-08-31 ledger fix queue) — THE PRE-CLAMP TABLE REQUEST.
            # APPEND-only, and UNCONDITIONAL in simulated-plant mode, the same
            # rule as every pair above: presence must not vary with a flag
            # inside one mode.  It is BLANK on every run whose commander is not
            # the SDP strategy (there is no table request to report, and a
            # number there would be a fabrication) — the same "blank rather than
            # zero" discipline cmd_v_sp/cmd_share_sp use under --pi-live.
            # WHY IT EXISTS: `cmd_share_sp` carries the value AFTER
            # SdpStrategy.clamp_share(), and under the shipped v2 policy every
            # table value the ems-sdp walk produces (0.90/0.95/1.00) clamps to
            # the SAME 0.8500 — so the emitted column cannot show that the
            # demand axis moved the table at all, and campaign 20260831_191509
            # could only diagnose the v1 clamp saturation from the exit
            # summary's counters.  This column is the table's ACTUAL request,
            # held between decisions exactly as the emitted one is.
            header_row += ["cmd_share_sp_raw"]
        # ── mppt_thresh_cnt — APPENDED LAST, BOTH MODES (fw v24, 2026-09-01) ──
        # The Ag105 reg-0x02 count the FIRMWARE reports it believes is in force,
        # straight off observation-frame byte 15.  It is an observed board field
        # like `state`/`switch`/`aux`, not a plant quantity, so unlike every
        # block above it belongs to BOTH schemas — a replay run observes the
        # board just as a simulated one does.  It is therefore appended after the
        # per-mode blocks, keeping `replay_rec` and every other established index
        # exactly where it was.
        # BLANK means UNKNOWN, never zero: blank on every row before the first
        # observation frame, and on EVERY row of a run against fw v21-v23, whose
        # 16-byte frame has no such byte (parse_output -> mppt_cnt None).  0 is a
        # legal count (11.0 V), so a zero here would be a fabricated threshold.
        # 255 is the honest "external-resistor mode / never written" value and is
        # written as 255.
        header_row += ["mppt_thresh_cnt"]
        # ── error_code — APPENDED LAST, BOTH SCHEMAS (fw v25, 2026-09-01) ────
        # Observation-frame byte 16: the LATCHED first-cause ErrorCode_t.  Same
        # class as mppt_thresh_cnt above (an observed board field, not a plant
        # quantity), so the same rules: both schemas, appended after it so every
        # established index is untouched, and BLANK means UNKNOWN.
        # BLANK, never 0: 0 is ERR_NONE ("nothing latched"), so a 0-fill on a
        # fw v21-v24 run — whose frame has no such byte — would read as a
        # positive statement of board health the board never made.
        # WHY IT MATTERS: FAULT_PI_TIMEOUT and FAULT_HIL_LINK share fault bit
        # 0x0010, so fault_flags alone cannot say whether the Pi watchdog fired
        # or the injection link died.  error_code can (ERR_PI_TIMEOUT 0x05 vs
        # ERR_HIL_STALE 0x10) — see run_hil_suite.judge_scenario().
        header_row += ["error_code"]
        # ── power balance — APPENDED LAST, BOTH SCHEMAS (2026-09-01f) ────────
        # Seven watt columns computed by Plant.step() (see the block before its
        # return): the motor-node power, the two source powers, the chopper
        # dissipation, the auxiliary load, the residual of the identity
        #     p_mot + p_chg_loss = p_fc + p_batt + p_chop + p_bal
        # and — APPENDED 2026-09-01, after the original six and therefore
        # without moving any of them — the Ag105's own dissipation.  A CSV
        # written before that date has six power columns and no
        # `p_chg_loss_w`; it is a 1:1-charger-era file and its `p_bal_w`
        # carries the charger term the seventh column now names.
        # They belong to the SIMULATED plant only, but they are appended after
        # the per-mode blocks and declared in BOTH schemas so the tail position
        # of every column is one fixed index, exactly as `mppt_thresh_cnt` and
        # `error_code` are.  On a replay run the plant integrator is bypassed, so
        # every row is BLANK — never 0, which would read as "this run moved no
        # power" when in truth the model was never asked.
        header_row += ["p_mot_w", "p_fc_w", "p_batt_w",
                       "p_chop_w", "p_aux_w", "p_bal_w", "p_chg_loss_w"]
        # ── MPC diagnostics — APPENDED AFTER `p_chg_loss_w`, BOTH SCHEMAS ────
        #    (2026-09-02; design document section 8 item 5, adjudication 2.6)
        # Three columns, all BLANK on a run whose strategy is not an MPC and on
        # every replay row — read through `getattr` off the strategy instance
        # exactly as `cmd_share_sp_raw` is, so a non-MPC run writes nothing
        # rather than a fabricated 0.
        #   mpc_solve_ms       the LAST decision's search time in milliseconds.
        #                      It is the budget evidence: the planner is given
        #                      `--mpc-budget-ms` and returns the shifted
        #                      incumbent when it expires, so a column that
        #                      crowds the budget says the search is too deep for
        #                      the horizon, not that the command is wrong.
        #   mpc_share_pred_err |predicted - delivered| stage share, measured one
        #                      decision AFTER the prediction and held until the
        #                      next.  ⚠️ THIS IS THE CLAIM THE STRATEGY MAKES:
        #                      it plans delivered splits, so this column is the
        #                      governor-aware model's own score.  Blank until a
        #                      first prediction has been scored, and NOT updated
        #                      inside a charge window or below the governor's
        #                      minimum load, where the delivered split does not
        #                      identify the applied ratio.
        #   mpc_budget_hit     0/1, the LAST decision's budget flag, held
        #                      between decisions.  Blank before the first
        #                      decision — never 0, which would read as "the
        #                      budget was met" on a run that had not solved.
        header_row += ["mpc_solve_ms", "mpc_share_pred_err", "mpc_budget_hit"]
        # ── fc_ceil / bt_ceil — APPENDED LAST, BOTH SCHEMAS (fw v26) ─────────
        # Observation-frame byte 4, bits 4/5: the source current-ceiling
        # governor's per-channel clamp state.  Same class as `state`/`switch`/
        # `aux`/`mppt_thresh_cnt`/`error_code` — an observed BOARD field, not a
        # plant quantity — so the same rules: declared in BOTH schemas, and
        # appended after every established column so no index moves.
        # The raw `aux` byte is still emitted unchanged at its own index; these
        # two are the decoded 0/1 form, so the scoring layer does not have to
        # re-implement the mask (run_hil_suite reads them by name, and
        # hil_report_analysis.aux_bits() draws the same two bits as lanes).
        # 0/1 rather than blank when a frame is present: the bit being clear is
        # a real observation ("this channel was not clamped"), unlike
        # mppt_thresh_cnt/error_code, whose BYTES can be absent from a legacy
        # frame.  BLANK only when there is no observation frame for the tick at
        # all — the same rule every other observed column follows, and the
        # honest value for "the board said nothing".
        header_row += ["fc_ceil", "bt_ceil"]
        writer.writerow(header_row)

    # M3: open the electrical-events sidecar UP FRONT and stream into it as events
    # happen (drained + flushed every tick, below), instead of writing it only
    # after the main loop returns.  Previously a timeout SIGKILL on a wedged run
    # lost exactly the evidence about why it wedged; now the file on disk is
    # current as of the last completed tick even if the process is killed hard.
    events_path = None
    events_file = None
    events_written = 0          # index into electrical.events already flushed
    elec_events_total = 0       # cumulative count (electrical.events is TRIMMED
                                 # below to bound RAM on a long run, so this is the
                                 # durable total)
    elec_over_absmax = []       # small list of over-abs-max sw_ring events, kept
                                 # in full (rare) for the exit banner
    if args.csv and electrical is not None:
        events_path = args.csv + ".events.jsonl"
        try:
            events_file = open(events_path, "w", encoding="utf-8")
        except OSError as exc:
            print(f"[hil] could not open {events_path}: {exc}", file=sys.stderr)
            events_path = None

    def _drain_electrical_events():
        """Flush any new ElectricalSim events to the sidecar and bound RAM.

        Called every tick.  electrical.events is TRIMMED after each drain (M3):
        the sidecar file is now the durable record, so there is no reason to also
        keep an ever-growing in-memory copy for the life of a long run.

        F5 (fix round, 2026-09-01) — THE events.jsonl ORDERING CONSEQUENCE, and
        why there is no State-99 teardown hook.  A `chopper_clamp` event is
        appended when its episode ENDS (PART B2), so it is written AFTER every
        event that occurred during the episode, even though its own `t` field is
        the episode's START.  Read `t` for onset and `t_end` for close; do NOT
        infer ordering from line position for this kind alone.  Every other kind
        is still emitted at its instant and is in file order.

        THE ALTERNATIVE WAS CONSIDERED AND REJECTED: this module never observes
        a State-99 teardown on the engine's behalf -- the engine has no state
        machine and the plant's teardown is a switch-word change like any other
        -- so a "State-99 hook" would have to be a new observation-frame test
        wired in purely to close an episode.  The single close in the `finally`
        block already covers every exit including a teardown that ends the run,
        and a teardown MID-run legitimately ends the episode by ceasing to
        conduct, which the coalescing gap closes on the next episode's start."""
        nonlocal events_written, elec_events_total
        if electrical is None:
            return
        new_events = electrical.events[events_written:]
        if not new_events:
            return
        elec_events_total += len(new_events)
        for e in new_events:
            if e.get("kind") == "sw_ring" and e.get("over_absmax"):
                elec_over_absmax.append(e)
            if events_file is not None:
                events_file.write(json.dumps(e) + "\n")
        if events_file is not None:
            events_file.flush()
        del electrical.events[:]
        events_written = 0

    src = f"replay={os.path.basename(args.replay)}" if replay else f"scenario={scenario}"
    # Mode marker, shown on the 1 Hz status line's banner and in the dashboard
    # header (the dashboard renders snapshot["source"] verbatim).
    if args.pi_live:
        src += " PI-LIVE"
    elif ems_name:
        src += f" EMS:{ems_name}"
    print(f"[hil] {src} dest={dest[0]}:{dest[1]} "
          f"rate={args.rate:.0f} Hz duration={args.duration:.1f} s")

    # ── .meta.json sidecar: what this run WAS ────────────────────────────────
    # Written twice — "running" now (so a SIGKILL/timeout still leaves a record
    # of what was attempted) and rewritten with results at exit.  Everything
    # expensive (git subprocesses, the constants sweep) happens HERE, once,
    # before the 1 kHz loop starts; the loop itself never touches the sidecar.
    meta_ok = False
    meta_started = None
    meta_const = None
    if args.csv:
        meta_const = collect_model_constants()
        meta_started = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        scenario_meta = None if args.replay else {
            "name": scenario,
            "description": meta.get("description"),
            "duration_s": meta.get("duration_s"),
            "electrical": meta.get("electrical"),
            "pi_timeline_entries": len(meta.get("pi_timeline") or []),
            "ems_default": meta.get("ems"),
            # THE STIMULUS ERA, recorded explicitly rather than inferred.
            # tools/hil_report_analysis.py's matched-DP post-pass reads this
            # key to tell a zero-preload run from a pre-2026-09-01 one; the
            # constants-derived fallback stays for sidecars written before the
            # key existed.  `None` where the scenario declares no preload.
            "aux_preload_a": meta.get("aux_preload_a"),
            # THE CHARGER ERA, recorded explicitly for the same reason as the
            # preload above.  This is a MODEL constant, not a scenario
            # parameter, so it is written from the module rather than from
            # `meta`.  A sidecar that PREDATES the key carries no `eta_chg` at
            # all, and the absence is the era sentinel `None` (see
            # `dp_eta_chg()`) — NOT 1.0.  The 1:1 current-transfer era those
            # runs were produced under is not reproducible by any efficiency
            # value, because it billed the BUS voltage where this model bills
            # the PACK voltage, which is exactly why it is named by a sentinel
            # and not by a number.
            "eta_chg": ETA_CHG,
            # THE DEMAND-MODEL ERA of the DP bound this run may be
            # priced against (2026-09-02), on identical terms: a
            # sidecar that PREDATES the key carries no `loss_map` and
            # that absence is the sentinel for the loss-map-free demand
            # model (see `dp_loss_map()`). It is resolved from the RUN's
            # own configuration rather than from the module default, so
            # a `--electrical simple` or `--droop measured` run records
            # `None` and is never priced against a hi-fi map.
            "loss_map": loss_map_for_config(
                args.electrical, droop_mode, asymmetry_mode),
            # THE ROAD-LOAD ERA and THE REGEN ERA (2026-09-02), on the
            # `eta_chg` / `loss_map` terms exactly: a sidecar that PREDATES
            # either key carries neither, and that ABSENCE is the sentinel for
            # the MEASURED RIG PROFILE and for the pre-regen demand model
            # respectively (see `dp_drag_mode()` and `dp_eta_regen()`).  Both
            # are resolved from THIS RUN's configuration rather than from a
            # scenario key, so a `--drag rig` control run of a compensated
            # scenario records `None` on both and is never priced against a
            # regen-bearing bound.
            "drag": plant_drag_mode(drag_mode),
            "eta_regen": plant_eta_regen(drag_mode),
        }
        meta_doc = {
            "format_version": META_FORMAT_VERSION,
            "tool": META_TOOL_NAME,
            "created": meta_started,
            "finished": None,
            "status": "running",
            "csv": args.csv,
            "csv_auto_named": csv_auto,
            "mode": mode_token,
            "scenario": scenario_meta,
            "ems_strategy": ems_name,
            "pi_live": bool(args.pi_live),
            "replay_source": (None if not args.replay else {
                "path": args.replay,
                "basename": os.path.basename(args.replay),
                "speed": args.replay_speed,
                "loop": bool(args.loop),
                "records": len(replay.records),
                "span_s": round(replay.span, 6),
                "blg_version": blg_header.get("version"),
                # None is HONEST here and is not the R-LOW-3 gap: a BLG v1 log
                # (TP0010) predates the header's fw_version field entirely, so
                # there is no version to record.  The gap R-LOW-3 closed is the
                # DIGEST below — the only field that identifies WHICH bytes were
                # replayed, as opposed to which path they were read from.
                "blg_fw_version": blg_header.get("fw_version"),
                "blg_sha256": blg_header.get("file_sha256"),
                "blg_bytes": blg_header.get("file_bytes"),
                # --replay-commands: were the log's recorded v_sp/share_sp also
                # replayed as Pi command packets?  A replay CSV whose `current`
                # column is non-zero is only interpretable alongside this flag.
                "replay_commands": bool(args.replay_commands),
            }),
            "argv": list(sys.argv[1:]) if argv is None else list(argv),
            "config": {
                "teensy_ip": args.teensy_ip,
                "port": args.port,
                "bind_port": args.bind_port,
                "duration_s": args.duration,
                "rate_hz": args.rate,
                "electrical": args.electrical,
                "trace_config": args.trace_config if args.electrical == "hifi" else None,
                # WP-E: WHICH DROOP REALIZATION THIS RUN USED. Recorded
                # UNCONDITIONALLY (not only when non-default) because a REPORT
                # reader comparing two runs' sag depths needs to be able to
                # tell design from measured on BOTH of them — a key that is
                # absent on the default reads as "old tool", not as "design".
                # `applied` is false when the mode was requested but the run
                # had no hi-fi engine to apply it to.
                "droop_mode": droop_mode,
                "droop_scale": DROOP_SCALE[droop_mode],
                "droop_applied": electrical is not None,
                # PART A (C1, 2026-09-01) — WHICH CONVERTER ASYMMETRY THIS RUN
                # CARRIED.  Recorded UNCONDITIONALLY, for the same reason as
                # droop_mode: a key that is absent reads as "old tool", not as
                # "symmetric".  `asymmetry_dv0_v` is the RESOLVED value (it
                # depends on --noise), and the two droop scales are recorded
                # only when a hi-fi engine realized them — simple mode has no
                # per-channel droop resistance to scale.
                "asymmetry": asymmetry_mode,
                "asymmetry_dv0_v": plant.asym_dv0_v if electrical is None
                                   else electrical.asym_dv0_v,
                "asymmetry_droop_scale_fc": (electrical.asym_droop_scale_fc
                                             if electrical is not None else None),
                "asymmetry_droop_scale_bt": (electrical.asym_droop_scale_bt
                                             if electrical is not None else None),
                # THE ROAD-LOAD PROFILE THIS RUN CARRIED (2026-09-02).
                # Recorded UNCONDITIONALLY, for `droop_mode`'s reason: a key
                # that is absent reads as "old tool", not as "rig".
                # `drag_k_air` is the RESOLVED coefficient, on the
                # `asymmetry_dv0_v` pattern, so a reader never has to
                # re-derive it from Cd and A_f.  `drag_regen_windows` records
                # what the manager actually commanded, which is the only place
                # a trace says WHERE it was allowed to harvest.
                "drag": drag_mode,
                "drag_k_air": drag_k_air(drag_mode),
                "drag_from": _drag_from if not args.replay else None,
                "regen_manager": regen_mgr is not None,
                "regen_windows": (None if regen_mgr is None
                                  else [list(w) for w in regen_mgr.windows]),
                "regen_duty_s": (None if regen_mgr is None
                                 else regen_mgr.duty_s()),
                # Trailing-edge rule (D-4): how many windows the manager
                # released EARLY, on the commanded motor current leaving the
                # braking region, rather than on the wall clock. `regen_duty_s`
                # above is the WALL-CLOCK duty and is therefore an upper bound
                # on the commanded one whenever this is non-zero.
                "regen_early_releases": (None if regen_mgr is None
                                         else regen_mgr.early_releases),
                "vesc_cap_f": (getattr(electrical, "c_vesc", None)
                               if electrical is not None else None),
                "noise": bool(args.noise),
                "soc0": args.soc0,
                "capacity_ah": args.capacity_ah,
                "chg_i_ceiling_a": chg_ceiling,
                "replay_preamble_s": replay_preamble_s if args.replay else None,
                "replay_i_fc_clamp_a": args.replay_i_fc_clamp,
                "replay_i_bt_clamp_a": args.replay_i_bt_clamp,
                "replay_commands": bool(args.replay_commands) if args.replay else None,
                "dash": bool(args.dash),
                # MED-2 (review, 2026-08-31) — WHICH BAKED POLICY DROVE THIS RUN.
                # Present ONLY for an SDP-policy run and absent otherwise, so no
                # other scenario's sidecar grows a null field. Keyed off the
                # STRATEGY TYPE for the reason `sdp_raw_src` is (a rename must
                # not silently drop the provenance record). ⚠️ THIS IS THE ONLY
                # PLACE A TRACE SAYS WHICH DEMAND MAP IT RAN: v1 and v2 declare
                # the same `schema`, so `normalization`/policy_sha256 in here is
                # what separates a v1 run from a v2 one. Nothing else in
                # this document can identify the artifact: `constants_hash`
                # covers module constants, not a JSON file on disk, so a
                # regenerated policy would change every command in the run
                # while leaving the whole sidecar identical. Both digests are
                # carried — the file sha for byte identity, the policy-block
                # sha for the DECISION LAW (stable across a regeneration that
                # did not change it, and the one to compare across campaigns).
                **({"sdp_policy": sdp_raw_src.provenance}
                   if (sdp_raw_src is not None and sdp_raw_src.provenance)
                   else {}),
                # MED (2026-08-31 ledger fix queue) — the DP TABLE's mirror of
                # the block above, added to close the provenance asymmetry the
                # campaign-191509 audit found: an `ems-dp-replay` folder carried
                # no way to verify which table produced its numbers. Present
                # ONLY for a dp-replay run, keyed off the STRATEGY TYPE for the
                # same rename-safety reason. See DpReplayStrategy.bind_scenario
                # for what each field is and why it is in the record.
                **({"dp_table": dp_table_src.provenance}
                   if (dp_table_src is not None and dp_table_src.provenance)
                   else {}),
                # THE MPC's CONFIGURATION (2026-09-02), written the way the two
                # blocks above are: present ONLY for an MPC run, keyed off the
                # STRATEGY TYPE so a rename cannot silently drop it. It carries
                # the RESOLVED value of every `--mpc-*` flag plus the derived
                # quantities a reader cannot recompute (the ladder, the terminal
                # price in g/SoC, the proxy over-read constant, the four modelled
                # levers, and — for `mpc-sto` — the TPM path and bin count), so a
                # trace can be re-read years later without this checkout. The
                # DECISION-TIMING statistics are merged into the SAME block at
                # finalize; see finalize_meta().
                **({"mpc": mpc_src.provenance}
                   if (mpc_src is not None and mpc_src.provenance)
                   else {}),
            },
            "constants_hash": constants_hash(meta_const),
            "constants": meta_const,
            "git": git_provenance(),
            "results": None,
        }
        meta_ok = write_meta_sidecar(args.csv, meta_doc)
        if meta_ok:
            print("[hil] run metadata: %s" % meta_path_for(args.csv))

    def finalize_meta(status, error=None):
        """Rewrite the sidecar with the run's outcome.  Never raises."""
        if not args.csv or meta_started is None:
            return
        elapsed_ = (time.monotonic() - t0) if t0 is not None else 0.0
        meta_doc["finished"] = datetime.datetime.now().astimezone().isoformat(
            timespec="seconds")
        meta_doc["status"] = status
        meta_doc["error"] = error
        meta_doc["results"] = {
            "elapsed_s": round(elapsed_, 3),
            "ticks": ticks,
            # One CSV row per tick whenever a writer exists (the row is written
            # inside the same iteration that increments `ticks`), so this needs
            # no per-tick counter of its own.
            "csv_rows": ticks if writer else 0,
            "achieved_rate_hz": round(ticks / elapsed_, 2) if elapsed_ > 0 else None,
            "target_rate_hz": args.rate,
            "max_overrun_ms": round(max_overrun * 1e3, 3),
            "tx_frames": tx_frames,
            "rx_frames": rx_frames,
            "rx_malformed": rx_bad,
            "send_errors": send_errors,
            "pi_frames": pi_frames,
            "final_state": obs["state"] if obs else None,
            "final_switch": obs["switch"] if obs else None,
            "final_aux": obs["aux"] if obs else None,
            "final_fault_flags": obs["fault_flags"] if obs else None,
            "observed_any_frame": obs is not None,
            # Mid-run warm-reset tripwire — see WARM_RESET_GRACE_S.  A nonzero
            # `warm_resets_mid_run` means the board restarted underneath the
            # stimulus, so the remainder of the run is not the scenario the
            # checks assume; every verdict on it is inconclusive unless the
            # scenario expects the recovery
            # (SCENARIOS[...]["warm_resets_expected"]).
            "warm_resets_observed": warm_resets,
            "warm_resets_mid_run": warm_resets_mid_run,
            "warm_reset_times_s": list(warm_reset_times),
            "warm_reset_grace_s": WARM_RESET_GRACE_S,
            "electrical_events": elec_events_total,
            "electrical_events_path": events_path,
            "electrical_over_absmax": len(elec_over_absmax),
            "electrical_substep_hz": (round(electrical.achieved_substep_hz, 1)
                                      if electrical is not None else None),
            "electrical_numeric_fault": (bool(electrical.summary().get("numeric_fault"))
                                         if electrical is not None else None),
            "soc_final": None if replay else round(plant.battery.soc, 6),
            "replay_last_record": replay.i if replay else None,
        }
        # MPC decision timing, merged into `config.mpc` at finalize (design
        # document section 8, item 6). It belongs beside the configuration
        # rather than in `results` because the two are read together: a median
        # solve time is only interpretable against the budget that bounded it.
        # NEVER RAISES — finalize_meta()'s contract — so a strategy that was
        # never built, or a run that ended before its first decision, simply
        # contributes nothing.
        try:
            if mpc_src is not None:
                _tm = mpc_src.timing()
                if _tm:
                    meta_doc["config"].setdefault("mpc", {})
                    meta_doc["config"]["mpc"]["timing"] = _tm
        except Exception:                       # pragma: no cover - defensive
            pass
        write_meta_sidecar(args.csv, meta_doc)

    # ── Optional live dashboard ──────────────────────────────────────────────
    # Lightness contract (docs/HIL_MODE.md "Live dashboard"): the loop's ONLY
    # obligation is `dash.snapshot = {...}` — one attribute assignment, atomic
    # under the GIL.  A daemon thread renders at 5 Hz from whatever snapshot is
    # current, so the view is deliberately several ticks behind.  Banners above
    # and the summary below still print normally; the 1 Hz status lines and the
    # in-loop replay note are suppressed/deferred while the screen is owned.
    dash = None
    deferred_notes = []
    # D10: anything that raises between the "running" sidecar write above and the
    # main loop's own try/except would leave the sidecar saying "running"
    # forever.  The dashboard bring-up is the only such code, and it CAN fail
    # (a missing module raises SystemExit; Dashboard.start() touches the
    # terminal).  Finalize as "error" here, then let the exception through
    # untouched.
    try:
        if args.dash:
            # Lazy import, same convention as the replay decoder above: the
            # module lives beside this file rather than on the default path.
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            try:
                from hil_dashboard import Dashboard
            except ImportError as exc:
                raise SystemExit(f"[hil] --dash needs tools/hil_dashboard.py ({exc})")
            d = Dashboard()
            if d.start():
                dash = d
    except BaseException as exc:          # SystemExit is not an Exception
        try:
            finalize_meta("error", error="dashboard setup: %s: %s"
                                         % (type(exc).__name__, exc))
        except Exception:
            pass                          # provenance must never mask the cause
        raise
    dash_on = dash is not None

    t0 = time.monotonic()
    next_tick = t0
    last_status = t0
    tx_enabled = True
    sent_seq = 0        # last seq actually transmitted (CSV column)
    run_status = "completed"
    pending_error = None    # D6: set by the except clause, consumed after teardown

    try:
        while True:
            now = time.monotonic()
            t = now - t0
            if t >= args.duration:
                break

            # ── Drain every observation frame waiting on the socket ──────────
            while True:
                try:
                    data, _addr = sock.recvfrom(256)
                except BlockingIOError:
                    break
                except OSError:
                    break
                decoded = parse_output(data)
                if decoded is None:
                    rx_bad += 1
                else:
                    # Warm-reset tripwire (see WARM_RESET_GRACE_S).  Per-frame
                    # cost is one integer compare on an already-parsed field;
                    # the list append happens only on a transition.
                    if (obs is not None and obs["state"] == 99
                            and decoded["state"] != 99):
                        warm_resets += 1
                        if t >= WARM_RESET_GRACE_S:
                            warm_resets_mid_run += 1
                        if len(warm_reset_times) < WARM_RESET_TIMES_MAX:
                            warm_reset_times.append(round(t, 3))
                        # Review M1 (2026-08-31): a warm reset re-runs the staged
                        # bring-up, so the scp-inrush one-shot must re-arm for a
                        # clean phase-1 ramp — otherwise the second P3 close ramps
                        # into the standing 5.0 A run load (the pre-redesign
                        # configuration).  Harmless for every other scenario
                        # (nothing else reads these fields; `plant` is
                        # constructed unconditionally, replay included).
                        plant.scp_armed = False
                        plant.scp_fired = False
                        plant.scp_fired_t = None
                        # L5 (review, 2026-08-31) — WHAT DELIBERATELY SURVIVES
                        # a mid-run warm reset, stated so the asymmetry above
                        # does not read as an oversight.  The BOARD restarts;
                        # the PLANT does not.  Nothing here is reset:
                        #   * the plant integrator (v, bus state, the hi-fi
                        #     node network) — the flywheel does not stop
                        #     spinning because the MCU rebooted, and zeroing it
                        #     would inject a step the hardware never sees;
                        #   * `plant.battery.soc` and the coulomb count — the
                        #     pack's charge is physical state;
                        #   * `plant.h2` (rate and cum_g) — the hydrogen burned
                        #     before the reset was still burned, so the metric
                        #     keeps ACCUMULATING rather than restarting;
                        #   * the EMS policy's own state (SoC reference,
                        #     trailing cruise window, charge latch) — the host
                        #     did not restart either.
                        # Continuing accumulation is the honest choice: the
                        # alternative silently discards part of a run's cost.
                        # The reset is not swept under the rug either — a
                        # non-whitelisted mid-run warm reset already renders
                        # the whole run INCONCLUSIVE in run_hil_suite.py, which
                        # is where "these totals span a board restart" is
                        # supposed to be caught.  Only `scp_*` re-arms, because
                        # it tracks a BOARD-side one-shot (the staged bring-up)
                        # that genuinely does run again.
                    obs = decoded
                    obs_last_t = t          # F11: stamp with sim-clock time, not
                                             # wall time — obs_age_s is measured
                                             # against the same clock as `t`
                    rx_frames += 1

            if replay:
                # Plant integrator BYPASSED: the rails come from the log.  The
                # observation-receive path, CSV logging and status line above/
                # below still run — comparing the firmware's live response
                # against the recorded bench run is the whole point.
                tx_enabled = True
                mot_pwr_closed = bool(obs and (obs["switch"] & SW_MOT_PWR))
                if t < replay_preamble_s:
                    # Synthetic bring-up preamble: healthy nominal rails so the
                    # fw v22+ staged bring-up can complete before the recorded
                    # trajectory starts.  See REPLAY_PREAMBLE_S.
                    sensors = replay_preamble_sensors(t, mot_pwr_closed)
                    rec_idx = REPLAY_PREAMBLE_REC
                else:
                    sensors, rec_idx = replay.sample(t - replay_preamble_s)
                    if sensors is None:
                        note = ("[hil] replay: end of log at t=%.3fs "
                                "(log time %.3fs)" % (t, t - replay_preamble_s))
                        if dash_on:
                            deferred_notes.append(note)   # screen is owned; print after stop()
                        else:
                            print(note)
                        break
                    # ReplaySource hands back the SAME dict on every zero-order-hold
                    # tick, so any per-tick modification must copy first or it would
                    # corrupt the record for every later sample of it.  One copy
                    # covers both modifications below.
                    if (replay_derive_v_rgn or args.replay_i_fc_clamp is not None
                            or args.replay_i_bt_clamp is not None):
                        sensors = dict(sensors)
                    if replay_derive_v_rgn:
                        # This record format has no V_rgn.  Derive it from the
                        # injected V_bus and the board's OWN MOT_PWR bit (fw v22
                        # topology: the RGN-V divider sits on V-MOT).
                        sensors["V_rgn"] = sensors["V_bus"] if mot_pwr_closed else 0.0
                    if args.replay_i_fc_clamp is not None:
                        # H1: ceiling on the injected FC current.  See the flag's
                        # help text and the banner above — this MODIFIES the
                        # recorded trajectory and is declared everywhere it is used.
                        if sensors["I_fc"] > args.replay_i_fc_clamp:
                            sensors["I_fc"] = args.replay_i_fc_clamp
                        elif sensors["I_fc"] < -args.replay_i_fc_clamp:
                            sensors["I_fc"] = -args.replay_i_fc_clamp
                    if args.replay_i_bt_clamp is not None:
                        # R-MED-1: the BT twin of the clamp above.  Symmetric
                        # (both signs) for the same reason: LIMIT_I_BT_MAX is
                        # judged on the magnitude, so a large NEGATIVE recorded
                        # sample latches OC_BT exactly as a positive one does.
                        if sensors["I_batt"] > args.replay_i_bt_clamp:
                            sensors["I_batt"] = args.replay_i_bt_clamp
                        elif sensors["I_batt"] < -args.replay_i_bt_clamp:
                            sensors["I_batt"] = -args.replay_i_bt_clamp
            else:
                # ── RX-BEFORE-STEP ORDERING, and what it decides ────────────
                # `obs` here is the MOST RECENT observation frame, received at the
                # top of this tick, and it is applied to the plant BEFORE the
                # solver runs. So on any tick where the board's switch word and an
                # autonomous plant event would both act, THE BOARD'S WORD WINS —
                # a tie goes to the firmware.
                #
                # This is not academic: it decided the scp-inrush scenario's
                # outcome (root-caused 2026-08-31) UNTIL THE 2026-08-31
                # DETERMINISTIC REDESIGN of that stimulus. Under the old flat
                # load the RT1987 SCP fold's cut landed one tick after switch
                # admission (S = MOT_PWR close + RT_TD_ON_S), while the
                # firmware's OC_FC teardown landed at S+L, where L is the
                # observation round trip — 1 OR 2 ticks depending on
                # sub-millisecond host/board phase. At L=2 the fold cut first and
                # `scp_cut` fired; at L=1 the teardown's EN-low preempted it and
                # no event was recorded, from a plant trace that was otherwise
                # bit-identical. Campaign 20260830_203006 and round 1 saw L=2;
                # round 2 saw L=1 and the scenario failed on a phase coin-flip,
                # not on anything the board or the model did wrong. The stimulus
                # now fires the fold INSIDE the admission tick (see the
                # SCP_INRUSH_ARM_V block), so it no longer enters this race — but
                # the ordering below is unchanged and still governs every other
                # same-tick contest.
                #
                # Keep this ordering — a plant that ran ahead of the board's own
                # word would be the less faithful of the two. But any scenario
                # whose verdict depends on an event landing in the SAME tick as a
                # firmware reaction is sitting on this coin flip, and must be
                # re-margined at the stimulus rather than have its check widened.
                tx_enabled = apply_scenario(plant, scenario, t)
                sensors = plant.step(dt, obs)
                rec_idx = None

            _drain_electrical_events()

            if tx_enabled:
                frame = pack_inject(
                    seq, sensors["V_fc"], sensors["V_batt"], sensors["V_bus"],
                    sensors["V_chg"], sensors["V_rgn"], sensors["I_fc"],
                    sensors["I_batt"], sensors["v_actual"],
                    sensors["I_charge"], sensors["ag105_status"],
                )
                try:
                    sock.sendto(frame, dest)
                    tx_frames += 1
                except OSError as exc:
                    send_errors += 1   # F2: continuity signal for run_hil_suite's
                                        # pi-live fault-attribution judge
                    print(f"[hil] send failed: {exc}", file=sys.stderr)
                sent_seq = seq                 # the seq actually on the wire this tick
                seq = (seq + 1) & 0xFF

            # ── Pi command timeline ─────────────────────────────────────────
            # Same socket, same destination: the firmware's receiveCommands()
            # drains both frame types and dispatches by length (fw v21).
            if commander is not None and tx_enabled:
                if replay and args.replay_commands:
                    # ── Replayed commands ────────────────────────────────────
                    # Driven from THIS TICK's already-sampled replay record, so
                    # the command stream is zero-order held on exactly the same
                    # time axis as the injection stream — --replay-speed
                    # alignment is therefore automatic and needs no separate
                    # pacing.  Written into `state` before tick(); the 50 Hz gate
                    # inside tick() then decides when a packet actually goes out,
                    # so the board sees the command that was current at the last
                    # due tick, exactly like a real Pi.
                    if t < replay_preamble_s:
                        # Synthetic bring-up window: hold the board at standstill
                        # in SAFE.  MODE_SAFE only acts in State 2 (.ino:5051-5052);
                        # from State 0/1 it is inert, which is what is wanted while
                        # the staged bring-up runs.
                        commander.state["mode_cmd"] = MODE_SAFE
                        commander.state["v_setpoint"] = 0.0
                        commander.state["power_share_setpoint"] = 0.5
                    else:
                        # MODE_HYBRID with mainState 1 is what moves the board
                        # Idle -> Run (.ino:5047-5050).  doState1() zeroes
                        # v_setpoint on that transition and resets the drive
                        # controller, so the real setpoint arrives on the next
                        # 50 Hz packet (<= 20 ms later) — by design, and stated in
                        # docs/HIL_MODE.md.  Once in Run the 50 Hz stream is
                        # LOAD-BEARING: PI_TIMEOUT_MS is 500 ms (.ino:2915) and the
                        # watchdog arms after the first command, so this branch
                        # must keep writing for the WHOLE remaining run, gaps in
                        # the log included.
                        commander.state["mode_cmd"] = MODE_HYBRID
                        commander.state["v_setpoint"] = sensors["cmd_v_sp"]
                        commander.state["power_share_setpoint"] = \
                            sensors["cmd_share_sp"]
                    commander.state["charge_goal"] = 0.0
                # F13: build the fb closure/dict only when there is an EMS policy
                # to feed it. A scripted timeline commander never reads fb_factory
                # (PiCommander.tick only calls it when self.policy is not None),
                # so for the scripted/plain path this was a dict-and-closure built
                # every 1 kHz tick for nothing. Hot path (no policy) is now just
                # `commander.tick(t, None)`, byte-identical in behavior.
                if commander.policy is not None:
                    def _fb():
                        """Feedback view for an EMS policy — see the MODE A block
                        above for which keys are telemetry-equivalent and which
                        are not (FB_TELEMETRY_EQUIV_KEYS). Built ONLY on a due
                        50 Hz commander tick, and only when a policy is armed."""
                        fb = {
                            "t": t,
                            # telemetry-equivalent (v4 packet, .ino:4988-5069) —
                            # see FB_TELEMETRY_EQUIV_KEYS
                            "v_actual": sensors["v_actual"],
                            "V_bus": sensors["V_bus"], "V_fc": sensors["V_fc"],
                            "V_batt": sensors["V_batt"], "V_chg": sensors["V_chg"],
                            "V_rgn": sensors["V_rgn"],
                            "I_fc": sensors["I_fc"], "I_batt": sensors["I_batt"],
                            "I_charge": sensors["I_charge"],
                            "ag105_status": sensors["ag105_status"],
                            # plant truth — NOT visible to a real Pi
                            "soc": sensors.get("soc"),
                            # scenario profile (host-side script, not feedback at all)
                            "v_profile": piecewise(meta.get("ems_v_profile"), t),
                            # scenario Run-exit override (host-side script, like
                            # v_profile — NOT telemetry). None when the scenario
                            # declares none, in which case every strategy falls
                            # back to its own constant. See ems_run_exit().
                            "ems_run_exit_s": meta.get("ems_run_exit_s"),
                            # observation frame — NOT in v4 telemetry except `switch`
                            # (offset 52) and `fault_flags` (offset 53)
                            "state": obs["state"] if obs else None,
                            "switch": obs["switch"] if obs else None,
                            "aux": obs["aux"] if obs else None,
                            "current": obs["current"] if obs else None,
                            "fault_flags": obs["fault_flags"] if obs else None,
                            # ── observation frame, MDAC words (2026-09-02) ──
                            # The two 12-bit droop codes the board actually
                            # applied. They are NOT in the v4 telemetry packet
                            # and so are NOT portable to a real Pi; a strategy
                            # that reads them must degrade without them.
                            # ⚠️ WHY THEY ARE HERE. `mpc-det`/`mpc-sto` carry a
                            # SHADOW copy of the firmware's share governor and
                            # correct it from feedback each tick. Without these
                            # two words the only correction available is the
                            # measured current split, which identifies the
                            # applied ratio ONLY where both channels conduct
                            # above the 0.60 A closed-loop gate — i.e. not in
                            # the open-loop hold, which is where a shadow model
                            # drifts. r_from_codes() reads the ratio directly
                            # and is valid in every mode. Additive: every other
                            # strategy ignores the keys.
                            "mdac_fc": obs["mdac_fc"] if obs else None,
                            "mdac_bt": obs["mdac_bt"] if obs else None,
                            # F11: age of the last DECODED observation frame, in
                            # sim-clock seconds; None if none has ever arrived.
                            # obs itself is NOT bounded by freshness (behavior-
                            # preserving) — a policy that cares must check this
                            # against ~HIL_ZERO_MS/1000 (0.25 s) itself; see the
                            # MODE A block / manual Sec 3.3.
                            "obs_age_s": (t - obs_last_t) if obs_last_t is not None
                                         else None,
                        }
                        return fb
                    pkt = commander.tick(t, _fb)
                else:
                    pkt = commander.tick(t, None)
                if pkt is not None:
                    try:
                        sock.sendto(pkt, dest)
                        pi_frames += 1
                    except OSError as exc:
                        print(f"[hil] pi command send failed: {exc}", file=sys.stderr)

            if writer:
                # Log the seq that was SENT this tick, not the already-incremented next one
                # (the old code logged seq post-increment, so every CSV row was off by one
                # against the frame it describes and against the firmware's seq echo).
                # On a non-transmitting tick ("comm-loss") there is no frame: log blank.
                row = [
                    f"{t:.6f}", sent_seq if tx_enabled else "",
                    f"{sensors['V_fc']:.4f}", f"{sensors['V_batt']:.4f}",
                    f"{sensors['V_bus']:.4f}", f"{sensors['V_chg']:.4f}",
                    f"{sensors['V_rgn']:.4f}", f"{sensors['I_fc']:.4f}",
                    f"{sensors['I_batt']:.4f}", f"{sensors['v_actual']:.5f}",
                    f"{sensors['I_charge']:.4f}", f"0x{sensors['ag105_status']:02X}",
                    obs["state"] if obs else "",
                    obs["switch"] if obs else "",
                    obs["aux"] if obs else "",
                    f"{obs['current']:.4f}" if obs else "",
                    obs["mdac_fc"] if obs else "",
                    obs["mdac_bt"] if obs else "",
                    obs["fault_flags"] if obs else "",
                ]
                if replay:
                    row.append(rec_idx)
                    # M3 — WHAT THESE TWO COLUMNS ARE, precisely: the RECORD'S OWN
                    # commanded value for THIS tick, sampled at the 1 kHz tick rate.
                    # They are NOT "what was last transmitted": under
                    # --replay-commands the state is rewritten every 1 kHz tick
                    # while packets leave at PiCommander.PI_CMD_HZ (50 Hz), so the
                    # transmitted stream LAGS this column by <= 20 ms, and across
                    # the preamble boundary the column LEADS the last transmitted
                    # mode by up to one command period.
                    # The 1 kHz semantics are deliberate: this column is the clean
                    # zero-order-held command axis for offline analysis, aligned
                    # tick-for-tick with the injected sensors beside it. Anything
                    # needing the wire-accurate stream must reconstruct it from the
                    # 50 Hz cadence.
                    # Blank under a plain --replay (no commander exists): a number
                    # there would be a fabrication.
                    if commander is not None and commander.active():
                        row.append(f"{commander.state['v_setpoint']:.4f}")
                        row.append(f"{commander.state['power_share_setpoint']:.4f}")
                    else:
                        row += ["", ""]
                else:
                    row.append(f"{sensors.get('soc', 0.0):.5f}")
                    if electrical is not None:
                        row.append(f"{electrical.achieved_substep_hz:.0f}")
                        # M3: electrical.events is trimmed on every drain now, so
                        # the durable per-tick total is the tracked cumulative
                        # counter, not len(electrical.events) (which is ~0 most
                        # ticks).
                        row.append(elec_events_total)
                        # L2 (2026-09-02): the count THIS tick ran, not
                        # `_n_sub`, which step() has already re-derived for the
                        # NEXT tick from the measured cost.
                        row.append(electrical.n_sub_last)
                    # Commanded setpoints as this process last sent them. Blank
                    # under --pi-live (no commander): the real Pi's commands never
                    # pass through here, so a number would be a fabrication.
                    if commander is not None and commander.active():
                        row.append(f"{commander.state['v_setpoint']:.4f}")
                        row.append(f"{commander.state['power_share_setpoint']:.4f}")
                    else:
                        row += ["", ""]
                    # H2 metric (append-only, unconditional in simulated mode).
                    # 9 significant digits: the rate is O(1e-4) g/s and the
                    # cumulative O(1e-3) g, so %.4f would round both to zero.
                    row.append(f"{sensors.get('h2_rate_gps', 0.0):.9g}")
                    row.append(f"{sensors.get('h2_cum_g', 0.0):.9g}")
                    # Same 9 significant digits, same reason (O(1e-3) g).
                    row.append(f"{sensors.get('h2_sdp_cum_g', 0.0):.9g}")
                    # MED-1: the SDP table's PRE-clamp request, or blank when no
                    # SDP policy is driving this run (see the header comment).
                    # Read off the strategy instance rather than the commander:
                    # the commander only carries what was EMITTED, which is the
                    # post-clamp value already in cmd_share_sp.
                    # DI-LOW-6: also BLANK before the first decision, when
                    # last_share_raw is still None — the column must never
                    # fabricate a table request the policy has not made yet.
                    row.append(
                        "" if (sdp_raw_src is None
                               or sdp_raw_src.last_share_raw is None)
                        else f"{sdp_raw_src.last_share_raw:.4f}")
                # mppt_thresh_cnt (fw v24) — appended in BOTH modes, see the
                # header comment.  Blank when there is no observation frame yet
                # or the frame was the 16-byte legacy layout; never 0-filled.
                row.append("" if (obs is None or obs.get("mppt_cnt") is None)
                           else int(obs["mppt_cnt"]))
                # error_code (fw v25) — appended in BOTH modes, see the header
                # comment.  Blank when there is no observation frame yet or the
                # frame predates fw v25; never 0-filled (0 is ERR_NONE).
                row.append("" if (obs is None or obs.get("error_code") is None)
                           else int(obs["error_code"]))
                # Power balance (2026-09-01f) — appended in BOTH schemas, see
                # the header comment.  Populated on every simulated tick (the
                # plant computes them unconditionally, like the h2 pair) and
                # BLANK on every replay row, where no plant ran.  6 decimals:
                # the columns span roughly 1e-2 to 1e2 W and the residual is
                # read against the aux term, which is O(1 W).
                for _pk in ("p_mot_w", "p_fc_w", "p_batt_w",
                            "p_chop_w", "p_aux_w", "p_bal_w",
                            "p_chg_loss_w"):
                    _pv = sensors.get(_pk)
                    row.append("" if _pv is None else f"{_pv:.6f}")
                # MPC diagnostics (2026-09-02) — appended in BOTH schemas, see
                # the header comment.  `mpc_src` is None for every non-MPC run
                # AND on a replay run, so all three columns are blank there.
                if mpc_src is None:
                    row += ["", "", ""]
                else:
                    # One cheap call per tick; it derives the held budget flag
                    # from the strategy's own decision/budget counters.
                    mpc_src.observe_decision()
                    _sms = mpc_src.solve_ms_last
                    _spe = mpc_src.share_pred_err
                    _bh = mpc_src.budget_hit_last
                    row.append("" if _sms is None else f"{_sms:.3f}")
                    row.append("" if _spe is None else f"{_spe:.5f}")
                    row.append("" if _bh is None else int(_bh))
                # fc_ceil / bt_ceil (fw v26) — appended in BOTH schemas, see
                # the header comment.  Decoded from the aux byte already in
                # hand, so this costs two mask tests per written row.
                if obs is None:
                    row += ["", ""]
                else:
                    _aux = obs["aux"]
                    row.append(1 if _aux & AUX_FC_CEILING else 0)
                    row.append(1 if _aux & AUX_BT_CEILING else 0)
                writer.writerow(row)

            ticks += 1

            # ── Dashboard feed: ONE attribute assignment, no I/O, no locks ───
            if dash_on:
                i_fc = sensors["I_fc"]
                i_bt = sensors["I_batt"]
                i_tot = i_fc + i_bt
                dash.snapshot = {
                    "t": t, "source": src, "mode": args.electrical,
                    "rate_hz": (ticks / (now - t0)) if now > t0 else None,
                    "tx": tx_frames, "rx": rx_frames, "bad": rx_bad, "pi": pi_frames,
                    # `.active()` covers BOTH command sources: a scripted timeline
                    # and an EMS policy. Under --pi-live there is no commander at
                    # all, so these degrade to None and the dashboard renders an
                    # em-dash — correct, since the real Pi's setpoints are external
                    # and genuinely unknown to this process.
                    "v_sp": (commander.state["v_setpoint"]
                             if commander and commander.active() else None),
                    "v_act": sensors["v_actual"],
                    "share_sp": (commander.state["power_share_setpoint"]
                                 if commander and commander.active() else None),
                    # Share is undefined at negligible source current — the
                    # ratio is all noise below ~50 mA.
                    "share_act": (i_fc / i_tot) if i_tot > 0.05 else None,
                    "V_bus": sensors["V_bus"], "I_tot": i_tot,
                    "I_fc": i_fc, "I_bt": i_bt,
                    "I_chg": sensors["I_charge"], "ag105": sensors["ag105_status"],
                    # fw v24 reg-0x02 threshold count (observation-frame byte 15).
                    # None on a legacy 16-byte frame or before the first frame;
                    # plain scalar, no I/O — the lightness contract holds.
                    "mppt_cnt": obs.get("mppt_cnt") if obs else None,
                    "state": obs["state"] if obs else None,
                    "switch": obs["switch"] if obs else None,
                    "aux": obs["aux"] if obs else None,
                    "I_cmd": obs["current"] if obs else None,
                    "faults": obs["fault_flags"] if obs else 0,
                    # fw v25 latched first-cause code (observation-frame byte
                    # 16).  None before the first frame and on any pre-v25
                    # board; the dashboard renders that as '—', never as
                    # ERR_NONE.  Plain scalar — lightness contract holds.
                    "error_code": obs.get("error_code") if obs else None,
                    "hifi_hz": electrical.achieved_substep_hz if electrical else None,
                    "hifi_events": elec_events_total,
                    "hifi_chopper_w": electrical.chopper_peak_w if electrical else None,
                }

            # ── 1 Hz status line (and CSV flush, M3) ─────────────────────────
            if now - last_status >= 1.0:
                last_status = now
                # M3: flush at ~1 Hz so a hard-killed run's CSV is current on disk
                # up to the last completed second, not just at clean exit.
                if csv_file:
                    csv_file.flush()
                if dash_on and dash.error is None:
                    pass                # the dashboard owns the screen
                elif obs:
                    print(f"[hil] t={t:6.2f}s  state={obs['state']:2d} "
                          f"sw=0x{obs['switch']:02X} aux=0x{obs['aux']:02X} "
                          f"I_cmd={obs['current']:+6.2f}A  faults=0x{obs['fault_flags']:04X} "
                          f"| v={sensors['v_actual']:5.2f} m/s V_bus={sensors['V_bus']:5.2f}V "
                          f"I_fc={sensors['I_fc']:5.2f} I_bt={sensors['I_batt']:5.2f} "
                          f"I_chg={sensors['I_charge']:4.2f} chg=0x{sensors['ag105_status']:02X}"
                          + (f" soc={sensors['soc'] * 100:4.1f}%" if not replay else "")
                          + (f" | elec {electrical.achieved_substep_hz / 1e3:5.1f} kHz "
                             f"({electrical.n_sub_last} sub/tick) ev={elec_events_total}"
                             if electrical is not None else ""))
                else:
                    print(f"[hil] t={t:6.2f}s  no observation frames yet "
                          f"(tx={tx_frames}) — is the board flashed with -DHIL_SIM=1?")

            # ── Drift-corrected scheduling ───────────────────────────────────
            next_tick += dt
            slack = next_tick - time.monotonic()
            if slack > 0:
                time.sleep(slack)
            else:
                overrun = -slack
                max_overrun = max(max_overrun, overrun)
                if overrun > 0.25:
                    # Badly behind (host stall): resynchronize rather than spin
                    # through a burst of catch-up ticks the plant cannot honour.
                    next_tick = time.monotonic()
    except KeyboardInterrupt:
        if dash is not None:
            dash.stop()                 # restore the terminal before printing
            dash_on = False
        run_status = "interrupted"
        print("\n[hil] interrupted")
    except Exception as exc:
        # D6: do NOT finalize here.  The `finally` below still has to drain the
        # last electrical events and CLOSE the CSV, so a sidecar written at this
        # point would claim csv_rows for a file that is not yet flushed to disk
        # — and if the close itself fails, the sidecar would already be on disk
        # asserting a complete record.  Capture the cause and finalize AFTER the
        # teardown, at the single call site below.
        if dash is not None:
            dash.stop()
            dash_on = False
        run_status = "error"
        pending_error = "%s: %s" % (type(exc).__name__, exc)
        raise
    except BaseException:
        # SystemExit / GeneratorExit / anything else that is NOT an Exception
        # (2026-09-02, review M3).  Without this clause `run_status` would
        # still read "running" when the `finally` finalizes, so a sidecar
        # written for a run that was killed mid-flight would be indistinguishable
        # from one still in progress.  The cause is not recorded as an `error`
        # — a SystemExit is a deliberate stop, not a failure — but the run is
        # not "completed" either.
        if dash is not None:
            dash.stop()
            dash_on = False
        run_status = "aborted"
        raise
    finally:
        # EVERY teardown step below is individually guarded (2026-09-02, review
        # M3).  The whole point of the `finally` is that the sidecar gets
        # finalized; a step that raises on its way there — a dashboard restore,
        # a deferred note with a glyph this console cannot encode, an electrical
        # drain — would skip the finalize and reintroduce exactly the defect
        # fix-queue item 1 closed.  A warning on stderr is the right trade: the
        # operator learns the teardown was partial, and the provenance survives.
        def _teardown_step(what, fn):
            try:
                fn()
            except BaseException as _exc:      # noqa: BLE001 - see above
                try:
                    print("[hil] WARNING: teardown step %s failed (%s: %s); "
                          "continuing to the sidecar finalize."
                          % (what, type(_exc).__name__, _exc), file=sys.stderr)
                except BaseException:
                    pass
        if dash is not None:
            _teardown_step("dashboard stop", dash.stop)   # idempotent
            dash_on = False
        for _note in deferred_notes:
            _teardown_step("deferred note", (lambda n=_note: print(n)))
        # M3: final drain so a break/exception on the last tick cannot lose the
        # handful of events accumulated since the previous drain.
        #
        # PART B2 (C1 round, 2026-09-01): close any chopper episode that is
        # still conducting FIRST. From this round a `chopper_clamp` event is
        # appended only when its episode ends (see
        # ElectricalSim.close_chopper_episode), so a run whose last braking
        # window is still open at the final tick would otherwise never emit it.
        if electrical is not None:
            _teardown_step("chopper-episode close",
                           electrical.close_chopper_episode)
        _teardown_step("electrical event drain", _drain_electrical_events)
        if events_file is not None:
            try:
                events_file.close()
            except OSError:
                pass
        if csv_file:
            # D6: guarded like events_file above — a close() that raises here
            # would replace the original exception with an OSError about the
            # log file, losing the actual cause of the failure.
            try:
                csv_file.close()
            except OSError:
                pass
        try:
            sock.close()
        except OSError:
            pass
        if pending_error is not None:
            # The teardown is complete, so this record is accurate.  Wrapped so
            # that a sidecar failure can never replace the exception now
            # propagating out of the `except` clause above.
            try:
                finalize_meta("error", error=pending_error)
            except Exception:
                pass
        else:
            # PROVENANCE BEFORE PRESENTATION (2026-09-02, fix-queue item 1).
            # The sidecar used to be written only at the very END of main(),
            # AFTER every summary print — so an exception in a print (the
            # cp1252 crash in MpcStrategy.summary_line()) discarded the
            # provenance of a run that had already completed 61 000 ticks and
            # written its full CSV: `eta_chg None`, `ems_strategy None`, and
            # two frontier tuples UNVERIFIED on data that was intact on disk.
            # The teardown above is complete at this point (events drained and
            # closed, CSV closed), so the record is accurate here.
            # finalize_meta() rewrites the file, so the tail call below is a
            # harmless refresh with a slightly later `elapsed_s`.
            try:
                finalize_meta(run_status)
            except Exception:
                pass

    elapsed = time.monotonic() - t0
    achieved = ticks / elapsed if elapsed > 0 else 0.0
    print(f"[hil] done: {ticks} ticks in {elapsed:.2f}s -> {achieved:.1f} Hz achieved "
          f"(target {args.rate:.0f} Hz), max overrun {max_overrun * 1e3:.2f} ms")
    print(f"[hil] tx={tx_frames} frames, rx={rx_frames} frames, {rx_bad} malformed, "
          f"send_errors={send_errors}")
    # LOW-7: both observation-frame lengths in one run means the firmware
    # CHANGED UNDER US -- a re-flash mid-run, or two boards answering one
    # host (see _announce_output_length()'s docstring). _OBS_LENGTHS_SEEN is
    # reset at the top of main(), so this reflects only THIS run.
    if len(_OBS_LENGTHS_SEEN) > 1:
        print(f"[hil] *** both observation-frame lengths seen this run "
              f"({sorted(_OBS_LENGTHS_SEEN)} bytes) -- the firmware changed "
              f"mid-run, or two boards answered one host ***")
    # Printed UNCONDITIONALLY (including the 0/0 case) so run_hil_suite.py can
    # parse it deterministically and tell "none observed" apart from "this sim
    # build has no tripwire".
    print(f"[hil] warm resets: {warm_resets} observed, {warm_resets_mid_run} "
          f"mid-run (after {WARM_RESET_GRACE_S:.1f}s)"
          + (f" at t={', '.join('%.3f' % x for x in warm_reset_times)}s"
             if warm_reset_times else ""))
    if warm_resets_mid_run:
        print("[hil] *** the board left its latched State 99 MID-RUN: a host "
              "stall of >= 1 s looks like a run boundary to fw v23+, which then "
              "warm-resets to State 0 and brings the stage back up. From that "
              "point THE REST OF THIS RUN IS NOT THE SCENARIO — the stimulus "
              "timeline kept playing against a board that restarted underneath "
              "it, a re-latched fault reads as having fired once, and any "
              "final-state check reads the post-recovery board. Treat this run "
              "as INCONCLUSIVE unless the scenario expects the recovery "
              "(comm-loss does). ***")
    if commander is not None and commander.active():
        if replay and args.replay_commands:
            print(f"[hil] pi commands sent: {pi_frames} (REPLAYED from "
                  f"{os.path.basename(args.replay)}'s recorded v_sp/share_sp; "
                  f"final v_sp={commander.state['v_setpoint']:.3f} "
                  f"share_sp={commander.state['power_share_setpoint']:.3f}, "
                  f"mode_cmd={commander.state['mode_cmd']})")
            print("[hil] NOTE: --replay-commands replays the COMMANDS only. The "
                  "plant side stayed OPEN LOOP — the injected v_actual never "
                  "responded to them, so this run is evidence about the "
                  "controller's REACTION, not about closed-loop tracking.")
        elif commander.policy is not None:
            print(f"[hil] pi commands sent: {pi_frames} "
                  f"(EMS {commander.policy_name}, {commander.policy_calls} policy "
                  f"evaluations; final v_sp={commander.state['v_setpoint']:.3f} "
                  f"share_sp={commander.state['power_share_setpoint']:.3f})")
        else:
            print(f"[hil] pi commands sent: {pi_frames} "
                  f"(timeline entries applied: {commander.idx}/{len(commander.timeline)})")
    elif args.pi_live:
        print("[hil] PI-LIVE: 0 commands sent by this process (a real Pi owned the "
              "command link)")
    if not replay:
        print(f"[hil] battery: SOC {args.soc0 * 100:.1f}% -> "
              f"{plant.battery.soc * 100:.1f}% "
              f"({args.capacity_ah:g} Ah), V_batt {plant.battery.v_terminal:.3f} V; "
              f"fuel cell {plant.fuel_cell.v_terminal:.3f} V at "
              f"{plant.fuel_cell.i:.3f} A")
        # H2 metric.  The qualifier is not decoration: Gfc is scale-portable by
        # design (H2Consumption banner) but not identified against THIS stack,
        # so the number is the model's estimate pending TODO(calibrate).
        print(f"[hil] H2 (Gfc model estimate — stack uncalibrated): "
              f"{plant.h2.cum_g:.6g} g cumulative, "
              f"final rate {plant.h2.rate_gps:.6g} g/s")
        # The student's axis, on the SAME P_fc input. Printed on its own line
        # with its own model named, so the two totals cannot be read as a
        # measurement and its disagreement.
        print(f"[hil] H2 (student static proxy, eta_fc "
              f"{H2_SDP_PROXY_ETA_FC:g} / Q_LHV "
              f"{H2_SDP_PROXY_Q_LHV_J_PER_G:g} J/g — a DIFFERENT MODEL of the "
              f"same quantity, not a cross-check): {plant.h2.proxy_cum_g:.6g} g "
              f"cumulative")
    # sdp-v2's demand-clamp diagnostics (None unless that strategy ran).
    if commander is not None and commander.policy is not None:
        _sdp_line = getattr(commander.policy, "summary_line", None)
        if _sdp_line is not None:
            _line = _sdp_line()
            if _line:
                print(_line)
    if electrical is not None:
        summ = electrical.summary()
        # M3: electrical.events is trimmed on every drain, so the durable totals
        # for this exit summary are the tracked counters, not summ['events'] /
        # electrical.events (which reflect only whatever has accumulated since the
        # last drain — near-empty on a normal exit).
        print(f"[hil] electrical(hifi): {summ['achieved_substep_hz'] / 1e3:.1f} kHz "
              f"achieved substep rate ({summ['substeps_per_tick']} substeps/tick, "
              f"trace={summ['trace_config']}), {elec_events_total} events")
        if summ.get("numeric_fault"):
            print("[hil] *** numeric_fault: the electrical solve produced a "
                  "non-finite node value at least once this run (see the "
                  "'numeric_fault' events in the sidecar) — treat this run's "
                  "electrical trace as suspect ***")
        if elec_over_absmax:
            print(f"[hil] *** {len(elec_over_absmax)} switching event(s) with an "
                  f"estimated ring peak ABOVE the 20 V abs-max — the boost-death "
                  f"signature; worst "
                  f"{max(e['peak_v'] for e in elec_over_absmax):.2f} V ***")
        if events_path:
            print(f"[hil] {elec_events_total} electrical events -> {events_path}")
    if replay:
        print(f"[hil] replay: {args.replay} at {args.replay_speed:g}x, "
              f"reached record {replay.i}/{len(replay.records) - 1}, "
              f"laps={replay.laps + 1 if args.loop else 1}")
    if args.csv:
        finalize_meta(run_status)
        print(f"[hil] CSV written to {args.csv}")
        print(f"[hil] run metadata ({run_status}) -> {meta_path_for(args.csv)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
