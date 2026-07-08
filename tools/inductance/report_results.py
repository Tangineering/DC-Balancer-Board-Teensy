#!/usr/bin/env python3
"""
report_results.py -- cross-config tables + plots from sweep_inductance results.

Reads the results store of EACH config given (they stay separate data sources --
e.g. the BT and FC sides) and emits two report bundles into --outdir:

  1. Mesh convergence @ each config's designated frequency:
        convergence_<freq>.csv / .md / .png
     Table: every stored record on the convergence axis, all verbose columns,
     plus dL% vs the previous (coarser) mesh. Plot: L vs mesh pitch (x inverted,
     coarse -> fine), one series per config -- INDUCTANCE ONLY by design.

  2. Frequency response @ each config's designated mesh:
        freq_sweep.csv / .md / .png
     Table: verbose as above. Plot: semilogx L vs frequency, one series per
     config, legend notes each side's designated mesh.

Missing points warn but never fail, so partially-solved stores still report.

Usage:
    python report_results.py config_vout_fc.json config_vout_bt.json [--outdir out]
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys

from gerber_inductance import load_config
from sweep_inductance import load_store, store_path, find_record

# verbose table columns: (header, record key or callable, format)
COLUMNS = [
    ("config",            "config",           "{}"),
    ("mesh_mm",           "mesh_pitch_mm",    "{:g}"),
    ("freq_Hz",           "freq_hz",          "{:g}"),
    ("L_nH",              lambda r: r["L_H"] * 1e9, "{:.4f}"),
    ("R_mOhm",            lambda r: (r["R_ohm"] * 1e3) if r.get("R_ohm") is not None else None, "{:.4f}"),
    ("dL_pct",            "dL_pct",           "{:+.2f}"),
    ("segments",          "segments",         "{}"),
    ("nodes",             "nodes",            "{}"),
    ("fwd_cells",         "fwd_cells",        "{}"),
    ("ret_cells",         "ret_cells",        "{}"),
    ("fwd_area_mm2",      "fwd_area_mm2",     "{:.2f}"),
    ("ret_area_mm2",      "ret_area_mm2",     "{:.2f}"),
    ("skin_depth_um",     lambda r: r["skin_depth_mm"] * 1e3, "{:.1f}"),
    ("nwxnh_f",           lambda r: f'{r.get("nwinc_f")}x{r.get("nhinc_f")}', "{}"),
    ("nwxnh_r",           lambda r: f'{r.get("nwinc_r")}x{r.get("nhinc_r")}', "{}"),
    ("loop_len_mm",       "loop_len_mm",      "{:.2f}"),
    ("eff_w_mm",          "eff_w_mm",         "{:.2f}"),
    ("analytic_nH",       lambda r: r["analytic_bound_H"] * 1e9, "{:.2f}"),
    ("solve_s",           "solve_seconds",    "{:.0f}"),
    ("solver",            "solver_mode",      "{}"),
    ("deck",              "deck",             "{}"),
    ("timestamp",         "timestamp",        "{}"),
    ("source",            "source",           "{}"),
]

SERIES_STYLE = [  # per-config plot style, cycled
    dict(color="#c1272d", marker="o"),
    dict(color="#0071bc", marker="s"),
    dict(color="#009e46", marker="^"),
    dict(color="#7b2d8b", marker="D"),
]


def side_label(base: str) -> str:
    b = base.lower()
    if "_bt" in b or b.endswith("bt"):
        return "Battery (BT)"
    if "_fc" in b or b.endswith("fc"):
        return "Fuel cell (FC)"
    return base


def fmt_freq(f: float) -> str:
    if f >= 1e6:
        return f"{f/1e6:g}MHz"
    if f >= 1e3:
        return f"{f/1e3:g}kHz"
    return f"{f:g}Hz"


def _cell(rec, key, fmt):
    v = key(rec) if callable(key) else rec.get(key)
    if v is None:
        return ""
    try:
        return fmt.format(v)
    except (ValueError, TypeError):
        return str(v)


def write_table(rows: list[dict], csv_path: str, md_path: str, title: str) -> None:
    headers = [c[0] for c in COLUMNS]
    grid = [[_cell(r, k, f) for (_, k, f) in COLUMNS] for r in rows]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(grid)
    widths = [max(len(h), *(len(g[i]) for g in grid)) if grid else len(h)
              for i, h in enumerate(headers)]
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write("| " + " | ".join(h.ljust(w) for h, w in zip(headers, widths)) + " |\n")
        f.write("|" + "|".join("-" * (w + 2) for w in widths) + "|\n")
        for g in grid:
            f.write("| " + " | ".join(c.ljust(w) for c, w in zip(g, widths)) + " |\n")
    print(f"    wrote {os.path.basename(csv_path)} + {os.path.basename(md_path)} "
          f"({len(rows)} row(s))")


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def collect(config_paths: list[str], outdir: str):
    """Load each config + its results store. Returns list of per-config dicts."""
    sides = []
    for cp in config_paths:
        cfg = load_config(cp)
        base = os.path.splitext(os.path.basename(cp))[0]
        if "sweep" not in cfg:
            print(f"WARNING: {base} has no `sweep` block -- skipped")
            continue
        spath = store_path(outdir, base)
        records = load_store(spath)
        if not records:
            print(f"WARNING: no results store ({os.path.basename(spath)}) or it is "
                  f"empty -- {base} will have no data")
        sides.append({"base": base, "label": side_label(base), "cfg": cfg,
                      "sweep": cfg["sweep"], "records": records})
    return sides


def convergence_report(sides, outdir):
    """Table + plot of L vs mesh pitch @ each side's designated frequency."""
    f_des_all = {float(s["sweep"]["designated_frequency_hz"]) for s in sides}
    tag = fmt_freq(next(iter(f_des_all))) if len(f_des_all) == 1 else "designated"
    rows, series = [], []
    for s in sides:
        f_des = float(s["sweep"]["designated_frequency_hz"])
        meshes = sorted((float(m) for m in s["sweep"]["mesh_sizes_mm"]), reverse=True)
        pts, prev_L = [], None
        for m in meshes:
            rec = find_record(s["records"], m, f_des)
            if rec is None:
                print(f"    WARNING: {s['base']} missing convergence point "
                      f"m={m:g} @ {fmt_freq(f_des)} (not solved yet?)")
                continue
            rec = dict(rec)
            rec["dL_pct"] = (100.0 * (rec["L_H"] - prev_L) / prev_L
                             if prev_L else None)
            prev_L = rec["L_H"]
            rows.append(rec)
            pts.append((m, rec["L_H"] * 1e9))
        if pts:
            series.append((s["label"], f_des, pts))

    write_table(rows, os.path.join(outdir, f"convergence_{tag}.csv"),
                os.path.join(outdir, f"convergence_{tag}.md"),
                f"Mesh convergence of loop inductance @ {tag}")

    if not series:
        print("    (convergence plot skipped: no data)")
        return
    plt = _plt()
    fig, ax = plt.subplots(figsize=(7.6, 4.8))
    # Categorical x-axis: evenly space the distinct pitches (coarse -> fine, left to
    # right) rather than plotting on a linear pitch scale. A linear scale crams the
    # fine meshes together and collides their labels (e.g. 0.11/0.10 mm); even spacing
    # keeps every convergence point legible.
    allx = sorted({p[0] for (_, _, pts) in series for p in pts}, reverse=True)
    xpos = {m: i for i, m in enumerate(allx)}
    for (label, f_des, pts), style in zip(series, SERIES_STYLE * 8):
        xs = [xpos[p[0]] for p in pts]
        ys = [p[1] for p in pts]
        ax.plot(xs, ys, ls="-", lw=2, ms=8, label=f"{label} @ {fmt_freq(f_des)}", **style)
        for (m, y) in pts:
            ax.annotate(f"{y:.3f}", (xpos[m], y), textcoords="offset points",
                        xytext=(0, 9), ha="center", fontsize=8, color=style["color"])
    ax.set_xticks(range(len(allx)))
    ax.set_xticklabels([f"{x:g}" for x in allx])
    ax.set_xlim(-0.4, len(allx) - 0.6)
    ax.set_xlabel("mesh pitch [mm]  (coarse → fine)")
    ax.set_ylabel("loop inductance [nH]")
    ax.set_title(f"Mesh convergence of loop inductance @ {tag}")
    ax.grid(True, alpha=0.3)
    ax.legend()
    out = os.path.join(outdir, f"convergence_{tag}.png")
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"    wrote {os.path.basename(out)}")


def freq_report(sides, outdir):
    """Table + plot of L vs frequency @ each side's designated mesh."""
    rows, series = [], []
    for s in sides:
        m_des = float(s["sweep"]["designated_mesh_mm"])
        freqs = sorted(float(f) for f in s["sweep"]["frequencies_hz"])
        pts, prev_L = [], None
        for f in freqs:
            rec = find_record(s["records"], m_des, f)
            if rec is None:
                print(f"    WARNING: {s['base']} missing frequency point "
                      f"f={fmt_freq(f)} @ m={m_des:g} (not solved yet?)")
                continue
            rec = dict(rec)
            rec["dL_pct"] = (100.0 * (rec["L_H"] - prev_L) / prev_L
                             if prev_L else None)
            prev_L = rec["L_H"]
            rows.append(rec)
            pts.append((f, rec["L_H"] * 1e9))
        if pts:
            series.append((s["label"], m_des, pts))

    write_table(rows, os.path.join(outdir, "freq_sweep.csv"),
                os.path.join(outdir, "freq_sweep.md"),
                "Loop inductance vs frequency @ designated mesh")

    if not series:
        print("    (frequency plot skipped: no data)")
        return
    plt = _plt()
    fig, ax = plt.subplots(figsize=(7.6, 4.8))
    ax.margins(y=0.18)      # headroom so below-trace labels clear the axis spine
    for (label, m_des, pts), style in zip(series, SERIES_STYLE * 8):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.semilogx(xs, ys, ls="-", lw=2, ms=8,
                    label=f"{label} @ {m_des:g} mm mesh", **style)
        # Alternate labels above/below the trace: adjacent points on the log axis
        # (e.g. 500 kHz and 1 MHz) otherwise collide into one unreadable string.
        for k, (x, y) in enumerate(pts):
            above = (k % 2 == 0)
            ax.annotate(f"{y:.3f}", (x, y), textcoords="offset points",
                        xytext=(0, 9 if above else -16), ha="center",
                        fontsize=8, color=style["color"])
    ax.set_xlabel("frequency [Hz]")
    ax.set_ylabel("loop inductance [nH]")
    ax.set_title("Loop inductance vs frequency (designated mesh per side)")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    out = os.path.join(outdir, "freq_sweep.png")
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"    wrote {os.path.basename(out)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("configs", nargs="+",
                    help="one or more sweep configs (e.g. FC and BT)")
    ap.add_argument("--outdir", default=None, help="output dir (default ./out)")
    args = ap.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    outdir = args.outdir or os.path.join(here, "out")
    os.makedirs(outdir, exist_ok=True)

    sides = collect(args.configs, outdir)
    if not sides:
        print("no usable configs")
        return 1
    print("[report] mesh convergence ...")
    convergence_report(sides, outdir)
    print("[report] frequency response ...")
    freq_report(sides, outdir)
    print(f"Done. Reports in {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
