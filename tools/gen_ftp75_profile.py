#!/usr/bin/env python3
"""Generate tools/ftp75_profile.py from the committed EPA FTP-75 raw data.

WHAT THIS IS.  The EPA's Federal Test Procedure (FTP-75) city drive cycle,
first 340 seconds, rescaled from vehicle mph to this rig's flywheel surface
speed and emitted as a piecewise-linear [(t, v_mps), ...] table that
`hil_plant_sim.py` consumes through a scenario's `ems_v_profile`.

WHY 340 SECONDS.  The slice is raw t = 0..340 s INCLUSIVE, i.e. 341 samples at
1 Hz.  That is the segment used in the scaled-vehicle study this
rig serves, references/Systemic_Scaling_of_Powertrain_Models_with_Youla_
Driver_Control.pdf (operator direction, 2026-08-31).  Matching the published
segment is the whole reason for the bound; it is NOT an arbitrary trim of
Phase 1 (which runs to t = 505 s) and must not be "restored" to 505 without
the study moving first.  The cycle's peak, 56.7 mph at t = 240 s, lies inside
the segment, so the scaling anchor below is unaffected by the choice.

END TREATMENT: NONE, AND NONE IS NEEDED.  The raw trace decelerates
8 -> 4.7 -> 1.4 -> 0 mph over t = 330..333 and reads 0 mph continuously from
t = 333 through t = 340, so the cut lands inside a NATIVE idle segment and the
segment ends at rest on its own.  No synthetic ramp-down tail is appended, and
nothing in the emitted table is anything but EPA data times one constant.

WHY A GENERATOR AND NOT A HAND-TYPED TABLE.  The raw file is 1875 rows; the
scaling is one constant; the decimation is mechanical.  Typing any of that by
hand invites exactly the class of transcription error the fw v8 slot-count
lesson was about (CLAUDE.md: "120 counts" recorded for "120 slots").  The
generator reads the COMMITTED raw file, verifies its sha256, and writes a
module carrying its own provenance header, so the chain from EPA bytes to
simulator setpoint is reproducible in one command:

    .venv_hil/Scripts/python.exe tools/gen_ftp75_profile.py --force

DETERMINISM.  stdlib only, no dict iteration over unordered inputs, and every
float is emitted with repr() (shortest round-tripping form).  Two runs on the
same input produce byte-identical output; that is asserted by the verification
step in the round's report and is cheap to re-check with a diff.

SCALING.  Vehicle mph -> rig m/s is ONE constant, chosen so the cycle's peak
lands on 3.0 m/s:

    v_mps = mph * (TARGET_PEAK_MPS / PEAK_MPH)
          = mph * 3.0 / 56.7

The mph->m/s SI factor (0.44704) cancels out of this ratio by construction —
the rig is not a 56.7 mph vehicle and nothing here claims dynamic similarity.
3.0 m/s is the top of the speed range the drive channel has been exercised at
on this bench (CLAUDE.md fw v16 round: ML0169 held a true 3.0 m/s), and the
whole cycle sits above the drive design's 0.5 m/s validity floor only
intermittently — the standstill and creep segments of the FTP are part of the
stimulus, not a defect.  See docs/HIL_PLANT.md.

DECIMATION.  The raw cycle is sampled at 1 Hz, and long stretches of it are
exactly linear (constant-acceleration ramps and constant-speed cruises), so
most interior points are redundant under the piecewise-linear interpolation
`hil_plant_sim.piecewise()` performs.  Points are dropped ONLY when the
reconstruction stays within COLLINEAR_TOL, and the generator then RE-VERIFIES
the reduced table against every original sample and reports the worst error.
The reduction is a cost saving in `piecewise()` (a linear scan), never a
change to the stimulus.
"""

import argparse
import hashlib
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)

# ── Raw data provenance (see references/drive_cycles/PROVENANCE.md) ──────────
RAW_REL = os.path.join("references", "drive_cycles", "ftpcol.txt")
RAW_PATH = os.path.join(REPO_ROOT, RAW_REL)
RAW_SHA256 = "9791a45a7fb2415de0bf01948b96e8aeff499bfd63744a8c6ca781ae88826f8a"
RAW_SIZE = 17689
SOURCE_URL = "https://www.epa.gov/sites/default/files/2015-10/ftpcol.txt"
FETCH_DATE = "2026-08-31"

# ── Slice: the study segment, t = 0..340 s ──────────────────────────────────
# The FTP-75 is Phase 1 (cold transient, 0-505 s), Phase 2 (stabilized,
# 505-1372 s), a 10-minute engine-off SOAK, then Phase 3 (a repeat of Phase 1
# hot).  The soak is NOT in this file — `t` runs continuously 0..1874 — so
# slicing by time is the only correct way to take a segment out of it.
#
# 340 s is the segment of the SCALED-VEHICLE STUDY (references/Systemic_Scaling
# _of_Powertrain_Models_with_Youla_Driver_Control.pdf), not a trim of Phase 1.
# It ends inside a native idle: 0 mph from t = 333 onward.
SEGMENT_END_S = 340         # inclusive
# Raw t from which the trace is already at 0 mph — the evidence that the cut
# needs no end treatment.  Asserted at generation time.
SEGMENT_IDLE_FROM_S = 333

# ── Scaling ─────────────────────────────────────────────────────────────────
PEAK_MPH = 56.7             # the segment peak, at t = 240 s
TARGET_PEAK_MPS = 3.0       # rig flywheel surface speed at that peak
SCALE_MPH_TO_MPS = TARGET_PEAK_MPS / PEAK_MPH

# ── Emitted time base ───────────────────────────────────────────────────────
# The profile is shifted so it starts at t = PROFILE_START_S in SIM time:
# EMS_RUN_ENTRY_S is 3.0 s (the MODE_SAFE settle plus the staged bring-up), and
# 2 more seconds inside Run before the cycle moves mirrors the `ems-y-*`
# scenarios' EMS_Y_START_S.  `piecewise()` clamps before the first point, and
# the FTP starts at rest, so t < PROFILE_START_S is commanded 0.0 m/s anyway.
PROFILE_START_S = 5.0

# ── Decimation ──────────────────────────────────────────────────────────────
# Absolute tolerance, in m/s, on the piecewise-linear reconstruction of a
# dropped point.  Deliberately at the float-noise floor rather than at any
# physically-motivated value: this is a redundancy removal, not a smoothing.
COLLINEAR_TOL = 1.0e-12
# Hard gate on the measured worst-case reconstruction error over ALL original
# samples.  A generator run that cannot meet this must fail loudly rather than
# emit a quietly-different stimulus.
RECON_ERR_MAX = 1.0e-9

OUT_REL = os.path.join("tools", "ftp75_profile.py")
OUT_PATH = os.path.join(REPO_ROOT, OUT_REL)


def read_raw(path):
    """(rows, sha256) where rows is [(t_int, mph_float), ...] in file order.

    Format (PROVENANCE.md): two header lines, then tab-delimited `t<TAB>mph`.
    CRLF line endings; parsed as text with universal newlines."""
    with open(path, "rb") as fh:
        blob = fh.read()
    digest = hashlib.sha256(blob).hexdigest()
    text = blob.decode("ascii")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    rows = []
    for lineno, line in enumerate(lines[2:], start=3):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            raise ValueError("%s:%d: expected 't<TAB>mph', got %r"
                             % (path, lineno, line))
        try:
            t = int(parts[0].strip())
            mph = float(parts[1].strip())
        except ValueError:
            raise ValueError("%s:%d: non-numeric row %r" % (path, lineno, line))
        rows.append((t, mph))
    return rows, digest


def slice_segment(rows):
    """Rows with 0 <= t <= SEGMENT_END_S, asserted contiguous, 1 Hz and
    ending at rest.

    The end-at-rest assertion is the one that earns its keep: it is the whole
    justification for appending no ramp-down tail, and a future re-slice that
    cut mid-motion would otherwise silently hand the firmware a step to zero
    on the way into Finish."""
    out = [(t, mph) for (t, mph) in rows if 0 <= t <= SEGMENT_END_S]
    if not out:
        raise ValueError("no segment rows found")
    for i, (t, _mph) in enumerate(out):
        if t != i:
            raise ValueError("segment slice is not a contiguous 1 Hz series: "
                             "row %d carries t=%d" % (i, t))
    tail = [mph for (t, mph) in out if t >= SEGMENT_IDLE_FROM_S]
    if not tail or any(mph != 0.0 for mph in tail):
        raise ValueError(
            "the t = %d..%d s tail is not at rest (%r) — the segment no longer "
            "ends inside a native idle, so cutting it here would step the "
            "setpoint to zero mid-motion. Re-derive the end treatment before "
            "moving SEGMENT_END_S."
            % (SEGMENT_IDLE_FROM_S, SEGMENT_END_S, tail))
    return out


def decimate_collinear(points, tol=COLLINEAR_TOL):
    """Drop interior points the piecewise-linear reconstruction recovers.

    Greedy: a point is kept when the segment from the LAST KEPT point to the
    NEXT point does not reproduce it within `tol`.  Anchors (first and last)
    are always kept.  The caller re-verifies the result against every original
    sample — this routine is an optimizer, not the correctness argument."""
    if len(points) <= 2:
        return list(points)
    keep = [points[0]]
    for i in range(1, len(points) - 1):
        t0, v0 = keep[-1]
        t1, v1 = points[i]
        t2, v2 = points[i + 1]
        span = t2 - t0
        if span <= 0:
            keep.append(points[i])
            continue
        v_lin = v0 + (v2 - v0) * (t1 - t0) / span
        if abs(v_lin - v1) > tol:
            keep.append(points[i])
    keep.append(points[-1])
    return keep


def piecewise(profile, t):
    """Local copy of hil_plant_sim.piecewise(), so verification uses the SAME
    interpolation the simulator will.  Kept as a copy rather than an import:
    this generator must run without importing the simulator (and its socket /
    argparse surface) at all."""
    if t <= profile[0][0]:
        return float(profile[0][1])
    for (t0, v0), (t1, v1) in zip(profile, profile[1:]):
        if t <= t1:
            span = t1 - t0
            if span <= 0:
                return float(v1)
            return float(v0) + (float(v1) - float(v0)) * (t - t0) / span
    return float(profile[-1][1])


def max_reconstruction_error(reduced, full):
    """Worst |reduced(t) - v| over every ORIGINAL sample."""
    worst = 0.0
    worst_t = None
    for t, v in full:
        err = abs(piecewise(reduced, t) - v)
        if err > worst:
            worst, worst_t = err, t
    return worst, worst_t


def render_module(reduced, full, digest, worst_err, worst_t):
    """The generated tools/ftp75_profile.py source text."""
    peak_v = max(v for _t, v in full)
    # `full` is ALREADY shifted, so this is the EMITTED-table time; the raw time
    # is it minus PROFILE_START_S.  Confusing the two is exactly the
    # transcription class this generator exists to remove.
    peak_t_out = next(t for t, v in full if v == peak_v)
    peak_t_raw = peak_t_out - PROFILE_START_S
    lines = []
    A = lines.append
    A('"""FTP-75 first %d s, rescaled to this rig — GENERATED FILE, DO NOT EDIT.'
      % SEGMENT_END_S)
    A("")
    A("Regenerate with:")
    A("    .venv_hil/Scripts/python.exe tools/gen_ftp75_profile.py --force")
    A("")
    A("SOURCE")
    A("    %s" % SOURCE_URL)
    A("    committed verbatim at %s" % RAW_REL.replace(os.sep, "/"))
    A("    sha256 %s" % digest)
    A("    fetched %s, %d bytes" % (FETCH_DATE, RAW_SIZE))
    A("")
    A("SLICE")
    A("    Raw t = 0..%d s inclusive, %d samples at 1 Hz — the segment of the"
      % (SEGMENT_END_S, len(full)))
    A("    scaled-vehicle study references/Systemic_Scaling_of_Powertrain_")
    A("    Models_with_Youla_Driver_Control.pdf, NOT a trim of Phase 1 (which")
    A("    runs to t = 505 s).  The FTP's 10-minute soak is not in the raw")
    A("    file; its `t` runs continuously, so the segment is taken by time.")
    A("    t = %d falls in a NATIVE idle segment (0 mph from t = %d), so the"
      % (SEGMENT_END_S, SEGMENT_IDLE_FROM_S))
    A("    table ends at rest and carries no synthetic ramp-down tail.")
    A("")
    A("SCALE")
    A("    v_mps = mph * %s / %s = mph * %r"
      % (TARGET_PEAK_MPS, PEAK_MPH, SCALE_MPH_TO_MPS))
    A("    chosen so the cycle peak (%g mph at raw t = %g s, emitted t = %g s)"
      % (peak_v / SCALE_MPH_TO_MPS, peak_t_raw, peak_t_out))
    A("    lands on %g m/s, the top of the range this bench has driven"
      % TARGET_PEAK_MPS)
    A("    (CLAUDE.md fw v16, ML0169).  No dynamic-similarity claim is made.")
    A("")
    A("TIME BASE")
    A("    Shifted by +%g s, so the cycle starts %g s into Run"
      % (PROFILE_START_S, PROFILE_START_S))
    A("    (EMS_RUN_ENTRY_S = 3.0).  Table spans t = %r .. %r s."
      % (reduced[0][0], reduced[-1][0]))
    A("")
    A("REDUCTION")
    A("    %d raw samples -> %d points by exact collinear decimation"
      % (len(full), len(reduced)))
    A("    (tolerance %g m/s).  Worst reconstruction error against EVERY"
      % COLLINEAR_TOL)
    A("    original sample: %.3g m/s%s."
      % (worst_err, "" if worst_t is None else " (at raw t = %g s)"
         % (worst_t - PROFILE_START_S)))
    A("    The reduction saves work in hil_plant_sim.piecewise(); it does not")
    A("    change the stimulus.")
    A('"""')
    A("")
    A("# (t_seconds, v_setpoint_mps) — piecewise-linear, consumed as a")
    A("# scenario's `ems_v_profile` (hil_plant_sim.SCENARIOS).")
    A("FTP75_PROFILE = [")
    for t, v in reduced:
        A("    (%r, %r)," % (float(t), float(v)))
    A("]")
    A("")
    A("# Convenience constants, all DERIVED from the table above.")
    A("FTP75_T_START = %r" % float(reduced[0][0]))
    A("FTP75_T_END = %r" % float(reduced[-1][0]))
    A("FTP75_PEAK_MPS = %r" % float(peak_v))
    A("FTP75_PEAK_T = %r" % float(peak_t_out))
    A("FTP75_POINTS = %d" % len(reduced))
    A("FTP75_RAW_SAMPLES = %d" % len(full))
    A("FTP75_RAW_SHA256 = %r" % digest)
    A("FTP75_SCALE_MPH_TO_MPS = %r" % SCALE_MPH_TO_MPS)
    A("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=OUT_PATH,
                    help="output module path (default %s)"
                         % OUT_REL.replace(os.sep, "/"))
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing output file")
    ap.add_argument("--dry-run", action="store_true",
                    help="report the reduction and write nothing")
    args = ap.parse_args(argv)

    if not os.path.isfile(RAW_PATH):
        ap.error("raw data missing: %s (see references/drive_cycles/"
                 "PROVENANCE.md)" % RAW_PATH)
    rows, digest = read_raw(RAW_PATH)
    if digest != RAW_SHA256:
        ap.error("raw data sha256 mismatch for %s\n  expected %s\n  got      %s\n"
                 "  The committed EPA file has changed. Do not regenerate against "
                 "an unverified input — re-fetch from %s and update PROVENANCE.md "
                 "and RAW_SHA256 together."
                 % (RAW_PATH, RAW_SHA256, digest, SOURCE_URL))

    segment = slice_segment(rows)
    full = [(float(t) + PROFILE_START_S, float(mph) * SCALE_MPH_TO_MPS)
            for (t, mph) in segment]
    reduced = decimate_collinear(full)
    worst_err, worst_t = max_reconstruction_error(reduced, full)
    if worst_err > RECON_ERR_MAX:
        ap.error("decimation error %.3g m/s exceeds RECON_ERR_MAX %g — refusing "
                 "to emit a table that is not the cycle" % (worst_err, RECON_ERR_MAX))

    peak_v = max(v for _t, v in full)
    print("[ftp75] raw          %s (%d bytes, sha256 %s...)"
          % (RAW_REL.replace(os.sep, "/"), RAW_SIZE, digest[:16]))
    print("[ftp75] segment      %d samples, raw t = 0..%d s (study segment; "
          "idle from t = %d)" % (len(segment), SEGMENT_END_S, SEGMENT_IDLE_FROM_S))
    print("[ftp75] scale        mph * %r  (peak %g mph -> %g m/s)"
          % (SCALE_MPH_TO_MPS, peak_v / SCALE_MPH_TO_MPS, peak_v))
    print("[ftp75] shifted to   t = %g .. %g s"
          % (reduced[0][0], reduced[-1][0]))
    print("[ftp75] decimation   %d -> %d points, worst reconstruction error "
          "%.3g m/s" % (len(full), len(reduced), worst_err))

    text = render_module(reduced, full, digest, worst_err, worst_t)
    if args.dry_run:
        print("[ftp75] --dry-run: nothing written")
        return 0
    if os.path.exists(args.out) and not args.force:
        ap.error("%s already exists; pass --force to overwrite" % args.out)
    # utf-8 + LF, explicitly: the docstring carries em-dashes, and letting the
    # platform pick either would make the output non-deterministic across
    # machines — the property this generator exists to guarantee.
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("[ftp75] wrote        %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
