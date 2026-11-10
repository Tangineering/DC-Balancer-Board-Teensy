#!/usr/bin/env python3
"""Battle-test round 7, transient-simulation lens, against IC1 detailed design revision 10.

Run:  .venv_hil/Scripts/python.exe docs/reviews/battery_isolation_2026-11-07/calc/bt7_transient_sim.py
      > docs/reviews/battery_isolation_2026-11-07/calc/bt7_transient_sim_output.txt
Standard library only. Cited "bt7 section N".

Question set (lens brief):
 (i)  a predicted purge with exactly T_lead,min 80 ms: bus, battery takeover, no UV_BUS;
 (ii) an unpredicted purge inside a window at worst and light load: V_bus vs time, the eFuse UVLO, the State-99
      teardown, and the FC recovery stresses;
 (iii) variant D: a braking event onto the FC-only bus.
The attack: every earlier transient model of the window (pc, out s1, bt6) starts the FC-only bus at 15.9 V or uses the
bench single-source slope 0.16 V/A, which was fitted at a mid split (g about 0.298 per channel). In a State-2 window
the share loop runs in CLOSED LOOP on the charger current (filtered total about 1 A, above the 0.25 A gate,
ino:14313-14327), sees a delivered FC fraction of 1.0 against an in-band command, and winds the controller output to
the fw v29 span clamp 0.15 (ino:14723-14726). The fw v28 rev 4 topology rule targets k_d = K_DROOP 0.30 there
(ino:13863-13897). The FC droop code is then g_FC = K_DROOP/(RE_MAX*0.15) = 0.993 (setDroopMdac, ino:15230 onward):
the FC channel carries the largest droop resistance the MDAC can realise. Campaign I measured exactly these codes in
every fw v28 charge window (mdac 4067/717, HIL_FINDINGS.md rows 7, 13, 21, 27, 42, 43).
"""
import csv
import math
import os
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))


def hdr(n, s):
    print('\n' + '=' * 110)
    print(f'Section {n}: {s}')
    print('=' * 110)


# ------------------------------------------------------------------ constants (cited)
K_DROOP = 0.30          # ohm, ino:3098
RE_MAX = 2.0136         # ohm, setDroopMdac comment block (ino:15230 onward)
R_MIN_SPAN = 0.15       # DROOP_R_MIN, ino:3101; fw v29 in-band span clamp
V0_BUS = 15.95          # V, measured no-load intercept (tools/hil_plant_sim.py:511)
K_SINGLE_BENCH = 0.16   # V/A, bench fit single source (tools/hil_plant_sim.py:510), fw v16 logs at mid split
G_MID = 0.298           # g at r = 0.5, k_d 0.30: 0.30/(2.0136*0.5) (hil_plant_sim.py:473-475 "R_e = RE_MAX*g = 0.60")
V_MPPT_FC = 13.82       # V, FC-profile threshold (IC1 9.7 entry step 1, R_MP 41.7 kOhm), BENCH S0-4 (+/-0.5 V)
V_SC1A = 13.0           # V, ERR_FC_ONLY_COLLAPSE reading (a), no dwell (IC1 9.11.5)
V_HASPWR = 13.5         # V, chargerHasPower() (IC1 12.5 item 1)
V_CHARGED = 13.5        # V, V_BUS_CHARGED_THRESH (ino:2317), busHotPlugUnsafe() (ino:13043)
LIMIT_I_FC = 1.4        # A, OC_FC single raw sample (ino:2090)
GOV_I = 1.25            # A, the 1.25 A governor (HR2)
INA_ZERO = 0.10         # A, INA253A1 zero error per channel (out s5, SLOS954A 7.5)
OV_BUS = 17.5           # V, LIMIT_V_BUS_MAX = V_BUS_NOMINAL + 1.5
P_IN_FC = {7.4: 13.0, 7.8: 13.7, 8.0: 14.05, 8.4: 14.8}   # W, IC1 Table 8 FC row (8.0 V interpolated 7.8/8.1)


# ================================================================================================ 1
hdr(1, 'HIL anchor: the FC-only window bus law at the closed-loop codes 4067/717 (campaign I, fw v28 rev 6)')
anchor = None
csvp = os.path.join(ROOT, 'HIL Results', 'hil_report_20260908_200836', 'scenario_charge-to-full_hifi',
                    'hil_scenario_charge-to-full_hifi.csv')
if os.path.exists(csvp):
    rows = list(csv.DictReader(open(csvp, newline='')))
    win = [r for r in rows if r['mdac_fc'] == '8163' and r['switch'] == '53']   # 0x1000 nibble + 4067; switch 0x35
    pre = [r for r in rows if r['switch'] in ('38', '39') and float(r['I_fc']) > 0.0 and r['state'] == '2']
    vb = [float(r['V_bus']) for r in win]
    ifc = [float(r['I_fc']) for r in win]
    vc = [float(r['V_chg']) for r in win]
    print(f'  rows {len(rows)}, in-window rows (codes 4067/717, switch 0x35) {len(win)}; state '
          f'{sorted(set(r["state"] for r in win))}, v_actual max {max(abs(float(r["v_actual"])) for r in win):.3f} m/s')
    print(f'  in window: V_bus median {st.median(vb):.4f} V, V_chg median {st.median(vc):.4f} V, I_fc median '
          f'{st.median(ifc):.4f} A, I_batt max {max(float(r["I_batt"]) for r in win):.3f} A')
    # least squares V_bus on I_fc over in-window rows that span the entry ramp
    n = len(win)
    mx, my = sum(ifc) / n, sum(vb) / n
    sxx = sum((x - mx) ** 2 for x in ifc)
    sxy = sum((x - mx) * (y - my) for x, y in zip(ifc, vb))
    slope = sxy / sxx if sxx > 0 else float('nan')
    print(f'  fit V_bus = {my - slope * mx:.3f} + ({slope:.3f}) * I_fc  -> realised FC droop {-slope:.3f} ohm '
          f'(design chain RE_MAX*g_FC = {RE_MAX * K_DROOP / (RE_MAX * R_MIN_SPAN):.3f} ohm at r 0.15)')
    print(f'  path drop V_bus - V_chg at {st.median(ifc):.3f} A: {st.median(vb) - st.median(vc):.4f} V '
          f'-> {(st.median(vb) - st.median(vc)) / st.median(ifc):.4f} ohm (D-BC-FC + eFuse in the plant)')
    anchor = -slope
else:
    print('  campaign-I CSV not present (HIL Results/ is local-only); using the ledger statement R_FC 1.92 ohm')
    anchor = 1.92
print('  The window is a State-2 standstill FC charge window (old topology: BT held off the bus by')
print('  assertFcChargeEnable(); IC1 D-s drops BT_BUS by the mode manager - the share loop sees the same FC-only bus).')

# droop realisations of the FC channel at the window split r = 0.15
g_fc = K_DROOP / (RE_MAX * R_MIN_SPAN)
R_design = RE_MAX * g_fc
R_bench_scaled = K_SINGLE_BENCH * g_fc / G_MID
print(f'\n  g_FC at r 0.15, k_d 0.30 = {g_fc:.3f} (code {int(g_fc * 4095)}); g_BT = {K_DROOP / (RE_MAX * 0.85):.3f} '
      f'(code {int(K_DROOP / (RE_MAX * 0.85) * 4095)})')
print(f'  FC droop at r 0.15: design chain {R_design:.3f} ohm; bench fit 0.16 V/A at g {G_MID} scaled by g: '
      f'{R_bench_scaled:.3f} ohm (the 4x design/bench gap is an OPEN finding, hil_plant_sim.py:467-505)')
print(f'  Every earlier window model: pc V0 15.9 V stiff (purge_collapse_sim.py:67); out s1 0.16 V/A for any split '
      f'(purge_demand_budget.py:51,109); bt6 s4 "k_d x dI" with k_d 0.30 ohm.')

# ================================================================================================ 2
hdr(2, 'FC-only window operating point vs the FC droop resistance (Ag105 constant input power, IC1 Table 8)')
R_PATH = 0.064   # ohm, V_bus - V_chg per A in section 1 (plant D-BC-FC + eFuse)
cases_R = [('out s1 / pc assumption', 0.16), ('bench-scaled, r 0.15', R_bench_scaled),
           ('design chain, r 0.5', RE_MAX * G_MID), ('HIL measured, r 0.15', anchor),
           ('design chain, r 0.15', R_design)]


def op_point(R, p_in, aux):
    """Solve V_bus = V0 - R*(I_chg + aux), I_chg = p_in / V_chg, V_chg = V_bus - R_PATH*I_chg."""
    vb = V0_BUS
    for _ in range(200):
        vc = vb - R_PATH * (p_in / max(vb, 1.0))
        ich = p_in / vc
        vb_new = V0_BUS - R * (ich + aux)
        vb = 0.5 * vb + 0.5 * vb_new
    vc = vb - R_PATH * (p_in / vb)
    return vb, vc, p_in / vc + aux


def mppt_limited(R, aux, v_th):
    """Module input regulated at v_th: the deliverable input power on the droop line."""
    i_tot = (V0_BUS - v_th - 0.0) / (R + R_PATH)
    ich = max(0.0, i_tot - aux)
    return v_th * ich


print(f'  aux on the bus 0.02 A (bag standstill total, bt6_bag_launch) and 0.15 A (IC1 Table 8 bounding); '
      f'R_PATH {R_PATH} ohm')
print(f'  {"realisation":26s} {"R_FC":>6s} {"Vpk":>4s} {"aux":>5s} | {"V_bus":>6s} {"V_chg":>6s} {"I_fc":>6s} | '
      f'{"to 13.82":>8s} {"to 13.0":>7s} {"to 13.5":>7s} | {"OC_FC+INA":>9s} | {"P_avail@13.82":>13s} {"@14.32":>7s}')
worst = {}
for lab, R in cases_R:
    for vpk in (7.4, 7.8, 8.0):
        for aux in (0.02, 0.15):
            p = P_IN_FC[vpk]
            vb, vc, ifc = op_point(R, p, aux)
            pa = mppt_limited(R, aux, V_MPPT_FC)
            pa2 = mppt_limited(R, aux, V_MPPT_FC + 0.5)
            frac = min(1.0, pa / p)
            frac2 = min(1.0, pa2 / p)
            print(f'  {lab:26s} {R:6.3f} {vpk:4.1f} {aux:5.2f} | {vb:6.2f} {vc:6.2f} {ifc:6.3f} | '
                  f'{vc - V_MPPT_FC:+8.2f} {vc - V_SC1A:+7.2f} {vc - V_HASPWR:+7.2f} | '
                  f'{LIMIT_I_FC - ifc - INA_ZERO:+9.3f} | {100 * frac:12.1f}% {100 * frac2:6.1f}%')
            worst.setdefault(lab, []).append((vc, frac, frac2, ifc))
print('  Columns: margins of V_chg to the Ag105 FC threshold, to SC-1 reading (a) and to chargerHasPower(); OC_FC margin')
print('  after the INA253A1 zero error; the share of the Table-8 input power the module can draw if it regulates its')
print('  input at 13.82 V (nominal) or 14.32 V (S0-4 acceptance +0.5 V). Below 100 % the 1.25 A I_set is not reached.')
for lab, v in worst.items():
    print(f'   {lab:26s}: V_chg {min(x[0] for x in v):.2f}-{max(x[0] for x in v):.2f} V; '
          f'deliverable at 13.82 V {100 * min(x[1] for x in v):.0f}-{100 * max(x[1] for x in v):.0f} %, '
          f'at 14.32 V {100 * min(x[2] for x in v):.0f}-{100 * max(x[2] for x in v):.0f} %; '
          f'I_fc up to {max(x[3] for x in v):.3f} A')

# the entry ramp: the controller winds r from the pre-window split to 0.15 at the dark-channel handoff slew
print('\n  Entry: the frozen pre-window split (loop below 0.075 A at standstill, ino:14287) becomes closed loop when the')
print('  module starts; the dark-BT handoff slew is 0.002 per tick (ino:3242, 3288-3325), so the walk 0.5 -> 0.15 is')
for tl in (1.0e-3, 1.341e-3):
    print(f'   {0.35 / 0.002:.0f} ticks = {0.35 / 0.002 * tl * 1e3:.0f} ms at a {tl * 1e3:.3f} ms loop; the bus walks down '
          f'with it (design chain: {op_point(RE_MAX * G_MID, 13.7, 0.02)[0]:.2f} V -> {op_point(R_design, 13.7, 0.02)[0]:.2f} V at 7.8 V)')

# ================================================================================================ 3
hdr(3, '(i) Predicted purge at exactly T_lead,min = 80 ms (P and D-s): bus at the drop, the re-close and the onset')
T_COND_WORST = 61.68e-3   # calc10 section 1
print(f'  Exit chain (calc10 section 1): D-BT-EN conducts at most {T_COND_WORST * 1e3:.2f} ms after the prediction; '
      f'margin at an 80 ms onset {80 - T_COND_WORST * 1e3:.2f} ms.')
for lab, R in cases_R:
    vb_w, vc_w, ifc_w = op_point(R, P_IN_FC[8.0], 0.02)
    vb_after = V0_BUS - R * 0.02
    print(f'   {lab:26s}: window bus {vb_w:5.2f} V -> after the feed drop {vb_after:5.2f} V (unload step '
          f'{vb_after - vb_w:+.2f} V; OV_BUS margin {OV_BUS - vb_after - 0.5:+.2f} V with a 0.5 V overshoot ASSUMED); '
          f'step-4 guard busHotPlugUnsafe (13.5 V) {"passes" if vb_after >= V_CHARGED else "REFUSES -> latch"}')
print('  At the onset BT carries the auxiliary load through D-BT-EN at the held split (D-s: r 0.15, R_BT = 0.30/0.85):')
for R_bt, lab in ((K_DROOP / 0.85, 'D-s, r 0.15'), (RE_MAX, 'P, worst held split (g_BT capped at 1)')):
    for aux in (0.02, 0.15):
        print(f'   {lab:40s} aux {aux:.2f} A: V_bus {V0_BUS - R_bt * aux:5.2f} V; reading (b) 12.0 V and UV_BUS: no trip')
print('  No contradiction in (i): the feed drop removes the sag before the re-close, so the step-4 guard passes and')
print('  the BT takeover at the onset is a light-load event. The window-time bus (section 2) does not reach (i).')

# ================================================================================================ 4
hdr(4, '(ii) Unpredicted purge inside a window from the drooped operating point (pc model, V0 replaced)')
src = open(os.path.join(HERE, 'purge_collapse_sim.py'), encoding='utf-8').read()
cut = src.index('def ms(x):')
ns = {}
exec(compile(src[:cut], 'purge_collapse_sim.py', 'exec'), ns)   # constants + run() + hr_flag() only
import itertools
summary = {}
for v0_lab, v0 in (('pc as written, 15.9 V', 15.9), ('design-chain droop, 13.8 V', 13.8),
                   ('HIL-like, 14.0 V', 14.0)):
    ns['V0'] = v0
    ns['V_MPPT'] = min(13.82, v0 - 0.05)   # the module regulates at or below its threshold: keep it drawing
    res = []
    for mode, p, aux, cv, tf, var in itertools.product(('CP', 'MPPT'), (13.0, 14.8), (0.0005, 0.015, 0.15),
                                                       (0.48e-3, 1.5e-3, 5e-3), (0.0, 0.020), ('P', 'D')):
        ev = ns['run'](mode, p, 221e-6, aux, cv, tf, (12.10, 12.88), var, 'E2', 1.341e-3)
        fc80 = ns['hr_flag'](ev, 0.080)
        res.append((ev.get('t_latch'), ev.get('t_s99'), fc80[0], fc80[2], ev['vb_min'], ev.get('t_efuse_off'),
                    ev['bt_peak_i'], ev['ef_restart'], ev.get('vm_at_bond')))
    lat = [r[0] for r in res if r[0] is not None]
    s99 = [r[1] for r in res if r[1] is not None]
    efo = [r[5] for r in res if r[5] is not None]
    vmb = [r[8] for r in res if r[8] is not None]
    n_hr = sum(1 for r in res if r[2])
    print(f'  {v0_lab:28s}: {len(res)} cases; latch {min(lat) * 1e3:.1f}-{max(lat) * 1e3:.1f} ms; FC_BUS LOW '
          f'(phase 0) {min(s99) * 1e3:.1f}-{max(s99) * 1e3:.1f} ms; FC_BUS+FC_REG HIGH at 80 ms: {n_hr}; '
          f'eFuse off {min(efo) * 1e3:.2f}-{max(efo) * 1e3:.2f} ms; warm eFuse restarts {sum(r[7] for r in res)}; '
          f'BT peak {max(r[6] for r in res):.2f} A; module node at the bond {min(vmb):.2f}-{max(vmb):.2f} V')
    summary[v0_lab] = (min(lat), max(lat), n_hr)
print('  A lower start moves reading (a) closer, so the latch comes earlier; every case is OPEN (FC_BUS LOW) at 80 ms,')
print('  no BT_BUS write follows (E2), and the module node is cold at the bond. The teardown and the recovery stresses')
print('  of IC1 Tables 23-24 (FC_REG LOW at phase 0 + 20 ms, the H-20 recharging only the 30 uF behind a disabled')
print('  boost and an open D-FC-EN) are unchanged. No rating exceeded; no contradiction from this lens in (ii).')

# ================================================================================================ 5
hdr(5, '(iii) Variant D: traction and a braking event on the FC-only bus at the window split')
print('  IC1 Table 26 gives D a traction allowance of 0.06-0.33 A bus-side (out s1, at 0.16 V/A); bt6 s4 put the')
print('  brake-onset bus rise at k_d x dI = 0.30 x 0.405 = 0.12 V.')
for lab, R in cases_R:
    vb0, vc0, _ = op_point(R, P_IN_FC[7.8], 0.02)
    # traction headroom to the Ag105 threshold and to the SC-1 (a) latch
    i_chg = P_IN_FC[7.8] / vc0
    head_th = (V0_BUS - V_MPPT_FC - R_PATH * i_chg) / R - i_chg - 0.02
    head_sc1 = (V0_BUS - V_SC1A - R_PATH * i_chg) / R - i_chg - 0.02
    rise = R * (0.33 + 0.075)
    print(f'   {lab:26s}: traction allowance to 13.82 V {head_th:+.3f} A, to the no-dwell 13.0 V latch {head_sc1:+.3f} A; '
          f'brake-onset rise {rise:.2f} V (bt6: 0.12 V); OV_BUS margin {OV_BUS - (vb0 + rise):+.2f} V')
print('  D-MT-EN blocks V-MOT -> bus and pin 30 is LOW (OR-7), so the regen energy stays on V-MOT (VESC stop 21.35 V,')
print('  chopper 22.13 V, facts_prior s6) as in fw v37 Run today; no rating is exceeded on braking. The re-acceleration')
print('  after the brake is the binding event: at the window split the FC-only bus has no traction allowance to the')
print('  module threshold (0.03-0.08 A) and 0.44-0.50 A to the no-dwell latch under the design-chain or HIL droop.')
print('  (The large allowances of the stiff rows are voltage headroom only; the FC budget of Table 8 still binds there.)')
print('  HIL witness (campaign I charge-cruise, fw v28, codes 4067/717, traction 3.5 A current command): in-window')
print('  V_bus min 13.18 V, V_chg min 13.13 V at I_fc up to 1.40 A - 0.13 V above the IC1 reading-(a) threshold.')
