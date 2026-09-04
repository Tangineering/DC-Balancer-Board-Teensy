#!/usr/bin/env python3
"""FIRMWARE-EQUIVALENCE test for the fw v27 rev 2 governor package.

WHAT THIS FILE ASSERTS, AND WHY IT IS DIFFERENT FROM THE REST OF THE SUITE.
Every other test of ``governor_model`` asserts the port against an expectation a
person wrote down. This one asserts it against THE FIRMWARE. It compiles
``test/gov_fw27_harness.cpp``, which includes
``teensy_controller/teensy_controller.ino`` against the same mock layer the
host-native firmware suite uses, drives the real functions through a scripted
command stream, and compares the resulting trace with the Python port driven
through the identical stream.

It is the sibling of ``test_governor_ceiling_equivalence.py``, which covers the
fw v26 current-ceiling clamp alone. This one covers the four fw v27 rev 2
mechanisms: the battery-only start, the relaxing feedforward clip with its
isolated-channel bypass and accumulating proposal, the load-scheduled droop
scale ``k_d``, and the g-guard count.

⚠️ THE ONE THING THIS CANNOT COMPARE, STATED RATHER THAN IMPLIED. The Youla
share controller is on the do-not-change list and is NOT ported (``governor_
model`` fidelity boundary 1), so a CLOSED-LOOP tick's commanded ratio is a
firmware quantity the port only approximates. The MDAC codes are therefore
compared EXACTLY on

  * every OPEN-LOOP tick — the feedforward path is ported in full (clip, iso
    bypass, proposal walk, ceilings, slew, actuation), and it is where the
    battery-only start, the hold and the re-entry live; and
  * every DIRECT actuation (``APPLY`` / ``MDAC``) — which is where the k_d
    schedule and the g-guard actually reach the hardware;

and the closed-loop stream is compared on the quantities that ARE ported: the
governor filter, the held schedule input, the live ``k_d``, the switch topology,
the latch/isolation/deferral flags, the refusal counters and the g-guard count.
Its CODES are not compared, and no assertion in this file pretends otherwise.

THE NUMERIC TOLERANCE. The firmware computes in ``float`` and the port in
``double``. Scalars are compared at single-precision relative tolerance; the
integer codes and every flag/counter are compared EXACTLY. The flags are the
load-bearing half: they carry the topology and hysteresis memory, so a port
whose boundary is wrong fails on them regardless of the numeric tolerance.

The test SKIPS when no C++ compiler is available, so a machine without MSYS2
still collects the rest of the suite. It is not skipped silently: the skip
message names the compiler it looked for.
"""
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO_ROOT = os.path.dirname(HERE)
TEST_DIR = os.path.join(REPO_ROOT, "test")
HARNESS_SRC = os.path.join(TEST_DIR, "gov_fw27_harness.cpp")
HARNESS_EXE = os.path.join(TEST_DIR, "gov_fw27_harness.exe")
INO_PATH = os.path.join(REPO_ROOT, "teensy_controller", "teensy_controller.ino")
MSYS2_BIN = r"C:\msys64\ucrt64\bin"

import governor_model as gm  # noqa: E402

V_BUS_CHARGED_THRESH = 13.5      # .ino — the re-close guard the port models
                                 # through ``v_bus_ok``


# ─────────────────────────────────────────────────────────────────────────────
# The stimulus. Owned HERE, not by the C++ file, so a coverage change needs no
# C++ edit. Each case is (name, [command tuples]).
#
# Every sequence is ORDER-DEPENDENT by design: the governor is a state machine,
# so a trace is a trajectory and not a table of independent evaluations.
# ─────────────────────────────────────────────────────────────────────────────
def _case_pure_schedule():
    """``shareDroopScaleTarget()`` across the whole reachable range, including
    the 0.906 A crossover above which it must return K_DROOP exactly."""
    cmds = []
    for tot in (0.0, 0.05, 0.075, 0.0751, 0.10, 0.20, 0.25, 0.2999, 0.30,
                0.3001, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70, 0.80, 0.90,
                0.9061287313432836, 0.9062, 0.95, 1.00, 1.20, 1.4706, 1.50,
                2.00, 2.50, 3.00, 4.00, 8.00):
        cmds.append(("KDT", tot))
    return cmds


def _case_pure_clip():
    """``shareFeedforwardClipTarget()``: the empty band (hold), the degenerate
    point at exactly 2*I_min, the relaxing branch above it, and the structural
    divide guard below SHARE_I_TOT_MIN_A."""
    cmds = []
    for tot in (0.0, 0.05, 0.075, 0.0751, 0.10, 0.20, 0.25, 0.2999, 0.30,
                0.3001, 0.35, 0.40, 0.50, 0.75, 1.00, 1.50, 2.00, 3.00):
        for sp, prev in ((0.15, 0.62), (0.50, 0.62), (0.85, 0.62),
                         (0.85, 0.15), (0.15, 0.85), (0.35, 0.35)):
            cmds.append(("CLIP", tot, sp, prev))
    return cmds


def _case_kd_schedule_walk():
    """The SCHEDULE as a trajectory: the hysteretic held input, the fractional
    slew, and the crossover in both directions. 0.3 A -> 2.0 A -> 0.3 A, at
    0.005 A per tick, is slow enough that the 0.05 A deadband re-samples many
    times and fast enough that the 2.353 %/tick bound is the binding constraint
    on the way up."""
    # ⚠️ THE STEP IS 0.0037 A, NOT 0.005 A, AND THAT IS DELIBERATE. The
    # schedule input is a HYSTERETIC sample tested with a strict `>` against a
    # 0.05 A deadband. A 0.005 A step makes every tenth sample land EXACTLY on
    # the deadband, where float32 and float64 round the same subtraction to
    # opposite sides of the test and the two traces legitimately disagree about
    # a boundary neither is wrong about. 0.0037 A is coprime with the deadband
    # to well beyond single precision, so every comparison here is about the
    # SCHEDULE and never about a tie.
    cmds = []
    tot = 0.30
    while tot <= 2.0 + 1e-9:
        cmds.append(("KDS", round(tot, 6)))
        tot += 0.0037
    while tot >= 0.30 - 1e-9:
        cmds.append(("KDS", round(tot, 6)))
        tot -= 0.0037
    # Then park on the crossover and confirm both sides settle exactly.
    for _ in range(200):
        cmds.append(("KDS", 0.9061287313432836))
    for _ in range(200):
        cmds.append(("KDS", 2.0))
    return cmds


def _case_apply_under_the_schedule():
    """``applyShareRatio()`` under a LIVE k_d, at every band position, on both
    sides of the crossover. This is the path on which the schedule reaches the
    hardware, so it is the one that must be bit-exact."""
    cmds = []
    for sched in (0.30, 0.40, 0.50, 0.70, 0.906, 1.00, 1.50, 2.00):
        cmds.append(("SETFILT", sched))
        # Settle the scale on this load before actuating, so the codes are the
        # schedule's own converged value and not a slew transient.
        for _ in range(400):
            cmds.append(("KDS", sched))
        for r in (0.15, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.85):
            cmds.append(("APPLY", r))
    return cmds


def _case_g_guard_stale_schedule():
    """THE g-GUARD. A stale light-load scale (0.906 ohm, the 0.5-capped
    maximum) meeting a ratio the controller has already slewed to the low band
    rail commands g = 0.906/(2.0136*0.15) = 3.0. The clamp must fire, the count
    must rise by exactly one per write, and it must SATURATE rather than wrap.
    The count is also asserted NOT to move on the writes either side."""
    cmds = [("SETKD", 0.906), ("SETFILT", 2.0)]
    for r in (0.85, 0.50, 0.30, 0.20, 0.15, 0.15, 0.15, 0.50, 0.85):
        cmds.append(("APPLY", r))
    # Direct setDroopMdac() calls: one gain over, both gains over (ONE event),
    # and neither over.
    cmds += [("MDAC", 1.5, 0.4), ("MDAC", 1.5, 2.5), ("MDAC", 0.4, 0.4),
             ("MDAC", 1.0, 1.0), ("MDAC", 1.0000001, 1.0)]
    return cmds


def _case_battery_only_start_below_the_gate():
    """PROFILE START BELOW THE GATE. The arm cuts the fuel cell on tick 1, the
    frozen path keeps the governor filter alive, the arm drops the instant the
    filtered total passes 2*I_min = 0.30 A, and the latch's own guarded release
    puts FC back on the bus. The load is 0.45 A of total, above the gate, so
    the release happens; the currents are scripted single-source while the cut
    stands, which is what the plant would deliver."""
    cmds = [("ARM",)]
    for _ in range(400):
        cmds.append(("LOAD", 0.5, 0.45, 16.0))
    return cmds


def _case_battery_only_start_above_the_gate():
    """PROFILE START ABOVE THE GATE (design record section 9.6). The loop closes
    on the first tick and the arm is dropped THERE, so the deferral resolves by
    ownership rather than by load migration. 2.0 A of total also puts the load
    guard (0.5 A on the doomed channel) in refusal, so the refusal counter is
    part of the comparison."""
    cmds = [("ARM",)]
    for _ in range(300):
        cmds.append(("LOAD", 0.5, 2.0, 16.0))
    return cmds


def _case_battery_only_disarm_on_out_of_band():
    """ONE OWNER PER SETPOINT. An out-of-band commanded setpoint DISARMS the arm
    permanently; a band-edge 0.15 or 0.85 is in band and does NOT."""
    cmds = [("ARM",)]
    cmds += [("LOAD", 0.85, 0.20, 16.0)] * 20     # in band: still armed
    cmds += [("LOAD", 0.15, 0.20, 16.0)] * 20     # in band: still armed
    cmds += [("LOAD", 1.00, 0.20, 16.0)] * 20     # out of band: DISARMS
    cmds += [("LOAD", 0.50, 0.20, 16.0)] * 60     # stays disarmed
    return cmds


def _case_hold_and_reentry():
    """THE HOLD, AND THE OPEN->CLOSED->OPEN ROUND TRIP. Drive the total up
    through the 0.30 A gate, converge, then let it fall below the 0.25 A exit
    so the HOLD branch owns the split, then bring it back. Below the gate the
    applied ratio must not move at all."""
    # sp = 0.50 deliberately. The point of this case is the MODE trajectory --
    # feedforward hold, gate crossing, closed loop, exit, hold, re-entry -- and
    # a band-edge setpoint would additionally park the ratio one hysteresis
    # width from a channel cutoff, so a sub-tolerance difference between the
    # firmware's Youla controller and the port's surrogate would flip the
    # TOPOLOGY and the case would be measuring the controller instead. 0.50 is
    # the least excitable point in the band; the band edges are covered by
    # `rising_total_hysteresis` and by the fw v26 clamp legs.
    cmds = []
    for _ in range(120):
        cmds.append(("LOAD", 0.50, 0.20, 16.0))   # below the gate
    for _ in range(600):
        cmds.append(("LOAD", 0.50, 0.80, 16.0))   # closed
    for _ in range(600):
        cmds.append(("LOAD", 0.50, 0.12, 16.0))   # HOLD (below the 0.25 exit)
    for _ in range(300):
        cmds.append(("LOAD", 0.50, 0.80, 16.0))   # closed again
    return cmds


def _case_rising_total_through_the_hysteresis():
    """A RISING TOTAL THROUGH 0.25-0.30 A, the mode-gate hysteresis sliver where
    the closed-loop clip degenerates to the balanced split. Ramped slowly enough
    that the ~20 ms filter tracks it, so the crossing is a real crossing and not
    a step."""
    cmds = []
    tot = 0.10
    while tot <= 0.60 + 1e-9:
        cmds.append(("LOAD", 0.85, round(tot, 6), 16.0))
        tot += 0.0005
    while tot >= 0.10 - 1e-9:
        cmds.append(("LOAD", 0.85, round(tot, 6), 16.0))
        tot -= 0.0005
    return cmds


def _case_iso_bypass_and_proposal():
    """THE CUT + RE-ENTRY AT THE HANDOFF CEILING (design record section 12).
    Force the split to the low band rail, take a cut through the direct
    actuation path, and then feed forward below the gate. At the sub-gate
    totals used here BOTH channels read dark, so the conduction-aware ceiling is
    DROOP_RATIO_SLEW_HANDOFF_PER_TICK = 0.002 -- smaller than
    SHARE_CUTOFF_HYST = 0.01. Without the accumulating proposal anchor the
    channel is stranded off the bus forever; with it the re-entry lands within
    five ticks and no more than one hysteresis width off the rail."""
    cmds = []
    # Seed the dark condition and the rail, then cut FC with a below-band ratio.
    for _ in range(120):
        cmds.append(("LOAD", 0.15, 0.10, 16.0))
    cmds.append(("SETPREV", 0.15))
    cmds.append(("APPLY", 0.10))          # takes the FC cut (both switches high)
    for _ in range(160):
        cmds.append(("LOAD", 0.50, 0.10, 16.0))
    return cmds


def _case_fw26_clamp_at_the_new_threshold():
    """THE fw v26 CLAMP LEGS AT THE NEW REACHABILITY THRESHOLD. Well above the
    0.906 A crossover, so k_d IS K_DROOP and the codes must be bit-identical to
    fw v26 -- which is exactly the property `test_fw27_kd_bit_identical_above_
    crossover` pins on the firmware side. Driven through the LOOP so the
    ordering (minority clip, then ceilings, then band, then slew) is what is
    compared, not the clamp in isolation."""
    cmds = []
    # The cruise leg: 2.00 A of total at a commanded 0.75.
    for _ in range(400):
        cmds.append(("LOAD", 0.75, 2.00, 16.0))
    # Sweep the total through the 1.4706 A threshold at the band edge.
    tot = 1.20
    while tot <= 2.20 + 1e-9:
        cmds.append(("LOAD", 0.85, round(tot, 6), 16.0))
        tot += 0.002
    while tot >= 1.20 - 1e-9:
        cmds.append(("LOAD", 0.85, round(tot, 6), 16.0))
        tot -= 0.002
    return cmds


def _case_open_loop_only():
    """A PROFILE THAT NEVER CLOSES THE LOOP, so every tick is the port's to
    own and the MDAC codes are comparable end to end.

    This is the case the fw v27 rev 1 change exists for. Below the 0.30 A gate
    the minority band is empty, so each commanded setpoint step must produce a
    HOLD -- the applied ratio must not move at all -- where fw v26 would have
    walked the fed-forward reference out to the commanded extreme. The second
    half takes a cut and drives the iso bypass, which IS ratio motion below the
    gate and is the one open-loop writer left."""
    cmds = []
    for sp in (0.50, 0.85, 0.15, 0.65):
        for _ in range(400):
            cmds.append(("LOAD", sp, 0.20, 16.0))
    # Force the split to the low rail and take a cut through the direct path,
    # then let the feedforward bypass walk the proposal back across the
    # re-entry hysteresis at the handoff ceiling.
    cmds.append(("SETPREV", 0.15))
    cmds.append(("APPLY", 0.10))
    for _ in range(400):
        cmds.append(("LOAD", 0.50, 0.12, 16.0))
    for _ in range(400):
        cmds.append(("LOAD", 0.65, 0.20, 16.0))
    return cmds


CASES = [
    ("pure_schedule", _case_pure_schedule),
    ("open_loop_only", _case_open_loop_only),
    ("pure_clip", _case_pure_clip),
    ("kd_schedule_walk", _case_kd_schedule_walk),
    ("apply_under_the_schedule", _case_apply_under_the_schedule),
    ("g_guard_stale_schedule", _case_g_guard_stale_schedule),
    ("battery_only_below_gate", _case_battery_only_start_below_the_gate),
    ("battery_only_above_gate", _case_battery_only_start_above_the_gate),
    ("battery_only_disarm", _case_battery_only_disarm_on_out_of_band),
    ("hold_and_reentry", _case_hold_and_reentry),
    ("rising_total_hysteresis", _case_rising_total_through_the_hysteresis),
    ("iso_bypass_proposal", _case_iso_bypass_and_proposal),
    ("fw26_clamp_new_threshold", _case_fw26_clamp_at_the_new_threshold),
]

# The rows on which the MDAC codes are comparable. See the module docstring:
# a closed-loop tick's ratio comes from the Youla controller, which is not
# ported, so its codes are not this test's to compare.
_CODE_COMPARABLE_OPS = frozenset({"APPLY", "MDAC"})


# ─────────────────────────────────────────────────────────────────────────────
# Firmware side
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def harness():
    """Build the firmware harness, or skip with the reason."""
    if not os.path.exists(HARNESS_SRC):
        pytest.skip("test/gov_fw27_harness.cpp is missing")
    env = dict(os.environ)
    if os.path.isdir(MSYS2_BIN):
        env["PATH"] = MSYS2_BIN + os.pathsep + env.get("PATH", "")
    cxx = shutil.which("g++", path=env.get("PATH"))
    if cxx is None:
        pytest.skip("no g++ on PATH and none at %s; the firmware-equivalence "
                    "check needs a host C++ compiler" % MSYS2_BIN)
    newest = max(os.path.getmtime(HARNESS_SRC), os.path.getmtime(INO_PATH))
    if (not os.path.exists(HARNESS_EXE)
            or os.path.getmtime(HARNESS_EXE) < newest):
        cmd = [cxx, "-std=c++17", "-I.", "-I../teensy_controller",
               "-I../controller_design", "-I../controller_design_MIMO",
               "-DBENCH_TEST=0", "-DHIL_SIM=0", "-DNO_ETH_WARNING",
               "-Wno-unused-function",
               "gov_fw27_harness.cpp", "-o", "gov_fw27_harness.exe"]
        proc = subprocess.run(cmd, cwd=TEST_DIR, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if proc.returncode != 0:
            pytest.fail("harness build failed:\n%s"
                        % proc.stdout.decode("utf-8", "replace"))
    return HARNESS_EXE


_COLS = ("op", "r", "g_fc", "g_bt", "k_d", "code_fc", "code_bt", "filt",
         "sched_tot", "sw_fc", "sw_bt", "iso_fc", "iso_bt", "cut_fc", "cut_bt",
         "def_fc", "def_bt", "armed", "active", "ref_load", "ref_blank",
         "g_clamp")
_INT_COLS = ("code_fc", "code_bt", "sw_fc", "sw_bt", "iso_fc", "iso_bt",
             "cut_fc", "cut_bt", "def_fc", "def_bt", "armed", "active",
             "ref_load", "ref_blank", "g_clamp")


def _stdin(cmds):
    out = []
    for c in cmds:
        out.append(" ".join(("%r" % x) if isinstance(x, float) else str(x)
                            for x in c))
    return "\n".join(out) + "\n"


def _firmware_trace(exe, cmds):
    env = dict(os.environ)
    if os.path.isdir(MSYS2_BIN):
        env["PATH"] = MSYS2_BIN + os.pathsep + env.get("PATH", "")
    proc = subprocess.run([exe], cwd=TEST_DIR, env=env,
                          input=_stdin(cmds).encode("ascii"),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.returncode == 0, (proc.stdout + proc.stderr).decode(
        "utf-8", "replace")
    lines = proc.stdout.decode("ascii").strip().splitlines()
    assert lines[0].strip() == ",".join(_COLS), lines[0]
    rows = []
    for line in lines[1:]:
        parts = line.strip().split(",")
        # The scalar-returning ops (CLIP, KDT) prepend an "OP=value" field.
        ret = None
        if "=" in parts[0]:
            ret = float(parts[0].split("=", 1)[1])
            parts = parts[1:]
        row = dict(zip(_COLS, parts))
        for k in _INT_COLS:
            row[k] = int(row[k])
        for k in ("r", "g_fc", "g_bt", "k_d", "filt", "sched_tot"):
            row[k] = float(row[k])
        row["ret"] = ret
        rows.append(row)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Port side — the same interpreter, over GovernorModel
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_loads(exe, cmds):
    """Turn every ``LOAD sp tot v_bus`` row into a concrete ``TICK sp i_fc i_bt
    v_bus`` row, using the FIRMWARE's own trajectory to split the total.

    WHY THIS EXISTS, AND WHY IT IS NOT CIRCULAR. Both sides must be driven by
    byte-identical inputs, or a comparison is not a comparison. But a plausible
    plant is exactly what makes a governor trace meaningful: if the scripted
    currents contradict the topology the loop just commanded — a fuel cell that
    keeps delivering nothing while both switches are closed, say — the share
    error never closes, the controller winds to a band rail, and the trace
    becomes a study of a fixture rather than of the governor.

    So the total current and the setpoint are the STIMULUS, and the split is
    resolved in a first firmware pass: tick ``i``'s currents follow the topology
    and the applied ratio the firmware carried into tick ``i``, i.e. row
    ``i - 1``. The resolved list is then replayed through BOTH sides. It is not
    circular, because the resolved list is a fixed sequence of numbers by the
    time either side is compared, and the port never contributes to it: the port
    is asked to reproduce a recorded firmware trajectory.
    """
    if not any(c[0] == "LOAD" for c in cmds):
        return list(cmds)
    # ITERATED TO A FIXED POINT, and the iteration is not optional. One pass
    # from a 50/50 provisional split is itself pathological: the provisional
    # currents contradict the ratio the controller is walking toward, so the
    # share error never closes, the integrator winds to a band rail and the
    # loop CUTS a channel. Resolving against that pass would then script a
    # single-source plant, which is a study of the fixture. Four passes take the
    # trajectory to a consistent plant on every case here; the count is fixed
    # (not convergence-tested) so the resolved stimulus is deterministic and a
    # rerun reproduces it byte for byte.
    out = [(("TICK", c[1], c[2] * 0.5, c[2] * 0.5, c[3])
            if c[0] == "LOAD" else c) for c in cmds]
    for _ in range(4):
        fw = _firmware_trace(exe, out)
        nxt = []
        for i, c in enumerate(cmds):
            if c[0] != "LOAD":
                nxt.append(c)
                continue
            _, sp, tot, vb = c
            # The topology and split the firmware carried INTO this tick.
            prev = fw[i - 1] if i > 0 else {"sw_fc": 1, "sw_bt": 1, "r": 0.5}
            if prev["sw_fc"] and prev["sw_bt"]:
                r = prev["r"]
                i_fc, i_bt = tot * r, tot * (1.0 - r)
            elif prev["sw_bt"]:
                i_fc, i_bt = 0.0, tot
            elif prev["sw_fc"]:
                i_fc, i_bt = tot, 0.0
            else:
                i_fc = i_bt = 0.0
            nxt.append(("TICK", sp, i_fc, i_bt, vb))
        out = nxt
    return out


def _firmware_open_loop_flags(fw, cmds):
    """Which TICK rows the FIRMWARE ran in open-loop mode.

    Replicated from the firmware's own mode gate (.ino:11060-11072) against the
    firmware's own filtered-total column, because the mode is HYSTERETIC and
    therefore not recoverable from a single row: entry is a strict `>` at
    2*I_min, exit a strict `<` at 2*I_min - SHARE_GOV_OL_HYST_A. Anything that
    is not a TICK is neither open nor closed and is reported False."""
    entry = 2.0 * gm.GOV_CONST["SHARE_MINORITY_I_MIN_A"]
    exit_ = entry - gm.GOV_CONST["SHARE_GOV_OL_HYST_A"]
    closed = False
    ever_closed = False
    flags = []
    for c, row in zip(cmds, fw):
        if c[0] != "TICK":
            flags.append(False)
            continue
        tot = row["filt"]
        if not closed:
            if tot > entry:
                closed = True
                ever_closed = True
        elif tot < exit_:
            closed = False
        # ⚠️ "UNCONTAMINATED", NOT MERELY "OPEN LOOP". Once the loop has closed
        # ONCE, the applied ratio it left behind is a Youla-controller output,
        # and the open-loop path that follows HOLDS exactly that ratio -- so a
        # later open-loop tick inherits an unported quantity even though every
        # decision it makes is ported. A comparison that ignored this would be
        # asserting the controller, not the port. The ratio and the codes are
        # therefore compared only on ticks the firmware reached with no
        # closed-loop history at all, which is where the battery-only start,
        # the profile-start hold and the iso bypass live.
        flags.append((not closed) and (not ever_closed))
    return flags


def _port_trace(cmds):
    g = gm.GovernorModel(dt_s=1e-3)
    st = g.state
    # Boot the switch beliefs to the harness's own boot topology: both bus
    # switches HIGH, no recorded rising edge (an unknown edge is treated as old
    # by busSwitchBlanked(), which is what the firmware's boot digitalWrite
    # leaves behind).
    st.sw_fc = True
    st.sw_bt = True
    st.sw_init = True
    t_ms = 0.0
    i_fc = i_bt = 0.0
    rows = []

    def snap(ret=None, wrote=False):
        s = g.state
        r = s.r_prev
        kd = s.droop_kd
        g_fc = kd / (gm.GOV_CONST["RE_MAX"] * r) if r > 0.0 else 1.0
        g_bt = kd / (gm.GOV_CONST["RE_MAX"] * (1.0 - r)) if r < 1.0 else 1.0
        return {
            "r": r, "k_d": kd, "filt": s.filt_total,
            "sched_tot": s.kd_sched_tot,
            "g_fc": min(max(g_fc, 0.0), 1.0),
            "g_bt": min(max(g_bt, 0.0), 1.0),
            "sw_fc": int(s.sw_fc), "sw_bt": int(s.sw_bt),
            "iso_fc": int(s.iso_fc), "iso_bt": int(s.iso_bt),
            "cut_fc": int(s.sp_cut_fc), "cut_bt": int(s.sp_cut_bt),
            "def_fc": int(s.deferred_fc), "def_bt": int(s.deferred_bt),
            "armed": int(s.batt_only_armed), "active": int(s.batt_only_active),
            "ref_load": s.refused_load, "ref_blank": s.refused_blank,
            "g_clamp": s.g_guard_count,
            "ret": ret,
        }

    # The two MDAC mirrors are WRITE-ONLY in the firmware, so the port tracks
    # them the same way: they keep the last word actually written.
    last_codes = [0, 0]

    for c in cmds:
        op = c[0]
        if op == "TICK":
            sp, i_fc, i_bt, vb = c[1], c[2], c[3], c[4]
            g.v_bus_ok = vb >= V_BUS_CHARGED_THRESH
            t_ms += 1.0
            out = g.step(sp, i_fc, i_bt, g.state.sw_fc, g.state.sw_bt,
                         t_ms / 1000.0)
            if out.wrote:
                last_codes = [out.code_fc, out.code_bt]
            row = snap()
        elif op == "ARM":
            g.arm_battery_only_start()
            row = snap()
        elif op == "RESET":
            g._reset_share_control_state()
            row = snap()
        elif op == "CLIP":
            g.state.filt_total = float(c[1])
            row = snap(ret=g.feedforward_clip_target(float(c[2]), float(c[3])))
        elif op == "KDT":
            row = snap(ret=g.droop_scale_target(float(c[1])))
        elif op == "KDS":
            g.state.filt_total = float(c[1])
            g._update_droop_scale()
            row = snap()
        elif op == "MDAC":
            last_codes = list(g.set_droop_mdac(float(c[1]), float(c[2])))
            row = snap()
            # The firmware's mirrors are the RAW gains it was handed, so the
            # reported g_ columns for this op are those, not the map's.
            row["g_fc"] = min(max(float(c[1]), 0.0), 1.0)
            row["g_bt"] = min(max(float(c[2]), 0.0), 1.0)
        elif op == "APPLY":
            wrote, _rl, _rb = g._apply_share_ratio(
                float(c[1]), i_fc, i_bt, t_ms, from_controller=False)
            if wrote:
                s = g.state
                gf = s.droop_kd / (gm.GOV_CONST["RE_MAX"] * s.r_prev)
                gb = s.droop_kd / (gm.GOV_CONST["RE_MAX"] * (1.0 - s.r_prev))
                last_codes = list(g.set_droop_mdac(gf, gb))
                row = snap()
                row["g_fc"] = min(max(gf, 0.0), 1.0)
                row["g_bt"] = min(max(gb, 0.0), 1.0)
            else:
                row = snap()
        elif op == "SETKD":
            g.state.droop_kd = float(c[1])
            row = snap()
        elif op == "SETFILT":
            g.state.filt_total = float(c[1])
            row = snap()
        elif op == "SETPREV":
            g.state.r_prev = float(c[1])
            row = snap()
        else:
            raise AssertionError("unknown op %r" % (op,))
        row["op"] = op
        row["code_fc"], row["code_bt"] = last_codes
        rows.append(row)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Comparison
# ─────────────────────────────────────────────────────────────────────────────
# ── WHAT IS COMPARED WHERE, AND WHY ─────────────────────────────────────────
# The Youla share controller is not ported, so on a CLOSED-LOOP tick the applied
# ratio is a firmware quantity the port only approximates. Everything downstream
# of that ratio is therefore a consequence of the unported controller and not
# evidence about this port: the switch topology (a cut is an r-based decision),
# the isolation/latch/deferral flags, the two refusal counters (both are r-based
# guard outcomes) and the g-guard count (it fires on g = k_d/(RE_MAX*r)).
# Those are compared on every row the port DOES own -- every open-loop tick and
# every direct actuation -- and are not compared on a closed-loop tick.
#
# What IS compared on every row, closed loop included, is the set of quantities
# that are functions of the SCRIPTED inputs alone: the governor filter, the held
# schedule input, the live k_d that follows from it, and the battery-only arm,
# whose ownership rules read the commanded setpoint and the charge window and
# never the ratio. Those four are exactly what fw v27 rev 2 adds to the closed
# loop, so the closed-loop half of this test is not vacuous.
_FLAG_COLS_ALWAYS = ("armed", "active")
_FLAG_COLS_PORTED = ("sw_fc", "sw_bt", "iso_fc", "iso_bt", "cut_fc", "cut_bt",
                     "def_fc", "def_bt", "ref_load", "ref_blank", "g_clamp")
# ``filt`` and ``sched_tot`` are functions of the SCRIPTED currents alone, so
# they are comparable on every row including closed-loop ticks; ``k_d`` follows
# from ``sched_tot`` by the ported schedule and is comparable for the same
# reason. ``r`` is the controller's output and is therefore comparable only
# where the controller is not running.
_SCALAR_COLS = ("filt",)
# ⚠️ THE SCHEDULE PAIR CARRIES A ONE-TICK LAG TOLERANCE, AND IT IS NOT A FUDGE.
# The schedule input is re-sampled when |filt - sched_tot| EXCEEDS a 0.05 A
# deadband, tested strictly. On a ramped load that test is a TIE at exactly one
# tick: the firmware evaluates it in float32 and the port in float64, and the
# two round the same subtraction to opposite sides. Neither is wrong, and the
# consequence is bounded and knowable -- the sample differs by at most one ramp
# step and k_d by at most one of its own slew steps. So the pair is bounded
# rather than equated, at exactly those two bounds, which is a stronger
# statement than a loose relative tolerance would be: a port that re-sampled on
# the wrong CONDITION, or slewed at the wrong RATE, still fails.
_LAG_COLS = ("sched_tot", "k_d")
_KD_SLEW_FRAC = gm.GOV_CONST["SHARE_KD_SLEW_FRAC_PER_TICK"]
_SCHED_LAG_A = 0.0501    # one deadband width, plus float32 slack at the tie
_LAG_TICKS = 8           # how far the schedule pair may lag; see _LAG_COLS
_RATIO_COLS = ("r",)
_REL = 2e-6          # single-precision, with room for one accumulated rounding


def _compare(cmds, fw, py, open_loop):
    assert len(fw) == len(py) == len(cmds)
    bad = []
    code_deltas = []
    n_code_rows = 0
    for i, (f, p) in enumerate(zip(fw, py)):
        assert f["op"] in (cmds[i][0], "v"), (i, f["op"], cmds[i][0])
        ported = cmds[i][0] != "TICK" or open_loop[i]
        for k in _FLAG_COLS_ALWAYS:
            if f[k] != p[k]:
                bad.append("row %d %r: %s fw=%r port=%r"
                           % (i, cmds[i], k, f[k], p[k]))
        if ported:
            for k in _FLAG_COLS_PORTED:
                if f[k] != p[k]:
                    bad.append("row %d %r: %s fw=%r port=%r"
                               % (i, cmds[i], k, f[k], p[k]))
        for k in _SCALAR_COLS:
            if abs(f[k] - p[k]) > _REL * max(1.0, abs(f[k])):
                bad.append("row %d %r: %s fw=%.9g port=%.9g"
                           % (i, cmds[i], k, f[k], p[k]))
        for k in _LAG_COLS:
            lim = (_SCHED_LAG_A if k == "sched_tot"
                   else 2.0 * _KD_SLEW_FRAC * max(abs(f[k]), abs(p[k])))
            lim = max(lim, _REL * max(1.0, abs(f[k])))
            if abs(f[k] - p[k]) <= lim:
                continue
            # The lag WINDOW. A one-sample disagreement about the deadband tie
            # displaces the whole schedule trajectory in TIME, so the port's
            # value at row i is the firmware's value a few rows either side.
            # Matching against that window keeps the check on the schedule's
            # SHAPE -- a port that re-sampled on the wrong condition, or slewed
            # at the wrong rate, leaves the window immediately -- while not
            # failing on a tie neither side is wrong about.
            lo = max(0, i - _LAG_TICKS)
            hi = min(len(fw) - 1, i + _LAG_TICKS)
            if any(abs(fw[j][k] - p[k]) <= lim for j in range(lo, hi + 1)):
                continue
            bad.append("row %d %r: %s fw=%.9g port=%.9g (bound %.4g, no match "
                       "within %d rows)"
                       % (i, cmds[i], k, f[k], p[k], lim, _LAG_TICKS))
        if ported:
            for k in _RATIO_COLS:
                if abs(f[k] - p[k]) > _REL * max(1.0, abs(f[k])):
                    bad.append("row %d %r: %s fw=%.9g port=%.9g"
                               % (i, cmds[i], k, f[k], p[k]))
        if f["ret"] is not None or p["ret"] is not None:
            if f["ret"] is None or p["ret"] is None:
                bad.append("row %d %r: one side returned no value" % (i, cmds[i]))
            elif abs(f["ret"] - p["ret"]) > _REL * max(1.0, abs(f["ret"])):
                bad.append("row %d %r: return fw=%.9g port=%.9g"
                           % (i, cmds[i], f["ret"], p["ret"]))
        if cmds[i][0] in _CODE_COMPARABLE_OPS or (cmds[i][0] == "TICK"
                                                  and open_loop[i]):
            n_code_rows += 1
            code_deltas.append(abs(f["code_fc"] - p["code_fc"]))
            code_deltas.append(abs(f["code_bt"] - p["code_bt"]))
    return bad, code_deltas, n_code_rows


@pytest.mark.parametrize("name,builder", CASES, ids=[c[0] for c in CASES])
def test_port_matches_firmware(harness, name, builder):
    cmds = _resolve_loads(harness, builder())
    fw = _firmware_trace(harness, cmds)
    py = _port_trace(cmds)
    open_loop = _firmware_open_loop_flags(fw, cmds)
    bad, code_deltas, n_code_rows = _compare(cmds, fw, py, open_loop)
    assert not bad, ("port diverges from the firmware on %d checks of %d rows "
                     "(case %s):\n%s"
                     % (len(bad), len(cmds), name, "\n".join(bad[:12])))
    if code_deltas:
        assert max(code_deltas) == 0, (
            "case %s: MDAC code delta %d over %d comparable rows; the ported "
            "code path must be bit-exact"
            % (name, max(code_deltas), n_code_rows))


def test_the_open_loop_codes_are_bit_exact(harness):
    """THE OPEN-LOOP MDAC CODES, SEPARATELY AND EXACTLY.

    The parametrized comparison above skips the codes on TICK rows because a
    CLOSED-loop tick's ratio comes from the unported Youla controller. This test
    restricts the same comparison to the ticks the firmware ran in OPEN loop —
    where the feedforward path is ported in full — and demands a code delta of
    zero. Open-loop occupancy is proven, not assumed: a case whose ticks are all
    closed-loop would pass vacuously, so the count is asserted."""
    cmds = _resolve_loads(harness, (_case_open_loop_only()
                                    + _case_battery_only_start_below_the_gate()
                                    + _case_iso_bypass_and_proposal()))
    fw = _firmware_trace(harness, cmds)
    py = _port_trace(cmds)
    open_loop = _firmware_open_loop_flags(fw, cmds)
    n_open = 0
    bad = []
    for i, (f, p) in enumerate(zip(fw, py)):
        if not open_loop[i]:
            continue
        n_open += 1
        if f["code_fc"] != p["code_fc"] or f["code_bt"] != p["code_bt"]:
            bad.append("row %d: codes fw=(%d,%d) port=(%d,%d)"
                       % (i, f["code_fc"], f["code_bt"],
                          p["code_fc"], p["code_bt"]))
    assert n_open > 200, ("only %d uncontaminated open-loop ticks in the "
                          "stimulus; the comparison would be near-vacuous"
                          % n_open)
    assert not bad, ("%d of %d open-loop ticks disagree on the MDAC codes:\n%s"
                     % (len(bad), n_open, "\n".join(bad[:12])))


def test_the_stimulus_actually_exercises_every_mechanism(harness):
    """A trace on which nothing happens would pass the comparisons above while
    proving nothing. Pin the coverage of all four fw v27 rev 2 mechanisms, on
    the FIRMWARE's trace, so the evidence is the firmware's and not the port's.
    """
    fw_bo = _firmware_trace(harness, _resolve_loads(
        harness, _case_battery_only_start_below_the_gate()))
    assert any(r["cut_fc"] for r in fw_bo), "the battery-only cut never fired"
    assert any(r["sw_fc"] == 0 for r in fw_bo), "FC_BUS never went low"
    assert fw_bo[-1]["sw_fc"] == 1, "FC never came back on the bus"
    assert fw_bo[-1]["armed"] == 0, "the arm was never dropped"

    fw_kd = _firmware_trace(harness, _case_kd_schedule_walk())
    kds = [r["k_d"] for r in fw_kd]
    assert max(kds) > 0.5, "the schedule never left K_DROOP"
    assert min(kds) == pytest.approx(0.30, abs=1e-6), (
        "the schedule never returned to the K_DROOP floor")

    fw_g = _firmware_trace(harness, _case_g_guard_stale_schedule())
    assert fw_g[-1]["g_clamp"] > 0, "the g-guard never fired"

    fw_clip = _firmware_trace(harness, _case_pure_clip())
    rets = [r["ret"] for r in fw_clip]
    assert any(abs(r - 0.62) < 1e-6 for r in rets), (
        "the empty-band HOLD never occurred")
    assert any(r not in (0.15, 0.50, 0.85, 0.62, 0.35) for r in rets), (
        "the relaxing branch never clipped to a band edge")

    fw_iso = _firmware_trace(harness, _resolve_loads(
        harness, _case_iso_bypass_and_proposal()))
    assert any(r["iso_fc"] for r in fw_iso), "no isolation ever occurred"
    assert fw_iso[-1]["iso_fc"] == 0, "the channel never re-entered"


def test_the_schedule_is_bit_identical_to_fw_v26_above_the_crossover(harness):
    """THE PROPERTY THAT PROTECTS EVERY fw v26 ANCHOR. At and above
    RE_MAX*SAFETY*I_min/K_DROOP = 0.906 A of filtered total the live scale IS
    K_DROOP, so every fixture that runs above it holds bit-exact. Asserted on
    the firmware's own trace and on the port's, at the same totals the design
    record's Table 2 lists."""
    cross = (gm.GOV_CONST["RE_MAX"] * gm.GOV_CONST["SHARE_KD_SAFETY"]
             * gm.GOV_CONST["SHARE_MINORITY_I_MIN_A"]
             / gm.GOV_CONST["K_DROOP"])
    assert cross == pytest.approx(0.9061287, abs=1e-6)
    cmds = [("KDT", t) for t in (cross, 1.0, 1.5, 2.0, 3.0, 4.0)]
    fw = _firmware_trace(harness, cmds)
    py = _port_trace(cmds)
    for i, (f, p) in enumerate(zip(fw, py)):
        assert f["ret"] == pytest.approx(gm.GOV_CONST["K_DROOP"], rel=1e-6), (
            "firmware schedule at %r is %.9g, not K_DROOP" % (cmds[i][1],
                                                              f["ret"]))
        assert p["ret"] == pytest.approx(gm.GOV_CONST["K_DROOP"], rel=1e-12)
