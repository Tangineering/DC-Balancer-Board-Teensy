"""Battle-test round 7 (requirements lens): ORIGIN of the recorded charge_goal requests that carry the IC1 rev 10
HR2 figure (446.6 s requested, D-s 107.3 s; bt6_req_ds_request_gate_output.txt, calc10 section 6).
The Pi SDP node (references/EMS/Pi_2026-11-03/EMS/ROS2/sdp_ems_node_2026-10-28B.py:293-319, 376-383) publishes
charge_goal = regen_charge_goal while a REGEN latch stands (armed P_demand < regen_pdem_w 0.0 W, released only when
P_demand > regen_release_w 0.5 W, lines 180-182), and raises it for FC charging only when the SDP solution has
P_batt < -fc_charge_min_w (0.5 W). This script classifies every live request sample by the /drive_cycle P_demand
(data[1], line 288-290) and the /ems_diagnostics P_batt (data[1], line 433) published by the same node.
Classes: REGEN-LATCH = P_demand <= 0.5 W (the regen gate holds charge_goal); FC-CHARGE = P_demand > 0.5 W and
P_batt < -0.5 W; OTHER = neither. Run: miniforge python bt7_req_origin.py > bt7_req_origin_output.txt"""
import os, sys, glob, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import purge_demand_budget as p
import scout_bags as sb
REPO = p.REPO
tot = {}
for path in sorted(glob.glob(os.path.join(REPO, "logs", "rosbags", "rosbag_sdp*"))):
    if not glob.glob(os.path.join(path, "*.mcap")): continue
    b = sb.load_bag(path)
    t, vs, et, ec = b["vs_t"], b["vs"], b["ec_t"], b["ec"]
    if not len(et): continue
    VS, EC = sb.VS, sb.EC
    c = lambda n: vs[:, VS.index(n)]
    sw = c("switch_state").astype(int); live = ((sw & 4) != 0) & (c("error_code") == 0)
    if live.sum() < 50: continue
    idx = np.clip(np.searchsorted(et, t) - 1, 0, len(et) - 1)
    req = ec[idx, EC.index("charge_goal")] > 0.05
    still = np.abs(c("v_actual")) <= 0.02
    dc = b["other"].get("/drive_cycle", []); dg = b["other"].get("/ems_diagnostics", [])
    if not dc or not dg:
        print(f"{os.path.basename(path)}: /drive_cycle {len(dc)} /ems_diagnostics {len(dg)} msgs - cannot classify"); continue
    dct = np.array([x[0] for x in dc]); pdem = np.array([x[1][1] for x in dc])
    dgt = np.array([x[0] for x in dg]); pbat = np.array([x[1][1] for x in dg])
    pd_ = pdem[np.clip(np.searchsorted(dct, t) - 1, 0, len(dct) - 1)]
    pb_ = pbat[np.clip(np.searchsorted(dgt, t) - 1, 0, len(dgt) - 1)]
    regen = pd_ <= 0.5; fcc = (pd_ > 0.5) & (pb_ < -0.5); oth = ~regen & ~fcc
    dt = 0.02
    m = live & req
    row = dict(req=m.sum()*dt, regen=(m&regen).sum()*dt, fcc=(m&fcc).sum()*dt, other=(m&oth).sum()*dt,
               still=(m&still).sum()*dt, still_regen=(m&still&regen).sum()*dt, still_fcc=(m&still&fcc).sum()*dt,
               move_regen=(m&~still&regen).sum()*dt, move_fcc=(m&~still&fcc).sum()*dt,
               pdem_still_max=float(np.max(pd_[m&still])) if (m&still).any() else float('nan'))
    print(f"{os.path.basename(path):40s} " + " ".join(f"{k} {v:6.1f}" for k, v in row.items()))
    for k, v in row.items():
        if k != 'pdem_still_max': tot[k] = tot.get(k, 0) + v
print("TOTALS", {k: round(v, 1) for k, v in tot.items()})
