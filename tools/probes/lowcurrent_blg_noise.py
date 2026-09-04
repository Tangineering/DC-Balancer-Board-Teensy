#!/usr/bin/env python3
"""Current-sense noise on decoded bench logs, binned by total current (2026-09-03).

Two modes over CSVs produced by tools/decode_benchlog.py:

  sigma     robust white-noise sigma of I_fc / I_batt / I_tot / share_act per
            steady 500-sample window (first-difference MAD, so slow drift is
            removed), binned by I_tot.  Table 3 of
            docs/modeling/low_current_share_stability_20260903.md.
  spectrum  for explicit windows RUN:i0:i1 — high-frequency sigma after a
            25-sample moving-mean detrend, lag 1-5 autocorrelation, and the
            inter-channel / bus correlations that separate common-mode load
            ripple (positive corr, alternating acf) from sensor noise and from
            light-load conduction exchange (negative corr, slow acf).
  windows   list steady two-source 1000-sample windows (for `spectrum`).

Run (stdlib only; CSVs looked up as <csv-dir>/<RUN>.csv):
    .venv_hil/Scripts/python.exe tools/decode_benchlog.py logs/TP0017.BLG -o out/TP0017.csv
    .venv_hil/Scripts/python.exe tools/probes/lowcurrent_blg_noise.py sigma --csv-dir out TP0017 WP0071
    .venv_hil/Scripts/python.exe tools/probes/lowcurrent_blg_noise.py windows --csv-dir out TP0017
    .venv_hil/Scripts/python.exe tools/probes/lowcurrent_blg_noise.py spectrum --csv-dir out TP0017:5200:6200
"""
import argparse
import csv
import math
import os


def load(csv_dir, run):
    with open(os.path.join(csv_dir, f"{run}.csv"), newline="") as f:
        return list(csv.DictReader(f))


def col(rows, k):
    return [float(r[k]) for r in rows]


def noise_sigma(x):
    d = sorted(x[i + 1] - x[i] for i in range(len(x) - 1))
    n = len(d)
    med = d[n // 2]
    mad = sorted(abs(v - med) for v in d)[n // 2]
    return 1.4826 * mad / math.sqrt(2)


def detrend(x, n=25):
    out = []
    for i in range(len(x)):
        a = max(0, i - n); b = min(len(x), i + n + 1)
        out.append(x[i] - sum(x[a:b]) / (b - a))
    return out


def acf(x, lags):
    m = sum(x) / len(x)
    v = sum((a - m) ** 2 for a in x)
    return [sum((x[i] - m) * (x[i + l] - m) for i in range(len(x) - l)) / v for l in lags]


def corr(x, y):
    mx = sum(x) / len(x); my = sum(y) / len(y)
    sx = math.sqrt(sum((a - mx) ** 2 for a in x)); sy = math.sqrt(sum((a - my) ** 2 for a in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def rms(x):
    return math.sqrt(sum(a * a for a in x) / len(x))


def mode_sigma(csv_dir, runs, W=500):
    for run in runs:
        rows = load(csv_dir, run)
        print(f"== {run}  n={len(rows)}")
        out = []
        for i in range(0, len(rows) - W, W):
            w = rows[i:i + W]
            icmd = col(w, "I_cmd")
            if max(icmd) - min(icmd) > 0.05:
                continue
            ifc = col(w, "I_fc"); ib = col(w, "I_batt")
            tot = [a + b for a, b in zip(ifc, ib)]
            mt = sum(tot) / W
            if mt < 0.05:
                continue
            sa = col(w, "share_act")
            if max(sa) - min(sa) > 0.5:      # dropout chatter, not a hold
                continue
            out.append((mt, sum(ifc) / W, sum(ib) / W, noise_sigma(ifc), noise_sigma(ib),
                        noise_sigma(sa), noise_sigma(tot)))
        bins = {}
        for o in out:
            bins.setdefault(round(o[0] * 4) / 4, []).append(o)
        for b in sorted(bins):
            L = bins[b]; k = len(L)
            avg = lambda j: sum(o[j] for o in L) / k
            print(f"  I_tot~{b:4.2f} A  (I_fc {avg(1):.2f}, I_bt {avg(2):.2f})  sigma: "
                  f"I_fc {1e3*avg(3):5.1f} mA  I_bt {1e3*avg(4):5.1f} mA  I_tot {1e3*avg(6):5.1f} mA  "
                  f"share_act {avg(5):.4f}   [{k} windows]")


def mode_windows(csv_dir, runs, W=1000, max_per_run=3):
    for run in runs:
        rows = load(csv_dir, run)
        i = found = 0
        while i < len(rows) - W and found < max_per_run:
            w = rows[i:i + W]
            ic = col(w, "I_cmd")
            if max(ic) - min(ic) < 0.05:
                fc = sum(col(w, "I_fc")) / W; bt = sum(col(w, "I_batt")) / W
                if fc > 0.03 and bt > 0.03:
                    print(f"{run}:{i}:{i+W}")
                    found += 1
                i += W
            else:
                i += 200


def mode_spectrum(csv_dir, specs):
    for spec in specs:
        run, i0, i1 = spec.split(":")
        rows = load(csv_dir, run)[int(i0):int(i1)]
        t = col(rows, "t_us")
        dt = sorted(t[i + 1] - t[i] for i in range(len(t) - 1))
        ifc = detrend(col(rows, "I_fc")); ib = detrend(col(rows, "I_batt"))
        tot = [a + b for a, b in zip(ifc, ib)]
        vb = detrend(col(rows, "V_bus")); icmd = col(rows, "I_cmd")
        mfc = sum(col(rows, "I_fc")) / len(rows); mb = sum(col(rows, "I_batt")) / len(rows)
        print(f"== {run}[{i0}:{i1}] I_fc {mfc:.2f} I_bt {mb:.2f} A, I_cmd {min(icmd):.2f}-{max(icmd):.2f}, "
              f"dt median {dt[len(dt)//2]:.0f} us (p95 {dt[int(0.95*len(dt))]:.0f})")
        print("   sigma(HF) I_fc %.1f mA  I_bt %.1f mA  I_tot %.1f mA  V_bus %.1f mV"
              % (1e3 * rms(ifc), 1e3 * rms(ib), 1e3 * rms(tot), 1e3 * rms(vb)))
        print("   acf I_fc lags1-5:", " ".join(f"{v:+.2f}" for v in acf(ifc, [1, 2, 3, 4, 5])),
              "| I_bt:", " ".join(f"{v:+.2f}" for v in acf(ib, [1, 2, 3, 4, 5])))
        print(f"   corr(I_fc,I_bt) {corr(ifc, ib):+.2f}   corr(I_fc,V_bus) {corr(ifc, vb):+.2f}"
              f"   corr(I_bt,V_bus) {corr(ib, vb):+.2f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=("sigma", "windows", "spectrum"))
    ap.add_argument("--csv-dir", required=True)
    ap.add_argument("items", nargs="+", help="RUN names, or RUN:i0:i1 for spectrum")
    a = ap.parse_args()
    if a.mode == "sigma":
        mode_sigma(a.csv_dir, a.items)
    elif a.mode == "windows":
        mode_windows(a.csv_dir, a.items)
    else:
        mode_spectrum(a.csv_dir, a.items)


if __name__ == "__main__":
    main()
