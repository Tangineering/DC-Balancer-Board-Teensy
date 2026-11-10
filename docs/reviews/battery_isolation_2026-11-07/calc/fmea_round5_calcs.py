"""Battle-test round 5 (delta FMEA on the revision-7 changes of detailed_design_IC1.md).

Stdlib only. Every input is a value stated in detailed_design_IC1.md revision 7, in its calc
scripts (calc7 = ic1_rev7_calcs_output.txt, bt4_logic_seq_enum_output.txt), in SLUSA52C
(references/Datasheets/BQ29200_TI.pdf) or in the firmware; ASSUMED values are marked.

Sections:
  1  ERR_MOD_SENSE (c) exit hold check between regen pulses (stale V_chg residual, node already cold)
  2  ERR_MOD_SENSE (c) during a pulse: healthy node fall time vs the 150 us sample
  3  D_VC1 specification feasibility: V_F <= 0.25 V at 16.2 mA at the cold end vs I_R <= 40 uA hot
  4  VC1 tap flying-lead chafe: current into Teensy pin 20 (no LB-side series element)
  5  ERR_CELL_MISMATCH: V_BT (pin 25) error with no pin-25 calibration, over the design's 3V3 range
  6  ERR_IPACK_PLAUS gain band: I_L,cal ambiguity (B8 stores the total VBT load incl. the BT boost input)
"""
import math

print("=" * 100)
print("[1] ERR_MOD_SENSE (c): exit hold check on a commanded exit between VOK pulses")
print("=" * 100)
# Design 9.5 exit step 1 / Table 16 (c): check runs when pin 8 has read HIGH in this window and
# V_chg >= 13.5 V on the last settled reading before the write. No condition on EF_EN or on pin 8 at the write.
# VCHG-IN after a VOK release holds on ~20 uF with tau 0.984 s (calc7 s5; bt4_logic_seq_enum s3).
tau = 0.984
releases = [16.13, 16.43]          # V at release (calc7 section 5)
period_cases = [(14.0, 0.523, 0.147), (15.0, 0.535, 0.183), (16.0, 0.523, 0.192),
                (17.0, 0.535, 0.223), (20.0, 0.562, 0.294)]  # (decay V/s, spacing s, off-span s) bt4 s3
for vrel in releases:
    t_hold = tau * math.log(vrel / 13.5)
    print(f"  release {vrel:.2f} V: V_chg stays >= 13.5 V for {t_hold*1000:.0f} ms after the release (tau {tau} s)")
for tau_k in (0.9, 1.0, 1.1, 1.2):
    t_hold = tau * tau_k * math.log(16.13 / 13.5)
    print(f"  tau x{tau_k:.1f}: hold >= 13.5 V for {t_hold*1000:.0f} ms (release 16.13 V)")
print("  The module node is dumped below 8.67-9.17 V within 1.3-2.9 ms of the release (Q_MD on, EF_EN L, calc6 s3),")
print("  so pin 8 is already LOW at the exit write; the 50 us sample reads LOW -> ERR_MOD_SENSE (c) latches.")
print("  Fraction of the window time in which a commanded exit meets the trigger but the node is cold:")
for decay, sp, off in period_cases:
    exposed = 0.0
    for vrel in releases:
        t_hold = tau * math.log(vrel / 13.5)
        exposed = max(exposed, min(off, t_hold) - 0.003)  # minus the 1.3-2.9 ms dump
    print(f"    decay {decay:4.1f} V/s spacing {sp:.3f} s off-span {off:.3f} s: exposed {exposed*1000:5.0f} ms "
          f"= {100*exposed/sp:4.1f} % of the period")
# exit after the 200 ms release dwell (brake demand ended): residual depends on the time since the last release
for dt in (0.20, 0.22, 0.25):
    for vrel in releases:
        for tau_k in (1.0, 1.1):
            v = vrel * math.exp(-dt / (tau * tau_k))
            print(f"  release-dwell exit {dt*1000:.0f} ms after the last release, release {vrel:.2f} V, tau x{tau_k}: "
                  f"V_chg {v:.2f} V -> {'CHECK RUNS (false latch)' if v >= 13.5 else 'not evaluated'}")
# probability that at least one of N traction-request exits falls in the exposed interval
for p in (0.25, 0.30, 0.36):
    for n in (1, 3, 5, 10):
        print(f"    p_exposed {p:.2f}, {n:2d} random-time exits per power cycle: P(at least one false latch) = "
              f"{1-(1-p)**n:.2f}")
print("  Probe (9.7a step 5): the feed drop follows step 3 (V_chg >= 13.5 V on two settled reads) and step 4 (pin 8")
print("  LOW = pass) in a check whose positive control read pin 8 HIGH: the Table 16 (c) trigger is met and the")
print("  healthy probe result itself (pin 8 LOW) latches (c) and voids the probe, unless the probe drop is excluded.")

print()
print("=" * 100)
print("[2] ERR_MOD_SENSE (c) during a pulse (node fed): time for the node to fall below the U_MS threshold")
print("=" * 100)
# dV/dt = -(V/R_MD + V/R_MB + P/V [above 11 V lockout, else I_idle]) / C
R_MD, R_MB = 15.0, 3300.0
def fall_time(v0, c, p_w, vth, i_idle=0.018, dt=1e-7):
    v, t = v0, 0.0
    while v > vth and t < 0.05:
        i = v / R_MD + v / R_MB + (p_w / v if v > 11.0 else i_idle)
        v -= i / c * dt
        t += dt
    return t
for v0 in (13.5, 15.0, 16.0):
    for c in (47e-6, 100e-6, 221e-6):
        for p in (0.0, 16.7, 22.7):
            t = fall_time(v0, c, p, 9.17)
            flag = "LOW by 150 us (false latch)" if t < 150e-6 else ("LOW by 50 us" if t < 50e-6 else "ok")
            print(f"  V0 {v0:4.1f} V C_mod {c*1e6:5.0f} uF P_in {p:4.1f} W: fall to 9.17 V in {t*1e6:6.0f} us  {flag}")
print("  C_mod 100-221 uF is the design's range (calc6 s3); 47 uF ASSUMED as a lower-than-stated case. P_in 16.7 W =")
print("  1.75 A x 8.4 V / 0.88; 22.7 W = the 8.0 V entry-gate cap (design 7.1). calc7 s6 used 13.5 V, 100 uF, 1.0 A.")

print()
print("=" * 100)
print("[3] D_VC1: V_F <= 0.25 V at 16.2 mA at T_cold together with I_R(4.2 V) <= 40 uA at T_hot")
print("=" * 100)
# Thermionic Schottky: I_S(T) = K T^2 exp(-phi/(k T)); V_F = n Vt ln(I/I_S) (series R ignored: optimistic).
# Reverse leakage at 4.2 V taken as I_R >= I_S (barrier lowering ignored: optimistic).
kB = 8.617e-5
def i_s_ratio(t1, t2, phi):
    return (t2 / t1) ** 2 * math.exp(-phi / kB * (1 / t2 - 1 / t1))
I_F, VF_MAX, IR_MAX = 16.2e-3, 0.25, 40e-6
for n in (1.0, 1.05, 1.1):
    for phi in (0.35, 0.45, 0.55, 0.65):
        for tc_c in (-20.0, 0.0, 10.0):
            tc = tc_c + 273.15
            vt = kB * tc
            is_cold_min = I_F * math.exp(-VF_MAX / (n * vt))
            # find the hottest T at which I_S(T) still <= 40 uA
            th_c = None
            for t_c in [x * 0.5 for x in range(-40, 300)]:
                if is_cold_min * i_s_ratio(tc, t_c + 273.15, phi) > IR_MAX:
                    th_c = t_c
                    break
            ir85 = is_cold_min * i_s_ratio(tc, 358.15, phi)
            ir60 = is_cold_min * i_s_ratio(tc, 333.15, phi)
            print(f"  n {n:.2f} phi_B {phi:.2f} eV T_cold {tc_c:5.1f} C: I_S(T_cold) >= {is_cold_min*1e9:8.1f} nA; "
                  f"I_R >= {ir60*1e6:7.1f} uA at 60 C, {ir85*1e6:7.1f} uA at 85 C; 40 uA exceeded above "
                  f"{th_c if th_c is not None else '>150'} C")
print("  calc7 s3 evaluated the V_F limit at 25 C only (I_S >= 0.96-2.33 uA at 25 C) although Table 7 states it")
print("  'over -20 to 85 C'. VC1 error = I_R x RB3 (261 Ohm, calc7 s2); ERR_CELL_MISMATCH sees 2x; latch at ~75 uA.")
for ir in (40e-6, 75e-6, 150e-6, 300e-6):
    print(f"    I_R {ir*1e6:5.0f} uA: VC1 low by {ir*261*1e3:5.1f} mV (BQ29200 cell-1 OVP late by the same); "
          f"mismatch term {2*ir*261*1e3:5.1f} mV")

print()
print("=" * 100)
print("[4] VC1 tap lead chafe: pin 20 sits directly on the lead (R_VC1a is at the VC1 end, R_VC1b to GND on LB)")
print("=" * 100)
# i.MX RT1062 GPIO absolute maximum ~ NVCC_GPIO + 0.3 V = 3.6 V: TODO(verify: IMXRT1060CEC table 'Absolute maximum')
VCLAMP = 3.6  # ASSUMED clamp onset (calc7 s2 uses the same 3.6 V)
for name, v, r_src in (("VBT (pack, 8.5 V)", 8.5, 0.05), ("VBUS 16.0 V", 16.0, 0.05),
                       ("VBUS 17.5 V", 17.5, 0.05), ("VCHG-IN_M 21.5 V", 21.5, 0.5)):
    i_direct = (v - VCLAMP) / (r_src + 1.0)   # 1 Ohm ASSUMED ESD-structure + lead resistance
    print(f"  chafe to {name}: no LB-side series element -> pin 20 forced to {v} V; clamp current ~ {i_direct:6.1f} A "
          f"(limited only by the source, the lead and the ESD structure, 1 Ohm ASSUMED)")
    for rs in (10e3, 22e3, 47e3):
        print(f"      with a series {rs/1e3:.0f} kOhm at the LB entry: {(v-VCLAMP)/rs*1e3:5.2f} mA injected")
print("  The design's F54 bound '<= 42.5 uA through R_VC1a' is the current drawn FROM VC1; it is not the pin-20 stress.")
# divider impact of an LB-side series resistor with the tap read through it into 100 nF (ADC load negligible)
print("  A series R at the pin with C_VC1 on the pin side keeps the 10 ms filter; the DC divider is unchanged.")

print()
print("=" * 100)
print("[5] ERR_CELL_MISMATCH: V_BT (pin 25) error when only the VC1 tap is two-point calibrated")
print("=" * 100)
# Firmware: V_batt = analogRead(BT_VOLTAGE) * SCALE_V_BATT, SCALE_V_BATT = ADC_VREF*(16.2+10)/10/ADC_MAX with
# ADC_VREF = 3.3 nominal (ino:2025-2026, ino:7030). Divider resistors 0.1 % (BOM lines 60-61).
# The VC1 channel is calibrated against a DMM (C-2a item 5), which absorbs the true 3V3; V_BT is not (Table 19).
for v3 in (3.20, 3.25, 3.28, 3.30, 3.32, 3.35, 3.40):
    for vbt in (7.4, 8.4):
        err = vbt * (3.30 / v3 - 1.0)
        div = vbt * 2 * 0.001 * 16.2 / 26.2
        print(f"  3V3 {v3:.2f} V, V_BT {vbt}: pin-25 reading error {err*1e3:+7.1f} mV (+/-{div*1e3:.1f} mV divider) "
              f"-> {'exceeds' if abs(err) > 0.080 else 'within'} the 80 mV threshold before any real imbalance")
print("  The design's own U_IM analysis uses 3V3 = 3.2-3.4 V (section 5.2); calc7 s2 ASSUMED 5 mV 'after two-point")
print("  cal' for V_BT, but no gate calibrates pin 25 (Table 19 item 5 calibrates the VC1 tap only).")
# the 3V3 band that keeps the uncalibrated V_BT error inside the 38.5 mV margin
for vbt in (7.4, 8.4):
    lo = 3.30 / (1 + 0.0385 / vbt)
    hi = 3.30 / (1 - 0.0385 / vbt)
    print(f"  V_BT {vbt}: margin 38.5 mV holds only for 3V3 in {lo:.4f}-{hi:.4f} V (+/-{(hi-lo)/2/3.3*100:.2f} %)")

print()
print("=" * 100)
print("[6] ERR_IPACK_PLAUS gain band with I_L,cal taken from gate B8 (State 99 response)")
print("=" * 100)
# Band: I_PACK1 / (BT_CURRENT x V_bus / (eta_cal x V_batt) + I_L,cal) outside 0.75-1.30 latches (Table 16).
# B8 measures 'I_L (LM1084 input current plus the BT-boost input current)' and stores I_L,cal (working 0.6 A regen,
# 0.3 A FC, Table 8). The band needs the non-boost load only (LM1084 input, ~0.1-0.3 A, calc7 s10).
def ratio(i_bt, vbus, vbatt, eta_true, eta_cal, il_true, il_cal, floor=0.0):
    i_true = i_bt * vbus / (eta_true * vbatt) + il_true
    pred = (i_bt + floor) * vbus / (eta_cal * vbatt) + il_cal
    return i_true / pred
for il_cal in (0.15, 0.30, 0.60, 0.75):
    worst = 9.0
    for i_bt in (1.0, 1.5, 2.0, 3.0):
        for vbatt in (7.4, 8.4):
            for eta_t, eta_c in ((0.95, 0.85), (0.90, 0.90), (0.85, 0.95)):
                for fl in (-0.1, 0.0, 0.1):
                    r = ratio(i_bt, 16.0, vbatt, eta_t, eta_c, 0.15, il_cal, fl)
                    worst = min(worst, r)
    print(f"  I_L,cal {il_cal:.2f} A (true non-boost load 0.15 A): lowest healthy ratio {worst:.3f} "
          f"-> {'BELOW 0.75: State 99 in healthy traction' if worst < 0.75 else 'inside'}")
