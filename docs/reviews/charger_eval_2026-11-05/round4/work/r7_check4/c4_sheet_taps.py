"""Check 4, items 4-6: tap adjacency and lengths, per-region booking overlap, sheet trims against bodies and pads."""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "r7_check"))
from brdgeo import Board, d_pt_seg, pip, edges, shoelace  # noqa: E402

B = Board()

# ------------------------------------------------------------------ taps
XS = [50.80, 53.34, 55.88, 58.42, 60.96, 63.50]
YS = [58.94, 61.48, 64.02, 66.56]
GRID = {66.56: ["T2", None, "F24", "T15", "T21", "T20"], 64.02: ["R175a", "T6", "T11", "T14", "T17", "T10"],
        61.48: ["R175b", None, "T4", "T16", "T17r", "T19"], 58.94: ["T1", "T7b", "T12", "T5", "T13", "T3"]}
POS = {}
for y, row in GRID.items():
    for x, t in zip(XS, row):
        POS[(x, y)] = t
nb = {}
pairs = []
for (x, y), t in POS.items():
    for dx, dy in ((2.54, 0), (0, 2.54)):
        q = (round(x + dx, 2), round(y + dy, 2))
        q = min(POS, key=lambda k: math.hypot(k[0] - q[0], k[1] - q[1]))
        if math.hypot(q[0] - x - dx, q[1] - y - dy) < 1e-6:
            pairs.append((t, POS[q]))
for a, b in pairs:
    if a and b:
        nb.setdefault(a, set()).add(b)
        nb.setdefault(b, set()).add(a)
print("orthogonal pairs: %d (with spares)" % len(pairs))
EN = {"T3", "T4", "T5"}
GND = {"T7b", "T17r"}
ok = []
ok.append(("no EN-EN adjacency", not any(a in EN and b in EN for a, b in pairs)))
ok.append(("T6 beside R175a", "R175a" in nb["T6"] or "R175b" in nb["T6"]))
ok.append(("T6 no GND/EN neighbour", not (nb["T6"] & (EN | GND))))
ok.append(("T10 not beside T21", "T21" not in nb["T10"]))
RAW = {"T3", "T4", "T5", "T8", "T10", "T11", "T12", "T13", "T14", "T15", "T16", "T17", "T19", "T20", "T21", "F24"}
ok.append(("T1 no raw Teensy GPIO neighbour", not (nb["T1"] & RAW)))
ok.append(("T2 no raw Teensy GPIO neighbour", not (nb["T2"] & RAW)))
ok.append(("T1/T7b adjacent", "T7b" in nb["T1"]))
ok.append(("T17/T17r adjacent", "T17r" in nb["T17"]))
for k, v in ok:
    print("  %-34s %s" % (k, v))
print("  neighbours T1 %s, T2 %s, T6 %s" % (sorted(nb["T1"]), sorted(nb["T2"]), sorted(nb["T6"])))
MB = {"T1": (97.790, 16.412), "T7b": (97.790, 19.363), "T2": (67.705, 69.850), "T3": (87.122, 42.926),
      "T4": (87.122, 37.846), "T5": (87.122, 35.306), "T6": (87.122, 55.626), "T22": (25.859, 30.439),
      "T8": (109.982, 53.086), "T9": (55.443, 26.492), "T10": (87.122, 63.246), "T11": (109.982, 68.326),
      "T12": (109.982, 32.766), "T13": (109.982, 35.306), "T14": (109.982, 65.786), "T15": (109.982, 83.566),
      "T16": (109.982, 37.846), "T17": (109.982, 81.026), "T17r": (109.982, 55.626), "T20": (81.534, 69.797),
      "T21": (109.982, 78.486), "T18": (50.800, 41.084), "T19": (109.982, 50.546), "F24": (87.122, 83.566)}
PADXY = {t: p for p, t in POS.items() if t}
PADXY.update({"T22": (26.44, 35.8), "T8": (28.98, 35.8), "T9": (31.52, 35.8), "T18": (41.68, 35.8)})
S20 = ["T1", "T2", "T3", "T4", "T5", "T6", "T22", "T8", "T9", "T10", "T11", "T12", "T13", "T14", "T15", "T16", "T17",
       "T17r", "T20", "T21"]
L = {t: math.hypot(MB[t][0] - PADXY[t][0], MB[t][1] - PADXY[t][1]) for t in MB}
print("  straight sum (20) %.1f mm; per tap %s" % (sum(L[t] for t in S20), {t: round(v, 1) for t, v in L.items()}))
# own check for a few MB points in the BRD
for t, (el, pd) in (("T2", ("C-D2", "1")), ("T20", ("ROS", "2")), ("T18", ("CO-5V", "1")), ("T9", ("SNS-BT", "15")),
                    ("T1", ("C-D6", "1"))):
    p = B.els[el]["pads"][pd]
    print("  BRD %s pad %s: (%.3f, %.3f) vs %s" % (el, pd, p["x"], p["y"], MB[t]))
# T8 dressed path
T8P = [(28.98, 35.8), (28.98, 34.40), (63.50, 34.40), MB["T8"]]
print("  T8 dressed %.2f mm" % sum(math.hypot(T8P[i + 1][0] - T8P[i][0], T8P[i + 1][1] - T8P[i][1]) for i in range(3)))
for nm, c in (("F10 T9", (31.52, 35.8)), ("F22 T18", (41.68, 35.8))):
    print("    lane y 34.40 (jacket r 0.5) to %s pad bottom %.3f: gap %.3f" % (nm, c[1] - 0.75, c[1] - 0.75 - 34.90))
print("    lane jacket low edge 33.90 vs CR low edge 34.14")

# ------------------------------------------------------------------ booking: B3 + S3 union
a = 3.0
b3, s3 = (35.00, 70.80), (35.00, 73.10)
ov = max(0.0, a - abs(b3[1] - s3[1])) * max(0.0, a - abs(b3[0] - s3[0]))
union = 2 * a * a - ov
print("\nB3/S3 3x3 beads: overlap %.2f mm2, union %.2f mm2 (booked 9.00)" % (ov, union))
gates = 6 * 15.0 + 2 * 7.0
for extra in (9.0, union):
    print("  tab Y with U109 moved, spot %.2f: %.1f / 153.7 = %.1f %%" % (extra, gates + extra, 100 * (gates + extra) / 153.7))
print("  tab Y with U108 + U109 moved, union spot: %.1f / 153.7 = %.1f %%; interior 201.6 + 7.0 = %.1f / 288.8 = %.1f %%"
      % (gates - 7 + union, 100 * (gates - 7 + union) / 153.7, 208.6, 100 * 208.6 / 288.8))
s1 = (36.00 - 1.5, 46.83 - 1.5, 36.00 + 1.5, 46.83 + 1.5)
print("  S1 footprint x %.2f-%.2f vs J101 region x 37.0 (+0.5 gap -> 36.5): into region %.2f mm, into gap %.2f mm; "
      "J101 body x 38.55 -> %.2f mm clear" % (s1[0], s1[2], s1[2] - 37.0, min(s1[2], 37.0) - 36.5, 38.55 - s1[2]))
print("  band exact area %.2f mm2 (raster 127.4)" % ((42.43 - 23.15) * (41.63 - 35.05)))
CY = {"0603": 4.35, "0805": 6.12, "1206": 10.925, "SOT": 10.0, "SSOP": 15.0, "SC70": 7.0, "SOD323": 6.12}
band = 7 * 10.0 + ((2 * 2.54 + 2.0) * 2.0 + 4.0) + 4.35
interior = 3 * 6.12 + 3 * 4.35 + 4 * 10.0 + 2 * 7.0 + 2 * 15.0 + 2 * 10.0 + 6.12 + 3 * 9.0 + 7.0 + 6 * 4.35
print("  sums: band %.2f (%.1f %%), interior %.2f (%.1f %%), tab X %.2f (%.1f %%), tab Y %.2f (%.1f %%), tab Y bottom %.2f (%.1f %%)"
      % (band, 100 * band / 127.4, interior, 100 * interior / 288.8, 80 + 10.925, 100 * 90.925 / 173.3,
         gates + 9, 100 * (gates + 9) / 153.7, 9 * 4.35, 100 * 9 * 4.35 / 133.2))
print("  flexible move total: 7 x 4.35 = %.2f mm2" % (7 * 4.35))

# ------------------------------------------------------------------ sheet
SH = [(16.700, 33.140), (49.700, 33.140), (49.700, 36.766), (48.800, 36.766), (48.800, 42.482), (49.700, 42.482),
      (49.700, 55.300), (66.000, 55.300), (66.000, 69.300), (47.700, 69.300), (47.700, 68.140), (45.624, 68.140),
      (45.624, 67.480), (39.719, 67.480), (39.719, 68.140), (38.560, 68.140), (38.560, 72.934), (37.561, 72.934),
      (37.561, 77.000), (36.864, 77.000), (36.864, 76.362), (22.064, 76.362), (22.064, 77.000), (18.286, 77.000),
      (16.700, 75.414), (16.700, 67.854), (16.752, 67.854), (16.752, 52.414), (16.700, 52.414)]
CUT = {'D-BT-SQ': [27.718, 47.849, 31.718, 52.226], 'C-D11': [24.615, 48.692, 27.709, 51.892],
       'C-D12': [32.743, 48.438, 35.837, 51.638], 'C-DC11': [32.986, 51.195, 35.086, 53.453],
       'C-DC12': [26.89, 51.449, 28.99, 53.707]}
print("\nsheet: %d vertices, area %.1f mm2 (relief holes / cut-outs not subtracted), bbox %.2f x %.2f" % (
    len(SH), shoelace(SH), max(p[0] for p in SH) - min(p[0] for p in SH), max(p[1] for p in SH) - min(p[1] for p in SH)))
R7 = [(17.70, 34.14), (48.70, 34.14), (48.70, 56.30), (65.00, 56.30), (65.00, 68.30), (48.70, 68.30),
      (48.70, 67.14), (37.56, 67.14), (37.56, 76.00), (18.70, 76.00), (17.70, 75.00)]
print("  CR outline vertices outside the sheet: %s" % [p for p in R7 if not pip(p, SH)])


def rect_pts(r, n=12):
    x0, y0, x1, y1 = r
    pts = []
    for i in range(n + 1):
        for j in range(n + 1):
            pts.append((x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * j / n))
    return pts


def in_region(p):
    if not pip(p, SH):
        return False
    for r in CUT.values():
        if r[0] < p[0] < r[2] and r[1] < p[1] < r[3]:
            return False
    return True


def clear_rect(r):
    """>0: distance from rect r to the sheet region (outside the outer polygon or inside a cut-out); <0 overlap."""
    if any(in_region(p) for p in rect_pts(r)):
        return -1.0
    c = [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])]
    re = list(zip(c, c[1:] + c[:1]))
    best = 1e9
    for a, b in edges(SH):
        best = min(best, min(d_pt_seg(q, a, b) for q in c), min(d_pt_seg(q, e0, e1) for e0, e1 in re for q in (a, b)))
    for cr in CUT.values():
        if cr[0] <= r[0] and r[2] <= cr[2] and cr[1] <= r[1] and r[3] <= cr[3]:
            best = min(best, r[0] - cr[0], cr[2] - r[2], r[1] - cr[1], cr[3] - r[3])
    return best


def clear_circ(c, rad):
    if in_region(c) and not any(0 for _ in ()):
        pass
    pts = [(c[0] + rad * math.cos(2 * math.pi * k / 36), c[1] + rad * math.sin(2 * math.pi * k / 36)) for k in range(36)] + [c]
    if any(in_region(p) for p in pts):
        return -1.0
    best = min(d_pt_seg(c, a, b) for a, b in edges(SH)) - rad
    for cr in CUT.values():
        if cr[0] <= c[0] <= cr[2] and cr[1] <= c[1] <= cr[3]:
            best = min(best, c[0] - cr[0] - rad, cr[2] - c[0] - rad, c[1] - cr[1] - rad, cr[3] - c[1] - rad)
    return best


res = []
for n, e in B.els.items():
    if n == "CHG":
        continue
    if e["side"] != "top":
        continue
    if e["body"]:
        res.append((clear_rect(e["body"]), n, "body"))
    for pn, pd in e["pads"].items():
        if pd["kind"] == "smd":
            if pd["layer"] != "1":
                continue
            res.append((clear_rect(pd["bb"]), n, "pad " + pn))
        elif pd.get("shape") in ("square", "octagon"):
            res.append((clear_rect(pd["bb"]), n, "pad " + pn + " " + pd["shape"]))
        else:
            res.append((clear_circ((pd["x"], pd["y"]), pd["dia"] / 2), n, "pad " + pn + " round"))
res.sort()
print("  nearest MB top bodies/pads to the sheet region (cut-outs and holes not counted as region):")
for r in res[:14]:
    print("    %+.3f %s %s" % r)
print("  excluding the five cut-out parts:")
for r in [r for r in res if r[1] not in CUT][:10]:
    print("    %+.3f %s %s" % r)
e = B.els["L-FC"]
print("  L-FC body %s box %s pads %s" % (e["body"], e["box"], {k: tuple(round(v, 3) for v in p["bb"]) for k, p in e["pads"].items()}))
# L-FC Eaton body (assumed) vs the sheet
LFC = B.els["L-FC"]
LE = (LFC["x"] - 6.9, LFC["y"] - 6.45, LFC["x"] + 6.9, LFC["y"] + 6.45)
print("  L-FC Eaton box %s: clearance %.3f" % (tuple(round(v, 3) for v in LE), clear_rect(LE)))
# CHG header pads vs the 2.2 mm relief hole
chg = B.els["CHG"]["pads"]
sq = sorted({(pd.get("shape"), round(pd["dia"], 3)) for pd in chg.values()})
print("  CHG pads: %d, shapes/sizes %s; relief hole r 1.1 vs square half-diagonal %.4f -> corner clearance %.3f, flat %.3f"
      % (len(chg), sq, 1.65 / math.sqrt(2), 1.1 - 1.65 / math.sqrt(2), 1.1 - 0.825))
