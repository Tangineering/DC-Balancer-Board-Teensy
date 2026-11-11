"""Corridor router steps L5-L6: detailed routing inside the planned corridors.

Usage (venv with numpy + shapely):
  python -u route_plan.py <model.json> <plan.json> <routes.json> [--iters 30] [--report route_report.md]
                          [--only-groups g1,g2] [--seed 1]

Each routable net is routed pad to pad by a negotiated-congestion grid search (PathFinder) that may use only the
net's allowed region: its corridors on their layers plus an escape disc around each pad (mode "corridor"), the
pad bounding box plus a margin (mode "local"), or the whole board (mode "free"). Nets of other groups compete
for the same cells; a contested cell costs more each iteration until one net moves. At the end, nets that still
overlap are dropped one by one until the remaining copper is legal, so the output never contains a clearance
violation between routed nets. The report attributes every failed or dropped net to its group and corridors."""
import argparse
import heapq
import json
import math
import random
import time

import numpy as np

from core import FREE, Ctx

ap = argparse.ArgumentParser()
ap.add_argument("model")
ap.add_argument("plan")
ap.add_argument("out")
ap.add_argument("--iters", type=int, default=30)
ap.add_argument("--via-cost", type=float, default=10.0)
ap.add_argument("--pour-penalty", type=float, default=30.0)
ap.add_argument("--report", default=None)
ap.add_argument("--only-groups", default="")
ap.add_argument("--seed", type=int, default=1)
A = ap.parse_args()
random.seed(A.seed)
t0 = time.time()
C = Ctx(A.model, A.plan)
if C.plan_errors:
    raise SystemExit("plan errors:\n  " + "\n  ".join(C.plan_errors))
R, NL, nx, ny = C.R, C.NL, C.nx, C.ny
LAYERS = C.LAYERS
only = {g for g in A.only_groups.split(",") if g}
todo_nets = [n for n in C.routable if not only or C.assign[n]["group"] in only]
print("grid %d x %d x %d, routable nets %d (%d selected), %.1f s" % (nx, ny, NL, len(C.routable), len(todo_nets),
                                                                   time.time() - t0), flush=True)


def disk(r):
    k = int(math.ceil(r / R))
    return [(dj, di) for dj in range(-k, k + 1) for di in range(-k, k + 1) if math.hypot(dj, di) * R <= r + 1e-9]


DT_T = disk(C.track + C.clear + R * 0.5)
DT_V = disk(C.via / 2 + C.clear + C.track / 2 + R * 0.5)
DV_V = disk(C.via + C.clear + R * 0.5)
occT = np.zeros((NL, ny, nx), np.float32)
occV = np.zeros((NL, ny, nx), np.float32)
hist = np.zeros((NL, ny, nx), np.float32)


def stamp(arr, l, j, i, offs, val):
    for dj, di in offs:
        jj, ii = j + dj, i + di
        if 0 <= jj < ny and 0 <= ii < nx:
            arr[l, jj, ii] += val


def contribute(net, route, val):
    cells, vias = route
    own = C.own.get(net, ())
    for (l, j, i) in cells:
        if (l, j, i) in own:
            continue
        stamp(occT, l, j, i, DT_T, val)
        stamp(occV, l, j, i, DT_V, val)
    for (j, i) in vias:
        for l in range(NL):
            stamp(occT, l, j, i, DT_V, val)
            stamp(occV, l, j, i, DV_V, val)


SQ2 = math.sqrt(2)
NB = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, SQ2), (1, -1, SQ2), (-1, 1, SQ2), (-1, -1, SQ2)]
PRES = 1.0


def route_net(net):
    """returns ((cells, vias), ok, unreached pad keys)"""
    n = C.nid(net)
    groups = {k: v for k, v in C.padcells.get(net, {}).items() if v}
    if len(groups) < 2:
        return ([], []), True, []
    j0, j1, i0, i1, allow = C.allowed(net)
    W, H = i1 - i0, j1 - j0
    oT = C.ownT[:, j0:j1, i0:i1]
    passT = ((oT == FREE) | (oT == n)) & allow
    oV = C.ownV[:, j0:j1, i0:i1]
    passV = np.all((oV == FREE) | (oV == n), axis=0)
    pn = C.pourN[:, j0:j1, i0:i1]
    costT = ((1.0 + hist[:, j0:j1, i0:i1]) * (1.0 + PRES * occT[:, j0:j1, i0:i1])
             + np.where((pn != FREE) & (pn != n), A.pour_penalty, 0.0))
    costT = np.where(passT, costT, np.inf).astype(np.float64)
    costV = A.via_cost * (1.0 + hist[:, j0:j1, i0:i1].max(axis=0)) * (1.0 + PRES * occV[:, j0:j1, i0:i1].max(axis=0))
    costV = np.where(passV, costV, np.inf).astype(np.float64)
    cT = [costT[l].ravel().tolist() for l in range(NL)]
    cV = costV.ravel().tolist()

    def loc(cs):
        return set((l, j - j0, i - i0) for (l, j, i) in cs if j0 <= j < j1 and i0 <= i < i1)

    keys = sorted(groups, key=lambda k: -len(groups[k]))
    tree = loc(groups[keys[0]])
    rest = [(k, loc(groups[k])) for k in keys[1:]]
    cells, vias, unreached = [], [], []
    while rest:
        tj = sum(c[1] for c in tree) / len(tree)
        ti = sum(c[2] for c in tree) / len(tree)
        rest.sort(key=lambda kg: min(math.hypot(c[1] - tj, c[2] - ti) for c in list(kg[1])[:4]) if kg[1] else 1e9)
        key, tgt = rest.pop(0)
        if not tgt:
            unreached.append(key)
            continue
        cy_ = sum(c[1] for c in tgt) / len(tgt)
        cx_ = sum(c[2] for c in tgt) / len(tgt)
        rad = max(math.hypot(c[1] - cy_, c[2] - cx_) for c in tgt)
        g, prev, pq = {}, {}, []
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
            if vc != math.inf and row[j * W + i] != math.inf:
                for l2 in range(NL):
                    if l2 == l or cT[l2][j * W + i] == math.inf:
                        continue
                    t = (l2, j, i)
                    nc = gc + vc
                    if nc < g.get(t, 1e30):
                        g[t] = nc
                        prev[t] = s
                        heapq.heappush(pq, (nc + max(0.0, math.hypot(j - cy_, i - cx_) - rad), nc, t))
        if found is None:
            unreached.append(key)
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
    return (cells, vias), not unreached, unreached


def conflict_cells(net, route):
    cells, vias = route
    own = C.own.get(net, ())
    out = [(l, j, i) for (l, j, i) in cells if (l, j, i) not in own and occT[l, j, i] > 0]
    out += [(0, j, i) for (j, i) in vias if max(occV[l, j, i] for l in range(NL)) > 0]
    return out


routes, failed = {}, {}
order = sorted(todo_nets, key=lambda net: (C.assign[net]["priority"], len(C.padcells.get(net, {}))))
bad = set()
for it_ in range(A.iters):
    todo = order if it_ == 0 else [n_ for n_ in order if n_ in bad or n_ in failed]
    if it_ > 0:
        random.shuffle(todo)
        todo.sort(key=lambda net: C.assign[net]["priority"])
    for net in todo:
        if net in routes:
            contribute(net, routes[net], -1.0)
        r, ok, unreached = route_net(net)
        routes[net] = r
        contribute(net, r, +1.0)
        if ok:
            failed.pop(net, None)
        else:
            failed[net] = unreached
    bad = set()
    for net, r in routes.items():
        contribute(net, r, -1.0)
        cc = conflict_cells(net, r)
        if cc:
            bad.add(net)
            for (l, j, i) in cc:
                hist[l, j, i] += 0.5
        contribute(net, r, +1.0)
    PRES *= 1.6
    print("iter %d: rerouted %d, in conflict %d, no path %d, %.0f s" % (it_, len(todo), len(bad), len(failed),
                                                                      time.time() - t0), flush=True)
    if not bad:
        break

# ---------------------------------------------------------------- legalise: drop conflicting nets, worst first
dropped = {}
while True:
    worst = None
    for net, r in routes.items():
        if net in dropped or net in failed:
            continue
        contribute(net, r, -1.0)
        cc = conflict_cells(net, r)
        contribute(net, r, +1.0)
        if cc and (worst is None or (C.assign[net]["priority"], len(cc)) > worst[0]):
            worst = ((C.assign[net]["priority"], len(cc)), net, cc)
    if worst is None:
        break
    _, net, cc = worst
    contribute(net, routes[net], -1.0)
    dropped[net] = cc
for net in failed:       # partial copper of a net with an unreached pad is not kept
    if net not in dropped:
        contribute(net, routes[net], -1.0)


def runs(seg):
    out = []
    if len(seg) < 2:
        return out
    start = seg[0]
    d0 = (seg[1][1] - seg[0][1], seg[1][2] - seg[0][2])
    for a, b2 in zip(seg[:-1], seg[1:]):
        d = (b2[1] - a[1], b2[2] - a[2])
        if d != d0:
            out.append((LAYERS[a[0]], C.bx0 + start[2] * R, C.by0 + start[1] * R, C.bx0 + a[2] * R, C.by0 + a[1] * R))
            start, d0 = a, d
    last = seg[-1]
    out.append((LAYERS[last[0]], C.bx0 + start[2] * R, C.by0 + start[1] * R, C.bx0 + last[2] * R, C.by0 + last[1] * R))
    return out


def to_copper(cells):
    tracks = []
    if not cells:
        return tracks
    seg = [cells[0]]
    for a, b2 in zip(cells[:-1], cells[1:]):
        if a[0] == b2[0] and max(abs(a[1] - b2[1]), abs(a[2] - b2[2])) == 1:
            seg.append(b2)
        else:
            tracks += runs(seg)
            seg = [b2]
    return tracks + runs(seg)


results = []
for net, (cells, vias) in routes.items():
    if net in failed or net in dropped:
        continue
    trk = to_copper(cells)
    results.append(dict(net=net, replace=True, tracks=[list(t) for t in trk], widths=[C.track] * len(trk),
                        vias=[[C.bx0 + i * R, C.by0 + j * R] for (j, i) in sorted(set(vias))],
                        via_d=[C.via] * len(set(vias))))
json.dump(dict(results=results, failed=sorted(failed), dropped=sorted(dropped),
               params=dict(track=C.track, clear=C.clear, via=C.via, drill=C.drill, res=R)), open(A.out, "w"))

# ---------------------------------------------------------------- report with attribution
corr = C.corridors()


def where(l, j, i):
    from shapely.geometry import Point
    x, y = C.bx0 + i * R, C.by0 + j * R
    ids = [cid for cid, c in corr.items() if l in c["layers"] and c["geom"].contains(Point(x, y))]
    return "%s (%.1f, %.1f)%s" % ((LAYERS[l],) + C.d(x, y) + ((" in " + "/".join(ids)) if ids else " outside corridors",))


L = ["# Corridor routing report", "",
     "Routed %d of %d selected nets; no path %d; dropped for conflicts %d; %d iterations, %.0f s." % (
         len(results), len(todo_nets), len(failed), len(dropped), it_ + 1, time.time() - t0), "",
     "## By group", "", "| Group | Nets | Routed | No path | Dropped |", "|---|---|---|---|---|"]
groups = {}
for net in todo_nets:
    g = groups.setdefault(C.assign[net]["group"], [0, 0, 0, 0])
    g[0] += 1
    g[1 + (1 if net in failed else 2 if net in dropped else 0)] += 1
for name, g in sorted(groups.items()):
    L.append("| %s | %d | %d | %d | %d |" % (name, g[0], g[1], g[2], g[3]))
L += ["", "## Nets with no path", "",
      "The allowed region does not connect these pads (a sealed pad, a corridor that does not reach the pad's escape "
      "disc, or a missing layer change). Fix the plan entry named here.", ""]
for net in sorted(failed):
    a = C.assign[net]
    pcs = {(p[0], p[1]): p for p in C.pad_centres(net)}
    pads = ", ".join("%s.%s at (%.1f, %.1f)" % ((k[0], k[1]) + C.d(pcs[k][2], pcs[k][3])) for k in failed[net] if k in pcs)
    L.append("- %s [group %s, mode %s, route %s]: unreached %s" % (net, a["group"], a["mode"], a["route"], pads))
L += ["", "## Nets dropped for conflicts", "",
      "These nets found a path only by overlapping other nets. The locations name the contested corridor.", ""]
for net in sorted(dropped):
    a = C.assign[net]
    cc = dropped[net]
    pts = sorted({where(l, j, i) for (l, j, i) in cc[:: max(1, len(cc) // 4)]})
    L.append("- %s [group %s, route %s]: %d contested cells, e.g. %s" % (net, a["group"], a["route"], len(cc),
                                                                     "; ".join(pts[:4])))
txt = "\n".join(L) + "\n"
if A.report:
    open(A.report, "w", encoding="utf-8").write(txt)
print(txt)
