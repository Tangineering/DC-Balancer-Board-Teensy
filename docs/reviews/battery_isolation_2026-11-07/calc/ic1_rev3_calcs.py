"""IC1 detailed design, revision 3: supporting calculations.

Stdlib only. Run:  python ic1_rev3_calcs.py
Every input carries its primary citation in a comment. Outputs are cited in
detailed_design_IC1.md as "calc/ic1_rev3_calcs.py section N".
"""
import itertools
import math


def hdr(n, title):
    print()
    print("=" * 78)
    print(f"Section {n}: {title}")
    print("=" * 78)


# ---------------------------------------------------------------------------
# 1. HR1 / HR2 power envelope of the Ag105 at 2S (rev 2 Table 8 re-run)
# ---------------------------------------------------------------------------
hdr(1, "Ag105 code envelope with the unregulated VBT load I_L")
ETA = 0.88            # Ag105 DS V1.1 p.20 row 1 (12 V in, 3S only)
ETA_LOW = 0.80        # sensitivity case, assumption
I_RATING = 2.5        # Ag105 max setting, Table 4 JSON code 1
CODES = {1: 2.5, 2: 2.0, 3: 1.75, 4: 1.5, 5: 1.25, 6: 1.0}  # Table 4 JSON
VPACK = [7.4, 7.8, 8.1, 8.2, 8.4]
for window, i_l in (("FC  (BT_BUS open)", 0.3), ("regen (BT_BUS closed)", 0.6)):
    print(f"-- {window}: I_L = {i_l} A (UNCONFIRMED working value, gate B8)")
    for code, iset in CODES.items():
        io = iset + i_l
        legal = io <= I_RATING + 1e-9
        p = [io * v / ETA for v in VPACK]
        p80 = [io * v / ETA_LOW for v in VPACK]
        print(f"   code {code} I_set {iset:4.2f} A  I_o {io:4.2f} A  legal={legal!s:5}  "
              f"P_in(eta .88) @7.4/7.8/8.1/8.2/8.4 V = "
              + "/".join(f"{x:4.1f}" for x in p)
              + "  (eta .80: " + "/".join(f"{x:4.1f}" for x in p80) + ")")
print("-- ceiling at I_o = 2.5 A:", "/".join(f"{2.5*v/ETA:4.1f}" for v in VPACK), "W")
v23 = 23.0 * ETA / 2.5
print(f"-- pack voltage at which 2.5 A reaches 23 W: {v23:.2f} V (eta 0.88)")
i_needed = 18.9 * ETA / 7.4
print(f"-- I_o needed for the 18.9 W peak at 7.4 V: {i_needed:.3f} A")

# FC window bus current, code 5, I_L 0.3 A
print("-- FC window bus current at 16 V, code 5 (1.25 A) + I_L 0.3 A, plus aux 0.15 A")
for v in (7.4, 8.0, 8.4):
    p_in = (1.25 + 0.3) * v / ETA
    i_bus = p_in / 16.0
    print(f"   V_pack {v}: P_in {p_in:5.2f} W  I_bus {i_bus:5.3f} A  + aux 0.15 = {i_bus+0.15:5.3f} A"
          f"  headroom to 1.247 A P_MAX {1.247-i_bus-0.15:+.3f} A")

# ---------------------------------------------------------------------------
# 2. VMOT_OK channel (graft G1): divider, hysteresis, tolerance
# ---------------------------------------------------------------------------
hdr(2, "VMOT_OK channel: thresholds and worst-case tolerance")
# Values (E96/E192, 0.1 %):
R_M1, R_M2, R_M3 = 99.8e3, 13.6e3, 715.0      # V-MOT divider (R_M1 = 2 x 49.9k in series); R_M3 shorted by Q_H when NOT OK
R_B1, R_B2, R_O = 99.8e3, 14.9e3, 301e3       # VBUS divider (R_B1 = 2 x 49.9k); R_O from comparator REF to bus tap
RDS_QH = 6.0                                  # BSS138 R_DS(on) max at V_GS 4.5 V, onsemi BSS138/D p.2
VREF_NOM, VREF_MIN, VREF_MAX = 1.242, 1.223, 1.260   # TLV3011B, SBOS300C sec 6.9
VOS_MAX = 9e-3                                # TLV3011B, SBOS300C sec 6.9 (-40..125 C, VCM = V-)
VHYS_MAX = 8e-3                               # TLV3011B built-in hysteresis 2-8 mV, sec 6.9
TOL = 1e-3                                    # 0.1 % resistors (design requirement)


def thresholds(rm1, rm2, rm3, rb1, rb2, ro, vref, vos, hys, vb):
    r_hi = (rm2 + rm3) / (rm1 + rm2 + rm3)                    # OK state (Q_H off)
    rm3s = rm3 * RDS_QH / (rm3 + RDS_QH)                      # Q_H on (NOT OK)
    r_lo = (rm2 + rm3s) / (rm1 + rm2 + rm3s)
    g = 1 / rb1 + 1 / rb2 + 1 / ro
    tap_b = (vb / rb1 + vref / ro) / g
    # assert: V-MOT tap must exceed bus tap + vos + hys
    v_assert = (tap_b + vos + hys) / r_lo
    v_release = (tap_b + vos) / r_hi
    return v_assert, v_release


nom = {vb: thresholds(R_M1, R_M2, R_M3, R_B1, R_B2, R_O, VREF_NOM, 0, 0, vb)
       for vb in (0.0, 13.5, 15.9, 16.0, 16.5, 17.5)}
for vb, (a, r) in nom.items():
    print(f"   nominal VBUS {vb:5.1f} V: assert {a:6.3f} V ({a/vb if vb else float('nan'):.4f} x)  "
          f"release {r:6.3f} V ({r/vb if vb else float('nan'):.4f} x)")

worst = {}
for vb in (13.5, 15.9, 16.0, 16.5, 17.5):
    amin, amax, rmin, rmax = 1e9, -1e9, 1e9, -1e9
    for s in itertools.product((-1, 1), repeat=6):
        vals = [x * (1 + si * TOL) for x, si in zip((R_M1, R_M2, R_M3, R_B1, R_B2, R_O), s)]
        for vref in (VREF_MIN, VREF_MAX):
            for vos in (-VOS_MAX, VOS_MAX):
                for hys in (0.0, VHYS_MAX):
                    a, r = thresholds(*vals, vref, vos, hys, vb)
                    amin, amax = min(amin, a), max(amax, a)
                    rmin, rmax = min(rmin, r), max(rmax, r)
    worst[vb] = (amin, amax, rmin, rmax)
    print(f"   worst VBUS {vb:5.1f} V: assert {amin:6.3f}..{amax:6.3f} V  release {rmin:6.3f}..{rmax:6.3f} V"
          f"  release margin above VBUS >= {rmin-vb:+.3f} V")
# zero-input fail-safe: bus tap offset vs comparator offset
g = 1 / R_B1 + 1 / R_B2 + 1 / R_O
off_tap_min = (VREF_MIN / (R_O * (1 + TOL))) / (1 / (R_B1 * (1 - TOL)) + 1 / (R_B2 * (1 - TOL)) + 1 / (R_O * (1 + TOL)))
print(f"   zero-input bus-tap offset (min) {off_tap_min*1e3:.1f} mV vs V_OS max {VOS_MAX*1e3:.0f} mV"
      f" -> NOT OK at V-MOT = VBUS = 0: {off_tap_min > VOS_MAX}")
tap_max = 28.0 * (R_M2 + R_M3) / (R_M1 + R_M2 + R_M3)
print(f"   V-MOT tap at the 28 V OV_RGN limit: {tap_max:.2f} V (TLV3011B CM max V+ + 0.2 = 5.2 V at 5 V)")
print(f"   VESC peak 21.20 V min (facts_prior sec 6) vs worst assert at 17.5 V bus {worst[17.5][1]:.3f} V:"
      f" margin {21.20-worst[17.5][1]:+.2f} V")
print("   No-limit-cycle condition: Ag105 threshold (18.0 V default, DS p.10, tolerance UNKNOWN)"
      " must exceed the release maximum:")
for vb in (16.0, 16.5, 17.5):
    print(f"      VBUS {vb}: release max {worst[vb][3]:.3f} V -> margin to 18.0 V {18.0-worst[vb][3]:+.3f} V")
# release race: V-MOT fall rate with the charger drawing
for c_mf in (0.48, 0.97, 4.0):
    for p in (19.8, 22.4):
        i_in = p / 18.0
        rate = i_in / (c_mf * 1e-3) / 1e3   # V/ms
        t_us = (worst[16.0][2] - 16.0) / rate * 1e3
        print(f"   C_VMOT {c_mf} mF, P_in {p} W: fall {rate:5.2f} V/ms; time from release-min to VBUS {t_us:6.0f} us")

# ---------------------------------------------------------------------------
# 3. Ag105 resistor-mode networks (graft G6)
# ---------------------------------------------------------------------------
hdr(3, "RCS and MPPTS networks")
par = lambda a, b: a * b / (a + b)
r_fc = par(62e3, 39.2e3)
print(f"   RCS: 62k alone = code-3 equivalent (1750 mA, Table 4 JSON); 62k || 39.2k = {r_fc/1e3:.2f} k"
      f" (Table 4 JSON 24k = 1250 mA; error {100*(r_fc-24e3)/24e3:+.2f} %)")
for name, r in (("62k open (base resistor lost)", None), ("62k + switch stuck on", r_fc),
                ("39.2k leg open", 62e3), ("CS shorted to Vin-", 0.0)):
    print(f"      fault '{name}': R = {('open' if r is None else f'{r/1e3:.1f} k')}")
def v_mppt(r):     # DS p.10: R = 20e3 * (36 / (47 - V) + 1)  ->  V = 47 - 36 / (R/20e3 - 1)
    return 47 - 36 / (r / 20e3 - 1)
def r_mppt(v):
    return 20e3 * (36 / (47 - v) + 1)
for v in (11.0, 13.6, 13.82, 18.0, 33.0):
    print(f"   MPPTS for {v:5.2f} V: {r_mppt(v)/1e3:6.2f} k")
for r in (41.2e3, 41.7e3, 42.2e3):
    print(f"   MPPTS {r/1e3:.1f} k -> {v_mppt(r):5.2f} V; +/-0.1 % -> "
          f"{v_mppt(r*0.999):5.2f}..{v_mppt(r*1.001):5.2f} V")
print("   Bus 16.0 V, D-BC-FC 35 mV regulation (RT1987 DS-00 sec 13), eFuse 45 mOhm max at 85 C (SLVSE94G sec 6.5)"
      f" x 1 A: input = {16.0-0.035-0.045:.2f} V; margin to 13.82 V = {16.0-0.08-13.82:.2f} V")

# ---------------------------------------------------------------------------
# 4. Charge pump (graft G4), recomputed from IC5 round-1 values
# ---------------------------------------------------------------------------
hdr(4, "Pumped arm: hold voltage and hang-to-off time")
T_LOOP = 1.131e-3                 # median loop, facts_firmware sec 8
f = 1 / (2 * T_LOOP)
VDRV = 4.9                        # AHCT1G125 VOH at 5 V: TODO(verify), IC5 sec 3.2 working value
VF = 0.32                         # BAT54 VF max at 1 mA, BAT54LT1/D Rev 18 p.2 (via IC5 Table 2)
R1, C1, R2, C2 = 470.0, 1e-6, 47e3, 1e-6
ILEAK = 5e-6                      # SN74LVC1G17 I_I max, SCES351Y sec 5.5 (via IC5)
transfer = 1 - math.exp(-(T_LOOP) / (R1 * C1))
k = f * C1 * R2
vh = (VDRV - 2 * VF) * transfer * k / (1 + k)
print(f"   f = {f:.0f} Hz, per-edge transfer {transfer:.3f}, k = {k:.1f}, V_H = {vh:.3f} V"
      f" (+/-{ILEAK*R2:.3f} V leakage)")
VTP_MAX, VTM_MIN, VTM_MAX = 2.08, 1.01, 1.35   # LVC1G17 at 3.3 V, interpolated (IC5 sec 3.2, UNCONFIRMED)
print(f"   ON margin {vh-ILEAK*R2-VTP_MAX:.3f} V")
tau = R2 * C2
t_fast = tau * math.log((vh + ILEAK * R2) / (VTM_MAX + ILEAK * R2))
t_slow = tau * math.log((vh + ILEAK * R2) / (VTM_MIN - ILEAK * R2))
print(f"   hang to PUMP_OK low: {t_fast*1e3:.0f}..{t_slow*1e3:.0f} ms")
vgap = -ILEAK * R2 + (vh + ILEAK * R2) * math.exp(-9.76e-3 / tau)
print(f"   after the worst measured 9.76 ms gap: H >= {vgap:.2f} V (stays above VT- max {VTM_MAX})")
kmin = None
for fq in range(1, 500):
    kk = fq * C1 * R2
    v = (VDRV - 2 * VF) * (1 - math.exp(-(1 / (2 * fq)) / (R1 * C1))) * kk / (1 + kk)
    if v - ILEAK * R2 > VTP_MAX:
        kmin = fq
        break
print(f"   minimum pump frequency for ON: {kmin} Hz (mean loop <= {1e3/(2*kmin):.1f} ms)")

# ---------------------------------------------------------------------------
# 5. eFuse SHDN levels, dVdT, IMON (TPS26631, SLVSE94G Jun 2024)
# ---------------------------------------------------------------------------
hdr(5, "TPS26631 enable, slew and limits")
print(f"   SHDN_EF high from an LVC output through 1k into 22k: {3.3*22/23:.2f} V (V_SHUTR max 2 V)")
print(f"   SHDN_EF with the gate output high-Z: 10 uA x 22k = {10e-6*22e3:.2f} V (V_SHUTF min 0.8 V)")
for cdvdt in (10e-9, 22e-9):
    slew_nom = 25 * 2e-6 / cdvdt / 1e3       # GAIN_dVdT 25, I_dVdT 2 uA, sec 6.5
    slew_min = 23.5 * 1.775e-6 / cdvdt / 1e3
    slew_max = 26 * 2.225e-6 / cdvdt / 1e3
    ton = 742 + 49.5 * cdvdt * 1e9
    print(f"   C_dVdT {cdvdt*1e9:.0f} nF: slew {slew_min:.2f}/{slew_nom:.2f}/{slew_max:.2f} V/ms,"
          f" UVLO turn-on delay {ton:.0f} us, 0->18 V {18/slew_nom:.1f} ms,"
          f" inrush per 100 uF {0.1e-3*slew_max*1e3:.2f} A")
print("   I_OL (R_ILIM 9k): 1.84/2.00/2.16 A; tSD(dly) 0.8/1/1.5 us; latch-off (MODE open) Table 8-1")
print(f"   P_in bound at I_OL max x 21.47 V = {2.16*21.47:.1f} W")
print("   UVLO divider 100k/13k:", f"rising {1.2*113/13:.2f} V, falling {1.122*113/13:.2f} V")

# ---------------------------------------------------------------------------
# 6. Pack-current trips U_C1 / U_C2 and the BT-loop detector D5
# ---------------------------------------------------------------------------
hdr(6, "Comparator thresholds")
K = 100 * 0.5e-3      # INA240A3 100 V/V (SBOS662C sec 7.5) x 0.5 mOhm -> V/A
err_v = math.sqrt(0)  # placeholder
terms = {
    "TLV3011B V_OS 9 mV": 9e-3 / K,
    "INA240 V_OS 25 uV": 25e-6 / 0.5e-3,
    "INA240 ref divider 0.1 % of 1.65 V": 1.65e-3 / K,
    "threshold divider 0.1 % (two resistors)": 2 * 1e-3 * 1.5 / K / 2,
}
for name, v in terms.items():
    print(f"   {name}: {v:.3f} A")
lin = sum(terms.values())
for nm, ith in (("U_C1 discharge", 3.0), ("U_C2 charge", 3.2)):
    print(f"   {nm} {ith} A: worst linear sum +/-{lin:.2f} A plus gain 0.2 % and R_SH tolerance"
          f" (+/-{ith*0.002:.3f} A + TODO(verify) shunt) -> {ith-lin-ith*0.012:.2f}..{ith+lin+ith*0.012:.2f} A with a 1 % shunt")
print(f"   I_PACK ADC: {3.3/4095*1e3:.3f} mV/count = {3.3/4095/K*1e3:.1f} mA/count")
# D5: INA253A1 0.1 V/A, offset floor 10 mV (facts_prior sec 10 item 11), TLV3011B 9 mV
th = 0.5
print(f"   D5 BT-loop: threshold {th} A = {th*0.1*1e3:.0f} mV; trip range "
      f"{th-(0.010+0.009)/0.1:.2f}..{th+(0.009)/0.1:.2f} A (INA253 floor lowers the trip current)")

# ---------------------------------------------------------------------------
# 7. Status ladders (graft G10)
# ---------------------------------------------------------------------------
hdr(7, "5-bit R-2R status ladders")
VCC = 3.3
step = VCC / 32
print(f"   step {step*1e3:.1f} mV, half step {step*1e3/2:.1f} mV")
# error: 2R = 40.2k vs 2 x 20.0k (0.5 % mismatch) and MSB VOH droop 0.1 V worst spec
mis = 0.005 * VCC
voh = 0.1 * 0.5
print(f"   mismatch error <= ~{mis*1e3:.0f} mV; VOH worst-spec droop on MSB {voh*1e3:.0f} mV;"
      f" sum {1e3*(mis+voh):.0f} mV vs half step {step*1e3/2:.0f} mV -> calibrate per code (C-2)")
print(f"   ADC source impedance R = 20k with 100 nF at the pin: tau {20e3*100e-9*1e3:.1f} ms")

# ---------------------------------------------------------------------------
# 8. Return path: ground offset and series-resistance budget (graft G9)
# ---------------------------------------------------------------------------
hdr(8, "Return path")
R_CONTACT = 20e-3            # TB005-762 p.1, max
R_LEAD_SOLDER = 0.3 * 5.21e-3 + 0.5e-3   # 0.3 m AWG 12 (5.21 mOhm/m, standard copper table) + 2 joints, estimate
for label, r in (("J-BT pin 2 screw only", R_CONTACT + 0.3 * 5.21e-3),
                 ("with G9 soldered parallel lead", par(R_CONTACT + 0.3 * 5.21e-3, R_LEAD_SOLDER))):
    for i in (7.2, 17.1):
        print(f"   {label}: R {r*1e3:5.2f} mOhm, I {i:5.1f} A -> SB ground below PCB GND by {i*r*1e3:5.0f} mV")
print("   BSS138 V_GS(th) min 0.8 V (BSS138/D p.2): Q_A 'off' with LB low = offset; margin "
      f"{0.8-17.1*(R_CONTACT+0.3*5.21e-3):.2f} V (screw only), "
      f"{0.8-17.1*par(R_CONTACT+0.3*5.21e-3,R_LEAD_SOLDER):.2f} V (with G9)")
new_series = 1.2e-3 + 0.5e-3   # S_GND pair hot + R_SH
print(f"   new series elements excluding fuse/terminals: {new_series*1e3:.1f} mOhm of the 12.9 mOhm budget"
      f" (rev 2 sec 4.1)")
v_lm = 7.4 - 17.1 * (R_CONTACT + R_CONTACT) - 17.1 * 12.9e-3
print(f"   VBT-GND at 7.4 V, 17.1 A, two contacts + full budget: {v_lm:.2f} V (LM1084 needs 6.5 V)")

# ---------------------------------------------------------------------------
# 9. Timing budgets
# ---------------------------------------------------------------------------
hdr(9, "Timing budgets")
print("   pump stop -> PUMP_OK low -> N1 -> FF1 clear -> eFuse off:"
      f" {t_fast*1e3:.0f}..{t_slow*1e3:.0f} ms + 1.5 us")
print("   VOK release -> eFuse off: tap RC 13 us (13.6k||100k x 1 nF ~ 12 us) + t_PD 4 us + gates <0.1 us + tSD 1.5 us"
      " = about 18 us")
tap_tau = par(R_M1, R_M2 + R_M3) * 1e-9
print(f"   V-MOT tap RC with 1 nF: {tap_tau*1e6:.1f} us")
print("   U_C trip -> eFuse off: 70 us filter (1.5k x 47 nF) + 4 us + 1.5 us ~ 76 us; S_GND gate rise tau 88-114 us")
print("   D-BT-SQ release after FF1 set: X node tau 4.7 ms (~5 ms) + t_D_ON 8 ms typ (no max) = ~13 ms")
xd = 10e3 * 100e-9
print(f"   D-BT-SQ cross-lock on exit: X node 10k x 100 nF tau {xd*1e3:.1f} ms -> 0.3-0.7 ms to EN < 0.6 V (rev 2)")
for dt, label in ((0.0, "entry on first negative command"), (40e-3, "[RER] 40 ms arm dwell")):
    print(f"   regen: {label}: FF1 at {dt*1e3+1.13:.0f} ms; first V-MOT pulse peaks at 19-47 ms (facts_prior sec 6)")

# ---------------------------------------------------------------------------
# 10. Optional hold-up C_HU (stage 3)
# ---------------------------------------------------------------------------
hdr(10, "Stage-3 hold-up on the eFuse output (UNCONFIRMED Ag105 behaviour)")
I_IDLE = 18e-3     # Ag105 idle input current max, DS p.20 row 4
for t_gap, v0, label in ((0.535, 18.0, "regen pulse spacing"), (0.140, 13.82, "H-20 purge, FC threshold")):
    c = I_IDLE * t_gap / (v0 - 11.0)
    print(f"   {label}: hold {t_gap*1e3:.0f} ms from {v0} V to 11 V UVLO at 18 mA: C_HU >= {c*1e3:.2f} mF;"
          f" stored {0.5*c*v0**2:.2f} J")
