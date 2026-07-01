"""
Minimal binary-STL writer + geometry helpers to turn a meshed CopperMask into a
3D solid you can load and measure in CAD.

Each filled mesh cell becomes an axis-aligned box (a voxel) at the conductor's
z-plane, so the exported solid *shows the discretization FastHenry actually used*
and preserves true dimensions (mm). Two conductors at their real z-separation let
you measure the dielectric gap and pour extents directly.

Dependencies: numpy + stdlib struct only.
"""

from __future__ import annotations

import struct

import numpy as np

from fasthenry import Conductor

# Corner order for a unit box, indices used by the triangle table below:
#   0:000  1:100  2:110  3:010  4:001  5:101  6:111  7:011   (bit = x,y,z)
_CORNERS = np.array([
    [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
    [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
], dtype=np.float64)

# 12 triangles (2 per face), wound CCW as seen from outside so the right-hand
# rule gives outward normals (verified face-by-face).
_TRIS = np.array([
    [4, 5, 6], [4, 6, 7],   # +z top
    [0, 3, 2], [0, 2, 1],   # -z bottom
    [1, 2, 6], [1, 6, 5],   # +x
    [0, 4, 7], [0, 7, 3],   # -x
    [3, 7, 6], [3, 6, 2],   # +y
    [0, 1, 5], [0, 5, 4],   # -y
], dtype=np.int64)


def boxes_triangles(mins: np.ndarray, sizes: np.ndarray) -> np.ndarray:
    """
    Triangulate a batch of axis-aligned boxes.
    mins  : (M,3) lower corner of each box (x0,y0,z0)
    sizes : (M,3) box extent (dx,dy,dz)
    returns (M*12, 3, 3) triangle vertices.
    """
    mins = np.asarray(mins, float).reshape(-1, 3)
    sizes = np.asarray(sizes, float).reshape(-1, 3)
    # (M,8,3) corners = mins + corner_pattern * sizes
    corners = mins[:, None, :] + _CORNERS[None, :, :] * sizes[:, None, :]
    tris = corners[:, _TRIS, :]                 # (M,12,3,3)
    return tris.reshape(-1, 3, 3)


def conductor_triangles(cond: Conductor, z_scale: float = 1.0) -> np.ndarray:
    """
    One voxel box per filled cell of a conductor's mesh. The box spans the cell
    footprint in x/y and [z-t/2, z+t/2] in z (FastHenry centre-plane convention),
    so two conductors' inner faces are exactly `dielectric_thickness` apart.
    z_scale multiplies z for visualisation only (distorts measurement if != 1).
    """
    cm = cond.mask
    js, is_ = np.nonzero(cm.mask)
    n = len(js)
    p = cm.pitch
    mins = np.empty((n, 3))
    mins[:, 0] = cm.x0 + is_ * p
    mins[:, 1] = cm.y0 + js * p
    mins[:, 2] = (cond.z - cond.thickness / 2.0) * z_scale
    sizes = np.empty((n, 3))
    sizes[:, 0] = p
    sizes[:, 1] = p
    sizes[:, 2] = cond.thickness * z_scale
    return boxes_triangles(mins, sizes)


def marker_cube(x: float, y: float, z: float, size: float = 0.5,
                z_scale: float = 1.0) -> np.ndarray:
    """A small cube centred at (x,y,z) to mark a port/closure point."""
    h = size / 2.0
    mins = np.array([[x - h, y - h, z * z_scale - h]])
    sizes = np.array([[size, size, size]])
    return boxes_triangles(mins, sizes)


_STL_REC = np.dtype([
    ("n", "<f4", 3), ("v1", "<f4", 3), ("v2", "<f4", 3),
    ("v3", "<f4", 3), ("attr", "<u2"),
])
assert _STL_REC.itemsize == 50, "binary STL record must be 50 bytes"


def write_binary_stl(path: str, tris: np.ndarray,
                     header: bytes = b"gerber_inductance mesh export") -> int:
    """Write triangles (…,3,3) to a binary STL file. Returns the triangle count."""
    tris = np.asarray(tris, dtype=np.float64).reshape(-1, 3, 3)
    n = len(tris)
    v1, v2, v3 = tris[:, 0], tris[:, 1], tris[:, 2]
    normals = np.cross(v2 - v1, v3 - v1)
    lens = np.linalg.norm(normals, axis=1, keepdims=True)
    lens[lens == 0] = 1.0
    normals = normals / lens
    rec = np.zeros(n, dtype=_STL_REC)
    rec["n"] = normals
    rec["v1"], rec["v2"], rec["v3"] = v1, v2, v3
    # binary STL header must be 80 bytes and must NOT start with "solid"
    hdr = header[:80].ljust(80, b" ")
    with open(path, "wb") as f:
        f.write(hdr)
        f.write(struct.pack("<I", n))
        f.write(rec.tobytes())
    return n


def triangles_bbox(tris: np.ndarray):
    """(min xyz, max xyz) over a triangle array — for the printed summary."""
    v = np.asarray(tris, float).reshape(-1, 3)
    return v.min(axis=0), v.max(axis=0)
