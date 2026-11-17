"""Raster rectangle packer for courtyard placement.

The board plane is rasterised at RES mm. A cell is usable for a part when its centre lies inside the part's
allowed region and outside every placed courtyard. A courtyard rectangle is feasible when every cell whose
centre lies inside the rectangle (grown by MARGIN) is usable; a summed-area table answers that for all
candidate positions at once. The KiCad DRC remains the gate; the packer only proposes positions.
"""
import random

import numpy as np
import shapely

RES = 0.05
MARGIN = 0.03


class Grid:
    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0 = x0, y0
        self.nx = int(round((x1 - x0) / RES))
        self.ny = int(round((y1 - y0) / RES))
        xs = x0 + (np.arange(self.nx) + 0.5) * RES
        ys = y0 + (np.arange(self.ny) + 0.5) * RES
        self.X, self.Y = np.meshgrid(xs, ys)  # [ny, nx]

    def mask(self, geom):
        if geom is None or geom.is_empty:
            return np.zeros((self.ny, self.nx), bool)
        return shapely.contains_xy(geom, self.X, self.Y)

    def rect_cells(self, x0, y0, x1, y1):
        i0 = int(np.floor((x0 - MARGIN - self.x0) / RES + 0.5))
        i1 = int(np.ceil((x1 + MARGIN - self.x0) / RES - 0.5))
        j0 = int(np.floor((y0 - MARGIN - self.y0) / RES + 0.5))
        j1 = int(np.ceil((y1 + MARGIN - self.y0) / RES - 0.5))
        return max(i0, 0), min(i1, self.nx), max(j0, 0), min(j1, self.ny)


def sat(a):
    s = np.zeros((a.shape[0] + 1, a.shape[1] + 1), np.int32)
    s[1:, 1:] = np.cumsum(np.cumsum(a.astype(np.int32), 0), 1)
    return s


def feasible(grid, usable_sat, w, h):
    """Boolean [ny, nx] array: True where a w x h rectangle whose lower-left cell is (j, i) is fully usable."""
    kw = int(np.ceil((w + 2 * MARGIN) / RES))
    kh = int(np.ceil((h + 2 * MARGIN) / RES))
    ny, nx = grid.ny, grid.nx
    out = np.zeros((ny, nx), bool)
    if kw > nx or kh > ny:
        return out, kw, kh
    s = usable_sat
    tot = s[kh:, kw:] - s[:-kh, kw:] - s[kh:, :-kw] + s[:-kh, :-kw]
    out[: ny - kh + 1, : nx - kw + 1] = tot == kw * kh
    return out, kw, kh


def pack(grid, parts, occupied, regions, tries=60, seed=1, log=None):
    """parts: list of dict(ref, region, rects={rot: (dx0, dy0, dx1, dy1)}, target=(x, y) or None, size, prio)
    occupied: bool array of cells already taken on this side. regions: name -> bool mask.
    Returns {ref: (x, y, rot)} of the best attempt (most placed, then least total distance)."""
    rng = random.Random(seed)
    best = None
    base = sorted(parts, key=lambda p: (-p.get("prio", 0), -p["size"]))
    for t in range(tries):
        order = list(base)
        if t:
            # perturb the order within priority classes
            for k in range(len(order) - 1):
                if rng.random() < 0.35 and order[k].get("prio", 0) == order[k + 1].get("prio", 0):
                    order[k], order[k + 1] = order[k + 1], order[k]
        occ = occupied.copy()
        res, cost = {}, 0.0
        for p in order:
            usable = regions[p["region"]] & ~occ
            us = sat(usable)
            bestc = None
            for rot, (dx0, dy0, dx1, dy1) in p["rects"].items():
                w, h = dx1 - dx0, dy1 - dy0
                f, kw, kh = feasible(grid, us, w, h)
                if not f.any():
                    continue
                jj, ii = np.nonzero(f)
                # rectangle lower-left cell centre -> rectangle lower-left corner
                rx0 = grid.x0 + ii * RES + MARGIN
                ry0 = grid.y0 + jj * RES + MARGIN
                ox = rx0 - dx0
                oy = ry0 - dy0
                if p.get("target") is not None:
                    tx, ty = p["target"]
                    cx, cy = ox + (dx0 + dx1) / 2, oy + (dy0 + dy1) / 2
                    d = np.hypot(cx - tx, cy - ty)
                else:
                    d = ry0 * 1000 + rx0
                k = int(np.argmin(d))
                if bestc is None or d[k] < bestc[0]:
                    bestc = (float(d[k]), float(ox[k]), float(oy[k]), rot)
            if bestc is None:
                continue
            d, ox, oy, rot = bestc
            dx0, dy0, dx1, dy1 = p["rects"][rot]
            i0, i1, j0, j1 = grid.rect_cells(ox + dx0, oy + dy0, ox + dx1, oy + dy1)
            occ[j0:j1, i0:i1] = True
            res[p["ref"]] = (ox, oy, rot)
            cost += d if p.get("target") is not None else 0.0
        score = (len(res), -cost)
        if best is None or score > best[0]:
            best = (score, res, t)
        if len(res) == len(parts) and t >= 10:
            pass
    if log is not None:
        log.append("packer: best try %d placed %d of %d, cost %.1f" % (best[2], best[0][0], len(parts),
                                                                       -best[0][1]))
    return best[1]
