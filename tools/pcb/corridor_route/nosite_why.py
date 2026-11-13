"""Why a plane-net fill piece has no via site: which layer blocks its candidate via cells.

Usage (pcbnew venv; run from corridor_route):
  python nosite_why.py <model.json> <plan.json> <routes.json> <routed.kicad_pcb> [--min-area 0.3] [--net /GND]
         [--no-respect-unflashed]

Give it the same inputs as plane_vias.py (the routing result and the routed board with refilled zones). For each
fill piece of a plane net on a routing layer that holds no via and no through-hole pad of its net and has no free
candidate cell, it prints the number of candidate cells (inside the piece) and how many of them are blocked by:
  routed copper : the routing result, on each layer (RT.occV);
  obstacles     : copper of other nets in the model, on each layer (C.ownV);
  holes         : hole-to-hole spacing (C.holeBan);
  unflashed     : the unflashed layers of the net's own through-hole pads (Ctx.selfban; the default rule of
                  plane_vias.py, off with --no-respect-unflashed).
A cell can be blocked by several causes. A piece blocked mostly by routed copper on one layer is a routing fix
(move that track, interactively or by a plan change); a piece blocked by obstacles or holes is a placement or pour
request. Pieces that do have a free cell are not printed (plane_vias.py ties them, unless its via spacing stops it).
Positions are printed in both frames: KiCad (y down) and the plan's design frame."""
import argparse
import json

import numpy as np
import pcbnew
from shapely.geometry import Point, Polygon

from core import FREE, Ctx
from engine import Router

try:
    import wx
    wx.DisableAsserts()
except Exception:
    pass

ap = argparse.ArgumentParser()
ap.add_argument("model")
ap.add_argument("plan")
ap.add_argument("routes")
ap.add_argument("board")
ap.add_argument("--min-area", type=float, default=0.3)
ap.add_argument("--net", default=None, help="one plane net (default: every plane net of the plan)")
ap.add_argument("--respect-unflashed", action=argparse.BooleanOptionalAction, default=True)
A = ap.parse_args()
C = Ctx(A.model, A.plan)
RT = Router(C)
K = json.load(open(A.routes))
for r in K["results"]:
    if "cells" in r and r["net"] in C.assign:
        RT.contribute(r["net"], ([tuple(c) for c in r["cells"]], [tuple(v) for v in r["via_cells"]]), +1.0)
mm = pcbnew.ToMM
b = pcbnew.LoadBoard(A.board)
nets = [A.net] if A.net else sorted(C.planes)
ties = {}
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA" and t.GetNetname() in nets:
        ties.setdefault(t.GetNetname(), []).append((mm(t.GetPosition().x), mm(t.GetPosition().y)))
for fp in b.GetFootprints():
    for p in fp.Pads():
        if p.GetNetname() in nets and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
            ties.setdefault(p.GetNetname(), []).append((mm(p.GetPosition().x), mm(p.GetPosition().y)))
count = 0
for z in b.Zones():
    net = z.GetNetname()
    if z.GetIsRuleArea() or net not in nets:
        continue
    n = C.nid(net)
    ban = [gv for _, _, gv in C.selfban.get(net, [])] if A.respect_unflashed else []
    for lay in z.GetLayerSet().Seq():
        ln = b.GetLayerName(lay)
        if ln not in C.LAYERS:
            continue
        fl = z.GetFilledPolysList(lay)
        for k in range(fl.OutlineCount()):
            o = fl.Outline(k)
            pts = [(mm(o.CPoint(q).x), mm(o.CPoint(q).y)) for q in range(o.PointCount())]
            if len(pts) < 3:
                continue
            g = Polygon(pts).buffer(0)
            if g.area < A.min_area or any(g.contains(Point(x, y)) for x, y in ties.get(net, [])):
                continue
            j0, j1, i0, i1, m = C.raster(g)
            jj, ii = np.nonzero(m)
            if not len(jj):
                continue
            jj, ii = jj + j0, ii + i0
            occ = {C.LAYERS[li]: int((RT.occV[li, jj, ii] > 0).sum()) for li in range(C.NL)}
            own = {C.LAYERS[li]: int(((C.ownV[li, jj, ii] != FREE) & (C.ownV[li, jj, ii] != n)).sum())
                   for li in range(C.NL)}
            hole = int(C.holeBan[jj, ii].sum())
            unfl = [any(gv.contains(Point(*C.xy(j, i))) for gv in ban) for j, i in zip(jj, ii)]
            free = sum(1 for j, i, u in zip(jj, ii, unfl) if not C.holeBan[j, i] and not u
                       and not (RT.occV[:, j, i] > 0).any()
                       and np.all((C.ownV[:, j, i] == FREE) | (C.ownV[:, j, i] == n)))
            if free:
                continue
            count += 1
            c = g.representative_point()
            print("%s %s %s %.1f mm2 at KiCad (%.1f, %.1f) design (%.1f, %.1f): cells %d; routed copper %s; "
                  "obstacles %s; holes %d; unflashed %d" % (net, z.GetZoneName(), ln, g.area, c.x, c.y,
                                                           *C.d(c.x, c.y), len(jj), occ, own, hole, sum(unfl)))
print("%d pieces without a free candidate cell" % count)
