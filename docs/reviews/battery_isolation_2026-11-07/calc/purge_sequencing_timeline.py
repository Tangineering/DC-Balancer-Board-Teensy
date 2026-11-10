"""Pre-purge window-close timeline, predictor lead time T_lead and post-purge re-entry (IC1 revision 8).

Supports docs/reviews/battery_isolation_2026-11-07/facts_purge_sequencing.md.

Run (stdlib only):
    .venv_hil/Scripts/python.exe purge_sequencing_timeline.py > purge_sequencing_timeline_output.txt

Scope (operator rulings 2026-11-08): the purge predictor is IDEAL and is not modelled. Purge
period and duration are the facts_prior section 7 figures only (10.34 s; 100-140 ms, +/-20 ms per
edge). This script computes the firmware/hardware chain that the predictor must lead, and the
dead time it leaves per purge period. Every input carries its citation; ESTIMATE / BENCH /
UNCONFIRMED tags mark values that no primary source fixes.

Abbreviations: DD = docs/reviews/battery_isolation_2026-11-07/detailed_design_IC1.md (rev 8);
ino = teensy_controller/teensy_controller.ino (fw v37 rev 2).

Sections
  1  Inputs
  2  Exit chain: prediction -> feed drop -> drain -> bond -> BT_BUS write -> BT conduction
  3  Share shift toward battery (slew arithmetic, Youla design bandwidth)
  4  T_lead tiers (hard: BT conducting; full: shift complete; deadline bound)
  5  Post-purge re-entry: gates and the entry chain to charge current
  6  Usable charge time per 10.34 s period
  7  Sensitivities: Ag105 Bring-Up, t_D_ON 12 ms, the F1 selector re-close adder, rate limit
"""
import math

# ---------------------------------------------------------------------------------------------
# 1. Inputs
# ---------------------------------------------------------------------------------------------
# Main-loop iteration (facts_firmware section 8; DD Table 11 "Firmware loop")
T_IT_MED = 1.131e-3        # s, median iteration
T_IT_P99 = 1.341e-3        # s, p99 iteration (upper end of 1337-1341 us)
T_GAP = 9.76e-3            # s, worst measured iteration (ML0226); applied ONCE per chain (DD calc7 sec 5 convention)

# Commanded-exit hold check (DD section 9.5 exit step 1): samples pin 8 at 50 us and 150 us after the write
T_HOLDCHK = 150e-6

# Module-node dump (DD section 5.3 / R6-3: R_MD 15 Ohm; U_MS threshold 8.69-9.15 V; C_mod 100-221 uF, Table 11)
R_MD = 15.0
C_MOD = (100e-6, 221e-6)
V_MS = (8.69, 9.15)
# FC-window module-node level: VBUS through D-BC-FC and the eFuse. V0 15.95 V no-load intercept
# (hil_plant_sim.V_BUS_DROOP_V0, cited in calc/purge_demand_budget.py); the eFuse drop is neglected,
# which over-states the start voltage and so lengthens the drain (conservative).
V_NODE_FC = 15.95
T_DRAIN_MAX_CAP = 30e-3    # s, ERR_MOD_DRAIN deadline cap (DD Table 11)

# Bond hardware: FF1 clear -> both S_GND on within about 0.3 ms (DD section 9.5 exit step 3, Table 11)
T_BOND_HW = 0.3e-3
# Confirmation: settled reading = two identical decodes on successive iterations (DD 12.4 item 4,
# Table 11 "Settled ladder reading": 2.26 ms median, 2.68 ms p99); deadline 4 iterations or 30 ms.
N_CONFIRM = 2
N_CONFIRM_DEADLINE = 4
T_CONFIRM_CAP = 30e-3

# RT1987 bus switch conduction onset on re-close onto an energized bus (ino:4853-4858):
#   t_D_ON 8 ms typ (RT1987 DS 17.4/17.6 Table 1; ino:4875 RT1987_T_D_ON_MS); no maximum (DD Table 11)
#   tON = (VIN/35) * (CSS_nF/0.0023 - 100) us, CSS = 100 nF on FC_BUS and BT_BUS (ino:4856-4857);
#   the TRCB comparator holds the survivor off for essentially the whole ramp (ino:4858-4860).
T_D_ON = 8e-3
T_D_ON_SENS = 12e-3        # DD Table 8a sensitivity value
CSS_BUS_NF = 100.0
V_BT_OUT = 15.95           # BT boost output ~ bus no-load intercept (as V_NODE_FC)
SURVIVOR_BLANK = 30e-3     # SHARE_CUT_SURVIVOR_BLANK_MS (ino:4869)

# Share loop (ino)
DROOP_R_MIN, DROOP_R_MAX = 0.15, 0.85          # ino:3101, 3105
SLEW_FULL = 0.02                                # DROOP_RATIO_SLEW_PER_TICK, ino:3242
SLEW_HANDOFF = 0.002                            # DROOP_RATIO_SLEW_HANDOFF_PER_TICK (ino:3288-3293)
HANDOFF_CAP_TICKS = 175                         # SHARE_HANDOFF_DWELL_MAX_TICKS, ino:3325
POWER_BAL_PERIOD = 1e-3                         # POWER_BAL_PERIOD_US, ino:3748 (rate-gated; runs at most once per iteration)
WC_SHARE = (30.0, 60.0)                         # rad/s, design closed-loop bandwidth (controller_design/system_model.md:342)
SELECTOR_DWELL = 0.250                          # SHARE_SELECTOR_DWELL_MS, ino:3466
F1_REOPEN_MEASURED = (39.6e-3, 39.9e-3)         # FC_CHARGE after the F1 disarm (CLAUDE.md campaigns I and II addenda)

# Post-purge re-entry
T_PERIOD = 10.34           # s, purge period (facts_prior section 7)
T_PURGE = (0.100, 0.140)   # s, purge duration (facts_prior section 7)
T_EDGE = 0.020             # s, +/- per edge (facts_prior section 7)
VCHG_TAU = 0.984           # s, VCHG-IN bleed tau, TODO(calibrate) at C-2 (DD Table 11)
V_VCHG_FED = 11.0          # V, entry needs V_chg below 11 V (DD 9.7 entry conditions; ERR_VCHG_FED row)
T_VCHG_BLANK = 1.0         # s, ERR_VCHG_FED blanking after any pin-31 fall (DD 12.6 ERR_VCHG_FED row)
T_BTDROP_TIMEOUT = 20e-3   # s, entry step 5 timeout (DD 9.7)
N_BTDROP = 2               # iterations to see BT_CURRENT < 0.2 A after BT_BUS LOW (ESTIMATE; RT1987 turn-off
                           # after EN low is TODO(verify: RT1987 DS-00), DD Table 11)
T_ASSERT = 100e-6          # assertFcChargeEnable(true): delayMicroseconds(100) (ino:12773)
T_DBC_RAMP_UVLO = 1.07e-3  # D-BC-FC on to eFuse UVLO, 12 V/ms to 12.88 V (DD Table 11; CSS 5.6 nF)
T_EF_ON = 1.24e-3          # eFuse UVLO/SHDN turn-on (DD Table 11)
T_EF_RAMP = 3.6e-3         # eFuse output ramp to 18 V (DD Table 11); to ~15.9 V it is shorter (conservative)
T_COLD = (0.065, 0.170)    # s, Ag105 cold start to current, prior measurement (facts_prior section 6); BENCH S0-6
T_BRINGUP = (8.4, 11.7)    # s, Ag105 Bring-Up without keep-alive (DD Table 11; facts_ag105 section 3); applicability
                           # to an isolated return UNCONFIRMED
RATE_LIMIT_PER_MIN = 20    # window transitions per minute ([RER]; DD 12.4 item 3)


def ms(x):
    return f"{x * 1e3:8.2f} ms"


def hdr(n, t):
    print()
    print("=" * 96)
    print(f"Section {n}: {t}")
    print("=" * 96)


hdr(1, "Inputs (see the docstring for citations)")
for k in ["T_IT_MED", "T_IT_P99", "T_GAP", "R_MD", "C_MOD", "V_MS", "V_NODE_FC", "T_D_ON", "T_D_ON_SENS",
          "CSS_BUS_NF", "SLEW_FULL", "SLEW_HANDOFF", "HANDOFF_CAP_TICKS", "WC_SHARE", "T_PERIOD", "T_PURGE",
          "VCHG_TAU", "T_VCHG_BLANK", "T_COLD", "T_BRINGUP"]:
    print(f"  {k:18s} = {globals()[k]}")

# ---------------------------------------------------------------------------------------------
# 2. Exit chain
# ---------------------------------------------------------------------------------------------
hdr(2, "Exit chain from 'purge predicted' to BT conducting")


def drain_cross(c, vth, v0=V_NODE_FC):
    """RC dump through R_MD only (module input current ignored -> slower -> conservative)."""
    return R_MD * c * math.log(v0 / vth)


tx_fast = drain_cross(C_MOD[0], V_MS[1])
tx_slow = drain_cross(C_MOD[1], V_MS[0])
print(f"  Module-node dump {V_NODE_FC} V -> U_MS edge: {ms(tx_fast)} (100 uF, 9.15 V) .. {ms(tx_slow)} (221 uF, 8.69 V)")
print(f"  (DD Table 11 gives 1.3-2.9 ms from 21.5 V for the regen window; the FC window starts lower)")


def reads_after(t_cross, t_it, gap=0.0):
    """Second successive LOW read: iterations are counted from the write iteration; the first read that
    can see LOW is the first iteration boundary after the crossing; the second is one iteration later.
    A gap, when present, lengthens the first iteration after the write."""
    t, n = 0.0, 0
    first = None
    while True:
        n += 1
        t += (gap if (n == 1 and gap) else t_it)
        if t >= t_cross and first is None:
            first = t
            continue
        if first is not None:
            return t


def tb_bt_onset(t_don, vin=V_BT_OUT):
    return t_don + (vin / 35.0) * (CSS_BUS_NF / 0.0023 - 100.0) * 1e-6


T_TON = tb_bt_onset(0.0)
print(f"  RT1987 CSS 100 nF ramp at {V_BT_OUT} V: tON = {ms(T_TON)}; onset = t_D_ON + tON = "
      f"{ms(tb_bt_onset(T_D_ON))} (t_D_ON 8 ms) / {ms(tb_bt_onset(T_D_ON_SENS))} (12 ms)")

cases = {
    "typ (median loop, fast node)": dict(t_it=T_IT_MED, tx=tx_fast, gap=0.0, tdon=T_D_ON),
    "typ (median loop, slow node)": dict(t_it=T_IT_MED, tx=tx_slow, gap=0.0, tdon=T_D_ON),
    "worst healthy (p99 + one 9.76 ms gap, slow node, t_D_ON 12 ms)": dict(t_it=T_IT_P99, tx=tx_slow, gap=T_GAP,
                                                                           tdon=T_D_ON_SENS),
}
exit_res = {}
for name, c in cases.items():
    t_it = c["t_it"]
    lag = t_it                                    # prediction seen at the next chgModeTick (<= 1 iteration)
    drain = reads_after(c["tx"], t_it, c["gap"])  # from the feed-drop write to the second LOW read
    confirm = N_CONFIRM * t_it
    t_feed = lag
    t_p33 = t_feed + T_HOLDCHK + drain
    t_bonded_hw = t_p33 + T_BOND_HW
    t_btw = t_p33 + confirm                       # BT_BUS write in the confirming iteration (DD 9.7 exit step 4)
    t_bt_on = t_btw + tb_bt_onset(c["tdon"])
    exit_res[name] = dict(t_feed=t_feed, t_p33=t_p33, t_btw=t_btw, t_bt_on=t_bt_on, t_it=t_it)
    print(f"\n  {name}")
    print(f"    prediction -> FC_CHARGE LOW (feed drop)     {ms(t_feed)}")
    print(f"    feed drop -> 2nd pin-8 LOW read (drain)      {ms(T_HOLDCHK + drain)}")
    print(f"    -> pin 33 LOW (bond command)                 {ms(t_p33)}")
    print(f"    -> both S_GND on (hardware, +0.3 ms)         {ms(t_bonded_hw)}")
    print(f"    -> bonded confirmation + BT_BUS write        {ms(t_btw)}")
    print(f"    -> BT pass FET conducting (t_D_ON + tON)     {ms(t_bt_on)}")
    print(f"    -> survivor blanking ends (write + 30 ms)    {ms(t_btw + SURVIVOR_BLANK)}")

# Deadline bound: the chain still bonds at the ERR_MOD_DRAIN deadline (DD 9.5 exit step 2 "latch and continue");
# a failed confirmation latches ERR_CHG_EXIT (State 99). Bound the healthy-or-latched chain:
t_dead_bound = T_IT_P99 + T_HOLDCHK + T_DRAIN_MAX_CAP + T_CONFIRM_CAP + tb_bt_onset(T_D_ON_SENS)
print(f"\n  Deadline bound (drain cap 30 ms + confirmation cap 30 ms + onset at t_D_ON 12 ms): {ms(t_dead_bound)}")
print("  Beyond the confirmation deadline the board latches ERR_CHG_EXIT (State 99) instead of re-closing BT_BUS.")

# ---------------------------------------------------------------------------------------------
# 3. Share shift
# ---------------------------------------------------------------------------------------------
hdr(3, "Share shift toward the battery (in-band reference to DROOP_R_MIN)")
span = DROOP_R_MAX - DROOP_R_MIN
n_full = math.ceil(round(span / SLEW_FULL, 9))
span_slow = HANDOFF_CAP_TICKS * SLEW_HANDOFF
n_rest = math.ceil(round((span - span_slow) / SLEW_FULL, 9))
for lbl, t_it in (("median", T_IT_MED), ("p99", T_IT_P99)):
    tick = max(POWER_BAL_PERIOD, t_it)
    print(f"  {lbl:6s} loop: powerBalance() tick {ms(tick)}")
    print(f"     full-rate walk 0.85->0.15: {n_full} ticks = {ms(n_full * tick)}")
    print(f"     dark-handoff walk: {HANDOFF_CAP_TICKS} ticks at 0.002 (span {span_slow:.2f}) + {n_rest} at 0.02 = "
          f"{HANDOFF_CAP_TICKS + n_rest} ticks = {ms((HANDOFF_CAP_TICKS + n_rest) * tick)}")
for wc in WC_SHARE:
    print(f"  Youla design bandwidth {wc:.0f} rad/s: 10-90 % rise ~2.2/wc = {ms(2.2 / wc)}; 2 % settle ~4/wc = {ms(4 / wc)} (ESTIMATE, first-order)")
T_SHIFT_TYP = (4 / WC_SHARE[1], 4 / WC_SHARE[0])         # after BT conduction onset
T_SHIFT_WORST = (HANDOFF_CAP_TICKS + n_rest) * max(POWER_BAL_PERIOD, T_IT_P99)  # from the BT_BUS write
print(f"  Adopted: typ shift complete {ms(T_SHIFT_TYP[0])}..{ms(T_SHIFT_TYP[1])} after BT conduction onset;")
print(f"           worst {ms(T_SHIFT_WORST)} after the BT_BUS write (dark-handoff limiter, p99 loop; covers the onset).")

# ---------------------------------------------------------------------------------------------
# 4. T_lead
# ---------------------------------------------------------------------------------------------
hdr(4, "Predictor lead time T_lead (prediction -> purge onset)")
typ = exit_res["typ (median loop, slow node)"]
wst = exit_res["worst healthy (p99 + one 9.76 ms gap, slow node, t_D_ON 12 ms)"]
TL_HARD = (typ["t_bt_on"], wst["t_bt_on"])
TL_FULL = (typ["t_bt_on"] + T_SHIFT_TYP[0], typ["t_bt_on"] + T_SHIFT_TYP[1], wst["t_btw"] + T_SHIFT_WORST)
print(f"  Hard tier (BT_BUS conducting before onset):   typ {ms(TL_HARD[0])}   worst {ms(TL_HARD[1])}")
print(f"  Full tier (share shift complete before onset): typ {ms(TL_FULL[0])}..{ms(TL_FULL[1])}   worst {ms(TL_FULL[2])}")
print(f"  Deadline bound of the hard tier:               {ms(t_dead_bound)}")
print("  Variant P (State 1): powerBalance() is not called in Idle (ino:7826-7869), so no shift exists; only the hard tier applies.")

# ---------------------------------------------------------------------------------------------
# 5. Re-entry
# ---------------------------------------------------------------------------------------------
hdr(5, "Earliest post-purge re-entry (times relative to purge onset t = 0)")
t_vchg11 = VCHG_TAU * math.log(V_NODE_FC / V_VCHG_FED)
print(f"  VCHG-IN {V_NODE_FC} V -> {V_VCHG_FED} V on the bleed: {ms(t_vchg11)} after the feed drop (tau {VCHG_TAU} s, TODO(calibrate))")
print(f"  ERR_VCHG_FED blanking: {T_VCHG_BLANK} s after the feed drop")


def entry_chain(t_it, tdon, tcold):
    return (N_CONFIRM * t_it + N_BTDROP * t_it + T_ASSERT + tdon + T_DBC_RAMP_UVLO + T_EF_ON + T_EF_RAMP + tcold)


EC = {"typ": entry_chain(T_IT_MED, T_D_ON, T_COLD[0]), "typ-slow": entry_chain(T_IT_MED, T_D_ON, T_COLD[1]),
      "worst": entry_chain(T_IT_P99, T_D_ON_SENS, T_COLD[1]) + (T_GAP - T_IT_P99)}
for k, v in EC.items():
    print(f"  Entry chain (gates met -> Ag105 charge current), {k:8s}: {ms(v)}  (of which cold start "
          f"{ms(T_COLD[0] if k == 'typ' else T_COLD[1])})")
SHIFT_BACK = (n_full * T_IT_MED, 4 / WC_SHARE[0])   # both channels live: full-rate slew, Youla settle
print(f"  Variant D shift back toward FC after the purge: {ms(SHIFT_BACK[0])} (full-rate slew) .. {ms(SHIFT_BACK[1])} (Youla 4/wc at 30 rad/s)")

rows = []
for variant in ("P", "D"):
    for reading in ("strict (blanking)", "literal (V_chg < 11 V)"):
        for tl_name, tl in (("typ", TL_HARD[0] if variant == "P" else TL_FULL[1]),
                            ("worst", TL_HARD[1] if variant == "P" else TL_FULL[2])):
            purge_end = T_PURGE[1] + T_EDGE                 # predictor declares the end; worst 140 ms + edge
            g_purge = purge_end + (SHIFT_BACK[1] if variant == "D" else 0.0)
            g_vchg = (T_VCHG_BLANK if reading.startswith("strict") else t_vchg11) - tl
            start = max(g_purge, g_vchg)
            binding = "VCHG" if g_vchg >= g_purge else ("purge+shift" if variant == "D" else "purge end")
            ec = EC["typ"] if tl_name == "typ" else EC["worst"]
            resume = start + ec
            dead = tl + resume
            rows.append((variant, reading, tl_name, tl, g_purge, g_vchg, binding, resume, dead, T_PERIOD - dead))
print()
print("  var reading                  case   T_lead     purge-gate  VCHG-gate   binding       resume(onset+)  dead/period  usable")
for r in rows:
    print(f"  {r[0]:3s} {r[1]:24s} {r[2]:6s} {ms(r[3])} {ms(r[4])} {ms(r[5])}  {r[6]:12s} {ms(r[7])}    {r[8]:6.3f} s    "
          f"{r[9]:6.3f} s ({100 * r[9] / T_PERIOD:5.1f} %)")

# ---------------------------------------------------------------------------------------------
# 6/7. Sensitivities
# ---------------------------------------------------------------------------------------------
hdr(6, "Usable charge time per period: summary")
for v in ("P", "D"):
    sel = [r for r in rows if r[0] == v]
    lo = min(r[9] for r in sel)
    hi = max(r[9] for r in sel)
    print(f"  Variant {v}: usable {lo:.3f}-{hi:.3f} s of {T_PERIOD} s ({100 * lo / T_PERIOD:.1f}-{100 * hi / T_PERIOD:.1f} %), "
          "before the Ag105 Bring-Up question and before the demand budget (facts_purge_demand.md)")

hdr(7, "Sensitivities")
for tb in T_BRINGUP:
    worst_dead = max(r[8] for r in rows) - T_COLD[1] + tb
    best_dead = min(r[8] for r in rows) - T_COLD[0] + tb
    print(f"  If every cold start runs a Bring-Up of {tb} s: usable {max(0.0, T_PERIOD - worst_dead):.3f}-"
          f"{max(0.0, T_PERIOD - best_dead):.3f} s per period")
print(f"  F1 selector re-close adder (only if the pre-purge shift let the selector cut FC_BUS): "
      f"{ms(F1_REOPEN_MEASURED[0])}-{ms(F1_REOPEN_MEASURED[1])} measured (campaigns I/II); selector dwell {SELECTOR_DWELL} s on a source change")
per_min = 2 * 60.0 / T_PERIOD
print(f"  Window transitions at one window per period: entry + exit = {per_min:.1f} per minute against the "
      f"{RATE_LIMIT_PER_MIN}/min [RER] limit")
print(f"  T_lead change from t_D_ON 8 -> 12 ms (hard tier): +{ms(T_D_ON_SENS - T_D_ON)}")
