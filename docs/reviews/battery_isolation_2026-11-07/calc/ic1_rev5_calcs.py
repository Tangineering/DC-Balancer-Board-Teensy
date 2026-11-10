"""IC1 detailed design, revision 5: calculations for the battle-test round 2 fixes.

Cited in detailed_design_IC1.md as "calc5 section N". Stdlib only.
Run: python ic1_rev5_calcs.py > ic1_rev5_calcs_output.txt

Inputs and their primaries are given per section. ASSUMED values carry the tag in the output.
"""
import math


def hdr(n, t):
    print(f"\n[{n}] {t}")


# ---------------------------------------------------------------------------
hdr(1, "SB-internal pack+ short with F_PK at the pack terminal (FM2-1)")
# Loop: pack(+) -> F_PK -> SB pack+ copper -> short -> SGND/PACK- -> R_SH -> pack(-).
# R_int ASSUMED (pack datasheet missing, facts_prior section 9); copper 2 mOhm ASSUMED (fmea_round2_calcs s7).
V_PACK = 7.4
for r_int in (0.040, 0.020, 0.010):
    i = V_PACK / (r_int + 0.002 + 0.0005)
    print(f"   R_int {r_int*1e3:.0f} mOhm (ASSUMED): prospective {i:5.0f} A -> F_PK 20 A is in the loop "
          f"(rev 4: no fuse in this loop)")
r_max_20a = V_PACK / 20.0
print(f"   any loop resistance below {r_max_20a:.2f} Ohm exceeds 20 A: the hazard does not depend on R_int")
# F_PK open: VBAL+ -> RB1B -> BQ VDD -> GND -> SGND -> S_GND body diode -> PACK- -> R_SH -> pack(-)
for vf in (0.30, 0.50):
    for vcell in (3.0, 3.7, 4.2):
        print(f"   F_PK open, body-diode drop {vf:.2f} V (ASSUMED small-signal), V_cell1 {vcell:.1f} V: "
              f"VC1 - GND = {vcell - vf:+.2f} V (limit -0.3 V, SLUSA52C 7.1)")

# ---------------------------------------------------------------------------
hdr(2, "Q_D5 body diode blocked by D_D5S BAT54 (FM2-4)")
V33 = 3.3
VT_MINUS_MIN = 0.89          # SN74LVC1G17 VT- min at 3.0 V (SCES351Y Table 5-1); 3.3 V value TODO(verify)
for vn1 in (0.10, 0.32):
    # Without D_D5S: D5_N = V_N1 + V_SD; V_SD bound 1.4 V max (BSS138/D at 115 mA) -> upper bound
    print(f"   rev 4, N1 {vn1:.2f} V: D5_N <= {vn1 + 1.4:.2f} V (below LVC244A V_IH 2.0 V) -> step 1 fails on a healthy board")
i_leak = 2e-6                # BAT54 I_R max 2 uA at 25 V, 25 C (BAT54LT1/D)
print(f"   rev 5, N1 LOW, D_D5S reverse biased: D5_N >= 3.3 - {i_leak*10e3*1e3:.0f} mV = "
      f"{V33 - i_leak*10e3:.2f} V (hot leakage TODO(verify: BAT54 I_R vs T))")
# D5 trip with FCQ armed: U_D5 sinks; Q_D5 on; N1 = V_OL(U_D5) + I x R_DS + V_F(BAT54)
i_n1 = (V33 - 0.4) / 10e3
v_n1 = 0.10 + i_n1 * 6.0 + 0.32   # V_OL ASSUMED 0.1 V; R_DS 6 Ohm max at 4.5 V (BSS138); BAT54 0.32 V max at 1 mA
print(f"   rev 5 D5 trip: N1 current {i_n1*1e3:.2f} mA, N1 <= {v_n1:.2f} V vs VT- min {VT_MINUS_MIN} V: "
      f"margin {VT_MINUS_MIN - v_n1:.2f} V (clear preserved)")

# ---------------------------------------------------------------------------
hdr(3, "Pack-negative open upstream of R_SH: Schottky D_VM from GND to VMID (FM2-6)")
R_PAR = 1 / (1 / 260 + 1 / 100)       # RB3 || RB1A (facts_board 2.3)
print(f"   rev 4: board return through RB3 || RB1A = {R_PAR:.1f} Ohm; VC1 - GND between -V_clamp and -V_cell2 (< -0.3 V)")
for vf in (0.20, 0.25, 0.30, 0.40):
    ok = "meets" if vf < 0.30 else "FAILS"
    print(f"   rev 5 with D_VM at V_F {vf:.2f} V (at the brown-out board current, BENCH): VC1 = VMID = {-vf:+.2f} V "
          f"-> {ok} the -0.3 V limit")
for vcell in (3.0, 4.2):
    print(f"   normal operation: D_VM reverse biased by V_cell1 {vcell:.1f} V (conducts only if pack(-) < GND - "
          f"{vcell:.1f} V - V_F)")

# ---------------------------------------------------------------------------
hdr(4, "ERR_IPACK_PLAUS margin (FM2-3, BT2-BM-01)")
for vbatt in (8.4, 7.4):
    for eta in (0.90, 0.95):
        i_pack = 1.0 * 16.0 / (eta * vbatt)
        print(f"   BT_CURRENT 1.0 A at 16.0 V, V_batt {vbatt} V, eta {eta} (ASSUMED): pack discharge "
              f">= {i_pack:.2f} A vs the 0.5 A floor -> x{i_pack/0.5:.1f}")
print("   KS+/KS- short: OUT1 = OUT2 = 1.650 V, I_PACK1 = 0 -> ERR_IPACK_PLAUS fires")

# ---------------------------------------------------------------------------
hdr(5, "ERR_VCHG_FED threshold and blanking (FM2-7, BT2-LS-01)")
R_BLEED = (78.7e3 + 10e3) * (100e3 + 10.5e3) / (78.7e3 + 10e3 + 100e3 + 10.5e3)
C_VCHG = 20e-6                         # C-D8 + C-D10 (facts_board 4.4)
tau = R_BLEED * C_VCHG
print(f"   bleed {R_BLEED/1e3:.2f} kOhm x {C_VCHG*1e6:.0f} uF: tau {tau:.3f} s")
for v0 in (16.0, 17.5, 21.47):
    print(f"   from {v0:5.2f} V to 11 V: {tau*math.log(v0/11):.3f} s")
print("   threshold 11 V: above the highest unfed level (VBT 8.5 V via R_KA, UNCONFIRMED path) and below the 13.5 V "
      "window floor; blanking 1.0 s after any feed edge (> 0.658 s from 21.47 V; TODO(calibrate) at C-2)")
print(f"   SCALE_V_CHG full scale 3.3 x 88.7 / 10 = {3.3*88.7/10:.2f} V (ino:2030)")

# ---------------------------------------------------------------------------
hdr(6, "ERR_VOK_STUCK re-keyed on channel disagreement (BT2-TR-01)")
rise = 0.34 / 0.116
fall14 = 0.33 / 14.0 * 1e3
fall20 = 0.33 / 20.0 * 1e3
print(f"   healthy disagreement: rise {rise:.1f} ms; fall {fall20:.1f} ms at 20 V/s, {fall14:.1f} ms at 14 V/s")
print(f"   50 ms threshold valid while the slowest V-MOT decay is >= {0.33/0.050:.1f} V/s (re-derive if V-MOT C grows)")
tail = (21.35 - 16.10) / 14.0 * 1e3
print(f"   both-permit secondary check: longest post-brake tail {tail:.0f} ms -> dwell 400 ms after the 200 ms rule")

# ---------------------------------------------------------------------------
hdr(7, "Regen-window open latency: command-step arm (OR-V') against the [RER] power arm (BT2-TR-02, BT2-RO-01)")
it_med, it_p99 = 1.131, 1.341
arm = 2.0                                     # 2 ticks at 1 kHz
settled = (2 * it_med, 3 * it_p99)            # settled reading, incl. a straddled first read
step5 = (it_med, it_p99)                      # sense-path check: one iteration
p30 = (arm + settled[0] + step5[0], arm + settled[1] + step5[1])
print(f"   OR-V' arm: pin 30 HIGH {p30[0]:.1f}-{p30[1]:.1f} ms after the I_cmd step")
vok = (5.0 + 3.5, 5.0 + 11.6)
print(f"   VOK assert {vok[0]:.1f}-{vok[1]:.1f} ms after the step (onset <= 5 ms + 3.5-11.6 ms): "
      f"pin 30 leads VOK by {vok[0]-p30[1]:+.1f} ms at the worst pairing (19 ms pulse, p99 loop)")
rer = (40 + settled[0], 40 + settled[1] + step5[1])
print(f"   [RER] power arm: pin 30 HIGH {rer[0]:.1f}-{rer[1]:.1f} ms after the step; first pulse peaks at 24-52 ms: lost")

# ---------------------------------------------------------------------------
hdr(8, "G1 residual error budget (BT2-TR-04)")
I_o = 1.55; vb_hi = 8.4; vbus_lo = 15.1
d_eta = I_o * vb_hi / vbus_lo * (1 / 0.80 - 1 / 0.88)
print(f"   eta 0.80-0.88 uncalibrated at I_o {I_o} A, {vb_hi} V / {vbus_lo} V: {d_eta:.3f} A")
d_il = 0.05 * vb_hi / (0.80 * vbus_lo)
print(f"   I_L spread +/-0.05 A (ASSUMED after calibration): {d_il:.3f} A")
floor = 0.10
d_aux = 0.03                                   # I_AUX spread ASSUMED
ipack = 0.02 * I_o * vb_hi / (0.80 * vbus_lo)  # I_PACK1 2 % ASSUMED (INA240 gain + shunt)
total = floor + d_eta + d_il + d_aux + ipack
print(f"   I_batt floor {floor:.2f} + eta {d_eta:.3f} + I_L {d_il:.3f} + aux {d_aux:.2f} + I_PACK1 {ipack:.3f} = {total:.3f} A")
print(f"   with eta calibrated to +/-0.02 at W1: eta term {I_o*vb_hi/vbus_lo*(1/0.86-1/0.88):.3f} A")
print("   working I_G1 0.35 A (TODO(calibrate)); D5 range 0.31-0.59 A -> G1 does not resolve sub-D5 flows")

# ---------------------------------------------------------------------------
hdr(9, "IMON over-current comparator U_IM (DS2-1)")
GAIN_IMON = 27.9e-6           # A/A, SLVSE94G 6.5 (as read for DS2-1); tolerance TODO(verify)
R_IM = 10e3
th = 3.3 * 10.0 / (59.0 + 10.0)
i_trip = th / (GAIN_IMON * R_IM)
print(f"   IMON {GAIN_IMON*R_IM:.3f} V/A; threshold 3V3 x 10.0k/69.0k = {th:.4f} V -> {i_trip:.2f} A input")
for vos in (-0.009, 0.009):
    print(f"   TLV3011B V_OS {vos*1e3:+.0f} mV: trip {(th+vos)/(GAIN_IMON*R_IM):.2f} A (IMON gain tolerance excluded)")
# Table 8 P_in is the input power at eta 0.88 (22.4 W regen, 14.8 W FC, both at 8.4 V); rescale to eta 0.80
for p, v, lab in ((22.4, 18.0, "regen eta 0.88 at the 18 V threshold"),
                  (22.4 * 0.88 / 0.80, 18.0, "regen eta 0.80 at the 18 V threshold"),
                  (14.8 * 0.88 / 0.80, 13.82, "FC eta 0.80 at the 13.82 V threshold")):
    print(f"   legitimate input {lab}: {p/v:.2f} A")
print("   S0-11 inrush criterion 0.6 A < trip; I_OL min 1.82 A > trip")

# ---------------------------------------------------------------------------
hdr(10, "Module run-on after the eFuse cut (BT2-TR-05, BT2-LS-04, BT2-AG-5): T_drain")
for c_uf in (10, 47, 100, 144):
    c = (c_uf + 1) * 1e-6
    for v0, p in ((21.35, 22.4), (16.0, 14.8)):
        e = 0.5 * c * (v0 ** 2 - 11.0 ** 2)
        print(f"   C_in {c_uf:3d} uF + C_EO: from {v0:5.2f} V at {p:4.1f} W: {e*1e3:5.1f} mJ, {e/p*1e3:5.2f} ms")
print("   T_drain 2 ms covers C_in up to 144 uF (S0-11 bound); TODO(calibrate) from S0-11")

# ---------------------------------------------------------------------------
hdr(11, "Module output ceiling against I_L (FM2-10)")
for iset in (1.75, 1.25):
    print(f"   I_set {iset} A: I_o <= 2.5 A needs I_L <= {2.5-iset:.2f} A (Table 4 JSON code 1 rating)")
print("   regen-window hold condition: estimated I_L <= 0.75 A (BT_CURRENT x V_bus / (eta x V_batt) + LM1084), "
      "TODO(calibrate) at B8")
