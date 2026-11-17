"""REVIEW_2026-11-14 INT-5 / CRL-3 (S3): the W3 lead pad (VCHG, battery lead) had its reference on F.Fab only, while
W4 (GND) beside it was labelled, and the W6 (TS_EXT / GND) and W7 (SDA / GND / SCL) lead pads carried no per-hole
net marks. This script, in place:

1. moves the W3 reference field from F.Fab to F.Silkscreen, next to the W3 pad;
2. adds a net label beside each hole of W6 and W7 on F.Silkscreen: W6 'TS' (pad 1, TS_EXT) and 'GND' (pad 2); W7
   'SCL' (pad 1), 'GND' (pad 2) and 'SDA' (pad 3). Where the full name has no legal position, the single letter of the
   INT-5 recommendation ('T', 'G', 'C', 'D') is used. The names come from the board pad nets, so they cannot disagree
   with cr.net.

W1, W2, W4 and W6 already carry their references on F.Silkscreen and are not changed (checked by the script). The W7
reference moves to the +x side of the new W7 label column (it stood level with pad 3, where the SDA label goes). W5 is the
J101 wire-pad grid (gen/cr_wire_labels.py).

Placement: each text is searched on a 0.05 mm grid within 2.0 mm of its pad, at 0.8 mm height and 0.15 mm stroke
(fab_silk_text), 0.8 mm character width first and 0.6 mm only where 0.8 mm has no legal position, at 0 and 90 degrees.
Each W6 / W7 label stands on the +x side of its hole with its centre within 0.3 mm of the hole centre in y. A position
is legal when the ink box keeps >= 0.05 mm from every F.Mask opening, >= 0.15 mm from every hole, >= 0.10 mm
from every other F.Silkscreen item and >= 0.25 mm from the board edge, and when the nearest pad to the text is its own
pad (no ambiguity). The script prefers positions clear of the tented via drills (+0.05 mm), then the wider text, then
the smaller distance to the pad. Idempotent: labels written by an earlier run are removed and placed again.

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/cr_lead_labels.py
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
NAMES = {"/TS_EXT": ["TS", "T"], "/GND": ["GND", "G"], "/SCL": ["SCL", "C"], "/SDA": ["SDA", "D"]}
LABELLED = ["W6", "W7"]
RADIUS, STEP = 2.0, 0.05

b = pcbnew.LoadBoard(PCB)
mexp = M(b.GetDesignSettings().m_SolderMaskExpansion)
fps = {r: b.FindFootprintByReference(r) for r in ["W1", "W2", "W3", "W4", "W6", "W7"]}
for r in ["W1", "W2", "W4", "W6", "W7"]:
    assert fps[r].Reference().GetLayer() == pcbnew.F_SilkS, r


def ink(t):
    bb = t.GetEffectiveTextShape(False).BBox()
    return box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom()))


def bbox(it):
    bb = it.GetBoundingBox()
    return box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom()))


# remove the labels of an earlier run: board texts on F.Silkscreen whose text is a label name and which lie within
# RADIUS + 3 mm of a W6 / W7 pad (no other board text on the CR reads TS, GND, SCL, SDA or a single letter)
padpts = [Point(M(p.GetPosition().x), M(p.GetPosition().y)) for r in LABELLED for p in fps[r].Pads()]
allnames = {n for v in NAMES.values() for n in v}
GONE = [d for d in b.GetDrawings() if d.GetLayer() == pcbnew.F_SilkS and d.GetClass() == "PCB_TEXT"
        and d.GetText() in allnames and min(bbox(d).distance(q) for q in padpts) < RADIUS + 3.0]
for d in GONE:
    b.Remove(d)

pads = []   # (ref, pad number, mask polygon)
hard = []
for fp in b.GetFootprints():
    for p in fp.Pads():
        if p.IsOnLayer(pcbnew.F_Mask):
            lay = pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.F_Mask
            s = pcbnew.SHAPE_POLY_SET()
            p.TransformShapeToPolygon(s, lay, 0, F(0.002), pcbnew.ERROR_OUTSIDE)
            o = s.Outline(0)
            poly = Polygon([(M(o.CPoint(k).x), M(o.CPoint(k).y)) for k in range(o.PointCount())]) \
                .buffer(mexp if lay == pcbnew.F_Cu else 0)
            pads.append((fp.GetReference(), p.GetNumber(), poly))
            hard.append(poly.buffer(0.05))
        if p.GetDrillSize().x > 0:
            hard.append(Point(M(p.GetPosition().x), M(p.GetPosition().y)).buffer(M(p.GetDrillSize().x) / 2 + 0.15))
vias = unary_union([Point(M(t.GetPosition().x), M(t.GetPosition().y)).buffer(M(t.GetDrillValue()) / 2 + 0.05)
                    for t in b.GetTracks() if t.GetClass() == "PCB_VIA"])
sps = pcbnew.SHAPE_POLY_SET()
b.GetBoardPolygonOutlines(sps)
o = sps.Outline(0)
inner = Polygon([(M(o.CPoint(k).x), M(o.CPoint(k).y)) for k in range(o.PointCount())]).buffer(0).buffer(-0.25,
                                                                                                    join_style=2)
blocked = unary_union(hard)


def silk(skip_ref_of=None):
    out = []
    for fp in b.GetFootprints():
        for f in fp.GetFields():
            if f.GetLayer() == pcbnew.F_SilkS and f.IsVisible() and \
                    not (f.IsReference() and fp.GetReference() == skip_ref_of):
                out.append(ink(f).buffer(0.10))
        for it in fp.GraphicalItems():
            if it.GetLayer() == pcbnew.F_SilkS:
                out.append(bbox(it).buffer(0.10))
    for d in b.GetDrawings():
        if d.GetLayer() == pcbnew.F_SilkS:
            out.append(bbox(d).buffer(0.10))
    return unary_union(out)


def best_spot(t, ref, num, texts, skip=None, accept=None, ambiguity=True, radius=RADIUS):
    """Search a legal position for text item t next to pad <num> of <ref> (unambiguous unless ambiguity is False;
    accept(g) is an extra filter on the ink box); returns a report line."""
    target = [g for r, n, g in pads if r == ref and n == num][0]
    near_pads = [(r, n, g) for r, n, g in pads if g.distance(target) < radius + 4.0]
    others = silk(skip)
    cx0, cy0, cx1, cy1 = target.bounds
    best = None
    for ti, s in enumerate(texts):
        t.SetText(s)
        for wi, w in enumerate((0.8, 0.6)):
            t.SetTextSize(pcbnew.VECTOR2I(F(w), F(0.8)))
            t.SetTextThickness(F(0.15))
            for ang in (0.0, 90.0):
                t.SetTextAngleDegrees(ang)
                for i in range(int((cx1 - cx0 + 2 * radius + 2) / STEP) + 1):
                    for j in range(int((cy1 - cy0 + 2 * radius + 2) / STEP) + 1):
                        x, y = cx0 - radius - 1 + i * STEP, cy0 - radius - 1 + j * STEP
                        t.SetPosition(pcbnew.VECTOR2I(F(x), F(y)))
                        g = ink(t)
                        d = g.distance(target)
                        if d > radius or not inner.contains(g) or g.intersects(blocked) or g.intersects(others):
                            continue
                        if accept is not None and not accept(g):
                            continue
                        dn = min(g.distance(q) for r, n, q in near_pads if not (r == ref and n == num))
                        if ambiguity and not d < dn:
                            continue
                        key = (ti, g.intersects(vias), wi, round(d, 3))
                        if best is None or key < best[0]:
                            best = (key, s, w, ang, (x, y))
    assert best is not None, (ref, num, texts)
    key, s, w, ang, (x, y) = best
    t.SetText(s)
    t.SetTextSize(pcbnew.VECTOR2I(F(w), F(0.8)))
    t.SetTextThickness(F(0.15))
    t.SetTextAngleDegrees(ang)
    t.SetPosition(pcbnew.VECTOR2I(F(x), F(y)))
    g = ink(t)
    return "%s.%s '%s' at (%.2f, %.2f) %.0f deg, 0.8 x %.1f mm, %.2f mm from the pad%s" % (
        ref, num, s, M(t.GetPosition().x), M(t.GetPosition().y), ang, w, g.distance(target),
        " (crosses a tented via)" if key[1] else "")


# 1. W3 reference on F.Silkscreen
w3 = fps["W3"].Reference()
w3.SetLayer(pcbnew.F_SilkS)
w3.SetVisible(True)
w3.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
w3.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
print("W3 reference: " + best_spot(w3, "W3", "1", ["W3"], skip="W3"))

# 2. W6 / W7 per-hole net labels: each label to the +x side of its pad, level with it (ink centre within 0.3 mm of the
# pad centre in y), so that a label reads across to its own hole. The W7 reference, which stood level with pad 3, is
# then re-placed to the +x side of the label column, level with pad 2, so it brackets the three labels.
for ref in LABELLED:
    labels = []
    for p in sorted(fps[ref].Pads(), key=lambda q: int(q.GetNumber())):
        t = pcbnew.PCB_TEXT(b)
        t.SetLayer(pcbnew.F_SilkS)
        t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
        py, pr = M(p.GetPosition().y), M(p.GetPosition().x) + M(p.GetSize().x) / 2

        def level(g, py=py, pr=pr):
            return abs(g.centroid.y - py) <= 0.3 and g.bounds[0] > pr

        msg = best_spot(t, ref, p.GetNumber(), NAMES[p.GetNetname()], skip="W7" if ref == "W7" else None,
                        accept=level)
        b.Add(t)
        labels.append(t)
        print("label: " + msg)
    if ref == "W7":
        col = max(ink(t).bounds[2] for t in labels)
        p2 = [p for p in fps["W7"].Pads() if p.GetNumber() == "2"][0]
        y2 = M(p2.GetPosition().y)
        r7 = fps["W7"].Reference()
        r7.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        r7.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
        print("W7 reference: " + best_spot(r7, "W7", "2", ["W7"], skip="W7", ambiguity=False,
                                           accept=lambda g: abs(g.centroid.y - y2) <= 0.3 and g.bounds[0] > col + 0.3, radius=4.0))
b.Save(PCB)
