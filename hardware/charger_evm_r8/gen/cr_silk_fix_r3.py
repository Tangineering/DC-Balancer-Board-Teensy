"""Phase B of the 2026-11-14 update: CR reference re-placement, in place (no copper change).

Items (update_2026-11-14/notes_phaseB_silk_cr.md):
- D2: the D107 cathode bar (gen/cr_pin1_marks.py; ink y 40.17-40.33, x 36.92-38.88) lay 0.14 mm below the C102c
  reference that gen/cr_silk_refs_r2.py had moved to (38.52, 39.59), so the bar read as its underline.
- The six references that the phase A check found over another part's courtyard (hidden once that part is fitted):
  C119 (over U110), U119 (over U106), C131 (over U105 / U106), R176 (over D107), U107 (over U118), C102a (over D107).
- D3: the J101 map cells '1 3V3', '5 CE' and '9 GND' stood 0.75 mm from J1 pins 5, 4 and 3 and could read as J1 pin
  labels. The map header becomes 'J101 top view' (the J101 reference field plus a board text 'top view' on one
  baseline, 0.8 mm high, 0.6 mm wide characters), and a 0.15 mm vertical F.Silkscreen line separates the J1 pin column
  from the map over the three map rows, midway between the J1 mask openings and the map texts. These two items are
  here, not in gen/cr_wire_labels.py, because the header position depends on the W7 'SCL' label that
  gen/cr_lead_labels.py places after gen/cr_wire_labels.py.

For each listed reference the script searches a 0.05 mm grid within 3.0 mm of the part's own courtyard, at text
heights 1.0 / 0.8 mm (stroke 0.15 mm; 0.8 mm = rule fab_silk_text), with 0.8 mm-wide characters before 0.6 mm-wide
ones, at 0 and 90 degrees. The ink box (pcbnew GetEffectiveTextShape) of a legal position:
- keeps >= 0.10 mm from every F.Mask opening (pad shape plus the board mask expansion);
- keeps >= 0.15 mm from every hole and >= 0.05 mm from every via drill (no text over a tented via drill);
- keeps >= 0.30 mm from every F.Silkscreen graphic (pin-1 dots, cathode bars, outlines: no mark reads as part of the
  text) and >= 0.10 mm from every other F.Silkscreen text;
- keeps >= 0.25 mm from the board edge;
- has zero overlap with the courtyard polygon of every other part;
- is nearer its own courtyard than any other courtyard by >= 0.10 mm.
Among the legal positions the script prefers the larger text, then the smaller gap to the own courtyard, then 0
degrees. The references are placed one at a time, and each placed text is an obstacle for the next. A reference with
no legal position goes onto B.Silkscreen, mirrored, 1.0 x 1.0 mm, centred over its part (the phase A convention of
R107, gen/cr_silk_refs_r2.py); the F.Fab ${REFERENCE} text of the footprint stays as the assembly-drawing label.

Board marking: the CR carried none. The script adds 'CR r8 2026-11-14' (0.8 mm high, 0.15 mm stroke) where the same
rules hold with no courtyard overlap at all, choosing the position with the largest clearance; it is skipped (and
reported) when no position exists.

Run after gen/cr_lead_labels.py and the rest of the phase A chain (update_2026-11-14/notes_phaseB_silk_cr.md 1.2). Copper, nets and footprint positions are not changed.
Idempotent: the search excludes the inks of the texts it moves, so a second run reaches the same positions; the
board marking is replaced, not duplicated.

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/cr_silk_fix_r3.py
"""
import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union
from shapely.prepared import prep

M, F = pcbnew.ToMM, pcbnew.FromMM
PCB = "cr/cr.kicad_pcb"
REFS = ["C102c", "C102a", "R176", "C119", "U119", "C131", "U107"]
MARKING = "CR r8 2026-11-14"
HEAD_TEXT = "top view"     # J101 map header 'J101 top view' = the J101 reference field + this text (D3)
HEAD_W, HEAD_Y = 0.6, 47.75   # character width; header band y 46.91-48.73 between the via rows (gen/cr_wire_labels.py)
MAP_X0, MAP_X1 = 47.7, 58.3   # J101 map strip (gen/cr_wire_labels.py X0, X1)
SEP_W = 0.15               # separator line between the J1 pin column and the J101 map (D3)
MASK_GAP, HOLE_GAP, VIA_GAP, MARK_GAP, TEXT_GAP, EDGE_BAND = 0.10, 0.15, 0.05, 0.30, 0.10, 0.25
NEAR_MARGIN, RADIUS, STEP = 0.10, 3.0, 0.05
STYLES = [(1.0, 1.0), (0.8, 0.8), (0.8, 0.6)]   # (height, width) mm, stroke 0.15 mm
BOTTOM_REFS = False   # operator ruling 2026-11-17: no B.Silkscreen reference for a top-side SMD part

b = pcbnew.LoadBoard(PCB)
mexp = M(b.GetDesignSettings().m_SolderMaskExpansion)


def ink(t):
    bb = t.GetEffectiveTextShape(False).BBox()
    return box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom()))


def polys(sps):
    out = []
    for i in range(sps.OutlineCount()):
        o = sps.Outline(i)
        out.append(Polygon([(M(o.CPoint(k).x), M(o.CPoint(k).y)) for k in range(o.PointCount())]).buffer(0))
    return unary_union(out)


def bbox(it):
    r = it.GetBoundingBox()
    return box(M(r.GetX()), M(r.GetY()), M(r.GetRight()), M(r.GetBottom()))


sps = pcbnew.SHAPE_POLY_SET()
b.GetBoardPolygonOutlines(sps)
inner = prep(polys(sps).buffer(-EDGE_BAND, join_style=2))

# --- fixed obstacles -------------------------------------------------------------------------------------------
hard, bhard, fmask = [], [], []
for fp in b.GetFootprints():
    for p in fp.Pads():
        for side, mlay, clay, acc in ((0, pcbnew.F_Mask, pcbnew.F_Cu, hard), (1, pcbnew.B_Mask, pcbnew.B_Cu, bhard)):
            if p.IsOnLayer(mlay):
                lay = clay if p.IsOnLayer(clay) else mlay
                s = pcbnew.SHAPE_POLY_SET()
                p.TransformShapeToPolygon(s, lay, 0, F(0.002), pcbnew.ERROR_OUTSIDE)
                acc.append(polys(s).buffer((mexp if lay == clay else 0) + MASK_GAP))
                if side == 0:
                    fmask.append(polys(s).buffer(mexp if lay == clay else 0))
        if p.GetDrillSize().x > 0:
            h = Point(M(p.GetPosition().x), M(p.GetPosition().y)).buffer(M(p.GetDrillSize().x) / 2 + HOLE_GAP)
            hard.append(h)
            bhard.append(h)
vias = []
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA":
        v = Point(M(t.GetPosition().x), M(t.GetPosition().y)).buffer(M(t.GetDrillValue()) / 2 + VIA_GAP)
        hard.append(v)
        bhard.append(v)
crt = {}
for fp in b.GetFootprints():
    c = fp.GetCourtyard(pcbnew.F_CrtYd)
    if c.OutlineCount():
        crt[fp.GetReference()] = polys(c)
moving = {r: b.FindFootprintByReference(r).Reference() for r in REFS}
body = {}   # F.Fab body outline (graphics only, not the F.Fab reference text)
for r in REFS:
    g_ = [bbox(it) for it in b.FindFootprintByReference(r).GraphicalItems()
          if it.GetLayer() == pcbnew.F_Fab and it.GetClass() != "PCB_TEXT"]
    body[r] = unary_union(g_).envelope if g_ else None


def is_mine(d):
    """An item of an earlier run: the board marking, the 'top view' header text or the separator line (the CR has no
    other F.Silkscreen board line)."""
    if d.GetLayer() != pcbnew.F_SilkS:
        return False
    if d.GetClass() == "PCB_SHAPE":
        return True
    return d.GetClass() == "PCB_TEXT" and (d.GetText().startswith("CR r8 ") or d.GetText() == HEAD_TEXT)


old_items = [d for d in b.GetDrawings() if is_mine(d)]   # kept referenced: a freed SWIG object breaks wrapping
for d in old_items:
    b.Remove(d)
jref = b.FindFootprintByReference("J101").Reference()

marks, texts, btexts = [], [], []
for fp in b.GetFootprints():
    for it in fp.GraphicalItems():
        if it.GetLayer() == pcbnew.F_SilkS:
            (texts if it.GetClass() == "PCB_TEXT" else marks).append(bbox(it))
        if it.GetLayer() == pcbnew.B_SilkS:
            btexts.append(bbox(it).buffer(TEXT_GAP))
    for f in fp.GetFields():
        if not f.IsVisible() or ((fp.GetReference() in moving or fp.GetReference() == "J101") and f.IsReference()):
            continue
        if f.GetLayer() == pcbnew.F_SilkS:
            texts.append(ink(f))
        elif f.GetLayer() == pcbnew.B_SilkS:
            btexts.append(ink(f).buffer(TEXT_GAP))
for d in b.GetDrawings():
    if d.GetLayer() == pcbnew.F_SilkS:
        (texts if d.GetClass() == "PCB_TEXT" else marks).append(ink(d) if d.GetClass() == "PCB_TEXT" else bbox(d))
    elif d.GetLayer() == pcbnew.B_SilkS:
        btexts.append(bbox(d).buffer(TEXT_GAP))

hard_u = prep(unary_union(hard))
mark_u = prep(unary_union([m.buffer(MARK_GAP) for m in marks]))
placed_texts = [t.buffer(TEXT_GAP) for t in texts]
crt_items = list(crt.items())

# --- D3: J101 map header 'J101 top view' and the separator line -------------------------------------------------
# The header is the J101 reference field followed by the text 'top view' on one baseline, with the word space of the
# string 'J101 top view'; it is centred over the map as far as the W7 'SCL' label and the via rows allow.
cells = [d for d in b.GetDrawings() if d.GetClass() == "PCB_TEXT" and d.GetLayer() == pcbnew.F_SilkS and
         len(d.GetText().split(" ")) == 2 and d.GetText().split(" ")[0].isdigit()]
assert len(cells) == 9, [c.GetText() for c in cells]
map_u = unary_union([ink(c) for c in cells])
head = pcbnew.PCB_TEXT(b)
head.SetText(HEAD_TEXT)
probe = pcbnew.PCB_TEXT(b)
probe.SetText("J101 " + HEAD_TEXT)
for t_ in (jref, head, probe):
    t_.SetLayer(pcbnew.F_SilkS)
    t_.SetMirrored(False)
    t_.SetTextSize(pcbnew.VECTOR2I(F(HEAD_W), F(0.8)))
    t_.SetTextThickness(F(0.15))
    t_.SetTextAngleDegrees(0.0)
    t_.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
    t_.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
    t_.SetPosition(pcbnew.VECTOR2I(0, 0))
o_j, o_h, o_p = ink(jref).bounds, ink(head).bounds, ink(probe).bounds
space = (o_p[2] - o_p[0]) - (o_j[2] - o_j[0]) - (o_h[2] - o_h[0])
tx_u = prep(unary_union(placed_texts))
hbest = None
for i in range(int((MAP_X1 - MAP_X0) / 0.01) + 1):
    xl = MAP_X0 + i * 0.01
    xh = xl + (o_j[2] - o_j[0]) + space
    if xh + o_h[2] - o_h[0] > MAP_X1:
        break
    for k in range(-60, 61):
        y = HEAD_Y + k * 0.01
        gj = box(xl, y + o_j[1], xl + o_j[2] - o_j[0], y + o_j[3])
        gh = box(xh, y + o_h[1], xh + o_h[2] - o_h[0], y + o_h[3])
        if not (inner.contains(gj) and inner.contains(gh)) or any(hard_u.intersects(g_) or mark_u.intersects(g_) or
                                                                  tx_u.intersects(g_) for g_ in (gj, gh)):
            continue
        key = (round(abs((xl + gh.bounds[2]) / 2 - (MAP_X0 + MAP_X1) / 2), 2), abs(k))
        if hbest is None or key < hbest[0]:
            hbest = (key, xl, xh, y)
assert hbest is not None, "no position for the J101 header"
key, xl, xh, y = hbest
jref.SetPosition(pcbnew.VECTOR2I(F(xl - o_j[0]), F(y)))
head.SetPosition(pcbnew.VECTOR2I(F(xh - o_h[0]), F(y)))
b.Add(head)
head_ink = unary_union([ink(jref), ink(head)])
placed_texts += [ink(jref).buffer(TEXT_GAP), ink(head).buffer(TEXT_GAP)]
# separator: a vertical line midway between the J1 pin-column mask openings and the map, over the three map rows
fmask_u = unary_union(fmask)
m0, m1 = map_u.bounds[1], map_u.bounds[3]
j1_edge = fmask_u.intersection(box(MAP_X0 - 1.5, m0, map_u.bounds[0], m1)).bounds[2]
sx = round((j1_edge + map_u.bounds[0]) / 2, 3)
sep = pcbnew.PCB_SHAPE(b)
sep.SetShape(pcbnew.SHAPE_T_SEGMENT)
sep.SetLayer(pcbnew.F_SilkS)
sep.SetWidth(F(SEP_W))
sep.SetStart(pcbnew.VECTOR2I(F(sx), F(m0)))
sep.SetEnd(pcbnew.VECTOR2I(F(sx), F(m1)))
gs = box(sx - SEP_W / 2, m0 - SEP_W / 2, sx + SEP_W / 2, m1 + SEP_W / 2)
sep_gap_mask, sep_gap_text = gs.distance(fmask_u), gs.distance(map_u)
assert sep_gap_mask >= MASK_GAP and sep_gap_text >= TEXT_GAP, (sep_gap_mask, sep_gap_text)
assert inner.contains(gs) and not hard_u.intersects(gs), ("separator", gs.bounds)
b.Add(sep)
marks.append(gs)
mark_u = prep(unary_union([m.buffer(MARK_GAP) for m in marks]))
report_d3 = ["J101 header 'J101 %s': ink x %.2f-%.2f y %.2f-%.2f, %.1f x %.1f mm, word space %.2f mm"
             % (HEAD_TEXT, head_ink.bounds[0], head_ink.bounds[2], head_ink.bounds[1], head_ink.bounds[3], 0.8, HEAD_W,
                space),
             "separator: x %.3f, y %.2f-%.2f, %.2f mm wide; gap to the J1 mask openings %.3f mm, to the map texts %.3f mm"
             % (sx, m0, m1, SEP_W, sep_gap_mask, sep_gap_text)]


def legal(g, ref, tx, oth):
    if not inner.contains(g) or hard_u.intersects(g) or mark_u.intersects(g) or tx.intersects(g):
        return None
    if oth[1].intersects(g) and oth[0].intersection(g).area > 1e-6:
        return None
    if ref is None:
        return 9.0, 9.0
    if body[ref] is not None and body[ref].intersects(g):   # under the own part body once fitted
        return None
    d_own, d_oth = g.distance(crt[ref]), g.distance(oth[0])
    if not d_own + NEAR_MARGIN <= d_oth:
        return None
    return d_own, d_oth


def search(t, ref, region, styles, keyf, step=STEP):
    tx = prep(unary_union(placed_texts))
    ou = unary_union([c for r, c in crt_items if r != ref])
    oth = (ou, prep(ou))
    x0, y0, x1, y1 = region
    best = None
    for si, (h, w) in enumerate(styles):
        t.SetTextSize(pcbnew.VECTOR2I(F(w), F(h)))
        t.SetTextThickness(F(0.15))
        for ang in (0.0, 90.0):
            t.SetTextAngleDegrees(ang)
            t.SetPosition(pcbnew.VECTOR2I(0, 0))
            o = ink(t).bounds
            nx, ny = int((x1 - x0) / step), int((y1 - y0) / step)
            for i in range(nx + 1):
                for j in range(ny + 1):
                    x, y = x0 + i * step, y0 + j * step
                    g = box(x + o[0], y + o[1], x + o[2], y + o[3])
                    if ref and g.distance(crt[ref]) > RADIUS:
                        continue
                    r = legal(g, ref, tx, oth)
                    if r is None:
                        continue
                    k = keyf(si, ang, g, r)
                    if best is None or k < best[0]:
                        best = (k, x, y, h, w, ang, g, r)
    return best


report = list(report_d3)
for ref in REFS:
    fp = b.FindFootprintByReference(ref)
    f = moving[ref]
    cx0, cy0, cx1, cy1 = crt[ref].bounds
    f.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    f.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
    f.SetLayer(pcbnew.F_SilkS)
    f.SetMirrored(False)
    best = search(f, ref, (cx0 - RADIUS - 2.0, cy0 - RADIUS - 2.0, cx1 + RADIUS + 2.0, cy1 + RADIUS + 2.0), STYLES,
                  lambda si, ang, g, r: (si, round(r[0], 2), ang, round(-r[1], 2)))
    if best is not None:
        k, x, y, h, w, ang, g, (d_own, d_oth) = best
        f.SetTextSize(pcbnew.VECTOR2I(F(w), F(h)))
        f.SetTextThickness(F(0.15))
        f.SetTextAngleDegrees(ang)
        f.SetPosition(pcbnew.VECTOR2I(F(x), F(y)))
        g = ink(f)
        placed_texts.append(g.buffer(TEXT_GAP))
        report.append("%s: F.Silkscreen (%.2f, %.2f) %.0f deg, %.1f x %.1f mm, ink x %.2f-%.2f y %.2f-%.2f, gap to own "
                      "courtyard %.2f mm, to nearest other courtyard %.2f mm"
                      % (ref, x, y, ang, h, w, g.bounds[0], g.bounds[2], g.bounds[1], g.bounds[3], d_own, d_oth))
        continue
    # Operator ruling 2026-11-17: no B.Silkscreen for a top-side SMD part (the bottom cannot be seen during assembly).
    # Without a legal top-side position the reference field moves to F.Fab, hidden; the F.Fab ${REFERENCE} text stays.
    if not BOTTOM_REFS:
        assert [it for it in fp.GraphicalItems() if it.GetLayer() == pcbnew.F_Fab and it.GetClass() == "PCB_TEXT"
                and it.GetText() == "${REFERENCE}"], (ref, "no F.Fab reference text")
        f.SetLayer(pcbnew.F_Fab)
        f.SetMirrored(False)
        f.SetVisible(False)
        report.append("%s: F.Fab only (no legal top-side position; no bottom-side reference, ruling 2026-11-17); "
                      "F.Fab ${REFERENCE} kept" % ref)
        continue
    # superseded fallback (BOTTOM_REFS True): B.Silkscreen, mirrored, over the part. The CR has no bottom-side part;
    # the text must keep the bottom-side margins (B.Mask openings, holes, via drills, other B.Silkscreen items, edge
    # band) and its ink centre must lie inside the own courtyard and nearer the own part centre than any other part
    # centre. Preferred: the larger text, then the smaller offset from the part centre, then 0 degrees.
    f.SetLayer(pcbnew.B_SilkS)
    f.SetMirrored(True)
    bu = prep(unary_union(bhard + btexts))
    pc = Point(M(fp.GetPosition().x), M(fp.GetPosition().y))
    centres = [Point(M(q.GetPosition().x), M(q.GetPosition().y)) for q in b.GetFootprints() if q.GetReference() != ref]
    oth_u = unary_union([c_ for r_, c_ in crt_items if r_ != ref])
    oth_p = prep(oth_u)
    bbest = None
    for si, (h, w) in enumerate(STYLES):
        f.SetTextSize(pcbnew.VECTOR2I(F(w), F(h)))
        f.SetTextThickness(F(0.15))
        for ang in (0.0, 90.0):
            f.SetTextAngleDegrees(ang)
            f.SetPosition(pcbnew.VECTOR2I(0, 0))
            o = ink(f).bounds
            for i in range(int((cx1 - cx0) / STEP) + 1):
                for j in range(int((cy1 - cy0) / STEP) + 1):
                    x, y = cx0 + i * STEP, cy0 + j * STEP
                    g = box(x + o[0], y + o[1], x + o[2], y + o[3])
                    c = g.centroid
                    if not crt[ref].contains(c) or not inner.contains(g) or bu.intersects(g):
                        continue
                    dc = c.distance(pc)
                    if any(c.distance(q) <= dc for q in centres):
                        continue
                    ov = oth_u.intersection(g).area if oth_p.intersects(g) else 0.0
                    k = (round(ov, 1), si, round(dc, 2), ang)
                    if bbest is None or k < bbest[0]:
                        bbest = (k, x, y, h, w, ang)
    assert bbest is not None, (ref, "no legal top-side or bottom-side position")
    k, x, y, h, w, ang = bbest
    b_ov = k[0]
    f.SetTextSize(pcbnew.VECTOR2I(F(w), F(h)))
    f.SetTextThickness(F(0.15))
    f.SetTextAngleDegrees(ang)
    f.SetPosition(pcbnew.VECTOR2I(F(x), F(y)))
    g = ink(f)
    btexts.append(g.buffer(TEXT_GAP))
    fab = [it for it in fp.GraphicalItems() if it.GetLayer() == pcbnew.F_Fab and it.GetClass() == "PCB_TEXT"
           and it.GetText() == "${REFERENCE}"]
    assert fab, (ref, "no F.Fab reference text")
    report.append("%s: B.Silkscreen, mirrored, (%.2f, %.2f) %.0f deg, %.1f x %.1f mm, over the part at (%.2f, %.2f), "
                  "ink x %.2f-%.2f y %.2f-%.2f, overlap with other courtyards %.1f mm2 (no legal top-side position); "
                  "F.Fab ${REFERENCE} kept"
                  % (ref, x, y, ang, h, w, M(fp.GetPosition().x), M(fp.GetPosition().y), g.bounds[0], g.bounds[2],
                     g.bounds[1], g.bounds[3], b_ov))

# --- board marking ---------------------------------------------------------------------------------------------
t = pcbnew.PCB_TEXT(b)
t.SetText(MARKING)
t.SetLayer(pcbnew.F_SilkS)
t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
bx = polys(sps).bounds
allobs = unary_union(hard + [m.buffer(MARK_GAP) for m in marks] + placed_texts + list(crt.values()))
best = search(t, None, bx, [(0.8, 0.8), (0.8, 0.6)],
              lambda si, ang, g, r: (si, ang, -round(min(g.distance(allobs), 1.0), 2)), step=0.25)
if best is None:
    report.append("board marking: no position meets the rules; not added")
else:
    k, x, y, h, w, ang, g, r = best
    t.SetTextSize(pcbnew.VECTOR2I(F(w), F(h)))
    t.SetTextThickness(F(0.15))
    t.SetTextAngleDegrees(ang)
    t.SetPosition(pcbnew.VECTOR2I(F(x), F(y)))
    b.Add(t)
    report.append("board marking '%s': F.Silkscreen (%.2f, %.2f) %.0f deg, %.1f x %.1f mm, ink x %.2f-%.2f y %.2f-%.2f,"
                  " clearance to the nearest obstacle %.2f mm"
                  % (MARKING, x, y, ang, h, w, g.bounds[0], g.bounds[2], g.bounds[1], g.bounds[3], -k[2]))
for line in report:
    print(line)
b.Save(PCB)
