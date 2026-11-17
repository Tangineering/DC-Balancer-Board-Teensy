"""Phase C of the 2026-11-14 update (second review, R2-INT-0, S2): W1 / W2 input-pair identification, in place.

Defect: the W1 reference (W1 = /VCHGOUT, the 20 AWG lead to EVM J1 pin 2, VIN1) stood below the W2 pad (W2 = /GND, the
20 AWG lead to EVM J1 pin 1, PGND), 0.10 mm from the W2 pad and 3.30 mm (centre to centre) from the W1 pad, so the
input pair could be swapped. A swap wires U101 VCHGOUT to the EVM PGND, that is the T-C-04 hard short at the EVM end
at the first power-up (sim/hardshort/RESULTS.md section 6).

This script, in place (F.Silkscreen texts only; copper, pads, zones and footprint positions do not change):

1. adds the text 'VIN1' level with the W1 pad on its +x side: the EVM end of the W1 lead is EVM J1 pin 2, VIN1 (the
   EVM terminal name is used rather than 'VIN', which could be read as the CR input net /VCHGIN);
2. moves the W1 reference field to the +x side of the W1 pad as well, with >= 0.40 mm between its ink and the 'VIN1'
   ink (the board-text gap of gen/eib_silk_refs_r2.py, so that the two texts do not read as one word);
3. adds the net text 'GND' next to the W2 pad on the side away from W1 (W2 lands on EVM J1 pin 1, PGND).

Rules (LAYOUT_DECISIONS D-78, CR rules for every moved or new text): text height 0.8 mm, stroke 0.15 mm, character
width 0.8 mm first and 0.6 mm where 0.8 mm has no legal position, 0 or 90 degrees. The ink box (pcbnew
GetEffectiveTextShape) of a legal position keeps >= 0.10 mm from every F.Mask opening (pad shape plus the board mask
expansion), >= 0.15 mm from every hole, >= 0.05 mm from every via drill, >= 0.30 mm from every F.Silkscreen graphic,
>= 0.10 mm from every other F.Silkscreen text and >= 0.25 mm inside the board edge, and has zero overlap with the
courtyard of any footprint other than its own. In addition, the ink lies nearer its own pad than any other pad by
>= 0.15 mm (AMBIG), and the 'VIN1' and 'W1' texts lie wholly on the +x side of the W1 pad, the 'GND' text wholly on
the -x side of the W1 pad's left edge (so that no W1-side text reads across to W2 and no W2 text reads across to W1).
Among the legal positions the script prefers the full net name, then an ink gap to the own pad of 0.5 mm or less,
then 0 degrees, then 0.8 mm characters, then the smaller gap to the own pad.

Idempotent: texts of an earlier run (board texts 'VIN1' / 'VIN' / 'GND' / 'G' on F.Silkscreen whose nearest pad is W1 or W2)
are removed before the search, and the W1 reference is searched with its own ink excluded, so a second run reaches the
same positions. Run it after gen/cr_silk_fix_r3.py and gen/sync_fields.py, before gen/cr_silk_refs_report.py
(HANDOFF.md section 4 step 9a).

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/cr_silk_fix_r4.py [board.kicad_pcb]
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
PCB = sys.argv[1] if len(sys.argv) > 1 else "cr/cr.kicad_pcb"
MASK_GAP, HOLE_GAP, VIA_GAP, GFX_GAP, TXT_GAP, EDGE, AMBIG = 0.10, 0.15, 0.05, 0.30, 0.10, 0.25, 0.15
STEP, RADIUS = 0.05, 4.0
LABELS = {"VIN1", "VIN", "GND", "G", "V"}

b = pcbnew.LoadBoard(PCB)
mexp = M(b.GetDesignSettings().m_SolderMaskExpansion)
W1, W2 = b.FindFootprintByReference("W1"), b.FindFootprintByReference("W2")
p1, p2 = list(W1.Pads())[0], list(W2.Pads())[0]
assert p1.GetNetname() == "/VCHGOUT" and p2.GetNetname() == "/GND", (p1.GetNetname(), p2.GetNetname())


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


# pads (F.Mask openings) and holes
pads, hard = [], []
for fp in b.GetFootprints():
    for p in fp.Pads():
        if p.IsOnLayer(pcbnew.F_Mask):
            lay = pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.F_Mask
            g = ppoly(p.GetEffectivePolygon(lay, pcbnew.ERROR_OUTSIDE)).buffer(mexp if lay == pcbnew.F_Cu else 0)
            pads.append((fp.GetReference(), p.GetNumber(), g))
            hard.append(g.buffer(MASK_GAP))
        if p.GetDrillSize().x > 0:
            hard.append(Point(M(p.GetPosition().x), M(p.GetPosition().y)).buffer(M(p.GetDrillSize().x) / 2 + HOLE_GAP))
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA":
        hard.append(Point(M(t.GetPosition().x), M(t.GetPosition().y)).buffer(M(t.GetDrillValue()) / 2 + VIA_GAP))
hard = unary_union(hard)
crt = {}
for fp in b.GetFootprints():
    c = fp.GetCourtyard(pcbnew.F_CrtYd)
    if c.OutlineCount():
        crt[fp.GetReference()] = ppoly(c)
sps = pcbnew.SHAPE_POLY_SET()
b.GetBoardPolygonOutlines(sps)
inner = ppoly(sps).buffer(-EDGE, join_style=2)
PAD1 = [g for r, n, g in pads if r == "W1"][0]
PAD2 = [g for r, n, g in pads if r == "W2"][0]


def nearest_ref(g):
    return min(((q.distance(g), r) for r, n, q in pads))[1]


# 0. remove the labels of an earlier run
gone = [d for d in b.GetDrawings() if d.GetLayer() == pcbnew.F_SilkS and d.GetClass() == "PCB_TEXT"
        and d.GetText() in LABELS and nearest_ref(ink(d)) in ("W1", "W2")]
for d in gone:
    b.Remove(d)


def silk(skip=()):
    """F.Silkscreen obstacles: other texts +TXT_GAP, graphics +GFX_GAP; items in skip are left out."""
    out = []
    for fp in b.GetFootprints():
        for f in fp.GetFields():
            if f.GetLayer() == pcbnew.F_SilkS and f.IsVisible() and f.m_Uuid.AsString() not in skip:
                out.append(ink(f).buffer(TXT_GAP))
        for it in fp.GraphicalItems():
            if it.GetLayer() == pcbnew.F_SilkS:
                out.append(bbox(it).buffer(GFX_GAP))
    for d in b.GetDrawings():
        if d.GetLayer() == pcbnew.F_SilkS and d.m_Uuid.AsString() not in skip:
            out.append(ink(d).buffer(TXT_GAP) if d.GetClass() == "PCB_TEXT" else bbox(d).buffer(GFX_GAP))
    return unary_union(out)


def search(t, ref, texts, accept, skip=()):
    target = PAD1 if ref == "W1" else PAD2
    others = silk(skip)
    near = [(r, q) for r, n, q in pads if r != ref and q.distance(target) < RADIUS + 4.0]
    x0, y0, x1, y1 = target.bounds
    best = None
    for ti, s in enumerate(texts):
        t.SetText(s)
        for wi, w in enumerate((0.8, 0.6)):
            t.SetTextSize(pcbnew.VECTOR2I(F(w), F(0.8)))
            t.SetTextThickness(F(0.15))
            for ai, ang in enumerate((0.0, 90.0)):
                t.SetTextAngleDegrees(ang)
                for i in range(int((x1 - x0 + 2 * RADIUS) / STEP) + 1):
                    for j in range(int((y1 - y0 + 2 * RADIUS) / STEP) + 1):
                        x, y = x0 - RADIUS + i * STEP, y0 - RADIUS + j * STEP
                        t.SetPosition(pcbnew.VECTOR2I(F(x), F(y)))
                        g = ink(t)
                        d = g.distance(target)
                        if d > RADIUS or not accept(g) or not inner.contains(g):
                            continue
                        if g.intersects(hard) or g.intersects(others):
                            continue
                        if any(g.intersects(c) for r, c in crt.items() if r != ref):
                            continue
                        dn = min(q.distance(g) for r, q in near)
                        if d + AMBIG > dn:
                            continue
                        key = (ti, d > 0.5, ai, wi, round(d, 3))
                        if best is None or key < best[0]:
                            best = (key, s, w, ang, x, y, dn)
    assert best is not None, (ref, texts)
    key, s, w, ang, x, y, dn = best
    t.SetText(s)
    t.SetTextSize(pcbnew.VECTOR2I(F(w), F(0.8)))
    t.SetTextThickness(F(0.15))
    t.SetTextAngleDegrees(ang)
    t.SetPosition(pcbnew.VECTOR2I(F(x), F(y)))
    g = ink(t)
    return "'%s' at (%.2f, %.2f), %.0f deg, 0.8 x %.1f mm, ink x %.2f-%.2f y %.2f-%.2f, %.2f mm from %s, %.2f mm " \
           "from the nearest other pad" % (s, M(t.GetPosition().x), M(t.GetPosition().y), ang, w, g.bounds[0],
                                            g.bounds[2], g.bounds[1], g.bounds[3], g.distance(PAD1 if ref == "W1" else
                                                                                           PAD2), ref, dn)


def new_text():
    t = pcbnew.PCB_TEXT(b)
    t.SetLayer(pcbnew.F_SilkS)
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
    return t


py1 = M(p1.GetPosition().y)
r1 = PAD1.bounds[2]
l1 = PAD1.bounds[0]
# 1. 'VIN1' level with W1 on its +x side
vin = new_text()
print("W1 net text: " + search(vin, "W1", ["VIN1", "VIN", "V"],
                               lambda g: g.bounds[0] > r1 and abs(g.centroid.y - py1) <= 0.3))
b.Add(vin)
# 2. W1 reference on the +x side of W1, 0.40 mm clear of the VIN1 ink
ref1 = W1.Reference()
assert ref1.GetLayer() == pcbnew.F_SilkS and ref1.IsVisible()
ref1.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
ref1.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
vink = ink(vin)
print("W1 reference: " + search(ref1, "W1", ["W1"],
                                lambda g: g.bounds[0] > r1 and g.distance(vink) >= 0.40,
                                skip=(ref1.m_Uuid.AsString(),)))
# 3. 'GND' at W2, wholly left of the W1 pad edge (minus the ambiguity margin)
gnd = new_text()
print("W2 net text: " + search(gnd, "W2", ["GND", "G"], lambda g: g.bounds[2] < l1 - 0.6))
b.Add(gnd)
b.Save(PCB)
print("saved " + PCB)
