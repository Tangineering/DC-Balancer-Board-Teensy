#!/usr/bin/env python3
"""Stdlib-only self-test for decode_benchlog.py.

Generates synthetic .BLG files in a temp dir and runs the real decoder
against them as a subprocess (exactly how a user invokes it), asserting on
its stdout (CSV) and stderr (diagnostics). No pytest/unittest dependency,
in the spirit of the C++ host-native suite (test/test_main.cpp): plain
assert() + a PASS/FAIL counter (plus a separate SKIP counter for checks
that need an optional real checked-in log file that may be absent in a
sparse checkout -- see (t) below).

Run: python tools/test_decode_benchlog.py
Exit code 0 on all-pass, 1 on any failure.

Covers (per docs/reviews/firmware/run-001-2026-08-10.md FW-R1-F2 / N2):
  (a) a synthetic valid 40 s run whose t_us STRADDLES the uint32 micros()
      wrap -- must decode every record and find the trailer, no warnings.
  (b) a brownout file (real records followed by stale/garbage bytes, no
      trailer) -- must stop exactly at the true end and warn about it.
  (c) close_reason 6 decodes as "io_error".
  (d) gap statistics (max_interval_us / missed_periods) for a file with
      one 50 ms gap.

Format-v3 coverage (fw v5 round, adds V_fc/V_batt/V_chg/V_rgn):
  (f) v3 header parse (record_size=68, fw_version).
  (g) v3 record decode, including the four new voltage fields, and CSV
      column count/order.
  (h) v3 trailer detection (same sentinel mechanism, now inside a 68 B
      record).
  (i) v3 truncated-file handling (brownout path, mirrors (b)).
  (j) regression: v1/v2 decoding is byte-for-byte unchanged after adding
      v3 support.

Format-v4 coverage (fw v6 round, adds header-only profileAmp/profileB;
RECORD format unchanged from v3):
  (k) header parse with both param-valid bits set: profile_amp/profile_b
      decoded and reported in the banner, at both the API and CLI level.
  (l) amp-only valid (bit0 set, bit1 clear): profile_b reports None and is
      absent from the banner even though its raw float bytes are non-zero.
  (m) neither valid (both bits clear): both params None, banner has no
      profile_amp/profile_b text, version=4 still reported.
  (n) record decode equivalence: a v4 file's records decode to the exact
      same csv_rows/csv_header as an equivalent v3 file (record format is
      byte-identical between v3 and v4).
  (o) v4 record_size/version self-consistency hard error, mirroring (h)
      for v3.
  v1/v2/v3 regression: byte-identical CLI output (CSV + stderr report) was
  verified separately against a real checked-in log per version
  (logs/PS0001.BLG v1, logs/TP0041.BLG v2, logs/TP0074.BLG v3) via filecmp
  against the pre-v4 decoder -- not re-checked here since that comparison
  needs the pre-change decoder binary, not just this test file.

Format-v6 coverage (fw v16 round, adds encoder_pos, enc_period_ref_us,
enc_multi_pitch_count, enc_spurious_drop_count -- 92 B record; header
unchanged from v4/v5):
  (p) header parse: record_size=92, version=6, fw_version, profileAmp/
      profileB carried through the same v4 header path unmodified.
  (q) record decode: the four new fields at their documented CSV positions
      (indices 17-20, right after u_unsat/drive_x0), and the 26-column
      CSV_HEADER_V6.
  (r) v6 record_size/version self-consistency hard error, mirroring (o)
      for v4.
  (s) v5 regression: v5 decode (header + 22-column CSV) is byte-for-byte
      unchanged after adding v6 support.
  (t) v5 real-log regression: logs/ML0146.BLG (a real checked-in fw v14
      capture) decodes to CSV content byte-for-byte identical to the
      committed logs/ML0146/ML0146.csv -- catches a future v5 regression
      that a synthetic-only round-trip (s) would not, since (s) packs and
      decodes with the SAME test file's assumptions about the v5 layout.
      SKIPPED (not failed) if either file is absent, e.g. a sparse
      checkout without logs/.

Format-v7 coverage (fw v20 round, adds enc_edge_count_a, enc_edge_count_b
(u32 boot-monotonic counters) and enc_phase_ewma, enc_duty_a_ewma,
enc_duty_b_ewma (u16 1/256 fixed-point LEVELS) -- 106 B record; header
unchanged from v4/v5/v6):
  (u) header parse: record_size=106, version=7, fw_version/profileAmp/
      profileB carried through the same v4 header path unmodified.
  (v) record decode: the five new fields at their documented CSV positions
      (indices 21-25, right after enc_spurious_drop_count), the 31-column
      CSV_HEADER_V7, and the fixed-point /256 exactness of the three EWMA
      level columns (fp 64 -> 0.25, fp 128 -> 0.5).
  (w) near-wrap u32 values (e.g. 0xFFFFFFF0) decode as large unsigned
      values, not negatives -- the counters are boot-monotonic u32s and a
      negative DIFF across the wrap is a consumer-side concern, not a
      decode transform.
  (x) v7 record_size/version self-consistency hard error, mirroring (r).
  (y) v6 regression: v6 decode (header + 26-column CSV) is unchanged after
      adding v7 support.
"""
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECODER = HERE / "decode_benchlog.py"
# tools/test_decode_benchlog.py -> tools -> repo root
REPO_ROOT = HERE.parent

MAGIC = b"BLG1"
HEADER_FMT = "<4sBBBBIIH"
HEADER_SIZE = 32
RECORD_FMT = "<I10fHBBBB2x"
RECORD_SIZE = 52
RECORD_FMT_V3 = "<I14fHBBBB2x"
RECORD_SIZE_V3 = 68
RECORD_FMT_V5 = "<I14fHBBBB2xff"
RECORD_SIZE_V5 = 76
RECORD_FMT_V6 = "<I14fHBBBB2xffiIII"
RECORD_SIZE_V6 = 92
RECORD_FMT_V7 = "<I14fHBBBB2xffiIIIIIHHH"
RECORD_SIZE_V7 = 106
TRAILER_FMT = "<IIIBBI"
CSV_HEADER_V3 = ("t_us,share_sp,share_act,v_sp,v_act,I_fc,I_batt,gFC,gBT,"
                  "V_bus,I_cmd,V_fc,V_batt,V_chg,V_rgn,fault_flags,ps_phase,"
                  "dc_phase,trap_phase,flags")
CSV_HEADER_V5 = ("t_us,share_sp,share_act,v_sp,v_act,I_fc,I_batt,gFC,gBT,"
                  "V_bus,I_cmd,V_fc,V_batt,V_chg,V_rgn,u_unsat,drive_x0,"
                  "fault_flags,ps_phase,dc_phase,trap_phase,flags")
CSV_HEADER_V6 = ("t_us,share_sp,share_act,v_sp,v_act,I_fc,I_batt,gFC,gBT,"
                  "V_bus,I_cmd,V_fc,V_batt,V_chg,V_rgn,u_unsat,drive_x0,"
                  "encoder_pos,enc_period_ref_us,enc_multi_pitch_count,"
                  "enc_spurious_drop_count,fault_flags,ps_phase,dc_phase,"
                  "trap_phase,flags")
CSV_HEADER_V7 = ("t_us,share_sp,share_act,v_sp,v_act,I_fc,I_batt,gFC,gBT,"
                  "V_bus,I_cmd,V_fc,V_batt,V_chg,V_rgn,u_unsat,drive_x0,"
                  "encoder_pos,enc_period_ref_us,enc_multi_pitch_count,"
                  "enc_spurious_drop_count,enc_edge_count_a,enc_edge_count_b,"
                  "enc_phase_ewma,enc_duty_a_ewma,enc_duty_b_ewma,"
                  "fault_flags,ps_phase,dc_phase,trap_phase,flags")

_passed = 0
_failed = 0
_skipped = 0


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"PASS: {name}")
    else:
        _failed += 1
        print(f"FAIL: {name}" + (f" -- {detail}" if detail else ""))


def skip(name, reason):
    """Report a test (or check) as SKIPPED -- counted separately from both
    PASS and FAIL, so a sparse checkout without logs/ doesn't fail the
    suite, but the skip is still visible (not silently absorbed into the
    pass count)."""
    global _skipped
    _skipped += 1
    print(f"SKIP: {name} -- {reason}")


def pack_header(profile_type=1, start_millis=0, start_micros=0,
                 k_droop_x1000=300):
    hdr = struct.pack(HEADER_FMT, MAGIC, 1, RECORD_SIZE, profile_type, 0,
                       start_millis, start_micros, k_droop_x1000)
    hdr += b"\x00" * (HEADER_SIZE - len(hdr))
    assert len(hdr) == HEADER_SIZE
    return hdr


def pack_record(t_us, share_sp=0.5, share_act=0.5, v_sp=0.0, v_act=0.0,
                 i_fc=0.0, i_batt=0.0, gfc=0.0, gbt=0.0, v_bus=17.5,
                 i_cmd=0.0, fault_flags=0, ps_phase=0xFF, dc_phase=0xFF,
                 trap_phase=0xFF, flags=0):
    rec = struct.pack(RECORD_FMT, t_us & 0xFFFFFFFF, share_sp, share_act,
                       v_sp, v_act, i_fc, i_batt, gfc, gbt, v_bus, i_cmd,
                       fault_flags, ps_phase, dc_phase, trap_phase, flags)
    assert len(rec) == RECORD_SIZE
    return rec


def pack_trailer(records_written, dropped, close_reason, error_code=0,
                  abandoned=0, record_size=RECORD_SIZE):
    body = struct.pack(TRAILER_FMT, 0xFFFFFFFF, records_written, dropped,
                        close_reason, error_code, abandoned)
    body += b"\x00" * (record_size - len(body))
    assert len(body) == record_size
    return body


def pack_header_v3(profile_type=1, start_millis=0, start_micros=0,
                    k_droop_x1000=300, fw_version=1):
    hdr = struct.pack(HEADER_FMT, MAGIC, 3, RECORD_SIZE_V3, profile_type, 0,
                       start_millis, start_micros, k_droop_x1000)
    hdr += struct.pack("<H", fw_version)
    hdr += b"\x00" * (HEADER_SIZE - len(hdr))
    assert len(hdr) == HEADER_SIZE
    return hdr


def pack_record_v3(t_us, share_sp=0.5, share_act=0.5, v_sp=0.0, v_act=0.0,
                    i_fc=0.0, i_batt=0.0, gfc=0.0, gbt=0.0, v_bus=17.5,
                    i_cmd=0.0, v_fc=12.5, v_batt=8.0, v_chg=12.0, v_rgn=0.5,
                    fault_flags=0, ps_phase=0xFF, dc_phase=0xFF,
                    trap_phase=0xFF, flags=0):
    rec = struct.pack(RECORD_FMT_V3, t_us & 0xFFFFFFFF, share_sp, share_act,
                       v_sp, v_act, i_fc, i_batt, gfc, gbt, v_bus, i_cmd,
                       v_fc, v_batt, v_chg, v_rgn, fault_flags, ps_phase,
                       dc_phase, trap_phase, flags)
    assert len(rec) == RECORD_SIZE_V3
    return rec


def pack_header_v4(profile_type=1, start_millis=0, start_micros=0,
                    k_droop_x1000=300, fw_version=1, param_flags=0x03,
                    profile_amp=6.0, profile_b=0.15):
    """v4 header: byte 7 (pad in v1-v3) becomes param_flags (bit0=amp
    valid, bit1=b valid); bytes 20-23/24-27 carry the two LE f32 params.
    Record format/size is unchanged from v3 (RECORD_SIZE_V3)."""
    hdr = struct.pack(HEADER_FMT, MAGIC, 4, RECORD_SIZE_V3, profile_type,
                       param_flags, start_millis, start_micros, k_droop_x1000)
    hdr += struct.pack("<H", fw_version)
    hdr += b"\x00" * (HEADER_SIZE - len(hdr))
    hdr = bytearray(hdr)
    struct.pack_into("<ff", hdr, 20, profile_amp, profile_b)
    assert len(hdr) == HEADER_SIZE
    return bytes(hdr)


def pack_header_v5(profile_type=1, start_millis=0, start_micros=0,
                    k_droop_x1000=300, fw_version=1, param_flags=0x03,
                    profile_amp=6.0, profile_b=0.15):
    """v5 header: byte-identical to v4 (see pack_header_v4) except
    record_size=76 (v5's own record layout)."""
    hdr = struct.pack(HEADER_FMT, MAGIC, 5, RECORD_SIZE_V5, profile_type,
                       param_flags, start_millis, start_micros, k_droop_x1000)
    hdr += struct.pack("<H", fw_version)
    hdr += b"\x00" * (HEADER_SIZE - len(hdr))
    hdr = bytearray(hdr)
    struct.pack_into("<ff", hdr, 20, profile_amp, profile_b)
    assert len(hdr) == HEADER_SIZE
    return bytes(hdr)


def pack_record_v5(t_us, share_sp=0.5, share_act=0.5, v_sp=0.0, v_act=0.0,
                    i_fc=0.0, i_batt=0.0, gfc=0.0, gbt=0.0, v_bus=17.5,
                    i_cmd=0.0, v_fc=12.5, v_batt=8.0, v_chg=12.0, v_rgn=0.5,
                    fault_flags=0, ps_phase=0xFF, dc_phase=0xFF,
                    trap_phase=0xFF, flags=0, u_unsat=0.0, drive_x0=0.0):
    rec = struct.pack(RECORD_FMT_V5, t_us & 0xFFFFFFFF, share_sp, share_act,
                       v_sp, v_act, i_fc, i_batt, gfc, gbt, v_bus, i_cmd,
                       v_fc, v_batt, v_chg, v_rgn, fault_flags, ps_phase,
                       dc_phase, trap_phase, flags, u_unsat, drive_x0)
    assert len(rec) == RECORD_SIZE_V5
    return rec


def pack_header_v6(profile_type=1, start_millis=0, start_micros=0,
                    k_droop_x1000=300, fw_version=1, param_flags=0x03,
                    profile_amp=6.0, profile_b=0.15):
    """v6 header: byte-identical to v4/v5 (see pack_header_v4/v5) except
    record_size=92 (v6's own record layout)."""
    hdr = struct.pack(HEADER_FMT, MAGIC, 6, RECORD_SIZE_V6, profile_type,
                       param_flags, start_millis, start_micros, k_droop_x1000)
    hdr += struct.pack("<H", fw_version)
    hdr += b"\x00" * (HEADER_SIZE - len(hdr))
    hdr = bytearray(hdr)
    struct.pack_into("<ff", hdr, 20, profile_amp, profile_b)
    assert len(hdr) == HEADER_SIZE
    return bytes(hdr)


def pack_record_v6(t_us, share_sp=0.5, share_act=0.5, v_sp=0.0, v_act=0.0,
                    i_fc=0.0, i_batt=0.0, gfc=0.0, gbt=0.0, v_bus=17.5,
                    i_cmd=0.0, v_fc=12.5, v_batt=8.0, v_chg=12.0, v_rgn=0.5,
                    fault_flags=0, ps_phase=0xFF, dc_phase=0xFF,
                    trap_phase=0xFF, flags=0, u_unsat=0.0, drive_x0=0.0,
                    encoder_pos=0, enc_period_ref_us=0,
                    enc_multi_pitch_count=0, enc_spurious_drop_count=0):
    rec = struct.pack(RECORD_FMT_V6, t_us & 0xFFFFFFFF, share_sp, share_act,
                       v_sp, v_act, i_fc, i_batt, gfc, gbt, v_bus, i_cmd,
                       v_fc, v_batt, v_chg, v_rgn, fault_flags, ps_phase,
                       dc_phase, trap_phase, flags, u_unsat, drive_x0,
                       encoder_pos, enc_period_ref_us & 0xFFFFFFFF,
                       enc_multi_pitch_count & 0xFFFFFFFF,
                       enc_spurious_drop_count & 0xFFFFFFFF)
    assert len(rec) == RECORD_SIZE_V6
    return rec


def pack_header_v7(profile_type=1, start_millis=0, start_micros=0,
                    k_droop_x1000=300, fw_version=1, param_flags=0x03,
                    profile_amp=6.0, profile_b=0.15):
    """v7 header: byte-identical to v4/v5/v6 (see pack_header_v4) except
    record_size=106 (v7's own record layout)."""
    hdr = struct.pack(HEADER_FMT, MAGIC, 7, RECORD_SIZE_V7, profile_type,
                       param_flags, start_millis, start_micros, k_droop_x1000)
    hdr += struct.pack("<H", fw_version)
    hdr += b"\x00" * (HEADER_SIZE - len(hdr))
    hdr = bytearray(hdr)
    struct.pack_into("<ff", hdr, 20, profile_amp, profile_b)
    assert len(hdr) == HEADER_SIZE
    return bytes(hdr)


def pack_record_v7(t_us, share_sp=0.5, share_act=0.5, v_sp=0.0, v_act=0.0,
                    i_fc=0.0, i_batt=0.0, gfc=0.0, gbt=0.0, v_bus=17.5,
                    i_cmd=0.0, v_fc=12.5, v_batt=8.0, v_chg=12.0, v_rgn=0.5,
                    fault_flags=0, ps_phase=0xFF, dc_phase=0xFF,
                    trap_phase=0xFF, flags=0, u_unsat=0.0, drive_x0=0.0,
                    encoder_pos=0, enc_period_ref_us=0,
                    enc_multi_pitch_count=0, enc_spurious_drop_count=0,
                    enc_edge_count_a=0, enc_edge_count_b=0,
                    enc_phase_ewma=64, enc_duty_a_ewma=128,
                    enc_duty_b_ewma=128):
    rec = struct.pack(RECORD_FMT_V7, t_us & 0xFFFFFFFF, share_sp, share_act,
                       v_sp, v_act, i_fc, i_batt, gfc, gbt, v_bus, i_cmd,
                       v_fc, v_batt, v_chg, v_rgn, fault_flags, ps_phase,
                       dc_phase, trap_phase, flags, u_unsat, drive_x0,
                       encoder_pos, enc_period_ref_us & 0xFFFFFFFF,
                       enc_multi_pitch_count & 0xFFFFFFFF,
                       enc_spurious_drop_count & 0xFFFFFFFF,
                       enc_edge_count_a & 0xFFFFFFFF,
                       enc_edge_count_b & 0xFFFFFFFF,
                       enc_phase_ewma & 0xFFFF,
                       enc_duty_a_ewma & 0xFFFF,
                       enc_duty_b_ewma & 0xFFFF)
    assert len(rec) == RECORD_SIZE_V7
    return rec


def run_decoder(blg_path):
    proc = subprocess.run(
        [sys.executable, str(DECODER), str(blg_path)],
        capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def write_blg(tmpdir, name, data):
    path = Path(tmpdir) / name
    path.write_bytes(data)
    return path


def test_wrap_straddle(tmpdir):
    """(a) A clean 40 s / 1 kHz run whose t_us straddles the uint32 wrap
    must decode ALL records and find the trailer, with no warnings."""
    n = 40_000  # 40 s at 1 kHz
    start = (2**32) - 20_000_000
    data = pack_header(profile_type=4)
    for i in range(n):
        t_us = (start + i * 1000) & 0xFFFFFFFF
        assert t_us != 0xFFFFFFFF  # never land on the sentinel by construction
        data += pack_record(t_us)
    data += pack_trailer(records_written=n, dropped=0, close_reason=1)

    path = write_blg(tmpdir, "wrap.BLG", data)
    rc, out, err = run_decoder(path)

    lines = [l for l in out.splitlines() if l]
    check("wrap: decoder exits 0", rc == 0, f"rc={rc} stderr={err}")
    check("wrap: emits all records", len(lines) - 1 == n,
          f"csv data rows={len(lines) - 1}, expected {n}")
    check("wrap: records read == n", f"records read: {n}" in err, err)
    check("wrap: trailer found (close_reason=complete)",
          "close_reason=complete" in err, err)
    check("wrap: no truncation warning", "WARNING: no trailer" not in err, err)
    check("wrap: no stale-content warning", "stopped at record" not in err, err)
    check("wrap: no records_written mismatch warning",
          "!= records actually read" not in err, err)
    check("wrap: max_interval_us=1000 (steady 1 kHz, no false gap)",
          "max_interval_us=1000" in err, err)
    check("wrap: missed_periods=0", "missed_periods=0" in err, err)


def test_brownout(tmpdir):
    """(b) Real records followed by garbage/stale tail, no trailer: decoder
    must stop at the true end and warn about truncation."""
    m = 100
    data = pack_header(profile_type=1)
    for i in range(m):
        data += pack_record(i * 1000)
    # Stale/garbage tail: two record-sized chunks of 0xAA bytes. Interpreted
    # as t_us this is a huge value, far outside MAX_GAP_US from the last
    # real record's t_us (99000), so the decoder must reject it as garbage.
    data += b"\xAA" * (2 * RECORD_SIZE)
    # No trailer appended -- simulates a brownout mid-run.

    path = write_blg(tmpdir, "brownout.BLG", data)
    rc, out, err = run_decoder(path)

    lines = [l for l in out.splitlines() if l]
    check("brownout: decoder exits 0", rc == 0, f"rc={rc} stderr={err}")
    check("brownout: stops at true end (m records, not m+2 garbage rows)",
          len(lines) - 1 == m, f"csv data rows={len(lines) - 1}, expected {m}")
    check("brownout: records read == m", f"records read: {m}" in err, err)
    check("brownout: truncation warning present",
          "WARNING: no trailer found" in err, err)
    check("brownout: stopped-at-record warning present",
          f"stopped at record {m}" in err, err)


def test_io_error_close_reason(tmpdir):
    """(c) close_reason 6 decodes as io_error."""
    data = pack_header(profile_type=2)
    data += pack_trailer(records_written=0, dropped=0, close_reason=6,
                          error_code=3)
    path = write_blg(tmpdir, "io_error.BLG", data)
    rc, out, err = run_decoder(path)
    check("io_error: decoder exits 0", rc == 0, f"rc={rc} stderr={err}")
    check("io_error: close_reason=io_error in trailer summary",
          "close_reason=io_error" in err, err)


def test_gap_statistics(tmpdir):
    """(d) A file with one 50 ms gap reports max_interval_us=50000 and
    missed_periods=49 (49 missed 1 kHz control ticks)."""
    data = pack_header(profile_type=1)
    t = 0
    times = [0, 1000, 2000, 3000, 4000]  # steady 1 kHz run-in
    t = times[-1] + 50_000               # the one 50 ms gap
    times.append(t)
    for extra in (1000, 2000):           # resume steady 1 kHz
        t += 1000
        times.append(t)
    for t_us in times:
        data += pack_record(t_us)
    data += pack_trailer(records_written=len(times), dropped=0,
                          close_reason=1)

    path = write_blg(tmpdir, "gap.BLG", data)
    rc, out, err = run_decoder(path)
    check("gap: decoder exits 0", rc == 0, f"rc={rc} stderr={err}")
    check("gap: max_interval_us=50000", "max_interval_us=50000" in err, err)
    check("gap: missed_periods=49", "missed_periods=49" in err, err)


def test_decode_blg_api(tmpdir):
    """(e) The importable decode_blg() API (used by tools/benchlog_analysis)
    must expose the same decode as the CLI: header fields, trailer dict,
    csv_rows matching the CLI's stdout, report_lines matching the CLI's
    stderr byte-for-byte, un-prefixed warnings, and ValueError (not
    sys.exit) on a bad file."""
    sys.path.insert(0, str(HERE))
    import decode_benchlog as db

    n = 100
    data = pack_header(profile_type=2, start_millis=42, start_micros=4242,
                        k_droop_x1000=305)
    for i in range(n):
        data += pack_record(1000 + i * 1000)
    data += pack_trailer(records_written=n + 1, dropped=3, close_reason=2)
    path = write_blg(tmpdir, "api.BLG", data)

    res = db.decode_blg(data)
    check("api: header fields", res.header == {
        "version": 1, "record_size": RECORD_SIZE, "profile_type": 2,
        "start_millis": 42, "start_micros": 4242, "k_droop_ohm": 0.305,
        "fw_version": None, "profile_amp": None, "profile_b": None,
        "hil_build": False},
        repr(res.header))

    # Format v2: fw_version parsed from offset 18 and reported.
    data_v2 = bytearray(data)
    data_v2[4] = 2
    struct.pack_into("<H", data_v2, 18, 7)
    res_v2 = db.decode_blg(bytes(data_v2))
    check("api: v2 header parses fw_version",
          res_v2.header["version"] == 2 and res_v2.header["fw_version"] == 7,
          repr(res_v2.header))
    check("api: v2 report line carries fw_version",
          any("fw_version=7" in l for l in res_v2.report_lines),
          repr(res_v2.report_lines[:1]))
    check("api: v1 report line marks pre-versioning",
          any("fw_version=pre-versioning" in l for l in res.report_lines),
          repr(res.report_lines[:1]))
    # An unknown future version still hard-errors (v3 is now supported --
    # see test_v3_* below -- so this probes an actually-unsupported version).
    data_v99 = bytearray(data)
    data_v99[4] = 99
    try:
        db.decode_blg(bytes(data_v99))
        check("api: v99 raises ValueError", False, "no exception")
    except ValueError as e:
        check("api: v99 raises ValueError", "unsupported version 99" in str(e))
    check("api: records_read", res.records_read == n)
    check("api: csv_rows count", len(res.csv_rows) == n)
    check("api: trailer dict", res.trailer == {
        "records_written": n + 1, "dropped": 3, "close_reason": 2,
        "close_reason_str": "stop", "error_code": 0, "abandoned": 0},
        repr(res.trailer))
    check("api: mismatch warning present, un-prefixed",
          len(res.warnings) == 1
          and res.warnings[0].startswith("WARNING: trailer records_written")
          and "[decode_benchlog]" not in res.warnings[0],
          repr(res.warnings))

    # report_lines must be exactly what the CLI prints to stderr.
    rc, out, err = run_decoder(path)
    check("api: report_lines == CLI stderr",
          "\n".join(res.report_lines) + "\n" == err,
          f"api={res.report_lines!r} cli={err!r}")
    csv_body = [l for l in out.splitlines()[1:] if l]
    check("api: csv_rows == CLI stdout rows", res.csv_rows == csv_body)

    # Hard errors raise ValueError from the API (the CLI wraps them).
    try:
        db.decode_blg(b"XXXX" + data[4:])
        check("api: bad magic raises ValueError", False, "no exception")
    except ValueError as e:
        check("api: bad magic raises ValueError", "bad magic" in str(e))


def test_v3_basic(tmpdir):
    """(f)(g) v3 header + record decode: record_size=68, fw_version, the
    four new voltage fields at their documented CSV positions, and the
    20-column v3 CSV header."""
    n = 50
    data = pack_header_v3(profile_type=4, fw_version=5)
    for i in range(n):
        data += pack_record_v3(t_us=i * 1000, share_sp=0.4, share_act=0.42,
                                i_fc=1.1, i_batt=0.9, v_fc=12.345,
                                v_batt=8.05, v_chg=12.1, v_rgn=0.55)
    data += pack_trailer(records_written=n, dropped=0, close_reason=1,
                          record_size=RECORD_SIZE_V3)

    path = write_blg(tmpdir, "v3.BLG", data)
    rc, out, err = run_decoder(path)
    lines = out.splitlines()

    check("v3: decoder exits 0", rc == 0, f"rc={rc} stderr={err}")
    check("v3: csv header is the 20-column v3 header",
          lines[0] == CSV_HEADER_V3, lines[0])
    data_rows = lines[1:]
    check("v3: emits all records", len(data_rows) == n,
          f"csv data rows={len(data_rows)}, expected {n}")

    first_fields = data_rows[0].split(",")
    check("v3: row has 20 fields", len(first_fields) == 20,
          repr(first_fields))
    # Column order: t_us,share_sp,share_act,v_sp,v_act,I_fc,I_batt,gFC,gBT,
    # V_bus,I_cmd,V_fc,V_batt,V_chg,V_rgn,fault_flags,ps_phase,dc_phase,
    # trap_phase,flags -- V_fc/V_batt/V_chg/V_rgn are indices 11-14.
    check("v3: V_fc at index 11", abs(float(first_fields[11]) - 12.345) < 1e-4,
          first_fields[11])
    check("v3: V_batt at index 12", abs(float(first_fields[12]) - 8.05) < 1e-4,
          first_fields[12])
    check("v3: V_chg at index 13", abs(float(first_fields[13]) - 12.1) < 1e-4,
          first_fields[13])
    check("v3: V_rgn at index 14", abs(float(first_fields[14]) - 0.55) < 1e-4,
          first_fields[14])

    check("v3: version=3 reported", "version=3" in err, err)
    check("v3: fw_version=5 reported", "fw_version=5" in err, err)
    check("v3: records read == n", f"records read: {n}" in err, err)
    check("v3: trailer found (close_reason=complete)",
          "close_reason=complete" in err, err)
    check("v3: no truncation warning", "WARNING: no trailer" not in err, err)


def test_v3_truncated(tmpdir):
    """(i) v3 brownout: real records followed by garbage/stale tail, no
    trailer -- decoder must stop at the true end and warn about it, using
    the 68 B v3 record stride (mirrors test_brownout for v1/v2)."""
    m = 80
    data = pack_header_v3(profile_type=1)
    for i in range(m):
        data += pack_record_v3(i * 1000)
    data += b"\xAA" * (2 * RECORD_SIZE_V3)
    # No trailer -- simulates a brownout mid-run.

    path = write_blg(tmpdir, "v3_brownout.BLG", data)
    rc, out, err = run_decoder(path)

    lines = [l for l in out.splitlines() if l]
    check("v3 brownout: decoder exits 0", rc == 0, f"rc={rc} stderr={err}")
    check("v3 brownout: stops at true end (m records, not m+2 garbage rows)",
          len(lines) - 1 == m, f"csv data rows={len(lines) - 1}, expected {m}")
    check("v3 brownout: records read == m", f"records read: {m}" in err, err)
    check("v3 brownout: truncation warning present",
          "WARNING: no trailer found" in err, err)
    check("v3 brownout: stopped-at-record warning present",
          f"stopped at record {m}" in err, err)


def test_v3_record_size_mismatch(tmpdir):
    """A v3 header claiming the v1/v2 record_size (52, self-inconsistent
    with version=3) is a hard error, not silently misparsed."""
    data = bytearray(pack_header_v3())
    data[5] = RECORD_SIZE  # corrupt record_size byte: 68 -> 52
    data = bytes(data) + pack_trailer(records_written=0, dropped=0,
                                       close_reason=1,
                                       record_size=RECORD_SIZE_V3)

    path = write_blg(tmpdir, "v3_badsize.BLG", data)
    rc, out, err = run_decoder(path)
    check("v3 bad record_size: decoder exits nonzero", rc != 0, f"rc={rc}")
    check("v3 bad record_size: error names both values",
          "unexpected record_size 52" in err and "expected 68" in err, err)


def test_v4_header_both_valid(tmpdir):
    """v4 header parse: both param-valid bits set -- profile_amp/profile_b
    are decoded and reported in the banner line; record decode is the same
    68 B v3 layout (records reuse pack_record_v3)."""
    sys.path.insert(0, str(HERE))
    import decode_benchlog as db

    n = 20
    data = pack_header_v4(profile_type=2, fw_version=6, param_flags=0x03,
                           profile_amp=6.0, profile_b=0.15)
    for i in range(n):
        data += pack_record_v3(t_us=i * 1000, v_fc=12.5, v_batt=8.1)
    data += pack_trailer(records_written=n, dropped=0, close_reason=1,
                          record_size=RECORD_SIZE_V3)

    res = db.decode_blg(data)
    check("v4 both-valid: version=4", res.header["version"] == 4,
          repr(res.header))
    check("v4 both-valid: profile_amp decoded",
          abs(res.header["profile_amp"] - 6.0) < 1e-5, repr(res.header))
    check("v4 both-valid: profile_b decoded",
          abs(res.header["profile_b"] - 0.15) < 1e-5, repr(res.header))
    check("v4 both-valid: banner has both fields",
          any("profile_amp=6.000" in l and "profile_b=0.150" in l
              for l in res.report_lines),
          repr(res.report_lines[:1]))
    check("v4 both-valid: record decode equals v3 (20 fields, 68 B stride)",
          len(res.csv_rows) == n and len(res.csv_rows[0].split(",")) == 20,
          repr(res.csv_rows[:1]))
    check("v4 both-valid: csv_header is the v3 20-column header",
          res.csv_header == CSV_HEADER_V3, res.csv_header)

    # CLI-level check too, mirroring the API check.
    path = write_blg(tmpdir, "v4_both.BLG", data)
    rc, out, err = run_decoder(path)
    check("v4 both-valid CLI: exits 0", rc == 0, f"rc={rc} stderr={err}")
    check("v4 both-valid CLI: banner has both fields",
          "profile_amp=6.000" in err and "profile_b=0.150" in err, err)
    check("v4 both-valid CLI: version=4 reported", "version=4" in err, err)


def test_v4_header_amp_only(tmpdir):
    """v4 header parse: only profile_amp valid (bit0 set, bit1 clear) --
    profile_b must be None and absent from the banner even though its raw
    float bytes are non-zero garbage."""
    sys.path.insert(0, str(HERE))
    import decode_benchlog as db

    data = pack_header_v4(fw_version=6, param_flags=0x01, profile_amp=3.5,
                           profile_b=0.99)  # profile_b bytes present but bit clear
    data += pack_trailer(records_written=0, dropped=0, close_reason=1,
                          record_size=RECORD_SIZE_V3)

    res = db.decode_blg(data)
    check("v4 amp-only: profile_amp decoded",
          res.header["profile_amp"] is not None
          and abs(res.header["profile_amp"] - 3.5) < 1e-5, repr(res.header))
    check("v4 amp-only: profile_b is None despite non-zero bytes",
          res.header["profile_b"] is None, repr(res.header))
    check("v4 amp-only: banner has amp but not b",
          any("profile_amp=3.500" in l for l in res.report_lines)
          and not any("profile_b=" in l for l in res.report_lines),
          repr(res.report_lines[:1]))


def test_v4_header_neither_valid(tmpdir):
    """v4 header parse: both bits clear -- both params report None and the
    banner carries no profile_amp/profile_b text at all (byte-identical in
    shape to the pre-v4 banner, just with version=4)."""
    sys.path.insert(0, str(HERE))
    import decode_benchlog as db

    data = pack_header_v4(fw_version=6, param_flags=0x00, profile_amp=1.23,
                           profile_b=4.56)
    data += pack_trailer(records_written=0, dropped=0, close_reason=1,
                          record_size=RECORD_SIZE_V3)

    res = db.decode_blg(data)
    check("v4 neither-valid: profile_amp is None",
          res.header["profile_amp"] is None, repr(res.header))
    check("v4 neither-valid: profile_b is None",
          res.header["profile_b"] is None, repr(res.header))
    check("v4 neither-valid: banner has no profile_amp/profile_b text",
          not any("profile_amp=" in l or "profile_b=" in l
                  for l in res.report_lines),
          repr(res.report_lines[:1]))
    check("v4 neither-valid: version=4 still reported",
          any("version=4" in l for l in res.report_lines),
          repr(res.report_lines[:1]))


def test_v4_record_decode_matches_v3(tmpdir):
    """v4 records decode identically to v3 records (same field values at
    the same CSV positions) -- the record format did not change in v4."""
    sys.path.insert(0, str(HERE))
    import decode_benchlog as db

    kwargs = dict(t_us=0, share_sp=0.4, share_act=0.42, i_fc=1.1, i_batt=0.9,
                  v_fc=12.345, v_batt=8.05, v_chg=12.1, v_rgn=0.55)

    data_v3 = pack_header_v3(fw_version=5)
    data_v3 += pack_record_v3(**kwargs)
    data_v3 += pack_trailer(records_written=1, dropped=0, close_reason=1,
                             record_size=RECORD_SIZE_V3)

    data_v4 = pack_header_v4(fw_version=5, param_flags=0x00)
    data_v4 += pack_record_v3(**kwargs)
    data_v4 += pack_trailer(records_written=1, dropped=0, close_reason=1,
                             record_size=RECORD_SIZE_V3)

    res_v3 = db.decode_blg(data_v3)
    res_v4 = db.decode_blg(data_v4)
    check("v4 record decode == v3 record decode (same row content)",
          res_v3.csv_rows == res_v4.csv_rows,
          f"v3={res_v3.csv_rows!r} v4={res_v4.csv_rows!r}")
    check("v4 csv_header == v3 csv_header",
          res_v3.csv_header == res_v4.csv_header)


def test_v4_record_size_mismatch(tmpdir):
    """A v4 header claiming the v1/v2 record_size (52, self-inconsistent
    with version=4) is a hard error, mirroring test_v3_record_size_mismatch."""
    data = bytearray(pack_header_v4())
    data[5] = RECORD_SIZE  # corrupt record_size byte: 68 -> 52
    data = bytes(data) + pack_trailer(records_written=0, dropped=0,
                                       close_reason=1,
                                       record_size=RECORD_SIZE_V3)

    path = write_blg(tmpdir, "v4_badsize.BLG", data)
    rc, out, err = run_decoder(path)
    check("v4 bad record_size: decoder exits nonzero", rc != 0, f"rc={rc}")
    check("v4 bad record_size: error names both values",
          "unexpected record_size 52" in err and "expected 68" in err, err)


def test_v1v2_regression(tmpdir):
    """(j) Regression: v1 and v2 CSV output is byte-for-byte unchanged by
    adding v3 support -- the 16-column header, field order, and field count
    are exactly what they were before v3 existed."""
    # Spelled out literally (not imported from decode_benchlog.CSV_HEADER)
    # so this test does not depend on the module under test to define its
    # own expectation.
    expected_header = ("t_us,share_sp,share_act,v_sp,v_act,I_fc,I_batt,gFC,"
                        "gBT,V_bus,I_cmd,fault_flags,ps_phase,dc_phase,"
                        "trap_phase,flags")

    # v1
    data_v1 = pack_header(profile_type=2)
    for i in range(10):
        data_v1 += pack_record(i * 1000)
    data_v1 += pack_trailer(records_written=10, dropped=0, close_reason=1)
    path = write_blg(tmpdir, "v1_regress.BLG", data_v1)
    rc, out, err = run_decoder(path)
    lines = out.splitlines()
    check("v1 regression: decoder exits 0", rc == 0, f"rc={rc} stderr={err}")
    check("v1 regression: 16-column header unchanged",
          lines[0] == expected_header, lines[0])
    check("v1 regression: row field count is 16",
          len(lines[1].split(",")) == 16, lines[1])
    check("v1 regression: fw_version pre-versioning",
          "fw_version=pre-versioning" in err, err)

    # v2 (mutate a v1 buffer's version byte + stamp fw_version, matching
    # test_decode_blg_api's construction).
    data_v2 = bytearray(data_v1)
    data_v2[4] = 2
    struct.pack_into("<H", data_v2, 18, 9)
    path = write_blg(tmpdir, "v2_regress.BLG", bytes(data_v2))
    rc, out, err = run_decoder(path)
    lines = out.splitlines()
    check("v2 regression: decoder exits 0", rc == 0, f"rc={rc} stderr={err}")
    check("v2 regression: 16-column header unchanged",
          lines[0] == expected_header, lines[0])
    check("v2 regression: row field count is 16",
          len(lines[1].split(",")) == 16, lines[1])
    check("v2 regression: fw_version=9 reported", "fw_version=9" in err, err)


def test_v6_header_and_record(tmpdir):
    """(p)(q) v6 header + record decode: record_size=92, version=6,
    fw_version/profileAmp/profileB carried through the v4 header path
    unmodified, the four new fields at their documented CSV positions
    (indices 17-20, right after u_unsat/drive_x0), and the 26-column v6
    CSV header."""
    sys.path.insert(0, str(HERE))
    import decode_benchlog as db

    n = 30
    data = pack_header_v6(profile_type=8, fw_version=16, param_flags=0x03,
                           profile_amp=2.0, profile_b=0.30)
    for i in range(n):
        data += pack_record_v6(t_us=i * 1000, v_fc=12.345, v_batt=8.05,
                                u_unsat=3.5, drive_x0=0.25,
                                encoder_pos=1000 + i * 2,
                                enc_period_ref_us=4200,
                                enc_multi_pitch_count=7,
                                enc_spurious_drop_count=12)
    data += pack_trailer(records_written=n, dropped=0, close_reason=1,
                          record_size=RECORD_SIZE_V6)

    res = db.decode_blg(data)
    check("v6: header version=6", res.header["version"] == 6,
          repr(res.header))
    check("v6: header record_size=92", res.header["record_size"] == 92,
          repr(res.header))
    check("v6: fw_version=16 carried through v4 header path",
          res.header["fw_version"] == 16, repr(res.header))
    check("v6: profile_amp/profile_b decoded (v4 header path unmodified)",
          abs(res.header["profile_amp"] - 2.0) < 1e-5
          and abs(res.header["profile_b"] - 0.30) < 1e-5, repr(res.header))
    check("v6: csv_header is the 26-column v6 header",
          res.csv_header == CSV_HEADER_V6, res.csv_header)
    check("v6: emits all records", len(res.csv_rows) == n,
          f"csv data rows={len(res.csv_rows)}, expected {n}")

    first_fields = res.csv_rows[0].split(",")
    check("v6: row has 26 fields", len(first_fields) == 26,
          repr(first_fields))
    # Column order: ...V_rgn(14),u_unsat(15),drive_x0(16),encoder_pos(17),
    # enc_period_ref_us(18),enc_multi_pitch_count(19),
    # enc_spurious_drop_count(20),fault_flags(21),...
    check("v6: encoder_pos at index 17",
          first_fields[17] == "1000", first_fields[17])
    check("v6: enc_period_ref_us at index 18",
          first_fields[18] == "4200", first_fields[18])
    check("v6: enc_multi_pitch_count at index 19",
          first_fields[19] == "7", first_fields[19])
    check("v6: enc_spurious_drop_count at index 20",
          first_fields[20] == "12", first_fields[20])

    last_fields = res.csv_rows[-1].split(",")
    check("v6: encoder_pos advances across records (signed count)",
          last_fields[17] == str(1000 + 2 * (n - 1)), last_fields[17])

    # CLI-level check too, mirroring the v4 both-valid CLI check.
    path = write_blg(tmpdir, "v6.BLG", data)
    rc, out, err = run_decoder(path)
    check("v6 CLI: exits 0", rc == 0, f"rc={rc} stderr={err}")
    check("v6 CLI: version=6 reported", "version=6" in err, err)
    check("v6 CLI: records read == n", f"records read: {n}" in err, err)
    check("v6 CLI: trailer found (close_reason=complete)",
          "close_reason=complete" in err, err)


def test_v6_negative_encoder_pos(tmpdir):
    """encoder_pos is a SIGNED i32 -- a reverse-direction run must decode
    a negative value correctly, not wrap to a huge unsigned number."""
    sys.path.insert(0, str(HERE))
    import decode_benchlog as db

    data = pack_header_v6(fw_version=16)
    data += pack_record_v6(t_us=0, encoder_pos=-4200)
    data += pack_trailer(records_written=1, dropped=0, close_reason=1,
                          record_size=RECORD_SIZE_V6)

    res = db.decode_blg(data)
    fields = res.csv_rows[0].split(",")
    check("v6: negative encoder_pos decodes as signed",
          fields[17] == "-4200", fields[17])


def test_v6_record_size_mismatch(tmpdir):
    """A v6 header claiming the v5 record_size (76, self-inconsistent with
    version=6) is a hard error, mirroring (o)/test_v4_record_size_mismatch
    for v4."""
    data = bytearray(pack_header_v6())
    data[5] = RECORD_SIZE_V5  # corrupt record_size byte: 92 -> 76
    data = bytes(data) + pack_trailer(records_written=0, dropped=0,
                                       close_reason=1,
                                       record_size=RECORD_SIZE_V6)

    path = write_blg(tmpdir, "v6_badsize.BLG", data)
    rc, out, err = run_decoder(path)
    check("v6 bad record_size: decoder exits nonzero", rc != 0, f"rc={rc}")
    check("v6 bad record_size: error names both values",
          "unexpected record_size 76" in err and "expected 92" in err, err)


def test_v7_header_and_record(tmpdir):
    """(u)(v) v7 header + record decode: record_size=106, version=7,
    fw_version/profileAmp/profileB carried through the v4 header path
    unmodified, the five new fields at their documented CSV positions
    (indices 21-25, right after enc_spurious_drop_count), the /256
    fixed-point exactness of the three EWMA level columns, and the
    31-column v7 CSV header."""
    sys.path.insert(0, str(HERE))
    import decode_benchlog as db

    n = 30
    data = pack_header_v7(profile_type=8, fw_version=20, param_flags=0x03,
                           profile_amp=2.0, profile_b=0.30)
    for i in range(n):
        data += pack_record_v7(t_us=i * 1000, encoder_pos=1000 + i * 2,
                                enc_period_ref_us=4200,
                                enc_multi_pitch_count=7,
                                enc_spurious_drop_count=12,
                                enc_edge_count_a=100_000 + i * 4,
                                enc_edge_count_b=100_150 + i * 4,
                                enc_phase_ewma=64, enc_duty_a_ewma=128,
                                enc_duty_b_ewma=131)
    data += pack_trailer(records_written=n, dropped=0, close_reason=1,
                          record_size=RECORD_SIZE_V7)

    res = db.decode_blg(data)
    check("v7: header version=7", res.header["version"] == 7,
          repr(res.header))
    check("v7: header record_size=106", res.header["record_size"] == 106,
          repr(res.header))
    check("v7: fw_version=20 carried through v4 header path",
          res.header["fw_version"] == 20, repr(res.header))
    check("v7: profile_amp/profile_b decoded (v4 header path unmodified)",
          abs(res.header["profile_amp"] - 2.0) < 1e-5
          and abs(res.header["profile_b"] - 0.30) < 1e-5, repr(res.header))
    check("v7: csv_header is the 31-column v7 header",
          res.csv_header == CSV_HEADER_V7, res.csv_header)
    check("v7: emits all records", len(res.csv_rows) == n,
          f"csv data rows={len(res.csv_rows)}, expected {n}")

    first_fields = res.csv_rows[0].split(",")
    check("v7: row has 31 fields", len(first_fields) == 31,
          repr(first_fields))
    # Column order: ...enc_spurious_drop_count(20),enc_edge_count_a(21),
    # enc_edge_count_b(22),enc_phase_ewma(23),enc_duty_a_ewma(24),
    # enc_duty_b_ewma(25),fault_flags(26),...
    check("v7: v6 fields keep their positions (encoder_pos at 17, "
          "enc_spurious_drop_count at 20)",
          first_fields[17] == "1000" and first_fields[20] == "12",
          repr(first_fields[17:21]))
    check("v7: enc_edge_count_a at index 21",
          first_fields[21] == "100000", first_fields[21])
    check("v7: enc_edge_count_b at index 22",
          first_fields[22] == "100150", first_fields[22])
    check("v7: enc_phase_ewma at index 23 is fp64/256 = 0.25 EXACTLY",
          first_fields[23] == "0.25", first_fields[23])
    check("v7: enc_duty_a_ewma at index 24 is fp128/256 = 0.5 EXACTLY",
          first_fields[24] == "0.5", first_fields[24])
    check("v7: enc_duty_b_ewma at index 25 is fp131/256 = 0.51171875",
          first_fields[25] == "0.51171875", first_fields[25])

    last_fields = res.csv_rows[-1].split(",")
    check("v7: edge counters advance across records (cumulative)",
          last_fields[21] == str(100_000 + 4 * (n - 1))
          and last_fields[22] == str(100_150 + 4 * (n - 1)),
          repr(last_fields[21:23]))

    # CLI-level check too, mirroring the v6 CLI check.
    path = write_blg(tmpdir, "v7.BLG", data)
    rc, out, err = run_decoder(path)
    check("v7 CLI: exits 0", rc == 0, f"rc={rc} stderr={err}")
    check("v7 CLI: version=7 reported", "version=7" in err, err)
    check("v7 CLI: records read == n", f"records read: {n}" in err, err)
    check("v7 CLI: trailer found (close_reason=complete)",
          "close_reason=complete" in err, err)


def test_v7_near_wrap_edge_counters(tmpdir):
    """(w) The edge counters are boot-monotonic u32s -- a value near the
    uint32 wrap must decode as a large UNSIGNED value (a later negative
    DIFF is the consumer's wrap/reset signal, not a decode transform)."""
    sys.path.insert(0, str(HERE))
    import decode_benchlog as db

    data = pack_header_v7(fw_version=20)
    data += pack_record_v7(t_us=0, enc_edge_count_a=0xFFFFFFF0,
                            enc_edge_count_b=0xFFFFFFFF)
    # A post-wrap second record: counters numerically SMALLER than the
    # first -- must still decode verbatim (no unwrap correction).
    data += pack_record_v7(t_us=1000, enc_edge_count_a=5,
                            enc_edge_count_b=2)
    data += pack_trailer(records_written=2, dropped=0, close_reason=1,
                          record_size=RECORD_SIZE_V7)

    res = db.decode_blg(data)
    f0 = res.csv_rows[0].split(",")
    f1 = res.csv_rows[1].split(",")
    check("v7: near-wrap enc_edge_count_a decodes unsigned",
          f0[21] == str(0xFFFFFFF0), f0[21])
    check("v7: max-u32 enc_edge_count_b decodes unsigned",
          f0[22] == str(0xFFFFFFFF), f0[22])
    check("v7: post-wrap smaller values decode verbatim (no unwrap)",
          f1[21] == "5" and f1[22] == "2", repr(f1[21:23]))


def test_v7_record_size_mismatch(tmpdir):
    """(x) A v7 header claiming the v6 record_size (92, self-inconsistent
    with version=7) is a hard error, mirroring test_v6_record_size_mismatch."""
    data = bytearray(pack_header_v7())
    data[5] = RECORD_SIZE_V6  # corrupt record_size byte: 106 -> 92
    data = bytes(data) + pack_trailer(records_written=0, dropped=0,
                                       close_reason=1,
                                       record_size=RECORD_SIZE_V7)

    path = write_blg(tmpdir, "v7_badsize.BLG", data)
    rc, out, err = run_decoder(path)
    check("v7 bad record_size: decoder exits nonzero", rc != 0, f"rc={rc}")
    check("v7 bad record_size: error names both values",
          "unexpected record_size 92" in err and "expected 106" in err, err)


def test_hil_build_flag(tmpdir):
    """(z) flags bit6 (0x40, fw v21 HIL_SIM build) is surfaced as
    header["hil_build"] -- true if ANY record has the bit set, false if
    none do -- plus a WARNING line/banner note when true, mirroring how
    bit4/bit5 are simply passed through raw in the CSV `flags` column
    (verified here too: bit6 does not disturb bit0-bit5 in the same
    byte). Exercised on v5/v6/v7 (the only formats with a flags byte that
    can plausibly be fw v21+)."""
    sys.path.insert(0, str(HERE))
    import decode_benchlog as db

    # (1) bit6 clear on every record: hil_build False, no warning, CSV
    # flags column carries the untouched byte through (0x03: fault/
    # velocity-valid bits only, no drive/share/hil bits).
    data = pack_header_v7(fw_version=20)
    for i in range(5):
        data += pack_record_v7(t_us=i * 1000, flags=0x03)
    data += pack_trailer(records_written=5, dropped=0, close_reason=1,
                          record_size=RECORD_SIZE_V7)
    res = db.decode_blg(data)
    check("hil_build: false when no record has bit6 set",
          res.header["hil_build"] is False, repr(res.header))
    check("hil_build: no HIL warning when bit6 clear",
          not any("HIL_SIM" in w for w in res.warnings), repr(res.warnings))
    check("hil_build: CSV flags column untouched (0x03) when bit6 clear",
          res.csv_rows[0].split(",")[-1] == "3", res.csv_rows[0])

    # (2) bit6 set on every record, combined with bit4/bit5 (0x40|0x10|0x20
    # = 0x70) -- hil_build True, warning present, and the CSV flags column
    # carries the FULL byte through raw (bit6 coexists with bit4/bit5
    # exactly like it coexists with bit0-bit3).
    data = pack_header_v7(fw_version=21)
    for i in range(5):
        data += pack_record_v7(t_us=i * 1000, flags=0x70)
    data += pack_trailer(records_written=5, dropped=0, close_reason=1,
                          record_size=RECORD_SIZE_V7)
    res = db.decode_blg(data)
    check("hil_build: true when every record has bit6 set",
          res.header["hil_build"] is True, repr(res.header))
    check("hil_build: HIL warning present when bit6 set",
          any("HIL_SIM" in w and "WARNING" in w for w in res.warnings),
          repr(res.warnings))
    check("hil_build: warning also flows through report_lines (CLI stderr)",
          any("HIL_SIM" in l for l in res.report_lines),
          repr(res.report_lines))
    check("hil_build: CSV flags column carries the full byte (0x70) through",
          res.csv_rows[0].split(",")[-1] == str(0x70), res.csv_rows[0])

    # (3) bit6 set on only ONE of several records: still detected (the
    # header-level flag is an ANY-record OR, not an all-records AND).
    data = pack_header_v7(fw_version=21)
    for i in range(5):
        data += pack_record_v7(t_us=i * 1000,
                                flags=(0x40 if i == 3 else 0x00))
    data += pack_trailer(records_written=5, dropped=0, close_reason=1,
                          record_size=RECORD_SIZE_V7)
    res = db.decode_blg(data)
    check("hil_build: true when only ONE record has bit6 set",
          res.header["hil_build"] is True, repr(res.header))

    # (4) v5 and v6 (not just v7) surface the same header field -- the flags
    # byte lives at the same offset in every record format that has one.
    data_v5 = pack_header_v5(fw_version=21)
    data_v5 += pack_record_v5(t_us=0, flags=0x40)
    data_v5 += pack_trailer(records_written=1, dropped=0, close_reason=1,
                             record_size=RECORD_SIZE_V5)
    res_v5 = db.decode_blg(data_v5)
    check("hil_build: v5 surfaces hil_build too",
          res_v5.header["hil_build"] is True, repr(res_v5.header))

    data_v6 = pack_header_v6(fw_version=21)
    data_v6 += pack_record_v6(t_us=0, flags=0x40)
    data_v6 += pack_trailer(records_written=1, dropped=0, close_reason=1,
                             record_size=RECORD_SIZE_V6)
    res_v6 = db.decode_blg(data_v6)
    check("hil_build: v6 surfaces hil_build too",
          res_v6.header["hil_build"] is True, repr(res_v6.header))


def test_v6_regression(tmpdir):
    """(y) Regression: v6 header + 26-column CSV decode is unchanged after
    adding v7 support -- same header path, same RECORD_FMT_V6/
    RECORD_SIZE_V6/CSV_HEADER_V6 as before v7 existed."""
    sys.path.insert(0, str(HERE))
    import decode_benchlog as db

    n = 25
    data = pack_header_v6(profile_type=4, fw_version=16, param_flags=0x03,
                           profile_amp=1.5, profile_b=0.20)
    for i in range(n):
        data += pack_record_v6(t_us=i * 1000, encoder_pos=42,
                                enc_period_ref_us=5000,
                                enc_multi_pitch_count=1,
                                enc_spurious_drop_count=2)
    data += pack_trailer(records_written=n, dropped=0, close_reason=1,
                          record_size=RECORD_SIZE_V6)

    res = db.decode_blg(data)
    check("v6 regression: version=6", res.header["version"] == 6,
          repr(res.header))
    check("v6 regression: record_size=92", res.header["record_size"] == 92,
          repr(res.header))
    check("v6 regression: csv_header is the 26-column v6 header",
          res.csv_header == CSV_HEADER_V6, res.csv_header)
    check("v6 regression: row has 26 fields (no v7 columns leaked in)",
          len(res.csv_rows[0].split(",")) == 26,
          repr(res.csv_rows[0].split(",")))


def test_v5_regression(tmpdir):
    """(s) Regression: v5 header + 22-column CSV decode is byte-for-byte
    unchanged after adding v6 support -- same header path, same
    RECORD_FMT_V5/RECORD_SIZE_V5/CSV_HEADER_V5 as before v6 existed."""
    sys.path.insert(0, str(HERE))
    import decode_benchlog as db

    n = 25
    data = pack_header_v5(profile_type=4, fw_version=11, param_flags=0x03,
                           profile_amp=1.5, profile_b=0.20)
    for i in range(n):
        data += pack_record_v5(t_us=i * 1000, v_fc=12.5, v_batt=8.1,
                                u_unsat=5.0, drive_x0=0.1)
    data += pack_trailer(records_written=n, dropped=0, close_reason=1,
                          record_size=RECORD_SIZE_V5)

    res = db.decode_blg(data)
    check("v5 regression: version=5", res.header["version"] == 5,
          repr(res.header))
    check("v5 regression: record_size=76", res.header["record_size"] == 76,
          repr(res.header))
    check("v5 regression: csv_header is the 22-column v5 header",
          res.csv_header == CSV_HEADER_V5, res.csv_header)
    check("v5 regression: emits all records", len(res.csv_rows) == n,
          f"csv data rows={len(res.csv_rows)}, expected {n}")
    check("v5 regression: row has 22 fields (no v6 columns leaked in)",
          len(res.csv_rows[0].split(",")) == 22,
          repr(res.csv_rows[0].split(",")))

    path = write_blg(tmpdir, "v5_regress.BLG", data)
    rc, out, err = run_decoder(path)
    check("v5 regression CLI: exits 0", rc == 0, f"rc={rc} stderr={err}")
    check("v5 regression CLI: version=5 reported", "version=5" in err, err)


def test_v5_real_log_regression(tmpdir):
    """(t) logs/ML0146.BLG (a real checked-in fw v14 capture) decodes to
    CSV content byte-for-byte identical to the committed
    logs/ML0146/ML0146.csv. Unlike test_v5_regression (s), which packs and
    decodes synthetic vectors built from this SAME test file's assumptions
    about the v5 layout, this exercises the actual firmware-written bytes
    against the actual previously-committed decoder output -- a v6-round
    regression that flips a v5 field order or column position would be
    caught here even if it happened to keep (s) self-consistent.

    SKIPPED (not FAILED) if either file is absent -- the tooling must not
    require logs/ to exist, e.g. in a sparse checkout."""
    blg_path = REPO_ROOT / "logs" / "ML0146.BLG"
    csv_path = REPO_ROOT / "logs" / "ML0146" / "ML0146.csv"
    if not blg_path.is_file():
        skip("v5 real-log regression", f"{blg_path} not present (sparse checkout?)")
        return
    if not csv_path.is_file():
        skip("v5 real-log regression", f"{csv_path} not present (sparse checkout?)")
        return

    rc, out, err = run_decoder(blg_path)
    check("v5 real-log regression: decoder exits 0", rc == 0,
          f"rc={rc} stderr={err}")

    with open(csv_path, "r", newline="") as f:
        expected_csv = f.read()

    check("v5 real-log regression: CSV content byte-for-byte identical "
          "to logs/ML0146/ML0146.csv",
          out == expected_csv,
          f"produced {len(out)} bytes, expected {len(expected_csv)} bytes "
          f"(first mismatch context omitted -- compare files directly)")
    check("v5 real-log regression: header line is the 22-column v5 header",
          out.splitlines()[0] == CSV_HEADER_V5 if out else False,
          out.splitlines()[0] if out else "<empty>")


def main():
    if not DECODER.exists():
        print(f"FAIL: decoder not found at {DECODER}")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        test_wrap_straddle(tmpdir)
        test_brownout(tmpdir)
        test_io_error_close_reason(tmpdir)
        test_gap_statistics(tmpdir)
        test_decode_blg_api(tmpdir)
        test_v3_basic(tmpdir)
        test_v3_truncated(tmpdir)
        test_v3_record_size_mismatch(tmpdir)
        test_v4_header_both_valid(tmpdir)
        test_v4_header_amp_only(tmpdir)
        test_v4_header_neither_valid(tmpdir)
        test_v4_record_decode_matches_v3(tmpdir)
        test_v4_record_size_mismatch(tmpdir)
        test_v1v2_regression(tmpdir)
        test_v6_header_and_record(tmpdir)
        test_v6_negative_encoder_pos(tmpdir)
        test_v6_record_size_mismatch(tmpdir)
        test_v7_header_and_record(tmpdir)
        test_v7_near_wrap_edge_counters(tmpdir)
        test_v7_record_size_mismatch(tmpdir)
        test_hil_build_flag(tmpdir)
        test_v6_regression(tmpdir)
        test_v5_regression(tmpdir)
        test_v5_real_log_regression(tmpdir)

    total = _passed + _failed
    print(f"\n{_passed}/{total} passed" +
          (f" ({_skipped} skipped)" if _skipped else ""))
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
