#!/usr/bin/env python3
"""Stdlib-only self-test for decode_benchlog.py.

Generates synthetic .BLG files in a temp dir and runs the real decoder
against them as a subprocess (exactly how a user invokes it), asserting on
its stdout (CSV) and stderr (diagnostics). No pytest/unittest dependency,
in the spirit of the C++ host-native suite (test/test_main.cpp): plain
assert() + a PASS/FAIL counter.

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
"""
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECODER = HERE / "decode_benchlog.py"

MAGIC = b"BLG1"
HEADER_FMT = "<4sBBBBIIH"
HEADER_SIZE = 32
RECORD_FMT = "<I10fHBBBB2x"
RECORD_SIZE = 52
TRAILER_FMT = "<IIIBBI"

_passed = 0
_failed = 0


def check(name, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"PASS: {name}")
    else:
        _failed += 1
        print(f"FAIL: {name}" + (f" -- {detail}" if detail else ""))


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
                  abandoned=0):
    body = struct.pack(TRAILER_FMT, 0xFFFFFFFF, records_written, dropped,
                        close_reason, error_code, abandoned)
    body += b"\x00" * (RECORD_SIZE - len(body))
    assert len(body) == RECORD_SIZE
    return body


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
        "fw_version": None},
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
    # An unknown future version still hard-errors.
    data_v3 = bytearray(data)
    data_v3[4] = 3
    try:
        db.decode_blg(bytes(data_v3))
        check("api: v3 raises ValueError", False, "no exception")
    except ValueError as e:
        check("api: v3 raises ValueError", "unsupported version 3" in str(e))
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

    total = _passed + _failed
    print(f"\n{_passed}/{total} passed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
