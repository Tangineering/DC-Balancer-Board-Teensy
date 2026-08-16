#!/usr/bin/env python3
"""Render every registered figure for one bench-log run.

Usage:
    python make_figures.py logs/NAME          # already-ingested run dir
    python make_figures.py logs/NAME.BLG      # ingests first, then renders

Every figure in figures.FIGURES is saved as run_dir/<figure_name>.png at
dpi=150, overwriting silently -- re-running after a hand-edit of
analysis_config.json is the normal workflow, so the PNGs are treated as
derived artefacts. analysis_config.json itself is never rewritten.

A builder may return None to skip itself gracefully (e.g. it needs CSV
columns that only exist on a newer .BLG format than the one being
rendered, such as drive_controller_conditioning's v5-only u_unsat/
drive_x0). A skipped figure is noted on stderr, produces no PNG, and does
not count as an error -- a stale PNG from a previous run of the SAME
format is left in place rather than deleted, since make_all has no way to
tell "never applicable" apart from "not regenerated this run".
"""
import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    if not getattr(sys, "frozen", False):  # frozen: bundle resolves the pkg
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from benchlog_analysis import common, figures, ingest_log
else:
    from . import common, figures, ingest_log


def _find_csv(run_dir):
    """The single *.csv in run_dir. Raises ValueError on 0 or >1 matches."""
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise ValueError(f"not a directory: {run_dir}")
    csvs = sorted(run_dir.glob("*.csv"))
    if not csvs:
        raise ValueError(
            f"no .csv found in {run_dir} -- ingest the .BLG first "
            f"(python ingest_log.py {run_dir}.BLG)")
    if len(csvs) > 1:
        names = ", ".join(p.name for p in csvs)
        raise ValueError(
            f"expected exactly one .csv in {run_dir}, found {len(csvs)}: {names}")
    return csvs[0]


def make_all(run_dir, data=None, cfg=None):
    """Render and save every registered figure for `run_dir`.

    run_dir: path to an ingested run directory (logs/NAME/).
    data:    optional pre-loaded common.load_csv() dict; loaded from the
             directory's single *.csv when omitted.
    cfg:     optional pre-loaded config dict; loaded via
             common.load_or_create_config(run_dir) when omitted.

    Returns the list of saved PNG Paths, in registry order.

    NOTE: this signature is a contract -- the GUI front-end imports and calls
    it directly. Do not change it.
    """
    run_dir = Path(run_dir)
    if data is None:
        data = common.load_csv(_find_csv(run_dir))
    if len(data.get("t_s", ())) == 0:
        # A header-only CSV (zero records -- e.g. an immediate-fault or fully
        # truncated capture) has nothing to plot; fail the same clean way as
        # the 0-CSV case instead of letting builders IndexError on t[0].
        raise ValueError(f"{run_dir} contains 0 samples -- nothing to plot")
    if cfg is None:
        cfg = common.load_or_create_config(run_dir)

    # Figure titles carry the run name; pass it through the cfg dict (on a
    # shallow copy, so a caller-supplied cfg is not mutated).
    cfg = dict(cfg)
    cfg.setdefault("_run_name", run_dir.name)

    saved = []
    for name, builder in figures.FIGURES:
        fig = builder(data, cfg)
        if fig is None:
            # Builder declined (e.g. required columns absent on this run's
            # format version) -- not an error, just nothing to save.
            print(f"[make_figures] skipping {name} (not applicable to this "
                  f"log's format)", file=sys.stderr)
            continue
        out_path = run_dir / f"{name}.png"
        try:
            fig.savefig(out_path, dpi=figures.DPI_DEFAULT)
        finally:
            figures.plt.close(fig)  # release memory even if savefig throws
        saved.append(out_path)
    return saved


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target",
                    help="run directory (logs/NAME) or a .BLG file to ingest")
    args = ap.parse_args()

    target = Path(args.target)
    try:
        if target.suffix.lower() == ".blg":
            run_dir = ingest_log.ingest(target)
        else:
            run_dir = target
        saved = make_all(run_dir)
    except (ValueError, OSError) as e:
        sys.exit(f"error: {e}")

    for path in saved:
        print(path)


if __name__ == "__main__":
    main()
