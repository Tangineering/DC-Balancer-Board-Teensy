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
    (1=complete, 2=stop, 3=X, 4=Q, 5=fault, 6=io_error), u8 error_code,
    u32 abandoned (sampled but never drained -- wedged-card close),
    rest zero.

Usage: python decode_benchlog.py FILE.BLG [-o out.csv]

CSV goes to stdout (or -o); trailer stats, close reason, gap statistics,
and a records-read-vs-trailer-total consistency check go to stderr.

t_us is micros() at sample, which wraps every 4294.967296 s (71.58 min); a
run is far shorter than that but can still STRADDLE a wrap, so the guard
compares the modular step (t_us - prev) mod 2**32 against MAX_GAP_US rather
than requiring a raw increase. The first record whose modular step is zero
or implausibly large is where the real data ended -- this is how a missing
trailer (file ends mid-record or with no sentinel, e.g. power loss mid-run)
is distinguished from stale pre-allocated card content following the last
real record (the firmware pre-allocates 32 MB and a brownout leaves
whatever was on the card there). A candidate trailer record is only
accepted as a real trailer if its close_reason is one of the known values
above; otherwise it is treated as data and falls through to the same step
check (guards against a legitimate sample landing on t_us == 0xFFFFFFFF,
p ~= 9.3e-6 per run).

v_sp/v_act are blanked in the CSV when flags bit1 (velocity chain valid) is
clear -- see above.

Gap statistics (printed to stderr): max_interval_us is the largest modular
step between consecutive records; missed_periods sums, over every step,
max(round(delta_us / 1000) - 1, 0) -- i.e. how many 1 kHz control ticks
appear to have not run at all. A missed period means the 1 kHz control tick
itself did not run that millisecond (the log's sample gate shares the
controllers' no-backfill rate-limiter), so gaps are control-loop-health
events disclosed in-band by the log, not logger data loss.

Importable API: decode_blg(data) -> DecodeResult parses an in-memory .BLG
buffer without touching stdout/stderr/argv, for use by other tools (see
tools/benchlog_analysis/). main() is a thin CLI wrapper around it that
reproduces the exact stdout/stderr byte stream documented above.
"""
import argparse
import struct
import sys
from dataclasses import dataclass, field

MAGIC = b"BLG1"
HEADER_FMT = "<4sBBBBIIH"
HEADER_SIZE = 32
RECORD_FMT = "<I10fHBBBB2x"
RECORD_SIZE = 52
TRAILER_FMT = "<IIIBBI"
CLOSE_REASONS = {1: "complete", 2: "stop", 3: "X", 4: "Q", 5: "fault",
                  6: "io_error"}
CSV_FIELDS = ["share_sp", "share_act", "v_sp", "v_act", "I_fc", "I_batt",
              "gFC", "gBT", "V_bus", "I_cmd"]
CSV_HEADER = ("t_us,share_sp,share_act,v_sp,v_act,I_fc,I_batt,gFC,gBT,V_bus,"
              "I_cmd,fault_flags,ps_phase,dc_phase,trap_phase,flags")

# 30 s: longer than any profile's worst card-stall gap (ring = 1024 rec ~=
# 1.0 s; longest profile is the 40 s Y), and 0.70% of the 2**32 wrap, so
# random garbage is rejected.
MAX_GAP_US = 30_000_000


@dataclass
class DecodeResult:
    """Result of decode_blg(). csv_rows have no trailing newline.

    header: {version, record_size, profile_type, start_millis,
             start_micros, k_droop_ohm}
    trailer: None, or {records_written, dropped, close_reason (int),
              close_reason_str, error_code, abandoned}
    warnings: human-readable warning lines, WITHOUT the
              "[decode_benchlog] " prefix.
    report_lines: every "[decode_benchlog] ..." line, in the exact order
                  the CLI prints them to stderr.
    """
    header: dict
    csv_rows: list = field(default_factory=list)
    records_read: int = 0
    trailer: dict = None
    warnings: list = field(default_factory=list)
    report_lines: list = field(default_factory=list)


def decode_blg(data):
    """Parse an in-memory .BLG buffer (bytes) and return a DecodeResult.

    Raises ValueError (with the same message text the CLI prints, minus
    the "error: " prefix) on a short file, bad magic, bad version, or
    unexpected record_size.
    """
    if len(data) < HEADER_SIZE:
        raise ValueError("file shorter than the 32-byte header")

    magic, version, record_size, profile_type, _pad, start_millis, \
        start_micros, k_droop_x1000 = struct.unpack_from(HEADER_FMT, data, 0)
    if magic != MAGIC:
        raise ValueError(f"bad magic {magic!r}, expected {MAGIC!r}")
    if version != 1:
        raise ValueError(f"unsupported version {version}, expected 1")
    if record_size != RECORD_SIZE:
        raise ValueError(f"unexpected record_size {record_size}, expected {RECORD_SIZE}")

    header = {
        "version": version,
        "record_size": record_size,
        "profile_type": profile_type,
        "start_millis": start_millis,
        "start_micros": start_micros,
        "k_droop_ohm": k_droop_x1000 / 1000.0,
    }

    csv_rows = []
    off = HEADER_SIZE
    records_read = 0
    trailer = None
    prev_t_us = None
    garbage_at = None
    max_interval_us = 0
    missed_periods = 0
    while off + RECORD_SIZE <= len(data):
        chunk = data[off:off + RECORD_SIZE]
        off += RECORD_SIZE
        t_us = struct.unpack_from("<I", chunk, 0)[0]
        if t_us == 0xFFFFFFFF:
            sentinel, records_written, dropped, close_reason, error_code, \
                abandoned = struct.unpack_from(TRAILER_FMT, chunk, 0)
            if close_reason in CLOSE_REASONS:
                trailer = (records_written, dropped, close_reason,
                           error_code, abandoned)
                break
            # Else: t_us == 0xFFFFFFFF but the reason byte isn't a known
            # close reason, so this isn't a real trailer -- a legitimate
            # sample can land on the sentinel value (p ~= 9.3e-6/run).
            # Fall through and treat it as an ordinary data record; the
            # step check below will reject it as garbage if it's actually
            # stale post-brownout card content.

        # Wrap-safe bounded modular step. t_us is micros() at sample, which
        # wraps every ~71.58 min; a run is far shorter than that but can
        # still straddle a wrap, so a raw non-increase is not itself
        # evidence of truncation. Compute the forward modular distance and
        # stop only when it's zero (duplicate/stall) or implausibly large
        # (stale pre-allocated card content following a brownout, or
        # random garbage) -- see MAX_GAP_US above.
        if prev_t_us is not None:
            delta = (t_us - prev_t_us) & 0xFFFFFFFF
            if delta == 0 or delta > MAX_GAP_US:
                garbage_at = records_read
                break
            if delta > max_interval_us:
                max_interval_us = delta
            missed_periods += max(round(delta / 1000) - 1, 0)
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
        csv_rows.append(",".join(str(c) for c in row))
        records_read += 1

    report_lines = []
    warnings = []

    report_lines.append(
        f"[decode_benchlog] version={version} profile_type={profile_type} "
        f"start_millis={start_millis} start_micros={start_micros} "
        f"K_DROOP={k_droop_x1000 / 1000.0:.3f} ohm")
    report_lines.append(f"[decode_benchlog] records read: {records_read}")

    trailer_dict = None
    if trailer is None:
        w = ("WARNING: no trailer found -- file is truncated (e.g. power "
             "loss mid-run)")
        warnings.append(w)
        report_lines.append(f"[decode_benchlog] {w}")
        if garbage_at is not None:
            w = (f"WARNING: stopped at record {garbage_at} -- modular "
                 f"t_us step was zero or exceeded MAX_GAP_US={MAX_GAP_US}, "
                 f"so everything past it is stale pre-allocated card "
                 f"content (or garbage), not data")
            warnings.append(w)
            report_lines.append(f"[decode_benchlog] {w}")
    else:
        records_written, dropped, close_reason, error_code, abandoned = trailer
        reason_str = CLOSE_REASONS.get(close_reason, f"unknown({close_reason})")
        trailer_dict = {
            "records_written": records_written,
            "dropped": dropped,
            "close_reason": close_reason,
            "close_reason_str": reason_str,
            "error_code": error_code,
            "abandoned": abandoned,
        }
        report_lines.append(
            f"[decode_benchlog] trailer: records_written={records_written} "
            f"dropped_count={dropped} abandoned={abandoned} "
            f"close_reason={reason_str} error_code={error_code}")
        if records_written != records_read:
            w = (f"WARNING: trailer records_written ({records_written}) "
                 f"!= records actually read ({records_read})")
            warnings.append(w)
            report_lines.append(f"[decode_benchlog] {w}")

    report_lines.append(f"[decode_benchlog] max_interval_us={max_interval_us} "
                         f"missed_periods={missed_periods}")

    return DecodeResult(header=header, csv_rows=csv_rows,
                         records_read=records_read, trailer=trailer_dict,
                         warnings=warnings, report_lines=report_lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help=".BLG file to decode")
    ap.add_argument("-o", "--output", help="CSV output path (default: stdout)")
    args = ap.parse_args()

    try:
        with open(args.file, "rb") as f:
            data = f.read()
        result = decode_blg(data)
    except OSError as e:
        sys.exit(f"error: {e}")
    except ValueError as e:
        sys.exit(f"error: {e}")

    out = open(args.output, "w", newline="") if args.output else sys.stdout
    out.write(CSV_HEADER + "\n")
    for row in result.csv_rows:
        out.write(row + "\n")
    if args.output:
        out.close()

    for line in result.report_lines:
        print(line, file=sys.stderr)


if __name__ == "__main__":
    main()
