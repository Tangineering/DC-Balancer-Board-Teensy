#!/usr/bin/env python3
"""Stage-0 batch scout for bench-log analysis rounds.

Given a set of .BLG logs (names, paths, or a numeric range), emits one
per-run summary row so an orchestrator can plan an agent fan-out without
hand-reading every decode_report.txt. For each run it reports:

  - analysis-folder completeness (CSV + decode_report.txt + >=1 PNG),
  - header facts: format version, fw_version, profile_type,
  - trailer facts: records, close_reason, error_code, dropped
    (close_reason/error_code are "inferred:none" when the trailer is
    absent -- a truncated/MCU-stop log),
  - timing: duration s, median sample interval ms, actual rate Hz,
  - quick stats: V_bus min, |I_cmd| max, v_act max, plus a share tail
    mean/sd over the last 25% of samples gated on I_tot > 0.3 A.

With --fix, any run whose analysis folder is missing or partial is first
run through the full pipeline (make_figures.main on the .BLG ingests and
renders; analysis_config.json is never overwritten -- that guarantee
lives in common.load_or_create_config). Without --fix, incomplete runs
are only flagged.

Output is a fixed-width table on stdout (and --csv FILE for a
machine-readable copy). Read-only apart from the --fix pipeline runs.

Usage:
    python scout_batch.py logs/ML0146.BLG logs/ML0147.BLG
    python scout_batch.py --range ML 146 151          # logs/ML0146..ML0151
    python scout_batch.py --range ML 146 151 --fix --csv scout.csv
"""
import argparse
import io
import sys
from pathlib import Path

import numpy as np

if __package__ in (None, "") and not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from benchlog_analysis import common, ingest_log, make_figures
else:
    from . import common, ingest_log, make_figures

# Columns whose indices we need; resolved per-file from csv_header so the
# scout works across BLG format versions (v1/v2, v3/v4, v5).
_NUM_COLS = ("t_us", "share_act", "v_act", "I_fc", "I_batt", "V_bus", "I_cmd")

FIELDS = ["run", "folder", "ver", "fw", "profile", "records", "close",
          "err", "dropped", "dur_s", "dt_ms", "rate_hz", "Vbus_min",
          "Icmd_max", "vact_max", "share_tail", "notes"]


def _folder_state(blg_path):
    """'complete', 'partial', or 'missing' for blg_path's run directory."""
    run_dir = blg_path.parent / blg_path.stem
    if not run_dir.is_dir():
        return "missing"
    has_csv = any(run_dir.glob("*.csv"))
    has_report = (run_dir / "decode_report.txt").is_file()
    has_png = any(run_dir.glob("*.png"))
    return "complete" if (has_csv and has_report and has_png) else "partial"


def _col(header_fields, name):
    try:
        return header_fields.index(name)
    except ValueError:
        return None


def scout_one(blg_path):
    """Decode blg_path in memory and return a dict of FIELDS values."""
    row = {k: "-" for k in FIELDS}
    row["run"] = blg_path.stem
    row["folder"] = _folder_state(blg_path)
    notes = []

    decode_benchlog = common.decode_benchlog_module()
    try:
        result = decode_benchlog.decode_blg(blg_path.read_bytes())
    except ValueError as e:
        row["notes"] = f"DECODE FAILED: {e}"
        return row

    hdr = result.header
    row["ver"] = hdr["version"]
    row["fw"] = hdr["fw_version"] if hdr["fw_version"] is not None else "pre-v2"
    row["profile"] = f"0x{hdr['profile_type']:02x}"
    row["records"] = result.records_read
    if result.trailer is not None:
        row["close"] = result.trailer["close_reason_str"]
        row["err"] = result.trailer["error_code"]
        row["dropped"] = result.trailer["dropped"]
    else:
        # Truncated log (MCU stop / power loss): no trailer was written.
        row["close"] = "inferred:none"
        row["err"] = "inferred:none"
        notes.append("NO TRAILER (truncated)")
    if result.warnings:
        notes.append(f"{len(result.warnings)} decode warning(s)")

    if result.csv_rows:
        fields = result.csv_header.split(",")
        idx = {n: _col(fields, n) for n in _NUM_COLS}
        data = np.genfromtxt(
            io.StringIO("\n".join(result.csv_rows)), delimiter=",",
            usecols=[i for i in idx.values() if i is not None])
        if data.ndim == 1:
            data = data[None, :]
        # Remap: position within usecols order (sorted by original index).
        kept = sorted(i for i in idx.values() if i is not None)
        pos = {n: kept.index(i) for n, i in idx.items() if i is not None}

        t = data[:, pos["t_us"]]
        t = t - t[0]
        if len(t) > 1:
            dts = np.diff(t)
            row["dur_s"] = f"{t[-1] / 1e6:.2f}"
            row["dt_ms"] = f"{np.median(dts) / 1e3:.3f}"
            row["rate_hz"] = f"{1e6 / np.median(dts):.0f}"
        vbus = data[:, pos["V_bus"]]
        row["Vbus_min"] = f"{np.nanmin(vbus):.2f}"
        row["Icmd_max"] = f"{np.nanmax(np.abs(data[:, pos['I_cmd']])):.2f}"
        if pos.get("v_act") is not None:
            va = data[:, pos["v_act"]]
            if np.any(np.isfinite(va)):
                row["vact_max"] = f"{np.nanmax(np.abs(va)):.3f}"
        # Share tail: last 25% of samples, gated on I_tot > 0.3 A (the
        # ratio is ill-conditioned near zero current).
        i_fc = data[:, pos["I_fc"]]
        i_bt = data[:, pos["I_batt"]]
        n0 = 3 * len(t) // 4
        itot = i_fc[n0:] + i_bt[n0:]
        gate = itot > 0.3
        if np.count_nonzero(gate) >= 10:
            share = i_fc[n0:][gate] / itot[gate]
            # ASCII "+-": the Windows console codepage mangles U+00B1.
            row["share_tail"] = f"{share.mean():.3f}+-{share.std():.3f}"

    row["notes"] = "; ".join(notes) if notes else ""
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("blg", nargs="*", help=".BLG files to scout")
    ap.add_argument("--range", nargs=3, metavar=("PREFIX", "FIRST", "LAST"),
                    help="e.g. --range ML 146 151 -> logs/ML0146..ML0151")
    ap.add_argument("--logs-dir", default="logs",
                    help="directory for --range lookups (default: logs)")
    ap.add_argument("--fix", action="store_true",
                    help="run the ingest+figures pipeline on any run whose "
                         "analysis folder is missing or partial")
    ap.add_argument("--csv", metavar="FILE",
                    help="also write the table as CSV to FILE")
    args = ap.parse_args(argv)

    paths = [Path(p) for p in args.blg]
    if args.range:
        prefix, first, last = args.range
        for n in range(int(first), int(last) + 1):
            hits = [p for p in Path(args.logs_dir).glob(f"{prefix}{n:04d}.*")
                    if p.suffix.lower() == ".blg"]
            if hits:
                paths.extend(hits)
            else:
                print(f"[scout] {prefix}{n:04d}: no .BLG found, skipped",
                      file=sys.stderr)
    if not paths:
        ap.error("no .BLG files given (positional or --range)")

    rows = []
    for p in paths:
        if args.fix and _folder_state(p) != "complete":
            print(f"[scout] {p.stem}: running pipeline (--fix)",
                  file=sys.stderr)
            try:
                run_dir = ingest_log.ingest(p)
                make_figures.make_all(run_dir)
            except (ValueError, OSError) as e:
                print(f"[scout] {p.stem}: pipeline FAILED ({e})",
                      file=sys.stderr)
        rows.append(scout_one(p))

    widths = {f: max(len(f), *(len(str(r[f])) for r in rows)) for f in FIELDS}
    print("  ".join(f.ljust(widths[f]) for f in FIELDS))
    for r in rows:
        print("  ".join(str(r[f]).ljust(widths[f]) for f in FIELDS))

    if args.csv:
        with open(args.csv, "w", encoding="utf-8") as f:
            f.write(",".join(FIELDS) + "\n")
            for r in rows:
                f.write(",".join(f'"{r[c]}"' if "," in str(r[c])
                                 else str(r[c]) for c in FIELDS) + "\n")
        print(f"[scout] wrote {args.csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
