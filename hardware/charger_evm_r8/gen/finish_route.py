"""Finishing router, step 2 (python with numpy + shapely): grid A* over the routing layers for every unconnected
pair in the dump. Obstacles are the copper of other nets inflated by clearance + half the track width (track grid)
or + the via radius (via grid). Pairs on the plane net (GND on the 4-layer CR) are closed by a via to the plane.
Usage: python finish_route.py <dump.json> <out.json> --res 0.1 --clear 0.16 --track 0.16 --via 0.6 --drill 0.3
       [--plane-net /GND] [--via-cost 12] [--max-expand 400000]"""
import argparse
import heapq
import json
import math
import re

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
ap.add_argument("--via-cost", type=float, default=12.0)
ap.add_argument("--max-expand", type=int, default=400000)
ap.add_argument("--max-rips", type=int, default=40)
ap.add_argument("--protect", default="", help="comma list of nets never ripped up")
A = ap.parse_args()

D = json.load(open(A.dump))
LAYERS = D["layers"]
NL = len(LAYERS)
x0, y0, x1, y1 = D["bbox"]
R = A.res
nx, ny = int(math.ceil((x1 - x0) / R)) + 1, int(math.ceil((y1 - y0) / R)) + 1
X, Y = np.meshgrid(x0 + np.arange(nx) * R, y0 + np.arange(ny) * R)
FREE, BLOCK = -1, -2
ownT = np.full((NL, ny, nx), FREE, np.int32)
ownV = np.full((NL, ny, nx), FREE, np.int32)
rT = A.clear + A.track / 2 + R * 0.5
rV = A.clear + A.via / 2 + R * 0.5
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
    bx0, by0, bx1, by1 = g.bounds
    i0, i1 = max(int((bx0 - x0) / R) - 1, 0), min(int((bx1 - x0) / R) + 2, nx)
    j0, j1 = max(int((by0 - y0) / R) - 1, 0), min(int((by1 - y0) / R) + 2, ny)
    return i0, i1, j0, j1


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


def add_item(it):
    if it["kind"] == "zone" and it.get("soft"):
        return
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


for it in D["items"]:
    add_item(it)


def cells_of(it):
    out = []
    g = geom_of(it)
    i0, i1, j0, j1 = window(g)
    m = shapely.contains_xy(g, X[j0:j1, i0:i1], Y[j0:j1, i0:i1])
    jj, ii = np.nonzero(m)
    if len(jj) == 0:   # very small copper: take the nearest cell to its centroid
        c = g.centroid
        jj, ii = np.array([int(round((c.y - y0) / R)) - j0]), np.array([int(round((c.x - x0) / R)) - i0])
    for ln in it["layers"]:
        li = LAYERS.index(ln)
        out += [(li, j + j0, i + i0) for j, i in zip(jj, ii)]
    return out


def find_item(x, y, desc):
    m = re.match(r"(PTH pad|Pad|SMD pad|NPTH pad) (\S*) \[([^\]]*)\] of (\S+)", desc)
    if m:
        num, net, ref = m.group(2), m.group(3), m.group(4)
        c = [it for it in D["items"] if it["kind"] == "pad" and it.get("ref") == ref and it.get("num") == num]
        return net, c
    m = re.match(r"(Track|Via|Zone[^\[]*) \[([^\]]*)\] on ([A-Za-z0-9.]+)", desc)
    if m:
        kind = {"Track": "track", "Via": "via"}.get(m.group(1), "zone")
        net, ln = m.group(2), m.group(3)
        cand = [it for it in D["items"] if it["kind"] == kind and it["net"] == net and (kind == "via" or ln in it["layers"])]
        if not cand:
            return net, []
        best = min(cand, key=lambda it: geom_of(it).distance(Point(x, y)))
        return net, [best]
    return None, []


SQ2 = math.sqrt(2)
NB = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, SQ2), (1, -1, SQ2), (-1, 1, SQ2), (-1, -1, SQ2)]


def astar(n, srcs, tgts, plane=False):
    passT = [bytearray(((ownT[l] == FREE) | (ownT[l] == n)).astype(np.uint8).tobytes()) for l in range(NL)]
    passV = bytearray(np.all((ownV == FREE) | (ownV == n), axis=0).astype(np.uint8).tobytes())
    tset = set(tgts) if tgts else set()
    sset = set(srcs)
    if plane:
        tc = None
    else:
        tj = sum(t[1] for t in tgts) / len(tgts)
        ti = sum(t[2] for t in tgts) / len(tgts)
        trad = max(math.hypot(t[1] - tj, t[2] - ti) for t in tgts)
    def h(j, i):
        if plane:
            return 0.0
        return max(0.0, math.hypot(j - tj, i - ti) - trad)
    g = {}
    prev = {}
    pq = []
    for s in srcs:
        g[s] = 0.0
        prev[s] = None
        heapq.heappush(pq, (h(s[1], s[2]), 0.0, s))
    exp = 0
    while pq:
        f, gc, s = heapq.heappop(pq)
        if gc > g.get(s, 1e18):
            continue
        l, j, i = s
        if (not plane and s in tset) or (plane and passV[j * nx + i] and s not in sset):
            path = [s]
            while prev[path[-1]] is not None:
                path.append(prev[path[-1]])
            return path[::-1]
        exp += 1
        if exp > A.max_expand:
            return None
        row = passT[l]
        for dj, di, c in NB:
            jj, ii = j + dj, i + di
            if not (0 <= jj < ny and 0 <= ii < nx):
                continue
            if not row[jj * nx + ii] and (l, jj, ii) not in tset:
                continue
            if dj and di and not (row[j * nx + ii] and row[jj * nx + i]):
                continue
            t = (l, jj, ii)
            nc = gc + c
            if nc < g.get(t, 1e18):
                g[t] = nc
                prev[t] = s
                heapq.heappush(pq, (nc + h(jj, ii), nc, t))
        if passV[j * nx + i] and not plane:
            for l2 in range(NL):
                if l2 != l and passT[l2][j * nx + i]:
                    t = (l2, j, i)
                    nc = gc + A.via_cost
                    if nc < g.get(t, 1e18):
                        g[t] = nc
                        prev[t] = s
                        heapq.heappush(pq, (nc + h(j, i), nc, t))
    return None


def to_copper(path):
    """Cells -> track segments (collinear runs merged) and vias at layer changes."""
    tracks, vias = [], []
    cx = lambda i: x0 + i * R  # noqa: E731
    cy = lambda j: y0 + j * R  # noqa: E731
    start = path[0]
    prev_d = None
    for a, b in zip(path[:-1], path[1:]):
        if a[0] != b[0]:
            if start != a:
                tracks.append((LAYERS[a[0]], cx(start[2]), cy(start[1]), cx(a[2]), cy(a[1])))
            vias.append((cx(a[2]), cy(a[1])))
            start, prev_d = b, None
            continue
        d = (b[1] - a[1], b[2] - a[2])
        if prev_d is not None and d != prev_d:
            tracks.append((LAYERS[a[0]], cx(start[2]), cy(start[1]), cx(a[2]), cy(a[1])))
            start = a
        prev_d = d
    last = path[-1]
    if start != last:
        tracks.append((LAYERS[last[0]], cx(start[2]), cy(start[1]), cx(last[2]), cy(last[1])))
    return tracks, vias


# ------------------------------------------------------------------ rip-up and reroute
ZONE_NETS = {it["net"] for it in D["items"] if it["kind"] == "zone"}
PROTECT = ZONE_NETS | {x for x in A.protect.split(",") if x} | ({A.plane_net} if A.plane_net else set())
ROUTED = [it for it in D["items"] if it["kind"] in ("track", "via")]
net_of = {}


def rebuild(skip_unprotected_routes_of=None):
    ownT[:] = FREE
    ownV[:] = FREE
    for it in D["items"]:
        if it["kind"] not in ("track", "via"):
            add_item(it)
    for it in ROUTED:
        if skip_unprotected_routes_of is not None and it["net"] not in PROTECT \
                and it["net"] != skip_unprotected_routes_of:
            continue
        add_item(it)


def soft_block_nets(n, srcs, tgts):
    """Route as if other nets' unprotected routed copper were absent; return the nets that path crosses."""
    rebuild(skip_unprotected_routes_of=net_of[n])
    p = astar(n, srcs, tgts)
    rebuild()
    if not p:
        return None
    zone = shapely.unary_union([Point(x0 + c[2] * R, y0 + c[1] * R).buffer(rT) for c in p])
    hit = set()
    for it in ROUTED:
        if it["net"] != net_of[n] and it["net"] not in PROTECT and geom_of(it).intersects(zone):
            hit.add(it["net"])
    return hit


def commit(net, path, plane=False):
    tracks, vias = to_copper(path)
    if plane:
        vias.append((x0 + path[-1][2] * R, y0 + path[-1][1] * R))
    new = [dict(kind="track", net=net, layers=[ln], seg=(xa, ya, xb, yb, A.track), new=True)
           for (ln, xa, ya, xb, yb) in tracks]
    new += [dict(kind="via", net=net, layers=LAYERS, circ=(vx, vy, A.via / 2), new=True) for (vx, vy) in vias]
    for it in new:
        ROUTED.append(it)
        add_item(it)


def route_pair(net, src, tgt, plane=False):
    n = nid(net)
    net_of[n] = net
    if plane:
        ok = True
        for cells in (src, tgt):
            p = astar(n, cells, None, plane=True)
            if p:
                commit(net, p, plane=True)
            else:
                ok = False
        return ok
    p = astar(n, src, tgt)
    if p:
        commit(net, p)
        return True
    return False


def route_whole_net(net):
    """Connect every pad of a ripped net (nearest first) with fresh copper."""
    groups = {}
    for it in D["items"]:
        if it["kind"] == "pad" and it["net"] == net:
            groups.setdefault((it.get("ref"), it.get("num")), []).append(it)
    plist = list(groups.values())
    if len(plist) < 2:
        return True
    comp = [c for it in plist[0] for c in cells_of(it)]
    rest = plist[1:]
    ok = True
    n = nid(net)
    net_of[n] = net
    while rest:
        cj = sum(c[1] for c in comp) / len(comp)
        ci = sum(c[2] for c in comp) / len(comp)
        rest.sort(key=lambda g: min(math.hypot(c[1] - cj, c[2] - ci) for it in g for c in cells_of(it)[:1]))
        g = rest.pop(0)
        tgt = [c for it in g for c in cells_of(it)]
        p = astar(n, comp, tgt)
        if p:
            commit(net, p)
            comp += p
        else:
            ok = False
        comp += tgt
    return ok


results, failed = [], []
replaced = set()
rips = 0
pairs = sorted(D["pairs"], key=lambda p: math.hypot(p[0][0] - p[1][0], p[0][1] - p[1][1]))
for pa, pb in pairs:
    netA, ia = find_item(*pa)
    netB, ib = find_item(*pb)
    net = netA or netB
    if not net or not ia or not ib:
        failed.append([pa[2], pb[2], "item not found"])
        continue
    n = nid(net)
    net_of[n] = net
    src = [c for it in ia for c in cells_of(it)]
    tgt = [c for it in ib for c in cells_of(it)]
    plane = A.plane_net is not None and net == A.plane_net
    if route_pair(net, src, tgt, plane):
        continue
    if plane or net in PROTECT or rips >= A.max_rips:
        failed.append([pa[2], pb[2], "no path"])
        continue
    hit = soft_block_nets(n, src, tgt)
    if not hit:
        failed.append([pa[2], pb[2], "no path (blocked by pads or protected copper)"])
        continue
    rips += 1
    ROUTED[:] = [it for it in ROUTED if it["net"] not in hit]
    replaced |= hit
    rebuild()
    if not route_pair(net, src, tgt):
        failed.append([pa[2], pb[2], "no path after rip-up of %s" % sorted(hit)])
    for h in sorted(hit):
        if not route_whole_net(h):
            failed.append([h, "", "ripped net not fully rerouted"])

for net in sorted({it["net"] for it in ROUTED if it.get("new")} | replaced):
    its = [it for it in ROUTED if it["net"] == net and (it.get("new") or net in replaced)]
    results.append(dict(net=net, replace=net in replaced,
                        tracks=[[it["layers"][0]] + list(it["seg"][:4]) for it in its if it["kind"] == "track"],
                        widths=[it["seg"][4] for it in its if it["kind"] == "track"],
                        vias=[list(it["circ"][:2]) for it in its if it["kind"] == "via"],
                        via_d=[2 * it["circ"][2] for it in its if it["kind"] == "via"]))

json.dump(dict(results=results, failed=failed, params=vars(A)), open(A.out, "w"), indent=0)
print("nets written", len(results), "ripped", sorted(replaced), "failed", len(failed))
for f in failed[:40]:
    print("  FAIL", f)
