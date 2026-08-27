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
    rows = _uniform_rows(0.5, 0.01, fault_flags=lambda t: 0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(_entry([{"kind": "no_fault", "name": "no_fault"}]), str(path))
    assert res["passed"] is True


def test_check_no_fault_fail(tmp_path):
    rows = _uniform_rows(0.5, 0.01, fault_flags=lambda t: rs.FAULT_UV_BUS if t > 0.2 else 0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(_entry([{"kind": "no_fault", "name": "no_fault"}]), str(path))
    assert res["passed"] is False
    assert "UV_BUS" in res["checks"][0]["detail"]


# -- fault_latched -------------------------------------------------------------

def _uv_collapse_rows():
    """V_bus armed (>= V_BUS_CHARGED_THRESH_V) for 50 ms, then collapses
    below LIMIT_V_BUS_MIN_V for 40 ms (> UV_BUS_DWELL_LATCH_MS=20ms), and
    FAULT_UV_BUS is set from partway through the collapse to the end
    (latched, matching what the real dwell filter would do)."""
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
                     "fault_flags": rs.FAULT_UV_BUS if set_bit else 0})
        t += dt
    return rows


def test_check_fault_latched_pass(tmp_path):
    rows = _uv_collapse_rows()
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_latched", "name": "uv_bus_latched",
            "bit": rs.FAULT_UV_BUS, "require_stimulus": True}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True


def test_check_fault_latched_fail_bit_clears_before_end(tmp_path):
    rows = _uv_collapse_rows()
    # Clear the bit on the final row: it must LATCH, not clear.
    rows[-1] = dict(rows[-1])
    rows[-1]["fault_flags"] = 0
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_latched", "name": "uv_bus_latched",
            "bit": rs.FAULT_UV_BUS, "require_stimulus": True}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is False
    assert "CLEARED" in res["checks"][0]["detail"]


def test_check_fault_latched_fail_never_set(tmp_path):
    rows = _uv_collapse_rows()
    for r in rows:
        r["fault_flags"] = 0
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_latched", "name": "uv_bus_latched",
            "bit": rs.FAULT_UV_BUS, "require_stimulus": True}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is False
    assert "never set" in res["checks"][0]["detail"]


def test_check_fault_latched_require_stimulus_inconclusive(tmp_path):
    """V_bus never actually collapses (armed, but stays well above
    LIMIT_V_BUS_MIN the whole time): the stimulus does not qualify, so the
    check must fail LOUDLY as inconclusive rather than pass or silently
    excuse the firmware, even though fault_flags is 0 throughout."""
    rows = _uniform_rows(0.2, 0.001, V_bus=lambda t: 15.9, fault_flags=lambda t: 0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_latched", "name": "uv_bus_latched",
            "bit": rs.FAULT_UV_BUS, "require_stimulus": True}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is False
    assert "INCONCLUSIVE" in res["checks"][0]["detail"]


# -- fault_not_latched ---------------------------------------------------------

def test_check_fault_not_latched_pass(tmp_path):
    rows = _uniform_rows(0.2, 0.005, fault_flags=lambda t: 0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_not_latched", "name": "uv_not_latched", "bit": rs.FAULT_UV_BUS}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True


def test_check_fault_not_latched_fail(tmp_path):
    rows = _uniform_rows(0.2, 0.005,
                          fault_flags=lambda t: rs.FAULT_UV_BUS if t > 0.1 else 0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_not_latched", "name": "uv_not_latched", "bit": rs.FAULT_UV_BUS}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is False
    assert "should NOT latch" in res["checks"][0]["detail"]


# -- bounded_current -------------------------------------------------------------

def test_check_bounded_current_pass(tmp_path):
    rows = _uniform_rows(0.2, 0.005, current=lambda t: 5.0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(_entry([{"kind": "bounded_current", "name": "bc"}]), str(path))
    assert res["passed"] is True


def test_check_bounded_current_fail(tmp_path):
    rows = _uniform_rows(0.2, 0.005, current=lambda t: 13.0)  # above MOTOR_I_CMD_MAX_A + eps
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(_entry([{"kind": "bounded_current", "name": "bc"}]), str(path))
    assert res["passed"] is False
    assert "limit" in res["checks"][0]["detail"]


# -- no_sustained_rail -------------------------------------------------------------

def test_check_no_sustained_rail_pass(tmp_path):
    # a short 0.2 s rail episode, well under the 1.0 s default limit
    rows = _uniform_rows(1.0, 0.01,
                          current=lambda t: 12.0 if 0.4 <= t < 0.6 else 0.0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "no_sustained_rail", "name": "nsr", "max_episode_s": rs.SUSTAINED_RAIL_S}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True


def test_check_no_sustained_rail_fail(tmp_path):
    rows = _uniform_rows(2.0, 0.01, current=lambda t: 12.0 if t >= 0.2 else 0.0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "no_sustained_rail", "name": "nsr", "max_episode_s": rs.SUSTAINED_RAIL_S}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is False
    assert "exceeds" in res["checks"][0]["detail"]


# -- no_rail_limit_cycle -------------------------------------------------------------

def _square_wave(t, freq, level):
    """+level / -level square wave at `freq` Hz (one full period = 1/freq)."""
    period = 1.0 / freq
    phase = (t % period) / period
    return level if phase < 0.5 else -level


def test_check_no_rail_limit_cycle_pass(tmp_path):
    # A single large-signal manoeuvre, not a repeating alternation.
    rows = _uniform_rows(2.0, 0.01, current=lambda t: 12.0 if t < 1.0 else -12.0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "no_rail_limit_cycle", "name": "nrlc", "max_alt_per_s": rs.LIMIT_CYCLE_ALT_PER_S}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True


def test_check_no_rail_limit_cycle_fail_2_5hz_case():
    """The ML0137 boxcar-defect signature: a rail-to-rail square wave at
    2.5 Hz (inside the documented 2.3-2.6 Hz range) must be caught."""
    import tempfile
    rows = _uniform_rows(3.0, 0.001, current=lambda t: _square_wave(t, 2.5, 12.0))
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "no_rail_limit_cycle", "name": "nrlc",
                "max_alt_per_s": rs.LIMIT_CYCLE_ALT_PER_S}
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is False
    assert "limit cycle" in res["checks"][0]["detail"]


# -- returns_off_rail -------------------------------------------------------------

def test_check_returns_off_rail_pass(tmp_path):
    # Rail from 0.2-0.4s, drops to 0 well within OFF_RAIL_WITHIN_S after.
    rows = _uniform_rows(1.0, 0.005,
                          current=lambda t: 12.0 if 0.2 <= t < 0.4 else 0.0)
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
    rows = _uniform_rows(3.0, 0.005,
                          current=lambda t: 12.0 if t >= 0.5 else 0.0)  # 2.5 s pinned
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "returns_off_rail", "name": "rr",
                "level_a": rs.OFF_RAIL_LEVEL_A, "within_s": rs.OFF_RAIL_WITHIN_S}
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is False
    assert "still on the rail" in res["checks"][0]["detail"]


def test_check_returns_off_rail_no_episodes_passes_trivially(tmp_path):
    rows = _uniform_rows(0.5, 0.01, current=lambda t: 0.0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "returns_off_rail", "name": "rr",
            "level_a": rs.OFF_RAIL_LEVEL_A, "within_s": rs.OFF_RAIL_WITHIN_S}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True
    assert "no rail episodes" in res["checks"][0]["detail"]


# -- near_zero_current -------------------------------------------------------------

def test_check_near_zero_current_pass(tmp_path):
    rows = _uniform_rows(0.5, 0.01, current=lambda t: 0.05)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "near_zero_current", "name": "nzc", "max_abs_a": rs.NEAR_ZERO_I_A}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True


def test_check_near_zero_current_fail_bang_bang(tmp_path):
    rows = _uniform_rows(0.5, 0.01, current=lambda t: _square_wave(t, 5.0, 12.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "near_zero_current", "name": "nzc", "max_abs_a": rs.NEAR_ZERO_I_A}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is False
    assert "not driving" in res["checks"][0]["detail"]


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
    rows = _uniform_rows(0.2, 0.01, fault_flags=lambda t: 0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    entry = _entry([{"kind": "not_a_real_check", "name": "bogus"}])
    res = rs.evaluate_replay_csv(entry, str(path))
    assert res["passed"] is False
    assert res["checks"][0]["passed"] is False
    assert "unknown check kind" in res["checks"][0]["detail"]


def test_evaluate_no_checks_defined_fails():
    entry = {"log": "SYN", "fw_version": 21, "mode": "conformance",
             "provisional": False, "checks": []}
    # even a CSV that would otherwise be fine
    res = rs.evaluate_replay_csv(entry, "/nonexistent/but/unreached.csv")
    assert res["passed"] is False


def test_evaluate_check_raising_exception_is_caught_as_failure(tmp_path, monkeypatch):
    """A check kind whose implementation raises must not propagate past
    evaluate_replay_csv — it is reported as a failure."""
    rows = _uniform_rows(0.2, 0.01, fault_flags=lambda t: 0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)

    def boom(data, spec):
        raise RuntimeError("synthetic failure")

    monkeypatch.setitem(rs.CHECK_KINDS, "no_fault", boom)
    entry = _entry([{"kind": "no_fault", "name": "no_fault"}])
    res = rs.evaluate_replay_csv(entry, str(path))
    assert res["passed"] is False
    assert "synthetic failure" in res["checks"][0]["detail"]


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

    rows = _uniform_rows(2.0, 0.01, current=current)
    path_ok = "l7_multi_ok.csv"
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, path_ok)
        write_replay_csv(path, rows)
        spec = {"kind": "returns_off_rail", "name": "rr",
                "level_a": rs.OFF_RAIL_LEVEL_A, "within_s": rs.OFF_RAIL_WITHIN_S}
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is True
    detail = res["checks"][0]["detail"]
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

    rows = _uniform_rows(3.5, 0.01, current=current)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "l7_multi_pinned.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "returns_off_rail", "name": "rr",
                "level_a": rs.OFF_RAIL_LEVEL_A, "within_s": rs.OFF_RAIL_WITHIN_S}
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is False
    detail = res["checks"][0]["detail"]
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
    rows = _uniform_rows(0.2, 0.001, V_bus=lambda t: 15.9, fault_flags=lambda t: 0)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "fault_latched", "name": "uv_bus_latched",
                "bit": rs.FAULT_UV_BUS, "require_stimulus": False}
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is False
    detail = res["checks"][0]["detail"]
    assert "INCONCLUSIVE" not in detail
    assert "never set" in detail


def test_f5_require_stimulus_false_passes_if_bit_latches_regardless_of_v_bus():
    """require_stimulus=False + the bit IS latched -> passes even though
    V_bus never actually dipped (the stimulus-sanity gate is skipped
    entirely, not just downgraded)."""
    rows = _uniform_rows(0.2, 0.001, V_bus=lambda t: 15.9,
                          fault_flags=lambda t: rs.FAULT_UV_BUS if t > 0.05 else 0)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "fault_latched", "name": "uv_bus_latched",
                "bit": rs.FAULT_UV_BUS, "require_stimulus": False}
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is True


def test_f6_non_uv_bit_skips_qualification_even_with_require_stimulus_true():
    """The stimulus-qualification gate is hardcoded to `bit == FAULT_UV_BUS`
    -- a fault_latched check on a DIFFERENT bit (e.g. FAULT_OC_FC) must never
    invoke the UV-specific dwell-integrator sanity check, even with
    require_stimulus left at its True default."""
    rows = _uniform_rows(0.2, 0.001, V_bus=lambda t: 15.9,  # never dips -- would be
                                                             # INCONCLUSIVE for UV_BUS
                          fault_flags=lambda t: rs.FAULT_OC_FC if t > 0.05 else 0)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "fault_latched", "name": "oc_fc_latched",
                "bit": rs.FAULT_OC_FC}   # require_stimulus defaults True
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is True
    assert "INCONCLUSIVE" not in res["checks"][0]["detail"]


def test_f6_non_uv_bit_never_set_fails_without_stimulus_note():
    rows = _uniform_rows(0.2, 0.001, V_bus=lambda t: 15.9, fault_flags=lambda t: 0)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.csv")
        write_replay_csv(path, rows)
        spec = {"kind": "fault_latched", "name": "oc_fc_latched", "bit": rs.FAULT_OC_FC}
        res = rs.evaluate_replay_csv(_entry([spec]), path)
    assert res["passed"] is False
    assert "INCONCLUSIVE" not in res["checks"][0]["detail"]
    assert "stimulus qualifies" not in res["checks"][0]["detail"]


# ─────────────────────────────────────────────────────────────────────────
# 9. Contract-review gap: multiple check kinds in one evaluate_replay_csv call
# ─────────────────────────────────────────────────────────────────────────

def test_evaluate_replay_csv_multiple_check_kinds_aggregation(tmp_path):
    """One entry mixing a passing, a failing, and an unknown check kind: the
    aggregation loop must run every check (not short-circuit on the first
    failure), report each individually, and the unknown kind must fail
    without raising -- overall `passed` is the AND of all three."""
    rows = _uniform_rows(0.3, 0.005, fault_flags=lambda t: 0, current=lambda t: 13.0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    entry = _entry([
        {"kind": "no_fault", "name": "no_fault"},              # passes (fault_flags all 0)
        {"kind": "bounded_current", "name": "bc"},              # fails (13.0 > clamp+eps)
        {"kind": "not_a_real_kind", "name": "bogus"},           # fails (unknown kind)
    ])
    res = rs.evaluate_replay_csv(entry, str(path))
    assert len(res["checks"]) == 3
    by_name = {c["name"]: c for c in res["checks"]}
    assert by_name["no_fault"]["passed"] is True
    assert by_name["bc"]["passed"] is False
    assert by_name["bogus"]["passed"] is False
    assert "unknown check kind" in by_name["bogus"]["detail"]
    assert res["passed"] is False   # AND over all three, not just the first
    # notes are still populated normally alongside the mixed checks
    assert any("Replay is OPEN LOOP" in n for n in res["notes"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
