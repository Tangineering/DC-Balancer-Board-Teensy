"""IC1 detailed design, revision 10 calculations (battle-test round 6 adjudication).

Cited in detailed_design_IC1.md as "calc10 section N". Standard library only. Every input is a value stated in the
design (revision 9), in the round-6 scripts (bt6_*.py, fmea_round6_calcs.py) or in the firmware (fw v37 rev 2,
cited ino:line). No purge statistic beyond facts_prior section 7 is used (period 10.34 s, duration 100-140 ms,
+/-20 ms per edge). The purge predictor is the operator's design (ruling OR-P) and is not modelled.

Sections
  1  Hard lead time over every placement of the one 9.76 ms gap (BT6-LS-03); T_lead,min and the late-prediction
     threshold T_late seen from the iteration that observes the prediction (BT6-LS-01)
  2  Re-entry and usable time per purge period at the revision-10 lead times (BT6-TR-01, FM6-2, BT6-REQ-04)
  3  Window-admission horizon
  4  Standstill share loop: why the share override moves no MDAC code below the 0.25 A gate (BT6-TR-01, FM6-2)
  5  PI-4 fail-closed rule: the bt6 section-3 grid re-run with the predictor action replaced by an immediate
     ERR_FC_ONLY_COLLAPSE latch (BT6-LS-01)
  6  Request-gated HR2 on the recorded Pi sessions (BT6-REQ-01)
  7  State-99 pack drain time and the window lower V_batt bound (BT6-TR-02, BT6-REQ-02)
  8  Traction release after a State-2 exit (FM6-3)
  9  Firmware size estimate re-derived per package (BT6-REQ-05)

Run:  .venv_hil/Scripts/python.exe calc/ic1_rev10_calcs.py > calc/ic1_rev10_calcs_output.txt
Section 5 imports calc/bt6_logic_seq_enum.py (run_u, classify) and runs about 4900 cases of the five-node model.
"""
import inspect
import itertools
import math
import os
import sys
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def hdr(n, title):
    print("=" * 100)
    print(f"[{n}] {title}")
    print("=" * 100)


# ---------------------------------------------------------------------------------------------------------------
# Inputs (citations)
LOOPS = (1.131e-3, 1.341e-3)          # s, median and p99 loop (facts_firmware s8; DD Table 11)
GAP = 9.76e-3                         # s, one long iteration (facts_firmware s8)
T_HOLD = 0.15e-3                      # s, exit hold check (DD 9.5 exit step 1)
T_SS = 19.77e-3                       # s, D-BT-EN soft-start onto a live 15.95 V bus, CSS 100 nF (calc9 s1)
T_DON = (0.008, 0.012)                # s, RT1987 t_D_ON typical and sensitivity value (no maximum; open item 2)
SHIFT_DARK_P99 = 258.81e-3            # s, dark-handoff walk 0.85 -> 0.15 at the p99 loop (seq s3)
T_PERIOD = 10.34                      # s, facts_prior s7
T_PURGE_END = 0.160                   # s, 140 ms + 20 ms edge (facts_prior s7)
VCHG_TAU, V_BUS, V_FLOOR = 0.984, 15.95, 11.0   # s, V, V; DD 9.11.4 (tau TODO(calibrate))
ENTRY_CHAIN = (83.53e-3, 201.79e-3)   # s, gates met -> charge current, typical and worst (seq s5)
I_SET = 1.25                          # A, FC profile (DD Table 5)
T_MIN_USEFUL = 1.0                    # s, minimum useful charge per window (calc9 s3)
SHIFT_BACK = (39.59e-3, 133.33e-3)    # s, shift back toward FC (seq s5), variant D only after revision 10

# ---------------------------------------------------------------------------------------------------------------
hdr(1, "Hard lead time over every placement of the one gap; T_lead,min and T_late")


def chain(loop, gap_at, drain, conf, tdon):
    """bt6_logic_seq_enum.py section 2 model. Returns (offset of the observing iteration after the prediction,
    BT_BUS write time, conduction time), all from the prediction."""
    t_obs = loop + (GAP - loop if gap_at == "drop" else 0.0)
    t = t_obs + T_HOLD
    dr = 2 * loop if drain == "typ" else max(0.010, 4 * loop)
    dr += (GAP - loop) if gap_at == "drain" else 0.0
    t += min(dr, 0.030)
    cf = 2 * loop if conf == "typ" else max(0.010, 4 * loop)
    cf += (GAP - loop) if gap_at == "confirm" else 0.0
    t += min(cf, 0.030)
    return t_obs, t, t + tdon + T_SS


cases = list(itertools.product(LOOPS, (None, "drop", "drain", "confirm"), ("typ", "deadline"), ("typ", "deadline"),
                               T_DON))
res = [(c, chain(*c)) for c in cases]
w_pred = max(res, key=lambda r: r[1][2])
w_obs = max(res, key=lambda r: r[1][2] - r[1][0])
print(f"  {len(cases)} cases (2 loops x 4 gap placements x drain typ/deadline x confirmation typ/deadline x t_D_ON 8/12 ms)")
print(f"  worst conduction after the PREDICTION: {w_pred[1][2]*1e3:.2f} ms (write {w_pred[1][1]*1e3:.2f} ms; case {w_pred[0]})")
by_gap = {}
for c, (to, tw, tc) in res:
    by_gap[c[1]] = max(by_gap.get(c[1], 0.0), tc)
for g in (None, "drop", "drain", "confirm"):
    print(f"     gap at {str(g):8s}: worst conduction {by_gap[g]*1e3:6.2f} ms after the prediction")
chain_obs = w_obs[1][2] - w_obs[1][0]
print(f"  worst conduction after the OBSERVING iteration (the one that writes the feed drop): {chain_obs*1e3:.2f} ms "
      f"(case {w_obs[0]})")
T_LATE = math.ceil(chain_obs * 1e3) * 1e-3
T_LEAD_MIN = math.ceil((T_LATE + GAP) * 1e3 / 10.0) * 10.0 * 1e-3
min_obs_tto = T_LEAD_MIN - GAP
print(f"  T_late = ceil(worst-from-observation {chain_obs*1e3:.2f} ms) = {T_LATE*1e3:.0f} ms: a prediction first observed"
      f" with purge_tto below T_late cannot be guaranteed to conduct before the onset -> latch, no exit")
print(f"  T_lead,min = ceil10(T_late + one gap before the observing iteration {GAP*1e3:.2f} ms) = {T_LEAD_MIN*1e3:.0f} ms"
      f" (revision 9: 60 ms; conduction at {w_pred[1][2]*1e3:.2f} ms after the prediction, BT6-LS-03)")
print(f"  An ideal predictor announcing at T_lead,min is observed at purge_tto >= {min_obs_tto*1e3:.2f} ms "
      f"(one gap before the observing iteration): margin {(min_obs_tto - T_LATE)*1e3:.2f} ms over T_late, "
      f"so a healthy predictor never trips the late rule")
print(f"  Margin at the onset for an ideal announcement at T_lead,min: {(T_LEAD_MIN - w_pred[1][2])*1e3:.2f} ms")
w_write = max(r[1][1] for r in res)
T_LEAD_NOM = math.ceil((w_write + SHIFT_DARK_P99) * 1e3 / 10.0) * 10.0 * 1e-3
print(f"  Full tier (State 2 in closed loop, filtered total >= 0.25 A): worst write {w_write*1e3:.2f} ms + dark walk "
      f"{SHIFT_DARK_P99*1e3:.2f} ms = {(w_write+SHIFT_DARK_P99)*1e3:.2f} ms -> T_lead,nom = {T_LEAD_NOM*1e3:.0f} ms "
      f"(unchanged; an upper bound: the walk assumes a 0.85 start and the clip floor lo = 0.125/I_tot lifts the end)")

# ---------------------------------------------------------------------------------------------------------------
hdr(2, "Re-entry and usable time per purge period (literal V_chg rule), revision-10 lead times")
t_vchg = VCHG_TAU * math.log(V_BUS / V_FLOOR)
print(f"  VCHG-IN {V_BUS} V -> {V_FLOOR} V on the bleed: {t_vchg*1e3:.1f} ms after the feed drop")
rows = []
for var, lead, sb in (("P", T_LEAD_MIN, (0.0, 0.0)), ("D-s", T_LEAD_MIN, (0.0, 0.0)),
                      ("D (not adopted)", T_LEAD_NOM, SHIFT_BACK)):
    t_drop = -(lead - LOOPS[1])
    for label, ch, s in (("typ", ENTRY_CHAIN[0], sb[0]), ("worst", ENTRY_CHAIN[1], sb[1])):
        gp, gv = T_PURGE_END + s, t_drop + t_vchg
        resume = max(gp, gv) + ch
        dead = lead + resume
        usable = T_PERIOD - dead
        rows.append((var, label, dead, usable))
        print(f"  {var:16s} {label:5s} T_lead {lead*1e3:4.0f} ms | purge gate {gp*1e3:6.1f} | V_chg gate {gv*1e3:6.1f} | "
              f"binding {'V_chg' if gv >= gp else 'purge end'} | resumes onset+{resume*1e3:6.1f} ms | dead {dead:5.3f} s"
              f" | usable {usable:5.3f} s ({100*usable/T_PERIOD:4.1f} %) | mean {I_SET*usable/T_PERIOD:5.3f} A")
print("  With the V_chg gate binding, the dead time runs from the feed drop to the charge resume and does not depend on")
print("  the lead: P and D-s are identical, and a longer lead moves the resume earlier relative to the onset only.")

# ---------------------------------------------------------------------------------------------------------------
hdr(3, "Window-admission horizon")
for var, lead in (("P and D-s", T_LEAD_MIN), ("D (not adopted)", T_LEAD_NOM)):
    print(f"  {var:16s}: {ENTRY_CHAIN[1]*1e3:.1f} ms entry + {T_MIN_USEFUL:.1f} s useful + {lead*1e3:.0f} ms lead = "
          f"{ENTRY_CHAIN[1] + T_MIN_USEFUL + lead:.3f} s")

# ---------------------------------------------------------------------------------------------------------------
hdr(4, "Standstill share loop below the 0.25 A gate (fw v37 rev 2)")
I_MIN, HYST, ALPHA, I_TOT_MIN = 0.125, 0.05, 0.05, 0.075   # ino:3202, 3233, 3330, 3116
print(f"  closed loop above 2 x I_min = {2*I_MIN:.2f} A; open loop below {2*I_MIN-HYST:.2f} A (ino:14313-14327)")
for tot in (0.016, 0.024, 0.09, 0.15, 0.165, 0.20, 0.225, 0.25):
    lo = I_MIN / tot
    state = "FROZEN return before the EMA (SHARE_I_TOT_MIN_A, ino:14287)" if tot < I_TOT_MIN else \
        ("feedforward clip band EMPTY -> HOLD prevRatio (ino:13772-13782)" if lo >= 1 - lo else "band open")
    print(f"     total {tot:5.3f} A: lo = {lo:5.3f}, hi = {1-lo:6.3f}: {state}")
for f0, aux in ((0.91, 0.09), (1.08, 0.15)):
    n = math.log((2 * I_MIN - HYST - aux) / (f0 - aux)) / math.log(1 - ALPHA)
    print(f"  EMA from {f0:.2f} A to the open-loop exit at aux {aux:.2f} A: {math.ceil(n)} ticks "
          f"({math.ceil(n)*LOOPS[0]*1e3:.0f}-{math.ceil(n)*LOOPS[1]*1e3:.0f} ms)")
print("  -> at a standstill total the override and the shift back move no MDAC code; on the vehicle (bag standstill total")
print("     0.016 A median, 0.024 A maximum, bt6_bag_launch_output) the loop freezes on the first sample. The BT_BUS")
print("     re-close is therefore the whole ruling-(1) shift in P and D-s; the override is kept for State 2 in closed loop.")

# ---------------------------------------------------------------------------------------------------------------
hdr(5, "PI-4 fail-closed rule: bt6 section-3 grid with the predictor action = immediate ERR_FC_ONLY_COLLAPSE")
import bt6_logic_seq_enum as bt6   # noqa: E402

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
assert old in src, "bt6 run_u source changed; update the substitution"
src = src.replace(old, new).replace("def run_u(", "def run_l(")
ns = dict(vars(bt6))
exec(compile(src, "run_l", "exec"), ns)
run_l = ns["run_l"]
modes = (('CP', 13.0), ('CP', 14.8), ('MPPT', 14.8))
tally = {}
n = writes = big = 0
lat = []
for (mode, p), aux, cv, tf, var, tdet, order in itertools.product(
        modes, (0.0005, 0.015, 0.15), (0.48e-3, 1.5e-3, 5e-3), (0.0, 0.020, 0.040, 0.060, 0.075), ('P', 'D'),
        (0.0, 0.002, 0.010, 0.020, 0.030, 0.040, 0.050, 0.060, 0.070), ('exit-first', 'det-first')):
    e = run_l(mode, p, 221e-6, aux, cv, tf, (12.10, 12.88), var, tdet, order, 1.341e-3)
    n += 1
    writes += 't_bt_write' in e
    big += e['bt_peak_i'] > 2.5
    if 't_latch' in e:
        lat.append(e['t_latch'])
    for tr in (0.080, 0.100):
        c = bt6.classify(e['snap'][tr])
        tally.setdefault(tr, {}).setdefault(c, 0)
        tally[tr][c] += 1
print(f"  {n} cases (both in-iteration orderings), p99 loop, C_mod 221 uF")
for tr in sorted(tally):
    print(f"     t_rec {tr*1e3:3.0f} ms: {tally[tr]}")
print(f"  BT_BUS HIGH writes after the onset: {writes}; bus-side BT peak above 2.5 A: {big}; latch at "
      f"{min(lat)*1e3:.1f}-{max(lat)*1e3:.1f} ms after the onset")
print("  Baseline as written in revision 9 (bt6 output s3): 15 HAZARD at 80 ms, 886 BT_BUS writes, 137 peaks above 2.5 A")

# ---------------------------------------------------------------------------------------------------------------
hdr(6, "HR2 on the recorded Pi sessions, request-gated (bt6_req_ds_request_gate_output.txt TOTALS)")
req, d_g, ds_g, ds_ungated, d_ungated = 446.6, 127.5, 107.3, 600.0, 650.0
print(f"  EMS request time (charge_goal > 0.05): {req:.1f} s")
print(f"  D-s AND request AND V_batt < 8.0 V: {ds_g:.1f} s = {100*ds_g/req:.1f} % of the request, {I_SET*ds_g/3.6:.1f} mAh")
print(f"  D   AND request AND V_batt < 8.0 V: {d_g:.1f} s = {100*d_g/req:.1f} % of the request, {I_SET*d_g/3.6:.1f} mAh")
print(f"  D increment over D-s: {d_g-ds_g:.1f} s ({I_SET*(d_g-ds_g)/3.6:.1f} mAh) gated, {d_ungated-ds_ungated:.0f} s "
      f"({I_SET*(d_ungated-ds_ungated)/3.6:.1f} mAh) ungated; D-s/D = {100*ds_g/d_g:.0f} % gated, "
      f"{100*ds_ungated/d_ungated:.0f} % ungated")
print(f"  Request time refused under D-s (in motion, or V_batt >= 8.0 V): {100*(1-ds_g/req):.1f} %")
pd = {"61 s cycle": (1.9, 3.5), "FTP-75 slice": (23.3, 27.8), "ftp75c": (12.4, 15.1), "UDDS": (19.3, 23.3)}
for k, (ds, dp) in pd.items():
    print(f"  plant model, request at every stop, {k:13s}: D pessimistic / D-s = {dp/ds:.2f}")

# ---------------------------------------------------------------------------------------------------------------
hdr(7, "State-99 pack drain (UNCONFIRMED inputs) and the window lower V_batt bound")
for q in (2.0, 5.0):
    for i in (0.20, 0.25):
        print(f"  remaining {q:.0f} Ah at {i:.2f} A (State-99 logic load, pc s6, UNCONFIRMED): {q/i:5.1f} h")
print("  UV_BATT arms only after V_batt >= V_BATT_ARM_THRESH 7.8 V with the BT pair routed (ino:2261-2267, 7283-7294);")
print("  a pack that boots below 7.8 V never arms it. Revision 10 adds the entry condition V_batt >= LIMIT_V_BATT_MIN")
print("  7.4 V (ino:2096) on two settled iterations, read directly, independent of btUvArmed (refusal code 14).")

# ---------------------------------------------------------------------------------------------------------------
hdr(8, "Traction release after a State-2 window exit (FM6-3)")
for tdon in T_DON:
    print(f"  t_D_ON {tdon*1e3:.0f} ms: D-BT-EN conducts {(tdon+T_SS)*1e3:.2f} ms after the BT_BUS write; worst healthy "
          f"write 15.27 ms (Table 21) -> traction released {15.27+(tdon+T_SS)*1e3:.2f} ms after the command; "
          f"deadline chain write {w_write*1e3:.2f} ms -> {(w_write+tdon+T_SS)*1e3:.2f} ms")

# ---------------------------------------------------------------------------------------------------------------
hdr(9, "Firmware size estimate per package (ESTIMATE, UNCONFIRMED)")
# Calibration points (design 12.12; calc/bt2_requirements_operability.py section D):
#   fw v28 (one feature package): +1916 .ino lines, +389 run_tests checks  -> 0.203 checks per line
#   fw v37 J session (one State-98 mode, three guards): about 1250 lines; v37 rev 2 guards alone 449 lines (~150/guard)
CHK_PER_LINE = 389 / 1916.0
pk = [
    ("Mode manager, 8 states, self-test, two ladder decoders, EEPROM record", 1.0, 1.5, 1916),
    ("27 new ERR_ conditions (18 exist in fw v37 rev 2) at 100-150 lines each", 27 * 100 / 1916, 27 * 150 / 1916, 1916),
    ("Ag105 policy, FC window, configuration check, probe, dump check", 1.0, 1.5, 1250),
    ("Purge interface, PI-4 latch, D-s window, in-band substitution, traction hold", 0.5, 1.0, 1916),
    ("Telemetry v6 / BLG and the refusal word", 0.25, 0.5, 1250),
]
lo_t = hi_t = 0.0
for name, a, b, base in pk:
    lo, hi = a * base, b * base
    lo_t += lo
    hi_t += hi
    print(f"  {name:78s}: {lo:6.0f}-{hi:6.0f} lines")
print(f"  total .ino: {lo_t:.0f}-{hi_t:.0f} lines; host checks at {CHK_PER_LINE:.3f} per line: "
      f"{lo_t*CHK_PER_LINE:.0f}-{hi_t*CHK_PER_LINE:.0f}")
print("  Stage-1 share: every package except the regen/VOK parts of the faults (about 6 of the 27 conditions):")
s1_lo = lo_t - 6 * 100
s1_hi = hi_t - 6 * 150
print(f"     Stage 1 about {s1_lo:.0f}-{s1_hi:.0f} lines ({100*s1_lo/lo_t:.0f}-{100*s1_hi/hi_t:.0f} %); the purge package "
      f"(fourth row) {0.5*1916:.0f}-{1.0*1916:.0f} lines")
