"""Items 1 and 3: corrections E1-E4, T18 position, tab X assignment and the 20-tap sums (own code path)."""
import itertools
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo2 import B, FREE_X, FREE_Y, TABX, d_rect_seg, seg_hits_rect  # noqa: E402
from brdgeo import d_poly_poly, rect_poly, d_pt_seg  # noqa: E402

P = lambda en, pn: (B.els[en]["pads"][pn]["x"], B.els[en]["pads"][pn]["y"])  # noqa: E731
dist = lambda a, b: math.hypot(a[0] - b[0], a[1] - b[1])  # noqa: E731

# ------------------------------------------------------------------ E1 square CHG pads
print("E1: CHG pads (non-GND) as squares, distance to the free edges")
chg = B.els["CHG"]
for pn, pd in sorted(chg["pads"].items(), key=lambda kv: (kv[1]["x"], kv[1]["y"])):
    net = B.padnet.get(("CHG", pn), "(unconnected)")
    if net == "GND":
        continue
    sq = rect_poly(pd["bb"])
    for tab, fe in (("X", FREE_X), ("Y", FREE_Y)):
        d = min(d_poly_poly(sq, [a, b, b]) for a, b in fe)
        if d < 6.0:
            print("   tab %s  %-8s %-14s (%.3f, %.3f) side %.3f shape %-6s: %.3f mm" % (
                tab, pn, net, pd["x"], pd["y"], pd["bb"][2] - pd["bb"][0], pd["shape"], d))

# ------------------------------------------------------------------ E2 per-net union under tab X (0.01 mm)
RES = 0.01
X0, Y0, X1, Y1 = TABX
NX, NY = int(round((X1 - X0) / RES)), int(round((Y1 - Y0) / RES))
shapes = []
for w in B.wires:
    if w["layer"] == "1" and w["net"] != "GND":
        shapes.append((w["net"], "seg", w["a"], w["b"], w["w"] / 2))
for v in B.vias:
    if v["net"] != "GND":
        shapes.append((v["net"], "pt", (v["x"], v["y"]), None, v["dia"] / 2))
cells = {}
for net, kind, a, b, r in shapes:
    pts = [a] + ([b] if b else [])
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    i0, i1 = max(0, int((min(xs) - r - X0) / RES) - 1), min(NX, int((max(xs) + r - X0) / RES) + 2)
    j0, j1 = max(0, int((min(ys) - r - Y0) / RES) - 1), min(NY, int((max(ys) + r - Y0) / RES) + 2)
    if i0 >= i1 or j0 >= j1:
        continue
    s = cells.setdefault(net, set())
    for j in range(j0, j1):
        y = Y0 + (j + 0.5) * RES
        for i in range(i0, i1):
            x = X0 + (i + 0.5) * RES
            dd = d_pt_seg((x, y), a, b) if kind == "seg" else math.hypot(x - a[0], y - a[1])
            if dd <= r:
                s.add((i, j))
# polygons (VBUS, 5V): rim cells inside tab X
for p in B.polys:
    if p["layer"] == "1" and p["net"] != "GND":
        xs = [q[0] for q in p["pts"]]
        if min(xs) - p["w"] / 2 > X1 or max(xs) + p["w"] / 2 < X0:
            continue
        print("   polygon %s may reach tab X (rim x min %.3f)" % (p["net"], min(xs) - p["w"] / 2))
print("\nE2: per-net union under tab X (raster 0.01 mm)")
allc = set()
tot = 0.0
for net in sorted(cells):
    if not cells[net]:
        continue
    a = len(cells[net]) * RES * RES
    tot += a
    allc |= cells[net]
    print("   %-14s %.2f mm2" % (net, a))
print("   sum of per-net unions %.2f mm2; all-net union %.2f mm2" % (tot, len(allc) * RES * RES))

# ------------------------------------------------------------------ E3 SCL trace outside the r7 outline
print("\nE3: SCL L1 trace (47.72,54.32)-(49.53,56.13)")
for w in B.wires:
    if w["net"] == "SCL" and w["layer"] == "1" and abs(w["a"][0] - 47.72) < 0.01 and abs(w["b"][0] - 49.53) < 0.01:
        a, b = w["a"], w["b"]
        # outside part: x > 48.70 (outside the r6 rectangle) and y < 56.30 (below tab X)
        t = (48.70 - a[0]) / (b[0] - a[0])
        c = (48.70, a[1] + t * (b[1] - a[1]))
        print("   exact ends a %s b %s w %.3f; crosses x 48.70 at y %.4f; b.y < 56.30: %s" % (a, b, w["w"], c[1], b[1] < 56.30))
        d = min(d_pt_seg(q, (48.70, 56.30), (65.00, 56.30)) for q in (c, b)) - w["w"] / 2
        print("   outside part (%.2f,%.2f)-(%.3f,%.3f): rim to the tab X low edge %.4f mm" % (c + b + (d,)))

# ------------------------------------------------------------------ taps
MB = {"T1": P("C-D6", "1"), "T7b": P("C-D6", "2"), "T2": P("C-D2", "1"), "T3": P("J1", "39"), "T4": P("J1", "43"),
      "T5": P("J1", "45"), "T6": P("J1", "29"), "T22": P("BAL", "8"), "T8": P("J2", "31"), "T9": P("SNS-BT", "15"),
      "T10": P("J1", "23"), "T11": P("J2", "19"), "T12": P("J2", "47"), "T13": P("J2", "45"), "T14": P("J2", "21"),
      "T15": P("J2", "07"), "T16": P("J2", "43"), "T17": P("J2", "09"), "T17r": P("J2", "29"), "T20": P("ROS", "2"),
      "T21": P("J2", "11"), "T18": P("CO-5V", "1"), "T19": P("J2", "33"), "F24": P("J1", "07")}
R7PAD = {"T1": (50.80, 58.94), "T7b": (53.34, 58.94), "T2": (58.42, 66.56), "T3": (55.88, 61.48),
         "T4": (58.42, 58.94), "T5": (55.88, 58.94), "T6": (53.34, 61.48), "T22": (26.44, 35.80),
         "T8": (28.98, 35.80), "T9": (31.52, 35.80), "T10": (63.50, 64.02), "T11": (58.42, 64.02),
         "T12": (60.96, 58.94), "T13": (63.50, 58.94), "T14": (63.50, 61.48), "T15": (55.88, 66.56),
         "T16": (58.42, 61.48), "T17": (60.96, 66.56), "T17r": (60.96, 64.02), "T20": (55.88, 64.02),
         "T21": (63.50, 66.56), "T18": (41.68, 40.88), "T19": (60.96, 61.48), "F24": (53.34, 66.56)}
SUM20 = ["T1", "T2", "T3", "T4", "T5", "T6", "T22", "T8", "T9", "T10", "T11", "T12", "T13", "T14", "T15", "T16",
         "T17", "T17r", "T20", "T21"]
REG = B.els["REG-5V"]["box"]
print("\nT18: CO-5V pad 1 %s; REG-5V box %s" % (tuple(round(v, 3) for v in MB["T18"]), tuple(round(v, 3) for v in REG)))
hdr = sorted(((pn, pd["x"], pd["y"]) for pn, pd in B.els["CHG"]["pads"].items() if abs(pd["x"] - 45.998) < 0.01),
             key=lambda q: q[2])
for k, y in ((4, 35.80), (5, 35.80), (6, 35.80), (7, 35.80), (7, 38.34), (7, 40.88), (6, 40.88), (6, 38.34)):
    p = (23.90 + k * 2.54, y)
    L = dist(p, MB["T18"])
    hit = seg_hits_rect(REG, p, MB["T18"])
    dreg = d_rect_seg(REG, p, MB["T18"])
    posts = [pn for pn, x, yy in hdr if d_pt_seg((x, yy), p, MB["T18"]) < 0.32 + 0.0]
    posts_pad = [pn for pn, x, yy in hdr if d_pt_seg((x, yy), p, MB["T18"]) < 0.825]
    print("   k %d (%.2f, %.2f): straight %.3f mm; crosses REG-5V %s (clearance %.3f); over post %s, over pad square %s" % (
        k, p[0], p[1], L, hit, dreg, posts, posts_pad))
print("   1x10 column pads (name, x, y):", [(pn, round(y, 3), B.padnet.get(("CHG", pn))) for pn, x, y in hdr])

# assignment
pos = list(R7PAD[k] for k in R7PAD if R7PAD[k][0] > 48.7)
print("\nTab X pads: %d, unique %s" % (len(pos), len(set(pos)) == len(pos)))
GX = [50.80, 53.34, 55.88, 58.42, 60.96, 63.50]
GY = [58.94, 61.48, 64.02, 66.56]
R175 = [(50.80, 61.48), (50.80, 64.02)]
occupied = set(pos) | set(R175)
free = [(x, y) for x in GX for y in GY if (x, y) not in occupied]
print("   R175 positions %s; free grid positions (spares) %s" % (R175, free))
adj = lambda a, b: abs(dist(a, b) - 2.54) < 1e-6  # noqa: E731
print("   T1/T7b adjacent %s; T17/T17r adjacent %s; T6 adjacent to R175 %s" % (
    adj(R7PAD["T1"], R7PAD["T7b"]), adj(R7PAD["T17"], R7PAD["T17r"]), any(adj(R7PAD["T6"], q) for q in R175)))
R6C = (23.90 + 3.5 * 2.54, 38.34)
R6RES = {"T22": (26.44, 35.80), "T8": (28.98, 35.80), "T9": (31.52, 35.80)}
s6 = sum(dist(R6RES.get(t, R6C), MB[t]) for t in SUM20)
s6c = sum(dist(R6C, MB[t]) for t in SUM20)
s6f = sum(dist(R6RES[t] if t == "T22" else R6C, MB[t]) for t in SUM20)
s7 = sum(dist(R7PAD[t], MB[t]) for t in SUM20)


def dressed(t):
    p = R7PAD[t]
    if p[0] > 48.7 and seg_hits_rect(REG, p, MB[t]):
        q = (63.50, p[1])
        return dist(p, q) + dist(q, MB[t])
    return dist(p, MB[t])


s7d = sum(dressed(t) for t in SUM20)
print("   r6 sum (F08-F10 on r6 pads) %.1f; r6 only F08 held %.1f; r6 all centre %.1f; r7 straight %.1f (%.1f %%), dressed %.1f" % (
    s6, s6f, s6c, s7, (s7 / s6 - 1) * 100, s7d))
print("   r7 vs only-F08 r6 basis %.1f %%; T22/T8/T9 r6 = r7: %s" % (
    (s7 / s6f - 1) * 100, [round(dist(R6RES[t], MB[t]), 1) for t in ("T22", "T8", "T9")]))
for t in ("T1", "T7b", "T5", "T6"):
    print("   %s at %s: straight %.2f, crosses REG-5V %s, dressed %.2f" % (
        t, R7PAD[t], dist(R7PAD[t], MB[t]), seg_hits_rect(REG, R7PAD[t], MB[t]), dressed(t)))

# constrained optimum (exhaustive over pair placements; min-cost matching for the rest by brute-force Hungarian)
def hungarian(cost):
    n, m = len(cost), len(cost[0])
    INF = float("inf")
    u, v, p, way = [0.0] * (n + 1), [0.0] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    res = 0.0
    for j in range(1, m + 1):
        if p[j]:
            res += cost[p[j] - 1][j - 1]
    return res


TABXSET = [t for t in R7PAD if R7PAD[t][0] > 48.7]
grid = [(x, y) for x in GX for y in GY if (x, y) not in R175]
W = lambda t: 1.0 if t in SUM20 else 0.0  # noqa: E731  (objective: the 20-tap sum; options cost nothing)
W2 = lambda t: 1.0  # noqa: E731                         (objective: every tab X pad)
for nm, wf in (("20-tap sum", W), ("all tab X pads", W2)):
    best = None
    rest = [t for t in TABXSET if t not in ("T1", "T7b", "T17", "T17r", "T6")]
    for p6 in [q for q in grid if any(adj(q, r) for r in R175)]:
        for a1, a2 in itertools.permutations(grid, 2):
            if not adj(a1, a2) or p6 in (a1, a2):
                continue
            base1 = wf("T1") * dist(a1, MB["T1"]) + wf("T7b") * dist(a2, MB["T7b"])
            for b1, b2 in itertools.permutations(grid, 2):
                if not adj(b1, b2) or len({p6, a1, a2, b1, b2}) < 5:
                    continue
                base = base1 + wf("T17") * dist(b1, MB["T17"]) + wf("T17r") * dist(b2, MB["T17r"]) + wf("T6") * dist(p6, MB["T6"])
                if best is not None and base > best[0]:
                    continue
                left = [q for q in grid if q not in (p6, a1, a2, b1, b2)]
                c = [[wf(t) * dist(q, MB[t]) for q in left] for t in rest]
                tot = base + hungarian(c)
                if best is None or tot < best[0] - 1e-9:
                    best = (tot, p6, a1, a2, b1, b2)
    print("   constrained optimum (%s objective, R175 rows 2-3 col 1): %.2f; T6 %s, T1/T7b %s/%s, T17/T17r %s/%s" % (
        (nm,) + best))
    if nm == "20-tap sum":
        print("      (calc assignment 20-tap tab X part: %.2f)" % sum(dist(R7PAD[t], MB[t]) for t in SUM20 if R7PAD[t][0] > 48.7))
    else:
        print("      (calc assignment all-pad tab X: %.2f)" % sum(dist(R7PAD[t], MB[t]) for t in TABXSET))
