"""Which mechanism makes the motor 6x electrical power ripple? Scaling test on ML0226.

Usage:
    python analyze_6x_scaling.py <ML0226.csv> <out_dir>

Hypotheses and the scaling of the bus-current ripple amplitude A6 that each predicts:
- back-EMF 5th/7th harmonics x sinusoidal FOC current: ripple power is a fixed fraction of the
  mechanical power, so A6 ~ v^1 * I^1 and k6 = A6 / (P_mech / V_bus) is constant;
- VESC dead-time distortion: ripple power ~ phase current, so A6 ~ v^0 * I^1;
- cogging (speed ripple through the flywheel inertia): A6 ~ v^-1 * I^1.

Method: the log is sampled at ~875 Hz with a +205 us long tick every 18-19 samples, and the line
is at 397 Hz per m/s (120-800 Hz), so it is aliased AND phase-jittered in the sample index. The
fit therefore uses the true timestamps t_us. The carrier phase is tracked from the smoothed speed,
phi = 2 pi c integral(v_s dt), and the fit includes the 1x rotation sidebands (k = -2..2), because
the real 1x speed modulation frequency-modulates the 6x line. c is scanned around 397 per window.
"""
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CSV, OUT = sys.argv[1], sys.argv[2]
K_F = 0.7538          # N/A, ML0226 coast-down fit (docs/fw37_planning_2026-11-04.md 10.3)
FROT = 2.089          # flywheel rev/s per m/s
K_SIDE = int(sys.argv[3]) if len(sys.argv) > 3 else 12   # rotation sidebands each side of the carrier
KS = tuple(range(-K_SIDE, K_SIDE + 1))
hdr = open(CSV).readline().strip().split(",")
cols = ["t_us", "v_act", "I_fc", "I_batt", "V_bus", "I_cmd"]
d = np.genfromtxt(CSV, delimiter=",", skip_header=1, usecols=[hdr.index(c) for c in cols])
t = (d[:, 0] - d[0, 0]) * 1e-6
v, itot, vbus, icmd = d[:, 1], d[:, 2] + d[:, 3], d[:, 4], d[:, 5]
fs = (len(t) - 1) / t[-1]

# smoothed speed (0.5 s boxcar) removes the 1x speed-sensor ripple from the phase track
n_s = int(0.5 * fs)
v_s = np.convolve(v, np.ones(n_s) / n_s, mode="same")
dts = np.r_[0, np.diff(t)]
s_int = np.cumsum(v_s * dts)                  # integral of v_s dt  [m]
th_rot = 2 * np.pi * FROT * s_int             # flywheel angle


def fit(x, phi, th, ks=(0,)):
    """LS amplitude (peak) of sum_k a_k cos(phi + k th) + b_k sin(...) with mean + slope."""
    cols_ = [np.ones_like(phi), np.linspace(-1, 1, len(phi))]
    for k in ks:
        cols_ += [np.cos(phi + k * th), np.sin(phi + k * th)]
    M = np.column_stack(cols_)
    coef, *_ = np.linalg.lstsq(M, x, rcond=None)
    ab = coef[2:].reshape(-1, 2)
    return np.sqrt((ab ** 2).sum(axis=1))


def fold(f):
    return np.abs(((f + fs / 2) % fs) - fs / 2)


W, H = int(2.0 * fs), int(1.0 * fs)
rows = []
for a in range(0, len(t) - W, H):
    b = a + W
    vm = v_s[a:b].mean()
    if vm < 0.3 or abs(v_s[b - 1] - v_s[a]) > 0.03 or np.max(np.diff(t[a:b])) > 0.003:
        continue
    th = th_rot[a:b] - th_rot[a]
    best = None
    for c in np.arange(385.0, 410.0, 0.25):
        phi = 2 * np.pi * c * (s_int[a:b] - s_int[a])
        amp = fit(itot[a:b], phi, th)[0]
        if best is None or amp > best[1]:
            best = (c, amp)
    c = best[0]
    phi = 2 * np.pi * c * (s_int[a:b] - s_int[a])
    # contamination: drop any sideband tone whose folded frequency lies within 0.75 Hz of the fold
    # of another speed-locked order; flag the window if the carrier itself is contaminated
    f6 = c * vm
    fr = FROT * vm
    others = [k * c / 6 * vm for k in range(1, 13) if k != 6] + [m * 41.3 * vm for m in (1, 2, 3)]
    ks = [k for k in KS if all(abs(fold(f6 + k * fr) - fold(fo)) > 0.75 for fo in others)]
    contam = 0 not in ks
    if contam:
        ks = list(KS)
    # noise-debiased amplitude: summed tone power minus the per-tone power of off-line fits
    tones = fit(itot[a:b], phi, th, ks=ks)
    p_bg = np.mean([np.mean(fit(itot[a:b], 2 * np.pi * cc * (s_int[a:b] - s_int[a]), th, ks=ks) ** 2)
                    for cc in (c * 0.90, c * 0.93, c * 1.07, c * 1.10)])
    p_line = float((tones ** 2).sum())
    A6 = float(np.sqrt(max(p_line - len(ks) * p_bg, 1e-12)))
    bg = float(np.sqrt(len(ks) * p_bg))
    vt = fit(vbus[a:b], phi, th, ks=ks)
    vb6 = float(np.sqrt((vt ** 2).sum()))
    rows.append(dict(t=t[a], v=vm, I=icmd[a:b].mean(), Itot=itot[a:b].mean(), Vbus=vbus[a:b].mean(),
                     c=c, f6=f6, A6=A6, Vb6=vb6, bg=bg, contam=contam))

R = {k: np.array([r[k] for r in rows]) for k in rows[0]}
snr = R["A6"] / R["bg"]
SNR_MIN = float(sys.argv[4]) if len(sys.argv) > 4 else 1.5
ok = (snr > SNR_MIN) & ~R["contam"] & (R["I"] > 1.0)
print(f"fs {fs:.1f} Hz; windows {len(rows)}, used {ok.sum()} (snr>{SNR_MIN}, uncontaminated, I_cmd>1 A)")
print(f"best-fit carrier constant c: median {np.median(R['c'][ok]):.1f} Hz per m/s "
      f"(IQR {np.percentile(R['c'][ok], 25):.1f}-{np.percentile(R['c'][ok], 75):.1f})")

# regression log A6 = a + b log v + g log I
X = np.column_stack([np.ones(ok.sum()), np.log(R["v"][ok]), np.log(R["I"][ok])])
y = np.log(R["A6"][ok])
coef, res, *_ = np.linalg.lstsq(X, y, rcond=None)
resid = y - X @ coef
cov = np.linalg.inv(X.T @ X) * resid.var(ddof=3)
se = np.sqrt(np.diag(cov))
print(f"log A6 = {coef[0]:.2f} + b log v + g log I:  b = {coef[1]:.2f} +/- {se[1]:.2f}, "
      f"g = {coef[2]:.2f} +/- {se[2]:.2f}; resid sd {resid.std():.3f}")
# speed-only fit (current range is narrow)
Xv = np.column_stack([np.ones(ok.sum()), np.log(R["v"][ok])])
cv, *_ = np.linalg.lstsq(Xv, y, rcond=None)
print(f"speed-only fit: A6 ~ v^{cv[1]:.2f}")

# normalised ripple k6 = A6 / (P_mech / V_bus), P_mech = K_F * I_cmd * v
Pm = K_F * R["I"] * R["v"]
k6 = R["A6"] / (Pm / R["Vbus"])
print("v bin   n   A6 [mA]   I_cmd [A]   P_mech [W]   k6 = A6/(P_mech/V_bus)   A6/I_cmd [mA/A]")
for lo, hi in [(0.3, 0.45), (0.45, 0.65), (0.7, 0.9), (0.9, 1.15), (1.15, 1.3), (1.3, 1.45), (1.45, 1.6), (1.9, 2.1)]:
    m = ok & (R["v"] >= lo) & (R["v"] < hi)
    if m.sum():
        print(f"{lo:.2f}-{hi:.2f} {m.sum():3d}  {1e3*np.median(R['A6'][m]):7.2f}   {np.median(R['I'][m]):6.2f}"
              f"       {np.median(Pm[m]):6.2f}        {np.median(k6[m]):6.3f}                 "
              f"{1e3*np.median(R['A6'][m]/R['I'][m]):6.2f}")

# fixed-current subset (open-loop holds at I_cmd = 4.2 A): the speed exponent with current held
m42 = ok & (np.abs(R["I"] - 4.2) < 0.02)
x42, y42 = np.log(R["v"][m42]), np.log(R["A6"][m42])
X42 = np.column_stack([np.ones(m42.sum()), x42]); c42, *_ = np.linalg.lstsq(X42, y42, rcond=None)
r42 = y42 - X42 @ c42
se42 = np.sqrt(np.linalg.inv(X42.T @ X42)[1, 1] * r42.var(ddof=2))
print(f"fixed I_cmd = 4.2 A: n {m42.sum()}, v {R['v'][m42].min():.2f}-{R['v'][m42].max():.2f} m/s, "
      f"A6 ~ v^{c42[1]:.2f} +/- {se42:.2f}")

# figure: measured amplitude against each hypothesis's prediction from the window's own v and I,
# each normalised at the 1.3-1.45 m/s open-loop hold
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#e4e3df", "grid.linewidth": 0.6,
                     "axes.edgecolor": "#8a897f", "axes.labelcolor": "#3b3a36",
                     "xtick.color": "#5c5b55", "ytick.color": "#5c5b55"})
fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.5, 3.8))
ref = ok & (R["v"] >= 1.3) & (R["v"] < 1.45)
order = np.argsort(R["v"][ok])
vo, Io, Vo = R["v"][ok][order], R["I"][ok][order], R["Vbus"][ok][order]
for law, ls, col, lab in [(vo * Io / Vo, "-", "#1f1e1c", "back-EMF harmonics: ∝ v·I (mechanical power)"),
                          (Io, "--", "#d55181", "dead time: ∝ I"),
                          (Io / vo, ":", "#7a5cc4", "cogging: ∝ I / v")]:
    full = {"v·I": R["v"] * R["I"] / R["Vbus"], "I": R["I"], "I/v": R["I"] / R["v"]}
    key = "v·I" if "v·I" in lab else ("I / v" if "/ v" in lab else "I")
    key = key.replace(" ", "")
    scale = np.median(R["A6"][ref]) / np.median(full[key][ref])
    a1.plot(vo, 1e3 * scale * law, ls=ls, color=col, lw=1.3, label=lab)
a1.plot(R["v"][ok], 1e3 * R["A6"][ok], "o", ms=3.5, color="#2a78d6", alpha=0.6, label="measured (ML0226, 2 s windows)")
a1.set_yscale("log"); a1.set_ylim(2, 150)
a1.set_xlabel("Speed [m/s]"); a1.set_ylabel("6x bus-current ripple, peak [mA]")
a1.set_title("Measured amplitude against three hypotheses", loc="left", fontsize=10, color="#1f1e1c")
a1.legend(frameon=False, fontsize=7.2, loc="upper left")
a2.plot(R["v"][ok], k6[ok], "o", ms=3.5, color="#eb6834", alpha=0.6)
a2.set_ylim(0, 0.2)
a2.set_xlabel("Speed [m/s]"); a2.set_ylabel("k6 = A6 / (P_mech / V_bus)")
a2.set_title("Ripple as a fraction of mechanical power", loc="left", fontsize=10, color="#1f1e1c")
fig.tight_layout()
fig.savefig(f"{OUT}/vbus_6x_scaling.png", dpi=150)
np.savez(f"{OUT}/../vbus_6x_scaling_windows.npz", **R)
