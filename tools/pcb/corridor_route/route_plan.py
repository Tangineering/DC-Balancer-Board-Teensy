"""Plan-driven router: detailed routing inside the regions that a plan allows.

Usage (venv with numpy + shapely):
  python -u route_plan.py <model.json> <plan.json> <routes.json> [--report route_report.md] [--iters 20]
                          [--seed 1] [--max-seconds S] [--patience 8] [--keep-routes prev_routes.json]
                          [--only-groups g1,g2] [--via-cost V] [--pour-penalty P]

Stages:
 1. Negotiation. Each routable net is routed pad to pad by a negotiated-congestion grid search (PathFinder)
    inside its allowed region. A contested cell costs more each iteration until one net moves. The conflict count
    normally stays near flat for the first 6 to 8 iterations and falls after that. The loop ends at --iters, when
    no conflict is left, when the best count has not improved for --patience iterations (after iteration 10), or
    at --max-seconds; the later stages always run, so a time limit still gives a legal result.
 2. Legalisation. Nets that still overlap are removed, one at a time, until the remaining copper is legal. The
    net removed is the one with the highest priority number; among equals, the one that conflicts with the most
    nets per connection it carries.
 3. Recovery. Each removed net is routed again with all kept copper as hard obstacles. Whatever connects is
    kept (a net may be kept in part); the pads that stay open are reported.
 4. Diagnosis. Each open net is routed alone on the empty board. A net that fails alone is BLOCKED; a net that
    routes alone is CONGESTED, and the report names the nets and the place that it lost to.
The output never contains a clearance violation between routed nets.

--keep-routes: the nets that were complete in an earlier routes.json (same model, same grid) are kept exactly
as they were and are obstacles; only the other nets are routed. Use it to repair open nets without losing nets
that already routed.
--seed: the order of rerouting is random after the first iteration. Two seeds of one plan differ by a few
connections; compare plans on two seeds before claiming a difference smaller than that."""
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
ap.add_argument("--iters", type=int, default=20)
ap.add_argument("--via-cost", type=float, default=None)
ap.add_argument("--pour-penalty", type=float, default=None)
ap.add_argument("--report", default=None)
ap.add_argument("--only-groups", default="")
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--max-seconds", type=float, default=0)
ap.add_argument("--patience", type=int, default=8)
ap.add_argument("--keep-routes", default=None)
A = ap.parse_args()
random.seed(A.seed)
import os
for f_ in (A.out, A.report):                # the output folders must exist before a long run starts
    if f_ and os.path.dirname(f_):
        os.makedirs(os.path.dirname(f_), exist_ok=True)
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
routes, unreached = RT.routes, RT.unreached

fixed = set()
if A.keep_routes:
    K = json.load(open(A.keep_routes))
    if abs(K["params"]["res"] - R) > 1e-9:
        raise SystemExit("--keep-routes: grid %.4f differs from this plan's grid %.4f" % (K["params"]["res"], R))
    for r in K["results"]:
        if r["net"] in todo_nets and not r.get("open_pads") and "cells" in r:
            # keep the net only if its old copper is still legal on this model (a part may have moved)
            n_ = C.nid(r["net"])
            cs_ = {tuple(c) for c in r["cells"]}
            legal = all(C.ownT[c] in (-1, n_) for c in cs_) and all(
                cs_ & set(pc) for k_, pc in C.padcells.get(r["net"], {}).items() if k_[0] != "locked")
            if not legal:
                continue
            routes[r["net"]] = ([tuple(c) for c in r["cells"]], [tuple(v) for v in r["via_cells"]])
            RT.paths_of[r["net"]] = [[tuple(c) for c in p] for p in r["paths"]]
            unreached[r["net"]] = []
            RT.contribute(r["net"], routes[r["net"]], +1.0)
            fixed.add(r["net"])
    RT.freeze()
print("grid %d x %d x %d (res %.4f, pitch %.3f), nets %d (%d kept from an earlier run), connections %d, %.1f s" % (
    C.nx, C.ny, NL, R, C.pitch, len(todo_nets), len(fixed), total_conn, time.time() - t0), flush=True)
if C.grid_sealed:
    print("warning: %d pads have no legal track start at this grid (see capacity.py check 1)" % len(C.grid_sealed))

cross = RT.crossing_counts(todo_nets)
order = [n for n in sorted(todo_nets, key=lambda net: (C.assign[net]["priority"], len(cross[net]), C.npads[net]))
         if n not in fixed]
bad = set()
history = []
best, best_it, stop_why = None, 0, "iteration limit"
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
        if net in fixed:
            continue
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
    if best is None or len(bad) < best:
        best, best_it = len(bad), it_
    if not bad:
        stop_why = "no conflict left"
        break
    if it_ >= 10 and it_ - best_it >= A.patience:
        stop_why = "no improvement for %d iterations" % A.patience
        break
    if A.max_seconds and time.time() - t0 > A.max_seconds:
        stop_why = "time limit %.0f s" % A.max_seconds
        break
print("negotiation ended: %s" % stop_why, flush=True)

# ---------------------------------------------------------------- legalise
kept = set(routes)
cellmap, viamap = RT.maps(kept)
conf, cc_of = {}, {}
for net in kept - fixed:
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
for net in sorted(kept - fixed, key=lambda x: (C.assign[x]["priority"], -C.connections(x))):
    if unreached.get(net) and net not in lost_to:      # a kept net with open pads: try the open pads once more
        RT.contribute(net, routes[net], -1.0)
        old_paths = RT.paths_of.get(net)
        r, un = RT.route_net(net, hard=True)
        if len(un) < len(unreached[net]):
            routes[net], unreached[net] = r, un
        else:
            RT.paths_of[net] = old_paths
        RT.contribute(net, routes[net], +1.0)
print("recovery: %d removed nets fully recovered, %.0f s" % (len(recovered), time.time() - t0), flush=True)

# ---------------------------------------------------------------- diagnosis of open nets
open_nets = [n for n in todo_nets if unreached.get(n) or n not in kept]
diag = {}
for net in open_nets:
    saved = RT.paths_of.get(net)
    _, un = RT.route_net(net, solo=True)
    RT.paths_of[net] = saved
    diag[net] = "BLOCKED" if un else "CONGESTED"


# ---------------------------------------------------------------- copper: prune dangling ends, merge runs
def copper(net):
    """(tracks [(layer, xa, ya, xb, yb)], via cells [(j, i)]) from the net's paths, without dangling ends"""
    adj = {}
    for path in RT.paths_of.get(net, []):
        for a, b in zip(path[:-1], path[1:]):
            if a != b:
                adj.setdefault(a, set()).add(b)
                adj.setdefault(b, set()).add(a)
    protect = set()
    for key, cs in C.padcells.get(net, {}).items():
        protect |= set(cs)
    leaves = [n_ for n_, nb in adj.items() if len(nb) == 1 and n_ not in protect]
    while leaves:
        n_ = leaves.pop()
        if n_ not in adj or len(adj[n_]) != 1 or n_ in protect:
            continue
        (m,) = adj.pop(n_)
        adj[m].discard(n_)
        if len(adj[m]) == 1 and m not in protect:
            leaves.append(m)
        elif not adj[m]:
            adj.pop(m)
    vias = sorted({(a[1], a[2]) for a, nb in adj.items() for b in nb if a[0] != b[0]})
    tracks = []
    for d in ((0, 1), (1, 0), (1, 1), (1, -1)):
        for a in sorted(adj):
            nxt = (a[0], a[1] + d[0], a[2] + d[1])
            prv = (a[0], a[1] - d[0], a[2] - d[1])
            if nxt in adj[a] and not (prv in adj and a in adj[prv]):
                e = nxt
                while True:
                    n2 = (e[0], e[1] + d[0], e[2] + d[1])
                    if n2 in adj.get(e, ()):
                        e = n2
                    else:
                        break
                xa, ya = C.xy(a[1], a[2])
                xb, yb = C.xy(e[1], e[2])
                tracks.append((LAYERS[a[0]], xa, ya, xb, yb))
    return tracks, vias


results = []
conn_made = 0
length = Counter()
nvias = 0
stats = {}
for net in todo_nets:
    if net not in kept or not routes[net][0]:
        continue
    trk, vs = copper(net)
    w = RT.width(net)
    un = unreached.get(net, [])
    conn_made += C.connections(net) - len(un)
    nvias += len(vs)
    per = Counter()
    for (ln, xa, ya, xb, yb) in trk:
        d = ((xa - xb) ** 2 + (ya - yb) ** 2) ** 0.5
        length[(C.assign[net]["group"], ln)] += d
        per[ln] += d
    stats[net] = dict(length=round(sum(per.values()), 2), by_layer={k: round(v, 2) for k, v in per.items()},
                      vias=len(vs), open=len(un))
    results.append(dict(net=net, replace=True, tracks=[list(t) for t in trk], widths=[w] * len(trk),
                        vias=[list(C.xy(j, i)) for (j, i) in vs], via_d=[C.via] * len(vs),
                        open_pads=["%s.%s" % k for k in un if k[0] != "locked"],
                        cells=[list(c) for c in routes[net][0]], via_cells=[list(v) for v in routes[net][1]],
                        paths=[[list(c) for c in p] for p in RT.paths_of.get(net, [])]))
full = [n for n in todo_nets if n in kept and not unreached.get(n)]
summary = dict(nets=len(todo_nets), nets_complete=len(full), connections=total_conn, connections_made=conn_made,
               vias=nvias, iterations=len(history), seconds=round(time.time() - t0), seed=A.seed, stopped=stop_why,
               blocked=sorted(n for n in diag if diag[n] == "BLOCKED"),
               congested=sorted(n for n in diag if diag[n] == "CONGESTED"))
json.dump(dict(results=results, open=sorted(open_nets), routed_nets=todo_nets, summary=summary, net_stats=stats,
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
     "Connections made: %d of %d. Nets complete: %d of %d. Vias: %d. Iterations: %d (%s). Seed: %d. Run time: %d s." % (
         conn_made, total_conn, len(full), len(todo_nets), nvias, len(history), stop_why, A.seed, time.time() - t0),
     "Rules: track %.3f, clearance %.3f, via %.2f/%.2f, grid %.4f, track pitch %.3f mm." % (
         C.track, C.clear, C.via, C.drill, R, C.pitch), "",
     "A connection is one pad-to-pad link; a net with n pads has n - 1 connections. Count connections, not nets. "
     "Two seeds of one plan differ by a few connections.", "",
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
prio1 = [n for n in todo_nets if C.assign[n]["priority"] <= 1]
if prio1:
    L += ["", "## Priority-1 nets (constrained nets and rails): routed geometry", "",
          "Check each row against the design limit of the net (length, layer, vias). The straight-line length is the "
          "length of the net's minimum spanning tree.", "",
          "| Net | Group | Routed length (mm) | Straight-line (mm) | Vias | Length by layer | Open |", "|---|---|---|---|---|---|---|"]
    for n in sorted(prio1):
        st = stats.get(n)
        mst = sum(((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5 for (x1, y1, x2, y2) in C.mst(n))
        if st:
            L.append("| %s | %s | %.1f | %.1f | %d | %s | %d |" % (n, C.assign[n]["group"], st["length"], mst, st["vias"],
                                                               ", ".join("%s %.1f" % kv for kv in st["by_layer"].items()),
                                                               st["open"]))
        else:
            L.append("| %s | %s | not routed | %.1f | - | - | all |" % (n, C.assign[n]["group"], mst))
L += ["", "## Negotiation history", "", "| Iteration | Rerouted | In conflict | With open pads |", "|---|---|---|---|"]
L += ["| %d | %d | %d | %d |" % h for h in history]
L += ["", "The count normally stays near flat for the first 6 to 8 iterations and then falls. A count that is still "
      "flat after iteration 12 means the board or a channel is full: more iterations will not help; change the plan.",
      "", "## Recovery", "", "Removed in legalisation: %d. Fully recovered: %d (%s). Kept from an earlier run: %d." % (
          len(lost_to), len(recovered), ", ".join(recovered) or "none", len(fixed))]
txt = "\n".join(L) + "\n"
if A.report:
    open(A.report, "w", encoding="utf-8").write(txt)
print(txt)
