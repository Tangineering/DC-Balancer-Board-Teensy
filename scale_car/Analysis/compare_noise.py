#!/usr/bin/env python3
r"""
compare_noise.py — noise floor and spectrum, two bags side by side.

    python3 compare_noise.py <bag_before> <bag_after>

Written to answer one question: did reducing the drive controller bandwidth
actually lower the current ripple, and at what cost to tracking.

METHOD
------
Noise is estimated from SUCCESSIVE DIFFERENCES, sigma = pstdev(diff)/sqrt(2).
That high-passes the smooth part of the signal, so a trending current does not
read as noise. Same estimator check_noise.py uses, so numbers are comparable.

Segments are split on speed, not on time: stationary (v < 0.1 m/s) is the
sensor and ADC floor with no control loop active; moving is the floor plus
whatever the loop and the converters add. The bandwidth change should move the
second and leave the first alone — if BOTH move, something other than the
controller changed between the runs.

CAVEAT ON THE SPECTRUM
----------------------
Telemetry is 50 Hz, so this shows 0-25 Hz only. The real switching ripple is at
tens of kHz and has already been aliased down by the time it reaches a packet.
What the PSD shows is the fold, not the source. It is still useful for
comparing two runs of the same rig, which is all this is for.
"""

import glob
import os
import sys

import numpy as np

IDX = {"v_actual": 0, "V_batt": 1, "I_batt": 2, "V_fc": 4,
       "I_fc": 5, "V_bus": 6, "share": 9}
CHANNELS = ["I_fc", "I_batt", "V_bus", "V_fc", "share"]


def find_mcap(p):
    if os.path.isfile(p) and p.endswith(".mcap"):
        return p
    hits = glob.glob(os.path.join(p, "*.mcap"))
    if len(hits) != 1:
        sys.exit(f"expected one .mcap in {p}, found {len(hits)}")
    return hits[0]


def load(path):
    try:
        from mcap_ros2.reader import read_ros2_messages
    except ImportError:
        sys.exit("pip install mcap mcap-ros2-support")
    rows, t = [], []
    t0 = None
    for m in read_ros2_messages(find_mcap(path)):
        if m.channel.topic != "/vehicle_state":
            continue
        d = list(m.ros_msg.data)
        if len(d) < 18:
            continue
        ts = m.log_time_ns / 1e9
        if t0 is None:
            t0 = ts
        t.append(ts - t0)
        rows.append(d[:18])
    if len(rows) < 100:
        sys.exit(f"too few /vehicle_state samples in {path}")
    return np.array(t), np.array(rows, dtype=float)


def sigma(v):
    """White-noise sigma via successive differences."""
    if len(v) < 3:
        return float("nan")
    return float(np.std(np.diff(v)) / np.sqrt(2.0))


def psd(t, v, fs=50.0):
    v = v - np.mean(v)
    n = len(v)
    if n < 256:
        return None, None
    w = np.hanning(n)
    f = np.fft.rfftfreq(n, 1.0 / fs)
    p = np.abs(np.fft.rfft(v * w)) ** 2 / (fs * np.sum(w ** 2))
    return f, p


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    paths = sys.argv[1:3]
    names = [os.path.basename(p.rstrip("/")) for p in paths]
    data = [load(p) for p in paths]

    for (t, d), nm in zip(data, names):
        mv = d[:, IDX["v_actual"]] > 0.1
        print(f"{nm}: {len(t)} samples, {t[-1]:.1f} s, "
              f"{100*mv.mean():.0f}% moving, v_max {d[:,0].max():.2f} m/s")

    for seg, mask_fn in (("STATIONARY (sensor floor)", lambda d: d[:, 0] <= 0.1),
                         ("MOVING (floor + loop)",     lambda d: d[:, 0] >  0.1)):
        print(f"\n=== {seg} ===")
        print(f"{'channel':<10}{names[0][:26]:>28}{names[1][:26]:>28}{'ratio':>9}")
        for ch in CHANNELS:
            vals = []
            for (t, d) in data:
                m = mask_fn(d)
                vals.append(sigma(d[m, IDX[ch]]) if m.sum() > 50 else float("nan"))
            r = vals[1] / vals[0] if vals[0] and np.isfinite(vals[0]) and vals[0] > 0 else float("nan")
            flag = ""
            if np.isfinite(r):
                flag = "  <-- better" if r < 0.8 else ("  <-- WORSE" if r > 1.25 else "")
            print(f"{ch:<10}{vals[0]:>28.5f}{vals[1]:>28.5f}{r:>9.2f}{flag}")

    print("\n  ratio = after / before. Below 1 is less noise.")
    print("  Expect the moving rows to improve and the stationary rows to")
    print("  stay put. If stationary also moved, something besides the")
    print("  controller bandwidth differs between these runs.")

    # tracking cost: how fast does v_actual follow a step
    print("\n=== tracking (the cost of lower bandwidth) ===")
    for (t, d), nm in zip(data, names):
        v = d[:, 0]
        a = np.gradient(np.convolve(v, np.ones(11)/11, mode="same"), t)
        mv = v > 0.3
        print(f"  {nm[:40]:<42} max accel {a[mv].max() if mv.any() else float('nan'):6.3f} "
              f"m/s^2   max decel {a[mv].min() if mv.any() else float('nan'):6.3f}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n(matplotlib missing, skipping the spectrum plot)")
        return

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.4))
    for ax, ch in zip(axes, ["I_fc", "I_batt"]):
        for (t, d), nm, c in zip(data, names, ["#888888", "#1F497D"]):
            m = d[:, 0] > 0.1
            if m.sum() < 256:
                continue
            f, p = psd(t[m], d[m, IDX[ch]])
            if f is None:
                continue
            ax.semilogy(f, p, lw=0.9, color=c, label=nm[:30])
        ax.set_title(f"{ch} while moving")
        ax.set_xlabel("frequency [Hz]  (aliased — 50 Hz telemetry)")
        ax.set_ylabel("PSD")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7)
    fig.tight_layout()
    out = "noise_comparison.png"
    fig.savefig(out, dpi=130)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
