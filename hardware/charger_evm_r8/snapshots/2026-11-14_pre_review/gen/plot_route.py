"""Plot copper (pours, tracks, vias, pads) per layer group -> <projdir>/route_<name>.png.
Step 1 (pcbnew venv): python plot_route.py dump <board> <projdir>; step 2: python plot_route.py plot <projdir> [x0 y0 x1 y1]"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.argv[1] == "dump":
    import pcbnew, importlib
    try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
        import wx
        wx.DisableAsserts()
    except Exception:
        pass
    
    L = importlib.import_module("layout_" + sys.argv[2])
    b = pcbnew.LoadBoard(os.path.join(sys.argv[3], sys.argv[2] + ".kicad_pcb"))
    Y = L.YOFF
    e = lambda v: (pcbnew.ToMM(v.x), Y - pcbnew.ToMM(v.y))
    out = {"outline": L.OUTLINE, "tracks": [], "vias": [], "pads": [], "zones": []}
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            out["vias"].append([e(t.GetPosition()), pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)), t.GetNetname()])
        else:
            out["tracks"].append([b.GetLayerName(t.GetLayer()), e(t.GetStart()), e(t.GetEnd()), pcbnew.ToMM(t.GetWidth()), t.GetNetname()])
    for z in b.Zones():
        if z.GetIsRuleArea():
            continue
        for lay in z.GetLayerSet().Seq():
            fp = z.GetFilledPolysList(lay)
            for i in range(fp.OutlineCount()):
                o = fp.Outline(i)
                out["zones"].append([b.GetLayerName(lay), z.GetNetname(), [e(o.CPoint(k)) for k in range(o.PointCount())]])
    for fp in b.GetFootprints():
        for p in fp.Pads():
            for lay, nm in ((pcbnew.F_Cu, "F.Cu"), (pcbnew.B_Cu, "B.Cu")):
                if p.IsOnLayer(lay):
                    poly = p.GetEffectivePolygon(lay, pcbnew.ERROR_INSIDE)
                    for i in range(poly.OutlineCount()):
                        o = poly.Outline(i)
                        out["pads"].append([nm, p.GetNetname(), [e(o.CPoint(k)) for k in range(o.PointCount())], fp.GetReference()])
    json.dump(out, open(os.path.join(sys.argv[3], "route_dump.json"), "w"))
else:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MP, Circle
    d = json.load(open(os.path.join(sys.argv[2], "route_dump.json")))
    lim = [float(v) for v in sys.argv[3:7]] if len(sys.argv) >= 7 else None
    col = {"F.Cu": "#c83434", "In1.Cu": "#c8c834", "In2.Cu": "#34a0c8", "B.Cu": "#3434c8"}
    for name, layers in (("top", ["F.Cu"]), ("inner", ["In1.Cu", "In2.Cu"]), ("bottom", ["B.Cu"])):
        if name == "inner" and not any(t[0] in layers for t in d["tracks"]) and not any(z[0] in layers for z in d["zones"]):
            continue
        fig, ax = plt.subplots(figsize=(14, 12))
        ol = d["outline"] + [d["outline"][0]]
        ax.plot([p[0] for p in ol], [p[1] for p in ol], "k-", lw=1)
        for lay, net, pts in d["zones"]:
            if lay in layers:
                ax.add_patch(MP(pts, closed=True, fc=col[lay], alpha=0.18 if "GND" in net else 0.35, ec="none"))
        for lay, net, pts, ref in d["pads"]:
            if lay in layers:
                ax.add_patch(MP(pts, closed=True, fc="#888888", ec="k", lw=0.2, alpha=0.8))
        for lay, a, bb, w, net in d["tracks"]:
            if lay in layers:
                ax.plot([a[0], bb[0]], [a[1], bb[1]], "-", color=col[lay], lw=max(w * 6, 0.5), solid_capstyle="round")
        for c, w, net in d["vias"]:
            ax.add_patch(Circle(c, w / 2, fc="#444444", ec="none"))
        if lim:
            ax.set_xlim(lim[0], lim[2]); ax.set_ylim(lim[1], lim[3])
        ax.set_aspect("equal"); ax.grid(True, lw=0.2)
        ax.set_title("%s copper (%s)" % (name, ", ".join(layers)))
        fig.savefig(os.path.join(sys.argv[2], "route_%s.png" % name), dpi=100, bbox_inches="tight")
