#!/usr/bin/env python3
"""FIRMWARE-EQUIVALENCE test for the fw v26 source current-ceiling clamp.

WHAT THIS FILE ASSERTS, AND WHY IT IS DIFFERENT FROM THE REST OF THE SUITE.
Every other test of ``governor_model`` asserts the port against an expectation
a person wrote down. This one asserts it against THE FIRMWARE. It compiles
``test/gov_ceiling_harness.cpp``, which includes
``teensy_controller/teensy_controller.ino`` against the same mock layer the
host-native firmware suite uses, drives the real ``applyShareCurrentCeilings()``
through a scripted sequence of (filtered total, setpoint) pairs, and compares
the resulting trace with the Python port driven through the identical sequence.
A divergence in the ordering, the hysteresis or the band constraint therefore
fails here, and no hand-written table can paper over it.

THE ONE TOLERANCE. The firmware computes in ``float`` and the port in ``float``
of double width. The two traces are therefore compared at single-precision
tolerance on the SETPOINT, and EXACTLY on the two clamp flags. The flags are
the load-bearing half: they carry the hysteresis memory, so a port whose
engagement or release boundary is wrong fails on the flags regardless of the
numeric tolerance.

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
HARNESS_SRC = os.path.join(TEST_DIR, "gov_ceiling_harness.cpp")
HARNESS_EXE = os.path.join(TEST_DIR, "gov_ceiling_harness.exe")
INO_PATH = os.path.join(REPO_ROOT, "teensy_controller", "teensy_controller.ino")
MSYS2_BIN = r"C:\msys64\ucrt64\bin"

import governor_model as gm  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# The stimulus. Owned HERE, not by the C++ file, so a coverage change needs no
# C++ edit. Each entry is (filtered total in A, commanded setpoint).
#
# The sequence is ORDER-DEPENDENT by design: the clamp carries hysteresis, so
# the trace is a state machine's trace and not a table of independent
# evaluations. Reordering it is a different test.
# ─────────────────────────────────────────────────────────────────────────────
def _sequence():
    seq = []
    # 1. Below the minimum-load gate: the clamp must return its argument and
    #    drop any state.
    seq += [(0.0, 0.5), (0.05, 0.85), (0.075, 0.85)]
    # 2. A slow ramp of the total through the reachability threshold at the
    #    highest setpoint the droop band admits. The fuel-cell ceiling first
    #    binds at 1.25 / 0.85 = 1.4706 A of total here, because this walk does
    #    NOT carry the minority-current clip the caller applies first.
    tot = 1.20
    while tot <= 2.60 + 1e-9:
        seq.append((round(tot, 4), 0.85))
        tot += 0.02
    # 3. Hysteretic release: walk the same total back down and confirm the flag
    #    holds until the demand falls SHARE_GOV_CEIL_HYST_A below the ceiling.
    tot = 2.60
    while tot >= 1.20 - 1e-9:
        seq.append((round(tot, 4), 0.85))
        tot -= 0.02
    # 4. Setpoint sweep at a fixed high total: engagement and release driven by
    #    the setpoint rather than by the load.
    for i in range(0, 71):
        seq.append((2.0, round(0.15 + i * 0.01, 4)))
    for i in range(70, -1, -1):
        seq.append((2.0, round(0.15 + i * 0.01, 4)))
    # 5. The battery lower bound, which needs a large total and a low setpoint.
    for tot in (2.8, 3.0, 3.2, 3.4, 3.6, 3.8, 3.94, 3.95, 3.96):
        for sp in (0.15, 0.20, 0.30, 0.50):
            seq.append((tot, sp))
    # 6. The infeasible pair above I_FC_CEIL + I_BT_CEIL = 3.95 A, where the
    #    fuel-cell bound must win and the commanded battery current is knowingly
    #    pushed over its own ceiling.
    for tot in (4.0, 4.2, 4.25, 4.4, 5.0, 6.0, 8.0, 8.33, 9.0):
        for sp in (0.15, 0.40, 0.85):
            seq.append((tot, sp))
    # 7. A drop back through the minimum-load gate, to confirm the state clears
    #    from a clamped condition and not only from an unclamped one.
    seq += [(9.0, 0.85), (0.05, 0.85), (2.0, 0.85)]
    return seq


@pytest.fixture(scope="module")
def harness():
    """Build the firmware harness, or skip with the reason."""
    if not os.path.exists(HARNESS_SRC):
        pytest.skip("test/gov_ceiling_harness.cpp is missing")
    env = dict(os.environ)
    if os.path.isdir(MSYS2_BIN):
        env["PATH"] = MSYS2_BIN + os.pathsep + env.get("PATH", "")
    cxx = shutil.which("g++", path=env.get("PATH"))
    if cxx is None:
        pytest.skip("no g++ on PATH and none at %s; the firmware-equivalence "
                    "check needs a host C++ compiler" % MSYS2_BIN)
    # Rebuild only when the executable is missing or older than either source.
    newest = max(os.path.getmtime(HARNESS_SRC), os.path.getmtime(INO_PATH))
    if (not os.path.exists(HARNESS_EXE)
            or os.path.getmtime(HARNESS_EXE) < newest):
        cmd = [cxx, "-std=c++17", "-I.", "-I../teensy_controller",
               "-I../controller_design", "-I../controller_design_MIMO",
               "-DBENCH_TEST=0", "-DHIL_SIM=0", "-DNO_ETH_WARNING",
               "-Wno-unused-function",
               "gov_ceiling_harness.cpp", "-o", "gov_ceiling_harness.exe"]
        proc = subprocess.run(cmd, cwd=TEST_DIR, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if proc.returncode != 0:
            pytest.fail("harness build failed:\n%s"
                        % proc.stdout.decode("utf-8", "replace"))
    return HARNESS_EXE


def _firmware_trace(exe, seq):
    env = dict(os.environ)
    if os.path.isdir(MSYS2_BIN):
        env["PATH"] = MSYS2_BIN + os.pathsep + env.get("PATH", "")
    stdin = "".join("%r %r\n" % (t, s) for t, s in seq)
    proc = subprocess.run([exe], cwd=TEST_DIR, env=env,
                          input=stdin.encode("ascii"),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace")
    lines = proc.stdout.decode("ascii").strip().splitlines()
    assert lines[0].strip() == "tot,sp_in,sp_out,fc,bt", lines[0]
    out = []
    for line in lines[1:]:
        parts = line.strip().split(",")
        out.append((float(parts[2]), int(parts[3]), int(parts[4])))
    return out


def _port_trace(seq):
    g = gm.GovernorModel(dt_s=1e-3)
    g._clear_ceiling_state()
    out = []
    for tot, sp in seq:
        g.state.filt_total = float(tot)
        sp_out = g._apply_share_current_ceilings(float(sp))
        out.append((sp_out,
                    1 if g.state.gov_fc_clamped else 0,
                    1 if g.state.gov_bt_clamped else 0))
    return out


def test_port_matches_firmware_trace(harness):
    seq = _sequence()
    fw = _firmware_trace(harness, seq)
    py = _port_trace(seq)
    assert len(fw) == len(py) == len(seq)
    bad = []
    for i, ((f_sp, f_fc, f_bt), (p_sp, p_fc, p_bt)) in enumerate(zip(fw, py)):
        if f_fc != p_fc or f_bt != p_bt:
            bad.append("row %d (tot=%r sp=%r): flags fw=(%d,%d) port=(%d,%d)"
                       % (i, seq[i][0], seq[i][1], f_fc, f_bt, p_fc, p_bt))
        elif abs(f_sp - p_sp) > 1e-6 * max(1.0, abs(f_sp)):
            bad.append("row %d (tot=%r sp=%r): sp fw=%.9g port=%.9g"
                       % (i, seq[i][0], seq[i][1], f_sp, p_sp))
    assert not bad, ("port diverges from the firmware on %d of %d rows:\n%s"
                     % (len(bad), len(seq), "\n".join(bad[:12])))


def test_the_sequence_actually_exercises_both_clamps(harness):
    """A trace on which nothing ever clamps would pass the comparison above
    while proving nothing. Pin the coverage."""
    fw = _firmware_trace(harness, _sequence())
    assert sum(r[1] for r in fw) > 100, "the fuel-cell clamp barely engaged"
    assert sum(r[2] for r in fw) > 5, "the battery clamp never engaged"
    assert any(r[1] == 0 and r[2] == 0 for r in fw), "nothing ever released"


def test_firmware_and_port_agree_on_the_reachability_threshold(harness):
    """The governing number for this feature is 1.55 A of TWO-SOURCE total
    (docs/fw26_current_ceiling_governor.md section 4.1.1): the minority-current
    clip caps the commanded fuel-cell fraction at 1 - 0.30/I_tot, so the
    ceiling is reachable only above I_FC_CEIL + I_MINORITY.

    Asserted against the firmware, with the minority clip applied here exactly
    as `powerBalance()` applies it before the call."""
    assert gm.CEILING_REACHABLE_I_TOT_A == pytest.approx(1.55, abs=1e-12)
    i_min = gm.GOV_CONST["SHARE_MINORITY_I_MIN_A"]
    seq = []
    tot = 1.40
    while tot <= 1.80 + 1e-9:
        # The minority clip, then the ceiling clamp: the firmware's order.
        lo = i_min / tot
        lo = min(lo, 0.5)
        sp = min(gm.GOV_CONST["DROOP_R_MAX"], 1.0 - lo)
        seq.append((round(tot, 4), round(sp, 9)))
        tot += 0.01
    fw = _firmware_trace(harness, seq)
    first = next((i for i, r in enumerate(fw) if r[1]), None)
    assert first is not None, "the clamp never engaged over the sweep"
    engaged_at = seq[first][0]
    assert engaged_at >= gm.CEILING_REACHABLE_I_TOT_A - 1e-9, (
        "the clamp engaged at %.4f A, BELOW the 1.55 A reachability threshold "
        "the design argues from" % engaged_at)
    assert engaged_at <= gm.CEILING_REACHABLE_I_TOT_A + 0.02 + 1e-9, (
        "the clamp engaged at %.4f A, more than one sweep step above the "
        "1.55 A threshold" % engaged_at)
    # And below the threshold nothing was touched.
    for i, r in enumerate(fw[:first]):
        assert r[1] == 0 and r[2] == 0, "clamped at %.4f A" % seq[i][0]
