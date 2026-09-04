#!/usr/bin/env python3
"""Governor-regime census over a run_hil_suite.py campaign (2026-09-03 exploration).

For every State-2 tick of the named EMS runs, classifies the share loop as
open-loop HOLD (I_tot < 0.55 A), hysteresis band (0.55-0.60 A), or closed loop,
and inside closed loop reports how often the minority clip binds on the
COMMANDED in-band share (`cmd_share_sp`, the value on the wire; NOT
`cmd_share_sp_raw`, which is the pre-clip policy output and is out of band on
the SDP/DP legs).  Also prints the I_tot histogram and the commanded-minority
quantiles.  Source of the numbers in
docs/modeling/low_current_share_stability_20260903.md Table 1.

Run (stdlib only):
    .venv_hil/Scripts/python.exe tools/probes/lowcurrent_hil_census.py \
        --report "HIL Results/hil_report_20260903_063659" [--runs ems-sdp ems-ftp75-sdp ...]
"""
import argparse
import csv
import os

DEFAULT_RUNS = ["ems-sdp", "ems-ftp75-sdp", "ems-ftp75-dp", "ems-ftp75-mpc",
                "ems-ftp75c-sdp", "ems-ftp75-socband", "ems-ftp75-5050"]
IMIN = 0.30          # SHARE_MINORITY_I_MIN_A
OL_EXIT = 0.55       # 2*IMIN - SHARE_GOV_OL_HYST_A
CL_ENTRY = 0.60      # 2*IMIN
BAND = (0.15, 0.85)  # DROOP_R_MIN / DROOP_R_MAX


def census(path):
    n = below = band = clipbind = 0
    hist = {}
    tot_list, minority_cmd = [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if row["state"] != "2":
                continue
            try:
                ifc = float(row["I_fc"]); ib = float(row["I_batt"])
                sp = float(row["cmd_share_sp"])
            except ValueError:
                continue
            tot = ifc + ib
            n += 1
            tot_list.append(tot)
            b = min(int(tot / 0.25), 12)
            hist[b] = hist.get(b, 0) + 1
            if tot < OL_EXIT:
                below += 1
            elif tot < CL_ENTRY:
                band += 1
            elif BAND[0] <= sp <= BAND[1]:
                lo = IMIN / tot
                if sp < lo or sp > 1.0 - lo:
                    clipbind += 1
            if BAND[0] <= sp <= BAND[1]:
                minority_cmd.append(min(sp, 1.0 - sp) * tot)
    return n, below, band, clipbind, hist, sorted(tot_list), sorted(minority_cmd)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", required=True, help="hil_report_<ts> folder")
    ap.add_argument("--runs", nargs="*", default=DEFAULT_RUNS)
    a = ap.parse_args()
    for r in a.runs:
        p = os.path.join(a.report, f"scenario_{r}_hifi", f"hil_scenario_{r}_hifi.csv")
        if not os.path.exists(p):
            print(f"{r:20s} missing: {p}")
            continue
        n, below, band, clip, hist, tots, mins = census(p)
        if not n:
            print(f"{r:20s} no State-2 ticks")
            continue
        med = tots[len(tots) // 2]
        print(f"{r:20s} n={n:6d} I_tot med={med:.3f} A  HOLD(<{OL_EXIT})={100*below/n:5.1f}%  "
              f"hyst-band={100*band/n:4.1f}%  clip-binding(closed)={100*clip/n:5.1f}%  "
              f"=> not tracking={100*(below+band+clip)/n:5.1f}%")
        print("   I_tot hist (0.25 A bins, %):",
              " ".join(f"{k*0.25:.2f}:{100*v/n:.0f}" for k, v in sorted(hist.items())))
        if mins:
            print("   commanded minority (sp*I_tot) quantiles:",
                  " ".join(f"q{q}={mins[int(q*len(mins))]:.3f}" for q in (0.1, 0.25, 0.5, 0.75)))


if __name__ == "__main__":
    main()
