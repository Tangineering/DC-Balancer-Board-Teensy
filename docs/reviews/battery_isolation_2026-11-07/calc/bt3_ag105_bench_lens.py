"""Battle-test round 3, Ag105 behaviour and bench-gate lens.

Target: detailed_design_IC1.md revision 5. Stdlib only.
Sections:
  1. eFuse-blocking probe (section 9.7a): validity of reg 0x07 per module status, by R_KA state.
  2. S0-2 rig measurement resolution on the specified 0.5 mOhm external shunt.
  3. Stage-0 rig earth loop across the Ag105 sense (scope ground + USB-referenced I2C master).
  4. Single-bit corruption of the commissioned Ag105 registers (Hamming distance 1).
Every input is cited; ASSUMED values are marked.
"""

def hdr(s):
    print()
    print(s)
    print("-" * len(s))

# ---------------------------------------------------------------- 1
hdr("Section 1. eFuse-blocking probe: is a valid reg 0x07 possible in the probe configuration?")
# Ag105 DS V1.1 p.14 'Measurements': "If the input voltage is below 9 volts or the Ag105 reports an
# error state, for example dropping below MPPT threshold voltage, all measures transmitted will be 0xFF."
# DS p.11 Table 5 (Table5 JSON): mode 2 'Disconnected Battery Error', mode 4 'OC/Regulation Error'.
# DS p.6: 0 V battery -> Bring-Up; no current draw -> battery disconnect status, repeat.
#         battery within 0.2 V/cell of the charge voltage -> fully charged status.
# Design 12.5 item 2: a measurement is valid only in GENSTAT Charging (010) or Fully Charged (011).
# Probe configuration (9.7a): pin 32 LOW -> D-BT-SQ disabled (RT1987 DS-00 s.17: VIN isolated from VOUT);
# the only output path is R_KA 1 kOhm (if fitted, ruling 9).
V_PACK = [7.4, 7.7, 7.99]     # V, FC-window/config-check entry admits V_batt < 8.0 V (design 9.7)
V_CV = 8.4                    # V, reg 0x01 = 0x08 (Table3 JSON)
R_KA = 1000.0                 # Ohm (design 5.3)
I_STBY = (120e-6, 420e-6)     # A, Ag105 DS p.20 row 7 battery standby current
I_SET_FC = 1.25               # A, FC profile (design Table 8)
for rka in (False, True):
    print(f"R_KA fitted = {rka}")
    if not rka:
        print("  VBat+ (VCHG) is floating behind the disabled D-BT-SQ: the module sees 0 V -> Bring-Up;")
        print("  no current can flow -> 'battery disconnect' status (DS p.6) = Table 5 mode 2 'Disconnected")
        print("  Battery Error' -> error state -> all measures 0xFF (DS p.14). GENSTAT 000 is also outside the")
        print("  12.5 item 2 validity set. => reg 0x07 is never valid: the probe CANNOT latch on a bypassed eFuse.")
    else:
        for vp in V_PACK:
            for i_s in I_STBY:
                v_seen = vp - i_s * R_KA
                i_max = (V_CV - vp) / R_KA
                frac = i_max / I_SET_FC
                print(f"  V_pack {vp:.2f} V: unpowered VBat+ {v_seen:.2f} V (standby {i_s*1e6:.0f} uA);"
                      f" max output current through R_KA {i_max*1e3:.2f} mA = {frac*100:.3f} % of I_set"
                      f" (10 % needed to leave Bring-Up/detection, DS p.6)")
        print("  Outcome undocumented: 'fully charged' once VCHG reaches 8.0 V through 1 kOhm (valid),")
        print("  or OC/Regulation Error ('voltage behaviour not expected from a battery', DS p.11) (0xFF, and")
        print("  GENSTAT 101 also trips G3 / FAULT_CHARGER_STAT in the configuration check, design 12.5 item 4).")
print("No step of 9.2/9.7a reads reg 0x07 while EF_EN is HIGH (a positive control), and S0-7 records reg 0x07")
print("only with the input ABSENT. The probe has no demonstrated detection power in either R_KA state.")

# ---------------------------------------------------------------- 2
hdr("Section 2. S0-2 measurement resolution on the 0.5 mOhm rig shunt")
R_EXT = 0.5e-3                # Ohm, design 14.1 'external 0.5 mOhm shunt, scoped at 1 MS/s'
LSB_FS_DIV = 8                # divisions full scale, 8-bit DSO (ASSUMED typical)
for vdiv in (1e-3, 2e-3):
    lsb = LSB_FS_DIV * vdiv / 256
    print(f"  8-bit DSO at {vdiv*1e3:.0f} mV/div: LSB {lsb*1e6:.1f} uV = {lsb/R_EXT*1e3:.0f} mA of pack current")
for label, i in (("S0-2 steady criterion 0.05 A", 0.05),
                 ("criterion margin to the simulator sink limit (I_set+0.3 vs I_set+0.2) 0.10 A", 0.10),
                 ("full regen I_set 1.75 A", 1.75)):
    print(f"  {label}: {i*R_EXT*1e6:.1f} uV on the shunt")
RIPPLE_PP = 0.300             # A p-p max at 2.5 A, Ag105 DS p.20 row 13
print(f"  Ag105 ripple current {RIPPLE_PP:.2f} A p-p (DS p.20 row 13): {RIPPLE_PP*R_EXT*1e6:.0f} uV p-p on the shunt")
print("  => the 0.05 A agreement is below one LSB; the 0.10 A blind-module margin is 1.6-3.2 LSB under")
print("     3x larger converter ripple; a blind module clamped by a simulator sinking at I_set+0.3 A differs")
print("     from a passing one by 0.10 A, which this chain cannot resolve.")
for r in (10e-3, 20e-3):
    print(f"  alternative rig shunt {r*1e3:.0f} mOhm: 0.05 A -> {0.05*r*1e3:.2f} mV; loss at 2.5 A {2.5**2*r*1e3:.0f} mW")

# ---------------------------------------------------------------- 3
hdr("Section 3. Stage-0 rig earth loop across the Ag105 sense")
# Rig (design 14.1): lab supply on Vin+ via CB; module Vin- is the rig reference; reg 0x06 needs an I2C master
# referenced to Vin- (Ag105 DS p.12: interface referenced to Vin-). A USB-powered master (Teensy) ties Vin- to
# the host earth (design 4.2 rule C2 states this for PCB GND). A single-ended scope ground on the VBat- end of the
# external shunt ties VBat- to earth. The loop parallels the sense (VBat- -> sense -> Vin-).
R_S = (0.020, 0.050, 0.100)   # Ohm, Ag105 sense: TODO(verify: Silvertel), S0-1; range ASSUMED
R_LOOP = (0.1, 0.3, 1.0)      # Ohm, scope ground lead + mains earth + USB ground return: ASSUMED
I_SET = 1.75; I_L = 0.6       # A, regen profile and working I_L (design Table 8)
for rs in R_S:
    for rl in R_LOOP:
        f_byp = rs / (rs + rl)        # share of pack current that bypasses the sense
        i_p = I_SET / (1 - f_byp)     # module regulates its sense share to I_set
        i_o = i_p + I_L
        print(f"  R_s {rs*1e3:3.0f} mOhm, R_loop {rl:.1f} Ohm: bypass {f_byp*100:5.1f} %, pack {i_p:.2f} A,"
              f" module output {i_o:.2f} A (rating 2.5 A), reg06 under-reads by {f_byp*100:.1f} %")
print("  S0-2 criterion: agreement within max(0.05 A, 10 %). Bypass shares above 10 % produce a false NO-GO of")
print("  the regulation layer, and drive the qualification unit Q above the 2.5 A output rating (D-3(a) envelope).")

# ---------------------------------------------------------------- 4
hdr("Section 4. Single-bit corruption of the commissioned registers")
# Table3/Table4 JSON; DS p.14 Table 8: codes above 0x0C default to 1000 mA / 4.2 V.
v_codes = {1: "1S 3.9", 2: "1S 4.0", 3: "1S 4.1", 4: "1S 4.2", 5: "2S 7.8", 6: "2S 8.0", 7: "2S 8.2",
           8: "2S 8.4", 9: "3S 11.7", 10: "3S 12.0", 11: "3S 12.3", 12: "3S 12.6"}
i_codes = {1: 2500, 2: 2000, 3: 1750, 4: 1500, 5: 1250, 6: 1000, 7: 750, 8: 500, 9: 250, 10: 200,
           11: 150, 12: 100}
for name, val, table, dflt, zero in (("reg 0x01", 0x08, v_codes, "4.2 V default (Table 8)", "resistor mode, VSEL open: 4.2 V"),
                                      ("reg 0x00", 0x00, i_codes, "1000 mA default (Table 8)", "resistor mode")):
    print(f"  {name} = 0x{val:02X}:")
    for b in range(8):
        v = val ^ (1 << b)
        if v == 0:
            d = zero
        elif v in table:
            d = table[v]
        else:
            d = dflt
        print(f"    bit {b} flipped -> 0x{v:02X}: {d}")
print("  reg 0x01: three of eight single-bit errors (0x09, 0x0A, 0x0C) select a 3S charge voltage.")
