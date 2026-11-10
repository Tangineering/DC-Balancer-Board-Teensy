"""Battle-test round 2, transient / numerical lens, against detailed_design_IC1.md Revision 4.

Time-domain models of the IC1 changeover and regen-window transitions. Standard library only.
Every input is cited; ASSUMED marks a working value with no primary.

Sources (abbreviations):
  DD    = detailed_design_IC1.md Rev 4 (section / table / equation numbers)
  FP    = facts_prior.md (section 6: regen pulse data; section 7: FC)
  RER   = docs/regen_enable_redesign.md (sections 3, 4, 6)
  T7    = references/Datasheets/Ag105_Table7_I2C_Parameters.json
  FB    = facts_board.md
  CALC4 = calc/ic1_rev4_calcs_output.txt

Run:  .venv_hil/Scripts/python.exe calc/bt2_transient_sim.py
"""
import math

def hdr(s):
    print("\n" + "=" * 78 + "\n" + s + "\n" + "=" * 78)

# ---------------------------------------------------------------------------------------------
# Common regen-pulse data (FP section 6)
V_PRE = 15.9            # V-MOT before the pulse (FP 6: "15.9 ->")
V_STOP = 21.35          # VESC over-voltage stop, mean measured peak (FP 6)
ONSET = 0.005           # pulse onset within about 5 ms of I_cmd < 0 (FP 6)
RISES = (0.019, 0.047)  # 15.9 -> 21.2-21.47 V in 19-47 ms (FP 6)
DECAYS = (14.0, 20.0)   # V/s linear decay with no regen current (FP 6)
FAULT_STOP = 0.500      # MCCONF_M_FAULT_STOP_TIME (FP 6); second pulse 0.523-0.562 s later
# VOK thresholds at VBUS 16.0 V (DD Table 9; DD 7.2: centred hysteresis lowers release by up to 32 mV)
ASSERT = (16.90, 17.24)
RELEASE = (16.16 - 0.032, 16.43)
# ERR_VOK_STUCK (DD Table 16): MOT_PWR HIGH, command not negative >= 200 ms, CHk_OK permit for 2 ms
VOKSTUCK_HOLDOFF = 0.200
VOKSTUCK_PERSIST = 0.002


def vmot_single_brake(tb, rise, decay, dt=1e-4, tend=1.5):
    """V-MOT for a brake command negative on [0, tb]; returns list of (t, v).
    Rise: linear from V_PRE at ONSET with slope (V_STOP-V_PRE)/rise while the command is negative and
    V < V_STOP; VESC stop at V_STOP (fault stop 500 ms, then a new pulse if still braking);
    decay at 'decay' V/s down to V_PRE when not rising."""
    slope_up = (V_STOP - V_PRE) / rise
    out = []
    v = V_PRE
    t = 0.0
    fault_until = -1.0
    while t <= tend:
        braking = (t < tb)
        rising = braking and t >= ONSET and t >= fault_until
        if rising:
            v += slope_up * dt
            if v >= V_STOP:
                v = V_STOP
                fault_until = t + FAULT_STOP
        else:
            v = max(V_PRE, v - decay * dt)
        out.append((t, v))
        t += dt
    return out


def vokstuck_false_trip(tb, rise, decay, a, r):
    """True if a healthy VOK channel (assert a, release r) still reads permit for >= 2 ms
    at or after tb + 200 ms (ERR_VOK_STUCK window opens)."""
    tr = vmot_single_brake(tb, rise, decay, tend=tb + 1.2)
    permit = False
    run = 0.0
    for (t, v) in tr:
        if not permit and v > a:
            permit = True
        elif permit and v < r:
            permit = False
        if t >= tb + VOKSTUCK_HOLDOFF:
            run = run + 1e-4 if permit else 0.0
            if run >= VOKSTUCK_PERSIST:
                return True, t
    return False, None


hdr("Section 1: ERR_VOK_STUCK against the normal post-brake V-MOT tail (DD Table 16, FP 6)")
for rise in RISES:
    for decay in DECAYS:
        tail_hi = (V_STOP - RELEASE[0]) / decay
        tail_lo = (V_STOP - RELEASE[1]) / decay
        print(f"  rise {rise*1e3:.0f} ms, decay {decay:.0f} V/s: after the VESC stop, a channel stays 'permit' "
              f"for {tail_lo*1e3:.0f}-{tail_hi*1e3:.0f} ms (to release {RELEASE[1]:.2f}/{RELEASE[0]:.2f} V)")
print("  ERR_VOK_STUCK opens 200 ms after the command stops being negative -> false latch whenever the brake")
print("  command ends less than (tail - 200 ms) after a VESC stop.")
# sweep brake duration 0..1.2 s (single brake; a multi-pulse brake repeats every ~0.52-0.55 s)
for rise in RISES:
    for decay in DECAYS:
        for (a, r, lab) in ((ASSERT[0], RELEASE[0], "worst (assert 16.90, release 16.13)"),
                            (ASSERT[1], RELEASE[1], "best  (assert 17.24, release 16.43)")):
            trips = []
            n = 0
            tb = 0.0
            while tb <= 1.2:
                ok, _ = vokstuck_false_trip(tb, rise, decay, a, r)
                trips.append((round(tb, 3), ok))
                n += 1
                tb += 0.002
            frac = sum(1 for _, k in trips if k) / n
            # report the trip intervals
            ivs = []
            cur = None
            for tbv, k in trips:
                if k and cur is None:
                    cur = [tbv, tbv]
                elif k:
                    cur[1] = tbv
                elif cur is not None:
                    ivs.append(tuple(cur)); cur = None
            if cur is not None:
                ivs.append(tuple(cur))
            ivtxt = ", ".join(f"{x*1e3:.0f}-{y*1e3:.0f} ms" for x, y in ivs)
            print(f"  rise {rise*1e3:2.0f} ms decay {decay:2.0f} V/s {lab}: false latch for brake durations "
                  f"{ivtxt}; {frac*100:4.1f} % of durations 0-1.2 s")
# disagreement time of two healthy channels (basis of the proposed fix)
d_assert = ASSERT[1] - ASSERT[0]
d_release = RELEASE[1] - RELEASE[0]
up_min = (V_STOP - V_PRE) / RISES[1] * 1e-3   # V per ms, slowest rise
print(f"  healthy-pair disagreement: assert spread {d_assert:.2f} V / slowest rise {up_min:.3f} V/ms = "
      f"{d_assert/up_min:.1f} ms; release spread {d_release:.2f} V / slowest decay 14 V/s = "
      f"{d_release/14*1e3:.1f} ms")
print("  -> 'exactly one CHk_OK permits for >= 50 ms' cannot occur on a healthy pair; a stuck channel")
print("     at bus level gives a permanent one-channel permit.")

# ---------------------------------------------------------------------------------------------
hdr("Section 2: OR-V regen arm (40 ms) against pulse 1 (DD 9.5, Table 11, Table 8a; RER 6; FP 6)")
ARM = 0.040                     # [RER] REGEN_ARM_DWELL_MS (DD Table 11, OR-V), best case: P_est >= 3 W at t = 0
LOOP = (1.131e-3, 1.341e-3)     # median / p99 iteration (DD Table 11)
SETTLE_IT = (2, 3)              # settled reading: 2 iterations, 3 if the first read straddles (DD 9.6)
TDON = (0.008, 0.012)           # RT1987 t_D_ON typ, sensitivity (DD 7.8)
RG_RAMP = 12.0e3                # V/s D-BC-RG soft-start (FB / facts_prior 10.4)
UV_RISE = (12.38, 12.88)        # eFuse UVLO rising (CALC4 section 9)
EF_DLY = 1.24e-3                # eFuse UVLO/SHDN turn-on delay (DD 7.5)
EF_SLEW = (5.79e3, 4.17e3)      # V/s eFuse output slew (DD 7.5)
for rise in RISES:
    t_stop = ONSET + rise
    for tdon in TDON:
        best = ARM + 0 + SETTLE_IT[0] * LOOP[0] + tdon + UV_RISE[0] / RG_RAMP + EF_DLY + 18.0 / EF_SLEW[0]
        worst = ARM + LOOP[1] + SETTLE_IT[1] * LOOP[1] + tdon + UV_RISE[1] / RG_RAMP + EF_DLY + 18.0 / EF_SLEW[1]
        print(f"  pulse {rise*1e3:2.0f} ms (VESC stop at {t_stop*1e3:4.1f} ms): pin 30 HIGH at "
              f"{(ARM+SETTLE_IT[0]*LOOP[0])*1e3:.1f}-{(ARM+LOOP[1]+SETTLE_IT[1]*LOOP[1])*1e3:.1f} ms; "
              f"t_D_ON {tdon*1e3:.0f} ms -> module input at 18 V at {best*1e3:.1f}-{worst*1e3:.1f} ms "
              f"= {(best-t_stop)*1e3:+.1f}..{(worst-t_stop)*1e3:+.1f} ms after the VESC stop (cold start 0)")
print("  Pulse 1 is never captured: the chain starts after the VESC has stopped, for every cold-start time.")

# Tail capture after the stop (node energy only), with the charger at P_IN once running.
P_IN = 22.4          # W regen profile at 8.4 V (DD Table 8)
ETA = 0.88           # Ag105 DS p.20 (unverified at 2S)
V_THR = 18.0         # regen-profile MPPT threshold (DD 7.2 item 5)
E_DECEL = {"2->1 m/s (0.30 s)": 1.81, "3->1 m/s (0.58 s)": 5.55}   # J into the pack (FP 6)
DUR = {"2->1 m/s (0.30 s)": 0.30, "3->1 m/s (0.58 s)": 0.58}
for C in (0.97e-3, 4.0e-3):
    for rise in RISES:
        for decay in DECAYS:
            t_stop = ONSET + rise
            for tcs in (0.0, 0.065, 0.170):
                t_on = ARM + SETTLE_IT[0] * LOOP[0] + TDON[0] + UV_RISE[0] / RG_RAMP + EF_DLY + 18.0 / EF_SLEW[0] + tcs
                v = V_STOP - decay * max(0.0, t_on - t_stop)
                p_hk = C * V_STOP * decay          # housekeeping draw implied by the measured decay
                # integrate C v dv/dt = -(p_hk + P_IN) while v > release (charger on), energy to charger
                e_chg_rel = 0.0; e_chg_thr = 0.0
                dt = 1e-5
                vv = v
                while vv > RELEASE[1]:
                    dv = -(p_hk + P_IN) / (C * vv) * dt
                    e = P_IN * dt
                    e_chg_rel += e
                    if vv > V_THR:
                        e_chg_thr += e
                    vv += dv
                print(f"  C {C*1e3:4.2f} mF, pulse {rise*1e3:2.0f} ms, decay {decay:2.0f} V/s, cold start "
                      f"{tcs*1e3:3.0f} ms: V-MOT at charger start {v:5.2f} V; pack energy from the tail "
                      f"{ETA*e_chg_rel:5.3f} J (to VOK release) / {ETA*e_chg_thr:5.3f} J (above the 18 V threshold)")
for k in E_DECEL:
    t2 = ONSET + RISES[0] + FAULT_STOP + ONSET
    print(f"  {k}: decel energy into the pack {E_DECEL[k]} J; pulse 2 starts at or after "
          f"{(ONSET+RISES[0]+FAULT_STOP)*1e3:.0f} ms ({'none within the decel' if t2 > DUR[k] else 'at the decel end'})")

# ---------------------------------------------------------------------------------------------
hdr("Section 3: module alive after an eFuse cut (ERR_EFUSE_BYPASS; re-bond with the module converting)")
I_Q = 0.018          # Ag105 idle current, maximum (DD 14.4, Ag105 DS p.20 row 4)
V_UV = 11.0          # Ag105 input lockout (DD 5.3, DS p.19)
C_EO = 1e-6
print("  The Ag105 answers I2C below 9 V input (returns 0xFF, Ag105 DS p.14 as cited in DD 12.5 item 2).")
for Cin in (10e-6, 47e-6, 100e-6, 220e-6):
    C = Cin + C_EO
    for (vcut, p, lab) in ((16.43, 22.4, "regen, VOK release"), (21.35, 22.4, "regen, exit at peak"),
                           (16.0, 14.8, "FC window exit")):
        t_conv = C * (vcut ** 2 - V_UV ** 2) / (2 * p)
        e = 0.5 * C * (vcut ** 2 - V_UV ** 2)
        t_idle = [C * (V_UV - vl) / I_Q for vl in (5.0, 3.5)]
        print(f"  C_in {Cin*1e6:5.0f} uF, {lab:20s}: converts {t_conv*1e3:6.2f} ms ({e*1e3:5.1f} mJ) after the cut, "
              f"then I2C alive a further {t_idle[0]*1e3:5.1f}-{t_idle[1]*1e3:5.1f} ms (logic to 5.0/3.5 V, "
              f"UNCONFIRMED; at I_q 18 mA max)")
# re-bond timing after FF1 clear: S_GND gate 0 -> 0.85 VBT with tau 88-114 us (DD Table 11, eq. 14)
for vbt in (7.4, 8.4):
    vg = 0.85 * vbt
    for tau in (88e-6, 114e-6):
        t_on = [-tau * math.log(1 - vt / vg) for vt in (1.2, 2.3)]          # CSD18510Q5B Vth
        t_qd = [-tau * math.log(1 - vt / vg) for vt in (1.43, 2.46)]        # gate-referred Q_D (DD eq. 7)
        print(f"  VBT {vbt} V, tau {tau*1e6:.0f} us: S_GND conducts at {t_on[0]*1e6:.0f}-{t_on[1]*1e6:.0f} us, "
              f"S_CHG commanded off at {t_qd[0]*1e6:.0f}-{t_qd[1]*1e6:.0f} us after FF1 clears")
print("  In a regen window EF_EN = FF1.Q AND PUMP_OK AND (VOK OR FCQ) (DD eq. 5): pin 30 LOW does not drop it,")
print("  so the eFuse cut and the re-bond start on the same pin-33 edge.")

# ---------------------------------------------------------------------------------------------
hdr("Section 4: G1 residual form in an FC window (DD 12.7 item 1; T7 registers; CALC4 section 8)")
I_SET = 1.25; I_L = 0.30; I_AUX = 0.15     # DD Table 8 FC profile, I_L working value; aux
INA_FLOOR = 0.10                           # INA253A1 zero-current floor up to 0.1 A per channel (FP 10 item 11)
print("  T7: reg 0x05 = measured BATTERY voltage, reg 0x06 = measured charge current, reg 0x07 = measured INPUT voltage.")
print("  DD 12.7: P_chg,est 'from valid reg 0x07 and reg 0x06 reads'; residual = I_fc + I_batt - "
      "(P_chg,est/(0.88 V_bus) + I_AUX) > 0.30 A for 5 ms")
for vb in (7.4, 8.4):
    for eta in (0.88, 0.80):
        for vbus in (16.0, 15.1):
            i_true = (I_SET + I_L) * vb / (eta * vbus)       # bus current of the charger (CALC4 sec 8 form)
            est_a = vb * I_SET / (0.88 * vbus)               # reading A: V_batt (0x05) x I_p
            est_b = vbus * I_SET / (0.88 * vbus)             # reading B: V_in (0x07) x I_p, as written
            ra = i_true - est_a
            rb = i_true - est_b
            print(f"  V_batt {vb} V, eta {eta:.2f}, V_bus {vbus:4.1f} V: charger bus current {i_true:5.3f} A; "
                  f"residual (0x05 x 0x06) {ra:+.3f} A [+{ra+2*INA_FLOOR:.3f} A with both INA253 floors]; "
                  f"residual (0x07 x 0x06, as written) {rb:+.3f} A")
print("  Reading A trips G1 in steady state (threshold 0.30 A) once the INA253 floors add; reading B")
print("  is negative by about 0.5 A, so G1 cannot see an unaccounted bus flow below about 0.8 A.")
# start-up lag: estimate from 50 Hz polls, residual > 0.30 A for 5 ms
POLL = 0.020
for tr in (0.010, 0.030, 0.060, 0.100):
    full = (I_SET + I_L) * 8.0 / (0.88 * 16.0)
    slope = full / tr
    err = min(full, slope * POLL)        # worst estimate lag of one poll period during the ramp
    print(f"  charger current ramp 0 -> full in {tr*1e3:4.0f} ms: estimate lag error up to {err:.2f} A "
          f"({'> 0.30 A' if err > 0.30 else '<= 0.30 A'} for one poll; blanking ends 5 ms after the dVdT ramp, "
          f"long before a 65-170 ms cold start)")
