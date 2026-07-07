#!/usr/bin/env python3
"""
sweep_inductance.py -- solve the mesh-convergence + frequency sweeps declared in
a config's `sweep` block, persisting verbose per-run records to a results store.

The sweep is deliberately NOT a cross-product. Two axes are solved:
  * convergence axis: every `mesh_sizes_mm` entry @ `designated_frequency_hz`
  * frequency axis:   every `frequencies_hz` entry @ `designated_mesh_mm`
The designated (mesh, freq) point is shared and solved once.

Results go to `out/<config-base>_results.json` (one record per (mesh, freq) with
segment counts, areas, filament counts, timing, the analytic bound, ...). The
store is append-as-you-go and idempotent: points already present are skipped, so
a multi-hour run can be interrupted and resumed by re-running the script.
Reporting is a separate step (report_results.py) reading these stores.

Parallelism (`--jobs N`): points are solved longest-deck-first in a thread pool
(each thread just waits on a PowerShell/FastHenry subprocess). Safety rules:
  * a one-shot COM instancing preflight verifies each COM client gets its OWN
    FastHenry2 process; if not, parallel is unsafe and we fall back to serial;
  * at most ONE "large" deck (>= LARGE_SEGMENTS segments) is in flight at any
    time (hard rule -- the big decks are memory-heavy);
  * every point gets its own workdir, and parallel solves never pre-kill
    FastHenry2 processes (each bridge instance cleans up only its own PID).

Usage:
    python sweep_inductance.py config.json [--outdir out] [--jobs N]
                               [--dry-run] [--force] [--only mesh|freq]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

import fasthenry as fh
import model_cache
from gerber_inductance import load_config, analytic_bound

LARGE_SEGMENTS = 20_000          # decks at/above this never run two-at-a-time
EST_S_PER_KSEG2 = 25.0           # calibrated: ~25 s x (segments/1000)^2 per point


# ----------------------------------------------------------------------------
# Run list + results store
# ----------------------------------------------------------------------------

def build_run_list(sweep: dict, only: str | None = None) -> list[tuple[float, float]]:
    """
    (mesh_mm, freq_hz) points to solve: all meshes @ designated freq, plus the
    designated mesh @ all freqs. The designated x designated point appears once.
    `only`: 'mesh' -> convergence axis only, 'freq' -> frequency axis only.
    """
    meshes = [float(m) for m in sweep["mesh_sizes_mm"]]
    freqs = [float(f) for f in sweep["frequencies_hz"]]
    m_des = float(sweep["designated_mesh_mm"])
    f_des = float(sweep["designated_frequency_hz"])
    if m_des not in meshes:
        raise ValueError(f"designated_mesh_mm {m_des} not in mesh_sizes_mm {meshes}")
    if f_des not in freqs:
        raise ValueError(f"designated_frequency_hz {f_des} not in frequencies_hz {freqs}")
    runs: list[tuple[float, float]] = []
    if only in (None, "mesh"):
        runs += [(m, f_des) for m in meshes]
    if only in (None, "freq"):
        runs += [(m_des, f) for f in freqs]
    seen, out = set(), []
    for r in runs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def store_path(outdir: str, base: str) -> str:
    return os.path.join(outdir, f"{base}_results.json")


def load_store(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_store(path: str, records: list[dict]) -> None:
    """Atomic write so a crash mid-save can't destroy hours of results."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=1)
    os.replace(tmp, path)


def _same_point(rec: dict, mesh: float, freq: float) -> bool:
    return (math.isclose(float(rec["mesh_pitch_mm"]), mesh, rel_tol=1e-9)
            and math.isclose(float(rec["freq_hz"]), freq, rel_tol=1e-9))


def find_record(records: list[dict], mesh: float, freq: float) -> dict | None:
    for rec in records:
        if _same_point(rec, mesh, freq):
            return rec
    return None


def upsert_record(records: list[dict], rec: dict) -> None:
    """Replace an existing (mesh, freq) record or append."""
    for i, old in enumerate(records):
        if _same_point(old, float(rec["mesh_pitch_mm"]), float(rec["freq_hz"])):
            records[i] = rec
            return
    records.append(rec)


def timeout_for(segments: int, override: int | None) -> int:
    """Per-point COM watchdog, scaled with deck size (a 48 k-segment deck
    legitimately solves for 4-6 h; the old fixed 2 h killed it mid-solve)."""
    if override:
        return int(override)
    est = EST_S_PER_KSEG2 * (segments / 1000.0) ** 2
    return int(max(7200, 1.5 * est))


def est_solve_s(segments: int) -> float:
    return EST_S_PER_KSEG2 * (segments / 1000.0) ** 2


# ----------------------------------------------------------------------------
# COM instancing preflight (parallel safety)
# ----------------------------------------------------------------------------

_PREFLIGHT_PS = r"""
$ErrorActionPreference = 'Stop'
$before = @(Get-Process FastHenry2 -ErrorAction SilentlyContinue).Count
$a = New-Object -ComObject FastHenry2.Document
Start-Sleep -Milliseconds 400
$b = New-Object -ComObject FastHenry2.Document
Start-Sleep -Milliseconds 400
$after = @(Get-Process FastHenry2 -ErrorAction SilentlyContinue).Count
try { [void]$a.Quit() } catch {}
try { [void]$b.Quit() } catch {}
Start-Sleep -Milliseconds 300
Get-Process FastHenry2 -ErrorAction SilentlyContinue |
    Stop-Process -Force -Confirm:$false -ErrorAction SilentlyContinue
Write-Output ($after - $before)
"""


def com_parallel_safe() -> bool:
    """
    True if each COM client gets its OWN FastHenry2 process (single-use server),
    which makes concurrent solves isolated. A shared/multi-use server would make
    parallel Run() calls trample each other -> caller must fall back to serial.
    """
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", _PREFLIGHT_PS],
                           capture_output=True, text=True, timeout=60)
        n = int(r.stdout.strip().splitlines()[-1])
        return n >= 2
    except Exception:                            # noqa: BLE001 -- any doubt -> serial
        return False


# ----------------------------------------------------------------------------
# Solving
# ----------------------------------------------------------------------------

def solve_point(deck_path: str, freq: float, workdir: str,
                mode: str, target: str,
                timeout_sec: int, kill_stale: bool) -> tuple[float, float, float]:
    """Solve ONE (deck, frequency) point; returns (freq, R_ohm, L_H)."""
    os.makedirs(workdir, exist_ok=True)
    with open(deck_path) as f:
        deck = f.read()
    single = fh._rewrite_freq(deck, freq)
    pt = os.path.join(workdir, "loop_pt.inp")
    with open(pt, "w") as f:
        f.write(single)
    if mode == "com":
        rows = fh.run_via_com(pt, workdir, progid=target,
                              timeout_sec=timeout_sec, kill_stale=kill_stale)
    else:
        rows = fh.inductance_table(fh.parse_zc(fh.run_fasthenry(pt, target, workdir)))
    if not rows:
        raise RuntimeError(f"no result for f={freq:g}")
    return rows[0]


def prepare_decks(cfg, base: str, pitches: list[float], outdir: str, verbose=True):
    """
    For each mesh pitch: cached model -> FastHenry deck + per-pitch metadata.
    Returns {pitch: {"deck": path, "meta": build_inp meta, "model": Model,
                     "bound": analytic dict, "shorts": [...], "vias": [...]}}.
    """
    deck_dir = os.path.join(outdir, "decks")
    mesh_dir = os.path.join(outdir, "meshes")
    os.makedirs(deck_dir, exist_ok=True)
    frq = cfg["freq"] if "freq" in cfg else {}
    sweep = cfg["sweep"]
    fmax_all = max([float(f) for f in sweep["frequencies_hz"]]
                   + [float(sweep["designated_frequency_hz"])])
    out = {}
    for pitch in pitches:
        if verbose:
            print(f"--- mesh pitch {pitch:g} mm ---")
        model = model_cache.get_model(cfg, pitch, mesh_dir, base, verbose=verbose)

        closure = cfg.get("closure", {"type": "short", "points": [cfg["terminal_a"]]})
        vias, shorts = [], []
        if closure.get("type", "short") == "short":
            shorts = [tuple(p) for p in closure.get("points", [cfg["terminal_a"]])]
        else:
            for v in closure.get("points", []):
                vias.append(fh.Via(float(v[0]), float(v[1]),
                                   float(v[2]) if len(v) > 2 else pitch))

        # skin_ref at the sweep's top frequency so one deck serves every point
        text, meta = fh.build_inp(
            model.forward, model.ret, vias,
            term_a=tuple(cfg["terminal_a"]), term_b=tuple(cfg["terminal_b"]),
            fmin=fmax_all, fmax=fmax_all, ndec=1,
            skin_ref_freq=float(frq.get("skin_ref_freq", fmax_all)),
            max_filaments=int(cfg.get("max_filaments", 5)),
            shorts=shorts,
        )
        deck_path = os.path.join(deck_dir, f"{base}_m{pitch:g}.inp")
        with open(deck_path, "w") as f:
            f.write(text)
        bound = analytic_bound(cfg, model, shorts=shorts, vias=vias)
        if verbose:
            print(f"    deck: {meta['segments']} segments, {meta['nodes']} nodes "
                  f"-> {os.path.basename(deck_path)}")
        out[pitch] = {"deck": deck_path, "meta": meta, "model": model,
                      "bound": bound, "shorts": shorts, "vias": vias}
    return out


def make_record(base: str, pitch: float, freq: float, row, prep: dict,
                solve_seconds: float, mode: str) -> dict:
    meta, model, bound = prep["meta"], prep["model"], prep["bound"]
    fil = meta.get("filaments", {})
    return {
        "config": base,
        "mesh_pitch_mm": pitch,
        "freq_hz": freq,
        "L_H": row[2],
        "R_ohm": None if row[1] != row[1] else row[1],       # NaN -> null
        "segments": meta["segments"],
        "nodes": meta["nodes"],
        "shorts": meta["shorts"],
        "via_segments": meta["via_segments"],
        "fwd_cells": int(model.forward.mask.mask.sum()),
        "ret_cells": int(model.ret.mask.mask.sum()),
        "fwd_area_mm2": model.fwd_fine.area_mm2(),
        "ret_area_mm2": model.ret_fine.area_mm2(),
        "skin_depth_mm": meta["skin_depth_mm"],
        "nwinc_f": fil.get("f", (None, None))[0],
        "nhinc_f": fil.get("f", (None, None))[1],
        "nwinc_r": fil.get("r", (None, None))[0],
        "nhinc_r": fil.get("r", (None, None))[1],
        "loop_len_mm": bound["loop_len_mm"],
        "eff_w_mm": bound["eff_w_mm"],
        "analytic_bound_H": bound["L"],
        "solve_seconds": solve_seconds,
        "solver_mode": mode,
        "deck": os.path.basename(prep["deck"]),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "source": "sweep_inductance",
    }


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", help="JSON config with a `sweep` block")
    ap.add_argument("--outdir", default=None, help="output dir (default ./out)")
    ap.add_argument("--fasthenry", default=None, help="path to fasthenry binary")
    ap.add_argument("--jobs", type=int, default=1,
                    help="parallel solves (default 1 = serial). COM instancing is "
                         "preflight-checked; falls back to serial if unsafe.")
    ap.add_argument("--dry-run", action="store_true",
                    help="build decks + print the solve plan, don't solve")
    ap.add_argument("--force", action="store_true",
                    help="re-solve points already in the results store")
    ap.add_argument("--only", choices=["mesh", "freq"], default=None,
                    help="solve only the convergence axis (mesh) or frequency axis")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if "sweep" not in cfg:
        print("config has no `sweep` block -- nothing to do "
              "(see config_vout_bt.json for the schema)")
        return 2
    sweep = cfg["sweep"]
    base = os.path.splitext(os.path.basename(args.config))[0]
    here = os.path.dirname(os.path.abspath(__file__))
    outdir = args.outdir or cfg.get("outdir") or os.path.join(here, "out")
    os.makedirs(outdir, exist_ok=True)

    runs = build_run_list(sweep, only=args.only)
    spath = store_path(outdir, base)
    records = load_store(spath)
    todo = [r for r in runs if args.force or find_record(records, *r) is None]
    done = [r for r in runs if r not in todo]

    print(f"[sweep] {base}: {len(runs)} point(s) "
          f"({len(done)} already in store, {len(todo)} to solve)"
          + (f"  [--only {args.only}]" if args.only else ""))
    if not todo:
        print(f"Nothing to solve. Store: {spath}")
        return 0

    pitches = sorted({m for (m, _) in todo}, reverse=True)
    prep = prepare_decks(cfg, base, pitches, outdir)

    override = sweep.get("solver_timeout_sec")
    # work items, longest-deck-first so the monster starts immediately
    items = sorted(todo, key=lambda r: prep[r[0]]["meta"]["segments"], reverse=True)
    print("\nsolve plan (longest first):")
    total_est = 0.0
    for (m, f) in items:
        seg = prep[m]["meta"]["segments"]
        e = est_solve_s(seg)
        total_est += e
        print(f"    m={m:<5g} f={f:<8g}  {seg:>6d} seg  est ~{e/60:6.1f} min  "
              f"timeout {timeout_for(seg, override)/3600:.1f} h"
              f"{'   [LARGE]' if seg >= LARGE_SEGMENTS else ''}")
    print(f"    total est ~{total_est/3600:.1f} h serial (upper bound; the estimate "
          f"has run ~2-4x high on this machine)")

    if args.dry_run:
        print("\n--dry-run: not solving.")
        return 0

    mode, target = fh.find_solver(args.fasthenry or cfg.get("fasthenry_path"))
    if mode is None:
        print("No FastHenry solver found (COM server or CLI binary). Decks are "
              "built under out/decks/.")
        return 1

    jobs = max(1, args.jobs)
    if jobs > 1 and mode == "com":
        print(f"\n[preflight] verifying FastHenry2 COM multi-instance safety ...")
        if com_parallel_safe():
            print(f"    OK: one process per COM client -> running {jobs} job(s)")
        else:
            print("    NOT SAFE (shared COM server) -> falling back to serial")
            jobs = 1

    lock = threading.Lock()
    large_sem = threading.Semaphore(1)           # hard rule: one LARGE deck at a time
    n_done = [0]

    def work(point):
        m, f = point
        seg = prep[m]["meta"]["segments"]
        wd = os.path.join(outdir, f"solve_{base}", f"m{m:g}_f{f:g}")
        is_large = seg >= LARGE_SEGMENTS
        if is_large:
            large_sem.acquire()
        try:
            t0 = time.time()
            row = solve_point(prep[m]["deck"], f, wd, mode, target,
                              timeout_sec=timeout_for(seg, override),
                              kill_stale=(jobs == 1))
            dt = time.time() - t0
        finally:
            if is_large:
                large_sem.release()
        rec = make_record(base, m, f, row, prep[m], dt, mode)
        with lock:
            upsert_record(records, rec)
            save_store(spath, records)
            n_done[0] += 1
            print(f"    [{n_done[0]}/{len(items)}] m={m:g} f={f:g} -> "
                  f"L={row[2]*1e9:.4f} nH  R={row[1]*1e3:.4f} mOhm  ({dt:.0f}s)",
                  flush=True)
        return rec

    print(f"\n[solve] {len(items)} point(s), jobs={jobs} ...")
    failures = []
    if jobs == 1:
        for p in items:
            try:
                work(p)
            except Exception as e:               # noqa: BLE001 -- keep solving the rest
                failures.append((p, str(e)))
                print(f"    FAILED m={p[0]:g} f={p[1]:g}: {e}", flush=True)
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            futs = {ex.submit(work, p): p for p in items}
            for fut in futs:
                try:
                    fut.result()
                except Exception as e:           # noqa: BLE001
                    failures.append((futs[fut], str(e)))
                    print(f"    FAILED m={futs[fut][0]:g} f={futs[fut][1]:g}: {e}",
                          flush=True)

    print(f"\n[done] {len(items) - len(failures)}/{len(items)} solved "
          f"-> {spath}")
    if failures:
        print("failures (re-run the script to retry just these):")
        for (p, msg) in failures:
            print(f"    m={p[0]:g} f={p[1]:g}: {msg.splitlines()[0] if msg else ''}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
