"""Simplified walkthrough diagrams for the round-4 BQ25798EVM carrier design, revision r8 (file names keep "r7").

Emits four hand-style SVGs next to this script (same drawing style as ../../round3/walkthrough/fig1-fig4):

  fig1_power_path_r7.svg     power path VBUS/V-MOT -> CR -> EVM -> pack, EIB on the EVM plate, taps; r7 items marked
  fig2_plan_view_r7.svg      top-view plan of the MB region around the CR (r7 outline, tabs, feet, tap field, W-lead path)
  fig3_side_stack_r7.svg     (a) side section through tab Y: stack heights, FT2 bed, B3 post, trunk and W5 stacked,
                             3-D clearance to L-FC; (b) side section through the B1R riser wedge (r8)
  fig4_assembly_order_r7.svg PM build order with the measurement gates MS1-MS8

Sources (read at run time, nothing is computed that the calc does not already state):
  ../calc/r7_calc_out.json         H.23 outputs (outline, feet, tap grid, dressing waypoints, routes, heights)
  ../calc/mb_neighbours_out.json   MB part boxes from the .brd (REG-5V, L-FC, J1, U$1)
  ../../../../charger_bq25798_wiring_design_2026-11-05.md  the values quoted in labels (A.3, A.7, A.8, B.4, D.1, I)

Coordinates: Eagle .brd board coordinates, mm, top view, +x right, +y UP.
Standard library only. Run: python -I make_diagrams_r7.py
"""
import json
import math
import os
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
CALC = os.path.join(HERE, "..", "calc")
J = json.load(open(os.path.join(CALC, "r7_calc_out.json"), encoding="utf-8"))
MB = json.load(open(os.path.join(CALC, "mb_neighbours_out.json"), encoding="utf-8"))
MBP = {e["name"]: e["bbox"] for e in MB["near"]}

# palette (round-3 walkthrough colours)
INK = "#222"
GREY = "#555"
SW_BLUE = "#d9e8fb"     # RT1987 switch
SRC = "#fde8c8"         # source
NEUTRAL = "#eeeeee"
CR_FILL = "#ffe0d0"
CR_EDGE = "#c0502a"
EVM_FILL = "#dff2df"
EVM_EDGE = "#2a7a2a"
NOTE_FILL = "#f6f6f6"
R7 = "#7b1fa2"          # marks an item new in r7
R7_FILL = "#f3e5f5"
R8 = "#ad1457"          # marks an item new or changed in r8 (audit run 001)
R8_FILL = "#fce4ec"
WARN = "#c62828"


class Svg:
    def __init__(self, w, h, title):
        self.w, self.h = w, h
        self.el = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
            'font-family="Helvetica, Arial, sans-serif" font-size="12">' % (w, h, w, h),
            '<rect width="%d" height="%d" fill="#ffffff"/>' % (w, h),
            '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#222"/></marker>'
            '<marker id="ap" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="%s"/></marker>'
            '<marker id="ap8" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
            'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="%s"/></marker></defs>' % (R7, R8),
            '<text x="20" y="28" font-size="16" font-weight="bold">%s</text>' % escape(title),
        ]

    def add(self, s):
        self.el.append(s)

    def rect(self, x, y, w, h, fill="none", stroke=INK, sw=1.0, dash=None, rx=0, op=None):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        o = ' fill-opacity="%s"' % op if op is not None else ""
        r = ' rx="%g"' % rx if rx else ""
        self.add('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"%s stroke="%s" stroke-width="%g"%s%s/>'
                 % (x, y, w, h, fill, o, stroke, sw, d, r))

    def text(self, x, y, s, size=12, color=INK, bold=False, anchor="start", italic=False):
        b = ' font-weight="bold"' if bold else ""
        a = ' text-anchor="%s"' % anchor if anchor != "start" else ""
        i = ' font-style="italic"' if italic else ""
        c = ' fill="%s"' % color if color != INK else ""
        sz = ' font-size="%g"' % size if size != 12 else ""
        self.add('<text x="%.1f" y="%.1f"%s%s%s%s%s>%s</text>' % (x, y, sz, b, a, i, c, escape(s)))

    def lines(self, x, y, rows, size=12, color=INK, dy=None, bold_first=False):
        dy = dy or size + 3
        for k, r in enumerate(rows):
            self.text(x, y + k * dy, r, size, color, bold=(bold_first and k == 0))

    def line(self, x1, y1, x2, y2, stroke=INK, sw=1.0, dash=None, arrow=None):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        m = ' marker-end="url(#%s)"' % arrow if arrow else ""
        self.add('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%g"%s%s/>'
                 % (x1, y1, x2, y2, stroke, sw, d, m))

    def path(self, d, stroke=INK, sw=2.5, fill="none", dash=None, arrow=None, op=None, cap=None):
        ds = ' stroke-dasharray="%s"' % dash if dash else ""
        m = ' marker-end="url(#%s)"' % arrow if arrow else ""
        o = ' stroke-opacity="%s"' % op if op is not None else ""
        c = ' stroke-linecap="%s" stroke-linejoin="round"' % cap if cap else ""
        self.add('<path d="%s" stroke="%s" stroke-width="%g" fill="%s"%s%s%s%s/>' % (d, stroke, sw, fill, ds, m, o, c))

    def poly(self, pts, stroke=INK, sw=1.5, fill="none", dash=None, closed=True, op=None, cap=None):
        d = "M" + " L".join("%.1f,%.1f" % p for p in pts) + (" Z" if closed else "")
        if op is not None and fill != "none":
            ds = ' stroke-dasharray="%s"' % dash if dash else ""
            self.add('<path d="%s" stroke="%s" stroke-width="%g" fill="%s" fill-opacity="%s"%s/>' % (d, stroke, sw, fill, op, ds))
        else:
            self.path(d, stroke, sw, fill, dash, op=op, cap=cap)

    def circle(self, x, y, r, fill="none", stroke=INK, sw=1.0, dash=None):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        self.add('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" stroke="%s" stroke-width="%g"%s/>' % (x, y, r, fill, stroke, sw, d))

    def r7tag(self, x, y, tag="r7", col=R7):
        """Small 'r7' (purple) or 'r8' (magenta) badge with its top-left corner at (x, y)."""
        self.rect(x, y, 22, 14, fill=col, stroke=col, rx=3)
        self.text(x + 11, y + 11, tag, 11, "#ffffff", bold=True, anchor="middle")

    def r8tag(self, x, y):
        self.r7tag(x, y, "r8", R8)

    def save(self, name):
        self.el.append("</svg>")
        with open(os.path.join(HERE, name), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(self.el) + "\n")
        print("wrote", name)


# ---------------------------------------------------------------------------------------------------------------------
# D1  power path
# ---------------------------------------------------------------------------------------------------------------------
def fig1():
    s = Svg(1320, 652, "Fig 1. Power path with the BQ25798EVM, r8 (simplified)")
    s.text(20, 46, "Blue = RT1987 ideal-diode switch: conducts left-to-right only, while its EN (Teensy pin) is HIGH. "
                   "Purple + r7 badge = new or changed in r7 (round 4); magenta + r8 badge = new or changed in r8 "
                   "(audit run 001).", 12, GREY)

    # VBUS bar
    s.line(400, 75, 400, 305, sw=4)
    s.text(372, 68, "VBUS 16.0 V", bold=True)
    # FC row
    s.rect(12, 80, 112, 40, SRC); s.lines(20, 98, ["H-20 fuel", "cell 7-11 V"])
    s.rect(140, 80, 120, 40, NEUTRAL); s.lines(148, 98, ["FC boost", "TPS61288 + INA253"])
    s.rect(290, 82, 90, 36, SW_BLUE); s.lines(297, 98, ["D-FC-EN", "FC_BUS (27)"])
    s.path("M124 100 H140 M260 100 H290 M380 100 H400")
    # BT row
    s.rect(12, 255, 112, 40, SRC); s.lines(20, 273, ["2S pack", "7.4-8.4 V (VBT)"])
    s.rect(140, 255, 120, 40, NEUTRAL); s.lines(148, 273, ["BT boost", "TPS61288 + INA253"])
    s.rect(290, 257, 90, 36, SW_BLUE); s.lines(297, 273, ["D-BT-EN", "BT_BUS (28)"])
    s.path("M124 275 H140 M260 275 H290 M380 275 H400")
    # motor path
    s.rect(425, 82, 105, 36, SW_BLUE); s.lines(432, 98, ["D-MT-EN", "MOT_PWR (29)"])
    s.path("M400 100 H425 M530 100 H560")
    s.line(560, 75, 560, 180, sw=4)
    s.text(568, 70, "V-MOT", bold=True)
    s.rect(610, 58, 130, 40, NEUTRAL); s.lines(618, 75, ["VESC + motor", "(regen source)"])
    s.path("M560 78 H610")
    # charge input switches
    s.rect(425, 212, 122, 36, SW_BLUE); s.lines(432, 228, ["D-BC-FC", "FC_CHARGE (31)"])
    s.path("M400 230 H425 M547 230 H690")
    s.rect(585, 152, 90, 36, SW_BLUE); s.lines(592, 168, ["D-BC-RG", "REGEN (30)"])
    s.path("M560 170 H585 M675 170 H690")
    s.line(690, 150, 690, 245, sw=4)
    s.text(650, 140, "VCHG-IN", bold=True)
    s.text(612, 264, "(CHG pad 10 pin)", 11, GREY)

    # CR carrier
    s.rect(712, 120, 170, 190, CR_FILL, CR_EDGE, sw=2)
    s.text(720, 138, "CR carrier", bold=True)
    s.lines(720, 156, ["eFuse U101 TPS26630", "I_OL 2.05-2.41 A", "OVP 23.12 V",
                       "D107 TVS on IN", "D103 Schottky on OUT", "comparators + permit", "logic, QUAL one-shot,",
                       "heartbeat monostable"], 11, dy=14)
    s.text(720, 300, "on the 22 Ag105 holes", 11, GREY)
    s.path("M690 200 H712")
    # r7 outline note on CR
    s.rect(712, 318, 170, 46, R7_FILL, R7, sw=1.5, dash="5,3")
    s.r7tag(716, 322)
    s.lines(742, 333, ["tab X + tab Y, feet", "FT1/FT2; 47.30 x 41.86 mm"], 11, R7, dy=14)
    # r8 items on the CR (B.4 R106s, H.23(n); A.3 B1R, H.23(s))
    s.rect(712, 372, 170, 76, R8_FILL, R8, sw=1.5, dash="5,3")
    s.r8tag(716, 376)
    s.lines(742, 387, ["R106s 1.00 kOhm 1 %:", "U101 FLT -> F17 (T16);", "FLT sink <= 3.377 mA"], 11, R8, dy=14)
    s.text(720, 443, "B1R wedge, B3 post 10.7 mm", 11, R8)

    # W1/W2 (r7 fixed length; r8 wire specification, A.3 / H.23(p))
    s.path("M882 160 H1015", sw=2.5)
    s.text(890, 150, "W1/W2", bold=True)
    s.r7tag(942, 139)
    s.r8tag(966, 139)
    s.text(890, 178, "fixed 0.30 m +-10 mm", 11, R7)
    s.lines(890, 196, ["20 AWG stranded,", "OD 1.60-1.75 mm,", "twist 20-25 mm"], 11, R8, dy=14)

    # EVM plate (r7) containing EVM and EIB
    s.rect(1000, 70, 300, 400, R7_FILL, R7, sw=1.5, dash="6,3")
    s.r7tag(1008, 77)
    s.text(1036, 88, "EVM plate (insulating, on the chassis,", 11, R7, bold=True)
    s.text(1036, 102, "past the MB +y edge); EVM and EIB co-mounted", 11, R7)
    s.rect(1015, 112, 130, 180, EVM_FILL, EVM_EDGE, sw=2)
    s.text(1022, 130, "BQ25798EVM", bold=True)
    s.lines(1022, 148, ["J1 VIN1 / PGND", "VINDPM 19.0 V", "(14.5 V in an", "FC window)", "", "J5 BATTERY / GND",
                        "IBAT sensed on", "the BAT+ side", "J8 I2C (0x6B)"], 11, dy=14)
    # EIB
    s.rect(1180, 120, 110, 172, "#ffffff", INK, sw=1.5)
    s.text(1188, 138, "EIB", bold=True)
    s.lines(1188, 155, ["36 x 24 mm", "E1-E8 leads,", "28 AWG Kynar,", "to EVM points"], 11, dy=14)
    s.rect(1186, 232, 98, 52, R7_FILL, R7, sw=1.2)
    s.r7tag(1190, 236)
    s.lines(1190, 263, ["R276 10 ohm", "in series E1"], 11, R7, dy=14)
    for yy in (150, 175, 200, 225):
        s.line(1180, yy, 1147, yy, arrow="a")
    s.lines(1015, 312, ["E1 REGN (JP12), E2 JP14 pin 2, E3 TP33,", "E4 JP21 pin 1, E5 TP36 (/CE drive),",
                        "E6 JP17 (/CE sense), E7 TP38 (STAT),", "E8 TP49 (AGND)"], 11, GREY, dy=14)

    # W5 ribbon CR -> EIB, W7 I2C CR -> EVM J8
    s.path("M882 290 H960 V390 H1240 V292", stroke="#00897b", sw=2, dash="6,3")
    s.path("M882 268 H940 V280 H1015", stroke="#1565c0", sw=1.5)
    s.line(1015, 420, 1045, 420, stroke="#00897b", sw=2, dash="6,3")
    s.text(1052, 424, "W5 14-way ribbon, J101 -> J201 (fixed 0.30 m)", 11, "#00897b")
    s.line(1015, 442, 1045, 442, stroke="#1565c0", sw=1.5)
    s.text(1052, 446, "W7 I2C triple SCL-GND-SDA -> EVM J8", 11, "#1565c0")

    # battery return W3/W4 -> CR -> D-BT-SQ -> pack
    s.path("M1015 270 H980 V480 H882", sw=2.5)
    s.text(900, 500, "W3/W4 18 AWG pair", bold=True, size=11)
    s.r7tag(1012, 489)
    s.text(1040, 500, "<= 0.30 m until MS2, then <= 200 mm route maximum", 11, R7)
    s.rect(712, 462, 170, 36, CR_FILL, CR_EDGE, sw=1.5)
    s.lines(720, 478, ["CR VCHG hole W3 to", "pads 18/19 (no eFuse)"], 11, dy=14)
    s.path("M712 480 H655")
    s.text(658, 470, "VCHG", bold=True)
    s.rect(560, 462, 95, 36, SW_BLUE); s.lines(567, 478, ["D-BT-SQ", "BT_SEQ (32)"])
    s.path("M560 480 H67 V295", arrow="a")
    s.text(260, 472, "charge current into the pack (VBT)")
    s.text(80, 320, "VBT also feeds the LM1084 5 V reg -> Teensy", 11, GREY)

    # taps
    s.rect(400, 330, 280, 110, "#fffbe6", "#b08900", sw=1.2)
    s.text(408, 348, "Taps CR -> MB (A.4)", bold=True)
    s.lines(408, 366, ["T1/T2 dividers via R170/R171 (V-MOT, VBUS)", "Teensy EN nets, 3V3, pins 5/6/7/18/19 ...",
                       "Kelvin at SNS-BT; T22 to BQ29200 pin 8", "via J1/J2 Teensy breakout"], 11, dy=14)
    s.rect(408, 422, 262, 14, R7_FILL, R7, sw=1)
    s.text(412, 433, "r7: 20 pads on tab X + F08-F10, F22 on footprint", 11, R7)
    s.path("M680 345 H698 V295 H712", stroke="#b08900", sw=1.5, dash="4,3")

    # ground note
    s.rect(20, 540, 1280, 98, NOTE_FILL, "#999")
    s.text(30, 560, "One ground.", bold=True)
    s.text(110, 560, "FC return, pack negative and the charger input and battery returns are all MB GND. The BQ25798 senses on the BAT+ / input")
    s.text(30, 577, "side, so a common ground is legal. The EVM and the EIB share the EVM plate (r7); the EIB's only circuit change in r7 is R276.")
    s.text(30, 594, "Loop to prevent: VBUS -> charger -> pack -> BT boost -> VBUS. It needs BT_BUS closed while the charger is fed from VBUS;")
    s.text(30, 611, "the permit logic on the CR forbids exactly that (design F.3). r7 moved no net, threshold or timing; r8 adds R106s in the FLT")
    s.text(30, 628, "readback path (CHG-R1-01) and states its firmware changes as requirements only (G.2, D.5).")
    s.save("fig1_power_path_r7.svg")


# ---------------------------------------------------------------------------------------------------------------------
# D2  plan view
# ---------------------------------------------------------------------------------------------------------------------
def fig2():
    X0, X1, Y0, Y1 = 0.0, 104.0, 30.0, 124.0
    K = 7.0
    OX, OY = 30, 70
    W = int(OX + (X1 - X0) * K + 330)
    H = int(OY + (Y1 - Y0) * K + 60)
    s = Svg(W, H, "Fig 2. Plan view of the MB region around the CR, r8 (top view, board mm, +y up; simplified)")
    s.text(20, 46, "Drawn: r7 outline, Ag105 footprint, feet, tap field, comparator band, W-lead dressing path with anchors "
                   "(r8: B1R wedge), polyimide strip, F17 / R106s (r8). MB parts are boxes only.", 12, GREY)

    def P(x, y):
        return (OX + (x - X0) * K, OY + (Y1 - y) * K)

    def R(x0, y0, x1, y1, **kw):
        x0c, x1c = max(x0, X0), min(x1, X1)
        y0c, y1c = max(y0, Y0), min(y1, Y1)
        a = P(x0c, y1c)
        s.rect(a[0], a[1], (x1c - x0c) * K, (y1c - y0c) * K, **kw)

    # frame and MB area
    R(X0, Y0, X1, Y1, fill="#ffffff", stroke="#999")
    R(X0, Y0, X1, 98.044, fill="#f4f4f2", stroke="none")
    edge = P(X0, 98.044)
    s.line(edge[0], edge[1], P(X1, 98.044)[0], edge[1], stroke="#37474f", sw=2.5)
    s.text(P(1, 99.2)[0], P(1, 99.2)[1], "MB +y edge (y 98.044)", 11, "#37474f", bold=True)
    s.text(P(1, 121.5)[0], P(1, 121.5)[1], "chassis (off the MB)", 11, GREY, italic=True)

    # MB parts
    for name, lab, fill in (("REG-5V", "LM1084 (REG-5V)", "#ffe0b2"), ("L-FC", "L-FC", "#e0e0e0"),
                            ("J1", "J1", "#eceff1"), ("U$1", "Teensy 4.1", "#eceff1"),
                            ("OP-FC", "OP-FC", "#eeeeee"), ("SNS-FC", "SNS-FC", "#eeeeee"),
                            ("D-FC-EN", "D-FC-EN", SW_BLUE)):
        b = MBP[name]
        if name == "L-FC":   # draw the Eaton 12.9 mm body (H.23(b)/(m)), not the .brd part box (1.012 mm from tab Y)
            b = [t[1] for t in J["m"]["trims"] if t[0].startswith("L-FC")][0]
        R(*b, fill=fill, stroke="#777", sw=1)
        cx = (max(b[0], X0) + min(b[2], X1)) / 2
        if name == "U$1":
            s.text(P(cx, 80)[0], P(cx, 80)[1], lab, 12, "#37474f", bold=True, anchor="middle")
        elif name == "J1":
            s.text(P(cx, 80)[0], P(cx, 80)[1], lab, 11, "#37474f", anchor="middle")
        elif name == "REG-5V":
            s.text(P(cx, 46.5)[0], P(cx, 46.5)[1], "LM1084", 12, "#bf360c", bold=True, anchor="middle")
            s.text(P(cx, 44.3)[0], P(cx, 44.3)[1], "(REG-5V)", 11, "#bf360c", anchor="middle")
        elif name == "L-FC":
            s.text(P(cx, 86.5)[0], P(cx, 86.5)[1], "L-FC (Eaton body)", 12, INK, bold=True, anchor="middle")
            s.text(P(cx, 84.3)[0], P(cx, 84.3)[1], "0.862 mm past tab Y", 11, GREY, anchor="middle")
        elif name == "D-FC-EN":
            pass
        else:
            s.text(P(cx, b[1] + 1.0)[0], P(cx, b[1] + 1.0)[1], lab, 11, GREY, anchor="middle")
    u = MBP["U$1"]
    tx, ty = P(u[0], 60)
    s.line(tx, ty - 60, tx, ty + 60, stroke="#37474f", sw=2)
    s.text(tx + 4, P(u[0], 66)[1], "Teensy edge", 11, "#37474f")
    s.text(tx + 4, P(u[0], 64)[1], "x 88.39", 11, "#37474f")
    d = MBP["D-FC-EN"]
    s.text(P(d[2] + 0.5, 74)[0], P(d[2] + 0.5, 74)[1], "D-FC-EN", 11, GREY)

    # polyimide strip: lead path band from the tab Y +x edge to the MB +y edge (bbox x 36.06-65.28, y 65.30-92.80)
    dw = J["l"]["dressing"]["waypoints"]

    def leave_box(c, p, half):
        """Point where the segment from the square centre c toward p leaves the square of half-side 'half'."""
        dx, dy = p[0] - c[0], p[1] - c[1]
        t = min(half / abs(dx) if dx else 1e9, half / abs(dy) if dy else 1e9)
        return (c[0] + t * dx, c[1] + t * dy)

    # Simplified: butt-capped bands along the lead path. The strip starts at the tab Y +x edge (x 37.56), stops at
    # each tie-base footprint (A1 6 x 6 mm, A2 10 x 10 mm) and ends at y 92.80 (design A.3; H.23(l) bbox).
    a1, a2 = tuple(dw["A1"]), tuple(dw["A2"])
    strip_w = 2 * (2.374 + 2.0) * K
    trunk_off = [(37.56, 71.1), tuple(dw["T5"]), tuple(dw["T6"]), leave_box(a1, dw["T6"], 3.0)]
    s.poly([P(*p) for p in trunk_off], stroke="#80cbc4", sw=strip_w, closed=False, op=0.45, cap="butt")
    s.poly([P(*p) for p in ((dw["WN"][0], a1[1] + 3.0), (dw["WN"][0], 92.8))], stroke="#80cbc4",   # WN lies inside A1
           sw=2 * (1.729 + 2.0) * K, closed=False, op=0.45, cap="butt")
    s.poly([P(*p) for p in (leave_box(a1, dw["E1"], 3.0), dw["E1"], leave_box(a2, dw["E1"], 5.0))], stroke="#80cbc4",
           sw=2 * (2.0 + 2.0) * K, closed=False, op=0.45, cap="butt")

    # Ag105 footprint and r7 outline
    vt = J["a"]["vertices"]
    s.poly([P(*v) for v in vt], stroke="#1565c0", sw=2.5, fill="#e3f2fd", op=0.55)
    s.poly([P(*v) for v in vt], stroke="#1565c0", sw=2.5)
    R(17.70, 34.14, 48.70, 67.14, fill="none", stroke="#455a64", sw=1.5, dash="6,4")

    # comparator band (footprint low-y band, A.8)
    R(23.15, 35.05, 42.43, 41.63, fill="#bbdefb", stroke="#1565c0", sw=1, dash="4,3")
    for yy, txt, bb in ((40.4, "comparator band", True), (38.6, "x 23.15-42.43", False), (36.9, "y 35.05-41.63", False)):
        c = P(35.0, yy)
        s.text(c[0], c[1], txt, 11, "#0d47a1", bold=bb, anchor="middle")
    # residual pads F08-F10, F22 on the low row y 35.80
    for x in (26.44, 28.98, 31.52, 41.68):
        a = P(x - 0.75, 35.80 + 0.75)
        s.rect(a[0], a[1], 1.5 * K, 1.5 * K, fill="#2e7d32", stroke="#1b5e20", sw=0.8)

    # thermal band boundary on tab X (H.23(h))
    hb = J["h"]["boundary"]
    s.poly([P(*p) for p in hb], stroke="#e65100", sw=1.5, dash="4,3", closed=False)

    # feet on the CR bottom: drawn dashed and below the top-side tap pads (F20/F21 lie over FT1, H.23(g), T-A-09)
    for key, lab in (("ft1", "FT1"), ("ft2", "FT2")):
        b = J["i"][key]["body"]
        R(*b, fill="#c8e6c9", stroke="#1b5e20", sw=1.5, dash="3,2", op=0.6)
    fh = P(28.0, 73.25)
    s.circle(fh[0], fh[1], 0.5 * K, fill="#ffffff", stroke="#1b5e20", sw=1.2)

    # tap field 6 x 4 on tab X (H.23(g)), R175 pads at (50.80, 61.48/64.02), spares (sp)
    xs, ys = J["g"]["xs"], J["g"]["ys"]
    spare = [tuple(p) for p in J["g"]["spare"]]
    for x in xs:
        for y in ys:
            a = P(x - 0.75, y + 0.75)
            if (x, y) in spare:
                s.rect(a[0], a[1], 1.5 * K, 1.5 * K, fill="#ffffff", stroke="#2e7d32", sw=0.8, dash="2,2")
            elif x == 50.8 and y in (61.48, 64.02):
                s.rect(a[0], a[1], 1.5 * K, 1.5 * K, fill="#a1887f", stroke="#5d4037", sw=0.8)
            else:
                s.rect(a[0], a[1], 1.5 * K, 1.5 * K, fill="#2e7d32", stroke="#1b5e20", sw=0.8)

    # W-lead dressing path (centre lines)
    trunk = ["T0", "J67", "T1", "B1", "T2", "T3", "B3", "T4", "T5", "T6", "A1"]
    s.poly([P(*dw[k]) for k in trunk], stroke="#b71c1c", sw=3, closed=False, cap="round")
    s.poly([P(24.3, 45.4), P(24.4, 47.0), P(24.4, 54.0), P(*dw["T0"])], stroke="#b71c1c", sw=2, closed=False)
    s.poly([P(*dw["A1"]), P(*dw["WN"]), P(58.0, 98.044), P(58.0, 104.0)], stroke="#b71c1c", sw=3, closed=False)
    s.poly([P(*dw["A1"]), P(*dw["E1"]), P(*dw["A2"]), P(77.25, 98.044), P(80.0, 104.0)],
           stroke="#b71c1c", sw=3, closed=False)
    w5 = [(40.75, 46.83), dw["F1"], dw["S2"], dw["F2"], dw["S3"], dw["F3"], dw["F4"], dw["A1R"], dw["E1R"],
          dw["A2"], (74.75, 98.044), (76.5, 104.0)]
    s.poly([P(*p) for p in w5], stroke="#00897b", sw=2, dash="6,3", closed=False)

    # anchors: beads/posts B1, B3 and spacers S1-S3 (3 x 3 mm), tie bases A1 (6 x 6) and A2 (10 x 10)
    x, y = dw["B3"]
    R(x - 1.5, y - 1.5, x + 1.5, y + 1.5, fill="#e1bee7", stroke=R7, sw=1.5)
    blk = J["s"]["block"]                     # r8 B1R wedge footprint (H.23(s)), replaces the 3 x 3 mm B1 spot
    R(blk[0], blk[1], blk[2], blk[3], fill=R8_FILL, stroke=R8, sw=1.8)
    # ramp direction arrow toe -> apex along +y on the wedge
    ta, tb_ = P((blk[0] + blk[2]) / 2 - 0.5, blk[1] + 0.6), P((blk[0] + blk[2]) / 2 - 0.5, blk[3] - 0.6)
    s.line(ta[0], ta[1], tb_[0], tb_[1], stroke=R8, sw=1.5, arrow="ap8")
    # F17 (T16) pad with R106s beside it on the tab X bottom (B.4, A.8 r8 placement)
    f17 = J["g"]["assignment"]["T16"]
    a = P(f17[1] - 1.05, f17[2] + 1.05)
    s.rect(a[0], a[1], 2.1 * K, 2.1 * K, fill="none", stroke=R8, sw=2.0)
    for k in ("S1", "S2", "S3"):
        x, y = dw[k]
        R(x - 1.5, y - 1.5, x + 1.5, y + 1.5, fill="#b2ebf2", stroke="#00838f", sw=1.5)
    for k, half in (("A1", 3.0), ("A2", 5.0)):
        x, y = dw[k]
        R(x - half, y - half, x + half, y + half, fill="#d7ccc8", stroke="#4e342e", sw=1.5, op=0.85)
        R(x - half - 1.5, y - half - 1.5, x + half + 1.5, y + half + 1.5, stroke="#4e342e", sw=0.8, dash="3,2")

    # labels with leaders
    def lab(px, py, rows, x, y, color=INK, bold=True, size=12):
        tx_, ty_ = P(px, py)
        lx_, ly_ = P(x, y)
        wid = len(rows[0]) * size * 0.6
        ex = lx_ + wid + 3 if tx_ > lx_ else lx_ - 3
        s.line(tx_, ty_, ex, ly_ - 4, stroke="#888", sw=0.8)
        for k, r in enumerate(rows):
            s.text(P(x, y)[0], P(x, y)[1] + k * (size + 3), r, size, color, bold=(bold and k == 0))

    lab(56.0, 67.0, ["tab X", "x 48.70-65.00", "y 56.30-68.30"], 66.5, 62.5, "#1565c0")
    lab(19.5, 69.0, ["tab Y", "x 17.70-37.56", "y 67.14-76.00"], 1.0, 69.8, "#1565c0")
    lab(17.7, 55.0, ["Ag105 footprint", "31 x 33 mm (dashed)"], 1.0, 56.2, "#455a64")
    b1 = J["i"]["ft1"]["centre"]
    lab(b1[0] + 2.0, b1[1], ["FT1 4.0 x 1.6", "(61.72, 66.71)"], 66.5, 68.6, "#1b5e20")
    lab(26.0, 73.25, ["FT2 4.0 x 4.0 + 1.0 mm", "fill hole (28.00, 73.25)"], 1.0, 75.0, "#1b5e20")
    lab(63.5, 58.94, ["tap field 6 x 4 at 2.54 mm", "(20 pads + R175 + 2 spare)"], 66.5, 53.5, "#1b5e20")
    lab(41.68, 35.8, ["F08-F10, F22 (low row y 35.80)"], 44.5, 31.6, "#1b5e20", bold=False, size=11)
    lab(blk[0], (blk[1] + blk[3]) / 2 - 1.0, ["B1R wedge", "(r8, 65 deg)"], 1.0, 61.6, R8, size=11)
    lab(dw["B3"][0], dw["B3"][1] - 1.5, ["B3 post + S3"], 39.0, 63.2, R7, size=11)
    lab(f17[1] + 1.05, f17[2] - 0.6, ["F17 (T16): R106s on the", "tab X bottom beside it (r8)"], 66.5, 47.5, R8,
        size=11)
    lab(dw["S1"][0] + 1.5, dw["S1"][1], ["S1"], 38.5, 49.0, "#00838f", size=11)
    lab(dw["S2"][0] + 1.5, dw["S2"][1], ["S2"], 33.5, 55.5, "#00838f", size=11)
    lab(dw["A1"][0] + 3, dw["A1"][1] + 3, ["A1 tie base 6 x 6"], 66.5, 79.5, "#4e342e", size=11)
    lab(dw["A2"][0] + 5, dw["A2"][1], ["A2 tie base 10 x 10"], 79.0, 87.0, "#4e342e", size=11)
    lab(48.0, 80.0, ["polyimide strip"], 38.0, 93.5, "#00695c", size=11)
    lab(25.8, 59.0, ["trunk x 25.80"], 1.0, 50.5, "#b71c1c", size=11)

    # chassis-tie limits past the MB +y edge
    for x, lim, tag in ((58.0, 2.4, "west group W1, W2, W6, W7: tie <= 2.4 mm"),
                        (74.75, 17.4, "W5: tie <= 17.4 mm"),
                        (77.25, 16.4, "W3/W4: tie <= 16.4 mm")):
        a = P(x - 1.2, 98.044 + lim)
        s.rect(a[0], a[1], 2.4 * K, lim * K, fill="#ffcdd2", stroke=WARN, sw=1, op=0.6)
    s.text(P(40.5, 101.6)[0], P(40.5, 101.6)[1], "west tie <= 2.4 mm", 11, WARN)
    s.text(P(81.0, 112.0)[0], P(81.0, 112.0)[1], "W5 tie <= 17.4 mm,", 11, WARN)
    s.text(P(81.0, 110.0)[0], P(81.0, 110.0)[1], "W3/W4 tie <= 16.4 mm", 11, WARN)
    s.text(P(81.0, 108.0)[0], P(81.0, 108.0)[1], "past the MB +y edge", 11, WARN)

    # arrow to EVM plate
    ev = J["l"]["evm"]
    a = P(30.0, 112.0)
    b = P(30.0, Y1 - 0.3)
    s.line(a[0], a[1], b[0], b[1], stroke=R7, sw=2.5, arrow="ap")
    s.text(P(31.5, 120.3)[0], P(31.5, 120.3)[1], "to the EVM plate (r7): EVM x %.2f-%.2f, y %.2f-%.2f;"
           % (ev[0], ev[1 + 1], ev[1], ev[3]), 11, R7, bold=True)
    e = J["l"]["eib"]
    s.text(P(31.5, 118.3)[0], P(31.5, 118.3)[1], "EIB x %.2f-%.2f beside its right edge (reference placement)"
           % (e[0], e[2]), 11, R7)

    # scale bar
    a = P(84.0, 33.0)
    s.line(a[0], a[1], a[0] + 10 * K, a[1], sw=2.5)
    s.line(a[0], a[1] - 4, a[0], a[1] + 4, sw=1.5)
    s.line(a[0] + 10 * K, a[1] - 4, a[0] + 10 * K, a[1] + 4, sw=1.5)
    s.text(a[0] + 5 * K, a[1] - 7, "10 mm", 11, anchor="middle")

    # legend
    lx = OX + (X1 - X0) * K + 20
    ly = OY + 10
    s.text(lx, ly, "Legend", 13, bold=True)
    items = [
        ("poly", "#1565c0", "#e3f2fd", "r7 CR outline (1394.06 mm2)"),
        ("dash", "#455a64", "none", "Ag105 footprint 31 x 33 mm"),
        ("dash", "#1b5e20", "#c8e6c9", "foot FT1 / FT2 (CR bottom side)"),
        ("box", "#1b5e20", "#2e7d32", "tap pad 1.5 x 1.5 mm (F-pad)"),
        ("box", "#5d4037", "#a1887f", "R175 pads (a, b)"),
        ("dash", "#2e7d32", "#ffffff", "spare tap grid position"),
        ("dash", "#1565c0", "#bbdefb", "comparator band (A.8)"),
        ("line", "#e65100", None, "thermal band boundary (H.23(h))"),
        ("line", "#b71c1c", None, "W1-W4, W6, W7 dressing path"),
        ("ldash", "#00897b", None, "W5 ribbon path"),
        ("box", R8, R8_FILL, "B1R riser wedge (r8, A.3)"),
        ("box", R7, "#e1bee7", "B3 post (bead), 10.7 mm (r8)"),
        ("box", "#00838f", "#b2ebf2", "W5 spacer S1-S3"),
        ("box", "#4e342e", "#d7ccc8", "tie base A1/A2 (+-1.5 mm zone)"),
        ("band", "#80cbc4", None, "polyimide strip on the MB"),
        ("box", WARN, "#ffcdd2", "chassis-tie limit past the edge"),
        ("box", "#777", "#eeeeee", "MB part box (.brd)"),
    ]
    for k, (kind, col, fill, txt) in enumerate(items):
        yy = ly + 22 + k * 22
        if kind in ("box", "poly"):
            s.rect(lx, yy - 11, 22, 13, fill=fill, stroke=col, sw=1.5)
        elif kind == "dash":
            s.rect(lx, yy - 11, 22, 13, fill=fill, stroke=col, sw=1.2, dash="4,3")
        elif kind == "line":
            s.line(lx, yy - 4, lx + 22, yy - 4, stroke=col, sw=3)
        elif kind == "ldash":
            s.line(lx, yy - 4, lx + 22, yy - 4, stroke=col, sw=2, dash="6,3")
        elif kind == "band":
            s.line(lx, yy - 4, lx + 22, yy - 4, stroke=col, sw=10)
        s.text(lx + 30, yy, txt, 11)
    ny = ly + 22 + len(items) * 22 + 14
    s.text(lx, ny, "Notes", 13, bold=True)
    notes = ["Trunk: W3 up x 24.40 joins at y 57.00;",
             "+y on x 25.80, +x across tab Y",
             "at y 69.60-71.10, leaves at x 37.56;",
             "y 71.75 at x 48.00, then to A1.",
             "West group: A1 -> x 58.00 -> MB edge.",
             "East group: A1 -> A2 -> MB edge",
             "(W3/W4 at x 77.25, W5 at x 74.75).",
             "No W lead crosses tab X.",
             "Every span between anchors <= 30 mm",
             "(longest 26.0 mm, S2-S3; r8 trunk",
             "span B1R apex to B3 10.4 mm).",
             "r8: W5 above the trunk over the",
             "whole overlap, on it from (28.70, 64.01).",
             "Polyimide strip bbox x 36.06-65.28,",
             "y 65.30-92.80; it stops at A1 and A2.",
             "Sources: r7_calc_out.json H.23(a), (g),",
             "(h), (i), (l), (s), (t); MB boxes from",
             "the .brd."]
    s.lines(lx, ny + 18, notes, 11, GREY, dy=15)
    s.save("fig2_plan_view_r7.svg")


# ---------------------------------------------------------------------------------------------------------------------
# D3  side section
# ---------------------------------------------------------------------------------------------------------------------
def fig3():
    s = Svg(1180, 1370, "Fig 3. Side sections through tab Y and the B1R riser, r8 (heights in mm above the MB top)")
    s.text(20, 46, "(a) Section along +y at x 36.00 (the controlling trunk point, B3 post, W5 run); FT2 and its fill hole "
                   "projected from x 28.00, the 1x12 header body and pin 11 from x 20.998.", 12, GREY)
    s.text(20, 62, "(b) Section along +y at x 25.80 (the trunk run on B1R). In each panel plan and height share one scale; "
                   "the thin layers (sheet, bed, tape) are drawn thicker than scale.", 12, GREY)

    # ---------------- panel (a) ----------------
    K = 18.0
    Y0, Y1 = 60.0, 92.0          # board y range along the section
    OX = 300
    ZB = 500                     # pixel row of the MB top (h = 0)

    def X(y):
        return OX + (y - Y0) * K

    def Z(h):
        return ZB - h * K

    s.text(20, 92, "(a) x 36.00: B3 post, trunk and W5 over tab Y", 13, bold=True)
    fh = J["i"]["foot_height"]
    t_sheet, t_bed = 0.125, fh["t_bed_nom"]
    cr_u, cr_t = J["j"]["cr_under"], J["j"]["cr_top"]
    lfc_box = [t[1] for t in J["m"]["trims"] if t[0].startswith("L-FC")][0]   # Eaton body, H.23(m)
    lfc_y0, lfc_y1 = lfc_box[1], lfc_box[3]
    H_LFC = J["l"]["rev4"]["heights"]["H_LFC"]
    need_w5 = J["j"]["w5_over_lfc_bottom"]                                    # 15.00 mm, W5 own requirement
    rib = J["j"]["ribbon_assumed"]
    S_, T_ = J["s"], J["t"]
    h_tr, t_b = S_["h_trunk"], S_["T_b"]                                      # r8 trunk half-width, bundle
    z_tb = cr_t + S_["b3_height"]                                             # trunk bottom on the B3 post
    z_tt = T_["trunk_top_plateau"]                                            # = W5 bottom
    z_top = T_["stack_top"]
    req36 = cr_t + S_["max_req_above_cr"]                                     # requirement at (36.00, 71.10)
    tab_end, sheet_end = 76.0, 76.362
    LX = 20                      # left label column

    # MB
    s.rect(X(Y0), Z(0), (Y1 - Y0) * K, 1.6 * K, fill="#c8e6c9", stroke="#2e7d32")
    s.text(X(Y0) + 6, Z(-1.05), "MB 1.6 mm", 11, "#1b5e20", bold=True)
    st = Z(0) - 4
    s.rect(X(Y0), st, (sheet_end - Y0) * K, 4, fill="#ffcc80", stroke="#e65100", sw=1)
    hdr1 = 64.484 + 1.27
    s.rect(X(Y0), Z(cr_u), (hdr1 - Y0) * K, st - Z(cr_u), fill="#cfd8dc", stroke="#455a64")
    f0, f1 = J["i"]["ft2"]["body"][1], J["i"]["ft2"]["body"][3]
    bt = st - t_bed * K
    s.rect(X(f0), bt, (f1 - f0) * K, st - bt, fill="#fff59d", stroke="#f9a825", sw=1)
    tape_top = Z(cr_u)
    tape_bot = tape_top + 4
    s.rect(X(f0), tape_top, (f1 - f0) * K, 4, fill="#90caf9", stroke="#1565c0", sw=1)
    s.rect(X(f0), tape_bot, (f1 - f0) * K, bt - tape_bot, fill="#a5d6a7", stroke="#1b5e20", sw=1.5)
    s.text(X((f0 + f1) / 2), (tape_bot + bt) / 2 + 4, "FT2", 12, "#1b5e20", bold=True, anchor="middle")
    s.rect(X(Y0), Z(cr_t), (tab_end - Y0) * K, (cr_t - cr_u) * K, fill=CR_FILL, stroke=CR_EDGE, sw=2)
    s.text(X(66.4), Z(cr_u) - 9, "CR 1.6 mm", 11, CR_EDGE, bold=True)
    s.rect(X(73.25 - 0.5), Z(cr_t), K, (cr_t - cr_u) * K, fill="#ffffff", stroke=CR_EDGE, sw=1)
    s.rect(X(64.484 - 0.32), Z(cr_t + 0.94), 0.64 * K, st - Z(cr_t + 0.94), fill="#ffd54f", stroke="#8d6e63", sw=1)
    s.rect(X(lfc_y0), Z(H_LFC), (lfc_y1 - lfc_y0) * K, H_LFC * K, fill="#e0e0e0", stroke="#424242", sw=2)
    s.text(X((lfc_y0 + Y1) / 2), Z(3.2), "L-FC body", 12, INK, bold=True, anchor="middle")
    s.text(X((lfc_y0 + Y1) / 2), Z(2.0), "5.0 mm (ASSUMPTION, MS3)", 11, GREY, anchor="middle")
    s.text(X((lfc_y0 + Y1) / 2), Z(0.8), "starts at y 76.862", 11, GREY, anchor="middle")

    # 10 mm 3-D clearance: quarter arc about the L-FC top -y corner, then the flat 15.00 mm line over the body
    cx, cz = X(lfc_y0), Z(H_LFC)
    r = 10 * K
    pts = [(cx - r * math.cos(math.radians(a)), cz - r * math.sin(math.radians(a))) for a in range(0, 91, 3)]
    s.poly(pts, stroke=WARN, sw=1.5, dash="5,4", closed=False)
    s.line(cx, cz - r, X(Y1), cz - r, stroke=WARN, sw=1.5, dash="5,4")
    s.text(X(80.0), cz - r + 15, "10 mm 3-D clearance: 15.00 mm over L-FC", 11, WARN)
    ex, ez = cx - r * math.cos(math.radians(40)), cz - r * math.sin(math.radians(40))
    s.line(cx, cz, ex, ez, stroke=WARN, sw=1)
    s.text((cx + ex) / 2 + 8, (cz + ez) / 2 + 4, "r 10 mm", 11, WARN)

    # B3 post (merged with S3) at y 70.80 from the CR top to the trunk jacket bottom (r8: 10.7 mm above the CR top)
    trunk_c = 71.10
    post0, post1 = 70.8 - 1.5, 70.8 + 1.5
    s.rect(X(post0), Z(z_tb), (post1 - post0) * K, (z_tb - cr_t) * K, fill="#e1bee7", stroke=R7, sw=1.5)
    # trunk: round bundle of diameter T_b (H.23(s)/(t)), bottom on the post
    s.circle(X(trunk_c), Z(z_tb + t_b / 2), t_b / 2 * K, fill="#ef9a9a", stroke="#b71c1c", sw=1.5)
    s.text(X(trunk_c), Z(z_tb + t_b / 2) + 4, "trunk", 11, "#7f0000", bold=True, anchor="middle")
    # W5 ribbon, 8.89 mm wide, centred on y 73.10, resting on the trunk top (H.23(t))
    w0, w1 = 73.10 - 4.445, 73.10 + 4.445
    s.add('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#4db6ac" fill-opacity="0.75" stroke="#00695c" '
          'stroke-width="1.5"/>' % (X(w0), Z(z_top), (w1 - w0) * K, (z_top - z_tt) * K))
    # plan gap trunk edge -> L-FC face
    gy = Z(z_tb) + 12
    s.line(X(trunk_c + h_tr), gy, X(lfc_y0), gy, stroke="#555", sw=1)
    s.line(X(trunk_c + h_tr), gy - 4, X(trunk_c + h_tr), gy + 4, stroke="#555", sw=1)
    s.line(X(lfc_y0), gy - 4, X(lfc_y0), gy + 4, stroke="#555", sw=1)
    s.text(X((trunk_c + h_tr + lfc_y0) / 2), gy + 15, "d %.2f" % (lfc_y0 - trunk_c - h_tr), 11, anchor="middle")

    # height axis with real values
    ax = X(Y1) + 18
    s.line(ax, Z(-1.6), ax, Z(22.0), stroke="#999", sw=1)
    ticks = [(0.0, "0 MB top"), (t_sheet, "0.125 sheet top"), (cr_u, "2.665 CR underside"),
             (cr_t, "4.265 CR top"), (H_LFC, "5.00 L-FC top (assumed)"),
             (req36, "%.3f requirement at (36.00, 71.10)" % req36),
             (z_tb, "%.3f trunk bottom, B3 post top" % z_tb), (need_w5, "15.00 W5 requirement over L-FC"),
             (z_tt, "%.3f trunk top = W5 bottom" % z_tt), (z_top, "%.3f stack top (information, D-H)" % z_top)]
    last = None
    for h, t in ticks:
        yy = Z(h)
        s.line(ax - 4, yy, ax + 4, yy, stroke="#555", sw=1)
        ty = yy + 4
        if last is not None and last - ty < 14:
            ty = last - 14
        s.line(ax + 4, yy, ax + 12, ty - 4, stroke="#bbb", sw=0.8)
        s.text(ax + 14, ty, t, 11)
        last = ty

    def left(px, py, ty, rows, color=INK):
        wid = max(len(r_) for r_ in rows) * 11 * 0.55
        s.line(px, py, LX + wid + 6, ty - 4, stroke="#999", sw=0.8)
        s.lines(LX, ty, rows, 11, color, dy=14)

    left(X(trunk_c - h_tr), Z(z_tb + h_tr), Z(17.6),
         ["round-lead trunk W1-W4, W6, W7 (r8): one", "RTV-bound round bundle, 4.885 mm; bottom",
          "%.3f mm above the MB (%.1f mm above the" % (z_tb, S_["b3_height"]), "CR top) on the B3 post"], "#b71c1c")
    left(X(w0), Z((z_tt + z_top) / 2), Z(21.6),
         ["W5 ribbon (0.9 mm assumed), 8.89 mm wide:", "rests on the trunk top, bonded with RTV;",
          "%.3f-%.3f mm above the MB" % (z_tt, z_top)], "#00695c")
    left(X(post0), Z(9.5), Z(10.6), ["B3 post, merged with S3,", "at (35.00, 70.80)"], R7)
    left(X(64.484 - 0.32), Z(cr_t + 0.8), Z(7.2), ["pin 11 post, 0.94 mm proud", "(RTV dome on pins 7-10)"], "#6d4c41")
    left(X(Y0) + 30, Z(1.4), Z(3.4), ["header body 2.54 mm (TSW, PBT),", "seats on the sheet"], "#263238")

    def below(px, py, row, rows, color=INK):
        ty = ZB + 46 + row * 18
        s.line(px, py, px, ty - 4, stroke="#999", sw=0.8)
        s.lines(px + 4, ty, rows, 11, color, dy=14)

    below(X(f1 - 0.3), tape_top + 2, 0, ["acrylic transfer tape 0.05 mm to the CR (2.19 + 0.30 + 0.05 = 2.54 mm)"], "#1565c0")
    below(X(f1 - 1.5), (tape_bot + bt) / 2, 1, ["foot block h_f 2.19 mm (+0/-0.05)"], "#1b5e20")
    below(X(f0 + 0.3), (bt + st) / 2, 2, ["FT2 bed: alkoxy RTV, 0.30 mm nominal, gated 0.15-0.45 mm by feelers (PM4 (2d))"], "#b26a00")
    below(X(60.4), st + 2, 3, ["polyimide sheet 0.125 mm (to y 76.362)"], "#e65100")
    s.line(X(73.25), Z(cr_t) + 2, X(77.6), Z(6.1), stroke="#999", sw=0.8)
    s.lines(X(77.7), Z(6.2), ["FT2 fill hole 1.0 mm NPTH", "at (28.00, 73.25)"], 11, CR_EDGE, dy=13)

    # ---------------- panel (b) ----------------
    K2 = 24.0
    Yb0, Yb1 = 58.0, 71.0
    OX2 = 330
    ZB2 = 1215

    def X2(y):
        return OX2 + (y - Yb0) * K2

    def Z2(h):
        return ZB2 - h * K2

    s.text(20, 672, "(b) x 25.80: the trunk on the B1R riser wedge (r8, CHG-R1-D03), W5 above it (CHG-R1-W01)", 13,
           bold=True)
    m = math.tan(math.radians(S_["slope_deg"]))
    y_toe, y_apx, z_apx = S_["toe_y"], 67.10, S_["apex"]                       # H.23(s); RISER_Y_END 67.10
    y_t2 = 69.60
    mm_ = S_["min_margin"]
    REQ_T2 = 9.497   # mm above the CR top required at T2 (25.80, 69.60): H.23(s) full-profile check row (text output)
    z_t2 = REQ_T2 + mm_                                                        # built at T2: 10.001 mm (H.23(s))
    s.rect(X2(Yb0), Z2(0), (Yb1 - Yb0) * K2, 1.6 * K2, fill="#c8e6c9", stroke="#2e7d32")
    s.text(X2(Yb0) + 6, Z2(-1.05), "MB 1.6 mm", 11, "#1b5e20", bold=True)
    st2 = Z2(0) - 4
    s.rect(X2(Yb0), st2, (Yb1 - Yb0) * K2, 4, fill="#ffcc80", stroke="#e65100", sw=1)
    s.text(X2(Yb0) + 6, Z2(0.55), "(no header body in this plane)", 11, GREY)
    s.rect(X2(Yb0), Z2(cr_t), (Yb1 - Yb0) * K2, (cr_t - cr_u) * K2, fill=CR_FILL, stroke=CR_EDGE, sw=2)
    s.text(X2(Yb0) + 6, Z2(cr_u) - 9, "CR 1.6 mm", 11, CR_EDGE, bold=True)
    # wedge on its transfer tape
    s.rect(X2(y_toe), Z2(cr_t) - 3, (y_apx - y_toe) * K2, 3, fill="#90caf9", stroke="#1565c0", sw=0.8)
    wedge = [(X2(y_toe), Z2(cr_t) - 3), (X2(y_apx), Z2(cr_t) - 3), (X2(y_apx), Z2(cr_t + z_apx))]
    s.poly(wedge, stroke=R8, sw=2, fill=R8_FILL, op=0.95)
    s.text(X2(y_apx) - 30, Z2(cr_t + 2.0), "B1R", 13, R8, bold=True, anchor="middle")
    # slope angle mark at the toe
    ar = 1.6 * K2
    apts = [(X2(y_toe) + ar * math.cos(math.radians(a)), Z2(cr_t) - 3 - ar * math.sin(math.radians(a)))
            for a in range(0, int(S_["slope_deg"]) + 1, 5)]
    s.poly(apts, stroke=R8, sw=1, closed=False)
    s.text(X2(y_toe) + ar + 4, Z2(cr_t) - 10, "%.0f deg" % S_["slope_deg"], 11, R8)
    # trunk bottom polyline (built) and the bundle band above it (vertical thickness T_b, H.23(t))
    bl = [(Yb0, 0.0), (y_toe, 0.0), (y_apx, z_apx), (y_t2, z_t2)]
    band = [(X2(y), Z2(cr_t + z)) for y, z in bl] + [(X2(y), Z2(cr_t + z + t_b)) for y, z in reversed(bl)]
    s.poly(band, stroke="#b71c1c", sw=1.2, fill="#ef9a9a", op=0.75)
    s.poly([(X2(y), Z2(cr_t + z)) for y, z in bl], stroke="#b71c1c", sw=2.5, closed=False)
    s.lines(X2(58.2), Z2(cr_t + t_b / 2) + 4, ["trunk", "(bundle 4.885 mm)"], 11, "#7f0000", dy=14)
    # W5 above the trunk: the 8 mm fold until the trunk top passes it at the ride point (H.23(t))
    fold = cr_t + 8.0
    w5b = []
    for k in range(0, 261):
        y = Yb0 + k * (y_t2 - Yb0) / 260
        if y <= y_toe:
            zt = cr_t + t_b
        elif y <= y_apx:
            zt = cr_t + m * (y - y_toe) + t_b
        else:
            zt = cr_t + z_apx + (z_t2 - z_apx) * (y - y_apx) / (y_t2 - y_apx) + t_b
        w5b.append((y, max(fold, zt)))
    rb = [(X2(y), Z2(z)) for y, z in w5b] + [(X2(y), Z2(z + rib)) for y, z in reversed(w5b)]
    s.poly(rb, stroke="#00695c", sw=1.2, fill="#4db6ac", op=0.75)
    # requirement: the H.23(s) T-F-12 check points past B1 and the T2 minimum-margin row
    rq = [(64.50 + d, cr_t + q) for d, q, _b in S_["checkpoints"]] + [(y_t2, cr_t + REQ_T2)]
    s.poly([(X2(y), Z2(z)) for y, z in rq], stroke=INK, sw=1.5, dash="6,3", closed=False)
    for y, z in rq:
        s.line(X2(y) - 4, Z2(z) - 4, X2(y) + 4, Z2(z) + 4, stroke=INK, sw=1.2)
        s.line(X2(y) - 4, Z2(z) + 4, X2(y) + 4, Z2(z) - 4, stroke=INK, sw=1.2)
    # W1/W2 joints projected (W2 x 27.70, W1 x 30.30, y 61.20), T1 and T2
    s.circle(X2(61.2), Z2(cr_t) - 5, 5, fill="#b71c1c", stroke="#7f0000", sw=1)
    s.line(X2(62.6), Z2(cr_u) + 2, X2(62.6), Z2(cr_u) + 26, stroke="#999", sw=0.8)
    s.text(X2(62.6) + 4, Z2(cr_u) + 22, "T1 y 62.60", 11, GREY)
    s.line(X2(y_t2), Z2(cr_t + z_t2) - 2, X2(y_t2), Z2(cr_u) + 26, stroke="#999", sw=0.8, dash="2,2")
    s.text(X2(y_t2) - 4, Z2(cr_u) + 22, "T2 y 69.60", 11, GREY, anchor="end")
    # right-hand height axis for panel (b)
    ax2 = X2(Yb1) + 18
    s.line(ax2, Z2(-1.6), ax2, Z2(21.0), stroke="#999", sw=1)
    ticks2 = [(cr_t, "4.265 CR top"), (fold, "%.3f W5 fold (8.0 mm above the CR top)" % fold),
              (cr_t + z_apx, "%.3f B1R apex (%.3f above the CR top)" % (cr_t + z_apx, z_apx)),
              (cr_t + z_t2, "%.3f trunk bottom at T2 (built)" % (cr_t + z_t2)),
              (cr_t + z_t2 + t_b, "%.3f trunk top at T2" % (cr_t + z_t2 + t_b))]
    last = None
    for h, t in ticks2:
        yy = Z2(h)
        s.line(ax2 - 4, yy, ax2 + 4, yy, stroke="#555", sw=1)
        ty = yy + 4
        if last is not None and last - ty < 14:
            ty = last - 14
        s.line(ax2 + 4, yy, ax2 + 12, ty - 4, stroke="#bbb", sw=0.8)
        s.text(ax2 + 14, ty, t, 11)
        last = ty

    left(X2((y_toe + y_apx) / 2 + 0.6), Z2(cr_t + 3.0), Z2(5.6),
         ["B1R: machined insulating wedge", "(G10/FR-4 or PEEK, ASSUMPTION),", "toe y %.2f, apex y %.2f;" % (y_toe, y_apx),
          "footprint x 23.55-26.05: the 2.50 mm", "face carries %.0f %% of the trunk width;" % (100 * J["y"]["b1r_support_frac"]),
          "taped to the CR (0.05 mm)"], R8)
    left(X2(61.2) - 5, Z2(cr_t) - 5, Z2(10.4),
         ["W1/W2 joints, projected (y 61.20;", "x 27.70 / 30.30); RTV bead over", ">= 5.0 mm of jacket, on the copper",
          "and on along the ramp"], "#7f0000")
    left(X2(63.0), Z2(fold + 0.45), Z2(16.4),
         ["W5 (projected from x 28.70):", "at the 8 mm fold, then on the", "trunk top from (28.70, 64.01)"], "#00695c")
    left(X2(65.5), Z2(cr_t + 7.62), Z2(20.6),
         ["3-D requirement: H.23(s) T-F-12", "check points (x) past B1 and T2"], INK)
    left(X2(y_t2) - 3, Z2(cr_t + REQ_T2) + 2, Z2(13.2),
         ["minimum margin %.3f mm at T2" % mm_, "(required %.3f, built %.3f mm" % (REQ_T2, z_t2),
          "above the CR top; H.23(s))"], INK)
    s.lines(X2(y_t2) + 6, Z2(cr_t + z_t2 + t_b + 3.0), ["trunk turns +x at T2;", "free span 10.4 mm",
                                                         "to the B3 post"], 11, "#7f0000", dy=13)

    # notes
    s.rect(20, 1272, 1140, 88, "#f6f6f6", "#999")
    s.text(30, 1290, "Resolved in r8 (the open point of the r7 walkthrough): the vertical order of W5 and the trunk "
                     "(CHG-R1-W01)", 12, INK, bold=True)
    s.text(30, 1307, "W5 lies above the trunk over the whole plan overlap, from the trunk start (y 57.00) to A1; it rests "
                     "on the trunk top and is bonded to it with RTV", 11)
    s.text(30, 1322, "from (28.70, 64.01) to A1 (H.23(t)). B1R carries the trunk from the CR copper to the B3 post with a "
                     "minimum margin of 0.504 mm (H.23(s)).", 11)
    s.text(30, 1340, "Heights: H.23(i) foot budget, H.23(j) stack, H.23(s)/(t) trunk and W5 (L-FC 5.0 mm, ribbon 0.9 mm "
                     "and bundle 4.885 mm are ASSUMPTIONs; MS3, MS2/MS7); MB and CR 1.6 mm assumed (MS6).", 11, GREY)
    s.save("fig3_side_stack_r7.svg")


# ---------------------------------------------------------------------------------------------------------------------
# D4  assembly order with gates
# ---------------------------------------------------------------------------------------------------------------------
def fig4():
    s = Svg(1180, 1120, "Fig 4. Build order for the r8 carrier and the gates that hold each step (design D.1, I)")
    s.text(20, 46, "Grey = rework or build step; amber = measured gate; purple chips = operator survey items MS1-MS8 (T-A-08). "
                   "Solid arrow = the step the item gates; dashed arrow = a later step that uses its result.", 12, GREY)

    BX, BW = 300, 560

    def step(y, h, head, rows, fill="#eeeeee", stroke=INK):
        s.rect(BX, y, BW, h, fill, stroke, sw=1.5)
        s.text(BX + 10, y + 18, head, 12, bold=True)
        s.lines(BX + 10, y + 34, rows, 11, dy=14)
        return y + h

    def gate(y, rows):
        h = 14 * len(rows) + 10
        s.rect(BX + 40, y, BW - 80, h, "#fff4d6", "#b08900", sw=1.2, rx=6)
        s.lines(BX + 52, y + 15, rows, 11, "#5d4300", dy=14)
        return y + h

    def arrow(y0, y1):
        s.line(BX + BW / 2, y0, BX + BW / 2, y1, sw=1.5, arrow="a")

    def chip(x, y, label, rows, target_y, side="left", uses=False):
        w = 230
        s.rect(x, y, w, 14 * len(rows) + 22, R7_FILL, R7, sw=1.2, rx=5)
        s.text(x + 8, y + 16, label, 12, R7, bold=True)
        s.lines(x + 8, y + 31, rows, 11, R7, dy=14)
        cy = y + 10
        dash = "5,3" if uses else None
        if side == "left":
            s.line(x + w, cy, BX - 2, target_y, stroke=R7, sw=1.2, arrow="ap", dash=dash)
        else:
            s.line(x, cy, BX + BW + 2, target_y, stroke=R7, sw=1.2, arrow="ap", dash=dash)

    y = 70
    y1 = step(y, 46, "Before any rework: MS1a with the Ag105 in place",
              ["standoff at four corners, module top height (information only, D-H)"], fill="#f3f3f3")
    arrow(y1, y1 + 14)
    y = y1 + 14
    y1 = step(y, 76, "PM0  KiCad capture of CR and EIB",
              ["r7 outline (tab X, tab Y, chamfer at (17.70, 76.00)), foot keep-outs FT1/FT2,",
               "FT2 1.0 mm fill hole, tap field split, bottom clearance rule, thermal band rule;",
               "r8: R106s 0402 on the tab X bottom beside F17; B1R area x 23.55-26.05, y 62.54-67.10"])
    pm0_y = y + 20
    y = gate(y1 + 6, ["T-A-06: pin identity (script + 1:1 print), netlist diff = 0, DRC on the r7 outline,",
                      "dry fit of both tabs and both feet; T-A-08 survey must pass first"])
    arrow(y, y + 14)
    y += 14
    y1 = step(y, 46, "PM1  Remove the Ag105 (after the T-B and T-C bench gates)",
              ["then MS1b module mass (information); MS6 MB thickness at the empty CHG holes"])
    pm1_y = y + 30
    arrow(y1, y1 + 14)
    y = y1 + 14
    y1 = step(y, 46, "PM2  C-D8 / C-D10 to >= 35 V;  PM3  R170 / R171 at C-D6 / C-D2",
              ["R171 body toward +y, clear of tab X (T-A-06 item (8) dry fit)"])
    y = gate(y1 + 6, ["r8: T-A-09 step 0 bond coupon before PM4 (1): sheet offcut on masked FR-4, an FT1-size",
                      "block bedded on the sheet and one on the mask, 0.4 N for 10 s each (A.7, H.23(r))"])
    arrow(y, y + 14)
    y += 14
    y1 = step(y, 120, "PM4 (1)-(2c)  sheet, headers, W1-W4 joints, B1R, feet taped",
              ["(1) polyimide sheet 0.125 mm on the MB (r7 outline + 1 mm, trims, relief holes)",
               "(2) headers into the CR, 22 joints at the CR top",
               "(2b) W1-W4 joints; underside trimmed and measured <= 0.5 mm; r8: B1R taped to the",
               "     CR top, W1/W2 on the ramp, RTV bead >= 5.0 mm of jacket from each joint",
               "(2c) feet taped: block 2.14-2.19 mm; r8: if the coupon failed, sheet cut under the feet",
               "     and re-made blocks h_f' = 2.19 mm + t_rm; edge distances FT1 / FT2 recorded"])
    pm4a_y = y + 20
    y = gate(y1 + 6, ["(2d) dry-seat gate: 0.05 mm feeler not under either header body;",
                      "at each foot 0.15 mm enters and 0.45 mm does not"])
    arrow(y, y + 14)
    y += 14
    y1 = step(y, 76, "PM4 (3)-(5)  seat, solder, cut, bed the feet",
              ["(3) fixture, two diagonal pins, feeler re-check (3f)/(3h), other 20 joints",
               "(4) MB-bottom tails <= min(1.0 mm, MS2 under-MB clearance - 0.5 mm)",
               "(5) bed FT1 through its lane, FT2 through the fill hole; cure >= 24 h"])
    pm4b_y = y + 48
    y = gate(y1 + 6, ["T-A-09: cure probe, 0.05 mm feelers at FT1, FT2 witness fillets,",
                      "0.4 N pull at each grip for 10 s, joint resistance unchanged"])
    arrow(y, y + 14)
    y += 14
    y1 = step(y, 106, "PM4 (6)  dress the leads (A.3)",
              ["pin 7-10 RTV dome; W7 (and W6); inspect A1/A2 zones, bond tie bases; polyimide strip",
               "r8: B3 post 10.7 mm above the CR top; trunk bound into one bundle, on the B1R ramp",
               "r8: W5 on S1/S2 at the 8 mm fold, on the trunk from (28.70, 64.01) to A1 (RTV)",
               "off-CR support TODO(design); chassis ties <= 2.4 / 16.4 / 17.4 mm past MB +y;",
               "W1/W2 and W5 slack as service loops on the EVM plate"])
    pm4c_y = y + 60
    arrow(y1, y1 + 14)
    y = y1 + 14
    y1 = step(y, 62, "PM6  Taps (gap path); PM7-PM11 on their own gates",
              ["tab X wires on the A.4 gap path; F20/F21 (over FT1) last, <= 350 C, <= 3 s",
               "PM10/PM11 after T-A-01b/c; PM7 (T18) only if T-B-09 fails"])
    pm6_y = y + 20
    y = gate(y1 + 6, ["T-A-09 again on FT1 (F20/F21 soldered over it)"])
    y = gate(y + 6, ["T-F-12: tap-to-tap and tap-to-power DMM, loupe on 1.04 mm gaps, pin 7-10 covers,",
                     "every lead on the A.3 path; r8: jacket heights at the B1R check points, T2, B3 and",
                     "the off-CR controlling points; W5 on the trunk, no trunk lead above W5; tie limits"])
    arrow(y, y + 14)
    y += 14
    y1 = step(y, 46, "First power-up and the bench/vehicle registry (section I)",
              ["T-F-18 tab vibration and joint integrity after a vehicle run (MS5 follow-up)"], fill="#f3f3f3")

    # MS chips
    chip(20, 110, "MS2-MS5, MS7; MS6 board edge", ["chassis room, MB items, thermal,", "vibration, EVM, MB thickness", "-> gate PM0"], pm0_y)
    chip(20, 290, "MS6 at the CHG holes", ["taken after PM1, before PM4", "-> post arithmetic; gates PM4"], pm4a_y)
    chip(20, 520, "MS3 (gates PM0)", ["L-FC height (<= 5.0 mm basis)", "-> B1R / B3 heights at PM4 (6)"], pm4c_y - 40,
         uses=True)
    chip(930, 600, "MS2 (gates PM0)", ["under-MB clearance", "-> tail cut length at PM4 (4)"], pm4b_y, side="right",
         uses=True)
    chip(930, 720, "MS2 (gates PM0)", ["chassis-tie points, EVM plate", "-> W3/W4/W6/W7 maxima at PM4 (6)"], pm4c_y,
         side="right", uses=True)
    chip(930, 880, "MS5 (gates PM0: feet)", ["peak MB acceleration <= 30 g;", "spectrum -> T-F-18 after build"], y + 20,
         side="right", uses=True)
    chip(930, 110, "MS8", ["router radius, stack-up,", "2 oz space -> PM0 DRC"], pm0_y, side="right")
    s.text(20, 1105, "MS1b gates nothing. A tab trim after the survey re-runs round4/calc/r7_calc.py (H.23) before PM0.", 11, GREY)
    s.save("fig4_assembly_order_r7.svg")


if __name__ == "__main__":
    fig1()
    fig2()
    fig3()
    fig4()
