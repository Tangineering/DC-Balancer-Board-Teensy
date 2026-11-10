#!/usr/bin/env python3
"""Round 4 (r7) minimal-change proposal: outline, MB copper under the two tabs, area booking, pin load and
resonance, tap lengths, E-lead maxima and header post arithmetic.

Coordinates: Eagle .brd board coordinates, top view, origin = MB origin, +x right, +y UP, mm.
Run: /c/Users/ricky/miniforge3/python.exe -I r7_minimal_calc.py   (numpy required)
Every input is either quoted from a named source (design r6 section, a round-4 work note, the .brd) or marked
ASSUMPTION. Output: r7_minimal_calc_out.txt beside this script (written by redirection).
"""
import importlib.util
import math
import os
import xml.etree.ElementTree as ET

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
R4 = os.path.normpath(os.path.join(HERE, "..", ".."))
BRD = os.path.normpath(os.path.join(R4, "..", "..", "..", "..", "references", "Scale Car Board PCB 20260625.brd"))

spec = importlib.util.spec_from_file_location("mbn", os.path.join(R4, "calc", "mb_neighbours.py"))
mbn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mbn)

# ----------------------------------------------------------------------------------------------------------------
# 1. Outline (r6 rectangle + two tabs). r6: design A.7. Tabs: this proposal.
# ----------------------------------------------------------------------------------------------------------------
MAIN = (17.70, 34.14, 48.70, 67.14)          # r6 CR outline, design A.7
TAB_X = (48.70, 56.30, 65.00, 68.30)         # +x tab: x to 65.00 (VBUS pour starts x 65.53, mb_mechanical 4.1);
#                                              low edge 1.79 mm above REG-5V body top y 54.51 (.brd), i.e. the r6
#                                              1.8 mm LM1084 side clearance; top 68.30 = +x usable top, 1.70 mm below MDAC-FC
TAB_Y = (17.70, 67.14, 39.72, 76.51)         # +y usable (mb_mechanical Table 1): 0.5 mm below L-FC, left of OP-FC
CY = 0.5                                     # courtyard limit inside the outline (design A.7)
RES = 0.05                                   # raster mm

PIN_A = [(20.998, 36.544 + 2.54 * k) for k in range(12)]   # pins 22..11, design A.8
PIN_B = [(45.998, 39.084 + 2.54 * k) for k in range(10)]   # pins 1..10


def area(r):
    return (r[2] - r[0]) * (r[3] - r[1])


def rect_mask(r, grid):
    X, Y = grid
    return (X >= r[0]) & (X <= r[2]) & (Y >= r[1]) & (Y <= r[3])


def seg_dist(X, Y, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return np.hypot(X - ax, Y - ay)
    t = np.clip(((X - ax) * dx + (Y - ay) * dy) / L2, 0, 1)
    return np.hypot(X - (ax + t * dx), Y - (ay + t * dy))


def pip(X, Y, poly):
    """Even-odd point in polygon on a grid."""
    inside = np.zeros_like(X, dtype=bool)
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cond = ((y1 > Y) != (y2 > Y))
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (x2 - x1) * (Y - y1) / (y2 - y1 + 1e-30) + x1
        inside ^= cond & (X < xint)
    return inside


def load_board():
    return ET.parse(BRD).getroot().find("drawing/board")


POWER_NETS_HINT = ("VBT", "VCHG", "VBUS", "5V", "V-MOT", "VMOT", "VFC", "VOUT", "VSW", "VBAL", "PACK", "VIN")


def classify(net):
    if net == "GND":
        return "GND"
    if net == "3V3":
        return "3V3"
    if any(net.upper().startswith(h) for h in POWER_NETS_HINT):
        return "POWER"
    return "SIGNAL"


def mb_l1_copper(board, rect, pad=1.5):
    """L1 (MB top, faces the CR underside) copper and all vias inside rect grown by `pad`."""
    x0, y0, x1, y1 = rect[0] - pad, rect[1] - pad, rect[2] + pad, rect[3] + pad
    wires, polys, vias = [], [], []
    for sig in board.find("signals"):
        net = sig.get("name")
        for g in sig:
            if g.tag == "wire" and g.get("layer") == "1":
                ax, ay, bx, by = (float(g.get(k)) for k in ("x1", "y1", "x2", "y2"))
                if max(ax, bx) >= x0 and min(ax, bx) <= x1 and max(ay, by) >= y0 and min(ay, by) <= y1:
                    wires.append((net, ax, ay, bx, by, float(g.get("width"))))
            elif g.tag == "polygon" and g.get("layer") == "1":
                pts = [(float(v.get("x")), float(v.get("y"))) for v in g.findall("vertex")]
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                if max(xs) >= x0 and min(xs) <= x1 and max(ys) >= y0 and min(ys) <= y1:
                    polys.append((net, pts))
            elif g.tag == "via":
                x, y = float(g.get("x")), float(g.get("y"))
                if x0 <= x <= x1 and y0 <= y <= y1:
                    vias.append((net, x, y, float(g.get("drill"))))
    return wires, polys, vias


def shadow_masks(board, rect, grid, grow):
    """Return masks of MB L1 copper of each class (grown by `grow`) within the grid."""
    X, Y = grid
    wires, polys, vias = mb_l1_copper(board, rect)
    m = {c: np.zeros_like(X, dtype=bool) for c in ("POWER", "3V3", "SIGNAL")}
    nets = {}
    for net, ax, ay, bx, by, w in wires:
        c = classify(net)
        nets.setdefault(net, 0)
        nets[net] += math.hypot(bx - ax, by - ay)
        if c == "GND":
            continue
        m[c] |= seg_dist(X, Y, ax, ay, bx, by) <= (w / 2 + grow)
    for net, pts in polys:
        c = classify(net)
        if c == "GND":
            continue
        inside = pip(X, Y, pts)
        if grow > 0:
            # grow by dilation with the polygon edges
            for i in range(len(pts)):
                ax, ay = pts[i]
                bx, by = pts[(i + 1) % len(pts)]
                inside |= seg_dist(X, Y, ax, ay, bx, by) <= grow
        m[c] |= inside
        nets.setdefault(net + " (poly)", 0)
    # via annular pad: drill + 2 x 0.25 mm ASSUMPTION (Eagle default restring is not read here)
    for net, x, y, d in vias:
        c = classify(net)
        if c == "GND":
            continue
        m[c] |= np.hypot(X - x, Y - y) <= (d / 2 + 0.25 + grow)
    return m, wires, polys, vias


def parts_in(rect):
    board = load_board()
    els = mbn.element_records(board)
    out = []
    for e in els:
        if e["name"] == "CHG":
            continue
        b = e["bbox"]
        if b[2] > rect[0] and b[0] < rect[2] and b[3] > rect[1] and b[1] < rect[3]:
            out.append((e["name"], e["package"], [round(v, 2) for v in b]))
    return out


def tab_report(board, name, tab, joined_edges):
    """Courtyard-usable area of one tab (top), and underside area clear of MB L1 copper classes."""
    lo = [tab[0] + (0 if "L" in joined_edges else CY), tab[1] + (0 if "B" in joined_edges else CY),
          tab[2] - (0 if "R" in joined_edges else CY), tab[3] - (0 if "T" in joined_edges else CY)]
    xs = np.arange(lo[0] + RES / 2, lo[2], RES)
    ys = np.arange(lo[1] + RES / 2, lo[3], RES)
    X, Y = np.meshgrid(xs, ys)
    cell = RES * RES
    usable = X.size * cell
    print("\n=== %s  outline %s  gross %.1f mm2  courtyard-usable %.1f mm2 (rect %s)" % (
        name, tab, area(tab), usable, [round(v, 2) for v in lo]))
    pr = parts_in(tab)
    print("  MB parts overlapping the tab outline:", pr if pr else "none")
    for grow in (0.0, 1.0):
        m, wires, polys, vias = shadow_masks(board, tab, (X, Y), grow)
        p = m["POWER"]
        anyng = m["POWER"] | m["3V3"] | m["SIGNAL"]
        print("  grow %.1f mm: under POWER %.1f, under 3V3 %.1f, under SIGNAL %.1f, under any non-GND %.1f mm2;"
              " clear of POWER (rule A) %.1f, clear of all non-GND (rule B) %.1f mm2" % (
                  grow, p.sum() * cell, m["3V3"].sum() * cell, m["SIGNAL"].sum() * cell, anyng.sum() * cell,
                  (~p).sum() * cell, (~anyng).sum() * cell))
        if grow == 0.0:
            nets = {}
            for net, ax, ay, bx, by, w in wires:
                # length inside the tab outline (sampled)
                n = max(2, int(math.hypot(bx - ax, by - ay) / 0.05))
                inside = 0.0
                for i in range(n):
                    t = (i + 0.5) / n
                    x, y = ax + t * (bx - ax), ay + t * (by - ay)
                    if tab[0] <= x <= tab[2] and tab[1] <= y <= tab[3]:
                        inside += math.hypot(bx - ax, by - ay) / n
                if inside > 0:
                    k = "%s w%.3f" % (net, w)
                    nets[k] = nets.get(k, 0) + inside
            print("  MB L1 traces inside the tab (mm):", {k: round(v, 1) for k, v in sorted(nets.items())})
            pv = [(n_, round(px, 2), round(py, 2)) for n_, px, py, d in vias
                  if tab[0] <= px <= tab[2] and tab[1] <= py <= tab[3]]
            print("  vias inside the tab (all tented, mlViaStopLimit, mb_mechanical 4.1): %d, non-GND: %s" % (
                len(pv), [v for v in pv if v[0] != "GND"]))
            pl = []
            for net, pts in polys:
                xs_, ys_ = [q[0] for q in pts], [q[1] for q in pts]
                if net != "GND" and max(xs_) >= tab[0] and min(xs_) <= tab[2] and max(ys_) >= tab[1] and \
                        min(ys_) <= tab[3]:
                    pl.append((net, round(min(xs_), 2), round(min(ys_), 2), round(max(xs_), 2), round(max(ys_), 2)))
            print("  non-GND L1 polygons touching the tab (bbox):", pl if pl else "none")
    return usable, X, Y


# ----------------------------------------------------------------------------------------------------------------
# 2. Area booking (stackup_area.md sections 2-4: strict usable 732 mm2, CR demand 1128 + 60 pours, U4 0.75)
# ----------------------------------------------------------------------------------------------------------------
STRICT_TOP = 732.0
DEMAND = {"all footprints": 1188.0, "forbidden-part footprints deleted (R106, R134, R145, R146, C105)": 1188.0 - 19.3,
          "all DNP footprints removed": 1101.0}
R3_BOTTOM = 435.0      # stackup_area.md section 3: r3 side split top 693 / bottom 435 mm2


def booking(top_ext, bot_cap_A, bot_cap_B):
    print("\n=== Area booking (strict basis)")
    top_total = STRICT_TOP + top_ext
    print("  top usable = %.0f (footprint, strict) + %.1f (tabs) = %.1f mm2" % (STRICT_TOP, top_ext, top_total))
    print("  r3 bottom set kept (435 mm2): top U = %.1f %%" % ((1188 - R3_BOTTOM) / top_total * 100))
    for dname, D in DEMAND.items():
        for U in (0.70, 0.75, 0.80):
            B = max(0.0, D - U * top_total)
            print("  demand %-62s U %.2f: bottom needed %.0f mm2; tab undersides hold %.0f (rule A) / %.0f (rule B)"
                  " at the same U -> footprint residual %.0f / %.0f mm2" % (
                      dname, U, B, U * bot_cap_A, U * bot_cap_B, max(0, B - U * bot_cap_A),
                      max(0, B - U * bot_cap_B)))
    for dname, D in DEMAND.items():
        print("  single-sided U (%s) = %.1f %%" % (dname, D / top_total * 100))


# ----------------------------------------------------------------------------------------------------------------
# 3. Pin load and resonance (model of round4/work/mb_pinload.py, combined tabs)
# ----------------------------------------------------------------------------------------------------------------
def pin_loads():
    print("\n=== Pin load (ORDER OF MAGNITUDE, mb_pinload.py model; ASSUMPTIONS: main CR 5-10 g, populated areal "
          "mass 0.6-0.8 g/cm2, 30 g shock normal to the MB, TODO(measure: M5))")
    pins = PIN_A + PIN_B
    xc = sum(p[0] for p in pins) / 22
    yc = sum(p[1] for p in pins) / 22
    sxx = sum((p[0] - xc) ** 2 for p in pins)
    syy = sum((p[1] - yc) ** 2 for p in pins)
    print("  pin centroid (%.2f, %.2f), Sxx %.0f, Syy %.0f mm2" % (xc, yc, sxx, syy))
    for m_main in (5.0, 10.0):
        for rho in (0.6, 0.8):
            for g in (10.0, 30.0):
                a = 9.81 * g
                F = m_main * 1e-3 * a
                Mx = My = 0.0
                for t in (TAB_X, TAB_Y):
                    m = rho * area(t) / 100.0 * 1e-3
                    cx, cy = (t[0] + t[2]) / 2, (t[1] + t[3]) / 2
                    F += m * a
                    Mx += m * a * (cx - xc) * 1e-3    # N m, moment from x offset
                    My += m * a * (cy - yc) * 1e-3
                per = [F / 22 + Mx * (p[0] - xc) * 1e-3 / (sxx * 1e-6) + My * (p[1] - yc) * 1e-3 / (syy * 1e-6)
                       for p in pins]
                print("  main %4.1f g, %.1f g/cm2, %2.0f g: tab masses X %.2f g, Y %.2f g; worst pin %.3f N "
                      "(r6 CR alone %.3f N); ratio %.2f" % (
                          m_main, rho, g, rho * area(TAB_X) / 100, rho * area(TAB_Y) / 100, max(per),
                          m_main * 1e-3 * a / 22, max(per) / (m_main * 1e-3 * a / 22)))
    E, rho_v, t = 20e9, 1850.0, 1.6e-3      # ASSUMPTIONS, mb_pinload.py
    k = math.sqrt(E * t * t / (12.0 * rho_v))
    for name, L_mm in (("tab X (from pin column x 45.998 to x 65.00)", 65.00 - 45.998),
                       ("tab Y (from pin 11 y 64.484 to y 76.51)", 76.51 - 64.484)):
        L = L_mm * 1e-3
        fs = [(1.875 ** 2) / (2 * math.pi * L * L) * k / math.sqrt(mf) for mf in (1.0, 2.0)]
        print("  f1 %s, L %.1f mm: %.0f-%.0f Hz unpropped (E 20 GPa, t 1.6 mm, mass factor 2-1; upper estimate)" % (
            name, L_mm, fs[1], fs[0]))
    # EVM on the CR: per-pin load per gram of EVM mass, CG at 50 mm from the centroid along x (illustration only)
    pins_x = [p[0] for p in pins]
    rmax = max(abs(x - xc) for x in pins_x)
    for arm in (44.45, 60.0):
        per_g = 1e-3 * 9.81 * 30 * (1 / 22 + arm * rmax / sxx)
        print("  EVM on the CR (rejected): per-pin load per gram of EVM at 30 g with the EVM CG %.1f mm from the "
              "pin centroid: %.3f N/g (EVM mass TODO(measure))" % (arm, per_g))


# ----------------------------------------------------------------------------------------------------------------
# 4. Tap lengths (A.4 destinations as in round4/work/mb_mech_calc.py TAPS)
# ----------------------------------------------------------------------------------------------------------------
TAPS = {
    "T1 C-D6 pad1 (V-MOT)": (97.79, 19.80), "T7b C-D6 pad2 (shield of T1)": (97.79, 19.80),
    "T2 C-D2 pad1 (VBUS)": (67.705, 69.85),
    "T3 J1.39": (87.122, 42.926), "T4 J1.43": (87.122, 37.846), "T5 J1.45": (87.122, 35.306),
    "T6 J1.29": (87.122, 55.626), "T22 BAL pad8": (25.86, 30.44), "T8 J2.31": (109.982, 53.086),
    "T9 SNS-BT GND/REF": (55.118, 23.622), "T10 J1.23": (87.122, 63.246), "T11 J2.19": (109.982, 68.326),
    "T12 J2.47": (109.982, 32.766), "T13 J2.45": (109.982, 35.306), "T14 J2.21": (109.982, 65.786),
    "T15 J2.07": (109.982, 83.566), "T16 J2.43": (109.982, 37.846), "T17 J2.09": (109.982, 81.026),
    "T17r J2.29": (109.982, 55.626), "T20 ROS pad2": (81.534, 69.797), "T21 J2.11": (109.982, 78.486),
}
R3_FIELD = (32.79, 38.34)
TABX_FIELD = (57.08, 61.61)       # centre of a 6 x 4 field at 2.54 mm in tab X: x 50.73-63.43, y 57.80-65.42
RESID_FIELD = {"T22 BAL pad8": (26.44, 35.80), "T8 J2.31": (28.98, 35.80), "T9 SNS-BT GND/REF": (31.52, 35.80)}  # r6 low-y row
RESIDUAL = ("T22 BAL pad8", "T8 J2.31", "T9 SNS-BT GND/REF")


def taps():
    print("\n=== Tap lengths, straight (mm)")
    s3 = s7 = 0.0
    for k, v in TAPS.items():
        if "T7b" in k:
            continue
        a = math.hypot(v[0] - R3_FIELD[0], v[1] - R3_FIELD[1])
        f = RESID_FIELD[k] if k in RESIDUAL else TABX_FIELD
        b = math.hypot(v[0] - f[0], v[1] - f[1])
        s3 += a
        s7 += b
        print("  %-24s r3 field %5.1f  ->  r7 %s %5.1f" % (k, a, "residual" if k in RESIDUAL else "tab X   ", b))
    print("  SUM of the 20 taps (T7b follows T1): r3 %.1f mm, r7 %.1f mm (%.0f %%)" % (s3, s7, (s7 / s3 - 1) * 100))
    # the 6 x 4 field geometry
    xs = [50.73 + 2.54 * i for i in range(6)]
    ys = [57.80 + 2.54 * j for j in range(4)]
    env = (xs[0] - 0.75, ys[0] - 0.75, xs[-1] + 0.75, ys[-1] + 0.75)
    lim = (TAB_X[0], TAB_X[1] + CY, TAB_X[2] - CY, TAB_X[3] - CY)
    print("  tab X field pad centres x %s, y %s; pad envelope %s; inside tab X courtyard limit %s: %s" % (
        [round(x, 2) for x in xs], [round(y, 2) for y in ys], [round(v, 2) for v in env], lim,
        env[0] >= lim[0] and env[2] <= lim[2] and env[1] >= lim[1] and env[3] <= lim[3]))
    print("  distance of the field's low-y pad edge from the 5V pour rim (y ~54.86, mb_mechanical 4.1): %.2f mm"
          % (env[1] - 54.86))


def loop_distance():
    """Largest distance from any point of the r7 outline to the eFuse commutation-loop region (A.8: IN strip
    x 36.1-44.55, y 52.03-61.55; OUT strip x 30.8-39.3, y 62.85-66.64; U101 courtyard x 39.3-44.3, y 61.6-66.6)."""
    loop = [(36.1, 52.03, 44.55, 61.55), (30.8, 62.85, 39.3, 66.64), (39.3, 61.6, 44.3, 66.6)]
    pts = []
    for r in (MAIN, TAB_X, TAB_Y):
        for x in np.arange(r[0], r[2] + 1e-9, 0.25):
            for y in np.arange(r[1], r[3] + 1e-9, 0.25):
                pts.append((x, y))

    def d(p):
        best = 1e9
        for r in loop:
            dx = max(r[0] - p[0], 0, p[0] - r[2])
            dy = max(r[1] - p[1], 0, p[1] - r[3])
            best = min(best, math.hypot(dx, dy))
        return best
    far = max(pts, key=d)
    n365 = sum(1 for p in pts if d(p) >= 36.5)
    print("\n=== Commutation-loop separation: farthest outline point %s at %.1f mm; grid points >= 36.5 mm "
          "(2-layer parity distance, stackup_area 5.2): %d" % ((round(far[0], 2), round(far[1], 2)), d(far), n365))


# ----------------------------------------------------------------------------------------------------------------
# 5. E-lead maxima (evm_geometry.md Table 6, vector positions, r6 EIB placement rule) and the E1/C205 resonance
# ----------------------------------------------------------------------------------------------------------------
E_STRAIGHT = {"E8": 13.6, "E3": 16.7, "E4": 20.6, "E2": 24.6, "E7": 29.9, "E1": 69.0, "E5": 49.1, "E6": 45.4}
E_HARD = {"E3": "92 mm untwisted at s 5 mm (206 mm at s 2 mm)", "E4": "59 mm untwisted at s 5 mm (131 mm within 2 mm "
          "of E8)", "E6": "196 mm untwisted at s 5 mm", "E8": "runs with its group", "E1": "none (static); damping "
          "resistor above ~20 mm", "E2": "none (48.7 kOhm feed)", "E5": "none (static)", "E7": "none (static)"}


def e_leads():
    print("\n=== E-lead maxima: straight x 1.25 rounded up to 5 mm (vector positions) and the pickup criterion")
    for k, s in E_STRAIGHT.items():
        mx = math.ceil(s * 1.25 / 5.0) * 5
        print("  %s straight %.1f -> build max %d mm; criterion limit (eib_merge_failsafe.md Table 9): %s" % (
            k, s, mx, E_HARD[k]))
    # resonance scaling from eib_merge_failsafe.md 3.4: 1.47 MHz at 85 mm, 1.75 at 60 mm, 3.03 at 20 mm
    for L in (85.0, 90.0):
        print("  E1 + C205 series resonance at %.0f mm (scaled from 1.47 MHz at 85 mm as 1/sqrt(L)): %.2f MHz;"
              " BQ25798 fsw 1.5 MHz (JP24, EM19)" % (L, 1.47 * math.sqrt(85.0 / L)))


# ----------------------------------------------------------------------------------------------------------------
# 6. Header post arithmetic (Samtec TSW, mb_mechanical.md Table 7; MB and CR 1.6 mm ASSUMED, PM4)
# ----------------------------------------------------------------------------------------------------------------
def posts():
    print("\n=== Header post arithmetic (TSW body 2.54 mm; tail B below the body, post C above; MB 1.6, CR 1.6 mm"
          " ASSUMED, TODO(measure/verify))")
    for style, A, B, C in (("-05", 8.51, 3.30, 2.67), ("-07", 10.92, 2.54, 5.84), ("-14", 13.46, 2.79, 8.13)):
        for orient in ("C up through the CR", "B up through the CR"):
            up, down = (C, B) if orient.startswith("C") else (B, C)
            print("  TSW%s %s: CR-top protrusion %.2f mm (>= 0.5 for a fillet), MB-bottom protrusion %.2f mm "
                  "(cut to <= 1.0)" % (style, orient, up - 1.6, down - 1.6))
    print("  stack: CR underside 2.54 mm above the MB top (r6 2.665 on the 0.125 mm sheet); CR top 4.14 mm")


if __name__ == "__main__":
    board = load_board()
    print("BRD:", BRD)
    print("MAIN %s %.1f mm2; TAB_X %s %.1f mm2; TAB_Y %s %.1f mm2; total gross %.1f mm2; added %.1f mm2" % (
        MAIN, area(MAIN), TAB_X, area(TAB_X), TAB_Y, area(TAB_Y), area(MAIN) + area(TAB_X) + area(TAB_Y),
        area(TAB_X) + area(TAB_Y)))
    ux, _, _ = tab_report(board, "TAB X", TAB_X, joined_edges="L")
    uy, _, _ = tab_report(board, "TAB Y", TAB_Y, joined_edges="B")
    # Recovered strips at the tab roots (the r6 courtyard limit no longer applies there): tab X root x 48.20-48.70
    # over y 56.80-66.64 (the 1x10 column keep-out ends at x 47.45, stackup_area 2.2); tab Y root y 66.64-67.14 is
    # already inside the tab Y usable rectangle above (joined bottom edge).
    rec_x = (48.70 - 48.20) * (66.64 - 56.80)
    print("\n  recovered root strip of tab X (x 48.20-48.70, y 56.80-66.64): %.1f mm2" % rec_x)
    top_ext = ux + uy + rec_x
    print("  tab top usable total %.1f mm2" % top_ext)
    # Underside capacity: computed by tab_report printouts (rule A / rule B at 1 mm grow). Re-run quickly here.
    caps = {}
    for nm, tab, je in (("X", TAB_X, "L"), ("Y", TAB_Y, "B")):
        lo = [tab[0] + (0 if "L" in je else CY), tab[1] + (0 if "B" in je else CY),
              tab[2] - (0 if "R" in je else CY), tab[3] - (0 if "T" in je else CY)]
        xs = np.arange(lo[0] + RES / 2, lo[2], RES)
        ys = np.arange(lo[1] + RES / 2, lo[3], RES)
        X, Y = np.meshgrid(xs, ys)
        m, _, _, _ = shadow_masks(board, tab, (X, Y), 1.0)
        # MB part shadows (+1 mm) for bottom parts: ROP1-FC/ROP2-FC under tab Y (0.60 mm tall)
        partm = np.zeros_like(X, dtype=bool)
        for pn, pk, b in parts_in(tab):
            partm |= (X >= b[0] - 1) & (X <= b[2] + 1) & (Y >= b[1] - 1) & (Y <= b[3] + 1)
        cell = RES * RES
        a_ = (~(m["POWER"] | partm)).sum() * cell
        b_ = (~(m["POWER"] | m["3V3"] | m["SIGNAL"] | partm)).sum() * cell
        caps[nm] = (a_, b_)
        print("  underside of tab %s outside MB parts (+1 mm): rule A (clear of POWER +1 mm) %.1f mm2, rule B "
              "(clear of every non-GND L1 feature +1 mm) %.1f mm2" % (nm, a_, b_))
    capA = caps["X"][0] + caps["Y"][0]
    capB = caps["X"][1] + caps["Y"][1]
    print("  underside capacity, gross: rule A %.1f, rule B %.1f mm2" % (capA, capB))
    booking(top_ext, capA, capB)
    pin_loads()
    taps()
    loop_distance()
    e_leads()
    posts()
