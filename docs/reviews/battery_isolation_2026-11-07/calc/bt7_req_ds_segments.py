"""Battle-test round 7 (requirements lens): structure of the request&standstill time that carries the IC1 rev 10
D-s HR2 figure (107.3 s of 446.6 s, bt6_req_ds_request_gate_output.txt). Per bag: each contiguous segment of
live & charge_goal>0.05 & |v_actual|<=0.02, its start/end relative to the live span, its duration, the commanded
v_setpoint during it, and V_fc / I_fc. Reuses purge_demand_budget.load_bags (same masks as bt6_req_ds_request_gate.py).
Run: .venv / miniforge python bt7_req_ds_segments.py > bt7_req_ds_segments_output.txt"""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import purge_demand_budget as p
for name, t, vs, et, ec, VS, EC in p.load_bags():
    if 'sdp' not in name or not len(et):
        continue
    c = lambda n: vs[:, VS.index(n)]
    sw = c("switch_state").astype(int); live = ((sw & 4) != 0) & (c("error_code") == 0)
    if live.sum() < 50: continue
    idx = np.clip(np.searchsorted(et, t) - 1, 0, len(et) - 1)
    req = ec[idx, EC.index("charge_goal")] > 0.05
    vsp = ec[idx, EC.index("v_setpoint")]
    goal = ec[idx, EC.index("charge_goal")]
    still = np.abs(c("v_actual")) <= 0.02
    m = live & req & still
    lt = t[live]; t0, t1 = lt[0], lt[-1]
    print(f"{name}: live span {t1-t0:7.1f} s; request&still {np.sum(m)*0.02:6.1f} s")
    d = np.diff(np.concatenate(([0], m.astype(int), [0])))
    st, en = np.where(d == 1)[0], np.where(d == -1)[0]
    for a, b in zip(st, en):
        dur = t[b-1] - t[a] + 0.02
        if dur < 0.2: continue
        seg = slice(a, b)
        print(f"   seg {t[a]-t0:7.1f}..{t[b-1]-t0:7.1f} s  dur {dur:6.2f} s | v_sp max {np.max(np.abs(vsp[seg])):.3f}"
              f" | v_sp==0 frac {np.mean(np.abs(vsp[seg])<1e-6):.2f} | goal {np.median(goal[seg]):.2f}"
              f" | V_fc {np.median(c('V_fc')[seg]):5.2f} | I_fc {np.median(c('I_fc')[seg]):.3f} | I_batt {np.median(c('I_batt')[seg]):.3f}"
              f" | V_batt {np.median(c('V_batt')[seg]):.2f} | sw 0x{int(np.median(sw[seg])):02x}")
    nseg = sum(1 for a, b in zip(st, en) if (t[b-1]-t[a]) >= 0.2)
    print(f"   segments >= 0.2 s: {nseg}")

print("\nSection B: in-cycle stops (standstill before the final standstill tail) and the request during them")
for name, t, vs, et, ec, VS, EC in p.load_bags():
    if 'sdp' not in name or not len(et):
        continue
    c = lambda n: vs[:, VS.index(n)]
    sw = c("switch_state").astype(int); live = ((sw & 4) != 0) & (c("error_code") == 0)
    if live.sum() < 50: continue
    idx = np.clip(np.searchsorted(et, t) - 1, 0, len(et) - 1)
    req = ec[idx, EC.index("charge_goal")] > 0.05
    vsp = ec[idx, EC.index("v_setpoint")]
    still = np.abs(c("v_actual")) <= 0.02
    li = np.where(live)[0]
    mov = np.where(live & ~still)[0]
    if not len(mov): continue
    last_move = mov[-1]; first_move = mov[0]
    inc = np.zeros_like(live); inc[first_move:last_move+1] = True
    s_in = live & still & inc
    d = np.diff(np.concatenate(([0], s_in.astype(int), [0]))); st, en = np.where(d == 1)[0], np.where(d == -1)[0]
    stops = [(a, b) for a, b in zip(st, en) if (t[b-1]-t[a]) >= 0.5]
    print(f"{name}: in-cycle span {t[last_move]-t[first_move]:6.1f} s | in-cycle standstill {np.sum(s_in)*0.02:5.1f} s in {len(stops)} stops >= 0.5 s"
          f" (durations {[round(float(t[b-1]-t[a]),1) for a,b in stops]}) | request during in-cycle standstill {np.sum(s_in & req)*0.02:5.1f} s"
          f" | request in motion {np.sum(live & ~still & req)*0.02:5.1f} s | tail after last motion {t[li[-1]]-t[last_move]:5.1f} s")
