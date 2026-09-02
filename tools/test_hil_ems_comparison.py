#!/usr/bin/env python3
"""pytest suite for tools/hil_ems_comparison.py -- the cross-strategy EMS
comparison stage.

The module is deliberately importable on the stdlib-only interpreter, so the
grouping, arithmetic and Markdown-rendering tests run there. The collection
and figure tests need numpy and matplotlib and are skipped without them.

Run: cd tools && python -m pytest test_hil_ems_comparison.py -v
"""
import csv
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hil_ems_comparison as ec        # noqa: E402  (stdlib-safe)
import run_hil_suite as suite          # noqa: E402  (stdlib-safe)

try:
    import numpy  # noqa: F401
    import matplotlib
    matplotlib.use("Agg")
    _HAVE_PLOT = True
except ImportError:                     # pragma: no cover - env guard
    _HAVE_PLOT = False

needs_plot = pytest.mark.skipif(not _HAVE_PLOT,
                                reason="needs numpy + matplotlib")


# ─────────────────────────────────────────────────────────────────────────
# Profile grouping
# ─────────────────────────────────────────────────────────────────────────

def test_profile_fingerprint_is_value_based_not_identity():
    a = [(0.0, 0.0), (10.0, 2.5)]
    b = [(0.0, 0.0), (10.0, 2.5)]          # equal value, different object
    c = [(0.0, 0.0), (10.0, 2.6)]
    assert ec.profile_fingerprint(a) == ec.profile_fingerprint(b)
    assert ec.profile_fingerprint(a) != ec.profile_fingerprint(c)
    assert ec.profile_fingerprint(None) is None
    assert ec.profile_fingerprint([]) is None


def test_group_key_pairs_fingerprint_with_duration():
    prof = [(0.0, 0.0), (10.0, 2.5)]
    k1 = ec.group_key({"ems_v_profile": prof, "duration_s": 350.0})
    k2 = ec.group_key({"ems_v_profile": prof, "duration_s": 61.0})
    assert k1[0] == k2[0] and k1 != k2
    assert ec.group_key({"duration_s": 350.0}) is None
    assert ec.group_key(None) is None


def test_ftp75_scenarios_group_together_and_apart_from_the_61s_cycle():
    sim = pytest.importorskip("hil_plant_sim")
    ftp = {ec.group_key(sim.SCENARIOS[n]) for n in
           ("ems-ftp75-5050", "ems-ftp75-socband", "ems-ftp75-sdp",
            "ems-ftp75-dp", "ems-ftp75-mpc")}
    short = {ec.group_key(sim.SCENARIOS[n]) for n in
             ("ems-soc-band", "ems-sdp", "ems-dp-replay", "ems-mpc")}
    assert len(ftp) == 1, "the five FTP-75 legs must share one stimulus group"
    assert len(short) == 1
    assert ftp != short


def test_match_frontier_picks_the_registered_tuple():
    ftp = ec.match_frontier(["ems-ftp75-socband", "ems-ftp75-sdp",
                             "ems-ftp75-dp", "ems-ftp75-mpc"])
    assert ftp["id"] == "ftp75"
    assert ftp["roles"]["reference"] == "ems-ftp75-socband"
    assert ec.match_frontier(["ems-y-b00-v1", "ems-y-b30-v1"]) is None


def test_group_label_falls_back_when_no_frontier_is_registered():
    assert ec.group_label({"label": "340 s EPA FTP-75 drive cycle"},
                          "abc123", 350.0) == "340 s EPA FTP-75 drive cycle"
    assert ec.group_label(None, "abc123", 200.0) == \
        "drive profile abc123 (200 s)"


# ─────────────────────────────────────────────────────────────────────────
# eq-H2 and ratio arithmetic, against hand numbers
# ─────────────────────────────────────────────────────────────────────────

# Campaign C's 61 s frontier record (results.json, ems_frontiers[0]).
REF_H2, REF_DSOC = 0.0120841759, -0.0020499999999999963
CAND_H2, CAND_DSOC = 0.0126188851, -0.0016399999999999748
BND_H2, BND_DSOC = 0.0117950506, -0.0019699999999999163
LAM = 0.41


def test_eq_h2_delegates_to_the_suite_arithmetic():
    assert ec.eq_h2(CAND_H2, CAND_DSOC, REF_DSOC, LAM) == \
        suite.ems_eq_h2(CAND_H2, CAND_DSOC, REF_DSOC, LAM)


def test_score_group_reproduces_the_recorded_frontier_numbers():
    rows = [{"run": "ems-soc-band", "h2_run_g": REF_H2,
             "delta_soc_run": REF_DSOC},
            {"run": "ems-sdp", "h2_run_g": CAND_H2,
             "delta_soc_run": CAND_DSOC},
            {"run": "ems-dp-replay", "h2_run_g": BND_H2,
             "delta_soc_run": BND_DSOC}]
    dsoc_ref, eq_ref, eq_bnd = ec.score_group(
        rows, "ems-soc-band", "ems-dp-replay", LAM)
    by = {r["run"]: r for r in rows}
    assert dsoc_ref == REF_DSOC
    # The reference leg's own eq-H2 is its raw hydrogen, by construction.
    assert eq_ref == pytest.approx(REF_H2, abs=1e-12)
    # Hand numbers from results.json ems_frontiers[0].per_lambda[lambda=0.41].
    assert by["ems-sdp"]["eq_h2_g"] == pytest.approx(0.011618885099999946,
                                                     abs=1e-12)
    assert eq_bnd == pytest.approx(0.011599928648780294, abs=1e-12)
    assert by["ems-sdp"]["vs_reference"] == pytest.approx(0.9614958600528105,
                                                          rel=1e-12)
    assert by["ems-sdp"]["vs_bound"] == pytest.approx(1.0016341868811103,
                                                      rel=1e-12)
    assert by["ems-soc-band"]["vs_reference"] == pytest.approx(1.0, rel=1e-12)


def test_score_group_credits_a_leg_that_ends_higher():
    """A leg that discharged LESS than the reference is credited its surplus
    SoC; a leg that discharged harder is charged for the difference."""
    rows = [{"run": "ref", "h2_run_g": 0.010, "delta_soc_run": -0.002},
            {"run": "shallow", "h2_run_g": 0.010, "delta_soc_run": -0.001},
            {"run": "deep", "h2_run_g": 0.010, "delta_soc_run": -0.003}]
    ec.score_group(rows, "ref", None, 0.41)
    by = {r["run"]: r for r in rows}
    assert by["shallow"]["eq_h2_g"] < by["ref"]["eq_h2_g"]
    assert by["deep"]["eq_h2_g"] > by["ref"]["eq_h2_g"]
    assert by["shallow"]["eq_h2_g"] == pytest.approx(0.010 - 0.001 / 0.41)
    # No bound leg named: the vs-bound column has nothing to divide by.
    assert by["deep"]["vs_bound"] is None


def test_score_group_without_a_reference_prices_soc_absolutely():
    rows = [{"run": "a", "h2_run_g": 0.010, "delta_soc_run": -0.002},
            {"run": "b", "h2_run_g": 0.011, "delta_soc_run": None}]
    dsoc_ref, eq_ref, eq_bnd = ec.score_group(rows, None, None, 0.41)
    assert dsoc_ref == 0.0 and eq_ref is None and eq_bnd is None
    assert rows[0]["eq_h2_g"] == pytest.approx(0.010 + 0.002 / 0.41)
    assert rows[1]["eq_h2_g"] is None
    assert rows[0]["vs_reference"] is None


def test_frontier_verdicts_are_keyed_by_candidate():
    results = {"ems_frontiers": [
        {"id": "ftp75", "verdict": "UNVERIFIED",
         "roles": {"reference": "ems-ftp75-socband",
                   "candidate": "ems-ftp75-sdp",
                   "bound": "ems-ftp75-dp"}},
        {"id": "cycle61", "verdict": "PASS",
         "roles": {"reference": "ems-soc-band", "candidate": "ems-sdp",
                   "bound": "ems-dp-replay"}}]}
    got = ec.frontier_verdicts_for(results, ["ems-ftp75-sdp",
                                             "ems-ftp75-socband"])
    assert set(got) == {"ems-ftp75-sdp"}
    assert got["ems-ftp75-sdp"]["id"] == "ftp75"
    assert ec.frontier_verdicts_for({}, ["ems-sdp"]) == {}


# ─────────────────────────────────────────────────────────────────────────
# Table rendering, including the missing-bound row
# ─────────────────────────────────────────────────────────────────────────

def _group_with_one_missing_bound():
    strategies = [
        {"run": "ems-ftp75-sdp", "folder": "scenario_ems-ftp75-sdp_hifi",
         "strategy": "sdp-v4", "role": "frontier", "h2_run_g": 0.0206247464,
         "delta_soc_run": -0.01506, "h2_dp_g": 0.019004983092761267,
         "pct_deviation": 8.522834770927417,
         "lambda_term": 2.4292131418093685,
         "residual_soc": 1.958734499707404e-06, "converged": True,
         "delta_soc_dp": -0.01506, "matched_dp_status": "ok",
         "matched_dp_notes": ["a carried boundary note"],
         "color": "#2a78d6"},
        {"run": "ems-ftp75-socband",
         "folder": "scenario_ems-ftp75-socband_hifi",
         "strategy": "soc-band", "role": "frontier", "h2_run_g": 0.0423184751,
         "delta_soc_run": -0.00675, "h2_dp_g": None, "pct_deviation": None,
         "lambda_term": None, "residual_soc": None, "converged": None,
         "delta_soc_dp": None, "matched_dp_status": "no_cached_solve",
         "matched_dp_notes": [], "color": "#eb6834"},
    ]
    ec.score_group(strategies, "ems-ftp75-socband", None, 0.41)
    return {"profile_id": "fa7b048b0f95", "duration_s": 350.0,
            "label": "340 s EPA FTP-75 drive cycle", "frontier_id": "ftp75",
            "reference": "ems-ftp75-socband", "bound": "ems-ftp75-dp",
            "lambda_soc_per_g": 0.41, "lambda_band": [0.409, 0.415],
            "dsoc_ref": -0.00675, "eq_h2_reference_g": 0.0423184751,
            "eq_h2_bound_g": None, "strategies": strategies,
            "frontier_verdicts": {}, "figures": {}}


def test_table_renders_a_missing_bound_as_a_dash_and_a_status():
    lines = ec.render_group_markdown(_group_with_one_missing_bound(), 1)
    text = "\n".join(lines)
    row = [ln for ln in lines if ln.startswith("| ems-ftp75-socband |")]
    assert len(row) == 1
    cells = [c.strip() for c in row[0].strip("|").split("|")]
    # h2 DP bound, deviation and lambda_term are all absent for this leg.
    assert cells[5] == "—" and cells[6] == "—" and cells[7] == "—"
    assert cells[8] == "no_cached_solve"
    assert "0.0423185" in row[0]                 # its measured hydrogen is not
    assert "340 s EPA FTP-75 drive cycle" in text


def test_table_renders_a_solved_bound_with_its_residual_and_convergence():
    lines = ec.render_group_markdown(_group_with_one_missing_bound(), 1)
    row = [ln for ln in lines if ln.startswith("| ems-ftp75-sdp |")][0]
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[5] == "0.0190050"
    assert cells[6] == "+8.52 %"
    assert cells[7] == "2.429213"
    assert cells[8] == "+2.0e-06, converged (ok)"


def test_dp_status_cell_flags_a_non_converged_bisection():
    cell = ec._dp_status_cell({"matched_dp_status": "ok",
                               "residual_soc": -3.2e-4, "converged": False})
    assert "NOT converged" in cell and "-3.2e-04" in cell
    assert ec._dp_status_cell({}) == "not computed"


def test_carried_matched_dp_notes_are_deduplicated_into_footnotes():
    g = _group_with_one_missing_bound()
    g["strategies"][1]["matched_dp_notes"] = ["a carried boundary note"]
    text = "\n".join(ec.render_group_markdown(g, 1))
    assert text.count("> a carried boundary note") == 1


def test_commentary_placeholder_is_present_verbatim_and_alone():
    payload = {"report": "hil_report_x", "meta": {},
               "lambda_soc_per_g": 0.41,
               "groups": [_group_with_one_missing_bound()]}
    md = ec.render_markdown(payload)
    assert md.count(ec.COMMENTARY_PLACEHOLDER) == 1
    assert ec.COMMENTARY_PLACEHOLDER == \
        "<!-- COMMENTARY: orchestrator fills this in -->"
    tail = md.split("## Commentary", 1)[1].strip()
    assert tail == ec.COMMENTARY_PLACEHOLDER, \
        "the Commentary section must hold the marker and nothing else"


def test_render_markdown_says_so_when_there_is_nothing_to_compare():
    md = ec.render_markdown({"report": "r", "meta": {}, "groups": []})
    assert "nothing to compare" in md
    assert ec.COMMENTARY_PLACEHOLDER in md


def test_render_markdown_links_both_figures_when_present():
    g = _group_with_one_missing_bound()
    g["figures"] = {"tradeoff": "ems_comparison/ems_tradeoff_x.png",
                    "traces": "ems_comparison/ems_traces_x.png"}
    md = ec.render_markdown({"report": "r", "meta": {}, "groups": [g]})
    assert "![Figure 1.1](ems_comparison/ems_tradeoff_x.png)" in md
    assert "![Figure 1.2](ems_comparison/ems_traces_x.png)" in md
    # Every figure is introduced by a sentence before it appears.
    assert md.index("Figure 1.1 places") < md.index("![Figure 1.1]")


# ─────────────────────────────────────────────────────────────────────────
# End to end on a synthetic two-strategy campaign folder
# ─────────────────────────────────────────────────────────────────────────

HEADER = ["t", "seq", "V_fc", "V_batt", "V_bus", "V_chg", "V_rgn", "I_fc",
          "I_batt", "v_actual", "I_charge", "ag105_status", "state",
          "switch", "aux", "current", "mdac_fc", "mdac_bt", "fault_flags",
          "soc", "cmd_v_sp", "cmd_share_sp", "h2_rate_gps", "h2_cum_g",
          "p_mot_w"]


def _write_run(report_dir, scenario, strategy, h2_final, dsoc, n=60,
               soc0=0.7):
    folder = report_dir / ("scenario_%s_hifi" % scenario)
    folder.mkdir(parents=True, exist_ok=True)
    csv_path = folder / ("hil_scenario_%s_hifi.csv" % scenario)
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for i in range(n):
            frac = i / float(n - 1)
            row = dict.fromkeys(HEADER, "0")
            row["t"] = "%.3f" % (i * 1.0)
            row["seq"] = str(i)
            row["ag105_status"] = "0x00"
            row["soc"] = "%.8f" % (soc0 + frac * dsoc)
            row["h2_cum_g"] = "%.10f" % (frac * h2_final)
            row["h2_rate_gps"] = "0"
            row["p_mot_w"] = "1.0"
            w.writerow([row[c] for c in HEADER])
    meta = {"tool": "run_hil_suite", "scenario": {}, "ems_strategy": strategy,
            "mode": "%s-hifi" % strategy, "status": "completed",
            "config": {"electrical": "hifi", "soc0": soc0,
                       "capacity_ah": 5.0, "duration_s": 61.0}}
    (folder / (csv_path.name + ".meta.json")).write_text(
        json.dumps(meta), encoding="utf-8")
    (folder / "analysis.json").write_text(json.dumps(
        {"kind": "scenario", "name": scenario,
         "folder": "scenario_%s_hifi" % scenario, "ems_strategy": strategy,
         "ems_role": "frontier"}), encoding="utf-8")
    return folder


@pytest.fixture
def tiny_campaign(tmp_path):
    """Two real 61 s-cycle scenarios, so the stimulus group and its frontier
    tuple resolve against the live hil_plant_sim registry."""
    d = tmp_path / "hil_report_20260101_000000"
    d.mkdir()
    _write_run(d, "ems-soc-band", "soc-band", 0.0120841759, -0.00205)
    _write_run(d, "ems-sdp", "sdp-v4", 0.0126188851, -0.00164)
    (d / "results.json").write_text(json.dumps(
        {"meta": {"date": "2026-01-01", "target_fw": 25},
         "results": [],
         "ems_frontiers": [{"id": "cycle61", "verdict": "PASS",
                            "roles": {"reference": "ems-soc-band",
                                      "candidate": "ems-sdp",
                                      "bound": "ems-dp-replay"}}]}),
        encoding="utf-8")
    return d


@needs_plot
def test_end_to_end_writes_markdown_json_and_both_figures(tiny_campaign):
    payload = ec.build_ems_comparison(tiny_campaign, matched_dp="lookup",
                                      log=lambda *a: None)
    assert payload is not None
    assert (tiny_campaign / ec.MARKDOWN_NAME).is_file()
    assert (tiny_campaign / ec.JSON_NAME).is_file()
    assert len(payload["groups"]) == 1
    g = payload["groups"][0]
    assert g["frontier_id"] == "cycle61"
    assert g["reference"] == "ems-soc-band"
    assert {s["run"] for s in g["strategies"]} == {"ems-soc-band", "ems-sdp"}
    for key in ("tradeoff", "traces"):
        rel = g["figures"][key]
        assert rel.startswith(ec.FIGURE_SUBDIR + "/")
        png = tiny_campaign / rel
        assert png.is_file() and png.stat().st_size > 1000


@needs_plot
def test_end_to_end_totals_come_from_the_csv_and_match_the_document(
        tiny_campaign):
    payload = ec.build_ems_comparison(tiny_campaign, matched_dp="off",
                                      log=lambda *a: None)
    by = {s["run"]: s for s in payload["groups"][0]["strategies"]}
    assert by["ems-sdp"]["h2_run_g"] == pytest.approx(0.0126188851, abs=1e-10)
    assert by["ems-sdp"]["delta_soc_run"] == pytest.approx(-0.00164, abs=1e-9)
    assert by["ems-sdp"]["eq_h2_g"] == pytest.approx(0.0116188851, abs=1e-9)
    md = (tiny_campaign / ec.MARKDOWN_NAME).read_text(encoding="utf-8")
    assert "0.0126189" in md and ec.COMMENTARY_PLACEHOLDER in md


@needs_plot
def test_json_payload_carries_no_trace_arrays(tiny_campaign):
    ec.build_ems_comparison(tiny_campaign, matched_dp="off",
                            log=lambda *a: None)
    raw = json.loads((tiny_campaign / ec.JSON_NAME).read_text(
        encoding="utf-8"))
    for g in raw["groups"]:
        for s in g["strategies"]:
            assert "_trace" not in s


@needs_plot
def test_single_run_group_is_not_rendered(tmp_path):
    d = tmp_path / "hil_report_20260101_000001"
    d.mkdir()
    _write_run(d, "ems-sdp", "sdp-v4", 0.012, -0.002)
    (d / "results.json").write_text(json.dumps({"meta": {}, "results": []}),
                                    encoding="utf-8")
    assert ec.build_ems_comparison(d, matched_dp="off",
                                   log=lambda *a: None) is None
    assert not (d / ec.MARKDOWN_NAME).exists()


@needs_plot
def test_figures_are_not_regenerated_without_force(tiny_campaign):
    ec.build_ems_comparison(tiny_campaign, matched_dp="off",
                            log=lambda *a: None)
    pid = json.loads((tiny_campaign / ec.JSON_NAME).read_text(
        encoding="utf-8"))["groups"][0]["profile_id"]
    png = tiny_campaign / ec.FIGURE_SUBDIR / ("ems_tradeoff_%s.png" % pid)
    first = png.stat().st_mtime_ns
    ec.build_ems_comparison(tiny_campaign, matched_dp="off",
                            log=lambda *a: None)
    assert png.stat().st_mtime_ns == first
    ec.build_ems_comparison(tiny_campaign, matched_dp="off", force=True,
                            log=lambda *a: None)
    assert png.stat().st_mtime_ns != first


@needs_plot
def test_decimation_keeps_the_final_sample(tiny_campaign):
    np = pytest.importorskip("numpy")
    t = np.arange(100000, dtype=float)
    y = t * 2.0
    td, yd = ec._decimate(t, y, max_points=500)
    assert td.shape[0] <= 501
    assert td[-1] == t[-1] and yd[-1] == y[-1]


@needs_plot
def test_analysis_pass_renders_the_stage_and_links_it(tiny_campaign):
    hra = pytest.importorskip("hil_report_analysis")
    hra.analyze_report(tiny_campaign, log=lambda *a: None)
    summary = (tiny_campaign / "ANALYSIS_SUMMARY.md").read_text(
        encoding="utf-8")
    assert "## EMS strategy comparison" in summary
    assert "(%s)" % ec.MARKDOWN_NAME in summary
    assert (tiny_campaign / ec.MARKDOWN_NAME).is_file()


@needs_plot
def test_analysis_pass_never_solves(tiny_campaign, monkeypatch):
    """A routine tool pass must not turn into a tens-of-minutes DP solve."""
    hra = pytest.importorskip("hil_report_analysis")
    seen = []
    real = ec.collect_group_data

    def spy(report_dir, **kw):
        seen.append(kw.get("matched_dp"))
        return real(report_dir, **kw)

    monkeypatch.setattr(ec, "collect_group_data", spy)
    hra.analyze_report(tiny_campaign, log=lambda *a: None)
    assert seen and set(seen) == {"lookup"}


@needs_plot
def test_analysis_pass_with_a_run_subset_skips_the_stage(tiny_campaign):
    hra = pytest.importorskip("hil_report_analysis")
    hra.analyze_report(tiny_campaign, only=["ems-sdp"], log=lambda *a: None)
    assert not (tiny_campaign / ec.MARKDOWN_NAME).exists()
    summary = (tiny_campaign / "ANALYSIS_SUMMARY.md").read_text(
        encoding="utf-8")
    assert "## EMS strategy comparison" not in summary


@needs_plot
def test_a_group_of_pure_stimulus_legs_is_not_ranked(tmp_path):
    """`charge-regen` and `mppt-tracking` share one 45 s profile and each
    declares an EMS strategy, but neither strategy is frontier-eligible: the
    pair is a charger exerciser, not a policy comparison."""
    d = tmp_path / "hil_report_20260101_000002"
    d.mkdir()
    _write_run(d, "charge-regen", "regen-harvest", 0.001, -0.0002)
    _write_run(d, "mppt-tracking", "mppt-harvest", 0.001, -0.0002)
    (d / "results.json").write_text(json.dumps({"meta": {}, "results": []}),
                                    encoding="utf-8")
    assert ec.build_ems_comparison(d, matched_dp="off",
                                   log=lambda *a: None) is None


@needs_plot
def test_a_newly_solved_bound_restales_the_figure(tiny_campaign):
    """A `--matched-dp solve` pass touches analysis.json and not the CSV. The
    figure draws the bound, so analysis.json must count as a figure input."""
    import time
    ec.build_ems_comparison(tiny_campaign, matched_dp="off",
                            log=lambda *a: None)
    pid = json.loads((tiny_campaign / ec.JSON_NAME).read_text(
        encoding="utf-8"))["groups"][0]["profile_id"]
    png = tiny_campaign / ec.FIGURE_SUBDIR / ("ems_tradeoff_%s.png" % pid)
    first = png.stat().st_mtime_ns
    time.sleep(0.01)
    aj = tiny_campaign / "scenario_ems-sdp_hifi" / "analysis.json"
    aj.write_text(aj.read_text(encoding="utf-8"), encoding="utf-8")
    os.utime(aj, None)
    ec.build_ems_comparison(tiny_campaign, matched_dp="off",
                            log=lambda *a: None)
    assert png.stat().st_mtime_ns != first


def test_registry_role_notes_travel_into_the_footnotes():
    g = _group_with_one_missing_bound()
    g["strategies"][0]["strategy_note"] = "ROLE: a POLICY-PARAMETER SWEEP POINT"
    g["strategies"][1]["strategy_note"] = None
    text = "\n".join(ec.render_group_markdown(g, 1))
    assert "> `sdp-v4` ROLE: a POLICY-PARAMETER SWEEP POINT" in text
    assert "must not be ranked as one" in text


def test_role_notes_block_is_absent_when_no_strategy_carries_one():
    text = "\n".join(ec.render_group_markdown(
        _group_with_one_missing_bound(), 1))
    assert "Strategy roles, carried from" not in text


def test_existing_commentary_is_read_back_and_the_placeholder_is_not():
    import tempfile
    from pathlib import Path as _P
    with tempfile.TemporaryDirectory() as d:
        p = _P(d) / "EMS_COMPARISON.md"
        p.write_text("# x\n\n## Commentary\n\n%s\n"
                     % ec.COMMENTARY_PLACEHOLDER, encoding="utf-8")
        assert ec.existing_commentary(p) is None
        p.write_text("# x\n\n## Commentary\n\nThe SDP leg wins by 3.8 %.\n",
                     encoding="utf-8")
        assert ec.existing_commentary(p) == "The SDP leg wins by 3.8 %."
        assert ec.existing_commentary(_P(d) / "absent.md") is None
        p.write_text("# x\n\nno commentary heading here\n", encoding="utf-8")
        assert ec.existing_commentary(p) is None


def test_render_markdown_uses_a_carried_commentary():
    md = ec.render_markdown({"report": "r", "meta": {}, "groups": []},
                            commentary="Hand-written finding.")
    assert "Hand-written finding." in md
    assert ec.COMMENTARY_PLACEHOLDER not in md


@needs_plot
def test_a_hand_written_commentary_survives_a_regenerate(tiny_campaign):
    """The routine analysis pass regenerates the whole document; the one
    hand-written section must not be lost to it."""
    ec.build_ems_comparison(tiny_campaign, matched_dp="off",
                            log=lambda *a: None)
    md_path = tiny_campaign / ec.MARKDOWN_NAME
    md = md_path.read_text(encoding="utf-8")
    md_path.write_text(md.replace(ec.COMMENTARY_PLACEHOLDER,
                                  "The candidate leads the reference by "
                                  "3.85 %."), encoding="utf-8")
    ec.build_ems_comparison(tiny_campaign, matched_dp="off", force=True,
                            log=lambda *a: None)
    after = md_path.read_text(encoding="utf-8")
    assert "The candidate leads the reference by 3.85 %." in after
    assert ec.COMMENTARY_PLACEHOLDER not in after
    assert "Table 1.1" in after           # the generated body still refreshed


@needs_plot
def test_orphaned_figures_are_removed(tiny_campaign):
    """A figure no group claims is deleted, so a grouping change cannot leave
    an undatable PNG behind."""
    ec.build_ems_comparison(tiny_campaign, matched_dp="off",
                            log=lambda *a: None)
    orphan = tiny_campaign / ec.FIGURE_SUBDIR / "ems_tradeoff_deadbeef.png"
    orphan.write_bytes(b"not a real png")
    keep = tiny_campaign / ec.FIGURE_SUBDIR / "notes.txt"
    keep.write_text("unrelated", encoding="utf-8")
    ec.build_ems_comparison(tiny_campaign, matched_dp="off",
                            log=lambda *a: None)
    assert not orphan.exists()
    assert keep.exists(), "only this stage's own PNGs are swept"


# ─────────────────────────────────────────────────────────────────────────
# Missing-bound note collapse
# ─────────────────────────────────────────────────────────────────────────

def _prefill_note(run):
    """A per-run prefill hint shaped like matched_dp_for_run()'s."""
    return ("no stored solve within 1e-05 SoC of the target. Solve exactly "
            "this problem with `python tools/dp_results_db.py prefill "
            "--key-fields @<file>` ... `--scenario %s --soc0 0.7`" % run)


def _group_with_three_missing_bounds():
    physics = "DP demand model has no regen term"
    strategies = [
        {"run": "ems-sdp", "strategy": "sdp-v4", "role": "frontier",
         "h2_run_g": 0.0126, "delta_soc_run": -0.00164, "h2_dp_g": 0.01266,
         "pct_deviation": -0.35, "lambda_term": 3.12,
         "residual_soc": 4.1e-07, "converged": True, "delta_soc_dp": -0.00164,
         "matched_dp_status": "ok",
         "matched_dp_notes": [physics], "color": "#2a78d6"},
        {"run": "ems-mpc", "strategy": "mpc-det", "role": "frontier",
         "h2_run_g": 0.0103, "delta_soc_run": -0.00258, "h2_dp_g": None,
         "pct_deviation": None, "lambda_term": None, "residual_soc": None,
         "converged": None, "delta_soc_dp": None,
         "matched_dp_status": "no_cached_solve",
         "matched_dp_notes": [physics, _prefill_note("ems-mpc")],
         "color": "#eb6834"},
        {"run": "ems-mpc-sto", "strategy": "mpc-sto", "role": "demonstration",
         "h2_run_g": 0.0093, "delta_soc_run": -0.00300, "h2_dp_g": None,
         "pct_deviation": None, "lambda_term": None, "residual_soc": None,
         "converged": None, "delta_soc_dp": None,
         "matched_dp_status": "no_cached_solve",
         "matched_dp_notes": [physics, _prefill_note("ems-mpc-sto")],
         "color": "#1baf7a"},
        {"run": "ems-soc-band", "strategy": "soc-band", "role": "frontier",
         "h2_run_g": 0.0121, "delta_soc_run": -0.00205, "h2_dp_g": None,
         "pct_deviation": None, "lambda_term": None, "residual_soc": None,
         "converged": None, "delta_soc_dp": None,
         "matched_dp_status": "no_cached_solve",
         "matched_dp_notes": [physics, _prefill_note("ems-soc-band")],
         "color": "#4a3aa7"},
    ]
    ec.score_group(strategies, "ems-soc-band", "ems-sdp", 0.41)
    return {"profile_id": "0fb191aa5ddf", "duration_s": 61.0,
            "label": "61 s synthetic cycle", "frontier_id": "cycle61",
            "reference": "ems-soc-band", "bound": "ems-sdp",
            "lambda_soc_per_g": 0.41, "lambda_band": [0.409, 0.415],
            "dsoc_ref": -0.00205, "eq_h2_reference_g": 0.0121,
            "eq_h2_bound_g": None, "strategies": strategies,
            "frontier_verdicts": {}, "figures": {}}


def test_missing_bounds_collapse_to_one_line_naming_every_leg():
    g = _group_with_three_missing_bounds()
    text = "\n".join(ec.render_group_markdown(g, 2))
    line = ec.bound_gap_line(g)
    assert line == ("No matched-DP bound is stored for: ems-mpc, "
                    "ems-mpc-sto, ems-soc-band (solve with "
                    "`hil_ems_comparison.py --matched-dp solve "
                    "--matched-dp-allow-long`).")
    assert text.count(line) == 1
    # The three per-run prefill hints are gone, not repeated once per leg.
    assert ec.NO_CACHED_SOLVE_NOTE_PREFIX not in text
    assert "dp_results_db.py prefill" not in text
    # ...and the physics boundary survives exactly once.
    assert text.count("> DP demand model has no regen term") == 1


def test_no_gap_line_when_every_leg_carries_a_bound():
    g = _group_with_three_missing_bounds()
    for s in g["strategies"]:
        s["matched_dp_status"] = "ok"
        s["matched_dp_notes"] = ["DP demand model has no regen term"]
    assert ec.bound_gap_line(g) is None
    text = "\n".join(ec.render_group_markdown(g, 2))
    assert "No matched-DP bound is stored for" not in text
    assert text.count("> DP demand model has no regen term") == 1


def test_distinct_physics_notes_are_all_kept():
    g = _group_with_three_missing_bounds()
    g["strategies"][0]["matched_dp_notes"] = ["first boundary",
                                              "second boundary"]
    g["strategies"][1]["matched_dp_notes"] = ["first boundary",
                                              _prefill_note("ems-mpc")]
    text = "\n".join(ec.render_group_markdown(g, 2))
    assert text.count("> first boundary") == 1
    assert text.count("> second boundary") == 1


def test_a_group_whose_only_notes_were_prefill_hints_drops_the_header():
    g = _group_with_three_missing_bounds()
    for s in g["strategies"]:
        s["matched_dp_notes"] = (
            [] if s["matched_dp_status"] == "ok"
            else [_prefill_note(s["run"])])
    text = "\n".join(ec.render_group_markdown(g, 2))
    assert "Boundaries carried from" not in text
    assert "No matched-DP bound is stored for" in text
