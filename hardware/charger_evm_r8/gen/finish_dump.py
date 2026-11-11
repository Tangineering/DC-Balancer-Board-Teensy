"""Finishing router, step 1 (pcbnew venv): dump the copper of a board and the unconnected item pairs of its DRC
report to JSON. Usage: python finish_dump.py <board.kicad_pcb> <drc.rpt> <out.json> <routing layers, e.g. F.Cu,In2.Cu,B.Cu>
Coordinates stay in the KiCad frame (mm, y down)."""
import json
import re
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

board, rpt, out, layers = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4].split(",")
b = pcbnew.LoadBoard(board)
LID = {b.GetLayerName(l): l for l in [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]}
mm = pcbnew.ToMM


def poly_pts(sps, i):
    o = sps.Outline(i)
    return [(mm(o.CPoint(k).x), mm(o.CPoint(k).y)) for k in range(o.PointCount())]


items = []   # dict(kind, net, layers, geom)  geom: poly pts | seg (x0,y0,x1,y1,w) | circ (x,y,r)
for fp in b.GetFootprints():
    for p in fp.Pads():
        ls = [ln for ln in layers if p.IsOnLayer(LID[ln])]
        if not ls and not p.GetDrillSizeX():
            continue
        for ln in (ls or layers[:1]):
            sps = p.GetEffectivePolygon(LID[ln], pcbnew.ERROR_INSIDE)
            for i in range(sps.OutlineCount()):
                items.append(dict(kind="pad", net=p.GetNetname(), layers=[ln], poly=poly_pts(sps, i),
                                  ref=fp.GetReference(), num=p.GetNumber()))
        if p.GetDrillSizeX() > 0:   # the hole blocks every routing layer
            c = p.GetPosition()
            items.append(dict(kind="hole", net=p.GetNetname(), layers=layers,
                              circ=(mm(c.x), mm(c.y), mm(max(p.GetSizeX(), p.GetDrillSizeX())) / 2)))
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA":
        c = t.GetPosition()
        items.append(dict(kind="via", net=t.GetNetname(), layers=layers,
                          circ=(mm(c.x), mm(c.y), mm(t.GetWidth(pcbnew.F_Cu)) / 2)))
    else:
        ln = b.GetLayerName(t.GetLayer())
        if ln in layers:
            s, e = t.GetStart(), t.GetEnd()
            items.append(dict(kind="track", net=t.GetNetname(), layers=[ln],
                              seg=(mm(s.x), mm(s.y), mm(e.x), mm(e.y), mm(t.GetWidth()))))
for z in b.Zones():
    if z.GetIsRuleArea():
        for lay in z.GetLayerSet().Seq():
            ln = b.GetLayerName(lay)
            if ln in layers and (z.GetDoNotAllowTracks() or z.GetDoNotAllowVias()):
                ol = z.Outline()
                for i in range(ol.OutlineCount()):
                    items.append(dict(kind="keepout", net="", layers=[ln], poly=poly_pts(ol, i),
                                      holes=[[(mm(h.CPoint(k).x), mm(h.CPoint(k).y)) for k in range(h.PointCount())]
                                             for h in [ol.Hole(i, j) for j in range(ol.HoleCount(i))]]))
        continue
    soft = z.GetAssignedPriority() <= 1          # GND pours yield to new tracks on refill
    for lay in z.GetLayerSet().Seq():
        ln = b.GetLayerName(lay)
        if ln not in layers:
            continue
        fp_ = z.GetFilledPolysList(lay)
        for i in range(fp_.OutlineCount()):
            items.append(dict(kind="zone", net=z.GetNetname(), layers=[ln], poly=poly_pts(fp_, i), soft=soft))

# board outline
bb = b.GetBoardEdgesBoundingBox()
outline = []
for d in b.GetDrawings():
    if d.GetLayer() == pcbnew.Edge_Cuts and d.GetShape() == pcbnew.SHAPE_T_SEGMENT:
        outline.append((mm(d.GetStart().x), mm(d.GetStart().y), mm(d.GetEnd().x), mm(d.GetEnd().y)))

# unconnected pairs from the DRC report
pairs = []
txt = open(rpt, encoding="utf-8").read()
for blk in re.findall(r"\[unconnected_items\][^\n]*\n(?:[^\n]*\n){1}((?:\s+@\([^\n]*\n){2})", txt):
    pts = re.findall(r"@\(([-\d.]+) mm, ([-\d.]+) mm\): ([^\n]*)", blk)
    if len(pts) == 2:
        pairs.append([(float(x), float(y), desc) for x, y, desc in pts])

json.dump(dict(items=items, outline=outline, bbox=(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()),
                                                   mm(bb.GetBottom())), pairs=pairs, layers=layers), open(out, "w"))
print("items", len(items), "pairs", len(pairs))
