"""Corridor router step L7a: write routed nets into a board file.

Usage (pcbnew venv):
  python apply_routes.py <in.kicad_pcb> <routes.json> <out.kicad_pcb>

For every net in routes.json the unlocked tracks and vias of that net are removed and replaced by the routed
copper; other nets are untouched. Zones are refilled. The input board is not modified unless <out> names it."""
import json
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

b = pcbnew.LoadBoard(sys.argv[1])
Rj = json.load(open(sys.argv[2]))
P = Rj["params"]
ALL = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.In3_Cu, pcbnew.In4_Cu, pcbnew.B_Cu]
LID = {b.GetLayerName(l): l for l in ALL}
names = {r["net"] for r in Rj["results"]}
doomed = [t for t in b.GetTracks() if t.GetNetname() in names and not t.IsLocked()]
for t in doomed:
    b.Remove(t)     # the list keeps the proxies alive until the save
nt = nv = 0
for r in Rj["results"]:
    net = b.FindNet(r["net"])
    if net is None:
        raise SystemExit("net %s is not on the board" % r["net"])
    for (ln, xa, ya, xb, yb), w in zip(r["tracks"], r["widths"]):
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(pcbnew.VECTOR2I_MM(xa, ya))
        t.SetEnd(pcbnew.VECTOR2I_MM(xb, yb))
        t.SetWidth(pcbnew.FromMM(w))
        t.SetLayer(LID[ln])
        t.SetNet(net)
        b.Add(t)
        nt += 1
    for (vx, vy), vd in zip(r["vias"], r["via_d"]):
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(pcbnew.VECTOR2I_MM(vx, vy))
        v.SetWidth(pcbnew.FromMM(vd))
        v.SetDrill(pcbnew.FromMM(P["drill"]))
        v.SetNet(net)
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        b.Add(v)
        nv += 1
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
b.Save(sys.argv[3])
print("nets %d: added tracks %d vias %d, removed %d -> %s" % (len(names), nt, nv, len(doomed), sys.argv[3]))
