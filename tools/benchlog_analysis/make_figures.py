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
import re
import sys
from pathlib import Path

import numpy as np

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


_FW_VERSION_RE = re.compile(r"fw_version=(\d+)")


def _read_fw_version(run_dir):
    """FW_VERSION from run_dir/decode_report.txt, or None.

    ingest_log writes the decoder's banner verbatim; its first line carries
    `fw_version=N` (or `fw_version=pre-versioning` on a format-v1 header, which
    has no such field). Returns an int, or None when the report is missing,
    unreadable, or reports no numeric version -- callers must treat None as
    "unknown" rather than as any particular firmware.
    """
    try:
        text = (Path(run_dir) / "decode_report.txt").read_text()
    except OSError:
        return None
    m = _FW_VERSION_RE.search(text)
    return int(m.group(1)) if m else None


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
    # The encoder slot pitch became a PER-LOG quantity at the 2026-08-25 wheel
    # change (120 slots -> 90, firmware fw v18), so figures that convert
    # encoder_pos into a distance must know which disc produced the log. The
    # CSV carries no fw column, but ingest_log wrote the decoder's banner to
    # decode_report.txt -- read it back here and inject it the same optional
    # way as _run_name, so the make_all signature (a GUI contract) is unchanged
    # and a hand-built cfg simply falls back to the pre-v18 pitch.
    cfg.setdefault("_fw_version", _read_fw_version(run_dir))
    # HIL provenance (fw v21, flags bit6 0x40): computed directly from the
    # loaded CSV's flags column rather than decode_report.txt, since it's
    # a per-record bit already available in `data`. True if ANY record has
    # the bit set. Every figure's suptitle (see figures._suptitle) shows a
    # warning banner when this is set, so a HIL PNG cannot be mistaken for
    # a real bench run -- see docs/HIL_MODE.md.
    flags_col = data.get("flags")
    hil_build = bool(flags_col is not None and flags_col.size and
                      np.any(np.nan_to_num(flags_col).astype(np.int64) & 0x40))
    cfg.setdefault("_hil_build", hil_build)

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
