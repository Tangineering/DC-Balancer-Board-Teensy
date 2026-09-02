#!/usr/bin/env python3
"""EMS-strategy comparison stage for one HIL campaign report folder.

The per-run analysis pass (`hil_report_analysis.py`) answers "did this run
behave", one run at a time.  This stage answers the question that only exists
ACROSS runs: given several energy-management strategies driven by ONE drive
stimulus, which one bought its hydrogen most cheaply once the state-of-charge
difference between them is priced?

It writes three artifacts into the report folder:

  * ``EMS_COMPARISON.md``      -- the rendered comparison, one section per
                                  drive-stimulus profile.
  * ``ems_comparison.json``    -- every number the Markdown quotes.
  * ``ems_comparison/*.png``   -- the figures the Markdown references.

TWO RULES GOVERN THE MARKDOWN.  First, it carries no number that is absent
from ``ems_comparison.json``: the document is a rendering of that object and
of nothing else.  Second, its Commentary section is written by a human.  This
module emits the placeholder marker and never interpretive prose, because the
interpretation of a strategy comparison depends on the campaign ledger, and a
generated sentence that reads like a finding is worse than no sentence.

GROUPING IS BY STIMULUS, NOT BY NAME.  Equivalent-hydrogen arithmetic corrects
for state of charge, not for demand, so two runs may only be compared when
they saw the same drive profile.  Runs are therefore grouped by the
fingerprint of ``hil_plant_sim.SCENARIOS[<name>]["ems_v_profile"]`` together
with the scenario duration; the FTP-75 legs share one profile object and fall
into one group without any name matching.

Requires numpy and matplotlib for the collection and figure stages, which is
why every import of ``hil_report_analysis`` is deferred into a function: the
stdlib-only interpreter must still be able to import this module and exercise
its pure arithmetic and rendering.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import run_hil_suite as _suite            # stdlib-only, safe at import time


# ==========================================================================
# Constants
# ==========================================================================

#: Verbatim marker the orchestrator replaces by hand.  Tests assert on this
#: exact string, and the Stage-4 close-out looks for it.
COMMENTARY_PLACEHOLDER = "<!-- COMMENTARY: orchestrator fills this in -->"

#: Subfolder, relative to the report folder, that holds this stage's figures.
FIGURE_SUBDIR = "ems_comparison"

MARKDOWN_NAME = "EMS_COMPARISON.md"
JSON_NAME = "ems_comparison.json"

#: A profile group is rendered only when at least this many EMS runs share it.
#: One run compared against itself ranks nothing.
MIN_RUNS_PER_GROUP = 2

#: Trace figures are decimated to at most this many samples per strategy.  A
#: 350 000-row cumulative trace and its 4 000-sample decimation are visually
#: identical at figure resolution, and the decimated figure renders in
#: seconds rather than minutes.
TRACE_MAX_POINTS = 4000

#: Per-strategy colours, assigned in the group's own run order so a strategy
#: keeps one colour across both figures of its section.
STRATEGY_COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7", "#e34948",
                   "#0f8f95", "#c07a1e", "#7a5cc9", "#e87ba4", "#008300")


# ==========================================================================
# Lazy module handles
# ==========================================================================

def _hra():
    """tools/hil_report_analysis.py.  Deferred: it imports numpy and
    matplotlib at module scope, and this module must import under the
    stdlib-only interpreter."""
    import hil_report_analysis
    return hil_report_analysis


def _sim():
    """tools/hil_plant_sim.py, deferred for the same reason."""
    import hil_plant_sim
    return hil_plant_sim


# ==========================================================================
# Pure arithmetic and grouping
# ==========================================================================

def profile_fingerprint(profile):
    """Stable short identity for a drive-velocity profile.

    The profile is a list of (time, velocity) pairs.  It is serialized with
    a fixed float format rather than repr, so the identity does not depend on
    the interpreter's float formatting.  Returns None for an absent profile.
    """
    if not profile:
        return None
    payload = ";".join("%.9g,%.9g" % (float(t), float(v)) for t, v in profile)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def group_key(scen_meta):
    """(profile fingerprint, duration) for a scenario, or None.

    None means the scenario carries no drive profile and therefore belongs to
    no comparison group.
    """
    if not scen_meta:
        return None
    fp = profile_fingerprint(scen_meta.get("ems_v_profile"))
    if fp is None:
        return None
    return (fp, float(scen_meta.get("duration_s") or 0.0))


def frontier_specs():
    """The registered EMS frontier tuples, in registry order."""
    return list(getattr(_suite, "EMS_FRONTIERS", []))


def match_frontier(run_names, specs=None):
    """The first frontier spec whose reference and candidate are both present.

    `run_names` is the set of scenario names in one profile group.  Returns
    the spec dict, or None when the group hosts no registered tuple.
    """
    names = set(run_names)
    for spec in (frontier_specs() if specs is None else specs):
        roles = spec.get("roles") or {}
        if roles.get("reference") in names and roles.get("candidate") in names:
            return spec
    return None


def group_label(spec, fingerprint, duration_s):
    """Human label for a profile group."""
    if spec and spec.get("label"):
        return str(spec["label"])
    return "drive profile %s (%.0f s)" % (fingerprint, duration_s)


def eq_h2(h2, dsoc, dsoc_ref, lam):
    """SoC-corrected hydrogen, delegated to the suite's own arithmetic.

    Re-exported here so this module has one import site for the quantity and
    a test can assert the two agree.
    """
    return _suite.ems_eq_h2(h2, dsoc, dsoc_ref, lam)


def _ratio(num, den):
    if num is None or den is None or not den:
        return None
    return float(num) / float(den)


def score_group(strategies, reference_name=None, bound_name=None, lam=None):
    """Attach eq-H2 and the two ratios to every strategy row.  In place.

    `strategies` is a list of row dicts carrying at least `run`, `h2_run_g`
    and `delta_soc_run`.  The reference leg supplies `dsoc_ref`; when there is
    no reference leg in the group, `dsoc_ref` is 0.0 and the eq-H2 column is
    an absolute SoC-priced cost rather than a difference against a sibling.
    The two ratio columns are then None, because there is nothing to divide
    by.  Returns (dsoc_ref, eq_h2_reference, eq_h2_bound).
    """
    if lam is None:
        lam = _suite.EMS_EQ_H2_LAMBDA_SOC_PER_G
    by_name = {s["run"]: s for s in strategies}
    ref = by_name.get(reference_name)
    dsoc_ref = 0.0 if (ref is None or ref.get("delta_soc_run") is None) \
        else float(ref["delta_soc_run"])
    for s in strategies:
        if s.get("h2_run_g") is None or s.get("delta_soc_run") is None:
            s["eq_h2_g"] = None
            continue
        s["eq_h2_g"] = eq_h2(s["h2_run_g"], s["delta_soc_run"], dsoc_ref, lam)
    eq_ref = (by_name.get(reference_name) or {}).get("eq_h2_g")
    eq_bnd = (by_name.get(bound_name) or {}).get("eq_h2_g")
    for s in strategies:
        s["vs_reference"] = _ratio(s.get("eq_h2_g"), eq_ref)
        s["vs_bound"] = _ratio(s.get("eq_h2_g"), eq_bnd)
    return dsoc_ref, eq_ref, eq_bnd


def frontier_verdicts_for(results_json, run_names):
    """Suite frontier records whose candidate is one of `run_names`.

    Keyed by candidate run name.  A campaign that registered two tuples on one
    stimulus (an SDP candidate and an MPC candidate) yields two entries.
    """
    out = {}
    for rec in (results_json or {}).get("ems_frontiers") or []:
        cand = ((rec.get("roles") or {}).get("candidate"))
        if cand in set(run_names):
            out[cand] = rec
    return out


# ==========================================================================
# Collection
# ==========================================================================

def _matched_dp_fields(mdp):
    """The bound half of one table row, from a run's `matched_dp` block."""
    if not mdp:
        return {"matched_dp_status": None, "h2_dp_g": None,
                "pct_deviation": None, "lambda_term": None,
                "residual_soc": None, "converged": None,
                "delta_soc_dp": None, "target_soc": None,
                "matched_dp_notes": []}
    return {
        "matched_dp_status": mdp.get("status"),
        "h2_dp_g": mdp.get("h2_dp_compared_g", mdp.get("h2_dp_g")),
        "pct_deviation": mdp.get("pct_deviation"),
        "lambda_term": mdp.get("lambda_term"),
        "residual_soc": mdp.get("residual_soc"),
        "converged": mdp.get("converged"),
        "delta_soc_dp": mdp.get("delta_soc_dp"),
        "target_soc": mdp.get("target_soc"),
        "matched_dp_notes": list(mdp.get("notes") or []),
    }


def _decimate(t, y, max_points=TRACE_MAX_POINTS):
    """Stride-decimate a trace, keeping the last sample.

    The last sample is kept explicitly because both traces this stage plots
    are monotone accumulators whose FINAL value is the quantity the table
    quotes; dropping it would make the figure disagree with the table.
    """
    import numpy as np
    n = int(t.shape[0])
    if n <= max_points:
        idx = np.arange(n)
    else:
        idx = np.unique(np.append(
            np.arange(0, n, max(1, n // max_points)), n - 1))
    return t[idx], y[idx]


def collect_group_data(report_dir, matched_dp="lookup", matched_dp_tol=None,
                       matched_dp_strict=False, matched_dp_allow_long=False,
                       log=print):
    """Every EMS profile group in a report folder, with traces attached.

    Returns a list of group dicts.  A group holds `strategies` (one row per
    run) and, on each row, an underscore-prefixed `_trace` entry with the
    decimated time, `h2_cum_g` and `soc` arrays.  Groups with fewer than
    MIN_RUNS_PER_GROUP runs are dropped, as is a group whose legs are all
    stimulus demonstrations: a strategy comparison needs at least two
    strategies and at least one frontier-eligible policy among them.
    """
    hra = _hra()
    sim = _sim()
    report_dir = Path(report_dir)
    results_json = hra._read_json(report_dir / "results.json") or {}

    buckets = {}
    for run in hra.discover_runs(report_dir):
        if run.kind != "scenario":
            continue
        scen_meta = (sim.SCENARIOS or {}).get(run.name)
        key = group_key(scen_meta)
        if key is None:
            continue
        dest = run.csv_path.parent
        analysis = hra._read_json(dest / "analysis.json") or {}
        meta = hra._read_json(run.meta_path) or {}
        strategy = analysis.get("ems_strategy") or meta.get("ems_strategy")
        if not strategy:
            # A drive-profile scenario with no EMS strategy (charge-regen,
            # mppt-tracking) is a hardware exerciser, not a policy leg.
            continue
        buckets.setdefault(key, []).append(
            (run, dest, analysis, meta, strategy, scen_meta))

    groups = []
    for (fp, duration_s), members in buckets.items():
        if len(members) < MIN_RUNS_PER_GROUP:
            continue
        # A group is a POLICY comparison only when at least one of its legs
        # runs a frontier-eligible strategy. The test is registry-derived
        # (hil_plant_sim.EMS_STRATEGY_META.frontier_eligible), not name-based,
        # and it is what separates the EMS legs from the charger exercisers:
        # `charge-regen` and `mppt-tracking` share a 45 s profile and each
        # declares an EMS strategy, but both are stimuli with no objective, so
        # ranking their hydrogen against each other would measure the cycle
        # and not a policy.
        if not any(hra.ems_strategy_role(m[4]) == "frontier"
                   for m in members):
            continue
        members.sort(key=lambda m: m[0].name)
        names = [m[0].name for m in members]
        spec = match_frontier(names)
        roles = (spec or {}).get("roles") or {}
        strategies = []
        for i, (run, dest, analysis, meta, strategy, scen_meta) in \
                enumerate(members):
            hil = hra.load_hil_csv(run.csv_path)
            # `off` drops the bound outright rather than falling back on the
            # block a previous pass left in analysis.json: the flag asks for a
            # comparison WITHOUT a DP bound, and quoting a stale cached one
            # would answer a different question.
            mdp = None
            if matched_dp != "off":
                mdp = analysis.get("matched_dp")
                fresh = hra.matched_dp_for_run(
                    analysis, meta, hra.attach_derived(dict(hil)),
                    mode=matched_dp, tol_soc=matched_dp_tol,
                    strict=matched_dp_strict, log=log,
                    allow_long=matched_dp_allow_long)
                if fresh is not None:
                    mdp = fresh
            row = {
                "run": run.name,
                "folder": run.folder_name,
                "strategy": strategy,
                "role": analysis.get("ems_role")
                        or hra.ems_strategy_role(strategy),
                # Carried VERBATIM from hil_plant_sim.EMS_STRATEGY_META. Some
                # strategies state in the registry that their totals are a
                # measurement but NOT a competitive score (the alpha-sweep
                # points, the stochastic MPC variant). A table that ranks them
                # silently would contradict the registry, so the note travels
                # with the row into the document's footnotes.
                "strategy_note": (
                    (getattr(sim, "EMS_STRATEGY_META", {}) or {})
                    .get(strategy, {}).get("role_note")),
                "frontier_role": next(
                    (r for r, n in roles.items() if n == run.name), None),
                "soc0": (mdp or {}).get("soc0"),
                "h2_run_g": (mdp or {}).get("h2_run_g"),
                "delta_soc_run": (mdp or {}).get("delta_soc_run"),
                "color": STRATEGY_COLORS[i % len(STRATEGY_COLORS)],
                # Staleness inputs for the figure cache: the CSV supplies the
                # traces, analysis.json supplies the matched-DP bound, and a
                # newly solved bound moves the second without touching the
                # first.
                "_inputs": [run.csv_path, dest / "analysis.json"],
            }
            row.update(_matched_dp_fields(mdp))
            if row["h2_run_g"] is None or row["delta_soc_run"] is None:
                row["h2_run_g"], row["delta_soc_run"] = \
                    _run_totals_from_csv(hil)
            t = hil["t_s"]
            row["_trace"] = {
                "h2": _decimate(t, hil.get("h2_cum_g")),
                "soc": _decimate(t, hil.get("soc")),
            } if ("h2_cum_g" in hil and "soc" in hil) else None
            strategies.append(row)

        lam = _suite.EMS_EQ_H2_LAMBDA_SOC_PER_G
        dsoc_ref, eq_ref, eq_bnd = score_group(
            strategies, roles.get("reference"), roles.get("bound"), lam)
        groups.append({
            "profile_id": fp,
            "duration_s": duration_s,
            "label": group_label(spec, fp, duration_s),
            "frontier_id": (spec or {}).get("id"),
            "reference": roles.get("reference"),
            "bound": roles.get("bound"),
            "lambda_soc_per_g": lam,
            "lambda_band": list(_suite.EMS_EQ_H2_LAMBDA_BAND),
            "dsoc_ref": dsoc_ref,
            "eq_h2_reference_g": eq_ref,
            "eq_h2_bound_g": eq_bnd,
            "strategies": strategies,
            "frontier_verdicts": frontier_verdicts_for(results_json, names),
            "figures": {},
        })

    # Groups that host a registered frontier come first, longest stimulus
    # first, so the drive-cycle section leads and the short synthetic cycles
    # follow.  Deterministic, and independent of folder iteration order.
    groups.sort(key=lambda g: (0 if g["frontier_id"] else 1,
                               -g["duration_s"], g["label"]))
    return groups


def _run_totals_from_csv(hil):
    """(final h2_cum_g, delta SoC) straight from a run's CSV columns.

    The fallback for a run whose analysis carries no matched-DP block at all;
    the block's own figures are the same two quantities.
    """
    hra = _hra()
    h2 = hil.get("h2_cum_g")
    soc = hil.get("soc")
    h2_final = None if h2 is None else hra._last_finite(h2)
    dsoc = None
    if soc is not None:
        first = hra._first_finite(soc)
        last = hra._last_finite(soc)
        if first is not None and last is not None:
            dsoc = last - first
    return h2_final, dsoc


# ==========================================================================
# Figures
# ==========================================================================

def _dp_x(row):
    """The abscissa of a row's DP bound marker.

    The bound is solved TO the run's terminal state of charge, so the two
    abscissae differ only by the bisection residual. `delta_soc_dp` is used
    when the record carries it, and the run's own value otherwise. Written as
    an explicit None test rather than an `or`, because a legitimate 0.0 must
    not fall through to the run's value.
    """
    dp = row.get("delta_soc_dp")
    return row["delta_soc_run"] if dp is None else float(dp)


def figure_tradeoff(group):
    """Hydrogen against state-of-charge change, with the matched-DP bounds.

    One filled marker per strategy at its measured (delta SoC, hydrogen), one
    open marker at its delta-SoC-matched DP bound, and a thin segment joining
    the pair so the vertical gap IS the deviation the table reports.  The
    dashed lines are constant-equivalent-hydrogen contours at the campaign
    lambda; a strategy sitting on a lower contour is the cheaper strategy
    once its state-of-charge difference is priced.
    """
    hra = _hra()
    plt = hra.plt
    rows = [s for s in group["strategies"]
            if s.get("h2_run_g") is not None
            and s.get("delta_soc_run") is not None]
    if not rows:
        return None
    lam = float(group["lambda_soc_per_g"])
    dsoc_ref = float(group.get("dsoc_ref") or 0.0)

    fig, ax = plt.subplots(figsize=(9.5, 6.5))

    xs = [s["delta_soc_run"] for s in rows]
    for s in rows:
        if s.get("h2_dp_g") is not None:
            xs.append(_dp_x(s))
    x_lo, x_hi = min(xs), max(xs)
    pad_x = 0.10 * (x_hi - x_lo) if x_hi > x_lo else 1e-4
    # Asymmetric: every run label is drawn to the RIGHT of its marker, so the
    # right margin must hold a label as well as a point.
    x_lo, x_hi = x_lo - pad_x, x_hi + 3.0 * pad_x

    # Iso-lines: h2 = eq + (dsoc - dsoc_ref) / lambda.  One per strategy, so
    # the ranking is readable off the contour spacing; the reference leg's
    # contour is drawn heavier because every other eq-H2 is measured from it.
    import numpy as np
    x_line = np.array([x_lo, x_hi], dtype=float)
    for s in rows:
        if s.get("eq_h2_g") is None:
            continue
        is_ref = (s["run"] == group.get("reference"))
        ax.plot(x_line, s["eq_h2_g"] + (x_line - dsoc_ref) / lam,
                color=s["color"], linestyle="--",
                linewidth=1.4 if is_ref else 0.7,
                alpha=0.85 if is_ref else 0.35, zorder=1)

    for s in rows:
        ax.plot([s["delta_soc_run"]], [s["h2_run_g"]], marker="o",
                markersize=8, color=s["color"], zorder=4, linestyle="none")
        if s.get("h2_dp_g") is not None:
            x_dp = _dp_x(s)
            ax.plot([s["delta_soc_run"], x_dp],
                    [s["h2_run_g"], s["h2_dp_g"]], color=s["color"],
                    linewidth=0.9, alpha=0.8, zorder=3)
            ax.plot([x_dp], [s["h2_dp_g"]], marker="o", markersize=7,
                    markerfacecolor="none", markeredgecolor=s["color"],
                    markeredgewidth=1.3, zorder=4, linestyle="none")
        ax.annotate(s["run"], (s["delta_soc_run"], s["h2_run_g"]),
                    textcoords="offset points", xytext=(9, 5),
                    color=s["color"], fontsize=8.5)

    ax.set_xlim(x_lo, x_hi)
    hra.bl_figures._style_axes(ax, ylabel="H2 consumed over the run [g]")
    ax.set_xlabel("delta SoC over the run [-]", color=hra.TEXT_COLOR,
                  fontsize=10)
    # Below the axes, not inside them: a marker can land anywhere in the
    # plane, and a caption box that overlaps a data point hides the result.
    fig.text(0.012, 0.012,
             "filled: measured run    open: delta-SoC-matched DP bound    "
             "dashed: constant eq-H2 contour at lambda = %.3f SoC/g" % lam,
             color=hra.TEXT_COLOR, fontsize=8.5, va="bottom")
    fig.suptitle("EMS strategies on %s: hydrogen against SoC change"
                 % group["label"], color=hra.TEXT_COLOR, fontsize=11)
    fig.tight_layout(rect=(0, 0.045, 1, 0.96))
    return fig


def figure_traces(group):
    """Cumulative hydrogen and state of charge against time, all strategies.

    The two panels share the time axis and the per-strategy colours of the
    trade-off figure, so a marker there and a trace here are the same run.
    """
    hra = _hra()
    plt = hra.plt
    rows = [s for s in group["strategies"] if s.get("_trace")]
    if not rows:
        return None
    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(10, 7.5), sharex=True)
    for s in rows:
        t, h2 = s["_trace"]["h2"]
        ax0.plot(t, h2, color=s["color"], linewidth=1.1, label=s["run"])
        t, soc = s["_trace"]["soc"]
        ax1.plot(t, soc, color=s["color"], linewidth=1.1, label=s["run"])
    hra.bl_figures._style_axes(ax0, ylabel="H2 consumed, cumulative [g]")
    hra.bl_figures._legend(ax0, loc="upper left")
    hra.bl_figures._style_axes(ax1, ylabel="SoC [-]")
    ax1.set_xlabel("Time [s]", color=hra.TEXT_COLOR, fontsize=10)
    fig.suptitle("EMS strategies on %s: hydrogen and SoC traces"
                 % group["label"], color=hra.TEXT_COLOR, fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return fig


def _group_is_stale(group, path, force=False):
    """True when a group's figure must be re-rendered.

    Every member run's CSV **and** its analysis.json count as inputs: a
    `--matched-dp solve` pass changes only the second, and a figure that
    ignored it would keep showing the missing bound it was drawn without.
    """
    hra = _hra()
    if force or not Path(path).exists():
        return True
    for s in group["strategies"]:
        for src in s.get("_inputs") or ():
            if hra._needs_render(path, src, force=False):
                return True
    return False


def render_figures(groups, report_dir, force=False):
    """Render both figures of every group.  Fills each group's `figures`."""
    hra = _hra()
    out_dir = Path(report_dir) / FIGURE_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    for g in groups:
        for key, builder in (("tradeoff", figure_tradeoff),
                             ("traces", figure_traces)):
            name = "ems_%s_%s.png" % (key, g["profile_id"])
            path = out_dir / name
            if not _group_is_stale(g, path, force=force):
                g["figures"][key] = "%s/%s" % (FIGURE_SUBDIR, name)
                continue
            fig = builder(g)
            if fig is None:
                continue
            hra._save(fig, path)
            g["figures"][key] = "%s/%s" % (FIGURE_SUBDIR, name)

    # Drop figures no group claims any more. A grouping rule change, or a
    # scenario removed from the campaign folder, otherwise leaves a PNG that
    # nothing references and that no reader can date.
    claimed = {Path(rel).name for g in groups for rel in g["figures"].values()}
    for stale in out_dir.glob("ems_*.png"):
        if stale.name not in claimed:
            try:
                stale.unlink()
            except OSError:                 # pragma: no cover - locked file
                pass
    return groups


# ==========================================================================
# Rendering
# ==========================================================================

def _num(value, spec="%.6g"):
    """A number for a table cell, or an em-dash when it does not exist."""
    if value is None:
        return "—"
    try:
        return spec % float(value)
    except (TypeError, ValueError):
        return str(value)


def _dp_status_cell(row):
    """The matched-DP residual and status, in one cell.

    A row with no bound renders its STATUS alone, so the reader sees why the
    hydrogen column is empty rather than an unexplained dash.
    """
    status = row.get("matched_dp_status") or "not computed"
    if row.get("residual_soc") is None:
        return status
    conv = "converged" if row.get("converged") else "NOT converged"
    return "%+.1e, %s (%s)" % (row["residual_soc"], conv, status)


#: Opening words of the per-run prefill hint `matched_dp_for_run()` attaches to
#: a `no_cached_solve` block. That note names the run, its terminal SoC and its
#: whole prefill command line, so it is DIFFERENT TEXT on every run and text
#: deduplication cannot collapse it. It is recognized by prefix and replaced by
#: one line per group; the per-run command line stays available in each run's
#: own ANALYSIS.md, which is where an operator prefilling one bound is already
#: looking.
NO_CACHED_SOLVE_NOTE_PREFIX = "no stored solve within"


def bound_gap_line(group):
    """One line naming every leg in a group that has no stored DP bound.

    None when every leg carries one.  Replaces the repeated per-run prefill
    hints, which said the same thing once per missing bound.
    """
    missing = [s["run"] for s in group["strategies"]
               if s.get("matched_dp_status") == "no_cached_solve"]
    if not missing:
        return None
    return ("No matched-DP bound is stored for: %s (solve with "
            "`hil_ems_comparison.py --matched-dp solve "
            "--matched-dp-allow-long`)." % ", ".join(missing))


def _frontier_cell(group, run_name):
    rec = (group.get("frontier_verdicts") or {}).get(run_name)
    if not rec:
        return "—"
    return "`%s` %s" % (rec.get("id") or "?", rec.get("verdict") or "—")


def render_group_markdown(group, index):
    """The Markdown section for one profile group."""
    lam = group["lambda_soc_per_g"]
    band = group.get("lambda_band") or []
    ref = group.get("reference")
    bnd = group.get("bound")
    L = ["## %d. %s" % (index, group["label"]), ""]
    L.append(
        "This section covers the %d energy-management runs that share the "
        "drive profile `%s` over %.0f s. The equivalent-hydrogen column "
        "prices the state-of-charge difference at lambda = %.3f SoC/g%s."
        % (len(group["strategies"]), group["profile_id"], group["duration_s"],
           lam,
           "" if len(band) < 2 else
           " (measured band %.3f to %.3f)" % (band[0], band[1])))
    L.append("")
    L.append("- reference leg: %s" % ("`%s`" % ref if ref else
                                      "none registered on this profile"))
    L.append("- lower-bound leg: %s" % ("`%s`" % bnd if bnd else
                                        "none registered on this profile"))
    L.append("- reference delta SoC: %s" % _num(group.get("dsoc_ref"), "%+.6f"))
    L.append("")

    fig1 = group["figures"].get("tradeoff")
    fig2 = group["figures"].get("traces")
    if fig1:
        L += ["Figure %d.1 places every strategy in the hydrogen against "
              "state-of-charge plane, joins each run to its delta-SoC-matched "
              "dynamic-programming bound, and draws the constant "
              "equivalent-hydrogen contours at the campaign lambda." % index,
              "",
              "![Figure %d.1](%s)" % (index, fig1), ""]
    if fig2:
        L += ["Figure %d.2 overlays the cumulative hydrogen and the state of "
              "charge of every strategy against time, in the colours of "
              "Figure %d.1." % (index, index),
              "",
              "![Figure %d.2](%s)" % (index, fig2), ""]

    L += ["Table %d.1 lists the measured totals, the matched bound, and the "
          "SoC-priced ranking." % index,
          "",
          "| run | strategy | role | h2 run (g) | delta SoC (run) |"
          " h2 DP bound (g) | deviation vs DP | lambda_term |"
          " DP residual / status | eq-H2 (g) | vs reference | vs bound |"
          " suite frontier |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in group["strategies"]:
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                 " %s | %s |"
                 % (s["run"],
                    "`%s`" % s["strategy"] if s.get("strategy") else "—",
                    s.get("role") or "—",
                    _num(s.get("h2_run_g"), "%.7f"),
                    _num(s.get("delta_soc_run"), "%+.6f"),
                    _num(s.get("h2_dp_g"), "%.7f"),
                    "—" if s.get("pct_deviation") is None
                    else "%+.2f %%" % s["pct_deviation"],
                    _num(s.get("lambda_term"), "%.6f"),
                    _dp_status_cell(s),
                    _num(s.get("eq_h2_g"), "%.7f"),
                    _num(s.get("vs_reference"), "%.4f"),
                    _num(s.get("vs_bound"), "%.4f"),
                    _frontier_cell(group, s["run"])))
    L.append("")
    L.append(
        "The `vs reference` and `vs bound` columns are this stage's own "
        "equivalent-hydrogen ratios and exist for every leg. The `suite "
        "frontier` column is the suite's registered verdict from "
        "`results.json`, and it exists only on a leg that is a registered "
        "CANDIDATE: a reference or bound leg carries no verdict of its own.")
    L.append("")

    role_notes = []
    for s in group["strategies"]:
        note = s.get("strategy_note")
        if note and (s["strategy"], note) not in role_notes:
            role_notes.append((s["strategy"], note))
    if role_notes:
        L += ["Strategy roles, carried from the simulator's strategy "
              "registry. A strategy whose registry entry says its totals are "
              "not a competitive score must not be ranked as one:", ""]
        for strategy, note in role_notes:
            L.append("> `%s` %s" % (strategy, note))
            L.append("")

    gap = bound_gap_line(group)
    if gap:
        L += [gap, ""]

    # Only the PHYSICS boundaries survive as block quotes: deduplicated by
    # text, with the per-run prefill hints removed by prefix (bound_gap_line
    # states that gap once, above).
    notes = []
    for s in group["strategies"]:
        for n in s.get("matched_dp_notes") or []:
            if n.startswith(NO_CACHED_SOLVE_NOTE_PREFIX) or n in notes:
                continue
            notes.append(n)
    if notes:
        L += ["Boundaries carried from the per-run matched-DP blocks:", ""]
        for n in notes:
            L.append("> %s" % n)
            L.append("")
    return L


COMMENTARY_HEADING = "## Commentary"


def existing_commentary(path):
    """The hand-written Commentary of a previously rendered document, or None.

    THE STAGE REGENERATES THE WHOLE FILE ON EVERY PASS, and the Commentary is
    the one part of it a human wrote. Losing that to a routine
    `hil_report_analysis.py` run would be silent data loss, so the text after
    the Commentary heading is read back and carried into the new render. The
    untouched placeholder returns None, which renders the placeholder again.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if COMMENTARY_HEADING not in text:
        return None
    body = text.split(COMMENTARY_HEADING, 1)[1].strip()
    if not body or body == COMMENTARY_PLACEHOLDER:
        return None
    return body


def render_markdown(payload, commentary=None):
    """The whole EMS_COMPARISON.md body for one campaign.

    `commentary` replaces the placeholder when a previous pass's hand-written
    Commentary is being carried forward.
    """
    meta = payload.get("meta") or {}
    L = ["# EMS strategy comparison", "",
         "- report: %s" % payload.get("report", "—"),
         "- report date: %s" % (meta.get("date") or "—"),
         "- target fw: v%s" % (meta.get("target_fw") or "—"),
         "- lambda: %.3f SoC/g" % payload.get(
             "lambda_soc_per_g", _suite.EMS_EQ_H2_LAMBDA_SOC_PER_G),
         "- profile groups rendered: %d" % len(payload.get("groups") or []),
         "",
         "This document compares the energy-management strategies of one "
         "campaign, grouped by the drive stimulus each was driven with. Every "
         "number below is generated from `%s` in this folder; the Commentary "
         "section at the end is written by hand." % JSON_NAME,
         ""]
    groups = payload.get("groups") or []
    if not groups:
        L += ["No profile group in this campaign holds %d or more "
              "energy-management runs, so there is nothing to compare."
              % MIN_RUNS_PER_GROUP, ""]
    for i, g in enumerate(groups, start=1):
        L += render_group_markdown(g, i)

    L += [COMMENTARY_HEADING, "", commentary or COMMENTARY_PLACEHOLDER, ""]
    return "\n".join(L) + "\n"


def _json_payload(report_dir, groups, meta):
    """The serializable form of the collected groups.

    Underscore-prefixed keys are the stage's own working state -- the decimated
    trace arrays and the figure-staleness input paths -- and are stripped: the
    JSON is the document's data source, not a memory dump.
    """
    out_groups = []
    for g in groups:
        gg = {k: v for k, v in g.items()
              if k != "strategies" and not k.startswith("_")}
        gg["strategies"] = [{k: v for k, v in s.items()
                             if not k.startswith("_")}
                            for s in g["strategies"]]
        out_groups.append(gg)
    return {
        "tool": "hil_ems_comparison",
        "format_version": 1,
        "report": Path(report_dir).name,
        "meta": meta,
        "lambda_soc_per_g": _suite.EMS_EQ_H2_LAMBDA_SOC_PER_G,
        "lambda_band": list(_suite.EMS_EQ_H2_LAMBDA_BAND),
        "groups": out_groups,
    }


# ==========================================================================
# Stage entry point
# ==========================================================================

def build_ems_comparison(report_dir, matched_dp="lookup", matched_dp_tol=None,
                         matched_dp_strict=False, matched_dp_allow_long=False,
                         force=False, log=print):
    """Run the whole stage over one report folder.

    Returns the JSON payload it wrote, or None when the campaign holds no
    comparable group -- in which case NO artifact is written, because an
    EMS_COMPARISON.md with no comparison in it is a misleading file rather
    than an honest empty one.
    """
    hra = _hra()
    report_dir = Path(report_dir)
    groups = collect_group_data(
        report_dir, matched_dp=matched_dp, matched_dp_tol=matched_dp_tol,
        matched_dp_strict=matched_dp_strict,
        matched_dp_allow_long=matched_dp_allow_long, log=log)
    if not groups:
        log("[hil_ems_comparison] no comparable EMS profile group in %s"
            % report_dir)
        return None
    render_figures(groups, report_dir, force=force)
    results_json = hra._read_json(report_dir / "results.json") or {}
    payload = _json_payload(report_dir, groups, results_json.get("meta", {}))
    hra.write_json_atomic(report_dir / JSON_NAME, payload)
    md_path = report_dir / MARKDOWN_NAME
    carried = existing_commentary(md_path)
    hra.write_text_atomic(md_path, render_markdown(payload,
                                                   commentary=carried))
    if carried:
        log("[hil_ems_comparison] carried the existing hand-written "
            "Commentary forward")
    log("[hil_ems_comparison] %d group(s), %d run(s); wrote %s"
        % (len(groups), sum(len(g["strategies"]) for g in groups),
           report_dir / MARKDOWN_NAME))
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="EMS-strategy comparison for one HIL campaign report "
                    "folder.")
    ap.add_argument("report_dir",
                    help="HIL suite report folder (resolved against CWD, "
                         "then repo-root 'HIL Results/')")
    ap.add_argument("--matched-dp", default="lookup",
                    choices=["off", "lookup", "solve"],
                    help="delta-SoC-matched DP bound source. 'lookup' "
                         "(default) reads tools/dp_db/ and never solves; "
                         "'solve' computes and stores a missing bound, which "
                         "costs tens of minutes per FTP-75 leg; 'off' omits "
                         "the bound columns")
    ap.add_argument("--matched-dp-tol", type=float, default=None,
                    help="terminal-SoC tolerance a cached bound may differ by")
    ap.add_argument("--matched-dp-strict", action="store_true",
                    help="refuse a cached bound solved under a different "
                         "hil_plant_sim constant set")
    ap.add_argument("--matched-dp-allow-long", action="store_true",
                    help="permit --matched-dp solve on a scenario longer than "
                         "the solve gate (FTP-75 costs tens of minutes)")
    ap.add_argument("--force", action="store_true",
                    help="regenerate figures that already exist")
    args = ap.parse_args(argv)

    hra = _hra()
    try:
        report_dir = hra.resolve_report_dir(args.report_dir)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    payload = build_ems_comparison(
        report_dir, matched_dp=args.matched_dp,
        matched_dp_tol=args.matched_dp_tol,
        matched_dp_strict=args.matched_dp_strict,
        matched_dp_allow_long=args.matched_dp_allow_long, force=args.force)
    return 0 if payload else 1


if __name__ == "__main__":
    sys.exit(main())
