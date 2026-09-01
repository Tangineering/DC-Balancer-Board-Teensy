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
    scenario it was generated for)."""
    out_dir = str(tmp_path)
    assert gen.main(_COARSE_ARGV + ["--out",
                                    os.path.join(out_dir, "dp_ems_table_ems-soc-band.csv")]) == 0
    strategy = hil.DpReplayStrategy(table_dir=out_dir)
    strategy.bind_scenario("ems-soc-band", hil.SCENARIOS["ems-soc-band"])
    assert strategy.times
    out = strategy(30.0, {"t": 30.0, "v_profile": 1.5})
    assert 0.0 <= out["power_share_setpoint"] <= 1.0


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
