"""Global routing: route every net on a coarse tile grid with measured capacities, report where the board
overflows, and write a corridor for each long net from its coarse path.

Usage (venv with numpy + shapely):
  python global_route.py <model.json> <plan.json> <out_plan.json> [--report global.md] [--tile 2.0] [--iters 15]
                         [--widen 1.0] [--min-tiles 3] [--via-cost 1.5] [--mode guide|hold] [--no-corridors]

Model. The board is cut into square tiles of --tile mm on every routing layer. The capacity of the border between
two tiles is the number of tracks that fit through the free cells of the border at the router's own track pitch
(the smallest of the three cell lines at the border). The via capacity of a tile is the number of via sites that
fit in its free via cells. Every net is routed pad to pad over the tiles by negotiated congestion: a border above
its capacity costs more each iteration until nets move away.

Output.
- The report: borders that stay above capacity (place, layer, capacity, demand, nets). These are the places where
  no assignment of nets to channels fits; they are evidence for a request. Borders at or near capacity are listed
  as well.
- The plan copy: for each net whose coarse path covers at least --min-tiles tiles, corridors made of its tiles
  on each layer, widened by --widen mm. --mode guide (default) writes a `net_guide` entry: the net may leave its
  corridors, but every cell outside them costs `costs.guide` times more (default 3). --mode hold writes a
  `net_route` entry that holds the net inside its corridors; a net that does not route alone inside them is
  released again. Hold loses connections when a corridor is wrong; use it only to test one net or one channel.
  The groups of the plan are unchanged, so priorities and widths stay as planned.
With --no-corridors only the report is written (use it for the capacity evidence alone)."""
import argparse
import heapq
import json
import math
from collections import Counter

import numpy as np
from shapely.geometry import box
from shapely.ops import unary_union

from core import FREE, Ctx
from engine import Router

ap = argparse.ArgumentParser()
ap.add_argument("model")
ap.add_argument("plan")
ap.add_argument("out")
ap.add_argument("--report", default=None)
ap.add_argument("--tile", type=float, default=2.0)
ap.add_argument("--iters", type=int, default=15)
ap.add_argument("--widen", type=float, default=1.0)
ap.add_argument("--mode", default="guide", choices=("guide", "hold"))
ap.add_argument("--min-tiles", type=int, default=3)
ap.add_argument("--via-cost", type=float, default=1.5)
ap.add_argument("--no-corridors", action="store_true")
A = ap.parse_args()
C = Ctx(A.model, A.plan)
R, NL, LAYERS = C.R, C.NL, C.LAYERS
G = A.tile
k = max(int(round(G / R)), 1)
G = k * R
gx, gy = int(math.ceil(C.nx / k)), int(math.ceil(C.ny / k))
pc = C.pitch_cells


def runs_cap(line):
    """tracks that fit through a line of cells: each run of n free cells carries ceil(n / pitch_cells)"""
    cap, n = 0, 0
    for v in line:
        if v:
            n += 1
        elif n:
            cap += -(-n // pc)
            n = 0
    if n:
        cap += -(-n // pc)
    return cap


free = (C.ownT == FREE)
capH = np.zeros((NL, gy, gx), np.int32)     # border between tile (a, b) and (a, b + 1)
capV = np.zeros((NL, gy, gx), np.int32)     # border between tile (a, b) and (a + 1, b)
for l in range(NL):
    for a in range(gy):
        for b in range(gx):
            j0, j1, i0, i1 = a * k, min((a + 1) * k, C.ny), b * k, min((b + 1) * k, C.nx)
            if b + 1 < gx:
                capH[l, a, b] = min(runs_cap(free[l, j0:j1, min(max(i1 + d, 0), C.nx - 1)]) for d in (-1, 0, 1))
            if a + 1 < gy:
                capV[l, a, b] = min(runs_cap(free[l, min(max(j1 + d, 0), C.ny - 1), i0:i1]) for d in (-1, 0, 1))
passV = np.all(C.ownV == FREE, axis=0) & ~C.holeBan
vp = (C.via + C.clear) / R
capT = np.zeros((gy, gx), np.int32)
for a in range(gy):
    for b in range(gx):
        nfree = int(passV[a * k:(a + 1) * k, b * k:(b + 1) * k].sum())
        capT[a, b] = max(int(round(nfree / (vp * vp))), 1 if nfree else 0)
demH, demV, demT = np.zeros_like(capH), np.zeros_like(capV), np.zeros_like(capT)
hisH, hisV, hisT = (np.zeros(capH.shape), np.zeros(capV.shape), np.zeros(capT.shape))
lmult = [float(C.P.get("layer_cost", {}).get(ln, 1.0)) for ln in LAYERS]
pres = 0.5


def tile(x, y):
    j, i = C.cell(x, y)
    return min(max(j // k, 0), gy - 1), min(max(i // k, 0), gx - 1)


def pad_nodes(net):
    out = []
    for key, grp in C.pads_of.get(net, {}).items():
        if key[0] == "locked":
            continue
        nodes = set()
        for it in grp:
            g = C.geom_of(it).centroid
            a, b = tile(g.x, g.y)
            for ln in it["layers"]:
                if ln in LAYERS:
                    nodes.add((LAYERS.index(ln), a, b))
        if nodes:
            out.append((key, nodes))
    return out


def step_cost(kind, l, a, b, mine, own):
    """cost of one more net on a resource; mine = resources this net already holds (free of charge)"""
    if (kind, l, a, b) in mine:
        return 0.2
    cap, dem, his = {"H": (capH, demH, hisH), "V": (capV, demV, hisV)}[kind]
    c = cap[l, a, b]
    if c <= 0:
        return 8.0 if own else None      # a net may always leave the tile of its own pad
    over = max(0, dem[l, a, b] + 1 - c)
    return (1.0 + his[l, a, b]) * (1.0 + pres * over) * lmult[l]


def via_cost(a, b, mine, own):
    if ("T", 0, a, b) in mine:
        return 0.2
    c = capT[a, b]
    if c <= 0:
        return 8.0 if own else None
    over = max(0, demT[a, b] + 1 - c)
    return A.via_cost * (1.0 + hisT[a, b]) * (1.0 + pres * over)


def route(net):
    """returns (resources set, nodes set, pads not reached)"""
    pads = pad_nodes(net)
    if len(pads) < 2:
        return set(), set(), []
    tree = set(pads[0][1])
    ptiles = {(n_[1], n_[2]) for _, nodes in pads for n_ in nodes}
    left = pads[1:]
    res = set()
    failed = []
    while left:
        target = {}
        for idx, (key, nodes) in enumerate(left):
            for n_ in nodes:
                target.setdefault(n_, idx)
        dist = {n_: 0.0 for n_ in tree}
        prev = {}
        pq = [(0.0, n_) for n_ in tree]
        heapq.heapify(pq)
        hit = None
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, 1e18):
                continue
            if u in target:
                hit = u
                break
            l, a, b = u
            nb = []
            if b + 1 < gx:
                nb.append(((l, a, b + 1), ("H", l, a, b)))
            if b > 0:
                nb.append(((l, a, b - 1), ("H", l, a, b - 1)))
            if a + 1 < gy:
                nb.append(((l, a + 1, b), ("V", l, a, b)))
            if a > 0:
                nb.append(((l, a - 1, b), ("V", l, a - 1, b)))
            for v, r in nb:
                c = step_cost(r[0], r[1], r[2], r[3], res, (a, b) in ptiles or (v[1], v[2]) in ptiles)
                if c is not None and d + c < dist.get(v, 1e18):
                    dist[v] = d + c
                    prev[v] = (u, r)
                    heapq.heappush(pq, (d + c, v))
            c = via_cost(a, b, res, (a, b) in ptiles)
            if c is not None:
                for l2 in range(NL):
                    v = (l2, a, b)
                    if l2 != l and d + c < dist.get(v, 1e18):
                        dist[v] = d + c
                        prev[v] = (u, ("T", 0, a, b))
                        heapq.heappush(pq, (d + c, v))
        if hit is None:
            failed += [key for key, _ in left]
            break
        idx = target[hit]
        u = hit
        while u in prev:
            tree.add(u)
            u, r = prev[u]
            res.add(r)
        tree |= left[idx][1] & {hit}
        tree.add(hit)
        left.pop(idx)
    return res, tree, failed


def charge(res, s):
    for (kind, l, a, b) in res:
        if kind == "H":
            demH[l, a, b] += s
        elif kind == "V":
            demV[l, a, b] += s
        else:
            demT[a, b] += s


nets = [n for n in sorted(C.routable) if C.connections(n) > 0]
nets.sort(key=lambda n: (C.assign[n]["priority"], C.npads[n]))
got = {}
hist_rows = []
for it_ in range(A.iters):
    for net in nets:
        if net in got:
            charge(got[net][0], -1)
        got[net] = route(net)
        charge(got[net][0], +1)
    # a border of capacity 0 is crossed only by a net that leaves its own pad tile: not an overflow
    oH, oV, oT = (np.maximum(demH - capH, 0) * (capH > 0), np.maximum(demV - capV, 0) * (capV > 0),
                  np.maximum(demT - capT, 0) * (capT > 0))
    over = int(oH.sum() + oV.sum() + oT.sum())
    hist_rows.append((it_, over, sum(1 for n in nets if got[n][2])))
    print("iter %d: overflow %d, nets without a coarse path %d" % hist_rows[-1], flush=True)
    if over == 0:
        break
    hisH += 0.5 * (oH > 0)
    hisV += 0.5 * (oV > 0)
    hisT += 0.5 * (oT > 0)
    pres *= 1.5

users = {}
for net in nets:
    for r in got[net][0]:
        users.setdefault(r, []).append(net)


def place(kind, l, a, b):
    if kind == "H":
        x, y = C.bx0 + (b + 1) * G, C.by0 + (a + 0.5) * G
    elif kind == "V":
        x, y = C.bx0 + (b + 0.5) * G, C.by0 + (a + 1) * G
    else:
        x, y = C.bx0 + (b + 0.5) * G, C.by0 + (a + 0.5) * G
    return "(%.1f, %.1f)" % C.d(x, y)


rows = []
for l in range(NL):
    for a in range(gy):
        for b in range(gx):
            for kind, cap, dem in (("H", capH, demH), ("V", capV, demV)):
                if dem[l, a, b] > 0 and cap[l, a, b] > 0:
                    rows.append((dem[l, a, b] - cap[l, a, b], dem[l, a, b] / max(cap[l, a, b], 1), kind, l, a, b,
                                 int(cap[l, a, b]), int(dem[l, a, b])))
for a in range(gy):
    for b in range(gx):
        if demT[a, b] > 0 and capT[a, b] > 0:
            rows.append((demT[a, b] - capT[a, b], demT[a, b] / max(capT[a, b], 1), "T", 0, a, b, int(capT[a, b]),
                         int(demT[a, b])))
rows.sort(key=lambda r: (-r[0], -r[1]))
kindtxt = {"H": "border crossed in x", "V": "border crossed in y", "T": "vias in the tile"}
L = ["# Global routing", "",
     "Tiles of %.2f mm, %d x %d on %d layers. Track pitch %.3f mm. Nets %d, connections %d. Iterations %d. "
     "Overflow that remains: %d track(s) or via(s) above capacity. Nets without a coarse path: %d." % (
         G, gx, gy, NL, C.pitch, len(nets), sum(C.connections(n) for n in nets), len(hist_rows), hist_rows[-1][1],
         hist_rows[-1][2]), "",
     "Overflow 0 means that an assignment of the nets to channels exists at this resolution. It does not prove that "
     "the detailed router finds it: pad escapes and the space inside a tile are not modelled. An overflow that "
     "remains is a place where the board lacks capacity on every layer: evidence for a placement request.", "",
     "## Borders and tiles above capacity", "", "| Place | Layer | Kind | Capacity | Demand | Nets |", "|---|---|---|---|---|---|"]
ov = [r for r in rows if r[0] > 0]
for (_, _, kind, l, a, b, cap, dem) in ov[:30]:
    L.append("| %s | %s | %s | %d | %d | %s |" % (place(kind, l, a, b), "all" if kind == "T" else LAYERS[l], kindtxt[kind],
                                               cap, dem, " ".join(users.get((kind, l, a, b), [])[:10])))
if not ov:
    L.append("| none | | | | | |")
L += ["", "## Borders and tiles at 80 % of capacity or more", "", "| Place | Layer | Kind | Capacity | Demand |", "|---|---|---|---|---|"]
full = [r for r in rows if r[0] <= 0 and r[1] >= 0.8 and r[6] >= 2]
for (_, _, kind, l, a, b, cap, dem) in sorted(full, key=lambda r: -r[7])[:20]:
    L.append("| %s | %s | %s | %d | %d |" % (place(kind, l, a, b), "all" if kind == "T" else LAYERS[l], kindtxt[kind], cap, dem))
if not full:
    L.append("| none | | | | |")
nopath = [n for n in nets if got[n][2]]
L += ["", "## Nets without a coarse path", "",
      ", ".join("%s (%s)" % (n, " ".join("%s.%s" % key for key in got[n][2][:4])) for n in nopath) or "None.", "",
      "## Use by layer", "", "| Layer | Tile borders crossed |", "|---|---|"]
use = Counter()
for net in nets:
    for (kind, l, a, b) in got[net][0]:
        use[LAYERS[l] if kind != "T" else "vias"] += 1
L += ["| %s | %d |" % (ln, use[ln]) for ln in LAYERS + ["vias"]]
L += ["", "## Negotiation", "", "| Iteration | Overflow | Nets without a coarse path |", "|---|---|---|"]
L += ["| %d | %d | %d |" % h for h in hist_rows]

if not A.no_corridors:
    P = json.load(open(A.plan))
    corr = list(P.get("corridors", []))
    key = "net_route" if A.mode == "hold" else "net_guide"
    nroute = dict(P.get(key, {}))
    made = []
    for idx, net in enumerate(nets):
        res, tree, failed = got[net]
        if failed or len({(a, b) for (_, a, b) in tree}) < A.min_tiles or C.assign[net]["mode"] == "corridor":
            continue
        ids = []
        for l in range(NL):
            ts = [(a, b) for (ll, a, b) in tree if ll == l]
            if not ts:
                continue
            g = unary_union([box(C.bx0 + b * G, C.by0 + a * G, C.bx0 + (b + 1) * G, C.by0 + (a + 1) * G) for a, b in ts])
            g = g.buffer(A.widen, join_style=2)
            for q, piece in enumerate(getattr(g, "geoms", [g])):
                cid = "g%d_%s_%d" % (idx, LAYERS[l].replace(".Cu", ""), q)
                corr.append(dict(id=cid, layers=[LAYERS[l]],
                                 polygon=[[round(v, 3) for v in C.d(x, y)] for x, y in list(piece.exterior.coords)[:-1]]))
                ids.append(cid)
        nroute[net] = ids
        made.append(net)
    P["corridors"], P[key] = corr, nroute
    json.dump(P, open(A.out, "w"), indent=1)
    released = []
    if A.mode == "hold":                           # release every net that does not route alone in its corridors
        C2 = Ctx(A.model, A.out)
        RT = Router(C2)
        released = [net for net in made if RT.route_net(net, solo=True)[1]]
        if C2.plan_errors:
            raise SystemExit("plan errors: " + "; ".join(C2.plan_errors))
    if released:
        for net in released:
            del nroute[net]
        used = {cid for r in nroute.values() for cid in r} | {c["id"] for c in P.get("corridors", []) if not c["id"].startswith("g")}
        P["corridors"] = [c for c in corr if c["id"] in used]
        json.dump(P, open(A.out, "w"), indent=1)
    L += ["", "## Corridors written", "",
          "Mode: " + A.mode + ". Nets with corridors from their coarse path: %d of %d. Released because they do not route alone inside "
          "the corridor (hold mode): %d (%s). Short nets and nets that the plan already holds in corridors are unchanged." % (
              len(made) - len(released), len(nets), len(released), ", ".join(released) or "none")]
txt = "\n".join(L) + "\n"
if A.report:
    open(A.report, "w", encoding="utf-8").write(txt)
print(txt)
