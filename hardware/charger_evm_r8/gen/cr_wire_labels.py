"""REVIEW_2026-11-14 INT-2 / EIL-1 (S2): the J101 W5 wire-pad numbers were on F.Fab only, and the CR 3 x 3 order differs
from the EIB J201 order (Table D-66), so the nine W5 wires had to be matched from a table. This script adds a J101 pad
map on F.Silkscreen, in place, the CR counterpart of gen/eib_wire_labels.py.

Side: the CR plugs onto the MB with the J1 header pins on the underside, so after assembly only the top side is visible,
and the W5 leads are soldered with the CR in place (DOC-4). The map is therefore on F.Silkscreen.

Position: the J101 pads cannot carry labels beside them (0.74 mm pad gaps; parts and references on every side of the
grid). The map sits in the free strip to the right of the J1 pin column, x 47.7-58.3 mm. Each map row is level with its
pad row (y 50.63, 53.17 and 55.71 mm), and the three columns follow the pad columns from left to right as seen from the
top, so a row of the map reads across to the row of pads. These three rows fall in the via-free bands between the rows
of /GND stitching vias (y 49.08, 51.59, 54.03 and 56.55 mm). Cells read '<pin> <net>'; short net names from Table D-66
and cr.net: 3V3 (J3V3_1 / J3V3_2), GND, STAT, CE (CE_DRV_J), RLA / RLB (ILIM_REL_A / _B), RFC (RFC_OFF_J). The J101
reference field moves from row 1 of the strip to the map header, centred over the map in the via-free band above it
(y 47.75 mm); the C102b reference stays where it is, to the left under the header.

Text: 0.8 mm high, 0.15 mm stroke (fab_silk_text); the character width is 0.8 mm when the three columns fit the strip
with >= 0.6 mm between them, else 0.6 mm (stated in the output). Every new text keeps >= 0.05 mm from every mask opening,
>= 0.15 mm from every hole, >= 0.05 mm from every via drill, >= 0.10 mm from every other silkscreen item and >= 0.25 mm
from the board edge (gen/silk_refs.py margins). The cells are built from the pads and nets of the board, so they
cannot disagree with cr.net. Idempotent: the map texts of an earlier run are replaced.

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/cr_wire_labels.py
"""
import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

M, F = pcbnew.ToMM, pcbnew.FromMM
PCB = "cr/cr.kicad_pcb"
SHORT = {"/J3V3_1": "3V3", "/J3V3_2": "3V3", "/GND": "GND", "/STAT": "STAT", "/CE_DRV_J": "CE",
         "/ILIM_REL_A": "RLA", "/ILIM_REL_B": "RLB", "/RFC_OFF_J": "RFC"}
X0, X1 = 47.7, 58.3          # map strip: 0.7 mm right of the J1 pin-column mask openings (x <= 47.0), left of the edge band
HEAD_Y = 47.75               # header in the via-free band y 46.91-48.73 (via rows 46.56 / 49.08)
MIN_GAP = 0.6

b = pcbnew.LoadBoard(PCB)
mexp = M(b.GetDesignSettings().m_SolderMaskExpansion)


def ink(t):
    bb = t.GetEffectiveTextShape(False).BBox()
    return box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom()))


def mine(d):
    """A map item written by an earlier run: a '<pin> <net>' cell on F.Silkscreen, or the 'top view' header text and
    the separator line that gen/cr_silk_fix_r3.py adds (the CR has no other such F.Silkscreen board item). The header
    and the separator are removed here so that a re-run of this script followed by gen/cr_silk_fix_r3.py restores them
    around the re-centred J101 reference."""
    if d.GetLayer() != pcbnew.F_SilkS:
        return False
    if d.GetClass() == "PCB_SHAPE":
        return True
    if d.GetClass() != "PCB_TEXT":
        return False
    if d.GetText() == "top view":
        return True
    s = d.GetText().split(" ")
    return len(s) == 2 and s[0].isdigit() and s[1] in SHORT.values()


j = b.FindFootprintByReference("J101")
jref = j.Reference()
GONE = [d for d in b.GetDrawings() if mine(d)]   # kept referenced: a freed SWIG object breaks later wrapping
for d in GONE:
    b.Remove(d)

# obstacles
hard = []
for fp in b.GetFootprints():
    for p in fp.Pads():
        if p.IsOnLayer(pcbnew.F_Mask):
            lay = pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.F_Mask
            s = pcbnew.SHAPE_POLY_SET()
            p.TransformShapeToPolygon(s, lay, 0, F(0.002), pcbnew.ERROR_OUTSIDE)
            o = s.Outline(0)
            hard.append(Polygon([(M(o.CPoint(k).x), M(o.CPoint(k).y)) for k in range(o.PointCount())])
                        .buffer((mexp if lay == pcbnew.F_Cu else 0) + 0.05))
        if p.GetDrillSize().x > 0:
            hard.append(Point(M(p.GetPosition().x), M(p.GetPosition().y)).buffer(M(p.GetDrillSize().x) / 2 + 0.15))
    for f in fp.GetFields():
        if f.GetLayer() == pcbnew.F_SilkS and f.IsVisible() and not (fp.GetReference() == "J101" and f.IsReference()):
            hard.append(ink(f).buffer(0.10))
    for it in fp.GraphicalItems():
        if it.GetLayer() == pcbnew.F_SilkS:
            bb = it.GetBoundingBox()
            hard.append(box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom())).buffer(0.10))
for d in b.GetDrawings():
    if d.GetLayer() == pcbnew.F_SilkS:
        bb = d.GetBoundingBox()
        hard.append(box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom())).buffer(0.10))
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA":
        hard.append(Point(M(t.GetPosition().x), M(t.GetPosition().y)).buffer(M(t.GetDrillValue()) / 2 + 0.05))
sps = pcbnew.SHAPE_POLY_SET()
b.GetBoardPolygonOutlines(sps)
o = sps.Outline(0)
inner = Polygon([(M(o.CPoint(k).x), M(o.CPoint(k).y)) for k in range(o.PointCount())]).buffer(0).buffer(-0.25,
                                                                                                    join_style=2)


def new_text(s, w):
    t = pcbnew.PCB_TEXT(b)
    t.SetText(s)
    t.SetLayer(pcbnew.F_SilkS)
    t.SetTextSize(pcbnew.VECTOR2I(F(w), F(0.8)))
    t.SetTextThickness(F(0.15))
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
    return t


def place(t, x_left, y):
    """Put the ink of t with its left end at x_left and its centre at y."""
    t.SetPosition(pcbnew.VECTOR2I(F(x_left), F(y)))
    g = ink(t)
    t.SetPosition(pcbnew.VECTOR2I(F(2 * x_left - g.bounds[0]), F(y + (y - g.centroid.y))))
    return ink(t)


pads = sorted(j.Pads(), key=lambda p: (round(M(p.GetPosition().y), 1), M(p.GetPosition().x)))
assert len(pads) == 9
rows = [pads[0:3], pads[3:6], pads[6:9]]
for w in (0.8, 0.6):
    cells = [[new_text("%s %s" % (p.GetNumber(), SHORT[p.GetNetname()]), w) for p in r] for r in rows]
    widths = [max(place(cells[r][c], 0, 0).bounds[2] - place(cells[r][c], 0, 0).bounds[0] for r in range(3))
              for c in range(3)]
    gap = (X1 - X0 - sum(widths)) / 2
    if gap >= MIN_GAP:
        break
assert gap >= MIN_GAP, gap
xs = [X0, X0 + widths[0] + gap, X0 + widths[0] + widths[1] + 2 * gap]
placed = []
for r in range(3):
    y = M(rows[r][0].GetPosition().y)
    for c in range(3):
        g = place(cells[r][c], xs[c], y)
        assert inner.contains(g), (cells[r][c].GetText(), "edge band", g.bounds)
        hit = [h for h in hard if g.intersects(h)]
        assert not hit, (cells[r][c].GetText(), "collides", g.bounds, [x.bounds for x in hit])
        placed.append(g)
# header: the J101 reference field, centred over the map
jref.SetLayer(pcbnew.F_SilkS)
jref.SetTextSize(pcbnew.VECTOR2I(F(0.8), F(0.8)))
jref.SetTextThickness(F(0.15))
jref.SetTextAngleDegrees(0.0)
jref.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
jref.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
jref.SetPosition(pcbnew.VECTOR2I(F((X0 + X1) / 2), F(HEAD_Y)))
g = ink(jref)
jref.SetPosition(pcbnew.VECTOR2I(F((X0 + X1) / 2 + ((X0 + X1) / 2 - g.centroid.x)), F(HEAD_Y + (HEAD_Y - g.centroid.y))))
g = ink(jref)
assert inner.contains(g) and not any(g.intersects(h) for h in hard), ("J101 header", g.bounds)
for row in cells:
    for t in row:
        b.Add(t)
mb = unary_union(placed + [g]).bounds
print("J101 map: 9 cells, character width %.1f mm, column gap %.2f mm, ink box x %.2f-%.2f, y %.2f-%.2f"
      % (w, gap, mb[0], mb[2], mb[1], mb[3]))
print("J101 reference (header) at (%.2f, %.2f)" % (M(jref.GetPosition().x), M(jref.GetPosition().y)))
for r in rows:
    print("   " + " | ".join("%s %s" % (p.GetNumber(), SHORT[p.GetNetname()]) for p in r))
b.Save(PCB)
