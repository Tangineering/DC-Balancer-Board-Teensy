#!/usr/bin/env python3
"""bt6_bag_launch.py - battle-test round 6 (transient lens): bus-side current at a launch from standstill.

Question: IC1 revision 9 section 9.7 exit step 4 releases the motor command at the BT_BUS re-close WRITE, while
D-BT-EN conducts only t_D_ON + 19.77 ms later (27.8-31.8 ms, calc9 section 1). For a variant D-s window that ends on a
v_setpoint step, the launch current is therefore carried by the FC alone for about 28-32 ms (plus the bonded
confirmation). Row F62 calls the launch bus power "small (UNCONFIRMED, gate W2b)". This script measures it on the
22 Pi bags.

Run with the miniforge interpreter (needs numpy and mcap_ros2), from the repo root or anywhere:
    C:/Users/ricky/miniforge3/python.exe calc/bt6_bag_launch.py > calc/bt6_bag_launch_output.txt

Data: /vehicle_state (50 Hz, Pi receive time) and /ems_command, column map tools/rosbag_analysis/scout_bags.py.
Bus-side total = I_fc + I_batt (the two INA253 boost-output channels; the convention of facts_purge_demand s5).
Launch rule (stated, used for every number):
  * an /ems_command sample with v_setpoint > 0.05 m/s whose preceding command was <= 0.05 m/s;
  * the vehicle at standstill: |v_actual| < 0.05 m/s on the last /vehicle_state sample at or before the step;
  * the stack running: V_fc >= 7.0 V at the step (otherwise the FC could not carry it in a window anyway).
Reported: the bus-side total in the 200 ms before the step (median), and the maximum bus-side total over the first
40 ms, 60 ms, 100 ms and 200 ms after the step, against OC_FC 1.4 A (ino LIMIT, one raw sample) and the 1.25 A governor
ceiling. The 50 Hz sample spacing and the transport jitter mean a 40 ms window holds 1-2 samples: a one-sample peak
can be missed, so the maxima are LOWER bounds on the true peak.
"""
import glob
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools", "rosbag_analysis"))
from scout_bags import VS, EC, load_bag  # noqa: E402

OC_FC, GOV = 1.4, 1.25
WINS = (0.040, 0.060, 0.100, 0.200)

rows = []
for d in sorted(glob.glob(os.path.join(REPO, "logs", "rosbags", "rosbag_*"))):
    f = glob.glob(os.path.join(d, "*.mcap"))
    if not f:
        continue
    b = load_bag(f[0])
    t, vs, te, ec = b["vs_t"], b["vs"], b["ec_t"], b["ec"]
    if len(t) < 10 or len(te) < 2:
        continue
    vsp = ec[:, EC.index("v_setpoint")]
    va = vs[:, VS.index("v_actual")]
    itot = vs[:, VS.index("I_fc")] + vs[:, VS.index("I_batt")]
    vfc = vs[:, VS.index("V_fc")]
    for k in range(1, len(te)):
        if not (vsp[k] > 0.05 and vsp[k - 1] <= 0.05):
            continue
        ts = te[k]
        j = np.searchsorted(t, ts, side="right") - 1
        if j < 10 or abs(va[j]) >= 0.05 or vfc[j] < 7.0:
            continue
        pre = itot[(t >= ts - 0.200) & (t <= ts)]
        r = dict(bag=os.path.basename(d), ts=ts, vsp=vsp[k], pre=float(np.median(pre)) if len(pre) else float("nan"))
        for w in WINS:
            sel = itot[(t > ts) & (t <= ts + w)]
            r[w] = float(sel.max()) if len(sel) else float("nan")
        rows.append(r)

print(f"Launches from standstill with the stack running: {len(rows)} (22 bags scanned)")
if rows:
    for w in WINS:
        a = np.array([r[w] for r in rows if not np.isnan(r[w])])
        print(f"  max bus-side total within {w * 1e3:4.0f} ms of the step: median {np.median(a):5.3f} A, p90 "
              f"{np.percentile(a, 90):5.3f} A, max {a.max():5.3f} A; above 1.25 A: {int((a > GOV).sum())}, above "
              f"1.40 A (OC_FC): {int((a > OC_FC).sum())} of {len(a)}")
    pre = np.array([r["pre"] for r in rows])
    print(f"  pre-step bus-side total (median of the 200 ms before): median {np.nanmedian(pre):5.3f} A, max {np.nanmax(pre):5.3f} A")
    print("\n  per launch (bag, t, v_setpoint, pre, max@40/60/100/200 ms):")
    for r in rows:
        print(f"   {r['bag']:42s} {r['ts']:8.2f} s  vsp {r['vsp']:4.2f}  pre {r['pre']:5.3f}  "
              f"{r[0.040]:5.3f} {r[0.060]:5.3f} {r[0.100]:5.3f} {r[0.200]:5.3f}")
