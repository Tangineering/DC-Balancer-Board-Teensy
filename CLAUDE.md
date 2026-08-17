# CLAUDE.md — Scale Car DC Balancer Board Firmware Reconciliation

## Purpose of this task

`teensy_controller.ino` is **stale firmware** written against an earlier board concept. The
PCB has since been redesigned, manufactured, and is now at revision **20260622**. Your job is
to bring the firmware into agreement with the **current hardware** as defined by the design
files, without changing the parts of the control logic (motor PI, power-share PI, encoder,
UDP protocol) that are still valid.

**Authoritative sources, in priority order:**
1. `Scale_Car_Teensy_IO__IO.csv` — the definitive Teensy 4.1 pin map. If the code disagrees
   with this file, **the CSV wins.**
2. `Scale_Car_Design_PCB_BOM_20260622.csv` — the definitive parts list (which ICs actually
   exist on the board).
3. `Scale_Car_DC_Balancer_Board_Schematic_20260622.pdf` — net connectivity and how the
   control pins drive the hardware.
4. `references/Datasheets/Ag105_Table3_Charge_Voltage_Select.json`,
   `references/Datasheets/Ag105_Table4_Charge_Current_Select.json`,
   `references/Datasheets/Ag105_Table5_Status_Output.json`,
   `references/Datasheets/Ag105_Table6_I2C_Status_Byte.json`,
   `references/Datasheets/Ag105_Table7_I2C_Parameters.json` — authoritative Ag105 register
   map, voltage/current selection tables, STAT pin behaviour, and I2C status byte (extracted
   from Ag105 DS V1.1, Tables 3–7).
5. Component datasheets in the project for remaining register maps / electrical limits.

Do **not** invent pin numbers, register addresses, or scale factors. If a value is unknown,
leave a clearly-marked `// TODO(calibrate)` rather than guessing.

---

## The core problem: the code targets a board that no longer exists

The firmware models a simple "FC boost + BT boost + one battery charger" system. The real
board is a **bidirectional power-pathing balancer** with ideal-diode source switches, a
regen braking path, and a different charger IC. Two whole categories of hardware are missing
from the firmware:

1. **The power-path / sequencing switches** (RT1987 ideal-diode controllers). The firmware
   never drives them. The board cannot route power without them, and mis-sequencing them can
   destroy the converters (a disabled TPS61288 back-feeds through its body diode during
   regen).
2. **The correct charger.** The code talks to a **`BQ25690` over I2C with a `REG_ICHG`
   current register**. There is no BQ25690 on the board. The charger is the **Silvertel
   Ag105 MPPT module**, which has a completely different I2C interface and is controlled
   mainly through an **MPPT-disable GPIO**, not a charge-current register.

Everything below is the reconciliation work.

---

## 1. Fix the pin map (highest priority — do this first)

Rebuild the `#define` pin block at the top of the file directly from
`Scale_Car_Teensy_IO__IO.csv`. Use the `Code Name` column verbatim as the macro name so the
firmware and the hardware doc share one vocabulary. Current correct mapping:

| Pin | Code Name | Dir | Function |
|----|-----------|-----|----------|
| 0  | `RX` | UART | VESC RX |
| 1  | `TX` | UART | VESC TX |
| ~~2~~ | — | — | *Free — was `ENC_A` before the 2026-08-16 bodge* |
| 3  | `FC_REG_ENABLE` | OUT | Fuel-cell boost regulator enable |
| 4  | `BT_REG_ENABLE` | OUT | Battery boost regulator enable |
| 5  | `MPPT_DISABLE` | OUT | **Ag105 MPPT disable** (was `CHARGER_ENABLE`) |
| 6  | `CHARGER_STAT` | IN | Ag105 STAT (was `CHARGER_OK`) |
| ~~7~~ | ~~`ENC_ENABLE`~~ | — | *Deleted 2026-08-16 — optical sensors hardwired to power; pin undriven* |
| ~~8~~ | — | — | *Free — was `ENC_B` before the 2026-08-16 bodge* |
| 9  | `CBAL_DISABLE` | OUT | **Cell-balancer (BQ29200) disable** — new |
| 11 | `MOSI` | SPI | MDAC |
| 12 | `MISO` | SPI | MDAC |
| 13 | `SCK` | SPI | MDAC |
| 14 | `ENC_A` | IN (INT) | **Encoder A** — bodged from pin 2, 2026-08-16 |
| 15 | `ENC_B` | IN (INT) | **Encoder B** — bodged from pin 8, 2026-08-16 |
| 18 | `SDA` | I2C | Ag105 charger |
| 19 | `SCL` | I2C | Ag105 charger |
| 24 | `FC_VOLTAGE` | AIN | Fuel-cell voltage |
| 25 | `BT_VOLTAGE` | AIN | Battery voltage |
| 26 | `BUS_VOLTAGE` | AIN | VBUS voltage |
| 27 | `FC_BUS_ENABLE` | OUT | **FC → VBUS ideal-diode switch** — new |
| 28 | `BT_BUS_ENABLE` | OUT | **BT → VBUS ideal-diode switch** — new |
| 29 | `MOT_PWR_ENABLE` | OUT | **VBUS → VESC/motor switch** — new |
| 30 | `REGEN_ENABLE` | OUT | **Regen → battery charger switch** — new |
| 31 | `FC_CHARGE_ENABLE` | OUT | **VBUS(FC) → charger switch** — new |
| 32 | `BT_SEQUENCE_ENABLE` | OUT | **Battery pack sequencing switch** — new |
| 36 | `CS_MDAC_FC` | SPI CS | FC droop MDAC |
| 37 | `CS_MDAC_BT` | SPI CS | BT droop MDAC |
| 38 | `CHG_VOLTAGE` | AIN | Charger input voltage — new |
| 39 | `RGN_VOLTAGE` | AIN | Regen-node voltage (was `CHRG_CURRENT`) |
| 40 | `FC_CURRENT` | AIN | FC current (INA253) |
| 41 | `BT_CURRENT` | AIN | BT current (INA253) |

**Renames / removals to apply everywhere in the file:**
- `CHARGER_ENABLE` (pin 5) → `MPPT_DISABLE` (and invert its *meaning* — see §3).
- `CHARGER_OK` (pin 6) → `CHARGER_STAT`.
- `CHRG_CURRENT` (pin 39) is **gone**; pin 39 is now `RGN_VOLTAGE` (an *input voltage*, not a
  current). Remove `I_charge = analogRead(CHRG_CURRENT)*SCALE_I;`. There is no charge-current
  ADC channel. However, the Ag105 **does** expose measured charge current over I2C (register
  `0x06`, scale 0.011 A/count — confirmed in `Ag105_Table7_I2C_Parameters.json`). Keep the
  `I_charge` float variable and populate it by polling register `0x06` at 50 Hz; do not drop
  it from telemetry. See §3 for the I2C read protocol (status byte always prepended).
- Add the six new digital outputs (27–32), two new analog inputs (38, 39), and
  `CBAL_DISABLE` (9).

When you change the telemetry/command struct layout, bump a protocol version constant and
note it so the Raspberry Pi bridge can be updated in lockstep.

---

## 2. Add the power-path sequencing state machine (new, safety-critical)

The new enable pins drive RT1987 ideal-diode controllers and must be sequenced. Encode these
rules from the IO CSV `Notes` column and the project design notes — **do not deviate**:

- **`BT_SEQUENCE_ENABLE` (32):** must **initialize OFF**. Turn ON once the system is powered
  and stable. It does **not** need to be turned off again afterward.
- **`FC_CHARGE_ENABLE` (31)** routes VBUS (fuel cell) into the charger. **`BT_BUS_ENABLE`
  (28) and `REGEN_ENABLE` (30) MUST be OFF before `FC_CHARGE_ENABLE` is turned ON.** Enforce
  this in code with a guard, not just by convention — assert the two are low, drive them low
  if not, then enable.
- **`FC_BUS_ENABLE` (27) / `BT_BUS_ENABLE` (28):** gate each source's contribution to VBUS.
  These replace the implicit "both regulators always on" assumption.
- **`MOT_PWR_ENABLE` (29):** gates VBUS → V-MOT/VESC. **SUPERSEDED (Death 5, 2026-07-08, see
  `docs/boost-bringup-debug.md`):** the original rule "OFF in Init/Idle/Error, only ON in Run" is no
  longer followed. Closing this at full bus onto the discharged 470µF+VESC node hot-plugs and kills a
  boost, so the node is instead **pre-charged during the low-voltage bring-up and kept energized
  through Idle/Run** (torn down only in State 99). The motor is held stopped in Idle by
  `vesc.setCurrent(0)`, not by cutting `MOT_PWR`. Turning it ON is gated by `assertMotPwrEnable()` /
  `motPwrHotPlugUnsafe()` so a discharged-node full-bus hot-plug can never happen (it faults
  `ERR_MOT_HOTPLUG` instead). **Trade-off:** the VESC is powered in Idle (lost hardware motor
  isolation) — acceptable because the alternative destroys boosts.
- **`REGEN_ENABLE` (30):** gates regen energy to the charger. Mutually exclusive with
  `FC_CHARGE_ENABLE` (see above).

**Critical hazard to respect (from the design history):** a *disabled* TPS61288 boost has a
body-diode passthrough. A VESC regen event can back-feed through a disabled converter's
synchronous rectifier and destroy it. So enable/disable ordering of the boosts vs. the
bus/regen switches matters — when entering a state, bring switches up/down in an order that
never leaves a regen path pointed into a disabled boost. Add explicit comments at each
`digitalWrite` explaining the ordering rationale.

Define safe default pin states in `setup()`:
- All `*_BUS_ENABLE`, `MOT_PWR_ENABLE`, `REGEN_ENABLE`, `FC_CHARGE_ENABLE`,
  `BT_SEQUENCE_ENABLE` → **OFF (LOW)** at boot.
- `MPPT_DISABLE` and `CBAL_DISABLE` → choose the **fail-safe** level (see §3, §4).

Note: the hardware also adds 10 kΩ EN-to-GND bodge resistors so every switch defaults low if
the Teensy GPIO is high-Z during MCU reset/boot. Firmware should still drive deterministic
levels early in `setup()` and not rely on the resistors alone.

Fold these into the existing state machine:
- **State 0 (Init):** enable FC/BT boosts, bring up `BT_SEQUENCE_ENABLE`, init MDAC, init
  VESC. Leave motor/regen/charge paths OFF. **Ag105 charger config is NOT done here** — the
  charger is unpowered in Init (no charger power path is open), so it cannot ACK I2C. Config
  is deferred to `pollAg105()`, which lazily configures it once it is powered + settled (§3).
- **State 1 (Idle):** motor current 0, `MOT_PWR_ENABLE` OFF.
- **State 2 (Run):** `MOT_PWR_ENABLE` ON; run motor/power-balance/charging. Manage
  `REGEN_ENABLE` vs `FC_CHARGE_ENABLE` mutual exclusion here.
- **State 3 (Finish):** motor 0, disable charging/regen/motor paths, back to Idle.
- **State 99 (Error):** all path switches OFF in safe order; boosts may stay on or off per
  the back-feed rule. Stay latched.

---

## 3. Replace the BQ25690 charger code with Ag105 (Silvertel)

This is the biggest logic change. The firmware's entire `setChargerTargetCurrentA()` /
`REG_ICHG` / `CHARGER_ADDR 0x6A` path is for a part **not on the board**. Remove it.

The board uses the **Silvertel Ag105** MPPT battery-charger module. Reconcile against
`AG105_Silvertel.pdf` and the BOM (`CHG`). Key behavioral facts that change the firmware:

- **Control is via the `MPPT_DISABLE` GPIO (pin 5), not a current register.** Strategy:
  assert `MPPT_DISABLE` **active during active braking/regen** (so the slow perturb-and-
  observe MPPT loop doesn't fight the fast regen transient) and **release it during
  cruise/coast** so the Ag105 harvests. Implement this in `chargingControl()`. **Confirmed
  from PCB schematic: `MPPT_DISABLE` is active-LOW — pulling LOW inhibits the MPPT
  perturb-and-observe loop; pulling HIGH releases it.** **FC-path bootstrap:** in cruise with
  `charge_goal > 0`, `chargingControl()` opens `FC_CHARGE_ENABLE` on *intent* (not on
  readiness) to power and boot the charger — gating the path on `ag105IsReady()` would
  deadlock, since the charger can't become ready until it is powered. Only the MPPT *release*
  (`MPPT_DISABLE` HIGH) is gated on `ag105IsReady()`.
- **The Ag105 is slow.** It is the *secondary* harvester. The TL431/BSP170P braking chopper
  is the *primary* fast clamp and is **not** under firmware control. Do not write code that
  assumes the charger absorbs regen spikes.
- **I2C config is power-gated and lazy — NOT done in State 0.** When no external resistors
  are fitted the Ag105 defaults to **4.2 V / 1000 mA** (external-resistor-mode register value
  0x00 with no RVS/RCS resistors — confirmed in `Ag105_Table3_Charge_Voltage_Select.json` and
  `Ag105_Table4_Charge_Current_Select.json`), so firmware must write **reg 0x01 = 0x08**
  (2S / 8.4 V) and **reg 0x00 = 0x01** (2500 mA) or the pack is undercharged. **Critical
  hardware constraint:** the Ag105 only receives input power when a charger power path is
  routed to it — `FC_CHARGE_ENABLE` HIGH, or `REGEN_ENABLE`+`MOT_PWR_ENABLE` both HIGH
  (`chargerHasPower()`). In Init/Idle all are LOW, so the charger is **unpowered and cannot
  ACK I2C** — configuring it in State 0 can never succeed and must never fault. Instead,
  `pollAg105()` configures it **lazily**: the first time `chargerHasPower()` is true and the
  `AG105_SETTLE_MS` bring-up window has elapsed and the charger ACKs, it writes the two
  registers and sets `ag105Configured`. The flag re-arms on power loss; EPROM persistence
  makes the re-write idempotent. I2C address is `0x30`. The Ag105 is self-powered at 3.3 V
  internally and is logic-compatible with the Teensy.
- **Charge-current strategy:** the dominant harvest lever is running the Ag105 up to its
  **2.5 A max** rather than the default (0x00 = external resistor mode). This IS configurable:
  write `0x01` to register `0x00` at init to select the 2.5 A profile. Charge current is also
  **readable** at any time from register `0x06` (scale: 0.011 A/count), so `I_charge` can be
  kept in telemetry by polling this register at 50 Hz rather than being dropped entirely.
- **`CHARGER_STAT` (pin 6)** replaces `CHARGER_OK`. Polarity is confirmed from
  `Ag105_Table5_Status_Output.json`: steady **HIGH = Charging**, steady **LOW = Input Voltage
  Removed**, 50% duty 2 s period = Fully Charged, pulse trains = error states. A single
  `digitalRead()` cannot distinguish charging from an error-state pulse-high, so use the
  I2C GENSTAT field (Table 6) as the primary `chargerReady` source. CHARGER_STAT steady-LOW
  is useful as a fast "no input power" hardware guard.

Replace `maxChargeCurrentA`, `REG_ICHG`, `CHARGER_ADDR`, and `setChargerTargetCurrentA()`
with Ag105 equivalents. Keep `charge_goal` from the Pi as the high-level intent, but map it
onto the Ag105's actual capabilities (enable/disable + configured current ceiling), not a
fictional per-mA register.

---

## 4. Add cell-balancer (BQ29200) handling

New pin `CBAL_DISABLE` (9) controls the **BQ29200** cell OVP/balancer. Per the design:
- The BQ29200 is used for **OVP-only**; `CB_EN` is hardwired to GND in hardware.
- `CBAL_DISABLE` is a **real Teensy-driven control** (it is *not* grounded and does *not*
  conflict with the hardwired `CB_EN`).
- **Confirmed polarity (PCB schematic):** LOW = balancer/OVP active; HIGH = disabled.
  No external pull resistor on the CB-DISABLE net — wire goes directly to Teensy GPIO.
  Enable `INPUT_PULLUP` before switching to `OUTPUT` so the pin defaults HIGH (balancer
  disabled = safe) during any MCU reset/high-Z window; then drive LOW in `setup()`.
- There is no balancer current register to program — this is a single digital control line.

The balancer's `BAL-NOK` fault output is **intentionally unused** (terminates at an orphan
label). Do **not** add code expecting a BAL-NOK input — there is no pin for it.

---

## 5. Fix the analog scaling and current sense

- **Current sense is the INA253A1IPWR** (BOM line 14). The board was intended to use the A3
  variant (400 mV/A = 0.4 V/A), but the A1 was ordered by mistake (100 mV/A = 0.1 V/A). The
  board is already manufactured, so **`K_sns = 0.1 V/A`** is the correct value for the fitted
  parts. If the board is re-spun with INA253A3IPWR, update `K_sns` to `0.4 V/A`. Source:
  INA253A1IPWR.pdf Device Comparison Table. **These INA253s run in unipolar,
  0-referenced mode** (REF1 and REF2 both tied to GND), so zero current ≈ 0 V output and the
  existing `amps = adc_volts / gain` form is correct. They sense **only the forward
  current of each boost regulator** (FC and BT); regen and charging currents flow through a
  **separate power path** and are never seen by these sensors, so there is no negative
  current to account for here. Their purpose is twofold: they set the droop for each boost
  regulator in hardware, and their analog output is read by the Teensy so firmware knows each
  regulator's current draw and can adjust the droop gains to hit the commanded FC/BT current
  share.
- **Teensy 4.1 ADC is not 10-bit by default.** The code uses `ADC_MAX = 1023.0`. Decide the
  `analogReadResolution()` explicitly (e.g. 12-bit → 4095) and make `ADC_MAX` match. Don't
  leave the resolution implicit.
- `SCALE_V_FC` / `SCALE_V_BATT` / `SCALE_V_BUS` are placeholder dividers. Recompute each from
  the actual divider resistors on the schematic (`Vmax = Vref*(R1+R2)/R2`). Mark any you
  can't resolve as `// TODO(calibrate)`.
- Add scaling for the two new analog inputs: `CHG_VOLTAGE` (38) and `RGN_VOLTAGE` (39), again
  from their schematic dividers.

---

## 6. Update faults, telemetry, and commands

- **Faults:** the regen/back-feed and sequencing hazards are now the dangerous failure
  modes. Keep existing OC/UV/OV checks but re-derive limits against the board: VBUS nominal
  is **16.0 V** (`V_BUS_NOMINAL = 16.0f`; measured no-load regulation 15.9 V — the RD1 = 215k
  FB retune, 2026-07-11; the pre-retune 17.5 V figure is STALE); `LIMIT_V_BUS_MAX` derives as
  `V_BUS_NOMINAL + 1.5f` = 17.5 V (TPS61288 HW OVP triggers at 19V — confirmed).
  Battery is **2S**; verify
  `LIMIT_V_BATT_MIN`. Consider adding a fault for an illegal switch combination (e.g.
  `FC_CHARGE_ENABLE` high while `REGEN_ENABLE`/`BT_BUS_ENABLE` high).
- **Telemetry struct:** it currently sends `I_charge` (no longer measured) and omits the new
  rails (`CHG_VOLTAGE`, `RGN_VOLTAGE`) and the new switch states. Decide what the Pi needs,
  update the packet accordingly, **recompute the byte count and checksum span**, and
  bump the protocol version. Don't silently change the layout — the Pi bridge parses fixed
  offsets. *(Implemented: protocol **v4**, **58 bytes**, checksum over bytes 1–56. The packet
  carries `charger_status` (raw Ag105 Table 6 status byte at offset 51 — Pi decodes
  off/CC/CV/fault), `switch_state`, a 16-bit `fault_flags`, and the latched `error_code`/
  `error_source_state`. Full layout in PLAN.md §6b.)*
- **Commands:** the 22-byte command packet still works, but `droop_enable` is parsed and
  discarded. Either wire it up or note explicitly that it's reserved. If the Pi needs to
  command the new power paths/modes, that's a protocol extension — flag it rather than
  hand-wave it.

---

## 7. MDAC / droop — mostly keep, verify the part

The dual-MDAC droop output (SPI, `CS_MDAC_FC` / `CS_MDAC_BT`) is still valid. The part is the
**AD5443** (12-bit multiplying DAC). Verify against its datasheet:
- SPI mode, bit order, and word width (the code uses `SPI_MODE0`, MSB-first, `transfer16`).
- That `MDAC_res = 4095` (12-bit) is correct for the AD5443.
- The op-amp on the MDAC output is the **OPA197** (now powered from the 5 V rail per the
  hardware bodge — this doesn't change firmware, but the output ceiling is set by 5 V, so the
  droop-code mapping must not assume a 3.3 V output swing).

Leave the droop math (`k_eq`, `A_v`, `K_sns` chain in `powerBalance()`) structurally intact.
`K_sns = 0.1 V/A` is the correct value for the INA253A1 parts fitted on this board (see §5
for the variant mixup). If the board is re-spun with INA253A3, update `K_sns` to `0.4 V/A`.

---

## 8. Testing State (State 98)

Add a hardware exerciser state reachable from State 1 via USB Serial character `T`. Key
requirements:

- **Pi watchdog suspended:** reset `lastPiMsg = millis()` at entry and exit of `doState98()`
  so the watchdog timeout never fires while in test mode.
- **`detectFaults()` still runs** every main-loop tick; a fault trips State 99 as normal.
- **Individual control:** USB Serial commands toggle `FC_REG_ENABLE`, `BT_REG_ENABLE`, and
  each of the 6 RT1987 ideal-diode switches. `FC_CHARGE_ENABLE` **must** go through
  `assertFcChargeEnable()` — the safety guard is never bypassed, even in test mode.
- **Simulated drive cycle** (`D` command): pre-programmed `v_setpoint` profile (standstill →
  ramp-up → cruise → coast-down → regen hold → standstill). `motorControl()`,
  `powerBalance()`, and `chargingControl()` execute unmodified; the drive cycle only supplies
  `v_setpoint`. Requires `MOT_PWR_ENABLE` to be HIGH before starting.
- **Combined drive-cycle + power-share profile** (`Y [Vmax] [b]`, 2026-08-10): a 16-region, 40 s
  table that sweeps `v_setpoint` (normalised × an operator `Vmax`) and `power_share_setpoint`
  (absolute, clipped to `[b, 1−b]` *after* interpolation) together, so the two loops' cross-coupling
  is exercised in one run; same prerequisites and control-call set as `D`, logged to `YPnnnn.BLG`
  with the region index in both phase bytes (PLAN.md §9h).
- **Combined current + power-share profile** (`W [Imax] [b]`, 2026-08-10): the same 16-region table
  with the motor axis reinterpreted as commanded current (both profiles share one
  `advanceComboRegion()` walk, so their shapes cannot diverge), using `T`'s motor conventions — no
  velocity-chain calibration, `MOT_PWR_ENABLE` warn-only — so the share loop can be exercised on an
  encoder-less bench; logged to `WPnnnn.BLG` (PLAN.md §9i). **The VESC watch moved from `W` to `U`.**
- **Status dump** (`S` command): print all pin states and ADC readings to USB Serial.
- **SD-card bench logging:** `R`/`T`/`D`/`Y`/`W` runs are auto-logged at 1 kHz to the built-in micro-SD;
  the `K` command prints logging status. Logging is observability-only — it never faults the
  board, and the sampling path does no card I/O. Card I/O is confined to logDrainTick() in
  loop(), which skips a tick when the card reports busy and writes at most one 512 B chunk;
  SdFat's write()/truncate()/close() are themselves synchronous, so the close is held off until
  State 99 has reached its latched phase (state99Phase == 3) and can never lengthen a teardown
  dwell.
- **Exit** (`Q` command): → State 1; `MOT_PWR_ENABLE` forced LOW on exit.

See PLAN.md §9 for the full command set and drive cycle phase table.

---

## 9. Unit tests

A host-native test suite lives in `test/` and can be compiled and run with `make` on any
machine with `g++` — no Teensy or Arduino IDE required.

- **Mock layer:** `mock_arduino.h`, `mock_wire.h`, `mock_spi.h`, `mock_vesc.h`, `mock_sd.h`
  stub out all Teensy-specific APIs. Wire mock includes an injectable byte queue for scripted
  I2C responses; SPI mock captures written words for assertion; the SD mock captures each
  file's written bytes in memory and can inject open/write failures and busy-tick stalls.
- **Coverage targets:** scale factor math, fault detection, PI controller convergence,
  command packet parsing, telemetry packing (58-byte v4 layout + checksum), Ag105 init
  I2C sequence, `pollAg105()` byte decoding, `assertFcChargeEnable()` ordering, drive
  cycle phase transitions, and `MPPT_DISABLE` polarity in `chargingControl()`. The review-round
  additions (PLAN.md §11) added coverage for GENSTAT decode, UV boot-gating, PI anti-windup,
  `doState0()` init-fault handling, `pollAg105()` state gating, and the wheel-speed reset. The
  audit-round additions (PLAN.md §14) cover the live-output PI semantics, power-PI anti-windup,
  gated-tick droop stability, the `ag105DataValid` staleness gate, and the State-98 `'2'` guard
  and `'Q'` path-closing exit. The State-98 trapezoidal current profile (PLAN.md §9f) is covered
  too: the single-line `"T <Imax> <hold> <rate>"` entry through ramp-up/hold/ramp-down and
  natural completion, start with `MOT_PWR_ENABLE` LOW (warn-only, no gate), the `±TRAP_I_ABS_MAX`
  clamp (both signs) with peaks above `MOTOR_I_CMD_MAX` accepted and actually reaching the VESC,
  negative-peak braking/regen entry, degenerate-line rejection (zero peak, negative hold,
  non-positive rate, incomplete line, bare `T`+newline), non-numeric mid-line cancellation, the
  `'T'`-stop and `'Q'`-exit paths (motor zeroed, path switches deliberately left as-is on
  `'T'`-stop), mutual exclusion with the drive cycle and power-share profile, `'X'` universal
  stop across all three profiles, and `pollVescWatch()` suppression. The Serial-Plotter stream
  (`'L'`, PLAN.md §9) is covered too: the six-field wire format and rate gate (asserted against
  the mock Serial's captured TX), status-line suppression/restore, the `'R'`/`'T'` arm-fire-cancel
  paths under plot mode, and the fire-time precondition re-check. SD logging coverage: lifecycle
  on every exit path incl. fault, ring-buffer overflow drop-count, no-card tolerance, record
  schema, and the `'K'` status command. The `'Y'` combined drive-cycle + power-share profile
  (PLAN.md §9h) is covered too: parameter parsing/clip/region walk/exit paths/`YP` logging/
  suppression — as is the `'W'` current-mode twin (PLAN.md §9i): shared-helper equivalence, `Imax`
  scaling, the `TRAP_I_ABS_MAX` ceiling, `WP` logging, and the `'W'`->`'U'` watch rebinding.
- Run before every flash: `cd test && make`.

See PLAN.md §10 for the full directory layout and test category table.

---

## What NOT to change

- The motor PI controller, power-share PI controller, and their `sampleTime` gating. *(Two
  behaviour-preserving exceptions were made in the review round, PLAN.md §11: the integrator
  state was hoisted to file scope for test resettability, and a clamp-based anti-windup bound
  was added to the motor PI. Two more user-approved exceptions in the audit round, PLAN.md §14:
  the power-share PI gained the same anti-windup clamp, and both PIs now always return a live
  output — the `sampleTime` gate applies to the integrator update only (the old 0.0f sentinel
  chopped the motor command / slammed the droop split on sub-sampleTime ticks). The gains are
  unchanged.)*
- The quadrature encoder ISRs and `updateWheelSpeed()`. *(A guarded buffer-reset hook was added
  to `updateWheelSpeed()` in §11; the velocity math is unchanged.)*
- The UDP framing approach (sync byte + XOR checksum), except for the struct-layout/length
  updates forced by the telemetry changes.
- The high-level 5-state machine *structure* (just add the new hardware sequencing inside it).

---

## Working method

1. Start with the pin map (§1) — it touches every other section.
2. Add the power-path switches and sequencing guards (§2) before charger work, since the
   sequencing rules constrain the charger path.
3. Replace the charger (§3), add the balancer (§4).
4. Fix analog/current (§5).
5. Reconcile faults/telemetry/commands (§6) and verify the MDAC part (§7).
6. For every register address, scale factor, or electrical limit, cite the datasheet/CSV you
   pulled it from in a comment. Where you cannot find a value, insert `// TODO(calibrate)` or
   `// TODO(verify: <file>)` rather than guessing.
7. Compile-check mentally for the renames — `CHARGER_ENABLE`, `CHARGER_OK`, `CHRG_CURRENT`,
   `REG_ICHG`, `CHARGER_ADDR`, `maxChargeCurrentA`, and `setChargerTargetCurrentA` all
   disappear or change; make sure no stale reference remains.

When done, produce a short changelog at the top of the `.ino` summarizing what moved from the
old board model to the 20260622 board, so the next reader sees the hardware delta at a glance.

---

## Standard practice: post-implementation self-review

**After completing any feature or change to the firmware, perform a self-review before
considering the work done — do not wait to be asked.** Treat this as a required final step of
every implementation task, the same way the test suite is.

1. **Re-read the diff** you just wrote, looking specifically for:
   - **Correctness bugs** — off-by-one, inverted polarity, wrong register/scale, missing
     `vesc.setCurrent(0)` flushes, stale references after a rename.
   - **Architectural issues** — asymmetric paths (e.g. a stop path that cleans up state but a
     natural-completion path that doesn't), state that isn't reset on exit/fault, switch-sequencing
     or back-feed hazards (§2), blocking calls that stall `detectFaults()`.
   - **Safety** — any new code path that could leave the motor running, a boost back-fed, a switch
     combination illegal, or the bus hot-plugged (see the bench-bring-up addenda).
2. **Report findings** to the user grouped by severity (correctness/safety first, then
   architecture, then doc/polish), each with a concrete recommended fix — even the minor ones.
3. **Apply the fixes** (with the user's go-ahead), and for every behavioural fix add or extend a
   host-native test that would have caught it.
4. **Re-run both builds** (`-DBENCH_TEST=0` and `=1`) and confirm all tests pass before closing out.

This was added after a feature round where the review caught a real asymmetry (a profile's natural
completion left the motor running while its stop path zeroed it) plus several minor issues — none
of which the happy-path tests flagged. The review is cheap and catches exactly this class of bug.

---

## Archived session history (2026-06-23 through fw v7, 2026-08-13)

The superseded status addenda from that period — early bring-up, the boost-death
investigations, the share-controller design round, fw v2–v7 — were moved verbatim to
`docs/claude-md-archive.md` to keep this file under the memory-size limit. Every fact
still current is restated in the addenda below or in `docs/firmware-versions.md` and
PLAN.md. Read the archive before revisiting bring-up failures or pre-v8 design history.

### Hardware bodge record (2026-07-10): BT compensator R_C 27.4k → 61.2k

`RC-BT` (TPS61288 COMP network, battery boost) was changed post-manufacturing from the
schematic's 27.4 kΩ to **61.2 kΩ to match the FC channel** — the schematic (2026-06-22) still
shows 27.4 k. Effect: both boost voltage loops now cross at ~4–19 kHz (symmetric lags, the
assumption behind the shared τ_r in the share-loop plant; analysis in
`controller_design/system_model.md` §6e, from TPS61288 DS §9.2.2.5). Margins (with the
2026-07-10 system decision to keep the battery at **7.4–8.4 V**): the DS f_c ≤ f_RHPZ/5
guideline holds for BT per-channel currents up to 4.0 A at worst-case cap derating (5.3 A
counting the bodge caps) — ≥ 30 % margin over the vehicle's ≤ ~3 A/channel; the deep-discharge
caution is retired by the operating floor (confirmation ringing check: bench manual CAL-3
step 5 at 7.4 V). Enforce the floor eventually via LIMIT_V_BATT_MIN. Any future BT boost
rework must keep this resistor value (or revert knowingly).


## Status & session addendum (2026-08-16, fw v8: encoder pin move, observability, slot count)

A bench report — `v_actual` pinned at 0.000 in the `'L'` stream while the encoder was visibly
producing a signal — turned out to be an unreconciled hardware bodge, and exposed a diagnosis dead
end and a scale error on the way there. **fw v8 (pending first flash);** ledger row in
`docs/firmware-versions.md` has full detail.

- **ROOT CAUSE — the encoder pins had moved and the firmware had not.** Bodge work relocated
  `ENC_A` 2 → **14** and `ENC_B` 8 → **15**, and hardwired the optical sensors to power, deleting
  the `ENC_ENABLE` net (pin 7). The firmware was attaching `CHANGE` interrupts to two pins the
  encoder was no longer wired to, so no ISR ever fired, `encoderPos` never moved, and `v_actual`
  read exactly 0.000. `ENC_ENABLE` is removed entirely — pin 7 is now **undriven** (no `pinMode`,
  no `digitalWrite` anywhere), and pins 2/8 are free. Teensy 4.1 pins 14/15 are A0/A1 and
  Serial3 TX/RX; neither alternate function is used here and both are interrupt-capable, so the
  ISR path is otherwise unchanged. The IO CSV was updated by the operator in lockstep (pin 7 row
  marked "No longer in use"), so the CSV remains the authority and the firmware follows it
  row-for-row. **Side effect worth knowing:** with the sensors hardwired, the encoder is live from
  power-on rather than from the State-0 `initControlPeripherals()` enable write — counts now
  appear before the bus is brought up.

- **The velocity chain had exactly ONE observable**, which is why the pin move above took a bench session to find rather than a `'S'` dump. `updateWheelSpeed()` is correct, so
  `v_actual == 0.000` can only mean `encoderPos` is not moving — but nothing printed `encoderPos`
  anywhere (not the State-98 `'S'` dump, not `printSensors()`, not telemetry). The ×2 decoder in
  `doEncoderA()`/`doEncoderB()` counts only when **both** channels transition in the right ORDER,
  so three distinct hardware faults collapse to an identical silent zero: a dead channel; a
  phototransistor swing that never crosses the Teensy's V_IL/V_IH (the OPB829DZ is a bare
  phototransistor with a pull-up (4.7 kΩ as designed; **bodged to 2.2 kΩ**, operator 2026-08-16)
  — no Schmitt, so "a signal on the scope" is compatible with
  zero interrupts); and two beams not 90° apart. Added `encEdgeCountA`/`encEdgeCountB` (volatile
  u32, bumped at the top of each ISR, read by nothing but the dumps), an `--- Encoder ---` block in
  the `'S'` dump, and the same line in the IDLE `printSensors()` dump. Diagnostic-only — no control
  path reads them.
- **`ENCODER_SLOTS_PER_REV` 60 → 120** (`ENCODER_COUNTS_PER_REV` 120 → **240**). The disc was
  counted directly: it physically carries 120 slots. fw v7's 60 was a **transcription error, not a
  competing measurement** — the 2026-08-13 figure of "120" was recorded as 120 `encoderPos` *counts*
  per hand-turned revolution and divided by the ×2 decode, when it was 120 *slots* and the decode
  multiplies. The observability gap above is the tell: no build through fw v7 could have read a
  count. **`v_actual` and BLG `v_act` HALVE** for identical motion vs fw v7 (fw 7 and fw 8 traces
  are not comparable; header `fwVersion` disambiguates). Chain vs fw ≤ 6: ×9.85.
  `VELOCITY_CHAIN_CALIBRATED` stays 1 — a direct slot count is a stronger source than the figure it
  replaces. (The `FLYWHEEL_RADIUS_M` disc-coupling `TODO(verify)` was untouched by the slot count — it was closed separately, below.)
- **CONFIRMED ON HARDWARE (2026-08-16, fw v8): one hand-turned flywheel revolution reads
  `encoderPos == 240`.** First time the counter has ever been read on this board. Two
  independent sources now agree (physical slot count, firmware counter), and the same reading
  independently confirms the ×2 decode factor, that both channels are alive and in quadrature,
  and that the pins-14/15 bodge is correctly reconciled. That settles the chain's *angular* half.
- **COUPLING RESOLVED (2026-08-16, operator) — surface/roller; the linear half is settled too, so
  the velocity SCALE chain is now complete.** The encoder is coupled to the flywheel and the
  **flywheel's own radius IS the rolling radius**, so the disc rim runs at surface speed and
  `FLYWHEEL_RADIUS_M = 0.0762` is correct as shipped. The wheel-*angular*-speed alternative — which
  would have forced the tire radius and made `v_actual` over-read by 2.31× — is retired, closing the
  fw v7 S3 residual. **No constant changes; this is a determination, not a measurement.**
  **Carry forward:** `v_actual` is flywheel **surface speed**, and `v_setpoint`, the State-98
  `'V'`/`'D'`/`'Y'` commands and the BLG `v_sp`/`v_act` columns are all in those same terms. There is
  no separate vehicle-speed scale in the firmware, and the 6.86:1 reduction (9.49 retired
  2026-08-16c, fw v14 K_F correction) and differentials do not
  enter the velocity loop — it closes on the encoded body, which is the flywheel.
- **The decoder had zero test coverage** — every prior test wrote `encoderPos` by hand. 11 new
  checks drive `doEncoderA`/`doEncoderB` from raw pin levels: forward/reverse ±2 per cycle, each of
  the three silent-zero failure modes asserted to yield zero counts *and* to stay diagnosable
  through the edge counters, and an ISR-driven end-to-end path to a non-zero `v_actual`. Both slot
  and count constants are pinned literally, because 120-slot/240-count and 60-slot/120-count both
  satisfy the "counts == slots × decode" identity. **Tests: 1663 production + 175 bench pass.**
- **Next bench:** the velocity SCALE chain is complete — counts/rev, decode factor, radius and
  coupling are all settled and the decoder is hardware-confirmed. Two items remain before a velocity
  run, both unrelated to scale: set the VESC Battery Current Max / Regen Max (§4, still open from
  fw v7), and calibrate `motorConstant` + the motor PI gains — which have never been tuned against a
  working `v_actual` at all, since none of the builds that could have tuned them were reading the
  encoder. Treat the first `'V'` run as gain identification from scratch, scope-armed, and prefer
  `'A'`/`'T'` (velocity-PI-free) first. **Drive-direction consequence — read before any `'V'`/`'D'` run:**
  fw v7 OVER-read `v_actual` by 2×, which shrank the velocity error and made the PI UNDER-drive.
  Correcting it restores the true error, so **fw v8 commands up to 2× the current fw v7 would have
  at the same `v_setpoint`** — the correction is toward truth, but the change on the bench is in
  the more aggressive direction, into the still-open fw v7 precondition (VESC Battery Current
  Max / Regen Max unset, §4; OC faults compiled out under `BENCH_TEST`; `MOTOR_I_CMD_MAX` 12 A).
  `motorConstant` and the motor PI gains remain uncalibrated against any scale, so treat the first
  `'V'`/`'D'` run as gain validation, scope-armed, and prefer `'A'`/`'T'` (velocity-PI-free) first.

### Hardware bodge record (2026-08-16): encoder rerouted to pins 14/15, ENC_ENABLE deleted

Post-manufacturing rework, recorded here alongside the RC-BT compensator bodge because it is the
same class of change — the board no longer matches the 2026-06-22 schematic and any future rework
must preserve it or revert it knowingly.

- `ENC_A` moved from Teensy **pin 2 → pin 14**; `ENC_B` from **pin 8 → pin 15**.
- The two OPB829DZ optical sensors are **hardwired to power**. The `ENC_ENABLE` net (pin 7) no
  longer exists; pin 7 is left **undriven** by firmware. Consequence: the encoder is live from
  power-on, not from State 0.
- `references/Scale Car Teensy IO - IO.csv` was amended in lockstep (rows moved to 14/15; the pin 7
  row is kept and marked "No longer in use"). **The CSV remains authoritative** — this bodge does
  not create a firmware/CSV divergence, unlike a bodge left unrecorded.
- Firmware tests pin `ENC_A == 14` / `ENC_B == 15` literally and assert `ENC_ENABLE` is undefined.
  That assertion is load-bearing: the rest of the suite drives the ISRs through the same macros, so
  a wrong pin number is self-consistent everywhere else and no other test would fail.
- Any board re-spin that restores the original routing must revert firmware, CSV, and those tests
  together.

---

## Status & session addendum (2026-08-16, fw v9: 'K' manual SD logging)

**fw v9 (pending first flash):** the State-98 `'K'` command became a single-line command
(`PEND_K_PARAMS`, same convention as `T`/`Y`/`W`) so the operator can log hand-driven runs:
empty line = the old status print; **`K 1`** opens a MANUAL log (`LOG_TYPE_MANUAL` 0x08, new
`ML####.BLG` prefix in the shared session counter, v4 header param flags 0 — no record/trailer
format change, no UDP change); **`K 0`** closes it via `logRequestClose(LOG_CLOSE_STOP)`.
Ownership is tracked by `logManualActive` (set only on a successful open; cleared in
`logFinishFile()` and `logDrainTick()`'s no-card clear). `K 1` is refused during the staged
bring-up (parse-time guard — the open path's directory scan + 32 MB preAllocate must not stall
the bring-up machine; the status form stays out of the keypress lockout), while any profile,
**`T` sweep**, or plot-arm is pending, and while a log is open/closing; `K 0` is refused on a
profile-owned log. `X`/`Q`/fault close a manual log through the normal drain; a profile start
over a live manual log force-finishes it (existing double-open branch). `logSampleTick()` is
unchanged — manual runs sample at 1 kHz with phase bytes `LOG_PHASE_NONE`.

Orchestrated round (Opus implementer, independent Sonnet test-writer, parallel Opus safety +
Sonnet correctness reviews). Safety S1 (MED): the `K 1` guard originally missed `tsweepActive` —
an ML open in a sweep's between-runs window would have silently cost the next sweep run its log
(the exact loss the sweep's WAIT_LOG gate exists to prevent); fixed with the sweep term.
Safety S2 / implementer-flagged: `printSdStatus()` now prints a "(manual — K 0 stops)" /
"(profile-owned)" ownership marker while a log runs. Correctness review: no logic bugs; three
coverage gaps closed (drain-window `K 1`, double `K 0`, plot-mode prompt). Decoder impact:
docstring-only (`profile_type` bit 3 = MANUAL; the tooling passes the bitmask through raw).
**Tests: 1777 production + 175 bench pass.** Ledger row in `docs/firmware-versions.md`;
command/table docs in PLAN.md §9 updated.

---

## Status & session addendum (2026-08-16, fw v10: Youla-H drive controller)

The drive-channel calibration campaign closed (motor ID, m_eff, b_eff three-way triangulated at
0.32 N·s/m, thermal Coulomb F_c = 1.2 ± 0.25 N, τ_v measured 1.0 ms, Td_v decided 2 ms — record:
`controller_design_MIMO/calibration/motor_id_20260815.md`) and two orchestrated rounds followed.
**fw v10 (pending first flash);** ledger row in `docs/firmware-versions.md` has full detail.

- **Round A — model + re-synthesis.** `plant_mimo.py` carries the measured constants (k_t
  4.266e-3, R_m 22.6 mΩ, m_eff 3.5 kg, r_t 0.0762 m flywheel rolling radius, b_eff 0.32 with
  `pole_factor ∈ {0.5, 3}`, F_c 1.2 N; the aero/C_rr/b_motor composite is RETIRED). Nominal
  plant: G22(0) = 1.411 (m/s)/A, pole −0.0914 rad/s, model-derived i_m0 = 4.07 A (0.6 % below
  the measured band's lower edge — a factor-of-4 correction attributed to the unmeasured η_dt,
  not closure). `synthesize_drive_siso.py` re-ran at **I_CLAMP = 12.0** (the fw MOTOR_I_CMD_MAX):
  chosen rung WC=55/Wu(0.15,300,7.5) → PM 49.6°, DM 54.2 ms, crossover 16.0 rad/s, worst-corner
  ‖S‖∞ 2.15 cont / 2.26 disc, all 24 corners stable, 22/22 gates. Replay reference vectors
  (`figures/drive_siso_replay.csv`) are generated from the FLOAT32-ROUNDED header coefficients at
  %.17e (review V1: double-generated vectors drift 1.7e-2 A through the near-unity mode);
  independent validator `validate_drive_siso.py` passes 15/16 — the one "failure" is the
  documented measurement that a float32 STATE recursion diverges ~1.4e-2 A (why the firmware
  state is double). **The MIMO-study artifacts are frozen on the retired plant and their pipeline
  currently fails its own gates** (compare_controllers clamp assert, synthesize_mimo 54/2,
  compute_Su DRIFT, mimo_crosscheck.m false-green) — bannered in the README/model doc/`.m`;
  regeneration is a future synthesis round, not a re-run.
- **Round B — firmware.** New `teensy_controller/drive_controller.h`: Hanus self-conditioned
  5-state realization (clamped u drives the state update — full-state anti-windup; integrator-only
  back-calculation measurably fails here, R's LF gain is 745.5 A/(m/s)), **double state vector**,
  float coefficients GENERATED into `teensy_controller/drive_controller_coeffs.h` by
  `synthesize_drive_siso.py` (one emitter, two copies with the study header — never hand-edit).
  `motorControl()` under `USE_YOULA_DRIVE_CONTROLLER` (default 1; PI verbatim at 0) sends the
  controller's AMPS straight through `commandMotorCurrent()` — no motorConstant division on this
  path (motorConstant is dead on the shipped build). Wrapper `youlaController_Drive()` gates the
  recursion to DRIVE_CTRL_TS_US − 200 µs (beat tolerance vs the equal-period rl_motor gate) and
  holds output between ticks. `resetDriveControlState()` at Idle→Run (which now also ZEROES
  v_setpoint — a stale Pi setpoint would rail the loop in 20–40 ms), the `'V'` entry edge only
  (a mid-run `V` is a setpoint step, deliberately not a reset), and `haltMotorOutput()` (covers
  all profile starts and every stop/`Q`/`X`/fault path). `constexpr` MOTOR_I_CMD_MAX +
  `static_assert` pins the clamp pairing (changing 12 A now breaks the build until re-synthesis).
  Safety review: no HIGHs; 1 MED (stale-setpoint rail at Run entry — fixed) + 3 LOWs applied.
  Correctness review: no logic bugs; double-state compile tripwire, v_setpoint-zeroing assert,
  and gate-edge test added; "velocity PI" wording swept (fallback/history references kept).
- **Tests: 2716 production + 175 bench pass** (replay-verified against the generated vectors,
  saturated episode included, via new `controller_design_MIMO/drive_replay_vectors.h`;
  `-I../controller_design_MIMO` added to the test Makefile).
- **Next bench (read before any velocity run):** the fw v7 S1 precondition is still open and
  sharper now — set the VESC Battery Current Max (≈4.2 A) / Regen Max (≈1.5 A) and tick
  `docs/VESC_MOTOR_INTEGRATION.md` §4 BEFORE any `'V'`/`'D'`/`'Y'` run; OC faults are compiled
  out under BENCH_TEST and the new loop rails at ±12 A within ~30 ms for |e| > ~16 mm/s. First
  `'V'` run is the synthesis validation: compare the small-signal step against
  `figures/drive_siso_step.csv`, scope-armed, small setpoints first.

---

## Status & session addendum (2026-08-16, fw v11: BLG v5 drive-controller observability)

Pre-velocity-run round (operator request): the SD bench log gains the drive controller's
internals so the Hanus conditioning is verifiable on hardware. **fw v11 (pending first flash —
fw v10 was never flashed, so the first flash carries both);** ledger row has full detail.

- **BLG RECORD FORMAT v5 (76 B, hdr[4] = 5).** Two float32 APPENDED (all v1–v4 offsets
  unchanged): `u_unsat` at 68 (drive controller PRE-clamp output, held between 500 Hz ticks —
  1 kHz logging duplicates it in pairs by design) and `drive_x0` at 72 (the exact-integrator
  state x[0]). Flags gain bit4 (command from the Youla DRIVE controller) and bit5 (share loop
  is the Youla build) so records are law-self-identifying; under a `USE_YOULA_DRIVE_CONTROLLER=0`
  flash the fields carry the PI's pre-clamp command and `pi_motor_accum` (A/B-comparable).
  During saturation, u_unsat hugging the rail = conditioning working; diverging beyond it =
  windup. Header layout otherwise v4-identical; trailer block grows with the record; UDP
  telemetry (v4/58 B) and the 'L' stream unchanged. Ring math re-verified at 76 B (6 rec/chunk,
  6.0× catch-up, ~7.4 min preallocation; no buffer grew).
- **Tooling:** `decode_benchlog.py` parses v5 (v1–v4 byte-identical, verified vs three
  checked-in logs); `benchlog_analysis` gains a `drive_controller_conditioning` figure
  (u_unsat vs I_cmd, ±12 A rails, saturated intervals shaded, x[0] subplot; skips pre-v5 logs);
  analyzer exe rebuilt; `make_test_blg.py --v5` defaults bits 4/5 ON.
- **Review round:** no firmware defects. D3: `setManualMotorCurrent()` ('A') now resets the
  drive controller (unconditional — 'A' never steps the loop, so there is no operating point to
  preserve; prevents a stale u_unsat/x0 trace with bit4 set in K-logged 'A' runs). D1/D2 (doc):
  **the operator set the VESC limits 2026-08-16 — Battery Current Max 6.0 A fwd / 1.5 A regen
  — closing the fw v7 S1 precondition**, but 6.0 A is 1.43× the §12.4-derived ≈4.2 A allowance
  and above its scope-gated 5.4 A conditional ceiling; §12.4 is annotated, and re-deriving it
  against 6.0 A (or lowering the setting) is the outstanding action before a vehicle run. Bench
  note: 6.0 A split evenly = exactly LIMIT_I_BT_MAX 3.0 A/channel, and FC-heavy setpoints
  exceed LIMIT_I_FC_MAX 1.4 A — with OC faults compiled out under BENCH_TEST, nothing in
  firmware catches either.
- **Tests: 2747 production + 175 bench pass.** New coverage: record size/offsets (append-only
  guarantee pinned via offsetof), hdr v5, bit4/bit5, pre-clamp value plumbing (saturating +
  unclamped), 500 Hz held-pair semantics, reset-to-zero; ring-wrap chunk math re-derived at 6
  records/chunk.
- **Next bench:** flash fw v11; first `'V'` run is the synthesis validation — small setpoints,
  scope-armed, compare against `figures/drive_siso_step.csv`, and read the new conditioning
  figure after each run.

---

## Status & session addendum (2026-08-16, fw v12: edge-period estimator + re-synthesis)

The first closed-loop `'V'` runs (ML0136–139, fw v11, steps 0.1/0.5/1.0 m/s) all limit-cycled
rail-to-rail at 2.3–2.6 Hz — the 16 rad/s design crossover. Four-agent log analysis converged on
the root cause: `updateWheelSpeed()`'s boxcar advanced once per main-loop tick, realizing a
~113 ms window (~56 ms group delay = 52–58° at crossover > the whole 49.6° PM; 0.0177 m/s
quantization), and the estimator was absent from the synthesis plant. The runs DID validate the
Hanus anti-windup on hardware (~150 rail episodes, u_unsat hugging the rail, clean releases) and
the DC friction model. **fw v12 (pending first flash — carries v10+v11+v12):**

- **Edge-period estimator (operator-specified).** Period measured same-edge-type (A-rising to
  A-rising) over one full slot pitch (2π·0.0762/120 = 3.990 mm) to cancel optical-sensor
  asymmetry; `ENC_PERIOD_AVG_N` = 2 period averaging (configurable); direction from the
  quadrature decode (Δ`encoderPos` = ±2 between A-risings; flip → ring invalidate); glitch
  drop < 200 µs without advancing the base; stale timeout max(1.5·lastPeriod, 150 ms) → 0;
  zero-speed floor ≈ 0.027 m/s; `PRIMASK` save/restore snapshots. **Safety-review MED-HIGH
  fixed: ring invalidation at speed HOLDS the last valid reading** (bounded by the stale
  timeout) instead of emitting a full-scale v=0 step into the 545 A/(m/s) controller — v_actual
  zeroes on exactly three events (boot, `encoderVelReset()`, stale timeout). Delay now
  (N+1)·pitch/(2v): ~3 ms at 2 m/s (was 56), ~12 ms at 0.5 m/s; quantization timer-limited.
  `'S'` dump gains a periods/dir line (fw v8 observability lesson).
- **Re-synthesis with the estimator in the plant** (separate Pade2 on the measured output only —
  the §4.4 coupling taps the physical speed; G22 4→6 states; corners × v0 ∈ {0.5, 2, 5} = 72).
  Bench gain datapoints refit (the 113 ms boxcar's ~93 ms fill dead-time explained the
  0.158-vs-0.198 (m/s²)/A spread; both converge to 0.186–0.204): **K_v recentred 1.25, corners
  {0.85, 1.25, 1.85}** (span narrows ×4.0 → ×2.2, which pays for the delay). Chosen rung WC=60 /
  Wu(0.25, 300, 12.5): **crossover 15.98 rad/s (unchanged), PM 51.9°, DM 56.7 ms, worst-corner
  ‖S‖∞ 2.42 cont / 2.52 disc, estimator phase at crossover 2.74° (was 51°), 0.5 m/s corner PM
  43.7°**; new gates pin both. **Validity floor: the design is gate-checked for v ≥ 0.5 m/s
  only** — below it the estimator is a deadband relay (needs ~3 edges/12 mm before a first
  reading) and low-setpoint steps are expected to limit-cycle; the ML0136/38 0.1 m/s runs are
  NOT covered by this fix. ⚠️ A v12 trace vs a v11 trace is two different control laws
  (K_v, weights, KI 73.6→53.4 all changed), not just two estimators.
- **Replay-vector hardening (test round caught it):** the regen vectors were knife-edged
  (float64 trajectory replayed open-loop through the float32 controller chattered ON the clamp
  boundary). Now generated closed-loop through the shipped float32 coefficients with
  stimulus-truncation gates; consumer tolerances embedded in the artifacts (small ≤1e-4 A;
  regen ~50 mA — the controller genuinely dithers across the ±12 A boundary during hard regen,
  82 clamp transitions in the design sim; tighter gates fail correct implementations).
  `tools/gen_drive_replay_header.py` is now a permanent tool (regenerate
  `drive_replay_vectors.h` whenever the synthesis regenerates the CSV).
- **Open items:** `m_eff` CHALLENGED — ramps vs cruise-hold gain datapoints contradict by ×2 in
  opposite directions and m_eff ≈ 1.6–2.0 kg (vs the operator's 3.5) is the single constant
  closing both, consistent with the coast-down residual; top bench item (re-measure J or a
  timestamped coast-down). `validate_mimo_model.py` G1.5/G1.6 now fail (truth model lacks the
  estimator + recentred K_v) — deferred to the MIMO regeneration round; staleness bannered.
- **Tests: 2785 production + 175 bench pass** (11 new estimator cases incl. the hold/timeout
  semantics and an ISR-driven end-to-end; C++ regen replay lands at 21 mA worst).
- **Next bench:** flash; first `'V'` at **≥ 0.5 m/s** (1–2 m/s preferred), scope-armed, overlay
  vs `figures/drive_siso_step.csv`, read the conditioning figure; expect clamp dither during
  hard regen (not a fault). Re-derive VESC doc §12.4 against the set 6.0 A before a vehicle run.

## Status & session addendum (2026-08-16, fw v14: K_F force-axis correction)

The `K_F` investigation the fw v13 freeze was waiting on has reported. The drive channel's
force axis was wrong on two independent counts; correcting both reconciles every
drive-channel measurement on record and **confirms `m_eff` = 3.5 kg**. **fw v14 (pending
first flash; the first flash now carries v10-v14);** ledger row in
`docs/firmware-versions.md` has full detail.

- **ROOT CAUSE - the force chain carried the wrong gear ratio AND the wrong radius.**
  `PHI` **9.49 -> 6.86**: the 9.49 was a STOCK-gearing web figure, and the fitted pinion is
  29T against a counted 70T spur. Triple-confirmed - Traxxas 4-Tec manual p.24 formula
  (spur/pinion)x2.85 gives 6.88, the manual's chart cell (29, 70) gives 6.87, operator
  rolling counts give 2.84-2.86 for the shaft/tire stage. The FORCE radius
  **0.0762 -> 0.033 m**: the rig is motor -> gearbox -> **tire** -> roller -> **flywheel**,
  so torque reaches the road through the tire while the encoder and the inertia belong to
  the flywheel. `plant_mimo.py` now splits the roles explicitly (`R_TIRE` for force/omega,
  `R_FLY` for encoder pitch and `J/r^2`). Net **`K_F` 0.4516 -> 0.7538 N/A, x1.669**.
- **The VESC-Tool RPM display reads x2 the true mechanical speed** (pole/pole-pair display
  convention, 4-pole motor) - which is why an operator flywheel-vs-motor spin count of ~32
  appeared to corroborate a larger reduction against the chain-predicted 6.86x(0.0762/0.033)
  = 15.8. **Display artifact only:** the lambda-vs-KV cross-check (1.451 predicted vs 1.422
  measured mWb at p = 2) is independent of it, so **`k_t` = 4.266e-3 N*m/A is untouched.**
  Halve anything read off that display before comparing it to a mechanical count.
- **The drag law rescales; `i_m0` does not.** `B_EFF_NOM` 0.32 -> **0.534 N*s/m**,
  `F_COULOMB` 1.2 -> **2.00 +- 0.42 N** (cold 2.19 / warm 1.75-1.84) - the raw data are hold
  CURRENTS and are unchanged; only their force conversion moved. `i_m0` = 4.07 A is
  therefore INVARIANT (drag is current-referenced), and its ~9 % shortfall against the
  measured 4.5 +- 0.4 A hold stands, still attributed to the unmeasured `eta_dt` = 0.85.
  Drive pole -0.0914 -> **-0.1526 rad/s**; `omega0` 249.1 -> **415.8 rad/s**.
- **Every contradiction on record closes, and `m_eff` = 3.5 kg is CONFIRMED.** The
  ramp-vs-cruise factor-of-2 dissolves (ramps x1.109-x1.213 vs cruise x0.905) for a stated
  reason: the cruise-implied gain IS the drag law and rescales with `K_F`, while the
  ramp-implied gain is `m_eff*a/I` and does not - one moves, the other does not. The
  coast-down closes too (ladder-predicted 0.37-0.45 -> x1.669 -> **0.62-0.75 m/s^2** vs
  observed 0.62). The 1.6-2.4 kg mass inferences were `F/a` fits reading `F = K_F*I`, so an
  understated `K_F` read back as an understated mass in exactly the observed ratio; x1.669
  moves all of them onto ~3.5 kg. **The operator's fw v13 ruling is confirmed and the
  investigation is RESOLVED** - the model and coefficients are no longer frozen.
  `eta_dt` stays 0.85 `TODO(calibrate)`: the ramp residual is now only x1.11-1.21, no longer
  the unphysical `eta_dt >= 1.0` that the retired axis implied.
- **`K_v` re-centred 1.25 -> 1.00, corners {0.85, 1.25, 1.85} -> {0.75, 1.00, 1.35}** (span
  x2.2 -> x1.8) - the axis no longer has to straddle a contradiction. Corners bracket both
  evidence bands with margin (0.75 is 10 % below the cruise band's 0.831; 1.35 is 11 % above
  the ramp band's 1.213). `G22(0)` = 1.4116 (m/s)/A; effective `K_F*K_v` 0.5645 -> 0.7538
  (**plant gain x1.34**).
- **Re-synthesis needed NO weight change.** The shipped rung (WC = 60, Wu(0.25, 300, 12.5))
  passes every gate on the corrected plant: crossover 17.52 rad/s, PM 50.8 deg, DM 50.6 ms,
  worst-corner ||S||inf 2.427 cont / 2.535 disc over 72 corners, 0 unstable, PM 41.8 deg at
  the 0.5 m/s validity floor. `validate_drive_siso.py` 15/16 (the one failure is the
  documented float32-STATE divergence). The ladder table in `synthesize_drive_siso.py` was
  NOT re-run and every non-chosen row is now indicative only - bannered in place.
- **Firmware effect is coefficient regeneration ONLY.** `FW_VERSION` 13 -> 14, the
  regenerated `drive_controller_coeffs.h`, and two stale comments quoting the old ratio.
  No pin, sequencing, fault, telemetry, BLG-format or command change; no control code
  edited. ⚠️ **A v14 `'V'` trace is a DIFFERENT CONTROL LAW from a v13 one** (new
  coefficients, new K_I, x1.34 plant gain). The **velocity chain is untouched** -
  `FLYWHEEL_RADIUS_M` 0.0762 m, 240 counts/rev and the edge-period estimator are all
  unchanged - so `v_act` traces ARE comparable across v13/v14.
- **Next bench:** unchanged from fw v13 - solder the Schmitt (74HC14 at 3.3 V) and verify
  the edge counter at 240/rev BEFORE any velocity run; then flash and run `'V'` at
  1-2 m/s scope-armed, overlaying against the regenerated `figures/drive_siso_step.csv`.
  Two model items remain open: `eta_dt` = 0.85 (now the largest surviving drive unknown),
  and **no-slip at the tire/roller contact**, which the corrected force chain makes an
  explicit assumption rather than an implicit one.

---

### Hardware bodge record (2026-08-16): encoder pull-ups 4.7 kΩ → 2.2 kΩ

The two OPB829DZ phototransistor pull-ups (BOM line 73, 4.7 kΩ as designed) were changed to
**2.2 kΩ** in a bodge round. Recorded alongside the pins-14/15 reroute because any future
encoder-front-end analysis or rework must use the fitted value. Consequence: the RC rising
edge is ~2× faster than the design value, but the front end remains a bare phototransistor
with no hysteresis — the ML0140–145 edge-corruption findings (missed AND spurious A-edges;
see the fw v12 analysis) were taken WITH the 2.2 kΩ fitted, so the faster pull-up is already
known to be insufficient on its own. A Schmitt buffer/comparator remains the root fix; the
stronger pull-up mainly shifts suspicion toward the phototransistor's own slow fall time and
threshold-region noise rather than the RC rise.

---

## Status & session addendum (2026-08-16, fw v13: estimator hardening + v_sp zero-cutoff)

The fw v12 fix-validation runs (ML0140-144 'V' steps 0.5-3 m/s + ML0145 forward stepladder)
showed the boxcar limit cycle gone (edge-period estimator confirmed live, timer-fine) but
exposed encoder EDGE CORRUPTION as the remaining sensor defect: spurious A-edges (v reads
1.33x/2x high - 100% contamination at low speed, ML0145) AND missed A-edges (2/3, 1/2
families, ML0143), plus blind holds under direction dither (ML0140: 120-560 ms; the stale
timeout, keyed to edge age, never fired) and a v_sp=0 relay (ML0144: closing the loop below
its own floor = 90% rail bang-bang; the same run at 1.0 m/s settled at 1.7% overshoot /
0.44 s rev-averaged). Scope capture 15: full-swing signals, ~0.5-1 ms analog edge ramps, no
hysteresis - root physical cause; a Schmitt bodge (SN74HC14N; check the pull-up rail - 2.2 k
bodged, possibly to 5 V, Teensy pins NOT 5 V tolerant) is the hardware fix. Direction
comparison: ML0135/TP reverse-direction data VALID (fwd vs rev within +-7%, sign-alternating
deviations). m_eff: operator RULING - 3.5 kg is a floor (flywheel J measured); the
apparent-mass discrepancy is assigned to K_F, under investigation in a separate session;
model/coefficients FROZEN meanwhile. fw v13 (pending flash; first flash carries v10-v13) -
the firmware backstop for the Schmitt:

- Adaptive period plausibility (ISR): EWMA reference (alpha=1/4 shifts); < 0.625x ref
  rejected without advancing the base (spurious halves merge); 1.5-3.5x ref reinterpreted as
  k=2/3 pitches (ring stores period/k); armed ONLY when ref < ENC_ADAPT_MAX_REF_US 13 ms
  (v > 0.307 m/s - safety review S1/S2: below that, genuine rail accel/decel legitimately
  breaks the ratio gates, and the k-branch has self-reinforcing poisoned fixed points at
  ref=T/2,T/3 reachable through rail decel at ~0.29 m/s; the 0.04-0.30 m/s band is
  UNMITIGATED by firmware and belongs to the Schmitt). Poison backstop:
  ENC_KBRANCH_RUN_MAX 4 consecutive k>1 acceptances -> full estimator reset.
- Reading-age stale bound: holds bounded by max(K x last reading sum, 100 ms) on the last
  ACCEPTED READING's age (not edge age) - fires even with edges arriving. Zero-speed floor
  now 0.0399 m/s. Sign embargo (S3): a cnt<2 reading whose sign differs from the last
  published holds (and does NOT refresh the reading age), publishing at cnt=2 - dither ages
  out to 0 instead of chattering single-pitch readings into the 545 A/(m/s) controller.
- Partial-ring live readings: cnt>=1 same-sign readings publish immediately (fast warm-up
  and flip recovery); reversal is data, not invalidation.
- V_SP_ZERO_THRESH 0.05 m/s zero-cutoff in motorControl() (both build paths): below it,
  0 A + entry-edge controller reset, no loop stepping (Idle-consistent; drive-cycle/combined
  standstill segments now COAST at 0 A; 'Y' parse warns if Vmax*0.2 < the threshold). PI
  fallback: pi_motor_lastMicros refreshes every cutoff tick (S4 - exit no longer integrates
  the whole cutoff window). static_asserts pin the floor ordering and LO_FRAC.
- Tests: 2858 production + 175 bench pass (adaptive-filter brackets, k-reinterpretation,
  poison guard, embargo ageing, arm-threshold bracket, zero-cutoff, ML0140 blind-hold
  regression). No coefficient/model/telemetry/BLG change.
- Next bench: solder the Schmitt (74HC14 at 3.3 V; move pull-ups to 3.3 V if they are on
  5 V), verify with a constant-speed edge-counter check (240/rev) and a repeat 'A' ladder
  (rungs gone), THEN flash fw v13 and re-run 'V' at 1-2 m/s scope-armed incl. a deliberate
  decel through 0.3 m/s (S1 doubling-signature check). K_F investigation results return here
  for the model/coefficient round.

---

## Status & session addendum (2026-08-16c, fw v14: K_F force-axis correction — cross-session)

The K_F investigation (separate session) closed and shipped **fw v14**; verified here
(FW_VERSION 14, ledger row 14, coefficients regenerated, **2861 production + 175 bench
rebuilt-from-source green**). In brief: the force chain carried the wrong ratio AND radius —
PHI 9.49 (stock gearing) -> **6.86** (fitted 29T/70T, triple-confirmed) and force radius
0.0762 (flywheel) -> **0.033 m** (tire; torque acts on the tire, the encoder/inertia belong
to the flywheel — the two were conflated). **K_F 0.4516 -> 0.7538 N/A (x1.669)**; the drag
law rescales in lockstep (b_eff 0.534 N s/m, F_c 2.00 +/- 0.42 N; i_m0 = 4.07 A invariant);
**m_eff = 3.5 kg CONFIRMED** (all three contradicting inferences close; the fw v13 freeze
ruling was correct — the deficit was entirely the force axis). The VESC Tool RPM display
reads 2x true mechanical speed (display artifact; k_t unaffected). K_v recentred 1.00,
corners {0.75, 1.00, 1.35}. Re-synthesis on the same weight rung: crossover 17.5 rad/s,
PM 50.8°, PM 41.8° at the 0.5 m/s floor. Coefficients + FW_VERSION only — no logic change;
a v14 'V' trace is a DIFFERENT control law than v13 (x1.34 stiffer DC plant gain); v_act
traces remain comparable (velocity chain untouched). **Do not re-fit any pre-v14 force-axis
numbers.** Still open: eta_dt 0.85 (largest surviving unknown), tire/roller no-slip (now an
explicit assumption), ML0141 gain excess (reduced to ~1.8-2.7x, boxcar-confounded —
re-evaluate on fw v14 runs), VESC Tool Gear Ratio setting still 9.49 (cosmetic). Full
record: motor_id_20260815.md §"K_F force-axis correction (2026-08-16c)". Bench order
unchanged from fw v13: Schmitt bodge -> edge-counter check -> 'A' ladder -> flash (first
flash carries v10-v14) -> 'V' at 1-2 m/s scope-armed.

---

## Status & session addendum (2026-08-17, fw v14 first-flash log round: ML0146-151 + YP0152)

First logs from the fw v14 flash (the flash carrying v10-v14), analyzed by a seven-agent
fan-out (one per log). No firmware change came out of this round. Analysis outputs live in
`logs/ML0146` ... `logs/YP0152`; runs: 'V' steps at 0.5/0.75/1.0/1.5/2.0 m/s (ML0146-150,
manual 'K' logs), a 0->2.66->0 m/s stepladder (ML0151, 56 s), and the first 'Y' combined
profile on the Youla drive controller (YP0152, Vmax 2.0, b 0.30, natural completion).
All decodes clean: zero drops, zero missed periods, zero faults.

- **K_F VALIDATED ON HARDWARE; the ML0141 gain excess is CLOSED.** Rail-acceleration check
  (ML0151, 0.7 s continuous +12 A): a_meas/a_model = 0.968. Hold currents at every cruise
  level 0.5-2.66 m/s across all seven logs sit at 0.89-0.92x the drag-law prediction
  i(v) = (2.00 + 0.534 v)/0.7538 (post-drag-event branch 1.10-1.15x; both inside the
  F_c = 2.00 +/- 0.42 N band). Incremental dv/dI at clean ladder transitions: 0.96-1.05x
  G22(0). The old 1.8-2.7x excess reproduces nowhere. The consistent ~10 % hold-current
  shortfall matches the still-open eta_dt = 0.85 in direction and rough scale.
- **The controller works.** SS error <= 2 mm/s at every level (std ~0.025-0.03 m/s). Hanus
  conditioning verified across ~90 saturation episodes (worst sustained u_unsat excursion
  +3.4 A past the rail, clean release every time, no windup). Zero-cutoff + controller
  reset verified on hardware in YP0152 (3951 coast ticks, I_cmd == 0 and x0 == 0
  throughout, clean re-entry). The 2.3-2.6 Hz boxcar limit cycle is confirmed gone
  (< 1 % band energy everywhere). Rise 0.08-0.10 s (1.3-1.6x faster than small-signal
  design) with 13-26 % overshoot vs 4.8 % design - plant slightly stiffer than nominal,
  consistent with the 0.89 hold ratio; watch, no action.
- **NEW: mechanical drag step-change, ML0151 t~27.5 s** (during the 2.0->2.5 step): real
  speed collapse 2.55->1.30 m/s, 688 ms full-rail recovery, and afterwards drag is
  PERMANENTLY ~2.2x higher (bus input at 2.0 m/s: 4.30 -> 9.44 W). Encoder edge rates match
  prediction on both sides, so it is physical (tire/roller contact or preload), not sensor.
  Inspect the rig before the next run; any drag-law refit must treat the two halves
  separately.
- **NEW: VESC ~428 ms dead window after hard regen->drive reversal** (ML0151 t=42.0 s):
  I_cmd +11.4 A commanded, delivered current < 50 mA, car still decelerating - the entire
  cause of the 2.66->2.0 step's 87 % undershoot (plus four 23-26 ms instances at low
  current). Not a firmware bug; characterize before any vehicle run.
- **Encoder verdict unchanged, sharpened.** Above 0.307 m/s: zero rung-family corruption in
  ~130k samples - the fw v13 adaptive filter holds; deliberate decels through 0.3 m/s
  (ML0150/151) were clean, no S1 doubling signature. Below ~0.4 m/s (YP0152 regions 13/14):
  sign reversals to -1.0 m/s driving full +/-12 A rails, 32 % saturation dwell. Residual
  defect at cruise: I_cmd chatter 3.5-5.6 Hz, up to ~11-13 A pk-pk while v_act ripples only
  ~0.03 m/s - estimator edge-jitter amplified by the ~545 A/(m/s) LF gain; current-side
  only, not a velocity limit cycle. The Schmitt (74HC14 at 3.3 V) remains the root fix and
  is now also the prerequisite for judging the chatter.
- **YP0152 was NOT a cross-coupling test:** total source current (median 0.13 A) never
  crossed the 0.60 A closed-loop entry gate, so the share loop ran open-loop feedforward
  for 99.8 % of the run (ML0146-151 had gFC = gBT = 0 outright). Repeat 'Y' with a real bus
  load >= 0.6 A (ideally >= 1.5 A) before drawing coupling conclusions. Bus health: V_bus
  15.87-15.95 V the whole profile - which is nominal, see below.
- **STALE-CONSTANT SWEEP: bus nominal is 16.0 V, not 17.5 V.** The round's one false alarm
  ("V_bus 1.6 V below nominal") traced to this file's own Section 6, which still taught the
  pre-retune 17.5 V / LIMIT_V_BUS_MAX 18.5f pair. The firmware has been right since the
  2026-07-11 RD1 = 215k FB retune (V_BUS_NOMINAL 16.0f, V0 = 15.91 V no-load,
  LIMIT_V_BUS_MAX = nominal + 1.5 = 17.5 V). Fixed in lockstep: CLAUDE.md Section 6,
  AGENTS.md, README.md (both 18.5 V references), PLAN.md (Section 6a + resolved-questions
  table), docs/modeling/bond-graph.md, and the two reconcile notes in
  papers/Droop_Control/sections/04_board_design.tex (now RESOLVED at 16.0 V). Historical
  bring-up narratives keep their as-was values. Do not reintroduce 17.5 V as nominal.
- **Next bench, in order:** (1) inspect the tire/roller contact (the ML0151 drag event
  moved the operating point mid-session); (2) solder the Schmitt; (3) characterize the VESC
  reversal dead window ('W'/'T' reversal test); (4) repeat 'Y' with a real bus load.
  Housekeeping: `.venv_benchlog` is missing pandas (agents worked around it) - repair
  before the next log round.

---

## Status & session addendum (2026-08-17, fw v15: dpos-based pitch count)

Operator-diagnosed, code-confirmed: the fw v13 adaptive period filter has an ABSORBING
slow-reading poison basin at ref ~ 2T. Real edges at T fail the 0.625 low-side gate
(T < 1.25T), are rejected without advancing the base (correct for genuine spurious edges),
and the next edge measures 2T -> ratio 1.0 -> accepted as ONE pitch, re-anchoring the EWMA
at 2T forever. v_actual reads exactly HALF; the drive controller doubles the real speed
("sudden 2x speed-up", bench 2026-08-17, no log). The ENC_KBRANCH_RUN_MAX tripwire was
structurally blind to it (every acceptance is k == 1, resetting the counter — it guarded
only the mirror ref ~ T/2 fast basin), and a tripwire reset taken mid-miss-burst could
SEED the basin (re-seed has no ratio gating). The ML0151 t~27.5 s "drag step-change" is a
CANDIDATE instance (v_act "collapse" ratio 2.55/1.30 = 1.96; the round's edge-rate
exoneration was circular — it predicted edge rate from v_act itself), though not settled:
bus input power genuinely changed, which pure re-scaling does not explain. **fw v15
(pending first flash; the first flash carries v10-v15):**

- **Pitch count is now a decoder MEASUREMENT, not a ratio inference.** In the accepted-
  interval path, pitches = nearest-integer(|dpos|/2) from dpos = encoderPos −
  encPosAtLastEdge ((|dpos|+1)>>1, floor 1, UNCAPPED, shift/add only). Sound because a
  rejected edge advances neither the time base nor the position reference, so dpos
  accumulates across rejections in lockstep with the period. Needs no reference and no
  speed arming (runs during seeding and below ENC_ADAPT_MAX_REF_US — the S1/S2 arming
  rationale is ratio ambiguity, which a count does not have). Both poison basins become
  non-stable: at ref~2T the merged 2T interval carries |dpos| = 4 -> stores/feeds T ->
  ref walks back; at ref~T/2 the true period passes the gate as one pitch.
- **Retired:** the ratio k = 2/3 branch, ENC_PERIOD_MAX_MULT, and the ENC_KBRANCH_RUN_MAX
  tripwire (encKBranchRun/encRefPoisonPending + the updateWheelSpeed() consumer) — under
  the new mechanism a run-length reset would fire during basin RECOVERY (consecutive
  pitches == 2 acceptances) and re-seed from the corrupted stream. **Kept:** the 0.625
  low-side gate + no-base-advance merge (and its speed arming, now governing only that
  gate), ENC_PERIOD_MIN_US, EWMA, ring, direction handling, dpos == 0 invalidation, and
  the ENTIRE reader side — v_act traces stay comparable with fw v12-v14.
- **Review round (two-lens, no HIGH/MED, 3 LOWs):** S1 (accepted, strengthened) — a
  PER-PITCH absolute floor: after the pitch division, per-pitch < ENC_PERIOD_MIN_US
  (200 us, incl. the integer-zero case) is dropped like a glitch (no store, no EWMA, no
  base advance). This is also the principled fast-direction backstop (per-pitch >= 200 us
  bounds indicated speed at ~20 m/s), which is why S2's arbitrary count cap was REJECTED.
  S3 (doc-only): the dpos == 0 branch still feeds the EWMA the raw elapsed interval,
  biasing ref high under dither — conservative direction only. Orchestrator liveness
  trace: persistent dpos corruption dropping every interval starves readings -> the fw v13
  reading-age bound fires within 100 ms -> v = 0 + clean reset. Bounded, safe direction.
- **Known residual (documented in the ISR):** a slot entirely unseen by channel A loses
  its decoder counts too (Afirst*/Bfirst* handshake), so |dpos|/2 under-reads by one and
  the interval stores SLOW — safe direction, EWMA-absorbed; the ratio cross-check that
  could catch it is exactly the ambiguous mechanism that created the basins, so it is
  deliberately not reinstated. The 0.04-0.30 m/s band and the un-Schmitted OPB829DZ edge
  corruption still belong to the 74HC14 hardware fix — v15 is a scale-stability fix, not
  a reason to defer the Schmitt.
- **Diagnostics:** encLastPitches/encMultiPitchCount (volatile, ISR-written, reset by
  encoderVelReset()) added to the State-98 'S' dump alongside ref (fw v8 observability
  lesson). No control path reads them. No pin/sequencing/fault/UDP/BLG/coefficient change.
- **Tests: 2913 production + 175 bench pass** (rebuilt from source, both builds). New:
  the 2T-basin escape regression (walks the estimator into the poisoned state, asserts it
  cannot stay locked), T/2-basin equivalent, uncapped multi-pitch counting (2/3/5),
  rounding (|dpos| = 1, 3), unconditional application (seeding + gate-dark), spurious-
  merge re-pin, dpos == 0 invalidation re-pin, tripwire-retirement negative (a persistent
  miss stream now yields correct readings and NO reset), diagnostics lifecycle, S1 floor
  (drop/boundary-at-200 us/zero-quotient), and negative-direction multi-pitch. Two
  pre-existing tests' "spurious" stimuli switched from full quadrature cycles to A-only
  wiggles — under dpos counting a full cycle IS real motion; the old stimulus was
  physically wrong, not the firmware.
- **Next bench:** unchanged order — inspect nothing further on the rig for the ML0151
  event until a v15 run separates the hypotheses (a repeat 2x event on v15 firmware would
  now be genuinely mechanical; v15 makes the encoder explanation impossible). Then:
  Schmitt (74HC14 at 3.3 V), VESC reversal dead-window characterization, 'Y' with a real
  bus load. On the first v15 'V' runs, watch encMultiPitchCount in the 'S' dump — a
  nonzero rate quantifies the real missed-edge frequency for the first time.
