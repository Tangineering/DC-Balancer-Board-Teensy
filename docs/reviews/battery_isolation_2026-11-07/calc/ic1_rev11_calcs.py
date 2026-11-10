"""IC1 detailed design, revision 11 calculations (battle-test round 7 adjudication).

Cited in detailed_design_IC1.md as "calc11 section N". Every input is a value stated in the design (revision 10), in the
round-7 scripts (bt7_*.py, fmea_round7_calcs.py) or in the round-6/9/10 scripts that are imported here. No purge
statistic beyond facts_prior section 7 is used (period 10.34 s, duration 100-140 ms). The purge predictor is the
operator's design (ruling OR-P) and is not modelled.

Sections
  1  D-s on the recorded Pi sessions with the dump-check precondition (FM7-1, BT7-LS-01): the revision-10 literal rule
     (code 12 everywhere), the revision-11 State-2 dump check at the first standstill request, code 4 (PI-4 UNKNOWN)
     against the pre-request H-20 tracking time, and the explicit request flag (BT7-REQ-01, BT7-REQ-02)
  2  FC-only window operating point at the revision-11 fixed window split r = DROOP_R_MAX 0.85 (BT7-TR-01)
  3  Iteration-gap bound behind the PI-4 late-prediction rule (FM7-2)

Run:  .venv_hil/Scripts/python.exe calc/ic1_rev11_calcs.py > calc/ic1_rev11_calcs_output.txt
Section 1 needs numpy (purge_demand_budget.py loads the bags), as bt6_req_ds_request_gate.py does; run it with the
interpreter that ran that script (C:/Users/ricky/miniforge3/python.exe).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def hdr(n, s):
    print("=" * 100)
    print(f"[{n}] {s}")
    print("=" * 100)


# ================================================================================================ 1
hdr(1, "D-s on the recorded Pi sessions with the dump-check precondition (codes 12 and 4) and the request flag")
import numpy as np                       # noqa: E402
import purge_demand_budget as p          # noqa: E402

T_DUMP = (0.020, 0.060)   # s, dump check duration (IC1 9.7b, TODO(calibrate))
T_VCHG = 0.3656           # s, VCHG-IN 15.95 V -> 11 V after the dump-check feed drop (calc10 section 2)
# The window entry chain (p.T_ENTRY + p.T_COLD) is billed by window_account itself; the dump check adds its own
# duration plus the V_chg decay, because the dump check feeds VCHG-IN and the window needs V_chg below 11 V.


def account_first_extra(t, adm, cost, extra):
    dt = np.minimum(np.diff(np.append(t, t[-1] + p.DT)), 0.1)
    chg = 0.0
    first = True
    for a, b in p.runs(adm):
        L = float(dt[a:b].sum())
        c = L - cost - (extra if first else 0.0)
        if first:
            first = False   # the dump check runs in the first admissible run whatever its length
        if c >= p.T_MIN_USEFUL:
            chg += c
    return chg


bags = p.load_bags()
tot = {"rev10_lit": 0.0, "ref": 0.0}
for k in (0, 1):
    for e in T_DUMP:
        tot[(k, e)] = 0.0
print("  per bag (mean over 10 purge phases), D-s mask = live & request(charge_goal>0.05) & still & V_batt<8.0 V")
for name, t, vs, et, ec, VS, EC in bags:
    c = lambda n: vs[:, VS.index(n)]  # noqa: E731
    sw = c("switch_state").astype(int)
    err = c("error_code")
    live = ((sw & 0x04) != 0) & (err == 0)
    if live.sum() < 50 or not len(et):
        continue
    v = c("v_actual")
    itot = c("I_fc") + c("I_batt")
    vb = c("V_batt")
    still = np.abs(v) <= 0.02
    idx = np.clip(np.searchsorted(et, t) - 1, 0, len(et) - 1)
    req = ec[idx, EC.index("charge_goal")] > 0.05
    if not req.any():
        continue
    gate = vb < p.V_BATT_GATE
    sel = gate & req & still
    row = {}
    for k in (0, 1):
        ref, ext = [], {e: [] for e in T_DUMP}
        for ph in np.linspace(0, p.PURGE_T_S, 10, endpoint=False):
            ic = p.i_chg_bus(vb, p.ETA_CHG, p.single_source_vbus(itot + 1.0))
            dem_ok = (itot + ic) <= p.LIM_A
            blk, _ = p.purge_block(t, ph, 0, "D", "none")
            adm = live & dem_ok & ~blk & sel
            cost = p.T_ENTRY[k] + p.T_COLD[k]
            ref.append(account_first_extra(t, adm, cost, 0.0))
            for e in T_DUMP:
                ext[e].append(account_first_extra(t, adm, cost, e + T_VCHG))
        row[k] = (float(np.mean(ref)), {e: float(np.mean(x)) for e, x in ext.items()})
        for e in T_DUMP:
            tot[(k, e)] += row[k][1][e]
        if k == 0:
            tot["ref"] += row[k][0]
    print(f"  {name[:42]:42s} rev-10 figure (no precondition) {row[0][0]:6.1f} s | rev-10 literal (code 12) "
          f"{0.0:5.1f} s | rev-11 State-2 dump check: nominal chain {row[0][1][T_DUMP[0]]:6.1f}-{row[0][1][T_DUMP[1]]:6.1f}"
          f" s, slow chain {row[1][1][T_DUMP[0]]:6.1f}-{row[1][1][T_DUMP[1]]:6.1f} s")
print(f"  TOTAL rev-10 figure (no precondition, nominal chain, reproduces bt6 TOTALS[1]) {tot['ref']:.1f} s")
print("  TOTAL rev-10 literal specification (dump check in State 1/98 only; first request in State 2): 0.0 s")
for k, lab in ((0, "nominal chain"), (1, "slow chain (T_ENTRY/T_COLD worst)")):
    print(f"  TOTAL rev-11 (State-2 dump check at the first standstill request), {lab}: "
          f"{tot[(k, T_DUMP[0])]:.1f} s (dump 20 ms) to {tot[(k, T_DUMP[1])]:.1f} s (dump 60 ms); "
          f"charge at 1.25 A: {tot[(k, T_DUMP[1])] * 1.25 / 3.6:.1f}-{tot[(k, T_DUMP[0])] * 1.25 / 3.6:.1f} mAh")
print("  Code 4 (PI-4 UNKNOWN until the first tracked purge): the H-20 read V_fc > 7 V for 53.6-55.2 s before the first")
print("  launch and the first request came at 67.5-72.4 s (fmea_round7_calcs_output.txt section 1), i.e. at least")
print(f"  {53.6 / p.PURGE_T_S:.1f} purge periods of {p.PURGE_T_S} s before it; an ideal predictor (OR-P) tracks from the first"
      " purge, so code 4 does not bind at the first request on any of the 6 sessions.")
print("  Request origin (bt7_req_origin_output.txt TOTALS): 446.6 s of charge_goal = 419.3 s regen latch + 0.0 s FC-charge")
print("  branch + 27.3 s other; all 112.8 s at standstill are the regen latch. Under the revision-11 explicit request")
print("  flag (reserved command byte = 0xA5) the deployed nodes send 0 or 1 there, so the recorded sessions carry")
print("  0 s of FC-window request and every variant delivers 0 s against EMS requests. The figures above are therefore")
print("  a COUNTERFACTUAL (recorded charge_goal treated as a flagged request) and measure only the precondition cost.")

# ================================================================================================ 2
hdr(2, "FC-only window operating point at the revision-11 fixed window split r = 0.85 (BT7-TR-01)")
K_DROOP = 0.30          # ohm, ino:3098 (bt7_transient_sim.py line 38)
RE_MAX = 2.0136         # ohm, setDroopMdac (bt7_transient_sim.py line 39)
K_SINGLE_BENCH = 0.16   # V/A bench single-source slope at g 0.298 (bt7_transient_sim.py lines 42-43)
G_MID = 0.298
V0_BUS = 15.95          # V (bt7_transient_sim.py line 41)
R_PATH = 0.064          # ohm (bt7 section 1)
V_MPPT_FC, V_SC1A, V_HASPWR = 13.82, 13.0, 13.5
LIMIT_I_FC, INA_ZERO = 1.4, 0.10
P_IN_FC = {7.4: 13.0, 7.8: 13.7, 8.0: 14.05}   # W, IC1 Table 8 FC row (bt7_transient_sim.py line 52)


def op_point(R, p_in, aux):
    vb = V0_BUS
    for _ in range(200):
        vc = vb - R_PATH * (p_in / max(vb, 1.0))
        vb = 0.5 * vb + 0.5 * (V0_BUS - R * (p_in / vc + aux))
    vc = vb - R_PATH * (p_in / vb)
    return vb, vc, p_in / vc + aux


def mppt_frac(R, aux, v_th, p_in):
    i_tot = (V0_BUS - v_th) / (R + R_PATH)
    return min(1.0, v_th * max(0.0, i_tot - aux) / p_in)


for r in (0.85, 0.15):
    g = min(1.0, K_DROOP / (RE_MAX * r))
    code = round(g * 4095)
    for lab, R in (("design chain", RE_MAX * g), ("bench-scaled", K_SINGLE_BENCH * g / G_MID)):
        vcs, fr, fr2, ifs = [], [], [], []
        for vpk, pin in P_IN_FC.items():
            for aux in (0.02, 0.15):
                vb, vc, ifc = op_point(R, pin, aux)
                vcs.append(vc)
                ifs.append(ifc)
                fr.append(mppt_frac(R, aux, V_MPPT_FC, pin))
                fr2.append(mppt_frac(R, aux, V_MPPT_FC + 0.5, pin))
        print(f"  r {r:.2f} g_FC {g:.4f} (code {code:4d}) {lab:13s} R_FC {R:5.3f} ohm: V_chg {min(vcs):.2f}-{max(vcs):.2f} V; "
              f"margin to 13.82 V {min(vcs) - V_MPPT_FC:+.2f} V, to 14.32 V {min(vcs) - V_MPPT_FC - 0.5:+.2f} V, "
              f"to 13.0 V {min(vcs) - V_SC1A:+.2f} V, to 13.5 V {min(vcs) - V_HASPWR:+.2f} V; deliverable "
              f"{100 * min(fr):.0f}-{100 * max(fr):.0f} % (13.82) / {100 * min(fr2):.0f}-{100 * max(fr2):.0f} % (14.32); "
              f"OC_FC margin after INA zero {LIMIT_I_FC - max(ifs) - INA_ZERO:+.3f} A")
print("  Window criterion proposed for W1/W2b: in-window V_chg >= measured S0-4 threshold + 0.3 V and >= 14.0 V.")
print("  At r 0.85 the design chain gives the minimum V_chg above; at r 0.15 (the revision-10 closed-loop clamp) it fails.")

# ================================================================================================ 3
hdr(3, "Iteration-gap bound behind the PI-4 late-prediction rule (FM7-2)")
T_LEAD_MIN, T_LATE, GAP_MEAS = 80.0, 61.0, 9.76   # ms, calc10 section 1; ML0226 worst gap (State 98, USE_ETHERNET 0)
bound = T_LEAD_MIN - T_LATE
print(f"  An ideal announcement at T_lead,min {T_LEAD_MIN:.0f} ms is observed late (below T_late {T_LATE:.0f} ms) only if the")
print(f"  iteration that precedes the observing iteration exceeds {bound:.1f} ms; measured worst gap {GAP_MEAS} ms on a")
print(f"  State-98, USE_ETHERNET 0 build (margin {bound - GAP_MEAS:.2f} ms). Proposed W1/W2b criterion on the production build:")
print(f"  maximum iteration <= 15 ms (4 ms below the {bound:.0f} ms bound, TODO(calibrate)); otherwise T_lead,min is raised by")
print(f"  the excess of the measured maximum over {bound:.0f} ms (a predictor requirement under OR-P).")
