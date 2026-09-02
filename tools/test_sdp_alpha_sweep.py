"""Independent Stage-2 tests for tools/sdp_alpha_sweep.py.

Run: C:/Users/ricky/miniforge3/python.exe -m pytest tools/test_sdp_alpha_sweep.py -q
"""

import csv
import hashlib
import json
import os
import subprocess
import sys

import pytest

np = pytest.importorskip("numpy")

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import sdp_alpha_sweep as sweep  # noqa: E402

SWEEP_DIR = sweep.SWEEP_DIR
ANCHOR_ARTIFACT = sweep.ANCHOR_ARTIFACT
HAVE_SWEEP_DIR = os.path.isdir(SWEEP_DIR)
HAVE_ANCHOR = os.path.isfile(ANCHOR_ARTIFACT)


# ---------------------------------------------------------------------------
# build_grid
# ---------------------------------------------------------------------------

def test_grid_has_21_points():
    grid = sweep.build_grid()
    assert len(grid) == 21


def test_grid_endpoints_exact():
    grid = sweep.build_grid()
    non_anchor = sorted(p["alpha"] for p in grid if not p["is_anchor"])
    assert len(non_anchor) == 20
    assert abs(non_anchor[0] - sweep.ALPHA_LO) < 1e-12
    assert abs(non_anchor[-1] - sweep.ALPHA_HI) < 1e-12


def test_grid_geomspace_constant_ratio():
    grid = sweep.build_grid()
    non_anchor = sorted(p["alpha"] for p in grid if not p["is_anchor"])
    ratios = [non_anchor[i + 1] / non_anchor[i] for i in range(len(non_anchor) - 1)]
    # geomspace: constant ratio between consecutive points, to float precision.
    for r in ratios[1:]:
        assert abs(r - ratios[0]) < 1e-9 * ratios[0]


def test_anchor_present_exactly_once_and_flagged():
    grid = sweep.build_grid()
    anchors = [p for p in grid if p["is_anchor"]]
    assert len(anchors) == 1
    assert anchors[0]["alpha"] == pytest.approx(sweep.ANCHOR_ALPHA, abs=1e-12)
    # And it is a genuinely additional point: exactly 20 non-anchor points.
    assert sum(1 for p in grid if not p["is_anchor"]) == 20


def test_grid_sorted_and_indexed_deterministically():
    grid = sweep.build_grid()
    idxs = [p["idx"] for p in grid]
    assert idxs == list(range(21))
    alphas = [p["alpha"] for p in grid]
    assert alphas == sorted(alphas)
    # Rebuilding gives the identical sequence (determinism).
    grid2 = sweep.build_grid()
    assert [p["alpha"] for p in grid2] == alphas
    assert [p["is_anchor"] for p in grid2] == [p["is_anchor"] for p in grid]


@pytest.mark.skipif(not HAVE_ANCHOR, reason="sdp_policy_v3.json not present")
def test_in_window_count_matches_investigator_prediction():
    """4 of the 20 geomspace points + the anchor lie inside BOTH admission
    windows (model and measured) — the count the investigator predicted."""
    win_model, win_meas = sweep._windows_from_anchor()
    grid = sweep.build_grid()
    in_both = [
        p for p in grid
        if win_model[0] < p["alpha"] < win_model[1]
        and win_meas[0] < p["alpha"] < win_meas[1]
    ]
    assert len(in_both) == 5
    assert sum(1 for p in in_both if p["is_anchor"]) == 1
    assert sum(1 for p in in_both if not p["is_anchor"]) == 4


# ---------------------------------------------------------------------------
# eq_h2
# ---------------------------------------------------------------------------

def test_eq_h2_hand_computed():
    # eq_h2 = h2 - (dsoc - dsoc_ref) / lambda, lambda = 0.41.
    h2 = 0.0125
    dsoc = -0.002
    dsoc_ref = -0.0015
    lam = 0.41
    expected = h2 - (dsoc - dsoc_ref) / lam
    got = sweep.eq_h2(h2, dsoc, dsoc_ref, lam=lam)
    assert got == pytest.approx(expected, abs=1e-15)
    # Default lambda matches the module constant of 0.41.
    assert sweep.EQ_H2_LAMBDA_SOC_PER_G == pytest.approx(0.41, abs=1e-12)
    got_default = sweep.eq_h2(h2, dsoc, dsoc_ref)
    assert got_default == pytest.approx(expected, abs=1e-15)


def test_eq_h2_zero_when_dsoc_matches_ref():
    assert sweep.eq_h2(0.0333, -0.001, -0.001) == pytest.approx(0.0333, abs=1e-15)


# ---------------------------------------------------------------------------
# share_histogram
# ---------------------------------------------------------------------------

def test_share_histogram_fractions_sum_to_one():
    policy_share = [[0.0, 0.5, 1.0, 0.5], [0.85, 0.85, 0.0, 1.0]]
    hist = sweep.share_histogram(policy_share)
    assert hist
    assert sum(hist.values()) == pytest.approx(1.0, abs=1e-12)
    # 0.85 appears twice out of eight cells.
    assert hist["0.8500"] == pytest.approx(2.0 / 8.0, abs=1e-12)


def test_share_histogram_degenerate_share_zero_everywhere():
    policy_share = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    hist = sweep.share_histogram(policy_share)
    assert hist == {"0.0000": 1.0}


def test_share_histogram_empty_policy():
    assert sweep.share_histogram([]) == {}


# ---------------------------------------------------------------------------
# summarize_artifact
# ---------------------------------------------------------------------------

def _make_synthetic_artifact(tmp_path, alpha=0.16, mode="lever",
                              win_model=(0.10, 0.20), win_meas=(0.10, 0.20),
                              n_charge=2, converged=True, iterations=42):
    charge = [[0, 0], [1, 1]] if n_charge else [[0, 0], [0, 0]]
    doc = {
        "schema": "sdp-policy-v1",
        "alpha": {
            "value": alpha,
            "mode": mode,
            "admission": {
                "window_model": list(win_model),
                "window_measured": list(win_meas),
            },
        },
        "solver": {
            "converged": converged,
            "iterations": iterations,
            "final_delta": 1e-13,
        },
        "actions": {
            "charge_forbidden_bins": [1, 2, 3],
        },
        "policy": {
            "share": [[0.0, 0.85], [0.5, 0.85]],
            "charge_goal": charge,
        },
    }
    path = tmp_path / "synthetic.json"
    path.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
    return str(path), doc


def test_summarize_artifact_policy_sha256_matches_consumer_recipe(tmp_path):
    path, doc = _make_synthetic_artifact(tmp_path)
    point = {"idx": 3, "alpha": 0.16, "is_anchor": False}
    entry = sweep.summarize_artifact(path, point, wall_s=1.23)
    expected = hashlib.sha256(
        json.dumps(doc["policy"], sort_keys=True).encode("utf-8")).hexdigest()
    assert entry["policy_sha256"] == expected
    assert entry["policy_sha256"] == sweep.policy_sha256(doc)


def test_summarize_artifact_n_charge_cells_counts_positive():
    doc = {
        "policy": {"charge_goal": [[0, 1, 0], [1, 1, 0]]},
    }
    charge = doc["policy"]["charge_goal"]
    n_charge = sum(1 for row in charge for v in row if float(v) > 0.0)
    assert n_charge == 3


def test_summarize_artifact_converged_iterations_passthrough(tmp_path):
    path, doc = _make_synthetic_artifact(
        tmp_path, converged=False, iterations=999)
    point = {"idx": 0, "alpha": 0.16, "is_anchor": False}
    entry = sweep.summarize_artifact(path, point, wall_s=None)
    assert entry["converged"] is False
    assert entry["iterations"] == 999
    assert entry["wall_s"] is None


def test_summarize_artifact_window_flags(tmp_path):
    path, doc = _make_synthetic_artifact(
        tmp_path, alpha=0.15, win_model=(0.10, 0.20), win_meas=(0.30, 0.40))
    point = {"idx": 0, "alpha": 0.15, "is_anchor": False}
    entry = sweep.summarize_artifact(path, point, wall_s=None)
    assert entry["in_window_model"] is True
    assert entry["in_window_measured"] is False


# ---------------------------------------------------------------------------
# build_manifest
# ---------------------------------------------------------------------------

def test_build_manifest_schema_and_fields():
    entries = [{"idx": 0, "alpha": 0.05}, {"idx": 1, "alpha": 0.1}]
    manifest = sweep.build_manifest(
        entries, "references/EMS/generated/TPM_dt1_hil.mat", "deadbeef" * 8,
        0.95, {"verdict": "MATCH"})
    assert manifest["schema"] == "sdp-alpha-sweep-v1"
    assert manifest["points"] == entries
    assert manifest["gamma"] == 0.95
    assert manifest["tpm"]["sha256"] == "deadbeef" * 8
    assert manifest["anchor_check"]["verdict"] == "MATCH"
    assert "generated_utc" in manifest


def test_sha256_file_recomputed_from_bytes(tmp_path):
    p = tmp_path / "f.bin"
    data = b"some bytes to hash \x00\x01\x02"
    p.write_bytes(data)
    assert sweep.sha256_file(str(p)) == hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Committed artifacts (skipped if the sweep directory is absent)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAVE_SWEEP_DIR, reason="sweep_20260901/ not present")
class TestCommittedArtifacts:

    @staticmethod
    def _manifest():
        with open(os.path.join(SWEEP_DIR, "manifest.json"),
                   encoding="utf-8") as f:
            return json.load(f)

    def test_manifest_lists_21_files_all_exist(self):
        manifest = self._manifest()
        assert len(manifest["points"]) == 21
        for entry in manifest["points"]:
            full = os.path.join(REPO_ROOT, entry["file"])
            assert os.path.isfile(full), entry["file"]

    def test_each_file_sha256_matches_manifest(self):
        manifest = self._manifest()
        for entry in manifest["points"]:
            full = os.path.join(REPO_ROOT, entry["file"])
            assert sweep.sha256_file(full) == entry["file_sha256"], entry["file"]

    def test_point_10_policy_sha_matches_sdp_policy_v3(self):
        manifest = self._manifest()
        by_idx = {e["idx"]: e for e in manifest["points"]}
        assert 10 in by_idx
        entry = by_idx[10]
        assert entry["is_anchor"] is True
        expected = ("0443febf240a9f5c207c42595f5841d2842496ac786c4d5342f1f8df"
                    "e33c61a2")
        assert entry["policy_sha256"] == expected

    def test_charge_cell_boundary_0_13_zero_14_20_positive(self):
        manifest = self._manifest()
        by_idx = {e["idx"]: e for e in manifest["points"]}
        for i in range(0, 14):
            assert by_idx[i]["n_charge_cells"] == 0, i
        for i in range(14, 21):
            assert by_idx[i]["n_charge_cells"] > 0, i

    def test_degenerate_share_zero_boundary_0_6_vs_7_plus(self):
        manifest = self._manifest()
        by_idx = {e["idx"]: e for e in manifest["points"]}
        for i in range(0, 7):
            hist = by_idx[i]["share_ladder_histogram"]
            assert hist == {"0.0000": pytest.approx(1.0)}, i
        for i in range(7, 21):
            hist = by_idx[i]["share_ladder_histogram"]
            assert not (len(hist) == 1 and "0.0000" in hist
                        and hist["0.0000"] == pytest.approx(1.0)), i

    def test_every_artifact_converged(self):
        manifest = self._manifest()
        for entry in manifest["points"]:
            assert entry["converged"] is True, entry["idx"]

    def test_alpha_value_and_mode_explicit(self):
        manifest = self._manifest()
        for entry in manifest["points"]:
            assert abs(entry["alpha_value_recorded"] - entry["alpha"]) < 1e-12
            assert entry["alpha_mode_recorded"] == "explicit"


# ---------------------------------------------------------------------------
# evaluation_rows
# ---------------------------------------------------------------------------

class _FakeResult(object):
    def __init__(self, h2_g, h2_proxy_g, delta_soc, mode_fractions,
                 charge_windows):
        self.h2_g = h2_g
        self.h2_proxy_g = h2_proxy_g
        self.delta_soc = delta_soc
        self.soc_final = 0.7 + delta_soc
        self.mode_fractions = mode_fractions
        self.charge_windows = charge_windows


def test_evaluation_rows_one_per_point_and_eq_h2_vs_anchor():
    grid = sweep.build_grid()
    anchor_idx = [p["idx"] for p in grid if p["is_anchor"]][0]
    results = {}
    for p in grid:
        results[p["idx"]] = (p, _FakeResult(
            h2_g=0.01 + 0.0001 * p["idx"],
            h2_proxy_g=0.0095 + 0.0001 * p["idx"],
            delta_soc=-0.001 - 0.00001 * p["idx"],
            mode_fractions={"share": 1.0, "charge": 0.0},
            charge_windows=[1, 2] if p["idx"] % 5 == 0 else [],
        ))
    rows = sweep.evaluation_rows(results, anchor_idx)
    assert len(rows) == 21
    dsoc_ref = results[anchor_idx][1].delta_soc
    for row in rows:
        r = results[row["idx"]][1]
        expected = sweep.eq_h2(r.h2_g, r.delta_soc, dsoc_ref)
        assert row["eq_h2_g"] == pytest.approx(expected, abs=1e-15)
        assert row["charge_windows"] == len(r.charge_windows)
    # Anchor row's eq_h2 reduces to its own h2_g (dsoc == dsoc_ref).
    anchor_row = [r for r in rows if r["idx"] == anchor_idx][0]
    assert anchor_row["eq_h2_g"] == pytest.approx(
        results[anchor_idx][1].h2_g, abs=1e-15)


def test_evaluation_rows_charge_windows_int_without_len():
    grid = sweep.build_grid()
    anchor_idx = [p["idx"] for p in grid if p["is_anchor"]][0]
    results = {p["idx"]: (p, _FakeResult(0.01, 0.0095, -0.001,
                                         {"share": 1.0}, 3))
               for p in grid}
    rows = sweep.evaluation_rows(results, anchor_idx)
    assert all(row["charge_windows"] == 3 for row in rows)


# ---------------------------------------------------------------------------
# CLI: grid
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAVE_ANCHOR, reason="sdp_policy_v3.json not present")
def test_cli_grid_prints_21_data_lines():
    result = subprocess.run(
        [sys.executable, os.path.join(_HERE, "sdp_alpha_sweep.py"), "grid"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    # Header line, 21 data lines, one window-summary line.
    data_lines = [l for l in lines if l and l[0].isdigit() or
                  (l[:3].strip().isdigit())]
    # More robust: count lines starting with an index 0-20 in the first field.
    idx_lines = [l for l in lines if l.split() and
                 l.split()[0].lstrip("-").isdigit()]
    assert len(idx_lines) == 21


# ---------------------------------------------------------------------------
# CLI: evaluate --self-test / walk-unavailable
# ---------------------------------------------------------------------------

def test_cli_evaluate_self_test_runs_without_walk_module(tmp_path):
    out_dir = str(tmp_path / "eval_out")
    rc = sweep.main(["evaluate", "--self-test", "--out", out_dir])
    assert rc == 0
    assert os.path.isfile(os.path.join(out_dir, "sweep_eval_selftest.csv"))
    assert os.path.isfile(os.path.join(out_dir, "sweep_eval_selftest.md"))


def test_cli_evaluate_exits_3_when_walk_module_unavailable(tmp_path, monkeypatch):
    def _boom():
        raise ImportError("no module named ems_walk (not built yet)")
    monkeypatch.setattr(sweep, "_load_walk", _boom)
    out_dir = str(tmp_path / "eval_out2")

    class _Args(object):
        self_test = False
        out = out_dir
        scenario = ["ems-sdp"]
        strategy = sweep.EVAL_STRATEGY

    rc = sweep.cmd_evaluate(_Args())
    assert rc == 3


# ---------------------------------------------------------------------------
# solve: filename, --allow-out-of-window, --force
# ---------------------------------------------------------------------------

def test_solver_argv_filename_pattern():
    point = {"idx": 7, "alpha": 0.12005608351123227, "is_anchor": False}
    name = sweep.point_filename(point)
    assert name == "alpha_07_0.120056.json"


def test_solver_argv_allow_out_of_window_only_when_needed():
    point = {"idx": 0, "alpha": 0.0514, "is_anchor": False}
    argv_out = sweep.solver_argv(point, "/tmp/x.json", False, in_model=False,
                                 in_meas=False)
    assert "--allow-out-of-window" in argv_out

    argv_in = sweep.solver_argv(point, "/tmp/x.json", False, in_model=True,
                                in_meas=True)
    assert "--allow-out-of-window" not in argv_in

    argv_partial = sweep.solver_argv(point, "/tmp/x.json", False,
                                     in_model=True, in_meas=False)
    assert "--allow-out-of-window" in argv_partial


def test_solver_argv_force_flag():
    point = {"idx": 0, "alpha": 0.0514, "is_anchor": False}
    argv_no_force = sweep.solver_argv(point, "/tmp/x.json", False, True, True)
    assert "--force" not in argv_no_force
    argv_force = sweep.solver_argv(point, "/tmp/x.json", True, True, True)
    assert "--force" in argv_force


@pytest.mark.skipif(not HAVE_ANCHOR, reason="sdp_policy_v3.json not present")
def test_cmd_solve_writes_manifest_naming_and_respects_existing_file(
        tmp_path, monkeypatch):
    """Monkeypatch the solver entry point to a stub writing a minimal
    artifact, and verify: file naming alpha_{idx:02d}_{alpha:.6f}.json,
    --allow-out-of-window passed only for out-of-window points, and --force
    semantics (existing file refused without it)."""
    fake_sweep_dir = str(tmp_path / "sweep_dir")
    monkeypatch.setattr(sweep, "SWEEP_DIR", fake_sweep_dir)

    win_model, win_meas = sweep._windows_from_anchor()
    calls = []

    class _StubSolver(object):
        @staticmethod
        def main(argv):
            calls.append(argv)
            out_path = argv[argv.index("--out") + 1]
            force = "--force" in argv
            if os.path.exists(out_path) and not force:
                print("[stub] refusing: exists, no --force")
                return 1
            alpha = float(argv[argv.index("--alpha") + 1])
            doc = {
                "alpha": {
                    "value": alpha, "mode": "explicit",
                    "admission": {
                        "window_model": list(win_model),
                        "window_measured": list(win_meas),
                    },
                },
                "solver": {"converged": True, "iterations": 1,
                          "final_delta": 1e-13},
                "actions": {"charge_forbidden_bins": []},
                "policy": {"share": [[0.0]], "charge_goal": [[0]]},
                "gamma": 0.95,
            }
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(doc, f)
            return 0

    monkeypatch.setattr(sweep, "_import_solver", lambda: _StubSolver)

    class _Args(object):
        force = False
        only = None

    rc = sweep.cmd_solve(_Args())
    assert rc == 0

    grid = sweep.build_grid()
    # Every point's --out matches the documented naming.
    for argv, point in zip(calls, grid):
        out_path = argv[argv.index("--out") + 1]
        assert os.path.basename(out_path) == sweep.point_filename(point)
        in_model = win_model[0] < point["alpha"] < win_model[1]
        in_meas = win_meas[0] < point["alpha"] < win_meas[1]
        if in_model and in_meas:
            assert "--allow-out-of-window" not in argv
        else:
            assert "--allow-out-of-window" in argv

    manifest_path = os.path.join(fake_sweep_dir, "manifest.json")
    assert os.path.isfile(manifest_path)
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    assert len(manifest["points"]) == 21

    # Re-running without --force must refuse (existing files, stub returns 1).
    rc2 = sweep.cmd_solve(_Args())
    assert rc2 == 1

    # With --force, every call must carry --force and succeed.
    class _ArgsForce(object):
        force = True
        only = None

    calls.clear()
    rc3 = sweep.cmd_solve(_ArgsForce())
    assert rc3 == 0
    for argv in calls:
        assert "--force" in argv


# ===========================================================================
# Stage-2 additions (2026-09-01): refine/plots subcommands, refinement grid,
# manifest.refinement block, WalkResult trace fields, HIL CSV synthesis.
# ===========================================================================

MANIFEST_PATH = os.path.join(SWEEP_DIR, "manifest.json")
HAVE_MANIFEST = os.path.isfile(MANIFEST_PATH)


def _load_manifest():
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# bisect_boundary against a stub solver
# ---------------------------------------------------------------------------

class _StubBisectSolver(object):
    """A fake sdp_ems_solver whose 'policy' crosses a boundary at alpha=0.20."""

    THRESHOLD = 0.20

    @classmethod
    def main(cls, argv):
        alpha = float(argv[argv.index("--alpha") + 1])
        out_path = argv[argv.index("--out") + 1]
        above = alpha >= cls.THRESHOLD
        doc = {
            "policy": {
                "share": [[1.0 if above else 0.0, 0.0]],
                "charge_goal": [[1 if above else 0, 0]],
            },
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        return 0


def test_bisect_boundary_result_inside_bracket_and_converges(tmp_path):
    tmp_path_file = str(tmp_path / "probe.json")
    result = sweep.bisect_boundary(
        _StubBisectSolver, "degeneracy", tmp_path_file,
        bracket=(0.10, 0.30), rel_tol=1e-6)
    lo, hi = 0.10, 0.30
    assert lo < result["alpha"] < hi
    assert result["interval"][0] <= result["alpha"] <= result["interval"][1]
    assert result["rel_width"] <= 1e-6
    # Converges to the stub's known threshold.
    assert result["alpha"] == pytest.approx(_StubBisectSolver.THRESHOLD, abs=1e-4)
    # Solve count is bounded: not unbounded, and consistent with a bisection
    # from a ~3x bracket down to 1e-6 relative width (~2 verification solves
    # plus roughly log2(0.2/1e-6) refinement solves).
    assert 2 <= result["solves"] <= 40


def test_bisect_boundary_non_straddling_bracket_raises(tmp_path):
    tmp_path_file = str(tmp_path / "probe.json")
    # Both ends above the stub's threshold -> predicate True at both ends ->
    # does not straddle.
    with pytest.raises(RuntimeError):
        sweep.bisect_boundary(
            _StubBisectSolver, "degeneracy", tmp_path_file,
            bracket=(0.25, 0.30), rel_tol=1e-6)
    # Both ends below -> predicate False at both ends -> does not straddle.
    with pytest.raises(RuntimeError):
        sweep.bisect_boundary(
            _StubBisectSolver, "degeneracy", tmp_path_file,
            bracket=(0.05, 0.10), rel_tol=1e-6)


def test_bisect_boundary_charge_predicate_stub(tmp_path):
    tmp_path_file = str(tmp_path / "probe.json")
    result = sweep.bisect_boundary(
        _StubBisectSolver, "charge", tmp_path_file,
        bracket=(0.10, 0.30), rel_tol=1e-5)
    assert result["alpha"] == pytest.approx(_StubBisectSolver.THRESHOLD, abs=1e-3)
    assert result["rel_width"] <= 1e-5


# ---------------------------------------------------------------------------
# refined_alphas / build_refined_grid
# ---------------------------------------------------------------------------

def test_refined_alphas_ten_points_ascending():
    alphas = sweep.refined_alphas(0.10)
    assert len(alphas) == 10
    assert alphas == sorted(alphas)


def test_refined_alphas_rel_offset_exact_for_refine_deltas():
    b = 0.111
    alphas = sweep.refined_alphas(b)
    below = alphas[:5]
    above = alphas[5:]
    deltas_desc = sorted(sweep.REFINE_DELTAS, reverse=True)
    for a, d in zip(below, deltas_desc):
        assert a == pytest.approx(b * (1.0 - d), rel=1e-12)
    deltas_asc = sorted(sweep.REFINE_DELTAS)
    for a, d in zip(above, deltas_asc):
        assert a == pytest.approx(b * (1.0 + d), rel=1e-12)
    # All below points are < b, all above points are > b.
    assert all(a < b for a in below)
    assert all(a > b for a in above)


def test_build_refined_grid_indices_consecutive_side_labels_not_anchor():
    boundaries = {"degeneracy": 0.111, "charge": 0.239}
    grid = sweep.build_refined_grid(boundaries, idx_start=21)
    assert len(grid) == 20
    idxs = [p["idx"] for p in grid]
    assert idxs == list(range(21, 41))
    for p in grid:
        assert p["is_anchor"] is False
        assert p["origin"] == "refined"
        b = boundaries[p["boundary"]]
        expected_side = "below" if p["alpha"] < b else "above"
        assert p["side"] == expected_side
        expected_offset = (p["alpha"] - b) / b
        assert p["rel_offset"] == pytest.approx(expected_offset, abs=1e-12)
    # First 10 belong to "degeneracy" (REFINE_ORDER[0]), next 10 to "charge".
    assert all(p["boundary"] == "degeneracy" for p in grid[:10])
    assert all(p["boundary"] == "charge" for p in grid[10:])


def test_build_refined_grid_missing_boundary_skipped():
    grid = sweep.build_refined_grid({"charge": 0.239}, idx_start=21)
    assert len(grid) == 10
    assert all(p["boundary"] == "charge" for p in grid)
    assert [p["idx"] for p in grid] == list(range(21, 31))


# ---------------------------------------------------------------------------
# Manifest: shape, boundary values, spacing.deltas, regeneration, shas
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAVE_MANIFEST, reason="manifest.json not present")
class TestRefinementManifest:

    def test_schema_unchanged_points_21_refinement_points_20(self):
        m = _load_manifest()
        assert m["schema"] == "sdp-alpha-sweep-v1"
        assert len(m["points"]) == 21
        assert len(m["refinement"]["points"]) == 20

    def test_boundary_values_inside_modelled_admission_window(self):
        m = _load_manifest()
        b = m["refinement"]["boundaries"]
        deg = b["degeneracy"]["alpha"]
        chg = b["charge"]["alpha"]
        assert deg == pytest.approx(0.111000013, abs=5.1e-8)
        assert chg == pytest.approx(0.239249990, abs=1.1e-7)
        # Both boundary values lie inside the modelled admission window
        # (0.111000, 0.239250), within 1e-6 of either end.
        lo, hi = 0.111000, 0.239250
        assert lo - 1e-6 <= deg <= hi + 1e-6
        assert lo - 1e-6 <= chg <= hi + 1e-6

    def test_boundaries_have_names_intervals_matching_alpha(self):
        m = _load_manifest()
        for name, b in m["refinement"]["boundaries"].items():
            assert b["name"] == name
            lo, hi = b["interval"]
            assert lo <= b["alpha"] <= hi

    def test_spacing_deltas_equals_refine_deltas(self):
        m = _load_manifest()
        deltas = m["refinement"]["spacing"]["deltas"]
        assert list(deltas) == [float(d) for d in sweep.REFINE_DELTAS]

    def test_refined_grid_from_manifest_regenerates_filenames(self):
        grid = sweep.refined_grid_from_manifest()
        assert len(grid) == 20
        m = _load_manifest()
        recorded_files = {e["idx"]: os.path.basename(e["file"])
                          for e in m["refinement"]["points"]}
        for p in grid:
            assert sweep.point_filename(p) == recorded_files[p["idx"]]

    def test_every_refined_artifact_sha_matches(self):
        m = _load_manifest()
        for entry in m["refinement"]["points"]:
            full = os.path.join(REPO_ROOT, entry["file"])
            assert os.path.isfile(full), entry["file"]
            assert sweep.sha256_file(full) == entry["file_sha256"], entry["file"]

    def test_idx_21_to_25_degenerate_and_zero_charge_cells(self):
        m = _load_manifest()
        by_idx = {e["idx"]: e for e in m["refinement"]["points"]}
        for i in range(21, 26):
            assert by_idx[i]["n_charge_cells"] == 0, i
            hist = by_idx[i]["share_ladder_histogram"]
            assert hist == {"0.0000": pytest.approx(1.0)}, i

    def test_idx_26_to_35_non_degenerate_zero_charge_cells(self):
        m = _load_manifest()
        by_idx = {e["idx"]: e for e in m["refinement"]["points"]}
        for i in range(26, 36):
            assert by_idx[i]["n_charge_cells"] == 0, i
            hist = by_idx[i]["share_ladder_histogram"]
            assert not (len(hist) == 1 and "0.0000" in hist
                        and hist["0.0000"] == pytest.approx(1.0)), i

    def test_idx_36_to_40_charge_cells_positive(self):
        m = _load_manifest()
        by_idx = {e["idx"]: e for e in m["refinement"]["points"]}
        for i in range(36, 41):
            assert by_idx[i]["n_charge_cells"] > 0, i

    def test_idx_40_policy_sha_matches_sdp_policy_v2(self):
        m = _load_manifest()
        by_idx = {e["idx"]: e for e in m["refinement"]["points"]}
        v2_path = os.path.join(REPO_ROOT, "tools", "sdp_policies",
                               "sdp_policy_v2.json")
        with open(v2_path, encoding="utf-8") as f:
            v2 = json.load(f)
        expected = hashlib.sha256(
            json.dumps(v2["policy"], sort_keys=True).encode("utf-8")).hexdigest()
        assert by_idx[40]["policy_sha256"] == expected


# ---------------------------------------------------------------------------
# cmd_solve preserves an existing refinement block
# ---------------------------------------------------------------------------

def _cmd_solve_fixture(tmp_path, monkeypatch, gamma=0.95):
    """Common setup for the cmd_solve/refinement-identity tests below: a fake
    SWEEP_DIR/MANIFEST_PATH and a stub solver that always reports `gamma`, so
    the caller controls whether a stamped identity matches a fresh solve's."""
    fake_sweep_dir = str(tmp_path / "sweep_dir")
    os.makedirs(fake_sweep_dir, exist_ok=True)
    monkeypatch.setattr(sweep, "SWEEP_DIR", fake_sweep_dir)
    monkeypatch.setattr(sweep, "MANIFEST_PATH",
                        os.path.join(fake_sweep_dir, "manifest.json"))

    win_model, win_meas = sweep._windows_from_anchor()

    class _StubSolver(object):
        @staticmethod
        def main(argv):
            out_path = argv[argv.index("--out") + 1]
            alpha = float(argv[argv.index("--alpha") + 1])
            doc = {
                "alpha": {"value": alpha, "mode": "explicit", "admission": {
                    "window_model": list(win_model),
                    "window_measured": list(win_meas)}},
                "solver": {"converged": True, "iterations": 1,
                          "final_delta": 1e-13},
                "actions": {"charge_forbidden_bins": []},
                "policy": {"share": [[0.0]], "charge_goal": [[0]]},
                "gamma": gamma,
            }
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(doc, f)
            return 0

    monkeypatch.setattr(sweep, "_import_solver", lambda: _StubSolver)
    return fake_sweep_dir, os.path.join(fake_sweep_dir, "manifest.json")


def _fresh_solve_identity(gamma):
    """The `solver_identity` a stub solve with this `gamma` will produce --
    tpm_sha256 is read from the REAL repo TPM file, same as cmd_solve does."""
    tpm_abs = os.path.join(REPO_ROOT,
                           "references/EMS/generated/TPM_dt1_hil.mat")
    return sweep.solver_identity(sweep.sha256_file(tpm_abs), gamma)


class _ArgsNoForce(object):
    force = False
    only = None


class _ArgsForce(object):
    force = True
    only = None


def test_cmd_solve_preserves_refinement_with_matching_identity(
        tmp_path, monkeypatch):
    fake_sweep_dir, manifest_path = _cmd_solve_fixture(
        tmp_path, monkeypatch, gamma=0.95)
    rc = sweep.cmd_solve(_ArgsNoForce())
    assert rc == 0

    # Stamp a refinement block whose identity matches THIS solve's (gamma
    # 0.95, same demand map, the same real TPM file cmd_solve itself hashes).
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["refinement"] = {"purpose": "sentinel", "points": [],
                              "identity": _fresh_solve_identity(0.95)}
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f)

    # Re-solving under the SAME identity (--force, same stub gamma) must
    # preserve the block.
    rc2 = sweep.cmd_solve(_ArgsForce())
    assert rc2 == 0
    with open(manifest_path, encoding="utf-8") as f:
        manifest2 = json.load(f)
    assert manifest2.get("refinement", {}).get("purpose") == "sentinel"


@pytest.mark.parametrize("stamp_identity", [False, True])
def test_cmd_solve_drops_refinement_with_missing_or_mismatched_identity(
        tmp_path, monkeypatch, capsys, stamp_identity):
    fake_sweep_dir, manifest_path = _cmd_solve_fixture(
        tmp_path, monkeypatch, gamma=0.95)
    rc = sweep.cmd_solve(_ArgsNoForce())
    assert rc == 0

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    block = {"purpose": "sentinel", "points": []}
    if stamp_identity:
        # Mismatched: a different gamma than the fresh re-solve below uses.
        block["identity"] = _fresh_solve_identity(0.50)
    # else: no "identity" key at all -- the "unstamped block" case.
    manifest["refinement"] = block
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f)

    # Re-solve under gamma 0.95 again (fixture's stub always reports 0.95),
    # so an identity stamped for gamma 0.50 mismatches, and a missing
    # identity has nothing to match at all -- both must be DROPPED.
    rc2 = sweep.cmd_solve(_ArgsForce())
    assert rc2 == 0
    with open(manifest_path, encoding="utf-8") as f:
        manifest2 = json.load(f)
    assert "refinement" not in manifest2 or manifest2["refinement"] is None
    if stamp_identity:
        assert "WARNING" in capsys.readouterr().err


def test_build_manifest_refinement_none_omits_key():
    entries = [{"idx": 0, "alpha": 0.05}]
    manifest = sweep.build_manifest(
        entries, "path", "sha", 0.95, {"verdict": "MATCH"}, refinement=None)
    assert "refinement" not in manifest


def test_build_manifest_refinement_present_included_verbatim():
    entries = [{"idx": 0, "alpha": 0.05}]
    ref = {"purpose": "x", "points": [1, 2, 3]}
    manifest = sweep.build_manifest(
        entries, "path", "sha", 0.95, {"verdict": "MATCH"}, refinement=ref)
    assert manifest["refinement"] is ref


# ---------------------------------------------------------------------------
# evaluation_rows origin defaults / --include
# ---------------------------------------------------------------------------

def test_evaluation_rows_origin_defaults_to_original():
    grid = sweep.build_grid()
    anchor_idx = [p["idx"] for p in grid if p["is_anchor"]][0]
    results = {p["idx"]: (p, _FakeResult(0.01, 0.0095, -0.001, {}, []))
              for p in grid}
    rows = sweep.evaluation_rows(results, anchor_idx)
    assert all(r["origin"] == "original" for r in rows)
    assert all(r["boundary"] == "" and r["side"] == "" for r in rows)


def test_evaluation_rows_origin_refined_from_point_dict():
    point = {"idx": 21, "alpha": 0.1, "is_anchor": False, "origin": "refined",
            "boundary": "degeneracy", "side": "below"}
    results = {21: (point, _FakeResult(0.01, 0.0095, -0.001, {}, []))}
    rows = sweep.evaluation_rows(results, 21)
    assert rows[0]["origin"] == "refined"
    assert rows[0]["boundary"] == "degeneracy"
    assert rows[0]["side"] == "below"


def test_evaluation_rows_dsoc_ref_override_prices_refined_like_all():
    """MED-2: a table with no anchor of its own (the refined-only selection)
    must be priced against the SAME dSoC reference as the combined ("all")
    table, via the explicit `dsoc_ref` override -- not against its own
    lowest-index row's dSoC, which would make the two tables' eq-H2 columns
    incomparable. Pin: idx 26's eq-H2 is IDENTICAL whether it is walked as
    part of the refined-only results dict or the combined one, given the
    same anchor-derived dsoc_ref passed explicitly to both calls."""
    grid = sweep.build_grid() + sweep.build_refined_grid(
        {"degeneracy": 0.111, "charge": 0.239}, idx_start=21)
    anchor_idx = [p["idx"] for p in grid if p["is_anchor"]][0]
    anchor_dsoc = -0.00234  # the anchor's own dSoC (walked once, externally)

    def _mk(idx, alpha, h2_g, dsoc):
        return _FakeResult(h2_g, h2_g * 0.95, dsoc, {}, [])

    all_results = {p["idx"]: (p, _mk(p["idx"], p["alpha"], 0.012, -0.0019))
                   for p in grid}
    refined_only = {p["idx"]: (p, _mk(p["idx"], p["alpha"], 0.012, -0.0019))
                    for p in grid if p["idx"] >= 21}
    assert 26 in refined_only and 26 in all_results

    # The "all" table has its own anchor, so dsoc_ref is implicit there.
    rows_all = sweep.evaluation_rows(all_results, anchor_idx, anchor_dsoc)
    # The "refined" table has NO anchor point of its own; it must be passed
    # the SAME anchor_dsoc explicitly (as cmd_evaluate's MED-2 fix does).
    refined_ref_idx = min(refined_only)
    rows_refined = sweep.evaluation_rows(refined_only, refined_ref_idx,
                                         anchor_dsoc)

    eq_h2_all_26 = [r["eq_h2_g"] for r in rows_all if r["idx"] == 26][0]
    eq_h2_refined_26 = [r["eq_h2_g"] for r in rows_refined
                        if r["idx"] == 26][0]
    assert eq_h2_all_26 == pytest.approx(eq_h2_refined_26, abs=1e-15)
    # And both equal the hand-computed value against the shared reference.
    expected = sweep.eq_h2(0.012, -0.0019, anchor_dsoc)
    assert eq_h2_all_26 == pytest.approx(expected, abs=1e-15)


def test_evaluation_rows_dsoc_ref_none_falls_back_to_anchor_own_delta_soc():
    """Without an explicit dsoc_ref (the default, `None`), evaluation_rows
    keeps its original behaviour: price against results[anchor_idx]'s own
    delta_soc."""
    grid = sweep.build_grid()
    anchor_idx = [p["idx"] for p in grid if p["is_anchor"]][0]
    results = {p["idx"]: (p, _FakeResult(0.01, 0.0095, -0.001 - 1e-5 * p["idx"],
                                         {}, []))
              for p in grid}
    rows = sweep.evaluation_rows(results, anchor_idx)
    anchor_row = [r for r in rows if r["idx"] == anchor_idx][0]
    assert anchor_row["eq_h2_g"] == pytest.approx(
        results[anchor_idx][1].h2_g, abs=1e-15)


def test_emit_eval_suffix_filenames(tmp_path):
    rows = [{"idx": 0, "alpha": 0.1, "is_anchor": True, "h2_g": 0.01,
             "delta_soc": -0.001, "soc_final": 0.699, "eq_h2_g": 0.01,
             "charge_windows": 0, "mode_fractions": "{}", "origin": "original",
             "boundary": "", "side": ""}]
    out_dir = str(tmp_path / "out")
    os.makedirs(out_dir, exist_ok=True)
    sweep._emit_eval(out_dir, "ems-sdp", rows, suffix="refined_")
    assert os.path.isfile(os.path.join(out_dir, "sweep_eval_refined_ems-sdp.csv"))
    assert os.path.isfile(os.path.join(out_dir, "sweep_eval_refined_ems-sdp.md"))
    assert os.path.isfile(
        os.path.join(out_dir, "sweep_h2_vs_dsoc_refined_ems-sdp.png"))


# ---------------------------------------------------------------------------
# HIL_CSV_COLUMNS vs the live simulated hi-fi header (hil_plant_sim.py)
# ---------------------------------------------------------------------------

def _derive_simulated_header(electrical_hifi):
    """Reconstruct a simulated (non-replay) CSV header order directly from
    tools/hil_plant_sim.py's source text, rather than copying the sweep
    module's own HIL_CSV_COLUMNS list back at itself. This walks the
    `header_row = [...]` / `.append(...)` / `+= [...]` statements inside
    main()'s `if args.csv:` block in file order, dropping the `if replay:`
    branch (never taken for a simulated run) and either keeping or dropping
    the `elec_substep_hz`/`elec_events` pair depending on `electrical_hifi`
    (True: --electrical hifi, so `electrical is not None`; False: the
    --electrical=simple default, `electrical is None`).
    """
    import re
    sim_path = os.path.join(REPO_ROOT, "tools", "hil_plant_sim.py")
    with open(sim_path, encoding="utf-8") as f:
        text = f.read()

    header_start = text.index("header_row = [")
    tail = text.index("writer.writerow(header_row)", header_start)
    block = text[header_start:tail]

    # A simulated run is never `--replay`, so `replay` is falsy.  Drop the
    # ENTIRE `if replay: ... else:` branch's if-side (it duplicates
    # cmd_v_sp/cmd_share_sp under a different guard, which would double-count
    # them if only the "replay_rec" line were skipped) by cutting the text
    # between "if replay:" and the following "else:" out of the block.
    if_replay = block.index("if replay:")
    else_at = block.index("else:", if_replay)
    block = block[:if_replay] + block[else_at + len("else:"):]

    cols = []
    for line in block.splitlines():
        if not electrical_hifi and ('"elec_substep_hz"' in line
                                    or '"elec_events"' in line):
            continue  # electrical-is-not-None-only branch
        for m in re.finditer(r'"([A-Za-z0-9_]+)"', line):
            cols.append(m.group(1))
    return cols


def _derive_simulated_default_header():
    return _derive_simulated_header(electrical_hifi=False)


def test_hil_csv_columns_omits_elec_columns_for_default_electrical_mode():
    """HIL_CSV_COLUMNS carries `elec_substep_hz`/`elec_events` unconditionally,
    but the live header only emits that pair under `--electrical hifi`
    (`electrical is not None`); the default `--electrical simple` run
    (`electrical is None`, hil_plant_sim.py's own default) omits them. This
    is therefore a REAL, independent mismatch against the default mode --
    not the xfail below, which is about the hifi-mode comparison."""
    default_header = _derive_simulated_header(electrical_hifi=False)
    assert "elec_substep_hz" not in default_header
    assert "elec_events" not in default_header
    assert "elec_substep_hz" in sweep.HIL_CSV_COLUMNS
    assert "elec_events" in sweep.HIL_CSV_COLUMNS


def test_hil_csv_columns_matches_the_hifi_simulated_header_exactly():
    """HIL_CSV_COLUMNS carries elec_substep_hz/elec_events unconditionally,
    which matches the `--electrical hifi` header shape (not the default
    `simple` one -- see the test above), so that is the correct live header
    to compare HIL_CSV_COLUMNS against.

    WAS AN XFAIL (2026-09-01f): the live header had grown a six-column
    power-balance tail the list did not carry.  The list was brought current
    with that tail and with `p_chg_loss_w`, appended by the charger-efficiency
    round, so the comparison is now EXACT and a future append fails here
    rather than being tolerated."""
    derived = _derive_simulated_header(electrical_hifi=True)
    assert derived == sweep.HIL_CSV_COLUMNS


def test_hil_csv_columns_prefix_matches_derived_hifi_header():
    """Independent of the xfail above: whatever the derived hifi header's
    extra tail is, HIL_CSV_COLUMNS must be an exact PREFIX of it (no
    reordering, no missing interior column) -- so a future column insertion
    in the middle of the schema is a real defect, not something this prefix
    check silently tolerates."""
    derived = _derive_simulated_header(electrical_hifi=True)
    n = len(sweep.HIL_CSV_COLUMNS)
    assert derived[:n] == sweep.HIL_CSV_COLUMNS, (
        "HIL_CSV_COLUMNS diverges from the live hifi header before its own "
        "length, not just at the tail: derived=%r" % derived)


# ---------------------------------------------------------------------------
# synthesize_hil_csv round-trip
# ---------------------------------------------------------------------------

class _FakeSimModule(object):
    SW_FC_BUS = 0x01
    SW_MOT_PWR = 0x02
    SW_BT_SEQ = 0x04
    SW_BT_BUS = 0x08
    SW_FC_CHARGE = 0x10
    AG105_ST_CHARGING = 0x01
    AG105_FLAG_CC = 0x02
    AG105_ST_DISCONNECT = 0x00
    AUX_FC_REG = 0x01
    AUX_BT_REG = 0x02

    @staticmethod
    def piecewise(prof, t):
        return 1.5


class _FakeTraceResult(object):
    def __init__(self, n):
        self.t = [0.02 * k for k in range(n)]
        self.soc = [0.7 - 0.0001 * k for k in range(n)]
        self.i_fc = [1.0 + 0.01 * k for k in range(n)]
        self.i_batt = [0.5] * n
        self.v_bus = [16.0] * n
        self.i_charge = [0.2 if k % 3 == 0 else 0.0 for k in range(n)]
        self.p_fc_bus_w = [20.0] * n
        self.h2_cum_g = [1e-5 * k for k in range(n)]
        self.sw_fc_charge = [1 if k % 3 == 0 else 0 for k in range(n)]
        self.mdac_fc = [100 + k for k in range(n)]
        self.mdac_bt = [None if k % 4 == 0 else 200 + k for k in range(n)]
        self.share_cmd = [0.85] * n


def test_synthesize_hil_csv_raises_without_trace(tmp_path):
    empty = _FakeTraceResult(0)
    empty.t = []
    with pytest.raises(ValueError):
        sweep.synthesize_hil_csv(str(tmp_path / "x.csv"), empty,
                                 _FakeSimModule, {}, 0.02)


def test_synthesize_hil_csv_switch_word_and_ag105_status(tmp_path):
    n = 6
    r = _FakeTraceResult(n)
    csv_path = str(tmp_path / "trace.csv")
    rows_written = sweep.synthesize_hil_csv(csv_path, r, _FakeSimModule,
                                             {"ems_v_profile": [(0.0, 0.0)]}, 0.02)
    assert rows_written == n

    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    assert header == sweep.HIL_CSV_COLUMNS
    assert len(rows) == n

    idx = {name: i for i, name in enumerate(header)}
    F = _FakeSimModule
    for k, row in enumerate(rows):
        fc_charge = bool(r.sw_fc_charge[k])
        switch = int(row[idx["switch"]])
        expected_base = F.SW_FC_BUS | F.SW_MOT_PWR | F.SW_BT_SEQ
        if fc_charge:
            assert switch & F.SW_FC_CHARGE
            assert not (switch & F.SW_BT_BUS)
        else:
            assert switch & F.SW_BT_BUS
            assert not (switch & F.SW_FC_CHARGE)
        assert switch & expected_base == expected_base

        status = int(row[idx["ag105_status"]], 16)
        if fc_charge:
            assert status == (F.AG105_ST_CHARGING | F.AG105_FLAG_CC)
        else:
            assert status == F.AG105_ST_DISCONNECT

        # Blank columns read back as blank strings here, and NaN once loaded
        # through hil_report_analysis (covered by the round-trip test below).
        for col in ("V_fc", "V_batt", "V_chg", "V_rgn", "current"):
            assert row[idx[col]] == ""

        # mdac_bt is None on every k % 4 == 0 stage -> blank column.
        if r.mdac_bt[k] is None:
            assert row[idx["mdac_bt"]] == ""
        else:
            assert row[idx["mdac_bt"]] == str(r.mdac_bt[k])


@pytest.mark.skipif(not HAVE_ANCHOR, reason="numpy / hil deps not confirmed present")
def test_synthesize_hil_csv_round_trips_through_hil_report_analysis(tmp_path):
    pytest.importorskip("numpy")
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)
    try:
        import hil_plant_sim as real_sim
        import hil_report_analysis as hra
    except ImportError as exc:
        pytest.skip("hil_plant_sim/hil_report_analysis not importable: %s" % exc)

    n = 5
    r = _FakeTraceResult(n)
    csv_path = str(tmp_path / "trace.csv")
    sweep.synthesize_hil_csv(csv_path, r, real_sim, {}, 0.02)

    hil = hra.load_hil_csv(csv_path)
    hil = hra.attach_derived(hil)
    data = hra.adapt_to_benchlog(hil)
    # Round-trip did not raise, and blank numeric columns came back as NaN.
    assert data is not None
    v_fc = hil.get("V_fc")
    if v_fc is not None:
        assert all(np.isnan(x) for x in np.atleast_1d(v_fc))


# ---------------------------------------------------------------------------
# Plot files exist under docs/modeling/sdp_alpha_sweep_20260901/plots/
# ---------------------------------------------------------------------------

PLOTS_ROOT = os.path.join(REPO_ROOT, "docs", "modeling",
                          "sdp_alpha_sweep_20260901", "plots")


def _plot_filenames():
    """The PNG basenames render_walk_figures writes, derived from
    sweep.PLOT_BUILDERS rather than hardcoded -- so a rename of the builder
    key (e.g. to "walk_currents_and_share") is picked up automatically
    instead of silently going stale."""
    prefix = getattr(sweep, "PLOT_PREFIX", "")
    return ["%s%s.png" % (prefix, name) for name in sweep.PLOT_BUILDERS]


@pytest.mark.skipif(not os.path.isdir(os.path.join(PLOTS_ROOT, "ems-sdp")),
                    reason="plots/ems-sdp/ not present")
def test_plot_files_exist_for_every_ems_sdp_point():
    scenario_dir = os.path.join(PLOTS_ROOT, "ems-sdp")
    grid = sweep.all_points("all")
    filenames = _plot_filenames()
    missing = []
    for point in grid:
        pdir = os.path.join(scenario_dir, sweep.plot_dir_name(point))
        if not os.path.isdir(pdir):
            missing.append(pdir)
            continue
        for fn in filenames:
            if not os.path.isfile(os.path.join(pdir, fn)):
                missing.append(os.path.join(pdir, fn))
        if not os.path.isfile(os.path.join(pdir, "walk_trace.csv")):
            missing.append(os.path.join(pdir, "walk_trace.csv"))
    assert not missing, "missing plot artifacts: %r" % missing[:10]


def test_plot_files_exist_for_ems_ftp75_sdp_points_present_on_disk():
    """The implementer may concurrently be re-rendering this folder, so this
    checks only the point directories that ACTUALLY EXIST on disk right now
    (never asserting existence of the folder itself, unlike the ems-sdp test
    above, which is the fully-rendered reference scenario) -- a mid-render
    scenario must not fail this test, but any directory that IS present must
    be complete."""
    scenario_dir = os.path.join(PLOTS_ROOT, "ems-ftp75-sdp")
    if not os.path.isdir(scenario_dir):
        pytest.skip("plots/ems-ftp75-sdp/ not present")
    filenames = _plot_filenames()
    missing = []
    checked = 0
    for entry in sorted(os.listdir(scenario_dir)):
        pdir = os.path.join(scenario_dir, entry)
        if not os.path.isdir(pdir):
            continue
        checked += 1
        for fn in filenames:
            if not os.path.isfile(os.path.join(pdir, fn)):
                missing.append(os.path.join(pdir, fn))
        if not os.path.isfile(os.path.join(pdir, "walk_trace.csv")):
            missing.append(os.path.join(pdir, "walk_trace.csv"))
    assert checked > 0, "expected at least one rendered point directory"
    assert not missing, "missing plot artifacts: %r" % missing[:10]


@pytest.mark.skipif(not os.path.isdir(PLOTS_ROOT), reason="plots/ not present")
def test_plot_run_name_carries_provenance_markers():
    point = {"idx": 5, "alpha": 0.094215}
    name = sweep.plot_run_name(point, "ems-sdp")
    assert "OFFLINE GOVERNOR WALK" in name
    assert "not a board run" in name


# ---------------------------------------------------------------------------
# Doc image links resolve
# ---------------------------------------------------------------------------

DOC_PATH = os.path.join(REPO_ROOT, "docs", "modeling",
                        "sdp_alpha_sweep_20260901.md")


@pytest.mark.skipif(not os.path.isfile(DOC_PATH),
                    reason="sdp_alpha_sweep_20260901.md not present")
def test_doc_image_links_all_resolve():
    import re
    with open(DOC_PATH, encoding="utf-8") as f:
        text = f.read()
    doc_dir = os.path.dirname(DOC_PATH)
    links = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    assert links, "expected at least one image link in the doc"
    missing = []
    for link in links:
        target = link.split("#", 1)[0].split("?", 1)[0]
        full = os.path.normpath(os.path.join(doc_dir, target))
        if not os.path.isfile(full):
            missing.append(link)
    assert not missing, "unresolved image links: %r" % missing


# ==========================================================================
# 2026-09-01 charger-efficiency round (WP-1B1): the sweep's charger era.
# ==========================================================================

def test_sweep_default_era_is_the_old_one_so_the_shipped_folder_reproduces():
    assert sweep.SWEEP_ETA_CHG_DEFAULT is None
    argv = sweep.solver_argv({"alpha": 0.2, "idx": 0, "is_anchor": False},
                             "out.json", False, True, True, None)
    assert "--eta-chg-none" in argv
    assert "--eta-chg" not in argv


def test_sweep_solver_argv_carries_an_explicit_era_in_both_directions():
    """Neither direction may be left to the solver's own default: the solver
    defaults to the plant's efficiency, and a sweep that inherited it would
    change era with an edit to another file."""
    argv = sweep.solver_argv({"alpha": 0.2, "idx": 0, "is_anchor": False},
                             "out.json", True, False, False, 0.88)
    assert "--eta-chg" in argv
    assert argv[argv.index("--eta-chg") + 1] == repr(0.88)
    assert "--eta-chg-none" not in argv
    assert "--allow-out-of-window" in argv       # out of window, both


def test_windows_for_era_old_matches_the_anchor_and_new_is_recomputed():
    old = sweep.windows_for_era(None)
    assert old == sweep._windows_from_anchor()
    new_model, new_meas = sweep.windows_for_era(0.88)
    assert new_model is not None and new_model[1] < old[0][1]
    # The measured pair does not order in the eta era - reported as None, and
    # `_in_window` reads that conservatively as "not inside".
    assert new_meas is None
    assert sweep._in_window(None, 0.12) is False


def test_manifest_records_the_charger_era():
    m = sweep.build_manifest([], "tpm.mat", "sha", {"effective": 0.95},
                             {"verdict": "x"})
    assert m["eta_chg"] is None
    m88 = sweep.build_manifest([], "tpm.mat", "sha", {"effective": 0.95},
                               {"verdict": "x"}, eta_chg=0.88)
    assert m88["eta_chg"] == 0.88


def test_shipped_sweep_manifest_is_old_era():
    """sweep_20260901/ predates the field; its ABSENCE reads as the old era
    and nothing regenerates it."""
    if not os.path.isfile(sweep.MANIFEST_PATH):
        pytest.skip("sweep folder not present in this checkout")
    m = json.load(open(sweep.MANIFEST_PATH, encoding="utf-8"))
    assert m.get("eta_chg") is None
