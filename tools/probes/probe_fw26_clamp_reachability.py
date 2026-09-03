#!/usr/bin/env python3
"""Probe: does the fw v26 current-ceiling clamp bind on any REGISTERED stimulus?

WHY THIS EXISTS.  The fw v26 tools round shipped with the claim that "the
highest two-source total on the whole EMS set is 1.462 A (`ems-soc-band`)", and
therefore that the clamp is inert everywhere except the two new
`fw26-clamp-*` scenarios.  The claim was written from the EMS legs alone.  It
omits the `ems-y` quartet, whose combined velocity/share profile reaches a
higher two-source total than any EMS leg, and it compares the RAW total against
the threshold rather than reconstructing what the governor actually commands.

WHAT IS RECONSTRUCTED, in the firmware's own order (`powerBalance()`,
.ino:10079-10378, ported in `tools/governor_model.py`):

  1. the two-source total, I_fc + I_batt, from the campaign CSV;
  2. the governor's load filter, an EMA at SHARE_GOV_FILT_ALPHA = 0.05 per
     tick, run only while the loop is live (State 2 and the total above
     SHARE_I_TOT_MIN_A) so a frozen or latched stretch cannot seed it;
  3. the minority-current clip, lo = SHARE_MINORITY_I_MIN_A / filtered_total
     (capped at 0.5), applied to the COMMANDED share and then to the droop
     band;
  4. the resulting COMMANDED fuel-cell current, sp_clipped * filtered_total.

Step 4 is the quantity `applyShareCurrentCeilings()` compares against
SHARE_GOV_I_FC_CEIL_A.  A tick on which it exceeds the ceiling is a tick on
which fw v26 would have clamped.

WHAT THIS IS NOT.  It is a RECONSTRUCTION from a campaign that ran fw v25, not
a measurement of fw v26.  The board did not clamp on these runs, because the
firmware that produced them had no clamp.  It bounds where fw v26 WILL act, and
that is what the suite's expectation is written against.

Usage:
    C:/Users/ricky/miniforge3/python.exe tools/probes/probe_fw26_clamp_reachability.py \
        --report "HIL Results/hil_report_20260902_041414"

Both the `scenario_<name>_hifi/` folder layout and a flat one are accepted.
"""
import argparse
import csv
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import governor_model as gov_mod                                # noqa: E402

C = gov_mod.GOV_CONST
FILT_ALPHA = C["SHARE_GOV_FILT_ALPHA"]
I_TOT_MIN = C["SHARE_I_TOT_MIN_A"]
I_MINORITY = C["SHARE_MINORITY_I_MIN_A"]
R_MIN, R_MAX = C["DROOP_R_MIN"], C["DROOP_R_MAX"]
FC_CEIL = C["SHARE_GOV_I_FC_CEIL_A"]
RUN_STATE = 2


def scan_csv(path):
    """Reconstruct the commanded fuel-cell current tick by tick.

    Returns a dict of scalars; `peak_fc_cmd_a` is the governing number and
    `ticks_over_ceiling` is how long fw v26 would have held the clamp."""
    filt = 0.0
    seeded = False
    peak_tot = 0.0
    peak_filt = 0.0
    peak_fc_cmd = 0.0
    peak_t = None
    over = 0
    rows = 0
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            try:
                state = int(float(row["state"]))
                i_fc = float(row["I_fc"])
                i_bt = float(row["I_batt"])
                t = float(row["t"])
            except (KeyError, TypeError, ValueError):
                continue
            rows += 1
            tot = i_fc + i_bt
            peak_tot = max(peak_tot, tot)
            if state != RUN_STATE or tot < I_TOT_MIN:
                # The firmware freezes the loop and does not advance the filter
                # on these ticks; a clamp cannot engage on them either.
                continue
            if not seeded:
                filt, seeded = tot, True
            else:
                filt += FILT_ALPHA * (tot - filt)
            peak_filt = max(peak_filt, filt)
            try:
                sp = float(row["cmd_share_sp"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (R_MIN <= sp <= R_MAX):
                # F1 idle in the firmware: an out-of-band setpoint is never
                # actuated, so no clamp runs on it.
                continue
            lo = min(I_MINORITY / filt, 0.5) if filt > 0.0 else 0.5
            sp_c = min(max(sp, lo), 1.0 - lo)
            fc_cmd = sp_c * filt
            if fc_cmd > peak_fc_cmd:
                peak_fc_cmd, peak_t = fc_cmd, t
            if fc_cmd > FC_CEIL:
                over += 1
    return {"rows": rows, "peak_i_tot_raw_a": peak_tot,
            "peak_i_tot_filtered_a": peak_filt,
            "peak_fc_cmd_a": peak_fc_cmd, "peak_fc_cmd_t_s": peak_t,
            "ticks_over_ceiling": over}


def find_runs(report_dir):
    """[(scenario_name, csv_path)] for every scenario run in a report folder."""
    out = []
    for entry in sorted(os.listdir(report_dir)):
        full = os.path.join(report_dir, entry)
        if not os.path.isdir(full) or not entry.startswith("scenario_"):
            continue
        for f in sorted(os.listdir(full)):
            if f.endswith(".csv") and f.startswith("hil_scenario_"):
                name = entry[len("scenario_"):]
                if name.endswith("_hifi"):
                    name = name[:-len("_hifi")]
                elif name.endswith("_simple"):
                    name = name[:-len("_simple")]
                out.append((name, os.path.join(full, f)))
                break
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", required=True,
                    help="a HIL Results/hil_report_<stamp> folder")
    ap.add_argument("--json", default=None, help="write the table as JSON")
    args = ap.parse_args(argv)

    runs = find_runs(args.report)
    if not runs:
        ap.error("no scenario runs under %s" % args.report)

    results = {}
    for name, path in runs:
        results[name] = scan_csv(path)

    print("fw v26 current-ceiling reachability, reconstructed from %s"
          % os.path.basename(args.report.rstrip("/\\")))
    print("ceiling %.3f A, minority floor %.2f A, filter alpha %.3f"
          % (FC_CEIL, I_MINORITY, FILT_ALPHA))
    print("%-26s %9s %9s %9s %8s %7s"
          % ("scenario", "I_tot_raw", "I_tot_filt", "FC_cmd", "t[s]", "ticks"))
    order = sorted(results, key=lambda k: -results[k]["peak_fc_cmd_a"])
    for name in order:
        r = results[name]
        print("%-26s %9.4f %9.4f %9.4f %8s %7d"
              % (name, r["peak_i_tot_raw_a"], r["peak_i_tot_filtered_a"],
                 r["peak_fc_cmd_a"],
                 "-" if r["peak_fc_cmd_t_s"] is None
                 else "%.3f" % r["peak_fc_cmd_t_s"],
                 r["ticks_over_ceiling"]))
    binding = [n for n in order if results[n]["ticks_over_ceiling"] > 0]
    print("")
    if binding:
        print("THE CLAMP BINDS on %d of %d runs: %s"
              % (len(binding), len(results), ", ".join(binding)))
    else:
        print("the clamp binds on NO run of this campaign")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=1, sort_keys=True)
        print("wrote %s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
