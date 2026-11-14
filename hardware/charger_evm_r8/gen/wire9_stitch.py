"""D-66 (CR): restore the D-20 GND stitching inside the J101 wire-pad grid. A 0.6 / 0.3 mm /GND via is added at each
centre of four wire pads (pitch 2.54 mm: 1.80 mm to each pad centre, 0.75 mm pad-edge gap) where DRC stays clean.
Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/wire9_stitch.py x,y [x,y ...]   (board mm)"""
import sys

import pcbnew
try:
    import wx
    wx.DisableAsserts()
except Exception:
    pass

PCB = "cr/cr.kicad_pcb"
b = pcbnew.LoadBoard(PCB)
gnd = b.FindNet("/GND")
for arg in sys.argv[1:]:
    x, y = map(float, arg.split(","))
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
    v.SetWidth(pcbnew.FromMM(0.6)); v.SetDrill(pcbnew.FromMM(0.3)); v.SetNet(gnd)
    b.Add(v)
    print("GND via at (%.3f, %.3f)" % (x, y))
b.BuildConnectivity()
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
b.Save(PCB)
