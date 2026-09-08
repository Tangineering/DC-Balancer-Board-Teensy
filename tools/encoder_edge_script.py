#!/usr/bin/env python3
"""
encoder_edge_script.py - encoder edge-list generator for the host-native
encoder-defect harness (WORK_QUEUE section 7d, opened 2026-09-08).

WHAT THIS IS
    A TRUE surface-velocity trajectory v(t) is stepped at 1 kHz from an I_cmd
    stream through the plant's own mechanical law

        m_eff * dv/dt = K_F * I_cmd - sign(v) * F_c - b_eff * v

    and the wheel position x(t) = integral(v) is converted into the CHANGE
    events the two optical channels would produce.  The output is a sorted list
    of (t_us, channel, level) events plus a JSON defect manifest that names
    every altered edge by slot index and time.

    The four mechanical constants are IMPORTED from tools/hil_plant_sim.py and
    are never re-typed here (the SOC_BAND_DRAIN_SCENARIOS hand-mirror defect of
    2026-09-01 is the precedent).  The encoder geometry is asserted against the
    firmware's own #defines by grep-and-compare at run time, the same pattern as
    the pinmap audit - a silent divergence between this generator and the .ino
    would make every edge time wrong by a scale factor.

RELATIONSHIP TO test/encoder_defect_harness.cpp
    The C++ harness does NOT read this generator's output.  It closes the drive
    loop on the firmware's own speed estimate, so its wheel position cannot be
    known ahead of time and its edges must be emitted incrementally from the
    live x(t).  It therefore carries its own port of the geometry below
    (emit_channel_level() / the level law), which is pinned against this file by
    `--emit-vectors` + the harness's `--verify` mode.

    This generator is the OFFLINE reference: it produces the edge scripts and
    manifests for inspection, for the open-loop cases, and for the follow-on
    physical pulse generator on pins 14/15 (WORK_QUEUE 7d deliverable 5).

GEOMETRY (all of it)
    u  = x / pitch                       wheel position in slot pitches
    A high  <=>  frac(u)            < 0.5
    B high  <=>  frac(u - phi)      < 0.5      phi = phase_offset_deg / 360

    phi = 0.25 is the nominal quarter-pitch lag: A leads B in the forward
    direction on this mount (the two sensors were physically swapped when the
    90-slot wheel was installed - see the doEncoderB() phase-tap comment).
    Slot index of an event = floor(u) at its crossing.

USAGE
    python tools/encoder_edge_script.py --help
    python tools/encoder_edge_script.py --profile ramp --duration 6.0 \
        --out logs/encoder_harness/nominal
    python tools/encoder_edge_script.py --profile cruise --cruise-i 3.0 \
        --missing-slots 40 --missing-run 3 --out logs/encoder_harness/miss3

Stdlib only.  ASCII output only.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from hil_plant_sim import (  # noqa: E402  (path set above)
    B_EFF,
    F_COULOMB,
    K_F,
    M_EFF,
    V_STICTION,
)

INO_PATH = os.path.join(_REPO_ROOT, "teensy_controller", "teensy_controller.ino")

# Encoder geometry.  These two are ASSERTED against the .ino at run time by
# assert_geometry_against_ino(); they are declared here only so that a caller
# that imports this module (the pytest suite) has the values without a grep.
ENCODER_SLOTS_PER_REV = 90.0
FLYWHEEL_RADIUS_M = 0.0762
SLOT_PITCH_M = (2.0 * math.pi * FLYWHEEL_RADIUS_M) / ENCODER_SLOTS_PER_REV

CH_A = "A"
CH_B = "B"

DT_S = 1.0e-3  # the plant / control tick


# ---------------------------------------------------------------------------
# 1. Geometry assertion against the firmware
# ---------------------------------------------------------------------------

def _grep_define_float(text: str, name: str) -> float:
    """Return the float literal of `#define <name> <value>f` in `text`."""
    m = re.search(
        r"^\s*#define\s+" + re.escape(name) + r"\s+([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)f?",
        text,
        re.MULTILINE,
    )
    if m is None:
        raise AssertionError("encoder_edge_script: no #define %s found in the .ino" % name)
    return float(m.group(1))


def assert_geometry_against_ino(ino_path: str = INO_PATH) -> dict:
    """Grep the firmware's geometry #defines and compare them with this module.

    Raises AssertionError on any disagreement.  Returns the parsed values.
    """
    with open(ino_path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    slots = _grep_define_float(text, "ENCODER_SLOTS_PER_REV")
    radius = _grep_define_float(text, "FLYWHEEL_RADIUS_M")

    if abs(slots - ENCODER_SLOTS_PER_REV) > 1e-6:
        raise AssertionError(
            "encoder_edge_script: ENCODER_SLOTS_PER_REV is %g in the .ino but %g here"
            % (slots, ENCODER_SLOTS_PER_REV)
        )
    if abs(radius - FLYWHEEL_RADIUS_M) > 1e-9:
        raise AssertionError(
            "encoder_edge_script: FLYWHEEL_RADIUS_M is %g in the .ino but %g here"
            % (radius, FLYWHEEL_RADIUS_M)
        )
    pitch = (2.0 * math.pi * radius) / slots
    if abs(pitch - SLOT_PITCH_M) > 1e-12:
        raise AssertionError("encoder_edge_script: slot pitch mismatch")
    return {
        "ENCODER_SLOTS_PER_REV": slots,
        "FLYWHEEL_RADIUS_M": radius,
        "ENC_SLOT_PITCH_M": pitch,
    }


# ---------------------------------------------------------------------------
# 2. Mechanical law (the plant's own, constants imported)
# ---------------------------------------------------------------------------

def step_velocity(v: float, i_cmd: float, dt: float = DT_S) -> float:
    """One forward-Euler step of m_eff*dv/dt = K_F*i - sign(v)*F_c - b_eff*v.

    THE LAW IS THE PLANT'S, NOT A RE-DERIVATION.  This is a verbatim transcription
    of the `k_air == 0.0` (rig-profile) branch of `PlantState.step` in
    `tools/hil_plant_sim.py`, which is the reference the firmware faces on the HIL
    bench.  Three details are load-bearing and were WRONG in an earlier re-derivation:

    1. The static branch is `abs(v) < V_STICTION` (not `abs(v) > V_STICTION` for the
       moving branch), so `abs(v) == V_STICTION` is a MOVING sample.
    2. Inside the static deadband with `abs(f_drive) <= F_COULOMB` the plant sets
       `f_net = 0` AND `v = 0` outright — the body is held, the viscous term does not
       act, and a sub-stiction velocity is deleted rather than decayed.
    3. The zero-crossing inhibit exists only in the MOVING branch and is gated on
       `f_drive == 0.0` EXACTLY, not on `abs(f_drive) <= F_COULOMB`.  Under a small
       non-zero drive the plant lets friction carry the body through zero.

    `tools/test_encoder_edge_script.py::test_step_velocity_matches_plant_reference`
    steps this function and `PlantState.step` from identical states and asserts the
    trajectories are bit-identical.
    """
    f_drive = K_F * i_cmd
    if abs(v) < V_STICTION:
        # Static-friction deadband: no breakaway until the drive exceeds F_c.
        if abs(f_drive) <= F_COULOMB:
            return 0.0
        f_net = f_drive - (F_COULOMB if f_drive > 0 else -F_COULOMB) - B_EFF * v
    else:
        f_sign = 1.0 if v > 0 else -1.0
        f_net = f_drive - f_sign * F_COULOMB - B_EFF * v
        # Do not let friction alone push the body through zero within one tick.
        v_try = v + (f_net / M_EFF) * dt
        if f_drive == 0.0 and (v_try * v) < 0.0:
            return 0.0
    return v + (f_net / M_EFF) * dt


def integrate_trajectory(i_cmd_stream, dt: float = DT_S, v0: float = 0.0):
    """Return (v_list, x_list): v at each tick boundary and the position after it.

    v_list[k] is the velocity DURING tick k (i.e. entering it); x_list[k] is the
    position at the END of tick k.  x_list[-1] is the total distance.
    """
    v = v0
    x = 0.0
    vs = []
    xs = []
    for i_cmd in i_cmd_stream:
        vs.append(v)
        v_next = step_velocity(v, i_cmd, dt)
        x += 0.5 * (v + v_next) * dt  # trapezoid over the tick
        xs.append(x)
        v = v_next
    return vs, xs


# ---------------------------------------------------------------------------
# 3. Ideal edge list
# ---------------------------------------------------------------------------

def channel_level(u: float, phi: float) -> int:
    """Level of a channel whose rising edges sit at u = n + phi, 50 % duty."""
    return 1 if ((u - phi) % 1.0) < 0.5 else 0


def _crossings_in_segment(u0: float, u1: float, phi: float):
    """Thresholds of one channel crossed while u goes u0 -> u1 (either sign).

    Yields (u_threshold, frac) pairs in traversal order, where `frac` is the
    fraction of the segment at which the crossing occurs.
    """
    if u1 == u0:
        return
    lo, hi = (u0, u1) if u1 > u0 else (u1, u0)
    # Thresholds are at u = phi + k/2 for integer k.
    k_start = math.floor((lo - phi) * 2.0) + 1
    k_end = math.ceil((hi - phi) * 2.0) - 1
    thresholds = []
    for k in range(k_start, k_end + 1):
        ut = phi + 0.5 * k
        if lo < ut <= hi:
            thresholds.append(ut)
    if u1 < u0:
        thresholds.reverse()
    span = u1 - u0
    for ut in thresholds:
        yield ut, (ut - u0) / span


def ideal_edges(xs, dt: float = DT_S, pitch: float = SLOT_PITCH_M,
                phase_offset_deg: float = 90.0):
    """Build the ideal CHANGE-event list from a position trajectory.

    Returns a list of dicts: {t_us, channel, level, slot, u}.
    Events are sorted by t_us; within a tick they are in traversal order.
    """
    phi = phase_offset_deg / 360.0
    events = []
    u_prev = 0.0
    lvl = {CH_A: channel_level(0.0, 0.0), CH_B: channel_level(0.0, phi)}
    for k, x in enumerate(xs):
        u = x / pitch
        t0 = k * dt
        seg = []
        for ch, off in ((CH_A, 0.0), (CH_B, phi)):
            for ut, frac in _crossings_in_segment(u_prev, u, off):
                seg.append((frac, ch, ut))
        seg.sort(key=lambda e: e[0])
        for frac, ch, ut in seg:
            new_level = 1 - lvl[ch]
            lvl[ch] = new_level
            t_us = int(round((t0 + frac * dt) * 1e6))
            events.append({
                "t_us": t_us,
                "channel": ch,
                "level": new_level,
                "slot": int(math.floor(ut)),
                "u": ut,
            })
        u_prev = u
    events.sort(key=lambda e: (e["t_us"], e["channel"]))
    return events


# ---------------------------------------------------------------------------
# 4. Defect scripts.  Each is applied to the IDEAL list before emission and
#    records every altered edge in the manifest.
# ---------------------------------------------------------------------------

def apply_missing_slots(events, k: int, n: int = 1):
    """Delete slots k .. k+n-1 from BOTH channels.  Produces an (n+1)T period."""
    kept, removed = [], []
    for e in events:
        if k <= e["slot"] < k + n:
            removed.append({"t_us": e["t_us"], "channel": e["channel"],
                            "level": e["level"], "slot": e["slot"], "action": "removed"})
        else:
            kept.append(e)
    return kept, removed


def apply_bounce(events, k: int, spacing_us: int):
    """A +1/-1/+1 tooth: the A rising edge of slot k gains a fall/rise pair.

    The channel-A level after the triple is unchanged (still high), so the
    quadrature decode sees one extra fall and one extra rise inside one pitch.
    """
    out, altered = [], []
    hit = False
    for e in events:
        out.append(e)
        if (not hit) and e["channel"] == CH_A and e["level"] == 1 and e["slot"] == k:
            hit = True
            for j, lv in ((1, 0), (2, 1)):
                extra = {
                    "t_us": e["t_us"] + j * spacing_us,
                    "channel": CH_A,
                    "level": lv,
                    "slot": k,
                    "u": e["u"],
                }
                out.append(extra)
                altered.append({"t_us": extra["t_us"], "channel": CH_A, "level": lv,
                                "slot": k, "action": "inserted"})
    if not hit:
        raise ValueError("apply_bounce: no A-rising edge at slot %d in this trajectory" % k)
    out.sort(key=lambda e: (e["t_us"], e["channel"]))
    return out, altered


def apply_jitter(events, amp_us: float, seed: int):
    """Zero-mean uniform jitter on every edge, applied per channel then merged.

    Jittering per channel and re-sorting per channel keeps each channel's
    level sequence alternating (a physical channel cannot emit two rises in a
    row); the inter-channel order is free to swap, which is exactly the
    quadrature corruption the 2.2 kOhm front end produces.
    """
    rng = random.Random(seed)
    altered = []
    by_ch = {CH_A: [], CH_B: []}
    for e in events:
        d = rng.uniform(-amp_us, amp_us)
        e2 = dict(e)
        e2["t_us"] = int(round(e["t_us"] + d))
        if e2["t_us"] < 0:
            e2["t_us"] = 0
        by_ch[e["channel"]].append(e2)
        altered.append({"t_us": e2["t_us"], "channel": e["channel"], "level": e["level"],
                        "slot": e["slot"], "action": "shifted",
                        "delta_us": e2["t_us"] - e["t_us"]})
    out = []
    for ch in (CH_A, CH_B):
        chan = sorted(by_ch[ch], key=lambda e: e["t_us"])
        # Re-impose alternation: the sort may have swapped a rise/fall pair.
        lvl = 1 - (chan[0]["level"] if chan else 0)
        for e in chan:
            lvl = 1 - lvl
            e["level"] = lvl
        out.extend(chan)
    out.sort(key=lambda e: (e["t_us"], e["channel"]))
    return out, altered


def apply_dropout(events, t_start_us: int, t_end_us: int):
    """Delete every edge inside [t_start_us, t_end_us) - the reading-age path."""
    kept, removed = [], []
    for e in events:
        if t_start_us <= e["t_us"] < t_end_us:
            removed.append({"t_us": e["t_us"], "channel": e["channel"],
                            "level": e["level"], "slot": e["slot"], "action": "removed"})
        else:
            kept.append(e)
    return kept, removed


# ---------------------------------------------------------------------------
# 5. I_cmd profiles (open loop - the harness closes the loop itself)
# ---------------------------------------------------------------------------

def profile_stream(name: str, duration_s: float, cruise_i: float, dt: float = DT_S):
    n = int(round(duration_s / dt))
    out = []
    for k in range(n):
        t = k * dt
        if name == "cruise":
            i = cruise_i
        elif name == "ramp":
            i = cruise_i * min(1.0, t / max(dt, 0.25 * duration_s))
        elif name == "step":
            i = 0.0 if t < 0.1 * duration_s else cruise_i
        elif name == "coast":
            i = cruise_i if t < 0.5 * duration_s else 0.0
        else:
            raise ValueError("unknown profile '%s'" % name)
        out.append(i)
    return out


# ---------------------------------------------------------------------------
# 6. Emission
# ---------------------------------------------------------------------------

def _atomic_write(path: str, render):
    """Write via `path + '.tmp'` then os.replace, so an interrupted or failed run
    never leaves a truncated file at the real name (a partial edge CSV or manifest
    is indistinguishable from a short run to every consumer downstream)."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="ascii", newline="") as fh:
            render(fh)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_edges_csv(path: str, events):
    def render(fh):
        fh.write("t_us,channel,level,slot\n")
        for e in events:
            fh.write("%d,%s,%d,%d\n" % (e["t_us"], e["channel"], e["level"], e["slot"]))
    _atomic_write(path, render)


def build(profile="cruise", duration_s=6.0, cruise_i=3.0, phase_offset_deg=90.0,
          missing_slot=None, missing_run=1, bounce_slot=None, bounce_spacing_us=300,
          jitter_us=0.0, jitter_seed=1, dropout_start_us=None, dropout_end_us=None,
          ino_path=INO_PATH):
    """Produce (events, manifest) for one parameterised run.  Defects compose."""
    geom = assert_geometry_against_ino(ino_path)
    pitch = geom["ENC_SLOT_PITCH_M"]
    stream = profile_stream(profile, duration_s, cruise_i)
    vs, xs = integrate_trajectory(stream)
    events = ideal_edges(xs, DT_S, pitch, phase_offset_deg)
    n_ideal = len(events)

    altered = []
    defects = {}
    if phase_offset_deg != 90.0:
        defects["phase_offset_deg"] = phase_offset_deg
    if missing_slot is not None:
        events, rm = apply_missing_slots(events, missing_slot, missing_run)
        altered.extend(rm)
        defects["missing_slots"] = {"k": missing_slot, "n": missing_run}
    if bounce_slot is not None:
        events, al = apply_bounce(events, bounce_slot, bounce_spacing_us)
        altered.extend(al)
        defects["bounce_slots"] = {"k": bounce_slot, "spacing_us": bounce_spacing_us}
    if jitter_us > 0.0:
        events, al = apply_jitter(events, jitter_us, jitter_seed)
        altered.extend(al)
        defects["edge_jitter_us"] = {"amp_us": jitter_us, "seed": jitter_seed}
    if dropout_start_us is not None and dropout_end_us is not None:
        events, rm = apply_dropout(events, dropout_start_us, dropout_end_us)
        altered.extend(rm)
        defects["dropout_window"] = {"start_us": dropout_start_us, "end_us": dropout_end_us}

    manifest = {
        "generator": "tools/encoder_edge_script.py",
        "geometry": geom,
        "mechanical_constants": {
            "M_EFF": M_EFF, "K_F": K_F, "F_COULOMB": F_COULOMB,
            "B_EFF": B_EFF, "V_STICTION": V_STICTION,
            "source": "tools/hil_plant_sim.py (imported, never re-typed)",
        },
        "profile": {"name": profile, "duration_s": duration_s, "cruise_i_a": cruise_i,
                    "dt_s": DT_S},
        "trajectory": {"v_final_mps": vs[-1] if vs else 0.0,
                       "v_max_mps": max(vs) if vs else 0.0,
                       "distance_m": xs[-1] if xs else 0.0,
                       "slots_travelled": (xs[-1] / pitch) if xs else 0.0},
        "phase_offset_deg": phase_offset_deg,
        "jitter_seed": jitter_seed,
        "defects": defects,
        "edge_counts": {"ideal": n_ideal, "emitted": len(events),
                        "altered": len(altered)},
        "altered_edges": altered,
    }
    return events, manifest


def main(argv=None):
    p = argparse.ArgumentParser(description="Encoder edge-list generator (WORK_QUEUE 7d).")
    p.add_argument("--profile", default="cruise",
                   choices=["cruise", "ramp", "step", "coast"])
    p.add_argument("--duration", type=float, default=6.0, help="seconds")
    p.add_argument("--cruise-i", type=float, default=3.0, help="I_cmd amps")
    p.add_argument("--phase-offset-deg", type=float, default=90.0)
    p.add_argument("--missing-slots", type=int, default=None, metavar="K")
    p.add_argument("--missing-run", type=int, default=1, metavar="N")
    p.add_argument("--bounce-slots", type=int, default=None, metavar="K")
    p.add_argument("--bounce-spacing-us", type=int, default=300)
    p.add_argument("--jitter-us", type=float, default=0.0)
    p.add_argument("--jitter-seed", type=int, default=1)
    p.add_argument("--dropout-start-us", type=int, default=None)
    p.add_argument("--dropout-end-us", type=int, default=None)
    p.add_argument("--out", default=None,
                   help="output stem; writes <stem>_edges.csv and <stem>_manifest.json")
    a = p.parse_args(argv)

    events, manifest = build(
        profile=a.profile, duration_s=a.duration, cruise_i=a.cruise_i,
        phase_offset_deg=a.phase_offset_deg,
        missing_slot=a.missing_slots, missing_run=a.missing_run,
        bounce_slot=a.bounce_slots, bounce_spacing_us=a.bounce_spacing_us,
        jitter_us=a.jitter_us, jitter_seed=a.jitter_seed,
        dropout_start_us=a.dropout_start_us, dropout_end_us=a.dropout_end_us,
    )

    print("geometry OK: %g slots/rev, r = %g m, pitch = %.6f mm"
          % (manifest["geometry"]["ENCODER_SLOTS_PER_REV"],
             manifest["geometry"]["FLYWHEEL_RADIUS_M"],
             manifest["geometry"]["ENC_SLOT_PITCH_M"] * 1e3))
    print("trajectory: v_max %.3f m/s, %.3f m, %.1f slots"
          % (manifest["trajectory"]["v_max_mps"],
             manifest["trajectory"]["distance_m"],
             manifest["trajectory"]["slots_travelled"]))
    print("edges: %d ideal, %d emitted, %d altered"
          % (manifest["edge_counts"]["ideal"], manifest["edge_counts"]["emitted"],
             manifest["edge_counts"]["altered"]))

    if a.out:
        d = os.path.dirname(os.path.abspath(a.out))
        if d and not os.path.isdir(d):
            os.makedirs(d)
        write_edges_csv(a.out + "_edges.csv", events)
        _atomic_write(a.out + "_manifest.json",
                      lambda fh: json.dump(manifest, fh, indent=2, sort_keys=True))
        print("wrote %s_edges.csv and %s_manifest.json" % (a.out, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
