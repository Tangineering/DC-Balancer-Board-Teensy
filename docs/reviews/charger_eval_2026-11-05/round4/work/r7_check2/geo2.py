"""Second independent check of r7_calc revision 2: shared geometry (stdlib only).

The BRD parser of work/r7_check/brdgeo.py is reused; every rule, distance and search below is new code and does not
import r7_calc.py.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "r7_check"))
from brdgeo import Board, d_pt_seg, d_seg_seg, d_poly_poly, pip, rect_poly, edges  # noqa: E402

B = Board()

TABX = (48.70, 56.30, 65.00, 68.30)
TABY_POLY = [(17.70, 67.14), (37.56, 67.14), (37.56, 76.00), (18.70, 76.00), (17.70, 75.00)]
R7 = [(17.70, 34.14), (48.70, 34.14), (48.70, 56.30), (65.00, 56.30), (65.00, 68.30), (48.70, 68.30),
      (48.70, 67.14), (37.56, 67.14), (37.56, 76.00), (18.70, 76.00), (17.70, 75.00)]
FREE_X = [((48.70, 56.30), (65.00, 56.30)), ((65.00, 56.30), (65.00, 68.30)), ((65.00, 68.30), (48.70, 68.30)),
          ((48.70, 68.30), (48.70, 67.14))]
FREE_Y = [((37.56, 67.14), (37.56, 76.00)), ((37.56, 76.00), (18.70, 76.00)), ((18.70, 76.00), (17.70, 75.00)),
          ((17.70, 75.00), (17.70, 67.14))]


def d_rect_pt(R, p):
    dx = max(R[0] - p[0], 0.0, p[0] - R[2])
    dy = max(R[1] - p[1], 0.0, p[1] - R[3])
    return math.hypot(dx, dy)


def seg_hits_rect(R, a, b):
    if R[0] <= a[0] <= R[2] and R[1] <= a[1] <= R[3]:
        return True
    if R[0] <= b[0] <= R[2] and R[1] <= b[1] <= R[3]:
        return True
    return any(d_seg_seg(a, b, c, d) == 0.0 for c, d in edges(rect_poly(R)))


def d_rect_seg(R, a, b):
    if seg_hits_rect(R, a, b):
        return 0.0
    cs = rect_poly(R)
    return min([d_pt_seg(c, a, b) for c in cs] + [d_rect_pt(R, a), d_rect_pt(R, b)])


def d_rect_rect(r1, r2):
    dx = max(r1[0] - r2[2], r2[0] - r1[2], 0.0)
    dy = max(r1[1] - r2[3], r2[1] - r1[3], 0.0)
    return math.hypot(dx, dy)


# ------------------------------------------------------------------ feature list for the D3 rule
FEATS = []   # dict(kind, net, label, geom, r)
for w in B.wires:
    if w["layer"] == "1" and w["net"] != "GND":
        FEATS.append(dict(kind="trace", net=w["net"], r=w["w"] / 2, geom=("seg", w["a"], w["b"]),
                          label="%s L1 trace w%.3f (%.2f,%.2f)-(%.2f,%.2f)" % (w["net"], w["w"], w["a"][0], w["a"][1],
                                                                              w["b"][0], w["b"][1])))
for p in B.polys:
    if p["layer"] == "1" and p["net"] != "GND":
        FEATS.append(dict(kind="poly", net=p["net"], r=p["w"] / 2, geom=("poly", p["pts"]),
                          label="%s L1 polygon w%.3f" % (p["net"], p["w"])))
VIAS = [dict(kind="via", net=v["net"], r=v["dia"] / 2, geom=("pt", (v["x"], v["y"])),
             label="%s via (%.3f,%.3f) d%.4f" % (v["net"], v["x"], v["y"], v["dia"])) for v in B.vias]
for f in VIAS:
    if f["net"] != "GND":
        FEATS.append(f)
for en, e in B.els.items():
    for pn, pd in e["pads"].items():
        net = B.padnet.get((en, pn))
        if net in (None, "GND"):
            continue
        if pd["kind"] == "smd" and pd["layer"] != "1":
            continue
        if pd["kind"] == "smd" or pd.get("shape") == "square":
            FEATS.append(dict(kind="pad", net=net, r=0.0, geom=("poly", rect_poly(pd["bb"])),
                              label="%s pad %s %s %s" % (en, pn, net, "smd" if pd["kind"] == "smd" else "square")))
        else:
            FEATS.append(dict(kind="pad", net=net, r=pd["dia"] / 2, geom=("pt", (pd["x"], pd["y"])),
                              label="%s pad %s %s round d%.3f" % (en, pn, net, pd["dia"])))
PARTS = [(en, e["box"]) for en, e in B.els.items() if en != "CHG"]


def d_rect_feat(R, f):
    g = f["geom"]
    if g[0] == "seg":
        d = d_rect_seg(R, g[1], g[2])
    elif g[0] == "pt":
        d = d_rect_pt(R, g[1])
    else:
        d = d_poly_poly(rect_poly(R), g[1])
    return d - f["r"]


def near(R, feats, pad=6.0):
    out = []
    for f in feats:
        g = f["geom"]
        if g[0] == "seg":
            pts = [g[1], g[2]]
        elif g[0] == "pt":
            pts = [g[1]]
        else:
            pts = g[1]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if max(xs) + f["r"] < R[0] - pad or min(xs) - f["r"] > R[2] + pad or \
           max(ys) + f["r"] < R[1] - pad or min(ys) - f["r"] > R[3] + pad:
            continue
        out.append(f)
    return out


def margins(R, tab, feats=None, vias=None, parts=None):
    """D3 rule margins of the body rectangle R (>= 0 = compliant). Returns a list of (margin, label)."""
    feats = FEATS if feats is None else feats
    vias = VIAS if vias is None else vias
    parts = PARTS if parts is None else parts
    out = []
    # outline: body inside the tab, >= 0.5 mm from the free edges
    if tab == "X":
        T, FREE = TABX, FREE_X
        inside = min(R[0] - T[0], R[1] - T[1], T[2] - R[2], T[3] - R[3])
        out.append((inside, "inside tab X rectangle"))
    else:
        FREE = FREE_Y
        inside = min(R[0] - 17.70, R[1] - 67.14, 37.56 - R[2], 76.00 - R[3])
        out.append((inside, "inside tab Y rectangle (root line y 67.14)"))
        # chamfer: top-left corner must be on the inner side of the chamfer line x - y = -57.3
        cdist = ((R[0] - R[3]) + 57.3) / math.sqrt(2.0)
        out.append((cdist - 0.5, "chamfer inset 0.5"))
    for a, b in FREE:
        out.append((d_rect_seg(R, a, b) - 0.5, "free edge (%.2f,%.2f)-(%.2f,%.2f) 0.5" % (a + b)))
    for f in vias:
        d = d_rect_pt(R, f["geom"][1])
        out.append((d - f["r"], "via pad under body: " + f["label"]))
    for f in feats:
        out.append((d_rect_feat(R, f) - 1.0, "copper 1.0: " + f["label"]))
    for en, bx in parts:
        out.append((d_rect_rect(R, bx) - 1.0, "part box 1.0: " + en))
    return out


def min_margin(R, tab, **kw):
    return min(margins(R, tab, **kw))[0]


def grow(R, gx, gy):
    return (R[0] - gx, R[1] - gy, R[2] + gx, R[3] + gy)


def body(cx, cy, w, h):
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def bisect(fn, lo=0.0, hi=10.0, it=60):
    """largest g in [lo, hi] with fn(g) >= 0, assuming monotone decreasing fn."""
    if fn(lo) < 0:
        return None
    if fn(hi) >= 0:
        return hi
    for _ in range(it):
        m = (lo + hi) / 2
        if fn(m) >= 0:
            lo = m
        else:
            hi = m
    return lo


def tolerances(R, tab, **kw):
    t = bisect(lambda g: min_margin(grow(R, g, g), tab, **kw))
    if t is None:
        return None
    tx = bisect(lambda g: min_margin(grow(R, g, t), tab, **kw), lo=t)
    ty = bisect(lambda g: min_margin(grow(R, t, g), tab, **kw), lo=t)
    return t, tx, ty
