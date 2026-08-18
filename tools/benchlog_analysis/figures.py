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
    is the dual-axis ownership colouring on twinx figures, where an axis
    label/ticks/spine take their family's hue.
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
    "V_chg": "#0f8f95",      # teal    - charger input voltage
    "V_rgn": "#7d6608",      # brass   - regen-node voltage
    "I_total": "#e87ba4",    # magenta - total bus current (I_fc + I_batt)
    "u_unsat": "#c07a1e",    # amber   - drive controller pre-clamp output
    "drive_x0": "#7a5cc9",   # purple  - Youla drive controller x[0] state
    "v_truth": "#1baf7a",    # aqua    - offline encoder-derived truth velocity
    "v_implied": "#eb6834",  # orange  - period-implied speed (pitch/ref)
    "multi_pitch": "#4a3aa7",  # violet - multi-pitch (missed-edge) rate
    "spurious_drop": "#e34948",  # red  - spurious-drop (rejection) rate
}

# Encoder slot pitch [m] -- one quadrature-decoded count is half a slot
# pitch (x2 decode); pitch itself is 2*pi*FLYWHEEL_RADIUS_M/ENCODER_SLOTS
# = 2*pi*0.0762/120 = 3.990e-3 m (see CLAUDE.md fw v12 addendum). Used only
# for the offline truth-velocity audit below -- not a control-path constant.
ENCODER_PITCH_M = 3.990e-3

# Deviation threshold for shading |v_act/v_truth - 1| > this fraction in the
# encoder_diagnostics scale-audit panel.
ENC_SCALE_DEVIATION_FRAC = 0.20

# Drive controller actuator rails [A] for the Hanus-conditioning plot
# (fw v11 velocity-loop drive controller saturation limits).
U_UNSAT_RAIL_A = 12.0
# Absolute tolerance for treating |u_unsat| as "at/over the rail" -- avoids
# flagging a sample that is a float epsilon under the rail as unsaturated.
U_UNSAT_RAIL_TOL_A = 1e-6

# No-load nominal bus voltage [V] for the reference line in bus_and_share.
# User-specified bench value (2026-08-10); the boosts regulate the loaded bus
# toward this and droop below it under load.
V_BUS_NOMINAL = 15.93

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


def _legend(ax, handles=None, labels=None, loc="upper right", ncol=1,
            bbox_to_anchor=None):
    if handles is None:
        handles, labels = ax.get_legend_handles_labels()
    if len(handles) < 2:
        return None
    kwargs = {}
    if bbox_to_anchor is not None:
        kwargs["bbox_to_anchor"] = bbox_to_anchor
    leg = ax.legend(handles, labels, loc=loc, ncol=ncol, fontsize=9,
                    framealpha=0.9, edgecolor="#cccccc", **kwargs)
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


def _r_cmd(data):
    """Commanded share ratio reconstructed from the logged droop gains.

    r_cmd = gBT/(gFC+gBT), exact from the firmware mapping
    gFC = K_DROOP/(RE_MAX*r), gBT = K_DROOP/(RE_MAX*(1-r)) -- no calibration
    constants needed. Ticks where both gains are zero (MDAC not yet driven)
    yield NaN, which plots as a gap per the NaN convention.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        return data["gBT"] / (data["gFC"] + data["gBT"])


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

def tracking_subplots(data, cfg):
    """Fig 1: velocity and power-share tracking, one loop per subplot.

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
    """Fig 2: tracking error of both loops (setpoint - measured).

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
    """Fig 3: control effort of both loops (motor current cmd, droop gains).

    The bottom subplot pairs the two droop MDAC gain commands (left axis)
    with the commanded share ratio r_cmd = gBT/(gFC+gBT) they were mapped
    from (right axis, ownership-coloured) -- the controller output and its
    actuation on one time base.
    """
    t = data["t_s"]
    r_cmd = _r_cmd(data)
    c_cmd = COLORS["r_cmd"]

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=FIGSIZE_STACK2, sharex=True,
                                   constrained_layout=True)

    ax0.axhline(0.0, color=ZERO_LINE_COLOR, linewidth=0.9, zorder=1)
    ax0.plot(t, data["I_cmd"], color=COLORS["I_cmd"], linewidth=LW_RAW,
             label="I_cmd")
    ax0.margins(y=0.10)  # headroom so a constant-current run doesn't sit on the edge
    _style_axes(ax0, ylabel="Motor current cmd [A]")
    ax0.set_title("Velocity-loop effort", color=TEXT_COLOR, fontsize=11,
                  loc="left")

    h = []
    h += ax1.plot(t, data["gFC"], color=COLORS["gFC"], linewidth=LW_RAW,
                  label="gFC")
    h += ax1.plot(t, data["gBT"], color=COLORS["gBT"], linewidth=LW_RAW,
                  label="gBT")
    _style_axes(ax1, ylabel="Droop MDAC gain [−]", xlabel="Time [s]")
    ax1.set_title("Power-share-loop effort", color=TEXT_COLOR, fontsize=11,
                  loc="left")

    ax1r = ax1.twinx()
    h += ax1r.plot(t, r_cmd, color=c_cmd, linewidth=LW_RAW,
                   label="r_cmd = gBT/(gFC+gBT)")
    ax1r.grid(False)
    ax1r.spines["top"].set_visible(False)
    ax1r.set_ylabel("Commanded share ratio [−]", fontsize=10)
    # Ownership colouring, per the dual-axis convention.
    ax1r.yaxis.label.set_color(c_cmd)
    ax1r.tick_params(axis="y", colors=c_cmd, labelsize=9)
    ax1r.spines["right"].set_color(c_cmd)
    ax1r.spines["left"].set_visible(False)

    # One row ABOVE the axes (right-anchored, clear of the left-side title):
    # both y-axes autoscale their own maxima near the top, so any in-axes
    # placement can land on a plateau of one family or the other.
    _legend(ax1, h, [x.get_label() for x in h], loc="lower right", ncol=3,
            bbox_to_anchor=(1.0, 1.0))

    ax1.set_xlim(float(t[0]), float(t[-1]))
    _suptitle(fig, _run_name(cfg), "control effort")
    return fig


def currents_and_share(data, cfg):
    """Fig 4: channel currents against the share they produce."""
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
    """Fig 5: power-share loop detail -- tracking on top, error + commanded
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
    r_cmd = _r_cmd(data)

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

    # Ownership colouring, per the dual-axis convention.
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
    """Fig 6: bus behaviour against the share driving it.

    Top: V_bus (left axis) with a dashed no-load-nominal reference line,
    and the total bus current draw I_fc + I_batt (right axis, ownership-
    coloured). The filtered total is the elementwise sum of the two
    individually-filtered channel currents, each at its own tau -- it is
    deliberately NOT a low-pass of the total at any single tau, and with
    unequal taus (or a NaN gap in only one channel) it is not equal to
    filtering the summed signal. Bottom: power-share tracking, so bus
    droop/loading can be read against the share split that produced it.
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
                   label="I_fc + I_batt (filt, τ=%s/%s)"
                         % (_tau_label(tau_fc), _tau_label(tau_bt)))
    ax0r.grid(False)
    ax0r.spines["top"].set_visible(False)
    ax0r.set_ylabel("Total bus current [A]", fontsize=10)

    # Band the two families into separate horizontal strips: voltage in the
    # upper band (its range widened to always include the nominal line),
    # current in the lower band, an empty corridor between them hosting the
    # legend --
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


def charge_regen_and_currents(data, cfg):
    """Fig 7 (v3+ only): charger/regen node voltages against channel currents.

    Top: the two power-path node voltages V_rgn (regen node) and V_chg
    (charger input), plotted raw -- nothing in this module filters a voltage
    (V_bus in bus_and_share is raw too). Bottom: the two boost channel
    currents I_fc / I_batt (raw + filtered) and their total I_fc + I_batt.
    The filtered total is the elementwise sum of the two individually-
    filtered channels, each at its own tau -- it is deliberately NOT a
    low-pass of the total at any single tau, and with unequal taus (or a NaN
    gap in only one channel) it is not equal to filtering the summed signal.

    Both families get their own subplot, so there is no dual axis and no
    banding here -- the two are read against a shared time axis only.

    Returns None (no figure) when V_chg/V_rgn are absent from `data` -- i.e.
    any pre-v3 CSV -- so make_all() can skip this figure gracefully for older
    logs instead of KeyError'ing. I_fc/I_batt exist in every format version.
    """
    if "V_chg" not in data or "V_rgn" not in data:
        return None

    t = data["t_s"]
    tau_fc = _tau(cfg, "I_fc_tau_s")
    tau_bt = _tau(cfg, "I_batt_tau_s")
    i_fc_f = common.lowpass(data["I_fc"], t, tau_fc)
    i_bt_f = common.lowpass(data["I_batt"], t, tau_bt)
    i_tot = data["I_fc"] + data["I_batt"]
    i_tot_f = i_fc_f + i_bt_f

    c_chg = COLORS["V_chg"]
    c_rgn = COLORS["V_rgn"]
    c_fc, c_bt, c_tot = COLORS["I_fc"], COLORS["I_batt"], COLORS["I_total"]

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=FIGSIZE_STACK2, sharex=True,
                                   constrained_layout=True)

    ax0.plot(t, data["V_rgn"], color=c_rgn, linewidth=LW_RAW,
             label="V_rgn (regen node)")
    ax0.plot(t, data["V_chg"], color=c_chg, linewidth=LW_RAW,
             label="V_chg (charger input)")
    _style_axes(ax0, ylabel="Voltage [V]")
    ax0.set_title("Charger and regen node voltages", color=TEXT_COLOR,
                  fontsize=11, loc="left")
    _legend(ax0)

    ax1.plot(t, data["I_fc"], color=c_fc, linewidth=LW_RAW_UNDER,
             alpha=ALPHA_RAW_UNDER, label="I_fc (meas)")
    ax1.plot(t, data["I_batt"], color=c_bt, linewidth=LW_RAW_UNDER,
             alpha=ALPHA_RAW_UNDER, label="I_batt (meas)")
    ax1.plot(t, i_tot, color=c_tot, linewidth=LW_RAW_UNDER,
             alpha=ALPHA_RAW_UNDER, label="I_fc + I_batt (meas)")
    ax1.plot(t, i_fc_f, color=_darker(c_fc), linewidth=LW_FILT,
             label="I_fc (filt, τ=%s)" % _tau_label(tau_fc))
    ax1.plot(t, i_bt_f, color=_darker(c_bt), linewidth=LW_FILT,
             label="I_batt (filt, τ=%s)" % _tau_label(tau_bt))
    ax1.plot(t, i_tot_f, color=_darker(c_tot), linewidth=LW_FILT,
             label="I_fc + I_batt (filt, τ=%s/%s)"
                   % (_tau_label(tau_fc), _tau_label(tau_bt)))
    _style_axes(ax1, ylabel="Current [A]", xlabel="Time [s]")
    ax1.set_title("Channel currents and total", color=TEXT_COLOR,
                  fontsize=11, loc="left")
    _legend(ax1, ncol=2)

    ax1.set_xlim(float(t[0]), float(t[-1]))
    _suptitle(fig, _run_name(cfg),
              "charger/regen node voltages and channel currents")
    return fig


def drive_controller_conditioning(data, cfg):
    """Fig 8 (v5 only): Hanus-conditioning verification for the drive loop.

    Top: I_cmd (the drive controller's clamped/commanded output, already
    plotted elsewhere) is NOT the focus here -- this figure is about the
    controller's internal PRE-clamp output, u_unsat, overlaid against the
    +/-U_UNSAT_RAIL_A actuator rails, with intervals where
    abs(u_unsat) >= U_UNSAT_RAIL_A (within U_UNSAT_RAIL_TOL_A) shaded to mark
    saturation -- the windows where the anti-windup/Hanus conditioning
    mechanism is actively doing work. Bottom: the Youla drive controller's
    integrator state x[0] (drive_x0) on the same time base, so state
    behaviour during a saturation window can be read directly against it.

    Returns None (no figure) when u_unsat/drive_x0 are absent from `data`
    -- i.e. any pre-v5 CSV -- so make_all() can skip this figure gracefully
    for older logs instead of KeyError'ing.
    """
    if "u_unsat" not in data or "drive_x0" not in data:
        return None

    t = data["t_s"]
    u = data["u_unsat"]
    x0 = data["drive_x0"]

    c_u = COLORS["u_unsat"]
    c_x0 = COLORS["drive_x0"]

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=FIGSIZE_STACK2, sharex=True,
                                   constrained_layout=True)

    ax0.axhline(0.0, color=ZERO_LINE_COLOR, linewidth=0.9, zorder=1)
    ax0.axhline(U_UNSAT_RAIL_A, color=c_u, linestyle="--", linewidth=LW_REF,
                zorder=ZORDER_REF, label="actuator rail (+/-%.0f A)"
                                          % U_UNSAT_RAIL_A)
    ax0.axhline(-U_UNSAT_RAIL_A, color=c_u, linestyle="--", linewidth=LW_REF,
                zorder=ZORDER_REF)
    ax0.plot(t, u, color=c_u, linewidth=LW_RAW, label="u_unsat (pre-clamp)")

    saturated = np.abs(u) >= (U_UNSAT_RAIL_A - U_UNSAT_RAIL_TOL_A)
    # fill_between's `where` mask draws one shaded span per contiguous run
    # of True; NaN cells in u compare False in `saturated` (np.abs(NaN) is
    # NaN, NaN >= x is False), so a logging gap simply isn't shaded rather
    # than raising.
    ax0.fill_between(t, 0.0, 1.0,
                      where=saturated, color=c_u, alpha=0.12, zorder=0,
                      transform=ax0.get_xaxis_transform(), linewidth=0,
                      label="saturated")
    _style_axes(ax0, ylabel="u_unsat [A]")
    ax0.set_title("Drive controller pre-clamp output vs. actuator rails",
                  color=TEXT_COLOR, fontsize=11, loc="left")
    _legend(ax0)

    ax1.axhline(0.0, color=ZERO_LINE_COLOR, linewidth=0.9, zorder=1)
    ax1.plot(t, x0, color=c_x0, linewidth=LW_RAW, label="drive_x0")
    ax1.fill_between(t, 0.0, 1.0,
                      where=saturated, color=c_u, alpha=0.12, zorder=0,
                      transform=ax1.get_xaxis_transform(), linewidth=0)
    _style_axes(ax1, ylabel="drive_x0 [-]", xlabel="Time [s]")
    ax1.set_title("Youla drive controller integrator state x[0]",
                  color=TEXT_COLOR, fontsize=11, loc="left")
    _legend(ax1)

    ax1.set_xlim(float(t[0]), float(t[-1]))
    _suptitle(fig, _run_name(cfg), "drive controller conditioning (u_unsat, x[0])")
    return fig


def _encoder_truth_velocity(encoder_pos, t_s, window_s=0.050):
    """Offline truth velocity from raw encoder_pos via a centered diff.

    v[i] = (encoder_pos[hi] - encoder_pos[lo]) * (ENCODER_PITCH_M / 2) / dt

    lo/hi are the samples nearest t_s[i] -/+ window_s/2 (t_s is monotonic
    non-decreasing, so np.searchsorted locates them in O(log n)). The /2
    accounts for the firmware's x2 quadrature decode -- encoder_pos advances
    two counts per physical slot pitch, so one count is pitch/2 of travel.
    NaN where the window collapses (edges of the run, or too few samples) or
    the bracketing encoder_pos samples are themselves NaN.
    """
    n = t_s.shape[0]
    v = np.full(n, np.nan, dtype=np.float64)
    if n < 2:
        return v
    half = window_s / 2.0
    lo_idx = np.searchsorted(t_s, t_s - half, side="left")
    hi_idx = np.searchsorted(t_s, t_s + half, side="right") - 1
    hi_idx = np.clip(hi_idx, 0, n - 1)
    for i in range(n):
        lo, hi = lo_idx[i], hi_idx[i]
        if hi <= lo:
            continue
        p_lo, p_hi = encoder_pos[lo], encoder_pos[hi]
        if not (np.isfinite(p_lo) and np.isfinite(p_hi)):
            continue
        dt = t_s[hi] - t_s[lo]
        if dt <= 0:
            continue
        v[i] = (p_hi - p_lo) * (ENCODER_PITCH_M / 2.0) / dt
    return v


def _cumulative_rate_per_s(counts, t_s, bin_s=1.0):
    """Per-second rate of a cumulative (monotonic non-decreasing) counter.

    Bins t_s into fixed bin_s windows and returns (bin_center_s, rate) where
    rate is the counter's increase over the bin divided by the bin's actual
    elapsed time (handles a short/partial trailing bin correctly). A
    negative increase (counter wrap) is reported as NaN rather than a
    negative rate -- see the module docstring's note on wrap.
    """
    t_s = np.asarray(t_s, dtype=np.float64)
    counts = np.asarray(counts, dtype=np.float64)
    n = t_s.shape[0]
    if n < 2:
        return np.empty(0), np.empty(0)
    t_end = t_s[-1]
    n_bins = max(int(np.ceil(t_end / bin_s)), 1)
    centers = np.empty(n_bins)
    rates = np.full(n_bins, np.nan)
    edges = np.arange(n_bins + 1) * bin_s
    idx = np.searchsorted(t_s, edges)
    idx = np.clip(idx, 0, n - 1)
    for b in range(n_bins):
        i0, i1 = idx[b], idx[b + 1]
        centers[b] = 0.5 * (edges[b] + edges[b + 1])
        if i1 <= i0:
            continue
        c0, c1 = counts[i0], counts[i1]
        dt = t_s[i1] - t_s[i0]
        if not (np.isfinite(c0) and np.isfinite(c1)) or dt <= 0:
            continue
        d = c1 - c0
        rates[b] = (d / dt) if d >= 0 else np.nan
    return centers, rates


def encoder_diagnostics(data, cfg):
    """Fig 9 (v6 only): encoder scale audit and edge-quality diagnostics.

    Panel (a): offline truth velocity computed directly from encoder_pos
    (centered diff, ENCODER_PITCH_M/2 per count) overlaid with the logged
    v_act -- this is the scale audit for the online edge-period estimator.
    Intervals where |v_act/v_truth| deviates more than
    ENC_SCALE_DEVIATION_FRAC from 1 are shaded.

    Panel (b): enc_period_ref_us converted to an implied speed
    (pitch / period, signed by v_act's sign) plotted against the SAME
    encoder_pos-derived truth velocity panel (a) uses -- a reference-poisoning
    event (the fw v13 k-branch basin, or the fw v17 x2 rounding basin) shows
    as roughly a 2x divergence from truth. The comparison reference is truth
    rather than v_act because v_implied and v_act are both estimator outputs
    and agree with each other inside a basin.

    Panel (c): per-second rates of the two cumulative counters
    (enc_multi_pitch_count = missed-edge rate, enc_spurious_drop_count =
    rejection rate), on the same time base as (a)/(b).

    Returns None (no figure) when the v6 columns are absent from `data`
    -- i.e. any pre-v6 CSV -- so make_all() can skip this figure gracefully,
    mirroring drive_controller_conditioning's pre-v5 skip.
    """
    v6_cols = ("encoder_pos", "enc_period_ref_us", "enc_multi_pitch_count",
               "enc_spurious_drop_count")
    if not all(c in data for c in v6_cols):
        return None

    t = data["t_s"]
    encoder_pos = data["encoder_pos"]
    v_act = data["v_act"]

    v_truth = _encoder_truth_velocity(encoder_pos, t)

    with np.errstate(divide="ignore", invalid="ignore"):
        ref_s = data["enc_period_ref_us"] * 1.0e-6
        v_implied_mag = np.where(ref_s > 0, ENCODER_PITCH_M / ref_s, np.nan)
        sign = np.where(np.isfinite(v_act) & (v_act != 0.0),
                         np.sign(v_act), 1.0)
        v_implied = sign * v_implied_mag

    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = v_act / v_truth
    deviated = np.isfinite(ratio) & (
        np.abs(ratio - 1.0) > ENC_SCALE_DEVIATION_FRAC)

    c_truth = COLORS["v_truth"]
    c_act = COLORS["velocity"]
    c_impl = COLORS["v_implied"]
    c_mp = COLORS["multi_pitch"]
    c_sd = COLORS["spurious_drop"]

    fig, (ax0, ax1, ax2) = plt.subplots(
        3, 1, figsize=(10, 10.5), sharex=True, constrained_layout=True)

    ax0.fill_between(t, 0.0, 1.0, where=deviated, color="#999999",
                      alpha=0.15, zorder=0,
                      transform=ax0.get_xaxis_transform(), linewidth=0,
                      label="|v_act/v_truth-1| > %.0f%%"
                            % (ENC_SCALE_DEVIATION_FRAC * 100.0))
    ax0.plot(t, v_truth, color=c_truth, linewidth=LW_RAW,
             label="v_truth (from encoder_pos)")
    ax0.plot(t, v_act, color=c_act, linewidth=LW_RAW_UNDER,
             alpha=0.75, label="v_act (logged)")
    _style_axes(ax0, ylabel="Velocity [m/s]")
    ax0.set_title("Scale audit: encoder-derived truth vs. logged v_act",
                  color=TEXT_COLOR, fontsize=11, loc="left")
    _legend(ax0)

    # Panel (b) compares the reference-implied speed against the encoder_pos
    # TRUTH velocity, not against v_act. Both v_implied and v_act are outputs
    # of the same estimator (v_implied is its EWMA state, v_act its ring
    # average), so plotting them against each other is self-confirming: the
    # x2 rounding basin parks BOTH at twice the truth and the panel reads
    # clean. encoder_pos owes nothing to the estimator, so it is the only
    # reference that can expose a basin the estimator agrees with itself on.
    ax1.plot(t, v_implied, color=c_impl, linewidth=LW_RAW,
             label="v_implied = pitch / enc_period_ref_us")
    ax1.plot(t, v_truth, color=c_truth, linewidth=LW_RAW_UNDER, alpha=0.75,
             label="v_truth (from encoder_pos)")
    _style_axes(ax1, ylabel="Velocity [m/s]")
    ax1.set_title(
        "Period-implied speed vs. encoder truth (basin-poisoning check)",
        color=TEXT_COLOR, fontsize=11, loc="left")
    _legend(ax1)

    centers_mp, rate_mp = _cumulative_rate_per_s(
        data["enc_multi_pitch_count"], t)
    centers_sd, rate_sd = _cumulative_rate_per_s(
        data["enc_spurious_drop_count"], t)
    ax2.plot(centers_mp, rate_mp, color=c_mp, linewidth=LW_RAW,
             label="multi-pitch rate (missed-edge) [/s]")
    ax2.plot(centers_sd, rate_sd, color=c_sd, linewidth=LW_RAW,
             label="spurious-drop rate (rejection) [/s]")
    _style_axes(ax2, ylabel="Rate [1/s]", xlabel="Time [s]")
    ax2.set_title("Cumulative-counter diff rates", color=TEXT_COLOR,
                  fontsize=11, loc="left")
    _legend(ax2)

    ax2.set_xlim(float(t[0]), float(t[-1]))
    _suptitle(fig, _run_name(cfg), "encoder diagnostics")
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
#      bare filename. A builder MAY return None instead of a Figure to skip
#      itself gracefully (e.g. required columns absent on older-format
#      data); make_figures.py treats a None return as "no PNG for this
#      figure on this run", not an error.
# That is the whole contract; make_figures.py picks it up automatically.
FIGURES = [
    ("tracking_subplots", tracking_subplots),
    ("error_subplots", error_subplots),
    ("effort_subplots", effort_subplots),
    ("currents_and_share", currents_and_share),
    ("share_controller", share_controller),
    ("bus_and_share", bus_and_share),
    ("charge_regen_and_currents", charge_regen_and_currents),
    ("drive_controller_conditioning", drive_controller_conditioning),
    ("encoder_diagnostics", encoder_diagnostics),
]
