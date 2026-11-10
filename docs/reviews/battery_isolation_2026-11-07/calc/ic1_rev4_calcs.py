"""IC1 detailed design, revision 4 (battle-test round 1 fixes): supporting calculations.

Stdlib only. Run:  python ic1_rev4_calcs.py   (output kept in ic1_rev4_calcs_output.txt)
Cited in detailed_design_IC1.md as "calc4 section N". Every input carries its source in a comment.
Values marked ASSUMED are working values with no primary; the design text tags them BENCH or UNCONFIRMED.
"""
import math


def hdr(n, title):
    print()
    print("=" * 78)
    print(f"Section {n}: {title}")
    print("=" * 78)


par = lambda a, b: a * b / (a + b)

# ---------------------------------------------------------------------------
# 1. Kelvin-lead fusible resistors R_K1/R_K2 (finding FM-1)
# ---------------------------------------------------------------------------
hdr(1, "Kelvin-lead series resistors: short bound and trip-budget terms")
V_PACK_MAX = 8.5                 # LIMIT_V_BATT_MAX (CLAUDE.md section 6)
R_INT = (0.010, 0.040)           # pack internal resistance, ASSUMED (verify_fm1_kelvin.py sweep)
for r in (1.0, 2.2, 4.7, 10.0):
    i_hi = V_PACK_MAX / (r + R_INT[0])
    print(f"   R_K = {r:4.1f} Ohm: KS lead shorted to pack+ -> I <= {i_hi:5.2f} A, P(R_K) = {i_hi**2*r:6.1f} W"
          f" (0.25 W part: {i_hi**2*r/0.25:5.0f} x rating)")
K_IN = 0.5e-3                    # R_SH 0.5 mOhm -> input-referred V/A
I_B = 90e-6                      # INA240 I_B typ, SBOS662C sec 7.5 (as tabulated in DD Table 7)
for r, tol in ((2.2, 0.01), (2.2, 0.05), (10.0, 0.01)):
    dr = 2 * r * tol             # worst mismatch of two resistors
    print(f"   R_K {r} Ohm, {tol*100:.0f} % parts: I_B x dR = {I_B*dr*1e6:5.1f} uV = {I_B*dr/K_IN:5.3f} A"
          f"; per 10 uA of I_B mismatch (TODO(verify: SBOS662C)) {10e-6*r/K_IN:5.3f} A")
r_chain = 0.050                  # charge-mode chain drop scale, ASSUMED R_s 50 mOhm
print(f"   KS+ bonded to PCB GND through R_K 2.2 Ohm: drop <= 1.75 A x {r_chain*1e3:.0f} mOhm = "
      f"{1.75*r_chain*1e3:.0f} mV -> {1.75*r_chain/2.2*1e3:.0f} mA in the bond (was up to 2.4 A unbounded by R_K)")

# ---------------------------------------------------------------------------
# 2. Trip budget, revision 4 (U_C2 polarity reversed; CMRR, 3V3 and R_K terms added)
# ---------------------------------------------------------------------------
hdr(2, "U_C1 / U_C2 thresholds and tolerance (rev 4)")
K = 100 * 0.5e-3                 # INA240A3 100 V/V x 0.5 mOhm = 50 mV/A (SBOS662C sec 7.5)
V3 = 3.3
TH1 = V3 * 10.0 / (12.0 + 10.0)  # R_T1a 12.0k / R_T1b 10.0k
TH2 = V3 * 10.0 / (12.1 + 10.0)  # R_T2a 12.1k / R_T2b 10.0k (rev 4: U_C2 on the reversed channel)
mid = V3 / 2                     # INA240 REF1 = 3V3, REF2 = GND -> VS/2
for nm, th in (("U_C1 discharge", TH1), ("U_C2 charge (reversed channel)", TH2)):
    i_nom = (mid - th) / K
    cmrr = th * 10 ** (-54 / 20)                 # TLV3011B CMRR 54 dB min, VOS spec at VCM = V- (SBOS300C 6.9)
    terms = {
        "TLV3011B V_OS 9 mV": 9e-3 / K,
        "TLV3011B CMRR at VCM": cmrr / K,
        "INA240 V_OS 25 uV": 25e-6 / K_IN,
        "INA240 ref divider 0.1 %": mid * 1e-3 / K,
        "threshold divider 0.1 % x 2": 2 * 1e-3 * th * (1 - th / V3) / K,
        "R_K 2.2 Ohm 1 % x I_B": I_B * 2 * 2.2 * 0.01 / K_IN,
    }
    lin = sum(terms.values())
    gain = i_nom * (0.002 + 0.01)                # INA240 gain 0.2 % + shunt 1 % (shunt TODO(verify))
    lo, hi = i_nom - lin - gain, i_nom + lin + gain
    # 3V3 tolerance: trip current proportional to 3V3 (threshold and midpoint both ratiometric)
    lo3, hi3 = lo * 3.2 / 3.3, hi * 3.4 / 3.3    # 3V3 = 3.2-3.4 V, ASSUMED (Teensy regulator TODO(verify: PJRC))
    print(f"   {nm}: TH {th:.4f} V, nominal {i_nom:.3f} A; terms " +
          ", ".join(f"{k} {v:.3f}" for k, v in terms.items()))
    print(f"      range at 3V3 = 3.30 V: {lo:.2f}..{hi:.2f} A; with 3V3 3.2-3.4 V: {lo3:.2f}..{hi3:.2f} A")

# ---------------------------------------------------------------------------
# 3. VOK bus-present comparator U_BPk (findings FM-2 / BT1-02)
# ---------------------------------------------------------------------------
hdr(3, "VOK channel: bus-present comparator and open-tap behaviour")
R_B1, R_B2, R_O = 99.8e3, 14.9e3, 301e3          # DD Fig. 4 / calc section 2
G = 1 / R_B1 + 1 / R_B2 + 1 / R_O
for vref in (1.223, 1.242, 1.260):               # TLV3011B REF, SBOS300C 6.9
    for vos in (-9e-3, 0, 9e-3):
        th = vref + vos
        vbus = (th * G - vref / R_O) * R_B1
        print(f"   U_BP threshold REF {vref:.3f} V, V_OS {vos*1e3:+.0f} mV -> bus present above VBUS {vbus:5.2f} V")
print(f"   bus tap open (top string open, pad lift, wire): BTk = {1.242*R_B2/(R_O+R_B2)*1e3:.1f} mV -> bus ABSENT -> channel blocks")
print("   R_Bk2 or C_Bk short: BTk = 0 V -> bus ABSENT -> channel blocks")
print(f"   BTk at VBUS 13.5 V (lowest window bus): {(13.5/R_B1+1.242/R_O)/G:.3f} V (> 1.269 V worst threshold)")
print(f"   BTk at VBUS 17.5 V: {(17.5/R_B1+1.242/R_O)/G:.3f} V ; V-MOT tap at 21.5 V (Q_H off): "
      f"{21.5*(13.6e3+715)/(99.8e3+13.6e3+715):.3f} V (TLV3011B at 3V3: input to V+ + 0.2 = 3.5 V)")
# symmetric-hysteresis release (finding BT1-T4): half of 8 mV moves release by 4 mV / tap ratio
tap = (13.6e3 + 715) / (99.8e3 + 13.6e3 + 715)
print(f"   centred 8 mV hysteresis lowers the release by up to {4e-3/tap*1e3:.0f} mV at V-MOT;"
      f" worst release margin at VBUS 17.5 V: 0.144 - {4e-3/tap:.3f} = {0.144-4e-3/tap:.3f} V")

# ---------------------------------------------------------------------------
# 4. Status ladders, revision 4 (findings FM-3, BT1-T1, BT1-03, BT1-BM-01)
# ---------------------------------------------------------------------------
hdr(4, "Status ladders: R = 2.00k, 2R = 4.02k, C = 10 nF")
R, C = 2.00e3, 10e-9
tau = R * C
LSB = 3.3 / 32
for nm, dv in (("1 LSB", LSB), ("2 bits (309 mV)", 3 * LSB), ("OK1+OK2 (1237 mV)", 12 * LSB), ("MSB (1650 mV)", 16 * LSB),
               ("full scale (3197 mV)", 31 * LSB)):
    print(f"   {nm:22s}: settle to 30 mV in {tau*math.log(dv/0.03)*1e6:6.1f} us; to 10 mV in {tau*math.log(dv/0.01)*1e6:6.1f} us")
print(f"   tau {tau*1e6:.0f} us (rev 3: 2000 us). Bit drive <= 3.3 V / ~6 k = {3.3/6e3*1e3:.2f} mA per bit;"
      f" 10 bits <= {10*3.3/6e3*1e3:.1f} mA from 3V3")
for cs in (5e-12, 20e-12):        # i.MX RT1062 ADC sample capacitance: TODO(verify: IMXRT1060 datasheet), ASSUMED
    print(f"   ADC sample capacitor {cs*1e12:.0f} pF (ASSUMED): kickback <= {3.3*cs/C*1e3:.1f} mV, recovered in"
          f" {tau*math.log(3.3*cs/C/0.001)*1e6 if 3.3*cs/C>0.001 else 0:.0f} us")
T_LOOP, T_P99 = 1.131e-3, 1.341e-3                # facts_firmware sec 8
for lbl, tl in (("median", T_LOOP), ("p99", T_P99)):
    # exit in iteration n; settled reading = two identical decodes on iterations n+1 and n+2
    print(f"   traction exit at {lbl} loop {tl*1e3:.3f} ms: confirm after 2 iterations = {2*tl*1e3:.2f} ms;"
          f" one extra iteration if the first read straddles an edge: {3*tl*1e3:.2f} ms")

# ---------------------------------------------------------------------------
# 5. Signal-side injection (finding FM-4)
# ---------------------------------------------------------------------------
hdr(5, "Signal-side injection R_I = 8.2k into SIG1 / SIG2 (R_F 1.5k)")
R_F, R_I = 1.5e3, 8.2e3
ratio = R_I / (R_F + R_I)
for ipack in (-0.5, 0.0, 0.5):       # bonded Idle pack current, discharge positive (ASSUMED range, validity gate)
    for nm, sign, th in (("U_C1", -1, TH1), ("U_C2", +1, TH2)):
        vout = mid + sign * K * ipack    # U_C1 channel: discharge lowers OUT; U_C2 reversed: discharge raises OUT
        sig = vout * ratio
        eq = (mid - sig) / K
        print(f"   I_pack {ipack:+.1f} A, {nm}: OUT {vout:.4f} V -> SIG_inj {sig:.4f} V = {eq:4.2f} A equivalent;"
              f" trips (SIG < TH {th:.3f} V): {sig < th}")
print(f"   validity: firmware requires SIG_inj (pin 16/17) <= {mid-K*3.8:.3f} V (3.8 A equivalent) and |I_PACK| <= 0.5 A")
print("   R_F open: SIG pulled to 0 V through R_I -> ADC reads ~0 V (expected ~1.40 V) -> detected")
print(f"   D5 injection: pin 35 -> R_I3 100k -> D_I3 -> U_D5 IN- (R_D5a 10k to BT-CURR): +{(3.3-0.3)/110e3*10e3*1e3:.0f} mV"
      f" = {(3.3-0.3)/110e3*10e3/0.1:.2f} A equivalent (INA253A1 0.1 V/A) against the 0.5 A threshold")

# ---------------------------------------------------------------------------
# 6. FF1 input network, revision 4 (FM-7, FM-13, BT1-04, BT1-T3, BT1-DS-01/02)
# ---------------------------------------------------------------------------
hdr(6, "Buffered pin-33 clear and set path")
II = 5e-6                                          # LVC1G17 I_I max, SCES351Y sec 5.5 (via DD Table 7)
print(f"   pin 33 high-Z: U_P33 input = I_I x R_P33 10k = {II*10e3*1e3:.0f} mV < VT- min 0.89 V -> P33B LOW")
for vf in (0.20, 0.32):
    print(f"   P33B LOW: N1 = VF(BAT54 at {(3.3-vf)/10e3*1e3:.2f} mA) <= {vf:.2f} V < U_CLS VT- min 0.89 V -> /CLR LOW")
for tau_ck in (9.4e-6, 10.6e-6):                   # 10k 1 % x 1 nF C0G 5 %
    for vt in (1.48, 2.00):                        # LVC1G17 VT+ 1.48-1.92 V at 3.0 V; 2.00 V taken as the 3.3 V bound (UNCONFIRMED)
        print(f"   CLK: tau {tau_ck*1e6:.1f} us, VT+ {vt:.2f} V -> U_CKS switches at {tau_ck*math.log(3.3/(3.3-vt))*1e6:.2f} us")
for cn in (70e-12, 130e-12):
    t = 10e3 * cn * math.log((3.3 - 0.3) / (3.3 - 2.0))
    print(f"   /CLR release: C_N1 {cn*1e12:.0f} pF, from 0.3 V to VT+ 2.0 V: {t*1e6:.2f} us")
print(f"   worst margin = {9.4e-6*math.log(3.3/1.82)*1e6:.2f} - {10e3*130e-12*math.log(3.0/1.3)*1e6:.2f} us"
      f" = {(9.4e-6*math.log(3.3/1.82)-10e3*130e-12*math.log(3.0/1.3))*1e6:.2f} us")

# ---------------------------------------------------------------------------
# 7. V_PACKN transfer function (BT1-BM-02)
# ---------------------------------------------------------------------------
hdr(7, "V_PACKN divider with R_VPS in the lower leg")
R_V1, R_V2, R_VPS = 100e3, 100e3, 10e3
a = (R_V2 + R_VPS) / (R_V1 + R_V2 + R_VPS) * 3.3
b = R_V1 / (R_V1 + R_V2 + R_VPS)
print(f"   V(pin 23) = {a:.4f} V + {b:.4f} x V_PACKN ; decode V_PACKN = {1/b:.3f} x V23 - {(R_V2+R_VPS)/R_V1:.3f} x 3V3")
print(f"   rev-3 decode (2 V23 - 3.3) error: offset {2*a-3.3:+.4f} V, gain {2*b-1:+.4f}")
lsb = 3.3 / 4095 / b
print(f"   1 ADC count = {lsb*1e3:.3f} mV of V_PACKN")
for i in (1, 3, 5, 7.2, 17.1):
    print(f"   5 mOhm at {i:4.1f} A = {5e-3*i*1e3:5.1f} mV = {5e-3*i/lsb:5.1f} counts")

# ---------------------------------------------------------------------------
# 8. FC-window guard G1, residual form (BT1-BM-04)
# ---------------------------------------------------------------------------
hdr(8, "FC-window bus current against G1")
ETA = 0.88                                         # Ag105 DS p.20 (12 V, 3S), unverified at 2S
for eta in (0.88, 0.80):
    for v in (7.4, 7.72, 8.0, 8.4):
        p = (1.25 + 0.3) * v / eta
        print(f"   eta {eta}: V_pack {v}: P_in {p:5.2f} W, bus {p/16:5.3f} A + aux 0.15 = {p/16+0.15:5.3f} A"
              f" (rev-3 G1 limit 1.0 A)")

# ---------------------------------------------------------------------------
# 9. eFuse UVLO re-set (BT1-DS-08)
# ---------------------------------------------------------------------------
hdr(9, "eFuse UVLO divider R_UV1 100k / R_UV2 10.5k")
k = (100e3 + 10.5e3) / 10.5e3
print(f"   rising {1.176*k:.2f}..{1.224*k:.2f} V; falling {1.09*k:.2f}..{1.15*k:.2f} V (SLVSE94G 6.5)")
print("   against Ag105 VIN min 11 V (DS p.19) and the FC-window bus floor 13.5 V")

# ---------------------------------------------------------------------------
# 10. D5 arming delay (BT1-T5)
# ---------------------------------------------------------------------------
hdr(10, "D5 arming delay, R_D5d 100k / C_D5d 100 nF from FCQ 3.27 V")
for vth in (0.8, 1.5):                             # BSS138 V_GS(th), BSS138/D p.2
    print(f"   Q_D5 V_th {vth} V: {-10e-3*math.log(1-vth/3.27)*1e3:.1f} ms")

# ---------------------------------------------------------------------------
# 11. Regen pulse capture budget for S0-6 (BT1-T2, BT1-RO-01)
# ---------------------------------------------------------------------------
hdr(11, "Hardware chain against the 19 ms and 47 ms pulses (linear V-MOT ramp, facts_prior sec 6)")
for t_pulse in (19.0, 47.0):
    slope = (21.35 - 15.9) / t_pulse
    for v_ass in (16.90, 17.24):
        t_vok = (v_ass - 15.9) / slope
        for tdon in (8.0, 12.0):                   # RT1987 t_D_ON 8 ms typ, no max (RT1987 DS-00 sec 13); 12 ms sensitivity
            t_uvlo = 12.88 / 12.0                  # D-BC-RG soft start 12 V/ms (CSS 5.6 nF) to the rev-4 UVLO max 12.88 V
            allow = t_pulse - (t_vok + tdon + t_uvlo)
            print(f"   pulse {t_pulse:.0f} ms, VOK {v_ass} V at {t_vok:4.2f} ms, t_D_ON {tdon:4.1f}: allowance for"
                  f" eFuse enable -> I_set = {allow:5.2f} ms (eFuse delay + ramp alone 4.4-5.6 ms)")

# ---------------------------------------------------------------------------
# 12. Miscellaneous
# ---------------------------------------------------------------------------
hdr(12, "Miscellaneous")
print(f"   regen window maximum input power at the 8.0 V entry gate, 2.5 A ceiling: {8.0*2.5/ETA:.2f} W (< 23 W)")
r1, r2 = 150e3, 82e3
for v in (6.0, 7.4, 8.5):
    vin = v * r2 / (r1 + r2)
    print(f"   BAL_OK divider 150k/82k at VBAL+ {v} V: {vin:.2f} V (LVC V_IH 2.0 V; I_I 5 uA x {par(r1,r2)/1e3:.0f}k ="
          f" {5e-6*par(r1,r2):.2f} V); drain {v/(r1+r2)*1e6:.0f} uA")
# gate supply split: two 2.2 uF in series per channel
print(f"   C_VTk = 2 x 2.2 uF in series = {par(2.2,2.2):.1f} uF per channel (one cracked part leaves 2.2 uF, not a short)")
# body-diode loss with both S_GND lost (unchanged figures, reference)
for i in (7.2, 17.1):
    print(f"   both S_GND off, I {i} A: body-diode loss {0.7*i:.1f}-{1.0*i:.1f} W total (V_SD 0.7-1.0 V)")
