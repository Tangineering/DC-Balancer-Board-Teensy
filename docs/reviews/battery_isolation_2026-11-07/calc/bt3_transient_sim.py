"""Battle-test round 3, transient / numerical lens, against detailed_design_IC1.md revision 5.

Stdlib only. Run: python bt3_transient_sim.py > bt3_transient_sim_output.txt
Every input cites its primary or is tagged ASSUMED. DD = detailed_design_IC1.md (rev 5).

Sections
 1. VOK channel disagreement on a V-MOT pulse that peaks between the two channels' assert levels
    (ERR_VOK_STUCK 50 ms primary rule, DD 12.6 Table 16; calc5 section 6 analysed only the both-assert case).
 2. Ag105 input hold-up after the eFuse cut under the threshold-stop behaviour that gate S0-5 requires
    (DD 15.1 S0-5 GO; DD 7.2 item 5) against the convert-to-11-V model of calc5 section 10 (T_drain).
 3. eFuse-blocking probe (DD 9.7a): module input voltage after T_hold, and ERR_VCHG_FED after its blanking,
    as a function of the unspecified MINIMUM Ag105 idle current (DS p.20 row 4 gives 18 mA MAXIMUM only).
 4. Warm re-entry: eFuse input = C_mod x dV/dt + warm module draw, against the U_IM trip (DD 5.2, calc5 section 9).
 5. Traction onset in a charge-mode window: reverse sense pulse duration against gate S0-10 (17 A, 0.5 ms).
 6. VOK release race: D-MT-EN bus feed duration including the tap-filter lag (DD 7.2 item 2 claims ~12 us).
"""
import math

def hdr(n, t):
    print(f"\n[{n}] {t}")

# ---------------------------------------------------------------------------
hdr(1, "VOK single-channel assert on a pulse peaking between the channel assert levels")
# Divider, DD Figure 4: V-MOT tap R_Mk1a + R_Mk1b = 99.8k; R_Mk2 13.6k; R_Mk3 715 shorted by Q_Hk when NOT OK.
R_M1, R_M2, R_M3 = 99.8e3, 13.6e3, 715.0
k_notok = R_M2 / (R_M1 + R_M2)                 # Q_H on (NOT OK): assert ratio
k_ok = (R_M2 + R_M3) / (R_M1 + R_M2 + R_M3)    # Q_H off (OK): release ratio
# Bus tap: R_Bk1 99.8k, R_Bk2 14.9k, R_Ok 301k to REF.
R_B1, R_B2, R_O = 99.8e3, 14.9e3, 301e3
def bt(vbus, ref):
    return (vbus / R_B1 + ref / R_O) / (1 / R_B1 + 1 / R_B2 + 1 / R_O)
for ref in (1.223, 1.242, 1.260):               # SBOS300C REF range (DD Table 7)
    b = bt(16.0, ref)
    print(f"   REF {ref:.3f} V: BT {b:.4f} V; assert {b/k_notok:6.3f} V, release {b/k_ok:6.3f} V "
          f"(release/assert {k_notok/k_ok:.4f})")
hyst_ratio = k_notok / k_ok
print(f"   hysteresis = assert x {1-hyst_ratio:.4f} = {17.0*(1-hyst_ratio):.3f} V at a 17.0 V assert")
print("   DD Table 9 at VBUS 16.0 V: assert 16.90-17.24 V, release 16.16-16.43 V (all tolerance corners)")

def disagreement(a1, a2, vp, r_up, r_dn, v0=15.9):
    """Linear rise from v0 at r_up (V/s) to vp, then linear decay at r_dn (V/s). Channel k asserts at a_k on the
    rise and releases at a_k*hyst_ratio on the fall. Return the longest interval (s) in which exactly one channel
    permits."""
    dt = 1e-5
    t, v, rising = 0.0, v0, True
    s1 = s2 = False
    run = best = 0.0
    while True:
        if rising:
            v += r_up * dt
            if v >= vp:
                v, rising = vp, False
        else:
            v -= r_dn * dt
        s1 = (v >= a1) if not s1 else (v > a1 * hyst_ratio)
        s2 = (v >= a2) if not s2 else (v > a2 * hyst_ratio)
        if s1 != s2:
            run += dt
            best = max(best, run)
        else:
            run = 0.0
        t += dt
        if not rising and v < min(a1, a2) * hyst_ratio - 0.05:
            return best

A1 = 16.90
print("   Peak inside [A1, A2): only channel 1 asserts; it holds until V-MOT falls to its own release, 0.75 V lower.")
print("   Rise 58-252 V/s (second-pulse and first-pulse dV/dt, regen_dynamics.md 1.1); decay 14.2-20.1 V/s")
print("   (sink slope after the command ends, regen_dynamics.md 1.1; facts_prior 6). ERR_VOK_STUCK dwell 50 ms.")
for d in (0.05, 0.11, 0.34):
    A2 = A1 + d
    rows = []
    for r_dn in (8.0, 14.2, 17.0, 20.1):
        worst = 0.0
        n_latch = n_tot = 0
        vp = A1 + 0.005
        while vp < A2:
            dd = disagreement(A1, A2, vp, 58.0, r_dn)
            worst = max(worst, dd)
            n_tot += 1
            n_latch += dd >= 0.050
            vp += 0.01
        rows.append(f"decay {r_dn:4.1f} V/s: longest {worst*1e3:5.1f} ms, peaks latching {n_latch}/{n_tot}")
    print(f"   channel spread d = {d:.2f} V (band {A1:.2f}-{A2:.2f} V):")
    for r in rows:
        print("      " + r)
# Both-assert case reproduced (calc5 section 6)
dd_both = disagreement(16.90, 17.24, 21.35, 252.0, 14.0)
print(f"   both-assert check (peak 21.35 V, spread 0.34 V, decay 14 V/s): {dd_both*1e3:.1f} ms (calc5 s6: 23.6 ms)")
r_min = (A1 * (1 - hyst_ratio)) / 0.050
print(f"   decay rate needed for the 50 ms dwell to hold on a single-assert pulse: >= {r_min:.1f} V/s "
      f"(DD static_assert: 6.6 V/s; measured sink slope 14.2-20.1 V/s)")
frac_band = 0.34 / (19.0 - 16.8)
print(f"   second-pulse peaks 16.8-19.0 V (regen_dynamics.md 1.1): worst-spread band covers {frac_band*100:.0f} % of that "
      f"range; d = 0.11 V covers {0.11/2.2*100:.0f} %")

# ---------------------------------------------------------------------------
hdr(2, "Ag105 input hold-up after the eFuse cut (threshold-stop model required by S0-5) vs T_drain 2 ms")
C_EO = 1e-6                                  # DD Table 7
V_LOCK = 11.0                                # Ag105 DS p.19 row 2 (typ)
IQ_MAX = 18e-3                               # Ag105 DS p.20 row 4 (max only; no min, no typ)
cases = [("FC window exit, module charging (stops at 13.82 V FC threshold)", 13.82),
         ("FC exit Fully Charged / configuration check (module not drawing: bus 16.0 V)", 16.00),
         ("Regen: eFuse cut at the VOK release (module stopped at 18 V; node follows V-MOT to release)", 16.30)]
for name, v0 in cases:
    print(f"   {name}: V0 {v0:.2f} V")
    for cm in (47e-6, 100e-6, 144e-6, 220e-6):
        c = cm + C_EO
        cells = []
        for iq in (0.5e-3, 1e-3, 2e-3, 5e-3, IQ_MAX):
            t = c * (v0 - V_LOCK) / iq
            cells.append(f"{iq*1e3:4.1f} mA {t*1e3:7.1f} ms")
        e = 0.5 * c * (v0 ** 2 - V_LOCK ** 2)
        print(f"      C_mod {cm*1e6:3.0f} uF: time above the 11 V lockout | " + " | ".join(cells)
              + f" | energy above lockout {e*1e3:4.1f} mJ")
print("   calc5 section 10 model (convert at 14.8-22.4 W down to 11 V): 0.05-1.08 ms -> T_drain 2 ms.")
print("   Under the S0-5 GO behaviour the module stops drawing at its threshold, so after T_drain it is still")
print("   powered for C x dV / I_q: >= 22.7 ms even at I_q 18 mA max (C_mod 144 uF, FC exit), and the")
print("   datasheet gives no lower bound on I_q, so no upper bound on the hold-up.")
iq_needed = (144e-6 + C_EO) * (13.82 - V_LOCK) / 2e-3
print(f"   I_q needed to drain the FC-exit hold-up within T_drain 2 ms at C_mod 144 uF: {iq_needed:.2f} A")

# ---------------------------------------------------------------------------
hdr(3, "eFuse-blocking probe (T_hold 0.5 s, reg 0x07 >= 64 counts = 9.0 V) and ERR_VCHG_FED (1.0 s blanking)")
# Probe: the module node (VCHG-IN_M) is isolated except: module I_q, and the eFuse reverse path OUT->IN
# (B_GATE/DRV open: no reverse blocking, DD 5.3) into VCHG-IN, which bleeds through R1-CHG (49.2 kOhm
# effective, calc5 s5) and R_UV1 + R_UV2 (110.5 kOhm, DD Figure 6). Body-diode drop ASSUMED 0.5 V.
C_VCHG = 20e-6 + 1e-6                         # C-D8 + C-D10 (facts_board 4.4) + C_EI
R_BLEED = 1 / (1 / 49.2e3 + 1 / 110.5e3)
VF = 0.5                                      # ASSUMED
V64 = 64 * 0.141                              # Table 7 JSON reg 0x07 scale; DD 9.7a step 4
print(f"   VCHG-IN bleed {R_BLEED/1e3:.1f} kOhm (R1-CHG path 49.2 k || UVLO divider 110.5 k); reg 0x07 count 64 = {V64:.2f} V")

def decay(v0, cm, iq, t_end, dt=1e-4):
    """Module node with C_mod + C_EO, I_q constant while above 1 V, coupled through VF to VCHG-IN (C_VCHG,
    R_BLEED) while V_mod - VF > V_in. Returns (V_mod, V_in) at t_end."""
    vm, vi = v0, v0 - VF
    t = 0.0
    while t < t_end:
        i_q = iq if vm > 1.0 else 0.0
        # VCHG-IN node: discharged by R_BLEED, recharged from the module node through the body diode
        i_bleed = vi / R_BLEED
        if vm - VF > vi:
            # diode conducts: nodes move together (combined capacitance)
            ctot = cm + C_EO + C_VCHG
            dv = -(i_q + i_bleed) / ctot * dt
            vm += dv
            vi = vm - VF
        else:
            vm -= i_q / (cm + C_EO) * dt
            vi -= i_bleed / C_VCHG * dt
        t += dt
    return vm, vi

print("   Probe: module node voltage after T_hold 0.5 s, configuration check (module not drawing, V0 16.0 V):")
for cm in (47e-6, 100e-6, 144e-6, 220e-6):
    cells = []
    for iq in (0.5e-3, 1e-3, 2e-3, 5e-3, IQ_MAX):
        vm, _ = decay(16.0, cm, iq, 0.5)
        flag = "LATCH" if vm >= V64 else "ok"
        cells.append(f"{iq*1e3:4.1f} mA {vm:5.2f} V {flag}")
    print(f"      C_mod {cm*1e6:3.0f} uF: " + " | ".join(cells))
print("   DD 9.7a: 'step 2 waits more than 5 times the worst hold-up (92 ms)'. The 92 ms of bt2_transient_sim s3")
print("   is computed AT I_q 18 mA MAX, i.e. it is the SHORTEST hold-up; the longest is unbounded by the datasheet.")
for cm in (100e-6, 144e-6, 220e-6):
    # smallest I_q that clears the probe: bisection
    lo, hi = 0.0, 20e-3
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        vm, _ = decay(16.0, cm, mid, 0.5, dt=5e-4)
        if vm >= V64:
            lo = mid
        else:
            hi = mid
    print(f"      C_mod {cm*1e6:3.0f} uF: the probe false-latches ERR_EFUSE_BYPASS for any I_q below {hi*1e3:.2f} mA")
print("   ERR_VCHG_FED after a regen window: V_chg (= VCHG-IN) at the end of the 200 ms dwell + 1.0 s blanking,")
print("   module node at 16.30 V at the VOK release (body-diode back-feed holds VCHG-IN up):")
for cm in (100e-6, 144e-6, 220e-6):
    cells = []
    for iq in (0.0, 0.2e-3, 0.5e-3, 1e-3, 2e-3):
        _, vi = decay(16.30, cm, iq, 1.2, dt=5e-4)
        cells.append(f"{iq*1e3:3.1f} mA {vi:5.2f} V {'LATCH' if vi > 11.0 else 'ok'}")
    print(f"      C_mod {cm*1e6:3.0f} uF: " + " | ".join(cells))
print("   calc5 s5 derived the 1.0 s blanking from VCHG-IN alone (20 uF, tau 0.984 s), not from the module-side")
print("   hold-up that the eFuse's unblocked reverse path couples onto VCHG-IN.")

# ---------------------------------------------------------------------------
hdr(4, "Warm re-entry: eFuse input = C_mod x slew + warm module draw, against U_IM 1.68-1.75 A")
SLEW = (4.17e3, 5.79e3)                       # V/s, DD 7.5 (SLVSE94G 6.3, 6.5, C_DV 10 nF)
UIM = (1.68, 1.75)                            # calc5 section 9 (IMON gain tolerance excluded)
draws = {"FC profile (calc5 s9: 1.07 A eta 0.88 / 1.18 A eta 0.80)": (1.07, 1.18),
         "Regen profile (calc5 s9: 1.24 A eta 0.88 / 1.37 A eta 0.80)": (1.24, 1.37)}
for name, (dlo, dhi) in draws.items():
    print(f"   {name}:")
    for cm in (47e-6, 100e-6, 104e-6):
        ilo = (cm + C_EO) * SLEW[0] + dlo
        ihi = (cm + C_EO) * SLEW[1] + dhi
        verdict = "TRIP" if ihi > UIM[0] else "ok"
        print(f"      C_mod {cm*1e6:3.0f} uF (inrush {(cm+C_EO)*SLEW[0]:.2f}-{(cm+C_EO)*SLEW[1]:.2f} A): "
              f"input {ilo:.2f}-{ihi:.2f} A vs U_IM {UIM[0]}-{UIM[1]} A -> {verdict}")
print("   104 uF is the largest C_mod the S0-11 GO (inrush <= 0.6 A at 5.79 V/ms) admits. The U_IM margin above the")
print("   legitimate draw (0.31-0.51 A) is smaller than the inrush the same gate admits, so the margin holds only")
print("   while the module is cold during the eFuse ramp (65-170 ms cold start). Section 2 shows the module can be")
print("   warm at the next window or the next pulse: hold-up across the 535 ms pulse spacing needs I_q below")
for cm in (100e-6, 144e-6, 220e-6):
    print(f"      C_mod {cm*1e6:3.0f} uF: {(cm+C_EO)*(16.30-V_LOCK)/0.535*1e3:.2f} mA")

# ---------------------------------------------------------------------------
hdr(5, "Traction onset in a charge-mode window: reverse sense pulse")
TAU_F = 70e-6                                 # R_F1/C_F1 (DD Table 7)
for i_step in (5.0, 10.0, 16.5):
    s_final = 1.65 - 0.05 * i_step            # SIG1 (50 mV/A, DD Table 15)
    t_x = -TAU_F * math.log(1 - (1.65 - 1.500) / (1.65 - s_final))
    t_pd = (4e-6, 20e-6)                      # push-pull 4 us at 100 mV; open-drain unspecified (ASSUMED 20 us)
    tau_g = (88e-6, 114e-6)                   # DD Table 11
    vfin = 6.3                                # DD eq. 14
    t_on = [tg * -math.log(1 - v / vfin) for tg, v in ((tau_g[0], 1.2), (tau_g[1], 2.3))]
    lo = t_x + t_pd[0] + t_on[0]
    hi = t_x + t_pd[1] + t_on[1]
    print(f"   {i_step:4.1f} A step: SIG1 crosses TH1 in {t_x*1e6:5.1f} us; sense carries the pulse "
          f"{lo*1e6:4.0f}-{hi*1e6:4.0f} us (until S_GND reaches V_GS(th)); S0-10 tests 17 A for >= 0.5 ms")
print("   With R_chain = R_s + 1.6 + 10.3-17.2 mOhm, the S_GND body diodes clamp the sense drop near 0.7-1.0 V;")
print("   the pulse is inside S0-10 if R_s >= ~25 mOhm. No contradiction found.")

# ---------------------------------------------------------------------------
hdr(6, "VOK release race on a VESC-draw fall: bus feed duration")
C_VMOT = 0.48e-3                              # facts_prior 6 (board only, worst for slew)
TAU_TAP = 12.5e-6                             # DD Table 7 (C_Mk 1 nF, about 12.5 us)
for i_vesc in (5.0, 20.0):
    slew = i_vesc / C_VMOT                    # V/s at V-MOT
    t_cross = 0.112 / slew                    # release margin 0.112 V (DD 7.2)
    feed = TAU_TAP + 4e-6 + 1e-6 + 1.5e-6 - t_cross   # filter lag on a ramp + t_PD + pull-up + tSD
    print(f"   VESC {i_vesc:4.1f} A: V-MOT {slew/1e3:5.1f} V/ms, crosses margin in {t_cross*1e6:4.1f} us; "
          f"feed >= {max(feed,0)*1e6:4.1f} us (filter lag on a ramp = tau {TAU_TAP*1e6:.1f} us); "
          f"charge at 1.37 A <= {max(feed,0)*1.37e6:4.1f} uC")
print("   DD 7.2 item 2: 'at most about 12 us (about 15 uC)'. The ramp lag of the 12.5 us tap filter alone exceeds")
print("   12 us at the 20 A fall; the bound is about 16 us (22 uC) before the open-drain delay. Magnitude negligible.")

# ---------------------------------------------------------------------------
hdr(7, "LM1084 input at the 7.4 V floor and 17.1 A (DD 7.6), with the pack internal resistance counted")
for rint in (0.0, 0.010, 0.020, 0.040):      # calc5 R_int ASSUMED 10-40 mOhm
    v = 7.4 - 17.1 * (0.0129 + 0.020 + rint)  # 12.9 mOhm budget + J-BT pin-1 contact 20 mOhm (pin-2 via lead B)
    print(f"   R_int {rint*1e3:4.0f} mOhm: VBT - GND {v:.2f} V {'< 6.5 V' if v < 6.5 else ''}")
print("   DD 7.6 counts no R_int; '7.4 V floor' is the light-load V_batt. Consequence: transient 5V sag of")
print("   at most ~0.35 V; Teensy VIN and the pump margin survive (informational, not a finding).")
