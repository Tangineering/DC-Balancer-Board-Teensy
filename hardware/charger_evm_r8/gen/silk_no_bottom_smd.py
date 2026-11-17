"""No bottom-side silkscreen for top-side SMD parts (operator ruling 2026-11-17). The bottom of a board cannot be
seen while its top-side parts are assembled, so a B.Silkscreen label of a top-side SMD part does not help assembly.
Labels of through-hole locations stay on B.Silkscreen, because both sides of a through-hole location are visible
during assembly.

For each footprint on the top side whose pads have no drill (an SMD part):
- a reference field on B.Silkscreen moves to F.Fab, not mirrored and hidden (the footprint's F.Fab ${REFERENCE}
  text, which the fallbacks of gen/cr_silk_refs_r2.py and gen/cr_silk_fix_r3.py keep, carries the reference);
- any other footprint item on B.Silkscreen is removed;
- a board-level B.Silkscreen text whose whole text is the reference is removed (gen/eib_silk_refs_r2.py writes the
  EIB bottom references as board texts; its F.Fab reference field stays).
Board texts that name a through-hole location (for example the EIB E-pad labels "E8 TP49") and items of through-hole
footprints (for example the J1 "1" mark) are not changed. Copper, nets, footprint positions and every top-side item
are not changed. The script is idempotent; run it last in both in-place sequences (LAYOUT_DECISIONS.md section 3).
Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/silk_no_bottom_smd.py <board.kicad_pcb>"""
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

PCB = sys.argv[1]
b = pcbnew.LoadBoard(PCB)
smd = {}
for fp in b.GetFootprints():
    pads = list(fp.Pads())
    if not fp.IsFlipped() and pads and all(p.GetDrillSize().x == 0 for p in pads):
        smd[fp.GetReference()] = fp
moved, removed = [], []
for r, fp in smd.items():
    fab = [it for it in fp.GraphicalItems() if it.GetLayer() == pcbnew.F_Fab and it.GetClass() == "PCB_TEXT"
           and it.GetText() == "${REFERENCE}"]
    for f in fp.GetFields():
        if f.GetLayer() == pcbnew.B_SilkS:
            assert f.GetName() != "Reference" or fab, (r, "no F.Fab ${REFERENCE} text; the reference would be lost")
            f.SetLayer(pcbnew.F_Fab)
            f.SetMirrored(False)
            f.SetVisible(False)
            moved.append("%s %s" % (r, f.GetName()))
    for it in list(fp.GraphicalItems()):
        if it.GetLayer() == pcbnew.B_SilkS:
            fp.Remove(it)
            removed.append("%s footprint %s" % (r, it.GetClass()))
for d in list(b.GetDrawings()):
    if d.GetClass() == "PCB_TEXT" and d.GetLayer() == pcbnew.B_SilkS and d.GetText().strip() in smd:
        removed.append("board text '%s'" % d.GetText().strip())
        b.Remove(d)
b.Save(PCB)
print("%s: %d SMD footprints; reference fields moved to F.Fab (hidden): %s; removed: %s" % (
    PCB, len(smd), ", ".join(moved) or "none", ", ".join(removed) or "none"))
