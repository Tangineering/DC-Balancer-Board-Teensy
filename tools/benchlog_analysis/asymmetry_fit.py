#!/usr/bin/env python3
"""Converter-asymmetry fit from the SD-card bench logs (WORK_QUEUE.md §1 item 6).

The HIL plant (tools/hil_electrical.py) models the FC and BT boost chains as
identical sources. The real chains differ, so a commanded droop ratio r does
not deliver a share alpha = r. This tool extracts stationary, governor-clean
windows from the BLG-derived CSVs in logs/ and fits the static droop-network
law to the (alpha, r, I_tot) triples.

Model (derived in docs/modeling/converter_asymmetry_20260901.md):

    R_F = k_d * s_F / r,      R_B = k_d * s_B / (1 - r)
    alpha = r / (rho*(1-r) + r)
            + A * r*(1-r) / ((rho*(1-r) + r) * I_tot)

with rho = s_F/s_B and A = dV0 / (k_d * s_B).  rho = 1, s_B = 1 reduces to the
system_model.md law alpha = r + dV0*r*(1-r)/(k_d*I_tot).

Anchors:
  controller_design/system_model.md:105-110, :189-203  (static law, k_d)
  teensy_controller/teensy_controller.ino:2166-2170    (RE_MAX, K_DROOP, band)
  teensy_controller/teensy_controller.ino:10534-10535  (gain map -> r_cmd)
  teensy_controller/teensy_controller.ino:10190-10270  (governor)

Usage:
  python asymmetry_fit.py --logs-dir logs --out docs/modeling/asymmetry_fit_20260901 [--fw-min N] [--plot]

numpy-only (works under .venv_benchlog); matplotlib only when --plot.
"""

import argparse
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

# ── Firmware constants (cited above) ─────────────────────────────────────────
K_DROOP = 0.30            # ohm, .ino:2167
RE_MAX = 2.014            # ohm, .ino:2166
DROOP_R_MIN = 0.15        # .ino:2170
DROOP_R_MAX = 0.85
SHARE_MINORITY_I_MIN_A = 0.30   # governor minority floor
SHARE_CL_ENTRY_A = 0.60         # closed-loop entry (2*0.30)

# Unscalable series resistance between a channel's regulated node and the bus:
# Boost.R_OUT 0.010 + RT_R_ON 0.021 + R_SHUNT 0.002 (tools/hil_electrical.py:203).
# The MDAC droop code does not set it, so it must be subtracted from a measured
# bus-referenced slope before that slope is expressed as a scale on the
# COMMANDED droop term (H2).
DROOP_FIXED_SERIES_OHM = 0.033

# ── Window-selection thresholds (documented in the companion .md) ────────────
WIN_S = 0.5               # window length, s
I_TOT_MIN = 0.60          # A, above the closed-loop entry threshold
I_CH_MIN = 0.05           # A, both channels must be conducting
SS_DARK_MAX_A = 0.02      # single-source: the dark channel's ceiling
SS_LIVE_MIN_A = 0.30      # single-source: the live channel's floor
SS_MIN_SPAN_A = 0.30      # single-source: current span a fit needs
R_STAT_PP = 0.015         # max peak-to-peak of r_cmd inside a window
ALPHA_DRIFT = 0.010       # max |mean(1st half) - mean(2nd half)| of the share
I_TOT_NOISE = 0.12        # max std(I_tot)/mean(I_tot) (ADC noise, not drift)
I_TOT_DRIFT = 0.06        # max |half-mean difference|/mean of I_tot (a ramp)
CONV_TOL = 0.02           # |alpha_mean - sp| for a converged closed-loop window
GOV_MARGIN = 0.02         # setpoint must clear the governor clip by this much


def read_fw_version(run_dir):
    """fw_version from decode_report.txt, or None when absent/unversioned."""
    path = os.path.join(run_dir, "decode_report.txt")
    if not os.path.isfile(path):
        return None
    with open(path, "r", errors="replace") as f:
        head = f.readline()
    m = re.search(r"fw_version=(\d+)", head)
    return int(m.group(1)) if m else None


def classify_mode(flags, has_v3_flags):
    """Share-loop mode for a block of flag bytes.

    flags bit0 = droop driven, bit2 = closed-loop this tick, bit3 = closed-loop
    since reset (tools/decode_benchlog.py:33-52). bits 2/3 only exist in record
    format v3 and later; older logs are labelled 'legacy'.
    """
    f = flags.astype(np.int64)
    if not np.all(f & 0x01):
        return None
    if not has_v3_flags:
        return "legacy"
    if np.all(f & 0x04):
        return "closed"
    if np.all((f & 0x04) == 0) and np.all((f & 0x08) == 0):
        return "openloop"
    return None          # mixed / HOLD -- not stationary in the sense we need


def extract_windows(name, run_dir, csv_path, fw):
    """Accepted windows from one run, plus a rejection tally."""
    data = common.load_csv(csv_path)
    rej = {}

    def bump(key, n=1):
        rej[key] = rej.get(key, 0) + n

    n = len(data["t_s"])
    if n == 0:
        bump("empty")
        return [], rej
    has_v3 = "V_fc" in data

    t = data["t_s"]
    gF, gB = data["gFC"], data["gBT"]
    I_fc, I_bt = data["I_fc"], data["I_batt"]
    with np.errstate(divide="ignore", invalid="ignore"):
        r_cmd = gB / (gF + gB)
    I_tot = I_fc + I_bt
    with np.errstate(divide="ignore", invalid="ignore"):
        alpha = I_fc / I_tot

    dt = np.median(np.diff(t)) if n > 1 else 1e-3
    step = max(int(round(WIN_S / dt)), 2)

    out = []
    for i0 in range(0, n - step + 1, step):
        s = slice(i0, i0 + step)
        if np.any(data["fault_flags"][s] != 0):
            bump("fault_flag_set")
            continue
        mode = classify_mode(data["flags"][s], has_v3)
        if mode is None:
            bump("mode_mixed_or_droop_idle")
            continue
        it = I_tot[s]
        if np.min(it) <= I_TOT_MIN:
            bump("i_tot_below_0.60A")
            continue
        if np.min(I_fc[s]) < I_CH_MIN or np.min(I_bt[s]) < I_CH_MIN:
            bump("channel_dark")
            continue
        rc = r_cmd[s]
        if not np.all(np.isfinite(rc)):
            bump("mdac_gains_zero")
            continue
        if np.ptp(rc) > R_STAT_PP:
            bump("r_cmd_nonstationary")
            continue
        sp = data["share_sp"][s]
        if np.ptp(sp) > 1e-9:
            bump("setpoint_moved")
            continue
        sp0 = float(sp[0])
        if sp0 < DROOP_R_MIN or sp0 > DROOP_R_MAX:
            bump("setpoint_out_of_band(cut)")
            continue
        # Governor clip (.ino:10250-10270): lo = SHARE_MINORITY_I_MIN_A /
        # share_govTotAFilt, hi = 1 - lo, lo clamped to 0.5. I_tot is stationary
        # inside an accepted window (I_TOT_RIPPLE), and the governor filter time
        # constant (~20 ticks) is far shorter than the window, so the window mean
        # stands in for the filtered total. The GOVERNED setpoint, not the raw
        # one, is what a converged closed loop delivers.
        lo = min(SHARE_MINORITY_I_MIN_A / float(np.mean(it)), 0.5)
        sp_gov = min(max(sp0, lo), 1.0 - lo)
        # Reject only when the clip sits within GOV_MARGIN of the raw setpoint:
        # there the filtered/mean-total substitution could flip the clip state.
        if abs(sp_gov - sp0) > 1e-12 and abs(sp0 - lo) < GOV_MARGIN:
            bump("governor_clip_ambiguous")
            continue
        it_m = float(np.mean(it))
        hh = len(it) // 2
        if float(np.std(it)) / it_m > I_TOT_NOISE:
            bump("i_tot_noisy")
            continue
        if abs(float(np.mean(it[:hh])) - float(np.mean(it[hh:]))) / it_m > I_TOT_DRIFT:
            bump("i_tot_ramping")
            continue
        al = alpha[s]
        h = len(al) // 2
        if abs(float(np.mean(al[:h])) - float(np.mean(al[h:]))) > ALPHA_DRIFT:
            bump("alpha_drifting")
            continue
        a_mean = float(np.mean(al))
        if mode in ("closed", "legacy") and abs(a_mean - sp_gov) > CONV_TOL:
            bump("closed_loop_not_converged")
            continue
        out.append(dict(
            log=name, fw=fw, t0=float(t[i0]), t1=float(t[i0 + step - 1]),
            mode=mode, share_sp=sp_gov, r_cmd=float(np.mean(rc)), alpha=a_mean,
            I_tot=float(np.mean(it)), I_fc=float(np.mean(I_fc[s])),
            I_batt=float(np.mean(I_bt[s])), V_bus=float(np.mean(data["V_bus"][s])),
            gFC=float(np.mean(gF[s])), gBT=float(np.mean(gB[s])),
            n_samples=int(step),
        ))
    return out, rej


# ── Models ───────────────────────────────────────────────────────────────────
def m1_predict(r, itot, dv0):
    return r + dv0 * r * (1.0 - r) / (K_DROOP * itot)


def m2_predict(r, itot, A, rho):
    den = rho * (1.0 - r) + r
    return r / den + A * r * (1.0 - r) / (den * itot)


def fit_m1(r, itot, alpha):
    """Through-origin least squares on x = r(1-r)/(k_d*I_tot)."""
    x = r * (1.0 - r) / (K_DROOP * itot)
    y = alpha - r
    dv0 = float(np.dot(x, y) / np.dot(x, x))
    return dict(dV0_V=dv0)


def fit_m2(r, itot, alpha):
    """Two-parameter fit by grid seed + Gauss-Newton (no scipy)."""
    def resid(p):
        return m2_predict(r, itot, p[0], p[1]) - alpha

    best, bp = np.inf, None
    for A in np.linspace(-1.0, 1.0, 81):
        for rho in np.linspace(0.6, 1.6, 101):
            c = float(np.sum(resid((A, rho)) ** 2))
            if c < best:
                best, bp = c, np.array([A, rho])
    p = bp.copy()
    for _ in range(200):
        r0 = resid(p)
        J = np.empty((len(r0), 2))
        for k in range(2):
            h = 1e-6 * max(abs(p[k]), 1e-3)
            q = p.copy(); q[k] += h
            J[:, k] = (resid(q) - r0) / h
        try:
            dp = np.linalg.lstsq(J, -r0, rcond=None)[0]
        except np.linalg.LinAlgError:
            break
        p = p + dp
        if np.max(np.abs(dp)) < 1e-12:
            break
    A, rho = float(p[0]), float(p[1])
    return dict(A_V_per_ohm=A, rho_sF_over_sB=rho,
                dV0_V_if_sB_1=A * K_DROOP)


def rms(pred, alpha):
    return float(np.sqrt(np.mean((pred - alpha) ** 2)))


def bootstrap(fitfn, r, itot, alpha, n_boot=2000, seed=20260901):
    rng = np.random.default_rng(seed)
    keys, draws = None, []
    n = len(r)
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        try:
            f = fitfn(r[idx], itot[idx], alpha[idx])
        except Exception:
            continue
        if keys is None:
            keys = sorted(f)
        draws.append([f[k] for k in keys])
    if not draws:
        return {}
    D = np.array(draws)
    return {k: [float(np.percentile(D[:, j], 2.5)),
                float(np.percentile(D[:, j], 97.5))]
            for j, k in enumerate(keys)}


def median_ratio_ci(a, b, n_boot=4000, seed=20260901):
    """CI95 on median(a)/median(b) by paired-independent resampling."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < 2 or len(b) < 2:
        return None
    rng = np.random.default_rng(seed)
    d = [float(np.median(rng.choice(a, len(a)))
               / np.median(rng.choice(b, len(b)))) for _ in range(n_boot)]
    return [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))]


def median_ci(a, n_boot=4000, seed=20260901):
    a = np.asarray(a, float)
    a = a[np.isfinite(a)]
    if len(a) < 2:
        return None
    rng = np.random.default_rng(seed)
    d = [float(np.median(rng.choice(a, len(a)))) for _ in range(n_boot)]
    return [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))]


def per_channel_droop(W):
    """Per-channel V_0 and effective droop resistance.

    V_bus = V_0x - R_ex * I_x, so within a group of windows that share ONE run
    and ONE commanded gain, regressing V_bus on the channel current gives the
    intercept V_0x and slope -R_ex. Grouping by run matters: V_0x drifts between
    runs (supply setting, pack state), so pooling runs fits a between-run
    voltage spread as if it were droop and biases R_ex low.
    """
    out = []
    logs = sorted({w["log"] for w in W})
    for chan, gkey, ikey in (("FC", "gFC", "I_fc"), ("BT", "gBT", "I_batt")):
        for lg in logs:
            sel = [w for w in W if w["log"] == lg]
            if len(sel) < 4:
                continue
            g = np.array([w[gkey] for w in sel])
            v = np.array([w["V_bus"] for w in sel])
            i = np.array([w[ikey] for w in sel])
            bins = np.round(np.log(np.maximum(g, 1e-9)) / 0.02)
            for b in np.unique(bins):
                m = bins == b
                if m.sum() < 4 or np.ptp(i[m]) < 0.15:
                    continue
                A = np.column_stack([np.ones(int(m.sum())), i[m]])
                coef, *_ = np.linalg.lstsq(A, v[m], rcond=None)
                gbar = float(np.mean(g[m]))
                R_meas = -float(coef[1])
                R_cmd = RE_MAX * gbar
                res = v[m] - A @ coef
                dof = max(int(m.sum()) - 2, 1)
                sxx = float(np.sum((i[m] - np.mean(i[m])) ** 2))
                se = float(np.sqrt(np.sum(res ** 2) / dof / sxx)) if sxx > 0 else None
                out.append(dict(log=lg, channel=chan, g_cmd=gbar, n=int(m.sum()),
                                V0_V=float(coef[0]), R_meas_ohm=R_meas,
                                R_cmd_ohm=R_cmd,
                                # H2: the scale applies to the COMMANDED droop
                                # term only, so the fixed series copper comes off
                                # the bus-referenced slope first.
                                s_scale=((R_meas - DROOP_FIXED_SERIES_OHM) / R_cmd
                                         if R_cmd > 0 else None),
                                s_scale_uncorrected=(R_meas / R_cmd if R_cmd > 0
                                                     else None),
                                slope_se_ohm=se,
                                I_span_A=float(np.ptp(i[m]))))
    return out


def single_source_windows(name, csv_path, fw):
    """Windows where exactly ONE channel conducts (the single-source regime).

    The shared-regime selection rejects these as `channel_dark`. They are the
    DIRECT measurement of each channel's own droop, with no parallel partner to
    disentangle, and the corpus contains both channels (H1).
    """
    data = common.load_csv(csv_path)
    n = len(data["t_s"])
    if n == 0:
        return []
    has_v3 = "V_fc" in data
    t, gF, gB = data["t_s"], data["gFC"], data["gBT"]
    I_fc, I_bt = data["I_fc"], data["I_batt"]
    dt = np.median(np.diff(t)) if n > 1 else 1e-3
    step = max(int(round(WIN_S / dt)), 2)
    out = []
    for i0 in range(0, n - step + 1, step):
        sl = slice(i0, i0 + step)
        if np.any(data["fault_flags"][sl] != 0):
            continue
        if classify_mode(data["flags"][sl], has_v3) is None:
            continue
        for chan, g, live, dark in (("FC", gF, I_fc, I_bt),
                                    ("BT", gB, I_bt, I_fc)):
            if np.max(np.abs(dark[sl])) > SS_DARK_MAX_A:
                continue
            if np.min(live[sl]) < SS_LIVE_MIN_A:
                continue
            gv = g[sl]
            if not np.all(np.isfinite(gv)) or np.all(gv <= 0):
                continue
            if np.ptp(gv) / max(float(np.mean(gv)), 1e-9) > 0.01:
                continue
            lv = live[sl]
            if float(np.std(lv)) / float(np.mean(lv)) > I_TOT_NOISE:
                continue
            out.append(dict(log=name, fw=fw, channel=chan, t0=float(t[i0]),
                            g_cmd=float(np.mean(gv)), I=float(np.mean(lv)),
                            V_bus=float(np.mean(data["V_bus"][sl])),
                            n_samples=int(step)))
    return out


def fit_single_source(SS):
    """Per-run, per-channel regression of V_bus on the live channel's current."""
    out = []
    for lg in sorted({w["log"] for w in SS}):
        for chan in ("FC", "BT"):
            sel = [w for w in SS if w["log"] == lg and w["channel"] == chan]
            if len(sel) < 4:
                continue
            i = np.array([w["I"] for w in sel])
            v = np.array([w["V_bus"] for w in sel])
            g = np.array([w["g_cmd"] for w in sel])
            if np.ptp(i) < SS_MIN_SPAN_A:
                continue
            if np.ptp(g) / max(float(np.mean(g)), 1e-9) > 0.02:
                continue
            A = np.column_stack([np.ones(len(i)), i])
            coef, *_ = np.linalg.lstsq(A, v, rcond=None)
            res = v - A @ coef
            sxx = float(np.sum((i - np.mean(i)) ** 2))
            se = float(np.sqrt(np.sum(res ** 2) / max(len(i) - 2, 1) / sxx))
            gbar = float(np.mean(g))
            K = -float(coef[1])
            out.append(dict(log=lg, channel=chan, n=len(i), g_cmd=gbar,
                            V0_V=float(coef[0]), K_ohm=K, slope_se_ohm=se,
                            I_span_A=float(np.ptp(i)),
                            R_cmd_ohm=RE_MAX * gbar,
                            s_scale=((K - DROOP_FIXED_SERIES_OHM)
                                     / (RE_MAX * gbar))))
    return out


def reconcile_ratios(single_fits):
    """Shared/single ratio arithmetic (companion document section 8).

    Two DIFFERENT ratio quantities are in play and must not be swapped:
      * `ratio_incl_series` = R_F/R_B of the BUS-REFERENCED slopes -- what the
        parallel-network identity 1 + R_other/R_x consumes.
      * `ratio_cmd_only` = s_F/s_B, the scale on the COMMANDED droop term with
        DROOP_FIXED_SERIES_OHM removed -- what a plant `droop_scale` needs.
    """
    def med(chan, key):
        v = [f[key] for f in single_fits if f["channel"] == chan]
        return float(np.median(v)) if v else None

    KF, KB = med("FC", "K_ohm"), med("BT", "K_ohm")
    sF, sB = med("FC", "s_scale"), med("BT", "s_scale")
    if None in (KF, KB, sF, sB):
        return {}

    # Shared regime at r = 0.5: both channels command g = K_DROOP/(RE_MAX*0.5).
    g_half = K_DROOP / (RE_MAX * 0.5)
    RF = DROOP_FIXED_SERIES_OHM + RE_MAX * g_half * sF
    RB = DROOP_FIXED_SERIES_OHM + RE_MAX * g_half * sB
    shared = RF * RB / (RF + RB)
    s_bar = 0.5 * (sF + sB)
    R_eq = DROOP_FIXED_SERIES_OHM + RE_MAX * g_half * s_bar
    shared_matched = 0.5 * R_eq
    single_pooled = 0.5 * (RF + RB)

    return dict(
        K_single_FC_ohm=KF, K_single_BT_ohm=KB,
        ratio_incl_series_F_over_B=KF / KB,
        s_single_FC=sF, s_single_BT=sB, ratio_cmd_only_sF_over_sB=sF / sB,
        g_cmd_FC=med("FC", "g_cmd"), g_cmd_BT=med("BT", "g_cmd"),
        # Branch A -- the bench single anchor read as ONE named channel.
        pred_ratio_if_single_is_FC=1.0 + RB / RF,
        pred_ratio_if_single_is_BT=1.0 + RF / RB,
        # Branch B -- the bench single anchor read as a POOLED both-channel
        # figure, which is what H1 establishes it to be.
        pred_ratio_pooled_single=single_pooled / shared,
        shared_pred_ohm=shared, shared_pred_if_matched_ohm=shared_matched,
        shared_mismatch_effect_frac=shared / shared_matched - 1.0,
        bench_shared_ohm=0.0740, bench_single_ohm=0.1615,
        bench_ratio=0.1615 / 0.0740)


def make_plots(W, fits, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    r = np.array([w["r_cmd"] for w in W])
    a = np.array([w["alpha"] for w in W])
    it = np.array([w["I_tot"] for w in W])
    fw = np.array([w["fw"] if w["fw"] else 0 for w in W])
    mode = np.array([w["mode"] for w in W])

    fig, ax = plt.subplots(figsize=(7.5, 5))
    x = r * (1 - r) / it
    for md, mk in (("closed", "o"), ("openloop", "s"), ("legacy", "^")):
        m = mode == md
        if m.any():
            ax.scatter(x[m], (a - r)[m], s=14, marker=mk, alpha=0.55, label=md)
    xs = np.linspace(0, x.max() * 1.05, 100)
    ax.plot(xs, fits["M1"]["params"]["dV0_V"] / K_DROOP * xs, "k-",
            label=f"M1  dV0={fits['M1']['params']['dV0_V']:+.4f} V")
    ax.set_xlabel(r"$r(1-r)/I_{tot}$  (A$^{-1}$)")
    ax.set_ylabel(r"$\alpha - r$")
    ax.axhline(0, color="0.7", lw=0.8)
    ax.legend(); ax.grid(alpha=0.3)
    ax.set_title("Converter asymmetry: delivered-minus-commanded share")
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "alpha_minus_r.png"), dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.5, 6))
    sc = ax.scatter(r, a, c=it, s=16, cmap="viridis")
    lim = [min(r.min(), a.min()) - 0.02, max(r.max(), a.max()) + 0.02]
    ax.plot(lim, lim, "k--", lw=0.9, label="ideal $\\alpha=r$")
    fig.colorbar(sc, ax=ax, label=r"$I_{tot}$ (A)")
    ax.set_xlabel("$r_{cmd}$"); ax.set_ylabel(r"$\alpha$ delivered")
    ax.legend(); ax.grid(alpha=0.3); ax.set_title("Commanded vs delivered share")
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "r_vs_alpha.png"), dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    for v in sorted(set(fw.tolist())):
        m = fw == v
        if m.sum() < 3:
            continue
        ax.scatter(x[m], (a - r)[m], s=14, alpha=0.6, label=f"fw {v} (n={m.sum()})")
    ax.plot(xs, fits["M1"]["params"]["dV0_V"] / K_DROOP * xs, "k-", lw=1)
    ax.set_xlabel(r"$r(1-r)/I_{tot}$  (A$^{-1}$)"); ax.set_ylabel(r"$\alpha - r$")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    ax.set_title("Asymmetry stratified by firmware version")
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "by_firmware.png"), dpi=140)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs-dir", default="logs")
    ap.add_argument("--out", default="docs/modeling/asymmetry_fit_20260901")
    ap.add_argument("--fw-min", type=int, default=None)
    ap.add_argument("--plot", action="store_true")
    args = ap.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    windows, single_windows, corpus = [], [], []
    for name in sorted(os.listdir(args.logs_dir)):
        run_dir = os.path.join(args.logs_dir, name)
        csv_path = os.path.join(run_dir, name + ".csv")
        if not os.path.isdir(run_dir) or not os.path.isfile(csv_path):
            continue
        fw = read_fw_version(run_dir)
        if args.fw_min is not None and (fw is None or fw < args.fw_min):
            corpus.append(dict(log=name, fw=fw, accepted=0,
                               rejects={"fw_below_min": 1}))
            continue
        try:
            w, rej = extract_windows(name, run_dir, csv_path, fw)
        except Exception as exc:                       # corrupt/partial CSV
            corpus.append(dict(log=name, fw=fw, accepted=0,
                               rejects={"load_error: " + str(exc)[:80]: 1}))
            continue
        windows.extend(w)
        try:
            ss = single_source_windows(name, csv_path, fw)
        except Exception:
            ss = []
        single_windows.extend(ss)
        corpus.append(dict(log=name, fw=fw, accepted=len(w),
                           single_source=len(ss), rejects=rej))

    cols = ["log", "fw", "t0", "t1", "mode", "share_sp", "r_cmd", "alpha",
            "I_tot", "I_fc", "I_batt", "V_bus", "gFC", "gBT", "n_samples"]
    with open(os.path.join(args.out, "windows.csv"), "w", newline="") as f:
        f.write(",".join(cols) + "\n")
        for w in windows:
            f.write(",".join("" if w[c] is None else str(w[c]) for c in cols) + "\n")

    summary = dict(n_windows=len(windows), constants=dict(
        K_DROOP=K_DROOP, RE_MAX=RE_MAX, window_s=WIN_S, I_TOT_MIN=I_TOT_MIN,
        CONV_TOL=CONV_TOL, ALPHA_DRIFT=ALPHA_DRIFT,
        I_TOT_NOISE=I_TOT_NOISE, I_TOT_DRIFT=I_TOT_DRIFT, GOV_MARGIN=GOV_MARGIN, R_STAT_PP=R_STAT_PP))

    if len(windows) >= 4:
        r = np.array([w["r_cmd"] for w in windows])
        it = np.array([w["I_tot"] for w in windows])
        a = np.array([w["alpha"] for w in windows])

        p1 = fit_m1(r, it, a)
        p2 = fit_m2(r, it, a)
        summary["M1"] = dict(params=p1, ci95=bootstrap(fit_m1, r, it, a),
                             rms=rms(m1_predict(r, it, p1["dV0_V"]), a), n=len(r))
        summary["M2"] = dict(params=p2, ci95=bootstrap(fit_m2, r, it, a, n_boot=400),
                             rms=rms(m2_predict(r, it, p2["A_V_per_ohm"],
                                                p2["rho_sF_over_sB"]), a), n=len(r))
        summary["M0_null"] = dict(rms=rms(r, a), n=len(r))

        # F-test style comparison of M2 over M1 (1 extra parameter).
        ss1 = np.sum((m1_predict(r, it, p1["dV0_V"]) - a) ** 2)
        ss2 = np.sum((m2_predict(r, it, p2["A_V_per_ohm"],
                                 p2["rho_sF_over_sB"]) - a) ** 2)
        dof = max(len(r) - 2, 1)
        summary["M2_vs_M1_F"] = float((ss1 - ss2) / (ss2 / dof)) if ss2 > 0 else None

        strat = {}
        for v in sorted({w["fw"] for w in windows if w["fw"]}):
            m = np.array([w["fw"] == v for w in windows])
            if m.sum() < 4:
                continue
            pv = fit_m1(r[m], it[m], a[m])
            strat[str(v)] = dict(n=int(m.sum()), **pv,
                                 ci95=bootstrap(fit_m1, r[m], it[m], a[m], 1000),
                                 rms=rms(m1_predict(r[m], it[m], pv["dV0_V"]), a[m]))
        summary["by_firmware_M1"] = strat

        bymode = {}
        for md in sorted({w["mode"] for w in windows}):
            m = np.array([w["mode"] == md for w in windows])
            if m.sum() < 4:
                continue
            pv = fit_m1(r[m], it[m], a[m])
            bymode[md] = dict(n=int(m.sum()), **pv,
                              ci95=bootstrap(fit_m1, r[m], it[m], a[m], 1000))
        summary["by_mode_M1"] = bymode

        # r_cmd required to deliver alpha = 0.50 (M1 inverse, small-signal).
        dv0 = p1["dV0_V"]
        req = {}
        for i_t in (0.5, 1.0, 2.0):
            lo, hi = 0.05, 0.95
            for _ in range(200):
                mid = 0.5 * (lo + hi)
                if m1_predict(mid, i_t, dv0) < 0.5:
                    lo = mid
                else:
                    hi = mid
            req[f"{i_t:.1f}A"] = 0.5 * (lo + hi)
        summary["r_cmd_for_alpha_0.50_M1"] = req

        pcd = per_channel_droop(windows)
        summary["per_channel_droop"] = pcd

        def _col(rows, chan, key):
            return [r[key] for r in rows
                    if r["channel"] == chan and r.get(key) is not None]

        # L1/L3: medians, their CIs, the ratio CI, and the leverage disclosure.
        shared_stats = {}
        for chan in ("FC", "BT"):
            R = _col(pcd, chan, "R_meas_ohm")
            if not R:
                continue
            shared_stats[chan] = dict(
                n_groups=len(R),
                R_meas_ohm_median=float(np.median(R)),
                R_meas_ohm_ci95=median_ci(R),
                s_scale_median=float(np.median(_col(pcd, chan, "s_scale"))),
                s_scale_ci95=median_ci(_col(pcd, chan, "s_scale")),
                s_scale_uncorrected_median=float(
                    np.median(_col(pcd, chan, "s_scale_uncorrected"))),
                slope_se_ohm_median=float(
                    np.median(_col(pcd, chan, "slope_se_ohm"))),
                group_n_min=int(min(r["n"] for r in pcd if r["channel"] == chan)),
                group_n_max=int(max(r["n"] for r in pcd if r["channel"] == chan)),
                I_span_A_min=float(min(_col(pcd, chan, "I_span_A"))),
                I_span_A_max=float(max(_col(pcd, chan, "I_span_A"))))
        if len(shared_stats) == 2:
            shared_stats["ratio_sF_over_sB"] = float(
                shared_stats["FC"]["s_scale_median"]
                / shared_stats["BT"]["s_scale_median"])
            shared_stats["ratio_sF_over_sB_ci95"] = median_ratio_ci(
                _col(pcd, "FC", "s_scale"), _col(pcd, "BT", "s_scale"))
            shared_stats["ratio_incl_series_RF_over_RB"] = float(
                shared_stats["FC"]["R_meas_ohm_median"]
                / shared_stats["BT"]["R_meas_ohm_median"])
            shared_stats["ratio_incl_series_ci95"] = median_ratio_ci(
                _col(pcd, "FC", "R_meas_ohm"), _col(pcd, "BT", "R_meas_ohm"))
        summary["shared_regime_per_channel"] = shared_stats

        # H1: the single-source regime, measured directly on both channels.
        ssf = fit_single_source(single_windows)
        summary["single_source_fits"] = ssf
        ss_stats = {}
        for chan in ("FC", "BT"):
            K = [f["K_ohm"] for f in ssf if f["channel"] == chan]
            if not K:
                continue
            ss_stats[chan] = dict(
                n_runs=len(K), K_ohm_median=float(np.median(K)),
                K_ohm_ci95=median_ci(K),
                slope_se_ohm_median=float(np.median(
                    [f["slope_se_ohm"] for f in ssf if f["channel"] == chan])),
                V0_V_median=float(np.median(
                    [f["V0_V"] for f in ssf if f["channel"] == chan])),
                g_cmd_median=float(np.median(
                    [f["g_cmd"] for f in ssf if f["channel"] == chan])),
                s_scale_median=float(np.median(
                    [f["s_scale"] for f in ssf if f["channel"] == chan])),
                s_scale_ci95=median_ci(
                    [f["s_scale"] for f in ssf if f["channel"] == chan]),
                I_span_A_median=float(np.median(
                    [f["I_span_A"] for f in ssf if f["channel"] == chan])),
                logs=sorted({f["log"] for f in ssf if f["channel"] == chan}))
        if len(ss_stats) == 2:
            ss_stats["ratio_cmd_only_sF_over_sB_ci95"] = median_ratio_ci(
                [f["s_scale"] for f in ssf if f["channel"] == "FC"],
                [f["s_scale"] for f in ssf if f["channel"] == "BT"])
            ss_stats["ratio_incl_series_ci95"] = median_ratio_ci(
                [f["K_ohm"] for f in ssf if f["channel"] == "FC"],
                [f["K_ohm"] for f in ssf if f["channel"] == "BT"])
        summary["single_source_regime"] = ss_stats
        summary["ratio_reconciliation"] = reconcile_ratios(ssf)
        summary["n_single_source_windows"] = len(single_windows)
        summary["coverage"] = dict(
            r_cmd_min=float(r.min()), r_cmd_max=float(r.max()),
            I_tot_min=float(it.min()), I_tot_max=float(it.max()),
            inv_I_min=float((1.0 / it).min()), inv_I_max=float((1.0 / it).max()),
            n_logs=len({w["log"] for w in windows}),
            modes={m: int(sum(1 for w in windows if w["mode"] == m))
                   for m in sorted({w["mode"] for w in windows})})
        # Sense-path degeneracy bound (M3): an INA zero-offset pair
        # (dF, dB) shifts the MEASURED share by (dF - alpha*(dF+dB))/I_tot,
        # which has the same 1/I_tot form as dV0. The equivalent dV0 it can
        # masquerade as, at r = 0.5, is k_d*(dF - 0.5*(dF+dB))/0.25.
        # M5: the plant INJECTS NoiseConfig's defaults {"I_fc": 0.020,
        # "I_batt": 0.0} (hil_electrical.py:415-421), not the fitted medians
        # (+0.0199 / +0.0002), so the equivalence must be computed on what is
        # actually injected.
        dF, dB = 0.020, 0.0
        summary["M3_sense_offset_equivalent_dV0_V"] = float(
            K_DROOP * (dF - 0.5 * (dF + dB)) / 0.25)

        if args.plot:
            make_plots(windows, summary, args.out)

    summary["corpus"] = corpus
    with open(os.path.join(args.out, "fit_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print(f"windows accepted: {len(windows)}")
    if "M1" in summary:
        print("M1 dV0 = {:+.4f} V  CI95 {}  rms {:.4f}".format(
            summary["M1"]["params"]["dV0_V"],
            [round(x, 4) for x in summary["M1"]["ci95"]["dV0_V"]],
            summary["M1"]["rms"]))
        print("M2 A = {:+.4f}  rho = {:.4f}  rms {:.4f}".format(
            summary["M2"]["params"]["A_V_per_ohm"],
            summary["M2"]["params"]["rho_sF_over_sB"], summary["M2"]["rms"]))
        print("null (alpha=r) rms {:.4f}".format(summary["M0_null"]["rms"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
