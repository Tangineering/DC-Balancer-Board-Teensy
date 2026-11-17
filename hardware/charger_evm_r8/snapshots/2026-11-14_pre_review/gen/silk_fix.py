"""Silkscreen cleanup for dense boards (D-12). Removes footprint silkscreen graphics that the fab would clip
anyway: items over pad copper or mask openings, items closer than the silk-to-edge clearance, and items that
overlap another footprint's silkscreen. Board-level texts are kept. Usage: python silk_fix.py <board.kicad_pcb>"""
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass
from shapely.geometry import box
from shapely.ops import unary_union

mm = pcbnew.ToMM
b = pcbnew.LoadBoard(sys.argv[1])
SILK = {pcbnew.F_SilkS: pcbnew.F_Cu, pcbnew.B_SilkS: pcbnew.B_Cu}


def bb(item):
    r = item.GetBoundingBox()
    return box(mm(r.GetLeft()), mm(r.GetTop()), mm(r.GetRight()), mm(r.GetBottom()))


from shapely.geometry import LineString  # noqa: E402
from shapely.ops import polygonize  # noqa: E402
segs = [LineString([(mm(d.GetStart().x), mm(d.GetStart().y)), (mm(d.GetEnd().x), mm(d.GetEnd().y))])
        for d in b.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts and d.GetShape() == pcbnew.SHAPE_T_SEGMENT]
board_in = unary_union(list(polygonize(unary_union(segs)))).buffer(-0.25, join_style=2)

pads = {pcbnew.F_Cu: [], pcbnew.B_Cu: []}
for fp in b.GetFootprints():
    for p in fp.Pads():
        for cu in pads:
            if p.IsOnLayer(cu) or p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                pads[cu].append(bb(p).buffer(0.15))
padu = {k: unary_union(v) for k, v in pads.items()}

removed = 0
graveyard = []   # removed items stay referenced until the save (pcbnew reuses freed addresses)
kept = {pcbnew.F_SilkS: [], pcbnew.B_SilkS: []}
for fp in b.GetFootprints():
    for it in list(fp.GraphicalItems()):
        lay = it.GetLayer()
        if lay not in SILK:
            continue
        g = bb(it)
        if g.intersects(padu[SILK[lay]]) or not board_in.contains(g) or \
                any(g.intersects(k) for ref, k in kept[lay] if ref != fp.GetReference()):
            fp.Remove(it)
            graveyard.append(it)
            removed += 1
        else:
            kept[lay].append((fp.GetReference(), g))
b.Save(sys.argv[1])
print("silkscreen items removed or hidden:", removed)
