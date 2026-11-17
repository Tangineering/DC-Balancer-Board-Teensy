"""REVIEW_2026-11-14 EIL-1 / INT-2 (S2): the J201 W5 wire-pad numbers were on F.Fab only, and the EIB 3 x 3 order differs
from the CR J101 order (Table D-66), so the nine W5 wires had to be matched from a table. This script adds, in place:

1. a J201 pad map on F.Silkscreen in the free strip above the board marking (x 7.15-23.6 mm, y 43.1-48.1 mm): the
   header 'J201 top view' over a 3 x 3 table of '<pin> <net>' cells, in the same arrangement as the J201 pads seen
   from the top (row 1 = pads 1, 4, 8), the columns separated by two vertical silkscreen lines. The cells
   are built from the pads and nets of the board, so they cannot disagree with eib.net. Short net names: 3V3, GND
   (GND_J), STAT, CE (CE_DRV_J), RLA / RLB (ILIM_REL_A / _B), RFC (RFC_OFF_J). The pads themselves cannot carry
   labels: the 0.74 mm pad gaps and the parts around the grid leave no room.
2. the EVM point beside each E label on B.Silkscreen (optional item of EIL-1), from the A.5 wiring table of
   docs/charger_bq25798_wiring_design_2026-11-05.md: E8 TP49, E3 TP33, E2 JP14 (pin 2), E7 TP38, E1 JP12 (REGN pin),
   E5 TP36; E4 and E6 carry no lead (r9-2), so they read 'E4 DNP' and 'E6 DNP'.
   Phase C (2026-11-15, R2-EIL-2): the E1 label reads 'E1 JP12.1' (JP12 pin 1, the square REGN post), and
   gen/eib_silk_fix_r3.py, run last, sets the character width of each E label (BACK_GAP to the bottom references).

Text: 0.8 x 0.8 mm, 0.15 mm stroke (fab_silk_text); separator lines 0.15 mm. The board marking must be on one line
(gen/eib_board_marking.py) so that the strip holds four rows. Every new
text is checked against the mask openings (+0.05 mm), the pad drill holes (+0.15 mm), the tented via drills (+0.05 mm;
for the E labels only where a via-free position exists), the other silkscreen items that are not reference fields (references are re-placed afterwards by gen/eib_silk_refs_r2.py) and a 0.25 mm edge band.
Idempotent: texts written by an earlier run are replaced.

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/eib_wire_labels.py
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
PCB = "eib/eib.kicad_pcb"
SHORT = {"/3V3": "3V3", "/GND_J": "GND", "/STAT": "STAT", "/CE_DRV_J": "CE", "/ILIM_REL_A": "RLA",
         "/ILIM_REL_B": "RLB", "/RFC_OFF_J": "RFC"}
EVM = {"E8": "TP49", "E3": "TP33", "E4": "DNP", "E2": "JP14", "E7": "TP38", "E1": "JP12.1", "E5": "TP36", "E6": "DNP"}
MAP_X0, MAP_X1 = 7.15, 23.6                        # map strip: x >= 7.15 (H1 M3 screw head <= 6.25), edge band
HEAD_Y, ROW_Y, ROW_PITCH = 43.75, 45.1, 1.25         # header row, then cell rows 45.10 / 46.35 / 47.60
E_LABEL_X = 3.25                                   # nearest left end of the B.Silkscreen E labels (E pads end at 2.95 mm)

b = pcbnew.LoadBoard(PCB)
mexp = M(b.GetDesignSettings().m_SolderMaskExpansion)


def ink(t):
    bb = t.GetEffectiveTextShape(False).BBox()
    return box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom()))


def mine(d):
    """A map item written by an earlier run: the header, a '<pin> <net>' cell, or a separator line (the EIB has no
    other board-level F.Silkscreen shape) on F.Silkscreen."""
    if d.GetLayer() != pcbnew.F_SilkS:
        return False
    if d.GetClass() == "PCB_SHAPE":
        return True
    if d.GetClass() != "PCB_TEXT":
        return False
    s = d.GetText().split(" ")
    return d.GetText().startswith("J201") or (len(s) == 2 and s[0].isdigit() and s[1] in SHORT.values())


# remove the map of an earlier run
gone = [d for d in b.GetDrawings() if mine(d)]
for d in gone:
    b.Remove(d)

# obstacles
obst = {pcbnew.F_SilkS: [], pcbnew.B_SilkS: []}
for fp in b.GetFootprints():
    for p in fp.Pads():
        for lay, mlay in ((pcbnew.F_SilkS, pcbnew.F_Mask), (pcbnew.B_SilkS, pcbnew.B_Mask)):
            if p.IsOnLayer(mlay):
                sh = p.GetEffectivePolygon(pcbnew.F_Cu if mlay == pcbnew.F_Mask else pcbnew.B_Cu, pcbnew.ERROR_OUTSIDE)
                o = sh.Outline(0)
                obst[lay].append(Polygon([(M(o.CPoint(k).x), M(o.CPoint(k).y))
                                          for k in range(o.PointCount())]).buffer(mexp + 0.05))
            if p.GetDrillSize().x > 0:
                obst[lay].append(Point(M(p.GetPosition().x), M(p.GetPosition().y)).buffer(M(p.GetDrillSize().x) / 2 + 0.15))
    for it in fp.GraphicalItems():
        if it.GetLayer() in obst:
            bb = it.GetBoundingBox()
            obst[it.GetLayer()].append(box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom())).buffer(0.1))
vias = {pcbnew.F_SilkS: [], pcbnew.B_SilkS: []}   # tented (setup: tenting front back): avoided where possible
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA":
        for lay in obst:
            vias[lay].append(Point(M(t.GetPosition().x), M(t.GetPosition().y)).buffer(M(t.GetDrillValue()) / 2 + 0.05))
e = b.GetBoardEdgesBoundingBox()
inner = box(M(e.GetX()) + 0.3, M(e.GetY()) + 0.3, M(e.GetRight()) - 0.3, M(e.GetBottom()) - 0.3)  # 0.25 mm band


def new_text(s, lay, w=0.8):
    t = pcbnew.PCB_TEXT(b)
    t.SetText(s)
    t.SetLayer(lay)
    t.SetTextSize(pcbnew.VECTOR2I(F(w), F(0.8)))
    t.SetTextThickness(F(0.15))
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
    if lay == pcbnew.B_SilkS:
        t.SetMirrored(True)
    return t


def place_left(t, x_left, y):
    """Put the ink of t with its left end at x_left and its centre at y."""
    t.SetPosition(pcbnew.VECTOR2I(F(x_left), F(y)))
    g = ink(t)
    t.SetPosition(pcbnew.VECTOR2I(F(2 * x_left - g.bounds[0]), F(y + (y - g.centroid.y))))
    return ink(t)


def check(t, g, lay, others):
    hit = [o for o in obst[lay] + others if g.intersects(o)]
    name = t.GetText() if hasattr(t, "GetText") else "separator"
    assert inner.contains(g), (name, "edge band", g.bounds)
    assert not hit, (name, "collides", g.bounds)


# 1. J201 map on F.Silkscreen
j = b.FindFootprintByReference("J201")
pads = sorted(j.Pads(), key=lambda p: (round(M(p.GetPosition().y), 1), M(p.GetPosition().x)))
assert len(pads) == 9
rows = [pads[0:3], pads[3:6], pads[6:9]]
cells = [[new_text("%s %s" % (p.GetNumber(), SHORT[p.GetNetname()]), pcbnew.F_SilkS) for p in r] for r in rows]
pitch = (MAP_X1 - MAP_X0) / 3
cx = [MAP_X0 + pitch * (k + 0.5) for k in range(3)]


def place_centre(t, x, y):
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    t.SetPosition(pcbnew.VECTOR2I(F(x), F(y)))
    g = ink(t)
    t.SetPosition(pcbnew.VECTOR2I(F(2 * x - g.centroid.x), F(2 * y - g.centroid.y)))
    return ink(t)


placed = []
head = new_text("J201 top view", pcbnew.F_SilkS)
placed.append((head, place_centre(head, cx[1], HEAD_Y)))
via_note = []
for r in range(3):
    for c in range(3):
        # centred in its column, or shifted by up to 0.6 mm within the column to clear a tented via
        lo, hi = MAP_X0 + pitch * c + 0.3, MAP_X0 + pitch * (c + 1) - 0.3
        for dx in [0.0] + [s * k * 0.1 for k in range(1, 7) for s in (1, -1)] + [None]:
            if dx is None:   # no via-free position in the column: centred over the tented via
                g = place_centre(cells[r][c], cx[c], ROW_Y + r * ROW_PITCH)
                via_note.append(cells[r][c].GetText())
                break
            g = place_centre(cells[r][c], cx[c] + dx, ROW_Y + r * ROW_PITCH)
            if g.bounds[0] >= lo and g.bounds[2] <= hi and not any(g.intersects(v) for v in vias[pcbnew.F_SilkS]):
                break
        placed.append((cells[r][c], g))
y_top = ROW_Y - 0.5
y_bot = ROW_Y + 2 * ROW_PITCH + 0.5
seps = []
for k in (1, 2):
    s = pcbnew.PCB_SHAPE(b)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetLayer(pcbnew.F_SilkS)
    s.SetWidth(F(0.15))
    # in the gap between the cell inks of columns k-1 and k: the via-free x nearest the gap centre (fallback centre)
    left = max(g.bounds[2] for t_, g in placed[1:] if t_ in [cells[r][k - 1] for r in range(3)]) + 0.2
    right = min(g.bounds[0] for t_, g in placed[1:] if t_ in [cells[r][k] for r in range(3)]) - 0.2
    xs = sorted([left + (right - left) * i / 20 for i in range(21)], key=lambda v: abs(v - (left + right) / 2))
    x = next((v for v in xs if not any(box(v - 0.075, y_top, v + 0.075, y_bot).intersects(w)
                                       for w in vias[pcbnew.F_SilkS])), (left + right) / 2)
    s.SetStart(pcbnew.VECTOR2I(F(x), F(y_top)))
    s.SetEnd(pcbnew.VECTOR2I(F(x), F(y_bot)))
    seps.append((s, box(x - 0.075, y_top - 0.075, x + 0.075, y_bot + 0.075)))
for t_, g in placed + seps:
    on_via = hasattr(t_, "GetText") and t_.GetText() in via_note
    check(t_, g, pcbnew.F_SilkS, [h.buffer(0.1) for u, h in placed + seps if u is not t_]
          + ([] if on_via else vias[pcbnew.F_SilkS]))
    b.Add(t_)
if via_note:
    print("map cells over a tented via: %s" % ", ".join(via_note))
mb = unary_union([g for t_, g in placed + seps]).bounds
print("J201 map: %d texts + 2 lines, ink box x %.2f-%.2f, y %.2f-%.2f" % (len(placed), mb[0], mb[2], mb[1], mb[3]))
for r in rows:
    print("   " + " | ".join("%s %s" % (p.GetNumber(), SHORT[p.GetNetname()]) for p in r))

# 2. EVM points beside the E labels on B.Silkscreen
elab = {d.GetText().split(" ")[0]: d for d in b.GetDrawings()
        if d.GetClass() == "PCB_TEXT" and d.GetLayer() == pcbnew.B_SilkS and d.GetText().split(" ")[0] in EVM}
assert set(elab) == set(EVM), sorted(elab)
others = [ink(d).buffer(0.1) for d in b.GetDrawings() if d.GetClass() == "PCB_TEXT" and d.GetLayer() == pcbnew.B_SilkS
          and d.GetText().split(" ")[0] not in EVM]
for name, d in sorted(elab.items()):
    y = M(b.FindFootprintByReference(name).GetPosition().y)   # the label row is the E pad row
    d.SetText("%s %s" % (name, EVM[name]))
    d.SetTextSize(pcbnew.VECTOR2I(F(0.8), F(0.8)))
    d.SetTextThickness(F(0.15))
    d.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
    # nearest clear left end at or right of E_LABEL_X, clear of the tented vias where possible (gen/silk_refs.py,
    # D-58, treats tented vias as no obstacle; the old E2 label already sat on the via at (3.86, 23.96))
    for extra in (vias[pcbnew.B_SilkS], []):
        for k in range(30):
            g = place_left(d, E_LABEL_X + 0.05 * k, y)
            if inner.contains(g) and not any(g.intersects(o) for o in obst[pcbnew.B_SilkS] + others + extra):
                break
        else:
            continue
        break
    check(d, g, pcbnew.B_SilkS, others)
    print("%s: '%s' x %.2f-%.2f%s" % (name, d.GetText(), g.bounds[0], g.bounds[2],
                                     "" if extra else " (crosses a tented via)"))
b.Save(PCB)
