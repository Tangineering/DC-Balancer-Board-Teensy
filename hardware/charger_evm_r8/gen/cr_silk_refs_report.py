"""Write cr/silk_refs.md (D-59 reference list) from the placement on cr/cr.kicad_pcb. Read-only on the board.

For each visible reference field the table gives the layer, the text height and angle, the gap from the ink box
(pcbnew GetEffectiveTextShape) to the own courtyard polygon, and in the note: the references whose ink overlaps another
part's courtyard polygon (hidden once that part is fitted), the bottom-side references and the references kept on
F.Fab. The scripts that last placed each reference are named in the file header (update_2026-11-14 notes).

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/cr_silk_refs_report.py
"""
import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

M = pcbnew.ToMM
PCB, OUT = "cr/cr.kicad_pcb", "cr/silk_refs.md"
b = pcbnew.LoadBoard(PCB)


def ink(t):
    bb = t.GetEffectiveTextShape(False).BBox()
    return box(M(bb.GetX()), M(bb.GetY()), M(bb.GetRight()), M(bb.GetBottom()))


crt = {}
for fp in b.GetFootprints():
    c = fp.GetCourtyard(pcbnew.F_CrtYd)
    ps = []
    for i in range(c.OutlineCount()):
        o = c.Outline(i)
        ps.append(Polygon([(M(o.CPoint(k).x), M(o.CPoint(k).y)) for k in range(o.PointCount())]).buffer(0))
    crt[fp.GetReference()] = unary_union(ps) if ps else None
rows = []
for fp in b.GetFootprints():
    f, r = fp.Reference(), fp.GetReference()
    if not f.IsVisible():
        continue   # MH1-MH4 (D-60)
    lay = f.GetLayer()
    if lay == pcbnew.F_Fab:
        rows.append((r, "F.Fab", "-", "-", "-", "no clear silkscreen position"))
        continue
    g = ink(f)
    gap = "%.2f" % g.distance(crt[r]) if crt[r] is not None else "-"
    if lay == pcbnew.B_SilkS:
        note = "mirrored, over the part (no clear top-side position); F.Fab ${REFERENCE} on the assembly drawing"
        rows.append((r, "B.Silkscreen", "%.1f" % M(f.GetTextHeight()), "%.0f" % f.GetTextAngleDegrees(), gap, note))
        continue
    over = sorted(q for q, c in crt.items() if c is not None and q != r and c.intersection(g).area > 1e-6)
    note = ("over the courtyard of " + ", ".join(over)) if over else ""
    if r == "J101":
        note = "header of the J101 map ('J101 top view')"
    rows.append((r, "F.Silkscreen", "%.1f" % M(f.GetTextHeight()), "%.0f" % f.GetTextAngleDegrees(), gap, note))


def key(row):
    r = row[0]
    return (''.join(ch for ch in r if ch.isalpha()), int(''.join(ch for ch in r if ch.isdigit()) or 0), r)


n = {k: sum(1 for x in rows if x[1] == k) for k in ("F.Silkscreen", "B.Silkscreen", "F.Fab")}
with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
    fh.write("# CR reference designators\n\n")
    fh.write("This list gives the placement of every visible reference field on `cr/cr.kicad_pcb` (D-59). It is "
             "written by\n`gen/cr_silk_refs_report.py` from the board. The placement comes from `gen/silk_refs.py` "
             "(D-58), then\n`gen/cr_silk_refs_r2.py`, `gen/cr_wire_labels.py`, `gen/cr_lead_labels.py`, "
             "`gen/cr_silk_fix_r3.py`\n(update 2026-11-14) and `gen/cr_silk_fix_r4.py` (the W1 reference, phase C "
             "2026-11-15, D-85). %d references are on F.Silkscreen, %d on B.Silkscreen "
             "and %d on F.Fab.\n\n" % (n["F.Silkscreen"], n["B.Silkscreen"], n["F.Fab"]))
    fh.write("The gap is measured from the text ink box to the own courtyard polygon. The note \"over the courtyard "
             "of\" names\nanother part whose courtyard polygon the ink overlaps. The text stroke is 0.15 mm "
             "throughout.\n\n")
    fh.write("| Reference | Layer | Text height (mm) | Angle (deg) | Gap to own courtyard (mm) | Note |\n")
    fh.write("|---|---|---|---|---|---|\n")
    for row in sorted(rows, key=key):
        fh.write("| " + " | ".join(row) + " |\n")
print("%s: %d rows (%s)" % (OUT, len(rows), n))
for row in rows:
    if row[5].startswith("over"):
        print("  ", row)
