#!/usr/bin/env python3
"""
inspect_board.py -- discover net coordinates to put in a config.

Rasterises a copper layer and lists its largest connected nets (area, centroid,
bbox). Pick the centroid of the net you care about (e.g. the VBUS/boost-output
pour on top, the ground pour on bottom) and paste the (x,y) into your config's
"forward"/"return" "point" fields and the terminal_a/terminal_b coordinates.

Optionally writes a PNG map (with a millimetre grid) of the layer so you can read
coordinates visually.

Usage:
    python inspect_board.py <copper_layer.gbr> [--pitch 0.3] [--top 12] [--png map.png]
"""

from __future__ import annotations

import argparse
import os
import sys

from gerber import parse_gerber
from geometry import rasterize, list_nets


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("gerber")
    ap.add_argument("--pitch", type=float, default=0.3)
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--png", default=None, help="optional PNG map output path")
    ap.add_argument("--min-cells", type=int, default=20)
    args = ap.parse_args(argv)

    layer = parse_gerber(args.gerber)
    cm = rasterize(layer, pitch=args.pitch)
    nets = list_nets(cm, min_cells=args.min_cells)

    print(f"{os.path.basename(args.gerber)}: {len(nets)} nets >= {args.min_cells} cells "
          f"(pitch={args.pitch} mm)\n")
    print(f"{'#':>3} {'area_mm2':>10} {'centroid(x,y)':>22} {'bbox (xmin,ymin,xmax,ymax)':>40}")
    for k, n in enumerate(nets[:args.top]):
        cx, cy = n["centroid"]
        bx = n["bbox"]
        print(f"{k:>3} {n['area_mm2']:>10.2f}  ({cx:8.3f},{cy:8.3f})   "
              f"({bx[0]:7.2f},{bx[1]:7.2f},{bx[2]:7.2f},{bx[3]:7.2f})")

    if args.png:
        _png(cm, nets[:args.top], args.png)
        print(f"\nwrote {args.png}")
    return 0


def _png(cm, nets, path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:                       # noqa: BLE001
        print(f"(png skipped: matplotlib unavailable: {e})")
        return
    extent = (cm.x0, cm.x0 + cm.nx * cm.pitch, cm.y0, cm.y0 + cm.ny * cm.pitch)
    fig, ax = plt.subplots(figsize=(9, 7))
    ax.imshow(cm.mask, origin="lower", extent=extent, cmap="Greys", interpolation="nearest")
    for k, n in enumerate(nets):
        cx, cy = n["centroid"]
        ax.plot(cx, cy, "r+", ms=10)
        ax.annotate(str(k), (cx, cy), color="red", fontsize=8)
    ax.set_xlabel("x [mm]"); ax.set_ylabel("y [mm]")
    ax.set_title("copper mask + net indices")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)


if __name__ == "__main__":
    sys.exit(main())
