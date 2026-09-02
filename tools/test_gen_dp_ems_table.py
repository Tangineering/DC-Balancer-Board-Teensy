#!/usr/bin/env python3
"""pytest suite for tools/gen_dp_ems_table.py -- the offline DP-optimal EMS
setpoint-table generator.

INTERPRETER: gen_dp_ems_table.py imports numpy at module scope (it is offline
tooling, not part of the 1 kHz simulator loop), so this file can only run
under an interpreter that has numpy -- the repo's `.venv_hil` is deliberately
stdlib-only and does NOT.  Following tools/test_figures.py's precedent for a
numpy-dependent test file, this module SKIPS CLEANLY (does not error/collect
at all) when numpy is unavailable, via `pytest.importorskip("numpy")` at
import time -- so `.venv_hil/Scripts/python.exe -m pytest tools/` still
collects this file without failing, it just reports it skipped.

Run:
    C:/Users/ricky/miniforge3/python.exe -m pytest tools/test_gen_dp_ems_table.py -v

Every test in this file uses DELIBERATELY COARSE parameters (--stage-dt 1.0,
--soc-step 5e-5, --n-share 5, --match-terminal-soc none) so the DP solve
finishes in well under a second -- these are NOT the parameters the shipped
table was generated with (see tools/dp_tables/dp_ems_table_ems-dp-replay.csv's
own header for that), they exist only to exercise the CODE PATHS cheaply.
Nothing here asserts a specific hydrogen or SoC number from a coarse solve.
"""
import hashlib
import os
import re
import sys

import pytest

np = pytest.importorskip("numpy")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gen_dp_ems_table as gen  # noqa: E402
import hil_plant_sim as hil     # noqa: E402


# Shared coarse argv fragment (fast, deterministic, no --match-terminal-soc
# bisection loop) used by most tests below.  --out/--force are appended by
# each test as needed.
_COARSE_ARGV = ["--scenario", "ems-soc-band", "--stage-dt", "1.0",
                "--soc-step", "5e-5", "--n-share", "5",
                "--match-terminal-soc", "none"]


# ─────────────────────────────────────────────────────────────────────────
# (s) determinism: two runs, same inputs, byte-identical output
# ─────────────────────────────────────────────────────────────────────────

def test_two_runs_same_inputs_produce_byte_identical_tables(tmp_path):
    out1 = str(tmp_path / "a.csv")
    out2 = str(tmp_path / "b.csv")
    rc1 = gen.main(_COARSE_ARGV + ["--out", out1])
    rc2 = gen.main(_COARSE_ARGV + ["--out", out2])
    assert rc1 == 0 and rc2 == 0
    with open(out1, "rb") as fh:
        a = fh.read()
    with open(out2, "rb") as fh:
        b = fh.read()
    assert a == b
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()


def test_dry_run_writes_nothing_and_returns_success(tmp_path):
    out = str(tmp_path / "never_written.csv")
    rc = gen.main(_COARSE_ARGV + ["--out", out, "--dry-run"])
    assert rc == 0
    assert not os.path.exists(out)


def test_refuses_to_overwrite_without_force(tmp_path, capsys):
    out = str(tmp_path / "a.csv")
    rc1 = gen.main(_COARSE_ARGV + ["--out", out])
    assert rc1 == 0
    capsys.readouterr()  # drain the first run's stdout
    rc2 = gen.main(_COARSE_ARGV + ["--out", out])
    assert rc2 == 2
    err = capsys.readouterr().err
    assert "REFUSING to overwrite" in err


def test_force_allows_overwrite(tmp_path):
    out = str(tmp_path / "a.csv")
    assert gen.main(_COARSE_ARGV + ["--out", out]) == 0
    assert gen.main(_COARSE_ARGV + ["--out", out, "--force"]) == 0


def test_unknown_scenario_is_a_clean_cli_refusal():
    with pytest.raises(SystemExit):
        gen.main(["--scenario", "not-a-real-scenario", "--dry-run"])


# ─────────────────────────────────────────────────────────────────────────
# item 2 (2026-08-31 reconciliation): match_target_soc / match_residual_soc /
# match_converged, and the M3 hard-fail without --allow-unmatched
# ─────────────────────────────────────────────────────────────────────────

# --match-tol 1e-15 is a tolerance no discrete control/SoC grid can reach --
# a cheap, reliable way to force a non-converged bisection (measured:
# residual ~2.4e-6 SoC after all 30 iterations, well above 1e-15).
_UNMATCHED_ARGV = ["--scenario", "ems-soc-band", "--stage-dt", "1.0",
                   "--soc-step", "5e-5", "--n-share", "5",
                   "--match-tol", "1e-15"]


def test_render_table_records_match_fields_as_placeholders_under_match_none(tmp_path):
    """--match-terminal-soc none (as _COARSE_ARGV uses) is not a matched
    comparison at all -- the three fields must be the 'none'/'n/a'
    placeholders, not stale numbers from a previous solve."""
    out = str(tmp_path / "a.csv")
    assert gen.main(_COARSE_ARGV + ["--out", out]) == 0
    with open(out, encoding="utf-8") as fh:
        text = fh.read()
    assert "# match_target_soc: none" in text
    assert "# match_residual_soc: none" in text
    assert "# match_converged: n/a" in text


def test_render_table_records_real_match_fields_under_heuristic_matching(tmp_path):
    """With the default --match-terminal-soc heuristic, the three fields must
    be REAL numbers, not the none/n/a placeholders -- and match_converged
    must be a real yes/no verdict."""
    out = str(tmp_path / "a.csv")
    # n-share 11 (vs the coarser 5 elsewhere in this file) actually converges
    # within the default --match-tol 2e-6 -- measured residual +1.19e-7.
    argv = ["--scenario", "ems-soc-band", "--stage-dt", "1.0",
            "--soc-step", "5e-5", "--n-share", "11", "--out", out]
    assert gen.main(argv) == 0
    with open(out, encoding="utf-8") as fh:
        text = fh.read()
    assert "# match_target_soc: none" not in text
    assert "# match_residual_soc: none" not in text
    assert "# match_converged: n/a" not in text
    assert ("# match_converged: yes" in text) or ("# match_converged: no" in text)


def test_unmatched_bisection_hard_fails_without_allow_unmatched(tmp_path, capsys):
    """M3 (review, 2026-08-31): a table whose matched-terminal-SoC bisection
    did NOT converge within --match-tol must REFUSE to write by default --
    its hydrogen figure is not comparable to the causal reference at the
    matched SoC, which is the table's whole purpose."""
    out = str(tmp_path / "unmatched.csv")
    rc = gen.main(_UNMATCHED_ARGV + ["--out", out])
    assert rc == 2
    assert not os.path.exists(out)
    err = capsys.readouterr().err
    assert "did NOT" in err
    assert "--allow-unmatched" in err


def test_unmatched_bisection_succeeds_with_allow_unmatched_and_records_no(tmp_path):
    out = str(tmp_path / "unmatched.csv")
    rc = gen.main(_UNMATCHED_ARGV + ["--out", out, "--allow-unmatched"])
    assert rc == 0
    assert os.path.exists(out)
    with open(out, encoding="utf-8") as fh:
        text = fh.read()
    assert "# match_converged: no" in text
    assert "# match_target_soc: none" not in text
    assert "# match_residual_soc: none" not in text


def test_unmatched_dry_run_reports_freely_without_allow_unmatched(tmp_path, capsys):
    """--dry-run must report an unmatched solve without needing
    --allow-unmatched at all -- "investigating a hard case costs nothing"
    per the M3 module comment."""
    rc = gen.main(_UNMATCHED_ARGV + ["--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry-run" in out


# ─────────────────────────────────────────────────────────────────────────
# (t) infeasible-forward raise path -- cheaply constructed, no full solve
# ─────────────────────────────────────────────────────────────────────────

def test_forward_pass_raises_dpinfeasible_when_initial_soc_outside_window():
    """The cheapest possible construction: soc0 is simply not inside
    [soc_grid[0], soc_grid[-1]] -- forward_pass() must raise DpInfeasible on
    the very first iteration rather than silently clamping or crashing with
    an unrelated error."""
    soc_grid = np.array([0.50, 0.51, 0.52])
    times = np.array([0.0])
    p_dem = np.array([10.0])
    v_bus = np.array([16.0])
    chg_ok = np.array([False])
    shares = np.array([0.5])
    Uopt = np.zeros((3, 1), dtype=np.int16)
    with pytest.raises(gen.DpInfeasible, match="left the SoC window"):
        gen.forward_pass(0.90, times, p_dem, v_bus, chg_ok, 0.1, 18000.0, 0.8,
                         shares, soc_grid, Uopt)


def test_forward_pass_raises_dpinfeasible_when_policy_and_mask_disagree():
    """The second D3 raise site: the stored policy selects the CHARGE control
    (index == m) at a stage the charge mask forbids -- a defensive check for
    "the backward pass and the mask disagree", constructed directly by
    forcing Uopt to point at the charge index while chg_ok is False."""
    soc_grid = np.array([0.50, 0.51, 0.52])
    times = np.array([0.0])
    p_dem = np.array([10.0])
    v_bus = np.array([16.0])
    chg_ok = np.array([False])           # charging forbidden at this stage
    shares = np.array([0.5])             # m = 1, so charge index is Uopt == 1
    Uopt = np.full((3, 1), 1, dtype=np.int16)
    with pytest.raises(gen.DpInfeasible, match="selected CHARGE"):
        gen.forward_pass(0.51, times, p_dem, v_bus, chg_ok, 0.1, 18000.0, 0.8,
                         shares, soc_grid, Uopt)


def test_forward_pass_raises_dpinfeasible_when_policy_picks_fc_overcurrent_share():
    """The third D3 raise site: the stored policy selects a split whose FC
    current exceeds LIMIT_I_FC_MAX_A at the demand actually reached -- a
    defensive check the backward pass's own feasibility mask should have
    already excluded, constructed directly by handing forward_pass() a
    demand large enough that share=1.0 (unrealistically wide, but this
    function does not itself enforce the DP_SHARE_MIN/MAX band) is an
    overcurrent share on a low bus voltage."""
    soc_grid = np.array([0.50, 0.51, 0.52])
    times = np.array([0.0])
    p_dem = np.array([100.0])            # a large demand at
    v_bus = np.array([10.0])             # a low bus voltage -> big FC current
    chg_ok = np.array([False])
    shares = np.array([1.0])             # ALL of the demand onto the FC channel
    Uopt = np.zeros((3, 1), dtype=np.int16)
    with pytest.raises(gen.DpInfeasible, match="overcurrent share"):
        gen.forward_pass(0.51, times, p_dem, v_bus, chg_ok, 0.1, 18000.0, 0.8,
                         shares, soc_grid, Uopt)


def test_end_to_end_infinite_cost_to_go_is_a_clean_dpinfeasible(tmp_path):
    """End-to-end (through main()): an SoC grid too narrow to reach ANY
    feasible terminal state must surface as a clean DpInfeasible, not a
    numpy warning or a silently wrong table.  Forced by an absurdly tight
    --soc-step * a single-point-ish grid via monkeypatching the window
    padding to (near) zero would require reaching into module internals;
    instead this drives the same failure the module's own docstring calls
    out (D3) via an unreachable charge ceiling that forces EVERY control at
    every stage to violate the FC current limit."""
    out = str(tmp_path / "infeasible.csv")
    argv = ["--scenario", "ems-soc-band", "--stage-dt", "1.0",
            "--soc-step", "5e-5", "--n-share", "5",
            "--match-terminal-soc", "none", "--out", out]
    # Sanity: the coarse defaults DO solve cleanly (rules out a false positive
    # below being caused by the coarse parameters themselves rather than the
    # deliberately-broken one).
    assert gen.main(list(argv)) == 0
    os.remove(out)

    # gen_dp_ems_table.py has no CLI knob for LIMIT_I_FC_MAX_A -- reach into
    # the module constant directly and restore it in a finally, the same
    # pattern test_hil_plant_sim.py uses for its module-constant patches.
    orig = gen.LIMIT_I_FC_MAX_A
    try:
        gen.LIMIT_I_FC_MAX_A = 1.0e-9    # unreachable: every share is infeasible
        with pytest.raises(gen.DpInfeasible, match="infinite cost-to-go"):
            gen.main(list(argv) + ["--force"])
    finally:
        gen.LIMIT_I_FC_MAX_A = orig


# ─────────────────────────────────────────────────────────────────────────
# Fingerprint / bind_scenario cross-check against hil_plant_sim.py
# (belt-and-braces: the generator and the strategy import the SAME function,
# but pin here too that the generator's own render/parse round-trip agrees.)
# ─────────────────────────────────────────────────────────────────────────

def test_generated_table_fingerprint_round_trips_through_load_dp_table(tmp_path):
    out = str(tmp_path / "a.csv")
    assert gen.main(_COARSE_ARGV + ["--out", out]) == 0
    meta, _times, _shares, _goals = hil.load_dp_table(out)
    want = hil.dp_profile_fingerprint("ems-soc-band", hil.SCENARIOS["ems-soc-band"])
    assert meta["profile_fingerprint"] == want


def test_generated_table_is_loadable_and_bindable_by_dp_replay_strategy(tmp_path):
    """The full consumer-side path: a table this generator writes must be
    something DpReplayStrategy.bind_scenario() actually accepts (same
    scenario it was generated for).

    The table is generated at BOTH of the plant's own eras, not at
    _COARSE_ARGV's defaults: `bind_scenario()` refuses an era mismatch before
    it even checks the fingerprint, and an old-era table against the current
    plant is exactly the mismatch those guards exist for (they are pinned
    consumer-side, in test_hil_plant_sim.py).

      * `--eta-chg` at `sim.ETA_CHG`  -> block (0), the charger era
      * `--loss-map plant`            -> block (0b), the demand-model era

    ⚠️ NEITHER FLAG DEFAULTS TO THE PLANT'S ERA, and that asymmetry is the
    point of the second half of this test: a plain `gen.main(_COARSE_ARGV)`
    produces a table this consumer REFUSES. That is deliberate (an old-era
    regeneration must not bind silently) and it is the generator-side view of
    the guard."""
    out_dir = str(tmp_path)
    name = "dp_ems_table_ems-soc-band.csv"
    assert gen.main(_COARSE_ARGV
                    + ["--eta-chg", repr(float(hil.ETA_CHG)),
                       "--loss-map", "plant",
                       "--out", os.path.join(out_dir, name)]) == 0
    strategy = hil.DpReplayStrategy(table_dir=out_dir)
    strategy.bind_scenario("ems-soc-band", hil.SCENARIOS["ems-soc-band"])
    assert strategy.times
    out = strategy(30.0, {"t": 30.0, "v_profile": 1.5})
    assert 0.0 <= out["power_share_setpoint"] <= 1.0

    # THE OTHER HALF: the DEFAULT flags produce a table the consumer refuses,
    # naming the demand-model era and the flag that fixes it.
    stale_dir = os.path.join(out_dir, "stale")
    os.makedirs(stale_dir, exist_ok=True)
    assert gen.main(_COARSE_ARGV
                    + ["--eta-chg", repr(float(hil.ETA_CHG)),
                       "--out", os.path.join(stale_dir, name)]) == 0
    stale = hil.DpReplayStrategy(table_dir=stale_dir)
    with pytest.raises(ValueError) as exc:
        stale.bind_scenario("ems-soc-band", hil.SCENARIOS["ems-soc-band"])
    assert "--loss-map plant" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────────
# 2026-08-31 wave 2: scenario_drain_a() generic aux_preload_a agreement, and
# --run-exit's per-scenario resolution (main() reads args.run_exit=None as
# "resolve from the scenario's ems_run_exit_s").
# ─────────────────────────────────────────────────────────────────────────

def test_scenario_drain_a_generic_branch_calls_scenario_aux_preload_a(monkeypatch):
    """A scenario outside the bespoke ('ems-soc-band', 'ems-dp-replay') pair
    goes through the GENERIC branch, which is now I_AUX_A +
    hil.scenario_aux_preload_a(scenario, t) -- the exact function
    apply_scenario()'s own fall-through branch calls, so the DP solves
    against the load the run will actually see.

    A fabricated scenario (not a real SCENARIOS entry) isolates the generic
    branch from any bespoke one that might otherwise claim the name."""
    fake = "test-generic-scenario-2026-08-31"
    monkeypatch.setitem(hil.SCENARIOS, fake, {"aux_preload_a": 0.75})
    for t in (0.0, hil.AUX_PRELOAD_START_S - 1.0, hil.AUX_PRELOAD_START_S,
             hil.AUX_PRELOAD_START_S + hil.SOC_LOAD_RAMP_S / 2.0,
             hil.AUX_PRELOAD_START_S + hil.SOC_LOAD_RAMP_S + 5.0):
        want = hil.I_AUX_A + hil.scenario_aux_preload_a(fake, t)
        assert gen.scenario_drain_a(fake, t) == pytest.approx(want), t


def test_scenario_drain_a_generic_branch_zero_when_no_aux_preload_declared():
    """A scenario with NO aux_preload_a key (every scenario that predates the
    2026-08-31 key, and mppt-tracking/charge-to-full which deliberately take
    the generic branch without declaring one) drains exactly I_AUX_A -- the
    generic term is 0.0 for it, matching the pre-key behaviour byte for
    byte."""
    for name in ("mppt-tracking", "charge-to-full"):
        assert "aux_preload_a" not in hil.SCENARIOS[name]
        for t in (0.0, 10.0, 100.0):
            assert gen.scenario_drain_a(name, t) == pytest.approx(hil.I_AUX_A)


def test_scenario_drain_a_ems_soc_band_bespoke_branch_unaffected():
    """ems-soc-band/ems-dp-replay keep their OWN hardcoded ramp arithmetic --
    the generic aux_preload_a mechanism must not silently graft itself onto
    the bespoke branch (neither scenario declares the key, so this is also a
    belt-and-braces check that the branch selection is still by name)."""
    assert "aux_preload_a" not in hil.SCENARIOS["ems-soc-band"]
    for t in (0.0, hil.SOC_BAND_DRAIN_START_S, hil.SOC_BAND_DRAIN_START_S + 5.0,
             hil.SOC_BAND_DRAIN_END_S + 5.0):
        ramp_in = max(0.0, min(1.0, (t - hil.SOC_BAND_DRAIN_START_S) / hil.SOC_LOAD_RAMP_S))
        ramp_out = max(0.0, min(1.0, (t - hil.SOC_BAND_DRAIN_END_S) / hil.SOC_LOAD_RAMP_S))
        want = hil.I_AUX_A + hil.SOC_BAND_DRAIN_LOAD_A * (ramp_in - ramp_out)
        assert gen.scenario_drain_a("ems-soc-band", t) == pytest.approx(want), t


def test_run_exit_default_resolves_from_scenario_ems_run_exit_s(tmp_path):
    """--run-exit omitted: main() resolves it from the SCENARIO's own
    `ems_run_exit_s` when it declares one (mppt-tracking: 43.0, ==
    EMS_REGEN_RUN_EXIT_S) rather than falling back to the bare
    SOC_BAND_RUN_EXIT_S constant -- the resolution this generator must agree
    with is DpReplayStrategy's M2 header check on the consumer side."""
    out = str(tmp_path / "mppt.csv")
    assert gen.main(["--scenario", "mppt-tracking", "--stage-dt", "1.0",
                     "--soc-step", "5e-5", "--n-share", "5",
                     "--match-terminal-soc", "none", "--out", out]) == 0
    text = open(out, encoding="utf-8").read()
    assert ("# run_exit_s: %r" % float(hil.SCENARIOS["mppt-tracking"]["ems_run_exit_s"])) in text
    assert "# run_exit_s: 43.0" in text


def test_run_exit_default_falls_back_to_model_constant_when_scenario_declares_none():
    """A scenario declaring no `ems_run_exit_s` (ems-soc-band, unaffected by
    this round) still resolves to the bare SOC_BAND_RUN_EXIT_S constant --
    the pre-2026-08-31 behaviour, byte for byte."""
    assert hil.SCENARIOS["ems-soc-band"].get("ems_run_exit_s") is None
    out = "run_exit_fallback_tmp.csv"
    try:
        assert gen.main(_COARSE_ARGV + ["--out", out, "--force"]) == 0
        text = open(out, encoding="utf-8").read()
        assert ("# run_exit_s: %r" % float(hil.SOC_BAND_RUN_EXIT_S)) in text
    finally:
        if os.path.exists(out):
            os.remove(out)


def test_run_exit_explicit_flag_overrides_scenario_default(tmp_path):
    """An explicit --run-exit still wins over the scenario's own
    `ems_run_exit_s` -- the None-default only supplies a value when the
    operator did not name one."""
    out = str(tmp_path / "mppt_override.csv")
    assert gen.main(["--scenario", "mppt-tracking", "--stage-dt", "1.0",
                     "--soc-step", "5e-5", "--n-share", "5",
                     "--match-terminal-soc", "none", "--run-exit", "20.0",
                     "--out", out]) == 0
    text = open(out, encoding="utf-8").read()
    assert "# run_exit_s: 20.0" in text


# ─────────────────────────────────────────────────────────────────────────
# 2026-09-01 matched-DP round (Stage 2 test-writer): library-extraction
# equivalence, prepare_problem argument validation, scenario_drain_a's
# aux_preload_a override, and the committed table's byte/header fidelity.
# ─────────────────────────────────────────────────────────────────────────

def test_prepare_problem_and_solve_unmatched_reproduce_main_dry_run(capsys):
    """Extraction equivalence (floor item 1): main()'s --dry-run path and a
    direct prepare_problem()+solve_unmatched() call on the SAME arguments
    must land on the same h2/soc totals -- main() now IS this library call
    plus argparse/printing around it, so a divergence would mean the
    extraction changed behaviour."""
    rc = gen.main(list(_COARSE_ARGV) + ["--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    m_h2 = re.search(r"h2 physical\s+([0-9.eE+-]+) g", out)
    m_soc = re.search(r"SoC 0\.700000 -> ([0-9.eE+-]+)", out)
    assert m_h2 and m_soc, out
    h2_expected = float(m_h2.group(1))
    soc_final_expected = float(m_soc.group(1))

    meta = hil.SCENARIOS["ems-soc-band"]
    problem = gen.prepare_problem(
        "ems-soc-band", meta, soc0=0.7, capacity_ah=gen.BATT_CAPACITY_AH,
        stage_dt=1.0, n_share=5, soc_step=5e-5,
        run_exit=float(hil.SOC_BAND_RUN_EXIT_S), charger_accounting="physical")
    solved = gen.solve_unmatched(problem, gen.DP_LAMBDA_TERM_G_PER_SOC)
    assert solved.h2_g == pytest.approx(h2_expected, rel=1e-6)
    assert solved.soc_final == pytest.approx(soc_final_expected, rel=1e-6)


def test_solve_matched_reports_closest_visited_point_when_bracket_exits(tmp_path):
    """(floor item 2) With an unreachable --match-tol, solve_matched() must
    still exit cleanly on the bracket-collapse test, mark converged False,
    and report a residual/soc_final PAIR that are mutually consistent -- the
    returned trajectory is the closest point the bisection actually visited,
    not a stale one."""
    meta = hil.SCENARIOS["ems-soc-band"]
    problem = gen.prepare_problem(
        "ems-soc-band", meta, soc0=0.7, capacity_ah=gen.BATT_CAPACITY_AH,
        stage_dt=1.0, n_share=5, soc_step=5e-5,
        run_exit=float(hil.SOC_BAND_RUN_EXIT_S), charger_accounting="physical")
    target = 0.7 - 0.01
    solved = gen.solve_matched(problem, target_soc=target, match_tol=1e-15)
    assert solved.converged is False
    assert solved.residual_soc is not None
    assert abs(solved.residual_soc) > 1e-15
    # Consistency: the reported residual is exactly the chosen trajectory's
    # terminal SoC minus the target -- i.e. the closest VISITED point, not an
    # unrelated number.
    assert solved.residual_soc == pytest.approx(solved.soc_final - target,
                                                 abs=1e-12)
    assert 1 <= solved.n_solves <= gen.DP_LAMBDA_TERM_BISECT_ITERS


def test_solve_matched_converges_and_reports_true_within_tolerance():
    """The positive case of item 2: a generous --match-tol converges, and
    converged/residual agree (|residual| <= match_tol)."""
    meta = hil.SCENARIOS["ems-soc-band"]
    problem = gen.prepare_problem(
        "ems-soc-band", meta, soc0=0.7, capacity_ah=gen.BATT_CAPACITY_AH,
        stage_dt=1.0, n_share=11, soc_step=5e-5,
        run_exit=float(hil.SOC_BAND_RUN_EXIT_S), charger_accounting="physical")
    href = gen.heuristic_reference(problem)
    solved = gen.solve_matched(problem, target_soc=href["soc_final"],
                                match_tol=2e-6)
    assert solved.converged is True
    assert abs(solved.residual_soc) <= 2e-6


# ── item 3: prepare_problem raises ValueError, main() reports argparse errors

@pytest.mark.parametrize("kwargs,match", [
    ({"n_share": 1}, "n_share"),
    ({"soc_step": 0.0}, "soc_step"),
    ({"soc_step": -1e-5}, "soc_step"),
    ({"stage_dt": 0.0}, "stage_dt"),
    ({"stage_dt": -1.0}, "stage_dt"),
    ({"capacity_ah": 0.0}, "capacity_ah"),
    ({"capacity_ah": -5.0}, "capacity_ah"),
    ({"soc0": 0.0}, "soc0"),
    ({"soc0": 1.0}, "soc0"),
    ({"soc0": 1.5}, "soc0"),
    ({"soc0": -0.1}, "soc0"),
])
def test_prepare_problem_raises_valueerror_not_systemexit(kwargs, match):
    """(floor item 3) A library caller of prepare_problem() gets a plain
    ValueError -- never argparse's SystemExit -- for every one of the
    documented bad-argument cases."""
    meta = hil.SCENARIOS["ems-soc-band"]
    base = dict(soc0=0.7, capacity_ah=gen.BATT_CAPACITY_AH, stage_dt=1.0,
                n_share=5, soc_step=5e-5,
                run_exit=float(hil.SOC_BAND_RUN_EXIT_S),
                charger_accounting="physical")
    base.update(kwargs)
    with pytest.raises(ValueError, match=match):
        gen.prepare_problem("ems-soc-band", meta, **base)


def test_prepare_problem_raises_valueerror_for_bad_charger_accounting():
    meta = hil.SCENARIOS["ems-soc-band"]
    with pytest.raises(ValueError, match="charger_accounting"):
        gen.prepare_problem("ems-soc-band", meta, soc0=0.7,
                            capacity_ah=gen.BATT_CAPACITY_AH, stage_dt=1.0,
                            n_share=5, soc_step=5e-5,
                            run_exit=float(hil.SOC_BAND_RUN_EXIT_S),
                            charger_accounting="not-a-real-mode")


def test_prepare_problem_raises_valueerror_when_share_grid_crosses_cut_band(
        monkeypatch):
    """The share control grid crossing/touching the firmware's share-cut band
    [0.15, 0.85] must be refused -- exercised by monkeypatching the module's
    own DP_SHARE_MIN/MAX constants outward past the band, since the real
    constants are always safely inside it by construction."""
    monkeypatch.setattr(gen, "DP_SHARE_MIN", 0.05)
    monkeypatch.setattr(gen, "DP_SHARE_MAX", 0.95)
    meta = hil.SCENARIOS["ems-soc-band"]
    with pytest.raises(ValueError, match="share-cut band"):
        gen.prepare_problem("ems-soc-band", meta, soc0=0.7,
                            capacity_ah=gen.BATT_CAPACITY_AH, stage_dt=1.0,
                            n_share=5, soc_step=5e-5,
                            run_exit=float(hil.SOC_BAND_RUN_EXIT_S),
                            charger_accounting="physical")


def test_main_still_reports_bad_soc0_as_an_argparse_error(capsys):
    """main() must convert prepare_problem()'s ValueError back into
    ap.error() -- a clean argparse exit code 2, not an uncaught ValueError
    traceback."""
    with pytest.raises(SystemExit) as excinfo:
        gen.main(list(_COARSE_ARGV) + ["--soc0", "1.5", "--dry-run"])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "soc0" in err


# ── items 4/5: scenario_drain_a's ems-sdp alias and aux_preload_a override

def test_scenario_drain_a_ems_sdp_matches_ems_soc_band():
    """(floor item 4) `ems-sdp` was the coordinator-routed defect: it must
    drain EXACTLY like `ems-soc-band` at every t, both scenarios named in
    SOC_BAND_DRAIN_SCENARIOS."""
    for t in (0.0, hil.SOC_BAND_DRAIN_START_S, hil.SOC_BAND_DRAIN_START_S + 5.0,
             hil.SOC_BAND_DRAIN_END_S + 5.0):
        assert gen.scenario_drain_a("ems-sdp", t) == \
            pytest.approx(gen.scenario_drain_a("ems-soc-band", t))


def test_soc_band_drain_scenarios_matches_apply_scenario_source():
    """The other half of item 4: gen_dp_ems_table.SOC_BAND_DRAIN_SCENARIOS
    must be the exact tuple apply_scenario() branches on in hil_plant_sim.py
    -- a source-text regex assertion, since the two are independently
    maintained lists (by design: the generator cannot import the simulator's
    branch condition, only mirror it)."""
    src_path = os.path.join(os.path.dirname(hil.__file__), "hil_plant_sim.py")
    with open(src_path, encoding="utf-8") as fh:
        src = fh.read()
    # The branch was hoisted onto a NAMED tuple (SOC_BAND_DRAIN_SCENARIO_NAMES)
    # when the alpha legs were added, so the assertion follows it there: the
    # branch must READ that name, and this generator's three scenarios must
    # still stand at the HEAD of that tuple, in order.
    #
    # SUBSET, NOT EQUALITY, and deliberately: the simulator's tuple has grown
    # members this generator does not mirror (`+ SDP_ALPHA_SCENARIOS`, and the
    # MPC legs) and hil_plant_sim.py documents why at the definition - no DP
    # table is solved for them.  The invariant that matters to THIS file is the
    # one-directional one: every scenario the generator models with the drain
    # load must be one the simulator actually applies it to.
    assert re.search(r'elif scenario in SOC_BAND_DRAIN_SCENARIO_NAMES:',
                     src) is not None, \
        "apply_scenario()'s SOC_BAND_DRAIN_SCENARIOS branch text has moved " \
        "or been retuned -- update gen_dp_ems_table.SOC_BAND_DRAIN_SCENARIOS " \
        "in lockstep"
    # The membership half is taken against the imported tuple rather than a
    # second source regex: the literal has grown twice (the alpha legs, then
    # the MPC legs) and a regex pinned to its exact shape fails on additions
    # that do not touch this invariant at all.
    missing = [s for s in gen.SOC_BAND_DRAIN_SCENARIOS
               if s not in hil.SOC_BAND_DRAIN_SCENARIO_NAMES]
    assert not missing, \
        "gen_dp_ems_table.SOC_BAND_DRAIN_SCENARIOS models the drain load for " \
        "%s, which apply_scenario() does NOT apply it to -- the DP would " \
        "solve against a demand the run never sees" % missing
    # The three the generator has always carried are still there, so this is
    # not vacuous if the generator's own list is ever emptied.
    for name in ("ems-soc-band", "ems-dp-replay", "ems-sdp"):
        assert name in gen.SOC_BAND_DRAIN_SCENARIOS


def test_scenario_drain_a_aux_preload_override_matches_y_registry_value():
    """(floor item 5) An explicit aux_preload_a override must reproduce
    EXACTLY what the registry path computes for a scenario that declares that
    same value as its own `aux_preload_a` (the Y-scenario convention,
    Y_AUX_LOAD_A) -- the override is a stand-in for "the load the board
    actually saw", not a different formula."""
    fake = "test-override-parity-scenario"
    import hil_plant_sim as hilmod
    hilmod.SCENARIOS[fake] = {"aux_preload_a": hilmod.Y_AUX_LOAD_A}
    try:
        for t in (0.0, hilmod.AUX_PRELOAD_START_S,
                 hilmod.AUX_PRELOAD_START_S + hilmod.SOC_LOAD_RAMP_S / 2.0,
                 hilmod.AUX_PRELOAD_START_S + hilmod.SOC_LOAD_RAMP_S + 10.0):
            via_registry = gen.scenario_drain_a(fake, t)
            via_override = gen.scenario_drain_a(fake, t, hilmod.Y_AUX_LOAD_A)
            assert via_override == pytest.approx(via_registry), t
    finally:
        del hilmod.SCENARIOS[fake]


def test_scenario_drain_a_aux_preload_override_none_is_bit_identical_to_prechange():
    """None must be the EXACT pre-change path (registry lookup), not merely
    close to it -- covered already by the existing generic-branch tests, but
    pinned here explicitly at the call-site level: omitting the 4th argument
    and passing aux_preload_a=None must be indistinguishable."""
    for name in ("mppt-tracking", "charge-to-full"):
        for t in (0.0, 10.0, 50.0):
            assert gen.scenario_drain_a(name, t) == \
                gen.scenario_drain_a(name, t, None)


def test_scenario_drain_a_aux_preload_override_falsy_zero_disables_ramp():
    """0.0 (falsy but not None) must take the explicit-zero branch, not the
    registry lookup -- distinct from the None case above."""
    fake = "test-override-falsy-zero-scenario"
    import hil_plant_sim as hilmod
    hilmod.SCENARIOS[fake] = {"aux_preload_a": 0.75}
    try:
        t = hilmod.AUX_PRELOAD_START_S + hilmod.SOC_LOAD_RAMP_S
        # Registry path would ramp the full 0.75 A in by here.
        assert gen.scenario_drain_a(fake, t) > gen.scenario_drain_a(fake, t, 0.0)
        assert gen.scenario_drain_a(fake, t, 0.0) == pytest.approx(hilmod.I_AUX_A)
    finally:
        del hilmod.SCENARIOS[fake]


# ── item 6: committed table fidelity

def test_committed_dp_replay_table_h2_matches_solve_unmatched_at_recorded_lambda():
    """(floor item 6, fallback form) Re-derive the solved lambda_term and h2
    figure from the committed table's OWN header, then reproduce the h2 total
    with a direct solve_unmatched() call at that lambda -- a full bisecting
    regeneration of this 610-stage/41-share table is measured at tens of
    seconds and is skipped here in favour of the header-fidelity check the
    floor explicitly allows."""
    table_path = os.path.join(gen.DP_TABLE_DIR, "dp_ems_table_ems-dp-replay.csv")
    if not os.path.exists(table_path):
        pytest.skip("committed table not present in this checkout")
    with open(table_path, encoding="utf-8") as fh:
        text = fh.read()

    def _num(pattern):
        m = re.search(pattern, text)
        assert m, pattern
        return float(m.group(1))

    lam_term = _num(r"# lambda_term_g_per_soc: ([0-9.eE+-]+)")
    h2_expected = _num(r"# h2_g_physical: ([0-9.eE+-]+)")
    soc0 = _num(r"# soc0: ([0-9.eE+-]+)")
    capacity_ah = _num(r"# capacity_ah: ([0-9.eE+-]+)")
    stage_dt = _num(r"# stage_dt_s: ([0-9.eE+-]+)")
    run_exit = _num(r"# run_exit_s: ([0-9.eE+-]+)")
    n_share = int(_num(r"# n_share: ([0-9]+)"))
    soc_step = _num(r"soc_grid: [0-9]+ points, [0-9.eE+-]+ \.\. [0-9.eE+-]+, "
                    r"step ([0-9.eE+-]+)")

    # THE ERA LINES ARE PART OF THE PROBLEM (2026-09-02). A table records its
    # charger era and its demand-model era in the header, and reproducing its
    # h2 total means solving in BOTH of them. Absent lines mean the old eras,
    # which is what makes this parse the right shape.
    m = re.search(r"# eta_chg: ([0-9.eE+-]+)", text)
    eta_chg = float(m.group(1)) if m else None
    m = re.search(r"# loss_map: (\S+)", text)
    loss_map = hil.loss_map_from_canonical(m.group(1)) if m else None

    meta = hil.SCENARIOS["ems-dp-replay"]
    problem = gen.prepare_problem(
        "ems-dp-replay", meta, soc0=soc0, capacity_ah=capacity_ah,
        stage_dt=stage_dt, n_share=n_share, soc_step=soc_step,
        run_exit=run_exit, charger_accounting="physical",
        eta_chg=eta_chg, loss_map=loss_map)
    solved = gen.solve_unmatched(problem, lam_term)
    assert solved.h2_g == pytest.approx(h2_expected, rel=1e-6)


# ==========================================================================
# ADDED BY THE STAGE-1 IMPLEMENTER (2026-09-01), NOT THE TEST-WRITER.
# Minimal pin for the aux_preload_a header line (MED-4, preload round).
# ==========================================================================


def test_render_table_records_the_aux_preload_a_header_for_every_committed_table():
    """The stimulus era must be READABLE, not only hashed.

    Before this line the auxiliary preload a table was solved against was
    recoverable only by recomputing profile_fingerprint, so a preload retune
    elsewhere left two tables distinguishable by a digest alone. The line is
    documentation: it is inside the fingerprint already, so it guards nothing
    and must not move a data row.
    """
    import hil_plant_sim as sim
    for name in ("ems-dp-replay", "ems-ftp75-5050", "ems-ftp75-dp"):
        path = gen.default_table_path(name)
        text = open(path, encoding="utf-8").read()
        header = text.split("t,power_share_setpoint,charge_goal", 1)[0]
        want = (0.0 if name in gen.SOC_BAND_DRAIN_SCENARIOS
                else float(sim.SCENARIOS[name].get("aux_preload_a") or 0.0))
        assert ("# aux_preload_a: %r" % want) in header, name
        # It sits in the tunables block, ahead of charger_accounting.
        assert header.index("# aux_preload_a:") <             header.index("# charger_accounting:"), name
        # And it is genuinely inside the fingerprint, which is what makes it
        # documentation rather than an unguarded input.
        assert "aux_preload_a" in sim.DP_FINGERPRINT_META_KEYS


# ==========================================================================
# 2026-09-01 charger-efficiency round (WP-1B1).  The Ag105 stops being a 1:1
# current-transfer element and becomes an energy-conserving converter, so a
# charge stage's BUS cost changes model.  These tests pin the era switch, the
# byte fidelity of the old era, and the header line.
# ==========================================================================
import charger_power as cp                                       # noqa: E402


def test_charger_power_helper_era_switch_is_the_billing_voltage():
    """The two eras differ in WHICH voltage the charge current is billed at -
    NOT in an efficiency value.  eta None bills the BUS; a float bills the
    PACK, divided by the efficiency.  eta=1.0 is therefore NOT the old era."""
    i, v_bus, v_pack = 0.8, 15.9, 7.86
    assert cp.charger_bus_power_w(i, v_bus, v_pack, None) == v_bus * i
    assert cp.charger_bus_power_w(i, v_bus, v_pack, 0.88) == \
        pytest.approx(v_pack * i / 0.88)
    # eta 1.0 bills the pack voltage, which is a THIRD model - the guard
    # against someone "simplifying" the era switch into a default of 1.0.
    assert cp.charger_bus_power_w(i, v_bus, v_pack, 1.0) != \
        cp.charger_bus_power_w(i, v_bus, v_pack, None)
    # Old-era bus CURRENT is the charge current itself, EXACTLY (1:1
    # transfer), not v_bus*i/v_bus - which can differ by an ulp and moves a
    # committed table's charge mask.
    assert cp.charger_bus_current_a(i, v_bus, v_pack, None) is i
    assert cp.charger_bus_current_a(i, v_bus, v_pack, 0.88) == \
        pytest.approx(v_pack * i / (0.88 * v_bus))
    assert cp.charger_bus_current_a(i, v_bus, v_pack, 0.88) < i


def test_charger_power_resolve_and_validate():
    assert cp.resolve_eta_chg(None) is None
    assert cp.resolve_eta_chg({}) is None                 # missing = old era
    assert cp.resolve_eta_chg({"eta_chg": None}) is None  # explicit null too
    assert cp.resolve_eta_chg({"eta_chg": 0.88}) == 0.88
    assert cp.check_eta_chg(None) is None
    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            cp.check_eta_chg(bad)


def test_step_charge_soc_is_era_invariant_but_hydrogen_is_not():
    """The efficiency sits on the charger's INPUT side, so the pack receives
    the same current in both eras and only the fuel cell's bill moves."""
    args = (0.7, 20.0, 15.9, 0.8, 0.1, 5.0 * 3600.0)
    s_old, h_old, hp_old = gen.step_charge(*args)
    s_new, h_new, hp_new = gen.step_charge(*args, eta_chg=0.88)
    assert s_new == s_old
    assert hp_new == hp_old              # the plant-equivalent omits the charger
    assert h_new < h_old                 # ~7.9 V/0.88 vs 15.9 V per amp
    v_pack = float(gen.pack_charge_voltage(0.7, 0.8))
    want = hil.H2_GFC_DC_GAIN_GPS_PER_W * (
        (20.0 + v_pack * 0.8 / 0.88) / hil.ETA_BOOST) * 0.1
    assert h_new == pytest.approx(want, rel=1e-12)


def test_charge_mask_new_era_admits_at_least_as_many_stages():
    """The new era's charger draws LESS bus current, so the single-source FC
    budget binds later and the mask can only grow."""
    meta = hil.SCENARIOS["ems-dp-replay"]
    common = dict(soc0=0.7, capacity_ah=gen.BATT_CAPACITY_AH, stage_dt=0.1,
                  n_share=5, soc_step=5e-5,
                  run_exit=float(hil.SOC_BAND_RUN_EXIT_S),
                  charger_accounting="physical")
    old = gen.prepare_problem("ems-dp-replay", meta, **common)
    new = gen.prepare_problem("ems-dp-replay", meta, eta_chg=0.88, **common)
    assert int(new.chg_ok.sum()) > int(old.chg_ok.sum())
    # Every stage the old mask admits, the new one admits too.
    assert bool((new.chg_ok | old.chg_ok == new.chg_ok).all())


def test_charge_mask_requires_a_pack_voltage_in_the_new_era():
    import numpy as _np
    t = _np.array([30.0])
    with pytest.raises(ValueError, match="v_pack_ref"):
        gen.charge_mask(t, _np.array([20.0]), _np.array([15.9]),
                        _np.array([True]), 0.8, 58.0, 0.88, None)


def test_prepare_problem_rejects_an_impossible_efficiency():
    meta = hil.SCENARIOS["ems-dp-replay"]
    with pytest.raises(ValueError, match="eta_chg"):
        gen.prepare_problem(
            "ems-dp-replay", meta, soc0=0.7,
            capacity_ah=gen.BATT_CAPACITY_AH, stage_dt=1.0, n_share=5,
            soc_step=5e-5, run_exit=float(hil.SOC_BAND_RUN_EXIT_S),
            charger_accounting="physical", eta_chg=1.4)


def test_render_table_emits_the_eta_chg_header_only_in_the_new_era(tmp_path):
    """The line is EMITTED ONLY when an efficiency is in force.  Adding
    `eta_chg: none` to every table would move the bytes of all three committed
    tables without changing a number in them; its ABSENCE is the old era."""
    out_old = str(tmp_path / "old.csv")
    out_new = str(tmp_path / "new.csv")
    base = list(_COARSE_ARGV)
    assert gen.main(base + ["--out", out_old]) == 0
    assert gen.main(base + ["--out", out_new, "--eta-chg", "0.88"]) == 0
    told = open(out_old, encoding="utf-8").read()
    tnew = open(out_new, encoding="utf-8").read()
    assert "# eta_chg:" not in told
    assert "# eta_chg: 0.88" in tnew
    # The reproduction command line carries the term too, and only there.
    assert "--eta-chg 0.88" in tnew.split("t,power_share", 1)[0]
    assert "--eta-chg" not in told.split("t,power_share", 1)[0]


def test_old_era_regeneration_reproduces_the_pre_change_table_byte_for_byte(
        tmp_path):
    """THE INVARIANT of the charger-efficiency round: with no efficiency in
    force, the generator must reproduce the table it produced BEFORE the
    round, exactly.

    The comparison is against a STORED FIXTURE rather than against
    tools/dp_tables/dp_ems_table_ems-dp-replay.csv, because the committed
    tables were regenerated as ETA-ERA tables in this same round (the plant
    now bills the charger at V_pack*i/eta, and a table solved in one era is
    not a bound on a run measured in the other).  The fixture is the
    pre-change file, copied verbatim.

    ONE LINE IS MASKED, and it is not this work package's doing: `eta_chg`
    joined hil_plant_sim.DP_FINGERPRINT_META_KEYS in the same round, so
    `profile_fingerprint` moved for every scenario whatever era it is solved
    in.  Every other header value and every data row is compared byte for
    byte.  Only `ems-dp-replay` is regenerated here: the two FTP-75 tables are
    the same solve at 3500 stages and take tens of minutes each.
    """
    fixture = os.path.join(HERE, "test_fixtures",
                           "dp_ems_table_ems-dp-replay_old_era.csv")
    if not os.path.exists(fixture):
        pytest.skip("old-era fixture not present in this checkout")
    out = str(tmp_path / "regen.csv")
    assert gen.main([
        "--scenario", "ems-dp-replay", "--soc0", "0.7", "--capacity-ah", "5.0",
        "--stage-dt", "0.1", "--lambda-dev", "0.0", "--lambda-term", "1.0",
        "--n-share", "41", "--soc-step", "5e-06",
        "--charger-accounting", "physical", "--run-exit", "58.0",
        "--match-terminal-soc", "heuristic", "--match-tol", "2e-06",
        "--out", out, "--force"]) == 0

    def _mask(text):
        return [ln for ln in text.split("\n")
                if not ln.startswith("# profile_fingerprint:")]

    got = _mask(open(out, encoding="utf-8", newline="").read())
    want = _mask(open(fixture, encoding="utf-8", newline="").read())
    assert got == want
    # The fixture really is the OLD era: no header line, and the h2 total the
    # eta-era table no longer carries for its causal reference.
    assert "# eta_chg:" not in "\n".join(want)


def test_committed_tables_are_eta_era_and_record_it_in_the_header():
    """The committed tables were regenerated at the plant's own efficiency in
    this round, and the header line is the ONLY record of that: a live
    scenario declares no `eta_chg`, so the profile fingerprint hashes the same
    sentinel in both eras and cannot separate them (hil_plant_sim.dp_eta_chg).
    This test is therefore the drift guard the fingerprint is not."""
    import hil_plant_sim as sim
    for name in ("ems-dp-replay", "ems-ftp75-5050", "ems-ftp75-dp"):
        path = gen.default_table_path(name)
        if not os.path.exists(path):
            pytest.skip("committed table %s not present" % name)
        header = open(path, encoding="utf-8").read().split(
            "t,power_share_setpoint,charge_goal", 1)[0]
        assert ("# eta_chg: %r" % float(sim.ETA_CHG)) in header, name
        assert "--eta-chg %r" % float(sim.ETA_CHG) in header, name


def test_plant_eta_chg_equals_the_shared_charger_default():
    """(L4) The generator's --eta-chg default help text, its startup
    cross-check and every committed table's header quote
    `charger_power.ETA_CHG_DEFAULT` and `hil_electrical.ETA_CHG` as if they
    were one number. They are pinned equal consumer-side
    (test_hil_electrical.py); mirrored here because it is THIS file's
    committed-table assertions that silently become vacuous if the two drift."""
    import charger_power as chg
    import hil_plant_sim as sim
    assert float(sim.ETA_CHG) == float(chg.ETA_CHG_DEFAULT)


# ─────────────────────────────────────────────────────────────────────────
# H1 (2026-09-02 review): the BACKWARD PASS must price the charger in the
# same era the forward pass reports.  solve_dp() billed `P + V_bus*chg_a`
# unconditionally, so an eta-era solve CHOSE its policy under the old era's
# 1.764x over-billing and then scored it under the new one.
# ─────────────────────────────────────────────────────────────────────────

def _dp_replay_problem(eta_chg):
    return gen.prepare_problem(
        "ems-dp-replay", hil.SCENARIOS["ems-dp-replay"], soc0=0.7,
        capacity_ah=5.0, stage_dt=0.1, n_share=41, soc_step=5e-6,
        run_exit=58.0, charger_accounting="physical", eta_chg=eta_chg)


def test_backward_pass_prices_the_charger_in_the_solved_era_at_lambda_3_5():
    """At LAMBDA_TERM 3.5 the two eras' policies DIFFER, which is what makes
    this a real regression rather than a restatement.

    Measured (2026-09-02, and these are the review's own figures): the old era
    admits 0 charge stages and burns 0.012521819 g; the eta era admits 157 --
    every stage its mask allows -- and burns 0.015344009 g while ending
    0.000889 SoC higher.  Before the fix the eta-era solve returned the OLD
    era's 0 charge stages, i.e. exactly the old-era policy under a new-era
    score, so `charge_eta > 0` is the assertion that would have failed."""
    import numpy as np
    old = gen.solve_unmatched(_dp_replay_problem(None), lambda_term=3.5)
    new = gen.solve_unmatched(_dp_replay_problem(0.88), lambda_term=3.5)
    charge_old = int(np.sum(old.charge))
    charge_new = int(np.sum(new.charge))
    assert charge_old == 0
    assert charge_new > 0, \
        "the eta-era backward pass is still billing the charger at V_bus"
    # It charges on EVERY admitted stage: at eta 0.88 the charger's bus draw
    # is small enough that the terminal-SoC weight dominates.
    assert charge_new == int(np.sum(_dp_replay_problem(0.88).chg_ok))
    assert new.soc_final > old.soc_final
    assert new.h2_g > old.h2_g
    # Pinned to 9 dp: these two numbers are the whole finding.
    assert round(old.h2_g, 9) == 0.012521819
    assert round(new.h2_g, 9) == 0.015344009


def test_old_era_backward_pass_charge_cost_is_exactly_the_bus_expression():
    """The fix must be a NO-OP in the old era, which is what keeps the three
    committed old-era fixtures byte-identical: charger_bus_power_w() returns
    `V_bus * chg_a` exactly (not a rounded reconstruction of it) when the era
    resolves to None."""
    import charger_power as chg
    v_bus, chg_a, v_pack = 15.93741, 0.8, 7.9241
    assert chg.charger_bus_power_w(chg_a, v_bus, v_pack, None) == v_bus * chg_a


# ═════════════════════════════════════════════════════════════════════════
# THE STATIC-LOSS MAP IN build_demand() (2026-09-02, the DP-bound round)
# ═════════════════════════════════════════════════════════════════════════
_LM_SCEN = "ems-dp-replay"


def _demand(loss_map, scenario=_LM_SCEN, dt=0.1):
    meta = hil.SCENARIOS[scenario]
    n = int(round(float(meta["duration_s"]) / dt))
    times = np.arange(n + 1) * dt
    return gen.build_demand(scenario, meta, times, dt, 0.0,
                            loss_map=loss_map) + (n,)


def test_loss_map_free_demand_is_byte_identical_to_the_pre_round_model():
    """THE OLD-ERA FIXTURE.  `loss_map=None` must reproduce the two-term model
    EXACTLY, including its four Picard iterations, or every band, table and
    stored solve taken before 2026-09-02 silently moves."""
    v, a, p_dem, v_bus, i_total, cruise, n = _demand(None)
    meta = hil.SCENARIOS[_LM_SCEN]
    times = np.arange(n + 1) * 0.1
    i_aux = np.array([gen.scenario_drain_a(_LM_SCEN, t, 0.0) for t in times])
    f_coul = np.where(v > hil.V_STICTION, hil.F_COULOMB,
                      np.where(v < -hil.V_STICTION, -hil.F_COULOMB, 0.0))
    p_mech = np.maximum(0.0, (hil.M_EFF * a + f_coul + hil.B_EFF * v) * v)
    vb = np.full(len(times), hil.V_BUS_DROOP_V0)
    for _ in range(4):
        it = p_mech / (hil.ETA_BOOST * vb) + i_aux
        vb = hil.V_BUS_DROOP_V0 - hil.K_DROOP_BUS_SHARED * it
    it = p_mech / (hil.ETA_BOOST * vb) + i_aux
    assert np.array_equal(v_bus, vb)
    assert np.array_equal(i_total, it)
    assert np.array_equal(p_dem, vb * it)


def test_the_loss_map_demand_satisfies_its_own_fixed_point_at_every_stage():
    """The map is a FIXED POINT, not a formula evaluated once.  Re-substituting
    the returned arrays into the five defining equations must reproduce them,
    which is what makes DP_LOSS_MAP_PICARD_ITERS an implementation detail
    rather than a tuning parameter."""
    lm = hil.plant_loss_map()
    v, a, p_dem, v_bus, i_total, cruise, n = _demand(lm)
    times = np.arange(n + 1) * 0.1
    i_aux = np.array([gen.scenario_drain_a(_LM_SCEN, t, 0.0) for t in times])
    f_coul = np.where(v > hil.V_STICTION, hil.F_COULOMB,
                      np.where(v < -hil.V_STICTION, -hil.F_COULOMB, 0.0))
    p_mech = np.maximum(0.0, (hil.M_EFF * a + f_coul + hil.B_EFF * v) * v)
    g_oth = lm["g_node_other"]
    i_motor = p_mech / (hil.ETA_BOOST * v_bus)
    v_mot = ((v_bus - lm["rt_v_fwd"] - lm["rt_r_on"] * i_motor)
             / (1.0 + lm["rt_r_on"] * g_oth))
    i_par = v_bus * lm["g_node_bus"] + v_mot * g_oth
    k_eff = lm["r_fix"] + lm["k_g"] * lm["g_par"]
    assert np.allclose(i_total, i_motor + i_aux + i_par, atol=1e-12)
    assert np.allclose(v_bus, lm["v0_eff"] - k_eff * i_total, atol=1e-9)
    assert np.allclose(p_dem, v_bus * i_total, atol=1e-12)
    # The parallel term is REAL and is what the pre-round model omitted: it is
    # never zero and never negative on an energized bus.
    assert (i_par > 0).all()


def test_the_loss_map_lowers_the_bus_and_raises_the_source_current():
    """The two defects have OPPOSITE signs on p_dem, and the direction of each
    is the claim.  The realized `--droop design` slope sags the bus about four
    times as far as the old law, and the bleed adds source current the old
    model did not bill."""
    lm = hil.plant_loss_map()
    _, _, p_old, vb_old, it_old, _, n = _demand(None)
    _, _, p_map, vb_map, it_map, _, _ = _demand(lm)
    assert vb_map.mean() < vb_old.mean()
    assert it_map.mean() > it_old.mean()
    # At standstill the whole difference IS the bleed: a 15.9 V bus at
    # 1/30 kOhm plus V-MOT one RT1987 forward drop behind it at 1/60 kOhm is
    # 0.791 mA, and nothing else moves. Under load the map's steeper bus law
    # sags the rail further and the constant-power motor draw rises with it,
    # so the difference GROWS; the ceiling below is that combined term.
    d = it_map - it_old
    assert d.min() == pytest.approx(7.907e-4, abs=2e-6)
    assert d.max() < 1.5e-2
    # On this scenario the two defects nearly cancel in the TOTAL, which is
    # why either fix alone made the measured deviation worse.
    assert abs(p_map[:n].sum() / p_old[:n].sum() - 1.0) < 0.05


def test_the_charge_mask_fc_budget_sees_the_parallel_current():
    """`charge_mask` bills the single-source FC budget `p_dem/v_bus`, which IS
    `i_total` and therefore carries `i_par` once the map is on.  The budget is
    consequently STRICTER in the loss-map era, and this test is what stops a
    later refactor from splitting the two apart."""
    lm = hil.plant_loss_map()
    for loss_map in (None, lm):
        v, a, p_dem, v_bus, i_total, cruise, n = _demand(loss_map)
        assert np.allclose(p_dem / v_bus, i_total, atol=1e-12)


def test_the_firmware_holds_the_parallel_droop_code_constant():
    """THE SEPARABILITY TRIPWIRE, and it is the load-bearing test of this round.

    `p_dem` may not depend on the control or the DP's stage cost is not
    separable and the solve is invalid.  It does not, because the firmware
    trades the SPLIT while holding the PARALLEL droop code fixed:
    `g_par = g_fc*g_bt/(g_fc+g_bt)` reads 0.148922 with sigma 2.79e-05 over
    343 001 Run-state rows of `ems-ftp75-dp` whose individual codes range over
    0.198-0.518 and 0.209-0.598 (campaign 20260902_041414).

    THE MECHANISM, so the assertion below is a statement about the firmware
    and not a coincidence of the trace.  The droop gain map the firmware
    writes is `g_FC = K_DROOP/(RE_MAX*r)` and `g_BT = K_DROOP/(RE_MAX*(1-r))`
    (.ino:10534-10535, mirrored in governor_model._out).  Their parallel
    combination is then

        g_par = g_FC*g_BT/(g_FC+g_BT) = K_DROOP/RE_MAX

    with `r` cancelling EXACTLY.  The parallel code is therefore constant by
    construction, not by tuning, and the only departures are the 12-bit MDAC
    quantization and the [0, 1] clamp at the extreme ratios, which is why the
    trace reads a sigma of 2.79e-05 rather than zero.

    This test asserts the property on the governor's own model rather than on
    an archived CSV, so it runs without the campaign folder.  If a firmware or
    governor change ever lets `g_par` move with the share, the map's
    control-independence is gone and the DP must be RE-DERIVED, not re-fitted.
    """
    gm = pytest.importorskip("governor_model")
    seen = []
    for r in (0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80):
        g_fc = min(1.0, gm.GOV_CONST["K_DROOP"] / (gm._RE_MAX * r))
        g_bt = min(1.0, gm.GOV_CONST["K_DROOP"] / (gm._RE_MAX * (1.0 - r)))
        assert 0.0 < g_fc < 1.0 and 0.0 < g_bt < 1.0, r
        # Through the MDAC words the firmware actually writes, so the 12-bit
        # quantization is inside the number being asserted.
        c_fc = gm.mdac_fraction(gm._mdac_code(g_fc))
        c_bt = gm.mdac_fraction(gm._mdac_code(g_bt))
        seen.append(c_fc * c_bt / (c_fc + c_bt))
    spread = max(seen) - min(seen)
    assert spread < 1e-4, (
        "the parallel droop code moved by %.3e across the share range; the "
        "DP's demand model is no longer control-independent and the loss map "
        "must be re-derived, not re-fitted" % spread)
    # The analytic value K_DROOP/RE_MAX, and the shipped coefficient measured
    # off campaign 20260902_041414, must agree to the quantization.
    analytic = gm.GOV_CONST["K_DROOP"] / gm._RE_MAX
    assert analytic == pytest.approx(hil.DP_DROOP_G_PAR, abs=1e-4)
    assert sum(seen) / len(seen) == pytest.approx(hil.DP_DROOP_G_PAR,
                                                  abs=1e-4)


def test_resolve_loss_map_arg_is_the_one_resolution_of_the_flag():
    assert gen.resolve_loss_map_arg("none") is None
    assert gen.resolve_loss_map_arg(None) is None
    assert gen.resolve_loss_map_arg("plant") == hil.plant_loss_map()
    with pytest.raises(ValueError):
        gen.resolve_loss_map_arg("hifi")


def test_prepare_problem_carries_the_map_and_defaults_to_the_old_era():
    meta = hil.SCENARIOS["ems-soc-band"]
    kw = dict(soc0=0.7, capacity_ah=5.0, stage_dt=1.0, n_share=5,
              soc_step=5e-5, run_exit=58.0, charger_accounting="physical")
    p_old = gen.prepare_problem("ems-soc-band", meta, **kw)
    assert p_old.loss_map is None
    p_map = gen.prepare_problem("ems-soc-band", meta,
                                loss_map=hil.plant_loss_map(), **kw)
    assert p_map.loss_map == hil.plant_loss_map()
    assert p_map.v_bus.mean() < p_old.v_bus.mean()
    # The fingerprint is taken over the LIVE scenario meta in both cases (the
    # `eta_chg` precedent), so the generator and the `dp-replay` consumer
    # agree by construction and the committed tables stay loadable.
    assert p_map.fingerprint == p_old.fingerprint
    with pytest.raises(ValueError):
        gen.prepare_problem("ems-soc-band", meta, loss_map={"v0_eff": 1.0},
                            **kw)


def test_the_committed_tables_record_their_demand_era_in_the_header():
    """A loss-map table must SAY so, and a loss-map-free one must say nothing,
    so the absence of the line is the old era's record."""
    for scen in ("ems-dp-replay", "ems-ftp75-dp", "ems-ftp75-5050"):
        path = os.path.join(HERE, "dp_tables",
                            "dp_ems_table_%s.csv" % scen)
        if not os.path.exists(path):
            pytest.skip("table %s not present in this checkout" % scen)
        head = open(path, encoding="utf-8").read(8000)
        assert "# loss_map: v0_eff=" in head, scen
        assert "--loss-map plant" in head, scen
        assert hil.loss_map_canonical(hil.plant_loss_map()) in head, scen


def test_the_default_flag_regenerates_an_old_era_table_byte_identically(tmp_path):
    """THE OLD-ERA FIXTURE, at file level.

    A table generated with NO `--loss-map` flag and one generated with
    `--loss-map none` must be byte-identical, and NEITHER may carry the
    `# loss_map:` header line or the flag in its reconstructed command: the
    ABSENCE of the line is the pre-2026-09-02 era's record, and emitting it
    unconditionally would have moved the bytes of all three committed tables
    without changing a number in any of them.

    The full-resolution claim was verified once by hand on the shipped
    `ems-dp-replay` table (regenerated with no flag against the pre-round
    committed file: sha256 f7ae4eb2707d4493..., 17 131 bytes, IDENTICAL); this
    coarse version is the one that runs every time."""
    a_path = str(tmp_path / "implicit.csv")
    b_path = str(tmp_path / "explicit.csv")
    assert gen.main(_COARSE_ARGV + ["--out", a_path]) == 0
    assert gen.main(_COARSE_ARGV + ["--loss-map", "none", "--out", b_path]) == 0
    a = open(a_path, "rb").read()
    assert a == open(b_path, "rb").read()
    text = a.decode("utf-8")
    assert "# loss_map:" not in text
    assert "--loss-map" not in text


def test_the_loss_map_flag_changes_the_table_and_says_so(tmp_path):
    old_path = str(tmp_path / "old.csv")
    map_path = str(tmp_path / "map.csv")
    assert gen.main(_COARSE_ARGV + ["--out", old_path]) == 0
    assert gen.main(_COARSE_ARGV + ["--loss-map", "plant", "--out", map_path]) == 0
    old = open(old_path, "rb").read()
    new = open(map_path, "rb").read()
    assert old != new
    text = new.decode("utf-8")
    assert "# loss_map: " + hil.loss_map_canonical(hil.plant_loss_map()) in text
    assert "--loss-map plant" in text
    # ... and the header line round-trips back to the map it was solved with.
    import re as _re
    m = _re.search(r"# loss_map: (\S+)", text)
    assert hil.loss_map_from_canonical(m.group(1)) == hil.plant_loss_map()
