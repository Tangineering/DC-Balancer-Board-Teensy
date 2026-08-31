#!/usr/bin/env python3
"""pytest suite for tools/hil_replay_suite.py — the replay-based HIL scenario
class (REPLAY_SUITE table, check kinds, evaluate_replay_csv, build_sim_argv).

Synthetic CSVs are built directly in the hil_plant_sim replay-CSV schema
(load_replay_csv only requires t/V_bus/current/fault_flags; other columns are
filled in for realism but not required). No network, no real board, no BLG
replay is executed — this exercises the evaluation logic against constructed
CSVs plus the two real logs already checked into logs/ for the integrity
checks.

Run: cd tools && python -m pytest test_hil_replay_suite.py -v
"""
import csv
import os
import struct
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import hil_replay_suite as rs  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────
# CSV construction helper
# ─────────────────────────────────────────────────────────────────────────

CSV_COLUMNS = [
    "t", "seq", "V_fc", "V_batt", "V_bus", "V_chg", "V_rgn", "I_fc", "I_batt",
    "v_actual", "I_charge", "ag105_status",
    "state", "switch", "aux", "current", "mdac_fc", "mdac_bt",
    "fault_flags", "replay_rec",
]


def write_replay_csv(path, rows):
    """rows: list of dicts with at least 't'; unset columns default to a
    reasonable filled value (obs columns blank unless given, matching a real
    replay CSV before the first observation frame)."""
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for i, r in enumerate(rows):
            row = {
                "t": f"{r['t']:.6f}", "seq": r.get("seq", i % 256),
                "V_fc": r.get("V_fc", 13.0), "V_batt": r.get("V_batt", 7.8),
                "V_bus": r.get("V_bus", 15.9), "V_chg": r.get("V_chg", 0.0),
                "V_rgn": r.get("V_rgn", 0.0), "I_fc": r.get("I_fc", 0.1),
                "I_batt": r.get("I_batt", 0.1), "v_actual": r.get("v_actual", 0.0),
                "I_charge": r.get("I_charge", 0.0), "ag105_status": "0x00",
                "state": r.get("state", 2), "switch": r.get("switch", 0),
                "aux": r.get("aux", 0), "current": r.get("current", 0.0),
                "mdac_fc": r.get("mdac_fc", 0), "mdac_bt": r.get("mdac_bt", 0),
                "fault_flags": r.get("fault_flags", 0), "replay_rec": i,
            }
            if r.get("no_obs"):
                for c in rs.OBS_COLUMNS:
                    row[c] = ""
            w.writerow(row)


def _uniform_rows(t_end, dt, **overrides_fn):
    """overrides_fn: dict of column -> callable(t) -> value (optional)."""
    n = int(t_end / dt)
    rows = []
    for i in range(n):
        t = i * dt
        row = {"t": t}
        for col, fn in overrides_fn.items():
            row[col] = fn(t)
        rows.append(row)
    return rows


# ─────────────────────────────────────────────────────────────────────────
# Bring-up-gate / grace-window / preamble fixture helpers (2026-08-30 repair,
# updated for the M5/M6 preamble-vs-grace split)
#
# evaluate_replay_csv() now runs a BRING-UP GATE before an entry's own checks:
# the CSV must report mainState BRINGUP_STATE_IDLE (1) at or before
# BRINGUP_DEADLINE_S, or every downstream check is skipped in favour of one
# `bringup_reached_idle` failure.
#
# TWO separate time bounds now gate content, and they are NOT interchangeable
# (hil_replay_suite.py's ReplayCsv docstring, M5/M6):
#   grace_s     (REPLAY_GRACE_S, 2.0 s) -- about the BOARD. ReplayCsv.faults
#               (read by no_fault / fault_latched's hits+end_flags /
#               fault_not_latched) is filtered to t >= grace_s at construction.
#   preamble_s  (REPLAY_PREAMBLE_S, 2.5 s, per-entry via entry_preamble_s())
#               -- about the STIMULUS. The UV_BUS/OC_FC stimulus-qualification
#               guards inside check_fault_latched (_uv_stimulus_qualifies /
#               _oc_fc_stimulus_qualifies) and check_no_rail_limit_cycle's
#               ReplayCsv.current_recorded are filtered to t >= preamble_s, NOT
#               grace_s -- a synthetic preamble must not arm or qualify a
#               stimulus check on rails this harness invented.
# An import-time assertion in hil_replay_suite.py pins REPLAY_PREAMBLE_S >=
# WARM_RESET_GRACE_S, so shifting content past preamble_s (the larger bound)
# always also clears grace_s -- one shift amount is enough for every check
# kind in this file, including require_stimulus=True fault_latched checks.
def _bringup_row(t=0.0):
    """A single observation row that satisfies the bring-up gate on its own:
    mainState 1 (Idle) well inside BRINGUP_DEADLINE_S, no fault."""
    return {"t": t, "state": rs.BRINGUP_STATE_IDLE, "fault_flags": 0}


def _shift_rows(rows, offset):
    """New row dicts with every `t` advanced by `offset` (does not mutate)."""
    return [dict(r, t=r["t"] + offset) for r in rows]


def _with_bringup(rows, shift=None):
    """Prepend a bring-up row and, if `shift` is given, move the rest of
    `rows` later in time by `shift` first.  Pass shift=rs.REPLAY_PREAMBLE_S for
    any test whose content must land inside the preamble-filtered stimulus
    window (which also clears the narrower grace_s bound -- see above)."""
    if shift:
        rows = _shift_rows(rows, shift)
    return [_bringup_row()] + rows


def _with_bringup_and_grace(rows):
    """`_with_bringup` shifted past REPLAY_PREAMBLE_S -- the common case for
    every fault-bit / stimulus-guarded check kind (no_fault / fault_latched
    incl. its UV_BUS/OC_FC stimulus qualification / fault_not_latched /
    no_rail_limit_cycle's current_recorded). Named '..._and_grace' for the
    existing call sites; the shift amount is preamble_s, the larger of the
    two bounds, which is why it still works for the plain grace-only checks
    too."""
    return _with_bringup(rows, shift=rs.REPLAY_PREAMBLE_S)


# ─────────────────────────────────────────────────────────────────────────
# 1. REPLAY_SUITE integrity
# ─────────────────────────────────────────────────────────────────────────

def test_suite_has_26_entries():
    assert len(rs.REPLAY_SUITE) == 26


def test_suite_modes_only_conformance_or_deviation():
    modes = {e["mode"] for e in rs.REPLAY_SUITE}
    assert modes <= {"conformance", "deviation"}
    assert modes == {"conformance", "deviation"}


def test_suite_every_path_exists_on_disk():
    for e in rs.REPLAY_SUITE:
        full = os.path.join(REPO_ROOT, e["path"])
        assert os.path.isfile(full), f"{e['log']}: missing {e['path']}"


def test_suite_verify_suite_logs_clean():
    problems = rs.verify_suite_logs(REPO_ROOT)
    assert problems == [], problems


def test_suite_spot_check_two_headers_independently():
    """Independently re-derive the header check verify_suite_logs performs,
    for two specific entries, rather than trusting verify_suite_logs alone."""
    index = rs.suite_index()
    for log in ("ML0146", "ML0151"):
        entry = index[log]
        path = os.path.join(REPO_ROOT, entry["path"])
        with open(path, "rb") as fh:
            head = fh.read(24)
        assert head[:4] == b"BLG1"
        blg_version = head[4]
        assert blg_version == entry["blg_version"]
        if blg_version >= 2:
            (fw,) = struct.unpack_from("<H", head, 18)
            assert fw == entry["fw_version"]


def test_suite_index_covers_every_entry():
    index = rs.suite_index()
    assert len(index) == len(rs.REPLAY_SUITE)  # no duplicate log names
    for e in rs.REPLAY_SUITE:
        assert index[e["log"]] is e


def test_suite_entries_have_at_least_one_check():
    for e in rs.REPLAY_SUITE:
        assert e["checks"], e["log"]
        for c in e["checks"]:
            assert c["kind"] in rs.CHECK_KINDS, (e["log"], c)


# ─────────────────────────────────────────────────────────────────────────
# 2. Check kinds — synthetic pass/fail pairs
# ─────────────────────────────────────────────────────────────────────────

def _entry(checks, **extra):
    e = {"log": "SYN", "fw_version": 21, "mode": "conformance",
         "provisional": False, "checks": checks}
    e.update(extra)
    return e


# -- no_fault ----------------------------------------------------------------

def test_check_no_fault_pass(tmp_path):
    rows = _with_bringup_and_grace(_uniform_rows(0.5, 0.01, fault_flags=lambda t: 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(_entry([{"kind": "no_fault", "name": "no_fault"}]), str(path))
    assert res["passed"] is True


def test_check_no_fault_fail(tmp_path):
    rows = _with_bringup_and_grace(
        _uniform_rows(0.5, 0.01, fault_flags=lambda t: rs.FAULT_UV_BUS if t > 0.2 else 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(_entry([{"kind": "no_fault", "name": "no_fault"}]), str(path))
    assert res["passed"] is False
    assert "UV_BUS" in res["checks"][-1]["detail"]


# -- fault_latched -------------------------------------------------------------

def _uv_collapse_rows():
    """V_bus armed (>= V_BUS_CHARGED_THRESH_V) for 50 ms, then collapses
    below LIMIT_V_BUS_MIN_V for 40 ms (> UV_BUS_DWELL_LATCH_MS=20ms), and
    FAULT_UV_BUS is set from partway through the collapse to the end
    (LATCHED, matching what the real dwell filter would do -- the bit is
    ORed with FAULT_ERROR, since triggerFault() always sets it alongside
    any latch, and check_fault_latched()/check_fault_not_latched() now use
    LATCH semantics (bit AND FAULT_ERROR), not the bare bit)."""
    rows = []
    dt = 0.001
    t = 0.0
    while t < 0.05:                       # armed period
        rows.append({"t": t, "V_bus": 15.9, "fault_flags": 0})
        t += dt
    collapse_start = t
    while t < collapse_start + 0.04:      # 40 ms collapse
        set_bit = (t - collapse_start) >= 0.022  # bit appears once dwell latches
        rows.append({"t": t, "V_bus": 10.0,
                     "fault_flags": (rs.FAULT_UV_BUS | rs.FAULT_ERROR) if set_bit else 0})
        t += dt
    return rows


def test_check_fault_latched_pass(tmp_path):
    rows = _with_bringup_and_grace(_uv_collapse_rows())
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_latched", "name": "uv_bus_latched",
            "bit": rs.FAULT_UV_BUS, "require_stimulus": True}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True


def test_check_fault_latched_fail_bit_clears_before_end(tmp_path):
    rows = _with_bringup_and_grace(_uv_collapse_rows())
    # Clear the bit on the final row: it must LATCH, not clear.
    rows[-1] = dict(rows[-1])
    rows[-1]["fault_flags"] = 0
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_latched", "name": "uv_bus_latched",
            "bit": rs.FAULT_UV_BUS, "require_stimulus": True}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is False
    assert "CLEARED" in res["checks"][-1]["detail"]


def test_check_fault_latched_fail_never_set(tmp_path):
    rows = _with_bringup_and_grace(_uv_collapse_rows())
    for r in rows:
        r["fault_flags"] = 0
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_latched", "name": "uv_bus_latched",
            "bit": rs.FAULT_UV_BUS, "require_stimulus": True}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is False
    assert "never set" in res["checks"][-1]["detail"]


# ── L1: whole-run first-observation note ────────────────────────────────────

def test_l1_whole_run_first_note_when_fault_persists_from_before_grace(tmp_path):
    """A fault that latched BEFORE the grace bound and PERSISTS through it
    (ML0217's INIT_FAIL at ~0.3 s is the standing real example) is still
    scored correctly on its post-grace samples -- but the post-grace 'first
    observation' time describes the FILTER, not the event. L1's whole-run
    first-observation note must name the real, earlier time."""
    dt = 0.01
    early_rows = []
    t = 0.1
    while t < rs.REPLAY_PREAMBLE_S + 0.5:
        early_rows.append({"t": t, "V_bus": 15.9,
                           "fault_flags": rs.FAULT_UV_BUS | rs.FAULT_ERROR})
        t += dt
    rows = [_bringup_row()] + early_rows
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_latched", "name": "uv_bus_latched",
            "bit": rs.FAULT_UV_BUS, "require_stimulus": False}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True
    detail = res["checks"][-1]["detail"]
    assert "whole-run first observation t=0.100s" in detail
    assert "BEFORE the" in detail
    assert "PERSISTED" in detail


def test_l1_whole_run_first_note_absent_when_first_observation_coincides():
    """The note is SILENT when the whole-run and post-grace first
    observations are the same instant (a fault that only ever appears after
    the grace bound) -- it exists specifically for the persisted-from-before
    case, not as a decoration on every fault_latched pass."""
    rows = _with_bringup_and_grace(_uv_collapse_rows())
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "fault_latched", "name": "uv_bus_latched",
                "bit": rs.FAULT_UV_BUS, "require_stimulus": True}
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is True
    detail = res["checks"][-1]["detail"]
    assert "whole-run first observation" not in detail


def test_l1_whole_run_first_note_carried_in_direction_when_bit_clears_before_grace(tmp_path):
    """The CARRIED-IN direction (item 2): the bit was set early (pre-grace)
    but is GONE by the LAST pre-grace sample -- the predecessor run's settle
    latch, cleared by the fw v23 warm reset -- so the post-grace LATCH is a
    SEPARATE, later event, not the same fault persisting. Must say CLEARED,
    never PERSISTED (the exact wrong call the campaign report caught on
    ML0203/ML0169/TP0053 the first time this note was written)."""
    rows = [_bringup_row()]
    rows.append({"t": 0.2, "fault_flags": rs.FAULT_UV_BUS})   # early sighting
    rows.append({"t": 0.5, "fault_flags": rs.FAULT_UV_BUS})
    rows.append({"t": 1.0, "fault_flags": 0})                 # CLEARS before grace
    rows.append({"t": 1.9, "fault_flags": 0})                 # last pre-grace sample
    rows.append({"t": 2.0, "fault_flags": rs.FAULT_UV_BUS | rs.FAULT_ERROR})  # separate LATCH
    rows.append({"t": 2.5, "fault_flags": rs.FAULT_UV_BUS | rs.FAULT_ERROR})
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_latched", "name": "uv_bus_latched",
            "bit": rs.FAULT_UV_BUS, "require_stimulus": False}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True
    detail = res["checks"][-1]["detail"]
    assert "CLEARED by t=1.900s" in detail
    assert "carried-in settle latch" in detail
    assert "PERSISTED" not in detail


def test_check_fault_latched_reports_transient_lead_before_the_real_latch(tmp_path):
    """Item 2: check_fault_latched's `lead` note names how much earlier the
    bit was merely INDICATED (bare bit, no FAULT_ERROR) before it actually
    LATCHED -- pin the print, not just the pass/fail."""
    rows = [_bringup_row()]
    rows.append({"t": 2.100, "fault_flags": rs.FAULT_UV_BUS})                    # indicated
    rows.append({"t": 2.200, "fault_flags": rs.FAULT_UV_BUS})
    rows.append({"t": 2.321, "fault_flags": rs.FAULT_UV_BUS | rs.FAULT_ERROR})   # latches
    rows.append({"t": 2.400, "fault_flags": rs.FAULT_UV_BUS | rs.FAULT_ERROR})
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "fault_latched", "name": "uv_bus_latched",
                "bit": rs.FAULT_UV_BUS, "require_stimulus": False}
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is True
    detail = res["checks"][-1]["detail"]
    assert "LATCHED (bit + FAULT_ERROR)" in detail
    assert "transiently indicated 221 ms earlier" in detail
    assert "t=2.100s" in detail


def test_check_fault_latched_run_ending_on_a_transient_no_longer_scores_latched(tmp_path):
    """Item 2: a run that ends with the bit merely INDICATED (no
    FAULT_ERROR) at the last sample must FAIL -- a transient at end of run
    is not a latch, even though the old bare-bit semantics would have
    accepted it."""
    rows = [_bringup_row()]
    rows.append({"t": 2.100, "fault_flags": rs.FAULT_UV_BUS})   # indicated only
    rows.append({"t": 2.200, "fault_flags": rs.FAULT_UV_BUS})   # ...and stays that way
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_latched", "name": "uv_bus_latched",
            "bit": rs.FAULT_UV_BUS, "require_stimulus": False}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is False
    detail = res["checks"][-1]["detail"]
    assert "INDICATED" in detail
    assert "never LATCHED" in detail
    assert "FAULT_ERROR was never set" in detail


# ── F5 (item 2): no_fault vs fault_not_latched — a documented, deliberate seam
def test_f5_no_fault_fails_on_a_transient_that_fault_not_latched_allows(tmp_path):
    """The contract note above check_fault_not_latched(): pairing `no_fault`
    with `fault_not_latched` on the SAME entry is NOT redundant. A bare
    transient indication (no FAULT_ERROR) passes fault_not_latched (it only
    promises 'never LATCHES') but FAILS no_fault (which promises 'nothing
    was even indicated'). Pin both halves of that seam on identical data."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.2, 0.005,
                      fault_flags=lambda t: rs.FAULT_UV_BUS if t > 0.1 else 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    entry = _entry([
        {"kind": "no_fault", "name": "no_fault"},
        {"kind": "fault_not_latched", "name": "uv_not_latched", "bit": rs.FAULT_UV_BUS},
    ])
    res = rs.evaluate_replay_csv(entry, str(path))
    by_name = {c["name"]: c for c in res["checks"]}
    assert by_name["no_fault"]["passed"] is False
    assert by_name["uv_not_latched"]["passed"] is True
    assert res["passed"] is False   # the pair disagrees; the run is NOT clean


def test_check_fault_latched_require_stimulus_inconclusive(tmp_path):
    """V_bus never actually collapses (armed, but stays well above
    LIMIT_V_BUS_MIN the whole time): the stimulus does not qualify, so the
    check must fail LOUDLY as inconclusive rather than pass or silently
    excuse the firmware, even though fault_flags is 0 throughout."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.2, 0.001, V_bus=lambda t: 15.9, fault_flags=lambda t: 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_latched", "name": "uv_bus_latched",
            "bit": rs.FAULT_UV_BUS, "require_stimulus": True}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is False
    assert "INCONCLUSIVE" in res["checks"][-1]["detail"]


# -- fault_not_latched ---------------------------------------------------------

def test_check_fault_not_latched_pass(tmp_path):
    rows = _with_bringup_and_grace(_uniform_rows(0.2, 0.005, fault_flags=lambda t: 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_not_latched", "name": "uv_not_latched", "bit": rs.FAULT_UV_BUS}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True


def test_check_fault_not_latched_fail(tmp_path):
    """LATCH semantics: the bit must be ORed with FAULT_ERROR to count as a
    latch (fault_not_latched fails on a LATCH, not a bare indication)."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.2, 0.005,
                      fault_flags=lambda t: (rs.FAULT_UV_BUS | rs.FAULT_ERROR)
                      if t > 0.1 else 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_not_latched", "name": "uv_not_latched", "bit": rs.FAULT_UV_BUS}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is False
    assert "should NOT latch" in res["checks"][-1]["detail"]


def test_check_fault_not_latched_passes_on_a_bare_transient_indication(tmp_path):
    """Item 2: a bit set WITHOUT FAULT_ERROR (indicated, never latched) must
    PASS fault_not_latched -- it only promises 'this never LATCHES', and the
    detail must name the transient so a reader is not misled into thinking
    nothing happened at all."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.2, 0.005,
                      fault_flags=lambda t: rs.FAULT_UV_BUS if t > 0.1 else 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_not_latched", "name": "uv_not_latched", "bit": rs.FAULT_UV_BUS}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True
    detail = res["checks"][-1]["detail"]
    assert "transiently INDICATED" in detail
    assert "without ever" in detail and "latching" in detail


# -- bounded_current -------------------------------------------------------------

def test_check_bounded_current_pass(tmp_path):
    rows = _with_bringup(_uniform_rows(0.2, 0.005, current=lambda t: 5.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(_entry([{"kind": "bounded_current", "name": "bc"}]), str(path))
    assert res["passed"] is True


def test_check_bounded_current_fail(tmp_path):
    rows = _with_bringup(
        _uniform_rows(0.2, 0.005, current=lambda t: 13.0))  # above MOTOR_I_CMD_MAX_A + eps
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(_entry([{"kind": "bounded_current", "name": "bc"}]), str(path))
    assert res["passed"] is False
    assert "limit" in res["checks"][-1]["detail"]


# -- no_sustained_rail -------------------------------------------------------------

def test_check_no_sustained_rail_pass(tmp_path):
    # a short 0.2 s rail episode, well under the 1.0 s default limit
    rows = _with_bringup(
        _uniform_rows(1.0, 0.01, current=lambda t: 12.0 if 0.4 <= t < 0.6 else 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "no_sustained_rail", "name": "nsr", "max_episode_s": rs.SUSTAINED_RAIL_S}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True


def test_check_no_sustained_rail_fail(tmp_path):
    rows = _with_bringup(
        _uniform_rows(2.0, 0.01, current=lambda t: 12.0 if t >= 0.2 else 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "no_sustained_rail", "name": "nsr", "max_episode_s": rs.SUSTAINED_RAIL_S}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is False
    assert "exceeds" in res["checks"][-1]["detail"]


# -- no_rail_limit_cycle -------------------------------------------------------------

def _square_wave(t, freq, level):
    """+level / -level square wave at `freq` Hz (one full period = 1/freq)."""
    period = 1.0 / freq
    phase = (t % period) / period
    return level if phase < 0.5 else -level


def test_check_no_rail_limit_cycle_pass(tmp_path):
    # A single large-signal manoeuvre, not a repeating alternation. Shifted
    # past preamble_s: check_no_rail_limit_cycle reads current_recorded
    # (M6), which is filtered to t >= preamble_s, not just grace_s.
    rows = _with_bringup_and_grace(
        _uniform_rows(2.0, 0.01, current=lambda t: 12.0 if t < 1.0 else -12.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "no_rail_limit_cycle", "name": "nrlc", "max_alt_per_s": rs.LIMIT_CYCLE_ALT_PER_S}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True


def test_check_no_rail_limit_cycle_fail_2_5hz_case():
    """The ML0137 boxcar-defect signature: a rail-to-rail square wave at
    2.5 Hz (inside the documented 2.3-2.6 Hz range) must be caught."""
    import tempfile
    rows = _with_bringup_and_grace(
        _uniform_rows(3.0, 0.001, current=lambda t: _square_wave(t, 2.5, 12.0)))
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "no_rail_limit_cycle", "name": "nrlc",
                "max_alt_per_s": rs.LIMIT_CYCLE_ALT_PER_S}
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is False
    assert "limit cycle" in res["checks"][-1]["detail"]


# -- returns_off_rail -------------------------------------------------------------

def test_check_returns_off_rail_pass(tmp_path):
    # Rail from 0.2-0.4s, drops to 0 well within OFF_RAIL_WITHIN_S after.
    rows = _with_bringup(
        _uniform_rows(1.0, 0.005, current=lambda t: 12.0 if 0.2 <= t < 0.4 else 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "returns_off_rail", "name": "rr",
            "level_a": rs.OFF_RAIL_LEVEL_A, "within_s": rs.OFF_RAIL_WITHIN_S}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True


def test_check_returns_off_rail_fail_pinned_to_rail_at_eof():
    """A rail episode that never comes off by the end of the CSV, and lasts
    longer than within_s, is the windup signature and must fail — NOT be
    excused just because the run happened to end."""
    import tempfile
    rows = _with_bringup(
        _uniform_rows(3.0, 0.005,
                      current=lambda t: 12.0 if t >= 0.5 else 0.0))  # 2.5 s pinned
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "returns_off_rail", "name": "rr",
                "level_a": rs.OFF_RAIL_LEVEL_A, "within_s": rs.OFF_RAIL_WITHIN_S}
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is False
    assert "still on the rail" in res["checks"][-1]["detail"]


def test_check_returns_off_rail_no_episodes_passes_trivially(tmp_path):
    rows = _with_bringup(_uniform_rows(0.5, 0.01, current=lambda t: 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "returns_off_rail", "name": "rr",
            "level_a": rs.OFF_RAIL_LEVEL_A, "within_s": rs.OFF_RAIL_WITHIN_S}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True
    assert "no rail episodes" in res["checks"][-1]["detail"]


# -- near_zero_current -------------------------------------------------------------

def test_check_near_zero_current_pass(tmp_path):
    rows = _with_bringup(_uniform_rows(0.5, 0.01, current=lambda t: 0.05))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "near_zero_current", "name": "nzc", "max_abs_a": rs.NEAR_ZERO_I_A}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True


def test_check_near_zero_current_fail_bang_bang(tmp_path):
    rows = _with_bringup(_uniform_rows(0.5, 0.01, current=lambda t: _square_wave(t, 5.0, 12.0)))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "near_zero_current", "name": "nzc", "max_abs_a": rs.NEAR_ZERO_I_A}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is False
    assert "not driving" in res["checks"][-1]["detail"]


# ─────────────────────────────────────────────────────────────────────────
# 3. evaluate_replay_csv edge cases
# ─────────────────────────────────────────────────────────────────────────

def test_evaluate_missing_csv_file_fails_not_raises():
    entry = _entry([{"kind": "no_fault", "name": "no_fault"}])
    res = rs.evaluate_replay_csv(entry, "/nonexistent/path/nope.csv")
    assert res["passed"] is False
    assert res["checks"][0]["name"] == "csv"
    assert res["checks"][0]["passed"] is False


def test_evaluate_zero_observation_csv_all_checks_fail_with_note(tmp_path):
    """A CSV with rows but never an observation frame (obs columns all
    blank): every check that depends on observations must fail, and the
    'board never answered' note must be present."""
    rows = _uniform_rows(0.2, 0.01)
    for r in rows:
        r["no_obs"] = True
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    entry = _entry([
        {"kind": "no_fault", "name": "no_fault"},
        {"kind": "bounded_current", "name": "bc"},
    ])
    res = rs.evaluate_replay_csv(entry, str(path))
    assert res["passed"] is False
    assert all(not c["passed"] for c in res["checks"])
    assert any("never answered" in n for n in res["notes"])


def test_evaluate_unknown_check_kind_is_a_failure(tmp_path):
    rows = _with_bringup(_uniform_rows(0.2, 0.01, fault_flags=lambda t: 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    entry = _entry([{"kind": "not_a_real_check", "name": "bogus"}])
    res = rs.evaluate_replay_csv(entry, str(path))
    assert res["passed"] is False
    assert res["checks"][-1]["passed"] is False
    assert "unknown check kind" in res["checks"][-1]["detail"]


def test_evaluate_no_checks_defined_fails():
    entry = {"log": "SYN", "fw_version": 21, "mode": "conformance",
             "provisional": False, "checks": []}
    # even a CSV that would otherwise be fine
    res = rs.evaluate_replay_csv(entry, "/nonexistent/but/unreached.csv")
    assert res["passed"] is False


def test_evaluate_check_raising_exception_is_caught_as_failure(tmp_path, monkeypatch):
    """A check kind whose implementation raises must not propagate past
    evaluate_replay_csv — it is reported as a failure."""
    rows = _with_bringup(_uniform_rows(0.2, 0.01, fault_flags=lambda t: 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)

    def boom(data, spec):
        raise RuntimeError("synthetic failure")

    monkeypatch.setitem(rs.CHECK_KINDS, "no_fault", boom)
    entry = _entry([{"kind": "no_fault", "name": "no_fault"}])
    res = rs.evaluate_replay_csv(entry, str(path))
    assert res["passed"] is False
    assert "synthetic failure" in res["checks"][-1]["detail"]


# ─────────────────────────────────────────────────────────────────────────
# 4. build_sim_argv
# ─────────────────────────────────────────────────────────────────────────

def test_build_sim_argv_has_replay_and_csv_no_transport_flags():
    entry = rs.suite_index()["ML0151"]
    argv = rs.build_sim_argv(entry, "/tmp/csvdir")
    assert "--replay" in argv
    # Orchestrator CWD-independence fix: build_sim_argv resolves the repo-root-
    # relative entry path against REPO_ROOT so the argv works from any CWD.
    assert argv[argv.index("--replay") + 1] == os.path.join(rs.REPO_ROOT, entry["path"])
    assert os.path.isfile(argv[argv.index("--replay") + 1])
    assert "--csv" in argv
    csv_arg = argv[argv.index("--csv") + 1]
    assert csv_arg == os.path.join("/tmp/csvdir", f"hil_replay_{entry['log']}.csv")
    for flag in ("--teensy-ip", "--port", "--bind-port"):
        assert flag not in argv, f"{flag} should be the wrapper's job, not build_sim_argv's"


def test_build_sim_argv_matches_replay_csv_path_helper():
    entry = rs.suite_index()["ML0146"]
    argv = rs.build_sim_argv(entry, "csvs")
    csv_arg = argv[argv.index("--csv") + 1]
    assert csv_arg == rs.replay_csv_path(entry, "csvs")


# ─────────────────────────────────────────────────────────────────────────
# 4b. H1: UV pair (TP0010/TP0053) i_fc_clamp_a; H2: ML0217 skip_preamble
# ─────────────────────────────────────────────────────────────────────────

def test_uv_pair_entries_carry_the_i_fc_clamp():
    index = rs.suite_index()
    for log in ("TP0010", "TP0053"):
        entry = index[log]
        assert entry["i_fc_clamp_a"] == pytest.approx(rs.UV_PAIR_I_FC_CLAMP_A)
    assert rs.UV_PAIR_I_FC_CLAMP_A == pytest.approx(1.3)


def test_only_the_uv_pair_carries_an_i_fc_clamp():
    for e in rs.REPLAY_SUITE:
        if e["log"] in ("TP0010", "TP0053"):
            assert e.get("i_fc_clamp_a") is not None, e["log"]
        else:
            assert e.get("i_fc_clamp_a") is None, e["log"]


def test_build_sim_argv_emits_replay_i_fc_clamp_for_uv_pair():
    index = rs.suite_index()
    for log in ("TP0010", "TP0053"):
        argv = rs.build_sim_argv(index[log], "/tmp/csvdir")
        assert "--replay-i-fc-clamp" in argv
        idx = argv.index("--replay-i-fc-clamp")
        assert float(argv[idx + 1]) == pytest.approx(rs.UV_PAIR_I_FC_CLAMP_A)


def test_build_sim_argv_omits_replay_i_fc_clamp_for_other_entries():
    entry = rs.suite_index()["ML0151"]
    assert entry.get("i_fc_clamp_a") is None
    argv = rs.build_sim_argv(entry, "/tmp/csvdir")
    assert "--replay-i-fc-clamp" not in argv


def test_ml0217_carries_skip_preamble_and_skip_bringup_gate():
    entry = rs.suite_index()["ML0217"]
    assert entry.get("skip_preamble") is True
    assert entry.get("skip_bringup_gate") is True
    assert entry.get("persistent_fault") is True
    check = entry["checks"][0]
    assert check["kind"] == "fault_latched"
    assert check["bit"] == rs.FAULT_INIT_FAIL


# ── _assert_skip_preamble_entries() import-time guard (item 2) ─────────────
# The guard already ran once at import (module load); these tests re-derive
# it directly against synthetic tables via monkeypatch, so a future entry
# that adds skip_preamble without the required persistent_fault/fault_latched
# pairing fails LOUDLY here instead of only ever being caught by luck at the
# next `import hil_replay_suite`.

def test_assert_skip_preamble_entries_rejects_missing_persistent_fault(monkeypatch):
    fake_suite = [{"log": "FAKE", "skip_preamble": True,
                   "checks": [{"kind": "fault_latched", "bit": rs.FAULT_INIT_FAIL}]}]
    monkeypatch.setattr(rs, "REPLAY_SUITE", fake_suite)
    with pytest.raises(AssertionError, match="persistent_fault"):
        rs._assert_skip_preamble_entries()


def test_assert_skip_preamble_entries_rejects_missing_fault_latched_check(monkeypatch):
    fake_suite = [{"log": "FAKE", "skip_preamble": True, "persistent_fault": True,
                   "checks": [{"kind": "no_fault"}]}]
    monkeypatch.setattr(rs, "REPLAY_SUITE", fake_suite)
    with pytest.raises(AssertionError, match="fault_latched"):
        rs._assert_skip_preamble_entries()


def test_assert_skip_preamble_entries_accepts_the_compliant_shape(monkeypatch):
    fake_suite = [{"log": "FAKE", "skip_preamble": True, "persistent_fault": True,
                   "checks": [{"kind": "fault_latched", "bit": rs.FAULT_INIT_FAIL}]}]
    monkeypatch.setattr(rs, "REPLAY_SUITE", fake_suite)
    rs._assert_skip_preamble_entries()   # must not raise


def test_assert_skip_preamble_entries_ignores_entries_without_skip_preamble(monkeypatch):
    """An entry with NO skip_preamble is entirely exempt, even with neither
    persistent_fault nor a fault_latched check -- the guard only concerns
    entries that void the preamble>=grace assertion."""
    fake_suite = [{"log": "FAKE", "checks": [{"kind": "no_fault"}]}]
    monkeypatch.setattr(rs, "REPLAY_SUITE", fake_suite)
    rs._assert_skip_preamble_entries()   # must not raise


def test_only_ml0217_carries_skip_preamble():
    for e in rs.REPLAY_SUITE:
        if e["log"] == "ML0217":
            assert e.get("skip_preamble") is True
        else:
            assert not e.get("skip_preamble"), e["log"]


def test_build_sim_argv_emits_replay_no_preamble_for_ml0217():
    entry = rs.suite_index()["ML0217"]
    argv = rs.build_sim_argv(entry, "/tmp/csvdir")
    assert "--replay-no-preamble" in argv


def test_build_sim_argv_omits_replay_no_preamble_for_other_entries():
    entry = rs.suite_index()["ML0151"]
    assert not entry.get("skip_preamble")
    argv = rs.build_sim_argv(entry, "/tmp/csvdir")
    assert "--replay-no-preamble" not in argv


def test_entry_preamble_s_resolver():
    assert rs.entry_preamble_s(rs.suite_index()["ML0217"]) == pytest.approx(0.0)
    assert rs.entry_preamble_s(rs.suite_index()["ML0151"]) == pytest.approx(
        rs.REPLAY_PREAMBLE_S)
    # Robust to a bare None / missing-dict caller (the function's own docstring
    # implies this via the `(entry or {})` guard).
    assert rs.entry_preamble_s(None) == pytest.approx(rs.REPLAY_PREAMBLE_S)
    assert rs.entry_preamble_s({}) == pytest.approx(rs.REPLAY_PREAMBLE_S)


def test_import_time_preamble_ge_grace_assertion_holds():
    """M7/L3: the module-level assertion (REPLAY_PREAMBLE_S >= WARM_RESET_GRACE_S)
    already ran at import time -- re-derive it here so a future accidental
    narrowing of either constant is caught by this test too, not only by a
    successful `import hil_replay_suite`."""
    assert rs.REPLAY_PREAMBLE_S >= rs.REPLAY_GRACE_S


# ─────────────────────────────────────────────────────────────────────────
# 4c. #4 (review, LOW): boundary equality at t == grace_s / t == preamble_s
#
# Production code uses strict `t < X: skip` (equivalently `t >= X` to keep)
# everywhere in this module. Pin the exact boundary sample so a future
# <-to-<= (or >=-to->) typo fails a test instead of silently reclassifying
# the one tick that sits exactly on a bound.
# ─────────────────────────────────────────────────────────────────────────

def test_replaycsv_faults_boundary_t_equals_grace_s_included():
    grace = rs.REPLAY_GRACE_S
    rows = [{"t": f"{grace:.6f}", "fault_flags": str(rs.FAULT_UV_BUS)}]
    data = rs.ReplayCsv(rows, ["t", "fault_flags"])
    assert any(t == pytest.approx(grace) for t, f in data.faults)
    assert data.faults_pre_grace == []


def test_replaycsv_faults_boundary_t_just_before_grace_s_excluded():
    grace = rs.REPLAY_GRACE_S
    rows = [{"t": f"{grace - 0.000001:.6f}", "fault_flags": str(rs.FAULT_UV_BUS)}]
    data = rs.ReplayCsv(rows, ["t", "fault_flags"])
    assert data.faults == []
    assert any(t == pytest.approx(grace - 0.000001) for t, f in data.faults_pre_grace)


def test_uv_stimulus_qualifies_boundary_armed_row_at_exactly_preamble_s_included():
    """_uv_stimulus_qualifies() filters `if t < data.preamble_s: continue` --
    a row at EXACTLY t == preamble_s must be INCLUDED. Proven by making that
    exact row the one that ESTABLISHES 'armed' (V_bus >= V_BUS_CHARGED_THRESH_V):
    without it, arming never happens and the dwell latch is unreachable, even
    though every subsequent dip sample is otherwise identical."""
    pre = rs.REPLAY_PREAMBLE_S
    rows = [
        {"t": f"{pre:.6f}", "V_bus": "15.9"},              # == preamble_s: armed
        {"t": f"{pre + 0.005:.6f}", "V_bus": "10.0"},
        {"t": f"{pre + 0.010:.6f}", "V_bus": "10.0"},
        {"t": f"{pre + 0.015:.6f}", "V_bus": "10.0"},
        {"t": f"{pre + 0.020:.6f}", "V_bus": "10.0"},
        {"t": f"{pre + 0.025:.6f}", "V_bus": "10.0"},      # 5 x 5ms dwell = 25ms, comfortably
                                                            # clears the 20ms latch (FP-safe
                                                            # margin over an exact-4-tick sum)
    ]
    data = rs.ReplayCsv(rows, ["t", "V_bus"])
    qualifies, when, _peak = rs._uv_stimulus_qualifies(data)
    assert qualifies is True
    assert when == pytest.approx(pre + 0.020, abs=1e-6) or when == pytest.approx(pre + 0.025, abs=1e-6)


def test_uv_stimulus_qualifies_boundary_armed_row_just_before_preamble_s_excluded():
    """The converse: the SAME armed row one microsecond before preamble_s is
    excluded, arming never happens (every included row is the low dip, which
    is below V_BUS_CHARGED_THRESH_V), and the stimulus never qualifies."""
    pre = rs.REPLAY_PREAMBLE_S
    rows = [
        {"t": f"{pre - 0.000001:.6f}", "V_bus": "15.9"},   # excluded
        {"t": f"{pre + 0.005:.6f}", "V_bus": "10.0"},
        {"t": f"{pre + 0.010:.6f}", "V_bus": "10.0"},
        {"t": f"{pre + 0.015:.6f}", "V_bus": "10.0"},
        {"t": f"{pre + 0.020:.6f}", "V_bus": "10.0"},
    ]
    data = rs.ReplayCsv(rows, ["t", "V_bus"])
    qualifies, _when, _peak = rs._uv_stimulus_qualifies(data)
    assert qualifies is False


def test_oc_fc_stimulus_qualifies_boundary_sample_at_exactly_preamble_s_included():
    pre = rs.REPLAY_PREAMBLE_S
    over = rs.LIMIT_I_FC_MAX_A + 1.0
    rows = [{"t": f"{pre:.6f}", "I_fc": f"{over:.3f}"}]
    data = rs.ReplayCsv(rows, ["t", "I_fc"])
    qualifies, when, peak = rs._oc_fc_stimulus_qualifies(data)
    assert qualifies is True
    assert when == pytest.approx(pre)
    assert peak == pytest.approx(over)


def test_oc_fc_stimulus_qualifies_boundary_sample_just_before_preamble_s_excluded():
    pre = rs.REPLAY_PREAMBLE_S
    over = rs.LIMIT_I_FC_MAX_A + 1.0
    rows = [{"t": f"{pre - 0.000001:.6f}", "I_fc": f"{over:.3f}"}]
    data = rs.ReplayCsv(rows, ["t", "I_fc"])
    qualifies, when, peak = rs._oc_fc_stimulus_qualifies(data)
    assert qualifies is False
    assert when is None
    assert peak == 0.0   # the excluded sample never even updates `peak`


# ─────────────────────────────────────────────────────────────────────────
# 5. FW_DELTA_NOTES
# ─────────────────────────────────────────────────────────────────────────

def test_every_suite_fw_version_has_a_delta_note():
    for e in rs.REPLAY_SUITE:
        fw = e["fw_version"]
        assert fw in rs.FW_DELTA_NOTES, f"{e['log']}: fw_version {fw} has no FW_DELTA_NOTES entry"
        assert rs.FW_DELTA_NOTES[fw]


def test_pre_v18_entries_get_stability_not_trace_match_note(tmp_path):
    rows = _uniform_rows(0.2, 0.01, fault_flags=lambda t: 0, current=lambda t: 1.0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    for e in rs.REPLAY_SUITE:
        if e["fw_version"] is None or e["fw_version"] < rs.COMPARABLE_FW_MIN:
            res = rs.evaluate_replay_csv(e, str(path))
            assert any("STABILITY and FAULT BEHAVIOUR" in n for n in res["notes"]), e["log"]


def test_v18_plus_entries_do_not_get_the_stale_wheel_note(tmp_path):
    rows = _uniform_rows(0.2, 0.01, fault_flags=lambda t: 0, current=lambda t: 1.0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    for e in rs.REPLAY_SUITE:
        if e["fw_version"] is not None and e["fw_version"] >= rs.COMPARABLE_FW_MIN:
            res = rs.evaluate_replay_csv(e, str(path))
            assert not any("STABILITY and FAULT BEHAVIOUR" in n for n in res["notes"]), e["log"]


# ─────────────────────────────────────────────────────────────────────────
# 6. L7: check_returns_off_rail single-pass rewrite — multi-episode pinning
# ─────────────────────────────────────────────────────────────────────────

def test_l7_returns_off_rail_multiple_episodes_all_release_cleanly():
    """Three separate rail episodes, each released promptly, in one CSV.
    Pins the single-pass cursor rewrite against the old per-episode full
    rescan: the cursor must correctly find EACH episode's own release point
    without episode 2/3's scan being thrown off by episode 1 already having
    advanced the cursor past it."""
    def current(t):
        if 0.10 <= t < 0.20 or 0.50 <= t < 0.60 or 1.00 <= t < 1.30:
            return 12.0
        return 0.0

    rows = _with_bringup(_uniform_rows(2.0, 0.01, current=current))
    path_ok = "l7_multi_ok.csv"
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, path_ok)
        write_replay_csv(path, rows)
        spec = {"kind": "returns_off_rail", "name": "rr",
                "level_a": rs.OFF_RAIL_LEVEL_A, "within_s": rs.OFF_RAIL_WITHIN_S}
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is True
    detail = res["checks"][-1]["detail"]
    assert "3 rail episode(s)" in detail


def test_l7_returns_off_rail_multiple_episodes_last_one_pinned_at_eof():
    """Two episodes release cleanly; a THIRD, later and longer than
    within_s, is still pinned when the CSV ends -- the windup failure must
    still be detected correctly even with earlier, unrelated episodes ahead
    of it in the single forward-cursor walk."""
    def current(t):
        if 0.10 <= t < 0.20 or 0.50 <= t < 0.60 or t >= 1.00:
            return 12.0
        return 0.0

    rows = _with_bringup(_uniform_rows(3.5, 0.01, current=current))
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "l7_multi_pinned.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "returns_off_rail", "name": "rr",
                "level_a": rs.OFF_RAIL_LEVEL_A, "within_s": rs.OFF_RAIL_WITHIN_S}
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is False
    detail = res["checks"][-1]["detail"]
    assert "still on the rail" in detail
    assert "t=1.000s" in detail or "t=1.00" in detail


# ─────────────────────────────────────────────────────────────────────────
# 7. L8: evaluate_replay_csv's numeric n_obs field
# ─────────────────────────────────────────────────────────────────────────

def test_l8_n_obs_field_zero_for_no_observation_csv(tmp_path):
    rows = _uniform_rows(0.2, 0.01)
    for r in rows:
        r["no_obs"] = True
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(_entry([{"kind": "no_fault", "name": "no_fault"}]), str(path))
    assert res["n_obs"] == 0
    assert isinstance(res["n_obs"], int)


def test_l8_n_obs_field_nonzero_for_normal_csv(tmp_path):
    rows = _uniform_rows(0.2, 0.01, fault_flags=lambda t: 0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(_entry([{"kind": "no_fault", "name": "no_fault"}]), str(path))
    assert res["n_obs"] == len(rows)
    assert res["n_obs"] > 0


def test_l8_n_obs_field_none_when_csv_never_parses():
    res = rs.evaluate_replay_csv(_entry([{"kind": "no_fault", "name": "no_fault"}]),
                                 "/nonexistent/path/nope.csv")
    assert res["n_obs"] is None


def test_l8_wrapper_side_abort_decision_treats_none_and_zero_alike():
    """Pin the exact numeric contract run_hil_suite.py's _run_plan() reads:
    `ev.get("n_obs") in (0, None)` must be True for both the zero-obs and the
    could-not-parse cases, and False for a normal CSV -- this is the decision
    itself, re-derived here rather than trusted from the source comment."""
    def no_obs_decision(n_obs):
        return n_obs in (0, None)

    assert no_obs_decision(0) is True
    assert no_obs_decision(None) is True
    assert no_obs_decision(5) is False
    assert no_obs_decision(1) is False


# ─────────────────────────────────────────────────────────────────────────
# 8. F5/F6: check_fault_latched stimulus-qualification gating
# ─────────────────────────────────────────────────────────────────────────

def test_f5_require_stimulus_false_skips_qualification():
    """With require_stimulus=False, a UV_BUS check must not run the leaky-
    dwell stimulus sanity check at all -- a bit that is simply never set
    fails on 'never set', not on 'INCONCLUSIVE'."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.2, 0.001, V_bus=lambda t: 15.9, fault_flags=lambda t: 0))
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "fault_latched", "name": "uv_bus_latched",
                "bit": rs.FAULT_UV_BUS, "require_stimulus": False}
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is False
    detail = res["checks"][-1]["detail"]
    assert "INCONCLUSIVE" not in detail
    assert "never set" in detail


def test_f5_require_stimulus_false_passes_if_bit_latches_regardless_of_v_bus():
    """require_stimulus=False + the bit IS latched -> passes even though
    V_bus never actually dipped (the stimulus-sanity gate is skipped
    entirely, not just downgraded)."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.2, 0.001, V_bus=lambda t: 15.9,
                      fault_flags=lambda t: (rs.FAULT_UV_BUS | rs.FAULT_ERROR)
                      if t > 0.05 else 0))
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "fault_latched", "name": "uv_bus_latched",
                "bit": rs.FAULT_UV_BUS, "require_stimulus": False}
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is True


def test_f6_oc_fc_stimulus_qualifies_when_i_fc_exceeds_limit():
    """FAULT_OC_FC now has its own stimulus model (2026-08-30): the INJECTED
    I_fc series must actually exceed LIMIT_I_FC_MAX_A, mirroring the
    firmware's single-sample OC comparison exactly.  Here it does (I_fc
    ramps above the limit at the same instant the bit is set), so the check
    passes and names the qualifying instant -- not INCONCLUSIVE."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.2, 0.001,
                      I_fc=lambda t: 2.0 if t > 0.05 else 0.1,
                      fault_flags=lambda t: (rs.FAULT_OC_FC | rs.FAULT_ERROR)
                      if t > 0.05 else 0))
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "fault_latched", "name": "oc_fc_latched",
                "bit": rs.FAULT_OC_FC}   # require_stimulus defaults True
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is True
    detail = res["checks"][-1]["detail"]
    assert "INCONCLUSIVE" not in detail
    assert "stimulus qualified" in detail


def test_f6_oc_fc_stimulus_inconclusive_when_i_fc_never_exceeds_limit():
    """The bit is set (e.g. carried over from a suite-authoring mistake) but
    the injected I_fc never actually crosses LIMIT_I_FC_MAX_A -- this is not
    a valid OC_FC stimulus and the check must fail LOUDLY as INCONCLUSIVE,
    the same discipline the UV_BUS stimulus model already has."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.2, 0.001, I_fc=lambda t: 0.2,
                      fault_flags=lambda t: rs.FAULT_OC_FC if t > 0.05 else 0))
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "fault_latched", "name": "oc_fc_latched", "bit": rs.FAULT_OC_FC}
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is False
    detail = res["checks"][-1]["detail"]
    assert "INCONCLUSIVE" in detail
    assert f"{rs.LIMIT_I_FC_MAX_A:.2f}" in detail


def test_f6_unmodeled_bit_with_require_stimulus_true_is_a_suite_error():
    """Only FAULT_UV_BUS and FAULT_OC_FC have a stimulus model. A
    fault_latched check on any other bit with require_stimulus left at its
    True default (e.g. FAULT_MOT_HOTPLUG) must fail as a SUITE authoring
    error -- silently skipping the guard is how an entry's stimulus rots
    unnoticed."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.2, 0.001,
                      fault_flags=lambda t: rs.FAULT_MOT_HOTPLUG if t > 0.05 else 0))
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "fault_latched", "name": "mot_hotplug_latched",
                "bit": rs.FAULT_MOT_HOTPLUG}   # require_stimulus defaults True
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is False
    assert "suite error" in res["checks"][-1]["detail"]


def test_f6_non_uv_bit_never_set_fails_without_stimulus_note():
    """require_stimulus explicitly False on an unmodeled bit: no stimulus
    check runs at all (neither a qualification pass nor a suite error), and
    a bit that is simply never set fails on 'never set'."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.2, 0.001, V_bus=lambda t: 15.9, fault_flags=lambda t: 0))
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "fault_latched", "name": "oc_fc_latched",
                "bit": rs.FAULT_OC_FC, "require_stimulus": False}
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is False
    detail = res["checks"][-1]["detail"]
    assert "INCONCLUSIVE" not in detail
    assert "never set" in detail


# ─────────────────────────────────────────────────────────────────────────
# 9. Contract-review gap: multiple check kinds in one evaluate_replay_csv call
# ─────────────────────────────────────────────────────────────────────────

def test_evaluate_replay_csv_multiple_check_kinds_aggregation(tmp_path):
    """One entry mixing a passing, a failing, and an unknown check kind: the
    aggregation loop must run every check (not short-circuit on the first
    failure), report each individually, and the unknown kind must fail
    without raising -- overall `passed` is the AND of all three."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.3, 0.005, fault_flags=lambda t: 0, current=lambda t: 13.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    entry = _entry([
        {"kind": "no_fault", "name": "no_fault"},              # passes (fault_flags all 0)
        {"kind": "bounded_current", "name": "bc"},              # fails (13.0 > clamp+eps)
        {"kind": "not_a_real_kind", "name": "bogus"},           # fails (unknown kind)
    ])
    res = rs.evaluate_replay_csv(entry, str(path))
    # + the bring-up gate's own passing check, ahead of the entry's three.
    assert len(res["checks"]) == 4
    by_name = {c["name"]: c for c in res["checks"]}
    assert by_name["no_fault"]["passed"] is True
    assert by_name["bc"]["passed"] is False
    assert by_name["bogus"]["passed"] is False
    assert "unknown check kind" in by_name["bogus"]["detail"]
    assert res["passed"] is False   # AND over all three, not just the first
    # notes are still populated normally alongside the mixed checks
    assert any("Replay is OPEN LOOP" in n for n in res["notes"])


# ─────────────────────────────────────────────────────────────────────────
# command_is_identically_zero() / VACUOUS_TAG / n_checks_substantive-vacuous
# (item 2, "F6"/item 5): replay mode constructs no commander, so a run whose
# `current` column is 0.0000 A on EVERY sample makes several checks true for
# free -- tagged, and counted, so a reader can tell substantive from vacuous.
# ─────────────────────────────────────────────────────────────────────────

def test_command_is_identically_zero_true_for_an_all_zero_series(tmp_path):
    rows = _with_bringup(_uniform_rows(0.2, 0.01, current=lambda t: 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    assert data.command_is_identically_zero() is True


def test_command_is_identically_zero_false_when_any_sample_is_nonzero(tmp_path):
    rows = _with_bringup(_uniform_rows(0.2, 0.01,
                                       current=lambda t: 5.0 if t > 0.1 else 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    assert data.command_is_identically_zero() is False


def test_command_is_identically_zero_false_when_no_observations_at_all(tmp_path):
    rows = _uniform_rows(0.2, 0.01)
    for r in rows:
        r["no_obs"] = True
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    assert data.command_is_identically_zero() is False


def test_vacuous_tag_applied_to_command_shape_checks_when_current_is_all_zero(tmp_path):
    rows = _with_bringup_and_grace(
        _uniform_rows(0.2, 0.005, fault_flags=lambda t: 0, current=lambda t: 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    entry = _entry([
        {"kind": "bounded_current", "name": "bc"},
        {"kind": "no_rail_limit_cycle", "name": "nrlc"},
        {"kind": "returns_off_rail", "name": "rr"},
        {"kind": "near_zero_current", "name": "nzc"},
    ])
    res = rs.evaluate_replay_csv(entry, str(path))
    by_name = {c["name"]: c for c in res["checks"]}
    for name in ("bc", "nrlc", "rr", "nzc"):
        assert by_name[name]["passed"] is True
        assert rs.VACUOUS_TAG in by_name[name]["detail"], name
    assert res["n_checks"] == 5   # + the bring-up gate check
    assert res["n_checks_vacuous"] == 4
    assert res["n_checks_substantive"] == 1
    assert any("4 of 5 checks are VACUOUS" in n for n in res["notes"])
    assert any("SUBSTANTIVE checks: 1" in n for n in res["notes"])


def test_vacuous_tag_absent_when_current_is_not_all_zero(tmp_path):
    rows = _with_bringup_and_grace(
        _uniform_rows(0.2, 0.005, fault_flags=lambda t: 0,
                      current=lambda t: 5.0 if t > 0.1 else 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    entry = _entry([{"kind": "bounded_current", "name": "bc"}])
    res = rs.evaluate_replay_csv(entry, str(path))
    by_name = {c["name"]: c for c in res["checks"]}
    assert by_name["bc"]["passed"] is True
    assert rs.VACUOUS_TAG not in by_name["bc"]["detail"]
    assert res["n_checks_vacuous"] == 0
    assert res["n_checks_substantive"] == res["n_checks"]
    assert not any("VACUOUS" in n for n in res["notes"])


# ─────────────────────────────────────────────────────────────────────────
# TARGET_FW_VERSION / LIMIT_V_BUS_MAX_V (item 2)
# ─────────────────────────────────────────────────────────────────────────

def test_target_fw_version_is_23():
    """21 -> 23 (2026-08-30): fw v22 (HIL sequential runs) and fw v23 (any-
    fault run-boundary recovery) are both load-bearing for this suite -- the
    whole replay half depends on the v22 staged bring-up completing and the
    v23 between-run recovery, so the target must say what it actually runs
    against. COMPARABLE_FW_MIN is a SEPARATE constant and stays at 18."""
    assert rs.TARGET_FW_VERSION == 23
    assert rs.COMPARABLE_FW_MIN == 18
    assert 22 in rs.FW_DELTA_NOTES and 23 in rs.FW_DELTA_NOTES


def test_limit_v_bus_max_v_matches_firmware():
    # teensy_controller/teensy_controller.ino:1305 -- LIMIT_V_BUS_MAX =
    # V_BUS_NOMINAL(16.0) + 1.5 = 17.5 V
    assert rs.LIMIT_V_BUS_MAX_V == pytest.approx(17.5)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
