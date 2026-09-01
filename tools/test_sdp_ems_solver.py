#!/usr/bin/env python3
"""pytest suite for tools/sdp_ems_solver.py -- the offline stochastic-DP EMS
policy solver.

INTERPRETER: sdp_ems_solver.py imports numpy and scipy at module scope (it is
offline tooling, not part of the 1 kHz simulator loop), so this file can only
run under an interpreter that has both -- the repo's `.venv_hil` is
deliberately stdlib-only and does NOT.  Following tools/test_gen_dp_ems_table.py's
precedent, this module SKIPS CLEANLY (does not error/collect at all) when
numpy is unavailable, via `pytest.importorskip("numpy")` at import time.

Run:
    C:/Users/ricky/miniforge3/python.exe -m pytest tools/test_sdp_ems_solver.py -v

Reduced-grid solves in this file use DELIBERATELY COARSE parameters
(--soc-n 11, --share-n 5) so a solve finishes in well under a second on this
rig's small TPM -- these are NOT the parameters the shipped artifact was
generated with (see tools/sdp_policies/sdp_policy_v1.json's own `solver` and
`soc`/`actions` blocks for that).  A single check runs the FULL default grid
against the SHIPPED artifact (item 1); everything else uses the reduced grid
to keep the suite fast, per a session-scoped fixture that solves it ONCE.
"""
import json
import os
import sys

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import sdp_ems_solver as solver         # noqa: E402
import tpm_generator                    # noqa: E402

SHIPPED_POLICY_PATH = os.path.join(HERE, "sdp_policies", "sdp_policy_v1.json")

_REDUCED_ARGV = ["--soc-n", "11", "--share-n", "5"]


# ─────────────────────────────────────────────────────────────────────────
# fixtures: solve the reduced grid ONCE per session; read the shipped
# artifact ONCE per session (it is checked-in, read-only).
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def shipped_policy():
    assert os.path.isfile(SHIPPED_POLICY_PATH), (
        "the shipped artifact %r is missing -- regenerate with "
        "tools/sdp_ems_solver.py before running this suite" % SHIPPED_POLICY_PATH)
    with open(SHIPPED_POLICY_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def reduced_policy(tmp_path_factory):
    out = tmp_path_factory.mktemp("sdp_reduced") / "reduced.json"
    rc = solver.main(_REDUCED_ARGV + ["--out", str(out)])
    assert rc == 0
    with open(out, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ─────────────────────────────────────────────────────────────────────────
# 1. Shipped-artifact schema pin (full default grid, against the SHIPPED file)
# ─────────────────────────────────────────────────────────────────────────

def test_shipped_artifact_schema_and_shapes(shipped_policy):
    doc = shipped_policy
    assert doc["schema"] == solver.SCHEMA == "sdp-policy-v1"
    for key in ("generated_utc", "tool", "argv", "causal", "sim_only", "tpm",
               "normalization", "demand_bins", "decision_dt_s", "gamma",
               "alpha", "soc", "actions", "battery", "h2", "solver", "policy"):
        assert key in doc, key
    assert doc["causal"] is True
    assert doc["sim_only"] is True

    soc = doc["soc"]
    share = doc["policy"]["share"]
    goal = doc["policy"]["charge_goal"]
    n_soc = soc["n"]
    n_bins = doc["demand_bins"]["n"]
    assert len(share) == n_soc
    assert len(goal) == n_soc
    for row in share:
        assert len(row) == n_bins
    for row in goal:
        assert len(row) == n_bins

    ladder = set(doc["actions"]["share_ladder"])
    for row in share:
        for v in row:
            assert v in ladder, v
    for row in goal:
        for v in row:
            assert v in (0.0, 1.0), v

    assert doc["solver"]["converged"] is True


def test_shipped_artifact_solver_converged_within_its_own_tolerance(shipped_policy):
    s = shipped_policy["solver"]
    assert s["final_delta"] < s["tolerance"]
    assert s["iterations"] > 0
    assert s["iterations"] <= s["max_iterations"]


# ─────────────────────────────────────────────────────────────────────────
# 2. Non-degeneracy of the shipped policy
# ─────────────────────────────────────────────────────────────────────────

def test_shipped_artifact_non_degenerate_across_bins_and_across_soc(shipped_policy):
    doc = shipped_policy
    share = np.array(doc["policy"]["share"])
    soc_grid = np.array(doc["soc"]["grid"]) if doc["soc"].get("grid") else \
        np.linspace(doc["soc"]["grid_min"], doc["soc"]["grid_max"], doc["soc"]["n"])
    i_tgt = int(np.abs(soc_grid - doc["soc"]["target"]).argmin())

    row_at_target = share[i_tgt]
    assert row_at_target.max() > row_at_target.min(), (
        "share does not vary across demand bins at the SoC-target row")

    col_at_bin10 = share[:, 10]
    assert col_at_bin10.max() > col_at_bin10.min(), (
        "share does not vary across SoC rows at demand bin 10")


# ─────────────────────────────────────────────────────────────────────────
# 3. charge_forbidden_bins honored (shipped artifact)
# ─────────────────────────────────────────────────────────────────────────

def test_shipped_artifact_charge_goal_zero_in_every_forbidden_bin(shipped_policy):
    doc = shipped_policy
    forbidden = doc["actions"]["charge_forbidden_bins"]
    assert forbidden, "sanity: the shipped artifact must actually forbid something"
    goal = np.array(doc["policy"]["charge_goal"])
    for j in forbidden:
        col = goal[:, j]
        assert (col == 0.0).all(), (
            "charge_goal asserted in forbidden bin %d (rows %s)"
            % (j, np.nonzero(col)[0].tolist()))


def test_shipped_artifact_charge_goal_can_be_nonzero_outside_forbidden_bins(shipped_policy):
    """Vacuity guard for the check above: confirm the artifact actually DOES
    assert charge_goal somewhere (i.e. the all-zero forbidden-bin check is
    not trivially true because charge is never asserted anywhere at all)."""
    doc = shipped_policy
    forbidden = set(doc["actions"]["charge_forbidden_bins"])
    goal = np.array(doc["policy"]["charge_goal"])
    n_bins = goal.shape[1]
    allowed_cols = [j for j in range(n_bins) if j not in forbidden]
    assert allowed_cols
    allowed_block = goal[:, allowed_cols]
    assert (allowed_block > 0.0).any(), (
        "charge_goal is never asserted anywhere outside the forbidden bins -- "
        "the forbidden-bin check above would pass even if charging were "
        "globally broken")


# ─────────────────────────────────────────────────────────────────────────
# Round 2 (review-fix round, 2026-08-31): reviewer LOW-3 provenance pins and
# the D3/D8 floor-node clamp-tie exception.
# ─────────────────────────────────────────────────────────────────────────

def test_shipped_artifact_tpm_sha256_matches_recomputed_hash_of_the_live_mat_file():
    """LOW-3(a): the artifact's recorded tpm.sha256 must equal a FRESH sha256
    of the actual TPM .mat file on disk right now -- not merely a value that
    was true at generation time. solver.sha256_file() is the SAME function
    the solver used to bake it, reused here rather than reimplemented."""
    doc_path = SHIPPED_POLICY_PATH
    with open(doc_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    tpm_rel = doc["tpm"]["path"]
    tpm_abs = os.path.join(solver.REPO_ROOT, tpm_rel.replace("/", os.sep))
    assert os.path.isfile(tpm_abs), tpm_abs
    assert solver.sha256_file(tpm_abs) == doc["tpm"]["sha256"]


def test_shipped_artifact_tpm_sidecar_sha256_matches_recomputed_hash():
    """LOW-3(a), sidecar half: checkout-stable because
    references/EMS/generated/.gitattributes now marks the sidecar `-text`
    (LF-normalized, no autocrlf rewrite between checkouts) -- so this pin
    should hold on any clean checkout, not just the machine that generated
    the artifact."""
    doc_path = SHIPPED_POLICY_PATH
    with open(doc_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    sidecar_rel = doc["tpm"]["sidecar_path"]
    sidecar_abs = os.path.join(solver.REPO_ROOT, sidecar_rel.replace("/", os.sep))
    assert os.path.isfile(sidecar_abs), sidecar_abs
    assert solver.sha256_file(sidecar_abs) == doc["tpm"]["sidecar_sha256"]


def test_shipped_artifact_policy_block_digest_pin(shipped_policy):
    """LOW-3(b): pin the POLICY-BLOCK digest, not the raw file sha256 -- the
    solver agent's own report proved the raw byte sha moves on every --force
    (it carries generated_utc), so pinning it here would fail on the very
    next regeneration even with an UNCHANGED decision law. The policy-block
    digest is exactly the quantity hil_plant_sim.load_sdp_policy() records as
    `policy_sha256` (recipe:
    sha256(json.dumps(doc["policy"], sort_keys=True).encode("utf-8")))."""
    import hashlib
    digest = hashlib.sha256(
        json.dumps(shipped_policy["policy"], sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert digest == "dbe42d1b0ec5b40f07bc1d0ad91dd86ef90f44f7c62c51382dbf54e339821048"


def test_shipped_artifact_floor_node_clamp_tie_exception(shipped_policy):
    """D3/D8 floor-node clamp-tie exception (reviewer finding, made
    executable): at the clamped TOP demand bin (column 24) the policy is
    bang-bang about the SoC target for every node EXCEPT the exact grid-floor
    node (row 0, SoC == grid_min), which the D3 clamp-then-D8-tie-break
    combination resolves to the battery-favoring 0.0 rather than continuing
    the 1.0 rail down to the floor. Row 1 (the next node up) is back on the
    ordinary 1.0 rail. A future change to the tie-break rule (D8's "ties
    resolve toward the LOWEST control index") would flip this silently
    without this pin."""
    share = shipped_policy["policy"]["share"]
    assert share[0][24] == pytest.approx(0.0)
    assert share[1][24] == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────────────
# 4. Interp-J regression: the SoC transition genuinely sub-grid-spacing, and
#    the interpolation used against it splits weight between two nodes
#    rather than snapping to one (the D1 correctness fix, made executable).
# ─────────────────────────────────────────────────────────────────────────

def test_build_stage_soc_transition_is_sub_grid_spacing_and_not_grid_aligned():
    """Cheapest possible pin of D1's own measured fact: at this rig's power a
    single 1 s stage moves SoC by ~1e-5-1e-6 against a ~1e-3 grid spacing, so
    under NEAREST-GRID snapping (the MATLAB's own behaviour, explicitly
    rejected by D1) every transition would land back on its own starting
    node. Verified directly against build_stage()'s own soc_next output --
    no full solve required."""
    soc_grid = np.linspace(0.55, 0.65, 101)
    step = soc_grid[1] - soc_grid[0]
    shares = np.linspace(0.0, 1.0, 21)
    p_centers = np.array([0.5])          # one positive-demand bin, 0.5 W
    cap_as = 5.0 * 3600.0                # BATT_CAPACITY_AH default * 3600
    chg_allowed = np.array([True])

    stage, soc_next, feas = solver.build_stage(
        p_centers, shares, soc_grid, alpha=0.25, dt=1.0, cap_as=cap_as,
        chg_a=0.8, chg_allowed=chg_allowed, soc_target=0.6,
        soc_lo=soc_grid[0], soc_hi=soc_grid[-1])

    # share = 0.0 (pure battery discharge, control index 0) at a mid-grid SoC
    # row: the transition must have MOVED (nonzero) but stayed far inside a
    # single grid cell (sub-spacing), i.e. it neither snapped to its own
    # starting node NOR jumped to a neighboring one.
    i_soc = 50
    moved = soc_next[0, i_soc, 0]
    delta = moved - soc_grid[i_soc]
    assert delta != 0.0
    assert 0.0 < abs(delta) < 0.01 * step, (
        "expected a sub-grid-spacing SoC step (D1's whole premise); got "
        "delta=%.3e against grid step=%.3e" % (delta, step))

    # Nearest-grid semantics (the REJECTED MATLAB behaviour) would round this
    # straight back to its own starting node -- confirm that is NOT what the
    # feasibility/soc_next array records, i.e. it genuinely lies strictly
    # between two grid nodes and needs interpolation to be read at all.
    idx_below = int(np.searchsorted(soc_grid, moved)) - 1
    assert 0 <= idx_below < len(soc_grid) - 1
    assert soc_grid[idx_below] < moved < soc_grid[idx_below + 1]


def test_interpolation_splits_weight_across_two_grid_nodes_for_a_sub_spacing_step():
    """The SAME np.interp() call value_iterate()/greedy_policy() use against
    build_stage()'s soc_next, exercised directly against a KNOWN (non-flat)
    cost-to-go column: a sub-grid-spacing move must change the interpolated
    value by a PROPORIONAL sub-grid-spacing amount, never by the full
    neighbor-to-neighbor jump a nearest-grid lookup would produce."""
    soc_grid = np.linspace(0.55, 0.65, 101)
    step = soc_grid[1] - soc_grid[0]
    # A column with real slope (linear in SoC), so np.interp's LINEAR
    # blending is directly checkable against the analytic answer.
    ej_col = 3.0 * soc_grid + 1.0

    i_soc = 50
    x0 = soc_grid[i_soc]
    sub_step = step * 0.01
    x1 = x0 + sub_step

    v0 = np.interp(x0, soc_grid, ej_col)
    v1 = np.interp(x1, soc_grid, ej_col)
    assert v0 == pytest.approx(ej_col[i_soc])
    # The interpolated value at x1 must differ from v0 by the SLOPE times the
    # sub-step -- i.e. it blended the two neighboring nodes' weight
    # proportionally, not snapped wholesale onto one of them.
    assert v1 == pytest.approx(v0 + 3.0 * sub_step, rel=1e-9)
    assert v1 != pytest.approx(v0)
    # And it must NOT equal the NEXT grid node's value either -- a
    # coarser-than-nearest-grid bug (rounding up) would produce that instead.
    assert v1 != pytest.approx(ej_col[i_soc + 1])


# ─────────────────────────────────────────────────────────────────────────
# 5. alpha collapse pin: --alpha-mode level (REJECTED) degenerates the
#    policy; the default coulombic (marginal) mode does not.
# ─────────────────────────────────────────────────────────────────────────

def test_alpha_mode_level_collapses_share_spread_to_zero(tmp_path):
    out = tmp_path / "level.json"
    rc = solver.main(_REDUCED_ARGV + ["--alpha-mode", "level", "--out", str(out)])
    assert rc == 0
    with open(out, encoding="utf-8") as fh:
        doc = json.load(fh)
    share = np.array(doc["policy"]["share"])
    assert share.max() == pytest.approx(0.0)
    assert share.min() == pytest.approx(0.0)
    assert doc["alpha"]["value"] == pytest.approx(
        solver.FULL_SIZE_ALPHA * doc["normalization"]["p_dem_max_w"]
        / solver.FULL_SIZE_P_DEM_MAX_W)


def test_alpha_mode_marginal_default_yields_nonzero_spread(reduced_policy):
    share = np.array(reduced_policy["policy"]["share"])
    assert share.max() > share.min()
    assert reduced_policy["alpha"]["value"] == pytest.approx(
        solver.FULL_SIZE_ALPHA * (solver.V_PACK_NOMINAL_V * solver.BATT_CAPACITY_AH)
        / (solver.FULL_SIZE_EM_V * solver.FULL_SIZE_Q_AH))


def test_explicit_alpha_overrides_alpha_mode(tmp_path):
    out = tmp_path / "explicit_alpha.json"
    rc = solver.main(_REDUCED_ARGV + ["--alpha", "0.1", "--alpha-mode", "level",
                                      "--out", str(out)])
    assert rc == 0
    with open(out, encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["alpha"]["value"] == pytest.approx(0.1)


# ─────────────────────────────────────────────────────────────────────────
# 6. Determinism: two reduced solves, identical args -> identical policy
# ─────────────────────────────────────────────────────────────────────────

def test_two_reduced_solves_produce_identical_policy_blocks(tmp_path):
    out1 = tmp_path / "a.json"
    out2 = tmp_path / "b.json"
    rc1 = solver.main(_REDUCED_ARGV + ["--out", str(out1)])
    rc2 = solver.main(_REDUCED_ARGV + ["--out", str(out2)])
    assert rc1 == 0 and rc2 == 0
    with open(out1, encoding="utf-8") as fh:
        doc1 = json.load(fh)
    with open(out2, encoding="utf-8") as fh:
        doc2 = json.load(fh)
    assert doc1["policy"] == doc2["policy"]
    assert doc1["solver"]["iterations"] == doc2["solver"]["iterations"]
    assert doc1["solver"]["final_delta"] == doc2["solver"]["final_delta"]
    assert doc1["alpha"] == doc2["alpha"]
    assert doc1["gamma"] == doc2["gamma"]
    # generated_utc is the one field expected to differ between two calls.
    assert "generated_utc" in doc1 and "generated_utc" in doc2


# ─────────────────────────────────────────────────────────────────────────
# 7. Refusals: existing output without --force; non-convergence
# ─────────────────────────────────────────────────────────────────────────

def test_refuses_to_overwrite_existing_output_without_force(tmp_path, capsys):
    out = tmp_path / "a.json"
    rc1 = solver.main(_REDUCED_ARGV + ["--out", str(out)])
    assert rc1 == 0
    capsys.readouterr()
    rc2 = solver.main(_REDUCED_ARGV + ["--out", str(out)])
    assert rc2 == 2
    err = capsys.readouterr().err
    assert "REFUSING to overwrite" in err


def test_force_allows_overwrite(tmp_path):
    out = tmp_path / "a.json"
    assert solver.main(_REDUCED_ARGV + ["--out", str(out)]) == 0
    assert solver.main(_REDUCED_ARGV + ["--out", str(out), "--force"]) == 0


def test_non_convergence_refuses_to_write(tmp_path, capsys):
    out = tmp_path / "unconverged.json"
    rc = solver.main(_REDUCED_ARGV + ["--out", str(out), "--max-iter", "1"])
    assert rc == 2
    assert not os.path.exists(out)
    err = capsys.readouterr().err
    assert "REFUSING to write an unconverged policy" in err


def test_non_convergence_dry_run_does_not_need_to_write(tmp_path, capsys):
    """--dry-run and non-convergence are two independent refusals to write;
    a non-converged --dry-run solve must still report cleanly (rc 2, same
    refusal) rather than crash on interacting flags."""
    out = tmp_path / "never.json"
    rc = solver.main(_REDUCED_ARGV + ["--out", str(out), "--max-iter", "1",
                                      "--dry-run"])
    assert rc == 2
    assert not os.path.exists(out)


# ─────────────────────────────────────────────────────────────────────────
# 8. Gamma: rescale_gamma is actually called; effective gamma == 0.95 at dt=1
# ─────────────────────────────────────────────────────────────────────────

def test_rescale_gamma_is_called_and_matches_recorded_effective_value(tmp_path, monkeypatch):
    calls = []
    real = solver.rescale_gamma

    def _spy(gamma_base, dt, dt_base=1.0):
        calls.append((gamma_base, dt, dt_base))
        return real(gamma_base, dt, dt_base)

    monkeypatch.setattr(solver, "rescale_gamma", _spy)
    out = tmp_path / "gamma.json"
    rc = solver.main(_REDUCED_ARGV + ["--out", str(out)])
    assert rc == 0
    assert calls, "solver.rescale_gamma was never called"
    gb, dt, dtb = calls[0]
    assert gb == pytest.approx(solver.GAMMA_BASE)
    assert dt == pytest.approx(1.0)
    with open(out, encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["gamma"]["effective"] == pytest.approx(0.95)
    assert doc["gamma"]["base"] == pytest.approx(0.95)
    assert doc["gamma"]["dt_s"] == pytest.approx(1.0)


def test_rescale_gamma_effective_tracks_dt_scaling_directly():
    """Belt-and-braces on the underlying function itself (imported from
    tpm_generator, not reimplemented here): gamma_eff = gamma_base**(dt/dt_base)."""
    assert tpm_generator.rescale_gamma(0.95, 1.0, 1.0) == pytest.approx(0.95)
    assert tpm_generator.rescale_gamma(0.95, 0.5, 1.0) == pytest.approx(0.95 ** 0.5)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
