"""Battle-test round 1 (FMEA lens) on detailed_design_IC1.md revision 3: supporting calculations.

Stdlib only. Run:  python fmea_round1_calcs.py
Design values are those of detailed_design_IC1.md rev 3 (cited "DD" with section/figure).
Datasheet values carry their primary in a comment.
"""
import math


def hdr(n, title):
    print()
    print("=" * 78)
    print(f"Section {n}: {title}")
    print("=" * 78)


# ---------------------------------------------------------------------------
# A. Clear net N1 and the FF1 clock when Teensy pin 33 is high-Z (reset, boot, brownout)
# ---------------------------------------------------------------------------
hdr("A", "N1 and CLK with pin 33 high-Z (DD Fig. 2)")
V33 = 3.3
R_N1 = 10e3        # DD Fig. 2: R_N1 10k to 3V3
R_P33 = 10e3       # DD Fig. 2: R_P33 10k pin 33 to GND
VF_LO, VF_HI = 0.20, 0.32   # BAT54 VF ~0.24 V max at 0.1 mA, 0.32 V max at 1 mA (BAT54LT1/D, via IC5 Table 2); bracket
VIL_MAX, VIH_MIN = 0.8, 2.0  # SN74LVC1G74 SCES794G sec 6.3, VCC 3.0-3.6 V
for vf in (VF_LO, VF_HI):
    i = (V33 - vf) / (R_N1 + R_P33)
    v_pin33 = i * R_P33
    v_n1 = V33 - i * R_N1
    print(f"   VF {vf:.2f} V: I {i*1e3:.3f} mA, pin-33 node (= CLK via 1k) {v_pin33:.3f} V, N1 (= /CLR) {v_n1:.3f} V")
print(f"   LVC74 VIL max {VIL_MAX} V, VIH min {VIH_MIN} V -> both nodes in the undefined band: "
      f"{VIL_MAX < (V33-VF_HI)/2 < VIH_MIN}")
# Required R_P33 for N1 <= 0.8 V - margin with R_N1 10k: N1 = vf + i*R_P33, i = (3.3 - vf)/(R_N1+R_P33)
for rp in (1e3, 2.2e3, 1e4):
    i = (V33 - VF_HI) / (R_N1 + rp)
    print(f"   R_P33 {rp/1e3:4.1f}k: N1 = {VF_HI + i*rp:.3f} V")
# Ratiometric: during the 3V3 ramp N1 ~ 0.54 x VCC, CLK ~ 0.45 x VCC (the LVC switching point region)
print("   During 3V3 ramp: N1/VCC ~ 0.55, CLK/VCC ~ 0.45 (both near VCC/2 for every VCC)")

# ---------------------------------------------------------------------------
# B. Status-ladder settling against the 1 ms / 2 ms confirmation windows
# ---------------------------------------------------------------------------
hdr("B", "R-2R ladder settling (DD Fig. 5, sec 7.7, 9.3, 9.5, 12.4)")
R_LAD = 20e3        # R-2R Thevenin output resistance = R (DD Fig. 5: R = 20.0k)
C_LAD = 100e-9      # C_LA / C_LB 100 nF at the pin (DD Fig. 5)
tau = R_LAD * C_LAD
STEP = 3.3 / 32     # 103 mV (DD sec 7.7)
TOL = 0.030         # decode window (DD sec 7.7: >30 mV from every calibrated code = undecodable)
print(f"   tau = {tau*1e3:.2f} ms; code step {STEP*1e3:.1f} mV; decode tolerance {TOL*1e3:.0f} mV")
for bit in range(5):
    dv = STEP * 2 ** bit
    t_settle = tau * math.log(dv / TOL) if dv > TOL else 0.0
    frac_1ms = 1 - math.exp(-1e-3 / tau)
    frac_2ms = 1 - math.exp(-2e-3 / tau)
    print(f"   bit {bit} step {dv*1e3:6.1f} mV: settle to 30 mV in {t_settle*1e3:5.2f} ms; "
          f"error at 1 ms {dv*(1-frac_1ms)*1e3:6.1f} mV, at 2 ms {dv*(1-frac_2ms)*1e3:6.1f} mV")
# Entry check (sec 9.5 step 4): FF1.Q bit0 (ladder A) rises, SG bits 0/1 (ladder B) fall within 2 ms
dvB = STEP * (1 + 2)   # both SG bits fall together on ladder B
print(f"   ladder B entry step (SG1+SG2) {dvB*1e3:.0f} mV: residual at 2 ms {dvB*math.exp(-2e-3/tau)*1e3:.0f} mV (> {TOL*1e3:.0f} mV -> wrong/undecodable)")
for c in (1e-9, 4.7e-9, 10e-9):
    t = R_LAD * c
    print(f"   C = {c*1e9:4.1f} nF: tau {t*1e6:6.1f} us, MSB settle {t*math.log(STEP*16/TOL)*1e6:6.1f} us")

# ---------------------------------------------------------------------------
# C. VOK channel with the VBUS tap open (wire, pad lift, R_Bk1a/b open), R_Bk2 or C_Bk shorted
# ---------------------------------------------------------------------------
hdr("C", "VOK bus-side open: fail direction (DD Fig. 4)")
R_M1, R_M2, R_M3 = 99.8e3, 13.6e3, 715.0      # DD Fig. 4; calc ic1_rev3 sec 2
R_B2, R_O = 14.9e3, 301e3
VREF = (1.223, 1.260)                         # TLV3011B REF, SBOS300C sec 6.9 (via DD Table 7)
VOS = 9e-3                                    # TLV3011B, SBOS300C sec 6.9
for vref in VREF:
    bt_open = vref * (1 / R_O) / (1 / R_B2 + 1 / R_O)
    r_lo = R_M2 / (R_M1 + R_M2)               # NOT-OK divider (Q_H shorts R_M3)
    vmot_ok = (bt_open + VOS + 8e-3) / r_lo
    print(f"   REF {vref:.3f} V: bus tap with VBUS open = {bt_open*1e3:.1f} mV -> channel reads OK for V-MOT > {vmot_ok:.2f} V")
mt16 = 16.0 * R_M2 / (R_M1 + R_M2)
print(f"   at V-MOT = VBUS = 16 V the V-MOT tap is {mt16:.3f} V >> bus tap: VOK ASSERTED at bus level")
print("   R_Bk2 short or C_Bk short: bus tap = 0 V -> same (OK at any V-MOT > ~0.1 V)")
print("   V-MOT side open (R_Mk1a/b open, tap wire open): V-MOT tap = 0 V -> NOT OK (safe)")
# Fail-safe alternative: pull the bus tap UP so an open tap reads NOT OK.
R_PU = 1e6
for vb in (0.0, 16.0):
    g = 1 / R_M1 + 1 / R_B2 + 1 / R_O + 1 / R_PU  # bus divider top modelled as R_M1-equal 99.8k
    tap = (vb / 99.8e3 + 1.242 / R_O + 5.0 / R_PU) / g
    print(f"   (option) 1 MOhm pull-up to 5 V on BTk: tap at VBUS {vb:4.1f} V = {tap:.4f} V")
g_open = 1 / R_B2 + 1 / R_O + 1 / R_PU
print(f"   (option) with VBUS tap open the tap = {(1.242/R_O + 5.0/R_PU)/g_open:.3f} V -> still LOW; a pull-up alone cannot fix it")
print("   -> the fail-safe form is a comparator polarity/structure change or an independent tap per channel (see finding)")

# Loop magnitude with both VOK channels false-OK in a regen window (BT_BUS closed): circulating power balance
hdr("C2", "Loop gain with VOK false-OK and BT_BUS closed")
ETA_CHG, ETA_BT = 0.88, 0.90   # Ag105 DS p.20 (3S/12 V only); TPS61288 eta assumed 0.90 (UNCONFIRMED)
I_P, V_PACK, AUX_W = 1.75, 7.8, 2.4
for s in (0.2, 0.5, 0.7, 0.75, 0.78):
    den = ETA_CHG - s / ETA_BT
    if den <= 0:
        print(f"   BT share {s:.2f}: unbounded (runaway to the eFuse I_OL)")
        continue
    p_in = (I_P * V_PACK + s * AUX_W / ETA_BT) / den
    print(f"   BT share {s:.2f}: charger input {p_in:5.1f} W = {p_in/16.0:4.2f} A at 16 V "
          f"(eFuse I_OL 1.84-2.16 A, SLVSE94G sec 6.5)")
print(f"   divergence at BT share s = eta_chg x eta_bt = {ETA_CHG*ETA_BT:.3f}")

# ---------------------------------------------------------------------------
# D. U_C2 threshold-side faults that pass the injection self-test (DD Fig. 3, sec 9.3 step 5)
# ---------------------------------------------------------------------------
hdr("D", "U_C2 / U_C1 injection coverage")
R_T2a, R_T2b, R_I2 = 10e3, 12.1e3, 1e3
VS_SWING_MAX = 3.3 - 0.2        # INA240 swing to VS - 0.2 V (SBOS662C sec 7.5, via DD Table 7)
th2_open = 3.3                  # R_T2b open: TH2 pulled to 3V3 by R_T2a
th2_inj = 3.3 * R_I2 / (R_T2a + R_I2)
print(f"   R_T2b open: TH2 = {th2_open:.2f} V > INA240 max output {VS_SWING_MAX:.2f} V -> U_C2 can never trip")
print(f"   injection (Q_I2a/b on, R_I2 1k): TH2 = {th2_inj:.3f} V < SIG2 1.65 V -> trips -> self-test PASSES")
for rb in (12.1e3, 15e3, 20e3, 30e3):
    th = 3.3 * rb / (R_T2a + rb)
    i_trip = (th - 1.65) / 0.05          # 50 mV/A (INA240A3 x 0.5 mOhm)
    print(f"   R_T2b {rb/1e3:5.1f}k: TH2 {th:.3f} V -> charge trip {i_trip:5.2f} A (injection still passes)")
print("   R_F2 open: SIG2 floats on C_F2 (TLV3011B I_B pA-class) near its last value ~1.65 V; injection pulls TH2 to")
print(f"   {th2_inj:.2f} V -> trips -> passes; in service SIG2 frozen -> U_C2 blind")
R_T1a, R_T1b, R_F1, R_I1 = 12e3, 10e3, 1.5e3, 1e3
sig1_inj = 1.65 * R_I1 / (R_F1 + R_I1)
print(f"   U_C1 injection level {sig1_inj:.3f} V: any TH1 in ({sig1_inj:.2f}, 1.50] V passes, i.e. trip current up to "
      f"{(1.65-sig1_inj)/0.05:.1f} A")

# ---------------------------------------------------------------------------
# E. D5 threshold-side fault (no in-service test)
# ---------------------------------------------------------------------------
hdr("E", "D5 reference open")
print("   R_D5c (1.00k bottom) open: IN+ = 3.3 V; INA253 output max ~VS (3.3 V) -> D5 can never trip; no self-test step")

# ---------------------------------------------------------------------------
# F. Parallel bond upstream of R_SH (F12 class, KS+ lead to GND, earthed probe on pack-)
# ---------------------------------------------------------------------------
hdr("F", "Current split with a parallel pack-negative bond R_b upstream of R_SH")
R_CHAIN_PARTS = {"R_SH": 0.5e-3, "S_CHG": 1.6e-3, "VBATN_X+joints": 5e-3}
for r_s in (0.02, 0.05, 0.10):   # Ag105 sense resistance unknown (BENCH S0-1)
    r_chain = sum(R_CHAIN_PARTS.values()) + r_s
    for r_b in (0.02, 0.1, 0.5):
        i_set = 1.75
        i_pack = i_set * (1 + r_chain / r_b)
        print(f"   R_s {r_s*1e3:4.0f} mOhm, R_b {r_b*1e3:4.0f} mOhm: Ag105 sees {i_set} A, I_PACK1 sees {i_set} A, "
              f"true pack current {i_pack:5.2f} A, bond carries {i_pack-i_set:5.2f} A")
print("   U_C2 (R_SH), ERR_ISO_MISMATCH (I_PACK1 vs reg 0x06) and V_PACKN/I_PACK1 all read the chain current: blind")

# ---------------------------------------------------------------------------
# G. Single-fault loss of both S_GND channels via the shared gate supply F_T / C_VT
# ---------------------------------------------------------------------------
hdr("G", "Both S_GND on body diodes (F_T open or C_VT short)")
VSD = (0.7, 1.0)    # CSD18510Q5B body diode, 1.0 V max at 32 A (SLPS632, via DD Table 7); 0.7 V working low value
for i in (3.0, 7.2, 17.1):
    p = [v * i for v in VSD]
    print(f"   I {i:5.1f} A: total body-diode loss {p[0]:5.1f}-{p[1]:5.1f} W ({p[0]/2:4.1f}-{p[1]/2:4.1f} W per FET)")
for vp in (7.4, 7.8):
    for i, vd in ((1.0, 0.75), (7.2, 0.85)):
        print(f"   V_pack {vp}, I {i} A: VBT-GND ~ {vp - vd - i*0.0129:.2f} V vs LM1084 6.5 V (SNVS037H sec 5.5)")
