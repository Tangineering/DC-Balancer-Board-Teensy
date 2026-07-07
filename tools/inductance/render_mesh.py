#!/usr/bin/env python3
"""
render_mesh.py -- PNG visualizations of the meshes and path coordinates a config
resolves to. Reuses gerber_inductance.build_model so the images show EXACTLY what
the solver uses.

Outputs (per config, into --outdir):
  <base>_mesh_forward.png : forward coarse mesh (voxel grid), mm axes, port-A /
                            closure nodes, dashed span + distance.
  <base>_mesh_return.png  : return coarse mesh, port-B / closure nodes.
                            (forward & return share the SAME axes -> comparable.)
  <base>_overlay.png      : forward (orange) + return (blue) translucent overlay.
  <base>_region.png       : forward net (orange) over surrounding copper with the
                            actual terminal_a / terminal_b / closure coordinates
                            (style of the hand-made vout_*_region.png).

Every image draws a thin dashed line between the port and the closure with the
loop-span distance labelled; annotations are offset radially so they don't overlap.

Usage:
    python render_mesh.py <config.json> [--outdir out] [--margin 3.0]
"""

from __future__ import annotations

import argparse
import math
import os
import sys

import numpy as np

import model_cache
from gerber_inductance import load_config, load_layer


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _extent(cm):
    return (cm.x0, cm.x0 + cm.nx * cm.pitch, cm.y0, cm.y0 + cm.ny * cm.pitch)


def _nearest_node(cm, x, y):
    """Nearest filled-cell centre (the node FastHenry actually snaps the port to)."""
    js, is_ = np.nonzero(cm.mask)
    if len(js) == 0:
        return (x, y)
    xs = cm.x0 + (is_ + 0.5) * cm.pitch
    ys = cm.y0 + (js + 0.5) * cm.pitch
    k = int(np.argmin(np.hypot(xs - x, ys - y)))
    return float(xs[k]), float(ys[k])


def _mark(ax, x, y, style, label, off):
    ax.plot(x, y, style, ms=11, mec="k", mew=0.6, zorder=6)
    ha = "left" if off[0] >= 0 else "right"
    va = "bottom" if off[1] >= 0 else "top"
    ax.annotate(f"{label}\n({x:.2f},{y:.2f})", (x, y), textcoords="offset points",
                xytext=off, fontsize=7, ha=ha, va=va, zorder=7,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="0.5", alpha=0.85))


def _radial_offsets(pts, dist=20):
    """Pixel offsets pointing away from the group centroid, so labels don't collide."""
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    out = []
    for (x, y) in pts:
        vx, vy = x - cx, y - cy
        n = math.hypot(vx, vy)
        if n < 1e-9:
            vx, vy, n = 0.7, 0.7, 1.0
        out.append((dist * vx / n, dist * vy / n))
    return out


def _draw_span(ax, p, c):
    """Thin dashed line p->c with the distance labelled perpendicular to it."""
    ax.plot([p[0], c[0]], [p[1], c[1]], ls="--", lw=1.0, color="0.2", alpha=0.9, zorder=5)
    d = math.hypot(c[0] - p[0], c[1] - p[1])
    mx, my = (p[0] + c[0]) / 2.0, (p[1] + c[1]) / 2.0
    dx, dy = c[0] - p[0], c[1] - p[1]
    L = math.hypot(dx, dy) or 1.0
    ox, oy = -dy / L, dx / L                     # perpendicular unit
    ax.annotate(f"d = {d:.2f} mm", (mx, my), textcoords="offset points",
                xytext=(18 * ox, 18 * oy), fontsize=7, ha="center", va="center", zorder=8,
                bbox=dict(boxstyle="round,pad=0.2", fc="lightyellow", ec="0.4", alpha=0.95))


def _annotate(ax, port, closures, extra=None, snap_cm=None):
    """Draw the port/closure/extra markers + dashed spans, with non-overlapping labels.
    port: (x,y,style,label); closures: [(x,y),...]; extra: [(x,y,style,label),...]."""
    def snap(x, y):
        return _nearest_node(snap_cm, x, y) if snap_cm is not None else (x, y)

    px, py = snap(port[0], port[1])
    markers = [(px, py, port[2], port[3])]
    clos = []
    for i, c in enumerate(closures):
        cx, cy = snap(c[0], c[1])
        clos.append((cx, cy))
        markers.append((cx, cy, "gs", "closure" if len(closures) == 1 else f"closure{i}"))
    for e in (extra or []):
        ex, ey = snap(e[0], e[1])
        markers.append((ex, ey, e[2], e[3]))

    for (cx, cy) in clos:                        # dashed span port -> each closure
        _draw_span(ax, (px, py), (cx, cy))

    offs = _radial_offsets([(m[0], m[1]) for m in markers], dist=20)
    for m, off in zip(markers, offs):
        _mark(ax, m[0], m[1], m[2], m[3], off)


def _union_bounds(bbs, margin):
    bbs = [b for b in bbs if b]
    xmin = min(b[0] for b in bbs); ymin = min(b[1] for b in bbs)
    xmax = max(b[2] for b in bbs); ymax = max(b[3] for b in bbs)
    return (xmin - margin, xmax + margin, ymin - margin, ymax + margin)


def _apply_bounds(ax, bounds):
    ax.set_xlim(bounds[0], bounds[1]); ax.set_ylim(bounds[2], bounds[3])
    ax.set_xlabel("x [mm]"); ax.set_ylabel("y [mm]")
    ax.grid(True, which="both", alpha=0.35, linewidth=0.5)
    ax.set_aspect("equal")


def render_mesh(cm, title, port, closures, path, bounds):
    """One conductor's coarse mesh + snapped port/closure nodes + dashed span."""
    plt = _plt()
    fig, ax = plt.subplots(figsize=(8, 7))
    ax.imshow(cm.mask, origin="lower", extent=_extent(cm), cmap="Blues",
              interpolation="nearest", vmin=0, vmax=1.4)
    _annotate(ax, port, closures, snap_cm=cm)
    _apply_bounds(ax, bounds)                     # shared axes across fwd/ret
    ax.set_title(title)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


def _port_and_extra(cfg):
    """Return (port, extra): merge terminal_a/b into one 'port A/B' if coincident."""
    ta = cfg["terminal_a"]; tb = cfg["terminal_b"]
    if math.hypot(ta[0] - tb[0], ta[1] - tb[1]) < 0.2:
        return (ta[0], ta[1], "b^", "port A/B"), []
    return (ta[0], ta[1], "b^", "terminal_a (+)"), [(tb[0], tb[1], "cv", "terminal_b (-)")]


def render_overlay(fwd, ret, cfg, title, path, bounds):
    """Forward (orange) and return (blue) meshes overlaid translucently."""
    plt = _plt()
    from matplotlib.patches import Patch
    fig, ax = plt.subplots(figsize=(8, 7))
    ov_r = np.zeros((*ret.mask.shape, 4)); ov_r[ret.mask] = [0.1, 0.45, 1.0, 0.5]
    ax.imshow(ov_r, origin="lower", extent=_extent(ret), interpolation="nearest")
    ov_f = np.zeros((*fwd.mask.shape, 4)); ov_f[fwd.mask] = [1.0, 0.4, 0.0, 0.5]
    ax.imshow(ov_f, origin="lower", extent=_extent(fwd), interpolation="nearest")

    port, extra = _port_and_extra(cfg)
    closures = [(p[0], p[1]) for p in cfg.get("closure", {}).get("points", [])]
    _annotate(ax, port, closures, extra=extra, snap_cm=None)
    ax.legend(handles=[Patch(color=[1.0, 0.4, 0.0, 0.6], label="forward (VOUT)"),
                       Patch(color=[0.1, 0.45, 1.0, 0.6], label="return (GND)")],
              loc="lower right", fontsize=8)
    _apply_bounds(ax, bounds)
    ax.set_title(title)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


def render_region(cfg, model, path, margin=3.0):
    """Forward net (orange) over its surrounding copper + actual path coordinates."""
    plt = _plt()
    _, fwd_full = load_layer(cfg, "forward", model.iso_pitch)   # greyscale context
    net = model.fwd_fine
    fig, ax = plt.subplots(figsize=(7, 8))
    ext = _extent(fwd_full)
    ax.imshow(fwd_full.mask, origin="lower", extent=ext, cmap="Greys", interpolation="nearest")
    ov = np.zeros((*fwd_full.mask.shape, 4)); ov[net.mask] = [1, 0.3, 0, 0.7]
    ax.imshow(ov, origin="lower", extent=ext, interpolation="nearest")

    port, extra = _port_and_extra(cfg)
    closures = [(p[0], p[1]) for p in cfg.get("closure", {}).get("points", [])]
    _annotate(ax, port, closures, extra=extra, snap_cm=None)

    bb = net.filled_bbox()
    if bb:
        ax.set_xlim(bb[0] - margin, bb[2] + margin)
        ax.set_ylim(bb[1] - margin, bb[3] + margin)
    ax.set_xlabel("x [mm]"); ax.set_ylabel("y [mm]")
    ax.set_title("forward net (orange) + path coordinates")
    ax.grid(True, alpha=0.3); ax.set_aspect("equal")
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--mesh-pitch", type=float, default=None,
                    help="override the config's mesh_pitch_mm (sweep variants); "
                         "output filenames gain a _m<pitch> suffix")
    ap.add_argument("--margin", type=float, default=3.0,
                    help="zoom margin around the mesh/net (mm)")
    args = ap.parse_args(argv)

    try:
        _plt()
    except Exception as e:                       # noqa: BLE001
        print(f"matplotlib unavailable: {e}\nInstall it: "
              f"pacman -S mingw-w64-ucrt-x86_64-python-matplotlib")
        return 1

    cfg = load_config(args.config)
    here = os.path.dirname(os.path.abspath(__file__))
    outdir = args.outdir or cfg.get("outdir") or os.path.join(here, "out")
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.config))[0]
    pitch = args.mesh_pitch if args.mesh_pitch is not None else float(cfg["mesh_pitch_mm"])
    # suffix the outputs only when overridden, so default behavior is unchanged
    base = stem + (f"_m{pitch:g}" if args.mesh_pitch is not None else "")

    model = model_cache.get_model(cfg, pitch, os.path.join(outdir, "meshes"), stem)
    ta = cfg["terminal_a"]; tb = cfg["terminal_b"]
    closures = [(p[0], p[1]) for p in cfg.get("closure", {}).get("points", [])]

    # shared axes so the forward and return images (and overlay) line up 1:1
    bounds = _union_bounds([model.forward.mask.filled_bbox(),
                            model.ret.mask.filled_bbox()], args.margin)

    fpath = os.path.join(outdir, f"{base}_mesh_forward.png")
    render_mesh(model.forward.mask,
                f"{base}: FORWARD mesh ({int(model.forward.mask.mask.sum())} cells @ "
                f"{model.mesh_pitch} mm, z={model.forward.z:.3f} mm)",
                (ta[0], ta[1], "b^", "port A"), closures, fpath, bounds)
    print(f"  wrote {os.path.basename(fpath)}")

    rpath = os.path.join(outdir, f"{base}_mesh_return.png")
    render_mesh(model.ret.mask,
                f"{base}: RETURN mesh ({int(model.ret.mask.mask.sum())} cells @ "
                f"{model.mesh_pitch} mm, z={model.ret.z:.3f} mm)",
                (tb[0], tb[1], "cv", "port B"), closures, rpath, bounds)
    print(f"  wrote {os.path.basename(rpath)}")

    opath = os.path.join(outdir, f"{base}_overlay.png")
    render_overlay(model.forward.mask, model.ret.mask, cfg,
                   f"{base}: forward (VOUT) over return (GND), @ {model.mesh_pitch} mm",
                   opath, bounds)
    print(f"  wrote {os.path.basename(opath)}")

    gpath = os.path.join(outdir, f"{base}_region.png")
    render_region(cfg, model, gpath, margin=args.margin)
    print(f"  wrote {os.path.basename(gpath)}")

    print(f"Done. PNGs in {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
