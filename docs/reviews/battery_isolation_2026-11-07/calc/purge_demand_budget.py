"""In-drive demand budget for FC charge windows between H-20 purges (IC1 revision 8), ideal purge predictor.

Supports docs/reviews/battery_isolation_2026-11-07/facts_purge_demand.md (revision 2026-11-08, after the
operator rulings of 2026-11-08: the purge predictor exists and is ideal; FC windows may open in State 2
between purges (variant D) as well as parked (variant P)).

Run (needs numpy and mcap_ros2 for section 5; the miniforge interpreter has both):
    C:/Users/ricky/miniforge3/python.exe purge_demand_budget.py > purge_demand_budget_output.txt

Purge facts are NOT measured here. They are the facts_prior section 7 figures only: period 10.34 s,
duration 100-140 ms, floor about 1 V. Every other input constant carries its citation.

Sections
  1  FC-window bus budget (charger input + aux vs P_MAX / governor / OC_FC)
  2  Predictor interface: lead time T_lead before onset and earliest re-entry after the purge
  3  Variant P (parked, State 1 / 98): charge per inter-purge interval and mean rate
  4  Drive cycles through the HIL plant demand model: variant D (State 2) and its standstill subset D-s
  5  Pi sessions: variant D on the measured bus current, synthetic purge schedule, EMS request
  6  Braking inside an FC window; traction requests mid-window; bus collapse rate (units fixed)
"""
import glob
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "tools", "rosbag_analysis"))

import hil_plant_sim as sim            # noqa: E402  plant mechanics constants and profiles
import gen_dp_ems_table as dpt         # noqa: E402  build_demand(): the plant's demand model


def hdr(n, title):
    print()
    print("=" * 100)
    print(f"Section {n}: {title}")
    print("=" * 100)


# ---------------------------------------------------------------------------
# Constants (with citations)
# ---------------------------------------------------------------------------
I_SET_FC = 1.25        # A, FC profile RCS 24.02 kOhm (detailed_design_IC1.md Table 8, sec 9.7 entry step 1); BENCH S0-4
I_L = 0.30             # A, unregulated VBT load in an FC window (BT_BUS open), UNCONFIRMED working value, gate B8 (Table 8)
ETA_CHG = 0.88         # Ag105 DS V1.1 p.20 (12 V in, 3S only) - not stated for 2S / 16 V in (IC1 sec 7.1)
ETA_CHG_LOW = 0.80     # sensitivity case (calc/ic1_rev3_calcs.py sec 1)
V_BUS_V0 = sim.V_BUS_DROOP_V0          # 15.95 V measured no-load intercept (hil_plant_sim.py:511)
K_SINGLE = sim.K_DROOP_BUS_SINGLE      # 0.16 V/A, exactly one source live (hil_plant_sim.py:510)
P_MAX_BUS_A = 1.247    # A, H-20 P_MAX 23.416 W stack, bus equivalence (CLAUDE.md 2026-09-09 addendum; tools/h2_map.py)
GOV_A = 1.25           # A, SHARE_GOV_I_FC_CEIL_A (facts_firmware sec 5; ino:3530)
OC_FC_A = 1.40         # A, LIMIT_I_FC_MAX bus-side, single sample (ino:2090)
LIM_A = min(P_MAX_BUS_A, GOV_A)        # binding steady ceiling of the FC-only bus
AUX_PLANT_A = sim.I_AUX_A              # 0.09 A HIL housekeeping load (hil_plant_sim.py:516)
AUX_IC1_A = 0.15       # A, IC1 design assumption (Table 8 note; facts_prior sec 7 "about 0.1-0.15 A")
C_VBUS_F = 35e-6       # F, VBUS proper (tools/hil_electrical.py:456); reproduces campaign G's 2.57 V/ms at 0.09 A
V_BATT_GATE = 8.0      # V, FC windows only below 8.0 V until gate S0-8b (IC1 sec 9.7 entry conditions)

# Purge facts: facts_prior sec 7 ONLY (ruling 2026-11-08: no further purge measurement)
PURGE_T_S = 10.34
PURGE_DUR_S = (0.100, 0.140)
# Interface parameter, not a measurement: time from the purge end until the predictor declares the
# stack able to carry a window again. The ideal predictor folds any recovery into its declared purge
# interval; 0.5 s is a SENSITIVITY value only (no primary source gives the recovery time).
T_REC_S = (0.0, 0.5)

# Exit chain (IC1 sec 9.7 exit steps 1-4; Table 11)
T_HOLDCHK = 0.00015              # s, exit hold check samples 50/150 us after the feed-drop write (Table 11)
T_EXIT_DRAIN = (0.0040, 0.01315)  # s, T_drain: 1.3-2.9 ms node + one 1.13 ms iteration (median case uses
                                  #    2.9 + 1.13); deadline 13.15 ms at the median loop (Table 11, calc6 s3/s9)
T_EXIT_P33 = (0.00452, 0.01315)   # s, pin 33 LOW confirm within 4 iterations: 4.52 ms median, 13.15 ms with
                                  #    one 9.76 ms gap (Table 11; facts_firmware sec 8 loop)
T_D_ON = (0.008, 0.012)           # s, RT1987 t_D_ON 8 ms typical, NO maximum; 12 ms = IC1 sensitivity (Table 8a)
T_SS_BUS = 0.0198                 # s, BT_BUS soft-start tON = (16/35)(100 nF/0.0023 - 100) us = 19.8 ms, CSS 100 nF;
                                  #    TRCB holds the switch off through the ramp onto a live bus (ino:4852-4862)
T_BLANK = 0.030                   # s, SHARE_CUT_SURVIVOR_BLANK_MS (ino:4869): firmware treats BT_BUS as dark until then
T_SHARE = (0.020, 0.050)          # s, share shift once BT conducts: ~20 ms share-loop feedback EMA (CLAUDE.md campaign
                                  #    G notes, F6); 50 ms = ESTIMATE from the 21-43 ms k_d slew entry (campaign I). BENCH.
T_DWELL = 0.250                   # s, SHARE_SELECTOR_DWELL_MS (ino:3466): selection changes at most every 250 ms

# Entry chain (IC1 sec 9.7 entry steps 3-7; Table 11)
T_ENTRY = (0.00452 + 0.020 + 0.0001 + 0.0028 + 0.00124 + 0.0036,   # p33 confirm + BT_CURRENT<0.2 A (<=20 ms)
           0.01315 + 0.020 + 0.0001 + 0.0061 + 0.00124 + 0.0036)   # + 100 us + D5 arm 2.8-6.1 ms + eFuse 1.24 + 3.6 ms
T_COLD = (0.065, 0.170)          # s, Ag105 cold start to current, prior measurement (facts_prior sec 6); BENCH S0-6
T_BRINGUP = (8.4, 11.7)          # s, Bring-Up without a keep-alive, 0.64 V/s ML0227 (IC1 Table 11; facts_ag105 s3),
                                 #    UNCONFIRMED for an isolated return
# VCHG-IN re-entry constraint (IC1 sec 9.7 entry conditions; Table 16 ERR_VCHG_FED: V_chg < 11 V outside a 1.0 s
# blanking after any pin-31 fall; VCHG-IN bleed tau 0.984 s, calc5 sec 5). Three readings of the entry rule:
TAU_VCHG = 0.984
T_VCHG_11 = TAU_VCHG * np.log(15.75 / 11.0)     # s from a 15.75 V single-source bus to 11 V
T_VCHG_BLANK = 1.0
T_MIN_USEFUL = 1.0     # s of charge current per window (1.25 C), a CHOICE: 2-6 x one hard-decel regen capture
                       # (0.2-0.66 C, facts_prior sec 6)

BAG_AUX_A = 0.02       # A, standstill bus total I_fc+I_batt in the bags; INA253 A1 zero error up to 0.1 A/channel
                       # (SLOS954A 7.5): a reading, not a proven aux load

DT = 0.02   # s, analysis grid = the 50 Hz /vehicle_state rate


def i_chg_bus(v_pack, eta, v_bus):
    """Bus current drawn by the Ag105 on the FC profile: (I_set + I_L) * V_pack / (eta * V_bus)."""
    return (I_SET_FC + I_L) * v_pack / (eta * v_bus)


def single_source_vbus(i_tot):
    return V_BUS_V0 - K_SINGLE * i_tot


def t_lead(k, with_share=True):
    """Lead from 'purge predicted' to purge onset: exit chain to BT_BUS conducting (+ share shift)."""
    t = T_HOLDCHK + T_EXIT_DRAIN[k] + T_EXIT_P33[k] + max(T_D_ON[k] + T_SS_BUS, T_BLANK)
    return t + (T_SHARE[k] if with_share else 0.0)


def t_post(k, reentry_rule, variant, lead):
    """Earliest window re-entry after the predicted purge END (purge end -> charge current flowing)."""
    pre = T_REC_S[0] if k == 0 else T_REC_S[1]
    if variant == "D":
        # D: the share must return to FC-only before BT_BUS can drop (entry step 5 waits for BT_CURRENT < 0.2 A).
        # Conservatively the pre-purge shift counts as a selection change, so the 250 ms selector dwell runs from
        # the shift command at (onset - T_SHARE): the re-selection may start (250 - T_SHARE - 140) ms after the
        # purge end, and then takes T_SHARE to complete.
        dwell_rel_end = T_DWELL - T_SHARE[k] - PURGE_DUR_S[1]
        pre = max(pre, dwell_rel_end) + T_SHARE[k]
    return pre, T_ENTRY[k]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def runs(mask):
    m = np.concatenate(([False], mask, [False])).astype(int)
    d = np.diff(m)
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]))


def purge_block(t, phase, k, variant, rule):
    """True where a window may NOT carry charge current: [onset - lead, re-entry point)."""
    lead = t_lead(k)
    dur = PURGE_DUR_S[1]          # the predictor's declared interval; 140 ms upper figure (facts_prior s7)
    pre, _ = t_post(k, rule, variant, lead)
    blk_after = dur + pre
    # VCHG-IN re-entry constraint, measured from the exit (onset - lead)
    if rule == "v11":
        blk_after = max(blk_after, T_VCHG_11 - lead)
    elif rule == "blank":
        blk_after = max(blk_after, T_VCHG_BLANK - lead)
    on = np.arange(phase, t[-1] + PURGE_T_S, PURGE_T_S)
    blk = np.zeros(len(t), bool)
    for o in on:
        blk |= (t >= o - lead) & (t < o + blk_after)
    return blk, lead + blk_after


def window_account(t, admissible, t_start_cost, t_min=T_MIN_USEFUL):
    """Charge seconds from contiguous admissible runs; each run pays t_start_cost before current flows."""
    dt = np.diff(np.append(t, t[-1] + DT))
    dt = np.minimum(dt, 0.1)
    chg = 0.0
    n_win = 0
    ends = []
    for a, b in runs(admissible):
        L = float(dt[a:b].sum())
        c = L - t_start_cost
        if c >= t_min:
            chg += c
            n_win += 1
            ends.append(b)
    return chg, n_win, ends


# ---------------------------------------------------------------------------
# Section 1
# ---------------------------------------------------------------------------
def section1():
    hdr(1, "FC-window bus budget: FC-only bus carries traction + aux + Ag105 input (FC profile)")
    print(f"LIM = min(P_MAX bus {P_MAX_BUS_A} A, governor {GOV_A} A) = {LIM_A} A; OC_FC {OC_FC_A} A single sample")
    print(f"Ag105 FC profile I_set {I_SET_FC} A + I_L {I_L} A = I_o {I_SET_FC + I_L} A (rating 2.5 A)")
    print("V_pack  eta   I_chg_bus  traction allowance (A, bus) at aux 0.09 / 0.15 A   P_trac allowance (W) at aux 0.15")
    for vp in (7.4, 7.8, 8.0, 8.2, 8.4):
        for eta in (ETA_CHG, ETA_CHG_LOW):
            vb = 15.9
            for _ in range(6):
                ic = i_chg_bus(vp, eta, vb)
                vb = single_source_vbus(ic + AUX_IC1_A + 0.2)
            a09 = LIM_A - ic - AUX_PLANT_A
            a15 = LIM_A - ic - AUX_IC1_A
            print(f"{vp:5.1f}  {eta:4.2f}  {ic:7.3f} A   {a09:+6.3f} / {a15:+6.3f}            "
                  f"{a15 * vb:+6.2f} W  (V_bus {vb:.2f} V)")
    print("Transient margin to OC_FC above LIM: %.3f A (single sample)" % (OC_FC_A - LIM_A))
    print("Traction the FC alone can carry once the charger input is dropped (exit step 1): LIM - aux = "
          f"{LIM_A - AUX_PLANT_A:.3f} / {LIM_A - AUX_IC1_A:.3f} A at aux 0.09 / 0.15 A")


# ---------------------------------------------------------------------------
# Section 2: predictor interface
# ---------------------------------------------------------------------------
def section2():
    hdr(2, "Predictor interface: lead time before onset and earliest re-entry (ideal predictor)")
    print(f"Purge facts used (facts_prior sec 7 only): period {PURGE_T_S} s, duration "
          f"{PURGE_DUR_S[0] * 1e3:.0f}-{PURGE_DUR_S[1] * 1e3:.0f} ms, floor ~1 V")
    for k, lab in ((0, "nominal"), (1, "worst ")):
        bt_on = max(T_D_ON[k] + T_SS_BUS, T_BLANK)
        print(f"[{lab}] exit: hold check {T_HOLDCHK * 1e3:.2f} + drain {T_EXIT_DRAIN[k] * 1e3:.2f} + p33 confirm "
              f"{T_EXIT_P33[k] * 1e3:.2f} + BT_BUS conduct max(t_D_ON {T_D_ON[k] * 1e3:.0f} + tON "
              f"{T_SS_BUS * 1e3:.1f}, blank {T_BLANK * 1e3:.0f}) = {bt_on * 1e3:.1f} ms")
        print(f"         T_lead,safety (BT conducting at onset) = {t_lead(k, False) * 1e3:6.1f} ms; "
              f"T_lead,ruling (+ share shift {T_SHARE[k] * 1e3:.0f} ms) = {t_lead(k) * 1e3:6.1f} ms")
        for var in ("P", "D"):
            pre, ent = t_post(k, None, var, t_lead(k))
            print(f"         re-entry ({var}): purge end + recovery/share/dwell {pre * 1e3:5.0f} ms + entry chain "
                  f"{ent * 1e3:.1f} ms + Ag105 cold start {T_COLD[k] * 1e3:.0f} ms (R_KA) = "
                  f"{(pre + ent + T_COLD[k]) * 1e3:6.0f} ms to charge current; without R_KA Bring-Up "
                  f"{T_BRINGUP[k]:.1f} s")
    print(f"VCHG-IN re-entry rule: V_chg < 11 V reached {T_VCHG_11 * 1e3:.0f} ms after the pin-31 fall (tau "
          f"{TAU_VCHG} s from 15.75 V); the ERR_VCHG_FED blanking lasts {T_VCHG_BLANK * 1e3:.0f} ms")
    print("Per-period blocked interval (exit lead + purge 140 ms + post) and charge-current time per 10.34 s period:")
    for rule in ("none", "v11", "blank"):
        for k, lab in ((0, "nominal"), (1, "worst")):
            for var in ("P", "D"):
                lead = t_lead(k)
                pre, ent = t_post(k, rule, var, lead)
                after = PURGE_DUR_S[1] + pre
                if rule == "v11":
                    after = max(after, T_VCHG_11 - lead)
                elif rule == "blank":
                    after = max(after, T_VCHG_BLANK - lead)
                blocked = lead + after
                for ka, tstart in (("R_KA", ent + T_COLD[k]), ("noKA", ent + T_BRINGUP[k])):
                    chg = max(0.0, PURGE_T_S - blocked - tstart)
                    print(f"   rule {rule:5s} {lab:7s} {var} {ka}: blocked {blocked * 1e3:6.0f} ms, start cost "
                          f"{tstart * 1e3:7.0f} ms, charge {chg:6.3f} s/period = duty {chg / PURGE_T_S:.3f}")


# ---------------------------------------------------------------------------
# Section 3: variant P
# ---------------------------------------------------------------------------
def section3():
    hdr(3, "Variant P (parked, State 1 / 98): mean pack current at I_set 1.25 A (CC; windows only below 8.0 V)")
    for rule in ("none", "v11", "blank"):
        for k, lab in ((0, "nominal"), (1, "worst")):
            lead = t_lead(k)
            pre, ent = t_post(k, rule, "P", lead)
            after = PURGE_DUR_S[1] + pre
            if rule == "v11":
                after = max(after, T_VCHG_11 - lead)
            elif rule == "blank":
                after = max(after, T_VCHG_BLANK - lead)
            for ka, tstart in (("R_KA fitted", ent + T_COLD[k]), ("no R_KA (Bring-Up)", ent + T_BRINGUP[k])):
                chg = max(0.0, PURGE_T_S - lead - after - tstart)
                i = I_SET_FC * chg / PURGE_T_S
                print(f"   rule {rule:5s} {lab:7s} {ka:20s}: {chg:6.3f} s per period, mean {i:.3f} A = {i:.3f} Ah/h"
                      f" ({i * 1e3 / 60:.1f} mAh/min)")
    print("Bench-supply windows (no purge): limited by FC_CHG_MAX_MS 30 s + FC_CHG_COOLDOWN_MS 2 s (ino:2633-2634):"
          f" R_KA {I_SET_FC * (30 - T_ENTRY[0] - T_COLD[0]) / 32:.3f} A mean")


# ---------------------------------------------------------------------------
# Section 4: drive cycles
# ---------------------------------------------------------------------------
def csv_profile(path):
    rows = np.loadtxt(path, delimiter=",", skiprows=1)
    return [(float(a), float(b)) for a, b in rows]


def plant_cycle(prof):
    t_end = prof[-1][0]
    times = np.arange(0.0, t_end + 1e-9, DT)
    meta = {"ems_v_profile": prof}
    v, a, p_dem, v_bus, i_total, cruise, i_regen = dpt.build_demand(
        "purge-demand-study", meta, times, DT, aux_preload_a=0.0, loss_map=None)
    i_trac = i_total - AUX_PLANT_A
    f_coul = np.where(v > sim.V_STICTION, sim.F_COULOMB, np.where(v < -sim.V_STICTION, -sim.F_COULOMB, 0.0))
    force = sim.M_EFF * a + f_coul + sim.B_EFF * v
    braking = (force * v < 0) & (np.abs(v) > sim.V_STICTION)
    return times, v, i_trac, braking


def run_variant(times, i_dem, braking, v_pack, eta, k, variant, rule, phases, still=None, request=None,
                brake_exits=False):
    """Mean over purge phases: (charge s, windows, traction exits, capped exits, purge-free fraction, demand-OK)."""
    ic = i_chg_bus(v_pack, eta, single_source_vbus(i_dem + 1.0))
    dem_ok = (i_dem + ic) <= LIM_A
    # a D window that opens on a demand fall (not after a purge) also shifts the share to FC-only first
    t_start = T_ENTRY[k] + T_COLD[k] + (T_SHARE[k] if variant == "D" else 0.0)
    T_exit_bt = t_lead(k, False)
    out = []
    for ph in phases:
        blk, blocked = purge_block(times, ph, k, variant, rule)
        adm = dem_ok & ~blk
        if brake_exits:
            adm &= ~braking
        if still is not None:
            adm &= still
        if request is not None:
            adm &= request
        chg, nw, ends = window_account(times, adm, t_start)
        n_tr = n_cap = 0
        for b in ends:
            if b < len(times) and not blk[b]:
                n_tr += 1
                j = np.searchsorted(times, times[b] + T_exit_bt)
                if np.any(i_dem[b:j + 1] > LIM_A):          # FC alone cannot carry traction + aux until BT conducts
                    n_cap += 1
        out.append((chg, nw, n_tr, n_cap, 1.0 - blocked / PURGE_T_S, dem_ok.mean()))
    o = np.array(out)
    return o.mean(axis=0), o.min(axis=0), o.max(axis=0)


def bag_fit(bags):
    """Least-squares traction scale K: bag total - BAG_AUX = K * plant traction, at steady cruise."""
    xs, ys = [], []
    rows = []
    for vt in (1.0, 1.5, 2.0, 2.9):
        meas = []
        for name, t, vs, et, ec, VS, EC in bags:
            v = vs[:, VS.index("v_actual")]
            itot = vs[:, VS.index("I_fc")] + vs[:, VS.index("I_batt")]
            vsm = np.convolve(v, np.ones(50) / 50, mode="same")
            acc = np.gradient(vsm, DT)
            sel = (np.abs(vsm - vt) < 0.05) & (np.abs(acc) < 0.05) & (vs[:, VS.index("error_code")] == 0)
            meas.extend(itot[sel].tolist())
        f = sim.F_COULOMB + sim.B_EFF * vt
        ipl = f * vt / (sim.ETA_BOOST * 15.9)
        if meas:
            m = float(np.median(meas))
            rows.append((vt, m, len(meas), ipl))
            xs.append(ipl); ys.append(m - BAG_AUX_A)
    xs = np.array(xs); ys = np.array(ys)
    K = float(xs @ ys / (xs @ xs))
    return K, rows


def section4(K):
    hdr(4, "Drive cycles: variant D (State 2 windows) and D-s (State-2 standstill only) on the HIL plant demand model")
    print("Plant model: gen_dp_ems_table.build_demand(loss_map=None): F = M_EFF a + F_C sgn v + B_EFF v,"
          " p_mech = max(0, F v), I_trac = p_mech/(ETA_BOOST V_bus); M_EFF %.2f kg, F_C %.2f N, B_EFF %.3f N s/m, "
          "ETA_BOOST %.2f" % (sim.M_EFF, sim.F_COULOMB, sim.B_EFF, sim.ETA_BOOST))
    print(f"Demand models: plant (traction + 0.09 A); IC1 (traction + 0.15 A); bag-calibrated ({BAG_AUX_A} A + "
          f"{K:.3f} x traction, fit in section 5)")
    print("Purge schedule: synthetic, period 10.34 s, 20 phases swept; reported value = phase mean (min-max)")
    print("Variant P on a drive cycle is 0 by definition (State 2 throughout, ino:7919-7959).")
    cycles = [
        ("61 s cycle (ems-dp-replay)", sim.SCENARIOS["ems-dp-replay"]["ems_v_profile"]),
        ("FTP-75 rig slice (ems-ftp75-*)", sim.SCENARIOS["ems-ftp75-dp"]["ems_v_profile"]),
        ("ftp75c compressed (ems-ftp75c-*)", sim.SCENARIOS["ems-ftp75c-dp"]["ems_v_profile"]),
        ("UDDS_trimmed_3.5mps.csv (Pi)", csv_profile(os.path.join(REPO, "references", "drive_cycles",
                                                                  "UDDS_trimmed_3.5mps.csv"))),
        ("RegenTest_v2_lowspeed.csv (Pi)", csv_profile(os.path.join(REPO, "references", "drive_cycles",
                                                                    "RegenTest_v2_lowspeed.csv"))),
        ("RegenTest_decel_sweep.csv (Pi)", csv_profile(os.path.join(REPO, "references", "drive_cycles",
                                                                    "RegenTest_decel_sweep.csv"))),
    ]
    phases = np.linspace(0.0, PURGE_T_S, 20, endpoint=False)
    summary = []
    for name, prof in cycles:
        times, v, i_trac, braking = plant_cycle(prof)
        T = times[-1]
        still = np.abs(v) <= sim.V_STICTION
        p_dem = 15.9 * (i_trac + AUX_PLANT_A)
        print(f"\n-- {name}: {T:.0f} s, peak v {v.max():.2f} m/s, standstill {still.mean() * 100:.1f} %, "
              f"braking {braking.mean() * 100:.2f} % ({braking.sum() * DT:.2f} s), "
              f"I_trac p50/p90/max {np.percentile(i_trac, [50, 90, 100]).round(3)} A; "
              f"P_dem<3 W (SDP v7 charge bins 0-2) {np.mean(p_dem < 3.0) * 100:.1f} %, <12 W {np.mean(p_dem < 12.0) * 100:.1f} %")
        cases = (("plant 0.09", i_trac + AUX_PLANT_A), ("IC1 0.15", i_trac + AUX_IC1_A),
                 ("bag-cal", BAG_AUX_A + K * i_trac))
        for lab_d, i_dem in cases:
            for vp in (7.4, 7.8):
                for k, case in ((0, "nominal"), (1, "worst")):
                    eta = ETA_CHG if k == 0 else ETA_CHG_LOW
                    for rule in ("none", "blank"):
                        mD, lo, hi = run_variant(times, i_dem, braking, vp, eta, k, "D", rule, phases)
                        mS, _, _ = run_variant(times, i_dem, braking, vp, eta, k, "D", rule, phases, still=still)
                        ah = mD[0] * I_SET_FC / 3.6
                        print(f"   {lab_d:10s} Vp {vp:.1f} {case:7s} rule {rule:5s}: demand-OK {mD[5] * 100:5.1f} %, "
                              f"purge-free {mD[4] * 100:5.1f} % | D: {mD[1]:4.1f} win, charge {mD[0]:6.1f} s "
                              f"({mD[0] / T * 100:5.1f} %; {lo[0]:.0f}-{hi[0]:.0f} s) = {ah:6.2f} mAh, mean "
                              f"{mD[0] * I_SET_FC / T:.3f} A, traction exits {mD[2]:4.1f} (capped {mD[3]:3.1f}) | "
                              f"D-s: {mS[0]:6.1f} s = {mS[0] * I_SET_FC / 3.6:5.2f} mAh")
                        summary.append((name, lab_d, vp, case, rule, mD[0], T, mS[0]))
        # Stage-2 policy: a braking stage exits the FC window (to permit a regen window, OR-7) - plant 0.09 A, 7.4 V
        mB, _, _ = run_variant(times, i_trac + AUX_PLANT_A, braking, 7.4, ETA_CHG, 0, "D", "none", phases,
                               brake_exits=True)
        m0, _, _ = run_variant(times, i_trac + AUX_PLANT_A, braking, 7.4, ETA_CHG, 0, "D", "none", phases)
        print(f"   braking exits the window (Stage 2 policy), plant 0.09 Vp 7.4 nominal: charge {mB[0]:.1f} s vs "
              f"{m0[0]:.1f} s when the window rides through braking ({(m0[0] - mB[0]):.1f} s lost)")
    return summary


# ---------------------------------------------------------------------------
# Section 5: Pi sessions
# ---------------------------------------------------------------------------
def load_bags():
    import scout_bags as sb
    out = []
    for p in sorted(glob.glob(os.path.join(REPO, "logs", "rosbags", "rosbag_*"))):
        if not glob.glob(os.path.join(p, "*.mcap")):
            continue
        b = sb.load_bag(p)
        out.append((os.path.basename(p), b["vs_t"], b["vs"], b["ec_t"], b["ec"], sb.VS, sb.EC))
    return out


def section5(bags, K, rows_fit):
    hdr(5, "Pi sessions: variant D on the measured bus current I_fc + I_batt (synthetic purge schedule)")
    print("Plant vs bag at steady cruise (|dv/dt| < 0.05 m/s^2 over 1 s, no error):")
    for vt, m, n, ipl in rows_fit:
        print(f"   v {vt:.1f} m/s: bag median total {m:.3f} A (n={n}); plant traction {ipl:.3f} A; "
              f"ratio (total - {BAG_AUX_A}) / traction = {(m - BAG_AUX_A) / ipl:.2f}")
    print(f"   least-squares traction scale K = {K:.3f}")
    phases = np.linspace(0.0, PURGE_T_S, 10, endpoint=False)
    print("\nbag | case | live Run s | demand-OK % | Vb<8.0 % | D charge s (win) = mAh | D & Vb<8.0 s = mAh | "
          "D & Vb<8.0 & charge_goal s = mAh | D-s & Vb<8.0 s | goal>0.05 % | braking % | still % | H-20")
    rows = []
    for name, t, vs, et, ec, VS, EC in bags:
        c = lambda n: vs[:, VS.index(n)]
        sw = c("switch_state").astype(int)
        err = c("error_code")
        live = ((sw & 0x04) != 0) & (err == 0)
        if live.sum() < 50:
            print(f"{name:44s} no live Run samples")
            continue
        v = c("v_actual")
        itot = c("I_fc") + c("I_batt")
        vb = c("V_batt")
        vsm = np.convolve(v, np.ones(10) / 10, mode="same")
        acc = np.gradient(vsm, t)
        a_coast = (sim.F_COULOMB + sim.B_EFF * np.abs(vsm)) / sim.M_EFF
        braking = (vsm > 0.05) & (acc < -(a_coast + 0.1))
        still = np.abs(v) <= 0.02
        if len(et):
            idx = np.clip(np.searchsorted(et, t) - 1, 0, len(et) - 1)
            req = ec[idx, EC.index("charge_goal")] > 0.05
        else:
            req = np.zeros(len(t), bool)
        h20 = float(np.median(c("V_fc")[live])) > 9.5      # bench-supply bags sit near 8.5 V flat
        gate = vb < V_BATT_GATE
        T = float(np.minimum(np.diff(np.append(t, t[-1] + DT)), 0.1)[live].sum())
        for k, case in ((0, "nominal"), (1, "worst")):
            eta = ETA_CHG if k == 0 else ETA_CHG_LOW
            res = []
            for sel_extra in (np.ones(len(t), bool), gate, gate & req, gate & still):
                vals = []
                for ph in phases:
                    ic = i_chg_bus(vb, eta, single_source_vbus(itot + 1.0))
                    dem_ok = (itot + ic) <= LIM_A
                    blk, _ = purge_block(t, ph, k, "D", "none")
                    adm = live & dem_ok & ~blk & sel_extra
                    tst = T_ENTRY[k] + T_COLD[k] + T_SHARE[k]
                    chg, nw, _ = window_account(t, adm, tst)
                    vals.append((chg, nw))
                res.append(np.mean(np.array(vals), axis=0))
            dok = float(((itot + i_chg_bus(vb, eta, single_source_vbus(itot + 1.0))) <= LIM_A)[live].mean())
            rows.append((name, case, T, dok, gate[live].mean(), res, req[live].mean(), braking[live].mean(),
                         still[live].mean(), h20))
            print(f"{name[7:44]:37s} {case[:3]} {T:6.0f} {dok * 100:5.1f} {gate[live].mean() * 100:5.1f} | "
                  f"{res[0][0]:6.1f} ({res[0][1]:4.1f}) = {res[0][0] * I_SET_FC / 3.6:5.2f} | "
                  f"{res[1][0]:6.1f} = {res[1][0] * I_SET_FC / 3.6:5.2f} | {res[2][0]:6.1f} = "
                  f"{res[2][0] * I_SET_FC / 3.6:5.2f} | {res[3][0]:6.1f} | {req[live].mean() * 100:5.1f} | "
                  f"{braking[live].mean() * 100:4.1f} | {still[live].mean() * 100:4.1f} | {'Y' if h20 else 'n'}")
    for case in ("nominal", "worst"):
        for only_h20 in (False, True):
            sel = [r for r in rows if r[1] == case and (r[9] or not only_h20)]
            T = sum(r[2] for r in sel)
            parts = [sum(r[5][i][0] for r in sel) for i in range(4)]
            lab = "H-20 bags" if only_h20 else "all bags "
            print(f"TOTAL {case:7s} {lab}: live {T:.0f} s; D {parts[0]:.0f} s ({parts[0] / T * 100:.1f} %, "
                  f"{parts[0] * I_SET_FC / T:.3f} A mean); D&Vb<8 {parts[1]:.0f} s ({parts[1] / T * 100:.1f} %, "
                  f"{parts[1] * I_SET_FC / T:.3f} A); D&Vb<8&goal {parts[2]:.0f} s ({parts[2] / T * 100:.1f} %, "
                  f"{parts[2] * I_SET_FC / T:.3f} A, {parts[2] * I_SET_FC / 3.6:.1f} mAh); D-s&Vb<8 {parts[3]:.0f} s "
                  f"({parts[3] / T * 100:.1f} %)")
            req_s = sum(r[6] * r[2] for r in sel)
            print(f"      EMS request time (charge_goal > 0.05, live): {req_s:.0f} s; D&Vb<8&goal charge = "
                  f"{parts[2] / req_s * 100 if req_s else 0:.1f} % of it")
    return rows


# ---------------------------------------------------------------------------
# Section 6: braking, traction requests, collapse rate
# ---------------------------------------------------------------------------
def section6():
    hdr(6, "Braking inside an FC window; bus collapse rate on an unpredicted purge")
    print("Collapse rate dV/dt = I_load / C_VBUS, C_VBUS %.0f uF (hil_electrical.py:456); campaign G 2.57 V/ms at "
          "0.09 A reproduces: %.2f V/ms" % (C_VBUS_F * 1e6, 0.09 / C_VBUS_F / 1e3))
    for lab, i in (("aux only 0.09 A", 0.09),
                   ("parked window: charger 0.83-1.04 A + aux 0.15 A", 1.075),
                   ("in-drive window at the LIM ceiling 1.247 A", LIM_A)):
        rate = i / C_VBUS_F / 1e3                     # V/ms
        t12 = (15.9 - 12.0) / rate                    # ms
        print(f"   {lab:50s}: {rate:6.2f} V/ms; 15.9 -> 12.0 V (LIMIT_V_BUS_MIN) in {t12 * 1e3:6.0f} us; BT_BUS "
              f"conduction {(T_D_ON[0] + T_SS_BUS) * 1e3:.1f} ms typical = {(T_D_ON[0] + T_SS_BUS) * 1e3 / t12:.0f} x longer")
    print("Upper bound on rate: assumes the FC boost stops delivering at once at onset (stack below the TPS61288 2.0 V"
          " VIN floor); the dip slope is not resolved at 50 Hz (BENCH).")
    print("Regen pulse vs exit chain: pulse rise 19-47 ms after the command (facts_prior s6); FC-window exit to"
          f" bonded {(T_HOLDCHK + T_EXIT_DRAIN[0] + T_EXIT_P33[0]) * 1e3:.1f}-"
          f"{(T_HOLDCHK + T_EXIT_DRAIN[1] + T_EXIT_P33[1]) * 1e3:.1f} ms, then the regen-window arm (OR-7: no direct"
          " FC -> regen transition)")


def main():
    section1()
    section2()
    section3()
    bags = load_bags()
    K, rows_fit = bag_fit(bags)
    section4(K)
    section5(bags, K, rows_fit)
    section6()


if __name__ == "__main__":
    main()
