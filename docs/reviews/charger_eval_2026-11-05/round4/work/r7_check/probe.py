"""Probe BRD elements needed for the tap and EVM checks (stdlib only)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brdgeo import Board  # noqa

B = Board()
for en in ("C-D6", "C-D2", "BAL", "SNS-BT", "ROS", "CO-5V", "J1", "J2"):
    e = B.els[en]
    print(en, e["pkg"], (e["x"], e["y"]), e["rot"], "box", tuple(round(v, 3) for v in e["box"]))
    for pn, pd in sorted(e["pads"].items(), key=lambda kv: kv[0]):
        if en in ("J1", "J2") and pn not in ("7", "07", "9", "09", "11", "19", "21", "23", "29", "31", "33",
                                              "39", "43", "45", "47", "1", "2", "3", "4"):
            continue
        print("   pad %-5s (%.3f, %.3f) %s %s net %s" % (pn, pd["x"], pd["y"], pd["kind"],
                                                       tuple(round(v, 3) for v in pd["bb"]),
                                                       B.padnet.get((en, pn))))
# Teensy element(s)
for en, e in B.els.items():
    if "TEENSY" in (e["pkg"] or "").upper() or "TEENSY" in (e["value"] or "").upper():
        print("TEENSY", en, e["pkg"], (e["x"], e["y"]), e["rot"], "box", tuple(round(v, 3) for v in e["box"]))
