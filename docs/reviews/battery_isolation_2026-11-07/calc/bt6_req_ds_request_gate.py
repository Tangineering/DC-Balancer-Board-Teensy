"""Battle-test round 6 (requirements lens): request-gated D vs D-s on the Pi sessions, and the EMS share command
at standstill with a charge request. Reuses purge_demand_budget.py (same masks, purge schedule, window accounting).
Run: C:/Users/ricky/miniforge3/python.exe bt6_req_ds_request_gate.py > bt6_req_ds_request_gate_output.txt
Section A: per bag, EMS request time, request&standstill time, window charge time for D and D-s with and without the
request mask (nominal case, rule none, 10 purge phases). Section B: power_share_cmd values while a request stands."""
import os
import sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import purge_demand_budget as p
bags = p.load_bags()
tot = {}
for name, t, vs, et, ec, VS, EC in bags:
    c = lambda n: vs[:, VS.index(n)]
    sw = c("switch_state").astype(int); err = c("error_code")
    live = ((sw & 0x04) != 0) & (err == 0)
    if live.sum() < 50: continue
    v = c("v_actual"); itot = c("I_fc")+c("I_batt"); vb = c("V_batt")
    still = np.abs(v) <= 0.02
    if len(et):
        idx = np.clip(np.searchsorted(et, t)-1, 0, len(et)-1); req = ec[idx, EC.index("charge_goal")] > 0.05
    else: req = np.zeros(len(t), bool)
    gate = vb < p.V_BATT_GATE
    dt = np.minimum(np.diff(np.append(t, t[-1]+p.DT)), 0.1)
    k=0; eta=p.ETA_CHG
    out=[]
    for sel in (gate&req, gate&req&still, req, req&still, still):
        vals=[]
        for ph in np.linspace(0, p.PURGE_T_S, 10, endpoint=False):
            ic = p.i_chg_bus(vb, eta, p.single_source_vbus(itot+1.0)); dem_ok=(itot+ic)<=p.LIM_A
            blk,_ = p.purge_block(t, ph, k, "D", "none")
            adm = live & dem_ok & ~blk & sel
            chg, nw, _ = p.window_account(t, adm, p.T_ENTRY[k]+p.T_COLD[k])
            vals.append(chg)
        out.append(np.mean(vals))
    reqstill = float((dt*(live&req&still)).sum()); reqlive=float((dt*(live&req)).sum())
    print(f"{name[:44]:44s} req {reqlive:6.1f}s req&still {reqstill:6.1f}s | D&g&Vb {out[0]:6.1f} Ds&g&Vb {out[1]:6.1f} D&g {out[2]:6.1f} Ds&g {out[3]:6.1f} Ds(still only) {out[4]:6.1f}")
    for i,x in enumerate(out): tot[i]=tot.get(i,0)+x
    tot['r']=tot.get('r',0)+reqlive; tot['rs']=tot.get('rs',0)+reqstill
print("TOTALS (0: D&goal&Vb<8, 1: D-s&goal&Vb<8, 2: D&goal, 3: D-s&goal, 4: D-s ungated; r: request s; rs: request&still s)", {k: round(float(v), 1) for k, v in tot.items()})
print("Section B")
for name, t, vs, et, ec, VS, EC in bags:
    if 'sdp' not in name or not len(et): continue
    c = lambda n: vs[:, VS.index(n)]
    sw=c("switch_state").astype(int); live=((sw&4)!=0)&(c("error_code")==0)
    still=np.abs(c("v_actual"))<=0.02
    idx=np.clip(np.searchsorted(et,t)-1,0,len(et)-1)
    req=ec[idx,EC.index("charge_goal")]>0.05
    sh=ec[idx,[i for i,n in enumerate(EC) if 'share' in n][0]]
    m=live&req&still; m2=live&req&~still
    if m.sum()+m2.sum()==0: continue
    u,cnt=np.unique(np.round(sh[m],3),return_counts=True)
    u2,cnt2=np.unique(np.round(sh[m2],3),return_counts=True)
    print(name, 'still&req share values', dict(zip(u[:8],cnt[:8])), '| moving&req', dict(zip(u2[:8],cnt2[:8])))
