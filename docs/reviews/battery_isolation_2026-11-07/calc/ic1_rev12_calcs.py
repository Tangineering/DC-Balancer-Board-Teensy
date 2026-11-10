"""IC1 detailed design, revision 12 calculations (battle-test round 8 adjudication).

Cited in detailed_design_IC1.md as "calc12 section N". Every input is a value stated in the design (revision 11), in a
round-8 script (bt8_*.py) or in a primary named beside it. Nothing here is a new measurement. Standard library only.

Sections
  1  MD_G-SHDN_EF short (BT8-FM-01): the shorted node in both EF_EN states, the revision-6 comparison, and the
     single-chafe outcomes once SHDN_EF runs in its own sleeve
  2  J-FC bench-supply setting (BT8-REQ-01): pin-24 voltage, the setting at which pin 24 reaches 3.3 V and 3.6 V, and
     the FC-window draw from J-FC against the current limit
  3  eFuse inrush against C_mod at C_DV 10 nF (BT8-TR-01): the largest C_mod that keeps 0.6 A, the C_DV rule and the
     ramp time it implies
  4  Fixed window split code (BT8-TR-02): the firmware truncation
  5  BAL_OK pack threshold at R_BL2 100 kOhm 1 % (BT8-TR-03)
  6  HR2 parked figure as net pack current (BT8-REQ-04)
  7  Pin-20 leakage at the datasheet limit against the F47 signal (BT8-DS-03)
  8  D_VC1 real-part leakage factor (BT8-DS-04): I_S from the NSR0320MW2 V_F row, the I_R/I_S ratio, and the hot
     limit for a die that just meets the V_F limit
  9  TLV3011B input under a lead chafe (BT8-DS-01) and the CB-end pins (BT8-DS-02)
 10  Idle-entry self-test under the revision-12 rule (BT8-LS-01): window delay, and the T1-T5 outcomes

Run:  .venv_hil/Scripts/python.exe docs/reviews/battery_isolation_2026-11-07/calc/ic1_rev12_calcs.py
      > docs/reviews/battery_isolation_2026-11-07/calc/ic1_rev12_calcs_output.txt
"""
import math


def hdr(n, s):
    print("=" * 100)
    print(f"[{n}] {s}")
    print("=" * 100)


def par(*rs):
    return 1.0 / sum(1.0 / r for r in rs)


# ================================================================================================ 1
hdr(1, "MD_G-SHDN_EF short (BT8-FM-01)")
# Design rev 11 Figure 2 / Figure 6: R_SD 1k (EF_EN -> SHDN_EF), R_MDS 1k (U_MDI -> MD_G), R_SDP 22k (SHDN to GND, CB),
# R_MDG 100k (Q_MD gate to GND, CB). SLVSE94G 6.5: SHDN sources at most 10 uA; V_SHUTF 0.8 V min, V_SHUTR 2.0 V max.
R_SD, R_MDS, R_SDP, R_MDG = 1e3, 1e3, 22e3, 100e3
I_SHDN = 10e-6
lo_n, hi_n = 1e9, -1e9
for v33 in (3.2, 3.3, 3.4):
    for tol in (-0.01, 0.0, 0.01):
        for ef_h in (True, False):
            rsd = R_SD * (1 + tol)
            rmds = R_MDS * (1 - tol)
            g = 1 / rsd + 1 / rmds + 1 / R_SDP + 1 / R_MDG
            # one LVC output at v33 and the other at 0 V (U_MDI = NOT EF_EN, so they always oppose)
            src = (v33 / rsd if ef_h else v33 / rmds) + I_SHDN
            v = src / g
            lo_n, hi_n = min(lo_n, v), max(hi_n, v)
print(f"shorted node over 3V3 3.2-3.4 V, 1 % resistors, both EF_EN states: {lo_n:.3f}-{hi_n:.3f} V")
print("  (bt8_fmea_rev8_sleeve section 1 at 3V3 3.3 V: 1.594-1.626 V; the 3V3 range widens it)")
print("  SLVSE94G 6.5 guarantees OFF below 0.8 V and ON above 2.0 V: the node is in neither band")
# Revision-12 routing: SHDN_EF in its own sleeve. A single insulation failure can then join SHDN_EF only to its
# own sleeve contents (none) or to the sleeve shield/GND if one is fitted; MD_G single faults are rows F49/F50.
print("single-chafe outcomes with SHDN_EF in its own sleeve (revision 12):")
print(f"  healthy SHDN_EF with EF_EN H: {3.3 * R_SDP / (R_SD + R_SDP):.3f} V (> 2.0 V: eFuse on)")
print("  SHDN_EF to GND: eFuse off in both states -> ERR_MOD_SENSE (b) positive control fails (loud, availability)")
print("  MD_G to GND: dump lost -> row F49, ERR_MOD_DRAIN at the first exit; MD_G to a HIGH conductor: row F50")
print("  MD_G to SHDN_EF: needs a failure of both sleeves (two insulation failures, the F54c acceptance class)")
# Q_MD linear-mode exposure (unchanged numbers; bt8 section 2), carried for the residual statement
for vn in (15.5, 16.0, 17.5):
    print(f"  double-fault residual: Q_MD worst linear dissipation at node {vn:4.1f} V = {vn * vn / (4 * 15.0):.2f} W")

# ================================================================================================ 2
hdr(2, "J-FC bench-supply setting (BT8-REQ-01)")
R1, R2 = 27.4e3, 10e3          # BOM rows 58-59, SCH R1-FC / R2-FC; ino:2022-2024
k = R2 / (R1 + R2)
print(f"divider ratio {k:.4f}; Thevenin {par(R1, R2) / 1e3:.2f} kOhm; full scale at 3.3 V: {3.3 / k:.3f} V")
for vj in (9.3, 12.0, 12.3, 16.0):
    print(f"  J-FC {vj:5.2f} V -> pin 24 {vj * k:.3f} V")
print(f"  pin 24 reaches 3.6 V (OVDD + 0.3 V at 3.3 V) at J-FC {3.6 / k:.2f} V")
print(f"  ADC headroom at 12.0 V: {(3.3 / k - 12.0) / (3.3 / k) * 100:.1f} % of full scale")
# Window draw from J-FC: bus 15.8 V; charger 0.82-0.93 A + aux 0.09-0.15 A (DD 9.11.3, Table 26, calc11 s2);
# boost efficiency 0.90-0.97 ASSUMED (SLVSFP3C p.1: up to 96.9 % at 7.2 V to 16 V).
for vj in (9.3, 12.0):
    lo = 15.8 * (0.82 + 0.09) / (0.97 * vj)
    hi = 15.8 * (0.93 + 0.15) / (0.90 * vj)
    print(f"  window draw from J-FC at {vj:4.1f} V: {lo:.2f}-{hi:.2f} A; limit 2.0 A -> margin x{2.0 / hi:.2f}")
print("  commissioning steps 1-11 (pin 32 LOW, module quiescent): 1.5 A limit retained")

# ================================================================================================ 3
hdr(3, "eFuse inrush against C_mod at C_DV 10 nF (BT8-TR-01)")
SLEW_MAX, SLEW_MIN = 5.79, 4.17   # V/ms at C_DV 10 nF (DD Table 7 C_DV row, SLVSE94G 6.3/6.5)
I_LIM = 0.6
cmax = I_LIM / (SLEW_MAX * 1e3) * 1e6
print(f"largest C_mod for 0.6 A at {SLEW_MAX} V/ms: {cmax:.1f} uF")
for c in (47, 100, 103.6, 150, 221):
    cdv = max(10.0, 10.0 * c / cmax)
    smin = SLEW_MIN * 10.0 / cdv
    print(f"  C_mod {c:6.1f} uF: C_DV >= {cdv:5.1f} nF; slowest slew {smin:.2f} V/ms; "
          f"ramp 0 -> 15.95 V {15.95 / smin:.1f} ms (+ UVLO delay, its C_DV scaling TODO(verify: SLVSE94G))")
print("  ERR_MOD_DUMP_ON sample re-keyed: the later of 10 ms and the S0-11 measured ramp + 2 ms after chargerHasPower()")

# ================================================================================================ 4
hdr(4, "Fixed window split code (BT8-TR-02)")
K_DROOP, RE_MAX, DROOP_R_MAX = 0.30, 2.0136, 0.85   # ino:3097-3105 as quoted in bt8 section 2
g = K_DROOP / (RE_MAX * DROOP_R_MAX)
print(f"g_FC = {g:.4f}; g x 4095 = {g * 4095:.2f}; (uint16_t) cast (ino:15264-15265) -> code {int(g * 4095)}")

# ================================================================================================ 5
hdr(5, "BAL_OK pack threshold at R_BL2 100 kOhm 1 % (BT8-TR-03)")
R_BL1, R_BL3 = 150e3, 47e3
VIH, I_LEAK = 2.0, 5e-6        # LVC244A VIH (TODO(verify: SCAS414)); leakage as calc8 section 5
worst = 0.0
for t1 in (-0.01, 0.01):
    for t2 in (-0.01, 0.01):
        rbl1, rbl2 = R_BL1 * (1 + t1), 100e3 * (1 + t2)
        # U_LA input = VBAL * rbl2/(rbl1+R_BL3+rbl2) - I_LEAK * Thevenin; solve for VBAL at VIH
        rt = rbl1 + R_BL3 + rbl2
        th = par(rbl1 + R_BL3, rbl2) + 0.0
        vbal = (VIH + I_LEAK * th) * rt / rbl2
        worst = max(worst, vbal)
print(f"VBAL+ at which BAL_OK reaches VIH, worst 1 % corner: {worst:.2f} V; margin to 7.4 V entry floor {7.4 - worst:+.2f} V")

# ================================================================================================ 6
hdr(6, "HR2 parked figure as net pack current (BT8-REQ-04)")
I_SET, T_P = 1.25, 10.34
for dead in (0.450, 0.569):
    for il in (0.20, 0.30):
        usable = 1 - dead / T_P
        net = I_SET * usable - il * dead / T_P
        print(f"  dead {dead:.3f} s, I_L {il:.2f} A (ASSUMED, B8): gross {I_SET * usable:.3f} A, net {net:.3f} A")

# ================================================================================================ 7
hdr(7, "Pin-20 leakage at the datasheet limit against the F47 signal (BT8-DS-03)")
sens = 4 * (par(200e3, 200e3) + 22e3)   # V of mismatch per A of pin current
print(f"sensitivity {sens * 1e-6:.3f} V/uA; at the IMXRT1060CEC Table 22 limit 1 uA: {sens * 1e-6 * 1e3:.0f} mV")
print(f"allowance (80 - 41.5 mV)/sensitivity = {(0.080 - 0.0415) / sens * 1e9:.0f} nA; ratio {1e-6 / ((0.080 - 0.0415) / sens):.1f}x")
worst_healthy = 0.0415 + sens * 1e-6
print(f"worst healthy error at the datasheet limit {worst_healthy:.2f} V; F47 reversed signal >= 8.0 - 2 x 0.25 = 7.5 V")
print(f"  any threshold in ({worst_healthy:.2f}, 7.0) V detects F47 on the first evaluation")

# ================================================================================================ 8
hdr(8, "D_VC1 real-part leakage factor (BT8-DS-04)")
VT25 = 8.617e-5 * 298.15
n = 1.01
is_nsr = 10e-3 / math.exp(0.24 / (n * VT25))          # NSR0320MW2: V_F 0.24 V typ at 10 mA, 25 C (bt8 reading)
ratio = 10e-6 / is_nsr                                  # I_R 10 uA typ at 15 V, 25 C
print(f"NSR0320MW2 (onsemi NSR0320MW2T1/D Rev. 8 as read in round 8): I_S {is_nsr * 1e6:.2f} uA; I_R/I_S at 25 C = {ratio:.1f}")
is_just = 16.2e-3 / math.exp(0.25 / (n * VT25))        # a die that just meets 0.25 V at 16.2 mA at 25 C
ir25 = ratio * is_just
t40 = 25 + 10 * math.log2(40e-6 / ir25)
print(f"die meeting V_F 0.25 V at 16.2 mA at 25 C: I_S {is_just * 1e6:.2f} uA, I_R(25 C) about {ir25 * 1e6:.1f} uA,")
print(f"  40 uA reached at about {t40:.0f} C under the design x2 per 10 K rule (T_min 25 C, the most favourable ruling)")
for vf_max_10 in (0.27,):
    vf16 = vf_max_10 + n * VT25 * math.log(16.2 / 10)
    print(f"NSR0320MW2 max row {vf_max_10} V at 10 mA -> {vf16:.3f} V at 16.2 mA, 25 C; margin to the -0.3 V VC1 limit {0.3 - vf16:.3f} V")

# ================================================================================================ 9
hdr(9, "TLV3011B inputs and CB-end pins under a lead chafe (BT8-DS-01, BT8-DS-02)")
for vc in (8.5, 17.5, 21.5):
    print(f"  chafe {vc:4.1f} V: U_MS IN+ / U_IM IN- = {vc - 10e-12 * 22e3:.3f} V (no V+ clamp, IB 10 pA, SBOS300C 6.2 note 2, 6.7);"
          f" current into a failed-short input <= {(vc - 3.3) / 22e3 * 1e3:.2f} mA (R_MS3) / {(vc - 3.3) / 10e3 * 1e3:.2f} mA (R_IMF);"
          f" CB SHDN/IMON pin {vc:.1f} V vs 5.5 V; Q_CS/Q_MP V_GS {vc * 100 / 101:.2f} V vs 20 V")

# ================================================================================================ 10
hdr(10, "Idle-entry self-test under the revision-12 rule (BT8-LS-01)")
T_ST = (0.3577, 0.4575)   # s, cc section 1
print(f"a window request waits for the self-test: first P window delayed by at most {T_ST[1] * 1e3:.1f} ms")
cases = [
    ("T1 Run -> parked form -> Finish -> Idle", "self-test runs to PASS, window follows"),
    ("T2 parked request standing at an Idle entry", "self-test runs to PASS, window follows"),
    ("T3 State 98 Q (MOT_PWR LOW), Stage 2", "deferred by step 10; step 10 re-runs when MOT_PWR is HIGH"),
    ("T4 State 98 Q, Stage 1, request standing", "self-test runs to PASS, window follows"),
    ("T5 boot -> State 0 -> State 1 -> Run at 0-490 ms", "0 -> 1 is not an Idle entry: the boot self-test pass stands"),
]
for c, r in cases:
    print(f"  {c:48s}: {r}")
print("  residual: Finish -> Idle -> Run within 357.7-457.5 ms -> deferred; D-s refused (code 16) until the next")
print("  Idle iteration without a State-2 request re-runs it to PASS")
