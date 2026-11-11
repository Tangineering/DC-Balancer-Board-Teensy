"""Corridor router step L2: check a corridor plan before any copper is made.

Usage (venv with numpy + shapely):
  python capacity.py <model.json> <plan.json> [<report.md>]

Checks, in this order:
 1. plan errors (unknown corridor, net in two groups, net that is not routable);
 2. pad escape: every pad of every routable net can leave its own neighbourhood (a sealed pad cannot be routed
    by any router; the fix is a placement, pad or pour change);
 3. corridor capacity: at stations along each path corridor, the number of parallel tracks that fit between the
    fixed obstacles on its layers, against the number of nets assigned to it;
 4. assignment coverage: every pad of a corridor-routed net can reach one of the net's corridors inside its
    escape disc, and the net's corridors form one connected region together with the escape discs.
Exit code 1 when any check fails."""
import math
import sys
from collections import Counter, deque

import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from core import BLOCK, FREE, Ctx

C = Ctx(sys.argv[1], sys.argv[2])
out = sys.argv[3] if len(sys.argv) > 3 else None
R, NL = C.R, C.NL
pitch = C.track + C.clear
L = ["# Corridor plan check", "",
     "Rules: track %.3f, clearance %.3f, via %.2f/%.2f, grid %.3f mm. Coordinates: %s." % (
         C.track, C.clear, C.via, C.drill, R, "design frame (y up)" if C.yoff is not None else "KiCad frame"), ""]
fail = False


def fmt(x, y):
    return "(%.2f, %.2f)" % C.d(x, y)


# ---------------------------------------------------------------- 1. plan errors
L += ["## 1. Plan errors", ""]
if C.plan_errors:
    fail = True
    L += ["- " + e for e in C.plan_errors]
else:
    L.append("None.")
by_group = Counter(a["group"] for a in C.assign.values())
L += ["", "Routable nets: %d. By group: %s." % (len(C.routable), ", ".join("%s %d" % kv for kv in sorted(by_group.items()))), ""]

# ---------------------------------------------------------------- 2. pad escape
ESC = 1.2   # a pad escapes when the search reaches a cell this far outside the pad's own cells
L += ["## 2. Pad escape (sealed pads)", ""]
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
        pV = np.all((oV == FREE) | (oV == n), axis=0)
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
    L += ["", "A sealed pad needs a placement change, a smaller neighbouring pad or pour, or a finer rule set. "
          "Do not route until this table is empty."]
else:
    L.append("None: every pad can leave its neighbourhood.")
L.append("")

# ---------------------------------------------------------------- 3. corridor capacity
L += ["## 3. Corridor capacity", "",
      "Capacity = parallel track centrelines that fit across the corridor at its narrowest station, summed over "
      "its layers (pitch %.3f mm). Demand = nets assigned to it." % pitch, "",
      "| Corridor | Layers | Width | Demand | Capacity | Margin | Narrowest station | Result |", "|---|---|---|---|---|---|---|---|"]
demand = Counter()
users = {}
for net, a in C.assign.items():
    if a["mode"] == "corridor":
        for cid in a["route"]:
            demand[cid] += 1
            users.setdefault(cid, []).append(net)
for cid, c in C.corridors().items():
    lay = ",".join(C.LAYERS[l] for l in c["layers"])
    if c["path"] is None:
        L.append("| %s | %s | region | %d | not computed | - | - | region: no capacity check |" % (cid, lay, demand[cid]))
        continue
    line = LineString(c["path"])
    best = None
    s = 0.0
    while s <= line.length + 1e-9:
        p = line.interpolate(s)
        q = line.interpolate(min(s + 0.05, line.length)) if s + 0.05 <= line.length else line.interpolate(s - 0.05)
        dx, dy = q.x - p.x, q.y - p.y
        if s + 0.05 > line.length:
            dx, dy = -dx, -dy
        nrm = math.hypot(dx, dy) or 1.0
        ux, uy = -dy / nrm, dx / nrm
        n_s = int(c["width"] / R) + 1
        cap = 0
        for l in c["layers"]:
            run = 0
            for t in range(n_s):
                off = -c["width"] / 2 + t * R
                j, i = C.cell(p.x + ux * off, p.y + uy * off)
                free = 0 <= j < C.ny and 0 <= i < C.nx and C.ownT[l, j, i] == FREE
                if free:
                    run += 1
                if (not free or t == n_s - 1) and run:
                    cap += int(((run - 1) * R + 1e-9) / pitch) + 1
                    run = 0
        if best is None or cap < best[0]:
            best = (cap, p.x, p.y)
        s += 0.25
    d = demand[cid]
    ok = best[0] >= d
    fail = fail or not ok
    L.append("| %s | %s | %.2f | %d | %d | %+d | %s | %s |" % (cid, lay, c["width"], d, best[0], best[0] - d,
                                                            fmt(best[1], best[2]), "ok" if ok else "OVER CAPACITY"))
L += ["", "A corridor at margin 0 or +1 will route only if every net enters and leaves in order; prefer margin >= 2.", ""]

# ---------------------------------------------------------------- 4. assignment coverage
L += ["## 4. Assignment coverage", ""]
bad = []
for net, a in sorted(C.assign.items()):
    if a["mode"] != "corridor":
        continue
    corr = C.corridors()
    geoms = [corr[cid]["geom"] for cid in a["route"] if cid in corr]
    pcs = C.pad_centres(net)
    discs = [Point(p[2], p[3]).buffer(a["escape"]) for p in pcs]
    for (ref, num, x, y), dsc in zip(pcs, discs):
        if geoms and not any(dsc.intersects(g) for g in geoms) and len(pcs) > 1:
            others = [o for o in discs if o is not dsc]
            if not any(dsc.intersects(o) for o in others):
                bad.append("%s: pad %s.%s at %s does not reach any of its corridors %s within escape %.1f mm"
                           % (net, ref, num, fmt(x, y), a["route"], a["escape"]))
    u = unary_union(geoms + discs)
    if u.geom_type != "Polygon":
        bad.append("%s: its corridors and escape discs form %d separate regions (route %s)"
                   % (net, len(u.geoms), a["route"]))
if bad:
    fail = True
    L += ["- " + x for x in bad]
else:
    L.append("Every corridor-routed net has a connected allowed region that touches all its pads.")
L += ["", "## Result", "", "FAIL: fix the plan (or the placement) and run this check again." if fail
      else "PASS: the plan may be routed."]
txt = "\n".join(L) + "\n"
if out:
    open(out, "w", encoding="utf-8").write(txt)
print(txt)
sys.exit(1 if fail else 0)
