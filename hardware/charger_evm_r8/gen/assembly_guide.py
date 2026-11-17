"""Assembly guide images for the parts whose silkscreen label does not help assembly (operator ruling 2026-11-17).

The top silkscreen keeps only reference labels that sit at their own part. A top-side SMD part goes into the
assembly guide instead when
- NONE: it has no visible F.Silkscreen reference (a reference on F.Fab, or a bottom-side label, which the ruling of
  2026-11-17 forbids for top-side SMD parts), or
- MARGINAL: its F.Silkscreen reference is away from its own pads: the ink is more than PAD_GAP_MAX from its own
  pads, or the ink is nearer the pads of another part than its own pads.
Exempt (labels stay on the silkscreen, never in the guide): wired connections and holes (references starting with
J, W, E, H, MH or TP) and parts whose pads are all plated through-holes. Their labels are used after assembly too.

The guide renders the top of the board (outline, holes, copper pads, silkscreen as printed) and highlights each
guide part: its courtyard in a bright outline and a tag with its reference and value on the part. Parts are split
over pages so that no two tags or highlights overlap. One part may sit on one page only.

Two steps, as gen/plot_route.py:
  1. pcbnew venv:            python gen/assembly_guide.py dump <cr|eib> [board.kicad_pcb]
     writes assembly_guide/<board>/guide.json and assembly_guide/<board>/README.md (the part lists).
  2. Python with matplotlib: python gen/assembly_guide.py plot <cr|eib>
     writes assembly_guide/<board>/<board>_guide_<n>.png and <board>_overview.png.
Optional, pcbnew venv, edits the board:  python gen/assembly_guide.py apply <board.kicad_pcb>
  moves every guide part's reference to F.Fab (hidden; the F.Fab ${REFERENCE} text stays) and removes the bottom
  texts of top-side SMD parts, so the printed silkscreen carries only the labels that sit at their parts.
Run from hardware/charger_evm_r8."""
import json
import math
import os
import sys

PAD_GAP_MAX = 1.0          # mm, ink to own pads; a larger gap is MARGINAL
EXEMPT_PREFIX = ("MH", "TP", "J", "W", "E", "H")
OUT = "assembly_guide"


def prefix(r):
    return "".join(ch for ch in r if ch.isalpha())[:2] if r[:2] in ("MH", "TP") else "".join(
        ch for ch in r if ch.isalpha())[:1]


def is_exempt_ref(r):
    return any(r.startswith(p) and (len(r) == len(p) or r[len(p)].isdigit()) for p in EXEMPT_PREFIX)


# ---------------------------------------------------------------------------------------------------------- dump
def dump(board_name, path):
    import pcbnew
    try:  # a wxWidgets debug assert opens a modal dialog that blocks an unattended run
        import wx
        wx.DisableAsserts()
    except Exception:
        pass
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    M = pcbnew.ToMM
    b = pcbnew.LoadBoard(path)

    def polys(sps):
        out = []
        for i in range(sps.OutlineCount()):
            o = sps.Outline(i)
            ext = [(M(o.CPoint(k).x), M(o.CPoint(k).y)) for k in range(o.PointCount())]
            holes = []
            for h in range(sps.HoleCount(i)):
                hh = sps.Hole(i, h)
                holes.append([(M(hh.CPoint(k).x), M(hh.CPoint(k).y)) for k in range(hh.PointCount())])
            if len(ext) >= 3:
                out.append(Polygon(ext, holes).buffer(0))
        return out

    def shp(item, layer):
        s = pcbnew.SHAPE_POLY_SET()
        if item.GetClass() in ("PCB_TEXT", "PCB_FIELD"):   # the strokes, not the text box
            item.TransformTextToPolySet(s, 0, pcbnew.FromMM(0.005), pcbnew.ERROR_INSIDE)
        else:
            item.TransformShapeToPolygon(s, layer, 0, pcbnew.FromMM(0.005), pcbnew.ERROR_INSIDE)
        return polys(s)

    def js(geoms):
        out = []
        for g in geoms:
            for p in (g.geoms if hasattr(g, "geoms") else [g]):
                if p.is_empty or p.geom_type != "Polygon":
                    continue
                out.append([[list(map(lambda v: round(v, 4), c)) for c in p.exterior.coords],
                            [[list(map(lambda v: round(v, 4), c)) for c in r.coords] for r in p.interiors]])
        return out

    o = pcbnew.SHAPE_POLY_SET()
    b.GetBoardPolygonOutlines(o)
    outline = polys(o)
    pads, silk, crt, info, refsilk = {}, [], {}, {}, {}
    for fp in b.GetFootprints():
        r = fp.GetReference()
        pp = []
        for p in fp.Pads():
            if p.IsOnLayer(pcbnew.F_Cu):
                pp += polys(p.GetEffectivePolygon(pcbnew.F_Cu, pcbnew.ERROR_INSIDE))
        pads[r] = pp
        c = fp.GetCourtyard(pcbnew.F_CrtYd)
        bb = fp.GetBoundingBox(False)
        crt[r] = polys(c) if c.OutlineCount() else [Polygon([(M(bb.GetLeft()), M(bb.GetTop())), (M(bb.GetRight()), M(
            bb.GetTop())), (M(bb.GetRight()), M(bb.GetBottom())), (M(bb.GetLeft()), M(bb.GetBottom()))])]
        for it in list(fp.GraphicalItems()) + list(fp.GetFields()):
            if it.GetLayer() == pcbnew.F_SilkS and (it.GetClass() != "PCB_FIELD" or it.IsVisible()):
                if it.GetClass() == "PCB_FIELD" and it.GetName() == "Reference":
                    refsilk[r] = shp(it, pcbnew.F_SilkS)    # drawn only when the part keeps its label
                else:
                    silk += shp(it, pcbnew.F_SilkS)
        plated = [p for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
        smd = [p for p in fp.Pads() if p.GetAttribute() in (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_CONN)]
        info[r] = dict(value=fp.GetValue(), flipped=fp.IsFlipped(), dnp=bool(fp.IsDNP()),
                       tht_only=bool(plated) and not smd, has_pads=bool(list(fp.Pads())))
    for d in b.GetDrawings():
        if d.GetLayer() == pcbnew.F_SilkS:
            silk += shp(d, pcbnew.F_SilkS)
    back_text = {d.GetText().strip() for d in b.GetDrawings()
                 if d.GetClass() == "PCB_TEXT" and d.GetLayer() == pcbnew.B_SilkS}

    padu = {r: unary_union(v) for r, v in pads.items() if v}
    rows = []
    for fp in sorted(b.GetFootprints(), key=lambda q: (prefix(q.GetReference()), int(
            "".join(ch for ch in q.GetReference() if ch.isdigit()) or 0), q.GetReference())):
        r = fp.GetReference()
        i = info[r]
        if is_exempt_ref(r) or i["tht_only"] or i["flipped"] or not i["has_pads"]:
            continue
        rf = fp.Reference()
        on_top = rf.GetLayer() == pcbnew.F_SilkS and rf.IsVisible()
        status, why, gap = "SILK", "", None
        if not on_top:
            where = ("B.Silkscreen" if rf.GetLayer() == pcbnew.B_SilkS or r in back_text else
                     b.GetLayerName(rf.GetLayer()) + ("" if rf.IsVisible() else ", hidden"))
            status, why = "NONE", "no top-side label (%s)" % where
        else:
            g = unary_union(shp(rf, pcbnew.F_SilkS))
            gap = g.distance(padu[r]) if r in padu else 99.0
            oth = min(((g.distance(u), k) for k, u in padu.items() if k != r and not info[k]["tht_only"]
                       and not k.startswith("MH")), default=(99.0, ""))
            if gap > PAD_GAP_MAX:
                status, why = "MARGINAL", "label %.2f mm from its pads (limit %.1f mm)" % (gap, PAD_GAP_MAX)
            elif oth[0] < gap:
                status, why = "MARGINAL", "label nearer the pads of %s (%.2f mm) than its own (%.2f mm)" % (
                    oth[1], oth[0], gap)
        rows.append(dict(ref=r, value=i["value"], dnp=i["dnp"], status=status, why=why,
                         gap=None if gap is None else round(gap, 3)))

    od = os.path.join(OUT, board_name)
    os.makedirs(od, exist_ok=True)
    guide = [x["ref"] for x in rows if x["status"] != "SILK"]
    data = dict(board=board_name, source=path, pad_gap_max=PAD_GAP_MAX, outline=js(outline), silk=js(silk),
                refsilk={r: js(v) for r, v in refsilk.items()},
                pads={r: js(v) for r, v in pads.items()}, courtyards={r: js(v) for r, v in crt.items()},
                rows=rows, guide=guide)
    with open(os.path.join(od, "guide.json"), "w", encoding="utf-8") as f:
        json.dump(data, f)
    n = {k: sum(1 for x in rows if x["status"] == k) for k in ("SILK", "MARGINAL", "NONE")}
    print("%s: %d top-side SMD parts; labelled on the silkscreen %d, guide %d (no top-side label %d, marginal %d)"
          % (board_name, len(rows), n["SILK"], len(guide), n["NONE"], n["MARGINAL"]))
    return data


# ---------------------------------------------------------------------------------------------------------- plot
def plot(board_name):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path

    od = os.path.join(OUT, board_name)
    with open(os.path.join(od, "guide.json"), encoding="utf-8") as f:
        D = json.load(f)
    rows = {x["ref"]: x for x in D["rows"]}

    def path_of(polys):
        verts, codes = [], []
        for ext, holes in polys:
            for ring in [ext] + holes:
                verts += ring
                codes += [Path.MOVETO] + [Path.LINETO] * (len(ring) - 2) + [Path.CLOSEPOLY]
        return Path(verts, codes) if verts else None

    def bounds(polys):
        xs = [p[0] for e, _ in polys for p in e]
        ys = [p[1] for e, _ in polys for p in e]
        return min(xs), min(ys), max(xs), max(ys)

    x0, y0, x1, y1 = bounds(D["outline"])
    TAG_H = 0.75                               # mm, tag text height on the board scale
    GAP = 0.9                                  # mm, courtyard to tag (the leader line spans it)
    PAGE_MAX = 14                              # parts per page

    def tag_text(r):
        v = rows[r]["value"]
        return r + ("\n" + v if v and v != r else "") + (" (DNP)" if rows[r]["dnp"] else "")

    def tag_size(r):
        lines = tag_text(r).split("\n")
        return max(len(s) for s in lines) * TAG_H * 0.74 + 0.6, len(lines) * TAG_H * 1.35 + 0.35

    def hit(a, c, m=0.2):
        return not (a[2] + m < c[0] or c[2] + m < a[0] or a[3] + m < c[1] or c[3] + m < a[1])

    def candidates(r):
        """tag boxes around the courtyard, right/left/above/below first, then the corners"""
        cx0, cy0, cx1, cy1 = bounds(D["courtyards"][r])
        cx, cy = (cx0 + cx1) / 2, (cy0 + cy1) / 2
        w, h = tag_size(r)
        out = []
        for ax_, ay_ in ((1, 0), (-1, 0), (0, -1), (0, 1), (1, -1), (-1, -1), (1, 1), (-1, 1)):
            tx = cx + ax_ * ((cx1 - cx0) / 2 + GAP + w / 2)
            ty = cy + ay_ * ((cy1 - cy0) / 2 + GAP + h / 2)
            tb = (tx - w / 2, ty - h / 2, tx + w / 2, ty + h / 2)
            if tb[0] >= x0 - 1.8 and tb[2] <= x1 + 1.8 and tb[1] >= y0 - 1.8 and tb[3] <= y1 + 1.8:
                out.append(tb)
        return out, (cx0, cy0, cx1, cy1)

    # pages: greedy; a part joins the first page where one of its tag positions overlaps no tag or highlighted
    # courtyard there, and its courtyard overlaps no tag there
    pages = []
    for r in D["guide"]:
        cands, cb = candidates(r)
        for pg in pages + [[]]:
            if len(pg) >= PAGE_MAX or any(hit(cb, t) for _, t, _ in pg):
                continue
            ok = [tb for tb in cands if not any(hit(tb, t) or hit(tb, c) for _, t, c in pg)
                  and not hit(tb, cb, 0.0)]
            if ok:
                pg.append((r, ok[0], cb))
                if pg not in pages:
                    pages.append(pg)
                break

    def draw(page, title, fname, highlight=True):
        W = x1 - x0 + 4
        H = y1 - y0 + 4
        fig, ax = plt.subplots(figsize=(W / 4.0, H / 4.0 + 0.9), dpi=150)
        ax.set_facecolor("#ffffff")
        ax.add_patch(PathPatch(path_of(D["outline"]), facecolor="#1f5c3a", edgecolor="#0b2615", lw=1.0))
        for r, pp in D["pads"].items():
            p = path_of(pp)
            if p is not None:
                on = highlight and r in [q for q, _, _ in page]
                ax.add_patch(PathPatch(p, facecolor="#ffd23f" if on else "#c9b27c", edgecolor="none"))
        # the silkscreen as printed after `apply`: the labels of guide parts are not drawn
        kept = [q for r, v in D["refsilk"].items() if r not in D["guide"] for q in v]
        sp = path_of(D["silk"] + kept)
        if sp is not None:
            ax.add_patch(PathPatch(sp, facecolor="#f2f2f2", edgecolor="none", alpha=0.85))
        mm_pt = fig.get_size_inches()[0] * 72 / W      # points per board mm
        for r, tb, cb in page:
            cp = path_of(D["courtyards"][r])
            ax.add_patch(PathPatch(cp, facecolor="#ff2bd6", edgecolor="#ff2bd6", lw=2.0, alpha=0.30))
            ax.add_patch(PathPatch(cp, facecolor="none", edgecolor="#ff2bd6", lw=2.0))
            tx, ty = (tb[0] + tb[2]) / 2, (tb[1] + tb[3]) / 2
            ccx, ccy = (cb[0] + cb[2]) / 2, (cb[1] + cb[3]) / 2
            # leader: from the tag edge to the courtyard edge, along the line between their centres
            ex = max(cb[0], min(tx, cb[2]))
            ey = max(cb[1], min(ty, cb[3]))
            sx = max(tb[0], min(ccx, tb[2]))
            sy = max(tb[1], min(ccy, tb[3]))
            ax.plot([sx, ex], [sy, ey], color="#ff2bd6", lw=1.6, solid_capstyle="round")
            ax.add_patch(plt.Rectangle((tb[0], tb[1]), tb[2] - tb[0], tb[3] - tb[1], facecolor="#ffffff",
                                       edgecolor="#ff2bd6", lw=1.2, alpha=0.95))
            ax.text(tx, ty, tag_text(r), ha="center", va="center", fontsize=TAG_H * mm_pt * 1.05,
                    fontweight="bold", color="#000000", linespacing=1.15)
        ax.set_xlim(x0 - 2, x1 + 2)
        ax.set_ylim(y1 + 2, y0 - 2)            # KiCad y grows downward; the image shows the board as in KiCad
        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_title(title, fontsize=11, loc="left")
        fig.tight_layout()
        fig.savefig(os.path.join(od, fname))
        plt.close(fig)

    for k in os.listdir(od):
        if k.endswith(".png"):
            os.remove(os.path.join(od, k))
    nm = board_name.upper()
    for n, pg in enumerate(pages, 1):
        refs = sorted(r for r, _, _ in pg)
        draw(pg, "%s top - assembly guide page %d of %d (%d parts; list in README.md)" % (nm, n, len(pages), len(refs)),
             "%s_guide_%d.png" % (board_name, n))
    draw([], "%s top - silkscreen as printed after the guide labels are removed" % nm, "%s_overview.png" % board_name, False)

    # README: which page shows which part
    page_of = {r: n for n, pg in enumerate(pages, 1) for r, _, _ in pg}
    L = ["# %s assembly guide" % nm, "",
         "Generated by `gen/assembly_guide.py` from `%s`. Do not edit by hand." % D["source"], "",
         "The top silkscreen labels only the parts whose label sits at their own pads. The pages below show the "
         "other top-side SMD parts: each is outlined in magenta on the rendered board with its reference and value. "
         "A part is in the guide when it has no top-side label (NONE) or when its label is more than %.1f mm from its "
         "own pads or nearer another part's pads (MARGINAL). Wired connections, holes and through-hole parts keep "
         "their silkscreen labels and are not in the guide." % D["pad_gap_max"], "",
         "| Page | Image | Parts |", "|---|---|---|"]
    for n, pg in enumerate(pages, 1):
        L.append("| %d | `%s_guide_%d.png` | %s |" % (n, board_name, n, ", ".join(sorted(r for r, _, _ in pg))))
    L += ["", "| Reference | Value | Status | Reason | Page |", "|---|---|---|---|---|"]
    for x in D["rows"]:
        L.append("| %s | %s | %s | %s | %s |" % (x["ref"], x["value"] + (" (DNP)" if x["dnp"] else ""), x["status"],
                                                x["why"] or "label at its pads", page_of.get(x["ref"], "-")))
    with open(os.path.join(od, "README.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")
    print("%s: %d guide parts on %d pages -> %s" % (board_name, len(D["guide"]), len(pages), od))


# ---------------------------------------------------------------------------------------------------------- apply
def apply(path):
    import pcbnew
    try:
        import wx
        wx.DisableAsserts()
    except Exception:
        pass
    name = os.path.splitext(os.path.basename(path))[0]
    D = dump(name, path)
    b = pcbnew.LoadBoard(path)
    guide = set(D["guide"])
    moved, removed = [], []
    for fp in b.GetFootprints():
        r = fp.GetReference()
        if r not in guide:
            continue
        fab = [it for it in fp.GraphicalItems() if it.GetLayer() == pcbnew.F_Fab and it.GetClass() == "PCB_TEXT"
               and it.GetText() == "${REFERENCE}"]
        rf = fp.Reference()
        if rf.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and (rf.IsVisible() or rf.GetLayer() == pcbnew.B_SilkS):
            assert fab or rf.GetLayer() == pcbnew.F_Fab, (r, "no F.Fab ${REFERENCE} text")
            rf.SetLayer(pcbnew.F_Fab)
            rf.SetMirrored(False)
            rf.SetVisible(False)
            moved.append(r)
    for d in list(b.GetDrawings()):
        if d.GetClass() == "PCB_TEXT" and d.GetLayer() == pcbnew.B_SilkS and d.GetText().strip() in guide:
            removed.append(d.GetText().strip())
            b.Remove(d)
    b.Save(path)
    print("%s: references moved to F.Fab: %s; bottom texts removed: %s" % (
        path, ", ".join(sorted(moved)) or "none", ", ".join(sorted(removed)) or "none"))


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "dump":
        bn = sys.argv[2]
        dump(bn, sys.argv[3] if len(sys.argv) > 3 else os.path.join(bn, bn + ".kicad_pcb"))
    elif mode == "plot":
        plot(sys.argv[2])
    elif mode == "apply":
        apply(sys.argv[2])
    else:
        sys.exit(__doc__)
