"""CHG header pads (square, 1.65 mm) against the free edges of tab X and tab Y: square vs disc model."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brdgeo import Board, d_seg_seg, d_pt_seg, rect_poly, edges  # noqa

B = Board()
FREE = {"tab X": [((48.70, 56.30), (65.00, 56.30)), ((65.00, 56.30), (65.00, 68.30)), ((65.00, 68.30), (48.70, 68.30)),
                  ((48.70, 68.30), (48.70, 67.14))],
        "tab Y": [((37.56, 67.14), (37.56, 76.00)), ((37.56, 76.00), (18.70, 76.00)), ((18.70, 76.00), (17.70, 75.00)),
                  ((17.70, 75.00), (17.70, 67.14))]}
chg = B.els["CHG"]
for pn, pd in chg["pads"].items():
    net = B.padnet.get(("CHG", pn), "(unconnected)")
    if net == "GND":
        continue
    sq = rect_poly(pd["bb"])
    for t, fe in FREE.items():
        dsq = min(d_seg_seg(a, b, c, d) for a, b in edges(sq) for c, d in fe)
        ddisc = min(d_pt_seg((pd["x"], pd["y"]), c, d) for c, d in fe) - pd["dia"] / 2
        if min(dsq, ddisc) < 6.0:
            print("%-6s %-8s %-14s (%.3f, %.3f) shape %-6s square %.3f  disc %.3f  diff %.3f" % (
                t, pn, net, pd["x"], pd["y"], pd["shape"], dsq, ddisc, ddisc - dsq))
v = [x for x in B.vias if abs(x["x"] - 63.967) < 0.01][0]
print("EN-REG-BT via dia (max of attribute and rules):", round(v["dia"], 4))
