#!/usr/bin/env python3
"""Spectral analysis of the bench-log voltage rails against flywheel speed.

Question: do the board's voltage signals (V_bus, V_fc, V_batt, V_chg, V_rgn)
carry content that tracks how fast the dyno flywheel is turning?

Method (results write-up: "Rail Ripple vs Flywheel Speed", 2026-10-23):
  1. Load every logs/*.BLG with blg_arrays.load_blg(). Keep non-HIL runs on
     fw >= 8; earlier firmware had the encoder on the wrong pin (fw v8 row of
     docs/firmware-versions.md), so its velocity is meaningless.
  2. Resample each run onto a uniform grid at its median sample interval (the
     logger samples once per main-loop pass, ~1.13 ms / ~885 Hz).
  3. Cut 2.0 s Hann windows at a 0.5 s hop; drop any window with a fault flag.
     Flywheel rotation rate comes from encoder_pos (BLG v6+; 120 slots before
     fw v18, 90 after, x2 quadrature decode) or from |v_act| for v4/v5 logs.
     A window is "steady" when its two halves differ in distance by < 8 %.
  4. Per window: one-sided PSD of each linearly detrended channel, broadband
     rms (1 Hz .. Nyquist-5), and the PSD re-sampled on an ORDER axis
     (frequency / flywheel rev rate), where shaft-locked tones line up.
  5. Report: rank correlations of ripple vs speed and vs load current (with
     the partial correlation on current), tone peak/sideband ratios at the
     drivetrain orders against a speed-shuffled null, tone amplitude by speed
     bin, and peak tracking; then three figures.

Drivetrain orders (x flywheel rev rate), from controller_design_MIMO/
mimo_system_model.md: r_fly 0.0762 m, tire r_t 0.033 m, motor->tire 6.86:1,
spur 70T/29T. Tire = r_fly/r_t = 2.309, motor = 2.309 x 6.86 = 15.84,
intermediate shaft = 15.84 / (70/29) = 6.56.

Usage:
  python tools/rail_spectral/rail_spectral.py [--logs logs] [--out DIR]
         [--cache FILE [--rebuild]] [--no-figures]

Writes DIR/report.txt and DIR/fig1_campbell.png, fig2_orders.png,
fig3_amplitude.png. DIR defaults to logs/rail_spectral/ (git-ignored). A full
pass over logs/ takes ~2 min and holds ~1 GB of spectra in memory; --cache
FILE pickles the windows (~1 GB on disk) and reuses them on later runs unless
--rebuild. Needs numpy + scipy; the figures also need matplotlib.
"""
import argparse
import pickle
import sys
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy import signal, stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blg_arrays import load_blg  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

# ── Geometry (controller_design_MIMO/mimo_system_model.md; .ino FLYWHEEL_RADIUS_M)
R_FLY = 0.0762          # m, flywheel rolling radius = encoder/inertia radius
R_TIRE = 0.033          # m, tire rolling radius (model value)
PHI = 6.86              # motor -> tire reduction
SPUR = 70 / 29          # spur stage
ORDER_TIRE = R_FLY / R_TIRE
ORDER_MOTOR = ORDER_TIRE * PHI
ORDER_SPUR = ORDER_MOTOR / SPUR
QUAD_DECODE = 2


def encoder_slots(fw):
    """Slots per flywheel rev on the disc fitted when this firmware ran.
    fw v18 (2026-08-25) swapped the 120-slot disc for a 90-slot one."""
    return 90 if fw >= 18 else 120


# ── Analysis parameters
VOLT_CH = ["V_bus", "V_fc", "V_batt", "V_chg", "V_rgn"]
CTX_CH = ["I_fc", "I_batt", "I_cmd", "v_act"]       # mechanism cross-checks
WIN_S = 2.0
HOP_S = 0.5
STEADY_TOL = 0.08
MIN_FW = 8
HZ = np.linspace(0, 440, 4401)       # common frequency grid, 0.1 Hz
ORD = np.linspace(0, 40, 4001)       # common order grid, 0.01
MIN_F_FLY_FOR_ORDERS = 0.3           # Hz; below this the order axis is meaningless
TONES = {  # name: order (measured peak positions; predicted values in brackets in the report)
    "flywheel x1": 1.0, "flywheel x2": 2.0,
    "tire x1": 2.29, "tire x2": 4.62, "tire x4": 9.21,
    "spur x2": 13.12, "spur x3": 19.67,
    "motor x1": 15.83, "motor x2": 31.68,
}
SPEED_BINS = [0.4, 0.8, 1.2, 1.6, 2.0, 2.5, 3.3]

_trapz = getattr(np, "trapezoid", None) or np.trapz


def _psd(x, w, fs):
    X = np.fft.rfft(signal.detrend(x, type="linear") * w)
    return 2 * np.abs(X) ** 2 / (fs * (w ** 2).sum())


def _band_rms(P, f, lo, hi):
    m = (f >= lo) & (f < hi)
    return float(np.sqrt(_trapz(P[m], f[m]))) if m.sum() > 1 else 0.0


def run_windows(name, run, channels=VOLT_CH + CTX_CH):
    """Window one loaded run (blg_arrays.load_blg() dict). Returns a list of
    per-window dicts; see the module docstring, step 3-4."""
    s, fw = run["sig"], run["fw"]
    t = s["t"]
    if len(t) < 3000:
        return []
    fs = 1.0 / np.median(np.diff(t))
    n = int(t[-1] * fs)
    tg = np.arange(n) / fs
    chans = [c for c in channels if c in s]
    sig = {c: np.interp(tg, t, s[c]) for c in chans}
    v_abs = np.interp(tg, t, np.abs(s["v_act"]))
    enc = np.interp(tg, t, s["enc"].astype(float)) if s["enc"] is not None else None
    fault = np.interp(tg, t, s["fault"].astype(float))
    nw, hop = int(WIN_S * fs), int(HOP_S * fs)
    w = signal.windows.hann(nw)
    f = np.fft.rfftfreq(nw, 1 / fs)
    slots = encoder_slots(fw)
    out = []
    for i0 in range(0, n - nw, hop):
        sl = slice(i0, i0 + nw)
        if fault[sl].max() > 0:
            continue
        if enc is not None:
            f_fly = abs(enc[i0 + nw - 1] - enc[i0]) / (QUAD_DECODE * slots) / (nw / fs)
            h = nw // 2
            a, b = abs(enc[i0 + h] - enc[i0]), abs(enc[i0 + nw - 1] - enc[i0 + h])
            steady = (a + b) > 0 and abs(a - b) / (a + b) < STEADY_TOL
        else:
            vm = v_abs[sl].mean()
            f_fly = vm / (2 * np.pi * R_FLY)
            steady = vm > 0 and v_abs[sl].std() / vm < STEADY_TOL
        rec = dict(file=name, fw=fw, fs=fs, t0=i0 / fs, f_fly=float(f_fly),
                   vmean=float(f_fly * 2 * np.pi * R_FLY), steady=bool(steady),
                   I_tot=float(np.mean(sig["I_fc"][sl] + sig["I_batt"][sl])))
        top = fs / 2 - 5
        for c in chans:
            P = _psd(sig[c][sl], w, fs)
            rec[c + "_rms"] = _band_rms(P, f, 1, top)
            rec[c + "_rms_lo"] = _band_rms(P, f, 1, 20)
            rec[c + "_rms_hi"] = _band_rms(P, f, 20, top)
            # float32: ~4k windows x 9 channels x 8.4k bins is ~1 GB at float32
            rec[c + "_P"] = np.interp(HZ, f, P, right=np.nan).astype(np.float32)
            rec[c + "_Pord"] = (np.interp(ORD, f / f_fly, P, right=np.nan).astype(np.float32)
                                if f_fly > MIN_F_FLY_FOR_ORDERS else None)
        out.append(rec)
    return out


def collect(logs_dir, log=print):
    """Window every eligible run under logs_dir. Returns (windows, runs)."""
    windows, runs = [], []
    for p in sorted(Path(logs_dir).glob("*.BLG")):
        try:
            run = load_blg(p)
        except ValueError as e:
            log(f"skip {p.name}: {e}")
            continue
        if run["fw"] is None or run["fw"] < MIN_FW or run["hil"]:
            continue
        ws = run_windows(p.name, run)
        if ws:
            runs.append(p.name)
            windows += ws
    return windows, runs


# ── Statistics ────────────────────────────────────────────────────────────────

def _partial_rank(x, y, z):
    """Spearman-style partial correlation of x, y controlling for z."""
    rx, ry, rz = map(stats.rankdata, (x, y, z))
    ex = rx - np.polyval(np.polyfit(rz, rx, 1), rz)
    ey = ry - np.polyval(np.polyfit(rz, ry, 1), rz)
    return stats.pearsonr(ex, ey)


def steady_moving(windows, f_min=1.0):
    return [r for r in windows if r["steady"] and r["f_fly"] > f_min]


def tone_ratio(rec, ch, order, f_fly):
    """Peak PSD at order x f_fly over the median of its sidebands."""
    P, f0 = rec[ch + "_P"], order * f_fly
    if f0 > 430:
        return np.nan
    pk = np.abs(HZ - f0) <= max(0.6, 0.01 * f0)
    sb = (np.abs(HZ - f0) > 1.5) & (np.abs(HZ - f0) < 6 + 0.05 * f0)
    return np.nanmax(P[pk]) / np.nanmedian(P[sb])


def tone_amplitude(rec, ch, order):
    """RMS of the tone at order x f_fly above its sideband floor."""
    P, f0 = rec[ch + "_P"], order * rec["f_fly"]
    pk = np.abs(HZ - f0) <= max(0.75, 0.012 * f0)
    sb = (np.abs(HZ - f0) > 1.5) & (np.abs(HZ - f0) < 6 + 0.05 * f0)
    return float(np.sqrt(max(np.nansum(P[pk] - np.nanmedian(P[sb])), 0) * (HZ[1] - HZ[0])))


def report(windows, seed=0):
    """Return the text report as a list of lines."""
    L = []
    S = steady_moving(windows, 0.5)
    Z = [r for r in windows if r["f_fly"] < 0.05]
    v = np.array([r["vmean"] for r in S])
    I = np.array([r["I_tot"] for r in S])
    L.append(f"steady moving windows {len(S)} from {len({r['file'] for r in S})} runs; "
             f"standstill windows {len(Z)}")
    L.append(f"speed {v.min():.2f}-{v.max():.2f} m/s; rho(speed, I_fc+I_batt) = "
             f"{stats.spearmanr(v, I)[0]:+.2f}")
    L.append(f"predicted orders: tire {ORDER_TIRE:.3f}, spur {ORDER_SPUR:.3f}, "
             f"motor {ORDER_MOTOR:.3f}")

    L.append("\n== Broadband ripple vs speed and load (Spearman; partial = speed | current)")
    for c in VOLT_CH:
        for band in ["_rms", "_rms_lo", "_rms_hi"]:
            y = np.array([r[c + band] for r in S])
            rho, p = stats.spearmanr(v, y)
            pr, _ = _partial_rank(v, y, I)
            z = np.median([r[c + band] for r in Z]) if Z else np.nan
            L.append(f"{c:7s}{band:8s} median {np.median(y) * 1e3:7.2f} mV "
                     f"(standstill {z * 1e3:6.2f})  rho(speed) {rho:+.2f} p={p:.1e}  "
                     f"rho(I) {stats.spearmanr(I, y)[0]:+.2f}  partial {pr:+.2f}")

    L.append("\n== Within-run rho(speed, broadband rms), runs with >=15 steady windows over >=1.5x speed")
    by_run = defaultdict(list)
    for r in S:
        by_run[r["file"]].append(r)
    for c in VOLT_CH:
        rs = [stats.spearmanr([r["vmean"] for r in g], [r[c + "_rms"] for r in g])[0]
              for g in by_run.values()
              if len(g) >= 15 and max(r["vmean"] for r in g) / min(r["vmean"] for r in g) >= 1.5]
        if rs:
            L.append(f"  {c}: {len(rs)} runs, median {np.median(rs):+.2f}, "
                     f"positive in {np.mean(np.array(rs) > 0) * 100:.0f}%")

    S1 = steady_moving(windows, 1.0)
    rng = np.random.default_rng(seed)
    L.append(f"\n== Tone peak/sideband ratio at drivetrain orders ({len(S1)} windows; "
             f"null = speeds shuffled across windows)")
    for c in VOLT_CH + CTX_CH:
        if c + "_P" not in S1[0]:
            continue
        L.append(f"  {c}")
        for name, o in TONES.items():
            real = np.array([tone_ratio(r, c, o, r["f_fly"]) for r in S1])
            perm = rng.permutation([r["f_fly"] for r in S1])
            null = np.array([tone_ratio(r, c, o, pf) for r, pf in zip(S1, perm)])
            L.append(f"    {name:12s} median {np.nanmedian(real):5.2f} (null {np.nanmedian(null):5.2f})"
                     f"  >4x in {np.nanmean(real > 4) * 100:4.1f}% (null {np.nanmean(null > 4) * 100:4.1f}%)")

    v1 = np.array([r["vmean"] for r in S1])
    I1 = np.array([r["I_tot"] for r in S1])
    L.append(f"\n== Tone amplitude by speed bin {SPEED_BINS} (median; mV for V_*, mA for I_*)")
    for c in ["V_bus", "V_fc", "V_batt", "I_batt", "I_fc"]:
        for name in ["motor x2", "motor x1", "tire x1"]:
            a = np.array([tone_amplitude(r, c, TONES[name]) for r in S1])
            med = [np.median(a[(v1 >= lo) & (v1 < hi)]) * 1e3 if ((v1 >= lo) & (v1 < hi)).any() else np.nan
                   for lo, hi in zip(SPEED_BINS[:-1], SPEED_BINS[1:])]
            pr, _ = _partial_rank(v1, a, I1)
            L.append(f"  {c:6s} {name:8s} " + " ".join(f"{m:6.2f}" for m in med) +
                     f" | rho(v) {stats.spearmanr(v1, a)[0]:+.2f} rho(I) {stats.spearmanr(I1, a)[0]:+.2f}"
                     f" partial {pr:+.2f}")
    L.append("  windows per bin: " + str([int(((v1 >= lo) & (v1 < hi)).sum())
                                          for lo, hi in zip(SPEED_BINS[:-1], SPEED_BINS[1:])]))
    fast = Counter(r["file"] for r in S1 if r["vmean"] > 2.0)
    L.append("  windows above 2 m/s by run: " + ", ".join(f"{f}:{k}" for f, k in fast.most_common()))

    L.append("\n== Peak tracking: Theil-Sen slope of in-band argmax frequency vs f_fly")
    for c in ["V_batt", "V_bus", "I_batt"]:
        for lo, hi, vlo, vhi, expect in [(40, 300, 1.6, 3.3, TONES["motor x2"]),
                                         (20, 110, 1.2, 3.3, TONES["motor x1"])]:
            sel = [r for r in S1 if vlo <= r["vmean"] < vhi]
            if len(sel) < 10:
                continue
            m = (HZ >= lo) & (HZ <= hi)
            ff = np.array([r["f_fly"] for r in sel])
            pk = np.array([HZ[m][np.nanargmax(r[c + "_P"][m])] for r in sel])
            sl = stats.theilslopes(pk, ff)
            L.append(f"  {c:6s} {lo}-{hi} Hz, {vlo}-{vhi} m/s: n={len(sel)} slope {sl[0]:.2f} "
                     f"[{sl[2]:.2f}, {sl[3]:.2f}] (expect {expect}); argmax on the order line "
                     f"in {np.mean(np.abs(pk - expect * ff) <= 0.75) * 100:.0f}%")
    return L


# ── Figures ───────────────────────────────────────────────────────────────────

def figures(windows, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    ink, ink2, surf, grid = "#0b0b0b", "#52514e", "#fcfcfb", "#e4e3df"
    series = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
    plt.rcParams.update({
        "figure.facecolor": surf, "axes.facecolor": surf, "axes.edgecolor": grid,
        "axes.labelcolor": ink2, "xtick.color": ink2, "ytick.color": ink2, "text.color": ink,
        "font.size": 10, "axes.grid": True, "grid.color": grid, "grid.linewidth": 0.6,
        "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 1.6})
    seq = LinearSegmentedColormap.from_list("seq", ["#fcfcfb", "#cfe1f6", "#7fb0ea", "#2a78d6", "#0f3f7a"])
    S = steady_moving(windows, 1.0)
    outdir = Path(outdir)

    # Fig 1: speed-binned spectrogram (Campbell diagram)
    fig, axs = plt.subplots(1, 2, figsize=(13, 5.2), sharey=True)
    vb = np.arange(0.4, 3.25, 0.1)
    for ax, c in zip(axs, ["V_batt", "V_bus"]):
        M = []
        for lo in vb:
            g = [r[c + "_P"] for r in S if lo <= r["vmean"] < lo + 0.1]
            M.append(np.nanmedian(g, 0) if len(g) >= 3 else np.full(len(HZ), np.nan))
        M = np.array(M)
        m = HZ <= 260
        with np.errstate(all="ignore"):
            Zdb = 10 * np.log10(M[:, m] / np.nanmedian(M[:, (HZ >= 5) & (HZ <= 250)], axis=1, keepdims=True))
        im = ax.pcolormesh(HZ[m], vb + 0.05, Zdb, cmap=seq, vmin=-3, vmax=15, shading="nearest", rasterized=True)
        for o, label in [(1, None), (ORDER_TIRE, None), (ORDER_MOTOR, "motor 1×"), (2 * ORDER_MOTOR, "motor 2×")]:
            fl = o * (vb + 0.05) / (2 * np.pi * R_FLY)
            ax.plot(fl, vb + 0.05, ls=(0, (3, 3)), lw=1, color=ink2)
            if label:
                ax.text(min(fl[-1], 255), 3.22, label, fontsize=8, color=ink2, ha="center", va="bottom")
        ax.set_xlim(0, 260)
        ax.set_xlabel("frequency [Hz]")
        ax.set_title(f"{c}: median PSD by flywheel speed", loc="left", fontsize=11)
        ax.grid(False)
    axs[0].set_ylabel("flywheel surface speed [m/s]")
    fig.colorbar(im, ax=axs, shrink=0.85, pad=0.01).set_label("dB re. per-speed median (5–250 Hz)")
    fig.savefig(outdir / "fig1_campbell.png", dpi=130, bbox_inches="tight")
    plt.close(fig)

    # Fig 2: order-domain median spectra
    marks = [(1, "fly"), (2, None), (ORDER_TIRE, "tire"), (2 * ORDER_TIRE, "tire×2"), (ORDER_SPUR, "spur"),
             (2 * ORDER_SPUR, "spur×2"), (ORDER_MOTOR, "motor"), (3 * ORDER_SPUR, "spur×3"), (2 * ORDER_MOTOR, "motor×2")]
    chans = ["V_batt", "V_fc", "V_bus", "V_rgn", "I_batt"]
    fig, axs = plt.subplots(len(chans), 1, figsize=(11, 10), sharex=True)
    for ax, c, col in zip(axs, chans, series):
        A = []
        for r in S:
            nh = np.nanmedian(r[c + "_P"][(HZ >= 5) & (HZ <= 400)])
            if r[c + "_Pord"] is not None and nh > 0:
                A.append(r[c + "_Pord"] / nh)
        with np.errstate(all="ignore"):
            med = np.nanmedian(A, 0)
        ax.semilogy(ORD, med, color=col, lw=1.2)
        for o, label in marks:
            ax.axvline(o, color=ink2, lw=0.7, ls=(0, (2, 3)))
            if c == chans[0] and label:
                ax.text(o, np.nanmax(med) * 1.6, label, fontsize=7.5, color=ink2,
                        ha="left" if label == "tire" else "center", va="bottom")
        ax.set_ylabel(c, color=ink)
        ax.set_xlim(0.5, 36)
    axs[0].set_title(f"Order-tracked spectra (x = frequency / flywheel rotation rate), median over "
                     f"{len(S)} steady windows, {len({r['file'] for r in S})} runs", loc="left", fontsize=11, pad=30)
    axs[-1].set_xlabel("order [× flywheel rev/s]")
    fig.savefig(outdir / "fig2_orders.png", dpi=130, bbox_inches="tight")
    plt.close(fig)

    # Fig 3: motor 2x tone amplitude vs speed; broadband ripple vs load
    v = np.array([r["vmean"] for r in S])
    I = np.array([r["I_tot"] for r in S])
    fig, axs = plt.subplots(1, 3, figsize=(14, 4.4))
    for ax, c, unit in [(axs[0], "V_batt", "mV"), (axs[1], "I_batt", "mA")]:
        a = np.array([tone_amplitude(r, c, TONES["motor x2"]) for r in S]) * 1e3
        sc = ax.scatter(v, np.maximum(a, 1e-2), c=I, s=9, cmap=seq, vmin=0,
                        vmax=np.percentile(I, 98), edgecolors="none")
        ax.set_yscale("log")
        ax.set_ylim(1e-2, None)
        ax.set_xlabel("flywheel speed [m/s]")
        ax.set_ylabel(f"{c} tone at 2× motor rev rate [{unit} rms]")
        ax.set_title(f"{c}: motor 2× tone", loc="left", fontsize=11)
    fig.colorbar(sc, ax=axs[:2], pad=0.01, shrink=0.9).set_label("I_fc + I_batt [A]")
    ax = axs[2]
    for c, col in zip(["V_fc", "V_batt", "V_bus", "V_rgn"], series):
        ax.scatter(I, np.array([r[c + "_rms"] for r in S]) * 1e3, s=5, color=col, alpha=0.45,
                   edgecolors="none", label=c)
    ax.set_yscale("log")
    ax.set_xlabel("I_fc + I_batt [A]")
    ax.set_ylabel("broadband ripple [mV rms]")
    ax.set_title("Broadband ripple tracks load current", loc="left", fontsize=11)
    ax.legend(frameon=False, markerscale=3, fontsize=8)
    fig.savefig(outdir / "fig3_amplitude.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--logs", default=str(REPO_ROOT / "logs"), help="folder of .BLG files")
    ap.add_argument("--out", default=None, help="output folder (default <logs>/rail_spectral)")
    ap.add_argument("--cache", default=None, help="pickle the windows here and reuse them (~1 GB)")
    ap.add_argument("--rebuild", action="store_true", help="recompute even if --cache exists")
    ap.add_argument("--no-figures", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out or Path(a.logs) / "rail_spectral")
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(a.cache) if a.cache else None
    if cache and cache.exists() and not a.rebuild:
        windows, runs = pickle.loads(cache.read_bytes())
        print(f"loaded {len(windows)} windows from {cache} (--rebuild to recompute)")
    else:
        windows, runs = collect(a.logs)
        print(f"{len(windows)} windows from {len(runs)} runs")
        if cache:
            cache.write_bytes(pickle.dumps((windows, runs)))
            print(f"cached -> {cache}")
    if not steady_moving(windows):
        print("no steady moving windows found; nothing to analyse")
        return 1
    # Empty sidebands / all-NaN order bins at the edges of the grids are
    # expected and handled (nan-aware reductions); don't spam the report.
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        lines = report(windows)
        (out / "report.txt").write_text("\n".join(lines) + "\n")
        print("\n".join(lines))
        if not a.no_figures:
            figures(windows, out)
            print(f"figures -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
