#!/usr/bin/env python3
"""
regenerate_outputs.py -- ONE command that rebuilds every derived output file
from the current meshes + solver results. It NEVER runs FastHenry.

For each config given, for each mesh pitch in its `sweep.mesh_sizes_mm`:
  * ensure the meshed geometry is in the cache (out/meshes/, built if missing)
  * render_mesh.py  -> <base>_m<pitch>_{mesh_forward,mesh_return,overlay,region}.png
  * export_mesh.py  -> <base>_m<pitch>_{forward,return,markers}.stl
Then report_results.py across ALL configs:
  * convergence_<freq>.{csv,md,png}   (mesh convergence @ designated frequency)
  * freq_sweep.{csv,md,png}           (frequency response @ designated mesh)

Solver results come from the stores written by sweep_inductance.py; missing
points warn but don't stop the regeneration.

Usage:
    python regenerate_outputs.py config_vout_fc.json config_vout_bt.json
                                 [--outdir out] [--skip-stl] [--skip-renders]
"""

from __future__ import annotations

import argparse
import os
import sys

import export_mesh
import model_cache
import render_mesh
import report_results
from gerber_inductance import load_config


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("configs", nargs="+", help="sweep configs (e.g. FC and BT)")
    ap.add_argument("--outdir", default=None, help="output dir (default ./out)")
    ap.add_argument("--skip-stl", action="store_true", help="skip STL exports")
    ap.add_argument("--skip-renders", action="store_true", help="skip PNG renders")
    args = ap.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    outdir = args.outdir or os.path.join(here, "out")
    os.makedirs(outdir, exist_ok=True)
    failures = 0

    for cp in args.configs:
        cfg = load_config(cp)
        base = os.path.splitext(os.path.basename(cp))[0]
        if "sweep" not in cfg:
            print(f"WARNING: {base} has no `sweep` block -- skipped")
            continue
        pitches = [float(m) for m in cfg["sweep"]["mesh_sizes_mm"]]
        print(f"\n=== {base}: {len(pitches)} mesh variant(s) {pitches} ===")
        for pitch in pitches:
            # make sure the cached model exists (renders/exports then hit the cache)
            model_cache.get_model(cfg, pitch, os.path.join(outdir, "meshes"), base)
            common = [cp, "--outdir", outdir, "--mesh-pitch", f"{pitch:g}"]
            if not args.skip_renders:
                print(f"  [render m={pitch:g}]")
                if render_mesh.main(common) != 0:
                    failures += 1
            if not args.skip_stl:
                print(f"  [stl    m={pitch:g}]")
                if export_mesh.main(common + ["--markers"]) != 0:
                    failures += 1

    print("\n=== reports ===")
    if report_results.main(args.configs + ["--outdir", outdir]) != 0:
        failures += 1

    if failures:
        print(f"\nDone with {failures} failure(s).")
        return 1
    print(f"\nAll outputs regenerated in {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
