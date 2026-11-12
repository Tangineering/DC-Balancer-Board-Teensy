"""Write routed nets into a copy of a board, with its project files, and refill the zones.

Usage (pcbnew venv):
  python apply_routes.py <in.kicad_pcb> <routes.json> <outdir>

The output board is <outdir>/<same file name as the input>. The project files that share the input's base name
(.kicad_pro, .kicad_sch, .kicad_dru), the library tables and the local libraries are copied beside it, because
kicad-cli needs them for the design rules and the schematic parity test. <outdir> must not be the input's folder:
the input board is never modified.

For every net in routes.json the unlocked tracks and vias of that net are removed and replaced by the routed
copper; other nets are untouched. Zones are refilled in a second pass on the reloaded board (a fill in the same
session as the edit leaves the old fill in place). The script then reads the saved board back and checks the
track and via counts."""
import glob
import json
import os
import shutil
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

src, routes, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
if outdir.lower().endswith(".kicad_pcb"):
    raise SystemExit("give an output FOLDER; the routed board keeps the input's file name")
srcdir = os.path.dirname(os.path.abspath(src))
if os.path.abspath(outdir) == srcdir:
    raise SystemExit("the output folder must differ from the input board's folder")
os.makedirs(outdir, exist_ok=True)
stem = os.path.splitext(os.path.basename(src))[0]
for ext in (".kicad_pro", ".kicad_sch", ".kicad_dru"):
    f = os.path.join(srcdir, stem + ext)
    if os.path.exists(f):
        shutil.copy2(f, outdir)
for f in ("fp-lib-table", "sym-lib-table"):
    if os.path.exists(os.path.join(srcdir, f)):
        shutil.copy2(os.path.join(srcdir, f), outdir)
for f in glob.glob(os.path.join(srcdir, "*.kicad_sym")):
    shutil.copy2(f, outdir)
for d in glob.glob(os.path.join(srcdir, "*.pretty")):
    dst = os.path.join(outdir, os.path.basename(d))
    if not os.path.exists(dst):
        shutil.copytree(d, dst)
out = os.path.join(outdir, stem + ".kicad_pcb")

b = pcbnew.LoadBoard(src)
if b is None:
    raise SystemExit("cannot load %s (write paths as C:/..., not /c/...)" % src)
Rj = json.load(open(routes))
P = Rj["params"]
ALL = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.In3_Cu, pcbnew.In4_Cu, pcbnew.B_Cu]
LID = {b.GetLayerName(l): l for l in ALL}
names = {r["net"] for r in Rj["results"]}
before = len(b.GetTracks())
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
b.Save(out)
expect = before - len(doomed) + nt + nv

b2 = pcbnew.LoadBoard(out)                   # second pass: the fill must run on the reloaded board
b2.BuildConnectivity()
pcbnew.ZONE_FILLER(b2).Fill(b2.Zones())
b2.Save(out)
b3 = pcbnew.LoadBoard(out)                   # read back
got = len(b3.GetTracks())
if got != expect:
    raise SystemExit("read-back mismatch: %d tracks and vias on the saved board, %d expected" % (got, expect))
print("nets %d: added tracks %d vias %d, removed %d; zones refilled; read back ok -> %s" % (
    len(names), nt, nv, len(doomed), out))
