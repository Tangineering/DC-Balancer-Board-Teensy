"""D-66 cleanup: a via of a wire-pad net that sits on its own J101/J201 wire pad (closer than pad radius + via
radius) is deleted, and the tracks that met it on any layer are re-ended at the pad centre (the plated pad flashes on
every layer a track reaches). Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/wire9_padvias.py <cr|eib>"""
import math
import sys

import pcbnew
try:
    import wx
    wx.DisableAsserts()
except Exception:
    pass

B = sys.argv[1]
REF = {"cr": "J101", "eib": "J201"}[B]
PCB = "%s/%s.kicad_pcb" % (B, B)
mm = pcbnew.ToMM
b = pcbnew.LoadBoard(PCB)
KEEP = []
pads = [(p.GetNetCode(), p.GetPosition(), mm(p.GetSize().x) / 2) for p in b.FindFootprintByReference(REF).Pads()]
plan = []
for v in b.GetTracks():
    if v.GetClass() != "PCB_VIA":
        continue
    for net, pc, pr in pads:
        d = math.hypot(mm(v.GetPosition().x - pc.x), mm(v.GetPosition().y - pc.y))
        if v.GetNetCode() == net and d < pr + mm(v.GetWidth(pcbnew.F_Cu)) / 2:
            vp = (v.GetPosition().x, v.GetPosition().y)
            ends = []
            for t in b.GetTracks():
                if t.GetClass() == "PCB_TRACK" and t.GetNetCode() == net:
                    for which, p in (("s", t.GetStart()), ("e", t.GetEnd())):
                        if math.hypot(p.x - vp[0], p.y - vp[1]) <= v.GetWidth(pcbnew.F_Cu) / 2:   # any end on the via copper
                            ends.append((t, which))
            plan.append((v, pc, ends))
            break
for v, pc, ends in plan:
    for t, which in ends:
        (t.SetStart if which == "s" else t.SetEnd)(pcbnew.VECTOR2I(pc.x, pc.y))
    print("via %s (%.3f, %.3f) deleted; %d track end(s) moved to the pad centre (%.3f, %.3f)" % (
        v.GetNetname(), mm(v.GetPosition().x), mm(v.GetPosition().y), len(ends), mm(pc.x), mm(pc.y)))
    b.Remove(v); KEEP.append(v)
b.BuildConnectivity()
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
b.Save(PCB)
