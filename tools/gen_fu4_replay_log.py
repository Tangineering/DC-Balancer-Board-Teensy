#!/usr/bin/env python3
"""Generate logs/SY0001.BLG — a SYNTHETIC bench log for HIL replay entry FU4.

⚠️ THIS FILE'S OUTPUT IS NOT A RECORDING. ⚠️
=============================================
`logs/SY0001.BLG` is authored by this generator, byte for byte. Nothing in it
was measured on the board, on the bench, or anywhere else. It is committed to
the repo alongside genuine bench recordings, so the `SY` prefix exists for
exactly one reason: every other prefix in `logs/` (`ML`, `TP`, `WP`, `YP`,
`PS`) marks a real run written by the firmware's own SD logger, and a reader
scanning the directory must be able to tell this one apart without opening it.
`SY` = SYNTHETIC. Do not analyse it as bench data, do not fit any constant to
it, and do not cite any number in it as a measurement.

WHY IT EXISTS
-------------
The HIL replay suite (`tools/hil_replay_suite.py`) replays recorded logs at the
board as injection frames plus, for opted-in entries, the log's own recorded
`v_sp`/`share_sp` as 22-byte Pi command packets (`--replay-commands`). Follow-up
item FU4 wanted one entry exercising the **Idle -> Run setpoint-arrival
transient**: the firmware's `doState1()` zeroes `v_setpoint` on the Run
transition (`teensy_controller/teensy_controller.ino:5382-5410` — the reset is
unconditional and ignores the triggering packet's payload), so a large setpoint
can only arrive on the SECOND post-reset command packet, <= 20 ms later, into a
freshly reset drive controller. That is a real, reachable operating condition
with a full-scale error landing on a zero-state loop.

No recorded log covers it. Every bench recording in `logs/` begins with the
vehicle at standstill and the setpoint already at or near zero, so replaying any
of them delivers a small or zero setpoint across the Run transition. The
stimulus had to be authored rather than found, and authoring it honestly means
saying so loudly rather than quietly minting a plausible-looking `ML` file.

THE STIMULUS (log-relative time; log t = sim t - REPLAY_PREAMBLE_S = 2.5 s)
--------------------------------------------------------------------------
  v_sp  = 2.0 m/s on [0.000, 1.500) s   the arrival leg
  v_sp  = 0.0 m/s on [1.500, 2.500) s   the release leg
  v_act = 0.0 m/s throughout

`v_sp` is held at 2.0 from record 0. Because `doState1()` zeroes `v_setpoint`
regardless of payload, the board sees 0.0 on the packet that moves it to Run and
2.0 on the next one — the two-packet mechanic above, delivered structurally by a
constant log rather than by timing a step against an unobservable transition
instant. 2.0 m/s is ~77x the ~26 mm/s error at which the drive controller's
454.4 A/(m/s) low-frequency gain rails the command, and sits inside the range
the rest of the suite replays (0.5-3.0 m/s), so it is a large-signal step
without being an absurd one.

`v_act` is pinned at 0.0 DELIBERATELY. Replay is open loop — the injected
velocity never responds to what the firmware commands — so any nonzero
trajectory here would be an invented plant response with no referent. Zero is
also the honest at-rest precondition for a Run entry. The velocity-valid flag
(record `flags` bit1) is set so the decoder emits 0.0 as a real value rather
than blanking the column.

The release leg exists so the entry can assert that the command comes back OFF
the rail: with `v_act` pinned at 0, dropping `v_sp` to 0.0 collapses the error
through `V_SP_ZERO_THRESH` (0.07 m/s, `teensy_controller.ino:8975`), which is a
deterministic zero-cutoff rather than a settling transient. The release is
therefore bounded by firmware structure, not by plant dynamics that replay does
not have.

Every other channel is a constant healthy nominal, chosen to match the suite's
own absent-rail substitution table (`docs/HIL_REPLAY_LOGS.md` §3b) so nothing
extraneous faults during the run:

  V_fc 12.9 V   V_batt 7.9 V   V_bus 15.95 V   V_chg 0.0 V   V_rgn 15.95 V
  I_fc 0.05 A   I_batt 0.05 A   share_sp 0.5   share_act 0.5   fault_flags 0

`I_cmd` is 0.0 on every record, and that is a statement, not a placeholder:
this log carries NO recorded controller response. A board holding `v_act` at
exactly 0.0 while commanding 12 A is physically impossible, so there is no
self-consistent response to write down. The response under test is the LIVE
board's. Any tooling that overlays a recorded `I_cmd` against the observed one
(`tools/hil_report_analysis.py`'s response-deviation figure) is meaningless for
this entry by construction.

`gFC`/`gBT` are both 0.298 — the design droop-chain gain at a 0.5 share split
(`tools/hil_plant_sim.py:198`) — which is the value consistent with the
`share_sp` 0.5 and with `flags` bit0 (droop being driven).

FORMAT
------
BLG record format **v3** (header byte 4 = 3, 68-byte records), deliberately not
v5/v6/v7. v3 is the earliest format carrying the four source/node voltage
channels the replay path needs directly, and it stops there: v5's drive
controller fields (`u_unsat`, `drive_x0`) and v6/v7's encoder diagnostics
(`encoder_pos`, period reference, edge/phase/duty counters) have no synthetic
referent whatsoever, and inventing them would read as fabricated hardware
telemetry. Choosing v3 makes their absence structural rather than a decision a
reader has to trust.

Header `fw_version` = 23. `FW_DELTA_NOTES[23]` in the replay suite marks fw v23
as THE FLASHED TARGET, so the entry carries no wheel-geometry or control-law
comparability caveat — which is correct here, because the log contains no
measured quantity for such a caveat to apply to.

All layout constants below are taken from `tools/decode_benchlog.py`, which is
the format authority (`HEADER_FMT`/`HEADER_SIZE` :250-251, `RECORD_FMT_V3`
:257-258, `TRAILER_FMT`/`CLOSE_REASONS` :285-287, the v3 field order at
:519-521, the `flags` bit1 velocity-valid rule at :529).

DETERMINISM
-----------
The output is byte-identical on every run. Record timestamps are derived from
the 1 kHz sample index (`t_us = i * 1000`), and the header's `start_millis` /
`start_micros` are fixed at 0 rather than sampled from the clock, so
regenerating the file produces the same sha256. That is a hard requirement: the
file is committed, and a generator that produced a fresh diff on every run would
make every regeneration look like a data change.

REGENERATION
------------
    .venv_hil/Scripts/python.exe tools/gen_fu4_replay_log.py --force

Then re-verify the suite's header cross-check:

    .venv_hil/Scripts/python.exe tools/hil_replay_suite.py --verify-logs

Without `--force` the generator refuses to overwrite an existing file (house
convention, matching `hil_plant_sim.py`'s `--csv` guard).

Stdlib only (argparse, hashlib, os, struct, sys).
"""

import argparse
import hashlib
import os
import struct
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(REPO_ROOT, "logs", "SY0001.BLG")

# ── Format constants — decode_benchlog.py is the authority ──────────────────
MAGIC = b"BLG1"                     # decode_benchlog.py:248
HEADER_FMT = "<4sBBBBIIH"           # :250  — 18 bytes; fw_version follows at 18
HEADER_SIZE = 32                    # :251
RECORD_FMT_V3 = "<I14fHBBBB2x"      # :257
RECORD_SIZE_V3 = 68                 # :258
TRAILER_FMT = "<IIIBBI"             # :285  — 18 bytes, zero-padded to a record
CLOSE_REASON_COMPLETE = 1           # :286 CLOSE_REASONS

BLG_VERSION = 3
FW_VERSION = 23                     # hil_replay_suite.FW_DELTA_NOTES[23]
PROFILE_TYPE = 0                    # manual/none — no profile authored this
K_DROOP_X1000 = 300                 # 0.300 ohm, the design droop value (cosmetic)

# ── Stimulus ────────────────────────────────────────────────────────────────
SAMPLE_PERIOD_US = 1000             # the firmware's own 1 kHz logSampleTick rate
N_RECORDS = 2500                    # 2.500 s
ARRIVAL_END_IDX = 1500              # v_sp steps to 0 at log t = 1.500 s
V_SP_ARRIVAL = 2.0                  # m/s — the setpoint that arrives post-reset
V_SP_RELEASE = 0.0                  # m/s — the release leg
V_ACT = 0.0                         # m/s — pinned; see the module docstring

# ── Constant healthy rails (docs/HIL_REPLAY_LOGS.md §3b nominals) ───────────
V_FC = 12.9
V_BATT = 7.9
V_BUS = 15.95
V_CHG = 0.0                         # charger unpowered — the honest value
V_RGN = 15.95                       # RGN-V sits on V-MOT (fw v22 topology)
I_FC = 0.05
I_BATT = 0.05
I_CMD = 0.0                         # NO recorded response — see the docstring
SHARE_SP = 0.5
SHARE_ACT = 0.5
G_FC = 0.298                        # design droop gain at a 0.5 split
G_BT = 0.298
FAULT_FLAGS = 0

# ps/dc/trap phase: 0xFF is the decoder's "no phase" sentinel (blanked in CSV,
# decode_benchlog.py:531-533). No profile authored this log, so all three are
# unset.
PHASE_NONE = 0xFF

# flags bit0 = a profile / live share loop is driving the droop;
# flags bit1 = velocity chain valid (decode_benchlog.py module docstring :36,
# :46; the bit1 rule is applied at :529). bit1 is REQUIRED here — without it the
# decoder blanks v_sp/v_act and the replay path would inject nothing.
FLAGS = 0x03


def build_blg():
    """Return the complete .BLG file as bytes. Pure and deterministic."""
    out = bytearray()

    # Header: HEADER_FMT covers bytes 0-17; fw_version is a separate u16 at
    # offset 18 (decode_benchlog.py:425 reads it there), then zero pad to 32.
    out += struct.pack(HEADER_FMT, MAGIC, BLG_VERSION, RECORD_SIZE_V3,
                       PROFILE_TYPE, 0, 0, 0, K_DROOP_X1000)
    out += struct.pack("<H", FW_VERSION)
    out += b"\x00" * (HEADER_SIZE - len(out))
    assert len(out) == HEADER_SIZE

    for i in range(N_RECORDS):
        v_sp = V_SP_ARRIVAL if i < ARRIVAL_END_IDX else V_SP_RELEASE
        out += struct.pack(
            RECORD_FMT_V3,
            i * SAMPLE_PERIOD_US,
            SHARE_SP, SHARE_ACT, v_sp, V_ACT, I_FC, I_BATT, G_FC, G_BT,
            V_BUS, I_CMD, V_FC, V_BATT, V_CHG, V_RGN,
            FAULT_FLAGS, PHASE_NONE, PHASE_NONE, PHASE_NONE, FLAGS)

    # Trailer: a record-sized chunk whose first u32 is the 0xFFFFFFFF sentinel.
    # records_written must equal the record count or the decoder warns
    # (decode_benchlog.py:621). dropped/error_code/abandoned are 0 — nothing was
    # dropped, because nothing was sampled.
    trailer = struct.pack(TRAILER_FMT, 0xFFFFFFFF, N_RECORDS, 0,
                          CLOSE_REASON_COMPLETE, 0, 0)
    out += trailer + b"\x00" * (RECORD_SIZE_V3 - len(trailer))

    return bytes(out)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Generate the SYNTHETIC HIL replay log logs/SY0001.BLG "
                    "(FU4: Idle->Run setpoint-arrival transient). The output is "
                    "authored, not recorded — see the module docstring.")
    ap.add_argument("-o", "--out", default=DEFAULT_OUT,
                    help="output path (default: logs/SY0001.BLG)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing output file")
    ap.add_argument("--stdout-hash", action="store_true",
                    help="print the sha256 and size without writing anything")
    args = ap.parse_args(argv)

    data = build_blg()
    digest = hashlib.sha256(data).hexdigest()

    if args.stdout_hash:
        print(f"{len(data)} bytes  sha256 {digest}")
        return 0

    if os.path.exists(args.out) and not args.force:
        # ASCII-only in every print below: this runs from subprocesses and CI
        # shells whose stdout encoding is not always UTF-8, and a non-ASCII dash
        # in a status line is not worth a UnicodeEncodeError.
        print(f"error: {args.out} exists - pass --force to overwrite",
              file=sys.stderr)
        return 2

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as fh:
        fh.write(data)
    print(f"[gen_fu4] wrote {args.out}: {len(data)} bytes, "
          f"{N_RECORDS} records + trailer, BLG v{BLG_VERSION}, "
          f"fw_version {FW_VERSION}")
    print(f"[gen_fu4] sha256 {digest}")
    print("[gen_fu4] SYNTHETIC - authored by this generator, not recorded on "
          "hardware. Do not analyse as bench data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
