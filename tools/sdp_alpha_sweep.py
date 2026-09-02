#!/usr/bin/env python
"""SDP alpha sweep: solve, catalogue, and offline-evaluate a grid of policies.

The stochastic-DP EMS objective weights the SoC-deviation term by `alpha`.  The
full-scale study of `references/EMS/SDP_EnergyManagement2.m` swept
alpha in [100, 1000].  The Round-B coulombic-energy scaling factor between the
full-size pack and this rig is 5.138889e-4 (500 -> 0.2569444), so the
corresponding bench range is [0.0514, 0.514].  This tool solves 20 log-spaced
points over that range, plus the shipped lever-calibrated alpha of
`tools/sdp_policies/sdp_policy_v3.json` as a flagged anchor point.

The artifacts are OFFLINE-evaluation artifacts.  `sdp_assert_calibrated_benchmark()`
in `tools/hil_plant_sim.py` refuses an out-of-window artifact for the
frontier-scored `sdp-v3` strategy, so a sweep point may only reach the board
through a non-certified strategy binding.

Subcommands:
  grid      print the 21-point grid
  solve     solve every point and write the artifacts plus manifest.json
  evaluate  offline-walk every point through tools/ems_walk.py

The module keeps the grid, manifest, and evaluation-table construction as pure
functions so a test can drive them without a solve.
"""

import argparse
import contextlib
import csv
import datetime
import hashlib
import io
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)

SWEEP_SCHEMA = "sdp-alpha-sweep-v1"
SWEEP_DIR = os.path.join(_HERE, "sdp_policies", "sweep_20260901")
ANCHOR_ARTIFACT = os.path.join(_HERE, "sdp_policies", "sdp_policy_v3.json")

# The full-scale study's alpha range (SDP_EnergyManagement2.m).
FULL_SCALE_ALPHA_RANGE = (100.0, 1000.0)
# Round-B coulombic-energy scaling: 500 -> 0.2569444 (see sdp_ems_solver.py's
# ALPHA_DERIVATION).  Applied to both ends of the full-scale range.
COULOMBIC_SCALE = 0.2569444444 / 500.0
ALPHA_LO = 0.0514
ALPHA_HI = 0.514
N_LOG_POINTS = 20
# The shipped v3 alpha (lever calibration, D12), carried as the anchor point.
ANCHOR_ALPHA = 0.1629624189805737

# The demand map every sweep point is solved against: the consumer-owned
# rig-scale map (D11), which is also the solver default.
DEMAND_MAP_W = (0.0, 25.0)

# The strategy the sweep artifacts are walked through.  The decision code is
# one class (SdpStrategy, hil_plant_sim.py:4188); the NAME selects the role.
# `sdp-v3` is the frontier-scored CALIBRATED BENCHMARK, and its loader
# (sdp_assert_calibrated_benchmark, hil_plant_sim.py:4103) refuses any artifact
# whose alpha.mode is not "lever" or which lies outside an admission window.
# Every sweep artifact is solved with an EXPLICIT alpha, so every one of them
# fails that certificate by construction - including the anchor.  The sweep
# therefore binds the NON-frontier `sdp-v2` role, which the same refusal text
# names as the correct destination for an uncertified artifact.
EVAL_STRATEGY = "sdp-v2"

# tools/run_hil_suite.py:6497.  Reimplemented, not imported: importing the
# suite runner pulls its whole scenario registry into an offline tool.
EQ_H2_LAMBDA_SOC_PER_G = 0.41


# ---------------------------------------------------------------------------
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def policy_sha256(doc):
    """The consumer's policy identity (hil_plant_sim.py:4063-4080).

    The digest covers the `policy` block ALONE, so it is invariant to
    generated_utc, argv, and the alpha provenance block.
    """
    return hashlib.sha256(
        json.dumps(doc["policy"], sort_keys=True).encode("utf-8")).hexdigest()


def eq_h2(h2_g, delta_soc, delta_soc_ref, lam=EQ_H2_LAMBDA_SOC_PER_G):
    """SoC-corrected hydrogen (run_hil_suite.ems_eq_h2, one line, reimplemented)."""
    return float(h2_g) - (float(delta_soc) - float(delta_soc_ref)) / float(lam)


# ---------------------------------------------------------------------------
def build_grid(alpha_lo=ALPHA_LO, alpha_hi=ALPHA_HI, n=N_LOG_POINTS,
               anchor=ANCHOR_ALPHA):
    """The sweep grid, ascending in alpha, indices assigned after the sort.

    Returns a list of dicts with keys idx, alpha, is_anchor.  The anchor is an
    additional point, never a replacement for a log-spaced one, so removing it
    leaves the geomspace grid intact.
    """
    import numpy as np
    values = [(float(a), False)
              for a in np.geomspace(alpha_lo, alpha_hi, n)]
    if anchor is not None:
        values.append((float(anchor), True))
    values.sort(key=lambda t: (t[0], not t[1]))
    return [{"idx": i, "alpha": a, "is_anchor": is_anchor}
            for i, (a, is_anchor) in enumerate(values)]


def _import_solver():
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)
    import sdp_ems_solver
    return sdp_ems_solver


def window_flags(alpha, doc):
    """in_window_{model,measured} for `alpha`, read from a solved artifact.

    The artifact records both windows, so the flags never have to be recomputed
    from a second copy of the lever constants.
    """
    adm = doc["alpha"]["admission"]
    wm = adm["window_model"]
    ws = adm["window_measured"]
    return (wm[0] < alpha < wm[1], ws[0] < alpha < ws[1])


def _windows_from_anchor():
    """The two admission windows, taken from the shipped v3 artifact."""
    with open(ANCHOR_ARTIFACT, "r", encoding="utf-8") as f:
        doc = json.load(f)
    adm = doc["alpha"]["admission"]
    return tuple(adm["window_model"]), tuple(adm["window_measured"])


def point_filename(point):
    return "alpha_%02d_%.6f.json" % (point["idx"], point["alpha"])


# ---------------------------------------------------------------------------
def share_histogram(policy_share):
    """Fraction of policy cells at each distinct share value, as a dict."""
    counts = {}
    total = 0
    for row in policy_share:
        for v in row:
            key = "%.4f" % float(v)
            counts[key] = counts.get(key, 0) + 1
            total += 1
    if total == 0:
        return {}
    return {k: counts[k] / float(total) for k in sorted(counts)}


def summarize_artifact(path, point, wall_s):
    """One manifest entry for a solved artifact.  Pure given the file."""
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    in_model, in_meas = window_flags(point["alpha"], doc)
    charge = doc["policy"]["charge_goal"]
    n_charge = sum(1 for row in charge for v in row if float(v) > 0.0)
    return {
        "idx": point["idx"],
        "alpha": point["alpha"],
        "is_anchor": bool(point["is_anchor"]),
        "in_window_model": bool(in_model),
        "in_window_measured": bool(in_meas),
        "file": os.path.relpath(path, REPO_ROOT).replace("\\", "/"),
        "file_sha256": sha256_file(path),
        "policy_sha256": policy_sha256(doc),
        "converged": bool(doc["solver"]["converged"]),
        "iterations": int(doc["solver"]["iterations"]),
        "final_delta": float(doc["solver"]["final_delta"]),
        "n_charge_cells": int(n_charge),
        "charge_forbidden_bins": list(doc["actions"]["charge_forbidden_bins"]),
        "share_ladder_histogram": share_histogram(doc["policy"]["share"]),
        "alpha_value_recorded": float(doc["alpha"]["value"]),
        "alpha_mode_recorded": doc["alpha"]["mode"],
        # None, not NaN, for a point that was not re-solved this run: NaN is
        # not valid JSON and json.dump emits it unquoted.
        "wall_s": None if wall_s is None else float(wall_s),
    }


def build_manifest(entries, tpm_path, tpm_sha, gamma, anchor_check):
    return {
        "schema": SWEEP_SCHEMA,
        "generated_utc": datetime.datetime.now(datetime.timezone.utc)
                                 .isoformat().replace("+00:00", "Z"),
        "tool": "tools/sdp_alpha_sweep.py",
        "purpose": "WORK_QUEUE section 1 item 3: an alpha sweep for the "
                   "operator to choose three live-run points from. These are "
                   "OFFLINE-evaluation artifacts; the frontier-scored sdp-v3 "
                   "strategy refuses an out-of-window artifact.",
        "alpha_range": {
            "full_scale": list(FULL_SCALE_ALPHA_RANGE),
            "coulombic_scale": COULOMBIC_SCALE,
            "bench": [ALPHA_LO, ALPHA_HI],
            "n_log_points": N_LOG_POINTS,
            "anchor": ANCHOR_ALPHA,
            "spacing": "numpy.geomspace, endpoints inclusive",
        },
        "tpm": {"path": tpm_path, "sha256": tpm_sha},
        "demand_map_w": list(DEMAND_MAP_W),
        "gamma": gamma,
        "anchor_check": anchor_check,
        "points": entries,
    }


def _atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
def solver_argv(point, out_path, force, in_model, in_meas):
    """The solver CLI arguments for one sweep point.

    An EXPLICIT --alpha sets alpha.value to the requested value exactly and
    records alpha.mode = "explicit" (sdp_ems_solver.py:1092-1096); --alpha-mode
    is then not consulted at all.  --allow-out-of-window is added only where
    the D12 tripwire would otherwise refuse the solve.
    """
    argv = ["--alpha", repr(float(point["alpha"])),
            "--demand-map", repr(DEMAND_MAP_W[0]), repr(DEMAND_MAP_W[1]),
            "--out", out_path]
    if not (in_model and in_meas):
        argv.append("--allow-out-of-window")
    if force:
        argv.append("--force")
    return argv


def cmd_solve(args):
    solver = _import_solver()
    win_model, win_meas = _windows_from_anchor()
    grid = build_grid()
    os.makedirs(SWEEP_DIR, exist_ok=True)

    only = set(args.only or [])
    entries = []
    for point in grid:
        out_path = os.path.join(SWEEP_DIR, point_filename(point))
        in_model = win_model[0] < point["alpha"] < win_model[1]
        in_meas = win_meas[0] < point["alpha"] < win_meas[1]
        if only and point["idx"] not in only:
            if os.path.exists(out_path):
                entries.append(summarize_artifact(out_path, point, None))
            continue
        argv = solver_argv(point, out_path, args.force, in_model, in_meas)
        buf = io.StringIO()
        t0 = time.time()
        with contextlib.redirect_stdout(buf):
            rc = solver.main(argv)
        wall = time.time() - t0
        if rc != 0:
            sys.stderr.write(buf.getvalue())
            print("[sweep] point %02d (alpha %.6f) FAILED, solver rc %s"
                  % (point["idx"], point["alpha"], rc))
            return 1
        entry = summarize_artifact(out_path, point, wall)
        entries.append(entry)
        print("[sweep] %02d alpha %.6f%s  win %s/%s  %d sweeps  "
              "charge cells %d  %.1f s"
              % (point["idx"], point["alpha"],
                 " ANCHOR" if point["is_anchor"] else "       ",
                 "IN" if in_model else "OUT", "IN" if in_meas else "OUT",
                 entry["iterations"], entry["n_charge_cells"], wall))

    anchor_check = check_anchor(entries)
    tpm_rel = "references/EMS/generated/TPM_dt1_hil.mat"
    tpm_abs = os.path.join(REPO_ROOT, tpm_rel)
    with open(os.path.join(SWEEP_DIR, point_filename(grid[0])), "r",
              encoding="utf-8") as f:
        gamma = json.load(f)["gamma"]
    manifest = build_manifest(entries, tpm_rel, sha256_file(tpm_abs), gamma,
                              anchor_check)
    _atomic_write_json(os.path.join(SWEEP_DIR, "manifest.json"), manifest)
    print("[sweep] manifest: %s" % os.path.join(SWEEP_DIR, "manifest.json"))
    print("[sweep] anchor check: %s" % anchor_check["verdict"])
    return 0


def check_anchor(entries):
    """Compare the anchor point's policy digest against the shipped v3 artifact."""
    anchors = [e for e in entries if e["is_anchor"]]
    if not anchors:
        return {"verdict": "NO ANCHOR POINT SOLVED"}
    got = anchors[0]["policy_sha256"]
    with open(ANCHOR_ARTIFACT, "r", encoding="utf-8") as f:
        ref_doc = json.load(f)
    ref = policy_sha256(ref_doc)
    return {
        "anchor_idx": anchors[0]["idx"],
        "anchor_alpha": anchors[0]["alpha"],
        "sweep_policy_sha256": got,
        "sdp_policy_v3_policy_sha256": ref,
        "match": got == ref,
        "verdict": ("MATCH - the anchor reproduces sdp_policy_v3.json's policy "
                    "block" if got == ref else
                    "MISMATCH - the anchor differs from sdp_policy_v3.json; "
                    "compare the TPM, demand map, and grid arguments"),
    }


# ---------------------------------------------------------------------------
def cmd_grid(args):
    win_model, win_meas = _windows_from_anchor()
    print("idx  alpha       in_model  in_meas  anchor")
    for p in build_grid():
        a = p["alpha"]
        print("%3d  %.9f  %-8s  %-7s  %s"
              % (p["idx"], a,
                 win_model[0] < a < win_model[1],
                 win_meas[0] < a < win_meas[1],
                 "ANCHOR" if p["is_anchor"] else ""))
    print("model window (%.6f, %.6f); measured window (%.6f, %.6f)"
          % (win_model + win_meas))
    return 0


# ---------------------------------------------------------------------------
def _load_walk():
    """Lazily import the offline walk.  Absent module is exit code 3."""
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)
    import ems_walk
    return ems_walk.walk


def evaluation_rows(results, anchor_idx):
    """The evaluation table, given {idx: (point, WalkResult)}.

    Pure: takes already-walked results so a test can drive it on synthetic
    WalkResult objects.
    """
    dsoc_ref = float(results[anchor_idx][1].delta_soc)
    rows = []
    for idx in sorted(results):
        point, r = results[idx]
        rows.append({
            "idx": idx,
            "alpha": point["alpha"],
            "is_anchor": bool(point["is_anchor"]),
            "h2_g": float(r.h2_g),
            "h2_proxy_g": float(getattr(r, "h2_proxy_g", float("nan"))),
            "delta_soc": float(r.delta_soc),
            "soc_final": float(r.soc_final),
            "eq_h2_g": eq_h2(r.h2_g, r.delta_soc, dsoc_ref),
            "charge_windows": int(len(r.charge_windows)
                                  if hasattr(r.charge_windows, "__len__")
                                  else r.charge_windows),
            "mode_fractions": json.dumps(dict(r.mode_fractions), sort_keys=True),
        })
    return rows


def write_eval_csv(path, rows):
    fields = ["idx", "alpha", "is_anchor", "h2_g", "h2_proxy_g", "delta_soc",
              "soc_final", "eq_h2_g", "charge_windows", "mode_fractions"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def markdown_table(rows):
    head = ("| idx | alpha | h2 (g) | dSoC | eq-H2 (g) | charge windows |\n"
            "|---:|---:|---:|---:|---:|---:|\n")
    body = "".join(
        "| %d%s | %.6f | %.6g | %+.6f | %.6g | %d |\n"
        % (r["idx"], " (anchor)" if r["is_anchor"] else "", r["alpha"],
           r["h2_g"], r["delta_soc"], r["eq_h2_g"], r["charge_windows"])
        for r in rows)
    return head + body


def write_figure(path, rows):
    """h2 against dSoC across the sweep, alpha annotated."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.0, 5.0))
    xs = [r["delta_soc"] for r in rows]
    ys = [r["h2_g"] for r in rows]
    ax.plot(xs, ys, "-o", color="0.35", markersize=4, linewidth=1.0)
    for r in rows:
        marker = "*" if r["is_anchor"] else None
        if marker:
            ax.plot([r["delta_soc"]], [r["h2_g"]], marker, color="crimson",
                    markersize=14, zorder=5)
        ax.annotate("%.3f" % r["alpha"], (r["delta_soc"], r["h2_g"]),
                    textcoords="offset points", xytext=(4, 4), fontsize=7)
    ax.set_xlabel(r"$\Delta$SoC over the scenario")
    ax.set_ylabel("hydrogen consumed (g, Gfc)")
    ax.set_title("SDP alpha sweep: hydrogen against SoC change")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def cmd_evaluate(args):
    out_dir = args.out or os.path.join(REPO_ROOT, "docs", "modeling",
                                       "sdp_alpha_sweep_20260901")
    os.makedirs(out_dir, exist_ok=True)
    if args.self_test:
        return _self_test(out_dir)
    try:
        walk = _load_walk()
    except ImportError as exc:
        print("[sweep] walk module not available yet (tools/ems_walk.py): %s"
              % exc, file=sys.stderr)
        return 3
    grid = build_grid()
    for scenario in args.scenario:
        results = {}
        anchor_idx = None
        for point in grid:
            pf = os.path.join(SWEEP_DIR, point_filename(point))
            if not os.path.exists(pf):
                print("[sweep] point %02d not solved (%s) - run `solve` first"
                      % (point["idx"], pf), file=sys.stderr)
                return 1
            r = walk(args.strategy, scenario, policy_file=pf)
            results[point["idx"]] = (point, r)
            if point["is_anchor"]:
                anchor_idx = point["idx"]
            print("[sweep] %02d alpha %.6f  h2 %.6g g  dSoC %+.6f"
                  % (point["idx"], point["alpha"], r.h2_g, r.delta_soc))
        rows = evaluation_rows(results, anchor_idx)
        _emit_eval(out_dir, scenario, rows)
    return 0


def _emit_eval(out_dir, scenario, rows):
    csv_path = os.path.join(out_dir, "sweep_eval_%s.csv" % scenario)
    write_eval_csv(csv_path, rows)
    md_path = os.path.join(out_dir, "sweep_eval_%s.md" % scenario)
    with open(md_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# SDP alpha sweep - offline walk, scenario `%s`\n\n"
                "Equivalent hydrogen uses lambda = %.2f SoC/g against the "
                "anchor point's SoC change.\n\n" % (scenario,
                                                    EQ_H2_LAMBDA_SOC_PER_G))
        f.write(markdown_table(rows))
    fig_path = os.path.join(out_dir, "sweep_h2_vs_dsoc_%s.png" % scenario)
    write_figure(fig_path, rows)
    print("[sweep] wrote %s, %s, %s" % (csv_path, md_path, fig_path))


class _FakeWalkResult(object):
    """A stand-in WalkResult, for --self-test only."""

    def __init__(self, alpha):
        self.h2_g = 0.0125 + 0.0002 * alpha
        self.h2_plant_g = self.h2_g
        self.h2_proxy_g = self.h2_g * 0.945
        self.soc_final = 0.7 - 0.002 + 0.001 * alpha
        self.delta_soc = self.soc_final - 0.7
        self.mode_fractions = {"share": 1.0, "charge": 0.0}
        self.share_cmd = [0.85]
        self.share_delivered = [0.85]
        self.charge_windows = []
        self.notes = ["self-test"]


def _self_test(out_dir):
    """Exercise the evaluation path against a fake walk result."""
    grid = build_grid()
    results = {p["idx"]: (p, _FakeWalkResult(p["alpha"])) for p in grid}
    anchor_idx = [p["idx"] for p in grid if p["is_anchor"]][0]
    rows = evaluation_rows(results, anchor_idx)
    _emit_eval(out_dir, "selftest", rows)
    print("[sweep] --self-test: %d rows, anchor idx %d" % (len(rows), anchor_idx))
    return 0


# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("grid", help="print the sweep grid")

    ps = sub.add_parser("solve", help="solve every point")
    ps.add_argument("--force", action="store_true",
                    help="overwrite existing artifacts")
    ps.add_argument("--only", type=int, nargs="+", metavar="IDX",
                    help="solve only these grid indices")

    pe = sub.add_parser("evaluate", help="offline-walk every point")
    pe.add_argument("--scenario", action="append", default=None,
                    help="scenario name (repeatable; default ems-sdp)")
    pe.add_argument("--out", default=None, help="output directory")
    pe.add_argument("--strategy", default=EVAL_STRATEGY,
                    help="strategy binding for the walk (default %s - see "
                         "EVAL_STRATEGY)" % EVAL_STRATEGY)
    pe.add_argument("--self-test", action="store_true",
                    help="exercise the evaluation path on a fake walk result")

    args = ap.parse_args(argv)
    if args.cmd == "grid":
        return cmd_grid(args)
    if args.cmd == "solve":
        return cmd_solve(args)
    if not args.scenario:
        args.scenario = ["ems-sdp"]
    return cmd_evaluate(args)


if __name__ == "__main__":
    sys.exit(main())
