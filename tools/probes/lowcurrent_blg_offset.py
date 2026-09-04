#!/usr/bin/env python3
"""Effective channel-offset current from bench hold windows (2026-09-03 exploration).

Static droop plant (controller_design/system_model.md section 3):
    alpha = r + dV0 * r (1 - r) / (k_d * I_tot)
so in any settled window with both channels conducting,
    dV0 / k_d  [A]  =  (alpha - r) * I_tot / (r (1 - r)),     r = gBT / (gFC + gBT).
The linear CAL-1 value is 0.05 / 0.30 = 0.17 A.  A value proportional to I_tot
is the droop-scale-mismatch (rho) signature rather than a voltage offset.  Printed
per (I_tot, r) bin with the minority current.  Section 2 item 3 of
docs/modeling/low_current_share_stability_20260903.md.

Run (stdlib only; CSVs from tools/decode_benchlog.py as <csv-dir>/<RUN>.csv):
    .venv_hil/Scripts/python.exe tools/probes/lowcurrent_blg_offset.py --csv-dir out TP0017 TP0115 WP0071
"""
import argparse
import csv
import os


def col(rows, k):
    return [float(r[k]) for r in rows]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--csv-dir", required=True)
    ap.add_argument("--window", type=int, default=250)
    ap.add_argument("runs", nargs="+")
    a = ap.parse_args()
    W = a.window
    print("dV0/k_d [A] = (alpha - r) I_tot / (r(1-r)), r = gBT/(gFC+gBT); linear-model value 0.17 A")
    for run in a.runs:
        with open(os.path.join(a.csv_dir, f"{run}.csv"), newline="") as f:
            rows = list(csv.DictReader(f))
        res = []
        for i in range(0, len(rows) - W, W):
            w = rows[i:i + W]
            ifc = col(w, "I_fc"); ib = col(w, "I_batt"); g1 = col(w, "gFC"); g2 = col(w, "gBT")
            mfc = sum(ifc) / W; mb = sum(ib) / W; tot = mfc + mb
            if tot < 0.1 or mfc < 0.02 or mb < 0.02:      # both channels conducting
                continue
            r = [b / (x + b) for x, b in zip(g1, g2) if x + b > 0]
            if len(r) != W:
                continue
            mr = sum(r) / W
            if max(r) - min(r) > 0.03 or not (0.12 < mr < 0.88):   # settled, in band
                continue
            alpha = mfc / tot
            d = alpha - mr
            res.append((tot, mr, alpha, d, d * tot / (mr * (1 - mr)), min(mfc, mb)))
        print(f"== {run}: {len(res)} windows")
        bins = {}
        for x in res:
            bins.setdefault((round(x[0] * 4) / 4, round(x[1], 1)), []).append(x)
        for k in sorted(bins):
            L = bins[k]; n = len(L)
            avg = lambda j: sum(v[j] for v in L) / n
            print(f"   I_tot~{k[0]:4.2f} r~{k[1]:.1f}: alpha {avg(2):.3f}  d=alpha-r {avg(3):+.3f}  "
                  f"dV0/kd {avg(4):+.3f} A  minority {avg(5):.3f} A  [{n}]")


if __name__ == "__main__":
    main()
