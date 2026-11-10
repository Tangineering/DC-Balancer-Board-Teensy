"""IC1 detailed design, revision 8 calculations (battle-test round 5 fixes).

Cited in detailed_design_IC1.md as "calc8 section N". Uses only values stated in the design (revision 7),
its earlier calc scripts, or the round-5 finding scripts named per section. Standard library only.

Sections
  1  ERR_MOD_SENSE (c) re-keyed precondition: between-pulse and probe exposure, node level at evaluation,
     healthy hold time, and the FC-window UVLO case that the V_chg term excludes (FM5-1, BT5-LS-01, BT5-TR-01)
  2  ERR_MOD_DUMP_ON restricted to pin-32-LOW sessions; FC-window coverage by OC_FC and U_IM (BT5-LS-02, BT5-TR-02/03)
  3  D_VC1 two-endpoint feasibility against the minimum operating ambient (BT5-DS-01, FM5-3)
  4  ERR_CELL_MISMATCH budget with the pin-25 calibration, the pin-20 leakage term and R_VC1c (FM5-4, BT5-BO-01)
  5  LB-entry series elements on the VC1, MS, BAL_OK and PROFILE leads (FM5-2, BT5-BO-02)
  6  ERR_IPACK_PLAUS gain band with the non-boost load constant I_NB,cal (FM5-5)
  7  Gate corrections: C-2a item 5 pack voltage, C-2a item 20 reverse I2t, F_VX I2t (BT5-BO-03, BT5-BO-04, BT5-DS-03)
"""
import math

print("=" * 100)
print("[1] ERR_MOD_SENSE (c): precondition read in the iteration of the write")
print("=" * 100)
tau_vchg = 0.984          # s, VCHG-IN bleed (DD Table 11)
for v_rel in (16.13, 16.43):
    t = tau_vchg * math.log(v_rel / 13.5)
    print(f"  release {v_rel:.2f} V: V_chg >= 13.5 V for {t*1e3:6.1f} ms after the VOK release")
print("  revision 7 exposure (bt5_transient_sim s1, fmea_round5_calcs s1): 21.4-37.0 % of random-phase regen exits")
print("  revision 8 precondition: EF_EN (ladder A bit 1, raw) H AND pin 8 HIGH, both read in the write iteration")
print("  immediately before the write, AND pin 8 HIGH continuously for >= 2 ms (micros() since its first HIGH")
print("  read in the current EF_EN-H interval), AND V_chg >= 13.5 V in the same iteration.")
print("  Between pulses EF_EN is L (VOK released) -> not evaluated: exposure 0 %. Probe step 5: EF_EN L -> not evaluated.")
print("  Re-assert span (EF_EN H, node cold during t_D_ON + ramp): pin 8 LOW -> not evaluated.")
# node level once pin 8 has been HIGH for 2 ms during an eFuse output ramp
slew_min, slew_max = 4.17, 5.79      # V/ms, DD 7.5
v_edge_hi = 9.17                      # V, U_MS window top (calc7 s7)
for slew in (slew_min, slew_max):
    v2 = v_edge_hi + slew * 2.0
    print(f"  ramp slew {slew:.2f} V/ms: node >= min({v2:.2f} V, V_chg) 2 ms after the U_MS edge; with V_chg >= 13.5 V the node is >= 13.4 V")
# healthy fall time from 13.4 V through the dump (R_MD || R_MB), constant-power module load (fmea_round5 s2 model)
R_dump = 1.0 / (1.0 / 15.0 + 1.0 / 3300.0)    # 14.93 Ohm


def fall_time(v0, c, p_in, v_end=9.17, dt=1e-7):
    v, t = v0, 0.0
    while v > v_end:
        i = v / R_dump + (p_in / v if v > 11.0 else 0.0)   # module converts down to its 11 V lockout (conservative)
        v -= i / c * dt
        t += dt
    return t


for c_uF in (47, 60, 100, 221):
    for p in (0.0, 14.8, 22.7):
        t = fall_time(13.4, c_uF * 1e-6, p)
        print(f"  healthy fall 13.4 V -> 9.17 V, C_mod {c_uF:3d} uF, P_in {p:4.1f} W: {t*1e6:6.0f} us "
              f"({'>= 150 us' if t >= 150e-6 else '< 150 us: 150 us sample unsafe'})")
# FC-window exit on an eFuse UVLO dropout: why the V_chg term stays
for c_uF in (100, 221):
    for v0 in (9.3, 9.5):
        t = fall_time(v0, c_uF * 1e-6, 0.0)
        print(f"  UVLO case (EF_EN H, V_chg < 13.0 V, node {v0:.1f} V, C_mod {c_uF} uF): fall in {t*1e6:5.0f} us "
              f"-> a check without the V_chg term would false-latch at the 150 us sample")
print("  F55 (pin 8 = EF_EN): pin 8 HIGH for the whole EF_EN-H interval (> 2 ms in every FC window, configuration check")
print("  and dump check), falls within ~3 us + U_MS delay after the write -> latched at the first such exit.")

print()
print("=" * 100)
print("[2] ERR_MOD_DUMP_ON in pin-32-LOW sessions only; FC-window coverage")
print("=" * 100)
I_node = 0.023      # A, healthy node draw (calc7 s4)
I_RKA_in = 0.014 * 8.4 / (0.80 * 15.9)   # module input for the R_KA-only output path, eta 0.80 ASSUMED
I_bt_handoff = 0.20  # A, BT current left after the < 0.2 A wait (9.7 step 5)
healthy = I_node + I_RKA_in + I_bt_handoff
print(f"  pin 32 LOW: healthy 4-iteration-mean step <= {I_node*1e3:.0f} mA node + {I_RKA_in*1e3:.1f} mA R_KA path + "
      f"{I_bt_handoff:.2f} A BT handoff = {healthy:.3f} A; threshold 0.40 A; margin {0.40-healthy:.3f} A")
print("  (single-sample INA253 floor +/-0.1 A, calc7 s10; a 4-iteration mean reduces it by about 2x if uncorrelated, UNCONFIRMED)")
for vb in (15.9, 17.5):
    stuck = vb / 15.0 + vb / 3300.0
    print(f"  V_bus {vb:4.1f} V: stuck dump {stuck:.3f} A -> step >= {stuck+I_node:.3f} A, margin above 0.40 A {stuck+I_node-0.40:.3f} A")
print("  Module start speed does not matter with pin 32 LOW: the output path is R_KA only (14 mA), so the input is <= "
      f"{I_RKA_in*1e3:.1f} mA plus I_q.")
I_aux = 0.15        # A, FC-bus aux (DD 5.3, 0.15 A aux)
print("  FC window (pin 32 HIGH), stuck dump arising after the power-cycle dump check:")
for chg in (0.45, 0.97):
    for vb in (15.9, 17.5):
        stuck = vb / 15.0
        tot = I_aux + stuck + chg + I_node
        print(f"    V_bus {vb:4.1f} V, module input {chg:.2f} A: FC bus {tot:.2f} A vs OC_FC 1.4 A -> "
              f"{'OC_FC latches (BENCH_TEST 0)' if tot > 1.4 else 'below OC_FC'}; eFuse input {stuck+chg+I_node:.2f} A vs U_IM 1.51-1.98 A")
for vb in (15.9, 17.5):
    stuck = vb / 15.0
    print(f"    V_bus {vb:4.1f} V, module not charging (Fully Charged): FC bus {I_aux+stuck+I_node:.2f} A, below OC_FC;"
          f" R_MD {stuck**2*15:.1f} W until the Fully-Charged exit (two valid reads, 40 ms at 50 Hz)")

print()
print("=" * 100)
print("[3] D_VC1: V_F <= 0.25 V at 16.2 mA at T_min, I_R(4.2 V) <= 40 uA at T_hot (design x2 per 10 K rule)")
print("=" * 100)
k, q = 1.380649e-23, 1.602176634e-19
I_F = 0.0162
for n in (1.0, 1.1):
    for t_min in (-20.0, 0.0, 10.0, 15.0, 20.0):
        vt = k * (t_min + 273.15) / q
        is_min = I_F * math.exp(-0.25 / (n * vt))
        # highest T_hot with I_S(T_hot) = is_min * 2**((T_hot - T_min)/10) <= 40 uA
        t_hot = t_min + 10.0 * math.log2(40e-6 / is_min)
        print(f"  n {n:.1f}, T_min {t_min:5.1f} C: I_S(T_min) >= {is_min*1e9:7.1f} nA -> 40 uA budget holds up to T_M16,max = {t_hot:5.1f} C")
print("  (I_R >= I_S; barrier lowering only raises I_R, so these T_M16,max values are upper bounds;")
print("   the thermionic model of fmea_round5_calcs s3 gives 41-107 C over phi_B 0.35-0.65 eV for T_min -20..10 C)")
for i_r in (40e-6, 114e-6, 153e-6):
    print(f"  I_R {i_r*1e6:5.0f} uA: VC1 low by {i_r*261*1e3:5.1f} mV (cell-1 OVP late by the same); mismatch term {2*i_r*261*1e3:5.1f} mV")

print()
print("=" * 100)
print("[4] ERR_CELL_MISMATCH budget (revision 8)")
print("=" * 100)
terms = [
    ("V_BT (pin 25) after the C-2a item 5 two-point calibration (now gated)", 5.0),
    ("2 x V_VC1 channel after two-point calibration (3 mV each)", 6.0),
    ("V_PACKN 2 counts (calc4 s7)", 3.4),
    ("2 x tap load offset through RB3 (calc7 s2)", 5.7),
    ("|I_PACK1| <= 1 A x R_SH", 0.5),
]
other = sum(v for _, v in terms)
for name, v in terms:
    print(f"  {v:5.1f} mV  {name}")
print(f"  sum of terms other than D_VC1 leakage and pin-20 leakage drift: {other:.1f} mV")
dvc1 = 2 * 40e-6 * 261 * 1e3
print(f"  2 x D_VC1 leakage at 40 uA: {dvc1:.1f} mV -> total {other+dvc1:.1f} mV, margin to 80 mV {80-other-dvc1:.1f} mV")
r_th_old = 100e3
r_th_new = 100e3 + 22e3
for r in (r_th_old, r_th_new):
    sens = 4 * r   # V per A of pin current (V_VC1 = 2 V_pin, formula uses 2 V_VC1)
    allow = (80 - other - dvc1) * 1e-3 / sens
    print(f"  pin-20 source {r/1e3:5.0f} kOhm: {sens*1e-6*1e3:.0f} mV of mismatch per uA of pin current; "
          f"uncalibrated leakage drift allowed {allow*1e9:5.0f} nA")
lat_worst = (80 - other - 1e-9) / (2 * 261) * 1e3
print(f"  latch leakage with every other term at its bound: (80 - {other:.1f}) / (2 x 261) = {(80-other)/(2*261)*1e3:5.0f} uA")
print(f"  latch leakage with the other terms at zero: 80 / (2 x 261) = {80/(2*261)*1e3:5.0f} uA")
print("  (revision 7 Table 16 'about 75 uA' was the excess above 40 uA, not the total; BT5 verifier)")

print()
print("=" * 100)
print("[5] LB-entry series elements on flying leads that land on an LB input (chafe to a positive conductor)")
print("=" * 100)
for name, r in (("R_VC1c (VC1 tap -> pin 20)", 22e3), ("R_MS3 (MS lead -> U_MS IN+)", 22e3),
                ("R_PGL (PROFILE lead -> pin 10 net)", 22e3)):
    for v in (8.5, 17.5, 21.5):
        print(f"  {name}: chafe to {v:4.1f} V -> injected {(v-3.6)/r*1e3:5.2f} mA (3.6 V clamp onset ASSUMED)")
print("  Teensy 3V3 load (about 100 mA, UNCONFIRMED) exceeds every injected current, so the rail cannot rise;")
print("  pad injection limit TODO(verify: IMXRT1060CEC); TLV3011B input current limit TODO(verify: SBOS300C 6.1)")
# VC1 tap filter and DC ratio
c_vc1 = 100e-9
print(f"  VC1 tap filter with R_VC1c: tau = (100k + 22k) x 100 nF = {(122e3*c_vc1)*1e3:.1f} ms (was 10.0 ms); DC ratio VC1/2 unchanged")
# MS lead: C_MS stays on the lead side, R_MS3 feeds IN+ only
c_in = 5e-12
print(f"  R_MS3 with C_MS on the lead side: added delay R_MS3 x C_in(IN+, ~5 pF ASSUMED) = {22e3*c_in*1e9:.0f} ns; "
      "U_MS DC threshold unchanged (TLV3011B bias pA)")
# PROFILE: R_PGL into two BSS138 gates through R_PG 1k at CB plus Q_I1b/Q_INV gates at LB
c_g = 4 * 50e-12
print(f"  R_PGL with about 4 x 50 pF of gate load (ASSUMED): tau {22e3*c_g*1e6:.1f} us; pin 10 changes only on a cold module (ms scale)")
# BAL_OK: R_BL1 150k at the tap, R_BL3 47k at the LB entry, R_BL2 100k to GND at the U_LA input
for vbal in (7.4, 8.5):
    vin = vbal * 100e3 / (150e3 + 47e3 + 100e3)
    print(f"  BAL_OK: VBAL+ {vbal:.1f} V -> U_LA input {vin:.2f} V (LVC244A VIH 2.0 V at 3.0-3.6 V, TODO(verify: SCAS414))")
th = 1.0 / (1.0 / 197e3 + 1.0 / 100e3)
print(f"  BAL_OK Thevenin {th/1e3:.0f} kOhm x 5 uA input leakage = {th*5e-6:.2f} V worst offset; drain at 8.5 V {8.5/297e3*1e6:.0f} uA")
for v in (8.5, 9.5, 17.5, 21.5):
    vn = v * 100e3 / (147e3)
    print(f"  BAL_OK lead chafed to {v:4.1f} V: U_LA input {vn:5.2f} V vs 6.5 V absolute maximum -> "
          f"{'within' if vn <= 6.5 else 'EXCEEDS: lead must stay segregated from this conductor'}")

print()
print("=" * 100)
print("[6] ERR_IPACK_PLAUS gain band with I_NB,cal (non-boost VBT load) in place of I_L,cal")
print("=" * 100)
worst = []
for i_nb_true in (0.10, 0.20, 0.30):
    for i_nb_cal_err in (-0.05, 0.05):
        i_nb_cal = i_nb_true + i_nb_cal_err
        for eta_true in (0.85, 0.95):
            for eta_cal in (0.85, 0.95):
                for ibt in (1.0, 4.0):
                    for vb_batt in (7.4, 8.4):
                        vbus = 16.0
                        ip_true = ibt * vbus / (eta_true * vb_batt) + i_nb_true
                        pred = ibt * vbus / (eta_cal * vb_batt) + i_nb_cal
                        for floor in (-0.1, 0.1):
                            worst.append((ip_true + floor) / pred)
print(f"  I_NB 0.1-0.3 A calibrated to +/-0.05 A, eta 0.85-0.95 both ways, BT 1-4 A, INA253 floor +/-0.1 A: "
      f"ratio {min(worst):.3f}-{max(worst):.3f} against the band 0.75-1.30")
print("  with the B8 I_L,cal (0.6 A, LM1084 + BT-boost input) mistaken for I_NB: lowest ratio 0.703 (fmea_round5_calcs s6) -> excluded by the separate constant")
print("  1 s mean (1000 samples at 1 kHz): the INA253 floor term averages down; the static spread above is the bound used")

print()
print("=" * 100)
print("[7] Gate corrections")
print("=" * 100)
for vp in (7.4, 8.0, 8.4, 8.5):
    print(f"  C-2a item 5 with VC1 held at GND: VC2-VC1 = {vp:.2f} V vs 8 V absolute maximum (SLUSA52C 7.1): "
          f"{'within, margin %.2f V' % (8.0 - vp) if vp < 8.0 else ('at the limit' if vp == 8.0 else 'OVERSTRESS')}")
print("  revision 8 item 5 grounds the R_VC1a/R_VC1b junction on LB instead: VC1 sag 21 uA x 261 Ohm = "
      f"{21e-6*261*1e3:.1f} mV, BQ29200 not stressed")
s0_10 = 17.0 ** 2 * 0.5e-3
for i in (1.0, 3.0, 7.0):
    for t_it in (1.341e-3, 9.76e-3):
        i2t = i * i * (t_it + 5e-3)
        print(f"  C-2a item 20 at {i:.0f} A, iteration {t_it*1e3:5.2f} ms + 5 ms: I2t {i2t:.3f} A2s = {i2t/s0_10:4.2f} x S0-10 "
              f"({s0_10:.4f} A2s); {i2t/2.469*100:4.1f} % of the F_VX 4 A melting I2t 2.469 A2s")
print("  F_VX 4 A (Littelfuse 451/453 amp code 004, rev GD as read in BT5-DS-03): 16.0 mOhm, melting I2t 2.469 A2s (8 ms);")
print("  revision 7 quoted 3.152 A2s, the amp code 005 (5 A) value")
