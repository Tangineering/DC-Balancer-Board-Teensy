"""Final step after routing: propose a trimmed board outline with corner mounting holes, and check it on a copy.

Usage (pcbnew venv):
  python trim_outline.py <routed board.kicad_pcb> <out dir> [--y-flip-offset Y0] [--margin 1.0]
      [--ear X0,Y0,X1,Y1 ...] [--holes 4] [--hole-drill 3.7] [--hole-keepout 4.0] [--hole-gap 0.5]
      [--flip-centre CX,CY --flip-block NAME:X0,Y0,X1,Y1 ...] [--apply]

The used area is the union of every footprint courtyard and pad, every track and via, and every zone that is not a
board-wide fill (a zone larger than half the board, such as a ground fill or a plane), grown by --margin. Each --ear
box (plan frame) is added: area kept for a mechanical reason, such as a keying overhang. One mounting hole is placed
at each corner of the bounding box of that area: within --hole-search mm of the corner, the site whose disc of radius
--hole-keepout clears the used area by --hole-gap, whose disc of radius --hole-board (the screw head) lies inside the
present outline, and that adds the least area to the outline. The proposed outline is the convex hull of the used
area, the ears and the --hole-board discs, clipped to the present outline (the outline never grows).
Defaults suit a 6-32 screw: drill 3.7 mm (#6 free fit), head disc 3.6 mm, copper keep-out 4.0 mm.

With --flip-centre and --flip-block (plan frame), the outline is turned by 180 degrees about the centre and its overlap
with each block is reported: a board that relies on landing on those blocks when it is fitted the wrong way round
keeps its key only while the overlap stays.

--apply writes <out dir>/<board>.kicad_pcb: the new Edge.Cuts outline, the holes as non-plated footprints MH1..MHn
with an all-layer copper keep-out of radius --hole-keepout, every zone clipped to the new outline (a zone whose
outline ran along the old edge keeps the same inset from the new edge), the copper of plane nets that lies outside
the new outline or too close to it (stitching vias) removed, and every zone refilled. It refuses when routed signal
copper lies outside the proposed outline. The copy is a check of the proposal; the outline belongs to the project's
generator, which the design owner changes.

Writes <out dir>/trim.json and <out dir>/TRIM.md (frames: plan frame when --y-flip-offset is given).
"""
import argparse
import json
import math
import os
import shutil

import pcbnew
from shapely.affinity import rotate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

ap = argparse.ArgumentParser()
ap.add_argument("board")
ap.add_argument("out")
ap.add_argument("--y-flip-offset", type=float, default=None)
ap.add_argument("--margin", type=float, default=1.0)
ap.add_argument("--ear", action="append", default=[])
ap.add_argument("--holes", type=int, default=4, choices=(0, 4))
ap.add_argument("--hole-drill", type=float, default=3.7)
ap.add_argument("--hole-keepout", type=float, default=4.0)
ap.add_argument("--hole-gap", type=float, default=0.5)
ap.add_argument("--hole-board", type=float, default=3.6, help="board radius kept around each hole (screw head)")
ap.add_argument("--hole-search", type=float, default=15.0, help="half-size of the search window at each corner")
ap.add_argument("--flip-centre", default=None)
ap.add_argument("--flip-block", action="append", default=[])
ap.add_argument("--plane-nets", default="/GND")
ap.add_argument("--edge-clear", type=float, default=0.5, help="plane copper closer than this to the new edge is removed")
ap.add_argument("--apply", action="store_true")
A = ap.parse_args()
mm, FMM = pcbnew.ToMM, pcbnew.FromMM
Y0 = A.y_flip_offset


def to_plan(x, y):
    return (x, Y0 - y) if Y0 is not None else (x, y)


def plan_geom(g):
    """KiCad-frame geometry -> plan frame (a mirror in y)"""
    from shapely.affinity import affine_transform
    return affine_transform(g, [1, 0, 0, -1, 0, Y0]) if Y0 is not None else g


def kicad_box(x0, y0, x1, y1):
    if Y0 is None:
        return box(x0, y0, x1, y1)
    return box(x0, Y0 - y1, x1, Y0 - y0)


def poly_of(sps):
    out = []
    for i in range(sps.OutlineCount()):
        o = sps.Outline(i)
        pts = [(mm(o.CPoint(k).x), mm(o.CPoint(k).y)) for k in range(o.PointCount())]
        holes = []
        for h in range(sps.HoleCount(i)):
            ho = sps.Hole(i, h)
            hp = [(mm(ho.CPoint(k).x), mm(ho.CPoint(k).y)) for k in range(ho.PointCount())]
            if len(hp) >= 3:
                holes.append(hp)
        if len(pts) >= 3:
            out.append(Polygon(pts, holes).buffer(0))     # holes kept: an edge band is a ring
    return unary_union(out) if out else Polygon()


b = pcbnew.LoadBoard(A.board)
TRACKS, ZONES = list(b.GetTracks()), list(b.Zones())      # read once: the containers break after a Remove
plane = {n for n in A.plane_nets.split(",") if n}
sps = pcbnew.SHAPE_POLY_SET()
b.GetBoardPolygonOutlines(sps)
old = poly_of(sps)
used = []
for fp in b.GetFootprints():
    for lay in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
        c = fp.GetCourtyard(lay)
        if c.OutlineCount():
            used.append(poly_of(c))
    for p in fp.Pads():
        for lid in (pcbnew.F_Cu, pcbnew.B_Cu):
            if p.IsOnLayer(lid):
                used.append(poly_of(p.GetEffectivePolygon(lid, pcbnew.ERROR_INSIDE)))
signal_cu = []
for t in TRACKS:
    if t.GetClass() == "PCB_VIA":
        g = Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetWidth(pcbnew.F_Cu)) / 2)
    else:
        s, e = t.GetStart(), t.GetEnd()
        g = LineString([(mm(s.x), mm(s.y)), (mm(e.x), mm(e.y))]).buffer(mm(t.GetWidth()) / 2)
    if t.GetNetname() in plane and t.GetClass() == "PCB_VIA" and not t.IsLocked():
        continue                     # stitching and plane vias: they follow the outline
    used.append(g)
    signal_cu.append(g)
wide = []


def board_wide(g):
    """a zone that follows the outline: its outer contour covers more than half the board (a ring counts too)"""
    gs = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
    return any(Polygon(p.exterior).area > 0.5 * old.area for p in gs if not p.is_empty)


for z in ZONES:
    if z.GetIsRuleArea():
        continue
    zg = poly_of(z.Outline())
    if board_wide(zg):
        wide.append(z.GetZoneName())
        continue
    used.append(zg)
U0 = unary_union(used)
U = U0.buffer(A.margin, join_style=2)
ears = [kicad_box(*map(float, e.split(","))) for e in A.ear]
core = unary_union([U] + ears)

holes = []
hull = core.convex_hull
if A.holes:
    from shapely.prepared import prep
    clear = prep(U0.buffer(A.hole_gap))
    inside = prep(old.buffer(-A.hole_board))         # the screw head stays on the board, inside the present outline
    x0, y0, x1, y1 = core.bounds
    for cx, cy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        best = None
        n = int(2 * A.hole_search / 0.25) + 1
        for a in range(n):
            for c in range(n):
                x, y = cx - A.hole_search + 0.25 * a, cy - A.hole_search + 0.25 * c
                pt = Point(x, y)
                if not inside.contains(pt) or clear.intersects(pt.buffer(A.hole_keepout, 16)):
                    continue
                area = unary_union([hull, pt.buffer(A.hole_board, 16)]).convex_hull.area
                key = (round(area, 1), math.hypot(x - cx, y - cy))
                if best is None or key < best[0]:
                    best = (key, (round(x, 2), round(y, 2)))
        if best is None:
            raise SystemExit("no hole site within %.1f mm of the corner (%.2f, %.2f)" % (A.hole_search, *to_plan(cx, cy)))
        holes.append(best[1])
        hull = unary_union([hull, Point(*best[1]).buffer(A.hole_board, 32)]).convex_hull
new = hull.intersection(old)
new = Polygon([(round(x, 2), round(y, 2)) for x, y in new.exterior.coords]).simplify(0.05)
# A vertex that the 0.01 mm rounding put within 0.011 mm of the clip edge (the present outline) goes back onto that
# edge: on the r9 CR the rounding put the -x vertices 0.004 mm outside the D-39 edge. The simplification above keeps a
# subset of the vertices and does not move them, so the vertex list is the same as without this step.
_snap = []
for x, y in list(new.exterior.coords)[:-1]:
    q = Point(x, y)
    if old.exterior.distance(q) < 0.011:
        q = old.exterior.interpolate(old.exterior.project(q))
        x, y = round(q.x, 4), round(q.y, 4)
    _snap.append((x, y))
new = Polygon(_snap)
warn = []
for i, (x, y) in enumerate(holes, 1):
    d = new.exterior.distance(Point(x, y)) - A.hole_drill / 2
    if not new.contains(Point(x, y)) or d < 1.0:
        warn.append("MH%d: hole edge %.2f mm from the new edge (below 1.0 mm); the present outline limits it" % (i, d))
outside = unary_union(signal_cu).difference(new.buffer(-0.381)) if signal_cu else Polygon()
if outside.area > 1e-6:
    warn.append("routed signal copper lies within 0.381 mm of or outside the proposed edge (%.3f mm2)" % outside.area)

flip = []
if A.flip_centre:
    fx, fy = map(float, A.flip_centre.split(","))
    kc = (fx, Y0 - fy) if Y0 is not None else (fx, fy)
    for which, outline in (("present", old), ("proposed", new)):
        r = rotate(outline, 180, origin=kc)
        for fb in A.flip_block:
            name, coords = fb.split(":")
            bl = kicad_box(*map(float, coords.split(",")))
            ov = r.intersection(bl)
            flip.append(dict(outline=which, block=name, overlap_mm2=round(ov.area, 1),
                             overlap_x_mm=round(ov.bounds[2] - ov.bounds[0], 2) if not ov.is_empty else 0.0))

os.makedirs(A.out, exist_ok=True)
newp = plan_geom(new)
res = dict(board=os.path.abspath(A.board), frame="plan (y = %s - KiCad y)" % Y0 if Y0 is not None else "KiCad",
           area_present_mm2=round(old.area, 1), area_proposed_mm2=round(new.area, 1),
           used_bounds_plan=[round(v, 2) for v in plan_geom(U0).bounds], margin=A.margin,
           outline_plan=[[round(x, 4), round(y, 4)] for x, y in list(newp.exterior.coords)[:-1]],
           ears_plan=A.ear, holes_plan=[list(to_plan(x, y)) for x, y in holes], hole_drill=A.hole_drill,
           hole_keepout=A.hole_keepout, board_wide_zones=wide, flip=flip, warnings=warn)

if A.apply:
    if any("signal copper" in w for w in warn):
        raise SystemExit("refused: " + "; ".join(warn))
    dst = os.path.join(A.out, os.path.basename(A.board))
    src_dir = os.path.dirname(os.path.abspath(A.board))
    for f in os.listdir(src_dir):
        p = os.path.join(src_dir, f)
        if os.path.isfile(p) and not f.endswith((".kicad_pcb", ".bak")) and not f.startswith("_autosave"):
            shutil.copy2(p, A.out)
        elif os.path.isdir(p) and f.endswith(".pretty"):
            shutil.copytree(p, os.path.join(A.out, f), dirs_exist_ok=True)
    removed = 0
    for t in TRACKS:
        if t.GetNetname() not in plane:
            continue
        g = (Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetWidth(pcbnew.F_Cu)) / 2)
             if t.GetClass() == "PCB_VIA" else
             LineString([(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))]).buffer(
                 mm(t.GetWidth()) / 2))
        if not new.buffer(-A.edge_clear).contains(g) or any(
                Point(x, y).buffer(A.hole_keepout).intersects(g) for x, y in holes):
            b.Remove(t)
            removed += 1
    clipped = []
    for z in ZONES:
        zg = poly_of(z.Outline())
        if zg.is_empty or not board_wide(zg):
            continue                           # a local zone keeps its outline
        if zg.geom_type == "MultiPolygon":
            zg = max(zg.geoms, key=lambda g: g.area)
        if z.GetIsRuleArea() and zg.interiors:
            # an edge band: a ring between the outline and an inner contour; keep its width
            w = old.exterior.distance(Point(zg.interiors[0].coords[0]))
            ng = new.difference(new.buffer(-w, join_style=2))
            tag = "band %.2f mm" % w
        else:
            inset = min(old.exterior.distance(Point(c)) for c in zg.exterior.coords)
            ng = new.buffer(-inset, join_style=2)
            for h in zg.interiors:
                ng = ng.difference(Polygon(h))
            tag = "inset %.2f mm" % inset
        if ng.is_empty:
            continue
        gs = list(ng.geoms) if ng.geom_type == "MultiPolygon" else [ng]
        ol = z.Outline()
        ol.RemoveAllContours()
        for g in gs:
            oi = ol.NewOutline()
            for x, y in list(g.exterior.coords)[:-1]:
                ol.Append(FMM(x), FMM(y), oi, -1)
            for h in g.interiors:
                hi = ol.NewHole(oi)
                for x, y in list(h.coords)[:-1]:
                    ol.Append(FMM(x), FMM(y), oi, hi)
        clipped.append("%s (%s)" % (z.GetZoneName() or z.GetNetname(), tag))
    for i, (x, y) in enumerate(holes, 1):
        fp = pcbnew.FOOTPRINT(b)
        fp.SetReference("MH%d" % i)
        fp.SetValue("6-32 hole %.2f mm" % A.hole_drill)
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
        fp.SetAttributes(pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES | pcbnew.FP_BOARD_ONLY)
        fp.SetPosition(pcbnew.VECTOR2I(FMM(x), FMM(y)))
        pad = pcbnew.PAD(fp)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
        pad.SetSize(pcbnew.VECTOR2I(FMM(A.hole_drill), FMM(A.hole_drill)))
        pad.SetDrillSize(pcbnew.VECTOR2I(FMM(A.hole_drill), FMM(A.hole_drill)))
        ls = pcbnew.LSET.AllCuMask()
        ls.AddLayer(pcbnew.F_Mask)
        ls.AddLayer(pcbnew.B_Mask)
        pad.SetLayerSet(ls)
        pad.SetNumber("")
        fp.Add(pad)
        pad.SetPosition(pcbnew.VECTOR2I(FMM(x), FMM(y)))
        b.Add(fp)
        ko = pcbnew.ZONE(b)
        ko.SetIsRuleArea(True)
        ko.SetZoneName("MH%d_keepout" % i)
        ko.SetLayerSet(pcbnew.LSET.AllCuMask())
        ko.SetDoNotAllowTracks(True)
        ko.SetDoNotAllowVias(True)
        ko.SetDoNotAllowPads(False)
        getattr(ko, "SetDoNotAllowZoneFills", None) and ko.SetDoNotAllowZoneFills(True)
        getattr(ko, "SetDoNotAllowCopperPour", None) and ko.SetDoNotAllowCopperPour(True)
        ko.SetDoNotAllowFootprints(False)
        ol = ko.Outline()
        oi = ol.NewOutline()
        for k in range(32):
            a = 2 * math.pi * k / 32
            ol.Append(FMM(x + A.hole_keepout * math.cos(a)), FMM(y + A.hole_keepout * math.sin(a)), oi, -1)
        b.Add(ko)
    for d in list(b.GetDrawings()):
        if d.GetLayer() == pcbnew.Edge_Cuts:
            b.Remove(d)
    pts = list(new.exterior.coords)[:-1]
    for k in range(len(pts)):
        s = pcbnew.PCB_SHAPE(b)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(FMM(0.05))
        s.SetStart(pcbnew.VECTOR2I(FMM(pts[k][0]), FMM(pts[k][1])))
        s.SetEnd(pcbnew.VECTOR2I(FMM(pts[(k + 1) % len(pts)][0]), FMM(pts[(k + 1) % len(pts)][1])))
        b.Add(s)
    b.Save(dst)
    b2 = pcbnew.LoadBoard(dst)                 # refill in a fresh load of the saved file
    pcbnew.ZONE_FILLER(b2).Fill(b2.Zones())
    b2.Save(dst)
    res.update(applied=dst, plane_copper_removed=removed, zones_clipped=clipped)

json.dump(res, open(os.path.join(A.out, "trim.json"), "w"), indent=1)
L = ["# Trimmed outline proposal", "",
     "Board: `%s`. Frame: %s." % (res["board"], res["frame"]), "",
     "| Item | Value |", "|---|---|",
     "| Present outline area | %.1f mm2 |" % res["area_present_mm2"],
     "| Proposed outline area | %.1f mm2 (%.0f %%) |" % (res["area_proposed_mm2"],
                                                       100 * res["area_proposed_mm2"] / res["area_present_mm2"]),
     "| Used area bounds (courtyards, pads, signal copper, local pours) | x %.2f-%.2f, y %.2f-%.2f |"
     % tuple(res["used_bounds_plan"][i] for i in (0, 2, 1, 3)),
     "| Margin around the used area | %.2f mm |" % A.margin,
     "| Ears kept | %s |" % ("; ".join(A.ear) or "none"),
     "| Board-wide zones (follow the outline) | %s |" % (", ".join(wide) or "none"), "",
     "Proposed outline vertices: %s" % ", ".join("(%.2f, %.2f)" % tuple(v) for v in res["outline_plan"]), ""]
if holes:
    L += ["Mounting holes (non-plated, drill %.2f mm, copper keep-out radius %.2f mm on every layer):" % (
        A.hole_drill, A.hole_keepout), ""]
    L += ["- MH%d at (%.2f, %.2f)" % (i, x, y) for i, (x, y) in enumerate(res["holes_plan"], 1)] + [""]
if flip:
    L += ["Overlap of the outline, turned 180 degrees about %s, with each block:" % A.flip_centre, "",
          "| Outline | Block | Overlap mm2 | Overlap in x mm |", "|---|---|---|---|"]
    L += ["| %s | %s | %.1f | %.2f |" % (f["outline"], f["block"], f["overlap_mm2"], f["overlap_x_mm"]) for f in flip]
    L += [""]
if A.apply:
    L += ["Applied copy: `%s`. Plane copper removed: %d. Zones clipped: %s." % (
        res["applied"], res["plane_copper_removed"], ", ".join(res["zones_clipped"]) or "none"), ""]
L += ["Warnings: " + ("; ".join(warn) if warn else "none")]
open(os.path.join(A.out, "TRIM.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
print("\n".join(L))
