"""Battle-test round 4 (delta FMEA of revision 6) calculations.

Every input is taken from detailed_design_IC1.md revision 6 (cited "DD"), its calc scripts (calc6 =
calc/ic1_rev6_calcs_output.txt), facts_board.md, the BQ29200 data sheet SLUSA52C (repository copy) or is marked
ASSUMED. Stdlib only. Run: python fmea_round4_calcs.py
"""
import math


def hdr(t):
    print()
    print("=" * 78)
    print(t)
    print("=" * 78)


# ---------------------------------------------------------------------------
hdr("Section 1. Q_MD stuck ON (F50): eFuse input against U_IM and OC_FC, R_MD energy")
R_MD = 15.0            # DD 5.3 item 1
UIM_MIN, UIM_MAX = 1.508, 1.977   # calc6 s5 (3V3 3.2-3.4 V)
OC_FC = 1.4            # DD 5.3 (OC_FC 1.4 A single sample), BENCH_TEST 0 only (DD 9.2 step 1)
I_AUX = 0.15           # DD 5.3 ("0.15 A aux")
I_IDLE_MAX = 0.018     # Ag105 DS p.20 row 4 (DD 5.3)
I_KA = 0.014           # DD 9.7a (R_KA path about 14 mA, output side)
ETA = 0.88             # DD 1 (unverified 0.88)
for v_in, label in ((16.0, "FC bus / bench 16 V"), (21.5, "regen peak 21.5 V")):
    i_md = v_in / R_MD
    print(f"{label}: R_MD current {i_md:.3f} A, {v_in*i_md:.1f} W")

v = 16.0
i_md = v / R_MD
# configuration check / commissioning: pin 32 LOW, module output only R_KA
i_mod_cfg = I_IDLE_MAX + I_KA * 8.4 / (ETA * v)
i_in = i_md + i_mod_cfg
print(f"config check / commissioning (pin 32 LOW): eFuse input {i_in:.3f} A vs U_IM {UIM_MIN}-{UIM_MAX} A "
      f"-> trip = {i_in >= UIM_MIN}; FC bus {i_in + I_AUX:.3f} A vs OC_FC {OC_FC} A -> latch = {i_in + I_AUX > OC_FC}")
for t in (0.5, 1.0, 2.0):
    print(f"  R_MD energy for a {t:.1f} s powered interval (AG105_SETTLE_MS 500 ms + reads): {v*i_md*t:.1f} J")
# FC window: module charges at 1.25 A (FC profile)
for vb in (7.4, 8.0, 8.4):
    i_mod = 1.25 * vb / (ETA * v)
    s = i_md + i_mod
    print(f"FC window charging, V_batt {vb}: module input {i_mod:.3f} A, eFuse input {s:.3f} A "
          f"(U_IM trips on a unit iff its trip <= {s:.3f} A; units trimmed to {UIM_MIN}-{min(UIM_MAX, 2.055-0.05):.3f} A); "
          f"FC bus {s + I_AUX:.3f} A -> OC_FC (BENCH_TEST 0) = {s + I_AUX > OC_FC}")
print("  before the module starts (cold start 65-170 ms, Bring-Up up to ~8-12 s, DD Table 11):"
      f" eFuse input {i_md + I_IDLE_MAX:.3f} A, FC bus {i_md + I_IDLE_MAX + I_AUX:.3f} A: no U_IM, no OC_FC")
print(f"  a 30 s FC window on a BENCH_TEST 1 build with a unit trimmed above the sum: {v*i_md*30:.0f} J into R_MD")
# regen window, cold module every pulse (DD 7.8): R_MD alone
for v_p, t_p in ((19.0, 0.019), (21.5, 0.047)):
    e = v_p ** 2 / R_MD * t_p
    print(f"regen pulse at {v_p} V for {t_p*1e3:.0f} ms (upper bound, VCHG-IN held): {e:.2f} J; "
          f"56 pulses per 30 s window (calc CC s3 cadence): {56*e:.0f} J, mean {56*e/30:.2f} W")

# ---------------------------------------------------------------------------
hdr("Section 2. MS (U_MS sense wire) shorted to SHDN_EF: U_MS mirrors EF_EN")
R_MS1, R_MS2 = 100e3, 16.2e3    # DD Figure 2 / Table 7
R_SD, R_SDP = 1e3, 22e3         # DD Figure 2 / Figure 6
VTH_LO, VTH_HI = 8.69, 9.15     # DD 5.3 item 3 (node threshold)
REF = 1.242
V_SHUTR_MAX, V_SHUTF_MIN = 2.0, 0.8   # SLVSE94G via DD 7.5
ratio = R_MS2 / (R_MS1 + R_MS2)
for ef_en in (3.3, 0.0):
    for vn in (0.0, 9.0, 16.0, 21.5):
        # node X = shorted MS/SHDN_EF; sources: EF_EN via R_SD, VCHG-IN_M via R_MS1; loads R_MS2, R_SDP
        g = 1/R_SD + 1/R_MS1 + 1/R_MS2 + 1/R_SDP
        vx = (ef_en/R_SD + vn/R_MS1) / g
        print(f"EF_EN {ef_en:.1f} V, node {vn:5.1f} V: shorted node {vx:.3f} V -> pin 8 "
              f"{'HIGH (fed)' if vx > REF else 'LOW (cold)'}; healthy reading would be "
              f"{'HIGH' if vn*ratio > REF else 'LOW'}; eFuse SHDN {'ON' if vx > V_SHUTR_MAX else ('OFF' if vx < V_SHUTF_MIN else 'band')}")
print("-> the window works, the positive control (EF_EN H) passes, every exit 'drains' at once, the probe")
print("   (EF_EN L, bypass puts 16 V on the node) reads cold = PASS, ERR_MOD_FED can never assert.")
# timing discriminator for an EF_EN-L positive control
for c in (100e-6, 221e-6):
    tau = R_MD * c
    for v0 in (16.0, 21.5):
        t = tau * math.log(v0 / VTH_HI)
        print(f"healthy U_MS stays HIGH after the feed drop: C_mod {c*1e6:.0f} uF from {v0} V to {VTH_HI} V: {t*1e3:.2f} ms")
c_ms = 1e-9
r_th = 1/(1/R_SD + 1/R_MS2 + 1/R_SDP)
print(f"mirrored U_MS falls with the SHDN node: tau {r_th*c_ms*1e6:.2f} us plus tSD 0.8-1.5 us and the comparator delay")

# ---------------------------------------------------------------------------
hdr("Section 3. Stage 3 with the revision-6 exit rule (Q_MD re-keyed to FF1./Q, R_MB kept)")
R_MB = 3.3e3
C_HU = 1.5e-3            # DD Table 7
for v0 in (18.0, 21.5):
    t = R_MB * C_HU * math.log(v0 / VTH_HI)
    print(f"exit step 2 with FF1 still set (Q_MD off): C_HU {C_HU*1e3:.1f} mF from {v0} V to {VTH_HI} V through R_MB"
          f" alone: {t:.2f} s (T_drain,max 10 ms -> ERR_MOD_DRAIN on every commanded exit)")
# hold-up from 18 V to 11 V over 535 ms (DD 14.4): idle 18 mA only vs plus R_MB
dt = 1e-5
def holdup(c, with_rmb):
    vv, t = 18.0, 0.0
    while vv > 11.0 and t < 2.0:
        i = I_IDLE_MAX + (vv / R_MB if with_rmb else 0.0)
        vv -= i / c * dt
        t += dt
    return t
for c in (1.38e-3, 1.5e-3):
    print(f"C_HU {c*1e3:.2f} mF, 18 V -> 11 V: idle only {holdup(c, False)*1e3:.0f} ms; with R_MB {holdup(c, True)*1e3:.0f} ms"
          f" (DD 14.4 sizing target 535 ms)")

# ---------------------------------------------------------------------------
hdr("Section 4. D_VC1 / D_VCB reverse leakage and short (BQ29200 accuracy, balancer, cell-1 drain)")
RB3, RB1A = 260.0, 100.0          # facts_board 2.3
VPROT_ACC = 0.025                 # SLUSA52C features: +/-25 mV, TA 0-60 C
VMM_ON = (0.017, 0.030, 0.045)    # SLUSA52C 7.5 VMM_DET_ON min/typ/max
for ir in (10e-6, 50e-6, 100e-6, 300e-6, 1e-3):
    e = ir * RB3
    print(f"D_VC1 I_R {ir*1e6:6.0f} uA: VC1 reads low by {e*1e3:6.1f} mV; bottom-cell OVP late / top-cell OVP early by "
          f"{e*1e3:.1f} mV ({e/VPROT_ACC:.1f} x the +/-25 mV OVP accuracy); apparent mismatch {2*e*1e3:.1f} mV "
          f"(balancing starts at {VMM_ON[0]*1e3:.0f}-{VMM_ON[2]*1e3:.0f} mV, stops near 0 +/-9 mV: steady true "
          f"imbalance driven toward ~{2*e*1e3:.0f} mV); cell-1 drain {ir*720*1e3:.1f} mAh per 30 days")
# Schottky leakage temperature growth: ASSUMED doubling per 10 K (a generic rule, not a primary)
for t in (25, 45, 65, 85):
    f = 2 ** ((t - 25) / 10)
    print(f"  ASSUMED x2/10 K: a part at the DD limit 10 uA (25 C) leaks {10*f:.0f} uA at {t} C -> VC1 error {10e-6*f*RB3*1e3:.1f} mV")
for vc in (3.7, 4.2):
    i_s = vc / RB1A
    print(f"D_VCB short or reversed (F47, undetected in service): cell-1 drain {i_s*1e3:.0f} mA "
          f"({i_s*24:.2f} Ah per day; RB1A {vc*i_s*1e3:.0f} mW in a 125 mW part)")

# ---------------------------------------------------------------------------
hdr("Section 5. F_VX open inside a charge window (row F14 restated)")
for vp in (7.4, 7.8, 8.2):
    pack_neg = 8.4 - 0.1 - vp   # module CV 8.4 V vs Vin- (GND), ASSUMED 0.1 V D-BT-SQ drop
    print(f"V_pack {vp}: module output pins VBT at ~8.3 V; pack(-) sits {pack_neg:+.2f} V vs GND -> S_GND body diodes "
          f"{'reverse-biased: the module, not the pack, supplies the board load, return to Vin- outside the sense' if pack_neg > 0 else 'conduct'}")

# ---------------------------------------------------------------------------
hdr("Section 6. D_VCB short with balancing enabled: BQ29200 top-cell balance switch from VDD to a grounded VC1_CB")
RB1B = 100.0                       # facts_board 2.3 (VBAL+ -> RB1B -> VDD), = RVD of SLUSA52C eq. 2
# RCB2 inferred from SLUSA52C 7.6 (RCB 120 Ohm row: ICB 5/10/15 mA) through eq. 2 at VC2-VC1 = 3.8 V: UNCONFIRMED
rcb2 = {}
for lab, icb in (("max ICB 15 mA", 0.015), ("nom ICB 10 mA", 0.010), ("min ICB 5 mA", 0.005)):
    rcb2[lab] = 3.8 / icb - (120.0 + RB1B)
for lab, r in rcb2.items():
    for vbal in (7.4, 8.4):
        i = vbal / (RB1B + r)
        vdd = vbal - i * RB1B
        print(f"RCB2 {r:5.0f} Ohm ({lab}), VBAL+ {vbal}: switch current {i*1e3:5.1f} mA "
              f"({i/0.015:.1f} x the 15 mA internal-balancing figure), VDD {vdd:.2f} V "
              f"({'below' if vdd < 4.0 else 'above'} the 4 V VDD minimum of SLUSA52C 7.3/7.6)")
print("cell-1 drain through RB1A with D_VCB shorted: 37-42 mA (section 4); the balancer sees cell 2 high by >17-45 mV")
print("once cell 1 has lost the mismatch, and pulls VDD into the grounded VC1_CB through RCB2.")
