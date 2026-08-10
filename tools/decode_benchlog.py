#!/usr/bin/env python3
"""Decode .BLG bench-log files (format version 1) into CSV.

The firmware writer lives in teensy_controller/teensy_controller.ino
(State 98 SD-card logging, see PLAN.md sec 9g). File layout:

  Header (32 B, LE): magic b'BLG1', u8 version(=1), u8 record_size(=52),
    u8 profile_type (bitmask: 1=PS, 2=TP, 4=DC), u8 pad, u32 start_millis,
    u32 start_micros, u16 K_DROOP_x1000 (ohms x1000), zero-padded to 32 B.

  Record (52 B, LE): u32 t_us, then 10x f32 (share_sp, share_act, v_sp,
    v_act, I_fc, I_batt, gFC, gBT, V_bus, I_cmd), u16 fault_flags,
    u8 ps_phase, u8 dc_phase, u8 trap_phase, u8 flags, u8 pad[2].
    flags bit0 = a profile / live share loop is driving the droop MDACs
    this tick; bit1 = velocity chain valid (v_sp/v_act meaningless when
    clear). Phase bytes are 0xFF when that profile isn't running.

  Trailer: a record with t_us == 0xFFFFFFFF (sentinel), reinterpreted as
    u32 sentinel, u32 records_written, u32 dropped_count, u8 close_reason
    (1=complete, 2=stop, 3=X, 4=Q, 5=fault), u8 error_code,
    u32 abandoned (sampled but never drained -- wedged-card close),
    rest zero.

Usage: python decode_benchlog.py FILE.BLG [-o out.csv]

CSV goes to stdout (or -o); trailer stats, close reason, and a
records-read-vs-trailer-total consistency check go to stderr. A missing
trailer (file ends mid-record or with no sentinel) is reported as a
truncated file (e.g. power loss mid-run) -- in that case decoding also
stops at the first record whose t_us does not strictly increase, because
the firmware pre-allocates 32 MB and a brownout leaves whatever stale
card content followed the last real record. v_sp/v_act are blanked in the
CSV when flags bit1 (velocity chain valid) is clear -- see above.
"""
import argparse
import struct
import sys

MAGIC = b"BLG1"
HEADER_FMT = "<4sBBBBIIH"
HEADER_SIZE = 32
RECORD_FMT = "<I10fHBBBB2x"
RECORD_SIZE = 52
TRAILER_FMT = "<IIIBBI"
CLOSE_REASONS = {1: "complete", 2: "stop", 3: "X", 4: "Q", 5: "fault"}
CSV_FIELDS = ["share_sp", "share_act", "v_sp", "v_act", "I_fc", "I_batt",
              "gFC", "gBT", "V_bus", "I_cmd"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help=".BLG file to decode")
    ap.add_argument("-o", "--output", help="CSV output path (default: stdout)")
    args = ap.parse_args()

    with open(args.file, "rb") as f:
        data = f.read()

    if len(data) < HEADER_SIZE:
        sys.exit("error: file shorter than the 32-byte header")

    magic, version, record_size, profile_type, _pad, start_millis, \
        start_micros, k_droop_x1000 = struct.unpack_from(HEADER_FMT, data, 0)
    if magic != MAGIC:
        sys.exit(f"error: bad magic {magic!r}, expected {MAGIC!r}")
    if version != 1:
        sys.exit(f"error: unsupported version {version}, expected 1")
    if record_size != RECORD_SIZE:
        sys.exit(f"error: unexpected record_size {record_size}, expected {RECORD_SIZE}")

    out = open(args.output, "w", newline="") if args.output else sys.stdout
    out.write("t_us,share_sp,share_act,v_sp,v_act,I_fc,I_batt,gFC,gBT,V_bus,"
               "I_cmd,fault_flags,ps_phase,dc_phase,trap_phase,flags\n")

    off = HEADER_SIZE
    records_read = 0
    trailer = None
    prev_t_us = None
    garbage_at = None
    while off + RECORD_SIZE <= len(data):
        chunk = data[off:off + RECORD_SIZE]
        off += RECORD_SIZE
        t_us = struct.unpack_from("<I", chunk, 0)[0]
        if t_us == 0xFFFFFFFF:
            sentinel, records_written, dropped, close_reason, error_code, \
                abandoned = struct.unpack_from(TRAILER_FMT, chunk, 0)
            trailer = (records_written, dropped, close_reason, error_code,
                       abandoned)
            break

        # Brownout guard: the firmware pre-allocates 32 MB, so a file that lost
        # its trailer is followed by however many megabytes of stale card
        # content -- which unpacks into perfectly plausible-looking rows. t_us
        # is micros() at sample and therefore strictly increasing within a run
        # (a run is far shorter than the ~71 min uint32 wrap), so the first
        # non-increasing timestamp is where the real data ended.
        if prev_t_us is not None and t_us <= prev_t_us:
            garbage_at = records_read
            break
        prev_t_us = t_us

        fields = struct.unpack_from(RECORD_FMT, chunk, 0)
        (_t, share_sp, share_act, v_sp, v_act, i_fc, i_batt, gfc, gbt,
         v_bus, i_cmd, fault_flags, ps_phase, dc_phase, trap_phase,
         flags) = fields
        velocity_valid = bool(flags & 0x02)
        v_sp_cell = ("%.9g" % v_sp) if velocity_valid else ""
        v_act_cell = ("%.9g" % v_act) if velocity_valid else ""
        ps_cell = "" if ps_phase == 0xFF else ps_phase
        dc_cell = "" if dc_phase == 0xFF else dc_phase
        tp_cell = "" if trap_phase == 0xFF else trap_phase
        row = [t_us, "%.9g" % share_sp, "%.9g" % share_act, v_sp_cell,
               v_act_cell, "%.9g" % i_fc, "%.9g" % i_batt, "%.9g" % gfc,
               "%.9g" % gbt, "%.9g" % v_bus, "%.9g" % i_cmd, fault_flags,
               ps_cell, dc_cell, tp_cell, flags]
        out.write(",".join(str(c) for c in row) + "\n")
        records_read += 1

    if args.output:
        out.close()

    print(f"[decode_benchlog] version={version} profile_type={profile_type} "
          f"start_millis={start_millis} start_micros={start_micros} "
          f"K_DROOP={k_droop_x1000 / 1000.0:.3f} ohm", file=sys.stderr)
    print(f"[decode_benchlog] records read: {records_read}", file=sys.stderr)

    if trailer is None:
        print("[decode_benchlog] WARNING: no trailer found -- file is "
              "truncated (e.g. power loss mid-run)", file=sys.stderr)
        if garbage_at is not None:
            print(f"[decode_benchlog] WARNING: stopped at record "
                  f"{garbage_at} -- t_us stopped increasing, so everything "
                  f"past it is stale pre-allocated card content, not data",
                  file=sys.stderr)
    else:
        records_written, dropped, close_reason, error_code, abandoned = trailer
        reason_str = CLOSE_REASONS.get(close_reason, f"unknown({close_reason})")
        print(f"[decode_benchlog] trailer: records_written={records_written} "
              f"dropped_count={dropped} abandoned={abandoned} "
              f"close_reason={reason_str} error_code={error_code}",
              file=sys.stderr)
        if records_written != records_read:
            print(f"[decode_benchlog] WARNING: trailer records_written "
                  f"({records_written}) != records actually read "
                  f"({records_read})", file=sys.stderr)


if __name__ == "__main__":
    main()
