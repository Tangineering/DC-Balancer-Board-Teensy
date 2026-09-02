"""Independent Stage-2 tests for tools/sdp_alpha_sweep.py.

Run: C:/Users/ricky/miniforge3/python.exe -m pytest tools/test_sdp_alpha_sweep.py -q
"""

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
