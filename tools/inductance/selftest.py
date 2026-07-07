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


def test_sweep_runlist():
    print("\n[sweep run-list construction]")
    import sweep_inductance as si
    sweep = {"mesh_sizes_mm": [0.5, 0.3, 0.2], "designated_mesh_mm": 0.3,
             "frequencies_hz": [1, 5e5, 1e6], "designated_frequency_hz": 5e5}
    runs = si.build_run_list(sweep)
    check("no cross-product: len == meshes + freqs - 1", len(runs) == 5, str(runs))
    check("designated point appears exactly once",
          runs.count((0.3, 5e5)) == 1, str(runs))
    check("convergence axis @ designated freq",
          all((m, 5e5) in runs for m in (0.5, 0.3, 0.2)))
    check("frequency axis @ designated mesh",
          all((0.3, f) in runs for f in (1, 5e5, 1e6)))
    only_m = si.build_run_list(sweep, only="mesh")
    only_f = si.build_run_list(sweep, only="freq")
    check("--only mesh keeps 3 points", len(only_m) == 3, str(only_m))
    check("--only freq keeps 3 points", len(only_f) == 3, str(only_f))
    single = si.build_run_list({"mesh_sizes_mm": [0.4], "designated_mesh_mm": 0.4,
                                "frequencies_hz": [5e5], "designated_frequency_hz": 5e5})
    check("single-entry sets -> exactly one run", single == [(0.4, 5e5)], str(single))
    try:
        si.build_run_list({"mesh_sizes_mm": [0.5], "designated_mesh_mm": 0.3,
                           "frequencies_hz": [5e5], "designated_frequency_hz": 5e5})
        check("designated mesh must be in the set", False)
    except ValueError:
        check("designated mesh must be in the set", True)


def test_results_store():
    print("\n[results store: idempotent skip / upsert]")
    import sweep_inductance as si
    with tempfile.TemporaryDirectory() as td:
        path = si.store_path(td, "cfg")
        check("empty store loads as []", si.load_store(path) == [])
        recs = []
        si.upsert_record(recs, {"mesh_pitch_mm": 0.3, "freq_hz": 5e5, "L_H": 1e-9})
        si.upsert_record(recs, {"mesh_pitch_mm": 0.2, "freq_hz": 5e5, "L_H": 2e-9})
        si.save_store(path, recs)
        back = si.load_store(path)
        check("round-trip preserves records", len(back) == 2 and
              back[0]["L_H"] == 1e-9)
        check("find_record hits", si.find_record(back, 0.3, 5e5) is not None)
        check("find_record misses", si.find_record(back, 0.15, 5e5) is None)
        si.upsert_record(back, {"mesh_pitch_mm": 0.3, "freq_hz": 5e5, "L_H": 9e-9})
        check("upsert replaces, not appends", len(back) == 2 and
              si.find_record(back, 0.3, 5e5)["L_H"] == 9e-9)
    check("timeout floor is 2h for small decks", si.timeout_for(2000, None) == 7200)
    check("timeout scales for large decks",
          si.timeout_for(48000, None) > 7200, str(si.timeout_for(48000, None)))
    check("timeout override wins", si.timeout_for(48000, 60) == 60)


def test_bridge_scaling():
    print("\n[pitch-scaled bridge_gaps keeps a slotted plane connected]")
    import math as _m
    from geometry import resample, bridge_gaps, largest_component
    from gerber_inductance import BRIDGE_GAP_MM
    # Synthetic GND plane 12x12mm with three 0.4mm-wide slots (like bottom-trace
    # clearances) that would sever the plane if not bridged. Fine grid @ 0.05mm.
    fine_pitch = 0.05
    n = int(12.0 / fine_pitch)
    m = np.ones((n, n), dtype=bool)
    for cx in (3.0, 6.0, 9.0):                    # vertical slots, 0.4mm wide, not full height
        i0 = int((cx - 0.2) / fine_pitch); i1 = int((cx + 0.2) / fine_pitch)
        m[int(1.0/fine_pitch):int(11.0/fine_pitch), i0:i1] = False
    plane = CopperMask(mask=m, x0=0.0, y0=0.0, pitch=fine_pitch)
    full = plane.area_mm2()
    for pitch in (0.2, 0.15, 0.10):
        iters = max(1, _m.ceil(BRIDGE_GAP_MM / (2.0 * pitch)))
        kept = largest_component(bridge_gaps(resample(plane, pitch), iters=iters))
        frac = kept.area_mm2() / full
        check(f"plane stays whole @ {pitch}mm (iters={iters}, frac={frac:.2f})",
              frac >= 0.90, f"kept {frac:.2f}")


def test_forward_notch_preserved():
    print("\n[forward 'fraction'+light closing preserves a notch the return 'any'+scaled fills]")
    from geometry import resample, bridge_gaps, largest_component
    from gerber_inductance import BRIDGE_GAP_MM
    import math as _m
    # Synthetic SOLID pour 10x10mm with a real notch cut into one edge (like a
    # via-clearance): 1.0mm tall, 2.0mm deep, centred. The forward policy should
    # preserve MUCH more of it than the aggressive return policy at coarse pitch.
    fine_pitch = 0.05
    n = int(10.0 / fine_pitch)
    m = np.ones((n, n), dtype=bool)
    ny0, ny1 = int(4.5 / fine_pitch), int(5.5 / fine_pitch)     # 1.0mm tall
    nx1 = int(2.0 / fine_pitch)                                 # 2.0mm deep
    m[ny0:ny1, 0:nx1] = False
    pour = CopperMask(mask=m, x0=0.0, y0=0.0, pitch=fine_pitch)

    def notch_fill(cm):
        # fraction of the notch bounding box (x<2, 4.5<y<5.5) that is copper
        js = [j for j in range(cm.ny) if 4.5 <= cm.y0 + (j + 0.5) * cm.pitch <= 5.5]
        is_ = [i for i in range(cm.nx) if cm.x0 + (i + 0.5) * cm.pitch <= 2.0]
        if not js or not is_:
            return 1.0
        sub = cm.mask[np.ix_(js, is_)]
        return float(sub.mean())

    fills = {}
    for pitch in (0.2, 0.15):
        fwd = largest_component(bridge_gaps(resample(pour, pitch, coverage="fraction"), iters=1))
        it = max(1, _m.ceil(BRIDGE_GAP_MM / (2.0 * pitch)))
        ret = largest_component(bridge_gaps(resample(pour, pitch, coverage="any"), iters=it))
        fills[pitch] = (notch_fill(fwd), notch_fill(ret))
        ff, rf = fills[pitch]
        # forward must never be MORE filled than return (holds at every pitch)
        check(f"forward keeps notch >= as open as return @ {pitch}mm "
              f"(fwd={ff:.2f} <= ret={rf:.2f})", ff <= rf + 1e-9, f"fwd={ff:.2f} ret={rf:.2f}")
    # the fill-in artifact bites hardest at COARSE pitch: there the return policy fills
    # a notch (fill ~1.0) that the forward policy preserves (fill well below it).
    ff, rf = fills[0.2]
    check(f"return FILLS a notch the forward PRESERVES @ 0.2mm (gap={rf - ff:.2f})",
          rf - ff > 0.3, f"fwd={ff:.2f} ret={rf:.2f}")


def test_model_cache():
    print("\n[model cache: save -> load round-trip]")
    import model_cache as mc
    from gerber_inductance import Model
    pitch, t_cu, h_di = 0.5, 0.035, 0.2
    fwd = _rect_mask(0.0, 4.0, 10.0, 2.0, pitch)
    ret = _rect_mask(0.0, 0.0, 10.0, 6.0, pitch)
    fwd_fine = _rect_mask(0.0, 4.0, 10.0, 2.0, 0.1)
    ret_fine = _rect_mask(0.0, 0.0, 10.0, 6.0, 0.1)
    forward = fh.Conductor(mask=fwd, z=h_di + t_cu, thickness=t_cu, tag="f")
    retc = fh.Conductor(mask=ret, z=0.0, thickness=t_cu, tag="r")
    model = Model(forward, retc, fwd_fine, ret_fine, pitch, 0.1, t_cu, h_di)
    with tempfile.TemporaryDirectory() as td:
        path = mc.cache_path(td, "synth", pitch)
        mc.save_model(model, path, fingerprint="abc123")
        back, fp = mc.load_model(path)
        check("fingerprint round-trips", fp == "abc123", fp)
        check("mesh pitch round-trips", back.mesh_pitch == pitch)
        check("stackup round-trips", back.t_cu == t_cu and back.h_di == h_di)
        check("coarse masks identical",
              np.array_equal(back.forward.mask.mask, fwd.mask) and
              np.array_equal(back.ret.mask.mask, ret.mask))
        check("fine masks identical",
              np.array_equal(back.fwd_fine.mask, fwd_fine.mask))
        check("conductor z placement rebuilt",
              back.forward.z == h_di + t_cu and back.ret.z == 0.0)
        check("grid origins preserved",
              back.forward.mask.x0 == 0.0 and back.forward.mask.y0 == 4.0)


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
    test_sweep_runlist()
    test_results_store()
    test_bridge_scaling()
    test_forward_notch_preserved()
    test_model_cache()
    test_end_to_end(deck)
    print(f"\n==== {PASS} passed, {FAIL} failed ====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
