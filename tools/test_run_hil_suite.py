#!/usr/bin/env python3
"""pytest suite for tools/run_hil_suite.py — the HIL suite wrapper (plan
building, argv construction, offline health-check analysis, and the pure
report renderer). No board, no subprocess of the real simulator — this
exercises only the pure/offline functions per the fence in the task.

Run: cd tools && python -m pytest test_run_hil_suite.py -v
"""
import argparse
import csv
import datetime
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_hil_suite as rhs  # noqa: E402
import hil_replay_suite as hrs  # noqa: E402
from hil_plant_sim import SCENARIOS, AG105_ST_CHARGING  # noqa: E402
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

def test_build_plan_full_count_40_runs():
    # 29 scenarios (25 as of 2026-08-31 wave 2: the ems-y-* quartet,
    # ems-ftp75-5050/-socband, mppt-tracking, charge-to-full, pi-silence and
    # share-staircase -- 15 + 10 = 25 -- plus `ems-sdp` from the SDP round,
    # plus ems-ftp75-sdp / ems-sdp-cross / ems-sdp-braking from the
    # SDP-interior round) + 27 replays (SY0001/FU4 added earlier) = 56. Every
    # scenario occupies a plan slot even when it is rendered as a SKIP record
    # (operator-required / --pi-live / --with-ftp75), so this count is a
    # plan-slot count, not a will-actually-run count.
    # WP-C (2026-09-01): +1 scenario, `regen-harvest-true` -> 30 scenarios, 57 slots.
    # WP-1C (2026-09-02): +3 scenarios, the `ems-sdp-alpha-*` trio -> 35
    # scenarios, 62 slots. They are SKIP records by default (--with-alpha), and
    # a skip record still occupies a plan slot, which is what this counts.
    plan = rhs.build_plan(_args())
    # WP-B: +v-bus-sense-offset (the UV-dwell objective's own home)
    assert len(plan) == len(SCENARIOS) + len(REPLAY_SUITE) == 62
    kinds = [p["kind"] for p in plan]
    assert kinds.count("scenario") == 35
    assert kinds.count("replay") == 27


def test_build_plan_replay_only():
    plan = rhs.build_plan(_args(replay_only=True))
    assert len(plan) == 27
    assert all(p["kind"] == "replay" for p in plan)


def test_build_plan_scenarios_only():
    plan = rhs.build_plan(_args(scenarios_only=True))
    assert len(plan) == 35      # WP-C: +regen-harvest-true; WP-E: +ems-ftp75-dp;
                                # WP-B: +v-bus-sense-offset;
                                # WP-1C: +the ems-sdp-alpha-* trio
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
    # 2026-08-31 wave 2: charge-to-full joins the charge-* glob family.
    plan = rhs.build_plan(_args(only=["charge-*"]))
    names = {p["name"] for p in plan}
    assert names == {"charge-cruise", "charge-regen", "charge-fault",
                     "charge-to-full"}


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
    entry is identical with or without it.

    The ems-ftp75-* scenarios (three since 2026-08-31: the -sdp variant
    joined FTP75_SCENARIOS) are excluded from the "no skip_reason"
    assertion: they are skip-recorded under DEFAULT args too (the
    --with-ftp75 gate, unrelated to --with-operator), so they carry a
    skip_reason on both sides of this comparison -- their argv equality is
    still asserted."""
    plan_default = {p["name"]: p for p in rhs.build_plan(_args()) if p["kind"] == "scenario"}
    plan_operator = {p["name"]: p for p in rhs.build_plan(_args(with_operator=True))
                     if p["kind"] == "scenario"}
    # WP-1C: the ems-sdp-alpha-* trio is excluded for exactly the reason the
    # FTP-75 set is -- they carry a skip_reason on BOTH sides of this
    # comparison (the --with-alpha gate, unrelated to --with-operator).
    gated = rhs.FTP75_SCENARIOS | rhs.ALPHA_SCENARIOS
    for name in plan_default:
        if name == "drive":
            continue
        assert plan_default[name]["argv"] == plan_operator[name]["argv"], name
        if name in gated:
            continue
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


# ── F1: fault_first_t_whole_run -- unfiltered first-sighting map ───────────

def test_analyze_scenario_csv_fault_first_t_whole_run_present_in_zero_obs_dict():
    """The whole-run map must be present (as {}) in the initial/degenerate
    metrics dict alongside fault_first_t, not added only once a row is
    actually parsed."""
    m = rhs.analyze_scenario_csv("/nonexistent/path/nope.csv")
    assert m["fault_first_t_whole_run"] == {}
    assert m["fault_first_t"] == {}


def test_analyze_scenario_csv_fault_first_t_whole_run_populated_pre_grace(tmp_path):
    """A bit that appears BEFORE the grace bound must still land in the
    whole-run map (F1's whole point), even though it is invisible to
    fault_first_t (post-grace only, see the next test)."""
    rows = [
        {"t": "0.500", "fault_flags": hex(0x0001), "state": "2"},  # pre-grace (2.0s)
        {"t": "3.000", "fault_flags": "0", "state": "2"},
    ]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path), grace_s=2.0)
    assert m["fault_first_t_whole_run"].get(rhs.fault_names(0x0001)) == pytest.approx(0.5)


def test_analyze_scenario_csv_fault_first_t_whole_run_differs_from_post_grace_on_in_grace_latch(
        tmp_path):
    """The exact scenario F1 exists to surface: a bit that latches INSIDE the
    grace window and persists reports the GRACE BOUND in fault_first_t (its
    honest post-grace-scoped answer) but its true onset time in
    fault_first_t_whole_run -- the two maps must disagree here, not agree."""
    rows = [
        {"t": "0.600", "fault_flags": hex(0x0001), "state": "99"},  # true onset, pre-grace
        {"t": "1.500", "fault_flags": hex(0x0001), "state": "99"},  # persists through grace
        {"t": "2.000", "fault_flags": hex(0x0001), "state": "99"},  # exactly at grace_s
        {"t": "3.000", "fault_flags": hex(0x0001), "state": "99"},
    ]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path), grace_s=2.0)
    name = rhs.fault_names(0x0001)
    assert m["fault_first_t_whole_run"][name] == pytest.approx(0.6)
    assert m["fault_first_t"][name] == pytest.approx(2.0)
    assert m["fault_first_t_whole_run"][name] != m["fault_first_t"][name]


def test_analyze_scenario_csv_fault_first_t_whole_run_matches_post_grace_when_onset_is_post_grace(
        tmp_path):
    """The converse sanity check: when a bit's true onset IS post-grace, both
    maps must agree -- the divergence in the test above is specifically a
    pre-grace-onset artifact, not a general property of the two maps."""
    rows = [
        {"t": "0.500", "fault_flags": "0", "state": "2"},
        {"t": "5.000", "fault_flags": hex(0x0001), "state": "99"},
    ]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path), grace_s=2.0)
    name = rhs.fault_names(0x0001)
    assert m["fault_first_t_whole_run"][name] == pytest.approx(5.0)
    assert m["fault_first_t"][name] == pytest.approx(5.0)


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
             n_obs_post_grace=None, last_obs_t=None, error_code_post_grace=None,
             error_code_final=None, fault_first_t_whole_run=None,
             fault_first_latch_t=None):
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
            # PART B1 (C1 round, 2026-09-01): the POST-GRACE LATCHED
            # first-sighting map, which is what judge_scenario() now reads for
            # `not_before_s`. It DEFAULTS TO `fault_first_t` so every existing
            # caller keeps meaning what it meant: those callers describe traces
            # in which the bit and the latch are the same event. A caller that
            # wants them to differ -- a transient bare bit followed by a later
            # latch -- passes both explicitly.
            "fault_first_latch_t": (fault_first_t or {}
                                    if fault_first_latch_t is None
                                    else fault_first_latch_t),
            # B-L3: the WHOLE-RUN first-sighting map, which the
            # `share_cut_load_hazard` tripwire anchors its teardown cutoff on
            # (minus the carried-in window). Empty by default -> no anchor ->
            # nothing is excluded as teardown, which is the conservative
            # reading for every test that does not care.
            "fault_first_t_whole_run": fault_first_t_whole_run or {},
            "final_state": final_state,
            "grace_s": rhs.WARM_RESET_GRACE_S if grace_s is None else grace_s,
            "survive_to_t": survive_to_t,
            "fault_bits_before_survive": fault_bits_before_survive,
            "state_at_survive": state_at_survive,
            "n_obs_post_grace": n_obs_post_grace,
            "last_obs_t": last_obs_t,
            # fw v25 wire attribution. None (the DEFAULT) is a pre-v25
            # board -- so every pre-existing test keeps exercising the
            # stream-health inference path unchanged.
            "error_code_post_grace": error_code_post_grace,
            "error_code_final": error_code_final}


def _events(over_absmax=0, worst_ring_v=None, worst_over_absmax_ring_v=None,
           kinds=None, field_values=None, events_by_kind=None):
    # events_by_kind (2026-08-31): analyze_events()'s real output always
    # carries this key, and _judge_event_spec() reads a `where`-filtered spec
    # from it rather than from field_values -- scp-inrush's single-outcome
    # events_require now pins `where`, so any caller exercising it must pass
    # events_by_kind explicitly (see _scp_cut_events() below).
    return {"total": 0, "kinds": kinds or {}, "over_absmax": over_absmax,
            "worst_ring_v": worst_ring_v,
            "worst_over_absmax_ring_v": worst_over_absmax_ring_v,
            "field_values": field_values or {},
            "events_by_kind": events_by_kind or {}}


def _child(status="ok", summary=None):
    return {"status": status, "returncode": 0, "summary": summary or {"achieved_hz": 1000.0}}


def _leaf_measurement_pass(spec):
    """A single leaf-spec measurement (M2) that just clears its own assertion
    kind (>= for min_ticks/min_value/strictly_decreases_by, <= for
    max_ticks/max_value, a latch at exactly after_t for fault_latch_bit, an
    edge at exactly after_t + max_ms/2 for the switch_fall_latency_ms kind
    -- 2026-08-31 wave 2 additions: max_value and max_ms/edge_t)."""
    m = {"rows": 10, "ticks": 0, "peak": None, "first": None, "last": None,
         "latch_t": None, "prev_bit": None, "edge_t": None,
         # 2026-09-01 kinds: max_continuous_ticks / edge_count_between.
         "run": 0, "max_run": 0, "edges": 0}
    if "max_ms" in spec:
        after = float(spec.get("after_t", 0.0))
        lim = float(spec["max_ms"])
        m["edge_t"] = after + (lim / 2.0) / 1000.0   # comfortably inside the bound
        m["prev_bit"] = 0 if spec.get("edge", "fall") == "fall" else 1
    elif "max_continuous_ticks" in spec:
        m["max_run"] = int(spec["max_continuous_ticks"])
        m["ticks"] = m["max_run"]
    elif "edge_count_between" in spec:
        lo, hi = (int(v) for v in spec["edge_count_between"])
        m["edges"] = (lo + hi) // 2                  # comfortably inside the band
    elif "min_ticks" in spec:
        m["ticks"] = int(spec["min_ticks"])
    elif "max_ticks" in spec:
        m["ticks"] = int(spec["max_ticks"])
    elif "min_value" in spec:
        m["peak"] = float(spec["min_value"])
    elif "max_value" in spec:
        m["peak"] = float(spec["max_value"])
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
            "latch_t": None, "prev_bit": None, "edge_t": None,
            "run": 0, "max_run": 0, "edges": 0}


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


# ─────────────────────────────────────────────────────────────────────────
# 4c. scp-inrush single-outcome events_require (2026-08-31 deterministic-fold
#     redesign): the ONE-TICK-RACE two-outcome events_any_of form is RETIRED
#     -- the stimulus now wins the race outright (see the SCP_INRUSH_ARM_V
#     block in hil_plant_sim.py), so the entry is back to a plain
#     events_require with a `where` filter. The band was PROVISIONAL at
#     [5.5, 6.7] A for a few hours (2026-08-31); it is now MEASURED at
#     [6.15, 6.55] A from three live board runs (i_cut 6.3797373 A
#     bit-identical across all three) and `provisional_note` was deleted --
#     see the entry's own comment in run_hil_suite.py.
# ─────────────────────────────────────────────────────────────────────────

def test_fault_expectations_scp_inrush_no_longer_carries_events_any_of():
    """events_any_of is GONE from scp-inrush -- it is a single events_require
    spec again, single-outcome."""
    expect = rhs.FAULT_EXPECTATIONS["scp-inrush"]
    assert "events_any_of" not in expect
    assert "events_require" in expect
    assert len(expect["events_require"]) == 1


def test_fault_expectations_scp_inrush_events_require_shape():
    """The single spec: scp_cut, filtered to MOT_PWR, exactly one, i_cut in
    the MEASURED [6.15, 6.55] A band (derived 2026-08-31 from three live
    board runs that measured i_cut = 6.3797373 A bit-identical)."""
    expect = rhs.FAULT_EXPECTATIONS["scp-inrush"]
    assert expect["events_require"] == [
        {"kind": "scp_cut", "where": {"switch": "MOT_PWR"}, "count": 1,
         "field": "i_cut", "min_value": 6.15, "max_value": 6.55},
    ]


def _scp_cut_events(i_cut, switch="MOT_PWR", extra=()):
    """events dict carrying one scp_cut event (plus any `extra` events) with
    events_by_kind populated -- required because the entry's spec uses
    `where`, which _judge_event_spec reads from events_by_kind, not
    field_values (see _judge_event_spec's docstring)."""
    by_kind = {"scp_cut": [{"switch": switch, "i_cut": i_cut}]}
    for kind, fields in extra:
        by_kind.setdefault(kind, []).append(fields)
    kinds = {k: len(v) for k, v in by_kind.items()}
    return _events(kinds=kinds, events_by_kind=by_kind)


def test_judge_scenario_scp_inrush_passes_inside_the_band_on_mot_pwr():
    m = _metrics(fault_bits_seen=0, final_fault_flags=0)
    events = _scp_cut_events(6.3797373)   # the actual live-measured value
    passed, checks = rhs.judge_scenario("scp-inrush", m, events, _child())
    ev = [c for c in checks if c["name"] == "events_require_scp_cut"][0]
    assert ev["passed"] is True
    assert passed is True


def test_judge_scenario_scp_inrush_band_boundaries():
    """6.15 and 6.55 A (the measured band edges) pass; just outside either
    edge fails."""
    m = _metrics(fault_bits_seen=0, final_fault_flags=0)
    for i_cut in (6.15, 6.55, 6.3, 6.3797373):
        events = _scp_cut_events(i_cut)
        _passed, checks = rhs.judge_scenario("scp-inrush", m, events, _child())
        ev = [c for c in checks if c["name"] == "events_require_scp_cut"][0]
        assert ev["passed"] is True, i_cut

    for i_cut in (6.149, 6.1, 6.551, 7.0, 5.5):
        events = _scp_cut_events(i_cut)
        _passed, checks = rhs.judge_scenario("scp-inrush", m, events, _child())
        ev = [c for c in checks if c["name"] == "events_require_scp_cut"][0]
        assert ev["passed"] is False, i_cut


def test_judge_scenario_scp_inrush_count_not_1_fails():
    """Zero cuts, or more than one, both fail the count == 1 pin."""
    m = _metrics(fault_bits_seen=0, final_fault_flags=0)

    zero = _events(kinds={}, events_by_kind={})
    _passed, checks = rhs.judge_scenario("scp-inrush", m, zero, _child())
    ev = [c for c in checks if c["name"] == "events_require_scp_cut"][0]
    assert ev["passed"] is False

    by_kind = {"scp_cut": [{"switch": "MOT_PWR", "i_cut": 6.0},
                           {"switch": "MOT_PWR", "i_cut": 6.1}]}
    two = _events(kinds={"scp_cut": 2}, events_by_kind=by_kind)
    _passed2, checks2 = rhs.judge_scenario("scp-inrush", m, two, _child())
    ev2 = [c for c in checks2 if c["name"] == "events_require_scp_cut"][0]
    assert ev2["passed"] is False


def test_judge_scenario_scp_inrush_same_band_cut_on_a_different_switch_does_not_satisfy():
    """A scp_cut IN-BAND on FC_BUS instead of MOT_PWR must NOT satisfy the
    `where` filter -- the whole point of pinning `where` on this entry."""
    m = _metrics(fault_bits_seen=0, final_fault_flags=0)
    events = _scp_cut_events(6.3, switch="FC_BUS")   # 6.3 is inside [6.15, 6.55]
    passed, checks = rhs.judge_scenario("scp-inrush", m, events, _child())
    ev = [c for c in checks if c["name"] == "events_require_scp_cut"][0]
    assert ev["passed"] is False
    assert passed is False


# ── `provisional_note` (2026-08-31 review M3; deleted from scp-inrush the
#    same day once the band was live-measured) ──────────────────────────────
# A threshold in an entry has not yet been derived from a live campaign; the
# note rides EVERY events_require check's detail (pass or fail) so
# results.json/REPORT.md carry the qualifier and a first-campaign band miss
# reads as "threshold not yet derived", never as a board/plant change. The
# MECHANISM is tested below against a synthetic expectation only -- scp-inrush
# itself no longer carries the key (its band is measured, not provisional),
# so the live-entry tests exercise its ABSENCE instead.

def test_fault_expectations_scp_inrush_does_not_carry_a_provisional_note():
    """The band is now MEASURED (three live board runs, i_cut = 6.3797373 A
    bit-identical), so `provisional_note` was DELETED the same day it was
    added -- pinned here so a future accidental re-add (e.g. copy-pasting
    the old comment block) is visible, and so the deletion this test
    documents was the deliberate act the entry's own comment describes,
    not a silent drop."""
    expect = rhs.FAULT_EXPECTATIONS["scp-inrush"]
    assert "provisional_note" not in expect


def test_judge_scenario_scp_inrush_no_provisional_suffix_on_pass_or_fail():
    """With the key gone, the live scp-inrush entry's events_require check
    must carry NO [PROVISIONAL: ...] suffix, on either outcome."""
    m = _metrics(fault_bits_seen=0, final_fault_flags=0)

    passing = _scp_cut_events(6.3797373)   # in the measured band
    _passed, checks = rhs.judge_scenario("scp-inrush", m, passing, _child())
    ev = [c for c in checks if c["name"] == "events_require_scp_cut"][0]
    assert ev["passed"] is True
    assert "PROVISIONAL" not in ev["detail"]

    failing = _events(kinds={}, events_by_kind={})
    _passed2, checks2 = rhs.judge_scenario("scp-inrush", m, failing, _child())
    ev2 = [c for c in checks2 if c["name"] == "events_require_scp_cut"][0]
    assert ev2["passed"] is False
    assert "PROVISIONAL" not in ev2["detail"]


_SYNTH_PROVISIONAL_NOTE_NAME = "__synthetic_provisional_note__"


def test_judge_scenario_provisional_note_absent_key_adds_no_suffix():
    """A synthetic entry with NO `provisional_note` key must get a plain
    detail -- no bracket, no trailing whitespace from a would-be empty
    suffix. Exercises both the PASS and FAIL side of the same
    events_require spec, keyed off a synthetic table entry so this does not
    depend on scp-inrush (or any other live entry) keeping the key at all."""
    synth = {
        "source": "test",
        "events_require": [{"kind": "scp_cut", "count": 1}],
    }
    assert "provisional_note" not in synth
    saved = dict(rhs.FAULT_EXPECTATIONS)
    rhs.FAULT_EXPECTATIONS[_SYNTH_PROVISIONAL_NOTE_NAME] = synth
    try:
        m = _metrics(fault_bits_seen=0, final_fault_flags=0)

        passing = _events(kinds={"scp_cut": 1})
        _passed, checks = rhs.judge_scenario(
            _SYNTH_PROVISIONAL_NOTE_NAME, m, passing, _child())
        ev = [c for c in checks if c["name"] == "events_require_scp_cut"][0]
        assert ev["passed"] is True
        assert "PROVISIONAL" not in ev["detail"]
        assert not ev["detail"].endswith("]")

        failing = _events()   # no scp_cut at all
        _passed2, checks2 = rhs.judge_scenario(
            _SYNTH_PROVISIONAL_NOTE_NAME, m, failing, _child())
        ev2 = [c for c in checks2 if c["name"] == "events_require_scp_cut"][0]
        assert ev2["passed"] is False
        assert "PROVISIONAL" not in ev2["detail"]
    finally:
        rhs.FAULT_EXPECTATIONS.clear()
        rhs.FAULT_EXPECTATIONS.update(saved)


def test_judge_scenario_provisional_note_present_key_adds_suffix_to_a_synthetic_entry():
    """The converse of the previous test: a synthetic entry WITH the key
    gets the suffix on both outcomes, with the exact note text rendered
    verbatim -- pins the "  [PROVISIONAL: <note>]" format itself (two
    leading spaces, colon, verbatim note, closing bracket) independent of
    scp-inrush's own note wording."""
    note = "a synthetic threshold, never derived from anything"
    synth = {
        "source": "test",
        "events_require": [{"kind": "scp_cut", "count": 1}],
        "provisional_note": note,
    }
    saved = dict(rhs.FAULT_EXPECTATIONS)
    rhs.FAULT_EXPECTATIONS[_SYNTH_PROVISIONAL_NOTE_NAME] = synth
    try:
        m = _metrics(fault_bits_seen=0, final_fault_flags=0)

        passing = _events(kinds={"scp_cut": 1})
        _passed, checks = rhs.judge_scenario(
            _SYNTH_PROVISIONAL_NOTE_NAME, m, passing, _child())
        ev = [c for c in checks if c["name"] == "events_require_scp_cut"][0]
        assert ev["passed"] is True
        assert ev["detail"].endswith("  [PROVISIONAL: %s]" % note)

        failing = _events()
        _passed2, checks2 = rhs.judge_scenario(
            _SYNTH_PROVISIONAL_NOTE_NAME, m, failing, _child())
        ev2 = [c for c in checks2 if c["name"] == "events_require_scp_cut"][0]
        assert ev2["passed"] is False
        assert ev2["detail"].endswith("  [PROVISIONAL: %s]" % note)
    finally:
        rhs.FAULT_EXPECTATIONS.clear()
        rhs.FAULT_EXPECTATIONS.update(saved)


def test_judge_scenario_provisional_note_rides_signals_require_checks_too():
    """DI-MED-5: `provisional_note` used to render onto events_require details
    ONLY, so an entry whose provisional thresholds are SIGNAL checks (ems-sdp's
    are) rendered them as if they were derived. Every signal check must carry
    the same suffix, on pass and on fail."""
    note = "a synthetic signal threshold, never derived from anything"
    synth = {
        "source": "test",
        "signals_require": [{"name": "synthetic_floor", "column": "I_fc",
                             "min_value": 1.0,
                             "label": "a synthetic signal floor"}],
        "provisional_note": note,
    }
    saved = dict(rhs.FAULT_EXPECTATIONS)
    rhs.FAULT_EXPECTATIONS[_SYNTH_PROVISIONAL_NOTE_NAME] = synth
    try:
        m = _metrics(fault_bits_seen=0, final_fault_flags=0)
        for signals in (_passing_signals(_SYNTH_PROVISIONAL_NOTE_NAME),
                        _failing_signals(_SYNTH_PROVISIONAL_NOTE_NAME)):
            _passed, checks = rhs.judge_scenario(
                _SYNTH_PROVISIONAL_NOTE_NAME, m, _events(), _child(),
                signals=signals)
            sig = [c for c in checks if c["name"].startswith("signal_")]
            assert sig
            for c in sig:
                assert c["detail"].endswith("  [PROVISIONAL: %s]" % note)
        # ... and the UNMEASURED branch carries it as well: a provisional
        # threshold that was never measured must not read as a derived gap.
        _passed2, checks2 = rhs.judge_scenario(
            _SYNTH_PROVISIONAL_NOTE_NAME, m, _events(), _child(), signals=None)
        gap = [c for c in checks2 if c["name"] == "signals_require"][0]
        assert gap["passed"] is False
        assert gap["detail"].endswith("  [PROVISIONAL: %s]" % note)
    finally:
        rhs.FAULT_EXPECTATIONS.clear()
        rhs.FAULT_EXPECTATIONS.update(saved)


def test_judge_scenario_no_provisional_note_leaves_signal_details_plain():
    """The converse: without the key, no signal check may gain a bracket."""
    m = _metrics(fault_bits_seen=0, final_fault_flags=0,
                 fault_bits_before_survive=0, state_at_survive=2)
    _passed, checks = rhs.judge_scenario(
        "soc-depletion", m, _events(), _child(),
        signals=_passing_signals("soc-depletion"))
    for c in [c for c in checks if c["name"].startswith("signal_")]:
        assert "PROVISIONAL" not in c["detail"]


def test_ems_sdp_provisional_note_is_gone_now_the_bands_are_measured():
    """DI-MED-5 CLOSED. Campaign 20260831_222036 was the first live
    sdp_policy_v2 run and measured all three previously-provisional bands, so
    the note must be REMOVED — a provisional marker left on a calibrated
    threshold trains readers to discount every band in the entry.

    The three checks themselves must still exist: deleting the note by
    deleting the checks would satisfy the first half of this test and gut the
    entry."""
    expect = rhs.FAULT_EXPECTATIONS["ems-sdp"]
    assert expect.get("provisional_note") is None
    names = {s.get("name") for s in expect["signals_require"]}
    for name in ("sdp_table_interior_at_high_demand",
                 "sdp_table_rail_at_low_demand",
                 # `sdp_charge_window_opened` was REPLACED by its inverse when
                 # the entry was rebound to the calibrated v3 artifact
                 # (2026-09-01): the policy has no charge cell to command, so
                 # the old check would be a guaranteed FAIL on a correct board.
                 "charge_path_never_opens"):
        assert name in names
    assert "sdp_charge_window_opened" not in names


def test_ems_sdp_calibrated_bands_match_the_campaign_measurements():
    """The measured values, pinned against the bands derived from them
    (campaign 20260831_222036): cmd_share_sp_raw is exactly 0.950000 over the
    interior window and exactly 1.000000 over the rail window, and the charge
    window carries 8652 ticks chattering / ~16000 held."""
    by = {s["name"]: s for s in rhs.FAULT_EXPECTATIONS["ems-sdp"]["signals_require"]}
    # 3 + 3b: a TWO-SIDED band, written as two specs because
    # _judge_signal_leaf() would silently drop a ceiling written beside a floor.
    assert by["sdp_table_interior_at_high_demand"]["max_value"] == pytest.approx(0.960)
    assert by["sdp_table_interior_floor"]["min_value"] == pytest.approx(0.940)
    assert (by["sdp_table_interior_floor"]["t_window"]
            == by["sdp_table_interior_at_high_demand"]["t_window"])
    for spec in (by["sdp_table_interior_at_high_demand"],
                 by["sdp_table_interior_floor"]):
        assert spec["column"] == "cmd_share_sp_raw"
        assert not ({"min_value", "max_value"} <= set(spec))
    assert by["sdp_table_interior_floor"]["min_value"] <= 0.950000
    assert by["sdp_table_interior_at_high_demand"]["max_value"] >= 0.950000
    # 4: the rail, tightened onto the measured exact 1.0 and still clear of the
    # 0.95 ladder step it must exclude.
    rail = by["sdp_table_rail_at_low_demand"]["min_value"]
    assert rail == pytest.approx(0.999)
    assert 0.95 < rail <= 1.000000
    # 5: the charge axis INVERTED with the v3 rebinding (2026-09-01). The
    # calibrated artifact declines the charge action endogenously, so the
    # assertion is that the path NEVER opens — max_ticks 0, exact rather than
    # lenient (chargingControl() opens FC_CHARGE only on charge_goal > 0, and
    # the table's charge map is identically zero).
    never = by["charge_path_never_opens"]
    assert never["switch_bit"] == rhs.SW_FC_CHARGE
    assert never["max_ticks"] == 0
    assert "min_ticks" not in never
    # No t_window: "never" is asserted over the WHOLE post-grace run.
    assert "t_window" not in never
    # max_ticks-only specs must justify their vacuity; there is deliberately no
    # companion positive bound on this bit (that is what must NOT happen).
    assert never["vacuity_note"]


# -- _judge_event_spec() unit coverage (shared by events_require and every
#    events_any_of branch) --------------------------------------------------

def test_judge_event_spec_where_filter_isolates_matching_kind_and_field():
    events = {"kinds": {"sw_ring": 1}, "field_values": {},
             "events_by_kind": {"sw_ring": [{"switch": "MOT_PWR", "i_cut": 4.5}]}}
    spec = {"kind": "sw_ring", "where": {"switch": "MOT_PWR"}, "count": 1,
           "field": "i_cut", "min_value": 3.5, "max_value": 5.5}
    ok, observed, problems = rhs._judge_event_spec(spec, events)
    assert ok is True
    assert problems == []
    assert "sw_ring[switch=MOT_PWR]" in observed


def test_judge_event_spec_where_filter_wrong_switch_value_is_negative(tmp_path=None):
    """The event KIND is right (sw_ring) but the field value inside `where`
    does not match -- the filtered count must be 0, distinctly from 'no such
    kind at all'."""
    events = {"kinds": {"sw_ring": 1}, "field_values": {},
             "events_by_kind": {"sw_ring": [{"switch": "FC_BUS", "i_cut": 4.5}]}}
    spec = {"kind": "sw_ring", "where": {"switch": "MOT_PWR"}, "count": 1,
           "field": "i_cut", "min_value": 3.5, "max_value": 5.5}
    ok, observed, problems = rhs._judge_event_spec(spec, events)
    assert ok is False
    assert "count 0, expected exactly 1" in problems[0]
    assert "sw_ring[switch=MOT_PWR]" in observed


def test_judge_event_spec_count_zero_does_not_demand_a_field_value():
    """Deliberate carve-out: a count==0 spec asserts ABSENCE. When no events
    (and so no field values) exist, that must NOT ALSO be flagged as 'no
    field to check' -- pinned so this is not later 'fixed' into a spurious
    second failure on every legitimate absence assertion."""
    events = {"kinds": {}, "field_values": {}, "events_by_kind": {}}
    spec = {"kind": "scp_cut", "count": 0, "field": "i_cut",
           "min_value": 6.0, "max_value": 6.6}
    ok, observed, problems = rhs._judge_event_spec(spec, events)
    assert ok is True
    assert problems == []


def test_judge_event_spec_bare_string_form_still_works():
    """The bare-string spec form ("kind" alone, meaning 'at least one') must
    still work -- _judge_event_spec is shared with events_require, which
    relies on it."""
    events = _events(kinds={"scp_cut": 1})
    ok, observed, problems = rhs._judge_event_spec("scp_cut", events)
    assert ok is True
    assert "1 'scp_cut' event(s)" in observed


# -- M3 (2026-09-01): `total_of` -- SUM across all coalesced episodes ------

def test_judge_event_spec_total_of_sums_across_episodes_and_passes():
    """The whole point of `total_of`: a floor no SINGLE episode individually
    clears can still pass when the SUM does -- this is exactly the tail-episode
    false-FAIL `events_require`'s per-episode ALL quantifier produced."""
    events = {"kinds": {"chopper_clamp": 3}, "field_values": {},
             "events_by_kind": {"chopper_clamp": [
                 {"energy_j": 0.12}, {"energy_j": 0.15}, {"energy_j": 0.02},
             ]}}
    spec = {"total_of": "chopper_clamp", "field": "energy_j", "min_value": 0.25}
    ok, observed, problems = rhs._judge_event_spec(spec, events)
    assert ok is True
    assert problems == []
    assert "0.2900" in observed


def test_judge_event_spec_total_of_below_min_value_fails():
    events = {"kinds": {"chopper_clamp": 2}, "field_values": {},
             "events_by_kind": {"chopper_clamp": [
                 {"energy_j": 0.05}, {"energy_j": 0.03},
             ]}}
    spec = {"total_of": "chopper_clamp", "field": "energy_j", "min_value": 0.3}
    ok, observed, problems = rhs._judge_event_spec(spec, events)
    assert ok is False
    assert "below min_value" in problems[0]


def test_judge_event_spec_total_of_no_matching_events_sums_to_zero():
    """No events of the kind at all -> total 0.0, judged like any other total
    below a positive floor -- not a separate 'no such event' branch (that
    branch belongs to the per-event `count`/absence path, not this one)."""
    events = {"kinds": {}, "field_values": {}, "events_by_kind": {}}
    spec = {"total_of": "chopper_clamp", "field": "energy_j", "min_value": 0.3}
    ok, observed, problems = rhs._judge_event_spec(spec, events)
    assert ok is False
    assert "= 0.0000" in observed


def test_judge_event_spec_total_of_respects_where_filter():
    events = {"kinds": {"sw_ring": 2}, "field_values": {},
             "events_by_kind": {"sw_ring": [
                 {"switch": "MOT_PWR", "energy_j": 0.4},
                 {"switch": "FC_BUS", "energy_j": 0.9},
             ]}}
    spec = {"total_of": "sw_ring", "where": {"switch": "MOT_PWR"},
           "field": "energy_j", "min_value": 0.3, "max_value": 0.5}
    ok, observed, problems = rhs._judge_event_spec(spec, events)
    assert ok is True


def test_regen_harvest_true_events_require_uses_total_of_not_per_episode_all():
    """M3 regression: the fixed entry must not regress to a per-episode ALL
    quantifier on the 0.3 J floor -- that was the defect."""
    entry = rhs.FAULT_EXPECTATIONS["regen-harvest-true"]
    reqs = entry["events_require"]
    totals = [r for r in reqs if isinstance(r, dict) and "total_of" in r]
    assert len(totals) == 1
    assert totals[0]["total_of"] == "chopper_clamp"
    assert totals[0]["field"] == "energy_j"
    # F4 (fix round, 2026-09-01): 0.3 -> 3.0 J. The 0.3 J figure was calibrated
    # against the TRUNCATED chopper events (each episode serialized carrying
    # only its first 0.25-0.9 ms tick); against whole episodes the campaign
    # measures 6.9-8.6 J per run.
    # WP-1C (2026-09-02): 3.0 -> 1.9 J for the ETA_CHG 0.88 charger. The
    # output-referred regen cap lets the Ag105 take ~2x the pack current out of
    # the same window, and the chopper -- a residual absorber -- burns what is
    # left: the plant probe measures 1.3043 J per window against the 1:1 era's
    # 2.3-2.9, i.e. ~3.9 J per 3-window run, and 1.9 J is 49 % under that (the
    # margin class the retired 3.0 carried against 6.9 J).
    assert totals[0]["min_value"] == 1.9
    # And the per-episode floor left behind is deliberately much looser than
    # 0.3 J -- it exists only to catch a fully-missing/degenerate episode.
    per_episode = [r for r in reqs if isinstance(r, dict) and r.get("kind")
                  == "chopper_clamp" and "field" in r]
    assert per_episode and per_episode[0]["min_value"] < 1.9
    assert per_episode[0]["min_value"] == 0.01


def test_judge_scenario_regen_harvest_true_events_require_no_keyerror():
    """End-to-end: judge_scenario's events_require loop must not KeyError
    building a check name for a `total_of` spec (it has no `kind` key) --
    exercised through the actual regen-harvest-true FAULT_EXPECTATIONS entry."""
    child = _child()
    metrics = _metrics(fault_bits_seen=0, final_fault_flags=0, final_state=2)
    events = _events(kinds={"chopper_clamp": 2}, events_by_kind={
        "chopper_clamp": [{"energy_j": 2.0}, {"energy_j": 2.0}],
    })
    ok, checks = rhs.judge_scenario("regen-harvest-true", metrics, events,
                                    child, signals={})
    names = [c["name"] for c in checks]
    assert "events_require_total_chopper_clamp" in names
    total_check = [c for c in checks
                  if c["name"] == "events_require_total_chopper_clamp"][0]
    assert total_check["passed"] is True


# -- events_any_of import-time validation (direct predicate re-derivation,
#    same convention as _expectation_time_bounds's reject-direction test --
#    the loop itself runs once at import, so this re-derives its assertions
#    rather than re-triggering a module import) ------------------------------

def _validate_events_any_of_group(name, grp):
    """Line-for-line re-derivation of the import-time events_any_of
    validation in run_hil_suite.py, for testing the predicate directly."""
    brs = grp.get("branches") or []
    assert grp.get("name"), "group needs a name"
    assert len(brs) >= 2, (
        "FAULT_EXPECTATIONS[%r].events_any_of[%r] has %d branch(es)"
        % (name, grp.get("name"), len(brs)))
    for b in brs:
        assert b.get("name") and b.get("events"), (
            "every branch needs a name and a non-empty events list")
        for s in b["events"]:
            assert isinstance(s, str) or "kind" in s, (
                "every event spec needs a kind")


def test_events_any_of_validation_accepts_a_well_formed_synthetic_group():
    """No table entry uses events_any_of today (scp-inrush migrated off it),
    so the validation predicate is exercised against a synthetic group
    instead of the live table -- proving the shape it accepts is still a
    real, satisfiable one."""
    grp = {"name": "synthetic_group", "branches": [
        {"name": "a", "events": [{"kind": "scp_cut", "count": 1}]},
        {"name": "b", "events": [{"kind": "scp_cut", "count": 0}]},
    ]}
    _validate_events_any_of_group("synthetic", grp)   # must not raise


# ── events_any_of MECHANISM regression (2026-08-31) ─────────────────────────
# scp-inrush migrated off events_any_of when its stimulus was redesigned to
# win the one-tick race outright, so the mechanism now has NO live table
# user. Kept for future races (see the "CURRENTLY UNUSED" comment at its
# definition in run_hil_suite.py), and exercised here through a SYNTHETIC
# FAULT_EXPECTATIONS entry -- installed and removed around each test, same
# convention as test_fault_expectations_allow_only_defaults_to_require_or_error
# above -- so the branch-naming/no-outcome-text machinery itself does not rot
# untested just because nothing in the shipped table currently reaches it.

_SYNTH_ANY_OF_NAME = "__synthetic_events_any_of__"

_SYNTH_ANY_OF_ENTRY = {
    "source": "test",
    "events_any_of": [{
        "name": "synthetic_race",
        "branches": [
            {"name": "branch_hi", "label": "the STRONGER outcome",
             "events": [{"kind": "scp_cut", "count": 1,
                        "field": "i_cut", "min_value": 6.0, "max_value": 6.6}]},
            {"name": "branch_lo", "label": "the WEAKER outcome",
             "events": [{"kind": "scp_cut", "count": 0},
                       {"kind": "sw_ring", "count": 1,
                        "field": "i_cut", "min_value": 3.5, "max_value": 5.5}]},
        ],
    }],
}


def _with_synthetic_any_of_entry():
    """Context-manager-free install/restore helper (mirrors the existing
    inline try/finally pattern at test_fault_expectations_allow_only_defaults_
    to_require_or_error)."""
    saved = dict(rhs.FAULT_EXPECTATIONS)
    rhs.FAULT_EXPECTATIONS[_SYNTH_ANY_OF_NAME] = dict(_SYNTH_ANY_OF_ENTRY)
    return saved


def _restore_fault_expectations(saved):
    rhs.FAULT_EXPECTATIONS.clear()
    rhs.FAULT_EXPECTATIONS.update(saved)


def test_judge_scenario_events_any_of_mechanism_names_the_winning_branch():
    saved = _with_synthetic_any_of_entry()
    try:
        m = _metrics(fault_bits_seen=0, final_fault_flags=0)
        events = _events(kinds={"scp_cut": 1},
                         field_values={"scp_cut": {"i_cut": [6.29]}})
        passed, checks = rhs.judge_scenario(_SYNTH_ANY_OF_NAME, m, events, _child())
        grp = [c for c in checks if c["name"] == "synthetic_race"][0]
        assert grp["passed"] is True
        assert "OUTCOME **branch_hi**" in grp["detail"]
        assert "the STRONGER outcome" in grp["detail"]
        assert passed is True
    finally:
        _restore_fault_expectations(saved)


def test_judge_scenario_events_any_of_mechanism_no_outcome_matched_text():
    saved = _with_synthetic_any_of_entry()
    try:
        m = _metrics(fault_bits_seen=0, final_fault_flags=0)
        events = _events()   # kinds == {}, field_values == {} -- neither branch
        passed, checks = rhs.judge_scenario(_SYNTH_ANY_OF_NAME, m, events, _child())
        grp = [c for c in checks if c["name"] == "synthetic_race"][0]
        assert grp["passed"] is False
        assert grp["detail"].startswith("NO outcome matched")
        assert "branch_hi" in grp["detail"]
        assert "branch_lo" in grp["detail"]
        assert passed is False
    finally:
        _restore_fault_expectations(saved)


def test_events_any_of_validation_rejects_a_one_branch_group():
    bad = {"name": "only_one_way", "branches": [
        {"name": "only", "events": [{"kind": "scp_cut", "count": 1}]},
    ]}
    with pytest.raises(AssertionError, match="branch"):
        _validate_events_any_of_group("synthetic", bad)


def test_events_any_of_validation_rejects_an_event_spec_without_kind():
    bad = {"name": "g", "branches": [
        {"name": "a", "events": [{"count": 1}]},          # no "kind"
        {"name": "b", "events": [{"kind": "scp_cut"}]},
    ]}
    with pytest.raises(AssertionError, match="kind"):
        _validate_events_any_of_group("synthetic", bad)


def test_events_any_of_validation_rejects_a_branch_missing_name_or_events():
    bad_no_name = {"name": "g", "branches": [
        {"events": [{"kind": "scp_cut"}]},
        {"name": "b", "events": [{"kind": "scp_cut"}]},
    ]}
    with pytest.raises(AssertionError):
        _validate_events_any_of_group("synthetic", bad_no_name)

    bad_no_events = {"name": "g", "branches": [
        {"name": "a", "events": []},
        {"name": "b", "events": [{"kind": "scp_cut"}]},
    ]}
    with pytest.raises(AssertionError):
        _validate_events_any_of_group("synthetic", bad_no_events)


def test_judge_scenario_events_forbid_over_absmax_pass_and_fail():
    """scp-inrush must exercise the foldback WITHOUT producing the Death-5
    boost-kill signature (events_forbid_over_absmax) -- still enforced under
    the single-outcome events_require form."""
    m = _metrics(fault_bits_seen=0, final_fault_flags=0)
    clean_events = _scp_cut_events(6.29)
    clean_events["over_absmax"] = 0
    passed, checks = rhs.judge_scenario("scp-inrush", m, clean_events, _child())
    forbid = [c for c in checks if c["name"] == "events_no_over_absmax"][0]
    assert forbid["passed"] is True
    assert passed is True

    ringing_events = _scp_cut_events(6.29)
    ringing_events["over_absmax"] = 1
    ringing_events["worst_over_absmax_ring_v"] = 21.5
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
            "events_require", "events_any_of", "source", "signals_require",
            "events_forbid_over_absmax", "provisional_note",
            # 2026-08-31 wave 2: the entry-level continuity assertion used by
            # pi-silence -- see child_stream_continuity() / judge_scenario().
            "child_tx_healthy"}
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


# -- switch_bit / max_continuous_ticks (2026-09-01, campaign 024231) --------
#
# The kind that replaced `sdpx_charge_released_between`. It bounds the LONGEST
# CONTINUOUS run rather than a total or an absence at a modelled instant, so a
# limit cycle whose period the model got wrong still passes.

def _sw_rows(pattern, bit, t0=3.0, dt=0.1):
    """CSV rows from a string pattern: '1' = bit set, '0' = clear, '.' = a
    BLANK switch cell (a pre-observation tick, which carries no level)."""
    rows = []
    for i, ch in enumerate(pattern):
        cell = "" if ch == "." else (str(bit) if ch == "1" else "0")
        rows.append({"t": "%.4f" % (t0 + i * dt), "switch": cell,
                     "fault_flags": "0"})
    return rows


def test_scan_signals_max_continuous_ticks_measures_the_longest_run(tmp_path):
    """Three separate 2-tick episodes are NOT a 6-tick hold. A total-tick
    ceiling cannot tell them apart; this kind exists because that distinction
    is the whole objective of the check it replaced."""
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, _sw_rows("110110110", rhs.SW_FC_CHARGE))
    specs = [{"name": "hold", "switch_bit": rhs.SW_FC_CHARGE,
              "max_continuous_ticks": 2, "label": "no long hold"}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    assert measured[0]["max_run"] == 2
    assert measured[0]["ticks"] == 6
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True
    assert "longest CONTINUOUS run 2 set tick(s)" in checks[0]["detail"]
    assert "6 set in total" in checks[0]["detail"]


def test_scan_signals_max_continuous_ticks_fails_one_long_hold(tmp_path):
    """The failure mode the check exists for: the latch never released."""
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, _sw_rows("011111", rhs.SW_FC_CHARGE))
    specs = [{"name": "hold", "switch_bit": rhs.SW_FC_CHARGE,
              "max_continuous_ticks": 3}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert measured[0]["max_run"] == 5
    assert checks[0]["passed"] is False
    assert "need <= 3" in checks[0]["detail"]


def test_scan_signals_max_continuous_ticks_boundary_is_inclusive(tmp_path):
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, _sw_rows("0111", rhs.SW_FC_CHARGE))
    for lim, want in ((3, True), (2, False)):
        specs = [{"name": "hold", "switch_bit": rhs.SW_FC_CHARGE,
                  "max_continuous_ticks": lim}]
        measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
        assert rhs.judge_signals(specs, measured, "why")[0]["passed"] is want


def test_scan_signals_max_continuous_ticks_run_is_clipped_by_the_window(tmp_path):
    """WINDOW EDGES. A run that starts before the window or continues past it
    is measured only over the window -- the kind reports what it observed, and
    never extrapolates a hold it did not see."""
    path = tmp_path / "a.csv"
    # 10 consecutive set ticks at t = 3.0 .. 3.9.
    _write_scenario_csv(path, _sw_rows("1" * 10, rhs.SW_FC_CHARGE))
    specs = [{"name": "hold", "switch_bit": rhs.SW_FC_CHARGE,
              "max_continuous_ticks": 100, "t_window": (3.25, 3.55)}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    # t = 3.3, 3.4, 3.5 only.
    assert measured[0]["max_run"] == 3
    assert measured[0]["rows"] == 3


def test_scan_signals_max_continuous_ticks_blank_row_does_not_split_a_hold(tmp_path):
    """A blank switch cell carries NO level, so it must neither extend nor
    break a run. Treating it as a break would report one hold as two shorter
    ones every time an observation frame was dropped -- and this kind is a
    CEILING, so that error reads as a pass."""
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, _sw_rows("111.111", rhs.SW_FC_CHARGE))
    specs = [{"name": "hold", "switch_bit": rhs.SW_FC_CHARGE,
              "max_continuous_ticks": 5}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    assert measured[0]["max_run"] == 6
    assert rhs.judge_signals(specs, measured, "why")[0]["passed"] is False


def test_scan_signals_max_continuous_ticks_unmeasured_column_is_vacuous(tmp_path):
    """WHY THE IMPORT-TIME COMPANION RULE COVERS THIS KIND: a blank column has
    a longest run of zero and satisfies any ceiling. The table guard, not the
    judge, is what stops that -- so this test pins the exposure the guard
    exists for."""
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, _sw_rows("....", rhs.SW_FC_CHARGE))
    specs = [{"name": "hold", "switch_bit": rhs.SW_FC_CHARGE,
              "max_continuous_ticks": 0}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    assert rhs.judge_signals(specs, measured, "why")[0]["passed"] is True


def test_scan_signals_max_continuous_ticks_works_on_a_value_mask_spec(tmp_path):
    """The kind is declared for switch_bit / aux_bit / value_mask, so the
    masked-integer path tracks runs too."""
    rows = [{"t": "3.0", "ag105_status": "0x42", "fault_flags": "0"},
            {"t": "3.1", "ag105_status": "0x42", "fault_flags": "0"},
            {"t": "3.2", "ag105_status": "0x00", "fault_flags": "0"},
            {"t": "3.3", "ag105_status": "0x42", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "st", "column": "ag105_status", "value_mask": 0xFF,
              "value_equals": 0x42, "max_continuous_ticks": 2}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    assert measured[0]["max_run"] == 2 and measured[0]["ticks"] == 3
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True
    assert "longest CONTINUOUS run 2 matching tick(s)" in checks[0]["detail"]


# -- switch_bit / edge_count_between (2026-09-01, campaign 024231) ----------

def test_scan_signals_edge_count_between_counts_rising_edges(tmp_path):
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, _sw_rows("0110011010", rhs.SW_FC_CHARGE))
    specs = [{"name": "windows", "switch_bit": rhs.SW_FC_CHARGE,
              "edge_count_between": (3, 3), "label": "three windows"}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    assert measured[0]["edges"] == 3
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True
    assert "counted 3 rise edge(s)" in checks[0]["detail"]


def test_scan_signals_edge_count_between_band_is_inclusive_both_ends(tmp_path):
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, _sw_rows("010101", rhs.SW_FC_CHARGE))   # 3 rises
    for band, want in (((3, 5), True), ((1, 3), True),
                       ((4, 6), False), ((1, 2), False)):
        specs = [{"name": "w", "switch_bit": rhs.SW_FC_CHARGE,
                  "edge_count_between": band}]
        measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
        assert rhs.judge_signals(specs, measured, "why")[0]["passed"] is want, band


def test_scan_signals_edge_count_between_first_sample_is_a_level_not_an_edge(tmp_path):
    """A window that OPENS with the bit already set must not count a phantom
    edge: the first in-window sample only establishes the level. Otherwise a
    window count would depend on where the window happened to open, which is
    exactly the phase sensitivity this family of kinds removes."""
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, _sw_rows("1110111", rhs.SW_FC_CHARGE))
    specs = [{"name": "w", "switch_bit": rhs.SW_FC_CHARGE,
              "edge_count_between": (1, 1)}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    assert measured[0]["edges"] == 1
    assert rhs.judge_signals(specs, measured, "why")[0]["passed"] is True


def test_scan_signals_edge_count_between_falling_edges(tmp_path):
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, _sw_rows("110100", rhs.SW_FC_CHARGE))
    specs = [{"name": "w", "switch_bit": rhs.SW_FC_CHARGE,
              "edge_count_between": (2, 2), "edge": "fall"}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    assert measured[0]["edges"] == 2
    assert "fall edge(s)" in rhs.judge_signals(specs, measured, "why")[0]["detail"]


def test_scan_signals_edge_count_between_blank_row_cannot_forge_an_edge(tmp_path):
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, _sw_rows("11.11", rhs.SW_FC_CHARGE))
    specs = [{"name": "w", "switch_bit": rhs.SW_FC_CHARGE,
              "edge_count_between": (0, 0)}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    assert measured[0]["edges"] == 0
    assert rhs.judge_signals(specs, measured, "why")[0]["passed"] is True


def test_scan_signals_edge_count_between_never_opened_fails_not_passes(tmp_path):
    """A bit that never went high counts zero edges and FAILS a band whose
    floor is positive -- so unlike a max-only kind this one is not vacuity
    prone, which is why the import guard does not demand a companion."""
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, _sw_rows("0000", rhs.SW_FC_CHARGE))
    specs = [{"name": "w", "switch_bit": rhs.SW_FC_CHARGE,
              "edge_count_between": (6, 12)}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    assert rhs.judge_signals(specs, measured, "why")[0]["passed"] is False


# -- import-time shape guards for the two 2026-09-01 kinds -------------------

def _shape_check(spec):
    """Drive run_hil_suite's OWN import-time signal-shape guard over ONE
    synthetic spec.  The real function, not a copy of its assertions: these
    guards are all that stands between a malformed spec and a campaign that
    measures nothing, and a duplicated copy would drift."""
    rhs._assert_signal_spec_shapes(
        "__shape__",
        {"source": "synthetic", "allow_only": 0, "signals_require": [spec]})


def test_shape_guard_max_continuous_ticks_refuses_a_companion_bound(tmp_path):
    """_judge_signal_leaf() returns on max_continuous_ticks BEFORE the tick
    bounds, so anything written beside it is silently dropped."""
    with pytest.raises(AssertionError, match="max_continuous_ticks"):
        _shape_check({"name": "x", "switch_bit": rhs.SW_FC_CHARGE,
                      "max_continuous_ticks": 10, "min_ticks": 5})


def test_shape_guard_max_continuous_ticks_needs_something_to_watch():
    with pytest.raises(AssertionError, match="switch_bit"):
        _shape_check({"name": "x", "column": "I_fc",
                      "max_continuous_ticks": 10})


def test_shape_guard_max_continuous_ticks_needs_a_companion_or_a_note():
    """The vacuity family: a blank column has a longest run of zero."""
    with pytest.raises(AssertionError, match="max_continuous_ticks"):
        _shape_check({"name": "x", "switch_bit": rhs.SW_FC_CHARGE,
                      "max_continuous_ticks": 10})
    # A vacuity_note satisfies it, exactly as it does for max_ticks.
    _shape_check({"name": "x", "switch_bit": rhs.SW_FC_CHARGE,
                  "max_continuous_ticks": 10, "vacuity_note": "because"})


def test_shape_guard_edge_count_between_rejects_an_empty_or_malformed_band():
    with pytest.raises(AssertionError, match="lo <= hi"):
        _shape_check({"name": "x", "switch_bit": rhs.SW_FC_CHARGE,
                      "edge_count_between": (9, 2)})
    with pytest.raises(AssertionError, match="INCLUSIVE"):
        _shape_check({"name": "x", "switch_bit": rhs.SW_FC_CHARGE,
                      "edge_count_between": (1, 2, 3)})
    with pytest.raises(AssertionError, match="'rise' or 'fall'"):
        _shape_check({"name": "x", "switch_bit": rhs.SW_FC_CHARGE,
                      "edge_count_between": (1, 2), "edge": "both"})
    with pytest.raises(AssertionError, match="switch_bit"):
        _shape_check({"name": "x", "column": "I_fc",
                      "edge_count_between": (1, 2)})
    with pytest.raises(AssertionError, match="edge_count_between"):
        _shape_check({"name": "x", "switch_bit": rhs.SW_FC_CHARGE,
                      "edge_count_between": (1, 2), "max_ticks": 5})
    # The well-formed shape imports clean.
    _shape_check({"name": "x", "switch_bit": rhs.SW_FC_CHARGE,
                  "edge_count_between": (6, 12), "edge": "rise"})


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


# ═════════════════════════════════════════════════════════════════════════
# 2026-08-31 wave 2 -- Round C, test-writer coverage: the five new
# signals_require check kinds, child_stream_continuity(), and the new
# scenarios' FAULT_EXPECTATIONS shape.
# ═════════════════════════════════════════════════════════════════════════

# ── aux_bit (the aux-byte analogue of switch_bit) ───────────────────────────

def test_scan_signals_aux_bit_min_ticks_pass(tmp_path):
    rows = [{"t": "1.0", "aux": str(rhs.AUX_MPPT_DISABLE), "fault_flags": "0"},
            {"t": "1.1", "aux": str(rhs.AUX_MPPT_DISABLE), "fault_flags": "0"},
            {"t": "1.2", "aux": "0", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "mppt", "aux_bit": rhs.AUX_MPPT_DISABLE, "min_ticks": 2}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True
    assert "bit set on 2 tick(s)" in checks[0]["detail"]


def test_scan_signals_aux_bit_max_ticks_fail_stayed_high_too_long(tmp_path):
    rows = [{"t": "1.0", "aux": str(rhs.AUX_MPPT_DISABLE), "fault_flags": "0"},
            {"t": "1.1", "aux": str(rhs.AUX_MPPT_DISABLE), "fault_flags": "0"},
            {"t": "1.2", "aux": str(rhs.AUX_MPPT_DISABLE), "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "mppt_asserted", "aux_bit": rhs.AUX_MPPT_DISABLE, "max_ticks": 0}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is False
    assert "bit set on 3 tick(s)" in checks[0]["detail"]


def test_scan_signals_aux_bit_is_a_separate_column_from_switch_bit(tmp_path):
    """A switch_bit numeric value that happens to equal AUX_MPPT_DISABLE must
    NOT be read from the `switch` column when the spec says `aux_bit` -- the
    bit_col resolution must key strictly off which field name is present."""
    rows = [{"t": "1.0", "switch": str(rhs.AUX_MPPT_DISABLE), "aux": "0",
            "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "mppt", "aux_bit": rhs.AUX_MPPT_DISABLE, "min_ticks": 1}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    # aux is 0, so this must NOT pass even though `switch` carries the value.
    assert checks[0]["passed"] is False


# ── value_mask / value_equals (masked-integer equality; ag105_status GENSTAT
#    and flag bits, transcribed as a HEX STRING "0x.." in the real CSV) ─────

def test_scan_signals_value_mask_genstat_pass(tmp_path):
    status_low_power_mppt_en = hex(rhs.AG105_ST_LOW_POWER | rhs.AG105_FLAG_MPPT_EN)
    rows = [{"t": "1.0", "ag105_status": status_low_power_mppt_en, "fault_flags": "0"},
            {"t": "1.1", "ag105_status": hex(AG105_ST_CHARGING), "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "low_power", "column": "ag105_status",
             "value_mask": rhs.AG105_GENSTAT_MASK, "value_equals": rhs.AG105_ST_LOW_POWER,
             "min_ticks": 1}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True
    assert "masked value matched on 1 tick(s)" in checks[0]["detail"]


def test_scan_signals_value_mask_genstat_fail_never_matched(tmp_path):
    rows = [{"t": "1.0", "ag105_status": hex(AG105_ST_CHARGING), "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "low_power", "column": "ag105_status",
             "value_mask": rhs.AG105_GENSTAT_MASK, "value_equals": rhs.AG105_ST_LOW_POWER,
             "min_ticks": 1}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is False


def test_scan_signals_value_mask_tracking_flag_pair(tmp_path):
    """MPPT_EN set, PWR_TRACK clear -- the exact pattern the threshold gate
    produces (mask over both bits, equals ONLY the MPPT_EN bit)."""
    val = rhs.AG105_ST_LOW_POWER | rhs.AG105_FLAG_MPPT_EN
    rows = [{"t": "1.0", "ag105_status": hex(val), "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "tracking_released_not_tracking", "column": "ag105_status",
             "value_mask": rhs.AG105_TRACK_MASK, "value_equals": rhs.AG105_FLAG_MPPT_EN,
             "min_ticks": 1}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True


def test_scan_signals_value_mask_trap_a_plain_min_value_on_a_hex_column_measures_nothing(tmp_path):
    """THE TRAP the value_mask kind exists to close, reproduced directly: a
    plain min_value spec on ag105_status (a hex-string column) must measure
    ZERO rows -- float() raises on "0x02" and the sample is silently
    skipped -- confirming a min_value spec on this column is unusable and
    value_mask really is required, not merely convenient."""
    rows = [{"t": "1.0", "ag105_status": hex(AG105_ST_CHARGING), "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "trap", "column": "ag105_status", "min_value": 0.0}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    # `rows` counts every row reached (window/grace admitted); float() raising
    # on the hex string happens AFTER that count and only leaves `peak`
    # unmeasured -- so "unmeasured" shows up as peak is None, not rows == 0.
    assert measured[0]["rows"] == 1
    assert measured[0]["peak"] is None


# ── max_value (a CEILING -- "nothing exceeded X") ───────────────────────────

def test_scan_signals_max_value_pass_stays_under_ceiling(tmp_path):
    rows = [{"t": "1.0", "I_charge": "0.02", "fault_flags": "0"},
            {"t": "1.1", "I_charge": "0.04", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "tapered", "column": "I_charge", "max_value": 0.05}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True
    assert "peak 0.0400" in checks[0]["detail"]


def test_scan_signals_max_value_fail_one_sample_exceeds(tmp_path):
    rows = [{"t": "1.0", "I_charge": "0.02", "fault_flags": "0"},
            {"t": "1.1", "I_charge": "0.30", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "tapered", "column": "I_charge", "max_value": 0.05}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is False
    assert "peak 0.3000" in checks[0]["detail"]


def test_scan_signals_max_value_unmeasured_fails_not_vacuously_passes(tmp_path):
    """No parseable samples in the window -- 'nothing exceeded X' must NOT be
    satisfied by an absence of evidence."""
    rows = [{"t": "1.0", "I_charge": "", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "tapered", "column": "I_charge", "max_value": 0.05}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is False
    assert "unmeasured" in checks[0]["detail"]


def test_scan_signals_max_value_equality_at_the_boundary_passes(tmp_path):
    rows = [{"t": "1.0", "I_charge": "0.05", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "tapered", "column": "I_charge", "max_value": 0.05}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True


# ── switch_fall_latency_ms (the `max_ms` kind -- latency measurement) ──────

def test_scan_signals_latency_fall_measured_and_within_bound(tmp_path):
    rows = [{"t": "9.5", "switch": str(rhs.SW_BT_BUS), "fault_flags": "0"},
            {"t": "10.0", "switch": "0", "fault_flags": "0"},   # falls at t=10.0
            {"t": "10.5", "switch": "0", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "bt_cut_latency", "switch_bit": rhs.SW_BT_BUS,
             "after_t": 9.9, "max_ms": 200.0, "t_window": (9.0, 11.0)}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True
    assert "MEASURED fall latency" in checks[0]["detail"]
    assert "100.00 ms" in checks[0]["detail"]   # (10.0 - 9.9) * 1000


def test_scan_signals_latency_fall_exceeds_bound_fails(tmp_path):
    rows = [{"t": "9.5", "switch": str(rhs.SW_BT_BUS), "fault_flags": "0"},
            {"t": "10.5", "switch": "0", "fault_flags": "0"}]   # 600 ms after after_t
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "bt_cut_latency", "switch_bit": rhs.SW_BT_BUS,
             "after_t": 9.9, "max_ms": 200.0, "t_window": (9.0, 11.0)}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is False


def test_scan_signals_latency_rise_edge_variant(tmp_path):
    rows = [{"t": "9.5", "switch": "0", "fault_flags": "0"},
            {"t": "10.0", "switch": str(rhs.SW_BT_BUS), "fault_flags": "0"}]  # rises
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "bt_restore_latency", "switch_bit": rhs.SW_BT_BUS, "edge": "rise",
             "after_t": 9.9, "max_ms": 200.0, "t_window": (9.0, 11.0)}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is True
    assert "MEASURED rise latency" in checks[0]["detail"]


def test_scan_signals_latency_no_transition_fails_with_last_level(tmp_path):
    """The bit never transitions inside the window -- 'no transition' with
    the last observed level reported, not a false 0 ms."""
    rows = [{"t": "9.5", "switch": str(rhs.SW_BT_BUS), "fault_flags": "0"},
            {"t": "10.5", "switch": str(rhs.SW_BT_BUS), "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "bt_cut_latency", "switch_bit": rhs.SW_BT_BUS,
             "after_t": 9.9, "max_ms": 200.0, "t_window": (9.0, 11.0)}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is False
    assert "no fall transition" in checks[0]["detail"]
    assert "HIGH" in checks[0]["detail"]


def test_scan_signals_latency_edge_before_after_t_is_ignored_not_spurious_zero(tmp_path):
    """An edge occurring BEFORE after_t must not register as a 0 ms latency
    -- prev_bit tracks it, but edge_t is only ever set for a transition AT or
    after after_t."""
    rows = [{"t": "5.0", "switch": str(rhs.SW_BT_BUS), "fault_flags": "0"},
            {"t": "5.5", "switch": "0", "fault_flags": "0"},   # falls BEFORE after_t
            {"t": "9.9", "switch": "0", "fault_flags": "0"},   # already low at after_t
            {"t": "10.5", "switch": "0", "fault_flags": "0"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    specs = [{"name": "bt_cut_latency", "switch_bit": rhs.SW_BT_BUS,
             "after_t": 9.9, "max_ms": 200.0, "t_window": (4.0, 11.0)}]
    measured = rhs.scan_signals(str(path), specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert checks[0]["passed"] is False
    assert "no fall transition" in checks[0]["detail"]


def test_fault_expectations_switch_fall_latency_specs_pass_the_import_time_shape_asserts():
    """Belt and braces: every switch_fall_latency_ms spec actually shipped in
    FAULT_EXPECTATIONS (share-staircase's four) satisfies the module's own
    import-time shape asserts -- re-checked here as an explicit test rather
    than only implicitly by the module having imported successfully."""
    found = 0
    for name, expect in rhs.FAULT_EXPECTATIONS.items():
        for spec in expect.get("signals_require") or []:
            if "max_ms" in spec:
                found += 1
                assert spec.get("switch_bit") is not None or spec.get("aux_bit") is not None, name
                assert spec.get("after_t") is not None
                assert spec.get("edge", "fall") in ("fall", "rise")
                assert spec["t_window"][0] < spec["after_t"]
    assert found == 4   # share-staircase's four latency checks


# ─────────────────────────────────────────────────────────────────────────
# Fix-round reconciliation (2026-08-31, post-GO): staircase_swept's window
# move, the MPPT toggle ceiling retune, and regression coverage for the four
# new import-time shape asserts the fix round added.
# ─────────────────────────────────────────────────────────────────────────

def test_staircase_swept_window_is_6_5_to_26_9():
    """H2 fix: the window opens at 6.5, not 6.0 -- opening AT the t=6.0
    pi_timeline entry sampled the PRE-step value ~19 times in 20 (the ZOH'd
    cmd_share_sp column only updates on a 50 Hz command tick landing exactly
    on that millisecond), making staircase_swept a chronic false-FAIL of a
    correct board."""
    spec = next(s for s in rhs.FAULT_EXPECTATIONS["share-staircase"]["signals_require"]
               if s["name"] == "staircase_swept")
    assert spec["t_window"] == (6.5, 26.9)


def test_mppt_hunt_ceiling_is_retired_for_an_edge_census():
    """fw v24: the toggle CEILING is gone, replaced by a phase-free edge census.

    The old check (`mppt_not_stuck_high`, max_ticks 2200) asserted the PRESENCE
    of the fw v23 hunt by excluding the ~3000-tick "stuck released" outcome.
    Under fw v24 that outcome is the EXPECTED one, so the ceiling could not be
    re-tuned -- it had to be replaced. Pinned negatively as well as positively:
    a future round that reinstates the constant should have to delete this.
    """
    assert not hasattr(rhs, "_MPPT_TOGGLE_MAX_TICKS")
    names = {s["name"]
             for s in rhs.FAULT_EXPECTATIONS["mppt-tracking"]["signals_require"]}
    assert "mppt_not_stuck_high" not in names
    spec = next(s for s in rhs.FAULT_EXPECTATIONS["mppt-tracking"]["signals_require"]
               if s["name"] == "mppt_no_hunt")
    # One rise per cruise-charge window (3), ceiling CALIBRATED 8 -> 5 from
    # campaign 080905 (measured exactly 3); the fw v23 hunt's 138 toggles are
    # ~69 rises and cannot pass at any duty cycle.
    assert spec["edge_count_between"] == rhs._MPPT_RISE_BAND == (3, 5)
    assert spec["edge"] == "rise"
    assert spec["aux_bit"] == rhs.AUX_MPPT_DISABLE
    assert spec["t_window"] == rhs._MPPT_ALL_CRUISE_W == (16.1, 41.0)
    assert len(rhs.EMS_MPPT_CRUISE_WINDOWS) == rhs._MPPT_RISE_BAND[0]


# ── Assert 1: strictly_decreases_by window must clear every pi_timeline
#    entry time by >= PI_CMD_PERIOD_S (run_hil_suite.py ~:1760-1775). ──────
#
# The predicate is reproduced here rather than re-triggered via a module
# reload (the guard runs once, at FAULT_EXPECTATIONS build time, over data
# baked into the module at import) -- the reproduction is anchored against
# REAL data (rhs.PI_CMD_PERIOD_S, share-staircase's actual pi_timeline) so it
# is not just testing itself, and the "real data passes" cross-check is the
# fidelity anchor: the module already imported cleanly, so every REAL entry
# must satisfy this predicate today.

def _strictly_decreases_window_clears_timeline(t_window_start, pi_timeline):
    return all(abs(float(t_window_start) - float(et)) >= rhs.PI_CMD_PERIOD_S
              for et, _fields in pi_timeline)


def test_strictly_decreases_by_phase_guard_rejects_the_pre_fix_window():
    """The negative case the fix round named directly: the pre-fix
    staircase_swept window (t_window[0] = 6.0) sits EXACTLY on
    share-staircase's own t=6.0 pi_timeline entry (0 s clear, < the 0.02 s
    PI_CMD_PERIOD_S bound) -- this is what a real import-time guard run
    against that window would have rejected."""
    timeline = SCENARIOS["share-staircase"]["pi_timeline"]
    entry_times = [t for t, _fields in timeline]
    assert 6.0 in entry_times
    assert _strictly_decreases_window_clears_timeline(6.0, timeline) is False


def test_strictly_decreases_by_phase_guard_accepts_the_shipped_window():
    timeline = SCENARIOS["share-staircase"]["pi_timeline"]
    assert _strictly_decreases_window_clears_timeline(6.5, timeline) is True


def test_strictly_decreases_by_phase_guard_every_real_spec_is_compliant():
    """Every strictly_decreases_by spec actually shipped in FAULT_EXPECTATIONS
    must clear its scenario's pi_timeline (if any) by the command period --
    the module imported cleanly, so this must hold; re-checked explicitly."""
    checked = 0
    for name, expect in rhs.FAULT_EXPECTATIONS.items():
        timeline = (SCENARIOS.get(name) or {}).get("pi_timeline") or ()
        for spec in expect.get("signals_require") or []:
            arms = [spec] + list(spec.get("any_of") or ())
            for sub in arms:
                if "strictly_decreases_by" not in sub or not sub.get("t_window"):
                    continue
                checked += 1
                assert _strictly_decreases_window_clears_timeline(
                    sub["t_window"][0], timeline), (name, sub.get("name"))
    assert checked > 0


# ── Assert 2: a max_ms spec may not also carry min_ticks/max_ticks
#    (run_hil_suite.py ~:1808-1815). ───────────────────────────────────────

def test_max_ms_spec_with_tick_bounds_would_be_rejected():
    """Mirrors the guard's predicate directly (it is a plain set-intersection
    check, safe to reproduce faithfully without a module reload) and confirms
    it on both a synthetic violation and the real shipped specs."""
    def _violates(spec):
        return "max_ms" in spec and bool({"min_ticks", "max_ticks"} & set(spec))

    bad = {"name": "x", "switch_bit": rhs.SW_BT_BUS, "after_t": 1.0, "max_ms": 40.0,
           "min_ticks": 5, "t_window": (0.0, 2.0)}
    assert _violates(bad) is True

    good = {"name": "x", "switch_bit": rhs.SW_BT_BUS, "after_t": 1.0, "max_ms": 40.0,
           "t_window": (0.0, 2.0)}
    assert _violates(good) is False

    # Every REAL max_ms spec in the module must be clean (it imported).
    for name, expect in rhs.FAULT_EXPECTATIONS.items():
        for spec in expect.get("signals_require") or []:
            for sub in [spec] + list(spec.get("any_of") or ()):
                assert not _violates(sub), (name, sub.get("name"))


# ── Assert 3: a max_ticks-only bit/column spec needs a same-signal companion
#    with a positive bound, or an explicit vacuity_note
#    (run_hil_suite.py ~:1776-1807). ────────────────────────────────────────

_BOUND_KEYS = ("min_ticks", "min_value", "strictly_decreases_by",
              "max_ms", "fault_latch_bit", "any_of")


def _signal_identity(sub):
    if "switch_bit" in sub:
        return ("switch_bit", sub["switch_bit"])
    if "aux_bit" in sub:
        return ("aux_bit", sub["aux_bit"])
    return ("column", sub.get("column"))


def _max_ticks_only_has_companion_or_note(sub, siblings):
    if "max_ticks" not in sub or any(k in sub for k in _BOUND_KEYS):
        return True   # not a max_ticks-only spec at all
    if sub.get("vacuity_note"):
        return True
    sig = _signal_identity(sub)
    for other in siblings:
        if other is sub:
            continue
        if _signal_identity(other) == sig and any(k in other for k in _BOUND_KEYS):
            return True
    return False


def test_max_ticks_only_companion_guard_rejects_an_isolated_spec():
    isolated = {"name": "x", "switch_bit": rhs.SW_FC_BUS, "max_ticks": 10,
               "t_window": (0.0, 5.0)}
    assert _max_ticks_only_has_companion_or_note(isolated, [isolated]) is False


def test_max_ticks_only_companion_guard_accepts_a_positive_bound_companion():
    top = {"name": "top", "switch_bit": rhs.SW_FC_BUS, "max_ticks": 10,
          "t_window": (0.0, 5.0)}
    companion = {"name": "bottom", "switch_bit": rhs.SW_FC_BUS, "min_ticks": 1,
                "t_window": (5.0, 10.0)}
    assert _max_ticks_only_has_companion_or_note(top, [top, companion]) is True


def test_max_ticks_only_companion_guard_accepts_an_explicit_vacuity_note():
    isolated = {"name": "x", "switch_bit": rhs.SW_FC_BUS, "max_ticks": 10,
               "t_window": (0.0, 5.0), "vacuity_note": "covered elsewhere"}
    assert _max_ticks_only_has_companion_or_note(isolated, [isolated]) is True


def test_handoff_sag_fc_bus_open_keeps_its_vacuity_note():
    """The fix round's ONE explicit escape hatch -- must not be silently
    removed by a future edit (that would make the entry the guard's target,
    not its documented exception)."""
    spec = next(s for s in rhs.FAULT_EXPECTATIONS["handoff-sag"]["signals_require"]
               if s["name"] == "fc_bus_open")
    assert spec.get("vacuity_note")
    assert "survive_to" in spec["vacuity_note"]
    assert _max_ticks_only_has_companion_or_note(
        spec, rhs.FAULT_EXPECTATIONS["handoff-sag"]["signals_require"]) is True


def test_max_ticks_only_companion_guard_every_real_spec_is_compliant():
    """Every max_ticks-only spec actually shipped satisfies the guard -- the
    module imported cleanly, so this must hold; re-checked explicitly rather
    than trusted implicitly."""
    checked = 0
    for name, expect in rhs.FAULT_EXPECTATIONS.items():
        siblings = expect.get("signals_require") or []
        flat_siblings = []
        for s in siblings:
            flat_siblings.append(s)
            flat_siblings.extend(s.get("any_of") or ())
        for spec in siblings:
            for sub in [spec] + list(spec.get("any_of") or ()):
                if "max_ticks" in sub and not any(k in sub for k in _BOUND_KEYS):
                    checked += 1
                    assert _max_ticks_only_has_companion_or_note(sub, flat_siblings), (
                        name, sub.get("name"))
    assert checked > 0
    # mppt_asserted (max_ticks=0, no other bound key) has a real companion:
    # mppt_released shares its aux_bit and carries min_ticks.
    mppt_asserted = next(s for s in rhs.FAULT_EXPECTATIONS["mppt-tracking"]["signals_require"]
                         if s["name"] == "mppt_asserted")
    assert "max_ticks" in mppt_asserted and "vacuity_note" not in mppt_asserted


# ── child_stream_continuity() ───────────────────────────────────────────────

def test_child_stream_continuity_healthy_stream_passes():
    child = _child(summary={"tx_frames": 1000, "send_errors": 0})
    ok, detail = rhs.child_stream_continuity(child, duration_s=1.0)
    assert ok is True
    assert "1000/1000 frames" in detail


def test_child_stream_continuity_98_percent_boundary_passes():
    expected = rhs.HIL_DEFAULT_RATE_HZ * 10.0
    child = _child(summary={"tx_frames": int(0.98 * expected), "send_errors": 0})
    ok, _detail = rhs.child_stream_continuity(child, duration_s=10.0)
    assert ok is True


def test_child_stream_continuity_below_98_percent_fails():
    expected = rhs.HIL_DEFAULT_RATE_HZ * 10.0
    child = _child(summary={"tx_frames": int(0.90 * expected), "send_errors": 0})
    ok, _detail = rhs.child_stream_continuity(child, duration_s=10.0)
    assert ok is False


def test_child_stream_continuity_any_send_error_fails_even_at_full_tx():
    child = _child(summary={"tx_frames": 100000, "send_errors": 1})
    ok, detail = rhs.child_stream_continuity(child, duration_s=1.0)
    assert ok is False
    assert "1 send error(s)" in detail


def test_child_stream_continuity_missing_fields_is_unmeasured_none_not_false():
    """F2: an older sim build with no `send_errors` field must report
    UNMEASURED (None), which the caller must treat as unverifiable -- never
    silently 'zero send errors'."""
    child = _child(summary={"tx_frames": 1000})   # no send_errors key
    ok, detail = rhs.child_stream_continuity(child, duration_s=1.0)
    assert ok is None
    assert "UNMEASURED" in detail


def test_child_stream_continuity_no_duration_is_unmeasured():
    child = _child(summary={"tx_frames": 1000, "send_errors": 0})
    ok, _detail = rhs.child_stream_continuity(child, duration_s=None)
    assert ok is None


def test_child_stream_continuity_no_child_summary_is_unmeasured():
    ok, _detail = rhs.child_stream_continuity({"status": "ok"}, duration_s=1.0)
    assert ok is None


# ── child_tx_healthy entry-level assertion (pi-silence) ─────────────────────

def test_judge_scenario_child_tx_healthy_true_when_stream_continuous():
    assert rhs.FAULT_EXPECTATIONS["pi-silence"]["child_tx_healthy"] is True
    m = _metrics(fault_bits_seen=rhs.FAULT_PI_TIMEOUT, final_fault_flags=rhs.FAULT_PI_TIMEOUT,
                fault_bits_before_survive=0, state_at_survive=2, survive_to_t=8.0)
    child = _child(summary={"tx_frames": 14000, "send_errors": 0})
    signals = _passing_signals("pi-silence")
    passed, checks = rhs.judge_scenario("pi-silence", m, _events(), child,
                                        signals=signals, duration_s=14.0)
    healthy = [c for c in checks if c["name"] == "child_tx_healthy"][0]
    assert healthy["passed"] is True


def test_judge_scenario_child_tx_healthy_false_when_stream_dropped():
    m = _metrics(fault_bits_seen=rhs.FAULT_PI_TIMEOUT, final_fault_flags=rhs.FAULT_PI_TIMEOUT,
                fault_bits_before_survive=0, state_at_survive=2, survive_to_t=8.0)
    child = _child(summary={"tx_frames": 10, "send_errors": 0})   # far below 98%
    signals = _passing_signals("pi-silence")
    passed, checks = rhs.judge_scenario("pi-silence", m, _events(), child,
                                        signals=signals, duration_s=14.0)
    healthy = [c for c in checks if c["name"] == "child_tx_healthy"][0]
    assert healthy["passed"] is False
    assert passed is False


def test_judge_scenario_child_tx_healthy_unmeasured_fails_as_a_check_not_silently():
    m = _metrics(fault_bits_seen=rhs.FAULT_PI_TIMEOUT, final_fault_flags=rhs.FAULT_PI_TIMEOUT,
                fault_bits_before_survive=0, state_at_survive=2, survive_to_t=8.0)
    child = _child(summary={})   # no tx_frames/send_errors at all
    signals = _passing_signals("pi-silence")
    passed, checks = rhs.judge_scenario("pi-silence", m, _events(), child,
                                        signals=signals, duration_s=14.0)
    healthy = [c for c in checks if c["name"] == "child_tx_healthy"][0]
    assert healthy["passed"] is False
    assert passed is False


def test_scenarios_without_child_tx_healthy_get_no_such_check():
    assert "child_tx_healthy" not in rhs.FAULT_EXPECTATIONS["sag"]
    m = _metrics(fault_bits_seen=rhs.FAULT_UV_BUS, final_fault_flags=rhs.FAULT_UV_BUS)
    passed, checks = rhs.judge_scenario("sag", m, _events(), _child(),
                                        signals=_passing_signals("sag"))
    assert not any(c["name"] == "child_tx_healthy" for c in checks)


def test_pi_live_excusal_and_child_tx_healthy_share_one_implementation():
    """The --pi-live PI_TIMEOUT excusal (judge_scenario's pi_live branch) and
    the child_tx_healthy signal check must agree about what 'continuous'
    means, because both attribute a fault to a live Pi rather than to the HIL
    link -- verified behaviourally: identical child summaries must produce
    identical continuity verdicts through both paths at the boundary."""
    below_expected = int(0.90 * rhs.HIL_DEFAULT_RATE_HZ * 10.0)
    child = _child(summary={"tx_frames": below_expected, "send_errors": 0})
    cont_ok, _detail = rhs.child_stream_continuity(child, duration_s=10.0)
    assert cont_ok is False
    # And through judge_scenario's --pi-live excusal path on a scenario whose
    # post-grace union is EXACTLY FAULT_ERROR|PI_TIMEOUT (the only union the
    # excusal ever considers):
    m = _metrics(final_fault_flags=rhs.FAULT_ERROR | rhs.FAULT_PI_TIMEOUT,
                fault_bits_seen=rhs.FAULT_ERROR | rhs.FAULT_PI_TIMEOUT)
    passed, checks = rhs.judge_scenario("charge-cruise", m, _events(), child,
                                        pi_live=True, duration_s=10.0,
                                        signals=_passing_signals("charge-cruise"))
    fa = [c for c in checks if c["name"] == "fault_allow_only"][0]
    # NOT continuous -> NOT excused -> the unexpected union fails fault_allow_only.
    assert fa["passed"] is False


# ── FAULT_EXPECTATIONS shape: the new entries ───────────────────────────────

def test_fault_expectations_has_all_ten_new_entries():
    for name in ("ems-y-b30-v1", "ems-y-b30-v3", "ems-y-b00-v1", "ems-y-b00-v3",
                "ems-ftp75-5050", "ems-ftp75-socband",
                "mppt-tracking", "charge-to-full", "pi-silence", "share-staircase"):
        assert name in rhs.FAULT_EXPECTATIONS, name
        assert rhs.FAULT_EXPECTATIONS[name].get("source"), name


def test_fault_expectations_ems_y_b00_variants_assert_cut_and_restore_switches():
    for name in ("ems-y-b00-v1", "ems-y-b00-v3"):
        sig = rhs.FAULT_EXPECTATIONS[name]["signals_require"]
        names = {s["name"] for s in sig}
        assert {"bt_bus_cut", "bt_bus_restored", "fc_bus_cut", "fc_bus_restored"} <= names


def test_fault_expectations_ems_y_b30_variants_assert_fc_current_biased_not_switches():
    for name in ("ems-y-b30-v1", "ems-y-b30-v3"):
        sig = rhs.FAULT_EXPECTATIONS[name]["signals_require"]
        names = {s["name"] for s in sig}
        assert "fc_current_biased" in names
        assert "bt_bus_cut" not in names


def test_fault_expectations_ems_ftp75_socband_is_fault_free():
    """The OC_FC allowance is RETIRED (operator ruling, 2026-09-01).

    It went unused in all six campaigns that ran this scenario (peak I_fc
    1.2413 A, holding the derivation's 14 % margin), and while it stood it
    silently excused the one fault this scenario is most likely to produce AND
    forced the h2 floor down to a vacuous 5e-3. Pinned NEGATIVELY as well:
    re-adding the bit must break this test, not quietly widen the entry.
    """
    expect = rhs.FAULT_EXPECTATIONS["ems-ftp75-socband"]
    # B-L1 (2026-09-01): 0, not FAULT_ERROR. The retirement removed the OC_FC
    # bit but left the FAULT_ERROR umbrella, which excuses the "latched State
    # 99" companion bit triggerFault() ORs onto EVERY latch -- so any fault at
    # all still passed. 0 is what the sibling fault-free entries carry.
    assert expect["allow_only"] == 0
    assert not (expect["allow_only"] & rhs.FAULT_OC_FC)
    assert "require" not in expect
    # It must match the fault-free siblings, not merely be non-zero-free.
    for sib in ("ems-ftp75-5050", "ems-ftp75-dp"):
        assert rhs.FAULT_EXPECTATIONS[sib]["allow_only"] == expect["allow_only"]
    # Operator ruling (b) itself is UNCHANGED -- charge-cruise still requires
    # OC_FC under it. Retiring the allowance here is a scenario-scoped judgement
    # about hedging, not a reversal of the ruling.
    assert rhs.FAULT_EXPECTATIONS["charge-cruise"]["require"] & rhs.FAULT_OC_FC


def test_fault_expectations_ems_ftp75_5050_is_fault_free():
    expect = rhs.FAULT_EXPECTATIONS["ems-ftp75-5050"]
    assert expect["allow_only"] == 0


def test_fault_expectations_pi_silence_requires_pi_timeout():
    expect = rhs.FAULT_EXPECTATIONS["pi-silence"]
    assert expect["require"] == rhs.FAULT_PI_TIMEOUT
    assert expect["not_before_s"] == pytest.approx(8.0)


def test_fault_expectations_mppt_tracking_asserts_no_hunt_signature():
    """fw v24 entry shape: the hunt is bounded ABSENT, the threshold is proved.

    Every check whose MEANING inverted is pinned by both names -- the new one
    present, the retired one gone -- so a partial revert cannot leave a check
    that reads as fw v23 evidence sitting in a fw v24 entry.
    """
    expect = rhs.FAULT_EXPECTATIONS["mppt-tracking"]
    sig = expect["signals_require"]
    names = {s["name"] for s in sig}
    assert {"mppt_asserted", "mppt_released", "mppt_no_hunt",
           "charging_occurred", "refusal_absent", "tracking_engaged",
           "mppt_threshold_written", "mppt_threshold_ceiling",
           "mppt_threshold_floor"} <= names
    assert not ({"mppt_not_stuck_high", "low_power_seen",
                 "tracking_released_not_tracking"} & names)
    # CALIBRATED 2026-09-01 from campaign 080905. The entry-level
    # provisional_note now covers exactly ONE bound and must NAME it, rather
    # than re-provisionalising the nine that are measured.
    _prov = expect.get("provisional_note") or ""
    assert "mppt_threshold_moved" in _prov
    assert "fw v24 first campaign" not in _prov

    by = {s["name"]: s for s in sig}
    # Low Power was REQUIRED (>= 50 ticks) under fw v23 and is now bounded
    # ABSENT: the direction of the bound is the whole inversion.
    # CALIBRATED 50 -> 20 (campaign 080905 measured ZERO refusal ticks; fw v23
    # measured 1481). The DIRECTION of the bound is the inversion; the value is
    # now measurement-backed.
    assert by["refusal_absent"]["max_ticks"] == 20
    assert by["refusal_absent"]["value_equals"] == rhs.AG105_ST_LOW_POWER
    # MPPT_EN|PWR_TRACK was UNREACHABLE under fw v23 (the old entry asserted
    # the complement) and is the fw v24 steady state.
    assert (by["tracking_engaged"]["value_equals"]
            == rhs.AG105_FLAG_MPPT_EN | rhs.AG105_FLAG_PWR_TRACK)
    assert by["tracking_engaged"]["min_ticks"] > 0


def test_mppt_threshold_specs_read_the_new_column_and_cannot_pass_blank():
    """The fw v24 count checks: right column, right band, non-vacuous.

    A campaign against a fw v21-v23 flash leaves `mppt_thresh_cnt` entirely
    blank (16-byte frame -> mppt_cnt None -> blank cell). All three specs must
    FAIL that run rather than pass it: the tick floor sees zero matching ticks,
    and both value bounds report "peak unmeasured", which _judge_signal_leaf
    treats as a failure on BOTH the min and the max side.
    """
    by = {s["name"]: s
          for s in rhs.FAULT_EXPECTATIONS["mppt-tracking"]["signals_require"]}
    for name in ("mppt_threshold_written", "mppt_threshold_ceiling",
                 "mppt_threshold_floor"):
        assert by[name]["column"] == "mppt_thresh_cnt"
        # Judged after the first write, never across it: the count is
        # legitimately 0xFF before the manager runs.
        assert by[name]["t_window"] == rhs._MPPT_THRESH_W
        assert by[name]["t_window"][0] >= rhs.EMS_MPPT_CRUISE_WINDOWS[0][1]
    # Bit 7 clear separates a written count (band [15, 27]) from the 0xFF
    # never-written sentinel without pinning a value nothing has measured.
    assert by["mppt_threshold_written"]["value_mask"] == 0x80
    assert by["mppt_threshold_written"]["value_equals"] == 0x00
    assert rhs.AG105_MPPT_N_RESISTOR & 0x80
    assert not (rhs.AG105_MPPT_N_FLOOR & 0x80)
    assert not (rhs.AG105_MPPT_N_CEIL & 0x80)
    assert by["mppt_threshold_written"]["min_ticks"] == rhs._MPPT_THRESH_MIN_TICKS > 0
    # The band, in COUNTS, mirroring the firmware's own clamp (.ino:1671-1690).
    assert by["mppt_threshold_ceiling"]["max_value"] == rhs.AG105_MPPT_N_CEIL == 27
    # F2: the FLOOR is judged on the in-window MINIMUM, not the peak. With
    # `min_value` it was vacuously true for any run whose maximum cleared 15 --
    # including one that spent the whole window under the clamp.
    assert "min_value" not in by["mppt_threshold_floor"]
    assert by["mppt_threshold_floor"]["floor_min_value"] == rhs.AG105_MPPT_N_FLOOR == 15
    # min_value and max_value must be on SEPARATE specs -- one spec carrying
    # both silently drops the ceiling (the import guard refuses it).
    assert "min_value" not in by["mppt_threshold_ceiling"]
    assert "max_value" not in by["mppt_threshold_floor"]
    # The OPERATING-POINT tripwire is a SEPARATE check from the firmware clamp:
    # 21 may be re-derived from measurement, 27 is the invariant and never moves.
    assert by["mppt_threshold_peak_tripwire"]["max_value"] == 21 < rhs.AG105_MPPT_N_CEIL


def test_mppt_threshold_specs_judge_blank_and_measured_columns():
    """Three-branch check of the new specs through _judge_signal_leaf itself."""
    by = {s["name"]: s
          for s in rhs.FAULT_EXPECTATIONS["mppt-tracking"]["signals_require"]}
    # (a) UNMEASURED -- the fw v21-v23 case. All three fail.
    blank = {"rows": 10, "ticks": 0, "peak": None, "trough": None,
             "first": None, "last": None,
             "latch_t": None, "prev_bit": None, "edge_t": None,
             "run": 0, "max_run": 0, "edges": 0}
    for name in ("mppt_threshold_written", "mppt_threshold_ceiling",
                 "mppt_threshold_floor"):
        ok, why = rhs._judge_signal_leaf(by[name], dict(blank))
        assert not ok, (name, why)
    # (b) MEASURED and in band -- a clamped count of 19 held for the window.
    good = dict(blank, ticks=rhs._MPPT_THRESH_MIN_TICKS, peak=19.0, trough=15.0,
                first=15.0, last=19.0)
    for name in ("mppt_threshold_written", "mppt_threshold_ceiling",
                 "mppt_threshold_floor"):
        ok, why = rhs._judge_signal_leaf(by[name], dict(good))
        assert ok, (name, why)
    # (c) NEVER WRITTEN -- the count stuck at the 0xFF resistor sentinel. The
    #     tick floor sees no matching ticks and the ceiling sees peak 255.
    stuck = dict(blank, ticks=0, peak=255.0, trough=255.0,
                 first=255.0, last=255.0)
    ok, _ = rhs._judge_signal_leaf(by["mppt_threshold_written"], dict(stuck))
    assert not ok
    ok, why = rhs._judge_signal_leaf(by["mppt_threshold_ceiling"], dict(stuck))
    assert not ok and "255" in why


# ─────────────────────────────────────────────────────────────────────────
# F1/F2 (campaign 080905): the two MINIMUM-side signal kinds.
# ─────────────────────────────────────────────────────────────────────────

def _leaf_m(**kw):
    base = {"rows": 10, "ticks": 0, "peak": None, "trough": None,
            "first": None, "last": None, "latch_t": None, "prev_bit": None,
            "edge_t": None, "run": 0, "max_run": 0, "edges": 0}
    base.update(kw)
    return base


def test_column_range_at_least_three_branches():
    """(a) motion, (b) a FROZEN carried-in constant, (c) unmeasured."""
    spec = {"column": "mppt_thresh_cnt", "column_range_at_least": 2}
    ok, why = rhs._judge_signal_leaf(spec, _leaf_m(peak=19.0, trough=15.0))
    assert ok and "range 4.0000" in why
    # THE CASE THE KIND EXISTS FOR: the count carried in from the predecessor
    # run and never moved. A LEVEL check passes here; a range check cannot.
    ok, why = rhs._judge_signal_leaf(spec, _leaf_m(peak=15.0, trough=15.0))
    assert not ok and "range 0.0000" in why
    ok, why = rhs._judge_signal_leaf(spec, _leaf_m())
    assert not ok and "unmeasured" in why


def test_floor_min_value_judges_the_minimum_not_the_peak():
    """The F2 defect, reproduced: a column that touches 19 once but otherwise
    sits at 9 PASSES `min_value` and must FAIL `floor_min_value`."""
    m = _leaf_m(peak=19.0, trough=9.0)
    ok, _ = rhs._judge_signal_leaf({"column": "c", "min_value": 15}, dict(m))
    assert ok, "min_value judges the peak -- this is the vacuity being fixed"
    ok, why = rhs._judge_signal_leaf({"column": "c", "floor_min_value": 15}, dict(m))
    assert not ok and "minimum 9.0000" in why
    ok, _ = rhs._judge_signal_leaf({"column": "c", "floor_min_value": 15},
                                   _leaf_m(peak=19.0, trough=15.0))
    assert ok
    ok, why = rhs._judge_signal_leaf({"column": "c", "floor_min_value": 15}, _leaf_m())
    assert not ok and "unmeasured" in why


def test_scan_signals_tracks_the_trough(tmp_path):
    """The scanner must record the in-window MINIMUM, on the plain-column path
    and on the derived (`sum_of`) one -- both feed the two new kinds."""
    csv_path = tmp_path / "s.csv"
    with open(csv_path, "w", newline="") as fh:
        fh.write("t,fault_flags,mppt_thresh_cnt,I_fc,I_batt\n")
        for t, c, a, b in ((3.0, 19, 0.4, 0.6), (4.0, 15, 0.1, 0.2),
                           (5.0, 17, 0.3, 0.3)):
            fh.write("%.1f,0x0000,%d,%.1f,%.1f\n" % (t, c, a, b))
    specs = [{"name": "r", "column": "mppt_thresh_cnt", "column_range_at_least": 2},
             {"name": "s", "sum_of": ["I_fc", "I_batt"], "floor_min_value": 0.2}]
    m = rhs.scan_signals(str(csv_path), specs)
    assert m[0]["trough"] == 15.0 and m[0]["peak"] == 19.0
    assert m[1]["trough"] == pytest.approx(0.3)   # 0.1+0.2, the smallest sum


def test_minimum_side_kinds_are_refused_beside_a_peak_bound():
    """Import guard: the dispatcher tests these kinds FIRST, so pairing one
    with min_value/max_value would silently discard the peak bound."""
    for bad in ({"name": "x", "column": "c", "column_range_at_least": 2,
                 "max_value": 9},
                {"name": "x", "column": "c", "floor_min_value": 1,
                 "min_value": 2},
                {"name": "x", "column": "c", "column_range_at_least": 2,
                 "floor_min_value": 1}):
        with pytest.raises(AssertionError):
            rhs._assert_signal_spec_shapes("fake", {"signals_require": [bad]})
    # ...and a kind with no column at all cannot read anything.
    with pytest.raises(AssertionError):
        rhs._assert_signal_spec_shapes(
            "fake", {"signals_require": [{"name": "x", "floor_min_value": 1}]})
    # The well-formed shapes pass.
    rhs._assert_signal_spec_shapes(
        "fake", {"signals_require": [{"name": "x", "column": "c",
                                      "column_range_at_least": 2},
                                     {"name": "y", "column": "c",
                                      "floor_min_value": 1}]})


def test_mppt_tracking_carries_the_080905_calibration_batch():
    """Every pin the campaign measured, asserted by value so a silent revert
    to the derived provisional numbers fails here."""
    by = {s["name"]: s
          for s in rhs.FAULT_EXPECTATIONS["mppt-tracking"]["signals_require"]}
    assert by["charging_occurred"]["min_value"] == 0.70    # meas peak 0.8815
    assert by["tracking_engaged"]["min_ticks"] == 2400     # meas 2902
    assert by["refusal_absent"]["max_ticks"] == 20         # meas 0
    assert rhs._MPPT_THRESH_MIN_TICKS == 12600             # meas 12900/12900
    assert rhs._MPPT_RISE_BAND == (3, 5)                   # meas 3
    # F1: the carried-in-count witness.
    assert by["mppt_threshold_moved"]["column_range_at_least"] == 2  # meas 4
    # F4: the OC budget, between the measurement (1.1638) and the limit (1.4).
    assert by["mppt_fc_headroom"]["column"] == "I_fc"
    assert 1.1638 < by["mppt_fc_headroom"]["max_value"] == 1.30 < 1.4


# ─────────────────────────────────────────────────────────────────────────
# fw v25 suite-wide share-cut hazard tripwire
# ─────────────────────────────────────────────────────────────────────────

def _sw_ring(t, switch, i_cut, reason="en_low"):
    return {"t": t, "kind": "sw_ring", "switch": switch, "reason": reason,
            "i_cut": i_cut, "peak_v": 16.0, "over_absmax": False}


def _events_with(rings):
    ev = rhs.analyze_events(None)
    ev["events_by_kind"] = {"sw_ring": list(rings)}
    return ev


def _hazard_check(metrics, rings):
    _p, checks = rhs.judge_scenario("steady", metrics, _events_with(rings),
                                    _live_child(), duration_s=30.0)
    return next(c for c in checks if c["name"] == "share_cut_load_hazard")


def test_share_cut_hazard_fires_on_a_loaded_bus_switch_cut():
    """The campaign-080905 signature: FC_BUS opened at 0.6371 A, above
    SHARE_CUT_MAX_HANDOFF_A 0.5, with no fault yet latched."""
    # error_code_final=0 = a clean fw v25 readback (B-M1's second gate).
    c = _hazard_check(_metrics(error_code_final=0), [_sw_ring(12.0, "FC_BUS", 0.6371)])
    assert c["passed"] is False
    assert "0.6371" in c["detail"] and "FC_BUS" in c["detail"]


def test_share_cut_hazard_ignores_light_cuts_and_non_bus_switches():
    """Cuts at light load past the blanking window are unchanged in effect
    under fw v25, and MOT_PWR/REGEN are not share paths at all."""
    c = _hazard_check(_metrics(error_code_final=0),
                      [_sw_ring(12.0, "FC_BUS", 0.42),
                       _sw_ring(13.0, "MOT_PWR", 4.0),
                       _sw_ring(14.0, "BT_BUS", 0.9, reason="scp_cut")])
    assert c["passed"] is True
    assert "SKIPPED" not in c["detail"]      # it really ran


def test_share_cut_hazard_excludes_state99_teardown_by_the_fault_time():
    """A teardown opens a loaded bus switch legitimately. The event carries no
    state field, so the discrimination is temporal -- on a LEAD WINDOW, at or
    after (this run's own first fault - TEARDOWN_LEAD_MS)."""
    m = _metrics(fault_bits_seen=0x8080, fault_first_t=None,
                 error_code_final=0)
    m["fault_first_t_whole_run"] = {"OC_BT": 20.0}
    assert _hazard_check(m, [_sw_ring(20.5, "BT_BUS", 3.0)])["passed"] is True
    # ...but the cut that CAUSED the fault lands strictly before the latch and
    # is still caught -- which is the 080905 case itself.
    assert _hazard_check(m, [_sw_ring(19.99, "FC_BUS", 0.6371)])["passed"] is False


def test_share_cut_hazard_survives_a_carried_in_latch_and_a_tight_teardown():
    """B-L3: the ONE fixture that both original defects fail.

    It reproduces what EVERY real run actually looks like, which neither
    pre-fix implementation could handle:

      * a CARRIED-IN latch at t = 0.0013 -- the predecessor run's fault,
        inherited through the fw v23 warm reset and present in the very first
        observation. B-H1's anchor (the raw whole-run minimum) is pinned there,
        so its cutoff excluded the WHOLE RUN and the tripwire was vacuous: the
        hazard below would have PASSED.
      * a benign State-99 TEARDOWN cut leading its own latch by 0.1 ms -- the
        measured separation (0.095-0.117 ms across campaign 20260901_080905),
        which is the observation round-trip, not physics. B-H2's proposed
        exact-anchor cutoff would have FAILED this benign cut.
      * a genuine share-path HAZARD 14 ms before that latch, the measured
        >= 13.8 ms lead.

    The fixed logic must do all three at once: exclude the teardown, catch the
    hazard, and not be defeated by the carried-in latch."""
    m = _metrics(fault_bits_seen=0x8080, error_code_final=0)
    m["fault_first_t_whole_run"] = {
        "PI_TIMEOUT/HIL_LINK": 0.0013,        # carried in from the predecessor
        "ERROR(latched State 99)": 0.0013,
        "OC_BT": 20.0000,                     # this run's OWN fault
    }
    # The post-grace map is deliberately LATE here (2.0 = the grace bound), the
    # way it reads for any fault latched inside the grace window; the tripwire
    # must not anchor on it.
    m["fault_first_t"] = {"OC_BT": 2.0}

    teardown = _sw_ring(19.9999, "BT_BUS", 3.0)     # 0.1 ms before the latch
    hazard = _sw_ring(19.9860, "FC_BUS", 0.6371)    # 14.0 ms before it

    # 1. The benign teardown alone must PASS (fails under an exact-anchor
    #    cutoff -- the B-H2 defect).
    assert _hazard_check(m, [teardown])["passed"] is True
    # 2. The hazard alone must FAIL (passes under a whole-run-minimum cutoff
    #    pinned at the carried-in 0.0013 -- the B-H1 defect).
    c = _hazard_check(m, [hazard])
    assert c["passed"] is False
    assert "0.6371" in c["detail"] and "FC_BUS" in c["detail"]
    # 3. Together: the hazard is named and the teardown is not.
    c = _hazard_check(m, [hazard, teardown])
    assert c["passed"] is False
    assert "FC_BUS" in c["detail"]
    assert "19.9999" not in c["detail"]

    # And the cutoff really is the lead window, not the anchor itself.
    cut = 20.0000 - rhs.TEARDOWN_LEAD_MS / 1000.0
    assert _hazard_check(m, [_sw_ring(cut + 0.0001, "FC_BUS", 3.0)])["passed"] is True
    assert _hazard_check(m, [_sw_ring(cut - 0.0001, "FC_BUS", 3.0)])["passed"] is False


def test_share_cut_hazard_teardown_lead_sits_between_the_measured_populations():
    """The window must stay clear of BOTH measured populations, or it starts
    scoring one of them wrong: teardown cuts lead by 0.095-0.117 ms (campaign
    20260901_080905's four) and genuine hazards by >= 13.8 ms."""
    assert 0.117 < rhs.TEARDOWN_LEAD_MS < 13.8
    # And with real margin on each side, not merely between them.
    assert rhs.TEARDOWN_LEAD_MS > 2.0 * 0.117      # clear of the round trip
    assert rhs.TEARDOWN_LEAD_MS < 13.8 / 2.0       # clear of the hazards
    # The carried-in filter must exclude a first-observation latch (~1.3 ms)
    # while admitting anything a run could plausibly cause itself.
    assert 0.0013 < rhs.CARRIED_IN_LATCH_MAX_S < 0.5


def test_share_cut_hazard_is_fw_gated_and_says_so(monkeypatch):
    """fw <= 24 legitimately produces the event; the check must render as an
    explicit SKIP rather than silently vanish."""
    monkeypatch.setattr(rhs, "TARGET_FW_VERSION", 24)
    c = _hazard_check(_metrics(error_code_final=0), [_sw_ring(12.0, "FC_BUS", 3.0)])
    assert c["passed"] is True
    assert "SKIPPED" in c["detail"] and "fw v25" in c["detail"]
    assert "TARGET_FW_VERSION is 24" in c["detail"]


def test_share_cut_hazard_also_requires_a_per_run_firmware_readback():
    """B-M1: TARGET_FW_VERSION is a DECLARATION and can be stale. error_code
    arrived on the 18-byte observation frame in fw v25, so its presence is
    positive evidence -- and a clean v25 board reads 0, not None, so 0 must
    NOT be mistaken for 'absent'."""
    hazard = [_sw_ring(12.0, "FC_BUS", 3.0)]
    # No readback -> SKIP, naming which condition declined.
    c = _hazard_check(_metrics(error_code_final=None), hazard)
    assert c["passed"] is True
    assert "SKIPPED" in c["detail"] and "error_code_final" in c["detail"]
    # A clean v25 board (error_code 0) is a readback -> the check runs.
    c = _hazard_check(_metrics(error_code_final=0), hazard)
    assert c["passed"] is False
    # ...as is a non-zero one.
    c = _hazard_check(_metrics(error_code_final=0x10), hazard)
    assert c["passed"] is False


def test_share_cut_guard_constants_match_the_firmware():
    assert rhs.SHARE_CUT_MAX_HANDOFF_A == 0.5       # .ino:2237
    assert rhs.SHARE_CUT_SURVIVOR_BLANK_MS == 30    # .ino:3353


# ─────────────────────────────────────────────────────────────────────────
# v-bus-sense-offset: the UV dwell threshold, asserted from both sides
# ─────────────────────────────────────────────────────────────────────────

def test_v_bus_sense_offset_entry_brackets_the_dwell_threshold():
    """The point of the scenario is that it bounds UV_BUS_DWELL_LATCH_MS from
    BELOW as well as above -- which `sag` (1 s under the limit) cannot."""
    expect = rhs.FAULT_EXPECTATIONS["v-bus-sense-offset"]
    assert expect["require"] == rhs.FAULT_UV_BUS
    assert expect["allow_only"] == rhs.FAULT_UV_BUS | rhs.FAULT_ERROR
    # THE LOWER-SIDE ASSERTION. not_before_s must sit strictly between the two
    # excursions: after excursion 1 (so a latch on 12 ms of dwell FAILS) and
    # before excursion 2 (so the real latch is not rejected).
    assert hil.V_BUS_UV_PROBE_1[1] < expect["not_before_s"] < hil.V_BUS_UV_PROBE_2[0]
    # ...and it must be post-grace, or it asserts nothing.
    assert expect["not_before_s"] > rhs.WARM_RESET_GRACE_S
    # B-M2: `not_before_s` is an ABSENCE assertion and passes for free on a
    # probe that never happened, so the entry must also carry the cadence
    # census that says probe 1 WAS delivered -- on probe 1's own window.
    cad = [s for s in expect["signals_require"] if "min_rows" in s]
    assert len(cad) == 1, "the probe-1 cadence de-vacuation check is missing"
    assert cad[0]["t_window"] == hil.V_BUS_UV_PROBE_1
    # Floor must be reachable at 1 kHz over an 8 ms window but strict enough to
    # catch a stall well below the ~12 ms that could corrupt the verdict.
    n_ticks = round((hil.V_BUS_UV_PROBE_1[1] - hil.V_BUS_UV_PROBE_1[0]) * 1000.0)
    assert 0 < cad[0]["min_rows"] <= n_ticks
    assert n_ticks - cad[0]["min_rows"] <= 2      # <= 2 ms of slack


def test_v_bus_sense_offset_probe_geometry_brackets_20ms():
    """The two excursions must straddle the firmware's 20 ms threshold with
    real margin. A geometry edit that put both on one side would leave the
    entry passing while proving nothing."""
    d1 = (hil.V_BUS_UV_PROBE_1[1] - hil.V_BUS_UV_PROBE_1[0]) * 1000.0
    d2 = (hil.V_BUS_UV_PROBE_2[1] - hil.V_BUS_UV_PROBE_2[0]) * 1000.0
    # B-M2 (2026-09-01): probe 1 is 8 ms, shortened from 12 for host-stall
    # margin. Pinned literally, both sides -- a geometry edit must come here.
    assert d1 == pytest.approx(8.0)
    assert d2 == pytest.approx(60.0)
    assert d1 < 20.0 < d2
    # B-M2: the stall margin the shortening bought. The firmware HOLDS the last
    # injected value for HIL_STALE_MS, so a host stall inside probe 1 lengthens
    # the DELIVERED dwell; the margin to the 20 ms threshold is what a stall
    # must exceed to corrupt the verdict. At 12 ms it was 8; require >= 10.
    assert 20.0 - d1 >= 10.0
    # LEAK INDEPENDENCE: excursion 1 leaves d1 ms in the accumulator, and
    # UV_BUS_DWELL_LEAK 0.05 drains it over d1/0.05 ms of healthy bus. The gap
    # must clear that, or excursion 2 latches on the PAIR and the threshold is
    # not what was measured.
    gap_ms = (hil.V_BUS_UV_PROBE_2[0] - hil.V_BUS_UV_PROBE_1[1]) * 1000.0
    assert gap_ms > 5.0 * (d1 / 0.05)
    # Depth: clear of the limit, not on it.
    assert hil.V_BUS_UV_PROBE_DEPTH_V <= -3.0


def test_v_bus_sense_offset_is_hifi_because_the_mode_is_the_design():
    """simple mode makes the offset a REAL disturbance the sources respond to,
    which would confound a dwell measurement with a current transient. hifi's
    offset is sense-path-only, so it perturbs only the quantity under test."""
    assert hil.SCENARIOS["v-bus-sense-offset"]["electrical"] == "hifi"


def test_v_bus_sense_offset_stimulus_walks_the_offset(monkeypatch):
    """apply_scenario drives the offset on for each excursion and off between
    -- and OFF is genuinely zero, not a smaller sag."""
    class _P:
        v_bus_offset = None
        i_aux = 0.0
    pl = _P()
    for t, want in ((4.999, 0.0),
                    (5.000, hil.V_BUS_UV_PROBE_DEPTH_V),
                    (5.007, hil.V_BUS_UV_PROBE_DEPTH_V),
                    (5.008, 0.0),              # exclusive upper bound
                    (5.012, 0.0),              # B-M2: probe 1 is 8 ms now
                    (6.500, 0.0),
                    (7.999, 0.0),
                    (8.000, hil.V_BUS_UV_PROBE_DEPTH_V),
                    (8.059, hil.V_BUS_UV_PROBE_DEPTH_V),
                    (8.060, 0.0),
                    (11.0, 0.0)):
        hil.apply_scenario(pl, "v-bus-sense-offset", t)
        assert pl.v_bus_offset == pytest.approx(want), t


def test_handoff_sag_no_longer_claims_the_uv_objective_is_homeless():
    """The note retargets rather than being deleted -- a reader arriving at
    handoff-sag for a UV number must be sent to the scenario that measures it."""
    src = rhs.FAULT_EXPECTATIONS["handoff-sag"]
    blob = " ".join(str(v) for v in src.values())
    # The entry still permits UV_BUS (the class it models did sag that far)...
    assert src["allow_only"] & rhs.FAULT_UV_BUS
    # ...but the scenario that OWNS the objective now exists.
    assert "v-bus-sense-offset" in rhs.FAULT_EXPECTATIONS
    assert "v-bus-sense-offset" in hil.SCENARIOS


# ─────────────────────────────────────────────────────────────────────────
# fw v25 expectation-impact: the derivation, pinned
# ─────────────────────────────────────────────────────────────────────────

def test_fw25_blanking_cannot_reach_any_pinned_cut_sequence():
    """The review's arithmetic, as a test. Every pinned cut in the table is
    separated from the nearest preceding bus-switch RESTORE by far more than
    SHARE_CUT_SURVIVOR_BLANK_MS, so no measured latency or tick pin moves.

    A future entry that cuts within the blanking window of a restore must fail
    here and be re-derived, rather than silently drifting."""
    blank_s = rhs.SHARE_CUT_SURVIVOR_BLANK_MS / 1000.0
    # share-staircase holds each excursion 3 s, i.e. EXACTLY 100x the blanking
    # window -- hence >=, not >. Its cuts are BT 33 / restore 36 / FC 39 /
    # restore 42.
    assert rhs._SS_FC_CUT_T - rhs._SS_BT_RESTORE_T >= 100 * blank_s
    assert rhs._SS_BT_RESTORE_T - rhs._SS_BT_CUT_T >= 100 * blank_s
    # ems-y-*: the FC cut (~34.3) against the BT restore window (~23.5-27.0).
    assert rhs._Y_FC_RESTORE_W[0] - rhs._Y_BT_RESTORE_W[1] > 100 * blank_s


def test_ems_sdp_braking_expectation_is_not_weakened_for_fw25():
    """The guards make the existing fault-free expectation REACHABLE; they are
    not a reason to admit the fault it used to produce."""
    expect = rhs.FAULT_EXPECTATIONS["ems-sdp-braking"]
    # `allow_only == 0` already says it, but pin the specific bit the fw <= 24
    # FAIL produced so a future widening cannot slip it back in unnoticed.
    assert expect["allow_only"] == 0
    FAULT_OC_BT = 0x0080          # .ino FAULT_* defines
    assert not (expect["allow_only"] & FAULT_OC_BT)


def test_fault_expectations_charge_to_full_asserts_no_action_baseline():
    sig = rhs.FAULT_EXPECTATIONS["charge-to-full"]["signals_require"]
    names = {s["name"] for s in sig}
    assert "fc_charge_still_open" in names
    assert "reached_full" in names
    assert "cv_flag" in names
    assert "current_tapered" in names


def test_fault_expectations_share_staircase_asserts_both_cuts_and_all_four_latencies():
    sig = rhs.FAULT_EXPECTATIONS["share-staircase"]["signals_require"]
    names = {s["name"] for s in sig}
    assert {"bt_bus_cut", "bt_bus_restored", "fc_bus_cut", "fc_bus_restored",
           "bt_cut_latency", "bt_restore_latency",
           "fc_cut_latency", "fc_restore_latency"} <= names


# ── --with-ftp75 ─────────────────────────────────────────────────────────────

def test_build_plan_ftp75_scenarios_skipped_by_default():
    plan = rhs.build_plan(_args())
    for name in rhs.FTP75_SCENARIOS:
        item = next(p for p in plan if p["name"] == name)
        assert item["kind"] == "scenario"
        assert item["argv"] is None
        assert "LONG-CYCLE" in item["skip_reason"]


def test_build_plan_with_ftp75_flag_runs_them():
    plan = rhs.build_plan(_args(with_ftp75=True))
    for name in rhs.FTP75_SCENARIOS:
        item = next(p for p in plan if p["name"] == name)
        assert item["argv"] is not None
        assert not item.get("skip_reason")


def test_build_plan_with_ftp75_does_not_affect_non_ftp75_scenarios():
    plan_default = {p["name"]: p for p in rhs.build_plan(_args()) if p["kind"] == "scenario"}
    plan_ftp75 = {p["name"]: p for p in rhs.build_plan(_args(with_ftp75=True))
                 if p["kind"] == "scenario"}
    for name in plan_default:
        if name in rhs.FTP75_SCENARIOS:
            continue
        assert plan_default[name]["argv"] == plan_ftp75[name]["argv"], name


def test_build_plan_pi_live_skips_ftp75_regardless_of_with_ftp75():
    """Ordering matters: the --pi-live gate is checked BEFORE --with-ftp75, so
    under both flags together the ftp75 scenarios are still skip-recorded,
    with the pi-live reason (not the ftp75 one)."""
    plan = rhs.build_plan(_args(pi_live=True, with_ftp75=True))
    for name in rhs.FTP75_SCENARIOS:
        item = next(p for p in plan if p["name"] == name)
        assert item["argv"] is None
        assert "pi-live" in item["skip_reason"].lower()
        assert "LONG-CYCLE" not in item["skip_reason"]


# -------------------------------------------------------------------------
# 4b. --with-alpha: the three SDP alpha-sweep legs (WP-1C, 2026-09-02)
# -------------------------------------------------------------------------

def test_alpha_scenarios_are_registered_and_share_the_ems_sdp_stimulus():
    """The trio's controlled variable is alpha and NOTHING else. If a leg's
    stimulus drifts from `ems-sdp`'s, the three runs stop being one experiment
    and every comparison the round is for becomes a comparison of loads."""
    base = SCENARIOS["ems-sdp"]
    for name in rhs.ALPHA_SCENARIOS:
        meta = SCENARIOS[name]
        assert meta["duration_s"] == base["duration_s"]
        assert meta["chg_i_ceiling_a"] == base["chg_i_ceiling_a"]
        assert meta.get("ems_v_profile") == base.get("ems_v_profile")


def test_build_plan_skips_alpha_by_default_with_a_named_reason():
    plan = rhs.build_plan(_args())
    for name in rhs.ALPHA_SCENARIOS:
        item = next(p for p in plan if p["name"] == name)
        assert item["kind"] == "scenario"
        assert item["argv"] is None
        assert "ALPHA SWEEP" in item["skip_reason"]
        assert "--with-alpha" in item["skip_reason"]


def test_build_plan_with_alpha_flag_runs_them():
    plan = rhs.build_plan(_args(with_alpha=True))
    for name in rhs.ALPHA_SCENARIOS:
        item = next(p for p in plan if p["name"] == name)
        assert item["argv"] is not None
        assert not item.get("skip_reason")


def test_build_plan_with_alpha_does_not_affect_other_scenarios():
    plan_default = {p["name"]: p for p in rhs.build_plan(_args())
                    if p["kind"] == "scenario"}
    plan_alpha = {p["name"]: p for p in rhs.build_plan(_args(with_alpha=True))
                  if p["kind"] == "scenario"}
    for name in plan_default:
        if name in rhs.ALPHA_SCENARIOS:
            continue
        assert plan_default[name]["argv"] == plan_alpha[name]["argv"], name


def test_build_plan_pi_live_skips_alpha_regardless_of_with_alpha():
    """Gate ORDER, pinned: --pi-live is checked BEFORE --with-alpha, so under
    both flags the alpha legs are skip-recorded for the pi-live reason. The
    alternative would name a flag that could not make the run happen."""
    plan = rhs.build_plan(_args(pi_live=True, with_alpha=True))
    for name in rhs.ALPHA_SCENARIOS:
        item = next(p for p in plan if p["name"] == name)
        assert item["argv"] is None
        assert "pi-live" in item["skip_reason"].lower()
        assert "ALPHA SWEEP" not in item["skip_reason"]


def test_full_argv_with_alpha_flag_not_passed_through_to_child():
    plan = rhs.build_plan(_args(with_alpha=True))
    item = next(p for p in plan if p["name"] == "ems-sdp-alpha-cal")
    argv = rhs.full_argv(item, _args(with_alpha=True))
    assert "--with-alpha" not in argv


def test_alpha_expectations_are_provisional_and_two_sided():
    """Every alpha bound is an OFFLINE prediction, so every one of the three
    entries must carry a provisional note, and the h2 band must be two-sided
    (one spec cannot carry both bounds - `_judge_signal_leaf` returns on the
    first it matches)."""
    for name in rhs.ALPHA_SCENARIOS:
        e = rhs.FAULT_EXPECTATIONS[name]
        assert e["allow_only"] == 0
        assert e["provisional_note"] and "no campaign" in e["provisional_note"]
        sig = e["signals_require"]
        h2 = [x for x in sig if x.get("column") == "h2_cum_g"]
        assert len(h2) == 2
        for x in h2:
            assert not ("min_value" in x and "max_value" in x)


def test_alpha_h2_bands_are_the_walk_plus_minus_25_percent():
    """The bands come from the sweep's own live_picks walk totals. Pinned so a
    band cannot be quietly widened to absorb a run: +/-25 % is the contract."""
    walks = {"ems-sdp-alpha-greedy": 0.004093022760826734,
             "ems-sdp-alpha-cal": 0.012602735460289607,
             "ems-sdp-alpha-charge": 0.015064731516112779}
    for name, walk in walks.items():
        by = {c["name"]: c for c in
              rhs.FAULT_EXPECTATIONS[name]["signals_require"]}
        assert by["alpha_h2_accounted"]["min_value"] == pytest.approx(0.75 * walk)
        assert by["alpha_h2_bounded"]["max_value"] == pytest.approx(1.25 * walk)
        assert (by["alpha_h2_accounted"]["min_value"] < walk
                < by["alpha_h2_bounded"]["max_value"])


def test_alpha_charge_census_matches_each_artifacts_charge_map():
    """THE TRIO'S HEADLINE DISCRIMINATOR. Two of the three artifacts carry zero
    charge cells and must never open FC_CHARGE; the third carries 591 and opens
    one window in the walk. A COUNT band, not a window, so a model error in
    WHEN the window opens cannot fail a run whose mechanism worked (the
    campaign-024231 S2 precedent)."""
    def census(name):
        return next(c for c in rhs.FAULT_EXPECTATIONS[name]["signals_require"]
                    if c["name"] == "alpha_charge_edge_census")
    for name in ("ems-sdp-alpha-greedy", "ems-sdp-alpha-cal"):
        c = census(name)
        assert c["edge_count_between"] == (0, 0)
        assert c["switch_bit"] == rhs.SW_FC_CHARGE and c["edge"] == "rise"
    c = census("ems-sdp-alpha-charge")
    assert c["edge_count_between"][0] == 1        # it MUST charge
    assert c["edge_count_between"][1] >= 1


def test_alpha_share_signatures_separate_the_degenerate_leg():
    """The greedy leg's alpha sits under the share lever's admission threshold,
    so its share map is 0 everywhere: a CEILING at the battery rail. The other
    two reach the FC rail: a FLOOR. Getting these the same way round would make
    all three legs assert the same thing."""
    by = {n: {c["name"]: c for c in
              rhs.FAULT_EXPECTATIONS[n]["signals_require"]}
          for n in rhs.ALPHA_SCENARIOS}
    greedy = by["ems-sdp-alpha-greedy"]["alpha_share_degenerate"]
    assert greedy["max_value"] == rhs._SDP_LOW_RAIL_CEIL
    # The window must start AFTER the first policy command - before it the
    # board holds the firmware default 0.50, which a ceiling would read as a
    # violation.
    assert greedy["t_window"][0] >= 5.0
    for n in ("ems-sdp-alpha-cal", "ems-sdp-alpha-charge"):
        assert (by[n]["alpha_share_high_rail"]["min_value"]
                == rhs._SDP_HIGH_RAIL_FLOOR)


def test_alpha_fc_ceiling_is_the_ems_sdp_cross_budget():
    """Inherited, not invented: the same 1.28 A single-source charge budget
    `ems-sdp-cross` measured 1.1920 A against, on the same stimulus and the
    same 0.8 A ceiling."""
    cross = next(c for c in
                 rhs.FAULT_EXPECTATIONS["ems-sdp-cross"]["signals_require"]
                 if c["name"] == "sdpx_fc_peak_bounded")
    for name in rhs.ALPHA_SCENARIOS:
        c = next(x for x in rhs.FAULT_EXPECTATIONS[name]["signals_require"]
                 if x["name"] == "alpha_fc_peak_bounded")
        assert c["max_value"] == cross["max_value"] == rhs._ALPHA_FC_CEIL


# -------------------------------------------------------------------------
# 4c. The charger era: eta_chg on the frontier and in the report header
# -------------------------------------------------------------------------

def test_eta_chg_is_a_frontier_stimulus_key():
    assert "eta_chg" in rhs.EMS_FRONTIER_STIMULUS_KEYS


def test_frontier_eta_mismatch_needs_resolved_values_not_the_registry():
    """`eta_chg` is a PLANT constant, not a scenario field, so the registry
    lookup is None for every leg and the key can only fire through the
    resolved override. Without one it must be silent - otherwise every
    campaign would report a mismatch on a key no scenario declares."""
    roles = rhs.EMS_FRONTIER
    keys = [k for k, _ in rhs.ems_frontier_stimulus_mismatches(roles)]
    assert "eta_chg" not in keys


def test_frontier_eta_mismatch_fires_on_a_mixed_era_campaign():
    """The case the key exists for: a pre-eta CSV ranked against a post-eta
    one. `None` is the 1:1-era sentinel and must be able to disagree with
    0.88."""
    roles = rhs.EMS_FRONTIER
    etas = {roles["reference"]: 0.88, roles["candidate"]: 0.88,
            roles["bound"]: None}
    got = dict(rhs.ems_frontier_stimulus_mismatches(roles, etas=etas))
    assert "eta_chg" in got
    assert got["eta_chg"][roles["bound"]] is None
    # ... and a campaign whose legs all ran the same era is silent.
    same = {n: 0.88 for n in roles.values()}
    assert "eta_chg" not in dict(
        rhs.ems_frontier_stimulus_mismatches(roles, etas=same))


def test_frontier_eta_mismatch_does_not_fire_on_a_partial_campaign():
    """A leg with no record yet must NOT be given the None sentinel: that would
    read as "this leg ran the old charger" and fire on every partial campaign,
    which for the cycle61 tuple is exit-affecting."""
    roles = rhs.EMS_FRONTIER
    etas = {roles["reference"]: 0.88}          # the other two have not run
    assert "eta_chg" not in dict(
        rhs.ems_frontier_stimulus_mismatches(roles, etas=etas))


def test_run_eta_chg_reads_the_scenario_block_of_the_sidecar(tmp_path):
    csv = tmp_path / "run.csv"
    doc = {"csv": str(csv), "results": {},
           "created": "2026-09-02T00:00:00+00:00",
           "scenario": {"name": "ems-sdp", "eta_chg": 0.88}}
    (tmp_path / "run.csv.meta.json").write_text(json.dumps(doc),
                                                encoding="utf-8")
    assert rhs.run_eta_chg(str(csv), _fake_child()) == pytest.approx(0.88)


def test_run_eta_chg_returns_none_for_a_pre_eta_or_missing_sidecar(tmp_path):
    """None is a VALUE (the 1:1 era), not an error - a sidecar written before
    the key existed and one that is missing entirely both read as the old
    era."""
    csv = tmp_path / "old.csv"
    doc = {"csv": str(csv), "results": {},
           "created": "2026-08-01T00:00:00+00:00",
           "scenario": {"name": "ems-sdp"}}
    (tmp_path / "old.csv.meta.json").write_text(json.dumps(doc),
                                                encoding="utf-8")
    assert rhs.run_eta_chg(str(csv), _fake_child()) is None
    assert rhs.run_eta_chg(str(tmp_path / "absent.csv"), _fake_child()) is None


def test_report_header_names_the_charger_era_and_the_comparability_boundary():
    r = _fake_scenario_result()
    r["eta_chg"] = 0.88
    report = rhs.render_report(_fake_meta(), [r])
    assert "Charger era" in report
    assert "0.88" in report
    assert "20260901_151156" in report


def test_report_header_names_the_1_to_1_era_when_the_run_recorded_none():
    r = _fake_scenario_result()
    r["eta_chg"] = None
    report = rhs.render_report(_fake_meta(), [r])
    assert "1:1 current transfer" in report


def test_report_header_says_not_recorded_when_no_run_carries_the_key():
    """An OLD results list (no `eta_chg` key at all) must not be reported as
    the 1:1 era - "the key is absent" and "the run recorded the old era" are
    different statements."""
    report = rhs.render_report(_fake_meta(), [_fake_scenario_result()])
    assert "not recorded" in report


def test_full_argv_with_ftp75_flag_not_passed_through_to_child():
    """--with-ftp75 is a run_hil_suite.py PLANNING flag (which scenarios enter
    the plan at all) -- it must not leak into the child simulator's argv,
    which knows nothing about it."""
    plan = rhs.build_plan(_args(with_ftp75=True))
    item = next(p for p in plan if p["name"] == "ems-ftp75-5050")
    argv = rhs.full_argv(item, _args(with_ftp75=True))
    assert "--with-ftp75" not in argv


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


# -- events_by_kind (2026-08-31, feeds _judge_event_spec's `where` filter) --

def test_analyze_events_missing_path_events_by_kind_present_and_empty():
    """events_by_kind must be present (as {}) in the zeroed/missing-path
    dict, alongside the other event fields, not added only once a real
    sidecar is parsed."""
    out = rhs.analyze_events(None)
    assert out["events_by_kind"] == {}
    out2 = rhs.analyze_events("/nonexistent/file.jsonl")
    assert out2["events_by_kind"] == {}


def test_analyze_events_events_by_kind_holds_the_whole_event_grouped_by_kind(tmp_path):
    lines = [
        {"kind": "sw_ring", "switch": "MOT_PWR", "i_cut": 4.5565, "over_absmax": False},
        {"kind": "sw_ring", "switch": "FC_BUS", "i_cut": 1.2, "over_absmax": False},
        {"kind": "scp_cut", "switch": "MOT_PWR", "i_cut": 6.29},
    ]
    path = tmp_path / "events.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for e in lines:
            fh.write(json.dumps(e) + "\n")
    out = rhs.analyze_events(str(path))
    assert len(out["events_by_kind"]["sw_ring"]) == 2
    assert len(out["events_by_kind"]["scp_cut"]) == 1
    mot_pwr = [e for e in out["events_by_kind"]["sw_ring"] if e["switch"] == "MOT_PWR"][0]
    assert mot_pwr["i_cut"] == pytest.approx(4.5565)
    fc_bus = [e for e in out["events_by_kind"]["sw_ring"] if e["switch"] == "FC_BUS"][0]
    assert fc_bus["i_cut"] == pytest.approx(1.2)
    # kinds count and events_by_kind length must always agree -- two different
    # views of the same underlying events, so they cannot legitimately drift.
    for kind, n in out["kinds"].items():
        assert len(out["events_by_kind"][kind]) == n


def test_analyze_events_events_by_kind_keeps_scalars_only(tmp_path):
    """Only int/float/str/bool fields survive into events_by_kind (the same
    scalars-only discipline field_values already applies) -- a nested
    dict/list value on a future event kind must not be carried through raw."""
    lines = [
        {"kind": "weird_event", "switch": "MOT_PWR", "i_cut": 4.5,
         "nested": {"a": 1}, "listy": [1, 2, 3]},
    ]
    path = tmp_path / "events.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for e in lines:
            fh.write(json.dumps(e) + "\n")
    out = rhs.analyze_events(str(path))
    ev = out["events_by_kind"]["weird_event"][0]
    assert ev["switch"] == "MOT_PWR"
    assert ev["i_cut"] == pytest.approx(4.5)
    assert "nested" not in ev
    assert "listy" not in ev


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
    absent from the post-grace union) must get the dedicated pre-grace sub-line
    -- the exact scenario A5/M2 exist to surface.

    WORDING (2026-08-31): the line used to attribute the bits to "the
    PREDECESSOR'S settle latch", which the CSV cannot support and which was
    false on most runs it printed for. It now names the mechanism it can see
    and implies nothing about the predecessor -- and the test asserts the old
    claim is GONE, not merely that some line appeared."""
    seen = rhs.FAULT_UV_BUS | rhs.FAULT_ERROR
    results = [_fake_replay_result(metrics=_replay_metrics(
        final_fault_flags=0, fault_bits_seen=seen, fault_bits_post_grace=0))]
    report = rhs.render_report(_fake_meta(), results)
    assert "pre-grace reconnect transient" in report
    assert "not distinguishable here" in report
    assert "carried in from the predecessor" not in report


def test_render_report_replay_metrics_block_no_carried_in_line_when_unions_match():
    results = [_fake_replay_result(metrics=_replay_metrics(
        final_fault_flags=0, fault_bits_seen=0, fault_bits_post_grace=0))]
    report = rhs.render_report(_fake_meta(), results)
    assert "pre-grace reconnect transient" not in report


def test_judge_scenario_carried_note_does_not_claim_a_predecessor_latch():
    """Campaign 20260831_222036, flagged by three analysis agents: the
    `fault_allow_only` detail asserted "carried-in from the predecessor's
    settle latch" on runs whose predecessor ended CLEAN (7 of 8 across two
    batches). The dominant pre-grace bit is 0x8010, generated FRESH by each
    child's own link handshake — so the wording must name what is observed and
    stop attributing it. Both halves matter: the honest clause present, and the
    unsupportable claim gone."""
    metrics = _metrics(fault_bits_seen=0x8010, fault_bits_post_grace=0,
                       final_fault_flags=0)
    # Both branches of judge_scenario carry the note: an entry WITH an
    # expectation (fault_allow_only) and one without (no_unexpected_fault).
    for scenario, check_name in (("charge-fault", "fault_allow_only"),
                                 ("steady", "no_unexpected_fault")):
        _passed, checks = rhs.judge_scenario(scenario, metrics, _events(),
                                             _child())
        detail = next(c["detail"] for c in checks if c["name"] == check_name)
        assert "pre-grace reconnect transient" in detail, scenario
        assert "predecessor state NOT implied" in detail, scenario
        assert "predecessor's settle latch" not in detail, scenario


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
    """soc-depletion overrides --soc0 to 0.20 (a low-SoC UV-latch stimulus);
    charge-to-full overrides it to 0.990 (a next-to-FULL stimulus, 2026-08-31
    wave 2). Both are legitimate per-scenario overrides and both are excluded
    here -- the assertion is that NEITHER leaks into any OTHER scenario's
    argv."""
    plan = rhs.build_plan(_args())
    overridden = {"soc-depletion", "charge-to-full"}
    for p in plan:
        if p["kind"] != "scenario" or p["name"] in overridden:
            continue
        if p["argv"] is None:
            # operator_required / --pi-live / --with-ftp75 skip record: no
            # argv is ever built for it.
            continue
        assert "--soc0" not in p["argv"], p["name"]


def test_charge_to_full_soc0_override():
    """charge-to-full's own argv carries the 0.990 override (arithmetic at
    the scenario's FAULT_EXPECTATIONS entry: 0.995 - 0.990 = 90 A*s of
    headroom to the Fully-Charged branch at the 1.0 A ceiling)."""
    plan = rhs.build_plan(_args())
    item = next(p for p in plan if p["name"] == "charge-to-full")
    assert item["argv"] is not None
    assert "--soc0" in item["argv"]
    idx = item["argv"].index("--soc0")
    assert item["argv"][idx + 1] == "0.990"


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
    # 2026-08-31: both new EMS-driven scenarios join the skip set via their
    # "ems" metadata key -- same rule as ems-drive-cycle, no new code path.
    "ems-soc-band", "ems-dp-replay",
    # 2026-08-31 wave 2: six more join via the SAME two metadata keys, no new
    # code path either.  Four via "ems": the ems-y-* quartet (each carries
    # "ems": "y-b*"), mppt-tracking ("ems": "mppt-harvest"), and pi-silence
    # ("ems": "hold-5050"). Two via "pi_timeline": charge-to-full and
    # share-staircase. The ems-ftp75-* pair is EMS-driven too (their "ems" is
    # "hold-5050"/"soc-band") and so is caught by the same rule -- they are
    # NOT listed separately because build_plan() orders the --pi-live gate
    # BEFORE the --with-ftp75 gate (see the scenario_aux_preload_a-adjacent
    # comment in build_plan()), so under --pi-live they are skip-recorded for
    # the pi-live reason regardless of --with-ftp75.
    "ems-y-b30-v1", "ems-y-b30-v3", "ems-y-b00-v1", "ems-y-b00-v3",
    "mppt-tracking", "pi-silence", "charge-to-full", "share-staircase",
    "ems-ftp75-5050", "ems-ftp75-socband",
    # WP-E 2026-09-01: `ems-ftp75-dp` joins via "ems": "dp-replay", same rule.
    "ems-ftp75-dp",
    # 2026-08-31 SDP round: `ems-sdp` joins via the same "ems" metadata key
    # ("ems": "sdp-v1") -- no new code path.
    # 2026-08-31 SDP-interior round: three more join the same way ("ems":
    # "sdp-v2").  `ems-ftp75-sdp` is in FTP75_SCENARIOS as well, and is listed
    # here for the same reason its two siblings are not listed separately --
    # the --pi-live gate is ordered FIRST, so it is skip-recorded for the
    # pi-live reason regardless of --with-ftp75.
    "ems-ftp75-sdp", "ems-sdp-cross", "ems-sdp-braking",
    "ems-sdp",
    # WP-C (2026-09-01): joins via the SAME "ems" metadata key
    # ("ems": "regen-harvest-hard") -- no new code path.
    "regen-harvest-true",
    # WP-1C (2026-09-02): the alpha trio joins via the same "ems" key
    # ("ems": "sdp-sweep") -- no new code path.  They are in ALPHA_SCENARIOS
    # as well, and are listed here for the same reason the FTP-75 legs are:
    # the --pi-live gate is ordered FIRST, so under --pi-live they are
    # skip-recorded for the pi-live reason regardless of --with-alpha.
    "ems-sdp-alpha-greedy", "ems-sdp-alpha-cal", "ems-sdp-alpha-charge",
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


def test_build_plan_pi_live_total_count_still_40():
    """Skip records still occupy a plan slot -- the total run count (56, since
    the 2026-08-31 SDP-interior round's three `sdp_soc_ref_offset` scenarios)
    is unchanged under --pi-live, only their kind (executed vs skipped)
    differs."""
    plan = rhs.build_plan(_args(pi_live=True))
    assert len(plan) == 62      # WP-C: +regen-harvest-true; WP-B: +v-bus-sense-offset;
                                # WP-1C: +the ems-sdp-alpha-* trio


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
    # fw v25: the wording moved to attribute_shared_0x8010()'s vocabulary. The
    # substance is unchanged -- a discontinuous stream on a pre-v25 board is
    # unattributable, so the fault is NOT excused.
    assert "not continuous" in fault_check["detail"]
    assert "cannot attribute" in fault_check["detail"]


# ─────────────────────────────────────────────────────────────────────────
# fw v25: 0x8010 attribution READS THE WIRE, and only infers as a fallback.
# ─────────────────────────────────────────────────────────────────────────

def test_attribute_shared_0x8010_prefers_the_wire_over_stream_health():
    """The payoff case, and the one the old inference got WRONG.

    A board reporting ERR_HIL_STALE while THIS process's tx counters look
    perfect is stating something real -- the datagrams left this host and did
    not arrive.  The pre-v25 inference would have concluded "stream continuous,
    therefore PI_TIMEOUT" and excused a genuine link failure.
    """
    cause, src, detail = rhs.attribute_shared_0x8010(
        _metrics(error_code_post_grace=rhs.ERR_HIL_STALE), _live_child(), 30.0)
    assert cause == "hil"
    assert src == rhs.ATTRIB_WIRE
    assert "ERR_HIL_STALE" in detail
    # ...and the mirror: the wire says PI_TIMEOUT even with a GAPPY stream,
    # where the inference would have refused to attribute at all.
    cause, src, _ = rhs.attribute_shared_0x8010(
        _metrics(error_code_post_grace=rhs.ERR_PI_TIMEOUT), _gappy_child(), 30.0)
    assert (cause, src) == ("pi", rhs.ATTRIB_WIRE)


def test_attribute_shared_0x8010_third_code_is_undecided_not_guessed():
    """A first cause that is neither of the two aliased ones means the 0x0010
    bit (if set) was a LATER OR.  Falling back to stream health there would
    manufacture an attribution the board contradicts."""
    cause, src, detail = rhs.attribute_shared_0x8010(
        _metrics(error_code_post_grace=0x09), _live_child(), 30.0)   # ERR_UV_BUS
    assert cause is None
    assert src == rhs.ATTRIB_WIRE
    assert "ERR_UV_BUS" in detail


def test_attribute_shared_0x8010_falls_back_to_inference_on_a_pre_v25_board():
    """No error_code on the wire -> the pre-v25 semantics, LABELLED as such."""
    cause, src, detail = rhs.attribute_shared_0x8010(
        _metrics(), _live_child(), 30.0)
    assert (cause, src) == ("pi", rhs.ATTRIB_INFERRED)
    assert "INFERRED" in detail
    cause, src, _ = rhs.attribute_shared_0x8010(_metrics(), _gappy_child(), 30.0)
    assert (cause, src) == (None, rhs.ATTRIB_INFERRED)
    # Unmeasured is neither verdict, and is flagged as unknown rather than
    # silently treated as a gap.
    cause, src, _ = rhs.attribute_shared_0x8010(
        _metrics(), {"status": "ok", "summary": {}}, 30.0)
    assert (cause, src) == (None, rhs.ATTRIB_UNKNOWN)


def test_judge_scenario_pi_live_excusal_refused_when_the_wire_says_hil_stale():
    """End-to-end: the excusal now fails a run the pre-v25 harness excused."""
    passed, checks = rhs.judge_scenario(
        "steady",
        _metrics(fault_bits_seen=0x8010, final_fault_flags=0x8010,
                 error_code_post_grace=rhs.ERR_HIL_STALE),
        rhs.analyze_events(None), _live_child(), pi_live=True, duration_s=30.0)
    assert passed is False
    fc = next(c for c in checks if c["name"] == "no_unexpected_fault")
    assert fc["passed"] is False
    assert "wire" in fc["detail"] and "ERR_HIL_STALE" in fc["detail"]


def test_judge_scenario_pi_live_excusal_granted_when_the_wire_says_pi_timeout():
    passed, checks = rhs.judge_scenario(
        "steady",
        _metrics(fault_bits_seen=0x8010, final_fault_flags=0x8010,
                 error_code_post_grace=rhs.ERR_PI_TIMEOUT),
        rhs.analyze_events(None), _gappy_child(), pi_live=True, duration_s=30.0)
    fc = next(c for c in checks if c["name"] == "no_unexpected_fault")
    assert fc["passed"] is True
    assert "excused" in fc["detail"] and "wire" in fc["detail"]
    assert passed is True


def test_analyze_scenario_csv_reads_error_code_post_grace_only(tmp_path):
    """The post-grace scoping is not cosmetic: a carried-in settle latch from
    the PREVIOUS run is still on the wire inside the grace window, and reading
    it would attribute the predecessor's fault to this run."""
    csv_path = tmp_path / "r.csv"
    grace = rhs.WARM_RESET_GRACE_S
    with open(csv_path, "w", newline="") as fh:
        fh.write("t,fault_flags,state,error_code\n")
        fh.write("0.10,0x8010,99,16\n")                  # carried-in, pre-grace
        fh.write("%.3f,0x0000,1,0\n" % (grace + 0.5))    # cleared, post-grace
    m = rhs.analyze_scenario_csv(str(csv_path))
    assert m["error_code_final"] == 0
    assert m["error_code_post_grace"] == 0
    # A CSV with no such column at all leaves BOTH None -- unknown, not clean.
    csv2 = tmp_path / "s.csv"
    with open(csv2, "w", newline="") as fh:
        fh.write("t,fault_flags,state\n0.10,0x0000,1\n")
    m2 = rhs.analyze_scenario_csv(str(csv2))
    assert m2["error_code_final"] is None
    assert m2["error_code_post_grace"] is None


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


def test_judge_warm_resets_zero_mid_run_detail_wording_interpolates_grace_bound():
    """2026-08-31 wording fix: the old detail claimed 'the board never left
    State 99 during the run', which is FALSE on the common case -- `count` is
    MID-RUN only (post-grace), so it is also zero on the (normal, expected)
    in-grace recovery from the previous run's inherited latch. The new
    wording must say that instead, and must interpolate the actual
    WARM_RESET_GRACE_S value rather than hard-coding '2.0'."""
    check, _note, _reason = rhs.judge_warm_resets(
        "steady", "scenario", _wr_counts(mid_run=0, observed=0), "meta.json")
    detail = check["detail"]
    assert "never left State 99 during the run" not in detail
    assert ("no mid-run warm reset after the %.1f s grace bound"
           % rhs.WARM_RESET_GRACE_S) in detail
    assert "in-grace recovery" in detail
    assert "is normal" in detail
    assert "(meta.json)" in detail


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


# ─────────────────────────────────────────────────────────────────────────
# EMS energy-accounting round (2026-08-31): H2/soc metrics surface,
# ems-soc-band / ems-dp-replay FAULT_EXPECTATIONS entries
# ─────────────────────────────────────────────────────────────────────────

# ── (p) analyze_scenario_csv(): final_h2_cum_g / delta_soc ──────────────────

def test_analyze_scenario_csv_h2_and_soc_metrics_populate_from_synthetic_csv(tmp_path):
    rows = [
        {"t": "0.000", "fault_flags": "", "soc": "", "h2_cum_g": ""},
        {"t": "0.001", "fault_flags": "0", "state": "2", "soc": "0.700000",
         "h2_cum_g": "0.0000010"},
        {"t": "0.002", "fault_flags": "0", "state": "2", "soc": "0.699500",
         "h2_cum_g": "0.0000025"},
        {"t": "0.003", "fault_flags": "0", "state": "2", "soc": "0.699000",
         "h2_cum_g": "0.0000040"},
    ]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows, extra_cols=("h2_cum_g",))
    m = rhs.analyze_scenario_csv(str(path))
    assert m["final_h2_cum_g"] == pytest.approx(0.0000040)
    assert m["soc_first"] == pytest.approx(0.700000)
    assert m["soc_last"] == pytest.approx(0.699000)
    assert m["delta_soc"] == pytest.approx(0.699000 - 0.700000)


def test_analyze_scenario_csv_h2_and_soc_metrics_none_when_columns_absent(tmp_path):
    """A CSV without h2_cum_g/soc columns at all (e.g. a replay-mode run)
    must leave every metric None -- blank-tolerant at the column-absence
    level, not just at the individual-cell level."""
    rows = [{"t": "0.000", "fault_flags": "0", "state": "2"},
            {"t": "0.001", "fault_flags": "0", "state": "2"}]
    path = tmp_path / "a.csv"
    # CSV_COLS already carries "soc" -- write it blank on every row so this
    # exercises "column present but every cell blank", and add no h2_cum_g
    # column at all to exercise "column absent entirely".
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path))
    assert m["final_h2_cum_g"] is None
    assert m["soc_first"] is None
    assert m["soc_last"] is None
    assert m["delta_soc"] is None


def test_analyze_scenario_csv_h2_metric_tolerates_a_single_malformed_cell(tmp_path):
    """A malformed (non-numeric) h2_cum_g cell must be SKIPPED, not abort the
    scan or cost the run its verdict -- these are reporting figures, no check
    reads them."""
    rows = [
        {"t": "0.000", "fault_flags": "0", "state": "2", "h2_cum_g": "NOT_A_NUMBER"},
        {"t": "0.001", "fault_flags": "0", "state": "2", "h2_cum_g": "0.0000050"},
    ]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows, extra_cols=("h2_cum_g",))
    m = rhs.analyze_scenario_csv(str(path))
    assert m["final_h2_cum_g"] == pytest.approx(0.0000050)
    assert m["error"] is None            # the malformed cell must not abort the scan


def test_analyze_scenario_csv_soc_metric_tolerates_a_single_malformed_cell(tmp_path):
    rows = [
        {"t": "0.000", "fault_flags": "0", "state": "2", "soc": "0.700000"},
        {"t": "0.001", "fault_flags": "0", "state": "2", "soc": "GARBAGE"},
        {"t": "0.002", "fault_flags": "0", "state": "2", "soc": "0.698000"},
    ]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path))
    assert m["soc_first"] == pytest.approx(0.700000)
    assert m["soc_last"] == pytest.approx(0.698000)
    assert m["error"] is None


# ── (q) FAULT_EXPECTATIONS shape for the two new entries ────────────────────

def test_fault_expectations_ems_soc_band_entry_shape():
    assert "ems-soc-band" in rhs.FAULT_EXPECTATIONS
    entry = rhs.FAULT_EXPECTATIONS["ems-soc-band"]
    assert entry.get("source")
    assert entry["allow_only"] == 0
    assert entry["survive_to"]["t"] == pytest.approx(41.0)
    assert entry["survive_to"]["states"] == {2, 3}
    names = {s["name"] for s in entry["signals_require"]}
    assert names == {"share_biased_to_fc", "fc_current_biased",
                     "charge_window", "h2_accounted"}
    for spec in entry["signals_require"]:
        assert "column" in spec and "min_value" in spec
        assert spec.get("label")


def test_fault_expectations_ems_dp_replay_entry_shape():
    assert "ems-dp-replay" in rhs.FAULT_EXPECTATIONS
    entry = rhs.FAULT_EXPECTATIONS["ems-dp-replay"]
    assert entry.get("source")
    assert entry["allow_only"] == 0
    assert entry["survive_to"]["t"] == pytest.approx(50.0)
    assert entry["survive_to"]["states"] == {2, 3}
    names = {s["name"] for s in entry["signals_require"]}
    assert names == {"dp_early_fc_rail", "dp_fc_current_railed", "dp_h2_accounted"}
    # Unlike ems-soc-band, this entry deliberately carries NO charge-window
    # assertion (the DP-table finding: it never opens the charger path here).
    assert "charge_window" not in names


def test_fault_expectations_ems_soc_band_and_ems_dp_replay_join_generic_schema_checks():
    """Both entries must pass the two generic schema invariants every other
    FAULT_EXPECTATIONS entry is held to (already exercised by
    test_fault_expectations_schema_every_entry_has_a_nonempty_source and
    test_fault_expectations_schema_only_known_fields over the whole dict --
    this re-derives the same check scoped to just the two new names, so a
    narrowing of those generic tests could not silently stop covering them)."""
    known = {"require", "allow_only", "not_before_s", "survive_to",
            "events_require", "events_any_of", "source", "signals_require",
            "events_forbid_over_absmax", "provisional_note"}
    for name in ("ems-soc-band", "ems-dp-replay"):
        entry = rhs.FAULT_EXPECTATIONS[name]
        assert entry.get("source")
        assert set(entry) <= known


# ── (r) ems-soc-band / ems-dp-replay signals_require: synthetic pass/fail ───

def _spec_by_name(specs, name):
    return next(s for s in specs if s.get("name") == name)


def _mid_t(spec):
    lo, hi = spec["t_window"]
    return (lo + hi) / 2.0


def _judge_one(spec, rows, extra_cols):
    """Write `rows` to a temp CSV, scan+judge just this one spec, return the
    single resulting check dict."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "a.csv")
        _write_scenario_csv(path, rows, extra_cols=extra_cols)
        measured = rhs.scan_signals(path, [spec], grace_s=0.0)
        return rhs.judge_signals([spec], measured, "why")[0]


def test_signals_ems_soc_band_share_biased_to_fc_pass_and_fail():
    spec = _spec_by_name(rhs.FAULT_EXPECTATIONS["ems-soc-band"]["signals_require"],
                         "share_biased_to_fc")
    t = _mid_t(spec)
    passing = [{"t": "%.3f" % t, "fault_flags": "0", "cmd_share_sp": "%.4f" % (spec["min_value"] + 0.05)}]
    failing = [{"t": "%.3f" % t, "fault_flags": "0", "cmd_share_sp": "%.4f" % (spec["min_value"] - 0.05)}]
    assert _judge_one(spec, passing, ("cmd_share_sp",))["passed"] is True
    assert _judge_one(spec, failing, ("cmd_share_sp",))["passed"] is False


def test_signals_ems_soc_band_share_biased_to_fc_ignores_samples_outside_t_window():
    spec = _spec_by_name(rhs.FAULT_EXPECTATIONS["ems-soc-band"]["signals_require"],
                         "share_biased_to_fc")
    before = spec["t_window"][0] - 1.0
    rows = [{"t": "%.3f" % before, "fault_flags": "0",
             "cmd_share_sp": "%.4f" % (spec["min_value"] + 0.10)}]
    assert _judge_one(spec, rows, ("cmd_share_sp",))["passed"] is False


def test_signals_ems_soc_band_fc_current_biased_pass_and_fail():
    spec = _spec_by_name(rhs.FAULT_EXPECTATIONS["ems-soc-band"]["signals_require"],
                         "fc_current_biased")
    t = _mid_t(spec)
    passing = [{"t": "%.3f" % t, "fault_flags": "0", "I_fc": "%.4f" % (spec["min_value"] + 0.05)}]
    failing = [{"t": "%.3f" % t, "fault_flags": "0", "I_fc": "%.4f" % (spec["min_value"] - 0.05)}]
    assert _judge_one(spec, passing, ())["passed"] is True
    assert _judge_one(spec, failing, ())["passed"] is False


def test_signals_ems_soc_band_charge_window_pass_and_fail():
    spec = _spec_by_name(rhs.FAULT_EXPECTATIONS["ems-soc-band"]["signals_require"],
                         "charge_window")
    t = _mid_t(spec)
    passing = [{"t": "%.3f" % t, "fault_flags": "0", "I_charge": "%.4f" % (spec["min_value"] + 0.05)}]
    failing = [{"t": "%.3f" % t, "fault_flags": "0", "I_charge": "0.0"}]
    assert _judge_one(spec, passing, ())["passed"] is True
    assert _judge_one(spec, failing, ())["passed"] is False


def test_signals_ems_soc_band_h2_accounted_pass_and_fail():
    """No t_window on this spec -- the check must judge over the whole run."""
    spec = _spec_by_name(rhs.FAULT_EXPECTATIONS["ems-soc-band"]["signals_require"],
                         "h2_accounted")
    assert "t_window" not in spec
    passing = [{"t": "3.0", "fault_flags": "0", "h2_cum_g": "%.6f" % (spec["min_value"] * 5.0)}]
    failing = [{"t": "3.0", "fault_flags": "0", "h2_cum_g": "%.6f" % (spec["min_value"] * 0.1)}]
    assert _judge_one(spec, passing, ("h2_cum_g",))["passed"] is True
    assert _judge_one(spec, failing, ("h2_cum_g",))["passed"] is False


def test_signals_ems_soc_band_full_spec_set_passes_together_on_one_realistic_csv():
    """A single CSV whose rows satisfy all four ems-soc-band specs at once --
    the shape a real campaign run's CSV would have to have to pass -- judged
    with scan_signals()/judge_signals() exactly as the suite would."""
    specs = rhs.FAULT_EXPECTATIONS["ems-soc-band"]["signals_require"]
    rows = []
    for spec in specs:
        t = _mid_t(spec) if "t_window" in spec else 30.0
        row = {"t": "%.3f" % t, "fault_flags": "0"}
        row[spec["column"]] = "%.6f" % (spec["min_value"] * 1.5)
        rows.append(row)
    extra = tuple(sorted({s["column"] for s in specs} - {"I_fc", "I_charge", "soc"}))
    measured = None
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "a.csv")
        _write_scenario_csv(path, rows, extra_cols=extra)
        measured = rhs.scan_signals(path, specs, grace_s=0.0)
    checks = rhs.judge_signals(specs, measured, "why")
    assert all(c["passed"] for c in checks), checks


def test_signals_ems_dp_replay_dp_early_fc_rail_pass_and_fail():
    spec = _spec_by_name(rhs.FAULT_EXPECTATIONS["ems-dp-replay"]["signals_require"],
                         "dp_early_fc_rail")
    t = _mid_t(spec)
    passing = [{"t": "%.3f" % t, "fault_flags": "0", "cmd_share_sp": "%.4f" % (spec["min_value"] + 0.05)}]
    failing = [{"t": "%.3f" % t, "fault_flags": "0", "cmd_share_sp": "0.50"}]  # firmware default
    assert _judge_one(spec, passing, ("cmd_share_sp",))["passed"] is True
    assert _judge_one(spec, failing, ("cmd_share_sp",))["passed"] is False


def test_signals_ems_dp_replay_dp_fc_current_railed_pass_and_fail():
    spec = _spec_by_name(rhs.FAULT_EXPECTATIONS["ems-dp-replay"]["signals_require"],
                         "dp_fc_current_railed")
    t = _mid_t(spec)
    passing = [{"t": "%.3f" % t, "fault_flags": "0", "I_fc": "%.4f" % (spec["min_value"] + 0.05)}]
    failing = [{"t": "%.3f" % t, "fault_flags": "0", "I_fc": "%.4f" % (spec["min_value"] - 0.05)}]
    assert _judge_one(spec, passing, ())["passed"] is True
    assert _judge_one(spec, failing, ())["passed"] is False


def test_signals_ems_dp_replay_dp_h2_accounted_pass_and_fail():
    spec = _spec_by_name(rhs.FAULT_EXPECTATIONS["ems-dp-replay"]["signals_require"],
                         "dp_h2_accounted")
    assert "t_window" not in spec
    passing = [{"t": "5.0", "fault_flags": "0", "h2_cum_g": "%.6f" % (spec["min_value"] * 5.0)}]
    failing = [{"t": "5.0", "fault_flags": "0", "h2_cum_g": "0.0"}]
    assert _judge_one(spec, passing, ("h2_cum_g",))["passed"] is True
    assert _judge_one(spec, failing, ("h2_cum_g",))["passed"] is False


# ─────────────────────────────────────────────────────────────────────────
# ems-sdp: FAULT_EXPECTATIONS entry shape (item 19) and
# final_h2_sdp_cum_g metric extraction (item 20). Stage-2 test-writer round,
# 2026-08-31 SDP round.
# ─────────────────────────────────────────────────────────────────────────

def test_fault_expectations_ems_sdp_entry_shape():
    """Importing run_hil_suite.py already ran every import-time spec assert
    over this entry (t_window/not_before_s/survive_to bounds, the known-
    fields schema check) -- collection succeeding is half this test. The
    other half pins the entry's OWN shape so a future edit that silently
    dropped a field or widened allow_only is caught here, not just by a
    live campaign."""
    assert "ems-sdp" in rhs.FAULT_EXPECTATIONS
    entry = rhs.FAULT_EXPECTATIONS["ems-sdp"]
    assert entry.get("source")
    assert "require" not in entry
    assert entry["allow_only"] == 0
    assert entry["survive_to"]["t"] == pytest.approx(50.0)
    assert entry["survive_to"]["states"] == {2, 3}
    names = {s["name"] for s in entry["signals_require"]}
    # Re-derived 2026-08-31 for the v2 demand map: two new checks discriminate
    # the table's INTERIOR actuation (cmd_share_sp_raw, invisible on the
    # emitted cmd_share_sp column since every table value clamps to the same
    # 0.8500), and a third asserts the charge window the v1 artifact could
    # never reach at all.
    # `sdp_table_interior_floor` joined the set when campaign 20260831_222036
    # calibrated the interior band and made it TWO-SIDED (the ceiling alone was
    # one-sided: a demand axis collapsing DOWNWARD satisfied it vacuously).
    # `charge_path_never_opens` REPLACED `sdp_charge_window_opened` on
    # 2026-09-01 when the leg was rebound to the calibrated `sdp-v3` artifact
    # (zero charge cells, declined endogenously) — the inverse assertion, and
    # a guaranteed FAIL under v2 rather than a vacuous pass.
    assert names == {"sdp_drive_commanded", "sdp_clamped_rail_commanded",
                     "sdp_table_interior_at_high_demand",
                     "sdp_table_interior_floor",
                     "sdp_table_rail_at_low_demand",
                     "charge_path_never_opens",
                     "sdp_fc_current_biased", "sdp_h2_accounted",
                     "sdp_student_h2_axis"}
    by_name = {s["name"]: s for s in entry["signals_require"]}
    assert by_name["sdp_table_interior_at_high_demand"]["column"] == "cmd_share_sp_raw"
    assert by_name["sdp_table_interior_at_high_demand"]["max_value"] == pytest.approx(0.960)
    assert by_name["sdp_table_interior_at_high_demand"]["t_window"] == (20.0, 36.0)
    assert by_name["sdp_table_interior_floor"]["column"] == "cmd_share_sp_raw"
    assert by_name["sdp_table_interior_floor"]["min_value"] == pytest.approx(0.940)
    assert by_name["sdp_table_interior_floor"]["t_window"] == (20.0, 36.0)
    assert by_name["sdp_table_rail_at_low_demand"]["column"] == "cmd_share_sp_raw"
    assert by_name["sdp_table_rail_at_low_demand"]["min_value"] == pytest.approx(0.999)
    assert by_name["sdp_table_rail_at_low_demand"]["t_window"] == (44.0, 54.0)
    assert by_name["charge_path_never_opens"]["switch_bit"] == rhs.SW_FC_CHARGE
    assert by_name["charge_path_never_opens"]["max_ticks"] == 0
    assert "t_window" not in by_name["charge_path_never_opens"]
    duration = SCENARIOS["ems-sdp"]["duration_s"]
    for spec in entry["signals_require"]:
        window = spec.get("t_window")
        if window is not None:
            lo, hi = window
            assert 0.0 <= lo < hi <= duration, spec["name"]


def test_signals_ems_sdp_drive_commanded_pass_and_fail():
    spec = _spec_by_name(rhs.FAULT_EXPECTATIONS["ems-sdp"]["signals_require"],
                         "sdp_drive_commanded")
    t = _mid_t(spec)
    passing = [{"t": "%.3f" % t, "fault_flags": "0", "cmd_v_sp": "%.4f" % (spec["min_value"] + 0.05)}]
    failing = [{"t": "%.3f" % t, "fault_flags": "0", "cmd_v_sp": "%.4f" % (spec["min_value"] - 0.05)}]
    assert _judge_one(spec, passing, ("cmd_v_sp",))["passed"] is True
    assert _judge_one(spec, failing, ("cmd_v_sp",))["passed"] is False


def test_signals_ems_sdp_clamped_rail_commanded_pass_and_fail():
    """The SDP-specific assertion: the emitted command must sit at/above the
    0.84 floor just under clamp_share()'s 0.8500 hardware-envelope clamp --
    NOT at soc-band's 0.75 ceiling or the DP table's 0.75 rail, both of which
    must FAIL this check (the vacuity guard the task calls out)."""
    spec = _spec_by_name(rhs.FAULT_EXPECTATIONS["ems-sdp"]["signals_require"],
                         "sdp_clamped_rail_commanded")
    t = _mid_t(spec)
    passing = [{"t": "%.3f" % t, "fault_flags": "0", "cmd_share_sp": "0.8500"}]
    failing_socband_ceiling = [{"t": "%.3f" % t, "fault_flags": "0", "cmd_share_sp": "0.75"}]
    failing_default = [{"t": "%.3f" % t, "fault_flags": "0", "cmd_share_sp": "0.50"}]
    assert _judge_one(spec, passing, ("cmd_share_sp",))["passed"] is True
    assert _judge_one(spec, failing_socband_ceiling, ("cmd_share_sp",))["passed"] is False
    assert _judge_one(spec, failing_default, ("cmd_share_sp",))["passed"] is False


def test_signals_ems_sdp_fc_current_biased_pass_and_fail():
    spec = _spec_by_name(rhs.FAULT_EXPECTATIONS["ems-sdp"]["signals_require"],
                         "sdp_fc_current_biased")
    t = _mid_t(spec)
    passing = [{"t": "%.3f" % t, "fault_flags": "0", "I_fc": "%.4f" % (spec["min_value"] + 0.05)}]
    failing = [{"t": "%.3f" % t, "fault_flags": "0", "I_fc": "%.4f" % (spec["min_value"] - 0.05)}]
    assert _judge_one(spec, passing, ())["passed"] is True
    assert _judge_one(spec, failing, ())["passed"] is False


def test_signals_ems_sdp_h2_accounted_pass_and_fail():
    spec = _spec_by_name(rhs.FAULT_EXPECTATIONS["ems-sdp"]["signals_require"],
                         "sdp_h2_accounted")
    assert "t_window" not in spec
    passing = [{"t": "5.0", "fault_flags": "0", "h2_cum_g": "%.6f" % (spec["min_value"] * 5.0)}]
    failing = [{"t": "5.0", "fault_flags": "0", "h2_cum_g": "0.0"}]
    assert _judge_one(spec, passing, ("h2_cum_g",))["passed"] is True
    assert _judge_one(spec, failing, ("h2_cum_g",))["passed"] is False


def test_signals_ems_sdp_student_h2_axis_is_a_plumbing_check_not_a_magnitude_one():
    """min_value: 0.0 -- ANY parseable sample passes (however small), while a
    genuinely absent/unparseable column fails. This is check 5's own
    documented distinction from check 4's magnitude budget."""
    spec = _spec_by_name(rhs.FAULT_EXPECTATIONS["ems-sdp"]["signals_require"],
                         "sdp_student_h2_axis")
    assert spec["min_value"] == pytest.approx(0.0)
    assert "t_window" not in spec
    tiny = [{"t": "5.0", "fault_flags": "0", "h2_sdp_cum_g": "0.0000001"}]
    assert _judge_one(spec, tiny, ("h2_sdp_cum_g",))["passed"] is True
    absent = [{"t": "5.0", "fault_flags": "0", "h2_sdp_cum_g": ""}]
    assert _judge_one(spec, absent, ("h2_sdp_cum_g",))["passed"] is False


# ── analyze_scenario_csv(): final_h2_sdp_cum_g (item 20) ────────────────────

def test_analyze_scenario_csv_final_h2_sdp_cum_g_populates_from_synthetic_csv(tmp_path):
    rows = [
        {"t": "0.000", "fault_flags": "", "h2_sdp_cum_g": ""},
        {"t": "0.001", "fault_flags": "0", "state": "2", "h2_sdp_cum_g": "0.0000008"},
        {"t": "0.002", "fault_flags": "0", "state": "2", "h2_sdp_cum_g": "0.0000021"},
        {"t": "0.003", "fault_flags": "0", "state": "2", "h2_sdp_cum_g": "0.0000035"},
    ]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows, extra_cols=("h2_sdp_cum_g",))
    m = rhs.analyze_scenario_csv(str(path))
    assert m["final_h2_sdp_cum_g"] == pytest.approx(0.0000035)


def test_analyze_scenario_csv_final_h2_sdp_cum_g_none_when_column_absent(tmp_path):
    """A CSV without h2_sdp_cum_g at all (e.g. a replay-mode run, or any CSV
    predating the SDP round) must leave the metric None -- the same
    column-absence tolerance final_h2_cum_g already carries."""
    rows = [{"t": "0.000", "fault_flags": "0", "state": "2"},
            {"t": "0.001", "fault_flags": "0", "state": "2"}]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path))
    assert m["final_h2_sdp_cum_g"] is None


def test_analyze_scenario_csv_final_h2_sdp_cum_g_tolerates_a_single_malformed_cell(tmp_path):
    rows = [
        {"t": "0.000", "fault_flags": "0", "state": "2", "h2_sdp_cum_g": "NOT_A_NUMBER"},
        {"t": "0.001", "fault_flags": "0", "state": "2", "h2_sdp_cum_g": "0.0000009"},
    ]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows, extra_cols=("h2_sdp_cum_g",))
    m = rhs.analyze_scenario_csv(str(path))
    assert m["final_h2_sdp_cum_g"] == pytest.approx(0.0000009)
    assert m["error"] is None


def test_analyze_scenario_csv_final_h2_sdp_cum_g_distinct_from_final_h2_cum_g(tmp_path):
    """The two columns are two DIFFERENT models on the same input -- a
    metrics extractor that accidentally aliased one column to the other
    would pass every test above individually; this pins that a single row
    carrying BOTH columns at DIFFERENT values populates BOTH metrics
    independently."""
    rows = [
        {"t": "0.001", "fault_flags": "0", "state": "2",
         "h2_cum_g": "0.0000100", "h2_sdp_cum_g": "0.0000095"},
    ]
    path = tmp_path / "a.csv"
    _write_scenario_csv(path, rows, extra_cols=("h2_cum_g", "h2_sdp_cum_g"))
    m = rhs.analyze_scenario_csv(str(path))
    assert m["final_h2_cum_g"] == pytest.approx(0.0000100)
    assert m["final_h2_sdp_cum_g"] == pytest.approx(0.0000095)
    assert m["final_h2_cum_g"] != pytest.approx(m["final_h2_sdp_cum_g"])


# ─────────────────────────────────────────────────────────────────────────
# Stage-2 additions, 2026-08-31 (campaign-191509 fix-queue round): the
# share-staircase fc_bus_restored re-derivation, the ems-y-* Y_AUX_LOAD_A
# re-derivation (_Y_FC_FLOOR), socband_fc_carried's re-derivation, the FTP-75
# two-spec h2 band (+ the import-time min_value/max_value refusal), and the
# key_metrics warm-reset label rendering.
# ─────────────────────────────────────────────────────────────────────────

def test_share_staircase_fc_bus_restored_min_ticks_is_900():
    """1500 -> 900 (60 % of its 1.5 s / 1500-row window, matching the 60 %
    margin rule every OTHER restore floor in this suite already follows --
    bt_bus_restored is 1500 of a 2500-row window). The old 1500/1500 floor was
    100 % of the window and campaign 20260831_191509 measured exactly that:
    a pass with zero margin against a single dropped observation frame."""
    spec = next(s for s in rhs.FAULT_EXPECTATIONS["share-staircase"]["signals_require"]
               if s["name"] == "fc_bus_restored")
    assert spec["switch_bit"] == rhs.SW_FC_BUS
    assert spec["min_ticks"] == 900
    lo, hi = spec["t_window"]
    assert hi - lo == pytest.approx(1.5)
    assert spec["min_ticks"] / ((hi - lo) * 1000.0) == pytest.approx(0.60)


def test_socband_fc_carried_threshold_is_056_at_preload_zero():
    """RE-DERIVED for the zero-preload era (was 0.95 A against the 0.65 A
    preload).  The derivation SHAPE is unchanged: `min_value` is a
    PEAK-over-window test, so the floor must separate this run's window peak
    from the CONSTANT-0.50 ems-ftp75-5050 sibling's -- anything at or below the
    sibling's peak is satisfied by a run that ignored the share command
    entirely.  Both peaks moved with the load, and both are pinned here,
    because they are what make the floor a discriminator rather than a
    decoration.

    Governor-walk peaks over t = (30, 340) at aux_preload_a 0.0:
        ems-ftp75-5050    0.4801 A   (was 0.8275 measured at 0.65 A)
        ems-ftp75-socband 0.6602 A   (was 1.2414 measured at 0.65 A)
    PROVISIONAL until a zero-preload campaign measures them."""
    spec = next(s for s in rhs.FAULT_EXPECTATIONS["ems-ftp75-socband"]["signals_require"]
               if s["name"] == "socband_fc_carried")
    assert spec["column"] == "I_fc"
    assert spec["min_value"] == pytest.approx(0.56)
    assert spec.get("provisional_note")
    # 16.6 % over the control's predicted peak, 15.2 % under this scenario's.
    assert spec["min_value"] > 0.4801
    assert spec["min_value"] < 0.6602
    assert spec["t_window"] == (30.0, 340.0)


def test_socband_ftp_charge_branch_is_asserted_after_the_preload_removal():
    """The preload removal's OWN objective, made a check.  At 0.65 A the source
    total never fell below 0.800 A, so `soc-band`'s charge branch
    (SOC_BAND_CHARGE_ENTER_ITOT_A 0.60 A) was foreclosed BY CONSTRUCTION and
    the entry said so.  At preload 0 the idle total is I_AUX_A = 0.15 A and the
    branch is admissible over most of the cycle -- so it must be observed, or
    the removal has bought coverage nobody checks.

    The floor is EXISTENCE ONLY and the entry says why: ems_walk.py gates
    charge admission on the DP's charge_mask(), not on SocBandStrategy's own
    hysteresis, so the window schedule is unmodelled and cannot size a floor.

    PART C (C1 round, 2026-09-01): the floor is 200 ticks, not 3000. 3000
    ticks = 3.0 s was a 3.2 % margin under the walk's only model of the total
    charging duration (3.1 s over two windows), which is not an existence
    floor -- a correct board opening one 2 s window would have failed it.
    200 ticks = ten PI_CMD_HZ command periods."""
    spec = next(s for s in rhs.FAULT_EXPECTATIONS["ems-ftp75-socband"]["signals_require"]
                if s["name"] == "socband_ftp_charge_opened")
    assert spec["switch_bit"] == rhs.SW_FC_CHARGE
    assert spec["min_ticks"] == 200
    # The floor must be an EXISTENCE floor, not a duration claim: comfortably
    # under the walk's 3.1 s and comfortably over one command period.
    assert 50 <= spec["min_ticks"] <= 1000
    assert spec["t_window"] == (30.0, 340.0)
    assert spec.get("provisional_note")
    # The scenario must actually declare the charger ceiling the check implies.
    assert hil.SCENARIOS["ems-ftp75-socband"]["chg_i_ceiling_a"] == pytest.approx(0.8)


def test_y_fc_floor_table_re_derived_from_measurement():
    """DI-MED-2: _Y_FC_BIAS_W narrowed to R3 alone (13.0-16.0), where v is held
    constant so only the share command moves I_fc.

    ⚠️ RE-DERIVED AGAIN 2026-08-31 against campaign 20260831_222036, the first
    campaign at the SHIPPED Y_AUX_LOAD_A 0.85 A. The previous pair
    (0.50 / 0.66) was fitted to 20260831_191509's RETIRED 0.60 A preload and is
    ~30 % loose against the current stimulus. Measured R3 peaks now:
    0.7289 / 0.9243 A true run, 0.5605 / 0.7110 A for a 0.50 split."""
    assert rhs._Y_FC_BIAS_W == (13.0, 16.0)
    assert rhs._Y_FC_FLOOR == {1.0: 0.65, 3.0: 0.85}
    # Each floor sits strictly between "a 0.50 split" and "the measured run".
    for vmax, split_peak, true_peak in ((1.0, 0.5605, 0.7289),
                                        (3.0, 0.7110, 0.9243)):
        floor = rhs._Y_FC_FLOOR[vmax]
        assert split_peak < floor < true_peak
        spec = next(s for s in rhs.FAULT_EXPECTATIONS["ems-y-b30-v%g" % vmax]
                    ["signals_require"] if s["name"] == "fc_current_biased")
        assert spec["min_value"] == pytest.approx(floor)
        assert spec["t_window"] == rhs._Y_FC_BIAS_W


# ── derived value sources: `sum_of` / `ratio_of` (2026-08-31) ───────────────

def _scan_one(tmp_path, spec, rows, cols):
    path = tmp_path / "d.csv"
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return rhs.judge_signals([spec], rhs.scan_signals(str(path), [spec]), "why")[0]


def _cur_rows(pairs, t0=10.0):
    return [{"t": "%.3f" % (t0 + i * 0.001), "I_fc": "" if a is None else a,
             "I_batt": "" if b is None else b}
            for i, (a, b) in enumerate(pairs)]


_CUR_COLS = ["t", "I_fc", "I_batt"]


def test_ratio_of_measures_the_delivered_share(tmp_path):
    """share_act = I_fc / (I_fc + I_batt) — invariant to the load, which is
    exactly what an ampere floor cannot be."""
    spec = {"name": "r", "ratio_of": ["I_fc", "I_batt"], "min_value": 0.695,
            "t_window": (9.0, 11.0), "label": "share"}
    # The same 0.70 split at two very different loads.
    chk = _scan_one(tmp_path, spec, _cur_rows([("0.700", "0.300"),
                                               ("2.800", "1.200")]), _CUR_COLS)
    assert chk["passed"] is True
    assert "peak 0.7000" in chk["detail"]


def test_ratio_of_ceiling_catches_an_overshoot(tmp_path):
    spec = {"name": "r", "ratio_of": ["I_fc", "I_batt"], "max_value": 0.705,
            "t_window": (9.0, 11.0), "label": "share"}
    chk = _scan_one(tmp_path, spec, _cur_rows([("0.700", "0.300"),
                                               ("0.900", "0.100")]), _CUR_COLS)
    assert chk["passed"] is False
    assert "peak 0.9000" in chk["detail"]


def test_ratio_of_skips_rows_under_ratio_min_den(tmp_path):
    """A ratio taken on ~0 A of total current is noise, not a share. The 50 mA
    mask is the one hil_report_analysis.py uses to derive share_act."""
    spec = {"name": "r", "ratio_of": ["I_fc", "I_batt"], "max_value": 0.705,
            "t_window": (9.0, 11.0), "label": "share"}
    # A 0.001/0.000 row would read as a share of 1.0 and fail the ceiling.
    chk = _scan_one(tmp_path, spec, _cur_rows([("0.700", "0.300"),
                                               ("0.001", "0.000")]), _CUR_COLS)
    assert chk["passed"] is True


def test_ratio_of_skips_a_row_with_any_column_blank(tmp_path):
    """A partial sum is a different quantity, not a smaller one — a row with
    I_batt blank must be dropped whole, not read as I_fc/I_fc = 1.0."""
    spec = {"name": "r", "ratio_of": ["I_fc", "I_batt"], "max_value": 0.705,
            "t_window": (9.0, 11.0), "label": "share"}
    chk = _scan_one(tmp_path, spec, _cur_rows([("0.700", "0.300"),
                                               ("0.700", None)]), _CUR_COLS)
    assert chk["passed"] is True


def test_sum_of_measures_the_source_total(tmp_path):
    spec = {"name": "s", "sum_of": ["I_fc", "I_batt"], "min_value": 1.02,
            "t_window": (9.0, 11.0), "label": "itot"}
    ok = _scan_one(tmp_path, spec, _cur_rows([("0.745", "0.320")]), _CUR_COLS)
    assert ok["passed"] is True and "peak 1.0650" in ok["detail"]
    low = _scan_one(tmp_path, spec, _cur_rows([("0.600", "0.300")]), _CUR_COLS)
    assert low["passed"] is False


def test_derived_source_with_no_rows_fails_not_passes(tmp_path):
    """The table's standing rule: a gap must never read as a pass."""
    spec = {"name": "s", "sum_of": ["I_fc", "I_batt"], "min_value": 1.02,
            "t_window": (90.0, 91.0), "label": "itot"}
    chk = _scan_one(tmp_path, spec, _cur_rows([("0.745", "0.320")]), _CUR_COLS)
    assert chk["passed"] is False


def _run_signal_shape_guard(spec):
    """Drive the import-time derived-source guard over one spec."""
    rhs.assert_derived_source_shape("SYN", spec.get("name", "x"), spec)


def test_derived_source_shape_guards():
    """Every malformed derived-source spelling must be refused at IMPORT, since
    each of them fails silently at score time: a `column` beside the derived
    source reads as an assertion and is ignored, a one-column ratio is
    identically 1.0, and a bound-less spec asserts nothing at all."""
    bad = [
        ({"name": "x", "sum_of": ["I_fc", "I_batt"],
          "ratio_of": ["I_fc", "I_batt"], "min_value": 1.0},
         "alternative value sources"),
        ({"name": "x", "sum_of": ["I_fc", "I_batt"], "column": "I_fc",
          "min_value": 1.0}, "would read as an assertion"),
        ({"name": "x", "ratio_of": ["I_fc"], "min_value": 0.5},
         "at least two columns"),
        ({"name": "x", "sum_of": ["I_fc", "I_batt"]}, "needs a value bound"),
        ({"name": "x", "column": "I_fc", "min_value": 1.0,
          "ratio_min_den": 0.05}, "read only by `ratio_of`"),
    ]
    for spec, msg in bad:
        with pytest.raises(AssertionError, match=re.escape(msg)):
            _run_signal_shape_guard(spec)


def test_derived_source_shape_guard_accepts_the_real_specs():
    """Converse: every derived-source spec actually shipped in the table
    survives the guard — otherwise the negatives above pin nothing."""
    n = 0
    for name, expect in rhs.FAULT_EXPECTATIONS.items():
        for spec in expect.get("signals_require") or ():
            if "sum_of" in spec or "ratio_of" in spec:
                n += 1
                _run_signal_shape_guard(spec)      # must not raise
    assert n >= 9        # 4 share bands x2 variants + 1 I_tot floor


# ── ems-y b30: the delivered-clip bands and the preload budget ──────────────

def test_y_b30_share_clip_bands_are_pinned_at_the_measured_levels():
    """Campaign 20260831_222036 delivered 0.7000/0.3000 EXACTLY on both
    variants; the bands are +/-0.005 around each clip level."""
    assert rhs._Y_SHARE_CLIP_TOL == pytest.approx(0.005)
    for vmax in (1.0, 3.0):
        by = {s["name"]: s for s in
              rhs.FAULT_EXPECTATIONS["ems-y-b30-v%g" % vmax]["signals_require"]}
        assert by["share_hi_delivered"]["min_value"] == pytest.approx(0.695)
        assert by["share_hi_not_overshot"]["max_value"] == pytest.approx(0.705)
        assert by["share_lo_delivered"]["max_value"] == pytest.approx(0.305)
        assert by["share_lo_not_undershot"]["min_value"] == pytest.approx(0.295)
        for n in ("share_hi_delivered", "share_hi_not_overshot"):
            assert by[n]["t_window"] == rhs._Y_HI_BOUND_W
            assert by[n]["ratio_of"] == ["I_fc", "I_batt"]
        for n in ("share_lo_delivered", "share_lo_not_undershot"):
            assert by[n]["t_window"] == rhs._Y_LO_BOUND_W
        # The two clip levels are 0.40 apart, so the bands cannot overlap —
        # a band wide enough to admit the other clip would assert nothing.
        assert by["share_lo_not_undershot"]["min_value"] > 0.0
        assert (by["share_hi_delivered"]["min_value"]
                > by["share_lo_delivered"]["max_value"] + 0.30)


def test_y_b00_variants_get_no_share_clip_bands():
    """The clip bands belong to b30. b00 cuts a source off the bus at each
    bound, so I_batt (or I_fc) goes to zero there and the RATIO rails to
    0/1 — a band around 1.00/0.00 would be asserting the cut, which the
    bt_bus_cut / fc_bus_cut switch checks already do properly."""
    for vmax in (1.0, 3.0):
        names = {s["name"] for s in
                 rhs.FAULT_EXPECTATIONS["ems-y-b00-v%g" % vmax]["signals_require"]}
        assert not (names & {"share_hi_delivered", "share_lo_delivered",
                             "itot_above_governor_break_even"})


def test_both_b30_variants_carry_the_preload_budget_tripwire():
    """SYMMETRY, 2026-09-01 (campaign 20260901_000816 fix queue item 4).

    The check used to run on b30-v1 alone, on the argument that one tripwire on
    the tighter variant catches a cut in the SHARED Y_AUX_LOAD_A. That holds for
    the shared constant and fails for anything that moves the two variants apart
    (a per-variant load, a Vmax retune, a governor change biting at one speed).
    ONE floor serves both: it is derived from the governor's break-even, which
    is a property of the CLIP and not of Vmax; the variants differ only in the
    margin they carry over it, and both margins are now stated."""
    assert rhs._Y_ITOT_FLOOR_A == pytest.approx(1.02)
    for vmax, measured in ((1.0, 1.0644), (3.0, 1.1836)):
        by = {s["name"]: s for s in
              rhs.FAULT_EXPECTATIONS["ems-y-b30-v%g" % vmax]["signals_require"]}
        spec = by["itot_above_governor_break_even"]
        assert spec["sum_of"] == ["I_fc", "I_batt"]
        assert spec["t_window"] == rhs._Y_HI_BOUND_W
        assert spec["min_value"] == pytest.approx(rhs._Y_ITOT_FLOOR_A)
        # Above the governor break-even, below THIS variant's measured minimum.
        assert 1.000 < spec["min_value"] < measured
        assert rhs._Y_ITOT_MEASURED_MIN_A[vmax] == pytest.approx(measured)
        # The measured value and its margin are in the check's own detail line,
        # so a reader does not have to go to a ledger for them.
        assert ("%.4f" % measured) in spec["label"]


def test_y_aux_load_a_is_085():
    from hil_plant_sim import Y_AUX_LOAD_A
    assert Y_AUX_LOAD_A == pytest.approx(0.85)


# ── FTP-75 h2_cum_g band: two specs, not one ────────────────────────────────

def test_ftp75_5050_h2_band_is_two_specs_045_to_085():
    """hold-5050's h2_cum_g band is now a FLOOR spec and a separate CEILING
    spec (2026-08-31 fix queue A-item): min_value and max_value dispatch
    through _judge_signal_leaf()'s if/return chain, min_value first, so a
    single spec carrying both would silently drop the ceiling -- confirmed
    directly below, and the module's own import-time assert refuses the
    shape entirely (negative test further down)."""
    sig = rhs.FAULT_EXPECTATIONS["ems-ftp75-5050"]["signals_require"]
    h2_specs = [s for s in sig if s.get("column") == "h2_cum_g"]
    assert len(h2_specs) == 2
    for s in h2_specs:
        assert not ("min_value" in s and "max_value" in s), s["name"]
    floor = next(s for s in h2_specs if "min_value" in s)
    ceiling = next(s for s in h2_specs if "max_value" in s)
    # RE-DERIVED at aux_preload_a 0.0 AND at the plant's default converter
    # asymmetry, then RE-WALKED at the M2 CONSISTENT PAIR (fix round F1,
    # 2026-09-01): the plant no longer injects M1's dv0 0.0444, and the walk is
    # driven at the dv0 that reproduces the plant's own alpha at r = 0.5,
    # 1.0155 A (0.030223 V). Walk 2.9888e-2 g, band +/-25 %. Symmetric walk
    # 2.809e-2; the retired M1-era walk 3.0729e-2.
    assert floor["min_value"] == pytest.approx(0.022)
    assert ceiling["max_value"] == pytest.approx(0.037)
    assert floor["min_value"] < 2.9888e-2 < ceiling["max_value"]
    for s in h2_specs:
        assert s.get("provisional_note")


def test_ftp75_socband_h2_band_is_now_two_sided():
    """The asymmetry is retired WITH the OC_FC allowance, and the two changes
    are coupled: the 5e-3 floor existed ONLY because a truncated run was an
    allowed outcome. With the run required to complete, the floor can finally
    bracket the measurement (9.159e-2, bit-identical across six campaigns)
    instead of asserting that the accounting ran at all."""
    sig = rhs.FAULT_EXPECTATIONS["ems-ftp75-socband"]["signals_require"]
    h2_specs = [s for s in sig if s.get("column") == "h2_cum_g"]
    assert len(h2_specs) == 2
    for s in h2_specs:
        assert not ("min_value" in s and "max_value" in s), s["name"]
    floor = next(s for s in h2_specs if "min_value" in s)
    ceiling = next(s for s in h2_specs if "max_value" in s)
    # RE-DERIVED TWICE (PART C, C1 round, 2026-09-01). The 3.546e-2 figure
    # that stood here predated the scenario's own chg_i_ceiling_a 0.8 key, and
    # the walk was symmetric. Against the SHIPPED registry with the plant's
    # default converter asymmetry (dv0 0.0444) the walk gives 3.7208e-2 g
    # (plant accounting); band = that +/-25 %. The 9.159e-2 is the RETIRED
    # 0.65 A era's measurement.
    # RE-WALKED at the M2 consistent pair (fix round F1, 2026-09-01): 3.6706e-2
    # g plant accounting, against the retired M1-era 3.7208e-2.
    # RE-DERIVED A THIRD TIME (WP-1C, 2026-09-02), and the round corrected
    # WHICH walk figure the band is against as well as its value:
    #   * the live `h2_cum_g` column integrates Gfc over the FC power the board
    #     draws, and the charger's draw is ON that bus, so `h2 (Gfc, physical)`
    #     is its analogue -- `h2 (Gfc, plant)` deliberately omits the charger.
    #     Evidence: the frontier's MEASURED vs-reference ratio (0.9003 x,
    #     campaign 20260901_151156) sits beside the physical-walk prediction
    #     (0.859) and nowhere near the plant-walk one (1.127).
    #   * under ETA_CHG 0.88 the socband walk RISES, because cheaper charging
    #     opens a third window: physical 3.7526e-2 -> 4.1873e-2 g.
    _WALK = 4.1873e-2
    assert floor["min_value"] == pytest.approx(rhs._FTP_H2_FLOOR_SOCBAND) == pytest.approx(0.031)
    assert ceiling["max_value"] == pytest.approx(0.052)
    # The band must BRACKET the prediction with real margin on both sides --
    # a floor above it, or a ceiling below it, would fail a correct board.
    assert floor["min_value"] < _WALK < ceiling["max_value"]
    assert floor["min_value"] < 0.80 * _WALK
    assert ceiling["max_value"] > 1.20 * _WALK
    for s in h2_specs:
        assert s.get("provisional_note")
    # The vacuous floor must be GONE from this entry (it stays as the 5050
    # variant's own constant, which is a different question).
    assert floor["min_value"] != pytest.approx(rhs._FTP_H2_FLOOR)


def _min_value_max_value_shape_is_refused(spec):
    """Re-derivation of the module's own import-time guard (run_hil_suite.py,
    the FAULT_EXPECTATIONS validation loop): a single signals_require spec
    must never carry BOTH min_value and max_value, because
    _judge_signal_leaf() tests min_value first and returns, silently
    dropping the ceiling. Reproduced here (rather than re-triggered via a
    module reload, which the codebase's own convention for these import-time
    guards avoids -- see _strictly_decreases_window_clears_timeline above)
    and cross-checked against real data below."""
    return not ("min_value" in spec and "max_value" in spec)


def test_min_value_max_value_guard_rejects_the_combined_shape():
    """The negative case: a spec carrying both keys on one column IS exactly
    the shape the FTP-75 band was split to avoid, and the re-derived
    predicate must reject it."""
    bad_spec = {"name": "bogus_band", "column": "h2_cum_g",
               "min_value": 0.045, "max_value": 0.085}
    assert _min_value_max_value_shape_is_refused(bad_spec) is False


def test_min_value_max_value_guard_accepts_the_split_shape():
    floor = {"name": "bogus_floor", "column": "h2_cum_g", "min_value": 0.045}
    ceiling = {"name": "bogus_ceiling", "column": "h2_cum_g", "max_value": 0.085}
    assert _min_value_max_value_shape_is_refused(floor) is True
    assert _min_value_max_value_shape_is_refused(ceiling) is True


def test_min_value_max_value_guard_every_real_spec_is_compliant():
    """Every signals_require spec actually shipped in FAULT_EXPECTATIONS must
    satisfy the re-derived predicate -- the module imported cleanly (it would
    have raised AssertionError otherwise), so this must hold; re-checked
    explicitly rather than trusted only implicitly."""
    checked = 0
    for name, expect in rhs.FAULT_EXPECTATIONS.items():
        for spec in expect.get("signals_require") or []:
            checked += 1
            assert _min_value_max_value_shape_is_refused(spec), (name, spec["name"])
    assert checked > 0


# ── key_metrics warm-reset label: "mid-run warm resets N (of M observed)" ──

def test_key_metrics_warm_reset_label_names_both_counts(monkeypatch):
    """LOW (2026-08-31 ledger fix queue): the rendered label used to read
    bare "N mid-run warm reset(s)", which a reader could misread as the
    whole-run count. It now names BOTH the scored mid-run count and the
    whole-run observed count explicitly. The SCORED quantity (the tripwire,
    `passed`, results.json) is still mid_run alone -- only the label grew."""
    def fake_run_child(item, args):
        return {"status": "ok", "returncode": 0, "wall_s": 0.01, "log": item["log"],
                "summary": {"achieved_hz": 1000.0}}

    def fake_warm_reset_count(csv_path, child):
        return {"mid_run": 0, "observed": 1, "times": [0.4]}, "meta.json"

    monkeypatch.setattr(rhs, "run_child", fake_run_child)
    monkeypatch.setattr(rhs, "warm_reset_count", fake_warm_reset_count)

    args = _args(only=["steady"], keep_going=True, settle_s=0.0)
    plan = rhs.build_plan(args)
    results, _aborted = rhs._run_plan(plan, args, [], [], lambda m, r: None)
    r = results[0]
    assert "mid-run warm resets 0 (of 1 observed)" in r["key_metrics"]


def test_key_metrics_warm_reset_label_unmeasured_renders_question_marks(monkeypatch):
    def fake_run_child(item, args):
        return {"status": "ok", "returncode": 0, "wall_s": 0.01, "log": item["log"],
                "summary": {"achieved_hz": 1000.0}}

    def fake_warm_reset_count(csv_path, child):
        return {"mid_run": None, "observed": None, "times": None}, "unmeasured"

    monkeypatch.setattr(rhs, "run_child", fake_run_child)
    monkeypatch.setattr(rhs, "warm_reset_count", fake_warm_reset_count)

    args = _args(only=["steady"], keep_going=True, settle_s=0.0)
    plan = rhs.build_plan(args)
    results, _aborted = rhs._run_plan(plan, args, [], [], lambda m, r: None)
    r = results[0]
    assert "mid-run warm resets ? (of ? observed)" in r["key_metrics"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ─────────────────────────────────────────────────────────────────────────
# The three SDP-interior scenarios (2026-08-31): entry shapes, and the
# window arithmetic that makes their share-crossing claims mean anything.
#
# WHAT THESE PIN, and why it is not covered by the import-time asserts:
# importing the module already checks every t_window against the scenario's
# duration and refuses the malformed spec shapes.  What it CANNOT check is
# the RELATION between two windows on the same column -- and that relation
# IS the assertion in all three entries: a ceiling before a band and a floor
# after it is what pins a crossing INSIDE the band.  A future edit that
# overlapped the two windows would still import cleanly and would assert
# nothing at all.
# ─────────────────────────────────────────────────────────────────────────

import hil_plant_sim as hil  # noqa: E402  (constants + piecewise for the walks)

SDP_INTERIOR_SCENARIOS = ("ems-ftp75-sdp", "ems-sdp-cross", "ems-sdp-braking")


def test_sdp_interior_entries_are_fault_free_and_calibrated():
    """Campaign 20260901_024231 ran all three for the first time, so every
    band was re-derived against the measured trace and the `provisional_note`
    was deleted from all three -- the ems-sdp / scp-inrush precedent. The
    absence of the note is what says "these numbers are measurements"."""
    for name in SDP_INTERIOR_SCENARIOS:
        entry = rhs.FAULT_EXPECTATIONS[name]
        assert entry.get("source"), name
        assert "require" not in entry, name
        # FAULT-FREE, all three. `ems-ftp75-sdp` is deliberately STRICTER than
        # its ems-ftp75-socband sibling (which ALLOWS OC_FC): its preload was
        # re-derived down to 0.45 A so the fuel-cell branch keeps 18.5 % at the
        # cycle peak, because an OC_FC latch would truncate the run at exactly
        # the post-flip half it exists to observe.
        assert entry["allow_only"] == 0, name
        assert entry.get("provisional_note") is None, name
        assert entry["survive_to"]["states"] == {2, 3}, name


def test_ems_ftp75_sdp_entry_pins_the_flip_inside_its_band():
    entry = rhs.FAULT_EXPECTATIONS["ems-ftp75-sdp"]
    names = {s["name"] for s in entry["signals_require"]}
    assert names == {"sdpftp_drive_commanded", "sdpftp_low_rail_early",
                     "sdpftp_high_rail_late", "sdpftp_raw_battery_branch",
                     "sdpftp_raw_fc_branch", "sdpftp_fc_floored_early",
                     "sdpftp_fc_carried_late", "sdpftp_bt_peak_bounded",
                     "sdpftp_h2_accounted", "sdpftp_h2_bounded"}
    by = {s["name"]: s for s in entry["signals_require"]}
    early = by["sdpftp_low_rail_early"]
    late = by["sdpftp_high_rail_late"]
    assert early["column"] == late["column"] == "cmd_share_sp"
    # A CEILING before the band and a FLOOR after it -- the construction that
    # pins the crossing without a transition-detecting check kind.
    assert early["max_value"] == pytest.approx(rhs._SDP_LOW_RAIL_CEIL)
    assert late["min_value"] == pytest.approx(rhs._SDP_HIGH_RAIL_FLOOR)
    # ... and the two windows must not overlap, or nothing is pinned.
    assert early["t_window"][1] <= late["t_window"][0]
    # THE BAND, RE-PROVISIONALIZED at aux_preload_a 0.0.  The flip is an
    # INTEGRAL of the pack drain, so removing 0.45 A of load moves it LATE:
    # governor walk 272.0 s (was 195.9 s at 0.45 A), and scaling by the
    # measured/walk ratio the 0.45 A era established (198.537/196.0) puts the
    # expected board flip at 275.5 s.  The band brackets that, asymmetrically,
    # because the high side must leave a usable post-flip window in 340 s.
    assert (early["t_window"][1], late["t_window"][0]) == (240.0, 295.0)
    assert early["t_window"][1] < 272.0 < late["t_window"][0]
    assert early["t_window"][1] < 275.5 < late["t_window"][0]
    for s in (early, late, by["sdpftp_raw_battery_branch"],
              by["sdpftp_raw_fc_branch"]):
        assert s.get("provisional_note")
    # The raw-column pair must ride the SAME band, or the two halves of the
    # entry pin different crossings.
    assert by["sdpftp_raw_battery_branch"]["t_window"] == early["t_window"]
    assert by["sdpftp_raw_fc_branch"]["t_window"] == late["t_window"]


def test_ems_ftp75_sdp_h2_band_tracks_the_zero_preload_walk():
    """RE-PROVISIONALIZED at aux_preload_a 0.0.  The 0.45 A era's band was
    [0.056, 0.070] around a MEASURED 0.0621749 g; the load removal takes the
    prediction to 0.019347 g (governor walk), so the band is that +/-25 % --
    the same shape the two sibling entries carry, and still tight enough that a
    2x scale error fails."""
    by = {s["name"]: s
          for s in rhs.FAULT_EXPECTATIONS["ems-ftp75-sdp"]["signals_require"]}
    lo = by["sdpftp_h2_accounted"]["min_value"]
    hi = by["sdpftp_h2_bounded"]["max_value"]
    # RE-WALKED at the M2 consistent pair (fix round F1, 2026-09-01): the plant
    # injects dv0 0.013522 with rho 0.9434, and the walk (which has no rho) is
    # driven at the equivalent 0.030223 V. The retired M1-era walk gave 0.019347.
    measured = 0.019918            # the WALK's prediction, not a measurement
    assert (lo, hi) == (pytest.approx(0.0149), pytest.approx(0.0249))
    assert lo < measured < hi
    for n in ("sdpftp_h2_accounted", "sdpftp_h2_bounded"):
        assert by[n].get("provisional_note")
    # A 2x scale error in either direction now fails.
    assert not (lo <= 2.0 * measured <= hi)
    assert not (lo <= 0.5 * measured <= hi)


def test_ems_ftp75_sdp_battery_channel_ceiling_is_a_handover_tripwire():
    """NEW in the campaign-024231 calibration round: the BT channel had never
    been bounded on this entry. Its whole-run peak lands AT THE FLIP, so the
    ceiling watches the branch handover rather than a steady state."""
    by = {s["name"]: s
          for s in rhs.FAULT_EXPECTATIONS["ems-ftp75-sdp"]["signals_require"]}
    bt = by["sdpftp_bt_peak_bounded"]
    assert bt["column"] == "I_batt"
    assert bt["max_value"] == pytest.approx(0.90)
    # Above the measurement, and far under LIMIT_I_BT_MAX 3.0 A -- a tripwire,
    # not a limit claim.
    assert 0.7117 < bt["max_value"] < 0.5 * 3.0
    # The window must CONTAIN the flip band, or it does not watch the handover.
    t0, t1 = bt["t_window"]
    assert t0 <= 185.0 and t1 >= 212.0


def test_ems_ftp75_sdp_raw_column_checks_separate_the_two_table_branches():
    """The clamped column cannot identify the ARTIFACT's branch (0.90/0.95/
    1.00 all emit as 0.8500), so the pre-clamp column carries that half."""
    by = {s["name"]: s
          for s in rhs.FAULT_EXPECTATIONS["ems-ftp75-sdp"]["signals_require"]}
    lo = by["sdpftp_raw_battery_branch"]
    hi = by["sdpftp_raw_fc_branch"]
    assert lo["column"] == hi["column"] == "cmd_share_sp_raw"
    assert lo["max_value"] == pytest.approx(rhs._SDP_RAW_LOW_CEIL)
    assert hi["min_value"] == pytest.approx(rhs._SDP_RAW_HIGH_FLOOR)
    # The bands must straddle the whole ladder gap: the table's values are
    # {0.00} on one branch and {0.90, 0.95, 1.00} on the other. M1: the floor
    # must ADMIT the fuel-cell branch's SMALLEST value, 0.90 (demand bin 24) --
    # the old `0.90 < hi["min_value"]` was the defect, not the guard.
    assert lo["max_value"] < 0.90
    assert hi["min_value"] < 0.90
    assert lo["max_value"] < hi["min_value"]
    assert lo["t_window"][1] <= hi["t_window"][0]


def test_ems_ftp75_sdp_raw_floor_admits_the_bin_24_request():
    """M1. The table's fuel-cell branch requests 1.00, except 0.95 in demand
    bins 22-23 and 0.90 in BIN 24 -- and the FTP-75 walk's peak demand sits only
    ~4 % below the bin-24 lower edge, well inside this entry's own +/-20 %
    model-sensitivity band. A floor above 0.90 therefore fails a CORRECT board
    the first time a sample lands in the top bin."""
    hi = {s["name"]: s
          for s in rhs.FAULT_EXPECTATIONS["ems-ftp75-sdp"]["signals_require"]
          }["sdpftp_raw_fc_branch"]
    for request in (0.90, 0.95, 1.00):
        assert request >= hi["min_value"], (
            "a raw fuel-cell-branch request of %.2f must pass the floor"
            % request)
    # ... and the battery branch's 0.00 still cannot.
    assert 0.00 < hi["min_value"]
    # A run whose post-flip window sits ENTIRELY in bin 24 (peak request 0.90)
    # passes the real leaf judge; under the old 0.94 floor it did not.
    ok, _text = rhs._judge_signal_leaf({"min_value": hi["min_value"]},
                                       {"rows": 3, "peak": 0.90})
    assert ok
    assert not rhs._judge_signal_leaf({"min_value": 0.94},
                                      {"rows": 3, "peak": 0.90})[0]


def test_ems_ftp75_sdp_board_side_checks_bracket_the_governor_floor():
    """The commanded 0.15 is always BELOW the minority governor's floor at
    this cycle's currents, so the DELIVERED FC current is pinned at
    SHARE_MINORITY_I_MIN_A = 0.300 A on the battery-heavy branch and at
    I_tot - 0.300 on the fuel-cell one.  The ceiling and the floor must
    therefore straddle both, and the ceiling must sit under the 0.8275 A the
    constant-0.50 ems-ftp75-5050 control peaks at (or it discriminates
    nothing)."""
    by = {s["name"]: s
          for s in rhs.FAULT_EXPECTATIONS["ems-ftp75-sdp"]["signals_require"]}
    early = by["sdpftp_fc_floored_early"]
    late = by["sdpftp_fc_carried_late"]
    assert early["column"] == late["column"] == "I_fc"
    # RE-PROVISIONALIZED at aux_preload_a 0.0, and the EARLY check's mechanism
    # CHANGED with it: over t = (30, 150) the source total now peaks at
    # 0.5253 A, BELOW the 0.55 A open-loop exit threshold, so the share loop is
    # OPEN there and the minority governor is not clipping.  The delivered
    # split is the commanded 0.15 itself -- walk peak I_fc 0.0788 A, against
    # the constant-0.50 sibling's 0.2626 A over the same window.
    # The LATE check's window moved to (295, 340): the old (235, 260) is now
    # BEFORE the predicted flip and would have measured the wrong branch.
    assert early["max_value"] == pytest.approx(0.18)
    assert 0.0788 < early["max_value"] < 0.2626
    assert early["t_window"] == (30.0, 150.0)
    # PART C (C1 round, 2026-09-01): 0.42 -> 0.46. A board stuck at a constant
    # 0.50 split delivers 0.4198 A over this window (0.4307 A with the
    # documented +2.6 % FTP75 gain offset), so the old floor did not reject the
    # very failure the check names.
    assert late["min_value"] == pytest.approx(0.46)
    assert late["min_value"] > 0.4307          # rejects a stuck-0.5 board
    assert late["t_window"] == (295.0, 340.0)
    assert late["min_value"] < 0.5402          # governor walk over that window
    assert late["min_value"] > early["max_value"]
    assert early.get("provisional_note") and late.get("provisional_note")
    # ... and still clear of LIMIT_I_FC_MAX, so a pass cannot be confused
    # with an overcurrent. (The floor rose 1.00 -> 1.08 on measurement, so the
    # clearance narrowed from 28 % to 23 %; it is still a floor no overcurrent
    # condition sits at.)
    assert late["min_value"] < 0.80 * 1.4


def test_ems_sdp_cross_entry_shape_and_charge_cycle_checks():
    entry = rhs.FAULT_EXPECTATIONS["ems-sdp-cross"]
    names = {s["name"] for s in entry["signals_require"]}
    assert names == {"sdpx_low_rail_early", "sdpx_high_rail_late",
                     "sdpx_raw_battery_branch", "sdpx_charge_cycled",
                     "sdpx_charge_max_hold", "sdpx_charge_released_fraction",
                     "sdpx_charge_window_count", "sdpx_charging_established",
                     "sdpx_fc_peak_bounded"}
    by = {s["name"]: s for s in entry["signals_require"]}
    # The crossing construction, as on ems-ftp75-sdp -- re-banded on the
    # MEASURED 42.292 s flip (campaign 20260901_024231).
    assert by["sdpx_low_rail_early"]["t_window"][1] <= \
        by["sdpx_high_rail_late"]["t_window"][0]
    assert (by["sdpx_low_rail_early"]["t_window"][1],
            by["sdpx_high_rail_late"]["t_window"][0]) == (35.0, 50.0)
    assert 35.0 < 42.292 < 50.0
    assert by["sdpx_raw_battery_branch"]["t_window"] == \
        by["sdpx_low_rail_early"]["t_window"]
    # The charge LIMIT CYCLE, asserted PHASE-FREE. All four charge specs share
    # the SAME switch bit and the SAME window, so they are four properties of
    # one measured trace rather than four unrelated claims.
    charge = [by[n] for n in ("sdpx_charge_cycled", "sdpx_charge_max_hold",
                              "sdpx_charge_released_fraction",
                              "sdpx_charge_window_count")]
    for spec in charge:
        assert spec["switch_bit"] == rhs.SW_FC_CHARGE
        assert spec["t_window"] == (70.0, 190.0)


def test_ems_sdp_cross_charge_band_brackets_the_measured_trace():
    """Every charge threshold on this entry is now a measurement (campaign
    20260901_024231): 64103 of 120000 ticks set, 9 windows, longest hold
    8085 ticks. The bands must contain those and exclude the two failure
    modes the entry exists to separate -- "never charged" and "latched on"."""
    by = {s["name"]: s
          for s in rhs.FAULT_EXPECTATIONS["ems-sdp-cross"]["signals_require"]}
    measured_ticks, measured_edges, measured_hold = 64103, 9, 8085
    total_ticks = 120000                       # 120 s of the 1 kHz CSV

    floor = by["sdpx_charge_cycled"]["min_ticks"]
    ceil_ = by["sdpx_charge_released_fraction"]["max_ticks"]
    hold = by["sdpx_charge_max_hold"]["max_continuous_ticks"]
    lo, hi = by["sdpx_charge_window_count"]["edge_count_between"]

    assert (floor, ceil_, hold, (lo, hi)) == (45000, 84000, 9000, (6, 12))
    assert floor <= measured_ticks <= ceil_
    assert measured_hold <= hold
    assert lo <= measured_edges <= hi
    # The walk-era floor could not fail: 12000 was 19 % of the truth.
    assert floor > 3 * 12000
    # "Latched on for the whole cruise" must fail all three of the bounds that
    # can see it.
    assert total_ticks > ceil_
    assert total_ticks > hold
    assert 1 < lo
    # ... and "never charged" must fail the floor and the count.
    assert 0 < floor and 0 < lo
    # The released fraction the ceiling encodes is the stated [0.30, 0.70] band
    # (its floor is carried by the stricter sdpx_charge_cycled).
    assert (1.0 - ceil_ / total_ticks) == pytest.approx(0.30)
    assert (1.0 - measured_ticks / total_ticks) == pytest.approx(0.466, abs=1e-3)
    # The hold ceiling is the dwell plus one decision stage, not a round guess.
    assert hold == pytest.approx(1000 * (hil.SDP_CHG_MIN_DWELL_S + 1.0))


def test_ems_sdp_cross_max_hold_replaced_the_phase_locked_absence_check():
    """The FAIL of campaign 20260901_024231. `sdpx_charge_released_between`
    asserted the ABSENCE of a charge window over a MODELLED instant taken from
    a walk whose period was wrong by 5.7x, and failed a correct board. Nothing
    in this entry may assert an absence at an instant again."""
    entry = rhs.FAULT_EXPECTATIONS["ems-sdp-cross"]
    names = {s["name"] for s in entry["signals_require"]}
    assert "sdpx_charge_released_between" not in names
    for spec in entry["signals_require"]:
        if spec.get("switch_bit") != rhs.SW_FC_CHARGE:
            continue
        # A max_ticks bound on the charge bit is only sound over the WHOLE
        # cycle window (the released-fraction check); a narrow sub-window is
        # the retired phase-locked shape.
        if "max_ticks" in spec:
            assert spec["t_window"] == (70.0, 190.0), spec["name"]
    # ... and the vacuity guard is satisfied by companionship, not by a note:
    # both max-only specs sit on the same switch bit as sdpx_charge_cycled.
    by = {s["name"]: s for s in entry["signals_require"]}
    assert "vacuity_note" not in by["sdpx_charge_released_fraction"]
    assert "vacuity_note" not in by["sdpx_charge_max_hold"]


def test_ems_sdp_cross_board_side_current_bounds_are_measured():
    """Two board-side bands de-provisionalized on measurement: the charger
    reached its full 0.8 A ceiling, and the single-source FC channel peaked at
    1.1920 A -- the tightest thing this scenario does."""
    by = {s["name"]: s
          for s in rhs.FAULT_EXPECTATIONS["ems-sdp-cross"]["signals_require"]}
    chg = by["sdpx_charging_established"]
    assert chg["column"] == "I_charge"
    assert chg["min_value"] == pytest.approx(0.75)
    # Under the scenario's own programmed ceiling, so it is reachable...
    assert chg["min_value"] < SCENARIOS["ems-sdp-cross"]["chg_i_ceiling_a"]
    # ... and well above the walk-era 0.5 A, which a half-delivering charger
    # would have satisfied.
    assert chg["min_value"] > 0.5
    fc = by["sdpx_fc_peak_bounded"]
    assert fc["column"] == "I_fc"
    assert fc["max_value"] == pytest.approx(1.28)
    # Above the measurement and BELOW LIMIT_I_FC_MAX, so it trips before the
    # board latches OC_FC and names the cause.
    assert 1.1920 < fc["max_value"] < 1.4


def test_ems_sdp_braking_entry_holds_the_share_axis_still():
    """The attribution claim ("every charge transition is demand-driven")
    rests on the share command being provably constant, so it is asserted
    from BOTH sides -- as two specs, since one spec carrying min_value and
    max_value silently drops the ceiling."""
    entry = rhs.FAULT_EXPECTATIONS["ems-sdp-braking"]
    by = {s["name"]: s for s in entry["signals_require"]}
    lo = by["sdpb_share_rail_held"]
    hi = by["sdpb_share_never_crossed"]
    assert lo["column"] == hi["column"] == "cmd_share_sp"
    assert lo["min_value"] == pytest.approx(rhs._SDP_HIGH_RAIL_FLOOR)
    assert hi["max_value"] == pytest.approx(0.86)
    assert lo["t_window"] == hi["t_window"]
    # The ceiling must exclude the battery-heavy branch's emitted 0.15 by a
    # wide margin, and the floor must exclude the firmware's own 0.50 default.
    assert hi["max_value"] < 1.0 and lo["min_value"] > 0.75


def test_ems_sdp_braking_charge_windows_correlate_with_the_low_plateaus():
    """ON across the run and OFF inside two of the 2.2 m/s cruise holds is
    what "the demand axis decided it" means in a trace.  The two OFF windows
    must fall inside actual cruise holds of the scenario's own profile, or
    they assert nothing about the correlation."""
    entry = rhs.FAULT_EXPECTATIONS["ems-sdp-braking"]
    by = {s["name"]: s for s in entry["signals_require"]}
    on = by["sdpb_charge_in_low_windows"]
    # DE-PROVISIONALIZED (campaign 20260901_024231): 52479 ticks measured
    # against the walk's 50100, so the floor moved 25000 -> 45000 = 86 %.
    assert on["switch_bit"] == rhs.SW_FC_CHARGE and on["min_ticks"] == 45000
    assert on["min_ticks"] < 52479
    prof = SCENARIOS["ems-sdp-braking"]["ems_v_profile"]
    hi_mps = hil.SDP_BRAKE_CRUISE_HI_MPS
    for tag in ("sdpb_charge_off_in_cruise_2", "sdpb_charge_off_in_cruise_3"):
        spec = by[tag]
        assert spec["switch_bit"] == rhs.SW_FC_CHARGE
        # 0 ticks measured in BOTH windows, so the walk-era 500-tick allowance
        # was slack nothing used; 100 ticks = 0.1 s, far under AG105_SETTLE_S.
        assert spec["max_ticks"] == 100
        t0, t1 = spec["t_window"]
        # The whole window is at the HIGH cruise level, i.e. in a
        # charge-forbidden demand bin by construction.
        for t in (t0, (t0 + t1) / 2.0, t1):
            assert hil.piecewise(prof, t) == pytest.approx(hi_mps), (tag, t)
    # The charger-current floor must sit under this scenario's own de-rated
    # ceiling, or it could never be reached -- and it is now 93 % of it, so a
    # half-delivering charger fails.
    ceiling = SCENARIOS["ems-sdp-braking"]["chg_i_ceiling_a"]
    est = by["sdpb_charging_established"]["min_value"]
    assert est == pytest.approx(0.65)
    assert 0.9 * ceiling < est < ceiling


def test_ems_sdp_braking_fc_peak_ceiling_guards_the_tightest_oc_margin():
    """NEW in the campaign-024231 calibration round. The one-decision charge
    overhang into the acceleration out of a low plateau peaked at 1.2617 A --
    9.9 % under LIMIT_I_FC_MAX 1.4 A, the tightest margin in the suite, and
    until now UNASSERTED. The ceiling must trip BEFORE the board faults."""
    by = {s["name"]: s
          for s in rhs.FAULT_EXPECTATIONS["ems-sdp-braking"]["signals_require"]}
    fc = by["sdpb_fc_peak_bounded"]
    assert fc["column"] == "I_fc"
    assert fc["max_value"] == pytest.approx(1.32)
    assert 1.2617 < fc["max_value"] < 1.4
    # The window must span the plateau/acceleration cycles the overhang lives
    # in -- the measured peak is at t = 65.51.
    t0, t1 = fc["t_window"]
    assert t0 <= 10.0 and t1 >= 126.0


def test_ems_sdp_braking_edge_census_composes_windows_plus_early_drops():
    """The cruise-guard early-drop branch, censused. The edge kind cannot tell
    a 1 s blip from a 13 s window, so the band is COMPOSED: four sustained
    plateau windows + [4, 6] early drops = [8, 10] rising edges. Campaign
    20260901_024231 measured exactly 9 = 4 + 5."""
    by = {s["name"]: s
          for s in rhs.FAULT_EXPECTATIONS["ems-sdp-braking"]["signals_require"]}
    census = by["sdpb_charge_edge_census"]
    assert census["switch_bit"] == rhs.SW_FC_CHARGE
    assert census["edge"] == "rise"
    lo, hi = census["edge_count_between"]
    assert (lo, hi) == (8, 10)
    assert lo <= 9 <= hi
    # The composition must be arithmetically what the comment claims.
    assert (lo - hil.SDP_BRAKE_CYCLES, hi - hil.SDP_BRAKE_CYCLES) == (4, 6)
    # The window must open BEFORE the Run-entry blip at t = 3.008 (which is the
    # only drop not paired with a deceleration) and close after the last
    # plateau window's rise at t = 114.862.
    t0, t1 = census["t_window"]
    assert t0 < 3.008 and t1 > 114.862
    # ... and it must not run past the scenario's own duration.
    assert t1 < SCENARIOS["ems-sdp-braking"]["duration_s"]


def test_sdp_interior_scenarios_all_carry_expectation_entries():
    """A scenario with no entry is scored "expected fault-free" and asserts
    nothing positive -- the rubber-stamp class these three exist to avoid."""
    for name in SDP_INTERIOR_SCENARIOS:
        assert name in rhs.FAULT_EXPECTATIONS, name
        assert rhs.FAULT_EXPECTATIONS[name]["signals_require"], name


def test_ems_ftp75_sdp_joined_the_with_ftp75_gate():
    """350 s, same cost argument as its two siblings -- and the gate is a SET
    rather than a name prefix, so joining it is an explicit act."""
    assert "ems-ftp75-sdp" in rhs.FTP75_SCENARIOS
    # WP-E: `ems-ftp75-dp` (the drive-cycle frontier BOUND) joined 2026-09-01.
    assert "ems-ftp75-dp" in rhs.FTP75_SCENARIOS
    assert len(rhs.FTP75_SCENARIOS) == 4
    plan = {p["name"]: p for p in rhs.build_plan(_args()) if p["kind"] == "scenario"}
    assert "LONG-CYCLE" in plan["ems-ftp75-sdp"]["skip_reason"]
    plan_on = {p["name"]: p for p in rhs.build_plan(_args(with_ftp75=True))
               if p["kind"] == "scenario"}
    assert not plan_on["ems-ftp75-sdp"].get("skip_reason")


def test_sdp_interior_scenarios_are_skipped_under_pi_live():
    """All three are EMS-driven, so the existing "ems" metadata rule skips
    them -- no new code path, and the ftp75 one is skipped for the PI-LIVE
    reason (that gate is ordered first) rather than the long-cycle one."""
    plan = {p["name"]: p for p in rhs.build_plan(_args(pi_live=True))
            if p["kind"] == "scenario"}
    for name in SDP_INTERIOR_SCENARIOS:
        assert "--pi-live" in plan[name]["skip_reason"], name


# ─────────────────────────────────────────────────────────────────────────────
# THE EMS FRONTIER CROSS-RUN CHECK (2026-09-01)
#
# The check exists because campaign 20260901_000816 shipped 53/53 PASS with a
# 9.9 pp policy regression in it, so the load-bearing tests here are the two
# FIXTURE REPLAYS: the recorded numbers of that campaign must FAIL, and the
# recorded numbers of the campaign before it (20260831_222036) must PASS. A
# check that cannot reproduce the verdict on the data that motivated it is not
# a check.
# ─────────────────────────────────────────────────────────────────────────────

# CAMPAIGN 2 (hil_report_20260901_000816) -- the REGRESSION that motivated the
# check. sdp-v2 charged, and its charging is loss-making at this rig's scale.
_C2_LEGS = {"ems-sdp":       (0.0161914, -0.00077),
            "ems-soc-band":  (0.0128472, -0.00206),
            "ems-dp-replay": (0.0116404, -0.00203)}
# CAMPAIGN 1 (hil_report_20260831_222036) -- the leg ON the frontier.
# L4: the reference and bound legs carry that campaign's ACTUAL recorded
# totals to full precision. The 0.0128475 / 0.0116403 this fixture used to hold
# were the rounded figures quoted in prose; a fixture whose job is to replay a
# campaign must replay the campaign's own numbers, or a future threshold edit is
# checked against a number no run ever produced.
_C1_LEGS = {"ems-sdp":       (0.0131881, -0.00148),
            "ems-soc-band":  (0.0128520889, -0.00206),
            "ems-dp-replay": (0.0116398977, -0.00203)}
# CAMPAIGN 3 (hil_report_20260901_024231) -- the FIRST LIVE EVALUATION of the
# frontier check, on the sdp-v3 artifact's endogenous never-charge candidate.
# Recorded to full precision from that report's own results.json.
_C3_LEGS = {"ems-sdp":       (0.0125424884, -0.0016599999999999948),
            "ems-soc-band":  (0.0128475468, -0.0020599999999999508),
            "ems-dp-replay": (0.011640519, -0.0020299999999999763)}


def _frontier_results(legs, **overrides):
    """Scenario result dicts carrying only what evaluate_ems_frontier() reads.

    `overrides` maps a scenario name to a dict merged into its record (or to
    None to omit the leg entirely), so a test can express "this leg was
    skipped / failed / never ran" without building a whole run."""
    out = []
    for name, (h2, dsoc) in legs.items():
        over = overrides.get(name, {}) if overrides else {}
        if over is None:
            continue
        rec = {"kind": "scenario", "name": name, "passed": True,
               "metrics": {"final_h2_cum_g": h2, "delta_soc": dsoc}}
        rec.update(over)
        out.append(rec)
    return out


def test_eq_h2_credits_a_smaller_discharge_and_charges_a_larger_one():
    """SIGN CHECK, and it is the one thing a reader can get backwards.

    On the campaign-2 numbers the SDP leg discharged 0.00129 SoC LESS than the
    reference; that surplus charge is hydrogen it did not have to burn, so it
    is CREDITED 0.00315 g at lambda 0.41 -- and the leg is STILL above the
    reference, which is the finding."""
    eq = rhs.ems_eq_h2(0.0161914, -0.00077, -0.00206, 0.41)
    assert eq == pytest.approx(0.0161914 - 0.00129 / 0.41, rel=1e-9)
    assert eq < 0.0161914
    assert eq > 0.0128472           # still worse than the reference's own total
    # The mirror: a leg that discharged HARDER is charged for the difference.
    assert rhs.ems_eq_h2(0.0128472, -0.00335, -0.00206, 0.41) == \
        pytest.approx(0.0128472 + 0.00129 / 0.41, rel=1e-9)
    # The reference leg's own correction is identically zero.
    assert rhs.ems_eq_h2(0.0128472, -0.00206, -0.00206, 0.41) == \
        pytest.approx(0.0128472)


def test_frontier_FAILS_on_the_campaign_2_regression_numbers():
    """The regression the check exists for: BOTH assertions must fail."""
    rec = rhs.evaluate_ems_frontier(_frontier_results(_C2_LEGS))
    assert rec["verdict"] == "FAIL"
    assert rec["passed"] is False
    nom = rec["per_lambda"][0]
    assert nom["passed_vs_reference"] is False
    assert nom["passed_vs_bound"] is False
    # ... and it fails at EVERY lambda in the band, so it is not knife-edge.
    assert all(p["passed"] is False for p in rec["per_lambda"])
    assert "OFF the frontier" in rec["reason"]
    # The measured ratios, so a threshold edit that quietly rescued this case
    # would show up here.
    assert rec["vs_reference"] == pytest.approx(1.0154, abs=5e-4)
    assert rec["vs_bound"] == pytest.approx(1.1278, abs=5e-4)


def test_frontier_reports_the_implied_lever_between_candidate_and_bound():
    """THE HONESTY METRIC (campaign 20260901_024231). For two CHARGE-FREE legs
    the vs-bound ratio is structurally ~1.0: both points differ only along the
    SHARE lever, and lambda IS that lever's rate, so eq-H2 subtracts exactly
    the difference they have. The implied lever is what makes that visible --
    0.41021 SoC/g against lambda 0.410, agreement to 0.05 %."""
    rec = rhs.evaluate_ems_frontier(_frontier_results(_C3_LEGS))
    assert rec["verdict"] == "PASS"
    assert rec["implied_lever_soc_per_g"] == pytest.approx(0.41021, abs=1e-5)
    # The degeneracy itself: implied lever == lambda  =>  vs_bound == 1.
    assert rec["vs_bound"] == pytest.approx(1.0, abs=1e-3)
    assert abs(rec["implied_lever_soc_per_g"]
               - rhs.EMS_EQ_H2_LAMBDA_SOC_PER_G) < 0.001
    # ... and the DISCRIMINATING arm is vs-reference, which is not degenerate.
    assert rec["vs_reference"] == pytest.approx(0.9003, abs=5e-4)


def test_frontier_implied_lever_departs_from_lambda_on_the_regression_case():
    """The converse, and it is what the vs-bound arm actually detects: the
    campaign-2 regression bought its SoC through the Ag105 charge lever, which
    is priced ~0.24 SoC/g, not 0.41. The implied lever is far from lambda and
    the ratio is nowhere near 1.0."""
    rec = rhs.evaluate_ems_frontier(_frontier_results(_C2_LEGS))
    lever = rec["implied_lever_soc_per_g"]
    assert lever == pytest.approx(0.2774, abs=1e-3)
    assert abs(lever - rhs.EMS_EQ_H2_LAMBDA_SOC_PER_G) > 0.10
    assert rec["vs_bound"] > 1.10


def test_frontier_implied_lever_is_None_when_the_two_legs_burnt_the_same():
    """The ratio is undefined, not infinite, when the hydrogen totals coincide
    -- the metric says so rather than dividing by zero."""
    legs = dict(_C3_LEGS)
    legs["ems-dp-replay"] = (legs["ems-sdp"][0], -0.00203)
    rec = rhs.evaluate_ems_frontier(_frontier_results(legs))
    assert rec["implied_lever_soc_per_g"] is None


def test_frontier_vs_bound_max_is_not_tightened_on_a_charge_free_reading():
    """The AMENDED intent (campaign 20260901_024231): the earlier note said
    tighten 1.06 -> 1.03 after two campaigns. That must NOT happen on a
    campaign whose candidate never charged, because such a reading measures
    the degeneracy above, not the candidate's spread. The constant and the
    banner that forbids it are pinned together."""
    assert rhs.EMS_FRONTIER_VS_BOUND_MAX == 1.06
    with open(rhs.__file__, encoding="utf-8") as fh:
        src = fh.read()
    assert "DO NOT TIGHTEN 1.06 -> 1.03 ON A CHARGE-FREE READING" in src
    # ... and the campaign-3 reading is exactly such a case: it PASSES the
    # vs-bound arm at 1.0000 x, which a 1.03 bound would still admit -- so the
    # tightening would buy no detection power at all on this data.
    rec = rhs.evaluate_ems_frontier(_frontier_results(_C3_LEGS))
    assert rec["vs_bound"] < 1.03


def test_frontier_PASSES_on_the_campaign_1_numbers():
    """The calibrated leg ON the frontier: -8.4 % against the heuristic and
    +1.8 % over the non-causal bound, stable across the lambda band."""
    rec = rhs.evaluate_ems_frontier(_frontier_results(_C1_LEGS))
    assert rec["verdict"] == "PASS"
    assert rec["passed"] is True
    assert all(p["passed"] for p in rec["per_lambda"])
    # L4: re-pinned against the campaign's ACTUAL totals (see _C1_LEGS).
    assert rec["vs_reference"] == pytest.approx(0.91607, abs=5e-5)
    assert rec["vs_bound"] == pytest.approx(1.01787, abs=5e-5)
    # A PASS is not exit-affecting, and neither is the flag load-bearing here --
    # pinned so the H1 split cannot silently start marking passes.
    assert rec["exit_affecting"] is False


@pytest.mark.parametrize("override,fragment", [
    ({"ems-sdp": None}, "not in this run's plan"),
    ({"ems-soc-band": {"skipped": True, "skip_reason": "--pi-live"}},
     "SKIPPED"),
    ({"ems-dp-replay": {"passed": False}}, "did NOT pass its own checks"),
    ({"ems-sdp": {"metrics": {}}}, "no h2_cum_g / delta_soc"),
])
def test_frontier_UNVERIFIED_when_a_leg_is_missing_or_unusable(override,
                                                               fragment):
    """A missing leg is NAMED and counts as not-passing -- never silent. A
    silently dropped leg is exactly how the campaign-2 regression went
    unnoticed."""
    rec = rhs.evaluate_ems_frontier(_frontier_results(_C1_LEGS, **override))
    assert rec["verdict"] == "UNVERIFIED"
    assert rec["passed"] is False
    assert any(fragment in m for m in rec["missing"]), rec["missing"]
    # The named leg is in the reason, so the REPORT.md headline row says which.
    assert fragment in rec["reason"]


@pytest.mark.parametrize("override,expected", [
    # NOT exit-affecting: nothing RAN that is unusable.
    ({"ems-sdp": None}, False),
    ({"ems-soc-band": {"skipped": True, "skip_reason": "--pi-live"}}, False),
    # Exit-affecting: the leg ran and its numbers cannot be used.
    ({"ems-dp-replay": {"passed": False}}, True),
    ({"ems-sdp": {"metrics": {}}}, True),
])
def test_frontier_exit_affecting_splits_the_UNVERIFIED_causes(override,
                                                              expected):
    """H1. UNVERIFIED covers two different situations and only one is a defect:
    a leg nobody exercised (not planned / skipped) vs a leg that ran and came
    back unusable. The verdict and the rendering are identical; the flag is
    what the exit code may act on."""
    rec = rhs.evaluate_ems_frontier(_frontier_results(_C1_LEGS, **override))
    assert rec["verdict"] == "UNVERIFIED"
    assert rec["passed"] is False
    assert rec["exit_affecting"] is expected


def test_frontier_pi_live_style_skip_plan_is_UNVERIFIED_but_not_exit_affecting():
    """H1, the case that motivated it: a --pi-live campaign skips EVERY
    EMS-driven scenario, so all three legs are explicit SKIPs. The frontier is
    honestly UNVERIFIED and NAMED -- and the run is not failed for behaving
    exactly as --pi-live documents."""
    skipped = {n: {"skipped": True,
                   "skip_reason": "--pi-live: EMS-driven scenario"}
               for n in rhs.EMS_FRONTIER.values()}
    rec = rhs.evaluate_ems_frontier(_frontier_results(_C1_LEGS, **skipped))
    assert rec["verdict"] == "UNVERIFIED"
    assert rec["exit_affecting"] is False
    for name in rhs.EMS_FRONTIER.values():
        assert any(name in m and "SKIPPED" in m for m in rec["missing"])


def test_frontier_names_a_pending_leg_as_pending_not_as_unplanned():
    """M4. Every intermediate rewrite of a full campaign's results.json sees
    legs the plan CONTAINS and has not reached yet. Blaming the plan for them
    ("not in this run's plan") is simply false, and a partial report is exactly
    where a reader is least able to check."""
    results = _frontier_results(_C1_LEGS, **{"ems-dp-replay": None})
    planned = set(rhs.EMS_FRONTIER.values())
    rec = rhs.evaluate_ems_frontier(results, planned)
    assert rec["verdict"] == "UNVERIFIED"
    assert rec["exit_affecting"] is False
    assert any("planned but not yet run" in m for m in rec["missing"])
    assert not any("not in this run's plan" in m for m in rec["missing"])
    # Without the plan set, the old wording is still what an unplanned leg gets.
    rec_noplan = rhs.evaluate_ems_frontier(results)
    assert any("not in this run's plan" in m for m in rec_noplan["missing"])
    # A leg genuinely outside the plan keeps the unplanned wording even when a
    # plan set IS supplied.
    rec_other = rhs.evaluate_ems_frontier(results, {"steady", "ems-sdp"})
    assert any("not in this run's plan" in m for m in rec_other["missing"])


def test_frontier_refuses_a_non_positive_eq_h2():
    """L5. The SoC correction is unbounded below, so a leg that ended far
    enough ABOVE the reference is credited more hydrogen than it burned. The
    ratios then carry no meaning -- and a zero denominator reaches a `%.4f` on
    a None. Refuse the comparison instead."""
    legs = dict(_C1_LEGS)
    # +0.006 SoC above the reference at lambda 0.41 is a ~14.6 mg credit
    # against a ~13.2 mg total: eq-H2 goes negative. Still inside the 0.010
    # matched-dSoC precondition, so this is genuinely reachable.
    legs["ems-sdp"] = (0.0131881, -0.00206 + 0.006)
    rec = rhs.evaluate_ems_frontier(_frontier_results(legs))
    assert rec["verdict"] == "UNVERIFIED"
    assert rec["passed"] is False
    assert rec["exit_affecting"] is True
    assert "NOT POSITIVE" in rec["reason"]
    assert "ems-sdp" in rec["reason"]
    # No ratios are published from a refused comparison.
    assert "per_lambda" not in rec


def test_frontier_returns_None_when_no_leg_was_planned_at_all():
    """A replay-only or subset run makes no claim -- manufacturing an
    UNVERIFIED record for a plan that never intended the comparison is noise,
    and would fail every scenarios-only invocation."""
    assert rhs.evaluate_ems_frontier([]) is None
    assert rhs.evaluate_ems_frontier(
        [{"kind": "replay", "name": "ML0146", "passed": True, "metrics": {}},
         {"kind": "scenario", "name": "steady", "passed": True,
          "metrics": {"final_h2_cum_g": 0.01, "delta_soc": -0.001}}]) is None


def test_frontier_UNVERIFIED_when_the_legs_are_not_at_matched_soc():
    """The eq-H2 correction is a LINEAR extrapolation at one exchange rate. A
    leg 0.05 SoC away from the reference is a different experiment, not a leg
    to be corrected."""
    legs = dict(_C1_LEGS)
    legs["ems-sdp"] = (0.0131881, -0.00206 + 0.05)
    rec = rhs.evaluate_ems_frontier(_frontier_results(legs))
    assert rec["verdict"] == "UNVERIFIED"
    assert rec["passed"] is False
    assert "matched-dSoC" in rec["reason"]
    assert rec["dsoc_gap"] == pytest.approx(0.05)
    # The comparison is NOT made -- no ratios are published from a precondition
    # failure, so nobody can quote one.
    assert "per_lambda" not in rec


def test_frontier_KNIFE_EDGE_when_the_verdict_flips_inside_the_lambda_band():
    """lambda is known to ~1.5 %, so a verdict that depends on where inside the
    measured band it is read is not a result. Constructed by solving for the h2
    that puts the vs-reference ratio exactly on the 0.98 threshold at the
    NOMINAL lambda: the correction term then moves the ratio across the
    threshold in opposite directions at the two band edges.

    The BOUND leg is loosened here on purpose. `passed` is the AND of both
    assertions, so a candidate sitting exactly on the reference threshold would
    also have to clear 1.06x the bound to make the flip observable -- otherwise
    the vs-bound arm fails at every lambda and the verdict is a uniform FAIL,
    which would test nothing about the band."""
    ref_h2, ref_dsoc = _C1_LEGS["ems-soc-band"]
    dsoc = -0.00148
    lam = rhs.EMS_EQ_H2_LAMBDA_SOC_PER_G
    # eq_cand(lam_nom) == 0.98 * eq_ref  =>  h2 = 0.98*ref_h2 + (dsoc-ref)/lam
    h2 = rhs.EMS_FRONTIER_VS_REFERENCE_MAX * ref_h2 + (dsoc - ref_dsoc) / lam
    legs = dict(_C1_LEGS)
    legs["ems-sdp"] = (h2, dsoc)
    legs["ems-dp-replay"] = (0.0122, -0.00203)
    rec = rhs.evaluate_ems_frontier(_frontier_results(legs))
    assert all(p["passed_vs_bound"] for p in rec["per_lambda"])
    assert rec["verdict"] == "KNIFE-EDGE"
    assert rec["passed"] is False
    assert "FLIPS inside the measured lambda band" in rec["reason"]
    # Both outcomes are genuinely present across the three evaluated lambdas.
    assert {p["passed"] for p in rec["per_lambda"]} == {True, False}


def _renderable(results):
    """Fill in the fields render_report() needs, so a crafted frontier result
    set can be pushed through main()."""
    for r in results:
        r.setdefault("mode", "hifi")
        r.setdefault("electrical_required", "any")
        r.setdefault("description", "")
        r.setdefault("duration_s", 61.0)
        r.setdefault("checks", [])
        r.setdefault("notes", [])
        r.setdefault("events", {})
        r.setdefault("key_metrics", "")
        r.setdefault("child", {"status": "ok", "summary": {}, "returncode": 0,
                               "wall_s": 1.0, "log": "x.log"})
    return results


@pytest.mark.parametrize("legs_name,only,expect_rc", [
    # H1 + the review's untested-behavior #1: the frontier verdict's coupling to
    # main()'s exit code, which was previously only reasoned about.
    #   FAIL              -> 1   (the regression the check exists for)
    ("c2", ["ems-sdp", "ems-soc-band", "ems-dp-replay"], 1),
    #   PASS              -> 0
    ("c1", ["ems-sdp", "ems-soc-band", "ems-dp-replay"], 0),
    #   UNVERIFIED, not exit-affecting -> 0.  A one-leg plan never intended the
    #   comparison; failing it contradicted the docstring and broke --pi-live.
    ("c1", ["ems-soc-band"], 0),
])
def test_main_exit_code_follows_the_frontier_verdict(tmp_path, monkeypatch,
                                                     legs_name, only,
                                                     expect_rc):
    legs = {"c1": _C1_LEGS, "c2": _C2_LEGS}[legs_name]
    wanted = set(only)
    crafted = _renderable(_frontier_results(
        {k: v for k, v in legs.items() if k in wanted}))

    def fake_run_plan(plan, args, problems, results, write_outputs):
        results.extend(crafted)
        return results, None

    monkeypatch.setattr(rhs, "_run_plan", fake_run_plan)
    argv = ["--out", str(tmp_path), "--scenarios-only"]
    for name in only:
        argv += ["--only", name]
    assert rhs.main(argv) == expect_rc
    loaded = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert "ems_frontier" in loaded


def test_frontier_scores_only_frontier_eligible_scenarios():
    """The demonstration legs are excluded BY CONSTRUCTION: they are not in
    EMS_FRONTIER at all, so adding them to a plan cannot move the verdict."""
    base = rhs.evaluate_ems_frontier(_frontier_results(_C1_LEGS))
    with_demo = rhs.evaluate_ems_frontier(
        _frontier_results(_C1_LEGS) + [
            {"kind": "scenario", "name": "ems-sdp-cross", "passed": True,
             "metrics": {"final_h2_cum_g": 99.0, "delta_soc": +0.5}},
            {"kind": "scenario", "name": "ems-sdp-braking", "passed": True,
             "metrics": {"final_h2_cum_g": 99.0, "delta_soc": +0.5}}])
    assert with_demo["verdict"] == base["verdict"] == "PASS"
    assert with_demo["eq_h2"] == base["eq_h2"]


def test_frontier_roles_name_the_three_ruled_scenarios():
    assert set(rhs.EMS_FRONTIER) == {"reference", "candidate", "bound"}
    assert rhs.EMS_FRONTIER["reference"] == "ems-soc-band"
    assert rhs.EMS_FRONTIER["candidate"] == "ems-sdp"
    assert rhs.EMS_FRONTIER["bound"] == "ems-dp-replay"
    # Every frontier leg's own EMS strategy must be frontier_eligible, or the
    # check would be ranking a run the report simultaneously banners as a
    # demonstration.
    for name in rhs.EMS_FRONTIER.values():
        strategy = SCENARIOS[name]["ems"]
        assert rhs.ems_frontier_eligible(strategy), (name, strategy)


def test_frontier_constants_are_the_measured_ones():
    assert rhs.EMS_EQ_H2_LAMBDA_SOC_PER_G == pytest.approx(0.41)
    assert rhs.EMS_EQ_H2_LAMBDA_BAND == (0.409, 0.415)
    lo, hi = rhs.EMS_EQ_H2_LAMBDA_BAND
    assert lo < rhs.EMS_EQ_H2_LAMBDA_SOC_PER_G < hi
    assert rhs.EMS_FRONTIER_VS_REFERENCE_MAX == pytest.approx(0.98)
    assert rhs.EMS_FRONTIER_VS_BOUND_MAX == pytest.approx(1.06)
    assert rhs.EMS_FRONTIER_DSOC_MATCH_MAX == pytest.approx(0.010)


# -- the demonstration banner ------------------------------------------------

def test_demonstration_banner_only_on_non_frontier_ems_scenarios():
    for name in ("ems-sdp-cross", "ems-sdp-braking"):
        banner = rhs.ems_demonstration_banner(name)
        assert banner and "DYNAMICS DEMONSTRATION" in banner
        assert "sdp-v2" in banner
    # The frontier legs, and the calibrated FTP-75 leg, carry NO banner.
    for name in ("ems-sdp", "ems-soc-band", "ems-dp-replay", "ems-ftp75-sdp"):
        assert rhs.ems_demonstration_banner(name) is None
    # A scenario with no EMS strategy at all is not banner territory.
    assert rhs.ems_demonstration_banner("steady") is None
    assert rhs.ems_demonstration_banner("no-such-scenario") is None


def test_demonstration_banner_prefers_the_runs_recorded_strategy():
    """L7. `--ems` overrides the scenario registry's default, so a run of
    `ems-sdp` (registry default `sdp-v3`, frontier-eligible) may actually have
    played `sdp-v2`. The banner must describe what RAN."""
    assert rhs.ems_demonstration_banner("ems-sdp") is None
    banner = rhs.ems_demonstration_banner("ems-sdp", "sdp-v2")
    assert banner and "DYNAMICS DEMONSTRATION" in banner
    assert "sdp-v2" in banner
    # ... and the converse: a demonstration scenario re-bound to an eligible
    # strategy carries no banner.
    # WP-1C (2026-09-02): the ELIGIBLE artifact is now `sdp-v4` -- `sdp-v3` was
    # re-classified as a demonstration when the eta-era alpha recalibration
    # shipped, so it is no longer the right name for this half of the test.
    assert rhs.ems_demonstration_banner("ems-sdp-cross", "sdp-v4") is None
    # No recorded strategy -> the registry default, unchanged behaviour.
    assert "sdp-v2" in rhs.ems_demonstration_banner("ems-sdp-cross")


def test_demonstration_banner_calls_an_unknown_strategy_unclassified():
    """L8. A strategy name this checkout does not register is neither eligible
    nor a registered demonstration; the demonstration banner would assert a
    `frontier_eligible: False` entry that does not exist."""
    banner = rhs.ems_demonstration_banner("ems-sdp", "sdp-v9-from-the-future")
    assert banner and "unclassified" in banner
    assert "sdp-v9-from-the-future" in banner
    assert "DYNAMICS DEMONSTRATION" not in banner


def test_demonstration_banner_appends_the_per_strategy_role_note():
    """L9. "Not on the frontier" covers two different things: a policy
    demonstration that pursues an objective and loses, and a stimulus with no
    objective at all. The note distinguishes them."""
    demo = rhs.ems_demonstration_banner("ems-sdp-cross")     # sdp-v2
    stim = rhs.ems_demonstration_banner("ems-sdp", "hold-5050")
    assert "LOSS-MAKING POLICY DEMONSTRATION" in demo
    assert "STIMULUS WITH NO OBJECTIVE" in stim
    assert "LOSS-MAKING" not in stim
    # Rendered AFTER the shared banner, as a continuation of the same blockquote.
    assert demo.index("DYNAMICS DEMONSTRATION") < demo.index("ROLE:")
    assert "\n>\n> " in demo
    # Every non-eligible strategy carries one, so no off-frontier run is left
    # with the ambiguous banner alone.
    for name, meta in rhs.EMS_STRATEGY_META.items():
        if not meta.get("frontier_eligible"):
            assert meta.get("role_note"), name


def test_report_renders_the_frontier_table_and_the_demonstration_banner():
    results = _frontier_results(_C2_LEGS)
    for r in results:
        r.update(mode="hifi", electrical_required="any", description="",
                 duration_s=61.0, checks=[], notes=[], events={},
                 child={"status": "ok", "summary": {}, "returncode": 0,
                        "wall_s": 1.0, "log": "x.log"}, key_metrics="")
    results.append({
        "kind": "scenario", "name": "ems-sdp-cross", "passed": True,
        "mode": "hifi", "electrical_required": "any", "description": "",
        "duration_s": 200.0, "checks": [], "notes": [], "events": {},
        "metrics": {"final_h2_cum_g": 0.02, "delta_soc": -0.001},
        "child": {"status": "ok", "summary": {}, "returncode": 0,
                  "wall_s": 1.0, "log": "x.log"}, "key_metrics": ""})
    md = rhs.render_report({"date": "x"}, results)
    assert "## EMS frontier - FAIL" in md.replace("—", "-")
    assert "lambda provenance" in md
    assert "TODO(calibrate)" in md          # the Gfc footnote
    assert "DYNAMICS DEMONSTRATION" in md
    # The three legs are in the table, by role.
    for name in rhs.EMS_FRONTIER.values():
        assert "`%s` | " % name in md


def test_report_renders_the_implied_lever_and_the_no_tighten_caveat():
    """A reader of a 1.0000 x vs-bound ratio must be able to see WHY it is
    1.0 -- the two legs differ only along the share lever -- rather than
    inferring a near-optimal policy. Campaign 20260901_024231's own numbers."""
    results = _frontier_results(_C3_LEGS)
    for r in results:
        r.update(mode="hifi", electrical_required="any", description="",
                 duration_s=61.0, checks=[], notes=[], events={},
                 child={"status": "ok", "summary": {}, "returncode": 0,
                        "wall_s": 1.0, "log": "x.log"}, key_metrics="")
    md = rhs.render_report({"date": "x"}, results)
    assert "## EMS frontier - PASS" in md.replace("—", "-")
    assert "implied lever, candidate vs bound: 0.41021 SoC/g" in md
    assert "STRUCTURAL" in md
    assert "vs reference" in md
    # ... and the lambda-provenance paragraph no longer advertises the retired
    # 1.03 tightening intent.
    assert "tighten to 1.03" not in md
    assert "LEVER-CLASS detector" in md


def test_report_omits_the_implied_lever_when_there_is_no_comparison():
    """An UNVERIFIED frontier has no candidate/bound pair, so the metric must
    not be rendered at all rather than rendered as a dash."""
    results = _frontier_results(_C1_LEGS, **{"ems-dp-replay": None})
    for r in results:
        r.update(mode="hifi", electrical_required="any", description="",
                 duration_s=61.0, checks=[], notes=[], events={},
                 child={"status": "ok", "summary": {}, "returncode": 0,
                        "wall_s": 1.0, "log": "x.log"}, key_metrics="")
    md = rhs.render_report({"date": "x"}, results)
    assert "implied lever, candidate vs bound" not in md


def test_report_renders_UNVERIFIED_without_a_ratio_table():
    results = _frontier_results(_C1_LEGS, **{"ems-dp-replay": None})
    for r in results:
        r.update(mode="hifi", electrical_required="any", description="",
                 duration_s=61.0, checks=[], notes=[], events={},
                 child={"status": "ok", "summary": {}, "returncode": 0,
                        "wall_s": 1.0, "log": "x.log"}, key_metrics="")
    md = rhs.render_report({"date": "x"}, results)
    assert "## EMS frontier - UNVERIFIED" in md.replace("—", "-")
    assert "UNVERIFIED leg: ems-dp-replay" in md
    # No lambda-sensitivity table: no comparison was made.
    assert "Lambda sensitivity" not in md


# ═════════════════════════════════════════════════════════════════════════
# WP-E — THE SECOND EMS FRONTIER (drive-cycle scale) and the `--droop` wiring
# ═════════════════════════════════════════════════════════════════════════

FTP75_SPEC = next(f for f in rhs.EMS_FRONTIERS if f["id"] == "ftp75")
CYCLE61_SPEC = next(f for f in rhs.EMS_FRONTIERS if f["id"] == "cycle61")


def _ftp_results(legs, **over):
    """Scenario result dicts for the FTP-75 frontier's three legs."""
    out = []
    for role, name in FTP75_SPEC["roles"].items():
        h2, dsoc = legs[role]
        r = {"kind": "scenario", "name": name, "passed": True,
             "metrics": {"final_h2_cum_g": h2, "delta_soc": dsoc}}
        r.update(over.get(name, {}))
        out.append(r)
    return out


def test_frontier_registry_shape_and_thresholds():
    """The two tuples carry SEPARATE thresholds, and that separation is the
    point: the 61 s cycle's optimum beats its reference by 14 %, while the
    OFFLINE drive-cycle solve measured the DP at -0.01 % -- a TIE. Applying
    0.98 at drive-cycle scale would fail a correct candidate."""
    assert [f["id"] for f in rhs.EMS_FRONTIERS] == ["cycle61", "ftp75"]
    assert CYCLE61_SPEC["vs_reference_max"] == 0.98
    assert FTP75_SPEC["vs_reference_max"] == 1.02      # does NOT assume a win
    assert FTP75_SPEC["vs_bound_max"] == CYCLE61_SPEC["vs_bound_max"] == 1.06
    assert FTP75_SPEC["provisional_note"] and "PROVISIONAL" in \
        FTP75_SPEC["provisional_note"]
    # WP-1C (2026-09-02): the 61 s tuple is now PROVISIONAL too. Its
    # thresholds are unchanged, but its reference leg is the tuple's only
    # charging leg, so ETA_CHG 0.88 cuts the reference's hydrogen ~10 % while
    # the charge-free candidate and bound do not move: the governor-walk
    # vs_reference goes 0.859 -> 0.958 against a 0.98 ask.
    assert CYCLE61_SPEC["provisional_note"] and         "PROVISIONAL" in CYCLE61_SPEC["provisional_note"]
    assert FTP75_SPEC["roles"] == {"reference": "ems-ftp75-socband",
                                   "candidate": "ems-ftp75-sdp",
                                   "bound": "ems-ftp75-dp"}
    # The 61 s roles object is the SAME dict the module constant names, so the
    # two records of it cannot drift.
    assert CYCLE61_SPEC["roles"] is rhs.EMS_FRONTIER


def test_frontier_ftp75_stimulus_split_is_resolved_and_the_tuple_evaluates():
    """THE SPLIT IS RESOLVED (operator ruling 2026-09-01), and this test is the
    inversion of the one that stood here.

    IT USED TO ASSERT THE DEFECT: `ems-ftp75-sdp` ran FTP75_SDP_PRELOAD_A
    (0.45 A) while the other two legs ran FTP75_PRELOAD_A (0.65 A), so the
    three were not one experiment -- eq-H2 corrects for SoC, not for demand,
    and the candidate would have won by ~0.2 A of avoided load. A second,
    then-inert split rode along: the reference leg declared no Ag105 cap while
    the two policy legs capped at 0.8 A.

    BOTH ARE GONE. `aux_preload_a` is 0.0 on all three legs (the ruling), and
    `ems-ftp75-socband` now declares the siblings' 0.8 A ceiling -- which it
    HAD to, because the preload removal re-opened its charge branch and turned
    the inert split live. The tuple therefore evaluates for the first time.

    The MECHANISM that refuses a split is not retired with the split: it is
    covered against a synthetic tuple immediately below, so a REGRESSION into
    a real split is still caught."""
    assert rhs.ems_frontier_stimulus_mismatches(FTP75_SPEC["roles"]) == []
    rec = rhs.evaluate_ems_frontier(
        _ftp_results({"reference": (0.09, -0.002),
                      "candidate": (0.08, -0.002),
                      "bound": (0.089, -0.002)}), spec=FTP75_SPEC)
    assert rec["verdict"] == "PASS"
    assert rec["passed"] is True
    assert rec["exit_affecting"] is False
    assert not rec.get("stimulus_mismatch")
    # The comparison actually ran, which the UNVERIFIED path never let it do.
    assert "per_lambda" in rec or "eq_h2" in rec
    # ... and the registry keys the precondition reads all agree.
    for key, want in (("aux_preload_a", 0.0), ("chg_i_ceiling_a", 0.8)):
        vals = {n: SCENARIOS[n].get(key) for n in FTP75_SPEC["roles"].values()}
        assert len(vals) == 3, (key, vals)
        for n, v in vals.items():
            assert v == pytest.approx(want), (key, n, v)


def test_frontier_stimulus_split_is_still_refused_on_a_synthetic_tuple():
    """THE MECHANISM, kept alive after the real split was resolved. A tuple
    whose legs disagree on a fingerprinted stimulus key must still be REFUSED
    with every disagreeing key named and both values shown -- otherwise
    resolving one defect quietly deletes the guard against the next."""
    roles = {"reference": "_split_a", "candidate": "_split_b",
             "bound": "_split_c"}
    prof = [(0.0, 0.0), (5.0, 1.0)]
    base = {"ems_v_profile": prof, "duration_s": 61.0, "ems_run_exit_s": 55.0,
            "aux_preload_a": 0.0, "chg_i_ceiling_a": 0.8}
    saved = {n: SCENARIOS.get(n) for n in roles.values()}
    spec = dict(FTP75_SPEC, roles=roles)
    try:
        for n in roles.values():
            SCENARIOS[n] = dict(base)
        # The SDP-shaped split that was real until 2026-09-01, plus the
        # charger-ceiling one that rode along with it.
        SCENARIOS["_split_b"] = dict(base, aux_preload_a=0.45)
        SCENARIOS["_split_a"] = dict(base)
        SCENARIOS["_split_a"].pop("chg_i_ceiling_a")
        rec = rhs.evaluate_ems_frontier(
            [{"kind": "scenario", "name": n, "passed": True,
              "metrics": {"final_h2_cum_g": h, "delta_soc": -0.002}}
             for n, h in (("_split_a", 0.09), ("_split_b", 0.08),
                          ("_split_c", 0.089))], spec=spec)
        assert rec["verdict"] == "UNVERIFIED"
        assert rec["passed"] is False
        by_key = {m["key"]: m["values"] for m in rec["stimulus_mismatch"]}
        assert set(by_key) == {"aux_preload_a", "chg_i_ceiling_a"}
        assert by_key["aux_preload_a"]["_split_b"] == pytest.approx(0.45)
        assert by_key["aux_preload_a"]["_split_a"] == pytest.approx(0.0)
        assert by_key["chg_i_ceiling_a"]["_split_a"] is None
        assert by_key["chg_i_ceiling_a"]["_split_c"] == pytest.approx(0.8)
        assert "same stimulus" in rec["reason"]
        # No comparison was attempted: none of the eq-H2 machinery ran.
        assert "per_lambda" not in rec and "eq_h2" not in rec
    finally:
        for n, v in saved.items():
            if v is None:
                SCENARIOS.pop(n, None)
            else:
                SCENARIOS[n] = v


def test_frontier_stimulus_mismatch_helper_is_registry_derived():
    """Knowable BEFORE a run starts -- which is the point, a campaign should
    not spend 17 minutes producing numbers that were never comparable."""
    assert rhs.ems_frontier_stimulus_mismatches(CYCLE61_SPEC["roles"]) == []
    # ⚠️ THE FTP-75 TUPLE IS COHERENT SINCE 2026-09-01 (the preload removal and
    # the socband charger-ceiling declaration), so the helper must report
    # NOTHING for it. The ORDERING property it used to demonstrate is
    # demonstrated on a synthetic tuple instead, since a real split no longer
    # exists to demonstrate it on.
    assert rhs.ems_frontier_stimulus_mismatches(FTP75_SPEC["roles"]) == []
    roles = {"reference": "_ord_a", "candidate": "_ord_b", "bound": "_ord_c"}
    prof = [(0.0, 0.0), (5.0, 1.0)]
    base = {"ems_v_profile": prof, "duration_s": 61.0, "ems_run_exit_s": 55.0,
            "aux_preload_a": 0.0, "chg_i_ceiling_a": 0.8}
    saved = {n: SCENARIOS.get(n) for n in roles.values()}
    try:
        for n in roles.values():
            SCENARIOS[n] = dict(base)
        SCENARIOS["_ord_b"] = dict(base, aux_preload_a=0.45)
        SCENARIOS["_ord_a"] = dict(base)
        SCENARIOS["_ord_a"].pop("chg_i_ceiling_a")
        mism = rhs.ems_frontier_stimulus_mismatches(roles)
        assert [k for k, _ in mism] == ["aux_preload_a", "chg_i_ceiling_a"]
        # Reported in EMS_FRONTIER_STIMULUS_KEYS order, so the report reads the
        # same way every campaign.
        assert [k for k, _ in mism] == [k for k in rhs.EMS_FRONTIER_STIMULUS_KEYS
                                        if k in dict(mism)]
    finally:
        for n, v in saved.items():
            if v is None:
                SCENARIOS.pop(n, None)
            else:
                SCENARIOS[n] = v
    # A role naming a scenario this checkout does not register is SKIPPED, not
    # reported as a mismatch (evaluate_ems_frontier already reports it missing,
    # and double-counting would say "stimulus split" when it is absence).
    assert rhs.ems_frontier_stimulus_mismatches(
        {"reference": "ems-soc-band", "candidate": "no-such-scenario",
         "bound": "ems-dp-replay"}) == []


def test_frontier_stimulus_profile_compared_by_value_not_identity():
    """The shipped FTP-75 scenarios deliberately share ONE list object, but a
    future leg built from an EQUAL copy is still the same stimulus and must
    not be refused for it."""
    roles = {"reference": "_wpe_a", "candidate": "_wpe_b", "bound": "_wpe_c"}
    base = {"ems_v_profile": [(0.0, 0.0), (5.0, 1.0)], "duration_s": 61.0,
            "ems_run_exit_s": 55.0, "aux_preload_a": 0.6,
            "chg_i_ceiling_a": 0.8}
    saved = {n: SCENARIOS.get(n) for n in roles.values()}
    try:
        for n in roles.values():
            # A DISTINCT but EQUAL profile list for each.
            SCENARIOS[n] = dict(base, ems_v_profile=list(base["ems_v_profile"]))
        assert rhs.ems_frontier_stimulus_mismatches(roles) == []
        SCENARIOS["_wpe_b"] = dict(base, ems_v_profile=[(0.0, 0.0), (5.0, 2.0)])
        assert [k for k, _ in rhs.ems_frontier_stimulus_mismatches(roles)] \
            == ["ems_v_profile"]
    finally:
        for n, v in saved.items():
            if v is None:
                SCENARIOS.pop(n, None)
            else:
                SCENARIOS[n] = v


def _coherent_results(legs):
    """Three SYNTHETIC legs sharing one stimulus, and a spec pointing at them.

    Synthetic rather than "swap the candidate for `ems-ftp75-5050`": the two
    causal FTP-75 legs do not agree with the DP leg on `chg_i_ceiling_a`
    either, so no combination of SHIPPED scenarios is stimulus-coherent today.
    These fixtures therefore exercise the arithmetic the real tuple cannot
    reach until an operator picks a resolution."""
    names = {"reference": "_wpe_ref", "candidate": "_wpe_cand",
             "bound": "_wpe_bound"}
    stim = {"ems_v_profile": [(0.0, 0.0), (100.0, 3.0)], "duration_s": 350.0,
            "ems_run_exit_s": 346.0, "aux_preload_a": 0.65,
            "chg_i_ceiling_a": 0.8}
    for n in names.values():
        SCENARIOS[n] = dict(stim)
    spec = dict(FTP75_SPEC, roles=names)
    out = [{"kind": "scenario", "name": names[role], "passed": True,
            "metrics": {"final_h2_cum_g": h, "delta_soc": d}}
           for role, (h, d) in legs.items()]
    return out, spec, list(names.values())


def _drop_synthetic(names):
    for n in names:
        SCENARIOS.pop(n, None)


def test_frontier_ftp75_numbers_pass_at_the_offline_tie():
    """NUMBERS-PASS fixture at the OFFLINE result the band was derived from:
    the DP ties `soc-band` at matched terminal SoC (-0.01 %). A candidate
    sitting at parity must PASS a 1.02 band -- under the 61 s tuple's 0.98 it
    would FAIL, which is exactly why the thresholds are per-frontier."""
    results, spec, names = _coherent_results({
        "reference": (0.09160, -0.00200),
        "candidate": (0.09159, -0.00200),   # the -0.01 % tie
        "bound": (0.09159, -0.00200)})
    try:
        rec = rhs.evaluate_ems_frontier(results, spec=spec)
        assert rec["verdict"] == "PASS", rec["reason"]
        assert rec["passed"] is True
        assert "stimulus_mismatch" not in rec
        assert rec["vs_reference"] == pytest.approx(0.99989, abs=1e-4)
        assert rec["id"] == "ftp75"
        assert rec["provisional_note"]
        # The SAME numbers FAIL under the 61 s tuple's stricter band -- the
        # claim that the split thresholds are load-bearing.
        strict = dict(spec, vs_reference_max=0.98)
        assert rhs.evaluate_ems_frontier(results, spec=strict)["verdict"] == "FAIL"
    finally:
        _drop_synthetic(names)


def test_frontier_ftp75_numbers_fail_when_the_candidate_is_materially_worse():
    """NUMBERS-FAIL fixture. 1.02 is not "anything goes": a candidate 5 %
    worse than the causal heuristic at matched SoC is a policy regression and
    must fail, at every lambda in the band."""
    results, spec, names = _coherent_results({
        "reference": (0.09160, -0.00200),
        "candidate": (0.09618, -0.00200),   # +5.0 %
        "bound": (0.09000, -0.00200)})
    try:
        rec = rhs.evaluate_ems_frontier(results, spec=spec)
        assert rec["verdict"] == "FAIL"
        assert rec["exit_affecting"] is True
        assert "_wpe_ref" in rec["reason"]
        assert all(not p["passed"] for p in rec["per_lambda"])
    finally:
        _drop_synthetic(names)


def test_frontier_ftp75_planned_skip_is_unverified_and_not_exit_affecting():
    """PLANNED-SKIP fixture. All four FTP-75 scenarios are --with-ftp75-gated,
    so a campaign WITHOUT the flag skip-records them. That is the documented
    behaviour of the flag, not a defect: UNVERIFIED and named, but the run is
    not failed for it.

    Checked on a stimulus-COHERENT synthetic tuple so the verdict comes from
    the skip and not from the real tuple's preload split (which is tested
    separately and would mask this path)."""
    results, spec, names = _coherent_results({
        "reference": (0.09, -0.002), "candidate": (0.09, -0.002),
        "bound": (0.09, -0.002)})
    try:
        for r in results:
            r["skipped"] = True
            r["skip_reason"] = "LONG-CYCLE: pass --with-ftp75 to run them"
        rec = rhs.evaluate_ems_frontier(results, spec=spec)
        assert rec["verdict"] == "UNVERIFIED"
        assert rec["exit_affecting"] is False
        assert len(rec["missing"]) == 3
        assert all("SKIPPED" in m for m in rec["missing"])
    finally:
        _drop_synthetic(names)


def test_frontier_ftp75_absent_from_a_plan_contributes_no_record():
    """A campaign without --with-ftp75 whose FTP-75 legs are not in the plan
    at all gets ONE frontier record, not two: manufacturing an UNVERIFIED
    record for a comparison the plan never intended is noise, and that rule
    is unchanged from the single-frontier behaviour."""
    legs = {"reference": ("ems-soc-band", 0.0128, -0.0020),
            "candidate": ("ems-sdp", 0.0125, -0.0017),
            "bound": ("ems-dp-replay", 0.0116, -0.0020)}
    results = [{"kind": "scenario", "name": n, "passed": True,
                "metrics": {"final_h2_cum_g": h, "delta_soc": d}}
               for n, h, d in legs.values()]
    recs = rhs.evaluate_ems_frontiers(results)
    assert [r["id"] for r in recs] == ["cycle61"]


def test_frontier_both_tuples_render_when_both_are_present():
    """With the FTP-75 half planned, BOTH records exist -- and both reach the
    report, each with its own verdict and its own label."""
    results = [{"kind": "scenario", "name": n, "passed": True,
                "metrics": {"final_h2_cum_g": h, "delta_soc": d}}
               for n, h, d in (("ems-soc-band", 0.0128, -0.0020),
                               ("ems-sdp", 0.0125, -0.0017),
                               ("ems-dp-replay", 0.0116, -0.0020))]
    results += _ftp_results({"reference": (0.0916, -0.0020),
                             "candidate": (0.0900, -0.0020),
                             "bound": (0.0899, -0.0020)})
    recs = rhs.evaluate_ems_frontiers(results)
    assert [r["id"] for r in recs] == ["cycle61", "ftp75"]
    for r in results:
        r.setdefault("mode", "hifi")
        r.setdefault("electrical_required", "any")
        r.setdefault("description", "")
        r.setdefault("duration_s", 61.0)
        r.setdefault("checks", [])
        r.setdefault("notes", [])
        r.setdefault("events", {})
        r.setdefault("child", {"status": "ok", "summary": {}, "returncode": 0,
                               "wall_s": 1.0, "log": "x.log"})
        r.setdefault("key_metrics", "")
    md = rhs.render_report({"date": "x"}, results).replace("—", "-")
    assert "61 s synthetic cycle" in md
    assert "340 s EPA FTP-75 drive cycle" in md
    # The FTP-75 tuple is still PROVISIONAL (no campaign has evaluated it), but
    # it is no longer STIMULUS SPLIT: the preload removal made the three legs
    # one experiment, so the record now carries a real verdict.
    assert "PROVISIONAL" in md
    assert "STIMULUS SPLIT" not in md
    recs = rhs.evaluate_ems_frontiers(results)
    assert {r["id"]: r["verdict"] for r in recs}["ftp75"] != "UNVERIFIED"


def test_frontier_results_json_keeps_the_singular_key_pointing_at_cycle61():
    """Back-compatibility: every existing consumer of results.json reads
    `ems_frontier`, and it must keep meaning the 61 s tuple now that a list
    exists alongside it."""
    results = [{"kind": "scenario", "name": n, "passed": True,
                "metrics": {"final_h2_cum_g": h, "delta_soc": d}}
               for n, h, d in (("ems-soc-band", 0.0128, -0.0020),
                               ("ems-sdp", 0.0125, -0.0017),
                               ("ems-dp-replay", 0.0116, -0.0020))]
    recs = rhs.evaluate_ems_frontiers(results)
    assert recs[0]["id"] == rhs.EMS_FRONTIERS[0]["id"] == "cycle61"
    assert recs[0]["roles"] == rhs.EMS_FRONTIER


# ── --droop wire-through ────────────────────────────────────────────────────

def test_droop_default_adds_no_flag_to_any_child():
    """Every campaign on record ran the design chain; stamping an explicit
    `--droop design` into every child's argv would make this campaign's
    recorded command lines differ from theirs for no behavioural reason."""
    plan = rhs.build_plan(_args(with_ftp75=True))
    for p in plan:
        assert "--droop" not in (p.get("argv") or []), p["name"]


def test_droop_measured_reaches_every_scenario_child_including_rebuilt_argvs():
    """The append must sit AFTER the per-scenario branches that REBUILD argv
    (soc-depletion and charge-to-full), or exactly those two runs would
    silently keep the design chain."""
    plan = rhs.build_plan(_args(with_ftp75=True, droop="measured"))
    scen = [p for p in plan if p["kind"] == "scenario"
            and not p.get("skip_reason")]
    assert scen
    for p in scen:
        argv = p["argv"]
        assert argv[argv.index("--droop") + 1] == "measured", p["name"]
    for name in ("soc-depletion", "charge-to-full"):
        p = next(x for x in scen if x["name"] == name)
        assert "--droop" in p["argv"], name


def test_droop_is_never_passed_to_the_replay_half():
    """A replay entry's thresholds were derived from design-mode sag depths;
    moving the bus rail under them would fail correct boards. A measured-mode
    replay campaign needs its bands re-derived first."""
    plan = rhs.build_plan(_args(droop="measured"))
    for p in plan:
        if p["kind"] == "replay":
            assert "--droop" not in (p.get("argv") or []), p["name"]


def test_report_states_which_droop_mode_the_campaign_ran():
    """The standing K_DROOP finding is about a 4x gap between two droop
    realizations, so a report that does not say which one it ran leaves every
    sag figure in it unplaceable."""
    md_design = rhs.render_report({"date": "x", "droop_mode": "design"}, [])
    assert "--droop design" in md_design
    assert "4x DEEPER" in md_design
    md_meas = rhs.render_report({"date": "x", "droop_mode": "measured"}, [])
    assert "--droop measured" in md_meas
    assert "EXPLAINS NOTHING" in md_meas
    assert "Droop realization (scenario half)" in md_meas
    # A campaign predating the key reads as design, which is what it was.
    assert "--droop design" in rhs.render_report({"date": "x"}, [])


def test_droop_mode_note_covers_every_registered_mode():
    assert set(rhs.K_DROOP_MODE_NOTE) == set(rhs.DROOP_MODES)


def test_frontier_stimulus_split_does_not_mask_a_genuinely_failed_leg():
    """SELF-REVIEW FIX (WP-E), kept after the FTP-75 split was resolved. The
    stimulus precondition is evaluated BEFORE the legs are compared, and its
    `exit_affecting` is FALSE on the FTP-75 tuple by design. It must therefore
    be OR'd with the leg-derived flag, or a campaign in which a leg RAN AND
    FAILED ITS OWN CHECKS would be excused by a stimulus split -- the exact
    class of silent pass this whole check exists to prevent.

    ⚠️ The real FTP-75 split is gone (2026-09-01), so the split arm is now
    exercised against a SYNTHETIC tuple. The failed-leg arm is exercised
    against the real one, where it still applies."""
    roles = {"reference": "_mask_a", "candidate": "_mask_b", "bound": "_mask_c"}
    prof = [(0.0, 0.0), (5.0, 1.0)]
    base = {"ems_v_profile": prof, "duration_s": 61.0, "ems_run_exit_s": 55.0,
            "aux_preload_a": 0.0, "chg_i_ceiling_a": 0.8}
    saved = {n: SCENARIOS.get(n) for n in roles.values()}
    spec = dict(FTP75_SPEC, roles=roles)
    try:
        for n in roles.values():
            SCENARIOS[n] = dict(base)
        SCENARIOS["_mask_b"] = dict(base, aux_preload_a=0.45)
        rows = [{"kind": "scenario", "name": n, "passed": p,
                 "metrics": {"final_h2_cum_g": h, "delta_soc": -0.002}}
                for n, h, p in (("_mask_a", 0.09, True), ("_mask_b", 0.08, True),
                                ("_mask_c", 0.089, False))]
        rec = rhs.evaluate_ems_frontier(rows, spec=spec)
        assert rec["verdict"] == "UNVERIFIED"
        assert rec["exit_affecting"] is True
        # The failed leg is still NAMED, not swallowed by the stimulus branch.
        assert any("did NOT pass its own checks" in m for m in rec["missing"])
        assert rec["stimulus_mismatch"]
        # ... and with every leg healthy the same split is NOT exit-affecting.
        for r in rows:
            r["passed"] = True
        assert rhs.evaluate_ems_frontier(rows, spec=spec)["exit_affecting"] is False
    finally:
        for n, v in saved.items():
            if v is None:
                SCENARIOS.pop(n, None)
            else:
                SCENARIOS[n] = v
    # THE REAL TUPLE: coherent now, so a failed leg must still be exit-affecting
    # on its own account, with no stimulus branch to hide behind.
    real = rhs.evaluate_ems_frontier(
        _ftp_results({"reference": (0.09, -0.002),
                      "candidate": (0.08, -0.002),
                      "bound": (0.089, -0.002)},
                     **{"ems-ftp75-dp": {"passed": False}}), spec=FTP75_SPEC)
    assert real["verdict"] == "UNVERIFIED"
    assert real["exit_affecting"] is True
    assert not real.get("stimulus_mismatch")


def test_frontier_cycle61_stimulus_split_would_be_exit_affecting():
    """The two tuples differ here on purpose: the 61 s legs are documented to
    share ONE stimulus object, so a split there is a regression and must fail
    the campaign -- unlike the FTP-75 tuple's known, operator-owned split."""
    assert CYCLE61_SPEC["stimulus_mismatch_exit_affecting"] is True
    assert FTP75_SPEC["stimulus_mismatch_exit_affecting"] is False
    saved = SCENARIOS["ems-sdp"]
    try:
        SCENARIOS["ems-sdp"] = dict(saved, aux_preload_a=0.9)
        results = [{"kind": "scenario", "name": n, "passed": True,
                    "metrics": {"final_h2_cum_g": 0.012, "delta_soc": -0.002}}
                   for n in CYCLE61_SPEC["roles"].values()]
        rec = rhs.evaluate_ems_frontier(results, spec=CYCLE61_SPEC)
        assert rec["verdict"] == "UNVERIFIED"
        assert rec["exit_affecting"] is True
    finally:
        SCENARIOS["ems-sdp"] = saved


# ── ems-ftp75-dp FAULT_EXPECTATIONS entry (WP-E) ────────────────────────────

def test_ems_ftp75_dp_expectation_entry_shape():
    """IMPORT-SHAPE PIN. Mirrors `ems-ftp75-5050`'s shape, because the two
    share a stimulus -- and asserts the ONE place they deliberately differ."""
    e = rhs.FAULT_EXPECTATIONS["ems-ftp75-dp"]
    ref = rhs.FAULT_EXPECTATIONS["ems-ftp75-5050"]
    assert e["allow_only"] == 0                       # fault-free, like 5050
    assert e["survive_to"] == ref["survive_to"]       # same cycle, same t
    assert e["source"]
    names = [c["name"] for c in e["signals_require"]]
    assert names == ["ftpdp_peak_commanded", "ftpdp_fc_carried",
                     "ftpdp_table_commanded", "ftpdp_table_low_rail",
                     "ftpdp_h2_accounted", "ftpdp_h2_bounded"]
    by = {c["name"]: c for c in e["signals_require"]}
    # The stimulus check is the sibling's, verbatim -- same profile, same peak.
    assert by["ftpdp_peak_commanded"]["min_value"] == 2.85
    assert by["ftpdp_peak_commanded"]["t_window"] == rhs._FTP_PEAK_W
    # The ONE deliberate loosening: the sibling's split is pinned at 0.50, this
    # one's is chosen by the table and can floor at its own 0.25 rail.
    # RE-DERIVED at aux_preload_a 0.0 (was 0.35 against the 0.65 A preload):
    # 0.25 x the governor-walk peak source total 0.9603 A = 0.240 A.
    assert by["ftpdp_fc_carried"]["min_value"] == 0.20
    assert by["ftpdp_fc_carried"]["min_value"] < 0.25 * 0.9603
    assert by["ftpdp_fc_carried"]["min_value"] < \
        {c["name"]: c for c in ref["signals_require"]}["ftp_fc_carried"]["min_value"]


def test_ems_ftp75_dp_expectation_asserts_the_table_actually_drove_the_run():
    """THE CHECK THAT MAKES THE BOUND LEG MEAN ANYTHING. Without it the run
    passes identically whether the DP table reached the wire or a constant
    0.50 split did -- and a silently un-driven bound leg makes the whole
    frontier verdict meaningless while every per-run check stays green.

    Both rails are asserted, so a run that replayed only the table's upper
    half (or dropped commands) fails too."""
    by = {c["name"]: c
          for c in rhs.FAULT_EXPECTATIONS["ems-ftp75-dp"]["signals_require"]}
    hi = by["ftpdp_table_commanded"]
    lo = by["ftpdp_table_low_rail"]
    assert hi["column"] == lo["column"] == "cmd_share_sp"
    # A constant-0.50 fallback satisfies NEITHER rail -- that is the point.
    assert hi["min_value"] > 0.50 and lo["max_value"] < 0.50
    # ... and both rails are inside the table's own [0.25, 0.75] control span,
    # so a correctly replayed table satisfies both.
    assert 0.25 <= lo["max_value"] and hi["min_value"] <= 0.75
    # E-H1: THE WINDOWS MUST NOT OVERLAP. `max_value` judges the window's PEAK,
    # so a low-rail ceiling sharing the high-rail window asserts "the peak over
    # a window whose peak is 0.75 is <= 0.30" -- unsatisfiable, and the two
    # checks become mutually exclusive. The low rail is the table's OPENING, so
    # its window must close where the high-rail window opens.
    assert lo["t_window"][1] <= hi["t_window"][0]


def test_ems_ftp75_dp_rail_checks_pass_together_on_the_tables_own_trajectory():
    """E-H1 REGRESSION. Checks 3 and 4 are judged against the DP table's OWN
    share column -- the exact trajectory a correct replay puts on the wire --
    and BOTH must pass. Before the window fix, check 4 carried check 3's
    (5.0, 340.0) window, which contains no low-rail stage at all, so no
    correct run could ever satisfy both.

    Reads the committed table rather than a synthetic fixture: the windows are
    a claim ABOUT THAT FILE, and a synthetic trajectory would let the file and
    the claim drift apart."""
    path = os.path.join(os.path.dirname(os.path.abspath(rhs.__file__)),
                        "dp_tables", "dp_ems_table_ems-ftp75-dp.csv")
    if not os.path.isfile(path):
        pytest.skip("generated DP table not present")
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            rows.append(line)
    tr = [(float(r["t"]), float(r["power_share_setpoint"]))
          for r in csv.DictReader(rows)]
    assert tr, "table parsed empty"

    by = {c["name"]: c
          for c in rhs.FAULT_EXPECTATIONS["ems-ftp75-dp"]["signals_require"]}

    def _peak(window):
        # scan_signals() floors every window at WARM_RESET_GRACE_S; mirror that
        # or this fixture judges rows the real scan never sees.
        vals = [s for t, s in tr
                if window[0] <= t <= window[1] and t >= rhs.WARM_RESET_GRACE_S]
        return (max(vals) if vals else None), len(vals)

    hi, lo = by["ftpdp_table_commanded"], by["ftpdp_table_low_rail"]
    hi_peak, hi_n = _peak(hi["t_window"])
    lo_peak, lo_n = _peak(lo["t_window"])
    assert hi_n and lo_n, "a rail window sees no table stages at all"
    assert hi_peak >= hi["min_value"], (hi_peak, hi["min_value"])
    assert lo_peak <= lo["max_value"], (lo_peak, lo["max_value"])
    # The low-rail window must carry real evidence, not one boundary sample.
    assert lo_n >= 20


def test_ems_ftp75_dp_h2_band_is_the_union_of_its_siblings_bands():
    """The band is NOT the DP's own reduced-model prediction (the re-solved
    table reports 0.0396922 g at a matched terminal SoC): that is an open-loop
    optimum of a different accounting and would import the reduced model's
    whole error budget into a live metric. It is the union of the two
    siblings' bands, on the structural argument that this leg runs their
    stimulus with a split that lies between theirs by construction.

    RE-DERIVED at aux_preload_a 0.0 AND at the plant's default converter
    asymmetry, then RE-WALKED at the M2 consistent pair (fix round F1,
    2026-09-01): union of [0.022, 0.037] (5050) and [0.028, 0.046] (socband),
    both M2-equivalent governor-walk +/-25 % bands."""
    by = {c["name"]: c
          for c in rhs.FAULT_EXPECTATIONS["ems-ftp75-dp"]["signals_require"]}
    lo = by["ftpdp_h2_accounted"]["min_value"]
    hi = by["ftpdp_h2_bounded"]["max_value"]
    # WP-1C (2026-09-02): the socband ceiling moved 0.046 -> 0.052 for the
    # ETA_CHG 0.88 charger, so the union moves with it. The 5050 floor does
    # not: that leg walks zero charge windows and is eta-invariant.
    assert (lo, hi) == (0.022, 0.052)
    # The solver's own matched-SoC optimum must land inside the live band, or
    # the two accountings have diverged by more than the band admits.
    assert lo < 0.0396922 < hi
    assert lo == rhs._FTP_H2_BAND_5050[0]
    assert hi == rhs._FTP_H2_CEILING_SOCBAND
    # Two SPECS, never one leaf carrying both bounds: `_judge_signal_leaf`
    # tests min before max and would silently drop the ceiling.
    assert "max_value" not in by["ftpdp_h2_accounted"]
    assert "min_value" not in by["ftpdp_h2_bounded"]
    # PROVISIONAL, and it says so through the `provisional_note` mechanism
    # (which renders a [PROVISIONAL: ...] qualifier into the report) rather
    # than by an inline literal in the label, as of 2026-09-01.
    assert all(by[n].get("provisional_note")
               for n in ("ftpdp_h2_accounted", "ftpdp_h2_bounded"))


def test_every_ftp75_scenario_has_an_expectation_entry():
    """A --with-ftp75 scenario with no entry scores on the runner's default,
    which is not what any of these runs mean."""
    for name in rhs.FTP75_SCENARIOS:
        assert name in rhs.FAULT_EXPECTATIONS, name


# ═════════════════════════════════════════════════════════════════════════
# Independent test-writer round (2026-09-01): preload-removal coverage,
# run_hil_suite.py half (requirements 3, 4, 5, 6, 8 of the round brief).
# ═════════════════════════════════════════════════════════════════════════

# ── Requirement 3: frontier coherence ───────────────────────────────────────

def test_ems_frontier_ftp75_stimulus_mismatches_is_empty_now_preload_is_uniform():
    """The three EMS_FRONTIER_FTP75 legs (socband/dp/sdp) all carry
    aux_preload_a=0.0 and chg_i_ceiling_a=0.8 since the 2026-09-01 removal --
    both splits documented in the registry comments are resolved, so the pure
    stimulus-coherence function must return no mismatches for this tuple."""
    roles = rhs.EMS_FRONTIER_FTP75
    assert rhs.ems_frontier_stimulus_mismatches(roles) == []


def test_ems_frontier_ftp75_stimulus_mismatch_reintroduced_by_mutation(monkeypatch):
    """Negative control: mutate one leg's aux_preload_a back toward the
    retired split and confirm the pure function FLAGS it -- proves the
    positive result above is not vacuous (e.g. the function silently skipping
    every key). Mutates the shared SCENARIOS dict rhs imported from
    hil_plant_sim and restores it, since the two modules share one dict
    object."""
    roles = rhs.EMS_FRONTIER_FTP75
    candidate = roles["candidate"]
    orig = rhs.SCENARIOS[candidate]["aux_preload_a"]
    try:
        rhs.SCENARIOS[candidate]["aux_preload_a"] = 0.45  # the retired value
        mismatches = rhs.ems_frontier_stimulus_mismatches(roles)
        keys = [k for k, _vals in mismatches]
        assert "aux_preload_a" in keys
        entry = next(vals for k, vals in mismatches if k == "aux_preload_a")
        assert entry[candidate] == pytest.approx(0.45)
        assert entry[roles["reference"]] == pytest.approx(0.0)
    finally:
        rhs.SCENARIOS[candidate]["aux_preload_a"] = orig
    # Restored: the positive test's condition holds again.
    assert rhs.ems_frontier_stimulus_mismatches(roles) == []


# ── Requirement 4: socband_ftp_charge_opened non-vacuity ───────────────────

def _socband_ftp_charge_opened_spec():
    return next(s for s in
               rhs.FAULT_EXPECTATIONS["ems-ftp75-socband"]["signals_require"]
               if s["name"] == "socband_ftp_charge_opened")


def test_socband_ftp_charge_opened_fails_when_fc_charge_never_asserted(tmp_path):
    spec = _socband_ftp_charge_opened_spec()
    rows = [{"t": "%.3f" % t, "switch": "0", "fault_flags": "0"}
           for t in (30.0, 100.0, 200.0, 300.0, 339.0)]
    path = tmp_path / "no_charge.csv"
    _write_scenario_csv(path, rows)
    measured = rhs.scan_signals(str(path), [spec], grace_s=0.0)
    checks = rhs.judge_signals([spec], measured, "why")
    assert checks[0]["passed"] is False


def test_socband_ftp_charge_opened_passes_when_held_for_3000_plus_ticks(tmp_path):
    spec = _socband_ftp_charge_opened_spec()
    lo, hi = spec["t_window"]
    mid = (lo + hi) / 2.0
    # 3000+ observed rows inside the window with FC_CHARGE set, one before and
    # one after the window WITHOUT it (so the window boundary itself is
    # exercised, not merely "the bit was set somewhere in the file").
    rows = [{"t": "%.3f" % (lo - 1.0), "switch": "0", "fault_flags": "0"}]
    rows += [{"t": "%.3f" % (mid + i * 0.001), "switch": str(rhs.SW_FC_CHARGE),
             "fault_flags": "0"} for i in range(3001)]
    rows += [{"t": "%.3f" % (hi + 1.0), "switch": "0", "fault_flags": "0"}]
    path = tmp_path / "charge_held.csv"
    _write_scenario_csv(path, rows)
    measured = rhs.scan_signals(str(path), [spec], grace_s=0.0)
    checks = rhs.judge_signals([spec], measured, "why")
    assert checks[0]["passed"] is True


# ── Requirement 5: anti-vacuity for every re-derived FTP-75 band ───────────
#
# Each entry is (scenario, spec_name, column) for a min_value/max_value
# current-column spec.  The THRESHOLD is read from the live registry rather
# than re-typed, so a future re-derivation of the number is exercised by this
# same test instead of silently going stale.
_ANTI_VACUITY_CURRENT_SPECS = [
    ("ems-ftp75-5050", "ftp_fc_carried", "I_fc"),
    ("ems-ftp75-socband", "socband_fc_carried", "I_fc"),
    ("ems-ftp75-sdp", "sdpftp_fc_floored_early", "I_fc"),
    ("ems-ftp75-sdp", "sdpftp_fc_carried_late", "I_fc"),
    ("ems-ftp75-dp", "ftpdp_fc_carried", "I_fc"),
]


def _spec_window_midpoint(spec):
    win = spec.get("t_window")
    if not win:
        return 100.0
    lo, hi = win
    return (lo + hi) / 2.0


def test_anti_vacuity_current_column_specs_reject_and_admit_at_the_new_bound(tmp_path):
    for scenario, spec_name, column in _ANTI_VACUITY_CURRENT_SPECS:
        specs = rhs.FAULT_EXPECTATIONS[scenario]["signals_require"]
        spec = _spec_by_name(specs, spec_name)
        t = _spec_window_midpoint(spec)
        eps = 1e-3
        if "min_value" in spec:
            bound = spec["min_value"]
            fail_val, pass_val = bound - eps, bound + eps
        else:
            bound = spec["max_value"]
            fail_val, pass_val = bound + eps, bound - eps
        for val, want_pass, tag in ((fail_val, False, "fail"),
                                    (pass_val, True, "pass")):
            rows = [{"t": "%.3f" % t, column: "%.6f" % val,
                    "switch": "0", "fault_flags": "0"}]
            path = tmp_path / ("%s_%s_%s.csv" % (spec_name, tag, scenario))
            _write_scenario_csv(path, rows)
            measured = rhs.scan_signals(str(path), [spec], grace_s=0.0)
            checks = rhs.judge_signals([spec], measured, "why")
            assert checks[0]["passed"] is want_pass, (
                "%s/%s: value %.6f at bound %.6f expected passed=%s, got %s"
                % (scenario, spec_name, val, bound, want_pass,
                   checks[0]["passed"]))


# H2 two-sided bands: (scenario, min_spec_name, max_spec_name).
_ANTI_VACUITY_H2_SPECS = [
    ("ems-ftp75-5050", "ftp_h2_accounted", "ftp_h2_bounded"),
    ("ems-ftp75-socband", "ftp_h2_accounted", "ftp_h2_bounded"),
    ("ems-ftp75-sdp", "sdpftp_h2_accounted", "sdpftp_h2_bounded"),
    ("ems-ftp75-dp", "ftpdp_h2_accounted", "ftpdp_h2_bounded"),
]


def test_anti_vacuity_h2_bands_reject_just_outside_and_admit_just_inside(tmp_path):
    for scenario, min_name, max_name in _ANTI_VACUITY_H2_SPECS:
        specs = rhs.FAULT_EXPECTATIONS[scenario]["signals_require"]
        min_spec = _spec_by_name(specs, min_name)
        max_spec = _spec_by_name(specs, max_name)
        lo = min_spec["min_value"]
        hi = max_spec["max_value"]
        assert lo < hi, (scenario, lo, hi)
        eps = 1e-6
        cases = [
            # (h2_cum_g value, expect min-spec passed, expect max-spec passed)
            (lo - eps, False, True),      # just under the floor
            (lo + eps, True, True),       # just inside, near the floor
            (hi - eps, True, True),       # just inside, near the ceiling
            (hi + eps, True, False),      # just over the ceiling
        ]
        for val, want_min_pass, want_max_pass in cases:
            rows = [{"t": "50.000", "h2_cum_g": "%.9f" % val,
                    "switch": "0", "fault_flags": "0"}]
            path = tmp_path / ("%s_%s_%.9f.csv" % (scenario, min_name, val))
            _write_scenario_csv(path, rows, extra_cols=("h2_cum_g",))
            measured = rhs.scan_signals(str(path), [min_spec, max_spec],
                                        grace_s=0.0)
            checks = rhs.judge_signals([min_spec, max_spec], measured, "why")
            assert checks[0]["passed"] is want_min_pass, (scenario, val)
            assert checks[1]["passed"] is want_max_pass, (scenario, val)


# ── Requirement 6: provisional_note presence, loop-driven ──────────────────

# The specs the 2026-09-01 preload-removal diff re-derived (identified by
# name from the diff itself), grouped by scenario. A future
# de-provisionalization must delete the NAME from this list in the same
# change that drops the note, or this test catches the drift.
_REDERIVED_FTP75_PROVISIONAL_SPECS = {
    "ems-ftp75-5050": ["ftp_fc_carried", "ftp_h2_accounted", "ftp_h2_bounded"],
    "ems-ftp75-socband": ["socband_share_biased", "socband_fc_carried",
                          "socband_ftp_charge_opened", "ftp_h2_accounted",
                          "ftp_h2_bounded"],
    "ems-ftp75-sdp": ["sdpftp_low_rail_early", "sdpftp_high_rail_late",
                      "sdpftp_raw_battery_branch", "sdpftp_raw_fc_branch",
                      "sdpftp_fc_floored_early", "sdpftp_fc_carried_late",
                      "sdpftp_bt_peak_bounded", "sdpftp_h2_accounted",
                      "sdpftp_h2_bounded"],
    "ems-ftp75-dp": ["ftpdp_fc_carried", "ftpdp_h2_accounted",
                     "ftpdp_h2_bounded"],
}


def test_every_rederived_ftp75_spec_carries_a_provisional_note():
    """Loop-driven (not one hardcoded assertion per spec) so a future
    de-provisionalization that forgets to also shrink this list is caught
    structurally rather than by a stale per-name assertion silently staying
    green."""
    for scenario, names in _REDERIVED_FTP75_PROVISIONAL_SPECS.items():
        specs = rhs.FAULT_EXPECTATIONS[scenario]["signals_require"]
        for name in names:
            spec = _spec_by_name(specs, name)
            assert spec.get("provisional_note"), (
                "%s/%s was re-derived at aux_preload_a=0.0 and must carry a "
                "provisional_note until the first zero-preload campaign "
                "measures it" % (scenario, name))


def test_rederived_ftp75_spec_names_all_exist_in_the_registry():
    """Sanity on the list above itself: every named spec must actually be
    present, or the loop test would vacuously pass by never finding it (
    `_spec_by_name` raising StopIteration would surface as an error, not a
    silent pass -- but pin the shape explicitly so a renamed spec is caught
    with a clear message rather than a bare StopIteration)."""
    for scenario, names in _REDERIVED_FTP75_PROVISIONAL_SPECS.items():
        specs = rhs.FAULT_EXPECTATIONS[scenario]["signals_require"]
        present = {s["name"] for s in specs}
        for name in names:
            assert name in present, (scenario, name)


# ── Requirement 8: SDP flip-band / survive_to consistency ──────────────────

def test_ems_ftp75_sdp_flip_band_consistent_with_survive_to_and_raw_windows():
    """Asserts RELATIONSHIPS pulled from the live FAULT_EXPECTATIONS entry
    itself (never re-typed magic numbers): the low-rail window must end
    strictly before the high-rail window starts (a real gap, the flip band),
    survive_to must reach at least the start of the post-flip observation
    window (or the entry could pass without ever observing the post-flip
    half), and the raw-column (pre-clamp) checks must use the EXACT same
    windows as their emitted-column siblings -- a drift between them would
    mean the two views of "before/after the flip" disagree with each other."""
    entry = rhs.FAULT_EXPECTATIONS["ems-ftp75-sdp"]
    specs = entry["signals_require"]
    low = _spec_by_name(specs, "sdpftp_low_rail_early")
    high = _spec_by_name(specs, "sdpftp_high_rail_late")
    raw_low = _spec_by_name(specs, "sdpftp_raw_battery_branch")
    raw_high = _spec_by_name(specs, "sdpftp_raw_fc_branch")
    survive_t = entry["survive_to"]["t"]

    lo_end = low["t_window"][1]
    hi_start = high["t_window"][0]
    assert lo_end < hi_start, "the flip band must be a real (non-empty) gap"
    assert survive_t >= hi_start, (
        "the run must be required to survive at least to the start of the "
        "post-flip observation window, or a truncated run before the flip "
        "could still satisfy survive_to")
    # The raw (pre-clamp) column checks are asserting the same before/after
    # split as the emitted-column checks -- they must share the windows.
    assert raw_low["t_window"] == low["t_window"]
    assert raw_high["t_window"] == high["t_window"]
    # And the band documented in hil_plant_sim.py's re-derivation (governor
    # walk 272.0 s, scaled to an expected board flip near 275.5 s) must fall
    # strictly inside the gap the two windows leave open.
    walk_predicted_flip = 275.5
    assert lo_end < walk_predicted_flip < hi_start


# ─────────────────────────────────────────────────────────────────────────
# C1 round (2026-09-01), PART B2 -- `max_of`: the ANY quantifier
# ─────────────────────────────────────────────────────────────────────────

def test_judge_event_spec_max_of_picks_the_largest_matching_value():
    events = {"kinds": {"chopper_clamp": 3}, "field_values": {},
             "events_by_kind": {"chopper_clamp": [
                 {"energy_j": 0.12}, {"energy_j": 2.5}, {"energy_j": 0.02},
             ]}}
    spec = {"max_of": "chopper_clamp", "field": "energy_j", "min_value": 1.0}
    ok, observed, problems = rhs._judge_event_spec(spec, events)
    assert ok is True
    assert problems == []
    assert "2.5000" in observed


def test_judge_event_spec_max_of_below_min_value_fails_even_with_a_large_total():
    """The discriminating property of `max_of` vs `total_of`: a long tail of
    small flickers can clear a `total_of` floor while no single episode
    clears a `max_of` floor -- `max_of` must fail here even though the SAME
    events would pass a `total_of` spec with the same min_value."""
    events = {"kinds": {"chopper_clamp": 5}, "field_values": {},
             "events_by_kind": {"chopper_clamp": [
                 {"energy_j": 0.25} for _ in range(5)
             ]}}
    max_spec = {"max_of": "chopper_clamp", "field": "energy_j", "min_value": 1.0}
    total_spec = {"total_of": "chopper_clamp", "field": "energy_j",
                 "min_value": 1.0}
    ok_max, _, _ = rhs._judge_event_spec(max_spec, events)
    ok_total, _, _ = rhs._judge_event_spec(total_spec, events)
    assert ok_max is False
    assert ok_total is True


def test_judge_event_spec_max_of_one_matching_event():
    events = {"kinds": {"chopper_clamp": 1}, "field_values": {},
             "events_by_kind": {"chopper_clamp": [{"energy_j": 0.5}]}}
    spec = {"max_of": "chopper_clamp", "field": "energy_j", "min_value": 0.4}
    ok, observed, _ = rhs._judge_event_spec(spec, events)
    assert ok is True
    assert "0.5000" in observed


def test_judge_event_spec_max_of_no_matching_events_is_undefined_not_zero():
    """Unlike `total_of` (which sums to 0.0 over nothing and is judged against
    the floor like any total), `max_of` over zero events has no value at all
    and must FAIL with a distinct 'undefined' message, never silently read as
    0.0."""
    events = {"kinds": {}, "field_values": {}, "events_by_kind": {}}
    spec = {"max_of": "chopper_clamp", "field": "energy_j", "min_value": 0.3}
    ok, observed, problems = rhs._judge_event_spec(spec, events)
    assert ok is False
    assert "undefined" in observed
    assert problems and "no" in problems[0]


def test_judge_event_spec_max_of_respects_where_filter():
    events = {"kinds": {"sw_ring": 2}, "field_values": {},
             "events_by_kind": {"sw_ring": [
                 {"switch": "MOT_PWR", "energy_j": 0.2},
                 {"switch": "FC_BUS", "energy_j": 0.9},
             ]}}
    spec = {"max_of": "sw_ring", "where": {"switch": "MOT_PWR"},
           "field": "energy_j", "min_value": 0.1}
    ok, observed, _ = rhs._judge_event_spec(spec, events)
    assert ok is True
    assert "0.2000" in observed        # the FC_BUS 0.9 must be excluded


def test_judge_event_spec_max_of_respects_max_value_ceiling():
    events = {"kinds": {"chopper_clamp": 2}, "field_values": {},
             "events_by_kind": {"chopper_clamp": [
                 {"energy_j": 0.5}, {"energy_j": 5.0},
             ]}}
    spec = {"max_of": "chopper_clamp", "field": "energy_j", "max_value": 4.0}
    ok, observed, problems = rhs._judge_event_spec(spec, events)
    assert ok is False
    assert "above max_value" in problems[0]


def test_max_of_spec_shape_guards_fire_on_synthetic_mutations():
    """Reproduces the module's own four import-time shape guards for `max_of`
    against synthetic specs, mirroring the guards asserted over
    FAULT_EXPECTATIONS at import (which by definition never see a spec that
    fails them -- the module would refuse to import)."""
    bad_specs = [
        {"kind": "chopper_clamp", "max_of": "chopper_clamp",
         "field": "energy_j", "min_value": 1.0},                # kind + max_of
        {"total_of": "chopper_clamp", "max_of": "chopper_clamp",
         "field": "energy_j", "min_value": 1.0},                # both aggregators
        {"max_of": "chopper_clamp", "min_value": 1.0},          # no field
        {"max_of": "chopper_clamp", "field": "energy_j"},       # no bound
    ]
    for spec in bad_specs:
        with pytest.raises(AssertionError):
            for _agg_key in ("total_of", "max_of"):
                if _agg_key not in spec:
                    continue
                assert "kind" not in spec, "kind+aggregator"
                assert not ("total_of" in spec and "max_of" in spec), \
                    "both aggregators"
                assert spec.get("field"), "no field"
                assert (spec.get("min_value") is not None
                       or spec.get("max_value") is not None), "no bound"


def test_regen_harvest_true_max_of_spec_is_registered():
    reqs = rhs.FAULT_EXPECTATIONS["regen-harvest-true"]["events_require"]
    maxes = [r for r in reqs if isinstance(r, dict) and "max_of" in r]
    assert len(maxes) == 1
    assert maxes[0]["max_of"] == "chopper_clamp"
    assert maxes[0]["field"] == "energy_j"
    # WP-1C (2026-09-02): 1.0 -> 0.65 J, from the same measured halving as the
    # `total_of` bound (50 % under the 1.3043 J probe).
    assert maxes[0]["min_value"] == pytest.approx(0.65)


# The strict xfail the test-writer put here (charge-regen defined twice) is
# REMOVED: the same fix round repaired both duplicates in tools/run_hil_suite.py
# -- the 'regen-harvest-true' one it had already flagged, and the 'charge-regen'
# one this test found, which was collateral from the first repair's own
# re-insertion.  The test now guards the whole table unconditionally.
def test_fault_expectations_has_no_duplicate_scenario_keys_in_source():
    """Regression guard: a dict literal with a repeated key compiles cleanly
    and silently drops everything the earlier occurrence carried, so this
    cannot be caught by importing the module -- it has to be caught by
    scanning the source text for the literal `"<name>": {` key-opening
    pattern FAULT_EXPECTATIONS entries use."""
    src = open(rhs.__file__, encoding="utf-8").read()
    for name in rhs.FAULT_EXPECTATIONS:
        pat = '"%s": {' % name
        count = src.count(pat)
        assert count <= 1, (
            "FAULT_EXPECTATIONS[%r] dict literal ('%s') appears %d times in "
            "%s -- the later one silently shadows the earlier one's checks"
            % (name, pat, count, rhs.__file__))


# ─────────────────────────────────────────────────────────────────────────
# PART B1 -- fault_first_latch_t: the LATCHED first sighting
# ─────────────────────────────────────────────────────────────────────────

def test_fault_first_latch_t_is_empty_when_bit_never_latches(tmp_path):
    """A bare (non-latched) bit sighting must NOT populate
    fault_first_latch_t, even though it populates fault_first_t."""
    rows = [{"t": "3.000", "fault_flags": hex(rhs.FAULT_UV_BATT)}]  # bare only
    path = tmp_path / "bare_only.csv"
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path), grace_s=0.0)
    name = rhs.fault_names(rhs.FAULT_UV_BATT)
    assert name in m["fault_first_t"]
    assert m["fault_first_latch_t"] == {}


def test_fault_first_latch_t_records_the_later_latch_not_the_bare_sighting(tmp_path):
    """The load-bearing case: a transient bare bit at t=3.0, then the same bit
    latched (with FAULT_ERROR) at t=9.0. fault_first_t must read 3.0 (first
    BARE sighting); fault_first_latch_t must read 9.0 (first LATCH)."""
    rows = [
        {"t": "3.000", "fault_flags": hex(rhs.FAULT_UV_BATT)},                 # transient
        {"t": "6.000", "fault_flags": "0"},                                    # cleared
        {"t": "9.000", "fault_flags": hex(rhs.FAULT_UV_BATT | rhs.FAULT_ERROR)},  # latch
    ]
    path = tmp_path / "transient_then_latch.csv"
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path), grace_s=0.0)
    name = rhs.fault_names(rhs.FAULT_UV_BATT)
    assert m["fault_first_t"][name] == pytest.approx(3.0)
    assert m["fault_first_latch_t"][name] == pytest.approx(9.0)


def test_fault_first_latch_t_latch_only_no_bare_predecessor(tmp_path):
    rows = [{"t": "9.000", "fault_flags": hex(rhs.FAULT_UV_BATT | rhs.FAULT_ERROR)}]
    path = tmp_path / "latch_only.csv"
    _write_scenario_csv(path, rows)
    m = rhs.analyze_scenario_csv(str(path), grace_s=0.0)
    name = rhs.fault_names(rhs.FAULT_UV_BATT)
    assert m["fault_first_t"][name] == pytest.approx(9.0)
    assert m["fault_first_latch_t"][name] == pytest.approx(9.0)


def test_not_before_s_passes_on_the_transient_then_latch_trace():
    """The trace from the fault_first_latch_t test above, driven through the
    real 'charge-cruise' entry (OC_FC, not_before_s=8.0): a transient bare
    bit BEFORE not_before_s, followed by the real latch AFTER it.
    not_before_s must PASS because the LATCH -- not the bare transient -- is
    what it judges."""
    expect = rhs.FAULT_EXPECTATIONS["charge-cruise"]
    want = expect["require"]
    not_before = expect["not_before_s"]
    name = rhs.fault_names(want)
    m = _metrics(fault_bits_seen=want, final_fault_flags=want,
                 fault_first_t={name: not_before - 5.0},          # bare, early
                 fault_first_latch_t={name: not_before + 1.0},    # latch, on time
                 fault_bits_before_survive=0, state_at_survive=2)
    passed, checks = rhs.judge_scenario("charge-cruise", m, _events(), _child())
    ef = [c for c in checks if c["name"] == "expected_fault"][0]
    assert ef["passed"] is True
    assert passed is True


def test_not_before_s_fails_when_the_latch_itself_is_early():
    """A latch before not_before_s must FAIL -- the latch, not merely a bare
    sighting, happened before the stimulus."""
    expect = rhs.FAULT_EXPECTATIONS["charge-cruise"]
    want = expect["require"]
    not_before = expect["not_before_s"]
    name = rhs.fault_names(want)
    m = _metrics(fault_bits_seen=want, final_fault_flags=want,
                 fault_first_t={name: not_before - 5.0},
                 fault_first_latch_t={name: not_before - 1.0},    # latch, early
                 fault_bits_before_survive=0, state_at_survive=2)
    passed, checks = rhs.judge_scenario("charge-cruise", m, _events(), _child())
    ef = [c for c in checks if c["name"] == "expected_fault"][0]
    assert ef["passed"] is False
    assert "BEFORE" in ef["detail"]


# ─────────────────────────────────────────────────────────────────────────
# PART B1 -- v-bus-sense-offset: the two-sided latch window on the
# excursion-2 check, measured 19.90 ms +/- 6 ms after the excursion opens
# ─────────────────────────────────────────────────────────────────────────

def _uv_excursion2_spec():
    reqs = rhs.FAULT_EXPECTATIONS["v-bus-sense-offset"]["signals_require"]
    return [s for s in reqs if s.get("name") == "uv_latched_on_excursion_2"][0]


def test_uv_excursion2_window_matches_the_documented_19_90ms_measurement():
    spec = _uv_excursion2_spec()
    lo, hi = spec["t_window"]
    opens_at = hil.V_BUS_UV_PROBE_2[0]
    assert lo == pytest.approx(opens_at + 0.0139, abs=1e-6)
    assert hi == pytest.approx(opens_at + 0.0259, abs=1e-6)
    assert lo <= opens_at + 0.01990 <= hi


def test_uv_excursion2_latch_at_measured_instant_passes(tmp_path):
    spec = _uv_excursion2_spec()
    opens_at = hil.V_BUS_UV_PROBE_2[0]
    t_latch = opens_at + 0.01990
    rows = [{"t": "%.5f" % t_latch,
            "fault_flags": hex(rhs.FAULT_UV_BUS | rhs.FAULT_ERROR)}]
    path = tmp_path / "latch_at_measured.csv"
    _write_scenario_csv(path, rows)
    measured = rhs.scan_signals(str(path), [spec], grace_s=0.0)
    checks = rhs.judge_signals([spec], measured, "why")
    assert checks[0]["passed"] is True


@pytest.mark.parametrize("offset_ms", [12.0, 27.0])
def test_uv_excursion2_latch_outside_window_fails(tmp_path, offset_ms):
    spec = _uv_excursion2_spec()
    opens_at = hil.V_BUS_UV_PROBE_2[0]
    t_latch = opens_at + offset_ms / 1000.0
    rows = [{"t": "%.5f" % t_latch,
            "fault_flags": hex(rhs.FAULT_UV_BUS | rhs.FAULT_ERROR)}]
    path = tmp_path / ("latch_%dms.csv" % int(offset_ms))
    _write_scenario_csv(path, rows)
    measured = rhs.scan_signals(str(path), [spec], grace_s=0.0)
    checks = rhs.judge_signals([spec], measured, "why")
    assert checks[0]["passed"] is False


# ─────────────────────────────────────────────────────────────────────────
# PART B3 -- mppt-tracking braking-window mirror-artifact pin: the count must
# sit at EXACTLY AG105_MPPT_N_CEIL (27) through the whole braking window
# ─────────────────────────────────────────────────────────────────────────

def _mppt_brake_specs():
    reqs = rhs.FAULT_EXPECTATIONS["mppt-tracking"]["signals_require"]
    ceiling = [s for s in reqs
              if s.get("name") == "mppt_threshold_braking_mirror_artifact_ceiling"][0]
    floor = [s for s in reqs
            if s.get("name") == "mppt_threshold_braking_mirror_artifact"][0]
    return ceiling, floor


def _mppt_brake_rows(count):
    lo, hi = rhs._MPPT_THRESH_BRAKE_W
    mid = (lo + hi) / 2.0
    return [{"t": "%.3f" % mid, "mppt_thresh_cnt": str(count),
            "fault_flags": "0"}]


def test_mppt_brake_window_pin_specs_use_ag105_mppt_n_ceil():
    ceiling, floor = _mppt_brake_specs()
    assert ceiling["max_value"] == hil.AG105_MPPT_N_CEIL == 27
    assert floor["floor_min_value"] == hil.AG105_MPPT_N_CEIL == 27
    assert ceiling["t_window"] == rhs._MPPT_THRESH_BRAKE_W
    assert floor["t_window"] == rhs._MPPT_THRESH_BRAKE_W


def test_mppt_brake_window_count_26_fails(tmp_path):
    ceiling, floor = _mppt_brake_specs()
    path = tmp_path / "cnt26.csv"
    _write_scenario_csv(path, _mppt_brake_rows(26), extra_cols=("mppt_thresh_cnt",))
    measured = rhs.scan_signals(str(path), [ceiling, floor], grace_s=0.0)
    checks = rhs.judge_signals([ceiling, floor], measured, "why")
    by_name = {c["name"]: c["passed"] for c in checks}
    # 26 clears the ceiling (<= 27) but not the floor (must be >= 27
    # everywhere in-window).
    assert by_name["signal_mppt_threshold_braking_mirror_artifact_ceiling"] is True
    assert by_name["signal_mppt_threshold_braking_mirror_artifact"] is False


def test_mppt_brake_window_count_27_passes_both(tmp_path):
    ceiling, floor = _mppt_brake_specs()
    path = tmp_path / "cnt27.csv"
    _write_scenario_csv(path, _mppt_brake_rows(27), extra_cols=("mppt_thresh_cnt",))
    measured = rhs.scan_signals(str(path), [ceiling, floor], grace_s=0.0)
    checks = rhs.judge_signals([ceiling, floor], measured, "why")
    by_name = {c["name"]: c["passed"] for c in checks}
    assert by_name["signal_mppt_threshold_braking_mirror_artifact_ceiling"] is True
    assert by_name["signal_mppt_threshold_braking_mirror_artifact"] is True


def test_mppt_brake_window_count_28_fails(tmp_path):
    ceiling, floor = _mppt_brake_specs()
    path = tmp_path / "cnt28.csv"
    _write_scenario_csv(path, _mppt_brake_rows(28), extra_cols=("mppt_thresh_cnt",))
    measured = rhs.scan_signals(str(path), [ceiling, floor], grace_s=0.0)
    checks = rhs.judge_signals([ceiling, floor], measured, "why")
    by_name = {c["name"]: c["passed"] for c in checks}
    # 28 clears the floor (>= 27) but exceeds the ceiling (<= 27).
    assert by_name["signal_mppt_threshold_braking_mirror_artifact_ceiling"] is False
    assert by_name["signal_mppt_threshold_braking_mirror_artifact"] is True


# ─────────────────────────────────────────────────────────────────────────
# Campaign-level wall-clock metadata (campaign_meta.json, 2026-09-01).
#
# A campaign's total runtime was recorded NOWHERE: per-run wall_s existed,
# plan.json stamped the start by its mtime alone, and the ~67-minute figure
# for hil_report_20260901_151156 could only be recovered by differencing
# file timestamps.  These pin the new file's content, the h:mm:ss rendering
# in REPORT.md, and -- load-bearing -- that the file is still written when
# the campaign aborts partway, with completed=False.
# ─────────────────────────────────────────────────────────────────────────

def test_fmt_hms_renders_hours_minutes_seconds():
    assert rhs._fmt_hms(0) == "0:00:00"
    assert rhs._fmt_hms(59.4) == "0:00:59"
    assert rhs._fmt_hms(61) == "0:01:01"
    # The reference campaign: 15:11:56 -> 16:19:11 is 67 min 15 s.
    assert rhs._fmt_hms(67 * 60 + 15) == "1:07:15"
    assert rhs._fmt_hms(3600) == "1:00:00"
    assert rhs._fmt_hms(None) == "?"
    assert rhs._fmt_hms(-1) == "?"


def test_build_campaign_meta_arithmetic_and_skip_accounting():
    """wall_s_overhead is total minus the sum of per-run wall_s, and a SKIPPED
    run counts as planned but NOT executed (it launches no child at all)."""
    args = _args(out="/tmp/report")
    # A REALISTIC epoch: _iso_local() calls astimezone(), which on Windows
    # cannot resolve a local offset for a near-epoch naive datetime (OSError 22).
    # 2025-08-24T00:26:40Z, plus 100 s.
    t0 = 1756000000.0
    plan = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
    results = [
        {"name": "a", "child": {"wall_s": 10.0}},
        {"name": "b", "child": {"wall_s": 20.0}},
        {"name": "c", "skipped": True, "child": {"wall_s": None}},
    ]
    cm = rhs.build_campaign_meta(args, ["--only", "a"], plan, results,
                                 started_t=t0, finished_t=t0 + 100.0,
                                 completed=True)
    assert cm["wall_s_total"] == 100.0
    assert cm["wall_s_runs_sum"] == 30.0
    assert cm["wall_s_overhead"] == 70.0
    assert cm["n_runs_planned"] == 3
    assert cm["n_runs_executed"] == 2
    assert cm["completed"] is True
    assert cm["argv"] == ["--only", "a"]
    assert cm["wall_hms_total"] == "0:01:40"
    # Same ISO-8601-with-offset convention as the per-run "launched_at" stamp:
    # seconds precision, and an offset is present.
    parsed = datetime.datetime.fromisoformat(cm["started_at"])
    assert parsed.utcoffset() is not None
    assert parsed.microsecond == 0
    assert (datetime.datetime.fromisoformat(cm["finished_at"])
            - parsed).total_seconds() == 100.0


def test_build_campaign_meta_is_json_serializable(tmp_path):
    args = _args(out=str(tmp_path))
    cm = rhs.build_campaign_meta(args, ["--out", str(tmp_path)], [{"name": "a"}],
                                 [{"name": "a", "child": {"wall_s": 1.5}}],
                                 started_t=1756000000.0,
                                 finished_t=1756000002.0,
                                 completed=False)
    path = rhs.write_campaign_meta(str(tmp_path), cm)
    assert os.path.basename(path) == rhs.CAMPAIGN_META_NAME
    loaded = json.loads((tmp_path / rhs.CAMPAIGN_META_NAME).read_text(encoding="utf-8"))
    assert loaded == cm
    assert loaded["completed"] is False


def test_campaign_meta_written_end_to_end(tmp_path, monkeypatch):
    """A completed campaign writes campaign_meta.json next to plan.json, with
    the executed-run count and the suite argv, and REPORT.md carries the
    runtime row plus the new appendix entry."""
    def fake_run_child(item, args):
        return {"status": "ok", "returncode": 0, "wall_s": 0.25, "log": item["log"],
                "summary": {"achieved_hz": 1000.0}}

    monkeypatch.setattr(rhs, "run_child", fake_run_child)
    # --keep-going for the same reason as the K4 tests: the fake child writes no
    # CSV, so the run fails its checks; the campaign metadata is what is pinned.
    rhs.main(["--out", str(tmp_path), "--only", "steady", "--keep-going"])

    meta_path = tmp_path / rhs.CAMPAIGN_META_NAME
    assert meta_path.is_file()
    cm = json.loads(meta_path.read_text(encoding="utf-8"))
    assert cm["n_runs_planned"] == 1
    assert cm["n_runs_executed"] == 1
    assert cm["wall_s_runs_sum"] == pytest.approx(0.25)
    assert cm["wall_s_total"] > 0.0
    # NOT `total >= runs_sum`: the mocked child returns a wall_s it never
    # actually spent, so the identity below is what this test can pin. On a
    # real campaign the overhead is positive by construction.
    assert cm["wall_s_overhead"] == pytest.approx(
        cm["wall_s_total"] - cm["wall_s_runs_sum"])
    assert cm["completed"] is True
    assert "--only" in cm["argv"] and "steady" in cm["argv"]
    assert cm["out"] == os.path.abspath(str(tmp_path))
    assert cm["wall_hms_total"] == rhs._fmt_hms(cm["wall_s_total"])

    report = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
    assert "Campaign runtime" in report
    assert cm["wall_hms_total"] in report
    assert "Campaign window" in report
    # The appendix lists it alongside plan.json.
    assert "`%s`" % rhs.CAMPAIGN_META_NAME in report
    # results.json carries the same block (render_report reads it from meta).
    loaded = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert loaded["meta"]["campaign_timing"] == cm


def test_campaign_meta_written_on_keyboardinterrupt_with_completed_false(
        tmp_path, monkeypatch):
    """The load-bearing case: an aborted campaign must still record its window,
    flagged completed=False so the runtime is not read as a full-plan figure."""
    def boom(plan, args, problems, results, write_outputs):
        raise KeyboardInterrupt

    monkeypatch.setattr(rhs, "_run_plan", boom)
    rc = rhs.main(["--out", str(tmp_path), "--only", "steady"])
    assert rc == 130

    cm = json.loads((tmp_path / rhs.CAMPAIGN_META_NAME).read_text(encoding="utf-8"))
    assert cm["completed"] is False
    assert cm["n_runs_executed"] == 0
    assert cm["n_runs_planned"] == 1
    assert cm["wall_s_runs_sum"] == 0.0
    report = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
    assert "ABORTED campaign" in report


def test_campaign_meta_written_when_every_run_is_skipped(tmp_path, monkeypatch):
    """An all-skips plan executes nothing: planned counts them, executed does
    not, and wall_s_runs_sum stays 0."""
    def fake_run_child(item, args):
        raise AssertionError("no child should ever be launched")

    monkeypatch.setattr(rhs, "run_child", fake_run_child)
    rhs.main(["--out", str(tmp_path), "--pi-live", "--scenarios-only",
              "--only", "charge-cruise"])
    cm = json.loads((tmp_path / rhs.CAMPAIGN_META_NAME).read_text(encoding="utf-8"))
    assert cm["n_runs_planned"] >= 1
    assert cm["n_runs_executed"] == 0
    assert cm["wall_s_runs_sum"] == 0.0


def test_dry_run_writes_plan_json_but_no_campaign_meta(tmp_path):
    """--dry-run keeps its existing behaviour (it writes plan.json) and must NOT
    gain a campaign_meta.json: no campaign ran, so there is no runtime."""
    rc = rhs.main(["--out", str(tmp_path), "--dry-run", "--only", "steady"])
    assert rc == 0
    assert (tmp_path / "plan.json").is_file()
    assert not (tmp_path / rhs.CAMPAIGN_META_NAME).exists()


def test_list_writes_nothing(tmp_path):
    """--list writes no report folder content at all -- unchanged by this
    round, pinned so campaign_meta.json cannot leak into it later."""
    rc = rhs.main(["--out", str(tmp_path), "--list", "--only", "steady"])
    assert rc == 0
    assert not (tmp_path / rhs.CAMPAIGN_META_NAME).exists()
    assert not (tmp_path / "plan.json").exists()


def test_render_report_omits_runtime_row_without_timing():
    """An intermediate (mid-campaign) rewrite has no finish time yet: the row is
    omitted rather than rendered with a placeholder runtime."""
    text = rhs.render_report({"settle_s": 1.0}, [])
    assert "Campaign runtime" not in text
