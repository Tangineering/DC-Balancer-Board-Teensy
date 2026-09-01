#!/usr/bin/env python3
"""Markov transition probability matrix (TPM) generator for binned power demand.

Python reimplementation of ``references/EMS/TPM_generator.m`` (the PhD
student's MATLAB script).  Builds a 50x50 TPM over normalized, binned power
demand from the ten Simulink stochastic drive-cycle files in
``references/EMS/Pdem_cycles/``.

Interpreter: requires numpy + scipy.  Use the miniforge interpreter --

    C:/Users/ricky/miniforge3/python.exe tools/tpm_generator.py --validate

``.venv_hil`` is stdlib-only and CANNOT run this tool.

Validation gate
---------------
At ``--dt 1.0`` the generated TPM is bit-identical to
``references/EMS/TPM_scaled.mat`` (50x50 float64, 497 nonzeros).  The energy
scaling factor sE cancels under the global min/max normalization, so
``TPM_fullsize.mat`` is the same matrix; either may be used as the reference.
``--validate`` runs that comparison.  ``--dt`` may not be combined with
``--validate`` (the gate is defined at dt = 1.0 only).

Exit codes
----------
    0  success (generate completed, or --validate PASSed)
    1  --validate FAILed (TPM differs from the reference)
    2  usage / refusal error (bad dt, refused output path, existing output
       without --force, missing reference)

Library API (importable without running the CLI, and without touching the
private scipy MAT reader unless a cycle file is actually decoded)
------------------------------------------------------------------
    load_pdem_cycle(path) -> (t, p_dem_scaled)
    build_tpm(series_list, dt, n_bins=50, exclude_boundary=False,
              truncate_native=False, smoothing_alpha=0.0,
              empty_row_policy="zero") -> (tpm, counts, meta)
    rescale_gamma(gamma_base, dt, dt_base=1.0) -> float

Unitless contract (for the SDP consumer)
----------------------------------------
The TPM is over NORMALIZED demand: bins partition [0, 1] where 0/1 are the
min/max of the concatenated (scaled) demand.  The matrix is invariant to any
affine rescaling of the demand axis (sE cancels -- the gate proves it), so
the SDP controller owns the energy scaling: it maps a measured P_dem onto
[0, 1] with whatever affine map matches its operating range (the provenance
records ``p_dem_scaled_min``/``max`` used here) and clamps out-of-range
values to the end bins.  Moving to a different energy scale changes the SDP's
lookup map, never this matrix.

HIL deviations (opt-in; defaults preserve MATLAB parity and the gate)
---------------------------------------------------------------------
    --n-bins N            fewer bins (10 cycles are thin for 50x50)
    --smooth-alpha A      Laplace add-A smoothing of the counts
    --empty-row-policy    zero (parity) | self | uniform for zero-count rows
    --drop-duplicates     drop later cycles whose decoded signal is
                          bit-identical to an earlier one (V2 == V1)
    --truncate-native     resample each cycle only over its native time span
                          instead of spline-extrapolating to 1000 s (V3 ends
                          at 600 s)
    --exclude-boundary    drop cross-file boundary transitions
    --hil                 preset: all of the above with n_bins 25,
                          empty-row-policy self (explicit flags win)
None of these may be combined with --validate.

Timescale guidance (SDP decision rate + discount factor)
--------------------------------------------------------
A TPM at fine dt approaches the identity (at dt = 0.02 s the diagonal holds
>99% of the mass) and carries almost no predictive information; the demand
process has ~1 s dynamics.  Run the SDP decision layer at ~0.5-1 s and let
the 50 Hz commander zero-order-hold its output.  When solving at any step
other than the one a discount factor was tuned at, rescale it:
``gamma_eff = gamma_base ** (dt / dt_base)`` (``rescale_gamma``); e.g. the
student's 0.95 at 1 s becomes 0.95**0.02 ~= 0.99897 at 20 ms -- reusing 0.95
verbatim at 20 ms would silently shrink the planning horizon from ~20 s to
~0.4 s.  Generation prints the diagonal mass and warns below dt = 0.1 s.

MATLAB semantics replicated
---------------------------
* ``out.simout`` Time/Data, Data scaled by sE = sm * sl**2.
* ``interp1(..., 'spline', 'extrap')`` == not-a-knot cubic spline with
  extrapolation == ``scipy.interpolate.CubicSpline(bc_type='not-a-knot',
  extrapolate=True)``.  Cycle V3's native data ends at 600 s, so the
  extrapolation branch is genuinely exercised out to 1000 s -- see the
  ``extrapolation_summary`` block in the provenance sidecar.
* Time grid ``0:dt:1000`` with MATLAB colon semantics: n = floor(1000/dt) + 1
  points, i.e. the endpoint is included only when dt divides 1000.
* File order V1..V10 (MATLAB ``num2str(i)``), NOT lexicographic.
* Global normalization (x - min) / (max - min) over the concatenation.
* ``discretize(x, linspace(0,1,51))``: 0-based bin i covers
  [edges[i], edges[i+1]) except the last bin (i = 49), which is closed
  [edges[49], edges[50]]; the global normalized max (1.0) therefore lands in
  0-based bin 49 (MATLAB's 1-based bin 50).
* Transitions counted over the whole concatenated index vector, INCLUDING the
  nine cross-file boundary transitions (the MATLAB concatenates first, then
  counts).  ``--exclude-boundary`` drops them; that is a DEVIATION.
* Row-normalize; all-zero rows stay all-zero (MATLAB NaN -> 0).

Memory note: the MCOS decode holds a ~52 MB function workspace plus the
decoded metadata per file; peak transient is roughly 230 MB.  Files are
decoded and released one at a time.  Reducing that peak was reviewed and
deliberately not pursued.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import scipy
from scipy.interpolate import CubicSpline
from scipy.io import loadmat, savemat

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
EMS_DIR = os.path.join(REPO_ROOT, "references", "EMS")
CYCLE_DIR = os.path.join(EMS_DIR, "Pdem_cycles")
DEFAULT_OUT_DIR = os.path.join(EMS_DIR, "generated")
REFERENCE_TPM = os.path.join(EMS_DIR, "TPM_scaled.mat")

NUM_DATASETS = 10
T_END = 1000.0          # time_common = 0:dt:1000  (TPM_generator.m:6)
N_BINS_DEFAULT = 50     # linspace(0,1,51) -> 50 bins (TPM_generator.m:38,42)
N_BINS_HIL = 25         # --hil preset: 10 cycles are thin for 50x50
GAMMA_DT_BASE_S = 1.0   # the step the student's gamma = 0.95 was tuned at
DT_GUIDANCE_S = 0.1     # below this, generation warns (near-identity TPM)

# Scale-car energy scaling factors (TPM_generator.m:8-15).  sE cancels under
# the min/max normalization but is kept so intermediate P_dem is scale-car
# level.
M_ORIGINAL_KG = 2242.0
VMAX_ORIGINAL_KPH = 130.0
M_SCALE_KG = 3.5
VMAX_SCALE_KPH = 3.0 * 3.6      # from 3 m/s
SM = M_SCALE_KG / M_ORIGINAL_KG                 # mass scaling factor
SL = VMAX_SCALE_KPH / VMAX_ORIGINAL_KPH         # length scaling factor
SE = SM * SL ** 2                               # energy scaling factor

_MIN_SIGNAL_LEN = 1000  # discriminates logged timeseries from scalar metadata

# Structural invariant of the shipped cycle set (verified on all ten files):
# the chosen simout pair's DATA vector is bit-identical to the data of the
# pair at this 0-based pair ordinal (MCOS metadata index 171 in every file),
# which is the ``P_req`` element of the logsout Dataset.  simout is the same
# signal logged a second time by a To-Workspace block.
_EXPECTED_DUP_ORDINAL = 6

# Gate provenance: last proven bit-identical against references/EMS/TPM_scaled.mat
GATE_LAST_PROVEN = "2026-08-31"

# Basenames that must never be an output target (irreplaceable, untracked).
_CYCLE_BASENAME_PREFIX = "simulink_pdem_output_stochastic_v"


# ---------------------------------------------------------------------------
# MCOS extraction
# ---------------------------------------------------------------------------
def _mat_file5_reader():
    """Lazily import the private scipy MAT v5 reader.

    Kept out of module import so ``import tpm_generator`` for ``build_tpm`` /
    ``matlab_discretize`` alone never touches a private scipy API.  Tested
    against scipy 1.18.1.
    """
    try:
        from scipy.io.matlab._mio5 import MatFile5Reader
    except ImportError as exc:  # pragma: no cover - environment guard
        raise ImportError(
            "tpm_generator requires scipy.io.matlab._mio5.MatFile5Reader "
            "(private API, tested against scipy 1.18.1; this interpreter has "
            f"scipy {scipy.__version__}). The Simulink .mat cycle files store "
            "out.simout as an opaque MCOS object that the public loadmat API "
            "cannot decode."
        ) from exc
    return MatFile5Reader


def _read_object_metadata(path: str) -> np.ndarray:
    """Recover the MCOS object metadata cell array from a Simulink .mat file.

    ``out`` is an opaque ``Simulink.SimulationOutput``; ``loadmat`` returns
    only a stub plus a ``__function_workspace__`` byte blob (~52 MB) that is
    itself a headerless MAT v5 stream.  A synthetic 128-byte header is
    prepended so ``MatFile5Reader`` will parse it.  The two-byte endian
    marker is mirrored from the workspace's own mini-header rather than
    hardcoded.
    """
    MatFile5Reader = _mat_file5_reader()
    d = loadmat(path)
    if "__function_workspace__" not in d:
        raise ValueError(f"{path}: no __function_workspace__ (not a Simulink MCOS .mat?)")
    fw = d["__function_workspace__"].tobytes()
    del d
    if len(fw) < 8:
        raise ValueError(f"{path}: __function_workspace__ too short ({len(fw)} bytes)")
    endian_marker = fw[2:4]                       # 'IM' (LE) or 'MI' (BE)
    if endian_marker not in (b"IM", b"MI"):
        raise ValueError(
            f"{path}: unrecognized endian marker {endian_marker!r} in the "
            "__function_workspace__ mini-header; cannot build a synthetic "
            "MAT v5 header."
        )
    fake_header = b"M" * 124 + fw[0:2] + endian_marker
    stream = io.BytesIO(fake_header + fw[8:])     # strip fw's mini-header
    del fw
    reader = MatFile5Reader(stream)
    reader.initialize_read()
    stream.seek(128)
    hdr, _ = reader.read_var_header()
    var = reader.read_var_array(hdr)
    names = getattr(getattr(var, "dtype", None), "names", None)
    if not names or "MCOS" not in names:
        raise ValueError(
            f"{path}: parsed function workspace has no 'MCOS' field "
            f"(fields: {names}); the file layout is not the expected "
            "Simulink.SimulationOutput MCOS form."
        )
    return np.ravel(var["MCOS"][0, 0][0]["_ObjectMetadata"])


def _extract_timeseries_pairs(meta: np.ndarray):
    """Yield ``(meta_index, time, data)`` for every logged timeseries.

    Structural identification (strategy (b) of the two allowed).  The object
    metadata is a flat cell array in which each logged signal contributes a
    long float64 TIME vector immediately followed by its equally long float64
    DATA vector.  A time vector is recognized by: starts at 0, non-decreasing,
    and followed by a same-length float64 vector that is NOT itself
    monotonically non-decreasing (a data signal swings).

    Signal names ARE present in the same raveled metadata as ``<U`` string
    cells (98 in V1, 94 in V3): each ``logsout`` Dataset element appears as an
    ``'outport'`` marker followed by its name (``P_req_final``, ``P_Bat``,
    ``SOC``, ..., ``MotorSpeed``).  The final pair carries the standalone name
    ``P_req`` with no ``'outport'`` marker -- that is ``out.simout``, the
    To-Workspace copy.  It is bit-identical to the ``P_req`` logsout element
    (pair ordinal 6, metadata index 171) in all ten shipped files; that
    duplication is checked at load time.
    """
    bigs = [
        (k, np.ravel(e))
        for k, e in enumerate(meta)
        if isinstance(e, np.ndarray) and e.dtype == np.float64 and e.size > _MIN_SIGNAL_LEN
    ]
    pairs = []
    j = 0
    while j < len(bigs) - 1:
        idx_t, t = bigs[j]
        _, dat = bigs[j + 1]
        if (
            t[0] == 0.0
            and np.all(np.diff(t) >= 0)
            and dat.size == t.size
            and not np.all(np.diff(dat) >= 0)
        ):
            pairs.append((idx_t, t, dat))
            j += 2
        else:
            j += 1
    return pairs


def load_pdem_cycle(path: str, strict: bool = True):
    """Load one Simulink cycle file.

    Returns ``(t, p_dem_scaled)`` -- the ``out.simout`` time vector and its
    data multiplied by the energy scaling factor sE (TPM_generator.m:22-23).

    ``strict`` (default True) enforces the layout invariant: the selected
    (last) pair must be bit-identical to an earlier pair in the same file.
    A file that logs an extra swinging signal after simout would otherwise be
    silently mis-read.  Set False to bypass with a warning.
    """
    t, p, _ = _load_pdem_cycle_with_layout(path, strict=strict)
    return t, p


def _load_pdem_cycle_with_layout(path: str, strict: bool = True):
    """Internal: like ``load_pdem_cycle`` but also returns layout metadata."""
    meta = _read_object_metadata(path)
    pairs = _extract_timeseries_pairs(meta)
    if not pairs:
        raise ValueError(f"{path}: no (time, data) timeseries pair found in MCOS metadata")
    chosen_idx, t, data = pairs[-1]          # last pair == out.simout

    dup_ordinals = [k for k, (_, _, d) in enumerate(pairs[:-1])
                    if d.size == data.size and np.array_equal(d, data)]
    layout = {
        "n_pairs": len(pairs),
        "chosen_pair_ordinal": len(pairs) - 1,
        "chosen_meta_index": int(chosen_idx),
        "duplicate_pair_ordinals": [int(k) for k in dup_ordinals],
    }
    if not dup_ordinals:
        msg = (
            f"{os.path.basename(path)}: the selected simout pair (metadata index "
            f"{chosen_idx}, pair {len(pairs) - 1} of {len(pairs)}) does NOT duplicate "
            "any earlier logged signal. In all ten shipped cycle files simout is a "
            "second copy of the logsout 'P_req' element (pair ordinal "
            f"{_EXPECTED_DUP_ORDINAL}). This file departs from the known layout and "
            "the last-pair rule may be selecting the wrong signal."
        )
        if strict:
            raise ValueError(msg + " Pass strict=False to load it anyway.")
        print(f"WARNING: {msg}", file=sys.stderr)
    elif _EXPECTED_DUP_ORDINAL not in dup_ordinals:
        print(
            f"WARNING: {os.path.basename(path)}: simout duplicates pair ordinal(s) "
            f"{dup_ordinals}, not the expected {_EXPECTED_DUP_ORDINAL}. Selection is "
            "probably still correct (the duplicate invariant holds) but the file "
            "layout differs from the shipped set.",
            file=sys.stderr,
        )

    t = np.ascontiguousarray(t, dtype=np.float64)
    p = np.ascontiguousarray(data, dtype=np.float64) * SE
    del meta, pairs
    return t, p, layout


def cycle_paths(cycle_dir: str = CYCLE_DIR, n: int = NUM_DATASETS):
    """V1..V10 in MATLAB ``num2str(i)`` order (not lexicographic)."""
    return [
        os.path.join(cycle_dir, f"simulink_pdem_output_stochastic_V{i}.mat")
        for i in range(1, n + 1)
    ]


def load_all_cycles(cycle_dir: str = CYCLE_DIR, n: int = NUM_DATASETS,
                    verbose: bool = False, strict: bool = True,
                    layouts: list | None = None,
                    drop_duplicates: bool = False):
    """Load V1..V10, cross-checking layout consistency and duplicate signals.

    Emits loud stdout warnings for (a) any two files whose DECODED simout
    signal hashes match (F1: V1 and V2 are bit-identical in the shipped set --
    one cycle is effectively double-weighted in the TPM) and (b) any file whose
    pair count / chosen index departs from the majority.  Neither is fatal:
    excluding a duplicate is an operator decision and the dt=1.0 gate requires
    inclusion.
    """
    series = []
    info = []
    for p in cycle_paths(cycle_dir, n):
        if not os.path.isfile(p):
            raise FileNotFoundError(p)
        t, y, layout = _load_pdem_cycle_with_layout(p, strict=strict)
        rec = dict(layout)
        rec["path"] = p
        rec["signal_sha256"] = hashlib.sha256(
            np.ascontiguousarray(y, dtype=np.float64).tobytes()).hexdigest()
        rec["n_native"] = int(t.size)
        rec["t_start"] = float(t[0])
        rec["t_end"] = float(t[-1])
        info.append(rec)
        if verbose:
            print(f"  loaded {os.path.basename(p)}: {t.size} samples, "
                  f"t=[{t[0]:.1f}, {t[-1]:.1f}] s, {layout['n_pairs']} pairs, "
                  f"simout@{layout['chosen_meta_index']}")
        series.append((t, y))

    # (a) duplicate decoded signals
    by_hash: dict[str, list[int]] = {}
    for i, rec in enumerate(info):
        by_hash.setdefault(rec["signal_sha256"], []).append(i)
    dup_groups = [g for g in by_hash.values() if len(g) > 1]
    dropped = set()
    for g in dup_groups:
        names = [os.path.basename(info[i]["path"]) for i in g]
        if drop_duplicates:
            for i in g[1:]:
                dropped.add(i)
            kept_name = os.path.basename(info[g[0]]["path"])
            print(f"DEVIATION: dropping {names[1:]} -- decoded simout signal is "
                  f"BIT-IDENTICAL to {kept_name}; keeping the first occurrence "
                  f"only ({len(g) - 1} cycle(s) removed from the TPM).")
        else:
            print(f"WARNING: cycle files {names} contain the BIT-IDENTICAL decoded "
                  f"simout signal. That cycle is double-weighted in the TPM. Not "
                  f"excluded: the dt=1.0 gate requires inclusion, and exclusion is "
                  f"an operator decision (--drop-duplicates).")
    for i, rec in enumerate(info):
        rec["dropped_duplicate"] = i in dropped
    if dropped:
        series = [s for i, s in enumerate(series) if i not in dropped]

    # (b) layout consistency
    from collections import Counter
    maj_pairs = Counter(r["n_pairs"] for r in info).most_common(1)[0][0]
    maj_index = Counter(r["chosen_meta_index"] for r in info).most_common(1)[0][0]
    for rec in info:
        if rec["n_pairs"] != maj_pairs or rec["chosen_meta_index"] != maj_index:
            # V3 legitimately yields 21 pairs / index 558 (it logs one fewer
            # signal); the duplicate-signal invariant above is the real guard,
            # so this is informational, not fatal.
            print(f"NOTE: {os.path.basename(rec['path'])} layout differs from the "
                  f"majority ({rec['n_pairs']} pairs @ {rec['chosen_meta_index']} vs "
                  f"{maj_pairs} @ {maj_index}); simout still duplicates pair ordinal "
                  f"{rec['duplicate_pair_ordinals']}, so selection is confirmed.")

    if layouts is not None:
        layouts.extend(info)
    return series


# ---------------------------------------------------------------------------
# Binning / TPM
# ---------------------------------------------------------------------------
def rescale_gamma(gamma_base: float, dt: float,
                  dt_base: float = GAMMA_DT_BASE_S) -> float:
    """Discount factor rescaled to a different decision step.

    ``gamma_eff = gamma_base ** (dt / dt_base)`` keeps the continuous-time
    planning horizon invariant: a gamma tuned per 1 s step (the student's
    0.95) must NOT be reused verbatim at another step -- at 20 ms it would
    shrink the effective horizon from ~20 s to ~0.4 s.
    """
    if not (0.0 < gamma_base <= 1.0):
        raise ValueError(f"gamma_base must be in (0, 1], got {gamma_base}")
    if dt <= 0 or dt_base <= 0:
        raise ValueError("dt and dt_base must be positive")
    return float(gamma_base ** (dt / dt_base))


def matlab_time_grid(dt: float, t_end: float = T_END) -> np.ndarray:
    """MATLAB colon semantics for ``0:dt:t_end``.

    ``np.arange(0, t_end + dt/2, dt)`` misbehaves when dt does not divide
    t_end (dt=0.03 drops the endpoint region inconsistently; dt=7.0 overshoots
    past 1000).  MATLAB emits floor(t_end/dt) + 1 points.
    """
    if dt <= 0:
        raise ValueError("dt must be positive")
    n = int(np.floor(t_end / dt + 1e-9)) + 1
    return np.arange(n, dtype=np.float64) * dt


def matlab_discretize(x: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """MATLAB ``discretize`` semantics, 0-based, with NaN for out-of-range.

    Bin i covers [edges[i], edges[i+1]) EXCEPT the last bin (i = n_bins-1),
    which is CLOSED: [edges[-2], edges[-1]].  ``np.digitize`` alone puts a
    value equal to the last edge into an overflow bin, so the closed right end
    is applied explicitly.  Returns a float array (NaN = out of range, and NaN
    input maps to NaN) mirroring MATLAB.
    """
    x = np.asarray(x, dtype=np.float64)
    n_bins = edges.size - 1
    idx = np.digitize(x, edges, right=False) - 1
    idx = np.where(x == edges[-1], n_bins - 1, idx)         # closed last bin
    out = idx.astype(np.float64)
    # Positive-form mask: NaN fails (x >= lo) & (x <= hi), so ~mask routes
    # NaN input to NaN output instead of falling through to the last bin.
    in_range = (x >= edges[0]) & (x <= edges[-1])
    out[~in_range] = np.nan
    return out


def build_tpm(series_list, dt: float, n_bins: int = N_BINS_DEFAULT,
              exclude_boundary: bool = False, truncate_native: bool = False,
              smoothing_alpha: float = 0.0, empty_row_policy: str = "zero"):
    """Build the TPM from a list of ``(t, p_dem_scaled)`` cycles.

    Returns ``(tpm, counts, meta)``.  ``meta`` carries the concatenated
    min/max, per-file resampled lengths, extrapolation accounting, row
    occupancy, all-zero rows, diagonal mass and the deviation policies.
    ``counts`` is always the RAW (unsmoothed) transition-count matrix.

    Deviations from the MATLAB (all default off; the dt=1.0 gate requires
    every default):

    * ``truncate_native`` -- resample each cycle only over its own native
      time span instead of spline-extrapolating to T_END (V3 ends at 600 s;
      extrapolated near-zero samples inflate idle-bin persistence).
    * ``smoothing_alpha`` -- Laplace add-alpha on every cell of the counts
      before row normalization (rare-transition and zero-row mitigation for
      a thin dataset).
    * ``empty_row_policy`` -- rows with zero RAW counts and zero smoothed
      mass: ``"zero"`` (parity: all-zero row, which an SDP expectation reads
      as cost 0 -- optimistic), ``"self"`` (probability 1 self-transition),
      ``"uniform"`` (1/n_bins each).
    """
    if dt <= 0:
        raise ValueError("dt must be positive")
    if not series_list:
        raise ValueError("series_list is empty")
    if smoothing_alpha < 0:
        raise ValueError("smoothing_alpha must be >= 0")
    if empty_row_policy not in ("zero", "self", "uniform"):
        raise ValueError(f"empty_row_policy must be zero|self|uniform, "
                         f"got {empty_row_policy!r}")
    time_common = matlab_time_grid(dt)

    resampled = []
    per_file = []
    for t, y in series_list:
        cs = CubicSpline(t, y, bc_type="not-a-knot", extrapolate=True)
        if truncate_native:
            # DEVIATION: only query the grid inside the cycle's native span.
            grid = time_common[(time_common >= t[0] - 1e-9)
                               & (time_common <= t[-1] + 1e-9)]
        else:
            grid = time_common
        r = np.asarray(cs(grid), dtype=np.float64)
        n_extrap = int(np.count_nonzero((grid < t[0]) | (grid > t[-1])))
        per_file.append({
            "n_native": int(t.size),
            "t_start": float(t[0]),
            "t_end": float(t[-1]),
            "n_resampled": int(r.size),
            "n_extrapolated": n_extrap,
            "extrapolated_fraction": (n_extrap / r.size) if r.size else 0.0,
        })
        resampled.append(r)
    lengths = [r.size for r in resampled]
    x = np.concatenate(resampled)
    del resampled

    xmin = float(x.min())
    xmax = float(x.max())
    if not np.isfinite(xmin) or not np.isfinite(xmax):
        raise ValueError("concatenated P_dem contains non-finite values")
    if xmax == xmin:
        raise ValueError(
            "degenerate series: concatenated P_dem is constant "
            f"({xmin}); the min/max normalization is undefined."
        )
    xn = (x - xmin) / (xmax - xmin)

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idxf = matlab_discretize(xn, edges)

    a = idxf[:-1]
    b = idxf[1:]
    if exclude_boundary:
        # DEVIATION from the MATLAB: drop transitions spanning a file join.
        keep = np.ones(a.size, dtype=bool)
        cut = 0
        for L in lengths[:-1]:
            cut += L
            keep[cut - 1] = False
        a = a[keep]
        b = b[keep]

    valid = np.isfinite(a) & np.isfinite(b)
    ai = a[valid].astype(np.int64)
    bi = b[valid].astype(np.int64)
    in_range = (ai >= 0) & (ai < n_bins) & (bi >= 0) & (bi < n_bins)
    if not np.all(in_range):
        raise ValueError(
            f"{int(np.count_nonzero(~in_range))} bin index/indices outside "
            f"[0, {n_bins}) survived discretization; refusing to count."
        )

    counts = np.zeros((n_bins, n_bins), dtype=np.float64)
    np.add.at(counts, (ai, bi), 1.0)

    raw_row_sums = counts.sum(axis=1)
    smoothed = counts + smoothing_alpha if smoothing_alpha > 0 else counts
    row_sums = smoothed.sum(axis=1)
    tpm = np.zeros_like(smoothed)
    nz = row_sums > 0
    tpm[nz] = smoothed[nz] / row_sums[nz, None]
    empty = ~nz
    if empty.any() and empty_row_policy == "self":
        # DEVIATION: an unvisited demand bin is modeled as absorbing rather
        # than as "future cost 0" (which the SDP expectation would read from
        # an all-zero row -- an optimistic bias).
        tpm[np.flatnonzero(empty), np.flatnonzero(empty)] = 1.0
    elif empty.any() and empty_row_policy == "uniform":
        tpm[empty] = 1.0 / n_bins

    diag_mass = (float(np.trace(counts) / raw_row_sums.sum())
                 if raw_row_sums.sum() > 0 else 0.0)
    n_extrap_total = sum(f["n_extrapolated"] for f in per_file)
    meta = {
        "dt": float(dt),
        "n_bins": int(n_bins),
        "n_samples_total": int(x.size),
        "n_grid_points": int(time_common.size),
        "grid_t_last": float(time_common[-1]),
        "resampled_lengths": [int(v) for v in lengths],
        "per_file": per_file,
        "extrapolation_summary": {
            "n_extrapolated_total": int(n_extrap_total),
            "extrapolated_fraction_of_dataset": (n_extrap_total / x.size) if x.size else 0.0,
            "files_with_extrapolation": [
                i for i, f in enumerate(per_file) if f["n_extrapolated"] > 0],
            "note": "MATLAB parity: interp1(...,'spline','extrap') is retained. "
                    "Extrapolated samples are numerically near zero and land in "
                    "the dominant idle bin, inflating idle-state persistence.",
        },
        "n_transitions_counted": int(ai.size),
        "exclude_boundary": bool(exclude_boundary),
        "n_boundary_transitions": int(len(lengths) - 1),
        "truncate_native": bool(truncate_native),
        "smoothing_alpha": float(smoothing_alpha),
        "empty_row_policy": empty_row_policy,
        "p_dem_scaled_min": xmin,
        "p_dem_scaled_max": xmax,
        "p_dem_raw_min": xmin / SE,
        "p_dem_raw_max": xmax / SE,
        "row_occupancy": [int(v) for v in raw_row_sums],
        "zero_rows": [int(i) for i in np.flatnonzero(raw_row_sums == 0)],
        "diagonal_mass": diag_mass,
        "nnz": int(np.count_nonzero(tpm)),
    }
    return tpm, counts, meta


# ---------------------------------------------------------------------------
# Output path safety / atomic writes
# ---------------------------------------------------------------------------
def _canon(p: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(p)))


def check_output_path(out_path: str) -> str | None:
    """Return a refusal reason for ``out_path``, or None if it is acceptable.

    Refuses (a) any directory under references/EMS EXCEPT
    references/EMS/generated, and (b) any basename that looks like a cycle
    file, in any directory -- those inputs are untracked and irreplaceable.
    Comparisons are realpath+normcase so a case-insensitive filesystem or a
    directory junction cannot bypass the check.
    """
    base = os.path.basename(out_path)
    if base.lower().startswith(_CYCLE_BASENAME_PREFIX):
        return (f"output basename {base!r} matches the cycle-file pattern "
                f"'simulink_pdem_output_stochastic_V*.mat'; those inputs are "
                f"untracked and irreplaceable.")
    out_dir = _canon(os.path.dirname(os.path.abspath(out_path)))
    ems = _canon(EMS_DIR)
    allowed = _canon(DEFAULT_OUT_DIR)
    try:
        under_ems = os.path.commonpath([out_dir, ems]) == ems
    except ValueError:      # different drives
        under_ems = False
    if not under_ems:
        return None
    try:
        under_allowed = os.path.commonpath([out_dir, allowed]) == allowed
    except ValueError:
        under_allowed = False
    if under_allowed:
        return None
    return (f"refusing to write inside the reference tree {EMS_DIR}; the only "
            f"permitted location under it is {DEFAULT_OUT_DIR}.")


def _atomic_write_bytes(path: str, writer) -> None:
    """Write via ``<path>.tmp`` then ``os.replace``; unlink the temp on error."""
    tmp = path + ".tmp"
    try:
        writer(tmp)
        os.replace(tmp, path)
    except BaseException:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        raise


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def run_validate(args) -> int:
    ref_path = args.reference
    if not os.path.isfile(ref_path):
        print(f"ERROR: reference not found: {ref_path}")
        return 2
    ref = np.asarray(loadmat(ref_path)["TPM"], dtype=np.float64)
    print(f"Validation gate: dt=1.0 vs {os.path.relpath(ref_path, REPO_ROOT)}")
    print("Loading cycles (V1..V10)...")
    series = load_all_cycles(args.cycle_dir, verbose=args.verbose)
    # Pure parity build: main() refuses every deviation flag under --validate.
    tpm, counts, meta = build_tpm(series, 1.0, N_BINS_DEFAULT)

    if tpm.shape != ref.shape:
        print(f"FAIL: shape {tpm.shape} != reference {ref.shape}")
        return 1
    diff = np.abs(tpm - ref)
    max_abs = float(diff.max())
    print(f"  nonzeros: generated {np.count_nonzero(tpm)}, reference {np.count_nonzero(ref)}")
    print(f"  max abs diff: {max_abs:.17g}")
    if max_abs == 0.0 and np.count_nonzero(tpm) == np.count_nonzero(ref):
        print("PASS: TPM is bit-identical to the reference.")
        return 0

    print("FAIL: TPM differs from the reference.")
    rows = sorted({int(i) for i in np.argwhere(diff > 0)[:, 0]})
    print(f"  {len(rows)} row(s) differ: {rows[:20]}{' ...' if len(rows) > 20 else ''}")
    shown = 0
    for i, j in np.argwhere(diff > 0):
        n_gen = counts[i, j]
        n_ref_est = ref[i, j] * counts[i].sum()
        print(f"   [{i:2d},{j:2d}] gen p={tpm[i, j]:.12g} (count {n_gen:.0f})  "
              f"ref p={ref[i, j]:.12g} (implied count {n_ref_est:.3f})")
        shown += 1
        if shown >= 40:
            print("   ... (truncated)")
            break
    return 1


def resolve_deviation_args(args):
    """Resolve the deviation flags (incl. the --hil preset) into a dict.

    Pure: reads ``args`` only.  Explicit flags win over the preset; without
    --hil the unset options resolve to MATLAB parity (n_bins 50, no
    smoothing, empty rows zero, keep duplicates, extrapolate, include
    boundary transitions).
    """
    hil = bool(getattr(args, "hil", False))
    n_bins = getattr(args, "n_bins", None)
    alpha = getattr(args, "smooth_alpha", None)
    erp = getattr(args, "empty_row_policy", None)
    return {
        "n_bins": n_bins if n_bins is not None
                  else (N_BINS_HIL if hil else N_BINS_DEFAULT),
        "smoothing_alpha": alpha if alpha is not None else 0.0,
        "empty_row_policy": erp if erp else ("self" if hil else "zero"),
        "drop_duplicates": bool(getattr(args, "drop_duplicates", False) or hil),
        "truncate_native": bool(getattr(args, "truncate_native", False) or hil),
        "exclude_boundary": bool(getattr(args, "exclude_boundary", False) or hil),
    }


def run_generate(args, argv_used) -> int:
    dt = args.dt
    dev = resolve_deviation_args(args)
    out_path = args.out
    if out_path is None:
        tag = ("%g" % dt).replace(".", "p")
        # A deviation artifact must not auto-name onto the parity name.
        parity = (dev["n_bins"] == N_BINS_DEFAULT and dev["smoothing_alpha"] == 0.0
                  and dev["empty_row_policy"] == "zero"
                  and not dev["drop_duplicates"] and not dev["truncate_native"]
                  and not dev["exclude_boundary"])
        suffix = "" if parity else ("_hil" if getattr(args, "hil", False) else "_dev")
        out_path = os.path.join(DEFAULT_OUT_DIR, f"TPM_dt{tag}{suffix}.mat")
    out_path = os.path.abspath(out_path)

    refusal = check_output_path(out_path)
    if refusal:
        print(f"ERROR: {refusal}")
        return 2
    out_dir = os.path.dirname(out_path)
    os.makedirs(out_dir, exist_ok=True)
    prov_path = out_path + ".provenance.json"
    if not args.force:
        for p in (out_path, prov_path):
            if os.path.exists(p):
                print(f"ERROR: {p} exists; pass --force to overwrite.")
                return 2

    print(f"Generating TPM at dt={dt} s ...")
    active_dev = sorted(k for k, v in dev.items()
                        if v not in (False, 0.0, N_BINS_DEFAULT, "zero"))
    if active_dev:
        print(f"  deviations from TPM_generator.m: {active_dev} "
              f"(output is NOT gate-comparable)")
    paths = cycle_paths(args.cycle_dir)
    layouts: list = []
    series = load_all_cycles(args.cycle_dir, verbose=args.verbose, layouts=layouts,
                             drop_duplicates=dev["drop_duplicates"])
    tpm, counts, meta = build_tpm(
        series, dt, dev["n_bins"],
        exclude_boundary=dev["exclude_boundary"],
        truncate_native=dev["truncate_native"],
        smoothing_alpha=dev["smoothing_alpha"],
        empty_row_policy=dev["empty_row_policy"])

    if dt < DT_GUIDANCE_S:
        print(f"WARNING: dt={dt} s is below {DT_GUIDANCE_S} s; the TPM is "
              f"near-identity (diagonal mass "
              f"{100 * meta['diagonal_mass']:.1f}%) and carries little "
              f"predictive information. Run the SDP decision layer at "
              f"~0.5-1 s and zero-order-hold its output at the 50 Hz "
              f"commander; rescale any discount factor with "
              f"rescale_gamma(gamma_base, dt).")

    ex = meta["extrapolation_summary"]
    if ex["n_extrapolated_total"] > 0:
        # meta["per_file"] indexes the KEPT series; map back through layouts.
        kept_paths = [p for p, lay in zip(paths, layouts)
                      if not lay.get("dropped_duplicate", False)]
        names = [os.path.basename(kept_paths[i]) for i in ex["files_with_extrapolation"]]
        print(f"WARNING: {ex['n_extrapolated_total']} of {meta['n_samples_total']} samples "
              f"({100 * ex['extrapolated_fraction_of_dataset']:.2f}% of the dataset) are "
              f"SPLINE-EXTRAPOLATED beyond their cycle's native time span "
              f"(files: {names}). These are near-zero and land in the dominant idle "
              f"bin, inflating idle-state persistence. Retained for MATLAB parity.")

    # F9: file hashes computed before the writes so a slow hash cannot leave a
    # half-written output behind.
    file_records = []
    kept = 0
    for i, p in enumerate(paths):
        lay = layouts[i]
        rec = {
            "path": os.path.relpath(p, REPO_ROOT).replace("\\", "/"),
            "sha256": _sha256(p),
            "bytes": os.path.getsize(p),
            "signal_sha256": lay["signal_sha256"],
            "n_pairs": lay["n_pairs"],
            "chosen_meta_index": lay["chosen_meta_index"],
            "duplicate_pair_ordinals": lay["duplicate_pair_ordinals"],
            "dropped_duplicate": bool(lay.get("dropped_duplicate", False)),
            "n_native": lay["n_native"],
            "t_start": lay["t_start"],
            "t_end": lay["t_end"],
        }
        if rec["dropped_duplicate"]:
            # Dropped before build_tpm -- no resample stats exist for it.
            rec.update({"n_resampled": None, "n_extrapolated": None,
                        "extrapolated_fraction": None})
        else:
            pf = meta["per_file"][kept]
            kept += 1
            rec.update({"n_resampled": pf["n_resampled"],
                        "n_extrapolated": pf["n_extrapolated"],
                        "extrapolated_fraction": pf["extrapolated_fraction"]})
        file_records.append(rec)
    by_hash: dict[str, list[str]] = {}
    for rec in file_records:
        by_hash.setdefault(rec["signal_sha256"], []).append(rec["path"])
    duplicate_signal_groups = [g for g in by_hash.values() if len(g) > 1]

    _atomic_write_bytes(out_path, lambda tmp: savemat(tmp, {"TPM": tpm}, do_compression=True))

    provenance = {
        "tool": "tools/tpm_generator.py",
        "argv": list(argv_used),
        "source_matlab": "references/EMS/TPM_generator.m",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "output_mat": os.path.basename(out_path),
        "output_mat_sha256": _sha256(out_path),
        "dt_s": float(dt),
        "time_grid": f"0:{dt}:{T_END} (MATLAB colon semantics; "
                     f"{meta['n_grid_points']} points, last t={meta['grid_t_last']})",
        "cycle_files": file_records,
        "duplicate_signal_groups": duplicate_signal_groups,
        "signal_identification": (
            "out.simout = last (time, data) float64 pair in the MCOS "
            "_ObjectMetadata cell array. Cross-checked per file: the chosen "
            "pair's data must be bit-identical to an earlier pair (the logsout "
            f"'P_req' element, pair ordinal {_EXPECTED_DUP_ORDINAL}); a file "
            "without that duplicate is rejected."
        ),
        "gate_provenance": {
            "claim": "At dt=1.0 this tool reproduces references/EMS/TPM_scaled.mat "
                     "bit-identically (max abs diff 0, 497 nonzeros).",
            "last_proven": GATE_LAST_PROVEN,
            "how_to_reprove": "python tools/tpm_generator.py --validate",
            "note": "The gate is NOT re-run during generation (it would double runtime).",
        },
        "scaling": {
            "m_original_kg": M_ORIGINAL_KG,
            "vmax_original_kph": VMAX_ORIGINAL_KPH,
            "m_scale_kg": M_SCALE_KG,
            "vmax_scale_kph": VMAX_SCALE_KPH,
            "sm": SM, "sl": SL, "sE": SE,
        },
        "interpolation": "scipy CubicSpline bc_type='not-a-knot', extrapolate=True "
                         "(== MATLAB interp1 'spline','extrap')",
        "bins": {
            "n_bins": dev["n_bins"],
            "edges": f"linspace(0, 1, {dev['n_bins'] + 1})",
            "convention": "MATLAB discretize, reported 0-based: bin i is "
                          "[e_i, e_i+1) except the last bin, closed",
        },
        "normalization": {
            "contract": "UNITLESS: bins partition [0,1]; the matrix is "
                        "invariant to affine rescaling of the demand axis. "
                        "The SDP consumer owns the energy scaling: map "
                        "measured P_dem onto [0,1] (this run used the "
                        "min/max below) and clamp out-of-range to the end "
                        "bins. A new energy scale changes the SDP lookup "
                        "map, not this matrix.",
            "p_dem_scaled_min_w": meta["p_dem_scaled_min"],
            "p_dem_scaled_max_w": meta["p_dem_scaled_max"],
        },
        "gamma_rescaling": {
            "rule": "gamma_eff = gamma_base ** (dt / dt_base); see "
                    "rescale_gamma(). A discount tuned per 1 s step (the "
                    "student's 0.95) must be rescaled before solving at any "
                    "other decision step.",
            "dt_base_s": GAMMA_DT_BASE_S,
            "example": {"gamma_base": 0.95, "dt_s": float(dt),
                        "gamma_eff": rescale_gamma(0.95, float(dt))},
        },
        "deviations": {
            "any_active": bool(active_dev),
            "active": active_dev,
            "n_bins": dev["n_bins"],
            "smoothing_alpha": dev["smoothing_alpha"],
            "empty_row_policy": dev["empty_row_policy"],
            "drop_duplicates": dev["drop_duplicates"],
            "truncate_native": dev["truncate_native"],
            "exclude_boundary": dev["exclude_boundary"],
            "note": "Any active deviation makes this output NOT comparable "
                    "to the dt=1.0 parity gate.",
        },
        "boundary_transition_policy": (
            "EXCLUDED (deviation from TPM_generator.m)" if dev["exclude_boundary"]
            else "INCLUDED (matches TPM_generator.m: concatenate then count)"
        ),
        "versions": {"numpy": np.__version__, "scipy": scipy.__version__,
                     "python": sys.version.split()[0]},
        "results": meta,
    }
    _atomic_write_bytes(
        prov_path,
        lambda tmp: open(tmp, "w", encoding="utf-8").write(
            json.dumps(provenance, indent=2)),
    )

    occ = np.array(meta["row_occupancy"], dtype=np.int64)
    print(f"  wrote {out_path}")
    print(f"  wrote {prov_path}")
    print(f"  samples {meta['n_samples_total']}, transitions {meta['n_transitions_counted']}")
    print(f"  nnz {meta['nnz']}, zero rows {len(meta['zero_rows'])} {meta['zero_rows']}")
    print(f"  row occupancy: min {occ.min()}, median {int(np.median(occ))}, max {occ.max()}")
    print(f"  diagonal mass {100 * meta['diagonal_mass']:.2f}% "
          f"(self-transitions / all transitions)")
    print(f"  P_dem scaled range [{meta['p_dem_scaled_min']:.6g}, "
          f"{meta['p_dem_scaled_max']:.6g}] W")
    return 0


def main(argv=None) -> int:
    argv_used = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        description="Build a binned power-demand Markov TPM from the Simulink "
                    "stochastic drive cycles (Python port of TPM_generator.m).")
    ap.add_argument("--validate", action="store_true",
                    help="run the dt=1.0 gate against the reference TPM and exit 0/1")
    ap.add_argument("--reference", default=REFERENCE_TPM,
                    help="reference .mat for --validate (default: references/EMS/TPM_scaled.mat)")
    ap.add_argument("--dt", type=float, default=None,
                    help="resampling time step in seconds (default 1.0; target use 0.02). "
                         "Not allowed with --validate.")
    ap.add_argument("--out", default=None,
                    help="output .mat path (default references/EMS/generated/TPM_dt<...>.mat)")
    ap.add_argument("--cycle-dir", default=CYCLE_DIR, help="directory of the cycle .mat files")
    ap.add_argument("--exclude-boundary", action="store_true",
                    help="DEVIATION: skip transitions spanning a cycle-file boundary")
    ap.add_argument("--n-bins", type=int, default=None,
                    help="DEVIATION: bin count (parity default 50; --hil preset 25)")
    ap.add_argument("--smooth-alpha", type=float, default=None,
                    help="DEVIATION: Laplace add-alpha smoothing of the counts "
                         "(parity default 0)")
    ap.add_argument("--empty-row-policy", choices=("zero", "self", "uniform"),
                    default=None,
                    help="DEVIATION: policy for zero-count rows (parity default "
                         "zero; --hil preset self)")
    ap.add_argument("--drop-duplicates", action="store_true",
                    help="DEVIATION: drop later cycles whose decoded signal is "
                         "bit-identical to an earlier one (V2 == V1)")
    ap.add_argument("--truncate-native", action="store_true",
                    help="DEVIATION: resample each cycle over its native time "
                         "span only, instead of spline-extrapolating to 1000 s")
    ap.add_argument("--hil", action="store_true",
                    help="preset for HIL/SDP use: --drop-duplicates "
                         "--truncate-native --exclude-boundary --n-bins 25 "
                         "--empty-row-policy self (explicit flags win)")
    ap.add_argument("--force", action="store_true", help="overwrite existing output files")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    dt_given = args.dt is not None
    if args.validate and dt_given:
        print("ERROR: --dt cannot be combined with --validate; the gate is "
              "defined at dt = 1.0 only.")
        return 2
    if args.validate:
        dev_flags = [name for name, on in (
            ("--exclude-boundary", args.exclude_boundary),
            ("--n-bins", args.n_bins is not None),
            ("--smooth-alpha", args.smooth_alpha is not None),
            ("--empty-row-policy", args.empty_row_policy is not None),
            ("--drop-duplicates", args.drop_duplicates),
            ("--truncate-native", args.truncate_native),
            ("--hil", args.hil),
        ) if on]
        if dev_flags:
            print(f"ERROR: {dev_flags} cannot be combined with --validate; "
                  "the gate is defined for the MATLAB-parity configuration only.")
            return 2
    if args.n_bins is not None and args.n_bins < 2:
        print(f"ERROR: --n-bins must be >= 2 (got {args.n_bins}).")
        return 2
    if args.smooth_alpha is not None and (
            not np.isfinite(args.smooth_alpha) or args.smooth_alpha < 0):
        print(f"ERROR: --smooth-alpha must be a finite number >= 0 "
              f"(got {args.smooth_alpha}).")
        return 2
    if args.dt is None:
        args.dt = 1.0
    if not np.isfinite(args.dt) or args.dt <= 0:
        print(f"ERROR: --dt must be a positive finite number (got {args.dt}).")
        return 2

    if args.validate:
        return run_validate(args)
    return run_generate(args, argv_used)


if __name__ == "__main__":
    sys.exit(main())
