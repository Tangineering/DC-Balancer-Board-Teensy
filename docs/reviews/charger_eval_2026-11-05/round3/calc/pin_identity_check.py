#!/usr/bin/env python3
"""CHG carrier pin-identity check (round 3 r6, finding cr-coordinate-convention-mirror-ambiguity; T-A-06 step 0).

The 22 CHG holes are symmetric under a y-mirror (both columns centred on y = 50.514 mm), so a carrier captured with the y axis
flipped still drops onto the motherboard with every pin reversed inside its column. This script makes the pin identity a
scripted gate instead of a visual one.

1. Without arguments it parses the motherboard .brd (Eagle XML, stdlib only), applies the CHG element transform
   (element at (47.498, 34.544), R180: board = (x0 - px, y0 - py)) and prints every pad name, number and board coordinate
   (Eagle convention: top view, origin = MB origin, +x right, +y UP).
2. With a CSV of the KiCad carrier header pads (columns: pad,x_mm,y_mm, as exported from the KiCad footprint position /
   pad report) it compares each pad with the .brd pad of the same number. `--kicad-y-down` negates the CSV y values first
   (KiCad's PCB editor uses +y DOWN). Any pad further than 0.05 mm from its .brd position fails, and a y-mirror is reported
   by name. Exit code 0 = pass, 1 = fail.

Usage: python3 -I pin_identity_check.py [--brd PATH] [--csv kicad_pads.csv [--kicad-y-down] [--dx DX --dy DY]]
`--dx/--dy` shift the CSV into MB board coordinates if the KiCad carrier has its own origin.
"""
import argparse
import csv
import math
import os
import sys
import xml.etree.ElementTree as ET

AG105_NAMES = {1: "VSEL", 2: "CSEL", 3: "STAT", 4: "VIN-", 5: "NC1", 6: "NC2", 7: "SCL", 8: "SDA", 9: "NC3", 10: "VIN+",
               11: "MPPTD", 12: "MPPTSEL", 13: "THERM", 14: "VBAT-1", 15: "VBAT-2", 16: "VLOAD-1", 17: "VLOAD-2", 18: "VBAT+1",
               19: "VBAT+2", 20: "LDIS", 21: "VLOAD+1", 22: "VLOAD+2"}
CR_NET = {10: "VCHGIN", 4: "GND", 14: "GND", 15: "GND", 18: "VCHG", 19: "VCHG", 8: "SDA", 7: "SCL", 3: "STAT", 11: "CHG_ARM",
          13: "TS_EXT"}

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BRD = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "..", "references", "Scale Car Board PCB 20260625.brd"))


def brd_pads(path):
    root = ET.parse(path).getroot()
    el = next(e for e in root.iter("element") if e.get("name") == "CHG")
    pkg_name = el.get("package")
    pkg = next(p for p in root.iter("package") if p.get("name") == pkg_name)
    x0, y0 = float(el.get("x")), float(el.get("y"))
    rot = el.get("rot") or "R0"
    ang = math.radians(float(rot.lstrip("MR")))
    mirror = rot.startswith("M")
    out = {}
    for pad in pkg.iter("pad"):
        px, py = float(pad.get("x")), float(pad.get("y"))
        if mirror:
            px = -px
        bx = x0 + px * math.cos(ang) - py * math.sin(ang)
        by = y0 + px * math.sin(ang) + py * math.cos(ang)
        out[pad.get("name")] = (round(bx, 3), round(by, 3))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brd", default=DEFAULT_BRD)
    ap.add_argument("--csv")
    ap.add_argument("--kicad-y-down", action="store_true")
    ap.add_argument("--dx", type=float, default=0.0)
    ap.add_argument("--dy", type=float, default=0.0)
    a = ap.parse_args()
    pads = brd_pads(a.brd)
    # map AG105 pad names in the Eagle package to pin numbers
    name_to_pin = {v: k for k, v in AG105_NAMES.items()}
    by_pin = {}
    for nm, xy in pads.items():
        pin = name_to_pin.get(nm)
        if pin is None:
            # the package may name pads by number
            try:
                pin = int(nm)
            except ValueError:
                continue
        by_pin[pin] = xy
    print("CHG pads from %s (Eagle board coordinates: top view, MB origin, +x right, +y UP)" % os.path.basename(a.brd))
    for pin in sorted(by_pin):
        x, y = by_pin[pin]
        print("  pin %2d %-8s x %7.3f  y %7.3f  KiCad y %8.3f  CR net %s" % (pin, AG105_NAMES[pin], x, y, -y, CR_NET.get(pin, "anchor")))
    ys = [xy[1] for xy in by_pin.values()]
    print("  column centre y %.3f (both columns): the pattern is symmetric under a y-mirror, so only pin identity detects one" % ((min(ys) + max(ys)) / 2))
    if not a.csv:
        return 0
    rows = list(csv.DictReader(open(a.csv, newline="")))
    fails, mirrored = [], 0
    for r in rows:
        pin = int(r["pad"])
        x = float(r["x_mm"]) + a.dx
        y = float(r["y_mm"])
        y = (-y if a.kicad_y_down else y) + a.dy
        bx, by = by_pin[pin]
        d = math.hypot(x - bx, y - by)
        if d > 0.05:
            fails.append("pin %d %s at (%.3f, %.3f), .brd (%.3f, %.3f), off by %.3f mm" % (pin, AG105_NAMES[pin], x, y, bx, by, d))
            ym = 2 * 50.514 - by
            if math.hypot(x - bx, y - ym) < 0.05:
                mirrored += 1
    for f in fails:
        print("FAIL " + f)
    if mirrored:
        print("FAIL %d of %d pads sit at the y-MIRROR of their .brd position: the capture is mirrored (KiCad y entered as +y)" % (mirrored, len(rows)))
    print("PASS: every pad within 0.05 mm of its .brd position" if not fails else "FAIL: %d pad(s) off" % len(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
