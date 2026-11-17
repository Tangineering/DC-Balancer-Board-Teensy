"""REVIEW_2026-11-14 CRL-7 (S3) and CRL-3 follow-up: re-place two reference designators of cr/cr.kicad_pcb, in place.

- R107: its reference (at (48.78, 65.40)) lay inside the J102 body outline (F.Fab x 46.06-54.93, y 64.38-83.63), so it
  is hidden once J102 is fitted. A pcbnew text-box check shows that the U106 reference (ink x 44.85-45.80) and the C116
  reference (x 43.86-45.01) end before the J102 body (x >= 46.06); they are not hidden and are not moved.
- C102c: its reference (at (37.60, 38.68)) covered the pin-1 corner of U101, where gen/cr_pin1_marks.py puts the U101
  pin-1 dot (DRC silk_overlap).

Every other reference stays where it is (gen/silk_refs.py, D-59). For each listed reference the script searches a
0.05 mm grid within 4.0 mm of the part's own courtyard, at text heights 1.0 / 0.8 mm (stroke 0.15 mm; the 0.8 mm
house minimum, rule fab_silk_text), with 0.8 mm-wide characters first and 0.6 mm-wide characters only where no
0.8 mm-wide position exists, at 0 and 90 degrees. A position is legal when the ink box keeps >= 0.05 mm from every
F.Mask opening, >= 0.15 mm from every hole, >= 0.10 mm from every other F.Silkscreen item and >= 0.25 mm from the board
edge (gen/silk_refs.py margins). Among the legal positions the script prefers, in order: no overlap with another
part's courtyard; a smaller gap to the own courtyard than to any other courtyard; no crossing of a tented via drill
(+0.05 mm); the larger text; the smaller gap to the own courtyard. Copper, nets and footprint positions are not
changed. Idempotent: a reference already at its chosen position is left unchanged.

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/cr_silk_refs_r2.py
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
REFS = ["R107", "C102c"]
MASK_GAP, HOLE_GAP, SILK_GAP, EDGE_BAND, VIA_GAP, RADIUS, STEP = 0.05, 0.15, 0.10, 0.25, 0.05, 4.0, 0.05
STYLES = [(1.0, 1.0), (0.8, 0.8), (0.8, 0.6)]   # (height, width), stroke 0.15 mm

b = pcbnew.LoadBoard(PCB)
mexp = M(b.GetDesignSettings().m_SolderMaskExpansion)


def ink(t):
    bb = t.GetEffectiveTextShape(False).BBox()
    return box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom()))


def outline():
    sps = pcbnew.SHAPE_POLY_SET()
    b.GetBoardPolygonOutlines(sps)
    o = sps.Outline(0)
    return Polygon([(M(o.CPoint(k).x), M(o.CPoint(k).y)) for k in range(o.PointCount())]).buffer(0)


inner = outline().buffer(-EDGE_BAND, join_style=2)
hard = []
for fp in b.GetFootprints():
    for p in fp.Pads():
        if p.IsOnLayer(pcbnew.F_Mask):
            lay = pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.F_Mask
            s = pcbnew.SHAPE_POLY_SET()
            p.TransformShapeToPolygon(s, lay, 0, F(0.002), pcbnew.ERROR_OUTSIDE)
            o = s.Outline(0)
            poly = Polygon([(M(o.CPoint(k).x), M(o.CPoint(k).y)) for k in range(o.PointCount())])
            hard.append(poly.buffer((mexp if lay == pcbnew.F_Cu else 0) + MASK_GAP))
        if p.GetDrillSize().x > 0:
            hard.append(Point(M(p.GetPosition().x), M(p.GetPosition().y)).buffer(M(p.GetDrillSize().x) / 2 + HOLE_GAP))
viad = []
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA":
        viad.append(Point(M(t.GetPosition().x), M(t.GetPosition().y)).buffer(M(t.GetDrillValue()) / 2 + VIA_GAP))
crt = {}
for fp in b.GetFootprints():
    g = [it for it in fp.GraphicalItems() if it.GetLayer() == pcbnew.F_CrtYd]
    if g:
        crt[fp.GetReference()] = unary_union([box(M(x.GetBoundingBox().GetX()), M(x.GetBoundingBox().GetY()),
                                                  M(x.GetBoundingBox().GetRight()), M(x.GetBoundingBox().GetBottom()))
                                              for x in g])


def silk_items(skip):
    out = []
    for fp in b.GetFootprints():
        for f in fp.GetFields():
            if f.GetLayer() == pcbnew.F_SilkS and f.IsVisible() and f is not skip and \
                    not (f.IsReference() and fp.GetReference() == skip_ref[0]):
                out.append(ink(f).buffer(SILK_GAP))
        for it in fp.GraphicalItems():
            if it.GetLayer() == pcbnew.F_SilkS:
                bb = it.GetBoundingBox()
                out.append(box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom())).buffer(SILK_GAP))
    for d in b.GetDrawings():
        if d.GetLayer() == pcbnew.F_SilkS:
            bb = d.GetBoundingBox()
            out.append(box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom())).buffer(SILK_GAP))
    return unary_union(out)


skip_ref = [None]
blocked = unary_union(hard)
via_u = unary_union(viad)
for ref in REFS:
    fp = b.FindFootprintByReference(ref)
    f = fp.Reference()
    skip_ref[0] = ref
    others = silk_items(f)
    own = crt[ref]
    oth = {r: g for r, g in crt.items() if r != ref}
    cx0, cy0, cx1, cy1 = own.bounds
    best = None
    for si, (h, w) in enumerate(STYLES):
        f.SetTextSize(pcbnew.VECTOR2I(F(w), F(h)))
        f.SetTextThickness(F(0.15))
        for ang in (0.0, 90.0):
            f.SetTextAngleDegrees(ang)
            nx = int((cx1 - cx0 + 2 * RADIUS) / STEP)
            ny = int((cy1 - cy0 + 2 * RADIUS) / STEP)
            for i in range(nx + 1):
                for j in range(ny + 1):
                    x, y = cx0 - RADIUS + i * STEP, cy0 - RADIUS + j * STEP
                    f.SetPosition(pcbnew.VECTOR2I(F(x), F(y)))
                    g = ink(f)
                    d_own = g.distance(own)
                    if d_own > RADIUS or not inner.contains(g) or g.intersects(blocked) or g.intersects(others):
                        continue
                    d_oth = min(g.distance(o) for o in oth.values() if o.distance(g) < 4.0) \
                        if any(o.distance(g) < 4.0 for o in oth.values()) else 9.0
                    vh = g.intersects(via_u)
                    key = (d_oth == 0.0, not d_own < d_oth, vh, si, round(d_own, 3))
                    if best is None or key < best[0]:
                        best = (key, (x, y), ang, (h, w), d_own, d_oth, vh)
    if best is not None and not best[0][1]:
        key, (x, y), ang, (h, w), d_own, d_oth, vh = best
        f.SetLayer(pcbnew.F_SilkS)
        f.SetMirrored(False)
        f.SetTextSize(pcbnew.VECTOR2I(F(w), F(h)))
        f.SetTextThickness(F(0.15))
        f.SetTextAngleDegrees(ang)
        f.SetPosition(pcbnew.VECTOR2I(F(x), F(y)))
        print("%s: F.Silkscreen (%.2f, %.2f) %.0f deg, %.1f x %.1f mm, gap to own courtyard %.2f mm, to nearest other "
              "courtyard %.2f mm%s" % (ref, x, y, ang, h, w, d_own, d_oth,
                                       (" (over another courtyard)" if d_oth == 0.0 else "") +
                                       (" (crosses a tented via)" if vh else "")))
        continue
    # no unambiguous top-side position (every legal position lies nearer another part than its own): the reference
    # goes onto B.Silkscreen, mirrored, centred over the part (gen/eib_silk_refs_r2.py uses the same fallback). The CR
    # has no part on the bottom side; the text must clear the B.Mask openings, holes and other B.Silkscreen items.
    f.SetLayer(pcbnew.B_SilkS)
    f.SetMirrored(True)
    f.SetTextSize(pcbnew.VECTOR2I(F(1.0), F(1.0)))
    f.SetTextThickness(F(0.15))
    f.SetTextAngleDegrees(0.0)
    f.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    f.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
    f.SetPosition(fp.GetPosition())
    g = ink(f)
    bh = []
    for q in b.GetFootprints():
        for p in q.Pads():
            if p.IsOnLayer(pcbnew.B_Mask) or p.GetDrillSize().x > 0:
                bb = p.GetBoundingBox()
                bh.append(box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom())).buffer(mexp + MASK_GAP))
        for it in list(q.GraphicalItems()) + [x for x in q.GetFields() if x.GetLayer() == pcbnew.B_SilkS]:
            if it.GetLayer() == pcbnew.B_SilkS and q.GetReference() != ref:
                bb = it.GetBoundingBox()
                bh.append(box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom())).buffer(SILK_GAP))
    for d in b.GetDrawings():
        if d.GetLayer() == pcbnew.B_SilkS:
            bb = d.GetBoundingBox()
            bh.append(box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom())).buffer(SILK_GAP))
    assert inner.contains(g) and not any(g.intersects(o) for o in bh), (ref, "bottom position blocked", g.bounds)
    print("%s: B.Silkscreen, mirrored, over the part at (%.2f, %.2f), 1.0 x 1.0 mm%s (best top-side position was "
          "nearer another courtyard than its own)" % (ref, M(fp.GetPosition().x), M(fp.GetPosition().y),
                                                      " (crosses a tented via)" if g.intersects(via_u) else ""))
b.Save(PCB)
