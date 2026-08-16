#!/usr/bin/env python3
"""Generate a synthetic, realistic .BLG bench log for pipeline testing.

No real .BLG capture exists yet, so this writer produces one in exactly the
format documented in tools/decode_benchlog.py's docstring (32-B header,
sentinel trailer; 52-B records for format v1/v2, 68-B records with four
extra voltage channels for format v3) with plausible-looking signal
content, for exercising ingest_log.py / common.py end to end.

Usage:
  python make_test_blg.py [-o logs/TEST0001.BLG] [--seed 0] [--truncate]
  python make_test_blg.py --v3 [-o logs/TEST0002.BLG] [--seed 0]
  python make_test_blg.py --v4 [-o logs/TEST0003.BLG] [--seed 0]
  python make_test_blg.py --v4 --profile-amp 6.0 --profile-b 0.15
  python make_test_blg.py --v5 [-o logs/TEST0004.BLG] [--seed 0]

--v3 writes the format-v3 header/record layout (adds V_fc, V_batt, V_chg,
V_rgn); default is the v1/v2 layout, selected as usual via --header-v1 /
fw_version.

--v4 writes the format-v4 header (record layout is unchanged from v3, so
--v4 implies the v3 68 B record layout): header byte 7 becomes a
param-valid flags byte (bit0=profileAmp, bit1=profileB) and bytes 20-27
carry the two LE f32 profile parameters, per --profile-amp/--profile-b
(both default to a valid, plausible value; pass --profile-amp-invalid /
--profile-b-invalid to clear the corresponding valid bit and exercise the
decoder's None-when-invalid path). Mutually exclusive with --header-v1,
--v3, and --v5.

--v5 writes the format-v5 header/record layout (header identical to v4;
record is the v3/v4 68 B record with u_unsat, drive_x0 appended, 76 B
total). Implies the v4 header (profileAmp/profileB always valid; use
--profile-amp-invalid/--profile-b-invalid to clear a bit as with --v4).
Synthetic u_unsat sweeps between +/-15 A (i.e. crosses the +/-12 A rail,
to exercise the saturation-shading path) and drive_x0 is a slow bounded
oscillation. Flags bit4/bit5 (Youla drive/share controller active) both
default ON for --v5, so a fresh synthetic file exercises the
Youla-controller-active decode path by default; pass --flags-bit4-off /
--flags-bit5-off to force either off instead, and combine as needed to
cover all four bit4/bit5 combinations across multiple invocations.
Mutually exclusive with --header-v1 and --v3.

--truncate drops the trailer and cuts off the last ~30% of records (plus a
partial trailing record), to exercise the truncated-file / no-trailer path
in the decoder.
"""
import argparse
import struct
from pathlib import Path

import numpy as np

MAGIC = b"BLG1"
HEADER_FMT = "<4sBBBBIIH"
HEADER_SIZE = 32
RECORD_FMT = "<I10fHBBBB2x"
RECORD_SIZE = 52
RECORD_FMT_V3 = "<I14fHBBBB2x"
RECORD_SIZE_V3 = 68
RECORD_FMT_V5 = "<I14fHBBBB2xff"
RECORD_SIZE_V5 = 76
TRAILER_FMT = "<IIIBBI"

DURATION_S = 40.0
RATE_HZ = 1000
N_SAMPLES = int(DURATION_S * RATE_HZ)

START_MILLIS = 123_456
START_MICROS = 987_654
K_DROOP_X1000 = 300
PROFILE_TYPE = 4  # DC (drive-cycle) bit, per the header docstring


def _trapezoid(t, t0, ramp_up, cruise, ramp_down, v_hi):
    """0 -> ramp to v_hi over ramp_up s -> cruise -> ramp back to 0 -> hold."""
    t1 = t0 + ramp_up
    t2 = t1 + cruise
    t3 = t2 + ramp_down
    out = np.zeros_like(t)
    seg = (t >= t0) & (t < t1)
    out[seg] = v_hi * (t[seg] - t0) / ramp_up
    seg = (t >= t1) & (t < t2)
    out[seg] = v_hi
    seg = (t >= t2) & (t < t3)
    out[seg] = v_hi * (1.0 - (t[seg] - t2) / ramp_down)
    seg = t >= t3
    out[seg] = 0.0
    return out


def _lag(x, t, tau_s):
    """First-order lag of x sampled at times t (simple causal one-pole)."""
    y = np.empty_like(x)
    y[0] = x[0]
    for i in range(1, len(x)):
        dt = t[i] - t[i - 1]
        alpha = 1.0 - np.exp(-dt / tau_s) if tau_s > 0 else 1.0
        y[i] = y[i - 1] + alpha * (x[i] - y[i - 1])
    return y


def build_signals(seed, wrap=False):
    rng = np.random.default_rng(seed)
    t = np.arange(N_SAMPLES) / RATE_HZ  # seconds since start

    # v_sp: 0 -> ramp to 3.0 over 5 s -> cruise 15 s -> ramp down 5 s -> 0, hold.
    v_sp = _trapezoid(t, 0.0, 5.0, 15.0, 5.0, 3.0)
    v_act = _lag(v_sp, t, 0.4) + rng.normal(0.0, 0.03, N_SAMPLES)

    # share_sp: 0.5 -> 0.7 at t=10s -> 0.3 at t=25s.
    share_sp = np.full(N_SAMPLES, 0.5)
    share_sp[t >= 10.0] = 0.7
    share_sp[t >= 25.0] = 0.3
    share_act_true = np.clip(_lag(share_sp, t, 0.15), 0.0, 1.0)
    share_act = np.clip(share_act_true + rng.normal(0.0, 0.02, N_SAMPLES),
                         0.0, 1.0)

    i_tot = 1.0 + 0.8 * v_act + rng.normal(0.0, 0.05, N_SAMPLES)
    i_fc = share_act_true * i_tot + rng.normal(0.0, 0.05, N_SAMPLES)
    i_batt = (1.0 - share_act_true) * i_tot + rng.normal(0.0, 0.05, N_SAMPLES)

    # gFC/gBT: slowly varying droop gains within [0.2, 0.9].
    gfc = 0.55 + 0.30 * np.sin(2 * np.pi * t / 23.0) \
        + rng.normal(0.0, 0.01, N_SAMPLES)
    gbt = 0.55 + 0.30 * np.sin(2 * np.pi * t / 31.0 + 1.3) \
        + rng.normal(0.0, 0.01, N_SAMPLES)
    gfc = np.clip(gfc, 0.2, 0.9)
    gbt = np.clip(gbt, 0.2, 0.9)

    v_bus = 17.5 + rng.normal(0.0, 0.05, N_SAMPLES)
    i_cmd = np.clip(2.0 * (v_sp - v_act), -8.0, 8.0)

    # v3-only source/node voltages: plausible, slowly-varying levels with
    # noise. Computed unconditionally (cheap) but only packed into records
    # when the v3 layout is selected.
    v_fc = 12.5 + 0.3 * np.sin(2 * np.pi * t / 17.0) \
        + rng.normal(0.0, 0.02, N_SAMPLES)
    v_batt = 8.0 + 0.15 * np.sin(2 * np.pi * t / 29.0 + 0.5) \
        + rng.normal(0.0, 0.02, N_SAMPLES)
    v_chg = 12.0 + 0.2 * np.sin(2 * np.pi * t / 13.0 + 1.0) \
        + rng.normal(0.0, 0.02, N_SAMPLES)
    v_rgn = 0.5 + 0.1 * np.abs(np.sin(2 * np.pi * t / 9.0)) \
        + rng.normal(0.0, 0.01, N_SAMPLES)

    fault_flags = np.zeros(N_SAMPLES, dtype=np.uint16)

    # ps_phase walks 0..15 over the run.
    ps_phase = np.minimum((t / DURATION_S * 16.0).astype(np.uint8), 15)
    dc_phase = np.full(N_SAMPLES, 0xFF, dtype=np.uint8)
    trap_phase = np.full(N_SAMPLES, 0xFF, dtype=np.uint8)

    # flags = 0x03 normally; velocity chain marked invalid for t in [30,31)s.
    flags = np.full(N_SAMPLES, 0x03, dtype=np.uint8)
    invalid = (t >= 30.0) & (t < 31.0)
    flags[invalid] &= ~0x02 & 0xFF

    # v5-only: u_unsat (drive controller pre-clamp output) swept well past
    # the +/-12 A rails so the saturation-shading path is exercised on both
    # sides, and drive_x0 (Youla drive controller integrator state) as a
    # slow bounded oscillation. Computed unconditionally (cheap) but only
    # packed into records when the v5 layout is selected.
    u_unsat = 15.0 * np.sin(2 * np.pi * t / 20.0) \
        + rng.normal(0.0, 0.05, N_SAMPLES)
    drive_x0 = 3.0 * np.sin(2 * np.pi * t / 33.0 + 0.7) \
        + rng.normal(0.0, 0.02, N_SAMPLES)

    # t_us: nominal +1000/sample with a few microseconds of jitter, always
    # strictly increasing (jitter magnitude << the 1000 us nominal step).
    # With wrap=True the run starts just short of the 2^32 us micros()
    # rollover so it straddles the wrap mid-run -- the decoder and the
    # analysis layer are both wrap-safe and this exercises that path.
    jitter = rng.integers(-3, 4, size=N_SAMPLES)
    jitter[0] = 0
    start_us = (2**32 - int(DURATION_S * 1e6) // 2) if wrap else START_MICROS
    t_us = (start_us + np.arange(N_SAMPLES, dtype=np.int64) * 1000
            + jitter)
    for i in range(1, N_SAMPLES):
        if t_us[i] <= t_us[i - 1]:
            t_us[i] = t_us[i - 1] + 1
    t_us = (t_us & 0xFFFFFFFF).astype(np.uint32)

    return dict(t_us=t_us, share_sp=share_sp, share_act=share_act,
                v_sp=v_sp, v_act=v_act, i_fc=i_fc, i_batt=i_batt,
                gfc=gfc, gbt=gbt, v_bus=v_bus, i_cmd=i_cmd,
                v_fc=v_fc, v_batt=v_batt, v_chg=v_chg, v_rgn=v_rgn,
                u_unsat=u_unsat, drive_x0=drive_x0,
                fault_flags=fault_flags, ps_phase=ps_phase,
                dc_phase=dc_phase, trap_phase=trap_phase, flags=flags)


def pack_header(fw_version=1, header_v1=False, v3=False, v4=False, v5=False,
                 profile_amp=6.0, profile_b=0.15, profile_amp_valid=True,
                 profile_b_valid=True):
    """Format-v2 header (u16 fw_version at offset 18) by default; header_v1
    writes the legacy v1 layout (no fw_version) for decoder back-compat
    testing; v3 writes the format-v3 header (record_size=68), which also
    carries fw_version (v3 always has it, like v2); v4 writes the format-v4
    header (also record_size=68 -- the record layout is unchanged from v3)
    and additionally packs the param-valid flags byte (header offset 7) and
    the profileAmp/profileB LE f32 fields (offsets 20/24); v5 writes the
    format-v5 header, which is byte-identical to v4 (record_size=76 is the
    only difference, and that lives in the record_size byte, not elsewhere
    in the header layout) -- so v5 reuses the v4 param-flags/profileAmp/
    profileB packing verbatim. profile_amp/profile_b are only meaningful
    when v4 or v5 is set; profile_amp_valid/profile_b_valid gate their
    valid bits (set False to exercise the decoder's None-when-invalid path
    with non-zero float bytes still present, mirroring
    test_decode_benchlog.py's amp-only/neither-valid cases)."""
    if sum([header_v1, v3, v4, v5]) > 1:
        raise ValueError("header_v1, v3, v4, and v5 are mutually exclusive")
    version = 1 if header_v1 else (3 if v3 else (5 if v5 else (4 if v4 else 2)))
    record_size = RECORD_SIZE_V5 if v5 else (
        RECORD_SIZE_V3 if (v3 or v4) else RECORD_SIZE)
    param_flags = 0
    if v4 or v5:
        if profile_amp_valid:
            param_flags |= 0x01
        if profile_b_valid:
            param_flags |= 0x02
    hdr = struct.pack(HEADER_FMT, MAGIC, version, record_size, PROFILE_TYPE,
                       param_flags, START_MILLIS, START_MICROS, K_DROOP_X1000)
    if not header_v1:
        hdr += struct.pack("<H", fw_version)
    hdr += b"\x00" * (HEADER_SIZE - len(hdr))
    hdr = bytearray(hdr)
    if v4 or v5:
        struct.pack_into("<ff", hdr, 20, profile_amp, profile_b)
    assert len(hdr) == HEADER_SIZE
    return bytes(hdr)


def pack_record(sig, i, v3=False, v4=False, v5=False):
    """Record layout is identical for v3 and v4 -- v4 only changes the
    header (see pack_header) -- so v4 is accepted here purely for call-site
    symmetry with build_blg() and packs the same RECORD_FMT_V3 as v3. v5
    packs RECORD_FMT_V5: the same fields plus u_unsat/drive_x0 appended."""
    if v5:
        rec = struct.pack(RECORD_FMT_V5, int(sig["t_us"][i]),
                           float(sig["share_sp"][i]), float(sig["share_act"][i]),
                           float(sig["v_sp"][i]), float(sig["v_act"][i]),
                           float(sig["i_fc"][i]), float(sig["i_batt"][i]),
                           float(sig["gfc"][i]), float(sig["gbt"][i]),
                           float(sig["v_bus"][i]), float(sig["i_cmd"][i]),
                           float(sig["v_fc"][i]), float(sig["v_batt"][i]),
                           float(sig["v_chg"][i]), float(sig["v_rgn"][i]),
                           int(sig["fault_flags"][i]), int(sig["ps_phase"][i]),
                           int(sig["dc_phase"][i]), int(sig["trap_phase"][i]),
                           int(sig["flags"][i]), float(sig["u_unsat"][i]),
                           float(sig["drive_x0"][i]))
        assert len(rec) == RECORD_SIZE_V5
        return rec
    if v3 or v4:
        rec = struct.pack(RECORD_FMT_V3, int(sig["t_us"][i]),
                           float(sig["share_sp"][i]), float(sig["share_act"][i]),
                           float(sig["v_sp"][i]), float(sig["v_act"][i]),
                           float(sig["i_fc"][i]), float(sig["i_batt"][i]),
                           float(sig["gfc"][i]), float(sig["gbt"][i]),
                           float(sig["v_bus"][i]), float(sig["i_cmd"][i]),
                           float(sig["v_fc"][i]), float(sig["v_batt"][i]),
                           float(sig["v_chg"][i]), float(sig["v_rgn"][i]),
                           int(sig["fault_flags"][i]), int(sig["ps_phase"][i]),
                           int(sig["dc_phase"][i]), int(sig["trap_phase"][i]),
                           int(sig["flags"][i]))
        assert len(rec) == RECORD_SIZE_V3
        return rec
    rec = struct.pack(RECORD_FMT, int(sig["t_us"][i]),
                       float(sig["share_sp"][i]), float(sig["share_act"][i]),
                       float(sig["v_sp"][i]), float(sig["v_act"][i]),
                       float(sig["i_fc"][i]), float(sig["i_batt"][i]),
                       float(sig["gfc"][i]), float(sig["gbt"][i]),
                       float(sig["v_bus"][i]), float(sig["i_cmd"][i]),
                       int(sig["fault_flags"][i]), int(sig["ps_phase"][i]),
                       int(sig["dc_phase"][i]), int(sig["trap_phase"][i]),
                       int(sig["flags"][i]))
    assert len(rec) == RECORD_SIZE
    return rec


def pack_trailer(records_written, dropped=0, close_reason=1, error_code=0,
                  abandoned=0, v3=False, v4=False, v5=False):
    record_size = RECORD_SIZE_V5 if v5 else (
        RECORD_SIZE_V3 if (v3 or v4) else RECORD_SIZE)
    body = struct.pack(TRAILER_FMT, 0xFFFFFFFF, records_written, dropped,
                        close_reason, error_code, abandoned)
    body += b"\x00" * (record_size - len(body))
    assert len(body) == record_size
    return body


def build_blg(seed, truncate, wrap=False, dropped=0, fw_version=1,
              header_v1=False, v3=False, v4=False, v5=False, profile_amp=6.0,
              profile_b=0.15, profile_amp_valid=True, profile_b_valid=True,
              flags_bit4=None, flags_bit5=None):
    """flags_bit4/flags_bit5 (v5 only): True/False forces that flags bit on
    or off on every record; None (default) defaults to ON for --v5 (Youla
    drive/share controllers active, matching the real firmware's default
    build), applied on top of the base signal's flags byte (0x03, minus the
    deliberate velocity-invalid window)."""
    sig = build_signals(seed, wrap=wrap)
    n = N_SAMPLES
    if truncate:
        n = int(N_SAMPLES * 0.70)
    record_size = RECORD_SIZE_V5 if v5 else (
        RECORD_SIZE_V3 if (v3 or v4) else RECORD_SIZE)

    if v5:
        # None defaults to ON for --v5.
        bit4 = True if flags_bit4 is None else flags_bit4
        bit5 = True if flags_bit5 is None else flags_bit5
        sig = dict(sig)  # shallow copy -- only flags is mutated
        flags = sig["flags"].copy()
        if bit4:
            flags |= 0x10
        else:
            flags &= ~0x10 & 0xFF
        if bit5:
            flags |= 0x20
        else:
            flags &= ~0x20 & 0xFF
        sig["flags"] = flags

    out = bytearray()
    out += pack_header(fw_version=fw_version, header_v1=header_v1, v3=v3,
                        v4=v4, v5=v5, profile_amp=profile_amp,
                        profile_b=profile_b,
                        profile_amp_valid=profile_amp_valid,
                        profile_b_valid=profile_b_valid)
    for i in range(n):
        out += pack_record(sig, i, v3=v3, v4=v4, v5=v5)

    if truncate:
        # Cut off mid-record: a partial trailing record's worth of garbage
        # bytes, and no trailer -- simulates power loss mid-write.
        out += b"\xA5" * (record_size // 2)
    else:
        out += pack_trailer(records_written=n, dropped=dropped, v3=v3, v4=v4,
                             v5=v5)

    return bytes(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default="logs/TEST0001.BLG",
                     help="output .BLG path (default: logs/TEST0001.BLG)")
    ap.add_argument("--seed", type=int, default=0, help="RNG seed")
    ap.add_argument("--wrap", action="store_true",
                     help="start t_us just below the 2^32 micros() rollover "
                          "so the run straddles the wrap")
    ap.add_argument("--dropped", type=int, default=0,
                     help="dropped_count to record in the trailer (default 0)")
    ap.add_argument("--truncate", action="store_true",
                     help="drop the trailer and truncate the last ~30%% of "
                          "records, to exercise the truncated-file path")
    ap.add_argument("--fw-version", type=int, default=1,
                     help="firmware version stamped in the v2 header "
                          "(default 1)")
    ap.add_argument("--header-v1", action="store_true",
                     help="write the legacy format-v1 header (no fw_version) "
                          "for decoder back-compat testing")
    ap.add_argument("--v3", action="store_true",
                     help="write the format-v3 header/record layout "
                          "(adds V_fc, V_batt, V_chg, V_rgn); mutually "
                          "exclusive with --header-v1 and --v4")
    ap.add_argument("--v4", action="store_true",
                     help="write the format-v4 header (profileAmp/profileB "
                          "param-valid flags + LE f32 fields; record layout "
                          "is the unchanged v3 68 B layout); mutually "
                          "exclusive with --header-v1, --v3, and --v5")
    ap.add_argument("--v5", action="store_true",
                     help="write the format-v5 header/record layout "
                          "(header identical to v4; record appends "
                          "u_unsat, drive_x0 -- 76 B total); mutually "
                          "exclusive with --header-v1, --v3, and --v4")
    ap.add_argument("--profile-amp", type=float, default=6.0,
                     help="v4/v5 only: profileAmp value to write "
                          "(default 6.0)")
    ap.add_argument("--profile-b", type=float, default=0.15,
                     help="v4/v5 only: profileB value to write "
                          "(default 0.15)")
    ap.add_argument("--profile-amp-invalid", action="store_true",
                     help="v4/v5 only: clear the profileAmp valid bit (the "
                          "float bytes are still written, to exercise the "
                          "decoder's None-when-invalid path against "
                          "non-zero garbage)")
    ap.add_argument("--profile-b-invalid", action="store_true",
                     help="v4/v5 only: clear the profileB valid bit (same "
                          "rationale as --profile-amp-invalid)")
    ap.add_argument("--flags-bit4-off", action="store_true",
                     help="v5 only: force flags bit4 (Youla drive "
                          "controller active) OFF on every record "
                          "(default: ON)")
    ap.add_argument("--flags-bit4-on", action="store_true",
                     help="v5 only: force flags bit4 ON on every record "
                          "(this is already the default; provided for "
                          "symmetry / explicitness)")
    ap.add_argument("--flags-bit5-off", action="store_true",
                     help="v5 only: force flags bit5 (Youla share "
                          "controller active) OFF on every record "
                          "(default: ON)")
    ap.add_argument("--flags-bit5-on", action="store_true",
                     help="v5 only: force flags bit5 ON on every record "
                          "(this is already the default; provided for "
                          "symmetry / explicitness)")
    args = ap.parse_args()

    if sum([args.header_v1, args.v3, args.v4, args.v5]) > 1:
        raise SystemExit(
            "--header-v1, --v3, --v4, and --v5 are mutually exclusive")
    if args.flags_bit4_off and args.flags_bit4_on:
        raise SystemExit(
            "--flags-bit4-off and --flags-bit4-on are mutually exclusive")
    if args.flags_bit5_off and args.flags_bit5_on:
        raise SystemExit(
            "--flags-bit5-off and --flags-bit5-on are mutually exclusive")

    flags_bit4 = True if args.flags_bit4_on else (
        False if args.flags_bit4_off else None)
    flags_bit5 = True if args.flags_bit5_on else (
        False if args.flags_bit5_off else None)

    data = build_blg(args.seed, args.truncate, wrap=args.wrap,
                     dropped=args.dropped, fw_version=args.fw_version,
                     header_v1=args.header_v1, v3=args.v3, v4=args.v4,
                     v5=args.v5,
                     profile_amp=args.profile_amp, profile_b=args.profile_b,
                     profile_amp_valid=not args.profile_amp_invalid,
                     profile_b_valid=not args.profile_b_invalid,
                     flags_bit4=flags_bit4, flags_bit5=flags_bit5)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)

    print(f"[make_test_blg] wrote {out_path} ({len(data)} bytes, "
          f"truncate={args.truncate}, wrap={args.wrap}, v3={args.v3}, "
          f"v4={args.v4}, v5={args.v5}, seed={args.seed})")


if __name__ == "__main__":
    main()
