"""
Render publication-format PDF figures for the MIMO_Droop_Drive_Comparison report.

Reads CSVs from ../../controller_design_MIMO/figures/ and writes PDFs into ./Figures/.
Run with the controller_design_MIMO venv:
    ../../controller_design_MIMO/ctrl-venv/Scripts/python.exe fig_export.py
"""
import os
import csv
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "controller_design_MIMO", "figures")
OUT = os.path.join(HERE, "Figures")
os.makedirs(OUT, exist_ok=True)

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 9,
    "axes.labelsize": 9,
    "legend.fontsize": 7.5,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "lines.linewidth": 1.3,
    "figure.constrained_layout.use": True,
})

DEC_COLOR = "#1f77b4"   # decentralized (PI) controller
MIMO_COLOR = "#d62728"  # MIMO H-inf controller


def load_csv(name):
    """Read a CSV (skipping '#' comment lines) into a dict of column -> list[float]."""
    path = os.path.join(SRC, name)
    with open(path, newline="") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    reader = csv.reader(lines)
    header = next(reader)
    cols = {h: [] for h in header}
    for row in reader:
        for h, v in zip(header, row):
            try:
                cols[h].append(float(v))
            except ValueError:
                cols[h].append(v)
    return cols


def save(fig, name):
    path = os.path.join(OUT, name)
    fig.savefig(path)
    plt.close(fig)
    size = os.path.getsize(path)
    print(f"wrote {name}: {size/1024:.1f} KB")


# ---------------------------------------------------------------------------
# 1. fig_coupling_sigma.pdf -- plant coupling |Gs12|/|Gs11| and condition number
# ---------------------------------------------------------------------------
def fig_coupling_sigma():
    d = load_csv("coupling_freq.csv")
    w = d["w_rad_s"]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(3.4, 3.6), sharex=True)

    ax1.loglog(w, d["ratio12_nominal"], color="#333333", label="nominal")
    ax1.loglog(w, d["ratio12_light_load_0p5A"], color="#2ca02c", ls="--", label="light load, 0.5 A")
    ax1.loglog(w, d["ratio12_fc_cruise_r0p85"], color="#9467bd", ls=":", label="FC cruise, $r=0.85$")
    ax1.set_ylabel(r"$|G_{s,12}|/|G_{s,11}|$")
    ax1.legend(loc="best", frameon=False)

    ax2.loglog(w, d["cond_nominal"], color="#333333")
    ax2.loglog(w, d["cond_light_load_0p5A"], color="#2ca02c", ls="--")
    ax2.loglog(w, d["cond_fc_cruise_r0p85"], color="#9467bd", ls=":")
    ax2.set_ylabel(r"$\mathrm{cond}(G_s)$")
    ax2.set_xlabel(r"$\omega$ [rad/s]")

    save(fig, "fig_coupling_sigma.pdf")


# ---------------------------------------------------------------------------
# 2. fig_sigma_S_both.pdf -- sigma-bar(S_o) nominal + worst corner, both controllers
# ---------------------------------------------------------------------------
def fig_sigma_S_both():
    dn = load_csv("sigma_nominal_both.csv")
    dw = load_csv("sigma_worst_corner_both.csv")

    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    ax.loglog(dn["w_rad_s"], dn["dec_sigma_So"], color=DEC_COLOR, label="Decentralized, nominal")
    ax.loglog(dn["w_rad_s"], dn["mimo_sigma_So"], color=MIMO_COLOR, label=r"MIMO $H_\infty$, nominal")
    ax.loglog(dw["w_rad_s"], dw["dec_sigma_So"], color=DEC_COLOR, ls="--", label="Decentralized, worst corner")
    ax.loglog(dw["w_rad_s"], dw["mimo_sigma_So"], color=MIMO_COLOR, ls="--", label=r"MIMO $H_\infty$, worst corner")
    ax.set_xlabel(r"$\omega$ [rad/s]")
    ax.set_ylabel(r"$\bar{\sigma}(S_o(j\omega))$")
    ax.legend(loc="best", frameon=False)

    save(fig, "fig_sigma_S_both.pdf")


# ---------------------------------------------------------------------------
# 3. fig_corner_scatter.pdf -- per-corner sigma-bar: decentralized vs MIMO
# ---------------------------------------------------------------------------
def fig_corner_scatter():
    d = load_csv("tier2_corner_scatter.csv")
    x = d["dec_sigma_So"]
    y = d["mimo_sigma_So"]

    fig, ax = plt.subplots(figsize=(3.2, 3.0))
    ax.scatter(x, y, s=14, color=MIMO_COLOR, alpha=0.75, edgecolors="none")
    lo = min(min(x), min(y))
    hi = max(max(x), max(y))
    ax.plot([lo, hi], [lo, hi], color="#888888", ls="--", lw=1, label="dec = MIMO")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel(r"Decentralized $\bar{\sigma}(S_o)$ per corner")
    ax.set_ylabel(r"MIMO $\bar{\sigma}(S_o)$ per corner")
    ax.legend(loc="best", frameon=False)

    save(fig, "fig_corner_scatter.pdf")


# ---------------------------------------------------------------------------
# 4. fig_transient_small.pdf -- 2x2: Delta-alpha and i_cmd for dV0=+-0.4
# ---------------------------------------------------------------------------
def fig_transient_small():
    dp = load_csv("transient_small_dV0p.csv")
    dm = load_csv("transient_small_dV0m.csv")

    # Truncate to the transient + initial steady state: the share settles in
    # ~0.15-0.20 s and the speed in ~0.30 s, so 1 s shows the full transient
    # plus a clear steady-state tail (the source CSVs run 12 s).
    T_SHOW = 1.0

    fig, axes = plt.subplots(2, 2, figsize=(5.2, 3.8), sharex=True)

    for col, (d, title) in zip(range(2), [(dp, r"$\Delta V_0=+0.4$ V"), (dm, r"$\Delta V_0=-0.4$ V")]):
        d = {k: np.asarray(v) for k, v in d.items()}
        msk = d["t_s"] <= T_SHOW
        d = {k: v[msk] for k, v in d.items()}
        t = d["t_s"]
        axtop = axes[0, col]
        axtop.plot(t, d["dec_alpha"], color=DEC_COLOR, label="Decentralized")
        axtop.plot(t, d["mimo_alpha"], color=MIMO_COLOR, label=r"MIMO $H_\infty$")
        axtop.set_title(title, fontsize=8.5)
        if col == 0:
            axtop.set_ylabel(r"$\Delta\alpha$")
            axtop.legend(loc="best", frameon=False)

        axbot = axes[1, col]
        axbot.plot(t, d["dec_i"], color=DEC_COLOR)
        axbot.plot(t, d["mimo_i"], color=MIMO_COLOR)
        axbot.set_xlabel(r"$t$ [s]")
        if col == 0:
            axbot.set_ylabel(r"$i_{cmd}$ [A]")

    save(fig, "fig_transient_small.pdf")


# ---------------------------------------------------------------------------
# 5. fig_regen.pdf -- regen event, v_bus response
# ---------------------------------------------------------------------------
def fig_regen():
    d = load_csv("regen_truth.csv")
    # Truncate to the transient + initial steady state: the event begins at
    # ~0.06 s and v_bus recovers within ~1.0-1.3 s; 5 s shows the full
    # transient plus a clear steady-state tail (the source CSV runs 60 s).
    d = {k: np.asarray(v) for k, v in d.items()}
    msk = d["t_s"] <= 5.0
    d = {k: v[msk] for k, v in d.items()}
    t = d["t_s"]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(3.6, 3.4), sharex=True)
    ax1.plot(t, d["dec_vbus"], color=DEC_COLOR, label="Decentralized")
    ax1.plot(t, d["mimo_vbus"], color=MIMO_COLOR, label=r"MIMO $H_\infty$")
    ax1.set_ylabel(r"$v_{bus}$ [V]")
    ax1.legend(loc="best", frameon=False)

    ax2.plot(t, d["dec_alpha"], color=DEC_COLOR)
    ax2.plot(t, d["mimo_alpha"], color=MIMO_COLOR)
    ax2.set_xlabel(r"$t$ [s]")
    ax2.set_ylabel(r"$\alpha$")

    save(fig, "fig_regen.pdf")


# ---------------------------------------------------------------------------
# 6. fig_drive_cycle.pdf -- tracking panel: v and alpha, ref vs both controllers
# ---------------------------------------------------------------------------
def fig_drive_cycle():
    d = load_csv("drive_cycle.csv")
    t = d["t_s"]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(4.4, 3.6), sharex=True)
    ax1.plot(t, d["v_ref"], color="#333333", ls=":", label="reference")
    ax1.plot(t, d["dec_v"], color=DEC_COLOR, label="Decentralized")
    ax1.plot(t, d["mimo_v"], color=MIMO_COLOR, label=r"MIMO $H_\infty$")
    ax1.set_ylabel(r"$v$ [m/s]")
    ax1.legend(loc="best", frameon=False, ncol=1)

    ax2.plot(t, d["alpha_ref"], color="#333333", ls=":")
    ax2.plot(t, d["dec_alpha"], color=DEC_COLOR)
    ax2.plot(t, d["mimo_alpha"], color=MIMO_COLOR)
    ax2.set_xlabel(r"$t$ [s]")
    ax2.set_ylabel(r"$\alpha$")

    save(fig, "fig_drive_cycle.pdf")


if __name__ == "__main__":
    fig_coupling_sigma()
    fig_sigma_S_both()
    fig_corner_scatter()
    fig_transient_small()
    fig_regen()
    fig_drive_cycle()
