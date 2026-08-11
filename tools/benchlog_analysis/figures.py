"""Figure builders for the bench-log analysis toolkit.

Registry-driven: FIGURES is an ordered list of (figure_name, builder) pairs.
Every builder has the signature

    builder(data: dict, cfg: dict) -> matplotlib.figure.Figure

where `data` is a common.load_csv() dict (numpy float64 arrays, NaN for blank
cells, plus the derived `t_s`) and `cfg` is a common.load_or_create_config()
dict. Builders NEVER save or close the figure -- make_figures.py owns the
file I/O so the same builders can be reused by a GUI or a notebook.

Style conventions enforced here (one place, so all figures agree):
  * x axis is always t_s, labelled "Time [s]".
  * Fixed role -> colour map (COLORS below); a signal keeps its colour in
    every figure it appears in.
  * Setpoints/references: dashed, same hue as their measured family.
  * Filtered overlays: darker shade of the same hue, drawn on top of a
    low-alpha raw trace, with the tau read out of cfg so the legend text can
    never drift from the config the user edited.
  * No markers (runs are ~40k points), light recessive grid behind the data,
    text in neutral dark grey (never in a series colour) -- the one exception
    is the dual-axis ownership colouring in tracking_overlay.
  * NaN gaps are left as gaps (matplotlib's default); nothing interpolates.
"""
import matplotlib

matplotlib.use("Agg")  # headless: required for CI, and for the bundled exe

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

import sys  # noqa: E402

if __package__ in (None, ""):  # pragma: no cover - direct-script import shim
    from pathlib import Path

    if not getattr(sys, "frozen", False):  # frozen: bundle resolves the pkg
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from benchlog_analysis import common
else:
    from . import common


# --------------------------------------------------------------------------
# Style constants
# --------------------------------------------------------------------------

# Role -> colour. Consistent across ALL figures; do not override locally.
COLORS = {
    "velocity": "#2a78d6",   # blue    - velocity loop family (v_sp, v_act)
    "share": "#eb6834",      # orange  - power-share family (share_sp/act)
    "I_fc": "#1baf7a",       # aqua    - fuel-cell channel current
    "I_batt": "#4a3aa7",     # violet  - battery channel current
    "I_cmd": "#2a78d6",      # blue    - velocity loop's control effort
    "gFC": "#1baf7a",        # aqua    - FC droop MDAC gain (matches I_fc)
    "gBT": "#4a3aa7",        # violet  - BT droop MDAC gain (matches I_batt)
    "r_cmd": "#008300",      # green   - commanded share ratio (controller out)
    "V_bus": "#e34948",      # red     - bus voltage
    "I_total": "#e87ba4",    # magenta - total bus current (I_fc + I_batt)
}

# No-load nominal bus voltage [V] for the reference line in bus_and_share.
# User-specified bench value (2026-08-10); the boosts regulate the loaded bus
# toward this and droop below it under load.
V_BUS_NOMINAL = 15.9

TEXT_COLOR = "#222222"       # all titles/labels/legends (neutral, not a hue)
ZERO_LINE_COLOR = "#8a8a8a"

LW_RAW = 1.2
LW_FILT = 1.6
LW_REF = 1.4
# Setpoints draw ABOVE their measured/filtered family: when tracking is tight
# the filtered trace sits exactly on the ref, and whichever is on top is the
# only one visible -- the dashed ref survives overlap, a solid line under a
# dash does too, so ref-on-top keeps both legible.
ZORDER_REF = 3
ALPHA_RAW_UNDER = 0.30       # raw trace under a filtered overlay
LW_RAW_UNDER = 1.0           # ...slightly thinner than a standalone raw trace

FIGSIZE_SINGLE = (10, 6)
FIGSIZE_STACK2 = (10, 7.5)

DPI_DEFAULT = 150


def _darker(hex_color, amount=0.35):
    """Blend a hex colour toward black by `amount` (0 = unchanged, 1 = black)."""
    hex_color = hex_color.lstrip("#")
    rgb = [int(hex_color[i:i + 2], 16) for i in (0, 2, 4)]
    rgb = [int(round(c * (1.0 - amount))) for c in rgb]
    return "#%02x%02x%02x" % tuple(rgb)


def _tau_label(tau_s):
    """Human-readable tau for a legend entry, e.g. 20 ms / 0.10 s."""
    if tau_s < 1.0:
        ms = tau_s * 1000.0
        return ("%.0f ms" % ms) if ms >= 10 else ("%.1f ms" % ms)
    return "%.2f s" % tau_s


def _tau(cfg, key):
    """Filter tau from cfg, defaulting to the package default if absent."""
    filters = cfg.get("filters", {}) if isinstance(cfg, dict) else {}
    return float(filters.get(key, common.DEFAULT_CONFIG["filters"][key]))


def _style_axes(ax, ylabel=None, xlabel=None):
    """Grid + label styling shared by every axes in every figure."""
    ax.grid(True, which="major", color="#cccccc", linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)  # grid behind the data
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.tick_params(colors=TEXT_COLOR, labelsize=9)
    if ylabel:
        ax.set_ylabel(ylabel, color=TEXT_COLOR, fontsize=10)
    if xlabel:
        ax.set_xlabel(xlabel, color=TEXT_COLOR, fontsize=10)


def _legend(ax, handles=None, labels=None, loc="upper right", ncol=1):
    if handles is None:
        handles, labels = ax.get_legend_handles_labels()
    if len(handles) < 2:
        return None
    leg = ax.legend(handles, labels, loc=loc, ncol=ncol, fontsize=9,
                    framealpha=0.9, edgecolor="#cccccc")
    for text in leg.get_texts():
        text.set_color(TEXT_COLOR)
    return leg


def _suptitle(fig, run_name, what):
    title = ("%s — %s" % (run_name, what)) if run_name else what
    fig.suptitle(title, color=TEXT_COLOR, fontsize=13, fontweight="bold")


def _run_name(cfg):
    """Run name injected by make_all via cfg["_run_name"] (optional)."""
    if isinstance(cfg, dict):
        return cfg.get("_run_name", "")
    return ""


def _finite_range(*arrays):
    """(min, max) over the finite entries of all arrays, or None if none."""
    lo, hi = np.inf, -np.inf
    for a in arrays:
        a = np.asarray(a, dtype=np.float64)
        finite = a[np.isfinite(a)]
        if finite.size:
            lo = min(lo, float(finite.min()))
            hi = max(hi, float(finite.max()))
    if not np.isfinite(lo):
        return None
    return lo, hi


def _band_limits(data_range, band_lo, band_hi):
    """Axis limits that place `data_range` inside the normalised band.

    band_lo/band_hi are fractions of the axes height (0 = bottom, 1 = top).
    Solving  (d - lo) / (hi - lo) = band  for both endpoints gives the axis
    span; a degenerate (zero-width) data range gets a small symmetric pad
    first so the span stays finite.
    """
    d0, d1 = data_range
    if d1 - d0 < 1e-9:
        pad = max(abs(d0), 1.0) * 0.05
        d0, d1 = d0 - pad, d1 + pad
    span = (d1 - d0) / (band_hi - band_lo)
    lo = d0 - band_lo * span
    return lo, lo + span


def _restrict_ticks(ax, axis, data_range, nbins=7):
    """Keep y ticks inside `data_range` only.

    Banded dual axes span far more range than their family occupies, so the
    default locator emits ticks (e.g. negative velocities) that exist nowhere
    in the data and read as real. Tick only over the band the family lives in.
    """
    d0, d1 = data_range
    if d1 - d0 < 1e-9:
        return
    locator = matplotlib.ticker.MaxNLocator(nbins=nbins, steps=[1, 2, 2.5, 5, 10])
    ticks = [t for t in locator.tick_values(d0, d1) if d0 - 1e-12 <= t <= d1 + 1e-12]
    if len(ticks) < 2:
        # A very narrow band can leave the locator with <2 in-band candidates;
        # falling back to the default locator would resurrect the off-band
        # ticks this function exists to suppress, so tick the band edges.
        ticks = [d0, d1]
    getattr(ax, "set_%sticks" % axis)(ticks)


# --------------------------------------------------------------------------
# Figure builders
# --------------------------------------------------------------------------

def tracking_overlay(data, cfg):
    """Fig 1: velocity + power-share tracking on one twinx axes.

    Deliberately dual-axis (user request). The two y-axes are scaled so the
    families occupy separate horizontal bands with a gap between them --
    velocity in the upper band, share in the lower -- so the overlay never
    turns into spaghetti. Axis labels/ticks are coloured to their family so
    which scale owns which trace is unambiguous. A run where one family has
    no data at all (e.g. no velocity chain on an R/PS profile) drops the
    dual axis entirely: the present family gets a plain plot of the whole
    figure area.
    """
    t = data["t_s"]
    tau = _tau(cfg, "share_act_tau_s")
    share_f = common.lowpass(data["share_act"], t, tau)

    c_vel = COLORS["velocity"]
    c_shr = COLORS["share"]
    c_shr_f = _darker(c_shr)

    r_v = _finite_range(data["v_sp"], data["v_act"])
    r_s = _finite_range(data["share_sp"], data["share_act"], share_f)

    fig, ax_v = plt.subplots(figsize=FIGSIZE_SINGLE, constrained_layout=True)

    if not (r_v and r_s):
        # Single-family run: no dual axis, no banding -- just plot whichever
        # family exists across the full figure area.
        if r_s:
            ax_v.plot(t, data["share_sp"], color=c_shr, linestyle="--",
                      linewidth=LW_REF, zorder=ZORDER_REF, label="share ref")
            ax_v.plot(t, data["share_act"], color=c_shr,
                      linewidth=LW_RAW_UNDER, alpha=ALPHA_RAW_UNDER,
                      label="share (meas)")
            ax_v.plot(t, share_f, color=c_shr_f, linewidth=LW_FILT,
                      label="share (filt, τ=%s)" % _tau_label(tau))
            _style_axes(ax_v, ylabel="Power share [FC fraction]",
                        xlabel="Time [s]")
        else:
            ax_v.plot(t, data["v_sp"], color=c_vel, linestyle="--",
                      linewidth=LW_REF, zorder=ZORDER_REF,
                      label="velocity ref")
            ax_v.plot(t, data["v_act"], color=c_vel, linewidth=LW_RAW,
                      label="velocity (meas)")
            _style_axes(ax_v, ylabel="Velocity [m/s]", xlabel="Time [s]")
        ax_v.set_xlim(float(t[0]), float(t[-1]))
        _legend(ax_v)
        _suptitle(fig, _run_name(cfg), "tracking (velocity + power share)")
        return fig

    ax_s = ax_v.twinx()

    # Velocity on the left axis (upper band).
    h = []
    h += ax_v.plot(t, data["v_sp"], color=c_vel, linestyle="--",
                   linewidth=LW_REF, zorder=ZORDER_REF, label="velocity ref")
    h += ax_v.plot(t, data["v_act"], color=c_vel, linewidth=LW_RAW,
                   label="velocity (meas)")

    # Share on the right axis (lower band); raw underneath, filtered on top.
    h += ax_s.plot(t, data["share_sp"], color=c_shr, linestyle="--",
                   linewidth=LW_REF, zorder=ZORDER_REF, label="share ref")
    h += ax_s.plot(t, data["share_act"], color=c_shr, linewidth=LW_RAW_UNDER,
                   alpha=ALPHA_RAW_UNDER, label="share (meas)")
    h += ax_s.plot(t, share_f, color=c_shr_f, linewidth=LW_FILT,
                   label="share (filt, τ=%s)" % _tau_label(tau))

    # Band separation: velocity gets the upper 0.60..0.97 of the axes height,
    # share the lower 0.03..0.40 -> a 20%-of-height empty corridor between the
    # families, which also hosts the combined legend. Ticks are restricted to
    # each family's own band so the off-band part of each scale (e.g. negative
    # "velocities" that exist nowhere in the data) is never labelled.
    ax_v.set_ylim(*_band_limits(r_v, 0.60, 0.97))
    _restrict_ticks(ax_v, "y", r_v)
    ax_s.set_ylim(*_band_limits(r_s, 0.03, 0.40))
    _restrict_ticks(ax_s, "y", r_s)

    _style_axes(ax_v, ylabel="Velocity [m/s]", xlabel="Time [s]")
    ax_s.grid(False)
    ax_s.set_axisbelow(True)
    for spine in ("top",):
        ax_s.spines[spine].set_visible(False)
    ax_s.set_ylabel("Power share [FC fraction]", fontsize=10)

    # Ownership colouring (the one sanctioned exception to neutral text).
    ax_v.yaxis.label.set_color(c_vel)
    ax_v.tick_params(axis="y", colors=c_vel, labelsize=9)
    ax_v.spines["left"].set_color(c_vel)
    ax_s.yaxis.label.set_color(c_shr)
    ax_s.tick_params(axis="y", colors=c_shr, labelsize=9)
    ax_s.spines["right"].set_color(c_shr)
    ax_s.spines["left"].set_visible(False)

    ax_v.set_xlim(float(t[0]), float(t[-1]))
    # Legend lives in the empty corridor between the two bands, so it cannot
    # sit on top of either family (or on a NaN gap in one of them).
    _legend(ax_v, h, [x.get_label() for x in h], loc="center", ncol=3)
    _suptitle(fig, _run_name(cfg), "tracking (velocity + power share)")
    return fig


def tracking_subplots(data, cfg):
    """Fig 2: the same tracking data, one loop per subplot (no scale tricks).

    A run with no velocity data omits the velocity subplot entirely; the
    power-share subplot then takes up the whole figure area.
    """
    t = data["t_s"]
    tau = _tau(cfg, "share_act_tau_s")
    share_f = common.lowpass(data["share_act"], t, tau)

    c_vel = COLORS["velocity"]
    c_shr = COLORS["share"]
    has_v = _finite_range(data["v_sp"], data["v_act"]) is not None

    if has_v:
        fig, (ax0, ax1) = plt.subplots(2, 1, figsize=FIGSIZE_STACK2,
                                       sharex=True, constrained_layout=True)
        ax0.plot(t, data["v_sp"], color=c_vel, linestyle="--",
                 linewidth=LW_REF, zorder=ZORDER_REF, label="velocity ref")
        ax0.plot(t, data["v_act"], color=c_vel, linewidth=LW_RAW,
                 label="velocity (meas)")
        _style_axes(ax0, ylabel="Velocity [m/s]")
        ax0.set_title("Velocity loop", color=TEXT_COLOR, fontsize=11,
                      loc="left")
        _legend(ax0)
    else:
        fig, ax1 = plt.subplots(figsize=FIGSIZE_SINGLE,
                                constrained_layout=True)

    ax1.plot(t, data["share_sp"], color=c_shr, linestyle="--",
             linewidth=LW_REF, zorder=ZORDER_REF, label="share ref")
    ax1.plot(t, data["share_act"], color=c_shr, linewidth=LW_RAW_UNDER,
             alpha=ALPHA_RAW_UNDER, label="share (meas)")
    ax1.plot(t, share_f, color=_darker(c_shr), linewidth=LW_FILT,
             label="share (filt, τ=%s)" % _tau_label(tau))
    _style_axes(ax1, ylabel="Power share [FC fraction]", xlabel="Time [s]")
    ax1.set_title("Power-share loop", color=TEXT_COLOR, fontsize=11,
                  loc="left")
    _legend(ax1)

    ax1.set_xlim(float(t[0]), float(t[-1]))
    _suptitle(fig, _run_name(cfg), "tracking")
    return fig


def error_subplots(data, cfg):
    """Fig 3: tracking error of both loops (setpoint - measured).

    A run with no velocity data omits the velocity-error subplot entirely;
    the share-error subplot then takes up the whole figure area.
    """
    t = data["t_s"]
    tau = _tau(cfg, "share_act_tau_s")
    share_f = common.lowpass(data["share_act"], t, tau)

    e_v = data["v_sp"] - data["v_act"]
    e_s_raw = data["share_sp"] - data["share_act"]
    e_s_filt = data["share_sp"] - share_f

    c_vel = COLORS["velocity"]
    c_shr = COLORS["share"]
    has_v = _finite_range(e_v) is not None

    if has_v:
        fig, (ax0, ax1) = plt.subplots(2, 1, figsize=FIGSIZE_STACK2,
                                       sharex=True, constrained_layout=True)
        ax0.axhline(0.0, color=ZERO_LINE_COLOR, linewidth=0.9, zorder=1)
        ax0.plot(t, e_v, color=c_vel, linewidth=LW_RAW,
                 label="velocity error")
        _style_axes(ax0, ylabel="Velocity error [m/s]")
        ax0.set_title("v_sp − v_act", color=TEXT_COLOR, fontsize=11,
                      loc="left")
    else:
        fig, ax1 = plt.subplots(figsize=FIGSIZE_SINGLE,
                                constrained_layout=True)

    ax1.axhline(0.0, color=ZERO_LINE_COLOR, linewidth=0.9, zorder=1)
    ax1.plot(t, e_s_raw, color=c_shr, linewidth=LW_RAW_UNDER,
             alpha=ALPHA_RAW_UNDER, label="share error (meas)")
    ax1.plot(t, e_s_filt, color=_darker(c_shr), linewidth=LW_FILT,
             label="share error (filt, τ=%s)" % _tau_label(tau))
    _style_axes(ax1, ylabel="Share error [−]", xlabel="Time [s]")
    ax1.set_title("share_sp − share_act", color=TEXT_COLOR, fontsize=11,
                  loc="left")
    _legend(ax1)

    ax1.set_xlim(float(t[0]), float(t[-1]))
    _suptitle(fig, _run_name(cfg), "tracking error")
    return fig


def effort_subplots(data, cfg):
    """Fig 4: control effort of both loops (motor current cmd, droop gains)."""
    t = data["t_s"]

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=FIGSIZE_STACK2, sharex=True,
                                   constrained_layout=True)

    ax0.axhline(0.0, color=ZERO_LINE_COLOR, linewidth=0.9, zorder=1)
    ax0.plot(t, data["I_cmd"], color=COLORS["I_cmd"], linewidth=LW_RAW,
             label="I_cmd")
    ax0.margins(y=0.10)  # headroom so a constant-current run doesn't sit on the edge
    _style_axes(ax0, ylabel="Motor current cmd [A]")
    ax0.set_title("Velocity-loop effort", color=TEXT_COLOR, fontsize=11,
                  loc="left")

    ax1.plot(t, data["gFC"], color=COLORS["gFC"], linewidth=LW_RAW,
             label="gFC")
    ax1.plot(t, data["gBT"], color=COLORS["gBT"], linewidth=LW_RAW,
             label="gBT")
    _style_axes(ax1, ylabel="Droop MDAC gain [−]", xlabel="Time [s]")
    ax1.set_title("Power-share-loop effort", color=TEXT_COLOR, fontsize=11,
                  loc="left")
    _legend(ax1)

    ax1.set_xlim(float(t[0]), float(t[-1]))
    _suptitle(fig, _run_name(cfg), "control effort")
    return fig


def currents_and_share(data, cfg):
    """Fig 5: channel currents against the share they produce."""
    t = data["t_s"]
    tau_fc = _tau(cfg, "I_fc_tau_s")
    tau_bt = _tau(cfg, "I_batt_tau_s")
    tau_sh = _tau(cfg, "share_act_tau_s")
    i_fc_f = common.lowpass(data["I_fc"], t, tau_fc)
    i_bt_f = common.lowpass(data["I_batt"], t, tau_bt)
    share_f = common.lowpass(data["share_act"], t, tau_sh)

    c_fc, c_bt, c_shr = COLORS["I_fc"], COLORS["I_batt"], COLORS["share"]

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=FIGSIZE_STACK2, sharex=True,
                                   constrained_layout=True)

    ax0.plot(t, data["I_fc"], color=c_fc, linewidth=LW_RAW_UNDER,
             alpha=ALPHA_RAW_UNDER, label="I_fc (meas)")
    ax0.plot(t, data["I_batt"], color=c_bt, linewidth=LW_RAW_UNDER,
             alpha=ALPHA_RAW_UNDER, label="I_batt (meas)")
    ax0.plot(t, i_fc_f, color=_darker(c_fc), linewidth=LW_FILT,
             label="I_fc (filt, τ=%s)" % _tau_label(tau_fc))
    ax0.plot(t, i_bt_f, color=_darker(c_bt), linewidth=LW_FILT,
             label="I_batt (filt, τ=%s)" % _tau_label(tau_bt))
    _style_axes(ax0, ylabel="Channel current [A]")
    ax0.set_title("Boost channel currents", color=TEXT_COLOR, fontsize=11,
                  loc="left")
    _legend(ax0, ncol=2)

    ax1.plot(t, data["share_sp"], color=c_shr, linestyle="--",
             linewidth=LW_REF, zorder=ZORDER_REF, label="share ref")
    ax1.plot(t, data["share_act"], color=c_shr, linewidth=LW_RAW_UNDER,
             alpha=ALPHA_RAW_UNDER, label="share (meas)")
    ax1.plot(t, share_f, color=_darker(c_shr), linewidth=LW_FILT,
             label="share (filt, τ=%s)" % _tau_label(tau_sh))
    _style_axes(ax1, ylabel="Power share [FC fraction]", xlabel="Time [s]")
    ax1.set_title("Resulting power share", color=TEXT_COLOR, fontsize=11,
                  loc="left")
    _legend(ax1)

    ax1.set_xlim(float(t[0]), float(t[-1]))
    _suptitle(fig, _run_name(cfg), "channel currents and power share")
    return fig


def share_controller(data, cfg):
    """Fig 6: power-share loop detail -- tracking on top, error + commanded
    ratio below.

    The commanded share ratio r_cmd is the share controller's output
    immediately before the droop-gain mapping. It is not logged directly,
    but the firmware maps it as gFC = K_DROOP/(RE_MAX*r) and
    gBT = K_DROOP/(RE_MAX*(1-r)) (teensy_controller.ino, setDroopGains), so
    r/(1-r) = gBT/gFC and

        r_cmd = gBT / (gFC + gBT)

    -- exact, and independent of the K_DROOP/RE_MAX calibration constants.
    The bottom subplot pairs the share error (left axis) with r_cmd (right
    axis, ownership-coloured) so controller action can be read against the
    error driving it.
    """
    t = data["t_s"]
    tau = _tau(cfg, "share_act_tau_s")
    share_f = common.lowpass(data["share_act"], t, tau)

    e_s_raw = data["share_sp"] - data["share_act"]
    e_s_filt = data["share_sp"] - share_f
    with np.errstate(divide="ignore", invalid="ignore"):
        r_cmd = data["gBT"] / (data["gFC"] + data["gBT"])

    c_shr = COLORS["share"]
    c_shr_f = _darker(c_shr)
    c_cmd = COLORS["r_cmd"]

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=FIGSIZE_STACK2, sharex=True,
                                   constrained_layout=True)

    ax0.plot(t, data["share_sp"], color=c_shr, linestyle="--",
             linewidth=LW_REF, zorder=ZORDER_REF, label="share ref")
    ax0.plot(t, data["share_act"], color=c_shr, linewidth=LW_RAW_UNDER,
             alpha=ALPHA_RAW_UNDER, label="share (meas)")
    ax0.plot(t, share_f, color=c_shr_f, linewidth=LW_FILT,
             label="share (filt, τ=%s)" % _tau_label(tau))
    _style_axes(ax0, ylabel="Power share [FC fraction]")
    ax0.set_title("Power-share tracking", color=TEXT_COLOR, fontsize=11,
                  loc="left")
    _legend(ax0)

    # Bottom: share error (left) vs commanded ratio (right), separate scales.
    h = []
    ax1.axhline(0.0, color=ZERO_LINE_COLOR, linewidth=0.9, zorder=1)
    h += ax1.plot(t, e_s_raw, color=c_shr, linewidth=LW_RAW_UNDER,
                  alpha=ALPHA_RAW_UNDER, label="share error (meas)")
    h += ax1.plot(t, e_s_filt, color=c_shr_f, linewidth=LW_FILT,
                  label="share error (filt, τ=%s)" % _tau_label(tau))
    _style_axes(ax1, ylabel="Share error [−]", xlabel="Time [s]")
    ax1.set_title("Share error and commanded ratio", color=TEXT_COLOR,
                  fontsize=11, loc="left")

    ax1r = ax1.twinx()
    h += ax1r.plot(t, r_cmd, color=c_cmd, linewidth=LW_RAW,
                   label="r_cmd = gBT/(gFC+gBT)")
    ax1r.grid(False)
    ax1r.spines["top"].set_visible(False)
    ax1r.set_ylabel("Commanded share ratio [−]", fontsize=10)

    # Ownership colouring, per the tracking_overlay convention.
    ax1.yaxis.label.set_color(c_shr)
    ax1.tick_params(axis="y", colors=c_shr, labelsize=9)
    ax1.spines["left"].set_color(c_shr)
    ax1r.yaxis.label.set_color(c_cmd)
    ax1r.tick_params(axis="y", colors=c_cmd, labelsize=9)
    ax1r.spines["right"].set_color(c_cmd)
    ax1r.spines["left"].set_visible(False)

    _legend(ax1, h, [x.get_label() for x in h], loc="upper right")

    ax1.set_xlim(float(t[0]), float(t[-1]))
    _suptitle(fig, _run_name(cfg), "power-share controller")
    return fig


def bus_and_share(data, cfg):
    """Fig 7: bus behaviour against the share driving it.

    Top: V_bus (left axis) with a dashed no-load-nominal reference line,
    and the total bus current draw I_fc + I_batt (right axis, ownership-
    coloured). The filtered total is the sum of the individually-filtered
    channel currents (the filter is linear, so this matches the per-channel
    taus exactly). Bottom: power-share tracking, so bus droop/loading can
    be read against the share split that produced it.
    """
    t = data["t_s"]
    tau_fc = _tau(cfg, "I_fc_tau_s")
    tau_bt = _tau(cfg, "I_batt_tau_s")
    tau_sh = _tau(cfg, "share_act_tau_s")
    i_tot = data["I_fc"] + data["I_batt"]
    i_tot_f = (common.lowpass(data["I_fc"], t, tau_fc)
               + common.lowpass(data["I_batt"], t, tau_bt))
    share_f = common.lowpass(data["share_act"], t, tau_sh)

    c_bus = COLORS["V_bus"]
    c_tot = COLORS["I_total"]
    c_shr = COLORS["share"]

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=FIGSIZE_STACK2, sharex=True,
                                   constrained_layout=True)

    h = []
    h.append(ax0.axhline(V_BUS_NOMINAL, color=c_bus, linestyle="--",
                         linewidth=LW_REF, zorder=ZORDER_REF,
                         label="V_bus nominal (%.1f V, no load)"
                               % V_BUS_NOMINAL))
    h += ax0.plot(t, data["V_bus"], color=c_bus, linewidth=LW_RAW,
                  label="V_bus (meas)")
    _style_axes(ax0, ylabel="Bus voltage [V]")
    ax0.set_title("Bus voltage and total current draw", color=TEXT_COLOR,
                  fontsize=11, loc="left")

    ax0r = ax0.twinx()
    h += ax0r.plot(t, i_tot, color=c_tot, linewidth=LW_RAW_UNDER,
                   alpha=ALPHA_RAW_UNDER, label="I_fc + I_batt (meas)")
    h += ax0r.plot(t, i_tot_f, color=_darker(c_tot), linewidth=LW_FILT,
                   label="I_fc + I_batt (filt)")
    ax0r.grid(False)
    ax0r.spines["top"].set_visible(False)
    ax0r.set_ylabel("Total bus current [A]", fontsize=10)

    # Band the two families like tracking_overlay: voltage in the upper band
    # (its range widened to always include the nominal line), current in the
    # lower band, an empty corridor between them hosting the legend --
    # otherwise the noisy raw V_bus band and the current band overprint each
    # other into an unreadable smear.
    r_bus = _finite_range(data["V_bus"], np.array([V_BUS_NOMINAL]))
    r_tot = _finite_range(i_tot, i_tot_f)
    if r_bus and r_tot:
        ax0.set_ylim(*_band_limits(r_bus, 0.62, 0.97))
        _restrict_ticks(ax0, "y", r_bus, nbins=5)
        ax0r.set_ylim(*_band_limits(r_tot, 0.03, 0.38))
        _restrict_ticks(ax0r, "y", r_tot, nbins=5)

    # Ownership colouring, per the dual-axis convention.
    ax0.yaxis.label.set_color(c_bus)
    ax0.tick_params(axis="y", colors=c_bus, labelsize=9)
    ax0.spines["left"].set_color(c_bus)
    ax0r.yaxis.label.set_color(_darker(c_tot))
    ax0r.tick_params(axis="y", colors=_darker(c_tot), labelsize=9)
    ax0r.spines["right"].set_color(_darker(c_tot))
    ax0r.spines["left"].set_visible(False)

    _legend(ax0, h, [x.get_label() for x in h], loc="center", ncol=2)

    ax1.plot(t, data["share_sp"], color=c_shr, linestyle="--",
             linewidth=LW_REF, zorder=ZORDER_REF, label="share ref")
    ax1.plot(t, data["share_act"], color=c_shr, linewidth=LW_RAW_UNDER,
             alpha=ALPHA_RAW_UNDER, label="share (meas)")
    ax1.plot(t, share_f, color=_darker(c_shr), linewidth=LW_FILT,
             label="share (filt, τ=%s)" % _tau_label(tau_sh))
    _style_axes(ax1, ylabel="Power share [FC fraction]", xlabel="Time [s]")
    ax1.set_title("Power share", color=TEXT_COLOR, fontsize=11, loc="left")
    _legend(ax1)

    ax1.set_xlim(float(t[0]), float(t[-1]))
    _suptitle(fig, _run_name(cfg), "bus voltage, current draw, power share")
    return fig


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------
# HOW TO ADD A FIGURE:
#   1. Write a builder  def my_figure(data, cfg) -> Figure  above. Use the
#      COLORS map and the _style_axes/_legend/_suptitle helpers so it matches
#      the rest; never save or close the figure inside the builder.
#   2. Append ("my_figure", my_figure) to FIGURES below. The name becomes the
#      output filename (<name>.png in the run directory) -- keep it a valid
#      bare filename.
# That is the whole contract; make_figures.py picks it up automatically.
FIGURES = [
    ("tracking_overlay", tracking_overlay),
    ("tracking_subplots", tracking_subplots),
    ("error_subplots", error_subplots),
    ("effort_subplots", effort_subplots),
    ("currents_and_share", currents_and_share),
    ("share_controller", share_controller),
    ("bus_and_share", bus_and_share),
]
