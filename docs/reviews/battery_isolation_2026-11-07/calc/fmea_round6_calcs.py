#!/usr/bin/env python3
"""Battle-test round 6 (FMEA of the FC window between purges, IC1 revision 9). Standard library only.

Run:  .venv_hil/Scripts/python.exe calc/fmea_round6_calcs.py > calc/fmea_round6_calcs_output.txt
Cited by battletest/fmea_round6.md as "r6 section N".

Section 1 - BT_BUS re-close FAILED or LATE at a PREDICTED purge (IC1 rev 9 row F59, section 9.11.3 last paragraph).
  State at the onset (t = 0): the pre-purge sequence of IC1 9.11.3 steps 1-4 is complete - feed dropped, module
  dumped, pack bonded, BT_BUS written HIGH at 15.27 ms after the prediction (Table 21 worst healthy), i.e. at
  t = -(T_lead,min - 15.27) = -44.73 ms for T_lead,min = 60 ms. The session has ended at that write, so
  ERR_FC_ONLY_COLLAPSE is NOT evaluated (IC1 Table 16 row, 9.11.5 SC-1); only UV_BUS protects (IC1 12.6 item 5).
  D-BT-EN either never conducts (single fault: Q_X1 drain-source short - row F40, no readback; FCQ net stuck HIGH
  so Q_X1 clamps EN_BE_X; EN_BE_X or pin-28 path open; RT1987 failed) or conducts after t_D_ON (no datasheet
  maximum, IC1 open item 2) plus its CSS ramp.
  Node model, loads, source and firmware are those of calc/purge_collapse_sim.py (pc), reduced to the nodes that
  exist with the charger path off: F (FC boost output, 30 uF) -D-FC-EN-> B (VBUS, 35 uF) -D-MT-EN-> V (V-MOT,
  0.48/1.5/5 mF). Bus-side aux 0.5/15/150 mA on B and VESC 0.075 A on V above 8 V (pc docstring). FC boost output
  current I0*max(0, 1 - t/T_fall), I0 = the pre-purge load, T_fall swept 0-75 ms (pc section 3b sweep values).
  Firmware: p99 loop 1.341 ms; UV_BUS adds min(dt, 5 ms) below 12.0 V, leaks 0.05 dt above, latches at 20 ms
  (ino:2163, 7369-7377); State 99 phase 0 on the next iteration drops FC_BUS and BT_BUS (IC1 9.9).
  Classification at the FC recovery instant t_rec (80 ms, 100 ms) exactly as pc section 3b:
    OPEN      FC_BUS already LOW;   BENIGN  V_bus >= 15.5 V;   IN-FAMILY 12.0-15.5 V;
    HAZARD    V_bus < 12.0 V with FC_BUS and FC_REG HIGH (the TP0010 class that revision 9 removed with policy E2).
  Remedy R: ERR_FC_ONLY_COLLAPSE reading (b) (V_bus below 12.0 V, or below 13.5 V, no dwell) kept armed from the
  BT_BUS write until the declared end of the purge (13.5 V: the window-entry floor; recorded two-source purges held
  15.29-15.93 V, calc/purge_seq_bags_output.txt section 5).

Section 2 - share override R_OV at standstill (IC1 9.11.3 step 5) against the fw v37 rev 2 feedforward clip.
  shareFeedforwardClipTarget() (ino:13772-13779): lo = SHARE_MINORITY_I_MIN_A / tot (0.125 A, ino:3202); an empty
  band (lo >= hi) returns prevRatio (HOLD). Open-loop mode holds below 2*I_min - SHARE_GOV_OL_HYST_A = 0.20 A
  (ino:3233, ino:14367). The EMA (alpha 0.05 per tick, ino:3330, ino:14292) decay after the feed drop is computed.

Section 3 - survivor blanking against D-BT-EN conduction (IC1 Table 21; ino:4869).
"""

DT = 20e-6
C_F, C_B = 30e-6, 35e-6
I_VESC, V_VESC_MIN = 0.075, 8.0
V0 = 15.9
V_UV, UV_LATCH, UV_LEAK, UV_CAP = 12.0, 20.0, 0.05, 5.0
T_LOOP = 1.341e-3
T_WRITE = -(60.0e-3 - 15.27e-3)     # BT_BUS write relative to the onset, T_lead,min 60 ms, worst healthy chain
VBT = 16.0


def run(aux, c_v, t_fall, t_don, slope, remedy=False, t_end=0.160, v_rem=12.0):
    """t_don None = D-BT-EN never conducts. Returns events and the snapshot at 80/100 ms."""
    cap = {'F': C_F, 'B': C_B, 'V': c_v}
    v = {k: V0 for k in cap}
    i0 = aux + I_VESC
    en = {'FCBUS': True, 'MOT': True, 'BTBUS': True, 'FCREG': True, 'BTREG': True}
    dwell = 0.0
    latch_t = None
    s99 = None
    next_it = 0.0
    last_it = -T_LOOP
    snap = {}
    ev = {}
    vb_min = V0
    t = T_WRITE
    # pre-onset interval: steady bus, only the BT ramp may start (no effect while the ramp is below V_bus)
    n = int((t_end - T_WRITE) / DT)
    for k in range(n):
        t = T_WRITE + k * DT
        if t < 0.0:
            i_fc = i0
        else:
            i_fc = i0 * max(0.0, 1.0 - t / t_fall) if t_fall > 0 else 0.0
        di = {'F': i_fc, 'B': -aux if v['B'] > 0.5 else 0.0, 'V': -I_VESC if v['V'] > V_VESC_MIN else 0.0}
        for kk in cap:
            v[kk] = max(0.0, v[kk] + di[kk] * DT / cap[kk])
        # ideal-diode merges (forward only)
        for _ in range(3):
            changed = False
            if en['FCBUS'] and v['F'] > v['B'] + 1e-9:
                q = C_F * v['F'] + C_B * v['B']
                v['F'] = v['B'] = q / (C_F + C_B)
                changed = True
            if en['MOT'] and v['B'] > v['V'] + 1e-9:
                grp = ['B', 'V'] + (['F'] if (en['FCBUS'] and abs(v['F'] - v['B']) < 1e-6) else [])
                q = sum(cap[x] * v[x] for x in grp)
                cs = sum(cap[x] for x in grp)
                for x in grp:
                    v[x] = q / cs
                changed = True
            # D-BT-EN ramp: voltage source behind TRCB, conducts when the ramp exceeds V_bus
            if en['BTBUS'] and t_don is not None and t >= T_WRITE + t_don:
                vr = min(VBT, slope * (t - T_WRITE - t_don))
                if v['B'] < vr - 1e-9:
                    ev.setdefault('t_bt_conduct', t)
                    v['B'] = vr
                    if en['FCBUS'] and v['F'] < v['B']:
                        pass  # D-FC-EN blocks reverse
                    if en['MOT'] and v['V'] < v['B']:
                        v['V'] = v['B']
                    changed = True
            if not changed:
                break
        if t >= 0.0:
            vb_min = min(vb_min, v['B'])
        for tr in (0.080, 0.100):
            if tr not in snap and t >= tr:
                snap[tr] = dict(vb=v['B'], vv=v['V'], fcbus=en['FCBUS'], fcreg=en['FCREG'])
        if t >= next_it:
            dt_ms = (t - last_it) * 1e3
            last_it = t
            next_it = t + T_LOOP
            if s99 is not None:
                if t - s99 >= 0.010:
                    en['MOT'] = False
                if t - s99 >= 0.020:
                    en['FCREG'] = en['BTREG'] = False
                continue
            if latch_t is not None:
                s99 = t
                en['FCBUS'] = en['BTBUS'] = False
                ev['t_fcbus_low'] = t
                continue
            if remedy and t >= T_WRITE and v['B'] < v_rem:
                latch_t = t
                ev['t_latch'] = t
                ev['by'] = 'R (no dwell)'
                continue
            armed = (en['FCBUS'] and en['FCREG']) or (en['BTBUS'] and en['BTREG'])
            if armed:
                d = min(dt_ms, UV_CAP)
                if v['B'] < V_UV:
                    dwell += d
                    ev.setdefault('t_lt12', t)
                    if dwell >= UV_LATCH:
                        latch_t = t
                        ev['t_latch'] = t
                        ev['by'] = 'UV_BUS'
                else:
                    dwell = max(0.0, dwell - UV_LEAK * d)
    ev['snap'] = snap
    ev['vb_min'] = vb_min
    return ev


def cls(s):
    if not (s['fcbus'] and s['fcreg']):
        return 'OPEN'
    if s['vb'] >= 15.5:
        return 'BENIGN'
    if s['vb'] >= 12.0:
        return 'IN-FAMILY'
    return 'HAZARD'


def ms(x):
    return '   -  ' if x is None else '%6.1f' % (x * 1e3)


def hdr(n, s):
    print('=' * 110)
    print('Section %d: %s' % (n, s))
    print('=' * 110)


AUX = (0.0005, 0.015, 0.150)
CV = (0.48e-3, 1.5e-3, 5.0e-3)
TF = (0.0, 0.010, 0.020, 0.040, 0.060, 0.075)

hdr(1, 'BT_BUS re-close failed (never conducts) at a PREDICTED purge; UV_BUS the only detector after the write')
for remedy, v_rem in ((False, 12.0), (True, 12.0), (True, 13.5)):
    tally = {}
    worst = None
    rows = []
    for aux in AUX:
        for cv in CV:
            for tf in TF:
                ev = run(aux, cv, tf, None, 0.81e3, remedy=remedy, v_rem=v_rem)
                for tr in (0.080, 0.100):
                    c = cls(ev['snap'][tr])
                    tally[(tr, c)] = tally.get((tr, c), 0) + 1
                    if c == 'HAZARD':
                        vb = ev['snap'][tr]['vb']
                        if worst is None or vb < worst[0]:
                            worst = (vb, aux, cv, tf, tr, ev)
                if not remedy and aux == 0.015 and cv == 1.5e-3:
                    rows.append((tf, ev))
    label = ('remedy R (reading (b) kept to the purge end, no dwell, threshold %.1f V)' % v_rem) if remedy else 'IC1 rev 9 as written (UV_BUS 20 ms dwell)'
    print('  %s, %d cases:' % (label, len(AUX) * len(CV) * len(TF)))
    for tr in (0.080, 0.100):
        print('    t_rec %3d ms: ' % (tr * 1e3) + ', '.join('%s %d' % (c, tally.get((tr, c), 0))
                                                         for c in ('OPEN', 'BENIGN', 'IN-FAMILY', 'HAZARD')))
    if worst:
        vb, aux, cv, tf, tr, ev = worst
        print('    lowest HAZARD bus: %.2f V at t_rec %d ms (aux %.1f mA, V-MOT %.2f mF, T_fall %.0f ms; 12 V crossing %s ms,'
              ' latch %s ms, FC_BUS LOW %s ms; V-MOT %.2f V)'
              % (vb, tr * 1e3, aux * 1e3, cv * 1e3, tf * 1e3, ms(ev.get('t_lt12')), ms(ev.get('t_latch')),
                 ms(ev.get('t_fcbus_low')), ev['snap'][tr]['vv']))
    if rows:
        print('    trace, aux 15 mA, V-MOT 1.5 mF:')
        for tf, ev in rows:
            s = ev['snap'][0.080]
            print('      T_fall %4.0f ms: 12 V crossing %s, latch %s, FC_BUS LOW %s ms; at 80 ms V_bus %5.2f V, FC_BUS %s -> %s'
                  % (tf * 1e3, ms(ev.get('t_lt12')), ms(ev.get('t_latch')), ms(ev.get('t_fcbus_low')), s['vb'],
                     'HIGH' if s['fcbus'] else 'LOW', cls(s)))
print()
print('  Late (not failed) D-BT-EN: t_D_ON swept, BT_BUS written at %.2f ms before the onset, ramp 0.81 / 0.50 V/ms' % (-T_WRITE * 1e3))
for slope in (0.81e3, 0.50e3):
    for tdon in (0.012, 0.025, 0.040, 0.060, 0.080, 0.100):
        tally = {}
        for aux in AUX:
            for cv in CV:
                for tf in TF:
                    ev = run(aux, cv, tf, tdon, slope)
                    c = cls(ev['snap'][0.080])
                    tally[c] = tally.get(c, 0) + 1
        print('    slope %.2f V/ms, t_D_ON %5.1f ms (conduction ~%6.1f ms after the onset on a live bus): at 80 ms ' %
              (slope / 1e3, tdon * 1e3, (T_WRITE + tdon + VBT / slope) * 1e3)
              + ', '.join('%s %d' % (c, tally.get(c, 0)) for c in ('OPEN', 'BENIGN', 'IN-FAMILY', 'HAZARD')))

hdr(2, 'Share override R_OV at standstill: the feedforward clip band and the EMA after the feed drop')
I_MIN, HYST, ALPHA = 0.125, 0.05, 0.05
for tot in (0.09, 0.10, 0.12, 0.15, 0.20, 0.25):
    lo = I_MIN / tot
    hi = 1.0 - lo
    print('  filtered total %.3f A: lo %.3f, hi %.3f -> %s' % (tot, lo, hi, 'band EMPTY -> HOLD prevRatio (R_OV ignored)' if not lo < hi else 'clip to [lo, hi]'))
print('  open-loop entry below 2*I_min - hyst = %.2f A; closed loop needs above 2*I_min = %.2f A' % (2 * I_MIN - HYST, 2 * I_MIN))
for i_win, i_aux in ((1.03, 0.09), (1.25, 0.15)):
    f = i_win
    k = 0
    while f >= 2 * I_MIN - HYST:
        f += ALPHA * (i_aux - f)
        k += 1
    print('  window total %.2f A -> aux %.2f A after the feed drop: filtered total below 0.20 A after %d ticks '
          '(%.1f ms at the 1.13 ms median loop, %.1f ms at the 1.341 ms p99 loop)' % (i_win, i_aux, k, k * 1.13, k * 1.341))
print('  Standstill aux total 0.09-0.15 A (IC1 9.11.3) never re-opens the band: R_OV and the shift back move no MDAC code.')

hdr(3, 'Survivor blanking (30 ms from the BT_BUS write, ino:4869) against D-BT-EN conduction')
for tdon in (8, 10, 12, 15, 20):
    tcond = tdon + (15.95 / 35.0) * (100.0 / 0.0023 - 100.0) / 1000.0
    print('  t_D_ON %2d ms: conduction %.2f ms after the write; blanking ends at 30.00 ms -> %s'
          % (tdon, tcond, 'covered' if tcond <= 30.0 else 'UNCOVERED by %.2f ms' % (tcond - 30.0)))
print('  break-even t_D_ON = %.2f ms (IC1 Table 21 worst healthy: blanking end 45.3 ms < conduction 47.0 ms)'
      % (30.0 - (15.95 / 35.0) * (100.0 / 0.0023 - 100.0) / 1000.0))
