"""Remove every track and via except those of the kept nets (the power-pour nets); refill; save.
Usage: python strip_routes.py <in.kicad_pcb> <out.kicad_pcb> <comma list of kept nets>"""
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

b = pcbnew.LoadBoard(sys.argv[1])
keep = set(sys.argv[3].split(","))
doomed = [t for t in b.GetTracks() if t.GetNetname() not in keep]
for t in doomed:
    b.Remove(t)
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
b.Save(sys.argv[2])
print("removed", len(doomed), "kept", len(b.GetTracks()))
