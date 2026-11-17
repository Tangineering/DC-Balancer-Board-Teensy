"""Delete the vias that a DRC report lists as dangling (connected on one layer or not at all); refill; save.
Usage: python finish_cleanup.py <board.kicad_pcb> <drc.rpt>"""
import re
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

b = pcbnew.LoadBoard(sys.argv[1])
txt = open(sys.argv[2], encoding="utf-8").read()
pts = [(float(x), float(y)) for x, y in re.findall(r"\[via_dangling\][^\n]*\n[^\n]*\n\s+@\(([-\d.]+) mm, ([-\d.]+) mm\)", txt)]
n = 0
for t in list(b.GetTracks()):
    if t.GetClass() == "PCB_VIA":
        x, y = pcbnew.ToMM(t.GetPosition().x), pcbnew.ToMM(t.GetPosition().y)
        if any(abs(x - px) < 0.002 and abs(y - py) < 0.002 for px, py in pts):
            b.Remove(t)
            n += 1
if n:
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.Save(sys.argv[1])
print("dangling vias removed", n)
