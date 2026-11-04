#!/usr/bin/env python3
"""
fchev_plot.py — Read an FCHEV .mcap rosbag on Windows (no ROS install needed)
UC Davis Future Mobility Lab | Scaled FCHEV Platform

One-time setup:
    pip install mcap mcap-ros2-support matplotlib

Usage — plot straight from the bag folder:
    python fchev_plot.py rosbag_2026-09-07_22-06-29

Also export CSVs while you're at it:
    python fchev_plot.py rosbag_2026-09-07_22-06-29 --csv

Point it at either the bag folder or the .mcap file directly; both work.
"""

import argparse
import csv
import glob
import os
import sys

try:
    from mcap_ros2.reader import read_ros2_messages
except ImportError:
    sys.exit(
        "Missing packages. Run:\n"
        "    pip install mcap mcap-ros2-support matplotlib\n"
    )


# ── Field names, matching Signal Table Rev 2026-08-17A (v4 packet) ───────────
FIELDS = {
    "/vehicle_state": [
        "v_actual", "V_batt", "I_batt", "I_charge", "V_fc",
        "I_fc", "V_bus", "V_rgn", "V_chg", "power_share_actual",
        "droop_FC", "droop_BT", "charger_status", "switch_state",
        "fault_flags", "error_code", "error_source_state", "SOC",
    ],
    "/ems_command": [
        "v_setpoint", "power_share_cmd", "charge_goal", "mode", "droop_enable",
    ],
    "/ems_diagnostics": [
        "P_fc", "P_batt", "power_share_diag", "feasible",
        "soc_clamped", "solve_ms", "mode_diag",
    ],
    "/drive_cycle": [
        "v_ref", "P_demand", "elapsed_s", "progress",
    ],
    "/comms_status": [
        "pkts_rx", "pkts_dropped", "stale_ms", "link_ok",
    ],
}


def find_mcap(path):
    """Accept either the bag directory or the .mcap file itself."""
    if os.path.isfile(path) and path.endswith(".mcap"):
        return path
    if os.path.isdir(path):
        hits = glob.glob(os.path.join(path, "*.mcap"))
        if len(hits) == 1:
            return hits[0]
        if not hits:
            sys.exit(f"No .mcap file found in {path}")
        sys.exit(f"Multiple .mcap files in {path} — pass one explicitly:\n  " +
                 "\n  ".join(hits))
    sys.exit(f"Not found: {path}")


def read_bag(mcap_path):
    """Return {topic: (times[], [series per field])}."""
    raw = {t: [] for t in FIELDS}
    t0 = None

    for m in read_ros2_messages(mcap_path):
        topic = m.channel.topic
        if topic not in raw:
            continue
        if t0 is None:
            t0 = m.log_time_ns
        vals = list(m.ros_msg.data)
        raw[topic].append(((m.log_time_ns - t0) / 1e9, vals))

    out = {}
    for topic, rows in raw.items():
        if not rows:
            continue
        names = FIELDS[topic]
        times = [r[0] for r in rows]
        cols = {}
        for i, name in enumerate(names):
            cols[name] = [r[1][i] if i < len(r[1]) else float("nan") for r in rows]
        out[topic] = (times, cols)
    return out


def trim(data, tmin, tmax):
    """Keep only samples with tmin <= t <= tmax, per topic."""
    out = {}
    for topic, (times, cols) in data.items():
        keep = [i for i, t in enumerate(times)
                if (tmin is None or t >= tmin) and (tmax is None or t <= tmax)]
        if not keep:
            continue
        out[topic] = ([times[i] for i in keep],
                      {n: [v[i] for i in keep] for n, v in cols.items()})
    return out


def noise_sigma(v):
    """White-noise sigma via successive differences, which high-pass the smooth signal."""
    if len(v) < 3:
        return float("nan")
    d = [v[i + 1] - v[i] for i in range(len(v) - 1)]
    m = sum(d) / len(d)
    var = sum((x - m) ** 2 for x in d) / len(d)
    return (var ** 0.5) / (2 ** 0.5)


def apply_filter(data, tau_ms):
    """
    Preview the Teensy-side EMA: filter the raw analog channels in place and
    recompute power_share_actual from the FILTERED currents, which is the whole
    point — the share ratio is where the current noise gets amplified.

    NOTE this runs on 50 Hz telemetry, while the Teensy loop is far faster. The
    firmware filter would see ~20x more samples per time constant, so this
    UNDERSTATES the achievable improvement. Treat it as a shape preview, not a
    prediction of the final noise floor.
    """
    if "/vehicle_state" not in data:
        return data, {}
    times, cols = data["/vehicle_state"]
    chans = ["I_fc", "I_batt", "V_fc", "V_batt", "V_bus", "V_rgn", "V_chg"]
    before = {c: noise_sigma(cols[c]) for c in chans if c in cols}
    before["power_share_actual"] = noise_sigma(cols.get("power_share_actual", []))

    for c in chans:
        if c not in cols:
            continue
        src = cols[c]
        out = [src[0]]
        for i in range(1, len(src)):
            dt_ms = max(1e-6, (times[i] - times[i - 1]) * 1000.0)
            a = dt_ms / (tau_ms + dt_ms)
            out.append(out[-1] + a * (src[i] - out[-1]))
        cols[c] = out

    # Re-derive the share from the filtered currents, mirroring computeDerivedSignals()
    if "I_fc" in cols and "I_batt" in cols and "power_share_actual" in cols:
        sh = []
        last = 0.5
        for ifc, ibt in zip(cols["I_fc"], cols["I_batt"]):
            tot = abs(ifc) + abs(ibt)
            if tot > 0.05:          # low-current guard, see the ratio note
                last = abs(ifc) / tot
            sh.append(last)
        cols["power_share_actual"] = sh

    after = {c: noise_sigma(cols[c]) for c in chans if c in cols}
    after["power_share_actual"] = noise_sigma(cols["power_share_actual"])
    return data, {"before": before, "after": after, "tau_ms": tau_ms}


def report_filter(st):
    if not st:
        return
    LSB = 0.00806
    print(f"\n  Filter preview — EMA tau = {st['tau_ms']:g} ms, applied at telemetry rate")
    print(f"    {'channel':<20}{'before':>10}{'':<11}{'after':>10}{'':<4}{'ratio':>7}")
    for c in st["before"]:
        b, a = st["before"][c], st["after"].get(c, float("nan"))
        if b != b:
            continue
        unit = "A" if c.startswith("I_") else ("V" if c.startswith("V_") else " ")
        extra = f"({b/LSB:5.1f} LSB)" if c.startswith("I_") else ""
        print(f"    {c:<20}{b:>10.4f} {unit}  {extra:<11}{a:>10.4f} {unit}  {b/a if a else 0:>5.1f}x")


def summarise(data):
    print("\n  Run summary")
    for topic, (times, _) in data.items():
        rate = len(times) / times[-1] if times and times[-1] > 0 else 0
        print(f"    {topic:<20} {len(times):>6} msgs   {rate:5.1f} Hz")

    if "/vehicle_state" not in data:
        return
    times, c = data["/vehicle_state"]
    print(f"\n    duration        {times[-1]:.1f} s")
    print(f"    SOC             {min(c['SOC']):.3f} -> {max(c['SOC']):.3f}")
    print(f"    v_actual max    {max(c['v_actual']):.2f} m/s")
    print(f"    V_bus           {min(c['V_bus']):.2f} – {max(c['V_bus']):.2f} V")

    bad = [f for f in c["fault_flags"] if f != 0]
    if bad:
        codes = sorted({int(f) for f in bad})
        print(f"    FAULTS          {len(bad)} samples nonzero, codes: " +
              ", ".join(f"0x{x:04X}" for x in codes))
    else:
        print("    faults          none (clean run)")


def write_csvs(data, outdir):
    os.makedirs(outdir, exist_ok=True)
    for topic, (times, cols) in data.items():
        name = topic.strip("/").replace("/", "_") + ".csv"
        path = os.path.join(outdir, name)
        names = list(cols.keys())
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_s"] + names)
            for i, t in enumerate(times):
                w.writerow([f"{t:.6f}"] + [cols[n][i] for n in names])
        print(f"    wrote {name}  ({len(times)} rows)")


def plot(data, title, save=None, show=True):
    import matplotlib
    if not show:
        matplotlib.use("Agg")          # no display needed when only saving
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(4, 1, figsize=(11, 11), sharex=True)
    fig.suptitle(title, fontsize=13, fontweight="bold")

    # 1 — speed tracking
    if "/vehicle_state" in data:
        t, c = data["/vehicle_state"]
        ax[0].plot(t, c["v_actual"], lw=1.2, label="v_actual")
    if "/drive_cycle" in data:
        t, c = data["/drive_cycle"]
        ax[0].plot(t, c["v_ref"], lw=1.2, ls="--", label="v_ref")
    ax[0].set_ylabel("speed (m/s)")
    ax[0].set_title("Speed tracking", fontsize=10, loc="left")
    ax[0].legend(fontsize=8); ax[0].grid(alpha=.3)

    # 2 — power share, commanded vs achieved
    if "/ems_command" in data:
        t, c = data["/ems_command"]
        ax[1].plot(t, c["power_share_cmd"], lw=1.2, label="commanded")
    if "/vehicle_state" in data:
        t, c = data["/vehicle_state"]
        ax[1].plot(t, c["power_share_actual"], lw=1.0, alpha=.8, label="achieved")
    ax[1].set_ylabel("power share")
    ax[1].set_ylim(-0.05, 1.05)
    ax[1].set_title("Power split — commanded vs achieved", fontsize=10, loc="left")
    ax[1].legend(fontsize=8); ax[1].grid(alpha=.3)

    # 3 — currents and bus
    if "/vehicle_state" in data:
        t, c = data["/vehicle_state"]
        ax[2].plot(t, c["I_fc"], lw=1.2, label="I_fc")
        ax[2].plot(t, c["I_batt"], lw=1.2, label="I_batt")
        ax[2].set_ylabel("current (A)")
        axb = ax[2].twinx()
        axb.plot(t, c["V_bus"], lw=0.9, color="gray", alpha=.6, label="V_bus")
        axb.set_ylabel("V_bus (V)", color="gray")
    ax[2].set_title("Source currents and bus voltage", fontsize=10, loc="left")
    ax[2].legend(fontsize=8, loc="upper left"); ax[2].grid(alpha=.3)

    # 4 — SOC and faults
    if "/vehicle_state" in data:
        t, c = data["/vehicle_state"]
        ax[3].plot(t, c["SOC"], lw=1.4, color="tab:green", label="SOC")
        ax[3].axhline(0.32, ls=":", lw=1, color="tab:red", alpha=.7)
        ax[3].axhline(0.78, ls=":", lw=1, color="tab:red", alpha=.7)
        ax[3].set_ylabel("SOC")
        if any(f != 0 for f in c["fault_flags"]):
            axf = ax[3].twinx()
            axf.plot(t, c["fault_flags"], lw=1, color="tab:red", label="fault_flags")
            axf.set_ylabel("fault_flags", color="tab:red")
    ax[3].set_title("SOC (dotted lines = 0.32 / 0.78 guards)", fontsize=10, loc="left")
    ax[3].set_xlabel("time (s)")
    ax[3].legend(fontsize=8, loc="upper left"); ax[3].grid(alpha=.3)

    plt.tight_layout()

    if save:
        os.makedirs(os.path.dirname(save), exist_ok=True)
        fig.savefig(save, dpi=150)
        print(f"\n  saved {save}")

    if show:
        plt.show()
    else:
        plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description="Plot an FCHEV rosbag2 .mcap run")
    ap.add_argument("bag", help="bag folder or .mcap file")
    ap.add_argument("--csv", action="store_true", help="also export CSVs")
    ap.add_argument("--no-plot", action="store_true", help="skip plotting")
    ap.add_argument("--tmin", type=float, default=None,
                    help="start of time window, seconds from run start")
    ap.add_argument("--tmax", type=float, default=None,
                    help="end of time window, seconds from run start "
                         "(e.g. --tmax 125 for the first 125 s)")
    ap.add_argument("--filter", type=float, default=None, metavar="TAU_MS",
                    help="preview the Teensy-side EMA: filter the analog channels with "
                         "this time constant in ms and re-derive power_share_actual from "
                         "the filtered currents (e.g. --filter 20)")
    ap.add_argument("--sigma", action="store_true",
                    help="report white-noise sigma per channel and exit")
    ap.add_argument("--save", default=None, metavar="PNG",
                    help="write the figure to this path as well as showing it")
    ap.add_argument("--no-show", action="store_true",
                    help="with --save, skip the interactive window")
    args = ap.parse_args()

    mcap_path = find_mcap(args.bag)
    name = os.path.basename(os.path.dirname(mcap_path)) or os.path.basename(mcap_path)
    print(f"Reading {os.path.basename(mcap_path)} ...")

    data = read_bag(mcap_path)
    if not data:
        sys.exit("No recognised FCHEV topics found in this bag.")

    if args.tmin is not None or args.tmax is not None:
        data = trim(data, args.tmin, args.tmax)
        if not data:
            sys.exit("Time window contains no samples — check --tmin / --tmax.")
        lo = "0" if args.tmin is None else f"{args.tmin:g}"
        hi = "end" if args.tmax is None else f"{args.tmax:g}"
        name = f"{name}  [{lo}–{hi} s]"
        print(f"  windowed to {lo}–{hi} s")

    fstats = {}
    if args.filter is not None:
        data, fstats = apply_filter(data, args.filter)
        name = f"{name}  [EMA {args.filter:g} ms]"

    if args.sigma:
        LSB = 0.00806
        t, c = data["/vehicle_state"]
        print("\n  White-noise sigma (successive differences)")
        for ch in ("I_fc", "I_batt", "V_fc", "V_batt", "V_bus"):
            if ch in c:
                s = noise_sigma(c[ch])
                extra = f"  ({s/LSB:5.1f} LSB)" if ch.startswith("I_") else ""
                print(f"    {ch:<10}{s:9.4f}{extra}")
        s = noise_sigma(c.get("power_share_actual", []))
        print(f"    {'share':<10}{s:9.4f}")

    summarise(data)
    report_filter(fstats)

    if args.csv:
        outdir = os.path.join(os.path.dirname(mcap_path) or ".", "csv")
        print(f"\n  Writing CSVs to {outdir}")
        write_csvs(data, outdir)

    if not args.no_plot:
        plot(data, name, save=args.save, show=not args.no_show)


if __name__ == "__main__":
    main()
