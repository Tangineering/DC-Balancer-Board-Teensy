#!/usr/bin/env python3
"""Generate a synthetic, realistic .BLG bench log for pipeline testing.

No real .BLG capture exists yet, so this writer produces one in exactly the
format documented in tools/decode_benchlog.py's docstring (format v1, 32-B
header, 52-B records, sentinel trailer) with plausible-looking signal
content, for exercising ingest_log.py / common.py end to end.

Usage:
  python make_test_blg.py [-o logs/TEST0001.BLG] [--seed 0] [--truncate]

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

    fault_flags = np.zeros(N_SAMPLES, dtype=np.uint16)

    # ps_phase walks 0..15 over the run.
    ps_phase = np.minimum((t / DURATION_S * 16.0).astype(np.uint8), 15)
    dc_phase = np.full(N_SAMPLES, 0xFF, dtype=np.uint8)
    trap_phase = np.full(N_SAMPLES, 0xFF, dtype=np.uint8)

    # flags = 0x03 normally; velocity chain marked invalid for t in [30,31)s.
    flags = np.full(N_SAMPLES, 0x03, dtype=np.uint8)
    invalid = (t >= 30.0) & (t < 31.0)
    flags[invalid] &= ~0x02 & 0xFF

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
                fault_flags=fault_flags, ps_phase=ps_phase,
                dc_phase=dc_phase, trap_phase=trap_phase, flags=flags)


def pack_header():
    hdr = struct.pack(HEADER_FMT, MAGIC, 1, RECORD_SIZE, PROFILE_TYPE, 0,
                       START_MILLIS, START_MICROS, K_DROOP_X1000)
    hdr += b"\x00" * (HEADER_SIZE - len(hdr))
    assert len(hdr) == HEADER_SIZE
    return hdr


def pack_record(sig, i):
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
                  abandoned=0):
    body = struct.pack(TRAILER_FMT, 0xFFFFFFFF, records_written, dropped,
                        close_reason, error_code, abandoned)
    body += b"\x00" * (RECORD_SIZE - len(body))
    assert len(body) == RECORD_SIZE
    return body


def build_blg(seed, truncate, wrap=False, dropped=0):
    sig = build_signals(seed, wrap=wrap)
    n = N_SAMPLES
    if truncate:
        n = int(N_SAMPLES * 0.70)

    out = bytearray()
    out += pack_header()
    for i in range(n):
        out += pack_record(sig, i)

    if truncate:
        # Cut off mid-record: a partial trailing record's worth of garbage
        # bytes, and no trailer -- simulates power loss mid-write.
        out += b"\xA5" * (RECORD_SIZE // 2)
    else:
        out += pack_trailer(records_written=n, dropped=dropped)

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
    args = ap.parse_args()

    data = build_blg(args.seed, args.truncate, wrap=args.wrap,
                     dropped=args.dropped)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)

    print(f"[make_test_blg] wrote {out_path} ({len(data)} bytes, "
          f"truncate={args.truncate}, wrap={args.wrap}, seed={args.seed})")


if __name__ == "__main__":
    main()
