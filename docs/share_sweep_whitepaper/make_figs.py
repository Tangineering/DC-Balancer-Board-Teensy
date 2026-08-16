"""Generate the zoomed / summary figures for the 2026-08-11 share-setpoint sweep
whitepaper (docs/share_sweep_whitepaper/main.tex).

Run from the repo root:
    .venv_benchlog/Scripts/python.exe docs/share_sweep_whitepaper/make_figs.py

Reads logs/<RUN>/<RUN>.csv (decoded by tools/benchlog_analysis) and writes PNGs
into docs/share_sweep_whitepaper/figs/.  Colors match tools/benchlog_analysis/
figures.py so the whitepaper's new figures read as one family with the
pipeline-generated ones.
"""
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "logs"
FIGS = Path(__file__).resolve().parent / "figs"
FIGS.mkdir(exist_ok=True)

# Palette: mirrors tools/benchlog_analysis/figures.py COLORS
C_IFC = "#1baf7a"
C_IBT = "#4a3aa7"
C_SHR = "#eb6834"
C_VBUS = "#e34948"
C_TEXT = "#222222"
GRID = dict(color="#cccccc", linewidth=0.6, alpha=0.7)

SWEEP = [  # run, share_sp, session order
    ("TP0007", 0.50), ("TP0008", 0.70), ("TP0009", 1.00), ("TP0010", 0.30),
    ("TP0011", 0.00), ("TP0012", 0.15), ("TP0013", 0.85),
]


def load(run):
    d = np.genfromtxt(LOGS / run / f"{run}.csv", delimiter=",", names=True)
    t = (d["t_us"] - d["t_us"][0]) / 1e6
    return t, d


def ema(t, x, tau):
    y = np.empty_like(x)
    y[0] = x[0]
    for i in range(1, len(x)):
        a = min(1.0, (t[i] - t[i - 1]) / tau)
        y[i] = y[i - 1] + a * (x[i] - y[i - 1])
    return y


def style(ax, ylabel=None):
    ax.grid(True, which="major", **GRID)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=C_TEXT, labelsize=9)
    if ylabel:
        ax.set_ylabel(ylabel, color=C_TEXT, fontsize=10)


def legend(ax, **kw):
    lg = ax.legend(fontsize=8, framealpha=0.9, edgecolor="#cccccc", **kw)
    for txt in lg.get_texts():
        txt.set_color(C_TEXT)


# ---------------------------------------------------------------- TP0010 zooms
def tp0010_zoom():
    t, d = load("TP0010")
    for name, (t0, t1), raw_only in (
        ("fig_tp0010_window", (3.8, 6.6), False),
        ("fig_tp0010_cycle", (5.70, 6.00), True),
    ):
        m = (t >= t0) & (t <= t1)
        fig, (a0, a1, a2) = plt.subplots(
            3, 1, figsize=(8.5, 7.2), sharex=True,
            gridspec_kw=dict(height_ratios=[1.2, 1, 1]))
        lw = 0.9 if raw_only else 0.5
        al = 1.0 if raw_only else 0.45
        a0.plot(t[m], d["I_fc"][m], color=C_IFC, lw=lw, alpha=al,
                label="I_fc (meas)")
        a0.plot(t[m], d["I_batt"][m], color=C_IBT, lw=lw, alpha=al,
                label="I_batt (meas)")
        if not raw_only:
            a0.plot(t[m], ema(t, d["I_fc"], 0.010)[m], color=C_IFC, lw=1.6,
                    label="I_fc (filt, 10 ms)")
            a0.plot(t[m], ema(t, d["I_batt"], 0.010)[m], color=C_IBT, lw=1.6,
                    label="I_batt (filt, 10 ms)")
        style(a0, "Channel current [A]")
        legend(a0, ncol=2, loc="upper left")

        a1.plot(t[m], d["V_bus"][m], color=C_VBUS, lw=0.9, label="V_bus")
        a1.axhline(15.0, color="#8a8a8a", lw=0.8, ls="--",
                   label="15 V excursion threshold")
        style(a1, "Bus voltage [V]")
        legend(a1, loc="lower left")

        a2.plot(t[m], d["gFC"][m], color=C_IFC, lw=1.1, label="gFC")
        a2.plot(t[m], d["gBT"][m], color=C_IBT, lw=1.1, label="gBT")
        style(a2, "Droop gain cmd [-]")
        a2.set_xlabel("Time [s]", color=C_TEXT, fontsize=10)
        a2.set_ylim(0, 1.05)
        legend(a2, loc="upper left", ncol=2)

        fig.align_ylabels()
        fig.tight_layout()
        fig.savefig(FIGS / f"{name}.png", dpi=150)
        plt.close(fig)
        print(FIGS / f"{name}.png")


# ---------------------------------------------------------------- TP0013 zoom
def tp0013_zoom():
    t, d = load("TP0013")
    t0, t1 = 3.8, 5.8
    m = (t >= t0) & (t <= t1)
    fig, (a0, a1, a2) = plt.subplots(
        3, 1, figsize=(8.5, 7.2), sharex=True,
        gridspec_kw=dict(height_ratios=[1.2, 1, 1]))
    a0.plot(t[m], d["I_fc"][m], color=C_IFC, lw=0.6, alpha=0.8,
            label="I_fc (meas)")
    a0.plot(t[m], d["I_batt"][m], color=C_IBT, lw=0.6, alpha=0.8,
            label="I_batt (meas)")
    style(a0, "Channel current [A]")
    legend(a0, ncol=2, loc="upper left")

    a1.plot(t[m], d["share_act"][m], color=C_SHR, lw=0.5, alpha=0.45,
            label="share (meas)")
    a1.plot(t[m], ema(t, d["share_act"], 0.020)[m], color="#a03d13", lw=1.4,
            label="share (filt, 20 ms)")
    a1.axhline(0.85, color=C_SHR, lw=1.0, ls="--", label="share ref = 0.85")
    style(a1, "Power share [FC frac]")
    a1.set_ylim(-0.05, 1.08)
    legend(a1, loc="lower right", ncol=3)

    a2.plot(t[m], d["gFC"][m], color=C_IFC, lw=1.1, label="gFC")
    a2.plot(t[m], d["gBT"][m], color=C_IBT, lw=1.1, label="gBT")
    style(a2, "Droop gain cmd [-]")
    a2.set_xlabel("Time [s]", color=C_TEXT, fontsize=10)
    a2.set_ylim(0, 1.05)
    legend(a2, loc="center left", ncol=2)

    fig.align_ylabels()
    fig.tight_layout()
    fig.savefig(FIGS / "fig_tp0013_dropout.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_tp0013_dropout.png")


# ------------------------------------------------------- sweep summary + drift
def hold_metrics():
    rows = []
    for order, (run, sp) in enumerate(SWEEP, start=1):
        t, d = load(run)
        hold = d["trap_phase"] == 1
        err = d["share_act"][hold] - sp
        itot = d["I_fc"] + d["I_batt"]

        # settling: first time |filtered err| < 0.05 sustained >= 0.2 s after
        # load onset (itot filt > 0.15 A)
        sf = ema(t, d["share_act"], 0.020)
        itf = ema(t, itot, 0.020)
        onset_i = np.argmax(itf > 0.15)
        settle = np.nan
        if itf[onset_i] > 0.15:
            ok = np.abs(sf - sp) < 0.05
            ok[:onset_i] = False
            # sustained 0.2 s ~ 174 samples at 1.15 ms
            n = int(0.2 / np.median(np.diff(t)))
            c = np.convolve(ok.astype(int), np.ones(n, int), "valid")
            j = np.argmax(c >= n)
            if c[j] >= n:
                settle = t[j] - t[onset_i]
        rows.append(dict(run=run, sp=sp, order=order,
                         err_mean=float(np.mean(err)),
                         err_std=float(np.std(err)),
                         itot_hold=float(np.mean(itot[hold])),
                         settle=settle))
    return rows


def sweep_summary(rows):
    rows_sp = sorted(rows, key=lambda r: r["sp"])
    sp = [r["sp"] for r in rows_sp]
    fig, (a0, a1) = plt.subplots(1, 2, figsize=(9.5, 3.6))

    a0.errorbar(sp, [r["err_mean"] for r in rows_sp],
                yerr=[r["err_std"] for r in rows_sp],
                fmt="o", color=C_SHR, ecolor="#e8a583", elinewidth=2,
                capsize=4, ms=6, label="hold-window mean err ± 1σ")
    a0.axhline(0, color="#8a8a8a", lw=0.8)
    style(a0, "Share error [-]")
    a0.set_xlabel("Share setpoint", color=C_TEXT, fontsize=10)
    a0.set_title("Steady-state (6 A hold) tracking error", color=C_TEXT,
                 fontsize=10)
    for r in rows_sp:
        if r["run"] == "TP0013":
            a0.annotate("TP0013: σ inflated by\nI_batt ADC quantization",
                        xy=(r["sp"], -r["err_std"]), xytext=(0.30, -0.095),
                        fontsize=8, color=C_TEXT,
                        arrowprops=dict(arrowstyle="->", color="#8a8a8a"))
    legend(a0, loc="lower left")

    a1.plot([r["sp"] for r in rows_sp], [r["settle"] for r in rows_sp],
            "o", color=C_SHR, ms=6)
    for r in rows_sp:
        if np.isnan(r["settle"]):
            a1.plot(r["sp"], 0.05, "x", color=C_VBUS, ms=9, mew=2)
            a1.annotate(f"{r['run']}: never settles",
                        xy=(r["sp"], 0.05), xytext=(r["sp"] - 0.42, 0.4),
                        fontsize=8, color=C_TEXT,
                        arrowprops=dict(arrowstyle="->", color="#8a8a8a"))
        if r["run"] == "TP0010":
            a1.annotate("TP0010: settles only after\nthe limit cycle self-clears",
                        xy=(r["sp"], r["settle"]), xytext=(0.02, 2.6),
                        fontsize=8, color=C_TEXT,
                        arrowprops=dict(arrowstyle="->", color="#8a8a8a"))
    style(a1, "Settle time after load onset [s]")
    a1.set_xlabel("Share setpoint", color=C_TEXT, fontsize=10)
    a1.set_title("Settling (|err| < 0.05 sustained 0.2 s)", color=C_TEXT,
                 fontsize=10)

    fig.tight_layout()
    fig.savefig(FIGS / "fig_sweep_summary.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_sweep_summary.png")


def run_order(rows):
    rows_o = sorted(rows, key=lambda r: r["order"])
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    ax.plot([r["order"] for r in rows_o], [r["itot_hold"] for r in rows_o],
            "o-", color="#e87ba4", lw=1.4, ms=6)
    for r in rows_o:
        ax.annotate(f"{r['run'][2:]}\nsp={r['sp']:g}",
                    xy=(r["order"], r["itot_hold"]),
                    xytext=(0, 8), textcoords="offset points",
                    ha="center", fontsize=7.5, color=C_TEXT)
    style(ax, "Mean bus current during 6 A hold [A]")
    ax.set_xlabel("Session run order", color=C_TEXT, fontsize=10)
    ax.set_ylim(bottom=1.0)
    ax.margins(y=0.22)
    fig.tight_layout()
    fig.savefig(FIGS / "fig_run_order.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_run_order.png")


# ===================================================================
# Part II: fw v3 fix-validation sweep (TP0014-TP0038, WP0039/WP0040)
# ===================================================================

VAL_SWEEP = [  # run, share_sp (session order == numeric order)
    ("TP0014", 0.00), ("TP0015", 0.12), ("TP0016", 0.15), ("TP0017", 0.18),
    ("TP0018", 0.20), ("TP0019", 0.225), ("TP0020", 0.25), ("TP0021", 0.30),
    ("TP0022", 0.35), ("TP0023", 0.40), ("TP0024", 0.45), ("TP0025", 0.50),
    ("TP0026", 0.55), ("TP0027", 0.60), ("TP0028", 0.65), ("TP0029", 0.70),
    ("TP0030", 0.725), ("TP0031", 0.75), ("TP0032", 0.775), ("TP0033", 0.80),
    ("TP0034", 0.82), ("TP0035", 0.84), ("TP0036", 0.85), ("TP0037", 0.87),
    ("TP0038", 1.00),
]


def val_metrics():
    rows = []
    for run, sp in VAL_SWEEP:
        t, d = load(run)
        itot = d["I_fc"] + d["I_batt"]
        hold = d["I_cmd"] >= 5.99
        err = d["share_act"][hold] - sp
        # Hysteretic dropout-event count: a dropout (minority < 0.02 A while
        # total > 0.3 A) counts only when followed by genuine re-conduction
        # (minority > 0.05 A), so ADC-noise fragmentation of a continuous
        # clean cutoff (TP0014/TP0038) does not register as switching.
        minority = np.minimum(d["I_fc"], d["I_batt"])
        events = 0
        state = "on"
        for mi, ti in zip(minority, itot):
            if state == "on" and mi < 0.02 and ti > 0.3:
                state = "off"
            elif state == "off" and mi > 0.05:
                state = "on"
                events += 1
        rows.append(dict(run=run, sp=sp,
                         err_mean=float(np.mean(err)),
                         err_std=float(np.std(err)),
                         events=events,
                         vmin=float(np.min(d["V_bus"]))))
    return rows


def val_sweep_summary(rows):
    sp = [r["sp"] for r in rows]
    fig, (a0, a1, a2) = plt.subplots(1, 3, figsize=(11.5, 3.5))

    a0.errorbar(sp, [r["err_mean"] for r in rows],
                yerr=[r["err_std"] for r in rows],
                fmt="o", color=C_SHR, ecolor="#e8a583", elinewidth=2,
                capsize=3, ms=5, label="hold-window mean err ± 1σ")
    a0.axhline(0, color="#8a8a8a", lw=0.8)
    style(a0, "Share error [-]")
    a0.set_xlabel("Share setpoint", color=C_TEXT, fontsize=10)
    a0.set_title("Steady-state (6 A hold) tracking error", color=C_TEXT,
                 fontsize=10)
    for r in rows:
        if r["run"] in ("TP0016", "TP0037", "TP0015"):
            a0.annotate(r["run"][2:], xy=(r["sp"], r["err_std"]),
                        xytext=(0, 5), textcoords="offset points",
                        ha="center", fontsize=7.5, color=C_TEXT)
    legend(a0, loc="lower left")

    a1.plot(sp, [r["events"] for r in rows], "o", color=C_SHR, ms=5)
    for r in rows:
        if r["events"] > 10:
            a1.annotate(f"{r['run'][2:]}", xy=(r["sp"], r["events"]),
                        xytext=(0, 6), textcoords="offset points",
                        ha="center", fontsize=7.5, color=C_TEXT)
    style(a1, "Minority-dropout events [-]")
    a1.set_xlabel("Share setpoint", color=C_TEXT, fontsize=10)
    a1.set_title("Dropout events per run", color=C_TEXT, fontsize=10)

    a2.plot(sp, [r["vmin"] for r in rows], "o", color=C_VBUS, ms=5)
    a2.axhline(15.9, color="#8a8a8a", lw=0.8, ls="--", label="no-load bus")
    style(a2, "Run-minimum bus voltage [V]")
    a2.set_xlabel("Share setpoint", color=C_TEXT, fontsize=10)
    a2.set_title("Bus collapse census", color=C_TEXT, fontsize=10)
    for r in rows:
        if r["vmin"] < 15.0:
            a2.annotate(f"{r['run'][2:]}: {r['vmin']:.1f} V",
                        xy=(r["sp"], r["vmin"]), xytext=(6, 4),
                        textcoords="offset points", fontsize=7.5, color=C_TEXT)
    legend(a2, loc="lower right")

    fig.tight_layout()
    fig.savefig(FIGS / "fig_valsweep_summary.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_valsweep_summary.png")


def tp0016_zoom():
    t, d = load("TP0016")
    m = (t >= 10.8) & (t <= 13.6)
    fig, (a0, a1, a2) = plt.subplots(
        3, 1, figsize=(8.5, 7.2), sharex=True,
        gridspec_kw=dict(height_ratios=[1.2, 1, 1]))
    a0.plot(t[m], d["I_fc"][m], color=C_IFC, lw=0.6, alpha=0.9,
            label="I_fc (meas)")
    a0.plot(t[m], d["I_batt"][m], color=C_IBT, lw=0.6, alpha=0.9,
            label="I_batt (meas)")
    style(a0, "Channel current [A]")
    legend(a0, ncol=2, loc="upper right")

    a1.plot(t[m], d["V_bus"][m], color=C_VBUS, lw=0.9, label="V_bus")
    a1.axhline(15.0, color="#8a8a8a", lw=0.8, ls="--",
               label="15 V excursion threshold")
    style(a1, "Bus voltage [V]")
    legend(a1, loc="lower left")

    a2.plot(t[m], d["gFC"][m], color=C_IFC, lw=1.1, label="gFC")
    a2.plot(t[m], d["gBT"][m], color=C_IBT, lw=1.1, label="gBT")
    style(a2, "Droop gain cmd [-]")
    a2.set_xlabel("Time [s]", color=C_TEXT, fontsize=10)
    a2.set_ylim(0, 1.05)
    legend(a2, loc="center right", ncol=2)

    fig.align_ylabels()
    fig.tight_layout()
    fig.savefig(FIGS / "fig_tp0016_window.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_tp0016_window.png")


def tp0037_gap():
    t, d = load("TP0037")
    m = (t >= 6.2) & (t <= 7.2)
    r_cmd = np.where(d["gFC"] + d["gBT"] > 0,
                     d["gBT"] / np.maximum(d["gFC"] + d["gBT"], 1e-9), np.nan)
    fig, (a0, a1, a2) = plt.subplots(
        3, 1, figsize=(8.5, 7.2), sharex=True,
        gridspec_kw=dict(height_ratios=[1.2, 1, 1]))
    a0.plot(t[m], d["I_fc"][m], color=C_IFC, lw=0.8, label="I_fc (meas)")
    a0.plot(t[m], d["I_batt"][m], color=C_IBT, lw=0.8, label="I_batt (meas)")
    style(a0, "Channel current [A]")
    legend(a0, ncol=2, loc="upper right")

    a1.plot(t[m], d["share_act"][m], color=C_SHR, lw=0.6, alpha=0.6,
            label="share (meas)")
    a1.plot(t[m], ema(t, d["share_act"], 0.020)[m], color="#a03d13", lw=1.4,
            label="share (filt, 20 ms)")
    a1.axhline(0.87, color=C_SHR, lw=1.0, ls="--", label="share ref = 0.87")
    style(a1, "Power share [FC frac]")
    a1.set_ylim(0.3, 1.08)
    legend(a1, loc="lower right", ncol=3)

    a2.plot(t[m], r_cmd[m], color="#7a5cc4", lw=1.1,
            label="commanded droop ratio r")
    a2.axhline(0.85, color="#8a8a8a", lw=0.9, ls="--",
               label="DROOP_R_MAX = 0.85 (cutoff threshold)")
    style(a2, "Droop ratio [-]")
    a2.set_xlabel("Time [s]", color=C_TEXT, fontsize=10)
    a2.set_ylim(0.35, 0.95)
    legend(a2, loc="lower right")

    fig.align_ylabels()
    fig.tight_layout()
    fig.savefig(FIGS / "fig_tp0037_gap.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_tp0037_gap.png")


def wp0039_ratchet():
    t, d = load("WP0039")
    m = t >= 11.4
    fig, (a0, a1) = plt.subplots(
        2, 1, figsize=(8.5, 5.4), sharex=True,
        gridspec_kw=dict(height_ratios=[1, 1.1]))
    a0.plot(t[m], d["I_fc"][m], color=C_IFC, lw=0.6, alpha=0.9,
            label="I_fc (meas)")
    a0.plot(t[m], d["I_batt"][m], color=C_IBT, lw=0.6, alpha=0.9,
            label="I_batt (meas)")
    style(a0, "Channel current [A]")
    legend(a0, ncol=2, loc="upper left")

    a1.plot(t[m], d["V_bus"][m], color=C_VBUS, lw=0.8, label="V_bus")
    a1.axhline(14.0, color="#8a8a8a", lw=0.8, ls="--",
               label="14 V sag threshold")
    style(a1, "Bus voltage [V]")
    a1.set_xlabel("Time [s]", color=C_TEXT, fontsize=10)
    legend(a1, loc="lower left")

    fig.align_ylabels()
    fig.tight_layout()
    fig.savefig(FIGS / "fig_wp0039_ratchet.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_wp0039_ratchet.png")


def wp0040_governor():
    t, d = load("WP0040")
    itot = d["I_fc"] + d["I_batt"]
    # Reconstruct the firmware governor law: per-tick EMA (alpha = 0.05) on
    # total current; clip in-band setpoints to [lo, 1-lo] with
    # lo = 0.20/filt when filt > 0.40 A, else collapse to 0.5.
    filt = np.empty_like(itot)
    filt[0] = 0.0
    for i in range(1, len(itot)):
        filt[i] = filt[i - 1] + 0.05 * (itot[i] - filt[i - 1])
    lo = np.where(filt > 0.40, 0.20 / np.maximum(filt, 1e-6), 0.5)
    sp_eff = np.clip(d["share_sp"], lo, 1.0 - lo)
    live = filt > 0.15  # share ratio numerically meaningless below this

    fig, (a0, a1) = plt.subplots(
        2, 1, figsize=(8.5, 5.6), sharex=True,
        gridspec_kw=dict(height_ratios=[1.4, 1]))
    a0.plot(t, d["share_sp"], color="#8a8a8a", lw=1.0, ls="--",
            label="table setpoint r*")
    a0.plot(t[live], sp_eff[live], color="#c98a1b", lw=1.5,
            label="governed setpoint (reconstructed)")
    sf = ema(t, d["share_act"], 0.020)
    a0.plot(t[live], sf[live], color=C_SHR, lw=0.9,
            label="share (meas, filt 20 ms)")
    style(a0, "Power share [FC frac]")
    a0.set_ylim(0.2, 0.8)
    legend(a0, loc="upper left", ncol=3)

    a1.plot(t, itot, color="#555555", lw=0.6, alpha=0.6, label="I_tot (meas)")
    a1.plot(t, filt, color="#111111", lw=1.3, label="I_tot (governor filter)")
    a1.axhline(0.40, color="#8a8a8a", lw=0.8, ls="--",
               label="collapse threshold 0.40 A")
    style(a1, "Total current [A]")
    a1.set_xlabel("Time [s]", color=C_TEXT, fontsize=10)
    legend(a1, loc="upper left", ncol=2)

    fig.align_ylabels()
    fig.tight_layout()
    fig.savefig(FIGS / "fig_wp0040_governor.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_wp0040_governor.png")


# ------------------------------------------------- fw v4 sweep (TP0041-TP0068)
V4_SWEEP = [  # run, share_sp (NOT session order: 0054-0057, 0059-0060 are
    # single-run reboots after faults; see start_millis in decode_report.txt)
    ("TP0041", 0.00), ("TP0042", 0.05), ("TP0043", 0.10), ("TP0044", 0.12),
    ("TP0045", 0.15), ("TP0046", 0.17), ("TP0047", 0.20), ("TP0048", 0.25),
    ("TP0049", 0.30), ("TP0050", 0.40), ("TP0051", 0.50), ("TP0052", 0.60),
    ("TP0053", 0.70), ("TP0054", 0.68), ("TP0055", 0.67), ("TP0056", 0.72),
    ("TP0057", 0.73), ("TP0058", 0.75), ("TP0059", 0.80), ("TP0060", 0.77),
    ("TP0061", 0.78), ("TP0062", 0.79), ("TP0063", 0.81), ("TP0064", 0.83),
    ("TP0065", 0.85), ("TP0066", 0.88), ("TP0067", 0.90), ("TP0068", 1.00),
]
V4_FAULTED = {"TP0053", "TP0054", "TP0055", "TP0056", "TP0057", "TP0059"}
V4_LATCHED = {"TP0041", "TP0042", "TP0043", "TP0044",
              "TP0066", "TP0067", "TP0068"}


def r_cmd(d):
    tot = d["gFC"] + d["gBT"]
    return np.where(tot > 1e-9, d["gBT"] / np.maximum(tot, 1e-9), np.nan)


def v4_metrics():
    rows = []
    for run, sp in V4_SWEEP:
        t, d = load(run)
        itot = d["I_fc"] + d["I_batt"]
        hold = d["I_cmd"] >= 5.99
        err = d["share_act"][hold] - sp if hold.any() else np.array([np.nan])
        minority = np.minimum(d["I_fc"], d["I_batt"])
        events = 0
        state = "on"
        for mi, ti in zip(minority, itot):
            if state == "on" and mi < 0.02 and ti > 0.3:
                state = "off"
            elif state == "off" and mi > 0.05:
                state = "on"
                events += 1
        rows.append(dict(run=run, sp=sp,
                         err_mean=float(np.nanmean(err)),
                         err_std=float(np.nanstd(err)),
                         events=events,
                         vmin=float(np.min(d["V_bus"])),
                         faulted=run in V4_FAULTED,
                         latched=run in V4_LATCHED))
    return rows


def v4_sweep_summary(rows):
    fig, (a0, a1, a2) = plt.subplots(1, 3, figsize=(11.5, 3.5))

    gov = [r for r in rows if not r["faulted"] and not r["latched"]]
    a0.errorbar([r["sp"] for r in gov], [r["err_mean"] for r in gov],
                yerr=[r["err_std"] for r in gov],
                fmt="o", color=C_SHR, ecolor="#e8a583", elinewidth=2,
                capsize=3, ms=5, label="hold mean err ± 1σ (governed runs)")
    a0.axhline(0, color="#8a8a8a", lw=0.8)
    style(a0, "Share error [-]")
    a0.set_xlabel("Share setpoint", color=C_TEXT, fontsize=10)
    a0.set_title("Steady-state (6 A hold) tracking error", color=C_TEXT,
                 fontsize=10)
    legend(a0, loc="lower left")

    a1.plot([r["sp"] for r in rows if not r["faulted"]],
            [r["events"] for r in rows if not r["faulted"]],
            "o", color=C_SHR, ms=5, label="completed")
    a1.plot([r["sp"] for r in rows if r["faulted"]],
            [r["events"] for r in rows if r["faulted"]],
            "x", color=C_VBUS, ms=8, mew=2, label="faulted (ERR_UV_BUS)")
    for r in rows:
        if r["events"] > 3:
            a1.annotate(r["run"][2:], xy=(r["sp"], r["events"]),
                        xytext=(0, 6), textcoords="offset points",
                        ha="center", fontsize=7.5, color=C_TEXT)
    style(a1, "Dropout events [-]")
    a1.set_xlabel("Share setpoint", color=C_TEXT, fontsize=10)
    a1.set_title("Hysteretic dropout events per run", color=C_TEXT,
                 fontsize=10)
    legend(a1, loc="upper left")

    a2.plot([r["sp"] for r in rows if not r["faulted"]],
            [r["vmin"] for r in rows if not r["faulted"]],
            "o", color=C_VBUS, ms=5, label="completed")
    a2.plot([r["sp"] for r in rows if r["faulted"]],
            [r["vmin"] for r in rows if r["faulted"]],
            "x", color=C_VBUS, ms=8, mew=2, label="faulted")
    a2.axhline(15.9, color="#8a8a8a", lw=0.8, ls="--", label="no-load bus")
    a2.axhline(12.0, color=C_VBUS, lw=0.8, ls=":", label="UV limit 12.0 V")
    style(a2, "Run-minimum bus voltage [V]")
    a2.set_xlabel("Share setpoint", color=C_TEXT, fontsize=10)
    a2.set_title("Bus collapse census", color=C_TEXT, fontsize=10)
    for r in rows:
        if r["run"] == "TP0060":
            a2.annotate("0060: 12.9 V", xy=(r["sp"], r["vmin"]),
                        xytext=(6, 4), textcoords="offset points",
                        fontsize=7.5, color=C_TEXT)
    legend(a2, loc="lower left")

    fig.tight_layout()
    fig.savefig(FIGS / "fig_v4sweep_summary.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_v4sweep_summary.png")


def tp0053_relay():
    t, d = load("TP0053")
    m = (t >= 3.4) & (t <= 5.3)
    fig, (a0, a1, a2) = plt.subplots(
        3, 1, figsize=(8.5, 7.2), sharex=True,
        gridspec_kw=dict(height_ratios=[1.2, 1, 1]))
    a0.plot(t[m], d["I_fc"][m], color=C_IFC, lw=0.7, label="I_fc (meas)")
    a0.plot(t[m], d["I_batt"][m], color=C_IBT, lw=0.7, label="I_batt (meas)")
    style(a0, "Channel current [A]")
    legend(a0, ncol=2, loc="upper left")

    a1.plot(t[m], d["V_bus"][m], color=C_VBUS, lw=0.9, label="V_bus")
    a1.axhline(12.0, color=C_VBUS, lw=0.8, ls=":", label="UV limit 12.0 V")
    style(a1, "Bus voltage [V]")
    legend(a1, loc="lower left")

    a2.plot(t[m], r_cmd(d)[m], color="#c98a1b", lw=1.1,
            label="r_cmd = gBT/(gFC+gBT)")
    style(a2, "Commanded droop ratio [-]")
    a2.set_xlabel("Time [s]", color=C_TEXT, fontsize=10)
    legend(a2, loc="upper left")

    fig.align_ylabels()
    fig.tight_layout()
    fig.savefig(FIGS / "fig_tp0053_relay.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_tp0053_relay.png")


def wp0072_cycle():
    t, d = load("WP0072")
    m = (t >= 17.0) & (t <= 18.48)
    fig, (a0, a1, a2) = plt.subplots(
        3, 1, figsize=(8.5, 7.2), sharex=True,
        gridspec_kw=dict(height_ratios=[1.2, 1, 1]))
    a0.plot(t[m], d["I_fc"][m], color=C_IFC, lw=0.7, label="I_fc (meas)")
    a0.plot(t[m], d["I_batt"][m], color=C_IBT, lw=0.7, label="I_batt (meas)")
    style(a0, "Channel current [A]")
    legend(a0, ncol=2, loc="upper left")

    a1.plot(t[m], r_cmd(d)[m], color="#c98a1b", lw=1.1,
            label="r_cmd (slew-limited triangle)")
    style(a1, "Commanded droop ratio [-]")
    legend(a1, loc="upper left")

    a2.plot(t[m], d["V_bus"][m], color=C_VBUS, lw=0.9, label="V_bus")
    a2.set_ylim(11.5, 16.5)
    a2.axhline(12.0, color=C_VBUS, lw=0.8, ls=":", label="UV limit 12.0 V")
    style(a2, "Bus voltage [V]")
    a2.set_xlabel("Time [s]", color=C_TEXT, fontsize=10)
    legend(a2, loc="lower left")

    fig.align_ylabels()
    fig.tight_layout()
    fig.savefig(FIGS / "fig_wp0072_cycle.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_wp0072_cycle.png")


def wp_boundary():
    fig, axes = plt.subplots(2, 1, figsize=(8.5, 5.4), sharex=True)
    for ax, run, lbl in ((axes[0], "WP0071", "WP0071 (b = 0.25, sp 0.75)"),
                         (axes[1], "WP0073", "WP0073 (b = 0.22, sp 0.78)")):
        t, d = load(run)
        m = (t >= 16.6) & (t <= 18.6)
        ax.plot(t[m], d["I_fc"][m], color=C_IFC, lw=0.7, label="I_fc")
        ax.plot(t[m], d["I_batt"][m], color=C_IBT, lw=0.7, label="I_batt")
        style(ax, "Channel current [A]")
        ax.set_title(lbl, color=C_TEXT, fontsize=10)
        legend(ax, ncol=2, loc="upper left")
    axes[1].set_xlabel("Time [s]", color=C_TEXT, fontsize=10)
    fig.align_ylabels()
    fig.tight_layout()
    fig.savefig(FIGS / "fig_wp_boundary.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_wp_boundary.png")


# ---------------------------------------------------------- fw v5 sweep (2026-08-12)
V5_SWEEP = [  # run, share_sp — two automated T-sweep batches within one boot
    ("TP0074", 0.00), ("TP0075", 0.10), ("TP0076", 0.12), ("TP0077", 0.15),
    ("TP0078", 0.18), ("TP0079", 0.20), ("TP0080", 0.22), ("TP0081", 0.25),
    ("TP0082", 0.30), ("TP0083", 0.40), ("TP0084", 0.50),
    ("TP0085", 0.00), ("TP0086", 0.90), ("TP0087", 0.88), ("TP0088", 0.85),
    ("TP0089", 0.82), ("TP0090", 0.80), ("TP0091", 0.78), ("TP0092", 0.75),
    ("TP0093", 0.70), ("TP0094", 0.60),
]
V5_LATCHED = {"TP0074", "TP0075", "TP0076", "TP0085", "TP0086", "TP0087"}


def v5_metrics():
    rows = []
    for run, sp in V5_SWEEP:
        t, d = load(run)
        itot = d["I_fc"] + d["I_batt"]
        hold = d["I_cmd"] >= 5.99
        err = d["share_act"][hold] - sp if hold.any() else np.array([np.nan])
        minority = np.minimum(d["I_fc"], d["I_batt"])
        events = 0
        state = "on"
        for mi, ti in zip(minority, itot):
            if state == "on" and mi < 0.02 and ti > 0.3:
                state = "off"
            elif state == "off" and mi > 0.05:
                state = "on"
                events += 1
        rows.append(dict(run=run, sp=sp,
                         err_mean=float(np.nanmean(err)),
                         err_std=float(np.nanstd(err)),
                         events=events,
                         vmin=float(np.min(d["V_bus"])),
                         vbatt_min=float(np.min(d["V_batt"])),
                         latched=run in V5_LATCHED))
    return rows


def v5_sweep_summary(rows):
    fig, (a0, a1, a2) = plt.subplots(1, 3, figsize=(11.5, 3.5))

    gov = [r for r in rows if not r["latched"]]
    a0.errorbar([r["sp"] for r in gov], [r["err_mean"] for r in gov],
                yerr=[r["err_std"] for r in gov],
                fmt="o", color=C_SHR, ecolor="#e8a583", elinewidth=2,
                capsize=3, ms=5, label="hold mean err ± 1σ (in-band runs)")
    a0.axhline(0, color="#8a8a8a", lw=0.8)
    style(a0, "Share error [-]")
    a0.set_xlabel("Share setpoint", color=C_TEXT, fontsize=10)
    a0.set_title("Steady-state (6 A hold) tracking error", color=C_TEXT,
                 fontsize=10)
    legend(a0, loc="lower left")

    a1.plot([r["sp"] for r in rows], [r["events"] for r in rows],
            "o", color=C_SHR, ms=5, label="all 21 runs completed")
    style(a1, "Dropout events [-]")
    a1.set_ylim(-0.5, 5)
    a1.set_xlabel("Share setpoint", color=C_TEXT, fontsize=10)
    a1.set_title("Hysteretic dropout events per run", color=C_TEXT,
                 fontsize=10)
    legend(a1, loc="upper left")

    a2.plot([r["sp"] for r in rows], [r["vmin"] for r in rows],
            "o", color=C_VBUS, ms=5, label="V_bus run min")
    a2.plot([r["sp"] for r in rows], [r["vbatt_min"] for r in rows],
            "s", color=C_IBT, ms=4, label="V_batt run min")
    a2.axhline(15.9, color="#8a8a8a", lw=0.8, ls="--", label="no-load bus")
    a2.axhline(12.0, color=C_VBUS, lw=0.8, ls=":", label="UV limit 12.0 V")
    style(a2, "Run-minimum voltage [V]")
    a2.set_xlabel("Share setpoint", color=C_TEXT, fontsize=10)
    a2.set_title("Bus and battery-rail census", color=C_TEXT, fontsize=10)
    legend(a2, loc="center left")

    fig.tight_layout()
    fig.savefig(FIGS / "fig_v5sweep_summary.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_v5sweep_summary.png")


def wp0100_r6():
    t, d = load("WP0100")
    m = (t >= 16.8) & (t <= 18.7)
    fig, (a0, a1, a2) = plt.subplots(
        3, 1, figsize=(8.5, 7.2), sharex=True,
        gridspec_kw=dict(height_ratios=[1.2, 1, 1]))
    a0.plot(t[m], d["I_fc"][m], color=C_IFC, lw=0.7, label="I_fc (meas)")
    a0.plot(t[m], d["I_batt"][m], color=C_IBT, lw=0.7, label="I_batt (meas)")
    style(a0, "Channel current [A]")
    legend(a0, ncol=2, loc="upper left")

    a1.plot(t[m], r_cmd(d)[m], color="#c98a1b", lw=1.1,
            label="r_cmd (slew-limited triangle)")
    style(a1, "Commanded droop ratio [-]")
    legend(a1, loc="upper left")

    a2.plot(t[m], d["V_bus"][m], color=C_VBUS, lw=0.9, label="V_bus")
    a2.axhline(15.9, color="#8a8a8a", lw=0.8, ls="--", label="no-load bus")
    style(a2, "Bus voltage [V]")
    a2.set_xlabel("Time [s]", color=C_TEXT, fontsize=10)
    legend(a2, loc="lower left")

    fig.align_ylabels()
    fig.tight_layout()
    fig.savefig(FIGS / "fig_wp0100_r6.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_wp0100_r6.png")


def fc_knee():
    fig, axes = plt.subplots(2, 1, figsize=(8.5, 5.4), sharex=True)
    for run, lbl in (("WP0100", "WP0100 (held, 28 episodes)"),
                     ("WP0099", "WP0099 (collapsed, episode 5)")):
        t, d = load(run)
        m = (t >= 16.90) & (t <= 17.30)
        col = C_IFC if run == "WP0100" else C_VBUS
        axes[0].plot(t[m], d["I_fc"][m], color=col, lw=0.9,
                     label=f"I_fc {lbl}")
        axes[1].plot(t[m], d["V_fc"][m], color=col, lw=0.9,
                     label=f"V_fc {lbl}")
    style(axes[0], "FC channel current [A]")
    legend(axes[0], loc="upper left")
    style(axes[1], "FC source rail [V]")
    axes[1].set_xlabel("Time [s]", color=C_TEXT, fontsize=10)
    legend(axes[1], loc="lower left")
    fig.align_ylabels()
    fig.tight_layout()
    fig.savefig(FIGS / "fig_fc_knee.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_fc_knee.png")


def wp0101_cut():
    t, d = load("WP0101")
    m = (t >= 16.90) & (t <= 17.01)
    fig, (a0, a1, a2) = plt.subplots(
        3, 1, figsize=(8.5, 7.2), sharex=True,
        gridspec_kw=dict(height_ratios=[1.2, 1, 1]))
    a0.plot(t[m], d["I_fc"][m], color=C_IFC, lw=0.9, label="I_fc (meas)")
    a0.plot(t[m], d["I_batt"][m], color=C_IBT, lw=0.9, label="I_batt (meas)")
    style(a0, "Channel current [A]")
    legend(a0, ncol=2, loc="upper left")

    a1.plot(t[m], d["V_fc"][m], color=C_IFC, lw=0.9, label="V_fc")
    a1.plot(t[m], d["V_batt"][m], color=C_IBT, lw=0.9, label="V_batt")
    style(a1, "Source rail [V]")
    legend(a1, loc="lower left")

    a2.plot(t[m], d["V_bus"][m], color=C_VBUS, lw=0.9, label="V_bus")
    a2.axhline(12.0, color=C_VBUS, lw=0.8, ls=":", label="UV limit 12.0 V")
    style(a2, "Bus voltage [V]")
    a2.set_xlabel("Time [s]", color=C_TEXT, fontsize=10)
    legend(a2, loc="lower left")

    fig.align_ylabels()
    fig.tight_layout()
    fig.savefig(FIGS / "fig_wp0101_cut.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_wp0101_cut.png")




# ---------------------------------------------------------- fw v6 sweep (2026-08-13)
V6_SWEEP = [  # run, share setpoint — one boot, two automated T-sweep batches
    ("TP0102", 0.00), ("TP0103", 0.10), ("TP0104", 0.12), ("TP0105", 0.15),
    ("TP0106", 0.17), ("TP0107", 0.20), ("TP0108", 0.22), ("TP0109", 0.25),
    ("TP0110", 0.35), ("TP0111", 0.50),
    ("TP0112", 0.00), ("TP0113", 0.90), ("TP0114", 0.88), ("TP0115", 0.85),
    ("TP0116", 0.83), ("TP0117", 0.80), ("TP0118", 0.78), ("TP0119", 0.75),
    ("TP0120", 0.65),
]
# setpoints outside [DROOP_R_MIN, DROOP_R_MAX] = [0.15, 0.85] -> setpoint latch
V6_LATCHED = {"TP0102", "TP0103", "TP0104", "TP0112", "TP0113", "TP0114"}


def v6_metrics():
    """Per-run hold metrics + a strict total-source-dropout census.

    The dropout criterion is deliberately strict: BOTH channels at hard zero
    while the motor is commanded above 1 A. A per-channel threshold test
    chops on the 8.06 mA current-sense quantum and manufactures hundreds of
    spurious events in the latched runs, where one channel is off by design.
    """
    rows = []
    for run, sp in V6_SWEEP:
        t, d = load(run)
        itot = d["I_fc"] + d["I_batt"]
        hold = d["I_cmd"] >= 5.99
        act = d["share_act"][hold] if hold.any() else np.array([np.nan])
        # strict: both channels dark under load
        # A dropout is a LOSS OF CONDUCTION, so both tests are needed: the
        # pair must go dark *and* must have been conducting immediately
        # before. Testing darkness alone counts the trapezoid's own
        # zero-current tails (where I_cmd is still commanded but the motor
        # draws nothing) as multi-second "events". The census is not
        # hold-gated: both firmware-v6 dropouts occur on the ramp, at the
        # open-loop -> closed-loop handover, not in the constant-current hold.
        dark = (itot < 0.10) & (d["I_cmd"] > 1.0)
        n_ev, dur, run_on, t0 = 0, [], False, 0.0
        for k, (tt, dk) in enumerate(zip(t, dark)):
            if dk and not run_on:
                # qualify the ONSET only: the pair must have been carrying
                # real current in the samples immediately before going dark.
                if k and np.max(itot[max(0, k - 5):k]) > 0.35:
                    run_on, t0 = True, tt
            elif not dk and run_on:
                run_on = False
                dur.append(tt - t0)
                n_ev += 1
        itot_hold = float(np.nanmean(itot[hold])) if hold.any() else np.nan
        eff_sp = max(sp, 0.30 / itot_hold) if itot_hold == itot_hold else np.nan
        rows.append(dict(
            run=run, sp=sp, latched=run in V6_LATCHED,
            act=float(np.nanmean(act)), act_sd=float(np.nanstd(act)),
            itot=itot_hold, eff_sp=eff_sp,
            events=n_ev, worst_ms=(max(dur) * 1e3 if dur else 0.0),
            vbus=float(np.min(d["V_bus"])), vbatt=float(np.min(d["V_batt"])),
            vfc=float(np.min(d["V_fc"])),
            pwr=float(np.nanmean((d["V_fc"] * d["I_fc"] +
                                  d["V_batt"] * d["I_batt"])[hold])),
        ))
    return rows


def v6_sweep_summary(rows):
    """Three panels: governed tracking vs the effective setpoint, the rail
    census, and the session-drift confound."""
    fig, (a0, a1, a2) = plt.subplots(1, 3, figsize=(11.5, 3.5))

    gov = [r for r in rows if not r["latched"]]
    a0.plot([r["sp"] for r in gov], [r["act"] - r["sp"] for r in gov],
            "o", color="#bbbbbb", ms=5, label="error vs raw setpoint")
    a0.plot([r["sp"] for r in gov], [r["act"] - r["eff_sp"] for r in gov],
            "o", color=C_SHR, ms=5, label="error vs governed setpoint")
    a0.axhline(0, color="#8a8a8a", lw=0.8)
    style(a0, "Share error [-]")
    a0.set_xlabel("Share setpoint", color=C_TEXT, fontsize=10)
    a0.set_title("Tracking: the apparent bias is the floor clip",
                 color=C_TEXT, fontsize=10)
    legend(a0, loc="lower left")

    a1.plot([r["sp"] for r in rows], [r["vbus"] for r in rows],
            "o", color=C_VBUS, ms=5, label="$V_\\mathrm{bus}$ run min")
    a1.plot([r["sp"] for r in rows], [r["vbatt"] for r in rows],
            "s", color=C_IBT, ms=4, label="$V_\\mathrm{batt}$ run min")
    a1.axhline(12.0, color=C_VBUS, lw=0.8, ls=":", label="bus UV limit 12.0 V")
    a1.annotate("TP0115", xy=(0.85, 12.19), xytext=(0.60, 13.4), fontsize=8,
                color=C_VBUS,
                arrowprops=dict(arrowstyle="->", color=C_VBUS, lw=1.0))
    style(a1, "Run-minimum voltage [V]")
    a1.set_xlabel("Share setpoint", color=C_TEXT, fontsize=10)
    a1.set_title("Rail census: one bus excursion, at $r_{\\max}$",
                 color=C_TEXT, fontsize=10)
    legend(a1, loc="center right")

    order = list(range(len(rows)))
    a2.plot(order, [r["pwr"] for r in rows], "o-", color=C_IFC, ms=4, lw=1.0,
            label="hold source power")
    for i, r in enumerate(rows):
        if r["sp"] == 0.00:
            a2.plot(i, r["pwr"], "o", color=C_VBUS, ms=8, mfc="none", mew=1.6)
    a2.annotate("repeat pair,\nsame setpoint:\n+31%",
                xy=(10, rows[10]["pwr"]), xytext=(3.2, 12.6), fontsize=8,
                color=C_VBUS,
                arrowprops=dict(arrowstyle="->", color=C_VBUS, lw=1.0))
    style(a2, "Hold source power [W]")
    a2.set_xlabel("Run order within the boot", color=C_TEXT, fontsize=10)
    a2.set_title("Session drift confounds the ladder", color=C_TEXT,
                 fontsize=10)
    legend(a2, loc="upper left")

    fig.tight_layout()
    fig.savefig(FIGS / "fig_v6sweep_summary.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_v6sweep_summary.png")


def tp0115_handover():
    """The one bus excursion of the firmware-v6 ladder: a total source
    dropout at the open-loop -> closed-loop handover, at r* = DROOP_R_MAX."""
    t, d = load("TP0115")
    m = (t >= 4.415) & (t <= 4.485)
    fig, (a0, a1, a2) = plt.subplots(
        3, 1, figsize=(8.5, 7.2), sharex=True,
        gridspec_kw=dict(height_ratios=[1.2, 1, 1]))

    a0.plot(t[m], d["I_fc"][m], color=C_IFC, lw=1.1, label="$I_\\mathrm{fc}$")
    a0.plot(t[m], d["I_batt"][m], color=C_IBT, lw=1.1,
            label="$I_\\mathrm{batt}$")
    a0.axvspan(4.4491, 4.4550, color="#f3c9c6", alpha=0.6, zorder=0)
    a0.annotate("both dark,\n5.9 ms", xy=(4.4515, 0.30), xytext=(4.4335, 1.15),
                fontsize=8, color=C_VBUS, ha="center",
                arrowprops=dict(arrowstyle="->", color=C_VBUS, lw=1.0))
    a0.annotate("BT drops out first", xy=(4.4270, 0.02), xytext=(4.4165, 1.15),
                fontsize=8, color=C_IBT,
                arrowprops=dict(arrowstyle="->", color=C_IBT, lw=1.0))
    style(a0, "Channel current [A]")
    legend(a0, ncol=2, loc="upper left")

    a1.plot(t[m], r_cmd(d)[m], color="#c98a1b", lw=1.3,
            label="$r_\\mathrm{cmd}$ (slew-limited)")
    a1.axvline(4.4247, color="#8a8a8a", lw=0.9, ls="--")
    a1.annotate("open loop $\\rightarrow$ closed loop", xy=(4.4255, 0.80),
                fontsize=8, color=C_TEXT)
    a1.axhline(0.85, color=C_VBUS, lw=0.8, ls=":", label="$r_{\\max}=0.85$")
    style(a1, "Commanded droop ratio [-]")
    legend(a1, loc="lower left")

    a2.plot(t[m], d["V_bus"][m], color=C_VBUS, lw=1.2,
            label="$V_\\mathrm{bus}$")
    a2.plot(t[m], d["V_batt"][m], color=C_IBT, lw=1.0,
            label="$V_\\mathrm{batt}$")
    a2.axhline(12.0, color=C_VBUS, lw=0.8, ls=":", label="UV limit 12.0 V")
    style(a2, "Voltage [V]")
    a2.set_xlabel("Time [s]", color=C_TEXT, fontsize=10)
    legend(a2, loc="lower left")

    fig.align_ylabels()
    fig.tight_layout()
    fig.savefig(FIGS / "fig_tp0115_handover.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_tp0115_handover.png")


def wp0124_brownout():
    """The Imax = 8 A truncation: an ohmic battery-rail collapse, fully
    resolved on the logged timescale, against the surviving 6 A twin."""
    fig, (a0, a1) = plt.subplots(1, 2, figsize=(11.0, 4.0))

    for run, col, lbl in (("WP0123", C_IFC, "WP0123, $I_\\max$ = 6 A (survived)"),
                          ("WP0124", C_VBUS, "WP0124, $I_\\max$ = 8 A (MCU stop)")):
        t, d = load(run)
        m = (t >= 10.0) & (t <= 15.0)
        a0.plot(t[m], d["V_batt"][m], color=col, lw=1.0, label=lbl)
    a0.axvline(14.571, color=C_VBUS, lw=1.0, ls="--")
    a0.annotate("log ends\n(no trailer)", xy=(14.55, 5.75), xytext=(13.15, 5.45),
                fontsize=8, color=C_VBUS, ha="center",
                arrowprops=dict(arrowstyle="->", color=C_VBUS, lw=1.0))
    a0.axhspan(5.3, 6.5, color="#f3c9c6", alpha=0.45, zorder=0)
    a0.annotate("LM1084 dropout region", xy=(10.15, 6.28), fontsize=8,
                color=C_VBUS)
    style(a0, "Battery rail $V_\\mathrm{batt}$ [V]")
    a0.set_xlabel("Profile time [s]", color=C_TEXT, fontsize=10)
    a0.set_title("The rail that collapsed", color=C_TEXT, fontsize=10)
    legend(a0, loc="upper right")

    # ohmic fit, both sources, WP0124
    t, d = load("WP0124")
    m = (t >= 11.0) & (t <= 15.0)
    for cur, volt, col, nm in (("I_batt", "V_batt", C_IBT, "battery"),
                               ("I_fc", "V_fc", C_IFC, "fuel cell")):
        sel = m & (d[cur] > 0.2)
        p = np.polyfit(d[cur][sel], d[volt][sel], 1)
        xs = np.linspace(0.2, d[cur][sel].max(), 50)
        a1.plot(d[cur][sel], d[volt][sel], ".", color=col, ms=1.4, alpha=0.30)
        a1.plot(xs, np.polyval(p, xs), color=col, lw=1.8,
                label=f"{nm}: $R_\\mathrm{{src}}$ = {-p[0]:.2f} $\\Omega$")
    style(a1, "Source rail voltage [V]")
    a1.set_xlabel("Channel current [A]", color=C_TEXT, fontsize=10)
    a1.set_title("Source stiffness: a $4\\times$ asymmetry", color=C_TEXT,
                 fontsize=10)
    legend(a1, loc="lower left")

    fig.tight_layout()
    fig.savefig(FIGS / "fig_wp0124_brownout.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_wp0124_brownout.png")


def vbatt_threshold():
    """Why no V_batt undervoltage threshold separates the survivors from the
    truncation on this bench: replay the firmware-v6 leaky-dwell filter."""
    def dwell_latch(t, v, thr, latch_ms=20.0, leak=0.05, dtcap=5.0):
        dw, prev = 0.0, t[0]
        for tt, vv in zip(t, v):
            dt = min((tt - prev) * 1e3, dtcap)
            prev = tt
            dw = dw + dt if vv < thr else dw - leak * dt
            dw = max(dw, 0.0)
            if dw >= latch_ms:
                return tt
        return None

    runs = ["TP0102", "TP0103", "TP0104", "TP0105", "TP0107", "TP0111",
            "TP0112", "TP0115", "TP0117", "TP0120",
            "WP0121", "WP0122", "WP0123", "WP0124"]
    thrs = [6.8, 6.5, 6.0, 5.7]
    fig, ax = plt.subplots(figsize=(9.0, 3.8))
    for j, thr in enumerate(thrs):
        for i, run in enumerate(runs):
            t, d = load(run)
            lat = dwell_latch(t, d["V_batt"], thr)
            healthy = run != "WP0124"
            if lat is None:
                continue
            col = C_VBUS if healthy else C_IFC
            mk = "x" if healthy else "o"
            ax.plot(i, j, mk, color=col, ms=9, mew=2.0)
    ax.plot([], [], "x", color=C_VBUS, ms=9, mew=2.0,
            label="false latch on a healthy run")
    ax.plot([], [], "o", color=C_IFC, ms=9, mew=2.0,
            label="correct latch (WP0124, the truncation)")
    ax.set_yticks(range(len(thrs)))
    ax.set_yticklabels([f"{x:.1f} V" for x in thrs])
    ax.set_xticks(range(len(runs)))
    ax.set_xticklabels(runs, rotation=60, ha="right", fontsize=7.5)
    ax.set_ylim(len(thrs) - 0.4, -0.6)   # higher trip voltage at the top
    ax.set_xlim(-0.6, len(runs) - 0.4)
    style(ax, "Candidate $V_\\mathrm{batt}$ trip")
    ax.set_title("No threshold separates the survivors from the truncation",
                 color=C_TEXT, fontsize=10)
    legend(ax, loc="upper center", ncol=2)
    fig.tight_layout()
    fig.savefig(FIGS / "fig_vbatt_threshold.png", dpi=150)
    plt.close(fig)
    print(FIGS / "fig_vbatt_threshold.png")


if __name__ == "__main__":
    tp0010_zoom()
    tp0013_zoom()
    rows = hold_metrics()
    for r in rows:
        print(r)
    sweep_summary(rows)
    run_order(rows)
    vrows = val_metrics()
    for r in vrows:
        print(r)
    val_sweep_summary(vrows)
    tp0016_zoom()
    tp0037_gap()
    wp0039_ratchet()
    wp0040_governor()
    v4rows = v4_metrics()
    for r in v4rows:
        print(r)
    v4_sweep_summary(v4rows)
    tp0053_relay()
    wp0072_cycle()
    wp_boundary()
    v5rows = v5_metrics()
    for r in v5rows:
        print(r)
    v5_sweep_summary(v5rows)
    wp0100_r6()
    fc_knee()
    wp0101_cut()
    v6rows = v6_metrics()
    for r in v6rows:
        print(r)
    v6_sweep_summary(v6rows)
    tp0115_handover()
    wp0124_brownout()
    vbatt_threshold()
