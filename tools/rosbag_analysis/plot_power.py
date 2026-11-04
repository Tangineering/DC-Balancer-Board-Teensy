#!/usr/bin/env python3
"""
plot_power.py — P_fc, P_batt and P_demand only.

    python3 plot_power.py ../../logs/rosbags/rosbag_sdp_2026-10-28_20-46-53 [out.png]

P_fc and P_batt come from /ems_diagnostics; P_demand from /drive_cycle.
Saves a PNG if a second argument is given, otherwise opens a window.
"""
import glob
import os
import sys

try:
    from mcap_ros2.reader import read_ros2_messages
    import matplotlib
except ImportError:
    sys.exit("pip install mcap mcap-ros2-support matplotlib")

if len(sys.argv) > 2:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt


def find(p):
    if os.path.isfile(p) and p.endswith(".mcap"):
        return p
    h = glob.glob(os.path.join(p, "*.mcap"))
    if len(h) == 1:
        return h[0]
    sys.exit(f"Expected one .mcap in {p}, found {len(h)}")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    bag = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None

    td, pfc, pbt, tc, pdem = [], [], [], [], []
    t0 = None
    for m in read_ros2_messages(find(bag)):
        top = m.channel.topic
        if top not in ("/ems_diagnostics", "/drive_cycle"):
            continue
        ts = m.log_time_ns / 1e9
        if t0 is None:
            t0 = ts
        d = list(m.ros_msg.data)
        if top == "/ems_diagnostics" and len(d) >= 2:
            td.append(ts - t0); pfc.append(d[0]); pbt.append(d[1])
        elif top == "/drive_cycle" and len(d) >= 2:
            tc.append(ts - t0); pdem.append(d[1])

    if not td:
        sys.exit("No /ems_diagnostics in this bag.")

    fig, ax = plt.subplots(figsize=(14, 6))
    if tc:
        ax.plot(tc, pdem, color="#7F7F7F", lw=1.2, label="P_demand")
    ax.plot(td, pbt, color="#C0504D", lw=1.0, label="P_batt")
    ax.plot(td, pfc, color="#1F497D", lw=1.4, label="P_fc")
    ax.axhline(0, color="#BFBFBF", lw=0.8)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("power (W)")
    ax.set_title(os.path.basename(bag.rstrip("/")))
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()

    sp = sum(1 for v in pfc if abs(v) > 0.05)
    print(f"samples   diagnostics {len(td)}, drive_cycle {len(tc)}")
    print(f"P_fc      min {min(pfc):+.2f}  max {max(pfc):+.2f} W   "
          f"nonzero {sp}/{len(pfc)} ({sp/len(pfc)*100:.1f}%)")
    print(f"P_batt    min {min(pbt):+.2f}  max {max(pbt):+.2f} W")
    if pdem:
        print(f"P_demand  min {min(pdem):+.2f}  max {max(pdem):+.2f} W")

    if out:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        fig.savefig(out, dpi=150)
        print(f"saved {out}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
