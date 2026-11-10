"""Independent check of H.23 items 1-4, 8, 10 (outline, clearances, under-tab content, bottom-rule area, feet,
r6 sheet vs CO-5V, loop distance). Stdlib only; written without reference to r7_calc.py."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brdgeo import (Board, d_pt_seg, d_seg_poly_region, d_poly_poly, d_pt_poly_region, pip, rect_poly,  # noqa
                    shoelace, d_rect_rect, edges)

B = Board()
print("BRD", os.path.basename(__import__("brdgeo").BRD))
print("MB outline bbox", B.outline_bbox, "holes", B.holes)
print("via dia", round(B.via_dia(0.35), 4), "CHG pad dia (1.1 drill)", round(B.pad_dia(1.1), 4))

# ---------------------------------------------------------------- 1. outline (BASIS D1, section 1)
R6 = (17.70, 34.14, 48.70, 67.14)
TABX = [(48.70, 56.30), (65.00, 56.30), (65.00, 68.30), (48.70, 68.30)]
TABY = [(17.70, 67.14), (37.56, 67.14), (37.56, 76.00), (18.70, 76.00), (17.70, 75.00)]
R7 = [(17.70, 34.14), (48.70, 34.14), (48.70, 56.30), (65.00, 56.30), (65.00, 68.30), (48.70, 68.30),
      (48.70, 67.14), (37.56, 67.14), (37.56, 76.00), (18.70, 76.00), (17.70, 75.00)]
print("\n[1] r7 outline area (shoelace) %.3f mm2; r6 rect %.3f; tab X %.3f; tab Y (with chamfer) %.3f" % (
    shoelace(R7), (R6[2] - R6[0]) * (R6[3] - R6[1]), shoelace(TABX), shoelace(TABY)))
# free edges of each tab (edges of R7 that bound the tab)
FREE_X = [((48.70, 56.30), (65.00, 56.30)), ((65.00, 56.30), (65.00, 68.30)), ((65.00, 68.30), (48.70, 68.30)),
          ((48.70, 68.30), (48.70, 67.14))]
FREE_Y = [((37.56, 67.14), (37.56, 76.00)), ((37.56, 76.00), (18.70, 76.00)), ((18.70, 76.00), (17.70, 75.00)),
          ((17.70, 75.00), (17.70, 67.14))]

# ---------------------------------------------------------------- feature list
feats = []   # (kind, net, label, geom, halfwidth)
for w in B.wires:
    if w["layer"] == "1" and w["net"] != "GND":
        feats.append(("trace", w["net"], "%s L1 trace w%.3f (%.2f,%.2f)-(%.2f,%.2f)" % (
            w["net"], w["w"], w["a"][0], w["a"][1], w["b"][0], w["b"][1]), ("seg", w["a"], w["b"]), w["w"] / 2))
for p in B.polys:
    if p["layer"] == "1" and p["net"] != "GND":
        xs = [q[0] for q in p["pts"]]
        ys = [q[1] for q in p["pts"]]
        feats.append(("poly", p["net"], "%s L1 polygon w%.3f bbox (%.2f,%.2f)-(%.2f,%.2f)" % (
            p["net"], p["w"], min(xs), min(ys), max(xs), max(ys)), ("poly", p["pts"]), p["w"] / 2))
for v in B.vias:
    if v["net"] != "GND":
        feats.append(("via", v["net"], "%s via (%.3f,%.3f) d%.4f" % (v["net"], v["x"], v["y"], v["dia"]),
                      ("pt", (v["x"], v["y"])), v["dia"] / 2))
for en, e in B.els.items():
    for pn, pd in e["pads"].items():
        net = B.padnet.get((en, pn))
        if net in (None, "GND"):
            continue
        if pd["kind"] == "smd" and pd["layer"] != "1":
            continue
        if pd["kind"] == "smd":
            feats.append(("pad", net, "%s pad %s %s smd" % (en, pn, net), ("poly", rect_poly(pd["bb"])), 0.0))
        else:
            if pd["shape"] == "square":
                feats.append(("pad", net, "%s pad %s %s tht sq%.3f" % (en, pn, net, pd["dia"]),
                              ("poly", rect_poly(pd["bb"])), 0.0))
            else:
                feats.append(("pad", net, "%s pad %s %s tht d%.3f (%s)" % (en, pn, net, pd["dia"], pd["shape"]),
                              ("pt", (pd["x"], pd["y"])), pd["dia"] / 2))
parts = [(en, e) for en, e in B.els.items() if en != "CHG"]


def dist_feat(geom, poly):
    if geom[0] == "seg":
        return d_seg_poly_region(geom[1], geom[2], poly)
    if geom[0] == "pt":
        return d_pt_poly_region(geom[1], poly)
    return d_poly_poly(geom[1], poly)


def dist_feat_free(geom, free):
    """distance from the feature centre-geometry to the free edges only"""
    out = 1e9
    for a, b in free:
        if geom[0] == "seg":
            from brdgeo import d_seg_seg
            out = min(out, d_seg_seg(geom[1], geom[2], a, b))
        elif geom[0] == "pt":
            out = min(out, d_pt_seg(geom[1], a, b))
        else:
            from brdgeo import d_seg_seg
            out = min(out, min(d_seg_seg(c, d, a, b) for c, d in edges(geom[1])))
    return out


R6P = rect_poly(R6)
for tname, tab, free in (("tab X", TABX, FREE_X), ("tab Y", TABY, FREE_Y)):
    print("\n[1/2] %s: features within 3 mm (rim clearance = distance to the tab region - half width; "
          "'UNDER' = centre geometry overlaps the tab)" % tname)
    rows = []
    for kind, net, lab, geom, hw in feats:
        d = dist_feat(geom, tab)
        if d - hw < 3.0:
            under = d == 0.0
            dfree = dist_feat_free(geom, free) - hw
            in_r6 = dist_feat(geom, R6P) == 0.0
            rows.append((d - hw, lab, under, dfree, in_r6))
    for en, e in parts:
        bx = e["box"]
        d = d_poly_poly(rect_poly(bx), tab)
        if d < 3.0:
            rows.append((d, "PART %s box (%.2f,%.2f)-(%.2f,%.2f) body %s" % (
                en, bx[0], bx[1], bx[2], bx[3], None if e["body"] is None else
                "(%.2f,%.2f)-(%.2f,%.2f) bodyclr %.3f" % (e["body"] + (d_poly_poly(rect_poly(e["body"]), tab),))),
                d == 0.0, d, False))
    rows.sort(key=lambda r: r[0])
    for r in rows:
        print("  %7.3f  %-6s free-edge rim %7.3f  %s%s" % (r[0], "UNDER" if r[2] else "", r[3], r[1],
                                                           "  [touches r6 rect]" if r[4] else ""))

# ---------------------------------------------------------------- 2. copper area by net under each tab (raster)
def raster_net_area(tab, res=0.02):
    xs = [p[0] for p in tab]
    ys = [p[1] for p in tab]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    nx, ny = int(round((x1 - x0) / res)), int(round((y1 - y0) / res))
    inside = bytearray(nx * ny)
    for j in range(ny):
        y = y0 + (j + 0.5) * res
        for i in range(nx):
            if pip((x0 + (i + 0.5) * res, y), tab):
                inside[j * nx + i] = 1
    nets = {}
    allm = bytearray(nx * ny)
    for kind, net, lab, geom, hw in feats:
        if dist_feat(geom, tab) - hw > 0:
            continue
        m = nets.setdefault(net, bytearray(nx * ny))
        if geom[0] == "seg":
            gx = [geom[1][0], geom[2][0]]
            gy = [geom[1][1], geom[2][1]]
        elif geom[0] == "pt":
            gx = [geom[1][0]] * 2
            gy = [geom[1][1]] * 2
        else:
            gx = [q[0] for q in geom[1]]
            gy = [q[1] for q in geom[1]]
        i0 = max(0, int((min(gx) - hw - x0) / res) - 1)
        i1 = min(nx, int((max(gx) + hw - x0) / res) + 2)
        j0 = max(0, int((min(gy) - hw - y0) / res) - 1)
        j1 = min(ny, int((max(gy) + hw - y0) / res) + 2)
        for j in range(j0, j1):
            y = y0 + (j + 0.5) * res
            for i in range(i0, i1):
                k = j * nx + i
                if not inside[k]:
                    continue
                p = (x0 + (i + 0.5) * res, y)
                if geom[0] == "seg":
                    dd = d_pt_seg(p, geom[1], geom[2])
                elif geom[0] == "pt":
                    dd = math.hypot(p[0] - geom[1][0], p[1] - geom[1][1])
                else:
                    dd = d_pt_poly_region(p, geom[1])
                if dd <= hw:
                    m[k] = 1
                    allm[k] = 1
    cell = res * res
    return sum(inside) * cell, {n: sum(m) * cell for n, m in nets.items()}, sum(allm) * cell


for tname, tab in (("tab X", TABX), ("tab Y", TABY)):
    a, per, tot = raster_net_area(tab)
    print("\n[2] %s region %.2f mm2; non-GND copper rim area by net: %s; union %.2f mm2" % (
        tname, a, {k: round(v, 2) for k, v in sorted(per.items())}, tot))
    ov = [en for en, e in parts if d_poly_poly(rect_poly(e["box"]), tab) == 0.0]
    print("    MB part boxes overlapping:", ov or "none")
    vu = [(v["net"], v["x"], v["y"]) for v in B.vias if d_pt_poly_region((v["x"], v["y"]), tab) < v["dia"] / 2]
    print("    vias whose pad overlaps (%d):" % len(vu), vu)

# ---------------------------------------------------------------- 3. bottom clearance rule area (rim + 1.0 mm)
def bottom_area(region_test, bbox, keepouts=(), res=0.05, grow=1.0):
    x0, y0, x1, y1 = bbox
    nx, ny = int(round((x1 - x0) / res)), int(round((y1 - y0) / res))
    near_feats = []
    for kind, net, lab, geom, hw in feats:
        if dist_feat(geom, rect_poly(bbox)) - hw <= grow + 0.01:
            near_feats.append((geom, hw))
    near_parts = [e["box"] for en, e in parts if d_rect_rect(e["box"], bbox) <= grow + 0.01]
    free = 0
    tot = 0
    for j in range(ny):
        y = y0 + (j + 0.5) * res
        for i in range(nx):
            x = x0 + (i + 0.5) * res
            if not region_test(x, y):
                continue
            tot += 1
            p = (x, y)
            blocked = False
            for b in near_parts:
                if b[0] - grow <= x <= b[2] + grow and b[1] - grow <= y <= b[3] + grow:
                    blocked = True
                    break
            if not blocked:
                for geom, hw in near_feats:
                    if geom[0] == "seg":
                        dd = d_pt_seg(p, geom[1], geom[2])
                    elif geom[0] == "pt":
                        dd = math.hypot(x - geom[1][0], y - geom[1][1])
                    else:
                        dd = d_pt_poly_region(p, geom[1])
                    if dd <= hw + grow:
                        blocked = True
                        break
            if not blocked:
                for k in keepouts:
                    if k[0] <= x <= k[2] and k[1] <= y <= k[3]:
                        blocked = True
                        break
            if not blocked:
                free += 1
    return tot * res * res, free * res * res


R7EDGES = edges(R7)
# free edges of the whole r7 outline = all R7 edges (the inset is 0.5 mm from every outline edge)


def inset_ok(x, y, m=0.5):
    if not pip((x, y), R7):
        return False
    return min(d_pt_seg((x, y), a, b) for a, b in R7EDGES) >= m


def in_tabx(x, y):
    return x >= 48.70 and y >= 56.30 and inset_ok(x, y)


def in_taby(x, y):
    return y >= 67.14 and x <= 37.56 and inset_ok(x, y)


FT1_KO = (59.5, 65.2, 64.5, 68.3)     # r7 stated FT1 keep-out incl. its access lane (H.23(d))
FT2_KO = (25.13, 71.0, 30.13, 76.0)
for nm, fn, bb, ko in (("tab X", in_tabx, (48.70, 56.30, 65.00, 68.30), FT1_KO),
                       ("tab Y", in_taby, (17.70, 67.14, 37.56, 76.00), FT2_KO)):
    tot, fr = bottom_area(fn, bb)
    _, fr2 = bottom_area(fn, bb, keepouts=(ko,))
    print("\n[3] %s inset region %.1f mm2; bottom-clearance-rule area %.1f mm2; minus foot keep-out %s: %.1f mm2"
          % (nm, tot, fr, ko, fr2))

# ---------------------------------------------------------------- 4. feet
def foot_report(name, body):
    bp = rect_poly(body)
    vu = [(v["net"], v["x"], v["y"]) for v in B.vias if d_pt_poly_region((v["x"], v["y"]), bp) < v["dia"] / 2]
    best = []
    for kind, net, lab, geom, hw in feats:
        d = dist_feat(geom, bp) - hw
        best.append((d, lab))
    best.sort()
    pb = sorted((d_rect_rect(e["box"], body), en) for en, e in parts)[:3]
    out_ok = all(inset_ok(x, y) for x, y in bp)
    print("\n[4] %s body %s: inside outline-0.5: %s; via pads under: %s; nearest non-GND rims: %s; nearest part "
          "boxes: %s" % (name, body, out_ok, vu or "none", [(round(d, 3), l) for d, l in best[:3]],
                         [(round(d, 3), n) for d, n in pb]))


foot_report("FT1 (r7: 4x2 at (62.0,66.7))", (60.0, 65.7, 64.0, 67.7))
foot_report("FT2 (r7: 4x4 at (27.63,73.5))", (25.63, 71.5, 29.63, 75.5))
foot_report("FT1 start point 4x4 (62.7,61.26)", (60.7, 59.26, 64.7, 63.26))


# 4x4 search in tab X: via-free and copper rim >= 1.0 mm, body >= 0.5 mm inside the outline
def search(w, h, step=0.1, thr=1.0):
    hits = []
    x = 48.70 + 0.5
    while x + w <= 65.00 - 0.5 + 1e-9:
        y = 56.30 + 0.5
        while y + h <= 68.30 - 0.5 + 1e-9:
            body = (x, y, x + w, y + h)
            bp = rect_poly(body)
            if all(inset_ok(px, py) for px, py in bp):
                ok = True
                for v in B.vias:
                    if d_pt_poly_region((v["x"], v["y"]), bp) < v["dia"] / 2:
                        ok = False
                        break
                if ok:
                    for kind, net, lab, geom, hw in feats:
                        if dist_feat(geom, bp) - hw < thr:
                            ok = False
                            break
                if ok:
                    hits.append(body)
            y += step
        x += step
    return hits


for w, h in ((4.0, 4.0), (4.0, 3.0), (3.0, 4.0), (4.0, 2.0)):
    hs = search(w, h, step=0.2)
    print("[4] tab X %.1f x %.1f via-free, copper >= 1.0 mm: %d spots (0.2 mm grid)%s" % (
        w, h, len(hs), "" if not hs else "; largest-x centre (%.2f, %.2f)" % max(
            ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in hs)))

# ---------------------------------------------------------------- 8. r6 sheet vs CO-5V
co = B.els["CO-5V"]
print("\n[8] CO-5V box", tuple(round(v, 3) for v in co["box"]), "body(21/51)", tuple(round(v, 3) for v in co["body"]),
      "pads", {k: (round(v["x"], 3), round(v["y"], 3)) for k, v in co["pads"].items()}, "side", co["side"])
SHEET6 = (16.70, 33.14, 49.70, 68.14)
for lab, b in (("body", co["body"]), ("box", co["box"])):
    ox = min(SHEET6[2], b[2]) - max(SHEET6[0], b[0])
    oy = min(SHEET6[3], b[3]) - max(SHEET6[1], b[1])
    print("    r6 sheet x %.2f-%.2f vs CO-5V %s: overlap %.3f x %.3f mm = %.3f mm2" % (
        SHEET6[0], SHEET6[2], lab, ox, oy, max(ox, 0) * max(oy, 0)))
for en in ("J-NTC", "J-BL", "C4A-BT", "C4B-BT", "RB1B", "RB2", "REG-5V"):
    e = B.els[en]
    bd = e["body"] or e["box"]
    print("    %s body %s: distance to r6 sheet %.3f" % (en, tuple(round(v, 3) for v in bd),
                                                          d_poly_poly(rect_poly(bd), rect_poly(SHEET6))))

# ---------------------------------------------------------------- 10. farthest outline point from the loop
LOOP = [(36.1, 52.03, 44.55, 61.55), (30.8, 62.85, 39.3, 66.64), (39.3, 61.6, 44.3, 66.6)]


def dl(p):
    return min(d_rect_rect((p[0], p[1], p[0], p[1]), r) for r in LOOP)


best = max(((dl(v), v) for v in R7))
print("\n[10] farthest r7 outline vertex from the loop region: %s at %.3f mm" % (best[1], best[0]))
# dense boundary sample too
mx = (0, None)
for a, b in R7EDGES:
    n = 200
    for k in range(n + 1):
        p = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
        if dl(p) > mx[0]:
            mx = (dl(p), p)
print("     dense boundary max %.3f at %s" % mx)
# low-y band distances
band = (23.15, 35.05, 42.43, 41.63)
print("     low-y band to the loop band y>=52.03: %.2f; to the REG-5V box (%.2f...)" % (52.03 - band[3],
                                                                                    B.els["REG-5V"]["box"][0]))
rg = B.els["REG-5V"]["box"]
print("     REG-5V box", tuple(round(v, 3) for v in rg), "band-to-box min %.2f max-x-gap %.2f" % (
    d_rect_rect(band, rg), rg[0] - band[0]))
