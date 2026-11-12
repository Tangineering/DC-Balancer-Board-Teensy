"""Check a routing plan before any copper is made.

Usage (venv with numpy + shapely):
  python capacity.py <model.json> <plan.json> [<report.md>]

Checks, in this order:
 1. plan errors and the net census (every routable net is in exactly one group or in the default);
 2. sealed pads: every pad of every routable net can leave its own neighbourhood;
 3. corridor capacity: at stations along each path corridor, the parallel tracks that fit between the fixed
    obstacles at the router's own track pitch, against the nets assigned to every path corridor that shares the
    station (overlapping corridors are one physical channel);
 4. solo routability: every net routes alone inside its allowed region (pads reach their corridors, a via site
    exists where the net must change layer);
 5. crossings: nets that the plan holds on one layer and whose straight-line trees cross (they need a bridge);
 6. congestion estimate (information): where the straight-line demand exceeds the free track supply.
Exit code 1 when check 1, 2, 3 or 4 fails."""
import math
import sys
from collections import Counter, deque

import numpy as np
from shapely.geometry import LineString, Point

from core import FREE, Ctx
from engine import Router, seg_cross

C = Ctx(sys.argv[1], sys.argv[2])
out = sys.argv[3] if len(sys.argv) > 3 else None
R, NL = C.R, C.NL
L = ["# Plan check", "",
     "Rules: track %.3f, clearance %.3f, via %.2f/%.2f, grid %.4f, track pitch %.3f mm (%d cells), edge clearance "
     "%.2f mm. Coordinates: %s." % (C.track, C.clear, C.via, C.drill, R, C.pitch, C.pitch_cells, C.edge_clear,
                                   "design frame (y up)" if C.yoff is not None else "KiCad frame"), ""]
fail = False


def fmt(x, y):
    return "(%.2f, %.2f)" % C.d(x, y)


# ---------------------------------------------------------------- 1. plan errors, census
L += ["## 1. Plan errors and net census", ""]
if C.plan_errors:
    fail = True
    L += ["- ERROR: " + e for e in C.plan_errors]
L += ["- warning: " + w for w in C.plan_warnings]
if not C.plan_errors and not C.plan_warnings:
    L.append("No errors.")
by_group = {}
for net, a in C.assign.items():
    g = by_group.setdefault(a["group"], [0, 0, a["mode"], a["priority"]])
    g[0] += 1
    g[1] += C.connections(net)
L += ["", "| Group | Mode | Priority | Nets | Connections |", "|---|---|---|---|---|"]
for name, g in sorted(by_group.items(), key=lambda kv: kv[1][3]):
    L.append("| %s | %s | %s | %d | %d |" % (name, g[2], g[3], g[0], g[1]))
big = [n for n in C.routable if C.npads.get(n, 0) >= 12]
if big:
    L += ["", "Nets with 12 or more pads and no pour: %s. Such a net competes with every signal near its pads. "
          "Give it a pour or a rail (a design change, report it), or route it first (priority 1)." % ", ".join(
              "%s (%d pads, priority %s)" % (n, C.npads[n], C.assign[n]["priority"]) for n in sorted(big))]
L.append("")

# ---------------------------------------------------------------- 2. sealed pads
ESC = 1.2   # a pad escapes when the search reaches a cell this far outside the pad's own cells
L += ["## 2. Sealed pads", ""]
sealed = []
for net in sorted(C.routable):
    n = C.nid(net)
    for (ref, num), cells in C.padcells[net].items():
        if ref == "locked" or not cells:
            continue
        js = [c[1] for c in cells]
        is_ = [c[2] for c in cells]
        k = int(ESC / R)
        j0, j1 = max(min(js) - k - 1, 0), min(max(js) + k + 2, C.ny)
        i0, i1 = max(min(is_) - k - 1, 0), min(max(is_) + k + 2, C.nx)
        oT = C.ownT[:, j0:j1, i0:i1]
        pT = (oT == FREE) | (oT == n)
        oV = C.ownV[:, j0:j1, i0:i1]
        pV = np.all((oV == FREE) | (oV == n), axis=0) & ~C.holeBan[j0:j1, i0:i1]
        seen = set((l, j - j0, i - i0) for (l, j, i) in cells)
        q = deque(seen)
        escaped = False
        blockers = Counter()
        H, W = j1 - j0, i1 - i0
        while q and not escaped:
            l, j, i = q.popleft()
            if (j + j0 < min(js) - k or j + j0 > max(js) + k or i + i0 < min(is_) - k or i + i0 > max(is_) + k):
                escaped = True
                break
            for dj, di in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                jj, ii = j + dj, i + di
                if not (0 <= jj < H and 0 <= ii < W):
                    escaped = True
                    break
                if (l, jj, ii) in seen:
                    continue
                if pT[l, jj, ii]:
                    seen.add((l, jj, ii))
                    q.append((l, jj, ii))
                else:
                    o = int(oT[l, jj, ii])
                    blockers[C.net_name.get(o, "keep-out / edge / two nets") + " on " + C.LAYERS[l]] += 1
            if pV[j, i]:
                for l2 in range(NL):
                    if l2 != l and pT[l2, j, i] and (l2, j, i) not in seen:
                        seen.add((l2, j, i))
                        q.append((l2, j, i))
        if not escaped:
            x = C.bx0 + (sum(is_) / len(is_)) * R
            y = C.by0 + (sum(js) / len(js)) * R
            sealed.append((net, ref, num, x, y, blockers.most_common(3)))
if sealed:
    fail = True
    L += ["| Net | Pad | At | Blocked by (cells) |", "|---|---|---|---|"]
    for net, ref, num, x, y, bl in sealed:
        L.append("| %s | %s.%s | %s | %s |" % (net, ref, num, fmt(x, y), "; ".join("%s (%d)" % b for b in bl)))
    L += ["", "A sealed pad cannot be routed by any plan. It needs a placement change, a smaller neighbouring pad, "
          "a notch in the pour that seals it (or `soft_pours` if the pour may be cut), or a finer rule set. "
          "Report it; do not route until this table is empty."]
else:
    L.append("None: every pad can leave its neighbourhood.")
L.append("")

# ---------------------------------------------------------------- 3. corridor capacity
corr = C.corridors()
users = {}                     # corridor -> {net: weight}
for net, a in C.assign.items():
    if a["mode"] == "corridor":
        for cid, w in C.flat_route(a["route"]):
            if cid in corr:
                users.setdefault(cid, {})[net] = max(w, users.get(cid, {}).get(net, 0.0))
local_boxes = []
for net, a in C.assign.items():
    if a["mode"] == "local":
        pcs = C.pad_centres(net)
        if len(pcs) > 1:
            xs, ys = [p[2] for p in pcs], [p[3] for p in pcs]
            local_boxes.append((min(xs), min(ys), max(xs), max(ys)))
L += ["## 3. Corridor capacity", "",
      "Capacity = parallel tracks that fit across the corridor at its narrowest station, summed over its layers, at "
      "the router's track pitch (%.3f mm). Demand = nets assigned to the corridor and to every other path corridor "
      "that covers the same station on a shared layer; a net with k alternative corridors counts 1/k in each. "
      "\"Local\" = nets in mode `local` whose pad box contains the station; they are not planned and use the same "
      "space." % C.pitch, "",
      "| Corridor | Layers | Width | Own nets | Demand | Capacity | Margin | Shared with | Local | Narrowest station | Result |",
      "|---|---|---|---|---|---|---|---|---|---|---|"]
for cid, c in corr.items():
    lay = ",".join(C.LAYERS[l] for l in c["layers"])
    own_n = len(users.get(cid, {}))
    if c["path"] is None:
        L.append("| %s | %s | region | %d | - | - | - | - | - | - | region: see checks 5 and 6 |" % (cid, lay, own_n))
        continue
    line = LineString(c["path"])
    worst = None
    s = 0.0
    while s <= line.length + 1e-9:
        p = line.interpolate(s)
        q = line.interpolate(min(s + 0.05, line.length)) if s + 0.05 <= line.length else line.interpolate(s - 0.05)
        dx, dy = q.x - p.x, q.y - p.y
        if s + 0.05 > line.length:
            dx, dy = -dx, -dy
        nrm = math.hypot(dx, dy) or 1.0
        ux, uy = -dy / nrm, dx / nrm
        shared = [d for d, cd in corr.items() if d != cid and cd["path"] is not None
                  and set(cd["layers"]) & set(c["layers"]) and cd["geom"].contains(p)]
        dem = dict(users.get(cid, {}))
        for d in shared:
            for net, w in users.get(d, {}).items():
                dem[net] = max(dem.get(net, 0.0), w)
        ids = {C.nid(n) for n in dem}
        n_s = int(c["width"] / R) + 1
        cap = 0
        for l in c["layers"]:
            run = 0
            for t in range(n_s):
                off = -c["width"] / 2 + t * R
                j, i = C.cell(p.x + ux * off, p.y + uy * off)
                free = 0 <= j < C.ny and 0 <= i < C.nx and (C.ownT[l, j, i] == FREE or int(C.ownT[l, j, i]) in ids)
                if free:
                    run += 1
                if (not free or t == n_s - 1) and run:
                    cap += (run - 1) // C.pitch_cells + 1
                    run = 0
        d = sum(dem.values())
        loc = sum(1 for (x0, y0, x1, y1) in local_boxes if x0 <= p.x <= x1 and y0 <= p.y <= y1)
        if worst is None or cap - d < worst[0]:
            worst = (cap - d, cap, d, p.x, p.y, shared, loc)
        s += 0.25
    margin, cap, d, px, py, shared, loc = worst
    ok = margin >= 0
    fail = fail or not ok
    L.append("| %s | %s | %.2f | %d | %.1f | %d | %+.1f | %s | %d | %s | %s |" % (
        cid, lay, c["width"], own_n, d, cap, margin, ",".join(shared) or "-", loc, fmt(px, py),
        "ok" if margin >= 2 else "ok, TIGHT" if ok else "OVER CAPACITY"))
L += ["", "A corridor with margin below 2, or with local nets at its narrowest station, often fails in routing: "
      "nets must enter and leave in order, and the local nets take tracks. Prefer margin >= 2.", ""]

# ---------------------------------------------------------------- 4. solo routability
L += ["## 4. Solo routability", ""]
RT = Router(C)
blocked = []
for net in sorted(C.routable):
    if C.connections(net) == 0:
        continue
    _, un = RT.route_net(net, solo=True)
    un = [k for k in un if k[0] != "locked"]
    if un:
        pcs = {(p[0], p[1]): p for p in C.pad_centres(net)}
        blocked.append("%s [group %s, mode %s, route %s, escape %.1f]: cannot reach %s" % (
            net, C.assign[net]["group"], C.assign[net]["mode"], C.assign[net]["route"], C.assign[net]["escape"],
            ", ".join("%s.%s at %s" % (k[0], k[1], fmt(pcs[k][2], pcs[k][3])) for k in un if k in pcs)))
if blocked:
    fail = True
    L += ["- " + b for b in blocked]
    L += ["", "Each net above fails with the board to itself. Extend a corridor to the pad, raise `escape` until the "
          "disc contains a via site, add a layer, or widen `margin`."]
else:
    L.append("Every net routes alone inside its allowed region.")
L.append("")

# ---------------------------------------------------------------- 5. crossings on one layer
L += ["## 5. Crossings held on one layer", ""]


def single_layer(net):
    a = C.assign[net]
    if a.get("layers") and len(a["layers"]) == 1:
        return a["layers"][0]
    if a["mode"] == "corridor":
        ls = {l for cid, _ in C.flat_route(a["route"]) if cid in corr for l in corr[cid]["layers"]}
        if len(ls) == 1:
            return C.LAYERS[next(iter(ls))]
    return None


sl = {net: single_layer(net) for net in C.routable}
segs = [(net, s) for net in C.routable if sl[net] for s in C.mst(net)]
pairs = Counter()
for a_ in range(len(segs)):
    na, sa = segs[a_]
    for b_ in range(a_ + 1, len(segs)):
        nb, sb = segs[b_]
        if na != nb and sl[na] == sl[nb] and seg_cross(sa, sb):
            pairs[tuple(sorted((na, nb))) + (sl[na],)] += 1
if pairs:
    L += ["The straight-line trees of these net pairs cross, and the plan holds both nets on the same single layer. "
          "Each pair needs a bridge: let one net of the pair use a second layer, or expect a longer detour.", "",
          "| Net | Net | Layer |", "|---|---|---|"]
    L += ["| %s | %s | %s |" % k for k in sorted(pairs)[:40]]
    if len(pairs) > 40:
        L.append("| ... %d more | | |" % (len(pairs) - 40))
else:
    L.append("None.")
L.append("")

# ---------------------------------------------------------------- 6. congestion estimate
G = 2.0
gx, gy = int(math.ceil((C.bx1 - C.bx0) / G)), int(math.ceil((C.by1 - C.by0) / G))
k = max(int(round(G / R)), 1)
supply = np.zeros((gy, gx))
for l in range(NL):
    f = (C.ownT[l] == FREE)
    for a_ in range(gy):
        for b_ in range(gx):
            blk = f[a_ * k:(a_ + 1) * k, b_ * k:(b_ + 1) * k]
            if blk.size:
                supply[a_, b_] += blk.mean() * G / C.pitch
demand = np.zeros((gy, gx))
for net in C.routable:
    cells = set()
    for (x1, y1, x2, y2) in C.mst(net):
        n = max(int(math.hypot(x2 - x1, y2 - y1) / (G / 4)), 1)
        for t in range(n + 1):
            x, y = x1 + (x2 - x1) * t / n, y1 + (y2 - y1) * t / n
            cells.add((min(int((y - C.by0) / G), gy - 1), min(int((x - C.bx0) / G), gx - 1)))
    for c_ in cells:
        demand[c_] += 1
util = np.where(supply >= 2.0, demand / np.maximum(supply, 2.0), 0.0)   # cells with no free copper are walls
hot = sorted(((util[a_, b_], a_, b_) for a_ in range(gy) for b_ in range(gx) if util[a_, b_] >= 0.6), reverse=True)[:12]
L += ["## 6. Congestion estimate (information)", "",
      "The board is cut into %.0f mm cells. Supply = tracks that fit through a cell on all routing layers. Demand = "
      "nets whose straight-line tree passes through the cell. A cell above about 0.6 is a likely bottleneck: plan a "
      "corridor around it or put the flows that cross there on different layers." % G, ""]
if hot:
    L += ["| Cell centre | Demand (nets) | Supply (tracks) | Utilisation |", "|---|---|---|---|"]
    for u, a_, b_ in hot:
        L.append("| %s | %d | %.0f | %.2f |" % (fmt(C.bx0 + (b_ + 0.5) * G, C.by0 + (a_ + 0.5) * G), demand[a_, b_],
                                              supply[a_, b_], u))
else:
    L.append("No cell above 0.6.")
L += ["", "## Result", "", "FAIL: fix the plan (or report the placement) and run this check again." if fail
      else "PASS: the plan may be routed."]
txt = "\n".join(L) + "\n"
if out:
    open(out, "w", encoding="utf-8").write(txt)
print(txt)
sys.exit(1 if fail else 0)
