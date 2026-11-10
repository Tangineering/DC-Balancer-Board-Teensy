"""Battle-test round 4, LOGIC / SEQUENCING lens: model check of the IC1 revision-6 delta.

Target: detailed_design_IC1.md revision 6 (sections 5.2, 5.3, 6, 8, 9.3, 9.5, 9.7, 9.7a, 9.9, 9.10, 10, 12.4-12.6).
Reuses the revision-5 network model of calc/bt3_logic_seq_enum.py and adds the revision-6 elements:
  Q_MD = LB3V3 AND NOT EF_EN (U_MDI, R_MDG pull-down)            design eq. 5, Figure 2, Table 13
  MOD_COLD_N (pin 8, INPUT_PULLUP, R_UMS 10k to LB 3V3) = L iff node < 8.69-9.15 V   design 5.3 item 3, Table 15
  pin 5 open-drain: {L, Z} (H only as a mis-configuration)         design 12.5 item 3
  cold-module rule (pin 8 LOW >= 20 ms), exit drain wait (two LOW reads, cap 10 ms), chokepoints, CC-2/CC-5 pin-5/pin-10
  waits, ERR_VOK_STUCK ratio rule with k_idle, ERR_MOD_SENSE positive control keyed on the second settled V_chg >= 13.5 V.
Stdlib only.  Run:  python bt4_logic_seq_enum.py > bt4_logic_seq_enum_output.txt

Numeric inputs (all cited):
  V-MOT pulse 15.9 -> 21.20-21.47 V in 19-47 ms; decay 14-20 V/s with no regen current; second pulse 0.523-0.562 s
    after the first; 0.3-0.6 s above bus per burst                                      facts_prior section 6
  VOK assert 16.90-17.24 V, release 16.16-16.43 V at VBUS 16.0 (centred hysteresis: up to 32 mV lower)   design 6 item 4
  VCHG-IN bleed tau 0.984 s (20 uF + C_EI)                                               design Table 11, 9.9 step 3
  eFuse UVLO rising 12.38-12.88 V, falling 11.47-12.10 V; SHDN/UVLO turn-on ~1.24 ms; output slew <= 5.79 V/ms
                                                                                        design 5.3, 7.5, Table 11
  D-BC-RG t_D_ON 8 ms typical, no maximum; VCHG-IN ramp 12 V/ms                          design Table 11 (RT1987 DS-00 13)
  U_MS threshold 8.69-9.15 V; C_mod 100-221 uF; R_MD 15 Ohm                              design 5.3, calc6 sections 3-4
  loop: median 1.131 ms, p99 1.341 ms, worst measured gap 9.76 ms (ML0226)              facts_firmware section 8
  ERR_MOD_SENSE (b): 10 ms after the second settled V_chg >= 13.5 V, EF_EN H throughout  design Table 16, 9.5
  ERR_MOD_DRAIN: pin 8 not LOW (two successive reads) within 10 ms of the feed drop     design 9.5 exit step 2, Table 16
  deferral: the first iteration of an exit drain defers SD drain + Ag105 I2C to the NEXT iteration   design 12.4 item 5
  k_idle: 1 s mean of V_rgn/V_bus in bonded Idle, MOT_PWR H, |I_mot| < 0.5 A, refreshed at every Idle entry;
    ERR_VMOT_CAL outside +/-3 % of the C-2 value                                        design Table 16
  Idle-entry self-test step 1 expects CH1_OK L and CH2_OK L                             design 9.3 step 1
  State 2 -> 3 on changeToFin, State 3 -> 1 in the same doState3() call                ino:7954-7957, ino:8017-8018
"""
import itertools
import math
import random

def hdr(t):
    print("\n" + "=" * 110 + "\n" + t + "\n" + "=" * 110)

LV = ("L", "H", "Z")

# =============================================================================================================
# Section 1: exhaustive steady-state enumeration of the revision-6 network, GPIO in {L,H,Z}, pin 5 in {L,Z,(H)}
# =============================================================================================================
FAULTS = [None, "EFUSE_FET_SHORT", "U_AND_STUCK_H", "FF1Q_SB_STUCK_L", "Q_X2_OPEN", "Q_X1_OPEN", "DBCFC_SHORT",
          "DBCRG_SHORT", "LB3V3_TAP_OPEN",
          # revision-6 elements
          "Q_MD_DS_SHORT", "U_MDI_STUCK_H", "U_MDI_STUCK_L", "MD_G_OPEN", "U_MS_OUT_STUCK_L", "R_MS1_OPEN",
          "R_MS2_OPEN", "PIN8_TAP_OPEN", "P5_PUSHPULL"]

def hw(g, env, fault, stage):
    teensy = env["teensy"]
    p = {k: (v == "H") for k, v in g.items() if k not in ("p34", "p20", "p5")}
    if not teensy:
        p = {k: False for k in p}
    lb = teensy and fault != "LB3V3_TAP_OPEN"
    pump_ok = lb and env["v5"] and g["p34"] == "T"
    p33b = lb and p["p33"]
    fcq = p["p31"]
    n1_low = (not p33b) or (not pump_ok) or env["uc1"] or env["clr"]
    ff1 = lb and (not n1_low) and env["ff1_prev"]           # FF1 set state carried in from an earlier edge
    ff1q_sb = ff1 and fault != "FF1Q_SB_STUCK_L"
    if stage == 2:
        okk = env["vmot_above"] if lb else True               # dead rail: open-drain outputs read OK / present
        bpk = env["bus"] if lb else True
        vok = okk and bpk and lb
    else:
        okk = bpk = vok = False
    src = (vok and p["p30"]) or fcq
    ef_en = (lb and ff1 and pump_ok and src) or (fault == "U_AND_STUCK_H" and lb)
    sgnd = (not ff1q_sb) or env["uc1"]
    x = lb and ((not ff1) or sgnd)
    btsq = p["p32"] and (not x or fault == "Q_X2_OPEN")
    bten = p["p28"] and (not fcq or fault == "Q_X1_OPEN")
    rg = ((p["p30"] and okk and bpk) if stage == 2 else p["p30"]) or fault == "DBCRG_SHORT"
    fc = (p["p31"] or fault == "DBCFC_SHORT") and env["bus"]
    mt = p["p29"] and env["bus"]
    rg_fed = rg and (env["vmot_above"] or mt)
    rg_busfed = rg and mt and not env["vmot_above"]
    fed = fc or rg_fed or env["resid"]
    efuse_on = (ef_en or fault == "EFUSE_FET_SHORT") and fed
    # revision-6 module node
    mdi_out = (lb and not ef_en)
    if fault == "U_MDI_STUCK_H":
        mdi_out = lb
    if fault == "U_MDI_STUCK_L":
        mdi_out = False
    qmd = (mdi_out and fault != "MD_G_OPEN") or fault == "Q_MD_DS_SHORT"
    node_hot = efuse_on or (env["node_resid"] and not qmd)   # residual drains in <= 2.9 ms with Q_MD, 0.42 s without
    # U_MS / pin 8 read (INPUT_PULLUP ~22k plus R_UMS 10k to LB 3V3)
    if not teensy:
        pin8 = None
    elif fault == "PIN8_TAP_OPEN":
        pin8 = "H"
    elif not lb:
        pin8 = "L"            # R_UMS 10k to a dead 3V3 rail against the ~22k internal pull-up: about 1.0 V < VIH
    elif fault in ("U_MS_OUT_STUCK_L", "R_MS1_OPEN"):
        pin8 = "L"
    elif fault == "R_MS2_OPEN":
        pin8 = "H" if (node_hot or env["node_resid"]) else "L"   # reads HIGH above ~1.3 V
    else:
        pin8 = "H" if node_hot else "L"
    # pin 5: open-drain, Z = released; a push-pull H would source into an unpowered module (BT3-AG-4)
    p5_sources = (g["p5"] == "H" and fault == "P5_PUSHPULL" and teensy)
    a = efuse_on and sgnd
    a2 = a and btsq
    b = efuse_on and (fc or rg_busfed) and btsq and bten
    false_cold = node_hot and pin8 == "L"
    dump_fights_feed = qmd and efuse_on
    return dict(ff1=ff1, a=a, a2=a2, b=b, sgnd=sgnd, btsq=btsq, efuse=efuse_on, ef_en=ef_en, qmd=qmd,
                pin8=pin8, node_hot=node_hot, false_cold=false_cold, fight=dump_fights_feed, p5src=p5_sources)

def section1():
    hdr("Section 1: exhaustive steady state, revision-6 network (Stage 1 and 2), fault-free and single faults")
    pins = ["p33", "p28", "p29", "p30", "p31", "p32"]
    envkeys = ["teensy", "v5", "bus", "vmot_above", "uc1", "clr", "resid", "node_resid", "ff1_prev"]
    print("  fault                stage  (a)fw (a')fw (b)fw  defaults(c)  false-cold  Q_MD-vs-feed  p5-sources  example")
    for stage in (1, 2):
        for fault in FAULTS:
            c = dict(a=0, a2=0, b=0, cbad=0, fc=0, fight=0, p5=0)
            ex = None
            # Z is modelled identically to L for these pins: each has a board pull-down (R_P33 10k at the U_P33 input,
            # RT1987 EN 10k bodges, R_FQP/R_RQP 100k); __main__ checks that 'Z' and 'L' give the same hw() result.
            for gv in itertools.product(("L", "H"), repeat=len(pins)):
                g = dict(zip(pins, gv))
                Hs = {k for k in pins if g[k] == "H"}
                legal = True
                if "p30" in Hs and ("p33" not in Hs or stage == 1 or "p31" in Hs):
                    legal = False
                if "p31" in Hs and "p33" not in Hs and "p32" in Hs:
                    legal = False
                for p5 in (("L", "Z", "H") if fault == "P5_PUSHPULL" else ("L", "Z")):
                    g["p5"] = p5
                    for p34 in ("T", "S"):
                        g["p34"] = p34
                        g["p20"] = "Z"
                        for ev in itertools.product((False, True), repeat=len(envkeys)):
                            env = dict(zip(envkeys, ev))
                            s = hw(g, env, fault, stage)
                            if legal and s["a"]:
                                c["a"] += 1
                                ex = ex or ("a", dict(g), sorted(k for k, v in env.items() if v))
                            if legal and s["a2"]:
                                c["a2"] += 1
                            if legal and s["b"]:
                                c["b"] += 1
                                ex = ex or ("b", dict(g), sorted(k for k, v in env.items() if v))
                            if not env["teensy"] and (not s["sgnd"] or s["efuse"] and not env["resid"]):
                                c["cbad"] += 1
                            if s["false_cold"] and env["teensy"]:
                                c["fc"] += 1
                            if s["fight"]:
                                c["fight"] += 1
                            if s["p5src"]:
                                c["p5"] += 1
            exs = "-" if ex is None else "%s %s env=%s" % (ex[0], ",".join("%s=%s" % kv for kv in ex[1].items()),
                                                         ",".join(ex[2]))
            print("  %-20s %5d %6d %6d %6d %11d %11d %13d %11d   %s" % (fault, stage, c["a"], c["a2"], c["b"], c["cbad"],
                  c["fc"], c["fight"], c["p5"], exs[:110]))
    print("""
  Reading. Fault-free and under every new single fault the firmware-legal (a), (a') and (b) counts stay 0 and the
  defaults (c) hold: Q_MD, U_MS, pin 8 and open-drain pin 5 sit outside the EF_EN and S_GND equations (eq. 5-7), so
  the revision-6 delta cannot create (a) or (b) by itself. (a)/(b) still appear only under EFUSE_FET_SHORT or
  U_AND_STUCK_H plus a feed (rows F11, F35, F36), unchanged from round 3.
  New in revision 6: 'false-cold' counts states in which pin 8 reads LOW (cold) while the module node is fed or holds
  a residual above the threshold. Fault-free it is 0 except through LB3V3_TAP_OPEN, where R_UMS (10 kOhm to the dead
  rail) defeats the INPUT_PULLUP: section 5.3 item 3 and Table 13 assume an unpowered U_MS reads HIGH or LOW only by
  its output stage. Single faults U_MS_OUT_STUCK_L / R_MS1_OPEN give false-cold reads until the next window's
  positive control. 'Q_MD-vs-feed' is the 17 W R_MD case; fault-free it needs a residual-free fed node with EF_EN L,
  which only an eFuse bypass gives (row F11 + probe), plus the Q_MD/U_MDI short rows F50.""")


# =============================================================================================================
# Section 2: Idle entry while V-MOT is still in a regen tail (self-test step 1 CH bits, k_idle)
# =============================================================================================================
def vmot_tail(t, peak, decay, vbus):
    """V-MOT after the pulse peak at t = 0: linear decay (facts_prior s6), floored at VBUS by D-MT-EN (MOT_PWR H)."""
    return max(vbus, peak - decay * t)

def section2():
    hdr("Section 2: Run -> Finish -> Idle (or State-98 'Q') inside a regen tail: self-test step 1 and k_idle")
    vbus = 16.0
    print("  Idle entry happens in the same doState3() call that leaves State 2 (ino:7954-7957, 8017-8018); the")
    print("  Idle-entry self-test step 1 runs on the next chgModeTick() and expects CH1_OK L and CH2_OK L (design 9.3).")
    print("  A comparator that asserted on the pulse permits until V-MOT falls below its release level.\n")
    print("  peak V   decay V/s  release V   CH permits for (s after peak)   step-1 FAIL if Idle entry within")
    worst = 0.0
    for peak in (21.20, 21.47):
        for decay in (14.0, 20.0):
            for rel in (16.13, 16.43):
                t_rel = (peak - rel) / decay
                worst = max(worst, t_rel)
                print("  %6.2f   %8.1f  %9.2f   %27.3f   %.3f s of the last pulse peak" % (peak, decay, rel, t_rel, t_rel))
    print("\n  -> ERR_CHG_SELFTEST (reboot-only, refuses EVERY window, FC windows included) when the Finish command or 'Q'")
    print("     arrives up to %.3f s after a regen pulse peak. Bursts stay above bus for 0.3-0.6 s (facts_prior s6)." % worst)
    # k_idle: 1 s mean of V_rgn/V_bus from Idle entry
    print("\n  k_idle = 1 s mean of V-MOT/VBUS from Idle entry (MOT_PWR H, motor command 0): inflation vs the true 1.000")
    print("  entry after peak   peak 21.47 V, 14 V/s   peak 21.20 V, 20 V/s   ERR_VMOT_CAL (+/-3 %)")
    for t0 in (0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30):
        res = []
        for peak, decay in ((21.47, 14.0), (21.20, 20.0)):
            n = 1000
            k = sum(vmot_tail(t0 + i / 1000.0, peak, decay, vbus) / vbus for i in range(n)) / n
            res.append(k)
        print("  %13.2f s   %18.4f   %18.4f   %s" % (t0, res[0], res[1],
              "LATCH (regen refused)" if max(res) > 1.03 else ("biased, passes" if max(res) > 1.003 else "ok")))
    # does a biased k_idle defeat a healthy channel later (ERR_VOK_STUCK)? needs 50 ms of permit with r < 1.003
    print("\n  Biased k_idle (passes the 3 % band) against ERR_VOK_STUCK: a healthy channel permits from assert down to its")
    print("  release; r = ratio / k_idle reads below 1.003 while ratio < 1.003 k. Time in that band at 14-20 V/s:")
    for k in (1.01, 1.02, 1.03):
        for decay in (14.0, 20.0):
            band_v = max(0.0, (1.003 * k - 16.13 / vbus) * vbus)
            print("    k_idle %.2f decay %4.1f V/s: %5.1f ms (latch needs 50 ms)" % (k, decay, 1000 * band_v / decay))
    print("""
  Reading. Two Idle-entry checks assume V-MOT at bus level, and the Finish path enters Idle within one loop of the
  Pi command, braking or not. (1) Step 1 reads CH1_OK/CH2_OK H for up to 0.38 s after a pulse peak and fails, which
  sets the reboot-only ERR_CHG_SELFTEST. The same holds for 'Q' during a D/Y/W regen hold. The rev-6 host test
  (12.11) enters Idle from State 2 with the pump toggling but with V-MOT at bus level, so it does not cover this.
  (2) k_idle, refreshed at every Idle entry, averages the tail into a 1 s mean: an entry within about 0.1 s of a
  peak inflates it by more than 3 % and latches ERR_VMOT_CAL (regen windows refused); a smaller inflation passes and
  only biases r (no ERR_VOK_STUCK: the band stays below 50 ms). Stage 2 only: in Stage 1 the CH bits are tied LOW
  and k_idle is not used. The tail exists in every Stage-2 Run with a brake command, window or not.""")


# =============================================================================================================
# Section 3: second and later pulses of a regen window - residual VCHG-IN stales the ERR_MOD_SENSE anchor
# =============================================================================================================
TAU_VCHG = 0.984
UVLO_R = (12.38, 12.88)
UVLO_F = (11.47, 12.10)
T_EF_ON = 1.24e-3
SLEW = 5.79e3            # V/s
RAMP_VCHG = 12.0e3       # V/s
T_LOOP = 1.131e-3

def pulse_pair(peak, rise, decay, spacing, assert_v, rel_v, vbus=16.0, v0=15.9):
    """Returns (t_assert_next - t_release, VCHG-IN residual at the next assert). V-MOT linear rise, linear decay."""
    t_assert = rise * (assert_v - v0) / (peak - v0)
    t_rel = rise + (peak - rel_v) / decay
    off = spacing - t_rel + t_assert
    return off, rel_v * math.exp(-off / TAU_VCHG)

def section3():
    hdr("Section 3: regen window, pulse n >= 2: VCHG-IN residual at the VOK assert and the ERR_MOD_SENSE (b) deadline")
    print("  VCHG-IN tracks V-MOT through D-BC-RG until the VOK release, then holds on 20 uF with tau 0.984 s; the window")
    print("  entry rule 'V_chg below 11 V' applies to the first pulse only. No Ag105 draw (present evidence: the cold")
    print("  start of 65-170 ms is not reached before the 18 V threshold is lost, design 7.8: 'no pulse is captured').\n")
    print("  decay  spacing  off-span  residual   >=13.5 V (stale anchor)")
    stale_cases = []
    for decay in (14.0, 15.0, 16.0, 17.0, 20.0):
        for spacing in (0.523, 0.535, 0.562):
            off, r = pulse_pair(21.47, 0.019, decay, spacing, 16.90, 16.43)
            if r >= 13.5:
                stale_cases.append((decay, spacing, r))
            print("  %5.1f  %7.3f  %8.3f  %8.2f   %s" % (decay, spacing, off, r, "YES" if r >= 13.5 else "no"))
    # Monte Carlo of the deadline with loop phase, t_D_ON, two anchor readings of the spec text
    print("\n  Deadline check (10 ms from the anchor; EF_EN stays H for the whole VOK span of 0.24-0.38 s):")
    print("    I1: anchor = first iteration with EF_EN H whose V_chg read and the previous read are both >= 13.5 V")
    print("    I2: anchor = second consecutive V_chg >= 13.5 V read taken with EF_EN H")
    rnd = random.Random(4)
    print("    t_D_ON ms   residual V   P(false ERR_MOD_SENSE) I1   I2")
    for tdon in (0.008, 0.009, 0.010, 0.012):
        for resid in (13.6, 14.1):
            f1 = f2 = 0
            N = 4000
            for _ in range(N):
                t1 = rnd.uniform(0, T_LOOP)                  # first read after the assert
                reads = [t1 + i * T_LOOP for i in range(40)]
                uvlo_r = rnd.uniform(*UVLO_R)
                uvlo_f = rnd.uniform(*UVLO_F)
                # residual >= UVLO_R: the eFuse turns on at T_EF_ON, drains 21 uF into C_mod, IN falls to UVLO_F
                def vchg(t):
                    if t < T_EF_ON:
                        return resid
                    if t < tdon:
                        return uvlo_f
                    return min(V_MOT_NOW, uvlo_f + RAMP_VCHG * (t - tdon))
                # pin 8 HIGH when the node passes ~9 V: eFuse re-start at the UVLO_R crossing + turn-on + slew
                t_uv = tdon + (uvlo_r - uvlo_f) / RAMP_VCHG
                t_p8 = t_uv + T_EF_ON + rnd.uniform(8.69, 9.15) / SLEW
                first_p8_read = next(t for t in reads if t >= t_p8)
                # I1
                a1 = None
                prev = vchg(-0.001)
                for t in reads:
                    v = vchg(t)
                    if v >= 13.5 and prev >= 13.5:
                        a1 = t
                        break
                    prev = v
                a2 = None
                cnt = 0
                for t in reads:
                    cnt = cnt + 1 if vchg(t) >= 13.5 else 0
                    if cnt == 2:
                        a2 = t
                        break
                if a1 is not None and first_p8_read > a1 + 0.010:
                    f1 += 1
                if a2 is not None and first_p8_read > a2 + 0.010:
                    f2 += 1
            print("    %9.0f   %10.1f   %24.2f %6.2f" % (tdon * 1e3, resid, f1 / N, f2 / N))
    print("""
  Reading. CC-1 re-keyed the positive control from the EF_EN rise to 'the second settled V_chg reading at or above
  13.5 V' on the assumption that V_chg is below 13.5 V until D-BC-RG feeds VCHG-IN. Inside a window that holds only for
  the first pulse. When the VESC re-pulses 0.523-0.562 s later and V-MOT decayed at about 16 V/s or slower, VCHG-IN
  still holds 13.5-14.2 V at the next VOK assert, so the anchor is taken at the EF_EN rise, t_D_ON before the feed.
  The residual itself does not reach pin 8: the eFuse drains 21 uF into C_mod (about 0.2-0.5 V) and stops at UVLO.
  Under reading I1 every such pulse latches at t_D_ON 8 ms or more: pin 8 rises about t_D_ON + 2.9 ms after the
  assert, and on the 1.131 ms iteration grid the first HIGH read lands at anchor + 10.18 ms or later (the deadline
  is met only for t_D_ON below about 7.1 ms); one hit refuses every window for the power cycle. Under the stricter reading I2 the stale
  anchor needs two reads inside the 1.24 ms eFuse turn-on delay (about 10 % of pulses), which over 56 pulses per
  30 s window is still near-certain. No host test (12.11) drives a second pulse with a residual V_chg.""")

V_MOT_NOW = 21.0


# =============================================================================================================
# Section 4: commanded-exit drain wait against the deferred iteration (ERR_MOD_DRAIN) and the 10 ms deadlines
# =============================================================================================================
def drain_time(v0, cmod, vth=9.15, r=15.0):
    return r * cmod * math.log(v0 / vth)

def section4():
    hdr("Section 4: exit drain wait (two pin-8 LOW reads within 10 ms) with the deferred SD/I2C iteration")
    print("  Iteration 0 writes the feed drop (pin 30 or FC_CHARGE LOW) and, per 12.4 item 5, defers logDrainTick() and")
    print("  the Ag105 I2C poll to iteration 1. Pin 8 is read at the start of each iteration (chgModeTick after")
    print("  detectFaults). L = duration of iteration 1. ERR_MOD_DRAIN if the second LOW read is later than 10 ms.\n")
    print("  start V  C_mod uF  drain ms   L=1.13   L=2.40   L=5.00   L=7.50   L=9.76  (time of 2nd LOW read, ms)")
    for v0 in (16.0, 16.4, 21.5):
        for cmod in (100e-6, 145e-6, 221e-6):
            td = drain_time(v0, cmod)
            row = []
            for L in (1.131e-3, 2.4e-3, 5.0e-3, 7.5e-3, 9.76e-3):
                reads = [T_LOOP, T_LOOP + L] + [T_LOOP + L + k * T_LOOP for k in range(1, 20)]
                lows = [t for t in reads if t >= td]
                t2 = lows[1]
                row.append("%5.2f%s" % (t2 * 1e3, "*" if t2 > 0.010 else " "))
            print("  %6.1f  %8.0f  %8.2f   %s" % (v0, cmod * 1e6, td * 1e3, "   ".join(row)))
    print("  (* = false ERR_MOD_DRAIN on a healthy board; windows refused for the power cycle)")
    # break-even L
    print("\n  Largest iteration-1 length that still passes: 10 ms - T (read 1 at T, read 2 at T + L when the drain is")
    print("  shorter than T) = %.2f ms; when the drain exceeds T, 10 ms - 2T = %.2f ms." % ((0.010 - T_LOOP) * 1e3,
                                                                                         (0.010 - 2 * T_LOOP) * 1e3))
    print("""
  Reading. The 10 ms T_drain,max is wall-clock while the confirmation needs two reads; revision 6 (R6-11) moved every
  other confirmation to 'iterations or 30 ms' because of the 9.76 ms measured gap, but kept 10 ms here, and the FM3-3
  deferral moves the SD drain and the I2C poll into exactly the first drain-wait iteration. Any iteration-1 length
  above 7.7-8.9 ms latches ERR_MOD_DRAIN with the module already cold. The host test of 12.11 injects a 10 ms
  iteration after the exit write and checks only ERR_CHG_EXIT/ENTRY/LADDER, not ERR_MOD_DRAIN. The same arithmetic
  bounds ERR_MOD_SENSE (b): worst lag 3.38 ms plus a 9.76 ms gap exceeds the 10 ms regen deadline.""")


# =============================================================================================================
# Section 5: exit ordering (d) traces, including the R6-12 pin-32 LOW on ERR_CHG_LADDER and in State 99
# =============================================================================================================
def section5():
    hdr("Section 5: invariant (d) and the D-BT-SQ opening order on every exit path")
    paths = [
        ("regen exit (9.5)", ["p30 L", "wait p8 LOW x2", "p33 L", "confirm", "p5 L after 20 ms cold"], True),
        ("FC exit (9.7)", ["FC_CHARGE L", "wait p8 LOW x2", "p33 L", "confirm", "BT_BUS", "p10/p5 L"], True),
        ("probe (9.7a)", ["(p33 L already)", "FC_CHARGE H <=100 ms", "FC_CHARGE L"], True),
        ("State 99 (9.9)", ["FC_CHARGE L, REGEN L", "wait p8 LOW (cap 10 ms)", "p33 L", "p32 L"], True),
        ("ERR_CHG_LADDER, LB alive (12.4 item 4)", ["ends window", "sets p32 L", "(order vs drain unstated)"], None),
        ("hardware trip (9.10)", ["FF1 clear", "eFuse off <=76 us", "bond 0.3 ms", "module runs <=1.1 ms (F10)"], False),
    ]
    for name, seq, ok in paths:
        print("  %-40s %s  -> %s" % (name, " -> ".join(seq),
              {True: "feed removed and node cold before the bond", False: "F10 by design (bounded)",
               None: "see trace below"}[ok]))
    print("""
  Trace (LB alive, FC window at 1.25 A, a settled ladder mismatch on 3 iterations, e.g. one SG bit wrong):
    it k   : ERR_CHG_LADDER -> 'ends any window, sets pin 32 LOW' (Table 16 row, 9.10 F51 row);
    it k   : pin 32 LOW: D-BT-SQ EN falls while FC_CHARGE is still HIGH and FF1 set (FCQ, EF_EN H): the Ag105
             output is opened under 1.25 A - the case that 12.4 item 7 (CC-7) calls unreachable ('a pin-32 LOW
             write inside a window would open the battery path during charge (gate S0-3) ... neither is reachable
             from a key') and that S0-3 must bound;
    it k+1 : FC_CHARGE L, drain wait, pin 33 L (the exit itself is (d)-correct).
  The pin-32 LOW of R6-12 is needed only when the ladders read code 0 (dead LB rail, cross-lock lost, F51); with the
  rail alive the cross-lock X disables D-BT-SQ at the bond anyway. (d) itself holds on every commanded path.""")


# =============================================================================================================
# Section 6: defaults (c) with the revision-6 elements
# =============================================================================================================
def section6():
    hdr("Section 6: defaults (c) for unpowered, reset and hang, revision-6 elements")
    rows = [
        ("Teensy unpowered (LB 3V3 absent)", dict(teensy=False, lb=False)),
        ("Teensy reset, LB 3V3 up (pins Z)", dict(teensy=True, lb=True, reset=True)),
        ("Loop hang in a regen window (pins static, pump static)", dict(teensy=True, lb=True, hang=True)),
        ("LB 3V3 tap open, Teensy alive (F51)", dict(teensy=True, lb=False)),
    ]
    for name, r in rows:
        if not r["teensy"]:
            q, p8, ff = "OFF (R_MDG)", "n/a", "clear (no rail)"
        elif not r["lb"]:
            q, p8, ff = "OFF (U_MDI unpowered)", "LOW (R_UMS to dead rail vs ~22k pull-up)", "clear; bonded on R_PA"
        elif r.get("reset"):
            q, p8, ff = "ON (EF_EN L)", "LOW once dumped", "clear at once (U_P33)"
        else:
            q, p8, ff = "OFF until PUMP_OK falls, then ON", "HIGH in a pulse, LOW after dump", "clear after 43-76 ms"
        print("  %-55s Q_MD %-30s pin 8 %-42s FF1 %s" % (name, q, p8, ff))
    print("""
  Reading. (c) holds: the eFuse is off (R_SDP or FF1 clear) and the pack bonded in every row. With Q_MD off (no
  rail) the residual module node decays on R_MB (16 V to 9 V in at most 0.42 s): the module can convert from C_mod
  (at most 51 mJ) with the pack bonded, the F10 class. In the F51 row pin 8 reads LOW whatever the node does, which
  contradicts Table 13 ('HIGH (reads fed) with U_MS released or unpowered without a clamp'); the ladder code-0 rule
  still ends the window, so this is a documentation error, not a new path.""")


def check_z_equals_l():
    pins = ["p33", "p28", "p29", "p30", "p31", "p32"]
    bad = 0
    for ev in itertools.product((False, True), repeat=4):
        env = dict(teensy=True, v5=True, bus=ev[0], vmot_above=ev[1], uc1=False, clr=False, resid=ev[2],
                   node_resid=ev[3], ff1_prev=True)
        for gv in itertools.product(LV, repeat=6):
            g = dict(zip(pins, gv)); g.update(p5="Z", p34="T", p20="Z")
            g2 = {k: ("L" if v == "Z" else v) for k, v in g.items()}
            for st in (1, 2):
                if hw(g, env, None, st) != hw(g2, env, None, st):
                    bad += 1
    print("  Z-versus-L equivalence over pins 33, 28-32 (pull-downs), 16 environments x 729 vectors x 2 stages:"
          " %d mismatches" % bad)

if __name__ == "__main__":
    hdr("Section 0: model reduction check")
    check_z_equals_l()
    section1()
    section2()
    section3()
    section4()
    section5()
    section6()
