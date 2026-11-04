"""
plot_ab.py — render the A/B sweep runs and save them to logs/rosbags/plots.

Run from the Analysis folder, after the CSVs have been exported:
    python3 plot_ab.py ../../logs/rosbags/rosbag_sweep-noclip_<stamp> ../../logs/rosbags/rosbag_sweep-clip_<stamp>

Saves, into ../../logs/rosbags/plots/:
    <bagname>.png   one 4-panel plot per run
    sweep_AB_compare.png   the two share traces stacked, for the write-up
"""
import csv, os, sys

import matplotlib
matplotlib.use("Agg")                     # save only, no window
import matplotlib.pyplot as plt

OUT = "../../logs/rosbags/plots"

def load(bag):
    d = {}
    for name in ("vehicle_state", "ems_command", "drive_cycle"):
        p = os.path.join(bag, "csv", name + ".csv")
        if os.path.exists(p):
            rows = list(csv.DictReader(open(p)))
            if rows:
                d[name] = {k: [float(r[k]) for r in rows] for k in rows[0]}
    return d

def panels(bag, d, path):
    vs = d.get("vehicle_state"); cm = d.get("ems_command")
    fig, ax = plt.subplots(4, 1, figsize=(13, 11), sharex=True)
    fig.suptitle(os.path.basename(bag), fontsize=13, fontweight="bold")

    if vs:
        ax[0].plot(vs["t_s"], vs["v_actual"], lw=1.0, label="v_actual")
    if "drive_cycle" in d:
        dc = d["drive_cycle"]
        ax[0].plot(dc["t_s"], dc["v_ref"], lw=1.0, ls="--", label="v_ref")
    ax[0].set_ylabel("speed (m/s)"); ax[0].set_title("Speed", fontsize=10, loc="left")
    ax[0].legend(fontsize=8); ax[0].grid(alpha=.3)

    if cm: ax[1].plot(cm["t_s"], cm["power_share_cmd"], lw=1.4, label="commanded")
    if vs: ax[1].plot(vs["t_s"], vs["power_share_actual"], lw=0.9, alpha=.8, label="achieved")
    ax[1].set_ylabel("power share"); ax[1].set_ylim(-.05, 1.05)
    ax[1].set_title("Power split", fontsize=10, loc="left")
    ax[1].legend(fontsize=8); ax[1].grid(alpha=.3)

    if vs:
        ax[2].plot(vs["t_s"], vs["I_fc"],   lw=0.9, label="I_fc")
        ax[2].plot(vs["t_s"], vs["I_batt"], lw=0.9, label="I_batt")
        tot = [a + b for a, b in zip(vs["I_fc"], vs["I_batt"])]
        ax[2].plot(vs["t_s"], tot, lw=1.2, color="k", alpha=.5, label="I_total")
        ax[2].axhline(0.25, ls=":", color="tab:red", lw=1.2)
        ax[2].text(vs["t_s"][0], 0.26, " closed-loop gate 0.25 A", fontsize=8, color="tab:red")
        ax[2].set_ylabel("current (A)")
        axb = ax[2].twinx()
        axb.plot(vs["t_s"], vs["V_bus"], lw=0.7, color="gray", alpha=.6)
        axb.set_ylabel("V_bus (V)", color="gray")
    ax[2].set_title("Source currents", fontsize=10, loc="left")
    ax[2].legend(fontsize=8, loc="upper left"); ax[2].grid(alpha=.3)

    if vs:
        ax[3].plot(vs["t_s"], vs["SOC"], lw=1.3, color="tab:green", label="SOC")
        ax[3].set_ylabel("SOC")
        if any(f != 0 for f in vs["fault_flags"]):
            axf = ax[3].twinx()
            axf.plot(vs["t_s"], vs["fault_flags"], lw=0.9, color="tab:red")
            axf.set_ylabel("fault_flags", color="tab:red")
    ax[3].set_title("SOC and fault flags", fontsize=10, loc="left")
    ax[3].set_xlabel("time (s)"); ax[3].legend(fontsize=8, loc="upper left"); ax[3].grid(alpha=.3)

    plt.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)
    print("  saved", path)

def compare(bags, data, path):
    fig, ax = plt.subplots(len(bags), 1, figsize=(13, 4.2 * len(bags)), sharex=True, sharey=True)
    if len(bags) == 1: ax = [ax]
    fig.suptitle("Feasible-band clip — commanded vs achieved share",
                 fontsize=13, fontweight="bold")
    for k, (bag, d) in enumerate(zip(bags, data)):
        vs = d.get("vehicle_state"); cm = d.get("ems_command")
        if cm: ax[k].plot(cm["t_s"], cm["power_share_cmd"], lw=1.6, label="commanded")
        if vs: ax[k].plot(vs["t_s"], vs["power_share_actual"], lw=0.9, alpha=.8, label="achieved")
        ax[k].set_title(os.path.basename(bag), fontsize=10, loc="left")
        ax[k].set_ylabel("power share"); ax[k].set_ylim(-.05, 1.05)
        ax[k].legend(fontsize=8); ax[k].grid(alpha=.3)
    ax[-1].set_xlabel("time (s)")
    plt.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)
    print("  saved", path)

def main():
    bags = sys.argv[1:]
    if not bags:
        sys.exit("usage: python3 plot_ab.py <bagA> <bagB>")
    os.makedirs(OUT, exist_ok=True)
    data = []
    for b in bags:
        b = b.rstrip("/")
        d = load(b)
        if "vehicle_state" not in d:
            sys.exit(f"no csv/vehicle_state.csv in {b} — run fchev_plot.py --csv first")
        data.append(d)
        panels(b, d, os.path.join(OUT, os.path.basename(b) + ".png"))
    if len(bags) > 1:
        compare([b.rstrip("/") for b in bags], data,
                os.path.join(OUT, "sweep_AB_compare.png"))

if __name__ == "__main__":
    main()
