"""Plane-via step: tie every piece of a plane net's fills to the plane by a stitching via.

Usage (pcbnew venv with numpy + shapely):
  python plane_vias.py <model.json> <plan.json> <routes.json> <routed.kicad_pcb> <out_routes.json>
                       [--report plane_vias.md] [--min-area 0.3] [--no-respect-unflashed]

<routes.json> is the routing result that was applied to make <routed.kicad_pcb> (zones refilled). Tracks cut the
ground fills of the outer layers into pieces. A piece that holds no via and no through-hole pad of its net is not
tied to the plane layer, and every pad in it is open. For each such piece of at least --min-area mm2 the script
places one via of the plane net inside the piece, at a site that is free of the routed copper with full
clearance, not on an SMD pad and clear of holes; it prefers the site deepest inside the piece.

Output: <out_routes.json> with one entry for each plane net (vias to ADD; nothing is removed). Apply it to the
ROUTED board:  python apply_routes.py <routed board> <out_routes.json> <new folder>
then score the new board against the unrouted baseline: the open connections of the plane nets are the test.
The report lists the pieces that got no via; each is a request (no via site in the piece), or a sliver that
the island removal of the zone will delete.

Unflashed through-hole pads: by default a new via is kept off the unflashed layers of the through-hole pads of its
own net (Ctx.selfban, the rule the router uses for tracks). A plane via beside such a pad makes KiCad flash the pad
on that inner layer, onto the tracks that the router ran there (CR board, 2026-11-12: shorts at J1 pads 14 and 15
on In2.Cu at 3 of 4 seeds). On the round-3 CR seeds the rule cost 1 via site in 8 runs and no GND connection.
--no-respect-unflashed restores the earlier behaviour (no check), for comparison with results made before it.

SMD pads (2026-11-13): a new via is kept off every SMD pad of any net, grown by the pad's solder-mask expansion and
the via radius (charger EVM D-37, D-55: the step had put a /GND via inside the U101 exposed pad at every seed).
--allow-via-in-pad restores the earlier behaviour."""
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
ap.add_argument("out")
ap.add_argument("--report", default=None)
ap.add_argument("--min-area", type=float, default=0.3)
# default on; --respect-unflashed is still accepted (it was the opt-in form), --no-respect-unflashed turns it off
ap.add_argument("--respect-unflashed", action=argparse.BooleanOptionalAction, default=True)
ap.add_argument("--allow-via-in-pad", action="store_true",
                help="admit a new via on an SMD pad (the behaviour before 2026-11-13)")
A = ap.parse_args()
C = Ctx(A.model, A.plan)
RT = Router(C)
R, NL = C.R, C.NL
K = json.load(open(A.routes))
if abs(K["params"]["res"] - R) > 1e-9:
    raise SystemExit("the routes were made at grid %.4f, this plan gives %.4f" % (K["params"]["res"], R))
for r in K["results"]:
    if "cells" in r and r["net"] in C.assign:
        RT.contribute(r["net"], ([tuple(c) for c in r["cells"]], [tuple(v) for v in r["via_cells"]]), +1.0)
mm = pcbnew.ToMM
b = pcbnew.LoadBoard(A.board)
ties = {}                      # net -> [(x, y)] vias and through-hole pads: points that reach every layer
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA" and t.GetNetname() in C.planes:
        ties.setdefault(t.GetNetname(), []).append((mm(t.GetPosition().x), mm(t.GetPosition().y)))
for fp in b.GetFootprints():
    for p in fp.Pads():
        if p.GetNetname() in C.planes and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
            ties.setdefault(p.GetNetname(), []).append((mm(p.GetPosition().x), mm(p.GetPosition().y)))
vgap = (C.drill + C.hole2hole) / R
placed = {}
occV_any = RT.occV.max(axis=0) > 0
# No new via on any SMD pad of any net, own net included, grown by the pad's solder-mask expansion and the via
# radius (charger EVM D-37: no via on an SMD pad or in its mask opening; D-55 / review m-9: the step put a /GND via
# inside the U101 exposed pad, a /GND SMD pad, at every probe seed). --allow-via-in-pad restores the earlier rule.
from shapely.ops import unary_union  # noqa: E402
from shapely.prepared import prep  # noqa: E402
_smd = []
if not A.allow_via_in_pad:
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
            for lay, mlay in ((pcbnew.F_Cu, pcbnew.F_Mask), (pcbnew.B_Cu, pcbnew.B_Mask)):
                if not p.IsOnLayer(lay):
                    continue
                sps = p.GetEffectivePolygon(lay, pcbnew.ERROR_INSIDE)
                exp = mm(p.GetSolderMaskExpansion(mlay)) if p.IsOnLayer(mlay) else 0.0
                for q in range(sps.OutlineCount()):
                    o = sps.Outline(q)
                    pg = Polygon([(mm(o.CPoint(k).x), mm(o.CPoint(k).y)) for k in range(o.PointCount())])
                    _smd.append(pg.buffer(0).buffer(max(exp, 0.0) + C.via / 2, join_style=2))
SMD_KO = prep(unary_union(_smd)) if _smd else None


def via_ok(n, j, i):
    if C.holeBan[j, i] or occV_any[j, i]:
        return False
    if SMD_KO is not None and SMD_KO.contains(Point(*C.xy(j, i))):
        return False
    oV = C.ownV[:, j, i]
    if not np.all((oV == FREE) | (oV == n)):
        return False
    if A.respect_unflashed:
        x, y = C.xy(j, i)
        if any(gv.contains(Point(x, y)) for _, _, gv in C.selfban.get(C.net_name.get(n, ""), [])):
            return False
    return all((vj - j) ** 2 + (vi - i) ** 2 >= vgap * vgap for (vj, vi) in placed.get(n, []))


res, done, failed, small, pieces = {}, [], [], 0, 0
for z in b.Zones():
    net = z.GetNetname()
    if z.GetIsRuleArea() or net not in C.planes:
        continue
    n = C.nid(net)
    for lay in z.GetLayerSet().Seq():
        ln = b.GetLayerName(lay)
        if ln not in C.LAYERS:
            continue                                   # the plane layer itself is not a routing layer
        fl = z.GetFilledPolysList(lay)
        for k in range(fl.OutlineCount()):
            o = fl.Outline(k)
            pts = [(mm(o.CPoint(q).x), mm(o.CPoint(q).y)) for q in range(o.PointCount())]
            holes = []
            for h in range(fl.HoleCount(k)):
                ho = fl.Hole(k, h)
                holes.append([(mm(ho.CPoint(q).x), mm(ho.CPoint(q).y)) for q in range(ho.PointCount())])
            if len(pts) < 3:
                continue
            g = Polygon(pts, [h for h in holes if len(h) >= 3]).buffer(0)
            if g.is_empty:
                continue
            pieces += 1
            if any(g.contains(Point(x, y)) for (x, y) in ties.get(net, [])):
                continue
            if g.area < A.min_area:
                small += 1
                continue
            site = None
            for shrink in (C.via / 2 + 0.05, C.via / 4, 0.0):      # deepest inside first
                gi = g.buffer(-shrink) if shrink else g
                if gi.is_empty:
                    continue
                j0, j1, i0, i1, m = C.raster(gi)
                if not m.size:
                    continue
                rp = gi.representative_point()
                cand = sorted(((C.X[j0 + a, i0 + c] - rp.x) ** 2 + (C.Y[j0 + a, i0 + c] - rp.y) ** 2, j0 + a, i0 + c)
                              for a, c in zip(*np.nonzero(m)))
                for _, j, i in cand:
                    if via_ok(n, int(j), int(i)):
                        site = (int(j), int(i))
                        break
                if site:
                    break
            rp = g.representative_point()
            label = "%s on %s, %.1f mm2 at (%.1f, %.1f)" % ((z.GetZoneName() or net, ln, g.area) + C.d(rp.x, rp.y))
            if site is None:
                failed.append(label)
                continue
            placed.setdefault(n, []).append(site)
            x, y = C.xy(site[0], site[1])
            ties.setdefault(net, []).append((x, y))     # the new via also ties a piece of another layer here
            e = res.setdefault(net, dict(net=net, replace=False, tracks=[], widths=[], vias=[], via_d=[]))
            e["vias"].append([x, y])
            e["via_d"].append(C.via)
            done.append(label)
json.dump(dict(results=list(res.values()), keep_existing=True, routed_nets=[],
               params=dict(track=C.track, clear=C.clear, via=C.via, drill=C.drill, res=R)), open(A.out, "w"))
L = ["# Plane-via step", "",
     "Pieces of the fills of the plane nets (%s) on the routing layers: %d. Tied by a new via: %d. Without a via "
     "site: %d. Below %.1f mm2 and not tied (slivers, left to the island removal): %d." % (
         ", ".join(sorted(C.planes)), pieces, len(done), len(failed), A.min_area, small), "",
     "Vias kept off the unflashed layers of their own net's through-hole pads: %s." % (
         "yes" if A.respect_unflashed else "NO (--no-respect-unflashed; check the score for new DRC items)"), "",
     "## Pieces without a via site", ""] + (["- " + f for f in failed] or ["None."])
L += ["", "Apply the output to the routed board with `apply_routes.py`, then score the result against the unrouted "
      "board. The open connections of the plane nets in `score.md` are the test: 0 is a pass."]
txt = "\n".join(L) + "\n"
if A.report:
    open(A.report, "w", encoding="utf-8").write(txt)
print(txt)
