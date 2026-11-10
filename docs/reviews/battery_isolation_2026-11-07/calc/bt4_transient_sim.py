"""Battle-test round 4, transient lens, against detailed_design_IC1.md revision 6 (DD).

Stdlib only. Run: python bt4_transient_sim.py > bt4_transient_sim_output.txt
Reuses the conventions of bt3_transient_sim.py and ic1_rev6_calcs.py (calc6). Every input cites a primary or a DD
section; values with no primary are tagged ASSUMED.

Sections
 1. Module-node dump: peak current, energy, R_MD pulse power; repetitive cadence (CC-18 535 ms vs the cold-start-
    limited cadence of a module-driven VOK limit cycle, DD 7.2 item 5 / row F23c).
 2. eFuse start inrush taken from V-MOT at a cold (dumped) module node: V-MOT sag against the VOK hysteresis.
 3. Release-reassert faster than the drain: is "every eFuse start is cold" (DD R6-3) guaranteed?
 4. eFuse-blocking probe with a real bypass: FC-bus current incl. the D-BC-FC soft-start into C_VCHG + C_mod, vs OC_FC.
 5. U_MS crossing vs the 10 ms cap: Stages 1-2 (dump) and Stage 3 (C_HU, Q_MD keyed to FF1./Q); Stage-3 hold-up
    across the 535 ms pulse spacing with the rev-6 bleed R_MB.
 6. F_VX (Littelfuse 451/453 4 A as a candidate): clearing time at the chafe currents, traction-onset pulse I2t.
 7. Pack-negative open (row F34b) with R_SH open: GND rise, INA240 IN+ against its -6 V absolute maximum.
 8. eFuse I_OL / U_IM against inrush + warm draw at R_ILIM 8.06 kOhm.
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
UMS = (8.69, 9.15)                # V, DD 5.3 item 3 (calc6 section 4)
V_LOCK = 11.0                     # Ag105 DS p.19 row 2 (typ only)
IQ_MAX = 18e-3                    # Ag105 DS p.20 row 4 (max only)
SLEW = (4.17e3, 5.79e3)           # V/s eFuse output, DD 7.5 (SLVSE94G 6.3, 6.5; C_DV 10 nF)
EF_DELAY = 1.24e-3                # s eFuse turn-on delay, DD 7.5
UVLO_ON = (12.38, 12.88)          # V eFuse UVLO rising, DD 5.3
T_D_ON = 8e-3                     # s RT1987 typ, no max (DD 7.8, Table 11)
RAMP_RT = 12.0e3                  # V/s D-BC-RG and D-BC-FC soft start, CSS 5.6 nF (DD 7.8, cc section 2, DD l.1763)
C_VCHG = 20e-6 + 1e-6             # C-D8 + C-D10 (facts_board 4.4) + C_EI (DD Fig. 6)
VOK_HYST = 0.74                   # V, DD Table 9 at VBUS 16 V: assert 16.90 - release 16.16 (min corner)
VOK_ASSERT = 16.90                # V, DD Table 9 VBUS 16.0 V, lowest corner
V_VESC_STOP = 21.35               # V, facts_prior section 6
SLOPES = (117.0, 280.0)           # V/s, facts_prior section 6: 15.9 -> 21.20-21.47 V in 19-47 ms
C_VMOT = (0.48e-3, 0.97e-3, 4.0e-3)   # F, facts_prior section 6 (board only .. ~4 mF weak estimate)
T_COLD = (65e-3, 170e-3)          # s, Ag105 cold start, facts_prior section 6
PERIOD_RG = 0.535                 # s, facts_prior section 6
I_AUX = 0.15                      # A, DD 5.3 (line 675)
OC_FC = 1.4                       # A single raw sample, DD 5.3 / ino
UIM = (1.508, 1.977)              # A, calc6 section 5 (3V3 3.2-3.4 V)
IOL_8K06 = (2.055, 2.412)         # A, calc6 section 5

# --------------------------------------------------------------------------- 1
hdr(1, "Module-node dump: per-dump numbers and repetitive cadence")
for cm in C_MODS:
    c = cm + C_EO
    for v0 in (18.0, 21.5):
        e = 0.5 * c * v0 ** 2
        tau = R_MD * c
        print(f"   C_mod {cm*1e6:4.0f} uF from {v0:4.1f} V: I_pk {v0/R_MD:4.2f} A, P_pk {v0**2/R_MD:5.1f} W, "
              f"tau {tau*1e3:4.2f} ms, E {e*1e3:5.1f} mJ, equivalent rectangular pulse {e/(v0**2/R_MD)*1e3:4.2f} ms at P_pk")
print("   Cadence. CC-18 used one dump per 535 ms (the VESC-trip pulse spacing). DD 7.2 item 5 and row F23c admit a")
print("   module-driven VOK limit cycle (the charger pulls V-MOT to the release level). Under rev 6 every release")
print("   dumps the node, so the next cycle needs a cold start; the shortest cycle is t_D_ON + eFuse delay + ramp +")
print("   cold start (+ the draw time to the release, taken as 0):")
for cm in C_MODS:
    c = cm + C_EO
    e = 0.5 * c * 21.5 ** 2
    for tc in T_COLD:
        per = T_D_ON + EF_DELAY + 21.5 / SLEW[0] + tc
        n30 = 30.0 / per
        print(f"   C_mod {cm*1e6:4.0f} uF, cold start {tc*1e3:4.0f} ms: period {per*1e3:5.1f} ms; mean R_MD "
              f"{e/per:5.3f} W; {n30:4.0f} dumps and {e*n30:5.2f} J per 30 s window "
              f"(CC-18: 0.095 W, 56 dumps, 2.86 J)")

# --------------------------------------------------------------------------- 2
hdr(2, "eFuse start from a dumped (0 V) module node: V-MOT sag against the VOK release")

def pulse(cvm, slope, cm, slew, uvlo):
    """Return (released, t_rel_ms, Vnode_at_release, Vmin_margin). Time 0 = VOK assert at VOK_ASSERT."""
    i_rg = cvm * slope                       # net regen current into the node without the charger
    dt = 2e-6
    t = 0.0
    vm, vi, vn = VOK_ASSERT, 0.0, 0.0        # V-MOT, VCHG-IN (assume bled to 0 between pulses: worst inrush), node
    ef_on_at = None
    release = VOK_ASSERT - VOK_HYST
    vmin_margin = 1e9
    while t < 60e-3:
        i_out = 0.0
        # D-BC-RG soft start after t_D_ON: VCHG-IN follows a 12 V/ms ramp until it meets V-MOT
        if t >= T_D_ON:
            target = min(vm, (t - T_D_ON) * RAMP_RT)
            if target > vi:
                dv = target - vi
                i_out += dv * C_VCHG / dt
                vi = target
            # eFuse: enabled at once (EF_EN H at assert); output ramps after UVLO + delay
            if ef_on_at is None and vi >= uvlo:
                ef_on_at = t + EF_DELAY
            if ef_on_at is not None and t >= ef_on_at and vn < vi:
                dvn = min(slew * dt, vi - vn)
                vn += dvn
                i_n = dvn * (cm + C_EO) / dt + vn / R_MB + vn / R_MS
                i_out += i_n
                vi_drop = 0.0
        # V-MOT: regen inflow until the VESC stops at V_VESC_STOP (then no inflow), charger draw out
        inflow = i_rg if vm < V_VESC_STOP else 0.0
        vm += (inflow - i_out) / cvm * dt
        if vi > vm:                             # VCHG-IN cannot exceed V-MOT (diode / ideal diode)
            vi = vm
            if vn > vi:
                vn = vi
        vmin_margin = min(vmin_margin, vm - release) if t > T_D_ON else vmin_margin
        if vm < release:
            return True, t * 1e3, vn, vm - release
        if vn >= vm - 0.05 and ef_on_at is not None:
            return False, t * 1e3, vn, vmin_margin
        t += dt
    return False, t * 1e3, vn, vmin_margin

for cvm in C_VMOT:
    for slope in SLOPES:
        for cm in (100e-6, 221e-6):
            rel, tms, vn, mg = pulse(cvm, slope, cm, SLEW[1], UVLO_ON[0])
            if rel:
                print(f"   C_VMOT {cvm*1e3:4.2f} mF, rise {slope:5.0f} V/s, C_mod {cm*1e6:3.0f} uF: VOK RELEASES at "
                      f"{tms:5.2f} ms with the module node at {vn:5.2f} V ({'below' if vn < V_LOCK else 'above'} 11 V)"
                      f" -> dump; the pulse never powers the module")
            else:
                print(f"   C_VMOT {cvm*1e3:4.2f} mF, rise {slope:5.0f} V/s, C_mod {cm*1e6:3.0f} uF: node charged at "
                      f"{tms:5.2f} ms, smallest V-MOT margin above release {mg:5.2f} V")
print("   DD 7.2 item 5 states that no cycle occurs if the Ag105 stops drawing above the release level. The eFuse")
print("   inrush into a node that rev 6 dumps to 0 V at every release is a draw that does not depend on the Ag105")
print("   threshold. Rev 5 kept the node at 0.02-2.3 s of hold-up (bt3 s2), so later pulses saw a part-charged node.")

# --------------------------------------------------------------------------- 3
hdr(3, "Release followed by re-assert before the dump makes the module cold")
for cm in C_MODS:
    c = cm + C_EO
    for v0 in (18.0, 21.5):
        t11 = R_MD * c * math.log(v0 / V_LOCK)
        t9 = R_MD * c * math.log(v0 / UMS[0])
        print(f"   C_mod {cm*1e6:4.0f} uF from {v0:4.1f} V: below 11 V after {t11*1e3:4.2f} ms, below U_MS low "
              f"edge after {t9*1e3:4.2f} ms")
for slope in SLOPES:
    print(f"   V-MOT rebound over the {VOK_HYST:.2f} V hysteresis at {slope:5.0f} V/s: {VOK_HYST/slope*1e3:5.2f} ms")
print("   EF_EN rises at the VOK assert (RGQ term) and turns Q_MD off within about 1 us (DD 5.3 item 1), so the dump")
print("   stops at the re-assert, before t_D_ON. At the measured rise rates the rebound (2.6-6.3 ms) exceeds the")
print("   21.5 V -> 11 V drain (1.0-2.2 ms): the claim holds for the recorded pulses. A faster V-MOT rebound (VESC")
print("   switching ripple, a step of regen current into 0.48 mF) is not bounded by any primary: the rebound rate that")
c = 221e-6 + C_EO
t11 = R_MD * c * math.log(21.5 / V_LOCK)
print(f"   defeats it is {VOK_HYST/t11:5.0f} V/s at 221 uF (= {VOK_HYST/t11*0.48e-3:4.2f} A net into 0.48 mF).")

# --------------------------------------------------------------------------- 4
hdr(4, "eFuse-blocking probe with a real bypass (eFuse IN-OUT shorted): FC-bus current")
for vbus in (15.9, 16.0, 17.5):
    vchg = vbus - 0.035                    # RT1987 forward regulation 35 mV (DD 7.2 item 1)
    i_steady = I_AUX + vchg / R_MD + vchg / R_MB + vchg / R_MS + IQ_MAX
    print(f"   V_bus {vbus:4.1f} V: steady FC current {i_steady:5.3f} A (aux 0.15 + R_MD + R_MB + U_MS + I_q 18 mA)"
          f" -> OC_FC 1.4 A margin {OC_FC - i_steady:+.3f} A")
for cm in C_MODS:
    c_tot = C_VCHG + C_EO + cm
    i_ramp = c_tot * RAMP_RT
    i_pk = I_AUX + i_ramp + 16.0 / R_MD
    print(f"   C_mod {cm*1e6:4.0f} uF: D-BC-FC soft start at 12 V/ms charges {c_tot*1e6:5.0f} uF through the bypass: "
          f"{i_ramp:4.2f} A; peak at the end of the ramp {i_pk:4.2f} A for {16.0/RAMP_RT*1e3:4.2f} ms "
          f"({'>' if i_pk > OC_FC else '<='} OC_FC 1.4 A)")
print("   DD 9.7a / calc6 s3 state 'about 1.07 A from the FC bus'; the soft-start charge of the module capacitance")
print("   through the bypass is omitted. Whether the INA253 FC sample sees the ramp depends on the bus capacitance")
print("   share (not given); at 17.5 V the steady figure alone leaves 0.06 A to OC_FC.")
print("   F35 variant (SHDN_EF stuck HIGH, eFuse itself on): output current = C*slew + V/R_MD:")
for cm in C_MODS:
    for slew in SLEW:
        i = (cm + C_EO) * slew + 16.0 / R_MD
        print(f"      C_mod {cm*1e6:4.0f} uF, slew {slew/1e3:4.2f} V/ms: {i:4.2f} A at 16 V "
              f"(I_OL {IOL_8K06[0]}-{IOL_8K06[1]} A: {'start-into-overload' if i > IOL_8K06[0] else 'below I_OL'})")

# --------------------------------------------------------------------------- 5
hdr(5, "U_MS crossing vs the 10 ms cap; Stage 3")
for cm in C_MODS:
    c = cm + C_EO
    t = R_MD * c * math.log(21.5 / UMS[0])
    print(f"   Stages 1-2, C_mod {cm*1e6:4.0f} uF: 21.5 V -> {UMS[0]} V in {t*1e3:4.2f} ms (cap 10 ms)")

def drain(c, v0, r, iq, vstop, tmax=10.0, dt=1e-4):
    t, v = 0.0, v0
    while v > vstop and t < tmax:
        v -= (v / r + (iq if v > V_LOCK else 0.0)) / c * dt
        t += dt
    return t

C_HU = 1.5e-3                       # DD 14.4 / Table 7
print("   Stage 3: Q_MD is keyed to FF1./Q (DD Fig. 6, 14.4), so during exit step 2 (pin 33 still HIGH, FF1 set) the")
print("   dump is OFF; only R_MB, R_MS and the module idle current discharge C_HU:")
for iq in (0.0, IQ_MAX):
    for v0 in (18.0, 21.5):
        t = drain(C_HU + 221e-6, v0, 1 / (1 / R_MB + 1 / R_MS), iq, UMS[0])
        print(f"      I_q {iq*1e3:4.1f} mA, from {v0:4.1f} V: pin 8 LOW after {t*1e3:7.0f} ms -> "
              f"{'ERR_MOD_DRAIN at 10 ms' if t > 0.010 else 'ok'}")
print("   Exit step 3 (pin 33 LOW, which would start the dump) is reached only after step 2, so every Stage-3 commanded")
print("   exit latches ERR_MOD_DRAIN (windows refused for the power cycle, row F49) and then re-bonds with C_HU charged.")
print("   Stage-3 hold-up across the 535 ms spacing, now with the rev-6 bleed R_MB || R_MS on the node:")
for cm in (100e-6, 221e-6):
    c = C_HU + cm + C_EO
    v, t = 18.0, 0.0
    while v > V_LOCK and t < 2.0:
        v -= (v / R_MB + v / R_MS + IQ_MAX) / c * 1e-4
        t += 1e-4
    need = None
    lo, hi = 1e-3, 5e-3
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        vv, tt = 18.0, 0.0
        while vv > V_LOCK and tt < PERIOD_RG:
            vv -= (vv / R_MB + vv / R_MS + IQ_MAX) / (mid + cm + C_EO) * 1e-4
            tt += 1e-4
        if vv > V_LOCK:
            hi = mid
        else:
            lo = mid
    print(f"      C_HU 1.5 mF + C_mod {cm*1e6:3.0f} uF from 18 V at I_q 18 mA: above 11 V for {t*1e3:5.0f} ms "
          f"(need 535 ms); C_HU needed {hi*1e3:4.2f} mF (DD 14.4: 1.38 mF without R_MB)")
print(f"   Stage-3 dump peak: 21.5 V / 10 Ohm = {21.5/10:4.2f} A against the Q_MD floor 'at least 2 A pulsed' (DD Table 7);"
      f" energy at 21.5 V {0.5*C_HU*21.5**2:4.2f} J per FF1 clear")

# --------------------------------------------------------------------------- 6
hdr(6, "F_VX: Littelfuse 451/453 4 A (very fast) as the candidate")
I2T = 3.152                         # A^2 s nominal melting, 451/453 datasheet rev GD 08/23/21 p.2 (calc. at 8 ms)
R_COLD = 0.0160                     # Ohm, same table
print(f"   cold resistance {R_COLD*1e3:.1f} mOhm (calc6 assumed 10-30 mOhm); melting I2t {I2T} A^2 s (8 ms basis);"
      f" breaking 300 A at 32 VDC")
for v, rloop in ((8.4, 0.0333), (7.4, 0.1883)):
    r = rloop + R_COLD
    i = v / r
    print(f"   chafe V_pack {v} V, calc6 loop {rloop*1e3:.1f} mOhm + F_VX: {i:6.1f} A; melt time ~I2t/I^2 = "
          f"{I2T/i**2*1e3:6.3f} ms (adiabatic approximation; the 8 ms-basis I2t overstates it at high current)")
for ipk, tp in ((12.0, 0.3e-3), (16.5, 0.3e-3), (17.0, 0.5e-3)):
    print(f"   reverse pulse {ipk:4.1f} A for {tp*1e3:3.1f} ms: {ipk**2*tp:5.3f} A^2 s = {ipk**2*tp/I2T*100:4.1f} % of melting I2t")
print("   200 % of rating (8 A) opens within 5 s maximum; 100 % carries 4 h minimum (datasheet p.1): a 4-8 A soft fault")
print("   through the Ag105 sense is not cleared within seconds.")

# --------------------------------------------------------------------------- 7
hdr(7, "Row F34b with R_SH open: INA240 IN+ (KS+, held at pack(-) by R_K1) against SBOS662C 7.1 (-6 V)")
RPAR = 72.3                         # RB3 || RB1A, calc6 s1
for vc1 in (3.7, 4.2):
    for ib in (0.0, 0.010, 0.030, 0.055):
        v_gnd = vc1 + 0.25 + ib * RPAR         # GND above pack(-): VMID + V_F + I*R (calc6 s1 geometry)
        v_gnd = min(v_gnd, 2 * vc1)
        print(f"   V_cell {vc1} V, board current via clamps {ib*1e3:4.0f} mA: GND {v_gnd:4.2f} V above pack(-) -> "
              f"KS+ at {-v_gnd:5.2f} V vs INA240 GND ({'EXCEEDS -6 V abs max' if v_gnd > 6.0 else 'within'})")
print("   Once IN+ passes the -6 V rating the INA240 input structure is a further board-return path in parallel with the")
print("   clamps (GND -> U_SH1 IN+ / U_SH2 IN- -> KS+ -> R_K1 2.2 Ohm -> pack(-)), which carries both cells and is limited")
print("   only by R_K1. With the boost VIN at its 2.0 V minimum (VBT - GND = 2 V, GND 6.4 V above pack(-)):")
for vgnd in (6.4, 7.0):
    i = (vgnd - 6.0) / 2.2
    print(f"      GND {vgnd} V: at least {i:4.2f} A through R_K1 if the input clamps at -6 V "
          f"({i**2*2.2:4.2f} W in a 0.25 W fusible; {6.0*i:4.2f} W in the INA240 input pair)")
print("   The input clamp voltage beyond -6 V is not specified; the bound above is the lower bound of the current.")

# --------------------------------------------------------------------------- 8
hdr(8, "eFuse I_OL and U_IM at R_ILIM 8.06 kOhm against start currents")
for cm in (100e-6, 104e-6, 221e-6):
    for warm in (0.0, 1.07, 1.24, 1.37):     # warm draw cases from bt3 s4 (calc5 s9)
        i = (cm + C_EO) * SLEW[1] + warm + 21.5 / R_MB
        tag = "U_IM TRIP" if i > UIM[0] else "ok"
        tag += ", > I_OL min" if i > IOL_8K06[0] else ""
        print(f"   C_mod {cm*1e6:4.0f} uF, warm draw {warm:4.2f} A: start current {i:4.2f} A -> {tag}")
print("   Cold starts (warm draw 0) stay below U_IM at every C_mod up to 221 uF; the rev-6 dump is what makes the")
print("   start cold. Section 3 bounds the exception.")
