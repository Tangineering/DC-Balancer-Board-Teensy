#!/usr/bin/env python3
"""Ingest a single .BLG bench log into a per-run analysis directory.

Given logs/NAME.BLG (any case of extension), creates the sibling directory
logs/NAME/ and populates it with:

  NAME.csv            -- decoded CSV (tools/decode_benchlog.py format),
                          overwritten every run.
  decode_report.txt    -- the decoder's stderr report lines, one per line,
                          overwritten every run.
  analysis_config.json -- filter-tau config; created from
                          common.DEFAULT_CONFIG on first ingest and NEVER
                          overwritten thereafter (see
                          common.load_or_create_config) so hand-edited taus
                          survive re-ingestion.

Usage: python ingest_log.py FILE.BLG
"""
import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, "") and not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from benchlog_analysis import common
else:
    from . import common


def ingest(blg_path):
    """Decode blg_path and populate its sibling run directory.

    blg_path: path to a .BLG file, e.g. logs/NAME.BLG (case-insensitive
    extension). Returns the Path to the created/updated run directory
    logs/NAME/.

    Raises ValueError (decode_blg's message, with the filename prepended)
    if the file fails to decode.
    """
    blg_path = Path(blg_path)
    if not blg_path.is_file():
        raise ValueError(f"not a file: {blg_path} (expected a .BLG log; "
                         f"pass the .BLG, not the run directory)")
    name = blg_path.stem
    run_dir = blg_path.parent / name

    decode_benchlog = common.decode_benchlog_module()

    with open(blg_path, "rb") as f:
        data = f.read()

    try:
        result = decode_benchlog.decode_blg(data)
    except ValueError as e:
        raise ValueError(f"{blg_path.name}: {e}") from e

    # Only create the run dir once the decode has succeeded, so a bad .BLG
    # doesn't leave a confusing empty directory behind.
    run_dir.mkdir(parents=True, exist_ok=True)

    # Both derived files are written atomically (temp + replace): a crash
    # mid-ingest must never leave a partial CSV, or a stale decode_report.txt
    # sitting next to a newer CSV it doesn't describe.
    csv_path = run_dir / f"{name}.csv"
    tmp = csv_path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="") as f:
        f.write(decode_benchlog.CSV_HEADER + "\n")
        for row in result.csv_rows:
            f.write(row + "\n")
    os.replace(tmp, csv_path)

    report_path = run_dir / "decode_report.txt"
    tmp = report_path.with_suffix(".txt.tmp")
    with open(tmp, "w") as f:
        for line in result.report_lines:
            f.write(line + "\n")
    os.replace(tmp, report_path)

    common.load_or_create_config(run_dir)  # never clobbers an existing one

    return run_dir


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help=".BLG file to ingest")
    args = ap.parse_args()

    try:
        run_dir = ingest(args.file)
    except (ValueError, OSError) as e:
        sys.exit(f"error: {e}")

    with open(run_dir / "decode_report.txt", "r") as f:
        sys.stderr.write(f.read())
    print(f"[ingest_log] wrote {run_dir}")


if __name__ == "__main__":
    main()
