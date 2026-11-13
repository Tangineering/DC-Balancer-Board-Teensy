"""Render the README figures of the charger EVM r9 design review guide.

Figures (written to ../figures/ as .svg and .png):
  fig2_1_block_diagram  - charger path, block diagram (replaces the ASCII Figure 2.1 of README.md).
  fig5_1_permit_gate    - r9 permit gate, gate-level logic diagram (README 5.3, Table 8.3;
                          design document B.1 and B.8; cr/cr.net).

Sources: README.md sections 2 and 5, Tables 2.1, 2.2, 5.1, 8.3, 8.4, 8.5;
docs/charger_bq25798_wiring_design_2026-11-05.md sections B.1 and B.8; cr/cr.net (r8-capture-2).

Deterministic: matplotlib only, fixed geometry, SVG hash salt and metadata dates pinned.
Run: python readme_figures.py   (prints a text-overlap check; exit code 1 if any overlap remains).
"""
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Polygon, Circle, PathPatch, Rectangle, FancyArrowPatch  # noqa: E402
from matplotlib.path import Path  # noqa: E402

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "svg.fonttype": "none",
    "svg.hashsalt": "charger-evm-r9-readme",
    "path.simplify": False,
    "figure.facecolor": "white",
    "savefig.facecolor": "white",
})

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "figures"))

UNIT_IN = 0.09            # inches per drawing unit (both axes, so circles stay round)

POWER = "#B03A2E"         # power conductors
LOGIC = "#1F5FAD"         # logic and analog signal conductors
INK = "#1A1A1A"
GREY = "#6B6B6B"
REGION_STYLE = {
    "MB": ("#EEF5EA", "#5E8C4A"),
    "TAPS": ("#FBF1E3", "#B07A2A"),
    "CR": ("#FFF9DB", "#A68A00"),
    "EVM": ("#E8F1FB", "#3D6FA8"),
    "EIB": ("#F2ECF8", "#7A5AA6"),
}

FS = 9.0       # base font size
FS_S = 8.0     # small labels
FS_XS = 7.0    # pin numbers and pad notes

_TEXTS = []    # (artist, container bbox in data units or None)


def new_canvas(x0, x1, y0, y1):
    w, h = (x1 - x0) * UNIT_IN, (y1 - y0) * UNIT_IN
    fig = plt.figure(figsize=(w, h))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_axis_off()
    _TEXTS.clear()
    return fig, ax


def text(ax, x, y, s, fs=FS, ha="center", va="center", color=INK, weight="normal", bg=False,
         container=None, check=True, rotation=0, style="normal"):
    kw = {}
    if bg:
        kw["bbox"] = dict(boxstyle="square,pad=0.12", fc="white", ec="none")
    t = ax.text(x, y, s, fontsize=fs, ha=ha, va=va, color=color, weight=weight, zorder=6,
                linespacing=1.15, rotation=rotation, style=style, **kw)
    if check:
        _TEXTS.append((t, container))
    return t


def box(ax, x0, y0, x1, y1, s="", fs=FS, fc="white", ec=INK, lw=1.2, weight="normal", r=0.8,
        ls="-", z=3, tx=None, ty=None, ha="center"):
    p = FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle=f"round,pad=0,rounding_size={r}",
                       fc=fc, ec=ec, lw=lw, ls=ls, zorder=z)
    ax.add_patch(p)
    if s:
        cx = (x0 + x1) / 2 if tx is None else tx
        cy = (y0 + y1) / 2 if ty is None else ty
        text(ax, cx, cy, s, fs=fs, weight=weight, ha=ha, container=(x0, y0, x1, y1))
    return p


def region(ax, x0, y0, x1, y1, key, title, fs=FS + 1):
    fc, ec = REGION_STYLE[key]
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0,rounding_size=1.5",
                                fc=fc, ec=ec, lw=1.4, ls=(0, (5, 3)), zorder=1))
    text(ax, x0 + 1.4, y1 - 1.2, title, fs=fs, ha="left", va="top", weight="bold", color=ec,
         container=(x0, y0, x1, y1))


def wire(ax, pts, kind="logic", head="end", lw=None, color=None, z=4, hops=()):
    """Polyline conductor. head: 'end', 'start', 'both' or 'none'. hops: points on vertical
    segments where a semicircular bridge marks a crossing with no connection."""
    color = color or (POWER if kind == "power" else LOGIC)
    lw = lw or (3.2 if kind == "power" else 1.3)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    if hops:
        _wire_with_hops(ax, pts, hops, color, lw, z)
    else:
        ax.plot(xs, ys, color=color, lw=lw, solid_capstyle="butt", solid_joinstyle="miter", zorder=z)
    ms = 15 if kind == "power" else 10

    def _head(a, b):
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=ms, color=color, lw=0,
                                     shrinkA=0, shrinkB=0, zorder=z + 0.5))

    def _toward(p, q, d):
        # point at distance d from q back toward p
        dx, dy = q[0] - p[0], q[1] - p[1]
        L = (dx * dx + dy * dy) ** 0.5
        return (q[0] - dx / L * d, q[1] - dy / L * d)

    d = 2.0 if kind == "power" else 1.4
    if head in ("end", "both"):
        _head(_toward(pts[-2], pts[-1], d), pts[-1])
    if head in ("start", "both"):
        _head(_toward(pts[1], pts[0], d), pts[0])


def _wire_with_hops(ax, pts, hops, color, lw, z, r=1.0):
    verts, codes = [pts[0]], [Path.MOVETO]
    for a, b in zip(pts[:-1], pts[1:]):
        hs = [h for h in hops if a[0] == b[0] == h[0] and min(a[1], b[1]) < h[1] < max(a[1], b[1])]
        sgn = 1 if b[1] > a[1] else -1
        for h in sorted(hs, key=lambda h: sgn * h[1]):
            y_in, y_out = h[1] - sgn * r, h[1] + sgn * r
            verts += [(a[0], y_in)]
            codes += [Path.LINETO]
            # bridge bulging to +x: cubic approximation of a semicircle
            k = 1.33 * r
            verts += [(a[0] + k, y_in), (a[0] + k, y_out), (a[0], y_out)]
            codes += [Path.CURVE4] * 3
        verts.append(b)
        codes.append(Path.LINETO)
    ax.add_patch(PathPatch(Path(verts, codes), fc="none", ec=color, lw=lw, zorder=z,
                           capstyle="butt", joinstyle="miter"))


def dot(ax, x, y, color=LOGIC, r=0.55):
    ax.add_patch(Circle((x, y), r, fc=color, ec="none", zorder=5))


def check_layout(fig, name):
    """Report text-text overlaps, text outside its container and text outside the canvas."""
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    ax = fig.axes[0]
    to_disp = ax.transData.transform
    W, H = fig.bbox.width, fig.bbox.height
    items = []
    for t, cont in _TEXTS:
        bb = t.get_window_extent(rend)
        items.append((t, bb, cont))
    problems = []
    for i in range(len(items)):
        ti, bi, ci = items[i]
        if bi.x0 < 0 or bi.y0 < 0 or bi.x1 > W or bi.y1 > H:
            problems.append(f"clipped: {ti.get_text()!r}")
        if ci is not None:
            (cx0, cy0) = to_disp((ci[0], ci[1]))
            (cx1, cy1) = to_disp((ci[2], ci[3]))
            if bi.x0 < cx0 - 0.5 or bi.x1 > cx1 + 0.5 or bi.y0 < cy0 - 0.5 or bi.y1 > cy1 + 0.5:
                problems.append(f"outside container: {ti.get_text()!r}")
        for j in range(i + 1, len(items)):
            tj, bj, _ = items[j]
            if bi.overlaps(bj):
                ox = min(bi.x1, bj.x1) - max(bi.x0, bj.x0)
                oy = min(bi.y1, bj.y1) - max(bi.y0, bj.y0)
                if ox > 0.5 and oy > 0.5:
                    problems.append(f"overlap: {ti.get_text()!r} x {tj.get_text()!r}")
    print(f"[{name}] {len(items)} text items checked, {len(problems)} problem(s)")
    for p in problems:
        print("   ", p)
    return problems


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(os.path.join(OUT, name + ".svg"), metadata={"Date": None, "Creator": None})
    fig.savefig(os.path.join(OUT, name + ".png"), dpi=200, metadata={"Software": None})
    plt.close(fig)


# --------------------------------------------------------------------------------------------
# Figure 2.1: charger path block diagram
# --------------------------------------------------------------------------------------------
def fig2_1():
    fig, ax = new_canvas(0, 180, -9, 111)

    # ---- regions ----
    region(ax, 2, 52, 67, 110, "MB", "MB (main board)")
    region(ax, 2, 2, 67, 48.5, "TAPS", "Taps / Teensy (on the MB)")
    region(ax, 68.5, 2, 122, 110, "CR", "CR (carrier, plug-on)")
    region(ax, 136, 56, 178, 110, "EVM", "EVM (BQ25798EVM on an insulating plate)")
    region(ax, 136, 2, 178, 48.5, "EIB", "EIB")
    text(ax, 80.0, 105.6, "SSQ sockets on the MB, TSW strips on the CR", fs=FS_S, ha="left", va="top",
         color=REGION_STYLE["CR"][1], container=(68.5, 2, 122, 110))

    # ---- MB power path ----
    box(ax, 5, 97, 23, 104, "FUEL CELL\n(H-20)", weight="bold")
    box(ax, 33, 96.5, 52, 104.5, "BATTERY PACK 2S\n(VBT)\npack V- = PCB GND", fs=FS_S, weight="bold")
    box(ax, 5, 85, 23, 92, "FC boost TPS61288\nFC_REG_ENABLE, pin 3", fs=FS_S)
    box(ax, 33, 85, 52, 92, "BT boost TPS61288\nBT_REG_ENABLE, pin 4", fs=FS_S)
    box(ax, 5, 74.5, 55, 78.5, "VBUS 16.0 V", fc="#F6D5D1", ec=POWER, weight="bold")
    box(ax, 31, 63.5, 42, 68, "V-MOT", fc="#F6D5D1", ec=POWER, weight="bold")
    box(ax, 48, 63.5, 64, 68, "VESC / motor", fs=FS_S)
    box(ax, 5, 53.5, 44, 59.5, "VCHG-IN\n(pin 38 CHG_VOLTAGE divider R1-CHG)", fs=FS_S, fc="#F6D5D1", ec=POWER)

    wire(ax, [(14, 97), (14, 92)], "power")
    wire(ax, [(14, 85), (14, 78.5)], "power")
    text(ax, 15.3, 81.7, "D-FC-EN (FC_BUS, pin 27)", fs=FS_S, ha="left")
    wire(ax, [(42.5, 96.5), (42.5, 92)], "power")
    wire(ax, [(42.5, 85), (42.5, 78.5)], "power")
    text(ax, 43.8, 81.7, "D-BT-EN (BT_BUS, pin 28)", fs=FS_S, ha="left")
    wire(ax, [(36.5, 74.5), (36.5, 68)], "power")
    text(ax, 37.8, 71.25, "D-MT-EN (MOT_PWR, pin 29)", fs=FS_S, ha="left")
    wire(ax, [(42, 65.75), (48, 65.75)], "power", head="both")
    wire(ax, [(8, 74.5), (8, 59.5)], "power")
    text(ax, 9.3, 71.25, "D-BC-FC (FC_CHARGE, pin 31)", fs=FS_S, ha="left")
    wire(ax, [(36.5, 63.5), (36.5, 59.5)], "power")
    text(ax, 35.2, 61.5, "D-BC-RG (REGEN, pin 30)", fs=FS_S, ha="right")

    # ---- CR J1 (CR underside, TSW strips) and J-TAP J102 (CR THT header): both on the CR, at its MB-side edge (Table 2.1) ----
    sx0, sx1 = 69.5, 78.5
    scx = (sx0 + sx1) / 2
    box(ax, sx0, 18, sx1, 104.0, "", fc="#FFFFFF", ec=INK, lw=1.4, r=0.6, z=2)
    text(ax, scx, 87.5, "CR J1\n22-pin\nCHG\nheader", fs=FS_S, weight="bold", container=(sx0, 18, sx1, 104.0))
    text(ax, scx, 70.0, "pads\n4, 14, 15\n= GND", fs=FS_XS, color=GREY, container=(sx0, 18, sx1, 104.0))
    box(ax, sx0, 3, sx1, 15.5, "J-TAP\nJ102\nMicro-Fit\n2 x 5", fs=FS_XS, weight="bold", r=0.6, z=2)

    def pad(y, s):
        text(ax, scx, y + 1.35, s, fs=FS_XS, color=GREY, container=(sx0, 18, sx1, 104.0))

    # ---- charger power loop ----
    # VCHG-IN -> pad 10 -> eFuse -> VCHGOUT -> W1/W2 -> EVM J1 VIN -> BQ25798 -> EVM J5 -> W3/W4 -> pads 18/19 -> D-BT-SQ -> pack
    wire(ax, [(44, 56.5), (84, 56.5)], "power")
    pad(56.5, "pad 10")
    box(ax, 84, 51, 106, 62, "eFuse U101\nTPS26630 + D103", fs=FS_S, weight="bold")
    wire(ax, [(106, 56.5), (111, 56.5), (111, 88), (139, 88)], "power")
    text(ax, 116.3, 89.4, "VCHGOUT", fs=FS_XS, color=POWER, ha="center")
    text(ax, 129, 89.6, "W1/W2 20 AWG", fs=FS_S, color=POWER)
    wire(ax, [(139, 100.5), (52, 100.5)], "power")
    pad(100.5, "pads 18/19")
    text(ax, 100, 101.9, "VCHG", fs=FS_XS, color=POWER)
    text(ax, 129, 102.1, "W3/W4 18 AWG", fs=FS_S, color=POWER)
    # D-BT-SQ sits on the MB segment of VCHG (CR J1 pads 18/19 -> pack), like the other switch labels;
    # the MB net name sits under the same segment, clear of the MB region border
    text(ax, 59.5, 101.9, "D-BT-SQ\n(BT_SEQ, pin 32)", fs=FS_S, va="bottom")
    text(ax, 59.5, 99.1, "VCHG (MB net)", fs=FS_XS, va="top", color=POWER)

    # ---- EVM ----
    box(ax, 139, 97.5, 152, 103.5, "EVM J5\nBATTERY", fs=FS_S)
    box(ax, 139, 85, 152, 91, "EVM J1\nVIN", fs=FS_S)
    box(ax, 139, 71, 152, 77, "EVM J7\npin 1 (TS)", fs=FS_S)
    box(ax, 139, 63, 152, 69, "EVM J8\nI2C", fs=FS_S)
    box(ax, 156, 60, 176, 104, "BQ25798\nbuck-boost\n\nI2C 0x6B", weight="bold")
    wire(ax, [(152, 88), (156, 88)], "power")
    wire(ax, [(156, 100.5), (152, 100.5)], "power")
    wire(ax, [(152, 74), (156, 74)], "logic")
    wire(ax, [(152, 66), (156, 66)], "logic", head="both")

    # ---- signals that pass through the CR outside the permit gate ----
    # TS_EXT: MB J-NTC -> pad 13 -> CR -> W6 -> EVM J7 pin 1
    box(ax, 48.5, 40.5, 66, 46.5, "MB J-NTC\n(optional pack NTC)", fs=FS_S)
    wire(ax, [(66, 43.5), (115, 43.5), (115, 74), (139, 74)], "logic")
    pad(43.5, "pad 13")
    text(ax, 98, 44.8, "TS_EXT", fs=FS_XS, color=LOGIC)
    text(ax, 129, 75.4, "W6 TS_EXT", fs=FS_S, color=LOGIC)
    # SDA/SCL: Teensy pins 18/19 -> pads 8/7 -> CR -> W7 -> EVM J8
    wire(ax, [(66, 32), (117.5, 32), (117.5, 66), (139, 66)], "logic", head="both")
    pad(32, "pads 8/7")
    text(ax, 98, 33.3, "SDA/SCL", fs=FS_XS, color=LOGIC)
    text(ax, 129, 67.4, "W7 SDA/SCL", fs=FS_S, color=LOGIC)
    # STAT: EVM STAT -> E7 -> EIB -> W5 -> CR J101 -> pad 3 -> Teensy pin 6
    wire(ax, [(112, 27), (66, 27)], "logic")
    pad(27, "pad 3")
    text(ax, 98, 28.3, "STAT", fs=FS_XS, color=LOGIC)

    # ---- permit gate, J101, W5, EIB ----
    box(ax, 82.5, 4, 108.5, 24,
        "Permit gate (Figure 5.1)\nComparators U102 H1,\nU103 UVB, U119 FCC_OFF,\nU120 FCC_ON\n"
        "Logic U105, U106, U107,\nU110, U118\nJ-TAP T1, T2, T5, T6, T10 in;\nT13 out (H1 readback)", fs=FS_S,
        weight="normal")
    # eFuse readbacks: U101.14 N_FLT -> R106s -> J102.9 (T16); U101.13 IMON -> R129 -> J102.8 (T17) (cr/cr.net)
    wire(ax, [(84, 53), (81, 53), (81, 13.5), (78.5, 13.5)], "logic", hops=[(81, 43.5), (81, 32), (81, 27), (81, 21)])
    text(ax, 82.0, 48.2, "FLT -> T16, IMON -> T17 (readbacks)", fs=FS_XS, ha="left", color=LOGIC)
    wire(ax, [(66, 21), (82.5, 21)], "logic")
    pad(21, "pad 11")
    wire(ax, [(78.5, 9.25), (82.5, 9.25)], "logic", head="both")
    box(ax, 112, 7, 120, 30, "CR\nJ101", fs=FS_S, weight="bold", r=0.6)
    wire(ax, [(108.5, 14), (112, 14)], "logic")
    wire(ax, [(120, 14), (138, 14)], "logic")
    wire(ax, [(138, 27), (120, 27)], "logic")
    text(ax, 129, 19.3, "CE_DRV,\nILIM_REL_A/B,\nRFC_OFF,\n3V3 x 2", fs=FS_XS, color=LOGIC)
    text(ax, 129, 28.4, "STAT", fs=FS_XS, color=LOGIC)
    text(ax, 129, 7.8, "W5 14-way\nribbon (4 GND)", fs=FS_XS, color=INK)
    box(ax, 138, 7, 145, 30, "EIB\nJ201", fs=FS_S, weight="bold", r=0.6)
    wire(ax, [(145, 14), (148.5, 14)], "logic")
    wire(ax, [(148.5, 27), (145, 27)], "logic")
    box(ax, 148.5, 5, 176.5, 40, "", fs=FS_S)
    text(ax, 162.5, 36.6, "EIB drivers", fs=FS_S, weight="bold", container=(148.5, 5, 176.5, 40))
    text(ax, 162.5, 34.6, va="top", s=
        "2-layer, beside the EVM\n\nU201/U202 open-drain\ndrivers, Q201-Q203\n\nE leads to EVM test points:\n"
        "E5 /CE: TP36\nE2: JP14 pin 2\nE3: TP33\nE7 STAT: TP38\nE1 REGN: JP12\nE8 AGND: TP49", fs=FS_S,
        container=(148.5, 5, 176.5, 40))
    # EIB <-> EVM leads
    wire(ax, [(159, 40), (159, 60)], "logic")
    wire(ax, [(166.5, 40), (166.5, 60)], "logic")
    wire(ax, [(173.5, 60), (173.5, 40)], "logic")
    text(ax, 159, 52.2, "/CE\n(E5)", fs=FS_XS, bg=True, color=LOGIC)
    text(ax, 166.5, 52.2, "ILIM_HIZ\n(E2, E3)", fs=FS_XS, bg=True, color=LOGIC)
    text(ax, 173.5, 52.2, "STAT\n(E7)", fs=FS_XS, bg=True, color=LOGIC)
    # E1 REGN (EVM JP12 -> EIB driver supply) and E8 AGND (TP49, the only EIB-to-EVM ground) (README Table 2.2)
    wire(ax, [(162.5, 60), (162.5, 40)], "logic")
    text(ax, 162.5, 44.6, "REGN\n(E1)", fs=FS_XS, bg=True, color=LOGIC)
    wire(ax, [(170, 60), (170, 40)], head="none", color=INK)
    text(ax, 170, 44.6, "AGND\n(E8)", fs=FS_XS, bg=True, color=INK)

    # ---- Teensy and taps ----
    box(ax, 27, 18, 66, 39, "", fs=FS)
    text(ax, 35.3, 28.5, "Teensy 4.1\non MB J1/J2\n(Dubox 2 x 24)", fs=FS_S, weight="bold", container=(27, 18, 66, 39))
    text(ax, 65.2, 33.2, "pins 18/19 SDA/SCL", fs=FS_XS, ha="right", va="bottom", container=(27, 18, 66, 39))
    text(ax, 65.2, 28.2, "pin 6 STAT", fs=FS_XS, ha="right", va="bottom", container=(27, 18, 66, 39))
    text(ax, 65.2, 22.2, "pin 5 CHG_ARM", fs=FS_XS, ha="right", va="bottom", container=(27, 18, 66, 39))
    box(ax, 3.5, 17.5, 22.5, 41.5, "", fs=FS_S)
    taps = ("Tap conductors\n"
            "T1 V-MOT\n  (C-D6, R170)\nT2 VBUS\n  (C-D2, R171)\nT5 pin-31 EN net\n  (MB J1.45)\n"
            "T6 3V3 (MB J1.29)\nT10 pin 33 CHG_QUAL\n  (MB J2.47)\nT13 pin 34\n  CHG_H1_RB\n"
            "T16 pin 35\n  CHG_EFUSE_FLT\nT17 pin 22 CHG_IIN\nT7b, T17r shields")
    text(ax, 4.4, 40.6, taps, fs=FS_S, ha="left", va="top", container=(3.5, 17.5, 22.5, 41.5))
    wire(ax, [(13, 17.5), (13, 9.25), (69.5, 9.25)], "logic", head="both")
    text(ax, 46, 13.6, "10 tap conductors, cable Molex 2147581101\nTeensy headers: T5, T6, T10, T13, T16, T17\n"
         "(T13, T16, T17 are readbacks to the Teensy)",
         fs=FS_XS, color=LOGIC)
    wire(ax, [(22.5, 28.5), (27, 28.5)], "logic", head="both")
    # Teensy -> MB switch and boost enables (Table 2.1)
    # one wide bridge carries the enables wire over both tap lines (T1 at y 50.3, T2 at y 49.5)
    _wire_with_hops(ax, [(31, 39), (31, 52)], [(31, 49.9)], LOGIC, 1.3, 4, r=1.6)
    wire(ax, [(31, 51.0), (31, 52)], "logic")
    # T1 and T2 are soldered to R170/R171 at the MB divider tops C-D6 (V-MOT) and C-D2 (VBUS)
    # (README section 8, PM3); they reach the tap field from the power nodes, not from the Teensy
    wire(ax, [(42, 64.3), (45, 64.3), (45, 50.3), (28.9, 50.3), (28.9, 40.6), (22.5, 40.6)], "logic",
         lw=0.9, hops=[(45, 56.5)])
    text(ax, 45.6, 53.6, "T1 (C-D6, R170)", fs=FS_XS, ha="left", color=LOGIC)
    wire(ax, [(55, 76.5), (65.5, 76.5), (65.5, 49.5), (29.7, 49.5), (29.7, 39.9), (22.5, 39.9)], "logic",
         lw=0.9, hops=[(65.5, 56.5)])
    text(ax, 65.0, 61.0, "T2 (C-D2, R171)", fs=FS_XS, ha="right", color=LOGIC)
    text(ax, 32.3, 43.8, "RT1987 and boost\nenables, pins 3, 4,\n27-32; fan out to the\nMB switch labels",
         fs=FS_XS, ha="left", color=LOGIC)

    # ---- legend ----
    ly = -4.5
    ax.plot([4, 14], [ly, ly], color=POWER, lw=3.2, zorder=4)
    text(ax, 15.5, ly, "Power conductor (arrow = direction of power flow)", fs=FS_S, ha="left")
    ax.plot([66, 76], [ly, ly], color=LOGIC, lw=1.3, zorder=4)
    text(ax, 77.5, ly, "Logic or analog signal (arrow = direction)", fs=FS_S, ha="left")
    ax.add_patch(FancyBboxPatch((124, ly - 2), 10, 4, boxstyle="round,pad=0,rounding_size=0.8",
                                fc="#F4F4F4", ec=GREY, lw=1.2, ls=(0, (5, 3)), zorder=1))
    text(ax, 135.5, ly, "Board region", fs=FS_S, ha="left")
    text(ax, 153, ly, "Switch labels: refdes (signal, Teensy pin)", fs=FS_XS, ha="left", color=GREY)

    probs = check_layout(fig, "fig2_1_block_diagram")
    save(fig, "fig2_1_block_diagram")
    return probs


# --------------------------------------------------------------------------------------------
# Figure 5.1: permit gate, gate level
# --------------------------------------------------------------------------------------------
def and_gate(ax, x, yc, n=2, w=10.0):
    h = 10.0 if n == 2 else 13.0
    r = h / 2
    xs = x + w - r
    verts = [(x, yc - r), (x, yc + r), (xs, yc + r)]
    codes = [Path.MOVETO, Path.LINETO, Path.LINETO]
    k = 0.5523 * r
    verts += [(xs + k, yc + r), (xs + r, yc + k), (xs + r, yc),
              (xs + r, yc - k), (xs + k, yc - r), (xs, yc - r), (x, yc - r)]
    codes += [Path.CURVE4] * 6 + [Path.CLOSEPOLY]
    ax.add_patch(PathPatch(Path(verts, codes), fc="white", ec=INK, lw=1.4, zorder=3))
    ins = [yc + 2.5, yc - 2.5] if n == 2 else [yc + 4.0, yc, yc - 4.0]
    return [(x, y) for y in ins], (x + w, yc)


def or_gate(ax, x, yc, w=10.0, h=10.0, d=2.6):
    yt, yb = yc + h / 2, yc - h / 2
    verts = [(x, yt), (x + 0.55 * w, yt), (x + w, yc),
             (x + 0.55 * w, yb), (x, yb),
             (x + d, yc), (x, yt)]
    codes = [Path.MOVETO, Path.CURVE3, Path.CURVE3, Path.CURVE3, Path.CURVE3, Path.CURVE3, Path.CURVE3]
    ax.add_patch(PathPatch(Path(verts, codes), fc="white", ec=INK, lw=1.4, zorder=3))

    def xback(y):
        t = (yt - y) / h
        return x + 2 * t * (1 - t) * d

    ins = [yc + 2.5, yc - 2.5]
    return [(xback(y), y) for y in ins], (x + w, yc)


def not_gate(ax, x, yc, w=6.0, h=6.0, color=INK, fc="white"):
    ax.add_patch(Polygon([(x, yc + h / 2), (x, yc - h / 2), (x + w, yc)], closed=True, fc=fc, ec=color,
                         lw=1.4, zorder=3))
    ax.add_patch(Circle((x + w + 0.7, yc), 0.7, fc=fc, ec=color, lw=1.2, zorder=3))
    return (x, yc), (x + w + 1.4, yc)


def comparator(ax, x, yc, w=10.0, h=10.0):
    ax.add_patch(Polygon([(x, yc + h / 2), (x, yc - h / 2), (x + w, yc)], closed=True, fc="white", ec=INK,
                         lw=1.4, zorder=3))
    text(ax, x + 1.4, yc + 2.4, "+", fs=FS, check=False)
    text(ax, x + 1.4, yc - 2.4, "−", fs=FS, check=False)
    return (x, yc + 2.4), (x, yc - 2.4), (x + w, yc)


def resistor(ax, x, y, label, w=6.0, h=2.0):
    ax.add_patch(Rectangle((x, y - h / 2), w, h, fc="white", ec=INK, lw=1.2, zorder=3))
    text(ax, x + w / 2, y + h / 2 + 0.3, label, fs=FS_XS, va="bottom")
    return (x, y), (x + w, y)


def ground(ax, x, y):
    ax.plot([x, x], [y, y - 1.2], color=INK, lw=1.1, zorder=4)
    for i, hw in enumerate((1.4, 0.9, 0.4)):
        yy = y - 1.2 - i * 0.55
        ax.plot([x - hw, x + hw], [yy, yy], color=INK, lw=1.1, zorder=4)


def pin(ax, x, y, s, side="in"):
    if side == "in":
        text(ax, x - 0.4, y + 0.35, s, fs=6.3, ha="right", va="bottom", color=GREY)
    else:
        text(ax, x + 0.4, y - 0.35, s, fs=6.3, ha="left", va="top", color=GREY)


def gate_label(ax, x, y, s):
    text(ax, x, y, s, fs=FS_XS, weight="bold", va="bottom")


def net(ax, x, y, s, ha="left", va="bottom"):
    text(ax, x, y, s, fs=FS_XS, ha=ha, va=va, color=LOGIC, weight="bold")


def fig5_1():
    fig, ax = new_canvas(0, 184, -2, 112)
    C = LOGIC

    # ---------------- inputs ----------------
    # comparators (outputs: pin 1 of each TLV3012B)
    cx = 28
    yH1, yUVB, yFON, yFOFF = 96, 78, 64, 50
    yQUAL, yP5 = 30, 20

    p, m, oH1 = comparator(ax, cx, yH1)
    text(ax, cx - 3.0, p[1], "T1 V-MOT (R109/R110)", fs=FS_XS, ha="right")
    text(ax, cx - 3.0, m[1], "T2 VBUS (R111/R112)", fs=FS_XS, ha="right")
    gate_label(ax, cx + 4, yH1 + 5.6, "U102 TLV3012B")
    p, m, oUVB = comparator(ax, cx, yUVB)
    text(ax, cx - 3.0, p[1], "T2 VBUS (R114/R115)", fs=FS_XS, ha="right")
    text(ax, cx - 3.0, m[1], "REF103", fs=FS_XS, ha="right")
    gate_label(ax, cx + 4, yUVB + 5.6, "U103 TLV3012B")
    p, m, oFON = comparator(ax, cx, yFON)
    text(ax, cx - 3.0, p[1], "T5 FCC (R122, R188/R189)", fs=FS_XS, ha="right")
    text(ax, cx - 3.0, m[1], "REF120", fs=FS_XS, ha="right")
    gate_label(ax, cx + 4, yFON + 5.6, "U120 TLV3012B")
    p, m, oFOFF = comparator(ax, cx, yFOFF)
    text(ax, cx - 3.0, p[1], "REF119/3 (R184/R185)", fs=FS_XS, ha="right")
    text(ax, cx - 3.0, m[1], "T5 FCC (R122, R186; R187 to 3V3)", fs=FS_XS, ha="right")
    gate_label(ax, cx + 4, yFOFF + 5.6, "U119 TLV3012B")
    # TLV3012B package pins (cr/cr.net): IN+ 3, IN- 4, OUT 1 on all four comparators
    for yc in (yH1, yUVB, yFON, yFOFF):
        wire(ax, [(cx - 2.6, yc + 2.4), (cx, yc + 2.4)], head="none", color=INK)
        wire(ax, [(cx - 2.6, yc - 2.4), (cx, yc - 2.4)], head="none", color=INK)
        pin(ax, cx, yc + 2.4, "3")
        pin(ax, cx, yc - 2.4, "4")
        pin(ax, cx + 10.0, yc, "1", "out")
    # H1 hysteresis: R113 6.49 MOhm from U102 OUT (net H1) to U102 IN+ (N_H1P, R109/R110 node) (cr/cr.net);
    # sets the 0.30 V hysteresis of README Table 5.1 (rise 17.31 V, fall 17.01 V)
    dot(ax, cx + 13.5, yH1)
    wire(ax, [(cx + 13.5, yH1), (cx + 13.5, yH1 + 9.5), (cx - 1.9, yH1 + 9.5), (cx - 1.9, yH1 + 2.4)],
         head="none")
    dot(ax, cx - 1.9, yH1 + 2.4)
    ax.add_patch(Rectangle((cx + 2.0, yH1 + 8.5), 6.0, 2.0, fc="white", ec=INK, lw=1.2, zorder=5))
    text(ax, cx + 5.0, yH1 + 10.8, "R113 6.49 MOhm (hysteresis)", fs=FS_XS, va="bottom")
    # UVB hysteresis: R116 10.0 MOhm from U103 OUT (net UVB, R116.1) to U103 IN+ (N_UVP, R114/R115 node,
    # R116.2) (cr/cr.net; design document B.8 row U103)
    dot(ax, cx + 13.5, yUVB)
    wire(ax, [(cx + 13.5, yUVB), (cx + 13.5, yUVB + 9.5), (cx - 1.9, yUVB + 9.5), (cx - 1.9, yUVB + 2.4)],
         head="none")
    dot(ax, cx - 1.9, yUVB + 2.4)
    ax.add_patch(Rectangle((cx + 2.0, yUVB + 8.5), 6.0, 2.0, fc="white", ec=INK, lw=1.2, zorder=5))
    text(ax, cx + 5.0, yUVB + 10.8, "R116 10.0 MOhm (hysteresis)", fs=FS_XS, va="bottom")

    # meanings (Table 5.1)
    mx = 1.0
    text(ax, mx, yH1 + 6.2, "H1: V-MOT > 1.089 x VBUS", fs=FS_XS, ha="left", color=GREY)
    text(ax, mx, yUVB + 6.2, "UVB: VBUS > 13.33 V (fall)", fs=FS_XS, ha="left", color=GREY)
    text(ax, mx, yFON + 6.2, "FCC_ON: EN > 1.75-1.88 V", fs=FS_XS, ha="left", color=GREY)
    text(ax, mx, yFOFF + 6.2, "FCC_OFF: EN < 0.39-0.44 V", fs=FS_XS, ha="left", color=GREY)

    # Teensy commands
    resistor(ax, 14, yQUAL, "R147 " + chr(10) + "1.00 kOhm")
    text(ax, 13.4, yQUAL, "CHG_QUAL\nTeensy pin 33\nJ-TAP B5 (T10)", fs=FS_XS, ha="right")
    wire(ax, [(20, yQUAL), (38, yQUAL)], head="none")
    dot(ax, 23, yQUAL)
    wire(ax, [(23, yQUAL), (23, yQUAL - 2.5)], head="none")
    ax.add_patch(Rectangle((22, yQUAL - 6.5), 2, 4, fc="white", ec=INK, lw=1.2, zorder=3))
    text(ax, 24.6, yQUAL - 4.5, "R123\n47.0 kOhm", fs=FS_XS, ha="left")
    ground(ax, 23, yQUAL - 6.5)

    text(ax, 13.4, yP5, "CHG_ARM\nTeensy pin 5\nCR J1 pad 11", fs=FS_XS, ha="right")
    wire(ax, [(14, yP5), (38, yP5)], head="none")
    dot(ax, 23, yP5)
    wire(ax, [(23, yP5), (23, yP5 - 2.5)], head="none")
    ax.add_patch(Rectangle((22, yP5 - 6.5), 2, 4, fc="white", ec=INK, lw=1.2, zorder=3))
    text(ax, 24.6, yP5 - 4.5, "R108\n47.0 kOhm", fs=FS_XS, ha="left")
    ground(ax, 23, yP5 - 6.5)

    # input net names at the gate column boundary
    net(ax, 39.5, yH1 + 0.4, "H1")
    net(ax, 42.2, yUVB + 0.4, "UVB")   # right of the R116 junction
    net(ax, 39.5, yFON + 0.4, "FCC_ON")
    net(ax, 39.5, yFOFF + 0.4, "FCCN = FCC_OFF")
    net(ax, 30.0, yQUAL + 0.4, "QUAL")
    net(ax, 30.0, yP5 + 0.4, "P5")

    # ---------------- stage 1 ----------------
    s1 = 56
    ins, oH1U = and_gate(ax, s1, 85)                         # U118A: H1 AND UVB
    gate_label(ax, s1 + 5, 90.6, "U118A  AND")
    wire(ax, [oH1, (50, yH1), (50, ins[0][1]), ins[0]], head="none")
    wire(ax, [oUVB, (50, yUVB), (50, ins[1][1]), ins[1]], head="none")
    pin(ax, *ins[0], "1")
    pin(ax, *ins[1], "2")
    pin(ax, *oH1U, "7", "out")
    # H1 readback: R126 -> J-TAP A5 (T13) -> Teensy pin 34
    dot(ax, 44, yH1)
    wire(ax, [(44, yH1), (44, 101), (56, 101)], head="none")
    resistor(ax, 56, 101, "R126 1.00 kOhm")
    wire(ax, [(62, 101), (70, 101)])
    text(ax, 71, 101, "J-TAP A5 (T13): H1 readback to Teensy pin 34 (CHG_H1_RB)", fs=FS_XS, ha="left")

    a, oFCCNN = not_gate(ax, s1, yFOFF)                       # U105 s1: NOT FCCN
    gate_label(ax, s1 + 3.5, yFOFF + 3.6, "U105 s1  NOT")
    wire(ax, [oFOFF, a], head="none")
    pin(ax, *a, "1")
    pin(ax, *oFCCNN, "7", "out")

    a, oP5N = not_gate(ax, s1, yP5)                           # U105 s2: NOT P5
    gate_label(ax, s1 + 3.5, yP5 + 3.6, "U105 s2  NOT")
    wire(ax, [(38, yP5), a], head="none")
    pin(ax, *a, "3")
    pin(ax, *oP5N, "5", "out")

    # spare section
    a, o = not_gate(ax, s1, 5, color=GREY, fc="#F2F2F2")
    wire(ax, [(s1 - 3, 5), a], head="none", color=GREY)
    ground(ax, s1 - 3, 5)
    pin(ax, *a, "6")
    pin(ax, *o, "2 nc", "out")
    text(ax, s1 + 3.5, 8.6, "U105 s3 spare: 3A to GND, 3Y nc", fs=FS_XS, va="bottom", color=GREY)

    # ---------------- stage 2 ----------------
    s2 = 76
    ins, oFCCP = and_gate(ax, s2, 61)                         # U118B: FCC_ON AND FCCNN
    gate_label(ax, s2 + 5, 66.6, "U118B  AND")
    wire(ax, [oFON, (72, yFON), (72, ins[0][1]), ins[0]], head="none")
    wire(ax, [oFCCNN, (70, yFOFF), (70, ins[1][1]), ins[1]], head="none")
    net(ax, oFCCNN[0] + 1.0, yFOFF + 0.4, "FCCNN")
    pin(ax, *ins[0], "5")
    pin(ax, *ins[1], "6")
    pin(ax, *oFCCP, "3", "out")

    ins3, oQF = and_gate(ax, s2, 30, n=3, w=11)               # U107: QUAL AND FCCN AND P5N
    gate_label(ax, s2 + 5.5, 37.2, "U107  AND (3-input)")
    # FCCN branch down to U107 B and across to U106B
    jx = 44
    dot(ax, jx, yFOFF)
    wire(ax, [(jx, yFOFF), (jx, ins3[0][1]), ins3[0]], head="none")   # top input: FCCN (pin 3)
    wire(ax, [(38, yQUAL), ins3[1]], head="none")  # QUAL (pin 1)
    wire(ax, [oP5N, (70, yP5), (70, ins3[2][1]), ins3[2]], head="none")  # P5N (pin 6)
    net(ax, oP5N[0] + 1.0, yP5 + 0.4, "P5N")
    pin(ax, *ins3[0], "3")
    pin(ax, *ins3[1], "1")
    pin(ax, *ins3[2], "6")
    pin(ax, *oQF, "4", "out")

    # ---------------- stage 3 ----------------
    s3 = 102
    insA, oGATE = or_gate(ax, s3, 74)                         # U110A: H1U OR FCCP
    gate_label(ax, s3 + 5, 79.6, "U110A  OR")
    insB, oRFC = or_gate(ax, s3, 44)                          # U106B: FCCN OR H1U
    gate_label(ax, s3 + 5, 49.6, "U106B  OR")
    hx = 94
    # H1U rail: from U118A, taps into U110A (pin 1) and U106B (pin 6); bridges FCCP
    wire(ax, [oH1U, (hx, 85), (hx, insB[0][1]), insB[0]], head="none", hops=[(hx, insA[1][1])])
    dot(ax, hx, insA[0][1])
    wire(ax, [(hx, insA[0][1]), insA[0]], head="none")
    net(ax, oH1U[0] + 1.6, 85.4, "H1U")
    # FCCP into U110A pin 2
    wire(ax, [oFCCP, (92, 61), (92, insA[1][1]), insA[1]], head="none")
    net(ax, oFCCP[0] + 1.2, 61.4, "FCCP")
    # FCCN into U106B pin 5
    dot(ax, jx, insB[1][1])
    wire(ax, [(jx, insB[1][1]), insB[1]], head="none")
    pin(ax, *insA[0], "1")
    pin(ax, *insA[1], "2")
    pin(ax, *oGATE, "7", "out")
    pin(ax, *insB[0], "6")
    pin(ax, *insB[1], "5")
    pin(ax, *oRFC, "3", "out")

    insC, oCE = or_gate(ax, s3, 12)                           # U106A: P5 OR GND (buffer)
    gate_label(ax, s3 + 5, 17.6, "U106A  OR (buffer)")
    dot(ax, 40, yP5)
    wire(ax, [(40, yP5), (40, 14.5), insC[0]], head="none")
    wire(ax, [(98, insC[1][1]), insC[1]], head="none")
    ground(ax, 98, insC[1][1])
    pin(ax, *insC[0], "1")
    pin(ax, *insC[1], "2")
    pin(ax, *oCE, "7", "out")

    # ---------------- stage 4 ----------------
    s4 = 124
    insD, oIL = or_gate(ax, s4, 62)                           # U110B: GATE OR QF
    gate_label(ax, s4 + 5, 67.6, "U110B  OR")
    wire(ax, [oGATE, (119, 74), (119, insD[0][1]), insD[0]], head="none")
    net(ax, oGATE[0] + 1.0, 74.4, "GATE")
    wire(ax, [oQF, (120.5, 30), (120.5, insD[1][1]), insD[1]], head="none", hops=[(120.5, 44)])
    net(ax, oQF[0] + 1.2, 30.4, "QF")
    pin(ax, *insD[0], "5")
    pin(ax, *insD[1], "6")
    pin(ax, *oIL, "3", "out")

    # ---------------- outputs ----------------
    rx = 145
    # ILIM_REL -> R131A/R131B -> J101.7/.8
    dot(ax, 142, 62)
    wire(ax, [oIL, (142, 62), (142, 66), (rx, 66)], head="none")
    wire(ax, [(142, 62), (142, 58), (rx, 58)], head="none")
    net(ax, oIL[0] + 1.0, 62.4, "ILIM_REL")
    resistor(ax, rx, 66, "R131A 100 ohm")
    resistor(ax, rx, 58, "R131B 100 ohm")
    wire(ax, [(rx + 6, 66), (155, 66)])
    wire(ax, [(rx + 6, 58), (155, 58)])
    text(ax, 155.8, 66, "J101.7  ILIM_REL_A", fs=FS_S, ha="left", weight="bold")
    text(ax, 155.8, 58, "J101.8  ILIM_REL_B", fs=FS_S, ha="left", weight="bold")
    text(ax, 155.8, 62, "EIB: Q203 feed (A), Q201 hold (B)", fs=FS_XS, ha="left", color=GREY)
    # RFC_OFF -> R132 -> J101.10
    wire(ax, [oRFC, (rx, 44)], head="none")
    net(ax, oRFC[0] + 1.0, 44.4, "RFC_OFF")
    resistor(ax, rx, 44, "R132 100 ohm")
    wire(ax, [(rx + 6, 44), (155, 44)])
    text(ax, 155.8, 44, "J101.10  RFC_OFF", fs=FS_S, ha="left", weight="bold")
    text(ax, 155.8, 40.6, "HIGH removes the FC clamp (Q202)", fs=FS_XS, ha="left", color=GREY)
    # CE_DRV -> R130 -> J101.5
    wire(ax, [oCE, (rx, 12)], head="none")
    net(ax, oCE[0] + 1.0, 12.4, "CE_DRV")
    resistor(ax, rx, 12, "R130 100 ohm")
    wire(ax, [(rx + 6, 12), (155, 12)])
    text(ax, 155.8, 12, "J101.5  CE_DRV", fs=FS_S, ha="left", weight="bold")
    text(ax, 155.8, 8.6, "EIB U201 ch1: /CE = NOT P5 at the EVM", fs=FS_XS, ha="left", color=GREY)

    # ---------------- equations and notes ----------------
    ex, ey = 128, 108.5
    text(ax, ex, ey,
         "ILIM_REL = (H1 AND UVB) OR (FCC_ON AND NOT FCC_OFF)\n"
         "                 OR (QUAL AND FCC_OFF AND NOT P5)\n"
         "CE_DRV   = P5 (buffered), so /CE = NOT P5\n"
         "RFC_OFF  = FCC_OFF OR (H1 AND UVB)",
         fs=FS_XS, ha="left", va="top", style="normal")
    text(ax, 1.0, -0.6,
         "Small grey numbers are package pin numbers (B.8; U107 SOT-23 DBV pin numbers TODO(verify: SCES487I)). "
         "A bridge marks a crossing with no connection; a dot marks a junction. All logic VCC = 3V3 via T6.",
         fs=FS_XS, ha="left", va="bottom", color=GREY)

    probs = check_layout(fig, "fig5_1_permit_gate")
    save(fig, "fig5_1_permit_gate")
    return probs


def main():
    probs = fig2_1() + fig5_1()
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
