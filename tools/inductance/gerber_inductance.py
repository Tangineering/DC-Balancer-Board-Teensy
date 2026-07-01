#!/usr/bin/env python3
"""
gerber_inductance.py -- estimate the parasitic LOOP inductance between two nodes
of a PCB, straight from the fabrication Gerbers.

Pipeline (see README.md for the physics and assumptions):
    copper Gerbers + drill  ->  copper masks  ->  pick forward net + return net
    ->  uniform-mesh FastHenry deck (port A<->B, vias close the loop)
    ->  run FastHenry  ->  L(f) table + plot, checked against a closed-form bound.

Everything written goes under --outdir (default ./out, inside tools/inductance/).
The script only READS the Gerbers; it never writes outside the output dir.

Usage:
    python gerber_inductance.py config.json [--outdir out] [--fasthenry PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass

import analytic
import fasthenry as fh
from gerber import parse_gerber, parse_excellon
from geometry import (CopperMask, rasterize, select_net, resample, bridge_gaps,
                      largest_component, list_nets)


def load_layer(cfg, key, pitch):
    """Rasterise the copper file named by cfg[key]['file'] over the full board."""
    spec = cfg[key]
    path = os.path.join(cfg["gerber_dir"], spec["file"])
    layer = parse_gerber(path)
    cm = rasterize(layer, pitch)
    return layer, cm


def load_config(config_path):
    """Read the JSON config; resolve gerber_dir relative to the config file."""
    with open(config_path) as f:
        cfg = json.load(f)
    if not os.path.isabs(cfg["gerber_dir"]):
        cfg["gerber_dir"] = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(config_path)), cfg["gerber_dir"]))
    return cfg


@dataclass
class Model:
    """The meshed geometry a config resolves to (shared by solver + STL export)."""
    forward: "fh.Conductor"      # coarse forward mesh, at z=h_di+t_cu
    ret: "fh.Conductor"          # coarse return mesh, at z=0
    fwd_fine: CopperMask         # isolation-pitch (true) forward copper
    ret_fine: CopperMask         # isolation-pitch (true) return copper (cropped)
    mesh_pitch: float
    iso_pitch: float
    t_cu: float
    h_di: float


def build_model(cfg, verbose=True):
    """
    Config -> the two meshed conductors FastHenry uses, plus the fine
    (isolation-pitch) copper and the resolved stackup/pitch parameters. Shared by
    the solver CLI (main) and the STL mesh exporter so both build IDENTICAL
    geometry. cfg must have gerber_dir already resolved (see load_config).
    """
    iso_pitch = float(cfg.get("isolation_pitch_mm", 0.1))
    mesh_pitch = float(cfg["mesh_pitch_mm"]) if "mesh_pitch_mm" in cfg else float(cfg["pitch_mm"])
    stack = cfg["stackup"]
    t_cu = float(stack["copper_thickness_mm"])
    h_di = float(stack["dielectric_thickness_mm"])

    if verbose:
        print(f"[1] parsing + rasterising copper (isolation pitch={iso_pitch} mm) ...")
    _, fwd_full = load_layer(cfg, "forward", iso_pitch)
    _, ret_full = load_layer(cfg, "return", iso_pitch)

    if verbose:
        print("[2] selecting + resampling nets ...")
    fwd_fine = select_net(fwd_full, *tuple(cfg["forward"]["point"]))
    ret_fine = select_net(ret_full, *tuple(cfg["return"]["point"]))
    if verbose:
        _warn_dominance("forward", fwd_fine, fwd_full)

    # Crop the return plane to the forward net's footprint + margin (return
    # current concentrates under the forward path; also keeps the mesh tractable).
    margin = float(cfg.get("return_margin_mm", 5.0))
    fbb = fwd_fine.filled_bbox()
    if fbb is not None:
        crop = (fbb[0] - margin, fbb[1] - margin, fbb[2] + margin, fbb[3] + margin)
        ret_fine = ret_fine.crop_to_bbox(crop)
        if verbose:
            print(f"    cropped return plane to forward footprint +{margin}mm "
                  f"-> {ret_fine.area_mm2():.1f} mm^2")

    # Resample to the coarse mesh grid, close sub-pitch holes, keep the largest
    # connected component (a single electrical body -> the loop is closeable).
    def _to_mesh(fine, label):
        coarse = largest_component(bridge_gaps(resample(fine, mesh_pitch)))
        ncomp = len(list_nets(resample(fine, mesh_pitch), min_cells=1))
        if verbose and ncomp > 1:
            print(f"    {label}: coarse mesh had {ncomp} fragments -> closed + kept "
                  f"largest ({int(coarse.mask.sum())} cells)")
        return coarse

    fwd_net = _to_mesh(fwd_fine, "forward")
    ret_net = _to_mesh(ret_fine, "return")
    if verbose:
        print(f"    forward net area = {fwd_fine.area_mm2():.2f} mm^2  "
              f"-> mesh {int(fwd_net.mask.sum())} cells @ {mesh_pitch} mm")
        print(f"    return  net area = {ret_fine.area_mm2():.2f} mm^2  "
              f"-> mesh {int(ret_net.mask.sum())} cells @ {mesh_pitch} mm")

    # z placement: bottom copper plane at 0, top copper plane at dielectric+cu.
    forward = fh.Conductor(mask=fwd_net, z=h_di + t_cu, thickness=t_cu, tag="f")
    ret = fh.Conductor(mask=ret_net, z=0.0, thickness=t_cu, tag="r")
    return Model(forward, ret, fwd_fine, ret_fine, mesh_pitch, iso_pitch, t_cu, h_di)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", help="JSON config (see config.example.json)")
    ap.add_argument("--outdir", default=None, help="output dir (default ./out)")
    ap.add_argument("--fasthenry", default=None, help="path to fasthenry binary")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the .inp and analytic bound but do not run FastHenry")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    here = os.path.dirname(os.path.abspath(__file__))
    outdir = args.outdir or cfg.get("outdir") or os.path.join(here, "out")
    os.makedirs(outdir, exist_ok=True)

    model = build_model(cfg)
    forward, ret = model.forward, model.ret
    fwd_net, ret_net = forward.mask, ret.mask
    fwd_fine, ret_fine = model.fwd_fine, model.ret_fine
    mesh_pitch, t_cu, h_di = model.mesh_pitch, model.t_cu, model.h_di

    # Loop closure. Two physical cases (see fasthenry.build_inp):
    #   closure.type == "short": forward & return are different nets (power/gnd);
    #       the loop closes through an external component -> ideal .equiv short.
    #   closure.type == "via":   forward & return are the same net on two layers;
    #       the loop closes through real copper vias (explicit list or drill-detected).
    closure = cfg.get("closure", {"type": "short", "points": [cfg["terminal_a"]]})
    ctype = closure.get("type", "short")
    vias, shorts = [], []
    if ctype == "short":
        shorts = [tuple(p) for p in closure.get("points", [cfg["terminal_a"]])]
        print(f"[3] loop closure: {len(shorts)} ideal short(s) (.equiv) "
              f"at {shorts}")
    else:
        if closure.get("points"):
            for v in closure["points"]:
                vias.append(fh.Via(float(v[0]), float(v[1]),
                                   float(v[2]) if len(v) > 2 else mesh_pitch))
        elif cfg.get("drill_file"):
            holes = parse_excellon(os.path.join(cfg["gerber_dir"], cfg["drill_file"]))
            for h in holes:
                fj, fi = fwd_net.world_to_cell(h.x, h.y)
                rj, ri = ret_net.world_to_cell(h.x, h.y)
                if (0 <= fj < fwd_net.ny and 0 <= fi < fwd_net.nx and fwd_net.mask[fj, fi]
                        and 0 <= rj < ret_net.ny and 0 <= ri < ret_net.nx and ret_net.mask[rj, ri]):
                    vias.append(fh.Via(h.x, h.y, h.diameter))
        print(f"[3] loop closure: {len(vias)} via(s) tying forward<->return")
        if not vias:
            print("    WARNING: no via ties the forward net to the return net -> the "
                  "loop is OPEN and FastHenry will report an open circuit. Add "
                  "explicit closure.points [[x,y,dia]] (a via location).")

    frq = cfg["freq"]
    print("[4] building FastHenry deck ...")
    text, meta = fh.build_inp(
        forward, ret, vias,
        term_a=tuple(cfg["terminal_a"]),
        term_b=tuple(cfg["terminal_b"]),
        fmin=float(frq["fmin"]), fmax=float(frq["fmax"]), ndec=float(frq["ndec"]),
        skin_ref_freq=float(frq.get("skin_ref_freq", frq["fmax"])),
        max_filaments=int(cfg.get("max_filaments", 5)),
        shorts=shorts,
    )
    inp_path = os.path.join(outdir, "loop.inp")
    with open(inp_path, "w") as f:
        f.write(text)
    print(f"    nodes={meta['nodes']} segments={meta['segments']} "
          f"vias={meta['via_segments']} shorts={meta['shorts']} "
          f"skin_depth@fmax={meta['skin_depth_mm']*1000:.1f} um")
    print(f"    wrote {inp_path}")
    # Rough runtime estimate (calibrated: ~1900 seg x 9 freq took ~900s).
    nfreq = int(round(math.log10(float(frq["fmax"]) / float(frq["fmin"]))
                      * float(frq["ndec"]))) + 1
    est_s = nfreq * (meta["segments"] / 1000.0) ** 2 * 25.0
    print(f"    est. solve time ~ {est_s:.0f}s for {nfreq} freq point(s) "
          f"(grows ~quadratically with segments)")
    if est_s > 180:
        print("    NOTE: this will be slow. For a faster preview increase "
              "mesh_pitch_mm, shrink return_margin_mm, or lower freq.ndec / range. "
              "Run large solves in the background.")

    # analytic sanity bound -----------------------------------------------------
    # Loop length is port -> closure (where the loop turns around), NOT the small
    # A-B port gap. Effective width ~ sqrt(forward area) as a rough mean width.
    ax, ay = cfg["terminal_a"]
    if shorts:
        cx, cy = shorts[0]
    elif vias:
        cx, cy = vias[0].x, vias[0].y
    else:
        cx, cy = cfg["terminal_b"]
    loop_len = math.hypot(cx - ax, cy - ay)
    eff_w = (fwd_fine.area_mm2() / loop_len) if loop_len > mesh_pitch else math.sqrt(
        max(fwd_fine.area_mm2(), 1.0))
    L_micro = analytic.microstrip_loop_inductance(max(loop_len, mesh_pitch),
                                                  max(eff_w, mesh_pitch), h_di + t_cu)
    print(f"[5] analytic sanity bound (microstrip, loop_len~{loop_len:.1f}mm, "
          f"w_eff~{eff_w:.1f}mm, h~{h_di+t_cu:.3f}mm): "
          f"L ~ {L_micro*1e9:.2f} nH  (order-of-magnitude check only)")

    mode, target = fh.find_solver(args.fasthenry or cfg.get("fasthenry_path"))
    if args.dry_run or mode is None:
        if mode is None:
            print("\n[6] No FastHenry found. Install the FastFieldSolvers build "
                  "(its COM server is auto-detected on Windows), or put a "
                  "command-line `fasthenry` on PATH / pass --fasthenry PATH. The "
                  "deck above is ready to solve:")
            print(f"        fasthenry {os.path.basename(inp_path)}   (run inside {outdir})")
        else:
            print(f"\n[6] --dry-run: skipping solve (solver found: {mode} -> {target}).")
        return 0

    print(f"[6] running FastHenry ({mode}: {target}) ...")
    if mode == "com":
        # Solve the sweep as single-frequency points: the COM server is reliable
        # per-point but flaky on multi-frequency decks.
        freqs = fh.sweep_frequencies(float(frq["fmin"]), float(frq["fmax"]),
                                     float(frq["ndec"]))
        # merge any explicit extra frequencies (e.g. the switching frequency)
        freqs = sorted(set(freqs) | {float(x) for x in frq.get("extra", [])})

        def _prog(i, n, row):
            print(f"    [{i}/{n}] {row[0]:.3g} Hz -> L={row[2]*1e9:.4f} nH "
                  f"R={row[1]*1e3:.4f} mOhm", flush=True)

        rows = fh.run_sweep_per_freq(inp_path, freqs, outdir, progid=target,
                                     progress=_prog)
    else:
        rows = fh.inductance_table(fh.parse_zc(fh.run_fasthenry(inp_path, target, outdir)))
    print("\n     freq[Hz]        R[mOhm]      L[nH]")
    for f, R, L in rows:
        rstr = f"{R*1e3:10.4f}" if R == R else "      n/a "   # NaN check
        print(f"   {f:12.4g}   {rstr}   {L*1e9:10.4f}")

    _maybe_plot(rows, outdir, L_micro)
    print(f"\nDone. Artifacts in {outdir}")
    return 0


def _warn_dominance(name, net, full):
    """A net covering most of the layer usually means clearances merged at this
    pitch -- warn the user to lower isolation_pitch_mm."""
    total = int(full.mask.sum())
    if total and net.mask.sum() / total > 0.7:
        print(f"    WARNING: {name} net is {100*net.mask.sum()/total:.0f}% of all "
              f"copper on its layer -- distinct nets likely merged. Lower "
              f"isolation_pitch_mm below the board's copper clearance.")


def _maybe_plot(rows, outdir, L_bound):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:                       # noqa: BLE001
        print(f"(plot skipped: matplotlib unavailable: {e})")
        return
    fs = [r[0] for r in rows]
    Ls = [r[2] * 1e9 for r in rows]
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.semilogx(fs, Ls, "o-", label="FastHenry loop L")
    ax.axhline(L_bound * 1e9, ls="--", color="gray", label="analytic bound")
    ax.set_xlabel("frequency [Hz]")
    ax.set_ylabel("loop inductance [nH]")
    ax.set_title("Parasitic loop inductance vs frequency")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    out = os.path.join(outdir, "inductance_vs_freq.png")
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    print(f"     plot: {out}")


if __name__ == "__main__":
    sys.exit(main())
