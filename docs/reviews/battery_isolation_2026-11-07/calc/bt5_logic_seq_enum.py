"""Battle-test round 5, LOGIC / SEQUENCING lens: model check of the IC1 revision-7 delta.

Target: detailed_design_IC1.md revision 7 (sections 6, 8 Table 11, 9.2, 9.3, 9.5, 9.7, 9.7a, 9.8, 9.9, 10, 12.4-12.6,
Table 7a/8a, Table 16, Appendix E).  Reuses the revision-6 network model hw() of calc/bt4_logic_seq_enum.py (which
reuses bt3) and adds the revision-7 delta:
  - D_N20 / WDOG1_B deleted: pin 20 is an analog input (VC1 tap), no N1 term          design R7-2, eq. 1, 12.3 item 1
  - Stage 3 withdrawn: Q_MD = NOT EF_EN only                                            design R7-4, eq. 5
  - ERR_MOD_DUMP_ON: FC_CURRENT 10 ms after chargerHasPower() first true vs the iteration before the EF_EN rise,
    step > 0.4 A latches; evaluated in FC windows, configuration checks and commissioning   Table 16, 9.7 step 6
  - ERR_MOD_SENSE (b) crossing anchor; deadline later of 10 ms and 4 iterations, cap 30 ms   Table 16, 9.5
  - ERR_MOD_SENSE (c) exit hold check: "in the iteration of a commanded feed drop, after a window in which pin 8 read
    HIGH and with V_chg at or above 13.5 V on the last settled reading, pin 8 reads LOW at 50 us or 150 us after the
    write"                                                                               Table 16 (c), 9.5 exit step 1
  - Idle-entry self-test step 1 (CH bits Stage 1 only), step 10 settle                  9.3
  - chokepoint setters pins 5/30/31, open-drain pin 5, cold-module rule                  12.4 items 2, 7; 12.5 item 3
Stdlib only.  Run:  python bt5_logic_seq_enum.py > bt5_logic_seq_enum_output.txt

Numeric inputs (all cited):
  V-MOT pulse 15.9 -> 21.20-21.47 V in 19-47 ms; decay 14-20 V/s; second pulse 0.523-0.562 s after the first
                                                                                        facts_prior section 6
  VOK assert 16.90-17.24 V, release 16.16-16.43 V (centred hysteresis: 16.13 V)          design eq. 4, calc7 section 5
  VCHG-IN bleed tau 0.984 s                                                              design Table 11
  eFuse UVLO rising 12.38-12.88 V; turn-on ~1.24 ms; output slew <= 5.79 V/ms            design 7.5, Table 11
  VCHG-IN ramp 12 V/ms (D-BC-FC / D-BC-RG soft start)                                    design Table 11
  U_MS threshold 8.69-9.15 V; R_MD 15 Ohm; C_mod 100-221 uF; R_MB 3.3 kOhm              design 5.3, Table 11
  loop: median 1.131 ms, p99 1.341 ms, worst gap 9.76 ms                                 facts_firmware section 8
  Table 8 FC profile input power 13.0-14.8 W; Table 8a allowance eFuse enable -> charge current 6.4/5.3 ms (19 ms
  pulse), 29.3/26.4 ms (47 ms pulse); eFuse delay+ramp 4.4-5.6 ms                       design 7.1, 7.8
  Stage 2 firmware only after S0-6 shows a cold start inside Table 8a                    design 14.3
"""
import itertools
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bt4_logic_seq_enum as bt4   # noqa: E402  (main-guarded; only hw() and constants are used)

TAU_VCHG = bt4.TAU_VCHG
UVLO_R = bt4.UVLO_R
T_EF_ON = bt4.T_EF_ON
SLEW = bt4.SLEW
RAMP_VCHG = bt4.RAMP_VCHG
LOOPS = (1.131e-3, 1.341e-3)
GAP = 9.76e-3


def hdr(t):
    print("\n" + "=" * 110 + "\n" + t + "\n" + "=" * 110)


# =============================================================================================================
# Section 1: exhaustive steady state with every Teensy GPIO in {L, H, Z}, including pins 5, 8 and 20
# =============================================================================================================
def hw5(g, env, fault, stage):
    """Revision-7 network = revision-6 network (bt4.hw, which ignores p20) plus GPIO-configuration effects on pins
    5, 8 and 20.  Pin 8 is an input; if firmware mis-configures it as an OUTPUT, the read returns the driven level."""
    s = bt4.hw(g, env, fault, stage)
    p8cfg = g.get("p8", "Z")          # Z = INPUT_PULLUP (design), L/H = mis-configured push-pull output
    if env["teensy"] and p8cfg in ("L", "H") and s["pin8"] is not None:
        s = dict(s)
        s["pin8"] = p8cfg
        s["false_cold"] = s["node_hot"] and p8cfg == "L"
    return s


def section1():
    hdr("Section 1: exhaustive steady state, revision-7 network, GPIO in {L,H,Z} incl. pins 5, 8, 20")
    pins = ["p33", "p28", "p29", "p30", "p31", "p32"]
    envkeys = ["teensy", "v5", "bus", "vmot_above", "uc1", "clr", "resid", "node_resid", "ff1_prev"]
    tot = dict(a=0, b=0, cbad=0, fc=0, p20eff=0, n=0)
    p8_false_cold = 0
    for stage in (1, 2):
        for gv in itertools.product(bt4.LV, repeat=len(pins)):
            g = dict(zip(pins, gv))
            Hs = {k for k in pins if g[k] == "H"}
            legal = not (("p30" in Hs and ("p33" not in Hs or stage == 1 or "p31" in Hs))
                         or ("p31" in Hs and "p33" not in Hs and "p32" in Hs))
            for p8, p34 in itertools.product(bt4.LV, ("T", "S")):
                g.update(p5="Z", p8=p8, p20="Z", p34=p34)
                for ev in itertools.product((False, True), repeat=len(envkeys)):
                    env = dict(zip(envkeys, ev))
                    s = hw5(g, env, None, stage)
                    tot["n"] += 1
                    if legal and s["a"]:
                        tot["a"] += 1
                    if legal and s["b"]:
                        tot["b"] += 1
                    if not env["teensy"] and (not s["sgnd"] or (s["efuse"] and not env["resid"])):
                        tot["cbad"] += 1
                    if s["false_cold"] and env["teensy"]:
                        tot["fc"] += 1
                        if p8 == "L":
                            p8_false_cold += 1
                    if p8 == "Z" and p34 == "T":
                        # pins 5 and 20 in {L,H,Z}: any change of a hardware output other than the pin-5 source flag
                        for p5, p20 in itertools.product(bt4.LV, bt4.LV):
                            g2 = dict(g); g2.update(p5=p5, p20=p20)
                            s2 = dict(hw5(g2, env, None, stage)); s1 = dict(s)
                            s2.pop("p5src"); s1.pop("p5src")
                            if s2 != s1:
                                tot["p20eff"] += 1
    print("  states evaluated: %d (6 control pins x {L,H,Z}, pin 8 x {L,H,Z}, pump T/S, 9 env bits, 2 stages; pins 5/20 x {L,H,Z} on the pin-8-Z subset)"
          % tot["n"])
    print("  (a) charger powered AND pack bonded, firmware-legal vectors, fault-free : %d" % tot["a"])
    print("  (b) bus->charger->pack->BT boost->bus loop, firmware-legal, fault-free    : %d" % tot["b"])
    print("  (c) Teensy unpowered/reset with S_GND off or eFuse on without residual    : %d" % tot["cbad"])
    print("  pin 5 or pin 20 level changes any hardware output (besides pin-5 sourcing)  : %d" % tot["p20eff"])
    print("  false-cold reads (pin 8 LOW while node fed), all from pin 8 driven LOW     : %d of %d"
          % (p8_false_cold, tot["fc"]))
    print("""
  Reading. Fault-free, (a), (b) and (c) are 0 over every GPIO level including Z: the revision-7 delta (D_N20 deleted,
  Stage 3 deleted, pin 20 analog) touches no term of eq. 1-13. Pin 20 has no hardware effect in any level. A pin 8
  mis-configured as an output driven LOW blinds the drain wait, ERR_MOD_FED and the eFuse-blocking probe; it is caught
  by ERR_MOD_SENSE (b) in the configuration check or FC window that precedes every regen window of a power cycle (the
  check always sees a crossing: entry requires V_chg < 11 V). The single-fault rows are unchanged from bt4 section 1.""")


# =============================================================================================================
# Section 2: ERR_MOD_SENSE (c) exit hold check against a regen window exit between pulses (healthy board)
# =============================================================================================================
def node_after_release(t_since_release, v_rel, cmod=100e-6, imod=0.018):
    """Module node after EF_EN falls at the VOK release: Q_MD + R_MB + module idle load; returns V."""
    v, t, dt = v_rel, 0.0, 2e-5
    while t < t_since_release and v > 0.05:
        v -= (v / 15.0 + v / 3300.0 + (imod if v > 9.0 else 0.0)) / cmod * dt
        t += dt
    return max(v, 0.0)


def section2():
    hdr("Section 2: ERR_MOD_SENSE (c) at a regen-window exit taken between pulses (healthy board)")
    print("  Rule text (Table 16 (c), 9.5 exit step 1): arm when pin 8 read HIGH in this window AND V_chg >= 13.5 V on")
    print("  the last settled reading; latch if pin 8 reads LOW 50 us or 150 us after the feed-drop write.")
    print("  V_chg is pin 38 = VCHG-IN, the eFuse INPUT. After a VOK release EF_EN is L, the eFuse blocks and Q_MD dumps")
    print("  the module node to < 9 V within ~1-3 ms, while VCHG-IN holds its charge (tau 0.984 s, D-BC-RG an ideal")
    print("  diode, clamped). The rule never asks whether the node is fed at the moment of the write.\n")
    print("  peak  decay  release  t_rel(s)  VCHG>=13.5 until(s)  trap span(s)  trap/period(0.523-0.562 s)  node@50us")
    rows = []
    for peak in (21.20, 21.47):
        for decay in (14.0, 20.0):
            for rel in (16.13, 16.43):
                t_rel = 0.019 + (peak - rel) / decay           # after pulse start (19 ms rise)
                span = TAU_VCHG * math.log(rel / 13.5)
                node = node_after_release(0.002, rel)           # 2 ms after release (one+ iteration later)
                f_lo, f_hi = span / 0.562, span / 0.523
                rows.append(span)
                print("  %5.2f  %5.1f  %7.2f  %8.3f  %19.3f  %12.3f  %11.0f-%2.0f %%                %5.2f V"
                      % (peak, decay, rel, t_rel, t_rel + span, span, 100 * f_lo, 100 * f_hi, node))
    print("\n  Every exit written in [t_rel, t_rel + span] after a captured pulse (pin 8 HIGH earlier in the window)")
    print("  latches ERR_MOD_SENSE (c) on a healthy board: windows refused for the power cycle and the last")
    print("  eFuse-blocking probe voided (a new configuration check is needed).")
    # Monte Carlo: exits at a uniformly random time inside a pulse train (Pi finish, traction request 9.6, 30 s cap,
    # I_L exit, release dwell end), and the 200 ms release dwell after a brake demand that ends with the last pulse.
    rnd = random.Random(5)
    N = 20000
    hits = 0
    hits_dwell = 0
    for _ in range(N):
        peak = rnd.uniform(21.20, 21.47)
        decay = rnd.uniform(14.0, 20.0)
        rel = rnd.uniform(16.13, 16.43)
        period = rnd.uniform(0.523, 0.562)
        t_rel = 0.019 + (peak - rel) / decay
        span = TAU_VCHG * math.log(rel / 13.5)
        te = rnd.uniform(0.0, period)                          # exit phase within the period of a later pulse
        if t_rel <= te <= min(t_rel + span, period):
            hits += 1
        # brake demand ends at a uniform time in [peak, t_rel] (decel finishing on the last pulse) + 200 ms dwell
        tb = rnd.uniform(0.019, t_rel) + 0.200
        if t_rel <= tb <= t_rel + span:
            hits_dwell += 1
    print("\n  Monte Carlo, %d exits (seed 5):" % N)
    print("    exit at a uniform phase of the pulse period (traction request, Pi finish/loss, 30 s cap): %.1f %% latch"
          % (100.0 * hits / N))
    print("    release-dwell exit, brake demand ending between the last peak and its VOK release      : %.1f %% latch"
          % (100.0 * hits_dwell / N))
    print("""
  Reading. Revision 7 conditions (c) on V_chg, the eFuse input, but the 0.248 ms hold that the rule relies on
  (calc/verify_ms_shdn_short.py S3) starts from a FED node. Between regen pulses VCHG-IN stays at or above 13.5 V for
  0.17-0.19 s after every VOK release (the BT4-LS-02 residual, calc7 section 5) while the node is already dumped, so
  pin 8 is LOW at the 50 us sample. No host test of 12.11 exits between pulses (the (c) tests inject pin 8 = EF_EN
  and a fed node held 0.25 ms). The probe trace of section 3 is the same defect.""")


# =============================================================================================================
# Section 3: ERR_MOD_SENSE (c) at the eFuse-blocking probe (literal reading)
# =============================================================================================================
def section3():
    hdr("Section 3: configuration check -> eFuse-blocking probe: is the probe's FC_CHARGE drop a (c) exit?")
    trace = [
        ("9.7a step 7 (comm. 7)", "FC_CHARGE H, EF_EN H, node fed", "pin 8 HIGH (positive control passes)"),
        ("comm. step 11", "FC_CHARGE L; (c) samples pin 8 HIGH at 50/150 us (node fed)", "no latch; drain; p33 L"),
        ("probe step 2", "pin 8 LOW 20 ms (cold)", "-"),
        ("probe step 3", "FC_CHARGE H with EF_EN L; V_chg >= 13.5 V on two settled reads", "last settled V_chg >= 13.5 V"),
        ("probe step 4", "pin 8 LOW on two reads (healthy eFuse blocks)", "probe PASS"),
        ("probe step 5", "FC_CHARGE L = a commanded feed drop; pin 8 read HIGH earlier in the check; V_chg >= 13.5 V",
         "(c) samples pin 8: LOW -> ERR_MOD_SENSE (c), probe VOID"),
    ]
    for a, b, c in trace:
        print("  %-24s %-86s %s" % (a, b, c))
    print("""
  Reading. 12.4 item 3 applies the exit hold check at 'every commanded exit [that] drops the feed (pin 30 or
  FC_CHARGE)'; the probe's step-5 FC_CHARGE drop satisfies every written arming term (pin 8 HIGH earlier in the same
  configuration check, V_chg >= 13.5 V confirmed by probe step 3). Under that reading every healthy probe voids
  itself and every regen window of the power cycle is refused. Whether the probe is outside 'this window' is not
  stated. Arming on 'EF_EN H and pin 8 HIGH on the last settled reading' removes both traces.""")


# =============================================================================================================
# Section 4: ERR_MOD_DUMP_ON sample time against the Ag105 start that Stage 2 requires (S0-6 / Table 8a)
# =============================================================================================================
def section4():
    hdr("Section 4: ERR_MOD_DUMP_ON (FC window, pin 32 HIGH) versus an Ag105 cold start inside Table 8a")
    print("  Sample: 10 ms after chargerHasPower() first true (EF_EN H AND V_chg >= 13.5 V on two settled iterations).")
    print("  Node (VCHG-IN_M) timeline from the VCHG-IN 13.5 V crossing t_c: UVLO crossed 0.05-0.09 ms earlier, eFuse")
    print("  turn-on 1.24 ms, output slew <= 5.79 V/ms (a slower dV/dt only moves node-up later).\n")
    print("  loop ms  gap  uvlo_r  CHP true (ms after t_c)  node>=9 V at  sample at  sample - node-up (ms)")
    lo, hi = 1e9, -1e9
    for L in LOOPS:
        for gap in (False, True):
            for ur in UVLO_R:
                t_u = -(13.5 - ur) / RAMP_VCHG
                t_node9 = t_u + T_EF_ON + 9.15 / SLEW
                chp_lo, chp_hi = L, 2 * L                       # two reads >= 13.5 V after the crossing
                s_lo = chp_lo + 0.010
                s_hi = chp_hi + 0.010 + (GAP if gap else 0.0)
                d_lo, d_hi = s_lo - t_node9, s_hi - t_node9
                lo, hi = min(lo, d_lo), max(hi, d_hi)
                print("  %6.3f  %3s  %6.2f  %10.2f-%5.2f          %8.2f   %5.2f-%5.2f   %6.2f-%5.2f"
                      % (L * 1e3, "yes" if gap else "no", ur, chp_lo * 1e3, chp_hi * 1e3, t_node9 * 1e3,
                         s_lo * 1e3, s_hi * 1e3, d_lo * 1e3, d_hi * 1e3))
    print("\n  -> the dump check samples %.1f-%.1f ms after the module node passes 9 V." % (lo * 1e3, hi * 1e3))
    # Stage-2 start allowance after node-up: Table 8a allowance (eFuse enable -> charge current) minus the eFuse
    # delay + ramp of 4.4-5.6 ms (design 7.8)
    print("\n  Table 8a allowance for the Ag105 start after the eFuse ramp (allowance - 4.4..5.6 ms), t_D_ON 8 ms:")
    for pulse, (a1, a2) in (("19 ms", (6.4, 5.3)), ("47 ms", (29.3, 26.4))):
        s_lo, s_hi = a2 - 5.6, a1 - 4.4
        print("    %s pulse: Ag105 start to current must be <= %.1f-%.1f ms after node-up" % (pulse, s_lo, s_hi))
    for p in (13.0, 14.8):
        for vb in (15.9, 17.5):
            print("  FC-profile input at the sample if started: %.1f W / %.1f V = %.2f A at VCHG-IN (> 0.4 A threshold)"
                  % (p, vb, p / vb))
    print("""
  Reading. calc7 section 4 takes 'a healthy node draws about 23 mA' from the 65-170 ms prior cold start. Stage 2 is
  built only after S0-6 shows a start inside Table 8a (design 14.3): <= 0-2 ms after node-up for the 19 ms family and
  <= 21-25 ms for the 47 ms family. Any start faster than about 7-10 ms (the whole 19 ms GO band and the lower third
  of the 47 ms band) puts the FC-profile input current (0.74-0.93 A, Table 8) into the 10 ms sample of every FC window
  (pin 32 HIGH, D-BT-SQ on, the module converts): ERR_MOD_DUMP_ON latches on a healthy board, ends the FC window and
  refuses every window, regen included, for the power cycle. In configuration checks and commissioning pin 32 is LOW
  (output only through R_KA, ~14 mA), so the check there is valid at any start time. The host test of 12.11 ('a 23 mA
  step ... does not latch') encodes the slow-start premise.""")


# =============================================================================================================
# Section 5: Finish inside a regen window -> Idle-entry self-test start vs the unfinished commanded exit
# =============================================================================================================
def section5():
    hdr("Section 5: Finish (State 3) inside a regen window: Idle-entry self-test step 1 vs the running exit")
    L = 1.131e-3
    ev = [
        (0.0, "doState3(): 9.8 starts the regen exit: pin 30 L (feed drop), exit hold check"),
        (1 * L, "drain wait read 1 (deferred SD/I2C iteration)"),
        (2 * L, "Idle entry (State 3 -> 1 within two iterations, Appendix E BT4-LS-01 verifier); drain read 2"),
        (2 * L + 0.0001, "self-test step 1 if CHG_SELFTEST starts on the Idle-entry event: expects FF1.Q L, SG bits H, "
                         "pin 8 L"),
        (3 * L, "exit step 3: pin 33 L (only now); bonded confirmation needs 2 settled iterations more"),
        (5 * L, "bonded settled reading"),
        (0.023, "pin 5 L after 20 ms cold; CHG_EXITING -> CHG_BONDED"),
    ]
    for t, e in ev:
        print("  t = %6.2f ms  %s" % (t * 1e3, e))
    print("""
  Reading. 9.3 runs the self-test 'at each Idle entry'; 9.8 runs the exit 'if a window stands'; 12.4 lists the mode
  manager states but no transition into CHG_SELFTEST, and the self-test abort list (State-2 request, fault, window
  request) does not include 'exit in progress'. If CHG_SELFTEST starts on the Idle-entry event, step 1 reads FF1.Q H
  (pin 33 still H) and fails: a reboot-only ERR_CHG_SELFTEST on a healthy board. The rule 'CHG_SELFTEST is entered
  only from CHG_BONDED, after CHG_EXITING has completed' is needed. The revision-7 host test 'Finish at the peak'
  would expose it at implementation if it is run with a window open.""")


# =============================================================================================================
# Section 6: (d) every exit removes the charger input before the bond; revision-7 exit list
# =============================================================================================================
def section6():
    hdr("Section 6: invariant (d) on every exit path, revision 7")
    rows = [
        ("regen exit 9.5", "p30 L -> (c) check -> p8 LOW x2 (deadline max(10 ms, 4 it) <= 30 ms) -> p33 L -> confirm -> p5 L",
         "feed off, node cold, then bond"),
        ("FC exit 9.7", "FC_CHARGE L -> (c) -> p8 LOW x2 -> p33 L -> confirm -> BT_BUS -> p10/p5 L", "same"),
        ("UVLO-dip FC exit 9.7", "eFuse already off with EF_EN H (Q_MD OFF) -> FC_CHARGE L -> Q_MD ON -> drain", "same"),
        ("probe 9.7a", "p33 L throughout; FC_CHARGE H <= 100 ms with EF_EN L", "bonded, input blocked by eFuse"),
        ("commissioning 9.2-11", "FC_CHARGE L -> p8 LOW -> p33 L -> FF1 L -> pump stop -> p32 H", "same"),
        ("State 99 9.9", "FC_CHARGE L, REGEN L -> p8 LOW x2 or deadline -> p33 L -> p32 L", "same (deadline: F49 class)"),
        ("ERR_CHG_LADDER, code != 0", "commanded exit -> bonded confirmation -> p32 L", "same"),
        ("ERR_CHG_LADDER, code 0", "p32 L at once; LB rail dead: eFuse off on R_SDP, bonded on R_PA, Q_MD OFF",
         "F10 class, node on R_MB"),
        ("hardware trip 9.10", "FF1 clear -> eFuse off <= 76 us -> bond ~0.3 ms; module <= 1.1 ms", "F10 by design"),
        ("ERR_MOD_DUMP_ON exit", "commanded exit with Q_MD stuck ON (node already near 0)", "same"),
    ]
    for a, b, c in rows:
        print("  %-26s %-98s %s" % (a, b, c))
    print("""
  Reading. (d) holds on every commanded path: the feed write precedes the drain wait and the pin-33 LOW. The exits that
  bond with a hot node are the deadline expiries (ERR_MOD_DRAIN, F49/F56) and the dead-rail code-0 path (Q_MD
  unpowered), both bounded by C_mod (<= 51 mJ) as in round 4. One spec conflict, harmless: State 99 phase 2 writes
  MPPT LOW, but the pin-5 chokepoint (12.4 item 7) refuses a pin-5 change until pin 8 has read LOW for 20 ms; phase 2
  can run ~11 ms after phase 0, so the write is refused and pin 5 stays released on an unpowered module.""")


if __name__ == "__main__":
    section1()
    section2()
    section3()
    section4()
    section5()
    section6()
