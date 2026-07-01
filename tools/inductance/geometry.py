"""
Rasterise Gerber primitives into a uniform copper mask, and pull out the
single connected net the user points at.

The mask is the bridge between "messy CAD geometry" and "regular grid the mesher
can turn into FastHenry bars". Everything is numpy from here on.

Pipeline:
    GerberLayer  --rasterize-->  CopperMask (bool grid)
    CopperMask + (x,y) point --select_net--> CopperMask of one connected region

Grid convention: cell (j, i) (row j, col i) has its CENTRE at
    x = x0 + (i + 0.5) * pitch
    y = y0 + (j + 0.5) * pitch
mask[j, i] == True  means that cell is copper.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from gerber import Aperture, GerberLayer, Region, Trace, Flash


# ----------------------------------------------------------------------------
# Copper mask
# ----------------------------------------------------------------------------

@dataclass
class CopperMask:
    mask: np.ndarray         # bool [ny, nx]
    x0: float                # world x of grid origin (left edge of col 0)
    y0: float                # world y of grid origin (bottom edge of row 0)
    pitch: float             # cell size (mm)

    @property
    def ny(self) -> int:
        return self.mask.shape[0]

    @property
    def nx(self) -> int:
        return self.mask.shape[1]

    def cell_center(self, j: int, i: int) -> tuple[float, float]:
        return (self.x0 + (i + 0.5) * self.pitch,
                self.y0 + (j + 0.5) * self.pitch)

    def world_to_cell(self, x: float, y: float) -> tuple[int, int]:
        i = int((x - self.x0) / self.pitch)
        j = int((y - self.y0) / self.pitch)
        return j, i

    def area_mm2(self) -> float:
        return float(self.mask.sum()) * self.pitch * self.pitch

    def copy_with(self, mask: np.ndarray) -> "CopperMask":
        return CopperMask(mask=mask, x0=self.x0, y0=self.y0, pitch=self.pitch)

    def filled_bbox(self) -> tuple[float, float, float, float] | None:
        """World (xmin,ymin,xmax,ymax) of the filled cells, or None if empty."""
        js, is_ = np.nonzero(self.mask)
        if len(js) == 0:
            return None
        return (self.x0 + is_.min() * self.pitch, self.y0 + js.min() * self.pitch,
                self.x0 + (is_.max() + 1) * self.pitch, self.y0 + (js.max() + 1) * self.pitch)

    def crop_to_bbox(self, bbox: tuple[float, float, float, float]) -> "CopperMask":
        """Zero out copper outside the world bbox (does not change the grid)."""
        xmin, ymin, xmax, ymax = bbox
        xs = self.x0 + (np.arange(self.nx) + 0.5) * self.pitch
        ys = self.y0 + (np.arange(self.ny) + 0.5) * self.pitch
        keep = np.outer((ys >= ymin) & (ys <= ymax), (xs >= xmin) & (xs <= xmax))
        return self.copy_with(self.mask & keep)


# ----------------------------------------------------------------------------
# Rasterisation
# ----------------------------------------------------------------------------

def rasterize(layer: GerberLayer,
              pitch: float,
              bbox: tuple[float, float, float, float] | None = None,
              margin: float = 0.5) -> CopperMask:
    """
    Rasterise every copper primitive of `layer` onto a uniform grid.

    pitch  : grid cell size in mm. Pick ~1/3 of the narrowest feature you care
             about. Smaller = more faithful but more FastHenry segments.
    bbox   : (xmin,ymin,xmax,ymax) to rasterise; default = layer.bbox()+margin.
    """
    if bbox is None:
        bx = layer.bbox()
        bbox = (bx[0] - margin, bx[1] - margin, bx[2] + margin, bx[3] + margin)
    xmin, ymin, xmax, ymax = bbox

    nx = max(1, int(np.ceil((xmax - xmin) / pitch)))
    ny = max(1, int(np.ceil((ymax - ymin) / pitch)))
    mask = np.zeros((ny, nx), dtype=bool)

    # Precompute cell-centre coordinate axes.
    xs = xmin + (np.arange(nx) + 0.5) * pitch
    ys = ymin + (np.arange(ny) + 0.5) * pitch

    # --- regions (filled polygons). LPD paints, LPC clears. -------------------
    for reg in layer.regions:
        _fill_polygon(mask, reg, xs, ys, xmin, ymin, pitch, paint=reg.dark)

    # --- traces (stroked segments) -------------------------------------------
    for tr in layer.traces:
        _stroke_segment(mask, tr, xs, ys, xmin, ymin, pitch)

    # --- flashes (pad placements) --------------------------------------------
    for fl in layer.flashes:
        _flash(mask, fl, xs, ys, xmin, ymin, pitch)

    return CopperMask(mask=mask, x0=xmin, y0=ymin, pitch=pitch)


def _cell_window(lo: float, hi: float, origin: float, pitch: float, n: int) -> tuple[int, int]:
    """Index range [a,b) of cells whose centres can lie in [lo,hi]."""
    a = int(np.floor((lo - origin) / pitch)) - 1
    b = int(np.ceil((hi - origin) / pitch)) + 1
    return max(0, a), min(n, b)


def _fill_polygon(mask, reg: Region, xs, ys, xmin, ymin, pitch, paint: bool) -> None:
    pts = np.asarray(reg.points, dtype=float)
    if len(pts) < 3:
        return
    px, py = pts[:, 0], pts[:, 1]
    i0, i1 = _cell_window(px.min(), px.max(), xmin, pitch, len(xs))
    j0, j1 = _cell_window(py.min(), py.max(), ymin, pitch, len(ys))
    if i0 >= i1 or j0 >= j1:
        return
    sub_x = xs[i0:i1]
    for j in range(j0, j1):
        inside = _row_inside(px, py, sub_x, ys[j])
        if paint:
            mask[j, i0:i1] |= inside
        else:
            mask[j, i0:i1] &= ~inside


def _row_inside(px, py, xq, yq) -> np.ndarray:
    """Even-odd point-in-polygon for a horizontal row of query x at height yq."""
    n = len(px)
    inside = np.zeros(len(xq), dtype=bool)
    j = n - 1
    for i in range(n):
        yi, yj = py[i], py[j]
        if (yi > yq) != (yj > yq):
            # x of the edge crossing at height yq
            xcross = px[i] + (yq - yi) / (yj - yi) * (px[j] - px[i])
            inside ^= (xq < xcross)
        j = i
    return inside


def _stroke_segment(mask, tr: Trace, xs, ys, xmin, ymin, pitch) -> None:
    r = tr.width / 2.0
    lo_x, hi_x = min(tr.x0, tr.x1) - r, max(tr.x0, tr.x1) + r
    lo_y, hi_y = min(tr.y0, tr.y1) - r, max(tr.y0, tr.y1) + r
    i0, i1 = _cell_window(lo_x, hi_x, xmin, pitch, len(xs))
    j0, j1 = _cell_window(lo_y, hi_y, ymin, pitch, len(ys))
    if i0 >= i1 or j0 >= j1:
        return
    sub_x = xs[i0:i1]
    dx, dy = tr.x1 - tr.x0, tr.y1 - tr.y0
    seg_len2 = dx * dx + dy * dy
    for j in range(j0, j1):
        yq = ys[j]
        if seg_len2 == 0.0:
            d2 = (sub_x - tr.x0) ** 2 + (yq - tr.y0) ** 2
        else:
            t = ((sub_x - tr.x0) * dx + (yq - tr.y0) * dy) / seg_len2
            t = np.clip(t, 0.0, 1.0)
            cxp = tr.x0 + t * dx
            cyp = tr.y0 + t * dy
            d2 = (sub_x - cxp) ** 2 + (yq - cyp) ** 2
        mask[j, i0:i1] |= (d2 <= r * r)


def _flash(mask, fl: Flash, xs, ys, xmin, ymin, pitch) -> None:
    hx, hy = fl.aperture.bbox_halfextent()
    i0, i1 = _cell_window(fl.x - hx, fl.x + hx, xmin, pitch, len(xs))
    j0, j1 = _cell_window(fl.y - hy, fl.y + hy, ymin, pitch, len(ys))
    if i0 >= i1 or j0 >= j1:
        return
    sub_x = xs[i0:i1]
    ap = fl.aperture
    for j in range(j0, j1):
        yq = ys[j]
        row = np.zeros(i1 - i0, dtype=bool)
        for k, xq in enumerate(sub_x):
            row[k] = ap.contains(xq - fl.x, yq - fl.y)
        mask[j, i0:i1] |= row


# ----------------------------------------------------------------------------
# Connected-net selection (4-connectivity flood fill, iterative)
# ----------------------------------------------------------------------------

def select_net(cm: CopperMask, x: float, y: float) -> CopperMask:
    """
    Return a mask containing only the copper region 4-connected to world point
    (x, y). This is how the user picks "the forward net" / "the return net":
    give a coordinate that lands on the copper of interest.
    """
    j, i = cm.world_to_cell(x, y)
    if not (0 <= j < cm.ny and 0 <= i < cm.nx) or not cm.mask[j, i]:
        # snap to nearest copper cell within a small radius
        j, i = _nearest_copper(cm.mask, j, i)
        if j is None:
            raise ValueError(f"No copper near ({x:.3f}, {y:.3f}) mm")
    out = _flood(cm.mask, j, i)
    return cm.copy_with(out)


def _nearest_copper(mask, j, i, radius=8):
    ny, nx = mask.shape
    best = None
    bestd = 1e9
    for dj in range(-radius, radius + 1):
        for di in range(-radius, radius + 1):
            jj, ii = j + dj, i + di
            if 0 <= jj < ny and 0 <= ii < nx and mask[jj, ii]:
                d = dj * dj + di * di
                if d < bestd:
                    bestd = d
                    best = (jj, ii)
    return best if best else (None, None)


def resample(cm: CopperMask, new_pitch: float,
             coverage: str = "any", thresh: float = 0.5) -> CopperMask:
    """
    Re-grid a mask to a coarser pitch over the same world extent by BLOCK
    coverage (not point sampling). Used to decouple the FINE pitch needed to
    isolate a net (resolve copper clearances) from the COARSER pitch that keeps
    the FastHenry segment count tractable: isolate on the fine grid, then
    resample the selected net down for meshing.

    coverage='any'      : a coarse cell is copper if ANY underlying fine cell is.
                          This closes sub-pitch holes (via antipads, thermal
                          reliefs) so a hole-riddled ground plane stays a single
                          connected mesh -- point-sampling instead shatters it
                          into many fragments and FastHenry sees an open circuit.
    coverage='fraction' : copper if filled-fraction >= thresh (keeps widths truer
                          for solid traces, but can drop thin features).

    Safe because resample operates on an ALREADY-isolated single-net mask, so
    'any' cannot pull in a neighbouring net.
    """
    width = cm.nx * cm.pitch
    height = cm.ny * cm.pitch
    nx = max(1, int(round(width / new_pitch)))
    ny = max(1, int(round(height / new_pitch)))
    # map each fine cell to its coarse cell index
    ci = np.clip(((np.arange(cm.nx) + 0.5) * cm.pitch / new_pitch).astype(int), 0, nx - 1)
    cj = np.clip(((np.arange(cm.ny) + 0.5) * cm.pitch / new_pitch).astype(int), 0, ny - 1)
    CI = np.broadcast_to(ci[None, :], cm.mask.shape)
    CJ = np.broadcast_to(cj[:, None], cm.mask.shape)
    filled = np.zeros((ny, nx), dtype=np.int32)
    total = np.zeros((ny, nx), dtype=np.int32)
    np.add.at(filled, (CJ, CI), cm.mask.astype(np.int32))
    np.add.at(total, (CJ, CI), 1)
    if coverage == "fraction":
        new = (total > 0) & (filled >= np.ceil(thresh * np.maximum(total, 1)))
    else:                                        # 'any'
        new = filled > 0
    return CopperMask(mask=new, x0=cm.x0, y0=cm.y0, pitch=new_pitch)


def bridge_gaps(cm: CopperMask, iters: int = 1) -> CopperMask:
    """
    Binary morphological closing (dilate then erode, 8-connected) to bridge
    sub-pitch gaps/necks that the coarse resample opened in a plane. Reconnects
    a ground pour that a row of via holes would otherwise split into separate
    mesh fragments, without growing the outer boundary.
    """
    m = cm.mask
    for _ in range(iters):
        m = _dilate(m)
    for _ in range(iters):
        m = _erode(m)
    return cm.copy_with(m)


def _shift_or(m):
    out = m.copy()
    out[1:, :] |= m[:-1, :]; out[:-1, :] |= m[1:, :]
    out[:, 1:] |= m[:, :-1]; out[:, :-1] |= m[:, 1:]
    out[1:, 1:] |= m[:-1, :-1]; out[:-1, :-1] |= m[1:, 1:]
    out[1:, :-1] |= m[:-1, 1:]; out[:-1, 1:] |= m[1:, :-1]
    return out


def _dilate(m):
    return _shift_or(m)


def _erode(m):
    return ~_shift_or(~m)


def largest_component(cm: CopperMask) -> CopperMask:
    """Keep only the largest 4-connected component (drops island artifacts)."""
    nets = list_nets(cm, min_cells=1)
    if not nets:
        return cm
    cx, cy = nets[0]["centroid"]
    return select_net(cm, cx, cy)


def list_nets(cm: CopperMask, min_cells: int = 20):
    """
    Label all 4-connected copper regions and return them sorted by area, as
    dicts: {cells, area_mm2, centroid:(x,y), bbox:(xmin,ymin,xmax,ymax)}.
    Use this to discover coordinates to drop into a config (point at a net).
    """
    labels = np.zeros(cm.mask.shape, dtype=np.int32)
    cur = 0
    nets = []
    ny, nx = cm.mask.shape
    for sj in range(ny):
        for si in range(nx):
            if cm.mask[sj, si] and labels[sj, si] == 0:
                cur += 1
                comp = _flood(cm.mask, sj, si)
                labels[comp] = cur
                js, is_ = np.nonzero(comp)
                if len(js) < min_cells:
                    continue
                cx = cm.x0 + (is_.mean() + 0.5) * cm.pitch
                cy = cm.y0 + (js.mean() + 0.5) * cm.pitch
                bbox = (cm.x0 + is_.min() * cm.pitch, cm.y0 + js.min() * cm.pitch,
                        cm.x0 + (is_.max() + 1) * cm.pitch, cm.y0 + (js.max() + 1) * cm.pitch)
                nets.append({
                    "cells": int(len(js)),
                    "area_mm2": float(len(js)) * cm.pitch * cm.pitch,
                    "centroid": (float(cx), float(cy)),
                    "bbox": tuple(float(v) for v in bbox),
                })
    nets.sort(key=lambda d: d["area_mm2"], reverse=True)
    return nets


def _flood(mask, j0, i0) -> np.ndarray:
    ny, nx = mask.shape
    out = np.zeros_like(mask)
    stack = [(j0, i0)]
    out[j0, i0] = True
    while stack:
        j, i = stack.pop()
        for dj, di in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            jj, ii = j + dj, i + di
            if 0 <= jj < ny and 0 <= ii < nx and mask[jj, ii] and not out[jj, ii]:
                out[jj, ii] = True
                stack.append((jj, ii))
    return out
