"""Finishing router, step 3 (pcbnew venv): add the routed tracks and vias to the board, refill the zones, save.
Usage: python finish_apply.py <board.kicad_pcb> <routes.json>"""
import json
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

b = pcbnew.LoadBoard(sys.argv[1])
R = json.load(open(sys.argv[2]))
P = R["params"]
LID = {b.GetLayerName(l): l for l in [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]}
nt = nv = nd = 0
ripped = {r["net"] for r in R["results"] if r.get("replace")}
if ripped:   # ripped-up nets: their old tracks and vias are replaced by the rerouted copper
    doomed = [t for t in b.GetTracks() if t.GetNetname() in ripped]
    for t in doomed:
        b.Remove(t)   # doomed keeps the proxies alive until the save
    nd = len(doomed)
for r in R["results"]:
    net = b.FindNet(r["net"])
    widths = r.get("widths") or [P["track"]] * len(r["tracks"])
    vds = r.get("via_d") or [P["via"]] * len(r["vias"])
    for (ln, xa, ya, xb, yb), w in zip(r["tracks"], widths):
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(pcbnew.VECTOR2I_MM(xa, ya))
        t.SetEnd(pcbnew.VECTOR2I_MM(xb, yb))
        t.SetWidth(pcbnew.FromMM(w))
        t.SetLayer(LID[ln])
        t.SetNet(net)
        b.Add(t)
        nt += 1
    for (vx, vy), vd in zip(r["vias"], vds):
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(pcbnew.VECTOR2I_MM(vx, vy))
        v.SetWidth(pcbnew.FromMM(vd))
        v.SetDrill(pcbnew.FromMM(P["drill"] if abs(vd - P["via"]) < 1e-6 else vd / 2))
        v.SetNet(net)
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        b.Add(v)
        nv += 1
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
b.Save(sys.argv[1])
print("added tracks", nt, "vias", nv, "removed (ripped)", nd)
