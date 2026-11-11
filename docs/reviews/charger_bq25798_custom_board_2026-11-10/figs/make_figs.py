"""Figure generator for the README walkthrough of the custom BQ25798 charger board (CCB), revision r2.

Writes the SVG figures of README.md into this folder. Diagrams are simplified redrawings of the design document
(docs/charger_bq25798_custom_board_2026-11-10.md, "the design"). Plots are computed from the calculation scripts of
the parent folder, which this script imports and re-runs (their console output is suppressed):

- layout_calc.py      forced-air thermal network ([LC] section 8): tj_band(), h_flat(), c_ccb, p_ic()
- tall_stack_calc.py  eFuse hard-short IN spike ([TS] section (c)): in_spike(), DL_IN
- sch_calc.py         inductor ripple ([CALC], [DS] Eq 5): rip_buck()
and reads mech_parse_out.json (MB board geometry), tida_layout_parse_out.txt (TIDA-050047 cell), bom_cost.json (cost
roll-up) and ledger_table.md (203-key finding ledger). Every constant typed in below cites its design section.

Run:  C:/Users/ricky/miniforge3/python.exe -I make_figs.py [--png <folder>]
The optional --png writes a PNG copy of every figure to <folder> for a visual check; the PNGs are not kept here.
"""
import contextlib
import importlib.util
import io
import json
import math
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True       # importing the calc scripts must not leave __pycache__ in the review folder
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                      # noqa: E402
from matplotlib.patches import Rectangle, Polygon, Circle, PathPatch, FancyBboxPatch  # noqa: E402
from matplotlib.path import Path as MPath           # noqa: E402
import numpy as np                                  # noqa: E402

HERE = Path(__file__).resolve().parent
CALC = HERE.parent

plt.rcParams.update({
    "svg.fonttype": "none", "svg.hashsalt": "ccb-r2", "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"], "font.size": 9,
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
    "axes.edgecolor": "#222222", "axes.labelcolor": "#222222", "xtick.color": "#222222", "ytick.color": "#222222",
    "text.color": "#222222", "axes.grid": False, "legend.frameon": True, "legend.framealpha": 1.0,
    "legend.edgecolor": "#999999", "legend.fontsize": 8,
})

# colour classes (one meaning each)
C_I = "#d6e6f7"       # IC-independent block
C_S = "#fde3c4"       # BQ25798-specific block
C_M = "#dcefd5"       # mixed
C_MB = "#ececec"      # motherboard part / node
C_SW = "#cfe0cf"      # RT1987 switch
INK = "#222222"
SIG = "#1f5fa8"       # signal arrows
PWR = "#222222"
SER = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b"]

PNG_DIR = None
OUTPUTS = []


def save(fig, name):
    path = HERE / name
    fig.savefig(path, format="svg", metadata={"Date": None}, bbox_inches="tight", pad_inches=0.08)
    if PNG_DIR is not None:
        fig.savefig(PNG_DIR / (Path(name).stem + ".png"), dpi=110, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)
    OUTPUTS.append(name)


def load(name):
    """Import a calculation script of the parent folder with its console output suppressed."""
    spec = importlib.util.spec_from_file_location(name, CALC / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------------------------------------- diagram helpers
def box(ax, x, y, w, h, text, fc="white", ec=INK, fs=8.5, lw=1.0, ls="-", weight="normal", ha="center",
        va="center", round_=True, color=INK, z=2):
    if round_:
        p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.6", fc=fc, ec=ec, lw=lw, ls=ls,
                           zorder=z)
    else:
        p = Rectangle((x, y), w, h, fc=fc, ec=ec, lw=lw, ls=ls, zorder=z)
    ax.add_patch(p)
    if text:
        tx = x + w / 2 if ha == "center" else x + 0.8
        ty = y + h / 2 if va == "center" else y + h - 0.8
        ax.text(tx, ty, text, ha=ha, va=va, fontsize=fs, weight=weight, color=color, zorder=z + 1,
                linespacing=1.25)
    return p


def arrow(ax, x1, y1, x2, y2, color=PWR, lw=1.6, ls="-", head=True, z=1, ms=9):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>" if head else "-", color=color, lw=lw, ls=ls,
                                shrinkA=0, shrinkB=0, mutation_scale=ms), zorder=z)


def poly_line(ax, pts, color=PWR, lw=1.6, ls="-", head=True, z=1, ms=9):
    xs, ys = zip(*pts)
    ax.plot(xs[:-1], ys[:-1], color=color, lw=lw, ls=ls, zorder=z, solid_capstyle="butt")
    arrow(ax, xs[-2], ys[-2], xs[-1], ys[-1], color=color, lw=lw, ls=ls, head=head, z=z, ms=ms)


def canvas(w, h, xmax, ymax):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, xmax)
    ax.set_ylim(0, ymax)
    ax.set_aspect("equal")
    ax.axis("off")
    return fig, ax


# ======================================================================================================== Figure 1
def fig_power_path():
    fig, ax = canvas(12.0, 7.0, 130, 76)
    ax.text(0, 75.5, "Power path through the CCB, with the inhibit and permit signals (simplified; design §0.1, §1.10-1.12)",
            fontsize=10, weight="bold", va="top")
    ax.add_patch(FancyBboxPatch((53, 12), 76, 57, boxstyle="round,pad=0,rounding_size=1.2", fc="#f7fbff",
                                ec="#5b7fa8", lw=1.2, ls="--", zorder=0))
    ax.text(128, 68.0, "CCB (one 4-layer board in the 22 CHG holes)", ha="right", va="top", fontsize=8.5,
            color="#3d5f88", weight="bold")
    ax.text(1, 68.0, "Motherboard (MB) rev 20260622", fontsize=8.5, color="#555555", weight="bold", va="top")
    # MB sources and switches
    box(ax, 1, 54, 18, 7, "VBUS\n16.0 V nominal", fc=C_MB, fs=7.8)
    box(ax, 1, 43, 18, 7, "D-MT-EN (RT1987)\nMOT_PWR_ENABLE 29", fc=C_SW, fs=7.0)
    box(ax, 1, 32, 18, 7, "V-MOT (VESC node)\n21.2-21.5 V in regen", fc=C_MB, fs=7.0)
    box(ax, 1, 22, 18, 7, "2S pack VBT\n7.4-8.4 V", fc=C_MB, fs=7.8)
    arrow(ax, 10, 54, 10, 50)
    arrow(ax, 10, 43, 10, 39)
    box(ax, 24, 54, 20, 7, "D-BC-FC (RT1987)\nFC_CHARGE_ENABLE 31", fc=C_SW, fs=7.0)
    box(ax, 24, 32, 20, 7, "D-BC-RG (RT1987)\nREGEN_ENABLE 30", fc=C_SW, fs=7.0)
    box(ax, 24, 22, 20, 7, "D-BT-SQ (RT1987)\nBT_SEQUENCE_ENABLE 32", fc=C_SW, fs=7.0)
    arrow(ax, 19, 57.5, 24, 57.5)
    arrow(ax, 19, 35.5, 24, 35.5)
    ax.plot([49, 49], [35.5, 57.5], color=PWR, lw=3.2, zorder=1)
    arrow(ax, 44, 57.5, 49, 57.5)
    arrow(ax, 44, 35.5, 49, 35.5)
    ax.text(49, 59.0, "VCHG-IN\n(MB net)", fontsize=7.0, ha="center", va="bottom")
    box(ax, 55, 43.5, 7, 7, "H301\npad 10", fc="#ffffff", fs=7.0, round_=False)
    arrow(ax, 49, 47, 55, 47)
    box(ax, 66, 43, 21, 8, "U301 TPS26630 eFuse\nI_OL 2.05-2.41 A\nOVP 23.12 V, UVLO 9.91 V\ndV/dt ramp 2.19 V/ms",
        fc=C_I, fs=6.9)
    arrow(ax, 62, 47, 66, 47)
    arrow(ax, 87, 47, 97, 47)
    ax.text(92, 47.6, "VCHGOUT", fontsize=6.8, ha="center", va="bottom")
    box(ax, 97, 40.5, 21, 13, "U501 BQ25798\nbuck-boost, 1.5 MHz\nL501 1.0 uH\nVINDPM: FC 14.5 V,\nregen 18.2-19.0 V",
        fc=C_S, fs=6.9)
    poly_line(ax, [(97, 42.5), (93, 42.5), (93, 25.5), (62, 25.5)])
    ax.text(77.5, 26.2, "BAT -> net VCHG (SYS is local only)", fontsize=6.8, ha="center", va="bottom")
    box(ax, 55, 22, 7, 7, "H301\npads\n18/19", fc="#ffffff", fs=6.6, round_=False)
    arrow(ax, 55, 25.5, 44, 25.5)
    ax.text(49.5, 26.2, "MB VCHG", fontsize=6.6, ha="center", va="bottom")
    arrow(ax, 24, 25.5, 19, 25.5)
    # interlock and charger interface
    box(ax, 63, 13, 29, 10, "Interlock block (IC-independent)\n7 comparators, permit logic,\nheartbeat ARM_OK, pack-OV term OVN",
        fc=C_I, fs=6.8)
    box(ax, 104, 13, 24, 10, "Charger interface block\n(BQ25798-specific)\nU401-U404, Q401-Q403", fc=C_S, fs=6.8)
    arrow(ax, 92, 19.5, 104, 19.5, color=SIG, lw=1.2)
    ax.text(98, 20.0, "CE_DRV,\nILIM_REL,\nRFC_OFF", fontsize=6.0, ha="center", va="bottom", color=SIG)
    arrow(ax, 104, 16, 92, 16, color=SIG, lw=1.2)
    ax.text(98, 15.5, "ILIM_SENSE,\nCE_SENSE", fontsize=6.0, ha="center", va="top", color=SIG)
    arrow(ax, 116, 23, 116, 40.5, color=SIG, lw=1.2)
    ax.text(117, 31.5, "/CE: HIGH\n= inhibit\nILIM_HIZ:\n< 0.75 V =\nconverter off", fontsize=6.3, color=SIG,
            va="center")
    poly_line(ax, [(51, 18), (63, 18)], color=SIG, lw=1.2, ls="--")
    ax.text(50.5, 17.5, "Flying taps F01-F24 (T1-T22): V-MOT, VBUS,\nEN nets of pins 28/30/31, BT current,\n"
            "BQ29200 OUT, heartbeat pin 21, CHG_ARM pin 5", fontsize=6.4, ha="right", va="center", color=SIG)
    # notes row
    ax.text(1, 8.5, "Regen permit H1q: V-MOT >= 1.089 x VBUS (D-MT-EN is then reverse-biased), REGEN proven ON, "
            "FC_CHARGE proven OFF, VBUS above the UVB threshold.\nFC permit H2c: FC_CHARGE proven ON, BT_BUS proven OFF, "
            "BT boost current near zero, bus healthy (or H1 during a brake).\n"
            "VCHG-IN upstream of the eFuse has no current limit in Run; it is short, solder-masked copper only. "
            "Returns: input via pad 4, battery via pads 14/15; pack negative = PCB GND.",
            fontsize=6.7, va="top", color="#5a2a00", linespacing=1.4)
    lx, ly = 66, 64.5
    for i, (fc, t) in enumerate([(C_MB, "MB node"), (C_SW, "MB RT1987 ideal-diode switch (Teensy EN pin)"),
                                 (C_I, "CCB, IC-independent [I]"), (C_S, "CCB, BQ25798-specific [S]")]):
        ax.add_patch(Rectangle((lx + (i % 2) * 28, ly - (i // 2) * 3.4), 2.2, 2.0, fc=fc, ec=INK, lw=0.7))
        ax.text(lx + 3 + (i % 2) * 28, ly + 1.0 - (i // 2) * 3.4, t, fontsize=6.6, va="center")
    save(fig, "fig01_power_path.svg")


# ======================================================================================================== Figure 2
def pin_number(x, y):
    """CHG pad number from its position (design Table 1.1)."""
    if abs(x - 45.998) < 0.5:
        return int(round((y - 39.084) / 2.54)) + 1
    return 11 + int(round((64.484 - y) / 2.54))


def fig_top_view(mech):
    e = mech["elems"]
    fig, ax = plt.subplots(figsize=(13.2, 11.2))
    ax.set_xlim(1, 66)
    ax.set_ylim(22, 92)
    ax.set_aspect("equal")
    ax.set_xlabel("MB x (mm), Eagle top view")
    ax.set_ylabel("MB y (mm)")
    ax.set_title("CCB position on the MB around the CHG footprint, to scale (data: mech_parse_out.json; design §1.2, §1.4, §1.8)",
                 fontsize=9.5, loc="left")
    win = (1, 22, 66, 92)

    def inwin(x, y):
        return win[0] <= x <= win[2] and win[1] <= y <= win[3]

    # non-GND pours (bounding boxes)
    pour_col = {"VCHG": "#f4a259", "VBT": "#e15759", "5V": "#b07aa1", "VFC": "#bab0ac", "VSW-FC": "#bab0ac",
                "VSW-BT": "#bab0ac", "VOUT-BT": "#bab0ac", "VBUS-FC": "#bab0ac", "VBUS-BT": "#bab0ac"}
    for p in mech["polys"]:
        b = p["bb"]
        if p["net"] == "GND" or b[0] > win[2] or b[2] < win[0] or b[1] > win[3] or b[3] < win[1]:
            continue
        col = pour_col.get(p["net"], "#cccccc")
        ax.add_patch(Rectangle((b[0], b[1]), b[2] - b[0], b[3] - b[1], fc=col, alpha=0.25, ec=col, lw=0.6,
                               hatch="////", zorder=1))
    for net, (tx, ty) in {"VCHG": (22.6, 43.5), "5V": (55.5, 53.3), "VSW-FC": (36.2, 86.3), "VFC": (19.5, 87.0),
                          "VOUT-BT": (49.0, 28.6)}.items():
        ax.text(tx, ty, f"{net} pour", fontsize=6.3, color="#6b3a00" if net == "VCHG" else "#4a2a55", zorder=6)
    # selected wires
    wcol = {"VCHG-IN": ("#d95f02", 1.0), "VBT": ("#c0392b", 1.0), "MPPT-DISABLE": ("#1b7837", 0.6),
            "CB-DISABLE": ("#1b7837", 0.6)}
    for w in mech["wires"]:
        if w["net"] in wcol and w["layer"] == 1 and (inwin(w["x1"], w["y1"]) or inwin(w["x2"], w["y2"])):
            c, s = wcol[w["net"]]
            ax.plot([w["x1"], w["x2"]], [w["y1"], w["y2"]], color=c, lw=max(0.6, w["w"] * 2.2 * s),
                    solid_capstyle="round", zorder=3)
    # all parts in the window, light outline
    for name, v in e.items():
        if name == "CHG" or not inwin(v["x"], v["y"]):
            continue
        bb = v["bb"].get("silk") or v["bb"].get("all")
        ax.add_patch(Rectangle((bb[0], bb[1]), bb[2] - bb[0], bb[3] - bb[1], fc="none", ec="#9a9a9a", lw=0.5,
                               zorder=2))
    # key neighbours, labelled
    key = {"REG-5V": ("LM1084 (REG-5V)\n4.83 mm tall, runs hot", "#7f3c8d"), "CO-5V": ("CO-5V\n2.10 mm", "#7f3c8d"),
           "J-BL": ("J-BL\n21.70 mm\n(serviceable)", "#555555"), "J-NTC": ("J-NTC", "#555555"),
           "J-FC": ("J-FC", "#555555"), "L-FC": ("L-FC (height: M7)", "#555555"),
           "OP-FC": ("OP-FC\n1.75 mm", "#555555"), "MDAC-FC": ("MDAC-FC", "#555555"),
           "BAL": ("BAL\n(BQ29200)", "#555555"), "D-BT-SQ": ("D-BT-SQ", "#555555")}
    for name, (lab, col) in key.items():
        v = e[name]
        bb = v["bb"].get("keepout") if name == "REG-5V" else (v["bb"].get("silk") or v["bb"]["all"])
        ax.add_patch(Rectangle((bb[0], bb[1]), bb[2] - bb[0], bb[3] - bb[1], fc="#f2f2f2", ec=col, lw=1.0,
                               zorder=2))
    lm = e["REG-5V"]["bb"]
    ax.add_patch(Rectangle((lm["copper"][0], 46.64), lm["copper"][2] - lm["copper"][0], 54.26 - 46.64,
                           fc="#d9c2e3", ec="#7f3c8d", lw=0.8, zorder=2))
    ax.text(56.6, 50.3, "LM1084 tab", fontsize=6.3, ha="center", zorder=6)
    lab_pos = {"REG-5V": (56.6, 41.5), "CO-5V": (50.8, 35.4), "J-BL": (9.9, 38.0), "J-NTC": (9.9, 60.0),
               "J-FC": (9.9, 80.0), "L-FC": (28.6, 90.4), "OP-FC": (42.4, 79.8), "MDAC-FC": (55.3, 71.7),
               "BAL": (24.4, 24.6), "D-BT-SQ": (30.3, 47.0)}
    for name, (lab, col) in key.items():
        tx, ty = lab_pos[name]
        ax.text(tx, ty, lab, fontsize=6.6, ha="center", va="center", color=col, zorder=6,
                bbox=dict(fc="white", ec="none", pad=0.4, alpha=0.85))
    # CHG footprint and pads
    fp = mech["fp"]
    ax.add_patch(Rectangle((fp[0], fp[1]), fp[2] - fp[0], fp[3] - fp[1], fc="none", ec="#000000", lw=1.0, ls="--",
                           zorder=4))
    for pad in e["CHG"]["pads"]:
        n = pin_number(pad["x"], pad["y"])
        s = 1.65
        hot = n in (4, 10, 14, 15, 18, 19)
        ax.add_patch(Rectangle((pad["x"] - s / 2, pad["y"] - s / 2), s, s, fc="#e0b000" if hot else "#c8c8c8",
                               ec="#333333", lw=0.5, zorder=5))
        dx = 1.5 if pad["x"] > 30 else -1.5
        ax.text(pad["x"] + dx, pad["y"], str(n), fontsize=5.6, ha="left" if dx > 0 else "right", va="center",
                zorder=6)
    # CCB outline: body + tab with the pin-11 chamfer
    out = [(17.70, 34.14), (48.70, 34.14), (48.70, 67.14), (38.90, 67.14), (38.90, 75.40), (37.90, 76.40),
           (17.70, 76.40)]
    ax.add_patch(Polygon(out, closed=True, fc="#5b9bd5", alpha=0.13, ec="#1f4e79", lw=2.0, zorder=4))
    ax.add_patch(Polygon(out, closed=True, fc="none", ec="#1f4e79", lw=2.0, zorder=7))
    ax.add_patch(Rectangle((38.90, 67.14), 9.8, 9.26, fc="none", ec="#1f4e79", lw=1.0, ls=":", zorder=7))
    ax.text(46.9, 75.4, "rect A'\n(reserve)", fontsize=5.6, ha="center", va="center", color="#1f4e79", zorder=8)
    ax.text(28.3, 73.9, "high-y tab (rect A)", fontsize=7.0, ha="center", color="#1f4e79", weight="bold", zorder=8)
    # power cell zone
    ax.add_patch(Rectangle((22.4, 50.4), 15.1, 17.0, fc="#fde3c4", alpha=0.55, ec="#c56a00", lw=1.2, hatch="..",
                           zorder=4))
    ax.text(29.95, 58.5, "power cell\nzone Z-P\n(U501, L501)", fontsize=7.0, ha="center", color="#8a4500",
            weight="bold", zorder=8)
    # feet
    for fx, used in ((23.20, True), (27.70, False), (32.20, True)):
        ax.add_patch(Circle((fx, 70.64), 3.0, fc="none", ec="#1b7837", lw=0.8, ls="--" if not used else "-",
                            zorder=8))
        ax.add_patch(Circle((fx, 70.64), 0.8, fc="#1b7837" if used else "white", ec="#1b7837", lw=0.8, zorder=8))
    ax.annotate("foot spots y 70.64: two used (23.20, 32.20),\none spare (27.70); 3.0 mm part-free circles",
                xy=(32.2, 73.6), xytext=(47.5, 88.5), fontsize=6.3, color="#1b7837", zorder=9,
                bbox=dict(fc="white", ec="#1b7837", pad=1.5, lw=0.5),
                arrowprops=dict(arrowstyle="-", color="#1b7837", lw=0.6))
    # fan, channel, flow
    ax.add_patch(Rectangle((17.70, 27.5), 31.0, 6.0, fc="#e8f1fa", ec="#1f4e79", lw=0.9, ls="--", zorder=4))
    ax.text(33.2, 30.5, "bench fan + duct at the low-y inlet edge (position only; MPN, depth TODO);\n"
            "air enters the channel x 22.33-44.67 and flows along +y", fontsize=6.3,
            ha="center", va="center", color="#1f4e79", zorder=8)
    for x in (22.33, 44.67):
        ax.plot([x, x], [34.14, 67.14 if x > 40 else 76.40], color="#1f4e79", lw=0.7, ls=(0, (2, 2)), zorder=7)
    for x in (29.0, 35.0, 41.0):
        arrow(ax, x, 35.2, x, 45.5, color="#1f77b4", lw=1.6, z=8)
    arrow(ax, 30.0, 76.4, 30.0, 81.0, color="#1f77b4", lw=1.4, z=8)
    arrow(ax, 41.8, 67.14, 41.8, 71.0, color="#1f77b4", lw=1.4, z=8)
    # distance to the LM1084
    ax.annotate("", xy=(50.947, 63.0), xytext=(37.5, 63.0),
                arrowprops=dict(arrowstyle="<->", color="#7f3c8d", lw=0.9), zorder=8)
    ax.plot([50.947, 50.947], [36.0, 66.0], color="#7f3c8d", lw=0.7, ls=":", zorder=7)
    ax.text(44.2, 63.6, "13.4 mm", fontsize=6.6, color="#7f3c8d", ha="center", zorder=8,
            bbox=dict(fc="white", ec="none", pad=0.2, alpha=0.85))
    ax.text(51.4, 64.8, "LM1084\ncourtyard\nx 50.947", fontsize=6.0, color="#7f3c8d", zorder=8)
    # legend
    from matplotlib.lines import Line2D
    hs = [Line2D([], [], color="#1f4e79", lw=2.0, label="CCB outline (body + tab, chamfer marks pin 11)"),
          Line2D([], [], color="#000000", lw=1.0, ls="--", label="CHG (Ag105) silk outline"),
          Rectangle((0, 0), 1, 1, fc="#e0b000", ec="#333333", label="power pads 4, 10, 14, 15, 18, 19"),
          Rectangle((0, 0), 1, 1, fc="#c8c8c8", ec="#333333", label="signal and anchor pads"),
          Line2D([], [], color="#d95f02", lw=2, label="MB VCHG-IN trace"),
          Line2D([], [], color="#c0392b", lw=2, label="MB VBT trace"),
          Line2D([], [], color="#1b7837", lw=1, label="MB MPPT-DISABLE, CB-DISABLE"),
          Rectangle((0, 0), 1, 1, fc="#f4a259", alpha=0.35, hatch="////", ec="#f4a259",
                    label="MB pours (bounding boxes)")]
    ax.legend(handles=hs, loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=7)
    save(fig, "fig02_top_view.svg")


# ======================================================================================================== Figure 3
def fig_side_view():
    fig, (a, b) = plt.subplots(2, 1, figsize=(10.5, 10.6), gridspec_kw=dict(height_ratios=[1.0, 0.92]))
    hu, hu_hi, hu_r1, tpcb, tsh = 5.125, 8.125, 2.54, 1.6, 0.125
    # ---- (a) section along y (flow direction), through the power cell (x about 28)
    a.set_xlim(19, 92)
    a.set_ylim(-3.5, 30)
    a.set_aspect("equal")
    a.set_xlabel("MB y (mm)")
    a.set_ylabel("height above MB top (mm)")
    a.set_title("(a) Section along the flow (+y) through the power cell, x about 28; heights to scale; g = 5 mm shown",
                fontsize=9, loc="left")
    a.add_patch(Rectangle((19, -1.6608), 73, 1.6608, fc="#c7dcc0", ec=INK, lw=0.8))
    a.text(80, -0.85, "MB 1.66 mm", fontsize=7, va="center")
    a.plot([33.14, 77.40], [tsh, tsh], color="#b8860b", lw=1.4)
    a.text(34.0, -2.7, "yellow line: polyimide sheet 0.125 mm on the MB", fontsize=6.3, color="#8a6500",
           va="center")
    a.add_patch(Rectangle((48.5, 0), 5.0, 1.10, fc=C_MB, ec=INK, lw=0.7))
    a.text(53.8, 0.55, "MB parts <= 1.10 mm (D-BT-SQ, C-D11, C-D12)", fontsize=6.0, va="center")
    a.add_patch(Rectangle((76.948, 0), 12.7, 4.0, fc="none", ec="#777777", lw=0.8, ls="--"))
    a.text(83.3, 2.0, "L-FC\n(height TODO, M7)", fontsize=6.3, ha="center", va="center", color="#555555")
    a.add_patch(Rectangle((34.14, hu), 42.26, tpcb, fc="#5b9bd5", ec="#1f4e79", lw=1.2, alpha=0.55))
    top = hu + tpcb
    a.add_patch(Rectangle((51.5, top), 6.5, 3.0, fc=C_S, ec=INK, lw=0.8))
    a.text(54.75, top + 1.5, "L501", fontsize=6.6, ha="center", va="center")
    a.add_patch(Rectangle((63.0, top), 4.0, 1.0, fc=C_S, ec=INK, lw=0.8))
    a.text(65.0, top + 1.6, "U501", fontsize=6.6, ha="center", va="bottom")
    a.text(42.0, hu + 0.8, "CCB 4-layer, 1.6 mm", fontsize=6.4, ha="center", va="center", color="#0d2a47")
    a.add_patch(Rectangle((69.14, tsh), 3.0, hu - tsh, fc="#d9ead3", ec="#1b7837", lw=0.8))
    a.add_patch(Rectangle((68.64, top), 4.0, 0.9, fc="#1b7837", ec="#1b7837"))
    a.annotate("nylon M3 foot spacer at y 70.64,\nlength = H_u, bonded to the MB,\nscrewed from the CCB top",
               xy=(72.1, 3.5), xytext=(84.5, 9.5), fontsize=6.2, ha="center", va="center", color="#1b7837",
               arrowprops=dict(arrowstyle="-", color="#1b7837", lw=0.6))
    a.add_patch(Rectangle((23.0, 2.35), 10.0, 25.0, fc="#eef4fb", ec="#1f4e79", lw=0.9, ls="--"))
    a.text(28.0, 15.0, "bench fan\n25-30 mm\nframe class\n(MPN, depth\nTODO)", fontsize=6.4, ha="center",
           va="center", color="#1f4e79")
    a.text(28.0, 1.2, "frame edge >= 2.35 mm", fontsize=5.6, ha="center", color="#1f4e79")
    for z in (2.0, 3.8):
        arrow(a, 33.5, z, 45.0, z, color="#1f77b4", lw=1.4)
    for z in (top + 4.0, top + 7.0):
        arrow(a, 33.5, z, 76.0, z, color="#1f77b4", lw=1.4)
    arrow(a, 76.4, 3.0, 79.6, 3.0, color="#1f77b4", lw=1.2)
    a.text(35.0, top + 8.6, "top stream about 10 mm deep (assumed in [LC] §8.9); outlet at the tab end y 76.40",
           fontsize=6.4, color="#1f77b4")
    a.text(34.0, 4.5, "gap flow", fontsize=6.0, color="#1f77b4")
    a.annotate("", xy=(47.0, tsh), xytext=(47.0, hu), arrowprops=dict(arrowstyle="<->", color=INK, lw=0.8))
    a.text(47.4, 2.8, "g = H_u - 0.125 mm", fontsize=6.0, va="center")
    a.text(91.5, 29.5, "Header strips at x 21.0 and x 46.0 run along y\nand form the side walls of the channel (panel b).",
           fontsize=6.4, ha="right", va="top", color="#8c564b")
    # ---- (b) section across x at y 49.0
    b.set_xlim(0, 66)
    b.set_ylim(-3.5, 25)
    b.set_aspect("equal")
    b.set_xlabel("MB x (mm)")
    b.set_ylabel("height above MB top (mm)")
    b.set_title("(b) Section across the board at y 49.0 (pins 5 and 17); heights to scale; air flows into the page",
                fontsize=9, loc="left")
    b.add_patch(Rectangle((0, -1.6608), 66, 1.6608, fc="#c7dcc0", ec=INK, lw=0.8))
    b.add_patch(Rectangle((3.255, 0), 16.405 - 3.255, 21.70, fc=C_MB, ec=INK, lw=0.8))
    b.text(9.8, 11.0, "J-BL\nterminal block\n21.70 mm\n(screws from\nabove)", fontsize=6.4, ha="center", va="center")
    b.add_patch(Rectangle((51.499, 0), 61.785 - 51.499, 4.83, fc="#e5d4ec", ec="#7f3c8d", lw=0.9))
    b.text(56.6, 2.4, "LM1084\n4.83 mm", fontsize=6.4, ha="center", va="center", color="#5c2a66")
    b.plot([50.947, 50.947], [0, 12], color="#7f3c8d", lw=0.7, ls=":")
    b.text(51.2, 11.2, "LM1084 courtyard x 50.947", fontsize=5.9, color="#7f3c8d")
    for x0, x1 in ((25.052, 27.272), (27.543, 32.418), (33.18, 35.4)):
        b.add_patch(Rectangle((x0, 0), x1 - x0, 1.10, fc=C_MB, ec=INK, lw=0.6))
    b.text(33.4, -2.6, "C-D11, D-BT-SQ, C-D12 (<= 1.10 mm)", fontsize=6.0, ha="center", va="center")
    b.plot([17.7, 48.7], [tsh, tsh], color="#b8860b", lw=1.4)
    # CCB r2, r2 band top and r1
    b.add_patch(Rectangle((17.70, hu), 31.0, tpcb, fc="#5b9bd5", ec="#1f4e79", lw=1.2, alpha=0.55))
    b.add_patch(Rectangle((17.70, hu_hi), 31.0, tpcb, fc="none", ec="#1f4e79", lw=0.8, ls=":"))
    b.add_patch(Rectangle((17.70, hu_r1), 31.0, tpcb, fc="none", ec="#999999", lw=0.9, ls="--"))
    b.text(33.2, hu + 0.8, "CCB, H_u 5.125 mm (g 5 mm)", fontsize=6.5, ha="center", va="center", color="#0d2a47")
    b.text(23.0, hu_hi + 0.8, "g 8 mm (H_u 8.125 mm), top of the recommended band", fontsize=5.8, va="center",
           color="#1f4e79")
    b.text(42.0, hu_r1 + 0.8, "r1: H_u 2.54 mm", fontsize=5.9, ha="center", va="center", color="#777777")
    # header columns (option K: socket + male body)
    hk = hu - 2.54
    for x in (20.998, 45.998):
        b.add_patch(Rectangle((x - 1.27, 0), 2.54, hk, fc="#e6d3c6", ec="#8c564b", lw=0.8))
        b.add_patch(Rectangle((x - 1.27, hk), 2.54, 2.54, fc="#f3e7de", ec="#8c564b", lw=0.8))
        b.plot([x, x], [-2.66, hu + tpcb + 1.5], color="#8c564b", lw=1.6)
    b.text(20.998, -3.0, "pin 17", fontsize=6.0, ha="center", va="center")
    b.text(45.998, -3.0, "pin 5", fontsize=6.0, ha="center", va="center")
    b.annotate("option K: socket h_k + 2.54 mm male body = H_u", xy=(45.998 + 1.3, 1.5), xytext=(38.0, 15.5),
               fontsize=6.3, color="#8c564b", arrowprops=dict(arrowstyle="-", color="#8c564b", lw=0.6))
    for x in (27.0, 33.0, 40.0):
        b.plot(x, 1.9, marker="o", ms=7, mfc="white", mec="#1f77b4", mew=1.2)
        b.plot(x, 1.9, marker=".", ms=4, color="#1f77b4")
    for x in (26.0, 33.0, 40.0):
        b.plot(x, hu + tpcb + 5.6, marker="o", ms=7, mfc="white", mec="#1f77b4", mew=1.2)
        b.plot(x, hu + tpcb + 5.6, marker=".", ms=4, color="#1f77b4")
    b.text(48.9, 6.0, "right edge x 48.70:\n2.86 mm to the\nLM1084 body", fontsize=6.0, va="bottom")
    b.text(17.4, 8.4, "left edge\nx 17.70", fontsize=6.0, ha="right")
    # rule box
    b.text(66.0, 24.6, "r1 rule: H_u + t_pcb + h_top <= H_env (still air, closed 2.415 mm layer)\n"
           "r2 rule 1: H_u >= h_mb + t_bot + g_air (g_air >= 1.0 mm)\n"
           "r2 rule 3: g >= 5 mm, 5-8 mm recommended (H_u 5.1-8.1 mm)\n"
           "r2: no height restriction; H_env is record only",
           fontsize=6.6, ha="right", va="top", bbox=dict(fc="white", ec="#999999", pad=3))
    fig.tight_layout()
    save(fig, "fig03_side_view.svg")


# ======================================================================================================== Figure 4
def fig_block_diagram():
    fig, ax = canvas(11.5, 7.4, 115, 74)
    ax.text(0, 73.5, "CCB block diagram with the IC-independent [I] and BQ25798-specific [S] content (design §1.10, Figure 1.10)",
            fontsize=10, weight="bold", va="top")
    # MB column
    box(ax, 0, 4, 21, 64, "", fc=C_MB, round_=True)
    ax.text(10.5, 66.5, "MB and Teensy", fontsize=8.5, weight="bold", ha="center", va="top")
    mb_rows = [(60, "VCHG-IN (D-BC-FC, D-BC-RG)"), (55, "MB VCHG -> D-BT-SQ -> pack"),
               (51, "GND: pads 4, 14, 15"), (47, "SDA/SCL Teensy 18/19 (2.7k)"),
               (43, "J-NTC pin 1 (TS_EXT)"), (39, "Teensy 6 <- STAT"), (35, "Teensy 5 CHG_ARM (P5)"),
               (25, "Taps T1-T22: V-MOT, VBUS,\nEN pins 28/30/31, BT current,\nBQ29200 OUT, HB 21, QUAL 10,\nFCCEIL 17"),
               (11, "Readbacks to Teensy 16, 22,\n23, 33, 34, 35 and 7")]
    for y, t in mb_rows:
        ax.text(1.0, y, t, fontsize=6.8, va="center")
    # header block
    box(ax, 23, 33, 7, 31, "H301\nheader\n[I]\n\n22 pads:\n11 nets,\n11\nanchors", fc=C_I, fs=7.0)
    # links MB -> header
    for y, lab in ((60, "10"), (55, "18/19"), (51, "4/14/15"), (47, "7/8"), (43, "13"), (39, "3"), (35, "11")):
        ax.plot([20.2, 23], [y, y], color=PWR if y >= 51 else SIG, lw=1.4 if y >= 51 else 0.9)
        ax.text(21.6, y + 0.6, lab, fontsize=5.8, ha="center", va="bottom")
    # input protection
    box(ax, 34, 54, 22, 12, "Input protection [I]\nU301 TPS26630 eFuse\nC302a/b/c, D307 TVS,\nC303, D303\n"
        "VCHGIN -> VCHGOUT", fc=C_I, fs=6.6)
    arrow(ax, 30, 60, 34, 60)
    # power stage
    box(ax, 62, 47, 30, 19, "Power stage [S]\nU501 BQ25798 (RQM, 4 x 4 mm)\nL501 1.0 uH, PROG R529 6.04 k\n"
        "VBUS 2 x 10 uF 50 V, PMID 3 x 10 uF 50 V\nSYS 5 x 10 uF, BAT 2 x 10 uF\nSDRV 1 nF to GND, BATP via 100 R",
        fc=C_S, fs=6.5)
    arrow(ax, 56, 60, 62, 60)
    ax.text(59, 61.0, "VCHGOUT", fontsize=6.0, ha="center", va="bottom")
    poly_line(ax, [(70, 47), (70, 44), (32, 44), (32, 55), (30, 55)])
    ax.text(50, 44.6, "BAT -> net VCHG -> pads 18/19", fontsize=6.5, ha="center", va="bottom")
    # I2C, TS, STAT direct to U501
    poly_line(ax, [(30, 47), (33, 47), (33, 50.5), (62, 50.5)], color=SIG, lw=0.9)
    ax.text(45, 51.0, "SDA/SCL, TS_EXT (direct, no board pull-ups)", fontsize=6.0, va="bottom", color=SIG)
    # charger interface block
    box(ax, 62, 22, 30, 19, "Charger interface block [S]\n(ex-EIB stages, now local)\nU401 SN74LVC3G06 (/CE, Q403, Q402)\n"
        "U402 (Q401 hold)\nQ401 hold, Q402 FC leg, Q403 feed\nR472, R472b 47 k to REGN\nU403 ILIM sense, U404 /CE sense",
        fc=C_S, fs=6.5)
    arrow(ax, 75, 41, 75, 47, color=SIG, lw=1.2)
    ax.text(75.8, 43.7, "/CE, ILIM_HIZ", fontsize=6.3, color=SIG)
    # interlock block
    box(ax, 34, 6, 22, 35, "", fc=C_I)
    ax.text(45, 39.5, "Interlock block [I]", fontsize=7.8, weight="bold", ha="center", va="top")
    ax.text(35.0, 36.5, "7 comparators U302-U304, U315,\nU319-U321 (H1, UVB, BT_OK,\nBTB_OFF, FCC_OFF/ON, RGN_ON)\n\n"
            "permit logic U305-U310, U314,\nU316, U318, U322\n\nheartbeat monostable U313\n(ARM_OK, 20-46 ms)\n\n"
            "pack-OV input U323 (OVN)\n\ntap field F01-F24", fontsize=6.6, va="top")
    box(ax, 36, 7, 18, 4.2, "U311 QUAL one-shot [S]", fc=C_S, fs=6.6)
    # header -> interlock
    arrow(ax, 33.5, 39, 30, 39, color=SIG, lw=0.9)
    ax.text(30.3, 42.0, "pad 3 STAT <- U501 (R475)", fontsize=5.8, color=SIG, va="center")
    poly_line(ax, [(30, 35), (31, 35), (31, 30), (34, 30)], color=SIG, lw=0.9)
    # taps bypass the header
    poly_line(ax, [(20.2, 25), (34, 25)], color=SIG, lw=1.0, ls="--")
    ax.text(27, 25.6, "flying taps\n(not via H301)", fontsize=5.9, ha="center", va="bottom", color=SIG)
    poly_line(ax, [(34, 12), (21, 12)], color=SIG, lw=1.0, ls="--")
    # contract band
    ax.add_patch(Rectangle((56.6, 22), 4.8, 19, fc="#fff7d6", ec="#b08900", lw=0.8, ls="--"))
    ax.text(59.0, 31.5, "interface contract (§1.10.2, §1.14)", fontsize=6.0, rotation=90, ha="center", va="center",
            color="#7a5d00")
    arrow(ax, 56, 37, 62, 37, color=SIG, lw=1.2)
    arrow(ax, 56, 33, 62, 33, color=SIG, lw=1.2)
    arrow(ax, 56, 29, 62, 29, color=SIG, lw=1.2)
    arrow(ax, 62, 25.5, 56, 25.5, color=SIG, lw=1.2)
    ax.text(93.5, 38, "commands (fail-safe LOW):\nCE_DRV, ILIM_REL, RFC_OFF\n\nsenses: ILIM_SENSE, CE_SENSE,\nSTAT",
            fontsize=6.6, va="top")
    # legend and IC-change note
    lx, ly = 93.5, 18
    for i, (fc, t) in enumerate([(C_I, "[I] carries over to any IC that\n     meets the §1.14 contract"),
                                 (C_S, "[S] redesigned for another IC"), (C_MB, "MB side")]):
        ax.add_patch(Rectangle((lx, ly - i * 5.0), 2.4, 2.2, fc=fc, ec=INK, lw=0.7))
        ax.text(lx + 3.2, ly + 1.1 - i * 5.0, t, fontsize=6.6, va="center")
    ax.text(93.5, 64, "Ground: one plane (GND).\nInput loop returns to pad 4;\nbattery loop to pads 14/15;\n"
            "quiet returns join the plane\naway from both paths (§1.13).", fontsize=6.6, va="top")
    save(fig, "fig04_block_diagram.svg")


# ======================================================================================================== Figure 5
def gate(ax, kind, x, y, ins, out, h=None, L=6.0, lab_w=0.4, fs=6.4, fc="#ffffff"):
    n = len(ins)
    h = h if h is not None else max(3.0, 1.7 * n)
    if kind == "AND":
        w = L - h / 2
        th = np.linspace(-np.pi / 2, np.pi / 2, 30)
        verts = [(x, y - h / 2), (x + w, y - h / 2)] + [(x + w + h / 2 * np.cos(t), y + h / 2 * np.sin(t)) for t in th] \
            + [(x, y + h / 2), (x, y - h / 2)]
        ax.add_patch(Polygon(verts, closed=True, fc=fc, ec=INK, lw=1.0, zorder=3))
        xin = x
    else:
        verts = [(x, y - h / 2), (x + 0.3 * h, y), (x, y + h / 2), (x + 0.55 * L, y + h / 2), (x + L, y),
                 (x + 0.55 * L, y - h / 2), (x, y - h / 2), (x, y - h / 2)]
        codes = [MPath.MOVETO, MPath.CURVE3, MPath.CURVE3, MPath.CURVE3, MPath.CURVE3, MPath.CURVE3, MPath.CURVE3,
                 MPath.CLOSEPOLY]
        ax.add_patch(PathPatch(MPath(verts, codes), fc=fc, ec=INK, lw=1.0, zorder=3))
        xin = x + 0.12 * h
    ax.text(x + L * 0.42, y, kind, fontsize=5.4, ha="center", va="center", color="#666666", zorder=4)
    pitch = h / (n + 1)
    pins = []
    for i, name in enumerate(ins):
        yy = y + h / 2 - pitch * (i + 1)
        ax.plot([x - 1.6, xin], [yy, yy], color=INK, lw=0.8, zorder=2)
        ax.text(x - 1.8, yy, name, fontsize=fs, ha="right", va="center", zorder=4)
        pins.append((x - 1.6, yy))
    ax.plot([x + L, x + L + 1.6], [y, y], color=INK, lw=0.8, zorder=2)
    ax.text(x + L + 1.8, y, out, fontsize=fs + 0.4, ha="left", va="center", weight="bold", zorder=4)
    return (x + L + 1.6, y), pins


def fig_permit_logic():
    fig, ax = canvas(11.5, 7.6, 120, 78)
    ax.text(0, 77.5, "Permit logic of the interlock block as gates (design §1.10.1, §1.12; round-3 [WD] B.3 equations)",
            fontsize=10, weight="bold", va="top")
    # inputs table
    rows = [("H1", "U302", "V-MOT > 1.089 x VBUS"), ("UVB", "U303", "VBUS > 13.33 / 13.72 V"),
            ("BT_OK", "U304", "BT INA253 output < 19.75 mV"), ("BTB_OFF", "U315", "BT_BUS EN (pin 28) < REF/3"),
            ("FCC_OFF = FCCN", "U319", "FC_CHARGE EN (pin 31) off"), ("FCC_ON", "U320", "FC_CHARGE EN (pin 31) on"),
            ("RGN_ON", "U321", "REGEN EN (pin 30) on"), ("FCI_OK", "U317 / R337", "FC current option (DNP: link)"),
            ("FCCEIL", "U316 input", "Teensy pin 17"), ("QQ", "U311 [S]", "QUAL one-shot 0.20-0.46 s, pin 10"),
            ("ARM_OK", "U313", "heartbeat pin 21, tw 20-46 ms"), ("OVN", "U323", "BQ29200 OUT (pack OV)"),
            ("P5", "R308 pull-down", "CHG_ARM, Teensy pin 5")]
    ax.text(0, 71.5, "Inputs", fontsize=8.5, weight="bold")
    for i, (n, ref, mean) in enumerate(rows):
        yy = 68.5 - i * 4.2
        ax.text(0, yy, n, fontsize=7.0, weight="bold", va="center")
        ax.text(14.5, yy, ref, fontsize=6.5, va="center", color="#555555")
        ax.text(0, yy - 1.7, mean, fontsize=6.3, va="center", color="#333333")
    ax.plot([29.5, 29.5], [6, 72], color="#bbbbbb", lw=0.8)
    # column 1
    gate(ax, "AND", 41, 68, ["H1", "RGN_ON"], "H1R")
    gate(ax, "AND", 41, 59, ["H1", "RGN_ON", "FCC_OFF", "UVB"], "H1q")
    gate(ax, "AND", 41, 49, ["UVB", "FCCEIL"], "UF")
    gate(ax, "AND", 41, 41, ["QQ", "FCCN"], "QQF  [S]")
    gate(ax, "AND", 41, 31, ["ARM_OK", "OVN"], "ARM_OK'")
    gate(ax, "OR", 41, 21, ["FCCN", "H1R"], "RFC_OFF")
    # column 2
    gate(ax, "OR", 64, 49, ["UF", "H1R"], "X")
    gate(ax, "AND", 64, 37, ["FCC_ON", "BTB_OFF", "BT_OK", "FCI_OK", "X"], "H2c")
    gate(ax, "OR", 64, 61, ["H1q", "H2c"], "GATE")
    # column 3
    gate(ax, "OR", 86, 61, ["GATE", "QQF"], "ILIM_PRE")
    gate(ax, "AND", 86, 46, ["P5", "ARM_OK'"], "CE_DRV")
    gate(ax, "AND", 86, 34, ["ILIM_PRE", "ARM_OK'"], "ILIM_REL")
    # outputs to the charger interface block
    out_rows = ["CE_DRV HIGH: U401 ch1 sinks /CE (charge enabled). LOW: /CE held HIGH (inhibit) by R472 and R472b to REGN.",
                "ILIM_REL HIGH: U401 ch2 turns the Q403 feed on and U402 turns the Q401 hold off. LOW: ILIM_HIZ < 0.75 V "
                "(converter off).",
                "RFC_OFF HIGH: U401 ch3 turns Q402 off and removes the FC clamp leg R457. LOW: FC clamp 0.65-0.95 A in force."]
    ax.add_patch(FancyBboxPatch((40, 2), 79, 13.5, boxstyle="round,pad=0,rounding_size=0.8", fc=C_S, ec=INK, lw=0.8))
    ax.text(41, 14.6, "Charger interface block [S]: what each command does at U501", fontsize=7.3, weight="bold",
            va="top")
    for i, t in enumerate(out_rows):
        ax.text(41, 11.0 - i * 3.0, t, fontsize=6.4, va="top")
    ax.text(100, 27, "Fail-safe levels (§1.10.2,\nTable 2.8): comparator\noutputs are LOW at POR;\neach command LOW is\n"
            "the safe state. An\nunpowered U401 floats:\n/CE HIGH, Q403 off,\nQ402 on.",
            fontsize=6.4, va="top", bbox=dict(fc="white", ec="#999999", pad=3))
    save(fig, "fig05_permit_logic.svg")


# ======================================================================================================== Figure 6
PKG = {"0402": (1.0, 0.5), "0402L": (1.0, 0.5), "0603": (1.6, 0.8), "0805_HV": (2.0, 1.25), "0805": (2.0, 1.25)}
CCB_REF = {"C11": "C532", "C12": "C518", "C10": "C529", "C9": "C530", "C8": "C531", "C13": "C519", "C14": "C520",
           "C15": "C521", "C16": "C522", "C17": "C523", "C1": "C506", "C7": "C508", "C6": "C513", "C18": "C535",
           "C20": "C538", "C21": "C539", "C22": "C536", "R1": "R515"}


def parse_tida(path):
    txt = path.read_text(encoding="utf-8", errors="replace")
    parts, flashes, holes = [], [], []
    sec = txt.split("Parts within 12 mm of U1")[1].split("=====")[0]
    for m in re.finditer(r"^\s+(\S+)\s+(\S+)\s+(TOP|BOTTOM|MID2)\s+(\d+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+[\d.]+\s*$", sec,
                         re.M):
        parts.append(dict(ref=m.group(1), pkg=m.group(2), side=m.group(3), rot=int(m.group(4)),
                          x=float(m.group(5)), y=float(m.group(6))))
    sec = txt.split("U1 flashes on GTL")[1].split("count:")[0]
    for m in re.finditer(r"^\s+(-?[\d.]+)\s+(-?[\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(D\d+)\s+(\S+)", sec, re.M):
        flashes.append(dict(x=float(m.group(1)), y=float(m.group(2)), w=float(m.group(3)), h=float(m.group(4)),
                            ap=m.group(5), kind=m.group(6)))
    sec = txt.split("All holes in the window")[1].split("=====")[0]
    for m in re.finditer(r"\(\s*(-?[\d.]+),\s*(-?[\d.]+)\)\s+([\d.]+)", sec):
        holes.append((float(m.group(1)), float(m.group(2)), float(m.group(3))))
    return parts, flashes, holes


def fig_floor_and_cell(tida):
    fig, (a, b) = plt.subplots(1, 2, figsize=(12.5, 7.6), gridspec_kw=dict(width_ratios=[1.0, 1.08]))
    # ---- (a) floor plan
    a.set_xlim(15.5, 51.5)
    a.set_ylim(33.0, 78.5)
    a.set_aspect("equal")
    a.set_xlabel("MB x (mm)")
    a.set_ylabel("MB y (mm)")
    a.set_title("(a) Floor plan on the CCB outline (Table 3.4, Table 3.9a)", fontsize=9, loc="left")
    out = [(17.70, 34.14), (48.70, 34.14), (48.70, 67.14), (38.90, 67.14), (38.90, 75.40), (37.90, 76.40),
           (17.70, 76.40)]
    a.add_patch(Polygon(out, closed=True, fc="white", ec="#1f4e79", lw=1.8, zorder=1))
    zones = [((22.4, 50.4, 37.5, 67.4), C_S, ""),
             ((37.5, 50.4, 44.6, 61.6), C_S, "Z-D drivers,\npin senses [S]"),
             ((37.5, 61.6, 44.6, 67.14), C_I, "Z-E eFuse\nU301 [I]"),
             ((44.3, 63.4, 48.2, 66.64), C_I, ""),
             ((25.4, 42.1, 44.6, 50.4), C_I, ""),
             ((22.4, 42.13, 25.4, 50.4), "#fbe3e3", ""),
             ((23.15, 35.05, 42.43, 41.63), C_I, ""),
             ((17.7, 67.14, 38.9, 76.40), C_S, "")]
    for (x0, y0, x1, y1), fc, t in zones:
        a.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fc=fc, ec="#666666", lw=0.7, zorder=2))
        if t:
            a.text((x0 + x1) / 2, (y0 + y1) / 2 + (2.6 if "Z-P" in t else 0), t, fontsize=6.4, ha="center",
                   va="center", zorder=6)
    a.text(30.0, 74.6, "Z-C tab: charger-pin passives [S]", fontsize=6.4, ha="center", zorder=6)
    a.text(23.9, 46.3, "VCHG\ncorridor\n(L-12)", fontsize=5.4, ha="center", va="center", zorder=6, color="#8a1c1c")
    a.text(33.0, 34.62, "Z-T tap field F01-F24 [I]", fontsize=5.4, ha="center", va="center", zorder=6)
    a.text(34.6, 56.0, "Z-P\npower\ncell [S]", fontsize=6.2, ha="center", va="center", zorder=6)
    a.text(30.4, 44.0, "Z-Q comparators, permit logic,\nmonostables [I]", fontsize=6.0, ha="center", va="center",
           zorder=6)
    for k in range(8):
        for yy in (35.80, 38.34, 40.88):
            a.add_patch(Rectangle((23.90 + k * 2.54 - 0.6, yy - 0.6), 1.2, 1.2, fc="#b0b0b0", ec="#555555", lw=0.4,
                                  zorder=4))
    # header pads and keep-outs
    for x in (20.998, 45.998):
        ys = np.arange(36.544, 64.49, 2.54) if x < 30 else np.arange(39.084, 61.95, 2.54)
        a.add_patch(Rectangle((x - 1.33, ys[0] - 1.1), 2.66, ys[-1] - ys[0] + 2.2, fc="none", ec="#8c564b", lw=0.6,
                              ls="--", zorder=3))
        for yy in ys:
            a.add_patch(Rectangle((x - 0.825, yy - 0.825), 1.65, 1.65, fc="#e0b000", ec="#333333", lw=0.4, zorder=4))
    # E-SW envelope, U501, L501
    a.add_patch(Rectangle((24.65, 51.5), 31.75 - 24.65, 65.35 - 51.5, fc="none", ec="#c00000", lw=1.4, ls="-",
                          zorder=5))
    a.add_patch(Rectangle((24.65, 51.5), 7.1, 6.5, fc="#f6c6a0", ec=INK, lw=0.7, zorder=4))
    a.text(28.2, 54.75, "L501", fontsize=6.4, ha="center", va="center", zorder=6)
    a.add_patch(Rectangle((28.2 - 2.45, 65.0 - 2.45), 4.9, 4.9, fc="#f6c6a0", ec=INK, lw=0.7, zorder=4))
    a.text(28.2, 65.0, "U501", fontsize=6.0, ha="center", va="center", zorder=6)
    a.text(28.2, 60.3, "E-SW: all\nSW1/SW2 copper", fontsize=5.4, color="#c00000", ha="center", va="center", zorder=6)
    th = np.linspace(0, 0.5 * np.pi, 80)
    for r, ls in ((10.0, "-"), (5.0, ":")):
        xs, ys = 31.75 + r * np.cos(th), 51.5 - r * np.sin(th)
        sel = (ys >= 42.1) & (ys <= 50.4)
        a.plot(xs[sel], ys[sel], color="#c00000", lw=0.9, ls=ls, zorder=6)
    a.text(42.2, 44.6, ">= 10 mm\n(Q10-T)", fontsize=5.6, color="#c00000", ha="center", zorder=6)
    a.text(36.6, 47.6, "5 mm", fontsize=5.6, color="#c00000", zorder=6)
    # feet, fan-mount holes
    for fx in (23.20, 32.20):
        a.add_patch(Circle((fx, 70.64), 3.0, fc="white", ec="#1b7837", lw=0.8, zorder=5))
        a.add_patch(Circle((fx, 70.64), 0.8, fc="#1b7837", ec="#1b7837", zorder=6))
    for fx in (26.70, 37.70):
        a.add_patch(Circle((fx, 36.14), 0.6, fc="white", ec="#1f4e79", lw=0.8, zorder=6))
    a.plot([50.947, 50.947], [33.0, 78.5], color="#7f3c8d", lw=0.8, ls=":")
    a.text(50.6, 77.5, "LM1084\ncourtyard", fontsize=5.8, color="#7f3c8d", ha="right", va="top")
    # ---- (b) power cell from TIDA-050047
    parts, flashes, holes = tida
    b.set_xlim(-10.8, 10.8)
    b.set_ylim(-4.6, 15.8)
    b.set_aspect("equal")
    b.set_xlabel("cell x (mm), TI orientation")
    b.set_ylabel("cell y (mm); power-pad edge at +y")
    b.set_title("(b) Power-loop placement copied from TIDA-050047 (§3.4, Table 3.8a/3.8b)", fontsize=9, loc="left")
    b.add_patch(Rectangle((-2.0, -2.0), 4.0, 4.0, fc="#f0f0f0", ec=INK, lw=0.9, zorder=2))
    for f in flashes:
        if f["kind"].startswith("Aperture"):
            b.add_patch(Rectangle((f["x"] - f["w"] / 2, f["y"] - f["h"] / 2), f["w"], f["h"], fc="#d4a017",
                                  ec="#7a5c00", lw=0.3, zorder=3))
    for x, y, d in holes:
        land = 0.762 if d > 0.3 else 0.508
        b.add_patch(Circle((x, y), land / 2, fc="#ffffff", ec="#444444", lw=0.6, zorder=4))
        b.add_patch(Circle((x, y), d / 2, fc="#444444", ec="none", zorder=5))
    for f in flashes:
        if f["kind"] == "CircleAperture" and f["w"] > 0.45:
            b.add_patch(Circle((f["x"], f["y"]), f["w"] / 2, fc="#ffffff", ec="#444444", lw=0.6, zorder=4))
    # TIDA inductor (L4) and CCB L501 (L1)
    b.add_patch(Rectangle((-5.49 / 2, 7.0 - 5.18 / 2), 5.49, 5.18, fc="none", ec="#777777", lw=0.9, ls="--",
                          zorder=2))
    b.add_patch(Rectangle((-3.55, 7.0), 7.1, 6.5, fc="#f6c6a0", ec=INK, lw=0.9, alpha=0.55, zorder=2))
    b.text(0, 12.6, "CCB L501 on L1 (7.1 x 6.5 mm, body y +7.0..+13.5)", fontsize=6.2, ha="center", zorder=7)
    b.text(0, 9.75, "TIDA L1 on L4 (dashed)", fontsize=5.8, ha="center", color="#555555", zorder=7)
    for p in parts:
        if p["ref"] in ("U1", "L1") or p["pkg"] not in PKG:
            continue
        w, h = PKG[p["pkg"]]
        if p["rot"] % 180 == 90:
            w, h = h, w
        top = p["side"] == "TOP"
        ref = CCB_REF.get(p["ref"])
        b.add_patch(Rectangle((p["x"] - w / 2, p["y"] - h / 2), w, h, fc=C_S if (ref and top) else "white",
                              ec="#1f4e79" if ref else "#999999", lw=0.8, ls="-" if top else "--", zorder=6))
        lab = ref if ref else f"({p['ref']})"
        b.text(p["x"], p["y"] + h / 2 + 0.15, lab, fontsize=4.9 if ref else 4.6, ha="center", va="bottom",
               color=INK if ref else "#888888", zorder=7, rotation=90 if p["rot"] % 180 == 90 else 0)
    b.text(-10.5, -3.0, "TIDA C2-C5 VBUS row: on the CCB,\nC511/C512 move to the VCHGOUT run", fontsize=5.6,
           va="top", color="#555555")
    b.text(-1.0, -4.1, "control edge: /CE 13, SCL 14, SDA 15 ...", fontsize=5.8, ha="center", color="#555555")
    b.text(-10.5, 15.4, "SW1 / SW2: 4 vias 0.254 mm per node under the body -> L3 strips -> 3 vias 0.381 mm per "
           "inductor terminal", fontsize=5.6, va="top")
    b.text(-10.5, 14.6, "solid outline: L1 (top); dashed: L4 (bottom); grey refs: TIDA parts without a CCB role",
           fontsize=5.6, va="top", color="#555555")
    b.text(-2.1, 2.45, "PMID SW1 GND SW2 SYS", fontsize=5.0, va="bottom", color="#7a5c00")
    fig.tight_layout()
    save(fig, "fig06_floor_plan_and_power_cell.svg")


# ======================================================================================================== Figure 7
def fig_thermal_velocity(lc):
    vs = np.arange(1.0, 4.001, 0.25)
    gaps = (3e-3, 5e-3, 8e-3, 12e-3)
    fig, axs = plt.subplots(1, 3, figsize=(13.0, 4.6), gridspec_kw=dict(width_ratios=[1, 1, 1.05]))
    for ax, mode, title in ((axs[0], "both", "(a) Fan on, gap and top at the same velocity"),
                            (axs[1], "gap", "(b) Fan on, gap only (top in still air)")):
        for g, c in zip(gaps, SER):
            lo, hi = [], []
            for v in vs:
                ht = lc.h_flat(v, lc.L_TOP)[1] + lc.H_RAD_TOP if mode == "both" else lc.H_TOP_STILL
                r = lc.tj_band(2.7, g, "duct", v, h_top=ht)
                lo.append(r[2])
                hi.append(r[3])
            ax.fill_between(vs, lo, hi, color=c, alpha=0.06, lw=0)
            ax.plot(vs, lo, color=c, lw=1.3)
            ax.plot(vs, hi, color=c, lw=1.3, ls="--")
            ax.plot([], [], color=c, lw=6, alpha=0.4, label=f"g {g*1e3:.0f} mm")
        ax.axhline(75, color="#c00000", lw=1.0, ls="-.")
        ax.text(4.0, 76, "T_J 100 C on a 25 C bench", fontsize=7, color="#c00000", ha="right", va="bottom")
        ax.set_xlabel("air velocity (m/s)")
        ax.set_title(title, fontsize=9, loc="left")
        ax.set_xlim(1, 4)
        ax.set_ylim(35, 105)
        ax.grid(True, color="#e5e5e5", lw=0.6)
    axs[0].set_ylabel("T_J - T_air at 2.7 W (C)")
    axs[0].legend(loc="upper right", title="band: solid = low,\ndashed = high", title_fontsize=7)
    # (c) gap selection at 2 m/s
    ax = axs[2]
    gs = np.arange(2.5, 12.01, 0.5) * 1e-3
    ht2 = lc.h_flat(2.0, lc.L_TOP)[1] + lc.H_RAD_TOP
    for mode, c, lab in (("both", SER[0], "fan on, both sides, 2 m/s"), ("gap", SER[2], "fan on, gap only, 2 m/s"),
                         ("off", SER[1], "fan off (still air + radiation)")):
        lo, hi = [], []
        for g in gs:
            if mode == "off":
                r = lc.tj_band(2.7, g, "still")
            else:
                r = lc.tj_band(2.7, g, "duct", 2.0, h_top=ht2 if mode == "both" else lc.H_TOP_STILL)
            lo.append(r[2])
            hi.append(r[3])
        ax.fill_between(gs * 1e3, lo, hi, color=c, alpha=0.15, lw=0)
        ax.plot(gs * 1e3, lo, color=c, lw=1.3)
        ax.plot(gs * 1e3, hi, color=c, lw=1.3, ls="--", label=lab)
    ax.axvspan(5, 8, color="#999999", alpha=0.15, lw=0)
    ax.text(6.5, 136, "recommended\ng 5-8 mm", fontsize=7, ha="center", va="top")
    ax.axvline(2.415, color="#777777", lw=0.8, ls=":")
    ax.text(2.6, 40, "r1 gap\n2.415 mm", fontsize=6.5, color="#555555")
    ax.axhline(75, color="#c00000", lw=1.0, ls="-.")
    ax.set_xlabel("channel gap g (mm)")
    ax.set_ylabel("T_J - T_air at 2.7 W (C)")
    ax.set_title("(c) Gap selection at 2.7 W", fontsize=9, loc="left")
    ax.set_xlim(2.4, 12)
    ax.set_ylim(35, 140)
    ax.grid(True, color="#e5e5e5", lw=0.6)
    ax.legend(loc="lower right", fontsize=6.8)
    fig.suptitle("Junction rise from the forced-air lumped model of layout_calc.py §8 (model estimate, not measured; "
                 "bands span k_pin, R_MB, Nu and the pin options)", fontsize=9, x=0.01, ha="left")
    fig.tight_layout()
    save(fig, "fig07_thermal_fan_on.svg")


# ======================================================================================================== Figure 8
def fig_thermal_fan_off(lc):
    fig, (a, b) = plt.subplots(1, 2, figsize=(12.5, 4.8))
    ps = np.arange(1.8, 3.001, 0.05)
    ht2 = lc.h_flat(2.0, lc.L_TOP)[1] + lc.H_RAD_TOP
    for (lab, g, mode, c) in (("fan off, g 5 mm", 5e-3, "still", SER[1]), ("fan off, g 8 mm", 8e-3, "still", SER[3]),
                              ("fan off, g 12 mm", 12e-3, "still", SER[5]),
                              ("fan on both sides 2 m/s, g 5 mm", 5e-3, "both", SER[0])):
        lo, hi = [], []
        for p in ps:
            r = lc.tj_band(p, g, "duct", 2.0, h_top=ht2) if mode == "both" else lc.tj_band(p, g, "still")
            lo.append(25 + r[2])
            hi.append(25 + r[3])
        a.fill_between(ps, lo, hi, color=c, alpha=0.15, lw=0)
        a.plot(ps, lo, color=c, lw=1.2)
        a.plot(ps, hi, color=c, lw=1.2, ls="--", label=lab)
    for y, t, c, ls in ((150, "TSHUT 150 C", "#000000", "-"), (120, "TREG 120 C (default)", "#7a0000", "-"),
                        (100, "design target 100 C", "#c00000", "-."), (95, "FR-50 derate, start value about 95 C", "#b05a00", ":")):
        a.axhline(y, color=c, lw=0.9, ls=ls)
        a.text(1.81, y + 0.8, t, fontsize=6.6, color=c, va="bottom")
    a.axhspan(105, 110, color="#b05a00", alpha=0.12, lw=0)
    a.text(1.81, 107.5, "FR-50 trip, start value 105-110 C", fontsize=6.6, color="#b05a00", va="center")
    for p, t in ((2.08, "2.08 W\nderate image"), (2.7, "2.7 W\nregen point"), (2.9, "2.9 W")):
        a.axvline(p, color="#999999", lw=0.7, ls=":")
        a.text(p + 0.01, 168, t, fontsize=6.2, color="#555555", va="top")
    a.set_xlim(1.8, 3.0)
    a.set_ylim(50, 170)
    a.set_xlabel("CCB loss P (W)")
    a.set_ylabel("T_J on a 25 C bench (C)")
    a.set_title("(a) Steady state against the board loss", fontsize=9, loc="left")
    a.legend(loc="lower right", fontsize=6.6)
    a.grid(True, color="#e5e5e5", lw=0.6)
    # (b) transient after the fan stops, 2.7 W, g 5 mm
    t = np.linspace(0, 1200, 400)
    on = lc.tj_band(2.7, 5e-3, "duct", 2.0, h_top=ht2)
    off = lc.tj_band(2.7, 5e-3, "still")
    dtj = 9.7 * lc.p_ic(2.7)
    for k, (lab, ls) in enumerate((("low end of the band", "-"), ("high end of the band", "--"))):
        tc0 = (on[2] if k == 0 else on[3]) - dtj
        r_off = off[0] if k == 0 else off[1]
        tcinf = 2.7 * r_off
        tau = lc.c_ccb * r_off
        tj = 25 + dtj + tcinf + (tc0 - tcinf) * np.exp(-t / tau)
        b.plot(t, tj, color=SER[1], lw=1.4, ls=ls, label=f"{lab}: tau = {tau:.0f} s")
        for thr, c in ((95, "#b05a00"), (105, "#b05a00"), (110, "#b05a00"), (120, "#7a0000")):
            if tj[-1] > thr > tj[0]:
                tx = -tau * math.log((25 + dtj + tcinf - thr) / (tcinf - tc0))
                b.plot(tx, thr, marker="o", ms=4, color=c)
    for y, tt, c, ls in ((120, "TREG 120 C", "#7a0000", "-"), (100, "target 100 C", "#c00000", "-."),
                         (95, "derate start value about 95 C", "#b05a00", ":")):
        b.axhline(y, color=c, lw=0.9, ls=ls)
        b.text(1195, y + 0.8, tt, fontsize=6.6, color=c, ha="right", va="bottom")
    b.axhspan(105, 110, color="#b05a00", alpha=0.12, lw=0)
    b.text(1195, 107.5, "trip start value 105-110 C", fontsize=6.6, color="#b05a00", ha="right", va="center")
    b.set_xlim(0, 1200)
    b.set_ylim(70, 175)
    b.set_xlabel("time after the fan stops (s)")
    b.set_ylabel("T_J on a 25 C bench (C)")
    b.set_title("(b) Fan stops at t = 0; 2.7 W held, g 5 mm", fontsize=9, loc="left")
    b.legend(loc="upper left", fontsize=6.6, bbox_to_anchor=(0.0, 0.90))
    b.grid(True, color="#e5e5e5", lw=0.6)
    fig.suptitle("Fan-off fault case from layout_calc.py §8 (model estimate). Panel (b) is the single-node response of "
                 "that network with the CCB heat capacity c_ccb = %.1f J/K; it holds 2.7 W and ignores the derate and "
                 "the MB heat capacity" % lc.c_ccb, fontsize=8.5, x=0.01, ha="left")
    fig.tight_layout()
    save(fig, "fig08_thermal_fan_off.svg")


# ======================================================================================================== Figure 9
def tj_heatsink(lc, g, mode, v, htop, r_sa, p=2.7):
    """T_J - T_air with a U501 top heatsink; same algebra as layout_calc.py §8.8."""
    res = []
    for r_tim in (0.5, 2.0):
        r_hs = 20.9 + r_tim * 1e-4 / lc.A_PKG + r_sa
        for k_pin, r_e in lc.PIN_CASES:
            for rmb in lc.R_MB_BAND:
                for hb in (("lo", "hi") if mode == "duct" else ("lo",)):
                    n1 = lc.forced_net(p, g, mode, v, htop, k_pin, rmb, r_e, hb)
                    n0 = lc.forced_net(1e-9, g, mode, v, htop, k_pin, rmb, r_e, hb)
                    a0 = n0["tC"]
                    bb = (n1["tC"] - a0) / p
                    res.append((a0 + bb * p + 9.7 * lc.p_ic(p)) / (1 + (bb + 9.7) / r_hs))
    return min(res), max(res)


def fig_thermal_compare(lc):
    ht2 = lc.h_flat(2.0, lc.L_TOP)[1] + lc.H_RAD_TOP
    rows = [
        ("r1 geometry, g 2.415 mm, still air, radiation omitted (as in r1)", lc.tj_band(2.7, 2.415e-3, "still", rad=False)[2:4], "r1"),
        ("r1 geometry, still air with radiation", lc.tj_band(2.7, 2.415e-3, "still")[2:4], "r1"),
        ("r2 fan off, g 5 mm", lc.tj_band(2.7, 5e-3, "still")[2:4], "off"),
        ("r2 fan off, g 8 mm", lc.tj_band(2.7, 8e-3, "still")[2:4], "off"),
        ("r2 fan off, g 5 mm, U501 heatsink R_sa 40 C/W (DNP option)", tj_heatsink(lc, 5e-3, "still", 0.0,
                                                                                    lc.H_TOP_STILL, 40.0), "off"),
        ("r2 fan on, gap only, g 5 mm, 2 m/s", lc.tj_band(2.7, 5e-3, "duct", 2.0)[2:4], "part"),
        ("r2 fan on, top only, g 5 mm, 2 m/s", lc.tj_band(2.7, 5e-3, "still", h_top=ht2)[2:4], "part"),
        ("r2 fan on, both sides, g 8 mm, 2 m/s", lc.tj_band(2.7, 8e-3, "duct", 2.0, h_top=ht2)[2:4], "on"),
        ("r2 fan on, both sides, g 5 mm, 2 m/s (design case)", lc.tj_band(2.7, 5e-3, "duct", 2.0, h_top=ht2)[2:4],
         "on"),
    ]
    col = {"r1": "#999999", "off": SER[1], "part": SER[4], "on": SER[0]}
    fig, ax = plt.subplots(figsize=(10.5, 4.6))
    for i, (lab, (lo, hi), k) in enumerate(rows):
        ax.barh(i, hi - lo, left=lo, height=0.55, color=col[k], alpha=0.85, edgecolor=INK, lw=0.5)
        ax.text(hi + 1.0, i, f"{lo:.0f}-{hi:.0f} C", fontsize=7, va="center")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows], fontsize=7.5)
    ax.axvline(75, color="#c00000", lw=1.0, ls="-.")
    ax.text(75.5, len(rows) - 0.4, "100 C on a 25 C bench", fontsize=7, color="#c00000", va="top")
    ax.axvline(95, color="#7a0000", lw=0.9)
    ax.text(95.5, len(rows) - 0.4, "TREG 120 C on a 25 C bench", fontsize=7, color="#7a0000", va="top")
    ax.set_xlim(30, 140)
    ax.set_xlabel("T_J - T_air at 2.7 W (C)")
    ax.set_title("Thermal configurations compared at the 2.7 W regen point (layout_calc.py §8 network; model estimate)",
                 fontsize=9, loc="left")
    ax.grid(True, axis="x", color="#e5e5e5", lw=0.6)
    fig.tight_layout()
    save(fig, "fig09_thermal_compare.svg")


# ======================================================================================================= Figure 10
def fig_electrical(sc, ts):
    fig, (a, b) = plt.subplots(1, 2, figsize=(12.5, 4.7))
    vin = np.linspace(14.5, 23.63, 200)
    ich, vsys = sc.ICHG_MAX, sc.VSYS_MAX
    for (f, L, tol, lab, c, ls) in ((sc.F_HI, sc.L_HI, 1.0, "1.5 MHz, 1.0 uH (baseline)", SER[0], "-"),
                                    (sc.F_HI, sc.L_HI, 0.8, "1.5 MHz, 0.8 uH (-20 %)", SER[0], "--"),
                                    (sc.F_LO, sc.L_LO, 1.0, "750 kHz, 2.2 uH (alternate)", SER[2], "-"),
                                    (sc.F_LO, sc.L_LO, 0.8, "750 kHz, 1.76 uH (-20 %)", SER[2], "--")):
        rip = np.array([sc.rip_buck(v, vsys, f, L * tol) for v in vin])
        a.plot(vin, ich + rip / 2, color=c, lw=1.4, ls=ls, label=f"peak, {lab}")
        a.plot(vin, rip, color=c, lw=0.9, ls=ls, alpha=0.55)
    a.axhline(6.5, color="#c00000", lw=1.0)
    a.text(14.6, 6.55, "Isat requirement 6.5 A at T_max (§2.1.3)", fontsize=6.8, color="#c00000", va="bottom")
    a.axhline(5.0, color="#7a5c00", lw=0.9, ls=":")
    a.text(14.6, 5.05, "ISW 5 A ([DS] §6.3; DC or peak not stated)", fontsize=6.8, color="#7a5c00", va="bottom")
    a.axhline(ich, color="#777777", lw=0.8, ls=":")
    a.text(23.5, ich - 0.05, "ICHG 3.21 A", fontsize=6.6, color="#555555", ha="right", va="top")
    pk = ich + sc.rip_buck(23.63, vsys, sc.F_HI, 0.8 * sc.L_HI) / 2
    a.plot(23.63, pk, marker="o", color=SER[0])
    a.annotate(f"worst case {pk:.2f} A", xy=(23.63, pk), xytext=(19.6, 5.75), fontsize=6.8,
               arrowprops=dict(arrowstyle="-", lw=0.6))
    for v, t in ((16.0, "VBUS 16.0"), (22.28, "V-MOT\nclamp max"), (23.63, "eFuse\nOVP max")):
        a.axvline(v, color="#bbbbbb", lw=0.7, ls=":")
        a.text(v - 0.08, 6.95, t, fontsize=6.0, ha="right", va="top", color="#555555")
    a.text(14.7, 2.85, "thin lines: ripple (A p-p)", fontsize=6.6, color="#555555")
    a.set_xlim(14.5, 23.8)
    a.set_ylim(1.6, 7.0)
    a.set_xlabel("VBUS (V); buck operation above VINDPM 14.5 V")
    a.set_ylabel("L501 current (A)")
    a.set_title("(a) L501 peak and ripple, [DS] Eq 4 and Eq 5 (sch_calc.py)\nICHG 3.21 A, VSYS 8.82 V",
                fontsize=9, loc="left")
    a.legend(loc="lower right", fontsize=6.4)
    a.grid(True, color="#e5e5e5", lw=0.6)
    # (b) eFuse IN spike vs OUT inductance
    louts = np.array([5, 7.5, 10, 15, 20, 30, 50, 75, 100, 150]) * 1e-9
    for hu, c in ((ts.H_U_R1, "#777777"), (8.0, SER[0]), (12.0, SER[3])):
        dl = 0.0 if hu == ts.H_U_R1 else ts.DL_IN[hu]
        for cin, ls, cl in ((3.4e-6, "-", "C_IN eff 3.4 uF"), (5.8e-6, "--", "C_IN nom 5.8 uF")):
            pk = []
            for lo in louts:
                dt = 1e-9 if lo >= 20e-9 else 0.5e-9
                worst = 0.0
                for v0 in (16.0, 22.0):
                    for cs in (4e-6, 5e-6, 10e-6, 20e-6):
                        for lin in (50e-9, 150e-9):
                            worst = max(worst, ts.in_spike(v0, cs, lin + dl, cin, lout=lo, dt=dt)[0])
                pk.append(worst)
            b.plot(louts * 1e9, pk, color=c, lw=1.4, ls=ls, marker="o", ms=2.5,
                   label=f"H_u {hu:.2f} mm (+{dl*1e9:.1f} nH), {cl}")
    for y, t, c in ((67, "U301 IN abs max 67 V", "#000000"), (60, "T-C-04 IN criterion 60 V", "#7a0000"),
                    (36.7, "D307 VBR min 36.7 V (TVS conducts; not modelled)", "#c00000")):
        b.axhline(y, color=c, lw=0.9, ls="-." if y < 50 else "-")
        b.text(5.2, y + 0.4, t, fontsize=6.6, color=c, va="bottom")
    b.axvspan(5, 20, color="#999999", alpha=0.12, lw=0)
    b.text(10, 24.5, "CCB OUT copper\n5-20 nH (assumed)", fontsize=6.6, ha="center")
    b.axvline(150, color="#999999", lw=0.8, ls=":")
    b.text(146, 24.5, "round-3 W1/W2\nlead 150 nH", fontsize=6.6, ha="right")
    b.set_xscale("log")
    b.set_xlim(5, 160)
    b.set_ylim(23, 70)
    b.set_xlabel("OUT-loop inductance L_OUT (nH)")
    b.set_ylabel("worst U301 IN peak (V)")
    b.set_title("(b) eFuse hard-short IN spike, ideal model (tall_stack_calc.py §(c));\nworst over V0, C_S and L_IN",
                fontsize=9, loc="left")
    b.legend(loc="center right", fontsize=6.0)
    b.grid(True, which="both", color="#eeeeee", lw=0.5)
    fig.tight_layout()
    save(fig, "fig10_electrical_checks.svg")


# ======================================================================================================= Figure 11
def fig_cost_schedule(cost):
    bl = cost["builds"]
    pa = cost["basis"]["path_a_usd"]
    fig, axs = plt.subplots(1, 3, figsize=(13.5, 4.6), gridspec_kw=dict(width_ratios=[1.25, 1.0, 1.0]))
    # (a) cash
    rows = [("Path A (2 EVMs + CR + EIB)", pa, "#777777"),
            ("CCB, 2 boards, hand (H)", bl["2+sp"]["option_H_usd"], SER[0]),
            ("CCB, 2 boards, PCBA (P)", bl["2+sp"]["option_P_usd"], SER[0]),
            ("CCB, 4 boards (test plan), H", bl["4+sp"]["option_H_usd"], SER[3]),
            ("CCB, 4 boards (test plan), P", bl["4+sp"]["option_P_usd"], SER[3]),
            ("Path A gates, then CCB (2 boards)", [pa[0] + bl["2+sp"]["option_H_usd"][0],
                                                   pa[1] + bl["2+sp"]["option_P_usd"][1]], SER[4]),
            ("Path A gates, then CCB (4 boards)", [pa[0] + bl["4+sp"]["option_H_usd"][0],
                                                   pa[1] + bl["4+sp"]["option_P_usd"][1]], SER[4]),
            ("Path B1 (MB re-spin, 5 boards)", [1000, 2000], SER[2]),
            ("Path B2 (two new power stages)", [2000, 4000], SER[2])]
    ax = axs[0]
    for i, (lab, (lo, hi), c) in enumerate(rows[::-1]):
        ax.barh(i, hi - lo, left=lo, height=0.55, color=c, alpha=0.85, edgecolor=INK, lw=0.5)
        ax.text(hi + 40, i, f"{lo:.0f}-{hi:.0f}", fontsize=6.6, va="center")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows[::-1]], fontsize=7)
    ax.set_xlim(0, 4800)
    ax.set_xlabel("parts and boards (USD); allowances except TI silicon and EVMs")
    ax.set_title("(a) Cash, base figures (§4.5, §7.1.3, §7.1.9)", fontsize=9, loc="left")
    ax.grid(True, axis="x", color="#e5e5e5", lw=0.6)
    # (b) effort
    eff = [("Path A", (417, 666)), ("Path A-C = CCB", (486, 822)), ("Path A gates, then CCB", (599, 1032)),
           ("Path B1", (564, 1048)), ("Path B2", (990, 1730))]
    resp = {"Path A": (431, 698), "Path A-C = CCB": (512, 884), "Path A gates, then CCB": (625, 1094)}
    ax = axs[1]
    for i, (lab, (lo, hi)) in enumerate(eff[::-1]):
        ax.barh(i, hi - lo, left=lo, height=0.55, color=SER[0] if "CCB" in lab else "#999999", alpha=0.85,
                edgecolor=INK, lw=0.5)
        ax.text(hi + 25, i, f"{lo}-{hi} h", fontsize=6.6, va="center")
        if lab in resp:
            ax.plot(resp[lab], [i - 0.36, i - 0.36], color="#c00000", lw=1.6)
            ax.text(resp[lab][1] + 25, i - 0.36, f"{resp[lab][0]}-{resp[lab][1]}", fontsize=6.0, va="center",
                    color="#c00000")
    ax.plot([], [], color="#c00000", lw=1.6, label="with one re-spin (AS-9)")
    ax.legend(loc="lower right", fontsize=6.4)
    ax.set_yticks(range(len(eff)))
    ax.set_yticklabels([e[0] for e in eff[::-1]], fontsize=7)
    ax.set_xlim(0, 2100)
    ax.set_xlabel("engineering effort (h), ESTIMATE (Table 7.1, 7.3a)")
    ax.set_title("(b) Effort", fontsize=9, loc="left")
    ax.grid(True, axis="x", color="#e5e5e5", lw=0.6)
    # (c) schedule
    sch = [("Path A", (1, 3), None), ("Path A-C = CCB", (7, 13), (10, 19)),
           ("Path A gates, then CCB", (12.5, 21), (15.5, 27)), ("Path B1", (10, 15), None)]
    ax = axs[2]
    for i, (lab, (lo, hi), rs) in enumerate(sch[::-1]):
        ax.barh(i, hi - lo, left=lo, height=0.55, color=SER[0] if "CCB" in lab else "#999999", alpha=0.85,
                edgecolor=INK, lw=0.5)
        ax.text(hi + 0.4, i + 0.12, f"{lo:g}-{hi:g} wk", fontsize=6.6, va="center")
        if rs:
            ax.plot(rs, [i - 0.36, i - 0.36], color="#c00000", lw=1.6)
            ax.text(rs[1] + 0.4, i - 0.36, f"{rs[0]:g}-{rs[1]:g}", fontsize=6.0, va="center", color="#c00000")
        if lab == "Path A gates, then CCB":
            ax.plot([10, 17], [i + 0.36, i + 0.36], color=SER[4], lw=1.6)
            ax.text(17.4, i + 0.36, "10-17", fontsize=6.0, va="center", color="#b35900")
    ax.plot([], [], color="#c00000", lw=1.6, label="with one re-spin")
    ax.plot([], [], color=SER[4], lw=1.6, label="CCB design during the Path A wait")
    ax.legend(loc="lower right", fontsize=6.2)
    ax.set_yticks(range(len(sch)))
    ax.set_yticklabels([s[0] for s in sch[::-1]], fontsize=7)
    ax.set_xlim(0, 32)
    ax.set_xlabel("weeks to the first bench charge on the path's own charger\n(Table 7.3, 7.3a; Path B2: about 4-6 months, not drawn)")
    ax.set_title("(c) Schedule", fontsize=9, loc="left")
    ax.grid(True, axis="x", color="#e5e5e5", lw=0.6)
    fig.tight_layout()
    save(fig, "fig11_cost_effort_schedule.svg")


# ======================================================================================================= Figure 12
def parse_ledger(path):
    counts, sev = {}, {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*(\d)\s*\|\s*\d+\s*\|\s*`[^`]+`\s*\|\s*([^|]+?)\s*\|[^|]*\|\s*\*\*(CLOSED|KEPT|CHANGED)\*\*",
                     line)
        if not m:
            continue
        rnd, s, st = int(m.group(1)), m.group(2).split()[0], m.group(3)
        counts.setdefault(rnd, {"CLOSED": 0, "CHANGED": 0, "KEPT": 0})[st] += 1
        sev.setdefault(s, {"CLOSED": 0, "CHANGED": 0, "KEPT": 0})[st] += 1
    return counts, sev


def fig_tests_and_ledger(ledger):
    counts, sev = ledger
    fig = plt.figure(figsize=(13.0, 6.9))
    gs = fig.add_gridspec(2, 3, height_ratios=[1.25, 1.0])
    ax = fig.add_subplot(gs[0, :])
    ax.set_xlim(0, 130)
    ax.set_ylim(0, 30)
    ax.axis("off")
    ax.set_title("(a) Order of the test phases (design §6.5.2; r2 sequence)", fontsize=9, loc="left")
    phases = [("Phase 0", "vehicle as it is (Ag105 fitted)",
               "T-K-01 (records),\nT-K-02 (record only),\nT-A-01, T-A-01b, T-A-01c,\nT-A-06c, T-E group\n(T-E-04 first)"),
              ("Phase 1", "design",
               "T-A-05, then T-A-06\nwith step 0;\nM15 fan survey on the\n1:1 template;\nthen the PCB order"),
              ("Phase 2", "incoming", "T-K-03, T-A-03,\nT-A-04, T-A-07 at\n25 C and 60 C"),
              ("Phase 3", "stage 1 on FIX1 (logic)",
               "T-K-05, T-C-01,\nT-C-01b, T-C-01c,\nT-C-02, T-C-03,\nT-C-10, T-C-12"),
              ("Phase 4", "stage 2 on FIX1 (power)",
               "T-K-06, T-B-01, T-K-07,\nT-K-08 (LOOP1),\nT-K-09/10, T-B group,\nT-C group, T-K-11,\n"
               "T-D group (FI1),\nT-K-16, T-W bench parts"),
              ("Phase 5", "vehicle fit",
               "PM1 Ag105 removal,\nT-F-01, T-K-04, T-K-17,\nT-K-18, T-K-12, T-K-13,\nT-K-14 + T-K-20,\nT-K-15, T-F group"),
              ("Phase 6", "FC windows, testbench",
               "T-W-01 on the vehicle,\nT-F-08, T-F-04 to\nT-F-09, T-G drive\ncycles")]
    w, hgt, y0 = 17.2, 21, 8
    for i, (t, sub, body) in enumerate(phases):
        x = 1 + i * 18.4
        fc = C_M if i in (3, 4) else (C_I if i < 3 else C_S)
        box(ax, x, y0, w, hgt, "", fc=fc)
        ax.text(x + w / 2, y0 + hgt - 1.0, t, fontsize=7.4, weight="bold", ha="center", va="top")
        ax.text(x + w / 2, y0 + hgt - 4.6, sub, fontsize=6.4, ha="center", va="top", style="italic")
        ax.text(x + 0.8, y0 + hgt - 9.0, body, fontsize=6.3, va="top", linespacing=1.3)
        if i < len(phases) - 1:
            arrow(ax, x + w, y0 + hgt / 2, x + 18.4, y0 + hgt / 2, lw=1.2)
    ax.text(1, 4.6, "Gate before phase 1 (verdict condition 1): T-B-06, T-B-09, T-B-10, T-B-12 and T-B-21 pass on the "
            "Path A rig, and the IC search keeps the BQ25798.", fontsize=6.8, va="center", color="#7a0000")
    ax.text(1, 1.4, "PM1 (the Ag105 desolder, the irreversible step) follows only after phases 3 and 4 pass. "
            "No FC-charge window runs before T-W-01.", fontsize=6.8, va="center", color="#7a0000")
    # (b) ledger by round
    ax = fig.add_subplot(gs[1, 0:2])
    rounds = sorted(counts)
    cols = {"CLOSED": SER[2], "CHANGED": SER[4], "KEPT": "#9e9e9e"}
    left = np.zeros(len(rounds))
    for st in ("CLOSED", "CHANGED", "KEPT"):
        vals = np.array([counts[r][st] for r in rounds])
        ax.barh(rounds, vals, left=left, color=cols[st], edgecolor=INK, lw=0.4, label=st, height=0.6)
        for r, l, v in zip(rounds, left, vals):
            if v:
                ax.text(l + v / 2, r, str(v), fontsize=6.6, ha="center", va="center")
        left += vals
    tot = {st: sum(counts[r][st] for r in rounds) for st in cols}
    ax.set_yticks(rounds)
    ax.set_yticklabels([f"round {r}" for r in rounds], fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel("finding keys")
    ax.set_title(f"(b) 203-key ledger by round (ledger_table.md): CLOSED {tot['CLOSED']}, CHANGED {tot['CHANGED']}, "
                 f"KEPT {tot['KEPT']}", fontsize=9, loc="left")
    ax.legend(loc="lower right", fontsize=7)
    ax.grid(True, axis="x", color="#e5e5e5", lw=0.6)
    # (c) by severity
    ax = fig.add_subplot(gs[1, 2])
    order = [s for s in ("blocker", "major", "minor") if s in sev]
    left = np.zeros(len(order))
    for st in ("CLOSED", "CHANGED", "KEPT"):
        vals = np.array([sev[s][st] for s in order])
        ax.barh(order, vals, left=left, color=cols[st], edgecolor=INK, lw=0.4, height=0.6)
        for i, (l, v) in enumerate(zip(left, vals)):
            if v:
                ax.text(l + v / 2, i, str(v), fontsize=6.6, ha="center", va="center")
        left += vals
    ax.invert_yaxis()
    ax.set_xlabel("finding keys")
    ax.set_title("(c) By severity", fontsize=9, loc="left")
    ax.grid(True, axis="x", color="#e5e5e5", lw=0.6)
    fig.tight_layout()
    save(fig, "fig12_tests_and_ledger.svg")


# ============================================================================================================ main
def main():
    global PNG_DIR
    if "--png" in sys.argv:
        PNG_DIR = Path(sys.argv[sys.argv.index("--png") + 1])
        PNG_DIR.mkdir(parents=True, exist_ok=True)
    mech = json.loads((CALC / "mech_parse_out.json").read_text(encoding="utf-8"))
    cost = json.loads((CALC / "bom_cost.json").read_text(encoding="utf-8"))
    tida = parse_tida(CALC / "tida_layout_parse_out.txt")
    ledger = parse_ledger(CALC / "ledger_table.md")
    only = None
    if "--only" in sys.argv:
        only = {int(n) for n in sys.argv[sys.argv.index("--only") + 1].split(",")}
    want = (lambda n: only is None or n in only)
    lc = load("layout_calc") if any(want(n) for n in (7, 8, 9)) else None
    sc = load("sch_calc") if want(10) else None
    ts = load("tall_stack_calc") if want(10) else None

    jobs = [(1, fig_power_path, ()), (2, fig_top_view, (mech,)), (3, fig_side_view, ()),
            (4, fig_block_diagram, ()), (5, fig_permit_logic, ()), (6, fig_floor_and_cell, (tida,)),
            (7, fig_thermal_velocity, (lc,)), (8, fig_thermal_fan_off, (lc,)), (9, fig_thermal_compare, (lc,)),
            (10, fig_electrical, (sc, ts)), (11, fig_cost_schedule, (cost,)), (12, fig_tests_and_ledger, (ledger,))]
    for n, fn, args in jobs:
        if want(n):
            fn(*args)
    print("ledger by round:", ledger[0])
    print("ledger by severity:", ledger[1])
    print("wrote:", ", ".join(OUTPUTS))


if __name__ == "__main__":
    main()
