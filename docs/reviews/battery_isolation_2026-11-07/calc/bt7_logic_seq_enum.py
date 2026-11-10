"""Battle-test round 7, LOGIC / SEQUENCING lens: model check of IC1 revision 10 (FC windows between purges).

Target: detailed_design_IC1.md revision 10: section 0.10 (Table 0g, R10-1..R10-7), 9.7, 9.7a, 9.7b, 9.9, 9.11.1-9.11.7,
12.4 items 6-7, Appendix H; calc/ic1_rev10_calcs.py (calc10).  Extends calc/bt6_logic_seq_enum.py (which reuses the
bt5/bt4 hardware network hw5()) with the revision-10 rules:
  R10-1 PI-4 latch (UNKNOWN / purge_active / late prediction inside a session that holds BT_BUS open -> State 99);
        busHotPlugUnsafe() refusal at exit step 4 -> latch;
  R10-2 SC-1 reading (b) armed from a prediction exit's BT_BUS write to the declared purge end;
  R10-3 no share override in P and D-s; T_lead,min 80 ms, T_late 61 ms;
  R10-4 SC-8 ownership of pins 27/28 from the pin-10 write to BT_BUS HIGH for 31.8 ms (to the purge end after a
        prediction exit); FC_BUS re-test before entry step 5; F1 disarm at D-s entry (once per stop); in-band
        substitution of an EMS rail command while a D-s request stands;
  R10-5 V_batt >= 7.4 V entry condition;  R10-6 traction released after BT_BUS HIGH for 31.8 ms.
Re-proves (a) no charger powered with the pack bonded, (b) never BT_BUS effective while in charge mode,
(c) safe defaults, (d) feed removed before the bond on every exit incl. the collapse teardown, (e) no re-close onto a
collapsed node on FC recovery, (f) no healthy-board latch across a predicted purge train; adds (g) reachability of
the adopted variants P and D-s over a power cycle.

Stdlib only.  Run:
  .venv_hil/Scripts/python.exe docs/reviews/battery_isolation_2026-11-07/calc/bt7_logic_seq_enum.py
      > docs/reviews/battery_isolation_2026-11-07/calc/bt7_logic_seq_enum_output.txt

Numeric inputs (all cited; none new):
  loop median 1.131 ms, p99 1.341 ms, one 9.76 ms gap                                  facts_firmware s8; calc10 s1
  D-BT-EN conduction after the write onto a live bus: t_D_ON + 19.77 ms; t_D_ON 8/12 ms  design Table 20; calc10 s1
  T_lead,min 80 ms, T_late 61 ms, admission horizon 1.282 s, traction hold 31.8 ms       design 9.11.2; calc10 s1, s3
  SHARE_CUT_SURVIVOR_BLANK_MS 30 ms; SHARE_CUT_MAX_HANDOFF_A 0.5 A                      ino:4869; ino:3218
  V_BUS_CHARGED_THRESH 13.5 V; busHotPlugUnsafe(reg) = reg HIGH && V_bus < 13.5 V        ino:2317; ino:13043-13045
  module node drain 0.83-2.01 ms; T_drain,max max(10 ms, 4 it) capped 30 ms              design Table 21; 12.4 item 3
  VCHG-IN bleed tau 0.984 s (15.95 V -> 11 V in 365.6 ms)                                design 9.11.4; calc10 s2
  purge period 10.34 s, duration 100-140 ms +/-20 ms, floor ~1 V                         facts_prior s7
  Ag105 cold start 65-170 ms (entry chain 83.5 / 201.8 ms)                               design 9.11.4
  fw v37 rev 2 share latch / selector / state code: ino:7826-7917 (doState1), ino:7919-7959 (doState2, FC_BUS
  re-assert gated on !shareSpCutFC at ino:7929), ino:7961-8018 (doState3: selector flags cleared, bus switches and
  shareSpCut*/shareIso* untouched, comment ino:7989), ino:13396-13438 (self-heal and guarded release), ino:13521-13552
  (setpoint-latch FC cut sets shareSpCutFC), ino:15102-15115 (armShareBatteryOnlyStart at Idle->Run).
"""
import itertools
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt5_logic_seq_enum as bt5   # noqa: E402  (main-guarded)
import bt6_logic_seq_enum as bt6   # noqa: E402  (main-guarded)

LOOPS = (1.131, 1.341)            # ms
GAP = 9.76                        # ms
T_SS = 19.77                      # ms
T_LEAD_MIN, T_LATE, HORIZON = 80.0, 61.0, 1282.0
HOLD_COND = 31.8                  # ms
BLANK = 30.0
TAU_VCHG = 984.0
PERIOD = 10340.0


def hdr(t):
    print("\n" + "=" * 112 + "\n" + t + "\n" + "=" * 112)


# =============================================================================================================
# Section 1: revision-10 sequences through the hardware network (a, b, b', d)
# =============================================================================================================
W = dict(p33="H", p28="L", p31="H", p29="H", p30="L", p32="H")     # FC window open


def v(**k):
    d = dict(W)
    d.update(k)
    return d


SEQ = {
    "R10 prediction exit 9.11.3 steps 1-4": [
        ("window", v(), True), ("1 feed drop", v(p31="L"), True), ("2 drain", v(p31="L"), True),
        ("3 bond", v(p31="L", p33="L"), False), ("4 BT_BUS HIGH", v(p31="L", p33="L", p28="H"), False)],
    "R10-1 PI-4 latch in CHG_FC -> State 99 (Table 23)": [
        ("window", v(), True), ("ph0 feed LOW, 27/28 LOW", v(p31="L"), True),
        ("bond", v(p31="L", p33="L"), False), ("p32 LOW", v(p31="L", p33="L", p32="L"), False),
        ("MOT LOW", v(p31="L", p33="L", p32="L", p29="L"), False)],
    "R10-1 PI-4 latch during a non-prediction exit, after the feed drop": [
        ("exit step 2 (drain)", v(p31="L"), True), ("ph0 27/28 LOW", v(p31="L"), True),
        ("bond", v(p31="L", p33="L"), False), ("p32 LOW", v(p31="L", p33="L", p32="L"), False)],
    "R10-1 guard refusal at exit step 4 -> latch": [
        ("exit step 3 bonded", v(p31="L", p33="L"), False), ("step 4 refused (p28 L)", v(p31="L", p33="L"), False),
        ("latch ph0", v(p31="L", p33="L"), False), ("p32 LOW", v(p31="L", p33="L", p32="L"), False)],
    "R10-4 D-s entry 1-6 after FC_BUS re-test": [
        ("bonded, BT_BUS HIGH", v(p31="L", p33="L", p28="H"), False), ("3 pin 33 HIGH", v(p31="L", p28="H"), True),
        ("5 BT_BUS LOW", v(p31="L"), True), ("6 FC_CHARGE HIGH", v(), True)],
    "R10-6 D-s traction exit with hold": [
        ("window", v(), True), ("1 feed drop, VESC 0 A", v(p31="L"), True),
        ("3 bond", v(p31="L", p33="L"), False), ("4 BT_BUS HIGH, hold", v(p31="L", p33="L", p28="H"), False),
        ("release after 31.8 ms", v(p31="L", p33="L", p28="H"), False)],
    "9.7b dump check with a prediction exit": [
        ("1 p32 LOW, p10", v(p31="L", p33="L", p28="H", p32="L"), False),
        ("2 p33 HIGH", v(p31="L", p28="H", p32="L"), True), ("3 BT_BUS LOW", v(p31="L", p32="L"), True),
        ("4 FC_CHARGE HIGH", v(p32="L"), True), ("exit 1 feed drop", v(p31="L", p32="L"), True),
        ("exit 3 bond", v(p31="L", p33="L", p32="L"), False), ("exit 4 BT_BUS", v(p31="L", p33="L", p28="H", p32="L"),
                                                              False)],
}


def section1():
    hdr("Section 1: revision-10 sequences through the hardware network (bt5.hw5): (a), (b), (b'), (d)")
    envkeys = ["v5", "bus", "vmot_above", "uc1", "clr", "resid", "node_resid"]
    for name, steps in SEQ.items():
        cnt = dict(a=0, b=0, bp=0, bp_exit=0, d=0, n=0)
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
                bten = g["p28"] == "H" and g["p31"] != "H"
                cnt["a"] += s["a"]
                cnt["b"] += s["b"]
                cnt["bp"] += bten and s["ff1"]
                cnt["bp_exit"] += bten and s["ff1"] and ("exit" in lab or "latch" in lab or "ph0" in lab)
                cnt["d"] += s["sgnd"] and s["efuse"] and not env["resid"]
        print("  %-62s steps %d, states %4d: (a) %d (b) %d (b') %d [in an exit/teardown %d] (d) %d"
              % (name, len(steps), cnt["n"], cnt["a"], cnt["b"], cnt["bp"], cnt["bp_exit"], cnt["d"]))
    print("""
  Reading. Revision 10 adds no hardware: on every revision-10 sequence (a), (b) and (d) are 0, and the only (b')
  states are entry steps 3-5 (pin 33 HIGH, BT_BUS still HIGH, FC_CHARGE LOW; board load through the sense in
  reverse, section 9.3 accepted, U_C1 bound). No exit or teardown step has BT_BUS HIGH with FF1 set.""")


# =============================================================================================================
# Section 2: timed model of the revision-10 mode manager over a predicted purge (P and D-s) - invariants a-f
# =============================================================================================================
class Sim:
    """One iteration-level trace.  Time in ms.  The window request stands from t = 0 at standstill; the next onset
    is at T_ON (ideal predictor: purge_tto = T_ON - t exactly; it announces at T_lead,min).  Injected events:
      inj = None | 'withdraw' | 'genstat' | 'traction' | 'state12' (P only)  at T_ON + inj_dt.
    interp: True = a timely prediction observed during a non-prediction exit relabels it a prediction exit
    (ownership and reading (b) to the purge end); False = the text read literally (only a prediction-started exit)."""

    def __init__(s, var, loop, gap_at, tdon, dur, inj, inj_dt, cmd, pre_cut, interp, bt_reg=True, t_on=1400.0):
        s.var, s.loop, s.gap_at, s.tdon, s.dur = var, loop, gap_at, tdon, dur
        s.inj, s.inj_t, s.cmd, s.interp, s.bt_reg = inj, (t_on + inj_dt if inj else None), cmd, interp, bt_reg
        s.T_ON = t_on
        s.ms = 2 if var == "Ds" else 1
        s.p = dict(p27=not pre_cut, p28=True, p31=False, p33=False, p10=False, p29=True)
        s.fc_rise = -1e9
        s.bt_write = -1e9          # BT_BUS HIGH since boot: conducting
        s.spcut = pre_cut          # shareSpCutFC (setpoint latch, battery-only selector)
        s.armed = pre_cut
        s.inhibit = False
        s.disarm_used = False
        s.req = True
        s.genstat_end = False
        s.moving = False
        s.vset = 0.0
        s.chg = "BONDED"
        s.k = 0                    # step counter inside a chg state
        s.t_step = 0.0
        s.exit_kind = None
        s.feed_drop = -1e9
        s.vchg_fed = False
        s.chp = 0                  # chargerHasPower settled count
        s.pin8_low_since = -1e9
        s.own_until = -1e9         # SC-8 ownership end (absolute ms) once the exit write is known
        s.owning = False
        s.b_armed_until = -1e9     # reading (b) extension after a prediction exit
        s.latched = None
        s.ev = {}
        s.hold_release = None
        s.obs_tto = None
        s.refused_cuts = 0
        s.substituted = 0
        s.srcless = 0.0
        s.srcless_first = None
        s.windows = 0
        s.viol = []

    # --- physics ---------------------------------------------------------------------------------------------
    def fc_ok(s, t):
        return not (s.T_ON <= t < s.T_ON + s.dur)

    def bt_cond(s, t):
        return s.p["p28"] and s.bt_reg and t >= s.bt_write + s.tdon + T_SS

    def fc_eff(s, t):
        return s.p["p27"] and s.fc_ok(t)

    def bus_live(s, t):
        return s.fc_eff(t) or s.bt_cond(t)

    def vchg(s, t):
        if s.p["p31"] and s.bus_live(t):
            return 15.95
        return 15.95 * math.exp(-max(0.0, t - s.feed_drop) / TAU_VCHG) if s.feed_drop > 0 else 0.5

    def pin8_hot(s, t):
        return s.p["p31"] or (t - s.feed_drop) < 2.01

    # --- predictor (ideal) -----------------------------------------------------------------------------------
    def tto(s, t):
        n = s.T_ON if t < s.T_ON + s.dur else s.T_ON + PERIOD
        return n - t

    def active(s, t):
        return s.T_ON <= t < s.T_ON + s.dur

    def purge_end(s):
        return s.T_ON + s.dur

    # --- share loop / selector (State 2 only, D-s) -------------------------------------------------------------
    def cmd_seen(s, t):
        rail = s.cmd <= 0.15 or s.cmd >= 0.85
        sub_window = s.req and not s.moving and s.vset == 0.0
        in_session = s.chg != "BONDED" or s.owning
        if rail and (sub_window or in_session) and s.ms == 2:
            s.substituted += 1
            return 0.1501 if s.cmd < 0.5 else 0.8499
        return s.cmd

    def share_tick(s, t):
        if s.mainstate() != 2:
            return
        c = s.cmd_seen(t)
        rail = c <= 0.15 or c >= 0.85
        total_low = not s.moving and not s.p["p31"]
        if not rail and s.inhibit:
            s.inhibit = False
        if not s.armed and not s.inhibit and not s.p["p31"] and total_low and rail:
            s.armed = True                                 # re-entry rule; fcUvLockoutActive -> battery-only
        if s.moving and s.armed and t > s.inj_t + 300:   # gate release after the launch total crosses 0.25 A
            s.armed = False
        sp = 0.0 if s.armed else c
        if s.spcut and sp >= 0.15:
            if s.owned(t):
                s.refused_cuts += 1
            elif s.bus_live(t) and s.bt_reg:
                s.p["p27"] = True
                s.fc_rise = t
                s.spcut = False
        elif not s.spcut and sp < 0.15 and s.p["p27"] and s.p["p28"] and s.bt_reg:
            blanked = t - s.bt_write < BLANK
            if s.owned(t):
                s.refused_cuts += 1
            elif not blanked:
                s.p["p27"] = False
                s.spcut = True
                s.ev.setdefault("latch_cut_t", t)

    def mainstate(s):
        return s.ms

    def owned(s, t):
        return s.owning

    # --- one iteration ---------------------------------------------------------------------------------------
    def latch(s, t, why):
        if s.latched is None:
            s.latched = (t, why)
            s.p["p31"] = False
            s.p["p27"] = False
            s.p["p28"] = False
            if s.vchg_fed and s.chg in ("FC", "ENTER"):
                s.feed_drop = t

    def step(s, t):
        if s.latched is not None:
            # State 99 phase 0/1/2 (Table 23): bond after pin 8 LOW twice or deadline; MOT_PWR at +10 ms
            if s.p["p33"] and (not s.pin8_hot(t) or t - s.latched[0] >= 10.0):
                s.p["p33"] = False
            if t - s.latched[0] >= 10.0:
                s.p["p29"] = False
            return
        # injected events
        if s.inj_t is not None and t >= s.inj_t and "inj_done" not in s.ev:
            s.ev["inj_done"] = t
            if s.inj == "withdraw":
                s.req = False
            elif s.inj == "genstat":
                s.genstat_end = True
            elif s.inj == "traction":
                s.vset = 0.5
            elif s.inj == "state12":
                s.ms = 2
                s.armed = True                             # armShareBatteryOnlyStart (ino:15102)
        tto = s.tto(t)
        session_bt_open = s.chg in ("FC",) or (s.chg == "ENTER" and s.k >= 5) or (s.chg == "EXIT" and s.k < 4)
        # SC-1 (a)/(b) and the R10-2 extension
        vbus_low = not s.bus_live(t) and (s.p["p31"] or s.srcless >= 16.9)
        if (session_bt_open or t <= s.b_armed_until) and vbus_low:
            return s.latch(t, "SC-1 (b)")
        if session_bt_open and s.vchg_fed and s.vchg(t) < 13.0:
            return s.latch(t, "SC-1 (a)")
        # PI-4 (ideal predictor: no UNKNOWN; purge_active rising or late prediction)
        if session_bt_open and (s.active(t) or (tto <= T_LEAD_MIN and s.obs_tto is None and tto < T_LATE)):
            return s.latch(t, "PI-4")
        pred = tto <= T_LEAD_MIN and not s.active(t)
        if pred and s.obs_tto is None:
            s.obs_tto = tto
            s.ev["obs"] = t
        # ---- chg state machine --------------------------------------------------------------------------
        if s.chg == "FC":
            reason = None
            if pred:
                reason = "pred"
            elif not s.req:
                reason = "withdraw"
            elif s.genstat_end:
                reason = "genstat"
            elif s.vset != 0.0 or (s.ms == 2 and s.var == "P" and s.inj == "state12"):
                reason = "traction"
            if reason:
                s.chg, s.k, s.exit_kind = "EXIT", 1, reason
                s.p["p31"] = False
                s.feed_drop = t
                s.t_step = t
                s.ev.setdefault("exit_" + reason, t)
            return s.after(t)
        if s.chg == "EXIT":
            if pred and s.interp and s.exit_kind != "pred":
                s.exit_kind = "pred"
            if s.k == 1:                                      # drain: pin 8 LOW twice (deadline)
                s.k8 = getattr(s, "k8", 0) + (0 if s.pin8_hot(t) else 1)
                if s.k8 >= 2 or t - s.t_step >= min(30.0, max(10.0, 4 * s.loop)):
                    s.p["p33"] = False
                    s.k, s.t_step, s.k8 = 2, t, 0
            elif s.k == 2:                                    # bonded confirmation (2 iterations)
                s.kc = getattr(s, "kc", 0) + 1
                if s.kc >= 2:
                    s.k, s.kc = 3, 0
            elif s.k == 3:                                    # step 4: guarded BT_BUS re-close
                vb = 15.9 if s.bus_live(t) else 10.0
                if s.bt_reg and vb < 13.5:
                    return s.latch(t, "R10-1 guard refusal")
                s.p["p28"] = True
                s.bt_write = t
                s.ev.setdefault("bt_write", t)
                s.k = 4
                s.own_until = t + HOLD_COND
                if s.exit_kind == "pred":
                    s.b_armed_until = s.purge_end() + 2 * s.loop
                    s.own_until = max(s.own_until, s.purge_end() + 2 * s.loop)
            elif s.k == 4:
                if t >= s.own_until:
                    s.owning = False
                    s.chg = "BONDED"
                    s.p["p10"] = False
                if s.vset != 0.0 and s.hold_release is None and t >= s.bt_write + HOLD_COND:
                    s.hold_release = t
            return s.after(t)
        if s.chg == "BONDED":
            if s.vset != 0.0 and s.hold_release is None and s.ev.get("bt_write") and t >= s.bt_write + HOLD_COND:
                s.hold_release = t
            if s.vset != 0.0 and not s.moving and s.hold_release is not None:
                s.moving = True
            # entry gates (section 9.7; 9.11.4)
            if not s.req or s.genstat_end or s.vset != 0.0:
                return s.after(t)
            if s.var == "P" and s.ms == 2:
                return s.after(t)                            # P left Idle; D-s not modelled from this trace
            if tto < HORIZON or s.active(t) or not s.fc_ok(t - 2 * s.loop):
                return s.after(t)
            if s.vchg(t) >= 11.0 or (t - s.feed_drop) < 2.01 + 20.0:
                return s.after(t)
            if s.ms == 2 and not s.p["p27"] and not s.disarm_used:   # D-s F1 disarm, once per stop
                s.armed, s.inhibit, s.disarm_used = False, True, True
                s.ev.setdefault("f1_disarm", t)
                return s.after(t)
            if not s.p["p27"] or t - s.fc_rise < BLANK:
                s.ev.setdefault("wait_f1", t)
                if t - s.ev["wait_f1"] > 100.0:
                    s.ev.setdefault("refused_code11", t)       # F1 gate still failing 100 ms later
                return s.after(t)
            s.ev.pop("wait_f1", None)
            s.chg, s.k, s.t_step = "ENTER", 1, t
            s.vchg_fed = False                              # reading (a) is per session (design 9.11.5 (i))
            s.p["p10"] = True
            s.owning = True
            return s.after(t)
        if s.chg == "ENTER":
            if s.k == 1:
                s.k = 2
            elif s.k == 2:
                s.p["p33"] = True
                s.k, s.kc = 3, 0
            elif s.k == 3:
                s.kc += 1
                if s.kc >= 2:
                    s.k = 4
            elif s.k == 4:
                s.k = 5
                # step 5 re-test: FC_BUS HIGH, unblanked, no cut flag
                if not s.p["p27"] or t - s.fc_rise < BLANK or s.spcut:
                    s.ev.setdefault("entry_refused_step5", t)
                    s.chg, s.k, s.exit_kind = "EXIT", 1, "refuse"
                    return s.after(t)
                s.p["p28"] = False
            elif s.k == 5:
                s.p["p31"] = True
                s.vchg_fed = True
                s.chg = "FC"
                s.windows += 1
                s.ev.setdefault("fc_on", []).append(t)
                s.obs_tto = None if s.tto(t) > T_LEAD_MIN else s.obs_tto
            return s.after(t)

    def after(s, t):
        # doState2: FC_BUS re-assert gated on !shareSpCutFC (ino:7929), refused under SC-8 ownership (no-op here)
        if s.mainstate() == 2:
            s.share_tick(t)
        return None

    def run(s, t_end):
        t = 0.0
        gap_used = False
        while t < t_end:
            s.step(t)
            # invariants
            bl = s.bus_live(t)
            if s.latched is None and not bl:
                s.srcless += s.loop
                if s.srcless_first is None:
                    s.srcless_first = t
            else:
                s.srcless = 0.0
            if not s.p["p33"] and s.p["p31"]:
                s.viol.append(("(a)/(d) bond with feed", t))
            if s.p["p28"] and s.p["p31"]:
                s.viol.append(("(b) BT_BUS pin HIGH with FC_CHARGE HIGH", t))
            if s.p["p28"] and s.p["p33"] and not s.p["p31"] and s.chg == "EXIT":
                s.viol.append(("(b') BT_BUS HIGH in charge mode inside an exit", t))
            if s.hold_release is not None and "launch_check" not in s.ev:
                s.ev["launch_check"] = s.bt_cond(t)
            # (e): FC recovery
            if abs(t - (s.T_ON + s.dur)) < s.loop / 2 + 1e-9 and "rec" not in s.ev:
                s.ev["rec"] = (s.p["p27"], bl or s.bt_cond(t))
            # step
            dt = s.loop
            if not gap_used:
                if s.gap_at == "drop" and s.tto(t + s.loop) <= T_LEAD_MIN + 0.0 and s.tto(t) > T_LEAD_MIN and \
                        s.chg == "FC":
                    dt, gap_used = GAP, True
                elif s.gap_at == "drain" and s.chg == "EXIT" and s.k == 1:
                    dt, gap_used = GAP, True
                elif s.gap_at == "confirm" and s.chg == "EXIT" and s.k == 2:
                    dt, gap_used = GAP, True
            t += dt
        return s


def section2():
    hdr("Section 2: timed model of the revision-10 mode manager over one predicted purge (ideal predictor)")
    grid = itertools.product(("P", "Ds"), LOOPS, (None, "drop", "drain", "confirm"), (8.0, 12.0), (80.0, 160.0),
                             (None, "withdraw", "genstat", "traction", "state12"),
                             (-150.0, -100.0, -79.0, -30.0, 0.0, 40.0, 120.0, 450.0),
                             (0.16, 0.15, 0.85), (False, True), (True, False))
    tally = dict(n=0, latch=0, srcless=0, viol=0, e_bad=0, bt_after_onset=0, launch_on_fc=0, code11=0, step5=0,
                 refused=0, windows_after=0, reentry_missing=0)
    examples = {}
    c11 = {}
    for var, loop, gap_at, tdon, dur, inj, idt, cmd, pre_cut, interp in grid:
        if gap_at in ("drain", "confirm") and loop != LOOPS[1]:
            continue
        if inj is None and idt != -150.0:
            continue
        if var == "P" and (cmd != 0.16 or pre_cut):
            continue
        if var == "Ds" and inj == "state12":
            continue
        s = Sim(var, loop, gap_at, tdon, dur, inj, idt, cmd, pre_cut, interp).run(1400.0 + 1100.0)
        tally["n"] += 1
        key = None
        if s.latched is not None:
            tally["latch"] += 1
            key = "latch:" + s.latched[1]
        if s.srcless_first is not None:
            tally["srcless"] += 1
            key = key or "srcless"
        if s.viol:
            tally["viol"] += 1
            key = key or ("viol:" + s.viol[0][0])
        rec = s.ev.get("rec")
        if rec and rec[0] and not rec[1]:
            tally["e_bad"] += 1
            key = key or "e"
        if s.ev.get("bt_write") and s.T_ON <= s.ev["bt_write"] < s.T_ON + s.dur and s.exit_kind == "pred":
            tally["bt_after_onset"] += 1
        if "launch_check" in s.ev and not s.ev["launch_check"]:
            tally["launch_on_fc"] += 1
            key = key or "launch_on_fc"
        if "refused_code11" in s.ev:
            tally["code11"] += 1
            k11 = (var, inj if inj in (None, "withdraw", "genstat") else inj, cmd, pre_cut, interp)
            c11[k11[:2] + (k11[2] if inj not in ("traction", "state12") else "-",)] =                 c11.get(k11[:2] + (k11[2] if inj not in ("traction", "state12") else "-",), 0) + 1
        if "entry_refused_step5" in s.ev:
            tally["step5"] += 1
        tally["refused"] += s.refused_cuts > 0
        if s.req and not s.genstat_end and s.vset == 0.0 and (s.var == "Ds" or s.ms == 1) and s.latched is None:
            fc_on = [x for x in s.ev.get("fc_on", []) if x > s.T_ON]
            if fc_on:
                tally["windows_after"] += 1
            else:
                tally["reentry_missing"] += 1
                key = key or "no re-entry"
        if key and key not in examples:
            examples[key] = (var, loop, gap_at, tdon, dur, inj, idt, cmd, pre_cut, interp, s.latched, s.srcless_first,
                             s.viol[:1], s.ev.get("bt_write"), s.ev.get("obs"), s.ev.get("f1_disarm"), s.exit_kind)
    print("  %d traces (P: State 1; Ds: State 2 at standstill; 2 loops x 4 gap placements x t_D_ON 8/12 x purge 80/160"
          " ms x exit injections x 8 offsets x EMS share 0.16/0.15/0.85 x selector cut before the stop x"
          " relabel reading)" % tally["n"])
    for k in ("latch", "srcless", "viol", "e_bad", "bt_after_onset", "launch_on_fc", "code11", "step5", "refused",
              "windows_after", "reentry_missing"):
        print("    %-16s %d" % (k, tally[k]))
    print("  code-11 refusals by (variant, injection, EMS share):", dict(sorted(c11.items(), key=str)))
    for k, e in examples.items():
        print("  example [%s]: var %s loop %.3f gap %s t_D_ON %.0f dur %.0f inj %s @onset%+.0f ms cmd %.2f pre_cut %s"
              " relabel %s -> latch %s, source-less from %s, viol %s, BT write %s, prediction observed %s, F1 disarm"
              " %s, exit kind %s" % ((k,) + e))
    print("""
  Reading. Counts are of traces, onset at t = 1400 ms. 'latch' on a healthy trace is an (f) violation; 'srcless' is
  any iteration outside State 99 with neither source pair conducting; 'e_bad' is FC_BUS HIGH at the FC recovery with
  no live bus (Death-5 / H-R); 'bt_after_onset' a prediction exit whose BT_BUS write falls in the purge; 'launch_on_fc'
  a traction release before D-BT-EN conducts; 'code11' an entry still refused on the F1 conduction gate 100 ms after the gates (the 30 ms blanking wait after
  the F1 disarm is not counted); 'refused' a
  share-latch write refused by SC-8; 'reentry_missing' a trace whose request still stood with no window after the
  purge (an availability loss, not a safety one).""")


# =============================================================================================================
# Section 3: reachability of P and D-s over a power cycle (mode-machine level, the fw v37 code that IC1 keeps)
# =============================================================================================================
def section3():
    hdr("Section 3: reachability of the adopted variants over a power cycle (code paths kept by IC1)")
    # Facts used (design and firmware):
    F = {
        "dump_check_needed": "9.7b: a dump-check pass in this power cycle precedes every FC window (R8-2); D-s needs it"
                             " earlier in the power cycle, else code 12 (design 1818-1819, Table 25)",
        "dump_check_states": "12.4 item 7: CHG_CONFIG (configuration check, dump check, probe) refused unless mainState"
                             " is 1 or 98 with the motor command 0",
        "dump_check_trigger": "9.7b: run 'before the first FC window of a power cycle without a configuration check';"
                              " 9.7a: the configuration check runs before the first REGEN window (none in Stage 1,"
                              " REGEN HIGH refused when IC1_STAGE 1, 12.4 item 7)",
        "permit": "PI-4: purge_tto UNKNOWN before the first purge after an H-20 start refuses every FC-fed session",
        "finish": "doState3 (ino:7961-8018): bus switches left as they are (comment ino:7989), selector flags cleared"
                  " (ino:8010-8015), shareSpCutFC / shareIsoFC NOT cleared",
        "idle": "doState1 (ino:7826-7917): no bus-switch write; powerBalance() (the only latch release, ino:13421) is"
                " called in State 2 only (ino:7944-7950)",
        "run_assert": "doState2 re-asserts FC_BUS only if !shareSpCutFC (ino:7929)",
        "cut": "setpoint-latch FC cut sets shareSpCutFC (ino:13546-13552) whenever the battery-only selector is armed"
               " (Idle->Run arm ino:15102; re-entry rule on a rail command at <= 0.25 A, ino:14106-14125)",
        "P_gate": "9.7 entry: the existing F1 conduction gate (FC_BUS HIGH, unblanked) is an entry condition; the F1"
                  " disarm is specified for the D-s entry only (9.11.6); no State-1 writer of pin 27 exists",
    }
    for k, txt in F.items():
        print("  [%s] %s" % (k, txt))

    def power_cycle(seq):
        st = dict(ms=0, fc_bus=True, spcut=False, armed=False, dump_ok=False, tracked=False, log=[])
        for ev in seq:
            kind = ev[0]
            if kind == "boot":
                st.update(ms=1, fc_bus=True, spcut=False, armed=False, dump_ok=False, tracked=False)
            elif kind == "h20_tracked":
                st["tracked"] = True
            elif kind == "run":
                st["ms"] = 2
                st["armed"] = True                                   # ino:15102
                if not st["spcut"]:
                    st["fc_bus"] = True                              # ino:7929
            elif kind == "stop_rail":                                # standstill, rail command, total <= 0.25 A
                st["armed"] = True
            elif kind == "launch":                                   # gate release, latch release
                st["armed"] = False
                if st["spcut"]:
                    st["spcut"] = False
                    st["fc_bus"] = True
            elif kind == "finish":
                st["ms"] = 1
                st["armed"] = False                                  # ino:8010-8015; spcut/fc_bus untouched
            if st["ms"] == 2 and st["armed"] and st["fc_bus"]:
                st["fc_bus"] = False                                 # cut (ino:13546-13552)
                st["spcut"] = True
            if kind == "request":
                if st["ms"] == 2:
                    if not st["dump_ok"]:
                        st["log"].append("State 2 request -> refused code 12 (no dump check; CHG_CONFIG not allowed"
                                         " in State 2)")
                    else:
                        st["log"].append("State 2 request -> D-s window (F1 disarm if FC cut)")
                elif st["ms"] == 1:
                    if not st["tracked"]:
                        st["log"].append("State 1 request -> refused code 4 (UNKNOWN)")
                    elif not st["fc_bus"]:
                        st["log"].append("State 1 request -> refused code 11 (FC_BUS LOW, shareSpCutFC held from Run;"
                                         " no State-1 writer) - also blocks the dump check")
                    else:
                        if not st["dump_ok"]:
                            st["dump_ok"] = True
                            st["log"].append("State 1 request -> dump check passes, then P window")
                        else:
                            st["log"].append("State 1 request -> P window")
        return st["log"]

    cases = {
        "G1 recorded-session shape: boot, Run at once, request only at stops in Run": [
            ("boot",), ("h20_tracked",), ("run",), ("launch",), ("stop_rail",), ("request",), ("launch",),
            ("stop_rail",), ("request",)],
        "G2 operator parks with a request before driving (unstated procedure)": [
            ("boot",), ("h20_tracked",), ("request",), ("run",), ("launch",), ("stop_rail",), ("request",)],
        "G3 drive, final stop on a rail command, Finish, park with a request": [
            ("boot",), ("h20_tracked",), ("request",), ("run",), ("launch",), ("stop_rail",), ("finish",),
            ("request",), ("request",)],
        "G4 drive, final stop in band (launch-released), Finish, park": [
            ("boot",), ("h20_tracked",), ("run",), ("launch",), ("finish",), ("request",)],
        "G5 Run entered and finished at standstill (battery-only start never released), park": [
            ("boot",), ("h20_tracked",), ("run",), ("finish",), ("request",)],
    }
    for name, seq in cases.items():
        print("  %s" % name)
        for line in power_cycle(seq):
            print("      %s" % line)
    print("""
  Reading. (g1) D-s is reachable only after an FC-fed session in State 1 or 98 of the same power cycle (G1 vs G2):
  the dump check is triggered only before the first FC window and CHG_CONFIG is refused in State 2, so a power cycle
  whose first request arrives in Run refuses every D-s window with code 12 until the vehicle is parked with a request.
  The recorded sessions have that shape (first request at 66.0-72.4 s, after the launch at about 55.8 s; bt7 bag
  script). (g2) The fw v37 Finish keeps a share-latch FC cut into Idle (G3, G5): State 1 has no writer of pin 27 and
  no latch release, so every State-1 FC-fed session (P window, dump check, configuration check) is refused with code
  11 for the whole Idle; the F1 disarm that revision 10 adds is specified for the D-s entry only.""")


# =============================================================================================================
# Section 4: unpredicted onset - recognition after the calc10 grid (t_det 70 ms) and the boundary of 'OPEN'
# =============================================================================================================
def section4():
    hdr("Section 4: PI-4 latch with a recognition latency beyond the calc10 grid (reduced grid; calc10 s5 method)")
    import inspect
    import textwrap
    src = textwrap.dedent(inspect.getsource(bt6.run_u))
    old = """            if exit_state is None and t >= t_det:
                ev['t_exit'] = t
                exit_state = 'drain'
                en['FCCHG'] = False
                ef_en = False
                drain_t0 = t
                pin8_low_n = 0
                return True
            return False"""
    new = """            nonlocal latch_t
            if exit_state is None and t >= t_det:
                ev['latch_by'] = 'PI4'
                ev['t_latch'] = t
                latch_t = t
                exit_state = 'latched'
                return True
            return False"""
    assert old in src
    ns = dict(vars(bt6))
    exec(compile(src.replace(old, new).replace("def run_u(", "def run_l("), "run_l", "exec"), ns)
    run_l = ns["run_l"]
    tal = {}
    for (mode, p), aux, cv, tf, var, tdet in itertools.product((('CP', 14.8), ('MPPT', 14.8)), (0.015, 0.15),
                                                               (1.5e-3,), (0.060, 0.075), ('P', 'D'),
                                                               (0.070, 0.077, 0.079, 0.085, 1.0)):
        e = run_l(mode, p, 221e-6, aux, cv, tf, (12.10, 12.88), var, tdet, 'det-first', 1.341e-3)
        c = bt6.classify(e['snap'][0.080])
        tal.setdefault(tdet, {}).setdefault(c, 0)
        tal[tdet][c] += 1
    for k in sorted(tal):
        print("  t_det %s: t_rec 80 ms %s" % ("never" if k >= 1.0 else "%.0f ms" % (k * 1e3), tal[k]))
    print("""
  Reading. The PI-4 latch only adds a latch; it never adds a write. Recognition after about 78 ms reduces to the
  baseline E2 classes that Table 23 row 3 already accepts (FC_BUS HIGH at 80 ms only with the bus at 12.04 V or more,
  IN-FAMILY). The calc10 'OPEN in 4860 of 4860' holds for t_det <= 70 ms, the grid bound, not for any recognition.""")


# =============================================================================================================
# Section 5: (c) safe defaults - unchanged network
# =============================================================================================================
def section5():
    hdr("Section 5: (c) Teensy unpowered / reset, every pin level (revision 10 adds no hardware)")
    pins = ["p33", "p28", "p29", "p30", "p31", "p32"]
    envkeys = ["v5", "bus", "vmot_above", "uc1", "clr", "resid", "node_resid", "ff1_prev"]
    bad = n = 0
    for gv in itertools.product(bt5.bt4.LV, repeat=len(pins)):
        g = dict(zip(pins, gv))
        g.update(p5="Z", p8="Z", p20="Z", p34="S")
        for ev in itertools.product((False, True), repeat=len(envkeys)):
            env = dict(zip(envkeys, ev))
            env["teensy"] = False
            for stage in (1, 2):
                s = bt5.hw5(g, env, None, stage)
                n += 1
                if not s["sgnd"] or (s["efuse"] and not env["resid"]):
                    bad += 1
    print("  %d states; S_GND off or eFuse on without a residual: %d" % (n, bad))


# =============================================================================================================
# Section 6: the exit re-close guard with a disabled BT boost (State 98)
# =============================================================================================================
def section6():
    hdr("Section 6: exit step 4 with BT_REG LOW (State 98): busHotPlugUnsafe() is vacuous, no R10-1 refusal")
    for loop in LOOPS:
        s = Sim("P", loop, None, 12.0, 140.0, None, 0.0, 0.16, False, False, bt_reg=False).run(1400.0 + 400.0)
        print("  loop %.3f ms: BT_BUS written at %.1f ms (no refusal: BT_REG LOW makes busHotPlugUnsafe() false,"
              " ino:13043-13045); onset 1400 ms; outcome %s; FC_BUS at the FC recovery %s"
              % (loop, s.ev.get("bt_write", float('nan')), s.latched, s.ev.get("rec")))
    print("""
  Reading. The window entry conditions (9.7) test V_bus, the F1 gate and BT_CURRENT but neither FC_REG nor BT_REG,
  and the 'guarded path' of exit step 4 is busHotPlugUnsafe(BT_REG_ENABLE) = BT_REG HIGH AND V_bus < 13.5 V, which is
  false for a disabled boost. In State 98 (keys 'B'/'2' are free while bonded, 12.4 item 7 CC-7) a window can open with
  the BT boost disabled; the prediction exit then re-closes BT_BUS onto the disabled TPS61288 (the S5 back-feed
  doctrine every fw v37 release path enforces, ino:13421-13426, 13441-13450) and the predicted purge leaves the bus
  with no regulated source: SC-1 (b) latches State 99 on a board with no fault.""")


if __name__ == "__main__":
    section1()
    section2()
    section3()
    section4()
    section5()
    section6()
