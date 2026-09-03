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
import hashlib
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

def test_suite_has_27_entries():
    # 12 conformance / 15 deviation (SY0001/FU4 added this round, conformance).
    assert len(rs.REPLAY_SUITE) == 27
    modes = [e["mode"] for e in rs.REPLAY_SUITE]
    assert modes.count("conformance") == 12
    assert modes.count("deviation") == 15


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


# -- fault_latched `not_before_s` (2026-08-31 ledger fix queue) — WHICH
#    mechanism latched, not just that one did. Three branches: the latch is
#    earlier than the bound (FAIL, wrong mechanism), the latch is at/after
#    the bound (PASS), and the spec carries no bound at all (old behavior,
#    unaffected by timing). `_uv_collapse_rows()` latches at a known,
#    reproducible offset from its own start (collapse_start=0.05s,
#    bit-set at 0.05+0.022=0.072s), which lands at
#    REPLAY_PREAMBLE_S + 0.072s once shifted by `_with_bringup_and_grace`.

def test_check_fault_latched_not_before_s_fails_when_latch_is_earlier(tmp_path):
    rows = _with_bringup_and_grace(_uv_collapse_rows())
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    latch_t = rs.REPLAY_PREAMBLE_S + 0.072
    spec = {"kind": "fault_latched", "name": "uv_bus_latched",
            "bit": rs.FAULT_UV_BUS, "require_stimulus": False,
            "not_before_s": latch_t + 0.030}   # bound AFTER the real latch
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is False
    detail = res["checks"][-1]["detail"]
    assert "LATCHED at t=" in detail
    assert "EARLIER than" in detail


def test_check_fault_latched_not_before_s_passes_when_latch_is_at_or_after(tmp_path):
    rows = _with_bringup_and_grace(_uv_collapse_rows())
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    latch_t = rs.REPLAY_PREAMBLE_S + 0.072
    spec = {"kind": "fault_latched", "name": "uv_bus_latched",
            "bit": rs.FAULT_UV_BUS, "require_stimulus": False,
            "not_before_s": latch_t - 0.030}   # bound BEFORE the real latch
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True


def test_check_fault_latched_without_not_before_s_is_the_old_timing_agnostic_behavior(tmp_path):
    """Absent `not_before_s`: the check must not care WHEN the latch happened
    at all -- pinned by re-running the exact "earlier" stimulus above with
    the key simply omitted and confirming it now PASSES."""
    rows = _with_bringup_and_grace(_uv_collapse_rows())
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_latched", "name": "uv_bus_latched",
            "bit": rs.FAULT_UV_BUS, "require_stimulus": False}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["passed"] is True
    assert "not_before_s" not in spec


# -- fault_latched `not_before_s`: CARRIED-IN vs PERSISTED (DI-MED-4) ───────
#    The bound is evaluated against the WHOLE-RUN first latched observation,
#    which back-to-back in a campaign can be the PREVIOUS run's settle latch —
#    still on the wire until the fw v23 warm reset clears it at ~0.5 s. The
#    two pre-grace stories are separated exactly as `_whole_run_first_note`
#    separates them: still set on the last pre-grace sample = PERSISTED (this
#    run's own latch, and the bound must see it); gone by then = CARRIED-IN
#    (the predecessor's, and the bound must skip it).

def _latched_rows(spans, bit=None):
    """Rows at 10 ms spacing over `spans` = [(t0, t1, latched_bool), ...]."""
    bit = rs.FAULT_UV_BUS if bit is None else bit
    rows = []
    for t0, t1, on in spans:
        t = t0
        while t < t1 - 1e-9:
            rows.append({"t": round(t, 4),
                         "fault_flags": (bit | rs.FAULT_ERROR) if on else 0})
            t += 0.01
    return rows


def test_check_fault_latched_not_before_s_skips_a_carried_in_predecessor_latch(tmp_path):
    """DI-MED-4 REGRESSION. A carried-in latch at t=0.1 that is CLEARED well
    before the 2.0 s grace bound must not be read as this run's latch: the
    bound is 2.0 s and the run's own latch is at 2.6 s, so this PASSES. Under
    the pre-fix raw whole-run scan it FAILED with a wrong-mechanism message —
    the ML0217 back-to-back scenario."""
    rows = ([_bringup_row(0.0)]
            + _latched_rows([(0.1, 0.5, True),      # predecessor's settle latch
                             (0.5, 2.0, False),     # cleared by the warm reset
                             (2.0, 2.6, False),
                             (2.6, 3.2, True)]))    # THIS run's latch
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_latched", "name": "uv_bus_latched",
            "bit": rs.FAULT_UV_BUS, "require_stimulus": False,
            "not_before_s": 2.0}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    detail = res["checks"][-1]["detail"]
    assert res["passed"] is True, detail
    assert "whole-run latch at t=2.6" in detail


def test_check_fault_latched_not_before_s_still_sees_a_persisted_early_latch(tmp_path):
    """The other half of the same rule: an early latch that is STILL SET on the
    last pre-grace sample is THIS run's, so the bound must still see it and
    FAIL. Without this, DI-MED-4's fix would have silently turned every
    pre-grace latch into a post-grace one."""
    rows = ([_bringup_row(0.0)]
            + _latched_rows([(0.1, 3.2, True)]))    # latched early and holds
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "fault_latched", "name": "uv_bus_latched",
            "bit": rs.FAULT_UV_BUS, "require_stimulus": False,
            "not_before_s": 2.0}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    detail = res["checks"][-1]["detail"]
    assert res["passed"] is False, detail
    assert "EARLIER than" in detail


def test_persisted_latch_t_helper_matches_the_whole_run_note_classification(tmp_path):
    """The helper and `_whole_run_first_note` must agree on which story a
    pre-grace sighting tells — they are two consumers of one rule, and a
    disagreement is how a report says PERSISTED while the bound treats it as
    carried-in."""
    carried = ([_bringup_row(0.0)]
               + _latched_rows([(0.1, 0.5, True), (0.5, 2.6, False),
                                (2.6, 3.2, True)]))
    persisted = [_bringup_row(0.0)] + _latched_rows([(0.1, 3.2, True)])
    for rows, expect_t, expect_word in ((carried, 2.6, "carried-in"),
                                        (persisted, 0.1, "PERSISTED")):
        data = rs.ReplayCsv([{k: str(v) for k, v in r.items()} for r in rows],
                            ["t", "fault_flags"])
        assert rs._persisted_latch_t(data, rs.FAULT_UV_BUS) == pytest.approx(
            expect_t, abs=0.011)
        assert expect_word in rs._whole_run_first_note(data, rs.FAULT_UV_BUS)


# -- fault_latched `latch_elapsed_band_s`: ML0217's real entry ──────────────

def test_ml0217_fault_latched_entry_pins_the_p0_elapsed_band():
    """F1 (campaign 20260831_222036). ML0217's bring-up gate is P0
    (PRECHARGE_TIMEOUT_MS 300 ms), measured ELAPSED from the State-0 entry —
    NOT the absolute 0.5 s the previous fix round pinned, which discriminated
    nothing because both candidate gates land past it.

    The band's endpoints are asserted literally, and so is the exclusion that
    is its whole purpose: 300 ms must be inside it and P1's 800 ms outside."""
    entry = rs.suite_index()["ML0217"]
    spec = next(c for c in entry["checks"] if c["kind"] == "fault_latched")
    assert "not_before_s" not in spec
    lo, hi = spec["latch_elapsed_band_s"]
    assert (lo, hi) == pytest.approx((0.20, 0.45))
    assert spec["elapsed_from_state"] == 0
    assert lo <= 0.300 <= hi          # P0, the classified gate
    assert not (lo <= 0.800 <= hi)    # P1, the gate this band must exclude


def test_ml0217_band_brackets_both_campaign_measurements():
    """301.3 ms (campaign 20260831_222036) and 301.1 ms (20260831_191509) are
    the two measurements the band was derived from; both must sit inside it
    with room, or the band is fitted rather than derived."""
    spec = next(c for c in rs.suite_index()["ML0217"]["checks"]
                if c["kind"] == "fault_latched")
    lo, hi = spec["latch_elapsed_band_s"]
    for measured in (0.3013, 0.3011):
        assert lo < measured < hi
        assert measured - lo > 0.05 and hi - measured > 0.05


# -- every real timing bound satisfies its import-time shape guard
#    (re-derived directly, not just trusted from a clean import — see
#    _assert_check_spec_shapes()) ───────────────────────────────────────────

def test_every_real_latch_timing_bound_is_well_formed():
    """`not_before_s` has no real user today (F1 retired ML0217's), so it is
    checked opportunistically; the elapsed band DOES and is required to exist,
    or this test would go quietly vacuous the way the one it replaced did."""
    bands = 0
    for e in rs.REPLAY_SUITE:
        for c in e["checks"]:
            if "not_before_s" in c:
                assert float(c["not_before_s"]) > 0.0, (e["log"], c["name"])
            if "latch_elapsed_band_s" in c:
                bands += 1
                lo, hi = c["latch_elapsed_band_s"]
                assert 0.0 <= float(lo) < float(hi), (e["log"], c["name"])
            if "elapsed_from_state" in c:
                assert "latch_elapsed_band_s" in c, (e["log"], c["name"])
    assert bands > 0


# -- fault_latched `latch_elapsed_band_s`: behaviour ────────────────────────

_LATCHED = rs.FAULT_UV_BUS | rs.FAULT_ERROR
# What the board really carries in on ML0217: the fresh child link-handshake
# blip, a DIFFERENT bit from the one under test.
_CARRIED = 0x0010 | rs.FAULT_ERROR


def _state_rows(spans):
    """(t0, t1, state, fault_flags) spans at 10 ms, as observation rows."""
    rows = []
    for t0, t1, state, flags in spans:
        t = t0
        while t < t1 - 1e-9:
            rows.append({"t": round(t, 4), "state": state,
                         "fault_flags": int(flags)})
            t += 0.01
    return rows


def _elapsed_spec(band=(0.20, 0.45), **extra):
    spec = {"kind": "fault_latched", "name": "init_fail_latched",
            "bit": rs.FAULT_UV_BUS, "require_stimulus": False,
            "latch_elapsed_band_s": band}
    spec.update(extra)
    return spec


def test_latch_elapsed_band_passes_on_the_ml0217_shape(tmp_path):
    """The real ML0217 shape, synthesized: latched from the predecessor, warm
    reset into State 0 at 0.50, own latch at 0.80 — 300 ms elapsed."""
    rows = _state_rows([(0.0, 0.50, 99, _CARRIED),   # predecessor's blip
                        (0.50, 0.80, 0, 0),          # warm reset -> bring-up
                        (0.80, 3.2, 99, _LATCHED)])  # P0 timeout latches
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(
        _entry([_elapsed_spec()], skip_bringup_gate=True), str(path))
    detail = res["checks"][-1]["detail"]
    assert res["passed"] is True, detail
    assert "300.0 ms after the mainState 0 entry" in detail


def test_latch_elapsed_band_fails_the_other_bring_up_gate(tmp_path):
    """The exclusion the band exists for: a latch 800 ms after the State-0
    entry (P1's BUS_CHARGE_TIMEOUT_MS) must FAIL, even though its ABSOLUTE
    time (1.30 s) is later than the 0.5 s bound the previous fix round used —
    i.e. the old bound passed exactly this case."""
    rows = _state_rows([(0.0, 0.50, 99, _CARRIED),
                        (0.50, 1.30, 0, 0),
                        (1.30, 3.2, 99, _LATCHED)])
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(
        _entry([_elapsed_spec()], skip_bringup_gate=True), str(path))
    detail = res["checks"][-1]["detail"]
    assert res["passed"] is False, detail
    assert "800.0 ms after the mainState 0 entry" in detail
    assert "OUTSIDE the [200, 450] ms band" in detail


def test_latch_elapsed_band_fails_a_latch_too_early_for_any_gate(tmp_path):
    """The floor is not decoration: 100 ms after the State-0 entry is before
    either bring-up timeout could have expired."""
    rows = _state_rows([(0.0, 0.50, 99, _CARRIED),
                        (0.50, 0.60, 0, 0),
                        (0.60, 3.2, 99, _LATCHED)])
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(
        _entry([_elapsed_spec()], skip_bringup_gate=True), str(path))
    assert res["passed"] is False
    assert "OUTSIDE" in res["checks"][-1]["detail"]


def test_latch_elapsed_band_excludes_a_carried_in_latch_from_the_measurement(tmp_path):
    """_persisted_latch_t()'s carried-in branch, in the elapsed frame — where
    getting it wrong is worse than a wrong bound: the predecessor's latch
    PRECEDES the State-0 entry, so a raw whole-run scan would compute a
    NEGATIVE elapsed time and fail a correct board.

    Structurally unreachable in today's plan order (no run ML0217 can follow
    leaves INIT_FAIL latched), which is why it is unit-tested here and nowhere
    else.

    The predecessor's latch carries THE SAME BIT — that is what makes this a
    carried-in case rather than an unrelated one — and this run's own latch is
    post-grace, which is the shape _persisted_latch_t() can discriminate."""
    rows = _state_rows([(0.0, 0.50, 99, _LATCHED),   # predecessor's own latch
                        (0.50, 2.50, 1, 0),          # cleared by the warm reset
                        (2.50, 2.80, 0, 0),          # THIS run's bring-up
                        (2.80, 4.5, 99, _LATCHED)])  # ... and its P0 timeout
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    # The raw first sighting is the carried-in one at t=0.0 ...
    assert data.first_fault_t(rs.FAULT_UV_BUS) == pytest.approx(0.0, abs=0.011)
    # ... which PRECEDES the State-0 anchor at 2.50, so measuring from it would
    # give a NEGATIVE elapsed time.  The persisted helper reports 2.80 instead.
    assert rs._persisted_latch_t(data, rs.FAULT_UV_BUS) == pytest.approx(
        2.80, abs=0.011)
    res = rs.evaluate_replay_csv(
        _entry([_elapsed_spec()], skip_bringup_gate=True), str(path))
    detail = res["checks"][-1]["detail"]
    assert res["passed"] is True, detail
    assert "300.0 ms after the mainState 0 entry" in detail


def test_latch_elapsed_band_anchors_on_the_LAST_state0_entry(tmp_path):
    """Two warm resets in one run: the anchor must be the one the latch
    actually followed (0.90), not the first State-0 entry (0.20). Anchoring on
    the first would read 900 ms and report the wrong gate."""
    rows = _state_rows([(0.0, 0.20, 99, 0),
                        (0.20, 0.40, 0, 0),          # first bring-up, no latch
                        (0.40, 0.90, 1, 0),          # ran, then reset again
                        (0.90, 1.20, 0, 0),
                        (1.20, 3.2, 99, _LATCHED)])  # 300 ms after the SECOND
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(
        _entry([_elapsed_spec()], skip_bringup_gate=True), str(path))
    detail = res["checks"][-1]["detail"]
    assert res["passed"] is True, detail
    assert "entry at t=0.9000s" in detail


def test_latch_elapsed_band_fails_loudly_with_no_anchor(tmp_path):
    """No State-0 entry at all — a latch that is the predecessor's and was
    never cleared. The check must refuse rather than invent an anchor."""
    rows = _state_rows([(0.0, 3.2, 99, _LATCHED)])
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(
        _entry([_elapsed_spec()], skip_bringup_gate=True), str(path))
    detail = res["checks"][-1]["detail"]
    assert res["passed"] is False, detail
    assert "never reported an ENTRY into mainState 0" in detail


def test_latch_elapsed_band_honours_a_non_default_anchor_state(tmp_path):
    """`elapsed_from_state` selects the anchor; anchoring the same trace on
    State 1 instead of State 0 measures a different interval."""
    rows = _state_rows([(0.0, 0.50, 99, 0),
                        (0.50, 0.80, 0, 0),
                        (0.80, 1.10, 1, 0),          # Idle entry at 0.80
                        (1.10, 3.2, 99, _LATCHED)])  # 300 ms after Idle
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    ok = rs.evaluate_replay_csv(
        _entry([_elapsed_spec(elapsed_from_state=1)], skip_bringup_gate=True),
        str(path))
    assert ok["passed"] is True, ok["checks"][-1]["detail"]
    # The same trace anchored on State 0 is 600 ms — outside the band.
    bad = rs.evaluate_replay_csv(
        _entry([_elapsed_spec()], skip_bringup_gate=True), str(path))
    assert bad["passed"] is False


def test_latch_elapsed_band_import_guard_refuses_a_degenerate_band(monkeypatch):
    """The import-shape guard is the only thing standing between a typo and a
    band that silently stops discriminating."""
    for bad in ((0.45, 0.20), (0.30, 0.30), (-0.1, 0.4)):
        monkeypatch.setattr(
            rs, "REPLAY_SUITE",
            [{"log": "SYN_BAND", "checks": [_elapsed_spec(band=bad)]}])
        with pytest.raises(AssertionError, match="0 <= lo < hi"):
            rs._assert_check_spec_shapes()


def test_latch_elapsed_band_import_guard_accepts_the_real_shape(monkeypatch):
    """Converse, so the negative above pins the defect and not a function that
    always raises."""
    monkeypatch.setattr(
        rs, "REPLAY_SUITE",
        [{"log": "SYN_BAND_OK", "checks": [_elapsed_spec()]}])
    rs._assert_check_spec_shapes()          # must not raise


# -- latch_precedes_uv (F4, WP0097's reclassification premise) ──────────────

def _oc_then_uv_rows(oc_t, uv_t, t_end=None):
    """OC_FC latches at `oc_t`; the injected V_bus drops under
    LIMIT_V_BUS_MIN at `uv_t` (None = never).  10 ms rows, shifted past the
    preamble so the stimulus window sees them."""
    t_end = t_end or (max(oc_t, uv_t or 0.0) + 0.5)
    rows = []
    t = 0.0
    while t < t_end - 1e-9:
        rows.append({
            "t": round(rs.REPLAY_PREAMBLE_S + t, 4),
            "state": 2,
            "V_bus": 11.0 if (uv_t is not None and t >= uv_t) else 15.9,
            "fault_flags": (rs.FAULT_OC_FC | rs.FAULT_ERROR) if t >= oc_t else 0,
        })
        t += 0.01
    return [_bringup_row(0.0)] + rows


def _uv_order_spec(min_lead_ms=10.0):
    return {"kind": "latch_precedes_uv", "name": "oc_precedes_uv",
            "bit": rs.FAULT_OC_FC, "min_lead_ms": min_lead_ms}


def test_latch_precedes_uv_passes_when_the_oc_leads(tmp_path):
    """WP0097's measured shape: OC latches ~22 ms before the bus goes sub-12."""
    path = tmp_path / "a.csv"
    write_replay_csv(path, _oc_then_uv_rows(oc_t=1.00, uv_t=1.03))
    res = rs.evaluate_replay_csv(_entry([_uv_order_spec()]), str(path))
    detail = res["checks"][-1]["detail"]
    assert res["passed"] is True, detail
    assert "lead of +30.00 ms" in detail


def test_latch_precedes_uv_fails_when_the_bus_collapses_first(tmp_path):
    """The failure the check exists for: the same green 'OC_FC latched' verdict
    off the wrong mechanism."""
    path = tmp_path / "a.csv"
    write_replay_csv(path, _oc_then_uv_rows(oc_t=1.05, uv_t=1.00))
    res = rs.evaluate_replay_csv(_entry([_uv_order_spec()]), str(path))
    detail = res["checks"][-1]["detail"]
    assert res["passed"] is False, detail
    assert "SHORT of the 10 ms" in detail


def test_latch_precedes_uv_fails_a_collapsed_but_positive_lead(tmp_path):
    """A 10 ms floor, not a sign test: a 5 ms lead is ordered correctly and
    still refused, because at that separation the attribution is not safe."""
    path = tmp_path / "a.csv"
    write_replay_csv(path, _oc_then_uv_rows(oc_t=1.00, uv_t=1.005))
    res = rs.evaluate_replay_csv(_entry([_uv_order_spec()]), str(path))
    assert res["passed"] is False


def test_latch_precedes_uv_passes_when_the_bus_never_collapses(tmp_path):
    """No competing mechanism at all is strictly stronger than leading one,
    and the detail must say which case it reported."""
    path = tmp_path / "a.csv"
    write_replay_csv(path, _oc_then_uv_rows(oc_t=1.00, uv_t=None))
    res = rs.evaluate_replay_csv(_entry([_uv_order_spec()]), str(path))
    detail = res["checks"][-1]["detail"]
    assert res["passed"] is True, detail
    assert "absent, not merely later" in detail


def test_latch_precedes_uv_fails_with_no_latch(tmp_path):
    """An ordering assertion with nothing to order is not evidence."""
    path = tmp_path / "a.csv"
    write_replay_csv(path, _oc_then_uv_rows(oc_t=99.0, uv_t=1.00, t_end=2.0))
    res = rs.evaluate_replay_csv(_entry([_uv_order_spec()]), str(path))
    detail = res["checks"][-1]["detail"]
    assert res["passed"] is False, detail
    assert "never LATCHED" in detail


def test_latch_precedes_uv_ignores_the_synthetic_preamble(tmp_path):
    """M5/L2: the harness's own preamble rails must never decide a stimulus
    question. A sub-12 V sample INSIDE the preamble is not the recorded
    collapse and must not shorten the measured lead."""
    rows = _oc_then_uv_rows(oc_t=1.00, uv_t=None)
    for r in rows:
        if 0.5 < r["t"] < 1.0:          # inside REPLAY_PREAMBLE_S (2.5 s)
            r["V_bus"] = 5.0
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(_entry([_uv_order_spec()]), str(path))
    assert res["passed"] is True, res["checks"][-1]["detail"]


def test_wp0097_entry_carries_the_ordering_check():
    """The real entry: the reclassification's premise is asserted, paired with
    the latch it orders, at the floor derived from the 22.37 ms measurement."""
    entry = rs.suite_index()["WP0097"]
    spec = next(c for c in entry["checks"] if c["kind"] == "latch_precedes_uv")
    assert spec["bit"] == rs.FAULT_OC_FC
    assert spec["min_lead_ms"] == pytest.approx(10.0)
    assert spec["min_lead_ms"] < 22.37          # the measured lead
    assert any(c["kind"] == "fault_latched" and c["bit"] == rs.FAULT_OC_FC
               for c in entry["checks"])


def test_latch_precedes_uv_import_guard_needs_a_positive_lead(monkeypatch):
    monkeypatch.setattr(rs, "REPLAY_SUITE", [{
        "log": "SYN_ORDER",
        "checks": [{"kind": "fault_latched", "name": "oc", "bit": rs.FAULT_OC_FC,
                    "require_stimulus": False},
                   _uv_order_spec(min_lead_ms=0.0)]}])
    with pytest.raises(AssertionError, match="positive `min_lead_ms`"):
        rs._assert_check_spec_shapes()


def test_latch_precedes_uv_import_guard_needs_the_paired_latch(monkeypatch):
    monkeypatch.setattr(rs, "REPLAY_SUITE", [{
        "log": "SYN_ORDER2", "checks": [_uv_order_spec()]}])
    with pytest.raises(AssertionError, match="orders a latch it does not"):
        rs._assert_check_spec_shapes()


def test_elapsed_from_state_without_a_band_is_refused(monkeypatch):
    spec = {"kind": "fault_latched", "name": "x", "bit": rs.FAULT_UV_BUS,
            "require_stimulus": False, "elapsed_from_state": 0}
    monkeypatch.setattr(rs, "REPLAY_SUITE",
                        [{"log": "SYN_ANCHOR", "checks": [spec]}])
    with pytest.raises(AssertionError, match="names the anchor"):
        rs._assert_check_spec_shapes()


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


# -- steps_onto_rail_within (FU4, 2026-08-31) --------------------------------
# `skip_preamble` is used throughout this block so `after_s` (which defaults
# to data.preamble_s) resolves to 0.0 and the stimulus can start at t=0 --
# the after_s-defaulting behaviour itself is covered separately below.

def test_check_steps_onto_rail_within_prompt_crossing_pass(tmp_path):
    """|I_cmd| reaches level_a well inside the budget -- PASS, and the detail
    carries the MEASURED latency."""
    rows = _with_bringup(_uniform_rows(
        0.5, 0.001, current=lambda t: 11.5 if t >= 0.05 else 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "steps_onto_rail_within", "name": "sorw",
            "level_a": 11.0, "within_s": 0.15, "after_s": 0.0}
    res = rs.evaluate_replay_csv(_entry([spec], skip_preamble=True), str(path))
    detail = res["checks"][-1]["detail"]
    assert res["checks"][-1]["passed"] is True
    assert res["passed"] is True
    assert "reached 11.0 A at t=0.050" in detail
    assert "ms after" in detail


def test_check_steps_onto_rail_within_late_crossing_fails_with_actual_time(tmp_path):
    """A crossing that happens, but later than within_s after after_s, must
    FAIL -- and the detail must carry the ACTUAL crossing time, not just the
    budget."""
    rows = _with_bringup(_uniform_rows(
        0.5, 0.001, current=lambda t: 11.5 if t >= 0.20 else 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "steps_onto_rail_within", "name": "sorw",
            "level_a": 11.0, "within_s": 0.15, "after_s": 0.0}
    res = rs.evaluate_replay_csv(_entry([spec], skip_preamble=True), str(path))
    detail = res["checks"][-1]["detail"]
    assert res["checks"][-1]["passed"] is False
    assert res["passed"] is False
    assert "reached 11.0 A at t=0.200" in detail
    assert "later than the 150 ms budget" in detail


def test_check_steps_onto_rail_within_never_crossing_fails_and_names_the_peak(tmp_path):
    """|I_cmd| never reaches level_a at all -- FAIL, and the detail must name
    the PEAK actually observed (the strongest available evidence that the
    loop did not respond)."""
    rows = _with_bringup(_uniform_rows(
        0.5, 0.001, current=lambda t: 4.0 if 0.05 <= t < 0.10 else 0.5))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "steps_onto_rail_within", "name": "sorw",
            "level_a": 11.0, "within_s": 0.15, "after_s": 0.0}
    res = rs.evaluate_replay_csv(_entry([spec], skip_preamble=True), str(path))
    detail = res["checks"][-1]["detail"]
    assert res["checks"][-1]["passed"] is False
    assert res["passed"] is False
    assert "NEVER crossed 11.0 A" in detail
    assert "peak +4.0000 A" in detail


def test_check_steps_onto_rail_within_after_s_defaults_to_preamble_s_normally(tmp_path):
    """Omitting `after_s` from the spec must resolve to data.preamble_s --
    2.5 s for a normal entry (no skip_preamble). A crossing right at the
    preamble boundary (t=preamble_s) is `dt=0`, well inside budget."""
    rows = _with_bringup(_uniform_rows(
        3.0, 0.01, current=lambda t: 11.5 if t >= rs.REPLAY_PREAMBLE_S else 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "steps_onto_rail_within", "name": "sorw",
            "level_a": 11.0, "within_s": 0.15}   # no after_s
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))   # NOT skip_preamble
    detail = res["checks"][-1]["detail"]
    assert res["checks"][-1]["passed"] is True
    assert f"t={rs.REPLAY_PREAMBLE_S:.3f}" in detail


def test_check_steps_onto_rail_within_after_s_defaults_to_zero_under_skip_preamble(tmp_path):
    """The converse: a skip_preamble entry resolves the same omitted
    `after_s` to 0.0 -- data.preamble_s is 0.0 for it (entry_preamble_s())."""
    rows = _with_bringup(_uniform_rows(
        0.5, 0.001, current=lambda t: 11.5 if t >= 0.05 else 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "steps_onto_rail_within", "name": "sorw",
            "level_a": 11.0, "within_s": 0.15}   # no after_s
    res = rs.evaluate_replay_csv(_entry([spec], skip_preamble=True), str(path))
    detail = res["checks"][-1]["detail"]
    assert res["checks"][-1]["passed"] is True
    assert "reached 11.0 A at t=0.050" in detail


# -- MOTOR_RESPONSE_KINDS / NOT_EXERCISED tagging for steps_onto_rail_within
# (FU4): a caller that forgets `replay_commands: True` on an entry using this
# check gets a flat-zero command series (no commander => the board never
# leaves Idle). check_steps_onto_rail_within's own verdict on a flat-zero
# series is a hard FAIL ("never crossed") -- membership in MOTOR_RESPONSE_KINDS
# does not change `passed`, it only PREPENDS the NOT_EXERCISED explanation to
# the (still-failing) detail, per the asymmetry documented at the set's
# definition. This is the ACTUAL implemented behaviour: a loud TAGGED FAIL,
# never a silent tagged pass -- there is no FAIL-vs-tagged-pass ambiguity to
# report here, the code and its own comment agree.

def test_steps_onto_rail_within_in_motor_response_kinds_set():
    assert "steps_onto_rail_within" in rs.MOTOR_RESPONSE_KINDS


def test_steps_onto_rail_within_not_exercised_tag_on_flat_zero_without_replay_commands(tmp_path):
    rows = _with_bringup(_uniform_rows(0.5, 0.01, current=lambda t: 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "steps_onto_rail_within", "name": "sorw",
            "level_a": 11.0, "within_s": 0.15, "after_s": 0.0}
    res = rs.evaluate_replay_csv(
        _entry([spec], skip_preamble=True, replay_commands=False), str(path))
    check = res["checks"][-1]
    # Implemented behaviour: passed stays False (a TAGGED FAIL), the tag is
    # PREPENDED to the ordinary "NEVER crossed" detail, not a substitute for it.
    assert check["passed"] is False
    assert check["detail"].startswith(rs.NOT_EXERCISED_PREFIX)
    assert "NEVER crossed 11.0 A" in check["detail"]
    assert res["passed"] is False
    assert res["n_checks_not_exercised"] >= 1


def test_steps_onto_rail_within_no_tag_when_replay_commands_true_even_if_flat_zero(tmp_path):
    """The tag is gated on `cmds_replayed is False` -- an entry that DOES set
    replay_commands never gets the NOT_EXERCISED substitution, even if (e.g.
    a firmware regression) the command series came back flat zero anyway. It
    still fails on its own terms (never crossed), just without the tag."""
    rows = _with_bringup(_uniform_rows(0.5, 0.01, current=lambda t: 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "steps_onto_rail_within", "name": "sorw",
            "level_a": 11.0, "within_s": 0.15, "after_s": 0.0}
    res = rs.evaluate_replay_csv(
        _entry([spec], skip_preamble=True, replay_commands=True), str(path))
    check = res["checks"][-1]
    assert check["passed"] is False
    assert not check["detail"].startswith(rs.NOT_EXERCISED_PREFIX)
    assert "NEVER crossed 11.0 A" in check["detail"]


# -- drive_loop_stepped (--replay-commands) ----------------------------------

def test_check_drive_loop_stepped_pass(tmp_path):
    rows = _with_bringup_and_grace(_uniform_rows(0.5, 0.001, current=lambda t: 2.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "drive_loop_stepped", "name": "dls"}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["checks"][-1]["passed"] is True
    assert res["passed"] is True
    assert "drive loop stepped" in res["checks"][-1]["detail"]


def test_check_drive_loop_stepped_fail_flat(tmp_path):
    rows = _with_bringup_and_grace(_uniform_rows(0.5, 0.001, current=lambda t: 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "drive_loop_stepped", "name": "dls"}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["checks"][-1]["passed"] is False
    assert res["passed"] is False
    assert "never stepped" in res["checks"][-1]["detail"]


def test_check_drive_loop_stepped_no_observation_frames_at_all_fails_not_raises(tmp_path):
    """A CSV with rows but never an observation frame at all -- both
    `data.current` and `data.current_recorded` are empty, so `series` falls
    back to nothing and the check must fail with the 'never answered' detail,
    not raise. Exercised as a unit call on check_drive_loop_stepped() directly
    (rather than through evaluate_replay_csv()): a zero-observation CSV never
    reaches per-check evaluation there at all -- the bring-up gate fails first
    and short-circuits every entry check (see
    test_evaluate_zero_observation_csv_all_checks_fail_with_note) -- so this
    branch is reachable only by calling the check function itself."""
    rows = _uniform_rows(0.1, 0.01)
    for r in rows:
        r["no_obs"] = True
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    assert data.current == [], "sanity: no observation frames at all"
    passed, detail = rs.check_drive_loop_stepped(data, {"kind": "drive_loop_stepped"})
    assert passed is False
    assert "never answered" in detail


def test_check_drive_loop_stepped_boundary_min_a_inclusive(tmp_path):
    """abs(i) >= min_a is the comparison (source: `if abs(i) >= min_a`) -- a
    sample sitting EXACTLY at DRIVE_STEPPED_MIN_A must count toward n, not be
    excluded by a strict '>' the source does not use."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.5, 0.001, current=lambda t: rs.DRIVE_STEPPED_MIN_A))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "drive_loop_stepped", "name": "dls"}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["checks"][-1]["passed"] is True


def test_check_drive_loop_stepped_boundary_min_samples_exact_pass_one_fewer_fails(tmp_path):
    """`n < min_n` is the comparison (source), so n == min_n passes and
    n == min_n - 1 fails -- exercised on both sides directly via the spec-level
    min_samples override, independent of the module default."""
    def _rows_with_n_stepped(n):
        rows = []
        for i in range(200):
            rows.append({"t": i * 0.001, "current": 5.0 if i < n else 0.0})
        return _with_bringup_and_grace(rows)

    spec = {"kind": "drive_loop_stepped", "name": "dls", "min_samples": 50}

    path_pass = tmp_path / "exact.csv"
    write_replay_csv(path_pass, _rows_with_n_stepped(50))
    res_pass = rs.evaluate_replay_csv(_entry([spec]), str(path_pass))
    assert res_pass["checks"][-1]["passed"] is True

    path_fail = tmp_path / "one_fewer.csv"
    write_replay_csv(path_fail, _rows_with_n_stepped(49))
    res_fail = rs.evaluate_replay_csv(_entry([spec]), str(path_fail))
    assert res_fail["checks"][-1]["passed"] is False


def test_check_drive_loop_stepped_opt_in_entry_with_flat_current_is_a_real_fail(tmp_path):
    """A replay_commands: True entry whose recorded current stayed flat zero
    must FAIL drive_loop_stepped for real -- the NOT-EXERCISED retagging below
    applies only to entries that do NOT set replay_commands, so this is not
    silently downgraded to a soft pass."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.5, 0.001, fault_flags=lambda t: 0, current=lambda t: 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    entry = _entry([
        {"kind": "drive_loop_stepped", "name": "dls"},
        {"kind": "bounded_current", "name": "bc"},
    ], replay_commands=True)
    res = rs.evaluate_replay_csv(entry, str(path))
    by_name = {c["name"]: c for c in res["checks"]}
    assert by_name["dls"]["passed"] is False
    assert not by_name["dls"]["detail"].startswith(rs.NOT_EXERCISED_PREFIX)
    # bounded_current still passes (0 A is within the clamp), and it STILL
    # carries the plain VACUOUS_TAG (command_is_identically_zero() is a
    # property of the DATA, independent of whether commands were replayed) --
    # only the NOT_EXERCISED retagging is gated on cmds_replayed being False.
    assert by_name["bc"]["passed"] is True
    assert rs.VACUOUS_TAG in by_name["bc"]["detail"]
    assert not by_name["bc"]["detail"].startswith(rs.NOT_EXERCISED_PREFIX)
    assert res["passed"] is False


# -- drive_loop_stepped: drive_min_frac (FU3, --replay-commands) ------------

def test_check_drive_loop_stepped_drive_min_frac_none_default_matches_previous_behavior(
        tmp_path):
    """No drive_min_frac in the spec (the module default) must be BYTE-
    IDENTICAL to the pre-FU3 behaviour: only the absolute min_samples floor
    is judged, and the detail carries no fraction requirement clause."""
    rows = _with_bringup_and_grace(_uniform_rows(0.5, 0.001, current=lambda t: 2.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "drive_loop_stepped", "name": "dls"}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["checks"][-1]["passed"] is True
    assert "AND >=" not in res["checks"][-1]["detail"]


def test_check_drive_loop_stepped_drive_min_frac_just_above_and_below(tmp_path):
    """Fraction boundary: 1000 recorded-window samples, drive_min_frac=0.40 --
    401 stepped samples (40.1%) passes, 399 (39.9%) fails, both comfortably
    clear of the 50-sample absolute floor either way."""
    def build(n_above):
        rows = [{"t": i * 0.001, "current": 5.0 if i < n_above else 0.0}
               for i in range(1000)]
        return _with_bringup_and_grace(rows)

    spec = {"kind": "drive_loop_stepped", "name": "dls", "drive_min_frac": 0.40}

    path_above = tmp_path / "above.csv"
    write_replay_csv(path_above, build(401))
    res_above = rs.evaluate_replay_csv(_entry([spec]), str(path_above))
    assert res_above["checks"][-1]["passed"] is True

    path_below = tmp_path / "below.csv"
    write_replay_csv(path_below, build(399))
    res_below = rs.evaluate_replay_csv(_entry([spec]), str(path_below))
    assert res_below["checks"][-1]["passed"] is False
    assert "DEGRADED" in res_below["checks"][-1]["detail"]


def test_check_drive_loop_stepped_absolute_floor_passes_but_fraction_fails(tmp_path):
    """THE key case FU3 exists for: the 50-sample absolute floor sits orders
    of magnitude below real activity, so a command path that DEGRADED to a
    small fraction of its duty cycle still clears the absolute floor -- only
    the fraction actually catches it. Same CSV, with vs without the fraction
    spec, to prove the absolute-floor-alone verdict really would have been a
    PASS."""
    rows = [{"t": i * 0.001, "current": 5.0 if i < 60 else 0.0} for i in range(1000)]
    rows = _with_bringup_and_grace(rows)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)

    spec_frac = {"kind": "drive_loop_stepped", "name": "dls", "drive_min_frac": 0.5}
    res_frac = rs.evaluate_replay_csv(_entry([spec_frac]), str(path))
    detail = res_frac["checks"][-1]["detail"]
    assert res_frac["checks"][-1]["passed"] is False
    assert "looks DEGRADED" in detail
    assert "floor PASSED" in detail

    spec_abs = {"kind": "drive_loop_stepped", "name": "dls2"}
    res_abs = rs.evaluate_replay_csv(_entry([spec_abs]), str(path))
    assert res_abs["checks"][-1]["passed"] is True   # confirms the "PASSED" claim above


def test_check_drive_loop_stepped_passing_detail_includes_percentage(tmp_path):
    """FU3: the passing detail now reports the stepped fraction as a
    percentage even when drive_min_frac is not given (informational)."""
    rows = _with_bringup_and_grace(_uniform_rows(0.5, 0.001, current=lambda t: 2.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(
        _entry([{"kind": "drive_loop_stepped", "name": "dls"}]), str(path))
    assert res["checks"][-1]["passed"] is True
    assert "(100.0%) have" in res["checks"][-1]["detail"]


def test_check_drive_loop_stepped_fail_detail_states_frac_requirement_when_given(tmp_path):
    rows = _with_bringup_and_grace(_uniform_rows(0.5, 0.001, current=lambda t: 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    spec = {"kind": "drive_loop_stepped", "name": "dls", "drive_min_frac": 0.35}
    res = rs.evaluate_replay_csv(_entry([spec]), str(path))
    assert res["checks"][-1]["passed"] is False
    assert "AND >= 35% of the window" in res["checks"][-1]["detail"]


# -- share_loop_actuated (FU1, --replay-commands) ----------------------------
# r = BT_code / (FC_code + BT_code) over MDAC words carrying the load-and-
# update control nibble (0x1nnn); MDAC_CMD_LOAD_UPDATE/MDAC_CODE_MASK below
# are re-derived from the module's own constants, not hand-copied literals.

def test_check_share_loop_actuated_pass_span_above_floor(tmp_path):
    """A ratio that sweeps well past the 0.20 floor passes."""
    def mdac_fc(t):
        bt_code = int(100 + (t / 0.5) * 3000)
        return rs.MDAC_CMD_LOAD_UPDATE | (4000 - bt_code)

    def mdac_bt(t):
        bt_code = int(100 + (t / 0.5) * 3000)
        return rs.MDAC_CMD_LOAD_UPDATE | bt_code

    rows = _with_bringup_and_grace(
        _uniform_rows(0.5, 0.001, mdac_fc=mdac_fc, mdac_bt=mdac_bt,
                      fault_flags=lambda t: 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(
        _entry([{"kind": "share_loop_actuated", "name": "sla"}]), str(path))
    assert res["checks"][-1]["passed"] is True
    assert "share actuator moved" in res["checks"][-1]["detail"]


def test_check_share_loop_actuated_fail_flat_split_nonzero_code(tmp_path):
    """A CONSTANT NONZERO split (r = 0.5 throughout, via 0x1800/0x1800 -- a
    real code write every sample, NOT the code==0 'unusable' case) must FAIL
    on span, distinctly from the 'not measured' branch."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.5, 0.001, mdac_fc=lambda t: 0x1800, mdac_bt=lambda t: 0x1800,
                      fault_flags=lambda t: 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(
        _entry([{"kind": "share_loop_actuated", "name": "sla"}]), str(path))
    assert res["checks"][-1]["passed"] is False
    assert "did not move" in res["checks"][-1]["detail"]
    assert "spanned only 0.0000" in res["checks"][-1]["detail"]


def test_check_share_loop_actuated_non_load_update_nibble_is_not_measured(tmp_path):
    """A control nibble other than 0x1 is not a code write at all and is
    skipped -- the FC word always carries nibble 0x2 here, so ZERO usable
    samples exist and the verdict must be 'not measured', not a flat-split
    failure (a DIFFERENT case -- see the previous test)."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.5, 0.001, mdac_fc=lambda t: 0x2800, mdac_bt=lambda t: 0x1800,
                      fault_flags=lambda t: 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(
        _entry([{"kind": "share_loop_actuated", "name": "sla"}]), str(path))
    assert res["checks"][-1]["passed"] is False
    assert "not measured" in res["checks"][-1]["detail"]
    assert "usable MDAC sample" in res["checks"][-1]["detail"]


def test_check_share_loop_actuated_below_min_samples_floor(tmp_path):
    """Fewer usable samples than min_samples (default or overridden) fails
    'not measured', even though every sample IS a valid load-and-update code
    (the previous test's zero-usable-samples case is a DIFFERENT reason for
    the same verdict)."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.01, 0.001, mdac_fc=lambda t: 0x1C00, mdac_bt=lambda t: 0x1400,
                      fault_flags=lambda t: 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(
        _entry([{"kind": "share_loop_actuated", "name": "sla"}]), str(path))
    assert res["checks"][-1]["passed"] is False
    assert "not measured" in res["checks"][-1]["detail"]
    assert f"need >= {rs.SHARE_ACTUATED_MIN_SAMPLES}" in res["checks"][-1]["detail"]


def test_check_share_loop_actuated_min_samples_override(tmp_path):
    """The same CSV that satisfies the module default min_samples fails
    against a spec-level override demanding more than exist."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.5, 0.001, mdac_fc=lambda t: 0x1C00, mdac_bt=lambda t: 0x1400,
                      fault_flags=lambda t: 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    default_res = rs.evaluate_replay_csv(
        _entry([{"kind": "share_loop_actuated", "name": "sla"}]), str(path))
    assert default_res["checks"][-1]["passed"] is False   # flat split, but WAS measured

    override_res = rs.evaluate_replay_csv(
        _entry([{"kind": "share_loop_actuated", "name": "sla",
                "min_samples": 100000}]), str(path))
    assert override_res["checks"][-1]["passed"] is False
    assert "not measured" in override_res["checks"][-1]["detail"]
    assert "need >= 100000" in override_res["checks"][-1]["detail"]


def test_check_share_loop_actuated_min_span_override(tmp_path):
    """A flat split (span 0.0) that would fail the module default passes
    against a spec-level min_span of 0.0."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.5, 0.001, mdac_fc=lambda t: 0x1800, mdac_bt=lambda t: 0x1800,
                      fault_flags=lambda t: 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    res = rs.evaluate_replay_csv(
        _entry([{"kind": "share_loop_actuated", "name": "sla", "min_span": 0.0}]),
        str(path))
    assert res["checks"][-1]["passed"] is True


def test_replay_suite_share_loop_actuated_only_on_the_five_documented_entries():
    """FU1: share_loop_actuated is opted into by exactly the five entries
    whose recorded share_sp varies (YP0152/YP0166/YP0196/YP0214/ML0203) --
    every constant-setpoint entry (including the other opted-in
    drive_loop_stepped-only entries) must NOT carry it."""
    expected = {"YP0152", "YP0166", "YP0196", "YP0214", "ML0203"}
    have = {e["log"] for e in rs.REPLAY_SUITE
           if any(c["kind"] == "share_loop_actuated" for c in e["checks"])}
    assert have == expected
    # sanity: every one of the five is itself replay_commands: True
    index = rs.suite_index()
    for log in expected:
        assert index[log]["replay_commands"] is True, log


# ─────────────────────────────────────────────────────────────────────────
# 2b. NOT_EXERCISED tagging (replay_commands-aware, supersedes the plain
#     VACUOUS_TAG on entries that do not opt in)
# ─────────────────────────────────────────────────────────────────────────

def test_not_exercised_tag_only_on_motor_response_kinds_for_non_opt_in_entry(tmp_path):
    """no_fault is NOT in MOTOR_RESPONSE_KINDS -- it must never carry the
    NOT-EXERCISED prefix, even on a command-free entry with flat current."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.2, 0.005, fault_flags=lambda t: 0, current=lambda t: 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    entry = _entry([{"kind": "no_fault", "name": "nf"},
                    {"kind": "bounded_current", "name": "bc"}])  # no replay_commands key
    res = rs.evaluate_replay_csv(entry, str(path))
    by_name = {c["name"]: c for c in res["checks"]}
    assert not by_name["nf"]["detail"].startswith(rs.NOT_EXERCISED_PREFIX)
    assert by_name["bc"]["detail"].startswith(rs.NOT_EXERCISED_PREFIX)
    assert by_name["bc"]["passed"] is True
    assert res["n_checks_not_exercised"] == 1


def test_not_exercised_tag_absent_on_opted_in_entry_even_with_flat_current(tmp_path):
    rows = _with_bringup_and_grace(
        _uniform_rows(0.2, 0.005, fault_flags=lambda t: 0, current=lambda t: 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    entry = _entry([{"kind": "bounded_current", "name": "bc"}], replay_commands=True)
    res = rs.evaluate_replay_csv(entry, str(path))
    by_name = {c["name"]: c for c in res["checks"]}
    assert not by_name["bc"]["detail"].startswith(rs.NOT_EXERCISED_PREFIX)
    assert res["n_checks_not_exercised"] == 0


def test_not_exercised_tag_absent_when_current_is_not_flat_regardless_of_replay_commands(tmp_path):
    """The NOT-EXERCISED condition is (cmds_replayed is False) AND (kind in
    MOTOR_RESPONSE_KINDS) AND (command_is_identically_zero()) -- all three,
    not just the absence of replay_commands."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.2, 0.005, fault_flags=lambda t: 0,
                      current=lambda t: 5.0 if t > 0.1 else 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    entry = _entry([{"kind": "bounded_current", "name": "bc"}])
    res = rs.evaluate_replay_csv(entry, str(path))
    by_name = {c["name"]: c for c in res["checks"]}
    assert not by_name["bc"]["detail"].startswith(rs.NOT_EXERCISED_PREFIX)
    assert res["n_checks_not_exercised"] == 0


def test_n_checks_vacuous_equals_plain_vacuous_plus_not_exercised(tmp_path):
    """n_checks_vacuous keeps its established total-non-evidence meaning: the
    disjoint-by-construction not-exercised count plus whatever plain vacuous
    checks remain (none, here, since every MOTOR_RESPONSE_KINDS check on a
    non-opt-in flat-current entry is retagged not-exercised)."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.2, 0.005, fault_flags=lambda t: 0, current=lambda t: 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    entry = _entry([{"kind": "bounded_current", "name": "bc"},
                    {"kind": "no_rail_limit_cycle", "name": "nrlc"}])
    res = rs.evaluate_replay_csv(entry, str(path))
    assert res["n_checks_not_exercised"] == 2
    assert res["n_checks_vacuous"] == 2
    assert res["n_checks_substantive"] == res["n_checks"] - 2
    assert any("2 of" in n and "NOT EXERCISED" in n for n in res["notes"])


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


# ── R-MED-1 (campaign 080905): TP0010's BT twin of the FC clamp ────────────

def test_tp0010_alone_carries_the_i_bt_clamp():
    """MEASURED, not assumed: TP0010's |I_batt| peaks at 3.5861 A against
    LIMIT_I_BT_MAX 3.0 and would latch OC_BT before the UV collapse is scored.
    TP0053's peaks at 2.3451 A and deliberately gets NO clamp -- clamping a
    trajectory that needs no clamping would modify a recording for nothing."""
    index = rs.suite_index()
    assert index["TP0010"]["i_bt_clamp_a"] == pytest.approx(rs.UV_PAIR_I_BT_CLAMP_A)
    assert index["TP0053"].get("i_bt_clamp_a") is None
    for e in rs.REPLAY_SUITE:
        if e["log"] != "TP0010":
            assert e.get("i_bt_clamp_a") is None, e["log"]
    # The clamp must sit UNDER the firmware limit or it does not remove the
    # OC stimulus it exists to remove.
    assert rs.UV_PAIR_I_BT_CLAMP_A < 3.0


def test_tp0010_declares_the_bt_clamp_in_its_why():
    """Every deliberate trajectory modification is DECLARED at every scoring
    site -- table, argv, banner, note. This is the table half."""
    why = rs.suite_index()["TP0010"]["why"]
    assert "I_batt" in why and "CLAMPED" in why
    assert "3.586" in why          # the measurement that justifies it
    assert "TP0053" in why         # ...and why its twin does not get one


def test_build_sim_argv_mirrors_the_i_bt_clamp():
    """A modifier declared in the table and not mirrored here means a hand-run
    replay silently differs from a suite-run one."""
    argv = rs.build_sim_argv(rs.suite_index()["TP0010"], "/tmp/csvdir")
    idx = argv.index("--replay-i-bt-clamp")
    assert float(argv[idx + 1]) == pytest.approx(rs.UV_PAIR_I_BT_CLAMP_A)
    assert "--replay-i-bt-clamp" not in rs.build_sim_argv(
        rs.suite_index()["TP0053"], "/tmp/csvdir")


# ── R-LOW-1: ML0151's OC knife-edge, asserted rather than narrated ─────────

class _FakeReplayData:
    def __init__(self, i_fc, preamble_s=0.0):
        self.i_fc = i_fc
        self.preamble_s = preamble_s


def test_i_fc_max_in_band_three_branches():
    spec = {"min_a": 1.20, "max_a": 1.40}
    ok, why = rs.check_i_fc_max_in_band(
        _FakeReplayData([(1.0, 0.8), (2.0, 1.354)]), spec)
    assert ok and "1.3540" in why
    # ABOVE: the entry has become a deviation-class OC stimulus.
    ok, why = rs.check_i_fc_max_in_band(
        _FakeReplayData([(1.0, 1.45)]), spec)
    assert not ok and "ABOVE" in why
    # BELOW: the near-limit condition the entry documents is gone.
    ok, why = rs.check_i_fc_max_in_band(
        _FakeReplayData([(1.0, 0.4)]), spec)
    assert not ok and "BELOW" in why
    # UNMEASURED: absent stimulus is not a pass.
    ok, why = rs.check_i_fc_max_in_band(_FakeReplayData([]), spec)
    assert not ok and "absent" in why


def test_i_fc_max_in_band_reads_magnitude_and_skips_the_preamble():
    """LIMIT_I_FC_MAX is judged on |I_fc| in the firmware, and the synthetic
    preamble's currents are this harness's invention, not the stimulus."""
    spec = {"min_a": 1.20, "max_a": 1.40}
    ok, why = rs.check_i_fc_max_in_band(
        _FakeReplayData([(1.0, -1.30)], preamble_s=0.0), spec)
    assert ok and "1.3000" in why
    # A big preamble sample must not be read as the stimulus peak.
    ok, _ = rs.check_i_fc_max_in_band(
        _FakeReplayData([(1.0, 9.0), (3.0, 1.30)], preamble_s=2.5), spec)
    assert ok


def test_ml0151_pins_its_oc_knife_edge():
    entry = rs.suite_index()["ML0151"]
    pin = next(c for c in entry["checks"] if c["kind"] == "i_fc_max_in_band")
    # Measured peak 1.354 A; ceiling IS the firmware limit, floor 11 % below.
    assert pin["max_a"] == pytest.approx(rs.LIMIT_I_FC_MAX_A) == pytest.approx(1.4)
    assert pin["min_a"] == pytest.approx(1.20)
    assert pin["min_a"] < 1.354
    # Registered in the dispatcher, and its field set pinned by the shape
    # guard -- a field typed onto the wrong kind reads as an assertion and is
    # silently ignored, which is what that guard exists to catch.
    assert rs.CHECK_KINDS["i_fc_max_in_band"] is rs.check_i_fc_max_in_band
    # The import-time field guard knows the kind (it runs over the whole
    # table at import, so a stray field on this check would have refused the
    # module load).
    rs._assert_check_spec_shapes()


# ─────────────────────────────────────────────────────────────────────────
# 4c. --replay-commands: REPLAY_SUITE table pins / build_sim_argv mirroring
# ─────────────────────────────────────────────────────────────────────────

REPLAY_COMMANDS_TRUE_SET = {
    "ML0137", "ML0140", "ML0146", "ML0149", "ML0151", "ML0153", "ML0164",
    "ML0165", "ML0169", "ML0203", "YP0152", "YP0166", "YP0196", "YP0214",
    "SY0001",   # FU4, 2026-08-31: replay_commands is MANDATORY on this entry
                # (its entire stimulus IS the recorded v_sp) -- see the
                # "fourth bucket" decision comment in hil_replay_suite.py.
}


def test_replay_suite_replay_commands_true_set_matches_the_15_entries():
    trues = {e["log"] for e in rs.REPLAY_SUITE if e.get("replay_commands") is True}
    assert trues == REPLAY_COMMANDS_TRUE_SET
    assert len(trues) == 15


def test_replay_suite_every_entry_declares_replay_commands_as_a_bool():
    """Every entry must set replay_commands to True or False explicitly (not
    omit it) -- an implicit falsy-but-absent value would silently escape the
    fault-path-purity/rule-2/rule-3 review discipline the table comment
    documents, and build_sim_argv's `.get()` would still work either way,
    hiding the omission."""
    for e in rs.REPLAY_SUITE:
        assert "replay_commands" in e, e["log"]
        assert isinstance(e["replay_commands"], bool), e["log"]


def test_replay_suite_true_entries_each_carry_a_drive_loop_stepped_check():
    for e in rs.REPLAY_SUITE:
        if e.get("replay_commands") is True:
            kinds = [c["kind"] for c in e["checks"]]
            assert "drive_loop_stepped" in kinds, e["log"]


def test_replay_suite_false_entries_never_carry_a_drive_loop_stepped_check():
    for e in rs.REPLAY_SUITE:
        if e.get("replay_commands") is False:
            kinds = [c["kind"] for c in e["checks"]]
            assert "drive_loop_stepped" not in kinds, e["log"]


# FU3 (2026-08-31): a deliberate RATCHET from round-1 measured data -- each
# opted-in entry's drive_min_frac sits at roughly HALF its own measured
# stepped-fraction (round-1 campaign 20260831_000518). Pinned as a literal
# table so a future edit that silently loosens (or accidentally drops) one
# entry's floor fails here, not three log-analysis rounds later.
EXPECTED_DRIVE_MIN_FRAC = {
    "ML0203": 0.35, "YP0196": 0.44, "YP0214": 0.44, "ML0146": 0.34,
    "ML0149": 0.34, "ML0165": 0.20, "ML0169": 0.04, "YP0152": 0.44,
    "ML0151": 0.45, "ML0137": 0.27, "ML0140": 0.35, "ML0153": 0.32,
    "ML0164": 0.35, "YP0166": 0.44,
    # DE-PROVISIONALIZED 2026-08-31 (ledger fix queue, FU4): SY0001 has now
    # run a real campaign (20260831_191509, drive activity 0.5914 of the
    # recorded window) and carries a measured floor like every other entry --
    # see the module's own comment at the SY0001 entry.
    "SY0001": 0.30,
}


def test_replay_suite_drive_min_frac_table_pin():
    index = rs.suite_index()
    have = {}
    for log in EXPECTED_DRIVE_MIN_FRAC:
        entry = index[log]
        dls = [c for c in entry["checks"] if c["kind"] == "drive_loop_stepped"][0]
        have[log] = dls.get("drive_min_frac")
    assert have == pytest.approx(EXPECTED_DRIVE_MIN_FRAC)


def test_replay_suite_drive_min_frac_set_matches_true_entries_exactly():
    """Every replay_commands: True entry (which is exactly the set carrying a
    drive_loop_stepped check, per the test above) must ALSO carry a
    drive_min_frac -- FU3 ratcheted every opted-in entry, none was left on
    the bare absolute floor. Table completeness, not just table correctness.

    UPDATED 2026-08-31 (ledger fix queue): SY0001 was the last entry missing
    its ratchet (its first campaign had not landed at FU4 time); it is now
    de-provisionalized (`provisional: False`) and carries a measured
    drive_min_frac like every other opted-in entry (see EXPECTED_DRIVE_MIN_FRAC
    above), so the set-equality check below now covers ALL true entries with
    no residual exemption. The exemption MECHANISM is kept (keyed on the
    entry's own `provisional: True` flag, its key presence verified rather
    than just its truthiness, not a hardcoded log name) so a future
    first-campaign entry is exempted automatically and an entry that is
    simply missing its ratchet without declaring `provisional` still fails
    here -- there just happens to be nothing exempted by it right now."""
    have_frac = set()
    for e in rs.REPLAY_SUITE:
        for c in e["checks"]:
            if c["kind"] == "drive_loop_stepped" and c.get("drive_min_frac") is not None:
                have_frac.add(e["log"])
    assert have_frac == set(EXPECTED_DRIVE_MIN_FRAC)

    index = rs.suite_index()
    true_entries = {e["log"] for e in rs.REPLAY_SUITE
                    if e.get("replay_commands") is True}
    missing = true_entries - have_frac
    for log in missing:
        entry = index[log]
        assert "provisional" in entry, (
            f"{log} carries replay_commands but no drive_min_frac, and does "
            f"not declare `provisional` to justify the gap")
        assert entry["provisional"] is True, log
    assert have_frac == true_entries - missing   # tautological by construction;
    # states the invariant this test actually enforces: EVERY true entry not
    # exempted-by-provisional-flag must have a drive_min_frac.
    # 2026-08-31: SY0001 was the only entry ever exempted here, and it is now
    # de-provisionalized (see the test docstring), so `missing` is currently
    # empty -- asserted directly rather than re-hardcoding the old exemption.
    assert missing == set()


def test_replay_suite_drive_min_frac_values_are_roughly_half_the_documented_measurement():
    """Cross-check FU3's own stated derivation ('roughly HALF its own
    measured stepped-fraction') against the entry comments' measured values,
    parsed straight from the source rather than hand-copied -- a floor that
    silently drifted from ~0.5x the measurement would still be a valid float
    but would no longer be the ratchet the table claims to be."""
    import inspect
    import re
    src = inspect.getsource(rs)
    # "measured 0.696 of the recorded window over threshold ... drive_min_frac": 0.35
    # "over threshold" wraps across a comment-line boundary for most entries
    # but sits on one line for SY0001's (2026-08-31) -- both are the same
    # phrase, so the whitespace between the two words is intentionally
    # permissive (inline space OR a newline back into the next `#` line).
    pattern = re.compile(
        r'measured (\d+\.\d+) of the recorded window over[\s#]+threshold.*?'
        r'"drive_min_frac":\s*([\d.]+)', re.DOTALL)
    matches = pattern.findall(src)
    assert len(matches) == len(EXPECTED_DRIVE_MIN_FRAC), (
        "sanity: expected one measured/floor comment pair per opted-in entry")
    for measured_s, floor_s in matches:
        measured, floor = float(measured_s), float(floor_s)
        assert floor == pytest.approx(measured / 2.0, abs=0.011), (measured, floor)


def test_replay_suite_fault_path_purity_entries_are_command_free():
    """Rule 1: the UV pair (TP0010/TP0053), ML0217 (INIT_FAIL), and the
    must-NOT-latch entries (TP0178/TP0201) must stay command-free -- a second
    stimulus over a fault-DECISION entry could confuse the attribution."""
    index = rs.suite_index()
    for log in ("TP0010", "TP0053", "ML0217", "TP0178", "TP0201"):
        assert index[log]["replay_commands"] is False, log


def test_replay_suite_current_mode_profile_entries_are_command_free():
    """Rule 2: 'T'/'W' State-98 profiles command CURRENT directly and record
    v_sp identically 0 -- these must all stay command-free (replaying them
    would command nothing, per the table comment)."""
    index = rs.suite_index()
    for log in ("WP0097", "WP0197", "TP0170", "TP0171", "TP0176", "TP0210"):
        assert index[log]["replay_commands"] is False, log


def test_build_sim_argv_emits_replay_commands_for_opted_in_entry():
    entry = rs.suite_index()["ML0146"]
    assert entry["replay_commands"] is True
    argv = rs.build_sim_argv(entry, "/tmp/csvdir")
    assert "--replay-commands" in argv


def test_build_sim_argv_omits_replay_commands_for_command_free_entry():
    entry = rs.suite_index()["TP0010"]
    assert entry["replay_commands"] is False
    argv = rs.build_sim_argv(entry, "/tmp/csvdir")
    assert "--replay-commands" not in argv


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
# 7b. A5: ReplayCsv.metrics() / evaluate_replay_csv()'s "metrics" field
# ─────────────────────────────────────────────────────────────────────────

def test_metrics_final_fault_flags_reflects_a_latched_bit_not_dropped(tmp_path):
    """A5 regression: this is the exact bug that hid a carried-in 0x8100
    latch. metrics()['final_fault_flags'] must be the LAST row's fault_flags,
    truthfully, not {} / 0x0000 by construction."""
    rows = _with_bringup_and_grace(_uv_collapse_rows())
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    m = data.metrics(csv_path=str(path))
    assert m["final_fault_flags"] == rows[-1]["fault_flags"]
    assert m["final_fault_flags"] & rs.FAULT_UV_BUS
    assert m["csv"] == str(path)


def test_metrics_fault_bits_seen_is_union_across_the_whole_run(tmp_path):
    rows = _with_bringup_and_grace([
        {"t": 0.0, "fault_flags": rs.FAULT_OC_FC, "state": 2},
        {"t": 0.1, "fault_flags": 0, "state": 2},        # transient bit clears
        {"t": 0.2, "fault_flags": rs.FAULT_UV_BUS, "state": 99},
    ])
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    m = data.metrics()
    assert m["fault_bits_seen"] == (rs.FAULT_OC_FC | rs.FAULT_UV_BUS)
    # final_fault_flags is only the LAST sample, not the union
    assert m["final_fault_flags"] == rs.FAULT_UV_BUS


def test_metrics_final_state_is_the_last_row_state(tmp_path):
    rows = _with_bringup_and_grace(_uniform_rows(0.2, 0.01, state=lambda t: 2))
    rows.append({"t": rows[-1]["t"] + 0.01, "state": 99, "fault_flags": 0})
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    m = data.metrics()
    assert m["final_state"] == 99


def test_metrics_n_obs_and_n_obs_post_grace_match_faults_all_and_faults(tmp_path):
    rows = _with_bringup_and_grace(_uniform_rows(0.1, 0.01, fault_flags=lambda t: 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    m = data.metrics()
    assert m["n_obs"] == len(data.faults_all)
    assert m["n_obs_post_grace"] == len(data.faults)
    assert m["n_obs_post_grace"] <= m["n_obs"]
    assert m["grace_s"] == data.grace_s
    assert m["duration_s"] == pytest.approx(data.duration_s)
    assert m["rows"] == data.n_rows
    assert m["last_obs_t"] == pytest.approx(data.faults_all[-1][0])


def test_metrics_empty_csv_reports_none_fields_not_raising(tmp_path):
    """A structurally valid CSV with zero observation rows (all obs columns
    blank) must not raise -- every observation-derived field degrades to
    None/0 gracefully."""
    rows = _uniform_rows(0.1, 0.01)
    for r in rows:
        r["no_obs"] = True
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    m = data.metrics()
    assert m["final_fault_flags"] is None
    assert m["last_obs_t"] is None
    assert m["n_obs"] == 0


# ─────────────────────────────────────────────────────────────────────────
# check_v_bus_min_in_band (2026-08-31 ledger fix queue) — the de-vacuation
# guard for TP0178/TP0201's must-NOT-latch claim. Six branches: below the
# floor (FAIL), exactly at the floor (FAIL, EXCLUSIVE), inside the band
# (PASS), exactly at the ceiling (PASS, INCLUSIVE), above the ceiling
# (FAIL), and a dip confined to the synthetic preamble (excluded from the
# recorded-window minimum entirely).
# ─────────────────────────────────────────────────────────────────────────

def _v_bus_min_entry(v_bus_after_preamble, min_v=12.0, max_v=12.30,
                     dip_in_preamble=None):
    """A CSV whose V_bus after the preamble sits at a single controlled
    value (the recorded-window minimum this check reads), optionally with a
    much lower dip confined to BEFORE the preamble boundary to probe the
    exclusion. Returns (data, spec)."""
    rows = []
    if dip_in_preamble is not None:
        rows.append({"t": 0.1, "V_bus": dip_in_preamble, "fault_flags": 0})
    rows = _with_bringup(rows, shift=None) if rows else [_bringup_row()]
    tail = _shift_rows(
        _uniform_rows(0.05, 0.01, V_bus=lambda t: v_bus_after_preamble,
                     fault_flags=lambda t: 0),
        rs.REPLAY_PREAMBLE_S)
    rows = rows + tail
    return rows, {"kind": "v_bus_min_in_band", "name": "uv_margin_pinned",
                  "min_v": min_v, "max_v": max_v}


def test_v_bus_min_in_band_below_floor_fails(tmp_path):
    rows, spec = _v_bus_min_entry(11.9)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    passed, detail = rs.check_v_bus_min_in_band(data, spec)
    assert passed is False
    assert "AT OR BELOW" in detail


def test_v_bus_min_in_band_exactly_at_floor_fails_exclusive(tmp_path):
    rows, spec = _v_bus_min_entry(12.0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    passed, detail = rs.check_v_bus_min_in_band(data, spec)
    assert passed is False
    assert "AT OR BELOW" in detail


def test_v_bus_min_in_band_inside_band_passes(tmp_path):
    rows, spec = _v_bus_min_entry(12.15)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    passed, detail = rs.check_v_bus_min_in_band(data, spec)
    assert passed is True
    assert "near-miss band" in detail


def test_v_bus_min_in_band_exactly_at_ceiling_passes_inclusive(tmp_path):
    rows, spec = _v_bus_min_entry(12.30)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    passed, detail = rs.check_v_bus_min_in_band(data, spec)
    assert passed is True


def test_v_bus_min_in_band_above_ceiling_fails(tmp_path):
    rows, spec = _v_bus_min_entry(12.5)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    passed, detail = rs.check_v_bus_min_in_band(data, spec)
    assert passed is False
    assert "ABOVE" in detail


def test_v_bus_min_in_band_excludes_a_dip_confined_to_the_preamble(tmp_path):
    """A deep dip (5.0 V, well below the floor) that occurs BEFORE the
    preamble boundary must not be seen by this check at all -- the reported
    minimum must be the post-preamble constant (15.9 V, well above the
    ceiling), proving the dip was excluded rather than merely outweighed."""
    rows, spec = _v_bus_min_entry(15.9, dip_in_preamble=5.0)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    passed, detail = rs.check_v_bus_min_in_band(data, spec)
    assert passed is False
    assert "ABOVE" in detail
    assert "15.9" in detail
    assert "5.0" not in detail.split("V vs")[0]   # the excluded dip never appears as "the" minimum


# -- TP0178/TP0201 real entry shape pins -------------------------------------

def test_tp0178_and_tp0201_entries_pin_the_same_uv_margin_band():
    index = rs.suite_index()
    for log in ("TP0178", "TP0201"):
        entry = index[log]
        names = {c["name"] for c in entry["checks"]}
        assert {"no_fault", "uv_not_latched", "uv_margin_pinned"} <= names
        vband = next(c for c in entry["checks"] if c["kind"] == "v_bus_min_in_band")
        assert vband["min_v"] == pytest.approx(12.0)
        assert vband["max_v"] == pytest.approx(12.30)
        fnl = next(c for c in entry["checks"] if c["kind"] == "fault_not_latched")
        assert fnl["bit"] == rs.FAULT_UV_BUS
        assert entry["replay_commands"] is False


# ─────────────────────────────────────────────────────────────────────────
# Import-time guards: negative tests. Both guards read the module-global
# REPLAY_SUITE with no arguments, so a violating case is tested by
# monkeypatching that global to a synthetic bad list and invoking the guard
# function directly -- the module already imported cleanly against the REAL
# table, so this is the only way to exercise the guard's failure branch at
# all without editing hil_replay_suite.py (out of scope for this file).
# ─────────────────────────────────────────────────────────────────────────

def test_assert_uv_not_latched_entries_rejects_a_pin_free_uv_entry(monkeypatch):
    bad_entry = {
        "log": "SYN_BAD", "checks": [
            {"kind": "fault_not_latched", "name": "uv_not_latched",
             "bit": rs.FAULT_UV_BUS},
            # no v_bus_min_in_band check at all -- the exact TP0178/TP0201
            # pre-fix defect this guard was written to catch.
        ],
    }
    monkeypatch.setattr(rs, "REPLAY_SUITE", [bad_entry])
    with pytest.raises(AssertionError, match="does not pin its own stimulus"):
        rs._assert_uv_not_latched_entries()


def test_assert_uv_not_latched_entries_rejects_a_band_missing_max_v(monkeypatch):
    bad_entry = {
        "log": "SYN_BAD2", "checks": [
            {"kind": "fault_not_latched", "name": "uv_not_latched",
             "bit": rs.FAULT_UV_BUS},
            {"kind": "v_bus_min_in_band", "name": "uv_margin_pinned",
             "min_v": 12.0},   # max_v missing
        ],
    }
    monkeypatch.setattr(rs, "REPLAY_SUITE", [bad_entry])
    with pytest.raises(AssertionError, match="needs an explicit `max_v`"):
        rs._assert_uv_not_latched_entries()


def test_assert_uv_not_latched_entries_rejects_min_v_not_less_than_max_v(monkeypatch):
    bad_entry = {
        "log": "SYN_BAD3", "checks": [
            {"kind": "fault_not_latched", "name": "uv_not_latched",
             "bit": rs.FAULT_UV_BUS},
            {"kind": "v_bus_min_in_band", "name": "uv_margin_pinned",
             "min_v": 12.30, "max_v": 12.0},   # inverted
        ],
    }
    monkeypatch.setattr(rs, "REPLAY_SUITE", [bad_entry])
    with pytest.raises(AssertionError, match="min_v < max_v"):
        rs._assert_uv_not_latched_entries()


def test_assert_uv_not_latched_entries_accepts_a_correctly_pinned_entry(monkeypatch):
    """Converse: the guard must NOT raise on a correctly-shaped entry, so the
    negative tests above are pinning the actual defect and not merely a
    function that always raises."""
    good_entry = {
        "log": "SYN_GOOD", "checks": [
            {"kind": "fault_not_latched", "name": "uv_not_latched",
             "bit": rs.FAULT_UV_BUS},
            {"kind": "v_bus_min_in_band", "name": "uv_margin_pinned",
             "min_v": 12.0, "max_v": 12.30},
        ],
    }
    monkeypatch.setattr(rs, "REPLAY_SUITE", [good_entry])
    rs._assert_uv_not_latched_entries()   # must not raise


def test_assert_check_spec_shapes_rejects_a_field_typed_onto_the_wrong_kind(monkeypatch):
    """The exact failure mode the guard exists for: `max_v` (a
    v_bus_min_in_band field) misplaced onto a `no_fault` check reads as an
    assertion via .get() and is silently ignored without this guard."""
    bad_entry = {
        "log": "SYN_BAD4", "checks": [
            {"kind": "no_fault", "name": "no_fault", "max_v": 12.30},
        ],
    }
    monkeypatch.setattr(rs, "REPLAY_SUITE", [bad_entry])
    with pytest.raises(AssertionError, match="does not read"):
        rs._assert_check_spec_shapes()


def test_assert_check_spec_shapes_rejects_an_unknown_check_kind(monkeypatch):
    bad_entry = {
        "log": "SYN_BAD5", "checks": [
            {"kind": "not_a_real_kind", "name": "bogus"},
        ],
    }
    monkeypatch.setattr(rs, "REPLAY_SUITE", [bad_entry])
    with pytest.raises(AssertionError, match="unknown check kind"):
        rs._assert_check_spec_shapes()


def test_assert_check_spec_shapes_rejects_a_non_positive_not_before_s(monkeypatch):
    bad_entry = {
        "log": "SYN_BAD6", "checks": [
            {"kind": "fault_latched", "name": "x", "bit": rs.FAULT_UV_BUS,
             "not_before_s": 0.0},
        ],
    }
    monkeypatch.setattr(rs, "REPLAY_SUITE", [bad_entry])
    with pytest.raises(AssertionError, match="not_before_s. must be positive"):
        rs._assert_check_spec_shapes()


def test_assert_check_spec_shapes_accepts_a_correctly_shaped_entry(monkeypatch):
    good_entry = {
        "log": "SYN_GOOD2", "checks": [
            {"kind": "no_fault", "name": "no_fault"},
            {"kind": "v_bus_min_in_band", "name": "uv_margin_pinned",
             "min_v": 12.0, "max_v": 12.30},
            {"kind": "fault_latched", "name": "x", "bit": rs.FAULT_UV_BUS,
             "not_before_s": 0.5},
        ],
    }
    monkeypatch.setattr(rs, "REPLAY_SUITE", [good_entry])
    rs._assert_check_spec_shapes()   # must not raise


# -- FU2: switch_transitions ------------------------------------------------

def test_metrics_switch_transitions_counts_value_changes_not_events(tmp_path):
    """switch_transitions counts VALUE CHANGES between consecutive recorded-
    window samples, not a count of 'events' -- a bit staying SET across three
    consecutive samples is one transition (the rising edge), not three, and
    it falling back is a second."""
    switches = [0, 0, 1, 1, 1, 0, 0]

    def switch_fn(t):
        return switches[int(round(t / 0.01))]

    rows = _with_bringup_and_grace(
        _uniform_rows(0.06, 0.01, switch=switch_fn, fault_flags=lambda t: 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    m = data.metrics()
    # 0->1 and 1->0: exactly 2 VALUE CHANGES, independent of how many samples
    # each level held for.
    assert m["switch_transitions"] == 2


def test_metrics_switch_transitions_zero_when_switch_never_changes(tmp_path):
    rows = _with_bringup_and_grace(
        _uniform_rows(0.05, 0.01, switch=lambda t: 0x3F, fault_flags=lambda t: 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    assert data.metrics()["switch_transitions"] == 0


def test_metrics_switch_transitions_preamble_content_excluded_entirely(tmp_path):
    """A switch flip that happens entirely BEFORE preamble_s (no shift
    applied) must not be counted at all -- switch_recorded is empty, same
    scoping as current_recorded."""
    rows = _with_bringup(
        _uniform_rows(0.06, 0.01, switch=lambda t: 0 if t < 0.03 else 1,
                     fault_flags=lambda t: 0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    assert data.switch_recorded == []
    assert data.metrics()["switch_transitions"] == 0


def test_metrics_switch_transitions_only_counts_post_preamble_flips(tmp_path):
    """Content straddling preamble_s: a flip BEFORE it is invisible, the SAME
    shaped flip AFTER it counts -- proving the scoping is on TIME, not on the
    switch pattern itself."""
    pre = _uniform_rows(0.06, 0.01, switch=lambda t: 0 if t < 0.03 else 1)
    post = _shift_rows(
        _uniform_rows(0.06, 0.01, switch=lambda t: 0 if t < 0.03 else 1),
        rs.REPLAY_PREAMBLE_S)
    rows = _with_bringup(pre + post)
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    assert data.metrics()["switch_transitions"] == 1   # only the shifted flip counts


def test_evaluate_replay_csv_metrics_field_populated_on_success(tmp_path):
    """A5: evaluate_replay_csv()'s top-level 'metrics' must be the SAME
    parse's data.metrics(), not the old hardcoded {}."""
    rows = _with_bringup_and_grace(_uv_collapse_rows())
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    entry = _entry([{"kind": "fault_latched", "name": "uv", "bit": rs.FAULT_UV_BUS,
                     "require_stimulus": True}])
    res = rs.evaluate_replay_csv(entry, str(path))
    assert res["metrics"], "must not be the old empty {}"
    assert res["metrics"]["final_fault_flags"] & rs.FAULT_UV_BUS
    assert res["metrics"]["csv"] == str(path)


def test_evaluate_replay_csv_metrics_field_populated_on_load_failure(tmp_path):
    """The load-failure path (missing/unreadable CSV) must ALSO set a
    non-empty metrics dict carrying an 'error' key, per ReplayCsv.metrics()'s
    documented contract for that field."""
    entry = _entry([{"kind": "no_fault", "name": "no_fault"}])
    res = rs.evaluate_replay_csv(entry, "/nonexistent/path/nope.csv")
    assert res["metrics"], "must not be the old empty {}"
    assert "error" in res["metrics"]
    assert res["metrics"]["csv"] == "/nonexistent/path/nope.csv"


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


def test_not_exercised_tag_applied_to_command_shape_checks_when_current_is_all_zero(tmp_path):
    """2026-08-30 (--replay-commands): on an entry WITHOUT replay_commands
    (this one omits the key entirely), the plain VACUOUS_TAG is now REPLACED
    by the sharper NOT_EXERCISED_TAG for every MOTOR_RESPONSE_KINDS check --
    see NOT_EXERCISED_PREFIX/_TAG. The underlying assertion (`passed` stays
    True) is unchanged from the original vacuous-tag behaviour."""
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
        assert by_name[name]["detail"].startswith(rs.NOT_EXERCISED_PREFIX), name
        # the plain VACUOUS_TAG text is stripped out entirely, not just prefixed
        assert rs.VACUOUS_TAG not in by_name[name]["detail"], name
    assert res["n_checks"] == 5   # + the bring-up gate check
    assert res["n_checks_not_exercised"] == 4
    assert res["n_checks_vacuous"] == 4
    assert res["n_checks_substantive"] == 1
    assert any("4 of 5 checks were NOT EXERCISED" in n for n in res["notes"])
    assert not any("VACUOUS" in n for n in res["notes"])


def test_vacuous_tag_survives_on_opted_in_entry_whose_current_stayed_flat(tmp_path):
    """The counterpart case the NOT_EXERCISED rewrite must NOT touch: an entry
    that DID set replay_commands: True but whose recorded current still came
    back flat zero keeps the plain VACUOUS_TAG (command_is_identically_zero()
    is a property of the data, not of whether commands were replayed) -- only
    entries WITHOUT replay_commands get the NOT_EXERCISED retag."""
    rows = _with_bringup_and_grace(
        _uniform_rows(0.2, 0.005, fault_flags=lambda t: 0, current=lambda t: 0.0))
    path = tmp_path / "a.csv"
    write_replay_csv(path, rows)
    entry = _entry([{"kind": "bounded_current", "name": "bc"}], replay_commands=True)
    res = rs.evaluate_replay_csv(entry, str(path))
    by_name = {c["name"]: c for c in res["checks"]}
    assert by_name["bc"]["passed"] is True
    assert rs.VACUOUS_TAG in by_name["bc"]["detail"]
    assert not by_name["bc"]["detail"].startswith(rs.NOT_EXERCISED_PREFIX)
    assert res["n_checks_not_exercised"] == 0
    assert res["n_checks_vacuous"] == 1


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

def test_target_fw_version_is_26():
    """21 -> 23 -> 24 -> 25 -> 26. The target must say what it actually runs
    against: fw v26 (the source current-ceiling share governor).
    COMPARABLE_FW_MIN is a SEPARATE constant and stays at 18 -- none of v24,
    v25 or v26 changed an encoder constant or a drive coefficient, so no
    entry's conformance/stability classification moves."""
    assert rs.TARGET_FW_VERSION == 26
    assert rs.COMPARABLE_FW_MIN == 18
    for v in (22, 23, 24, 25, 26):
        assert v in rs.FW_DELTA_NOTES
    # The v24 and v25 rows must both say the drive law and the wheel did NOT
    # move -- that is the claim every replay comparison across the boundary
    # rests on.
    for v in (24, 25, 26):
        assert "SAME WHEEL AND SAME DRIVE LAW" in rs.FW_DELTA_NOTES[v]


def test_fw26_delta_note_states_the_reachability_argument():
    """The v26 row must carry the STRUCTURAL reason the current-ceiling clamp
    cannot reach a replay entry -- the minority clip's 1.55 A two-source
    threshold -- so a replay reader does not go looking for a clamped tick."""
    note = rs.FW_DELTA_NOTES[26]
    assert "SHARE_GOV_I_FC_CEIL_A" in note
    assert "SHARE_MINORITY_I_MIN_A" in note
    assert "1.55 A" in note
    assert "UNREACHABLE BY ANY REPLAY ENTRY" in note
    assert "No entry's expectations move." in note


def test_fw25_delta_note_states_the_expectation_relevant_guard_consequence():
    """The v25 row is not a changelog echo: a replay reader must be able to see
    from it WHICH observable moved.  The guards make an en_low bus-switch
    sw_ring above SHARE_CUT_MAX_HANDOFF_A a hazard signature rather than a
    normal event, and the note has to say so or the suite-wide tripwire looks
    arbitrary."""
    note = rs.FW_DELTA_NOTES[25]
    assert "SHARE_CUT_MAX_HANDOFF_A" in note
    assert "SHARE_CUT_SURVIVOR_BLANK_MS" in note
    assert "en_low" in note and "NO LONGER OCCUR" in note
    # ...and that a refused cut is NOT a fault, so a reader does not go hunting
    # for a flag that never gets set.
    assert "not a fault" in note
    # State-99 teardown must be excluded explicitly -- those cuts are not share
    # cuts and legitimately open a loaded switch.
    assert "TEARDOWN" in note


def test_limit_v_bus_max_v_matches_firmware():
    # teensy_controller/teensy_controller.ino:1305 -- LIMIT_V_BUS_MAX =
    # V_BUS_NOMINAL(16.0) + 1.5 = 17.5 V
    assert rs.LIMIT_V_BUS_MAX_V == pytest.approx(17.5)


# ─────────────────────────────────────────────────────────────────────────
# gen_fu4_replay_log.py -- the SY0001.BLG generator (FU4, 2026-08-31)
# ─────────────────────────────────────────────────────────────────────────
import gen_fu4_replay_log as gen4  # noqa: E402
import decode_benchlog as dblg     # noqa: E402  (format authority, used to
                                    # verify the generator's OWN OUTPUT
                                    # independently of gen4's own constants)

SY0001_PATH = os.path.join(REPO_ROOT, "logs", "SY0001.BLG")


def test_gen_fu4_build_blg_is_byte_deterministic():
    a = gen4.build_blg()
    b = gen4.build_blg()
    assert a == b
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()


def test_gen_fu4_sha256_pin_against_committed_logs_sy0001():
    """The committed logs/SY0001.BLG must be BYTE-IDENTICAL to what the
    generator produces right now -- imports the module's own builder (no
    subprocess), so a generator edit that would change the committed file
    cannot pass silently. If this ever needs to change, regenerate the file
    with `--force` and re-verify with `--verify-logs`, per the module
    docstring; it must never be hand-patched to match a stale generator."""
    assert os.path.isfile(SY0001_PATH), "logs/SY0001.BLG is missing"
    with open(SY0001_PATH, "rb") as fh:
        committed = fh.read()
    generated = gen4.build_blg()
    assert hashlib.sha256(committed).hexdigest() == hashlib.sha256(generated).hexdigest()
    assert committed == generated


def test_gen_fu4_header_bytes_magic_version_fw():
    data = gen4.build_blg()
    res = dblg.decode_blg(data)
    assert res.header["version"] == 3
    assert res.header["fw_version"] == 23
    assert res.header["record_size"] == gen4.RECORD_SIZE_V3
    assert data[:4] == b"BLG1"


def test_gen_fu4_record_count_is_2500():
    data = gen4.build_blg()
    res = dblg.decode_blg(data)
    assert res.records_read == 2500
    assert len(res.csv_rows) == 2500


def test_gen_fu4_v_sp_step_at_t_us_1500000():
    """v_sp holds 2.0 for records [0, 1500) and steps to 0.0 at record 1500
    (t_us = 1500000) -- decoded independently through decode_benchlog's own
    CSV_HEADER_V3 column order, not gen4's own constants."""
    data = gen4.build_blg()
    res = dblg.decode_blg(data)
    cols = res.csv_header.split(",")
    t_idx = cols.index("t_us")
    v_sp_idx = cols.index("v_sp")
    rows = [r.split(",") for r in res.csv_rows]
    assert rows[1499][t_idx] == "1499000"
    assert float(rows[1499][v_sp_idx]) == pytest.approx(2.0)
    assert rows[1500][t_idx] == "1500000"
    assert float(rows[1500][v_sp_idx]) == pytest.approx(0.0)
    assert float(rows[0][v_sp_idx]) == pytest.approx(2.0)
    assert float(rows[2499][v_sp_idx]) == pytest.approx(0.0)


def test_gen_fu4_trailer_fields():
    data = gen4.build_blg()
    res = dblg.decode_blg(data)
    assert res.trailer is not None
    assert res.trailer["records_written"] == 2500
    assert res.trailer["dropped"] == 0
    assert res.trailer["close_reason"] == gen4.CLOSE_REASON_COMPLETE
    assert res.trailer["close_reason_str"] == "complete"
    assert res.trailer["error_code"] == 0
    assert res.trailer["abandoned"] == 0
    assert res.warnings == []   # a clean records_written match raises none


# ─────────────────────────────────────────────────────────────────────────
# SY0001 REPLAY_SUITE entry shape (FU4, 2026-08-31)
# ─────────────────────────────────────────────────────────────────────────

def test_sy0001_entry_present_and_conformance():
    index = rs.suite_index()
    assert "SY0001" in index
    entry = index["SY0001"]
    assert entry["mode"] == "conformance"


def test_sy0001_entry_replay_commands_true_and_no_longer_provisional():
    """DE-PROVISIONALIZED 2026-08-31 (ledger fix queue): campaign
    20260831_191509 is SY0001's first real run, so `provisional` is now
    False and the entry carries a measured `drive_min_frac` (pinned in
    EXPECTED_DRIVE_MIN_FRAC / test_replay_suite_drive_min_frac_table_pin)."""
    entry = rs.suite_index()["SY0001"]
    assert entry.get("replay_commands") is True
    assert entry.get("provisional") is False
    dls = next(c for c in entry["checks"] if c["kind"] == "drive_loop_stepped")
    assert dls.get("drive_min_frac") == pytest.approx(0.30)


def test_sy0001_entry_fw_and_blg_version_match_the_committed_file():
    """The entry's declared fw_version/blg_version must match the header
    bytes ACTUALLY in logs/SY0001.BLG -- re-derived from the file, not
    copy-pasted from the generator's constants a second time."""
    entry = rs.suite_index()["SY0001"]
    assert entry["fw_version"] == 23
    assert entry["blg_version"] == 3
    with open(SY0001_PATH, "rb") as fh:
        head = fh.read(24)
    assert head[:4] == b"BLG1"
    assert head[4] == entry["blg_version"]
    (fw,) = struct.unpack_from("<H", head, 18)
    assert fw == entry["fw_version"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ─────────────────────────────────────────────────────────────────────────
# The replay half's share-cut census (campaign 20260902_011926, item 7)
#
# The 151156 ledger says no replay can exercise the fw v25 share-cut guard.
# The suite cannot SCORE it (a replay writes no events.jsonl), but the firmware
# path IS exercised: 163 in-Run bus-switch falling edges across six opt-in
# replays, none of which anything looked at.
# ─────────────────────────────────────────────────────────────────────────

def _census_rows(seq):
    """`seq`: list of (switch, I_fc, I_batt, state) at 1 ms spacing."""
    rows = []
    for i, (sw, i_fc, i_bt, st) in enumerate(seq):
        rows.append({"t": i * 0.001, "switch": sw, "I_fc": i_fc,
                     "I_batt": i_bt, "state": st, "fault_flags": 0})
    return rows


def _census(tmp_path, seq, name="census.csv"):
    rows = _with_bringup(_shift_rows(_census_rows(seq), rs.REPLAY_PREAMBLE_S))
    path = tmp_path / name
    write_replay_csv(path, rows)
    data = rs.load_replay_csv(str(path))
    return rs.share_cut_census(data)


def test_share_cut_census_counts_in_run_falling_edges(tmp_path):
    both = rs.SW_FC_BUS | rs.SW_BT_BUS
    out = _census(tmp_path, [
        (both, 0.30, 0.30, 2),
        (rs.SW_BT_BUS, 0.66, 0.30, 2),      # FC_BUS cut, own row 0.66 A
        (rs.SW_BT_BUS, 0.30, 0.30, 2),
        (0, 0.30, 0.20, 2),                 # BT_BUS cut, own row 0.20 A
        (0, 0.30, 0.20, 2),
    ])
    assert out["n_cuts"] == 2
    assert out["n_over_own_row"] == 1                 # only the 0.66 A one
    assert out["i_own_row_peak_a"] == pytest.approx(0.66)
    assert out["limit_a"] == rs.SHARE_CUT_MAX_HANDOFF_A == 0.5
    assert {c["switch"] for c in out["cuts"]} == {"FC_BUS", "BT_BUS"}


def test_share_cut_census_excludes_state_99_teardowns(tmp_path):
    """A State-99 teardown opens a LOADED bus switch by design
    (safeAllSwitches()); counting those would drown the census in the one case
    that is not a share decision."""
    both = rs.SW_FC_BUS | rs.SW_BT_BUS
    out = _census(tmp_path, [
        (both, 2.00, 2.00, 99),
        (0, 2.00, 2.00, 99),                # teardown cut, heavily loaded
        (0, 2.00, 2.00, 99),
    ])
    assert out["n_cuts"] == 0
    assert out["i_own_row_peak_a"] is None


def test_share_cut_census_reports_the_preceding_row_separately(tmp_path):
    """The 1.9 ms command round trip means the load the guard SAW may be the
    previous sample's, so both are reported and neither is a verdict."""
    both = rs.SW_FC_BUS | rs.SW_BT_BUS
    out = _census(tmp_path, [
        (both, 0.57, 0.30, 2),              # the row the guard likely read
        (rs.SW_BT_BUS, 0.40, 0.30, 2),      # the cut itself, now under 0.5 A
        (rs.SW_BT_BUS, 0.40, 0.30, 2),
    ])
    assert out["n_cuts"] == 1
    assert out["n_over_own_row"] == 0
    assert out["n_over_prev_row"] == 1
    assert out["i_prev_row_peak_a"] == pytest.approx(0.57)


def test_share_cut_census_is_reported_on_every_entry_and_never_fails(tmp_path):
    both = rs.SW_FC_BUS | rs.SW_BT_BUS
    rows = _with_bringup(_shift_rows(_census_rows([
        (both, 0.66, 0.30, 2),
        (rs.SW_BT_BUS, 0.66, 0.30, 2),
        (rs.SW_BT_BUS, 0.66, 0.30, 2),
    ]), rs.REPLAY_PREAMBLE_S))
    path = tmp_path / "entry.csv"
    write_replay_csv(path, rows)
    entry = _entry([{"kind": "no_fault", "name": "no_fault"}])
    res = rs.evaluate_replay_csv(entry, str(path))
    assert res["passed"] is True, res["checks"]
    # Structured, so a campaign can total it without parsing prose...
    assert res["share_cut_census"]["n_cuts"] == 1
    assert res["share_cut_census"]["n_over_own_row"] == 1
    # ...and visible in the report as a NOTE, not as a passing check row: it
    # asserts nothing, and a row would inflate the substantive count.
    assert any(n.startswith(rs.INFORMATIONAL_PREFIX) for n in res["notes"])
    assert all(c["name"] != "share_cut_census" for c in res["checks"])
    assert res["n_checks"] == 2          # bring-up gate + no_fault


def test_share_cut_census_is_a_registered_check_kind_that_passes():
    """Registered so an entry can carry it explicitly the day one wants a
    per-entry row; it must never be able to fail."""
    assert rs.CHECK_KINDS["share_cut_census"] is rs.check_share_cut_census
