# Scale_Car_Teensy

Teensy 4.1 firmware for a scale FCHEV (Fuel-Cell Hybrid EV) platform — the **Scale Car DC
Balancer Board, Rev 20260622**.

The board is a bidirectional power-pathing balancer: ideal-diode source switches route a fuel
cell and a 2S battery onto a shared VBUS, a regen path returns braking energy to the charger,
and an MPPT module harvests into the battery. This firmware drives that hardware.

It controls:
- motor torque through a VESC (`VescUart` over UART),
- fuel-cell/battery power sharing through dual AD5443 MDAC droop outputs (SPI),
- the RT1987 ideal-diode power-path switches (6 sequenced GPIOs),
- the Silvertel **Ag105** MPPT battery charger (I2C config + `MPPT_DISABLE` GPIO),
- the BQ29200 cell OVP/balancer (`CBAL_DISABLE` GPIO),
- command/telemetry with a Raspberry Pi over UDP Ethernet,
- a safety state machine, Pi watchdog, latching fault handling, and a USB-serial test mode.

> The authoritative hardware sources are `references/Scale Car Teensy IO - IO.csv` (pin map),
> `references/Scale Car Design PCB BOM 20260622.csv` (parts), and the schematic PDF. See
> `CLAUDE.md` for the reconciliation spec and `PLAN.md` for the implementation plan.

## Hardware interfaces

- **UART (`Serial1`)**: VESC motor controller (`RX`=0, `TX`=1).
- **SPI**: two AD5443 MDACs (`CS_MDAC_FC`=36, `CS_MDAC_BT`=37) for FC/BT droop gains; OPA197
  output buffers run from the 5 V rail (hardware bodge).
- **I2C (`Wire`)**: Silvertel **Ag105** charger at address **0x30**.
- **Ethernet/UDP**: command in (port 5001), telemetry out (port 5000), Teensy IP 192.168.1.50.
- **Encoder interrupts**: wheel-speed estimation from `ENC_A`=2 / `ENC_B`=8.
- **ADC inputs (12-bit)**: FC/BT current (INA253A1, 0.1 V/A), FC/BT/BUS/CHG/RGN voltages.
- **Digital outputs**: FC/BT boost enables, 6 RT1987 path switches, `MPPT_DISABLE`,
  `CBAL_DISABLE`, encoder enable.

### Power-path switches (RT1987 ideal-diode controllers)

| Pin | Name | Role |
|----|------|------|
| 27 | `FC_BUS_ENABLE` | FC regulator → VBUS |
| 28 | `BT_BUS_ENABLE` | BT regulator → VBUS |
| 29 | `MOT_PWR_ENABLE` | VBUS → VESC/motor (Run only) |
| 30 | `REGEN_ENABLE` | regen → charger input |
| 31 | `FC_CHARGE_ENABLE` | VBUS(FC) → charger (guarded) |
| 32 | `BT_SEQUENCE_ENABLE` | battery-pack sequencing (init LOW, then HIGH) |

All switches default LOW at boot (fail-safe; 10 kΩ EN-to-GND bodge resistors back this up).
`FC_CHARGE_ENABLE` and `REGEN_ENABLE` are **mutually exclusive** and are only ever driven
through `assertFcChargeEnable()`, which forces `BT_BUS_ENABLE` and `REGEN_ENABLE` LOW (with an
RT1987 turn-off settle delay) before opening the FC→charger path.

**VBUS bring-up — never hot-plug a running boost onto a dead bus.** VBUS carries a 470 µF bulk
cap. Connecting a boost that is already running at ~17.5 V onto a discharged 0 V bus forces a
large charge transient that the RT1987 absorbs as SCP current-limit bursts — which (on the shared
9 V bench rail) browned out the Teensy and destroyed a boost. The boots are therefore brought up
**gently**: enable the bus switches *first* (the RT1987s soft-start the bus from a low voltage),
then enable the boosts so their own soft-start ramps the bus to 17.5 V. This is handled in State 0
and mirrored by the State 98 `G` command; the bus is then kept energized through Idle/Finish so a
Run never re-hot-plugs it.

## Runtime flow

Main loop execution order:
1. `updateSensors()`
2. `computeDerivedSignals()`
3. `detectFaults()`
4. `checkPiWatchdog()`
5. `receiveCommands()`
6. state machine (`doState0/1/2/3/98/99`)
7. `pollAg105()` + `sendTelemetry()` at ~50 Hz

## State machine

- **State 0 (Init)**: a **non-blocking phase machine** that brings VBUS up gently — enable the
  bus switches first (`FC_BUS_ENABLE`/`BT_BUS_ENABLE`), settle, then enable the FC/BT boosts so
  their soft-start ramps the bus (see *VBUS bring-up* above). It also raises `BT_SEQUENCE_ENABLE`,
  inits the MDAC and VESC, then **gates the transition to Idle on `V_bus ≥ V_BUS_CHARGED_THRESH`**.
  If the bus never reaches the threshold within `BUS_CHARGE_TIMEOUT_MS`, it raises `FAULT_INIT_FAIL`
  → State 99 (catches a dead boost, a failed switch, or no source). The Ag105 is **not** configured
  here — it is unpowered in Init; `pollAg105()` configures it lazily once a charger path powers it.
- **State 1 (Idle)**: motor current zero, `MOT_PWR_ENABLE` LOW; the bus is left **energized**
  (boosts + bus switches stay ON). Waits for a Run command from the Pi, or `T` on USB serial to
  enter test mode (State 98).
- **State 2 (Run)**: `MOT_PWR_ENABLE` HIGH; run `chargingControl()`, `motorControl()`,
  `powerBalance()`. `chargingControl()` owns the `REGEN`/`FC_CHARGE`/`BT_BUS` switches and the
  `MPPT_DISABLE` line. The bus is already up from Init/Idle, so entering Run does not hot-plug it.
- **State 3 (Finish)**: stops the motor and closes the motor/regen/charge paths, but **leaves the
  boosts + bus switches ON** so the bus stays armed and the next Idle→Run never re-hot-plugs the
  470 µF bus. Clears the wheel-speed buffer and returns to Idle. (No cap/regen drain — the
  disabled-boost back-feed hazard doesn't apply while the boosts stay enabled.)
- **State 98 (Test)**: USB-serial hardware exerciser (see below).
- **State 99 (Error)**: **non-blocking** two-phase safe shutdown that bleeds VBUS/regen energy and
  then disables the boosts and tears the bus down — latched until power cycle (which re-runs the
  State-0 gentle bring-up).

The State 99 shutdown is a phase machine gated on `millis()` (no blocking `delay()`), so
`detectFaults()` keeps sampling through the highest-energy drain windows.

## Charger control (Silvertel Ag105)

There is **no charge-current register to program per-mA**. Control is:
- **I2C config at init** (`initAg105Charger()`): reg `0x00 = 0x01` (2.5 A profile),
  reg `0x01 = 0x08` (2S / 8.4 V). Stored in EPROM; rewritten every boot.
- **`MPPT_DISABLE` GPIO (pin 5, active-LOW)**: LOW inhibits the MPPT perturb-and-observe loop
  (during regen, so it doesn't fight the fast transient); HIGH releases it (cruise/coast
  harvest).
- **I2C polling** (`pollAg105()` at 50 Hz): reads reg `0x06` (measured charge current,
  0.011 A/count) into `I_charge`, and caches the Table-6 status byte. The Ag105 prepends its
  status byte before any read, so each 1-byte field is read as 2 bytes.
- **Readiness** (`ag105IsReady()`): GENSTAT (status bits [2:0]) == Charging (0x02) or
  Fully Charged (0x03).
- An Ag105 I2C read failure only latches State 99 in the charging-relevant states (Run/Finish);
  in Init/Idle/Test a missing or still-powering charger does not lock the system.

## Telemetry & commands

- **Commands**: 22-byte UDP packet (sync `0xBB` + XOR checksum). Fields: timestamp, counter,
  `v_setpoint`, `power_share_setpoint`, `charge_goal`, `mode_cmd`, and a reserved `droop_enable`
  byte (parsed, not yet wired).
- **Telemetry — protocol v4, 58 bytes** (`TELEMETRY_VERSION = 4`, sync `0xAA`, XOR over bytes
  1–56). Carries the measured/derived signals, droop gains, the raw Ag105 Table-6
  `charger_status` byte (offset 51), a `switch_state` bitmask of the 6 path switches, a 16-bit
  `fault_flags`, the latched `error_code`, and `error_source_state`. The Pi bridge parses fixed
  offsets and **must match this version** — see `PLAN.md` §6b for the byte-by-byte layout and the
  block comment above `sendTelemetry()`.

## Key functions

### `motorControl()` + `PI_Controller_Motor()`
Computes torque from speed error (`v_setpoint - v_actual`) and commands VESC current. The
integrator has **anti-windup**: `pi_motor_accum` is clamped to the torque equivalent of
`MOTOR_I_CMD_MAX`. Integrator state is file-scope (resettable by the unit tests).

### `powerBalance()` + `PI_Controller_Power()`
Controls the FC/BT split from measured INA253 currents; PI output (`droopRatio`) is mapped to
FC/BT droop gains and written via `setDroopMdac()` (AD5443, SPI_MODE0, MSB-first, `transfer16`).

### `chargingControl()`
Manages `MPPT_DISABLE` and the regen/FC-charge/BT-bus switches based on `charge_goal`, regen
state (`current < -0.1`), and Ag105 readiness — enforcing the FC-charge/regen mutual exclusion.

### `updateWheelSpeed()` + encoder ISRs
Encoder counts over a moving time window estimate flywheel speed → `v_actual`. The averaging
buffer is reset by State 3 between runs so a new run's first samples aren't measured against
stale timestamps.

## Safety features

- FC overcurrent (`I_fc > LIMIT_I_FC_MAX`), BT overcurrent (`I_batt > LIMIT_I_BT_MAX`)
- Battery UV/OV, FC UV — **UV checks are gated to Run (State 2)** so unramped rails at boot
  don't latch State 99
- Bus OV (`LIMIT_V_BUS_MAX = 18.5 V`, below the 19 V TPS61288 HW OVP) and Bus UV (Run only)
- Regen-node and charger-input overvoltage
- Illegal switch combination (`FC_CHARGE_ENABLE` with `BT_BUS`/`REGEN`)
- Ag105 GENSTAT error states (OC/Regulation 0x05, Thermal Shutdown 0x06, Timeout 0x07) and I2C
  comms failure
- Pi watchdog timeout (`PI_TIMEOUT_MS`, States 2/3 only)

Faults funnel through `triggerFault()`, which latches a primary `error_code` + source state and
transitions to **State 99**.

## Fault reference

When any check in `detectFaults()` trips, `triggerFault()` sets that condition's bit in the
16-bit `fault_flags`, latches the **first** cause into `error_code` (and the active state into
`error_source_state`), forces `FAULT_ERROR` (`0x8000`), and transitions to **State 99** —
latched until power cycle. Both `fault_flags` and `error_code` ride in the v4 telemetry packet,
so every value below is observable on the Pi. Read `error_code` for the root cause and
`fault_flags` for everything that tripped.

### Fault flags (`fault_flags` bitmask)

`fault_flags` is an OR of these bits — more than one can be set at once:

| Mask | Flag | Trigger | Limit | Gated to |
|------|------|---------|-------|----------|
| `0x0001` | `FAULT_OC_FC` | `I_fc` overcurrent | `LIMIT_I_FC_MAX = 3.5 A` | all |
| `0x0002` | `FAULT_UV_BATT` | `V_batt` undervoltage | `LIMIT_V_BATT_MIN = 6.2 V` | Run |
| `0x0004` | `FAULT_OV_BUS` | `V_bus` overvoltage | `LIMIT_V_BUS_MAX = 18.5 V` | all |
| `0x0008` | `FAULT_SWITCH_CONFLICT` | `FC_CHARGE_ENABLE` high while `BT_BUS`/`REGEN` high | — | all |
| `0x0010` | `FAULT_PI_TIMEOUT` | Pi watchdog expired | `PI_TIMEOUT_MS` | States 2/3 |
| `0x0020` | `FAULT_OV_BATT` | `V_batt` overvoltage | `LIMIT_V_BATT_MAX = 8.6 V` | all |
| `0x0040` | `FAULT_UV_FC` | `V_fc` undervoltage | `LIMIT_V_FC_MIN = 6.0 V` | Run |
| `0x0080` | `FAULT_OC_BT` | `I_batt` overcurrent | `LIMIT_I_BT_MAX = 6.0 A` | all |
| `0x0100` | `FAULT_UV_BUS` | `V_bus` undervoltage | `LIMIT_V_BUS_MIN = 12.0 V` | Run |
| `0x0200` | `FAULT_OV_RGN` | regen-node overvoltage | `LIMIT_V_RGN_MAX = 28.0 V` | all |
| `0x0400` | `FAULT_OV_CHG` | charger-input overvoltage | `LIMIT_V_CHG_MAX = 24.0 V` | all |
| `0x0800` | `FAULT_I2C_CHARGER` | Ag105 I2C comms failure | — | Run/Finish |
| `0x1000` | `FAULT_CHARGER_STAT` | Ag105 GENSTAT error (`0x05` OC/regulation, `0x06` thermal, `0x07` timeout) | — | charging states |
| `0x2000` | `FAULT_INIT_FAIL` | init failure: VBUS failed to reach `V_BUS_CHARGED_THRESH` within `BUS_CHARGE_TIMEOUT_MS` (also legacy Ag105 config) | `V_BUS_CHARGED_THRESH` | State 0 |
| `0x8000` | `FAULT_ERROR` | latched marker: system entered State 99 | — | set with any fault |

The UV checks marked **"Gated to Run"** are deliberately suppressed outside State 2, so unramped
rails at boot don't latch State 99 (see Safety features above).

### Error codes (`error_code` latched cause)

`error_code` is the single latched primary cause — the *first* fault to fire — and is distinct
from the multi-bit `fault_flags`. `error_source_state` records which state was active when it
latched. Values map 1:1 to `errorCodeStr()`:

| Code | Enum | String |
|------|------|--------|
| `0x00` | `ERR_NONE` | (none) |
| `0x01` | `ERR_OC_FC` | FC overcurrent |
| `0x02` | `ERR_UV_BATT` | Batt undervoltage |
| `0x03` | `ERR_OV_BUS` | Bus overvoltage |
| `0x04` | `ERR_SWITCH_CONFLICT` | Switch conflict |
| `0x05` | `ERR_PI_TIMEOUT` | Pi timeout |
| `0x06` | `ERR_OV_BATT` | Batt overvoltage |
| `0x07` | `ERR_UV_FC` | FC undervoltage |
| `0x08` | `ERR_OC_BT` | BT overcurrent |
| `0x09` | `ERR_UV_BUS` | Bus undervoltage |
| `0x0A` | `ERR_OV_RGN` | Regen overvoltage |
| `0x0B` | `ERR_OV_CHG` | Charger input OV |
| `0x0C` | `ERR_I2C_CHARGER` | Ag105 I2C fail |
| `0x0D` | `ERR_CHARGER_STAT` | Ag105 STAT fault |
| `0x0E` | `ERR_INIT_FAIL` | Init failure |

**Recovery:** State 99 is latched — a fault clears only on a power cycle. Diagnose with
`error_code` (root cause) first, then inspect the full `fault_flags` bitmask for any secondary
conditions that tripped in the same tick.

## Test mode (State 98)

State 98 is a USB-serial hardware exerciser for bench bring-up. **Enter** it by sending `T`
while in Idle (State 1); **exit** with `Q`, which returns to Idle and forces `MOT_PWR_ENABLE`
LOW. The Pi watchdog is suspended in this state, but `detectFaults()` still runs every tick — a
fault latches State 99 exactly as in normal operation. `FC_CHARGE_ENABLE` only ever moves through
`assertFcChargeEnable()`, even here.

### Serial command set

All commands are single characters over USB serial; every toggle echoes the resulting pin state
back over serial:

| Key | Action | Notes |
|-----|--------|-------|
| `F` | Toggle `FC_REG_ENABLE` (FC boost) | |
| `B` | Toggle `BT_REG_ENABLE` (BT boost) | |
| `1` | Toggle `FC_BUS_ENABLE` | **ON refused** if FC boost is ON and `V_bus` < `V_BUS_CHARGED_THRESH` (hot-plug guard — use `G`) |
| `2` | Toggle `BT_BUS_ENABLE` | **ON refused** if BT boost is ON and `V_bus` < `V_BUS_CHARGED_THRESH` (hot-plug guard — use `G`) |
| `3` | Toggle `MOT_PWR_ENABLE` | must be HIGH before a drive cycle (`D`) |
| `4` | Toggle `REGEN_ENABLE` | forces `FC_CHARGE` off via `assertFcChargeEnable(false)` before going HIGH |
| `5` | Toggle `FC_CHARGE_ENABLE` | always through the `assertFcChargeEnable()` guard |
| `6` | Toggle `BT_SEQUENCE_ENABLE` | |
| `C` | Toggle `CBAL_DISABLE` | HIGH = OVP bypassed (prints a warning) |
| `M` | Toggle `MPPT_DISABLE` | HIGH = MPPT harvesting; LOW = inhibited |
| `G` | Safe VBUS bring-up | bus switches → settle → boosts (`bringUpBus()`); the safe way to energize the bus |
| `D` | Start/stop simulated drive cycle | requires `MOT_PWR_ENABLE` HIGH to start |
| `S` | Print status dump (all pins, all ADCs, `I_charge`, `fault_flags`, `error_code`) | read-only |
| `I` | Scan the I2C bus | read-only |
| `Q` | Exit → Idle (State 1) | forces `MOT_PWR_ENABLE` LOW |

### Testing an individual component

1. Connect a USB-serial terminal and send `T` to enter test mode from Idle.
2. Send `S` to capture a baseline snapshot of all pin states and ADC readings.
3. Toggle the line(s) you want to exercise with the keys above; the firmware echoes each new
   state so you can confirm the write landed.
4. Re-send `S` to read back the effect on the relevant ADC/pin.
5. Send `Q` to exit (this forces `MOT_PWR_ENABLE` LOW).

Mind the guarded keys: `5` (`FC_CHARGE_ENABLE`) always runs through `assertFcChargeEnable()`,
which drives `BT_BUS_ENABLE`/`REGEN_ENABLE` LOW first; `4` (`REGEN_ENABLE`) forces `FC_CHARGE`
off before going HIGH; `1`/`2` refuse to connect a source to the bus while the matching boost is
running and the bus is discharged (use `G` to energize the bus safely first); and `C`
(`CBAL_DISABLE` HIGH) bypasses cell OVP — use with care.

### Running the emulated drive cycle

1. Set `MOT_PWR_ENABLE` HIGH first with key `3` — `D` aborts with an error otherwise.
2. Press `D` to start. While active, `advanceDriveCycle()` supplies a pre-programmed
   `v_setpoint`, and the real `chargingControl()` / `motorControl()` / `powerBalance()` run
   unmodified, in the same call order as State 2 — only the setpoint source differs.
3. A `[DC]` status line prints every 500 ms: `t`, `v_sp`, `v_act`, `V_bus`, `I_fc`, `I_bt`,
   `I_chg`, and `FLT` (fault flags).
4. Press `D` again to stop early — the firmware flushes a zero VESC command and parks all path
   switches via `safeAllSwitches()`.

The profile runs through these phases (from `DRIVE_CYCLE[]`):

| Phase | Duration | `v_setpoint` | Purpose |
|-------|----------|--------------|---------|
| 0 Standstill | 2 s | 0.0 | verify sensors, confirm no faults |
| 1 Ramp-up | 4 s | 0.0 → 3.0 | linear ramp; `motorControl()` live |
| 2 Cruise | 6 s | 3.0 | steady speed; `powerBalance()` live |
| 3 Coast-down | 3 s | 3.0 → 0.0 | linear ramp down |
| 4 Regen hold | 3 s | −0.5 | negative setpoint (regen braking) |
| 5 Standstill | 2 s | 0.0 | confirm `I_charge > 0` if charging |

On completion `v_setpoint` returns to 0, but `MOT_PWR_ENABLE` is left as the operator set it —
toggle it off with `3`, or exit with `Q` (which forces it LOW).

## Unit tests

A host-native suite in `test/` builds and runs with `g++` — no Teensy or Arduino IDE required:

```bash
cd test && make           # or: g++ -std=c++17 -Wall -Wextra -I. -I.. test_main.cpp -o run_tests
```

Mocks stub the Teensy/Arduino, Wire, SPI, VESC, and Ethernet APIs. Coverage includes scale-factor
math, fault detection (incl. GENSTAT decode and UV boot-gating), PI convergence + anti-windup,
command parsing, telemetry packing (58-byte v4 layout + checksum), the Ag105 init/poll I2C
sequences, `assertFcChargeEnable()` ordering, `pollAg105()` state gating, `doState0()` init-fault
handling, the State 98 drive cycle, and the wheel-speed buffer reset. Run before every flash.

## Notes for calibration

Items marked `TODO(calibrate)` / `TODO(verify)` in the source still need bench values, including:
- `SCALE_V_CHG` / `SCALE_V_RGN` dividers, and confirmation of the FC/BT/BUS dividers
- `motorConstant`, the PI gains (`Kp`, `Ki`), and `MOTOR_I_CMD_MAX` (anti-windup bound)
- the VBUS bring-up tunables: `V_BUS_CHARGED_THRESH`, `BUS_SETTLE_MS`, `BUS_CHARGE_TIMEOUT_MS`
- the regen-detection threshold and the State 99 cap-drain / regen-decay delays
- encoder counts-per-rev mapping to true vehicle speed
- AD5443 SPI timing/word-format verification against `references/Datasheets/ad5426_5432_5443.pdf`
