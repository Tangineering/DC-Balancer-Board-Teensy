#!/usr/bin/env python3
"""Footprint underside (r6 31 x 33 mm CR) area available to bottom parts under rule A (clear of MB L1 POWER copper
+1 mm, the r3 shadow rule extended to every power net) and rule B (clear of every non-GND MB L1 feature +1 mm),
outside the r3 bottom keep-out, the two header bodies (2.54 mm wide, ASSUMED centred on the columns), the W1-W4
pads (+0.5 mm) and MB parts under the footprint (+1 mm). Also lists the MB L1 copper under W1-W4.
Run: /c/Users/ricky/miniforge3/python.exe -I r7_footprint_underside.py  (from this folder)."""
import importlib.util
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("r7", os.path.join(HERE, "r7_minimal_calc.py"))
r7 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r7)
board = r7.load_board()
lim = (18.20, 34.64, 48.20, 66.64)                     # courtyard limit, design A.7
RES = 0.05
xs = np.arange(lim[0] + RES / 2, lim[2], RES)
ys = np.arange(lim[1] + RES / 2, lim[3], RES)
X, Y = np.meshgrid(xs, ys)
cell = RES * RES
ex = np.zeros_like(X, dtype=bool)
ex |= (X >= 24.5) & (X <= 36.0) & (Y >= 48.5) & (Y <= 53.5)               # r3 bottom keep-out (A.7)
ex |= (np.abs(X - 20.998) <= 1.27 + 0.5) & (Y >= 36.544 - 1.27 - 0.5) & (Y <= 64.484 + 1.27 + 0.5)   # 1x12 body
ex |= (np.abs(X - 45.998) <= 1.27 + 0.5) & (Y >= 39.084 - 1.27 - 0.5) & (Y <= 61.944 + 1.27 + 0.5)   # 1x10 body
for (wx, wy, pd) in ((30.3, 61.2, 2.3), (27.7, 61.2, 2.3), (24.3, 45.4, 2.5), (24.3, 55.6, 2.5)):
    ex |= np.hypot(X - wx, Y - wy) <= pd / 2 + 0.5
for pn, pk, b in r7.parts_in((17.70, 34.14, 48.70, 67.14)):
    ex |= (X >= b[0] - 1) & (X <= b[2] + 1) & (Y >= b[1] - 1) & (Y <= b[3] + 1)
m, wires, polys, vias = r7.shadow_masks(board, (17.70, 34.14, 48.70, 67.14), (X, Y), 1.0)
base = (~ex).sum() * cell
A = (~(ex | m["POWER"])).sum() * cell
A3 = (~(ex | m["POWER"] | m["3V3"])).sum() * cell
B = (~(ex | m["POWER"] | m["3V3"] | m["SIGNAL"])).sum() * cell
print("footprint underside, courtyard-limited %.1f mm2; outside keep-out/bodies/W pads/MB parts %.1f mm2" % (
    X.size * cell, base))
print("  rule A (clear of POWER +1 mm) %.1f mm2; rule A + 3V3 %.1f mm2; rule B (clear of every non-GND +1 mm) %.1f mm2"
      % (A, A3, B))
nets = sorted({w[0] for w in wires if r7.classify(w[0]) != "GND"} |
              {p[0] for p in polys if r7.classify(p[0]) != "GND"})
print("  non-GND MB L1 nets under/near the footprint:", {n: r7.classify(n) for n in nets})
for (nm, wx, wy, pd) in (("W1 VCHGOUT", 30.3, 61.2, 2.3), ("W2 GND", 27.7, 61.2, 2.3), ("W3 VCHG", 24.3, 45.4, 2.5),
                         ("W4 GND", 24.3, 55.6, 2.5)):
    near = set()
    for net, ax, ay, bx, by, w in wires:
        d = r7.seg_dist(np.array([wx]), np.array([wy]), ax, ay, bx, by)[0]
        if d <= w / 2 + pd / 2 + 1.0:
            near.add((net, round(float(d - w / 2), 2)))
    for net, pts in polys:
        if r7.pip(np.array([[wx]]), np.array([[wy]]), pts)[0, 0]:
            near.add((net + " poly (inside outline)", 0.0))
    for net, vx, vy, d in vias:
        dd = float(np.hypot(vx - wx, vy - wy))
        if dd <= pd / 2 + 1.5:
            near.add((net + " via", round(dd, 2)))
    print("  %s at (%.1f, %.1f): MB L1 copper within pad radius + 1 mm (net, centre-line edge distance mm): %s" % (
        nm, wx, wy, sorted(near)))
