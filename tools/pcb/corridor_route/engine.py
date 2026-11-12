"""Detailed router shared by capacity.py (solo routability) and route_plan.py (negotiated routing).

The router is a negotiated-congestion grid search (PathFinder). Each net may use only its allowed region
(core.Ctx.allowed). Costs come from the plan:

  "costs": {"via": 10, "pour": 30, "reserve": 6, "direction": 3}
  "layer_cost": {"B.Cu": 2.0}                      cost multiplier of a layer, plan level or per group
  "directions": {"F.Cu": "h", "B.Cu": "v"}         preferred direction of a layer ("h", "v" or "any"), plan level
                                                   or per group; a step against it costs `costs.direction` times
"""
import heapq
import math

import numpy as np

from core import FREE, disk_lt, lattice_radius

SQ2 = math.sqrt(2)
NB = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, SQ2), (1, -1, SQ2), (-1, 1, SQ2), (-1, -1, SQ2)]
INF = math.inf


def seg_cross(a, b):
    """True when two segments (x1, y1, x2, y2) properly cross"""
    def o(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    p1, p2, p3, p4 = a[:2], a[2:], b[:2], b[2:]
    d1, d2, d3, d4 = o(p3, p4, p1), o(p3, p4, p2), o(p1, p2, p3), o(p1, p2, p4)
    return (d1 * d2 < -1e-12) and (d3 * d4 < -1e-12)


class Router:
    def __init__(self, C, via_cost=None, pour_penalty=None):
        self.C = C
        costs = C.P.get("costs", {})
        self.via_cost = float(via_cost if via_cost is not None else costs.get("via", 10.0))
        self.pour_penalty = float(pour_penalty if pour_penalty is not None else costs.get("pour", 30.0))
        self.reserve_cost = float(costs.get("reserve", 6.0))
        self.dir_pen = float(costs.get("direction", 3.0))
        self.thermal_cost = float(costs.get("thermal", 8.0))
        self.guide_cost = float(costs.get("guide", 3.0))
        NL, ny, nx = C.NL, C.ny, C.nx
        self.occT = np.zeros((NL, ny, nx), np.float32)
        self.occV = np.zeros((NL, ny, nx), np.float32)
        self.hist = np.zeros((NL, ny, nx), np.float32)
        self.pres = 1.0
        self._disc = {}
        self._resv = {}
        self.fixT = None          # cells claimed by nets kept from an earlier run: hard obstacles
        self.fixV = None
        self.paths_of = {}        # net -> [path, ...], each path a list of (layer, j, i); set by route_net
        self.routes = {}          # net -> (cells, vias)
        self.unreached = {}       # net -> [pad keys]

    # ------------------------------------------------------------ discs
    def disc(self, r):
        key = round(r, 5)
        if key not in self._disc:
            offs = disk_lt(lattice_radius(r, self.C.R), self.C.R)
            self._disc[key] = (np.array([o[0] for o in offs], np.int64), np.array([o[1] for o in offs], np.int64), offs)
        return self._disc[key]

    def width(self, net):
        return float(self.C.assign[net]["width"])

    def radii(self, net):
        C = self.C
        w = self.width(net)
        return dict(TT=w / 2 + C.clear + C.track / 2, TV=w / 2 + C.clear + C.via / 2,
                    VT=C.via / 2 + C.clear + C.track / 2, VV=C.via + C.clear)

    def _stamp(self, arr, layers, jj, ii, disc, val):
        if len(jj) == 0:
            return
        dj, di, _ = disc
        J = (jj[:, None] + dj[None, :]).ravel()
        I = (ii[:, None] + di[None, :]).ravel()
        ok = (J >= 0) & (J < self.C.ny) & (I >= 0) & (I < self.C.nx)
        if np.isscalar(layers) or layers.ndim == 0:
            np.add.at(arr[int(layers)], (J[ok], I[ok]), val)
        else:
            Lr = np.repeat(layers, len(dj))
            np.add.at(arr, (Lr[ok], J[ok], I[ok]), val)

    def contribute(self, net, route, val):
        cells, vias = route
        C = self.C
        own = C.own.get(net, ())
        r = self.radii(net)
        cs = [c for c in cells if c not in own]
        if cs:
            a = np.array(cs, np.int64)
            self._stamp(self.occT, a[:, 0], a[:, 1], a[:, 2], self.disc(r["TT"]), val)
            self._stamp(self.occV, a[:, 0], a[:, 1], a[:, 2], self.disc(r["TV"]), val)
        if vias:
            v = np.array(sorted(set(vias)), np.int64)
            for l in range(C.NL):
                self._stamp(self.occT, np.int64(l), v[:, 0], v[:, 1], self.disc(r["VT"]), val)
                self._stamp(self.occV, np.int64(l), v[:, 0], v[:, 1], self.disc(r["VV"]), val)

    def freeze(self):
        """the occupancy stamped so far (nets kept from an earlier run) becomes a hard obstacle for every other net"""
        self.fixT = self.occT > 0
        self.fixV = self.occV.max(axis=0) > 0

    # ------------------------------------------------------------ per-net cost pieces
    def reserve_mult(self, net):
        """cost multiplier array for corridors reserved for other nets, or None"""
        C = self.C
        corr = C.corridors()
        mine = frozenset(cid for cid, _ in C.flat_route(C.assign[net]["route"]))
        other = [cid for cid, c in corr.items() if c["reserve"] and cid not in mine]
        if not other:
            return None
        key = frozenset(other)
        if key not in self._resv:
            import shapely
            m = np.ones((C.NL, C.ny, C.nx), np.float32)
            for cid in other:
                c = corr[cid]
                inside = shapely.contains_xy(c["geom"], C.X, C.Y)
                for l in c["layers"]:
                    m[l][inside] = self.reserve_cost
            self._resv[key] = m
        return self._resv[key]

    def guide_mult(self, net, j0, j1, i0, i1):
        """cost multiplier [NL, h, w] outside the guide corridors of the net (plan `net_guide`), or None"""
        C = self.C
        ids = C.P.get("net_guide", {}).get(net)
        if not ids:
            return None
        import shapely
        corr = C.corridors()
        m = np.full((C.NL, j1 - j0, i1 - i0), self.guide_cost, np.float64)
        X, Y = C.X[j0:j1, i0:i1], C.Y[j0:j1, i0:i1]
        for cid in ids:
            c = corr.get(cid)
            if c:
                inside = shapely.contains_xy(c["geom"], X, Y)
                for l in c["layers"]:
                    m[l][inside] = 1.0
        return m

    def dir_mult(self, net):
        C = self.C
        d = dict(C.P.get("directions", {}))
        d.update(C.assign[net].get("directions") or {})
        ph, pv = [], []
        for ln in C.LAYERS:
            v = d.get(ln, "any")
            ph.append(self.dir_pen if v == "v" else 1.0)
            pv.append(self.dir_pen if v == "h" else 1.0)
        return ph, pv

    def layer_mult(self, net):
        C = self.C
        d = dict(C.P.get("layer_cost", {}))
        d.update(C.assign[net].get("layer_cost") or {})
        return [float(d.get(ln, 1.0)) for ln in C.LAYERS]

    # ------------------------------------------------------------ one net
    def route_net(self, net, hard=False, solo=False):
        """returns ((cells, vias), unreached pad keys). hard: cells used by other nets are obstacles.
        solo: other nets are ignored (is the net routable alone inside its allowed region?)."""
        C = self.C
        R, NL = C.R, C.NL
        n = C.nid(net)
        groups = {k: v for k, v in C.padcells.get(net, {}).items() if v}
        if len(groups) < 2:
            return ([], []), []
        j0, j1, i0, i1, allow = C.allowed(net)
        W, H = i1 - i0, j1 - j0
        sl = (slice(None), slice(j0, j1), slice(i0, i1))
        oT = C.ownT[sl]
        passT = (oT == FREE) | (oT == n)
        oV = C.ownV[sl]
        passV = np.all((oV == FREE) | (oV == n), axis=0) & ~C.holeBan[j0:j1, i0:i1]
        ban = C.self_ban(net, j0, j1, i0, i1)
        if ban is not None:
            passT = passT & ~ban[0]
            passV = passV & ~ban[1]
        occT = self.occT[sl]
        occV = self.occV[sl].max(axis=0)
        e = (self.width(net) - C.track) / 2
        if e > 1e-6:                               # a wide track needs the extra half-width everywhere
            from core import dilate
            offs = disk_lt(e + C.R * 0.75, R)
            passT = ~dilate(~passT, offs)
            if not solo:
                occT = occT.copy()
                for dj, di in offs:
                    if dj or di:
                        ys, yd = (slice(dj, H), slice(0, H - dj)) if dj >= 0 else (slice(0, H + dj), slice(-dj, H))
                        xs, xd = (slice(di, W), slice(0, W - di)) if di >= 0 else (slice(0, W + di), slice(-di, W))
                        np.maximum(occT[:, yd, xd], self.occT[sl][:, ys, xs], out=occT[:, yd, xd])
        passT &= allow
        pn = C.pourN[sl]
        lm = self.layer_mult(net)
        base = np.ones((NL, H, W), np.float64)
        for l in range(NL):
            base[l] *= lm[l]
        rm = self.reserve_mult(net)
        if rm is not None:
            base *= rm[sl]
        gm = self.guide_mult(net, j0, j1, i0, i1)
        if gm is not None:
            base *= gm
        base += np.where((pn != FREE) & (pn != n), self.pour_penalty, 0.0)
        base += np.where(C.ring[sl], self.thermal_cost, 0.0)
        vc0 = C.assign[net].get("via_cost")
        vc0 = self.via_cost if vc0 is None else float(vc0)
        if solo:
            costT = base
            costV = np.full((H, W), vc0, np.float64)
        elif hard:
            costT = np.where(occT > 0, INF, base)
            costV = np.where(occV > 0, INF, vc0)
        else:
            costT = base * (1.0 + self.hist[sl]) * (1.0 + self.pres * occT)
            costV = vc0 * (1.0 + self.hist[sl].max(axis=0)) * (1.0 + self.pres * occV)
        if self.fixT is not None and not solo:
            passT = passT & ~self.fixT[sl]
            passV = passV & ~self.fixV[j0:j1, i0:i1]
        costT = np.where(passT, costT, INF)
        costV = np.where(passV, costV, INF)
        cT = [costT[l].ravel().tolist() for l in range(NL)]
        cV = costV.ravel().tolist()
        ph, pv = self.dir_mult(net)
        mult = [[(pv[l] if di == 0 else ph[l] if dj == 0 else (ph[l] + pv[l]) / 2) * c for dj, di, c in NB]
                for l in range(NL)]
        vgap = (C.drill + C.hole2hole) / R          # same-net via spacing, in cells

        def loc(cs):
            return set((l, j - j0, i - i0) for (l, j, i) in cs if j0 <= j < j1 and i0 <= i < i1)

        keys = sorted(groups, key=lambda k: -len(groups[k]))
        tree = loc(groups[keys[0]])
        rest = [(k, loc(groups[k])) for k in keys[1:]]
        cells, vias, unreached, paths = [], [], [], []
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
                ml = mult[l]
                for q, (dj, di, c) in enumerate(NB):
                    jj, ii = j + dj, i + di
                    if not (0 <= jj < H and 0 <= ii < W):
                        continue
                    t = (l, jj, ii)
                    cost = row[jj * W + ii]
                    if cost == INF:
                        if t not in tgt:
                            continue
                        cost = 1.0
                    if dj and di and (row[j * W + ii] == INF or row[jj * W + i] == INF):
                        continue
                    nc = gc + ml[q] * cost
                    if nc < g.get(t, 1e30):
                        g[t] = nc
                        prev[t] = s
                        heapq.heappush(pq, (nc + max(0.0, math.hypot(jj - cy_, ii - cx_) - rad), nc, t))
                vc = cV[j * W + i]
                if vc != INF and row[j * W + i] != INF:
                    if vias and any(0 < math.hypot(j + j0 - vj, i + i0 - vi) < vgap for (vj, vi) in vias):
                        continue
                    near = False                    # a layer change earlier on this same path, too close
                    a_, steps = s, 0
                    while prev.get(a_) is not None and steps < 2 * vgap + 2:
                        b_ = prev[a_]
                        if b_[0] != a_[0] and 0 < math.hypot(b_[1] - j, b_[2] - i) < vgap:
                            near = True
                            break
                        a_, steps = b_, steps + 1
                    if near:
                        continue
                    for l2 in range(NL):
                        if l2 == l or cT[l2][j * W + i] == INF:
                            continue
                        t = (l2, j, i)
                        nc = gc + vc
                        if nc < g.get(t, 1e30):
                            g[t] = nc
                            prev[t] = s
                            heapq.heappush(pq, (nc + max(0.0, math.hypot(j - cy_, i - cx_) - rad), nc, t))
            if found is None:
                unreached.append(key)
                continue
            path = [found]
            while prev[path[-1]] is not None:
                path.append(prev[path[-1]])
            path.reverse()
            for a, b2 in zip(path[:-1], path[1:]):
                if a[0] != b2[0]:
                    vias.append((a[1] + j0, a[2] + i0))
            cells += [(l, j + j0, i + i0) for (l, j, i) in path]
            paths.append([(l, j + j0, i + i0) for (l, j, i) in path])
            tree |= set(path) | tgt
        if not solo:
            self.paths_of[net] = paths
        return (cells, vias), unreached

    # ------------------------------------------------------------ conflicts
    def conflict_cells(self, net, route):
        """cells of the route that another net's copper claims (call with the net's own contribution removed)"""
        cells, vias = route
        C = self.C
        own = C.own.get(net, ())
        out = [(l, j, i) for (l, j, i) in cells if (l, j, i) not in own and self.occT[l, j, i] > 0]
        out += [(-1, j, i) for (j, i) in vias if self.occV[:, j, i].max() > 0]
        return out

    def partners(self, net, cc, cellmap, viamap):
        """nets whose copper is within clearance of the conflict cells cc"""
        r = self.radii(net)
        C = self.C
        dTT, dVT, dVV = self.disc(r["TT"])[2], self.disc(r["VT"])[2], self.disc(r["VV"])[2]
        out = set()
        for (l, j, i) in cc:
            if l >= 0:
                for dj, di in dTT:
                    out |= cellmap.get((l, j + dj, i + di), set())
                for dj, di in dVT:
                    out |= viamap.get((j + dj, i + di), set())
            else:
                for dj, di in dVT:
                    for l2 in range(C.NL):
                        out |= cellmap.get((l2, j + dj, i + di), set())
                for dj, di in dVV:
                    out |= viamap.get((j + dj, i + di), set())
        out.discard(net)
        return out

    def maps(self, nets):
        cellmap, viamap = {}, {}
        for net in nets:
            cells, vias = self.routes[net]
            own = self.C.own.get(net, ())
            for c in cells:
                if c not in own:
                    cellmap.setdefault(c, set()).add(net)
            for v in vias:
                viamap.setdefault(v, set()).add(net)
        return cellmap, viamap

    # ------------------------------------------------------------ ordering
    def crossing_counts(self, nets):
        """net -> number of other nets whose minimum spanning tree crosses its own"""
        C = self.C
        segs = [(net, s) for net in nets for s in C.mst(net)]
        cnt = {net: set() for net in nets}
        for a in range(len(segs)):
            na, sa = segs[a]
            for b in range(a + 1, len(segs)):
                nb, sb = segs[b]
                if na != nb and seg_cross(sa, sb):
                    cnt[na].add(nb)
                    cnt[nb].add(na)
        return cnt
