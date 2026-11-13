"""Reference-designator placement on the top silkscreen of a routed board (D-58; D-12a reversed keeps every
reference on the silkscreen). Each reference field is moved to the nearest position where it is clear of every
solder-mask opening, every other silkscreen item and the silk-to-edge band. Text height 1.0 mm is tried first,
then the 0.8 mm house minimum (cr.kicad_dru rule fab_silk_text: 0.8 / 0.15 mm). A position over another part's
courtyard is accepted only when no free position exists within the search radius. A reference with no clear
position at all moves to F.Fab and is listed. Copper, nets and footprint positions are not changed.
Usage (pcbnew venv): python silk_refs.py <board.kicad_pcb> [report.md]"""
import math
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass
from shapely.geometry import LineString, box
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree

mm = pcbnew.ToMM
MASK_GAP = 0.05       # silk to mask-opening margin (DRC min_silk_clearance is 0)
SILK_GAP = 0.10       # text to other silkscreen
EDGE_BAND = 0.25      # silk to board edge (silk_fix.py uses the same band)
RADIUS = 3.0          # search radius from the footprint courtyard (mm)
STEP = 0.15
SIZES = [(1.0, 0.15), (0.8, 0.15)]
ANGLES = [0.0, 90.0]

b = pcbnew.LoadBoard(sys.argv[1])
ds = b.GetDesignSettings()
mexp = mm(ds.m_SolderMaskExpansion)


def bb(item):
    r = item.GetBoundingBox()
    return box(mm(r.GetLeft()), mm(r.GetTop()), mm(r.GetRight()), mm(r.GetBottom()))


segs = [LineString([(mm(d.GetStart().x), mm(d.GetStart().y)), (mm(d.GetEnd().x), mm(d.GetEnd().y))])
        for d in b.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts and d.GetShape() == pcbnew.SHAPE_T_SEGMENT]
board_in = unary_union(list(polygonize(unary_union(segs)))).buffer(-EDGE_BAND, join_style=2)

# static obstacles: top mask openings (pads on F.Cu / F.Mask and every hole) and footprint silk graphics
mask = []
for fp in b.GetFootprints():
    for p in fp.Pads():
        if p.IsOnLayer(pcbnew.F_Mask) or p.IsOnLayer(pcbnew.F_Cu) or \
                p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
            mask.append(bb(p).buffer(mexp + MASK_GAP, join_style=2))
for t in b.GetTracks():   # an untented via is a mask opening; tented vias are not
    if t.Type() == pcbnew.PCB_VIA_T and not t.IsTented(pcbnew.F_Cu):
        mask.append(bb(t).buffer(MASK_GAP, join_style=2))
silk = []
for fp in b.GetFootprints():
    for it in fp.GraphicalItems():
        if it.GetLayer() == pcbnew.F_SilkS:
            silk.append(bb(it).buffer(SILK_GAP, join_style=2))
static = mask + silk
tree = STRtree(static)
court = {}
for fp in b.GetFootprints():
    c = fp.GetCourtyard(pcbnew.F_CrtYd)
    if c.OutlineCount():
        r = c.BBox()
        court[fp.GetReference()] = box(mm(r.GetLeft()), mm(r.GetTop()), mm(r.GetRight()), mm(r.GetBottom()))
    else:
        court[fp.GetReference()] = bb(fp)


def text_box(ref, size, thick, ang):
    """Box of the reference field at its anchor (0, 0) for the given size and angle, as offsets."""
    ref.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size), pcbnew.FromMM(size)))
    ref.SetTextThickness(pcbnew.FromMM(thick))
    ref.SetTextAngleDegrees(ang)
    p = ref.GetPosition()
    g = bb(ref)
    return (g.bounds[0] - mm(p.x), g.bounds[1] - mm(p.y), g.bounds[2] - mm(p.x), g.bounds[3] - mm(p.y))


def candidates(fp, ref):
    body = court[fp.GetReference()]
    cx, cy = body.centroid.x, body.centroid.y
    others = [g for r, g in court.items() if r != fp.GetReference()]
    otree = STRtree(others)
    out = []
    for si, (size, thick) in enumerate(SIZES):
        for ang in ANGLES:
            x0, y0, x1, y1 = text_box(ref, size, thick, ang)
            n = int(round((RADIUS + max(body.bounds[2] - body.bounds[0], body.bounds[3] - body.bounds[1])) / STEP))
            for i in range(-n, n + 1):
                for j in range(-n, n + 1):
                    x, y = cx + i * STEP, cy + j * STEP
                    g = box(x + x0, y + y0, x + x1, y + y1)
                    d = g.distance(body)
                    if d > RADIUS or not board_in.contains(g):
                        continue
                    over = any(g.intersects(others[k]) for k in otree.query(g))
                    cost = d + 0.8 * si + (0.2 if ang else 0.0) + (5.0 if over else 0.0)
                    out.append((cost, x, y, size, thick, ang, g, over))
    out.sort(key=lambda c: c[0])
    return out


refs = [(fp, fp.Reference()) for fp in b.GetFootprints()
        if fp.Reference().GetLayer() == pcbnew.F_SilkS and fp.Reference().IsVisible()]   # MH1-MH4 hidden (D-60)
saved = {fp.GetReference(): (ref.GetPosition(), ref.GetTextSize(), ref.GetTextThickness(), ref.GetTextAngleDegrees())
         for fp, ref in refs}
cand = {}
for fp, ref in refs:
    cand[fp.GetReference()] = [c for c in candidates(fp, ref)
                               if not any(c[6].intersects(static[k]) for k in tree.query(c[6]))]
# most-constrained first
order = sorted(refs, key=lambda fr: len(cand[fr[0].GetReference()]))
placed = []
rows = []
fab = []
# references already on F.Fab from an earlier run stay there and are listed in the report (D-61)
kept_fab = sorted(fp.GetReference() for fp in b.GetFootprints()
                  if fp.Reference().GetLayer() == pcbnew.F_Fab and fp.Reference().IsVisible())
for r_ in kept_fab:
    rows.append((r_, "-", "-", "-", "F.Fab (kept from an earlier run)"))
for fp, ref in order:
    r = fp.GetReference()
    pos0, size0, th0, ang0 = saved[r]
    pick = None
    for c in cand[r]:
        g = c[6]
        if all(not g.intersects(p.buffer(SILK_GAP, join_style=2)) for p in placed):
            pick = c
            break
    if pick is None:
        ref.SetTextSize(size0)
        ref.SetTextThickness(th0)
        ref.SetTextAngleDegrees(ang0)
        ref.SetPosition(pos0)
        ref.SetLayer(pcbnew.F_Fab)
        fab.append(r)
        rows.append((r, "-", "-", "-", "F.Fab (no clear position)"))
        continue
    cost, x, y, size, thick, ang, g, over = pick
    ref.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size), pcbnew.FromMM(size)))
    ref.SetTextThickness(pcbnew.FromMM(thick))
    ref.SetTextAngleDegrees(ang)
    ref.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
    placed.append(g)
    rows.append((r, f"{size:.1f}", f"{ang:.0f}", f"{g.distance(court[r]):.2f}",
                 "over another courtyard" if over else ""))

b.Save(sys.argv[1])
n_over = sum(1 for row in rows if row[4] == "over another courtyard")
print(f"references placed: {len(rows) - len(fab) - len(kept_fab)} on F.Silkscreen ({n_over} over another courtyard), "
      f"{len(fab)} moved to F.Fab: {', '.join(sorted(fab)) or 'none'}; {len(kept_fab)} already on F.Fab")
if len(sys.argv) > 2:
    def key(r):
        return (''.join(ch for ch in r[0] if ch.isalpha()), int(''.join(ch for ch in r[0] if ch.isdigit()) or 0))
    with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as f:
        f.write("| Reference | Text height (mm) | Angle (deg) | Gap to own courtyard (mm) | Note |\n")
        f.write("|---|---|---|---|---|\n")
        for row in sorted(rows, key=key):
            f.write("| " + " | ".join(row) + " |\n")
