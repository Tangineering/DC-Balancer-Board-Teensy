"""Shared core of the corridor router: loads a board model (board_model.py) and a corridor plan (plan.json), builds
the routing grid, the hard-obstacle rasters and each net's allowed region.

Frames. The model is in the KiCad frame (mm, y down). A plan may state `"frame": {"y_flip_offset": Y0}`; its
coordinates are then design coordinates with y up, converted here by y_kicad = Y0 - y_design.

Grid clearance model. A cell is a candidate track centreline. Copper of another net blocks every cell closer than
clearance + track/2 (tracks) or clearance + via/2 (via centres). Keep-outs block by track/2 and via/2.
"""
import json
import math

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

FREE, BLOCK = -1, -2


class Ctx:
    def __init__(self, model_path, plan_path):
        self.D = json.load(open(model_path))
        self.P = json.load(open(plan_path))
        r = self.P.get("rules", {})
        self.track = float(r.get("track", 0.16))
        self.clear = float(r.get("clear", 0.16))
        self.via = float(r.get("via", 0.6))
        self.drill = float(r.get("drill", 0.3))
        self.R = float(r.get("res", 0.1))
        self.yoff = self.P.get("frame", {}).get("y_flip_offset")
        self.LAYERS = self.D["layers"]
        self.NL = len(self.LAYERS)
        self.bx0, self.by0, self.bx1, self.by1 = self.D["bbox"]
        R = self.R
        self.nx = int(math.ceil((self.bx1 - self.bx0) / R)) + 1
        self.ny = int(math.ceil((self.by1 - self.by0) / R)) + 1
        self.X, self.Y = np.meshgrid(self.bx0 + np.arange(self.nx) * R, self.by0 + np.arange(self.ny) * R)
        self.nets = {}
        self.keep = set(self.P.get("keep_nets", [])) | {it["net"] for it in self.D["items"] if it["kind"] == "zone"}
        self.plane = self.P.get("plane_net")
        if self.plane:
            self.keep.add(self.plane)
        self._corr = None
        self._allowed = {}
        self._build_obstacles()
        self._build_pads()
        self._assign()

    # ------------------------------------------------------------ frame
    def k(self, pt):
        """plan point -> KiCad frame"""
        x, y = pt
        return (x, self.yoff - y) if self.yoff is not None else (x, y)

    def d(self, x, y):
        """KiCad point -> plan frame"""
        return (x, self.yoff - y) if self.yoff is not None else (x, y)

    def cell(self, x, y):
        return int(round((y - self.by0) / self.R)), int(round((x - self.bx0) / self.R))

    def nid(self, name):
        if not name:
            return BLOCK
        if name not in self.nets:
            self.nets[name] = len(self.nets)
        return self.nets[name]

    # ------------------------------------------------------------ geometry
    @staticmethod
    def geom_of(it, extra=0.0):
        if "poly" in it:
            g = Polygon(it["poly"], it.get("holes") or None).buffer(0)
        elif "seg" in it:
            xa, ya, xb, yb, w = it["seg"]
            g = (LineString([(xa, ya), (xb, yb)]).buffer(w / 2) if (xa, ya) != (xb, yb)
                 else Point(xa, ya).buffer(w / 2))
        else:
            cx, cy, r = it["circ"]
            g = Point(cx, cy).buffer(r)
        return g.buffer(extra) if extra else g

    def window(self, g):
        gx0, gy0, gx1, gy1 = g.bounds
        R = self.R
        i0, i1 = max(int((gx0 - self.bx0) / R) - 1, 0), min(int((gx1 - self.bx0) / R) + 2, self.nx)
        j0, j1 = max(int((gy0 - self.by0) / R) - 1, 0), min(int((gy1 - self.by0) / R) + 2, self.ny)
        return i0, i1, j0, j1

    def raster(self, g):
        """(j0, j1, i0, i1, mask) of the cells whose centre lies in g"""
        i0, i1, j0, j1 = self.window(g)
        if i0 >= i1 or j0 >= j1:
            return 0, 0, 0, 0, np.zeros((0, 0), bool)
        return j0, j1, i0, i1, shapely.contains_xy(g, self.X[j0:j1, i0:i1], self.Y[j0:j1, i0:i1])

    def _claim(self, arr, li, g, n):
        j0, j1, i0, i1, m = self.raster(g)
        if m.size == 0:
            return
        sub = arr[li, j0:j1, i0:i1]
        if n == BLOCK:
            sub[m] = BLOCK
        else:
            sub[m & (sub == FREE)] = n
            sub[m & (sub != n) & (sub != FREE)] = BLOCK

    # ------------------------------------------------------------ obstacles
    def _build_obstacles(self):
        D, NL = self.D, self.NL
        rT = self.clear + self.track / 2 + self.R * 0.5
        rV = self.clear + self.via / 2 + self.R * 0.5
        self.ownT = np.full((NL, self.ny, self.nx), FREE, np.int32)
        self.ownV = np.full((NL, self.ny, self.nx), FREE, np.int32)
        self.pourN = np.full((NL, self.ny, self.nx), FREE, np.int32)
        self.routable = set()
        for it in D["items"]:
            if it["kind"] in ("track", "via") and it["net"] not in self.keep and not it.get("locked"):
                self.routable.add(it["net"])
            if (it["kind"] == "pad" and it["net"] and it["net"] not in self.keep
                    and not it["net"].startswith("unconnected")):
                self.routable.add(it["net"])
        for it in D["items"]:
            if it["kind"] in ("track", "via") and it["net"] in self.routable and not it.get("locked"):
                continue
            if it["kind"] == "zone" and it.get("soft"):
                continue
            if it["kind"] == "zone":
                for ln in it["layers"]:
                    self._claim(self.pourN, self.LAYERS.index(ln), self.geom_of(it, rT), self.nid(it["net"]))
                continue
            n = BLOCK if it["kind"] == "keepout" else self.nid(it["net"])
            for ln in it["layers"]:
                li = self.LAYERS.index(ln)
                if it["kind"] == "keepout":
                    g = self.geom_of(it)
                    self._claim(self.ownT, li, g.buffer(self.track / 2), BLOCK)
                    self._claim(self.ownV, li, g.buffer(self.via / 2), BLOCK)
                else:
                    self._claim(self.ownT, li, self.geom_of(it, rT), n)
                    self._claim(self.ownV, li, self.geom_of(it, rV), n)
        self.net_name = {v: k for k, v in self.nets.items()}

    def cells_of(self, it):
        g = self.geom_of(it)
        j0, j1, i0, i1, m = self.raster(g)
        jj, ii = np.nonzero(m)
        if len(jj) == 0:
            c = g.centroid
            cj, ci = self.cell(c.x, c.y)
            jj, ii, j0, i0 = np.array([cj]), np.array([ci]), 0, 0
        out = []
        for ln in it["layers"]:
            li = self.LAYERS.index(ln)
            out += [(li, int(j + j0), int(i + i0)) for j, i in zip(jj, ii)]
        return out

    def _build_pads(self):
        pads_of = {}
        for it in self.D["items"]:
            if it["kind"] == "pad" and it["net"] in self.routable:
                pads_of.setdefault(it["net"], {}).setdefault((it.get("ref"), it.get("num")), []).append(it)
        for it in self.D["items"]:
            if it["kind"] in ("track", "via") and it.get("locked") and it["net"] in self.routable:
                pads_of.setdefault(it["net"], {})[("locked", id(it))] = [it]
        self.pads_of = pads_of
        self.padcells = {net: {key: [c for it in grp for c in self.cells_of(it)] for key, grp in groups.items()}
                         for net, groups in pads_of.items()}
        self.own = {net: {c for key, cs in groups.items() if key[0] != "locked" for c in cs}
                    for net, groups in self.padcells.items()}

    def pad_centres(self, net):
        """[(ref, num, x, y)] in the KiCad frame"""
        out = []
        for (ref, num), grp in self.pads_of.get(net, {}).items():
            if ref == "locked":
                continue
            c = unary_union([self.geom_of(it) for it in grp]).centroid
            out.append((ref, num, c.x, c.y))
        return out

    # ------------------------------------------------------------ plan: corridors and assignment
    def corridors(self):
        """id -> dict(layers=[layer index], geom=shapely polygon (KiCad frame), path=[(x, y)] or None, width)"""
        if self._corr is None:
            self._corr = {}
            for c in self.P.get("corridors", []):
                layers = c.get("layers") or [c["layer"]]
                li = [self.LAYERS.index(l) for l in layers]
                if "path" in c:
                    path = [self.k(p) for p in c["path"]]
                    geom = LineString(path).buffer(c["width"] / 2, cap_style=2, join_style=2)
                else:
                    path = None
                    geom = Polygon([self.k(p) for p in c["polygon"]]).buffer(0)
                self._corr[c["id"]] = dict(layers=li, geom=geom, path=path, width=c.get("width"),
                                           note=c.get("note", ""))
        return self._corr

    def _assign(self):
        """net -> dict(mode, route, escape, margin, priority, group)"""
        dflt = dict(mode="local", route=[], escape=1.5, margin=2.5, priority=5, group="(default)")
        dflt.update(self.P.get("default", {}))
        self.assign = {}
        self.plan_errors = []
        corr = self.corridors()
        for g in self.P.get("groups", []):
            for cid in g.get("route", []):
                if cid not in corr:
                    self.plan_errors.append("group %s: unknown corridor %s" % (g.get("name"), cid))
            for net in g["nets"]:
                if net not in self.routable:
                    self.plan_errors.append("group %s: net %s is not a routable net" % (g.get("name"), net))
                    continue
                if net in self.assign:
                    self.plan_errors.append("net %s is in two groups (%s, %s)" % (net, self.assign[net]["group"],
                                                                               g.get("name")))
                a = dict(dflt)
                a.update({k: v for k, v in g.items() if k in ("mode", "route", "escape", "margin", "priority")})
                if g.get("route") and "mode" not in g:
                    a["mode"] = "corridor"
                a["group"] = g.get("name", "?")
                self.assign[net] = a
        for net in self.routable:
            self.assign.setdefault(net, dict(dflt))

    def allowed(self, net):
        """(j0, j1, i0, i1, mask[NL, h, w]): the cells the net may use"""
        if net in self._allowed:
            return self._allowed[net]
        a = self.assign[net]
        NL = self.NL
        pcs = self.pad_centres(net)
        per_layer = [[] for _ in range(NL)]
        if a["mode"] == "free":
            g = box(self.bx0, self.by0, self.bx1, self.by1)
            for l in range(NL):
                per_layer[l].append(g)
        elif a["mode"] == "local":
            xs = [p[2] for p in pcs] or [self.bx0]
            ys = [p[3] for p in pcs] or [self.by0]
            m = a["margin"]
            g = box(min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m)
            for l in range(NL):
                per_layer[l].append(g)
        else:
            corr = self.corridors()
            for cid in a["route"]:
                c = corr.get(cid)
                if c:
                    for l in c["layers"]:
                        per_layer[l].append(c["geom"])
            esc = [Point(p[2], p[3]).buffer(a["escape"]) for p in pcs]
            for l in range(NL):
                per_layer[l] += esc
        geoms = [unary_union(gs) if gs else None for gs in per_layer]
        bounds = [g.bounds for g in geoms if g is not None and not g.is_empty]
        if not bounds:
            self._allowed[net] = (0, 1, 0, 1, np.zeros((NL, 1, 1), bool))
            return self._allowed[net]
        R = self.R
        i0 = max(int((min(b[0] for b in bounds) - self.bx0) / R) - 1, 0)
        i1 = min(int((max(b[2] for b in bounds) - self.bx0) / R) + 2, self.nx)
        j0 = max(int((min(b[1] for b in bounds) - self.by0) / R) - 1, 0)
        j1 = min(int((max(b[3] for b in bounds) - self.by0) / R) + 2, self.ny)
        mask = np.zeros((NL, j1 - j0, i1 - i0), bool)
        for l, g in enumerate(geoms):
            if g is not None and not g.is_empty:
                mask[l] = shapely.contains_xy(g, self.X[j0:j1, i0:i1], self.Y[j0:j1, i0:i1])
        for (l, j, i) in self.own.get(net, ()):   # a net's own pads are always usable
            if j0 <= j < j1 and i0 <= i < i1:
                mask[l, j - j0, i - i0] = True
        self._allowed[net] = (j0, j1, i0, i1, mask)
        return self._allowed[net]
