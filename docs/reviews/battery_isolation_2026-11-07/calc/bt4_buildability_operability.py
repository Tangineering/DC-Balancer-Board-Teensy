"""Battle-test round 4, buildability and operability lens (revision 6 delta).

Every input is a value stated in detailed_design_IC1.md rev 6, the BRD, the SCH or the firmware; each is cited
inline. Output: bt4_buildability_operability_output.txt.
"""
import math

def hdr(s):
    print("\n[" + s + "]")

# ---------------------------------------------------------------- 1. BRD geometry at the BQ29200 (M16)
hdr("1 BRD geometry at the BQ29200 (M16 clamp landing)")
# BRD signal wires/element origins (references/Scale Car Board PCB 20260625.brd, signals VMID, VC1, VC1_CB, GND)
RB3_pad1_VMID = (18.2885, 28.448)    # VMID wire endpoint at RB3 pad 1
RB3_pad2_VC1 = (19.3035, 28.448)     # VC1 wire endpoint at RB3 pad 2
RB1A_pad1_VMID = (20.828, 27.4325)   # VMID wire endpoint at RB1A pad 1
RB1A_pad2_VC1CB = (20.828, 28.4475)  # VC1_CB wire endpoint at RB1A pad 2
CBL2_pad1_VC1 = (19.3166, 30.226)    # VC1 wire endpoint at CBL2 pad 1
CBL2_origin = (18.542, 30.226)       # element, 0603 R180 -> pad 2 (GND) mirrored about origin
CBL2_pad2_GND = (2 * CBL2_origin[0] - CBL2_pad1_VC1[0], 30.226)
GND_via = (20.066, 29.21)            # GND signal via, drill 0.35
Ag105_body_ymin = 34.5               # design section 5.5 (DS Fig. 11 body)
d = lambda a, b: math.hypot(a[0] - b[0], a[1] - b[1])
print("RB3 and RB1A package RESC1005X40 (0402); BQ29200 DRB 8-SON; CBL2 CAPC1608X85 (0603)")
print("RB3 pad pitch (VMID pad to VC1 pad)   %.3f mm" % d(RB3_pad1_VMID, RB3_pad2_VC1))
print("RB1A pad pitch (VMID pad to VC1_CB)   %.3f mm" % d(RB1A_pad1_VMID, RB1A_pad2_VC1CB))
print("D_VC1 as specified: RB3 pad2 -> CBL2 pad2 (GND) %.2f mm; alternative across CBL2 itself %.2f mm"
      % (d(RB3_pad2_VC1, CBL2_pad2_GND), d(CBL2_pad1_VC1, CBL2_pad2_GND)))
print("D_VCB: RB1A pad2 -> CBL2 pad2 %.2f mm (crosses the VC1 trace at x=19.32); -> GND via (20.066,29.21) %.2f mm"
      % (d(RB1A_pad2_VC1CB, CBL2_pad2_GND), d(RB1A_pad2_VC1CB, GND_via)))
print("clearance BQ29200 group (y<=32.3) to Ag105 body edge (y=34.5): %.1f mm; GND pour solid, thermals=no (BRD)"
      % (Ag105_body_ymin - 32.3))
# bridge of a clamp anode (GND) to the adjacent VMID pad bypasses RB3/RB1A
V_cell = 4.2
for R_loop in (0.05, 0.2, 0.5):   # ASSUMED balance-lead + trace + joint resistance, Ohm
    print("anode-to-VMID bridge, R_loop %.2f Ohm ASSUMED: cell-1 short %.0f A (no fuse in the balance lead)"
          % (R_loop, V_cell / R_loop))
# C-1 diode-mode reverse reading with such a bridge: DMM sees RB3 260 Ohm || RB1A 100 Ohm in both directions
I_dmm = 1e-3   # ASSUMED typical DMM diode-test current
print("C-1 diode test with a VMID bridge, balance plug out: GND->VC1 reads RB3 = %.2f V both directions;"
      " GND->VC1_CB reads RB1A = %.2f V both directions (reverse is not open -> C-1 catches it)"
      % (I_dmm * 260, I_dmm * 100))

# ---------------------------------------------------------------- 2. F50 in Stage 2: Q_MD stuck ON in a regen window
hdr("2 F50 (Q_MD D-S short or U_MDI stuck HIGH) in a Stage-2 regen window")
R_MD = 15.0                         # design Table 7
UIM_lo, UIM_hi = 1.51, 1.98         # design section 5.2 (calc6 s5)
inrush_max = 0.6                    # S0-11 GO criterion
I_q_mod = 0.018                     # Ag105 DS p.20 row 4 maximum (design 5.3)
pulse_on = (0.019, 0.047)           # design 7.8 / S0-2b pulse families
period = 0.535
n_per_window = 56                   # design Table 7 (CC-18)
win = 30.0
P_design_mean = 0.095               # Table 7 R_MD mean, healthy
for V in (17.2, 18.0, 21.35, 21.5):  # VOK band of V-MOT (V2-1) up to the 21.5 V dump figure
    I_md = V / R_MD
    steady = I_md + I_q_mod
    peak_ramp_end = I_md + inrush_max
    print("V %.2f V: R_MD %.3f A; steady eFuse input %.3f A (U_IM min %.2f: %s); ramp-end peak %.3f A (%s)"
          % (V, I_md, steady, UIM_lo, "NO trip" if steady < UIM_lo else "trip",
             peak_ramp_end, "may trip, unit-dependent" if UIM_lo <= peak_ramp_end <= UIM_hi
             else ("trips" if peak_ramp_end > UIM_hi else "no trip")))
print("module boot 65-170 ms vs pulse 19-47 ms (design CC-16): the module draws ~I_q inside a pulse,"
      " so the module term does not lift the input above U_IM")
V = 21.5
for t in pulse_on:
    E = V ** 2 / R_MD * t
    print("pulse %2d ms: %.2f J per pulse in R_MD (healthy dump 0.051 J); window mean %.2f W"
          " (x%.0f the 0.095 W design mean) over %d pulses / %.0f s"
          % (t * 1e3, E, E / period, E / period / P_design_mean, n_per_window, win))
print("pin-8 positive control: node fed by the eFuse -> pin 8 HIGH -> passes; ERR_MOD_DRAIN: dump works -> passes")
# FC-window case: OC_FC single raw sample 1.4 A bus side (ino:2090, ino:669)
I_aux = 0.15
print("FC window 16 V: R_MD %.3f A + aux %.2f A = %.3f A; + inrush up to 0.6 A -> above OC_FC 1.4 A at the first"
      " window (State 99): Stage 1 is covered by OC_FC, not by U_IM as row F50 states" % (16 / R_MD, I_aux,
                                                                                         16 / R_MD + I_aux))
# PTC-in-series discriminator (proposed fix): rms current
t_dump = 0.0016  # ~ one tau from 21.5 V at 100 uF (calc6 s3 tau 1.52 ms)
rms_healthy = 1.43 * math.sqrt(t_dump / period / 2)
rms_stuck = 1.43 * math.sqrt(0.047 / period)
print("rms through R_MD over a window: healthy %.3f A, stuck-on (47 ms pulses) %.3f A (x%.1f)"
      % (rms_healthy, rms_stuck, rms_stuck / rms_healthy))

# ---------------------------------------------------------------- 3. C-2 'U_MS threshold against a ramped supply on VCHG-IN_M'
hdr("3 C-2 U_MS threshold ramp with Q_MD on (bonded, EF_EN L)")
R_MB = 3300.0
R_MS = 116.2e3
R_load = 1 / (1 / R_MD + 1 / R_MB + 1 / R_MS)
for V in (8.69, 9.15, 9.5):
    print("ramp at %.2f V: load %.3f A, R_MD %.2f W (2512 continuous ~1 W class, TODO(select))"
          % (V, V / R_load, V ** 2 / R_MD))
for I_lim in (0.1, 0.5):
    print("current-limited supply %.1f A: node cannot exceed %.2f V (threshold not reachable)" % (I_lim, I_lim * R_load))
E_ramp = sum((v * 0.01) ** 2 / R_MD * 0.01 for v in range(0, 950))  # 0 -> 9.5 V in 9.5 s
print("0 -> 9.5 V ramp over 9.5 s with Q_MD on: %.1f J into R_MD (healthy dump 0.051 J, probe cap 1.71 J)" % E_ramp)

# ---------------------------------------------------------------- 4. pin-8 sink with RENC2
hdr("4 Pin 8 (ENC_B net) LOW-level load on U_MS")
for renc in (2200.0, 4700.0):        # 4.7k as designed (SCH/BRD RENC2), 2.2k per the 2026-08-16 bodge record
    R_pu = 1 / (1 / renc + 1 / 10e3 + 1 / 22e3)   # + R_UMS 10k + Teensy INPUT_PULLUP (22k ASSUMED)
    print("RENC2 %.1fk: U_MS sinks %.2f mA at 3.3 V" % (renc / 1e3, 3.3 / R_pu * 1e3))
print("U_MS V_OL at that sink: TODO(verify: SBOS300C); Teensy V_IL max TODO(verify: IMXRT1060 datasheet)")

# ---------------------------------------------------------------- 5. Gate order vs prerequisites
hdr("5 Section 15 listed order vs prerequisites")
listed = ["S0-*", "D-1", "D-2", "D-3", "B2", "BG-17", "B13", "P8", "JBL", "P-M1",
          "C-1", "C-1b", "C-1c", "C-2", "C-1d", "C-2b", "B10", "B11*", "B8", "B-FPK", "B-PKN", "ST", "T1", "T2",
          "C-3", "W0", "W1", "W2", "C-4"]
needs = {
    "D-3": "after M1, M2, M13, M16 (all Stage-1 rework) -> cannot be 'pre-rework'",
    "P-M1": "after M1 and F_VX (CB fitted)",
    "B-FPK": "F_PK at its M14 position (Stage-1 harness)",
    "B-PKN": "SB and R_SH (Stage-1), M16 clamps, and C-1 clamp-orientation check before any balance-plug connection",
    "C-2": "contains fed-exit items (pin-8 drain, ERR_MOD_DRAIN, V_chg after a window) that need a powered module;"
           " commissioning step 1 requires C-2 to pass first, and an un-commissioned module latches ERR_AG105_CFG",
}
for g in listed:
    if g in needs:
        print("%-6s at position %2d: %s" % (g, listed.index(g) + 1, needs[g]))
print("commissioning 9.2 step 1 prerequisites: C-1, C-1b, C-1c, C-2, P8, B-FPK, B-PKN, BG-17, D-3 (C-1d not listed)")
