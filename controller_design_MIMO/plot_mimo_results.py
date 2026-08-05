#!/usr/bin/env python
"""plot_mimo_results.py — thesis figures for the Phase-5 comparison.

Reads ONLY the CSVs written by compare_controllers.py (and the Phase-4 CSVs
already in figures/) and writes single-column SVG figures to figures/.

Run:  ctrl-venv/Scripts/python.exe plot_mimo_results.py
      (run compare_controllers.py first — this script does no analysis)

Style: matplotlib Agg only, no seaborn, no external style sheets; single-column
thesis width (3.4 in) or 1.5-column (5.0 in) for multi-panel figures; every axis
labelled with units; tight_layout everywhere.
"""

import os
import sys
import re

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
FIGDIR = os.path.join(HERE, "figures")

matplotlib.rcParams.update({
    "font.size": 8,
    "axes.titlesize": 8,
    "axes.labelsize": 8,
    "legend.fontsize": 7,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "grid.linewidth": 0.5,
    "lines.linewidth": 1.1,
    "figure.dpi": 110,
    "savefig.bbox": "tight",
    "svg.fonttype": "none",
})

W1, W15 = 3.4, 5.0          # inches: single column, 1.5 column

C_DEC = "#1f77b4"           # decentralized, native rates
C_D500 = "#7fb3d5"          # decentralized, 500 Hz share (rate-confound variant)
C_MIMO = "#d62728"          # centralized MIMO
C_REF = "#444444"

# motor-current clamp for the actuator-limit reference lines.  Parsed from the
# emitted header (never hard-coded) so a re-synthesis at a different clamp moves
# the dashed lines automatically -- 2026-08-04: +-5 A -> +-20 A.
with open(os.path.join(HERE, "drive_siso_coeffs.h"), encoding="utf-8") as _f:
    I_MOT_MAX = float(re.search(r"DRIVE_CTRL_I_MAX\s*=\s*([-\d.eE+]+)f",
                                _f.read()).group(1))

_WRITTEN = []


def load(name):
    path = os.path.join(FIGDIR, name)
    if not os.path.exists(path):
        print(f"  MISSING {name} — run compare_controllers.py first")
        return None
    rows = []
    with open(path, encoding="utf-8") as f:
        header = None
        for line in f:
            if line.startswith("#"):
                continue
            if header is None:
                header = [h.strip() for h in line.strip().split(",")]
                continue
            rows.append([float(x) for x in line.strip().split(",")])
    d = np.array(rows)
    return {h: d[:, i] for i, h in enumerate(header)}


def save(fig, name):
    path = os.path.join(FIGDIR, name)
    fig.savefig(path, format="svg")
    plt.close(fig)
    _WRITTEN.append(name)
    print(f"  wrote {name}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Plant coupling: sigma plot + coupling overlay
# ─────────────────────────────────────────────────────────────────────────────
d = load("coupling_freq.csv")
if d is not None:
    fig, ax = plt.subplots(2, 1, figsize=(W1, 4.2), sharex=True)
    cases = [("nominal", "#1f77b4", "nominal (2 A, r=0.5)"),
             ("light_load_0p5A", "#d62728", "light load (0.5 A)"),
             ("fc_cruise_r0p85", "#2ca02c", "FC cruise (r=0.85)")]
    ax[0].loglog(d["w_rad_s"], d["sigmax_nominal"], color="#1f77b4",
                 label=r"$\bar\sigma(G_s)$ nominal")
    ax[0].loglog(d["w_rad_s"], d["sigmin_nominal"], color="#1f77b4", ls="--",
                 label=r"$\underline{\sigma}(G_s)$ nominal")
    ax[0].loglog(d["w_rad_s"], d["sigmax_light_load_0p5A"], color="#d62728",
                 label=r"$\bar\sigma(G_s)$ 0.5 A")
    ax[0].loglog(d["w_rad_s"], d["sigmin_light_load_0p5A"], color="#d62728", ls="--",
                 label=r"$\underline{\sigma}(G_s)$ 0.5 A")
    ax[0].set_ylabel("singular value [-]")
    ax[0].set_title("Scaled 2×2 plant: singular values and coupling")
    ax[0].legend(loc="lower left", ncol=1, framealpha=0.9)
    for key, col, lbl in cases:
        ax[1].loglog(d["w_rad_s"], d[f"ratio12_{key}"], color=col, label=lbl)
    ax[1].axhline(1.0, color=C_REF, lw=0.7, ls=":")
    ax[1].set_xlabel("frequency [rad/s]")
    ax[1].set_ylabel(r"$|G_{s,12}| / |G_{s,11}|$ [-]")
    ax[1].legend(loc="lower left", framealpha=0.9)
    fig.tight_layout()
    save(fig, "fig_coupling_sigma.svg")

    fig, ax = plt.subplots(figsize=(W1, 2.3))
    for key, col, lbl in cases:
        ax.loglog(d["w_rad_s"], d[f"cond_{key}"], color=col, label=lbl)
    ax.axvline(200.0, color=C_REF, lw=0.7, ls=":")
    ax.text(210, ax.get_ylim()[0] * 3, "in-band limit", fontsize=6, color=C_REF)
    ax.set_xlabel("frequency [rad/s]")
    ax.set_ylabel(r"$\mathrm{cond}(G_s(j\omega))$ [-]")
    ax.set_title("Plant conditioning")
    ax.legend(loc="upper left", framealpha=0.9)
    fig.tight_layout()
    save(fig, "fig_coupling_cond.svg")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Coupling gain over the OP grid
# ─────────────────────────────────────────────────────────────────────────────
d = load("coupling_dalpha_dItot.csv")
if d is not None:
    fig, ax = plt.subplots(figsize=(W1, 2.4))
    m_ok = d["feasible"] > 0.5
    for dv, col, mk in ((+0.4, "#d62728", "o"), (-0.4, "#1f77b4", "s"),
                        (0.0, "#666666", "x")):
        s = m_ok & (np.abs(d["dV0_V"] - dv) < 1e-9)
        ax.scatter(d["I_tot0_A"][s], d["dalpha_dItot_per_A"][s], s=18, marker=mk,
                   color=col, label=rf"$\Delta V_0 = {dv:+.1f}$ V")
    ax.axhline(0.0, color=C_REF, lw=0.7)
    ax.set_xlabel(r"$I_{tot,0}$ [A]")
    ax.set_ylabel(r"$\partial\alpha/\partial I_{tot}$ [share/A]")
    ax.set_title("Static coupling gain (feasible OPs only)")
    ax.legend(framealpha=0.9)
    fig.tight_layout()
    save(fig, "fig_coupling_gain_grid.svg")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Sensitivity: both controllers, nominal + worst corner
# ─────────────────────────────────────────────────────────────────────────────
dn = load("sigma_nominal_both.csv")
dw = load("sigma_worst_corner_both.csv")
if dn is not None and dw is not None:
    fig, ax = plt.subplots(2, 1, figsize=(W1, 4.2), sharex=True)
    ax[0].loglog(dn["w_rad_s"], dn["dec_sigma_So"], color=C_DEC, label="decentralized")
    ax[0].loglog(dn["w_rad_s"], dn["mimo_sigma_So"], color=C_MIMO, label="MIMO")
    ax[0].axhline(1.0, color=C_REF, lw=0.7, ls=":")
    ax[0].set_ylabel(r"$\bar\sigma(S_o)$ [-]")
    ax[0].set_title("Output sensitivity — nominal plant")
    ax[0].legend(loc="lower right", framealpha=0.9)
    ax[1].loglog(dw["w_rad_s"], dw["dec_sigma_So"], color=C_DEC, label="decentralized")
    ax[1].loglog(dw["w_rad_s"], dw["mimo_sigma_So"], color=C_MIMO, label="MIMO")
    ax[1].axhline(1.0, color=C_REF, lw=0.7, ls=":")
    ax[1].set_xlabel("frequency [rad/s]")
    ax[1].set_ylabel(r"$\bar\sigma(S_o)$ [-]")
    ax[1].set_title("Worst in-envelope corner (MIMO)")
    ax[1].legend(loc="lower right", framealpha=0.9)
    fig.tight_layout()
    save(fig, "fig_sigma_S.svg")

    fig, ax = plt.subplots(3, 1, figsize=(W1, 5.4), sharex=True)
    ax[0].loglog(dn["w_rad_s"], dn["dec_S11"], color=C_DEC, label="decentralized")
    ax[0].loglog(dn["w_rad_s"], dn["mimo_S11"], color=C_MIMO, label="MIMO")
    ax[0].set_ylabel(r"$|S_{11}|$ [-]")
    ax[0].set_title("Per-channel sensitivity and cross-coupling (nominal)")
    ax[0].legend(loc="lower right", framealpha=0.9)
    ax[1].loglog(dn["w_rad_s"], dn["dec_S22"], color=C_DEC)
    ax[1].loglog(dn["w_rad_s"], dn["mimo_S22"], color=C_MIMO)
    ax[1].set_ylabel(r"$|S_{22}|$ [-]")
    ax[2].loglog(dn["w_rad_s"], np.maximum(dn["dec_T_alpha_vref"], 1e-12), color=C_DEC)
    ax[2].loglog(dn["w_rad_s"], np.maximum(dn["mimo_T_alpha_vref"], 1e-12), color=C_MIMO)
    ax[2].set_ylabel(r"$|T_{\alpha \leftarrow v_{ref}}|$ [share/(m/s)]")
    ax[2].set_xlabel("frequency [rad/s]")
    fig.tight_layout()
    save(fig, "fig_S_channels.svg")

# ─────────────────────────────────────────────────────────────────────────────
# 4. Corner scatter
# ─────────────────────────────────────────────────────────────────────────────
path = os.path.join(FIGDIR, "tier2_corner_scatter.csv")
if os.path.exists(path):
    labels, num = [], []
    with open(path, encoding="utf-8") as f:
        hdr = f.readline().strip().split(",")
        for line in f:
            p = line.strip().split(",")
            labels.append(p[0])
            num.append([float(x) for x in p[1:]])
    num = np.array(num)
    col = {h: i - 1 for i, h in enumerate(hdr)}
    labels = np.array(labels)
    dec = num[:, col["dec_sigma_So"]]
    mim = num[:, col["mimo_sigma_So"]]
    fig, ax = plt.subplots(figsize=(W1, 3.0))
    styles = [("in-envelope", "#1f77b4", "o"),
              ("FC-cruise", "#2ca02c", "^"),
              ("K-out-of-envelope", "#d62728", "s")]
    for lbl, c, mk in styles:
        s = labels == lbl
        if s.any():
            ax.scatter(dec[s], mim[s], s=14, marker=mk, color=c, alpha=0.75, label=lbl)
    lim = [0.9, max(np.nanmax(dec), np.nanmax(mim)) * 1.08]
    ax.plot(lim, lim, color=C_REF, lw=0.8, ls="--", label="parity")
    ax.set_xlim(lim); ax.set_ylim(lim)
    ax.set_xlabel(r"decentralized  $\|S_o\|_\infty$ [-]")
    ax.set_ylabel(r"MIMO  $\|S_o\|_\infty$ [-]")
    ax.set_title("Per-corner worst-case sensitivity")
    ax.legend(loc="upper left", framealpha=0.9)
    fig.tight_layout()
    save(fig, "fig_corner_scatter.svg")

# ─────────────────────────────────────────────────────────────────────────────
# 5. Drive-transient panels
# ─────────────────────────────────────────────────────────────────────────────
def transient_panel(csv, title, out):
    d = load(csv)
    if d is None:
        return
    fig, ax = plt.subplots(4, 1, figsize=(W15, 6.4), sharex=True)
    ax[0].plot(d["t_s"], d["v_ref"], color=C_REF, ls=":", label="reference")
    for pre, c, lbl in (("dec", C_DEC, "decentralized (1 kHz share)"),
                        ("dec500", C_D500, "decentralized (500 Hz share)"),
                        ("mimo", C_MIMO, "MIMO (500 Hz)")):
        ax[0].plot(d["t_s"], d[f"{pre}_v"], color=c, label=lbl)
        ax[1].plot(d["t_s"], d[f"{pre}_alpha"], color=c)
        ax[2].plot(d["t_s"], d[f"{pre}_i"], color=c)
        ax[3].plot(d["t_s"], d[f"{pre}_r"], color=c)
    ax[0].set_ylabel(r"$\Delta v$ [m/s]")
    ax[0].set_title(title)
    ax[0].legend(loc="lower right", framealpha=0.9)
    ax[1].set_ylabel(r"$\Delta\alpha$ [-]")
    ax[2].set_ylabel(r"$i_{cmd}$ [A]")
    ax[2].axhline(I_MOT_MAX, color=C_REF, lw=0.7, ls="--")
    ax[2].axhline(-I_MOT_MAX, color=C_REF, lw=0.7, ls="--")
    ax[3].set_ylabel(r"$r$ [-]")
    ax[3].axhline(0.85, color=C_REF, lw=0.7, ls="--")
    ax[3].axhline(0.15, color=C_REF, lw=0.7, ls="--")
    ax[3].set_xlabel("time [s]")
    fig.tight_layout()
    save(fig, out)


transient_panel("transient_small_dV0p.csv",
                r"Drive transient, $\Delta v_{ref} = +0.05$ m/s, $\Delta V_0 = +0.4$ V",
                "fig_transient_small_dV0p.svg")
transient_panel("transient_small_dV0m.csv",
                r"Drive transient, $\Delta v_{ref} = +0.05$ m/s, $\Delta V_0 = -0.4$ V",
                "fig_transient_small_dV0m.svg")
transient_panel("transient_large_dV0p.csv",
                r"Drive transient, $\Delta v_{ref} = +2$ m/s (actuator-limited), "
                r"$\Delta V_0 = +0.4$ V", "fig_transient_large_dV0p.svg")
transient_panel("transient_large_dV0m.csv",
                r"Drive transient, $\Delta v_{ref} = +2$ m/s (actuator-limited), "
                r"$\Delta V_0 = -0.4$ V", "fig_transient_large_dV0m.svg")

# ─────────────────────────────────────────────────────────────────────────────
# 6. Regen panel (with v_bus)
# ─────────────────────────────────────────────────────────────────────────────
d = load("regen_truth.csv")
if d is not None:
    fig, ax = plt.subplots(4, 1, figsize=(W15, 6.4), sharex=True)
    ax[0].plot(d["t_s"], d["v_ref"], color=C_REF, ls=":", label="reference")
    for pre, c, lbl in (("dec", C_DEC, "decentralized (1 kHz share)"),
                        ("dec500", C_D500, "decentralized (500 Hz share)"),
                        ("mimo", C_MIMO, "MIMO (500 Hz)")):
        ax[0].plot(d["t_s"], d[f"{pre}_v"], color=c, label=lbl)
        ax[1].plot(d["t_s"], d[f"{pre}_alpha"], color=c)
        ax[2].plot(d["t_s"], d[f"{pre}_i"], color=c)
        ax[3].plot(d["t_s"], d[f"{pre}_vbus"], color=c)
    ax[0].set_ylabel(r"$\Delta v$ [m/s]")
    ax[0].set_title("Regen event on the 15-state truth model: 2 m/s → standstill")
    ax[0].legend(loc="upper right", framealpha=0.9)
    ax[1].set_ylabel(r"$\Delta\alpha$ [-]")
    ax[2].set_ylabel(r"$i_{cmd}$ [A]")
    ax[2].axhline(-I_MOT_MAX, color=C_REF, lw=0.7, ls="--")
    ax[3].set_ylabel(r"$\Delta v_{bus}$ [V]")
    ax[3].set_xlabel("time [s]")
    for a in ax:
        a.set_xlim(0, 6.0)
    fig.tight_layout()
    save(fig, "fig_regen_bus.svg")

# ─────────────────────────────────────────────────────────────────────────────
# 7. FC-charge cruise
# ─────────────────────────────────────────────────────────────────────────────
d = load("fccruise.csv")
if d is not None:
    fig, ax = plt.subplots(3, 1, figsize=(W15, 5.0), sharex=True)
    for pre, c, lbl in (("dec", C_DEC, "decentralized (1 kHz share)"),
                        ("dec500", C_D500, "decentralized (500 Hz share)"),
                        ("mimo", C_MIMO, "MIMO (500 Hz)")):
        ax[0].plot(d["t_s"], d[f"{pre}_v"], color=c, label=lbl)
        ax[1].plot(d["t_s"], d[f"{pre}_alpha"], color=c)
        ax[2].plot(d["t_s"], d[f"{pre}_r"], color=c)
    ax[0].plot(d["t_s"], d["v_ref"], color=C_REF, ls=":", label="reference")
    ax[0].set_ylabel(r"$\Delta v$ [m/s]")
    ax[0].set_title(r"FC-charge cruise ($r_0 = 0.85$, no upward droop authority)")
    ax[0].legend(loc="lower right", framealpha=0.9)
    ax[1].set_ylabel(r"$\Delta\alpha$ [-]")
    ax[2].set_ylabel(r"$r$ [-]")
    ax[2].axhline(0.85, color=C_REF, lw=0.7, ls="--")
    ax[2].set_xlabel("time [s]")
    for a in ax:
        a.set_xlim(0, 6.0)
    fig.tight_layout()
    save(fig, "fig_fccruise.svg")

# ─────────────────────────────────────────────────────────────────────────────
# 8. Drive cycle
# ─────────────────────────────────────────────────────────────────────────────
d = load("drive_cycle.csv")
if d is not None:
    fig, ax = plt.subplots(4, 1, figsize=(W15, 6.6), sharex=True)
    ax[0].plot(d["t_s"], d["v_ref"], color=C_REF, ls=":", label="reference")
    for pre, c, lbl in (("dec", C_DEC, "decentralized (1 kHz share)"),
                        ("dec500", C_D500, "decentralized (500 Hz share)"),
                        ("mimo", C_MIMO, "MIMO (500 Hz)")):
        ax[0].plot(d["t_s"], d[f"{pre}_v"], color=c, label=lbl)
        ax[1].plot(d["t_s"], d[f"{pre}_alpha"] - d["alpha_ref"], color=c)
        ax[2].plot(d["t_s"], d[f"{pre}_i"], color=c)
        ax[3].plot(d["t_s"], d[f"{pre}_r"], color=c)
    ax[0].set_ylabel(r"$\Delta v$ [m/s]")
    ax[0].set_title("30 s drive cycle (ramp / cruise / coast / hold), share steps "
                    "at 11–15 s, −1 A load step at 22–25 s")
    ax[0].legend(loc="lower left", framealpha=0.9, ncol=2)
    ax[1].set_ylabel("share error [-]")
    ax[2].set_ylabel(r"$i_{cmd}$ [A]")
    ax[2].axhline(I_MOT_MAX, color=C_REF, lw=0.7, ls="--")
    ax[2].axhline(-I_MOT_MAX, color=C_REF, lw=0.7, ls="--")
    ax[3].set_ylabel(r"$r$ [-]")
    ax[3].set_xlabel("time [s]")
    fig.tight_layout()
    save(fig, "fig_drive_cycle.svg")

print(f"\n{len(_WRITTEN)} figures written to figures/")
if not _WRITTEN:
    sys.exit(1)
