"""Measure a built board against the r8 design constraints (A.2, A.7, A.8, A.9) and print a markdown table.
Usage (pcbnew venv): python check_constraints.py <cr|eib> <projdir>"""
import math
import os
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass
from shapely.geometry import Polygon, box, Point
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbbuild as pb  # noqa: E402

BOARD, PROJ = sys.argv[1], sys.argv[2]
b = pcbnew.LoadBoard(os.path.join(PROJ, BOARD + ".kicad_pcb"))
rows = []


def row(rule, ref, measured, limit, ok):
    rows.append("| %s | %s | %s | %s | %s |" % (rule, ref, measured, limit, "pass" if ok is True else
                                                 ("FAIL" if ok is False else ok)))


FP = {fp.GetReference(): fp for fp in b.GetFootprints()}


def pads_e(ref, fr):
    return {p.GetNumber(): fr.e(p.GetPosition()) for p in FP[ref].Pads()}


def pad_poly(ref, num, fr):
    for p in FP[ref].Pads():
        if p.GetNumber() == num:
            lay = pcbnew.B_Cu if FP[ref].IsFlipped() else pcbnew.F_Cu
            sps = p.GetEffectivePolygon(lay, pcbnew.ERROR_INSIDE)
            o = sps.Outline(0)
            return Polygon([fr.e(o.CPoint(k)) for k in range(o.PointCount())])


def crt(ref, fr):
    return pb.crt_rect(FP[ref], fr)


if BOARD == "cr":
    import layout_cr as L
    fr = pb.Frame(L.YOFF)
    # A.8 CHG hole table (pin identity, T-A-06 step 0)
    tab = {1: 39.084, 2: 41.624, 3: 44.164, 4: 46.704, 5: 49.244, 6: 51.784, 7: 54.324, 8: 56.864, 9: 59.404,
           10: 61.944}
    tab.update({11 + k: 64.484 - 2.54 * k for k in range(12)})
    pe = pads_e("J1", fr)
    err = max(math.hypot(pe[str(n)][0] - (45.998 if n <= 10 else 20.998), pe[str(n)][1] - y) for n, y in tab.items())
    row("A.8 CHG holes, 22 pins (pin identity)", "J1", "max position error %.4f mm" % err, "0.001 mm", err < 1e-3)
    # outline
    pts = [(round(x, 3), round(y, 3)) for x, y in L.OUTLINE]
    row("A.7 r7 outline V1-V11, chamfer at (17.70, 76.00)", "Edge.Cuts", "%d vertices, bbox %.2f x %.2f mm, area %.2f mm2"
        % (len(pts), L.P.bounds[2] - L.P.bounds[0], L.P.bounds[3] - L.P.bounds[1], L.P.area), "47.30 x 41.86, 1394.06",
        abs(L.P.area - 1394.06) < 0.05)
    # every part on the board (a part the packer could not place is parked outside the outline)
    board_only = {r[0] for r in L.BOARD_ONLY}
    out = sorted(r for r, fp in FP.items() if r not in board_only and not r.startswith("#")
                 and not crt(r, fr).is_empty and not L.P.buffer(0.01).contains(crt(r, fr)))
    row("Every part inside the outline (packer placed all parts)", ", ".join(out) or "all", "%d outside" % len(out), "0",
        not out)
    # D-35: divider tops R102/R109/R111/R114 >= 2.0 mm from logic copper on F.Cu; packer-placed ICs are checked here,
    # the A.8-fixed J1/J101/U102/U103 pins are exempt with one escape each (D-35)
    def _pbox(p):
        bb = p.GetBoundingBox()
        return box(pcbnew.ToMM(bb.GetLeft()), L.YOFF - pcbnew.ToMM(bb.GetBottom()), pcbnew.ToMM(bb.GetRight()),
                   L.YOFF - pcbnew.ToMM(bb.GetTop()))
    hull = unary_union([_pbox(p).convex_hull for r in ("R102", "R109", "R111", "R114") for p in FP[r].Pads()])
    near = []
    for r, fp in FP.items():
        if not r.startswith("U") or fp.IsFlipped() or r in L.FIXED or r in L.ANALOG_ICS:
            continue
        for p in fp.Pads():
            if p.GetNetname() in ("/GND", "/3V3") or not p.GetNetname().startswith("/"):
                continue
            d = _pbox(p).distance(hull)
            if d < 2.0:
                near.append("%s.%s %s %.2f" % (r, p.GetNumber(), p.GetNetname(), d))
    row("D-35 packer-placed logic ICs >= 2.0 mm from divider tops (F.Cu pads)", "; ".join(near) or "none",
        "%d pads inside" % len(near), "0 (operator item; interim exemption, D-35)", "info")
    # fixed pads
    for ref, (x, y) in {"W1": (30.3, 61.2), "W2": (27.7, 61.2), "W3": (24.3, 45.4), "W4": (24.3, 55.6)}.items():
        e = pads_e(ref, fr)["1"]
        row("A.8 added pads", ref, "(%.3f, %.3f)" % e, "(%.2f, %.2f)" % (x, y), math.hypot(e[0] - x, e[1] - y) < 1e-3)
    for ref, want in {"W7": [(27.0, 57.5), (29.0, 57.5), (31.0, 57.5)], "W6": [(33.0, 57.5), (35.0, 57.5)]}.items():
        e = pads_e(ref, fr)
        got = [e[str(i + 1)] for i in range(len(want))]
        d = max(math.hypot(g[0] - w[0], g[1] - w[1]) for g, w in zip(got, want))
        row("A.8 added SMT lead pads", ref, "max error %.4f mm" % d, "0.001 mm", d < 1e-3)
    taps = {k: v for k, v in L.FIXED.items() if k.startswith("F") and k[1:].isdigit()}
    d = max(math.hypot(pads_e(k, fr)["1"][0] - v[0], pads_e(k, fr)["1"][1] - v[1]) for k, v in taps.items())
    row("A.8 r7 tab X assignment and low row (F01-F24)", "%d pads" % len(taps), "max error %.4f mm" % d, "0.001 mm",
        d < 1e-3)
    # eFuse distances (A.8 IN / OUT strip rows)
    u = {n: pad_poly("U101", n, fr) for n in ("1", "2", "5", "17", "18")}
    inpins = unary_union([u["1"], u["2"], u["5"]])
    for ref, num, lim in (("C102c", "1", 3.0), ("C102a", "1", 3.0), ("D107", "1", 3.0)):
        dd = pad_poly(ref, num, fr).distance(inpins)
        row("A.8 IN strip: pad edge to pins 1/2/5", "%s pad %s" % (ref, num), "%.2f mm" % dd, "<= %.1f mm" % lim, dd <= lim)
    dd = pad_poly("C103", "1", fr).distance(unary_union([u["17"], u["18"]]))
    row("A.8 OUT strip: C103 pad to pins 17/18", "C103 pad 1", "%.2f mm" % dd, "<= 3.0 mm", dd <= 3.0)
    dd = pad_poly("R102", "2", fr).distance(pad_poly("U101", "6", fr))
    row("A.8 IN strip: R102 N_UV pad to pin 6 (design 2.1 mm)", "R102", "%.2f mm" % dd, "information", "info")
    # rim rule: comparators, clamps, dividers (U123/D108 removed, D-38) x <= 39.53 (A.7 thermal band, mb_mechanical 5.3)
    for ref in ("U102", "U103", "U104", "U115", "U119", "U120", "U121", "D104", "D105", "D106",
                "R109", "R110", "R111", "R112", "R114", "R115"):
        mx = crt(ref, fr).bounds[2]
        ok = mx <= 39.53 + 1e-6
        if ref in ("U120", "U121") and not ok:
            ok = "conditional (MS4b, T-A-08)"
        row("A.7/A.8 >= 10 mm from the MB 5V rim (courtyard x <= 39.53)", ref, "courtyard x max %.2f" % mx, "<= 39.53", ok)
    # dividers in the divider strip
    strip = box(23.15, 42.14, 36.50, 45.69)
    for ref in ("R109", "R110", "R111", "R112", "R114", "R115"):
        row("A.8 divider strip x 23.15-36.50, y 42.14-45.69", ref, "inside" if strip.buffer(1e-3).contains(crt(ref, fr))
            else "outside", "inside", strip.buffer(1e-3).contains(crt(ref, fr)))
    # distance of analog parts from the U101 loop region
    for ref in ("U102", "U103", "U104", "U115", "U119", "U120", "U121", "D104", "D105", "D106"):
        dd = crt(ref, fr).distance(L.LOOP)
        row("H.23(f) distance from the U101 loop region (information)", ref, "%.2f mm" % dd, "band 10.40 mm", "info")
    # R106s
    e = pads_e("R106s", fr)
    f17 = pads_e("F17", fr)["1"]
    side = "bottom" if FP["R106s"].IsFlipped() else "top"
    dd = min(math.hypot(v[0] - f17[0], v[1] - f17[1]) for v in e.values())
    row("A.8 r8 R106s on the tab X bottom beside F17", "R106s", "%s, %.2f mm from the F17 centre" % (side, dd),
        "tab X bottom", side == "bottom" and L.TAB_X.contains(crt("R106s", fr)))
    # tab contents
    topX = sorted(r for r, fp in FP.items() if not fp.IsFlipped() and not crt(r, fr).is_empty
                  and crt(r, fr).intersection(L.TAB_X).area > 0.01)
    row("A.8 tab X top: tap pads and R175 only", ", ".join(topX), "%d footprints" % len(topX), "F pads + R175",
        all(r == "R175" or (r.startswith("F") and r[1:].isdigit()) or r.startswith("FT") for r in topX))
    topY = sorted(r for r, fp in FP.items() if not fp.IsFlipped() and not crt(r, fr).is_empty
                  and crt(r, fr).intersection(L.TAB_Y).area > 0.01)
    row("A.8 tab Y top: driven logic only", ", ".join(topY), "%d footprints" % len(topY), "LVC gates (U105-U118 class)",
        all(r.startswith(("U10", "U11", "FT")) or r in ("U117", "U112", "D101") for r in topY))
    botX = sorted(r for r, fp in FP.items() if fp.IsFlipped() and crt(r, fr).intersection(L.TAB_X).area > 0.01)
    row("A.7/A.8 tab X bottom: 1 % logic series resistors and pull-downs only", ", ".join(botX), "%d" % len(botX),
        "R class", all(r in L.TABX_OK for r in botX))
    # region bookings (top), information
    for name, reg in (("footprint low-y band", L.BAND), ("tab Y top", L.TAB_Y.intersection(L.INSET))):
        a = sum(crt(r, fr).intersection(reg).area for r, fp in FP.items() if not fp.IsFlipped())
        row("A.8 per-region booking (KiCad courtyards, information)", name, "%.1f of %.1f mm2 = %.1f %%" %
            (a, reg.area, 100 * a / reg.area), "<= 75 % target", "info")
    ds = b.GetDesignSettings()
    row("A.8 every via tented (L4) / r8 F17-R106s rule", "board setup", "front %s, back %s" % (ds.m_TentViasFront,
                                                                                          ds.m_TentViasBack),
        "both tented", bool(ds.m_TentViasFront and ds.m_TentViasBack))
    nv = sum(1 for p in FP["U101"].Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH)
    row("A.8 U101 thermal pad >= 9 vias 0.3 mm", "U101", "%d vias" % nv, ">= 9", nv >= 9)
else:
    import layout_eib as L
    fr = pb.Frame(L.YOFF)
    row("A.9 outline", "Edge.Cuts", "%.1f x %.1f mm" % (L.W, L.H), "36.0 x 24.0 mm (D-13: 38 x 24)", "deviation D-13")
    ys = [pads_e(r, fr)["1"][1] for r in ("E8", "E3", "E4", "E2", "E7", "E1", "E5", "E6")]
    order = [r for r, _ in sorted({r: pads_e(r, fr)["1"][1] for r in L.EPOS}.items(), key=lambda kv: -kv[1])]
    row("A.9 E-pad order top to bottom", " ".join(order), "positions " + ", ".join("%.2f" % y for y in sorted(ys, reverse=True)),
        "E8 - E3 E4 E2 - E7 - E1 - E5 E6", order == ["E8", "E3", "E4", "E2", "E7", "E1", "E5", "E6"])
    span = max(ys) - min(ys)
    row("A.9 outer E-pad centres 27.94 mm", "E8-E6", "%.2f mm" % span, "27.94 mm", abs(span - 27.94) < 1e-3)
    for h, c in zip(("H1", "H2"), L.HOLES):
        e = fr.e(FP[h].GetPosition())
        row("A.9 M3 holes at diagonal corners, 3.5 mm in", h, "(%.2f, %.2f)" % e, "(%.1f, %.1f)" % c,
            math.hypot(e[0] - c[0], e[1] - c[1]) < 1e-3)
    for ref, epad in (("R276", "E1"), ("R275", "E7")):
        dd = pad_poly(ref, "1", fr).distance(pad_poly(epad, "1", fr))
        row("A.9 series resistor at its E pad", ref, "pad gap %.2f mm" % dd, "at the pad", "info")
    j = fr.e(FP["J201"].GetPosition())
    row("A.9 J201 on the opposite long edge", "J201", "x %.2f mm (E column x %.2f)" % (j[0], L.EX), "far edge", j[0] > 15)
print("| Rule (design row) | Item | Measured | Limit | Result |")
print("|---|---|---|---|---|")
print("\n".join(rows))
