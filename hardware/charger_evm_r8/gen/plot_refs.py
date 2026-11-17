"""Reference placement plot of one board side: courtyards, pads and every reference designator, no values.

Usage (pcbnew venv, from hardware/charger_evm_r8): python gen/plot_refs.py <board.kicad_pcb> <out dir> [top|bottom]
The board is loaded in memory only: value fields are hidden and every reference is shown on the fab layer for the
plot, and the board file is never saved. Writes <out dir>/<board>_refs_<side>.svg (board area only).
"""
import os
import sys

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

pcb, out = sys.argv[1], sys.argv[2]
side = sys.argv[3] if len(sys.argv) > 3 else "top"
b = pcbnew.LoadBoard(pcb)
fab = pcbnew.F_Fab if side == "top" else pcbnew.B_Fab
for fp in b.GetFootprints():
    fp.Value().SetVisible(False)
    for it in fp.GraphicalItems():
        if it.GetClass() == "PCB_TEXT" and it.GetText() == "${VALUE}":
            it.SetVisible(False)
    ref = fp.Reference()
    on_side = (fp.IsFlipped() == (side == "bottom"))
    # one reference per part, on the fab layer of its side, centred on the part, readable size
    for it in fp.GraphicalItems():
        if it.GetClass() == "PCB_TEXT" and it.GetText() == "${REFERENCE}":
            it.SetVisible(False)
    ref.SetLayer(fab if on_side else (pcbnew.B_Fab if side == "top" else pcbnew.F_Fab))
    ref.SetVisible(on_side and not fp.GetReference().startswith("#"))
    ref.SetPosition(fp.GetPosition())
    ref.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(0.7), pcbnew.FromMM(0.7)))
    ref.SetTextThickness(pcbnew.FromMM(0.12))
    ref.SetMirrored(side == "bottom")
pc = pcbnew.PLOT_CONTROLLER(b)
po = pc.GetPlotOptions()
os.makedirs(out, exist_ok=True)
po.SetOutputDirectory(out)
po.SetPlotFrameRef(False)
po.SetAutoScale(False)
po.SetScale(1)
po.SetMirror(side == "bottom")
po.SetUseAuxOrigin(False)
po.SetPlotValue(False)
po.SetPlotReference(True)
po.SetSketchPadsOnFabLayers(True)
try:
    po.SetPlotInvisibleText(False)
except Exception:
    pass
crt = pcbnew.F_CrtYd if side == "top" else pcbnew.B_CrtYd
seq = pcbnew.LSEQ()
for L in (fab, crt, pcbnew.Edge_Cuts):
    seq.push_back(L)
name = os.path.splitext(os.path.basename(pcb))[0] + "_refs_" + side
pc.OpenPlotfile(name, pcbnew.PLOT_FORMAT_SVG, "references " + side)
pc.PlotLayers(seq)
pc.ClosePlot()
# crop the page to the board outline (+2 mm); the SVG viewBox is in page millimetres
import glob
import re
svg = max(glob.glob(os.path.join(out, "*%s.svg" % name)), key=os.path.getmtime)
bb = b.GetBoardEdgesBoundingBox()
x0, y0 = pcbnew.ToMM(bb.GetX()) - 2, pcbnew.ToMM(bb.GetY()) - 2
w, h = pcbnew.ToMM(bb.GetWidth()) + 4, pcbnew.ToMM(bb.GetHeight()) + 4
t = open(svg, encoding="utf-8").read()
m = re.search(r'width="([\d.]+)mm" height="([\d.]+)mm" viewBox="[^"]*"', t)
if side == "bottom":
    x0 = float(m.group(1)) - (x0 + w)
t = t.replace(m.group(0), 'width="%.3fmm" height="%.3fmm" viewBox="%.4f %.4f %.4f %.4f"' % (w, h, x0, y0, w, h), 1)
dst = os.path.join(out, name + ".svg")
open(dst, "w", encoding="utf-8").write(t)
if os.path.abspath(svg) != os.path.abspath(dst):
    os.remove(svg)
print(dst)
