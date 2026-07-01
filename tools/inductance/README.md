# Gerber → Parasitic Loop-Inductance Estimator

Estimate the **parasitic loop inductance between two nodes** of this PCB directly
from the fabrication Gerbers, swept over frequency, using
[FastHenry](https://www.fastfieldsolvers.com/) as the field solver.

Motivation: the recurring battery-boost (TPS61288) deaths on this board
(`docs/boost-bringup-debug.md`) are suspected to involve an inductive overshoot
ringing past the 20 V SW/VOUT abs-max. The ring frequency and overshoot energy
depend on the **VBUS / boost-output ↔ ground loop inductance** — this tool puts a
number on it instead of a guess.

> **Scope / write-confinement:** everything this tool writes goes under
> `tools/inductance/` (the `out/` subfolder). It only *reads* the Gerbers in
> `references/PCB Manufacturing Files/`.

---

## What it computes

True **loop inductance**: a forward net (e.g. a boost-output pour) plus an
explicit **return** (the ground pour on the other layer), with the loop closed at
the load. `L(f) = Im(Z_port(f)) / (2πf)`, swept DC→MHz so the skin/proximity
drop-off is visible. It is **not** a full-board 3D extractor — it solves one
user-chosen loop at a time.

## Pipeline

```
copper Gerbers + drill
   └─ gerber.py        self-contained RS-274X + Excellon parser → polygons/holes
   └─ geometry.py      rasterise to a copper mask; flood-fill the net you point at
                       (fine pitch to isolate nets; resample coarser to mesh)
   └─ fasthenry.py     uniform-mesh PEEC deck (nodes+segments), port + closure,
                       run fasthenry, parse Zc.mat → L(f)
   └─ analytic.py      closed-form microstrip bound as an independent sanity check
   └─ gerber_inductance.py   CLI that ties it together + plots L(f)
```

## Install

```sh
# Python deps. This machine's MSYS2 UCRT64 python has numpy but NOT matplotlib
# (and no pip). numpy is all the core needs; matplotlib is optional (plots/PNG):
#   /c/msys64/usr/bin/pacman.exe -S mingw-w64-ucrt-x86_64-python-matplotlib
# On a normal Python install:  python -m pip install -r requirements.txt
```

**FastHenry (the solver).** Two supported flavours, auto-detected by `find_solver()`:

1. **FastFieldSolvers FastHenry2 (Windows)** — this ships only a GUI exe, but it
   is also a **COM automation server** (ProgID `FastHenry2.Document`). The tool
   drives it **headless** via `run_fasthenry_com.ps1` (PowerShell bridge), reading
   back `GetFrequencies()` / `GetInductance()` as L(f) directly. Just install it;
   the COM server is found automatically (no PATH setup). This is what's installed
   on this machine and is the validated path.
2. **Command-line `fasthenry`** (classic MIT build) — if a `fasthenry` binary is
   on PATH / `$FASTHENRY` / `--fasthenry PATH`, the tool runs it and parses `Zc.mat`.

The parser/mesher/analytic stages and `--dry-run` work **without** any solver;
only the final solve needs one.

## Workflow

**1. Discover net coordinates.** Gerbers carry no net names, so you point at a net
by coordinate. List the biggest nets on a layer (and optionally dump a PNG map):

```sh
python inspect_board.py "../../references/PCB Manufacturing Files/copper_top.gbr" \
        --pitch 0.15 --png out/top_map.png
python inspect_board.py "../../references/PCB Manufacturing Files/copper_bottom.gbr" \
        --pitch 0.15
```

Read the forward net's centroid (e.g. the boost-output pour) and the ground
pour's centroid off the table / PNG.

**2. Fill in a config** (copy `config.example.json`): the forward/return net
points, the two port terminals, the loop closure, the stackup, and the frequency
sweep. See the field-by-field notes inside `config.example.json`.

**3. Run.**

```sh
python gerber_inductance.py config.json                # full solve (needs FastHenry)
python gerber_inductance.py config.json --dry-run      # build deck + bound only
```

Outputs (in `out/`): `loop.inp` (the FastHenry deck), `inductance_vs_freq.png`,
and a printed `freq / R / L` table.

## Key modelling choices (and why)

- **Two pitches.** Distinct nets only separate if the grid pitch is **smaller than
  the copper clearance** (~0.15 mm here) — otherwise neighbouring nets merge into
  one blob (the tool warns when a net covers >70 % of its layer). But a fine grid
  over a whole pour makes far too many FastHenry segments. So the net is *isolated*
  on a fine grid (`isolation_pitch_mm`) and then *resampled* onto a coarser
  `mesh_pitch_mm` for the solve.
- **Return-plane cropping.** Return current concentrates under/near the forward
  path, so the ground plane is cropped to the forward net's footprint +
  `return_margin_mm`. This is both physically justified and what keeps the mesh
  tractable (an uncropped ground pour here is ~11000 mm² → ~60 k segments).
- **Loop closure.** A `short` closure (`.equiv`) ties forward↔return through an
  ideal node merge at the **load** end — correct for a power→load→ground loop
  (forward and return are *different* nets, never shorted by copper). Use a `via`
  closure only when forward and return are the *same* net stitched across layers.
- **Skin effect.** FastHenry filament counts (`nwinc`/`nhinc`) are set from the
  copper skin depth at the top sweep frequency, capped by `max_filaments`.
- **Sanity bound.** The DC asymptote of the swept result should land within a small
  factor of the printed microstrip bound. A wild mismatch means a bad port/closure
  placement or a merged net — fix that before trusting the number.

## Performance (read before a fine run)

FastHenry solve time grows **~quadratically with segment count** and linearly
with the number of frequency points. Measured on this machine (FastHenry2 COM):
**~1,600–1,900 segments × 5–9 freqs ≈ 6–15 minutes.** The return ground plane
dominates the segment count, so `return_margin_mm` and `mesh_pitch_mm` are your
main speed levers.

- **Preview tier** (the shipped `config.example.json`): `mesh_pitch_mm ≈ 2.0`,
  `return_margin_mm ≈ 3.0`, `freq.ndec = 1` → a few minutes.
- **Production tier** (thesis number): `mesh_pitch_mm ≈ 0.6–0.8`, `ndec = 2` →
  much slower (tens of minutes to hours); run it in the background.
- **Convergence check:** run two pitches (e.g. 2.0 then 1.2). If L barely moves,
  the coarse mesh is already converged and you can trust the fast number.

The CLI prints an estimated solve time after building the deck.

## Troubleshooting

- **"FastHenry returned 0 frequency points"** — most often a **space in the path**.
  FastHenry2's COM `Run()` silently fails (returns success, produces nothing) when
  the deck path contains a space, and this repo lives under `C:\Life Ops\...`. The
  bridge works around it by passing the Windows **8.3 short path** to `Run()`. If
  8.3 name generation is disabled on the volume the bridge raises a clear error —
  enable it (`fsutil 8dot3name set 0`) or move the project to a space-free path.
  Other causes: a stale/wedged FastHenry2 process (the bridge kills these and the
  Python side retries in fresh processes), or too large a mesh — coarsen it.
- **Empty / open-circuit result** — the forward and return nets aren't joined.
  Check `[3] loop closure` reported ≥1 short/via, and that the closure point lands
  on (or near) copper present on both layers.
- **A net covers >70 % of its layer (warning)** — `isolation_pitch_mm` is coarser
  than the copper clearance and distinct nets merged; lower it.
- **Solve is glacial** — see Performance above; the segment count is in the
  `[4]` line.

## Assumptions you must supply / verify

- `stackup.copper_thickness_mm` (1 oz = 0.035 mm) and
  `stackup.dielectric_thickness_mm` (the core thickness between top and bottom
  copper) — **`TODO(calibrate)`: confirm the dielectric from the fab stackup.**
  Loop L on a 2-layer board is roughly proportional to this height.
- The board is **2-layer** (top + bottom copper). Multilayer is out of scope.
- Aperture macros are bounded by a circle and arcs are linearised — irrelevant for
  the wide pours that dominate loop inductance, but noted.

## Validate before trusting

```sh
python selftest.py
```

Checks the parser on the real board, net selection, deck generation on a synthetic
microstrip, and the analytic math. If a `fasthenry` binary is present it also
solves the synthetic microstrip and checks the result is physical. For a hard
validation, build a known microstrip geometry and confirm the solved DC L matches
the closed-form microstrip value within a few percent before believing the board
numbers.

## Files

| file | role |
|------|------|
| `gerber.py` | RS-274X + Excellon parser (no external deps) |
| `geometry.py` | rasterise, net flood-fill, resample, crop, list nets |
| `fasthenry.py` | mesh → FastHenry deck, run, parse `Zc.mat` → L(f) |
| `analytic.py` | microstrip / parallel-plate / bar closed-form bounds |
| `gerber_inductance.py` | CLI entry point (`build_model(cfg)` builds the shared mesh) |
| `inspect_board.py` | list nets + optional PNG map to find coordinates |
| `export_mesh.py` | export the meshed conductors as STL solids for CAD |
| `stl_export.py` | binary-STL writer + voxel/marker geometry |
| `selftest.py` | dependency-light test suite |
| `config.example.json` | annotated config template |

## Visualizing / measuring the mesh (STL export)

To inspect the exact geometry FastHenry solved — the forward pour and the return
plane at their true z-separation — export it as STL and open it in CAD:

```sh
python export_mesh.py config.json --markers          # coarse mesh (as solved) + port/closure cubes
python export_mesh.py config.json --fine             # also the isolation-pitch TRUE copper
python export_mesh.py config.json --z-scale 20       # exaggerate z to SEE the thin copper (distorts measurement)
```

Writes `out/<config>_forward.stl` and `out/<config>_return.stl` as separate solids
(so CAD keeps VOUT vs GND distinct). Each mesh cell is a voxel box, so the
discretization is visible; vertices are in **mm**. The two conductors' inner faces
are exactly `dielectric_thickness_mm` apart (the printed summary reports the gap),
so you can measure the dielectric spacing, pour extents, and loop length directly.
`build_model(cfg)` in `gerber_inductance.py` builds the identical geometry the
solver uses, so the STL is a faithful picture of what was solved.
