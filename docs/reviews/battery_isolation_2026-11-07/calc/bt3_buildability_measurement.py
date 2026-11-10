"""Battle-test round 3, buildability and measurement-integrity lens, against detailed_design_IC1.md revision 5.

Stdlib only. Every input is cited or marked ASSUMED. Run:
  .venv_hil/Scripts/python.exe docs/reviews/battery_isolation_2026-11-07/calc/bt3_buildability_measurement.py
"""
import math


def hdr(n, t):
    print("=" * 78)
    print(f"Section {n}. {t}")
    print("=" * 78)


def awg_mohm_per_m(awg):
    # copper, 20 C: d = 0.127 mm * 92^((36-awg)/39); rho 1.724e-8 Ohm m
    d = 0.127e-3 * 92 ** ((36 - awg) / 39)
    a = math.pi * d * d / 4
    return 1.724e-8 / a * 1e3, a * 1e6, (d / 0.0254e-3) ** 2  # mOhm/m, mm2, circular mils


def onderdonk_a(cmil, t_s, ta=25.0, tm=1083.0):
    return cmil * math.sqrt(math.log10(1 + (tm - ta) / (234 + ta)) / (33 * t_s))


# ---------------------------------------------------------------------------
hdr(1, "D_VM (M16, GND anode -> VMID cathode): reversed fit or short = cell-1 short through the balance lead")
print("Loop: cell1(+) = VMID -> balance-lead VMID wire -> J-BL pin 2 -> D_VM -> GND pour -> lead A/B -> SGND ->")
print("      S_GND (bonded) -> PACK- -> R_SH -> pack-negative lead -> pack(-) -> [pack PCM, unknown] -> cell1(-)")
print("Inputs: V_cell1 3.0-4.2 V; balance wire ASSUMED 22-26 AWG, 0.15-0.30 m (pack lead + harness);")
print("        main return chain 3-13 mOhm (design budget 12.9 mOhm, sec. 7.6); cell R_int ASSUMED 5-20 mOhm;")
print("        shorted D_VM ASSUMED 10-100 mOhm; reversed D_VM: V_F ASSUMED 0.5-0.8 V at high current")
for awg in (22, 24, 26):
    r_m, mm2, cmil = awg_mohm_per_m(awg)
    print(f"  {awg} AWG: {r_m:.1f} mOhm/m, {mm2:.3f} mm2, {cmil:.0f} cmil; Onderdonk melt current 1 s {onderdonk_a(cmil,1):.0f} A, "
          f"10 s {onderdonk_a(cmil,10):.0f} A")
cases = []
for awg, length in ((22, 0.15), (26, 0.30)):
    r_w = awg_mohm_per_m(awg)[0] * length / 1e3
    for v_cell in (3.0, 4.2):
        for mode, vf, r_d in (("D_VM short", 0.0, 0.010), ("D_VM short", 0.0, 0.100), ("D_VM reversed", 0.5, 0.005), ("D_VM reversed", 0.8, 0.020)):
            for r_main, r_int in ((0.003, 0.005), (0.013, 0.020)):
                r = r_w + r_d + r_main + r_int
                i = max(v_cell - vf, 0) / r
                cases.append(i)
                if (r_main, r_int) == (0.013, 0.020) or r_d == 0.010:
                    print(f"  {mode:13s} {awg} AWG {length:.2f} m, V_cell1 {v_cell:.1f} V, R_main {r_main*1e3:.0f} mOhm, "
                          f"R_int {r_int*1e3:.0f} mOhm, R_D {r_d*1e3:.0f} mOhm: I = {i:6.1f} A")
print(f"  range over the grid: {min(cases):.0f}-{max(cases):.0f} A; no fuse in the loop (F_PK is in the pack-positive lead);")
print("  the only interrupter is the pack PCM, whose existence and trip are unknown (facts_prior section 9, line 237).")
print("  Before revision 5 nothing joined VMID to GND except RB3/RB1A (260/100 Ohm) into the BQ29200: a fault there gave mA.")

# ---------------------------------------------------------------------------
hdr(2, "F34b in service: pack negative opens while the BT boost runs -> D_VM carries the boost input current")
print("TPS61288 VIN range 2.0-18 V; VIN UVLO falling 1.8-2.0 V; switch peak limit 12/15/17.1 A (TPS61288 DS, sec. 7.5).")
print("After the open, VBT - GND = V_cell2 - V_F(D_VM) - I x R_balance: the boost keeps regulating the bus from cell 2.")
for p_in in (20.0, 53.3, 80.0):
    for v_cell2 in (3.7, 4.2):
        r_bal = 0.040  # 26 AWG 0.3 m (section 1)
        # solve I = P/(V - 0.3 - I R)
        v0 = v_cell2 - 0.3
        disc = v0 * v0 - 4 * r_bal * p_in
        if disc < 0:
            print(f"  P_in {p_in:5.1f} W, V_cell2 {v_cell2:.1f} V: no operating point below the switch limit -> input at the "
                  f"current limit (12-17.1 A peak)")
            continue
        i = (v0 - math.sqrt(disc)) / (2 * r_bal)
        print(f"  P_in {p_in:5.1f} W (53.3 W = 7.2 A at 7.4 V, in-service figure of sec. 7.6), V_cell2 {v_cell2:.1f} V: "
              f"I(D_VM, balance lead) = {i:5.1f} A until the Teensy browns out")
print("  Duration = 5 V rail hold-up to the Teensy reset (not given in the design; UNCONFIRMED, ms-scale); the boost EN has")
print("  only the internal 850-1100 kOhm pull-down (TPS61288 DS R_EN).")
print("  Gate B-PKN opens pack negative with the Teensy on USB and the boosts idle: it measures only the brown-out current.")

# ---------------------------------------------------------------------------
hdr(3, "VBATN_X shorted to pack positive (harness chafe, SB copper): pack short through the Ag105 internal sense")
print("Bonded mode: VBATN_X is tied to Vin- = GND through the module sense R_s (S_CHG off). Charge mode: U_C1 trips,")
print("FF1 clears, S_GND re-bonds and S_CHG opens -> the same loop as the bonded mode.")
print("Loop: pack(+) -> F_PK -> chafe -> VBATN_X lead -> pins 14/15 stubs -> R_s (+ internal parallel switch, unknown) ->")
print("      Vin- pin 4 -> GND pour -> lead A/B -> S_GND -> R_SH -> pack(-)")
print("Inputs: V_pack 7.4-8.4 V; R_int 10-40 mOhm ASSUMED (calc5 sec. 1 range); R_s 10-75 mOhm (S0-1 unknown; 60-74 mOhm")
print("        is the design's OV_BATT boundary, sec. 12.6); VBATN_X 10.3-17.2 mOhm (sec. 12.6); chain 3-13 mOhm; chafe 0-50 mOhm")
for v in (7.4, 8.4):
    for r_s in (0.010, 0.040, 0.075):
        for r_int, r_ch, r_cf in ((0.010, 0.003, 0.0), (0.040, 0.013, 0.050)):
            r = r_int + r_ch + r_cf + 0.0103 + r_s
            i = v / r
            p_s = i * i * r_s
            print(f"  V {v:.1f} V, R_s {r_s*1e3:4.0f} mOhm, R_int {r_int*1e3:2.0f}, chain {r_ch*1e3:2.0f}, chafe {r_cf*1e3:2.0f}: "
                  f"I = {i:5.0f} A ({i/4:4.1f} x I_DIS 4 A), I/F_PK = {i/20:4.1f} x, P(R_s) = {p_s:6.0f} W")
print("  F_PK is a 20 A slow-blow ATO (sec. 5.6); its clearing time at 2.3-11 x rating is TODO(verify: fuse datasheet).")
print("  U_C1 (2.52-3.50 A discharge) can only re-bond; in the bonded mode it has no actuator that opens this loop.")

# ---------------------------------------------------------------------------
hdr(4, "Pre-heat of M13 / M16 against the Ag105 absolute maximum storage temperature")
print("Ag105 DS V1.1 p.19, Absolute Maximum Ratings row 2: storage -40 to +100 C.")
print("Design M13/M16: pre-heat the board area to 100-120 C. M16 (J-BL pin 3, (11.43, 30.48)) is 4.0 mm below and")
print(f"7.5 mm left of the Ag105 body corner (x 18.9, y 34.5): distance {math.hypot(18.9-11.43, 34.5-30.48):.1f} mm.")
print("Build order of Table 6 puts M1/M2 (module cut, unit fitted) before M13/M16; gate D-3 (module qualification) is a")
print("pre-rework gate, so the qualified unit is soaked at up to 20 C above its absolute maximum after qualification.")
