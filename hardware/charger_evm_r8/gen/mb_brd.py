"""Read-only MB board data for the CR generator (D-51, 2026-11-12).

Parses `references/Scale Car Board PCB 20260625.brd` (Eagle 9.7 XML, the as-designed MB) and returns part
placements in the MB frame (Eagle board coordinates, top view, +y up; D-01). Every element on the MB is a
top-side part (no mirrored rotation occurs in the file), so the transform is: rotate the package geometry by the
element angle, then translate to the element origin.

Stdlib only (xml.etree), so the geometry checks of `cr_geometry.py` run headless without KiCad.
"""
import math
import os
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
BRD = os.path.normpath(os.path.join(HERE, "..", "..", "..", "references", "Scale Car Board PCB 20260625.brd"))

# Eagle layers used here: 1 Top copper, 21 tPlace (silkscreen), 39 tKeepout, 51 tDocu (package body outline)
L_TOP, L_PLACE, L_KEEPOUT, L_DOCU = 1, 21, 39, 51

_CACHE = {}


def _rot(angle_str):
    a = (angle_str or "R0").lstrip("SM")
    if (angle_str or "").startswith(("M", "SM")):
        raise ValueError("mirrored element %s: not expected on the MB (all parts top-side)" % angle_str)
    return float(a[1:]) if a.startswith("R") else 0.0


def _xf(x, y, ex, ey, ang):
    c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    return (ex + x * c - y * s, ey + x * s + y * c)


def load(path=BRD):
    if path in _CACHE:
        return _CACHE[path]
    root = ET.parse(path).getroot()
    pkgs = {}
    for lib in root.iter("library"):
        key = lib.get("urn") or lib.get("name")
        for pk in lib.iter("package"):
            pkgs[(key, pk.get("name"))] = pk
            pkgs.setdefault((lib.get("name"), pk.get("name")), pk)
    parts = {}
    for el in root.iter("element"):
        pk = pkgs.get((el.get("library_urn"), el.get("package")))
        if pk is None:
            pk = pkgs.get((el.get("library"), el.get("package")))
        ex, ey, ang = float(el.get("x")), float(el.get("y")), _rot(el.get("rot"))
        geo = {}   # layer -> list of (x, y) points (vertices, with the half line width applied as an outer offset)
        pads = {}
        if pk is not None:
            for w in pk.findall("wire"):
                lay = int(w.get("layer"))
                hw = float(w.get("width") or 0) / 2
                for px, py in ((float(w.get("x1")), float(w.get("y1"))), (float(w.get("x2")), float(w.get("y2")))):
                    geo.setdefault(lay, []).append((_xf(px, py, ex, ey, ang), hw, "wire"))
            for r in pk.findall("rectangle"):
                lay = int(r.get("layer"))
                x1, y1, x2, y2 = (float(r.get(k)) for k in ("x1", "y1", "x2", "y2"))
                for px, py in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)):
                    geo.setdefault(lay, []).append((_xf(px, py, ex, ey, ang), 0.0, "rect"))
            for c in pk.findall("circle"):
                lay = int(c.get("layer"))
                cx, cy = _xf(float(c.get("x")), float(c.get("y")), ex, ey, ang)
                rr = float(c.get("radius")) + float(c.get("width") or 0) / 2
                for px, py in ((cx - rr, cy - rr), (cx + rr, cy + rr)):
                    geo.setdefault(lay, []).append(((px, py), 0.0, "circle"))
            for pg in pk.findall("polygon"):
                lay = int(pg.get("layer"))
                hw = float(pg.get("width") or 0) / 2
                for v in pg.findall("vertex"):
                    geo.setdefault(lay, []).append((_xf(float(v.get("x")), float(v.get("y")), ex, ey, ang), hw, "poly"))
            for p in pk.findall("pad"):
                pads[p.get("name")] = dict(xy=_xf(float(p.get("x")), float(p.get("y")), ex, ey, ang),
                                           drill=float(p.get("drill")), kind="pth")
            for p in pk.findall("smd"):
                pads[p.get("name")] = dict(xy=_xf(float(p.get("x")), float(p.get("y")), ex, ey, ang),
                                           dx=float(p.get("dx")), dy=float(p.get("dy")), kind="smd")
        parts[el.get("name")] = dict(name=el.get("name"), package=el.get("package"), value=el.get("value"),
                                     xy=(ex, ey), rot=ang, geo=geo, pads=pads)
    polys = {}
    for sig in root.iter("signal"):
        for pg in sig.findall("polygon"):
            if int(pg.get("layer")) != L_TOP:
                continue
            pts = [(float(v.get("x")), float(v.get("y"))) for v in pg.findall("vertex")]
            polys.setdefault(sig.get("name"), []).append(dict(pts=pts, width=float(pg.get("width") or 0)))
    _CACHE[path] = dict(parts=parts, polys=polys, path=path)
    return _CACHE[path]


def extent(part, layers, outer=True, kinds=("wire", "rect", "poly", "circle")):
    """Bounding box (x0, y0, x1, y1) of a part's graphics on <layers>. outer=True adds the half line width
    (the drawn outer edge); outer=False uses the line centrelines (the package's nominal body dimension).
    kinds=("wire", "rect", "poly") leaves out circles, such as a pin-1 dot drawn outside the body."""
    xs, ys = [], []
    for lay in layers:
        for (px, py), hw, kind in part["geo"].get(lay, []):
            if kind not in kinds:
                continue
            h = hw if outer else 0.0
            xs += [px - h, px + h]
            ys += [py - h, py + h]
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def pads_in_order(partname, path=BRD):
    """Pad positions in package order. For the CHG (Ag105) package the order is the Ag105 pin order 1-22
    (VSEL..VIN+ = 1-10, MPPTD..VLOAD+2 = 11-22; outline_change_2026-11-12/connector.md F1)."""
    return [v["xy"] for v in load(path)["parts"][partname]["pads"].values()]


def pad(partname, padname, path=BRD):
    return load(path)["parts"][partname]["pads"][padname]["xy"]


def part(name, path=BRD):
    return load(path)["parts"][name]


def signal_polys(name, path=BRD):
    return load(path)["polys"].get(name, [])
