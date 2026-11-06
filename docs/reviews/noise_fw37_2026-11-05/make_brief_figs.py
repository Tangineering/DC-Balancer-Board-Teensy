import numpy as np, sys, json
from scipy.signal import welch
from scipy.interpolate import interp1d
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

C = sys.argv[1]; OUT = sys.argv[2]
BAGS = [("fw v35 (2026-10-30)", "rosbag_sdp_2026-10-30_01-49-38", "#2a78d6"),
        ("fw v37 rev 2 (2026-11-05)", "rosbag_sdp_2026-11-05_20-09-52", "#eb6834")]
FS = 47.62; FROT = 2.089
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#e4e3df", "grid.linewidth": 0.6,
                     "axes.edgecolor": "#8a897f", "axes.labelcolor": "#3b3a36",
                     "xtick.color": "#5c5b55", "ytick.color": "#5c5b55"})


def load(b):
    z = np.load(f"{C}/{b}.npz"); t = z["vs_t"]; d = z["vs"]; ect = z["ec_t"]; ec = z["ec"]
    keep = np.r_[True, np.any(np.diff(d[:, [0, 2, 5, 6, 4]], axis=0) != 0, axis=1)]
    t = t[keep]; d = d[keep]
    cmd = interp1d(ect, ec[:, 1], kind="previous", bounds_error=False, fill_value=np.nan)(t)
    D = dict(t=t, v=d[:, 0], Ifc=d[:, 5], Ibt=d[:, 2], Vbus=d[:, 6], Vfc=d[:, 4],
             sw=d[:, 13].astype(int), cmd=cmd)
    D["Itot"] = D["Ifc"] + D["Ibt"]
    D["s"] = np.where(D["Itot"] > 0.3, D["Ifc"] / np.maximum(D["Itot"], 1e-6), np.nan)
    pur = (D["sw"] == 0x27) & (D["Ifc"] < 0.03) & (D["v"] > 0.3)
    med = np.array([np.median(D["Vfc"][max(0, i - 50):i + 50]) for i in range(len(t))])
    pur |= D["Vfc"] < med - 2.0
    D["purge"] = np.zeros(len(t), bool)
    for i in np.flatnonzero(pur):
        D["purge"] |= np.abs(t - t[i]) < 0.5
    stp = np.zeros(len(t), bool)
    dc = np.abs(np.diff(np.nan_to_num(cmd), prepend=np.nan_to_num(cmd[0]))) > 0.02
    for i in np.flatnonzero(dc):
        stp |= (t >= t[i] - 0.2) & (t <= t[i] + 1.0)
    D["step"] = stp
    D["base"] = (D["sw"] == 0x27) & (D["v"] > 0.3) & (D["Itot"] > 0.3)
    return D


def runs(mask, minlen):
    idx = np.flatnonzero(mask)
    return [r for r in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1) if len(r) >= minlen]


def psd(D, key, mask, nper=128):
    acc = 0; n = 0
    for r in runs(mask, nper):
        x = D[key][r]
        f, p = welch(x - x.mean(), fs=FS, nperseg=nper, detrend="linear")
        acc = acc + p * len(r); n += len(r)
    return f, acc / n, n


def bandrms(f, p, a, b):
    m = (f >= a) & (f < b)
    return float(np.sqrt(np.trapezoid(p[m], f[m])))


def lockin(D, key, mask):
    vs = np.convolve(D["v"], np.ones(48) / 48, "same")
    ph = 2 * np.pi * np.cumsum(FROT * vs * np.r_[0, np.diff(D["t"])])
    A = []; W = []
    for r in runs(mask, 96):
        k = np.arange(len(r)); x = D[key][r]
        x = x - np.polyval(np.polyfit(k, x, 1), k)
        c = 2 * np.mean(x * np.cos(ph[r])); s = 2 * np.mean(x * np.sin(ph[r]))
        A.append(np.hypot(c, s)); W.append(len(r))
    return float(np.average(A, weights=W)), int(sum(W))


data = [(lab, load(b), col) for lab, b, col in BAGS]
res = {}

# Fig 1: PSDs
fig, axs = plt.subplots(2, 2, figsize=(9.5, 6.2), sharex=True)
chans = [("Itot", "I_tot = I_fc + I_batt", "A$^2$/Hz"), ("Ifc", "I_fc (fuel-cell boost)", "A$^2$/Hz"),
         ("Vbus", "V_bus", "V$^2$/Hz"), ("s", "Share ratio I_fc / I_tot", "1/Hz")]
for ax, (k, title, un) in zip(axs.flat, chans):
    for lab, D, col in data:
        m = D["base"] & ~D["purge"] & ~D["step"] & (D["v"] > 1.8)
        f, p, n = psd(D, k, m)
        ax.semilogy(f, p, color=col, lw=2, label=lab)
        res.setdefault("psd_" + k, {})[lab] = {"2-6": bandrms(f, p, 2, 6), "6-12": bandrms(f, p, 6, 12),
                                               "12-23.8": bandrms(f, p, 12, 23.8), "n": n}
    ax.axvspan(1.8 * FROT, 2.8 * FROT, color="#e4e3df", alpha=0.7, lw=0, zorder=0)
    ax.set_title(title, loc="left", fontsize=10, color="#1f1e1c"); ax.set_ylabel(un)
for ax in axs[1]:
    ax.set_xlabel("Frequency [Hz]")
yl = axs[0, 0].get_ylim()
axs[0, 0].legend(frameon=False, loc="upper right")
fig.suptitle("Cruise spectra, matched clean windows: both sources on the bus, v > 1.8 m/s, purges and command "
             "steps excluded, de-duplicated (fs 47.62 Hz).\nGrey band = 1x flywheel frequency at 1.8-2.8 m/s.", fontsize=9, color="#3b3a36", x=0.01, ha="left")
fig.tight_layout(rect=(0, 0, 1, 0.93)); fig.savefig(f"{OUT}/brief_psd_before_after.png", dpi=150); plt.close(fig)

# Fig 2: 1x ratio
keys = [("Itot", "I_tot"), ("Ibt", "I_batt"), ("Ifc", "I_fc"), ("Vbus", "V_bus"), ("s", "share"), ("v", "v_actual")]
units = {"Itot": ("mA", 1e3), "Ibt": ("mA", 1e3), "Ifc": ("mA", 1e3), "Vbus": ("mV", 1e3), "s": ("", 1), "v": ("mm/s", 1e3)}
amp = {}
for k, lbl in keys:
    amp[lbl] = [lockin(D, k, D["base"] & ~D["purge"] & ~D["step"] & (D["v"] > 1.8) & (D["v"] < 2.9)) for _, D, _ in data]
fig, ax = plt.subplots(figsize=(7.4, 3.6))
y = np.arange(len(keys))[::-1]
r = [amp[l][1][0] / amp[l][0][0] for _, l in keys]
ax.axvline(1, color="#8a897f", lw=1)
ax.axvline(0.29, color="#3b3a36", lw=1, ls="--")
ax.text(0.30, y[0] + 0.45, "design |C*S| ratio 0.29 (4.6 Hz)", fontsize=8, color="#3b3a36", va="bottom")
ax.hlines(y, 0, r, color="#eb6834", lw=2)
ax.plot(r, y, "o", ms=8, color="#eb6834", mec="white", mew=2)
for yy, rr, (k, l) in zip(y, r, keys):
    u, sc = units[k]
    b, a = amp[l][0][0] * sc, amp[l][1][0] * sc
    fmt = "{:.3f}" if k == "s" else "{:.1f}"
    ax.text(rr + 0.03, yy, f"{rr:.2f}x   ({fmt.format(b)} -> {fmt.format(a)}{(" " + u) if u else ""})", va="center", fontsize=8, color="#3b3a36")
ax.set_yticks(y); ax.set_yticklabels([l for _, l in keys]); ax.set_xlim(0, 1.5); ax.set_ylim(-0.6, len(keys) - 0.1)
ax.grid(axis="y", visible=False)
ax.set_xlabel("1x amplitude, fw v37 / fw v35 (peak amplitude in brackets)")
ax.set_title("Once-per-rev (1x) line at cruise, 1.8-2.9 m/s, tracked-phase lock-in", loc="left", fontsize=10)
fig.tight_layout(); fig.savefig(f"{OUT}/brief_1x_ratio.png", dpi=150); plt.close(fig)
res["amp1x"] = amp

# Fig 3: share 2-6 Hz under masks
masks = [("Moving, both sources,\nnothing excluded", lambda D: D["base"]),
         ("Purges\nexcluded", lambda D: D["base"] & ~D["purge"]),
         ("Purges and\ncommand steps\nexcluded", lambda D: D["base"] & ~D["purge"] & ~D["step"])]
vals = []
for _, fn in masks:
    row = []
    for _, D, _ in data:
        f, p, n = psd(D, "s", fn(D)); row.append(bandrms(f, p, 2, 6))
    vals.append(row)
fig, ax = plt.subplots(figsize=(6.8, 3.6)); x = np.arange(len(masks)); w = 0.36
for j, (lab, _, col) in enumerate(data):
    vv = [v[j] for v in vals]
    ax.bar(x + (j - 0.5) * w, vv, w, color=col, label=lab, edgecolor="white", linewidth=2)
    for xx, v in zip(x + (j - 0.5) * w, vv):
        ax.text(xx, v + 0.0006, f"{v:.3f}", ha="center", fontsize=8, color="#3b3a36")
ax.set_xticks(x); ax.set_xticklabels([m for m, _ in masks]); ax.set_ylabel("share rms, 2-6 Hz")
ax.grid(axis="x", visible=False); ax.legend(frameon=False, loc="upper right")
ax.set_title("Share ratio, 2-6 Hz: the drop appears once purges and EMS steps are removed", loc="left", fontsize=10)
fig.tight_layout(); fig.savefig(f"{OUT}/brief_share_masks.png", dpi=150); plt.close(fig)
res["share_masks"] = {m.replace("\n", " "): v for (m, _), v in zip(masks, vals)}

# Fig 4: trace
t0, t1 = float(sys.argv[3]), float(sys.argv[4])
fig, axs = plt.subplots(2, 1, figsize=(9, 4.6), sharex=True)
for lab, D, col in data:
    m = (D["t"] >= t0) & (D["t"] <= t1)
    axs[0].plot(D["t"][m], D["Itot"][m], color=col, lw=1.6, label=lab)
    axs[1].plot(D["t"][m], D["s"][m], color=col, lw=1.6)
    res.setdefault("trace", {})[lab] = {"v": float(np.median(D["v"][m])), "cmd": float(np.nanmedian(D["cmd"][m])),
                                        "sw": sorted(set(D["sw"][m].tolist())), "purge": bool(D["purge"][m].any()),
                                        "step": bool(D["step"][m].any())}
axs[0].set_ylabel("I_tot [A]"); axs[1].set_ylabel("share I_fc / I_tot")
axs[1].set_xlabel("Bag time [s] (both runs follow the same cycle in bag time)")
axs[0].legend(frameon=False, ncol=2, loc="upper right")
axs[0].set_title(f"Cruise, {t0:g}-{t1:g} s: total current and share before and after", loc="left", fontsize=10)
fig.tight_layout(); fig.savefig(f"{OUT}/brief_trace.png", dpi=150); plt.close(fig)
print(json.dumps(res, indent=1, default=float))
