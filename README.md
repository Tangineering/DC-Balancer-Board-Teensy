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

- **State 0 (Init)**: enable FC/BT boosts, raise `BT_SEQUENCE_ENABLE`, init MDAC, configure the
  Ag105 over I2C, init VESC, then go to Idle. **Aborts to State 99 if the Ag105 I2C config
  fails** (does not silently demote to Idle).
- **State 1 (Idle)**: motor current zero, `MOT_PWR_ENABLE` LOW; wait for a Run command from the
  Pi, or `T` on USB serial to enter test mode (State 98).
- **State 2 (Run)**: `MOT_PWR_ENABLE` HIGH; run `chargingControl()`, `motorControl()`,
  `powerBalance()`. `chargingControl()` owns the `REGEN`/`FC_CHARGE`/`BT_BUS` switches and the
  `MPPT_DISABLE` line.
- **State 3 (Finish)**: **non-blocking** two-phase safe shutdown (bleed VBUS caps → bleed
  regen), then clears the wheel-speed buffer and returns to Idle.
- **State 98 (Test)**: USB-serial hardware exerciser (see below).
- **State 99 (Error)**: **non-blocking** two-phase safe shutdown, then disables boosts, latched
  until power cycle.

The State 3/99 shutdowns are phase machines gated on `millis()` (no blocking `delay()`), so
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
- **Telemetry — protocol v3, 57 bytes** (`TELEMETRY_VERSION = 3`, sync `0xAA`, XOR over bytes
  1–55). Carries the measured/derived signals, droop gains, a `switch_state` bitmask of the 6
  path switches, a 16-bit `fault_flags`, the latched `error_code`, and `error_source_state`.
  The Pi bridge parses fixed offsets and **must match this version** — see `PLAN.md` §6b for the
  byte-by-byte layout and the block comment above `sendTelemetry()`.

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

## Test mode (State 98)

Reachable from Idle via `T` on USB serial. Single-char commands toggle each boost and path
switch (`F B 1 2 3 4 5 6 C M`), print status (`S`), run a simulated drive cycle (`D`), or exit
(`Q`). `FC_CHARGE_ENABLE` always goes through `assertFcChargeEnable()`. The drive cycle supplies
a pre-programmed `v_setpoint` profile and runs `motorControl()`/`powerBalance()`/
`chargingControl()` unmodified. Stopping the cycle (`D`) flushes a zero VESC command and parks
all path switches safe; `Q` additionally forces `MOT_PWR_ENABLE` LOW. `detectFaults()` still runs
every tick; the Pi watchdog does not fire in this state.

## Unit tests

A host-native suite in `test/` builds and runs with `g++` — no Teensy or Arduino IDE required:

```bash
cd test && make           # or: g++ -std=c++17 -Wall -Wextra -I. -I.. test_main.cpp -o run_tests
```

Mocks stub the Teensy/Arduino, Wire, SPI, VESC, and Ethernet APIs. Coverage includes scale-factor
math, fault detection (incl. GENSTAT decode and UV boot-gating), PI convergence + anti-windup,
command parsing, telemetry packing (57-byte layout + checksum), the Ag105 init/poll I2C
sequences, `assertFcChargeEnable()` ordering, `pollAg105()` state gating, `doState0()` init-fault
handling, the State 98 drive cycle, and the wheel-speed buffer reset. Run before every flash.

## Notes for calibration

Items marked `TODO(calibrate)` / `TODO(verify)` in the source still need bench values, including:
- `SCALE_V_CHG` / `SCALE_V_RGN` dividers, and confirmation of the FC/BT/BUS dividers
- `motorConstant`, the PI gains (`Kp`, `Ki`), and `MOTOR_I_CMD_MAX` (anti-windup bound)
- the regen-detection threshold and the State 3/99 cap-drain / regen-decay delays
- encoder counts-per-rev mapping to true vehicle speed
- AD5443 SPI timing/word-format verification against `references/Datasheets/ad5426_5432_5443.pdf`
