"""Sim 4, section 5.6a: brief T2 (VBUS tap) interruptions, H1 inhibit latency and the C107-alone false-trip check,
for the five C106/C107/C108 options of Table 5.5 (2026-11-15, second review R2-LOG-0, R2-SIM-1, R2-SIM-2).

python t2brief.py              runs the three families below and writes decks/, results/ and figures/ files
python t2brief.py int          runs one family only (int, intx, intl, lat, thr, rise, fig); 'agg' only re-aggregates

Families (decks under decks/t2int, decks/t2lat, decks/t2thr, decks/t2rise):
  t2int  T2 opened at 1 ms in Run cruise (P5 HIGH, /CE LOW, V-MOT = VBUS, REGN 5.0 V) and re-connected after
         2, 5, 10, 15, 20, 30 or 40 us, or never ('perm'); VBUS 14.5 / 15.9 / 16.4 V; corners early / nom / late;
         seven comparator-delay sets (fixed tPD pairs and the overdrive model, as run.py t2race/t2skew/t2od).
  t2lat  H1 inhibit latency: regen burst (H1U released, V-MOT 18.6 V) followed by a V-MOT fall at I / C_VMOT_MIN with
         I = 1.25 A and 1.80 A and C_VMOT_MIN = 0.4 mF (round3/calc/r3_calc.py H.13), down to VBUS - 35 mV
         (D-MT-EN conduction, r3_calc.py H.13), then held there.
  t2thr  static H1 fall threshold of the base option per VBUS and corner (slow 0.2 V/ms V-MOT ramp), used to split
         the t2lat time into a circuit latency L and the H.13 window.
  t2rise false-H1-trip check: VBUS = V-MOT rising at the H.6 slew 12 V/ms (and 24 V/ms for C107 alone) from 0, 13.0,
         14.5 or 15.2 V to 15.9 or 16.4 V, P5 HIGH (worst case: /CE LOW).

Entry point stays run.py for the other families; this script reuses its deck builder, corner sets and checker.
"""
import csv
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_argv = sys.argv[:]
sys.argv = [sys.argv[0]]          # run.py reads --quick from sys.argv; this script always uses the full corner set
import run as R  # noqa: E402
import analyse as A  # noqa: E402
sys.argv = _argv

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RES, FIG = R.RES, R.FIG
for extra in ("m_vmot", "m_vbus"):
    if extra not in R.SAVE:
        R.SAVE.append(extra)

PRE = R.PRE
T_EV = 1e-3
WORKERS = 12

# options of Table 5.5 (values in F); 'base' = as built (gen/netlist.py lines 166, 171, 177)
OPTS = {"base": {}, "C108_470p": dict(C108=470e-12), "C107_4n7_only": dict(C107=4.7e-9),
        "C106C107_4n7": dict(C106=4.7e-9, C107=4.7e-9), "C106C107_10n": dict(C106=10e-9, C107=10e-9)}
OPT_LABEL = {"base": "as built (470 p / 470 p / 1.0 n)", "C108_470p": "C108 = 470 pF",
             "C107_4n7_only": "C107 alone = 4.7 nF", "C106C107_4n7": "C106 = C107 = 4.7 nF",
             "C106C107_10n": "C106 = C107 = 10 nF"}
SLOW = ("C107_4n7_only", "C106C107_4n7", "C106C107_10n")   # options with a 235-501 us filter: longer runs

# comparator-delay sets (SBOS300C Table 6.10: tPD 2 us typical, 4 us maximum at VOD 100 mV; Figures 8-12/8-13 for
# the overdrive model); the same sets as run.py TPD_PAIRS and OD_SETS, reduced to seven
DELAYS = {"f2": dict(h1=2e-6, uvb=2e-6), "f4": dict(h1=4e-6, uvb=4e-6), "f4u2": dict(h1=4e-6, uvb=2e-6),
          "f2u4": dict(h1=2e-6, uvb=4e-6), "f2u8": dict(h1=2e-6, uvb=8e-6), "od4": dict(tpd100=4e-6),
          "odmix": dict(tpd100=2e-6, h1_100=1.3e-6, uvb_100=4e-6)}
DURS = (2e-6, 5e-6, 10e-6, 15e-6, 20e-6, 30e-6, 40e-6, None)   # None = permanent open
VBUSES = (14.5, 15.9, 16.4)
CORNERS = ("early", "nom", "late")

C_VMOT_MIN = 0.4e-3          # r3_calc.py H.13 (C_VMOT_MIN)
VFWD = 0.035                 # r3_calc.py H.13: D-MT-EN conducts at V-MOT = VBUS - 35 mV
V_START = 18.6               # regen-burst V-MOT before the fall (above the H1 rise maximum 18.127 V, sim 3 Table 6)
CURRENTS = (1.25, 1.80)
LAT_VBUS = (14.5, 15.5, 15.9, 16.4)
LAT_DELAYS = ("f2", "f4", "od4")
THR_SLOPE = 0.2e3            # V/s, slow ramp for the static threshold
SLEW_RISE = 12e3             # V/s, H.6 (design doc line 3402: 12 V/ms)

JOBS = []


def tstop_int(on, dur):
    """Run end: 1 ms (470 pF options) or 3 ms (4.7 nF and 10 nF options) after the opening; interruptions longer than
    0.5 ms (family t2intl) add their own duration, so that the recovery after the re-connection is covered."""
    extra = dur if (dur is not None and dur > 0.5e-3) else 0.0
    return T_EV + extra + (3.0e-3 if on in SLOW else 1.0e-3)


DURS_X = (50e-6, 70e-6, 100e-6, 150e-6, 200e-6, 300e-6)
DELAYS_X = ("f2", "f2u8", "od4", "odmix")


def fam_int(family="t2int", durs=DURS, opts=tuple(OPTS), delays=tuple(DELAYS)):
    """family t2intx (check pass): the same case at 50-300 us for the four delay sets of DELAYS_X, to find the end of
    the hazardous interruption band of each option (the formal 2-40 us sweep is family t2int)."""
    for on in opts:
        ov = OPTS[on]
        for dur in durs:
            for vb in VBUSES:
                for cn in CORNERS:
                    for dn in delays:
                        dk = DELAYS[dn]
                        if dur is None:
                            jt = {"1": [(0, 1), (T_EV, 1), (T_EV + 1e-8, 0)]}
                            dlab = "perm"
                        else:
                            jt = {"1": [(0, 1), (T_EV, 1), (T_EV + 1e-8, 0), (T_EV + dur, 0), (T_EV + dur + 1e-8, 1)]}
                            dlab = "%gus" % (dur * 1e6)
                        name = "int_%s_%s_%gV_%s_%s" % (on, dlab, vb, cn, dn)
                        ts = tstop_int(on, dur)
                        c = R.D.Case(name, ts, t_max=0.5e-6, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, vb)],
                                     vmot=[(0, vb)], regn=[(0, 5.0)], pins=R.state_pins("cruise"), jtap=jt,
                                     overrides=dict(ov), **R._tpd_kw(cn, **dk))
                        JOBS.append(dict(family=family, case=c, window=(T_EV, ts),
                                         expect={k: "safe" for k in R.T2_OUT}, allow_trans=100e-6, post=None,
                                         info=dict(option=on, dur_us=dlab, vbus=vb, corner=cn, delay=dn)))


def fam_lat():
    for on, ov in OPTS.items():
        for I in CURRENTS:
            s = I / C_VMOT_MIN
            for vb in LAT_VBUS:
                v_end = vb - VFWD
                t_end = T_EV + (V_START - v_end) / s
                ts = t_end + 1.2e-3
                for cn in CORNERS:
                    for dn in LAT_DELAYS:
                        name = "lat_%s_%gA_%gV_%s_%s" % (on, I, vb, cn, dn)
                        c = R.D.Case(name, ts, t_max=0.5e-6, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, vb)],
                                     vmot=[(0, V_START), (T_EV, V_START), (t_end, v_end)], regn=[(0, 5.0)],
                                     pins=R.state_pins("cruise"), overrides=dict(ov), **R._tpd_kw(cn, **DELAYS[dn]))
                        JOBS.append(dict(family="t2lat", case=c, window=(T_EV, ts), expect={}, allow_trans=100e-6,
                                         post=None, info=dict(option=on, I_A=I, slope_V_per_ms=s / 1e3, vbus=vb,
                                                              corner=cn, delay=dn, t_cond_us=(t_end - T_EV) * 1e6)))


def fam_thr():
    for vb in LAT_VBUS:
        v_end = vb - VFWD
        t_end = T_EV + (V_START - v_end) / THR_SLOPE
        for cn in CORNERS:
            name = "thr_%gV_%s" % (vb, cn)
            c = R.D.Case(name, t_end + 0.2e-3, t_max=2e-6, preroll=PRE, v3=[(0, 3.3)], vbus=[(0, vb)],
                         vmot=[(0, V_START), (T_EV, V_START), (t_end, v_end)], regn=[(0, 5.0)],
                         pins=R.state_pins("cruise"), **R._tpd_kw(cn, **DELAYS["f2"]))
            JOBS.append(dict(family="t2thr", case=c, window=(T_EV, t_end), expect={}, allow_trans=100e-6, post=None,
                             info=dict(option="base", vbus=vb, corner=cn, delay="f2")))


def fam_rise():
    for on, ov in OPTS.items():
        slews = (SLEW_RISE, 2 * SLEW_RISE) if on == "C107_4n7_only" else (SLEW_RISE,)
        for sl in slews:
            for v0 in (0.0, 13.0, 14.5, 15.2):
                for v1 in (15.9, 16.4):
                    t1 = T_EV + (v1 - v0) / sl
                    ts = t1 + (3.0e-3 if on in SLOW else 1.5e-3)
                    for cn in CORNERS:
                        for dn in ("f2", "odmix"):
                            name = "rise_%s_%gVms_%g_%gV_%s_%s" % (on, sl / 1e3, v0, v1, cn, dn)
                            pts = [(0, v0), (T_EV, v0), (t1, v1)]
                            c = R.D.Case(name, ts, t_max=0.5e-6, preroll=PRE, v3=[(0, 3.3)], vbus=pts, vmot=pts,
                                         regn=[(0, 5.0)], pins=R.state_pins("cruise"), overrides=dict(ov),
                                         **R._tpd_kw(cn, **DELAYS[dn]))
                            JOBS.append(dict(family="t2rise", case=c, window=(T_EV, ts),
                                             expect={k: "safe" for k in R.T2_OUT}, allow_trans=100e-6, post=None,
                                             info=dict(option=on, slew_V_per_ms=sl / 1e3, v0=v0, v1=v1, corner=cn,
                                                       delay=dn)))


# ---------------------------------------------------------------------------------------------------------------
def _dur_where(t, mask):
    """Total time (s) over which mask holds, sample-and-hold on the left sample."""
    if t.size < 2:
        return 0.0
    return float(np.sum(np.diff(t)[mask[:-1]]))


def _first(t, mask):
    i = np.where(mask)[0]
    return float(t[i[0]]) if i.size else float("nan")


def _last_true_end(t, mask):
    i = np.where(mask)[0]
    if i.size == 0:
        return float("nan")
    return float(t[min(i[-1] + 1, t.size - 1)])


def metrics(job, w):
    t = w["time"]
    k = t >= T_EV - 1e-12
    t = t[k]
    il = w["e_ilim_hold"][k]
    ce = w["e_nce_drv"][k]
    regn = w["e_regn"][k] > A.REGN_ON
    c3 = w["c_3v3"][k]
    h1 = w["c_h1"][k] > 0.5 * c3
    uvb = w["c_uvb"][k] > 0.5 * c3
    h1u = w["c_h1u"][k] > A.vih(c3)
    rel = w["c_ilim_rel"][k] > A.vil(c3)
    ce_low = regn & (ce < A.VIL_CE)
    out = dict(ilim_peak_V=float(np.max(il)), ce_max_V=float(np.max(ce)),
               t_above_1v0_ceLOW_us=_dur_where(t, (il > A.VIH_ILIM) & ce_low) * 1e6,
               t_above_0v75_ceLOW_us=_dur_where(t, (il > A.VIL_ILIM) & ce_low) * 1e6,
               t_rel_us=_dur_where(t, rel) * 1e6, t_h1u_us=_dur_where(t, h1u) * 1e6,
               n_1v0_episodes=len(A.runs(t, (il > A.VIH_ILIM) & ce_low)),
               end_ilim_V=float(il[-1]), end_h1=int(h1[-1]), end_uvb=int(uvb[-1]))
    fam = job["family"]
    if fam in ("t2lat", "t2thr") or job["case"].name.startswith(("lat_", "thr_")):
        vm = w["m_vmot"][k]
        hold = il < A.VIL_ILIM
        out["ilim_at_ev_V"] = float(il[0])
        # the release must exist before the fall (H1U released by the regen burst)
        out["released_at_ev"] = int(il[0] > A.VIH_ILIM)
        out["t_hold_us"] = (_last_true_end(t, ~hold) - T_EV) * 1e6
        out["t_rel_drop_us"] = (_last_true_end(t, rel) - T_EV) * 1e6
        out["t_h1_fall_us"] = (_last_true_end(t, h1) - T_EV) * 1e6
        if fam == "t2thr":
            i = np.where(h1)[0]
            th = float(t[min(i[-1] + 1, t.size - 1)]) if i.size else float("nan")
            v_at = float(np.interp(th, t, vm))
            # correct for the base IN+ filter lag (50.1 kOhm x 470 pF, tau 23.5 us) and the 2 us comparator delay
            out["v_fall_static_V"] = v_at + THR_SLOPE * (50.1e3 * 470e-12 + 2e-6)
    return out


def execute(job):
    row, w = R.execute(job)
    if w is not None:
        row.update(metrics(job, w))
    return row


def run_jobs(jobs):
    rows = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, row in enumerate(ex.map(execute, jobs)):
            rows.append(row)
            if (i + 1) % 50 == 0 or i + 1 == len(jobs):
                print("  %d/%d decks (%.0f s)" % (i + 1, len(jobs), time.time() - t0), flush=True)
    return rows


def clean_family(fam):
    d = os.path.join(R.DECKS, fam)
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.endswith(".cir"):
                os.remove(os.path.join(d, f))


# ---------------------------------------------------------------------------------------------------------------
def load(fam):
    p = os.path.join(RES, fam + ".csv")
    return list(csv.DictReader(open(p, encoding="utf-8"))) if os.path.exists(p) else []


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def rng(v, fmt="%.2f"):
    v = [x for x in v if x == x]
    if not v:
        return "-"
    return fmt % min(v) if abs(max(v) - min(v)) < 1e-12 else (fmt + "-" + fmt) % (min(v), max(v))


# H.13 windows: H1 fall minimum per VBUS. r3 basis (r3_calc_out.txt lines 154-156, back-computed from the allowance +
# 46 us of deductions at 4.5 V/ms) and the sim 3 worst case with TCR (sim/comparators/RESULTS.md Table 4 lines 172-176)
FALL_MIN = {15.5: dict(r3=16.379), 15.9: dict(r3=16.810, sim3=16.732), 16.4: dict(r3=17.340, sim3=17.260)}
TB06 = 150.0   # us, T-B-06 ILIM-path criterion (design doc line 3545)


def aggregate():
    out = []
    # ---- interruptions: per option and duration, over VBUS x corners x delay sets
    ri = [r for r in load("t2int") + load("t2intx") + load("t2intl") if r.get("verdict") != "SIM_FAIL"]
    nfail_i = sum(1 for r in load("t2int") + load("t2intx") + load("t2intl") if r.get("verdict") == "SIM_FAIL")
    agg_i = []
    durs = ["2us", "5us", "10us", "15us", "20us", "30us", "40us", "50us", "70us", "100us", "150us", "200us", "300us",
            "1000us", "3000us", "perm"]
    for on in OPTS:
        for d in durs:
            sel = [r for r in ri if r["option"] == on and r["dur_us"] == d]
            if not sel:
                continue
            fams = sorted(set(r["family"] for r in sel))
            pk = [f(r["ilim_peak_V"]) for r in sel]
            worst = max(sel, key=lambda r: f(r["ilim_peak_V"]))
            agg_i.append(dict(option=on, dur=d, family="+".join(fams), decks=len(sel), peak_V=rng(pk, "%.3f"),
                              peak_typ_f2_V=rng([f(r["ilim_peak_V"]) for r in sel if r["delay"] == "f2"], "%.3f"),
                              n_above_1v0=sum(p > 1.0 for p in pk), n_above_0v75=sum(p > 0.75 for p in pk),
                              t_above_1v0_max_us=round(max(f(r["t_above_1v0_ceLOW_us"]) for r in sel), 1),
                              t_above_0v75_max_us=round(max(f(r["t_above_0v75_ceLOW_us"]) for r in sel), 1),
                              rel_max_us=round(max(f(r["t_rel_us"]) for r in sel), 1),
                              ce_max_V=round(max(f(r["ce_max_V"]) for r in sel), 3),
                              end_held=sum(f(r["end_ilim_V"]) < 0.75 for r in sel),
                              worst_case=worst["case"]))
    R.write_csv(os.path.join(RES, "agg_t2int.csv"), agg_i)
    # ---- static threshold per VBUS, corner
    thr = {(f(r["vbus"]), r["corner"]): f(r["v_fall_static_V"]) for r in load("t2thr")}
    # ---- latency
    rl = [r for r in load("t2lat") if r.get("verdict") != "SIM_FAIL"]
    agg_l = []
    for on in OPTS:
        for I in CURRENTS:
            for vb in LAT_VBUS:
                sel = [r for r in rl if r["option"] == on and f(r["I_A"]) == I and f(r["vbus"]) == vb]
                if not sel:
                    continue
                s = I / C_VMOT_MIN
                L = []
                L_fixed = []
                budget_sim = []
                for r in sel:
                    vth = thr.get((vb, r["corner"]), float("nan"))
                    t_cross = (V_START - vth) / s * 1e6
                    L.append(f(r["t_hold_us"]) - t_cross)
                    if r["delay"] in ("f2", "f4"):
                        L_fixed.append(L[-1])
                    budget_sim.append(f(r["t_cond_us"]) - f(r["t_hold_us"]))
                row = dict(option=on, I_A=I, slope_V_per_ms=round(s / 1e3, 3), vbus=vb, decks=len(sel),
                           released_at_ev=sum(int(f(r["released_at_ev"])) for r in sel),
                           L_us=rng(L, "%.1f"), L_fixed_us=rng(L_fixed, "%.1f"), budget_sim_us=rng(budget_sim, "%.1f"),
                           vth_static_V=rng([thr.get((vb, c), float("nan")) for c in CORNERS], "%.3f"))
                for basis in ("r3", "sim3"):
                    fm = FALL_MIN.get(vb, {}).get(basis)
                    if fm is None:
                        row["budget_%s_us" % basis] = "-"
                        row["budget_fixed_%s_us" % basis] = "-"
                        continue
                    win = (fm - (vb - VFWD)) / s * 1e6
                    row["window_%s_us" % basis] = round(win, 1)
                    row["budget_%s_us" % basis] = round(win - max(L), 1)
                    row["budget_fixed_%s_us" % basis] = round(win - max(L_fixed), 1)
                agg_l.append(row)
    R.write_csv(os.path.join(RES, "agg_t2lat.csv"), agg_l)
    # ---- false-trip check
    rr = [r for r in load("t2rise") if r.get("verdict") != "SIM_FAIL"]
    agg_r = []
    for on in OPTS:
        for sl in sorted(set(f(r["slew_V_per_ms"]) for r in rr if r["option"] == on)):
            for v0 in (0.0, 13.0, 14.5, 15.2):
                sel = [r for r in rr if r["option"] == on and f(r["slew_V_per_ms"]) == sl and f(r["v0"]) == v0]
                if not sel:
                    continue
                agg_r.append(dict(option=on, slew_V_per_ms=sl, v0=v0, decks=len(sel),
                                  h1u_max_us=round(max(f(r["t_h1u_us"]) for r in sel), 1),
                                  rel_max_us=round(max(f(r["t_rel_us"]) for r in sel), 1),
                                  peak_V=rng([f(r["ilim_peak_V"]) for r in sel], "%.3f"),
                                  t_above_1v0_max_us=round(max(f(r["t_above_1v0_ceLOW_us"]) for r in sel), 1),
                                  unsafe=sum(1 for r in sel if str(r.get("verdict", "")).startswith("UNSAFE"))))
    R.write_csv(os.path.join(RES, "agg_t2rise.csv"), agg_r)
    for name, rows in (("interruptions", agg_i), ("latency", agg_l), ("rise", agg_r)):
        print("== %s" % name)
        for r in rows:
            print("  " + " | ".join("%s=%s" % kv for kv in r.items()))
    print("t2int simulator failures: %d" % nfail_i)
    plot_int(ri)


def plot_int(ri):
    if not ri:
        return
    xs = {"2us": 2, "5us": 5, "10us": 10, "15us": 15, "20us": 20, "30us": 30, "40us": 40, "50us": 50, "70us": 70,
          "100us": 100, "150us": 150, "200us": 200, "300us": 300,
          "1000us": 1000, "3000us": 3000, "perm": 8000}
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))
    for on in OPTS:
        pk, tt = [], []
        for d, x in xs.items():
            sel = [r for r in ri if r["option"] == on and r["dur_us"] == d]
            if sel:
                pk.append((x, max(f(r["ilim_peak_V"]) for r in sel)))
                tt.append((x, max(f(r["t_above_1v0_ceLOW_us"]) for r in sel)))
        axs[0].plot([p[0] for p in pk], [p[1] for p in pk], "o-", label=OPT_LABEL[on])
        axs[1].plot([p[0] for p in tt], [p[1] for p in tt], "o-", label=OPT_LABEL[on])
    for ax in axs:
        ax.set_xscale("log")
        ax.set_xticks(list(xs.values()))
        ax.set_xticklabels([k.replace("us", "") for k in xs], fontsize=7)
        ax.minorticks_off()
        ax.set_xlabel("T2 interruption (us; 'perm' = permanent open)")
        ax.grid(alpha=0.3)
    axs[0].axhline(1.0, color="r", lw=0.8, ls="--")
    axs[0].axhline(0.75, color="orange", lw=0.8, ls="--")
    axs[0].set_ylabel("ILIM_HIZ peak at the EVM pin (V), worst over all decks")
    axs[1].set_ylabel("time above VIH 1.0 V with /CE LOW (us), worst")
    axs[0].legend(fontsize=7)
    fig.suptitle("Sim 4 section 5.6a: brief T2 interruptions, VBUS 14.5-16.4 V, 3 corners; 2-40 us: 7 delay sets, 50-300 us: 4", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "t2int_peak_vs_duration.png"), dpi=130)
    plt.close(fig)


FIG_CASES = (("t2int", "int_base_20us_16.4V_early_f2", (0.99, 1.10)),
             ("t2int", "int_C108_470p_10us_16.4V_early_f2", (0.99, 1.10)),
             ("t2rise", "rise_C107_4n7_only_12Vms_13_16.4V_nom_f2", (0.95, 1.8)),
             ("t2lat", "lat_C106C107_4n7_1.8A_15.9V_early_od4", (0.95, 1.9)))


def figures():
    """Waveform figures of selected cases (re-runs the decks with the same definitions)."""
    JOBS.clear()
    fam_int()
    fam_rise()
    fam_lat()
    want = {(fm, nm): z for fm, nm, z in FIG_CASES}
    jobs = [j for j in JOBS if (j["family"], j["case"].name) in want]
    for j in jobs:
        _, w = R.execute(j)
        z = want[(j["family"], j["case"].name)]
        R.plot_waves(w, "%s / %s (zoom)" % (j["family"], j["case"].name),
                     os.path.join(FIG, "%s__%s_zoom.png" % (j["family"], j["case"].name)), t_unit=1e-3,
                     xlabel="time (ms)", xlim=z)


def main():
    which = sys.argv[1:] or ["thr", "lat", "rise", "int", "intx", "intl", "fig"]
    if "fig" in which:
        which = [w for w in which if w != "fig"]
        if not which:
            figures()
            return
        do_fig = True
    else:
        do_fig = False
    t_all = time.time()
    fams = {"int": ("t2int", fam_int),
            "intx": ("t2intx", lambda: (fam_int("t2intx", DURS_X, ("C107_4n7_only", "C106C107_4n7", "C106C107_10n"),
                                                DELAYS_X),
                                        fam_int("t2intx", (50e-6, 100e-6), ("base", "C108_470p"), DELAYS_X))),
            "intl": ("t2intl", lambda: fam_int("t2intl", (1e-3, 3e-3), ("base",) + SLOW, ("f2", "od4"))),
            "lat": ("t2lat", fam_lat), "thr": ("t2thr", fam_thr),
            "rise": ("t2rise", fam_rise)}
    for w in which:
        if w == "agg":
            continue
        fam, fn = fams[w]
        JOBS.clear()
        fn()
        clean_family(fam)
        print("%s: %d decks" % (fam, len(JOBS)), flush=True)
        rows = run_jobs(list(JOBS))
        R.write_csv(os.path.join(RES, fam + ".csv"), rows, first=["family", "case", "verdict", "violations"])
        print("%s: %d simulator failures" % (fam, sum(1 for r in rows if r.get("verdict") == "SIM_FAIL")))
    aggregate()
    if do_fig:
        figures()
    print("done in %.0f s" % (time.time() - t_all))


if __name__ == "__main__":
    main()
