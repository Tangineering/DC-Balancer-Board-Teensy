"""IC1 detailed design, revision 6 calculations (battle-test round 3 fixes).

Cited in detailed_design_IC1.md as "calc6 section N". Stdlib only.
Primaries (as cited in the design document):
  BOM 20260622 line 86 (RB1A/RB1B 100 Ohm 0402 0.125 W), line 88 (RB3 261 Ohm 0402 0.1 W);
  facts_board 2.3 (balance network), 5 (BQ29200 pins); SLUSA52C 7.1 (VC1 >= -0.3 V);
  SLVSE94G 6.5 (GAIN(IMON) 25.66/27.9/30.14 uA/A; I(OL) 1.84/2.00/2.16 A at R_ILIM 9 k, I_OL ~ 1/R_ILIM);
  SBOS300C 6.9 (TLV3011B V_OS +/-9 mV, V_HYS 2-8 mV, REF 1.223-1.260 V);
  Ag105 DS p.20 row 6 (I_DIS 4 A); design Table 9 (VOK release), Table 10 (U_C1/U_C2), Table 11 (loop timing);
  teensy_controller.ino:2028/2032 (SCALE_V_BUS, SCALE_V_RGN), :2020 (12-bit ADC).
Every value tagged ASSUMED below has no primary.
"""
import math

def hdr(s):
    print("\n[" + s + "]")

# ---------------------------------------------------------------- 1
hdr("1 Pin-side BQ29200 clamps (replace D_VM at VMID)")
RB3, RB1A = 261.0, 100.0          # BOM lines 88, 86
P_RB3, P_RB1A = 0.100, 0.125      # W ratings, BOM lines 88, 86
Rpar = RB3 * RB1A / (RB3 + RB1A)
for vc in (3.0, 3.7, 4.2):
    print(f"V_cell {vc:.1f} V: clamp short via RB3 {vc/RB3*1e3:5.1f} mA ({vc**2/RB3*1e3:5.1f} mW, rating {P_RB3*1e3:.0f} mW);"
          f" via RB1A {vc/RB1A*1e3:5.1f} mA ({vc**2/RB1A*1e3:5.1f} mW, rating {P_RB1A*1e3:.0f} mW, x{vc**2/RB1A/P_RB1A:.2f})")
print(f"RB3 || RB1A = {Rpar:.1f} Ohm; F34b board return bound at V_cell2 4.2 V: {4.2/Rpar*1e3:.1f} mA")
# F34b: board return = GND -> clamps -> RB3/RB1A -> VMID -> cell 1+. VBT - GND = V_cell2 - V_F - I*Rpar.
for ib in (0.010, 0.030, 0.050):
    vbt = 4.2 - 0.25 - ib * Rpar
    print(f"  board current {ib*1e3:4.0f} mA: VBT - GND <= {vbt:5.2f} V (V_cell2 4.2 V, V_F 0.25 V)")
print("  -> above ~55 mA VBT - GND reaches 0: the board cannot draw more; the TPS61288 (VIN min 2.0 V) cannot run.")
# per-diode share in F34b (worst: all through the RB1A clamp)
print(f"  clamp current per diode at most: D_VCB {4.2/RB1A*1e3:.0f} mA, D_VC1 {4.2/RB3*1e3:.0f} mA")

# ---------------------------------------------------------------- 2
hdr("2 F_VX in VBATN_X (module end)")
legit = {"regen I_set": 1.75, "FC I_set": 1.25, "F38 high-R CSEL ceiling": 2.50,
         "U_C1 trip max (reverse, transient)": 3.50, "U_C2 trip max (charge, transient)": 3.64}
for k, v in legit.items():
    print(f"  {k:38s} {v:.2f} A")
F_VX = 4.0
print(f"F_VX {F_VX:.1f} A fast-acting: 75 % derating gives {0.75*F_VX:.2f} A continuous >= 2.50 A; "
      f"rating <= Ag105 I_DIS 4 A (DS p.20 row 6)")
# chafe loop currents (calc/bt3_buildability_measurement.py section 3 reproduces 39-252 A)
for vp, rint, rch, rcf, rs in ((8.4, .010, .003, 0.0, .010), (7.4, .040, .013, .050, .075)):
    r = rint + rch + rcf + 0.0103 + rs
    print(f"  chafe V_pack {vp} V, R_loop {r*1e3:.1f} mOhm: {vp/r:6.1f} A = {vp/r/F_VX:5.1f} x F_VX rating")
# OV_BATT boundary shift: rev 5 boundary 60-64 mOhm of R_s at 1.75 A; R_FVX ASSUMED 10-30 mOhm
for rf in (0.010, 0.030):
    print(f"  R_FVX {rf*1e3:.0f} mOhm (ASSUMED): R_s boundary {60-rf*1e3:.0f}-{64-rf*1e3:.0f} mOhm; "
          f"offset added at 1.75 A {1.75*rf*1e3:.1f} mV")

# ---------------------------------------------------------------- 3
hdr("3 Module-node dump (Q_MD/R_MD keyed to NOT EF_EN) and bleed R_MB")
R_MD, R_MB, C_EO = 15.0, 3300.0, 1e-6
for cm in (100e-6, 145e-6, 221e-6):
    c = cm + C_EO
    tau = R_MD * c
    print(f"C_mod {cm*1e6:4.0f} uF: tau {tau*1e3:4.2f} ms; 21.5->11 V {tau*math.log(21.5/11)*1e3:4.2f} ms;"
          f" 21.5->9 V {tau*math.log(21.5/9)*1e3:4.2f} ms; 16->9 V {tau*math.log(16/9)*1e3:4.2f} ms;"
          f" 16->0.5 V {tau*math.log(16/0.5)*1e3:5.1f} ms; energy at 21.5 V {0.5*c*21.5**2*1e3:4.1f} mJ")
    tb = R_MB * c
    print(f"   Q_MD open, bleed R_MB only: 16->9 V {tb*math.log(16/9):4.2f} s; 21.47->11 V {tb*math.log(21.47/11):4.2f} s")
print(f"R_MD peak {21.5/R_MD:.2f} A; probe with a bypassed eFuse: {16**2/R_MD:.1f} W "
      f"(1.0 A from the FC bus); 10 ms {16**2/R_MD*0.010:.2f} J, 100 ms cap {16**2/R_MD*0.1:.2f} J")
print(f"R_MB dissipation at 21.5 V {21.5**2/R_MB*1e3:.0f} mW, {21.5/R_MB*1e3:.1f} mA ({21.5/R_MB/1.0*100:.2f} % of a 1 A input)")
# interlock: dump gate off within ~1 us of EF_EN rising; eFuse output slew <= 5.79 V/ms
print(f"dump-off interlock: in 1 us the eFuse output rises <= {5.79e3*1e-6*1e3:.1f} mV -> <= {5.79e-3/R_MD*1e3:.2f} mA in R_MD")

# ---------------------------------------------------------------- 4
hdr("4 U_MS module-node comparator (VCHG-IN_M, threshold ~9 V)")
R1, R2 = 100e3, 16.2e3
k = R2 / (R1 + R2)
for ref, os_ in ((1.223, -0.009), (1.2415, 0.0), (1.260, 0.009)):
    for tol in (0.998, 1.002):
        pass
lo = (1.223 - 0.009) / (k * 1.002)
hi = (1.260 + 0.009 + 0.004) / (k * 0.998)
print(f"divider ratio {k:.4f}; threshold nominal {1.2415/k:.2f} V; range {lo:.2f}-{hi:.2f} V (REF, V_OS, hysteresis, 0.1 %)")
print(f"IN+ at 21.5 V {21.5*k:.2f} V (below 3V3 + 0.2 V); divider current {21.5/(R1+R2)*1e3:.2f} mA")

# ---------------------------------------------------------------- 5
hdr("5 U_IM window with SLVSE94G gain tolerance; R_ILIM 9.09k -> 8.06k")
G = (25.66e-6, 30.14e-6); RIM = 10e3; DIV = 10 / 69
def iol(r):
    return 1.84 * 9 / r, 2.16 * 9 / r
for r in (9.09, 8.25, 8.06):
    a, b = iol(r)
    print(f"R_ILIM {r:.2f}k: I_OL {a:.3f}-{b:.3f} A; fast trip 3 x I_OL {3*a:.1f}-{3*b:.1f} A; "
          f"P_in bound at 21.47 V {b*21.47:.1f} W")
worst_hi = 0
for v33 in (3.2, 3.3, 3.4):
    vt = v33 * DIV
    hi = (vt * 1.002 + 0.009 + 0.004) / (G[0] * RIM * 0.999)
    lo = (vt * 0.998 - 0.009 + 0.001) / (G[1] * RIM * 1.001)
    worst_hi = max(worst_hi, hi)
    print(f"3V3 {v33}: U_IM trip {lo:.3f}-{hi:.3f} A (one-sided hysteresis)")
a, _ = iol(8.06)
print(f"upper trip {worst_hi:.3f} A vs I_OL min {a:.3f} A at 8.06k: margin {a-worst_hi:.3f} A (need >= 0.05)")
print(f"lower trip at 3.2 V vs largest legitimate input 1.458 A (calc bt3 datasheet lens s1): margin "
      f"{(3.2*DIV*0.998-0.008)/(G[1]*RIM*1.001)-1.458:.3f} A")

# ---------------------------------------------------------------- 6
hdr("6 ERR_VOK_STUCK ratio rule")
# Table 9 release minimum, less 32 mV for a centred hysteresis (calc4 section 3)
for vb, rel in ((13.5, 13.69), (15.9, 16.06), (16.0, 16.16), (16.5, 16.65), (17.5, 17.64)):
    print(f"VBUS {vb:4.1f} V: healthy-permit floor ratio V_MOT/VBUS >= {(rel-0.032)/vb:.4f}")
print("stuck channel at bus level reads r = 1.000 against the Idle self-calibration (V-MOT = VBUS - D-MT-EN drop)")
lsb_rgn = 3.3 * 88.7 / 10 / 4095; lsb_bus = 3.3 * 56.4 / 10 / 4095
print(f"ADC LSB: pin 39 {lsb_rgn*1e3:.2f} mV, pin 26 {lsb_bus*1e3:.2f} mV; ratio quantum at 16 V "
      f"{math.hypot(lsb_rgn, lsb_bus)/16*100:.3f} % (one sample)")
print("r_TH 1.003: margin 0.003 below the 1.0063 healthy floor and 0.003 above a stuck channel")
# rev-5 single-assert interval for reference (bt3_transient_sim section 1): 0.754 V / decay
for r in (8.0, 14.2, 17.0, 20.1):
    print(f"  rev-5 dwell rule: single-assert interval at {r:4.1f} V/s = {0.754/r*1e3:5.1f} ms (50 ms dwell)")

# ---------------------------------------------------------------- 7
hdr("7 Iteration-count confirmation (FM3-3)")
med, p99, worst = 1.131, 1.341, 9.76
print(f"4 iterations at the median {4*med:.2f} ms, at p99 {4*p99:.2f} ms; with one worst gap "
      f"{worst+3*med:.2f} ms (< 30 ms cap < 43 ms pump hang)")
print(f"settled after one worst gap = gap + median = {worst+med:.2f} ms (fmea_round3 s3 printed 2*gap = {2*worst:.2f} ms)")
print(f"ladder persistence 3 iterations at the median {3*med:.2f} ms")

# ---------------------------------------------------------------- 8
hdr("8 ERR_IPACK_PLAUS re-key (BT3-RO-01)")
for bt, floor in ((0.4, 0.10),):
    true = bt - floor
    pred = true * 15.1 / 8.4
    print(f"BT_CURRENT {bt} A with the 0.10 A INA253 floor: true >= {true:.2f} A -> pack discharge >= {pred:.3f} A "
          f"(15.1 V bus, 8.4 V pack, eta 1.0) = x{pred/0.25:.2f} the 0.25 A pass/latch level")

# ---------------------------------------------------------------- 9
hdr("9 Exit and traction delay with the measured drain")
for cm in (100e-6, 145e-6, 221e-6):
    td = R_MD * (cm + C_EO) * math.log(21.5 / 9)
    print(f"C_mod {cm*1e6:4.0f} uF: drain to pin-8 LOW {td*1e3:4.2f} ms (+1 iteration) ; traction delay "
          f"{td*1e3+3*med:4.2f} ms median, {td*1e3+3*p99:4.2f} ms p99 (drain + one pin-8 confirm read + two settled exit reads)")
print("cap T_drain,max 10 ms -> ERR_MOD_DRAIN")
