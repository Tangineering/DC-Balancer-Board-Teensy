"""Negotiated-congestion (PathFinder) router for the signal nets of a board dump (finish_dump.py format).

Every routable net (not GND/plane, not a pour net, not in --keep) is routed pad to pad on a grid over the routing
layers. Overlap with other nets' routed copper is allowed but costs a present-congestion term; cells that stay
contested gain a history cost. Nets in conflict are ripped up and rerouted until no conflict remains or the
iteration limit is reached. Pads, holes, keep-outs, pours and the copper of kept nets are hard obstacles.
Clearance model on the grid: two track centrelines of different nets stay >= track + clearance apart; a via
centre stays >= via/2 + clearance + track/2 from another net's centreline and >= via + clearance from another
net's via. Usage:
  python pathfinder.py <dump.json> <out.json> --res 0.1 --clear 0.16 --track 0.16 --via 0.6 --drill 0.3
         --plane-net /GND --keep /GND,/VCHGIN,... --iters 30"""
import argparse
import heapq
import json
import math
import random
import time

import numpy as np
import shapely
from shapely.geometry import Polygon, Point, LineString

ap = argparse.ArgumentParser()
ap.add_argument("dump")
ap.add_argument("out")
ap.add_argument("--res", type=float, default=0.1)
ap.add_argument("--clear", type=float, default=0.16)
ap.add_argument("--track", type=float, default=0.16)
ap.add_argument("--via", type=float, default=0.6)
ap.add_argument("--drill", type=float, default=0.3)
ap.add_argument("--plane-net", default=None)
ap.add_argument("--keep", default="")
ap.add_argument("--iters", type=int, default=30)
ap.add_argument("--via-cost", type=float, default=10.0)
ap.add_argument("--margin", type=float, default=4.0, help="search window margin around a net's pads, mm")
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--pour-penalty", type=float, default=30.0, help="cost per cell inside another net's power pour")
A = ap.parse_args()
random.seed(A.seed)
t0 = time.time()

D = json.load(open(A.dump))
LAYERS = D["layers"]
NL = len(LAYERS)
bx0, by0, bx1, by1 = D["bbox"]
R = A.res
nx, ny = int(math.ceil((bx1 - bx0) / R)) + 1, int(math.ceil((by1 - by0) / R)) + 1
X, Y = np.meshgrid(bx0 + np.arange(nx) * R, by0 + np.arange(ny) * R)
FREE, BLOCK = -1, -2
KEEP = {x for x in A.keep.split(",") if x} | {it["net"] for it in D["items"] if it["kind"] == "zone"}
if A.plane_net:
    KEEP.add(A.plane_net)
nets = {}


def nid(name):
    if not name:
        return BLOCK
    if name not in nets:
        nets[name] = len(nets)
    return nets[name]


def geom_of(it, extra=0.0):
    if "poly" in it:
        g = Polygon(it["poly"], it.get("holes") or None).buffer(0)
    elif "seg" in it:
        xa, ya, xb, yb, w = it["seg"]
        g = LineString([(xa, ya), (xb, yb)]).buffer(w / 2) if (xa, ya) != (xb, yb) else Point(xa, ya).buffer(w / 2)
    else:
        cx, cy, r = it["circ"]
        g = Point(cx, cy).buffer(r)
    return g.buffer(extra) if extra else g


def window(g):
    gx0, gy0, gx1, gy1 = g.bounds
    i0, i1 = max(int((gx0 - bx0) / R) - 1, 0), min(int((gx1 - bx0) / R) + 2, nx)
    j0, j1 = max(int((gy0 - by0) / R) - 1, 0), min(int((gy1 - by0) / R) + 2, ny)
    return i0, i1, j0, j1


# ---------------------------------------------------------------- hard obstacles
rT = A.clear + A.track / 2 + R * 0.5            # fixed copper -> track centreline
rV = A.clear + A.via / 2 + R * 0.5              # fixed copper -> via centre
ownT = np.full((NL, ny, nx), FREE, np.int32)
ownV = np.full((NL, ny, nx), FREE, np.int32)


def claim(arr, li, g, n):
    i0, i1, j0, j1 = window(g)
    if i0 >= i1 or j0 >= j1:
        return
    m = shapely.contains_xy(g, X[j0:j1, i0:i1], Y[j0:j1, i0:i1])
    sub = arr[li, j0:j1, i0:i1]
    if n == BLOCK:
        sub[m] = BLOCK
    else:
        sub[m & (sub == FREE)] = n
        sub[m & (sub != n) & (sub != FREE)] = BLOCK


ROUTABLE = set()
for it in D["items"]:
    if it["kind"] in ("track", "via") and it["net"] not in KEEP and not it.get("locked"):
        ROUTABLE.add(it["net"])          # existing unlocked routing of these nets is replaced
    if it["kind"] == "pad" and it["net"] and it["net"] not in KEEP and not it["net"].startswith("unconnected"):
        ROUTABLE.add(it["net"])
pourN = np.full((NL, ny, nx), FREE, np.int32)   # power pours: a penalty for other nets, not a block
for it in D["items"]:
    if it["kind"] in ("track", "via") and it["net"] in ROUTABLE and not it.get("locked"):
        continue
    if it["kind"] == "zone" and it.get("soft"):
        continue
    if it["kind"] == "zone":
        for ln in it["layers"]:
            claim(pourN, LAYERS.index(ln), geom_of(it, rT), nid(it["net"]))
        continue
    n = BLOCK if it["kind"] == "keepout" else nid(it["net"])
    for ln in it["layers"]:
        li = LAYERS.index(ln)
        if it["kind"] == "keepout":
            g = geom_of(it)
            claim(ownT, li, g.buffer(A.track / 2), BLOCK)
            claim(ownV, li, g.buffer(A.via / 2), BLOCK)
        else:
            claim(ownT, li, geom_of(it, rT), n)
            claim(ownV, li, geom_of(it, rV), n)
print("hard obstacles rasterised: %.1f s, routable nets %d" % (time.time() - t0, len(ROUTABLE)), flush=True)

# ---------------------------------------------------------------- dynamic occupancy (other nets' routes)
def disk(r):
    k = int(math.ceil(r / R))
    return [(dj, di) for dj in range(-k, k + 1) for di in range(-k, k + 1) if math.hypot(dj, di) * R <= r + 1e-9]


DT_T = disk(A.track + A.clear + R * 0.5)                          # track vs track
DT_V = disk(A.via / 2 + A.clear + A.track / 2 + R * 0.5)          # track vs via
DV_V = disk(A.via + A.clear + R * 0.5)                            # via vs via
occT = np.zeros((NL, ny, nx), np.float32)    # cost to put a centreline here (others' copper nearby)
occV = np.zeros((NL, ny, nx), np.float32)    # cost to put a via here
hist = np.zeros((NL, ny, nx), np.float32)


def stamp(arr, l, j, i, offs, val):
    for dj, di in offs:
        jj, ii = j + dj, i + di
        if 0 <= jj < ny and 0 <= ii < nx:
            arr[l, jj, ii] += val


OWN = {}   # net -> set of its own pad cells: copper inside a pad is never a conflict (pads are hard obstacles)


def contribute(net, route, val):
    cells, vias = route
    own = OWN.get(net, ())
    for (l, j, i) in cells:
        if (l, j, i) in own:
            continue
        stamp(occT, l, j, i, DT_T, val)
        stamp(occV, l, j, i, DT_V, val)
    for (j, i) in vias:
        for l in range(NL):
            stamp(occT, l, j, i, DT_V, val)
            stamp(occV, l, j, i, DV_V, val)


# ---------------------------------------------------------------- per-net pads
pads_of = {}
for it in D["items"]:
    if it["kind"] == "pad" and it["net"] in ROUTABLE:
        pads_of.setdefault(it["net"], {}).setdefault((it.get("ref"), it.get("num")), []).append(it)


def cells_of(it):
    g = geom_of(it)
    i0, i1, j0, j1 = window(g)
    m = shapely.contains_xy(g, X[j0:j1, i0:i1], Y[j0:j1, i0:i1])
    jj, ii = np.nonzero(m)
    if len(jj) == 0:
        c = g.centroid
        jj, ii = np.array([int(round((c.y - by0) / R)) - j0]), np.array([int(round((c.x - bx0) / R)) - i0])
    out = []
    for ln in it["layers"]:
        li = LAYERS.index(ln)
        out += [(li, j + j0, i + i0) for j, i in zip(jj, ii)]
    return out


for it in D["items"]:
    if it["kind"] in ("track", "via") and it.get("locked") and it["net"] in ROUTABLE:
        pads_of.setdefault(it["net"], {})[("locked", id(it))] = [it]
PADCELLS = {net: [[c for it in grp for c in cells_of(it)] for grp in groups.values()]
            for net, groups in pads_of.items()}
for _net, _groups in pads_of.items():
    OWN[_net] = {c for k, grp in _groups.items() if k[0] != "locked" for it in grp for c in cells_of(it)}

SQ2 = math.sqrt(2)
NB = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, SQ2), (1, -1, SQ2), (-1, 1, SQ2), (-1, -1, SQ2)]
PRES = 1.0


def route_net(net):
    n = nid(net)
    groups = PADCELLS.get(net, [])
    if len(groups) < 2:
        return ([], []), True
    allc = [c for g in groups for c in g]
    j0 = max(min(c[1] for c in allc) - int(A.margin / R), 0)
    j1 = min(max(c[1] for c in allc) + int(A.margin / R) + 1, ny)
    i0 = max(min(c[2] for c in allc) - int(A.margin / R), 0)
    i1 = min(max(c[2] for c in allc) + int(A.margin / R) + 1, nx)
    W, H = i1 - i0, j1 - j0
    passT = (ownT[:, j0:j1, i0:i1] == FREE) | (ownT[:, j0:j1, i0:i1] == n)
    passV = np.all((ownV[:, j0:j1, i0:i1] == FREE) | (ownV[:, j0:j1, i0:i1] == n), axis=0)
    pn = pourN[:, j0:j1, i0:i1]
    costT = ((1.0 + hist[:, j0:j1, i0:i1]) * (1.0 + PRES * occT[:, j0:j1, i0:i1])
             + np.where((pn != FREE) & (pn != n), A.pour_penalty, 0.0))
    costT = np.where(passT, costT, np.inf).astype(np.float64)
    costV = (A.via_cost * (1.0 + hist[:, j0:j1, i0:i1].max(axis=0)) * (1.0 + PRES * occV[:, j0:j1, i0:i1].max(axis=0)))
    costV = np.where(passV, costV, np.inf).astype(np.float64)
    cT = [costT[l].ravel().tolist() for l in range(NL)]
    cV = costV.ravel().tolist()
    order = sorted(range(len(groups)), key=lambda k: -len(groups[k]))
    tree = set((l, j - j0, i - i0) for (l, j, i) in groups[order[0]])
    rest = [set((l, j - j0, i - i0) for (l, j, i) in groups[k]) for k in order[1:]]
    cells, vias = [], []
    ok = True
    while rest:
        # connect the pad group nearest to the tree
        tj = sum(c[1] for c in tree) / len(tree)
        ti = sum(c[2] for c in tree) / len(tree)
        rest.sort(key=lambda g: min(math.hypot(c[1] - tj, c[2] - ti) for c in list(g)[:4]))
        tgt = rest.pop(0)
        cy_ = sum(c[1] for c in tgt) / len(tgt)
        cx_ = sum(c[2] for c in tgt) / len(tgt)
        rad = max(math.hypot(c[1] - cy_, c[2] - cx_) for c in tgt)
        g = {}
        prev = {}
        pq = []
        for s in tree:
            g[s] = 0.0
            prev[s] = None
            heapq.heappush(pq, (max(0.0, math.hypot(s[1] - cy_, s[2] - cx_) - rad), 0.0, s))
        found = None
        while pq:
            f, gc, s = heapq.heappop(pq)
            if gc > g.get(s, 1e30):
                continue
            if s in tgt:
                found = s
                break
            l, j, i = s
            row = cT[l]
            for dj, di, c in NB:
                jj, ii = j + dj, i + di
                if not (0 <= jj < H and 0 <= ii < W):
                    continue
                t = (l, jj, ii)
                cost = row[jj * W + ii]
                if cost == math.inf:
                    if t not in tgt:
                        continue
                    cost = 1.0
                if dj and di and (row[j * W + ii] == math.inf or row[jj * W + i] == math.inf):
                    continue
                nc = gc + c * cost
                if nc < g.get(t, 1e30):
                    g[t] = nc
                    prev[t] = s
                    heapq.heappush(pq, (nc + max(0.0, math.hypot(jj - cy_, ii - cx_) - rad), nc, t))
            vc = cV[j * W + i]
            if vc != math.inf:
                for l2 in range(NL):
                    if l2 == l:
                        continue
                    t = (l2, j, i)
                    if cT[l2][j * W + i] == math.inf:
                        continue
                    nc = gc + vc
                    if nc < g.get(t, 1e30):
                        g[t] = nc
                        prev[t] = s
                        heapq.heappush(pq, (nc + max(0.0, math.hypot(j - cy_, i - cx_) - rad), nc, t))
        if found is None:
            ok = False
            tree |= tgt
            continue
        path = [found]
        while prev[path[-1]] is not None:
            path.append(prev[path[-1]])
        path.reverse()
        for a, b2 in zip(path[:-1], path[1:]):
            if a[0] != b2[0]:
                vias.append((a[1] + j0, a[2] + i0))
        cells += [(l, j + j0, i + i0) for (l, j, i) in path]
        tree |= set(path) | tgt
    return (cells, vias), ok


def conflicts(net, route):
    cells, vias = route
    own = OWN.get(net, ())
    c = 0.0
    for (l, j, i) in cells:
        if (l, j, i) in own:
            continue
        c += occT[l, j, i]
    for (j, i) in vias:
        c += max(occV[l, j, i] for l in range(NL))
    return c


routes = {}
order = sorted(ROUTABLE, key=lambda net: len(PADCELLS.get(net, [])))
failed = set()
for it_ in range(A.iters):
    todo = order if it_ == 0 else [n_ for n_ in order if n_ in bad]
    random.shuffle(todo) if it_ > 0 else None
    for net in todo:
        if net in routes:
            contribute(net, routes[net], -1.0)
        r, ok = route_net(net)
        routes[net] = r
        contribute(net, r, +1.0)
        if not ok:
            failed.add(net)
        else:
            failed.discard(net)
    # conflicts: a net whose cells see other nets' occupancy
    bad = set()
    for net, r in routes.items():
        contribute(net, r, -1.0)
        c = conflicts(net, r)
        if c > 0:
            bad.add(net)
            own = OWN.get(net, ())
            for (l, j, i) in r[0]:
                if occT[l, j, i] > 0 and (l, j, i) not in own:
                    hist[l, j, i] += 0.5
        contribute(net, r, +1.0)
    PRES *= 1.6
    print("iter %d: rerouted %d, nets in conflict %d, unroutable %d, %.0f s" % (it_, len(todo), len(bad),
                                                                             len(failed), time.time() - t0), flush=True)
    if it_ == 0:
        print("  unroutable:", sorted(failed), flush=True)
    if not bad:
        break


def to_copper(cells):
    """Merge a cell path (possibly several branches, in path order) into straight segments; split at gaps."""
    tracks = []
    if not cells:
        return tracks
    seg = [cells[0]]
    for a, b2 in zip(cells[:-1], cells[1:]):
        adj = a[0] == b2[0] and max(abs(a[1] - b2[1]), abs(a[2] - b2[2])) == 1
        if adj:
            seg.append(b2)
        else:
            tracks += runs(seg)
            seg = [b2]
    tracks += runs(seg)
    return tracks


def runs(seg):
    out = []
    if len(seg) < 2:
        return out
    start = seg[0]
    d0 = (seg[1][1] - seg[0][1], seg[1][2] - seg[0][2])
    for a, b2 in zip(seg[:-1], seg[1:]):
        d = (b2[1] - a[1], b2[2] - a[2])
        if d != d0:
            out.append((LAYERS[a[0]], bx0 + start[2] * R, by0 + start[1] * R, bx0 + a[2] * R, by0 + a[1] * R))
            start, d0 = a, d
    last = seg[-1]
    out.append((LAYERS[last[0]], bx0 + start[2] * R, by0 + start[1] * R, bx0 + last[2] * R, by0 + last[1] * R))
    return out


results = []
for net, (cells, vias) in routes.items():
    trk = to_copper(cells)
    results.append(dict(net=net, replace=True, tracks=[list(t) for t in trk], widths=[A.track] * len(trk),
                        vias=[[bx0 + i * R, by0 + j * R] for (j, i) in sorted(set(vias))],
                        via_d=[A.via] * len(set(vias))))
# conflict report: where the remaining conflicts are (board mm, KiCad frame), per net
creport = []
for net in sorted(bad):
    r = routes[net]
    contribute(net, r, -1.0)
    own = OWN.get(net, ())
    pts = [(LAYERS[l], round(bx0 + i * R, 1), round(by0 + j * R, 1)) for (l, j, i) in r[0]
           if occT[l, j, i] > 0 and (l, j, i) not in own]
    contribute(net, r, +1.0)
    creport.append(dict(net=net, cells=len(pts), sample=pts[:6]))
json.dump(dict(results=results, failed=sorted(failed), conflicts=sorted(bad), conflict_report=creport,
               params=vars(A)), open(A.out, "w"))
print("written %d nets; unroutable %s; still in conflict %d" % (len(results), sorted(failed), len(bad)))
