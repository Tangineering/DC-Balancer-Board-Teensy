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
from shapely.geometry import LineString, Polygon, box, Point
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
    from shapely.ops import polygonize
    edge_poly = unary_union(list(polygonize(unary_union([LineString([fr.e(d.GetStart()), fr.e(d.GetEnd())])
                                                         for d in ec]))))
    TRIMMED = len(ec) != 4      # D-60: the routed board is trimmed by gen/trim_cr.py; before the trim it is the D-39 box
    if not TRIMMED:
        ok = all(abs(a - b_) < 1e-3 for a, b_ in zip(bb, (G.X0, G.Y0, G.X1, G.Y1)))
        row("D-39 plug-on outline x 18.584-67, y 7-94 (Edge.Cuts; placement frame, before the D-60 trim)", "Edge.Cuts",
            "%d segments, x %.3f-%.3f, y %.3f-%.3f" % ((len(ec),) + bb[0::2] + bb[1::2]), "4 segments, the D-39 rectangle",
            ok)
    else:
        dev = edge_poly.symmetric_difference(G.P_FINAL).area
        row("D-60 final outline (Edge.Cuts) = cr_geometry.FINAL_OUTLINE, inside the D-39 rectangle", "Edge.Cuts",
            "%d segments, x %.3f-%.3f, y %.3f-%.3f, area %.1f mm2; area differing from FINAL_OUTLINE %.4f mm2" % (
                (len(ec),) + bb[0::2] + bb[1::2] + (edge_poly.area, dev)),
            "%d segments; difference < 0.01 mm2" % len(G.FINAL_OUTLINE),
            len(ec) == len(G.FINAL_OUTLINE) and dev < 0.01 and G.P.buffer(0.01).contains(edge_poly))
        for h, (x, y) in G.MOUNTING_HOLES.items():
            fp = FP.get(h)
            got = "missing"
            ok = False
            if fp is not None:
                pd = list(fp.Pads())
                e = fr.e(fp.GetPosition())
                got = "(%.2f, %.2f), %d pad, %s, drill %.2f mm" % (
                    e[0], e[1], len(pd), "NPTH" if pd and pd[0].GetAttribute() == pcbnew.PAD_ATTRIB_NPTH else "not NPTH",
                    pcbnew.ToMM(pd[0].GetDrillSizeX()) if pd else 0)
                ok = (len(pd) == 1 and pd[0].GetAttribute() == pcbnew.PAD_ATTRIB_NPTH and
                      abs(pcbnew.ToMM(pd[0].GetDrillSizeX()) - G.HOLE_DRILL) < 1e-3 and math.hypot(e[0] - x, e[1] - y) < 0.01)
            kz = [z for z in b.Zones() if z.GetIsRuleArea() and z.GetZoneName() == h + "_keepout"]
            row("D-60 6-32 mounting hole on the board (NPTH %.2f mm) with its all-layer keep-out" % G.HOLE_DRILL, h,
                got + ("; keep-out zone present" if kz else "; keep-out zone MISSING"),
                "(%.2f, %.2f), NPTH %.2f mm, keep-out r %.1f mm" % (x, y, G.HOLE_DRILL, G.HOLE_KEEPOUT), ok and bool(kz))
    BOARD_P = edge_poly if TRIMMED else L.P
    # every part inside the outline (a part the packer could not place is parked outside it)
    out = sorted(r for r, fp in FP.items() if not r.startswith("#")
                 and not crt(r, fr).is_empty and not BOARD_P.buffer(0.01).contains(crt(r, fr)))
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
    # D-55 (review M-2): the via annulus (not only its centre) is tested against the pad copper grown by the pad's
    # solder-mask expansion, on the layer of the pad. Superseded: a HitTest of the via centre only.
    smd = []
    for r, fp in FP.items():
        for p in fp.Pads():
            if p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
            for lay, mlay in ((pcbnew.F_Cu, pcbnew.F_Mask), (pcbnew.B_Cu, pcbnew.B_Mask)):
                if not p.IsOnLayer(lay):
                    continue
                sps = p.GetEffectivePolygon(lay, pcbnew.ERROR_INSIDE)
                g = unary_union([Polygon([fr.e(sps.Outline(i).CPoint(k)) for k in range(sps.Outline(i).PointCount())])
                                 for i in range(sps.OutlineCount())])
                exp = pcbnew.ToMM(p.GetSolderMaskExpansion(mlay)) if p.IsOnLayer(mlay) else 0.0
                smd.append((r, p.GetNumber(), g.buffer(max(exp, 0.0), join_style=2)))
    vip, vgap = [], []
    for t in b.GetTracks():
        if t.GetClass() != "PCB_VIA":
            continue
        ann = Point(fr.e(t.GetPosition())).buffer(pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)) / 2, 64)
        for r, num, g in smd:
            if ann.intersects(g):
                vip.append("%s.%s" % (r, num))
            else:
                vgap.append(ann.distance(g))
    row("D-37 via annulus on an SMD pad or its mask opening (fallback only; each listed for operator review)",
        ", ".join(sorted(vip)) or "none", "%d vias; smallest annulus gap to a pad + mask %.3f mm" % (
            len(vip), min(vgap) if vgap else float("nan")), "0 unless listed", "info" if vip else True)
    # D-55 (review M-2): C102b-end VCHGIN vias against the A.8 IN-strip row ("6 vias each end") and D-21 (five)
    c2 = pad_poly("C102b", "1", fr).centroid
    nvb = sum(1 for t in b.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetname() == "/VCHGIN"
              and Point(fr.e(t.GetPosition())).distance(c2) < 3.0)
    row("A.8 IN strip: VCHGIN vias at the C102b end (A.8 6 each end; D-21 five)", "C102b pad 1", "%d vias within 3 mm"
        % nvb, ">= 6", nvb >= 6)
    # D-20 (amended): L4 solid GND, no signal or strap track on B.Cu
    l4 = sum(1 for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetLayer() == pcbnew.B_Cu)
    l4z = sorted({z.GetNetname() for z in b.Zones() if not z.GetIsRuleArea() and z.IsOnLayer(pcbnew.B_Cu)})
    row("D-20 L4 (B.Cu): no tracks, GND pour only", "B.Cu", "%d tracks; pour nets %s" % (l4, ", ".join(l4z) or "none"),
        "0 tracks; /GND only", l4 == 0 and all(n == "/GND" for n in l4z))
    # fixed pads (A.8; D-45 kept W1-W4 positions pending the step-5 D-08 re-derivation)
    # W2 x 27.7 -> 27.2 (D-55, review m-1; D-08 re-derived)
    for ref, (x, y) in {"W1": (30.3, 61.2), "W2": (27.2, 61.2), "W3": (24.3, 45.4), "W4": (24.3, 55.6)}.items():
        e = pads_e(ref, fr)["1"]
        row("A.8 W1-W4 lead pads (D-45; D-08 re-derived at placement; W2 D-55)", ref, "(%.3f, %.3f)" % e,
            "(%.2f, %.2f)" % (x, y), math.hypot(e[0] - x, e[1] - y) < 1e-3)
    dd = pad_poly("W1", "1", fr).distance(pad_poly("W2", "1", fr))
    ov = crt("W1", fr).intersection(crt("W2", fr)).area
    row("D-55 (m-1) W1 (VCHGOUT) to W2 (GND) pad gap and courtyard overlap", "W1-W2",
        "pad gap %.3f mm; courtyard overlap %.3f mm2" % (dd, ov), ">= 0.5 mm; 0 mm2", dd >= 0.5 and ov < 1e-6)
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
    # D-55 (review B-1): the U101 network, centre to centre from the part pad on the node to the U101 pin it serves.
    up = pads_e("U101", fr)
    for ref, pad, pin, node in (("R101", "1", "10", "ILIM"), ("C101", "1", "9", "dVdT"), ("R103", "2", "7", "OVP"),
                                ("R104", "1", "7", "OVP"), ("R105", "1", "13", "IMON"), ("R129", "1", "13", "IMON")):
        if ref not in FP:
            continue
        q = pads_e(ref, fr)[pad]
        dd = math.hypot(q[0] - up[pin][0], q[1] - up[pin][1])
        row("A.8 %s node within 5 mm of U101 pins 7-13 (pad to pin, centre to centre; D-55)" % node,
            "%s.%s -> U101.%s" % (ref, pad, pin), "%.2f mm" % dd, "<= 5 mm", dd <= 5.0)
    q = pads_e("R103", fr)["1"]
    dd = math.hypot(q[0] - up["6"][0], q[1] - up["6"][1])
    row("A.8 N_UV: R103 to U101 pin 6 (information; pin 6 is outside pins 7-13)", "R103.1 -> U101.6", "%.2f mm" % dd,
        "information", "info")
    q = pads_e("R106s", fr)["1"]
    dd = math.hypot(q[0] - up["14"][0], q[1] - up["14"][1])
    row("A.8 (r9-3) R106s as near to U101 pin 14 as the courtyard check allows (D-55)", "R106s.1 -> U101.14",
        "%.2f mm" % dd, "<= 5 mm (target; r6 pocket figure)", dd <= 5.0)
    # D-55 (review B-1, m-4): straight-line ratsnest crossings of the CHG +x pin column. Per net (all nets except /GND,
    # the plane, and the single-pin nets), a minimum spanning tree over the pad centres; an edge counts when it
    # meets the column copper envelope (pins 1-10, x 45.048-46.948, y 38.134-62.894) and neither end is a column pad.
    from shapely.geometry import LineString
    colbox = box(45.998 - 0.95, 39.084 - 0.95, 45.998 + 0.95, 61.944 + 0.95)
    netpts = {}
    for r, fp in FP.items():
        for p in fp.Pads():
            n = p.GetNetname()
            if n and n != "/GND" and not n.startswith("unconnected-"):
                netpts.setdefault(n, []).append(fr.e(p.GetPosition()))
    cross = []
    for n, pts in sorted(netpts.items()):
        if len(pts) < 2:
            continue
        inside, edges = {0}, []
        while len(inside) < len(pts):
            d, i, j = min((math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]), i, j)
                          for i in inside for j in range(len(pts)) if j not in inside)
            inside.add(j)
            edges.append((pts[i], pts[j]))
        for a, c in edges:
            if colbox.contains(Point(a)) or colbox.contains(Point(c)):
                continue
            if LineString([a, c]).intersects(colbox):
                cross.append(n)
    row("D-55 (B-1, m-4) ratsnest edges crossing the CHG +x pin column (MST per net, straight line)",
        ", ".join(cross) or "none", "%d edges" % len(cross), "0", not cross)
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
    # D-55 (review m-2): R103 and R104 (0.1 % eFuse UV/OV divider) are listed exemptions with the reason of R102:
    # U101's own network, held within 5 mm of pins 6-7 by A.8. R129 (IMON node) and C129 (CHG_IIN filter) are
    # U101-network parts since D-55; R129 sits in pocket row 3 above the window top (A.8 IMON <= 5 mm binds; the two
    # window rows hold R104 and R103), a listed exemption that replaces the D-54 item-7 deviation.
    # D-56 (review r9b N-4): R103 and R104 exchange rows. Row 1 (y 64.20) is outside the window (rim distance), row 2
    # inside, so the listed exemption moves from R104 to R103; both stay listed, and a part inside passes.
    for ref, why in (("R103", "listed exemption: U101 network, A.8 <= 5 mm (D-55, D-56)"),
                     ("R104", "listed exemption: U101 network, A.8 <= 5 mm (D-55)"),
                     ("R129", "listed exemption: U101 network, A.8 IMON <= 5 mm (D-55)"),
                     ("C129", "deviation: outside the window (D-55)")):
        if ref not in FP:
            continue
        g = crt(ref, fr)
        ins = strict.contains(g)
        row("D-20 window y 30.8-66.86 and >= 10 mm from the MB 5V copper rim (U101 network and CHG_IIN filter)", ref,
            "inside" if ins else "outside: courtyard x %.2f-%.2f, y %.2f-%.2f" % (g.bounds[0], g.bounds[2],
                                                                                 g.bounds[1], g.bounds[3]),
            "inside", True if ins else why)
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
    dd = pad_poly("R110", "1", fr).distance(Point(pads_e("W3", fr)["1"]).buffer(1.25, 64))
    row("D-55 (m-3) W3 18 AWG joint to the R110 0.1 % divider pad (pad gap; information)", "W3 - R110.1",
        "%.2f mm" % dd, "information (r9 step 5: 0.78 mm)", "info")
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
    # D-55 (review M-1): window-pane paste apertures clear every thermal-via drill; coverage of the 2.7 mm pad
    drills = [Point(fr.e(p.GetPosition())).buffer(pcbnew.ToMM(p.GetDrillSizeX()) / 2, 64) for p in FP["U101"].Pads()
              if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
    aps = []
    for p in FP["U101"].Pads():
        if p.IsOnLayer(pcbnew.F_Paste) and not p.IsOnLayer(pcbnew.F_Cu):
            bb_ = p.GetBoundingBox()
            aps.append(box(pcbnew.ToMM(bb_.GetLeft()), L.YOFF - pcbnew.ToMM(bb_.GetBottom()),
                           pcbnew.ToMM(bb_.GetRight()), L.YOFF - pcbnew.ToMM(bb_.GetTop())))
    gap = min(a.distance(d) for a in aps for d in drills) if aps and drills else float("nan")
    cov = 100 * unary_union(aps).area / (2.7 * 2.7) if aps else 0.0
    row("D-40 / A.8 U101 exposed-pad paste apertures clear of every via drill (window pane; D-55)", "U101.25",
        "%d apertures; smallest gap to a drill %.3f mm; coverage %.1f %%" % (len(aps), gap, cov),
        "gap >= 0.15 mm (D-56, N-6); coverage TODO(verify: SLVSE94G section 11, stencil vendor)", gap >= 0.15 - 1e-4)
    # D-56 (review r9b N-7): F.Cu escape of the U101 network pads and the U101 ground pads of C102c and C103. Method of
    # cr/placement_review_r9b.md section 1: obstacles are the F.Cu fill of every pour of another net (the /GND fills
    # excepted: /GND is the plane net and the router cuts it), every F.Cu pad, track and via of another net and every
    # F.Cu keep-out that forbids tracks, each grown by the Default clearance plus half the Default track
    # (route_cr.CLEAR + route_cr.TRACK / 2). The free space is the outline less the route_cr.EDGE_BAND band less the
    # grown obstacles. A pad passes when the free component(s) that touch it reach another same-net pad or via, or
    # hold a 0.6 mm via site: a point off every SMD pad plus its mask expansion plus the via radius (D-37), at least
    # via radius + clearance from every other-net obstacle on F.Cu and from every non-/GND pour fill of another net on
    # the inner layers and B.Cu (hard pours), >= 0.127 mm hole to hole from every drill, and inside the edge band.
    import route_cr as RC

    def _sps(sps):
        polys = []
        for i in range(sps.OutlineCount()):
            o = sps.Outline(i)
            ext = [fr.e(o.CPoint(k)) for k in range(o.PointCount())]
            holes = [[fr.e(sps.Hole(i, j).CPoint(k)) for k in range(sps.Hole(i, j).PointCount())]
                     for j in range(sps.HoleCount(i))]
            if len(ext) >= 3:
                polys.append(Polygon(ext, [h for h in holes if len(h) >= 3]).buffer(0))
        return unary_union(polys)

    def _pad_geom(p, lay):
        return _sps(p.GetEffectivePolygon(lay, pcbnew.ERROR_INSIDE)).union(
            Point(fr.e(p.GetPosition())).buffer(pcbnew.ToMM(p.GetDrillSizeX()) / 2, 32)
            if p.GetDrillSizeX() > 0 else Polygon())

    grow = RC.CLEAR + RC.TRACK / 2
    vr = RC.VIA[0] / 2
    lays = {"F": pcbnew.F_Cu, "In1": pcbnew.In1_Cu, "In2": pcbnew.In2_Cu, "B": pcbnew.B_Cu}
    fills = {k: [] for k in lays}   # (net, geometry) of every non-rule-area zone fill, per layer
    for z in b.Zones():
        if z.GetIsRuleArea():
            continue
        for k, lay in lays.items():
            if z.IsOnLayer(lay) and z.HasFilledPolysForLayer(lay):
                fills[k].append((z.GetNetname(), _sps(z.GetFilledPolysList(lay))))
    keepf = unary_union([_sps(z.Outline()) for z in b.Zones() if z.GetIsRuleArea() and z.IsOnLayer(pcbnew.F_Cu)
                         and z.GetDoNotAllowTracks() and z.GetZoneName() != "edge_band_router"])
    fpads = [(fp.GetReference(), p.GetNumber(), p.GetNetname(), _pad_geom(p, pcbnew.F_Cu))
             for fp in b.GetFootprints() for p in fp.Pads() if p.IsOnLayer(pcbnew.F_Cu)]
    vias = [(t.GetNetname(), Point(fr.e(t.GetPosition())), pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)) / 2)
            for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]
    trks = [(t.GetNetname(), LineString([fr.e(t.GetStart()), fr.e(t.GetEnd())]).buffer(pcbnew.ToMM(t.GetWidth()) / 2))
            for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetLayer() == pcbnew.F_Cu]
    drills = [Point(fr.e(p.GetPosition())).buffer(pcbnew.ToMM(p.GetDrillSizeX()) / 2, 32) for fp in b.GetFootprints()
              for p in fp.Pads() if p.GetDrillSizeX() > 0] + [c.buffer(RC.VIA[1] / 2, 32) for _, c, _ in vias]
    smd_mask = unary_union([g for _, _, g in smd])   # every SMD pad plus its mask expansion (D-37 row above)
    inset = BOARD_P.buffer(-RC.EDGE_BAND, join_style=2)          # D-60: the final outline once trimmed
    via_inset = BOARD_P.buffer(-(RC.EDGE_BAND + vr), join_style=2)

    def escape(ref, num):
        me = [q for q in fpads if q[0] == ref and q[1] == num][0]
        net, pg = me[2], me[3]
        obs = [g for n, g in fills["F"] if n != net and n != "/GND"]
        obs += [g for r, nm, n, g in fpads if n != net]
        obs += [g for n, g in trks if n != net]
        obs += [c.buffer(rad, 32) for n, c, rad in vias if n != net]
        raw = unary_union(obs + [keepf])
        free = inset.difference(raw.buffer(grow, 16))
        comps = [c for c in getattr(free, "geoms", [free]) if not c.is_empty and c.intersects(pg)]
        comp = unary_union(comps)
        reach = sorted({"%s.%s" % (r, nm) for r, nm, n, g in fpads if n == net and (r, nm) != (ref, num)
                        and g.intersects(comp)} | {"via(%.2f,%.2f)" % (c.x, c.y) for n, c, rad in vias
                                                    if n == net and c.distance(comp) < 1e-6})
        # via site inside the component (F.Cu), clear on the other layers (hard non-/GND pours of another net)
        site = comp.intersection(via_inset).difference(raw.buffer(vr + RC.CLEAR, 16)).difference(
            smd_mask.buffer(vr, 16))
        hard = unary_union([g for k in ("In1", "In2", "B") for n, g in fills[k] if n != net and n != "/GND"])
        site = site.difference(hard.buffer(vr + RC.CLEAR, 16)).difference(
            unary_union(drills).buffer(RC.VIA[1] / 2 + 0.127, 16))
        from shapely.ops import nearest_points
        sp = nearest_points(site, pg)[0] if not site.is_empty else None   # the via site nearest the pad
        ok = bool(reach) or sp is not None
        meas = "free %.2f mm2; reaches %s; via site %s" % (
            comp.area, ", ".join(reach[:4]) + (" +%d" % (len(reach) - 4) if len(reach) > 4 else "") if reach
            else "no same-net pad", "(%.2f, %.2f), %.2f mm from the pad" % (sp.x, sp.y, sp.distance(pg))
            if sp is not None else "none")
        return net, meas, ok

    for ref, num in (("U101", "6"), ("U101", "7"), ("U101", "9"), ("U101", "10"), ("U101", "13"), ("U101", "14"),
                     ("R102", "2"), ("C102c", "2"), ("C103", "2")):
        if ref not in FP:
            continue
        net, meas, ok = escape(ref, num)
        row("D-56 (r9b N-7) F.Cu escape: a %.4f mm track leaves the pad to a same-net pad or a 0.6 mm via site "
            "(hard pours, other-net copper, keep-outs)" % RC.TRACK, "%s.%s %s" % (ref, num, net), meas,
            "reaches a same-net pad/via or holds a via site", ok)
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
