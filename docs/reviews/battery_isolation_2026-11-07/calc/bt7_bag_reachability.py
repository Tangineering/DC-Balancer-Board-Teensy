"""Battle-test round 7 (logic lens): power-cycle reachability evidence for variants P and D-s on the Pi bags.
Reuses purge_demand_budget.load_bags() (same loader as bt6_req_ds_request_gate.py).  numpy required:
  C:/Users/ricky/miniforge3/python.exe bt7_bag_reachability.py > bt7_bag_reachability_output.txt
Per bag: the first EMS charge request (charge_goal > 0.05) against the first launch (|v_actual| > 0.02 m/s), and
the switch_state of the last sample with error_code 0 (SW_FC_BUS 0x01, SW_BT_BUS 0x02; PLAN.md section 6b), plus the
standstill time with FC_BUS LOW and BT_BUS HIGH (the battery-only selector state).  mainState is not in the
telemetry, so 'Run' is inferred from the drive (UNCONFIRMED for the pre-launch interval)."""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import purge_demand_budget as p
n_low_end = n_req = n_req_after_launch = 0
for name, t, vs, et, ec, VS, EC in p.load_bags():
    c = lambda k: vs[:, VS.index(k)]
    sw = c("switch_state").astype(int); err = c("error_code"); v = c("v_actual")
    mv = np.abs(v) > 0.02
    t_launch = (t[mv][0] - t[0]) if mv.any() else None
    if len(et):
        r = ec[:, EC.index("charge_goal")] > 0.05
        t_req = (et[r][0] - t[0]) if r.any() else None
    else:
        t_req = None
    ok = np.where(err == 0)[0]
    last = sw[ok[-1]] if len(ok) else None
    still = ~mv & (err == 0)
    bo = still & ((sw & 1) == 0) & ((sw & 2) != 0)
    if last is not None and not (last & 1):
        n_low_end += 1
    if t_req is not None:
        n_req += 1
        n_req_after_launch += (t_launch is not None and t_req > t_launch)
    print("%-44s launch %6s s | first request %6s s | last error-free sw 0x%s FC_BUS %s | standstill battery-only %5.1f s"
          % (name[:44], "-" if t_launch is None else "%.1f" % t_launch, "-" if t_req is None else "%.1f" % t_req,
             "--" if last is None else "%02x" % last, "-" if last is None else ("HIGH" if last & 1 else "LOW"),
             float(bo.sum()) * p.DT))
print("bags with a request: %d; first request after the first launch: %d" % (n_req, n_req_after_launch))
print("bags whose last error-free sample has FC_BUS LOW: %d" % n_low_end)
