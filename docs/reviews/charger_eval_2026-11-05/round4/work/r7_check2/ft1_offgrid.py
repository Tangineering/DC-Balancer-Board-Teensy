"""FT1: exact best y centre (off the 0.02 mm grid) for heights 1.6 and 1.7."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo2 import FEATS, VIAS, near, body, tolerances  # noqa: E402

Z = (44.0, 52.0, 70.0, 73.0)
kw = dict(feats=near(Z, FEATS, 0.0), vias=near(Z, VIAS, 0.0))
for w, h, cx in ((4.0, 1.6, 61.72), (4.0, 1.7, 61.72), (3.6, 1.7, 61.50)):
    best = None
    for j in range(0, 41):
        cy = 66.68 + 0.001 * j
        tol = tolerances(body(cx, cy, w, h), "X", **kw)
        if tol and (best is None or tol[0] > best[0][0]):
            best = (tol, cy)
    print("%.1f x %.1f at x %.2f: best y %.4f -> t %.4f tx %.4f ty %.4f" % ((w, h, cx, best[1]) + best[0]))
