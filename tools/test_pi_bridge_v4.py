"""Conformance tests: Raspberry Pi bridge parser vs. firmware protocol v4.

The firmware side is authoritative. Two anchors define it:

  * ``teensy_controller/teensy_controller.ino`` ``sendTelemetry()`` — 58-byte
    telemetry packet, SYNC 0xAA, checksum = XOR of bytes 1..56 stored at byte 57.
  * ``teensy_controller/teensy_controller.ino`` ``processPiCommandPacket()`` —
    22-byte command packet, SYNC 0xBB, checksum = XOR of bytes 1..20 at byte 21.

The Pi side is a reference copy of the PhD student's code under
``references/EMS/Pi_2026-09-01/``. It is not executed here (it imports ROS 2);
the tests read the source text and regex-extract its declared constants, then
exercise those constants against packets built exactly as the firmware builds
them. An edit on either side that breaks agreement fails a test.

Every test skips cleanly when the reference drop is absent.

Stdlib only. Run with::

    .venv_hil\\Scripts\\python.exe -m pytest tools/test_pi_bridge_v4.py -q
"""

import re
import struct
from pathlib import Path

import pytest

# ── Reference-source locations ────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
PI_ROOT = REPO_ROOT / "references" / "EMS" / "Pi_2026-09-01" / "EMS"
BRIDGE_PY = PI_ROOT / "ROS2" / "teensy_bridge_node_2026-08-17A.py"
SDP_NODE_PY = PI_ROOT / "ROS2" / "sdp_ems_node_2026-03-16A.py"
INO = REPO_ROOT / "teensy_controller" / "teensy_controller.ino"

# ── Firmware-authoritative protocol constants ─────────────────────────────────
SYNC_BYTE_TX = 0xAA          # .ino:2899
SYNC_BYTE_RX = 0xBB          # .ino:2900
TELEMETRY_VERSION = 4        # .ino:1825
TELEMETRY_SIZE = 58          # sendTelemetry(), .ino:5614
TELEMETRY_CKSUM_LO = 1       # XOR span start, .ino:5658
TELEMETRY_CKSUM_HI = 57      # XOR span end (exclusive), .ino:5658
COMMAND_SIZE = 22            # processPiCommandPacket(), .ino:5433
COMMAND_CKSUM_HI = 21        # XOR span end (exclusive), .ino:5439

# (offset, width, name) for every telemetry field, from the sendTelemetry()
# block comment at .ino:5585-5612.
TELEMETRY_FIELDS = [
    (0, 1, "sync"),
    (1, 4, "timestamp_ms"),
    (5, 2, "pkt_counter_T"),
    (7, 4, "v_actual"),
    (11, 4, "V_batt"),
    (15, 4, "I_batt"),
    (19, 4, "I_charge"),
    (23, 4, "V_fc"),
    (27, 4, "I_fc"),
    (31, 4, "V_bus"),
    (35, 4, "V_rgn"),
    (39, 4, "V_chg"),
    (43, 4, "power_share_actual"),
    (47, 2, "droop_FC_q16"),
    (49, 2, "droop_BT_q16"),
    (51, 1, "charger_status"),
    (52, 1, "switch_state"),
    (53, 2, "fault_flags"),
    (55, 1, "error_code"),
    (56, 1, "error_source_state"),
    (57, 1, "checksum"),
]

# The 18-element /vehicle_state layout the v4 bridge publishes
# (teensy_bridge_node_2026-08-17A.py:298-317).
VEHICLE_STATE_LEN_V4 = 18
VS_IDX_SWITCH_STATE = 13
VS_IDX_FAULT_FLAGS = 14
VS_IDX_SOC = 17
# The superseded 15-element layout the stale SDP node still assumes.
VEHICLE_STATE_LEN_V1 = 15
VS_V1_IDX_FAULT_FLAGS = 13
VS_V1_IDX_SOC = 14


def _require(path: Path) -> str:
    if not path.is_file():
        pytest.skip(f"reference source absent: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def _xor(data: bytes) -> int:
    r = 0
    for b in data:
        r ^= b
    return r


# ── (a) Constants extracted from the bridge source ────────────────────────────

def _bridge_src() -> str:
    return _require(BRIDGE_PY)


def _extract_t2p_fmt(src: str) -> str:
    """Return the literal T2P_FMT value, evaluating the ``"f" * 10`` idiom."""
    m = re.search(r'^T2P_FMT\s*=\s*(.+)$', src, re.M)
    assert m, "T2P_FMT assignment not found in bridge source"
    expr = m.group(1).split("#")[0].strip()
    # The expression is a concatenation of string literals and "lit" * N terms.
    out = []
    for term in expr.split("+"):
        term = term.strip()
        rep = re.fullmatch(r'"([^"]*)"\s*\*\s*(\d+)', term)
        lit = re.fullmatch(r'"([^"]*)"', term)
        if rep:
            out.append(rep.group(1) * int(rep.group(2)))
        elif lit:
            out.append(lit.group(1))
        else:
            raise AssertionError(f"unparsable T2P_FMT term: {term!r}")
    return "".join(out)


def test_bridge_declares_v4_telemetry_size():
    src = _bridge_src()
    m = re.search(r'assert\s+T2P_SIZE\s*==\s*(\d+)', src)
    assert m, "T2P_SIZE assertion not found"
    assert int(m.group(1)) == TELEMETRY_SIZE


def test_bridge_t2p_fmt_matches_firmware_layout():
    fmt = _extract_t2p_fmt(_bridge_src())
    assert fmt == "<BIH" + "f" * 10 + "HHBBHBBB"
    assert struct.calcsize(fmt) == TELEMETRY_SIZE
    # Field widths, in order, must reproduce the firmware offset table.
    widths = [struct.calcsize("<" + c) for c in fmt[1:]]
    offsets, acc = [], 0
    for w in widths:
        offsets.append((acc, w))
        acc += w
    assert offsets == [(o, w) for o, w, _ in TELEMETRY_FIELDS]


def test_bridge_sync_bytes_match_firmware():
    src = _bridge_src()
    tx = re.search(r'^TEENSY_HEADER\s*=\s*(0x[0-9A-Fa-f]+)', src, re.M)
    rx = re.search(r'^PI_HEADER\s*=\s*(0x[0-9A-Fa-f]+)', src, re.M)
    assert tx and rx
    assert int(tx.group(1), 16) == SYNC_BYTE_TX
    assert int(rx.group(1), 16) == SYNC_BYTE_RX


def test_bridge_checksum_span_is_bytes_1_to_56():
    """The bridge verifies XOR(chunk[1:-1]) — identical to the firmware span."""
    src = _bridge_src()
    assert re.search(r'_xor\(chunk\[1:-1\]\)\s*!=\s*chunk\[-1\]', src), \
        "bridge telemetry checksum span is not XOR(bytes 1..56)"


def test_bridge_command_pack_format():
    src = _bridge_src()
    decl = re.search(r'^P2T_FMT\s*=\s*"([^"]+)"', src, re.M)
    assert decl and decl.group(1) == "<BIHfffBBB"
    assert struct.calcsize(decl.group(1)) == COMMAND_SIZE
    # The payload actually packed is one byte shorter; the XOR byte is appended.
    m = re.search(r'struct\.pack\(\s*\n?\s*"(<BIHfffBB)"', src)
    assert m, "command payload pack format not found"
    assert struct.calcsize(m.group(1)) == COMMAND_SIZE - 1
    assert re.search(r'struct\.pack\("B",\s*_xor\(payload\[1:\]\)\)', src), \
        "command checksum is not XOR over bytes 1..20"


def test_firmware_anchors_still_hold():
    """Guard against the firmware side moving without this file moving."""
    if not INO.is_file():
        pytest.skip("firmware source absent")
    src = INO.read_text(encoding="utf-8", errors="replace")
    assert "#define TELEMETRY_VERSION 4" in src
    assert "const uint8_t  SYNC_BYTE_TX = 0xAA;" in src
    assert "const uint8_t  SYNC_BYTE_RX = 0xBB;" in src
    assert "uint8_t packet[58];" in src
    assert "for (int i = 1; i < 57; i++) checksum ^= packet[i];" in src
    assert "for (int i = 1; i < 21; i++) checksum ^= buffer[i];" in src


# ── (b) Telemetry round trip ──────────────────────────────────────────────────

# Distinct sentinel per field, so a swapped pair cannot pass.
TLM_SENTINELS = dict(
    timestamp_ms=0x11223344,
    pkt_counter_T=0x5566,
    v_actual=1.5,
    V_batt=7.75,
    I_batt=2.25,
    I_charge=0.375,
    V_fc=11.125,
    I_fc=0.875,
    V_bus=15.9375,
    V_rgn=13.5,
    V_chg=14.25,
    power_share_actual=0.625,
    droop_FC_q16=0x1234,
    droop_BT_q16=0x4321,
    charger_status=0x49,          # GENSTAT 1, MPPT enabled, CC set
    switch_state=0x2D,
    fault_flags=0x8010,           # FAULT_ERROR | FAULT_PI_TIMEOUT
    error_code=0x0F,              # ERR_MOT_HOTPLUG
    error_source_state=2,
)


def build_telemetry_packet(**overrides) -> bytearray:
    """Build a 58-byte packet byte-for-byte as sendTelemetry() does."""
    f = dict(TLM_SENTINELS)
    f.update(overrides)
    p = bytearray()
    p.append(SYNC_BYTE_TX)
    p += struct.pack("<I", f["timestamp_ms"])
    p += struct.pack("<H", f["pkt_counter_T"])
    for name in ("v_actual", "V_batt", "I_batt", "I_charge", "V_fc", "I_fc",
                 "V_bus", "V_rgn", "V_chg", "power_share_actual"):
        p += struct.pack("<f", f[name])
    p += struct.pack("<H", f["droop_FC_q16"])
    p += struct.pack("<H", f["droop_BT_q16"])
    p.append(f["charger_status"])
    p.append(f["switch_state"])
    p += struct.pack("<H", f["fault_flags"])
    p.append(f["error_code"])
    p.append(f["error_source_state"])
    assert len(p) == TELEMETRY_CKSUM_HI
    p.append(_xor(p[TELEMETRY_CKSUM_LO:TELEMETRY_CKSUM_HI]))
    assert len(p) == TELEMETRY_SIZE
    return p


def test_telemetry_packet_is_58_bytes():
    assert len(build_telemetry_packet()) == TELEMETRY_SIZE


def test_bridge_format_parses_every_telemetry_field():
    fmt = _extract_t2p_fmt(_bridge_src())
    pkt = build_telemetry_packet()
    (sync, ts, ctr, v, vb, ib, ic, vfc, ifc, vbus, vrgn, vchg, sha,
     dfc, dbt, chg_status, sw_state, flt, err_code, err_src, cs) = \
        struct.unpack(fmt, bytes(pkt))

    assert sync == SYNC_BYTE_TX
    assert ts == TLM_SENTINELS["timestamp_ms"]
    assert ctr == TLM_SENTINELS["pkt_counter_T"]
    assert v == TLM_SENTINELS["v_actual"]
    assert vb == TLM_SENTINELS["V_batt"]
    assert ib == TLM_SENTINELS["I_batt"]
    assert ic == TLM_SENTINELS["I_charge"]
    assert vfc == TLM_SENTINELS["V_fc"]
    assert ifc == TLM_SENTINELS["I_fc"]
    assert vbus == TLM_SENTINELS["V_bus"]
    assert vrgn == TLM_SENTINELS["V_rgn"]
    assert vchg == TLM_SENTINELS["V_chg"]
    assert sha == TLM_SENTINELS["power_share_actual"]
    assert dfc == TLM_SENTINELS["droop_FC_q16"]
    assert dbt == TLM_SENTINELS["droop_BT_q16"]
    assert chg_status == TLM_SENTINELS["charger_status"]
    assert sw_state == TLM_SENTINELS["switch_state"]
    assert flt == TLM_SENTINELS["fault_flags"]
    assert err_code == TLM_SENTINELS["error_code"]
    assert err_src == TLM_SENTINELS["error_source_state"]
    assert cs == pkt[-1]


def test_tail_fields_land_at_their_firmware_offsets():
    pkt = build_telemetry_packet()
    assert pkt[51] == TLM_SENTINELS["charger_status"]
    assert pkt[52] == TLM_SENTINELS["switch_state"]
    assert struct.unpack_from("<H", pkt, 53)[0] == TLM_SENTINELS["fault_flags"]
    assert pkt[53] == 0x10 and pkt[54] == 0x80          # little-endian u16
    assert pkt[55] == TLM_SENTINELS["error_code"]
    assert pkt[56] == TLM_SENTINELS["error_source_state"]


def test_droop_gains_are_raw_q16_counts():
    """The packet carries counts; the bridge publishes them unscaled."""
    pkt = build_telemetry_packet(droop_FC_q16=65535, droop_BT_q16=0)
    fmt = _extract_t2p_fmt(_bridge_src())
    dfc, dbt = struct.unpack(fmt, bytes(pkt))[13:15]
    assert (dfc, dbt) == (65535, 0)
    # Firmware mapping: u16 = constrain(gain, 0, 1) * 65535.
    assert dfc / 65535.0 == pytest.approx(1.0)


def test_bridge_checksum_verification_accepts_a_good_packet():
    pkt = build_telemetry_packet()
    assert _xor(pkt[1:-1]) == pkt[-1]


# ── (c) Command round trip ────────────────────────────────────────────────────

def build_command_packet(v_sp=1.25, pshare=0.75, chg=1.0, mode=0, droop_en=1,
                         ts=0x00ABCDEF, ctr=0x0102) -> bytes:
    """Build a 22-byte command exactly as the bridge's _send_udp_cmd() does."""
    payload = struct.pack("<BIHfffBB", SYNC_BYTE_RX, ts, ctr,
                          float(v_sp), float(pshare), float(chg),
                          int(mode), int(droop_en))
    return payload + struct.pack("B", _xor(payload[1:]))


def parse_command_like_firmware(buf: bytes):
    """Mirror processPiCommandPacket() (.ino:5433-5491). None = rejected."""
    if len(buf) != COMMAND_SIZE:
        return None
    if buf[0] != SYNC_BYTE_RX:
        return None
    if _xor(buf[1:COMMAND_CKSUM_HI]) != buf[COMMAND_CKSUM_HI]:
        return None
    idx = 1
    timestamp = struct.unpack_from("<I", buf, idx)[0]; idx += 4
    pkt_counter = struct.unpack_from("<H", buf, idx)[0]; idx += 2
    v_sp = struct.unpack_from("<f", buf, idx)[0]; idx += 4
    share_sp = struct.unpack_from("<f", buf, idx)[0]; idx += 4
    charge = struct.unpack_from("<f", buf, idx)[0]; idx += 4
    mode_cmd = buf[idx]; idx += 1
    droop_enable_reserved = buf[idx]; idx += 1
    assert idx == COMMAND_CKSUM_HI
    return dict(timestamp=timestamp, pkt_counter=pkt_counter, v_setpoint=v_sp,
                power_share_setpoint=share_sp, charge_goal=charge,
                mode_cmd=mode_cmd, droop_enable_reserved=droop_enable_reserved)


def test_command_packet_is_22_bytes():
    assert len(build_command_packet()) == COMMAND_SIZE


def test_command_round_trip_field_order():
    pkt = build_command_packet(v_sp=-2.5, pshare=0.25, chg=0.5, mode=3,
                               droop_en=1, ts=0x0000BEEF, ctr=0x0007)
    got = parse_command_like_firmware(pkt)
    assert got is not None
    assert got["timestamp"] == 0x0000BEEF
    assert got["pkt_counter"] == 0x0007
    assert got["v_setpoint"] == -2.5
    assert got["power_share_setpoint"] == 0.25
    assert got["charge_goal"] == 0.5
    assert got["mode_cmd"] == 3
    assert got["droop_enable_reserved"] == 1


def test_command_droop_enable_byte_is_reserved_in_firmware():
    """Byte 21 is parsed then discarded (.ino:5477-5479)."""
    if not INO.is_file():
        pytest.skip("firmware source absent")
    src = INO.read_text(encoding="utf-8", errors="replace")
    assert "uint8_t droop_enable_reserved = buffer[idx++];" in src
    assert "(void)droop_enable_reserved;" in src
    # Both encodings must parse identically apart from that byte.
    a = parse_command_like_firmware(build_command_packet(droop_en=0))
    b = parse_command_like_firmware(build_command_packet(droop_en=1))
    assert a is not None and b is not None
    a.pop("droop_enable_reserved"); b.pop("droop_enable_reserved")
    assert a == b


# ── (d) Negative cases ────────────────────────────────────────────────────────

def test_corrupted_telemetry_checksum_is_rejected():
    pkt = build_telemetry_packet()
    pkt[20] ^= 0x01                       # flip a bit inside the XOR span
    assert _xor(pkt[1:-1]) != pkt[-1]


def test_telemetry_bytes_outside_span_are_not_covered():
    """Byte 0 (sync) is outside the XOR span — the firmware span starts at 1."""
    pkt = build_telemetry_packet()
    good = _xor(pkt[1:-1])
    pkt[0] = 0x00
    assert _xor(pkt[1:-1]) == good


def test_wrong_telemetry_sync_is_rejected_by_the_bridge_scan():
    src = _bridge_src()
    assert re.search(r'if\s+data\[s\]\s*!=\s*TEENSY_HEADER', src)
    pkt = build_telemetry_packet()
    pkt[0] = 0xAB
    assert pkt[0] != SYNC_BYTE_TX


def test_wrong_command_sync_is_rejected():
    pkt = bytearray(build_command_packet())
    pkt[0] = 0xAA
    assert parse_command_like_firmware(bytes(pkt)) is None


def test_corrupted_command_checksum_is_rejected():
    pkt = bytearray(build_command_packet())
    pkt[COMMAND_CKSUM_HI] ^= 0xFF
    assert parse_command_like_firmware(bytes(pkt)) is None


def test_legacy_54_byte_packet_does_not_satisfy_the_v4_parse():
    """A v1/54-byte packet must fail, not silently mis-decode."""
    legacy_fmt = "<BIH" + "f" * 10 + "HHBBB"
    assert struct.calcsize(legacy_fmt) == 54
    legacy = struct.pack(legacy_fmt, SYNC_BYTE_TX, 1, 2,
                         *([0.0] * 10), 0, 0, 0, 0, 0)
    fmt = _extract_t2p_fmt(_bridge_src())
    with pytest.raises(struct.error):
        struct.unpack(fmt, legacy)
    # The bridge's length guard drops it before unpacking.
    assert len(legacy) < TELEMETRY_SIZE


# ── (e) Stale-node tripwire ───────────────────────────────────────────────────

def test_sdp_ems_node_still_reads_the_superseded_15_element_layout():
    """TRIPWIRE — this test PASSES while the defect is present.

    ``sdp_ems_node_2026-03-16A.py`` was never updated for protocol v4. Under the
    18-element /vehicle_state the v4 bridge publishes, its index 13 reads
    ``switch_state`` (an RT1987 bitmask) as ``fault_flags``, and its index 14
    reads ``fault_flags`` as SOC. Both are wrong, and both fail unsafely: a
    nonzero switch bitmask forces the node to SAFE on every tick, and a
    fault-flag word read as SOC is far above any plausible state of charge.

    When the student ships a corrected node, this test must be FLIPPED to assert
    the v4 indices (13 -> switch_state ignored, 14 -> fault_flags, 17 -> SOC) and
    the length guard ``len(msg.data) < 18``. Do not delete it.
    """
    src = _require(SDP_NODE_PY)

    guard = re.search(r'if\s+len\(msg\.data\)\s*<\s*(\d+)\s*:\s*return', src)
    assert guard, "length guard not found in sdp_ems_node"
    assert int(guard.group(1)) == VEHICLE_STATE_LEN_V1, (
        "sdp_ems_node length guard changed — the node may have been fixed; "
        "flip this tripwire to the v4 assertions."
    )

    soc = re.search(r'self\.SOC\s*=\s*msg\.data\[(\d+)\]', src)
    flt = re.search(r'self\.fault_flags\s*=\s*int\(msg\.data\[(\d+)\]\)', src)
    assert soc and flt
    soc_idx, flt_idx = int(soc.group(1)), int(flt.group(1))

    # The defect: the stale indices are the v1 ones, not the v4 ones.
    assert soc_idx == VS_V1_IDX_SOC and soc_idx != VS_IDX_SOC
    assert flt_idx == VS_V1_IDX_FAULT_FLAGS and flt_idx != VS_IDX_FAULT_FLAGS
    # Under the v4 layout those indices name different signals entirely.
    assert flt_idx == VS_IDX_SWITCH_STATE
    assert soc_idx == VS_IDX_FAULT_FLAGS


def test_simple_ems_node_08_17A_reads_the_v4_layout():
    """The counterpart node IS current — the contrast the memo relies on."""
    src = _require(PI_ROOT / "ROS2" / "simple_ems_node_2026-08-17A.py")
    guard = re.search(r'if\s+len\(msg\.data\)\s*<\s*(\d+)\s*:', src)
    assert guard and int(guard.group(1)) == VEHICLE_STATE_LEN_V4
    assert re.search(r'self\.SOC\s*=\s*msg\.data\[17\]', src)
    assert re.search(r'self\.fault_flags\s*=\s*int\(msg\.data\[14\]\)', src)


def test_sdp_standalone_scripts_still_assert_the_54_byte_protocol():
    """TRIPWIRE — passes while the standalone SDP scripts remain on v1."""
    for name in ("sdp_ems_standalone.py", "sdp_ems_standalone_2026-03-16A.py"):
        src = _require(PI_ROOT / "SDP" / name)
        m = re.search(r'assert\s+T2P_SIZE\s*==\s*(\d+)', src)
        assert m, f"{name}: T2P_SIZE assertion not found"
        assert int(m.group(1)) == 54, (
            f"{name}: T2P_SIZE assertion changed — the script may have been "
            "updated to v4; flip this tripwire."
        )


def test_bridge_publishes_soc_from_a_v_batt_lookup_table():
    """SOC is a Pi-side estimate; no SOC field exists in the packet."""
    src = _bridge_src()
    assert re.search(r'def\s+soc_from_vbatt\(', src)
    assert re.search(r'soc\s*=\s*soc_from_vbatt\(Vb\)', src)
    assert "SOC" not in [n for _, _, n in TELEMETRY_FIELDS]
