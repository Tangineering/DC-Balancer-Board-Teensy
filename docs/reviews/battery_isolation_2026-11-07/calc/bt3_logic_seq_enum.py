"""Battle-test round 3, LOGIC / SEQUENCING lens: model check of the IC1 revision-5 control network and sequences.

Target: detailed_design_IC1.md revision 5 (sections 5.2, 6, 8, 9, 10, 11, 12). Stdlib only.
Run: python bt3_logic_seq_enum.py > bt3_logic_seq_enum_output.txt

Hardware model (design section 6, equations 1-13, Figures 2-5, revision-5 input network):
  GPIO p33,p35,p10,p28,p29,p30,p31,p32 in {L,H,Z}; p34 in {T,L,H,Z} (T = toggling); p20 in {L,Z} (open-drain WDOG1_B).
    Z = high-Z with the board pulls: R_P33/R_P34/R_P35/R_P10 10k, R_FQP/R_RQP 100k, RT1987 EN 10k bodges -> reads L.
  P33B = U_P33(p33)                          ; U_N33 pulls N1 LOW when P33B L          (R5-16)
  N1 = P33B & PUMP_OK & UC1_N & UC2_N & UIM_N & p20 & !(D5 & FCQ_armed) & !(BQ_OUT | BQ_wire_open)   (eq. 1)
  FF1: clear while N1 L; set by a P33B rising edge while N1 H; else hold                           (eq. 2)
  PUMP_OK = p34 toggling & 5V & LB3V3                                                              (eq. 3)
  CHk = OKk & BPk ; VOK = CH1 & CH2 (Stage 2) ; VOK = L (Stage 1, R_VKP)                          (eq. 4)
  EF_EN = FF1 & PUMP_OK & ((VOK & P30Q) | FCQ)   (R5-15)                                           (eq. 5)
  S_GND ON = !(FF1Q_SB & !UC1) ; S_CHG ON = FF1Q_SB & both S_GND gates low                         (eq. 6, 7)
  X = FF1./Q | SG1_ON | SG2_ON ; D-BT-SQ = p32 & !X                                                (eq. 8)
  D-BT-EN = p28 & !FCQ ; D-BC-RG = p30 & (Stage 2: OK1 & OK2 & BP1 & BP2) ; D-BC-FC = p31 ; D-MT-EN = p29
  LB3V3 tap open (Teensy alive): every LB IC unpowered (Ioff): FF1Q_SB on R_PA (bonded), SHDN_EF on R_SDP (eFuse off),
    OKk_N/BPk_N pull-ups to a dead rail read 0 V = "OK"/"present" -> Q_RG/Q_RB clamps OFF; X node has no source ->
    Q_X2 OFF; Q_X1 is a discrete FET whose gate is the pin-31 net through R_FQ -> still works.
Invariants:
  (a)  charger powered (eFuse conducting into a fed VCHG-IN) AND pack bonded (an S_GND channel ON)
  (a') (a) AND D-BT-SQ conducting  = the ML0227 configuration
  (b)  loop: charger powered AND fed from VBUS AND D-BT-SQ AND D-BT-EN
  (c)  defaults (Teensy Z / reset / hang): bonded, eFuse off, D-BT-SQ off
  (d)  every exit: charger input removed (eFuse off and module drained) before the bond
  (e)  NEW: a bonded-mode feed (VCHG-IN fed with FF1 clear) is either refused by firmware or seen by ERR_VCHG_FED
"""
import itertools

def hdr(t):
    print("\n" + "=" * 100 + "\n" + t + "\n" + "=" * 100)

LV = ("L", "H", "Z")

FAULTS = [None, "EFUSE_FET_SHORT", "U_AND_STUCK_H", "U_RS_STUCK_H", "U_OR_STUCK_H", "FF1Q_SB_STUCK_L",
          "Q_X1_OPEN", "Q_X2_OPEN", "DBTEN_SHORT", "DBCFC_SHORT", "DBCRG_SHORT", "U_N33_OPEN", "U_NP_OPEN",
          "U_CLS_STUCK_H", "LB3V3_TAP_OPEN"]

def hw(g, env, ff1_prev, fault, stage):
    p = {k: (v == "H") for k, v in g.items() if k not in ("p34", "p20")}
    teensy = env["teensy"]
    if not teensy:
        p = {k: False for k in p}
    lb = teensy and fault != "LB3V3_TAP_OPEN"
    v5 = env["v5"]
    pump_ok = lb and v5 and g["p34"] == "T" and teensy
    p33b = lb and p["p33"]
    fcq = p["p31"]
    p30q = p["p30"]
    uc1 = env["uc1"]
    uc2 = env.get("uc2", False) or env.get("clr", False)   # U_C2, U_IM, BQ OUT act identically on N1
    uim, bq = env.get("uim", False), env.get("bq", False)
    d5 = env.get("d5", False) and fcq
    wd = teensy and g["p20"] == "L"
    n1_src_low = (not p33b and fault != "U_N33_OPEN") or (not pump_ok and fault != "U_NP_OPEN") \
        or uc1 or uc2 or uim or wd or d5 or bq
    n1 = lb and not n1_src_low
    clr = (not n1) and fault != "U_CLS_STUCK_H"
    if not lb:
        ff1 = False
    elif clr:
        ff1 = False
    elif p33b and not env["p33_prev_H"]:
        ff1 = True
    else:
        ff1 = ff1_prev
    ff1q_sb = ff1 and lb and fault != "FF1Q_SB_STUCK_L"
    # VOK channel k (Stage 2). With the LB rail dead the open-drain outputs read 0 V = OK / present.
    if stage == 2:
        okk = env["vmot_above"] if lb else True
        bpk = env["bus"] if lb else True
        vok = (okk and bpk) and lb
    else:
        okk = bpk = False
        vok = False
    src = ((vok and p30q) or fcq) or (fault == "U_OR_STUCK_H") or (fault == "U_RS_STUCK_H" and lb)
    ef_en = (lb and ff1 and pump_ok and src) or (fault == "U_AND_STUCK_H" and lb)
    sgnd = (not ff1q_sb) or uc1
    schg = ff1q_sb and not sgnd
    sg_on = sgnd and lb
    x = lb and ((not ff1) or sg_on)
    btsq = p["p32"] and (not x or fault == "Q_X2_OPEN")
    bten = (p["p28"] and (not fcq or fault == "Q_X1_OPEN")) or fault == "DBTEN_SHORT"
    if stage == 2:
        rg = (p["p30"] and okk and bpk) or fault == "DBCRG_SHORT"
    else:
        rg = p["p30"] or fault == "DBCRG_SHORT"
    fc = (p["p31"] or fault == "DBCFC_SHORT") and env["bus"]
    mt = p["p29"] and env["bus"]
    # VCHG-IN feed: from VBUS (D-BC-FC), or from V-MOT via D-BC-RG; V-MOT is bus-fed when not above VBUS.
    rg_fed = rg and (env["vmot_above"] or mt)
    rg_busfed = rg and mt and not env["vmot_above"]
    fed = fc or rg_fed or env["resid"]
    efuse_on = (ef_en or fault == "EFUSE_FET_SHORT") and fed
    a = efuse_on and sgnd
    a2 = a and btsq
    b = efuse_on and (fc or rg_busfed) and btsq and bten
    fed_bonded = fed and not ff1
    return dict(ff1=ff1, a=a, a2=a2, b=b, sgnd=sgnd, schg=schg, btsq=btsq, efuse=efuse_on, fed_bonded=fed_bonded,
                ef_en=ef_en, bten=bten, rg=rg)

def section1():
    hdr("Section 1: exhaustive steady-state enumeration (fault-free, then single faults), Stage 1 and Stage 2")
    pins = ["p33", "p28", "p29", "p30", "p31", "p32"]        # p35/p10 act only through the injections (= uc1/clr)
    envkeys = ["teensy", "v5", "bus", "vmot_above", "uc1", "clr", "resid", "p33_prev_H"]
    print("  fault              stage  (a)hw   (a)fw   (a')fw  (b)fw   fed+bonded(fw)  example (a) or (b), firmware-legal")
    for stage in (1, 2):
        for fault in FAULTS:
            cnt = dict(ahw=0, afw=0, a2fw=0, bfw=0, fb=0)
            ex = None
            for gv in itertools.product(LV, repeat=len(pins)):
                g = dict(zip(pins, gv)); g["p35"] = "L"; g["p10"] = "L"
                for p34 in ("T", "S"):                      # S = static L, H or Z (no edges)
                    g["p34"] = p34
                    for p20 in ("L", "Z"):
                        g["p20"] = p20
                        Hs = {k for k in pins if g[k] == "H"}
                        # firmware-legal rule of rev 5 (12.4 item 7): p30/p31 HIGH only with p33 HIGH (charge mode
                        # commanded), except the eFuse-blocking probe (p31 H, p33 L, p32 L); p30 never H in Stage 1;
                        # p30 and p31 never together.
                        legal = True
                        if "p30" in Hs and ("p33" not in Hs or stage == 1 or "p31" in Hs):
                            legal = False
                        if "p31" in Hs and "p33" not in Hs and "p32" in Hs:
                            legal = False
                        for ev in itertools.product((False, True), repeat=len(envkeys)):
                            env = dict(zip(envkeys, ev))
                            for ffp in (False, True):
                                s = hw(g, env, ffp, fault, stage)
                                if s["a"]:
                                    cnt["ahw"] += 1
                                if legal and s["a"]:
                                    cnt["afw"] += 1
                                    if ex is None:
                                        ex = ("a", dict(g), {k: v for k, v in env.items() if v})
                                if legal and s["a2"]:
                                    cnt["a2fw"] += 1
                                if legal and s["b"]:
                                    cnt["bfw"] += 1
                                    if ex is None or ex[0] == "a":
                                        ex = ("b", dict(g), {k: v for k, v in env.items() if v})
                                if legal and s["fed_bonded"] and not env["resid"]:
                                    cnt["fb"] += 1
            exs = "-" if ex is None else "%s: %s env=%s" % (ex[0], " ".join("%s=%s" % kv for kv in ex[1].items()),
                                                          ",".join(sorted(ex[2])))
            print("  %-18s %5d  %7d %7d %7d %7d %13d   %s" % (fault, stage, cnt["ahw"], cnt["afw"], cnt["a2fw"],
                                                            cnt["bfw"], cnt["fb"], exs[:150]))
    print("""
  Reading. Fault-free, (a), (a') and (b) are unreachable for every GPIO vector (including Z) and every environment,
  because EF_EN needs FF1.Q and the bond needs NOT FF1Q_SB (eq. 5, 6). The 'fed+bonded' column is the bonded-mode
  VCHG-IN feed that the firmware-legal rule still permits (the eFuse-blocking probe; and Stage-2 VOK with p30 H in
  charge mode followed by an FF1 clear). It is not (a) without an eFuse bypass.
  LB3V3_TAP_OPEN (a single wire, M6 J2 05/06, Teensy alive): (a) stays unreachable because SHDN_EF falls to R_SDP, but
  in the same state the D-BT-SQ cross-lock (X) and all four D-BC-RG clamps release (open-drain pull-ups to a dead rail
  read 'OK' and 'bus present'), so the eFuse FET is the only hardware element between a bus-fed VCHG-IN and an
  ML0227 configuration - see section 4.""")

# ------------------------------------------------------------------------------------------------
# Section 2: two writers of pins 5 and 30 in State 2 (chargingControl() survives, design 12.2 item 5 / 12.4 item 6)
# ------------------------------------------------------------------------------------------------
def charging_control(t_ms, cmd_A, charge_goal, flag_vbatn_iso, trip_latched, removed_lines):
    """fw v37 rev 2 chargingControl() writes of pins 5 and 30 (ino:15289-15558), with the IC1 removals applied.
    Returns a list of (pin, level, line)."""
    w = []
    if charge_goal <= 0.05:
        w.append(("p5", 0, 15304))
        if 15308 not in removed_lines:
            w.append(("p30", 0, 15308))
        return w
    if cmd_A < -0.1:                                    # regenActive, ino:15338
        gated = (not flag_vbatn_iso) or trip_latched     # ino:15356
        w.append(("p30", 0 if gated else 1, 15357))      # NOT in the design's removal list
        w.append(("p5", 0, 15358))
        return w
    # cruise/coast: branch 15503-15506 compiled out, close path 15507-15527 kept; MPPT tail 15545-15556 kept
    if 15524 not in removed_lines:
        w.append(("p30", 0, 15524))
    w.append(("p5", 0, 15549))                          # charger not ready in the bonded mode / between pulses
    return w

def section2():
    hdr("Section 2: pin 5 (MPPT_DISABLE) and pin 30 (REGEN_ENABLE) have two writers inside a Stage-2 regen window")
    removed = {15308, 15375, 15395, 15524}              # design 12.4 item 6 list
    print("  Design 12.4 item 6 removes REGEN writes at ino:%s (all LOW writes). ino:15357 (the only HIGH writer:" %
          sorted(removed))
    print("  'digitalWrite(REGEN_ENABLE, chargerFeedGated ? LOW : HIGH)') is not listed; with AG105_VBATN_ISOLATED = 1")
    print("  (design 12.2 item 3) chargerFeedGated = ag105CommTripLatched only. MPPT_DISABLE writes at ino:15304, 15358,")
    print("  15377, 15549-15554 are not addressed by any removal, refusal or host test (12.11 lists only REGEN).")
    print()
    # Brake trace: command -12 A from t=0 for 600 ms, then 0 A. Mode manager per design 9.5 (arm 2 ticks, pin 5 H at
    # entry step 2, pin 33 H, settled, check, pin 30 H at ~6 ms). chargingControl at 50 Hz with phase phi.
    for charge_goal in (0.0, 0.5):
        for phi in (0, 7, 13, 19):
            p5 = 0; p30 = 0; p33 = 0
            p5_hist = []
            bonded_p30H = 0
            owner_conflicts = []
            win_open = False; exit_t = None
            for t in range(0, 1200):
                cmd = -12.0 if t < 600 else 0.0
                # mode manager (1 kHz, runs before doState2 in the same iteration)
                if not win_open and exit_t is None and t == 3:
                    p5 = 1; p33 = 1
                if not win_open and p33 and t == 6:
                    p30 = 1; win_open = True
                if win_open and t == 800:               # brake ended at 600 + 200 ms dwell
                    p30 = 0; exit_t = t; win_open = False
                if exit_t is not None and t == exit_t + 2:
                    p33 = 0
                if exit_t is not None and t == exit_t + 5:
                    p5 = 0
                # chargingControl at 50 Hz (doState2 after chgModeTick)
                if (t - phi) % 20 == 0 and t >= phi:
                    for pin, lvl, line in charging_control(t, cmd, charge_goal, True, False, removed):
                        if pin == "p5":
                            if lvl != p5:
                                owner_conflicts.append((t, "p5", lvl, line))
                            p5 = lvl
                        if pin == "p30":
                            if lvl != p30:
                                owner_conflicts.append((t, "p30", lvl, line))
                            p30 = lvl
                if win_open:
                    p5_hist.append(p5)
                if p30 and not p33:
                    bonded_p30H += 1
            frac = 100.0 * (1 - sum(p5_hist) / max(1, len(p5_hist)))
            first = owner_conflicts[:3]
            print("  charge_goal %.1f phase %2d ms: pin 5 LOW for %5.1f %% of the open window; pin 30 HIGH while pin 33 LOW"
                  " (bonded) for %4d ms; first conflicting writes %s" % (charge_goal, phi, frac, bonded_p30H, first))
    print("""
  Reading. With charge_goal 0 (OR-O: charge_goal ignored in Run) the charge_goal branch writes pin 5 LOW every 20 ms;
  with charge_goal > 0.05 the regen branch writes pin 5 LOW every 20 ms and pin 30 HIGH every 20 ms. In both cases the
  OR-4 condition (MPPTD HIGH inside every window, section 9.5 entry step 2) holds only until the first chargingControl()
  tick, 0-20 ms after entry, i.e. before or at the first VOK pulse. With charge_goal > 0.05 pin 30 also stays HIGH after
  the exit bond for the remaining 50 Hz ticks of the brake and is re-raised on every later brake tick in the bonded
  mode; ERR_VCHG_FED evaluates only with pins 30 and 31 commanded LOW (Table 16), so it is blind to this feed.""")

    # (d) interleaving: an exit that is NOT the brake end (I_L hold, 30 s cap, ladder, fault) while still braking.
    hits = 0; n = 0
    for phi in range(20):
        for exit_t in range(100, 140):
            n += 1
            # T_drain = 2 ms between p30 LOW (exit_t) and p33 LOW (exit_t + 2); chargingControl tick inside it re-raises
            for t in (exit_t, exit_t + 1):
                if (t - phi) % 20 == 0:
                    hits += 1
                    break
    print("\n  Invariant (d) on a commanded exit while the brake is still commanded (I_L hold, 30 s cap, ladder mismatch):")
    print("  if ino:15357 survives and no write chokepoint refuses it, a chargingControl() tick falls inside the 2 ms")
    print("  T_drain in %d of %d exit phases (%.0f %%): pin 30 is re-raised, RGQ = VOK & P30Q re-enables the eFuse, and"
          % (hits, n, 100.0 * hits / n))
    print("  pin 33 then goes LOW onto a powered, converting module (the F10 hardware-trip case on a commanded exit).")


def section2b():
    hdr("Section 2b: a brake whose window is refused (V_chg not yet below 11 V, rate limit, or IC1_STAGE 1)")
    removed = {15308, 15375, 15395, 15524}
    # VCHG-IN after a window exit at 21.47 V decays with tau 0.984 s (design Table 11): below 11 V after 0.658 s.
    import math
    t11 = 0.984 * math.log(21.47 / 11.0)
    print("  VCHG-IN 21.47 V -> 11 V after %.3f s (tau 0.984 s); a brake that starts sooner is refused a window by the" % t11)
    print("  entry precondition 'V_chg below 11 V' (design 9.5). With the rate limit (20 transitions/min) spent, every")
    print("  brake is refused. In Stage 1 (IC1_STAGE 1) no brake opens a window.")
    for stage, cg in ((1, 0.5), (2, 0.5)):
        p30_bonded = 0; p5_low = 0
        p30 = 0
        for t in range(0, 3000):                      # 500 ms brake, then 2.5 s cruise/coast in State 2
            cmd = -12.0 if t < 500 else 2.0
            if t % 20 == 0:
                for pin, lvl, line in charging_control(t, cmd, cg, True, False, removed):
                    if pin == "p30":
                        p30 = lvl
            if p30:
                p30_bonded += 1
        feed = ("D-BC-RG EN = pin 30 directly (M5 not made): VCHG-IN = V-MOT = VBUS through MOT_PWR, continuously"
                if stage == 1 else "D-BC-RG on whenever VOK: VCHG-IN fed from V-MOT at every regen pulse")
        print("  Stage %d, charge_goal %.1f, 500 ms brake + 2.5 s cruise, window refused: pin 30 HIGH, pack bonded, for %d of 3000 ms (no LOW writer left: 15308/15524 removed);"
              % (stage, cg, p30_bonded))
        print("     %s; ERR_VCHG_FED not evaluated (pin 30 commanded HIGH);" % feed)
        print("     eFuse held off only by FF1.Q L and the SRC term (Stage 1: FCQ L) - the 'input unfed in the bonded mode'")
        print("     barrier of rows F11/F13b/F35/F36 and of HR3 is gone for the whole brake.")

# ------------------------------------------------------------------------------------------------
# Section 3: Idle-entry self-test step 1 against the pump writer
# ------------------------------------------------------------------------------------------------
def section3():
    hdr("Section 3: self-test step 1 (design 9.3) at boot and at an Idle entry")
    # Pump model (design 7.4): PUMP_OK H while toggling >= 26 Hz; falls 43-76 ms after the last edge.
    cases = [("boot (setup(), pump not started, 12.3 item 5)", False),
             ("Idle entry from Run (pump toggling in every state, 12.4 item 1; Table 12 Idle and Self-test rows p34 = T)",
              True)]
    for name, pumping in cases:
        pump_ok = pumping
        expect = dict(ff1=False, ef_en=False, eflt=True, pump_ok=False, sg1=True, sg2=True)
        got = dict(ff1=False, ef_en=False, eflt=True, pump_ok=pump_ok, sg1=True, sg2=True)
        bad = [k for k in expect if expect[k] != got[k]]
        print("  %-105s step 1 %s%s" % (name, "PASS" if not bad else "FAIL", "" if not bad else " (mismatch: %s)" % bad))
    print("""
  Reading. Step 1 expects PUMP_OK L. The only pump-stop request in the self-test is in step 2, after step 1, and
  12.4 item 1 keeps pin 34 toggling in every state except CHG_INHIBITED, State-99 phase 3 and self-test stop intervals.
  At every Idle entry from Run the pump is running, PUMP_OK is H, step 1 fails on a healthy board, and section 9.3
  sets the reboot-only ERR_CHG_SELFTEST latch, which refuses every window until a power cycle. The boot self-test
  passes, so the defect appears at the first Run -> Idle transition of every power cycle (and in State 98 -> Idle).""")

# ------------------------------------------------------------------------------------------------
# Section 4: LB 3V3 tap open with the Teensy alive, per mode
# ------------------------------------------------------------------------------------------------
def section4():
    hdr("Section 4: LB 3V3 supply lead open (M6, J2 05/06) with the Teensy running - barrier inventory per mode")
    rows = [
        ("Idle/Run bonded (p32 H, p30 L, p31 L)", dict(p33="L", p35="L", p10="L", p28="H", p29="H", p30="L", p31="L", p32="H", p34="T", p20="Z"), False),
        ("Regen window, VOK false (V-MOT at bus)", dict(p33="H", p35="L", p10="L", p28="H", p29="H", p30="H", p31="L", p32="H", p34="T", p20="Z"), False),
        ("FC window", dict(p33="H", p35="L", p10="H", p28="L", p29="H", p30="L", p31="H", p32="H", p34="T", p20="Z"), False),
        ("State 99 latched (p32 H kept, Table 12)", dict(p33="L", p35="L", p10="L", p28="L", p29="L", p30="L", p31="L", p32="H", p34="L", p20="Z"), False),
    ]
    env = dict(teensy=True, v5=True, bus=True, vmot_above=False, uc1=False, uc2=False, uim=False, d5=False, bq=False,
               resid=False, p33_prev_H=True)
    print("  mode                                         fault           bonded eFuse D-BT-SQ D-BC-RG  fed+bonded  (a) (a') (b)")
    for name, g, _ in rows:
        for fault in (None, "LB3V3_TAP_OPEN", "LB3V3_TAP_OPEN+EFUSE"):
            f = "LB3V3_TAP_OPEN" if fault else None
            s = hw(g, env, True, f, 2)
            if fault == "LB3V3_TAP_OPEN+EFUSE":
                # second fault: eFuse FET short (F11) on top of the open tap
                fed = s["rg"] and g["p29"] == "H" or g["p31"] == "H"
                a = fed and s["sgnd"]
                print("  %-44s %-15s %6s %5s %7s %7s %11s  %3s %4s %3s" % (name, "tap+F11", s["sgnd"], fed, s["btsq"],
                      s["rg"], fed, a, a and s["btsq"], a and s["btsq"] and s["bten"] and fed))
                continue
            print("  %-44s %-15s %6s %5s %7s %7s %11s  %3s %4s %3s" % (name, str(f), s["sgnd"], s["efuse"], s["btsq"],
                  s["rg"], s["fed_bonded"], s["a"], s["a2"], s["b"]))
    print("""
  Reading. With the LB rail dead the bond is made (FF1Q_SB on R_PA) and the eFuse is held off by R_SDP, so (a) needs
  a second fault. But the same single lead removes the D-BT-SQ cross-lock (D-BT-SQ follows p32, which the design keeps
  HIGH in Idle, Run and State 99) and releases all four D-BC-RG clamps (D-BC-RG follows p30 whatever V-MOT and VBUS do).
  In a regen window pin 30 is HIGH, so VCHG-IN is bus-fed through D-MT-EN and D-BC-RG with the pack bonded until the
  firmware drops pin 30 (ERR_CHG_LADDER after 3 ms of a mismatched ladder: ladders read code 0). Table 13 and the HR5
  row treat '3V3 lost' as 'Teensy also unpowered'; R4-3 (g) states only that a 5 V loss no longer reads OK.""")

# ------------------------------------------------------------------------------------------------
# Section 5: defaults (c) and hardware-exit ordering (d) recap for revision 5
# ------------------------------------------------------------------------------------------------
def section5():
    hdr("Section 5: defaults (c) and exit ordering (d), revision-5 network")
    env0 = dict(teensy=False, v5=True, bus=True, vmot_above=True, uc1=False, uc2=False, uim=False, d5=False, bq=False,
                resid=True, p33_prev_H=True)
    g0 = dict(p33="Z", p35="Z", p10="Z", p28="Z", p29="Z", p30="Z", p31="Z", p32="Z", p34="Z", p20="Z")
    for stage in (1, 2):
        s = hw(g0, env0, True, None, stage)
        print("  Teensy unpowered/reset, stage %d, VCHG-IN residual, V-MOT above bus: bonded=%s eFuse=%s D-BT-SQ=%s (a)=%s (b)=%s"
              % (stage, s["sgnd"], s["efuse"], s["btsq"], s["a"], s["b"]))
    # Hang mid-window: pins static, pump static -> PUMP_OK L after 43-76 ms
    g1 = dict(p33="H", p35="L", p10="L", p28="H", p29="H", p30="H", p31="L", p32="H", p34="H", p20="Z")
    env1 = dict(env0, teensy=True, resid=False)
    s = hw(g1, env1, True, None, 2)
    print("  Hang in a regen window after 43-76 ms (p34 static): FF1=%s bonded=%s eFuse=%s (a)=%s; fed+bonded=%s"
          % (s["ff1"], s["sgnd"], s["efuse"], s["a"], s["fed_bonded"]))
    print("""
  (c) holds for an absent rail, a reset and a hang (after 43-76 ms) with the fault-free network. (d) holds for a
  commanded exit only while pin 30 and FC_CHARGE have a single writer (section 2); for a hardware exit the module
  converts from C_in for up to about 1.1 ms after the bond with D-BT-SQ still enabled for 0.3-0.7 ms (row F10,
  unchanged in kind).""")

if __name__ == "__main__":
    section1()
    section2()
    section2b()
    section3()
    section4()
    section5()
