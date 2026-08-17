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
- **Encoder interrupts**: wheel-speed estimation from `ENC_A`=14 / `ENC_B`=15 (bodged from 2/8 on
  2026-08-16; the optical sensors are hardwired to power, so there is no enable pin).
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

**VBUS bring-up — only enable a boost on a stiff source.** The hazard is *not* bus inrush: VBUS
carries only ~30–40 µF (the RT1987 ceramics); the 470 µF bulk cap is on the V-MOT/regen node behind
`MOT_PWR_ENABLE`. The real failure mode is enabling a boost on a source that can **collapse**:
switching with built-up inductor current on a sagging/recovering rail destroys the power stage. The
exact mechanism is **unconfirmed pending a scope capture** — most likely a VOUT overshoot past the
20 V SW/VOUT abs-max (the TPS61288 OVP is at 19 V, only ~0.5 V of margin, and the 3×22 µF output
caps DC-derate to ~30 µF) and/or transient reverse conduction. Either way the destructive energy
comes from the boost's own inductor/output cap, so *a supply current limit does not bound it*. On a
board-powered Teensy this also motorboats: the boost loads `VBT`, the logic rail browns out, the MCU
resets, and re-enables the boost. So in **production** (`BENCH_TEST=0`, stiff vehicle source) State 0
brings the bus up gently (switches first, then the boosts' own soft-start) and is mirrored by the
State 98 `G` command; the bus is then kept energized through Idle/Finish so a Run never re-hot-plugs
it. Under **`BENCH_TEST`** State 0 keeps the power stage **off** at boot (see State 0 below). Bench
rule: the supply must exceed the logic baseline (≥ ~0.5–1 A) or the board-powered Teensy browns out,
and the bus may be brought up (`G`) only on a stiff supply.

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

- **State 0 (Init)**: behavior depends on the `BENCH_TEST` build flag.
  - **Production (`BENCH_TEST=0`)**: a **non-blocking phase machine** that brings VBUS up gently —
    bus switches first (`FC_BUS_ENABLE`/`BT_BUS_ENABLE`), settle, then the FC/BT boosts (their
    soft-start raises the bus; see *VBUS bring-up* above). Raises `BT_SEQUENCE_ENABLE`, inits the
    MDAC and VESC, then **gates the transition to Idle on `V_bus ≥ V_BUS_CHARGED_THRESH`**; if the
    bus never reaches it within `BUS_CHARGE_TIMEOUT_MS`, raises `FAULT_INIT_FAIL` → State 99
    (catches a dead boost, failed switch, or no source).
  - **Bench (`BENCH_TEST=1`, the default flash)**: boots **straight to Idle with the power stage
    OFF** — boosts, bus switches, and `BT_SEQUENCE` all stay LOW, and there is no `V_bus` gate. This
    prevents enabling a boost on a soft/current-limited bench supply (which browns out the
    board-powered Teensy and motorboats the boost to failure). Bring the bus up manually with the
    State 98 `G` command on a stiff supply.
  - Either way the Ag105 is **not** configured here — it is unpowered in Init; `pollAg105()`
    configures it lazily once a charger path powers it. Shared init lives in `initControlPeripherals()`.
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
- Bus OV (`LIMIT_V_BUS_MAX = V_BUS_NOMINAL + 1.5 = 17.5 V` at the 16.0 V nominal, below the 19 V TPS61288 HW OVP) and Bus UV (Run only)
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
| `0x0004` | `FAULT_OV_BUS` | `V_bus` overvoltage | `LIMIT_V_BUS_MAX = 17.5 V` | all |
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
| `2` | Toggle `BT_BUS_ENABLE` | same hot-plug guard as `1`; **also refused** while `FC_CHARGE_ENABLE` is HIGH (illegal combination) |
| `3` | Toggle `MOT_PWR_ENABLE` | ON allowed **only at a regulated bus** (`motPwrConnectBlocked()`); must be HIGH before `D`/`R` |
| `4` | Toggle `REGEN_ENABLE` | forces `FC_CHARGE` off via `assertFcChargeEnable(false)` before going HIGH |
| `5` | Toggle `FC_CHARGE_ENABLE` | always through the `assertFcChargeEnable()` guard |
| `6` | Toggle `BT_SEQUENCE_ENABLE` | |
| `C` | Toggle `CBAL_DISABLE` | HIGH = OVP bypassed (prints a warning) |
| `M` | Toggle `MPPT_DISABLE` | HIGH = MPPT harvesting; LOW = inhibited |
| `G` | Staged bus bring-up | `busBringupTick()` phases P0–P3: bus alone → boosts → dwell → motor node; `X` aborts (stage dark) |
| `D` | Start/stop simulated drive cycle | requires `MOT_PWR_ENABLE` HIGH and the calibrated velocity chain |
| `S` | Print status dump (all pins, ADCs, `I_charge`, faults, bench-tool state) | read-only |
| `I` | Scan the I2C bus | read-only |
| `E` | One-shot VESC firmware + telemetry read | blocks up to ~100 ms (bench-only) |
| `U` | Toggle VESC watch (~2 Hz `[VW]` line, flags fault changes) | **rebound from `W` (2026-08-10)**; auto-paused during profiles and plot mode |
| `P` | Set power-share setpoint (prompts for a value) | closed-loop: `powerBalance()` drives the MDACs live; needs current flowing |
| `O` | Set droop ratio 0.15–0.85 (prompts for a value) | open-loop direct MDAC write; no current needed — the calibration entry point |
| `A` | Set manual motor current in A (prompts) | constant VESC current, bypasses the velocity PI |
| `V` | Set manual motor velocity in m/s (prompts) | refused until the velocity chain is calibrated |
| `R` | Start/stop power-share profile sweep | needs `A`/`V` set + `MOT_PWR_ENABLE` HIGH; stop parks switches |
| `T <Imax> <hold s> <rate A/s>` | Start trapezoidal current profile (one line, e.g. `T 6 5 0.5`) | direct phase-current ramp; `T` alone while running stops it; switches left as-is |
| `Y [Vmax] [b]` | Start combined drive-cycle + power-share profile (one line, both args optional, e.g. `Y 1 0.3`) | sweeps velocity **and** share together; same prerequisites as `D`; `Y` alone while running stops it |
| `W [Imax] [b]` | Start combined **current** + power-share profile (one line, both args optional, e.g. `W 6 0.0`) | same table as `Y` with the motor axis in amps; no encoder needed; `W` alone while running stops it |
| `X` | Universal stop | cancels any profile/bring-up/armed run + manual motor + live share loop |
| `L` | Toggle Serial-Plotter stream | 50 Hz `sp,act,gFC,gBT,ifc,ibt` line; suppresses status lines; `R`/`T` arm with a 5 s delay |
| `K` | Print SD-card logging status | card present, current/last file, record/drop counts; read-only |
| `H` / `?` | Print the command list | |
| `Q` | Exit → Idle (State 1) | forces `MOT_PWR_ENABLE` LOW, closes charge/regen paths, drops plot mode |

### Serial-Plotter stream (`L`)

For live plotting in the Arduino IDE (Tools → Serial Plotter). `L` toggles a condensed 50 Hz
line — `sp:…,act:…,gFC:…,gBT:…,ifc:…,ibt:…` (share setpoint, measured share, both droop gains,
both channel currents; all naturally 0–3 so the plotter's shared autoscale keeps every trace
readable). While ON, the periodic human-readable output that would break the plotter's parser is
suppressed: the `[PS]`/`[DC]`/`[TP]` 500 ms snapshots, phase banners, and the `[VW]` watch line
(VESC faults latch, so they're still reported once plotting stops). Because the IDE 2.x plotter
has no send box, `R` and `T` under plot mode **arm** the run and fire it 5 s later — switch to
the plotter window during the countdown. The arm cancels on the same key again, `X`, `Q`,
turning `L` off, or any other run starting; `R`'s preconditions are re-checked at fire time.
Arming is refused while another profile is already running, and arming the other profile
supersedes a pending arm with an explicit cancel message.

### SD-card logging (`K` / automatic)

Logs the power-share/motor/bus signals at the full 1 kHz control cadence to the Teensy's
built-in micro-SD — 20x finer than the 50 Hz `L` stream, needed to see the Youla-H share loop's
actual transient. Logging starts and stops automatically with the profile lifecycle: it opens
when `R`, `T`, `D`, `Y`, or `W` starts, and closes on natural completion, the matching stop-toggle, `X`,
`Q`, or a fault (the close is deferred out of the fault transition and held until the State-99
teardown is latched, so it cannot lengthen a teardown dwell). There's no separate arm command — a card present at profile start is logged, a missing
one is silently skipped. No card in the slot, a full card, or a write error never faults the
board or blocks a profile: the firmware prints a warning and keeps running. `K` prints a
status line — card present, current/last file name (`PS`/`TP`/`DC`/`YP`/`WP` prefix by profile type),
record and drop counts — and stays live
even during the bring-up lockout. It reports no free-space figure on purpose: the FAT-walking
calls that would produce one block for seconds on a real card. Retrieve a run by pulling the card (`PSnnnn.BLG` /
`TPnnnn.BLG` / `DCnnnn.BLG` / `YPnnnn.BLG` / `WPnnnn.BLG` in the root) and decode it on the laptop:

```
python tools/decode_benchlog.py FILE.BLG > run.csv
```

### Combined drive-cycle + power-share profile (`Y`)

`D` moves the velocity with the share held still; `R` moves the share with the motor held still.
`Y` moves **both at once**, which is the only way to see the cross-coupling the vehicle actually
runs in — the velocity loop's changing bus draw against the share loop's changing droop split.
It's a fixed 40 s, 16-region table: solo ramps and steps on each axis (so you can still fit a
per-axis response from the same run), two deliberately simultaneous regions (a combined ramp and a
combined step), buffers between excitations to let each transient settle, and two brief excursions
to the share extremes (all-FC, all-BT) to check the droop clamp.

Both arguments are optional and go on one line with the key:

```
Y 1 0.3
```

- **`Vmax`** (m/s, default `1.0`) scales the table's normalised velocity waypoints, so the same
  profile works at any bench speed. Must be greater than 0 and no more than 5.0 m/s — the same
  ceiling the `V` manual-velocity key enforces.
- **`b`** (default `0`) clips the share setpoint to `[b, 1−b]`, for keeping a fragile setup away
  from the share extremes. Must satisfy `0 ≤ b < 0.5` (at 0.5 the band collapses to a point and
  the share axis flattens, so it's refused). Above 0.35 it still runs but prints a warning: the
  clip then starts eating the table's intermediate plateaus, not just the 0/1 bound checks.

The clip is applied *after* interpolation, so a ramp that crosses the bound keeps its normal slope
and then flattens — that kink is deliberate, not a bug. A bare `Y` + Enter runs the defaults.

Like `R` and `T` — and unlike `D` — `Y` does **not** run the charging manager. That's deliberate:
`chargingControl()` would open the FC charge path mid-run, which drops the battery off the bus and
pins the measured share at 1.0, destroying the very thing the run is measuring. Your charge and
regen switches stay exactly where you set them, so a share experiment behaves as though
`charge_goal` were 0 no matter what the Pi last commanded; coast-down regen is soaked up by the
hardware braking chopper as always. `Y` also starts immediately under plot mode rather than
arming like `R`/`T` (its prerequisites are checked at the keypress, which an arming delay would
undermine); a pending `R`/`T` arm is refused over, and cancelled by, a running `Y`.

Prerequisites are the same as `D`: no bring-up in progress, a calibrated velocity chain, and
`MOT_PWR_ENABLE` HIGH (key `3`). Press `Y` again to stop — the motor is zeroed and the path
switches parked, exactly as stopping `D` or `R` does. On natural completion the motor is zeroed
and the share returns to 0.50, with the switches left as they are (matching how `D`/`R` finish).
`X` and `Q` stop it like any other profile — and note that **stopping parks all the switches, so
the bus is dark and you need another `G` before the next run** (a natural completion doesn't).
Runs log automatically to `YPnnnn.BLG` (same
`decode_benchlog.py`, no format change — the profile's region index appears in *both* the
drive-cycle and power-share phase columns, which is how you recognize a combined run).

### Combined current + power-share profile (`W`)

`Y` needs a calibrated encoder chain, which the bench doesn't have yet — so `W` is the combined-axis
run you can actually do today. It's the same 16-region, 40 s table, with the motor axis
reinterpreted as **commanded current** instead of velocity. Everything about the motor side follows
`T`: current goes straight to the VESC, the velocity PI is never involved, no calibration is
required, and `MOT_PWR_ENABLE` LOW is only a warning (your VESC may have its own supply).

```
W 6 0.0
```

- **`Imax`** (A, default `5.0`) scales the table's normalised motor column — at the default the
  plateaus are 0 / 3.0 / 5.0 / 2.5 / 1.0 A. Must be greater than 0 and no more than 25 A, the same
  ESC ceiling `T` uses; peaks above the 5 A budget are allowed, exactly as in `T`. Negative peaks
  are refused here (the table already coasts back to zero — use `T` for a braking ramp).
- **`b`** works exactly as in `Y`, with the same clip, the same bounds, and the same warning above
  0.35.

Stopping (`W` again) zeroes the motor, returns the share to 0.50, and parks the path switches —
the `Y`/`R` convention rather than `T`'s, because this profile sweeps the share and therefore owns
the source configuration during the run. **A stopped run leaves the bus dark, so you need a fresh
`G` bring-up before the next one** (a run that finishes on its own leaves the switches alone). `X` and `Q` stop it like any other profile, and it's
mutually exclusive with `D`, `R`, `T`, and `Y`. Runs log to `WPnnnn.BLG`; the region index lands in
the power-share and trapezoid phase columns (`Y` uses power-share and drive-cycle), which is how
you tell the two combined runs apart in a decoded CSV.

**Note the key change:** `W` used to be the VESC watch. That moved to **`U`** ("UART watch").
Pressing `W` never starts anything by itself — it opens a parameter prompt you can cancel — so old
muscle memory can't launch a motor profile by accident.

**Watch out: the share extremes now open a bus switch** (this applies to `Y` as well as `W`). Regions 6 and 11 push the share all the
way to one source, and since the full-span change that no longer just clips the droop — the starved
channel is physically taken off the bus (its RT1987 switch opens while the motor is drawing). If
your bound `b` is below 0.15 the run will do this twice, and both profiles print a warning at start
saying so. Do the first such run scope-armed and at low current (`W 2 0.2`). Two things follow when
you read the log: while a channel is off the bus the share loop is open (no MDAC writes at all), so
the R6/R11 samples are topology events rather than controller response — don't fit a plant through
them. And if a run *finishes* with a channel still cut off, the firmware puts it back on the bus
automatically; if it can't (bus not in regulation) it says so, and `X`, `Q`, or the next `G` clears
it.

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
   `I_chg`, and `FLT` (fault flags). (Suppressed while the `L` plot stream is on.)
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
handling, the State 98 drive cycle, and the wheel-speed buffer reset. It also covers the SD-card
bench logger: lifecycle on every profile exit path (complete/stop/`X`/`Q`/fault), the 1 kHz
rate gate, ring-buffer overflow drop-and-count, no-card and mid-run write-error tolerance, file
naming/collision, the 52-byte record schema, and `K` status output. The `Y` and `W` combined profiles
(parameter parsing/clip/region walk/exit paths/`YP`+`WP` logging/suppression) are covered too. Run
before every flash.

`tools/decode_benchlog.py` has its own stdlib-only self-test, `tools/test_decode_benchlog.py`
(no pytest/g++ needed): it generates synthetic `.BLG` files and asserts on the decoder's actual
output — a wrap-straddling run decodes in full, a brownout tail is truncated at the true end,
`close_reason` 6 (`io_error`) decodes correctly, and gap statistics (`max_interval_us`,
`missed_periods`) come out right for a known gap. Run with:

```bash
python tools/test_decode_benchlog.py
```

## Notes for calibration

Items marked `TODO(calibrate)` / `TODO(verify)` in the source still need bench values, including:
- `SCALE_V_CHG` / `SCALE_V_RGN` dividers, and confirmation of the FC/BT/BUS dividers
- `motorConstant`, the PI gains (`Kp`, `Ki`), and `MOTOR_I_CMD_MAX` (anti-windup bound)
- the VBUS bring-up tunables: `V_BUS_CHARGED_THRESH`, `BUS_SETTLE_MS`, `BUS_CHARGE_TIMEOUT_MS`
- the regen-detection threshold and the State 99 cap-drain / regen-decay delays
- encoder counts-per-rev mapping to true vehicle speed
- AD5443 SPI timing/word-format verification against `references/Datasheets/ad5426_5432_5443.pdf`
