#!/usr/bin/env python3
"""bt6_transient_sim.py - battle-test round 6, TRANSIENT lens, against IC1 revision 9 section 9.11.

Standard library only. Run from the review folder:
    .venv_hil/Scripts/python.exe calc/bt6_transient_sim.py > calc/bt6_transient_sim_output.txt
Cited as "bt6 section N". The launch-current bag scan is calc/bt6_bag_launch.py (miniforge, mcap_ros2).

Sections
  1  Predicted purge at exactly T_lead,min (State 1): conduction margin; the PURGE_LEAD_SHORT bus (UV_BUS timing).
  2  State-2 standstill (variant D-s): what the share override R_OV can do. Filtered total after the feed drop
     (SHARE_GOV_FILT_ALPHA 0.05/tick, ino:3330, ino:14292), the closed-loop exit (2*I_min - hyst = 0.20 A,
     ino:14326), the in-band minority clip lo = SHARE_MINORITY_I_MIN_A / I_tot (0.125 A, ino:3202, ino:14581-14583),
     the inverted-band bounded HOLD (ino:14624-14627) and the open-loop HOLD (ino:14380-14385, ino:13746).
  3  Unpredicted purge, policy E2: sensitivity of the latch time to the two ASSUMED inputs that set the decay of the
     merged bus + V-MOT node under the ideal MPPT hold - the VESC idle current (0.075 A ASSUMED, TODO(calibrate),
     HIL_PLANT.md 4.3) and the FC-profile MPPT threshold (13.82 V, BENCH S0-4). Re-uses the revision-9 collapse
     model (calc/purge_collapse_sim.py, "pc") unchanged, only those two globals are swept.
  4  Variant D: braking onto the FC-only bus.
  5  State 99 after an unpredicted purge: the pack drain until a power cycle and the next power-up.
"""
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def hdr(n, s):
    print('\n' + '=' * 110)
    print(f'Section {n}: {s}')
    print('=' * 110)


# ===================================================================================================================== 1
hdr(1, 'Predicted purge at exactly T_lead,min = 60 ms (State 1, variant P)')
SLOPE = 15.95 / 19.77e-3          # D-BT-EN soft-start onto a live 15.95 V bus, calc9 s1 (V/s)
for tdon in (8e-3, 12e-3, 16e-3, 20e-3):
    t_write = 1.34e-3 + 0.15e-3 + 13.15e-3 + 13.15e-3      # calc9 s1 deadline chain to the BT_BUS write
    t_cond = t_write + tdon + 19.77e-3
    print(f'  t_D_ON {tdon * 1e3:4.0f} ms: BT_BUS write {t_write * 1e3:5.2f} ms, D-BT-EN fully on {t_cond * 1e3:5.2f} ms '
          f'after the prediction; margin to a 60 ms onset {60 - t_cond * 1e3:+6.2f} ms')
print('  At the onset the bus load is aux + VESC idle; the FC boost leaves regulation (VIN UVLO 1.8-2.0 V, SLVSFP3C 7.5)')
print('  and D-FC-EN blocks reverse current, so the BT boost takes the load through an enabled ideal diode with no')
print('  switching event. No contradiction.')
print('\n  PURGE_LEAD_SHORT (D-BT-EN not yet on at the onset): bus decay before the RT1987 ramp catches it.')
print('  D-MT-EN blocks V-MOT -> bus; V-MOT joins only once it has fallen below the bus (pc model).')
C_B, C_F = 35e-6, 30e-6
for aux in (0.0005, 0.015, 0.15):
    for cv in (0.48e-3, 1.5e-3, 5e-3):
        # bus + FC boost output (F joined through D-FC-EN while F > B) decay alone at aux; V-MOT at 0.075 A
        vb, vv, t, dt = 15.9, 15.9, 0.0, 1e-5
        t12 = None
        while t < 0.2:
            vb -= aux / (C_B + C_F) * dt
            vv -= 0.075 / cv * dt
            if vv < vb:    # D-MT-EN forward (bus -> V-MOT): charge-conserving merge (pc projection)
                vb = vv = ((C_B + C_F) * vb + cv * vv) / (C_B + C_F + cv)
            t += dt
            if t12 is None and vb < 12.0:
                t12 = t
        print(f'   aux {aux * 1e3:6.1f} mA, V-MOT {cv * 1e3:4.2f} mF: bus below 12 V at '
              f'{"   >200" if t12 is None else f"{t12 * 1e3:7.1f}"} ms; UV_BUS latch (20 ms dwell) at '
              f'{"    none" if t12 is None or t12 + 0.02 > 0.2 else f"{(t12 + 0.020) * 1e3:7.1f}"} ms if the ramp has not caught it')
print('  Section 9.11.3 states "UV_BUS ... puts FC_BUS LOW about 22-23 ms after the onset, before the earliest FC recovery')
print('  at 80 ms": compare the rows above. The statement is the heavy-aux corner only; where the bus decays slowly the late')
print('  D-BT-EN ramp (0.81 V/ms) catches a bus that is still above 12 V, so the outcome is a ride-through (BENIGN at t_rec),')
print('  not a latch. No hazard either way; the stated timing is not general.')

# ===================================================================================================================== 2
hdr(2, 'Variant D-s: the share override at standstill (firmware constants, fw v37 rev 2)')
ALPHA, I_MIN, HYST, H_MIN = 0.05, 0.125, 0.05, 0.10
I_GATE_IN, I_GATE_OUT = 2 * I_MIN, 2 * I_MIN - HYST
print(f'  closed-loop entry > {I_GATE_IN:.3f} A, exit < {I_GATE_OUT:.3f} A of filtered total; the in-band clip floor lo = '
      f'{I_MIN}/I_tot reaches DROOP_R_MIN 0.15 only at I_tot >= {I_MIN / 0.15:.3f} A')
print('  Window (FC-only): I_tot = charger 0.82-0.93 A (out s1) + aux. After the feed drop: standstill total.')
for i_win in (0.97, 1.08):
    for i_ss, lab in ((0.016, 'bag standstill median 0.016 A (bt6_bag_launch)'), (0.165, 'plant aux 0.09 + VESC 0.075'),
                      (0.225, 'plant aux 0.15 + VESC 0.075')):
        for tl in (1.0e-3, 1.341e-3):
            f, n = i_win, 0
            t_lo015 = t_exit = None
            while n < 400:
                n += 1
                f += ALPHA * (i_ss - f)
                if t_lo015 is None and f < I_MIN / 0.15:
                    t_lo015 = n * tl
                if t_exit is None and f < I_GATE_OUT:
                    t_exit = n * tl
            lo_end = min(0.5, H_MIN / max(i_ss, 1e-6))
            print(f'   window {i_win:4.2f} A -> {lab:44s} loop {tl * 1e3:5.3f} ms: R_OV 0.15 out of the clip from '
                  f'{t_lo015 * 1e3:5.1f} ms; open loop (HOLD) from '
                  f'{"never (stays in the 0.20-0.25 A sliver: bounded HOLD [" + format(lo_end, ".3f") + ", " + format(1 - lo_end, ".3f") + "])" if t_exit is None else format(t_exit * 1e3, "5.1f") + " ms"}')
print('  The override starts after the bonded confirmation, 5.81-15.27 ms after the prediction (Table 21). By then the')
print('  filtered total has already fallen below 0.833 A, so the in-band clip lifts R_OV to lo > 0.15; the dark-BT handoff')
print('  slew (0.002/tick, ino:3288) moves r by at most 0.002 x ticks until the loop leaves closed loop; after that the')
print('  open-loop branch HOLDS ("AT THE SHIPPED CONSTANTS THIS IS ALWAYS THE HOLD", ino:13746) or the sliver HOLD binds.')
for tl in (1.0e-3, 1.341e-3):
    for i_win in (0.97, 1.08):
        f, n, moved = i_win, 0, 0.0
        while f >= I_GATE_OUT and n < 400:
            n += 1
            f += ALPHA * (0.165 - f)
            if n * tl >= 5.81e-3:
                moved += 0.002
        print(f'   loop {tl * 1e3:5.3f} ms, window {i_win:4.2f} A: maximum ratio motion from the override start to the HOLD '
              f'{moved:5.3f} (closed loop ends after {n * tl * 1e3:5.1f} ms); Table 20 assumes a 0.35 + 0.36 walk in 258.8 ms')
print('  The direction is not even fixed: if the window wound r to the 0.15 clamp (section 9.11.3, UNCONFIRMED), the clip')
print('  lo = 0.125/I_tot (0.4 at 0.31 A) walks r UP, i.e. toward the fuel cell, during the same interval.')
print('  Consequence: at standstill at most 0.12 of ratio motion (direction set by the clip) happens after the close; T_lead,nom 290 ms for D-s rests on a walk that the')
print('  firmware never executes. Re-deriving D-s with T_lead,min 60 ms (as variant P) moves the binding re-entry gate to')
print('  V_chg below 11 V (calc9 s2: onset + 0.391-0.509 s) and the dead time from 0.573-0.785 s to 0.450-0.569 s per period.')

# ===================================================================================================================== 3
hdr(3, 'Unpredicted purge, policy E2: latch time vs the VESC idle current and the MPPT threshold (pc model)')
src = open(os.path.join(HERE, 'purge_collapse_sim.py'), encoding='utf-8').read()
ns = {'__name__': 'pc_model'}
exec(compile(src.split('def hr_flag')[0], 'purge_collapse_sim.py(head)', 'exec'), ns)
print('  MPPT ideal hold, P_in 14.8 W, C_mod 221 uF, eFuse corner (12.10, 12.88), variant P, p99 loop 1.341 ms, E2.')
print('  Class at t_rec (FC boost leaves VIN UVLO): OPEN = FC_BUS LOW; else bus voltage (pc section 3b classes).')
fails = []
for vm in (13.82, 14.3):
    for ives in (0.075, 0.05, 0.03, 0.02, 0.01):
        for aux in (0.0005, 0.015):
            for cv in (0.48e-3, 1.5e-3, 5e-3):
                for tf in (0.0, 0.020):
                    ns['I_VESC'], ns['V_MPPT'] = ives, vm
                    e = ns['run']('MPPT', 14.8, 221e-6, aux, cv, tf, (12.10, 12.88), 'P', 'E2', 1.341e-3)
                    lat = e.get('t_latch')
                    cls = {}
                    for tr in (0.080, 0.100, 0.140):
                        s = e['snap'][tr]
                        closed = s['en']['FCBUS'] and s['en']['FCREG'] and not s['uv']['FCBUS']
                        vb = s['v']['B']
                        cls[tr] = 'OPEN' if not closed else ('BENIGN' if vb >= 15.5 else ('IN-FAMILY' if vb >= 12.0 else 'HAZARD'))
                        cls[tr] += '' if not closed else f' {vb:5.2f} V'
                    if cls[0.080] != 'OPEN':
                        fails.append((vm, ives, aux, cv, tf, lat, cls))
print(f'  {len(fails)} of 120 cases with FC_BUS and FC_REG still HIGH at t_rec 80 ms (I_VESC 0.075 A, the pc value: '
      f'{sum(1 for x in fails if x[1] == 0.075)})')
for vm, ives, aux, cv, tf, lat, cls in fails:
    print(f'   V_MPPT {vm:5.2f} V I_VESC {ives * 1e3:4.0f} mA aux {aux * 1e3:5.1f} mA C_V {cv * 1e3:4.2f} mF T_fall '
          f'{tf * 1e3:2.0f} ms: latch {"none by 160 ms" if lat is None else format(lat * 1e3, ".1f") + " ms"}; at 80 ms '
          f'{cls[0.080]}; 100 ms {cls[0.100]}; 140 ms {cls[0.140]}')
ns['I_VESC'], ns['V_MPPT'] = 0.075, 13.82
print('  Why the latch does not slip: under the hold the bus + VCHG-IN + module node (about 0.31 mF) decays on I_IDLE,')
print('  the bleeds and aux, while V-MOT decays on I_VESC / C_V. D-MT-EN joins V-MOT only once V-MOT has fallen BELOW the')
print('  bus, so a SMALLER VESC idle current keeps V-MOT out of the merged node and the 13.0 V reading comes sooner; a')
print('  higher MPPT threshold (14.3 V) adds only the extra 1.3 V on the 0.31 mF node. The E2 latch-before-recovery claim')
print('  survives both ASSUMED inputs over the swept range. No contradiction.')

# ===================================================================================================================== 4
hdr(4, 'Variant D: braking onto the FC-only bus')
print('  In an FC window pin 30 is LOW (window types exclusive, OR-7) and D-MT-EN conducts bus -> V-MOT only, so the')
print('  regen current charges V-MOT alone; V-MOT is bounded by the VESC stop (~21.35 V) and the chopper clamp (22.13 V,')
print('  facts_prior s6). This is the same path as fw v37 rev 2 Run today (AG105_VBATN_ISOLATED 0 holds REGEN LOW).')
for cv in (0.48e-3, 1.5e-3, 5e-3):
    t_back = cv * (21.35 - 15.95) / 0.075
    print(f'   V-MOT {cv * 1e3:4.2f} mF: after braking it returns from 21.35 V to the bus on the VESC idle in '
          f'{t_back * 1e3:6.1f} ms (0.075 A ASSUMED); RT1987 D-MT-EN |VOUT-VIN| at most {22.13 - 15.95:4.2f} V vs 40 V abs max')
print('  FC-only bus side: the traction step DOWN at the brake onset removes at most 0.33 A + 0.075 A from the FC boost;')
print('  the bus rises by the droop k_d x dI (K_DROOP 0.30 Ohm held in FC windows, fw v28 rev 4): about 0.12 V, inside')
print('  the 17.5 V OV_BUS limit. No rating is exceeded and no new path exists. No contradiction.')

# ===================================================================================================================== 5
hdr(5, 'State 99 after an unpredicted purge: pack drain until a power cycle, and the next power-up')
print('  pc section 6: the Teensy stays on the pack through the LM1084 at 0.2-0.25 A (UNCONFIRMED) until a power cycle;')
print('  IC1 Table 24 D6/D7 and section 9.11.5 "Residuals" record it as a property of the present State 99.')
for cap in (2.0, 3.0, 5.0):
    for i in (0.20, 0.25):
        print(f'   {cap:3.1f} Ah of remaining charge at {i:4.2f} A: {cap / i:5.1f} h to empty')
print('  Variant P is the parked mode that IC1 sells at 1.18-1.20 Ah per parked hour (Table 22), i.e. the mode most likely')
print('  to run unattended for hours; a parked window opens only below 8.0 V (entry gate), so the pack is already below')
print('  the top of its window when State 99 latches.')
print('  The LM1084 stops regulating below 6.5 V input (SNVS037H 5.5) but passes pack - dropout to the Teensy VIN; nothing')
print('  in IC1 or fw v37 disconnects the logic load at a pack floor, the pack PCM is "missing primary" (facts_prior s9),')
print('  and the BQ29200 is OVP-only. On the next power-up UV_BATT (7.4 V) uses the ARMED dwell shape: it arms only after')
print('  V_batt has been seen at or above V_BATT_ARM_THRESH 7.8 V (ino:2261-2267), so a pack that drained below 7.4 V')
print('  never arms it, while the FC-window entry gate is only "V_batt below 8.0 V" (Table 25 code 7) with no lower bound;')
print('  the Ag105 then pre-charges at 10 % below 2.7 V/cell and charges normally above (DS p.6, facts_ag105).')
