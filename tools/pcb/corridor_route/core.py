"""Shared core of the plan-driven router: loads a board model (board_model.py) and a routing plan (plan.json),
builds the routing grid, the hard-obstacle rasters and each net's allowed region.

Frames. The model is in the KiCad frame (mm, y down). A plan may state `"frame": {"y_flip_offset": Y0}`; its
coordinates are then design coordinates with y up, converted here by y_kicad = Y0 - y_design.

Grid clearance model. A cell is a candidate track centreline. Fixed copper of another net blocks every cell closer
than clearance + track/2 (tracks) or clearance + via/2 (via centres), plus a margin that covers the sag of a
diagonal step between two cell centres. Keep-outs block by track/2 and via/2. The board edge blocks by the board's
copper-to-edge clearance. A pour of another net is a hard obstacle (with the pour's own clearance) unless the
plan lists it in `soft_pours` or the pour is a low-priority fill; a soft pour only costs.

Grid pitch. The default grid is (track + clearance) / 2, so that two tracks on adjacent legal cells are exactly
one fab pitch apart. `pitch_cells` is the number of cells between two parallel tracks; capacity.py uses it."""
import json
import math

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

FREE, BLOCK = -1, -2


def disk_lt(r, R):
    """grid offsets (dj, di) whose distance is strictly less than r"""
    k = int(math.ceil(r / R))
    return [(dj, di) for dj in range(-k, k + 1) for di in range(-k, k + 1) if math.hypot(dj, di) * R < r - 1e-9]


def lattice_radius(r, R):
    """Radius to use for a cell-to-cell conflict test so that copper drawn between cell centres (unit and
    diagonal steps) keeps the distance r. A diagonal step can pass closer to a lattice point than both of its
    ends only for particular r / R ratios; the radius is enlarged for those and left exact otherwise."""
    q = r / R
    k = 1
    while k / math.sqrt(2) < q + 1e-9:
        if k / math.sqrt(2) < q - 1e-9 and q <= math.sqrt(k * k / 2 + 0.5) + 1e-9:
            return math.sqrt(r * r + R * R / 2) + 1e-6
        k += 2
    return r


def dilate(a, offs):
    """boolean dilation of the last two axes of a by the offset list"""
    out = a.copy()
    H, W = a.shape[-2:]
    for dj, di in offs:
        if dj == 0 and di == 0:
            continue
        ys, yd = (slice(dj, H), slice(0, H - dj)) if dj >= 0 else (slice(0, H + dj), slice(-dj, H))
        xs, xd = (slice(di, W), slice(0, W - di)) if di >= 0 else (slice(0, W + di), slice(-di, W))
        out[..., yd, xd] |= a[..., ys, xs]
    return out


class Ctx:
    def __init__(self, model_path, plan_path):
        self.D = json.load(open(model_path))
        self.P = json.load(open(plan_path))
        self.plan_errors = []
        self.plan_warnings = []
        r = self.P.get("rules", {})
        br = self.D.get("board_rules", {})
        self.track = float(r.get("track", max(br.get("min_track", 0.0), 0.127)))
        self.clear = float(r.get("clear", max(br.get("min_clear", 0.0), 0.127)))
        self.via = float(r.get("via", max(br.get("min_via", 0.0), 0.6)))
        self.drill = float(r.get("drill", max(br.get("min_drill", 0.0), 0.3)))
        self.hole2hole = float(r.get("hole_to_hole", br.get("hole_to_hole", 0.25)))
        self.edge_clear = float(r.get("edge_clear", br.get("edge_clear", 0.5)))
        for name, val, lo in (("track", self.track, br.get("min_track", 0.0)), ("clear", self.clear, br.get("min_clear", 0.0)),
                              ("via", self.via, br.get("min_via", 0.0)), ("drill", self.drill, br.get("min_drill", 0.0)),
                              ("hole_to_hole", self.hole2hole, br.get("hole_to_hole", 0.0)),
                              ("edge_clear", self.edge_clear, br.get("edge_clear", 0.0))):
            if val < lo - 1e-9:
                self.plan_errors.append("rules.%s = %.3f is below the board setup minimum %.3f" % (name, val, lo))
        half = (self.track + self.clear) / 2
        self.R = float(r.get("res", round(half if half <= 0.13 else half / 2, 4)))
        self.thermal = float(r.get("thermal_keepout", 0.35))    # cost ring around through-hole pads on a pour
        # via-in-pad: False (default) = no via copper on or beside any SMD pad; True = allowed everywhere;
        # a list of "REF.PAD" = allowed at these pads only
        self.via_in_pad = r.get("via_in_pad", False)
        self.mask_margin = float(r.get("mask_margin", br.get("mask_margin", 0.05)))
        self.pitch_cells = int(math.ceil((self.track + self.clear) / self.R - 1e-9))
        self.pitch = self.pitch_cells * self.R
        if self.pitch > (self.track + self.clear) * 1.25:
            self.plan_warnings.append("grid %.3f mm gives a track pitch of %.3f mm against the fab pitch %.3f mm; "
                                      "use res = (track + clear) / 2" % (self.R, self.pitch, self.track + self.clear))
        self.yoff = self.P.get("frame", {}).get("y_flip_offset")
        self.LAYERS = self.D["layers"]
        self.NL = len(self.LAYERS)
        self.bx0, self.by0, self.bx1, self.by1 = self.D["bbox"]
        R = self.R
        self.nx = int(math.ceil((self.bx1 - self.bx0) / R)) + 1
        self.ny = int(math.ceil((self.by1 - self.by0) / R)) + 1
        self.X, self.Y = np.meshgrid(self.bx0 + np.arange(self.nx) * R, self.by0 + np.arange(self.ny) * R)
        self.nets = {}
        self.route_nets = set(self.P.get("route_nets", []))     # nets routed although they have a pour
        self.zone_nets = {it["net"] for it in self.D["items"] if it["kind"] == "zone"}
        self.keep = (set(self.P.get("keep_nets", [])) | self.zone_nets) - self.route_nets
        pl = self.P.get("plane_net")
        self.planes = set(pl if isinstance(pl, list) else [pl] if pl else [])
        self.keep |= self.planes
        self.soft_pours = set(self.P.get("soft_pours", []))
        self.hard_pours = set(self.P.get("hard_pours", []))
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

    def xy(self, j, i):
        return self.bx0 + i * self.R, self.by0 + j * self.R

    def nid(self, name):
        if not name:
            return BLOCK
        if name not in self.nets:
            self.nets[name] = len(self.nets)
        return self.nets[name]

    def sag(self, r):
        """margin added to a clearance radius r around fixed copper (diagonal step between two cell centres)"""
        return math.sqrt(r * r + self.R * self.R / 2) - r + 1e-4

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
        if g.is_empty:
            return 0, 0, 0, 0, np.zeros((0, 0), bool)
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
            sub[m & (sub != n) & (sub != FREE)] = BLOCK
            sub[m & (sub == FREE)] = n

    def zone_is_soft(self, it):
        if it.get("name") in self.hard_pours or it["net"] in self.hard_pours:
            return False
        if it.get("name") in self.soft_pours or it["net"] in self.soft_pours:
            return True
        return bool(it.get("soft"))

    # ------------------------------------------------------------ obstacles
    def _build_obstacles(self):
        D, NL = self.D, self.NL
        rT = self.clear + self.track / 2
        rV = self.clear + self.via / 2
        rT += self.sag(rT) + 0.01        # 0.01 mm: pad outlines are polygons that lie just inside the true arcs
        rV += self.sag(rV) + 0.01
        # header and wire pads only (drill >= 0.6 mm): a via-in-pad of an exposed pad has no thermal spokes
        th_pads = {(it.get("ref"), it.get("num")) for it in D["items"]
                   if it["kind"] == "hole" and (it.get("drill") or 0) >= 0.6}
        zone_on = {(it["net"], ln) for it in D["items"] if it["kind"] == "zone" for ln in it["layers"]}
        drilled = {(it.get("ref"), it.get("num")) for it in D["items"] if it["kind"] == "hole"}
        vip_ok = set(self.via_in_pad) if isinstance(self.via_in_pad, list) else set()
        smd_ban = []
        self.ownT = np.full((NL, self.ny, self.nx), FREE, np.int32)
        self.ownV = np.full((NL, self.ny, self.nx), FREE, np.int32)
        self.pourN = np.full((NL, self.ny, self.nx), FREE, np.int32)
        self.holeBan = np.zeros((self.ny, self.nx), bool)        # via centres too close to a drilled hole
        self.ring = np.zeros((NL, self.ny, self.nx), bool)        # thermal-spoke rings of poured through-hole pads
        self.selfban = {}        # net -> [(layer index, geometry for tracks, geometry for vias)]
        self.routable = set()
        for it in D["items"]:
            if it["kind"] in ("track", "via") and it["net"] not in self.keep and not it.get("locked"):
                self.routable.add(it["net"])
            if (it["kind"] == "pad" and it["net"] and it["net"] not in self.keep
                    and not it["net"].startswith("unconnected")):
                self.routable.add(it["net"])
        self.routable.discard("")
        # board edge
        if D.get("edge_poly"):
            inside = unary_union([Polygon(e["poly"], e.get("holes") or None).buffer(0) for e in D["edge_poly"]])
            for arr, half in ((self.ownT, self.track / 2), (self.ownV, self.via / 2)):
                ok = inside.buffer(-(self.edge_clear + half + self.sag(self.edge_clear + half)))
                m = shapely.contains_xy(ok, self.X, self.Y) if not ok.is_empty else np.zeros(self.X.shape, bool)
                arr[:, ~m] = BLOCK
        for it in D["items"]:
            kind = it["kind"]
            if kind in ("track", "via") and it["net"] in self.routable and not it.get("locked"):
                continue                                           # existing unlocked copper of a net to be routed
            if kind == "zone":
                if it["net"] in self.route_nets:
                    continue
                n = self.nid(it["net"])
                if self.zone_is_soft(it):
                    for ln in it["layers"]:
                        self._claim(self.pourN, self.LAYERS.index(ln), self.geom_of(it, rT), n)
                else:
                    zc = max(self.clear, it.get("clearance") or 0.0)
                    for ln in it["layers"]:
                        li = self.LAYERS.index(ln)
                        self._claim(self.ownT, li, self.geom_of(it, zc + self.track / 2 + self.sag(zc)), n)
                        self._claim(self.ownV, li, self.geom_of(it, zc + self.via / 2 + self.sag(zc)), n)
                continue
            if kind in ("hole", "via"):
                cx, cy, _ = it["circ"]
                dr = it.get("drill") or 2 * (it["circ"][2] - (0.127 if kind == "hole" else 0.15))
                g = Point(cx, cy).buffer(dr / 2 + self.hole2hole + self.drill / 2 + 0.01)
                j0, j1, i0, i1, m = self.raster(g)
                if m.size:
                    self.holeBan[j0:j1, i0:i1] |= m
            n = BLOCK if kind == "keepout" else self.nid(it["net"])
            for ln in it["layers"]:
                li = self.LAYERS.index(ln)
                if kind == "hole" and "flashed" in it and ln not in it["flashed"]:
                    # the pad is not flashed here; a track of its own net that touched the hole would make KiCad
                    # flash the full pad on this layer, into the space that other nets were given
                    self._claim(self.ownT, li, self.geom_of(it, rT), BLOCK)
                    self._claim(self.ownV, li, self.geom_of(it, rV), BLOCK)
                    if it.get("pad_poly") and it["net"]:
                        # copper of the pad's own net inside the pad outline would also flash the pad here
                        pg = Polygon(it["pad_poly"]).buffer(0)
                        self.selfban.setdefault(it["net"], []).append(
                            (li, pg.buffer(self.track / 2 + self.R), pg.buffer(self.via / 2 + self.R)))
                    continue
                if kind == "keepout":
                    g = self.geom_of(it)
                    if it.get("no_tracks", True):
                        self._claim(self.ownT, li, g.buffer(self.track / 2), BLOCK)
                    if it.get("no_vias", True):
                        self._claim(self.ownV, li, g.buffer(self.via / 2), BLOCK)
                else:
                    # a through-hole pad of a poured net needs room for its thermal spokes
                    self._claim(self.ownT, li, self.geom_of(it, rT), n)
                    self._claim(self.ownV, li, self.geom_of(it, rV), n)
                    # SMD pad: decided from the pad item itself (N-5, 2026-11-13). Keyed on (ref, number), the
                    # U101.25 exposed pad escaped the ban because its nine thermal vias are holes numbered 25.
                    # Models made before the "drilled" field fall back to the (ref, number) test.
                    is_smd = (not it["drilled"]) if "drilled" in it else (it.get("ref"), it.get("num")) not in drilled
                    if (kind == "pad" and is_smd and self.via_in_pad is not True
                            and "%s.%s" % (it.get("ref"), it.get("num")) not in vip_ok):
                        smd_ban.append((li, it))
                    if (kind == "pad" and (it["net"], ln) in zone_on
                            and (it.get("ref"), it.get("num")) in th_pads and self.thermal > 0):
                        # room for the thermal spokes: a cost ring, so a track uses it only without another way
                        j0, j1, i0, i1, m = self.raster(self.geom_of(it, rT + self.thermal))
                        if m.size:
                            self.ring[li, j0:j1, i0:i1] |= m
        # a via on an SMD pad, or with its copper inside the pad's solder-mask opening, takes solder from the
        # joint. KiCad DRC does not report it. The ban holds for the pad's own net too: a via joins a pad
        # through a track.
        vr = self.via / 2 + self.mask_margin
        for li, it in smd_ban:
            self._claim(self.ownV, li, self.geom_of(it, vr + self.sag(vr) + 0.01), BLOCK)
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
        # A pad cell is a legal track start only when a track centred on it clears the neighbouring copper.
        # A pad with no legal cell at this grid is "grid-sealed": it keeps all its cells and is reported.
        self.grid_sealed = []
        self.padcells = {}
        for net, groups in pads_of.items():
            n = self.nid(net)
            self.padcells[net] = {}
            for key, grp in groups.items():
                cells = [c for it in grp for c in self.cells_of(it)]
                legal = [c for c in cells if self.ownT[c] == n]
                if not legal and key[0] != "locked" and cells:
                    self.grid_sealed.append((net, key[0], key[1]))
                self.padcells[net][key] = legal or cells
        self.own = {net: {c for key, cs in groups.items() if key[0] != "locked" for c in cs}
                    for net, groups in self.padcells.items()}
        self.npads = {net: sum(1 for k in g if k[0] != "locked") for net, g in pads_of.items()}

    def self_ban(self, net, j0, j1, i0, i1):
        """(banT[NL, h, w], banV[h, w]) cells the net itself must not use (its own unflashed pads), or None"""
        if net not in self.selfban:
            return None
        banT = np.zeros((self.NL, j1 - j0, i1 - i0), bool)
        banV = np.zeros((j1 - j0, i1 - i0), bool)
        X, Y = self.X[j0:j1, i0:i1], self.Y[j0:j1, i0:i1]
        for li, gt, gv in self.selfban[net]:
            b = gt.bounds
            if b[2] < X[0, 0] or b[0] > X[0, -1] or b[3] < Y[0, 0] or b[1] > Y[-1, 0]:
                continue
            banT[li] |= shapely.contains_xy(gt, X, Y)
            banV |= shapely.contains_xy(gv, X, Y)
        return banT, banV

    def connections(self, net):
        return max(self.npads.get(net, 0) - 1, 0)

    def pad_centres(self, net):
        """[(ref, num, x, y)] in the KiCad frame"""
        out = []
        for (ref, num), grp in self.pads_of.get(net, {}).items():
            if ref == "locked":
                continue
            c = unary_union([self.geom_of(it) for it in grp]).centroid
            out.append((ref, num, c.x, c.y))
        return out

    def mst(self, net):
        """[(x1, y1, x2, y2)] minimum spanning tree over the pad centres (KiCad frame)"""
        pts = [(p[2], p[3]) for p in self.pad_centres(net)]
        if len(pts) < 2:
            return []
        inn, out, segs = [pts[0]], pts[1:], []
        while out:
            best = min(((math.hypot(a[0] - b[0], a[1] - b[1]), a, b) for a in inn for b in out), key=lambda t: t[0])
            segs.append((best[1][0], best[1][1], best[2][0], best[2][1]))
            inn.append(best[2])
            out.remove(best[2])
        return segs

    # ------------------------------------------------------------ plan: corridors and assignment
    def corridors(self):
        """id -> dict(layers=[layer index], geom=polygon (KiCad frame), path=[(x, y)] or None, width, reserve)"""
        if self._corr is None:
            self._corr = {}
            for c in self.P.get("corridors", []):
                layers = c.get("layers") or [c["layer"]]
                bad = [l for l in layers if l not in self.LAYERS]
                if bad:
                    self.plan_errors.append("corridor %s: layer %s is not a routing layer" % (c["id"], bad))
                    continue
                li = [self.LAYERS.index(l) for l in layers]
                if "path" in c:
                    path = [self.k(p) for p in c["path"]]
                    geom = LineString(path).buffer(c["width"] / 2, cap_style=2, join_style=2)
                else:
                    path = None
                    geom = Polygon([self.k(p) for p in c["polygon"]]).buffer(0)
                self._corr[c["id"]] = dict(layers=li, geom=geom, path=path, width=c.get("width"),
                                           note=c.get("note", ""), reserve=bool(c.get("reserve")))
        return self._corr

    @staticmethod
    def flat_route(route):
        """route list with alternatives -> [(corridor id, weight)]; an inner list is a set of alternatives"""
        out = []
        for e in route or []:
            if isinstance(e, list):
                out += [(cid, 1.0 / len(e)) for cid in e]
            else:
                out.append((e, 1.0))
        return out

    def _assign(self):
        """net -> dict(mode, route, escape, margin, priority, group, width, layers, layer_cost, directions)"""
        dflt = dict(mode="local", route=[], escape=1.5, margin=2.5, priority=5, group="(default)",
                    width=self.track, layers=None, layer_cost={}, directions=None, via_cost=None)
        dflt.update(self.P.get("default", {}))
        keys = ("mode", "route", "escape", "margin", "priority", "width", "layers", "layer_cost", "directions",
                "via_cost")
        self.assign = {}
        corr = self.corridors()
        for g in self.P.get("groups", []):
            for cid, _ in self.flat_route(g.get("route")):
                if cid not in corr:
                    self.plan_errors.append("group %s: unknown corridor %s" % (g.get("name"), cid))
            for l in (g.get("layers") or []):
                if l not in self.LAYERS:
                    self.plan_errors.append("group %s: layer %s is not a routing layer" % (g.get("name"), l))
            for net in g["nets"]:
                if net not in self.routable:
                    self.plan_errors.append("group %s: net %s is not a routable net" % (g.get("name"), net))
                    continue
                if net in self.assign:
                    self.plan_errors.append("net %s is in two groups (%s, %s)" % (net, self.assign[net]["group"],
                                                                               g.get("name")))
                a = dict(dflt)
                a.update({k: v for k, v in g.items() if k in keys})
                if g.get("route") and "mode" not in g:
                    a["mode"] = "corridor"
                a["group"] = g.get("name", "?")
                self.assign[net] = a
        for net in self.routable:
            self.assign.setdefault(net, dict(dflt))
        # per-net additions written by layer_assign.py and global_route.py; they work on top of the groups
        for net, d in self.P.get("net_layer_cost", {}).items():
            if net in self.assign:
                self.assign[net] = dict(self.assign[net], layer_cost=dict(self.assign[net].get("layer_cost") or {}, **d))
        for net, route in self.P.get("net_route", {}).items():
            if net in self.assign:
                for cid, _ in self.flat_route(route):
                    if cid not in corr:
                        self.plan_errors.append("net_route %s: unknown corridor %s" % (net, cid))
                self.assign[net] = dict(self.assign[net], mode="corridor", route=route)
        for net, a in self.assign.items():
            if a["width"] < self.track - 1e-9:
                self.plan_errors.append("net %s: width %.3f is below rules.track %.3f" % (net, a["width"], self.track))

    def allowed(self, net):
        """(j0, j1, i0, i1, mask[NL, h, w]): the cells the net may use"""
        if net in self._allowed:
            return self._allowed[net]
        a = self.assign[net]
        NL = self.NL
        pcs = self.pad_centres(net)
        lay_ok = [True] * NL if not a.get("layers") else [self.LAYERS[l] in a["layers"] for l in range(NL)]
        per_layer = [[] for _ in range(NL)]
        esc = [Point(p[2], p[3]).buffer(a["escape"]) for p in pcs]
        if a["mode"] == "free":
            g = box(self.bx0, self.by0, self.bx1, self.by1)
            for l in range(NL):
                if lay_ok[l]:
                    per_layer[l].append(g)
        elif a["mode"] == "local":
            xs = [p[2] for p in pcs] or [self.bx0]
            ys = [p[3] for p in pcs] or [self.by0]
            m = a["margin"]
            g = box(min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m)
            for l in range(NL):
                if lay_ok[l]:
                    per_layer[l].append(g)
        else:
            corr = self.corridors()
            for cid, _ in self.flat_route(a["route"]):
                c = corr.get(cid)
                if c:
                    for l in c["layers"]:
                        per_layer[l].append(c["geom"])
        if a["mode"] == "corridor" or a.get("layers"):
            for l in range(NL):                # the escape disc is on every layer: a pad may need a via to leave
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
