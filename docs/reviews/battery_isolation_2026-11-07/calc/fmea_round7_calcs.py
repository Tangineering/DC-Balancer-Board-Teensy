"""FMEA round 7 (FC windows between purges, IC1 revision 10). Run:
C:/Users/ricky/miniforge3/python.exe fmea_round7_calcs.py > fmea_round7_calcs_output.txt
Section 1: Pi sessions - is there any pre-Run (v_setpoint == 0, before the first launch) charge request with the
           H-20 producing, i.e. an opportunity for the State-1 dump check that every D-s window needs (code 12)?
Section 2: request toggles at a stop (charge_goal falling edges while still) - each one ends the in-band substitution.
Section 3: D-s request-gated time once the code-12 precondition is applied (first D-s window only after a State-1
           FC-fed session in the same power cycle)."""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import purge_demand_budget as p
bags = p.load_bags()
print("=" * 100); print("[1] Pre-Run charge requests and H-20 state before the first launch"); print("=" * 100)
n_req_bags = 0; n_prerun_opp = 0
for name, t, vs, et, ec, VS, EC in bags:
    if not len(et): continue
    c = lambda n: vs[:, VS.index(n)]
    req_e = ec[:, EC.index("charge_goal")] > 0.05
    if not req_e.any(): continue
    n_req_bags += 1
    vsp = ec[:, EC.index("v_setpoint")]
    mv = np.nonzero(np.abs(vsp) > 1e-6)[0]
    t_launch = et[mv[0]] if len(mv) else np.inf
    t_req0 = et[np.nonzero(req_e)[0][0]]
    pre = req_e & (et < t_launch)
    vfc = c("V_fc"); fc_on_pre = (vfc > 7.0) & (t < t_launch)
    t_fc_pre = float(np.sum(np.minimum(np.diff(np.append(t, t[-1])), 0.1)[fc_on_pre]))
    opp = pre.any()
    n_prerun_opp += int(opp)
    print(f"  {name[:42]:42s} first command {et[0]:7.2f} s, first launch {t_launch:7.2f} s, first request {t_req0:7.2f} s, "
          f"request before launch: {'YES' if opp else 'no '}, H-20 V_fc>7 V before launch {t_fc_pre:6.1f} s")
print(f"  bags with any request: {n_req_bags}; with a request before the first launch: {n_prerun_opp}")
print("=" * 100); print("[2] Request falling edges while still (substitution ends; selector may re-arm)"); print("=" * 100)
tot_edges = 0
for name, t, vs, et, ec, VS, EC in bags:
    if not len(et): continue
    c = lambda n: vs[:, VS.index(n)]
    idx = np.clip(np.searchsorted(et, t) - 1, 0, len(et) - 1)
    req = ec[idx, EC.index("charge_goal")] > 0.05
    still = np.abs(c("v_actual")) <= 0.02
    fall = np.nonzero(req[:-1] & ~req[1:] & still[1:])[0]
    rise = np.nonzero(~req[:-1] & req[1:] & still[1:])[0]
    if len(fall) or len(rise):
        tot_edges += len(fall)
        print(f"  {name[:42]:42s} falls while still {len(fall):3d}, rises while still {len(rise):3d}")
print(f"  total falling edges at a stop: {tot_edges}")
print("=" * 100); print("[3] EMS 'mode' field and switch_state before the first launch (is the pre-launch interval Idle or Run?)"); print("=" * 100)
for name, t, vs, et, ec, VS, EC in bags:
    if not len(et) or not (ec[:, EC.index("charge_goal")] > 0.05).any(): continue
    c = lambda n: vs[:, VS.index(n)]
    vsp = ec[:, EC.index("v_setpoint")]
    mv = np.nonzero(np.abs(vsp) > 1e-6)[0]; tl = et[mv[0]]
    modes, cnt = np.unique(ec[et < tl, EC.index("mode")], return_counts=True)
    sw = c("switch_state").astype(int); pre = t < tl
    swv, swc = np.unique(sw[pre], return_counts=True)
    print(f"  {name[:42]:42s} mode values before launch {dict(zip(modes.tolist(), cnt.tolist()))}; "
          f"switch_state before launch {dict(zip([hex(x) for x in swv.tolist()], swc.tolist()))}; t_first_vs {t[0]:.2f} s")
