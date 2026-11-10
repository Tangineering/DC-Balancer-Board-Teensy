"""Battle-test round 1, datasheet lens: checks of detailed_design_IC1.md revision 3.

Stdlib only. Every constant is cited. Run:
    .venv_hil/Scripts/python.exe docs/reviews/battery_isolation_2026-11-07/calc/bt1_datasheet_lens_calcs.py
"""
import math


def hdr(n, t):
    print("\n" + "=" * 78 + f"\nSection {n}: {t}\n" + "=" * 78)


# ---------------------------------------------------------------------------
hdr(1, "N1 (/CLR of U_FF) with Teensy pin 33 high-Z (reset, brownout, boot)")
# Design Figure 2: 3V3 - R_N1 10k - N1 - D_N33 (anode N1) - pin33 node - R_P33 10k - GND
# BAT54 VF: 0.24 V max at 0.1 mA, 0.32 V max at 1 mA (onsemi BAT54LT1/D, cited by design Table 7)
# SN74LVC1G74 SCES794G sec 6.3: VCC 3.0-3.6 V -> VIH min 2.0 V, VIL max 0.8 V
for v33 in (3.0, 3.3, 3.6):
    for vf in (0.15, 0.24):
        i = (v33 - vf) / 20e3
        n1 = v33 - 10e3 * i
        print(f"   3V3 {v33:.1f} V, VF {vf:.2f} V: I {i*1e3:.3f} mA, N1 = {n1:.2f} V "
              f"(VIL max 0.8 V, VIH min 2.0 V) -> {'LOW' if n1 < 0.8 else ('HIGH' if n1 > 2.0 else 'UNDEFINED')}")
print("   => pin 33 high-Z does NOT clear FF1; the clear relies on PUMP_OK, which decays in 43-76 ms "
      "(design calc section 4).")

# ---------------------------------------------------------------------------
hdr(2, "U_FF CLK and /CLR edges when pin 33 rises (set race, input slew)")
# CLK: R_CK 1k, C_CK 1 nF (Figure 2) -> tau 1.0 us
tau_clk = 1e3 * 1e-9
# N1 rises through R_N1 10k into the net capacitance: 5 BAT54 (D_N33, D_NP, D_NC1, D_NC2, D_N20),
# CT 10 pF max each (BAT54LT1/D); Q_D5 and Q_OV drains, BSS138 Coss 13 pF typ (onsemi BSS138/D);
# U_FF input about 4 pF; wiring about 10 pF (estimate).  UNCONFIRMED total; range given.
for c_n1 in (60e-12, 90e-12, 120e-12):
    tau_n1 = 10e3 * c_n1
    # N1 starts at about 0.25 V (diode-clamped LOW); must reach VIH 2.0 V at 3.3 V
    t_clr = -tau_n1 * math.log(1 - (2.0 - 0.25) / (3.3 - 0.25))
    # LVC CLK switching point taken as VCC/2 (non-Schmitt input); range VIL..VIH
    t_clk_mid = -tau_clk * math.log(1 - 1.65 / 3.3)
    t_clk_lo = -tau_clk * math.log(1 - 0.8 / 3.3)
    print(f"   C_N1 {c_n1*1e12:.0f} pF: /CLR reaches VIH at {t_clr*1e6:.2f} us; CLK crosses 0.8 V at "
          f"{t_clk_lo*1e6:.2f} us and VCC/2 at {t_clk_mid*1e6:.2f} us -> "
          f"{'CLK edge BEFORE /CLR released (set may fail)' if t_clk_mid < t_clr else 'ok'}")
# Input transition rate: SCES794G sec 6.3, dt/dv max 10 ns/V at VCC 3.3 V +/- 0.3 V
slope_clk = (3.3 / tau_clk) * math.exp(-0.69)          # V/s at the VCC/2 crossing
print(f"   CLK slope at threshold {slope_clk/1e6:.2f} V/us = {1e9/slope_clk:.0f} ns/V vs 10 ns/V max "
      f"(x{(1e9/slope_clk)/10:.0f})")
slope_n1 = (3.05 / (10e3 * 90e-12)) * math.exp(-0.6)
print(f"   /CLR slope (90 pF) {1e9/slope_n1:.0f} ns/V vs 10 ns/V max (x{(1e9/slope_n1)/10:.0f})")

# ---------------------------------------------------------------------------
hdr(3, "Q_D interlock threshold referred to the S_GND gate; exit overlap")
# DQ = (Vg - VF) * R_PDD / (R_D + R_PDD); R_D 47k, R_PDD 100k (Figure 1)
# BSS138 VGS(th) 0.8 / 1.3 / 1.5 V (design Table 7, onsemi BSS138/D)
# CSD18510Q5B VGS(th) 1.2 / 1.7 / 2.3 V (SLPS632 sec 5.1, re-read this round)
k = 100 / 147
for vth_qd in (0.8, 1.3, 1.5):
    vg = vth_qd / k + 0.25
    print(f"   Q_D Vth {vth_qd:.1f} V -> S_GND gate must exceed {vg:.2f} V before Q_D starts to clamp S_CHG")
print("   Design eq. 7 states the threshold as 0.8-1.5 V on the gate; the gate-referred range is 1.43-2.46 V,")
print("   which overlaps the CSD18510Q5B conduction region (VGS(th) 1.2-2.3 V).")
# Exit: S_GND gate rises tau 88-114 us to ~6.3 V (design Table 11, eq. 14).
# Q_C gate discharges via R_CQ 10k into C_CQ 10 nF from ~3.0 V; Q_B stays ON until Q_C turns off.
for tau_g in (88e-6, 114e-6):
    t_cond = -tau_g * math.log(1 - 1.2 / 6.3)           # S_GND begins to conduct (Vth min)
    t_qd_strong = -tau_g * math.log(1 - 2.75 / 6.3)     # Q_D overdrive ~0.2 V at Vth 1.5 V
    print(f"   gate tau {tau_g*1e6:.0f} us: S_GND conducts from {t_cond*1e6:.0f} us; Q_D strong "
          f"(gate 2.75 V) at {t_qd_strong*1e6:.0f} us")
for vth_qc in (0.8, 1.5):
    t_qc = 100e-6 * math.log(3.0 / vth_qc)
    print(f"   Q_C (Vth {vth_qc} V) turns off at {t_qc*1e6:.0f} us -> Q_B sources {8.5/1e3*1e3:.1f} mA into G3 "
          f"through R_B3 1k until then")
# Q_D must hold G3 below S_CHG Vth min 1.2 V against Q_B: R_DS(Q_D) < 1k*1.2/(8.5-1.2)
print(f"   Q_D R_DS needed to hold G3 < 1.2 V against Q_B: {1e3*1.2/(8.5-1.2):.0f} Ohm")

# ---------------------------------------------------------------------------
hdr(4, "BQ29200 cell-1 reference shift in the charge mode")
# SLUSA52C sec 7.5: OVP when (VC2-VC1) or (VC1-GND) > VPROTECT; bq29200 VPROTECT 4.35 V;
# VOA +/-10 mV at 25 C; drift +/-0.6 mV/C (-40..110 C).  GND pin = PCB GND (facts_board 2.2, 2.3).
VPROT = 4.35
for vcell in (4.20, 4.25):
    for off in (0.03, 0.06, 0.10, 0.15, 0.40):
        read = vcell + off
        print(f"   cell1 {vcell:.2f} V, PACK- above GND by {off*1e3:3.0f} mV -> VC1-GND {read:.2f} V "
              f"{'>= VPROTECT: false OVP trip' if read >= VPROT - 0.010 else ''}")
# Non-sense part of the charge-mode return: R_SH 0.5 mOhm + S_CHG 1.6 mOhm max (4.5 V) +
# 0.5 mm2 VBATN_X lead ~0.3 m at 34.5 mOhm/m (copper, estimate) -> ~12.5 mOhm; Ag105 sense: unknown
r_known = 0.5e-3 + 1.6e-3 + 0.3 * 34.5e-3
print(f"   known series part {r_known*1e3:.1f} mOhm x 1.75 A = {r_known*1.75*1e3:.0f} mV before the Ag105 sense drop")
print("   Negative direction: design states PACK- down to -1.0 V -> cell 1 under-read by up to 1.0 V (OVP blind).")
# CD delay: XDELAY 6-12 s/uF (0-60 C), 5.5-13.5 s/uF (-40..110 C); CBLD 330 nF (facts_board 2.3);
# recommended CCD max 0.1 uF (SLUSA52C sec 7.3)
for lo, hi, lab in ((6, 12, "0-60 C"), (5.5, 13.5, "-40..110 C")):
    print(f"   CD 0.33 uF, XDELAY {lo}-{hi} s/uF ({lab}): {0.33*lo:.2f}-{0.33*hi:.2f} s (cap tolerance excluded)")

# ---------------------------------------------------------------------------
hdr(5, "U_C1/U_C2 trip error terms omitted from calc section 6")
# TLV3011B SBOS300C 6.9: VOS specified at VCM = V- only; CMRR 54 dB min over the full CM range (VS 5.5 V)
cmrr = 10 ** (-54 / 20)
K = 100 * 0.5e-3   # INA240A3 x 0.5 mOhm = 50 mV/A
for name, vcm in (("U_C1", 1.50), ("U_C2", 1.807)):
    dv = cmrr * vcm
    print(f"   {name}: VCM {vcm:.2f} V x CMRR 54 dB = {dv*1e3:.1f} mV = {dv/K:.3f} A extra")
# 3V3 tolerance: SIG = 3V3/2 + 50 mV/A * I ; TH = 3V3 * ratio -> I_trip proportional to 3V3
for name, ratio in (("U_C1", 10.0 / 22.0), ("U_C2", 12.1 / 22.1)):
    for v in (3.2, 3.3, 3.4):
        print(f"   {name}: 3V3 = {v:.1f} V -> trip {abs(v*(ratio-0.5))/K:.3f} A")

# ---------------------------------------------------------------------------
hdr(6, "MPPTS resistor law sensitivity (Ag105 DS p.10, 'approximate resistance')")
def v_mppt(r):
    return 47 - 36 / (r / 20e3 - 1)
r0 = 41.7e3
for frac in (-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03):
    print(f"   effective R {frac*100:+.0f} %: {v_mppt(r0*(1+frac)):.2f} V")
print(f"   slope {(v_mppt(r0*1.001)-v_mppt(r0*0.999))/(r0*0.002)*1e3:.2f} V/kOhm "
      f"({(v_mppt(r0*1.01)-v_mppt(r0))/v_mppt(r0)*100:.1f} % of V per 1 % of R)")
print("   FC window input 15.92 V (design calc section 3): threshold reaches it at effective R "
      f"{20e3*(36/(47-15.92)+1)/1e3:.2f} k (+{(20e3*(36/(47-15.92)+1)/r0-1)*100:.1f} %)")

# ---------------------------------------------------------------------------
hdr(7, "eFuse UVLO against the Ag105 input minimum")
# R_UV1 100k / R_UV2 13.0k; SLVSE94G 6.5: VUVLOR 1.176-1.224 V, VUVLOF 1.09-1.15 V
r = 113.0 / 13.0
print(f"   eFuse on  {1.176*r:.2f}-{1.224*r:.2f} V; off {1.09*r:.2f}-{1.15*r:.2f} V")
print("   Ag105 DS p.19: VIN recommended min 11 V; VLOCK 11 V (typ column only)")
