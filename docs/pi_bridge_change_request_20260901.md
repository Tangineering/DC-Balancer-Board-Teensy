# Change Request: Raspberry Pi Software Alignment with Telemetry Protocol v4

**To:** Author of the Raspberry Pi energy-management software, scaled FCHEV platform
**From:** Ricky Tan, rstan@ucdavis.edu
**Date:** 2026-09-01
**Subject:** Three Pi-side modules decode a superseded packet layout

---

## 1. Summary

The Teensy 4.1 balancer-board firmware transmits telemetry in protocol version 4: a 58-byte
UDP datagram. The command packet from the Raspberry Pi is 22 bytes and is unchanged from
earlier revisions.

The `teensy_bridge_node_2026-08-17A.py` bridge is correct. It parses all 21 telemetry fields at
the correct offsets, verifies the correct checksum span, and transmits a conformant command
packet. No change is required to that file.

Three other modules still assume the superseded 54-byte layout, or its 15-element ROS 2 topic.
One of them fails unsafely, and the default launch file activates it. This request lists the
required changes in order of severity. Section 5 gives the authoritative packet layouts so that
each change can be verified without access to the firmware repository.

---

## 2. What is correct

| Module | Status |
|--------|--------|
| `EMS/ROS2/teensy_bridge_node_2026-08-17A.py` | Conformant. No change required. |
| `EMS/ROS2/simple_ems_node_2026-08-17A.py` | Conformant. Reads the 18-element topic layout. |
| `EMS/ROS2/drive_cycle_node_2026-03-16A.py` | Conformant. Does not consume vehicle state. |

The bridge's fault-bit constants agree with the firmware definitions bit for bit, including the
`0x8000` latch marker. Its checksum verification span, both synchronisation bytes, and the
command field order are all correct.

---

## 3. Required changes

### 3.1 Severity 1 — `EMS/ROS2/sdp_ems_node_2026-03-16A.py` decodes the wrong signals

**Location:** lines 100 to 103, in `_cb_state`.

**Current code:**

```python
# data=[v_actual,V_batt,I_batt,I_charge,V_fc,I_fc,V_bus,P_motor,share_echo,share_actual,droop_FC,droop_BT,charger,faults,SOC]
if len(msg.data) < 15: return
self.v_actual=msg.data[0]; self.SOC=msg.data[14]
self.fault_flags=int(msg.data[13]); self.state_stamp=time.monotonic()
```

**Required code:**

```python
# 18-element layout, protocol v4 — see the bridge node docstring for the full table.
if len(msg.data) < 18: return
self.v_actual=msg.data[0]; self.SOC=msg.data[17]
self.fault_flags=int(msg.data[14]); self.state_stamp=time.monotonic()
```

**Why.** The bridge now publishes 18 elements. Index 13 carries `switch_state`, a power-path
bitmask that is nonzero whenever any ideal-diode switch is closed. Index 14 carries
`fault_flags`. The node therefore reads a switch bitmask as a fault word, and a fault word as
state of charge.

Both misreads are defects, and the second one is unsafe. The node commands SAFE mode on every
control tick during normal operation, because a closed switch reads as a fault; that outcome
is fail-safe. **When the switch bitmask is momentarily zero, the node reads a fault-flag word as
a state of charge far above 1.0, and its state-of-charge hysteresis takes the high-charge
branch regardless of the true pack condition.** That branch commands battery operation on a
pack whose state is unknown, and it is the reason for the severity-1 rating.

### 3.2 Severity 1 — `EMS/ROS2/fchev_launch_2026-03-16A.py` launches the broken node

**Location:** lines 132 to 134.

**Required action.** Do not launch `sdp_ems_node` until the change in §3.1 is applied. Either
correct that node first, or remove its launch entry.

**Why.** A default launch starts the bridge and the stochastic-dynamic-programming node
together. The node then publishes wrong commands on `/ems_command`, and the bridge forwards
them to the board.

### 3.3 Severity 2 — the standalone scripts reject every telemetry packet

**Locations:**

| File | Lines |
|------|------:|
| `EMS/SDP/sdp_ems_standalone.py` | 101 to 103 |
| `EMS/SDP/sdp_ems_standalone_2026-03-16A.py` | 87 to 89 |
| `EMS/Simple/simple_ems_test_2026-03-16A.py` | 69 to 70 |

**Current code:**

```python
T2P_FMT  = "<BIH" + "f" * 10 + "HHBBB"
T2P_SIZE = struct.calcsize(T2P_FMT)
assert T2P_SIZE == 54
```

**Required code:**

```python
T2P_FMT  = "<BIH" + "f" * 10 + "HHBBHBBB"
T2P_SIZE = struct.calcsize(T2P_FMT)
assert T2P_SIZE == 58
```

The unpack target must be widened in the same edit. Replace the 18-name tuple

```python
(_, ts, ctr, v, Vb, Ib, Ic, Vfc, Ifc, Vbus, Pm, she, sha, dFC, dBT, chg, flt, _)
```

with the 21-name v4 tuple

```python
(_, ts, ctr, v, Vb, Ib, Ic, Vfc, Ifc, Vbus, Vrgn, Vchg, sha,
 dFC, dBT, chg_status, sw_state, flt, err_code, err_src, _)
```

**Why.** Each script guards on `len(data) < T2P_SIZE` before parsing. A 58-byte datagram passes
that guard, but the 54-byte unpack then raises. If the guard is reached with the old size, the
first 54 bytes decode with `P_motor` and `share_echo` in slots that now carry `V_rgn` and
`V_chg`, and the fault byte reads a droop count. Correct both the format and the tuple in one
edit.

Note two renamed fields. `P_motor_actual` no longer exists; compute it as `V_bus × I_fc` or
`V_bus × I_batt` on the Pi. `power_share_echo` no longer exists; the Pi already knows the
setpoint it sent.

### 3.4 Severity 3 — the stale-link flag destroys the fault word

**Location:** `EMS/ROS2/teensy_bridge_node_2026-08-17A.py`, lines 130 and 361.

**Current code:**

```python
FAULT_COMMS_STALE = 0x8000  # reuse ERROR bit as comms-stale indicator
...
state[14] = float(FAULT_COMMS_STALE)  # inject comms fault
```

**Required code:**

```python
FAULT_COMMS_STALE = 0x8000
...
state[14] = float(int(state[14]) | FAULT_COMMS_STALE)
```

**Why.** The assignment overwrites the last received fault word. A consumer therefore cannot
tell a Pi-side link timeout from a firmware fault latch, and the latched cause is lost. The
bitwise combination preserves both. Apply the bitwise combination shown above; it is the
recommended change. A dedicated bit outside the firmware's `0x0001` to `0x8000` range is an
optional further improvement, and only if a wider field is acceptable to the consumers.

### 3.5 Severity 3 — the command packet is declared in two places

**Location:** `EMS/ROS2/teensy_bridge_node_2026-08-17A.py`, lines 95 and 337.

`P2T_FMT` is `"<BIHfffBBB"`, but `_send_udp_cmd` packs `"<BIHfffBB"` and appends the checksum
byte separately. The two agree today. Derive the payload format from a single constant, so that
a future edit cannot separate them.

---

## 4. Verification procedure

Do the steps in order.

1. Apply the change in §3.1.
2. Start the bridge node and the corrected energy-management node.
3. Confirm that `/vehicle_state` carries 18 elements.
4. Confirm that element 17 stays between 0.05 and 1.00 during a run.
5. Confirm that element 14 is zero while the board is fault-free.
6. Close one power-path switch and confirm that element 14 stays zero.
7. Apply the changes in §3.3 and run each standalone script against a live board.
8. Confirm that each script reports a nonzero received-packet count.

**Warning:** Do not run the stochastic-dynamic-programming node against a powered board before
step 6 passes. The uncorrected node commands SAFE mode continuously and can also take its
high-charge branch on a false state of charge.

---

## 5. Authoritative packet layouts

### 5.1 Telemetry, Teensy to Pi — 58 bytes

Synchronisation byte 0xAA at offset 0. Checksum at offset 57 is the exclusive-or of bytes 1 to
56 inclusive. All multi-byte fields are little-endian and unpadded.

| Offset | Bytes | Type | Field | Units |
|-------:|------:|------|-------|-------|
| 0  | 1 | uint8   | sync 0xAA | — |
| 1  | 4 | uint32  | timestamp | ms |
| 5  | 2 | uint16  | packet counter | count |
| 7  | 4 | float32 | `v_actual` | m/s |
| 11 | 4 | float32 | `V_batt` | V |
| 15 | 4 | float32 | `I_batt` | A |
| 19 | 4 | float32 | `I_charge` | A |
| 23 | 4 | float32 | `V_fc` | V |
| 27 | 4 | float32 | `I_fc` | A |
| 31 | 4 | float32 | `V_bus` | V |
| 35 | 4 | float32 | `V_rgn` | V |
| 39 | 4 | float32 | `V_chg` | V |
| 43 | 4 | float32 | `power_share_actual` | fraction |
| 47 | 2 | uint16  | droop gain, fuel-cell channel | raw count |
| 49 | 2 | uint16  | droop gain, battery channel | raw count |
| 51 | 1 | uint8   | charger status | bitfield |
| 52 | 1 | uint8   | switch state | bitmask |
| 53 | 2 | uint16  | fault flags | bitmask |
| 55 | 1 | uint8   | error code | enumeration |
| 56 | 1 | uint8   | error source state | state number |
| 57 | 1 | uint8   | checksum | — |

Struct format string: `"<BIH" + "f" * 10 + "HHBBHBBB"`.

The two droop gains are **raw counts**, not fractions. Divide by 65535 to obtain the fraction
in the range 0.0 to 1.0.

The telemetry packet contains **no state-of-charge field**. The bridge estimates it from
`V_batt` through the `soc_from_vbatt` lookup table and publishes it as element 17. That
estimate has no current or temperature correction.

### 5.2 Switch-state bitmask, offset 52

| Bit | Value | Switch |
|----:|------:|--------|
| 0 | 0x01 | fuel cell to bus |
| 1 | 0x02 | battery to bus |
| 2 | 0x04 | bus to motor controller |
| 3 | 0x08 | regeneration to charger |
| 4 | 0x10 | bus to charger |
| 5 | 0x20 | battery pack sequencing |

### 5.3 Fault bitmask, offsets 53 and 54

| Value | Fault |
|------:|-------|
| 0x0001 | fuel-cell overcurrent |
| 0x0002 | battery undervoltage |
| 0x0004 | bus overvoltage |
| 0x0008 | illegal switch combination |
| 0x0010 | Pi watchdog timeout |
| 0x0020 | battery overvoltage |
| 0x0040 | fuel-cell undervoltage |
| 0x0080 | battery overcurrent |
| 0x0100 | bus undervoltage |
| 0x0200 | regeneration-node overvoltage |
| 0x0400 | charger-input overvoltage |
| 0x0800 | charger I2C failure |
| 0x1000 | charger status error |
| 0x2000 | initialisation failure |
| 0x4000 | motor hot-plug refused |
| 0x8000 | error latched |

### 5.4 Charger status byte, offset 51

The raw status byte of the Silvertel Ag105 charger module.

| Bits | Meaning |
|------|---------|
| 0 to 2 | general status: 0 battery disconnect, 1 low power, 2 charging, 3 fully charged, 4 bring-up, 5 regulation error, 6 thermal shutdown, 7 timeout error |
| 3 | maximum-power-point tracking enabled |
| 4 | power tracking |
| 5 | constant voltage |
| 6 | constant current |
| 7 | thermal limiting |

### 5.5 Command, Pi to Teensy — 22 bytes

Synchronisation byte 0xBB at offset 0. Checksum at offset 21 is the exclusive-or of bytes 1 to
20 inclusive.

| Offset | Bytes | Type | Field | Accepted range |
|-------:|------:|------|-------|----------------|
| 0  | 1 | uint8   | sync 0xBB | — |
| 1  | 4 | uint32  | timestamp | ms |
| 5  | 2 | uint16  | packet counter | count |
| 7  | 4 | float32 | velocity setpoint | clamped to the firmware limit |
| 11 | 4 | float32 | power-share setpoint | clamped to 0.0 to 1.0 |
| 15 | 4 | float32 | charge goal | — |
| 19 | 1 | uint8   | mode | 0 hybrid, 1 fuel cell only, 2 battery, 3 charge, 4 safe |
| 20 | 1 | uint8   | reserved | see below |
| 21 | 1 | uint8   | checksum | — |

Struct format string: `"<BIHfffBBB"`.

The firmware admits each of the three floats only when the value is finite. A non-finite field
is discarded and the previous value is held.

Byte 20 is **reserved**. The firmware reads it and discards it; no hardware responds to it.
Continue to transmit it, and do not assume that setting it enables or disables anything.

The firmware requires a command at least every 500 ms. A longer gap latches a watchdog fault
and stops the motor.

---

## 6. Sign-off

Prepared by Ricky Tan, rstan@ucdavis.edu, 2026-09-01.

Reply with the revised module list once §3.1 and §3.2 are applied. Those two changes gate the
next hardware campaign; §3.3 to §3.5 may follow.
