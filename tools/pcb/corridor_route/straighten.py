"""Straightening pass: replace staircases of routed tracks by straight and 45-degree runs where nothing is in the way.

Usage (pcbnew venv):
  python straighten.py <board.kicad_pcb> <out dir> [--plan plan.json] [--clear C] [--edge-clear E]
                       [--nets /A,/B] [--report STRAIGHTEN.md] [--routes-out routes_st.json]

The grid router steps from cell to cell, and the costs vary from cell to cell, so a free stretch of track often
comes out as a staircase of short steps. This pass works on the finished board (after the plane-via and stitching
steps) and changes only unlocked tracks of signal nets; it never moves a via, a pad or a locked track.

For each net and copper layer the tracks form chains between anchors (a pad, a via, a junction of three or more
tracks, an end). Along each chain the pass replaces the longest run P[i]..P[j] that it can by one segment (when
P[i] and P[j] lie on a straight or 45-degree line) or by two segments (one 45-degree and one straight, either
order), and repeats from P[j]. A replacement is kept only when all of these hold:

- its copper keeps the clearance (--clear, default the plan's rules.clear) from the copper of every other net on
  the layer: pads, tracks, vias, holes (plated-hole-to-copper 0.254 mm at least) and the hard pours of other nets
  (a fill of priority 1 or below, such as a ground fill, refills around it);
- it stays --edge-clear inside the board outline and outside every keep-out rule area that forbids tracks;
- it keeps the thermal ring (rules.thermal_keepout) of the through-hole pads of poured nets, unless the old run
  already entered that ring, and keeps off the unflashed layers of its own net's through-hole pads;
- it does not add length inside a reserved plan corridor that the net is not assigned to (the divider-top zones of
  a soft keep-away rule, with --plan);
- every bend of the new chain turns by 90 degrees or less (no acute angle).

Hard spots stay as they are. Run DRC (score.py against the unrouted board) on the result: it must stay valid, and
the open connections of the plane nets must not rise (a straightened track can cut a ground fill differently).

Output: <out dir>/<board>.kicad_pcb (zones refilled), the report, and with --routes-out a routes file with the
straightened tracks of the changed nets (for parallel_metric.py; it has no grid cells).
"""
import argparse
import json
import math
import os
import shutil
from collections import defaultdict

import pcbnew
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

ap = argparse.ArgumentParser()
ap.add_argument("board")
ap.add_argument("out")
ap.add_argument("--plan", default=None)
ap.add_argument("--clear", type=float, default=None)
ap.add_argument("--edge-clear", type=float, default=0.381)
ap.add_argument("--hole-clear", type=float, default=0.254)
ap.add_argument("--nets", default="")
ap.add_argument("--report", default=None)
ap.add_argument("--routes-out", default=None)
A = ap.parse_args()
mm, FMM = pcbnew.ToMM, pcbnew.FromMM
P = json.load(open(A.plan)) if A.plan else {}
rules = P.get("rules", {})
CLEAR = (A.clear if A.clear is not None else rules.get("clear", 0.127)) + 0.002
THERM = rules.get("thermal_keepout", 0.35)
Y0 = (P.get("frame") or {}).get("y_flip_offset")
planes = set([P["plane_net"]] if isinstance(P.get("plane_net"), str) else P.get("plane_net") or [])
only = {n for n in A.nets.split(",") if n}
EPS = 1e-3


def poly_of(sps):
    out = []
    for i in range(sps.OutlineCount()):
        o = sps.Outline(i)
        pts = [(mm(o.CPoint(k).x), mm(o.CPoint(k).y)) for k in range(o.PointCount())]
        hs = []
        for h in range(sps.HoleCount(i)):
            ho = sps.Hole(i, h)
            hs.append([(mm(ho.CPoint(k).x), mm(ho.CPoint(k).y)) for k in range(ho.PointCount())])
        if len(pts) >= 3:
            out.append(Polygon(pts, [h for h in hs if len(h) >= 3]).buffer(0))
    return unary_union(out) if out else Polygon()


b = pcbnew.LoadBoard(A.board)
TRACKS, ZONES = list(b.GetTracks()), list(b.Zones())
lname = {b.GetLayerName(l): l for l in range(pcbnew.PCB_LAYER_ID_COUNT) if b.GetLayerName(l)}
cu_layers = [n for n in ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu") if n in lname]
sps = pcbnew.SHAPE_POLY_SET()
b.GetBoardPolygonOutlines(sps)
edge = poly_of(sps)

# reserved plan corridors (plan frame -> KiCad frame)
reserve = []
if P.get("corridors"):
    assigned = defaultdict(set)
    for g in P.get("groups", []):
        for cid in (g.get("route") or []):
            for c in (cid if isinstance(cid, list) else [cid]):
                for n in g["nets"]:
                    assigned[n].add(c)
    for c in P["corridors"]:
        if not c.get("reserve") or "polygon" not in c:
            continue
        pts = [(x, Y0 - y) if Y0 is not None else (x, y) for x, y in c["polygon"]]
        reserve.append((c["id"], set(c.get("layers") or [c.get("layer")]), Polygon(pts).buffer(0)))
else:
    assigned = {}

# per-layer obstacles: (net, geometry, clearance)
obst = defaultdict(list)
therm = defaultdict(list)          # layer -> (net, ring geometry) of through-hole pads of poured nets
selfban = defaultdict(list)        # (net, layer) -> unflashed own pads
zone_net_layers = {(z.GetNetname(), b.GetLayerName(l)) for z in ZONES if not z.GetIsRuleArea()
                   for l in z.GetLayerSet().Seq()}
for fp in b.GetFootprints():
    for p in fp.Pads():
        net = p.GetNetname()
        drill = mm(p.GetDrillSizeX())
        c = p.GetPosition()
        for ln in cu_layers:
            lid = lname[ln]
            if p.IsOnLayer(lid) and p.FlashLayer(lid):
                g = poly_of(p.GetEffectivePolygon(lid, pcbnew.ERROR_INSIDE))
                obst[ln].append((net, g, CLEAR))
                if drill > 0 and (net, ln) in zone_net_layers and drill >= 0.6:
                    therm[ln].append((net, g.buffer(CLEAR + THERM)))
            elif drill > 0 and p.IsOnLayer(lid):
                ls = [l for l in cu_layers if p.IsOnLayer(lname[l]) and p.FlashLayer(lname[l])]
                if ls:
                    selfban[(net, ln)].append(poly_of(p.GetEffectivePolygon(lname[ls[0]], pcbnew.ERROR_INSIDE)))
            if drill > 0:
                obst[ln].append((net if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH else "",
                                 Point(mm(c.x), mm(c.y)).buffer(drill / 2), max(A.hole_clear, CLEAR)))
for t in TRACKS:
    net = t.GetNetname()
    if t.GetClass() == "PCB_VIA":
        c = t.GetPosition()
        for ln in cu_layers:
            obst[ln].append((net, Point(mm(c.x), mm(c.y)).buffer(mm(t.GetWidth(pcbnew.F_Cu)) / 2), CLEAR))
for z in ZONES:
    if z.GetIsRuleArea():
        if z.GetDoNotAllowTracks():
            for l in z.GetLayerSet().Seq():
                ln = b.GetLayerName(l)
                if ln in cu_layers:
                    obst[ln].append(("", poly_of(z.Outline()), 0.0))
        continue
    if z.GetAssignedPriority() <= 1:
        continue                              # a soft fill refills around new tracks
    for l in z.GetLayerSet().Seq():
        ln = b.GetLayerName(l)
        if ln in cu_layers:
            g = poly_of(z.GetFilledPolysList(l)) if z.IsFilled() else poly_of(z.Outline())
            obst[ln].append((z.GetNetname(), g, max(CLEAR, mm(z.GetLocalClearance() or 0))))

# the tracks to work on: unlocked tracks of signal nets, by (net, layer)
work = defaultdict(list)
for t in TRACKS:
    if t.GetClass() == "PCB_VIA" or t.IsLocked() or t.GetNetname() in planes:
        continue
    if only and t.GetNetname() not in only:
        continue
    work[(t.GetNetname(), b.GetLayerName(t.GetLayer()))].append(t)
anchors_v = defaultdict(set)
for t in TRACKS:
    if t.GetClass() == "PCB_VIA":
        anchors_v[t.GetNetname()].add((round(mm(t.GetPosition().x), 4), round(mm(t.GetPosition().y), 4)))


# live track geometry of every net on every layer: updated as each net is straightened
cur = defaultdict(list)                    # (net, layer) -> [shapely copper]
for t in TRACKS:
    if t.GetClass() != "PCB_VIA":
        s0, e0 = t.GetStart(), t.GetEnd()
        cur[(t.GetNetname(), b.GetLayerName(t.GetLayer()))].append(
            LineString([(mm(s0.x), mm(s0.y)), (mm(e0.x), mm(e0.y))]).buffer(mm(t.GetWidth()) / 2))


def key(x, y):
    return (round(x, 4), round(y, 4))


def octilinear(p, q):
    dx, dy = abs(q[0] - p[0]), abs(q[1] - p[1])
    return dx < EPS or dy < EPS or abs(dx - dy) < EPS


def candidates(p, q):
    if octilinear(p, q):
        return [[p, q]]
    dx, dy = q[0] - p[0], q[1] - p[1]
    m = min(abs(dx), abs(dy))
    sx, sy = math.copysign(1, dx), math.copysign(1, dy)
    c1 = (p[0] + sx * m, p[1] + sy * m)                    # 45 degrees first, then straight
    c2 = (q[0] - sx * m, q[1] - sy * m)                    # straight first, then 45 degrees
    return [[p, c1, q], [p, c2, q]]


def turn_ok(a, b_, c):
    v1 = (b_[0] - a[0], b_[1] - a[1])
    v2 = (c[0] - b_[0], c[1] - b_[1])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 < EPS or n2 < EPS:
        return True
    return (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2) >= -1e-6          # deflection <= 90 degrees


changed_nets, stats = set(), defaultdict(int)
new_tracks = defaultdict(list)
new_widths = defaultdict(list)
net_vias = defaultdict(list)
for t in TRACKS:
    if t.GetClass() == "PCB_VIA" and t.GetNetname() not in planes:
        net_vias[t.GetNetname()].append(([mm(t.GetPosition().x), mm(t.GetPosition().y)], mm(t.GetWidth(pcbnew.F_Cu))))
for (net, ln), ts in sorted(work.items()):
    lid = lname[ln]
    width = mm(ts[0].GetWidth())
    others = [(g, c) for n, g, c in obst[ln] if n != net or n == ""]
    for (n2, l2), gs in cur.items():           # tracks of other nets on this layer, as they are now
        if l2 == ln and n2 != net:
            others += [(g, CLEAR) for g in gs]
    geoms = [g.buffer(c) if c > 0 else g for g, c in others]
    tree = STRtree(geoms)
    rings = [g for n, g in therm[ln] if n != net]
    ring_tree = STRtree(rings) if rings else None
    bans = selfban.get((net, ln), [])
    inside = edge.buffer(-(A.edge_clear + width / 2))
    res_here = [(cid, g) for cid, lays, g in reserve if ln in lays and cid not in assigned.get(net, set())]

    def blocked(path, old_path):
        line = LineString(path)
        cu = line.buffer(width / 2)
        if not inside.contains(line):
            return True
        for k in tree.query(cu, predicate="intersects"):
            return True
        if ring_tree is not None:
            hit = list(ring_tree.query(cu, predicate="intersects"))
            if hit:
                old_cu = LineString(old_path).buffer(width / 2)
                if any(not old_cu.intersects(rings[k]) for k in hit):
                    return True
        if any(cu.intersects(g) for g in bans):
            return True
        for _, g in res_here:
            if line.intersection(g).length > LineString(old_path).intersection(g).length + 1e-6:
                return True
        return False

    # graph of this net's tracks on this layer
    adj = defaultdict(list)
    for t in ts:
        s, e = t.GetStart(), t.GetEnd()
        a_, b2 = key(mm(s.x), mm(s.y)), key(mm(e.x), mm(e.y))
        if a_ != b2:
            adj[a_].append(b2)
            adj[b2].append(a_)
    pads_here = [g for n, g, _ in obst[ln] if n == net]
    anchor = set()
    for v, nb in adj.items():
        if len(nb) != 2 or v in anchors_v[net] or any(g.buffer(1e-3).contains(Point(v)) for g in pads_here):
            anchor.add(v)
    seen, chains = set(), []
    for a_ in list(adj):
        if a_ not in anchor:
            continue
        for nb in adj[a_]:
            if (a_, nb) in seen:
                continue
            ch = [a_, nb]
            seen.add((a_, nb))
            seen.add((nb, a_))
            while ch[-1] not in anchor:
                nxt = [x for x in adj[ch[-1]] if x != ch[-2]]
                if not nxt:
                    break
                seen.add((ch[-1], nxt[0]))
                seen.add((nxt[0], ch[-1]))
                ch.append(nxt[0])
            chains.append(ch)
    # loops without an anchor are left alone
    out_segments = []
    for ch in chains:
        stats["chains"] += 1
        pts = list(ch)
        res = [pts[0]]
        i = 0
        while i < len(pts) - 1:
            done = False
            for j in range(len(pts) - 1, i + 1, -1):
                for cand in candidates(pts[i], pts[j]):
                    trial = res[:-1] + cand + pts[j + 1:]
                    k0 = len(res) - 1
                    ok_turns = all(turn_ok(trial[m - 1], trial[m], trial[m + 1])
                                   for m in range(max(1, k0 - 1), min(len(trial) - 1, k0 + len(cand) + 1)))
                    if not ok_turns or blocked(cand, pts[i:j + 1]):
                        continue
                    res = res[:-1] + cand
                    i = j
                    done = True
                    break
                if done:
                    break
            if not done:
                res.append(pts[i + 1])
                i += 1
        # drop collinear middle points
        clean = [res[0]]
        for m in range(1, len(res) - 1):
            a_, b_, c = clean[-1], res[m], res[m + 1]
            if abs((b_[0] - a_[0]) * (c[1] - b_[1]) - (b_[1] - a_[1]) * (c[0] - b_[0])) > 1e-6:
                clean.append(b_)
        clean.append(res[-1])
        stats["segments_before"] += len(pts) - 1
        stats["segments_after"] += len(clean) - 1
        stats["length_before"] += sum(math.dist(pts[m], pts[m + 1]) for m in range(len(pts) - 1))
        stats["length_after"] += sum(math.dist(clean[m], clean[m + 1]) for m in range(len(clean) - 1))
        out_segments += [(clean[m], clean[m + 1]) for m in range(len(clean) - 1)]
    if len(out_segments) < len(ts):
        changed_nets.add(net)
    for t in ts:
        b.Remove(t)
    for p0, p1 in out_segments:
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(pcbnew.VECTOR2I(FMM(p0[0]), FMM(p0[1])))
        t.SetEnd(pcbnew.VECTOR2I(FMM(p1[0]), FMM(p1[1])))
        t.SetWidth(FMM(width))
        t.SetLayer(lid)
        t.SetNet(b.FindNet(net))
        b.Add(t)
        new_tracks[net].append([ln, p0[0], p0[1], p1[0], p1[1]])
        new_widths[net].append(width)
    cur[(net, ln)] = [LineString([p0, p1]).buffer(width / 2) for p0, p1 in out_segments]

os.makedirs(A.out, exist_ok=True)
src_dir = os.path.dirname(os.path.abspath(A.board))
for f in os.listdir(src_dir):
    pth = os.path.join(src_dir, f)
    if os.path.isfile(pth) and not f.endswith((".kicad_pcb", ".bak")) and not f.startswith("_autosave"):
        shutil.copy2(pth, A.out)
    elif os.path.isdir(pth) and f.endswith(".pretty"):
        shutil.copytree(pth, os.path.join(A.out, f), dirs_exist_ok=True)
dst = os.path.join(A.out, os.path.basename(A.board))
b.Save(dst)
b2 = pcbnew.LoadBoard(dst)
pcbnew.ZONE_FILLER(b2).Fill(b2.Zones())
b2.Save(dst)
if A.routes_out:
    json.dump(dict(results=[dict(net=n, tracks=v, widths=new_widths[n], vias=[q[0] for q in net_vias[n]],
                                 via_d=[q[1] for q in net_vias[n]]) for n, v in new_tracks.items()]),
              open(A.routes_out, "w"))
L = ["# Straightening pass", "",
     "Board: `%s` -> `%s`." % (A.board, dst), "",
     "| Measure | Before | After |", "|---|---|---|",
     "| Track segments (unlocked, signal nets) | %d | %d |" % (stats["segments_before"], stats["segments_after"]),
     "| Track length, mm | %.1f | %.1f |" % (stats["length_before"], stats["length_after"]),
     "", "Chains: %d. Nets changed: %d. Clearance %.4f mm, edge %.3f mm, thermal ring %.2f mm, reserved corridors: %d." % (
         stats["chains"], len(changed_nets), CLEAR, A.edge_clear, THERM, len(reserve)),
     "", "Next: score the result against the unrouted board (valid; plane-net open connections not higher)."]
txt = "\n".join(L) + "\n"
open(A.report or os.path.join(A.out, "STRAIGHTEN.md"), "w", encoding="utf-8").write(txt)
print(txt)
