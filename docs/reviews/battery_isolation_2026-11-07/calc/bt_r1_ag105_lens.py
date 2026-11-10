"""Battle-test round 1, Ag105-behaviour / bench-gate lens: checks on detailed_design_IC1.md revision 3.

Every input is cited. Stdlib only. Run: python bt_r1_ag105_lens.py
"""

ETA = 0.88            # Ag105 DS p.20 row 1 (12 V in, 3S only; design working value)
I_AUX = 0.15          # A bus aux, detailed_design_IC1 Table 8 / calc section 1
I_FC_OC = 1.4         # A, LIMIT_I_FC_MAX, teensy_controller.ino:2090 (bus side, single sample)
V_BUS_FC = 15.92      # V at VCHG-IN in an FC window, ic1_rev3_calcs_output section 3
BENCH_LIM = 1.5       # A, commissioning bench supply limit, detailed_design_IC1 section 9.2 step 2
I_OL = (1.84, 2.16)   # A, TPS26631 I_OL at R_ILIM 9.09k, design Table 7 (SLVSE94G 6.5)
U_C1 = (2.67, 3.33)   # A, design Table 10
U_C2 = (2.84, 3.47)   # A, design Table 10
RATING = 2.5          # A module output, Table 4 JSON code 1 / design section 7.1


def hdr(s):
    print("\n" + "=" * 78 + "\n" + s + "\n" + "=" * 78)


hdr("A. Commissioning (section 9.2) with the as-found vehicle registers")
# As-found: reg 0x00 = 0x01 (2500 mA) written by pollAg105 lazy config (ino:2467-2468, CLAUDE.md section 3)
# and by the fw v37 J '1 2' session; reg 0x02 register mode 12.85 V (facts_prior section 4.2).
for I_L in (0.3,):
    for vp in (7.4, 7.8, 7.99):
        I_o = 2.5 + I_L
        p_in = vp * I_o / ETA
        i_in = p_in / V_BUS_FC
        i_bus = i_in + I_AUX
        print(f"  V_pack {vp:4.2f} V: I_o {I_o:.2f} A (rating {RATING} A), P_in {p_in:5.1f} W, "
              f"I_chg_in {i_in:.3f} A, bus-side {i_bus:.3f} A vs OC_FC {I_FC_OC} A -> "
              f"{'TRIPS' if i_bus > I_FC_OC else 'ok'}; vs bench limit {BENCH_LIM} A (bus side, before FC-boost loss) -> "
              f"{'LIMITED' if i_bus > BENCH_LIM else 'ok'}")
print("  Pack >= 8.0 V: Ag105 reports Fully Charged at detection (DS p.5/p.6, 0.2 V/cell) -> no charge current.")

hdr("B. RCS drift-high single fault (Table 4 JSON: larger R = larger current)")
table4 = [(62e3, 1.75), (100e3, 2.0), (200e3, 2.5)]
for r, i_set in table4:
    for I_L, mode in ((0.6, "regen"), (0.3, "FC")):
        I_o = i_set + I_L
        for vp in (7.4, 8.0):
            p_in = vp * I_o / ETA
            for vin in ((17.0, 21.5) if mode == "regen" else (V_BUS_FC,)):
                i_in = p_in / vin
                print(f"  R_CS {r/1e3:5.0f}k I_set {i_set:.2f} A {mode:5s} V_pack {vp} I_o {I_o:.2f} A "
                      f"({'OVER' if I_o > RATING else 'in'} rating) V_in {vin:5.2f} I_in {i_in:.2f} A "
                      f"eFuse({'TRIP' if i_in > I_OL[0] else 'no trip'}) U_C2({'TRIP' if i_set > U_C2[0] else 'no trip'})"
                      + (f" bus {i_in + I_AUX:.2f} A vs OC_FC" if mode == "FC" else ""))

hdr("C. eFuse-only bound on Ag105 OUTPUT current when its regulation is blind (F19 / OR-I)")
for vin in (V_BUS_FC, 17.0, 21.5):
    for vp in (7.4, 8.4):
        i_o = I_OL[1] * vin * ETA / vp
        print(f"  V_in {vin:5.2f} V, V_pack {vp}: I_o up to {i_o:.2f} A = {i_o / RATING:.2f} x rating "
              f"(U_C2 caps only the pack share at {U_C2[1]} A; I_L adds on top)")

hdr("D. Stage-3 C_HU energy left on the Ag105 input at window exit (eFuse off)")
C_HU = 1.5e-3   # F, design Table 7
for v0 in (13.82, 18.0, 21.47):
    e = 0.5 * C_HU * (v0 ** 2 - 11.0 ** 2)   # down to the 11 V V_LOCK (Ag105 DS p.19)
    for p in (0.018 * v0, 15.0, 21.0):
        print(f"  from {v0:5.2f} V: {e*1e3:6.1f} mJ above V_LOCK; at {p:5.2f} W draw -> {e/p*1e3:7.1f} ms powered after exit")

hdr("E. Reverse-current gate coverage")
print(f"  S0-9 tests 3.0 A / 60 s; U_C1 passes up to {U_C1[1]} A indefinitely (no time limit), windows 30 s "
      f"each at up to 20 transitions/min (design 8, 12.4).")
print("  S0-10 tests 15 A / 1 ms; BT boost switch limit 17.1 A (design 7.6, SLVSFP3C 7.5); U_C1 path to bond "
      "= 76 us + 3 x 88-114 us gate rise = 0.34-0.42 ms.")
for tau in (88e-6, 114e-6):
    print(f"   tau {tau*1e6:.0f} us: trip-to-bond ~ {(76e-6 + 3 * tau) * 1e3:.2f} ms")
