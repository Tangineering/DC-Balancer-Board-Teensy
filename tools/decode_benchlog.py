#!/usr/bin/env python3
"""Decode .BLG bench-log files (format versions 1, 2, 3, 4, 5, and 6) into CSV.

The firmware writer lives in teensy_controller/teensy_controller.ino
(State 98 SD-card logging, see PLAN.md sec 9g). File layout:

  Header (32 B, LE): magic b'BLG1', u8 version(=1|2|3|4), u8 record_size
    (=52 for v1/v2, 68 for v3/v4), u8 profile_type (bitmask: 1=PS, 2=TP,
    4=DC, 8=MANUAL -- the fw v9 operator-driven 'K 1' run, filed as
    MLnnnn.BLG and carrying no profile parameters), u8 pad/param_flags
    (see below), u32 start_millis, u32
    start_micros, u16 K_DROOP_x1000 (ohms x1000), then in format v2+ a u16
    fw_version at offset 18 (the FW_VERSION the firmware was built with,
    see docs/firmware-versions.md; v1 files predate firmware versioning
    and report fw_version None / "pre-versioning"), zero-padded to 32 B.
    The header's own record_size byte is cross-checked against the size
    expected for its version; a mismatch is a hard error (a
    version/record_size pair that disagrees with itself means a corrupt
    or unrecognised file, not a new format).

  Header, format v4 (adds two per-run profile parameters; RECORD format is
    UNCHANGED from v3 -- v4 records are byte-identical to v3 records, still
    68 B / RECORD_FMT_V3): the byte at offset 7 (pad in v1-v3) becomes a
    param-valid flags byte: bit0 = profileAmp valid, bit1 = profileB valid.
    Bytes 20-23 (LE f32) carry profileAmp (Imax for T/W profiles, Vmax for
    Y; invalid/0.0 for R/D). Bytes 24-27 (LE f32) carry profileB (the W/Y
    share-clip bound b; invalid/0.0 otherwise). Byte 19 and bytes 28-31 are
    reserved zero. A value is only trusted when its valid bit is set --
    decode_blg() reports it as None in the header dict and omits it from
    the banner line when the bit is clear, regardless of what garbage (or
    stale zero) sits in the float bytes.

  Record, format v1/v2 (52 B, LE): u32 t_us, then 10x f32 (share_sp,
    share_act, v_sp, v_act, I_fc, I_batt, gFC, gBT, V_bus, I_cmd),
    u16 fault_flags, u8 ps_phase, u8 dc_phase, u8 trap_phase, u8 flags,
    u8 pad[2]. flags bit0 = a profile / live share loop is driving the
    droop MDACs this tick; bit1 = velocity chain valid (v_sp/v_act
    meaningless when clear). Phase bytes are 0xFF when that profile isn't
    running.

  Record, format v3 (68 B, LE): u32 t_us, then 14x f32 (share_sp,
    share_act, v_sp, v_act, I_fc, I_batt, gFC, gBT, V_bus, I_cmd, V_fc,
    V_batt, V_chg, V_rgn), u16 fault_flags, u8 ps_phase, u8 dc_phase,
    u8 trap_phase, u8 flags, u8 pad[2]. v3 appends four source/node
    voltage channels (V_fc, V_batt, V_chg, V_rgn) after I_cmd; bit0/bit1
    of flags are unchanged from v1/v2 (droop-drive / velocity-chain-valid).
    v3 also defines two new flags bits describing the share loop's control
    mode this tick: bit2 (0x04) = closed-loop control active this tick;
    bit3 (0x08) = closed-loop has been active continuously since the last
    share-control reset. The four combinations decode as: bit2=1 (bit3
    irrelevant) = closed-loop; bit2=0/bit3=1 = HOLD (closed-loop was
    active since the last reset but is not driving this tick);
    bit2=0/bit3=0 = open-loop feedforward. The decoder passes the flags
    byte through unchanged (raw uint) in both v1/v2 and v3 CSVs -- this is
    a documentation-only addition, decode behaviour is identical.

  Header, format v5 (fw v11): adds no header fields -- v5 is IDENTICAL to v4
    in the header (32 B layout, same offsets, same param-valid flags byte
    at offset 7, same profileAmp/profileB fields). Only the RECORD format
    changes; see below. v4's `if version >= 4:` header branches (fw_version,
    param_flags, profileAmp/profileB) already cover v5 unchanged.

  Record, format v5 (76 B, LE): the existing v3/v4 68 B record (u32 t_us,
    14x f32 channel columns, u16 fault_flags, u8 ps_phase, u8 dc_phase, u8
    trap_phase, u8 flags, u8 pad[2]) with two little-endian f32 fields
    APPENDED at the end (offsets 0-67 unchanged):
      offset 68-71: u_unsat  -- drive controller pre-clamp output [A]
                    (PI-fallback build: the PI controller's pre-clamp
                    command instead).
      offset 72-75: drive_x0 -- Youla drive controller integrator state
                    x[0] (PI-fallback build: pi_motor_accum instead).
    These two fields legitimately repeat in pairs (1 kHz sampling vs a
    500 Hz controller tick) -- this is not a decode bug or a logging
    artifact.
    flags gains two new bits, in the SAME byte/offset as before (the
    decoder passes the whole byte through raw in the CSV, exactly as it
    does for bit0-bit3 today -- no new CSV columns from the flag bits
    themselves): bit4 (0x10) = this tick's drive command came from the
    Youla drive controller (clear = PI fallback); bit5 (0x20) = this
    tick's share loop is the Youla share controller (clear = PI
    fallback).

  Header, format v6 (fw v16): adds no header fields -- v6 is IDENTICAL to
    v4/v5 in the header (32 B layout, same offsets). Only the RECORD format
    changes; see below. The existing `if version >= 4:` header branches
    already cover v6 unchanged.

  Record, format v6 (92 B, LE): the v5 76 B record (offsets 0-75 unchanged)
    with four more fields APPENDED at the end:
      offset 76-79: i32 encoder_pos -- raw quadrature-decoded encoder count
                    (signed, direction-sensitive).
      offset 80-83: u32 enc_period_ref_us -- edge-period estimator's
                    reference period [us] this tick.
      offset 84-87: u32 enc_multi_pitch_count -- CUMULATIVE counter of
                    multi-pitch (k>1) period reinterpretations (see fw v13's
                    adaptive-filter k-branch); diff consecutive samples to
                    get a per-interval rate, do not read it as an
                    instantaneous count.
      offset 88-91: u32 enc_spurious_drop_count -- CUMULATIVE counter of
                    dropped intervals (raw floor + the 0.625x-of-reference
                    gate + the per-pitch floor, fw v16); also a running
                    total, diff to rate it.
    Both counters are firmware-side free-running u32 counts -- a diff that
    goes negative across a sample pair means the counter wrapped, not that
    something reversed; this decoder does not attempt unwrap correction, it
    only exposes the raw cumulative value.

  Trailer: a record with t_us == 0xFFFFFFFF (sentinel), reinterpreted as
    u32 sentinel, u32 records_written, u32 dropped_count, u8 close_reason
    (1=complete, 2=stop, 3=X, 4=Q, 5=fault, 6=io_error), u8 error_code,
    u32 abandoned (sampled but never drained -- wedged-card close),
    rest zero -- padded out to the version's full record size (52 B for
    v1/v2, 68 B for v3).

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

Format v4 adds no CSV columns -- v4 files decode with the same 20-column
v3 CSV layout (RECORD_INFO[4] reuses the v3 record format/csv_header). The
new profileAmp/profileB values are header-only metadata: they are reported
in the banner report line (see below) and exposed on DecodeResult.header,
not written into the CSV.

Format v5 adds two CSV columns -- u_unsat and drive_x0 -- inserted right
before fault_flags (i.e. immediately after V_rgn), giving a 22-column
CSV_HEADER_V5. The header itself is unchanged from v4 (RECORD_INFO[5] has
its own record fmt/size/csv_fields/csv_header but reuses v4's header
decode path unmodified).

Format v6 adds four more CSV columns -- encoder_pos, enc_period_ref_us,
enc_multi_pitch_count, enc_spurious_drop_count -- APPENDED after drive_x0
(i.e. still before fault_flags), giving a 26-column CSV_HEADER_V6. The
header itself is unchanged from v4/v5 (RECORD_INFO[6] has its own record
fmt/size/csv_fields/csv_header but reuses v4's header decode path
unmodified).

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
reproduces the exact stdout/stderr byte stream documented above. The
result's csv_header (not the module-level CSV_HEADER constant) is the
correct CSV header line for the decoded file's version -- v1/v2 files get
the 16-column CSV_HEADER, v3/v4 files get the 20-column CSV_HEADER_V3, v5
files get the 22-column CSV_HEADER_V5, v6 files get the 26-column
CSV_HEADER_V6.
DecodeResult.header also carries "profile_amp" and "profile_b" (float or
None -- None for v1-v3 files and for a v4 file whose corresponding valid
bit is clear).
"""
import argparse
import struct
import sys
from dataclasses import dataclass, field

MAGIC = b"BLG1"
HEADER_FMT = "<4sBBBBIIH"
HEADER_SIZE = 32

# v1/v2 record layout (kept as module-level constants for back-compat with
# any external importer that reads them directly -- they describe the
# v1/v2 record only, now that v3 exists alongside it).
RECORD_FMT = "<I10fHBBBB2x"
RECORD_SIZE = 52

# v3 record layout: adds V_fc, V_batt, V_chg, V_rgn (4 f32) after I_cmd.
RECORD_FMT_V3 = "<I14fHBBBB2x"
RECORD_SIZE_V3 = 68

# v5 record layout: v3/v4's 68 B record with u_unsat, drive_x0 (2 f32)
# APPENDED at the end (offsets 0-67 unchanged) -- see the module docstring.
RECORD_FMT_V5 = "<I14fHBBBB2xff"
RECORD_SIZE_V5 = 76

# v6 record layout: v5's 76 B record with encoder_pos (i32),
# enc_period_ref_us (u32), enc_multi_pitch_count (u32),
# enc_spurious_drop_count (u32) APPENDED at the end (offsets 0-75
# unchanged) -- see the module docstring.
RECORD_FMT_V6 = "<I14fHBBBB2xffiIII"
RECORD_SIZE_V6 = 92

TRAILER_FMT = "<IIIBBI"
CLOSE_REASONS = {1: "complete", 2: "stop", 3: "X", 4: "Q", 5: "fault",
                  6: "io_error"}

SUPPORTED_VERSIONS = (1, 2, 3, 4, 5, 6)

# Per-version record format/size and CSV header/field list. v1 and v2 share
# a record layout; v3 appends the four new voltage channels after I_cmd.
# v4 changes only the HEADER (adds profileAmp/profileB); its record format
# is byte-identical to v3, so it reuses RECORD_FMT_V3/CSV_FIELDS_V3/
# CSV_HEADER_V3 below. v5 appends u_unsat, drive_x0 after the v3/v4 record
# fields (see RECORD_FMT_V5 above); its header is unchanged from v4.
CSV_FIELDS = ["share_sp", "share_act", "v_sp", "v_act", "I_fc", "I_batt",
              "gFC", "gBT", "V_bus", "I_cmd"]
CSV_HEADER = ("t_us,share_sp,share_act,v_sp,v_act,I_fc,I_batt,gFC,gBT,V_bus,"
              "I_cmd,fault_flags,ps_phase,dc_phase,trap_phase,flags")

CSV_FIELDS_V3 = ["share_sp", "share_act", "v_sp", "v_act", "I_fc", "I_batt",
                 "gFC", "gBT", "V_bus", "I_cmd", "V_fc", "V_batt", "V_chg",
                 "V_rgn"]
CSV_HEADER_V3 = ("t_us,share_sp,share_act,v_sp,v_act,I_fc,I_batt,gFC,gBT,"
                  "V_bus,I_cmd,V_fc,V_batt,V_chg,V_rgn,fault_flags,ps_phase,"
                  "dc_phase,trap_phase,flags")

CSV_FIELDS_V5 = ["share_sp", "share_act", "v_sp", "v_act", "I_fc", "I_batt",
                 "gFC", "gBT", "V_bus", "I_cmd", "V_fc", "V_batt", "V_chg",
                 "V_rgn", "u_unsat", "drive_x0"]
CSV_HEADER_V5 = ("t_us,share_sp,share_act,v_sp,v_act,I_fc,I_batt,gFC,gBT,"
                  "V_bus,I_cmd,V_fc,V_batt,V_chg,V_rgn,u_unsat,drive_x0,"
                  "fault_flags,ps_phase,dc_phase,trap_phase,flags")

CSV_FIELDS_V6 = ["share_sp", "share_act", "v_sp", "v_act", "I_fc", "I_batt",
                 "gFC", "gBT", "V_bus", "I_cmd", "V_fc", "V_batt", "V_chg",
                 "V_rgn", "u_unsat", "drive_x0", "encoder_pos",
                 "enc_period_ref_us", "enc_multi_pitch_count",
                 "enc_spurious_drop_count"]
CSV_HEADER_V6 = ("t_us,share_sp,share_act,v_sp,v_act,I_fc,I_batt,gFC,gBT,"
                  "V_bus,I_cmd,V_fc,V_batt,V_chg,V_rgn,u_unsat,drive_x0,"
                  "encoder_pos,enc_period_ref_us,enc_multi_pitch_count,"
                  "enc_spurious_drop_count,fault_flags,ps_phase,dc_phase,"
                  "trap_phase,flags")

RECORD_INFO = {
    1: {"fmt": RECORD_FMT, "size": RECORD_SIZE, "csv_fields": CSV_FIELDS,
        "csv_header": CSV_HEADER},
    2: {"fmt": RECORD_FMT, "size": RECORD_SIZE, "csv_fields": CSV_FIELDS,
        "csv_header": CSV_HEADER},
    3: {"fmt": RECORD_FMT_V3, "size": RECORD_SIZE_V3,
        "csv_fields": CSV_FIELDS_V3, "csv_header": CSV_HEADER_V3},
    4: {"fmt": RECORD_FMT_V3, "size": RECORD_SIZE_V3,
        "csv_fields": CSV_FIELDS_V3, "csv_header": CSV_HEADER_V3},
    5: {"fmt": RECORD_FMT_V5, "size": RECORD_SIZE_V5,
        "csv_fields": CSV_FIELDS_V5, "csv_header": CSV_HEADER_V5},
    6: {"fmt": RECORD_FMT_V6, "size": RECORD_SIZE_V6,
        "csv_fields": CSV_FIELDS_V6, "csv_header": CSV_HEADER_V6},
}

# 30 s: longer than any profile's worst card-stall gap (ring = 1024 rec ~=
# 1.0 s; longest profile is the 40 s Y), and 0.70% of the 2**32 wrap, so
# random garbage is rejected.
MAX_GAP_US = 30_000_000


@dataclass
class DecodeResult:
    """Result of decode_blg(). csv_rows have no trailing newline.

    header: {version, record_size, profile_type, start_millis,
             start_micros, k_droop_ohm, fw_version, profile_amp, profile_b}
             -- profile_amp/profile_b are float or None; None for v1-v3
             files and for a v4 file whose corresponding param-valid flag
             bit (header byte 7, bit0=amp/bit1=b) is clear.
    trailer: None, or {records_written, dropped, close_reason (int),
              close_reason_str, error_code, abandoned}
    warnings: human-readable warning lines, WITHOUT the
              "[decode_benchlog] " prefix.
    report_lines: every "[decode_benchlog] ..." line, in the exact order
                  the CLI prints them to stderr.
    csv_header: the CSV header line matching this file's version (v1/v2 ==
                module-level CSV_HEADER, v3/v4 == CSV_HEADER_V3) -- always
                use this rather than the module-level CSV_HEADER constant,
                since the constant only describes v1/v2.
    """
    header: dict
    csv_rows: list = field(default_factory=list)
    records_read: int = 0
    trailer: dict = None
    warnings: list = field(default_factory=list)
    report_lines: list = field(default_factory=list)
    csv_header: str = CSV_HEADER


def decode_blg(data):
    """Parse an in-memory .BLG buffer (bytes) and return a DecodeResult.

    Raises ValueError (with the same message text the CLI prints, minus
    the "error: " prefix) on a short file, bad magic, bad version, or
    unexpected record_size.
    """
    if len(data) < HEADER_SIZE:
        raise ValueError("file shorter than the 32-byte header")

    magic, version, record_size, profile_type, hdr7, start_millis, \
        start_micros, k_droop_x1000 = struct.unpack_from(HEADER_FMT, data, 0)
    if magic != MAGIC:
        raise ValueError(f"bad magic {magic!r}, expected {MAGIC!r}")
    if version not in SUPPORTED_VERSIONS:
        expected = " or ".join(str(v) for v in SUPPORTED_VERSIONS)
        raise ValueError(f"unsupported version {version}, expected {expected}")

    record_info = RECORD_INFO[version]
    expected_record_size = record_info["size"]
    if record_size != expected_record_size:
        raise ValueError(
            f"unexpected record_size {record_size} for version {version}, "
            f"expected {expected_record_size}")
    record_fmt = record_info["fmt"]

    # v2/v3/v4 add a u16 fw_version at offset 18 (in v1 those bytes are zero
    # pad); None marks a pre-versioning (v1) log.
    fw_version = struct.unpack_from("<H", data, 18)[0] if version >= 2 else None

    # v4 repurposes header byte 7 (pad in v1-v3) as a param-valid flags byte
    # and adds two LE f32 fields at offsets 20/24: profileAmp (bit0) and
    # profileB (bit1). A value is trusted only when its bit is set --
    # otherwise it's reported as None regardless of what's in the bytes
    # (invalid/0.0 per the firmware contract, but garbage is possible too).
    profile_amp = None
    profile_b = None
    if version >= 4:
        param_flags = hdr7
        raw_amp, raw_b = struct.unpack_from("<ff", data, 20)
        if param_flags & 0x01:
            profile_amp = raw_amp
        if param_flags & 0x02:
            profile_b = raw_b

    header = {
        "version": version,
        "record_size": record_size,
        "profile_type": profile_type,
        "start_millis": start_millis,
        "start_micros": start_micros,
        "k_droop_ohm": k_droop_x1000 / 1000.0,
        "fw_version": fw_version,
        "profile_amp": profile_amp,
        "profile_b": profile_b,
    }

    csv_rows = []
    off = HEADER_SIZE
    records_read = 0
    trailer = None
    prev_t_us = None
    garbage_at = None
    max_interval_us = 0
    missed_periods = 0
    while off + record_size <= len(data):
        chunk = data[off:off + record_size]
        off += record_size
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

        fields = struct.unpack_from(record_fmt, chunk, 0)
        if version == 6:
            (_t, share_sp, share_act, v_sp, v_act, i_fc, i_batt, gfc, gbt,
             v_bus, i_cmd, v_fc, v_batt, v_chg, v_rgn, fault_flags, ps_phase,
             dc_phase, trap_phase, flags, u_unsat, drive_x0, encoder_pos,
             enc_period_ref_us, enc_multi_pitch_count,
             enc_spurious_drop_count) = fields
        elif version == 5:
            (_t, share_sp, share_act, v_sp, v_act, i_fc, i_batt, gfc, gbt,
             v_bus, i_cmd, v_fc, v_batt, v_chg, v_rgn, fault_flags, ps_phase,
             dc_phase, trap_phase, flags, u_unsat, drive_x0) = fields
        elif version in (3, 4):
            (_t, share_sp, share_act, v_sp, v_act, i_fc, i_batt, gfc, gbt,
             v_bus, i_cmd, v_fc, v_batt, v_chg, v_rgn, fault_flags, ps_phase,
             dc_phase, trap_phase, flags) = fields
        else:
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
               "%.9g" % gbt, "%.9g" % v_bus, "%.9g" % i_cmd]
        if version in (3, 4, 5, 6):
            row += ["%.9g" % v_fc, "%.9g" % v_batt, "%.9g" % v_chg,
                    "%.9g" % v_rgn]
        if version in (5, 6):
            row += ["%.9g" % u_unsat, "%.9g" % drive_x0]
        if version == 6:
            row += [encoder_pos, enc_period_ref_us, enc_multi_pitch_count,
                    enc_spurious_drop_count]
        row += [fault_flags, ps_cell, dc_cell, tp_cell, flags]
        csv_rows.append(",".join(str(c) for c in row))
        records_read += 1

    report_lines = []
    warnings = []

    fw_str = "pre-versioning" if fw_version is None else str(fw_version)
    banner = (
        f"[decode_benchlog] version={version} fw_version={fw_str} "
        f"profile_type={profile_type} "
        f"start_millis={start_millis} start_micros={start_micros} "
        f"K_DROOP={k_droop_x1000 / 1000.0:.3f} ohm")
    # v4 profile params are appended only when their valid bit is set, so
    # v1-v3 banners (and a v4 file with neither bit set) are unaffected --
    # this keeps the v1/v2/v3 report output byte-identical to pre-v4.
    if version >= 4:
        extra = []
        if profile_amp is not None:
            extra.append(f"profile_amp={profile_amp:.3f}")
        if profile_b is not None:
            extra.append(f"profile_b={profile_b:.3f}")
        if extra:
            banner += " " + " ".join(extra)
    report_lines.append(banner)
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
                         warnings=warnings, report_lines=report_lines,
                         csv_header=record_info["csv_header"])


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
    out.write(result.csv_header + "\n")
    for row in result.csv_rows:
        out.write(row + "\n")
    if args.output:
        out.close()

    for line in result.report_lines:
        print(line, file=sys.stderr)


if __name__ == "__main__":
    main()
