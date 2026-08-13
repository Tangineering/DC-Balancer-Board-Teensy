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

Format-v3 coverage (fw v5 round, adds V_fc/V_batt/V_chg/V_rgn):
  (f) v3 header parse (record_size=68, fw_version).
  (g) v3 record decode, including the four new voltage fields, and CSV
      column count/order.
  (h) v3 trailer detection (same sentinel mechanism, now inside a 68 B
      record).
  (i) v3 truncated-file handling (brownout path, mirrors (b)).
  (j) regression: v1/v2 decoding is byte-for-byte unchanged after adding
      v3 support.
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
RECORD_FMT_V3 = "<I14fHBBBB2x"
RECORD_SIZE_V3 = 68
TRAILER_FMT = "<IIIBBI"
CSV_HEADER_V3 = ("t_us,share_sp,share_act,v_sp,v_act,I_fc,I_batt,gFC,gBT,"
                  "V_bus,I_cmd,V_fc,V_batt,V_chg,V_rgn,fault_flags,ps_phase,"
                  "dc_phase,trap_phase,flags")

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
        test_v1v2_regression(tmpdir)

    total = _passed + _failed
    print(f"\n{_passed}/{total} passed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
