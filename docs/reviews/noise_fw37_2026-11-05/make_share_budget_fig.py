"""Share-ratio noise budget, fw v35 vs fw v37 (noise round 2026-11-05, README section 3.1).

Regenerates figs/brief_share_budget.png. Usage:
    python make_share_budget_fig.py <cache_dir> <out_dir>
where <cache_dir> holds the .npz files written by tools/rosbag_analysis/scout_bags.py --npz.

Method (the share-spectrum agent's a6.py, with the brief's conventions):
- duplicate telemetry rows removed, fs = 47.62 Hz (bag-conventions trap 20);
- moving (v > 0.3 m/s), both sources on the bus (0x27), I_tot > 0.3 A;
- +/-0.5 s around each H-20 purge and +/-0.2 s around each share-command step excluded;
- n = s - clip(cmd, 0.15, 0.85), s = I_fc / I_tot;
- stacked areas = multiple coherence of n with the 1x angle (cos, sin), then + I_tot, then + V_fc;
- governor floor reference = clip(cmd, 0.125 / EMA(I_tot, 19.5 ms), 1 - lo), the setpoint clip in powerBalance().
"""
import sys
import numpy as np
from scipy import signal
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

C, OUT = sys.argv[1], sys.argv[2]
FS = 47.62
NP = 64
BAGS = {"fw v35 (2026-10-30)": "rosbag_sdp_2026-10-30_01-49-38",
        "fw v37 rev 2 (2026-11-05)": "rosbag_sdp_2026-11-05_20-09-52"}
BANDS = [(2, 6), (6, 12), (12, 23.8)]
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#e4e3df", "grid.linewidth": 0.6,
                     "axes.edgecolor": "#8a897f", "axes.labelcolor": "#3b3a36",
                     "xtick.color": "#5c5b55", "ytick.color": "#5c5b55"})


def load(bag):
    z = np.load(f"{C}/{bag}.npz")
    t, vs, ect, ec = z["vs_t"], z["vs"], z["ec_t"], z["ec"]
    keep = np.r_[True, np.any(np.diff(vs[:, [0, 2, 5, 6, 4]], axis=0) != 0, axis=1)]
    t, vs = t[keep], vs[keep]
    idx = np.searchsorted(ect, t, side="right") - 1
    cmd = np.where(idx >= 0, ec[np.clip(idx, 0, None), 1], np.nan)
    D = dict(t=t, v=vs[:, 0], Ib=vs[:, 2], Vfc=vs[:, 4], Ifc=vs[:, 5], sw=vs[:, 13].astype(int), cmd=cmd)
    D["It"] = D["Ifc"] + D["Ib"]
    with np.errstate(all="ignore"):
        D["s"] = D["Ifc"] / D["It"]
    a = 1 - np.exp(-(1 / FS) / 0.0195)
    itf = np.empty_like(D["It"]); itf[0] = max(D["It"][0], 0)
    for i in range(1, len(itf)):
        itf[i] = itf[i - 1] + a * (max(D["It"][i], 0) - itf[i - 1])
    with np.errstate(all="ignore"):
        lo = 0.125 / itf
    ref = np.clip(D["cmd"], np.maximum(lo, 0.15), np.minimum(1 - lo, 0.85))
    D["ref"] = np.where(lo < 1 - lo, ref, np.nan)
    D["th"] = np.cumsum(np.r_[0, np.diff(t)] * D["v"]) / 0.0762
    from scipy.ndimage import median_filter
    dip = D["Vfc"] < median_filter(D["Vfc"], size=151) - 1.0
    near = np.zeros(len(t), bool)
    for e in np.flatnonzero(np.diff(dip.astype(int)) == 1) + 1:
        near |= np.abs(t - t[e]) < 0.5
    st = np.zeros(len(t), bool)
    for e in np.flatnonzero(np.abs(np.diff(np.nan_to_num(cmd))) > 0.02) + 1:
        st |= np.abs(t - t[e]) < 0.2
    D["mask"] = (D["v"] > 0.3) & (D["It"] > 0.3) & (D["sw"] == 0x27) & ~near & ~st & np.isfinite(cmd)
    return D


def runs(m, minlen):
    e = np.flatnonzero(np.diff(np.r_[0, m.astype(int), 0]))
    return [(a, b) for a, b in zip(e[::2], e[1::2]) if b - a >= minlen]


def welch_runs(xs, R):
    acc, n = {}, 0
    for a, b in R:
        nseg = 1 + ((b - a) - NP) // (NP // 2)
        seg = {k: signal.detrend(v[a:b]) for k, v in xs.items()}
        for i in xs:
            for j in xs:
                f, P = signal.csd(seg[i], seg[j], fs=FS, nperseg=NP, detrend="linear")
                acc[(i, j)] = acc.get((i, j), 0) + P * nseg
        n += nseg
    return f, {k: v / n for k, v in acc.items()}, n


def mcoh(P, y, X, f):
    Pxx = np.array([[P[(a, b)] for b in X] for a in X]).transpose(2, 0, 1)
    Pxy = np.array([P[(a, y)] for a in X]).T
    Pyx = np.array([P[(y, a)] for a in X]).T
    g = np.array([np.real(Pyx[i] @ np.linalg.solve(Pxx[i], Pxy[i])) / np.real(P[(y, y)][i]) for i in range(len(f))])
    return np.clip(g, 0, 1)


def band(f, P, lo, hi):
    m = (f >= lo) & (f < hi)
    return float(np.sqrt(np.sum(np.real(P[m])) * (f[1] - f[0])))


fig, axs = plt.subplots(1, 2, figsize=(10.5, 4.0), sharey=True)
for ax, (lab, bag) in zip(axs, BAGS.items()):
    D = load(bag)
    R = runs(D["mask"], NP)
    cmdc = np.clip(D["cmd"], 0.15, 0.85)
    xs = dict(n=D["s"] - cmdc, gov=D["ref"] - cmdc, e=D["s"] - D["ref"], It=D["It"],
              cos=np.cos(D["th"]), sin=np.sin(D["th"]), Vfc=D["Vfc"])
    f, P, ns = welch_runs(xs, R)
    Pn = np.real(P[("n", "n")])
    g_rot = mcoh(P, "n", ["cos", "sin"], f)
    g_ri = mcoh(P, "n", ["cos", "sin", "It"], f)
    g_riv = mcoh(P, "n", ["cos", "sin", "It", "Vfc"], f)
    s0 = np.concatenate([D["s"][a:b] for a, b in R]); It0 = np.concatenate([D["It"][a:b] for a, b in R])
    Pq = np.full(len(f), np.mean(((1 - s0) ** 2 + s0 ** 2) * (0.00806 ** 2 / 12) / It0 ** 2) / (FS / 2))
    ax.fill_between(f, 1e-9, g_rot * Pn, color="#2a78d6", alpha=0.75, lw=0, label="1x-locked (rotation angle)")
    ax.fill_between(f, g_rot * Pn, g_ri * Pn, color="#eb6834", alpha=0.75, lw=0, label="+ coherent with I_tot")
    ax.fill_between(f, g_ri * Pn, g_riv * Pn, color="#1baf7a", alpha=0.75, lw=0, label="+ coherent with V_fc")
    ax.semilogy(f, Pn, color="#1f1e1c", lw=1.8, label="uncommanded share n = s - cmd")
    ax.semilogy(f, np.real(P[("gov", "gov")]), color="#d55181", lw=1.4, ls="--", label="governor floor reference")
    ax.semilogy(f, np.real(P[("e", "e")]), color="#7a5cc4", lw=1.4, ls=":", label="tracking error e = s - reference")
    ax.semilogy(f, Pq, color="#8a897f", lw=1.2, ls="-.", label="ADC quantization floor")
    ticks = sum(b - a for a, b in R)
    ax.set_title(f"{lab}: {len(R)} runs, {ticks} samples", loc="left", fontsize=10, color="#1f1e1c")
    ax.set_xlabel("Frequency [Hz]")
    ax.set_ylim(1e-7, 1e-3); ax.set_xlim(0, FS / 2)
    print(lab, "runs", len(R), "samples", ticks, "|",
          " ".join(f"{a}-{b} Hz: n {band(f, Pn, a, b):.4f} 1x {band(f, g_rot * Pn, a, b):.4f} gov {band(f, P[('gov', 'gov')], a, b):.4f}"
                   for a, b in BANDS))
axs[0].set_ylabel("PSD [1/Hz]")
axs[0].legend(frameon=False, fontsize=7.5, loc="upper right")
fig.tight_layout()
fig.savefig(f"{OUT}/brief_share_budget.png", dpi=150)
