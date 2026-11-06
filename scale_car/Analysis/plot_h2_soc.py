#!/usr/bin/env python3
r"""
plot_h2_soc.py — hydrogen usage and EKF state of charge from one bag.

    python3 plot_h2_soc.py <bagdir> [--soc-min 0.5] [--soc-max 0.8] [--save out.png]

Reads the two topics the 2026-11-03A bridge added, /h2_usage and
/soc_diagnostics, alongside /vehicle_state. None of the older analysis scripts
know about them.

/h2_usage        [0] mdot_g_s  [1] total_g  [2] i_stack  [3] p_stack
                 [4] faraday_ml_min  [5] purge_g_s
/soc_diagnostics [0] soc  [1] sigma  [2] innovation  [3] k_soc  [4] i_pack  [5] v1
/vehicle_state   [0] v_actual  [4] V_fc  [5] I_fc  [6] V_bus  [17] SOC

WHAT TO READ OFF IT
-------------------
Panel 3, the innovation, is the EKF's own report card: measured terminal
voltage minus what the model predicted. White noise around zero means the
model fits. Structure that tracks the load means R0 is wrong — which it
currently is, since pack_r_int_ohm is still the 0.050 placeholder.

Panel 2's cumulative grams is Faraday only unless h2_purge_ml_min has been
set from an idle soak, so it is a LOWER BOUND on consumption.
"""

import argparse
import glob
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

NAVY, GOLD, GREY = "#1F497D", "#DFBF50", "#888888"


def find_mcap(p):
    if os.path.isfile(p) and p.endswith(".mcap"):
        return p
    hits = glob.glob(os.path.join(p, "*.mcap"))
    if len(hits) != 1:
        sys.exit(f"expected one .mcap in {p}, found {len(hits)}")
    return hits[0]


def read(path):
    try:
        from mcap_ros2.reader import read_ros2_messages
    except ImportError:
        sys.exit("pip install mcap mcap-ros2-support")
    out = {"/vehicle_state": [], "/h2_usage": [], "/soc_diagnostics": []}
    t0 = None
    for m in read_ros2_messages(find_mcap(path)):
        if m.channel.topic not in out:
            continue
        ts = m.log_time_ns / 1e9
        if t0 is None:
            t0 = ts
        out[m.channel.topic].append((ts - t0, list(m.ros_msg.data)))
    return out


def arr(rows, n):
    if not rows:
        return None, None
    t = np.array([r[0] for r in rows])
    d = np.array([r[1][:n] for r in rows if len(r[1]) >= n], dtype=float)
    return (t[:len(d)], d) if len(d) else (None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bag")
    ap.add_argument("--soc-min", type=float, default=0.5)
    ap.add_argument("--soc-max", type=float, default=0.8)
    ap.add_argument("--save", default=None)
    ap.add_argument("--two", action="store_true",
                    help="just SOC and hydrogen; drop the stack-power and "
                         "innovation panels")
    a = ap.parse_args()

    topics = read(a.bag)
    tv, vs = arr(topics["/vehicle_state"], 18)
    th, h2 = arr(topics["/h2_usage"], 6)
    ts, sd = arr(topics["/soc_diagnostics"], 6)

    name = os.path.basename(a.bag.rstrip("/"))
    print(f"bag       {name}")
    for k, v in topics.items():
        print(f"  {k:<20} {len(v)} msgs")
    if tv is None:
        sys.exit("no /vehicle_state")
    print(f"  duration  {tv[-1]:.1f} s")

    if h2 is None:
        print("\n  NO /h2_usage IN THIS BAG — the old bridge node was running.")
    else:
        print(f"\n--- hydrogen ---")
        print(f"  total            {h2[-1,1]*1000:8.2f} mg over {th[-1]:.0f} s")
        print(f"  mean flow        {np.mean(h2[:,4]):8.2f} ml/min")
        print(f"  peak flow        {np.max(h2[:,4]):8.2f} ml/min")
        print(f"  peak stack power {np.max(h2[:,3]):8.2f} W")
        print(f"  peak stack curr  {np.max(h2[:,2]):8.3f} A")
        if h2[-1,5] == 0.0:
            print("  purge term is ZERO (unmeasured) -> total is a LOWER BOUND")

    print(f"\n--- state of charge ---")
    print(f"  start {vs[0,17]:.4f}   end {vs[-1,17]:.4f}   delta {vs[-1,17]-vs[0,17]:+.4f}")
    if sd is not None:
        print(f"  sigma      final {sd[-1,1]:.5f}")
        print(f"  innovation mean {np.mean(sd[:,2])*1000:+.2f} mV   "
              f"std {np.std(sd[:,2])*1000:.2f} mV")
        print(f"  |innovation| p95 {np.percentile(np.abs(sd[:,2]),95)*1000:.1f} mV")
        drift = np.corrcoef(np.abs(sd[:,4]), sd[:,2])[0,1] if len(sd) > 10 else 0.0
        print(f"  corr(innovation, |i_pack|) = {drift:+.3f}")
        if abs(drift) > 0.3:
            print("    -> innovation tracks load: R0 is wrong. Measure it.")
        else:
            print("    -> no load correlation: R0 is not obviously off")

    if a.two:
        n = 2
    else:
        n = 4 if (h2 is not None or sd is not None) else 2
    fig, ax = plt.subplots(n, 1, figsize=(13, 3.2*n if a.two else 2.6*n), sharex=True)
    ax = np.atleast_1d(ax)
    k = 0

    if a.two:
        # SOC is the subject here, so it takes the left axis and speed goes
        # faint on the right purely for context.
        ax[k].plot(tv, vs[:,17], color="green", lw=1.8, label="SOC")
        ax[k].set_ylim(a.soc_min, a.soc_max)
        ax[k].set_ylabel("SOC"); ax[k].grid(alpha=0.3)
        ax[k].legend(fontsize=9, loc="upper left")
        a2 = ax[k].twinx()
        a2.plot(tv, vs[:,0], color=GREY, lw=0.7, alpha=0.55, label="v_actual")
        a2.set_ylabel("speed [m/s]", color=GREY)
        a2.legend(fontsize=8, loc="upper right")
    else:
        ax[k].plot(tv, vs[:,0], color=NAVY, lw=0.8, label="v_actual")
        ax[k].set_ylabel("speed [m/s]"); ax[k].grid(alpha=0.3)
        ax[k].legend(fontsize=8, loc="upper left")
        a2 = ax[k].twinx()
        a2.plot(tv, vs[:,17], color="green", lw=1.4, label="SOC")
        a2.set_ylim(a.soc_min, a.soc_max); a2.set_ylabel("SOC")
        a2.legend(fontsize=8, loc="upper right")
    ax[k].set_title(name, fontsize=10); k += 1

    if h2 is not None:
        ax[k].plot(th, h2[:,1]*1000, color=NAVY, lw=1.6, label="cumulative H2 [mg]")
        ax[k].set_ylabel("H2 [mg]"); ax[k].grid(alpha=0.3)
        ax[k].legend(fontsize=8, loc="upper left")
        b2 = ax[k].twinx()
        b2.plot(th, h2[:,4], color=GOLD, lw=0.7, alpha=0.8, label="flow [ml/min]")
        b2.set_ylabel("flow [ml/min]"); b2.legend(fontsize=8, loc="upper right")
        k += 1

    if h2 is not None and not a.two:
        ax[k].plot(th, h2[:,3], color=NAVY, lw=0.8, label="P_stack [W]")
        ax[k].set_ylabel("stack power [W]"); ax[k].grid(alpha=0.3)
        ax[k].legend(fontsize=8, loc="upper left")
        c2 = ax[k].twinx()
        c2.plot(th, h2[:,2], color=GOLD, lw=0.7, alpha=0.8, label="I_stack [A]")
        c2.set_ylabel("stack current [A]"); c2.legend(fontsize=8, loc="upper right")
        k += 1

    if sd is not None and not a.two and k < n:
        ax[k].plot(ts, sd[:,2]*1000, color=NAVY, lw=0.7, label="innovation [mV]")
        ax[k].axhline(0, color=GREY, lw=0.8)
        ax[k].set_ylabel("innovation [mV]"); ax[k].grid(alpha=0.3)
        ax[k].legend(fontsize=8, loc="upper left")
        d2 = ax[k].twinx()
        d2.plot(ts, sd[:,1], color=GOLD, lw=1.0, label="sigma_SOC")
        d2.set_ylabel("sigma"); d2.legend(fontsize=8, loc="upper right")
        k += 1

    ax[-1].set_xlabel("time [s]")
    fig.tight_layout()
    out = a.save or os.path.join(
        os.path.dirname(os.path.abspath(a.bag.rstrip("/"))), "Plots",
        name + ("_h2_soc_2panel.png" if a.two else "_h2_soc.png"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=120)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
