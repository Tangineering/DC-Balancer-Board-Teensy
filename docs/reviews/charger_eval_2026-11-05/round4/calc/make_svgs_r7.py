#!/usr/bin/env python3
"""Generate the round-4 (r7) figures (stdlib only).

Writes, into round4/:
  carrier_layout_r7.svg   top view of the r7 carrier (CR) outline over the motherboard (MB), with the EVM reference
                          placement past the MB +y edge as a second panel at a smaller scale;
  wiring_bq25798.svg      the round-3 wiring drawing (round3/calc/make_svgs.py) with the r7 changes only;
  carrier_schematic.svg   the round-3 carrier / EIB schematic with the r7 changes only.

Edit this generator, not the SVGs. Coordinate sources (no coordinate is typed in by hand except where a comment cites the
design section it comes from):
  r7_calc_out.json  H.23(a) outline, (g) tap field, (h) thermal band, (i) feet, (d) foot keep-outs, (l) EVM placement,
                    (m) r7 polyimide sheet, its enlarged cut-outs and the L-FC Eaton body; calc revision 4 adds
                    g.r175a (R175 pads), l.routes[*].cr_mb_path (W-lead dressing path with jacket half-widths),
                    l.dressing.anchors (beads B1/B3, W5 spacers S1-S3, MB tie bases A1/A2 with tolerance),
                    l.dressing.polyimide_strip, l.rev4.sw3d (3-D switched-conductor spans), l.rev4.chassis_tie,
                    i.foot_height (h_f);
  r7_calc_out.txt   H.23(l) "full path" lines (W-lead routes including the CR pad and the terminal);
  design A.8 / A.7  CR header pads, W1-W4, W6/W7, J101 region, r6 rectangle and r6 chamfer, comparator band (BASIS D5);
  .brd              MB part boxes (mb_neighbours.element_records via r7_calc.ELS) and MB layer-1 copper (r7_calc.SHAPES).
The r7_calc module is imported for its .brd parse only; r7_calc.main() is not run.
Run: python -I make_svgs_r7.py
"""
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import r7_calc as R  # noqa: E402  (module import parses the .brd; no output file is written)

OUTDIR = os.path.dirname(HERE)
CALC_JSON = os.path.join(HERE, "r7_calc_out.json")
CALC_TXT = os.path.join(HERE, "r7_calc_out.txt")

INK, MUTE, PWR, BAT, SIG, TAP, GNDC, FILL1, FILL2, FILL3, FILL4 = (
    "#1b1f24", "#5b6470", "#c0392b", "#8e44ad", "#1f6fb2", "#2e8b57", "#444", "#f4f6f8", "#fff7e6", "#eef6ff", "#f0fff4")


# ===================================================================== text extent estimate (overlap check)
def text_w(s, size, bold=False):
    """Advance-width estimate for DejaVu Sans (the widest font in the font-family list), in px."""
    w = 0.0
    for ch in s:
        if ch == " ":
            f = 0.32
        elif ch in "iljI.,:;'|!":
            f = 0.30
        elif ch in "ftr()[]/-\\":
            f = 0.40
        elif ch in "mwMW%":
            f = 0.92
        elif ch.isupper():
            f = 0.70
        elif ch.isdigit():
            f = 0.64
        else:
            f = 0.58
        w += f
    return w * size * (1.08 if bold else 1.0)


def text_box(x, y, s, size, anchor="start", bold=False):
    w = text_w(s, size, bold)
    x0 = x if anchor == "start" else (x - w / 2 if anchor == "middle" else x - w)
    return (x0, y - 0.78 * size, x0 + w, y + 0.22 * size)


def boxes_overlap(a, b, tol=0.5):
    return min(a[2], b[2]) - max(a[0], b[0]) > tol and min(a[3], b[3]) - max(a[1], b[1]) > tol


class Svg:
    """Round-3 drawing primitives (round3/calc/make_svgs.py), unchanged in output; text extents are recorded."""

    def __init__(self, w, h, title):
        self.w, self.h, self.items, self.tb = w, h, [], []
        self.items.append('<rect x="0" y="0" width="%d" height="%d" fill="#ffffff"/>' % (w, h))
        self.text(w / 2, 26, title, 18, anchor="middle", weight="bold")

    def text(self, x, y, s, size=11, anchor="start", color=INK, weight="normal", italic=False):
        st = ' font-style="italic"' if italic else ""
        self.items.append('<text x="%.1f" y="%.1f" font-family="DejaVu Sans, Arial, sans-serif" font-size="%s" '
                          'text-anchor="%s" fill="%s" font-weight="%s"%s>%s</text>' % (x, y, size, anchor, color, weight, st, escape(s)))
        if s:
            self.tb.append(text_box(x, y, s, float(size), anchor, weight == "bold") + (s,))

    def box(self, x, y, w, h, title=None, fill=FILL1, stroke=INK, sw=1.4, dash=None, tsize=13):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        self.items.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="6" fill="%s" stroke="%s" stroke-width="%s"%s/>'
                          % (x, y, w, h, fill, stroke, sw, d))
        if title:
            self.text(x + 8, y + 18, title, tsize, weight="bold")

    def line(self, pts, color=INK, sw=1.4, dash=None):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        p = " ".join("%.1f,%.1f" % q for q in pts)
        self.items.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="%s"%s/>' % (p, color, sw, d))

    def dot(self, x, y, color=INK, r=2.6):
        self.items.append('<circle cx="%.1f" cy="%.1f" r="%s" fill="%s"/>' % (x, y, r, color))

    def pin(self, x, y, label, side="L", color=INK, size=10):
        self.dot(x, y, color)
        if side == "L":
            self.text(x - 5, y + 3.5, label, size, anchor="end", color=color)
        else:
            self.text(x + 5, y + 3.5, label, size, anchor="start", color=color)

    def res(self, x1, y1, x2, y2, label, color=INK):
        # draw a resistor body centred on the segment (horizontal or vertical)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        if abs(x2 - x1) >= abs(y2 - y1):
            self.line([(x1, y1), (mx - 14, my)], color)
            self.line([(mx + 14, my), (x2, y2)], color)
            self.items.append('<rect x="%.1f" y="%.1f" width="28" height="9" fill="#fff" stroke="%s" stroke-width="1.3"/>' % (mx - 14, my - 4.5, color))
            self.text(mx, my - 8, label, 9, anchor="middle", color=color)
        else:
            self.line([(x1, y1), (mx, my - 14)], color)
            self.line([(mx, my + 14), (x2, y2)], color)
            self.items.append('<rect x="%.1f" y="%.1f" width="9" height="28" fill="#fff" stroke="%s" stroke-width="1.3"/>' % (mx - 4.5, my - 14, color))
            self.text(mx + 8, my + 3, label, 9, color=color)

    def cap(self, x, y, label, vertical=True, color=INK, left=False):
        # capacitor from (x,y) down to ground symbol
        self.line([(x, y), (x, y + 10)], color)
        self.line([(x - 8, y + 10), (x + 8, y + 10)], color, 2)
        self.line([(x - 8, y + 15), (x + 8, y + 15)], color, 2)
        self.line([(x, y + 15), (x, y + 24)], color)
        self.gnd(x, y + 24)
        if left:
            self.text(x - 11, y + 15, label, 9, anchor="end", color=color)
        else:
            self.text(x + 11, y + 15, label, 9, color=color)

    def gnd(self, x, y, color=GNDC):
        self.line([(x - 7, y), (x + 7, y)], color, 1.6)
        self.line([(x - 4, y + 3), (x + 4, y + 3)], color, 1.4)
        self.line([(x - 1.5, y + 6), (x + 1.5, y + 6)], color, 1.2)

    def flag(self, x, y, name, side="R", color=SIG):
        w = text_w(name, 9) + 16                     # text extent + tip and margin (was 7 px/char, overstated)
        if side == "R":
            pts = [(x, y), (x + 6, y - 7), (x + w, y - 7), (x + w, y + 7), (x + 6, y + 7), (x, y)]
            tx = x + 9
        else:
            pts = [(x, y), (x - 6, y - 7), (x - w, y - 7), (x - w, y + 7), (x - 6, y + 7), (x, y)]
            tx = x - w + 4
        p = " ".join("%.1f,%.1f" % q for q in pts)
        self.items.append('<polygon points="%s" fill="#ffffff" stroke="%s" stroke-width="1.1"/>' % (p, color))
        self.text(tx, y + 3.5, name, 9, color=color)

    def tri(self, x, y, h, label):
        # comparator: left edge at x, centre y, height h
        pts = [(x, y - h / 2), (x + h * 0.9, y), (x, y + h / 2), (x, y - h / 2)]
        p = " ".join("%.1f,%.1f" % q for q in pts)
        self.items.append('<polygon points="%s" fill="#ffffff" stroke="%s" stroke-width="1.5"/>' % (p, INK))
        self.text(x + 6, y - h / 2 + 14, "+", 12)
        self.text(x + 6, y + h / 2 - 6, "-", 12)
        self.text(x + h * 0.3, y + 4, label, 9, weight="bold")

    def raw(self, s):
        self.items.append(s)

    def save(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">\n' % (self.w, self.h, self.w, self.h))
            fh.write("\n".join(self.items))
            fh.write("\n</svg>\n")


# ===================================================================== wiring diagram (round 3 + r7 changes)
W_CAP = "<= 0.30 m until MS2; route maxima after MS2"     # BASIS D7: 0.30 m caps stay the T-A-02 bound until MS2
W12_LEN = "fixed 0.30 m +- 10 mm (D-F3); slack = service loop"  # r7 review 7 D-F3 (A.3): W1/W2 are never cut to the route


def wiring():
    s = Svg(1760, 1300, "BQ25798EVM in place of the Ag105: wiring (board rev 20260622, round 4 r7)")
    s.text(880, 46, "docs/charger_bq25798_wiring_design_2026-11-05.md sections A.2-A.8 are the netlist; this drawing must match them", 11, "middle", MUTE)

    # ---------------- motherboard
    s.box(20, 70, 580, 1200, "MB  motherboard rev 20260622 (Ag105 removed)", FILL1)
    s.box(40, 110, 240, 70, "D-BC-FC  RT1987 (EN = pin 31)", "#fff")
    s.text(48, 150, "VIN = VBUS   VOUT = VCHG-IN", 10)
    s.text(48, 166, "EN net J1.45/46 -> T5", 10, color=MUTE)
    s.box(40, 200, 240, 70, "D-BC-RG  RT1987 (EN = pin 30)", "#fff")
    s.text(48, 240, "VIN = V-MOT  VOUT = VCHG-IN", 10)
    s.text(48, 256, "EN net J1.43/44 -> T4", 10, color=MUTE)
    s.box(300, 110, 280, 70, "VBUS node", "#fff")
    s.text(308, 150, "C-D2 pad 1 -> R171 10.0k (at joint) -> T2", 10, color=TAP)
    s.text(308, 166, "D-MT-EN VIN, D-BT-EN VOUT (EN 28 -> T3)", 10, color=MUTE)
    s.box(300, 200, 280, 70, "V-MOT node", "#fff")
    s.text(308, 240, "C-D6 pad 1 -> R170 10.0k -> T1; pad 2 -> T7b (shield)", 10, color=TAP)
    s.text(308, 256, "CAL 470 uF, VESC J-M, chopper", 10, color=MUTE)
    s.box(40, 290, 240, 64, "VCHG-IN: C-D8, C-D10 (35 V)", "#fff")
    s.text(48, 326, "R1/R2-CHG -> pin 38 (no W8)", 10, color=MUTE)
    s.text(48, 342, "r2: no current limit in Run", 10, color=MUTE)
    s.box(300, 290, 280, 64, "D-BT-SQ  RT1987 (EN = pin 32)", "#fff")
    s.text(308, 330, "VIN = VCHG   VOUT = VBT (pack +)", 10)
    s.line([(155, 180), (155, 290)], PWR, 2.4)
    s.text(162, 285, "VCHG-IN", 9, color=PWR)
    s.box(300, 370, 280, 40, "SNS-BT INA253 (55.1, 23.6 mm): GND/REF1 pad -> T9", "#fff", tsize=10)

    fx, fy = 60, 430
    s.box(fx, fy, 500, 330, "CHG footprint (Ag105 holes) -> carrier CR header pins", FILL2, dash="6,3")
    left = [("1 VSEL", "nc", MUTE), ("2 CSEL", "nc", MUTE), ("3 STAT", "CHRG-STAT -> Teensy 6", SIG), ("4 VIN-", "GND (power star)", GNDC),
            ("5 NC1", "nc", MUTE), ("6 NC2", "nc", MUTE), ("7 SCL", "SCL -> Teensy 19, RSCL 2.7k (PM9)", SIG), ("8 SDA", "SDA -> Teensy 18, RSDA 2.7k (PM9)", SIG),
            ("9 NC3", "nc", MUTE), ("10 VIN+", "VCHG-IN", PWR)]
    right = [("11 MPPTD", "CHG_ARM <- Teensy 5", SIG), ("12 MPPTSEL", "nc", MUTE), ("13 THERM", "N$34 -> J-NTC 1", SIG),
             ("14 VBAT-1", "GND (power star)", GNDC), ("15 VBAT-2", "GND (power star)", GNDC), ("16 VLOAD-1", "nc", MUTE),
             ("17 VLOAD-2", "nc", MUTE), ("18 VBAT+1", "VCHG", BAT), ("19 VBAT+2", "VCHG", BAT), ("20 LDIS", "nc", MUTE),
             ("21 VLOAD+1", "nc", MUTE), ("22 VLOAD+2", "nc", MUTE)]
    pad = {}
    for i, (p, n, c) in enumerate(left):
        y = fy + 40 + i * 28
        s.dot(fx + 20, y, c, 4)
        s.text(fx + 30, y + 4, p, 10, weight="bold", color=c)
        s.text(fx + 105, y + 4, n, 9, color=c)
        pad[p.split()[0]] = (fx + 20, y)
    for i, (p, n, c) in enumerate(right):
        y = fy + 36 + i * 24
        s.dot(fx + 480, y, c, 4)
        s.text(fx + 470, y + 4, p, 10, anchor="end", weight="bold", color=c)
        s.text(fx + 380, y + 4, n, 9, anchor="end", color=c)
        pad[p.split()[0]] = (fx + 480, y)
    s.text(fx + 10, fy + 322, "pins 1-10 at board x 46.0 mm (input side); 11-22 at x 21.0 mm (battery side); table A.8", 9, color=MUTE)
    s.line([(155, 354), (155, 410), (40, 410), (40, pad["10"][1]), (pad["10"][0], pad["10"][1])], PWR, 2.4)
    # VCHG (D-BT-SQ VIN) leaves the box on its right side and runs down x 590, clear of the SNS-BT box text
    s.line([(580, 322), (590, 322), (590, pad["18"][1]), (pad["18"][0], pad["18"][1])], BAT, 2.4)

    s.box(40, 790, 540, 460, "Teensy 4.1 breakout J1 / J2 (female, two positions per pin)", "#fff")
    taps = [("J1.39", "D-BT-EN net (pin 28 BT_BUS)", "T3"), ("J1.43", "D-BC-RG net (pin 30 REGEN)", "T4"),
            ("J1.45", "D-BC-FC net (pin 31 FC_CHARGE)", "T5"), ("J1.29", "3V3 (only rail source; CR R175 68R)", "T6"),
            ("J2.31", "BT-CURR (pin 41, INA253 BT)", "T8"), ("J1.23", "pin 10  CHG_QUAL (out)", "T10"), ("J2.19", "pin 17  CHG_FCCEIL (out)", "T11"),
            ("J2.47", "pin 33  CHG_ILIM_RB (in, far end)", "T12"), ("J2.45", "pin 34  CHG_H1_RB (in, GPIO only)", "T13"),
            ("J2.21", "pin 16  CHG_H2_RB (in)", "T14"), ("J2.07", "pin 23  CHG_BTOK_RB (in)", "T15"),
            ("J2.43", "pin 35  CHG_EFUSE_FLT (in, INPUT_PULLUP)", "T16"), ("J2.09", "pin 22 (A8) CHG_IIN (analog)", "T17"),
            ("J2.29", "GND (T17 shield, CR end only)", "T17r"), ("ROS pad 2", "pin 7  CHG_CE_RB (in, far end; ROS removed)", "T20"),
            ("J2.11", "pin 21  CHG_HB heartbeat (out)", "T21"), ("J2.33", "pin 40 FC_CURRENT (U117 option, DNP)", "T19"),
            ("BAL pad 8", "BQ29200 OUT (BAL-NOK) -> pack-OV permit, 30 AWG (r6)", "T22")]
    for i, (j, n, t) in enumerate(taps):
        y = 820 + i * 19
        s.text(52, y + 4, j, 10, weight="bold")
        s.text(116, y + 4, n, 10)
        s.dot(568, y, TAP)
        s.text(560, y + 4, t, 9, anchor="end", color=TAP)
    s.text(52, 1172, "CO-5V pad 1 (+5 V) -> F101 fuse + R172 33R at the joint -> T18, keep-alive option only (DNP).", 10, color=MUTE)
    s.text(52, 1188, "T1/T2: 10.0k at the joint, then the wire.", 10, color=MUTE)
    s.text(52, 1204, "Pins 5, 6, 18, 19 reach CR through CHG pads 11, 3, 8, 7 (no tap). Pin 20 kept for WDOG1_B (R5).", 10, color=MUTE)
    s.text(52, 1220, "Pins 2, 8 (encoder nets) untouched (T-A-01b); F24 optional PURGE_SENSE on pin 2 only if cleared. No T7.", 10, color=MUTE)

    # ---------------- r7: EVM plate carrying the EIB and the EVM (BASIS D7, section 1 "EVM plate"); drawn first (background)
    s.box(1062, 74, 690, 1150, "EVM plate (insulating, on the chassis)", "#fafaf7", MUTE, 1.4, "8,4", 13)
    s.text(1072, 300, "EVM on its stock bumpons, held by edge clamps;", 10, color=MUTE)
    s.text(1072, 316, "EIB on its two M3 nylon standoffs (EVM and EIB on one plate)", 10, color=MUTE)

    # ---------------- carrier
    cx, cy, cw, ch = 650, 110, 400, 1000
    s.box(cx, cy, cw, ch, "CR r7: r6 footprint + tab X + tab Y, FT1/FT2", FILL3)                        # r7
    s.text(cx + 10, cy + 40, "1x10 + 1x12 header pins = CHG pads (A.2); netlist B.8", 10, color=MUTE)
    s.box(cx + 20, cy + 60, 360, 138, "U101 eFuse TPS26630RGER", "#fff")
    s.text(cx + 30, cy + 96, "IN/IN_SYS <- VCHGIN (pad 10 only)   OUT -> VCHGOUT", 10)
    s.text(cx + 30, cy + 112, "I_OL 2.05-2.41 A (R101 8.06k); UVLO 9.9 V; OVP 23.1 V", 10)
    s.text(cx + 30, cy + 128, "IN: C102a/b/c 1u+4.7u(100V)+0.1u, D107 SMAJ33A class;", 10)
    s.text(cx + 30, cy + 144, "OUT: D103 SMA + C103 (r5 region table)", 10)
    s.text(cx + 30, cy + 160, "IMON 27.4k -> R129 10k / C129 1n -> T17; FLT -> T16 (R106 DNP)", 10)
    s.text(cx + 30, cy + 176, "MODE open, SHDN open, PGTH + PGOOD to GND", 10, color=MUTE)
    s.box(cx + 20, cy + 205, 360, 150, "Comparators (TLV3012B x 7, r6)", "#fff")
    s.text(cx + 30, cy + 243, "U102 H1: V-MOT (T1) vs VBUS (T2C), ratio 1.089", 10)
    s.text(cx + 30, cy + 261, "U103 UVB: VBUS > 13.33 / 13.72 V (same T2 wire)", 10)
    s.text(cx + 30, cy + 279, "U104 BT_OK: BT-CURR (T8) < 19.75 mV, Kelvin T9 + R143", 10)
    s.text(cx + 30, cy + 297, "U115 BTB_OFF: D-BT-EN (T3) < REF/3 (0.39-0.44 V)", 10)
    s.text(cx + 30, cy + 315, "U119 FCC_OFF (T5 < REF/3); U120 FCC_ON, U121 RGN_ON (> 1.75 V)", 10)
    s.text(cx + 30, cy + 333, "readbacks: H1 -> T13, H2c -> T14, BT_OK -> T15", 10, color=MUTE)
    s.box(cx + 20, cy + 372, 360, 250, "Permit logic + monostables (SN74LVC, 3V3 from T6)", "#fff")
    eqs = ["H1q = H1 . RGN_ON . FCC_OFF . UVB;  H1R = H1 . RGN_ON (U118A)", "H2c = FCC_ON . BTB_OFF . BT_OK . FCI_OK . ((UVB . FCCEIL) + H1R)", "GATE = H1q + H2c",
           "QQ = U111 one-shot (QUAL, CLR = P5N); QQF = QQ . FCC_OFF", "ARM_OK' = ARM_OK (U113, 20-46 ms) . OVN (BQ29200 via U123, r6)",
           "ILIM_REL = (GATE + QQF) . ARM_OK' -> W5 pins 7 and 8", "CE_DRV = P5 . ARM_OK'              -> W5 pin 5",
           "RFC_OFF = FCC_OFF + H1R            -> W5 pin 10", "inputs: FCC F06 (U119/U120), RGN F05 (U121), BTB F04, BAL F08,",
           "QUAL F11, FCCEIL F12, HB F21, CHG_ARM (P5) pad 11", "FCI_OK = 3V3 (R137) unless U117 option fitted"]
    for i, e in enumerate(eqs):
        s.text(cx + 30, cy + 410 + i * 18, e, 10, color=INK if i < 8 else MUTE)
    s.box(cx + 20, cy + 640, 360, 70, "Keep-alive option (DNP, R9)", "#fff", dash="5,3")
    s.text(cx + 30, cy + 676, "5V (T18) -> U112 TPS22810 (EN = RGN) -> D101 -> 680 R", 10)
    s.text(cx + 30, cy + 694, "-> VCHG (pads 18/19). Fit only if T-B-09 fails", 10, color=MUTE)
    s.box(cx + 20, cy + 725, 360, 126, "Connectors and pads", "#fff")
    s.text(cx + 30, cy + 761, "J101 2x7 1.27 mm SMT, keyed -> W5 ribbon to EIB J201", 10)
    s.text(cx + 30, cy + 779, "tap field: 6 x 4 grid on tab X + residual pads F08-F10, F22 (A.7 r7)", 10)          # r7
    s.text(cx + 30, cy + 797, "power holes (r5): W1/W2 1.3 mm, pad 2.3 (30.3/27.7, 61.2),", 10)
    s.text(cx + 30, cy + 813, "W3/W4 1.5 mm (24.3, 45.4/55.6)", 10)
    s.text(cx + 30, cy + 831, "SCL/SDA/GND pads -> W7 to EVM J8; R145/R146 DNP", 10)
    s.text(cx + 20, cy + 870, "Power star: CR GND = pads 4, 14, 15", 10, color=GNDC, weight="bold")
    s.text(cx + 20, cy + 888, "STAT pad 3: R107 10k to 3V3 -> W5 pin 4", 10, color=SIG)
    s.text(cx + 20, cy + 942, "3V3: T6 -> R175 68R (pad R175a -> R175b); R176/R177 -> W5 1/2", 10, color=SIG)
    s.text(cx + 20, cy + 906, "THERM pad 13 -> W6 (only if NTC, T-E-09)", 10, color=SIG)
    s.text(cx + 20, cy + 924, "readback in: W5 11 -> R125 -> T12; W5 13 -> R148 -> T20 (pin 7)", 10, color=SIG)
    s.text(cx + 20, cy + 960, "r7: Eagle coords, +y UP; chamfer at the tab Y -x/+y corner (17.70, 76.00), pin-11 side", 10, color=MUTE)
    s.text(cx + 20, cy + 978, "r7: W leads on the A.3 dressing path (B1/B3, S1-S3, A1/A2)", 10, color=MUTE)

    s.line([(pad["22"][0] + 10, fy + 160), (cx, fy + 160)], MUTE, 6, "2,4")
    s.text(620, fy + 150, "22 pins", 10, "middle", MUTE)
    for i in range(len(taps)):
        y = 820 + i * 19
        s.line([(568, y), (612, y), (612 + (i % 5) * 4, cy + 790), (cx, cy + 779)], TAP, 0.8)
    s.line([(580, 150), (622, 150), (622, cy + 243), (cx + 20, cy + 243)], TAP, 1.2)
    s.text(585, 145, "T2", 9, color=TAP)
    s.line([(580, 240), (632, 240), (632, cy + 251), (cx + 20, cy + 251)], TAP, 1.2)
    s.text(585, 235, "T1, T7b", 9, color=TAP)
    s.line([(580, 390), (640, 390), (640, cy + 279), (cx + 20, cy + 279)], TAP, 1.2)
    s.text(604, 385, "T9", 9, color=TAP)

    # ---------------- EIB
    ex, ey = 1110, 470
    s.box(ex, ey, 270, 440, "EIB  EVM interface board (EVM plate)", FILL4)                                # r7: on the plate
    lines = [("U201 SN74LVC3G06 (open drain)", True), ("  1Y -> /CE (E5, TP36); R272 + R272b 47k on the EVM", False),
             ("  2Y -> Q203 gate (PMOS feed)", False), ("  3Y -> Q202 gate (FC leg)", False),
             ("U202 SN74LVC1G06 -> Q201 gate (hold)", True), ("Q203 BSS84: REGN -> R255 48.7k -> E2", False),
             ("   (JP14 pin 2; EVM R21 = 0 ohm)", False), ("Q201 2N7002K: ILIM (E3, TP33) -> AGND", False),
             ("Q202 2N7002K + R257 59.0k -> E3", False), ("gate pull-ups 47k to REGN (E1)", False),
             ("47k pull-downs on every driver input", False), ("U203 TLV3012B ILIM sense (E4, JP21)", True),
             ("   thr 0.59-0.65 V -> R265 470R -> W5 11", False), ("U204 TLV3012B /CE sense (E6, JP17)", True),
             ("   /CE/2 vs REF -> R264 470R -> W5 13", False), ("STAT: E7 TP38 -> R275 1k (r5) -> W5 4", False), ("AGND: E8 TP49", False),
             ("R273 10R ribbon GND; R274 10k bleed", False),
             ("R276 10.0R: E1 pad -> REGN node C205 (r7)", False),                                       # r7: BASIS D7
             ("unpowered: /CE HIGH, Q201 on, Q203 off", True)]
    for i, (l, b) in enumerate(lines):
        s.text(ex + 10, ey + 40 + i * 20, l, 10, weight="bold" if b else "normal", color=PWR if i == len(lines) - 1 else INK)

    # ---------------- EVM
    vx, vy = 1420, 110
    s.box(vx, vy, 320, 1100, "EVM  BQ25798EVM (BMS034A/B-003)", FILL2)
    blocks = [(vy + 50, "J1 (ED120/2DS)", ["pin 2 VIN1 <- W1", "pin 1 GND <- W2"], PWR),
              (vy + 150, "J5 (ED120/3DS)", ["pin 1 BATTERY <- W3", "pin 2 EXT_BATP (empty)", "pin 3 GND <- W4"], BAT),
              (vy + 270, "J7 (3.5 mm)", ["pin 1 EXT_TS <- W6 (if NTC)", "pin 2 AGND"], SIG),
              (vy + 370, "J8 (KK 254 4-pin)", ["2 SCL, 3 SDA <- W7 (1, 4 empty)", "W7 GND bonded at the CR only"], SIG),
              # r7: E-lead build maxima (mm, BASIS D7 / H.23(k)); E4 lands on JP21 pin 1 = the lower post
              (vy + 470, "EIB joints (A.5 row top->bottom, max mm)", ["E8 TP49 AGND 20;  E3 TP33 ILIM 25", "E4 JP21 pin 1 (lower post) 30",
                                                                    "E2 JP14 pin 2 35;  E7 TP38 STAT 40", "E1 JP12 REGN pin 90 (R276 at EIB)",
                                                                    "E5 TP36 /CE 65;  E6 JP17 (sense) 60"], INK),
              (vy + 620, "On-EVM parts", ["R256 200k + C252 2.2n across JP21 1-2", "R272 (R42 site) + R272b (TP36) 47k -> REGN", "EVM R23 -> 49.9k; R21 -> 0 ohm"], INK),
              (vy + 750, "Mods (section C)", ["JP17 shunt + pin 2 (AGND);", "R42, R39, R40, JP32, JP7, JP30 out", "JP14 shunt + pin 1, JP13 pin 1, R20 out",
                                         "JP1/JP2 2-3; JP3/JP5 links in holes, JP4 shunt", "JP8 1-2; JP9 2-3; JP6/10/11 out", "C11, C12, C29-C31 -> 35 V",
                                         "J2 removed, J3/J4 insulated; JP24 kept", "JP18 kept unless NTC (T-E-09)", "no capacitor added at the input"], INK)]
    anchors = {}
    for y, t, ls, col in blocks:
        s.box(vx + 15, y, 290, 20 + 17 * len(ls) + 8, t, "#fff", tsize=11)
        for i, l in enumerate(ls):
            s.text(vx + 25, y + 36 + i * 17, l, 10, color=col)
        anchors[t.split()[0]] = y + 30
    s.line([(cx + cw, cy + 90), (1260, cy + 90), (1260, anchors["J1"]), (vx + 15, anchors["J1"])], PWR, 3)
    s.line([(cx + cw, cy + 100), (1250, cy + 100), (1250, anchors["J1"] + 17), (vx + 15, anchors["J1"] + 17)], INK, 3)
    s.text(1070, cy + 84, "W1/W2  20 AWG twisted pair", 10, color=PWR)
    s.text(1070, cy + 116, W12_LEN, 10, color=PWR)                                                       # r7 review 7 (D-F3)
    s.line([(cx + cw, cy + 950), (1395, cy + 950), (1395, anchors["J5"]), (vx + 15, anchors["J5"])], BAT, 3.4)
    s.line([(cx + cw, cy + 960), (1405, cy + 960), (1405, anchors["J5"] + 34), (vx + 15, anchors["J5"] + 34)], INK, 3.4)
    s.text(1070, cy + 984, "W3/W4  18 AWG twisted pair", 10, color=BAT)
    s.text(1070, cy + 1000, W_CAP, 10, color=BAT)                                                        # r7
    s.line([(cx + cw, cy + 827), (1385, cy + 827), (1385, anchors["J8"]), (vx + 15, anchors["J8"])], SIG, 1.8)
    s.text(1070, cy + 821, "W7  SCL-GND-SDA twisted triple", 10, color=SIG)
    s.text(1070, cy + 843, W_CAP, 10, color=SIG)                                                         # r7
    s.line([(cx + cw, cy + 761), (1090, cy + 761), (1090, ey + 200), (ex, ey + 200)], SIG, 2.2)
    s.box(1080, ey - 88, 300, 80, None, "#fff", stroke=SIG, sw=1)
    s.text(1088, ey - 71, "W5  14-way 0.635 mm ribbon, fixed 0.30 m cable (J101 -> J201)", 10, color=SIG)
    s.text(1088, ey - 54, "1 3V3  2 3V3  3 GND  4 STAT  5 CE_DRV", 9, color=SIG)
    s.text(1088, ey - 39, "6 KEY (pin omitted)  7 REL_A  8 REL_B  9 GND", 9, color=SIG)
    s.text(1088, ey - 24, "10 RFC_OFF  11 ILIM_SNS  12 GND  13 CE_SNS  14 GND", 9, color=SIG)
    s.line([(ex + 270, ey + 150), (1415, ey + 150), (1415, anchors["EIB"]), (vx + 15, anchors["EIB"])], INK, 1.6)
    s.line([(cx + cw, cy + 906), (1375, cy + 906), (1375, anchors["J7"]), (vx + 15, anchors["J7"])], SIG, 1.4, "6,3")
    s.text(1070, cy + 900, "W6  26 AWG pair (only if NTC)", 10, color=SIG)

    # r7: the legend moves to a strip under the CR box and the EVM plate (the plate occupies its round-3 place)
    lx, ly = 650, 1232
    s.box(lx, ly, 1100, 62, "Legend", "#fff", tsize=11)
    for i, (c, t, w) in enumerate([(PWR, "charger input (VCHG-IN / VCHGOUT)", 3), (BAT, "charger output (VCHG)", 3), (INK, "return / GND / EIB joints", 3),
                                   (SIG, "signal / I2C / ribbon", 2), (TAP, "tap to MB (26 AWG)", 1.2), (MUTE, "mechanical / not connected", 1.2)]):
        x0, y0 = lx + 90 + (i % 3) * 335, ly + 22 + (i // 3) * 22
        s.line([(x0, y0), (x0 + 40, y0)], c, w)
        s.text(x0 + 48, y0 + 4, t, 10)
    path = os.path.join(OUTDIR, "wiring_bq25798.svg")
    s.save(path)
    return s, path


# ===================================================================== carrier schematic (round 3 + r7 changes)
def schematic():
    s = Svg(1760, 1420, "CHG adapter carrier (CR) and EVM interface board (EIB): schematic, round 4 r7")
    s.text(880, 46, "Net-label schematic. Values from calc/r3_calc.py; pin numbers in design section B.8. Every net name matches section B", 11, "middle", MUTE)

    # ---------- eFuse
    s.box(20, 70, 560, 340, "1  eFuse U101 TPS26630RGER", FILL1)
    s.box(200, 120, 160, 240, "U101", "#fff")
    lp = [("IN (1,2)", 150), ("IN_SYS (5)", 172), ("UVLO (6)", 210), ("OVP (7)", 240), ("dVdT (9)", 270), ("ILIM (10)", 300), ("MODE (11)", 330)]
    rp = [("OUT (17,18)", 150), ("IMON (13)", 190), ("FLT (14)", 262), ("SHDN (12)", 286), ("PGTH/PGOOD (15/16)", 306), ("B_GATE, DRV (3,4)", 326), ("GND (8), PAD", 346)]
    for n, y in lp:
        s.pin(200, y, "", "L")
        s.text(206, y + 3.5, n, 9)
    for n, y in rp:
        s.pin(360, y, "", "R")
        s.text(354, y + 3.5, n, 9, anchor="end")
    s.line([(110, 150), (200, 150)], PWR, 2)
    s.line([(150, 150), (150, 172), (200, 172)], PWR, 1.5)
    s.dot(150, 150, PWR)
    s.cap(130, 150, "")
    s.text(66, 138, "C102a/b/c 1u+4.7u+0.1u; D107", 8)
    s.res(45, 150, 45, 210, "R102 845k 0805")
    s.line([(45, 150), (110, 150)], PWR)
    s.flag(110, 150, "VCHGIN", "L", PWR)               # drawn after the wire so the wire does not cross the name
    s.line([(45, 210), (200, 210)])
    s.res(45, 210, 45, 240, "R103 66.5k")
    s.line([(45, 240), (200, 240)])
    s.dot(45, 240)
    s.res(45, 240, 45, 300, "R104 49.9k")
    s.gnd(45, 300)
    s.text(26, 320, "(0.1 %)", 8, color=MUTE)
    s.cap(185, 270, "")
    s.text(173, 276, "C101 22n", 9, anchor="end")
    s.line([(185, 270), (200, 270)])
    s.res(200, 300, 130, 300, "")
    s.text(160, 316, "R101 8.06k", 9, anchor="middle")         # below the resistor, clear of the C101 ground
    s.gnd(115, 306)
    s.line([(115, 300), (115, 306)])
    s.text(206, 376, "MODE open = latch-off", 9, color=MUTE)
    s.flag(500, 150, "VCHGOUT", "R", PWR)
    s.line([(360, 150), (500, 150)], PWR, 2)
    s.cap(400, 150, "C103 1u")
    s.items.append('<polygon points="452,166 444,152 460,152" fill="#fff" stroke="%s"/>' % INK)
    s.line([(444, 166), (460, 166)])
    s.line([(452, 150), (452, 152)])
    s.line([(452, 166), (452, 176)])
    s.gnd(452, 176)
    s.text(466, 172, "D103 low-IR Schottky", 8)
    s.res(360, 190, 470, 190, "")
    s.text(415, 207, "R129 10k", 9, anchor="middle")         # below the resistor, clear of the C103 ground
    s.flag(470, 190, "CHG_IIN (T17)", "R")
    s.res(385, 190, 385, 240, "")
    s.text(393, 233, "R105 27.4k", 9)                          # below the R129 label, right of the resistor
    s.gnd(385, 240)
    s.text(300, 232, "C105 DNP (r6)", 8)
    s.cap(455, 190, "")
    s.text(470, 222, "C129 1n", 8)
    s.res(360, 262, 470, 262, "")
    s.flag(470, 262, "CHG_EFUSE_FLT (T16)", "R")
    s.text(392, 254, "R106 DNP (pin 35 INPUT_PULLUP)", 8)
    s.text(366, 292, "open (internal 2.48-3.3 V)", 9, color=MUTE)
    s.line([(360, 306), (380, 306)])
    s.gnd(380, 306)
    s.text(366, 332, "open", 9, color=MUTE)
    s.line([(360, 346), (420, 346)])
    s.gnd(420, 346)
    s.text(30, 400, "I_OL 2.05-2.41 A; fast-trip 2x; UVLO 9.9 V; OVP 23.1 V (22.6-23.6); ramp 2.19 V/ms; no clamp diode on IMON", 9, color=MUTE)

    # ---------- comparators
    s.box(600, 70, 560, 600, "2  Comparators (TLV3012BIDBVR; V+ = 3V3, 100 nF each)", FILL1)
    s.tri(840, 150, 70, "U102")
    s.flag(660, 115, "T1 (R170 10k at MB)", "L", TAP)
    s.res(660, 115, 740, 115, "R109 487k 0805")
    s.line([(740, 115), (780, 115), (780, 130), (840, 130)])
    s.res(780, 115, 780, 185, "")
    s.text(790, 160, "R110 56.2k", 8)
    s.gnd(780, 185)
    s.cap(760, 115, "C106", left=True)
    s.flag(660, 230, "T2C (R171 10k at MB)", "L", TAP)
    s.res(660, 230, 740, 230, "R111 442k 0805")
    s.line([(740, 230), (810, 230), (810, 170), (840, 170)])
    s.res(810, 230, 810, 290, "")
    s.text(820, 270, "R112 56.2k", 8)
    s.gnd(810, 290)
    s.cap(725, 230, "C107")
    s.line([(903, 150), (980, 150)])
    s.flag(980, 150, "H1", "R")
    s.res(925, 150, 925, 98, "")
    s.line([(925, 98), (820, 98), (820, 130)])
    s.text(932, 120, "R113 6.49M", 8)
    s.text(850, 205, "D104/D105 BAV199 clamps on IN+/IN-", 8, color=MUTE)
    s.tri(840, 350, 70, "U103")
    s.flag(660, 320, "T2C", "L", TAP)
    s.res(660, 320, 740, 320, "R114 1.00M 0805")
    s.line([(740, 320), (780, 320), (780, 330), (840, 330)])
    s.res(780, 320, 780, 390, "")
    s.text(773, 372, "R115 104k", 8, anchor="end")
    s.gnd(780, 390)
    s.cap(755, 320, "C108 1n", left=True)
    s.line([(840, 370), (820, 370), (820, 410), (890, 410)])
    s.text(895, 414, "own REF; D106 clamp", 8)
    s.line([(903, 350), (980, 350)])
    s.flag(980, 350, "UVB", "R")
    s.res(925, 350, 925, 300, "")
    s.line([(925, 300), (820, 300), (820, 330)])
    s.text(932, 322, "R116 10.0M", 8)
    s.tri(840, 480, 70, "U104")
    s.text(640, 444, "REF -R141 61.9k- IN+ -R142 1.00k SOT- KELVIN (T9); R143 100R KELVIN-GND", 9)
    s.flag(820, 460, "IN+ 19.75 mV", "L")
    s.flag(700, 500, "BT_CURR (T8)", "L", TAP)
    s.res(700, 500, 780, 500, "R140 10k")
    s.line([(780, 500), (840, 500)])
    s.cap(800, 500, "C140 10n", left=True)
    s.text(640, 547, "R144 1.00M T8 -> 3V3 (open tap -> BT_OK LOW)", 9, color=TAP)
    s.line([(903, 480), (980, 480)])
    s.flag(980, 480, "BT_OK", "R")
    s.tri(840, 610, 70, "U115")
    s.text(640, 575, "IN+ = REF/3: R117 20.0k / R118 10.0k (C109 100n)", 9)
    s.flag(700, 630, "BTB (T3)", "L", TAP)
    s.res(700, 630, 780, 630, "R120 10k")
    s.line([(780, 630), (840, 630)])
    s.text(640, 660, "R119 10.0M IN- -> 3V3 (open tap -> BTB_OFF LOW)", 9, color=TAP)
    s.line([(903, 610), (980, 610)])
    s.flag(980, 610, "BTB_OFF", "R")

    # ---------- logic
    s.box(1180, 70, 560, 600, "3  Permit logic and monostables (SN74LVC, VCC = 3V3)", FILL1)
    gates = [
        (1200, 105, "U105 3G04 (C114)", ["1A, 3A to GND (r6 spare); CHG_ARM -> P5N"]),
        (1200, 160, "U116A 2G08 AND", ["UVB, FCCEIL -> UF"]),
        (1200, 200, "U116B 2G08 AND", ["FCC_OFF (= FCCN), UVB -> W"]),
        (1200, 240, "U106A 2G32 OR", ["UF, H1R -> X"]),
        (1200, 280, "U106B 2G32 OR", ["FCC_OFF, H1R -> RFC_OFF"]),
        (1200, 320, "U107 1G11 3-AND", ["BT_OK, X, FCI_OK -> Y1"]),
        (1200, 360, "U108 1G11 3-AND", ["FCC_ON, BTB_OFF, Y1 -> H2c"]),
        (1200, 400, "U109 1G11 3-AND", ["H1, RGN_ON, W -> H1q"]),
        (1470, 105, "U110A 2G32 OR", ["H1q, H2c -> GATE"]),
        (1470, 145, "U111 1G123", ["B = QUAL, CLR = P5N -> QQ", "R150 100k / C150 3.3u: 0.20-0.46 s"]),
        (1470, 200, "U110B 2G32 OR", ["GATE, QQF -> ILIM_PRE"]),
        (1470, 240, "U113 1G123", ["B = HB, CLR = 3V3 -> ARM_OK", "R151 100k / C151 330n: 20-46 ms"]),
        (1470, 295, "U114A 2G08 AND", ["P5, ARM_OK' -> CE_DRV"]),
        (1470, 335, "U114B 2G08 AND", ["ILIM_PRE, ARM_OK' -> ILIM_REL"]),
        (1470, 375, "U118A 2G08 AND (r2)", ["H1, RGN_ON -> H1R"]),
        (1470, 413, "U118B 2G08 AND (r2)", ["QQ, FCC_OFF -> QQF"]),
    ]
    for x, y, t, ls in gates:
        hh = 20 + 14 * len(ls)
        s.box(x, y, 255, hh, None, "#fff")
        s.text(x + 8, y + 14, t, 10, weight="bold")
        for i, l in enumerate(ls):
            s.text(x + 14, y + 28 + i * 14, l, 9.5)
    ins = [("FCC (F06/T5, R122 1k -> U119/U120; R187 3.3M pu; R134 DNP)", 455), ("RGN (F05/T4, R121 1k -> U121; R133 100k pd)", 473),
           ("CHG_ARM (pad 11; R108 47k pd)", 491), ("QUAL (F11/T10; R147 1k, R123 47k pd)", 509), ("FCCEIL (F12/T11; R124 47k pd)", 527),
           ("HB (F21/T21; R135 1k, R136 100k pd)", 545), ("FCI_OK (R137 0R; U117/R160-R163/C124/C127 DNP)", 563),
           ("BAL (F08/T22; R178 100k, D108 clamp, R179 1M pu) -> U123", 581)]
    for n, y in ins:
        s.flag(1200, y, n, "R")
    outs = [("ILIM_REL: R131A -> J101.7, R131B -> J101.8", 455), ("CE_DRV: R130 100R -> J101.5", 473), ("RFC_OFF: R132 100R -> J101.10", 491),
            ("H1 R126 -> T13; H2c R127 -> T14; BT_OK R128 -> T15", 509), ("J101.11 ILIM_SENSE -> R125 1k -> T12", 527), ("J101.13 CE_SENSE -> R148 1k -> T20 (pin 7)", 545)]
    for n, y in outs:
        s.flag(1728, y, n, "L")                      # right-aligned off-sheet outputs, clear of the input flags
    s.text(1200, 604, "STAT pad 3: R107 10k to 3V3 -> J101.4. SDA/SCL pads 8/7 -> W7; R145/R146 DNP (pull-ups MB 2.7k, PM9).", 9, color=MUTE)
    s.text(1200, 620, "Decoupling 100 nF: C110 U102, C111 U103, C112 U104, C113 U115, C114-C123 U105-U116,", 9, color=MUTE)
    s.text(1200, 634, "C126 U118, C131-C135 U119-U123 (r6); C125 10u bulk.", 9, color=MUTE)

    # ---------- keep-alive
    s.box(20, 430, 560, 160, "4  Keep-alive option (DO NOT POPULATE unless T-B-09 fails)", FILL1, dash="5,3")
    s.flag(110, 490, "5V_KA (T18)", "L", PWR)
    s.box(170, 465, 120, 70, "U112 TPS22810", "#fff", tsize=10)
    s.line([(110, 490), (170, 490)], PWR)
    s.text(176, 510, "VIN    VOUT", 9)
    s.text(176, 524, "EN <- RGN   CT C152", 9)
    s.line([(290, 490), (330, 490)], PWR)
    s.text(300, 472, "D101 BAT54HT1G", 9)
    s.items.append('<polygon points="330,482 345,490 330,498" fill="#fff" stroke="%s"/>' % INK)
    s.line([(345, 482), (345, 498)])
    s.res(345, 490, 460, 490, "R_KA 680R 0.25W")
    s.flag(460, 490, "VCHG (pads 18/19)", "R", BAT)
    s.text(30, 570, "VCHG held 3.63-4.46 V while REGEN is closed; 0.7-1.4 mA in Run, 0.5-2.3 uA parked; QOD open", 9, color=MUTE)

    # ---------- r6 comparators and pack-OV input
    s.box(20, 598, 560, 88, "2b  r6: EN-net comparators and pack-OV permit input", FILL1)
    s.text(30, 632, "U119 FCC_OFF: IN+ = REF/3 (R184 20.0k / R185 10.0k, C130); IN- = FCC via R186 10.0k, R187 3.30M pu -> FCCN", 9)
    s.text(30, 647, "U120 FCC_ON / U121 RGN_ON: IN+ = tap x R189/(R188 453k + R189 1.00M) (R190/R191 for RGN), IN- = REF: 1.75-1.88 V", 9)
    s.text(30, 662, "U123 SN74LVC1G14 (Schmitt): BAL (T22) via R178 100k, D108 BAV199, R179 1.00M pu -> OVN = NOT(OV)", 9)
    s.text(30, 677, "U122 SN74LVC1G08: ARM_OK' = ARM_OK . OVN -> U114 pins 2 and 6 (open tap / unpowered BQ29200 = OV = inhibit)", 9)

    # ---------- EIB (r7: on the EVM plate)
    s.box(20, 690, 1720, 530, "5  EVM interface board (EIB, 2xx) on the EVM plate (insulating, on the chassis); VCC = 3V3 from ribbon pins 1+2 via CR R176/R177 200R (R274 10k bleed); AGND = TP49 (E8) only", FILL4)
    s.box(330, 730, 200, 290, "U201 SN74LVC3G06", "#fff")
    for i, (a, y) in enumerate([("1A", 770), ("2A", 860), ("3A", 950)]):
        s.pin(330, y, "", "L")
        s.text(336, y + 3.5, a, 9)
        s.pin(530, y, "", "R")
        s.text(524, y + 3.5, "%dY (OD)" % (i + 1), 9, anchor="end")
    for name, y, rin, rpd in (("CE_DRV (J201.5)", 770, "R250 1k", "R267 47k"), ("ILIM_REL_A (J201.7)", 860, "R251 1k", "R268 47k"),
                              ("RFC_OFF (J201.10)", 950, "R253 1k", "R269 47k")):
        s.flag(148, y, name, "L")
        s.res(150, y, 250, y, rin)
        s.line([(250, y), (330, y)])
        s.res(290, y, 290, y + 40, "")
        s.text(298, y + 26, rpd, 8)
        s.gnd(290, y + 40)
    s.line([(530, 770), (720, 770)])
    s.flag(720, 770, "/CE (E5, TP36)", "R", PWR)
    s.text(560, 760, "R272 (R42 site, link to TP27) + R272b (TP36, link to JP12) 47k /CE -> REGN on the EVM", 8, color=MUTE)
    s.line([(530, 860), (640, 860)])
    s.res(640, 860, 640, 810, "")
    s.text(648, 832, "R271 47k", 8)
    s.flag(640, 810, "REGN", "R", PWR)                                         # r7: the EIB REGN node; E1 enters via R276
    # r7 (BASIS D7): R276 10.0 ohm 1 % 0603 in series with E1 at the EIB E1 pad, between the E1 lead and the REGN node (C205)
    s.flag(900, 825, "E1 (JP12 REGN pin)", "L", PWR)
    s.res(900, 825, 1000, 825, "R276 10.0R 1 %", PWR)
    s.flag(1000, 825, "REGN (C205)", "R", PWR)
    s.box(660, 840, 130, 50, "Q203 BSS84", "#fff", tsize=10)
    s.text(666, 882, "G  S <- REGN  D -> R255", 8)
    s.res(790, 860, 900, 860, "R255 48.7k")
    s.flag(900, 860, "ILIM_FEED (E2, JP14 pin 2)", "R", PWR)
    s.line([(530, 950), (860, 950)])
    s.res(820, 950, 820, 910, "")
    s.text(828, 934, "R254 47k", 8)
    s.flag(820, 905, "REGN", "R", PWR)
    s.box(860, 930, 120, 50, "Q202 2N7002K", "#fff", tsize=10)
    s.text(866, 972, "G   D -> R257   S -> AGND", 8)
    s.res(980, 950, 1100, 950, "R257 59.0k")
    s.flag(1100, 950, "ILIM_HOLD (E3, TP33)", "R", PWR)
    # U202 / Q201
    s.box(1120, 740, 160, 70, "U202 SN74LVC1G06", "#fff", tsize=10)
    s.flag(1118, 775, "ILIM_REL_B (J201.8) R266 1k, R270 47k pd", "L")
    s.line([(1280, 775), (1360, 775)])
    s.res(1340, 775, 1340, 735, "")
    s.text(1348, 755, "R252 47k to REGN", 8)
    s.box(1360, 755, 130, 50, "Q201 2N7002K", "#fff", tsize=10)
    s.text(1366, 797, "G   D -> E3   S -> AGND", 8)
    s.line([(1490, 775), (1560, 775)])
    s.flag(1560, 775, "ILIM_HOLD (E3)", "R", PWR)
    # sense comparators
    s.tri(1500, 870, 60, "U203")
    s.flag(1470, 855, "ILIM_SNS (E4, JP21 pin 1, lower post)", "L", TAP)    # r7: JP21 pin 1 = the lower square post
    s.line([(1470, 855), (1500, 855)])
    s.text(1300, 880, "R258 10.0k series (r3); R259 10M to 3V3", 8)
    s.text(1300, 912, "IN- = REF x R261 10.0k/(R260 10.0k + R261) (0.59-0.65 V); R265 470R (r4)", 8)
    s.line([(1554, 870), (1600, 870)])
    s.flag(1600, 870, "J201.11 -> pin 33", "R")
    s.tri(1500, 970, 60, "U204")
    s.flag(1470, 955, "nCE_SNS (E6, JP17)", "L", TAP)
    s.line([(1470, 955), (1500, 955)])
    s.text(1300, 980, "R262 1M / R263 1M to AGND", 8)
    s.text(1460, 1012, "IN- = own REF: /CE threshold ~2.5 V; R264 470R (r4)", 8)
    s.line([(1554, 970), (1600, 970)])
    s.flag(1600, 970, "J201.13 -> R148 -> pin 7", "R")
    s.text(40, 1050, "EVM side: R21 -> 0 ohm, JP14 shunt + pin 1, JP13 pin 1 and R20 removed, R23 -> 49.9k, R256 200k + C252 2.2n across JP21 pins 1-2: regen clamp 1.33-1.76 A, FC clamp (Q202 on) 0.65-0.95 A, held <= 0.11 V", 9)
    s.text(40, 1070, "Release needs BOTH Q203 on (feed) and Q201 off (hold), each from its own driver and ribbon conductor; any open lead/resistor/driver leaves the converter in HIZ", 9, color=PWR, weight="bold")
    s.text(40, 1090, "Fail-safe: VCC = 0 -> U201/U202 outputs float -> /CE HIGH (R272/R272b), Q203 off (R271), Q201 on (R252), Q202 on (R254); pins 33/7 read LOW through pad pull-downs -> flagged", 9, color=PWR)
    s.text(40, 1110, "Broken sense wire: E4 -> R259 pulls U203 IN+ HIGH (reads released); E6 -> R263 pulls U204 IN+ LOW (reads /CE LOW): both are the dangerous direction and trip FR-08", 9)
    s.text(40, 1130, "Ribbon J201/J101 (1.27 mm, r4): 1 3V3 (R176), 2 3V3 (R177), 3 GND, 4 STAT (E7 TP38 via R275 1k, r5), 5 CE_DRV, 6 KEY (pin omitted), 7 ILIM_REL_A, 8 ILIM_REL_B, 9 GND, 10 RFC_OFF, 11 ILIM_SENSE, 12 GND, 13 CE_SENSE, 14 GND", 9, color=MUTE)
    s.text(40, 1150, "Decoupling C201-C204 100 nF at each VCC/V+; C205 100 nF at Q203 source (REGN). J201 GND pins 3/9/12/14 joined -> R273 10R -> AGND (single DC ground E8). E-pad row (r6, top to bottom): E8 - E3 E4 E2 - E7 - E1 - E5 E6 (E1 and E7 isolated by empty pads; 12 positions, 27.94 mm c-c)", 9, color=MUTE)
    # r7 (BASIS D7, H.23(k)): E-lead build maxima and R276
    s.text(40, 1170, "r7 (A.5): E-lead build maxima E8 20, E3 25, E4 30 (JP21 pin 1 = lower post), E2 35, E7 40, E1 90, E5 65, E6 60 mm; R276 10.0 ohm 1 % 0603 in series with E1 at the EIB E1 pad (E1 lead -> R276 -> REGN node, C205)", 9)

    s.box(20, 1235, 1720, 170, "6  Power-up / reset states", "#fff")
    rows = ["Teensy reset (pins high-Z): P5, QUAL, FCCEIL LOW (47k), HB no edges (100k) -> ARM_OK 0; EN nets LOW (10k bodge) -> FCC_ON = RGN_ON = 0 -> GATE 0; charger unpowered.",
            "Monostable power-up: Q LOW (glitch-free reset, SCES586E) -> QQ = 0, ARM_OK = 0 until the first heartbeat edge.",
            "Comparator POR (<= 1.9 ms, or V+ below its minimum): H1 = UVB = BT_OK = BTB_OFF = FCC_OFF = FCC_ON = RGN_ON = LOW -> H1q = H2c = 0, RFC_OFF = H1R (r6).",
            "CR 3V3 lost: no external source back-powers it (r2); EIB outputs float -> /CE HIGH, ILIM held (if REGN up), FC clamp; pin 7 LOW with P5 LOW and REGN expected -> FR-08(b). eFuse U101 runs from VCHG-IN.",
            "Teensy hang or stalled 1 kHz monitor: no heartbeat edges -> ARM_OK falls within 20-46 ms -> CE_DRV 0 (/CE HIGH) and ILIM_REL 0 (held) in every mode; BT_BUS stays as it was (R5).",
            "Charger POR: ILIM clamp latched from the pin at that instant: 100 mA if held, regen or FC level if released; /CE follows P5 . ARM_OK' until firmware re-images.",
            "r6: BQ29200 OUT HIGH (cell > 4.35 V for 1.6-4.9 s), T22 open or balance lead unplugged -> OVN 0 -> ARM_OK' 0 -> /CE HIGH and ILIM held in every mode; pin 7 shows the unexpected inhibit."]
    for i, r in enumerate(rows):
        s.text(34, 1268 + i * 22, r, 10)
    path = os.path.join(OUTDIR, "carrier_schematic.svg")
    s.save(path)
    return s, path


# ===================================================================== carrier layout (r7, new)
S = 8.0                                   # px/mm, main panel
WIN = (0.0, 25.0, 105.0, 100.0)           # main window x0, y0, x1, y1 (board mm)
PX0, PY0 = 40.0, 92.0                     # main panel top-left (px)
S2 = 2.4                                  # px/mm, EVM placement panel
WIN2 = (-14.0, 0.0, 134.0, 212.0)
QX0, QY0 = 928.0, 134.0                   # second panel top-left (px)


def X(x):
    return PX0 + (x - WIN[0]) * S


def Y(y):
    return PY0 + (WIN[3] - y) * S


def X2(x):
    return QX0 + (x - WIN2[0]) * S2


def Y2(y):
    return QY0 + (WIN2[3] - y) * S2


def rect_px(b, fx=X, fy=Y):
    """Board rectangle (x0, y0, x1, y1) -> px box (left, top, right, bottom)."""
    return (fx(b[0]), fy(b[3]), fx(b[2]), fy(b[1]))


def pts_attr(pts, fx=X, fy=Y):
    return " ".join("%.2f,%.2f" % (fx(p[0]), fy(p[1])) for p in pts)


def full_paths():
    """W-lead routes from the r7_calc_out.txt H.23(l) 'full path' lines (CR pad -> ... -> terminal)."""
    paths, lead, sec = {}, None, False
    with open(CALC_TXT, encoding="ascii", errors="replace") as fh:
        for line in fh:
            if line.startswith("H.23(l)"):
                sec = True
                continue
            if sec and line.startswith("H.23(m)"):
                break
            if not sec:
                continue
            m = re.match(r"^  (W\d(?: SCL| SDA)?)\s", line)
            if m:
                lead = m.group(1)
            if "full path:" in line and lead:
                paths[lead] = [(float(a), float(b)) for a, b in re.findall(r"\(\s*(-?[\d.]+),\s*(-?[\d.]+)\)", line)]
    return paths


def subpath(path, p0, p1):
    """Part of a polyline between the projections of p0 and p1 (both lie on it, H.23(l) l.rev4.sw3d)."""
    acc, segs = 0.0, []
    for a, b in zip(path[:-1], path[1:]):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        segs.append((a, b, acc, L))
        acc += L

    def proj(p):
        best = None
        for a, b, s0, L in segs:
            if L == 0:
                continue
            t = max(0.0, min(1.0, ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / L ** 2))
            q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            d = math.hypot(p[0] - q[0], p[1] - q[1])
            if best is None or d < best[0]:
                best = (d, s0 + t * L)
        return best[1]

    s0, s1 = sorted((proj(p0), proj(p1)))

    def at(sv):
        for a, b, st, L in segs:
            if st <= sv <= st + L + 1e-9 and L > 0:
                t = (sv - st) / L
                return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        return path[-1]

    out = [at(s0)]
    for a, b, st, L in segs:
        if s0 < st < s1:
            out.append(a)
    out.append(at(s1))
    return out


def poly_dist(b, poly):
    """Plan distance from a rectangle to a polygon outline (0 when they overlap)."""
    rp = R.rpoly(b)
    if any(R.pip(x, y, poly) for x, y in rp) or any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for x, y in poly):
        return 0.0
    return min(R.dseg_seg(a1, a2, c1, c2) for a1, a2 in R.edges(rp) for c1, c2 in R.edges(poly))


def intersects(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def layout():
    J = json.load(open(CALC_JSON))
    paths = full_paths()
    W, H = 1320, 1010
    s = Svg(W, H, "CHG carrier r7 (round 4): outline, tabs, feet, tap field")
    s.text(PX0, 50, "Top view, Eagle .brd board coordinates in mm (+y up), 8 px/mm. Sources: r7_calc_out.json H.23 (a), (d), (g), (h), (i), (l), (m); "
                    "design A.7/A.8; MB parts and layer-1 copper from the .brd (mb_neighbours.py via r7_calc.py).", 10, color=MUTE)
    s.text(PX0, 66, "Drawn on the CR top side: outlines, header pads, W1-W4 holes, W6/W7 pads, tap pads, R175 pads, J101 and comparator regions, "
                    "the W-lead dressing path, beads B1/B3 and W5 spacers S1-S3 (calc revision 4).", 10, color=MUTE)
    s.text(PX0, 80, "Drawn under the CR or on the MB: MB parts, MB copper, feet (CR bottom), polyimide sheet with relief holes and cut-outs, "
                    "polyimide strip, tie bases A1/A2.", 10, color=MUTE)
    s.raw('<defs>'
          '<pattern id="hFoot" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
          '<rect width="6" height="6" fill="#c8e6c9"/><line x1="0" y1="0" x2="0" y2="6" stroke="#1b5e20" stroke-width="1.6"/></pattern>'
          '<pattern id="hUsb" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">'
          '<rect width="7" height="7" fill="#ede7f6"/><line x1="0" y1="0" x2="0" y2="7" stroke="#7e57c2" stroke-width="1"/></pattern>'
          '<pattern id="hComp" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
          '<rect width="8" height="8" fill="#e3f2fd"/><line x1="0" y1="0" x2="0" y2="8" stroke="#90caf9" stroke-width="1.2"/></pattern>'
          '<clipPath id="cMain"><rect x="%.2f" y="%.2f" width="%.2f" height="%.2f"/></clipPath>'
          '<clipPath id="cEvm"><rect x="%.2f" y="%.2f" width="%.2f" height="%.2f"/></clipPath>'
          '</defs>' % (X(WIN[0]), Y(WIN[3]), (WIN[2] - WIN[0]) * S, (WIN[3] - WIN[1]) * S,
                       X2(WIN2[0]), Y2(WIN2[3]), (WIN2[2] - WIN2[0]) * S2, (WIN2[3] - WIN2[1]) * S2))

    a = J["a"]
    r7 = [tuple(p) for p in a["vertices"]]
    tab_x = (48.70, 56.30, 65.00, 68.30)          # BASIS section 1 = r7_calc_out.json a.vertices[2..5]
    tab_y = (17.70, 67.14, 37.56, 76.00)          # BASIS section 1 = a.vertices[6..10]
    assert (r7[2], r7[3], r7[4]) == ((tab_x[0], tab_x[1]), (tab_x[2], tab_x[1]), (tab_x[2], tab_x[3]))
    assert (r7[7], r7[8]) == ((tab_y[2], tab_y[1]), (tab_y[2], tab_y[3]))
    r6 = [(17.70, 34.14), (48.70, 34.14), (48.70, 67.14), (18.70, 67.14), (17.70, 66.14)]   # DOC A.7 r3 rectangle, r6 chamfer
    sheet = [tuple(p) for p in J["m"]["r7_sheet"]]
    g = J["g"]
    taps = sorted(((v[0], v[1], v[2], k) for k, v in g["assignment"].items()), key=lambda t: t[0])
    ft = J["i"]
    keep = J["d"]["foot_keepouts"]
    band = [tuple(p) for p in J["h"]["boundary"]]
    # one extra boundary sample at the tab X right edge x 65.00, same rule as H.23(h) (largest y with d5v <= 6.4 mm)
    yb, y = None, tab_x[1]
    while y <= tab_x[3] + 1e-9:
        if R.d5v(tab_x[2], y) <= R.BAND:
            yb = y
        y += 0.02
    band_end = (tab_x[2], round(yb, 2))
    lfc_eaton = [t[1] for t in J["m"]["trims"] if t[0].startswith("L-FC")][0]
    Ld = J["l"]["dressing"]
    routes = J["l"]["routes"]
    pins_a = [(20.998, 36.544 + 2.54 * k) for k in range(12)]     # DOC A.8 pins 22..11 (x 20.998)
    pins_b = [(45.998, 39.084 + 2.54 * k) for k in range(10)]     # DOC A.8 pins 1..10 (x 45.998)
    pad_d = 1.9                                                   # DOC A.8 "pad >= 1.9 mm" (drawn at the minimum)
    w_holes = [("W1", 30.3, 61.2, 2.3, 1.3, PWR), ("W2", 27.7, 61.2, 2.3, 1.3, INK),          # DOC A.8 added CR pads
               ("W3", 24.3, 45.4, 2.5, 1.5, BAT), ("W4", 24.3, 55.6, 2.5, 1.5, INK)]
    w_smt = [("SCL", 27.0), ("GND", 29.0), ("SDA", 31.0), ("TS", 33.0), ("GND", 35.0)]       # DOC A.8 W7 / W6 at y 57.5
    W_SMT_Y, W_SMT = 57.5, (1.2, 1.5)     # DOC A.8 size 1.2 x 1.5 mm; orientation (1.2 in x) ASSUMPTION
    j101_reg = (37.0, 42.13, 44.5, 51.53)                         # DOC A.8 J101 region
    j101_body = (38.55, 42.13, 42.45, 51.53)                      # DOC A.8 J101 body courtyard
    comp = (23.15, 35.05, 42.43, 41.63)                           # BASIS D5 / r7_calc H.23(f): footprint low-y band

    # ------------------------------------------------------------- main panel
    s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#ffffff" stroke="%s" stroke-width="1"/>'
          % (X(WIN[0]), Y(WIN[3]), (WIN[2] - WIN[0]) * S, (WIN[3] - WIN[1]) * S, MUTE))
    s.raw('<g clip-path="url(#cMain)">')
    mb = R.MB_OUTLINE
    s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#f7f8f4" stroke="none"/>'
          % (X(mb[0]), Y(mb[3]), (mb[2] - mb[0]) * S, (mb[3] - mb[1]) * S))
    # MB layer-1 copper: VBUS pour near tab X and the 5V set of r7_calc.five_v_shapes(); rim = path + half the width
    vb = [sh for sh in R.SHAPES if sh["net"] == "VBUS" and sh["kind"] == "poly" and intersects(sh["bb"], (60, 50, 90, 80))]
    for sh in vb:
        s.raw('<polygon points="%s" fill="#ef9a9a" fill-opacity="0.35" stroke="#e53935" stroke-opacity="0.55" '
              'stroke-width="%.2f" stroke-linejoin="round"/>' % (pts_attr(sh["pts"]), 2 * sh["r"] * S))
    for sh in R.five_v_shapes():
        if sh["kind"] == "poly":
            s.raw('<polygon points="%s" fill="#ffcc80" fill-opacity="0.55" stroke="#fb8c00" stroke-opacity="0.8" '
                  'stroke-width="%.2f" stroke-linejoin="round"/>' % (pts_attr(sh["pts"]), 2 * sh["r"] * S))
        elif sh["kind"] == "wire":
            s.raw('<polyline points="%s" fill="none" stroke="#fb8c00" stroke-opacity="0.85" stroke-width="%.2f" '
                  'stroke-linecap="round"/>' % (pts_attr(sh["pts"]), 2 * sh["r"] * S))
        else:
            c = sh["pts"][0]
            s.raw('<circle cx="%.2f" cy="%.2f" r="%.2f" fill="#fb8c00" fill-opacity="0.85"/>' % (X(c[0]), Y(c[1]), sh["r"] * S))
    # MB part boxes within 25 mm of the r7 outline
    hi = {"REG-5V": "REG-5V (LM1084)", "L-FC": "L-FC", "OP-FC": "OP-FC", "ROP1-FC": "ROP1-FC", "ROP2-FC": "ROP2-FC",
          "J-FC": "J-FC", "J-NTC": "J-NTC", "J-BL": "J-BL", "CO-5V": "CO-5V", "MDAC-FC": "MDAC-FC", "U$1": "Teensy 4.1 (U$1)",
          "J1": "J1"}
    near, outside = [], []
    for n, e in R.ELS.items():
        if n == "CHG":
            continue
        if poly_dist(e["bbox"], r7) <= 25.0:
            if intersects(e["bbox"], WIN):
                near.append((n, e["bbox"]))
            else:
                outside.append(n)
    for n, b in near:
        px = rect_px(b)
        if n == "REG-5V":
            fill, st, sw = "#ffe0b2", "#e65100", 1.6
        elif n in hi:
            fill, st, sw = "#cfd8dc", "#263238", 1.3
        else:
            fill, st, sw = "#eceff1", "#90a4ae", 0.8
        op = ' fill-opacity="0.55"' if n in ("REG-5V", "U$1", "J1") else ""
        s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="%s"%s stroke="%s" stroke-width="%s"/>'
              % (px[0], px[1], px[2] - px[0], px[3] - px[1], fill, op, st, sw))
    le = rect_px(lfc_eaton)
    s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="none" stroke="#6d4c41" stroke-width="1.2" '
          'stroke-dasharray="5,3"/>' % (le[0], le[1], le[2] - le[0], le[3] - le[1]))
    usb = J["l"]["usb"]
    ub = rect_px(usb)
    s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="url(#hUsb)" stroke="#5e35b1" stroke-width="1.2" '
          'stroke-dasharray="4,2"/>' % (ub[0], ub[1], ub[2] - ub[0], ub[3] - ub[1]))
    s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="none" stroke="#37474f" stroke-width="2.6"/>'
          % (X(mb[0]), Y(mb[3]), (mb[2] - mb[0]) * S, (mb[3] - mb[1]) * S))
    # polyimide sheet (r7, H.23(m)), CR bottom side
    s.raw('<polygon points="%s" fill="none" stroke="#00897b" stroke-width="1.5" stroke-dasharray="1.5,2.5"/>' % pts_attr(sheet))
    # sheet openings (A.7 r7, H.23(m)): 2.2 mm relief holes at the 22 header pads (kept: the 3.4 mm holes merge into slots
    # and drop t_bed to 0.175 mm) and the five enlarged cut-outs (part body joined with its own pads + 0.5 mm; they merge)
    for (x, y) in pins_a + pins_b:
        s.raw('<circle cx="%.2f" cy="%.2f" r="%.2f" fill="none" stroke="#00897b" stroke-width="1.1" stroke-dasharray="1.5,1.5"/>'
              % (X(x), Y(y), 2.2 / 2 * S))
    for nm, co in J["m"]["cutouts_enlarged"].items():
        p = rect_px(co["rect"])
        s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#e0f2f1" fill-opacity="0.5" stroke="#00897b" stroke-width="1.1" '
              'stroke-dasharray="1.5,2.5"/>' % (p[0], p[1], p[2] - p[0], p[3] - p[1]))
    # polyimide strip (A.3 r7, H.23(l) l.dressing.polyimide_strip): on the MB under the leads, lead envelope + 2.0 mm, clipped to
    # its extent and to the MB side of the tab Y +x edge (x 37.56)
    strip = Ld["polyimide_strip"]
    sx0 = max(strip[0], tab_y[2])
    s.raw('<clipPath id="cStrip"><rect x="%.2f" y="%.2f" width="%.2f" height="%.2f"/></clipPath>'
          % (X(sx0), Y(strip[3]), (strip[2] - sx0) * S, (strip[3] - strip[1]) * S))
    s.raw('<g clip-path="url(#cStrip)" opacity="0.45">')
    for lead in ("W1", "W3", "W5"):
        cp = routes[lead]["cr_mb_path"]
        for (a_, ha), (b_, hb) in zip(cp[:-1], cp[1:]):
            s.raw('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="#80cbc4" stroke-width="%.2f" stroke-linecap="round"/>'
                  % (X(a_[0]), Y(a_[1]), X(b_[0]), Y(b_[1]), 2 * (max(ha, hb) + 2.0) * S))
    s.raw('</g>')
    # r7 outline (fill), r6 outline (dashed)
    s.raw('<polygon points="%s" fill="#e3f2fd" fill-opacity="0.45" stroke="none"/>' % pts_attr(r7))
    # thermal band (part of tab X within 6.4 mm of the MB 5V rim)
    bpoly = [(tab_x[0], tab_x[1])] + band + [band_end, (tab_x[2], tab_x[1])]
    s.raw('<polygon points="%s" fill="#ff8a65" fill-opacity="0.28" stroke="none"/>' % pts_attr(bpoly))
    s.raw('<polyline points="%s" fill="none" stroke="#d84315" stroke-width="1.6" stroke-dasharray="7,2,2,2"/>'
          % pts_attr(band + [band_end]))
    # comparator block region (top), J101 region
    cb = rect_px(comp)
    s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="url(#hComp)" fill-opacity="0.9" stroke="#1565c0" '
          'stroke-width="1.2" stroke-dasharray="6,3"/>' % (cb[0], cb[1], cb[2] - cb[0], cb[3] - cb[1]))
    jr, jb = rect_px(j101_reg), rect_px(j101_body)
    s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#f3e5f5" fill-opacity="0.7" stroke="#6a1b9a" '
          'stroke-width="1.2" stroke-dasharray="6,3"/>' % (jr[0], jr[1], jr[2] - jr[0], jr[3] - jr[1]))
    s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="none" stroke="#6a1b9a" stroke-width="1"/>'
          % (jb[0], jb[1], jb[2] - jb[0], jb[3] - jb[1]))
    # feet (CR bottom): keep-outs dashed, bodies hatched
    for name, k1, k2 in keep:
        for kb in (k1, k2):
            if kb:
                p = rect_px(kb)
                s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="none" stroke="#2e7d32" stroke-width="1" '
                      'stroke-dasharray="3,2"/>' % (p[0], p[1], p[2] - p[0], p[3] - p[1]))
    for f in ("ft1", "ft2"):
        p = rect_px(ft[f]["body"])
        s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="url(#hFoot)" stroke="#1b5e20" stroke-width="1.4"/>'
              % (p[0], p[1], p[2] - p[0], p[3] - p[1]))
    # FT2 fill hole (BASIS B2, H.23(i) i.ft2_fill_hole): NPTH at the foot centre, CR-top keep-out disc dashed
    fh = ft["ft2_fill_hole"]
    s.raw('<circle cx="%.2f" cy="%.2f" r="%.2f" fill="none" stroke="#1b5e20" stroke-width="1" stroke-dasharray="3,2"/>'
          % (X(fh["centre"][0]), Y(fh["centre"][1]), fh["ko_disc"] / 2 * S))
    s.raw('<circle cx="%.2f" cy="%.2f" r="%.2f" fill="#ffffff" stroke="#1b5e20" stroke-width="1.4"/>'
          % (X(fh["centre"][0]), Y(fh["centre"][1]), fh["d"] / 2 * S))
    # outlines on top of the fills
    s.raw('<polygon points="%s" fill="none" stroke="#546e7a" stroke-width="1.6" stroke-dasharray="7,4"/>' % pts_attr(r6))
    s.raw('<polygon points="%s" fill="none" stroke="#0d47a1" stroke-width="2.6" stroke-linejoin="miter"/>' % pts_attr(r7))
    # tap field courtyard, R175 box, tap pads
    tc = rect_px(g["courtyard"])
    s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="none" stroke="%s" stroke-width="0.8" stroke-dasharray="2,2"/>'
          % (tc[0], tc[1], tc[2] - tc[0], tc[3] - tc[1], TAP))
    rb = rect_px(g["r175_box"])
    s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#fffde7" stroke="#8d6e63" stroke-width="1"/>'
          % (rb[0], rb[1], rb[2] - rb[0], rb[3] - rb[1]))
    # R175 pads on the grid (H.23(g) g.r175a; R175b one row below in the same column, R175 rows 2-3): a = Teensy 3V3 (F07) side
    r175a = tuple(g["r175a"])
    r175b = (r175a[0], g["ys"][g["ys"].index(r175a[1]) - 1])
    for (x, y), t in ((r175a, "a"), (r175b, "b")):
        p = rect_px((x - 0.75, y - 0.75, x + 0.75, y + 0.75))
        s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#a1887f" stroke="#5d4037" stroke-width="0.8"/>'
              % (p[0], p[1], p[2] - p[0], p[3] - p[1]))
        s.text(X(x), Y(y) + 2.2, t, 6.5, anchor="middle", color="#ffffff", weight="bold")
    for fid, x, y, tname in taps:
        p = rect_px((x - 0.75, y - 0.75, x + 0.75, y + 0.75))       # DOC A.4: 1.5 x 1.5 mm SMT pads
        s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="%s" stroke="#1b5e20" stroke-width="0.8"/>'
              % (p[0], p[1], p[2] - p[0], p[3] - p[1], TAP))
        s.text(X(x), Y(y) + 2.2, fid[1:], 6.5, anchor="middle", color="#ffffff", weight="bold")
    # spare tab X grid positions (H.23(g) "spare": freed when T18 moved to the residual pad F22)
    for (x, y) in g["spare"]:
        p = rect_px((x - 0.75, y - 0.75, x + 0.75, y + 0.75))
        s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#ffffff" stroke="#1b5e20" stroke-width="0.8" '
              'stroke-dasharray="2,1.5"/>' % (p[0], p[1], p[2] - p[0], p[3] - p[1]))
        s.text(X(x), Y(y) + 2.2, "sp", 6.5, anchor="middle", color="#1b5e20")
    # CHG header pads (A.8)
    for (x, y) in pins_a + pins_b:
        s.raw('<circle cx="%.2f" cy="%.2f" r="%.2f" fill="#fff8e1" stroke="#b8860b" stroke-width="1.3"/>'
              % (X(x), Y(y), pad_d / 2 * S))
        s.raw('<circle cx="%.2f" cy="%.2f" r="%.2f" fill="#5d4037"/>' % (X(x), Y(y), 1.1 / 2 * S))
    # W1-W4 holes, W6/W7 pads (A.8)
    for nm, x, y, pd, hd, col in w_holes:
        s.raw('<circle cx="%.2f" cy="%.2f" r="%.2f" fill="#ffffff" stroke="%s" stroke-width="2"/>' % (X(x), Y(y), pd / 2 * S, col))
        s.raw('<circle cx="%.2f" cy="%.2f" r="%.2f" fill="%s"/>' % (X(x), Y(y), hd / 2 * S, col))
    for nm, x in w_smt:
        p = rect_px((x - W_SMT[0] / 2, W_SMT_Y - W_SMT[1] / 2, x + W_SMT[0] / 2, W_SMT_Y + W_SMT[1] / 2))
        s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#bbdefb" stroke="%s" stroke-width="1.1"/>'
              % (p[0], p[1], p[2] - p[0], p[3] - p[1], SIG))
    # MB tie bases A1/A2 (A.3 r7, H.23(l) l.dressing.anchors.tie_bases): base solid, base + tolerance zone dashed
    tbs = Ld["anchors"]["tie_bases"]
    for nm, tb in tbs.items():
        z = rect_px(tb["zone"])
        s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="none" stroke="#5d4037" stroke-width="1.1" stroke-dasharray="4,2"/>'
              % (z[0], z[1], z[2] - z[0], z[3] - z[1]))
        c, h = tb["centre"], tb["side"] / 2
        b_ = rect_px((c[0] - h, c[1] - h, c[0] + h, c[1] + h))
        s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#d7ccc8" fill-opacity="0.85" stroke="#5d4037" stroke-width="1.4"/>'
              % (b_[0], b_[1], b_[2] - b_[0], b_[3] - b_[1]))
    # W-lead jacket envelopes (H.23(l) cr_mb_path half-widths; one group so overlaps do not darken), W5 ribbon band
    s.raw('<g opacity="0.22">')
    for lead in ("W1", "W3", "W4", "W6", "W7 SCL", "W7 SDA"):
        cp = routes[lead]["cr_mb_path"]
        for (a_, ha), (b_, hb) in zip(cp[:-1], cp[1:]):
            s.raw('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="#546e7a" stroke-width="%.2f" stroke-linecap="round"/>'
                  % (X(a_[0]), Y(a_[1]), X(b_[0]), Y(b_[1]), 2 * max(ha, hb) * S))
    s.raw('</g>')
    cp5 = routes["W5"]["cr_mb_path"]
    s.raw('<polyline points="%s" fill="none" stroke="#0b8f8f" stroke-opacity="0.16" stroke-width="%.2f" stroke-linejoin="miter"/>'
          % (pts_attr([q[0] for q in cp5]), 2 * cp5[0][1] * S))
    # CR beads B1/B3 (RTV spacer posts) and W5 spacer beads S1-S3, 3.0 x 3.0 mm footprints (ASSUMPTION, H.23(l))
    for nm, (x, y) in Ld["anchors"]["cr"].items():
        fill, st = ("#e1bee7", "#6a1b9a") if nm.startswith("B") else ("#b2ebf2", "#00838f")
        p = rect_px((x - 1.5, y - 1.5, x + 1.5, y + 1.5))
        s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="%s" fill-opacity="0.85" stroke="%s" stroke-width="1.3"/>'
              % (p[0], p[1], p[2] - p[0], p[3] - p[1], fill, st))
    # 3-D switched-conductor spans (H.23(l) l.rev4.sw3d): the run held above the MB on spacers, dashed purple under the centre line
    for lead in ("W1", "W5"):
        for seg in J["l"]["rev4"]["sw3d"][lead]:
            for base, pr in seg["per"].items():
                sp = subpath([q[0] for q in routes[lead]["cr_mb_path"]], pr["p0"], pr["p1"])
                s.raw('<polyline points="%s" fill="none" stroke="#8e24aa" stroke-width="6" stroke-opacity="0.75" '
                      'stroke-dasharray="4,3" stroke-linejoin="round"/>' % pts_attr(sp))
    # centre lines (one colour per lead; the shared trunk shows the last drawn)
    lstyle = {"W1": (PWR, 1.6, None), "W2": (INK, 1.2, None), "W3": (BAT, 1.6, None), "W4": (INK, 1.2, None),
              "W6": (SIG, 1.0, "4,2"), "W7 SCL": (SIG, 1.0, None), "W7 SDA": (SIG, 1.0, None), "W5": ("#0b8f8f", 1.6, "6,2")}
    for lead in ("W5", "W6", "W7 SCL", "W7 SDA", "W4", "W2", "W3", "W1"):
        col, sw, da = lstyle[lead]
        d = ' stroke-dasharray="%s"' % da if da else ""
        s.raw('<polyline points="%s" fill="none" stroke="%s" stroke-width="%s" stroke-linejoin="round"%s/>'
              % (pts_attr([q[0] for q in routes[lead]["cr_mb_path"]]), col, sw, d))
    s.raw('</g>')

    # ------------------------------------------------------------- main panel labels (manual, registered first)
    def lab(x, y, t, size=9, anchor="start", color=INK, bold=False):
        s.text(X(x), Y(y), t, size, anchor=anchor, color=color, weight="bold" if bold else "normal")

    def leader(p, q, color="#78909c"):
        s.raw('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="%s" stroke-width="0.8"/>'
              % (X(p[0]), Y(p[1]), X(q[0]), Y(q[1]), color))

    lab(53.4, 69.7, "tab X", 12, color="#0d47a1", bold=True)
    lab(18.3, 69.5, "tab Y", 12, color="#0d47a1", bold=True)        # clear of the trunk (x 23.4-28.2)
    lab(37.6, 66.0, "r6 footprint", 9, color="#546e7a", bold=True)
    lab(18.9, 77.05, "chamfer r7", 7.5, color="#0d47a1")      # above tab Y, clear of the FT2 labels
    leader((18.8, 76.8), (18.15, 75.65), "#0d47a1")
    lab(18.25, 68.0, "r6 chamfer", 7.5, color="#546e7a")
    # header pads: pin 1 and pin 11
    lab(44.5, 38.75, "1", 10, anchor="end", color="#8d6e00", bold=True)
    lab(22.25, 64.15, "11", 10, color="#8d6e00", bold=True)
    for nm, x, y, pd, hd, col in w_holes:
        if nm in ("W1", "W2"):
            lab(x, y + 1.55, nm, 8, anchor="middle", color=col, bold=True)
        else:
            lab(x + 1.5, y - 0.35, nm, 8, color=col, bold=True)
    lab(29.0, 56.0, "W7", 8, anchor="middle", color=SIG, bold=True)
    lab(34.0, 56.0, "W6", 8, anchor="middle", color=SIG, bold=True)
    lab(40.75, 47.6, "J101", 9, anchor="middle", color="#6a1b9a", bold=True)
    lab(40.75, 46.3, "region", 7.5, anchor="middle", color="#6a1b9a")
    lab(32.8, 40.45, "comparator block (top)", 8, anchor="middle", color="#0d47a1", bold=True)
    lab(32.8, 39.2, "U102-U104, U115, U119-U121,", 7.5, anchor="middle", color="#0d47a1")
    lab(32.8, 38.0, "0.1 % dividers, filter caps", 7.5, anchor="middle", color="#0d47a1")
    lab(51.9, 56.85, "thermal band (6.4 mm)", 7.5, color="#bf360c", bold=True)
    lab(50.8, 62.45, "R175", 6.5, anchor="middle", color="#5d4037")
    # adopted feet (H.23(i)): label "FTn <w> x <h> mm, +-tx/ty" in two lines
    f1, f2 = ft["ft1"], ft["ft2"]
    lab(66.3, 67.35, "FT1 %.1f x %.1f mm" % tuple(f1["size"]), 8.5, color="#1b5e20", bold=True)
    lab(66.3, 66.15, "±%.3f/%.3f mm" % (f1["tx"], f1["ty"]), 7.5, color="#1b5e20")
    leader((66.2, 67.0), (63.72, 66.9), "#1b5e20")
    fc2 = f2["centre"]
    lab(25.35, 74.2, "FT2 %.1f x %.1f" % tuple(f2["size"]), 7.5, anchor="end", color="#1b5e20", bold=True)   # W5 runs right of FT2
    lab(25.35, 73.0, "±%.3f/%.3f" % (f2["tx"], f2["ty"]), 7.5, anchor="end", color="#1b5e20")
    lab(25.35, 71.8, "%.1f mm fill hole" % fh["d"], 7.5, anchor="end", color="#1b5e20")
    lab(70.0, 50.0, "VBUS L1", 8, color="#c62828", bold=True)
    lab(70.0, 48.8, "pour (rim)", 8, color="#c62828")
    lab(56.6, 47.0, "5V L1 copper", 8, anchor="middle", color="#e65100", bold=True)
    lab(56.6, 45.9, "(rim, under REG-5V)", 7.5, anchor="middle", color="#e65100")
    lab(97.28, 96.6, "USB", 8, anchor="middle", color="#4527a0", bold=True)
    lab(97.28, 95.4, "end (+y)", 7.5, anchor="middle", color="#4527a0")
    lab(60.0, 98.5, "MB +y edge (y 98.044)", 8, color="#37474f", bold=True)
    lab(0.6, 91.5, "MB edge x 0", 8, color="#37474f", bold=True)
    lab(26.0, 87.0, "L-FC Eaton body", 7.5, color="#6d4c41")
    lab(26.0, 86.0, "12.9 mm (dashed)", 7.5, color="#6d4c41")
    # FC droop-network parts beside tab Y (BASIS D1 trim): fixed label positions in the free MB area, with leaders
    b1, b2 = R.ELS["ROP1-FC"]["bbox"], R.ELS["ROP2-FC"]["bbox"]
    lab(45.4, 74.25, "ROP1-FC", 8.5, color="#263238", bold=True)
    s.line([(X(b1[2]), Y(75.55)), (X(45.2), Y(75.55)), (X(45.4), Y(75.2))], "#78909c", 0.8)
    lab((b2[0] + b2[2]) / 2, b2[3] + 0.33, "ROP2-FC", 8.5, anchor="middle", color="#263238", bold=True)
    manual = {"ROP1-FC", "ROP2-FC"}
    # dressing path, beads, spacers, tie bases (A.3 r7 review 7; H.23(l))
    for nm, tb in tbs.items():
        c = tb["centre"]
        lab(c[0] + tb["side"] / 2 - 0.3, c[1] - tb["side"] / 2 + 0.4, nm, 9, anchor="end", color="#3e2723", bold=True)   # inside the base
    lab(23.9, 66.6, "B1", 7.5, anchor="end", color="#6a1b9a", bold=True)
    lab(35.0, 74.95, "B3/S3", 7.5, anchor="middle", color="#6a1b9a", bold=True)
    lab(35.0, 45.2, "S1", 7.5, anchor="middle", color="#00838f", bold=True)
    lab(30.4, 53.1, "S2", 7.5, color="#00838f", bold=True)

    # ------------------------------------------------------------- MB part names (automatic placement)
    pan = (X(WIN[0]) + 1, Y(WIN[3]) + 1, X(WIN[2]) - 1, Y(WIN[1]) - 1)
    cr_obst = [rect_px(b) for b in ((16.7, 33.14, 49.7, 68.14), (47.7, 55.3, 66.0, 69.3), (16.7, 66.14, 38.56, 77.0))]
    part_px = {n: rect_px(b) for n, b in near}
    unl = []
    order = sorted(near, key=lambda t: (t[0] not in hi, -(t[1][2] - t[1][0]) * (t[1][3] - t[1][1])))
    for n, b in order:
        if n == "REG-5V" or n in manual:
            continue                                   # labelled inside (REG-5V, below) or at a fixed position (above)
        t = hi.get(n, n)
        size, bold = (8.5, True) if n in hi else (6.5, False)
        bp = part_px[n]
        w_ = text_w(t, size, bold)
        h_ = size * 1.0
        under_cr = poly_dist(b, r7) == 0.0             # part lies (partly) under the r7 outline
        obst = [part_px[m] for m in part_px if m != n] + ([] if under_cr else cr_obst)
        cx, cy = (bp[0] + bp[2]) / 2, (bp[1] + bp[3]) / 2
        cands = []
        if w_ <= bp[2] - bp[0] - 2 and h_ <= bp[3] - bp[1] - 2:
            cands.append((cx, cy, False, True))
        hw, hh = (bp[2] - bp[0]) / 2, (bp[3] - bp[1]) / 2
        for dx, dy in ((0, -(hh + h_ / 2 + 1.5)), (0, hh + h_ / 2 + 1.5), (hw + w_ / 2 + 2, 0), (-(hw + w_ / 2 + 2), 0)):
            cands.append((cx + dx, cy + dy, False, False))
        for rr in (8, 14, 22, 32, 44, 58):
            for ang in range(0, 360, 20):
                dx = (hw + w_ / 2 + rr) * math.cos(math.radians(ang))
                dy = (hh + h_ / 2 + rr) * math.sin(math.radians(ang))
                cands.append((cx + dx, cy + dy, True, False))
        placed = None
        for strict in (True, False):
            for (lx, ly, lead, inside) in cands:
                tb = (lx - w_ / 2, ly - h_ / 2, lx + w_ / 2, ly + h_ / 2)
                if tb[0] < pan[0] or tb[2] > pan[2] or tb[1] < pan[1] or tb[3] > pan[3]:
                    continue
                if any(boxes_overlap(tb, q[:4], 0.0) for q in s.tb):
                    continue
                if strict and any(boxes_overlap(tb, o, 0.0) for o in obst if not inside):
                    continue
                if not strict and any(boxes_overlap(tb, o, 0.0) for o in cr_obst) and not under_cr:
                    continue
                placed = (lx, ly, lead, tb)
                break
            if placed:
                break
        if not placed:
            unl.append(n)
            continue
        lx, ly, lead, tb = placed
        if lead:
            qx = min(max(lx, bp[0]), bp[2])
            qy = min(max(ly, bp[1]), bp[3])
            ex_ = min(max(qx, tb[0]), tb[2])
            ey_ = min(max(qy, tb[1]), tb[3])
            s.raw('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="#90a4ae" stroke-width="0.7"/>' % (qx, qy, ex_, ey_))
        s.text(lx, ly + 0.36 * size, t, size, anchor="middle", color="#263238" if n in hi else "#455a64",
               weight="bold" if bold else "normal")
    reg = rect_px(R.ELS["REG-5V"]["bbox"])
    s.text((reg[0] + reg[2]) / 2, Y(51.0), hi["REG-5V"], 8.5, anchor="middle", color="#bf360c", weight="bold")

    # scale bar and orientation
    sbx, sby = X(WIN[2]) - 10 * S - 44, Y(WIN[1]) + 16  # below the main panel, right end
    s.raw('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="%s" stroke-width="2"/>' % (sbx, sby, sbx + 10 * S, sby, INK))
    for k in (0, 5, 10):
        s.raw('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="%s" stroke-width="1.2"/>'
              % (sbx + k * S, sby - 4, sbx + k * S, sby, INK))
    s.text(sbx + 10 * S + 6, sby + 3, "10 mm", 8)

    # ------------------------------------------------------------- second panel: EVM reference placement (H.23(l))
    L = J["l"]
    s.text(QX0, 86, "EVM reference placement past the MB +y edge", 10.5, weight="bold")
    s.text(QX0, 99, "(BASIS D7, H.23(l)), same board coordinates, 2.4 px/mm", 9, color=MUTE)
    s.text(QX0, 112, "Adopted once MS2 confirms the chassis room; plate and clamps", 8.5, color=MUTE)
    s.text(QX0, 123.5, "TODO(design: from MS2 and MS7).", 8.5, color=MUTE)
    s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#ffffff" stroke="%s" stroke-width="1"/>'
          % (X2(WIN2[0]), Y2(WIN2[3]), (WIN2[2] - WIN2[0]) * S2, (WIN2[3] - WIN2[1]) * S2, MUTE))
    s.raw('<g clip-path="url(#cEvm)">')
    s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#f7f8f4" stroke="#37474f" stroke-width="1.8"/>'
          % (X2(mb[0]), Y2(mb[3]), (mb[2] - mb[0]) * S2, (mb[3] - mb[1]) * S2))
    u1 = rect_px(R.ELS["U$1"]["bbox"], X2, Y2)
    s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#cfd8dc" stroke="#263238" stroke-width="1"/>'
          % (u1[0], u1[1], u1[2] - u1[0], u1[3] - u1[1]))
    ub2 = rect_px(usb, X2, Y2)
    s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="url(#hUsb)" stroke="#5e35b1" stroke-width="1" '
          'stroke-dasharray="4,2"/>' % (ub2[0], ub2[1], ub2[2] - ub2[0], ub2[3] - ub2[1]))
    ev = rect_px(L["evm"], X2, Y2)
    s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#fff7e6" stroke="%s" stroke-width="1.6"/>'
          % (ev[0], ev[1], ev[2] - ev[0], ev[3] - ev[1], INK))
    eb = rect_px(L["eib"], X2, Y2)
    s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#f0fff4" stroke="%s" stroke-width="1.4"/>'
          % (eb[0], eb[1], eb[2] - eb[0], eb[3] - eb[1], INK))
    # fallback (i) (H.23(l) l.fallbacks.i): EVM + EIB group shifted -x, dashed outline (clipped at the panel edge)
    fb1 = L["fallbacks"]["i"]
    for bx in (fb1["evm"], fb1["eib"]):
        q = rect_px(bx, X2, Y2)
        s.raw('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="none" stroke="#e65100" stroke-width="1.2" '
              'stroke-dasharray="5,3"/>' % (q[0], q[1], q[2] - q[0], q[3] - q[1]))
    s.raw('<polygon points="%s" fill="#bbdefb" stroke="#0d47a1" stroke-width="1.4"/>' % pts_attr(r7, X2, Y2))
    style = {"W1": (PWR, 1.8, None), "W2": (INK, 1.2, None), "W3": (BAT, 1.8, None), "W4": (INK, 1.2, None),
             "W6": (SIG, 1.0, "4,2"), "W7 SCL": (SIG, 1.0, None), "W7 SDA": (SIG, 1.0, None), "W5": ("#0b8f8f", 1.6, "6,2")}
    for lead in ("W5", "W6", "W7 SCL", "W7 SDA", "W3", "W4", "W1", "W2"):
        col, sw, da = style[lead]
        d = ' stroke-dasharray="%s"' % da if da else ""
        s.raw('<polyline points="%s" fill="none" stroke="%s" stroke-width="%s" stroke-linejoin="round"%s/>'
              % (pts_attr(paths[lead], X2, Y2), col, sw, d))
        e = paths[lead][-1]
        s.raw('<circle cx="%.2f" cy="%.2f" r="2.2" fill="%s"/>' % (X2(e[0]), Y2(e[1]), col))
    j201 = L["j201"]
    s.raw('<rect x="%.2f" y="%.2f" width="6" height="6" fill="#0b8f8f"/>' % (X2(j201[0]) - 3, Y2(j201[1]) - 3))
    s.raw('</g>')
    # P2 crossings of the MB +y edge (the chassis tie closes the last span past it, A.3 anchor rule)
    for p2 in sorted({tuple(v["P2"]) for v in L["routes"].values()}):
        s.raw('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="#37474f" stroke-width="1.6"/>'
              % (X2(p2[0]), Y2(p2[1]) - 4, X2(p2[0]), Y2(p2[1]) + 4))

    def lab2(x, y, t, size=8, anchor="start", color=INK, bold=False):
        s.text(X2(x), Y2(y), t, size, anchor=anchor, color=color, weight="bold" if bold else "normal")

    lab2(30.0, 201.0, "EVM 88.90 x 88.90 mm", 9, anchor="middle", bold=True)
    lab2(30.0, 196.0, "x %.2f-%.2f, y %.3f-%.3f" % (L["evm"][0], L["evm"][2], L["evm"][1], L["evm"][3]), 7.5,
         anchor="middle", color=MUTE)
    lab2(105.5, 190.0, "EIB", 9, anchor="middle", bold=True)
    lab2(105.5, 185.5, "J201", 7.5, anchor="start", color="#0b8f8f")
    lab2(3.0, 26.0, "MB 131.064 x 98.044 mm", 8.5, bold=True, color="#37474f")
    xs_p2 = {lead: v["P2"][0] for lead, v in L["routes"].items()}
    ct = L["rev4"]["chassis_tie"]
    lab2(3.0, 19.5, "Ticks on the MB +y edge: x %.2f (W1, W2, W6, W7), %.2f (W5), %.2f (W3, W4)."
         % (xs_p2["W1"], xs_p2["W5"], xs_p2["W3"]), 7.5, color="#37474f")
    lab2(3.0, 14.5, "Chassis tie past that edge <= %.1f / %.1f / %.1f mm (A.3 anchor rule)."
         % (ct["west group (W1, W2, W6, W7)"]["tie_max"], ct["W5"]["tie_max"], ct["W3/W4"]["tie_max"]), 7.5, color="#37474f")
    lab2(91.0, 62.0, "Teensy", 7.5, color="#263238")
    lab2(102.5, 128.0, "USB", 7.5, color="#4527a0", bold=True)
    lab2(102.5, 124.0, "corridor", 7.5, color="#4527a0")
    lab2(102.5, 120.0, "45 mm", 7.5, color="#4527a0")
    lab2(102.5, 116.0, "ASSUMPTION", 7.5, color="#4527a0")
    lab2(24.0, 54.0, "CR r7", 8, color="#0d47a1", bold=True)
    term = {"J1": paths["W1"][-1], "J5": paths["W3"][-1], "J7": paths["W6"][-1], "J8": paths["W7 SDA"][-1]}
    lab2(term["J1"][0] + 3.0, term["J1"][1] + 0.8, "J1 (W1, W2)", 7.5, color=PWR, bold=True)
    lab2(term["J5"][0] - 2.5, term["J5"][1] + 3.0, "J5 (W3, W4)", 7.5, anchor="end", color=BAT, bold=True)
    lab2(term["J7"][0] + 3.0, term["J7"][1] - 1.2, "J7 (W6)", 7.5, color=SIG, bold=True)
    lab2(term["J8"][0] + 2.0, term["J8"][1] + 1.5, "J8 (W7)", 7.5, color=SIG, bold=True)
    lab2((fb1["eib"][0] + fb1["eib"][2]) / 2, fb1["eib"][3] - 6.0, "fallback (i)", 7.5, anchor="middle", color="#e65100", bold=True)
    lab2((fb1["eib"][0] + fb1["eib"][2]) / 2, fb1["eib"][3] - 10.5, "EIB position", 7.5, anchor="middle", color="#e65100")
    # fallback verdicts (H.23(l)): text note under the second panel
    fb2, fb3 = L["fallbacks"]["ii"], L["fallbacks"]["iii"]
    fy0 = Y2(WIN2[1]) + 13
    fnotes = [("Fallbacks if MS2 rejects this placement (H.23(l)):", True, INK),
              ("(i) EVM + EIB shifted -x %.2f mm (orange dashed, clipped): %s;"
               % (fb1["shift"], "PASSES" if fb1["passes"] else "FAILS"), False, "#e65100"),
              ("     needs %.1f mm of chassis room past the MB -x edge (W1 at x %.2f" % (fb1["chassis_room"], fb1["xmin"][2][0]),
               False, "#e65100"),
              ("     + %.1f mm bend; EVM overhang %.1f mm), clear of J-BL/J-FC/J-NTC (MS2)."
               % (fb1["bend_allowance"], fb1["overhang"]), False, "#e65100"),
              ("(ii) EIB past the USB corridor: %s (W3/W4/W5 blocked; E maxima > D7)."
               % ("PASSES" if fb2["passes"] else "FAILS"), False, INK),
              ("(iii) EIB at the EVM left edge: %s (E4 %.1f mm > 59 mm limit)."
               % ("PASSES" if fb3["passes"] else "FAILS", fb3["e_leads"]["E4"][0]), False, INK)]
    for k, (t, b, col) in enumerate(fnotes):
        s.text(QX0, fy0 + k * 10.5, t, 7.5, color=col, weight="bold" if b else "normal")

    # ------------------------------------------------------------- legend (under the main panel)
    ly0 = Y(WIN[1]) + 18
    s.text(PX0, ly0, "Legend", 11, weight="bold")
    items = [
        ("rect", dict(fill="none", stroke="#0d47a1", sw=2.6), "r7 outline (solid): r6 rectangle + tab X + tab Y"),
        ("rect", dict(fill="none", stroke="#546e7a", sw=1.6, dash="7,4"), "r6 outline (dashed), 31.0 x 33.0 mm"),
        ("rect", dict(fill="none", stroke="#00897b", sw=1.5, dash="1.5,2.5"), "r7 polyimide sheet (dotted), on the MB"),
        ("circle", dict(fill="#fff8e1", stroke="#b8860b"), "CHG header pad, 1.9 mm (A.8)"),
        ("sq", dict(fill=TAP, stroke="#1b5e20"), "tap pad 1.5 x 1.5 mm, top (F-number)"),
        ("rect", dict(fill="url(#hFoot)", stroke="#1b5e20", sw=1.4), "foot body (CR bottom); keep-out, FT1 lane dashed"),
        ("hole", dict(fill="#ffffff", stroke="#1b5e20"), "FT2 1.0 mm fill hole (NPTH); 2.0 mm keep-out"),
        ("rect", dict(fill="#ff8a65", stroke="#d84315", sw=1.2, op=0.35), "thermal band (6.4 mm from the 5V rim)"),
        ("rect", dict(fill="url(#hComp)", stroke="#1565c0", sw=1.2, dash="6,3"), "comparator block region (top)"),
        ("rect", dict(fill="#f3e5f5", stroke="#6a1b9a", sw=1.2, dash="6,3"), "J101 region; solid: body courtyard"),
        ("circle", dict(fill="#ffffff", stroke=PWR, sw=2), "W1-W4 plated hole and pad"),
        ("sq", dict(fill="#bbdefb", stroke=SIG), "W6/W7 SMT pad 1.2 x 1.5 mm"),
        ("rect", dict(fill="#eceff1", stroke="#90a4ae", sw=0.8), "MB part box within 25 mm (.brd)"),
        ("rect", dict(fill="#cfd8dc", stroke="#263238", sw=1.3), "MB part near the tabs (bold label)"),
        ("rect", dict(fill="none", stroke="#6d4c41", sw=1.2, dash="5,3"), "L-FC Eaton 12.9 mm body"),
        ("rect", dict(fill="#ffcc80", stroke="#fb8c00", sw=1.2), "MB 5V L1 copper (rim)"),
        ("rect", dict(fill="#ef9a9a", stroke="#e53935", sw=1.2), "MB VBUS L1 pour (rim)"),
        ("rect", dict(fill="url(#hUsb)", stroke="#5e35b1", sw=1.2, dash="4,2"), "Teensy USB plug corridor"),
        ("rect", dict(fill="none", stroke="#37474f", sw=2.6), "MB outline"),
        ("sq", dict(fill="#ffffff", stroke="#1b5e20", dash="2,1.5"), "spare tab X grid position (sp)"),
        ("rect", dict(fill="none", stroke="#e65100", sw=1.2, dash="5,3"), "fallback (i) EVM + EIB position"),
        ("sq", dict(fill="#a1887f", stroke="#5d4037"), "R175 pad: a Teensy 3V3 (F07) side, b rail side"),
        ("circle", dict(fill="none", stroke="#00897b", sw=1.1, dash="1.5,1.5"), "sheet relief hole 2.2 mm (kept, A.7)"),
        ("rect", dict(fill="#e0f2f1", stroke="#00897b", sw=1.1, dash="1.5,2.5"), "sheet cut-out, enlarged (body + pads + 0.5 mm)"),
        ("band", dict(stroke="#546e7a", sw=1.6, op=0.22, line=PWR), "W-lead path: centre line, band = jacket envelope"),
        ("band", dict(stroke="#0b8f8f", sw=1.6, op=0.16, line="#0b8f8f", dash="6,2"), "W5 ribbon: centre line, 8.89 mm band"),
        ("line", dict(stroke="#8e24aa", sw=6, op=0.75, dash="4,3"), "3-D rule: span held above the MB on spacers"),
        ("sq", dict(fill="#e1bee7", stroke="#6a1b9a"), "RTV bead / spacer post B1, B3 (3 x 3 mm)"),
        ("sq", dict(fill="#b2ebf2", stroke="#00838f"), "W5 spacer bead S1-S3 (3 x 3 mm)"),
        ("rect", dict(fill="#d7ccc8", stroke="#5d4037", sw=1.4), "MB tie base A1/A2; dashed: +-1.5 mm zone"),
        ("rect", dict(fill="#80cbc4", stroke="#80cbc4", sw=1, op=0.45), "polyimide strip on the MB (envelope + 2 mm)"),
    ]
    cols, colw, rowh = 3, 290, 17
    for i, (kind, st, t) in enumerate(items):
        c, r = i % cols, i // cols
        x0, y0 = PX0 + c * colw, ly0 + 12 + r * rowh
        dash = ' stroke-dasharray="%s"' % st["dash"] if st.get("dash") else ""
        op = ' fill-opacity="%s"' % st["op"] if st.get("op") else ""
        if kind == "rect":
            s.raw('<rect x="%.1f" y="%.1f" width="30" height="11" fill="%s"%s stroke="%s" stroke-width="%s"%s/>'
                  % (x0, y0, st["fill"], op, st["stroke"], st.get("sw", 1), dash))
        elif kind == "circle":
            s.raw('<circle cx="%.1f" cy="%.1f" r="5.5" fill="%s" stroke="%s" stroke-width="%s"%s/>'
                  % (x0 + 15, y0 + 5.5, st["fill"], st["stroke"], st.get("sw", 1.3), dash))
        elif kind == "band":
            s.raw('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-opacity="%s" stroke-width="11"/>'
                  '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%s"%s/>'
                  % (x0, y0 + 5.5, x0 + 30, y0 + 5.5, st["stroke"], st["op"], x0, y0 + 5.5, x0 + 30, y0 + 5.5, st["line"],
                     st["sw"], dash))
        elif kind == "line":
            s.raw('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-opacity="%s" stroke-width="%s"%s/>'
                  % (x0, y0 + 5.5, x0 + 30, y0 + 5.5, st["stroke"], st["op"], st["sw"], dash))
        elif kind == "hole":
            s.raw('<circle cx="%.1f" cy="%.1f" r="8" fill="none" stroke="%s" stroke-width="1" stroke-dasharray="3,2"/>'
                  '<circle cx="%.1f" cy="%.1f" r="4" fill="%s" stroke="%s" stroke-width="1.4"/>'
                  % (x0 + 15, y0 + 5.5, st["stroke"], x0 + 15, y0 + 5.5, st["fill"], st["stroke"]))
        else:
            s.raw('<rect x="%.1f" y="%.1f" width="11" height="11" fill="%s" stroke="%s" stroke-width="1"%s/>'
                  % (x0 + 9.5, y0, st["fill"], st["stroke"], dash))
        s.text(x0 + 38, y0 + 9.5, t, 9)

    # ------------------------------------------------------------- notes
    i1 = J["i"]
    routes = L["routes"]
    notes = [
        "r7 outline: r6 rectangle x 17.70-48.70, y 34.14-67.14 + tab X x 48.70-65.00, y 56.30-68.30 + tab Y x 17.70-37.56, y 67.14-76.00; "
        "%.2f mm2 (H.23(a)); the 1.0 mm x 45 deg pin-11 chamfer moved to (17.70, 76.00)." % a["area_total"],
        "Tap field (calc revision 4, D-F4 adjacency exclusions): %d pads + R175 on tab X in a 6 x 4 grid at 2.54 mm (x %.2f-%.2f, y %.2f-%.2f; H.23(g)); "
        "R175 pads R175a (%.2f, %.2f) and R175b (%.2f, %.2f); spares %s (sp)."
        % (len(g["tab_x_pads"]), g["xs"][0], g["xs"][-1], g["ys"][0], g["ys"][-1], r175a[0], r175a[1], r175b[0], r175b[1],
           " and ".join("(%.2f, %.2f)" % tuple(p) for p in g["spare"])),
        "    Pad number = F-number; the tap of each F-pad is in A.4. Every orthogonal pair is in the H.23(g) short table; none is forbidden.",
        "Residual tap pads on the footprint low-y band (H.23(g)): %s; F22 is the low-row T18 position nearest CO-5V (BASIS B3; straight %.2f mm to CO-5V pad 1)."
        % (", ".join("%s (%s) at (%.2f, %.2f)" % (g["assignment"][t][0], t, v[0], v[1]) for t, v in g["residual"].items()),
           [c["straight"] for c in g["t18_candidates"] if tuple(c["pad"]) == tuple(g["t18_pad"])][0]),
        "FT1 = %.1f x %.1f mm at (%.2f, %.2f), tx/ty ±%.3f/%.3f mm, bound by the %s; "
        "FT2 = %.1f x %.1f mm at (%.2f, %.2f), tx/ty ±%.3f/%.3f mm, bound by the %s (H.23(i))."
        % (f1["size"][0], f1["size"][1], f1["centre"][0], f1["centre"][1], f1["tx"], f1["ty"], re.sub(r" w[\d.]+ \(.*?\)-\(.*?\)", "", f1["bind"]),
           f2["size"][0], f2["size"][1], f2["centre"][0], f2["centre"][1], f2["tx"], f2["ty"], f2["bind"]),
        "Foot block height h_f = 2.54 - t_bed %.2f - t_bond %.2f = %.2f mm (block +0/-0.05 mm; 0.05 mm acrylic transfer tape on the CR bottom; H.23(i))."
        % (i1["foot_height"]["t_bed_nom"], i1["foot_height"]["t_bond"], i1["foot_height"]["h_f"]),
        "Foot keep-out = body + 0.5 mm; FT1 has an RTV lane to the tab X top edge (bedded before the W leads and taps, B1), FT2 has no lane (H.23(d)).",
        "FT2 sits at the far edge of tab Y (B2: largest lever from the pin-11 row with t >= 0.25 mm); its +y lane is behind the L-FC body, so it is "
        "bedded through a %.1f mm NPTH fill hole at (%.2f, %.2f)," % (fh["d"], fh["centre"][0], fh["centre"][1]),
        "    injected from the CR top (%.1f mm CR-top keep-out disc). The mid-height spot (%.2f, %.2f), ty %.2f mm, is a sensitivity case only."
        % (fh["ko_disc"], i1["alternatives"]["ft2_mid"]["centre"][0], i1["alternatives"]["ft2_mid"]["centre"][1],
           i1["alternatives"]["ft2_mid"]["ty"]),
        "Thermal band boundary: H.23(h) samples at x 48.7-64.7 (1 mm) plus x 65.00 (y %.2f), computed here with r7_calc.d5v under the same rule." % band_end[1],
        "Copper rim = polygon vertex path or trace centre line + half the outline width (r7_calc convention); vias at the 0.7564 mm pad. "
        "Only the 5V set near tab X and the VBUS pour near tab X are drawn.",
        "W6/W7 pads: A.8 gives 1.2 x 1.5 mm; the orientation (1.2 mm along x) is an ASSUMPTION. Header pads are drawn at the A.8 minimum 1.9 mm.",
        "W-lead dressing path (A.3, H.23(l)): trunk +y on x 25.80, +x across tab Y at y 69.60-71.75, off the CR at x 37.56 to tie base A1; west group "
        "(W1, W2, W6, W7) up x 58.00, east group (W3, W4, W5) via A2.",
        "    Anchors: beads B1/B3 and W5 spacers S1-S3 on the CR (3.0 x 3.0 mm, ASSUMPTION; B3 and S3 merge), tie bases A1 %.0f x %.0f mm +- %.1f and "
        "A2 %.0f x %.0f mm +- %.1f on the MB (zone dashed); longest span 26.0 mm (<= 30 mm)."
        % (tbs["A1"]["side"], tbs["A1"]["side"], tbs["A1"]["tol"], tbs["A2"]["side"], tbs["A2"]["side"], tbs["A2"]["tol"]),
        "3-D switched-conductor rule (decision 2026-11-10, no height limit): the round leads are held >= %.2f mm above the MB from B1 to (%.2f, %.2f), "
        "W5 >= %.2f mm (L-FC top 5.0 mm, ASSUMPTION)."
        % (J["l"]["rev4"]["sw3d"]["W1"][0]["need"], J["l"]["rev4"]["sw3d"]["W1"][0]["p1"][0], J["l"]["rev4"]["sw3d"]["W1"][0]["p1"][1],
           J["l"]["rev4"]["sw3d"]["W5"][0]["need"]),
        "Polyimide strip on the MB under the leads off the CR: lead envelope + 2.0 mm within x %.2f-%.2f, y %.2f-%.2f (drawn from the tab Y +x edge); "
        "it stops at each tie-base footprint." % tuple(Ld["polyimide_strip"][k] for k in (0, 2, 1, 3)),
        "W1/W2: fixed build length 0.30 m +- 10 mm (routes %.1f / %.1f mm; slack = service loop on the EVM plate, D-F3). Route maxima after MS2: %s mm; "
        "until MS2 the 0.30 m caps stay the T-A-02 bound."
        % (routes["W1"]["L"], routes["W2"]["L"], ", ".join("%s %d" % (k, v["max"]) for k, v in routes.items() if v["max"])),
        "    W5: fixed 304.8 mm factory cable; route %.1f mm + 20 mm 3-D allowance = %.1f mm minimum fit." % (routes["W5"]["L"], routes["W5"]["L"] + 20.0),
        "Sheet openings (H.23(m)): 2.2 mm relief holes at the 22 header pads (3.4 mm holes would merge into slots and drop t_bed to %.3f mm); "
        "five enlarged cut-outs merge into two openings." % J["m"]["relief"]["t_bed_nominal_after"],
        "EVM panel: EVM, EIB, USB corridor and routes from H.23(l); the EVM bottom edge sits 20 mm past the MB +y edge (J8 mating gap); "
        "J1/J5/J7/J8 dots are the route terminals; the USB plug + bend length is TODO(measure: MS2).",
        "CHG header pads: pin 1 (45.998, 39.084), pins 1-10 on x 45.998; pin 11 (20.998, 64.484), pins 11-22 on x 20.998 (A.8).",
        "MB parts within 25 mm of the r7 outline that lie wholly below y 25 (outside the window): %s." % ", ".join(sorted(outside)),
    ]
    if unl:
        notes.append("MB parts drawn without a name (no free label position): %s." % ", ".join(unl))
    ny = ly0 + 12 + ((len(items) + cols - 1) // cols) * rowh + 22
    s.text(PX0, ny, "Notes", 11, weight="bold")
    for k, t in enumerate(notes):
        s.text(PX0, ny + 16 + k * 14.5, t, 8.8, color=INK)
    path = os.path.join(OUTDIR, "carrier_layout_r7.svg")
    s.h = int(ny + 16 + len(notes) * 14.5 + 10)
    s.items[0] = '<rect x="0" y="0" width="%d" height="%d" fill="#ffffff"/>' % (s.w, s.h)
    s.save(path)
    return s, path, dict(band_end=band_end, outside=outside, unlabelled=unl)


# ===================================================================== checks
def check(svg, path):
    ET.parse(path)                                        # well-formed XML
    over = []
    tb = svg.tb
    for i in range(len(tb)):
        for j in range(i + 1, len(tb)):
            if boxes_overlap(tb[i], tb[j], 0.5):
                over.append((tb[i][4], tb[j][4]))
    off = [t[4] for t in tb if t[0] < -0.5 or t[2] > svg.w + 0.5 or t[1] < -0.5 or t[3] > svg.h + 0.5]
    return over, off


if __name__ == "__main__":
    for fn in (wiring, schematic, layout):
        res = fn()
        sv, pth = res[0], res[1]
        ov, off = check(sv, pth)
        print("wrote %s (%d text items; XML ok)" % (pth, len(sv.tb)))
        for a_, b_ in ov:
            print("  text overlap: %r <-> %r" % (a_, b_))
        for t_ in off:
            print("  text outside the canvas: %r" % t_)
        if len(res) > 2:
            print("  info:", res[2])
