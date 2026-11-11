"""Corridor router: draw the board model, the corridor plan and (optionally) the routed copper, one PNG per
routing layer. Needs matplotlib and numpy only (any Python that has them; not the pcbnew venv).

Usage:
  python render.py <model.json> <outdir> [--plan plan.json] [--routes routes.json] [--window x0 y0 x1 y1]
                   [--labels] [--nets /A,/B]

Coordinates on the axes are plan coordinates: the design frame (y up) when the plan or the model states a
y_flip_offset, otherwise the KiCad frame drawn with y increasing downward. --labels writes the part references.
--nets highlights the pads of the named nets."""
import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon as MP

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


def d(p):
    return (p[0], yoff - p[1]) if yoff is not None else (p[0], p[1])


COL = ["#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00", "#a65628", "#f781bf", "#17becf", "#bcbd22", "#666666"]
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
            ax.add_patch(MP([d(q) for q in it["poly"]], closed=True, fc="none", ec="#aa0000", hatch="///", lw=0.3,
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
    for ci, c in enumerate(P.get("corridors", [])):
        layers = c.get("layers") or [c["layer"]]
        if layer not in layers:
            continue
        col = COL[ci % len(COL)]
        if "path" in c:
            xs = [p[0] for p in c["path"]]
            ys = [p[1] for p in c["path"]]
            # linewidth in data units: draw as a polygon band
            import math
            pts = c["path"]
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
            ax.text(xs[0], ys[0], c["id"], color=col, fontsize=9, weight="bold", zorder=9,
                    bbox=dict(fc="w", ec=col, pad=1, alpha=0.8))
        else:
            ax.add_patch(MP(c["polygon"], closed=True, fc=col, ec=col, alpha=0.2, lw=1.0, zorder=6))
            ax.text(c["polygon"][0][0], c["polygon"][0][1], c["id"], color=col, fontsize=9, weight="bold", zorder=9,
                    bbox=dict(fc="w", ec=col, pad=1, alpha=0.8))
    if RT:
        for r in RT["results"]:
            for (ln, xa, ya, xb, yb), w in zip(r["tracks"], r["widths"]):
                if ln == layer:
                    a, b = d((xa, ya)), d((xb, yb))
                    ax.plot([a[0], b[0]], [a[1], b[1]], "-", color="#0033cc", lw=max(w * 7, 0.6),
                            solid_capstyle="round", zorder=8)
            for (vx, vy), vd in zip(r["vias"], r["via_d"]):
                ax.add_patch(Circle(d((vx, vy)), vd / 2, fc="#001a66", ec="none", zorder=8))
    if A.labels:
        side = "F" if layer == D["layers"][0] else ("B" if layer == D["layers"][-1] else None)
        for p in D.get("parts", []):
            if side and p["side"] == side:
                c = d((p["x"], p["y"]))
                ax.text(c[0], c[1], p["ref"], fontsize=5, ha="center", va="center", color="#000080", zorder=10)
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
