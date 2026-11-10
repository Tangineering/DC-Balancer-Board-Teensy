"""Third independent check (r7_calc revision 3): FT1 exact centre, FT2 at (28.00, 73.25), T18 low row, tab X/Y bottom area.

Uses the BRD parser (r7_check/brdgeo.py) and the D3 margin helper (r7_check2/geo2.py); does not import r7_calc.py.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "r7_check2"))
sys.path.insert(0, os.path.join(HERE, "..", "r7_check"))
from geo2 import (B, FEATS, VIAS, PARTS, margins, min_margin, grow, body, tolerances, near, d_rect_rect,  # noqa: E402
                  d_rect_seg, d_rect_pt, seg_hits_rect, FREE_X)
from brdgeo import d_pt_seg  # noqa: E402

ZX = (44.0, 52.0, 70.0, 73.0)
ZY = (12.0, 60.0, 43.0, 82.0)
KX = dict(feats=near(ZX, FEATS, 0.0), vias=near(ZX, VIAS, 0.0))
KY = dict(feats=near(ZY, FEATS, 0.0), vias=near(ZY, VIAS, 0.0))

# ---------------------------------------------------------------- FT1: exact max-min y at x 61.72 (golden section)
def t_of(cx, cy, w, h):
    tol = tolerances(body(cx, cy, w, h), "X", **KX)
    return tol[0] if tol else -1.0


def golden(f, lo, hi, it=60):
    g = (math.sqrt(5) - 1) / 2
    a, b = lo, hi
    c, d = b - g * (b - a), a + g * (b - a)
    fc, fd = f(c), f(d)
    for _ in range(it):
        if fc > fd:
            b, d, fd = d, c, fc
            c = b - g * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + g * (b - a)
            fd = f(d)
    return (a + b) / 2


print("FT1")
for w, h, cx in ((4.0, 1.6, 61.72), (4.0, 1.7, 61.76), (3.8, 1.7, 61.86)):
    yb = golden(lambda y: t_of(cx, y, w, h), 66.60, 66.80)
    R = body(cx, yb, w, h)
    t, tx, ty = tolerances(R, "X", **KX)
    ms = sorted(margins(R, "X", **KX))
    cop = min((m + 1.0, l) for m, l in ms if l.startswith("copper"))
    print("  %.1f x %.1f at x %.2f: best y %.5f; t %.4f tx %.4f ty %.4f; body y %.4f-%.4f; binding %s; nearest copper %.4f (%s)"
          % (w, h, cx, yb, t, tx, ty, R[1], R[3], ms[0][1], cop[0], cop[1]))
    if (w, h) == (4.0, 1.6):
        for yy in (66.70, 66.705):
            print("    at y %.3f: t %.4f" % (yy, t_of(cx, yy, w, h)))
        R5 = body(cx, 66.705, w, h)
        print("    keep-out at y 66.705: x %.3f-%.3f y %.3f-%.3f" % (R5[0] - 0.5, R5[2] + 0.5, R5[1] - 0.5, R5[3] + 0.5))
        # 5V copper distance (H.23(h)): nearest 5V feature to the body
        d5 = min(m + 1.0 for m, l in margins(R5, "X", feats=[f for f in FEATS if f["net"] == "5V"], vias=[], parts=[])
                 if l.startswith("copper"))
        print("    nearest 5V copper rim to the body %.4f mm" % d5)
        # fallback cut-out = keep-out rectangle: nearest non-GND rim outside it
        K = grow(R5, 0.5, 0.5)
        dk = min((m + 1.0, l) for m, l in margins(K, "X", **KX) if l.startswith("copper"))
        print("    cut-out (keep-out) nearest non-GND rim %.4f (%s)" % dk)
    if (w, h) == (4.0, 1.7):
        # scan x too
        best = None
        for i in range(-10, 11):
            x = 61.76 + 0.01 * i
            v = t_of(x, yb, w, h)
            if best is None or v > best[0]:
                best = (v, x)
        print("    x scan at y %.4f: best t %.4f at x %.2f" % (yb, best[0], best[1]))

# ---------------------------------------------------------------- FT2 at (28.00, 73.25)
print("\nFT2")
for cy in (73.25, 71.32):
    R = body(28.00, cy, 4.0, 4.0)
    ms = sorted(margins(R, "Y", **KY))
    print("  (28.00, %.2f): body y %.3f-%.3f; zero-move margin %.4f (%s)" % (cy, R[1], R[3], ms[0][0], ms[0][1]))
    for m, l in ms[:4]:
        print("     %+.4f %s" % (m, l))
    t, tx, ty = tolerances(R, "Y", **KY)
    print("     t %.4f tx %.4f ty %.4f; lever a %.3f" % (t, tx, ty, cy - 64.484))
    sl = {}
    for lab, dx, dy in (("+x", 1, 0), ("-x", -1, 0), ("+y", 0, 1), ("-y", 0, -1)):
        f = lambda g: min_margin((R[0] + dx * g, R[1] + dy * g, R[2] + dx * g, R[3] + dy * g), "Y", **KY)  # noqa
        lo, hi = 0.0, 20.0
        for _ in range(60):
            m = (lo + hi) / 2
            if f(m) >= 0:
                lo = m
            else:
                hi = m
        sl[lab] = lo
    print("     one-sided slack " + ", ".join("%s %.3f" % kv for kv in sl.items()))
    print("     nearest part box %.3f %s" % min((d_rect_rect(R, bx), en) for en, bx in PARTS))
    cop = [(m + 1.0, l) for m, l in margins(R, "Y", **KY) if l.startswith("copper")]
    print("     nearest non-GND copper rim %s" % (str(min(cop)) if cop else "none in zone"))
    vu = [l for m, l in margins(R, "Y", **KY) if l.startswith("via") and m < 0]
    print("     vias under body: %s" % vu)
# largest lever with t >= 0.25 (y scan)
lo, hi = 71.32, 74.0
for _ in range(60):
    m = (lo + hi) / 2
    tt = tolerances(body(28.0, m, 4.0, 4.0), "Y", **KY)
    if tt and tt[0] >= 0.25:
        lo = m
    else:
        hi = m
print("  largest centre y with t >= 0.25 at x 28.00: %.5f (a %.4f)" % (lo, lo - 64.484))

# ---------------------------------------------------------------- T18 low row
print("\nT18")
co = B.els["CO-5V"]["pads"]["1"]
P1 = (co["x"], co["y"])
REG = B.els["REG-5V"]["box"]
print("  CO-5V pad 1 %s, REG-5V box %s, pad-centre to box %.4f" % (P1, REG, d_rect_pt(REG, P1)))
print("  CO-5V pad 1 detail: %s" % {k: co[k] for k in co if k != "bb"})
hdr = sorted(((pn, pd["x"], pd["y"], pd) for pn, pd in B.els["CHG"]["pads"].items()), key=lambda q: (q[1], q[2]))
for k in (4, 5, 6, 7):
    p = (23.90 + k * 2.54, 35.80)
    L = math.hypot(p[0] - P1[0], p[1] - P1[1])
    near_posts = sorted((d_pt_seg((x, y), p, P1), pn, x, y) for pn, x, y, pd in hdr)[:2]
    s = []
    for dc, pn, x, y in near_posts:
        sq = (x - 0.32, y - 0.32, x + 0.32, y + 0.32)
        s.append("pin %s (%.3f,%.3f): centre %.3f, square %.3f" % (pn, x, y, dc, d_rect_seg(sq, p, P1)))
    print("  k %d (%.2f, %.2f): length %.3f; REG-5V clearance %.4f (hit %s); %s" % (
        k, p[0], p[1], L, d_rect_seg(REG, p, P1), seg_hits_rect(REG, p, P1), "; ".join(s)))
pin1 = [q for q in hdr if q[0] == "1"]
print("  CHG pin 1:", [(q[0], q[1], q[2], q[3].get("dia"), q[3].get("shape")) for q in pin1])
print("  old tab X position (41.68, 40.88): length %.3f" % math.hypot(41.68 - P1[0], 40.88 - P1[1]))

# ---------------------------------------------------------------- tab X / tab Y bottom area (raster 0.05)
print("\nBottom area")
RES = 0.05
feats_all = [f for f in FEATS] + []
FT1K = (59.22, 65.405, 64.22, 68.005)
FT1L = (59.22, 68.005, 64.22, 68.30)
FT2K = (25.5, 70.75, 30.5, 75.75)


def rim_ok(x, y, fl):
    for f in fl:
        g = f["geom"]
        if g[0] == "seg":
            d = d_pt_seg((x, y), g[1], g[2])
        elif g[0] == "pt":
            d = math.hypot(x - g[1][0], y - g[1][1])
        else:
            pts = g[1]
            d = min(d_pt_seg((x, y), pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts)))
            # inside polygon counts as copper
            ins = False
            n = len(pts)
            for i in range(n):
                (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % n]
                if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                    ins = not ins
            if ins:
                d = 0.0
        if d - f["r"] < 1.0:
            return False
    return True


def in_rect(x, y, R):
    return R[0] <= x <= R[2] and R[1] <= y <= R[3]


# tab X
fx = near((48.7, 56.3, 65.0, 68.3), FEATS, 2.0)
px = [bx for en, bx in PARTS if d_rect_rect(bx, (48.7, 56.3, 65.0, 68.3)) < 1.5]
cnt = cnt_nf = 0
nx, ny = int(round((65.0 - 48.7) / RES)), int(round((68.3 - 56.3) / RES))
for i in range(nx):
    x = 48.7 + (i + 0.5) * RES
    for j in range(ny):
        y = 56.3 + (j + 0.5) * RES
        if any(d_pt_seg((x, y), a, b) < 0.5 for a, b in FREE_X):
            continue
        if any(d_rect_pt(bx, (x, y)) < 1.0 for bx in px):
            continue
        if not rim_ok(x, y, fx):
            continue
        cnt_nf += 1
        if in_rect(x, y, FT1K) or in_rect(x, y, FT1L):
            continue
        cnt += 1
print("  tab X: before keep-outs %.2f mm2, after FT1 keep-out + lane %.2f mm2 (removed %.2f)" % (
    cnt_nf * RES * RES, cnt * RES * RES, (cnt_nf - cnt) * RES * RES))
# tab Y: inset region (x >= 18.20, x <= 37.06, y <= 75.50, chamfer inset), y > 67.14; no copper, check part boxes
fy = near((17.7, 67.14, 37.56, 76.0), FEATS, 2.0)
py_ = [bx for en, bx in PARTS if d_rect_rect(bx, (17.7, 67.14, 37.56, 76.0)) < 1.5]
print("  tab Y: copper feats within 2 mm %d, part boxes within 1.5 mm %s" % (len(fy), py_))
RES2 = 0.01
c0 = c1 = 0
for i in range(int(round((37.56 - 17.70) / RES2))):
    x = 17.70 + (i + 0.5) * RES2
    for j in range(int(round((76.0 - 67.14) / RES2))):
        y = 67.14 + (j + 0.5) * RES2
        if x < 18.20 or x > 37.06 or y > 75.50:
            continue
        if ((x - y) + 57.3) / math.sqrt(2.0) < 0.5:
            continue
        if any(d_rect_pt(bx, (x, y)) < 1.0 for bx in py_):
            continue
        if not rim_ok(x, y, fy):
            continue
        c0 += 1
        if in_rect(x, y, FT2K):
            continue
        c1 += 1
print("  tab Y: before keep-out %.3f mm2, after FT2 keep-out %.3f mm2 (removed %.3f); analytic removal 5.0 x (75.50 - 70.75) = %.3f"
      % (c0 * RES2 ** 2, c1 * RES2 ** 2, (c0 - c1) * RES2 ** 2, 5.0 * (75.50 - 70.75)))
