"""Battle-test round 5, transient lens, against detailed_design_IC1.md revision 7 (DD).

Stdlib only. Run: python bt5_transient_sim.py > bt5_transient_sim_output.txt
Reuses the inputs and conventions of bt4_transient_sim.py and ic1_rev7_calcs.py (calc7). Every input cites a
primary or a DD section; values with no primary are tagged ASSUMED.

Sections
 1. VESC-stop pulse train (facts_prior section 6: 15.9 -> 21.35 V in 19-47 ms, then a linear 14-20 V/s decay, next
    pulse 0.523-0.562 s later): VOK on/off intervals, VCHG-IN residual after each VOK release (bleed tau 0.984 s),
    and the exposure of the revision-7 exit hold check (ERR_MOD_SENSE (c), DD 9.5 exit step 1, Table 16) to an exit
    taken while EF_EN is already LOW (module node dumped, pin 8 LOW) and V_chg still reads >= 13.5 V.
 2. Exit hold check, healthy margin: time for the module node to fall from V0 to the U_MS edge after the feed drop,
    as a function of the (unbounded below) Ag105 input capacitance, against the 150 us sample.
 3. ERR_MOD_DUMP_ON sample time (10 ms after chargerHasPower() first turns true) measured from the eFuse enable,
    against the module-start interval that Stage 2 needs (DD Table 8a) and the FC-window module input current.
 4. Stuck-on dump at an eFuse start: I_out = V/R_MD + C x slew at the end of the ramp, against U_IM and I_OL (row
    F50 "Not U_IM"; gate C-2b (f) GO "ERR_MOD_DUMP_ON at the EF_EN rise").
 5. Pack-negative open (row F34b) with both boosts at 16.5 A: pin-side clamp currents including the CBL2 transient.
 6. Dump repetitive duty on the measured pulse train (release at the VOK release level, not at 21.5 V).
"""
import math

def hdr(n, t):
    print(f"\n[{n}] {t}")

# --------------------------------------------------------------------------- common inputs
R_MD = 15.0                       # DD 5.3 item 1, Table 7
R_MB = 3300.0                     # DD 5.3 item 2
R_MS = 116.2e3                    # R_MS1 + R_MS2, DD Figure 6
C_EO = 1e-6                       # DD Figure 6
C_MODS = (100e-6, 145e-6, 221e-6) # DD 5.3 / calc6 section 3 (Ag105 input C not given; S0-11)
UMS_EDGE = (8.67, 9.17)           # V, DD 5.3 item 3 with the CMRR term (calc7 section 7)
IQ_MAX = 18e-3                    # Ag105 DS p.20 row 4 (max only)
SLEW = (4.17e3, 5.79e3)           # V/s eFuse output, DD 7.5
EF_DELAY = 1.24e-3                # s eFuse turn-on delay, DD 7.5
UVLO_ON = (12.38, 12.88)          # V eFuse UVLO rising, DD 5.3
RAMP_RT = 12.0e3                  # V/s D-BC-RG / D-BC-FC soft start (DD 7.8)
TAU_VCHG = 0.984                  # s VCHG-IN bleed with the eFuse off (DD Table 11, calc5 section 5)
C_VCHG = 20e-6 + 1e-6             # C-D8 + C-D10 (facts_board 4.4) + C_EI
V_PULSE0 = 15.9                   # V, facts_prior section 6
V_STOP = 21.35                    # V VESC stop (mean measured peak), facts_prior section 6
T_RISE = (19e-3, 47e-3)           # s, 15.9 -> 21.2-21.47 V, facts_prior section 6
DECAY = (14.0, 20.0, 72.0)        # V/s linear decay with no regen current, facts_prior section 6; 72 = 20 + the IC1 node idle load 25 mA / 0.48 mF (board-only C_VMOT)
PERIOD = (0.523, 0.562)           # s second pulse spacing, facts_prior section 6
VOK_ASSERT = (16.90, 17.24)       # V, DD Table 9 / 7.8 (VBUS 16.0 V)
VOK_REL = (16.13, 16.43)          # V, DD Table 9 release corners (calc7 section 5 uses 16.13 / 16.43)
DWELL = 0.200                     # s regen release dwell, DD 9.5 exit conditions
LOOP = (1.131e-3, 1.341e-3)       # s median / p99 iteration, DD Table 11
GAP = 9.76e-3                     # s worst measured iteration
UIM = (1.508, 1.977)              # A, calc6 section 5
IOL = (2.055, 2.412)              # A at R_ILIM 8.06 kOhm, DD Table 7
V_FC_BUS = (15.9, 16.0, 17.5)     # V, DD 7.x / CLAUDE.md section 6 (V_BUS_NOMINAL 16.0, LIMIT 17.5)

# --------------------------------------------------------------------------- 1
hdr(1, "VESC-stop pulse train: VOK intervals, VCHG-IN residual, exposure of the exit hold check (ERR_MOD_SENSE (c))")
print("   Node tracking during the tail: with EF_EN H and the module idle, the module node + VCHG-IN load is at most")
for cm in C_MODS:
    c = cm + C_EO + C_VCHG
    i_load = IQ_MAX + V_STOP / R_MB + V_STOP / R_MS + V_STOP / (TAU_VCHG / 20e-6)
    print(f"     C_mod {cm*1e6:3.0f} uF: {i_load*1e3:4.1f} mA into {c*1e6:4.0f} uF = {i_load/c:5.0f} V/s own decay "
          f"vs the {DECAY[0]:.0f}-{DECAY[2]:.0f} V/s V-MOT tail -> D-BC-RG conducts; VCHG-IN follows V-MOT to the release level")
print("   (with I_q = 0 the own decay is lower still, but it stays above 14 V/s for C_mod <= 221 uF only if I_load/C > 14:")
for cm in C_MODS:
    c = cm + C_EO + C_VCHG
    i0 = V_STOP / R_MB + V_STOP / R_MS + V_STOP / (TAU_VCHG / 20e-6)
    print(f"     C_mod {cm*1e6:3.0f} uF, I_q 0: {i0/c:5.1f} V/s -> {'tracks' if i0/c > DECAY[1] else 'node lags V-MOT (VCHG-IN higher at release)'}")
print()
worst = []
for vr in VOK_REL:
    t13 = TAU_VCHG * math.log(vr / 13.5)
    worst.append(t13)
    print(f"   release at {vr:5.2f} V: V_chg >= 13.5 V for {t13*1e3:5.1f} ms after the VOK release (eFuse off, tau {TAU_VCHG} s)")
print()
print("   Cycle timing (onset t = 0, rise linear to 21.35 V, linear tail, release, next onset at the period):")
rows = []
for tr in T_RISE:
    for dk in DECAY:
        for per in PERIOD:
            for va, vr in ((VOK_ASSERT[0], VOK_REL[0]), (VOK_ASSERT[1], VOK_REL[1])):
                rise = (V_STOP - V_PULSE0) / tr
                t_as = (va - V_PULSE0) / rise
                t_rel = tr + (V_STOP - vr) / dk
                t_next = per + t_as
                off = t_next - t_rel
                t13 = TAU_VCHG * math.log(vr / 13.5)
                exposed = min(off, t13)
                frac_off = exposed / per
                # dwell exit: demand ends at phase p (uniform over the period); exit at p + 200 ms.
                # exposure: exit in [t_rel, t_rel + t13] modulo the period and EF_EN L at the exit.
                n = 20000
                hit = 0
                for k in range(n):
                    p = per * k / n
                    te = p + DWELL
                    # wrap into a cycle: assume pulses continue only while demand stands; the last pulse is the
                    # one whose onset precedes the demand end; exit relative to that onset:
                    ph = te % per if te < per + t_as else None
                    if p < t_as:
                        # demand ended before this pulse's VOK assert: no VOK pulse in this cycle; the previous
                        # release (t_rel - per) governs
                        dt_rel = te - (t_rel - per)
                        ef_l = True
                    else:
                        dt_rel = te - t_rel
                        ef_l = te >= t_rel
                    if ef_l and 0 <= dt_rel <= t13:
                        hit += 1
                rows.append((tr, dk, per, va, vr, t_as, t_rel, off, t13, frac_off, hit / n))
for r in rows:
    tr, dk, per, va, vr, t_as, t_rel, off, t13, frac_off, frac_dwell = r
    print(f"   rise {tr*1e3:2.0f} ms, tail {dk:2.0f} V/s, period {per*1e3:3.0f} ms, assert/release {va:5.2f}/{vr:5.2f} V: "
          f"VOK on {t_as*1e3:5.1f}-{t_rel*1e3:5.1f} ms, EF_EN L {off*1e3:5.1f} ms/cycle, of which V_chg>=13.5 V "
          f"{min(off,t13)*1e3:5.1f} ms -> random-phase exit exposed {frac_off*100:4.1f} %; dwell exit (demand end uniform) exposed {frac_dwell*100:4.1f} %")
fo = [r[9] for r in rows]
fd = [r[10] for r in rows]
print(f"   -> exposure per exit: random phase {min(fo)*100:.1f}-{max(fo)*100:.1f} %, dwell exit {min(fd)*100:.1f}-{max(fd)*100:.1f} %")
print("   An exit in the exposed span reads pin 8 LOW at 50 us (the node was dumped at the VOK release, before the")
print("   write) while 'pin 8 read HIGH in this window' and 'V_chg >= 13.5 V on the last settled reading' both hold:")
print("   ERR_MOD_SENSE (c) latches on a healthy board, voids the probe and refuses windows for the power cycle.")
print("   Second exposed span: after a re-assert, EF_EN H but the node cold for t_D_ON + ramp; V_chg >= 13.5 V only until")
print("   the eFuse UVLO drain (<= ~1.3 ms), so that span is small.")

# --------------------------------------------------------------------------- 2
hdr(2, "Exit hold check: healthy time for pin 8 to fall after the feed drop, vs C_node (Ag105 C_in has no lower bound)")
def t_fall(v0, c, i_mod, v_stop_mod, v_edge, dt=1e-7):
    """Node V with R_MD, R_MB, R_MS, module current i_mod while V > v_stop_mod, else I_q; returns time to v_edge."""
    v, t = v0, 0.0
    while v > v_edge:
        i = v / R_MD + v / R_MB + v / R_MS + (i_mod if v > v_stop_mod else 0.0)
        v -= i / c * dt
        t += dt
        if t > 0.1:
            return float("inf")
    return t
cases = [
    ("DD estimate: 13.5 V, 1.0 A held to the edge", 13.5, 1.0, 0.0),
    ("FC window: 15.9 V, 0.92 A until 13.82 V threshold (S0-5 behaviour)", 15.9, 0.92, 13.82),
    ("FC window, S0-5 NO-GO: 15.9 V, 0.92 A until the 11 V lockout", 15.9, 0.92, 11.0),
    ("FC window, S0-5 NO-GO, max input 1.32 A to 11 V", 15.9, 1.32, 11.0),
    ("Regen tail: 16.13 V, module below its 18 V threshold (I_q only)", 16.13, IQ_MAX, 99.0),
    ("Regen peak: 21.35 V, 1.458 A until 18 V", 21.35, 1.458, 18.0),
]
for label, v0, im, vs in cases:
    out = []
    cmin = None
    for c_uf in (10, 20, 30, 40, 50, 60, 80, 100, 145, 221):
        c = c_uf * 1e-6 + C_EO
        tf = t_fall(v0, c, im, vs, UMS_EDGE[1])
        out.append(f"{c_uf}uF:{tf*1e6:5.0f}us")
        if cmin is None and tf >= 150e-6:
            cmin = c_uf
    # exact c_min by bisection
    lo, hi = 1e-6, 400e-6
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        if t_fall(v0, mid + C_EO, im, vs, UMS_EDGE[1], dt=2e-8) >= 150e-6:
            hi = mid
        else:
            lo = mid
    print(f"   {label}: C_mod for >= 150 us: {hi*1e6:5.1f} uF")
    print("      " + "  ".join(out))
print("   S0-11 GO bounds C_mod only from above (<= 221 uF); gate C-2b (g) runs the exit hold check in a configuration")
print("   check (pin 32 LOW, module output only R_KA, so the module draws ~I_q) - the loaded FC-window case is untested.")

# --------------------------------------------------------------------------- 3
hdr(3, "ERR_MOD_DUMP_ON sample time from the eFuse enable vs the module start that Stage 2 needs")
print("   Timeline from the D-BC-FC output start (12 V/ms): UVLO at 12.38-12.88 V, V_chg 13.5 V crossing,")
print("   chargerHasPower() at the 2nd settled read >= 13.5 V (crossing + 1 iteration; + one 9.76 ms gap worst),")
print("   sample = + 10 ms (DD 12.6 Table 16).")
for uv in UVLO_ON:
    t_en = uv / RAMP_RT
    t_x = 13.5 / RAMP_RT
    for it in (LOOP[0], LOOP[1], GAP + LOOP[1]):
        t_chp = t_x + it
        t_s = t_chp + 10e-3
        print(f"   UVLO {uv:5.2f} V, chargerHasPower after {it*1e3:5.2f} ms: sample {(t_s - t_en)*1e3:5.2f} ms after eFuse enable; "
              f"eFuse ramp to 16 V ends {(EF_DELAY + 16.0/SLEW[0])*1e3:4.2f} ms after enable (slowest slew)")
print("   DD Table 8a 'allowance from eFuse enable to charge current': 5.3-6.4 ms (19 ms pulse), 26.4-29.3 ms (47 ms pulse)")
print("   at t_D_ON 8 ms. A module that meets the 19 ms family (S0-6 GO) is drawing charge current before the sample;")
print("   one that meets the 47 ms family with a start under ~11-21 ms is too.")
print("   FC-window module input current at the sample (pin 32 HIGH, FC profile 1.25 A, I_L 0.1-0.3 A, eta ASSUMED):")
for vb in (7.4, 8.0):
    for eta in (0.80, 0.88):
        for il in (0.1, 0.3):
            for frac in (0.63, 1.0):
                i_in = frac * (1.25 + il) * vb / eta / 15.9
                print(f"     V_batt {vb:3.1f} V, eta {eta:.2f}, I_L {il:.1f} A, {frac*100:3.0f} % of I_set: input {i_in:4.2f} A "
                      f"+ 23 mA healthy node -> step {i_in+0.023:4.2f} A vs 0.4 A threshold: {'FALSE LATCH' if i_in+0.023 > 0.4 else 'ok'}")
print("   Baseline confound (no module start): BT_CURRENT handed to FC after the < 0.2 A wait (<= 0.2 A) + 23 mA = 0.22 A;")
print("   margin to 0.4 A is 0.18 A against single-sample INA253 noise (floor +/-0.1 A, DD calc7 section 10).")
print("   Configuration check / commissioning (pin 32 LOW, output only R_KA ~14 mA): input ~ I_q whatever the start speed.")

# --------------------------------------------------------------------------- 4
hdr(4, "Stuck-on dump at an eFuse start: output current at the ramp end vs U_IM and I_OL")
def ramp_profile(v_in, c, s):
    """Return (peak current, time spent above each U_IM corner during the ramp) for a linear ramp to v_in."""
    t_r = v_in / s
    pk = v_in / R_MD + c * s + v_in / R_MB + IQ_MAX
    above = []
    for trip in UIM:
        # I(t) = s t / R_MD + c s + ... ; above trip for t > t_a until t_r, then V/R_MD steady
        i_c = c * s + IQ_MAX
        if pk <= trip:
            above.append(0.0)
        else:
            t_a = max(0.0, (trip - i_c) * R_MD / s)
            above.append(t_r - t_a)
    return pk, above
for v_in, lab in ((15.9, "FC bus 15.9 V"), (17.5, "FC bus 17.5 V"), (18.5, "regen VCHG-IN 18.5 V"), (21.35, "regen 21.35 V")):
    for cm in C_MODS:
        for s in SLEW:
            pk, ab = ramp_profile(v_in, cm + C_EO, s)
            verdict = []
            if pk > UIM[1]:
                verdict.append("above every U_IM unit")
            elif pk > UIM[0]:
                verdict.append("above the U_IM low corner")
            if pk > IOL[0]:
                verdict.append("> I_OL min: start into overload")
            steady = v_in / R_MD + v_in / R_MB + IQ_MAX
            print(f"   {lab}, C_mod {cm*1e6:3.0f} uF, slew {s/1e3:4.2f} V/ms: peak {pk:4.2f} A for "
                  f"{ab[0]*1e3:4.2f} ms above 1.51 A / {ab[1]*1e3:4.2f} ms above 1.98 A (U_IM tau 0.1 ms); steady {steady:4.2f} A "
                  f"{'; '.join(verdict) if verdict else '; below U_IM'}")
print("   Row F50 says 'Not U_IM: the eFuse input of 1.08-1.45 A lies below its 1.51 A minimum'; that is the steady term")
print("   only. At the ramp end the C x slew term adds 0.42-1.29 A, so U_IM (FF1 clear, ERR_CHG_TRIP, State 99 in")
print("   production) fires before the 10 ms ERR_MOD_DUMP_ON sample on most corners, and at the first VOK pulse of a")
print("   regen window. Gate C-2b (f) GO ('ERR_MOD_DUMP_ON at the EF_EN rise') then reads ERR_CHG_TRIP instead.")

# --------------------------------------------------------------------------- 5
hdr(5, "Pack-negative open (F34b) with both boosts at 16.5 A: pin-side clamp currents")
RB3, RB1A, CBL2 = 260.0, 4700.0, 100e-9      # facts_board 2.3 / line 72; DD R7-1
for vcell in (3.7, 4.2):
    for vf in (0.0, 0.25):
        i_ss = (vcell - vf) / RB3
        i_cb = (vcell - 0.6) / RB1A
        # transient: GND rises toward pack(+) as the boost input caps discharge at 16.5 A; CBL2 holds VC1-GND at
        # +V_cell1 until it discharges through RB3; the RB3 voltage is GND - pack(-) at most -> <= V_pack / RB3,
        # flowing into CBL2 (tau RB3*CBL2), not into the VC1 pin; D_VC1 conducts only after CBL2 has reversed.
        i_tr = 2 * vcell / RB3
        print(f"   V_cell {vcell} V, V_F {vf:.2f} V: D_VC1 steady {i_ss*1e3:4.1f} mA; RB3 transient into CBL2 <= {i_tr*1e3:4.1f} mA "
              f"(tau {RB3*CBL2*1e6:4.1f} us, not through D_VC1); VC1_CB <= {i_cb*1e3:4.2f} mA")
print("   The boost current (16.5 A) only sets the GND slew; RB3 and RB1A bound both pins. No contradiction found.")

# --------------------------------------------------------------------------- 6
hdr(6, "Dump duty on the measured pulse train")
for cm in C_MODS:
    c = cm + C_EO
    for vr in VOK_REL:
        e = 0.5 * c * vr ** 2
        print(f"   C_mod {cm*1e6:3.0f} uF, dump from the release level {vr:5.2f} V: {e*1e3:5.1f} mJ, I_pk {vr/R_MD:4.2f} A; "
              f"at one per {PERIOD[0]*1e3:.0f} ms {e/PERIOD[0]:5.3f} W")
print("   The VOK release falls on the 14-20 V/s tail, so a dump starts at 16.1-16.4 V, not 21.5 V: below the Table 7")
print("   51 mJ / 1.43 A design figures. A commanded exit inside the tail can still dump from up to 21.35 V.")
