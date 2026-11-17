"""REVIEW_2026-11-14 EIL-7 (S3): the EIB board marking read 'EIB r8' / '2026-11-11' (two F.Silkscreen lines), although
the copper had changed since (D-66 wire pads and D-68 pour clearance on 2026-11-13, the 2026-11-14 review updates), so
boards of different packages could not be told apart. This script writes the marking as one line, 'EIB r8 2026-11-14',
at the former date-line position (12.0, 49.05), and removes the separate date text; the line freed above it holds
the J201 map of gen/eib_wire_labels.py (EIL-1). The F.Fab layer carries no board marking.

Phase B (2026-11-14, defect D1 of the phase A check): at (12.0, 49.05) the ink box (x 5.89-18.19, y 48.50-49.49 mm)
came 3.07 mm from the H1 centre (3.5, 46.5), inside the 3.55 mm mounting-hole keep-out, so an M3 washer or standoff
could cover the "E". The text now stands at POS = (14.18, 49.15). The script asserts the placement rules: ink box
>= 3.6 mm from the H1 and H2 centres, >= 0.25 mm inside the board edge, >= 0.40 mm from every other F.Silkscreen
item (the J201 map texts and lines), and the text strokes clear of every via drill. No via-free 12.3 mm span exists
in the bottom row (stitching vias at x 6.21, 11.96, 16.46 and 23.21 mm, y 49.21 mm), so POS is the position of the
largest stroke-to-drill gap in a 0.01 mm search over x 12.65-17.60 mm and y 49.05-49.25 mm. Idempotent.

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/eib_board_marking.py
"""
import math

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

NEW = "EIB r8 2026-11-14"
POS = (14.18, 49.15)                  # mm, text anchor (centre justified)
HOLES = [(3.5, 46.5), (20.5, 15.5)]   # H1, H2 centres (mm)
HOLE_GAP, EDGE, TEXT_GAP = 3.6, 0.25, 0.40
PCB = "eib/eib.kicad_pcb"
b = pcbnew.LoadBoard(PCB)
texts = [d for d in b.GetDrawings() if d.GetClass() == "PCB_TEXT" and d.GetLayer() == pcbnew.F_SilkS]
name = [t for t in texts if t.GetText() in ("EIB r8", NEW)]
date = [t for t in texts if t.GetText() in ("2026-11-11", "2026-11-14")]
assert len(name) == 1, [t.GetText() for t in texts]
t = name[0]
changed = False
if not (t.GetText() == NEW and not date):
    assert len(date) == 1, [x.GetText() for x in texts]
    t.SetText(NEW)
    t.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(0.8), pcbnew.FromMM(0.8)))
    t.SetTextThickness(pcbnew.FromMM(0.15))
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    b.Remove(date[0])
    changed = True
want = pcbnew.VECTOR2I(pcbnew.FromMM(POS[0]), pcbnew.FromMM(POS[1]))
if t.GetPosition() != want:
    t.SetPosition(want)
    changed = True

# placement rules (phase B, D1)
M = pcbnew.ToMM
bb = t.GetEffectiveTextShape(False).BBox()
x0, y0, x1, y1 = M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom())


def box_dist(px, py):
    return math.hypot(max(x0 - px, 0.0, px - x1), max(y0 - py, 0.0, py - y1))


e = b.GetBoardEdgesBoundingBox()   # the bounding box includes half the 0.1 mm edge line width
ex0, ey0, ex1, ey1 = M(e.GetX()) + 0.05, M(e.GetY()) + 0.05, M(e.GetRight()) - 0.05, M(e.GetBottom()) - 0.05
hole_gap = min(box_dist(*h) for h in HOLES)
assert hole_gap >= HOLE_GAP, ("hole keep-out", hole_gap)
assert x0 >= ex0 + EDGE and y0 >= ey0 + EDGE and x1 <= ex1 - EDGE and y1 <= ey1 - EDGE, ("edge", x0, y0, x1, y1)
for d in b.GetDrawings():
    if d.m_Uuid.AsString() == t.m_Uuid.AsString() or d.GetLayer() != pcbnew.F_SilkS:
        continue
    ob = d.GetEffectiveTextShape(False).BBox() if d.GetClass() == "PCB_TEXT" else d.GetBoundingBox()
    gx = max(M(ob.GetX()) - x1, x0 - M(ob.GetRight()), 0.0)
    gy = max(M(ob.GetY()) - y1, y0 - M(ob.GetBottom()), 0.0)
    assert math.hypot(gx, gy) >= TEXT_GAP, ("silkscreen neighbour", d.GetClass(), math.hypot(gx, gy))
poly = pcbnew.SHAPE_POLY_SET()
t.TransformTextToPolySet(poly, 0, pcbnew.FromMM(0.005), pcbnew.ERROR_OUTSIDE)
dmin = 1e9
for v in b.GetTracks():
    if v.GetClass() == "PCB_VIA":
        c = v.GetPosition()
        r = v.GetDrillValue() / 2.0
        for i in range(poly.OutlineCount()):
            o = poly.Outline(i)
            if o.PointInside(c):
                dmin = -1.0
            for k in range(o.SegmentCount()):
                dmin = min(dmin, M(o.CSegment(k).Distance(c)) - M(r))
assert dmin > 0.0, ("text stroke over a via drill", dmin)
if changed:
    b.Save(PCB)
print("board marking: '%s' at (%.2f, %.2f); ink x %.2f-%.2f, y %.2f-%.2f; gap to H1/H2 %.2f mm; stroke to via drill "
      "%.3f mm%s" % (NEW, M(t.GetPosition().x), M(t.GetPosition().y), x0, x1, y0, y1, hole_gap, dmin,
                     "" if changed else " (unchanged)"))
