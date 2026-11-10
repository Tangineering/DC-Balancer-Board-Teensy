"""Battle-test round 1, transient/numerical lens: time-domain checks of detailed_design_IC1.md rev 3.

Stdlib only. Run:  python bt1_transient_sim.py
Every input cites its primary (design doc section, fact sheet, or datasheet).  Explicit Euler, dt noted per section.
"""
import math

def hdr(n, t):
    print("\n" + "=" * 78 + f"\nSection {n}: {t}\n" + "=" * 78)

# ---------------------------------------------------------------------------
# 1. Status-ladder settling vs the 1 ms / 2 ms confirmation deadlines
# ---------------------------------------------------------------------------
hdr(1, "R-2R ladder settling (design 5.2 Fig.5, 7.7; calc ic1_rev3 sec 7)")
VCC = 3.3
STEP = VCC / 32                 # 103.1 mV LSB (design 7.7)
TAU = 20e3 * 100e-9             # R-2R output impedance R = 20.0k x C_LA 100 nF (ic1_rev3 calc sec 7: 2.0 ms)
WIN = 0.030                     # decode window +/-30 mV (design 7.7)
def settle(bits):
    dv = sum(STEP * 2 ** b for b in bits)
    return dv, TAU * math.log(dv / WIN)

def mis_window(bits, dt=1e-6):
    """walk the exponential; time spent decodable-but-wrong and undecodable before the final code is reached"""
    dv = sum(STEP * 2 ** b for b in bits)
    t, wrong, undec = 0.0, 0.0, 0.0
    longest_bad = cur = 0.0
    while True:
        e = dv * math.exp(-t / TAU)
        if e < WIN:
            break
        r = e % STEP
        near = min(r, STEP - r)
        if near < WIN:
            wrong += dt
        else:
            undec += dt
        cur += dt
        t += dt
    return wrong, undec, t

cases = [
    ("entry: ladder B SG1_ON+SG2_ON fall (bits 0,1)", [0, 1], "9.5 step 4 / 9.7 step 3: confirm within 2 ms"),
    ("entry: ladder A FF1.Q rises (bit 0)", [0], "9.5 step 4: confirm within 2 ms"),
    ("exit: ladder A FF1.Q + EF_EN fall (bits 0,1)", [0, 1], "9.5 exit step 3: confirm within 2 ms"),
    ("exit in regen pulse: ladder B SG bits + OK1_N/OK2_N (bits 0-3)", [0, 1, 2, 3], "9.5 exit step 3"),
    ("VOK toggle in a pulse: ladder B OK1_N+OK2_N (bits 2,3)", [2, 3], "12.4 item 4: mismatch/decode fail > 2 ms latches"),
    ("VOK toggle: ladder A EF_EN (bit 1)", [1], "12.4 item 4"),
    ("self-test 5: UC2_N + FF1/SG change (ladder B bits 4,0,1)", [4, 0, 1], "9.3 step 5: within 1 ms"),
    ("self-test 6: UC1_N (ladder A bit 4) + FF1.Q (bit 0)", [4, 0], "9.3 step 6: within 1 ms"),
]
for name, bits, req in cases:
    dv, ts = settle(bits)
    w, u, tt = mis_window(bits, dt=2e-6)
    print(f"   {name}: step {dv*1e3:6.0f} mV -> within 30 mV after {ts*1e3:4.2f} ms "
          f"(wrong-code {w*1e3:4.2f} ms, undecodable {u*1e3:4.2f} ms)  [{req}]")
print("   Traction exit (9.6): 1 loop (1.13 ms, facts_firmware 8) + S_GND rise 0.3 ms + ladder settle "
      f"{settle([0,1])[1]*1e3:.2f} ms = {1.13+0.3+settle([0,1])[1]*1e3:.1f} ms vs claimed <= 5 ms (V2-5 GO)")

# ---------------------------------------------------------------------------
# 2. VOK release race: comparator delay at slow overdrive
# ---------------------------------------------------------------------------
hdr(2, "VOK release race (design 7.2 item 2; Table 11)")
# TLV3011B (SBOS300C 6.10): t_PD 2 typ / 4 max at V_OD = 100 mV only.  No low-overdrive spec for the B part.
# TLV3011 (non-B, SBOS300C 6.8): 6 us @100 mV, 12 us @10 mV (L->H typ) -> fit t = t0 + k/V_OD (proxy, UNCONFIRMED for B)
k = (12 - 6) / (1 / 0.010 - 1 / 0.100)   # us*V
t0 = 6 - k / 0.100
scale = 4.0 / 6.0                        # scale the non-B curve so that 100 mV gives the B max 4 us
R_TOP, R_BOT = 99.8e3, 13.6e3 + 715.0   # design Fig.4
RATIO = R_BOT / (R_TOP + R_BOT)
TAU_TAP = (R_TOP * R_BOT / (R_TOP + R_BOT)) * 1e-9   # 1 nF C_Mk
REL_MARGIN = {16.0: 0.160, 17.5: 0.144}   # worst release above VBUS (ic1_rev3 calc sec 2)
HYS_REL = 4e-3 / RATIO                     # if the 2-8 mV internal hysteresis is centred, release moves down <= 4 mV at the tap
print(f"   proxy fit: t_PD = {t0*scale:.2f} us + {k*scale*1e3:.3f} us*mV / V_OD ;  tap ratio {RATIO:.4f}, tap tau {TAU_TAP*1e6:.1f} us")
print(f"   ic1_rev3 calc sec 2 puts all hysteresis on assert; a centred V_HYS lowers release by up to {HYS_REL*1e3:.0f} mV at V-MOT")

def race(slope_v_per_ms, margin):
    dt = 0.05e-6
    s = slope_v_per_ms * 1e3            # V/s at V-MOT
    t = 0.0; tap = 0.0; integ = 0.0     # tap error relative to threshold (V), overdrive integral
    t_reach_vbus = margin / s
    fired = None
    while t < 2e-3:
        vin_err = s * t * RATIO          # how far the unfiltered tap has gone past the threshold
        tap += (vin_err - tap) * dt / TAU_TAP
        if tap > 0:
            integ += tap * dt           # V*s
        # step-equivalent firing: integral of overdrive reaches k (V*us) after the fixed part
        if integ * 1e6 >= k * scale:
            fired = t + t0 * scale * 1e-6
            break
        t += dt
    t_cut = fired + 0.1e-6 + 1.5e-6     # LVC gates + tSD(dly) max 1.5 us (SLVSE94G 6.6)
    return t_cut, t_reach_vbus

for label, slope in (("charger 22.4 W, 0.48 mF", 2.59), ("charger 22.4 W, 0.97 mF", 1.28),
                     ("VESC draws 5 A, 0.48 mF", 5 / 0.48 + 2.59), ("VESC draws 20 A, 0.48 mF", 20 / 0.48 + 2.59),
                     ("VESC draws 20 A, 4 mF", 20 / 4 + 0.31)):
    for vb, m in REL_MARGIN.items():
        for mm, tag in ((m, "calc margin"), (m - HYS_REL, "centred hys")):
            tc, tr = race(slope, mm)
            feed = max(0.0, tc - tr)
            print(f"   {label:26s} VBUS {vb}: {tag:11s} eFuse off {tc*1e6:5.1f} us, V-MOT at VBUS {tr*1e6:6.1f} us"
                  f" -> bus-fed window {feed*1e6:5.1f} us ({'design claim holds' if feed == 0 else 'claim CONTRADICTED'})")

# ---------------------------------------------------------------------------
# 3. U_C1 trip vs a BT-boost current step in the charge mode
# ---------------------------------------------------------------------------
hdr(3, "Reverse sense current during a BT-boost step in charge mode (design 9.6, F8, S0-9/S0-10)")
# VBT input caps only C1-BT 10 uF (facts_board line 82) -> pack current ~ boost input current.
# L-BT 2.2 uH (facts_board 82): max di/dt ~ 7.4 V / 2.2 uH = 3.4 A/us; loop-limited ramps 20-200 us assumed.
# Peak 16.46 A (facts_prior 6, incident).  Sense path: R_s (unknown, BENCH S0-1; swept) + S_CHG 1.6 mOhm (SLPS632).
# S_GND body diodes (2 in parallel): V_SD model 0.55 V + 15 mOhm each (CSD18510Q5B 1.0 V max at 32 A, SLPS632) - assumption.
# U_C1: INA240A3 50 mV/A (0.5 mOhm x 100), filter 1.5k/47 nF = 70.5 us, trip 2.67-3.33 A, t_PD 4 us (SBOS300C 6.10).
# S_GND gate: Q_A off then R_GU 10k || 57k into Ciss 8.77-11.4 nF (design 6 item 14); asymptote 0.85 x (VBT_T - SGND).
# Q_D on when G > 0.3 + Vth_QD x 1.47 (Vth 0.8-1.5, BSS138/D) -> S_CHG gate dumped (6 Ohm x 11 nF, ~0.1 us).
def uc1_event(i_pk, t_ramp, r_s, i_trip, ciss, vth_qd, vbt=7.4, dt=0.2e-6):
    tau_f = 1.5e3 * 47e-9
    tau_g = (10e3 * 57e3 / 67e3) * ciss
    t = 0.0; sig = 0.0; trip = None; g = 0.0; schg_on = True
    peak_s = 0.0; i2t = 0.0; t_end = None; vpk = 0.0
    while t < 3e-3:
        i = i_pk * min(1.0, t / t_ramp)
        # split between sense path (resistive) and body diodes (only if drop > 0.55 V)
        rs = r_s + 1.6e-3
        if schg_on:
            i_s = i if i * rs < 0.55 else None
            if i_s is None:   # solve i_s*rs = 0.55 + (i - i_s)*0.0075
                i_s = (0.55 + i * 0.0075) / (rs + 0.0075)
        else:
            i_s = 0.0
        vdrop = i_s * rs if schg_on else 0.55 + i * 0.0075
        vpk = max(vpk, vdrop)
        peak_s = max(peak_s, i_s); i2t += i_s ** 2 * dt
        sig += (i - sig) * dt / tau_f
        if trip is None and sig >= i_trip:
            trip = t + 4e-6
        if trip is not None and t >= trip:
            vasym = 0.85 * (vbt - 16.46 * 0.024 - min(vdrop, 1.0))
            g += (vasym - g) * dt / tau_g
            if schg_on and g >= 0.3 + vth_qd * 1.47:
                schg_on = False; t_end = t
        if not schg_on and t > (t_end or 0) + 50e-6:
            break
        t += dt
    return peak_s, t_end, i2t, vpk

print("   (S0-10 tests 15 A for 1 ms = 0.225 A^2 s; Ag105 DS p.20 row 6 gives 4 A continuous discharge)")
for r_s in (0.005, 0.02, 0.05, 0.1):
    worst = None
    for t_ramp in (20e-6, 50e-6, 200e-6):
        for i_trip in (2.67, 3.33):
            for ciss, vq in ((8.77e-9, 0.8), (11.4e-9, 1.5)):
                pk, te, i2t, vpk = uc1_event(16.46, t_ramp, r_s, i_trip, ciss, vq)
                if worst is None or te > worst[1]:
                    worst = (pk, te, i2t, vpk, t_ramp, i_trip, ciss)
    pk, te, i2t, vpk, tr, it, ci = worst
    print(f"   R_s {r_s*1e3:5.1f} mOhm: worst S_CHG-off at {te*1e6:5.0f} us after onset, sense peak {pk:5.2f} A,"
          f" I^2t {i2t:.4f} A^2 s, PACK- below GND up to {vpk:4.2f} V (ramp {tr*1e6:.0f} us, trip {it} A, Ciss {ci*1e9:.2f} nF)")
# LM1084 headroom during that excursion (pack DCIR 24 mOhm facts_prior 9; two 20 mOhm J-BT contacts facts_board 334)
for dcir in (0.024, 0.060):
    v = 7.4 - 16.46 * dcir - 16.46 * 0.040 - 1.0 * 0
    for vexc in (0.0, 0.8, 1.0):
        print(f"   OCV 7.4 V, DCIR {dcir*1e3:.0f} mOhm, 16.46 A, contacts 40 mOhm, PACK- excursion {vexc:.1f} V:"
              f" VBT-GND = {v - vexc:4.2f} V (LM1084 regulation needs 6.5 V, SNVS037H 5.5)")

# ---------------------------------------------------------------------------
# 4. Regen pulse chain: when does the Ag105 input reach 18 V, vs the VESC stop?
# ---------------------------------------------------------------------------
hdr(4, "Regen pulse timeline vs the S0-6 '15 ms' criterion (design 7.8, 15.1 S0-6)")
# V-MOT pulse 15.9 -> 21.35 V (VESC stop) in 19-47 ms (facts_prior 6); linear approximation.
# Chain: VOK assert 16.90-17.24 V (Table 9) ; t_D_ON 8 ms typ, no max (RT1987 DS-00 13) ;
# D-BC-RG soft start 12.0 V/ms with CSS 5.6 nF (facts_prior 10 item 4) from VCHG-IN = 0 (decays tau ~1 s via R1-CHG||R_UV) ;
# eFuse UVLO 10.43 V then turn-on delay 1.237 ms (ic1_rev3 calc 5) ; eFuse slew 4.17-5.79 V/ms to 18 V (regen threshold).
for t_rise in (19e-3, 47e-3):
    s = (21.35 - 15.9) / t_rise
    for v_ass in (16.90, 17.24):
        t_ok = (v_ass - 15.9) / s
        t_stop = t_rise
        for t_don in (8e-3, 12e-3):
            t_uvlo = t_ok + t_don + 10.43 / 12.0e3
            for slew in (5.79e3, 4.17e3):
                t_18 = t_uvlo + 1.237e-3 + 18.0 / slew
                print(f"   rise {t_rise*1e3:2.0f} ms, assert {v_ass:5.2f} V (t {t_ok*1e3:4.1f} ms), t_D_ON {t_don*1e3:2.0f} ms, eFuse "
                      f"{slew/1e3:4.2f} V/ms: Ag105 input at 18 V at {t_18*1e3:5.1f} ms; VESC stop {t_stop*1e3:4.1f} ms;"
                      f" budget for cold start + current rise {(t_stop - t_18)*1e3:+5.1f} ms")
print("   facts_prior 6 warm-response requirement: tau_warm <= 2 ms (board C) / 4 ms (0.97 mF); S0-6 GO says <= ~15 ms")

# ---------------------------------------------------------------------------
# 5. FF1 set race: /CLR release (N1 via R_N1) vs CLK (R_CK/C_CK)
# ---------------------------------------------------------------------------
hdr(5, "FF1 set race (design Fig.2; Table 11 row 1)")
# N1 node: R_N1 10k to 3V3; capacitance = 5 BAT54 (C_T <= 10 pF at 1 V, BAT54LT1/D; larger at 0 V) + Q_D5, Q_OV drains
# (BSS138 Coss, UNCONFIRMED ~10-13 pF) + LVC74 input + trace.  Starts at ~0.25 V (BAT54 VF at 0.33 mA).
# CLK: R_CK 1k (1 %) x C_CK 1 nF (C0G 5 %).  LVC74 V_IL 0.8 / V_IH 2.0 V at 3.3 V (SCES794G TODO(verify)); same die threshold Vt.
for cn in (70e-12, 100e-12, 130e-12):
    for vt in (0.8, 1.4, 2.0):
        t_clr = 10e3 * cn * math.log((3.3 - 0.25) / (3.3 - vt))
        t_clk = 1e3 * 0.95e-9 * math.log(3.3 / (3.3 - vt))
        print(f"   C_N1 {cn*1e12:3.0f} pF, Vt {vt:.1f} V: /CLR released {t_clr*1e6:4.2f} us, CLK edge {t_clk*1e6:4.2f} us,"
              f" margin {(t_clk - t_clr)*1e6:+5.2f} us {'(FF1 FAILS TO SET)' if t_clk <= t_clr else ''}")

# ---------------------------------------------------------------------------
# 6. D5 arming delay
# ---------------------------------------------------------------------------
hdr(6, "D5 arming (design Fig.3, Table 11 '10 ms')")
# FCQ = 3.3 V x 100k/101k ; R_D5d 100k / C_D5d 100 nF ; Q_D5 conducts when gate - D5_N(0 V) > Vth 0.8-1.5 V (BSS138/D)
vf = 3.3 * 100 / 101
for vth in (0.8, 1.5, 2.0):
    print(f"   Q_D5 gate reaches {vth} V after {10e-3*math.log(vf/(vf-vth))*1e3:4.1f} ms (claimed arming delay 10 ms)")

# ---------------------------------------------------------------------------
# 7. FC-window eFuse inrush vs the FC-only bus OC_FC single-sample latch
# ---------------------------------------------------------------------------
hdr(7, "eFuse inrush into the Ag105 input in an FC window (design 7.5, C-3, S0-11)")
# Ag105 input C unknown (TODO(verify: Silvertel)); DS p.6 advises 470 uF across the input for long leads (facts_prior 4.2).
# I_OL 1.84-2.16 A (SLVSE94G 6.5); OC_FC 1.4 A single sample (design F23); aux 0.15 A (Table 8).
for c in (22e-6, 100e-6, 220e-6, 470e-6):
    i = (c + 1e-6) * 5.79e3
    i_fc = min(i, 2.16) + 0.15
    print(f"   C_in {c*1e6:4.0f} uF: inrush {i:4.2f} A (I_OL caps at 1.84-2.16 A); FC-only bus {i_fc:4.2f} A"
          f" {'-> OC_FC latch (State 99)' if i_fc > 1.4 else ''}")
