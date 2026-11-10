#!/usr/bin/env python3
"""purge_seq_bags.py - H-20 purge statistics from the 22 Pi rosbags, for the purge-sequencing
fact sheet (facts_purge_sequencing.md, sections 2 and 6).

Run with the miniforge interpreter (needs numpy and mcap_ros2):
    C:/Users/ricky/miniforge3/python.exe purge_seq_bags.py > purge_seq_bags_output.txt

Data: logs/rosbags/*/ *.mcap, /vehicle_state at 50 Hz (tools/rosbag_analysis/scout_bags.py
column map). Times are Pi receive times (log_time), not Teensy times, so every edge carries the
20 ms sample period plus the transport jitter (scout_bags.py docstring).

Detection rule (stated here, used for every number):
  * a stack is "running" over a sample when V_fc >= 7.0 V (V_FC_ARM_THRESH, ino:2278);
  * a purge ONSET is the first sample with V_fc < 6.0 V whose preceding sample was >= 7.0 V
    (6.0 V is the onset level the BQ25798 design F.4 used; the fw v30 trip limit is 4.5 V,
    LIMIT_V_FC_MIN ino:2148, and both are reported);
  * the purge END is the first later sample with V_fc >= 6.0 V;
  * an interval is the onset-to-onset time inside one bag; intervals outside 8-13 s are counted
    as "not a consecutive pair" (stack stopped, bag gap, missed onset) and excluded from the
    statistics but listed.
No value is invented: everything printed is computed from the bags.
"""
import glob
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools", "rosbag_analysis"))
from scout_bags import VS, load_bag  # noqa: E402

V_RUN, V_ONSET, V_TRIP = 7.0, 6.0, 4.5
FC_BUS, BT_BUS = 0x01, 0x02


def col(b, n):
    return b["vs"][:, VS.index(n)]


def purges(b):
    t = b["vs_t"]
    vfc = col(b, "V_fc")
    out = []
    i = 1
    n = len(t)
    while i < n:
        if vfc[i] < V_ONSET and vfc[i - 1] >= V_RUN:
            j = i
            while j < n and vfc[j] < V_ONSET:
                j += 1
            if j >= n:
                break
            out.append((i, j))
            i = j
        i += 1
    return out


def main():
    bags = sorted(glob.glob(os.path.join(REPO, "logs", "rosbags", "rosbag_*")))
    rows, intervals, int_load, pred_err, excluded = [], [], [], [], []
    print("Section 1. Per-bag purge census (50 Hz /vehicle_state)")
    print(f"{'bag':<44}{'dur_s':>7}{'run_s':>7}{'n':>4}{'int_med':>8}")
    for p in bags:
        try:
            b = load_bag(p)
        except SystemExit as e:
            print(f"{os.path.basename(p):<44} skipped: {e}")
            continue
        if len(b["vs_t"]) < 10:
            print(f"{os.path.basename(p):<44} no /vehicle_state")
            continue
        t = b["vs_t"]
        dt = np.median(np.diff(t))
        vfc, vbus = col(b, "V_fc"), col(b, "V_bus")
        ifc, ibt = col(b, "I_fc"), col(b, "I_batt")
        sw = col(b, "switch_state").astype(int)
        st = col(b, "error_source_state")
        run_s = float(np.sum(vfc >= V_RUN) * dt)
        ps = purges(b)
        on_t = [t[i] for i, _ in ps]
        bag_int = []
        for k, (i, j) in enumerate(ps):
            pre = (t >= t[i] - 0.30) & (t <= t[i] - 0.04)
            dur = t[j] - t[i]
            below_trip = int(np.sum(vfc[i:j] < V_TRIP))
            w = slice(max(i - 1, 0), min(j + 3, len(t)))
            topo_pre = sw[i - 1]
            rows.append(dict(
                bag=os.path.basename(p), t=t[i], dur=dur, nsamp=j - i, n_trip=below_trip,
                vfc_min=float(vfc[i:j].min()), vbus_pre=float(np.mean(vbus[pre])) if pre.any() else np.nan,
                vbus_min=float(vbus[w].min()), ifc_pre=float(np.mean(ifc[pre])) if pre.any() else np.nan,
                ibt_pre=float(np.mean(ibt[pre])) if pre.any() else np.nan,
                ibt_max=float(ibt[w].max()), ifc_min=float(ifc[w].min()),
                fc_bus=bool(topo_pre & FC_BUS), bt_bus=bool(topo_pre & BT_BUS),
                bt_bus_any=bool(np.any(sw[w] & BT_BUS)), sw_seq=[int(x) for x in sw[w]]))
            if k > 0:
                d = on_t[k] - on_t[k - 1]
                if 8.0 <= d <= 13.0:
                    intervals.append(d)
                    bag_int.append(d)
                    seg = (t >= on_t[k - 1]) & (t < on_t[k])
                    int_load.append((d, float(np.mean(ifc[seg])), float(np.mean(ifc[seg] * vbus[seg]))))
                else:
                    excluded.append((os.path.basename(p), round(on_t[k - 1], 2), round(d, 2)))
            # predictor: last onset + median of the last 5 valid intervals in this bag
            if len(bag_int) >= 4 and k > 0 and 8.0 <= on_t[k] - on_t[k - 1] <= 13.0:
                hist = bag_int[-6:-1] if len(bag_int) >= 6 else bag_int[:-1]
                if len(hist) >= 3:
                    pred_err.append(on_t[k] - (on_t[k - 1] + float(np.median(hist))))
        med = f"{np.median(bag_int):8.3f}" if bag_int else "       -"
        print(f"{os.path.basename(p):<44}{t[-1]-t[0]:7.0f}{run_s:7.0f}{len(ps):4d}{med}")

    iv = np.array(intervals)
    print("\nSection 2. Onset-to-onset interval, consecutive pairs only (8-13 s)")
    print(f"  n = {len(iv)}; median {np.median(iv):.3f} s; mean {iv.mean():.3f} s; sd {iv.std(ddof=1):.3f} s")
    print(f"  min {iv.min():.3f} s; max {iv.max():.3f} s; p1 {np.percentile(iv,1):.3f}; p99 {np.percentile(iv,99):.3f}")
    print(f"  excluded pairs (not consecutive): {len(excluded)}; first 10: {excluded[:10]}")
    il = np.array(int_load)
    if len(il) > 5:
        a, c = np.polyfit(il[:, 1], il[:, 0], 1)
        r = np.corrcoef(il[:, 1], il[:, 0])[0, 1]
        print(f"  load dependence: interval = {c:.3f} + {a:.4f} * mean I_fc[A]; r = {r:.3f}; "
              f"mean I_fc range {il[:,1].min():.3f}-{il[:,1].max():.3f} A")
        a2, c2 = np.polyfit(il[:, 2], il[:, 0], 1)
        print(f"  vs mean bus-side FC power: slope {a2:.4f} s/W over {il[:,2].min():.2f}-{il[:,2].max():.2f} W")

    pe = np.array(pred_err)
    print("\nSection 3. Prediction error of 'last onset + median of the last <=5 intervals' (onset - t_pred)")
    if len(pe):
        print(f"  n = {len(pe)}; mean {pe.mean()*1e3:.1f} ms; sd {pe.std(ddof=1)*1e3:.1f} ms; "
              f"min (earliest) {pe.min()*1e3:.1f} ms; max (latest) {pe.max()*1e3:.1f} ms")
        for q in (0.1, 1, 5, 50, 95, 99, 99.9):
            print(f"  p{q}: {np.percentile(pe, q)*1e3:7.1f} ms")
        print("  NOTE: includes the 20 ms sample quantisation and Pi receive-time jitter on both onsets.")

    R = rows
    dur = np.array([r["dur"] for r in R])
    print("\nSection 4. Purge depth and duration (all detected onsets)")
    print(f"  n = {len(R)}; duration below 6.0 V: median {np.median(dur)*1e3:.0f} ms, "
          f"min {dur.min()*1e3:.0f}, max {dur.max()*1e3:.0f} ms (+/-20 ms per edge)")
    print(f"  samples below 4.5 V (fw v30 trip) per purge: "
          f"{np.bincount([r['n_trip'] for r in R]).tolist()} (index = count)")
    vmin = np.array([r["vfc_min"] for r in R])
    print(f"  V_fc minimum at 50 Hz: median {np.median(vmin):.2f} V, min {vmin.min():.2f}, max {vmin.max():.2f} V")

    print("\nSection 5. Bus response by pre-purge topology (sample before onset)")
    for name, f in (("two-source (FC_BUS and BT_BUS closed)", lambda r: r["fc_bus"] and r["bt_bus"]),
                    ("FC-only (FC_BUS closed, BT_BUS open)", lambda r: r["fc_bus"] and not r["bt_bus"]),
                    ("BT-only (BT_BUS closed, FC_BUS open)", lambda r: r["bt_bus"] and not r["fc_bus"]),
                    ("neither", lambda r: not r["fc_bus"] and not r["bt_bus"])):
        S = [r for r in R if f(r)]
        if not S:
            print(f"  {name}: n = 0")
            continue
        dv = np.array([r["vbus_pre"] - r["vbus_min"] for r in S])
        vm = np.array([r["vbus_min"] for r in S])
        ip = np.array([r["ifc_pre"] for r in S])
        print(f"  {name}: n = {len(S)}; V_bus min {vm.min():.2f}-{vm.max():.2f} V (median {np.median(vm):.2f}); "
              f"sag {np.median(dv):.2f} V median, {dv.max():.2f} V max; pre-purge I_fc {np.nanmin(ip):.3f}-{np.nanmax(ip):.3f} A")
        if "FC-only" in name:
            for r in S:
                print(f"    {r['bag']} t={r['t']:.2f}s Vbus_pre={r['vbus_pre']:.2f} Vbus_min={r['vbus_min']:.2f} "
                      f"Ifc_pre={r['ifc_pre']:.3f} Ibt_max={r['ibt_max']:.3f} Vfc_min={r['vfc_min']:.2f} "
                      f"sw={r['sw_seq']}")
    two = [r for r in R if r["fc_bus"] and r["bt_bus"]]
    if two:
        ibs = np.array([r["ibt_max"] - r["ibt_pre"] for r in two])
        ifp = np.array([r["ifc_pre"] for r in two])
        print(f"  two-source: I_batt rise during purge median {np.median(ibs):.3f} A, max {ibs.max():.3f} A; "
              f"pre-purge I_fc median {np.median(ifp):.3f} A, max {ifp.max():.3f} A")


if __name__ == "__main__":
    main()
