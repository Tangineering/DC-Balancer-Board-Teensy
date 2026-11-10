#!/usr/bin/env python3
"""purge_stats.py - H-20 purge statistics from the Pi rosbags (facts_purge.md).

Source: logs/rosbags/rosbag_*/ *.mcap, topic /vehicle_state (bridge v4 18-element array, index map
in tools/rosbag_analysis/scout_bags.py VS list). The Teensy sends telemetry every 20 ms; V_fc is the
latest analogRead(FC_VOLTAGE) * SCALE_V_FC at send time (teensy_controller.ino:7029, :7680), so the
bags are 50 Hz POINT samples of the stack terminal voltage. Time base: telemetry index
k = round((log_time - t0) / 20 ms), which removes Pi receive jitter (residual sd 0.1 ms on 22 of 23
bags) and keeps sample alignment across dropped packets.

Usage (needs mcap_ros2 + numpy; the repo's miniforge python has both):
    python purge_stats.py [rosbag_dir] [--cache DIR]
--cache reads/writes <DIR>/<bag>.npz in the scout_bags.py format (same arrays).

Every number printed here is cited in facts_purge.md by section of this output.
"""
import argparse
import glob
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools", "rosbag_analysis"))

DT = 0.020            # telemetry period, s (fit: 20.0000 ms on every bag)
V_TH = 7.0            # purge DETECTION threshold on V_fc, V: under the loaded rail (bag p5 8.9-10.2 V) and above the
                      # boost-off floor (4.9-6.0 V, section 3 of the output); durations use the 50 % level instead
COLLAPSE_MS = 500.0   # a sub-threshold run longer than this is a sustained collapse, not a purge
HR = "-" * 100

VS = ["v_actual", "V_batt", "I_batt", "I_charge", "V_fc", "I_fc", "V_bus",
      "V_rgn", "V_chg", "power_share_actual", "droop_FC", "droop_BT",
      "charger_status", "switch_state", "fault_flags", "error_code",
      "error_source_state", "SOC"]


def load(bagdir, cache):
    name = os.path.basename(os.path.normpath(bagdir))
    if cache:
        p = os.path.join(cache, name + ".npz")
        if os.path.exists(p):
            d = np.load(p)
            return name, d["vs_t"], d["vs"]
    from scout_bags import load_bag  # noqa: E402  (tools/rosbag_analysis)
    b = load_bag(bagdir)
    if cache:
        os.makedirs(cache, exist_ok=True)
        np.savez_compressed(os.path.join(cache, name + ".npz"), vs_t=b["vs_t"], vs=b["vs"],
                            ec_t=b["ec_t"], ec=b["ec"], VS=np.array(VS), EC=np.array(["x"]))
    return name, b["vs_t"], b["vs"]


def q(a, ps=(0, 1, 5, 25, 50, 75, 95, 99, 100)):
    a = np.asarray(a, float)
    a = a[~np.isnan(a)]
    if len(a) == 0:
        return "n=0"
    return "n=%d " % len(a) + " ".join("p%g=%.4g" % (p, np.percentile(a, p)) for p in ps)


def runs(mask):
    """(start, end_inclusive) of True runs."""
    m = np.concatenate([[False], mask, [False]]).astype(int)
    d = np.diff(m)
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0] - 1))


def analyse_bag(name, t, vs):
    k = np.round((t - t[0]) / DT).astype(int)
    keep = np.concatenate([[True], np.diff(k) > 0])       # drop duplicates
    k, vs = k[keep], vs[keep]
    n = k[-1] + 1
    # Resample onto the full index grid; missing samples are NaN.
    G = np.full((n, vs.shape[1]), np.nan)
    G[k] = vs
    have = ~np.isnan(G[:, 0])
    col = {c: G[:, i] for i, c in enumerate(VS)}
    v = col["V_fc"]
    info = dict(name=name, n=n, dur=n * DT, missing=int(n - have.sum()),
                vmed=float(np.nanmedian(v)), events=[], collapses=[])
    below = np.where(have, v < V_TH, False)
    for s, e in runs(below):
        nb = e - s + 1
        # a missing sample adjacent to the run makes its edges uncertain
        edge_gap = (s > 0 and not have[s - 1]) or (e + 1 < n and not have[e + 1])
        ev = dict(k0=s, k1=e, nb=nb, dur_ms=nb * DT * 1e3, floor=float(np.nanmin(v[s:e + 1])),
                  edge_gap=bool(edge_gap), t=s * DT)
        if nb * DT * 1e3 > COLLAPSE_MS:
            info["collapses"].append(ev)
            continue
        # pre-purge baseline: median V_fc / I_fc over [-1.5 s, -0.2 s]
        a, b = max(0, s - 75), max(0, s - 10)
        ev["v_base"] = float(np.nanmedian(v[a:b])) if b > a else float(np.nanmedian(v[e + 1:e + 60]))
        ev["truncated"] = bool(s == 0 or e + 1 >= n)
        # 50 % level duration: level = (baseline + floor)/2, linear interpolation on each edge
        lev = 0.5 * (ev["v_base"] + ev["floor"])
        i0 = s
        while i0 > 0 and have[i0 - 1] and v[i0 - 1] < lev:
            i0 -= 1
        j0 = s
        while j0 <= e and v[j0] >= lev:
            j0 += 1
        i1 = e
        while i1 >= s and v[i1] >= lev:
            i1 -= 1
        ev["t50"] = s * DT                                                     # fallback timing reference
        if ev["truncated"] or j0 > e or i1 < s or j0 == 0 or i1 + 1 >= n:
            ev["dur50_ms"] = np.nan
        else:
            tf = (j0 - 1) + (v[j0 - 1] - lev) / (v[j0 - 1] - v[j0])          # fall crossing (sample units)
            tr = i1 + (lev - v[i1]) / (v[i1 + 1] - v[i1])                    # rise crossing
            ev["dur50_ms"] = (tr - tf) * DT * 1e3
            ev["t50"] = tf * DT        # ONSET used for all timing: interpolated 50 % fall crossing
        # first sample more than 1 V under the baseline (sample-grid onset, for the precursor check)
        kb = s
        while kb > 0 and have[kb - 1] and v[kb - 1] < ev["v_base"] - 1.0:
            kb -= 1
        ev["k_on1"] = kb
        for th in (3.0, 5.0):
            ev["n_below_%g" % th] = int(np.sum(v[s:e + 1] < th))
        ev["i_base"] = float(np.nanmedian(col["I_fc"][a:b])) if b > a else np.nan
        ev["v_pre1"] = float(v[kb - 1]) if kb >= 1 else np.nan               # last sample before the 1 V onset
        ev["v_pre_m05"] = float(np.nanmedian(v[max(0, s - 25):s])) if s >= 2 else np.nan  # [-0.5 s, 0)
        ev["i_pre1"] = float(col["I_fc"][s - 1]) if s >= 1 else np.nan
        sw = col["switch_state"][max(0, s - 1)]
        ev["sw"] = int(sw) if not np.isnan(sw) else -1
        ev["state_err"] = float(col["error_code"][max(0, s - 1)])
        # recovery: first sample after the run with V_fc >= baseline - 0.3 V (cap 3 s)
        rec = np.nan
        for j in range(e + 1, min(n, e + 150)):
            if have[j] and v[j] >= ev["v_base"] - 0.3:
                rec = (j - e) * DT * 1e3
                break
        ev["recover_ms"] = rec
        # first post-purge sample above threshold (the sample after the run)
        ev["v_post1"] = float(v[e + 1]) if e + 1 < n else np.nan
        # bus behaviour across the purge (two-source vs FC-only)
        w0, w1 = max(0, s - 5), min(n, e + 15)
        ev["vbus_pre"] = float(np.nanmedian(col["V_bus"][max(0, s - 25):s])) if s > 2 else np.nan
        ev["vbus_min"] = float(np.nanmin(col["V_bus"][w0:w1]))
        ev["ibatt_pre"] = float(np.nanmedian(col["I_batt"][max(0, s - 25):s])) if s > 2 else np.nan
        ev["ibatt_max"] = float(np.nanmax(col["I_batt"][s:w1]))
        ev["ifc_min_in"] = float(np.nanmin(col["I_fc"][s:e + 1]))
        info["events"].append(ev)
    info["col"] = col
    info["have"] = have
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=os.path.join(REPO, "logs", "rosbags"))
    ap.add_argument("--cache", default=None)
    a = ap.parse_args()
    bags = [d for d in sorted(glob.glob(os.path.join(a.root, "rosbag_*"))) if glob.glob(d + "/*.mcap")]
    infos = [analyse_bag(*load(d, a.cache)) for d in bags]

    print("1. INVENTORY (V_TH = %.1f V, collapse > %.0f ms excluded)" % (V_TH, COLLAPSE_MS))
    print(HR)
    h20 = []
    for I in infos:
        src = "H-20" if I["vmed"] > 9.5 else "bench supply (flat ~8.3-8.6 V, no purges)"
        if src == "H-20":
            h20.append(I)
        print("%-44s %6.1f s miss=%4d Vfc_med=%5.2f purges=%3d collapses=%d  %s" % (
            I["name"], I["dur"], I["missing"], I["vmed"], len(I["events"]), len(I["collapses"]), src))
        for c in I["collapses"]:
            print("    collapse at t=%.2f s, %.0f ms below %.1f V, floor %.2f V" % (c["t"], c["dur_ms"], V_TH, c["floor"]))
    # Off-schedule filter. An event is SCHEDULED when the gap to its previous or next event lies within
    # +/-0.15 s of a non-zero multiple of the nominal period. The only rejects are the stack-voltage-loss
    # chatter of 2026-10-28 22:18 before its UV_FC latch (fw36 review section 2).
    P_nom = float(np.median(np.concatenate([np.diff([e["t50"] for e in I["events"]]) for I in h20 if len(I["events"]) > 1])))
    print("nominal period (median of all raw onset gaps): %.4f s" % P_nom)

    def on_sched(g):
        m = round(g / P_nom)
        return m >= 1 and abs(g - m * P_nom) < 0.15

    for I in h20:
        on = [e["t50"] for e in I["events"]]
        keep, off = [], []
        for j, e in enumerate(I["events"]):
            ok = (j > 0 and on_sched(on[j] - on[j - 1])) or (j + 1 < len(on) and on_sched(on[j + 1] - on[j]))
            (keep if ok else off).append(e)
        I["events"], I["offsched"] = keep, off
        for e in off:
            print("    OFF-SCHEDULE %-40s t=%.2f s nb=%d floor %.2f V base %.2f V" % (I["name"], e["t"], e["nb"], e["floor"], e["v_base"]))
    ev = [e for I in h20 for e in I["events"]]
    print("H-20 bags: %d; scheduled purges measured: %d (off-schedule excluded: %d); H-20 time: %.1f s" % (
        len(h20), len(ev), sum(len(I["offsched"]) for I in h20), sum(I["dur"] for I in h20)))
    print("  floor < 3 V (normal operation): %d; floor >= 3 V (boost-off after a latch): %d" % (
        sum(e["floor"] < 3 for e in ev), sum(e["floor"] >= 3 for e in ev)))
    for I in h20:
        for e in I["events"]:
            if e["floor"] >= 3:
                print("    shallow purge %-40s t=%.2f s floor %.2f V error_code %g switch_state 0x%02x" % (
                    I["name"], e["t"], e["floor"], e["state_err"], e["sw"]))
    print("  truncated at bag start/end: %d" % sum(e["truncated"] for e in ev))
    print("  error_code at onset != 0 among floor < 3 V purges: %d" % sum(e["floor"] < 3 and e["state_err"] != 0 for e in ev))

    print("\n2. THRESHOLD SENSITIVITY (raw sub-threshold runs <= 500 ms, before the schedule filter)")
    print(HR)
    for th in (3.0, 4.0, 5.0, 6.0, 7.0, 8.0):
        cnt = 0
        for I in h20:
            v = I["col"]["V_fc"]
            for s, e in runs(np.where(I["have"], v < th, False)):
                if (e - s + 1) * DT * 1e3 <= COLLAPSE_MS:
                    cnt += 1
        print("  V_th %.1f V: %d runs" % (th, cnt))

    print("\n3. PER-PURGE SHAPE (normal-operation purges: floor < 3 V, not truncated)")
    print(HR)
    evn = [e for e in ev if e["floor"] < 3 and not e["truncated"]]
    print("  n = %d" % len(evn))
    for th, key in ((7, "nb"), (5, "n_below_5"), (3, "n_below_3")):
        print("  samples below %d V:" % th, {int(x): int(np.sum([e[key] == x for e in evn])) for x in sorted({e[key] for e in evn})})
    print("  duration at the 50 %% level (interpolated) ms ", q([e["dur50_ms"] for e in evn], (0, 1, 5, 50, 95, 99, 100)))
    print("  samples-below-7V x 20 ms (bounds +/-20 ms)    ", q([e["dur_ms"] for e in evn], (0, 1, 5, 50, 95, 99, 100)))
    print("  floor V       ", q([e["floor"] for e in evn]))
    print("  pre baseline V", q([e["v_base"] for e in evn]))
    fb = np.array([(e["floor"], e["i_base"]) for e in evn if not np.isnan(e["i_base"])])
    print("  floor vs baseline I_fc: r = %+.3f; floor at I_fc<0.02 A %s; at I_fc>=0.1 A %s" % (
        np.corrcoef(fb[:, 0], fb[:, 1])[0, 1], q(fb[fb[:, 1] < 0.02, 0], (0, 50, 100)), q(fb[fb[:, 1] >= 0.1, 0], (0, 50, 100))))
    print("  edge-gap purges (missing sample next to the run):", sum(e["edge_gap"] for e in ev))
    print("  recovery to baseline-0.3 V after last sub-7V sample, ms ", q([e["recover_ms"] for e in evn], (0, 5, 50, 95, 99, 100)))
    print("  recovery not reached within 3 s:", sum(np.isnan(e["recover_ms"]) for e in evn))
    for I in h20:
        for e in I["events"]:
            if e in evn and (np.isnan(e["recover_ms"]) or e["recover_ms"] > 100):
                print("    slow recovery: %s t=%.2f s %s ms base %.2f V I_fc base %.3f A" % (I["name"], e["t"], e["recover_ms"], e["v_base"], e["i_base"]))
    print("  first sample after the run, V ", q([e["v_post1"] for e in evn]))
    evs = [e for e in ev if e["floor"] >= 3]
    print("  boost-off (post-latch) purges: n=%d dur50 ms %s floor %s" % (len(evs), q([e["dur50_ms"] for e in evs], (0, 50, 100)), q([e["floor"] for e in evs], (0, 50, 100))))

    print("\n4. INTERVALS (50 % fall crossing to 50 % fall crossing within a bag)")
    print(HR)
    allint = []
    rows = []
    for I in h20:
        E = I["events"]
        for j in range(len(E) - 1):
            e0, e1 = E[j], E[j + 1]
            x = e1["t50"] - e0["t50"]
            col = I["col"]
            s, f = e0["k1"] + 1, e1["k0"]
            ifc = col["I_fc"][s:f]
            pbus = col["I_fc"][s:f] * col["V_bus"][s:f]
            fcbus = (np.nan_to_num(col["switch_state"][s:f]).astype(int) & 1) > 0
            rows.append(dict(bag=I["name"], t=e1["t"], interval=x, i_mean=float(np.nanmean(ifc)),
                             p_mean=float(np.nanmean(pbus)), q=float(np.nansum(ifc) * DT),
                             fcbus=float(np.mean(fcbus)), gap=int(np.sum(~I["have"][s:f])),
                             idx=j + 1, t0=e0["t"], normal=bool(e0["floor"] < 3 and e1["floor"] < 3)))
            allint.append(x)
    allint = np.array(allint)
    P_med = float(np.median(allint))
    print("  all intervals s ", q(allint))
    r = allint / P_med
    print("  ratio to median: <0.6 (doubled) %d, 0.6-1.4 %d, 1.4-2.6 (one missing) %d, >2.6 %d" % (
        np.sum(r < 0.6), np.sum((r >= 0.6) & (r < 1.4)), np.sum((r >= 1.4) & (r < 2.6)), np.sum(r >= 2.6)))
    for R in rows:
        if not (0.6 <= R["interval"] / P_med < 1.4):
            print("    off-period interval: %-44s t=%.2f s interval %.3f s (x%.3f), missing samples in span %d" % (
                R["bag"], R["t"], R["interval"], R["interval"] / P_med, R["gap"]))
    good = [R for R in rows if 0.6 <= R["interval"] / P_med < 1.4]
    gi = np.array([R["interval"] for R in good])
    gn = np.array([R["interval"] for R in good if R["normal"]])
    print("  single-period intervals s ", q(gi, (0, 0.1, 1, 5, 50, 95, 99, 99.9, 100)))
    print("  single-period mean %.4f s sd %.2f ms" % (gi.mean(), gi.std(ddof=1) * 1e3))
    print("  normal-normal pairs: %s; sd %.2f ms" % (q(gn, (0, 1, 50, 99, 100)), gn.std(ddof=1) * 1e3))
    print("  pairs involving a boost-off purge: %s" % q([R["interval"] for R in good if not R["normal"]], (0, 50, 100)))

    print("\n5. PER-BAG PERIOD (least-squares fit onset = a + P*n on normal purges) and residual jitter")
    print(HR)
    resid_all = []
    Ps = []
    for I in h20:
        on = np.array([e["t50"] for e in I["events"] if e["floor"] < 3 and not e["truncated"]])
        if len(on) < 3:
            print("  %-44s %d normal purges, no fit" % (I["name"], len(on)))
            continue
        nn = np.round((on - on[0]) / P_med)
        A = np.vstack([np.ones_like(nn), nn]).T
        c, *_ = np.linalg.lstsq(A, on, rcond=None)
        res = on - A @ c
        sd = res.std(ddof=2)
        se = sd / np.sqrt(np.sum((nn - nn.mean()) ** 2))
        resid_all.extend(res.tolist())
        Ps.append((c[1], se, len(on)))
        print("  %-44s n=%3d P=%.4f s (SE %.4f) resid sd %5.1f ms max|resid| %5.1f ms span %.0f s" % (
            I["name"], len(on), c[1], se, sd * 1e3, np.abs(res).max() * 1e3, on[-1] - on[0]))
    resid_all = np.array(resid_all)
    Ps = np.array(Ps)
    w = 1 / Ps[:, 1] ** 2
    Pw = np.sum(w * Ps[:, 0]) / np.sum(w)
    chi2 = np.sum(w * (Ps[:, 0] - Pw) ** 2)
    print("  weighted mean period %.5f s (SE %.5f); per-bag range %.4f..%.4f s; chi2 %.1f on %d dof" % (
        Pw, 1 / np.sqrt(np.sum(w)), Ps[:, 0].min(), Ps[:, 0].max(), chi2, len(Ps) - 1))
    print("  pooled residual ms ", q(resid_all * 1e3, (0, 0.5, 1, 5, 50, 95, 99, 99.5, 100)))
    print("  pooled residual sd %.2f ms" % (resid_all.std() * 1e3))
    P_med = float(np.median(gn))

    print("\n6. LOAD DEPENDENCE (single-period intervals; I_fc is the BUS-SIDE INA253 current, P = V_bus*I_fc)")
    print(HR)
    im = np.array([R["i_mean"] for R in good]); pm = np.array([R["p_mean"] for R in good])
    qq = np.array([R["q"] for R in good])
    for lab, x in (("mean I_fc A", im), ("mean P_bus W", pm)):
        ok = ~np.isnan(x)
        cc = np.corrcoef(x[ok], gi[ok])[0, 1]
        sl, ic = np.polyfit(x[ok], gi[ok], 1)
        # bootstrap CI on slope
        rng = np.random.default_rng(1)
        bs = []
        idx = np.where(ok)[0]
        for _ in range(2000):
            s = rng.choice(idx, len(idx))
            bs.append(np.polyfit(x[s], gi[s], 1)[0])
        print("  interval vs %-12s r=%+.3f slope %+.4f s per unit (95%% CI %+.4f..%+.4f) intercept %.4f s; x range %.3f..%.3f" % (
            lab, cc, sl, np.percentile(bs, 2.5), np.percentile(bs, 97.5), ic, np.nanmin(x), np.nanmax(x)))
    for lo, hi in ((-1, 0.02), (0.02, 0.15), (0.15, 0.3), (0.3, 2)):
        sel = (im >= lo) & (im < hi)
        if sel.any():
            print("  I_fc bin [%5.2f, %4.2f) A: %s" % (max(lo, 0), hi, q(gi[sel], (0, 50, 100))) + "  mean %.4f" % gi[sel].mean())
    print("  charge per interval C ", q(qq, (0, 5, 50, 95, 100)), " CV(Q)=%.3f vs CV(interval)=%.4f" % (
        qq.std() / max(qq.mean(), 1e-9), gi.std() / gi.mean()))

    print("\n7. DEPENDENCE ON POSITION IN THE SESSION (bag start is not stack start-up)")
    print(HR)
    t0s = np.array([R["t0"] for R in good]); ix = np.array([R["idx"] for R in good])
    print("  interval vs time-in-bag: r=%+.3f slope %+.2e s/s" % (np.corrcoef(t0s, gi)[0, 1], np.polyfit(t0s, gi, 1)[0]))
    for lo, hi in ((1, 2), (2, 5), (5, 50)):
        sel = (ix >= lo) & (ix < hi)
        print("  interval number %d..%d: %s" % (lo, hi - 1, q(gi[sel], (0, 50, 100))))
    print("  first purge time after bag start s ", q([I["events"][0]["t"] for I in h20 if I["events"]]))
    for I in h20:
        v = I["col"]["V_fc"]
        v0 = np.nanmedian(v[:25])
        if v0 < 5:
            print("  %s starts with V_fc %.2f V (stack start-up inside the bag)" % (I["name"], v0))
    print("  bags starting with V_fc < 5 V (start-up captured): %d" % sum(np.nanmedian(I["col"]["V_fc"][:25]) < 5 for I in h20))

    print("\n8. PRECURSOR (what the Teensy could see before onset)")
    print(HR)
    dpre = np.array([e["v_pre1"] - e["v_base"] for e in ev])
    dpre05 = np.array([e["v_pre_m05"] - e["v_base"] for e in ev])
    print("  V_fc last sample before onset minus baseline V ", q(dpre))
    print("  V_fc median over [-0.5 s, 0) minus baseline V ", q(dpre05))
    # epoch average, idle cycles vs loaded
    for lab, sel in (("I_fc base < 0.02 A", lambda e: e["i_base"] < 0.02), ("I_fc base >= 0.1 A", lambda e: e["i_base"] >= 0.1)):
        V, Ii = [], []
        for I in h20:
            for e in I["events"]:
                if np.isnan(e["i_base"]) or not sel(e):
                    continue
                s = e["k0"]
                if s - 100 < 0 or s + 25 > I["n"]:
                    continue
                V.append(I["col"]["V_fc"][s - 100:s + 25] - e["v_base"])
                Ii.append(I["col"]["I_fc"][s - 100:s + 25] - e["i_base"])
        if not V:
            continue
        V, Ii = np.nanmean(V, 0), np.nanmean(Ii, 0)
        tt = (np.arange(-100, 25)) * DT
        pick = [-100, -50, -25, -10, -5, -3, -2, -1, 0, 1, 2, 3, 5, 8, 10, 15, 24]
        print("  epoch mean (%s, n=%d): t[s]:dV_fc / dI_fc" % (lab, sum(1 for I in h20 for e in I["events"] if not np.isnan(e["i_base"]) and sel(e))))
        print("    " + "  ".join("%+.2f:%+.3f/%+.3f" % (tt[p + 100], V[p + 100], Ii[p + 100]) for p in pick))

    print("\n9. SECONDARY EVENT (cycle-phase epoch of V_fc on idle cycles: I_fc < 0.02 A throughout)")
    print(HR)
    phase_v = []
    sec = []
    for I in h20:
        on = [e["k0"] for e in I["events"]]
        for j in range(len(on) - 1):
            s, f = on[j], on[j + 1]
            if not (0.6 <= (f - s) * DT / P_med < 1.4):
                continue
            ifc = I["col"]["I_fc"][s:f]
            if np.nanmax(np.abs(ifc)) >= 0.02:
                continue
            v = I["col"]["V_fc"][s:f]
            ref = np.nanmedian(v[int(1.5 / DT):int(4.5 / DT)])
            m = int(P_med / DT)
            seg = np.full(m, np.nan)
            seg[:min(m, f - s)] = (v - ref)[:m]
            phase_v.append(seg)
            # secondary dip: 5-sample running median minimum in [1.0 s, P-1.0 s]
            lo, hi = int(1.0 / DT), (f - s) - int(1.0 / DT)
            vv = v[lo:hi] - ref
            sm = np.array([np.nanmedian(vv[max(0, i - 2):i + 3]) for i in range(len(vv))])
            i = int(np.nanargmin(sm))
            under = sm < -0.35
            durs = [(b - a_ + 1) * DT for a_, b in runs(under)]
            sec.append(((i + lo) * DT, float(sm[i]), max(durs) if durs else 0.0))
    if phase_v:
        PV = np.nanmean(phase_v, 0)
        print("  idle cycles: %d" % len(phase_v))
        for tt in np.arange(0, P_med, 0.5):
            i = int(tt / DT)
            print("    phase %5.2f s  mean dV_fc %+.3f V" % (tt, np.nanmean(PV[i:i + 25])))
        sec = np.array(sec)
        print("  per-cycle deepest smoothed dip after +1 s: time s ", q(sec[:, 0], (0, 5, 50, 95, 100)))
        print("  depth V ", q(sec[:, 1], (0, 5, 50, 95, 100)))
        print("  longest span below -0.35 V, s ", q(sec[:, 2], (0, 5, 50, 95, 100)))

    print("\n10. BUS ACROSS THE PURGE (switch_state at onset-1: bit0 FC_BUS, bit1 BT_BUS)")
    print(HR)
    for lab, cond in (("two-source (FC_BUS+BT_BUS)", lambda s: (s & 3) == 3), ("FC_BUS only", lambda s: (s & 3) == 1),
                      ("BT_BUS only", lambda s: (s & 3) == 2), ("neither", lambda s: (s & 3) == 0)):
        E = [e for e in ev if e["sw"] >= 0 and cond(e["sw"])]
        if not E:
            print("  %-28s n=0" % lab)
            continue
        print("  %-28s n=%d  V_bus drop V %s" % (lab, len(E), q([e["vbus_pre"] - e["vbus_min"] for e in E], (0, 50, 95, 100))))
        print("  %-28s       I_fc pre A %s" % ("", q([e["i_base"] for e in E], (0, 50, 95, 100))))
        print("  %-28s       I_batt rise A %s" % ("", q([e["ibatt_max"] - e["ibatt_pre"] for e in E], (0, 50, 95, 100))))
    print("  purges after a latched error (error_code != 0 at onset): %d" % sum(e["state_err"] not in (0.0,) and not np.isnan(e["state_err"]) for e in ev))

    print("\n11. TIMER PREDICTOR (prediction error e = actual onset - predicted; e < 0 = early)")
    print(HR)
    for lab, mode in (("fixed global P_med", "fixed"), ("per-bag running median of last 5", "run5"), ("per-bag running mean of last 3", "run3")):
        errs = []
        for I in h20:
            on = np.array([e["k0"] for e in I["events"]]) * DT
            for j in range(1, len(on)):
                hist = np.diff(on[:j])
                hist = hist[(hist / P_med > 0.6) & (hist / P_med < 1.4)]
                if mode == "fixed":
                    P = P_med
                elif mode == "run5":
                    if len(hist) < 3:
                        continue
                    P = np.median(hist[-5:])
                else:
                    if len(hist) < 3:
                        continue
                    P = np.mean(hist[-3:])
                gap = on[j] - on[j - 1]
                nper = max(1, round(gap / P))
                if nper != 1:
                    continue              # missing purge: handled by the unlock rule, not the lead
                errs.append(on[j] - (on[j - 1] + P))
        errs = np.array(errs) * 1e3
        print("  %-36s e ms %s" % (lab, q(errs, (0, 0.1, 1, 5, 50, 95, 99, 99.9, 100))))
        sd = errs.std(ddof=1)
        print("  %-36s sd %.1f ms; normal-model 0.1 %% early tail = mean - 3.09 sd = %.1f ms; 1e-4: mean - 3.72 sd = %.1f ms" % (
            "", sd, errs.mean() - 3.09 * sd, errs.mean() - 3.72 * sd))

    print("\n12. USABLE FRACTION (arithmetic only; terms other than lead/duration/recovery are inputs from the design)")
    print(HR)
    D99 = np.percentile([e["dur_ms"] for e in ev], 99) + 20.0
    R95 = np.nanpercentile([e["recover_ms"] for e in ev], 95)
    for lead in (60, 100, 150, 200, 300):
        for late in (40, 60):
            for coldstart in (65, 170):
                closed = lead + late + D99 + R95 + coldstart
                print("  lead %3d ms + late %2d ms + purge %.0f ms + recovery p95 %.0f ms + Ag105 cold start %3d ms = %4.0f ms closed of %.0f ms -> usable %.1f %%" % (
                    lead, late, D99, R95, coldstart, closed, P_med * 1e3, 100 * (1 - closed / (P_med * 1e3))))


if __name__ == "__main__":
    main()
