"""Plot CR courtyards (top and bottom) against the placement regions and keep-outs -> <projdir>/placement_<side>.png.
Step 1 (pcbnew venv): python plot_place.py dump <board> <projdir> ; step 2 (python with matplotlib): python plot_place.py plot <projdir>"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.argv[1] == "dump":
    import pcbnew, pcbbuild as pb, importlib
    try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
        import wx
        wx.DisableAsserts()
    except Exception:
        pass
    
    L = importlib.import_module("layout_" + sys.argv[2])
    b = pcbnew.LoadBoard(os.path.join(sys.argv[3], sys.argv[2] + ".kicad_pcb"))
    fr = pb.Frame(L.YOFF)
    out = {"F": [], "B": [], "outline": L.OUTLINE, "keep": {}}
    for fp in b.GetFootprints():
        for side, lay in (("F", pcbnew.F_CrtYd), ("B", pcbnew.B_CrtYd)):
            g = pb._crt_polys(fp, fr, lay)
            if g is None or g.is_empty:
                continue
            geoms = [g] if g.geom_type == "Polygon" else list(g.geoms)
            for gg in geoms:
                out[side].append([fp.GetReference(), list(gg.exterior.coords)])
    for name, poly, layers, opts in L.rule_areas():
        geoms = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
        out["keep"][name] = [[list(g.exterior.coords), [list(h.coords) for h in g.interiors]] for g in geoms]
    regs = {k: getattr(L, k) for k in ("INTERIOR", "TABY_TOP", "DIV_STRIP", "BAND", "ANALOG_STRICT", "JTAP_REG")
            if hasattr(L, k)}   # TABY_TOP and BAND exist on the r7 outline only (D-52)
    out["regions"] = {k: [list(g.exterior.coords) for g in ([v] if v.geom_type == "Polygon" else list(v.geoms))]
                      for k, v in regs.items()}
    json.dump(out, open(os.path.join(sys.argv[3], "placement_dump.json"), "w"))
else:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MP
    d = json.load(open(os.path.join(sys.argv[2], "placement_dump.json")))
    for side in ("F", "B"):
        fig, ax = plt.subplots(figsize=(14, 12.5))
        ol = d["outline"] + [d["outline"][0]]
        ax.plot([p[0] for p in ol], [p[1] for p in ol], "k-", lw=1.5)
        for name, gs in d["keep"].items():
            if (side == "B") == (name in ("MB_bottom_clearance", "FT1_keepout", "FT2_keepout", "L4_no_tracks")):
                for ext, holes in gs:
                    ax.add_patch(MP(ext, closed=True, fc=(1, 0.6, 0.6, 0.45), ec="r", lw=0.4))
                    for h in holes:
                        ax.add_patch(MP(h, closed=True, fc="w", ec="r", lw=0.4))
        if side == "F":
            for k, gs in d["regions"].items():
                for ext in gs:
                    ax.add_patch(MP(ext, closed=True, fc="none", ec="g", lw=0.8, ls="--"))
        for ref, pts in d[side]:
            ax.add_patch(MP(pts, closed=True, fc=(0.6, 0.7, 1, 0.5), ec="b", lw=0.5))
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            ax.text(sum(xs) / len(xs), sum(ys) / len(ys), ref, fontsize=5, ha="center", va="center")
        # view from the outline (D-39 plug-on outline y 7-94; the fixed r7 window y 33-77 cut it off) plus the
        # PARK spot at x 75 so a part the packer could not place stays visible
        oxs = [p[0] for p in d["outline"]]; oys = [p[1] for p in d["outline"]]
        ax.set_xlim(min(oxs) - 3, max(max(oxs), 75.0) + 3); ax.set_ylim(min(oys) - 3, max(oys) + 3)
        ax.set_aspect("equal"); ax.grid(True, lw=0.2)
        ax.set_title("CR %s courtyards (Eagle board coordinates, top view)" % ("top" if side == "F" else "bottom"))
        fig.savefig(os.path.join(sys.argv[2], "placement_%s.png" % side), dpi=110, bbox_inches="tight")
