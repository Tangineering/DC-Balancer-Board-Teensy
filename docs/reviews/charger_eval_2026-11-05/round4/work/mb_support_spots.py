#!/usr/bin/env python3
"""Round 4 work: candidate far-end support spots in each extension zone.

For each zone, on a 0.25 mm grid, a point qualifies as
  FOOT  : a bonded-foot centre if a 4.0 x 4.0 mm square around it holds no part body (bbox + 0.25 mm) and no via;
  DRILL : a drilled-hole centre if, in addition, a 3.0 mm radius circle holds no non-GND copper on L1 or L16
          (polygons + traces with their width), so a new NPTH only perforates the GND pours.
The 5V island and its 1 mm rim are excluded for both (heat, adhesive rating). Prints the counts and the qualifying
point farthest from the pin field in each zone (the useful prop position).
Run: /c/Users/ricky/miniforge3/python.exe -I mb_support_spots.py
"""
import math
import os
import sys

import numpy as np
from matplotlib.path import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mb_mech_calc as M  # noqa: E402

STEP = 0.25
ZONES = {
    "+x usable": [48.70, 55.01, 80.23, 68.30],
    "+x core": [48.70, 55.01, 65.00, 67.14],
    "+y usable": [17.70, 67.14, 39.72, 76.51],
    "-y usable": [17.70, 26.00, 48.70, 34.14],
}
PIN_FIELD = [20.998, 36.544, 45.998, 64.484]


def seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    t = np.clip(((px - x1) * dx + (py - y1) * dy) / L2, 0, 1) if L2 > 0 else 0
    return np.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def main():
    p5 = [p for p in M.POLYS if p[0] == "5V"][0]
    path5 = Path(p5[2])
    for name, z in ZONES.items():
        xs = np.arange(z[0] + 2.0, z[2] - 2.0 + 1e-9, STEP)
        ys = np.arange(z[1] + 2.0, z[3] - 2.0 + 1e-9, STEP)
        X, Y = np.meshgrid(xs, ys)
        P = np.c_[X.ravel(), Y.ravel()]
        foot = np.ones(len(P), dtype=bool)
        for e in M.ELS.values():
            if e["name"] == "CHG":
                continue
            b = e["bbox"]
            hit = (P[:, 0] + 2.0 > b[0] - 0.25) & (P[:, 0] - 2.0 < b[2] + 0.25) & \
                  (P[:, 1] + 2.0 > b[1] - 0.25) & (P[:, 1] - 2.0 < b[3] + 0.25)
            foot &= ~hit
        for (n, vx, vy, d) in M.VIAS:
            hit = (np.abs(P[:, 0] - vx) < 2.0 + d / 2) & (np.abs(P[:, 1] - vy) < 2.0 + d / 2)
            foot &= ~hit
        near5 = path5.contains_points(P, radius=2 * (p5[3] / 2 + 1.0))
        foot &= ~near5
        foot_np = foot.copy()
        for (net, lay, pts, w) in M.POLYS:
            if net != "GND" and net in M.POWER_NETS:
                foot_np &= ~Path(pts).contains_points(P, radius=2 * (2.0 + w / 2 + 0.5))
        drill = foot.copy()
        for (net, lay, pts, w) in M.POLYS:
            if net == "GND":
                continue
            drill &= ~Path(pts).contains_points(P, radius=2 * (3.0 + w / 2))
        for (net, lay, x1, y1, x2, y2, w) in M.WIRES:
            if net == "GND":
                continue
            drill &= ~(seg_dist(P[:, 0], P[:, 1], x1, y1, x2, y2) < 3.0 + w / 2)

        def far(mask):
            if not mask.any():
                return None
            Q = P[mask]
            dx = np.maximum(np.maximum(PIN_FIELD[0] - Q[:, 0], Q[:, 0] - PIN_FIELD[2]), 0)
            dy = np.maximum(np.maximum(PIN_FIELD[1] - Q[:, 1], Q[:, 1] - PIN_FIELD[3]), 0)
            i = int(np.argmax(np.hypot(dx, dy)))
            return (round(float(Q[i, 0]), 2), round(float(Q[i, 1]), 2), round(float(np.hypot(dx, dy)[i]), 1))

        print("%-10s grid %d pts | FOOT ok %d (%.0f %%), farthest %s | FOOT off power pours %d, farthest %s | "
              "DRILL ok %d, farthest %s"
              % (name, len(P), foot.sum(), 100.0 * foot.mean(), far(foot), foot_np.sum(), far(foot_np),
                 drill.sum(), far(drill)))


if __name__ == "__main__":
    main()
