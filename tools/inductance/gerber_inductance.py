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

# Widest GND-plane clearance slot (mm) the mesher must bridge so the return plane
# stays a single connected body at every mesh pitch. bridge_gaps closes 2*iters*
# pitch, so iters is scaled as ceil(BRIDGE_GAP_MM/(2*pitch)). Measured empirically:
# at <=0.15mm the FC return plane severed with the old fixed 1-iteration closing;
# 0.6mm restores full connectivity at 0.20/0.15/0.10mm (see build_model).
BRIDGE_GAP_MM = 0.6

# If largest_component keeps a smaller fraction of the resampled copper than this,
# the plane was severed (a meshing artifact), not merely de-speckled -> warn loudly.
SEVERED_PLANE_FRAC = 0.90


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


def build_model(cfg, mesh_pitch=None, verbose=True):
    """
    Config -> the two meshed conductors FastHenry uses, plus the fine
    (isolation-pitch) copper and the resolved stackup/pitch parameters. Shared by
    the solver CLIs (main, sweep_inductance) and the STL/PNG mesh exporters so
    all build IDENTICAL geometry. cfg must have gerber_dir already resolved
    (see load_config). mesh_pitch (mm) overrides the config's mesh_pitch_mm so
    sweep callers don't have to mutate cfg.
    """
    iso_pitch = float(cfg.get("isolation_pitch_mm", 0.1))
    if mesh_pitch is None:
        mesh_pitch = float(cfg["mesh_pitch_mm"]) if "mesh_pitch_mm" in cfg else float(cfg["pitch_mm"])
    mesh_pitch = float(mesh_pitch)
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
    #
    # bridge_gaps is a morphological CLOSING: n iterations bridge interior slots
    # up to 2*n cells wide WITHOUT growing the outer boundary. The two conductors
    # need OPPOSITE treatment, so their coverage + closing policy differ:
    #
    #  * RETURN plane: a hole-riddled GND pour. Use 'any' coverage (a coarse cell
    #    is copper if ANY fine cell is -> fills sub-pitch antipads/slots) and an
    #    AGGRESSIVE pitch-scaled closing. A fixed 1-iteration closing bridges only
    #    2*pitch, so at a FINE pitch the ~BRIDGE_GAP_MM clearance slots stop being
    #    sub-pitch and SEVER the plane -- largest_component then keeps a fragment and
    #    the return current is pinched, inflating L ~3x (seen at FC 0.15mm: 31% of the
    #    plane dropped). Scaling iters keeps the plane whole at every pitch.
    #
    #  * FORWARD net: a SOLID pour the user points at (stays a single component even
    #    with NO bridging). Use 'fraction' coverage (truer widths) and only a light
    #    FIXED 1-iteration de-speckle. The aggressive scaled closing that the return
    #    needs would instead FILL real via-clearance notches in the forward pour,
    #    widening a genuine current-crowding neck and UNDER-estimating L at coarse
    #    pitch (BT: coarse meshes read ~2.87 nH by dilating over a notch that the fine
    #    meshes resolve as ~3.15 nH). 'fraction' + light closing preserves the notch.
    ret_bridge_iters = max(1, math.ceil(BRIDGE_GAP_MM / (2.0 * mesh_pitch)))

    def _to_mesh(fine, label, coverage, bridge_iters):
        resampled = resample(fine, mesh_pitch, coverage=coverage)
        closed = bridge_gaps(resampled, iters=bridge_iters) if bridge_iters > 0 else resampled
        coarse = largest_component(closed)
        ncomp = len(list_nets(resampled, min_cells=1))
        if verbose and ncomp > 1:
            print(f"    {label}: coarse mesh had {ncomp} fragments -> closed "
                  f"({bridge_iters} iter, {coverage}) + kept largest "
                  f"({int(coarse.mask.sum())} cells)")
        # Guard: if the kept component is much smaller than the resampled copper,
        # the plane was SEVERED (not just de-speckled) -> the loop geometry is wrong.
        resampled_cells = int(resampled.mask.sum())
        kept = int(coarse.mask.sum())
        if resampled_cells and kept / resampled_cells < SEVERED_PLANE_FRAC:
            print(f"    WARNING: {label} mesh @ {mesh_pitch}mm kept only "
                  f"{100*kept/resampled_cells:.0f}% of the resampled copper -- the "
                  f"plane likely severed at clearance slots (bridge_iters={bridge_iters}). "
                  f"The result at this pitch is a MESHING ARTIFACT; raise BRIDGE_GAP_MM "
                  f"or coarsen the pitch.")
        return coarse

    fwd_net = _to_mesh(fwd_fine, "forward", coverage="fraction", bridge_iters=1)
    ret_net = _to_mesh(ret_fine, "return", coverage="any", bridge_iters=ret_bridge_iters)
    if verbose:
        print(f"    forward net area = {fwd_fine.area_mm2():.2f} mm^2  "
              f"-> mesh {int(fwd_net.mask.sum())} cells @ {mesh_pitch} mm")
        print(f"    return  net area = {ret_fine.area_mm2():.2f} mm^2  "
              f"-> mesh {int(ret_net.mask.sum())} cells @ {mesh_pitch} mm")

    # z placement: bottom copper plane at 0, top copper plane at dielectric+cu.
    forward = fh.Conductor(mask=fwd_net, z=h_di + t_cu, thickness=t_cu, tag="f")
    ret = fh.Conductor(mask=ret_net, z=0.0, thickness=t_cu, tag="r")
    return Model(forward, ret, fwd_fine, ret_fine, mesh_pitch, iso_pitch, t_cu, h_di)


def analytic_bound(cfg, model, shorts=None, vias=None):
    """
    Closed-form microstrip sanity bound for the configured loop (see README).
    Loop length is port -> closure (where the loop turns around), NOT the small
    A-B port gap. Effective width ~ forward area / loop length as a mean width.
    Returns {"L": henries, "loop_len_mm": ..., "eff_w_mm": ...}. Shared by the
    single-run CLI and sweep_inductance so both report the identical number.
    """
    ax, ay = cfg["terminal_a"]
    if shorts:
        cx, cy = shorts[0]
    elif vias:
        cx, cy = vias[0].x, vias[0].y
    else:
        cx, cy = cfg["terminal_b"]
    mesh_pitch = model.mesh_pitch
    loop_len = math.hypot(cx - ax, cy - ay)
    area = model.fwd_fine.area_mm2()
    eff_w = (area / loop_len) if loop_len > mesh_pitch else math.sqrt(max(area, 1.0))
    L_micro = analytic.microstrip_loop_inductance(max(loop_len, mesh_pitch),
                                                  max(eff_w, mesh_pitch),
                                                  model.h_di + model.t_cu)
    return {"L": L_micro, "loop_len_mm": loop_len, "eff_w_mm": eff_w}


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

    # analytic sanity bound (shared helper -- see analytic_bound) ----------------
    bound = analytic_bound(cfg, model, shorts=shorts, vias=vias)
    L_micro, loop_len, eff_w = bound["L"], bound["loop_len_mm"], bound["eff_w_mm"]
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
