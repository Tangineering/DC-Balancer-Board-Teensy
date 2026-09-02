# Raspberry Pi Bridge Audit against Telemetry Protocol v4

Date: 2026-09-01. Auditor: Ricky Tan. Firmware reference: fw v25 (committed, not flashed at
the time of audit); telemetry protocol v4; command packet unchanged since v1.

## 1. Purpose and scope

This document records a field-by-field comparison of the Raspberry Pi bridge software against
the firmware's UDP wire protocol. The audit gates the first `--pi-live` (Mode B) hardware-in-
the-loop campaign, in which the Pi supplies commands in place of the simulator's internal
commander. Mode B is unsafe to attempt while any Pi-side parser disagrees with the firmware
layout, because both packet formats are positional and a disagreement decodes silently.

The audit covers wire-format conformance only: packet size, field offsets, field types,
byte order, synchronisation bytes, checksum spans, and the semantic index layout of the ROS 2
topic the bridge publishes. Section 8 lists what the audit does not cover.

## 2. Sources compared

The firmware side is authoritative. The following anchors were read directly and every claim
below is traceable to one of them.

| Source | Anchor |
|--------|--------|
| `teensy_controller/teensy_controller.ino` | `sendTelemetry()` lines 5585–5667; block comment 5585–5612; checksum loop 5658–5659 |
| `teensy_controller/teensy_controller.ino` | `processPiCommandPacket()` lines 5433–5491; checksum 5439–5441; field order 5450–5479 |
| `teensy_controller/teensy_controller.ino` | `TELEMETRY_VERSION 4` line 1825; `SYNC_BYTE_TX 0xAA` line 2899; `SYNC_BYTE_RX 0xBB` line 2900 |
| `teensy_controller/teensy_controller.ino` | Fault bitmask lines 1323–1352; `ErrorCode_t` lines 1645–1666; switch bitmask lines 1828–1833 |
| `PLAN.md` | §6b lines 525–579 (v4 layout); §6c lines 605–611 (command packet, reserved byte) |
| `references/EMS/Pi_2026-09-01/` | Reference copy of the Pi software, committed under 567a3ed |

The Pi drop is a reference copy, not the live installation. Fixes are not pushed from this
repository. The change request in `docs/pi_bridge_change_request_20260901.md` is the delivery
mechanism.

Note on paths: an earlier investigation cited directories `ROS/` and `TPM/` under the Pi drop.
Those directories are empty. The Python sources are under `EMS/ROS2/`, `EMS/SDP/`, and
`EMS/Simple/`.

## 3. Telemetry packet — 58 bytes, Teensy to Pi

The bridge declares `T2P_FMT = "<BIH" + "f" * 10 + "HHBBHBBB"`, `T2P_SIZE == 58`
(`teensy_bridge_node_2026-08-17A.py:89–92`). The `<` prefix disables struct padding, so the
declared field widths determine the offsets exactly. The table below compares the resulting
offsets against the firmware.

| Offset | Bytes | Type | Firmware name | Bridge name | Scale / units | Verdict |
|-------:|------:|------|---------------|-------------|---------------|---------|
| 0  | 1 | uint8   | `SYNC_BYTE_TX` = 0xAA | `TEENSY_HEADER` = 0xAA | — | Match |
| 1  | 4 | uint32  | `millis()` timestamp | `ts` | ms | Match |
| 5  | 2 | uint16  | `pkt_counter_T` | `ctr` | count, wraps at 2^16 | Match |
| 7  | 4 | float32 | `v_actual` | `v` | m/s | Match |
| 11 | 4 | float32 | `V_batt` | `Vb` | V | Match |
| 15 | 4 | float32 | `I_batt` | `Ib` | A, unipolar | Match |
| 19 | 4 | float32 | `I_charge` | `Ic` | A (Ag105 reg 0x06 × 0.011) | Match |
| 23 | 4 | float32 | `V_fc` | `Vfc` | V | Match |
| 27 | 4 | float32 | `I_fc` | `Ifc` | A, unipolar | Match |
| 31 | 4 | float32 | `V_bus` | `Vbus` | V | Match |
| 35 | 4 | float32 | `V_rgn` | `Vrgn` | V | Match |
| 39 | 4 | float32 | `V_chg` | `Vchg` | V | Match |
| 43 | 4 | float32 | `power_share_actual` | `sha` | fraction | Match |
| 47 | 2 | uint16  | `fc_u16` | `dFC` | raw Q16 count | Match |
| 49 | 2 | uint16  | `bt_u16` | `dBT` | raw Q16 count | Match |
| 51 | 1 | uint8   | `ag105_status_raw` | `chg_status` | Ag105 Table 6 bitfield | Match |
| 52 | 1 | uint8   | `readSwitchState()` | `sw_state` | switch bitmask | Match |
| 53 | 2 | uint16 LE | `fault_flags` | `flt` | fault bitmask | Match |
| 55 | 1 | uint8   | `error_code` | `err_code` | `ErrorCode_t` | Match |
| 56 | 1 | uint8   | `error_source_state` | `err_src` | `mainState` | Match |
| 57 | 1 | uint8   | checksum | `_cs` | XOR of bytes 1–56 | Match |

Synchronisation: the firmware writes 0xAA at byte 0. The bridge scans the datagram for the
first 0xAA at which a complete 58-byte chunk fits (`:238–241`).

Checksum: the firmware computes `XOR` over indices 1 to 56 inclusive (`.ino:5658–5659`). The
bridge verifies `_xor(chunk[1:-1]) != chunk[-1]` (`:243`), which is the identical span.

Version: `TELEMETRY_VERSION` is a compile-time constant and is not transmitted. The bridge
therefore cannot detect a version mismatch from the wire. Its size assertion at import time is
the only guard. This is a known design limitation of v4, not a bridge defect.

## 4. Command packet — 22 bytes, Pi to Teensy

| Offset | Bytes | Type | Firmware name | Bridge value | Verdict |
|-------:|------:|------|---------------|--------------|---------|
| 0  | 1 | uint8   | `SYNC_BYTE_RX` = 0xBB | `PI_HEADER` = 0xBB | Match |
| 1  | 4 | uint32  | `timestamp` | `ts` | Match |
| 5  | 2 | uint16  | `pkt_counter_Pi` | `self._tx_counter` | Match |
| 7  | 4 | float32 | `v_sp_rx` | `v_sp` | Match |
| 11 | 4 | float32 | `share_sp_rx` | `pshare` | Match |
| 15 | 4 | float32 | `charge_rx` | `chg` | Match |
| 19 | 1 | uint8   | `mode_cmd` | `mode` | Match |
| 20 | 1 | uint8   | `droop_enable_reserved` | `droop_en` | Match, reserved |
| 21 | 1 | uint8   | checksum | `_xor(payload[1:])` | Match |

The bridge declares `P2T_FMT = "<BIHfffBBB"` (22 bytes) for the size assertion only. The
payload it actually packs is `"<BIHfffBB"` (21 bytes), to which it appends the XOR byte
(`:336–342`). The result is byte-identical to the declared format. The two-format construction
is correct but is a latent maintenance hazard, because editing one format does not force an
edit of the other.

Firmware input handling: each of the three floats is admitted only when `isfinite()`
(`.ino:5473–5475`); a rejected field holds its previous value. `v_setpoint` is constrained to
`±V_SETPOINT_MAX` and `power_share_setpoint` to `[0, 1]`. The Pi may send any float; the
firmware will not accept a non-finite one.

## 5. Field semantics and scale conventions

The droop gains are published as **raw Q16 counts**, not as fractions. The firmware encodes
`u16 = constrain(gain, 0.0, 1.0) × 65535` (`.ino:5642–5643`), and the bridge stores `float(dFC)`
and `float(dBT)` unscaled into `/vehicle_state[10]` and `[11]`. A consumer that wants a
fraction must divide by 65535. No consumer in the reference drop does so; none currently reads
those elements.

`fault_flags` and `switch_state` are published as **undecoded numeric words**. The bridge holds
the fault bit constants (`:112–127`) and they agree with the firmware definitions at
`.ino:1323–1343` bit for bit, including `FAULT_ERROR = 0x8000`. The bridge does not decode
`switch_state`; the firmware bit assignment is `SW_FC_BUS 0x01`, `SW_BT_BUS 0x02`,
`SW_MOT_PWR 0x04`, `SW_REGEN 0x08`, `SW_FC_CHARGE 0x10`, `SW_BT_SEQ 0x20` (`.ino:1828–1833`).

`FAULT_COMMS_STALE` is defined as `0x8000` (`:130`), the same bit as `FAULT_ERROR`. When Teensy
telemetry goes stale the bridge overwrites `/vehicle_state[14]` with that value (`:361`), which
destroys the last received fault word rather than adding to it. A consumer cannot distinguish a
Pi-side stale link from a firmware State-99 latch. This is a defect of low severity for Mode B,
because the HIL suite attributes link faults from the observation frame, but it is reported to
the author.

`error_code` values are an append-only enum (`.ino:1645–1666`, values 0x00–0x10). The bridge
passes the raw value through without decoding.

## 6. SoC source

The telemetry packet carries **no state-of-charge field**. The bridge synthesises SoC on the Pi
from a nine-breakpoint lookup table over `V_batt` (`soc_from_vbatt`, `:140–150`, range 0.05 to
1.00) and publishes it as `/vehicle_state[17]`. Any EMS strategy that consumes Pi-side SoC is
therefore consuming a terminal-voltage estimate with no current or temperature correction and
no interpolation between breakpoints. The HIL simulator's SoC-based strategies use plant truth
and are flagged simulation-only; the two quantities are not interchangeable, and a Mode B
comparison against a simulation-only strategy is not valid.

## 7. Per-file verdicts

| File | Verdict | Defect |
|------|---------|--------|
| `EMS/ROS2/teensy_bridge_node_2026-08-17A.py` | Current | None. Conformant with protocol v4 in both directions. |
| `EMS/ROS2/simple_ems_node_2026-08-17A.py` | Current | None. Reads the 18-element layout: SoC at index 17, fault flags at index 14, length guard 18. |
| `EMS/ROS2/drive_cycle_node_2026-03-16A.py` | Current | None. Publishes `/drive_cycle` only; does not read `/vehicle_state`. |
| `EMS/ROS2/sdp_ems_node_2026-03-16A.py` | **Broken** | Length guard 15 and indices 13/14 (`:100–103`). Under the 18-element layout, index 13 is `switch_state` read as `fault_flags`, and index 14 is `fault_flags` read as SoC. Both misreads fail unsafely. |
| `EMS/ROS2/simple_ems_node_2026-04-06A.py` | Stale | Superseded by the 08-17A revision. Same 15-element indices (`:109–113`). Harmless if not launched. |
| `EMS/ROS2/teensy_bridge_node_2026-03-16A.py` | Stale | Superseded. Asserts `T2P_SIZE == 54` and publishes 15 elements. Harmless if not launched. |
| `EMS/ROS2/fchev_launch_2026-03-16A.py` | Broken | Launches `sdp_ems_node` (`:132–134`) alongside the bridge, so a default launch activates the broken node. |
| `EMS/SDP/sdp_ems_standalone.py` | Broken | `T2P_FMT = "<BIH" + "f"*10 + "HHBBB"`, `assert T2P_SIZE == 54` (`:101–103`). Every v4 packet is discarded by the length guard; the script receives nothing. |
| `EMS/SDP/sdp_ems_standalone_2026-03-16A.py` | Broken | Identical 54-byte assertion (`:87–89`). |
| `EMS/Simple/simple_ems_test_2026-03-16A.py` | Broken | Same 54-byte format (`:69–70`). Bench test script only. |
| `EMS/SDP/CostToGo_J_scaled.mat` | Not audited | Binary cost-to-go table; see §8. |

The three 54-byte scripts fail closed rather than open: their length guard rejects a 58-byte
datagram, so they receive no telemetry at all. The ROS 2 SDP node fails open, which is the more
dangerous mode, because it decodes and acts on wrong values.

## 8. What this audit did not verify

The following are outside the scope of the wire-format audit and remain unverified.

- ROS 2 topic semantics beyond element indexing: quality-of-service settings, publication
  rates, message-drop behaviour, and node lifecycle.
- End-to-end timing: the Pi command period against the firmware's 500 ms watchdog, the bridge's
  50 Hz publication rate under load, and jitter introduced by the receive thread.
- The Pi-side stochastic-dynamic-programming cost-to-go table `CostToGo_J_scaled.mat`, its
  scaling convention, and its agreement with the repository's own SDP artefacts.
- Behaviour of the bridge's watchdog transmission of a SAFE command, which was read but not
  exercised.
- The live Pi installation. Only the reference copy under `references/EMS/Pi_2026-09-01/` was
  read, and the audit cannot confirm which revisions are deployed.

## 9. Regression tests

`tools/test_pi_bridge_v4.py` encodes this audit as 24 stdlib-only tests. The tests extract the
bridge's literal format strings, header constants, and checksum expressions from the source
text by regular expression, then exercise them against packets built exactly as the firmware
builds them. Both stale-node findings are encoded as tripwires that pass while the defect is
present and fail when the Pi source changes, so a shipped fix forces a deliberate test update
rather than passing unnoticed. Run:

```
.venv_hil\Scripts\python.exe -m pytest tools/test_pi_bridge_v4.py -q
```

Result at the time of audit: 24 passed.

## 10. Mode B gate verdict

The bridge parser is v4-conformant in both directions: all 21 telemetry fields, both
synchronisation bytes, both checksum spans, and all nine command fields agree with the firmware
byte for byte. **Mode B is gated on the Pi running the `teensy_bridge_node_2026-08-17A` bridge
and an energy-management node that reads the 18-element `/vehicle_state` layout.** The
`simple_ems_node_2026-08-17A` node satisfies that condition today; `sdp_ems_node_2026-03-16A`
does not and must not be launched until it is corrected. The default launch file activates the
broken node and must be edited or bypassed before a Mode B campaign.
