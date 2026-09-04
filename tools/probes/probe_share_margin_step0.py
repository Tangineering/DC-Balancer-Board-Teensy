#!/usr/bin/env python3
"""Step 0 of the margin-referred share governor (no firmware change).

Hypothesis under test (docs/modeling/low_current_share_stability_20260903.md
section 4.2): the minority-channel DROPOUT boundary is a CONDUCTION MARGIN, not
a current floor, so ONE margin floor `M_floor` should separate the bench runs
that dropped a channel from the runs that did not.

This probe derives every quantity from the committed bench logs in `logs/` with
no new bench data.  It is stdlib-only and deterministic; either interpreter
works:

    .venv_hil/Scripts/python.exe tools/probes/probe_share_margin_step0.py
    C:/Users/ricky/miniforge3/python.exe tools/probes/probe_share_margin_step0.py

WHAT IT COMPUTES
----------------
Per 1 kHz bench-log tick, from the decoded BLG columns `share_sp`, `I_fc`,
`I_batt`, `gFC`, `gBT`, `V_bus`:

    I_tot  = I_fc + I_batt
    r      = gBT / (gFC + gBT)          the COMMANDED droop ratio
    alpha  = I_fc / I_tot               the DELIVERED fuel-cell share
    d_hat  = share_sp - r               the note's online offset estimate
    (also alpha - r, the offset the delivered share implies)

`r` recovers exactly because the firmware writes
`gFC = K_DROOP/(RE_MAX*r)` and `gBT = K_DROOP/(RE_MAX*(1-r))`
(teensy_controller.ino:10905-10906), so `gBT/(gFC+gBT) == r` identically and
the ratio is independent of both K_DROOP and RE_MAX.  The probe verifies this
against `K_DROOP/(RE_MAX*gFC)` on every tick of every log and refuses to
continue if the two disagree by more than 1e-6.

Each source is a Thevenin voltage behind its channel resistance:

    R_FC = rho*k_d/r     + R_f
    R_BT =     k_d/(1-r) + R_f
    dV0  = V_0F - V_0B

The minority channel's CONDUCTION MARGIN is its emf minus the bus voltage that
would obtain if it carried no current:

    M_FC = dV0 + R_BT * I_tot           (fuel cell in the minority)
    M_BT = R_FC * I_tot - dV0           (battery in the minority)

with `dV0` estimated from the same window by inverting the split law:

    dV0_hat = I_tot * (x*R_FC - (1-x)*R_BT),   x = alpha  or  x = share_sp

Three droop realizations are scored (a fourth is printed as a sensitivity):

    (i)   design      k_d = 0.30 ohm, rho = 1, R_f = 0
    (ii)  measured    k_d = 0.30*DROOP_SCALE["measured"], rho = 1, R_f = 0
    (iii) split-law   k_d = 0.30 ohm, rho = 0.9434, R_f = 0.033 ohm
    (iv)  measured+split-law  k_d = 0.30*s, rho = 0.9434, R_f = 0.033 ohm

CLASSIFICATION
--------------
A dropout event is a run of ticks with the minority channel below
DARK_A = 0.02 A while I_tot >= I_TOT_MIN_A = 0.30 A, ending when that channel
recovers above LIVE_A = 0.05 A (the hysteresis convention of
.claude/skills/benchlog-agent-analysis/references/log-conventions.md; a naive
threshold counter fabricates hundreds of phantom events out of ADC noise).

  * FAIL point   -- the last tick before an event onset at which the channel
                    that is about to go dark still carried >= LIVE_A.  This is
                    the margin at which conduction was actually lost.
  * SURVIVED tick -- any tick with both channels >= LIVE_A and
                    I_tot >= I_TOT_MIN_A, at least GUARD_S = 1.0 s away from
                    every dropout event in the same log.  This is a margin that
                    was demonstrably held.

A single floor separates iff  max(FAIL M) < min(SURVIVED M).
"""
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

from decode_benchlog import decode_blg  # noqa: E402

# ---------------------------------------------------------------------------
# Firmware constants (teensy_controller.ino).  K_DROOP is ALSO carried in every
# BLG header (u16 ohms x1000) and is cross-checked per log.
K_DROOP = 0.30                                  # ohm  (.ino:2217)
K_SNS = 0.1                                     # V/A  (.ino:2206, INA253A1)
A_V = 5.02                                      # OPA197 gain (.ino:2207)
RD1_OVER_RINJ = 215.0 / 53.6                    # (.ino:2213)
RE_MAX = K_SNS * A_V * RD1_OVER_RINJ            # 2.0136 ohm (.ino:2216)

# Plant constants (tools/hil_electrical.py).  Repeated as literals so the probe
# runs under the stdlib interpreter; a self-check below re-derives DROOP_SCALE.
DROOP_MEASURED_SINGLE_OHM = 0.16                # hil_electrical.py:212
DROOP_DESIGN_SINGLE_OHM = 0.63287               # hil_electrical.py:208
DROOP_FIXED_SERIES_OHM = 0.033                  # hil_electrical.py:203
DROOP_SCALE_MEASURED = ((DROOP_MEASURED_SINGLE_OHM - DROOP_FIXED_SERIES_OHM)
                        / (DROOP_DESIGN_SINGLE_OHM - DROOP_FIXED_SERIES_OHM))
ASYM_RHO = 0.9434                               # hil_electrical.py:280 / 281

# (label, k_d [ohm], rho, R_f [ohm], scored?)
REALIZATIONS = (
    ("i-design", K_DROOP, 1.0, 0.0, True),
    ("ii-measured", K_DROOP * DROOP_SCALE_MEASURED, 1.0, 0.0, True),
    ("iii-splitlaw", K_DROOP, ASYM_RHO, DROOP_FIXED_SERIES_OHM, True),
    ("iv-meas+split", K_DROOP * DROOP_SCALE_MEASURED, ASYM_RHO,
     DROOP_FIXED_SERIES_OHM, False),
)

# Event / classification thresholds.
DARK_A = 0.02          # channel is dark below this
LIVE_A = 0.05          # channel has re-conducted above this
I_TOT_MIN_A = 0.30     # share statistics are ill-conditioned below this
GUARD_S = 1.0          # a survived tick must be this far from any event
BURST_GAP_S = 0.25     # events closer than this are ONE limit-cycle burst
SLEW_STATIC_MAX = 1.0  # |dr/dt| [1/s] under which a first passage counts as
                       # quasi-static (the limiter's ceiling is ~17/s)
SUSTAIN_S = 0.20       # a "sustained" survived tick is centred in this much
                       # uninterrupted two-channel conduction
R_CONVENTION_TOL = 1e-6

# The eight logs of the note's section 2, with the role each plays.
LOGS = (
    # (name, role, note)
    ("TP0016", "dropout", "sp 0.15, FC minority, bus collapsed to 8.2 V"),
    ("TP0017", "clean", "sp 0.18, FC minority, clean neighbour of TP0016"),
    ("WP0073", "dropout", "b = 0.22, BT minority, cycled at 18.7 Hz"),
    ("WP0071", "clean", "clean neighbour of WP0073"),
    ("WP0100", "dropout", "28 BT dropouts"),
    ("WP0095", "clean", "clean neighbour of WP0100"),
    ("TP0105", "dropout", "fw v6 ladder handover, FC minority"),
    ("TP0115", "dropout", "fw v6 ladder handover, BT minority"),
)


# ---------------------------------------------------------------------------
def load(name):
    """Decode one BLG into a dict of column lists plus its header."""
    path = os.path.join(ROOT, "logs", name + ".BLG")
    with open(path, "rb") as fh:
        res = decode_blg(fh.read())
    cols = res.csv_header.split(",")
    data = {c: [] for c in cols}
    for row in res.csv_rows:
        for c, v in zip(cols, row.split(",")):
            data[c].append(float(v) if v != "" else float("nan"))
    return data, res.header


def derive(data):
    """Add t, I_tot, r, alpha, d_hat, and the conduction mask."""
    t0 = data["t_us"][0]
    n = len(data["t_us"])
    t = [(data["t_us"][i] - t0) * 1e-6 for i in range(n)]
    itot, r, alpha, dhat, ahat, cond = [], [], [], [], [], []
    nan = float("nan")
    worst_conv = 0.0
    for i in range(n):
        ifc, ibt = data["I_fc"][i], data["I_batt"][i]
        gf, gb = data["gFC"][i], data["gBT"][i]
        tot = ifc + ibt
        itot.append(tot)
        if gf + gb > 1e-9:
            ri = gb / (gf + gb)
            if gf > 1e-9:
                worst_conv = max(worst_conv, abs(ri - K_DROOP / (RE_MAX * gf)))
        else:
            ri = nan
        r.append(ri)
        a = ifc / tot if tot > 1e-9 else nan
        alpha.append(a)
        dhat.append(data["share_sp"][i] - ri)
        ahat.append(a - ri)
        cond.append(ifc >= LIVE_A and ibt >= LIVE_A and tot >= I_TOT_MIN_A
                    and ri == ri)
    return {"t": t, "I_tot": itot, "r": r, "alpha": alpha,
            "d_hat": dhat, "a_minus_r": ahat, "cond": cond,
            "r_convention_err": worst_conv}


def events(minor, itot):
    """Dropout events on one channel: list of (onset_idx, recover_idx)."""
    out = []
    n = len(minor)
    i = 0
    while i < n:
        if minor[i] < DARK_A and itot[i] >= I_TOT_MIN_A:
            j = i
            while j < n and minor[j] < LIVE_A:
                j += 1
            out.append((i, min(j, n - 1)))
            i = j
        else:
            i += 1
    return out


def channel_r(rr, kd, rho, rf):
    """(R_FC, R_BT) at commanded ratio rr under one droop realization."""
    return rho * kd / rr + rf, kd / (1.0 - rr) + rf


def margin(direction, rr, itot, x, kd, rho, rf):
    """Minority conduction margin [V] and the dV0 estimate that produced it.

    `direction` is "FC" or "BT" (which channel is the minority); `x` is the
    share used to estimate dV0 -- alpha (delivered) or share_sp (commanded).
    """
    rfc, rbt = channel_r(rr, kd, rho, rf)
    dv0 = itot * (x * rfc - (1.0 - x) * rbt)
    if direction == "FC":
        return dv0 + rbt * itot, dv0, rfc, rbt
    return rfc * itot - dv0, dv0, rfc, rbt


def fmt(v, w=8, p=4):
    if v is None or v != v:
        return " " * (w - 3) + "n/a"
    return ("%*.*f" % (w, p, v))


# ---------------------------------------------------------------------------
def collect():
    """Return (fails, survived, per_log) over every log."""
    fails, survived, per_log = [], [], []
    for name, role, note in LOGS:
        data, hdr = load(name)
        d = derive(data)
        if d["r_convention_err"] > R_CONVENTION_TOL:
            sys.exit("error: %s violates r = gBT/(gFC+gBT) by %.3e"
                     % (name, d["r_convention_err"]))
        if abs(hdr["k_droop_ohm"] - K_DROOP) > 1e-9:
            sys.exit("error: %s header K_DROOP %.4f != %.4f"
                     % (name, hdr["k_droop_ohm"], K_DROOP))
        t = d["t"]
        ev = {"FC": events(data["I_fc"], d["I_tot"]),
              "BT": events(data["I_batt"], d["I_tot"])}
        # --- FAIL points ---------------------------------------------------
        log_fails = []
        for direction, series in (("FC", data["I_fc"]), ("BT", data["I_batt"])):
            prev_recover_t = None
            n_burst = 0
            for onset, recover in ev[direction]:
                # Only the FIRST event of a burst is a first passage: inside a
                # limit cycle the "last conducting tick" is a recovery
                # overshoot, not an approach to the boundary.
                lead = (prev_recover_t is None
                        or t[onset] - prev_recover_t > BURST_GAP_S)
                prev_recover_t = t[recover]
                if not lead:
                    continue
                n_burst += 1
                k = onset - 1
                while k >= 0 and series[k] < LIVE_A:
                    k -= 1
                if k < 0 or not d["cond"][k]:
                    continue
                # Slew rates over the ~20 ms before the boundary, to tell a
                # quasi-static first passage from one driven by a share step.
                m20 = k
                while m20 > 0 and t[k] - t[m20] < 0.020:
                    m20 -= 1
                span = max(t[k] - t[m20], 1e-6)
                dr_dt = (d["r"][k] - d["r"][m20]) / span
                di_dt = (d["I_tot"][k] - d["I_tot"][m20]) / span
                # "prior quiet": no dropout of EITHER channel in the second
                # before this one, i.e. the board was not already cycling.
                quiet = True
                for other in ("FC", "BT"):
                    for o_on, o_rec in ev[other]:
                        if 0.0 < t[k] - t[o_rec] <= 1.0 or t[o_on] < t[k] <= t[o_rec]:
                            quiet = False
                rec = {
                    "log": name, "fw": hdr["fw_version"], "dir": direction,
                    "burst": n_burst, "dr_dt": dr_dt, "di_dt": di_dt,
                    "quiet": quiet,
                    "t": t[k], "I_tot": d["I_tot"][k], "r": d["r"][k],
                    "alpha": d["alpha"][k], "sp": data["share_sp"][k],
                    "d_hat": d["d_hat"][k], "a_minus_r": d["a_minus_r"][k],
                    "I_min": min(data["I_fc"][k], data["I_batt"][k]),
                    "I_dir": series[k], "V_bus": data["V_bus"][k],
                    # A FAIL point is an instant, not a hold: its window
                    # statistic IS the boundary sample.  This biases the test
                    # TOWARD separation, because the survived side is averaged
                    # and the fail side is not.
                    "I_tot_w": d["I_tot"][k], "r_w": d["r"][k],
                    "alpha_w": d["alpha"][k], "I_dir_w": series[k],
                }
                log_fails.append(rec)
        fails.extend(log_fails)
        # --- SURVIVED ticks -------------------------------------------------
        bad = []
        for direction in ("FC", "BT"):
            for onset, rec_i in ev[direction]:
                bad.append((t[onset] - GUARD_S, t[rec_i] + GUARD_S))
        keep = [False] * len(t)
        for i in range(len(t)):
            if not d["cond"][i]:
                continue
            ti = t[i]
            if any(lo <= ti <= hi for lo, hi in bad):
                continue
            keep[i] = True
        dt = statistics.median(t[i + 1] - t[i] for i in range(len(t) - 1))
        half = max(1, int(round(0.5 * SUSTAIN_S / dt)))
        # Prefix sums for the window means (the per-tick minimum is one sample
        # of a noisy hold; the window mean is the level the board actually
        # held).  r is NaN before the governor first writes the MDACs, so its
        # prefix sum is taken over the kept region only, where r is finite.
        n = len(t)
        pf, pb, pr = [0.0] * (n + 1), [0.0] * (n + 1), [0.0] * (n + 1)
        for i in range(n):
            ri = d["r"][i]
            pf[i + 1] = pf[i] + data["I_fc"][i]
            pb[i + 1] = pb[i] + data["I_batt"][i]
            pr[i + 1] = pr[i] + (ri if ri == ri else 0.0)

        def wmean(pre, i):
            return (pre[i + half + 1] - pre[i - half]) / (2 * half + 1)

        log_surv = []
        for i in range(n):
            if not keep[i]:
                continue
            ti = t[i]
            sustained = (i - half >= 0 and i + half < n
                         and all(keep[j] for j in range(i - half, i + half + 1)))
            direction = "FC" if d["alpha"][i] < 0.5 else "BT"
            if sustained:
                fw_, bw_, rw_ = wmean(pf, i), wmean(pb, i), wmean(pr, i)
            else:
                fw_, bw_, rw_ = (data["I_fc"][i], data["I_batt"][i],
                                 d["r"][i])
            tw = fw_ + bw_
            log_surv.append({
                "log": name, "fw": hdr["fw_version"], "dir": direction,
                "sustained": sustained,
                "t": ti, "I_tot": d["I_tot"][i], "r": d["r"][i],
                "alpha": d["alpha"][i], "sp": data["share_sp"][i],
                "d_hat": d["d_hat"][i], "a_minus_r": d["a_minus_r"][i],
                "I_min": min(data["I_fc"][i], data["I_batt"][i]),
                "I_dir": (data["I_fc"][i] if direction == "FC"
                          else data["I_batt"][i]),
                "V_bus": data["V_bus"][i],
                # window-mean operating point (used for the robust statistic)
                "I_tot_w": tw, "r_w": rw_, "alpha_w": fw_ / tw,
                "I_dir_w": fw_ if direction == "FC" else bw_,
            })
        survived.extend(log_surv)
        per_log.append({
            "name": name, "role": role, "note": note, "fw": hdr["fw_version"],
            "blg": hdr["version"], "n": len(t), "dur": t[-1],
            "n_ev_fc": len(ev["FC"]), "n_ev_bt": len(ev["BT"]),
            "n_fail": len(log_fails), "n_surv": len(log_surv),
            "V_bus_min": min(data["V_bus"]),
            "conv_err": d["r_convention_err"],
        })
    return fails, survived, per_log


def add_margins(recs):
    """Attach M under every realization, for both dV0 estimators."""
    for rec in recs:
        for label, kd, rho, rf, _scored in REALIZATIONS:
            for est, x in (("alpha", rec["alpha"]), ("sp", rec["sp"])):
                m, dv0, rfc, rbt = margin(rec["dir"], rec["r"], rec["I_tot"],
                                          x, kd, rho, rf)
                rec["M_%s_%s" % (label, est)] = m
                rec["dV0_%s_%s" % (label, est)] = dv0
            rec["Rsum_%s" % label] = rfc + rbt
            mw, _dv, rfw, rbw = margin(rec["dir"], rec["r_w"], rec["I_tot_w"],
                                       rec["alpha_w"], kd, rho, rf)
            rec["MW_%s" % label] = mw
            rec["RsumW_%s" % label] = rfw + rbw


# ---------------------------------------------------------------------------
def sec(title):
    print("")
    print("=" * 78)
    print(title)
    print("=" * 78)


def main():
    print("probe_share_margin_step0 -- margin-referred governor, Step 0")
    print("repo root: %s" % ROOT)
    print("K_DROOP %.4f ohm   RE_MAX %.6f ohm   DROOP_SCALE[measured] %.6f"
          % (K_DROOP, RE_MAX, DROOP_SCALE_MEASURED))
    print("rho %.4f   R_f %.4f ohm" % (ASYM_RHO, DROOP_FIXED_SERIES_OHM))
    print("thresholds: DARK %.2f A  LIVE %.2f A  I_tot_min %.2f A  guard %.1f s"
          % (DARK_A, LIVE_A, I_TOT_MIN_A, GUARD_S))

    fails, survived, per_log = collect()
    add_margins(fails)
    add_margins(survived)

    # -- Table 1: inventory --------------------------------------------------
    sec("TABLE 1 -- log inventory and dropout census")
    print("%-8s %-8s %3s %3s %7s %6s %6s %6s %6s %8s  %s"
          % ("log", "role", "fw", "blg", "dur_s", "evFC", "evBT", "brst",
             "surv", "Vbus_min", "r-convention err"))
    for p in per_log:
        print("%-8s %-8s %3s %3d %7.2f %6d %6d %6d %6d %8.3f  %.2e"
              % (p["name"], p["role"], p["fw"], p["blg"], p["dur"],
                 p["n_ev_fc"], p["n_ev_bt"], p["n_fail"], p["n_surv"],
                 p["V_bus_min"], p["conv_err"]))
    print("")
    print("note: 'brst' counts BURST-LEADING events only -- events whose onset")
    print("      is within %.2f s of the previous event's recovery are ONE"
          % BURST_GAP_S)
    print("      limit cycle and only its first passage is scored -- and only")
    print("      those whose last conducting tick passed the I_tot >= %.2f A"
          % I_TOT_MIN_A)
    print("      gate.  'evFC'/'evBT' are the raw event counts.")
    print("total ticks decoded: %d; scored records (survived + first"
          % sum(p["n"] for p in per_log))
    print("passages): %d" % (len(survived) + len(fails)))

    # -- Table 2: FAIL points ------------------------------------------------
    sec("TABLE 2 -- FAIL points (last conducting tick before each dropout)")
    print("one row per event; M in volts, under the DELIVERED-share dV0"
          " estimate (x = alpha)")
    print("")
    print("'quiet' marks a first passage with no dropout of either channel in")
    print("the preceding 1.0 s; dr/dt is the commanded-ratio slew over the")
    print("20 ms before the boundary (the limiter's ceiling is 0.02/tick,")
    print("about 17/s at the 1.16 ms loop period).")
    print("")
    hdr = ("%-8s %-3s %5s %8s %7s %7s %7s %7s %8s %8s %8s %8s %8s "
           "| %8s %8s %8s"
           % ("log", "dir", "quiet", "t_s", "I_tot", "r", "alpha", "sp",
              "I_min", "V_bus", "d_hat", "dr/dt", "dItot/dt",
              "M_i", "M_ii", "M_iii"))
    print(hdr)
    for rec in fails:
        print("%-8s %-3s %5s %8.3f %7.4f %7.4f %7.4f %7.3f %8.4f %8.3f "
              "%8.4f %8.3f %8.3f | %8.4f %8.4f %8.4f"
              % (rec["log"], rec["dir"], "yes" if rec["quiet"] else "no",
                 rec["t"], rec["I_tot"], rec["r"],
                 rec["alpha"], rec["sp"], rec["I_dir"], rec["V_bus"],
                 rec["d_hat"], rec["dr_dt"], rec["di_dt"],
                 rec["M_i-design_alpha"],
                 rec["M_ii-measured_alpha"], rec["M_iii-splitlaw_alpha"]))

    # -- Table 2b: the offset estimates --------------------------------------
    sec("TABLE 2b -- the standing offset at each FAIL point")
    print("d_hat = share_sp - r is the note's online estimator; alpha - r is")
    print("the offset the delivered share implies.  dV0_hat inverts the split")
    print("law of the named realization at that operating point.")
    print("")
    print("%-8s %-3s %8s %9s %9s %10s %10s %10s %10s"
          % ("log", "dir", "t_s", "d_hat", "alpha-r", "dV0(i,a)", "dV0(i,sp)",
             "dV0(iii,a)", "dV0(iii,sp)"))
    for rec in fails:
        print("%-8s %-3s %8.3f %9.4f %9.4f %10.4f %10.4f %10.4f %10.4f"
              % (rec["log"], rec["dir"], rec["t"], rec["d_hat"],
                 rec["a_minus_r"], rec["dV0_i-design_alpha"],
                 rec["dV0_i-design_sp"], rec["dV0_iii-splitlaw_alpha"],
                 rec["dV0_iii-splitlaw_sp"]))
    print("")
    print("For reference the plant's fitted value is ASYM_DV0_V = 0.013522 V")
    print("(hil_electrical.py), a CONSTANT.  Any estimate far from it is the")
    print("estimator absorbing a droop-scale or slew error into a voltage.")

    # -- Table 3: separation test -------------------------------------------
    sec("TABLE 3 -- separation test: does ONE M_floor separate?")
    for est in ("alpha", "sp"):
        print("")
        print("dV0 estimator: x = %s   (%s)"
              % (est, "delivered share" if est == "alpha"
                 else "commanded setpoint, the note's online d_hat"))
        print("%-14s %-4s %6s %8s %8s %8s %8s %8s %-16s"
              % ("realization", "dir", "nF/nS", "max_FAIL", "minSURV",
                 "minSUST", "gap_mV", "gap_A", "where minSUST"))
        for label, kd, rho, rf, scored in REALIZATIONS:
            key = "M_%s_%s" % (label, est)
            for direction in ("FC", "BT", "both"):
                F = [x for x in fails if direction in (x["dir"], "both")]
                S = [x for x in survived if direction in (x["dir"], "both")]
                Su = [x for x in S if x["sustained"]]
                if not F or not Su:
                    continue
                mx = max(x[key] for x in F)
                mn = min(x[key] for x in S)
                wsu = min(Su, key=lambda x: x[key])
                mnu = wsu[key]
                # A-equivalent at the median FAIL operating point:
                # M = (R_FC + R_BT) * I_minority exactly, so dI = dM / Rsum.
                rsum = statistics.median(x["Rsum_%s" % label] for x in F)
                gap = mnu - mx
                print("%-14s %-4s %2d/%-3d %8.4f %8.4f %8.4f %8.1f %8.4f "
                      "%s@%.2fs%s"
                      % (label + ("" if scored else "*"), direction,
                         len(F), len(Su), mx, mn, mnu, gap * 1000.0,
                         gap / rsum, wsu["log"], wsu["t"],
                         "  SEPARATES" if gap > 0 else "  OVERLAP"))
        print("  Both columns are PER-TICK M values: minSURV over every")
        print("  survived tick, minSUST over the subset centred in %.2f s of"
              % SUSTAIN_S)
        print("  uninterrupted two-channel conduction (the gap uses minSUST).")
        print("  Table 5 repeats the comparison on %.2f s WINDOW MEANS."
              % SUSTAIN_S)
        print("  (* = sensitivity realization, not one of the three scored)")

    # -- Table 4: the identity ----------------------------------------------
    sec("TABLE 4 -- what M actually is")
    print("At any operating point where both channels conduct, the two")
    print("Thevenin equations give the EXACT identity")
    print("")
    print("    M_minority = (R_FC + R_BT) * I_minority")
    print("")
    print("so with dV0 taken from the same window's delivered share, M is the")
    print("minority CURRENT rescaled by the series droop sum.  Residuals:")
    print("")
    print("%-14s %11s %11s" % ("realization", "max|resid|_V", "Rsum range"))
    for label, kd, rho, rf, _scored in REALIZATIONS:
        res = 0.0
        lo, hi = 1e9, -1e9
        for rec in fails + survived:
            rsum = rec["Rsum_%s" % label]
            lo, hi = min(lo, rsum), max(hi, rsum)
            res = max(res, abs(rec["M_%s_alpha" % label] - rsum * rec["I_dir"]))
        print("%-14s %11.2e %5.3f-%5.3f" % (label, res, lo, hi))
    print("")
    print("The x = share_sp estimator breaks the identity by")
    print("(R_FC+R_BT)*I_tot*(sp - alpha); that error is tabulated below.")
    print("")
    print("%-8s %-3s %8s %9s %9s %9s"
          % ("log", "dir", "t_s", "sp-alpha", "dM_i_V", "dM_iii_V"))
    for rec in fails:
        print("%-8s %-3s %8.3f %9.4f %9.4f %9.4f"
              % (rec["log"], rec["dir"], rec["t"], rec["sp"] - rec["alpha"],
                 rec["M_i-design_sp"] - rec["M_i-design_alpha"],
                 rec["M_iii-splitlaw_sp"] - rec["M_iii-splitlaw_alpha"]))

    # -- Table 5: direct observables ----------------------------------------
    sec("TABLE 5 -- deepest SUSTAINED two-channel hold, per log and direction")
    print("The tick with the smallest minority current that sat inside %.2f s"
          % SUSTAIN_S)
    print("of uninterrupted two-channel conduction.  These are margins the")
    print("board demonstrably held.")
    print("")
    print("Every column is a %.2f s WINDOW MEAN centred on that tick, so a"
          % SUSTAIN_S)
    print("single noisy sample cannot set the record.")
    print("")
    print("%-8s %-4s %7s %8s %8s %8s %8s %8s %8s %8s"
          % ("log", "dir", "n_sust", "t_s", "I_min_A", "I_tot_A", "r", "M_i",
             "M_ii", "M_iii"))
    for name, _role, _note in LOGS:
        for direction in ("FC", "BT"):
            sel = [x for x in survived
                   if x["log"] == name and x["dir"] == direction
                   and x["sustained"]]
            if not sel:
                continue
            w = min(sel, key=lambda x: x["I_dir_w"])
            print("%-8s %-4s %7d %8.3f %8.4f %8.4f %8.4f %8.4f %8.4f %8.4f"
                  % (name, direction, len(sel), w["t"], w["I_dir_w"],
                     w["I_tot_w"], w["r_w"], w["MW_i-design"],
                     w["MW_ii-measured"], w["MW_iii-splitlaw"]))
    print("")
    print("Candidate discriminants, FAIL versus SUSTAINED-SURVIVED.  The")
    print("overlap factor is max_FAIL / min_SUST: 1.0 means the two classes")
    print("just touch, and larger means worse separation.")
    print("gap_A converts a voltage gap through the identity at the median")
    print("FAIL operating point, so the two rows are directly comparable.")
    print("%-22s %-5s %9s %9s %9s %9s %8s"
          % ("variable", "dir", "max_FAIL", "min_SUST", "gap", "gap_A",
             "overlap"))
    Sst = [x for x in survived if x["sustained"]]
    for direction in ("FC", "BT", "both"):
        F = [x for x in fails if direction in (x["dir"], "both")]
        S = [x for x in Sst if direction in (x["dir"], "both")]
        if not F or not S:
            continue
        mx = max(x["I_dir_w"] for x in F)
        mn = min(x["I_dir_w"] for x in S)
        print("%-22s %-5s %9.4f %9.4f %9.4f %9.4f %8.2f%s"
              % ("I_minority [A]", direction, mx, mn, mn - mx, mn - mx,
                 mx / mn, "  SEPARATES" if mn > mx else "  OVERLAP"))
        for label, _kd, _rho, _rf, scored in REALIZATIONS:
            if not scored:
                continue
            key = "MW_%s" % label
            mxm = max(x[key] for x in F)
            mnm = min(x[key] for x in S)
            rsum = statistics.median(x["RsumW_%s" % label] for x in F)
            print("%-22s %-5s %9.4f %9.4f %9.4f %9.4f %8.2f%s"
                  % ("M [V], " + label, direction, mxm, mnm, mnm - mxm,
                     (mnm - mxm) / rsum,
                     mxm / mnm, "  SEPARATES" if mnm > mxm else "  OVERLAP"))
    print("")
    print("bus voltage, which the note quotes as the competing observable:")
    print("%-22s %-5s %9s %9s"
          % ("variable", "dir", "min_FAIL", "min_SUST"))
    for direction in ("FC", "BT", "both"):
        F = [x for x in fails if direction in (x["dir"], "both")]
        S = [x for x in Sst if direction in (x["dir"], "both")]
        if not F or not S:
            continue
        print("%-22s %-5s %9.3f %9.3f"
              % ("V_bus [V]", direction, min(x["V_bus"] for x in F),
                 min(x["V_bus"] for x in S)))

    # -- Table 6: the note's quoted pairs ------------------------------------
    sec("TABLE 6 -- the note's quoted pairs, matched on direction")
    print("For each pair the FAIL point with the LARGEST margin in the dropout")
    print("run is set against the SURVIVED tick with the SMALLEST margin in")
    print("the clean run; a pair separates only if the second exceeds the")
    print("first.  Realization (i), x = alpha.")
    print("")
    pairs = (("TP0016", "TP0017", "FC"),
             ("WP0073", "WP0071", "BT"),
             ("WP0100", "WP0095", "BT"),
             ("TP0105", "TP0017", "FC"),
             ("TP0115", "WP0095", "BT"))
    print("%-9s %-9s %-3s %10s %10s %10s %9s %9s"
          % ("dropout", "clean", "dir", "M_fail_V", "M_clean_V", "gap_mV",
             "I_fail_A", "I_clean_A"))
    for dname, cname, direction in pairs:
        F = [x for x in fails if x["log"] == dname and x["dir"] == direction]
        S = [x for x in survived
             if x["log"] == cname and x["dir"] == direction
             and x["sustained"]]
        if not F or not S:
            print("%-9s %-9s %-3s   (no comparable tick in one member)"
                  % (dname, cname, direction))
            continue
        wf = max(F, key=lambda x: x["MW_i-design"])
        ws = min(S, key=lambda x: x["MW_i-design"])
        print("%-9s %-9s %-3s %10.4f %10.4f %10.1f %9.4f %9.4f%s"
              % (dname, cname, direction, wf["MW_i-design"],
                 ws["MW_i-design"],
                 1000.0 * (ws["MW_i-design"] - wf["MW_i-design"]),
                 wf["I_dir_w"], ws["I_dir_w"],
                 "  ok" if ws["MW_i-design"] > wf["MW_i-design"]
                 else "  OVERLAP"))

    # -- Verdict -------------------------------------------------------------
    sec("VERDICT")
    any_sep = False
    for label, kd, rho, rf, scored in REALIZATIONS:
        if not scored:
            continue
        for est in ("alpha", "sp"):
            key = "M_%s_%s" % (label, est)
            mx = max(x[key] for x in fails)
            mn = min(x[key] for x in survived if x["sustained"])
            ok = mn > mx
            any_sep = any_sep or ok
            print("%-14s x=%-6s max_FAIL %8.4f V   min_SURV %8.4f V   "
                  "%s by %.1f mV"
                  % (label, est, mx, mn,
                     "separates" if ok else "OVERLAPS", abs(mn - mx) * 1000.0))
    print("")
    print("Restricted to QUIET first passages only (the board was not already")
    print("cycling), which is the population the quasi-static margin theory")
    print("actually addresses:")
    quiet_fails = [x for x in fails if x["quiet"]]
    Sst = [x for x in survived if x["sustained"]]
    if quiet_fails:
        print("  quiet FAIL points: %s"
              % ", ".join("%s/%s@%.3fs" % (x["log"], x["dir"], x["t"])
                          for x in quiet_fails))
        for label, kd, rho, rf, scored in REALIZATIONS:
            if not scored:
                continue
            key = "MW_%s" % label
            mx = max(x[key] for x in quiet_fails)
            mn = min(x[key] for x in Sst)
            print("  %-14s max_FAIL %8.4f V  min_SUST %8.4f V  %s by %.1f mV"
                  % (label, mx, mn,
                     "separates" if mn > mx else "OVERLAPS",
                     abs(mn - mx) * 1000.0))
        mxi = max(x["I_dir_w"] for x in quiet_fails)
        mni = min(x["I_dir_w"] for x in Sst)
        print("  %-14s max_FAIL %8.4f A  min_SUST %8.4f A  %s by %.4f A"
              % ("I_minority", mxi, mni,
                 "separates" if mni > mxi else "OVERLAPS", abs(mni - mxi)))
    print("")
    print("Restricted further to QUASI-STATIC first passages -- quiet AND")
    print("|dr/dt| < %.1f /s, i.e. not driven by a commanded share step --"
          % SLEW_STATIC_MAX)
    print("compared against sustained holds in the SAME direction:")
    for direction in ("FC", "BT"):
        stat = [x for x in fails if x["quiet"] and x["dir"] == direction
                and abs(x["dr_dt"]) < SLEW_STATIC_MAX]
        Sd = [x for x in Sst if x["dir"] == direction]
        if not stat or not Sd:
            print("  %s: no quasi-static first passage on record" % direction)
            continue
        print("  %s: %s" % (direction,
                            ", ".join("%s@%.3fs" % (x["log"], x["t"])
                                      for x in stat)))
        mxi = max(x["I_dir_w"] for x in stat)
        mni = min(x["I_dir_w"] for x in Sd)
        print("    %-16s max_FAIL %8.4f A  min_SUST %8.4f A  overlap %.2f"
              % ("I_minority", mxi, mni, mxi / mni))
        for label, kd, rho, rf, scored in REALIZATIONS:
            if not scored:
                continue
            key = "MW_%s" % label
            mx = max(x[key] for x in stat)
            mn = min(x[key] for x in Sd)
            print("    %-16s max_FAIL %8.4f V  min_SUST %8.4f V  overlap %.2f"
                  % (label, mx, mn, mx / mn))
    print("")
    print("Realizations (i) and (ii) differ only by the scalar")
    print("DROOP_SCALE[measured] = %.6f on k_d with R_f = 0, so M_ii = s*M_i"
          % DROOP_SCALE_MEASURED)
    print("exactly and no separation verdict can differ between them; only the")
    print("series floor R_f of realization (iii) changes any ordering.")
    print("")
    if any_sep:
        print("At least one realization separates -- see Table 3 for which.")
    else:
        print("NO realization admits a single M_floor: in every one, some")
        print("SURVIVED tick sits below some FAIL point.  The section 4.2")
        print("hypothesis is NOT supported by the existing bench record, and")
        print("the two-axis bench sweep of section 5 remains the only route.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
