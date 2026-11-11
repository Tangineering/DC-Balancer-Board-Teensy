"""Check 4 of r7_calc revision 3, item 2: W-lead dressing path clearances, spans, anchors, routes, BFS feasibility.

Own code. BRD parsing reuses work/r7_check/brdgeo.py; the path nodes are transcribed from r7_calc_out.txt H.23(l)
("full path" lines) and the hazard geometry from DOC A.8 / the H.23(g) grid; nothing is imported from r7_calc.py.
"""
import math
import os
import sys
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "r7_check"))
from brdgeo import Board, d_pt_seg, d_seg_seg, pip, rect_poly, edges, d_rect_rect  # noqa: E402

B = Board()


def d_rect_pt(R, p):
    return math.hypot(max(R[0] - p[0], 0.0, p[0] - R[2]), max(R[1] - p[1], 0.0, p[1] - R[3]))


def inside(R, p):
    return R[0] <= p[0] <= R[2] and R[1] <= p[1] <= R[3]


def d_rect_seg(R, a, b):
    if inside(R, a) or inside(R, b):
        return 0.0
    if any(d_seg_seg(a, b, c, d) == 0.0 for c, d in edges(rect_poly(R))):
        return 0.0
    return min([d_pt_seg(c, a, b) for c in rect_poly(R)] + [d_rect_pt(R, a), d_rect_pt(R, b)])


# ------------------------------------------------------------------ hazards (D-F2) from DOC A.8 + H.23(g) grid
POST = 0.64
HZ = {}
for k in range(12):
    x, y = 20.998, 36.544 + 2.54 * k
    HZ["1x12 pin %d post" % (22 - k)] = (x - POST / 2, y - POST / 2, x + POST / 2, y + POST / 2)
for k in range(10):
    x, y = 45.998, 39.084 + 2.54 * k
    HZ["1x10 pin %d post" % (k + 1)] = (x - POST / 2, y - POST / 2, x + POST / 2, y + POST / 2)
HZ["pin-10 pad"] = (45.998 - 0.95, 61.944 - 0.95, 45.998 + 0.95, 61.944 + 0.95)
for nm, r in (("C102c", (40.3, 60.10, 43.3, 61.55)), ("C102a", (39.8, 55.30, 42.1, 60.05)),
              ("R102", (42.65, 56.65, 44.45, 60.05)), ("C102b", (39.75, 52.05, 44.50, 55.25)),
              ("D107", (36.60, 53.40, 39.70, 60.00))):
    HZ["IN " + nm] = r
HZ["U101 cy"] = (39.3, 61.6, 44.3, 66.6)
HZ["+x pocket"] = (44.3, 63.40, 48.2, 66.64)
XS = [50.80, 53.34, 55.88, 58.42, 60.96, 63.50]
YS = [58.94, 61.48, 64.02, 66.56]
GRID = {66.56: ["T2", None, "F24", "T15", "T21", "T20"], 64.02: ["R175a", "T6", "T11", "T14", "T17", "T10"],
        61.48: ["R175b", None, "T4", "T16", "T17r", "T19"], 58.94: ["T1", "T7b", "T12", "T5", "T13", "T3"]}
for y, row in GRID.items():
    for x, t in zip(XS, row):
        if t and not t.startswith("R175"):
            HZ["tap " + t] = (x - 0.75, y - 0.75, x + 0.75, y + 0.75)
for t, (x, y) in (("F08", (26.44, 35.8)), ("F09", (28.98, 35.8)), ("F10", (31.52, 35.8)), ("F22", (41.68, 35.8))):
    HZ["tap " + t] = (x - 0.75, y - 0.75, x + 0.75, y + 0.75)
FIELD_CY = (49.80, 57.94, 64.50, 67.56)

# ------------------------------------------------------------------ switched conductors and rework points
SWN = ("VSW-FC", "VSW-BT")
SWSEG = []
for w in B.wires:
    if w["net"] in SWN and w["layer"] == "1":
        SWSEG.append((w["a"], w["b"], w["w"] / 2))
SWPOLY = [p for p in B.polys if p["net"] in SWN and p["layer"] == "1"]
LFC = B.els["L-FC"]
LFC_E = (LFC["x"] - 6.9, LFC["y"] - 6.45, LFC["x"] + 6.9, LFC["y"] + 6.45)
SWBOX = {n: B.els[n]["box"] for n in ("REG-FC", "REG-BT", "L-BT")}
SWBOX["L-FC Eaton"] = LFC_E
print("L-FC origin (%.3f, %.3f) Eaton box %s" % (LFC["x"], LFC["y"], tuple(round(v, 3) for v in LFC_E)))
print("switched L1 wires %d, polys %d; layer-16 VSW items %d" % (
    len(SWSEG), len(SWPOLY), sum(1 for w in B.wires if w["net"] in SWN and w["layer"] == "16") +
    sum(1 for p in B.polys if p["net"] in SWN and p["layer"] == "16")))


def d_sw_pt(p):
    d = min(d_rect_pt(b, p) for b in SWBOX.values())
    for a, b, r in SWSEG:
        d = min(d, d_pt_seg(p, a, b) - r)
    for P in SWPOLY:
        if pip(p, P["pts"]):
            return 0.0
        d = min(d, min(d_pt_seg(p, a, b) for a, b in edges(P["pts"])) - P["w"] / 2)
    return d


def d_sw_seg(a, b):
    best = (1e9, None)
    for n, bx in SWBOX.items():
        best = min(best, (d_rect_seg(bx, a, b), n))
    for c, d, r in SWSEG:
        best = min(best, (d_seg_seg(a, b, c, d) - r, "VSW wire"))
    for P in SWPOLY:
        if pip(a, P["pts"]) or pip(b, P["pts"]):
            return (0.0, P["net"] + " poly")
        best = min(best, (min(d_seg_seg(a, b, c, d) for c, d in edges(P["pts"])) - P["w"] / 2, P["net"] + " poly"))
    return best


REWORK = {n: B.els[n]["box"] for n in ("C-D2", "D-FC-EN", "C-D1")}

# ------------------------------------------------------------------ paths (nodes from the output; half-widths)
OD = {"W1": 1.6, "W2": 1.6, "W3": 2.0, "W4": 2.0, "W6a": 1.0, "W6b": 1.0, "W7a": 0.8, "W7b": 0.8, "W7c": 0.8}


def bundle(names):
    ods = [OD[n] for n in names]
    if len(ods) == 1:
        return ods[0] / 2
    return max(max(ods) / 2, 0.575 * math.sqrt(sum(o * o for o in ods)))   # own reading: >= one OD/2


ALL = list(OD)
H_TR = bundle(ALL)
H_W = bundle(["W1", "W2", "W6a", "W6b", "W7a", "W7b", "W7c"])
H_E = bundle(["W3", "W4"])
H_34 = bundle(["W3", "W4"])
H_3467 = bundle(["W3", "W4", "W6a", "W6b", "W7a", "W7b", "W7c"])
H_12 = bundle(["W1", "W2"])
H_7 = bundle(["W7a", "W7b", "W7c"])
H_6 = bundle(["W6a", "W6b"])
RIB = 14 * 0.635 / 2
print("half-widths: trunk %.3f west %.3f east(W3/W4) %.3f (own bundle rule gives max(OD/2,...) = %.3f; calc uses max(OD,...))"
      % (H_TR, H_W, H_E, H_34))
# the calc's own rule max(max OD, ...) for W3/W4 gives 2.00 (one full OD); use 2.00 there to reproduce, report both
H_E_CALC = max(2.0, 0.575 * math.sqrt(8.0))
TR = [(25.80, 62.60), (25.80, 64.50), (25.80, 69.60), (31.00, 69.60), (35.00, 70.80), (36.00, 71.10), (46.00, 71.10),
      (48.00, 71.75), (60.50, 73.50)]
WEST = [(58.00, 76.00), (58.00, 98.044)]
EAST = [(61.00, 85.50), (71.50, 88.00), (77.25, 98.044)]


def mk(head, hhead, tail, htail):
    """nodes with the half-width of the segment that starts at each node."""
    pts = head + TR + tail
    hs = hhead + [H_TR] * (len(TR) - 1) + htail
    return pts, hs


P = {}
P["W1"] = mk([(30.30, 61.20)], [H_12], WEST, [H_W, H_W])
P["W2"] = mk([(27.70, 61.20)], [H_12], WEST, [H_W, H_W])
P["W3"] = mk([(24.30, 45.40), (24.40, 47.00), (24.40, 54.00), (25.80, 57.00), (25.80, 59.20)],
             [1.0, 1.0, 1.0, H_34, H_3467], EAST, [H_E_CALC, H_E_CALC, H_E_CALC])
P["W4"] = mk([(24.30, 55.60), (25.80, 57.00), (25.80, 59.20)], [1.0, H_34, H_3467], EAST, [H_E_CALC] * 3)
P["W6"] = mk([(33.00, 57.50), (33.00, 59.00), (25.80, 59.20)], [H_6, H_6, H_3467], WEST, [H_W, H_W])
P["W7 SCL"] = mk([(27.00, 57.50), (25.80, 59.20)], [H_7, H_3467], WEST, [H_W, H_W])
P["W7 SDA"] = mk([(31.00, 57.50), (31.00, 59.00), (25.80, 59.20)], [H_7, H_7, H_3467], WEST, [H_W, H_W])
W5 = [(40.75, 46.83), (36.00, 46.83), (28.70, 46.83), (28.70, 55.00), (28.70, 73.10), (35.00, 73.10), (42.00, 73.10),
      (44.50, 73.80), (60.50, 73.80), (61.00, 85.80), (71.50, 88.00), (74.75, 98.044)]


def arc(pts):
    s = [0.0]
    for i in range(1, len(pts)):
        s.append(s[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
    return s


def clip(pts, s_from):
    s = arc(pts)
    out = []
    for i in range(len(pts) - 1):
        if s[i + 1] <= s_from:
            continue
        a = pts[i]
        if s[i] < s_from:
            t = (s_from - s[i]) / (s[i + 1] - s[i])
            a = (a[0] + t * (pts[i + 1][0] - a[0]), a[1] + t * (pts[i + 1][1] - a[1]))
        out.append((i, a, pts[i + 1]))
    return out


def round_min(pts, hs, rects, s_from):
    best = (1e9, None)
    for i, a, b in clip(pts, s_from):
        for n, r in rects.items():
            best = min(best, (d_rect_seg(r, a, b) - hs[i], n))
    return best


def ribbon_rects(pts, h, s_from):
    """W5 flat ribbon: axis segments as rectangles (square fold corners; extended by h only at a direction change)."""
    rs = []
    segs = clip(pts, s_from)
    for k, (i, a, b) in enumerate(segs):
        horiz = abs(a[1] - b[1]) < 1e-9
        vert = abs(a[0] - b[0]) < 1e-9
        if not (horiz or vert):
            rs.append(("seg", a, b))
            continue
        x0, x1 = min(a[0], b[0]), max(a[0], b[0])
        y0, y1 = min(a[1], b[1]), max(a[1], b[1])
        # extension at the start: only when the previous segment exists, is not collinear, and this is not a cut end
        prev_turn = k > 0 and i > 0 and s_from < arc(pts)[i] and not (
            (horiz and abs(pts[i - 1][1] - a[1]) < 1e-9) or (vert and abs(pts[i - 1][0] - a[0]) < 1e-9))
        next_turn = i + 2 < len(pts) and not (
            (horiz and abs(pts[i + 2][1] - b[1]) < 1e-9) or (vert and abs(pts[i + 2][0] - b[0]) < 1e-9))
        if horiz:
            y0, y1 = y0 - h, y1 + h
            ea, eb = (h if prev_turn else 0.0), (h if next_turn else 0.0)
            if a[0] <= b[0]:
                x0, x1 = x0 - ea, x1 + eb
            else:
                x0, x1 = x0 - eb, x1 + ea
        else:
            x0, x1 = x0 - h, x1 + h
            ea, eb = (h if prev_turn else 0.0), (h if next_turn else 0.0)
            if a[1] <= b[1]:
                y0, y1 = y0 - ea, y1 + eb
            else:
                y0, y1 = y0 - eb, y1 + ea
        rs.append(("rect", (x0, y0, x1, y1), i))
    return rs


def ribbon_min(rects, s_from, only_cr=False):
    best = (1e9, None)
    for r in ribbon_rects(W5, RIB, s_from):
        for n, q in rects.items():
            if r[0] == "rect":
                R = r[1]
                ov = not (R[2] <= q[0] or q[2] <= R[0] or R[3] <= q[1] or q[3] <= R[1])
                d = -min(R[2] - q[0], q[2] - R[0], R[3] - q[1], q[3] - R[1]) if ov else d_rect_rect(R, q)
            else:
                d = d_rect_seg(q, r[1], r[2]) - RIB
            best = min(best, (d, n))
    return best


print("\n--- per lead: hazards (after the 5 mm bead), tap-field courtyard, switched (whole / from A1), rework")
A1 = (60.50, 73.50)
for ld, (pts, hs) in P.items():
    hz = round_min(pts, hs, HZ, 5.0)
    hz_all = round_min(pts, hs, HZ, 0.0)
    fc = round_min(pts, hs, {"field courtyard": FIELD_CY}, 0.0)
    sw = (1e9, None)
    sw_a1 = (1e9, None)
    ia1 = pts.index(A1)
    for i in range(len(pts) - 1):
        d, n = d_sw_seg(pts[i], pts[i + 1])
        sw = min(sw, (d - hs[i], n))
        if i >= ia1:
            sw_a1 = min(sw_a1, (d - hs[i], n))
    rw = round_min(pts, hs, REWORK, 0.0)
    print("  %-7s hazards %.3f (%s) [incl. bead %.3f %s]; field cy %.3f; switched %.3f (%s), from A1 %.3f; rework %.3f (%s)"
          % (ld, hz[0], hz[1], hz_all[0], hz_all[1], fc[0], sw[0], sw[1], sw_a1[0], rw[0], rw[1]))
# W5 from the J101 region edge x 37.0 (s 3.75)
s5 = 40.75 - 37.0
hz5 = ribbon_min({k: v for k, v in HZ.items() if not k.startswith("IN ")}, s5)
in5 = ribbon_min({k: v for k, v in HZ.items() if k.startswith("IN ")}, 0.0)
in5b = ribbon_min({k: v for k, v in HZ.items() if k.startswith("IN ")}, s5)
fc5 = ribbon_min({"fc": FIELD_CY}, 0.0)
lfc5 = ribbon_min({"L-FC Eaton": LFC_E}, 0.0)
sw5 = min((d_sw_seg(W5[i], W5[i + 1])[0] - RIB, d_sw_seg(W5[i], W5[i + 1])[1]) for i in range(len(W5) - 1))
sw5a = min((d_sw_seg(W5[i], W5[i + 1])[0] - RIB, d_sw_seg(W5[i], W5[i + 1])[1]) for i in range(8, len(W5) - 1))
rw5 = ribbon_min(REWORK, 0.0)
print("  W5      hazards (non-IN, from x 37.0) %.3f (%s); IN strip whole %.3f (%s), from x 37.0 %.3f; field cy %.3f; "
      "L-FC (square ribbon) %.3f; switched round %.3f (%s), from A1 %.3f; rework %.3f (%s)"
      % (hz5[0], hz5[1], in5[0], in5[1], in5b[0], fc5[0], lfc5[0], sw5[0], sw5[1], sw5a[0], rw5[0], rw5[1]))

# ------------------------------------------------------------------ spans
print("\n--- spans between anchors (anchor = bead/base centre on the path; bead end = 5 mm)")
ANCH = {"B1": (25.80, 64.50), "B3": (35.00, 70.80), "A1": A1, "A2": (71.50, 88.00)}
for ld, (pts, hs) in P.items():
    s = arc(pts)
    marks = [("bead end", 5.0)]
    for n, q in ANCH.items():
        if q in pts:
            marks.append((n, s[pts.index(q)]))
    marks.append(("MB edge", s[-1]))
    marks.sort(key=lambda m: m[1])
    marks = [m for m in marks if m[1] >= 5.0]
    sp = ["%s->%s %.1f" % (marks[i][0], marks[i + 1][0], marks[i + 1][1] - marks[i][1]) for i in range(len(marks) - 1)]
    print("  %-7s %s; CR+MB arc %.1f" % (ld, "; ".join(sp), s[-1]))
s = arc(W5)
m5 = [("S1", s[1]), ("S2", s[3]), ("S3", s[5]), ("A1R", s[8]), ("A2", s[10]), ("MB edge", s[-1])]
print("  W5      %s; arc %.1f" % ("; ".join("%s->%s %.1f" % (m5[i][0], m5[i + 1][0], m5[i + 1][1] - m5[i][1])
                                         for i in range(len(m5) - 1)), s[-1]))

# ------------------------------------------------------------------ anchors: zones on the MB
print("\n--- tie-base zones (base + 2 x 1.5 mm tolerance)")
R7 = [(17.70, 34.14), (48.70, 34.14), (48.70, 56.30), (65.00, 56.30), (65.00, 68.30), (48.70, 68.30),
      (48.70, 67.14), (37.56, 67.14), (37.56, 76.00), (18.70, 76.00), (17.70, 75.00)]
for nm, c, side in (("A1", A1, 6.0), ("A2", (71.50, 88.00), 10.0)):
    hz = side / 2 + 1.5
    Z = (c[0] - hz, c[1] - hz, c[0] + hz, c[1] + hz)
    parts = sorted((d_rect_rect(Z, e["box"]), n) for n, e in B.els.items() if n != "CHG")[:3]
    vias = [(v["net"], round(v["x"], 3), round(v["y"], 3)) for v in B.vias
            if d_rect_pt(Z, (v["x"], v["y"])) < v["dia"] / 2]
    nets = set()
    for w in B.wires:
        if w["layer"] == "1" and w["net"] != "GND" and d_rect_seg(Z, w["a"], w["b"]) < w["w"] / 2:
            nets.add(w["net"])
    for p in B.polys:
        if p["layer"] == "1" and p["net"] != "GND":
            if any(inside(Z, q) for q in p["pts"]) or any(pip(q, p["pts"]) for q in rect_poly(Z)) or \
                    min(d_rect_seg(Z, a, b) for a, b in edges(p["pts"])) < p["w"] / 2:
                nets.add(p["net"] + "(poly)")
    cr = any(pip(q, R7) for q in rect_poly(Z)) or min(d_rect_seg(Z, a, b) for a, b in edges(R7)) == 0.0
    dcr = min(d_rect_seg(Z, a, b) for a, b in edges(R7))
    print("  %s zone %s: nearest parts %s; vias %s; non-GND L1 nets %s; touches CR shadow %s (dist %.3f)"
          % (nm, tuple(round(v, 2) for v in Z), [(round(d, 3), n) for d, n in parts], vias, sorted(nets), cr, dcr))

# ------------------------------------------------------------------ MB parts / non-GND vias under each lead off the CR
print("\n--- crossings off the CR (plan envelope)")
allp, allv = set(), set()
for ld, (pts, hs) in list(P.items()) + [("W5", (W5, [RIB] * len(W5)))]:
    ps, vs = set(), set()
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        for n, e in B.els.items():
            if n == "CHG":
                continue
            if d_rect_seg(e["box"], a, b) < hs[i] and not (pip(a, R7) and pip(b, R7)):
                # skip a part that lies under the CR outline entirely
                if not all(pip(q, R7) for q in rect_poly(e["box"])):
                    ps.add(n)
        for v in B.vias:
            if v["net"] != "GND" and d_pt_seg((v["x"], v["y"]), a, b) < hs[i] + v["dia"] / 2 and not pip((v["x"], v["y"]), R7):
                vs.add((v["net"], round(v["x"], 2), round(v["y"], 2)))
    allp |= ps
    allv |= vs
    print("  %-7s parts %s; vias %s" % (ld, sorted(ps), sorted(vs)))
print("  union parts %s; %d non-GND vias" % (sorted(allp), len(allv)))
xs, ys = [], []
for n in allp:
    b = B.els[n]["box"]
    xs += [b[0], b[2]]
    ys += [b[1], b[3]]
for _, x, y in allv:
    xs += [x - 0.378, x + 0.378]
    ys += [y - 0.378, y + 0.378]
print("  strip extent + 2.0: x %.2f-%.2f, y %.2f-%.2f" % (min(xs) - 2, max(xs) + 2, min(ys) - 2, max(ys) + 2))

# ------------------------------------------------------------------ BFS: largest switched clearance, wider domain
print("\n--- BFS feasibility of the 10 mm rule (own raster, hazards at 2 mm + h, tap-field courtyard never over)")


def bfs_best(h, dom, res=0.25):
    x0, y0, x1, y1 = dom
    nx, ny = int(round((x1 - x0) / res)), int(round((y1 - y0) / res))
    ok = bytearray(nx * ny)
    sd = [0.0] * (nx * ny)
    hz = list(HZ.values())
    for j in range(ny):
        y = y0 + (j + 0.5) * res
        for i in range(nx):
            x = x0 + (i + 0.5) * res
            k = j * nx + i
            p = (x, y)
            if min(d_rect_pt(r, p) for r in hz) >= 2.0 + h and d_rect_pt(FIELD_CY, p) >= h:
                ok[k] = 1
            sd[k] = d_sw_pt(p) - h
    i0, j0 = int((25.80 - x0) / res), int((57.00 - y0) / res)

    def reach(D):
        seen = bytearray(nx * ny)
        k0 = j0 * nx + i0
        if not ok[k0]:
            return False
        seen[k0] = 1
        q = deque([k0])
        while q:
            k = q.popleft()
            j, i = divmod(k, nx)
            if y0 + (j + 0.5) * res >= 98.044 - res:
                return True
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ii, jj = i + di, j + dj
                if 0 <= ii < nx and 0 <= jj < ny:
                    kk = jj * nx + ii
                    if not seen[kk] and ok[kk] and sd[kk] >= D:
                        seen[kk] = 1
                        q.append(kk)
        return False
    lo, hi = -10.0, 30.0
    if not reach(lo):
        return None
    for _ in range(14):
        mid = (lo + hi) / 2
        if reach(mid):
            lo = mid
        else:
            hi = mid
    return lo


for dom, lab in (((5.0, 30.0, 80.0, 99.0), "calc domain x 5-80, y 30-99"),
                 ((0.0, 0.0, 131.064, 98.044), "whole MB x 0-131.06, y 0-98.04")):
    for h in (H_TR, 0.5):
        print("  %s, h %.3f: best %.2f mm" % (lab, h, bfs_best(h, dom, res=0.5 if dom[2] > 100 else 0.25)))

# ------------------------------------------------------------------ route lengths (full paths) and maxima
print("\n--- route lengths of the printed full paths")
FULL = {
    "W1": [(30.30, 61.20), (25.80, 62.60), (25.80, 64.50), (25.80, 69.60), (31.00, 69.60), (35.00, 70.80), (36.00, 71.10),
           (46.00, 71.10), (48.00, 71.75), (60.50, 73.50), (58.00, 76.00), (58.00, 98.04), (-0.40, 118.04),
           (-7.80, 168.84), (6.20, 168.84)],
    "W3": [(24.30, 45.40), (24.40, 47.00), (24.40, 54.00), (25.80, 57.00), (25.80, 59.20), (25.80, 62.60), (25.80, 64.50),
           (25.80, 69.60), (31.00, 69.60), (35.00, 70.80), (36.00, 71.10), (46.00, 71.10), (48.00, 71.75), (60.50, 73.50),
           (61.00, 85.50), (71.50, 88.00), (77.25, 98.04), (88.50, 118.04), (93.47, 138.73), (96.09, 142.24),
           (82.09, 142.24)],
    "W5": W5[:-1] + [(74.75, 98.04), (88.50, 138.73), (114.50, 149.65), (114.50, 177.65)],
}
for ld, pts in FULL.items():
    L = arc(pts)[-1]
    print("  %s route %.1f; x1.25 -> %.1f -> ceil10 %d" % (ld, L, 1.25 * L, int(math.ceil(1.25 * L / 10 - 1e-9) * 10)))
