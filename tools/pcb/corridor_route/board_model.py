"""Corridor router step L0: dump a placed board to a routing model and a text summary.

Usage (pcbnew venv):
  python board_model.py <board.kicad_pcb> <outdir> --layers F.Cu,In2.Cu,B.Cu [--y-flip-offset 100]

Writes <outdir>/model.json (copper, holes, keep-outs, pours, outline; KiCad frame, mm, y down) and
<outdir>/model_summary.md (parts and nets, in the design frame when --y-flip-offset is given). Reads the board
only; it never saves it."""
import argparse
import json
import os

import pcbnew
try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
    import wx
    wx.DisableAsserts()
except Exception:
    pass

ap = argparse.ArgumentParser()
ap.add_argument("board")
ap.add_argument("outdir")
ap.add_argument("--layers", required=True, help="routing layers, comma separated, e.g. F.Cu,In2.Cu,B.Cu")
ap.add_argument("--y-flip-offset", type=float, default=None)
A = ap.parse_args()
layers = A.layers.split(",")
os.makedirs(A.outdir, exist_ok=True)
b = pcbnew.LoadBoard(A.board)
ALL = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.In3_Cu, pcbnew.In4_Cu, pcbnew.B_Cu]
LID = {b.GetLayerName(l): l for l in ALL}
mm = pcbnew.ToMM
YO = A.y_flip_offset


def dsn(x, y):
    return (round(x, 3), round(YO - y, 3)) if YO is not None else (round(x, 3), round(y, 3))


def poly_pts(sps, i):
    o = sps.Outline(i)
    return [(mm(o.CPoint(k).x), mm(o.CPoint(k).y)) for k in range(o.PointCount())]


items, parts = [], []
for fp in b.GetFootprints():
    pos = fp.GetPosition()
    bb = fp.GetBoundingBox(False)
    parts.append(dict(ref=fp.GetReference(), value=fp.GetValue(), side="B" if fp.IsFlipped() else "F",
                      x=mm(pos.x), y=mm(pos.y), w=mm(bb.GetWidth()), h=mm(bb.GetHeight()), dnp=fp.IsDNP(),
                      pads=len(list(fp.Pads()))))
    for p in fp.Pads():
        ls = [ln for ln in layers if p.IsOnLayer(LID[ln]) and p.FlashLayer(LID[ln])]
        for ln in ls:
            sps = p.GetEffectivePolygon(LID[ln], pcbnew.ERROR_INSIDE)
            for i in range(sps.OutlineCount()):
                items.append(dict(kind="pad", net=p.GetNetname(), layers=[ln], poly=poly_pts(sps, i),
                                  ref=fp.GetReference(), num=p.GetNumber()))
        if p.GetDrillSizeX() > 0:
            # the hole blocks every routing layer; 0.127 mm is added so that the router's copper clearance also
            # covers a 0.254 mm plated-hole-to-inner-copper fab rule
            c = p.GetPosition()
            items.append(dict(kind="hole", net=p.GetNetname(), layers=layers,
                              circ=(mm(c.x), mm(c.y), mm(p.GetDrillSizeX()) / 2 + 0.127)))
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA":
        c = t.GetPosition()
        items.append(dict(kind="via", net=t.GetNetname(), layers=layers, locked=t.IsLocked(),
                          circ=(mm(c.x), mm(c.y), mm(t.GetWidth(pcbnew.F_Cu)) / 2)))
    else:
        ln = b.GetLayerName(t.GetLayer())
        if ln in layers:
            s, e = t.GetStart(), t.GetEnd()
            items.append(dict(kind="track", net=t.GetNetname(), layers=[ln], locked=t.IsLocked(),
                              seg=(mm(s.x), mm(s.y), mm(e.x), mm(e.y), mm(t.GetWidth()))))
for z in b.Zones():
    if z.GetIsRuleArea():
        for lay in z.GetLayerSet().Seq():
            ln = b.GetLayerName(lay)
            if ln in layers and (z.GetDoNotAllowTracks() or z.GetDoNotAllowVias()):
                ol = z.Outline()
                for i in range(ol.OutlineCount()):
                    holes = [ol.Hole(i, j) for j in range(ol.HoleCount(i))]
                    items.append(dict(kind="keepout", net="", layers=[ln], poly=poly_pts(ol, i), name=z.GetZoneName(),
                                      holes=[[(mm(h.CPoint(k).x), mm(h.CPoint(k).y)) for k in range(h.PointCount())]
                                             for h in holes]))
        continue
    soft = z.GetAssignedPriority() <= 1          # low-priority (GND fill) pours yield to new tracks on refill
    for lay in z.GetLayerSet().Seq():
        ln = b.GetLayerName(lay)
        if ln not in layers:
            continue
        fl = z.GetFilledPolysList(lay)
        for i in range(fl.OutlineCount()):
            items.append(dict(kind="zone", net=z.GetNetname(), layers=[ln], poly=poly_pts(fl, i), soft=soft,
                              name=z.GetZoneName()))
bb = b.GetBoardEdgesBoundingBox()
outline = [(mm(d.GetStart().x), mm(d.GetStart().y), mm(d.GetEnd().x), mm(d.GetEnd().y)) for d in b.GetDrawings()
           if d.GetLayer() == pcbnew.Edge_Cuts and d.GetShape() == pcbnew.SHAPE_T_SEGMENT]
json.dump(dict(items=items, parts=parts, outline=outline, layers=layers, y_flip_offset=YO,
               bbox=(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))),
          open(os.path.join(A.outdir, "model.json"), "w"))

# ---------------------------------------------------------------- summary
nets = {}
for it in items:
    if it["kind"] == "pad" and it["net"] and not it["net"].startswith("unconnected"):
        xs = [q[0] for q in it["poly"]]
        ys = [q[1] for q in it["poly"]]
        nets.setdefault(it["net"], {})[(it["ref"], it["num"])] = (sum(xs) / len(xs), sum(ys) / len(ys), it["layers"][0])
zone_nets = {it["net"] for it in items if it["kind"] == "zone"}
L = ["# Board model summary", "",
     "Frame: %s. Routing layers: %s." % ("design frame, y up (y = %.3f - KiCad y)" % YO if YO is not None
                                         else "KiCad frame, y down", ", ".join(layers)),
     "Outline bounding box: (%.2f, %.2f) to (%.2f, %.2f)." % (dsn(mm(bb.GetLeft()), mm(bb.GetBottom())) +
                                                              dsn(mm(bb.GetRight()), mm(bb.GetTop()))),
     "", "## Nets", "",
     "A net with a pour (zone) is a kept net; the router does not route it.", "",
     "| Net | Pads | Pour | Span x | Span y | Pads (ref.pin @ x, y side) |", "|---|---|---|---|---|---|"]
for net in sorted(nets, key=lambda n: (-len(nets[n]), n)):
    ps = nets[net]
    pts = [dsn(v[0], v[1]) for v in ps.values()]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    side = {k: next((pp["side"] for pp in parts if pp["ref"] == k[0]), "?") for k in ps}
    desc = "; ".join("%s.%s @ %.1f, %.1f %s" % (k[0], k[1], p[0], p[1], side[k]) for k, p in zip(ps, pts))
    if len(desc) > 600:
        desc = desc[:600] + " ..."
    L.append("| %s | %d | %s | %.1f-%.1f | %.1f-%.1f | %s |" % (net, len(ps), "yes" if net in zone_nets else "",
                                                             min(xs), max(xs), min(ys), max(ys), desc))
L += ["", "## Parts", "", "| Ref | Value | Side | x | y | Pads | DNP |", "|---|---|---|---|---|---|---|"]
for p in sorted(parts, key=lambda p: p["ref"]):
    x, y = dsn(p["x"], p["y"])
    L.append("| %s | %s | %s | %.2f | %.2f | %d | %s |" % (p["ref"], p["value"], p["side"], x, y, p["pads"],
                                                         "DNP" if p["dnp"] else ""))
open(os.path.join(A.outdir, "model_summary.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
print("model: %d items, %d parts, %d nets -> %s" % (len(items), len(parts), len(nets), A.outdir))
