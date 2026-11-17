"""Phase C of the 2026-11-14 update (second review): EIB E-pad identification, in place (silkscreen texts only).

Items:
- R2-INT-7 / R2-EIL-0: the E-pad landing labels ('E8 TP49' ... 'E6 DNP', gen/eib_wire_labels.py) are on B.Silkscreen
  only, and the E1-E8 reference fields are hidden, so no E identity is visible from the top once the EIB stands on its
  standoffs. The script adds a short F.Silkscreen label ('E<n>', else the digit '<n>') beside every E pad that has a
  legal position under the rules below, and reports each pad that has none.
- R2-EIL-1: the bottom E labels stood 0.41-0.53 mm from the bottom reference texts R252, R254 and R271, against the
  0.80 mm gap that D-78 set between two bottom-side reference texts. Each bottom E label stays level with its pad; its
  left end stays at its position or moves toward +x in 0.05 mm steps (at most 2.0 mm), with 0.8 mm characters before
  0.6 mm ones (height 0.8 mm and stroke 0.15 mm stay). A legal position keeps >= 0.80 mm (BACK_GAP) from every bottom
  reference text, >= 0.10 mm from the other E labels, >= 0.10 mm from every B.Mask opening, >= 0.15 mm from every hole,
  >= 0.30 mm from every B.Silkscreen graphic and 0.25 mm inside the edge. The first legal position whose strokes keep
  >= 0.05 mm from every via drill is taken; where none exists, the first legal position is kept and reported (the
  phase A labels already crossed tented vias). The script asserts the 0.80 mm gap afterwards.
- R2-EIL-2: E1 lands on JP12 pin 1 only (the square REGN post; design document A.5, E1 row), so the bottom label
  reads 'E1 JP12.1' (gen/eib_wire_labels.py carries the same text, so a re-run of that script keeps it).

Top-side label rules: text 0.8 mm high, 0.15 mm stroke, 0.8 mm character width first and 0.6 mm where 0.8 mm has no
legal position, 0 or 90 degrees (LAYOUT_DECISIONS D-78). The ink box keeps >= 0.10 mm from every F.Mask opening,
>= 0.15 mm from every hole, >= 0.05 mm from every via drill, >= 0.30 mm from every F.Silkscreen graphic, >= 0.40 mm
from every F.Silkscreen text (the EIB board-text gap TEXT_GAP of gen/eib_silk_refs_r2.py, so that 'E1' does not run
into a reference as one word), >= 0.25 mm inside the board edge and >= 3.6 mm from the H1 and H2 centres (HOLE_KEEP,
the M3 washer and standoff keep-out of gen/eib_board_marking.py; the bottom labels obey it too), and has zero overlap
with the courtyard of any other footprint. The label must be unambiguous: its ink lies nearer its own pad than any other pad by >= 0.15 mm (AMBIG),
and, because the E pads form one column, its ink centre lies nearer (in y) the own pad centre than any other E pad
centre by >= 0.5 mm (ROW_MARGIN). Among the legal positions the script prefers 'E<n>' over '<n>', then a smaller
y offset from the pad centre, then 0 degrees, then 0.8 mm characters, then the smaller gap to the pad. The labels are
placed in pad order, and each placed label is an obstacle for the next.

Idempotent: top labels of an earlier run (F.Silkscreen board texts that read 'E1'...'E8' or '1'...'8' and whose
nearest pad is an E pad) are removed first. Run it last in the EIB sequence (HANDOFF.md section 4 step 9a), after
gen/sync_fields.py; gen/eib_silk_refs_r2.py treats board texts as obstacles, so a later run of that script on a board
that carries these labels may place references differently. Copper, pads, zones and footprint positions do not change.

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/eib_silk_fix_r3.py [board.kicad_pcb]
"""
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

M, F = pcbnew.ToMM, pcbnew.FromMM
PCB = sys.argv[1] if len(sys.argv) > 1 else "eib/eib.kicad_pcb"
MASK_GAP, HOLE_GAP, VIA_GAP, GFX_GAP, TXT_GAP, EDGE, AMBIG, ROW_MARGIN = 0.10, 0.15, 0.05, 0.30, 0.40, 0.25, 0.15, 0.5
BACK_GAP = 0.80
HOLE_KEEP = 3.6   # ink >= 3.6 mm from the H1 / H2 centres (M3 washer and standoff keep-out of gen/eib_board_marking.py, D-78)
STEP, RADIUS = 0.05, 2.0
EPADS = ["E8", "E3", "E4", "E2", "E7", "E1", "E5", "E6"]
E1_LABEL = "E1 JP12.1"
TOPTEXTS = {s for e in EPADS for s in (e, e[1])}

b = pcbnew.LoadBoard(PCB)
mexp = M(b.GetDesignSettings().m_SolderMaskExpansion)


def ink(t):
    bb = t.GetEffectiveTextShape(False).BBox()
    return box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom()))


def bbox(it):
    bb = it.GetBoundingBox()
    return box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom()))


def ppoly(sps):
    return unary_union([Polygon([(M(sps.Outline(i).CPoint(k).x), M(sps.Outline(i).CPoint(k).y))
                                 for k in range(sps.Outline(i).PointCount())]).buffer(0)
                        for i in range(sps.OutlineCount())])


def obstacles(mask_layer, cu_layer):
    pads, hard = [], []
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if p.IsOnLayer(mask_layer):
                lay = cu_layer if p.IsOnLayer(cu_layer) else mask_layer
                g = ppoly(p.GetEffectivePolygon(lay, pcbnew.ERROR_OUTSIDE)).buffer(mexp if lay == cu_layer else 0)
                pads.append((fp.GetReference(), p.GetNumber(), g))
                hard.append(g.buffer(MASK_GAP))
            if p.GetDrillSize().x > 0:
                hard.append(Point(M(p.GetPosition().x), M(p.GetPosition().y))
                            .buffer(M(p.GetDrillSize().x) / 2 + HOLE_GAP))
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            hard.append(Point(M(t.GetPosition().x), M(t.GetPosition().y)).buffer(M(t.GetDrillValue()) / 2 + VIA_GAP))
    return pads, unary_union(hard)


sps = pcbnew.SHAPE_POLY_SET()
b.GetBoardPolygonOutlines(sps)
inner = ppoly(sps).buffer(-EDGE, join_style=2)
holekeep = unary_union([Point(M(b.FindFootprintByReference(h).GetPosition().x),
                              M(b.FindFootprintByReference(h).GetPosition().y)).buffer(HOLE_KEEP) for h in ("H1", "H2")])

# ---- bottom side: E1 pin, BACK_GAP to the bottom reference texts (R2-EIL-1, R2-EIL-2)
elab = {d.GetText().split(" ")[0]: d for d in b.GetDrawings()
        if d.GetClass() == "PCB_TEXT" and d.GetLayer() == pcbnew.B_SilkS and d.GetText().split(" ")[0] in EPADS}
assert set(elab) == set(EPADS), sorted(elab)
backrefs = [d for d in b.GetDrawings() if d.GetClass() == "PCB_TEXT" and d.GetLayer() == pcbnew.B_SilkS
            and d.GetText().split(" ")[0] not in EPADS]
backref_ink = [(d.GetText(), ink(d)) for d in backrefs]
bpads, bhard = obstacles(pcbnew.B_Mask, pcbnew.B_Cu)
bgfx = unary_union([bbox(it).buffer(GFX_GAP) for fp in b.GetFootprints() for it in fp.GraphicalItems()
                    if it.GetLayer() == pcbnew.B_SilkS] +
                   [bbox(d).buffer(GFX_GAP) for d in b.GetDrawings()
                    if d.GetLayer() == pcbnew.B_SilkS and d.GetClass() != "PCB_TEXT"])
bvias = [Point(M(t.GetPosition().x), M(t.GetPosition().y)).buffer(M(t.GetDrillValue()) / 2)
         for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]
bmaskhole = unary_union([q.buffer(MASK_GAP) for r, n, q in bpads] +
                        [Point(M(p.GetPosition().x), M(p.GetPosition().y)).buffer(M(p.GetDrillSize().x) / 2 + HOLE_GAP)
                         for fp in b.GetFootprints() for p in fp.Pads() if p.GetDrillSize().x > 0])


def strokes(t):
    sp = pcbnew.SHAPE_POLY_SET()
    t.TransformTextToPolySet(sp, 0, F(0.005), pcbnew.ERROR_OUTSIDE)
    return ppoly(sp)


def set_label(d, w, left):
    d.SetTextSize(pcbnew.VECTOR2I(F(w), F(0.8)))
    d.SetTextThickness(F(0.15))
    g = ink(d)
    d.Move(pcbnew.VECTOR2I(F(left - g.bounds[0]), 0))
    return ink(d)


for name in EPADS:
    d = elab[name]
    # left end on a 1 um grid, so that a re-run does not drift by 1 nm; mirrored text grows toward -x when the string
    # gets longer, so the left end is restored by set_label() below
    left0 = round(ink(d).bounds[0], 3)
    if name == "E1" and d.GetText() != E1_LABEL:
        d.SetText(E1_LABEL)
    others = [ink(o) for o in b.GetDrawings() if o.GetClass() == "PCB_TEXT" and o.GetLayer() == pcbnew.B_SilkS
              and o.m_Uuid.AsString() != d.m_Uuid.AsString() and o.GetText().split(" ")[0] in EPADS]
    found, fallback = None, None
    # left end at its position or shifted toward +x in 0.05 mm steps (up to 2.0 mm; the label stays level with
    # its pad); 0.8 mm characters before 0.6 mm; legal = BACK_GAP to the bottom references, 0.10 mm to the other E
    # labels, mask (+0.10) / hole (+0.15) margins, edge band, graphics; preferred = no stroke within VIA_GAP of a via
    # drill (the fallback is the first position legal without that test)
    for w in (0.8, 0.6):
        for k in range(41):
            g = set_label(d, w, left0 + 0.05 * k)
            gap = min(g.distance(q) for s_, q in backref_ink)
            if gap < BACK_GAP or not inner.contains(g) or g.intersects(bgfx) or g.intersects(bmaskhole) \
                    or g.intersects(holekeep):
                continue
            if others and min(g.distance(o) for o in others) < 0.10:
                continue
            if fallback is None:
                fallback = (w, k)
            st = strokes(d)
            if any(st.distance(v) < VIA_GAP for v in bvias):
                continue
            found = (w, k)
            break
        if found:
            break
    assert found or fallback, name
    w, k = found or fallback
    g = set_label(d, w, left0 + 0.05 * k)
    gap = min(g.distance(q) for s_, q in backref_ink)
    near = min(backref_ink, key=lambda sq: g.distance(sq[1]))
    vd = min(strokes(d).distance(v) for v in bvias)
    print("bottom %-11s 0.8 x %.1f mm, ink x %.2f-%.2f y %.2f-%.2f, %.2f mm from bottom text %s, stroke %.3f mm "
          "from the nearest via drill%s" % ("'%s'" % d.GetText(), w, g.bounds[0], g.bounds[2], g.bounds[1],
                                             g.bounds[3], gap, near[0], vd,
                                             "" if found else " (no via-clear position; first legal position kept)"))
    assert gap >= BACK_GAP, (name, gap)

# ---- top side: E labels (R2-INT-7 / R2-EIL-0)
pads, hard = obstacles(pcbnew.F_Mask, pcbnew.F_Cu)


def nearest_pad(g):
    return min(((q.distance(g), r) for r, n, q in pads))[1]


gone = [d for d in b.GetDrawings() if d.GetLayer() == pcbnew.F_SilkS and d.GetClass() == "PCB_TEXT"
        and d.GetText() in TOPTEXTS and nearest_pad(ink(d)) in EPADS]
for d in gone:
    b.Remove(d)
crt = {}
for fp in b.GetFootprints():
    c = fp.GetCourtyard(pcbnew.F_CrtYd)
    if c.OutlineCount():
        crt[fp.GetReference()] = ppoly(c)
ecent = {e: M(b.FindFootprintByReference(e).GetPosition().y) for e in EPADS}


def silk():
    out = []
    for fp in b.GetFootprints():
        for f in fp.GetFields():
            if f.GetLayer() == pcbnew.F_SilkS and f.IsVisible():
                out.append(ink(f).buffer(TXT_GAP))
        for it in fp.GraphicalItems():
            if it.GetLayer() == pcbnew.F_SilkS:
                out.append(bbox(it).buffer(GFX_GAP))
    for d in b.GetDrawings():
        if d.GetLayer() == pcbnew.F_SilkS:
            out.append(ink(d).buffer(TXT_GAP) if d.GetClass() == "PCB_TEXT" else bbox(d).buffer(GFX_GAP))
    return unary_union(out)


placed, missing = [], []
for e in EPADS:
    target = [g for r, n, g in pads if r == e][0]
    near = [q for r, n, q in pads if r != e and q.distance(target) < RADIUS + 4.0]
    others = silk()
    py = ecent[e]
    t = pcbnew.PCB_TEXT(b)
    t.SetLayer(pcbnew.F_SilkS)
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
    t.SetTextThickness(F(0.15))
    x0, y0, x1, y1 = target.bounds
    best = None
    for ti, s in enumerate((e, e[1])):
        t.SetText(s)
        for wi, w in enumerate((0.8, 0.6)):
            t.SetTextSize(pcbnew.VECTOR2I(F(w), F(0.8)))
            for ai, ang in enumerate((0.0, 90.0)):
                t.SetTextAngleDegrees(ang)
                for i in range(int((x1 - x0 + 2 * RADIUS) / STEP) + 1):
                    for j in range(int((y1 - y0 + 2 * RADIUS) / STEP) + 1):
                        x, y = x0 - RADIUS + i * STEP, y0 - RADIUS + j * STEP
                        t.SetPosition(pcbnew.VECTOR2I(F(x), F(y)))
                        g = ink(t)
                        dy = abs(g.centroid.y - py)
                        if any(abs(g.centroid.y - ecent[o]) < dy + ROW_MARGIN for o in EPADS if o != e):
                            continue
                        d = g.distance(target)
                        if d > RADIUS or not inner.contains(g) or g.intersects(hard) or g.intersects(others) \
                                or g.intersects(holekeep):
                            continue
                        if any(g.intersects(c) for r, c in crt.items() if r != e):
                            continue
                        dn = min(q.distance(g) for q in near)
                        if d + AMBIG > dn:
                            continue
                        key = (ti, round(dy, 1), ai, wi, round(d, 3))
                        if best is None or key < best[0]:
                            best = (key, s, w, ang, x, y, dn, dy)
    if best is None:
        missing.append(e)
        print("top    %s: no legal position" % e)
        continue
    key, s, w, ang, x, y, dn, dy = best
    t.SetText(s)
    t.SetTextSize(pcbnew.VECTOR2I(F(w), F(0.8)))
    t.SetTextAngleDegrees(ang)
    t.SetPosition(pcbnew.VECTOR2I(F(x), F(y)))
    g = ink(t)
    b.Add(t)
    placed.append(e)
    print("top    %s: '%s' at (%.2f, %.2f), %.0f deg, 0.8 x %.1f mm, ink x %.2f-%.2f y %.2f-%.2f, %.2f mm from the pad, "
          "%.2f mm from the nearest other pad, centre %.2f mm from the pad row" % (
              e, s, x, y, ang, w, g.bounds[0], g.bounds[2], g.bounds[1], g.bounds[3], g.distance(target), dn, dy))
print("top labels placed: %s; no legal position: %s" % (" ".join(placed) or "none", " ".join(missing) or "none"))
b.Save(PCB)
print("saved " + PCB)
