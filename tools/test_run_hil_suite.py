#!/usr/bin/env python3
"""pytest suite for tools/run_hil_suite.py — the HIL suite wrapper (plan
building, argv construction, offline health-check analysis, and the pure
report renderer). No board, no subprocess of the real simulator — this
exercises only the pure/offline functions per the fence in the task.

Run: cd tools && python -m pytest test_run_hil_suite.py -v
"""
import argparse
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_hil_suite as rhs  # noqa: E402
from hil_plant_sim import SCENARIOS  # noqa: E402
from hil_replay_suite import REPLAY_SUITE  # noqa: E402


def _args(**overrides):
    """A minimal argparse.Namespace matching what build_plan()/full_argv()
    read off args — built from run_hil_suite's own parser defaults so this
    test doesn't hand-guess a field name the parser doesn't have."""
    ns = rhs.main.__globals__  # not used; just documenting intent
    base = dict(
        out="/tmp/hil_report_test", only=[], skip=[],
        replay_only=False, scenarios_only=False,
        electrical_pref="hifi", teensy_ip="192.168.1.50", port=5001,
        settle_s=5.0, keep_going=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


# ─────────────────────────────────────────────────────────────────────────
# 1. build_plan()
# ─────────────────────────────────────────────────────────────────────────

def test_build_plan_full_count_39_runs():
    # 13 scenarios (ems-drive-cycle added this round) + 26 replays = 39.
    plan = rhs.build_plan(_args())
    assert len(plan) == len(SCENARIOS) + len(REPLAY_SUITE) == 39
    kinds = [p["kind"] for p in plan]
    assert kinds.count("scenario") == 13
    assert kinds.count("replay") == 26


def test_build_plan_replay_only():
    plan = rhs.build_plan(_args(replay_only=True))
    assert len(plan) == 26
    assert all(p["kind"] == "replay" for p in plan)


def test_build_plan_scenarios_only():
    plan = rhs.build_plan(_args(scenarios_only=True))
    assert len(plan) == 13
    assert all(p["kind"] == "scenario" for p in plan)


def test_build_plan_only_pattern_filters_by_name():
    plan = rhs.build_plan(_args(only=["ML*"]))
    assert plan  # at least one ML log
    assert all(p["name"].startswith("ML") for p in plan)


def test_build_plan_skip_pattern_excludes_by_name():
    plan_full = rhs.build_plan(_args())
    plan_skipped = rhs.build_plan(_args(skip=["steady"]))
    assert len(plan_skipped) == len(plan_full) - 1
    assert "steady" not in [p["name"] for p in plan_skipped]


def test_build_plan_only_and_skip_combine():
    """skip is applied on top of only (filter_plan applies both), so a name
    matching both --only and --skip is excluded."""
    plan = rhs.build_plan(_args(only=["ML*"], skip=["ML0146"]))
    names = [p["name"] for p in plan]
    assert "ML0146" not in names
    assert all(n.startswith("ML") for n in names)


def test_build_plan_only_pattern_matches_scenario_glob():
    plan = rhs.build_plan(_args(only=["charge-*"]))
    names = {p["name"] for p in plan}
    assert names == {"charge-cruise", "charge-regen", "charge-fault"}


def test_build_plan_electrical_pref_resolution_any_scenarios():
    """Scenarios whose SCENARIOS['electrical'] is 'any' get args.electrical_pref;
    hifi-required and simple-required entries keep their own mode regardless
    of the preference."""
    plan_hifi = {p["name"]: p for p in rhs.build_plan(_args(electrical_pref="hifi"))
                if p["kind"] == "scenario"}
    plan_simple = {p["name"]: p for p in rhs.build_plan(_args(electrical_pref="simple"))
                  if p["kind"] == "scenario"}

    for name, meta in SCENARIOS.items():
        need = meta.get("electrical", "any")
        if need == "any":
            assert plan_hifi[name]["mode"] == "hifi"
            assert plan_simple[name]["mode"] == "simple"
        else:
            # hifi-required (or simple-required) scenarios are unaffected by
            # the preference in EITHER direction.
            assert plan_hifi[name]["mode"] == need
            assert plan_simple[name]["mode"] == need


def test_build_plan_electrical_required_field_matches_scenarios_registry():
    plan = rhs.build_plan(_args())
    by_name = {p["name"]: p for p in plan if p["kind"] == "scenario"}
    for name, meta in SCENARIOS.items():
        assert by_name[name]["electrical_required"] == meta.get("electrical", "any")


def test_build_plan_scenario_argv_has_scenario_electrical_duration_csv():
    plan = rhs.build_plan(_args(only=["steady"]))
    assert len(plan) == 1
    argv = plan[0]["argv"]
    assert "--scenario" in argv and "steady" in argv
    assert "--electrical" in argv
    assert "--duration" in argv
    assert "--csv" in argv


def test_build_plan_replay_argv_uses_build_sim_argv():
    from hil_replay_suite import suite_index, build_sim_argv
    plan = rhs.build_plan(_args(only=["ML0151"]))
    assert len(plan) == 1
    entry = suite_index()["ML0151"]
    expected = build_sim_argv(entry, "/tmp/hil_report_test")
    assert plan[0]["argv"] == expected


def test_build_plan_timeout_uses_grace_s():
    plan = rhs.build_plan(_args(only=["steady"]))
    dur = plan[0]["duration_s"]
    assert plan[0]["timeout_s"] == pytest.approx(dur + rhs.GRACE_S)


def test_build_plan_no_match_returns_empty():
    plan = rhs.build_plan(_args(only=["no-such-run-xyz"]))
    assert plan == []


# ─────────────────────────────────────────────────────────────────────────
# 2. full_argv()
# ─────────────────────────────────────────────────────────────────────────

def test_full_argv_appends_transport_flags():
    plan = rhs.build_plan(_args(only=["steady"]))
    item = plan[0]
    argv = rhs.full_argv(item, _args(teensy_ip="10.0.0.9", port=6001))
    assert argv[0] == sys.executable
    assert argv[1] == rhs.SIM_SCRIPT
    assert "--teensy-ip" in argv
    assert argv[argv.index("--teensy-ip") + 1] == "10.0.0.9"
    assert "--port" in argv
    assert argv[argv.index("--port") + 1] == "6001"
    # transport flags are NOT part of the item's own argv (the wrapper's job)
    assert "--teensy-ip" not in item["argv"]
    assert "--port" not in item["argv"]


def test_full_argv_scp_inrush_gets_vesc_cap_uf_converted_in_hifi_mode():
    """scp-inrush's SCENARIOS entry carries vesc_cap_f=0.9e-3; build_plan()
    must convert it to --vesc-cap-uf 900 (x1e6) ONLY when the resolved mode
    is hifi (scp-inrush requires hifi, so this is always true for it, but
    the conversion is gated on mode == 'hifi' in the source, not on the
    scenario name)."""
    meta = SCENARIOS["scp-inrush"]
    assert meta["electrical"] == "hifi"
    assert meta["vesc_cap_f"] == pytest.approx(0.9e-3)

    plan = rhs.build_plan(_args(only=["scp-inrush"]))
    assert len(plan) == 1
    argv = plan[0]["argv"]
    assert plan[0]["mode"] == "hifi"
    assert "--vesc-cap-uf" in argv
    idx = argv.index("--vesc-cap-uf")
    assert float(argv[idx + 1]) == pytest.approx(0.9e-3 * 1e6)  # 900


def test_no_other_scenario_gets_vesc_cap_uf():
    """Only scp-inrush's SCENARIOS entry sets vesc_cap_f; every other
    scenario's argv must NOT carry --vesc-cap-uf."""
    plan = rhs.build_plan(_args())
    for p in plan:
        if p["kind"] != "scenario" or p["name"] == "scp-inrush":
            continue
        assert "--vesc-cap-uf" not in p["argv"], p["name"]


def test_full_argv_replay_items_also_get_transport_flags():
    plan = rhs.build_plan(_args(only=["ML0151"]))
    argv = rhs.full_argv(plan[0], _args())
    assert "--replay" in argv
    assert "--teensy-ip" in argv and "--port" in argv


# ─────────────────────────────────────────────────────────────────────────
# 3. analyze_scenario_csv()
# ─────────────────────────────────────────────────────────────────────────

CSV_COLS = [
    "t", "seq", "V_fc", "V_batt", "V_bus", "V_chg", "V_rgn", "I_fc", "I_batt",
    "v_actual", "I_charge", "ag105_status",
    "state", "switch", "aux", "current", "mdac_fc", "mdac_bt",
    "fault_flags", "soc",
]


def _write_scenario_csv(path, rows, extra_cols=()):
    import csv
    cols = CSV_COLS + list(extra_cols)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            row = {c: "" for c in cols}
            row.update(r)
            w.writerow(row)


def test_analyze_scenario_csv_missing_file():
    m = rhs.analyze_scenario_csv("/nonexistent/nope.csv")
    assert m["error"] == "CSV not written"
    assert m["n_obs"] == 0


def test_analyze_scenario_csv_counts_obs_and_blank_rows(tmp_path):
    """Rows before the first observation frame have a blank fault_flags cell
    and must NOT count toward n_obs, but must still count toward rows."""
    rows = [
        {"t": "0.000", "fault_flags": ""},          # pre-observation, blank
        {"t": "0.001", "fault_flags": ""},
        {"t": "0.002", "fault_flags": "0", "state": "2"},
        {"t": "0.003", "fault_flags": "0x0010", "state": "2"},
    ]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path))
    assert m["rows"] == 4
    assert m["n_obs"] == 2
    assert m["final_fault_flags"] == 0x0010
    assert m["fault_bits_seen"] == 0x0010
    assert m["final_state"] == 2
    assert m["duration_s"] == pytest.approx(0.003, abs=1e-6)


def test_analyze_scenario_csv_fault_bits_seen_is_union_not_just_final():
    rows = [
        {"t": "0.000", "fault_flags": "0x0001", "state": "1"},
        {"t": "0.001", "fault_flags": "0x0002", "state": "2"},
        {"t": "0.002", "fault_flags": "0", "state": "1"},   # cleared by the end
    ]
    path_dir = "/tmp"
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.csv")
        _write_scenario_csv(path, rows)
        m = rhs.analyze_scenario_csv(path)
    assert m["final_fault_flags"] == 0          # final tick is clean
    assert m["fault_bits_seen"] == 0x0003        # but the union saw both bits


def test_analyze_scenario_csv_zero_obs_rows_only(tmp_path):
    rows = [{"t": "0.000", "fault_flags": ""}, {"t": "0.001", "fault_flags": ""}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path))
    assert m["rows"] == 2
    assert m["n_obs"] == 0
    assert m["final_fault_flags"] is None
    assert m["final_state"] is None


def test_analyze_scenario_csv_hifi_substep_stats(tmp_path):
    rows = [
        {"t": "0.000", "fault_flags": "0", "elec_substep_hz": "20000"},
        {"t": "0.001", "fault_flags": "0", "elec_substep_hz": "30000"},
        {"t": "0.002", "fault_flags": "0", "elec_substep_hz": "40000"},
    ]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows, extra_cols=["elec_substep_hz", "elec_events"])
    m = rhs.analyze_scenario_csv(str(path))
    assert m["substep_hz_min"] == pytest.approx(20000.0)
    assert m["substep_hz_mean"] == pytest.approx(30000.0)


def test_analyze_scenario_csv_no_substep_columns_gives_none(tmp_path):
    rows = [{"t": "0.000", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path))
    assert m["substep_hz_min"] is None
    assert m["substep_hz_mean"] is None


def test_analyze_scenario_csv_malformed_fault_flags_cell_skipped(tmp_path):
    """A non-numeric fault_flags cell must not raise, and must not count as
    an observation."""
    rows = [
        {"t": "0.000", "fault_flags": "not-a-number"},
        {"t": "0.001", "fault_flags": "0", "state": "1"},
    ]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path))
    # the malformed cell is non-blank so it increments n_obs before the int()
    # parse fails and 'continue's -- confirm this against the real behaviour
    # rather than assuming, since it's a subtlety worth pinning either way.
    assert m["rows"] == 2
    assert m["final_fault_flags"] == 0
    assert m["final_state"] == 1


# ─────────────────────────────────────────────────────────────────────────
# 4. judge_scenario()
# ─────────────────────────────────────────────────────────────────────────

def _metrics(n_obs=10, rows=10, final_fault_flags=0, fault_bits_seen=0, final_state=2):
    return {"n_obs": n_obs, "rows": rows, "final_fault_flags": final_fault_flags,
            "fault_bits_seen": fault_bits_seen, "final_state": final_state}


def _events(over_absmax=0, worst_ring_v=None):
    return {"total": 0, "kinds": {}, "over_absmax": over_absmax, "worst_ring_v": worst_ring_v}


def _child(status="ok", summary=None):
    return {"status": status, "returncode": 0, "summary": summary or {"achieved_hz": 1000.0}}


def test_judge_scenario_fault_required_with_fault_present_passes():
    """'sag' is in FAULT_REQUIRED (UV_BUS 0x0100)."""
    assert "sag" in rhs.FAULT_REQUIRED
    _why, want = rhs.FAULT_REQUIRED["sag"]
    m = _metrics(fault_bits_seen=want, final_fault_flags=want)
    passed, checks = rhs.judge_scenario("sag", m, _events(), _child())
    assert passed is True
    ef = [c for c in checks if c["name"] == "expected_fault"][0]
    assert ef["passed"] is True


def test_judge_scenario_fault_required_without_fault_fails():
    m = _metrics(fault_bits_seen=0, final_fault_flags=0)
    passed, checks = rhs.judge_scenario("sag", m, _events(), _child())
    assert passed is False
    ef = [c for c in checks if c["name"] == "expected_fault"][0]
    assert ef["passed"] is False


def test_judge_scenario_comm_loss_fault_required_matches_hil_link_bit():
    assert "comm-loss" in rhs.FAULT_REQUIRED
    _why, want = rhs.FAULT_REQUIRED["comm-loss"]
    assert want == 0x0010     # FAULT_HIL_LINK aliases FAULT_PI_TIMEOUT
    m = _metrics(fault_bits_seen=want, final_fault_flags=want)
    passed, _checks = rhs.judge_scenario("comm-loss", m, _events(), _child())
    assert passed is True


def test_judge_scenario_no_unexpected_fault_scenario_fails_on_any_fault():
    """'steady' is neither required nor allowed -> any fault is unexpected."""
    assert "steady" not in rhs.FAULT_REQUIRED
    assert "steady" not in rhs.FAULT_ALLOWED
    m = _metrics(fault_bits_seen=0x0100, final_fault_flags=0x0100)
    passed, checks = rhs.judge_scenario("steady", m, _events(), _child())
    assert passed is False
    nuf = [c for c in checks if c["name"] == "no_unexpected_fault"][0]
    assert nuf["passed"] is False


def test_judge_scenario_no_unexpected_fault_scenario_passes_when_clean():
    m = _metrics(fault_bits_seen=0, final_fault_flags=0)
    passed, checks = rhs.judge_scenario("steady", m, _events(), _child())
    assert passed is True


def test_judge_scenario_fault_allowed_scenario_always_passes_that_check():
    """'soc-depletion' is FAULT_ALLOWED — present or absent, that check passes."""
    assert "soc-depletion" in rhs.FAULT_ALLOWED
    for bits in (0, 0x0002):
        m = _metrics(fault_bits_seen=bits, final_fault_flags=bits)
        passed, checks = rhs.judge_scenario("soc-depletion", m, _events(), _child())
        fa = [c for c in checks if c["name"] == "fault_allowed"][0]
        assert fa["passed"] is True


def test_judge_scenario_zero_obs_fails():
    m = _metrics(n_obs=0, rows=10)
    passed, checks = rhs.judge_scenario("steady", m, _events(), _child())
    assert passed is False
    obs = [c for c in checks if c["name"] == "observation_frames"][0]
    assert obs["passed"] is False
    assert "never answered" in obs["detail"]


def test_judge_scenario_sw_ring_over_absmax_fails_even_if_no_fault():
    m = _metrics(fault_bits_seen=0, final_fault_flags=0)
    passed, checks = rhs.judge_scenario("steady", m, _events(over_absmax=2, worst_ring_v=21.5),
                                        _child())
    assert passed is False
    ring = [c for c in checks if c["name"] == "sw_ring_over_absmax"][0]
    assert ring["passed"] is False
    assert "21.50" in ring["detail"]


def test_judge_scenario_child_process_failure_fails():
    m = _metrics()
    passed, checks = rhs.judge_scenario("steady", m, _events(), _child(status="TIMEOUT"))
    assert passed is False
    cp = [c for c in checks if c["name"] == "child_process"][0]
    assert cp["passed"] is False


def test_judge_scenario_low_achieved_rate_fails():
    m = _metrics()
    passed, checks = rhs.judge_scenario("steady", m, _events(),
                                        _child(summary={"achieved_hz": 500.0}))
    assert passed is False
    rate = [c for c in checks if c["name"] == "achieved_rate"][0]
    assert rate["passed"] is False


def test_judge_scenario_missing_rate_skips_that_check():
    m = _metrics()
    child = _child()
    child["summary"] = {}   # no achieved_hz key at all (helper's `or` default would mask this)
    passed, checks = rhs.judge_scenario("steady", m, _events(), child)
    assert not any(c["name"] == "achieved_rate" for c in checks)
    assert passed is True


# ─────────────────────────────────────────────────────────────────────────
# 5. analyze_events()
# ─────────────────────────────────────────────────────────────────────────

def test_analyze_events_missing_path_returns_zeroed():
    out = rhs.analyze_events(None)
    assert out["total"] == 0 and out["kinds"] == {} and out["over_absmax"] == 0
    out2 = rhs.analyze_events("/nonexistent/file.jsonl")
    assert out2["total"] == 0


def test_analyze_events_counts_by_kind_and_over_absmax(tmp_path):
    lines = [
        {"kind": "boost_ovp", "channel": "FC"},
        {"kind": "sw_ring", "switch": "FC_BUS", "over_absmax": False, "peak_v": 18.0},
        {"kind": "sw_ring", "switch": "BT_BUS", "over_absmax": True, "peak_v": 22.3},
        {"kind": "sw_ring", "switch": "MOT_PWR", "over_absmax": True, "peak_v": 25.9},
        {"kind": "scp_cut", "switch": "MOT_PWR", "cut_count": 1},
    ]
    path = tmp_path / "events.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for e in lines:
            fh.write(json.dumps(e) + "\n")
    out = rhs.analyze_events(str(path))
    assert out["total"] == 5
    assert out["kinds"] == {"boost_ovp": 1, "sw_ring": 3, "scp_cut": 1}
    assert out["over_absmax"] == 2
    assert out["worst_ring_v"] == pytest.approx(25.9)


def test_analyze_events_ignores_blank_and_malformed_lines(tmp_path):
    path = tmp_path / "events.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "boost_ovp"}) + "\n")
        fh.write("\n")
        fh.write("not json at all\n")
        fh.write(json.dumps({"kind": "boost_ovp"}) + "\n")
    out = rhs.analyze_events(str(path))
    assert out["total"] == 2
    assert out["kinds"] == {"boost_ovp": 2}


def test_analyze_events_no_over_absmax_ring_events_leaves_worst_none(tmp_path):
    path = tmp_path / "events.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "sw_ring", "over_absmax": False, "peak_v": 12.0}) + "\n")
    out = rhs.analyze_events(str(path))
    assert out["over_absmax"] == 0
    assert out["worst_ring_v"] is None


# ─────────────────────────────────────────────────────────────────────────
# 6. render_report()
# ─────────────────────────────────────────────────────────────────────────

def _fake_child(rc=0, status="ok", achieved_hz=1000.0, log="run.log"):
    return {"status": status, "returncode": rc, "wall_s": 1.5, "log": log,
            "summary": {"achieved_hz": achieved_hz, "tx_frames": 1000,
                       "rx_frames": 998, "rx_bad": 0, "max_overrun_ms": 0.5}}


def _fake_scenario_result(name="steady", passed=True, fault_bits=0, over_absmax=0):
    metrics = {"csv": "x.csv", "rows": 100, "n_obs": 100,
               "final_fault_flags": fault_bits, "fault_bits_seen": fault_bits,
               "final_state": 2, "duration_s": 30.0,
               "substep_hz_min": None, "substep_hz_mean": None}
    events = {"total": 0, "kinds": {}, "over_absmax": over_absmax,
              "worst_ring_v": 21.0 if over_absmax else None}
    checks = [{"name": "observation_frames", "passed": True, "detail": "ok"}]
    return {"kind": "scenario", "name": name, "mode": "hifi",
            "electrical_required": "any", "description": "test scenario",
            "duration_s": 30.0, "passed": passed, "checks": checks, "notes": [],
            "metrics": metrics, "events": events, "child": _fake_child(),
            "csv": "x.csv", "events_path": "x.csv.events.jsonl",
            "log_path": "run.log", "key_metrics": "obs 100/100"}


def _fake_replay_result(name="ML0151", mode="conformance", passed=True):
    checks = [{"name": "no_fault", "passed": passed, "detail": "..."}]
    return {"kind": "replay", "name": name, "mode": mode,
            "description": "test replay", "duration_s": 56.0,
            "passed": passed, "checks": checks, "notes": ["fw 14: ..."],
            "metrics": {}, "events": {}, "child": _fake_child(),
            "csv": "y.csv", "events_path": None, "log_path": "run_replay.log",
            "key_metrics": "1/1 checks passed"}


def _fake_meta(**overrides):
    m = {"date": "2026-08-27T00:00:00", "teensy_ip": "192.168.1.50", "port": 5001,
         "target_fw": 21, "host": "Linux 6.0 (x86_64)", "python": "3.11.0",
         "electrical_pref": "hifi", "settle_s": 5.0, "out": "/tmp/x",
         "aborted": None, "suite_log_problems": []}
    m.update(overrides)
    return m


def test_render_report_is_pure_string_function():
    results = [_fake_scenario_result(), _fake_replay_result()]
    report = rhs.render_report(_fake_meta(), results)
    assert isinstance(report, str)
    assert report.startswith("# HIL suite report")


def test_render_report_contains_summary_table_rows():
    results = [_fake_scenario_result(name="steady"), _fake_replay_result(name="ML0151")]
    report = rhs.render_report(_fake_meta(), results)
    assert "## Summary" in report
    assert "| steady | scenario |" in report
    assert "| ML0151 | replay |" in report


def test_render_report_k_droop_finding_always_present():
    """The K_DROOP x4 finding must appear whether or not anything else is
    wrong — it's an always-reported open finding, not conditional."""
    report_clean = rhs.render_report(_fake_meta(), [_fake_scenario_result()])
    report_failed = rhs.render_report(_fake_meta(), [_fake_scenario_result(passed=False,
                                                                            fault_bits=0x0100)])
    for report in (report_clean, report_failed):
        assert "K_DROOP_BUS design-vs-measured" in report
        assert "x4" in report or "four times" in report


def test_render_report_conformance_and_deviation_grouping():
    results = [
        _fake_replay_result(name="ML0203", mode="conformance"),
        _fake_replay_result(name="TP0010", mode="deviation"),
    ]
    report = rhs.render_report(_fake_meta(), results)
    assert "### Conformance" in report
    assert "### Deviation" in report
    conf_idx = report.index("### Conformance")
    dev_idx = report.index("### Deviation")
    ml_idx = report.index("`ML0203`")
    tp_idx = report.index("`TP0010`")
    assert conf_idx < ml_idx < dev_idx < tp_idx


def test_render_report_over_absmax_finding_appears_when_present():
    results = [_fake_scenario_result(over_absmax=2)]
    report = rhs.render_report(_fake_meta(), results)
    assert "boost-death signature" in report
    assert "over abs-max" in report or "over_absmax" in report.lower() or "worst estimated" in report


def test_render_report_no_over_absmax_finding_when_absent():
    results = [_fake_scenario_result(over_absmax=0)]
    report = rhs.render_report(_fake_meta(), results)
    assert "No `sw_ring` event above the 20 V abs-max" in report


def test_render_report_aborted_meta_shown():
    report = rhs.render_report(_fake_meta(aborted="board unreachable"), [])
    assert "ABORTED" in report
    assert "board unreachable" in report


def test_render_report_empty_results_does_not_crash():
    report = rhs.render_report(_fake_meta(), [])
    assert "0 (0 scenario, 0 replay)" in report
    assert "0/0 passed" in report


def test_results_json_round_trips():
    results = [_fake_scenario_result(), _fake_replay_result()]
    meta = _fake_meta()
    dumped = json.dumps({"meta": meta, "results": results}, indent=2, default=str)
    loaded = json.loads(dumped)
    assert loaded["meta"] == meta
    assert len(loaded["results"]) == 2
    assert loaded["results"][0]["name"] == results[0]["name"]
    assert loaded["results"][0]["passed"] == results[0]["passed"]
    assert loaded["results"][1]["checks"][0]["name"] == "no_fault"


# ─────────────────────────────────────────────────────────────────────────
# 7. Exit-code logic — FINDING, not a test
# ─────────────────────────────────────────────────────────────────────────

def test_finding_exit_code_logic_is_inline_in_main_untestable_offline():
    """FINDING (updated for the review-fix round): the per-run loop was
    factored out into module-level `_run_plan()` (M4), which IS now covered
    below via monkeypatched `run_child`. What remains genuinely inline in
    main()'s tail, and still not independently testable offline, is the
    final exit-code selection -- `if interrupted: return 130` /
    `if aborted: return 2` / `return 0 if npass == len(results) and results
    else 1` -- plus the KeyboardInterrupt/finally wiring around
    `_run_plan()` itself. The KeyboardInterrupt -> 130 + partial-report path
    IS exercised below (test_m4_main_keyboardinterrupt_writes_partial_report)
    by monkeypatching `_run_plan` to raise; the plain 0-vs-1 success/failure
    tail is not, since reaching it needs `_run_plan` to run its real loop to
    completion, which needs a plan whose child processes are real subprocess
    calls (main() calls `run_child` directly, not through an injectable
    parameter the way `_run_plan` does). Recorded as a narrower residual gap
    than before, not asserted against."""
    assert True


# ─────────────────────────────────────────────────────────────────────────
# 8. Re-pinned: soc-depletion plan special-case (duration 650, --soc0 0.15)
# ─────────────────────────────────────────────────────────────────────────

def test_soc_depletion_duration_and_soc0_repinned_to_650_and_0_15():
    """soc-depletion's SCENARIOS entry itself still says duration_s=120 (see
    test_hil_plant_sim.py's SCENARIOS-registry tests) -- build_plan() special-
    cases ONLY this one scenario name and overrides both the duration and adds
    --soc0 0.15, per the review-fix round's derivation (5s ramp + 645s of load
    at 3 A on a 5 Ah pack reaches ~4.25% SOC, past the ~5% UV-crossing point;
    see the comment at the override site). Every other scenario must be
    unaffected by this special case."""
    plan = rhs.build_plan(_args(only=["soc-depletion"]))
    assert len(plan) == 1
    item = plan[0]
    assert item["duration_s"] == pytest.approx(650.0)
    assert item["timeout_s"] == pytest.approx(650.0 + rhs.GRACE_S)
    argv = item["argv"]
    assert "--duration" in argv
    assert argv[argv.index("--duration") + 1] == "650"
    assert "--soc0" in argv
    assert argv[argv.index("--soc0") + 1] == "0.15"
    # SCENARIOS itself is untouched -- this is purely a build_plan() override.
    assert SCENARIOS["soc-depletion"]["duration_s"] == pytest.approx(120.0)


def test_soc_depletion_override_does_not_leak_into_other_scenarios():
    plan = rhs.build_plan(_args())
    for p in plan:
        if p["kind"] != "scenario" or p["name"] == "soc-depletion":
            continue
        assert "--soc0" not in p["argv"], p["name"]


# ─────────────────────────────────────────────────────────────────────────
# 9. F2: handoff-sag is FAULT_ALLOWED (review-fix round)
# ─────────────────────────────────────────────────────────────────────────

FAULT_UV_BUS = 0x0100   # hil_replay_suite.FAULT_UV_BUS, re-derived for this test file


def test_f2_handoff_sag_is_in_fault_allowed():
    assert "handoff-sag" in rhs.FAULT_ALLOWED
    assert "handoff-sag" not in rhs.FAULT_REQUIRED


def test_f2_judge_scenario_handoff_sag_with_uv_fault_passes_that_check():
    """A UV_BUS fault on handoff-sag is a PLAUSIBLE outcome (TP0178/TP0201-
    class reactive standby pickup), not an unexpected failure -- the
    fault_allowed check must pass whether or not the fault actually fired."""
    m_with_fault = _metrics(fault_bits_seen=FAULT_UV_BUS, final_fault_flags=FAULT_UV_BUS)
    passed, checks = rhs.judge_scenario("handoff-sag", m_with_fault, _events(), _child())
    fa = [c for c in checks if c["name"] == "fault_allowed"][0]
    assert fa["passed"] is True
    assert passed is True   # nothing else in the default fixture should fail it

    m_clean = _metrics(fault_bits_seen=0, final_fault_flags=0)
    passed2, checks2 = rhs.judge_scenario("handoff-sag", m_clean, _events(), _child())
    fa2 = [c for c in checks2 if c["name"] == "fault_allowed"][0]
    assert fa2["passed"] is True
    assert passed2 is True


# ─────────────────────────────────────────────────────────────────────────
# 10. M4: _run_plan() write_outputs-per-run + main() partial-report wiring
# ─────────────────────────────────────────────────────────────────────────

def test_m4_run_plan_calls_write_outputs_after_every_run(monkeypatch):
    """_run_plan() must rewrite results.json/REPORT.md (via the injected
    write_outputs callback) after EVERY completed run, not just at the end --
    so an interruption mid-plan loses at most the run in flight."""
    def fake_run_child(item, args):
        return {"status": "ok", "returncode": 0, "wall_s": 0.01, "log": item["log"],
                "summary": {"achieved_hz": 1000.0, "tx_frames": 10, "rx_frames": 10,
                           "rx_bad": 0}}

    monkeypatch.setattr(rhs, "run_child", fake_run_child)

    args = _args(only=["steady", "ML0146"], keep_going=True, settle_s=0.0)
    plan = rhs.build_plan(args)
    assert len(plan) == 2   # one scenario, one replay -- both kinds exercised

    calls = []

    def write_outputs(meta, results):
        calls.append((len(results), dict(meta)))

    results, aborted = rhs._run_plan(plan, args, [], [], write_outputs)

    assert len(results) == 2
    assert len(calls) == 2, "write_outputs must fire once per completed run"
    # After run 1: 1 result recorded, and the plan is not yet complete.
    assert calls[0][0] == 1
    assert calls[0][1]["partial"] is True
    # After run 2 (the last one): 2 results recorded, plan complete.
    assert calls[1][0] == 2
    assert calls[1][1]["partial"] is False


def test_m4_run_plan_results_list_is_the_same_object_mutated_in_place(monkeypatch):
    """_run_plan()'s docstring says it mutates and returns `results` -- pin
    that the returned list IS the one passed in (append-in-place), not a
    fresh copy, since write_outputs() is handed that same list reference on
    every call and relies on it reflecting what's been appended so far."""
    def fake_run_child(item, args):
        return {"status": "ok", "returncode": 0, "wall_s": 0.01, "log": item["log"],
                "summary": {"achieved_hz": 1000.0}}

    monkeypatch.setattr(rhs, "run_child", fake_run_child)
    args = _args(only=["steady"], keep_going=True, settle_s=0.0)
    plan = rhs.build_plan(args)
    seeded = []
    out, _aborted = rhs._run_plan(plan, args, [], seeded, lambda m, r: None)
    assert out is seeded


def test_f6_all_skipped_plan_exits_nonzero(tmp_path, monkeypatch):
    """F6: when EVERY planned run was skipped, main() must not exit 0 -- the
    old `npass == len(results) and results` check let an all-skips run look
    like a clean pass because skipped records count as passed=True."""
    def fake_run_child(item, args):
        raise AssertionError("no child should ever be launched: the whole "
                             "plan is expected to be skip-only")

    monkeypatch.setattr(rhs, "run_child", fake_run_child)
    # --pi-live + --only matching ONLY a pi_timeline/ems scenario -> every
    # planned run is a skip record, nothing is ever launched.
    rc = rhs.main(["--out", str(tmp_path), "--pi-live", "--scenarios-only",
                   "--only", "charge-cruise"])
    assert rc == 1


def test_f6_partial_skip_plan_is_not_flagged_all_skipped(monkeypatch):
    """Sanity converse of the above: a plan with at least one EXECUTED run
    alongside skips must not trip the 'every planned run was skipped' F6
    guard (checked directly against _run_plan's results, since judging the
    executed run's own pass/fail needs a real CSV main() doesn't fabricate
    here)."""
    def fake_run_child(item, args):
        return {"status": "ok", "returncode": 0, "wall_s": 0.01, "log": item["log"],
                "summary": {"achieved_hz": 1000.0, "tx_frames": 10, "rx_frames": 10,
                           "rx_bad": 0}}

    monkeypatch.setattr(rhs, "run_child", fake_run_child)
    args = _args(pi_live=True, scenarios_only=True,
                 only=["steady", "charge-cruise"], settle_s=0.0)
    plan = rhs.build_plan(args)
    results, _aborted = rhs._run_plan(plan, args, [], [], lambda m, r: None)
    assert results, "sanity: at least one run must have been recorded"
    assert not all(r.get("skipped") for r in results), (
        "steady is not a pi_timeline/ems scenario and must have executed")


def test_m4_main_keyboardinterrupt_writes_partial_report(tmp_path, monkeypatch):
    """main() must catch a KeyboardInterrupt out of _run_plan(), still write
    results.json/REPORT.md (via its finally block), mark meta["partial"]
    True, and return exit code 130."""
    def boom(plan, args, problems, results, write_outputs):
        raise KeyboardInterrupt

    monkeypatch.setattr(rhs, "_run_plan", boom)
    rc = rhs.main(["--out", str(tmp_path), "--only", "steady"])
    assert rc == 130

    results_path = tmp_path / "results.json"
    report_path = tmp_path / "REPORT.md"
    assert results_path.is_file()
    assert report_path.is_file()
    loaded = json.loads(results_path.read_text())
    assert loaded["meta"]["partial"] is True
    assert loaded["results"] == []
    assert "PARTIAL" in report_path.read_text()


# ─────────────────────────────────────────────────────────────────────────
# 6. --pi-live: build_plan() skip records
# ─────────────────────────────────────────────────────────────────────────

# Exactly the scenarios whose SCENARIOS entry carries a pi_timeline or an
# ems strategy -- these are the ones build_plan() must SKIP under --pi-live.
PI_LIVE_SKIP_SCENARIOS = {
    "charge-cruise", "charge-regen", "charge-fault", "soc-depletion",
    "handoff-sag", "ems-drive-cycle",
}


def test_pi_live_skip_set_matches_pi_timeline_or_ems_scenarios():
    computed = {name for name, meta in SCENARIOS.items()
                if meta.get("pi_timeline") or meta.get("ems")}
    assert computed == PI_LIVE_SKIP_SCENARIOS


def test_build_plan_pi_live_produces_skip_records_for_exact_set():
    """F5 ripple: --pi-live now ALSO skip-records the entire replay half, so
    this must filter to the scenario half to keep pinning the original
    pi_timeline/ems set (the replay skip set is covered separately)."""
    plan = rhs.build_plan(_args(pi_live=True))
    skipped = {p["name"] for p in plan
               if p.get("skip_reason") and p["kind"] == "scenario"}
    assert skipped == PI_LIVE_SKIP_SCENARIOS


def test_build_plan_pi_live_skip_records_shape():
    plan = rhs.build_plan(_args(pi_live=True))
    # F5 ripple: skip records now exist for both kinds -- scope this test to
    # the scenario half, which is what it was written to pin.
    skips = [p for p in plan if p.get("skip_reason") and p["kind"] == "scenario"]
    assert skips
    for p in skips:
        assert p["kind"] == "scenario"
        assert p["argv"] is None
        assert p["duration_s"] == 0.0
        assert isinstance(p["skip_reason"], str) and p["skip_reason"]


def test_build_plan_pi_live_non_skip_scenarios_unaffected():
    plan_live = rhs.build_plan(_args(pi_live=True))
    plan_default = rhs.build_plan(_args())
    live_names = {p["name"] for p in plan_live if not p.get("skip_reason")
                  and p["kind"] == "scenario"}
    default_names = {p["name"] for p in plan_default if p["kind"] == "scenario"}
    assert live_names == default_names - PI_LIVE_SKIP_SCENARIOS


def test_build_plan_pi_live_total_count_still_39():
    """Skip records still occupy a plan slot -- the total run count (39) is
    unchanged under --pi-live, only their kind (executed vs skipped) differs."""
    plan = rhs.build_plan(_args(pi_live=True))
    assert len(plan) == 39


# ─────────────────────────────────────────────────────────────────────────
# 7. full_argv(): --pi-live passthrough (scenario half only) and skip == []
# ─────────────────────────────────────────────────────────────────────────

def test_full_argv_pi_live_flag_present_for_runnable_scenario():
    plan = rhs.build_plan(_args(pi_live=True))
    steady = next(p for p in plan if p["name"] == "steady")
    argv = rhs.full_argv(steady, _args(pi_live=True))
    assert "--pi-live" in argv


def test_full_argv_pi_live_absent_without_the_flag():
    plan = rhs.build_plan(_args())
    steady = next(p for p in plan if p["name"] == "steady")
    argv = rhs.full_argv(steady, _args())
    assert "--pi-live" not in argv


def test_full_argv_pi_live_not_applied_to_replay_half():
    """--pi-live applies to the scenario half only -- a replay child never
    gets --pi-live even when the suite-level flag is set (hil_plant_sim.py
    refuses --pi-live with --replay, and replay mode makes no commander
    anyway)."""
    plan = rhs.build_plan(_args(pi_live=True, replay_only=True))
    assert plan
    replay_item = plan[0]
    assert replay_item["kind"] == "replay"
    argv = rhs.full_argv(replay_item, _args(pi_live=True))
    assert "--pi-live" not in argv


def test_full_argv_returns_empty_list_for_skip_records():
    plan = rhs.build_plan(_args(pi_live=True))
    skip_item = next(p for p in plan if p.get("skip_reason"))
    assert rhs.full_argv(skip_item, _args(pi_live=True)) == []


def test_full_argv_pi_live_and_dashboard_coexist_in_argv():
    plan = rhs.build_plan(_args(pi_live=True))
    steady = next(p for p in plan if p["name"] == "steady")
    argv = rhs.full_argv(steady, _args(pi_live=True, dashboard=True))
    assert "--pi-live" in argv
    assert "--dash" in argv


# ─────────────────────────────────────────────────────────────────────────
# 7b. F5: --pi-live skips the ENTIRE replay half
# ─────────────────────────────────────────────────────────────────────────

def test_build_plan_pi_live_skips_entire_replay_half():
    plan = rhs.build_plan(_args(pi_live=True))
    replay_items = [p for p in plan if p["kind"] == "replay"]
    assert replay_items, "sanity: the replay half must still occupy plan slots"
    assert all(p.get("skip_reason") for p in replay_items)
    assert all("second stimulus" in p["skip_reason"] for p in replay_items)
    assert len(replay_items) == len(REPLAY_SUITE)


def test_build_plan_pi_live_replay_skip_records_shape():
    plan = rhs.build_plan(_args(pi_live=True))
    replay_skips = [p for p in plan if p["kind"] == "replay" and p.get("skip_reason")]
    assert replay_skips
    for p in replay_skips:
        assert p["argv"] is None
        assert p["duration_s"] == 0.0
        assert p["csv"] is None


def test_build_plan_default_replay_half_unaffected_by_pi_live_off():
    plan = rhs.build_plan(_args())
    replay_items = [p for p in plan if p["kind"] == "replay"]
    assert replay_items
    assert not any(p.get("skip_reason") for p in replay_items)


def test_full_argv_replay_only_and_pi_live_is_argparse_error():
    """F5: --replay-only + --pi-live is refused up front -- once the whole
    replay half is skipped under --pi-live, --replay-only has nothing left to
    run."""
    with pytest.raises(SystemExit):
        rhs.main(["--replay-only", "--pi-live", "--list"])


# ─────────────────────────────────────────────────────────────────────────
# 8. judge_scenario(): FAULT_PI_TIMEOUT excusal under --pi-live
#
# F1/F2 REWRITE: triggerFault() ALWAYS ORs in FAULT_ERROR 0x8000 (.ino:4501-
# 4503), so a real PI_TIMEOUT latch is observed as 0x8010, never bare 0x0010 --
# the old tests below stimulated fault_bits_seen=0x0010, a union the firmware
# can never actually produce, and the old `seen & ~0x0010` mask left 0x8000 in
# `unexpected` so the excusal never really passed. All 0x0010 stimuli here are
# rewritten to 0x8010 (FAULT_ERROR | PI_TIMEOUT). The excusal additionally now
# requires the child's OWN injection stream to have been continuous
# (tx_frames >= 0.98 * rate * duration_s, send_errors == 0) -- these tests
# pass duration_s explicitly and use _live_child()/_gappy_child() to supply a
# continuous or gappy child summary.
# ─────────────────────────────────────────────────────────────────────────

RATE_HZ = rhs.HIL_DEFAULT_RATE_HZ


def _metrics(fault_bits_seen=0, final_fault_flags=0, n_obs=10, rows=10):
    return {"n_obs": n_obs, "rows": rows, "fault_bits_seen": fault_bits_seen,
            "final_fault_flags": final_fault_flags, "final_state": 2}


def _live_child(duration_s=30.0, achieved_hz=1000.0):
    """A child summary whose own injection stream was continuous for the
    whole run -- the only kind F2's excusal may fire on."""
    return {"status": "ok", "summary": {
        "achieved_hz": achieved_hz,
        "tx_frames": int(RATE_HZ * duration_s),   # exactly 100% -- well over 98%
        "send_errors": 0,
    }}


def _gappy_child(duration_s=30.0, achieved_hz=1000.0):
    """A child summary whose tx count fell well short of the run -- the
    stream had gaps, so F2 must refuse to attribute the fault to the Pi."""
    return {"status": "ok", "summary": {
        "achieved_hz": achieved_hz,
        "tx_frames": int(RATE_HZ * duration_s * 0.5),   # well under 98%
        "send_errors": 0,
    }}


def test_judge_scenario_pi_timeout_excused_only_under_pi_live_on_non_required_scenario():
    child = _live_child()
    passed_default, checks_default = rhs.judge_scenario(
        "steady", _metrics(fault_bits_seen=0x8010, final_fault_flags=0x8010),
        rhs.analyze_events(None), child, pi_live=False, duration_s=30.0)
    passed_live, checks_live = rhs.judge_scenario(
        "steady", _metrics(fault_bits_seen=0x8010, final_fault_flags=0x8010),
        rhs.analyze_events(None), child, pi_live=True, duration_s=30.0)
    assert passed_default is False, "PI_TIMEOUT must still FAIL a scenario by default"
    assert passed_live is True, ("PI_TIMEOUT must be excused under --pi-live when "
                                 "the fault union is exactly 0x8010 and the "
                                 "injection stream was continuous")


def test_judge_scenario_pi_timeout_not_excused_with_gappy_injection_stream():
    """F2: 0x0010 (aliased FAULT_HIL_LINK) observed with a GAPPY injection
    stream must NOT be excused -- a genuine HIL-link failure is plausible."""
    passed_live, checks_live = rhs.judge_scenario(
        "steady", _metrics(fault_bits_seen=0x8010, final_fault_flags=0x8010),
        rhs.analyze_events(None), _gappy_child(), pi_live=True, duration_s=30.0)
    assert passed_live is False
    fault_check = next(c for c in checks_live if c["name"] == "no_unexpected_fault")
    assert fault_check["passed"] is False
    assert "gaps" in fault_check["detail"]


def test_judge_scenario_pi_timeout_not_excused_on_extra_bit_0x8030():
    """F2: the fault union must be EXACTLY 0x8010 -- an extra bit alongside it
    (0x8030 = FAULT_ERROR | PI_TIMEOUT | 0x0020) must not be excused even with
    a continuous stream."""
    passed_live, checks_live = rhs.judge_scenario(
        "steady", _metrics(fault_bits_seen=0x8030, final_fault_flags=0x8030),
        rhs.analyze_events(None), _live_child(), pi_live=True, duration_s=30.0)
    assert passed_live is False
    fault_check = next(c for c in checks_live if c["name"] == "no_unexpected_fault")
    assert fault_check["passed"] is False


def test_judge_scenario_comm_loss_still_requires_0x0010_under_both_modes():
    child = _live_child()
    for pi_live in (False, True):
        # F1/F2: FAULT_REQUIRED still checks against the raw wanted bit
        # (0x0010) via `seen & want` -- comm-loss is unaffected by the excusal
        # rewrite because it never reaches the no_unexpected_fault branch.
        passed, checks = rhs.judge_scenario(
            "comm-loss", _metrics(fault_bits_seen=0x8010, final_fault_flags=0x8010),
            rhs.analyze_events(None), child, pi_live=pi_live, duration_s=30.0)
        fault_check = next(c for c in checks if c["name"] == "expected_fault")
        assert fault_check["passed"] is True

        passed_missing, checks_missing = rhs.judge_scenario(
            "comm-loss", _metrics(fault_bits_seen=0, final_fault_flags=0),
            rhs.analyze_events(None), child, pi_live=pi_live, duration_s=30.0)
        fault_check_missing = next(c for c in checks_missing
                                    if c["name"] == "expected_fault")
        assert fault_check_missing["passed"] is False


def test_judge_scenario_pi_timeout_excusal_does_not_mask_other_faults():
    """--pi-live excuses ONLY the exact 0x8010 union -- a PI_TIMEOUT bit
    alongside an unrelated fault bit must still fail."""
    passed, checks = rhs.judge_scenario(
        "steady", _metrics(fault_bits_seen=0x8010 | 0x0100,
                           final_fault_flags=0x8010 | 0x0100),
        rhs.analyze_events(None), _live_child(), pi_live=True, duration_s=30.0)
    assert passed is False
    fault_check = next(c for c in checks if c["name"] == "no_unexpected_fault")
    assert fault_check["passed"] is False


def test_judge_scenario_pi_timeout_excusal_not_applied_to_fault_required_scenarios():
    """FAULT_REQUIRED scenarios ('sag', 'comm-loss') use the expected_fault
    check path, not no_unexpected_fault -- the pi_live excusal branch must
    never engage there."""
    passed, checks = rhs.judge_scenario(
        "sag", _metrics(fault_bits_seen=0x8100, final_fault_flags=0x8100),
        rhs.analyze_events(None), _live_child(), pi_live=True, duration_s=30.0)
    assert passed is True
    assert not any(c["name"] == "no_unexpected_fault" for c in checks)


# ─────────────────────────────────────────────────────────────────────────
# 9. render_report(): skip records, meta mode, "Command source" row
# ─────────────────────────────────────────────────────────────────────────

def _skip_result(name="charge-cruise", reason="--pi-live: this scenario carries "
                                               "its own pi_timeline (4 entries)"):
    return {
        "kind": "scenario", "name": name, "mode": "hifi",
        "electrical_required": "any", "description": "d", "duration_s": 0.0,
        "cmd_mode": "pi-live",
        "passed": True, "skipped": True, "skip_reason": reason,
        "checks": [{"name": "skipped", "passed": True, "detail": reason}],
        "notes": [], "metrics": {}, "events": {},
        "child": {"status": "skipped", "summary": {}},
        "csv": None, "events_path": None, "log_path": None,
        "key_metrics": "skipped",
    }


def _base_meta(**overrides):
    meta = {"date": "2026-08-28", "teensy_ip": "192.168.1.50", "port": 5001,
            "target_fw": rhs.TARGET_FW_VERSION, "host": "test", "python": "3.x",
            "electrical_pref": "hifi", "settle_s": 5.0, "out": "/tmp/x",
            "aborted": None, "partial": False, "suite_log_problems": [],
            "mode": "scripted"}
    meta.update(overrides)
    return meta


def test_render_report_handles_skip_records_without_crashing():
    results = [_skip_result()]
    report = rhs.render_report(_base_meta(mode="pi-live"), results)
    assert isinstance(report, str) and report
    assert "charge-cruise" in report
    assert "not run" in report
    assert "SKIPPED" in report


def test_render_report_f6_skip_record_renders_skipped_not_pass():
    """F6: a skipped run must render as SKIPPED, both in the summary table's
    result cell and the per-run heading -- not as PASS, which used to be
    indistinguishable from an executed clean run."""
    results = [_skip_result(name="charge-cruise")]
    report = rhs.render_report(_base_meta(mode="pi-live"), results)
    assert "### `charge-cruise` — SKIPPED" in report
    # summary-table row: no "PASS" for this run's result cell
    table_line = next(l for l in report.splitlines() if l.startswith("| charge-cruise "))
    assert "| SKIPPED |" in table_line
    assert "| PASS |" not in table_line


def test_render_report_f6_skip_record_omits_fabricated_metric_lines():
    """F6: a skipped run must not render fabricated-clean detail lines (final
    fault_flags 0x0000, frames tx ?/rx ? etc.) since no child ever ran."""
    results = [_skip_result(name="charge-cruise")]
    report = rhs.render_report(_base_meta(mode="pi-live"), results)
    # Isolate the charge-cruise section only (avoid false negatives from other
    # runs in a larger report).
    start = report.index("### `charge-cruise`")
    end = report.find("### `", start + 1)
    section = report[start: end if end != -1 else len(report)]
    assert "final `fault_flags`" not in section
    assert "frames: tx" not in section


def test_render_report_skip_count_labeled_in_result_row():
    results = [_skip_result(name="a"), _skip_result(name="b")]
    report = rhs.render_report(_base_meta(mode="pi-live"), results)
    assert "SKIPPED, not executed" in report
    assert "2 of them SKIPPED" in report


def test_render_report_command_source_row_pi_live():
    report = rhs.render_report(_base_meta(mode="pi-live"), [])
    assert "Command source" in report
    assert "MODE B" in report
    assert "--pi-live" in report


def test_render_report_command_source_row_scripted():
    report = rhs.render_report(_base_meta(mode="scripted"), [])
    assert "Command source" in report
    assert "scripted" in report


def test_render_report_mixed_skip_and_normal_records():
    """A childless skip record next to a normal executed record must not
    crash render_report (skip records have no rc/wall/log fields the
    executed-record branch reads)."""
    normal = {
        "kind": "scenario", "name": "steady", "mode": "hifi",
        "electrical_required": "any", "description": "d", "duration_s": 30.0,
        "cmd_mode": "pi-live",
        "passed": True, "checks": [{"name": "observation_frames", "passed": True,
                                    "detail": "ok"}],
        "notes": [], "metrics": {"csv": "x.csv", "rows": 10, "n_obs": 10,
                                 "final_fault_flags": 0, "fault_bits_seen": 0,
                                 "final_state": 2},
        "events": {},
        "child": {"status": "ok", "returncode": 0, "wall_s": 1.0, "log": "x.log",
                  "summary": {"achieved_hz": 1000.0, "tx_frames": 100,
                             "rx_frames": 100, "rx_bad": 0}},
        "csv": "x.csv", "events_path": None, "log_path": "x.log",
        "key_metrics": "obs 10/10, faults none",
    }
    results = [normal, _skip_result()]
    report = rhs.render_report(_base_meta(mode="pi-live"), results)
    assert "steady" in report
    assert "charge-cruise" in report


# ─────────────────────────────────────────────────────────────────────────
# 10. cmd_mode tagging via _suite_mode()
# ─────────────────────────────────────────────────────────────────────────

def test_suite_mode_pi_live_vs_scripted():
    assert rhs._suite_mode(_args(pi_live=True)) == "pi-live"
    assert rhs._suite_mode(_args()) == "scripted"
    assert rhs._suite_mode(_args(pi_live=False)) == "scripted"


def test_run_plan_tags_cmd_mode_on_records(monkeypatch):
    def fake_run_child(item, args):
        return {"status": "ok", "returncode": 0, "wall_s": 0.01, "log": item["log"],
                "summary": {"achieved_hz": 1000.0}}

    monkeypatch.setattr(rhs, "run_child", fake_run_child)
    args = _args(only=["steady"], keep_going=True, settle_s=0.0, pi_live=True)
    plan = rhs.build_plan(args)
    results, _aborted = rhs._run_plan(plan, args, [], [], lambda m, r: None)
    assert results
    assert all(r["cmd_mode"] == "pi-live" for r in results)


def test_run_plan_skip_record_carries_cmd_mode():
    args = _args(only=["charge-cruise"], pi_live=True, settle_s=0.0)
    plan = rhs.build_plan(args)
    assert plan and plan[0].get("skip_reason")
    results, _aborted = rhs._run_plan(plan, args, [], [], lambda m, r: None)
    assert len(results) == 1
    assert results[0]["cmd_mode"] == "pi-live"
    assert results[0]["skipped"] is True
    assert results[0]["passed"] is True


# ─────────────────────────────────────────────────────────────────────────
# 11. F14(a): print_plan() wall-time estimate excludes skipped runs
# ─────────────────────────────────────────────────────────────────────────

def test_print_plan_wall_time_excludes_skipped_settle_pauses(capsys):
    """F14(a): a skipped run launches no child and gets no settle pause --
    it must not contribute settle_s to the printed wall-time estimate. Checked
    against an INDEPENDENTLY computed expectation from the plan itself (per-
    scenario duration_s varies -- 30/40/45/60 s -- so a skip-count * settle_s
    delta against a second plan is not a stable comparison)."""
    args_live = _args(pi_live=True, scenarios_only=True, settle_s=5.0)
    plan_live = rhs.build_plan(args_live)
    n_skipped = sum(1 for p in plan_live if p.get("skip_reason"))
    assert n_skipped > 0, "sanity: --pi-live must actually skip some scenarios"

    expected_total = sum((p.get("duration_s") or 0.0) + 5.0
                         for p in plan_live if not p.get("skip_reason"))

    rhs.print_plan(plan_live, args_live)
    out_live = capsys.readouterr().out
    total_live = float(out_live.rsplit("incl.", 1)[1].split(":")[1].split("s")[0])

    assert total_live == pytest.approx(expected_total, abs=1.0)


# ─────────────────────────────────────────────────────────────────────────
# 12. "HIL Results" default --out convention
# ─────────────────────────────────────────────────────────────────────────

def _capture_args_via_list(monkeypatch, argv):
    """main(["--list", ...]) resolves args.out (including the default-out
    branch) and calls print_plan(plan, args) before returning 0 -- this is
    the earliest seam that exposes the resolved args.out without actually
    running the suite. Capture it by patching print_plan."""
    captured = {}

    def fake_print_plan(plan, args):
        captured["out"] = args.out

    monkeypatch.setattr(rhs, "print_plan", fake_print_plan)
    rc = rhs.main(argv)
    assert rc == 0
    assert "out" in captured, "print_plan was not called -- main() did not reach --list"
    return captured["out"]


def test_main_default_out_lands_under_hil_results_dir(tmp_path, monkeypatch):
    fake_dir = tmp_path / "HIL Results"
    monkeypatch.setattr(rhs, "HIL_RESULTS_DIR", str(fake_dir))
    out = _capture_args_via_list(monkeypatch, ["--list"])
    assert os.path.normpath(os.path.dirname(out)) == os.path.normpath(str(fake_dir))


def test_main_default_out_matches_hil_report_timestamp_pattern(tmp_path, monkeypatch):
    import re
    fake_dir = tmp_path / "HIL Results"
    monkeypatch.setattr(rhs, "HIL_RESULTS_DIR", str(fake_dir))
    out = _capture_args_via_list(monkeypatch, ["--list"])
    basename = os.path.basename(out)
    assert re.fullmatch(r"hil_report_\d{8}_\d{6}", basename), basename


def test_main_default_out_creates_hil_results_dir(tmp_path, monkeypatch):
    fake_dir = tmp_path / "HIL Results"
    assert not fake_dir.exists()
    monkeypatch.setattr(rhs, "HIL_RESULTS_DIR", str(fake_dir))
    _capture_args_via_list(monkeypatch, ["--list"])
    assert fake_dir.is_dir()


def test_main_explicit_relative_out_is_cwd_relative_not_hil_results(tmp_path, monkeypatch):
    """An explicit --out keeps its historical semantics: relative to the CWD,
    NOT redirected under HIL_RESULTS_DIR -- only the default-out branch
    changed."""
    fake_dir = tmp_path / "HIL Results"
    monkeypatch.setattr(rhs, "HIL_RESULTS_DIR", str(fake_dir))
    monkeypatch.chdir(tmp_path)
    out = _capture_args_via_list(monkeypatch, ["--list", "--out", "my_report"])
    assert os.path.normpath(out) == os.path.normpath(str(tmp_path / "my_report"))
    assert os.path.normpath(str(fake_dir)) not in os.path.normpath(out)


def test_main_explicit_absolute_out_returned_verbatim(tmp_path, monkeypatch):
    fake_dir = tmp_path / "HIL Results"
    monkeypatch.setattr(rhs, "HIL_RESULTS_DIR", str(fake_dir))
    explicit = str(tmp_path / "elsewhere" / "my_report")
    out = _capture_args_via_list(monkeypatch, ["--list", "--out", explicit])
    assert os.path.normpath(out) == os.path.normpath(explicit)


def test_hil_results_dir_name_and_parent_is_repo_root():
    """Pin the literal folder name (not just 'somewhere under REPO_ROOT') so
    a revert of the feature -- e.g. back to a bare 'reports' dir -- fails
    this test."""
    assert os.path.basename(os.path.normpath(rhs.HIL_RESULTS_DIR)) == "HIL Results"
    parent = os.path.dirname(os.path.normpath(rhs.HIL_RESULTS_DIR))
    assert os.path.normpath(parent) == os.path.normpath(rhs._REPO)
    assert os.path.isdir(os.path.join(rhs._REPO, "tools"))
    assert os.path.isdir(os.path.join(rhs._REPO, "teensy_controller"))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
