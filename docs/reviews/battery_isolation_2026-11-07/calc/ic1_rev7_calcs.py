"""IC1 detailed design, revision 7 calculations (battle-test round 4 fixes).

Stdlib only. Every input is a value stated in detailed_design_IC1.md, a primary it cites, or a battle-test round-4
script output; ASSUMED values are labelled. Output: calc/ic1_rev7_calcs_output.txt ("calc7 section N").
"""
import math

def hdr(n, t):
    print(f"\n[{n} {t}]")

# ---------------------------------------------------------------------------------------------------------------
hdr(1, "Balance network after M16 rev 7: D_VCB deleted, RB1A 100 Ohm -> 4.7 kOhm, D_VC1 kept")
RB3 = 260.0      # SCH value (BOM 261), facts_board 2.3
RB1A_old, RB1A_new = 100.0, 4700.0   # SLUSA52C 7.3 RCB recommended 100-4.7k
RB1B = 100.0     # RVD
for vc in (3.7, 4.2):
    i_old = vc / RB1A_old
    i_new = vc / RB1A_new
    print(f"V_cell {vc}: VC1_CB bridged to GND drains cell 1 at {i_old*1e3:5.1f} mA (RB1A 100) -> {i_new*1e3:4.2f} mA"
          f" (RB1A 4.7k), {i_new*24:5.3f} Ah/day, {vc*vc/RB1A_new*1e3:4.2f} mW in RB1A")
# eq 1 / eq 2 (SLUSA52C 8.3.5); RCB1/RCB2 blank in 7.5 -> range inferred (UNCONFIRMED) 33-540 Ohm
for rcb2 in (33.0, 160.0, 540.0):
    icb2 = 4.2 / ((RB1A_new + RB1B) + rcb2)
    icb1 = 4.2 / (RB1A_new + rcb2)
    print(f"  balance current at RCB 4.7k, RCB1=RCB2={rcb2:5.0f} Ohm (UNCONFIRMED): ICB1 {icb1*1e3:4.2f} mA, ICB2 {icb2*1e3:4.2f} mA"
          f" (SLUSA52C Table 7.6 at RCB 4700: 0.5/0.75/1 mA)")
# F34b (pack-negative open upstream of R_SH): board return through D_VC1 + RB3 only; VC1_CB through RB1A into the pin
for vf in (0.0, 0.25):
    i_rb3 = (4.2 - vf) / RB3
    print(f"F34b: V_F {vf:4.2f} V: board return bound through RB3 = (V_cell2 - V_F)/RB3 = {i_rb3*1e3:5.1f} mA (rev 6 with RB1A: 58.1 mA)")
for v_esd in (0.3, 0.6):
    i_cb = (4.2 - v_esd) / RB1A_new
    i_cb_old = (4.2 - v_esd) / RB1A_old
    print(f"  VC1_CB with no clamp, pin structure at -{v_esd} V: {i_cb*1e3:4.2f} mA through RB1A 4.7k"
          f" (with RB1A 100 Ohm it would be {i_cb_old*1e3:4.1f} mA); VC1_CB abs max not in SLUSA52C 7.1: TODO(verify: TI)")
print(f"D_VC1 short: cell-1 drain {4.2/RB3*1e3:4.1f} mA = {4.2/RB3*24:4.2f} Ah/day; VC2-VC1 = V_pack 8.40/8.50 V vs 8 V abs max (SLUSA52C 7.1)")

# ---------------------------------------------------------------------------------------------------------------
hdr(2, "VC1 tap to Teensy pin 20 (A6): R_VC1a 200k at the VC1 pad, R_VC1b 200k + C_VC1 100 nF on LB")
Ra, Rb, Cv = 200e3, 200e3, 100e-9
for vc1 in (3.0, 4.2, 4.4):
    i = vc1 / (Ra + Rb)
    print(f"VC1 {vc1} V: pin 20 {vc1*Rb/(Ra+Rb):5.3f} V; tap current {i*1e6:5.2f} uA; VC1 sag through RB3 {i*261*1e3:4.2f} mV")
print(f"Thevenin {Ra*Rb/(Ra+Rb)/1e3:.0f} kOhm, tau {Ra*Rb/(Ra+Rb)*Cv*1e3:.0f} ms; ADC LSB at VC1 {2*3.3/4096*1e3:4.2f} mV (12-bit, 3V3 = 3.30 V)")
print(f"F34b: VC1 = -0.25 V -> pin 20 {-0.25/2:+.3f} V through 100 kOhm (<= 1.3 uA); fault VC1 at 8.5 V -> pin 20 4.25 V,"
      f" clamp current <= {(4.25-3.6)/100e3*1e6:4.1f} uA (ASSUMED 3.6 V clamp onset)")
print(f"Chafe of the tap lead to GND or to VBT 8.5 V through R_VC1a: <= {8.5/200e3*1e6:4.1f} uA; VC1 moves <= {8.5/200e3*261*1e3:4.1f} mV")
# mismatch = V_cell2 - V_cell1 = V_BT - 2 V_VC1 + V_PACKN (bonded, pack(-) = PACK- within I*R_SH)
budget = {
    'V_BT channel after two-point cal (ASSUMED 5 mV)': 5.0,
    '2 x V_VC1 channel after two-point cal (ASSUMED 3 mV each)': 6.0,
    'V_PACKN 2 counts (calc4 section 7: 1.692 mV/count)': 3.4,
    '2 x tap load offset through RB3 (section above)': 2 * 4.4 / 400e3 * 261 * 1e3,
    '2 x D_VC1 leakage at T_M16,max (40 uA x 261 Ohm)': 2 * 40e-6 * 261 * 1e3,
    '|I_PACK1| <= 1 A x R_SH 0.5 mOhm': 0.5,
}
tot = 0.0
for k, v in budget.items():
    tot += v
    print(f"  mismatch error term: {k}: {v:5.1f} mV")
print(f"  worst-case sum {tot:5.1f} mV against the ERR_CELL_MISMATCH threshold 80 mV (TODO(calibrate)): margin {80-tot:4.1f} mV")
print("  D_VC1 short or reversed D_VC1: V_VC1 ~ 0 V (short) or ~ +V_F -> mismatch reads ~ V_pack (7.4-8.5 V): latches on the first evaluation")

# ---------------------------------------------------------------------------------------------------------------
hdr(3, "D_VC1 specification (FM4-5, BT4-DS-01)")
I_clamp = 4.2 / RB3
print(f"D_VC1 carries at most {I_clamp*1e3:4.1f} mA (RB3 alone); rev 6 asked V_F <= 0.25 V at 45 mA (RB1A current, now gone)")
Vt = 0.025693
for n in (1.0, 1.1):
    for I in (I_clamp, 0.045):
        Is = I * math.exp(-0.25 / (n * Vt))
        print(f"  n {n}: V_F 0.25 V at {I*1e3:4.1f} mA implies I_S >= {Is*1e6:5.2f} uA at 25 C")
for T in (45, 60, 85):
    f = 2 ** ((T - 25) / 10.0)
    print(f"  ASSUMED x2 per 10 K: a 40 uA limit at {T} C equals {40/f:5.2f} uA at 25 C (scale x{f:5.1f})")
print(f"  I_R 40 uA x 261 Ohm = {40e-6*261*1e3:5.2f} mV VC1 error (cell 1 reads low, cell 2 high)")

# ---------------------------------------------------------------------------------------------------------------
hdr(4, "ERR_MOD_DUMP_ON: FC_CURRENT step at the EF_EN rise (FM4-3, BT4-1)")
R_MD, R_MB, R_div, Iq = 15.0, 3300.0, 116.2e3, 0.018
for v in (15.9, 16.0, 17.5):
    healthy = Iq + v / R_MB + v / R_div
    fault = healthy + v / R_MD
    print(f"V_bus {v:4.1f} V: healthy node draw {healthy*1e3:5.1f} mA; stuck dump {fault:5.3f} A; step margin to 0.4 A:"
          f" {0.4-healthy:4.2f} A below / {fault-0.4:4.2f} A above; R_MD {v*v/R_MD:4.1f} W")
print(f"FC_CURRENT LSB (INA253A1 0.1 V/A, 12-bit, 3.30 V) = {3.3/4096/0.1*1e3:4.1f} mA")
print(f"energy to detection (feed at the eFuse + 2 iterations + 10 ms + one 9.76 ms gap: about 25-30 ms, 30 ms used): {16.0**2/15*0.030:4.2f} J at 16 V, {17.5**2/15*0.030:4.2f} J at 17.5 V"
      f" (R_MD single-pulse requirement 1.71 J)")
print(f"MD_G series 1 kOhm: chafe to GND {3.3/1000*1e3:4.1f} mA; gate fraction with R_MDG 100k {100/101*100:5.1f} %")

# ---------------------------------------------------------------------------------------------------------------
hdr(5, "Deadline rule: later of 10 ms and 4 iterations after the edge, capped at 30 ms (BT4-LS-03, BT4-LS-02)")
drains = [0.84, 1.28, 1.93, 2.83, 3.02]
def reads(T, L1):
    t = [T]          # iteration 0 ends at T (feed-drop write at t = 0 at the start of iteration 0)
    t.append(t[-1] + L1)
    for _ in range(6):
        t.append(t[-1] + T)
    return t
for T in (1.0, 1.131, 1.341):
    for L1 in (T, 9.76):
        r = reads(T, L1)
        dl = min(max(10.0, r[3]), 30.0)   # 4 iterations after the edge = 4th read time r[3]
        worst = 0.0
        ok = True
        for d in drains:
            low = [x for x in r if x >= d]
            second = low[1]
            worst = max(worst, second)
            if second > dl:
                ok = False
        print(f"  loop {T:5.3f} ms, iteration-1 length {L1:5.2f} ms: deadline {dl:5.2f} ms; latest 2nd LOW read {worst:5.2f} ms -> "
              f"{'PASS' if ok else 'FALSE LATCH'} (drain 0.84-3.02 ms)")
print("  ERR_MOD_SENSE (b): pin 8 HIGH at most 3.38 ms after the anchor (Table 16); with the same deadline rule the first")
print("  read after a 9.76 ms gap lands at <= anchor + 9.76 + 1.341 = 11.10 ms, inside max(10 ms, 4 iterations >= 13.15 ms)")
print(f"  crossing-anchor margin at the p99 loop without a gap: 10 - 3.38 - 1.341 = {10-3.38-1.341:4.2f} ms")
# residual VCHG-IN at the next VOK assert: bt4_logic_seq_enum section 3 gives 13.51-14.14 V on 6 of 15 grid points;
# the verifier's spot check uses 0.126 s from the release to the next assert (16 V/s decay case)
for rel in (16.13, 16.43):
    for gap in (0.126, 0.2):
        res = rel * math.exp(-gap / 0.984)
        print(f"  residual at re-assert: release {rel} V, {gap} s from release to re-assert (tau 0.984 s): {res:5.2f} V")
print("  any residual >= 13.0 V is above UVLO rising (<= 12.88 V); the eFuse drains VCHG-IN to <= 12.10 V within ~1.24 ms,")
print("  so a V_chg read below 13.0 V precedes the real feed (t_D_ON 8 ms typical) and re-arms the crossing anchor.")

# ---------------------------------------------------------------------------------------------------------------
hdr(6, "Exit-iteration pin-8 hold check (FM4-2): samples 50 us and 150 us after the feed-drop write")
print("  healthy U_MS stays HIGH >= 0.248 ms after the feed drop (calc/verify_ms_shdn_short.py S3: 100 uF, 13.5 V, 1.0 A ESTIMATE)")
print(f"  margin of the 150 us sample: {0.248-0.150:5.3f} ms; mirrored node (MS shorted to SHDN_EF) falls in ~3 us + U_MS delay")
print("  (open-drain TLV3011B delay not specified, TODO(verify: SBOS300C); must be < 50 us for detection, measured at C-2b)")

# ---------------------------------------------------------------------------------------------------------------
hdr(7, "U_MS threshold with the CMRR term (BT4-DS-07)")
ratio = 16.2 / 116.2
cm = 1.242 * 10 ** (-54 / 20.0)
print(f"  CMRR 54 dB at VCM 1.242 V: {cm*1e3:4.2f} mV at IN+ = {cm/ratio*1e3:5.1f} mV at the node; window 8.69-9.15 V ->"
      f" {8.69-cm/ratio:5.2f}-{9.15+cm/ratio:5.2f} V")

# ---------------------------------------------------------------------------------------------------------------
hdr(8, "F_VX prospective current (BT4-DS-05)")
for rfvx in (0.0, 0.010, 0.016, 0.030):
    r = 0.0 + 0.003 + 0.0 + 0.0103 + 0.010 + rfvx      # R_int 0 (worst), chain 3, chafe 0, lead 10.3, R_s 10 mOhm
    print(f"  R_int 0, R_FVX {rfvx*1e3:4.0f} mOhm: {8.4/r:6.1f} A at 8.4 V")
print("  -> interrupting rating >= 300 A DC at >= 32 V covers every case with R_FVX >= 5 mOhm; R_FVX = 0 is non-physical for a 4 A fuse")
print(f"     (R_FVX 5 mOhm: {8.4/(0.0233+0.005):5.1f} A)")

# ---------------------------------------------------------------------------------------------------------------
hdr(9, "R_MD duty (BT4-TR-03, FM4-3)")
print(f"  limit cycle 79-184 ms period (bt4_transient_sim section 1): {1/0.079:4.1f} Hz x 51 mJ = {0.051/0.079:4.2f} W mean for 30 s")
print("  stuck-on dump in a regen pulse: 0.46-1.45 J per pulse (fmea_round4 section 1); detected before the first regen window")
print("  of the next power cycle by ERR_MOD_DUMP_ON; within one drive R_MD may fail open (row F49, ERR_MOD_DRAIN)")

# ---------------------------------------------------------------------------------------------------------------
hdr(10, "ERR_IPACK_PLAUS gain band (BT4-TR-02)")
worst_lo, worst_hi = 9.0, 0.0
for ibt_meas in (1.0, 2.0, 4.0):
    for vb in (7.4, 8.4):
        for eta in (0.85, 0.95):
            for il in (0.1, 0.3):
                for floor in (-0.1, 0.1):
                    true_dis = (ibt_meas + floor) * 16.0 / (eta * vb) + il
                    pred = ibt_meas * 16.0 / (0.90 * vb) + 0.2
                    q = true_dis / pred
                    worst_lo, worst_hi = min(worst_lo, q), max(worst_hi, q)
print(f"  healthy I_PACK1/predicted over BT_CURRENT 1-4 A, V_batt 7.4-8.4 V, eta 0.85-0.95 (ASSUMED), I_L 0.1-0.3 A,"
      f" INA253 floor +/-0.1 A: {worst_lo:5.3f}-{worst_hi:5.3f}")
print("  -> band 0.75-1.30 (TODO(calibrate) at C-2/W1 with eta_cal and I_L,cal) has margin on both sides; a common-mode")
print("     gain loss of more than about 25 % on U_SH1 latches; U_SH2 is checked by ERR_IPACK_XCHK against U_SH1")

# ---------------------------------------------------------------------------------------------------------------
hdr(11, "Idle-entry CH settle (BT4-LS-01)")
print("  CH permits up to 0.238-0.381 s after the pulse peak (bt4_logic_seq_enum section 2); settle rule: both CH bits L on")
print("  settled reads for 100 ms, deadline 1 s after Idle entry -> earliest k_idle sample at release + 0.1 s with V-MOT at")
print("  bus level (excess integral 0, k_idle 1.000); a Finish at the peak completes step 10 by 0.48 s < 1 s deadline")
