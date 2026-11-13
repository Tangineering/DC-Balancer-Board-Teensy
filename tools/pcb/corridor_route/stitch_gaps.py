"""Stitching gap fill on the finished board: add plane-net vias until every point of a plane pour lies within a
distance limit of a via or plated hole of that net.

Usage (pcbnew venv):
  python stitch_gaps.py <board.kicad_pcb> <out dir> [--net /GND] [--layer B.Cu] [--limit 3.54] [--sample 0.5]
                        [--clear 0.1524] [--hole-gap 0.127] [--edge-band 0.4] [--y-flip-offset Y0] [--max-add 50]

The grid stitching of plane_vias.py --stitch places a via only within half a pitch of each grid node, so dense
areas can keep a gap. This pass works on the board's own copper (after straightening and trimming, when the
router's grid occupancy is out of date). It samples the filled pour of --net on --layer on a --sample grid and
measures the distance from each sample to the nearest via or plated through-hole of the net (the stitch points).
While the largest distance exceeds --limit, it takes the worst sample and adds a via at the legal site nearest to
it, within --limit of it. A site is legal when the via (the board's via size) keeps --clear from the copper of every
other net on every copper layer (pads, tracks, vias, pours), keeps --hole-gap between hole edges, lies outside every
SMD pad's solder-mask opening (the pad grown by its mask expansion, at least 0.05 mm, square corners), off the pad of
an unflashed through-hole pad of its own net, outside every keep-out that forbids vias, and inside the outline less
--edge-band. A worst sample with no legal site that would bring it under the limit is reported and skipped.

The default limit 3.54 mm is the largest distance on a 5 mm square stitching grid (5 / sqrt 2).

Writes <out dir>/<board>.kicad_pcb (zones refilled) and <out dir>/STITCH_GAPS.md. Run DRC on the result.
"""
import argparse
import math
import os
import shutil

import numpy as np
import pcbnew
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep
from shapely.strtree import STRtree

ap = argparse.ArgumentParser()
ap.add_argument("board")
ap.add_argument("out")
ap.add_argument("--net", default="/GND")
ap.add_argument("--layer", default="B.Cu")
ap.add_argument("--limit", type=float, default=3.54)
ap.add_argument("--sample", type=float, default=0.5)
ap.add_argument("--clear", type=float, default=0.1524)
ap.add_argument("--hole-gap", type=float, default=0.127)
ap.add_argument("--edge-band", type=float, default=0.4)
ap.add_argument("--y-flip-offset", type=float, default=None)
ap.add_argument("--max-add", type=int, default=50)
A = ap.parse_args()
mm, FMM = pcbnew.ToMM, pcbnew.FromMM
Y0 = A.y_flip_offset


def plan(x, y):
    return (x, Y0 - y) if Y0 is not None else (x, y)


def poly(sps):
    out = []
    for i in range(sps.OutlineCount()):
        o = sps.Outline(i)
        pts = [(mm(o.CPoint(k).x), mm(o.CPoint(k).y)) for k in range(o.PointCount())]
        hs = []
        for h in range(sps.HoleCount(i)):
            ho = sps.Hole(i, h)
            hs.append([(mm(ho.CPoint(k).x), mm(ho.CPoint(k).y)) for k in range(ho.PointCount())])
        if len(pts) >= 3:
            out.append(Polygon(pts, [h for h in hs if len(h) >= 3]).buffer(0))
    return unary_union(out) if out else Polygon()


b = pcbnew.LoadBoard(A.board)
TRACKS, ZONES = list(b.GetTracks()), list(b.Zones())
ds = b.GetDesignSettings()
VIA_D = mm(ds.GetCurrentViaSize()) or 0.6
VIA_DR = mm(ds.GetCurrentViaDrill()) or 0.3
layers = {b.GetLayerName(l): l for l in (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu)
          if b.IsLayerEnabled(l)}
cu = {ln: [] for ln in layers}
drills, mask_open, unfl, keep, stitch = [], [], [], [], []
for fp in b.GetFootprints():
    for p in fp.Pads():
        net, c = p.GetNetname(), p.GetPosition()
        pc = (mm(c.x), mm(c.y))
        if p.GetDrillSizeX() > 0:
            drills.append(Point(pc).buffer(mm(p.GetDrillSizeX()) / 2))
            if net == A.net and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                stitch.append(pc)
        for ln, lid in layers.items():
            if p.IsOnLayer(lid) and p.FlashLayer(lid):
                g = poly(p.GetEffectivePolygon(lid, pcbnew.ERROR_INSIDE))
                if net != A.net:
                    cu[ln].append(g)
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and lid in (pcbnew.F_Cu, pcbnew.B_Cu):
                    ml = pcbnew.F_Mask if lid == pcbnew.F_Cu else pcbnew.B_Mask
                    e = mm(p.GetSolderMaskExpansion(ml)) if p.IsOnLayer(ml) else 0.0
                    mask_open.append(g.buffer(max(e, 0.05), join_style=2))
            elif p.GetDrillSizeX() > 0 and p.IsOnLayer(lid) and net == A.net:
                unfl.append(Point(pc).buffer(max(mm(p.GetSizeX()), mm(p.GetSizeY())) / 2))
for t in TRACKS:
    net = t.GetNetname()
    if t.GetClass() == "PCB_VIA":
        c = t.GetPosition()
        pc = (mm(c.x), mm(c.y))
        drills.append(Point(pc).buffer(mm(t.GetDrill()) / 2))
        if net == A.net:
            stitch.append(pc)
        else:
            for ln in layers:
                cu[ln].append(Point(pc).buffer(mm(t.GetWidth(pcbnew.F_Cu)) / 2))
    elif net != A.net:
        s, e = t.GetStart(), t.GetEnd()
        ln = b.GetLayerName(t.GetLayer())
        if ln in cu:
            cu[ln].append(LineString([(mm(s.x), mm(s.y)), (mm(e.x), mm(e.y))]).buffer(mm(t.GetWidth()) / 2))
pour = []
for z in ZONES:
    if z.GetIsRuleArea():
        if z.GetDoNotAllowVias():
            keep.append(poly(z.Outline()))
        continue
    for l in z.GetLayerSet().Seq():
        ln = b.GetLayerName(l)
        g = poly(z.GetFilledPolysList(l))
        if z.GetNetname() == A.net:
            if ln == A.layer:
                pour.append(g)
        elif ln in cu:
            cu[ln].append(g)
sps = pcbnew.SHAPE_POLY_SET()
b.GetBoardPolygonOutlines(sps)
inside = prep(poly(sps).buffer(-(A.edge_band + VIA_D / 2)))
trees = [STRtree(g) for g in cu.values() if g]
dtree = STRtree(drills)
mo = prep(unary_union(mask_open)) if mask_open else None
uf = prep(unary_union(unfl)) if unfl else None
ko = prep(unary_union(keep)) if keep else None
pour = unary_union(pour)


def legal(x, y):
    pt = Point(x, y)
    if not inside.contains(pt):
        return False
    v = pt.buffer(VIA_D / 2, 32)
    vc = v.buffer(A.clear)
    if any(len(tr.query(vc, predicate="intersects")) for tr in trees):
        return False
    if len(dtree.query(pt.buffer(VIA_DR / 2 + A.hole_gap), predicate="intersects")):
        return False
    for g in (mo, uf, ko):
        if g is not None and g.intersects(v):
            return False
    return True


# samples of the plane pour
x0, y0, x1, y1 = pour.bounds
pp = prep(pour)
samples = np.array([(x, y) for x in np.arange(x0, x1, A.sample) for y in np.arange(y0, y1, A.sample)
                    if pp.contains(Point(x, y))])


def worst(pts):
    S = np.array(pts)
    d = np.sqrt(((samples[:, None, :] - S[None, :, :]) ** 2).sum(-1)).min(1)
    return d


d = worst(stitch)
before = float(d.max())
added, skipped = [], []
skip = np.zeros(len(samples), bool)
while len(added) < A.max_add:
    dd = np.where(skip, -1, d)
    k = int(dd.argmax())
    if dd[k] <= A.limit:
        break
    wx, wy = samples[k]
    best = None
    step = 0.05
    r = A.limit
    n = int(2 * r / step) + 1
    for a in range(n):
        for c in range(n):
            x, y = wx - r + step * a, wy - r + step * c
            q = (x - wx) ** 2 + (y - wy) ** 2
            if q > r * r or (best is not None and q >= best[0]):
                continue
            if legal(x, y):
                best = (q, x, y)
    if best is None:
        skipped.append((wx, wy, float(dd[k])))
        skip |= np.hypot(samples[:, 0] - wx, samples[:, 1] - wy) < A.sample * 1.5
        continue
    _, x, y = best
    x, y = round(float(x), 3), round(float(y), 3)          # numpy floats: pcbnew.FromMM takes Python floats only
    added.append((x, y))
    stitch.append((x, y))
    drills.append(Point(x, y).buffer(VIA_DR / 2))
    dtree = STRtree(drills)
    d = np.minimum(d, np.hypot(samples[:, 0] - x, samples[:, 1] - y))
after = float(np.where(skip, -1, d).max()) if len(samples) else 0.0
after_all = float(d.max()) if len(samples) else 0.0

netinfo = b.FindNet(A.net)
for x, y in added:
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(pcbnew.VECTOR2I(FMM(x), FMM(y)))
    v.SetWidth(FMM(VIA_D))
    v.SetDrill(FMM(VIA_DR))
    v.SetNet(netinfo)
    b.Add(v)
os.makedirs(A.out, exist_ok=True)
src = os.path.dirname(os.path.abspath(A.board))
for f in os.listdir(src):
    p = os.path.join(src, f)
    if os.path.isfile(p) and not f.endswith((".kicad_pcb", ".bak")) and not f.startswith("_autosave"):
        shutil.copy2(p, A.out)
    elif os.path.isdir(p) and f.endswith(".pretty"):
        shutil.copytree(p, os.path.join(A.out, f), dirs_exist_ok=True)
dst = os.path.join(A.out, os.path.basename(A.board))
b.Save(dst)
b2 = pcbnew.LoadBoard(dst)
pcbnew.ZONE_FILLER(b2).Fill(b2.Zones())
b2.Save(dst)
L = ["# Stitching gap fill", "",
     "Net %s, pour on %s, %d samples at %.2f mm, limit %.2f mm, via %.2f / %.2f mm." % (
         A.net, A.layer, len(samples), A.sample, A.limit, VIA_D, VIA_DR), "",
     "| Measure | Value |", "|---|---|",
     "| Stitch points before | %d |" % (len(stitch) - len(added)),
     "| Largest distance before | %.2f mm |" % before,
     "| Vias added | %d |" % len(added),
     "| Largest distance after | %.2f mm |" % after_all, ""]
L += ["Added vias (%s frame):" % ("design" if Y0 is not None else "KiCad"), ""]
L += ["- (%.2f, %.2f)" % plan(x, y) for x, y in added] or ["- none"]
L += ["", "Samples above the limit with no legal site within the limit:", ""]
L += ["- (%.2f, %.2f): %.2f mm" % (plan(x, y) + (dd_,)) for x, y, dd_ in skipped] or ["- none"]
txt = "\n".join(L) + "\n"
open(os.path.join(A.out, "STITCH_GAPS.md"), "w", encoding="utf-8").write(txt)
print(txt)
