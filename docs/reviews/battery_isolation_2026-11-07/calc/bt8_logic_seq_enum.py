"""Battle-test round 8, LOGIC / SEQUENCING lens: model check of IC1 revision 11 as a whole.

Target: detailed_design_IC1.md revision 11 (sections 0.8-0.11, 5.2, 5.3, 9.3, 9.7, 9.7a, 9.7b, 9.9, 9.11, 12.4,
12.6, Appendices F and I).  Extends calc/bt7_logic_seq_enum.py (which reuses the bt5/bt4 hardware network hw5()) with:
  - the revision-8 LB-entry resistors R_VC1c, R_MS3, R_BL3 (+ R_BL2 100k), R_PGL: levels seen by the comparators,
    the LVC buffer and the profile FETs, with every Teensy GPIO in {L, H, Z};
  - the revision-11 rules: State-2 dump check then window at the same stop (R11-1), the explicit request flag and
    refusal codes 11/12/15 (R11-2), the fixed window split and the share-loop freeze (R11-4), the boost-enable entry
    condition and the exit-step-4 BT_REG latch (R11-5, F64), the guarded Idle FC_BUS release (R11-6);
  - the interaction of the Idle-entry self-test (9.3, 12.4 item 8) with a standing window request (OR-RQ parked form,
    9.11.6) and with the Run/Idle/State-98 transitions.
Re-proves (a) no charger powered with the pack bonded, (b) no bus->charger->pack->BT boost->bus loop, (c) safe
defaults, (d) charger input removed before the bond on every exit, (e) no Death-5 re-close onto a collapsed node,
(f) no healthy-board trace latches a fault.

Stdlib only.  Run:
  .venv_hil/Scripts/python.exe docs/reviews/battery_isolation_2026-11-07/calc/bt8_logic_seq_enum.py
      > docs/reviews/battery_isolation_2026-11-07/calc/bt8_logic_seq_enum_output.txt

Numeric inputs (all cited; none new):
  R_BL1 150k, R_BL3 47k, R_BL2 100k; LVC VIH 2.0 V; leakage offset 0.33 V via 66 kOhm   design Table 7 row R_BL*;
                                                                                        Appendix F item 3
  R_PGL 22k, R_PG 1k, R_PGP 100k; BSS138 V_GS(th) 0.8-1.5 V                              design Fig. 6; section 4.2
  R_VC1a/R_VC1b 200k, R_VC1c 22k, C_VC1 100 nF (tau 12.2 ms); ERR_CELL_MISMATCH 80 mV/1 s  design 5.2; Table 16
  R_MS1 100k, R_MS2 16.2k, C_MS 1 nF (lead side), R_MS3 22k                              design Fig. 2, 5.3 item 3
  Idle-entry self-test 357.7-457.5 ms                                                    calc/cc_completeness_calcs s1
  Pi first command 0.00-0.49 s into the recorded sessions                                calc/fmea_round7_calcs s1
  loop median 1.131 ms, p99 1.341 ms, one 9.76 ms gap                                    facts_firmware s8; calc10 s1
  t_D_ON 8/12 ms, D-BT-EN soft-start onto a live bus 19.77 ms                            design Table 20
"""
import itertools
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt5_logic_seq_enum as bt5   # noqa: E402  (main-guarded)
import bt7_logic_seq_enum as bt7   # noqa: E402  (main-guarded)

LOOPS = (1.131, 1.341)
GAP = 9.76
T_SS = 19.77


def hdr(t):
    print("\n" + "=" * 112 + "\n" + t + "\n" + "=" * 112)


# =============================================================================================================
# Section 1: revision-8 LB-entry resistors - levels at the comparators, the LVC buffer and the profile FETs
# =============================================================================================================
def section1():
    hdr("Section 1: revision-8 LB-entry resistors (R_BL3/R_BL2, R_PGL, R_MS3, R_VC1c): logic levels, every GPIO level")
    # BAL_OK (design Fig. 5 line 745; Table 7; Appendix F item 3)
    R1, R3 = 150e3, 47e3
    VIH, VIL = 2.0, 0.8
    print("  BAL_OK = VBAL+ x R_BL2 / (R_BL1 + R_BL3 + R_BL2), offset +/- I_I x Thevenin (I_I 5 uA, TODO(verify: TI SN74LVC244A))")
    for R2 in (100e3, 82e3):
        th = 1.0 / (1.0 / (R1 + R3) + 1.0 / R2)
        off = 5e-6 * th
        for vp in (7.4, 8.0, 8.5):
            vn = vp * R2 / (R1 + R3 + R2)
            print("    R_BL2 %3.0fk  pack %.1f V: nominal %.3f V, worst %.3f V  (VIH %.1f V) -> %s"
                  % (R2 / 1e3, vp, vn, vn - off, VIH, "H" if vn - off >= VIH else "INDETERMINATE"))
        vp_min = (VIH + off) * (R1 + R3 + R2) / R2
        print("    R_BL2 %3.0fk: lowest pack with a guaranteed H = %.2f V (Thevenin %.1f kOhm, offset %.3f V)"
              % (R2 / 1e3, vp_min, th / 1e3, off))
    print("    The fitted value is 100 kOhm (Table 7: 'R_BL2 was 82 kOhm'); the 82 kOhm rows are the pre-revision-8 value.")
    # PROFILE (Fig. 6 line 773)
    for v3 in (3.2, 3.3, 3.4):
        vg = v3 * 100e3 / (22e3 + 1e3 + 100e3)
        print("  PROFILE HIGH at 3V3 %.1f V: Q_CS/Q_MP V_GS = %.2f V (BSS138 V_GS(th) max 1.5 V) -> ON" % (v3, vg))
    print("  PROFILE with pin 10 L or Z: pin-10 net on R_P10 10k, CB gates on R_PGP 100k -> 0 V -> OFF (regen profile)")
    # U_MS
    th_ms = 1.0 / (1 / 100e3 + 1 / 16.2e3)
    print("  U_MS IN+: lead node Thevenin %.2f kOhm x C_MS 1 nF = %.1f us; R_MS3 22k x C_in (pF) adds < 0.1 us"
          % (th_ms / 1e3, th_ms * 1e-9 * 1e6))
    print("    exit hold check samples at 50 us and 150 us: unchanged by R_MS3 (TLV3011B input bias pA range)")
    # VC1 tap after a bond
    tau = (100e3 + 22e3) * 100e-9
    import math
    for dv in (0.05, 0.1, 0.2):
        t80 = tau * math.log(2 * dv / 0.080) if 2 * dv > 0.080 else 0.0
        print("  VC1 tap at the bond: PACK- step %.2f V -> mismatch term 2 x step decays below 80 mV in %.1f ms"
              " (persistence 1 s)" % (dv, t80 * 1e3))
    # (c) through the network: the rev-8 resistors are not terms of hw5 (they set analog levels only); re-run Z set
    pins = ["p33", "p28", "p29", "p30", "p31", "p32"]
    envkeys = ["v5", "bus", "vmot_above", "uc1", "clr", "resid", "node_resid", "ff1_prev"]
    bad = n = 0
    for gv in itertools.product(bt5.bt4.LV, repeat=len(pins)):
        g = dict(zip(pins, gv))
        for p10, p5, p8, p20 in itertools.product(bt5.bt4.LV, repeat=4):
            g.update(p5=p5, p8=p8, p20=p20, p34="S", p10=p10)
            for ev in itertools.product((False, True), repeat=len(envkeys)):
                env = dict(zip(envkeys, ev))
                env["teensy"] = False
                s = bt5.hw5(g, env, None, 1)
                n += 1
                if not s["sgnd"] or (s["efuse"] and not env["resid"]):
                    bad += 1
    print("  (c) Teensy unpowered/reset, pins 33/28/29/30/31/32/10/5/8/20 in {L,H,Z}: %d states, S_GND off or eFuse on"
          " without a residual: %d" % (n, bad))
    print("""
  Reading. The four revision-8 resistors change analog levels only. BAL_OK holds a guaranteed H down to a 6.92 V pack
  with the fitted 100 kOhm (0.48 V below the 7.4 V entry floor); PROFILE drives the CB FETs at 2.60-2.76 V; U_MS and
  the exit hold check keep their timing; the VC1 tap transient at a bond is 2-14 ms against a 1 s persistence. No
  revision-8 resistor is a term of the latch, the eFuse enable or the S_GND drive, so (a), (b), (c) are unchanged.""")


# =============================================================================================================
# Section 2: revision-11 sequences through the hardware network (a), (b), (b'), (d)
# =============================================================================================================
W = dict(p33="H", p28="L", p31="H", p29="H", p30="L", p32="H")


def v(**k):
    d = dict(W)
    d.update(k)
    return d


SEQ = {
    "R11-1 State-2 dump check (pin 32 L) then window at the same stop": [
        ("dc 1 p32 L, p10 H", v(p31="L", p33="L", p28="H", p32="L"), False),
        ("dc 2 p33 H", v(p31="L", p28="H", p32="L"), True),
        ("dc 3 BT_BUS L; split written", v(p31="L", p32="L"), True),
        ("dc 4 FC_CHARGE H", v(p32="L"), True),
        ("dc exit 1 feed drop", v(p31="L", p32="L"), True),
        ("dc exit 3 bond", v(p31="L", p33="L", p32="L"), False),
        ("dc exit 4 BT_BUS H", v(p31="L", p33="L", p28="H", p32="L"), False),
        ("p32 H after FF1 L", v(p31="L", p33="L", p28="H"), False),
        ("365.6 ms later: win 3 p33 H", v(p31="L", p28="H"), True),
        ("win 5 BT_BUS L", v(p31="L"), True), ("win 6 FC_CHARGE H", v(), True)],
    "R11-1 dump check aborted by traction (no verdict)": [
        ("dc 4 FC_CHARGE H", v(p32="L"), True), ("exit 1 feed drop, VESC 0 A", v(p31="L", p32="L"), True),
        ("exit 3 bond", v(p31="L", p33="L", p32="L"), False),
        ("exit 4 BT_BUS H, hold 31.8 ms", v(p31="L", p33="L", p28="H", p32="L"), False),
        ("p32 H", v(p31="L", p33="L", p28="H"), False)],
    "R11-5 / F64 exit step 4 with BT_REG LOW -> latch, no BT_BUS write": [
        ("window", v(), True), ("exit 1 feed drop", v(p31="L"), True), ("exit 3 bond", v(p31="L", p33="L"), False),
        ("latch ph0 (27/28 L)", v(p31="L", p33="L"), False), ("p32 L", v(p31="L", p33="L", p32="L"), False)],
    "P exit on a State 1->2 request (VESC held)": [
        ("window", v(), True), ("exit 1", v(p31="L"), True), ("exit 3 bond", v(p31="L", p33="L"), False),
        ("exit 4 BT_BUS H", v(p31="L", p33="L", p28="H"), False)],
    "Finish inside a D-s window (exit continues in State 1)": [
        ("window", v(), True), ("exit 1", v(p31="L"), True), ("exit 3", v(p31="L", p33="L"), False),
        ("exit 4", v(p31="L", p33="L", p28="H"), False)],
    "State-98 Q inside a P window (exit, then MOT_PWR L)": [
        ("window", v(), True), ("exit 1", v(p31="L"), True), ("exit 3", v(p31="L", p33="L"), False),
        ("exit 4", v(p31="L", p33="L", p28="H"), False), ("Q: MOT_PWR L", v(p31="L", p33="L", p28="H", p29="L"),
                                                         False)],
    "Idle-entry self-test steps 4-8 after a P exit (charge mode, BT_BUS H)": [
        ("bonded", v(p31="L", p33="L", p28="H"), False), ("step 4 p33 H", v(p31="L", p28="H"), True),
        ("step 4b p33 L", v(p31="L", p33="L", p28="H"), True), ("step 8 pump stop", v(p31="L", p28="H"), True)],
}


def section2():
    hdr("Section 2: revision-11 sequences through the hardware network (bt5.hw5): (a), (b), (b'), (d)")
    envkeys = ["v5", "bus", "vmot_above", "uc1", "clr", "resid", "node_resid"]
    for name, steps in SEQ.items():
        cnt = dict(a=0, b=0, bp=0, d=0, n=0)
        for lab, pins, ff1prev in steps:
            for ev in itertools.product((False, True), repeat=len(envkeys)):
                env = dict(zip(envkeys, ev))
                env.update(teensy=True, ff1_prev=ff1prev)
                if env["uc1"] or env["clr"] or not env["v5"]:
                    continue
                g = dict(pins)
                g.update(p5="Z", p8="Z", p20="Z", p34="T")
                s = bt5.hw5(g, env, None, 1)
                cnt["n"] += 1
                cnt["a"] += s["a"]
                cnt["b"] += s["b"]
                cnt["bp"] += (g["p28"] == "H" and g["p31"] != "H") and s["ff1"]
                cnt["d"] += s["sgnd"] and s["efuse"] and not env["resid"]
        print("  %-66s steps %2d, states %4d: (a) %d (b) %d (b') %d (d) %d"
              % (name, len(steps), cnt["n"], cnt["a"], cnt["b"], cnt["bp"], cnt["d"]))
    print("""
  Reading. (a), (b) and (d) are 0 on every revision-11 sequence. The (b') states are the charge-mode steps with BT_BUS
  HIGH and FCQ LOW (entry steps 3-4, self-test steps 4-8), the accepted board load through the sense in reverse.""")


# =============================================================================================================
# Section 3: timed model - F64 rule and the fixed-split restore against D-BT-EN conduction
# =============================================================================================================
class Sim11(bt7.Sim):
    """bt7.Sim with the revision-11 exit-step-4 rule: BT_REG LOW -> ERR_FC_ONLY_COLLAPSE, no BT_BUS write."""

    def step(s, t):
        if s.latched is None and s.chg == "EXIT" and getattr(s, "k", 0) == 3 and not s.bt_reg:
            return s.latch(t, "R11-5 BT_REG LOW at exit step 4")
        return bt7.Sim.step(s, t)


def section3():
    hdr("Section 3: timed model - R11-5 exit rule (F64) and the R11-4 restore against D-BT-EN conduction")
    for loop in LOOPS:
        s = Sim11("P", loop, None, 12.0, 140.0, None, 0.0, 0.16, False, False, bt_reg=False).run(1400.0 + 400.0)
        print("  loop %.3f ms, BT_REG LOW: latch %s; BT_BUS write %s; FC_BUS at the FC recovery %s"
              % (loop, s.latched, s.ev.get("bt_write"), s.ev.get("rec")))
    print("  Restore of the stored split = the iteration after the BT_BUS write (12.4 item 10):")
    for loop, gap_after in itertools.product(LOOPS, (False, True)):
        dt = GAP if gap_after else loop
        for tdon in (8.0, 12.0):
            print("    loop %.3f ms, %s: restore at write + %.2f ms; D-BT-EN conduction bound write + %.1f ms -> %s"
                  % (loop, "9.76 ms gap after the write" if gap_after else "no gap", dt, tdon + T_SS,
                     "restore first" if dt < tdon + T_SS else "LATE"))
    print("""
  Reading. With BT_REG LOW the exit latches at step 4 with no BT_BUS write, and FC_BUS is LOW at the FC recovery: the
  bt7 section-6 trace is closed (no write onto a disabled TPS61288). The restore lands 1.1-9.8 ms after the BT_BUS
  write, before the 27.8-31.8 ms conduction bound of Table 20 in every case (Appendix I item 3). The R11-5 entry
  condition makes the BT_REG-LOW exit reachable only through a firmware defect (row F64).""")


# =============================================================================================================
# Section 4: Idle-entry self-test against a standing window request and the Run/Idle/State-98 transitions
# =============================================================================================================
SELFTEST_MS = (357.7, 457.5)        # cc section 1
PI_FIRST_CMD_S = (0.04, 0.02, 0.00, 0.04, 0.03, 0.49)   # fmea_round7 section 1 (six sessions with a request)


def idle_entry(request_standing, run_cmd_after_ms, stage, mot_pwr_high, rule="as written"):
    """One Idle entry.  Returns (self-test result, windows admitted afterwards in this Idle/Run).
    as written: 9.3 'Abort': a State-2 request or a mode-manager request for a window aborts -> deferred;
                'A deferred result refuses every window until a later Idle entry passes' (9.3, 12.4 item 8, Table 16).
    wait:       the alternative reading of 9.3 last paragraph ('delays the first window by that time')."""
    dur = SELFTEST_MS[1]
    if stage == 2 and not mot_pwr_high:
        return "deferred (step 10, MOT_PWR LOW)", False
    if request_standing and rule == "as written":
        return "deferred (aborted by the window request at its first step)", False
    if run_cmd_after_ms is not None and run_cmd_after_ms < dur:
        return "deferred (aborted by the State-2 request at %.0f ms < %.1f ms)" % (run_cmd_after_ms, dur), False
    return "pass", True


def section4():
    hdr("Section 4: Idle-entry self-test vs a standing request (OR-RQ parked form) and Run/Idle/State-98 transitions")
    cases = [
        ("T1 Run -> Pi MODE_SAFE + 0xA5 + charge_goal (parked form, 9.11.6) -> Finish -> Idle", True, None, 1, True),
        ("T2 Idle with the parked request already standing at a later Idle entry", True, None, 1, True),
        ("T3 State 98 -> Q (MOT_PWR LOW, ino:9279) -> Idle, Stage 2, no request", False, None, 2, False),
        ("T4 State 98 -> Q -> Idle, Stage 1, parked request standing", True, None, 1, False),
    ]
    for name, req, runms, stage, mp in cases:
        for rule in ("as written", "wait"):
            res, ok = idle_entry(req, runms, stage, mp, rule)
            print("  %-86s [%s] self-test %s -> windows %s" % (name, rule, res, "admitted" if ok else
                                                                   "REFUSED until a later Idle entry passes"))
    print("  T5 boot -> State 0 -> State 1 (if an Idle entry runs the self-test) -> Pi mode_cmd 0-3 (changeToRun):")
    n_abort = 0
    for t in PI_FIRST_CMD_S:
        res, ok = idle_entry(False, t * 1e3, 1, True)
        n_abort += not ok
        print("      first command %.2f s: %s -> D-s windows in this Run %s" % (t, res, "admitted" if ok else "REFUSED"))
    print("      %d of %d recorded sessions would abort (offset of the bag start to the Teensy Idle entry UNCONFIRMED)"
          % (n_abort, len(PI_FIRST_CMD_S)))
    # what re-enables windows after a deferred result in a parked vehicle
    print("  Later Idle entries reachable from State 1 without driving: State 98 'T' then 'Q' (ino:9279: MOT_PWR LOW;"
          " Stage 2 step 10 -> deferred again; Stage 1: request still standing -> aborted again)")
    print("""
  Reading. Section 9.3 'Abort' and 12.4 item 8 abort the Idle-entry self-test on a window request and record
  'deferred'; a deferred result 'refuses every window until a later Idle entry passes'. The OR-RQ parked request is
  sent in every packet from the MODE_SAFE packet that causes the Finish, so it stands at the Idle entry: the self-test
  aborts at its first step and every P window of that Idle is refused, with no refusal code in Table 25. A parked
  vehicle has no later Idle entry that can pass (T2, T4; T3 in Stage 2). The same rule defers the boot-time Idle
  self-test whenever the Pi commands Run within 357.7-457.5 ms of the Idle entry, which refuses every D-s window of
  that Run. The 'wait' reading (9.3 last paragraph: the self-test 'delays the first window') removes T1, T2, T4.""")


if __name__ == "__main__":
    section1()
    section2()
    section3()
    section4()
