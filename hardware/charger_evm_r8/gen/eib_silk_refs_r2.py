"""REVIEW_2026-11-14 EIL-2 (S2): on the EIB several references stood 3-7 mm from their parts and nearer to another part
(Q201 3.7 mm from Q202, R250 1.6 mm from R266; R267-R271, R273 and R276 3.8-6.3 mm away), so a 10 ohm part could be
taken for a 47 kOhm part, and U201's reference was on F.Fab only (D-64). This script re-places every reference field
of the EIB parts (C, R, Q, U and J201; the E pads and holes keep their hidden fields) on F.Silkscreen, in place,
under an unambiguity rule that gen/silk_refs.py (D-59, D-64) did not have:

- the text ink box keeps clear of every mask opening (+0.05 mm), every pad drill (+0.15 mm), every silkscreen graphic
  (+0.10 mm: the pin-1 dots of gen/eib_pin1_marks.py, the J201 bar, the J201 map lines), every board text (+0.40 mm,
  so that a reference does not run into the J201 map or the board marking as one word), every other reference
  (+0.25 mm), every courtyard, its own included, and the 0.25 mm silk-to-edge band;
- the gap to every other courtyard is at least max(2 x d_own, d_own + AMBIG), with d_own the gap to its own courtyard
  and d_own <= RADIUS, so that each reference reads as the label of exactly one part (DNP footprints count: an empty
  footprint must not take the label of a fitted part);
- tented vias are avoided where a position exists without them.

Text 0.8 mm high with 0.15 mm stroke (fab_silk_text); where no 0.8 x 0.8 mm position exists, a 0.8 mm high, 0.6 mm
wide text is tried (height and stroke stay at the rule). The fitted parts are placed first; a reference that finds
no position moves to F.Fab and is listed (the iBOM then carries it); for a fitted part, a mirrored B.Silkscreen text
of the reference is also placed over the part, so that the part can be identified from the bottom. A randomized greedy search (fixed seed) keeps
the assignment with the most fitted parts on the silkscreen, then the smallest total distance. Copper, nets,
footprint positions and the library footprints are not changed. Rerunning gives the same result (fixed seed).

Phase B (2026-11-14, defect D4 of the phase A check and the phase B text rules) adds four rules:

- the text ink box keeps 0.10 mm (was 0.05 mm) from every mask opening (MASK_GAP);
- no text stroke lies over a via drill; the test is made on the stroke outline, so an ink box may span a drill
  between two strokes (DRILL_HARD);
- among the candidates of equal cost, each reference takes the one with the largest gap to the other references
  (spread pass), so that "R253" no longer ends against "R273";
- a reference whose text centre lies nearer a fitted part without a top-side label than its own part leaves the top
  side (orphan rule), so that "C202" no longer stands level with the unlabelled R254; the search scores the
  assignments after this rule.

The report also flags each reference whose text centre lies nearer another courtyard than its own (information
only; as a rule it removed up to 8 fitted references). The bottom-side fallback tries both text widths on a
+/-1.0 mm grid. The B.Silkscreen texts are recreated on each run with new UUIDs; their geometry does not change.

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/eib_silk_refs_r2.py [report.md]
"""
import random
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass
from shapely.affinity import translate
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

M, F = pcbnew.ToMM, pcbnew.FromMM
PCB = "eib/eib.kicad_pcb"
MASK_GAP, SILK_GAP, TEXT_GAP, REF_GAP, EDGE = 0.10, 0.10, 0.40, 0.25, 0.25
# phase B (D4): the text-centre test is reported, not scored (CENTRE_PEN 0): as a hard rule or a 1.0 cost it
# removed 1 to 3 fitted references from the silkscreen and found no centre-clear position for U201 or C202.
# VIA_HARD True removes 5 fitted references. TIE is the cost band of the spread pass.
CENTRE_RULE, VIA_HARD, CENTRE_PEN, TIE, VIA_GAP = True, False, 0.0, 0.005, 0.05
BACK_GAP = 0.80   # phase B: gap between two bottom-side reference texts
DRILL_HARD = True   # phase B: no text stroke over a via drill (stroke level; the ink box may span a drill)
RADIUS, AMBIG, STEP = 2.0, 0.15, 0.1
SIZES = [(0.8, 0.8), (0.6, 0.8)]      # (width, height) mm; stroke 0.15
TRIALS = 400

b = pcbnew.LoadBoard(PCB)
mexp = M(b.GetDesignSettings().m_SolderMaskExpansion)


def poly(sps, i=0):
    o = sps.Outline(i)
    return Polygon([(M(o.CPoint(k).x), M(o.CPoint(k).y)) for k in range(o.PointCount())])


def ink(t):
    bb = t.GetEffectiveTextShape(False).BBox()
    return box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom()))


static, vias, drills = [], [], []
court = {}
for fp in b.GetFootprints():
    for p in fp.Pads():
        if p.IsOnLayer(pcbnew.F_Mask):
            static.append(poly(p.GetEffectivePolygon(pcbnew.F_Cu, pcbnew.ERROR_OUTSIDE)).buffer(mexp + MASK_GAP))
        if p.GetDrillSize().x > 0:
            static.append(Point(M(p.GetPosition().x), M(p.GetPosition().y)).buffer(M(p.GetDrillSize().x) / 2 + 0.15))
    for it in fp.GraphicalItems():
        if it.GetLayer() == pcbnew.F_SilkS:
            bb = it.GetBoundingBox()
            static.append(box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom())).buffer(SILK_GAP))
    c = fp.GetCourtyard(pcbnew.F_CrtYd)
    if c.OutlineCount():
        court[fp.GetReference()] = poly(c)
for d in b.GetDrawings():
    if d.GetLayer() == pcbnew.F_SilkS:
        g = ink(d) if d.GetClass() == "PCB_TEXT" else None
        if g is None:
            bb = d.GetBoundingBox()
            g = box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom()))
        static.append(g.buffer(TEXT_GAP if d.GetClass() == "PCB_TEXT" else SILK_GAP))
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA":
        vias.append(Point(M(t.GetPosition().x), M(t.GetPosition().y)).buffer(M(t.GetDrillValue()) / 2 + VIA_GAP))
        drills.append(Point(M(t.GetPosition().x), M(t.GetPosition().y)).buffer(M(t.GetDrillValue()) / 2))
e = b.GetBoardEdgesBoundingBox()
inner = box(M(e.GetX()) + EDGE + 0.05, M(e.GetY()) + EDGE + 0.05, M(e.GetRight()) - EDGE - 0.05,
            M(e.GetBottom()) - EDGE - 0.05)
stree, vtree = STRtree(static), STRtree(vias)
ctree_keys = sorted(court)
ctree = STRtree([court[k] for k in ctree_keys])

targets = [fp for fp in b.GetFootprints() if fp.GetReference()[0] in "CRQU" or fp.GetReference() == "J201"]


def strokes(t):
    """The filled stroke outline of a text (phase B: the via-drill test is made on the strokes)."""
    sps = pcbnew.SHAPE_POLY_SET()
    t.TransformTextToPolySet(sps, 0, F(0.005), pcbnew.ERROR_OUTSIDE)
    return unary_union([poly(sps, i).buffer(0) for i in range(sps.OutlineCount())])


def candidates(fp):
    ref = fp.Reference()
    r = fp.GetReference()
    own = court[r]
    cx, cy = own.centroid.x, own.centroid.y
    out = []
    for si, (w, h) in enumerate(SIZES):
        for ang in (0.0, 90.0):
            ref.SetTextSize(pcbnew.VECTOR2I(F(w), F(h)))
            ref.SetTextThickness(F(0.15))
            ref.SetTextAngleDegrees(ang)
            ref.SetPosition(pcbnew.VECTOR2I(F(cx), F(cy)))
            g0 = ink(ref)
            s0 = strokes(ref)
            ox, oy = g0.centroid.x - cx, g0.centroid.y - cy
            span = RADIUS + max(own.bounds[2] - own.bounds[0], own.bounds[3] - own.bounds[1])
            n = int(span / STEP) + 1
            for i in range(-n, n + 1):
                for j in range(-n, n + 1):
                    x, y = cx + i * STEP, cy + j * STEP
                    gx0, gy0, gx1, gy1 = g0.bounds
                    g = box(gx0 + i * STEP, gy0 + j * STEP, gx1 + i * STEP, gy1 + j * STEP)
                    if not inner.contains(g):
                        continue
                    d_own = g.distance(own)
                    if d_own <= 0 or d_own > RADIUS:
                        continue
                    if any(g.intersects(static[k]) for k in stree.query(g)):
                        continue
                    near = g.buffer(max(2 * d_own, d_own + AMBIG))
                    if any(ctree_keys[k] != r and ctree.geometries[k].intersects(near) for k in ctree.query(near)):
                        continue
                    off_centre = False
                    if CENTRE_RULE:   # phase B (D4): the text centre lies nearer its own part than any other part
                        c = g.centroid
                        dc = c.distance(own)
                        off_centre = any(ctree_keys[k] != r and ctree.geometries[k].distance(c) < dc
                                         for k in ctree.query(c.buffer(dc)))
                    hit = [k for k in vtree.query(g) if g.intersects(vias[k])]
                    on_via = bool(hit)
                    if DRILL_HARD and hit:
                        sk = translate(s0, i * STEP, j * STEP)
                        if any(sk.intersects(drills[k]) for k in hit):
                            continue
                    if VIA_HARD and on_via:
                        continue
                    cost = (d_own + (0.3 if ang else 0.0) + 1.0 * si + (2.0 if on_via else 0.0)
                            + (CENTRE_PEN if off_centre else 0.0))
                    out.append((cost, x, y, w, h, ang, g, on_via, off_centre))
    out.sort(key=lambda c: c[0])
    return out


saved = {fp.GetReference(): (fp.Reference().GetPosition(), fp.Reference().GetTextSize(),
                             fp.Reference().GetTextThickness(), fp.Reference().GetTextAngleDegrees(),
                             fp.Reference().GetLayer()) for fp in targets}
cand = {fp.GetReference(): candidates(fp) for fp in targets}
fitted = [fp.GetReference() for fp in targets if not fp.IsDNP()]
dnp = [fp.GetReference() for fp in targets if fp.IsDNP()]


def orphan_check(picks):
    """Phase B (D4): a reference whose text centre lies nearer a fitted part without a top-side label than its own
    part would be read as that part's label (the 2026-11-14 check: "C202" standing level with the unlabelled R254).
    Such a reference leaves the top side (F.Fab, plus the bottom-side text for a fitted part). Repeated until no
    reference is removed, because each removal leaves another fitted part without a top-side label."""
    removed = []
    while True:
        bad = []
        for r, c in picks.items():
            ctr = c[6].centroid
            dc = ctr.distance(court[r])
            if any(k != r and k not in picks and court[k].distance(ctr) < dc for k in fitted):
                bad.append(r)
        if not bad:
            return removed
        for r in bad:
            del picks[r]
        removed += bad


def solve(order):
    placed, picks = [], {}
    for r in order:
        for c in cand[r][:400]:
            g = c[6]
            if all(not g.intersects(p) for p in placed):
                picks[r] = c
                placed.append(g.buffer(REF_GAP))
                break
    orphan_check(picks)   # the score counts the references that survive the orphan rule
    nf = sum(1 for r in fitted if r in picks)
    nd = sum(1 for r in dnp if r in picks)
    return (-nf, -nd, sum(c[0] for c in picks.values())), picks


rng = random.Random(20261114)
base = sorted(fitted, key=lambda r: len(cand[r])) + sorted(dnp, key=lambda r: len(cand[r]))
best = solve(base)
for _ in range(TRIALS):
    f = fitted[:]
    d = dnp[:]
    rng.shuffle(f)
    rng.shuffle(d)
    f.sort(key=lambda r: len(cand[r]) * rng.uniform(0.5, 2.0))
    s = solve(f + d)
    if s[0] < best[0]:
        best = s
score, picks = best


def spread(picks):
    """Phase B (D4): among the candidates of equal cost (within TIE), move each reference to the one with the largest
    gap to the other references, so that two labels do not read as one word ("R253" against "R273"). The own-part gap,
    the rules and the score do not change. Fixed order, two passes: deterministic."""
    for _ in range(2):
        for r in sorted(picks):
            others = [picks[k][6] for k in picks if k != r]
            c0 = picks[r]
            best_c, best_gap = c0, min(o.distance(c0[6]) for o in others)
            for c in cand[r]:
                if c[0] > c0[0] + TIE:
                    break
                if any(c[6].intersects(o.buffer(REF_GAP)) for o in others):
                    continue
                gap = min(o.distance(c[6]) for o in others)
                if gap > best_gap + 1e-6:
                    best_c, best_gap = c, gap
            picks[r] = best_c


spread(picks)


orphaned = orphan_check(picks)   # after the spread pass

rows, fab = [], []
for fp in sorted(targets, key=lambda f: (f.GetReference()[0], int(f.GetReference()[1:]))):
    r = fp.GetReference()
    ref = fp.Reference()
    if r not in picks:
        pos, size, th, ang, lay = saved[r]
        ref.SetTextSize(size)
        ref.SetTextThickness(th)
        ref.SetTextAngleDegrees(ang)
        ref.SetPosition(pos)
        ref.SetLayer(pcbnew.F_Fab)
        ref.SetVisible(True)
        fab.append(r)
        rows.append((r, "DNP" if fp.IsDNP() else "", "-", "-", "-", "-", "F.Fab (no unambiguous silkscreen position)"))
        continue
    cost, x, y, w, h, ang, g, on_via, off_centre = picks[r]
    ref.SetLayer(pcbnew.F_SilkS)
    ref.SetVisible(True)
    ref.SetTextSize(pcbnew.VECTOR2I(F(w), F(h)))
    ref.SetTextThickness(F(0.15))
    ref.SetTextAngleDegrees(ang)
    ref.SetPosition(pcbnew.VECTOR2I(F(x), F(y)))
    g2 = ink(ref)
    assert abs(g2.bounds[0] - g.bounds[0]) < 0.01 and abs(g2.bounds[1] - g.bounds[1]) < 0.01, (r, g.bounds, g2.bounds)
    d_own = g2.distance(court[r])
    d_oth = min(court[k].distance(g2) for k in court if k != r)
    rows.append((r, "DNP" if fp.IsDNP() else "", "%.1f x %.1f" % (w, h), "%.0f" % ang, "%.2f" % d_own, "%.2f" % d_oth,
                 "; ".join(n for n, f in (("crosses a tented via", on_via), ("text centre nearer another part", off_centre)) if f)))
# fitted parts without a top-side position: a mirrored B.Silkscreen text of the reference over the part (read from the
# bottom, it sits on the part's own spot), clear of the bottom mask openings, drills, vias and other bottom silk
tnames = {fp.GetReference() for fp in targets}
for d in list(b.GetDrawings()):   # texts of an earlier run
    if d.GetClass() == "PCB_TEXT" and d.GetLayer() == pcbnew.B_SilkS and d.GetText() in tnames:
        b.Remove(d)
bobst = []
for fp in b.GetFootprints():
    for p in fp.Pads():
        if p.IsOnLayer(pcbnew.B_Mask):
            bobst.append(poly(p.GetEffectivePolygon(pcbnew.B_Cu, pcbnew.ERROR_OUTSIDE)).buffer(mexp + MASK_GAP))
        if p.GetDrillSize().x > 0:
            bobst.append(Point(M(p.GetPosition().x), M(p.GetPosition().y)).buffer(M(p.GetDrillSize().x) / 2 + 0.15))
for d in b.GetDrawings():
    if d.GetClass() == "PCB_TEXT" and d.GetLayer() == pcbnew.B_SilkS:
        bobst.append(ink(d).buffer(TEXT_GAP))
back = []
for r in [r for r in fab if r in fitted]:
    fp = b.FindFootprintByReference(r)
    c = court[r].centroid
    t = pcbnew.PCB_TEXT(b)
    t.SetText(r)
    t.SetLayer(pcbnew.B_SilkS)
    t.SetMirrored(True)
    t.SetTextThickness(F(0.15))
    best_b = None
    # phase B: both text widths and a +/-1.0 mm grid (R252 found no 0.8 mm wide position within +/-0.6 mm)
    for si, (w, h) in enumerate(SIZES):
        t.SetTextSize(pcbnew.VECTOR2I(F(w), F(h)))
        for ang in (0.0, 90.0):
            t.SetTextAngleDegrees(ang)
            for i in range(-10, 11):
                for j in range(-10, 11):
                    t.SetPosition(pcbnew.VECTOR2I(F(c.x + i * STEP), F(c.y + j * STEP)))
                    g = ink(t)
                    if not inner.contains(g) or any(g.intersects(o) for o in bobst + vias + back):
                        continue
                    if not g.intersects(court[r]):   # must lie over its own part
                        continue
                    cost = g.centroid.distance(c) + (0.3 if ang else 0.0) + 1.0 * si
                    if best_b is None or cost < best_b[0]:
                        best_b = (cost, ang, c.x + i * STEP, c.y + j * STEP, w, h)
    assert best_b is not None, (r, "no bottom-side position")
    t.SetTextSize(pcbnew.VECTOR2I(F(best_b[4]), F(best_b[5])))
    t.SetTextAngleDegrees(best_b[1])
    t.SetPosition(pcbnew.VECTOR2I(F(best_b[2]), F(best_b[3])))
    b.Add(t)
    back.append(ink(t).buffer(BACK_GAP))   # phase B: 0.40 mm let "C202" and "R254" read as one word
    rows[[x[0] for x in rows].index(r)] = (r, "", "%.1f x %.1f" % best_b[4:6], "%.0f" % best_b[1], "-", "-",
                                           "F.Fab; B.Silkscreen text over the part (bottom view)")
b.Save(PCB)
print("references on F.Silkscreen: %d of %d (fitted %d of %d); on F.Fab: %s; bottom-side texts: %s" % (
    len(picks), len(targets), sum(1 for r in fitted if r in picks), len(fitted), ", ".join(fab) or "none",
    ", ".join(r for r in fab if r in fitted) or "none"))
lines = ["| Reference | DNP | Text w x h (mm) | Angle (deg) | Gap to own courtyard (mm) | Gap to nearest other courtyard (mm) | Note |",
         "|---|---|---|---|---|---|---|"] + ["| " + " | ".join(r) + " |" for r in rows]
if len(sys.argv) > 1:
    with open(sys.argv[1], "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
else:
    print("\n".join(lines))
