"""Measure a built board against the design constraints and print a markdown table. CR: the r9 plug-on outline
(D-39 to D-52; A.2, A.8; the H.23 successor rows of cr_geometry.py). EIB: A.9, as fabricated (D-49).
Usage (pcbnew venv): python check_constraints.py <cr|eib> <projdir>
The board-independent CR rows run headless: python cr_geometry.py [<projdir>]."""
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
    # Plug-on outline (D-39), rows rebuilt in D-50 step 4 (D-52). Retired with the r7 outline: the V1-V11 outline and
    # chamfer row, the 10 mm rim rule at x <= 39.53 (D-11, re-derived as the analog-window rows below), the tab X /
    # tab Y content rows, the tab X bottom and R106s-location rows (D-16, D-17, D-32), the per-region tab bookings
    # (H.23(e2)), the W6/W7 r8 SMT coordinates (D-45) and the D-35 packer-pad scope of the r7 placement.
    import layout_cr as L
    import cr_geometry as G
    fr = pb.Frame(L.YOFF)
    # A.8 CHG hole table (pin identity, T-A-06 step 0; D-02)
    pe = pads_e("J1", fr)
    err = max(math.hypot(pe[str(n)][0] - x, pe[str(n)][1] - y) for n, (x, y) in G.CHG_TABLE.items())
    row("A.8 CHG holes, 22 pins (pin identity, D-02)", "J1", "max position error %.4f mm" % err, "0.001 mm", err < 1e-3)
    row("D-02 / D-41: CHG footprint on F.Cu (no flip)", "J1", "flipped" if FP["J1"].IsFlipped() else "F.Cu",
        "F.Cu", not FP["J1"].IsFlipped())
    # outline (D-39) read back from Edge.Cuts
    ec = [d for d in b.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    xs, ys = [], []
    for d in ec:
        for pt in (d.GetStart(), d.GetEnd()):
            e = fr.e(pt)
            xs.append(e[0])
            ys.append(e[1])
    bb = (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)
    ok = all(abs(a - b_) < 1e-3 for a, b_ in zip(bb, (G.X0, G.Y0, G.X1, G.Y1))) and len(ec) == 4
    row("D-39 plug-on outline x 18.584-67, y 7-94 (Edge.Cuts)", "Edge.Cuts", "%d segments, x %.3f-%.3f, y %.3f-%.3f"
        % ((len(ec),) + bb[0::2] + bb[1::2]), "4 segments, the D-39 rectangle", ok)
    # every part inside the outline (a part the packer could not place is parked outside it)
    out = sorted(r for r, fp in FP.items() if not r.startswith("#")
                 and not crt(r, fr).is_empty and not L.P.buffer(0.01).contains(crt(r, fr)))
    row("Every part inside the outline (packer placed all parts)", ", ".join(out) or "all", "%d outside" % len(out), "0",
        not out)
    # D-44: one SMT side
    bot = sorted(r for r, fp in FP.items() if fp.IsFlipped() and not r.startswith("#"))
    row("D-44 every SMT part on the top side", ", ".join(bot) or "none", "%d flipped" % len(bot), "0", not bot)
    smd_b = sorted("%s.%s" % (r, p.GetNumber()) for r, fp in FP.items() for p in fp.Pads()
                   if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and p.IsOnLayer(pcbnew.B_Cu))
    row("D-44 no SMD pad on B.Cu (one stencil, one reflow)", ", ".join(smd_b[:8]) or "none", "%d pads" % len(smd_b), "0",
        not smd_b)
    # D-44 / r9-3: every chip passive 0603 or larger
    small = sorted(r for r, fp in FP.items() if r[0] in "RC" and ("0402" in fp.GetFPID().GetLibItemName().wx_str()
                                                                  or "0201" in fp.GetFPID().GetLibItemName().wx_str()))
    row("D-44 chip passives >= 0603 (r9-3)", ", ".join(small) or "none", "%d below 0603" % len(small), "0", not small)
    # D-39 / D-40: IC pitch >= 0.65 mm, U101 (0.5 mm VQFN-24) the one approved exception
    for r, fp in sorted(FP.items()):
        if not r.startswith("U"):
            continue
        cs = [fr.e(p.GetPosition()) for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD
              and p.GetNumber() not in ("", "25")]   # pad 25 = the U101 exposed pad (D-40)
        pitch = min((math.hypot(a[0] - c[0], a[1] - c[1]) for i, a in enumerate(cs) for c in cs[i + 1:]),
                    default=float("nan"))
        ok = pitch >= 0.65 - 1e-3 or (r == "U101" and abs(pitch - 0.5) < 1e-3)
        if r == "U101" or pitch < 0.65 - 1e-3:
            row("D-39 IC pitch >= 0.65 mm (U101 0.5 mm approved, D-40)", r, "%.2f mm" % pitch, ">= 0.65 mm or U101",
                ok)
    others = sorted(r for r in FP if r.startswith("U") and r != "U101")
    row("D-39 IC pitch >= 0.65 mm", ", ".join(others), "%d ICs checked" % len(others), "minimum pad-centre spacing",
        "pass (rows above list any exception)")
    # D-03 amended: every CR footprint on the 0.25 mm courtyard basis
    old = sorted(r for r, fp in FP.items() if "CrtYd0.10" in fp.GetFPID().GetLibItemName().wx_str())
    row("D-03 (amended 2026-11-12) courtyard basis 0.25 mm", ", ".join(old) or "none", "%d on the 0.10 mm basis"
        % len(old), "0", not old)
    # D-37 via-in-pad listing (U101 exposed-pad vias are footprint pads, exempt by D-40)
    smd = [(r, p) for r, fp in FP.items() for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]
    vip = []
    for t in b.GetTracks():
        if t.GetClass() != "PCB_VIA":
            continue
        for r, p in smd:
            if p.HitTest(t.GetPosition()):
                vip.append("%s.%s" % (r, p.GetNumber()))
    row("D-37 via in an SMD pad (fallback only; each listed for operator review)", ", ".join(sorted(vip)) or "none",
        "%d vias" % len(vip), "0 unless listed", "info" if vip else True)
    # D-20 (amended): L4 solid GND, no signal or strap track on B.Cu
    l4 = sum(1 for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetLayer() == pcbnew.B_Cu)
    l4z = sorted({z.GetNetname() for z in b.Zones() if not z.GetIsRuleArea() and z.IsOnLayer(pcbnew.B_Cu)})
    row("D-20 L4 (B.Cu): no tracks, GND pour only", "B.Cu", "%d tracks; pour nets %s" % (l4, ", ".join(l4z) or "none"),
        "0 tracks; /GND only", l4 == 0 and all(n == "/GND" for n in l4z))
    # fixed pads (A.8; D-45 kept W1-W4 positions pending the step-5 D-08 re-derivation)
    for ref, (x, y) in {"W1": (30.3, 61.2), "W2": (27.7, 61.2), "W3": (24.3, 45.4), "W4": (24.3, 55.6)}.items():
        e = pads_e(ref, fr)["1"]
        row("A.8 W1-W4 lead pads (D-45; D-08 re-derived at placement)", ref, "(%.3f, %.3f)" % e, "(%.2f, %.2f)" % (x, y),
            math.hypot(e[0] - x, e[1] - y) < 1e-3)
    for ref, n in (("W6", 2), ("W7", 3)):
        fp = FP.get(ref)
        np_ = sum(1 for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH) if fp else 0
        row("D-45 W6/W7 plated through-hole lead pads (PLACEHOLDER geometry)", ref, "%d PTH pads" % np_, "%d" % n,
            np_ == n)
    # D-46 J-TAP
    jt = FP.get("J102")
    npads = sum(1 for p in jt.Pads() if p.GetNumber()) if jt else 0
    row("D-46 J-TAP header, Micro-Fit 3.0 2 x 5", "J102", "%d pads" % npads, "10 cavities", bool(jt) and npads == 10)
    if jt:
        c = crt("J102", fr)
        row("D-46 J-TAP on the +x side of the CR (courtyard in the +x half, x >= %.3f)" % G.X_MID, "J102",
            "courtyard x %.2f-%.2f, y %.2f-%.2f" % (c.bounds[0], c.bounds[2], c.bounds[1], c.bounds[3]),
            "x min >= %.3f" % G.X_MID, c.bounds[0] >= G.X_MID - 1e-6)
        jp = pads_e("J102", fr)
        for pad in sorted(G.JTAP, key=int):
            tap, xy, mx = G.far_end(pad)
            d = math.hypot(jp[pad][0] - xy[0], jp[pad][1] - xy[1])
            row("H.23(l) successor: J-TAP straight-line run (lower bound of the dressed run; A.4 maximum)",
                "%s J102.%s -> %s.%s" % (tap, pad, G.JTAP[pad][1], G.JTAP[pad][2]), "%.1f mm" % d,
                "<= %.0f mm" % mx, d <= mx)
        row("D-46 J-TAP latch finger access", "J102", "latch side not modelled",
            "TODO(verify: Molex 43045 header drawing)", "info")
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
    # D-20 sensitive-part window and the D-11 interim 10 mm rim (successor of the x <= 39.53 rim rule)
    strict = G.analog_window().buffer(1e-3)   # the window itself (the placement regions also cut the U101 loop)
    for ref in L.ANALOG_ICS + L.DIVIDERS + ["R102"]:
        if ref not in FP:
            continue
        g = crt(ref, fr)
        row("D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (preferred; exemption if outside)", ref,
            "inside" if strict.contains(g) else "outside: courtyard x %.2f-%.2f, y %.2f-%.2f" % (
                g.bounds[0], g.bounds[2], g.bounds[1], g.bounds[3]),
            "inside", True if strict.contains(g) else "exemption (D-20)")
    # divider-top rule (A.8 Analog; D-35 scope, D-36: an all-layer metric, not a gate): logic-IC signal pads within
    # 2.0 mm of the divider tops R102, R109, R111, R114 (the r7 packer-pad interim exemptions retire with the r7
    # placement)
    def _pbox(p):
        bb_ = p.GetBoundingBox()
        return box(pcbnew.ToMM(bb_.GetLeft()), L.YOFF - pcbnew.ToMM(bb_.GetBottom()), pcbnew.ToMM(bb_.GetRight()),
                   L.YOFF - pcbnew.ToMM(bb_.GetTop()))
    hull = unary_union([_pbox(p).convex_hull for r in ("R102", "R109", "R111", "R114") if r in FP
                        for p in FP[r].Pads()])
    near = ["%s.%s %s %.2f" % (r, p.GetNumber(), p.GetNetname(), _pbox(p).distance(hull))
            for r in L.LOGIC_ICS if r in FP for p in FP[r].Pads()
            if p.GetNetname().startswith("/") and p.GetNetname() not in ("/GND", "/3V3")
            and _pbox(p).distance(hull) < 2.0]
    row("D-35 / D-36 logic-IC pads within 2.0 mm of the divider tops (metric, F.Cu pads)", "; ".join(near) or "none",
        "%d pads" % len(near), "metric: lower is better (D-36)", "info")
    # dividers in the divider strip (A.8 / D-13)
    strip = box(23.15, 42.14, 36.50, 45.69)
    for ref in ("R109", "R110", "R111", "R112", "R114", "R115"):
        row("A.8 divider strip x 23.15-36.50, y 42.14-45.69", ref, "inside" if strip.buffer(1e-3).contains(crt(ref, fr))
            else "outside", "inside", strip.buffer(1e-3).contains(crt(ref, fr)))
    # distance of analog parts from the U101 loop region
    for ref in ("U102", "U103", "U119", "U120", "D104", "D105", "D106"):
        dd = crt(ref, fr).distance(L.LOOP)
        row("H.23(f) distance from the U101 loop region (information)", ref, "%.2f mm" % dd, ">= 3.0 mm (region rule)",
            "info")
    # H.23(e) successor: whole-side booking on the placed board
    a = sum(crt(r, fr).area for r, fp in FP.items() if not fp.IsFlipped() and not crt(r, fr).is_empty)
    row("H.23(e) successor: top-side courtyard booking (KiCad courtyards, information)", "top",
        "%.1f of %.1f mm2 = %.1f %%" % (a, L.INSET.area, 100 * a / L.INSET.area), "<= 75 % target", "info")
    ds = b.GetDesignSettings()
    row("D-20 every via tented on both sides", "board setup", "front %s, back %s" % (ds.m_TentViasFront,
                                                                               ds.m_TentViasBack),
        "both tented", bool(ds.m_TentViasFront and ds.m_TentViasBack))
    nv = sum(1 for p in FP["U101"].Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH)
    row("A.8 U101 thermal pad >= 9 vias 0.3 mm (D-40 exempt from D-37)", "U101", "%d vias" % nv, ">= 9", nv >= 9)
    # geometry rows that do not need the board (terminal clearance D-51, rotated key, CHG columns, J-TAP region)
    for gr in G.rows():
        rows.append("| %s | %s | %s | %s | %s |" % (gr["rule"], gr["item"], gr["measured"], gr["limit"],
                                                     gr["result"]))
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
