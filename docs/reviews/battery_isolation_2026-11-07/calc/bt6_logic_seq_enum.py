"""Battle-test round 6, LOGIC / SEQUENCING lens: model check of IC1 revision 9 (FC windows between purges).

Target: detailed_design_IC1.md revision 9, section 9.11 (9.11.1-9.11.7, Tables 20-27), 9.7, 9.7a, 9.7b, 9.9,
12.4 items 6-7, Table 16 `ERR_FC_ONLY_COLLAPSE`, rows F57-F62, Appendix G.  Extends calc/bt5_logic_seq_enum.py
(which reuses the bt4 network hw()) with:
  - an IDEAL predictor input (purge_tto, purge_active, UNKNOWN; PI-1..PI-7, design 9.11.2);
  - the pre-purge sequence (9.11.3 steps 1-6) and the post-purge re-entry (9.11.4);
  - the State-2 standstill window (variant D-s, 9.7) and the share latch / source selector of fw v37 rev 2
    (updateShareSetpointCutoff() ino:13357-13420, powerBalance() re-entry rule ino:14096-14125,
    chargingControl() F1 disarm ino:15444-15463, assertFcChargeEnable() ino:12743-12759);
  - the unpredicted-purge teardown (policy E2, Table 23) re-using the five-node model of calc/purge_collapse_sim.py
    (function run() copied and extended below; every constant is that script's, cited there).
Re-proves (a) no charger powered with the pack bonded, (b) never BT_BUS effective while in charge mode, (c) safe
defaults, (d) feed removed before the bond on every exit, (e) no re-close onto a collapsed node on FC recovery,
(f) no healthy-board latch across a predicted purge train.

Stdlib only.  Run:  .venv_hil/Scripts/python.exe calc/bt6_logic_seq_enum.py > calc/bt6_logic_seq_enum_output.txt

Numeric inputs (all cited):
  loop median 1.131 ms, p99 1.341 ms, one 9.76 ms gap                                       facts_firmware s8
  D-BT-EN conduction after the write onto a live bus: t_D_ON + 19.77 ms (CSS 100 nF)        design Table 20
  survivor blanking SHARE_CUT_SURVIVOR_BLANK_MS 30 ms                                        ino:4869
  SHARE_CUT_MAX_HANDOFF_A 0.5 A; gate 2*SHARE_MINORITY_I_MIN_A 0.25 A                         ino:3218; ino:14110
  V_BUS_CHARGED_THRESH 13.5 V (busHotPlugUnsafe guard on every BT_BUS re-close)              ino:2317, ino:13043
  LIMIT_V_BUS_MIN 12.0 V, UV_BUS 20 ms dwell, leak 0.05, dt cap 5 ms                         ino:2163, 2189-2193
  LIMIT_V_FC_MIN 4.5 V, UV_FC 1000 ms dwell, armed at V_FC_ARM_THRESH 7.0 V while routed     ino:2148, 2243, 2278
  purge period 10.34 s, duration 100-140 ms (+/-20 ms per edge), floor ~1 V                facts_prior s7
  VCHG-IN bleed tau 0.984 s, ERR_VCHG_FED 11 V with 1.0 s blanking after a feed drop          design 9.11.4
  FC recovery t_rec 80 / 100 ms after the onset                                              pc header
"""
import itertools
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bt5_logic_seq_enum as bt5   # noqa: E402  (main-guarded; hw5 only)

LOOPS = (1.131e-3, 1.341e-3)
GAP = 9.76e-3
T_SS = 19.77e-3
BLANK = 30e-3


def hdr(t):
    print("\n" + "=" * 110 + "\n" + t + "\n" + "=" * 110)


# =============================================================================================================
# Section 1: pin-vector check of every revision-9 sequence through the hardware network (invariants a, b, d)
# =============================================================================================================
# Each step is the commanded pin vector of the design text; env bits that a step leaves physically open are
# enumerated (node residual, resid, vmot_above, uc1/clr).  'ff1_prev' follows p33 (FF1 is set by the pin-33 edge).
SEQ = {
    "pre-purge exit 9.11.3 (P, D-s)": [
        ("window open (CHG_FC)", dict(p33="H", p28="L", p31="H", p29="H", p30="L", p32="H"), True),
        ("1 FC_CHARGE LOW", dict(p33="H", p28="L", p31="L", p29="H", p30="L", p32="H"), True),
        ("2 drain wait", dict(p33="H", p28="L", p31="L", p29="H", p30="L", p32="H"), True),
        ("3 pin 33 LOW (bond)", dict(p33="L", p28="L", p31="L", p29="H", p30="L", p32="H"), False),
        ("4 BT_BUS HIGH", dict(p33="L", p28="H", p31="L", p29="H", p30="L", p32="H"), False),
    ],
    "re-entry 9.7 entry 1-6": [
        ("bonded, BT_BUS HIGH", dict(p33="L", p28="H", p31="L", p29="H", p30="L", p32="H"), False),
        ("3 pin 33 HIGH", dict(p33="H", p28="H", p31="L", p29="H", p30="L", p32="H"), True),
        ("5 BT_BUS LOW", dict(p33="H", p28="L", p31="L", p29="H", p30="L", p32="H"), True),
        ("6 FC_CHARGE HIGH", dict(p33="H", p28="L", p31="H", p29="H", p30="L", p32="H"), True),
    ],
    "E2 collapse teardown Table 23": [
        ("latch (window open)", dict(p33="H", p28="L", p31="H", p29="H", p30="L", p32="H"), True),
        ("2 FC_CHARGE, REGEN LOW", dict(p33="H", p28="L", p31="L", p29="H", p30="L", p32="H"), True),
        ("3 bus switches LOW", dict(p33="H", p28="L", p31="L", p29="H", p30="L", p32="H"), True),
        ("5 pin 33 LOW", dict(p33="L", p28="L", p31="L", p29="H", p30="L", p32="H"), False),
        ("6 pin 32 LOW", dict(p33="L", p28="L", p31="L", p29="H", p30="L", p32="L"), False),
        ("7 MOT_PWR LOW", dict(p33="L", p28="L", p31="L", p29="L", p30="L", p32="L"), False),
    ],
    # The fw v37 S2 restore inside assertFcChargeEnable(true) (ino:12745-12749) writes FC_BUS HIGH; pin 27 has no
    # hardware term in hw(), so the vector is the same as entry step 6: the check is of the charger/pack network only.
    "UNKNOWN-after-onset commanded exit (PI-4)": [
        ("onset, window open", dict(p33="H", p28="L", p31="H", p29="H", p30="L", p32="H"), True),
        ("1 FC_CHARGE LOW", dict(p33="H", p28="L", p31="L", p29="H", p30="L", p32="H"), True),
        ("3 pin 33 LOW", dict(p33="L", p28="L", p31="L", p29="H", p30="L", p32="H"), False),
        ("4 BT_BUS HIGH (guard V_bus>=13.5)", dict(p33="L", p28="H", p31="L", p29="H", p30="L", p32="H"), False),
    ],
}


def section1():
    hdr("Section 1: revision-9 sequences through the hardware network: (a), (b), (b'), (d)")
    envkeys = ["v5", "bus", "vmot_above", "uc1", "clr", "resid", "node_resid"]
    print("  (a)  efuse on AND S_GND on (charger powered, pack bonded)")
    print("  (b)  hw() loop term: efuse on, fed from the bus, D-BT-SQ and D-BT-EN both effective")
    print("  (b') D-BT-EN effective while FF1 is set (BT boost draws through the sense in reverse; the key constraint)")
    print("  (d)  S_GND on while the module node is hot from a feed (efuse on), firmware-legal steps only")
    for name, steps in SEQ.items():
        cnt = dict(a=0, b=0, bp=0, d=0, n=0)
        for lab, pins, ff1prev in steps:
            for ev in itertools.product((False, True), repeat=len(envkeys)):
                env = dict(zip(envkeys, ev))
                env.update(teensy=True, ff1_prev=ff1prev)
                if env["uc1"] or env["clr"] or not env["v5"]:
                    continue            # hardware trips are rows F10/9.10; healthy sequence only here
                g = dict(pins)
                g.update(p5="Z", p8="Z", p20="Z", p34="T")
                s = bt5.hw5(g, env, None, 1)
                cnt["n"] += 1
                bten = g["p28"] == "H" and g["p31"] != "H"
                cnt["a"] += s["a"]
                cnt["b"] += s["b"]
                cnt["bp"] += bten and s["ff1"]
                cnt["d"] += s["sgnd"] and s["efuse"] and not env["resid"]
        print("  %-44s steps %d, states %5d: (a) %d  (b) %d  (b') %d  (d) %d"
              % (name, len(steps), cnt["n"], cnt["a"], cnt["b"], cnt["bp"], cnt["d"]))
    print("""
  Reading. Revision 9 adds no hardware, so the network invariants hold on every new sequence as written: the feed
  drop precedes the bond, BT_BUS is written only after the bond, and the E2 teardown writes no BT_BUS HIGH. The
  hardware alone does not hold (b') between exit step 1 and step 3: Q_X1 is keyed to FCQ only (design section 6
  item 9: EN_BE = p28 AND NOT FCQ), so from the FC_CHARGE LOW write to the bonded confirmation the BT_BUS closure is
  prevented by firmware ownership (12.4 item 7, SC-8) alone. That interval is 4.7-15.3 ms per exit (Table 21) and,
  with a window per 10.34 s period, occurs about 5.8 times per minute (section 2).""")


# =============================================================================================================
# Section 2: ideal predictor, pre-purge timing and the survivor-blanking race of the share latch (D-s)
# =============================================================================================================
def section2():
    hdr("Section 2: ideal predictor: BT_BUS conducting before the onset; selector cut against D-BT-EN conduction")
    worst = {}
    for state, tlead in (("P (State 1/98)", 0.060), ("D-s (State 2)", 0.290)):
        for loop, gap_at, drain, conf, tdon in itertools.product(LOOPS, (None, "drop", "drain", "confirm"),
                                                                  ("typ", "deadline"), ("typ", "deadline"),
                                                                  (0.008, 0.012)):
            t = loop + (GAP - loop if gap_at == "drop" else 0.0)          # prediction -> feed drop
            t += 0.15e-3                                                  # exit hold check
            dr = 2 * loop if drain == "typ" else max(0.010, 4 * loop)
            dr += (GAP - loop) if gap_at == "drain" else 0.0
            t += min(dr, 0.030)
            cf = 2 * loop if conf == "typ" else max(0.010, 4 * loop)
            cf += (GAP - loop) if gap_at == "confirm" else 0.0
            t += min(cf, 0.030)
            t_write = t
            t_cond = t_write + tdon + T_SS
            margin = tlead - t_cond
            key = state
            if key not in worst or margin < worst[key][0]:
                worst[key] = (margin, t_write, t_cond, loop, gap_at, drain, conf, tdon)
    for k, (m, tw, tc, loop, gap_at, drain, conf, tdon) in worst.items():
        print("  %-15s worst: BT_BUS write %.1f ms, conduction %.1f ms after the prediction, margin to the onset %.1f ms"
              " (loop %.3f ms, gap at %s, drain %s, confirmation %s, t_D_ON %.0f ms)"
              % (k, tw * 1e3, tc * 1e3, m * 1e3, loop * 1e3, gap_at, drain, conf, tdon * 1e3))
    print("  -> healthy chains conduct before the onset (Table 20 healthy worst 47.0 ms). The deadline chain with the one 9.76 ms gap placed before the feed drop (not inside the drain or confirmation, as Table 20 places it) and both waits at their 10 ms deadlines conducts at 61.7 ms: 1.7 ms past T_lead,min 60 ms.")
    print()
    print("  Share-latch survivor-blanking race (State 2 only; selector armed battery-only at the BT_BUS write):")
    print("  the latch cuts FC_BUS (sp 0.0 < DROOP_R_MIN, I_fc <= 0.5 A, both bus pins HIGH) once BT_BUS is out of its")
    print("  30 ms blanking (ino:13398-13410); the bus is source-less until D-BT-EN conducts.")
    for tdon in (0.008, 0.010, 0.012, 0.016, 0.020):
        cond = tdon + T_SS
        gap = max(0.0, cond - BLANK - 1.341e-3)
        # bus sag at the HIL aux rate 2.57 V/ms while the ramp (0.81 V/ms from 0 at write+t_D_ON) catches it
        t = BLANK + 1.341e-3
        vb = 15.9
        while True:
            vr = 0.81e3 * (t - tdon)
            if vr >= vb or t > 0.2:
                break
            vb -= 2.57e3 * 1e-5
            t += 1e-5
        print("    t_D_ON %4.1f ms: conduction at write+%.1f ms, FC cut at write+%.1f ms: source-less %.2f ms, bus minimum %5.2f V"
              % (tdon * 1e3, cond * 1e3, (BLANK + 1.341e-3) * 1e3, gap * 1e3, vb))
    print("""
  Reading. The arm can stand at the BT_BUS write only if the re-entry rule re-armed it between the FC_CHARGE LOW
  write and the override (ino:14106-14125 requires FC_CHARGE LOW, a rail command and the total under 0.25 A, all
  true at a standstill exit) or if it was never disarmed. The override R_OV is in band, so it HOLDS an armed
  selection (ino:14127-14130). With t_D_ON <= 10.2 ms the blanking covers the conduction; above it the bus sags
  for a few ms with no fault (UV_BUS needs 20 ms). This is open item 32; no new defect, recorded for W2a.""")


# =============================================================================================================
# Section 3: the unpredicted onset with a predictor that RECOGNISES it (PI-4 UNKNOWN or purge_active): precedence
# =============================================================================================================
C_F, C_B, C_C, C_EO = 30e-6, 35e-6, 21e-6, 1e-6
R_C_BLEED = (78.7e3 + 10e3) * (100e3 + 10.5e3) / (78.7e3 + 10e3 + 100e3 + 10.5e3)
R_MB, R_MS, R_MD = 3300.0, 116.2e3, 15.0
V_LOCK, I_IDLE, V_MPPT = 11.0, 0.018, 13.82
RT_UVLO = 2.925
I_VESC, V_VESC_MIN = 0.075, 8.0
V0 = 15.9
V_UV, UV_LATCH, UV_LEAK, UV_CAP = 12.0, 20.0, 0.05, 5.0
V_EXIT = 13.0
V_GUARD = 13.5
PIN8_TH = 8.92
T_DON = 0.008
VBT = 16.0
V_BODY = 0.6
DT = 20e-6
T_END = 0.160


def run_u(mode, p_in, c_mod, aux, c_v, t_fall, ef_corner, variant, t_det, order, t_loop, slope=0.81e3, t_don=T_DON):
    """calc/purge_collapse_sim.py run() with policy E2 as written in revision 9 PLUS the PI-4 path: at t_det after
    the onset the predictor reports UNKNOWN (or purge_active), which 'closes an open one as a prediction does'
    (design 9.11.2): the commanded exit of 9.7 (feed drop, drain, bond, confirmation, BT_BUS through the
    busHotPlugUnsafe guard, retried each iteration while refused).  E2 detector: (a) V_chg < 13.0 V with EF_EN H,
    (b) V_bus < 12.0 V, evaluated while the session holds BT_BUS open, i.e. until the BT_BUS write (SC-1).
    order 'exit-first': the prediction block runs before SC-1 in chgModeTick(); 'det-first' the reverse."""
    C_M = c_mod + C_EO
    cap = {'F': C_F, 'B': C_B, 'C': C_C, 'M': C_M, 'V': c_v}
    v = {k: V0 for k in cap}
    ef_off_v, ef_on_v = ef_corner
    i_trac = 0.28 if variant == 'D' else 0.0
    i0 = p_in / V0 + aux + I_VESC + i_trac + V0 / R_C_BLEED + V0 / R_MB + V0 / R_MS
    en = {'FCBUS': True, 'FCCHG': True, 'MOT': True, 'BTBUS': False, 'FCREG': True, 'BTREG': True}
    uvl = {'FCBUS': False, 'FCCHG': False, 'MOT': False}
    ef_en, ef_on, locked, p33 = True, True, False, True
    ev = {}
    dwell = 0.0
    last_it, next_it = 0.0, t_loop
    exit_state, pin8_low_n, drain_t0, confirm_n = None, 0, None, 0
    bt_en_t, s99, latch_t = None, None, None
    session = True
    bt_peak_i = 0.0
    vb_at_write = None
    snap = {}
    for k in range(int(T_END / DT)):
        t = k * DT
        i_fc = i0 * max(0.0, 1.0 - t / t_fall) if t_fall > 0 else 0.0
        di = {'F': i_fc, 'B': -aux if v['B'] > 0.5 else 0.0, 'C': -v['C'] / R_C_BLEED, 'M': 0.0, 'V': 0.0}
        im = v['M'] / R_MB + v['M'] / R_MS
        if not ef_en:
            im += v['M'] / R_MD
        if not locked and v['M'] < V_LOCK:
            locked = True
        if not locked:
            im += (p_in / v['M']) if (mode == 'CP' or v['M'] > V_MPPT) else I_IDLE
        else:
            im += I_IDLE if v['M'] > 1.0 else 0.0
        di['M'] -= im
        if v['V'] > V_VESC_MIN:
            di['V'] -= I_VESC + i_trac
        for kk in cap:
            v[kk] = max(0.0, v[kk] + di[kk] * DT / cap[kk])
        for sw, vin in (('FCBUS', 'F'), ('FCCHG', 'B'), ('MOT', 'B')):
            if en[sw] and not uvl[sw] and v[vin] < RT_UVLO:
                uvl[sw] = True
        if ef_on and (not ef_en or v['C'] < ef_off_v):
            ef_on = False
        elif (not ef_on) and ef_en and v['C'] >= ef_on_v:
            ef_on = True
        links = []
        if en['FCBUS'] and not uvl['FCBUS']:
            links.append(('F', 'B'))
        if en['FCCHG'] and not uvl['FCCHG']:
            links.append(('B', 'C'))
        if en['MOT'] and not uvl['MOT']:
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
            if en['BTBUS'] and bt_en_t is not None and t >= bt_en_t + t_don:
                vr = min(VBT, slope * (t - bt_en_t - t_don))
                gb = find('B')
                if v['B'] < vr - 1e-9:
                    cs = sum(cap[x] for x in groups[gb])
                    bt_peak_i = max(bt_peak_i, cs * (vr - v['B']) / DT)
                    ev.setdefault('t_bt_conduct', t)
                    for x in groups[gb]:
                        v[x] = vr
                    changed = True
            if not changed:
                break
        for tr in (0.080, 0.100):
            if tr not in snap and t >= tr:
                snap[tr] = (en['FCBUS'] and en['FCREG'] and not uvl['FCBUS'], v['B'], v['V'],
                            en['MOT'] and not uvl['MOT'])
        if t < next_it:
            continue
        dt_ms = (t - last_it) * 1e3
        last_it, next_it = t, t + t_loop
        vbus, vchg, pin8_high = v['B'], v['C'], v['M'] >= PIN8_TH
        if s99 is not None:
            if p33:
                pin8_low_n = pin8_low_n + 1 if not pin8_high else 0
                if pin8_low_n >= 2 or t - s99 >= max(0.010, 4 * t_loop):
                    p33 = False
            if t - s99 >= 0.010:
                en['MOT'] = False
            if t - s99 >= 0.020:
                en['FCREG'] = en['BTREG'] = False
            continue
        if latch_t is not None:
            s99 = t
            en['FCBUS'] = en['BTBUS'] = en['FCCHG'] = False
            ef_en = False
            pin8_low_n = 0
            continue
        # UV_BUS (armed on a matched pair)
        if (en['FCBUS'] and en['FCREG']) or (en['BTBUS'] and en['BTREG']):
            d = min(dt_ms, UV_CAP)
            if vbus < V_UV:
                dwell += d
                if dwell >= UV_LATCH:
                    latch_t = t
                    ev['latch_by'] = 'UV_BUS'
                    ev['t_latch'] = t
            else:
                dwell = max(0.0, dwell - UV_LEAK * d)

        def det():
            if session and ((ef_en and vchg < V_EXIT) or vbus < V_UV):
                ev['latch_by'] = 'E2'
                ev['t_latch'] = t
                return True
            return False

        def pred():
            nonlocal exit_state, ef_en, drain_t0, pin8_low_n
            if exit_state is None and t >= t_det:
                ev['t_exit'] = t
                exit_state = 'drain'
                en['FCCHG'] = False
                ef_en = False
                drain_t0 = t
                pin8_low_n = 0
                return True
            return False
        if order == 'det-first':
            if det():
                latch_t = t
                continue
            if pred():
                continue
        else:
            if pred():
                if det():           # same iteration: the feed drop already took EF_EN low
                    latch_t = t
                continue
            if det():
                latch_t = t
                continue
        if exit_state == 'drain':
            pin8_low_n = pin8_low_n + 1 if not pin8_high else 0
            if pin8_low_n >= 2 or t - drain_t0 >= min(0.030, max(0.010, 4 * t_loop)):
                p33 = False
                exit_state, confirm_n = 'confirm', 0
        elif exit_state == 'confirm':
            confirm_n += 1
            if confirm_n >= 2:
                exit_state = 'write'
        elif exit_state == 'write':
            if vbus >= V_GUARD:                          # busHotPlugUnsafe(BT_REG_ENABLE) false
                en['BTBUS'] = True
                bt_en_t = t
                vb_at_write = vbus
                ev['t_bt_write'] = t
                exit_state = 'done'
                session = False                          # SC-1 coverage ends at the BT_BUS re-close write
            else:
                ev['guard_refusals'] = ev.get('guard_refusals', 0) + 1
    ev['snap'] = snap
    ev['bt_peak_i'] = bt_peak_i
    ev['vb_at_write'] = vb_at_write
    return ev


def classify(s):
    fc_closed, vb, vv, mot = s
    if not fc_closed:
        return 'OPEN'
    if vb >= 15.5:
        return 'BENIGN'
    if vb >= 12.0:
        return 'IN-FAMILY'
    return 'HAZARD'


def section3():
    hdr("Section 3: unpredicted onset inside an FC window, predictor reports UNKNOWN / purge_active at t_det (PI-4)")
    print("  Design 9.11.2: UNKNOWN (PI-4: 'after an onset that it did not predict') 'closes an open one as a prediction")
    print("  does', i.e. runs the commanded exit with the BT_BUS re-close; SC-1 (E2) latches with no re-close. The design")
    print("  states no precedence and no bound on the recognition latency t_det. Exit-first: the feed drop takes EF_EN")
    print("  low, so SC-1 reading (a) is disarmed and only reading (b) V_bus < 12 V remains, until the BT_BUS write.")
    modes = (('CP', 13.0), ('CP', 14.8), ('MPPT', 14.8))
    res = {}
    n = 0
    for (mode, p), aux, cv, tf, var, tdet, order in itertools.product(
            modes, (0.0005, 0.015, 0.15), (0.48e-3, 1.5e-3, 5e-3), (0.0, 0.020, 0.040, 0.060, 0.075), ('P', 'D'),
            (0.0, 0.002, 0.010, 0.020, 0.030, 0.040, 0.050, 0.060, 0.070), ('exit-first', 'det-first')):
        e = run_u(mode, p, 221e-6, aux, cv, tf, (12.10, 12.88), var, tdet, order, 1.341e-3)
        n += 1
        for tr in (0.080, 0.100):
            c = classify(e['snap'][tr])
            key = (order, tr)
            res.setdefault(key, {}).setdefault(c, []).append((mode, p, aux, cv, tf, var, tdet, e))
    print("  %d cases per order (3 load modes x 3 aux x 3 C_V x 5 T_fall x 2 variants x 9 t_det), p99 loop, C_mod 221 uF"
          % (n // 2))
    for key in sorted(res):
        d = res[key]
        s = ', '.join('%s %d' % (c, len(d[c])) for c in ('OPEN', 'BENIGN', 'IN-FAMILY', 'HAZARD') if c in d)
        print("  [%s, t_rec %3.0f ms] %s" % (key[0], key[1] * 1e3, s))
        for c in ('IN-FAMILY', 'HAZARD'):
            if c in d:
                lo = min(d[c], key=lambda r: r[7]['snap'][key[1]][1])
                e = lo[7]
                tdets = sorted(set(round(r[6] * 1e3) for r in d[c]))
                tfs = sorted(set(round(r[4] * 1e3) for r in d[c]))
                print("     %s: t_det %s ms, T_fall %s ms; lowest bus %.2f V (V-MOT %.2f V, D-MT-EN joined %s);"
                      " case %s %.1f W aux %.1f mA C_V %.2f mF T_fall %.0f ms var %s t_det %.0f ms: exit %.1f ms,"
                      " BT_BUS write %s ms at V_bus %s V, BT conducts %s ms, latch %s ms [%s], BT peak %.2f A"
                      % (c, tdets, tfs, e['snap'][key[1]][1], e['snap'][key[1]][2], e['snap'][key[1]][3],
                         lo[0], lo[1], lo[2] * 1e3, lo[3] * 1e3, lo[4] * 1e3, lo[5], lo[6] * 1e3,
                         e.get('t_exit', float('nan')) * 1e3,
                         '%.1f' % (e['t_bt_write'] * 1e3) if 't_bt_write' in e else '-',
                         '%.2f' % e['vb_at_write'] if e['vb_at_write'] is not None else '-',
                         '%.1f' % (e['t_bt_conduct'] * 1e3) if 't_bt_conduct' in e else '-',
                         '%.1f' % (e['t_latch'] * 1e3) if 't_latch' in e else '-', e.get('latch_by', 'none'),
                         e['bt_peak_i']))
    # D4: BT_BUS turn-on stress reintroduced
    peaks = [(r[7]['bt_peak_i'], r) for key in res if key[0] == 'exit-first' and key[1] == 0.080
             for c in res[key] for r in res[key][c] if 't_bt_write' in r[7]]
    nwrite = len(peaks)
    big = [x for x in peaks if x[0] > 2.5]
    # per-t_det breakdown (exit-first, t_rec 80 ms) and the E2-only baseline (no predictor exit, t_det = never)
    print("  exit-first, t_rec 80 ms, by t_det: [HAZARD / IN-FAMILY / BT_BUS written after onset / BT peak > 2.5 A /"
          " exit stuck at the 13.5 V guard with no latch at 80 ms]")
    allr = [r for key in res if key == ('exit-first', 0.080) for c in res[key] for r in res[key][c]]
    for td in sorted(set(r[6] for r in allr)):
        sub = [r for r in allr if r[6] == td]
        hz = sum(1 for r in sub if classify(r[7]['snap'][0.080]) == 'HAZARD')
        inf = sum(1 for r in sub if classify(r[7]['snap'][0.080]) == 'IN-FAMILY')
        wr = sum(1 for r in sub if 't_bt_write' in r[7])
        pk = sum(1 for r in sub if r[7]['bt_peak_i'] > 2.5)
        stuck = sum(1 for r in sub if r[7].get('guard_refusals', 0) > 0 and 't_bt_write' not in r[7]
                    and (r[7].get('t_latch') is None or r[7]['t_latch'] > 0.080))
        print("     t_det %4.0f ms: %3d / %3d / %3d / %3d / %3d   of %d" % (td * 1e3, hz, inf, wr, pk, stuck, len(sub)))
    base = {}
    for (mode, p), aux, cv, tf, var in itertools.product(modes, (0.0005, 0.015, 0.15), (0.48e-3, 1.5e-3, 5e-3),
                                                         (0.0, 0.020, 0.040, 0.060, 0.075), ('P', 'D')):
        e = run_u(mode, p, 221e-6, aux, cv, tf, (12.10, 12.88), var, 1.0, 'det-first', 1.341e-3)
        for tr in (0.080, 0.100):
            base.setdefault(tr, {}).setdefault(classify(e['snap'][tr]), 0)
            base[tr][classify(e['snap'][tr])] += 1
    for tr in sorted(base):
        print("  baseline E2 only (no predictor exit), t_rec %3.0f ms: %s" % (tr * 1e3, base[tr]))
    print("  exit-first: BT_BUS re-close written after the onset in %d of %d cases; bus-side peak above the RT1987 2.5 A"
          " start limit (DS-00 s17.5) in %d" % (nwrite, n // 2, len(big)))
    if big:
        pk, r = max(big, key=lambda x: x[0])
        print("     largest %.2f A: %s %.1f W aux %.1f mA C_V %.2f mF T_fall %.0f ms var %s t_det %.0f ms"
              % (pk, r[0], r[1], r[2] * 1e3, r[3] * 1e3, r[4] * 1e3, r[5], r[6] * 1e3))
    print("""
  Reading. The baseline (SC-1 alone, no predictor exit) writes no BT_BUS after any onset and has no HAZARD case,
  as revision 9 claims. Adding the PI-4 rule 'UNKNOWN closes an open session as a prediction does' changes that in
  both orderings, because at the moment the predictor recognises the onset SC-1 has usually not tripped yet (V_chg
  is still above 13.0 V; with the ideal MPPT hold it stays there for tens of ms): the commanded exit drops the feed,
  which takes EF_EN low and disarms SC-1 reading (a); the bus, now carrying only its auxiliary load, stays above
  the 13.5 V guard, so the BT_BUS write is made and ends SC-1 coverage with FC_BUS and FC_REG HIGH. That is policy
  E1 re-entered through the predictor interface: D4 turn-on stress (peaks to 4.46 A against the 2.5 A RT1987
  start limit) at every recognition latency, the H-R HAZARD class (bus 10.95 V at the FC recovery with V-MOT
  joined, no latch) at 50-70 ms, and a guard-refusal stall (exit waiting at V_bus 12.0-13.5 V, reading (a)
  disarmed, reading (b) not yet tripped) that leaves FC_BUS HIGH at the recovery.""")


# =============================================================================================================
# Section 4: State-2 standstill window entry: the share latch acts on pins 27/28 during entry steps 1-4
# =============================================================================================================
def section4():
    hdr("Section 4: D-s entry steps 1-4: FC_BUS cut by the re-entry rule before the mode manager drops BT_BUS")
    print("  Ownership (12.4 item 7, SC-8) starts at entry step 5. Entry steps 1-4 (pin 10, pin 5, pin 33 with a")
    print("  4-iteration confirmation, the sense-path check) leave pins 27/28 to the share latch in State 2.")
    # Re-arm preconditions at the SHIFT BACK of 9.11.4 (deterministic, no EMS transition needed):
    #  (2) shareClosedLoopRun: the window's own charger load (0.91-1.08 A total, Table 8 + aux) closes the loop;
    #  (3)/(4) after the window close the filter decays to the aux level (alpha 0.05/tick, ino:3330):
    for i0, iaux in ((0.91, 0.09), (1.08, 0.15)):
        n = math.log((i0 - iaux) / (0.20 - iaux)) / -math.log(0.95)
        print("   filtered total %.2f A -> below the 0.20 A closed-loop exit in %.0f ticks (%.0f-%.0f ms); the window closes"
              " >= 290 ms before the onset and the shift back is >= 160 ms after it" % (i0, n, n * 1.131, n * 1.341))
    print("   inhibit: the in-band R_OV clears it with no cut latched (ino:14096-14105); fcUvLockoutActive() is TRUE on a")
    print("   purging H-20 (30 s > 10.34 s, ino:2256), so a 0.15 OR a 0.85 command re-arms BATTERY-only (ino:14119).")
    trace = [
        (0.0, "chgModeTick(): shift back releases R_OV, restores the stored EMS command (a rail, 0.15 or 0.85); 'no share"
              " override standing' is now true and every other 9.7 entry condition holds (Table 22 D-s: the shift"
              " back is the binding gate); F1 conduction gate passes (FC_BUS HIGH, unblanked); entry step 1 (pin 10 HIGH)"),
        (0.0, "powerBalance() (same or next iteration): not armed, shareClosedLoopRun, open-loop, !inhibit, FC_CHARGE LOW,"
              " total <= 0.25 A, rail command: RE-ARM battery-only (ino:14106-14125); updateShareSetpointCutoff():"
              " sp_eff 0.0, FC_BUS and BT_BUS HIGH, BT unblanked (written >= 450 ms earlier), |I_fc| <= 0.5 A:"
              " FC_BUS LOW, shareSpCutFC (ino:13398-13410). The bus is held by BT alone."),
        (1.3, "entry step 2: pin 5 released"),
        (2.6, "entry step 3: pin 33 HIGH; confirmation 2-4 iterations"),
        (6.5, "entry step 4: sense-path check passes (one iteration)"),
        (7.9, "entry step 5: the mode manager drops BT_BUS (writeBusSwitch is unconditional, ino:4920-4932); BT_CURRENT"
              " < 0.2 A on the next read (aux only): the bus is SOURCE-LESS (FC_BUS LOW by the latch, BT_BUS LOW)"),
        (9.2, "entry step 6: assertFcChargeEnable(true): the S2 restore writes FC_BUS HIGH unguarded (ino:12745-12749)"
              " and FC_CHARGE HIGH; D-FC-EN conducts only after t_D_ON 8 ms plus its soft-start"),
    ]
    for t, s in trace:
        print("   t = %5.1f ms  %s" % (t, s))
    for rate, lab in ((2.57, "HIL I_AUX 0.09 A on 35 uF"), (4.3, "0.15 A aux on 35 uF (pc s1)"),
                      (0.231, "pc s1 upper aux decay with F joined")):
        t12 = (15.9 - 12.0) / rate
        print("   bus from 15.9 V to 12.0 V at %.3f V/ms (%s): %.1f ms after step 5 -> ERR_FC_ONLY_COLLAPSE (b) latches"
              " State 99 on a healthy board" % (rate, lab, t12))
    print("""
  Reading. Section 9.7 checks the F1 conduction gate as an entry CONDITION (before step 1), SC-8 starts at step 5,
  and 9.11.4 lets the entry follow the shift back 'whatever share the loop holds', so nothing re-checks that FC_BUS
  conducts when BT_BUS is dropped. In State 1/98 no share loop runs (variant P is immune). In State 2 the latch,
  the re-entry rule and the load guard keep their writes on pins 27/28 through steps 1-4 (2.6-30 ms), and the
  shift back to a rail command re-arms the selector deterministically (the 12.11 host test 'R_OV never arms the
  selector' does not cover the shift back). Whether the cut lands inside steps 1-4 or before the admission depends
  on the unspecified call order of chgModeTick() and doState2(); an in-band to rail EMS change during steps 1-4
  gives the same trace without the shift back. The outcome is a State-99 latch with a perfect predictor (invariant f),
  and an unguarded FC_BUS write by the S2 restore onto a sagging bus. Fix: extend SC-8 ownership to the whole
  CHG_ENTERING state (from the pin-10 write), and re-test FC_BUS HIGH, unblanked and no shareSpCut*/shareIso*
  latched immediately before step 5 (refuse with code 11 otherwise).""")


# =============================================================================================================
# Section 5: healthy board across a predicted purge train: fault integrators (invariant f)
# =============================================================================================================
def section5():
    hdr("Section 5: healthy board, ideal predictor, 120 s purge train: UV_FC, UV_BUS, ERR_VCHG_FED, [RER], E2")
    period = 10.34
    for state, tlead, dead in (("P", 0.060, 0.569), ("D-s", 0.290, 0.785)):
        for dur in (0.100, 0.140, 0.180):
            t, dt = 0.0, 1.341e-3
            fc_dw, fc_peak = 0.0, 0.0
            trans = []
            t_on = None
            while t < 120.0:
                ph = t % period
                vfc = 1.0 if ph < dur else 13.0
                if vfc < 4.5:
                    fc_dw += min(dt * 1e3, 5.0)
                else:
                    fc_dw = max(0.0, fc_dw - 0.05 * min(dt * 1e3, 5.0))
                fc_peak = max(fc_peak, fc_dw)
                # window open from onset+dead-lead .. next onset - lead
                if ph >= dead - tlead and ph < period - tlead:
                    if t_on is None:
                        t_on = t
                        trans.append(t)
                else:
                    if t_on is not None:
                        trans.append(t)
                        t_on = None
                t += dt
            per_min = max(sum(1 for x in trans if x >= s and x < s + 60.0) for s in [i * 0.5 for i in range(120)])
            print("  %-3s purge %3.0f ms: UV_FC dwell peak %6.1f ms of 1000 (FC_BUS HIGH throughout, bonded);"
                  " window transitions max %d per 60 s (limit 20)" % (state, dur * 1e3, fc_peak, per_min))
    for tau in (0.984, 2.0, 2.69, 3.0):
        v1 = 15.95 * math.exp(-1.0 / tau)
        print("  ERR_VCHG_FED after a predicted exit: tau %.3f s -> V_chg %.2f V at the end of the 1.0 s blanking (latch if"
              " >= 11 V): %s" % (tau, v1, "LATCH" if v1 >= 11.0 else "no latch"))
    print("  break-even tau for the 1.0 s blanking: %.2f s (2.7 x the design tau, TODO(calibrate) at C-2b)"
          % (1.0 / math.log(15.95 / 11.0)))
    print("""
  Reading. With the ideal predictor no onset falls inside a session, so SC-1 never sees a purge; UV_BUS stays armed
  on a bus that BT holds; UV_FC accumulates at most one purge per period and leaks it in under 4 s; the window
  rate is 11.6 per minute. No healthy-board latch is found on the predicted train itself. The healthy-board latch
  of section 4 (State 2 entry) and the policy conflict of section 3 are the revision-9 sequencing defects.""")


# =============================================================================================================
# Section 6: (c) safe defaults and (e) next power-up, unchanged network
# =============================================================================================================
def section6():
    hdr("Section 6: (c) Teensy unpowered / reset and (e) the next power-up")
    pins = ["p33", "p28", "p29", "p30", "p31", "p32"]
    envkeys = ["v5", "bus", "vmot_above", "uc1", "clr", "resid", "node_resid", "ff1_prev"]
    bad = n = 0
    for gv in itertools.product(bt5.bt4.LV, repeat=len(pins)):
        g = dict(zip(pins, gv))
        g.update(p5="Z", p8="Z", p20="Z", p34="S")
        for ev in itertools.product((False, True), repeat=len(envkeys)):
            env = dict(zip(envkeys, ev))
            env["teensy"] = False
            for stage in (1, 2):
                s = bt5.hw5(g, env, None, stage)
                n += 1
                if not s["sgnd"] or (s["efuse"] and not env["resid"]):
                    bad += 1
    print("  Teensy unpowered/reset, every pin level and env bit: %d states, S_GND off or eFuse on without residual: %d"
          % (n, bad))
    print("""
  Reading. (c) holds: revision 9 adds no hardware. (e) next power-up: no window state is stored, setup() drives
  every path switch LOW (ino:6709-6715), the bring-up connects V-MOT only from a regulated bus; nothing re-closes
  onto a collapsed node at power-up. On the FC recovery after an E2 latch, FC_BUS is LOW in phase 0 (Table 23);
  the exception is the exit-first ordering of section 3, where FC_BUS and FC_REG stay HIGH.""")


if __name__ == "__main__":
    section1()
    section2()
    section3()
    section4()
    section5()
    section6()
