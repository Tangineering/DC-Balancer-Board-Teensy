"""Battle-test round 3, datasheet re-verification lens: calculations.

Sources (vendor primaries, read 2026-11-07):
  SLVSE94G (TPS2663x, rev. June 2024): section 6.5 GAIN(IMON) 25.66/27.9/30.14 uA/A for 0.6 A <= I_OUT <= 2 A,
      26.22/27.9/29.58 uA/A for 2-6 A; I(OL) 1.84/2.00/2.16 A at R_ILIM 9 kOhm; R_ON 30.44 mOhm typ;
      section 6.5 RthJA 31.4 C/W; T(J_REG) 136/145/154 C; section 8.3.7.2.1 thermal regulation at start-up.
  SBOS300C (TLV3011B, rev. April 2023): section 6.9 V_OS +/-6 mV (25 C), +/-9 mV (-40..125 C);
      input hysteresis 2/6/8 mV; section 9.4.5 POR output Hi-Z for up to 1.9 ms.
  Ag105 DS V1.1 (local PDF): p.14 "If the input voltage is below 9 volts or the Ag105 reports an error state ...
      all measures transmitted will be 0xFF"; p.6 Bring-Up / battery disconnect; Table 5 mode 2
      "Disconnected Battery Error".
  Design values: detailed_design_IC1.md rev 5 (Figure 2, section 7.5, section 9.7a, Table 10, calc5 section 9).
"""


def hdr(n, t):
    print(f"\n[{n}] {t}")


# ---------------------------------------------------------------------------
hdr(1, "U_IM trip window with the SLVSE94G IMON gain tolerance (design: 1.68-1.75 A, gain tolerance excluded)")
R_IM_NOM = 10e3
R_IM_TOL = 0.001
G_IMON = (25.66e-6, 27.9e-6, 30.14e-6)        # A/A, SLVSE94G 6.5, 0.6-2 A row
VOS = 0.009                                    # TLV3011B, -40..125 C (SBOS300C 6.9)
VHYS_HALF = 0.004                              # TLV3011B hysteresis 8 mV max, assumed centred (SBOS300C 6.9)
DIV = 10.0 / (59.0 + 10.0)                     # R_IMb / (R_IMa + R_IMb), 0.1 % parts
DIV_TOL = 0.002                                # two 0.1 % resistors, worst case
I_OL_MIN = 1.84 * 9.0 / 9.09                   # SLVSE94G 6.5 at 9 kOhm, scaled to R_ILIM 9.09 kOhm
I_OL_MAX = 2.16 * 9.0 / 9.09
LEGIT = (("regen input, eta 0.80 at 18 V (design calc5 s9)", 1.37),
         ("regen input at the 2.5 A output ceiling, eta 0.80, 8.4 V, 18 V", 2.5 * 8.4 / 0.80 / 18.0))

for v33, lab in ((3.30, "3V3 nominal"), (3.20, "3V3 3.20 V (Table 10 ASSUMED)"), (3.40, "3V3 3.40 V (Table 10 ASSUMED)")):
    vth = v33 * DIV
    i_lo = (vth * (1 - DIV_TOL) - VOS - VHYS_HALF) / (G_IMON[2] * R_IM_NOM * (1 + R_IM_TOL))
    i_hi = (vth * (1 + DIV_TOL) + VOS + VHYS_HALF) / (G_IMON[0] * R_IM_NOM * (1 - R_IM_TOL))
    i_nom = vth / (G_IMON[1] * R_IM_NOM)
    print(f"   {lab}: threshold {vth:.4f} V; trip nominal {i_nom:.3f} A; worst range {i_lo:.3f}-{i_hi:.3f} A")
    print(f"      upper trip minus I_OL min ({I_OL_MIN:.3f} A): {i_hi - I_OL_MIN:+.3f} A "
          f"-> {'U_IM can sit ABOVE I_OL: a start into an overload at I_OL is not detected' if i_hi > I_OL_MIN else 'ok'}")
    for name, il in LEGIT:
        print(f"      lower trip minus {name} ({il:.3f} A): {i_lo - il:+.3f} A")

# Gain-only spread at nominal everything else
vth = 3.30 * DIV
print(f"   gain only: trip {vth/(G_IMON[2]*R_IM_NOM):.3f}-{vth/(G_IMON[0]*R_IM_NOM):.3f} A "
      f"(spread x{G_IMON[2]/G_IMON[0]:.3f})")
print(f"   feasible window needs trip_hi <= {I_OL_MIN:.3f} A and trip_lo >= 1.46 A: ratio {I_OL_MIN/1.46:.3f} available")
# Threshold re-centred on an absolute reference (TLV3011B REF 1.223-1.260 V, divided): spread estimate
ref_spread = 1.260 / 1.223
print(f"   absolute-REF threshold: gain x ref spread = {G_IMON[2]/G_IMON[0]*ref_spread:.3f} before offsets "
      f"(3V3-ratiometric at +/-3 %: {G_IMON[2]/G_IMON[0]*3.4/3.2:.3f})")

# Thermal-regulation current at start-up into a hard short: the eFuse cannot hold I_OL, so U_IM is irrelevant there
for vin in (13.5, 16.0, 21.47):
    for ta in (25.0, 60.0):
        p = (145.0 - ta) / 31.4
        print(f"   start into a hard short, V_IN {vin:5.2f} V, T_A {ta:.0f} C: thermal-regulated current about "
              f"{p/vin:.2f} A (P {p:.1f} W; RthJA 31.4 C/W is the EVM figure, board value BENCH)")
for ta in (25.0, 60.0):
    p = (145.0 - ta) / 31.4
    print(f"   I_OL can be held only while V_IN - V_OUT <= {p/I_OL_MIN:.2f} V at T_A {ta:.0f} C "
          f"(the regime in which U_IM is the only time bound)")

# ---------------------------------------------------------------------------
hdr(2, "eFuse-blocking probe (section 9.7a): module state and timing when the eFuse is bypassed")
T_PROBE_MAX = 0.100        # FC_CHARGE dropped within 100 ms of step 3 (section 9.7a step 5)
T_D_ON = 0.008             # RT1987 D-BC-FC turn-on delay, typical, no maximum (RT1987 DS-00 section 13)
COLD_START = (0.065, 0.170)  # Ag105 cold start to current (facts_prior section 6)
SETTLE = 0.500             # AG105_SETTLE_MS (ino:2484)
print(f"   module input fed by the bypass at most {T_PROBE_MAX - T_D_ON:.3f} s before FC_CHARGE drops "
      f"(t_D_ON {T_D_ON*1e3:.0f} ms typical consumed first)")
print(f"   measured Ag105 cold start {COLD_START[0]*1e3:.0f}-{COLD_START[1]*1e3:.0f} ms; firmware's own settle "
      f"gate {SETTLE*1e3:.0f} ms: the read lands inside the module boot in "
      f"{'every' if T_PROBE_MAX - T_D_ON < COLD_START[1] else 'no'} worst case")
print("   battery side during the probe: FF1 clear -> S_CHG OFF -> Ag105 VBat- (pins 14/15, VBATN_X) open; pin 32 LOW ->")
print("   D-BT-SQ disabled; VBAT+ reaches the pack only through R_KA 1 kOhm (if fitted). Expected GENSTAT: Battery")
print("   Disconnect (Table 6 code 000) = Table 5 mode 2 'Disconnected Battery Error' -> DS p.14: all measures 0xFF.")
print("   Design rule (Table 16): 0xFF / NAK = no evidence. Net: a bypassed eFuse reads 0xFF or NAK -> ERR_EFUSE_BYPASS")
print("   cannot latch in the configuration in which the probe runs (UNCONFIRMED on hardware; no gate injects a bypass).")
v_fc = 16.0
print(f"   expected valid reading if the module did report: {v_fc/0.141:.0f} counts (design 113)")
