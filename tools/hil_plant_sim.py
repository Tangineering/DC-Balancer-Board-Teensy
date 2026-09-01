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

  Observation frame (Teensy -> host), 16 bytes, little-endian
    0  u8    sync 0xB6
    1  u8    seq echo (last accepted injection seq)
    2  u8    mainState
    3  u8    switch_state bitmask (see SW_* below)
    4  u8    aux: bit0 FC_REG_ENABLE, bit1 BT_REG_ENABLE,
                  bit2 MPPT_DISABLE,  bit3 CBAL_DISABLE
    5  f32   current [A] (post-clamp motor-current command)
    9  u16   last MDAC word, FC channel
   11  u16   last MDAC word, BT channel
   13  u16   fault_flags
   15  u8    XOR checksum over bytes 1..14

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
import os
import socket
import struct
import subprocess
import sys
import time

# ─────────────────────────────────────────────────────────────────────────────
# Protocol constants — must match teensy_controller.ino (fw v21)
# ─────────────────────────────────────────────────────────────────────────────
HIL_SYNC_INJECT = 0xB5
HIL_SYNC_OUTPUT = 0xB6
HIL_INJECT_SIZE = 40
HIL_OUTPUT_SIZE = 16

TEENSY_PORT_DEFAULT = 5001          # local_port in the .ino

SW_FC_BUS, SW_BT_BUS, SW_MOT_PWR = 0x01, 0x02, 0x04
SW_REGEN, SW_FC_CHARGE, SW_BT_SEQ = 0x08, 0x10, 0x20

AUX_FC_REG, AUX_BT_REG = 0x01, 0x02
AUX_MPPT_DISABLE, AUX_CBAL_DISABLE = 0x04, 0x08

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
# TODO(verify) — OPEN OPERATOR QUESTION (R1): whether this board fits an MPPTS
# resistor is UNCONFIRMED.  An off-board MPPTSEL header exists on the schematic;
# its contents are unknown.  With the header open the threshold is the 18 V
# default modelled here.  If a resistor sets a LOWER threshold, this constant and
# the `mppt-tracking` scenario's expectations move TOGETHER — the scenario's
# predicted hunt is contingent on R1, and a campaign that does not see the hunt
# is evidence about R1, not a scenario defect.
AG105_MPPT_V_THRESH = 18.0   # V     input rail above which tracking permits charging
# TODO(verify): chatter guard on the threshold COMPARISON only (not on the pin).
# No datasheet hysteresis figure is published; 0.5 V is a modelling choice sized
# to be well above the simple engine's bus ripple and well below the ~2 V gap
# between the 15.95 V bus and the 18 V threshold, so it cannot decide the
# scenario's outcome either way.
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
K_DROOP_BUS_SHARED = 0.074   # V/A  both sources live
K_DROOP_BUS_SINGLE = 0.16    # V/A  exactly one source live
V_BUS_DROOP_V0 = 15.95       # V    measured no-load intercept
# Back-compatible alias: the shared-source value is the common case.
K_DROOP_BUS = K_DROOP_BUS_SHARED

ETA_BOOST = 0.85         # boost-stage efficiency, motor draw -> bus current
I_AUX_A = 0.15           # A     fixed housekeeping load on the bus
C_BUS_F = 470e-6         # F     bus bulk capacitance (decay when no source is closed)
R_BUS_BLEED = 2000.0     # ohm   effective bleed across that capacitance

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
)
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
CONSTANTS_EXCLUDE_PREFIXES = (
    "META_", "WARM_RESET_", "HIL_SYNC_", "HIL_INJECT_", "HIL_OUTPUT_",
    "TEENSY_PORT", "SW_", "AUX_", "MDAC_CMD_", "CONSTANTS_EXCLUDE",
    "UDP_", "PI_CMD_", "FB_",
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


def parse_output(data: bytes):
    """Validate and decode a 16-byte observation frame; return a dict or None."""
    if len(data) != HIL_OUTPUT_SIZE or data[0] != HIL_SYNC_OUTPUT:
        return None
    if xor_checksum(data[1:HIL_OUTPUT_SIZE - 1]) != data[HIL_OUTPUT_SIZE - 1]:
        return None
    seq, state, sw, aux = data[1], data[2], data[3], data[4]
    (current,) = struct.unpack_from("<f", data, 5)
    mdac_fc, mdac_bt, faults = struct.unpack_from("<HHH", data, 9)
    return {
        "seq": seq,
        "state": state,
        "switch": sw,
        "aux": aux,
        "current": current,
        "mdac_fc": mdac_fc,
        "mdac_bt": mdac_bt,
        "fault_flags": faults,
    }


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
#        double-layer lag modelled in hil_electrical.py:405.  The two are not
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

    def reset(self):
        self.x = [0.0, 0.0, 0.0, 0.0]
        self.rate_gps = 0.0
        self.cum_g = 0.0

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
        the codes only parametrize; proportional-to-code is a SIMPLIFICATION that
        preserves the sign and monotonicity of the share loop's authority (raise the
        FC code, get more FC current) without claiming the true gain.
      * The Ag105 charger is modelled at the STATUS level only: input power in ->
        settle delay -> "Charging" with a first-order current ramp toward the 2.5 A
        configured ceiling.  CV taper exists only as the SoC-triggered Fully-Charged
        branch.  The I2C transport and the config handshake are not modelled at all
        (the firmware skips them entirely under HIL).
      * MPPT: by DEFAULT (`mppt_emulation=False`) MPPT_DISABLE only clears the two
        tracking FLAGS in the status byte and has no effect on charging, which is
        why the pin has never been causally load-bearing in this rig.  With
        `mppt_emulation=True` the part's actual mechanism is modelled at LAYER 1:
        an INPUT-VOLTAGE THRESHOLD (AG105_MPPT_V_THRESH, datasheet p.10), NOT a
        perturb-and-observe tracker — see the constant's banner, including the R1
        open question about the MPPTS resistor.  The tracking DYNAMICS (how the
        module walks its operating point once above the threshold) are still not
        modelled at all.
    """

    def __init__(self, electrical=None, soc0=0.7, capacity_ah=BATT_CAPACITY_AH,
                 ag105_i_max=AG105_I_MAX, mppt_emulation=False):
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
        f_drive = K_F * i_cmd if (mot_live and bus_up) else 0.0
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
        self.v += (f_net / M_EFF) * dt

        # ── Electrical ───────────────────────────────────────────────────────
        # Motor bus draw from mechanical power, through the boost efficiency.
        p_mech = max(0.0, f_drive * self.v)      # regen (negative) is floored at 0 here:
                                                 # the VESC's Battery Regen Max is a torque
                                                 # clip on this rig, not a dump path (see
                                                 # CLAUDE.md 2026-08-17b) — excess energy
                                                 # stays kinetic rather than returning to bus.
        if mot_live and self.v_bus > 1.0:
            i_motor = p_mech / (ETA_BOOST * self.v_bus)
        else:
            i_motor = 0.0
        i_motor += self.i_mot_extra if mot_live else 0.0
        i_total = i_motor + self.i_aux

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
            })
            self.v_bus = rails["V_bus"]
            self.i_fc = rails["I_fc"]
            self.i_batt = rails["I_batt"]
            self.v_chg = rails["V_chg"]
            self.v_rgn = rails["V_rgn"]
            v_fc = rails["V_fc"]
            v_batt = rails["V_batt"]
        else:
            # ── Simple droop node ───────────────────────────────────────────
            if fc_live or bt_live:
                # MEASURED droop, mode-aware: the fit separates cleanly into a
                # both-sources-live regime and a single-source regime (see the
                # K_DROOP_BUS_* constants).  The old single source-agnostic
                # 0.35 V/A placeholder is retired.
                k = K_DROOP_BUS_SHARED if (fc_live and bt_live) else K_DROOP_BUS_SINGLE
                self.v_bus = V_BUS_DROOP_V0 - k * i_total + self.v_bus_offset
                # Share split by droop code ratio (see class docstring for the caveat).
                if fc_live and bt_live:
                    denom = code_fc + code_bt
                    frac_fc = (code_fc / denom) if denom > 1e-9 else 0.5
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
            self.v_rgn = self.v_bus if (sw & SW_MOT_PWR) else 0.0
            chg_fed = bool(sw & SW_FC_CHARGE) or \
                (bool(sw & SW_REGEN) and bool(sw & SW_MOT_PWR))
            self.v_chg = self.v_bus if chg_fed else 0.0

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
            if v_chg_in >= AG105_MPPT_V_THRESH + AG105_MPPT_V_HYST:
                self.mppt_inhibited = False
        elif v_chg_in < AG105_MPPT_V_THRESH:
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
            self.i_charge += (self.ag105_i_max - self.i_charge) * (dt / AG105_TAU_S)
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
    ⚠️ WHAT THE REGEN WINDOWS DO AND DO NOT SHOW (measured 2026-08-30c).  The
                 plant FLOORS regen power at zero (`p_mech = max(0.0, ...)` in
                 Plant.step(); the VESC's Battery Regen Max is a torque clip on this
                 rig, not a dump path — CLAUDE.md 2026-08-17b).  So the energy the
                 Ag105 receives during a braking window is NOT recovered kinetic
                 energy: it is sourced from the BOOSTS, through the bus, via
                 REGEN + MOT_PWR.  This scenario therefore validates the regen
                 POWER PATH and the firmware's branch selection — REGEN high with
                 FC_CHARGE low, MPPT_DISABLE LOW, I_charge delivered through that
                 path — and says NOTHING about energy recovery or round-trip
                 efficiency.  The tell is in the trace: battery SoC DECREASES across
                 a regen window rather than rising.  Do not quote a charge figure
                 from this scenario as harvested energy.
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
    intent     : make MPPT_DISABLE CAUSALLY LOAD-BEARING for the first time.  With
                 `mppt_emulation` on (SCENARIOS["mppt-tracking"]), the plant's
                 Ag105 refuses to charge while tracking is RELEASED and the input
                 rail is below AG105_MPPT_V_THRESH.  The bus is ~15.95 V and the
                 datasheet default threshold is 18 V, so the FC path cannot clear
                 it — and the firmware releases tracking only once the charger
                 reports ready.
    fields     : mode_cmd (SAFE -> HYBRID at EMS_RUN_ENTRY_S, back to SAFE at the
                 scenario's ems_run_exit_s), v_setpoint (the scenario's
                 ems_v_profile), power_share_setpoint (0.50 constant), charge_goal
                 (1.0 inside a BRAKING window or a LOW-CRUISE window, else 0.0).
    feedback   : `fb["t"]`, `fb["v_profile"]` and the scenario's ems_run_exit_s
                 ONLY — portable to the real Pi (FB_TELEMETRY_EQUIV_KEYS).

    ⚠️ THE PREDICTED CLOSED-LOOP BEHAVIOUR IS A HUNT, and it is this model's
    PREDICTION rather than an observation.  Contingent on R1 (see
    AG105_MPPT_V_THRESH): if the board fits an MPPTS resistor setting a threshold
    below the bus voltage, none of this happens and the run harvests normally.

    Under the 18 V default the loop closes like this, at the firmware's own
    50 Hz charger cadence (CHARGING_CTRL_PERIOD_US 20000, and pollAg105() on the
    same 20 ms telemetry gate, .ino:4406-4412):
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
    un-inset plateaus.)

    THE FINDING THIS PREDICTS, if R1 resolves to "no resistor": cruise-time
    harvesting on the FC path CANNOT hold on a 15.95 V bus with MPPT released.
    That is a statement about the HARDWARE, and the point of running it.
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
#                  total JUMPS to the single-source value (~0.34 + the charger's
#                  ~0.8 A stamped draw = ~1.14 A), which is above ENTER: without
#                  hysteresis the policy would immediately withdraw charge_goal
#                  and chatter the path open/closed at 50 Hz.  1.30 A sits
#                  above that steady value and below LIMIT_I_FC_MAX 1.4 A, so
#                  the release doubles as an overcurrent backstop.
#   ⚠️ L9 (review, 2026-08-31) — the "overcurrent backstop" reading holds under
#   `--electrical hifi` ONLY.  It depends on the charger's draw APPEARING in
#   `fb["I_fc"] + fb["I_batt"]`, and only the hi-fi engine stamps it on the bus
#   (hil_electrical.py, `J[N_CHG] -= i_charge`); SIMPLE mode's Plant.step()
#   computes `i_total = i_motor + i_aux` and never charges the sources for it.
#   Under `--electrical simple` the measured total therefore does NOT jump when
#   FC_CHARGE opens, this threshold is never approached, and the release is
#   plain hysteresis with no current guard behind it.  The FIRMWARE's own
#   LIMIT_I_FC_MAX check is unaffected either way — it reads the injected rails.
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

    def __init__(self):
        self.reset()

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
                             and i_tot <= SOC_BAND_CHARGE_EXIT_ITOT_A)
        else:
            self.charging = (deficit_gate and cruising
                             and i_tot <= SOC_BAND_CHARGE_ENTER_ITOT_A)

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
# ⚠️ `aux_preload_a` is a DEMAND INPUT and is deliberately NOT in this tuple —
# adding it would invalidate the shipped tables in tools/dp_tables/.  The
# combination is refused at import instead; see the M4 note just above
# SCENARIO_NAMES for the full reasoning and the condition to revisit it.
DP_FINGERPRINT_META_KEYS = ("ems_v_profile", "duration_s", "chg_i_ceiling_a")



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
        if key == "ems_v_profile" and val:
            val = [(float(a), float(b)) for a, b in val]
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
    def bind_scenario(self, scenario, meta, electrical_mode=None, args=None):
        """Load and validate this scenario's table.  Raises ValueError to refuse.

        main() calls this before the run starts (the generic `bind_scenario`
        hook), so every failure mode surfaces as a startup refusal rather than a
        mid-run crash or, worse, a silently wrong trace.

        `electrical_mode` is the RESOLVED engine ("simple" / "hifi"), not the
        requested one, and `args` the parsed CLI namespace.  Both are optional
        so a caller that only wants the profile check (a test, a future tool)
        keeps working; main() passes both."""
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

        regen = ("      C:/Users/ricky/miniforge3/python.exe "
                 "tools/gen_dp_ems_table.py --scenario %s --force" % scenario)

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
                ("chg_ceiling_a",
                 float(meta.get("chg_i_ceiling_a", AG105_I_MAX)),
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
                ("charge_share_value",
                 float(SOC_BAND_SHARE_NOMINAL + SOC_BAND_SHARE_SPAN),
                 "DP charge-stage share "
                 "(= SOC_BAND_SHARE_NOMINAL + SOC_BAND_SHARE_SPAN)"),
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
# I_AUX_A.  DERIVATION — it exists to keep the firmware's share loop closed:
#   * The governor arms the closed share loop only above 2*SHARE_MINORITY_I_MIN_A
#     = 0.60 A of measured source total.  Without a preload the 'Y' table's own
#     load spans 0.150-1.407 A (measured against the Plant/droop model at
#     Vmax 3) and sits BELOW the gate through every standstill and low-speed
#     region — a share-tracking assertion there would be measuring feedforward.
#   * With +0.60 A the total spans 0.750-2.011 A, i.e. above the gate for the
#     WHOLE table including its standstill regions (the binding case is
#     I_AUX_A 0.15 + 0.60 = 0.750 A, 25 % clear of the gate).
#   * Headroom: the worst per-channel current is FC at region 4's entry, where
#     the table commands share 0.65 on a Vmax-3 load — 0.836 A against
#     LIMIT_I_FC_MAX 1.4 A, a 40 % margin.  At Vmax 1 the same point is 0.565 A.
# ⚠️ These are the MODEL's currents (M_EFF/K_F/F_COULOMB/B_EFF + the droop bus,
# constants at the top of this file), not measurements. A campaign that misses
# the fc_current_biased check should move THIS number, never the check.
Y_AUX_LOAD_A = 0.60


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
#             Vmax-1 variant's source total never reaches the 0.60 A governor
#             gate, so its share loop runs OPEN-LOOP FEEDFORWARD for the whole
#             run. That is correct for a topology test and wrong for a tracking
#             one — do not read share-tracking numbers off a b00 run.
#   Vmax 1 / 3  the low and high ends of the drive channel's exercised range
#             (3.0 m/s is ML0169's measured hold, CLAUDE.md fw v16).
ems_y_b30_v1 = make_ems_y(1.0, 0.30)
ems_y_b30_v3 = make_ems_y(3.0, 0.30)
ems_y_b00_v1 = make_ems_y(1.0, 0.00)
ems_y_b00_v3 = make_ems_y(3.0, 0.00)


EMS_STRATEGIES = {
    "hold-5050": ems_hold_5050,
    "regen-harvest": ems_regen_harvest,
    # `regen-harvest` plus FC-path charge windows at low cruise, for the
    # `mppt-tracking` scenario.  A SEPARATE function, deliberately: charge-regen's
    # measurements are pinned across five campaigns and must not move because
    # this scenario's windows did.  See ems_mppt_harvest().
    "mppt-harvest": ems_mppt_harvest,
    # ⚠️ SIM-ONLY: soc-band closes on fb["soc"], which is PLANT TRUTH and is NOT
    # in FB_TELEMETRY_EQUIV_KEYS — it is not portable to a real Pi without a
    # V_batt-based SoC estimator (future work).  See the banner above the class.
    "soc-band": ems_soc_band,
    # ⚠️ NON-CAUSAL / OFFLINE-OPTIMAL BENCHMARK, not a controller and not
    # portable to any Pi: it replays a table computed offline with full
    # foreknowledge of ONE drive cycle.  Refuses at startup against any other
    # profile.  See the banner above DpReplayStrategy.
    "dp-replay": ems_dp_replay,
    # The firmware's own 'Y' combined drive-cycle + power-share table (16
    # regions, 40 s), commanded from the EMS layer instead of the USB console.
    # All four read ONLY fb["t"] and the scenario's ems_run_exit_s, so all four
    # are portable to a real Pi.  See make_ems_y() and the banner above it.
    "y-b30-v1": ems_y_b30_v1,
    "y-b30-v3": ems_y_b30_v3,
    "y-b00-v1": ems_y_b00_v1,
    "y-b00-v3": ems_y_b00_v3,
}

EMS_NAMES = list(EMS_STRATEGIES)


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
#                THRESHOLD (AG105_MPPT_V_THRESH, datasheet p.10), so
#                MPPT_DISABLE becomes causally load-bearing instead of a
#                flag-only control.  ABSENT/False is the default and leaves the
#                charger branch byte-identical, which is why every pre-2026-08-31
#                scenario is unaffected.  See Plant.__init__ and the constant's
#                banner (incl. the R1 open question).
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
        # (the plant floors regen power at 0).  Budget against LIMIT_I_FC_MAX
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
        #     charger ceiling                           0.800 A
        #                                        total  1.139 A  -> 19 % margin
        # The charger term is deliberately the SIM's stamped draw, which is the
        # Ag105 OUTPUT current placed on the VCHG node (hil_electrical.py:1256) and
        # therefore ~1.47x the physical input draw (HIL_FINDINGS "charge-cruise",
        # sim defect 1 — OUT OF SCOPE here).  Budgeting against the overstated
        # number is the conservative direction: fixing that defect can only lower
        # the FC current, never raise it.
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
# THE PRELOAD, and the trade-off it forces.  FTP75_PRELOAD_A is 0.65 A:
#   * WHY IT IS THERE. Measured against the Plant/droop model over the whole
#     segment, the cycle's own load leaves the source total below the 0.60 A
#     governor gate through every idle segment, and the FTP is roughly a third
#     idle. With +0.65 A the total is 0.800 A at standstill — 33 % above the
#     gate — and 100.00 % of the post-ramp run (t >= 7.5 s) is above it, so the
#     share loop is genuinely CLOSED for the whole cycle.
#   * HEADROOM. Peak source total is 1.613 A at t = 245 s (the cycle peak);
#     at hold-5050's 0.50 split that is 0.807 A per channel, 42 % under
#     LIMIT_I_FC_MAX 1.4 A. Under `soc-band`, whose share ceiling is 0.75, the
#     same peak is 1.210 A — 14 % of margin left, which is why that scenario's
#     suite entry ALLOWS OC_FC (see run_hil_suite.py FAULT_EXPECTATIONS).
#   * ⚠️ WHAT IT COSTS. `soc-band` admits a charge window only below
#     SOC_BAND_CHARGE_ENTER_ITOT_A = 0.60 A of source total, and the preload
#     puts the FLOOR at 0.800 A. The preload therefore FORECLOSES the charge
#     window on ems-ftp75-socband, by construction: that scenario exercises the
#     policy's share-bias branch over a long cycle, NOT its charging branch
#     (`ems-soc-band` remains the home of the charge-window assertion). Stated
#     here rather than discovered from a trace with no charge in it.
#   * These are the MODEL's currents (M_EFF/K_F/F_COULOMB/B_EFF and the droop
#     bus), not measurements. A campaign that misses a share-tracking check
#     should move THIS number, never the check.
FTP75_PRELOAD_A = 0.65
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
    ("ems-ftp75-socband", "soc-band",
     "the causal charge-sustaining policy over a long cycle: the SoC deficit "
     "walks the split toward the fuel cell. Its CHARGING branch is out of "
     "reach here by construction — see FTP75_PRELOAD_A"),
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

# gen_dp_ems_table.py note: a DP table for an FTP-75 scenario is FUTURE WORK.
# The solver's cost is stage-count-dominated and this cycle is ~6x the length
# of `ems-dp-replay`'s (~21 min offline, measured 2026-08-31), so it is a
# deliberate deferral rather than a gap. Nothing blocks it: the generator's
# demand model already reads `aux_preload_a` through
# scenario_aux_preload_a(), and its --run-exit already resolves from
# `ems_run_exit_s`, so a table can be generated whenever the run time is worth
# paying.

# ── mppt-tracking: the Ag105 MPPT input-voltage threshold, closed-loop ──────
#
# THE FIRST SCENARIO IN WHICH MPPT_DISABLE DOES ANYTHING.  Everywhere else in
# this suite the pin only sets two flags in the status byte, so nothing the
# firmware does with it can be validated.  Here `mppt_emulation` turns on the
# part's real mechanism — an INPUT-VOLTAGE THRESHOLD, 18 V by default with MPPTS
# open (AG105_Silvertel.pdf p.10; NOT perturb-and-observe, see the
# AG105_MPPT_V_THRESH banner) — and the pin becomes causal.
#
# ⚠️ THIS SCENARIO ASSERTS A PREDICTION, not a previously-observed behaviour, and
# the prediction is CONTINGENT ON R1 (does this board fit an MPPTS resistor?).
# Under the 18 V default the firmware and the module HUNT: the firmware releases
# tracking only once the charger reports ready, and releasing it is exactly what
# stops the charging that made it ready.  The full loop trace and the ~40 ms
# period are derived in ems_mppt_harvest()'s docstring.  A campaign that does NOT
# see the hunt is evidence about R1 — a lower threshold set by a fitted resistor
# — and must be read as a hardware finding, not as a scenario defect.
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
                    "INPUT-VOLTAGE THRESHOLD emulated (18 V default, datasheet "
                    "p.10): charge_goal is asserted on the braking windows (regen "
                    "path, MPPT inhibited) AND on the low-cruise plateaus (FC "
                    "path, MPPT released) — where the 15.95 V bus cannot clear "
                    "the threshold, so the firmware and the module are predicted "
                    "to HUNT. Contingent on R1 (MPPTS resistor unconfirmed)."),
    # "any": the threshold gate is a comparison against the charger's input rail,
    # which both engines produce.  ⚠️ In SIMPLE mode V_chg is rigidly V_bus
    # whenever a charger path is closed (no series impedance, no charger draw
    # pulling the rail down), so the threshold sees a stiffer rail than the hi-fi
    # engine's.  Both are far below 18 V, so the verdict is the same either way —
    # but do not read a MARGIN to the threshold off a simple-mode run.
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
# ⚠️ mppt_emulation IS DELIBERATELY OFF HERE.  With it on, the 18 V threshold
# would block charging on this very path and the run could never reach FULL —
# the two scenarios test different things and must not be merged.  `mppt-tracking`
# owns the threshold gate; this one owns the FULL/CV path.
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

# ── M4 (review 2026-08-31): the one key that is a DEMAND INPUT and is NOT in the
# fingerprint.  `aux_preload_a` is applied by apply_scenario()'s generic
# fall-through branch and changes the bus load the DP solved against just as
# surely as `ems_v_profile` does — so a `dp-replay` scenario that declared one
# would be pinned to a fingerprint that does not cover its own demand, and the
# guard would happily accept a table generated for a different load.
#
# IT IS NOT IN DP_FINGERPRINT_META_KEYS ON PURPOSE, and that is future work
# rather than an oversight: adding a key changes the canonical string
# dp_profile_fingerprint() hashes, which invalidates the SHIPPED table in
# tools/dp_tables/ and costs a ~21 min regeneration.  There is exactly one
# dp-replay scenario today and it declares no preload, so the key would buy
# nothing.  Add it — and regenerate — when a SECOND DP scenario lands.
#
# Until then, refuse the combination at import so the gap cannot be reached
# silently.  This is deliberately checked against the SCENARIOS registry rather
# than inside dp_profile_fingerprint(): the function is also called by
# tools/gen_dp_ems_table.py, and a startup refusal there would read as a
# generator bug rather than as a registry one.
for _dpn, _dpm in SCENARIOS.items():
    if _dpm.get("ems") == "dp-replay":
        assert "aux_preload_a" not in _dpm, (
            "SCENARIOS[%r] is a dp-replay scenario AND declares `aux_preload_a`. "
            "That key is a DEMAND INPUT the DP solves against, but it is not in "
            "DP_FINGERPRINT_META_KEYS (see the note there), so the table guard "
            "would not notice a preload change. Either add the key to "
            "DP_FINGERPRINT_META_KEYS and REGENERATE every table in "
            "tools/dp_tables/ (~21 min), or express the load through a branch "
            "apply_scenario() already fingerprints (the SOC_BAND_DRAIN_* "
            "constants)." % _dpn)
del _dpn, _dpm

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
# 20 % above V_MOT_LOAD_FLOOR (hil_electrical.py:197, 1.0 V) — high enough that
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
    elif scenario in ("ems-soc-band", "ems-dp-replay"):
        # BOTH names, deliberately: `ems-dp-replay` is the same cycle and the
        # same drain driven by the offline-optimal table instead of the causal
        # policy, and the comparison is only meaningful if the load is
        # bit-identical.  See the SCENARIOS["ems-dp-replay"] note.
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


def main(argv=None):
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

    electrical = None
    if args.electrical == "hifi" and not args.replay:
        c_vesc = (args.vesc_cap_uf * 1e-6) if args.vesc_cap_uf is not None \
            else meta.get("vesc_cap_f", C_VESC_DEFAULT)
        electrical = ElectricalSim(
            trace_config=args.trace_config,
            noise=NoiseConfig() if args.noise else None,
            c_vesc_f=c_vesc)
        print(f"[hil] electrical=hifi trace={args.trace_config} "
              f"C_vesc={c_vesc * 1e6:.0f} uF noise={'on' if args.noise else 'off'}")
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
              f"(tracking released) and V_chg < {AG105_MPPT_V_THRESH:.1f} V "
              f"(+{AG105_MPPT_V_HYST:.1f} V hysteresis). Datasheet p.10 default; "
              f"TODO(verify) R1 — MPPTS resistor unconfirmed.")
    plant = Plant(electrical=electrical, soc0=args.soc0,
                  capacity_ah=args.capacity_ah, ag105_i_max=chg_ceiling,
                  mppt_emulation=mppt_emu)
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
                           args=args)
                except (ValueError, OSError) as exc:
                    ap.error("--ems %s cannot run scenario '%s':\n%s"
                             % (ems_name, scenario, exc))
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
                header_row += ["elec_substep_hz", "elec_events"]
            # APPEND-only, and UNCONDITIONAL in simulated-plant mode: the two
            # command columns are present for EVERY simulated run, not only under
            # --ems. Column presence must not vary with a flag inside one mode, or
            # nothing downstream can parse "a simulated-mode CSV" without first
            # knowing which flags produced it. They are BLANK when no commander
            # exists (--pi-live: the real Pi's commands are not observable here).
            # Replay mode's schema is untouched — `replay_rec` keeps its index.
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
        keep an ever-growing in-memory copy for the life of a long run."""
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
                "blg_fw_version": blg_header.get("fw_version"),
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
                "vesc_cap_f": (getattr(electrical, "c_vesc", None)
                               if electrical is not None else None),
                "noise": bool(args.noise),
                "soc0": args.soc0,
                "capacity_ah": args.capacity_ah,
                "chg_i_ceiling_a": chg_ceiling,
                "replay_preamble_s": replay_preamble_s if args.replay else None,
                "replay_i_fc_clamp_a": args.replay_i_fc_clamp,
                "replay_commands": bool(args.replay_commands) if args.replay else None,
                "dash": bool(args.dash),
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
                    if replay_derive_v_rgn or args.replay_i_fc_clamp is not None:
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
                    "state": obs["state"] if obs else None,
                    "switch": obs["switch"] if obs else None,
                    "aux": obs["aux"] if obs else None,
                    "I_cmd": obs["current"] if obs else None,
                    "faults": obs["fault_flags"] if obs else 0,
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
                             f"({electrical._n_sub} sub/tick) ev={elec_events_total}"
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
    finally:
        if dash is not None:
            dash.stop()                 # idempotent
            dash_on = False
        for note in deferred_notes:
            print(note)
        # M3: final drain so a break/exception on the last tick cannot lose the
        # handful of events accumulated since the previous drain.
        _drain_electrical_events()
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

    elapsed = time.monotonic() - t0
    achieved = ticks / elapsed if elapsed > 0 else 0.0
    print(f"[hil] done: {ticks} ticks in {elapsed:.2f}s -> {achieved:.1f} Hz achieved "
          f"(target {args.rate:.0f} Hz), max overrun {max_overrun * 1e3:.2f} ms")
    print(f"[hil] tx={tx_frames} frames, rx={rx_frames} frames, {rx_bad} malformed, "
          f"send_errors={send_errors}")
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
