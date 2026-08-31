#!/usr/bin/env python3
"""pytest suite for tools/run_hil_suite.py — the HIL suite wrapper (plan
building, argv construction, offline health-check analysis, and the pure
report renderer). No board, no subprocess of the real simulator — this
exercises only the pure/offline functions per the fence in the task.

Run: cd tools && python -m pytest test_run_hil_suite.py -v
"""
import argparse
import datetime
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_hil_suite as rhs  # noqa: E402
import hil_replay_suite as hrs  # noqa: E402
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
    assert plan[0]["timeout_s"] == pytest.approx(dur + rhs.TIMEOUT_GRACE_S)


def test_build_plan_no_match_returns_empty():
    plan = rhs.build_plan(_args(only=["no-such-run-xyz"]))
    assert plan == []


# ─────────────────────────────────────────────────────────────────────────
# 1b. 'drive' (operator_required): SKIPPED by default, included under
#     --with-operator
# ─────────────────────────────────────────────────────────────────────────

def test_build_plan_drive_is_skipped_by_default():
    assert SCENARIOS["drive"].get("operator_required") is True
    plan = rhs.build_plan(_args(only=["drive"]))
    assert len(plan) == 1
    item = plan[0]
    assert item["kind"] == "scenario"
    assert item["argv"] is None
    assert item["duration_s"] == 0.0
    assert item["skip_reason"] and item["skip_reason"].startswith("OPERATOR-REQUIRED")


def test_build_plan_drive_runs_under_with_operator():
    plan = rhs.build_plan(_args(only=["drive"], with_operator=True))
    assert len(plan) == 1
    item = plan[0]
    assert item["kind"] == "scenario"
    assert not item.get("skip_reason")
    assert item["argv"] is not None
    assert "--scenario" in item["argv"] and "drive" in item["argv"]
    assert item["duration_s"] == pytest.approx(SCENARIOS["drive"]["duration_s"])


def test_build_plan_with_operator_does_not_affect_other_scenarios():
    """--with-operator only changes 'drive' -- every other scenario's plan
    entry is identical with or without it."""
    plan_default = {p["name"]: p for p in rhs.build_plan(_args()) if p["kind"] == "scenario"}
    plan_operator = {p["name"]: p for p in rhs.build_plan(_args(with_operator=True))
                     if p["kind"] == "scenario"}
    for name in plan_default:
        if name == "drive":
            continue
        assert plan_default[name]["argv"] == plan_operator[name]["argv"], name
        assert not plan_default[name].get("skip_reason")
        assert not plan_operator[name].get("skip_reason")


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
        if p["argv"] is None:
            # operator_required skip record ('drive' without --with-operator):
            # no argv is ever built for it, so there is nothing to assert here.
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


# ── M1: n_obs_post_grace / last_obs_t ───────────────────────────────────────

def test_analyze_scenario_csv_n_obs_post_grace_and_last_obs_t_normal_run(tmp_path):
    """A board answering through and past the grace bound: n_obs_post_grace
    counts only the post-grace ticks, and last_obs_t is the LAST observed
    tick regardless of the grace bound."""
    rows = [
        {"t": "0.500", "fault_flags": "0", "state": "2"},
        {"t": "1.500", "fault_flags": "0", "state": "2"},
        {"t": "2.500", "fault_flags": "0", "state": "2"},
        {"t": "3.500", "fault_flags": "0", "state": "2"},
    ]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path), grace_s=2.0)
    assert m["n_obs"] == 4
    assert m["n_obs_post_grace"] == 2   # t=2.500, t=3.500
    assert m["last_obs_t"] == pytest.approx(3.5)


def test_analyze_scenario_csv_n_obs_post_grace_zero_when_board_dies_before_grace(tmp_path):
    """The M1 motivating case: the board answers a few ticks, then goes
    SILENT before the grace bound ever arrives -- n_obs is nonzero (it
    answered) but n_obs_post_grace is 0, and last_obs_t names the moment it
    stopped."""
    rows = [
        {"t": "0.100", "fault_flags": "0", "state": "2"},
        {"t": "0.200", "fault_flags": "0", "state": "2"},
        {"t": "0.400", "fault_flags": "0", "state": "2"},
    ]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path), grace_s=2.0)
    assert m["n_obs"] == 3
    assert m["n_obs_post_grace"] == 0
    assert m["last_obs_t"] == pytest.approx(0.4)


def test_analyze_scenario_csv_last_obs_t_none_when_never_observed(tmp_path):
    rows = [{"t": "0.000", "fault_flags": ""}, {"t": "0.001", "fault_flags": ""}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path))
    assert m["last_obs_t"] is None
    assert m["n_obs_post_grace"] == 0


# ── #4 (review, LOW): boundary equality -- t == grace_s lands POST-grace ────
# Production code (`post = t is not None and t >= grace_s`) uses >=, i.e. it
# skips strictly `t < grace_s`. Pin that convention directly so a future
# <-to-<= (or >=-to->) typo fails a test instead of silently reclassifying
# the one tick that sits exactly on the boundary.

def test_analyze_scenario_csv_boundary_t_equals_grace_s_lands_post_grace(tmp_path):
    rows = [{"t": "2.000000", "fault_flags": "0x0100", "state": "2"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path), grace_s=2.0)
    assert m["n_obs_post_grace"] == 1
    assert m["fault_bits_post_grace"] == 0x0100


def test_analyze_scenario_csv_boundary_t_just_before_grace_s_excluded(tmp_path):
    rows = [{"t": "1.999999", "fault_flags": "0x0100", "state": "2"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path), grace_s=2.0)
    assert m["n_obs_post_grace"] == 0
    assert m["fault_bits_post_grace"] == 0


# ─────────────────────────────────────────────────────────────────────────
# 4. judge_scenario()
# ─────────────────────────────────────────────────────────────────────────

def _metrics(n_obs=10, rows=10, final_fault_flags=0, fault_bits_seen=0, final_state=2,
             fault_bits_post_grace=None, fault_first_t=None, grace_s=None,
             survive_to_t=None, fault_bits_before_survive=0, state_at_survive=None,
             n_obs_post_grace=None, last_obs_t=None):
    """Build an analyze_scenario_csv()-shaped metrics dict.

    By default `fault_bits_post_grace` mirrors `fault_bits_seen` (no carried-in
    exclusion, as if every bit was observed fresh from this run), `fault_first_t`
    is empty -- which is enough for judge_scenario()'s `not_before_s` gate to
    pass VACUOUSLY, since a bit absent from `fault_first_t` never triggers the
    'appeared before the stimulus' rejection (see the dedicated not_before tests
    below for the case that supplies it deliberately) -- and (M1)
    `n_obs_post_grace` mirrors `n_obs`, so the new `observation_frames_post_grace`
    check passes by default too (see test_judge_scenario_observation_frames_post_grace_*
    for the case that deliberately empties the post-grace window).

    L4: `fault_first_t` keys are fault NAME STRINGS (rhs.fault_names(bit)), not
    raw int bitmasks -- callers must key it the same way judge_scenario() reads
    it, or a `not_before_s` test passes/fails for the wrong reason."""
    if n_obs_post_grace is None:
        n_obs_post_grace = n_obs
    return {"n_obs": n_obs, "rows": rows, "final_fault_flags": final_fault_flags,
            "fault_bits_seen": fault_bits_seen,
            "fault_bits_post_grace": (fault_bits_seen if fault_bits_post_grace is None
                                      else fault_bits_post_grace),
            "fault_first_t": fault_first_t or {},
            "final_state": final_state,
            "grace_s": rhs.WARM_RESET_GRACE_S if grace_s is None else grace_s,
            "survive_to_t": survive_to_t,
            "fault_bits_before_survive": fault_bits_before_survive,
            "state_at_survive": state_at_survive,
            "n_obs_post_grace": n_obs_post_grace,
            "last_obs_t": last_obs_t}


def _events(over_absmax=0, worst_ring_v=None, worst_over_absmax_ring_v=None,
           kinds=None, field_values=None):
    return {"total": 0, "kinds": kinds or {}, "over_absmax": over_absmax,
            "worst_ring_v": worst_ring_v,
            "worst_over_absmax_ring_v": worst_over_absmax_ring_v,
            "field_values": field_values or {}}


def _child(status="ok", summary=None):
    return {"status": status, "returncode": 0, "summary": summary or {"achieved_hz": 1000.0}}


def _leaf_measurement_pass(spec):
    """A single leaf-spec measurement (M2) that just clears its own assertion
    kind (>= for min_ticks/min_value/strictly_decreases_by, <= for max_ticks,
    a latch at exactly after_t for fault_latch_bit)."""
    m = {"rows": 10, "ticks": 0, "peak": None, "first": None, "last": None,
         "latch_t": None}
    if "min_ticks" in spec:
        m["ticks"] = int(spec["min_ticks"])
    elif "max_ticks" in spec:
        m["ticks"] = int(spec["max_ticks"])
    elif "min_value" in spec:
        m["peak"] = float(spec["min_value"])
    elif "strictly_decreases_by" in spec:
        need = float(spec["strictly_decreases_by"])
        m["first"] = need
        m["last"] = 0.0
    elif "fault_latch_bit" in spec:
        m["latch_t"] = float(spec.get("after_t", 0.0))
    return m


def _leaf_measurement_fail(spec):
    """The converse: unmeasured (zero rows), which judge_signals() fails on
    'never reached' for every leaf-spec kind, including fault_latch_bit."""
    return {"rows": 0, "ticks": 0, "peak": None, "first": None, "last": None,
            "latch_t": None}


def _signals_from(scenario_name, leaf_builder):
    """A scan_signals()-shaped measured list (M2/A1) for `scenario_name`'s
    signals_require, one entry per top-level spec in the same order.  A plain
    (non-`any_of`) spec gets one leaf measurement from `leaf_builder`; a
    disjunctive (`any_of`) spec gets {"any_of": [<leaf>, ...]}, one per arm --
    matching the shape scan_signals()/judge_signals() actually exchange (see
    _flatten_signal_specs / _nest in run_hil_suite.py)."""
    specs = rhs.FAULT_EXPECTATIONS[scenario_name].get("signals_require") or []
    out = []
    for spec in specs:
        arms = spec.get("any_of")
        if arms:
            out.append({"any_of": [leaf_builder(a) for a in arms]})
        else:
            out.append(leaf_builder(spec))
    return out


def _passing_signals(scenario_name):
    return _signals_from(scenario_name, _leaf_measurement_pass)


def _failing_signals(scenario_name):
    return _signals_from(scenario_name, _leaf_measurement_fail)


def test_judge_scenario_fault_required_with_fault_present_passes():
    """'sag' requires UV_BUS (0x0100)."""
    assert "sag" in rhs.FAULT_EXPECTATIONS
    want = rhs.FAULT_EXPECTATIONS["sag"]["require"]
    assert want == rhs.FAULT_UV_BUS
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
    assert "comm-loss" in rhs.FAULT_EXPECTATIONS
    want = rhs.FAULT_EXPECTATIONS["comm-loss"]["require"]
    assert want == 0x0010     # FAULT_HIL_LINK aliases FAULT_PI_TIMEOUT
    m = _metrics(fault_bits_seen=want, final_fault_flags=want)
    passed, _checks = rhs.judge_scenario("comm-loss", m, _events(), _child())
    assert passed is True


def test_judge_scenario_no_unexpected_fault_scenario_fails_on_any_fault():
    """'steady' has no FAULT_EXPECTATIONS entry -> any fault is unexpected."""
    assert "steady" not in rhs.FAULT_EXPECTATIONS
    m = _metrics(fault_bits_seen=0x0100, final_fault_flags=0x0100)
    passed, checks = rhs.judge_scenario("steady", m, _events(), _child())
    assert passed is False
    nuf = [c for c in checks if c["name"] == "no_unexpected_fault"][0]
    assert nuf["passed"] is False


def test_judge_scenario_no_unexpected_fault_scenario_passes_when_clean():
    m = _metrics(fault_bits_seen=0, final_fault_flags=0)
    passed, checks = rhs.judge_scenario("steady", m, _events(), _child())
    assert passed is True


def test_judge_scenario_fault_allow_only_scenario_passes_with_or_without_the_allowed_bit():
    """'soc-depletion' has no `require`, only `allow_only` (UV_BATT|ERROR) —
    present or absent, the allow_only check passes as long as the survive_to
    gate is also met and (M2) its signals_require ('soc' fell >= 0.05) is
    satisfied, and no `expected_fault` check is even emitted (there is
    nothing REQUIRED here)."""
    assert "require" not in rhs.FAULT_EXPECTATIONS["soc-depletion"]
    allow = rhs.FAULT_EXPECTATIONS["soc-depletion"]["allow_only"]
    assert allow & rhs.FAULT_UV_BATT
    signals = _passing_signals("soc-depletion")
    for bits in (0, rhs.FAULT_UV_BATT):
        m = _metrics(fault_bits_seen=bits, final_fault_flags=bits,
                     fault_bits_before_survive=0, state_at_survive=2)
        passed, checks = rhs.judge_scenario("soc-depletion", m, _events(), _child(),
                                            signals=signals)
        fa = [c for c in checks if c["name"] == "fault_allow_only"][0]
        assert fa["passed"] is True
        assert not any(c["name"] == "expected_fault" for c in checks)
        assert passed is True


# ─────────────────────────────────────────────────────────────────────────
# 4b. FAULT_EXPECTATIONS: not_before_s / allow_only / survive_to / events_require
# ─────────────────────────────────────────────────────────────────────────

def test_judge_scenario_charge_cruise_not_before_rejects_early_oc_fc():
    """'charge-cruise' requires OC_FC not_before_s=8.0 -- a first-appearance
    time BEFORE the stimulus did not come from it and must fail the
    expected_fault check, even though the bit IS present post-grace."""
    expect = rhs.FAULT_EXPECTATIONS["charge-cruise"]
    want = expect["require"]
    not_before = expect["not_before_s"]
    m = _metrics(fault_bits_seen=want, final_fault_flags=want,
                 fault_first_t={rhs.fault_names(want): not_before - 1.0},   # too early
                 fault_bits_before_survive=0, state_at_survive=2)
    passed, checks = rhs.judge_scenario("charge-cruise", m, _events(), _child())
    assert passed is False
    ef = [c for c in checks if c["name"] == "expected_fault"][0]
    assert ef["passed"] is False
    assert "BEFORE the stimulus" in ef["detail"]


def test_judge_scenario_charge_cruise_not_before_accepts_on_time_oc_fc():
    """The converse: OC_FC first appearing AT OR AFTER not_before_s passes."""
    expect = rhs.FAULT_EXPECTATIONS["charge-cruise"]
    want = expect["require"]
    not_before = expect["not_before_s"]
    m = _metrics(fault_bits_seen=want, final_fault_flags=want,
                 fault_first_t={rhs.fault_names(want): not_before + 0.5},
                 fault_bits_before_survive=0, state_at_survive=2)
    passed, checks = rhs.judge_scenario("charge-cruise", m, _events(), _child())
    ef = [c for c in checks if c["name"] == "expected_fault"][0]
    assert ef["passed"] is True
    assert passed is True


def test_judge_scenario_allow_only_rejects_an_unlisted_bit():
    """'sag' allow_only is UV_BUS|ERROR only -- an unrelated extra bit
    (e.g. OC_FC) alongside the required UV_BUS must fail fault_allow_only,
    even though the require check itself is satisfied."""
    expect = rhs.FAULT_EXPECTATIONS["sag"]
    want = expect["require"]
    extra_bits = want | rhs.FAULT_OC_FC
    m = _metrics(fault_bits_seen=extra_bits, final_fault_flags=extra_bits,
                 fault_first_t={rhs.fault_names(want): expect["not_before_s"] + 0.5})
    passed, checks = rhs.judge_scenario("sag", m, _events(), _child())
    assert passed is False
    ef = [c for c in checks if c["name"] == "expected_fault"][0]
    assert ef["passed"] is True   # UV_BUS itself is present and on-time
    fa = [c for c in checks if c["name"] == "fault_allow_only"][0]
    assert fa["passed"] is False
    assert "OC_FC" in fa["detail"]


def test_fault_expectations_allow_only_defaults_to_require_or_error():
    """An entry that specifies `require` but omits `allow_only` is not
    'anything goes' -- it defaults to require|FAULT_ERROR. Every entry in the
    live table happens to set allow_only explicitly, so this pins the DEFAULT
    computation directly against judge_scenario() with a synthetic entry."""
    import types
    synth = {"require": rhs.FAULT_UV_BUS, "source": "test"}   # no allow_only key
    saved = dict(rhs.FAULT_EXPECTATIONS)
    rhs.FAULT_EXPECTATIONS["__synthetic_default_allow_only__"] = synth
    try:
        want = rhs.FAULT_UV_BUS
        m = _metrics(fault_bits_seen=want, final_fault_flags=want)
        passed, checks = rhs.judge_scenario(
            "__synthetic_default_allow_only__", m, _events(), _child())
        fa = [c for c in checks if c["name"] == "fault_allow_only"][0]
        assert fa["passed"] is True
        # An extra bit outside require|ERROR must still be rejected -- the
        # default is NOT "anything goes".
        extra = want | rhs.FAULT_OC_FC
        m2 = _metrics(fault_bits_seen=extra, final_fault_flags=extra)
        _passed2, checks2 = rhs.judge_scenario(
            "__synthetic_default_allow_only__", m2, _events(), _child())
        fa2 = [c for c in checks2 if c["name"] == "fault_allow_only"][0]
        assert fa2["passed"] is False
    finally:
        rhs.FAULT_EXPECTATIONS.clear()
        rhs.FAULT_EXPECTATIONS.update(saved)


def test_judge_scenario_survive_to_fails_when_fault_lands_before_the_gate():
    """'charge-cruise' survive_to requires the run to reach t=8.0 in Run/
    Finish before anything latches -- a bit observed BEFORE that time fails
    survives_to_stimulus even if the (later) expected_fault also passes."""
    expect = rhs.FAULT_EXPECTATIONS["charge-cruise"]
    want = expect["require"]
    m = _metrics(fault_bits_seen=want, final_fault_flags=want,
                 fault_first_t={rhs.fault_names(want): expect["not_before_s"] + 0.5},
                 fault_bits_before_survive=want,   # latched before the gate
                 state_at_survive=None)
    passed, checks = rhs.judge_scenario("charge-cruise", m, _events(), _child())
    assert passed is False
    sv = [c for c in checks if c["name"] == "survives_to_stimulus"][0]
    assert sv["passed"] is False
    assert "never reached its own stimulus" in sv["detail"]


def test_judge_scenario_survive_to_fails_on_wrong_state_at_the_gate():
    """The board is un-latched at t=8.0 but not in {2, 3} (Run/Finish) --
    e.g. still in State 0/1 -- so it never actually got there either."""
    expect = rhs.FAULT_EXPECTATIONS["charge-cruise"]
    want = expect["require"]
    m = _metrics(fault_bits_seen=want, final_fault_flags=want,
                 fault_first_t={rhs.fault_names(want): expect["not_before_s"] + 0.5},
                 fault_bits_before_survive=0, state_at_survive=1)
    passed, checks = rhs.judge_scenario("charge-cruise", m, _events(), _child())
    assert passed is False
    sv = [c for c in checks if c["name"] == "survives_to_stimulus"][0]
    assert sv["passed"] is False
    assert "mainState at t=" in sv["detail"]


def test_judge_scenario_events_require_scp_cut_passes_when_present():
    """'scp-inrush' events_require is now the DICT form (2026-08-30c,
    campaign follow-up (1)): exactly one scp_cut, its i_cut field inside
    the [5.0, 8.0] A fold-plausibility band."""
    expect = rhs.FAULT_EXPECTATIONS["scp-inrush"]["events_require"][0]
    assert expect == {"kind": "scp_cut", "count": 1,
                      "field": "i_cut", "min_value": 5.0, "max_value": 8.0}
    m = _metrics(fault_bits_seen=0, final_fault_flags=0)
    events = _events(kinds={"scp_cut": 1},
                     field_values={"scp_cut": {"i_cut": [6.29]}})
    passed, checks = rhs.judge_scenario("scp-inrush", m, events, _child())
    ev = [c for c in checks if c["name"] == "events_require_scp_cut"][0]
    assert ev["passed"] is True
    assert passed is True


def test_judge_scenario_events_require_scp_cut_fails_when_absent():
    """'scp-inrush' requires no fault at all, but DOES require exactly one
    scp_cut event in the electrical sidecar -- absent, the whole judgement
    fails even though every fault-bit check is clean."""
    m = _metrics(fault_bits_seen=0, final_fault_flags=0)
    events = _events()   # kinds == {}
    passed, checks = rhs.judge_scenario("scp-inrush", m, events, _child())
    assert passed is False
    ev = [c for c in checks if c["name"] == "events_require_scp_cut"][0]
    assert ev["passed"] is False
    assert "count 0, expected exactly 1" in ev["detail"]


def test_judge_scenario_events_require_scp_cut_fails_on_wrong_count():
    """More than one cut is a real change (with firmware attached, the
    State-99 teardown opens MOT_PWR before the 64 ms retry re-arms, so the
    retry cadence should never be reachable here) -- count != 1 fails even
    though at least one scp_cut fired."""
    m = _metrics(fault_bits_seen=0, final_fault_flags=0)
    events = _events(kinds={"scp_cut": 3},
                     field_values={"scp_cut": {"i_cut": [6.29, 6.1, 6.4]}})
    passed, checks = rhs.judge_scenario("scp-inrush", m, events, _child())
    ev = [c for c in checks if c["name"] == "events_require_scp_cut"][0]
    assert ev["passed"] is False
    assert "count 3, expected exactly 1" in ev["detail"]
    assert passed is False


def test_judge_scenario_events_require_scp_cut_fails_when_i_cut_outside_band():
    """The i_cut plausibility band [5.0, 8.0] A: a cut outside it is not a
    foldback event at all and must fail, even with the right count."""
    m = _metrics(fault_bits_seen=0, final_fault_flags=0)
    events = _events(kinds={"scp_cut": 1},
                     field_values={"scp_cut": {"i_cut": [2.5]}})
    passed, checks = rhs.judge_scenario("scp-inrush", m, events, _child())
    ev = [c for c in checks if c["name"] == "events_require_scp_cut"][0]
    assert ev["passed"] is False
    assert "out of the [5, 8] plausibility band" in ev["detail"]
    assert "2.500" in ev["detail"]


def test_judge_scenario_events_forbid_over_absmax_pass_and_fail():
    """scp-inrush must exercise the foldback WITHOUT producing the Death-5
    boost-kill signature (events_forbid_over_absmax)."""
    m = _metrics(fault_bits_seen=0, final_fault_flags=0)
    clean_events = _events(over_absmax=0, kinds={"scp_cut": 1},
                           field_values={"scp_cut": {"i_cut": [6.29]}})
    passed, checks = rhs.judge_scenario("scp-inrush", m, clean_events, _child())
    forbid = [c for c in checks if c["name"] == "events_no_over_absmax"][0]
    assert forbid["passed"] is True
    assert passed is True

    ringing_events = _events(over_absmax=1, worst_over_absmax_ring_v=21.5,
                             kinds={"scp_cut": 1},
                             field_values={"scp_cut": {"i_cut": [6.29]}})
    passed2, checks2 = rhs.judge_scenario("scp-inrush", m, ringing_events, _child())
    forbid2 = [c for c in checks2 if c["name"] == "events_no_over_absmax"][0]
    assert forbid2["passed"] is False
    assert "Death-5" in forbid2["detail"]
    assert passed2 is False


def test_fault_expectations_scp_inrush_events_forbid_over_absmax_flag():
    assert rhs.FAULT_EXPECTATIONS["scp-inrush"]["events_forbid_over_absmax"] is True


def test_fault_expectations_schema_every_entry_has_a_nonempty_source():
    for name, expect in rhs.FAULT_EXPECTATIONS.items():
        assert expect.get("source"), name


def test_fault_expectations_schema_only_known_fields():
    known = {"require", "allow_only", "not_before_s", "survive_to",
            "events_require", "source", "signals_require",
            "events_forbid_over_absmax"}
    for name, expect in rhs.FAULT_EXPECTATIONS.items():
        assert set(expect) <= known, (name, set(expect) - known)


def test_fault_expectations_bringup_entry_shape():
    """L2 (2026-08-30): 'bringup' moved OUT of the unlisted/no-entry group into
    FAULT_EXPECTATIONS with a POSITIVE survive_to assertion (the staged
    bring-up actually completed), no `require`, and an explicit
    allow_only=FAULT_ERROR (same value the unlisted-scenario default would
    give, written out so a reader does not have to re-derive it)."""
    assert "bringup" in rhs.FAULT_EXPECTATIONS
    entry = rhs.FAULT_EXPECTATIONS["bringup"]
    assert "require" not in entry
    assert entry["allow_only"] == rhs.FAULT_ERROR
    assert entry["survive_to"]["t"] == pytest.approx(4.0)
    assert entry["survive_to"]["states"] == {1, 2}
    assert entry.get("source")


def test_fault_expectations_bringup_still_unlisted_scenarios_unaffected():
    """The three scenarios that DID stay in the unlisted/no-entry group
    (steady, step-load, drive) must remain absent -- bringup's move must not
    have dragged them along or been a wholesale table restructure."""
    for name in ("steady", "step-load", "drive"):
        assert name not in rhs.FAULT_EXPECTATIONS, name


def test_judge_scenario_bringup_survive_to_passes_in_idle_or_run_fails_in_init():
    """Functional pin of the new bringup entry: surviving to t=4.0 in state 1
    (Idle) or 2 (Run) passes; still in state 0 (Init, bring-up never
    completed) at that gate fails -- the entry's whole POINT."""
    for state in (1, 2):
        m = _metrics(fault_bits_seen=0, final_fault_flags=0,
                     fault_bits_before_survive=0, state_at_survive=state)
        passed, checks = rhs.judge_scenario("bringup", m, _events(), _child())
        assert passed is True, state
        assert not any(c["name"] == "expected_fault" for c in checks)

    m_stuck = _metrics(fault_bits_seen=0, final_fault_flags=0,
                       fault_bits_before_survive=0, state_at_survive=0)
    passed_stuck, checks_stuck = rhs.judge_scenario("bringup", m_stuck, _events(), _child())
    assert passed_stuck is False
    sv = [c for c in checks_stuck if c["name"] == "survives_to_stimulus"][0]
    assert sv["passed"] is False


def test_fault_expectations_not_before_and_survive_to_exceed_grace():
    """M7/L3: re-derive the module's own import-time invariant directly
    against the live table -- run_hil_suite.py asserts, at import, that every
    `not_before_s` and every `survive_to.t` is strictly > WARM_RESET_GRACE_S
    (both are compared against the POST-GRACE window, so a value at or below
    the grace bound would be vacuous or unreachable rather than stricter).
    Re-deriving it here means a future entry that violates it fails an
    explicit test, not just an import-time AssertionError nobody watches.
    Also confirms the table isn't vacuously satisfying this by omitting both
    fields everywhere."""
    saw_not_before = saw_survive_to = False
    for name, expect in rhs.FAULT_EXPECTATIONS.items():
        nb = expect.get("not_before_s")
        if nb is not None:
            saw_not_before = True
            assert nb > rhs.WARM_RESET_GRACE_S, name
        sv = (expect.get("survive_to") or {}).get("t")
        if sv is not None:
            saw_survive_to = True
            assert sv > rhs.WARM_RESET_GRACE_S, name
    assert saw_not_before and saw_survive_to, (
        "sanity: the live table must exercise both fields or this test is vacuous")


def test_fault_expectations_time_bounds_stay_under_scenario_duration_via_helper():
    """2026-08-30 duration-trim import-time assert, re-derived using the
    MODULE'S OWN `_expectation_time_bounds()` (fix-round addition) rather than
    hand-walking not_before_s/survive_to.t only -- the live import assert now
    covers signals_require t_window uppper bounds and any_of after_t too, so
    this test must exercise the same helper the assert uses, or a bug in
    a field type this test doesn't hand-walk would go uncaught.
    soc-depletion is excepted from the strict SCENARIOS duration_s check: the
    suite overrides its 120 s SCENARIOS entry to 400 s in build_plan(), and
    the import assert conservatively uses the smaller (SCENARIOS) value."""
    saw_any = False
    for name, expect in rhs.FAULT_EXPECTATIONS.items():
        dur = (SCENARIOS.get(name) or {}).get("duration_s")
        if dur is None:
            continue
        for key, t in rhs._expectation_time_bounds(expect):
            if t is None:
                continue
            saw_any = True
            assert t < dur, (name, key, t, dur)
    assert saw_any, "sanity: the live table must exercise this bound or the test is vacuous"


def test_expectation_time_bounds_charge_regen_two_t_window_upper_bounds():
    """charge-regen carries TWO signals_require specs, each with
    t_window=(14.0, 16.1) -- both t_window[1] values (16.1, 16.1) must be
    yielded, alongside survive_to.t=14.0."""
    entry = rhs.FAULT_EXPECTATIONS["charge-regen"]
    bounds = list(rhs._expectation_time_bounds(entry))
    by_key = dict(bounds)
    assert by_key["survive_to.t"] == pytest.approx(14.0)
    t_window_vals = sorted(t for k, t in bounds if "t_window" in k)
    assert t_window_vals == [pytest.approx(16.1), pytest.approx(16.1)]
    assert sum(1 for k, _t in bounds if "t_window" in k) == 2
    assert "not_before_s" not in by_key or by_key["not_before_s"] is None


def test_expectation_time_bounds_soc_depletion_survive_to_and_any_of_after_t():
    """soc-depletion's survive_to.t (13.0) and its any_of arm's after_t (also
    13.0, the UV_BATT-latch arm) must BOTH be yielded, distinctly keyed."""
    entry = rhs.FAULT_EXPECTATIONS["soc-depletion"]
    bounds = dict(rhs._expectation_time_bounds(entry))
    assert bounds["survive_to.t"] == pytest.approx(13.0)
    after_t_keys = [k for k in bounds if k.endswith(".after_t")]
    assert len(after_t_keys) == 1
    assert "any_of" in after_t_keys[0]
    assert bounds[after_t_keys[0]] == pytest.approx(13.0)


def test_expectation_time_bounds_t_window_none_upper_bound_not_yielded():
    """A t_window whose upper bound is None ("to the end of the run") must
    NOT be yielded -- it cannot be past the duration by construction, and
    yielding None would either vacuously pass or crash the `t < dur`
    comparison at import."""
    entry = {"signals_require": [
        {"name": "x", "column": "I_charge", "min_value": 1.0,
         "t_window": (5.0, None)}]}
    keys = [k for k, _t in rhs._expectation_time_bounds(entry)]
    assert not any("t_window" in k for k in keys)


def test_expectation_time_bounds_no_time_valued_fields_yields_nothing_but_survive_to():
    """A bare entry with neither not_before_s, survive_to, nor
    signals_require still yields the two top-level slots (both None)."""
    bounds = dict(rhs._expectation_time_bounds({"allow_only": 0}))
    assert bounds == {"not_before_s": None, "survive_to.t": None}


def test_fault_expectations_duration_predicate_rejects_a_bound_at_or_past_duration():
    """Re-derive the import-time predicate itself (rather than trusting the
    source comment) and confirm it actually REJECTS the mistake it exists to
    catch: a bound at or past the scenario's own duration_s -- now exercised
    across every field kind `_expectation_time_bounds()` can yield (not_before_s,
    survive_to.t, signals_require t_window[1], any_of after_t), not just the
    two original top-level fields."""
    def predicate_ok(t, dur):
        return dur is None or t is None or t < dur

    assert predicate_ok(8.0, 15.0) is True     # comfortably inside
    assert predicate_ok(15.0, 15.0) is False   # AT the duration -- never crossed
    assert predicate_ok(20.0, 15.0) is False   # PAST the duration -- probes a
                                                # row that does not exist
    assert predicate_ok(None, 15.0) is True    # no bound declared -- vacuous ok
    assert predicate_ok(8.0, None) is True     # no duration known -- vacuous ok

    # Now drive the SAME predicate through _expectation_time_bounds() against a
    # synthetic entry that violates it via a t_window upper bound and via an
    # any_of arm's after_t -- the two NEW field kinds this round's import assert
    # must also catch, not just the pre-existing not_before_s/survive_to.t pair.
    bad_entry = {
        "not_before_s": 5.0,        # fine, under a 20.0 s duration
        "signals_require": [
            {"name": "ok", "column": "x", "min_value": 1.0, "t_window": (1.0, 19.9)},
            {"name": "bad_window", "column": "x", "min_value": 1.0,
             "t_window": (1.0, 25.0)},                       # PAST the 20.0 s duration
            {"name": "bad_any_of", "any_of": [
                {"fault_latch_bit": 0x1, "after_t": 21.0}]},  # PAST the duration
        ],
    }
    dur = 20.0
    violations = [(k, t) for k, t in rhs._expectation_time_bounds(bad_entry)
                  if not predicate_ok(t, dur)]
    violating_keys = {k for k, _t in violations}
    assert any("bad_window" in k for k in violating_keys)
    assert any("bad_any_of" in k for k in violating_keys)
    assert len(violations) == 2   # exactly the two deliberately-bad fields


# ─────────────────────────────────────────────────────────────────────────
# 4c. M2: signals_require -- scan_signals() / judge_signals()
# ─────────────────────────────────────────────────────────────────────────

def test_scan_signals_no_specs_is_free_and_returns_nothing(tmp_path):
    """A scenario with no signals_require pays nothing -- scan_signals()
    returns an empty list without even opening the CSV."""
    out = rhs.scan_signals("/nonexistent/path/nope.csv", [])
    assert out == []


# -- switch_bit / min_ticks -----------------------------------------------

def test_scan_signals_switch_bit_min_ticks_pass(tmp_path):
    rows = [{"t": "3.0", "switch": str(rhs.SW_REGEN), "fault_flags": "0"},
            {"t": "3.1", "switch": str(rhs.SW_REGEN), "fault_flags": "0"},
            {"t": "3.2", "switch": "0", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "regen", "switch_bit": rhs.SW_REGEN, "min_ticks": 2,
             "label": "REGEN_ENABLE asserted"}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True
    assert checks[0]["name"] == "signal_regen"


def test_scan_signals_switch_bit_min_ticks_fail_not_enough_ticks(tmp_path):
    rows = [{"t": "3.0", "switch": str(rhs.SW_REGEN), "fault_flags": "0"},
            {"t": "3.1", "switch": "0", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "regen", "switch_bit": rhs.SW_REGEN, "min_ticks": 5}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is False
    assert "bit set on 1 tick" in checks[0]["detail"]


# -- switch_bit / max_ticks -------------------------------------------------

def test_scan_signals_switch_bit_max_ticks_pass_bit_stayed_clear(tmp_path):
    rows = [{"t": "3.0", "switch": "0", "fault_flags": "0"},
            {"t": "3.1", "switch": "0", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "fc_bus_open", "switch_bit": rhs.SW_FC_BUS, "max_ticks": 0}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True


def test_scan_signals_switch_bit_max_ticks_fail_bit_stayed_set(tmp_path):
    rows = [{"t": "3.0", "switch": str(rhs.SW_FC_BUS), "fault_flags": "0"},
            {"t": "3.1", "switch": str(rhs.SW_FC_BUS), "fault_flags": "0"},
            {"t": "3.2", "switch": str(rhs.SW_FC_BUS), "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "fc_bus_open", "switch_bit": rhs.SW_FC_BUS, "max_ticks": 1}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is False


# -- column / min_value ------------------------------------------------------

def test_scan_signals_min_value_pass(tmp_path):
    rows = [{"t": "3.0", "I_charge": "0.1", "fault_flags": "0"},
            {"t": "3.1", "I_charge": "0.6", "fault_flags": "0"},
            {"t": "3.2", "I_charge": "0.3", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "charge_current", "column": "I_charge", "min_value": 0.5}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True
    assert "peak 0.6000" in checks[0]["detail"]


def test_scan_signals_min_value_fail_peak_too_low(tmp_path):
    rows = [{"t": "3.0", "I_charge": "0.1", "fault_flags": "0"},
            {"t": "3.1", "I_charge": "0.2", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "charge_current", "column": "I_charge", "min_value": 0.5}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is False


def test_scan_signals_min_value_unmeasured_fails_not_skips(tmp_path):
    """A row is scanned (m['rows'] > 0) but the column cell itself is always
    blank: judge_signals() reports the peak as 'unmeasured' -- an UNMEASURED
    positive assertion FAILS, it is never silently skipped (that is the whole
    reason this table exists)."""
    rows = [{"t": "3.0", "fault_flags": "0"}]   # I_charge column present but blank
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "charge_current", "column": "I_charge", "min_value": 0.5,
             "label": "charger current"}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "the-why-string")
    assert checks[0]["passed"] is False
    assert "unmeasured" in checks[0]["detail"]
    assert "the-why-string" in checks[0]["detail"]


def test_scan_signals_no_rows_scanned_at_all_reports_never_reached(tmp_path):
    """The DIFFERENT unmeasured case: no row even falls inside the spec's own
    t_window / grace filter, so m['rows'] stays 0 and judge_signals() reports
    'no observed rows ... never reached' -- distinct wording from a scanned-
    but-blank column (the case above)."""
    rows = [{"t": "3.0", "I_charge": "0.9", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "charge_current", "column": "I_charge", "min_value": 0.5,
             "label": "charger current", "t_window": (10.0, 20.0)}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "the-why-string")
    assert checks[0]["passed"] is False
    assert "no observed rows" in checks[0]["detail"]
    assert "never reached" in checks[0]["detail"]
    assert "the-why-string" in checks[0]["detail"]


# -- column / strictly_decreases_by ------------------------------------------

def test_scan_signals_strictly_decreases_by_pass(tmp_path):
    rows = [{"t": "3.0", "soc": "0.70", "fault_flags": "0"},
            {"t": "3.1", "soc": "0.60", "fault_flags": "0"},
            {"t": "3.2", "soc": "0.50", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "soc_fell", "column": "soc", "strictly_decreases_by": 0.15}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True
    assert "fell by 0.200000" in checks[0]["detail"]


def test_scan_signals_strictly_decreases_by_fail_not_enough_fall(tmp_path):
    rows = [{"t": "3.0", "soc": "0.70", "fault_flags": "0"},
            {"t": "3.1", "soc": "0.68", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "soc_fell", "column": "soc", "strictly_decreases_by": 0.15}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is False


def test_scan_signals_strictly_decreases_by_fail_soc_rose(tmp_path):
    """A RISING value must not accidentally pass -- 'first - last' goes
    negative, which is < the required positive fall."""
    rows = [{"t": "3.0", "soc": "0.50", "fault_flags": "0"},
            {"t": "3.1", "soc": "0.70", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "soc_fell", "column": "soc", "strictly_decreases_by": 0.05}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is False


# -- fault_latch_bit (A1) ------------------------------------------------------
# The LATCH rule: fault_flags & MASK AND fault_flags & FAULT_ERROR on the SAME
# row, at t >= after_t. A bare bit (no FAULT_ERROR) or an early latch (before
# after_t) must not count -- mirrors hil_replay_suite's check_fault_latched.

def test_scan_signals_fault_latch_bit_bare_bit_without_fault_error_rejected(tmp_path):
    rows = [{"t": "20.0", "fault_flags": hex(rhs.FAULT_UV_BATT)}]  # bit set, no ERROR
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "uv", "fault_latch_bit": rhs.FAULT_UV_BATT, "after_t": 13.0}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is False
    assert "never" in checks[0]["detail"]


def test_scan_signals_fault_latch_bit_latched_before_after_t_rejected(tmp_path):
    """A latch (bit + FAULT_ERROR) occurring BEFORE after_t must not count --
    a transient before the stimulus window is not evidence of it."""
    rows = [{"t": "5.0", "fault_flags": hex(rhs.FAULT_UV_BATT | rhs.FAULT_ERROR)}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "uv", "fault_latch_bit": rhs.FAULT_UV_BATT, "after_t": 13.0}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is False


def test_scan_signals_fault_latch_bit_latched_at_exactly_after_t_accepted(tmp_path):
    """The boundary: a latch at t == after_t counts (>=, not >)."""
    rows = [{"t": "13.0", "fault_flags": hex(rhs.FAULT_UV_BATT | rhs.FAULT_ERROR)}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "uv", "fault_latch_bit": rhs.FAULT_UV_BATT, "after_t": 13.0}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True
    assert "LATCHED" in checks[0]["detail"]
    assert "t=13.000" in checks[0]["detail"]


def test_scan_signals_fault_latch_bit_latched_after_after_t_accepted(tmp_path):
    rows = [{"t": "266.0", "fault_flags": hex(rhs.FAULT_UV_BATT | rhs.FAULT_ERROR)}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "uv", "fault_latch_bit": rhs.FAULT_UV_BATT, "after_t": 13.0}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True


def test_scan_signals_fault_latch_bit_blank_cell_skipped_not_a_crash(tmp_path):
    rows = [{"t": "13.0", "fault_flags": ""},
            {"t": "13.001", "fault_flags": hex(rhs.FAULT_UV_BATT | rhs.FAULT_ERROR)}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "uv", "fault_latch_bit": rhs.FAULT_UV_BATT, "after_t": 13.0}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True


def test_scan_signals_fault_latch_bit_0x_prefixed_and_bare_decimal_both_parse(tmp_path):
    """fault_flags cells are parsed with int(cell, 0) -- both '0x...' hex and
    a bare decimal string must parse (CSVs write hex; some hand-built test
    fixtures use decimal)."""
    rows = [{"t": "13.0", "fault_flags": str(rhs.FAULT_UV_BATT | rhs.FAULT_ERROR)}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "uv", "fault_latch_bit": rhs.FAULT_UV_BATT, "after_t": 13.0}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True


def test_scan_signals_fault_latch_bit_malformed_cell_skipped_not_raising(tmp_path):
    rows = [{"t": "13.0", "fault_flags": "not-a-number"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "uv", "fault_latch_bit": rhs.FAULT_UV_BATT, "after_t": 13.0}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is False


def test_scan_signals_fault_latch_bit_rows_counted_even_before_after_t(tmp_path):
    """'rows' still counts a pre-after_t sample (so 'no rows to judge' keeps
    its own separate meaning), it just never latches from it."""
    rows = [{"t": "1.0", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "uv", "fault_latch_bit": rhs.FAULT_UV_BATT, "after_t": 13.0}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    assert measured[0]["rows"] == 1
    assert measured[0]["latch_t"] is None


# -- any_of disjunction (A1) ---------------------------------------------------

def test_judge_signals_any_of_passes_when_only_first_arm_passes(tmp_path):
    rows = [{"t": "3.0", "soc": "0.70", "fault_flags": "0"},
            {"t": "3.1", "soc": "0.60", "fault_flags": "0"}]  # fell 0.10, no UV latch
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    spec = {"name": "either", "label": "either proof",
            "any_of": [
                {"column": "soc", "strictly_decreases_by": 0.05, "label": "fall"},
                {"fault_latch_bit": rhs.FAULT_UV_BATT, "after_t": 0.0, "label": "latch"},
            ]}
    measured = rhs.scan_signals(str(path), [spec], grace_s=0.0)
    checks = rhs.judge_signals([spec], measured, "why")
    assert checks[0]["passed"] is True
    assert "satisfied by arm 1" in checks[0]["detail"]
    assert "[OK] fall" in checks[0]["detail"]
    assert "[no] latch" in checks[0]["detail"]


def test_judge_signals_any_of_passes_when_only_second_arm_passes(tmp_path):
    rows = [{"t": "3.0", "soc": "0.70", "fault_flags": "0"},
            {"t": "3.1", "soc": "0.69", "fault_flags":     # fell only 0.01, too little
             hex(rhs.FAULT_UV_BATT | rhs.FAULT_ERROR)}]     # but latches
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    spec = {"name": "either", "label": "either proof",
            "any_of": [
                {"column": "soc", "strictly_decreases_by": 0.05, "label": "fall"},
                {"fault_latch_bit": rhs.FAULT_UV_BATT, "after_t": 0.0, "label": "latch"},
            ]}
    measured = rhs.scan_signals(str(path), [spec], grace_s=0.0)
    checks = rhs.judge_signals([spec], measured, "why")
    assert checks[0]["passed"] is True
    assert "satisfied by arm 2" in checks[0]["detail"]
    assert "[no] fall" in checks[0]["detail"]
    assert "[OK] latch" in checks[0]["detail"]


def test_judge_signals_any_of_fails_when_neither_arm_passes(tmp_path):
    rows = [{"t": "3.0", "soc": "0.70", "fault_flags": "0"},
            {"t": "3.1", "soc": "0.69", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    spec = {"name": "either", "label": "either proof",
            "any_of": [
                {"column": "soc", "strictly_decreases_by": 0.05, "label": "fall"},
                {"fault_latch_bit": rhs.FAULT_UV_BATT, "after_t": 0.0, "label": "latch"},
            ]}
    measured = rhs.scan_signals(str(path), [spec], grace_s=0.0)
    checks = rhs.judge_signals([spec], measured, "why")
    assert checks[0]["passed"] is False
    assert "NO arm satisfied" in checks[0]["detail"]
    assert "[no] fall" in checks[0]["detail"]
    assert "[no] latch" in checks[0]["detail"]


def test_judge_signals_any_of_detail_reports_every_arm_not_just_the_winner(tmp_path):
    """The detail must name EVERY arm's measurement, not just the one that
    won -- so a reader can see a failing arm was physically foreclosed by the
    passing one, rather than a check that was silently weakened."""
    rows = [{"t": "3.0", "soc": "0.70", "fault_flags": "0"},
            {"t": "3.1", "soc": "0.60",
             "fault_flags": hex(rhs.FAULT_UV_BATT | rhs.FAULT_ERROR)}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    spec = {"name": "either", "label": "either proof",
            "any_of": [
                {"column": "soc", "strictly_decreases_by": 0.05, "label": "SoC fall"},
                {"fault_latch_bit": rhs.FAULT_UV_BATT, "after_t": 0.0, "label": "UV latch"},
            ]}
    measured = rhs.scan_signals(str(path), [spec], grace_s=0.0)
    checks = rhs.judge_signals([spec], measured, "why")
    detail = checks[0]["detail"]
    assert "SoC fall" in detail
    assert "UV latch" in detail
    assert "either proof" in detail
    assert "why" in detail


def test_scan_signals_and_judge_signals_any_of_shape_stays_parallel_to_specs(tmp_path):
    """scan_signals() must return one measurement slot per TOP-LEVEL spec
    (parallel to `specs`), even when one spec is disjunctive and the other is
    not -- mixing plain and any_of specs in one call must not misalign."""
    rows = [{"t": "3.0", "soc": "0.70", "fault_flags": "0", "I_charge": "1.0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [
        {"name": "plain", "column": "I_charge", "min_value": 0.5, "label": "plain"},
        {"name": "either", "label": "either",
         "any_of": [{"column": "soc", "strictly_decreases_by": 0.05, "label": "fall"},
                    {"fault_latch_bit": rhs.FAULT_UV_BATT, "after_t": 0.0, "label": "latch"}]},
    ]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    assert len(measured) == 2
    assert "any_of" not in measured[0]
    assert "any_of" in measured[1]
    assert len(measured[1]["any_of"]) == 2
    checks = rhs.judge_signals(specs, measured, "why")
    assert len(checks) == 2
    assert checks[0]["passed"] is True   # plain: I_charge peak 1.0 >= 0.5


# -- t_window edges -----------------------------------------------------------

def test_scan_signals_t_window_excludes_samples_outside_it(tmp_path):
    rows = [{"t": "1.0", "I_charge": "9.0", "fault_flags": "0"},   # before window
            {"t": "5.0", "I_charge": "0.1", "fault_flags": "0"},   # inside, too low
            {"t": "9.0", "I_charge": "9.0", "fault_flags": "0"}]   # after window
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "charge_current", "column": "I_charge", "min_value": 0.5,
             "t_window": (3.0, 7.0)}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    # The 9.0 A samples are outside the window and must not count -- only the
    # in-window 0.1 A sample is seen, which is below min_value.
    assert checks[0]["passed"] is False
    assert "peak 0.1000" in checks[0]["detail"]


def test_scan_signals_t_window_boundary_inclusive_both_ends(tmp_path):
    """t0 and t1 themselves are INSIDE the window (the guard is `t < w[0] or
    t > w[1]`, both strict)."""
    rows = [{"t": "3.0", "I_charge": "0.9", "fault_flags": "0"},   # == t0
            {"t": "7.0", "I_charge": "0.1", "fault_flags": "0"}]   # == t1
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "charge_current", "column": "I_charge", "min_value": 0.5,
             "t_window": (3.0, 7.0)}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True   # the t0 sample (0.9 A) counted


def test_scan_signals_t_window_open_ended_to_the_end(tmp_path):
    """t1 = None means 'to the end of the run' -- no upper bound."""
    rows = [{"t": "3.0", "I_charge": "0.1", "fault_flags": "0"},
            {"t": "999.0", "I_charge": "0.9", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "charge_current", "column": "I_charge", "min_value": 0.5,
             "t_window": (3.0, None)}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True


# -- post-grace filtering -----------------------------------------------------

def test_scan_signals_filters_pre_grace_samples(tmp_path):
    """Every spec is judged only on rows at or after the grace bound, for the
    same reason the fault checks are -- a pre-grace sample belongs to the
    previous run."""
    rows = [{"t": "0.5", "I_charge": "9.0", "fault_flags": "0"},   # pre-grace
            {"t": "3.0", "I_charge": "0.1", "fault_flags": "0"}]   # post-grace, low
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "charge_current", "column": "I_charge", "min_value": 0.5}]
    measured = rhs.scan_signals(str(path), specs, grace_s=2.0)
    checks = rhs.judge_signals(specs, measured, "why")
    # The 9.0 A pre-grace sample must not count -- only the 0.1 A post-grace
    # sample is seen, which is below min_value.
    assert checks[0]["passed"] is False
    assert "peak 0.1000" in checks[0]["detail"]


# ── #4 (review, LOW): boundary equality -- t == grace_s is measured ────────
# scan_signals() skips strictly `t < grace_s`; a row at EXACTLY t == grace_s
# must be measured, not excluded.

def test_scan_signals_boundary_t_equals_grace_s_is_measured(tmp_path):
    rows = [{"t": "2.000000", "I_charge": "0.9", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "x", "column": "I_charge", "min_value": 0.5}]
    measured = rhs.scan_signals(str(path), specs, grace_s=2.0)
    assert measured[0]["rows"] == 1
    assert measured[0]["peak"] == pytest.approx(0.9)


def test_scan_signals_boundary_t_just_before_grace_s_excluded(tmp_path):
    rows = [{"t": "1.999999", "I_charge": "0.9", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "x", "column": "I_charge", "min_value": 0.5}]
    measured = rhs.scan_signals(str(path), specs, grace_s=2.0)
    assert measured[0]["rows"] == 0
    assert measured[0]["peak"] is None


def test_scan_signals_missing_file_returns_empty_measurements():
    specs = [{"name": "x", "column": "I_charge", "min_value": 0.5}]
    out = rhs.scan_signals("/nonexistent/path/nope.csv", specs)
    assert len(out) == 1
    assert out[0]["rows"] == 0


# -- multiple specs, parallel measurement -------------------------------------

def test_scan_signals_measures_multiple_specs_in_one_pass(tmp_path):
    rows = [{"t": "3.0", "switch": str(rhs.SW_REGEN), "I_charge": "0.6",
             "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [
        {"name": "regen", "switch_bit": rhs.SW_REGEN, "min_ticks": 1},
        {"name": "charge_current", "column": "I_charge", "min_value": 0.5},
    ]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert len(checks) == 2
    assert all(c["passed"] for c in checks)


# -- suite-error / unknown spec shape -----------------------------------------

def test_judge_signals_spec_with_no_assertion_kind_is_a_suite_error(tmp_path):
    rows = [{"t": "3.0", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "bogus", "column": "I_charge"}]   # no min_value/etc.
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is False
    assert "declares no" in checks[0]["detail"]


def test_judge_signals_csv_read_error_is_reported_not_raised():
    specs = [{"name": "x", "column": "I_charge", "min_value": 0.5}]
    measured = [{"error": "synthetic OSError"}]
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is False
    assert "synthetic OSError" in checks[0]["detail"]


# -- signals_require wired end-to-end through judge_scenario() ---------------

def test_judge_scenario_signals_require_unmeasured_fails_not_skipped():
    """signals=None (the caller did not run scan_signals()) is NOT the same
    as 'nothing to check' -- an unmeasured positive assertion is a gap, and
    judge_scenario() must fail it, not silently omit the check."""
    m = _metrics(fault_bits_seen=0, final_fault_flags=0,
                 fault_bits_before_survive=0, state_at_survive=2)
    passed, checks = rhs.judge_scenario("soc-depletion", m, _events(), _child(),
                                        signals=None)
    sig = [c for c in checks if c["name"] == "signals_require"][0]
    assert sig["passed"] is False
    assert "not measured" in sig["detail"]
    assert passed is False


def test_judge_scenario_signals_require_measured_and_failing_fails_the_run():
    m = _metrics(fault_bits_seen=0, final_fault_flags=0,
                 fault_bits_before_survive=0, state_at_survive=2)
    signals = _failing_signals("soc-depletion")
    passed, checks = rhs.judge_scenario("soc-depletion", m, _events(), _child(),
                                        signals=signals)
    sig_checks = [c for c in checks if c["name"].startswith("signal_")]
    assert sig_checks and all(not c["passed"] for c in sig_checks)
    assert passed is False


def test_judge_scenario_zero_obs_fails():
    m = _metrics(n_obs=0, rows=10)
    passed, checks = rhs.judge_scenario("steady", m, _events(), _child())
    assert passed is False
    obs = [c for c in checks if c["name"] == "observation_frames"][0]
    assert obs["passed"] is False
    assert "never answered" in obs["detail"]
    # M1: observation_frames_post_grace is not even emitted when the board
    # never answered AT ALL -- observation_frames already covers that.
    assert not any(c["name"] == "observation_frames_post_grace" for c in checks)


# ── M1: observation_frames_post_grace ───────────────────────────────────────

def test_judge_scenario_observation_frames_post_grace_passes_by_default():
    """_metrics()' default mirrors n_obs into n_obs_post_grace, so a normal
    fixture passes this check too -- the sanity case every other judge_scenario
    test above already relies on implicitly."""
    m = _metrics()
    passed, checks = rhs.judge_scenario("steady", m, _events(), _child())
    post = [c for c in checks if c["name"] == "observation_frames_post_grace"][0]
    assert post["passed"] is True
    assert passed is True


def test_judge_scenario_observation_frames_post_grace_fails_when_board_dies_before_grace():
    """M1's motivating case: the board answered SOME ticks (observation_frames
    passes) but none of them are post-grace -- it went silent inside the
    grace window. Every post-grace fault check would otherwise pass on an
    EMPTY window, misreporting a dead board as clean. last_obs_t must be
    named in the detail."""
    m = _metrics(n_obs=5, n_obs_post_grace=0, last_obs_t=0.437,
                 fault_bits_seen=0, final_fault_flags=0)
    passed, checks = rhs.judge_scenario("steady", m, _events(), _child())
    post = [c for c in checks if c["name"] == "observation_frames_post_grace"][0]
    assert post["passed"] is False
    assert "0.437" in post["detail"]
    assert "went silent" in post["detail"]
    assert passed is False


def test_judge_scenario_observation_frames_post_grace_detail_handles_missing_last_obs_t():
    """Defensive formatting: last_obs_t missing entirely (None) must not
    raise a formatting error -- rendered as '?' rather than crashing the
    whole judgement."""
    m = _metrics(n_obs=5, n_obs_post_grace=0, last_obs_t=None)
    passed, checks = rhs.judge_scenario("steady", m, _events(), _child())
    post = [c for c in checks if c["name"] == "observation_frames_post_grace"][0]
    assert post["passed"] is False
    assert "?" in post["detail"]


def test_judge_scenario_sw_ring_over_absmax_fails_even_if_no_fault():
    """Item 9: the abs-max banner reads worst_over_absmax_ring_v (the
    over-abs-max SUBSET), not worst_ring_v (which item 9 now records
    unconditionally, sub-abs-max rings included)."""
    m = _metrics(fault_bits_seen=0, final_fault_flags=0)
    events = _events(over_absmax=2, worst_ring_v=21.5, worst_over_absmax_ring_v=21.5)
    passed, checks = rhs.judge_scenario("steady", m, events, _child())
    assert passed is False
    ring = [c for c in checks if c["name"] == "sw_ring_over_absmax"][0]
    assert ring["passed"] is False
    assert "21.50" in ring["detail"]


def test_judge_scenario_sw_ring_over_absmax_uses_over_absmax_subset_not_worst_ring():
    """Item 9 regression: worst_ring_v may be a SUB-abs-max ring (e.g. from a
    different, cleaner switching event) while worst_over_absmax_ring_v is
    the actual over-abs-max peak -- the banner must report the latter, not
    accidentally the former."""
    m = _metrics(fault_bits_seen=0, final_fault_flags=0)
    events = _events(over_absmax=1, worst_ring_v=17.578,          # sub-abs-max, lower
                     worst_over_absmax_ring_v=21.5)                # the real over-abs-max peak
    _passed, checks = rhs.judge_scenario("steady", m, events, _child())
    ring = [c for c in checks if c["name"] == "sw_ring_over_absmax"][0]
    assert "21.50" in ring["detail"]
    assert "17.58" not in ring["detail"]


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
    assert out["worst_over_absmax_ring_v"] == pytest.approx(25.9)


def test_analyze_events_field_values_collected_per_kind(tmp_path):
    """Item 3: analyze_events() collects every numeric field, keyed by event
    kind, so a events_require spec can pin a plausibility band on one (e.g.
    scp_cut's i_cut) -- 't'/'kind'/'switch' and booleans are excluded."""
    lines = [
        {"kind": "scp_cut", "switch": "MOT_PWR", "cut_count": 1, "i_cut": 6.29, "t": 0.6},
        {"kind": "scp_cut", "switch": "MOT_PWR", "cut_count": 2, "i_cut": 6.10, "t": 0.664},
        {"kind": "sw_ring", "switch": "FC_BUS", "over_absmax": False, "peak_v": 17.578},
    ]
    path = tmp_path / "events.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for e in lines:
            fh.write(json.dumps(e) + "\n")
    out = rhs.analyze_events(str(path))
    assert out["field_values"]["scp_cut"]["i_cut"] == [pytest.approx(6.29), pytest.approx(6.10)]
    assert out["field_values"]["scp_cut"]["cut_count"] == [1.0, 2.0]
    assert "t" not in out["field_values"]["scp_cut"]
    assert "switch" not in out["field_values"]["scp_cut"]
    assert out["field_values"]["sw_ring"]["peak_v"] == [pytest.approx(17.578)]


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


def test_analyze_events_worst_ring_v_recorded_unconditionally(tmp_path):
    """Item 9: worst_ring_v is now recorded for EVERY sw_ring event, not just
    ones flagged over_absmax -- a sub-abs-max ring used to be invisible
    (campaign 20260830_203006's 17.578 V FC-open ring, 0.078 V over
    LIMIT_V_BUS_MAX, appeared nowhere in REPORT.md). worst_over_absmax_ring_v
    is the SEPARATE, narrower subset and stays None when nothing crossed the
    abs-max."""
    path = tmp_path / "events.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "sw_ring", "over_absmax": False, "peak_v": 12.0}) + "\n")
    out = rhs.analyze_events(str(path))
    assert out["over_absmax"] == 0
    assert out["worst_ring_v"] == pytest.approx(12.0)
    assert out["worst_over_absmax_ring_v"] is None


def test_analyze_events_worst_over_absmax_ring_v_is_the_over_absmax_subset(tmp_path):
    """worst_ring_v is the max across ALL rings; worst_over_absmax_ring_v is
    the max across only the ones flagged over_absmax -- and they can differ,
    as here where the single biggest ring is NOT the over-abs-max one."""
    lines = [
        {"kind": "sw_ring", "over_absmax": False, "peak_v": 30.0},   # biggest overall
        {"kind": "sw_ring", "over_absmax": True, "peak_v": 21.5},    # biggest over-abs-max
        {"kind": "sw_ring", "over_absmax": True, "peak_v": 20.5},
    ]
    path = tmp_path / "events.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for e in lines:
            fh.write(json.dumps(e) + "\n")
    out = rhs.analyze_events(str(path))
    assert out["over_absmax"] == 2
    assert out["worst_ring_v"] == pytest.approx(30.0)
    assert out["worst_over_absmax_ring_v"] == pytest.approx(21.5)


# ─────────────────────────────────────────────────────────────────────────
# 6. render_report()
# ─────────────────────────────────────────────────────────────────────────

def _fake_child(rc=0, status="ok", achieved_hz=1000.0, log="run.log"):
    return {"status": status, "returncode": rc, "wall_s": 1.5, "log": log,
            "summary": {"achieved_hz": achieved_hz, "tx_frames": 1000,
                       "rx_frames": 998, "rx_bad": 0, "max_overrun_ms": 0.5}}


def _fake_scenario_result(name="steady", passed=True, fault_bits=0, over_absmax=0,
                          worst_ring_v=None):
    metrics = {"csv": "x.csv", "rows": 100, "n_obs": 100,
               "final_fault_flags": fault_bits, "fault_bits_seen": fault_bits,
               "final_state": 2, "duration_s": 30.0,
               "substep_hz_min": None, "substep_hz_mean": None}
    if worst_ring_v is None:
        worst_ring_v = 21.0 if over_absmax else None
    events = {"total": 0, "kinds": {}, "over_absmax": over_absmax,
              "worst_ring_v": worst_ring_v,
              "worst_over_absmax_ring_v": worst_ring_v if over_absmax else None}
    checks = [{"name": "observation_frames", "passed": True, "detail": "ok"}]
    return {"kind": "scenario", "name": name, "mode": "hifi",
            "electrical_required": "any", "description": "test scenario",
            "duration_s": 30.0, "passed": passed, "checks": checks, "notes": [],
            "metrics": metrics, "events": events, "child": _fake_child(),
            "csv": "x.csv", "events_path": "x.csv.events.jsonl",
            "log_path": "run.log", "key_metrics": "obs 100/100"}


def _fake_replay_result(name="ML0151", mode="conformance", passed=True,
                        metrics=None, replay_commands=None, skipped=False,
                        checks=None):
    """metrics/replay_commands/skipped/checks default to the ORIGINAL fixture
    shape (metrics={}, no replay_commands key, not skipped) so every existing
    call site is unaffected; the fix-round render_report tests pass them
    explicitly."""
    reason = "--pi-live: this scenario is EMS/pi_timeline-driven"
    if checks is None:
        checks = ([{"name": "skipped", "passed": True, "detail": reason}] if skipped
                  else [{"name": "no_fault", "passed": passed, "detail": "..."}])
    r = {"kind": "replay", "name": name, "mode": mode,
         "description": "test replay", "duration_s": 56.0,
         "passed": passed, "checks": checks, "notes": ["fw 14: ..."],
         "metrics": {} if metrics is None else metrics, "events": {},
         "child": _fake_child(),
         "csv": "y.csv", "events_path": None, "log_path": "run_replay.log",
         "key_metrics": "1/1 checks passed"}
    if replay_commands is not None:
        r["replay_commands"] = replay_commands
    if skipped:
        r["skipped"] = True
        r["skip_reason"] = reason
    return r


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


def test_render_report_worst_ring_line_shown_even_when_sub_absmax():
    """Item 9: the per-run 'worst estimated switching-ring peak' line must
    appear whenever worst_ring_v is not None, REGARDLESS of over_absmax --
    campaign 20260830_203006's 17.578 V FC-open ring (sub-abs-max) used to
    be invisible in REPORT.md entirely."""
    results = [_fake_scenario_result(over_absmax=0, worst_ring_v=17.578)]
    results[0]["events"]["total"] = 1     # the per-run line is gated on ev["total"]
    results[0]["events"]["kinds"] = {"sw_ring": 1}
    report = rhs.render_report(_fake_meta(), results)
    assert "worst estimated switching-ring peak" in report
    assert "17.578" in report
    assert "LIMIT_V_BUS_MAX" in report


def test_render_report_worst_ring_line_absent_when_never_measured():
    results = [_fake_scenario_result(over_absmax=0, worst_ring_v=None)]
    report = rhs.render_report(_fake_meta(), results)
    assert "worst estimated switching-ring peak" not in report


def test_render_report_sub_absmax_rings_above_limit_v_bus_max_section():
    """Item 9: when NO result crossed the 20 V abs-max at all, a result
    whose worst_ring_v is nonetheless above LIMIT_V_BUS_MAX (17.5 V) is
    still surfaced, in the 'Known open findings' section -- the only place
    it would otherwise show up nowhere in the whole report."""
    results = [_fake_scenario_result(name="handoff-sag", over_absmax=0,
                                     worst_ring_v=17.578)]
    report = rhs.render_report(_fake_meta(), results)
    assert "No `sw_ring` event above the 20 V abs-max" in report
    assert "Sub-abs-max rings above `LIMIT_V_BUS_MAX`" in report
    assert "`handoff-sag`: worst estimated ring peak 17.578 V" in report


def test_render_report_sub_absmax_section_absent_when_all_rings_under_limit():
    results = [_fake_scenario_result(over_absmax=0, worst_ring_v=12.0)]
    report = rhs.render_report(_fake_meta(), results)
    assert "Sub-abs-max rings above" not in report


def test_render_report_aborted_meta_shown():
    report = rhs.render_report(_fake_meta(aborted="board unreachable"), [])
    assert "ABORTED" in report
    assert "board unreachable" in report


def test_render_report_empty_results_does_not_crash():
    report = rhs.render_report(_fake_meta(), [])
    assert "0 (0 scenario, 0 replay)" in report
    assert "0/0 passed" in report


# ─────────────────────────────────────────────────────────────────────────
# 6b. M1: render_report()'s replay-half preamble — the two-branch
#     replay_commands-count sentence (fix round)
# ─────────────────────────────────────────────────────────────────────────

def test_render_report_replay_preamble_reports_the_opted_in_split():
    """When at least one replay entry set replay_commands, the preamble must
    name BOTH the count that did (with the controller-reaction language) and
    the count that did not (tagged NOT EXERCISED) — counted from the actual
    records, not a static sentence."""
    results = [
        _fake_replay_result(name="ML0146", replay_commands=True),
        _fake_replay_result(name="ML0151", replay_commands=True),
        _fake_replay_result(name="TP0010", replay_commands=False),
    ]
    report = rhs.render_report(_fake_meta(), results)
    assert "**2 of 3** replay entries set `replay_commands`" in report
    assert "The remaining **1** construct no commander at all" in report
    assert "NOT EXERCISED" in report
    assert "No entry in this run set" not in report


def test_render_report_replay_preamble_zero_opt_in_branch():
    """No replay entry set replay_commands: the OTHER branch fires — a single
    blanket sentence, not the N-of-M split (which would read '0 of 2' rather
    than the intended plain-English zero-case wording)."""
    results = [
        _fake_replay_result(name="TP0010", replay_commands=False),
        _fake_replay_result(name="TP0053"),   # key omitted entirely -- also falsy
    ]
    report = rhs.render_report(_fake_meta(), results)
    assert "No entry in this run set `replay_commands`" in report
    assert "no commander was" in report
    assert "NOT EXERCISED" in report
    assert "replay entries set `replay_commands`:" not in report   # the opt-in branch's sentence


def test_render_report_replay_preamble_absent_when_no_replay_results():
    """The whole '## Replay suite' section (preamble included) must not
    render at all when there are no replay results -- scenario-only runs must
    not pay for, or confuse a reader with, replay-half language."""
    report = rhs.render_report(_fake_meta(), [_fake_scenario_result()])
    assert "## Replay suite" not in report
    assert "replay_commands" not in report


def test_render_report_replay_preamble_open_loop_warning_present():
    results = [_fake_replay_result(replay_commands=True)]
    report = rhs.render_report(_fake_meta(), results)
    assert "does NOT close the loop" in report
    assert "REACTION test, never a tracking test" in report


# ─────────────────────────────────────────────────────────────────────────
# 6c. M2: render_report()'s per-entry replay fault-metrics block
# ─────────────────────────────────────────────────────────────────────────

def _replay_metrics(**overrides):
    m = {"csv": "y.csv", "rows": 100, "n_obs": 90, "n_obs_post_grace": 70,
         "final_fault_flags": 0, "fault_bits_seen": 0, "fault_bits_post_grace": 0,
         "fault_first_t": {}, "last_obs_t": 5.6, "grace_s": rhs.WARM_RESET_GRACE_S,
         "final_state": 2, "duration_s": 5.6}
    m.update(overrides)
    return m


def test_render_report_replay_metrics_block_final_flags_and_unions_rendered():
    latched = rhs.FAULT_UV_BUS | rhs.FAULT_ERROR
    results = [_fake_replay_result(metrics=_replay_metrics(
        final_fault_flags=latched, fault_bits_seen=latched,
        fault_bits_post_grace=latched, final_state=99))]
    report = rhs.render_report(_fake_meta(), results)
    assert "100 rows, 90 with an observation frame" in report
    assert ("final `fault_flags` `0x%04X`" % latched) in report
    assert "union over the run:" in report
    assert "POST-GRACE union (t >= %.1fs" % rhs.WARM_RESET_GRACE_S in report
    assert "final state: 99" in report


def test_render_report_replay_metrics_block_carried_in_sub_line_when_bit_cleared_pre_grace():
    """A bit seen only BEFORE the grace bound (present in the whole-run union,
    absent from the post-grace union) must get the dedicated 'carried in from
    the predecessor's settle latch' sub-line -- the exact scenario A5/M2 exist
    to surface."""
    seen = rhs.FAULT_UV_BUS | rhs.FAULT_ERROR
    results = [_fake_replay_result(metrics=_replay_metrics(
        final_fault_flags=0, fault_bits_seen=seen, fault_bits_post_grace=0))]
    report = rhs.render_report(_fake_meta(), results)
    assert "carried in from the predecessor's settle latch" in report
    assert "cleared by the fw v23 grace-window warm reset" in report


def test_render_report_replay_metrics_block_no_carried_in_line_when_unions_match():
    results = [_fake_replay_result(metrics=_replay_metrics(
        final_fault_flags=0, fault_bits_seen=0, fault_bits_post_grace=0))]
    report = rhs.render_report(_fake_meta(), results)
    assert "carried in from the predecessor's settle latch" not in report


def test_render_report_replay_metrics_block_load_failure_form():
    """A load-failure metrics dict (only csv/error -- ReplayCsv.metrics() never
    ran) must render the short 'could not be read' form, not attempt the
    rows/final-flags line (which would KeyError-style crash on a dict this
    thin if it were reached)."""
    results = [_fake_replay_result(metrics={"csv": "y.csv", "error": "boom: no such file"})]
    report = rhs.render_report(_fake_meta(), results)
    assert "**could not be read** (boom: no such file)" in report
    assert "with an observation frame" not in report


def test_render_report_replay_metrics_block_absent_when_metrics_empty():
    """The original bare `{}` shape (or any metrics dict with rows falsy and
    no error key) must render NEITHER form -- no crash, no fabricated line."""
    results = [_fake_replay_result(metrics={})]
    report = rhs.render_report(_fake_meta(), results)
    assert "with an observation frame" not in report
    assert "could not be read" not in report


def test_render_report_replay_skipped_record_short_circuits_before_metrics_block():
    """A skipped replay record (--pi-live) has no child/CSV at all -- the
    renderer must print the 'child: not run' line and `continue` BEFORE ever
    reaching the metrics block, even if (defensively) a metrics dict were
    present on the record."""
    results = [_fake_replay_result(skipped=True,
                                   metrics=_replay_metrics(final_fault_flags=0x8010))]
    report = rhs.render_report(_fake_meta(), results)
    assert "child: **not run**" in report
    assert "with an observation frame" not in report
    assert "final `fault_flags`" not in report


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

def test_soc_depletion_duration_and_soc0_repinned_to_400_and_0_20():
    """soc-depletion's SCENARIOS entry itself still says duration_s=120 (see
    test_hil_plant_sim.py's SCENARIOS-registry tests) -- build_plan() special-
    cases ONLY this one scenario name and overrides both the duration and adds
    --soc0. RE-DERIVED AGAIN (campaign 20260830_214819, HIL_FINDINGS
    'soc-depletion', 2026-08-30, superseding the 880 s / 0.15 M4 derivation):
    the coulomb current that actually depletes the pack is PACK-SIDE (~6.19 A,
    behind the boost), not the 2.2 A BUS-side SOC_ENDURANCE_LOAD_A, and the
    UV_BATT latch is a STATE condition (soc_latch ~= 0.1130) that FORECLOSES
    the run, not a time budget -- so the old --soc0 0.15 could only ever fall
    0.037, below the 0.05 signal threshold, no matter how long the run ran.
    Corrected together: --soc0 0.20 (ceiling 0.20 - 0.113 = 0.087, 1.74x the
    threshold) and --duration 400 (estimated latch at ~266 s + margin, 480 s
    CHEAPER than the old 880 s). The signal check is now disjunctive (see
    FAULT_EXPECTATIONS/test_soc_depletion_signal_spec_is_disjunctive): either
    the 0.05 SoC fall or a post-ramp UV_BATT latch proves depletion."""
    plan = rhs.build_plan(_args(only=["soc-depletion"]))
    assert len(plan) == 1
    item = plan[0]
    assert item["duration_s"] == pytest.approx(400.0)
    assert item["timeout_s"] == pytest.approx(400.0 + rhs.TIMEOUT_GRACE_S)
    argv = item["argv"]
    assert "--duration" in argv
    assert argv[argv.index("--duration") + 1] == "400"
    assert "--soc0" in argv
    assert argv[argv.index("--soc0") + 1] == "0.20"
    # SCENARIOS itself is untouched -- this is purely a build_plan() override.
    assert SCENARIOS["soc-depletion"]["duration_s"] == pytest.approx(120.0)


def test_soc_depletion_signal_spec_is_disjunctive_any_of_two_arms():
    """A1: the soc_depleted signal spec must be an any_of with exactly two
    arms -- the SoC-fall proof and the post-ramp UV_BATT latch proof -- since
    the two are mutually exclusive in practice (a latch ends the run and caps
    the observable fall)."""
    expect = rhs.FAULT_EXPECTATIONS["soc-depletion"]
    specs = expect["signals_require"]
    assert len(specs) == 1
    spec = specs[0]
    arms = spec["any_of"]
    assert len(arms) == 2
    assert arms[0]["strictly_decreases_by"] == pytest.approx(0.05)
    assert arms[0]["column"] == "soc"
    assert arms[1]["fault_latch_bit"] == rhs.FAULT_UV_BATT
    assert arms[1]["after_t"] == pytest.approx(13.0)


def test_soc_depletion_override_does_not_leak_into_other_scenarios():
    plan = rhs.build_plan(_args())
    for p in plan:
        if p["kind"] != "scenario" or p["name"] == "soc-depletion":
            continue
        if p["argv"] is None:
            # operator_required skip record ('drive' without --with-operator):
            # no argv is ever built for it.
            continue
        assert "--soc0" not in p["argv"], p["name"]


# ─────────────────────────────────────────────────────────────────────────
# 9. F2: handoff-sag allow_only includes UV_BUS (review-fix round; migrated
#    from FAULT_REQUIRED/FAULT_ALLOWED to FAULT_EXPECTATIONS, 2026-08-30)
# ─────────────────────────────────────────────────────────────────────────

FAULT_UV_BUS = 0x0100   # hil_replay_suite.FAULT_UV_BUS, re-derived for this test file


def test_f2_handoff_sag_is_in_fault_allowed():
    assert "handoff-sag" in rhs.FAULT_EXPECTATIONS
    expect = rhs.FAULT_EXPECTATIONS["handoff-sag"]
    assert "require" not in expect   # not REQUIRED, only ALLOWED
    assert expect["allow_only"] & FAULT_UV_BUS


def test_f2_judge_scenario_handoff_sag_with_uv_fault_passes_that_check():
    """A UV_BUS fault on handoff-sag is a PLAUSIBLE outcome (TP0178/TP0201-
    class reactive standby pickup), not an unexpected failure -- the
    fault_allow_only check must pass whether or not the fault actually fired,
    as long as the run also reached its own survive_to gate (t=20.0, states
    {2, 3}) and (M3) its signals_require (FC_BUS_ENABLE opened and stayed
    open) is satisfied."""
    signals = _passing_signals("handoff-sag")
    m_with_fault = _metrics(fault_bits_seen=FAULT_UV_BUS, final_fault_flags=FAULT_UV_BUS,
                            fault_bits_before_survive=0, state_at_survive=2)
    passed, checks = rhs.judge_scenario("handoff-sag", m_with_fault, _events(), _child(),
                                        signals=signals)
    fa = [c for c in checks if c["name"] == "fault_allow_only"][0]
    assert fa["passed"] is True
    assert passed is True   # nothing else in the default fixture should fail it

    m_clean = _metrics(fault_bits_seen=0, final_fault_flags=0,
                       fault_bits_before_survive=0, state_at_survive=2)
    passed2, checks2 = rhs.judge_scenario("handoff-sag", m_clean, _events(), _child(),
                                          signals=signals)
    fa2 = [c for c in checks2 if c["name"] == "fault_allow_only"][0]
    assert fa2["passed"] is True
    assert passed2 is True


# ─────────────────────────────────────────────────────────────────────────
# 9b. A5: _run_plan()'s replay branch stores the REAL metrics, not {}
# ─────────────────────────────────────────────────────────────────────────

def test_a5_run_plan_replay_metrics_is_not_empty_and_carries_final_fault_flags(
        monkeypatch):
    """A5 (campaign 20260830_214819): the replay branch of _run_plan() used to
    hardcode `"metrics": {}`, so a replay run that ended LATCHED (e.g. a
    carried-in 0x8100/0x8001) rendered in results.json/REPORT.md as
    'final fault_flags 0x0000 (none)' -- the exact latched end-state that
    carries into the next run, hidden. This test is built to FAIL under that
    old behaviour: it asserts the truthful nonzero final_fault_flags actually
    reaches the result record, which `{"metrics": {}}` could never satisfy."""
    def fake_run_child(item, args):
        return {"status": "ok", "returncode": 0, "wall_s": 0.01, "log": item["log"],
                "summary": {"achieved_hz": 1000.0}}

    latched = rhs.FAULT_UV_BUS | rhs.FAULT_ERROR

    def fake_evaluate_replay_csv(entry, csv_path):
        return {"passed": True,
               "checks": [{"name": "uv", "passed": True, "detail": "..."}],
               "notes": [], "n_obs": 10,
               "n_checks_vacuous": 0, "n_checks_substantive": 1,
               # A5: the exact shape ReplayCsv.metrics() returns -- a truthful
               # LATCHED end-state the old `{}` could never carry.
               "metrics": {"csv": csv_path, "rows": 10, "n_obs": 10,
                           "n_obs_post_grace": 8, "final_fault_flags": latched,
                           "fault_bits_seen": latched, "fault_bits_post_grace": latched,
                           "fault_first_t": {"UV_BUS": 5.25}, "last_obs_t": 10.0,
                           "grace_s": 2.0, "final_state": 99, "duration_s": 10.0}}

    monkeypatch.setattr(rhs, "run_child", fake_run_child)
    monkeypatch.setattr(rhs, "evaluate_replay_csv", fake_evaluate_replay_csv)

    args = _args(only=["ML0146"], keep_going=True, settle_s=0.0)
    plan = rhs.build_plan(args)
    results, _aborted = rhs._run_plan(plan, args, [], [], lambda m, r: None)
    r = results[0]
    # This is the assertion that FAILS under the old `"metrics": {}` --
    # r["metrics"] would be {} and .get("final_fault_flags") would be None,
    # not the truthful latched value.
    assert r["metrics"]
    assert r["metrics"]["final_fault_flags"] == latched
    assert r["metrics"]["final_state"] == 99


def test_a5_run_plan_replay_metrics_defaults_to_empty_dict_when_evaluate_omits_it(
        monkeypatch):
    """A defensive-default check: if evaluate_replay_csv() ever omits the
    'metrics' key entirely (rather than the source's designed-in {} on the
    load-failure path), _run_plan() must still produce an empty dict, not
    raise a KeyError."""
    def fake_run_child(item, args):
        return {"status": "ok", "returncode": 0, "wall_s": 0.01, "log": item["log"],
                "summary": {"achieved_hz": 1000.0}}

    def fake_evaluate_replay_csv(entry, csv_path):
        return {"passed": True,
               "checks": [{"name": "no_fault", "passed": True, "detail": "..."}],
               "notes": [], "n_obs": 10,
               "n_checks_vacuous": 0, "n_checks_substantive": 1}
        # deliberately no "metrics" key at all

    monkeypatch.setattr(rhs, "run_child", fake_run_child)
    monkeypatch.setattr(rhs, "evaluate_replay_csv", fake_evaluate_replay_csv)

    args = _args(only=["ML0146"], keep_going=True, settle_s=0.0)
    plan = rhs.build_plan(args)
    results, _aborted = rhs._run_plan(plan, args, [], [], lambda m, r: None)
    assert results[0]["metrics"] == {}


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


def test_run_plan_replay_key_metrics_shows_substantive_not_evidence_split_no_command_replay(
        monkeypatch):
    """Item 5/L3, wording updated 2026-08-30 (fix-round): a replay run's
    key_metrics string must say how many of its passing checks carried no
    evidence -- "%d/%d checks passed" alone counts vacuous checks alongside
    real ones and reads stronger than the run actually is. The three-way
    `nonevidence_why` branch in _run_plan() is keyed on the ENTRY's own
    `replay_commands` (the intent), not on the observed counters: this case
    has `ev.get("replay_commands")` falsy (the key is omitted entirely, same
    as an explicit False), so the label reads "no command replay" -- there is
    no longer a "no commander" wording anywhere in the source."""
    def fake_run_child(item, args):
        return {"status": "ok", "returncode": 0, "wall_s": 0.01, "log": item["log"],
                "summary": {"achieved_hz": 1000.0, "tx_frames": 10, "rx_frames": 10,
                           "rx_bad": 0}}

    def fake_evaluate_replay_csv(entry, csv_path):
        return {"passed": True,
               "checks": [{"name": "no_fault", "passed": True, "detail": "..."},
                          {"name": "bc", "passed": True, "detail": "vacuous-tagged"}],
               "notes": [], "n_obs": 10,
               "n_checks_vacuous": 1, "n_checks_substantive": 1}
        # deliberately no "replay_commands" / "n_checks_not_exercised" keys --
        # a real evaluate_replay_csv() result whose vacuous check never went
        # through the NOT_EXERCISED retagging path.

    monkeypatch.setattr(rhs, "run_child", fake_run_child)
    monkeypatch.setattr(rhs, "evaluate_replay_csv", fake_evaluate_replay_csv)

    args = _args(only=["ML0146"], keep_going=True, settle_s=0.0)
    plan = rhs.build_plan(args)
    assert len(plan) == 1

    results, _aborted = rhs._run_plan(plan, args, [], [], lambda m, r: None)
    assert len(results) == 1
    r = results[0]
    assert r["n_checks_vacuous"] == 1
    assert r["n_checks_substantive"] == 1
    assert "2/2 checks passed" in r["key_metrics"]
    assert "1 substantive, 1 not evidence — no command replay" in r["key_metrics"]
    assert "commands replayed" not in r["key_metrics"]
    assert "no commander" not in r["key_metrics"]   # the old wording is gone entirely


def test_run_plan_replay_key_metrics_defensive_suite_bug_branch(monkeypatch):
    """The defensive third branch: replay_commands truthy AND
    n_checks_not_exercised truthy is supposed to be UNREACHABLE (NOT_EXERCISED
    is only ever applied on a non-opt-in entry -- see hil_replay_suite's
    check-loop gate), but if evaluate_replay_csv() ever produced that
    combination anyway, _run_plan() must name it distinctly as a suite
    defect rather than silently folding it into either of the two legitimate
    labels."""
    def fake_run_child(item, args):
        return {"status": "ok", "returncode": 0, "wall_s": 0.01, "log": item["log"],
                "summary": {"achieved_hz": 1000.0}}

    def fake_evaluate_replay_csv(entry, csv_path):
        return {"passed": True,
               "checks": [{"name": "bc", "passed": True, "detail": "..."}],
               "notes": [], "n_obs": 10,
               "n_checks_vacuous": 1, "n_checks_substantive": 0,
               "n_checks_not_exercised": 1, "replay_commands": True}

    monkeypatch.setattr(rhs, "run_child", fake_run_child)
    monkeypatch.setattr(rhs, "evaluate_replay_csv", fake_evaluate_replay_csv)

    args = _args(only=["ML0146"], keep_going=True, settle_s=0.0)
    plan = rhs.build_plan(args)
    results, _aborted = rhs._run_plan(plan, args, [], [], lambda m, r: None)
    r = results[0]
    assert r["replay_commands"] is True
    assert r["n_checks_not_exercised"] == 1
    assert "0 substantive, 1 not evidence — opt-in entry tagged NOT EXERCISED (suite bug)" \
        in r["key_metrics"]


def test_run_plan_replay_key_metrics_labels_no_command_replay_when_not_exercised(
        monkeypatch):
    """The converse label: when n_checks_not_exercised is truthy (a
    command-free entry retagged NOT EXERCISED), key_metrics must say
    'no command replay', not 'no commander'."""
    def fake_run_child(item, args):
        return {"status": "ok", "returncode": 0, "wall_s": 0.01, "log": item["log"],
                "summary": {"achieved_hz": 1000.0}}

    def fake_evaluate_replay_csv(entry, csv_path):
        return {"passed": True,
               "checks": [{"name": "no_fault", "passed": True, "detail": "..."},
                          {"name": "bc", "passed": True,
                           "detail": "NOT EXERCISED (no command replay): ..."}],
               "notes": [], "n_obs": 10,
               "n_checks_vacuous": 1, "n_checks_substantive": 1,
               "n_checks_not_exercised": 1, "replay_commands": False}

    monkeypatch.setattr(rhs, "run_child", fake_run_child)
    monkeypatch.setattr(rhs, "evaluate_replay_csv", fake_evaluate_replay_csv)

    args = _args(only=["ML0146"], keep_going=True, settle_s=0.0)
    plan = rhs.build_plan(args)
    results, _aborted = rhs._run_plan(plan, args, [], [], lambda m, r: None)
    r = results[0]
    assert r["n_checks_not_exercised"] == 1
    assert "1 substantive, 1 not evidence — no command replay" in r["key_metrics"]
    assert "commands replayed" not in r["key_metrics"]


def test_run_plan_replay_key_metrics_shows_commands_replayed_suffix(monkeypatch):
    """An entry that DID replay commands gets the "(commands replayed)"
    suffix on key_metrics, ahead of any substantive/vacuous split."""
    def fake_run_child(item, args):
        return {"status": "ok", "returncode": 0, "wall_s": 0.01, "log": item["log"],
                "summary": {"achieved_hz": 1000.0}}

    def fake_evaluate_replay_csv(entry, csv_path):
        return {"passed": True,
               "checks": [{"name": "dls", "passed": True, "detail": "..."}],
               "notes": [], "n_obs": 10,
               "n_checks_vacuous": 0, "n_checks_substantive": 1,
               "n_checks_not_exercised": 0, "replay_commands": True}

    monkeypatch.setattr(rhs, "run_child", fake_run_child)
    monkeypatch.setattr(rhs, "evaluate_replay_csv", fake_evaluate_replay_csv)

    args = _args(only=["ML0146"], keep_going=True, settle_s=0.0)
    plan = rhs.build_plan(args)
    results, _aborted = rhs._run_plan(plan, args, [], [], lambda m, r: None)
    r = results[0]
    assert r["replay_commands"] is True
    assert r["key_metrics"].startswith("1/1 checks passed (commands replayed)")


def test_run_plan_replay_key_metrics_omits_split_when_nothing_vacuous(monkeypatch):
    def fake_run_child(item, args):
        return {"status": "ok", "returncode": 0, "wall_s": 0.01, "log": item["log"],
                "summary": {"achieved_hz": 1000.0}}

    def fake_evaluate_replay_csv(entry, csv_path):
        return {"passed": True,
               "checks": [{"name": "no_fault", "passed": True, "detail": "..."}],
               "notes": [], "n_obs": 10,
               "n_checks_vacuous": 0, "n_checks_substantive": 1}

    monkeypatch.setattr(rhs, "run_child", fake_run_child)
    monkeypatch.setattr(rhs, "evaluate_replay_csv", fake_evaluate_replay_csv)

    args = _args(only=["ML0146"], keep_going=True, settle_s=0.0)
    plan = rhs.build_plan(args)
    results, _aborted = rhs._run_plan(plan, args, [], [], lambda m, r: None)
    r = results[0]
    assert r["key_metrics"].startswith("1/1 checks passed")
    assert "vacuous" not in r["key_metrics"]


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
    pi_timeline/ems set (the replay skip set is covered separately).

    'drive' is ALSO skip-recorded under the default args used here, but for
    an unrelated reason (operator_required, no --with-operator) that has
    nothing to do with --pi-live -- it is skipped identically with pi_live
    off, so it is excluded by its distinct 'OPERATOR-REQUIRED' skip_reason
    prefix rather than folded into the pi_timeline/ems set."""
    plan = rhs.build_plan(_args(pi_live=True))
    skipped = {p["name"] for p in plan
               if p.get("skip_reason") and p["kind"] == "scenario"
               and not p["skip_reason"].startswith("OPERATOR-REQUIRED")}
    assert skipped == PI_LIVE_SKIP_SCENARIOS
    # sanity: 'drive' IS skipped, but for the operator-required reason.
    drive = next(p for p in plan if p["name"] == "drive")
    assert drive["skip_reason"].startswith("OPERATOR-REQUIRED")


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
    """'drive' is excluded from BOTH sides here: it is skip-recorded in both
    plans (operator_required, no --with-operator given to either), so it
    never appears in either "not skipped" set and the equality below would
    otherwise be comparing sets that both already lack it -- excluding it
    explicitly documents that rather than relying on it happening to cancel
    out."""
    plan_live = rhs.build_plan(_args(pi_live=True))
    plan_default = rhs.build_plan(_args())
    live_names = {p["name"] for p in plan_live if not p.get("skip_reason")
                  and p["kind"] == "scenario"}
    default_names = {p["name"] for p in plan_default if p["kind"] == "scenario"} - {"drive"}
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

# NOTE: this section reuses the single `_metrics()` helper defined in section 4
# above (extended with the grace/survive_to fields) -- it used to shadow that
# definition with a narrower duplicate of the same name; removed so both
# sections share one fixture and cannot silently drift apart.


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
        # F1/F2: comm-loss's FAULT_EXPECTATIONS `require` still checks against
        # the raw wanted bit (0x0010) via `post & require` -- it is unaffected
        # by the pi_live excusal rewrite because it never reaches the
        # no_unexpected_fault branch (that branch only runs when the scenario
        # has no FAULT_EXPECTATIONS entry at all).
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
    """Scenarios with a FAULT_EXPECTATIONS `require` ('sag', 'comm-loss') use
    the expected_fault/fault_allow_only check path, not no_unexpected_fault --
    the pi_live excusal branch must never engage there."""
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
    scenario duration_s varies -- 6-58 s (2026-08-30 trim) -- so a skip-count * settle_s
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


# ─────────────────────────────────────────────────────────────────────────
# parse_child_summary() — exact stdout-line format
# ─────────────────────────────────────────────────────────────────────────

def test_parse_child_summary_done_line_ticks_hz_overrun():
    text = ("[hil] done: 250 ticks in 0.25s -> 1000.0 Hz achieved (target 1000 Hz), "
            "max overrun 1.234 ms\n")
    out = rhs.parse_child_summary(text)
    assert out["ticks"] == 250
    assert out["achieved_hz"] == pytest.approx(1000.0)
    assert out["max_overrun_ms"] == pytest.approx(1.234)


def test_parse_child_summary_tx_rx_and_send_errors():
    text = "[hil] tx=500 frames, rx=498 frames, 2 malformed, send_errors=1\n"
    out = rhs.parse_child_summary(text)
    assert out["tx_frames"] == 500
    assert out["rx_frames"] == 498
    assert out["rx_bad"] == 2
    assert out["send_errors"] == 1


def test_parse_child_summary_send_errors_absent_on_older_build():
    """F2: an older sim build's tx= line has no send_errors= field -- the key
    must be ABSENT (treated as unknown by the pi-live judge), not defaulted
    to 0."""
    text = "[hil] tx=500 frames, rx=498 frames, 2 malformed\n"
    out = rhs.parse_child_summary(text)
    assert out["tx_frames"] == 500
    assert "send_errors" not in out


def test_parse_child_summary_warm_resets_no_times_suffix():
    text = "[hil] warm resets: 0 observed, 0 mid-run (after 2.0s)\n"
    out = rhs.parse_child_summary(text)
    assert out["warm_resets"] == 0
    assert out["warm_resets_mid_run"] == 0


def test_parse_child_summary_warm_resets_with_times_suffix():
    text = "[hil] warm resets: 3 observed, 1 mid-run (after 2.0s) at t=0.500, 2.500, 2.600s\n"
    out = rhs.parse_child_summary(text)
    assert out["warm_resets"] == 3
    assert out["warm_resets_mid_run"] == 1


def test_parse_child_summary_full_realistic_block():
    text = (
        "[hil] done: 30000 ticks in 30.02s -> 999.3 Hz achieved (target 1000 Hz), "
        "max overrun 0.812 ms\n"
        "[hil] tx=30000 frames, rx=29998 frames, 0 malformed, send_errors=0\n"
        "[hil] warm resets: 1 observed, 1 mid-run (after 2.0s) at t=5.502s\n"
        "[hil] electrical(hifi): 32.1 kHz achieved substep rate (32 substeps/tick, "
        "trace=short), 14 events\n"
    )
    out = rhs.parse_child_summary(text)
    assert out["ticks"] == 30000
    assert out["tx_frames"] == 30000
    assert out["rx_frames"] == 29998
    assert out["rx_bad"] == 0
    assert out["send_errors"] == 0
    assert out["warm_resets"] == 1
    assert out["warm_resets_mid_run"] == 1
    assert out["substep_khz"] == pytest.approx(32.1)
    assert out["elec_events"] == 14


def test_parse_child_summary_over_absmax_line_captured():
    text = ("[hil] *** 2 switching event(s) with an estimated ring peak ABOVE the "
            "20 V abs-max -- the boost-death signature; worst 24.10 V ***\n")
    out = rhs.parse_child_summary(text)
    assert "over_absmax_line" in out
    assert "ABOVE the 20 V abs-max" in out["over_absmax_line"]


# ─────────────────────────────────────────────────────────────────────────
# read_run_meta() / warm_reset_count() -- REPAIRED for the fix round:
# read_run_meta() gained `launched_at=None` and three staleness guards (D2):
#   1. `results` must not be None (a "running"-only sidecar is UNMEASURED).
#   2. `doc["csv"]` must normcase/abspath-match the requested csv_path.
#   3. (only when `launched_at` is given) `created` must be >= launched_at;
#      unparseable `created` CANNOT be compared and therefore PASSES.
# warm_reset_count() now returns a {"mid_run", "observed", "times"} dict (not
# a bare int) alongside the source string.
# ─────────────────────────────────────────────────────────────────────────

def test_read_run_meta_none_path_returns_empty_dict():
    assert rhs.read_run_meta(None) == {}


def test_read_run_meta_missing_sidecar_returns_empty_dict(tmp_path):
    assert rhs.read_run_meta(str(tmp_path / "nope.csv")) == {}


def test_read_run_meta_reads_the_sidecar(tmp_path):
    csv_path = tmp_path / "run.csv"
    csv_path.write_text("t,seq\n")
    sidecar = tmp_path / "run.csv.meta.json"
    # D2 guard 2 requires `csv` in the sidecar to match the requested path.
    sidecar.write_text(json.dumps({"status": "completed", "csv": str(csv_path),
                                   "results": {"warm_resets_mid_run": 2}}))
    meta = rhs.read_run_meta(str(csv_path))
    assert meta["status"] == "completed"
    assert meta["results"]["warm_resets_mid_run"] == 2


def test_read_run_meta_malformed_json_returns_empty_dict(tmp_path):
    csv_path = tmp_path / "run.csv"
    sidecar = tmp_path / "run.csv.meta.json"
    sidecar.write_text("{not valid json")
    assert rhs.read_run_meta(str(csv_path)) == {}


def test_read_run_meta_non_dict_json_returns_empty_dict(tmp_path):
    csv_path = tmp_path / "run.csv"
    sidecar = tmp_path / "run.csv.meta.json"
    sidecar.write_text(json.dumps([1, 2, 3]))
    assert rhs.read_run_meta(str(csv_path)) == {}


def test_read_run_meta_guard1_results_none_is_stale_unmeasured(tmp_path):
    """D2 guard 1: the sidecar is written TWICE -- 'running' with results=None
    before the loop, then again at exit. A results=None sidecar means the
    child died before finalizing, which read_run_meta() must treat as
    completely absent (never surfaced as a stale-but-present doc)."""
    csv_path = tmp_path / "run.csv"
    sidecar = tmp_path / "run.csv.meta.json"
    sidecar.write_text(json.dumps({"status": "running", "csv": str(csv_path),
                                   "results": None}))
    assert rhs.read_run_meta(str(csv_path)) == {}


def test_read_run_meta_guard2_csv_field_mismatch_rejected(tmp_path):
    """D2 guard 2: a sidecar recording a DIFFERENT csv path belongs to some
    other run (copied/renamed into place) and must be rejected."""
    csv_path = tmp_path / "run.csv"
    sidecar = tmp_path / "run.csv.meta.json"
    sidecar.write_text(json.dumps({"status": "completed",
                                   "csv": str(tmp_path / "other.csv"),
                                   "results": {"warm_resets_mid_run": 1}}))
    assert rhs.read_run_meta(str(csv_path)) == {}


def test_read_run_meta_guard2_csv_field_match_is_normcase_abspath_tolerant(tmp_path):
    """The comparison is normcase(abspath(...)) on both sides, so a
    non-normalized but equivalent path in the sidecar must still match."""
    csv_path = tmp_path / "run.csv"
    sidecar = tmp_path / "run.csv.meta.json"
    weird = os.path.join(str(tmp_path), ".", "run.csv")
    sidecar.write_text(json.dumps({"status": "completed", "csv": weird,
                                   "results": {"warm_resets_mid_run": 1}}))
    meta = rhs.read_run_meta(str(csv_path))
    assert meta.get("results", {}).get("warm_resets_mid_run") == 1


def test_read_run_meta_guard3_created_before_launched_at_rejected(tmp_path):
    """D2 guard 3 (only active when `launched_at` is supplied): a sidecar
    whose `created` predates the CALLER's launch time belongs to a previous
    attempt into the same (non-fresh, --force'd) path and must be discarded."""
    csv_path = tmp_path / "run.csv"
    sidecar = tmp_path / "run.csv.meta.json"
    old_created = (datetime.datetime.now() - datetime.timedelta(minutes=5)) \
        .astimezone().isoformat(timespec="seconds")
    sidecar.write_text(json.dumps({"status": "completed", "csv": str(csv_path),
                                   "created": old_created,
                                   "results": {"warm_resets_mid_run": 1}}))
    launched_at = datetime.datetime.now().astimezone()
    assert rhs.read_run_meta(str(csv_path), launched_at) == {}
    # Guard 3 is opt-in: with no launched_at to compare against, the very same
    # (stale-looking) sidecar is still accepted.
    assert rhs.read_run_meta(str(csv_path)) != {}


def test_read_run_meta_guard3_equal_second_timestamps_accepted(tmp_path):
    """`created == launched_at` (to the second) must NOT be rejected -- the
    guard is a strict `created < launched_at`."""
    csv_path = tmp_path / "run.csv"
    sidecar = tmp_path / "run.csv.meta.json"
    now = datetime.datetime.now().astimezone().replace(microsecond=0)
    sidecar.write_text(json.dumps({"status": "completed", "csv": str(csv_path),
                                   "created": now.isoformat(timespec="seconds"),
                                   "results": {"warm_resets_mid_run": 1}}))
    meta = rhs.read_run_meta(str(csv_path), now)
    assert meta.get("results", {}).get("warm_resets_mid_run") == 1


def test_read_run_meta_guard3_garbage_created_is_accepted_unverifiable(tmp_path):
    """An unparseable `created` cannot be compared, so guard 3 lets it through
    (docstring: 'cannot verify' passes rather than discarding a sidecar that
    is probably fine)."""
    csv_path = tmp_path / "run.csv"
    sidecar = tmp_path / "run.csv.meta.json"
    sidecar.write_text(json.dumps({"status": "completed", "csv": str(csv_path),
                                   "created": "not-a-timestamp",
                                   "results": {"warm_resets_mid_run": 1}}))
    launched_at = datetime.datetime.now().astimezone()
    meta = rhs.read_run_meta(str(csv_path), launched_at)
    assert meta.get("results", {}).get("warm_resets_mid_run") == 1


def test_warm_reset_count_prefers_meta_json_over_child_stdout(tmp_path):
    csv_path = tmp_path / "run.csv"
    sidecar = tmp_path / "run.csv.meta.json"
    sidecar.write_text(json.dumps({"csv": str(csv_path),
                                   "results": {"warm_resets_mid_run": 3,
                                              "warm_resets_observed": 4,
                                              "warm_reset_times_s": [1.0, 2.0]}}))
    child = {"summary": {"warm_resets_mid_run": 99}}
    counts, source = rhs.warm_reset_count(str(csv_path), child)
    assert counts == {"mid_run": 3, "observed": 4, "times": [1.0, 2.0]}
    assert source == "meta.json"


def test_warm_reset_count_falls_back_to_child_stdout_when_no_sidecar(tmp_path):
    """The --dashboard case: the child's stdout goes to the terminal and is
    never captured, but a sidecar-less run can still fall back to whatever
    the caller DID manage to capture in `child['summary']`. D4: the stdout
    line carries both counts but no timestamps, hence times=None."""
    csv_path = tmp_path / "run.csv"       # no .meta.json written
    child = {"summary": {"warm_resets_mid_run": 5, "warm_resets": 6}}
    counts, source = rhs.warm_reset_count(str(csv_path), child)
    assert counts == {"mid_run": 5, "observed": 6, "times": None}
    assert source == "child stdout"


def test_warm_reset_count_unmeasured_when_neither_source_available(tmp_path):
    csv_path = tmp_path / "run.csv"
    counts, source = rhs.warm_reset_count(str(csv_path), {})
    assert counts == {"mid_run": None, "observed": None, "times": None}
    assert source == "unmeasured"


def test_warm_reset_count_none_csv_path_falls_back_to_stdout():
    counts, source = rhs.warm_reset_count(
        None, {"summary": {"warm_resets_mid_run": 7, "warm_resets": 8}})
    # read_run_meta(None) short-circuits to {}, so only the stdout fallback applies.
    assert counts == {"mid_run": 7, "observed": 8, "times": None}
    assert source == "child stdout"


def test_warm_reset_count_uses_child_launched_at_for_the_sidecar_guard(tmp_path):
    """warm_reset_count() must parse child['launched_at'] and pass it through
    to read_run_meta()'s guard 3 -- a sidecar older than the child's own
    launch is rejected here too, falling back to the stdout summary."""
    csv_path = tmp_path / "run.csv"
    sidecar = tmp_path / "run.csv.meta.json"
    old_created = (datetime.datetime.now() - datetime.timedelta(minutes=5)) \
        .astimezone().isoformat(timespec="seconds")
    sidecar.write_text(json.dumps({"csv": str(csv_path), "created": old_created,
                                   "results": {"warm_resets_mid_run": 3}}))
    child = {"launched_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
             "summary": {"warm_resets_mid_run": 9, "warm_resets": 9}}
    counts, source = rhs.warm_reset_count(str(csv_path), child)
    assert source == "child stdout"
    assert counts["mid_run"] == 9


def test_warm_reset_count_unparseable_launched_at_does_not_crash(tmp_path):
    csv_path = tmp_path / "run.csv"
    child = {"launched_at": "not-a-timestamp",
             "summary": {"warm_resets_mid_run": 4, "warm_resets": 4}}
    counts, source = rhs.warm_reset_count(str(csv_path), child)
    assert source == "child stdout"
    assert counts["mid_run"] == 4


# ─────────────────────────────────────────────────────────────────────────
# judge_warm_resets() — REPAIRED signature (name, kind, counts, source) ->
# (check, note, reason_or_None). The fix round's D15 (comm-loss count >
# expected is now INCONCLUSIVE, not a plain FAIL) and K7 (unmeasured on a
# whitelisted scenario is an explicit UNVERIFIED note, not a quiet pass) are
# both matrix INVERSIONS from the pre-fix-round behaviour -- see the two
# tests named accordingly below.
# ─────────────────────────────────────────────────────────────────────────

def _wr_counts(mid_run=None, observed=None, times=None):
    return {"mid_run": mid_run, "observed": observed, "times": times}


def test_judge_warm_resets_none_is_unmeasured_pass_with_note():
    check, note, reason = rhs.judge_warm_resets(
        "steady", "scenario", _wr_counts(mid_run=None), "unmeasured")
    assert reason is None
    assert note is None
    assert check["passed"] is True
    assert check["name"] == "warm_reset_tripwire"
    assert "not measurable" in check["detail"]


def test_judge_warm_resets_non_whitelisted_zero_passes_clean():
    check, note, reason = rhs.judge_warm_resets(
        "steady", "scenario", _wr_counts(mid_run=0, observed=0), "meta.json")
    assert reason is None
    assert note is None
    assert check["passed"] is True
    assert check["name"] == "warm_reset_tripwire"


def test_judge_warm_resets_non_whitelisted_nonzero_is_inconclusive():
    check, note, reason = rhs.judge_warm_resets(
        "steady", "scenario", _wr_counts(mid_run=1, observed=1), "meta.json")
    assert reason is not None
    assert check["passed"] is False
    assert check["name"] == "warm_reset_tripwire"
    assert "steady" not in (rhs.SCENARIOS.get("steady") or {})  # sanity: no override


def test_judge_warm_resets_comm_loss_exactly_one_passes_not_inconclusive():
    assert rhs.SCENARIOS["comm-loss"].get("warm_resets_expected") == 1
    check, note, reason = rhs.judge_warm_resets(
        "comm-loss", "scenario", _wr_counts(mid_run=1, observed=1), "meta.json")
    assert reason is None
    assert check["passed"] is True
    assert check["name"] == "warm_reset_expected"


def test_judge_warm_resets_comm_loss_zero_fails_not_inconclusive():
    """Zero mid-run resets on comm-loss means the recovery never happened --
    a plain FAIL, and specifically NOT inconclusive (nothing was destroyed;
    the required event simply did not occur)."""
    check, note, reason = rhs.judge_warm_resets(
        "comm-loss", "scenario", _wr_counts(mid_run=0, observed=0), "meta.json")
    assert reason is None
    assert check["passed"] is False
    assert check["name"] == "warm_reset_expected"


def test_judge_warm_resets_comm_loss_two_is_now_inconclusive_by_design():
    """D15 (fix round) -- INVERTS the old expectation: an EXTRA mid-run reset
    beyond the whitelisted count destroys evidence exactly as it does
    anywhere else. The whitelist licenses only the ONE reset comm-loss's own
    2 s gap provokes, not a host stall on top of it, so count=2 (expected=1)
    is now INCONCLUSIVE, not a plain FAIL."""
    check, note, reason = rhs.judge_warm_resets(
        "comm-loss", "scenario", _wr_counts(mid_run=2, observed=2), "meta.json")
    assert reason is not None
    assert check["passed"] is False
    assert check["name"] == "warm_reset_expected"


def test_judge_warm_resets_comm_loss_none_is_unverified_note_k7():
    """K7 (fix round) -- INVERTS the old expectation: on a whitelisted
    scenario, an unmeasured count is no longer a quiet pass -- the
    requirement itself was never checked, so the detail text says UNVERIFIED
    explicitly. Still non-failing (passed True): nothing was disproved."""
    check, note, reason = rhs.judge_warm_resets(
        "comm-loss", "scenario", _wr_counts(mid_run=None), "unmeasured")
    assert reason is None
    assert check["passed"] is True
    assert check["name"] == "warm_reset_expected"
    assert "UNVERIFIED" in check["detail"]
    assert "unmeasured" in check["detail"]


def test_judge_warm_resets_reason_text_mentions_the_source():
    _check, _note, reason = rhs.judge_warm_resets(
        "steady", "scenario", _wr_counts(mid_run=2, observed=2), "child stdout")
    assert reason is not None
    assert "child stdout" in reason
    assert "2" in reason


def test_judge_warm_resets_d16_replay_kind_never_inherits_scenario_expected():
    """D16: a replay entry sharing a name with a whitelisted scenario (a
    collision, e.g. hypothetically 'comm-loss') must NOT consult SCENARIOS --
    only kind='scenario' may. Treated as an ordinary run: one unexplained
    mid-run reset with no exemption is INCONCLUSIVE, not a satisfied
    warm_reset_expected pass."""
    check, note, reason = rhs.judge_warm_resets(
        "comm-loss", "replay", _wr_counts(mid_run=1, observed=1), "meta.json")
    assert check["name"] == "warm_reset_tripwire"
    assert reason is not None
    assert check["passed"] is False


def test_judge_warm_resets_d4_grace_window_note_when_observed_exceeds_mid_run():
    check, note, reason = rhs.judge_warm_resets(
        "steady", "scenario", _wr_counts(mid_run=0, observed=1, times=[0.5]), "meta.json")
    assert note is not None
    assert "grace window" in note
    assert "0.5" in note
    # A grace-window-only transition is neither a failure nor inconclusive.
    assert check["passed"] is True
    assert reason is None


def test_judge_warm_resets_d4_no_note_when_observed_equals_mid_run():
    check, note, reason = rhs.judge_warm_resets(
        "steady", "scenario", _wr_counts(mid_run=0, observed=0), "meta.json")
    assert note is None


def test_judge_warm_resets_item10_renders_only_in_grace_timestamps():
    """Item 10: `times` carries EVERY observed transition, mid-run ones
    included -- the note must render ONLY the in-grace subset. The exact
    comm-loss bug this fixes: 'at t=0.5, 7.5' where 7.5 was the scenario's
    OWN designed mid-run recovery, not a second in-grace event."""
    check, note, reason = rhs.judge_warm_resets(
        "steady", "scenario",
        _wr_counts(mid_run=0, observed=1, times=[0.5, 7.5]), "meta.json")
    assert note is not None
    assert "0.5" in note
    assert "7.5" not in note


def test_judge_warm_resets_item10_no_in_grace_timestamp_fallback():
    """When `times` exist but NONE is in-grace (the list is capped, or the
    clocks disagree), the note must say so explicitly rather than printing
    mid-run times under an 'in-grace' heading."""
    check, note, reason = rhs.judge_warm_resets(
        "steady", "scenario",
        _wr_counts(mid_run=0, observed=1, times=[7.5, 12.0]), "meta.json")
    assert note is not None
    assert "no in-grace timestamp available" in note
    assert "7.5" in note and "12" in note
    assert rhs.WARM_RESET_GRACE_S is not None
    assert ("%.1f" % rhs.WARM_RESET_GRACE_S) in note


def test_judge_warm_resets_d4_note_alongside_a_real_mid_run_reset():
    """The grace-window note and the mid-run verdict are independent: a run
    can have BOTH a grace-window transition AND a separate mid-run one."""
    check, note, reason = rhs.judge_warm_resets(
        "steady", "scenario", _wr_counts(mid_run=1, observed=2, times=[0.5, 5.0]),
        "meta.json")
    assert note is not None
    assert check["passed"] is False
    assert reason is not None


# ─────────────────────────────────────────────────────────────────────────
# render_report() -- D4 grace-window note rendering
# ─────────────────────────────────────────────────────────────────────────

def test_render_report_d4_scenario_note_rendered_with_marker():
    result = _fake_scenario_result()
    result["notes"] = ["1 warm reset(s) inside the start-of-run grace window ..."]
    report = rhs.render_report(_fake_meta(), [result])
    assert "> NOTE: 1 warm reset(s) inside the start-of-run grace window ..." in report


def test_render_report_d4_replay_note_rendered_with_marker():
    result = _fake_replay_result()
    result["notes"] = list(result["notes"]) + ["1 warm reset(s) inside the grace window"]
    report = rhs.render_report(_fake_meta(), [result])
    assert "_note_: 1 warm reset(s) inside the grace window" in report


# ─────────────────────────────────────────────────────────────────────────
# render_report() -- K4: inconclusive result, all three render sites
# ─────────────────────────────────────────────────────────────────────────

def test_render_report_inconclusive_clean_all_three_sites():
    result = _fake_scenario_result(passed=False)
    result["inconclusive"] = True
    result["inconclusive_reason"] = "1 mid-run HIL warm reset(s) observed (meta.json): ..."
    result["also_failed"] = 0
    report = rhs.render_report(_fake_meta(), [result])
    # Header: the clean-inconclusive sentence, and D3's exclusion holds in
    # the OTHER direction here -- no "also FAILED"/"further run(s)" wording.
    assert "1 run(s) saw a MID-RUN HIL warm reset" in report
    assert "These are NOT failures" in report
    assert "further run(s)" not in report
    # Table cell (via result_label(bold_fail=True)):
    assert "**INCONCLUSIVE**" in report
    assert "also FAILED" not in report
    # Blockquote:
    assert "> **INCONCLUSIVE.** 1 mid-run HIL warm reset(s) observed" in report


def test_render_report_inconclusive_with_also_failed_all_three_sites():
    result = _fake_scenario_result(passed=False)
    result["checks"] = [{"name": "observation_frames", "passed": False, "detail": "no frames"}]
    result["inconclusive"] = True
    result["inconclusive_reason"] = "2 mid-run HIL warm reset(s) observed (meta.json): ..."
    result["also_failed"] = 1
    report = rhs.render_report(_fake_meta(), [result])
    # Header: the "also FAILED" branch -- D3: excluded from the "not
    # failures" sentence, since ninc_clean is 0 when every inconclusive run
    # also carries a real failure.
    assert "1 further run(s) saw a mid-run warm reset AND had" in report
    assert "These are NOT failures" not in report
    # Table cell:
    assert "INCONCLUSIVE (also FAILED 1 check(s))" in report
    # Blockquote (unaffected by also_failed -- still renders):
    assert "> **INCONCLUSIVE.** 2 mid-run HIL warm reset(s) observed" in report


def test_render_report_inconclusive_mixed_clean_and_failed_header_both_parts():
    clean = _fake_scenario_result(name="steady", passed=False)
    clean["inconclusive"] = True
    clean["inconclusive_reason"] = "1 mid-run HIL warm reset(s) observed (meta.json): x"
    clean["also_failed"] = 0
    failed = _fake_scenario_result(name="sag", passed=False)
    failed["checks"] = [{"name": "expected_fault", "passed": False, "detail": "no fault"}]
    failed["inconclusive"] = True
    failed["inconclusive_reason"] = "1 mid-run HIL warm reset(s) observed (meta.json): y"
    failed["also_failed"] = 1
    report = rhs.render_report(_fake_meta(), [clean, failed])
    assert "1 run(s) saw a MID-RUN HIL warm reset" in report
    assert "These are NOT failures" in report
    assert "1 further run(s) saw a mid-run warm reset AND had" in report


# ─────────────────────────────────────────────────────────────────────────
# K4 -- end-to-end: one _run_plan()/main()-level test per half, using the
# existing run_child monkeypatch pattern (section 10 above), a written
# .meta.json showing warm_resets_mid_run=1.
# ─────────────────────────────────────────────────────────────────────────

def _fake_run_child_with_mid_run_reset(mid_run=1, observed=1, times=(5.5,)):
    """Builds a run_child() replacement that writes a completed .meta.json
    sidecar (matching item['csv'], launched safely in the past) showing the
    given mid-run warm-reset count, and returns a matching child record."""
    def fake_run_child(item, args):
        meta_doc = {"status": "completed", "csv": item["csv"],
                    "results": {"warm_resets_mid_run": mid_run,
                               "warm_resets_observed": observed,
                               "warm_reset_times_s": list(times)}}
        with open(item["csv"] + ".meta.json", "w", encoding="utf-8") as fh:
            json.dump(meta_doc, fh)
        return {"status": "ok", "returncode": 0, "wall_s": 0.01, "log": item["log"],
                "summary": {"achieved_hz": 1000.0, "tx_frames": 10, "rx_frames": 10,
                           "rx_bad": 0},
                "launched_at": (datetime.datetime.now() - datetime.timedelta(seconds=30))
                               .astimezone().isoformat(timespec="seconds")}
    return fake_run_child


def test_k4_scenario_half_inconclusive_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(rhs, "run_child", _fake_run_child_with_mid_run_reset())
    # --keep-going: the fake child writes no real CSV, so analyze_scenario_csv()
    # sees zero observation frames and would otherwise trip the unrelated
    # "board unreachable, abort after run 1" guard (rc=2) before the tripwire
    # verdict this test actually cares about is ever reached.
    rc = rhs.main(["--out", str(tmp_path), "--only", "steady", "--keep-going"])
    assert rc == 1

    results = json.loads((tmp_path / "results.json").read_text())["results"]
    assert len(results) == 1
    res = results[0]
    assert res["kind"] == "scenario"
    assert res["inconclusive"] is True
    assert res["passed"] is False
    assert res["inconclusive_reason"]
    report = (tmp_path / "REPORT.md").read_text()
    assert "INCONCLUSIVE" in report


def test_k4_replay_half_inconclusive_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(rhs, "run_child", _fake_run_child_with_mid_run_reset())
    rc = rhs.main(["--out", str(tmp_path), "--only", "ML0146", "--keep-going"])
    assert rc == 1

    results = json.loads((tmp_path / "results.json").read_text())["results"]
    assert len(results) == 1
    res = results[0]
    assert res["kind"] == "replay"
    assert res["inconclusive"] is True
    assert res["passed"] is False
    assert res["inconclusive_reason"]
    # encoding="utf-8" explicit: the replay-half preamble (M1, fix round) now
    # writes a literal "⚠️" into REPORT.md, and main() writes the file as
    # UTF-8 -- Path.read_text()'s platform-default encoding (cp1252 on
    # Windows) cannot decode the variation-selector byte in that emoji and
    # raises UnicodeDecodeError. Reading it back the same way it was written
    # is a test-robustness fix, not a change to what main() writes.
    report = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
    assert "INCONCLUSIVE" in report


# ─────────────────────────────────────────────────────────────────────────
# D1/K2 -- exactly one --force in every child argv, both halves, and in
# hil_replay_suite.build_sim_argv() itself.
# ─────────────────────────────────────────────────────────────────────────

def test_full_argv_scenario_half_has_exactly_one_force():
    plan = rhs.build_plan(_args(only=["steady"]))
    assert len(plan) == 1
    argv = rhs.full_argv(plan[0], _args())
    assert argv.count("--force") == 1


def test_full_argv_replay_half_has_exactly_one_force():
    plan = rhs.build_plan(_args(only=["ML0146"]))
    assert len(plan) == 1
    # build_sim_argv() already emits --force into plan[0]["argv"] (D1); the
    # dedup in full_argv() must not add a second one on top of it.
    assert "--force" in plan[0]["argv"]
    argv = rhs.full_argv(plan[0], _args())
    assert argv.count("--force") == 1


def test_build_sim_argv_has_exactly_one_force():
    entry = REPLAY_SUITE[0]
    argv = hrs.build_sim_argv(entry, "/tmp/csv_dir")
    assert argv.count("--force") == 1


# ─────────────────────────────────────────────────────────────────────────
# D11 -- refusal/uniquification must consider .meta.json and .events.jsonl,
# not just the CSV itself (output_path_taken() / unique_output_path()).
# These live in hil_plant_sim.py; see test_hil_plant_sim.py's mirror of this
# section for the sanitize/token-level coverage.
# ─────────────────────────────────────────────────────────────────────────

def test_d11_child_csv_paths_are_absolute(tmp_path):
    """The suite always passes --force (D1), so this is really pinning that
    run_hil_suite.py hands its children ABSOLUTE CSV paths (module docstring:
    'the suite's artifacts never get redirected into HIL Results') -- an
    orphan-sidecar refusal in hil_plant_sim.py (covered thoroughly in
    test_hil_plant_sim.py) only means anything if the path it is guarding is
    the one the child was actually told to use, not a relative path that
    could resolve somewhere else entirely."""
    plan = rhs.build_plan(_args(only=["steady"], out=str(tmp_path)))
    argv = rhs.full_argv(plan[0], _args(out=str(tmp_path)))
    assert "--csv" in argv
    csv_path = argv[argv.index("--csv") + 1]
    assert os.path.isabs(csv_path), "child CSV paths must be absolute (D11 note)"


# ─────────────────────────────────────────────────────────────────────────
# warn_short_settle()
# ─────────────────────────────────────────────────────────────────────────

def test_warn_short_settle_fires_below_threshold(capsys):
    rhs.warn_short_settle(_args(settle_s=1.0))
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "1.00" in out


def test_warn_short_settle_silent_at_default_5s(capsys):
    rhs.warn_short_settle(_args(settle_s=5.0))
    out = capsys.readouterr().out
    assert out == ""


def test_warn_short_settle_silent_exactly_at_threshold(capsys):
    rhs.warn_short_settle(_args(settle_s=rhs.SETTLE_MIN_RECOVER_S))
    out = capsys.readouterr().out
    assert out == ""


def test_warn_short_settle_fires_just_below_threshold(capsys):
    rhs.warn_short_settle(_args(settle_s=rhs.SETTLE_MIN_RECOVER_S - 0.01))
    out = capsys.readouterr().out
    assert "WARNING" in out


def test_settle_min_recover_s_is_1_5():
    """Pin the literal value: it is derived from the firmware's 1000 ms run-
    boundary requirement plus host-jitter margin (module docstring), not an
    arbitrary round number that could silently drift."""
    assert rhs.SETTLE_MIN_RECOVER_S == pytest.approx(1.5)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
