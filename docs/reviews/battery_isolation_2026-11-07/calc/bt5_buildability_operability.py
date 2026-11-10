"""Battle-test round 5, buildability and operability lens: checks on the revision-7 delta of detailed_design_IC1.md.

Sources (all cited in the finding text):
  IMXRT1060CEC Rev. 4 (04/2024) Table 7 (Vin/Vout -0.5 .. OVDD+0.3 V), Table 22 (IIN -1..+1 uA no PU/PD;
    R_Keeper 105-175 kOhm at 0.3/0.7 NVCC), Table 54 (RAS <= 1 kOhm at Tsamp 150 ns).
  SLUSA52C section 7.1 (VC2-VC1 -0.3..8 V; VC1-GND -0.3..16 V).
  detailed_design_IC1.md rev 7: R_VC1a = R_VC1b = 200 kOhm, C_VC1 100 nF, pin 20 = VC1/2; mismatch
    = V_BT - 2 V_VC1 + V_PACKN, threshold 80 mV, healthy budget 41.5 mV (calc7 section 2);
    row F22b (S_CHG on, board return through the Ag105 sense in reverse, one iteration + 5 ms);
    S0-9 (3.5 A reverse, steady), S0-10 (17 A for >= 0.5 ms, sacrificial module); C-2a item 20 (1, 3, 7 A).
"""
V33 = 3.3
R_a = R_b = 200e3
R_th = R_a * R_b / (R_a + R_b)
print("== 1. Pin-20 source and the i.MX RT pad keeper / leakage ==")
print(f"Thevenin source at pin 20: {R_th/1e3:.0f} kOhm")
for vc1 in (3.0, 3.7, 4.25):
    vth = vc1 / 2
    print(f" VC1 {vc1:.2f} V -> open-circuit pin 20 {vth:.3f} V (VIL 0.3*3.3 = 0.99 V, VIH 0.7*3.3 = 2.31 V: inside the undefined band)")
    for rk in (105e3, 175e3):
        v_lo = vth * rk / (rk + R_th)
        v_hi = vth + (V33 - vth) * R_th / (rk + R_th)
        print(f"   keeper {rk/1e3:.0f}k held LOW: pin {v_lo:.3f} V (err {1e3*(v_lo-vth):+.0f} mV) ; held HIGH: pin {v_hi:.3f} V (err {1e3*(v_hi-vth):+.0f} mV)")
# gain drift of a calibrated channel when the keeper resistance moves inside its range (keeper held LOW)
k1 = 105e3 / (105e3 + R_th); k2 = 175e3 / (175e3 + R_th)
print(f" keeper-LOW gain spans {k1:.3f}-{k2:.3f}; a calibration at one end read at the other: {100*(k2/k1-1):.1f} % gain error")
for drift_pct in (1, 2, 5):
    err_vc1 = 4.2 * drift_pct / 100
    print(f"   {drift_pct} % residual gain drift at VC1 4.2 V: V_VC1 error {1e3*err_vc1:.0f} mV -> mismatch error {2e3*err_vc1:.0f} mV (threshold 80, healthy margin 38.5)")
print(" mismatch sensitivity to a pin-20 current: dMismatch/dI = 2 (V_VC1 term) x 2 (divider) x R_th")
for i_ua in (0.1, 0.2, 0.5, 1.0):
    e = 4 * R_th * i_ua * 1e-6
    print(f"   I = {i_ua:.1f} uA (IIN spec max 1 uA): mismatch error {1e3*e:.0f} mV")
print(f" uncalibrated leakage that consumes the 38.5 mV margin: {38.5e-3/(4*R_th)*1e9:.0f} nA")

print("\n== 2. Tap lead chafed to VBT / VCHG: voltage at pin 20 ==")
print(" LB side of the lead = VC1_T = pin 20 directly (section 5.2 line 498: no series resistor at LB)")
for name, v in (("VBT 8.5 V", 8.5), ("VCHG-IN / V-MOT 21.5 V", 21.5)):
    print(f"  {name}: pin 20 forced to {v:.1f} V vs Table 7 max OVDD+0.3 = 3.6 V; ESD-diode current limited only by the chafe/wire;"
          f" current through R_VC1a ({v:.1f}-4.25)/200k = {1e6*max(v-4.25,0)/R_a:.1f} uA (the only current row F54 / calc7 bound)")

print("\n== 3. C-2a item 5: D_VC1 jumpered with a supply as the pack ==")
for vp in (7.4, 7.95, 8.0, 8.4, 8.5):
    print(f"  V_pack {vp:.2f} V: VC1 = 0 -> VC2-VC1 = {vp:.2f} V vs SLUSA52C 7.1 max 8 V -> {'OVERSTRESS' if vp > 8.0 else 'within'}")

print("\n== 4. C-2a item 20 reverse sense pulse on the fitted unit-Q module ==")
s0_10 = 17**2 * 0.5e-3
for i in (1, 3, 7):
    for t_it in (1.341e-3, 9.76e-3):
        t = t_it + 5e-3
        print(f"  {i} A for {1e3*t:.2f} ms (iteration {1e3*t_it:.2f} ms + 5 ms): I2t {i*i*t:.3f} A2s = {i*i*t/s0_10:.2f} x S0-10 (17 A, 0.5 ms = {s0_10:.4f} A2s); {i/3.5:.1f} x S0-9 3.5 A")
