"""Tab X non-GND copper area by net: union per net vs the sum of per-shape areas (0.02 mm raster, cell centres)."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brdgeo import Board, d_pt_seg  # noqa

B = Board()
X0, Y0, X1, Y1, RES = 48.70, 56.30, 65.00, 68.30, 0.02
NX, NY = int(round((X1 - X0) / RES)), int(round((Y1 - Y0) / RES))
shapes = []
for w in B.wires:
    if w["layer"] == "1" and w["net"] != "GND":
        shapes.append((w["net"], "seg", w["a"], w["b"], w["w"] / 2))
for v in B.vias:
    if v["net"] != "GND":
        shapes.append((v["net"], "pt", (v["x"], v["y"]), None, v["dia"] / 2))
union, ssum = {}, {}
for net, kind, a, b, r in shapes:
    xs = [a[0]] + ([b[0]] if b else [])
    ys = [a[1]] + ([b[1]] if b else [])
    if max(xs) + r < X0 or min(xs) - r > X1 or max(ys) + r < Y0 or min(ys) - r > Y1:
        continue
    m = set()
    i0 = max(0, int((min(xs) - r - X0) / RES) - 1)
    i1 = min(NX, int((max(xs) + r - X0) / RES) + 2)
    j0 = max(0, int((min(ys) - r - Y0) / RES) - 1)
    j1 = min(NY, int((max(ys) + r - Y0) / RES) + 2)
    for j in range(j0, j1):
        y = Y0 + (j + 0.5) * RES
        for i in range(i0, i1):
            x = X0 + (i + 0.5) * RES
            dd = d_pt_seg((x, y), a, b) if kind == "seg" else math.hypot(x - a[0], y - a[1])
            if dd <= r:
                m.add((i, j))
    if not m:
        continue
    union.setdefault(net, set()).update(m)
    ssum[net] = ssum.get(net, 0.0) + len(m) * RES * RES
tu = ts = 0.0
for net in sorted(union):
    u = len(union[net]) * RES * RES
    tu += u
    ts += ssum[net]
    print("%-14s union %.2f  per-shape sum %.2f" % (net, u, ssum[net]))
print("TOTAL union %.2f  per-shape sum %.2f" % (tu, ts))
