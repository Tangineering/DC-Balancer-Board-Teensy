"""REVIEW_2026-11-14 CRL-8 (and its EIB analogue): OSH Park plates a hole when there is copper under the drill and leaves
it unplated when there is none ("Our fabs use the presence of copper to determine whether or not a drill will be
plated. Copper under a drill means via/plated hole, no copper means unplated hole.",
https://docs.oshpark.com/design-tools/diptrace/producing-plated-vias/, read 2026-11-14). The OSH Park upload of
gen/export.sh is the KiKit OSH Park package, whose single drill file merges the NPTH holes into a MixedPlating file;
the NonPlated attribute there is informational only, so an NPTH hole is built unplated only if no copper lies on or
around it. This check makes that a gate of the export.

For every NPTH pad of the board it measures, on every copper layer, the gap from the hole edge to the nearest copper
(pads, tracks, vias, filled zones, the NPTH pad's own copper included). A gap <= 0 (copper under the drill: OSH Park
would plate the hole) fails; a gap below MIN_GAP is reported as a warning. Exit code 1 on a failure.

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/npth_check.py <board.kicad_pcb> [report.txt]
"""
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

M = pcbnew.ToMM
MIN_GAP = 0.254   # mm; the fab_hole_to_inner_copper / hole clearance order of the fab rules

b = pcbnew.LoadBoard(sys.argv[1])


def sps_polys(sps):
    out = []
    for i in range(sps.OutlineCount()):
        o = sps.Outline(i)
        holes = [[(M(sps.Hole(i, h).CPoint(k).x), M(sps.Hole(i, h).CPoint(k).y)) for k in range(sps.Hole(i, h).PointCount())]
                 for h in range(sps.HoleCount(i))]
        out.append(Polygon([(M(o.CPoint(k).x), M(o.CPoint(k).y)) for k in range(o.PointCount())], holes))
    return out


lines, fail = [], False
npth = [(fp, p) for fp in b.GetFootprints() for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH]
for lay in b.GetEnabledLayers().CuStack():
    cu = []
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if p.IsOnLayer(lay) and p.FlashLayer(lay):
                sps = pcbnew.SHAPE_POLY_SET()
                p.TransformShapeToPolygon(sps, lay, 0, pcbnew.FromMM(0.001), pcbnew.ERROR_INSIDE)
                cu.append(((fp.GetReference(), p.GetNumber(), p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH), sps_polys(sps)))
    for t in b.GetTracks():
        if t.IsOnLayer(lay):
            sps = pcbnew.SHAPE_POLY_SET()
            t.TransformShapeToPolygon(sps, lay, 0, pcbnew.FromMM(0.001), pcbnew.ERROR_INSIDE)
            cu.append((("track/via", t.GetNetname(), False), sps_polys(sps)))
    for z in b.Zones():
        if z.IsOnLayer(lay) and not z.GetIsRuleArea():
            cu.append((("zone", z.GetNetname(), False), sps_polys(z.GetFilledPolysList(lay))))
    for fp, p in npth:
        hole = Point(M(p.GetPosition().x), M(p.GetPosition().y)).buffer(M(p.GetDrillSize().x) / 2, 64)
        best = (99.0, "")
        for who, polys in cu:
            for g in polys:
                d = hole.distance(g) if not g.intersects(hole) else 0.0
                if d < best[0]:
                    best = (d, "%s %s" % (who[0], who[1]))
        tag = "FAIL (copper on the hole: plated by OSH Park)" if best[0] <= 0 else (
            "warn (< %.3f mm)" % MIN_GAP if best[0] < MIN_GAP else "ok")
        fail |= best[0] <= 0
        lines.append("%-6s %-3s drill %.3f mm  %-6s nearest copper %.3f mm (%s)  %s" % (
            fp.GetReference(), p.GetNumber(), M(p.GetDrillSize().x), b.GetLayerName(lay), best[0], best[1], tag))
lines.append("NPTH holes: %d; result: %s" % (len(npth), "FAIL" if fail else "pass"))
txt = "\n".join(lines) + "\n"
print(txt, end="")
if len(sys.argv) > 2:
    with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)
sys.exit(1 if fail else 0)
