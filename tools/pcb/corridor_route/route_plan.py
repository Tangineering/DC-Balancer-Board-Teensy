"""Plan-driven router: detailed routing inside the regions that a plan allows.

Usage (venv with numpy + shapely):
  python -u route_plan.py <model.json> <plan.json> <routes.json> [--iters 30] [--report route_report.md]
                          [--only-groups g1,g2] [--seed 1] [--via-cost V] [--pour-penalty P]

Stages:
 1. Negotiation. Each routable net is routed pad to pad by a negotiated-congestion grid search (PathFinder)
    inside its allowed region. A contested cell costs more each iteration until one net moves.
 2. Legalisation. Nets that still overlap are removed, one at a time, until the remaining copper is legal. The
    net removed is the one with the highest priority number; among equals, the one that conflicts with the most
    nets per connection it carries.
 3. Recovery. Each removed net is routed again with all kept copper as hard obstacles. Whatever connects is
    kept (a net may be kept in part); the pads that stay open are reported.
 4. Diagnosis. Each open net is routed alone on the empty board. A net that fails alone is BLOCKED (its allowed
    region does not connect its pads); a net that routes alone is CONGESTED, and the report names the nets and
    the place that it lost to.
The output never contains a clearance violation between routed nets."""
import argparse
import json
import random
import time
from collections import Counter

from shapely.geometry import Point

from core import Ctx
from engine import Router

ap = argparse.ArgumentParser()
ap.add_argument("model")
ap.add_argument("plan")
ap.add_argument("out")
ap.add_argument("--iters", type=int, default=30)
ap.add_argument("--via-cost", type=float, default=None)
ap.add_argument("--pour-penalty", type=float, default=None)
ap.add_argument("--report", default=None)
ap.add_argument("--only-groups", default="")
ap.add_argument("--seed", type=int, default=1)
A = ap.parse_args()
random.seed(A.seed)
t0 = time.time()
C = Ctx(A.model, A.plan)
if C.plan_errors:
    raise SystemExit("plan errors:\n  " + "\n  ".join(C.plan_errors))
RT = Router(C, A.via_cost, A.pour_penalty)
R, NL = C.R, C.NL
LAYERS = C.LAYERS
only = {g for g in A.only_groups.split(",") if g}
todo_nets = [n for n in sorted(C.routable) if (not only or C.assign[n]["group"] in only) and C.connections(n) > 0]
total_conn = sum(C.connections(n) for n in todo_nets)
print("grid %d x %d x %d (res %.4f, pitch %.3f), nets %d, connections %d, %.1f s" % (
    C.nx, C.ny, NL, R, C.pitch, len(todo_nets), total_conn, time.time() - t0), flush=True)

cross = RT.crossing_counts(todo_nets)
order = sorted(todo_nets, key=lambda net: (C.assign[net]["priority"], len(cross[net]), C.npads[net]))
routes, unreached = RT.routes, RT.unreached
bad = set()
history = []
for it_ in range(A.iters):
    todo = order if it_ == 0 else [n_ for n_ in order if n_ in bad or unreached.get(n_)]
    if it_ > 0:
        random.shuffle(todo)
        todo.sort(key=lambda net: C.assign[net]["priority"])
    for net in todo:
        if net in routes:
            RT.contribute(net, routes[net], -1.0)
        r, un = RT.route_net(net)
        routes[net] = r
        unreached[net] = un
        RT.contribute(net, r, +1.0)
    bad = set()
    for net, r in routes.items():
        RT.contribute(net, r, -1.0)
        cc = RT.conflict_cells(net, r)
        if cc:
            bad.add(net)
            for (l, j, i) in cc:
                if l >= 0:
                    RT.hist[l, j, i] += 0.5
                else:
                    RT.hist[:, j, i] += 0.5
        RT.contribute(net, r, +1.0)
    RT.pres *= 1.6
    nopath = sum(1 for n_ in routes if unreached.get(n_))
    history.append((it_, len(todo), len(bad), nopath))
    print("iter %d: rerouted %d, in conflict %d, with open pads %d, %.0f s" % (it_, len(todo), len(bad), nopath,
                                                                             time.time() - t0), flush=True)
    if not bad:
        break

# ---------------------------------------------------------------- legalise
kept = set(routes)
cellmap, viamap = RT.maps(kept)
conf, cc_of = {}, {}
for net in kept:
    RT.contribute(net, routes[net], -1.0)
    cc = RT.conflict_cells(net, routes[net])
    RT.contribute(net, routes[net], +1.0)
    if cc:
        cc_of[net] = cc
        conf[net] = RT.partners(net, cc, cellmap, viamap)
lost_to = {}
while conf:
    net = max(conf, key=lambda x: (C.assign[x]["priority"], len(conf[x]) / max(1, C.connections(x)), len(cc_of[x])))
    lost_to[net] = (sorted(conf[net]), cc_of[net])
    RT.contribute(net, routes[net], -1.0)
    kept.discard(net)
    del conf[net]
    cellmap, viamap = RT.maps(kept)
    for other in list(conf):
        RT.contribute(other, routes[other], -1.0)
        cc = RT.conflict_cells(other, routes[other])
        RT.contribute(other, routes[other], +1.0)
        if cc:
            cc_of[other] = cc
            conf[other] = RT.partners(other, cc, cellmap, viamap)
        else:
            del conf[other]
print("legalised: kept %d, removed %d, %.0f s" % (len(kept), len(lost_to), time.time() - t0), flush=True)

# ---------------------------------------------------------------- recovery: removed nets against hard obstacles
recovered = []
for net in sorted(lost_to, key=lambda x: (C.assign[x]["priority"], -C.connections(x))):
    r, un = RT.route_net(net, hard=True)
    routes[net] = r
    unreached[net] = un
    if r[0]:
        RT.contribute(net, r, +1.0)
        kept.add(net)
        if not un:
            recovered.append(net)
for net in sorted(kept, key=lambda x: (C.assign[x]["priority"], -C.connections(x))):
    if unreached.get(net) and net not in lost_to:      # a kept net with open pads: try the open pads once more
        RT.contribute(net, routes[net], -1.0)
        r, un = RT.route_net(net, hard=True)
        if len(un) < len(unreached[net]):
            routes[net], unreached[net] = r, un
        RT.contribute(net, routes[net], +1.0)
print("recovery: %d removed nets fully recovered, %.0f s" % (len(recovered), time.time() - t0), flush=True)

# ---------------------------------------------------------------- diagnosis of open nets
open_nets = [n for n in todo_nets if unreached.get(n) or n not in kept]
diag = {}
for net in open_nets:
    _, un = RT.route_net(net, solo=True)
    diag[net] = "BLOCKED" if un else "CONGESTED"


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
conn_made = 0
length = Counter()
nvias = 0
for net in todo_nets:
    if net not in kept or not routes[net][0]:
        continue
    cells, vias = routes[net]
    trk = to_copper(cells)
    w = RT.width(net)
    vs = sorted(set(vias))
    un = unreached.get(net, [])
    conn_made += C.connections(net) - len(un)
    nvias += len(vs)
    for (ln, xa, ya, xb, yb) in trk:
        length[(C.assign[net]["group"], ln)] += ((xa - xb) ** 2 + (ya - yb) ** 2) ** 0.5
    results.append(dict(net=net, replace=True, tracks=[list(t) for t in trk], widths=[w] * len(trk),
                        vias=[[C.bx0 + i * R, C.by0 + j * R] for (j, i) in vs], via_d=[C.via] * len(vs),
                        open_pads=["%s.%s" % k for k in un if k[0] != "locked"]))
full = [n for n in todo_nets if n in kept and not unreached.get(n)]
summary = dict(nets=len(todo_nets), nets_complete=len(full), connections=total_conn, connections_made=conn_made,
               vias=nvias, iterations=len(history), seconds=round(time.time() - t0),
               blocked=sorted(n for n in diag if diag[n] == "BLOCKED"),
               congested=sorted(n for n in diag if diag[n] == "CONGESTED"))
json.dump(dict(results=results, open=sorted(open_nets), summary=summary,
               params=dict(track=C.track, clear=C.clear, via=C.via, drill=C.drill, res=R)), open(A.out, "w"))

# ---------------------------------------------------------------- report
corr = C.corridors()


def where(l, j, i):
    x, y = C.xy(j, i)
    ids = [cid for cid, c in corr.items() if (l < 0 or l in c["layers"]) and c["geom"].contains(Point(x, y))]
    return "%s (%.1f, %.1f)%s" % (("via" if l < 0 else LAYERS[l],) + C.d(x, y) + ((" in " + "/".join(ids)) if ids else "",))


def padtxt(net, keys):
    pcs = {(p[0], p[1]): p for p in C.pad_centres(net)}
    return ", ".join("%s.%s at (%.1f, %.1f)" % ((k[0], k[1]) + C.d(pcs[k][2], pcs[k][3])) for k in keys if k in pcs)


L = ["# Routing report", "",
     "Connections made: %d of %d. Nets complete: %d of %d. Vias: %d. Iterations: %d. Run time: %d s." % (
         conn_made, total_conn, len(full), len(todo_nets), nvias, len(history), time.time() - t0),
     "Rules: track %.3f, clearance %.3f, via %.2f/%.2f, grid %.4f, track pitch %.3f mm." % (
         C.track, C.clear, C.via, C.drill, R, C.pitch), "",
     "A connection is one pad-to-pad link; a net with n pads has n - 1 connections. Count connections, not nets.", "",
     "## By group", "", "| Group | Nets | Complete | Connections made / total | Track length by layer (mm) |",
     "|---|---|---|---|---|"]
groups = {}
for net in todo_nets:
    g = groups.setdefault(C.assign[net]["group"], [0, 0, 0, 0])
    g[0] += 1
    g[1] += 1 if net in full else 0
    g[2] += (C.connections(net) - len(unreached.get(net, []))) if net in kept and routes[net][0] else 0
    g[3] += C.connections(net)
for name, g in sorted(groups.items()):
    ll = ", ".join("%s %.0f" % (ln, length[(name, ln)]) for ln in LAYERS if length[(name, ln)] > 0)
    L.append("| %s | %d | %d | %d / %d | %s |" % (name, g[0], g[1], g[2], g[3], ll))
L += ["", "## Open nets", "",
      "BLOCKED: the net does not route even alone. Its allowed region does not connect its pads: a corridor does "
      "not reach the pad's escape disc, no via site exists where it must change layer, a pour or keep-out seals "
      "the pad, or the layer list is too narrow. Repair the plan entry or report the placement.",
      "CONGESTED: the net routes alone but lost its space to the nets named. Repair by priority, layer, corridor "
      "width or a second corridor at the place named.", "",
      "| Net | Group | Class | Open pads | Lost to | Where |", "|---|---|---|---|---|---|"]
for net in sorted(open_nets, key=lambda x: (diag[x], C.assign[x]["group"], x)):
    a = C.assign[net]
    un = [k for k in unreached.get(net, []) if k[0] != "locked"]
    part, cc = lost_to.get(net, ([], []))
    pts = sorted({where(l, j, i) for (l, j, i) in cc[:: max(1, len(cc) // 4)]})[:3]
    state = "all" if (net not in kept or not routes[net][0]) else padtxt(net, un)
    L.append("| %s | %s | %s | %s | %s | %s |" % (net, a["group"], diag[net], state, ", ".join(part[:6]) +
                                                 (" (+%d)" % (len(part) - 6) if len(part) > 6 else ""), "; ".join(pts)))
if not open_nets:
    L.append("| none | | | | | |")
L += ["", "## Negotiation history", "", "| Iteration | Rerouted | In conflict | With open pads |", "|---|---|---|---|"]
L += ["| %d | %d | %d | %d |" % h for h in history]
L += ["", "A conflict count that stays flat for many iterations means a channel is full: more iterations will not "
      "help; change the plan.", "",
      "## Recovery", "", "Removed in legalisation: %d. Fully recovered: %d (%s)." % (
          len(lost_to), len(recovered), ", ".join(recovered) or "none")]
txt = "\n".join(L) + "\n"
if A.report:
    open(A.report, "w", encoding="utf-8").write(txt)
print(txt)
