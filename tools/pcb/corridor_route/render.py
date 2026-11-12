"""Draw the board model, the plan (regions and corridors) and, optionally, the routed copper: one PNG per routing
layer. Needs matplotlib and numpy only (any Python that has them; not the pcbnew venv).

Usage:
  python render.py <model.json> <outdir> [--plan plan.json] [--routes routes.json] [--window x0 y0 x1 y1]
                   [--labels] [--nets /A,/B] [--tag NAME]

Coordinates on the axes are plan coordinates: the design frame (y up) when the plan or the model states a
y_flip_offset, otherwise the KiCad frame drawn with y increasing downward. --labels writes the part references.
--nets highlights the pads of the named nets. With --routes, routed copper is coloured by plan group and each
open net is drawn as red dashed lines between its pads."""
import argparse
import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Patch, PathPatch, Polygon as MP
from matplotlib.path import Path

ap = argparse.ArgumentParser()
ap.add_argument("model")
ap.add_argument("outdir")
ap.add_argument("--plan")
ap.add_argument("--routes")
ap.add_argument("--window", nargs=4, type=float)
ap.add_argument("--labels", action="store_true")
ap.add_argument("--nets", default="")
ap.add_argument("--tag", default="")
A = ap.parse_args()
D = json.load(open(A.model))
P = json.load(open(A.plan)) if A.plan else {}
RT = json.load(open(A.routes)) if A.routes else None
yoff = P.get("frame", {}).get("y_flip_offset", D.get("y_flip_offset"))
hl = {n for n in A.nets.split(",") if n}
os.makedirs(A.outdir, exist_ok=True)
group_of = {n: g.get("name", "?") for g in P.get("groups", []) for n in g["nets"]}


def d(p):
    return (p[0], yoff - p[1]) if yoff is not None else (p[0], p[1])


def ring_patch(poly, holes, **kw):
    """polygon with holes as one patch"""
    verts, codes = [], []
    for ring in [poly] + list(holes or []):
        pts = [d(q) for q in ring]
        verts += pts + [pts[0]]
        codes += [Path.MOVETO] + [Path.LINETO] * (len(pts) - 1) + [Path.CLOSEPOLY]
    return PathPatch(Path(verts, codes), **kw)


def inwin(x, y):
    return not A.window or (A.window[0] <= x <= A.window[2] and A.window[1] <= y <= A.window[3])


COL = ["#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00", "#a65628", "#f781bf", "#17becf", "#bcbd22", "#666666"]
GCOL = ["#0033cc", "#008000", "#9400d3", "#cc6600", "#008b8b", "#b8860b", "#c71585", "#2f4f4f"]
gnames = sorted({group_of.get(r["net"], "(default)") for r in RT["results"]}) if RT else []
gcol = {g: GCOL[i % len(GCOL)] for i, g in enumerate(gnames)}
pad_xy = {}
for it in D["items"]:
    if it["kind"] == "pad" and it["net"]:
        xs = [q[0] for q in it["poly"]]
        ys = [q[1] for q in it["poly"]]
        pad_xy.setdefault(it["net"], {})[(it["ref"], it["num"])] = (sum(xs) / len(xs), sum(ys) / len(ys))

for li, layer in enumerate(D["layers"]):
    fig, ax = plt.subplots(figsize=(15, 13))
    for (xa, ya, xb, yb) in D["outline"]:
        a, b = d((xa, ya)), d((xb, yb))
        ax.plot([a[0], b[0]], [a[1], b[1]], "k-", lw=1.2)
    for it in D["items"]:
        if layer not in it["layers"]:
            continue
        k = it["kind"]
        if k == "zone":
            ax.add_patch(MP([d(q) for q in it["poly"]], closed=True, fc="#f2c0c0" if not it.get("soft") else "#eeeeee",
                            ec="none", alpha=0.6, zorder=1))
        elif k == "keepout":
            ax.add_patch(ring_patch(it["poly"], it.get("holes"), fc="none", ec="#aa0000", hatch="///", lw=0.3,
                                    zorder=2))
        elif k == "pad":
            sel = it["net"] in hl
            ax.add_patch(MP([d(q) for q in it["poly"]], closed=True, fc="#ffd400" if sel else "#9a9a9a",
                            ec="k", lw=0.2, zorder=4))
        elif k == "hole":
            c = d(it["circ"][:2])
            ax.add_patch(Circle(c, it["circ"][2], fc="#555555", ec="none", zorder=5))
        elif k == "via":
            c = d(it["circ"][:2])
            ax.add_patch(Circle(c, it["circ"][2], fc="#333333", ec="none", zorder=5))
        elif k == "track":
            xa, ya, xb, yb, w = it["seg"]
            a, b = d((xa, ya)), d((xb, yb))
            ax.plot([a[0], b[0]], [a[1], b[1]], "-", color="#7a3b00", lw=max(w * 7, 0.6), solid_capstyle="round",
                    zorder=3)
    for r in P.get("regions", []):
        pts = r.get("polygon") or [[r["box"][0], r["box"][1]], [r["box"][2], r["box"][1]], [r["box"][2], r["box"][3]],
                                   [r["box"][0], r["box"][3]]]
        ax.add_patch(MP(pts, closed=True, fc="none", ec="#444444", ls=":", lw=1.2, zorder=6))
        cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        if inwin(cx, cy):
            ax.text(cx, cy, r["name"], color="#444444", fontsize=11, weight="bold", ha="center", alpha=0.6, zorder=9)
    nlab = 0
    for ci, c in enumerate(P.get("corridors", [])):
        layers = c.get("layers") or [c["layer"]]
        if layer not in layers:
            continue
        col = COL[ci % len(COL)]
        if "path" in c:
            pts = c["path"]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            left, right = [], []
            for i, p in enumerate(pts):
                q0 = pts[max(i - 1, 0)]
                q1 = pts[min(i + 1, len(pts) - 1)]
                dx, dy = q1[0] - q0[0], q1[1] - q0[1]
                n = math.hypot(dx, dy) or 1.0
                ux, uy = -dy / n * c["width"] / 2, dx / n * c["width"] / 2
                left.append((p[0] + ux, p[1] + uy))
                right.append((p[0] - ux, p[1] - uy))
            ax.add_patch(MP(left + right[::-1], closed=True, fc=col, ec=col, alpha=0.25, lw=1.0, zorder=6))
            ax.plot(xs, ys, "--", color=col, lw=0.8, zorder=7)
            m = len(pts) // 2                       # label at the middle vertex, shifted so labels do not stack
            lx, ly = (pts[m - 1][0] + pts[m][0]) / 2 if m else pts[0][0], (pts[m - 1][1] + pts[m][1]) / 2 if m else pts[0][1]
        else:
            ax.add_patch(MP(c["polygon"], closed=True, fc=col, ec=col, alpha=0.15, lw=1.0, zorder=6))
            lx, ly = c["polygon"][0][0], c["polygon"][0][1]
        if inwin(lx, ly):
            ax.text(lx, ly + 0.5 * (nlab % 3), c["id"] + (" (reserved)" if c.get("reserve") else ""), color=col,
                    fontsize=8, weight="bold", zorder=11, bbox=dict(fc="w", ec=col, pad=1, alpha=0.85))
            nlab += 1
    if RT:
        for r in RT["results"]:
            col = gcol[group_of.get(r["net"], "(default)")]
            for (ln, xa, ya, xb, yb), w in zip(r["tracks"], r["widths"]):
                if ln == layer:
                    a, b = d((xa, ya)), d((xb, yb))
                    ax.plot([a[0], b[0]], [a[1], b[1]], "-", color=col, lw=max(w * 7, 0.6),
                            solid_capstyle="round", zorder=8)
            for (vx, vy), vd in zip(r["vias"], r["via_d"]):
                ax.add_patch(Circle(d((vx, vy)), vd / 2, fc=col, ec="k", lw=0.3, zorder=8))
        done = {r["net"]: set(r.get("open_pads", [])) for r in RT["results"]}
        for net in RT.get("open", []):
            pts = [d(v) for k, v in pad_xy.get(net, {}).items()
                   if net not in done or ("%s.%s" % k) in done[net] or True]
            for a, b in zip(pts[:-1], pts[1:]):
                ax.plot([a[0], b[0]], [a[1], b[1]], "--", color="#ff0000", lw=0.7, zorder=10)
    if A.labels:
        side = "F" if layer == D["layers"][0] else ("B" if layer == D["layers"][-1] else None)
        for p in D.get("parts", []):
            if side and p["side"] == side:
                c = d((p["x"], p["y"]))
                if inwin(*c):
                    ax.text(c[0], c[1], p["ref"], fontsize=5, ha="center", va="center", color="#000080", zorder=10,
                            clip_on=True)
    leg = [Patch(fc="#9a9a9a", ec="k", label="pad"), Patch(fc="#f2c0c0", label="pour (hard)"),
           Patch(fc="#eeeeee", ec="#bbbbbb", label="pour (soft fill)"),
           Patch(fc="none", ec="#aa0000", hatch="///", label="keep-out"),
           Line2D([0], [0], color="#7a3b00", lw=2, label="existing track")]
    if P.get("corridors"):
        leg.append(Patch(fc=COL[0], alpha=0.25, label="corridor (colour per id)"))
    for g in gnames:
        leg.append(Line2D([0], [0], color=gcol[g], lw=2, label="routed: " + g))
    if RT and RT.get("open"):
        leg.append(Line2D([0], [0], color="#ff0000", lw=1, ls="--", label="open net"))
    ax.legend(handles=leg, loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=7)
    ax.set_aspect("equal")
    if A.window:
        ax.set_xlim(A.window[0], A.window[2])
        ax.set_ylim(A.window[1], A.window[3])
    elif yoff is None:
        ax.invert_yaxis()
    ax.grid(True, lw=0.25)
    ax.minorticks_on()
    ax.set_title("%s%s  (plan coordinates%s)" % (layer, (" - " + A.tag) if A.tag else "",
                                                ", design frame y up" if yoff is not None else ", KiCad frame"))
    fn = os.path.join(A.outdir, "%s%s.png" % (layer.replace(".", "_"), ("_" + A.tag) if A.tag else ""))
    fig.savefig(fn, dpi=110, bbox_inches="tight")
    plt.close(fig)
    print("wrote", fn)
