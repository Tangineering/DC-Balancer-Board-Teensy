"""Battle-test round 2, Ag105-behaviour and bench-gate lens: supporting calculations.

Target: detailed_design_IC1.md revision 4. Stdlib only. Every input names its source.
Run: python bt_r2_ag105_lens.py > bt_r2_ag105_lens_output.txt
"""

# ---------------------------------------------------------------------------
# Section 1. ERR_ISO_MISMATCH residual when the Ag105 is not delivering current
# Design rule (detailed_design_IC1.md section 12.6, Table 16):
#   trip when |I_PACK1 - reg06 * 0.011 A| > max(0.15 A, 10 %) for 100 ms,
#   in an FC window or a configuration check, charger powered, valid read
#   (valid = GENSTAT Charging or Fully Charged and data != 0xFF, section 12.5 item 2).
# Reg 0x06 is an unsigned 8-bit field, 0.011 A/count (Ag105 DS p.13 Table 7; Table7 JSON):
#   it cannot represent a reverse (discharge) current, so its floor is 0 A.
# In the charge mode the board load I_L returns through the Ag105 sense in reverse (OR-S,
#   design section 0.1 and section 7.1). When the module output is zero (Fully Charged,
#   DS p.5 / p.11; or pin 32 LOW so D-BT-SQ is disabled, design section 9.2/9.7a),
#   I_PACK1 = -I_L.
# I_L working values: 0.3 A (BT_BUS open, FC window / config check), 0.6 A (BT_BUS closed),
#   design Table 8 (ASSUMED, gate B8 open).
print("Section 1. ERR_ISO_MISMATCH residual with the module output at zero")
for i_l in (0.1, 0.2, 0.3, 0.6):
    i_pack1 = -i_l
    for reg06_a in (0.0, i_l):  # 0 = unsigned floor; i_l = worst plausible magnitude reading
        resid = abs(i_pack1 - reg06_a)
        ref = max(abs(i_pack1), reg06_a)
        thr = max(0.15, 0.10 * ref)
        print(f"  I_L {i_l:.2f} A, reg06 {reg06_a:.2f} A: residual {resid:.3f} A, "
              f"threshold {thr:.3f} A -> {'TRIP' if resid > thr else 'no trip'}")
# Minimum I_L that trips with reg06 = 0: residual = I_L > 0.15 A.
print("  Trip for any I_L above 0.150 A when reg06 reads 0 (unsigned floor).")
print()

# Charging but input-power-limited (MPPT threshold holding the input, design 9.7 / DS p.10):
# output I_o below I_L gives a negative pack current while GENSTAT stays Charging.
print("Section 1b. Charging, output below I_L (input-limited)")
for i_o in (0.0, 0.1, 0.2):
    i_l = 0.3
    i_pack1 = i_o - i_l
    resid = abs(i_pack1 - 0.0)
    print(f"  I_o {i_o:.2f} A, I_L {i_l:.2f} A: I_PACK1 {i_pack1:+.2f} A, reg06 0.00 A, "
          f"residual {resid:.2f} A -> {'TRIP' if resid > 0.15 else 'no trip'}")
print()

# ---------------------------------------------------------------------------
# Section 2. R_KA keep-alive and the battery-side supply of the module
# Ag105 DS p.20 row 7: battery standby current 120-420 uA with no input voltage.
# R_KA = 1 kOhm (design Table 7, M11).
print("Section 2. R_KA drop at the battery standby current")
for i_sb in (120e-6, 420e-6):
    print(f"  I_BAT {i_sb*1e6:.0f} uA: drop {i_sb*1e3:.3f} V across 1 kOhm; "
          f"module battery pins at V_pack - {i_sb*1e3:.2f} V")
print("  The battery side of the module is therefore supplied from the pack through R_KA")
print("  whenever the input is absent, in the bonded mode included.")
print()

# ---------------------------------------------------------------------------
# Section 3. Residual module energy after the eFuse turns off (exit, trip, State 99)
# The S0-11 gate admits an inrush of at most 0.6 A at the C_DV 10 nF slew of
# 4.17-5.79 V/ms (design Table 7, calc section 5): C_in <= 0.6 / slew.
print("Section 3. Module input capacitance admitted by S0-11 and the residual energy")
for slew_v_per_ms in (4.17, 5.79):
    c_max = 0.6 / (slew_v_per_ms * 1e3)
    print(f"  slew {slew_v_per_ms:.2f} V/ms: C_in up to {c_max*1e6:.0f} uF")
c_in = 0.6 / 4.17e3 + 1e-6  # worst admitted C_in plus C_EO 1 uF (design Fig. 6)
for v0 in (16.0, 18.0, 21.5):
    e = 0.5 * c_in * (v0**2 - 11.0**2)  # down to the 11 V lockout (DS p.19)
    for p in (13.0, 22.4):  # Table 8 input powers (FC 7.4 V, regen 8.4 V)
        t = e / p
        print(f"  V_in {v0:4.1f} V: E {e*1e3:5.1f} mJ; at {p:4.1f} W the module runs "
              f"{t*1e3:5.2f} ms after the eFuse cut")
print("  D-BT-SQ is disabled 0.3-0.7 ms after the FF1 clear (design Table 11), RT1987 turn-off")
print("  after EN low is TODO(verify: RT1987 DS-00); S_GND is on within about 0.3 ms.")
print()

# ---------------------------------------------------------------------------
# Section 4. S0-2 real-pack bound from the lab-supply limit
# Rig limit: <= 1.2 x P_in / V_in (design section 14.1). Efficiency 0.88 (DS p.20, 12 V 3S only).
print("Section 4. Pack-current bound on the S0-2 real-pack runs (lab supply limit only)")
for name, p_in_nom, v_in, i_l in (("regen 1.75 A", 19.8, 18.0, 0.6), ("FC 1.25 A", 13.0, 16.0, 0.3)):
    p_lim = 1.2 * p_in_nom
    i_in = p_lim / v_in
    for eta in (0.80, 0.88, 0.95):
        i_out = p_lim * eta / 7.4
        print(f"  {name}: supply limit {i_in:.2f} A at {v_in:.0f} V; eta {eta:.2f}: module output "
              f"{i_out:.2f} A, pack {i_out - i_l:.2f} A (I_L {i_l} A)")
print("  The bound is a power bound on a lab supply CC loop (millisecond response, output")
print("  capacitor dump not bounded); the rig has no fast pack-current trip.")
