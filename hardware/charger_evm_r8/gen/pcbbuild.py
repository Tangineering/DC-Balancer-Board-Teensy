"""Build <board>.kicad_pcb from the schematic netlist and the layout module (layout_cr.py / layout_eib.py).

Frame: every design coordinate is an Eagle board coordinate (A.2: top view, MB origin, +x right, +y UP).
KiCad X = x, KiCad Y = YOFF - y (YOFF = 100 mm for the CR, so the CR lies at KiCad Y 24.00-65.86 mm).
Usage: python pcbbuild.py <board> <projdir>
"""
import importlib
import math
import os
import re
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

from shapely.geometry import Polygon, box, Point
from shapely.ops import unary_union
from shapely import affinity

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ------------------------------------------------------------------ netlist
def sexpr(text):
    toks = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+', text)
    stack = [[]]
    for t in toks:
        if t == "(":
            stack.append([])
        elif t == ")":
            x = stack.pop()
            stack[-1].append(x)
        else:
            stack[-1].append(t[1:-1] if t.startswith('"') else t)
    return stack[0][0]


def find(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def read_netlist(path):
    root = sexpr(open(path, encoding="utf-8").read())
    comps = {}
    for comp in find(find(root, "components")[0], "comp"):
        ref = find(comp, "ref")[0][1]
        val = find(comp, "value")[0][1]
        fp = find(comp, "footprint")[0][1]
        fields = {}
        for fl in find(comp, "fields"):
            for f in find(fl, "field"):
                name = find(f, "name")[0][1]
                fields[name] = f[2] if len(f) > 2 and not isinstance(f[2], list) else ""
        dnp = any(find(p, "name") and find(p, "name")[0][1] == "dnp" for p in find(comp, "property"))
        comps[ref] = dict(value=val, footprint=fp, fields=fields, dnp=dnp)
    nets = {}
    for net in find(find(root, "nets")[0], "net"):
        name = find(net, "name")[0][1]
        nodes = [(find(n, "ref")[0][1], find(n, "pin")[0][1]) for n in find(net, "node")]
        nets[name] = nodes
    return comps, nets


# ------------------------------------------------------------------ geometry helpers
class Frame:
    def __init__(self, yoff):
        self.yoff = yoff

    def v(self, x, y):
        return pcbnew.VECTOR2I_MM(x, self.yoff - y)

    def e(self, vec):
        return pcbnew.ToMM(vec.x), self.yoff - pcbnew.ToMM(vec.y)


def add_outline(board, fr, pts, layer=pcbnew.Edge_Cuts, width=0.1):
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(layer)
        s.SetWidth(pcbnew.FromMM(width))
        s.SetStart(fr.v(*a))
        s.SetEnd(fr.v(*b))
        board.Add(s)


def add_rule_area(board, fr, poly, layers, name, tracks=False, vias=False, pads=False, pour=False, fps=True):
    """Keep-out rule area; poly is a shapely Polygon in Eagle coordinates (holes supported)."""
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    z.SetZoneName(name)
    ls = pcbnew.LSET()
    for l in layers:
        ls.AddLayer(l)
    z.SetLayerSet(ls)
    z.SetDoNotAllowTracks(tracks)
    z.SetDoNotAllowVias(vias)
    z.SetDoNotAllowPads(pads)
    z.SetDoNotAllowCopperPour(pour)
    z.SetDoNotAllowFootprints(fps)
    ol = z.Outline()
    ol.NewOutline()
    for x, y in list(poly.exterior.coords)[:-1]:
        ol.Append(fr.v(x, y))
    for hole in poly.interiors:
        ol.NewHole()
        for x, y in list(hole.coords)[:-1]:
            ol.Append(fr.v(x, y), 0, ol.HoleCount(0) - 1)
    board.Add(z)
    return z


def _crt_polys(fp, fr, layer):
    fp.BuildCourtyardCaches()
    sps = fp.GetCourtyard(layer)
    polys = []
    for i in range(sps.OutlineCount()):
        o = sps.Outline(i)
        pts = [fr.e(o.CPoint(k)) for k in range(o.PointCount())]
        if len(pts) >= 3:
            polys.append(Polygon(pts).buffer(0))
    return unary_union(polys) if polys else None


def crt_rect(fp, fr):
    """Courtyard of a placed footprint on its own side, as a shapely geometry in Eagle coordinates."""
    g = _crt_polys(fp, fr, pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd)
    return g if g is not None else Polygon()


def other_crt_rect(fp, fr):
    """Courtyard on the opposite side (e.g. the CHG header bodies on B for a top-placed header)."""
    return _crt_polys(fp, fr, pcbnew.F_CrtYd if fp.IsFlipped() else pcbnew.B_CrtYd)


def place(fp, fr, x, y, rot, side):
    if side == "B" and not fp.IsFlipped():
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    fp.SetPosition(fr.v(x, y))
    fp.SetOrientationDegrees(rot)


def pad_e(fp, fr, num):
    for p in fp.Pads():
        if p.GetNumber() == num:
            return fr.e(p.GetPosition())
    return None


# ------------------------------------------------------------------ build
def build(board_name, projdir):
    L = importlib.import_module("layout_" + board_name)
    fr = Frame(L.YOFF)
    comps, nets = read_netlist(os.path.join(projdir, board_name + ".net"))
    lib = "charger_r8_" + board_name
    libdir = os.path.join(projdir, lib + ".pretty")
    b = pcbnew.BOARD()
    b.SetCopperLayerCount(L.LAYERS)
    ds = b.GetDesignSettings()
    if L.LAYERS == 4:
        b.SetLayerType(pcbnew.In1_Cu, pcbnew.LT_POWER)
    add_outline(b, fr, L.OUTLINE)
    # nets
    netinfo = {}
    for name in nets:
        ni = pcbnew.NETINFO_ITEM(b, name)
        b.Add(ni)
        netinfo[name] = ni
    pinnet = {}
    for name, nodes in nets.items():
        for ref, pin in nodes:
            pinnet[(ref, pin)] = name
    fps = {}
    for ref, c in sorted(comps.items()):
        libname, fpname = c["footprint"].split(":")
        fp = pcbnew.FootprintLoad(libdir, fpname)
        if fp is None:
            raise SystemExit("cannot load %s from %s" % (fpname, libdir))
        fp.SetFPID(pcbnew.LIB_ID(libname, fpname))
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        for k, v in c["fields"].items():
            if k in ("MPN", "Manufacturer", "Note") and v:
                fp.SetField(k, v)
                fld = fp.GetFieldByName(k)
                if fld:
                    fld.SetVisible(False)
        if c["dnp"]:
            fp.SetDNP(True)
        b.Add(fp)
        if c["fields"].get("Side") == "bottom":
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        for p in fp.Pads():
            n = pinnet.get((ref, p.GetNumber()))
            if n:
                p.SetNet(netinfo[n])
        fps[ref] = fp
    # board-only footprints (feet marks, fill hole, mounting holes)
    for ref, fpname, x, y, rot, side in L.BOARD_ONLY:
        fp = pcbnew.FootprintLoad(libdir, fpname)
        fp.SetFPID(pcbnew.LIB_ID(lib, fpname))
        fp.SetReference(ref)
        fp.SetValue(fpname)
        b.Add(fp)
        place(fp, fr, x, y, rot, side)
        fp.Reference().SetVisible(False)
        fps[ref] = fp
    # fixed placements
    for ref, (x, y, rot) in L.FIXED.items():
        fp = fps[ref]
        side = "B" if fp.IsFlipped() else "F"
        place(fp, fr, x, y, rot, side)
        if ref in L.ORIENT:
            orient(fp, fr, x, y, *L.ORIENT[ref])
    # rule areas
    keep = L.rule_areas()
    for name, poly, layers, opts in keep:
        geoms = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
        for i, g in enumerate(geoms):
            if g.area > 1e-4:
                add_rule_area(b, fr, g, layers, "%s_%d" % (name, i), **opts)
    # greedy placement
    log = greedy(b, fr, fps, L, pinnet)
    # silkscreen/fab notes
    for tx in getattr(L, "TEXTS", []):
        txt, x, y, layer, size = tx[:5]
        t = pcbnew.PCB_TEXT(b)
        t.SetText(txt)
        t.SetPosition(fr.v(x, y))
        t.SetLayer(layer)
        t.SetTextSize(pcbnew.VECTOR2I_MM(size, size))
        t.SetTextThickness(pcbnew.FromMM(0.15 if size >= 0.8 else 0.12))
        if len(tx) > 5 and tx[5] == "L":
            t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
        if layer in (pcbnew.B_SilkS, pcbnew.B_Fab):
            t.SetMirrored(True)
        b.Add(t)
    out = os.path.join(projdir, board_name + ".kicad_pcb")
    b.Save(out)
    with open(os.path.join(projdir, "placement_log.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log) + "\n")
    return out


def orient(fp, fr, x, y, pad, direction):
    """Choose the rotation (0/90/180/270) that puts <pad> on the <direction> side of the part centre
    (direction in Eagle terms: '+x', '-x', '+y', '-y')."""
    best = None
    for rot in (0, 90, 180, 270):
        fp.SetOrientationDegrees(rot)
        px, py = pad_e(fp, fr, pad)
        dx, dy = px - x, py - y
        score = {"+x": dx, "-x": -dx, "+y": dy, "-y": -dy}[direction]
        if best is None or score > best[0]:
            best = (score, rot)
    fp.SetOrientationDegrees(best[1])


def local_rects(fp, fr, rots):
    out = {}
    for rot in rots:
        fp.SetPosition(fr.v(0, 0))
        fp.SetOrientationDegrees(rot)
        g = crt_rect(fp, fr)
        if g.is_empty:
            continue
        out[rot] = tuple(round(v, 4) for v in g.bounds)
    return out


def greedy(b, fr, fps, L, pinnet):
    """Phased placement with the raster packer (packer.py). Regions, phases and targets come from the layout
    module; every placement is re-checked by the KiCad DRC afterwards."""
    import numpy as np
    import packer
    packer.MARGIN = getattr(L, "PACK_MARGIN", packer.MARGIN)   # routing channel kept around every courtyard
    log = []
    L.setup(fps)
    grid = packer.Grid(*L.GRID_BOUNDS)
    fixed = set(L.FIXED) | {r[0] for r in L.BOARD_ONLY}
    occ = {"F": np.zeros((grid.ny, grid.nx), bool), "B": np.zeros((grid.ny, grid.nx), bool)}

    def mark(fp):
        side = "B" if fp.IsFlipped() else "F"
        for s_, g in ((side, crt_rect(fp, fr)), ("F" if side == "B" else "B", other_crt_rect(fp, fr))):
            if g is not None and not g.is_empty:
                occ[s_] |= grid.mask(g.buffer(packer.MARGIN))

    for ref in fixed:
        mark(fps[ref])
    masks = {}
    phases = list(L.PHASES)
    while phases:
        ph = phases.pop(0)
        phase_name, side, refs = ph[:3]
        fallback = ph[3] if len(ph) > 3 else None
        forced = ph[4] if len(ph) > 4 else None
        base_margin = getattr(L, 'PACK_MARGIN', 0.03)
        packer.MARGIN = getattr(L, 'PHASE_MARGIN', {}).get(phase_name.replace(' fallback', ''), base_margin)
        parts = []
        for ref in refs:
            fp = fps[ref]
            rn = forced or L.region_name(ref)
            if rn not in masks:
                masks[rn] = grid.mask(L.REGIONS[rn])
            rects = local_rects(fp, fr, L.rotations(ref))
            (dx0, dy0, dx1, dy1) = rects[min(rects)]
            parts.append(dict(ref=ref, region=rn, rects=rects,
                              target=None if L.fill(ref, phase_name) else L.target(ref, fps, fr, pinnet),
                              size=(dx1 - dx0) * (dy1 - dy0), prio=L.prio(ref)))
        res = packer.pack(grid, parts, occ[side], masks, tries=L.TRIES, seed=7, log=log)
        for p in parts:
            fp = fps[p["ref"]]
            if p["ref"] in res:
                x, y, rot = res[p["ref"]]
                place(fp, fr, x, y, rot, side)
                mark(fp)
                L.PLACED.add(p["ref"])
                t = p["target"]
                log.append("%-6s %s %-12s (%.3f, %.3f) rot %d  target %s" % (
                    p["ref"], side, p["region"], x, y, rot, "(%.2f, %.2f)" % t if t else "-"))
            else:
                place(fp, fr, L.PARK[0], L.PARK[1], 0, side)
                log.append("%-6s %s %-12s UNPLACED%s" % (p["ref"], side, p["region"],
                                                       " -> fallback %s" % fallback if fallback else ""))
        left = [p["ref"] for p in parts if p["ref"] not in res]
        if left and fallback:
            phases.insert(0, (phase_name + " fallback", side, left, None, fallback))
        log.append("phase %s done" % phase_name)
    return log


if __name__ == "__main__":
    print(build(sys.argv[1], sys.argv[2]))
