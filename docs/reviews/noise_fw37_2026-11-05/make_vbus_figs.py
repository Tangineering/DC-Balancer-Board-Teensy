"""V_bus at the loop rate (ML0226, fw v37 bench) for the noise brief (README section 9).

Regenerates figs/brief_vbus_1k.png and figs/brief_vbus_spectrogram.png. Usage:
    python make_vbus_figs.py <ML0226.csv> <out_dir>

Left panel: V_bus PSD at standstill and at the closed-loop speed holds, on the measured sample rate
(the loop runs at ~884 Hz, not 1 kHz). Markers show where the motor's 6x electrical line
(397 Hz per m/s) lands after folding at the loop's Nyquist frequency.
Right panel: V_bus rms in 0.5-23.8 Hz for the true signal, a 21 ms snapshot (what the Pi bag sees)
and a 21 ms boxcar mean (what a telemetry mean would give).
"""
import sys
import numpy as np
from scipy.signal import welch
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CSV, OUT = sys.argv[1], sys.argv[2]
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#e4e3df", "grid.linewidth": 0.6,
                     "axes.edgecolor": "#8a897f", "axes.labelcolor": "#3b3a36",
                     "xtick.color": "#5c5b55", "ytick.color": "#5c5b55"})

cols = ["t_us", "v_sp", "v_act", "I_fc", "I_batt", "V_bus", "I_cmd"]
hdr = open(CSV).readline().strip().split(",")
d = np.genfromtxt(CSV, delimiter=",", skip_header=1, usecols=[hdr.index(c) for c in cols])
t = d[:, 0] * 1e-6; vsp = d[:, 1]; v = d[:, 2]; vb = d[:, 5]; icmd = d[:, 6]
fs = 1.0 / np.median(np.diff(t))


def segments():
    out = {}
    still = (np.abs(v) < 0.02) & (np.abs(icmd) < 0.05)
    out["standstill"] = still
    for sp in (1.0, 1.5, 2.0):
        m = (np.abs(vsp - sp) < 1e-3) & (np.abs(v - sp) < 0.1)
        out[f"{sp:.1f} m/s hold"] = m
    return out


def runs(m, minlen):
    e = np.flatnonzero(np.diff(np.r_[0, m.astype(int), 0]))
    return [(a, b) for a, b in zip(e[::2], e[1::2]) if b - a >= minlen]


def psd(m, nper=1024):
    acc, n = 0, 0
    for a, b in runs(m, nper):
        # The ticks are bimodal (1128 / 1332 us), so the effective rate is the segment's MEAN rate.
        fs_seg = (b - a - 1) / (t[b - 1] - t[a])
        f, p = welch(vb[a:b] - vb[a:b].mean(), fs=fs_seg, nperseg=nper, detrend="linear")
        acc = acc + p * (b - a); n += b - a
    return f, acc / n, n, fs_seg


def fold_test(m):
    """True in-band, 21 ms snapshot and 21 ms boxcar V_bus rms over 0.5-23.8 Hz (mV)."""
    vals = {"true": [], "snapshot": [], "boxcar": []}
    w = []
    for a, b in runs(m, 4096):
        tt, x = t[a:b], vb[a:b]
        f, p = welch(x - x.mean(), fs=fs, nperseg=4096, detrend="linear")
        mm = (f >= 0.5) & (f < 23.8)
        vals["true"].append(np.trapezoid(p[mm], f[mm]))
        grid = np.arange(tt[0], tt[-1], 0.021)
        k = np.searchsorted(tt, grid)
        k = k[k < len(tt)]
        snap = x[k]
        box = np.array([x[k[i]:k[i + 1]].mean() for i in range(len(k) - 1)])
        for name, y in (("snapshot", snap), ("boxcar", box)):
            f2, p2 = welch(y - y.mean(), fs=1 / 0.021, nperseg=min(256, len(y)), detrend="linear")
            m2 = (f2 >= 0.5) & (f2 < 23.8)
            vals[name].append(np.trapezoid(p2[m2], f2[m2]))
        w.append(b - a)
    return {k: 1e3 * np.sqrt(np.average(v_, weights=w)) for k, v_ in vals.items()}


segs = segments()
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 3.9), gridspec_kw={"width_ratios": [1.45, 1]})
colors = {"standstill": "#8a897f", "1.0 m/s hold": "#2a78d6", "1.5 m/s hold": "#1baf7a", "2.0 m/s hold": "#eb6834"}
nyq = fs / 2
for name, m in segs.items():
    f, p, n, fs_seg = psd(m)
    ax1.semilogy(f, np.sqrt(p) * 1e3, color=colors[name], lw=1.5 if name != "standstill" else 1.2, label=name)
    if name != "standstill":
        sp = float(name.split()[0])
        ftrue = 397.0 * sp
        falias = abs(((ftrue + fs_seg / 2) % fs_seg) - fs_seg / 2)
        i = np.argmin(np.abs(f - falias))
        ax1.annotate(f"6x line, {sp:.1f} m/s\n(true {ftrue:.0f} Hz)", xy=(f[i], np.sqrt(p[i]) * 1e3),
                     xytext=(f[i], 5.5), ha="center", va="bottom", fontsize=7, color=colors[name],
                     arrowprops=dict(arrowstyle="-", color=colors[name], lw=0.8, ls=":"))
    print(name, "samples", n, "fs_seg", round(fs_seg, 1))
ax1.axvspan(0, 23.8, color="#e4e3df", alpha=0.7, lw=0, zorder=0)
ax1.text(12, 0.06, "bag\nband", ha="center", fontsize=7.5, color="#5c5b55")
ax1.set_xlim(0, nyq); ax1.set_ylim(0.05, 14)
ax1.set_xlabel("Frequency [Hz] (loop rate about 875 Hz)")
ax1.set_ylabel("V_bus ASD [mV/√Hz]")
ax1.set_title("V_bus at the loop rate, ML0226", loc="left", fontsize=10, color="#1f1e1c")
ax1.legend(frameon=False, fontsize=7.5, loc="lower right", ncol=4)

names = list(segs)
res = [fold_test(segs[n]) for n in names]
x = np.arange(len(names)); w = 0.27
for j, (key, col, lab) in enumerate([("true", "#2a78d6", "true content, 0.5-23.8 Hz"),
                                     ("snapshot", "#eb6834", "21 ms snapshot (bag)"),
                                     ("boxcar", "#1baf7a", "21 ms mean (telemetry fix)")]):
    vals = [r[key] for r in res]
    ax2.bar(x + (j - 1) * w, vals, w, color=col, edgecolor="white", linewidth=1.5, label=lab)
    for xx, vv in zip(x + (j - 1) * w, vals):
        ax2.text(xx, vv + 0.08, f"{vv:.1f}", ha="center", fontsize=7, color="#3b3a36")
for n, r in zip(names, res):
    print(n, {k: round(v_, 2) for k, v_ in r.items()})
ax2.set_xticks(x); ax2.set_xticklabels([n.replace(" hold", "") for n in names])
ax2.set_ylabel("V_bus rms, 0.5-23.8 Hz [mV]"); ax2.grid(axis="x", visible=False)
ax2.set_title("What the bag sees", loc="left", fontsize=10, color="#1f1e1c")
ax2.legend(frameon=False, fontsize=7.5, loc="upper left")
fig.tight_layout()
fig.savefig(f"{OUT}/brief_vbus_1k.png", dpi=150)
print("fs", fs)

# ---- Spectrogram of the whole log (figs/brief_vbus_spectrogram.png) ----
# Regenerated from the switching agent's figure with true units: the sample rate is the log's
# MEAN rate (the ticks are bimodal), the time axis is the logged t_us, and the overlay is the
# motor 6x electrical line, 397 Hz per m/s x v_act, folded at that rate's Nyquist frequency.
from scipy.signal import spectrogram
fs_mean = (len(t) - 1) / (t[-1] - t[0])
f_s, i_s, Sxx = spectrogram(vb - vb.mean(), fs=fs_mean, nperseg=512, noverlap=384, detrend="linear",
                            scaling="density", mode="psd")
centres = np.clip((i_s * fs_mean).astype(int), 0, len(t) - 1)
tt = t[centres] - t[0]
half = 256
vfr = np.array([v[max(0, c - half):c + half].mean() for c in centres])
fig, ax = plt.subplots(figsize=(10.5, 3.7))
ax.pcolormesh(tt, f_s, 10 * np.log10(Sxx * 1e6 + 1e-12), shading="auto", vmin=-40, vmax=0,
              cmap="viridis", rasterized=True)
F = 397.0 * vfr
Ff = np.abs(((F + fs_mean / 2) % fs_mean) - fs_mean / 2)
Ff[vfr < 0.3] = np.nan
ax.plot(tt, Ff, color="#ff6b5b", lw=1.0, ls="--", label="motor 6x electrical, 397 Hz per m/s, folded")
ax.set_xlim(tt[0], tt[-1]); ax.set_ylim(0, fs_mean / 2)
ax.set_xlabel("Log time [s]")
ax.set_ylabel(f"Frequency [Hz] (sample rate {fs_mean:.0f} Hz)")
ax.grid(False)
ax.legend(frameon=False, loc="upper left", labelcolor="white", fontsize=8)
ax.set_title("V_bus spectrogram, ML0226 (dB re 1 mV²/Hz, -40 to 0)", loc="left", fontsize=10,
             color="#1f1e1c")
fig.tight_layout()
fig.savefig(f"{OUT}/brief_vbus_spectrogram.png", dpi=150)
print("fs_mean", fs_mean)
