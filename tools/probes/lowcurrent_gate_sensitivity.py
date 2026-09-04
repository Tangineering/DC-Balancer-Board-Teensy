#!/usr/bin/env python3
"""Closed-loop time recovered by a lower share-loop gate (2026-09-03 exploration).

Reads the recorded I_tot distribution of EMS runs in a campaign folder and, for
each candidate gate (= 2 * SHARE_MINORITY_I_MIN_A), prints the fraction of
State-2 ticks that would be in closed loop and the fraction on which a 0.15
share command would be clip-free (I_tot >= I_min / 0.15).  Source of
docs/modeling/low_current_share_stability_20260903.md Table 2.

Run (stdlib only):
    .venv_hil/Scripts/python.exe tools/probes/lowcurrent_gate_sensitivity.py \
        --report "HIL Results/hil_report_20260903_063659"
"""
import argparse
import csv
import os

DEFAULT_RUNS = ["ems-sdp", "ems-ftp75-sdp", "ems-ftp75c-sdp", "ems-ftp75-socband"]
GATES = (0.60, 0.50, 0.40, 0.30)
SP_EDGE = 0.15


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", required=True)
    ap.add_argument("--runs", nargs="*", default=DEFAULT_RUNS)
    ap.add_argument("--gates", nargs="*", type=float, default=GATES)
    a = ap.parse_args()
    print("closed-loop fraction (I_tot >= gate) / clip-free fraction at sp=%.2f (I_min = gate/2)"
          % SP_EDGE)
    for r in a.runs:
        p = os.path.join(a.report, f"scenario_{r}_hifi", f"hil_scenario_{r}_hifi.csv")
        if not os.path.exists(p):
            print(f"{r:18s} missing")
            continue
        tot = []
        with open(p, newline="") as f:
            for row in csv.DictReader(f):
                if row["state"] != "2":
                    continue
                try:
                    tot.append(float(row["I_fc"]) + float(row["I_batt"]))
                except ValueError:
                    pass
        n = len(tot)
        if not n:
            continue
        line = f"{r:18s}"
        for g in a.gates:
            cl = sum(1 for t in tot if t >= g) / n
            free = sum(1 for t in tot if t >= (g / 2) / SP_EDGE) / n
            line += f" | gate {g:.2f}: closed {100*cl:5.1f}% free {100*free:4.1f}%"
        print(line)
        tot.sort()
        print("     I_tot quantiles:",
              " ".join(f"q{q}={tot[int(q*n)]:.3f}" for q in (0.1, 0.25, 0.5, 0.75, 0.9)))


if __name__ == "__main__":
    main()
