#!/usr/bin/env python3
"""
export_mesh.py -- export the meshed conductors a config resolves to as STL solids
for inspection/measurement in CAD.

It rebuilds the EXACT geometry the solver uses (via gerber_inductance.build_model)
and writes the forward pour and the return plane as separate STL files at their
true z-separation. Each mesh cell becomes a voxel box, so you can see the
discretization and measure real dimensions (pour extents, the dielectric gap,
loop length).

Usage:
    python export_mesh.py <config.json> [--outdir out] [--fine] [--markers] [--z-scale N]

Everything is written under --outdir (default ./out, inside tools/inductance/).
STL vertices are in millimetres; import into CAD as mm.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

import fasthenry as fh
import model_cache
import stl_export as stl
from gerber_inductance import load_config


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", help="JSON config (same file the solver uses)")
    ap.add_argument("--outdir", default=None, help="output dir (default ./out)")
    ap.add_argument("--mesh-pitch", type=float, default=None,
                    help="override the config's mesh_pitch_mm (sweep variants); "
                         "output filenames gain a _m<pitch> suffix")
    ap.add_argument("--fine", action="store_true",
                    help="also export the isolation-pitch TRUE copper (shows meshing error)")
    ap.add_argument("--markers", action="store_true",
                    help="also export small cubes at the port + closure points")
    ap.add_argument("--z-scale", type=float, default=1.0,
                    help="multiply z for visibility (default 1.0 = true scale; "
                         "any other value DISTORTS measurements)")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    here = os.path.dirname(os.path.abspath(__file__))
    outdir = args.outdir or cfg.get("outdir") or os.path.join(here, "out")
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.config))[0]
    pitch = args.mesh_pitch if args.mesh_pitch is not None else float(cfg["mesh_pitch_mm"])
    # suffix the outputs only when overridden, so default behavior is unchanged
    base = stem + (f"_m{pitch:g}" if args.mesh_pitch is not None else "")
    zs = float(args.z_scale)
    if zs != 1.0:
        print(f"WARNING: --z-scale={zs} distorts z; measurements in CAD will be wrong "
              f"in z. Use 1.0 for measurement.")

    model = model_cache.get_model(cfg, pitch, os.path.join(outdir, "meshes"), stem)
    z_fwd = model.h_di + model.t_cu
    z_ret = 0.0

    def _emit(tris, suffix, label):
        path = os.path.join(outdir, f"{base}_{suffix}.stl")
        n = stl.write_binary_stl(path, tris)
        lo, hi = stl.triangles_bbox(tris)
        print(f"  {label:16s} {n:7d} tris  "
              f"x[{lo[0]:.2f},{hi[0]:.2f}] y[{lo[1]:.2f},{hi[1]:.2f}] "
              f"z[{lo[2]:.4f},{hi[2]:.4f}]  -> {os.path.basename(path)}")
        return lo, hi

    print(f"[mesh export] {base}  (mesh_pitch={model.mesh_pitch} mm, "
          f"copper={model.t_cu} mm, dielectric={model.h_di} mm)")
    print("  --- coarse mesh (as solved) ---")
    _emit(stl.conductor_triangles(model.forward, zs), "forward", "forward (VOUT)")
    _emit(stl.conductor_triangles(model.ret, zs), "return", "return (GND)")

    if args.fine:
        print("  --- fine (isolation-pitch true copper) ---")
        fwd_fine_cond = fh.Conductor(model.fwd_fine, z=z_fwd, thickness=model.t_cu, tag="f")
        ret_fine_cond = fh.Conductor(model.ret_fine, z=z_ret, thickness=model.t_cu, tag="r")
        _emit(stl.conductor_triangles(fwd_fine_cond, zs), "fine_forward", "fine forward")
        _emit(stl.conductor_triangles(ret_fine_cond, zs), "fine_return", "fine return")

    if args.markers:
        tris = []
        ta = cfg["terminal_a"]; tb = cfg["terminal_b"]
        tris.append(stl.marker_cube(ta[0], ta[1], z_fwd, size=0.6, z_scale=zs))   # port + (forward)
        tris.append(stl.marker_cube(tb[0], tb[1], z_ret, size=0.6, z_scale=zs))   # port - (return)
        for p in cfg.get("closure", {}).get("points", []):
            tris.append(stl.marker_cube(p[0], p[1], z_fwd, size=0.6, z_scale=zs))  # closure (forward)
        _emit(np.concatenate(tris, axis=0), "markers", "markers (A/B/closure)")

    gap = model.h_di
    print(f"  dielectric gap (return top face -> forward bottom face) = {gap:.4f} mm"
          + ("" if zs == 1.0 else f"  (x{zs} in file = {gap*zs:.4f} mm)"))
    print(f"Done. STL files in {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
