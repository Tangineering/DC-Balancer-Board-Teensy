"""Layer assignment from crossings: propose a preferred layer for each long net, so that nets whose straight-line
trees cross sit on different layers.

Usage (venv with numpy + shapely):
  python layer_assign.py <model.json> <plan.json> <out_plan.json> [--report layer_assign.md] [--min-length 4]
                         [--cost 2.5] [--pad-penalty 0.5] [--layer-weight B.Cu:0.3,In2.Cu:0.05]

The nets with a straight-line tree of at least --min-length mm and at least one crossing are assigned. The cost
of a net on a layer is: the crossings with the nets already on that layer, plus --pad-penalty for each pad of the
net that is not on the layer (it needs a via), plus --layer-weight times the tree length (use it to keep copper
off a layer, for example a layer that carries a ground pour on a 2-layer board). A greedy pass and repeated
single-net moves reduce the total.

Output: a copy of the plan with `net_layer_cost` added: for each assigned net, the other layers cost --cost
times more. This is a preference, not a limit: the router still changes layer where it must. The groups of the
plan are unchanged. The report lists the crossings that remain on one layer; each needs a bridge."""
import argparse
import json
from collections import Counter

from core import Ctx
from engine import seg_cross

ap = argparse.ArgumentParser()
ap.add_argument("model")
ap.add_argument("plan")
ap.add_argument("out")
ap.add_argument("--report", default=None)
ap.add_argument("--min-length", type=float, default=4.0)
ap.add_argument("--cost", type=float, default=2.5)
ap.add_argument("--pad-penalty", type=float, default=0.5)
ap.add_argument("--layer-weight", default="")
A = ap.parse_args()
C = Ctx(A.model, A.plan)
LAYERS = C.LAYERS
lw = {l: 0.0 for l in LAYERS}
for kv in [x for x in A.layer_weight.split(",") if x]:
    l, v = kv.split(":")
    lw[l] = float(v)
mst = {n: C.mst(n) for n in C.routable if C.connections(n) > 0}
length = {n: sum(((a - c) ** 2 + (b - d) ** 2) ** 0.5 for (a, b, c, d) in s) for n, s in mst.items()}
segs = [(n, s) for n, ss in mst.items() for s in ss]
W = {n: Counter() for n in mst}
for a in range(len(segs)):
    na, sa = segs[a]
    for b in range(a + 1, len(segs)):
        nb, sb = segs[b]
        if na != nb and seg_cross(sa, sb):
            W[na][nb] += 1
            W[nb][na] += 1
fixed = {}
for n in mst:                                   # a net that the plan already holds on one layer keeps it
    ls = C.assign[n].get("layers")
    if ls and len(ls) == 1:
        fixed[n] = ls[0]
cand = [n for n in sorted(mst) if n not in fixed and length[n] >= A.min_length and W[n]]
off = {}
for n in cand:
    per = Counter()
    for key, grp in C.pads_of[n].items():
        if key[0] == "locked":
            continue
        on = {ln for it in grp for ln in it["layers"]}
        for l in LAYERS:
            if l not in on:
                per[l] += 1
    off[n] = per
asg = dict(fixed)


def cost(n, l):
    return (sum(w for m, w in W[n].items() if asg.get(m) == l) + A.pad_penalty * off[n][l] + lw[l] * length[n])


for n in sorted(cand, key=lambda x: -sum(W[x].values())):
    asg[n] = min(LAYERS, key=lambda l: (cost(n, l), LAYERS.index(l)))
for _ in range(30):
    moved = 0
    for n in cand:
        cur = asg.pop(n)
        best = min(LAYERS, key=lambda l: (cost(n, l), LAYERS.index(l)))
        if cost(n, best) < cost(n, cur) - 1e-9:
            asg[n] = best
            moved += 1
        else:
            asg[n] = cur
    if not moved:
        break
P = json.load(open(A.plan))
nlc = dict(P.get("net_layer_cost", {}))
for n in cand:
    nlc[n] = {l: A.cost for l in LAYERS if l != asg[n]}
P["net_layer_cost"] = nlc
json.dump(P, open(A.out, "w"), indent=1)
total = sum(w for n in mst for w in W[n].values()) // 2
left = Counter()
pairs = []
for n in cand + list(fixed):
    for m, w in W[n].items():
        if n < m and asg.get(m) == asg[n]:
            left[asg[n]] += w
            pairs.append((w, n, m, asg[n]))
free_x = sum(w for n in mst if n not in asg for m, w in W[n].items() if m not in asg and n < m)
L = ["# Layer assignment from crossings", "",
     "Nets with a tree: %d. Assigned: %d (tree length at least %.1f mm and at least one crossing). Held on a layer "
     "by the plan: %d. Crossing pairs of tree segments on the whole board: %d." % (len(mst), len(cand), A.min_length,
                                                                                len(fixed), total), "",
     "| Layer | Nets assigned | Tree length (mm) | Crossings that remain on the layer |", "|---|---|---|---|"]
for l in LAYERS:
    ns = [n for n in cand if asg[n] == l]
    L.append("| %s | %d | %.0f | %d |" % (l, len(ns), sum(length[n] for n in ns), left[l]))
L += ["", "Crossings between nets that were not assigned (short nets): %d." % free_x, "",
      "## Crossings that remain on one layer", "",
      "Each pair needs a bridge: one of the two nets changes layer at the crossing.", "",
      "| Net | Net | Layer | Crossings |", "|---|---|---|---|"]
L += ["| %s | %s | %s | %d |" % (n, m, l, w) for (w, n, m, l) in sorted(pairs, reverse=True)[:30]] or ["| none | | | |"]
L += ["", "## Assignment", "", "| Net | Layer | Tree length (mm) | Crossings with all nets | Pads off the layer |",
      "|---|---|---|---|---|"]
L += ["| %s | %s | %.1f | %d | %d |" % (n, asg[n], length[n], sum(W[n].values()), off[n][asg[n]])
      for n in sorted(cand, key=lambda x: (asg[x], -length[x]))]
txt = "\n".join(L) + "\n"
if A.report:
    open(A.report, "w", encoding="utf-8").write(txt)
print(txt)
