"""Independent check of H.23 (r7_calc_out.txt): BRD parsing and plan geometry (stdlib only).

Coordinates: Eagle board mm, top view, +y up. Written without reference to r7_calc.py.
"""
import math
import os
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
BRD = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "..", "..", "references",
                                    "Scale Car Board PCB 20260625.brd"))

MIL = 0.0254


def _len(v):
    v = v.strip()
    if v.endswith("mil"):
        return float(v[:-3]) * MIL
    if v.endswith("mm"):
        return float(v[:-2])
    return float(v)


def rot_parse(s):
    s = s or "R0"
    mir = "M" in s
    spin = "S" in s
    ang = float(s.replace("M", "").replace("S", "").replace("R", "") or 0)
    return mir, ang


def xform(px, py, ex, ey, rot):
    mir, ang = rot_parse(rot)
    if mir:
        px = -px
    a = math.radians(ang)
    return ex + px * math.cos(a) - py * math.sin(a), ey + px * math.sin(a) + py * math.cos(a)


class Board:
    def __init__(self, path=BRD):
        root = ET.parse(path).getroot()
        self.b = root.find("drawing/board")
        self.rules = {}
        for p in self.b.find("designrules"):
            self.rules[p.get("name")] = p.get("value")
        self._outline()
        self._packages()
        self._elements()
        self._signals()

    def rule_len(self, name):
        return _len(self.rules[name])

    def via_dia(self, drill):
        rv = float(self.rules["rvViaOuter"])
        ring = min(max(rv * drill, self.rule_len("rlMinViaOuter")), self.rule_len("rlMaxViaOuter"))
        return drill + 2 * ring

    def pad_dia(self, drill):
        rv = float(self.rules["rvPadTop"])
        ring = min(max(rv * drill, self.rule_len("rlMinPadTop")), self.rule_len("rlMaxPadTop"))
        return drill + 2 * ring

    def _outline(self):
        pts = []
        self.holes = []
        for w in self.b.find("plain"):
            if w.tag == "wire" and w.get("layer") == "20":
                pts += [(float(w.get("x1")), float(w.get("y1"))), (float(w.get("x2")), float(w.get("y2")))]
            if w.tag == "hole":
                self.holes.append((float(w.get("x")), float(w.get("y")), float(w.get("drill"))))
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        self.outline_bbox = (min(xs), min(ys), max(xs), max(ys))

    def _packages(self):
        self.pkgs = {}
        for lib in self.b.find("libraries"):
            pr = lib.find("packages")
            if pr is None:
                continue
            for pk in pr:
                self.pkgs[(lib.get("name"), pk.get("name"))] = pk

    def _elements(self):
        self.els = {}
        for e in self.b.find("elements"):
            ex, ey = float(e.get("x")), float(e.get("y"))
            rot = e.get("rot", "R0")
            mir, _ = rot_parse(rot)
            pk = self.pkgs.get((e.get("library"), e.get("package")))
            pads = {}
            boxpts = []
            body = []   # layers 21/51 straight wires and rectangles (body outline)
            if pk is not None:
                for g in pk:
                    if g.tag == "pad":
                        px, py = float(g.get("x")), float(g.get("y"))
                        dr = float(g.get("drill"))
                        dia = float(g.get("diameter") or 0) or self.pad_dia(dr)
                        cx, cy = xform(px, py, ex, ey, rot)
                        shape = g.get("shape", "round")
                        pads[g.get("name")] = dict(x=cx, y=cy, kind="tht", dia=dia, shape=shape, layer="all",
                                                   bb=(cx - dia / 2, cy - dia / 2, cx + dia / 2, cy + dia / 2))
                        boxpts += [(cx - dia / 2, cy - dia / 2), (cx + dia / 2, cy + dia / 2)]
                    elif g.tag == "smd":
                        px, py = float(g.get("x")), float(g.get("y"))
                        dx, dy = float(g.get("dx")), float(g.get("dy"))
                        _, la = rot_parse(g.get("rot", "R0"))
                        r = math.radians(la)
                        cs = []
                        for sx in (-0.5, 0.5):
                            for sy in (-0.5, 0.5):
                                qx, qy = sx * dx, sy * dy
                                qx, qy = qx * math.cos(r) - qy * math.sin(r), qx * math.sin(r) + qy * math.cos(r)
                                cs.append(xform(px + qx, py + qy, ex, ey, rot))
                        bx = (min(c[0] for c in cs), min(c[1] for c in cs), max(c[0] for c in cs),
                              max(c[1] for c in cs))
                        lay = g.get("layer")
                        if mir:
                            lay = "16" if lay == "1" else "1"
                        pads[g.get("name")] = dict(x=(bx[0] + bx[2]) / 2, y=(bx[1] + bx[3]) / 2, kind="smd",
                                                   layer=lay, bb=bx, corners=cs)
                        boxpts += [(bx[0], bx[1]), (bx[2], bx[3])]
                    elif g.tag in ("wire", "rectangle") and g.get("layer") in ("21", "22", "51", "52", "39", "40"):
                        if g.tag == "rectangle":
                            x1, y1, x2, y2 = (float(g.get(k)) for k in ("x1", "y1", "x2", "y2"))
                            _, ra = rot_parse(g.get("rot", "R0"))
                            cx0, cy0 = (x1 + x2) / 2, (y1 + y2) / 2
                            rr = math.radians(ra)
                            loc = []
                            for qx, qy in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)):
                                ux, uy = qx - cx0, qy - cy0
                                loc.append((cx0 + ux * math.cos(rr) - uy * math.sin(rr),
                                            cy0 + ux * math.sin(rr) + uy * math.cos(rr)))
                            pts = [xform(a, b_, ex, ey, rot) for a, b_ in loc]
                        else:
                            pts = [xform(float(g.get("x1")), float(g.get("y1")), ex, ey, rot),
                                   xform(float(g.get("x2")), float(g.get("y2")), ex, ey, rot)]
                        boxpts += pts
                        if g.get("layer") in ("21", "51") and (g.tag == "rectangle" or not g.get("curve")):
                            body += pts
                    elif g.tag == "circle" and g.get("layer") in ("21", "22", "51", "52"):
                        cx, cy = xform(float(g.get("x")), float(g.get("y")), ex, ey, rot)
                        rr = float(g.get("radius"))
                        boxpts += [(cx - rr, cy - rr), (cx + rr, cy + rr)]
            if boxpts:
                box = (min(p[0] for p in boxpts), min(p[1] for p in boxpts), max(p[0] for p in boxpts),
                       max(p[1] for p in boxpts))
            else:
                box = (ex, ey, ex, ey)
            bodyb = None
            if body:
                bodyb = (min(p[0] for p in body), min(p[1] for p in body), max(p[0] for p in body),
                         max(p[1] for p in body))
            self.els[e.get("name")] = dict(name=e.get("name"), x=ex, y=ey, rot=rot, pkg=e.get("package"),
                                           value=e.get("value"), pads=pads, box=box, body=bodyb,
                                           side="bottom" if mir else "top")

    def _signals(self):
        self.wires, self.polys, self.vias, self.padnet = [], [], [], {}
        for s in self.b.find("signals"):
            net = s.get("name")
            for g in s:
                if g.tag == "contactref":
                    self.padnet[(g.get("element"), g.get("pad"))] = net
                elif g.tag == "wire":
                    self.wires.append(dict(net=net, layer=g.get("layer"), w=float(g.get("width")),
                                           a=(float(g.get("x1")), float(g.get("y1"))),
                                           b=(float(g.get("x2")), float(g.get("y2"))), curve=g.get("curve")))
                elif g.tag == "polygon":
                    pts = [(float(v.get("x")), float(v.get("y"))) for v in g.findall("vertex")]
                    self.polys.append(dict(net=net, layer=g.get("layer"), w=float(g.get("width")), pts=pts,
                                           rank=g.get("rank")))
                elif g.tag == "via":
                    dr = float(g.get("drill"))
                    # Eagle: the larger of the 'diameter' attribute and the design-rule restring diameter applies
                    dia = max(float(g.get("diameter") or 0), self.via_dia(dr))
                    self.vias.append(dict(net=net, x=float(g.get("x")), y=float(g.get("y")), drill=dr, dia=dia,
                                          stop=g.get("alwaysstop")))


# ------------------------------------------------------------------------------------------------ geometry
def d_pt_seg(p, a, b):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def seg_inter(a, b, c, d):
    def cr(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    d1, d2, d3, d4 = cr(c, d, a), cr(c, d, b), cr(a, b, c), cr(a, b, d)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def d_seg_seg(a, b, c, d):
    if seg_inter(a, b, c, d):
        return 0.0
    return min(d_pt_seg(a, c, d), d_pt_seg(b, c, d), d_pt_seg(c, a, b), d_pt_seg(d, a, b))


def pip(p, poly):
    x, y = p
    ins = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                ins = not ins
    return ins


def edges(poly):
    return [(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))]


def d_pt_poly_region(p, poly):
    """0 inside, else the distance to the boundary."""
    if pip(p, poly):
        return 0.0
    return min(d_pt_seg(p, a, b) for a, b in edges(poly))


def d_seg_poly_region(a, b, poly):
    if pip(a, poly) or pip(b, poly):
        return 0.0
    return min(d_seg_seg(a, b, c, d) for c, d in edges(poly))


def d_poly_poly(p1, p2):
    if any(pip(v, p2) for v in p1) or any(pip(v, p1) for v in p2):
        return 0.0
    return min(d_seg_seg(a, b, c, d) for a, b in edges(p1) for c, d in edges(p2))


def rect_poly(r):
    x0, y0, x1, y1 = r
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def shoelace(poly):
    s = 0.0
    for (x1, y1), (x2, y2) in edges(poly):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def d_rect_rect(r1, r2):
    dx = max(r1[0] - r2[2], r2[0] - r1[2], 0.0)
    dy = max(r1[1] - r2[3], r2[1] - r1[3], 0.0)
    return math.hypot(dx, dy)
