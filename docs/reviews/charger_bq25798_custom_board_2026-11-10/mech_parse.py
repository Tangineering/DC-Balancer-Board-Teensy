#!/usr/bin/env python3
"""Board mechanics around the CHG (Ag105) footprint, from the EAGLE XML .brd (stdlib only).

Coordinate convention (same as round3/calc/pin_identity_check.py and wiring design A.8):
Eagle board coordinates, top view, origin = MB origin (lower-left corner of the dimension outline),
+x right, +y UP, mm. "right" = +x, "left" = -x, "high-y"/"top edge" = +y, "low-y" = -y.

Usage: python -I mech_parse.py [--brd PATH] > mech_parse_out.txt
"""
import argparse
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

DEF_BRD = r"C:\Life Ops\School\Thesis\DC-Balancer-Charger-custom\references\Scale Car Board PCB 20260625.brd"
OUTER = {1: "Top", 16: "Bottom"}
OUTLINE_LAYERS = {21: "tPlace", 22: "bPlace", 51: "tDocu", 52: "bDocu", 39: "tKeepout", 40: "bKeepout"}
POWER_HINT = re.compile(r"VBUS|V-?MOT|VBT|VBAT|VCHG|VFC|GND|5V|3V3|VIN|VOUT|V-?RGN|VRGN|MID|V\+|V-|PWR|REGEN|SW", re.I)


def mm(v):
    v = v.strip()
    if v.endswith("mil"):
        return float(v[:-3]) * 0.0254
    if v.endswith("mm"):
        return float(v[:-2])
    if v.endswith("inch"):
        return float(v[:-4]) * 25.4
    return float(v)


def parse_rot(rot):
    rot = rot or "R0"
    mirror = "M" in rot
    ang = float(re.sub(r"[^0-9.]", "", rot) or 0)
    return mirror, ang


def xf(px, py, x0, y0, rot):
    mirror, ang = parse_rot(rot)
    if mirror:
        px = -px
    a = math.radians(ang)
    return (x0 + px * math.cos(a) - py * math.sin(a), y0 + px * math.sin(a) + py * math.cos(a))


def layer_xf(layer, rot):
    """Mirrored elements swap top/bottom layers."""
    mirror, _ = parse_rot(rot)
    if not mirror:
        return layer
    swap = {1: 16, 16: 1, 21: 22, 22: 21, 25: 26, 26: 25, 27: 28, 28: 27, 29: 30, 30: 29, 31: 32, 32: 31,
            35: 36, 36: 35, 39: 40, 40: 39, 41: 42, 42: 41, 51: 52, 52: 51}
    return swap.get(layer, layer)


class BBox:
    def __init__(self):
        self.x0 = self.y0 = math.inf
        self.x1 = self.y1 = -math.inf

    def add(self, x, y, r=0.0):
        self.x0 = min(self.x0, x - r); self.x1 = max(self.x1, x + r)
        self.y0 = min(self.y0, y - r); self.y1 = max(self.y1, y + r)

    def ok(self):
        return self.x0 < math.inf

    def t(self):
        return (round(self.x0, 3), round(self.y0, 3), round(self.x1, 3), round(self.y1, 3))


def rect_gap(a, b):
    """Edge-to-edge gap between two axis-aligned rects (x0,y0,x1,y1); negative = overlap depth (min axis)."""
    dx = max(b[0] - a[2], a[0] - b[2])
    dy = max(b[1] - a[3], a[1] - b[3])
    if dx >= 0 and dy >= 0:
        return math.hypot(dx, dy)
    return max(dx, dy)


def rect_inter(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brd", default=DEF_BRD)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    root = ET.parse(a.brd).getroot()

    # ---------- design rules: auto pad diameter ----------
    dr = {p.get("name"): p.get("value") for p in root.iter("param")}
    rv = float(dr["rvPadTop"]); rmin = mm(dr["rlMinPadTop"]); rmax = mm(dr["rlMaxPadTop"])
    rvv = float(dr["rvViaOuter"]); rminv = mm(dr["rlMinViaOuter"]); rmaxv = mm(dr.get("rlMaxViaOuter", "20mil"))

    def pad_dia(drill, dia):
        if dia and float(dia) > 0:
            return max(float(dia), drill + 2 * min(max(rv * drill, rmin), rmax))
        return drill + 2 * min(max(rv * drill, rmin), rmax)

    def via_dia(drill, dia):
        auto = drill + 2 * min(max(rvv * drill, rminv), rmaxv)
        return max(float(dia), auto) if dia and float(dia) > 0 else auto

    print("# mech_parse.py output")
    print("# source: %s" % a.brd)
    print("# convention: Eagle board coords, top view, origin = MB lower-left (dimension corner), +x right, +y UP, mm")
    print("# design rules: rvPadTop %s, rlMinPadTop %s, rlMaxPadTop %s; rvViaOuter %s, rlMinViaOuter %s; mtCopper[0] %s"
          % (dr["rvPadTop"], dr["rlMinPadTop"], dr["rlMaxPadTop"], dr["rvViaOuter"], dr["rlMinViaOuter"],
             dr["mtCopper"].split()[0]))

    # ---------- board outline ----------
    plain = root.find(".//board/plain")
    dim = BBox()
    for w in plain.iter("wire"):
        if w.get("layer") == "20":
            dim.add(float(w.get("x1")), float(w.get("y1"))); dim.add(float(w.get("x2")), float(w.get("y2")))
    print("\n## 3. Board outline (layer 20 Dimension, <plain>)")
    print("outline bbox x %.3f-%.3f, y %.3f-%.3f (%.3f x %.3f mm)" % (dim.x0, dim.x1, dim.y0, dim.y1, dim.x1 - dim.x0, dim.y1 - dim.y0))
    plain_holes = [(float(h.get("x")), float(h.get("y")), float(h.get("drill"))) for h in plain.iter("hole")]
    for h in plain_holes:
        print("plain hole at (%.3f, %.3f) drill %.4f" % h)

    # ---------- libraries / packages ----------
    pkgs = {}
    for lib in root.iter("library"):
        for p in lib.iter("package"):
            pkgs[(lib.get("name"), p.get("name"))] = p

    # ---------- element geometry ----------
    elems = {}
    for e in root.iter("element"):
        name = e.get("name")
        pkg = pkgs[(e.get("library"), e.get("package"))]
        x0, y0, rot = float(e.get("x")), float(e.get("y")), e.get("rot") or "R0"
        info = {"name": name, "value": e.get("value"), "package": e.get("package"), "library": e.get("library"),
                "x": x0, "y": y0, "rot": rot, "pads": [], "smds": [], "holes": [], "bb": {}, "side": "bottom" if "M" in rot else "top"}
        bbs = {k: BBox() for k in ("silk", "docu", "keepout", "copper", "all")}

        def addpt(layer, x, y, r=0.0):
            L = layer_xf(layer, rot)
            X, Y = xf(x, y, x0, y0, rot)
            if L in (21, 22):
                bbs["silk"].add(X, Y, r)
            if L in (51, 52):
                bbs["docu"].add(X, Y, r)
            if L in (39, 40):
                bbs["keepout"].add(X, Y, r)
            if L in (1, 16, 17):
                bbs["copper"].add(X, Y, r)
            if L in (1, 16, 17, 21, 22, 51, 52, 39, 40):
                bbs["all"].add(X, Y, r)

        for w in pkg.iter("wire"):
            L = int(w.get("layer")); wd = float(w.get("width")) / 2
            addpt(L, float(w.get("x1")), float(w.get("y1")), wd); addpt(L, float(w.get("x2")), float(w.get("y2")), wd)
        for r in pkg.iter("rectangle"):
            L = int(r.get("layer"))
            for (px, py) in ((r.get("x1"), r.get("y1")), (r.get("x2"), r.get("y2")), (r.get("x1"), r.get("y2")), (r.get("x2"), r.get("y1"))):
                addpt(L, float(px), float(py))
        for c in pkg.iter("circle"):
            L = int(c.get("layer")); rr = float(c.get("radius")) + float(c.get("width")) / 2
            addpt(L, float(c.get("x")), float(c.get("y")), rr)
        for pg in pkg.iter("polygon"):
            L = int(pg.get("layer"))
            for v in pg.iter("vertex"):
                addpt(L, float(v.get("x")), float(v.get("y")))
        for p in pkg.iter("pad"):
            d = float(p.get("drill")); D = pad_dia(d, p.get("diameter"))
            X, Y = xf(float(p.get("x")), float(p.get("y")), x0, y0, rot)
            info["pads"].append({"name": p.get("name"), "x": X, "y": Y, "drill": d, "dia": D, "shape": p.get("shape") or "round"})
            addpt(17, float(p.get("x")), float(p.get("y")), D / 2)
        for s in pkg.iter("smd"):
            dx, dy = float(s.get("dx")), float(s.get("dy"))
            L = int(s.get("layer"))
            X, Y = xf(float(s.get("x")), float(s.get("y")), x0, y0, rot)
            info["smds"].append({"name": s.get("name"), "x": X, "y": Y, "dx": dx, "dy": dy, "layer": layer_xf(L, rot), "srot": s.get("rot")})
            sx, sy = float(s.get("x")), float(s.get("y"))
            _, sa = parse_rot(s.get("rot"))
            ca, sn = math.cos(math.radians(sa)), math.sin(math.radians(sa))
            for (u, v) in ((-dx / 2, -dy / 2), (dx / 2, -dy / 2), (dx / 2, dy / 2), (-dx / 2, dy / 2)):
                addpt(L, sx + u * ca - v * sn, sy + u * sn + v * ca)
        for h in pkg.iter("hole"):
            X, Y = xf(float(h.get("x")), float(h.get("y")), x0, y0, rot)
            info["holes"].append((X, Y, float(h.get("drill"))))
            addpt(51, float(h.get("x")), float(h.get("y")), float(h.get("drill")) / 2)
        info["bb"] = {k: v.t() for k, v in bbs.items() if v.ok()}
        elems[name] = info

    # ---------- signals: pad -> net, copper ----------
    padnet = {}
    wires, vias, polys = [], [], []
    for s in root.iter("signal"):
        net = s.get("name")
        for c in s.iter("contactref"):
            padnet[(c.get("element"), c.get("pad"))] = net
        for w in s.iter("wire"):
            L = int(w.get("layer"))
            if L in (1, 2, 15, 16):
                wires.append({"net": net, "layer": L, "x1": float(w.get("x1")), "y1": float(w.get("y1")),
                              "x2": float(w.get("x2")), "y2": float(w.get("y2")), "w": float(w.get("width"))})
        for v in s.iter("via"):
            d = float(v.get("drill"))
            vias.append({"net": net, "x": float(v.get("x")), "y": float(v.get("y")), "drill": d,
                         "dia": via_dia(d, v.get("diameter")), "extent": v.get("extent")})
        for pg in s.iter("polygon"):
            bb = BBox()
            for v in pg.iter("vertex"):
                bb.add(float(v.get("x")), float(v.get("y")))
            polys.append({"net": net, "layer": int(pg.get("layer")), "bb": bb.t(), "width": float(pg.get("width")),
                          "rank": pg.get("rank"), "isolate": pg.get("isolate"), "pour": pg.get("pour") or "solid",
                          "nverts": len(list(pg.iter("vertex")))})

    # ---------- 1. CHG ----------
    chg = elems["CHG"]
    print("\n## 1. CHG element")
    print("library %s, package %s, value %s, origin (%.3f, %.3f), rot %s, side %s"
          % (chg["library"], chg["package"], chg["value"], chg["x"], chg["y"], chg["rot"], chg["side"]))
    print("outline bboxes (board mm, x0,y0,x1,y1): %s" % json.dumps(chg["bb"]))
    print("package has layers present: %s" % sorted({w.get("layer") for w in pkgs[(chg['library'], chg['package'])].iter("wire")}))
    print("pads (drill, auto pad dia from DRU, shape):")
    for p in sorted(chg["pads"], key=lambda p: (round(p["x"]), -p["y"])):
        print("  %-8s x %7.3f y %7.3f drill %.2f pad %.3f %s  MB net: %s"
              % (p["name"], p["x"], p["y"], p["drill"], p["dia"], p["shape"], padnet.get(("CHG", p["name"]), "(none)")))
    silk = chg["bb"]["silk"]
    print("silk outline (line centre) x %.3f-%.3f y %.3f-%.3f; with 0.127 width: %s" %
          (silk[0] + 0.0635, silk[2] - 0.0635, silk[1] + 0.0635, silk[3] - 0.0635, silk))
    fp = (silk[0] + 0.0635, silk[1] + 0.0635, silk[2] - 0.0635, silk[3] - 0.0635)  # footprint rect = silk line centre
    print("FOOTPRINT RECT used below (silk line centre): %s, %.3f x %.3f mm" % (tuple(round(v, 3) for v in fp), fp[2] - fp[0], fp[3] - fp[1]))

    # ---------- 3. distances to board edge ----------
    print("\n## 3b. CHG footprint to board edge")
    print("left (-x)  : %.3f mm" % (fp[0] - dim.x0))
    print("right (+x) : %.3f mm" % (dim.x1 - fp[2]))
    print("low-y (-y) : %.3f mm" % (fp[1] - dim.y0))
    print("high-y (+y): %.3f mm" % (dim.y1 - fp[3]))

    # ---------- 2. neighbours ----------
    print("\n## 2. Elements within 25 mm of the CHG footprint edge (gap = edge-to-edge, footprint vs element 'all' bbox)")
    rows = []
    for n, e in elems.items():
        if n == "CHG" or "all" not in e["bb"]:
            continue
        g = rect_gap(fp, e["bb"]["all"])
        if g <= 25.0:
            ex = e["bb"]["all"]
            cx, cy = (ex[0] + ex[2]) / 2, (ex[1] + ex[3]) / 2
            # direction
            dirs = []
            if ex[2] <= fp[0]: dirs.append("L")
            if ex[0] >= fp[2]: dirs.append("R")
            if ex[3] <= fp[1]: dirs.append("LOWY")
            if ex[1] >= fp[3]: dirs.append("HIGHY")
            if not dirs: dirs.append("UNDER/OVERLAP")
            rows.append((g, n, e, "/".join(dirs)))
    rows.sort(key=lambda r: r[0])
    for g, n, e, d in rows:
        print("  %-10s %-22s pkg %-28s side %-6s at (%7.3f,%7.3f) %-6s all-bbox %s silk %s docu %s gap %6.2f dir %s"
              % (n, (e["value"] or "")[:22], e["package"][:28], e["side"], e["x"], e["y"], e["rot"], e["bb"]["all"],
                 e["bb"].get("silk"), e["bb"].get("docu"), g, d))

    # elements whose bbox lies (partly) under the footprint
    print("\n## 2b. Elements whose bbox intersects the footprint rect (parts under the Ag105)")
    for n, e in elems.items():
        if n != "CHG" and "all" in e["bb"] and rect_inter(fp, e["bb"]["all"]):
            print("  %-10s %-20s %-26s side %s all %s" % (n, e["value"], e["package"], e["side"], e["bb"]["all"]))

    # named parts of interest anywhere on the board
    print("\n## 2c. Named parts of interest (anywhere)")
    for n, e in sorted(elems.items()):
        if re.search(r"LM1084|CO-5V|NTC|J-BL|BAL|RT|^H\d|MOUNT|HOLE|^J|^D-|^L|^C.*E|ELEC|CPOL", n + " " + (e["value"] or "") + " " + e["package"], re.I):
            print("  %-12s %-24s pkg %-30s side %-6s at (%7.3f,%7.3f) %-6s all %s gap %s"
                  % (n, (e["value"] or "")[:24], e["package"][:30], e["side"], e["x"], e["y"], e["rot"], e["bb"].get("all"),
                     round(rect_gap(fp, e["bb"]["all"]), 2) if "all" in e["bb"] else "-"))
        if e["holes"]:
            for h in e["holes"]:
                print("      non-plated hole (%.3f, %.3f) drill %.3f" % h)

    # ---------- 4. copper near / under ----------
    regions = {
        "UNDER": fp,
        "LEFT(-x) 30mm": (fp[0] - 30, fp[1], fp[0], fp[3]),
        "RIGHT(+x) 30mm": (fp[2], fp[1], fp[2] + 30, fp[3]),
        "LOWY(-y) 30mm": (fp[0], fp[1] - 30, fp[2], fp[1]),
        "HIGHY(+y) 30mm": (fp[0], fp[3], fp[2], fp[3] + 30),
    }
    for rn, R in regions.items():
        R = (max(R[0], dim.x0), max(R[1], dim.y0), min(R[2], dim.x1), min(R[3], dim.y1))
        regions[rn] = R
    print("\n## 4. MB copper by region (regions clipped to the board outline)")
    for rn, R in regions.items():
        print("\n### region %s: x %.3f-%.3f y %.3f-%.3f" % (rn, R[0], R[2], R[1], R[3]))
        agg = {}
        for w in wires:
            bb = (min(w["x1"], w["x2"]) - w["w"] / 2, min(w["y1"], w["y2"]) - w["w"] / 2,
                  max(w["x1"], w["x2"]) + w["w"] / 2, max(w["y1"], w["y2"]) + w["w"] / 2)
            if rect_inter(bb, R):
                k = (w["net"], OUTER.get(w["layer"], "L%d" % w["layer"]))
                a_ = agg.setdefault(k, {"n": 0, "wmax": 0, "wmin": 99, "bb": BBox()})
                a_["n"] += 1; a_["wmax"] = max(a_["wmax"], w["w"]); a_["wmin"] = min(a_["wmin"], w["w"])
                a_["bb"].add(bb[0], bb[1]); a_["bb"].add(bb[2], bb[3])
        print("  wires (net, layer: count, width min-max, extent of the touching segments):")
        for (net, L), v in sorted(agg.items(), key=lambda kv: (-kv[1]["wmax"], kv[0])):
            flag = " POWER?" if (POWER_HINT.search(net) or v["wmax"] >= 0.6) else ""
            print("    %-18s %-6s n %3d w %.3f-%.3f extent %s%s" % (net, L, v["n"], v["wmin"], v["wmax"], v["bb"].t(), flag))
        print("  polygons touching:")
        for p in polys:
            if rect_inter(p["bb"], R):
                print("    %-18s %-6s bbox %s pour %s rank %s isolate %s verts %d" % (p["net"], OUTER.get(p["layer"], p["layer"]), p["bb"], p["pour"], p["rank"], p["isolate"], p["nverts"]))
        vv = [v for v in vias if R[0] <= v["x"] <= R[2] and R[1] <= v["y"] <= R[3]]
        vnet = {}
        for v in vv:
            vnet.setdefault(v["net"], []).append((round(v["x"], 2), round(v["y"], 2)))
        print("  vias: %d" % len(vv))
        for net, pts in sorted(vnet.items()):
            print("    %-18s %3d  %s" % (net, len(pts), pts if len(pts) <= 12 else str(pts[:12]) + " ..."))
        print("  elements (any part of bbox in region):")
        for n, e in sorted(elems.items()):
            if n != "CHG" and "all" in e["bb"] and rect_inter(e["bb"]["all"], R):
                print("    %-12s %-22s %-28s %-6s all %s" % (n, (e["value"] or "")[:22], e["package"][:28], e["side"], e["bb"]["all"]))

    # ---------- 5. free spots for a support foot ----------
    # obstacles on the TOP surface: top-layer wires (non-pour), all through-hole pads, top SMDs, vias, top-side element bboxes
    print("\n## 5. Candidate support-foot spots (top side)")
    obst = []  # (x0,y0,x1,y1,label)
    for w in wires:
        if w["layer"] in (1, 16):
            obst.append((min(w["x1"], w["x2"]) - w["w"] / 2, min(w["y1"], w["y2"]) - w["w"] / 2,
                         max(w["x1"], w["x2"]) + w["w"] / 2, max(w["y1"], w["y2"]) + w["w"] / 2, "wire:" + w["net"], w))
    for v in vias:
        r = v["dia"] / 2
        obst.append((v["x"] - r, v["y"] - r, v["x"] + r, v["y"] + r, "via:" + v["net"], None))
    for n, e in elems.items():
        if n == "CHG":
            continue
        if e["side"] == "top" and "all" in e["bb"]:
            b = e["bb"]["all"]; obst.append((b[0], b[1], b[2], b[3], "part:" + n, None))
        for p in e["pads"]:
            r = p["dia"] / 2
            obst.append((p["x"] - r, p["y"] - r, p["x"] + r, p["y"] + r, "pad:%s.%s" % (n, p["name"]), None))

    def seg_dist(px, py, w):
        x1, y1, x2, y2 = w["x1"], w["y1"], w["x2"], w["y2"]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        t = 0 if L2 == 0 else max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / L2))
        return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy)) - w["w"] / 2

    def clearance(px, py):
        best, lab = 1e9, ""
        for o in obst:
            if o[5] is not None:
                d = seg_dist(px, py, o[5])
            else:
                dx = max(o[0] - px, 0, px - o[2]); dy = max(o[1] - py, 0, py - o[3])
                d = math.hypot(dx, dy) if (dx or dy) else -1
            if d < best:
                best, lab = d, o[4]
        return best, lab

    FOOT_R = 3.0  # 6 mm diameter foot (M3 nylon hex standoff 5.5 mm AF + margin)
    for rn, R in regions.items():
        if rn == "UNDER":
            continue
        cands = []
        y = R[1] + FOOT_R
        while y <= R[3] - FOOT_R + 1e-9:
            x = R[0] + FOOT_R
            while x <= R[2] - FOOT_R + 1e-9:
                if x - FOOT_R >= dim.x0 + 0.5 and x + FOOT_R <= dim.x1 - 0.5 and y - FOOT_R >= dim.y0 + 0.5 and y + FOOT_R <= dim.y1 - 0.5:
                    c, lab = clearance(x, y)
                    if c >= FOOT_R:
                        cands.append((c, x, y, lab, rect_gap(fp, (x, y, x, y))))
                x += 0.5
            y += 0.5
        # keep spots nearest to the footprint, de-duplicated by 4 mm
        cands.sort(key=lambda t: (t[4], -t[0]))
        picked = []
        for c in cands:
            if all(math.hypot(c[1] - p[1], c[2] - p[2]) > 4 for p in picked):
                picked.append(c)
            if len(picked) >= 8:
                break
        print("  %s: %d grid points with a %.1f mm-radius clear circle (no top OR bottom signal wire, via, pad or top part bbox; GND pours NOT counted)" % (rn, len(cands), FOOT_R))
        for c in picked:
            print("    (%.2f, %.2f) clearance %.2f to %s, %.2f mm from footprint edge" % (c[1], c[2], c[0], c[3], c[4]))

    # existing holes near CHG
    print("\n## 5b. Existing non-plated holes and large plated holes on the board")
    for h in plain_holes:
        print("  plain hole (%.3f, %.3f) drill %.3f gap-to-footprint %.2f" % (h[0], h[1], h[2], rect_gap(fp, (h[0], h[1], h[0], h[1]))))
    for n, e in elems.items():
        for h in e["holes"]:
            print("  %s hole (%.3f, %.3f) drill %.3f gap %.2f" % (n, h[0], h[1], h[2], rect_gap(fp, (h[0], h[1], h[0], h[1]))))
        for p in e["pads"]:
            if p["drill"] >= 2.5:
                print("  %s pad %s (%.3f, %.3f) drill %.3f gap %.2f" % (n, p["name"], p["x"], p["y"], p["drill"], rect_gap(fp, (p["x"], p["y"], p["x"], p["y"]))))

    # dump JSON
    if a.json:
        with open(a.json, "w") as f:
            json.dump({"fp": fp, "dim": dim.t(), "elems": elems, "polys": polys, "wires": wires, "vias": vias}, f, indent=1, default=str)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------------------------------------------
# Part 2: heights and per-side overhang sweep (run after main(); reads the JSON written by main()).
# Height sources: IPC-7351 package names encode the max height after 'X' in 1/100 mm (e.g. CAPC3225X135 = 1.35 mm);
# others from the datasheets in references/Datasheets. None = unknown (TODO).
HEIGHTS = {
    "CAPC": ("ipc", None), "RESC": ("ipc", None), "CAPM": ("ipc", None), "SOP65": ("ipc", None), "TO254": ("ipc", None),
    "D0008A-IPC_A": (1.75, "OPA197IDR.pdf D0008A 'SOIC - 1.75 mm max height' (txt line 2338)"),
    "IC_RT1987N-A": (1.00, "RT1987_DS-00.pdf s19 Outline Dimension, A max 1.000 mm"),
    "DRB8_1P6X2P4": (1.00, "BQ29200_TI.pdf 'VSON - 1 mm max height'"),
    "CONV_TPS61288LRQQR": (1.00, "TPS61288LRQQR.pdf 'VQFN-HR - 1 mm max height'"),
    "CUI_TB005_-762-03BE": (21.70, "TB005-762_CUI.pdf p2 mechanical drawing, 21.70 mm"),
    "CUI_TB005-762-02BE": (21.70, "TB005-762_CUI.pdf p2 mechanical drawing, 21.70 mm"),
    "691411410002": (None, "TODO(verify: Wurth 691411410002 datasheet, not in references)"),
    "HCM1A1305V3-2R2-R": (None, "TODO(verify: Eaton HCM1A1305V3 datasheet, not in references)"),
    "RM_10_ADI": (None, "TODO(verify: AD5443 RM-10 outline; ad5426_5432_5443.pdf text extraction gives no height)"),
    "CAP_FN_G_PAN": (None, "TODO(verify: Panasonic EEE-FN1V471UP)"),
    "AMPHENOL_87606-324LF": (None, "TODO(verify: Amphenol 87606-324LF)"),
}


def height_of(pkg):
    m = re.search(r"X(\d{2,3})(?:-|$|N)", pkg)
    for k, (h, src) in HEIGHTS.items():
        if pkg.startswith(k) or pkg == k:
            if h == "ipc" and m:
                return int(m.group(1)) / 100.0, "IPC-7351 name %s" % pkg
            if h != "ipc":
                return h, src
    if m:
        return int(m.group(1)) / 100.0, "IPC-7351 name %s" % pkg
    return None, "TODO(verify)"


def sweep(jpath):
    d = json.load(open(jpath))
    fp = d["fp"]; dim = d["dim"]
    el = d["elems"]
    print("\n## 6. Heights of elements near the footprint and per-side sweep")
    near = []
    for n, e in el.items():
        if n == "CHG" or "all" not in e["bb"]:
            continue
        g = rect_gap(fp, e["bb"]["all"])
        if g <= 30:
            h, src = height_of(e["package"])
            near.append((g, n, e["package"], h, src, e["bb"]["all"]))
    near.sort()
    for g, n, pk, h, src in [(a[0], a[1], a[2], a[3], a[4]) for a in near]:
        print("  %-10s %-26s gap %6.2f  height %s  [%s]" % (n, pk[:26], g, "%.2f" % h if h is not None else "unknown", src))
    # per side: for a band the width of the footprint (or its height), walk outward 0.5 mm at a time and report
    # the first element of each height class met; and the tallest element inside each candidate rectangle.
    sides = {
        "HIGHY(+y)": lambda t: (fp[0], fp[3], fp[2], fp[3] + t),
        "LOWY(-y)": lambda t: (fp[0], fp[1] - t, fp[2], fp[1]),
        "RIGHT(+x)": lambda t: (fp[2], fp[1], fp[2] + t, fp[3]),
        "LEFT(-x)": lambda t: (fp[0] - t, fp[1], fp[0], fp[3]),
    }
    for sn, f in sides.items():
        print("\n  side %s: first contact with each element as the band grows (band = full footprint span)" % sn)
        seen = set()
        t = 0.0
        while t <= 30.0:
            R = f(t)
            for g, n, pk, h, src, bb in near:
                if n not in seen and rect_inter(R, bb):
                    seen.add(n)
                    print("    at %5.1f mm: %-10s h %-7s bbox %s" % (t, n, "%.2f" % h if h is not None else "?", tuple(round(v, 2) for v in bb)))
            t += 0.5


def candidate_rects(jpath):
    d = json.load(open(jpath))
    fp = d["fp"]; el = d["elems"]
    cands = {
        "A  HIGHY, left of OP-FC, below L-FC": (17.50, 67.644, 38.90, 76.40),
        "A' HIGHY, full width, below L-FC/over OP-FC": (17.50, 67.644, 49.199, 76.40),
        "B  LOWY, right of J-BL, above L-BT": (17.50, 21.30, 49.199, 32.843),
        "B' LOWY, shallow (to y 26.0)": (17.50, 26.00, 49.199, 32.843),
        "C  RIGHT, between footprint and LM1084 courtyard": (49.199, 32.843, 50.90, 67.644),
        "D  LEFT, between J-BL/J-NTC courtyards and footprint": (16.50, 32.843, 17.198, 67.644),
    }
    print("\n## 6b. Candidate overhang rectangles: contents and tallest part")
    for cn, R in cands.items():
        inside = []
        for n, e in el.items():
            if n != "CHG" and "all" in e["bb"] and rect_inter(R, e["bb"]["all"]):
                h, src = height_of(e["package"])
                inside.append((h if h is not None else -1, n, e["package"], src))
        inside.sort(reverse=True)
        print("  %s: x %.2f-%.2f y %.2f-%.2f (%.1f x %.1f mm = %.0f mm2)" % (cn, R[0], R[2], R[1], R[3], R[2] - R[0], R[3] - R[1], (R[2] - R[0]) * (R[3] - R[1])))
        for h, n, pk, src in inside:
            print("      %-10s %-26s h %s [%s]" % (n, pk[:26], "%.2f" % h if h >= 0 else "unknown", src))
        cu = {}
        for w in d["wires"]:
            bb = (min(w["x1"], w["x2"]) - w["w"] / 2, min(w["y1"], w["y2"]) - w["w"] / 2,
                  max(w["x1"], w["x2"]) + w["w"] / 2, max(w["y1"], w["y2"]) + w["w"] / 2)
            if rect_inter(bb, R):
                k = (w["net"], OUTER.get(w["layer"], w["layer"]))
                cu.setdefault(k, []).append(round(w["w"], 3))
        print("      copper wires in rect: %s" % ({"%s/%s" % k: sorted(set(v)) for k, v in cu.items()} or "none"))
        pv = [p for p in d["polys"] if rect_inter(p["bb"], R)]
        print("      polygons in rect: %s" % [(p["net"], OUTER.get(p["layer"], p["layer"]), p["bb"]) for p in pv])
        vv = [(v["net"], round(v["x"], 2), round(v["y"], 2)) for v in d["vias"] if R[0] <= v["x"] <= R[2] and R[1] <= v["y"] <= R[3]]
        print("      vias in rect: %s" % (vv or "none"))


def key_distances(jpath):
    d = json.load(open(jpath))
    fp = d["fp"]; el = d["elems"]
    print("\n## 7. Key distances from the CHG silk line centre (x %.3f-%.3f, y %.3f-%.3f); silk line width 0.127 mm"
          % (fp[0], fp[2], fp[1], fp[3]))
    reg = el["REG-5V"]
    tab = [s for s in reg["smds"] if s["name"] == "4"][0]
    # R90 element: smd dx lies along board y, dy along board x
    tab_x0 = tab["x"] - tab["dy"] / 2
    print("  LM1084 (REG-5V): courtyard tKeepout x0 %.3f -> %.3f mm; tab pad x %.3f-%.3f y %.3f-%.3f -> %.3f mm; body docu x0 %.3f -> %.3f mm"
          % (reg["bb"]["keepout"][0], reg["bb"]["keepout"][0] - fp[2], tab_x0, tab["x"] + tab["dy"] / 2,
             tab["y"] - tab["dx"] / 2, tab["y"] + tab["dx"] / 2, tab_x0 - fp[2], 51.562, 51.562 - fp[2]))
    for p in d["polys"]:
        if p["net"] == "5V":
            print("  5V pour (LM1084 tab copper) x0 %.3f -> %.3f mm from CHG silk; bbox %s" % (p["bb"][0], p["bb"][0] - fp[2], p["bb"]))
    co = el["CO-5V"]
    print("  CO-5V: silk x0 %.3f (outer) vs CHG silk outer %.3f -> %.3f mm; pad copper x0 %.3f -> %.3f mm; y %.3f-%.3f"
          % (co["bb"]["silk"][0], fp[2] + 0.0635, co["bb"]["silk"][0] - fp[2] - 0.0635, co["bb"]["copper"][0], co["bb"]["copper"][0] - fp[2], co["bb"]["all"][1], co["bb"]["all"][3]))
    for n in ("J-BL", "J-NTC", "J-FC"):
        e = el[n]
        print("  %s: courtyard tKeepout x1 %.3f -> %.3f mm; silk x1 %.3f -> %.3f mm; y %.3f-%.3f; pads %s"
              % (n, e["bb"]["keepout"][2], fp[0] - e["bb"]["keepout"][2], e["bb"]["silk"][2], fp[0] - e["bb"]["silk"][2],
                 e["bb"]["all"][1], e["bb"]["all"][3], [(p["name"], round(p["x"], 3), round(p["y"], 3)) for p in e["pads"]]))
    for n in ("OP-FC", "C4A-BT", "C4B-BT", "C4C-BT", "MDAC-FC", "BAL"):
        e = el[n]
        print("  %s: bbox %s copper %s" % (n, e["bb"]["all"], e["bb"].get("copper")))


if __name__ == "__main__" and "--json" in sys.argv:
    jp = sys.argv[sys.argv.index("--json") + 1]
    sweep(jp)
    candidate_rects(jp)
    key_distances(jp)
