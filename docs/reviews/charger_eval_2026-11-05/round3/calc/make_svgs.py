#!/usr/bin/env python3
"""Generate round3/wiring_bq25798.svg and round3/carrier_schematic.svg (stdlib only).

Edit this generator, not the SVGs. Netlists here must match docs/charger_bq25798_wiring_design_2026-11-05.md
sections A and B. Run: python3 make_svgs.py
"""
import os
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.dirname(HERE)

INK, MUTE, PWR, BAT, SIG, TAP, GNDC, FILL1, FILL2, FILL3, FILL4 = (
    "#1b1f24", "#5b6470", "#c0392b", "#8e44ad", "#1f6fb2", "#2e8b57", "#444", "#f4f6f8", "#fff7e6", "#eef6ff", "#f0fff4")


class Svg:
    def __init__(self, w, h, title):
        self.w, self.h, self.items = w, h, []
        self.items.append('<rect x="0" y="0" width="%d" height="%d" fill="#ffffff"/>' % (w, h))
        self.text(w / 2, 26, title, 18, anchor="middle", weight="bold")

    def text(self, x, y, s, size=11, anchor="start", color=INK, weight="normal", italic=False):
        st = ' font-style="italic"' if italic else ""
        self.items.append('<text x="%.1f" y="%.1f" font-family="DejaVu Sans, Arial, sans-serif" font-size="%s" '
                          'text-anchor="%s" fill="%s" font-weight="%s"%s>%s</text>' % (x, y, size, anchor, color, weight, st, escape(s)))

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

    def cap(self, x, y, label, vertical=True, color=INK):
        # capacitor from (x,y) down to ground symbol
        self.line([(x, y), (x, y + 10)], color)
        self.line([(x - 8, y + 10), (x + 8, y + 10)], color, 2)
        self.line([(x - 8, y + 15), (x + 8, y + 15)], color, 2)
        self.line([(x, y + 15), (x, y + 24)], color)
        self.gnd(x, y + 24)
        self.text(x + 11, y + 15, label, 9, color=color)

    def gnd(self, x, y, color=GNDC):
        self.line([(x - 7, y), (x + 7, y)], color, 1.6)
        self.line([(x - 4, y + 3), (x + 4, y + 3)], color, 1.4)
        self.line([(x - 1.5, y + 6), (x + 1.5, y + 6)], color, 1.2)

    def flag(self, x, y, name, side="R", color=SIG):
        w = 7 * len(name) + 10
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

    def save(self, path):
        with open(path, "w") as fh:
            fh.write('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">\n' % (self.w, self.h, self.w, self.h))
            fh.write("\n".join(self.items))
            fh.write("\n</svg>\n")


# ===================================================================== wiring diagram
def wiring():
    s = Svg(1760, 1300, "BQ25798EVM in place of the Ag105: wiring (board rev 20260622, round 3 r6)")
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
    s.text(48, 330, "R1/R2-CHG -> pin 38 (no W8, r2: no current limit in Run)", 10, color=MUTE)
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
    s.line([(440, 354), (440, 405), (575, 405), (575, pad["18"][1]), (pad["18"][0], pad["18"][1])], BAT, 2.4)

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
        s.text(105, y + 4, n, 10)
        s.dot(568, y, TAP)
        s.text(560, y + 4, t, 9, anchor="end", color=TAP)
    s.text(52, 1180, "CO-5V pad 1 (+5 V) -> F101 fuse + R172 33R at the joint -> T18, keep-alive option only (DNP). T1/T2: 10.0k at the joint, then the wire.", 10, color=MUTE)
    s.text(52, 1198, "Pins 5, 6, 18, 19 reach CR through CHG pads 11, 3, 8, 7 (no tap). Pin 20 kept for WDOG1_B (R5).", 10, color=MUTE)
    s.text(52, 1216, "Pins 2, 8 (encoder nets) untouched (T-A-01b); F24 optional PURGE_SENSE on pin 2 only if cleared. No T7.", 10, color=MUTE)

    # ---------------- carrier
    cx, cy, cw, ch = 650, 110, 400, 1000
    s.box(cx, cy, cw, ch, "CR  CHG adapter carrier (31 x 33 mm, 4-layer, 2 oz)", FILL3)
    s.text(cx + 10, cy + 40, "1x10 + 1x12 header pins = CHG pads (A.2); netlist B.8", 10, color=MUTE)
    s.box(cx + 20, cy + 60, 360, 128, "U101 eFuse TPS26630RGER", "#fff")
    s.text(cx + 30, cy + 98, "IN/IN_SYS <- VCHGIN (pad 10 only)   OUT -> VCHGOUT", 10)
    s.text(cx + 30, cy + 116, "I_OL 2.05-2.41 A (R101 8.06k); UVLO 9.9 V; OVP 23.1 V", 10)
    s.text(cx + 30, cy + 134, "IN: C102a/b/c 1u+4.7u(100V)+0.1u, D107 SMAJ33A class; OUT: D103 SMA + C103 (r5 region table)", 10)
    s.text(cx + 30, cy + 152, "IMON 27.4k -> R129 10k / C129 1n -> T17; FLT -> T16 (R106 DNP)", 10)
    s.text(cx + 30, cy + 170, "MODE open, SHDN open, PGTH + PGOOD to GND", 10, color=MUTE)
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
    s.box(cx + 20, cy + 725, 360, 110, "Connectors and pads", "#fff")
    s.text(cx + 30, cy + 761, "J101 2x7 1.27 mm SMT, keyed -> W5 ribbon to EIB J201", 10)
    s.text(cx + 30, cy + 779, "tap field F01-F24 (3 x 8 top-side SMT pads, no holes) -> T1-T21", 10)
    s.text(cx + 30, cy + 797, "power holes (r5): W1/W2 1.3 mm, pad 2.3 (30.3/27.7, 61.2), W3/W4 1.5 mm (24.3, 45.4/55.6)", 10)
    s.text(cx + 30, cy + 815, "SCL/SDA/GND pads -> W7 to EVM J8; R145/R146 DNP", 10)
    s.text(cx + 20, cy + 870, "Power star: CR GND = pads 4, 14, 15", 10, color=GNDC, weight="bold")
    s.text(cx + 20, cy + 888, "STAT pad 3: R107 10k to 3V3 -> W5 pin 4", 10, color=SIG)
    s.text(cx + 20, cy + 942, "3V3: T6 -> R175 68R; R176/R177 200R -> W5 1/2 (r4)", 10, color=SIG)
    s.text(cx + 20, cy + 906, "THERM pad 13 -> W6 (only if NTC, T-E-09)", 10, color=SIG)
    s.text(cx + 20, cy + 924, "readback in: W5 11 -> R125 -> T12; W5 13 -> R148 -> T20 (pin 7)", 10, color=SIG)
    s.text(cx + 20, cy + 960, "r6: Eagle coords, +y UP; outline chamfer at the pin-11 corner (A.8)", 10, color=MUTE)

    s.line([(pad["22"][0] + 10, fy + 160), (cx, fy + 160)], MUTE, 6, "2,4")
    s.text((pad["22"][0] + cx) / 2, fy + 150, "22 header pins", 10, "middle", MUTE)
    for i in range(len(taps)):
        y = 820 + i * 19
        s.line([(568, y), (612, y), (612 + (i % 5) * 4, cy + 790), (cx, cy + 779)], TAP, 0.8)
    s.line([(580, 150), (622, 150), (622, cy + 243), (cx + 20, cy + 243)], TAP, 1.2)
    s.text(585, 145, "T2", 9, color=TAP)
    s.line([(580, 240), (632, 240), (632, cy + 251), (cx + 20, cy + 251)], TAP, 1.2)
    s.text(585, 235, "T1, T7b", 9, color=TAP)
    s.line([(580, 390), (640, 390), (640, cy + 279), (cx + 20, cy + 279)], TAP, 1.2)
    s.text(585, 385, "T9", 9, color=TAP)

    # ---------------- EIB
    ex, ey = 1110, 470
    s.box(ex, ey, 270, 400, "EIB  EVM interface board (chassis)", FILL4)
    lines = [("U201 SN74LVC3G06 (open drain)", True), ("  1Y -> /CE (E5, TP36); R272 + R272b 47k on the EVM", False),
             ("  2Y -> Q203 gate (PMOS feed)", False), ("  3Y -> Q202 gate (FC leg)", False),
             ("U202 SN74LVC1G06 -> Q201 gate (hold)", True), ("Q203 BSS84: REGN -> R255 48.7k -> E2", False),
             ("   (JP14 pin 2; EVM R21 = 0 ohm)", False), ("Q201 2N7002K: ILIM (E3, TP33) -> AGND", False),
             ("Q202 2N7002K + R257 59.0k -> E3", False), ("gate pull-ups 47k to REGN (E1)", False),
             ("47k pull-downs on every driver input", False), ("U203 TLV3012B ILIM sense (E4, JP21)", True),
             ("   thr 0.59-0.65 V -> R265 470R -> W5 11", False), ("U204 TLV3012B /CE sense (E6, JP17)", True),
             ("   /CE/2 vs REF -> R264 470R -> W5 13", False), ("STAT: E7 TP38 -> R275 1k (r5) -> W5 4; AGND: E8 TP49", False),
             ("R273 10R ribbon GND; R274 10k bleed", False),
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
              (vy + 470, "EIB joints (A.5, r6 row top->bottom)", ["E8 TP49 AGND   E3 TP33 ILIM", "E4 JP21 (sense)  E2 JP14 pin 2",
                                            "E7 TP38 STAT   E1 JP12 REGN pin", "E5 TP36 /CE    E6 JP17 (sense)"], INK),
              (vy + 620, "On-EVM parts", ["R256 200k + C252 2.2n across JP21 1-2", "R272 (R42 site) + R272b (TP36) 47k -> REGN", "EVM R23 -> 49.9k; R21 -> 0 ohm"], INK),
              (vy + 750, "Mods (section C)", ["JP17 shunt + pin 2 (AGND), R42, R39, R40, JP32, JP7, JP30 out", "JP14 shunt + pin 1, JP13 pin 1, R20 out",
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
    s.text(1070, cy + 84, "W1/W2  20 AWG twisted pair, <= 0.30 m", 10, color=PWR)
    s.line([(cx + cw, cy + 950), (1395, cy + 950), (1395, anchors["J5"]), (vx + 15, anchors["J5"])], BAT, 3.4)
    s.line([(cx + cw, cy + 960), (1405, cy + 960), (1405, anchors["J5"] + 34), (vx + 15, anchors["J5"] + 34)], INK, 3.4)
    s.text(1070, cy + 984, "W3/W4  18 AWG twisted pair, <= 0.30 m", 10, color=BAT)
    s.line([(cx + cw, cy + 815), (1385, cy + 815), (1385, anchors["J8"]), (vx + 15, anchors["J8"])], SIG, 1.8)
    s.text(1070, cy + 809, "W7  SCL-GND-SDA twisted triple, <= 0.30 m", 10, color=SIG)
    s.line([(cx + cw, cy + 761), (1090, cy + 761), (1090, ey + 200), (ex, ey + 200)], SIG, 2.2)
    s.box(1080, ey - 85, 300, 64, None, "#fff", stroke=SIG, sw=1)
    s.text(1088, ey - 68, "W5  14-way 0.635 mm ribbon, <= 0.30 m (J101 -> J201)", 10, color=SIG)
    s.text(1088, ey - 50, "1 3V3 2 3V3 3 GND 4 STAT 5 CE_DRV 6 KEY (pin omitted) 7 REL_A", 9, color=SIG)
    s.text(1088, ey - 34, "8 REL_B 9 GND 10 RFC_OFF 11 ILIM_SNS 12 GND 13 CE_SNS 14 GND", 9, color=SIG)
    s.line([(ex + 270, ey + 150), (1415, ey + 150), (1415, anchors["EIB"]), (vx + 15, anchors["EIB"])], INK, 1.6)
    s.line([(cx + cw, cy + 906), (1375, cy + 906), (1375, anchors["J7"]), (vx + 15, anchors["J7"])], SIG, 1.4, "6,3")
    s.text(1070, cy + 900, "W6  26 AWG pair (only if NTC)", 10, color=SIG)

    lx, ly = 1110, 1100
    s.box(lx, ly, 280, 170, "Legend", "#fff", tsize=11)
    for i, (c, t, w) in enumerate([(PWR, "charger input (VCHG-IN / VCHGOUT)", 3), (BAT, "charger output (VCHG)", 3), (INK, "return / GND / EIB joints", 3),
                                   (SIG, "signal / I2C / ribbon", 2), (TAP, "tap to MB (26 AWG)", 1.2), (MUTE, "mechanical / not connected", 1.2)]):
        s.line([(lx + 12, ly + 40 + i * 20), (lx + 52, ly + 40 + i * 20)], c, w)
        s.text(lx + 60, ly + 44 + i * 20, t, 10)
    s.save(os.path.join(OUTDIR, "wiring_bq25798.svg"))


# ===================================================================== carrier schematic
def schematic():
    s = Svg(1760, 1420, "CHG adapter carrier (CR) and EVM interface board (EIB): schematic, round 3 r6")
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
    s.flag(110, 150, "VCHGIN", "L", PWR)
    s.line([(110, 150), (200, 150)], PWR, 2)
    s.line([(150, 150), (150, 172), (200, 172)], PWR, 1.5)
    s.dot(150, 150, PWR)
    s.cap(130, 150, "C102a/b/c 1u+4.7u+0.1u; D107")
    s.res(60, 150, 60, 210, "R102 845k 0805")
    s.line([(60, 150), (110, 150)], PWR)
    s.line([(60, 210), (200, 210)])
    s.res(60, 210, 60, 240, "R103 66.5k")
    s.line([(60, 240), (200, 240)])
    s.dot(60, 240)
    s.res(60, 240, 60, 300, "R104 49.9k")
    s.gnd(60, 300)
    s.text(30, 320, "(0.1 %)", 8, color=MUTE)
    s.cap(185, 270, "C101 22n")
    s.line([(185, 270), (200, 270)])
    s.res(200, 300, 130, 300, "R101 8.06k")
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
    s.res(360, 190, 470, 190, "R129 10k")
    s.flag(470, 190, "CHG_IIN (T17)", "R")
    s.res(385, 190, 385, 240, "R105 27.4k")
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
    s.tri(840, 150, 70, "U102 H1")
    s.flag(660, 115, "T1 (R170 10k at MB)", "L", TAP)
    s.res(660, 115, 740, 115, "R109 487k 0805")
    s.line([(740, 115), (780, 115), (780, 130), (840, 130)])
    s.res(780, 115, 780, 185, "")
    s.text(790, 160, "R110 56.2k", 8)
    s.gnd(780, 185)
    s.cap(760, 115, "C106")
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
    s.tri(840, 350, 70, "U103 UVB")
    s.flag(660, 320, "T2C", "L", TAP)
    s.res(660, 320, 740, 320, "R114 1.00M 0805")
    s.line([(740, 320), (780, 320), (780, 330), (840, 330)])
    s.res(780, 320, 780, 390, "")
    s.text(790, 370, "R115 104k", 8)
    s.gnd(780, 390)
    s.cap(755, 320, "C108 1n")
    s.line([(840, 370), (820, 370), (820, 410), (890, 410)])
    s.text(895, 414, "own REF; D106 clamp", 8)
    s.line([(903, 350), (980, 350)])
    s.flag(980, 350, "UVB", "R")
    s.res(925, 350, 925, 300, "")
    s.line([(925, 300), (820, 300), (820, 330)])
    s.text(932, 322, "R116 10.0M", 8)
    s.tri(840, 480, 70, "U104 BT_OK")
    s.text(640, 444, "REF -R141 61.9k- IN+ -R142 1.00k SOT- KELVIN (T9); R143 100R KELVIN-GND", 9)
    s.flag(820, 460, "IN+ 19.75 mV", "L")
    s.flag(700, 500, "BT_CURR (T8)", "L", TAP)
    s.res(700, 500, 780, 500, "R140 10k")
    s.line([(780, 500), (840, 500)])
    s.cap(790, 500, "C140 10n")
    s.text(640, 535, "R144 1.00M T8 -> 3V3 (open tap -> BT_OK LOW)", 9, color=TAP)
    s.line([(903, 480), (980, 480)])
    s.flag(980, 480, "BT_OK", "R")
    s.tri(840, 610, 70, "U115 BTB_OFF")
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
        s.flag(1475, y, n, "R")
    s.text(1200, 600, "STAT pad 3: R107 10k to 3V3 -> J101.4. SDA/SCL pads 8/7 -> W7; R145/R146 DNP (pull-ups MB 2.7k, PM9).", 9, color=MUTE)
    s.text(1200, 618, "Decoupling 100 nF: C110 U102, C111 U103, C112 U104, C113 U115, C114-C123 U105-U116, C126 U118, C131-C135 U119-U123 (r6); C125 10u bulk.", 9, color=MUTE)

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

    # ---------- EIB
    s.box(20, 690, 1720, 530, "5  EVM interface board (EIB, 2xx) on the chassis; VCC = 3V3 from ribbon pins 1+2 via CR R176/R177 200R (R274 10k bleed); AGND = TP49 (E8) only", FILL4)
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
    s.flag(640, 810, "REGN (E1)", "R", PWR)
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
    s.flag(1470, 855, "ILIM_SNS (E4, JP21)", "L", TAP)
    s.line([(1470, 855), (1500, 855)])
    s.text(1300, 880, "R258 10.0k series (r3); R259 10M to 3V3", 8)
    s.text(1460, 912, "IN- = REF x R261 10.0k/(R260 10.0k + R261) (0.59-0.65 V); R265 470R (r4)", 8)
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
    s.save(os.path.join(OUTDIR, "carrier_schematic.svg"))


if __name__ == "__main__":
    wiring()
    schematic()
    print("wrote", os.path.join(OUTDIR, "wiring_bq25798.svg"), "and", os.path.join(OUTDIR, "carrier_schematic.svg"))
