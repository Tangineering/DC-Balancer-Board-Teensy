#!/usr/bin/env python3
"""Safe-collapse analysis: an UNPREDICTED H-20 purge inside an IC1 FC window (revision 8).

Study: docs/reviews/battery_isolation_2026-11-07/facts_purge_collapse.md (this script is cited "pc section N").
Standard library only. Run:  .venv_hil/Scripts/python.exe calc/purge_collapse_sim.py > calc/purge_collapse_sim_output.txt

Scope (operator ruling 2026-11-08 (2)): an unpredicted purge may collapse the bus and latch State 99. The question is
only whether any component is damaged and in which order the pins must end. The predictor is not modelled.

Model (ideal-diode node network, charge-conserving projection, explicit Euler, DT = 20 us):
  F  FC boost output        C_F  = 30 uF  (OFC, docs/HIL_PLANT.md 8.2, derated bulk)                 -> D-FC-EN (pin 27)
  B  VBUS                   C_B  = 35 uF  (30-40 uF band midpoint, HIL_PLANT.md 8.2; tools/hil_electrical.py:456)
  C  VCHG-IN                C_C  = 21 uF  (C-D8 + C-D10 20 uF, calc5 s5; + C_EI 1 uF, IC1 5.3)           <- D-BC-FC (pin 31)
  M  module node VCHG-IN_M  C_M  = C_mod + C_EO, C_mod 100-221 uF (IC1 5.3, gate S0-11), C_EO 1 uF   <- eFuse U_EF
  V  V-MOT                  C_V  = 0.48 / 1.5 / 5 mF (facts_prior s6: 0.48 mF board .. ~5 mF; capture 11
                                    effective 1.4-1.6 mF, boost-bringup-debug.md "Capture 11")       <- D-MT-EN (pin 29)
Links:
  RT1987 (D-FC-EN, D-BC-FC, D-MT-EN, D-BT-EN): ideal diode when enabled (V_FWD 35 mV neglected, RT1987 DS-00
    s17.6); disabled when EN LOW or VIN < 2.925 V (UVLO falling typ, DS-00 s17.1); a UVLO-disabled switch stays off
    in this window (re-enable needs t_D_ON 8 ms + soft-start, DS-00 s17.1) and is flagged.
  eFuse TPS26631: ON (bidirectional channel) while EF_EN H and V_C above its UVLO; UVLO off 11.47-12.10 V, on
    12.38-12.88 V (IC1 5.3, calc4 s9). OFF: reverse body diode M -> C (B_GATE/DRV open, SLVSE94G Table 5-1, IC1 5.3),
    drop 0.6 V ASSUMED.
Loads:
  Ag105 FC profile input P_in 13.0-14.8 W (IC1 Table 8). Mode CP: constant power until V_M < 11.0 V (V_LOCK typ,
    Ag105 DS p.19; no min/max), then idle I_IDLE 18 mA max (DS p.20 row 4). Mode MPPT: the module throttles so that
    V_M stays >= 13.82 V (FC-profile MPPTS threshold, BENCH S0-4) - the IDEAL fast MPPT bound (the real loop speed
    is not published; facts_ag105 s7) - and draws I_IDLE below it. R_MB 3.3 k, R_MS1+R_MS2 116.2 k on M; R_MD 15 Ohm
    when EF_EN L (dump, IC1 5.3). VCHG-IN bleed R1-CHG 88.7 k || R_UV 110.5 k = 49.2 k (calc5 s5).
  Bus-side aux on B: 0.5 mA (bleed-level: R_NODE_BLEED_BUS 30 k at 16 V, HIL_PLANT.md 4.2), 15 mA (HIL I_AUX 0.09 A
    minus the 0.075 A VESC term, HIL_PLANT.md 4.3), 150 mA (IC1 Table 8 bounding aux, all of it on VBUS).
  V-MOT: VESC 0.075 A (HIL_PLANT.md 4.3, TODO(calibrate)); variant D adds 0.28 A traction (top of the 0.17-0.28 A
    FC-window headroom, IC1 Table 8); VESC load drops below 8.0 V (VESC l_min_vin ASSUMED 8 V, TODO(verify: VESC)).
Source: FC boost output current I_fc(t) = I0 * max(0, 1 - t/T_fall), T_fall 0 (step) or 20 ms (one 50 Hz bag
  sample; the fall time is not measured, facts_prior s7). I0 = the pre-purge steady load. The boost is in VIN UVLO
  for the whole purge (floor ~1 V < 1.8-2.0 V falling UVLO, TPS61288 SLVSFP3C 7.5).
Firmware (fw v37 rev 2 + IC1 rev 8): one iteration every T_loop (1.341 ms p99; one 9.76 ms gap in the sensitivity
  run; facts_firmware s8). UV_BUS: V_bus < 12.0 V adds min(dt, 5 ms), else leaks 0.05 dt; latch at 20 ms
  (ino:2163, 2189-2193, 7369-7377). State 99 phase 0 runs on the iteration after the latch (FC_CHARGE LOW, both bus
  switches LOW; IC1 9.9 steps 1-3), MOT_PWR LOW at +10 ms, boosts LOW at +20 ms (ino:8320-8337); pin 33 LOW after
  pin 8 reads LOW twice or at the T_drain,max deadline (IC1 9.9 step 2).
  Policy E1 = IC1 rev 8 as written: a V_chg reading < 13.0 V with EF_EN H ends the window as a COMMANDED exit
  (IC1 9.7 exit conditions): FC_CHARGE LOW, drain (pin 8 LOW twice; deadline max(10 ms, 4 it) cap 30 ms), pin 33
  LOW, settled bonded read (2 iterations), BT_BUS re-close: D-BT-EN conducts once its soft-start ramp, started
  t_D_ON 8 ms after EN (DS-00 s17.1), exceeds V_bus; ramp 16 V / 19.8 ms = 0.81 V/ms (CSS 100 nF, calc
  purge_demand_budget.py T_SS_BUS) and 0.5 V/ms (capture 11 measured V-MOT ramp).
  Policy E2 = proposed: the same V_chg < 13.0 V reading (or V_bus < 13.0 V) inside a window latches State 99 at
  once (no BT_BUS re-close).
Hazard H-R (the recovery race): at the FC recovery instant t_rec the FC boost leaves VIN UVLO (rising 2.3-2.4 V,
SLVSFP3C 7.5) while FC_BUS (pin 27) and FC_REG (pin 3) are still HIGH, so the boost restarts into the bus and, through
an enabled D-MT-EN, into V-MOT. t_rec = 80 ms (100 ms minimum duration minus the 20 ms bag edge uncertainty) and
100 ms (facts_prior s7).
"""
import itertools
import math

DT = 20e-6
T_END = 0.160

C_F, C_B, C_C = 30e-6, 35e-6, 21e-6
C_EO = 1e-6
R_C_BLEED = (78.7e3 + 10e3) * (100e3 + 10.5e3) / (78.7e3 + 10e3 + 100e3 + 10.5e3)
R_MB, R_MS, R_MD = 3300.0, 116.2e3, 15.0
V_LOCK, I_IDLE, V_MPPT = 11.0, 0.018, 13.82
RT_UVLO = 2.925
I_VESC, V_VESC_MIN = 0.075, 8.0
V0 = 15.9          # loaded bus before the purge (V_BUS_NOMINAL 16.0, no-load 15.91 V; ino:2102)
V_UV, UV_LATCH, UV_LEAK, UV_CAP = 12.0, 20.0, 0.05, 5.0
V_EXIT = 13.0
PIN8_TH = 8.92     # mid of 8.69-9.15 V (IC1 5.3); corners change drain time by < 0.1 ms
T_DON = 0.008
VBT = 16.0
V_BODY = 0.6       # eFuse reverse body diode drop, ASSUMED


def run(mode, p_in, c_mod, aux, c_v, t_fall, ef_corner, variant, policy, t_loop, slope=0.81e3,
        gap_at=None, gap=0.00976, trace=False):
    C_M = c_mod + C_EO
    cap = {'F': C_F, 'B': C_B, 'C': C_C, 'M': C_M, 'V': c_v}
    v = {k: V0 for k in cap}
    ef_off_v, ef_on_v = ef_corner
    i_trac = 0.28 if variant == 'D' else 0.0
    # pre-purge steady FC output current (bus side)
    i0 = p_in / V0 + aux + I_VESC + i_trac + V0 / R_C_BLEED + V0 / R_MB + V0 / R_MS
    en = {'FCBUS': True, 'FCCHG': True, 'MOT': True, 'BTBUS': False, 'FCREG': True, 'BTREG': True}
    uvlo_latched = {'FCBUS': False, 'FCCHG': False, 'MOT': False}
    ef_en, ef_on, locked = True, True, False
    p33 = True  # charge mode
    ev = {}
    dwell = 0.0
    last_it = 0.0
    next_it = t_loop
    exit_state = None   # None, 'drain', 'confirm', 'btwait'
    pin8_low_n = 0
    drain_t0 = None
    confirm_n = 0
    bt_en_t = None
    s99 = None          # time of phase 0
    latch_t = None
    ef_restart = 0
    vb_min = V0
    bt_peak_i = 0.0
    ef_ever_off = False
    n = int(T_END / DT)
    snap = {}
    it_count = 0
    for k in range(n):
        t = k * DT
        # ---------------- source and loads (currents into each node) ----------------
        i_fc = i0 * max(0.0, 1.0 - t / t_fall) if t_fall > 0 else 0.0
        di = {'F': i_fc, 'B': -aux if v['B'] > 0.5 else 0.0, 'C': -v['C'] / R_C_BLEED, 'M': 0.0, 'V': 0.0}
        # module
        im = v['M'] / R_MB + v['M'] / R_MS
        if ef_en is False:
            im += v['M'] / R_MD
        if not locked:
            if v['M'] < V_LOCK:
                locked = True
                ev.setdefault('t_lockout', t)
        if not locked:
            if mode == 'CP':
                im += p_in / v['M']
            else:  # MPPT ideal: draw only while above the threshold
                im += (p_in / v['M']) if v['M'] > V_MPPT else I_IDLE
        else:
            im += I_IDLE if v['M'] > 1.0 else 0.0
        di['M'] -= im
        if v['V'] > V_VESC_MIN:
            di['V'] -= I_VESC + i_trac
        for kk in cap:
            v[kk] += di[kk] * DT / cap[kk]
            if v[kk] < 0.0:
                v[kk] = 0.0
        # ---------------- RT1987 UVLO (VIN) ----------------
        for sw, vin in (('FCBUS', 'F'), ('FCCHG', 'B'), ('MOT', 'B')):
            if en[sw] and not uvlo_latched[sw] and v[vin] < RT_UVLO:
                uvlo_latched[sw] = True
                ev.setdefault('t_uvlo_' + sw, t)
        # ---------------- eFuse state ----------------
        if ef_on and (not ef_en or v['C'] < ef_off_v):
            ef_on = False
            ef_ever_off = True
            ev.setdefault('t_efuse_off', t)
        elif (not ef_on) and ef_en and v['C'] >= ef_on_v:
            ef_on = True
            ef_restart += 1
        # ---------------- projection: merge forward-biased ideal diodes ----------------
        links = []
        if en['FCBUS'] and not uvlo_latched['FCBUS']:
            links.append(('F', 'B'))
        if en['FCCHG'] and not uvlo_latched['FCCHG']:
            links.append(('B', 'C'))
        if en['MOT'] and not uvlo_latched['MOT']:
            links.append(('B', 'V'))
        for _ in range(6):
            parent = {kk: kk for kk in cap}

            def find(x):
                while parent[x] != x:
                    x = parent[x]
                return x
            changed = False
            for (u, d) in links:
                if v[u] > v[d] + 1e-9:
                    ru, rd = find(u), find(d)
                    if ru != rd:
                        parent[rd] = ru
                        changed = True
            if ef_on:
                ru, rd = find('C'), find('M')
                if ru != rd and abs(v['C'] - v['M']) > 1e-9:
                    parent[rd] = ru
                    changed = True
            groups = {}
            for kk in cap:
                groups.setdefault(find(kk), []).append(kk)
            for g in groups.values():
                if len(g) > 1:
                    q = sum(cap[x] * v[x] for x in g)
                    cs = sum(cap[x] for x in g)
                    for x in g:
                        v[x] = q / cs
            # body diode M -> C when the eFuse is off
            if not ef_on:
                gm, gc = find('M'), find('C')
                if gm != gc and v['M'] > v['C'] + V_BODY:
                    cm = sum(cap[x] for x in groups[gm])
                    cc = sum(cap[x] for x in groups[gc])
                    qx = (v['M'] - v['C'] - V_BODY) / (1 / cm + 1 / cc)
                    for x in groups[gm]:
                        v[x] -= qx / cm
                    for x in groups[gc]:
                        v[x] += qx / cc
                    changed = True
            # D-BT-EN soft-start ramp (voltage source behind TRCB)
            if en['BTBUS'] and bt_en_t is not None and t >= bt_en_t + T_DON:
                vr = min(VBT, slope * (t - bt_en_t - T_DON))
                gb = find('B')
                if v['B'] < vr - 1e-9:
                    cs = sum(cap[x] for x in groups[gb])
                    dq = cs * (vr - v['B'])
                    bt_peak_i = max(bt_peak_i, dq / DT)
                    ev.setdefault('t_bt_conduct', t)
                    for x in groups[gb]:
                        v[x] = vr
                    changed = True
            if not changed:
                break
        vb_min = min(vb_min, v['B'])
        for tr in (0.080, 0.100, 0.140):
            if tr not in snap and t >= tr:
                snap[tr] = dict(v=dict(v), en=dict(en), uv=dict(uvlo_latched), s99=s99)
        # ---------------- firmware iteration ----------------
        if t >= next_it:
            it_count += 1
            dt_ms = (t - last_it) * 1e3
            last_it = t
            step = gap if (gap_at is not None and abs(t - gap_at) < t_loop / 2) else t_loop
            next_it = t + step
            vbus, vchg, pin8_high = v['B'], v['C'], v['M'] >= PIN8_TH
            # State 99 sequencing
            if s99 is not None:
                if p33:
                    pin8_low_n = pin8_low_n + 1 if not pin8_high else 0
                    if pin8_low_n >= 2 or t - s99 >= max(0.010, 4 * t_loop):
                        p33 = False
                        ev['t_bond'] = t
                        ev['vm_at_bond'] = v['M']
                if t - s99 >= 0.010 and en['MOT']:
                    en['MOT'] = False
                    ev['t_mot_low'] = t
                if t - s99 >= 0.020 and en['FCREG']:
                    en['FCREG'] = en['BTREG'] = False
                    ev['t_boost_low'] = t
                continue
            if latch_t is not None:       # phase 0 on the iteration after the latch
                s99 = t
                ev['t_s99'] = t
                en['FCBUS'] = en['BTBUS'] = en['FCCHG'] = False
                ef_en = False
                ev.setdefault('t_dump_on', t)
                pin8_low_n = 0
                continue
            # UV_BUS dwell (armed: FC pair matched, ino:7338-7360)
            fc_feeding = en['FCBUS'] and en['FCREG']
            bt_feeding = en['BTBUS'] and en['BTREG']
            if fc_feeding or bt_feeding:
                d = min(dt_ms, UV_CAP)
                if vbus < V_UV:
                    dwell += d
                    ev.setdefault('t_vbus_lt12_seen', t)
                    if dwell >= UV_LATCH:
                        latch_t = t
                        ev['t_latch'] = t
                        ev['latch_by'] = 'UV_BUS'
                else:
                    dwell = max(0.0, dwell - UV_LEAK * d)
            # window exit / policy
            if exit_state is None and ef_en and vchg < V_EXIT:
                ev['t_exit_trigger'] = t
                if policy == 'E2':
                    latch_t = t
                    ev['t_latch'] = t
                    ev['latch_by'] = 'E2 window collapse'
                    continue
                exit_state = 'drain'
                en['FCCHG'] = False
                ef_en = False
                ev['t_dump_on'] = t
                drain_t0 = t
                pin8_low_n = 0
                continue
            if exit_state == 'drain':
                pin8_low_n = pin8_low_n + 1 if not pin8_high else 0
                if pin8_low_n >= 2 or t - drain_t0 >= min(0.030, max(0.010, 4 * t_loop)):
                    p33 = False
                    ev['t_bond'] = t
                    ev['vm_at_bond'] = v['M']
                    exit_state = 'confirm'
                    confirm_n = 0
            elif exit_state == 'confirm':
                confirm_n += 1
                if confirm_n >= 2:
                    en['BTBUS'] = True
                    bt_en_t = t
                    ev['t_bt_en'] = t
                    exit_state = 'btwait'
    ev['vb_min'] = vb_min
    ev['ef_restart'] = ef_restart
    ev['bt_peak_i'] = bt_peak_i
    ev['snap'] = snap
    ev['uvlo'] = dict(uvlo_latched)
    return ev


def hr_flag(ev, tr):
    """H-R at t_rec: FC_BUS EN and FC_REG still HIGH (and not UVLO-latched) -> boost restarts onto the bus."""
    s = ev['snap'][tr]
    fc_closed = s['en']['FCBUS'] and s['en']['FCREG'] and not s['uv']['FCBUS']
    mot_joined = s['en']['MOT'] and not s['uv']['MOT']
    return fc_closed, mot_joined, s['v']['B'], s['v']['V']


def ms(x):
    return '   -  ' if x is None else f'{x * 1e3:6.1f}'


def hdr(n, s):
    print('\n' + '=' * 110)
    print(f'Section {n}: {s}')
    print('=' * 110)


# =========================================================================================================== 1
hdr(1, 'Collapse rates before any firmware action (bus-side, analytic)')
for lab, i, c in (('charger 13.0 W at 15.9 V + aux 0.15 A on B+C+M (C_mod 100 uF)', 13.0 / 15.9 + 0.15, C_B + C_C + 101e-6),
                  ('charger 14.8 W at 15.9 V + aux 0.15 A on B+C+M (C_mod 221 uF)', 14.8 / 15.9 + 0.15, C_B + C_C + 222e-6),
                  ('charger 14.8 W + F (30 uF) joined, C_mod 100 uF', 14.8 / 15.9, C_F + C_B + C_C + 101e-6),
                  ('aux 0.09 A alone on VBUS 35 uF (campaign G check)', 0.09, C_B),
                  ('aux 0.015 A on B+F (65 uF), eFuse off', 0.015, C_B + C_F),
                  ('aux 0.0005 A on B+F (65 uF), eFuse off', 0.0005, C_B + C_F)):
    print(f'  {lab:66s}: {i / c / 1e3:7.3f} V/ms')
for cv in (0.48e-3, 1.5e-3, 5e-3):
    for it, lab in ((I_VESC, 'VESC 0.075 A'), (I_VESC + 0.28, 'VESC + traction 0.28 A (variant D)')):
        r = it / cv
        t8 = (V0 - V_VESC_MIN) / r
        print(f'  V-MOT {cv * 1e3:4.2f} mF, {lab:38s}: {r / 1e3:6.3f} V/ms; V-MOT at 100 / 140 ms '
              f'{max(0, V0 - r * 0.1):5.2f} / {max(0, V0 - r * 0.14):5.2f} V; reaches 8 V at {t8 * 1e3:6.1f} ms')

# =========================================================================================================== 2
hdr(2, 'Reference traces (p99 loop 1.341 ms, C_mod 221 uF, eFuse UVLO high corner, V-MOT 1.5 mF)')
for mode, p, aux, var, pol in (('CP', 14.8, 0.015, 'P', 'E1'), ('CP', 13.0, 0.0005, 'P', 'E1'),
                               ('MPPT', 14.8, 0.0005, 'P', 'E1'), ('MPPT', 14.8, 0.0005, 'P', 'E2'),
                               ('MPPT', 14.8, 0.0005, 'D', 'E1'), ('CP', 14.8, 0.15, 'D', 'E1')):
    for tf in (0.0, 0.020):
        e = run(mode, p, 221e-6, aux, 1.5e-3, tf, (12.10, 12.88), var, pol, 1.341e-3)
        print(f'{mode:4s} P_in {p:4.1f} W aux {aux * 1e3:5.1f} mA var {var} {pol} T_fall {tf * 1e3:2.0f} ms: '
              f'eFuse off {ms(e.get("t_efuse_off"))}  lockout {ms(e.get("t_lockout"))}  exit {ms(e.get("t_exit_trigger"))}'
              f'  bond {ms(e.get("t_bond"))} (V_M {e.get("vm_at_bond", float("nan")):5.2f} V)  BT_EN {ms(e.get("t_bt_en"))}'
              f'  BT cond {ms(e.get("t_bt_conduct"))}  latch {ms(e.get("t_latch"))} [{e.get("latch_by", "none")}]'
              f'  MOT low {ms(e.get("t_mot_low"))}  boosts low {ms(e.get("t_boost_low"))}  Vbus min {e["vb_min"]:5.2f}'
              f'  BT peak {e["bt_peak_i"]:5.2f} A  warm eFuse restarts {e["ef_restart"]}  UVLO {[k for k, x in e["uvlo"].items() if x]}')

# =========================================================================================================== 3
hdr(3, 'Grid: latch timing and the recovery race H-R (FC_BUS + FC_REG still HIGH at t_rec)')
modes = (('CP', 13.0), ('CP', 14.8), ('MPPT', 14.8))
grid = list(itertools.product(modes, (100e-6, 221e-6), (0.0005, 0.015, 0.15), (0.48e-3, 1.5e-3, 5e-3),
                              (0.0, 0.020), ((11.47, 12.38), (12.10, 12.88)), ('P', 'D'), ('E1', 'E2')))
rows = []
for (mode, p), cm, aux, cv, tf, efc, var, pol in grid:
    e = run(mode, p, cm, aux, cv, tf, efc, var, pol, 1.341e-3)
    fc80 = hr_flag(e, 0.080)
    fc100 = hr_flag(e, 0.100)
    rows.append(((mode, p, cm, aux, cv, tf, efc, var, pol), e, fc80, fc100))
print(f'{len(rows)} cases (3 load modes x 2 C_mod x 3 aux x 3 C_V x 2 T_fall x 2 eFuse corners x 2 variants x 2 '
      f'policies), p99 loop')
for pol in ('E1', 'E2'):
    for var in ('P', 'D'):
        sub = [r for r in rows if r[0][8] == pol and r[0][7] == var]
        lat = [r[1].get('t_latch') for r in sub]
        nolatch = sum(1 for x in lat if x is None)
        lat_v = [x for x in lat if x is not None]
        mot = [r[1].get('t_mot_low') for r in sub if r[1].get('t_mot_low') is not None]
        hr80 = [r for r in sub if r[2][0]]
        hr80j = [r for r in hr80 if r[2][1]]
        hr100 = [r for r in sub if r[3][0]]
        bt_c = [r for r in sub if r[1].get('t_bt_conduct') is not None]
        warm = [r for r in sub if r[1]['ef_restart'] > 0]
        bonds = [r[1]['vm_at_bond'] for r in sub if 'vm_at_bond' in r[1]]
        print(f'\n[{pol} variant {var}] {len(sub)} cases: latch at {min(lat_v) * 1e3:.1f}-{max(lat_v) * 1e3:.1f} ms '
              f'(no latch by 160 ms: {nolatch}); MOT_PWR LOW at {min(mot) * 1e3:.1f}-{max(mot) * 1e3:.1f} ms; '
              f'FC_BUS still HIGH at t_rec 80 ms: {len(hr80)} (with D-MT-EN joined: {len(hr80j)}); at 100 ms: '
              f'{len(hr100)}; BT_BUS conducted before the latch: {len(bt_c)}; warm eFuse restarts: {len(warm)}; '
              f'V_M at bond {min(bonds):.2f}-{max(bonds):.2f} V')
        if hr80:
            worst = max(hr80, key=lambda r: (r[1].get('t_latch') or 1.0))
            (mode, p, cm, aux, cv, tf, efc, var_, pol_) = worst[0]
            print(f'   H-R cases at 80 ms: modes {sorted(set(r[0][0] for r in hr80))}, aux '
                  f'{sorted(set(r[0][3] * 1e3 for r in hr80))} mA, C_V {sorted(set(r[0][4] * 1e3 for r in hr80))} mF;'
                  f' bus at t_rec {min(r[2][2] for r in hr80):.2f}-{max(r[2][2] for r in hr80):.2f} V, V-MOT '
                  f'{min(r[2][3] for r in hr80):.2f}-{max(r[2][3] for r in hr80):.2f} V')
            print(f'   latest-latch H-R case: {mode} {p} W C_mod {cm * 1e6:.0f} uF aux {aux * 1e3:.1f} mA C_V '
                  f'{cv * 1e3:.2f} mF T_fall {tf * 1e3:.0f} ms eFuse {efc}: latch {ms(worst[1].get("t_latch"))} ms, '
                  f'exit {ms(worst[1].get("t_exit_trigger"))} ms')

# ----------------------------------------------------------------------------------------------------------- 3b
hdr('3b', 'FC fall-time sweep: bus state at t_rec with FC_BUS still HIGH (severity = 16 V - V_bus)')
print('Hazard class at t_rec (FC boost leaves VIN UVLO with FC_BUS + FC_REG HIGH):')
print('  BENIGN  : V_bus >= 15.5 V (bus held by BT after a ride-through; the boost charges only its own 30 uF)')
print('  IN-FAMILY: 12.0 <= V_bus < 15.5 V (no deeper than the TP0178 12.15 V dropout, nondestructive)')
print('  HAZARD  : V_bus < 12.0 V (TP0010 class: 6.5 V sags with 3+ A reconnect spikes, 33 events nondestructive,')
print('            "Death-5-family stress" in boost-bringup-debug.md); also flagged if D-MT-EN is joined then')
worst = {}
for (mode, p), aux, cv, tf, efc, var, pol in itertools.product(modes, (0.0005, 0.015, 0.15), (0.48e-3, 1.5e-3, 5e-3),
                                                               (0.0, 0.010, 0.020, 0.040, 0.060, 0.075),
                                                               ((11.47, 12.38), (12.10, 12.88)), ('P', 'D'),
                                                               ('E1', 'E2')):
    e = run(mode, p, 221e-6, aux, cv, tf, efc, var, pol, 1.341e-3)
    for tr in (0.080, 0.100):
        fc_closed, mot_j, vb, vv = hr_flag(e, tr)
        if not fc_closed:
            cls = 'OPEN'
        elif vb >= 15.5:
            cls = 'BENIGN'
        elif vb >= 12.0:
            cls = 'IN-FAMILY'
        else:
            cls = 'HAZARD'
        key = (pol, var, tr)
        worst.setdefault(key, {}).setdefault(cls, []).append((mode, p, aux, cv, tf, efc, vb, vv, mot_j,
                                                             e.get('t_latch'), e.get('t_exit_trigger')))
for key in sorted(worst):
    d = worst[key]
    tot = sum(len(x) for x in d.values())
    s = ', '.join(f'{c} {len(d[c])}' for c in ('OPEN', 'BENIGN', 'IN-FAMILY', 'HAZARD') if c in d)
    print(f'[{key[0]} variant {key[1]} t_rec {key[2] * 1e3:.0f} ms] {tot} cases: {s}')
    for c in ('IN-FAMILY', 'HAZARD'):
        if c in d:
            lo = min(d[c], key=lambda r: r[6])
            print(f'    {c}: T_fall {sorted(set(r[4] * 1e3 for r in d[c]))} ms, modes {sorted(set(r[0] for r in d[c]))},'
                  f' aux {sorted(set(r[2] * 1e3 for r in d[c]))} mA; lowest bus {lo[6]:.2f} V (V-MOT {lo[7]:.2f} V, '
                  f'D-MT-EN joined {lo[8]}, latch {ms(lo[9])} ms, exit {ms(lo[10])} ms, case {lo[0]} T_fall '
                  f'{lo[4] * 1e3:.0f} ms aux {lo[2] * 1e3:.1f} mA C_V {lo[3] * 1e3:.2f} mF)')

# =========================================================================================================== 4
hdr(4, 'Worst-gap sensitivity: one 9.76 ms iteration at the exit trigger / at the 12 V crossing (E1 and E2)')
for mode, p, aux, var in (('CP', 14.8, 0.015, 'P'), ('MPPT', 14.8, 0.0005, 'P'), ('MPPT', 14.8, 0.0005, 'D')):
    for pol in ('E1', 'E2'):
        base = run(mode, p, 221e-6, aux, 1.5e-3, 0.0, (12.10, 12.88), var, pol, 1.341e-3)
        for anchor in ('t_exit_trigger', 't_vbus_lt12_seen'):
            ga = base.get(anchor)
            if ga is None:
                continue
            e = run(mode, p, 221e-6, aux, 1.5e-3, 0.0, (12.10, 12.88), var, pol, 1.341e-3, gap_at=ga)
            print(f'{mode:4s} aux {aux * 1e3:5.1f} mA var {var} {pol} gap at {anchor:17s}: latch {ms(e.get("t_latch"))}'
                  f' ({e.get("latch_by", "none")}), MOT LOW {ms(e.get("t_mot_low"))}, bond {ms(e.get("t_bond"))} at '
                  f'V_M {e.get("vm_at_bond", float("nan")):5.2f} V; FC_BUS HIGH at 80 ms: {hr_flag(e, 0.080)[0]}')

# =========================================================================================================== 5
hdr(5, 'BT_BUS re-close of policy E1 when it conducts before the latch (capture-11 family check)')
for slope in (0.5e3, 0.81e3):
    sub = []
    for (mode, p), cm, aux, cv, tf, efc, var in itertools.product(modes, (221e-6,), (0.0005, 0.015, 0.15),
                                                                   (0.48e-3, 1.5e-3, 5e-3), (0.0, 0.020),
                                                                   ((12.10, 12.88),), ('P', 'D')):
        e = run(mode, p, cm, aux, cv, tf, efc, var, 'E1', 1.341e-3, slope=slope)
        if e.get('t_bt_conduct') is not None:
            sub.append((mode, aux, cv, var, e))
    print(f'ramp {slope / 1e3:.2f} V/ms: {len(sub)} of 108 cases conduct before the latch')
    for mode, aux, cv, var, e in sub[:12]:
        print(f'   {mode:4s} aux {aux * 1e3:5.1f} mA C_V {cv * 1e3:4.2f} mF var {var}: conducts {ms(e["t_bt_conduct"])} ms,'
              f' peak bus-side current {e["bt_peak_i"]:5.2f} A, latch {ms(e.get("t_latch"))}')
print('   capture 11 (boost-bringup-debug.md): the same 100 nF ramp onto V-MOT + VESC drew a 0.7-1 A hump, no SCP cut;')
print('   RT1987 SCP: 2.5 A start limit, 250 us timer, disabled after tON (DS-00 s17.5).')

# =========================================================================================================== 6
hdr(6, 'Energies and stresses per unpredicted purge')
for cm in (100e-6, 221e-6):
    c = cm + C_EO
    for v_dump in (11.0, 13.0, 15.9):
        print(f'  R_MD dump from {v_dump:5.2f} V, C_M {c * 1e6:4.0f} uF: {0.5 * c * v_dump ** 2 * 1e3:5.1f} mJ, '
              f'peak {v_dump / R_MD:4.2f} A, 15.9->9 V in {R_MD * c * math.log(v_dump / 9.0) * 1e3:4.2f} ms'
              if v_dump > 9 else '')
print('  IC1 5.3: one dump at 21.5 V / 221 uF = 51 mJ is the design case; the probe bypass case is 0.17 J in 10 ms.')
print('  RT1987 reverse differentials in the collapsed state (abs max VIN, VOUT -0.3..40 V to GND, DS-00 s10):')
for name, vin, vout in (('D-MT-EN, V-MOT at the chopper clamp 22.13 V, bus 0 V', 0.0, 22.13),
                        ('D-BC-RG (pin 30 LOW), V-MOT 22.13 V, VCHG-IN 0 V', 22.13, 0.0),
                        ('D-BT-EN (pin 28 LOW), BT boost 16 V, bus 0 V', 16.0, 0.0),
                        ('D-BC-FC (pin 31 LOW), bus 0 V, VCHG-IN 12.9 V', 0.0, 12.9)):
    print(f'   {name:55s}: |VIN-VOUT| {abs(vin - vout):5.2f} V, max pin {max(vin, vout):5.2f} V vs 40 V')
print('  Teensy supply: VBT = pack 7.4-8.4 V (no VBUS -> VBT path, facts_board 6.3 item 2); LM1084 needs >= 6.5 V')
for vp, i_teensy, r_ret in ((7.4, 0.25, 0.020), (7.4, 0.25, 0.100)):
    print(f'   pack {vp} V, logic load {i_teensy} A (boost-bringup-debug.md capture 7: ~200 mA), return {r_ret * 1e3:.0f} mOhm'
          f' (sense R_s + leads, ASSUMED): LM1084 input {vp - i_teensy * r_ret:5.3f} V, margin '
          f'{vp - i_teensy * r_ret - 6.5:5.3f} V')
print('  E1 BT re-close pack current (bus-side 1.0 A at 16 V, eta 0.92 ASSUMED, pack 7.4 V): '
      f'{1.0 * 16 / (0.92 * 7.4):4.2f} A; pack sag at 50-100 mOhm (boost-bringup-debug.md capture 7 note): '
      f'{1.0 * 16 / (0.92 * 7.4) * 0.05:4.2f}-{1.0 * 16 / (0.92 * 7.4) * 0.10:4.2f} V')
print('  State 99 latched until power cycle: logic drain on the pack at 0.2-0.25 A (UNCONFIRMED) is 4.8-6.0 Ah/day;'
      ' a 5 Ah pack (capacity unverified, facts_prior s9) reaches its cut-off within about a day unless power-cycled.')
