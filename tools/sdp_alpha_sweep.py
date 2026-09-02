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
import pathlib
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
# Refinement (second sweep, 2026-09-01)
#
# The first sweep resolved two behaviour transitions to the width of its own
# log-spaced grid.  The refinement locates each one by bisection through the
# solver and then places five points on each side of it, so both regimes are
# sampled five times within a few percent of the boundary.
#
# The two transitions, each a monotone predicate of alpha:
#   "degeneracy" - below the boundary the solved policy commands share 0.0 in
#                  EVERY cell (pure hydrogen greed); above it the share map is
#                  non-degenerate.  Bracketed by grid points 6 and 7.
#   "charge"     - below the boundary no policy cell selects charge_goal > 0;
#                  above it charging enters.  Bracketed by grid points 13/14.
#
# SPACING RULE: boundary * (1 -/+ d) for d in REFINE_DELTAS.  The deltas are
# geometric (x2 per step), so the five points on a side span one decade of
# distance from the boundary and the pair nearest it sits 0.5 % away - close
# enough that the two neighbours straddling a boundary differ by 1 % in alpha.
# ---------------------------------------------------------------------------
REFINE_DELTAS = (0.005, 0.01, 0.02, 0.04, 0.08)
REFINE_IDX_START = 21
# Bisection brackets, taken from the first sweep's grid (Section 7 of
# docs/modeling/sdp_alpha_sweep_20260901.md).
REFINE_BRACKETS = {
    "degeneracy": (0.106354, 0.120056),
    "charge": (0.220060, 0.248413),
}
REFINE_ORDER = ("degeneracy", "charge")
# Relative width at which the bisection stops, on the log-alpha axis.
BISECT_REL_TOL = 1e-6


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
def policy_is_degenerate(doc):
    """True when the solved share map commands 0.0 in every policy cell."""
    return all(float(v) == 0.0 for row in doc["policy"]["share"] for v in row)


def policy_admits_charge(doc):
    """True when at least one policy cell selects the charge action."""
    return any(float(v) > 0.0
               for row in doc["policy"]["charge_goal"] for v in row)


# The bisection predicate for each boundary, written so that it is FALSE below
# the boundary and TRUE above it.  Both are monotone in alpha over the bracket.
REFINE_PREDICATES = {
    "degeneracy": lambda doc: not policy_is_degenerate(doc),
    "charge": policy_admits_charge,
}


def refined_alphas(boundary_value, deltas=REFINE_DELTAS):
    """The ten refinement alphas for one boundary, ascending.

    Five below at ``b * (1 - d)`` and five above at ``b * (1 + d)``, for the
    geometric deltas.  Pure, so a test can check the spacing without a solve.
    """
    ds = sorted(float(d) for d in deltas)
    below = [boundary_value * (1.0 - d) for d in reversed(ds)]
    above = [boundary_value * (1.0 + d) for d in ds]
    return below + above


def build_refined_grid(boundaries, idx_start=REFINE_IDX_START,
                       deltas=REFINE_DELTAS, order=REFINE_ORDER):
    """The refinement points, given ``{boundary_name: alpha}``.

    Indices run consecutively from ``idx_start`` in ``order``, ascending in
    alpha within each boundary group.  The points are NEVER anchors.
    """
    points, idx = [], int(idx_start)
    for name in order:
        if name not in boundaries:
            continue
        b = float(boundaries[name])
        alphas = refined_alphas(b, deltas)
        for a in alphas:
            points.append({
                "idx": idx,
                "alpha": float(a),
                "is_anchor": False,
                "origin": "refined",
                "boundary": name,
                "boundary_alpha": b,
                "side": "below" if a < b else "above",
                "rel_offset": (a - b) / b,
            })
            idx += 1
    return points


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
    entry = {
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
    # Refinement provenance, present only on a refined point.
    for key in ("origin", "boundary", "boundary_alpha", "side", "rel_offset"):
        if key in point:
            entry[key] = point[key]
    return entry


def build_manifest(entries, tpm_path, tpm_sha, gamma, anchor_check,
                   refinement=None):
    """The sweep manifest.

    ``points`` is the ORIGINAL 21-point grid and stays 21 entries long.
    The second sweep lives in the additive ``refinement`` block, which
    carries the two bisected boundaries, the spacing rule, and its own
    ``points`` list.  Keeping the two lists separate means a consumer
    pinned to the first sweep reads exactly what it read before.
    """
    manifest = {
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
    if refinement is not None:
        manifest["refinement"] = refinement
    return manifest


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
    tpm_sha = sha256_file(tpm_abs)
    refinement = _refinement_if_current(solver_identity(tpm_sha, gamma))
    manifest = build_manifest(entries, tpm_rel, tpm_sha, gamma,
                              anchor_check, refinement=refinement)
    _atomic_write_json(os.path.join(SWEEP_DIR, "manifest.json"), manifest)
    print("[sweep] manifest: %s" % os.path.join(SWEEP_DIR, "manifest.json"))
    print("[sweep] anchor check: %s" % anchor_check["verdict"])
    return 0


# ---------------------------------------------------------------------------
# Refinement: bisect each boundary, then solve the ten points around it
# ---------------------------------------------------------------------------
MANIFEST_PATH = os.path.join(SWEEP_DIR, "manifest.json")


def solver_identity(tpm_sha, gamma):
    """The solver-constants identity a refinement block is stamped with.

    A refinement is only meaningful against the same solver constants the
    original grid was solved with.  Stamping these three lets `cmd_solve`
    detect a re-solve under different constants and drop a refinement that can
    no longer be trusted, instead of silently re-attaching a stale block.
    """
    return {"tpm_sha256": tpm_sha,
            "demand_map_w": list(DEMAND_MAP_W),
            "gamma": gamma}


def load_refinement(path=None, warn=True):
    """The manifest's ``refinement`` block, or None when there is not one."""
    path = path or MANIFEST_PATH
    if not os.path.exists(path):
        if warn:
            print("[sweep] no manifest at %s" % path, file=sys.stderr)
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("refinement")


def refined_grid_from_manifest(path=None):
    """Rebuild the refinement grid from the manifest's recorded boundaries.

    The grid is regenerated from ``build_refined_grid`` rather than read back
    from the stored point list, so the stored boundaries and the spacing rule
    are the only inputs and a hand-edited point list cannot drift.
    """
    ref = load_refinement(path, warn=False)
    if not ref:
        return []
    boundaries = {name: float(b["alpha"])
                  for name, b in ref["boundaries"].items()}
    return build_refined_grid(boundaries,
                              idx_start=int(ref["idx_start"]),
                              deltas=tuple(ref["spacing"]["deltas"]),
                              order=tuple(ref["order"]))


def all_points(include="all"):
    """The sweep points: ``original``, ``refined`` or ``all``."""
    if include == "original":
        return build_grid()
    if include == "refined":
        return refined_grid_from_manifest()
    return build_grid() + refined_grid_from_manifest()


def _probe_solve(solver, alpha, tmp_path):
    """Solve one alpha into a scratch file and return the artifact document."""
    argv = ["--alpha", repr(float(alpha)),
            "--demand-map", repr(DEMAND_MAP_W[0]), repr(DEMAND_MAP_W[1]),
            "--out", tmp_path, "--allow-out-of-window", "--force"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = solver.main(argv)
    if rc != 0:
        sys.stderr.write(buf.getvalue())
        raise RuntimeError("solver failed at alpha %r (rc %s)" % (alpha, rc))
    with open(tmp_path, "r", encoding="utf-8") as f:
        return json.load(f)


def bisect_boundary(solver, name, tmp_path, bracket=None,
                    rel_tol=BISECT_REL_TOL, max_iter=64):
    """Locate one behaviour boundary by bisection on the log-alpha axis.

    The predicate (``REFINE_PREDICATES[name]``) is FALSE below the boundary and
    TRUE above it.  Both bracket ends are verified before the bisection starts,
    so a bracket that does not straddle the boundary is an error rather than a
    silently wrong answer.  The bisection is geometric because the sweep grid
    is, and it stops when ``(hi - lo) / mid`` falls below ``rel_tol``.

    Returns a dict recording the bracket, the solve count, the final interval,
    and the reported boundary (the interval midpoint).
    """
    import math

    pred = REFINE_PREDICATES[name]
    bracket_used = REFINE_BRACKETS[name] if bracket is None else bracket
    lo, hi = float(bracket_used[0]), float(bracket_used[1])
    doc_lo = _probe_solve(solver, lo, tmp_path)
    doc_hi = _probe_solve(solver, hi, tmp_path)
    if pred(doc_lo) or not pred(doc_hi):
        raise RuntimeError(
            "bracket [%r, %r] does not straddle the %r boundary "
            "(predicate lo=%s hi=%s)" % (lo, hi, name,
                                         pred(doc_lo), pred(doc_hi)))
    n = 2
    while (hi - lo) / (0.5 * (lo + hi)) > rel_tol and n < max_iter:
        mid = math.sqrt(lo * hi)
        if pred(_probe_solve(solver, mid, tmp_path)):
            hi = mid
        else:
            lo = mid
        n += 1
    alpha = 0.5 * (lo + hi)
    return {
        "name": name,
        "alpha": float(alpha),
        "interval": [float(lo), float(hi)],
        "half_width": float(0.5 * (hi - lo)),
        "rel_width": float((hi - lo) / alpha),
        "bracket": [float(bracket_used[0]), float(bracket_used[1])],
        "solves": int(n),
        "rel_tol": float(rel_tol),
        "predicate": ("the solved share map is non-degenerate: at least one "
                      "cell commands share > 0" if name == "degeneracy"
                      else "at least one policy cell selects charge_goal > 0"),
        "method": "geometric bisection on log(alpha) through "
                  "sdp_ems_solver.main(); both bracket ends verified first",
    }


def _is_degenerate_entry(entry):
    """Degeneracy read back from a manifest entry's share histogram."""
    return entry["share_ladder_histogram"].get("0.0000", 0.0) == 1.0


def cmd_refine(args):
    solver = _import_solver()
    os.makedirs(SWEEP_DIR, exist_ok=True)
    tmp_path = os.path.join(SWEEP_DIR, "_bisect_probe.json")
    win_model, win_meas = _windows_from_anchor()

    boundaries = {}
    try:
        for name in REFINE_ORDER:
            t0 = time.time()
            b = bisect_boundary(solver, name, tmp_path, rel_tol=args.rel_tol)
            b["wall_s"] = time.time() - t0
            boundaries[name] = b
            print("[refine] %-11s boundary alpha %.9f  (+/- %.2g, %d solves, "
                  "%.1f s)" % (name, b["alpha"], b["half_width"], b["solves"],
                               b["wall_s"]))
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    grid = build_refined_grid({k: v["alpha"] for k, v in boundaries.items()},
                              deltas=REFINE_DELTAS)
    entries = []
    for point in grid:
        out_path = os.path.join(SWEEP_DIR, point_filename(point))
        in_model = win_model[0] < point["alpha"] < win_model[1]
        in_meas = win_meas[0] < point["alpha"] < win_meas[1]
        if args.no_solve and os.path.exists(out_path):
            entries.append(summarize_artifact(out_path, point, None))
            continue
        argv = solver_argv(point, out_path, True, in_model, in_meas)
        buf = io.StringIO()
        t0 = time.time()
        with contextlib.redirect_stdout(buf):
            rc = solver.main(argv)
        wall = time.time() - t0
        if rc != 0:
            sys.stderr.write(buf.getvalue())
            print("[refine] point %02d (alpha %.6f) FAILED, solver rc %s"
                  % (point["idx"], point["alpha"], rc))
            return 1
        entry = summarize_artifact(out_path, point, wall)
        entries.append(entry)
        print("[refine] %02d alpha %.9f  %-10s %-5s  degenerate %-5s  "
              "charge cells %3d  %.1f s"
              % (point["idx"], point["alpha"], point["boundary"],
                 point["side"], str(_is_degenerate_entry(entry)),
                 entry["n_charge_cells"], wall))

    tpm_rel = "references/EMS/generated/TPM_dt1_hil.mat"
    tpm_abs = os.path.join(REPO_ROOT, tpm_rel)
    with open(os.path.join(SWEEP_DIR, point_filename(grid[0])), "r",
              encoding="utf-8") as f:
        gamma = json.load(f)["gamma"]
    refinement = {
        "generated_utc": datetime.datetime.now(datetime.timezone.utc)
                                 .isoformat().replace("+00:00", "Z"),
        "identity": solver_identity(sha256_file(tpm_abs), gamma),
        "purpose": "Second sweep: five alpha points on each side of each of "
                   "the two behaviour-transition boundaries the first sweep "
                   "bracketed, so both regimes are sampled five times within "
                   "8 % of the transition.",
        "order": list(REFINE_ORDER),
        "idx_start": REFINE_IDX_START,
        "spacing": {
            "rule": "alpha = boundary * (1 -/+ d)",
            "deltas": [float(d) for d in REFINE_DELTAS],
            "note": "geometric deltas, x2 per step; the pair straddling a "
                    "boundary differs by 1 % in alpha, the outermost pair by "
                    "16 %.",
        },
        "boundaries": boundaries,
        "points": entries,
    }
    _write_manifest_with_refinement(refinement)
    print("[refine] manifest updated: %s" % MANIFEST_PATH)
    return 0


def _write_manifest_with_refinement(refinement):
    """Rewrite manifest.json, keeping the original 21-point block verbatim."""
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["refinement"] = refinement
    manifest["generated_utc"] = (datetime.datetime.now(datetime.timezone.utc)
                                 .isoformat().replace("+00:00", "Z"))
    _atomic_write_json(MANIFEST_PATH, manifest)


def _refinement_if_current(identity):
    """The stored refinement block, or None when it no longer applies.

    A block whose stamped `identity` differs from this solve's is DROPPED with
    a warning rather than carried forward: its boundaries were bisected against
    different solver constants and no longer locate this grid's transitions.
    An unstamped block (written before the stamp existed) is also dropped, for
    the same reason it cannot be checked.
    """
    ref = load_refinement(warn=False)
    if ref is None:
        return None
    stored = ref.get("identity")
    if stored == identity:
        return ref
    print("[sweep] WARNING: dropping the stored refinement block - its solver "
          "identity %r does not match this solve's %r. Re-run `refine`."
          % (stored, identity), file=sys.stderr)
    return None


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


def evaluation_rows(results, anchor_idx, dsoc_ref=None):
    """The evaluation table, given {idx: (point, WalkResult)}.

    ``dsoc_ref`` overrides the SoC reference eq-H2 is priced against.  It is
    passed when the selection does not contain the anchor point, so that a
    refined-only table is priced against the SAME reference as the combined
    one; ``anchor_idx`` is then only the table's own ordering fallback.

    Pure: takes already-walked results so a test can drive it on synthetic
    WalkResult objects.
    """
    if dsoc_ref is None:
        dsoc_ref = float(results[anchor_idx][1].delta_soc)
    dsoc_ref = float(dsoc_ref)
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
            # ADDITIVE: "original" for a first-sweep grid point, "refined" for
            # a second-sweep point.  A point dict that predates the refinement
            # carries no key, so the default keeps old callers unchanged.
            "origin": point.get("origin", "original"),
            "boundary": point.get("boundary", ""),
            "side": point.get("side", ""),
        })
    return rows


def write_eval_csv(path, rows):
    fields = ["idx", "alpha", "is_anchor", "origin", "boundary", "side",
              "h2_g", "h2_proxy_g", "delta_soc", "soc_final", "eq_h2_g",
              "charge_windows", "mode_fractions"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def markdown_table(rows):
    head = ("| idx | alpha | origin | h2 (g) | dSoC | eq-H2 (g) | "
            "charge windows |\n|---:|---:|:--|---:|---:|---:|---:|\n")
    body = "".join(
        "| %d%s | %.6f | %s | %.6g | %+.6f | %.6g | %d |\n"
        % (r["idx"], " (anchor)" if r["is_anchor"] else "", r["alpha"],
           _origin_label(r), r["h2_g"], r["delta_soc"], r["eq_h2_g"],
           r["charge_windows"])
        for r in rows)
    return head + body


def _origin_label(row):
    if row.get("origin", "original") != "refined":
        return "grid"
    return "%s %s" % (row.get("boundary", ""), row.get("side", ""))


# The two bisected transition alphas, used to name the legs and to mark the
# alpha-axis figure.  Read from the manifest's refinement block so the figure
# and the artifacts can never disagree; the analytic window ends are the
# fallback when no refinement has been run.
FALLBACK_BOUNDARIES = {"degeneracy": 0.111000, "charge": 0.239250}

LEG_LABELS = {"greedy": "greedy (share map degenerate)",
              "calibrated": "calibrated (share lever only)",
              "charge_admitting": "charge-admitting"}


def boundary_alphas():
    ref = load_refinement(warn=False)
    if not ref:
        return dict(FALLBACK_BOUNDARIES)
    return {k: float(v["alpha"]) for k, v in ref["boundaries"].items()}


def leg_of(row, boundaries):
    """The behaviour leg a row belongs to."""
    if row["charge_windows"] > 0:
        return "charge_admitting"
    if row["alpha"] > boundaries.get("degeneracy",
                                     FALLBACK_BOUNDARIES["degeneracy"]):
        return "calibrated"
    return "greedy"


def cluster_rows(rows, boundaries, places=8):
    """Group rows into legs, one entry per distinct (h2, dSoC) cluster.

    Rows inside a leg are identical to `places` decimals, which is why the
    scatter overprints; the clustered figure draws each group ONCE.
    """
    groups = {}
    for r in rows:
        key = (leg_of(r, boundaries),
               round(r["h2_g"], places), round(r["delta_soc"], places))
        groups.setdefault(key, []).append(r)
    out = []
    for (leg, h2, dsoc), members in groups.items():
        alphas = sorted(m["alpha"] for m in members)
        out.append({
            "leg": leg, "h2_g": h2, "delta_soc": dsoc,
            "alpha_lo": alphas[0], "alpha_hi": alphas[-1],
            "n": len(members),
            "has_anchor": any(m["is_anchor"] for m in members),
            "anchor": [m for m in members if m["is_anchor"]] or None,
        })
    out.sort(key=lambda g: g["alpha_lo"])
    return out


def write_figure(path, rows):
    """Hydrogen against SoC change, ONE marker per behaviour leg.

    Every point inside a leg is identical to eight decimals, so a per-point
    scatter overprints 41 markers onto three positions and 41 alpha labels onto
    each other.  The clusters are therefore drawn once and annotated with the
    alpha range and the member count.  No polyline is drawn through the points
    in index order: the legs are connected in ALPHA order by a light dotted
    line, which is the only ordering that means anything here.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    boundaries = boundary_alphas()
    groups = cluster_rows(rows, boundaries)
    colors = {"greedy": "#4c72b0", "calibrated": "#55a868",
              "charge_admitting": "#c44e52"}

    fig, ax = plt.subplots(figsize=(8.0, 5.5))
    ax.plot([g["delta_soc"] for g in groups], [g["h2_g"] for g in groups],
            ":", color="0.65", linewidth=1.0, zorder=1,
            label="legs in alpha order")
    for g in groups:
        ax.plot([g["delta_soc"]], [g["h2_g"]], "o",
                color=colors.get(g["leg"], "0.35"), markersize=10, zorder=3)
        if g["has_anchor"]:
            ax.plot([g["delta_soc"]], [g["h2_g"]], "*", color="black",
                    markersize=17, zorder=4, label="anchor (shipped alpha)")
        ax.annotate(
            "%s\n$\\alpha \\in$ [%.6f, %.6f], n = %d"
            % (LEG_LABELS[g["leg"]], g["alpha_lo"], g["alpha_hi"], g["n"]),
            (g["delta_soc"], g["h2_g"]), textcoords="offset points",
            xytext=(10, -4), fontsize=8, va="top",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="0.8",
                      alpha=0.9))
    ax.set_xlabel(r"$\Delta$SoC over the scenario")
    ax.set_ylabel("hydrogen consumed (g, Gfc)")
    ax.set_title("SDP alpha sweep: hydrogen against SoC change, by leg")
    ax.margins(x=0.30, y=0.18)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_alpha_figure(path, rows):
    """Hydrogen and SoC change against alpha, on a log axis.

    This is the view the clustered figure cannot give: the two transitions are
    vertical, the refined points are dense on either side of each of them, and
    the piecewise-constant legs are flat between them.  Both panels are drawn
    step-style, because the quantity IS a step function of alpha.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    boundaries = boundary_alphas()
    rows = sorted(rows, key=lambda r: r["alpha"])
    a = [r["alpha"] for r in rows]
    colors = {"greedy": "#4c72b0", "calibrated": "#55a868",
              "charge_admitting": "#c44e52"}
    legs = [leg_of(r, boundaries) for r in rows]

    fig, axes = plt.subplots(2, 1, figsize=(8.5, 7.0), sharex=True)
    panels = ((axes[0], [r["h2_g"] for r in rows],
               "hydrogen consumed (g, Gfc)"),
              (axes[1], [r["delta_soc"] for r in rows],
               r"$\Delta$SoC over the scenario"))
    for ax, y, ylabel in panels:
        ax.step(a, y, where="post", color="0.45", linewidth=1.2, zorder=2)
        for xi, yi, leg, r in zip(a, y, legs, rows):
            ax.plot([xi], [yi], "o", color=colors.get(leg, "0.35"),
                    markersize=7 if r.get("origin") == "refined" else 5,
                    markerfacecolor=("white" if r.get("origin") == "refined"
                                     else colors.get(leg, "0.35")),
                    zorder=3)
            if r["is_anchor"]:
                ax.plot([xi], [yi], "*", color="black", markersize=16,
                        zorder=5)
        for name, b in sorted(boundaries.items()):
            ax.axvline(b, color="0.25", linestyle="--", linewidth=1.0,
                       zorder=1)
        ax.set_xscale("log")
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.3, which="both")
    for name, b in sorted(boundaries.items()):
        axes[0].annotate("%s boundary\n%.6f" % (name, b), (b, 1.0),
                         xycoords=("data", "axes fraction"),
                         textcoords="offset points", xytext=(4, -12),
                         fontsize=8, va="top", color="0.25")
    axes[1].set_xlabel(r"$\alpha$ (log scale)")
    axes[0].set_title("SDP alpha sweep: the two behaviour transitions",
                      fontsize=11)
    axes[0].annotate("open markers: refined points; star: anchor",
                     (0.0, 1.005), xycoords="axes fraction", fontsize=8,
                     color="0.35")
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
    include = getattr(args, "include", "original")
    grid = all_points(include)
    if not grid:
        print("[sweep] --include %s selected no points (run `refine` first)"
              % include, file=sys.stderr)
        return 1
    suffix = {"original": "", "refined": "refined_", "all": "all_"}[include]
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
        dsoc_ref = None
        if anchor_idx is None:
            # MED-2: a selection without the anchor (the refined-only table)
            # must STILL be priced against the ANCHOR's SoC change, or its
            # eq-H2 column is not comparable with the other tables'.  The
            # anchor is therefore walked once more, purely for its dSoC.
            anchor_point = _anchor_point()
            apf = os.path.join(SWEEP_DIR, point_filename(anchor_point))
            dsoc_ref = float(walk(args.strategy, scenario,
                                  policy_file=apf).delta_soc)
            anchor_idx = min(results)
            print("[sweep] eq-H2 reference: anchor idx %d, dSoC %+.6f"
                  % (anchor_point["idx"], dsoc_ref))
        rows = evaluation_rows(results, anchor_idx, dsoc_ref)
        _emit_eval(out_dir, scenario, rows, suffix)
    return 0


def _anchor_point():
    """The anchor grid point, whose SoC change prices every eq-H2 column."""
    return [p for p in build_grid() if p["is_anchor"]][0]


def _emit_eval(out_dir, scenario, rows, suffix=""):
    csv_path = os.path.join(out_dir, "sweep_eval_%s%s.csv" % (suffix, scenario))
    write_eval_csv(csv_path, rows)
    md_path = os.path.join(out_dir, "sweep_eval_%s%s.md" % (suffix, scenario))
    with open(md_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# SDP alpha sweep - offline walk, scenario `%s`\n\n"
                "Equivalent hydrogen uses lambda = %.2f SoC/g against the "
                "anchor point's SoC change.\n\n" % (scenario,
                                                    EQ_H2_LAMBDA_SOC_PER_G))
        f.write(markdown_table(rows))
    fig_path = os.path.join(out_dir,
                            "sweep_h2_vs_dsoc_%s%s.png" % (suffix, scenario))
    write_figure(fig_path, rows)
    afig_path = os.path.join(out_dir,
                             "sweep_h2_vs_alpha_%s%s.png" % (suffix, scenario))
    write_alpha_figure(afig_path, rows)
    print("[sweep] wrote %s, %s, %s, %s"
          % (csv_path, md_path, fig_path, afig_path))


# ---------------------------------------------------------------------------
# Plots: synthesize a HIL-schema CSV from an OFFLINE walk, then render the
# standard report figures from it
#
# There is no board run behind a sweep point, so the traces below come from the
# reduced offline model of `tools/ems_walk.py` and carry that model's fidelity
# boundaries (no Youla dynamics, the DP demand model, charge admission by the
# DP mask).  The provenance is carried into every figure's suptitle through
# `cfg["_run_name"]`, and is stated again in the plot folder's README.
# ---------------------------------------------------------------------------

# The simulated hi-fi HIL CSV header, verbatim and in order
# (tools/hil_plant_sim.py:8512-8611, the `header_row` construction inside the
# writer).  A synthesized CSV must present the same columns in the same order,
# because `load_hil_csv` keys purely off the header.
#
# WHY THIS IS A LITERAL AND NOT DERIVED: the live header is built inline in the
# simulator's `main()` from local flags (`electrical`, the replay branch), and
# the module exposes neither a header constant nor a builder function, so there
# is nothing to import.  Deriving it would mean re-implementing the branch
# logic, which is the same duplication with an extra layer.  The lockstep is
# therefore a TEST obligation: assert this list against the live writer.
HIL_CSV_COLUMNS = [
    "t", "seq", "V_fc", "V_batt", "V_bus", "V_chg", "V_rgn", "I_fc", "I_batt",
    "v_actual", "I_charge", "ag105_status", "state", "switch", "aux",
    "current", "mdac_fc", "mdac_bt", "fault_flags", "soc", "elec_substep_hz",
    "elec_events", "cmd_v_sp", "cmd_share_sp", "h2_rate_gps", "h2_cum_g",
    "h2_sdp_cum_g", "cmd_share_sp_raw", "mppt_thresh_cnt", "error_code",
    # Power-balance tail, appended to BOTH schemas 2026-09-01f
    # (tools/hil_plant_sim.py:8608).  Plant.step() quantities the reduced walk
    # does not compute, so they are written blank.
    "p_mot_w", "p_fc_w", "p_batt_w", "p_chop_w", "p_aux_w", "p_bal_w",
]

# Documented constants for the columns the reduced model does not produce.
WALK_CSV_STATE = 2               # State 2 (Run) throughout the walk window
WALK_CSV_FAULT_FLAGS = 0         # the offline model raises no fault
WALK_CSV_ERROR_CODE = 0


def _walk_csv_switch_word(sim, fc_charge):
    """The switch word for a walk stage.

    FC_BUS, MOT_PWR and BT_SEQ are held for the whole Run window.  BT_BUS is
    held LOW inside an FC-charge window, exactly as chargingControl() does
    (CLAUDE.md, 2026-09-01c), and FC_CHARGE is asserted there instead.
    """
    word = sim.SW_FC_BUS | sim.SW_MOT_PWR | sim.SW_BT_SEQ
    if fc_charge:
        word |= sim.SW_FC_CHARGE
    else:
        word |= sim.SW_BT_BUS
    return word


def _walk_csv_ag105_status(sim, fc_charge):
    """Charging in constant current inside a window; disconnected outside.

    The reduced model has no Ag105 state machine, so these are the plausible
    Table-6 bytes for the two conditions, not simulated ones.
    """
    if fc_charge:
        return sim.AG105_ST_CHARGING | sim.AG105_FLAG_CC
    return sim.AG105_ST_DISCONNECT


def synthesize_hil_csv(path, result, sim, scenario_meta, dt_s):
    """Write one walk result as a HIL-schema CSV.

    Every column of `HIL_CSV_COLUMNS` is emitted in order.  A column the walk
    cannot produce is written BLANK, which `load_hil_csv` reads as NaN, so a
    figure that depends on it declines rather than plotting a fabricated trace.
    Returns the number of rows written.
    """
    if not result.t:
        raise ValueError("the walk carries no trace; call walk(trace=True)")
    prof = scenario_meta.get("ems_v_profile")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HIL_CSV_COLUMNS)
        for k, t in enumerate(result.t):
            fc_charge = bool(result.sw_fc_charge[k])
            v_sp = None if prof is None else sim.piecewise(prof, t)
            h2_prev = result.h2_cum_g[k - 1] if k else 0.0
            rate = (result.h2_cum_g[k] - h2_prev) / dt_s
            w.writerow([
                "%.6f" % t,                                   # t
                k,                                            # seq
                "", "",                                       # V_fc, V_batt
                "%.4f" % result.v_bus[k],                     # V_bus
                "", "",                                       # V_chg, V_rgn
                "%.4f" % result.i_fc[k],                      # I_fc
                "%.4f" % result.i_batt[k],                    # I_batt
                "" if v_sp is None else "%.5f" % v_sp,        # v_actual
                "%.4f" % result.i_charge[k],                  # I_charge
                "0x%02X" % _walk_csv_ag105_status(sim, fc_charge),
                WALK_CSV_STATE,                               # state
                _walk_csv_switch_word(sim, fc_charge),        # switch
                sim.AUX_FC_REG | sim.AUX_BT_REG,              # aux
                "",                                           # current
                "" if result.mdac_fc[k] is None else result.mdac_fc[k],
                "" if result.mdac_bt[k] is None else result.mdac_bt[k],
                WALK_CSV_FAULT_FLAGS,                         # fault_flags
                "%.5f" % result.soc[k],                       # soc
                "", "",                                       # elec_* columns
                "" if v_sp is None else "%.5f" % v_sp,        # cmd_v_sp
                "%.5f" % result.share_cmd[k],                 # cmd_share_sp
                "%.9g" % rate,                                # h2_rate_gps
                "%.9g" % result.h2_cum_g[k],                  # h2_cum_g
                "",                                           # h2_sdp_cum_g
                "",                                           # cmd_share_sp_raw
                "",                                           # mppt_thresh_cnt
                WALK_CSV_ERROR_CODE,                          # error_code
                "", "", "", "", "", "",                       # power balance
            ])
    return len(result.t)


def plot_run_name(point, scenario):
    """The provenance string every figure's suptitle carries."""
    return ("OFFLINE GOVERNOR WALK - alpha_%02d_%.6f - not a board run (%s)"
            % (point["idx"], point["alpha"], scenario))


def plot_dir_name(point):
    return "alpha_%02d_%.6f" % (point["idx"], point["alpha"])


# The synthesized figures carry a `walk_` prefix so that a future glob for a
# board-run figure name (`**/currents_and_share.png`) cannot ingest an offline
# walk as if it were a run.
PLOT_PREFIX = "walk_"
PLOT_BUILDERS = ("currents_and_share", "hil_charger_and_soc")


def render_walk_figures(hra, bl_figures, csv_path, dest, cfg):
    """Render the two standard figures from a synthesized CSV.

    Returns ``{figure_name: path_or_None}``; None means the builder declined
    (a missing column), which is reported rather than hidden.
    """
    hil = hra.attach_derived(hra.load_hil_csv(csv_path))
    data = hra.adapt_to_benchlog(hil)
    out = {}
    for name, builder, src in (
            ("currents_and_share", bl_figures.currents_and_share, data),
            ("hil_charger_and_soc", hra.hil_charger_and_soc, hil)):
        try:
            fig = builder(src, cfg)
        except KeyError as exc:
            out[name] = None
            print("[plots]   %s: declined (missing column %s)" % (name, exc))
            continue
        if fig is None:
            out[name] = None
            print("[plots]   %s: declined (builder returned None)" % name)
            continue
        target = os.path.join(dest, "%s%s.png" % (PLOT_PREFIX, name))
        hra._save(fig, target)
        out[name] = target
    return out


def cmd_plots(args):
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)
    import ems_walk
    import hil_plant_sim as sim
    import hil_report_analysis as hra
    from benchlog_analysis import figures as bl_figures
    import gen_dp_ems_table as gen

    out_root = args.out or os.path.join(REPO_ROOT, "docs", "modeling",
                                        "sdp_alpha_sweep_20260901", "plots")
    points = all_points(args.include)
    if args.only:
        keep = set(args.only)
        points = [p for p in points if p["idx"] in keep]
    if not points:
        print("[plots] no points selected", file=sys.stderr)
        return 1

    dt_s = float(gen.DP_STAGE_DT_S)
    written = 0
    for scenario in args.scenario:
        meta = sim.SCENARIOS[scenario]
        for point in points:
            pf = os.path.join(SWEEP_DIR, point_filename(point))
            if not os.path.exists(pf):
                print("[plots] point %02d not solved (%s)"
                      % (point["idx"], pf), file=sys.stderr)
                return 1
            dest = os.path.join(out_root, scenario, plot_dir_name(point))
            os.makedirs(dest, exist_ok=True)
            r = ems_walk.walk(args.strategy, scenario, policy_file=pf,
                              trace=True)
            csv_path = os.path.join(dest, "walk_trace.csv")
            n = synthesize_hil_csv(csv_path, r, sim, meta, dt_s)
            cfg = dict(hra.load_run_config(
                pathlib.Path(dest), pathlib.Path(dest)))
            # `_hil_build` stays FALSE deliberately: its banner claims a
            # simulated PLANT log, and this is neither a plant run nor a board
            # run.  The provenance rides `_run_name` instead.
            cfg["_run_name"] = plot_run_name(point, scenario)
            cfg["_hil_build"] = False
            made = render_walk_figures(hra, bl_figures, csv_path, dest, cfg)
            written += sum(1 for v in made.values() if v)
            print("[plots] %02d alpha %.6f  %s  %d rows  %d/%d figures"
                  % (point["idx"], point["alpha"], scenario, n,
                     sum(1 for v in made.values() if v), len(made)))
    print("[plots] %d figures under %s" % (written, out_root))
    return 0


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

    pr = sub.add_parser("refine",
                        help="bisect the two behaviour boundaries and solve "
                             "five points on each side of each")
    pr.add_argument("--rel-tol", type=float, default=BISECT_REL_TOL,
                    help="bisection stop width, relative (default %g)"
                         % BISECT_REL_TOL)
    pr.add_argument("--no-solve", action="store_true",
                    help="re-summarize already-solved refinement artifacts "
                         "instead of re-solving them")

    pp = sub.add_parser("plots",
                        help="render the standard figures for every point "
                             "from a synthesized offline-walk CSV")
    pp.add_argument("--scenario", action="append", default=None,
                    help="scenario name (repeatable; default ems-sdp)")
    pp.add_argument("--include", choices=("original", "refined", "all"),
                    default="all", help="which points to plot (default all)")
    pp.add_argument("--only", type=int, nargs="+", metavar="IDX",
                    help="plot only these indices")
    pp.add_argument("--out", default=None, help="plot root directory")
    pp.add_argument("--strategy", default=EVAL_STRATEGY,
                    help="strategy binding for the walk (default %s)"
                         % EVAL_STRATEGY)

    pe = sub.add_parser("evaluate", help="offline-walk every point")
    pe.add_argument("--include", choices=("original", "refined", "all"),
                    default="original",
                    help="which points to walk; the output file names carry "
                         "the selection (default original: the first sweep's "
                         "same rows plus three additive provenance columns)")
    pe.add_argument("--scenario", action="append", default=None,
                    help="scenario name (repeatable; default ems-sdp)")
    pe.add_argument("--out", default=None, help="output directory")
    pe.add_argument("--strategy", default=EVAL_STRATEGY,
                    help="strategy binding for the walk (default %s - see "
                         "EVAL_STRATEGY)" % EVAL_STRATEGY)
    pe.add_argument("--self-test", action="store_true",
                    help="exercise the evaluation path on a fake walk result")

    args = ap.parse_args(argv)
    if getattr(args, "scenario", None) is not None or args.cmd in ("evaluate",
                                                                   "plots"):
        if not getattr(args, "scenario", None):
            args.scenario = ["ems-sdp"]
    if args.cmd == "grid":
        return cmd_grid(args)
    if args.cmd == "solve":
        return cmd_solve(args)
    if args.cmd == "refine":
        return cmd_refine(args)
    if args.cmd == "plots":
        return cmd_plots(args)
    return cmd_evaluate(args)


if __name__ == "__main__":
    sys.exit(main())
