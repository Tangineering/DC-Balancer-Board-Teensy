"""Flow table: which regions of the board exchange signals, how many nets each flow has, and which flows cross.

Usage (venv with numpy + shapely):
  python flows.py <model.json> <plan.json> [<flows.md>]

The plan needs only `frame`, `rules`, `keep_nets` / `plane_net` and a `regions` list at this stage:
  "regions": [{"name": "TABX", "polygon": [[x, y], ...]}, {"name": "LOGIC", "box": [x0, y0, x1, y1]}]
A pad that lies in no region is in region "-". A flow is the set of regions that a net touches. The script counts
the nets and connections of each flow and the crossings between flows (straight-line trees). Two flows that cross
many times need different layers; a flow with many nets needs a corridor of that capacity."""
import sys
from collections import Counter, defaultdict

from shapely.geometry import Point, Polygon, box

from core import Ctx
from engine import seg_cross

C = Ctx(sys.argv[1], sys.argv[2])
out = sys.argv[3] if len(sys.argv) > 3 else None
regs = []
for r in C.P.get("regions", []):
    if "box" in r:
        (x0, y0), (x1, y1) = C.k(r["box"][:2]), C.k(r["box"][2:])
        g = box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    else:
        g = Polygon([C.k(p) for p in r["polygon"]]).buffer(0)
    regs.append((r["name"], g))


def region(x, y):
    p = Point(x, y)
    for name, g in regs:
        if g.contains(p):
            return name
    return "-"


flow_of, flows = {}, defaultdict(list)
for net in sorted(C.routable):
    pcs = C.pad_centres(net)
    if len(pcs) < 2:
        continue
    f = "-".join(sorted({region(p[2], p[3]) for p in pcs}))
    flow_of[net] = f
    flows[f].append(net)
segs = [(net, s) for net in flow_of for s in C.mst(net)]
cross = Counter()
net_cross = Counter()
for a in range(len(segs)):
    na, sa = segs[a]
    for b in range(a + 1, len(segs)):
        nb, sb = segs[b]
        if na != nb and seg_cross(sa, sb):
            cross[tuple(sorted((flow_of[na], flow_of[nb])))] += 1
            net_cross[na] += 1
            net_cross[nb] += 1
L = ["# Flow table", "",
     "Regions: %s. Region \"-\" = pads outside every region." % (", ".join(n for n, _ in regs) or "none defined"), "",
     "| Flow (regions touched) | Nets | Connections | Largest net (pads) | Nets |", "|---|---|---|---|---|"]
for f, nets in sorted(flows.items(), key=lambda kv: -len(kv[1])):
    big = max(nets, key=lambda n: C.npads[n])
    L.append("| %s | %d | %d | %s (%d) | %s |" % (f, len(nets), sum(C.connections(n) for n in nets), big, C.npads[big],
                                                " ".join(nets)))
L += ["", "A flow inside one region (one name) is local: leave it to mode `local` unless it has many pads.", "",
      "## Crossings between flows", "",
      "Count of crossing pairs of straight-line tree segments. Flows that cross need different layers, or one of them "
      "needs a bridge.", "", "| Flow | Flow | Crossings |", "|---|---|---|"]
for (fa, fb), n in sorted(cross.items(), key=lambda kv: -kv[1])[:30]:
    L.append("| %s | %s | %d |" % (fa, fb, n))
if not cross:
    L.append("| none | | |")
L += ["", "## Nets with the most crossings", "",
      ", ".join("%s %d" % kv for kv in net_cross.most_common(15)) or "none"]
txt = "\n".join(L) + "\n"
if out:
    open(out, "w", encoding="utf-8").write(txt)
print(txt)
