"""IC1 detailed design, revision 9 calculations (operator rulings of 2026-11-08: FC windows between purges).

Cited in detailed_design_IC1.md as "calc9 section N". Standard library only. Every input is a value stated in the
design (revision 8), in the fact sheets facts_purge_sequencing.md, facts_purge_collapse.md and facts_purge_demand.md,
or in their scripts (purge_sequencing_timeline.py "seq", purge_collapse_sim.py "pc", purge_demand_budget.py "out").
No purge statistic beyond facts_prior section 7 is used (period 10.34 s, duration 100-140 ms, +/-20 ms per edge).

Sections
  1  Predictor lead time: the two fact-sheet chains reconciled; the design requirement T_lead,min and T_lead,nom
  2  Re-entry after the purge under the adopted literal V_chg rule; dead time and usable time per purge period
  3  Window-admission horizon (minimum predicted time to the next onset that admits a window)
  4  HR2 recomputed: variant P (parked) charge rate; variants D and D-s per drive cycle (fraction of cycle, Ah)
  5  HR2 on the recorded Pi sessions (D against D-s)
"""
import math

def hdr(n, title):
    print("=" * 100)
    print(f"[{n}] {title}")
    print("=" * 100)

# ---------------------------------------------------------------------------------------------------------------
# Inputs (citations)
T_IT_MED, T_IT_P99, T_GAP = 1.131e-3, 1.341e-3, 9.76e-3   # s, facts_firmware s8 (DD Table 11)
T_HOLD_CHECK = 0.15e-3                                     # s, exit hold check samples to 150 us (DD 9.5 exit 1)
T_DRAIN_DL_MED = 13.15e-3                                  # s, T_drain,max at the median loop with one gap (DD Table 11)
T_CONF_DL_MED = 13.15e-3                                   # s, 4-iteration confirmation deadline, median loop, one gap
V_BUS = 15.95                                              # V, FC-window bus (seq s1)
CSS_NF = 100.0                                             # nF, D-BT-EN soft-start capacitor (ino:4853-4860)
T_D_ON_TYP, T_D_ON_SENS = 8e-3, 12e-3                      # s, RT1987 typical; DD Table 8a sensitivity (no maximum)
SEQ_WRITE_TYP = (5.81e-3, 6.94e-3)                         # s, prediction -> BT_BUS write, typical (seq s2)
SEQ_WRITE_WORST = 15.27e-3                                 # s, prediction -> BT_BUS write, worst healthy (seq s2)
SHIFT_DARK_P99 = 258.81e-3                                 # s, dark-handoff walk 0.85->0.15 at the p99 loop (seq s3)
SHIFT_YOULA = (66.67e-3, 133.33e-3)                        # s, 4/wc at 60 and 30 rad/s (seq s3, ESTIMATE)
SHIFT_BACK = (39.59e-3, 133.33e-3)                         # s, shift back toward FC (seq s5)
T_PERIOD = 10.34                                           # s, facts_prior s7
T_PURGE_END = 0.160                                        # s, 140 ms + 20 ms edge after the onset (facts_prior s7)
VCHG_TAU, V_FLOOR_ENTRY = 0.984, 11.0                      # s, V; DD Table 11 (TODO(calibrate)); DD 9.7 entry
ENTRY_CHAIN = (83.53e-3, 188.53e-3, 201.79e-3)             # s, gates met -> charge current: typ, slow start, worst (seq s5)
T_COLD = (0.065, 0.170)                                    # s, Ag105 cold start (facts_prior s6; BENCH S0-6)
T_BRINGUP = (8.4, 11.7)                                    # s, Bring-Up without R_KA (DD Table 11; UNCONFIRMED)
I_SET_FC = 1.25                                            # A, FC profile (DD Table 5)
T_MIN_USEFUL = 1.0                                         # s, minimum useful charge per window (out s5 CHOICE)

def t_on_css(v_in, css_nf):
    """RT1987 soft-start time tON = (VIN/35) x (CSS_nF/0.0023 - 100) us (as quoted at ino:4855)."""
    return (v_in / 35.0) * (css_nf / 0.0023 - 100.0) * 1e-6

# ---------------------------------------------------------------------------------------------------------------
hdr(1, "Predictor lead time T_lead (prediction -> purge onset)")
t_on = t_on_css(V_BUS, CSS_NF)
cond = {d: d + t_on for d in (T_D_ON_TYP, T_D_ON_SENS)}
print(f"  D-BT-EN conduction after the EN write onto a live {V_BUS} V bus: tON = {t_on*1e3:.2f} ms; "
      f"t_D_ON + tON = {cond[T_D_ON_TYP]*1e3:.2f} ms (t_D_ON 8 ms) / {cond[T_D_ON_SENS]*1e3:.2f} ms (12 ms)")
hard_typ = [w + cond[T_D_ON_TYP] for w in SEQ_WRITE_TYP]
hard_worst = SEQ_WRITE_WORST + cond[T_D_ON_SENS]
print(f"  Sequencing sheet, healthy chain: typical {hard_typ[0]*1e3:.2f}-{hard_typ[1]*1e3:.2f} ms, "
      f"worst healthy {hard_worst*1e3:.2f} ms (p99 loop, one 9.76 ms gap, slow node, t_D_ON 12 ms)")
# deadline-based chain: every firmware wait runs to its 4-iteration deadline at the median loop with one gap
write_dl = T_IT_P99 + T_HOLD_CHECK + T_DRAIN_DL_MED + T_CONF_DL_MED
hard_dl = write_dl + cond[T_D_ON_SENS]
print(f"  Deadline-based chain (prediction->drop {T_IT_P99*1e3:.2f} + hold check 0.15 + drain deadline 13.15 + "
      f"confirmation deadline 13.15 ms): BT_BUS write at {write_dl*1e3:.2f} ms; conduction at {hard_dl*1e3:.2f} ms")
print(f"  (the demand sheet's 58.2 ms omits the {T_IT_P99*1e3:.2f} ms from the prediction to the feed-drop write)")
T_LEAD_MIN = math.ceil(hard_dl * 1e3 / 10.0) * 10.0 * 1e-3
print(f"  DESIGN REQUIREMENT T_lead,min = {T_LEAD_MIN*1e3:.0f} ms (deadline chain rounded up to 10 ms): "
      f"margin {((T_LEAD_MIN - hard_worst)*1e3):.1f} ms over the healthy worst")
full_seq = SEQ_WRITE_WORST + SHIFT_DARK_P99
full_dl = write_dl + SHIFT_DARK_P99
full_typ = [h + s for h in hard_typ for s in SHIFT_YOULA]
print(f"  Full tier (ruling-1 shift complete): typical {min(full_typ)*1e3:.1f}-{max(full_typ)*1e3:.1f} ms (ESTIMATE); "
      f"worst {full_seq*1e3:.2f} ms (sequencing sheet); deadline chain + dark-handoff walk {full_dl*1e3:.2f} ms")
T_LEAD_NOM = math.ceil(full_dl * 1e3 / 10.0) * 10.0 * 1e-3
print(f"  DESIGN REQUIREMENT T_lead,nom = {T_LEAD_NOM*1e3:.0f} ms (State-2 windows; deadline chain + dark walk, "
      f"rounded up to 10 ms)")
print("  The demand sheet's 108.3 ms full tier rests on a 20-50 ms EMA ESTIMATE of the shift; the firmware slew")
print("  constants (DROOP_RATIO_SLEW_PER_TICK 0.02, handoff 0.002 for <= 175 ticks, ino:3242, 3288-3325) bound it")
print("  at 258.8 ms instead, so the sequencing figure governs.")
print("  Sensitivity: every ms of t_D_ON above 12 ms adds 1 ms to both requirements.")

# ---------------------------------------------------------------------------------------------------------------
hdr(2, "Re-entry and usable time per purge period (adopted literal rule: V_chg below 11 V on two settled reads)")
t_vchg = VCHG_TAU * math.log(V_BUS / V_FLOOR_ENTRY)
print(f"  VCHG-IN {V_BUS} V -> {V_FLOOR_ENTRY} V on the bleed: {t_vchg*1e3:.1f} ms after the feed drop "
      f"(tau {VCHG_TAU} s, TODO(calibrate))")
rows = []
for var, lead, shift_back in (("P", T_LEAD_MIN, (0.0, 0.0)), ("D-s/D", T_LEAD_NOM, SHIFT_BACK)):
    t_drop = -(lead - T_IT_P99)            # feed drop relative to the onset (one p99 iteration after the prediction)
    for label, ch, sb in (("typ", ENTRY_CHAIN[0], shift_back[0]), ("worst", ENTRY_CHAIN[2], shift_back[1])):
        gate_purge = T_PURGE_END + sb
        gate_vchg = t_drop + t_vchg
        gate = max(gate_purge, gate_vchg)
        resume = gate + ch
        dead = lead + resume
        usable = T_PERIOD - dead
        rows.append((var, label, lead, gate_purge, gate_vchg, resume, dead, usable))
        print(f"  {var:6s} {label:5s} T_lead {lead*1e3:5.0f} ms | purge gate {gate_purge*1e3:6.1f} ms | V_chg gate "
              f"{gate_vchg*1e3:6.1f} ms | charge resumes onset+{resume*1e3:6.1f} ms | dead {dead:5.3f} s | usable "
              f"{usable:5.3f} s ({100*usable/T_PERIOD:4.1f} %) | mean {I_SET_FC*usable/T_PERIOD:5.3f} A at I_set")
print("  Strict reading (wait out the 1.0 s ERR_VCHG_FED blanking) for comparison: dead 1.084-1.202 s, usable 88.4-89.5 %")
print("  (seq s5). The literal reading is adopted: a fed VCHG-IN (F15, F17, pin 31 stuck HIGH) never falls below 11 V,")
print("  so the entry refusal is the same; only the ERR_VCHG_FED latch waits for the blanking.")
for tb in T_BRINGUP:
    for var, label, lead, gp, gv, resume, dead, usable in rows:
        if label != "worst":
            continue
        u = max(0.0, usable - (tb - T_COLD[1]))
        print(f"  Without R_KA, Bring-Up {tb:4.1f} s per cold start, {var:6s} worst: usable {u:5.3f} s "
              f"({100*u/T_PERIOD:4.1f} %), mean {I_SET_FC*u/T_PERIOD:5.3f} A")
    for var, label, lead, gp, gv, resume, dead, usable in rows:
        if label != "typ":
            continue
        u = max(0.0, usable - (tb - T_COLD[0]))
        print(f"  Without R_KA, Bring-Up {tb:4.1f} s per cold start, {var:6s} typ  : usable {u:5.3f} s "
              f"({100*u/T_PERIOD:4.1f} %), mean {I_SET_FC*u/T_PERIOD:5.3f} A")

# ---------------------------------------------------------------------------------------------------------------
hdr(3, "Window-admission horizon")
for var, lead in (("P", T_LEAD_MIN), ("D-s/D", T_LEAD_NOM)):
    horizon = ENTRY_CHAIN[2] + T_MIN_USEFUL + lead
    print(f"  {var:6s}: a window may open only when the predicted time to the next onset is at least "
          f"{ENTRY_CHAIN[2]*1e3:.1f} ms entry + {T_MIN_USEFUL:.1f} s useful + {lead*1e3:.0f} ms lead = {horizon:.3f} s")
print(f"  Inter-purge interval after re-entry (period - worst dead time): "
      f"{min(r[7] for r in rows):.3f} s, so every period admits one window under an ideal predictor")
print(f"  Window transitions: 2 per period = {2*60/T_PERIOD:.1f} per minute against the [RER] limit of 20 per minute")

# ---------------------------------------------------------------------------------------------------------------
hdr(4, "HR2: variant P charge rate and variants D / D-s per drive cycle")
usable_p = [r[7] for r in rows if r[0] == "P"]
print(f"  Variant P (parked, R_KA fitted, CC region below the 8.0 V entry gate): "
      f"{I_SET_FC*min(usable_p)/T_PERIOD:.3f}-{I_SET_FC*max(usable_p)/T_PERIOD:.3f} A mean "
      f"= {I_SET_FC*min(usable_p)/T_PERIOD:.2f}-{I_SET_FC*max(usable_p)/T_PERIOD:.2f} Ah per parked hour; 0 Ah per drive cycle")
print("  (demand sheet Table 4, rule v11 nominal: 1.196 A; rule blank: 1.103-1.117 A; agreement)")
# Demand sheet Table 5 (out s4): plant model, R_KA, V_pack 7.4 V, rule 'none'; length s, D t s, D mAh, D-s t s, D-s mAh,
# pessimistic (IC1 aux 0.15 A, 7.8 V, worst) D mAh
cycles = [
    ("61 s cycle (ems-dp-replay)", 61.0, 57.1, 19.8, 5.5, 1.9, 3.5),
    ("FTP-75 rig slice", 345.0, 181.9, 63.2, 67.1, 23.3, 27.8),
    ("ftp75c", 175.0, 93.4, 32.4, 35.7, 12.4, 15.1),
    ("UDDS_trimmed_3.5mps", 333.0, 144.8, 50.3, 55.5, 19.3, 23.3),
    ("RegenTest_v2_lowspeed", 152.0, 98.2, 34.1, 80.5, 28.0, 29.5),
    ("RegenTest_decel_sweep", 183.0, 111.0, 38.5, 91.8, 31.9, 34.3),
]
print(f"  {'cycle':28s} {'len s':>6s} | {'D-s s':>6s} {'D-s %':>6s} {'D-s mAh':>8s} {'D-s A':>6s} | "
      f"{'D s':>6s} {'D %':>6s} {'D mAh':>7s} {'D pess mAh':>10s} | {'D-s/D':>6s}")
for name, L, td, qd, ts, qs, qp in cycles:
    chk = I_SET_FC * ts / 3.6
    assert abs(chk - qs) < 0.15, (name, chk, qs)
    print(f"  {name:28s} {L:6.0f} | {ts:6.1f} {100*ts/L:5.1f}% {qs:8.1f} {qs*3.6/L:6.3f} | "
          f"{td:6.1f} {100*td/L:5.1f}% {qd:7.1f} {qp:10.1f} | {qs/qd:6.2f}")
print("  Literal re-entry rule: these are rule-'none' figures; rule 'blank' lowers every D figure by 2-7 % (out s4), so")
print("  the adopted literal rule lowers them by at most 7 %. D-s mAh check: I_set x t (CC) reproduces the sheet.")

# ---------------------------------------------------------------------------------------------------------------
hdr(5, "HR2 on the 22 recorded Pi sessions (2831 s live; out s5)")
live, d_s, ds_s, req_s, req_d = 2831.0, 650.0, 600.0, 447.0, 127.0
print(f"  D with the 8.0 V gate: {d_s:.0f} s ({100*d_s/live:.1f} %); D-s: {ds_s:.0f} s ({100*ds_s/live:.1f} %); "
      f"D-s share of D = {100*ds_s/d_s:.0f} %")
print(f"  Moving windows (D minus D-s) add {d_s-ds_s:.0f} s = {100*(d_s-ds_s)/live:.1f} % of live time, "
      f"{I_SET_FC*(d_s-ds_s)/3.6:.1f} mAh at I_set over 47 min")
print(f"  EMS request time {req_s:.0f} s; D yields {req_d:.0f} s inside it ({100*req_d/req_s:.1f} %)")
