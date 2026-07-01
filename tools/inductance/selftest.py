#!/usr/bin/env python3
"""
Self-tests that run WITHOUT a FastHenry binary and without external deps beyond
numpy. They exercise:
  * the Gerber/Excellon parser on the real board files (sanity of geometry),
  * net selection (connected-component pick),
  * FastHenry deck generation on a synthetic microstrip,
  * the analytic bound math.

If a `fasthenry` binary is discoverable, an end-to-end solve of the synthetic
microstrip is also run and checked against the closed-form bound.

Run:  /c/msys64/ucrt64/bin/python.exe selftest.py [path-to-gerber-dir]
"""

from __future__ import annotations

import math
import os
import sys
import tempfile

import numpy as np

import analytic
import fasthenry as fh
from gerber import parse_gerber, parse_excellon
from geometry import CopperMask, rasterize, select_net

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}   {detail}")


def test_parser(gdir):
    print("\n[parser on real board]")
    top = parse_gerber(os.path.join(gdir, "copper_top.gbr"))
    bot = parse_gerber(os.path.join(gdir, "copper_bottom.gbr"))
    bx = top.bbox()
    w, h = bx[2] - bx[0], bx[3] - bx[1]
    check("top copper within a ~131x98mm board", 100 < w < 140 and 80 < h < 110,
          f"w={w:.1f} h={h:.1f}")
    check("top has regions+traces+flashes", top.regions and top.traces and top.flashes)
    holes = parse_excellon(os.path.join(gdir, "drill_1_64.xln"))
    check("drill holes parsed", len(holes) > 100, f"n={len(holes)}")
    check("drill within board", all(0 < hh.x < 140 and 0 < hh.y < 110 for hh in holes))
    return top, bot


def test_net_selection(top):
    print("\n[net selection]")
    cm = rasterize(top, pitch=0.3)
    check("mask has copper", cm.mask.any())
    # pick the centroid of the largest region polygon as a probe point
    biggest = max(top.regions, key=lambda r: len(r.points))
    pts = np.asarray(biggest.points)
    px, py = pts[:, 0].mean(), pts[:, 1].mean()
    try:
        net = select_net(cm, px, py)
        frac = net.mask.sum() / cm.mask.sum()
        check("selected a connected sub-net", 0 < net.mask.sum() <= cm.mask.sum(),
              f"cells={int(net.mask.sum())} frac={frac:.3f}")
    except ValueError as e:
        check("selected a connected sub-net", False, str(e))


def _rect_mask(x0, y0, w, h, pitch):
    nx = int(round(w / pitch))
    ny = int(round(h / pitch))
    return CopperMask(mask=np.ones((ny, nx), dtype=bool), x0=x0, y0=y0, pitch=pitch)


def test_deck_and_bound():
    print("\n[synthetic microstrip deck + analytic bound]")
    # 20mm long, 2mm wide forward trace over a 20x10mm return plane, 0.2mm apart.
    pitch = 0.5
    length, width = 20.0, 2.0
    h_di, t_cu = 0.2, 0.035
    fwd = _rect_mask(0.0, 4.0, length, width, pitch)
    ret = _rect_mask(0.0, 0.0, length, 10.0, pitch)
    forward = fh.Conductor(mask=fwd, z=h_di + t_cu, thickness=t_cu, tag="f")
    retc = fh.Conductor(mask=ret, z=0.0, thickness=t_cu, tag="r")
    # close the loop with a via at the far end (x=19.5), port at near end (x=0.5)
    vias = [fh.Via(19.5, 5.0, 0.5)]
    text, meta = fh.build_inp(forward, retc, vias,
                              term_a=(0.5, 5.0), term_b=(0.5, 0.5),
                              fmin=1e3, fmax=1e7, ndec=1)
    check("deck has segments", meta["segments"] > 0, str(meta["segments"]))
    check("deck has a via segment", meta["via_segments"] == 1)
    check("port nodes assigned", meta["port_nodes"].get("A") and meta["port_nodes"].get("B"))
    check("deck has .external and .freq", ".external" in text and ".freq" in text)
    check("deck declares mm + copper sigma (5.8e4 S/mm)",
          ".units mm" in text and "sigma=58000" in text)

    L_micro = analytic.microstrip_loop_inductance(length, width, h_di + t_cu)
    L_pp = analytic.parallel_plate_loop_inductance(length, width, h_di + t_cu)
    # parallel-plate: mu0*L*h/w = 4pi e-7 *0.02*0.000235/0.002
    expect_pp = (4e-7 * math.pi) * 0.020 * (0.000235) / 0.002
    check("parallel-plate matches hand calc", abs(L_pp - expect_pp) / expect_pp < 1e-6,
          f"{L_pp:.3e} vs {expect_pp:.3e}")
    check("microstrip bound positive & < parallel-plate", 0 < L_micro <= L_pp,
          f"micro={L_micro*1e9:.3f}nH pp={L_pp*1e9:.3f}nH")
    check("bar partial inductance sane (~10-30nH for 20mm)",
          5e-9 < analytic.rectangular_bar_partial_inductance(length, width, t_cu) < 5e-8)
    return text


def test_end_to_end(deck_text):
    print("\n[end-to-end FastHenry solve (if solver available)]")
    mode, target = fh.find_solver(None)
    if mode is None:
        print("  SKIP  no FastHenry (CLI or COM) found -- deck generation already verified")
        return
    print(f"  using solver: {mode} -> {target}")
    with tempfile.TemporaryDirectory() as td:
        inp = os.path.join(td, "loop.inp")
        with open(inp, "w") as f:
            f.write(deck_text)
        if mode == "com":
            # per-frequency (robust) path, same as the CLI; 2 points keeps it quick
            rows = fh.run_sweep_per_freq(inp, [1e3, 1e7], td, progid=target)
        else:
            rows = fh.inductance_table(fh.parse_zc(fh.run_fasthenry(inp, target, td)))
        check("solver returned rows", len(rows) > 0)
        if not rows:
            return
        Ldc = rows[0][2]
        check("solved L is physical (0.1-100 nH)", 1e-10 < Ldc < 1e-7,
              f"L={Ldc*1e9:.3f} nH")
        # Validation: solved L must sit in the order-of-magnitude band set by the
        # closed forms for THIS geometry (20mm x 2mm over 0.235mm). The closed
        # forms are coarse (parallel-plate assumes w>>h; a 2mm/0.235mm trace is
        # only moderately wide), so the band is wide on purpose -- its job is to
        # catch an open circuit (L->0) or a merged net (L huge), not to be exact.
        L_pp = analytic.parallel_plate_loop_inductance(20.0, 2.0, 0.235)
        L_micro = analytic.microstrip_loop_inductance(20.0, 2.0, 0.235)
        lo, hi = 0.3 * L_micro, 4.0 * L_pp
        check("solved L within order-of-magnitude closed-form band",
              lo <= Ldc <= hi,
              f"L={Ldc*1e9:.3f}nH band=[{lo*1e9:.3f},{hi*1e9:.3f}]nH")
        # L should not increase with frequency (skin effect lowers it)
        if len(rows) > 1:
            check("L is non-increasing with frequency (skin effect)",
                  rows[-1][2] <= rows[0][2] * 1.02,
                  f"L(dc)={rows[0][2]*1e9:.3f} L(hf)={rows[-1][2]*1e9:.3f} nH")


def main():
    gdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "references", "PCB Manufacturing Files")
    gdir = os.path.normpath(gdir)
    print(f"gerber dir: {gdir}")
    top, _ = test_parser(gdir)
    test_net_selection(top)
    deck = test_deck_and_bound()
    test_end_to_end(deck)
    print(f"\n==== {PASS} passed, {FAIL} failed ====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
