"""Vectorised .BLG reader: a whole bench log as numpy arrays.

tools/decode_benchlog.py is the authoritative decoder, but it walks the file
record by record into CSV text, which is slow over the ~1 GB logs/ folder.
This module reads the same layout straight into arrays. It imports the record
constants (header format, MAX_GAP_US, close reasons) from decode_benchlog so
the two cannot drift, and applies the same end-of-data rules:

  * stop BEFORE the first record whose wrap-safe step from its predecessor is
    zero or larger than MAX_GAP_US (stale card content after a brownout);
  * stop BEFORE a trailer record (t_us == 0xFFFFFFFF with a known close
    reason at trailer offset 12).

test_rail_spectral.py checks the arrays against decode_blg() on synthetic
v1, v3 and v6 files.

Only the fields the spectral study needs are returned: the float channel
block, fault_flags, flags, and (BLG v6+) encoder_pos.
"""
import struct
import sys
from pathlib import Path

import numpy as np

TOOLS_DIR = Path(__file__).resolve().parents[1]


def _decoder():
    if str(TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLS_DIR))
    import decode_benchlog
    return decode_benchlog


FLOAT_NAMES_V1 = ["share_sp", "share_act", "v_sp", "v_act", "I_fc", "I_batt",
                  "gFC", "gBT", "V_bus", "I_cmd"]
FLOAT_NAMES_V3 = FLOAT_NAMES_V1 + ["V_fc", "V_batt", "V_chg", "V_rgn"]

# Record offsets common to every version (decode_benchlog RECORD_FMT*):
#   u32 t_us @0, nf x f32 @4, u16 fault_flags, u8 ps/dc/trap phase, u8 flags.
# BLG v5 appends f32 u_unsat @68, f32 drive_x0 @72; v6 appends i32
# encoder_pos @76.
ENCODER_POS_OFFSET = 76
TRAILER_CLOSE_REASON_OFFSET = 12   # TRAILER_FMT "<IIIBBI": u32 x3, then u8 close_reason
SENTINEL = 0xFFFFFFFF


def load_blg(path):
    """Return {version, fw, profile_type, hil, sig} for one .BLG file.

    sig holds float64 arrays keyed by channel name, plus 't' (seconds from
    the first record, wrap-safe), 'flags' (u8), 'fault' (u16) and 'enc'
    (i64 encoder_pos, or None before BLG v6). Raises ValueError on a bad
    header, like decode_blg().
    """
    D = _decoder()
    data = Path(path).read_bytes()
    if len(data) < D.HEADER_SIZE:
        raise ValueError("file shorter than the 32-byte header")
    magic, ver, rs, ptype, _h7, _sm, _su, _kd = struct.unpack_from(D.HEADER_FMT, data, 0)
    if magic != D.MAGIC:
        raise ValueError(f"bad magic {magic!r}")
    if ver not in D.SUPPORTED_VERSIONS:
        raise ValueError(f"unsupported version {ver}")
    if rs != D.RECORD_INFO[ver]["size"]:
        raise ValueError(f"unexpected record_size {rs} for version {ver}")
    fw = struct.unpack_from("<H", data, 18)[0] if ver >= 2 else None

    n = (len(data) - D.HEADER_SIZE) // rs
    raw = np.frombuffer(data, dtype=np.uint8, count=n * rs,
                        offset=D.HEADER_SIZE).reshape(n, rs)
    names = FLOAT_NAMES_V3 if ver >= 3 else FLOAT_NAMES_V1
    nf = len(names)
    t = raw[:, 0:4].copy().view("<u4").ravel().astype(np.int64)

    # End of data: first trailer, or the record before the first bad step.
    end = n
    is_trailer = (t == SENTINEL) & np.isin(
        raw[:, TRAILER_CLOSE_REASON_OFFSET], list(D.CLOSE_REASONS))
    tr = np.flatnonzero(is_trailer)
    if len(tr):
        end = tr[0]
    step = np.diff(t[:end]) & 0xFFFFFFFF
    bad = np.flatnonzero((step == 0) | (step > D.MAX_GAP_US))
    if len(bad):
        end = bad[0] + 1
    raw = raw[:end]
    t = t[:end]

    f = raw[:, 4:4 + 4 * nf].copy().view("<f4").reshape(end, nf).astype(np.float64)
    fault_off = 4 + 4 * nf
    fault = raw[:, fault_off:fault_off + 2].copy().view("<u2").ravel()
    flags = raw[:, fault_off + 5].copy()
    enc = None
    if ver >= 6:
        enc = raw[:, ENCODER_POS_OFFSET:ENCODER_POS_OFFSET + 4].copy() \
            .view("<i4").ravel().astype(np.int64)

    t_s = np.concatenate([[0], np.cumsum(np.diff(t) & 0xFFFFFFFF)]) * 1e-6 \
        if end else np.zeros(0)
    sig = {k: f[:, i] for i, k in enumerate(names)}
    sig.update(t=t_s, t_us=t, flags=flags, fault=fault, enc=enc)
    return dict(version=ver, fw=fw, profile_type=ptype,
                hil=bool((flags & 0x40).any()), sig=sig)
