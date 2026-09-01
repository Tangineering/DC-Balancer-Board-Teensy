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
  assert `MPPT_DISABLE` **active during active braking/regen** (so the slow MPPT loop
  doesn't fight the fast regen transient) and **release it during
  cruise/coast** so the Ag105 harvests. Implement this in `chargingControl()`. **Confirmed
  from PCB schematic: `MPPT_DISABLE` is active-LOW — pulling LOW inhibits the MPPT
  loop; pulling HIGH releases it.** **MECHANISM CORRECTED (2026-08-31, datasheet
  p.10): the Ag105's MPPT is an INPUT-VOLTAGE-THRESHOLD regulator, not perturb-and-observe
  (earlier "P&O" wording here and in two .ino comments was unsourced lore) — charging
  commences only when the input exceeds a threshold set by an MPPTS resistor or I2C reg
  0x02 (11-33 V, ~0.088 V/count; DEFAULT 18 V with MPPTS open). **R1 CLOSED AS MOOT
  (2026-09-01):** Table 7 encodes reg 0x02 values 0-250 as register mode and ≥251 as the
  MPPTS resistor, so a firmware write overrides any fitted resistor and the MPPTSEL header's
  population is documentation, not a design dependency. **fw v24 writes reg 0x02
  dynamically:** target = V_chg (pin 38) windowed minimum − 3.0 V, quantized DOWN, clamped to
  counts [15 = 12.320 V, 27 = 13.376 V], applied through a monotone-lower session ratchet
  (≤ 2 lowerings per session, 30 s apart, deadband 3 counts, ≤ 8 physical writes per boot).
  The two stale P&O .ino comments were corrected in fw v24. Ag105 EPROM write endurance is
  not in the datasheet — `TODO(verify: Silvertel)`; the structural lifetime bound is ~236
  writes.** **FC-path bootstrap:** in cruise with
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
- **MPPT threshold** (`N` command, fw v24): prints the Ag105 reg-0x02 threshold status (current
  count, tracked V_chg window minimum, ratchet and write budgets), forces a threshold write, or
  restores the default.
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
- Run before every flash: build and run all three targets from `test/`. Every target needs
  `-I../controller_design_MIMO` on the include path (the drive-controller replay vectors live
  there).
  - `run_tests` — production build, compiled with `-DBENCH_TEST=0 -DHIL_SIM=0` (3842 checks).
  - `run_tests_bench` — bench build, `-DBENCH_TEST=1 -DHIL_SIM=0` (175 checks).
  - `run_tests_hil` — HIL build, `-DHIL_SIM=1 -DUSE_ETHERNET=1` (4324 checks).

See PLAN.md §10 for the full directory layout and test category table.

**HIL build flag.** `HIL_SIM` (repo default **0**) compiles the signal-level
hardware-in-the-loop path, in which a UDP **40-byte injection frame** overrides
`updateSensors()` and an **18-byte observation frame** streams switch/state/command mirrors
back at 1 kHz. It requires `USE_ETHERNET=1`. An HIL flash requires editing `HIL_SIM` to 1 in
the `.ino` — a default flash is a normal bench build, and a `HIL_SIM=1` build sits visibly in
the State-0 wait loop until a simulator streams to it. See `docs/HIL_MODE.md` for the frame
tables and test plan, and `docs/HIL_USER_MANUAL.md` for the operator procedure.

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

## Archived session history (2026-06-23 through 2026-08-31, fw v2–v23 tooling bring-up)

The superseded status addenda from that period were moved verbatim to
`docs/claude-md-archive.md` to keep this file under the memory-size limit. Two ranges are
archived. The first (2026-06-23 through fw v7, 2026-08-13) covers early bring-up, the
boost-death investigations, the share-controller design round, and fw v2–v7. The second
(rotated 2026-09-01) covers the encoder/BLG era and the HIL tooling bring-up: fw v8–v17 and
fw v20 (encoder pin move, `'K'` manual logging, the Youla-H drive controller, BLG v5–v7, the
edge-period estimator, the K_F force-axis correction, the dpos/fractional-pitch ledger, the
log rounds ML0146–ML0180), and the HIL rounds fw v21–v23 with their tooling follow-ups
(2026-08-27 through 2026-08-31). Every load-bearing fact from both ranges survives in
`docs/firmware-versions.md`, PLAN.md, the HIL docs (`docs/HIL_MODE.md`,
`docs/HIL_PLANT.md`, `docs/HIL_USER_MANUAL.md`, `docs/HIL_REPLAY_LOGS.md`), or a retained
hardware bodge record below. Read the archive before revisiting bring-up failures, pre-v18
encoder/velocity history, or the origin of an HIL tool.

The three hardware bodge records below are **never rotated** — the board does not match the
2026-06-22 schematic, and any rework must preserve or knowingly revert each one.

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

**Campaign records:** the per-campaign HIL ledgers (`HIL_FINDINGS.md`, `HIL_SUMMARY.md`,
report folders) live under the gitignored `HIL Results/` directory and are local-only. The
campaign addenda below are therefore the **only committed record** of what each campaign
found — do not delete one on the assumption that the report folder still holds it.

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

## Status & session addendum (2026-08-25, fw v18: 90-slot wheel + general-Hanus anti-windup fix)

Two hardware rounds since fw v17. First, logs ML0182/183 (fw v17, the thin-tooth 120-slot
painted PETG-CF wheel) showed the decoder producing counts over only a ~30 deg sector of each
revolution (~20 of 240 counts/rev; revolution-locked bursts, ~92 % blind) — sensor alignment,
not firmware. The operator then swapped in a **90-tooth wheel** and hand-confirmed **180
encoderPos counts per rotation**. Orchestrated round (Opus implementer, Sonnet test-writer,
Opus safety + Sonnet correctness reviews) shipped **fw v18 (pending flash; carries v18 alone
— fw v17 was flashed for ML0182/183)**. Ledger row 18 has full detail.

- **Wheel reconciliation:** `ENCODER_SLOTS_PER_REV` 120 -> **90** (counts/rev 180,
  `ENC_SLOT_PITCH_M` 3.990 -> **5.3198 mm**). Re-derived: `ENC_ADAPT_MAX_REF_US` 13000 ->
  **15000 us** (arms 0.3547 m/s = 1.064x v_arm), `ENC_VEL_CORROB_MIN_MPS` 0.30 -> **0.35**,
  zero-speed floor 0.0399 -> **0.0532 m/s**, and therefore `V_SP_ZERO_THRESH` 0.05 ->
  **0.07 m/s** (ordering static_assert re-admitted; margin 24 %). NEW compile tripwires pin
  the pitch coupling: gate-arming above v_arm (squared product form) and corroboration <=
  arming speed — both verified to FIRE on the "wheel changed, constants stale" mistake.
  `VELOCITY_CHAIN_CALIBRATED` stays 1 (operator hand count).
- **Drive re-synthesis** (plant_mimo ENC_SLOTS 90; estimator delay x4/3): same weight rung
  passes all gates — crossover 17.25 rad/s, PM 50.2 deg, 72 corners 0 unstable, PM at the
  0.5 m/s floor 41.8 -> **38.4 deg** (gate > 30), worst-corner ||S||inf 2.867 cont /
  3.017 disc (above the 2.5 target, under the 3.0 gate — accepted as the delay cost).
  Synthesis env is **controller_design_MIMO/ctrl-venv** (.venv_benchlog has no scipy).
- **STRUCTURAL ANTI-WINDUP DEFECT FOUND AND FIXED (shipped since fw v10).** The test round's
  saturation probe exposed a +-12 A period-4 (125 Hz) rail-to-rail limit cycle under
  sustained constant error. Root cause: Tustin discretization leaves an exact controller
  transmission zero at z = -1 (the (z+1) factor is common to both parallel branches at ANY
  weight rung), and the Hanus SELF-conditioned form's saturated-mode matrix AC = AD-BD*CD/DD
  has the controller zeros as eigenvalues — marginally stable at Nyquist, always. **fw v17
  fails the same dwell sweep at e >= 8.25 m/s (14/48); its e = 5.0 pass was stimulus luck.**
  Hardware-reachable during VESC post-reversal dead windows (ML0151 class). Fix
  (user-authorized, folded into v18): **general Hanus gain** — x_next = AD*x + BD*e +
  L*(u - u_unsat), L pole-placed (dual place_poles) to move ONLY the z = -1 mode -> +0.5,
  all other saturated-mode eigenvalues untouched; unsaturated behavior bit-identical
  (conditioning term exactly zero off the clamp; linear gates byte-identical). Full-damped
  placements measurably FAIL (integrator conditioning mode dragged off ~1 -> standing error
  up to -1.13 m/s) — minimal perturbation is the design, recorded at the site. New
  SYNTHESIS gates: oscillatory-eigenvalue margin (|eig| < 0.999 on non-positive-real modes;
  a flat 1-1e-3 bound is unachievable — the exact integrator keeps a slow +0.9997 real
  mode) and the LOAD-BEARING 48-case constant-error dwell sweep (tail p-p 0.000 A). New
  `dwell` replay episode (600 ticks at e = 5, tol 0.10 mA) + firmware dwell-sweep test.
  Side effect: the long-standing float32-STATE replay "expected failure" is GONE
  (validate_drive_siso now **17/17**; regen divergence 1.6e-2 -> 1.1e-5 A — the conditioned
  trajectory no longer rides the clamp boundary); state stays double.
- **Tooling:** benchlog pitch is now per-log — fw_version >= 18 -> 5.3198 mm, with an
  explicit `cfg["_encoder_pitch_m"]` override (fw is a PROXY for the disc; ML0183 is the
  last 120-slot log) and a visible fallback provenance stamp on the encoder_diagnostics
  panel. log-conventions.md carries the dual geometry + log-number boundary. Analyzer exe
  NEEDS REBUILD (flagged, not done). make_test_blg stamps pitch by --fw-version.
- **Review round:** safety — no HIGH; 3 MED (stale metrics record documenting the retired
  recursion; fw-as-proxy override; pitch-coupling tripwires) + 5 LOW (V-command sub-cutoff
  warning, stale 12 mm warm-up, stale 745.5/544.8 A/(m/s) LF-gain sweep -> **454.4** and
  e_sat 26.4 mm/s, fallback annotation, compare_controllers pointer). Correctness — clean,
  1 LOW (margin formula made explicit). All applied.
- **Tests: 3043 production + 175 bench pass** (rebuilt from source, orchestrator-verified).
  New: dwell sweep incl. the 8.25-11.75 defect band + both rails, dwell replay, DRIVE_CTRL_L
  pin, 90/180 literal pins, the 0.06 m/s coast bracket. Test build needs
  `-I../controller_design_MIMO`.
- ⚠️ A v18 'V' trace is a different control law than v17 (new coefficients AND new
  saturated-mode behavior), and pre-v18 v_act was computed on physically different wheels.
- **Next bench:** flash fw v18; motor PI/`'V'` validation on the new wheel (small setpoints,
  scope-armed, overlay vs regenerated figures/drive_siso_step.csv); a sustained-rail event
  should now HOLD 12 A, not chatter — the BLG u_unsat trace is the verification signal.
  Then: VESC regen-ceiling characterization -> matched-Itot share sweep -> F_c/b_eff refit.
  Housekeeping: rebuild the benchlog analyzer exe; .venv_benchlog still lacks pandas/scipy.

---

## Status & session addendum (2026-08-31b, overnight campaigns 1–4: 156 runs, zero board defects)

Four back-to-back full-suite campaigns run autonomously overnight (operator away;
`OVERNIGHT_LOG.md` has the decision log + resume points), each analyzed under the
hil-agent-analysis skill, with two fix rounds between. Commits 817295d → 9612369 →
82c8f75; report folders hil_report_20260831_{000518,010145,015024,021553} (local-only).

- **Round 1 (39/39 — first fully-green campaign on record, every PASS verified for the
  right reason):** the TRCB/SOFT-start fix CONFIRMED ON HARDWARE (comm-loss warm
  MOT_PWR re-close 1.041× physical, was 3.9×; reverse_block observed in soft-start;
  bleed τ to 0.02%); command replay proven at scale 1.00 by the V_SP_ZERO_THRESH bin
  scan (the I_cmd zero/nonzero boundary lands exactly on the firmware's 0.07 m/s —
  a constant the replay path never applies); replay-half vacuity 40.5% → 6.6%;
  soc-depletion A1 redesign validated (both gate arms independently green, latch
  270.704 s vs ~266 predicted, +1.8% fully explained by the rising pack current);
  duration trims cost nothing; the INA253 sense-side question (B1) was raised by an
  analysis agent and REFUTED same night against the schematic (output-side confirmed —
  sheets 1/2/4; margin claims stand). Fix round → 9612369: `share_loop_actuated`
  check kind (the share axis had ZERO checks across 122), `drive_min_frac` floors at
  ~half round-1 measured activity (a degraded command path now fails), i_cut band,
  `fault_first_t_whole_run` (the post-grace-scoped map mis-reads in-grace latch
  onsets), `switch_transitions`.
- **Round 2 (38/39):** the one FAIL exposed the scp-inrush KNIFE-EDGE — the sim's SCP
  cut (tick S+1 after the 8 ms TD_ON admission) races the firmware's OC teardown at
  S+L where **L = the observation round-trip = 1 or 2 ticks** (sub-ms host phase); the
  sim applies the observed switch word BEFORE stepping the solver, so a tie goes to
  the firmware. The celebrated 0.076% i_cut "repeat" was two draws of the same L=2
  coin. Plant trace bit-identical; board correct in both orderings. A headless bench
  proved the re-margin fix INFEASIBLE (a tick-S cut needs ~12.7 A = 1.49× RT_I_FOLD_HIGH
  — a hard short, not the SCP-margin case; the 5.0 A stimulus's claimed 15% fold margin
  also never existed — bench threshold ~5.53 A). Adopted instead (82c8f75): two-outcome
  `events_any_of` — A_fold_fired (1 scp_cut, i_cut 6.0–6.6, STRONGER) / B_fold_approached
  (0 cuts + MOT_PWR sw_ring 3.5–5.5 A + the OC latch, WEAKER) — the check names the
  outcome and tracks the L distribution instead of scoring a coin flip. The
  deterministic-fold path (stimulus TIMING redesign) is an open operator item.
  Everything else REPEAT CLEAN (comm-loss re-close 0.3696 A/ch EXACT; bringup peaks
  exact to 4 decimals).
- **Rounds 3–4 (39/39 both; round 4 ZERO structural diffs vs 3):** both branches of the
  two-outcome check validated live (L record across five campaigns: A,A,B,B,A —
  bimodal by mechanism). The handoff-sag cut-latency tracker (round-1 anomaly, −65%
  vs baseline) CLOSED with a corrected model: datapoint #5 (13.130 ms) broke the
  assumed [0,12) window and revealed the true one — uniform command-arrival phase over
  the **20 ms share tick** (all five points 2.850–13.130 ms fit [0,20); campaign-2's
  11.968 ms was never a distinct mode). Reopen only on a value ≥ 20 ms.
- **Tests: 712 passed + 25 numpy-skips (.venv_hil, five suites) / 756 (miniforge incl.
  test_hil_report_analysis).** All tooling; FW stays v23; wire protocol frozen.
- **Standing items** (unchanged unless noted): scp timing redesign (optional,
  operator); FU4 Idle→Run setpoint-arrival synthetic entry; Rs(SOC) calibration vs a
  real 2S pack (still sets soc_latch 0.113); early-exit guard (now minor); analyzer
  exe rebuild; .venv_benchlog pandas/scipy; Pi-bridge v4 parser audit.

---

## Status & session addendum (2026-08-31c, Round A: scp deterministic fold + FU4 synthetic replay entry)

Orchestrated tooling round (two parallel Opus implementers, independent Sonnet test-writer,
parallel Opus data-integrity + Sonnet contract reviews, orchestrator fix pass). Python
tooling + one committed data file + docs; FW stays v23; wire protocol frozen. Closes the
two operator-queued items from the ratification review: the scp deterministic-fold
stimulus redesign and FU4.

- **scp-inrush is now DETERMINISTIC — the two-outcome check is retired from the table.**
  Root cause of the old S+1 race (feasibility bench): the flat t=0 load faded in through
  the plant's 1.0 V Norton load floor (`V_MOT_LOAD_FLOOR`, hil_electrical.py:197), so the
  fold engaged ~1.3 ms after SOFT entry and the cut landed one tick past admission —
  racing the firmware's OC teardown at L=1/2. New three-phase stimulus (hil_plant_sim.py
  `SCP_INRUSH_*` block): the P3 ramp runs UNLOADED; a 6.5 A fold pulse steps in when
  V-MOT crosses `SCP_INRUSH_ARM_V` 1.2 V mid-soft-start (above the floor -> full current
  in one substep -> fold binds and CUTS INSIDE THAT SAME 1 kHz TICK, >= 600 us before any
  board word can arrive); a one-shot latch withdraws it (the 64 ms retry soft-starts
  clean to ON); a 5.0 A run load at +110 ms latches OC_FC deterministically. The load
  moved 5.0 -> 6.5 A because at 5.0 A the fold needed v_in > 15.2 V, which the P3 gate
  (13.5 V) does not guarantee. The one-shot re-arms on the observed mainState 99->non-99
  edge (review M1 — a forged-boundary warm reset re-runs bring-up and must get a clean
  phase-1 ramp, not a standing run load). `FAULT_EXPECTATIONS["scp-inrush"]` is
  single-outcome `events_require` again (count 1, where MOT_PWR); `events_any_of` STAYS
  in the codebase, table-unused, for future races.
- **VALIDATED ON HARDWARE + BAND DERIVED LIVE: i_cut = 6.3797373 A BIT-IDENTICAL across
  three live board runs** (fresh-boot cut at t~0.102; post-latch runs at ~0.602 behind
  the fw v23 500 ms recovery debounce; full cut->retry->ON->run-load->OC_FC->teardown
  sequence every time). Band pinned [6.15, 6.55] bracketing the headless substep sweep
  (6.256-6.398 over n_sub 8-100). The feasibility bench's 5.79-5.88 A figure was its own
  rig's bring-up-emulation artifact. A `provisional_note` expectation mechanism (renders
  a [PROVISIONAL: ...] qualifier into events_require check details) was added for
  not-yet-derived thresholds and the scp key deleted same-day once the band was measured.
- **FU4 — synthetic Idle->Run setpoint-arrival replay entry `SY0001`** (new SY prefix =
  synthetic, logs/SY0001.BLG, BLG v3/fw 23, 2500 records, committed + byte-deterministic
  from stdlib-only tools/gen_fu4_replay_log.py, sha pinned by test). Stimulus: v_sp held
  2.0 m/s from record 0 (doState1() zeroes v_setpoint on the transition regardless of
  payload, .ino:5382-5410, so the real setpoint structurally lands on the SECOND 50 Hz
  packet), step back to 0 at +1.5 s through the V_SP_ZERO_THRESH cutoff; v_actual pinned
  0 (isolates the setpoint stimulus; open-loop rail during the hold is EXPECTED per the
  suite's FU5 note). New check kind `steps_onto_rail_within` (|I_cmd| >= 11 A within
  0.15 s of the preamble boundary; budget includes the Run-transition packet the
  original 0.08 s spec missed, + packet-loss headroom note). Entry is `provisional` (no
  drive_min_frac until a first campaign measures the baseline, FU3 precedent). Suite is
  now 40 runs / 27 replays.
- **Review round:** 1 HIGH (H1 — the "no not_before_s/survive_to" derivation cited a
  0.7 s grace window; the constant is 2.0 s, and a require+not_before_s would FAIL
  against the post-grace-scoped fault_first_t, not vacuously pass — comment rewritten),
  3 MED (M1 re-arm above; M2 HIL_PLANT.md taught the retired flat load; M3
  provisional_note), 7 LOW + 2 contract findings — all accepted, all applied
  (orchestrator-applied directly; L1 rename deferred to a comment fix).
- **Tests: 738 passed + 25 skipped (.venv_hil, five suites) / 113 (miniforge
  report-analysis) — orchestrator-rerun.** New coverage: three-phase state machine incl.
  re-arm-after-reset, single-outcome band edges at the live values, events_any_of
  synthetic-table mechanism regression, provisional_note suffix mechanism,
  steps_onto_rail_within three branches, SY0001 sha/header/determinism pins.
- **Standing items CLOSED: "scp timing redesign (optional)" and "FU4".** Next rounds
  queued: Round B (DP-informed EMS routes 2+1 + the Gfc H2 metric — research digested,
  see the round report), Round C (scenario expansion: Y-profile EMS x4, FTP75 per
  strategy, MPPT tracking, +3 orchestrator proposals).

---

## Status & session addendum (2026-08-31d, Round B: DP-informed EMS + Gfc H2 metric)

Orchestrated tooling round (two sequential Opus implementers [Route 2 then Route 1],
independent Sonnet test-writer with a reconciliation pass, parallel Opus data-integrity +
Sonnet contract reviews, Opus fix round). Python tooling + docs; FW stays v23; wire
protocol frozen. Implements the operator's DP brief (routes 2+1) + the Gfc H2 transfer
function.

- **H2 metric (Gfc).** `H2Consumption` in hil_plant_sim.py: the PhD student's Gfc
  (== the commented-out H2_tf at references/EMS/DPtrial.m:51-52), ZOH modal/parallel
  first-order at 1 kHz (Tustin REJECTED — the 1.887e6 rad/s pole maps to z=-0.9997
  Nyquist ringing; tf2sos biquads REJECTED at 8.2e-3 err), update-then-read, input =
  STACK power (FuelCellSource v_terminal x i, not the bus-side product), ten pinned
  validation vectors at rtol 1e-9, import-time DC-gain assert (rel 1e-13) tripwires
  silent coefficient edits. CSV columns h2_rate_gps/h2_cum_g (simulated mode only,
  append-only tail) + exit summary. **SCALE PORTABILITY RESOLVED (operator ruling
  2026-08-31): the 720 in den[0]=1044=720x1.45 is the full-size FUEL CELL's OCV, and
  the TF needs NO adjustment — P_fc (W) in and g/s out both ride the system's energy
  scaling (references/Systemic_Scaling_of_Powertrain_Models_with_Youla_Driver_Control.pdf,
  Tan/Yadav/Assadian).** H2 figures are the model's estimate proper; surviving caveat is
  stack identification only (TODO(calibrate); DC gain implies eta 47.25% vs the DP's own
  55% static proxy, +16.4% — a model-choice note).
- **`soc-band` (Route 2)** — causal charge-sustaining EMS strategy: SoC0 capture,
  +/-SOC_BAND_HALF deadband, proportional share bias saturating at [0.25, 0.75], causal
  cruise gate (trailing window, never future profile points — operator ruling b), charge
  admission with dual hysteresis (i_tot 0.60/1.30 A; deficit enter-at-band-edge /
  hold-to-zero). SIM-ONLY flagged (fb["soc"] is plant truth outside
  FB_TELEMETRY_EQUIV_KEYS; V_batt-based estimation is the portable path, future work).
  Scenario `ems-soc-band` (61 s two-cruise-level profile, 1.0 A drain t=10-38,
  chg_i_ceiling_a 0.8, four signals_require). Route 2's own offline walk caught + fixed
  a real defect (a charge window admitted at the 1.5 m/s cruise -> single-source FC
  1.42 A > LIMIT_I_FC_MAX; drain end moved 35->38 s).
- **`dp-replay` (Route 1)** — offline-optimal benchmark: tools/gen_dp_ems_table.py
  (miniforge numpy) ports the MATLAB DP's STRUCTURE with three declared defect fixes
  (linear interpolation of J — nearest-grid quantized away ~99% of realistic steps;
  stored argmin policy; raise-on-infeasible), solves against the sim's nonlinear
  BatterySource (declared divergence from the constant-720V lossless MATLAB pack),
  stage cost on the Gfc DC gain, charging masked to cruise (ruling b), --lambda-dev
  default 0 (a running penalty re-ranks and broke the lower bound by 0.07% — measured),
  --match-terminal-soc bisection (residual +1.6e-6). Checked-in table
  tools/dp_tables/dp_ems_table_ems-dp-replay.csv (byte-deterministic; .gitattributes
  -text guards CRLF; header carries every consumed tunable) played through the 50 Hz
  commander by strategy `dp-replay` with startup refusals: profile fingerprint,
  charger-accounting vs resolved engine, and ten header-vs-live drift comparisons
  (three constants escape the fingerprint — measured by mutation). Scenario
  `ems-dp-replay` is hifi-only (accounting match; "any" would hard-fail a simple-pref
  campaign). Comparison surface: final_h2_cum_g/delta_soc scenario metrics in
  results.json/REPORT.md.
- **OFFLINE RESULT: DP -14.33% hydrogen vs soc-band at matched terminal SoC**
  (1.17564e-2 vs 1.37227e-2 g), and **the DP opens the charger on ZERO stages** — 
  share-shifting buys 0.405 SoC/gram vs the Ag105's 0.169; a finding, not a gap.
  **VALIDATED LIVE (first hardware execution of both):** soc-band 0.012842 g, dp-replay
  0.011640 g (-9.4% live; the DP's live total within 1.0% of its own offline
  prediction), both 61 s fault-free, share endpoints as designed (0.689 FC-biased vs
  the table's 0.250 rail).
- **Reviews:** contract 1 HIGH (the operator's scale-portability ruling needed a
  9-site sweep beyond the primary banners — applied everywhere incl. the regenerated
  table + REPORT renderer) + 1 MED; data-integrity 2 HIGH (same sweep; the standing
  .ino-flags commit exclusion) + 6 MED (accounting runtime guard; fingerprint drift
  guards; match-residual header lines + hard-fail without --allow-unmatched; the
  DC-gain assert; constants_hash changelog — the hash MOVED 2026-08-31, 20 additive
  names, pre-2026-08-31 hashes not comparable; deficit-gate hysteresis) + 9 LOW — all
  accepted, all applied. Table regenerated: sha256 08ddc077...; comparison numbers
  UNMOVED.
- **Tests: 811 passed + 27 skipped (.venv_hil, six suites incl. new
  test_gen_dp_ems_table.py) / 761 (miniforge incl. report-analysis) — orchestrator-
  rerun.** references/EMS/ now holds the PhD student's MATLAB (DPtrial,
  DP_EnergyManagement2, NEW SDP_EnergyManagement2 + TPM.mat — stochastic-DP source
  material for a future round); the ~330 MB simulink_pdem_output_stochastic_*.mat
  outputs are gitignored, local-only.
- **Next: Round C** (scenario expansion: 4 synthetic Y-profile EMS scenarios spanning
  {0.30/0.70 vs 0/1 share band} x {1 vs 3 m/s Vmax}; FTP75 scaled to 3 m/s peak per
  EMS strategy; Ag105 MPPT-tracking emulation; +3 orchestrator proposals). The SDP
  material suggests a future stochastic-DP route beyond Round C.

---

## Status & session addendum (2026-08-31e, Round C: scenario expansion — Y-profiles, FTP75, MPPT, watchdog, staircase, charge-to-full)

Orchestrated tooling round in two implementation waves (Opus x2), independent Sonnet
test-writer (synchronized hold-and-reconcile across the fix round), Opus data-integrity +
Sonnet contract reviews (the latter with two verification sub-agents), Opus fix round.
Python tooling + committed data + docs; FW stays v23; wire protocol frozen. Ten new
scenarios (15 -> 21 registered; plan 52 runs), two prerequisites, five check-kind
extensions, one datasheet correction, one open hardware question.

- **Prerequisites:** per-scenario `ems_run_exit_s` (module run-exit constants would have
  ended a 350 s cycle at t=55) and generic `aux_preload_a` (ramped; import-assert refuses
  it on bespoke-branch and dp-replay scenarios — the DP fingerprint does not cover it,
  deferred until a second DP table lands). Existing scenarios byte-identical.
- **Four `ems-y-*` scenarios**: the firmware's 16-region State-98 'Y' COMBINED_PROFILE
  (.ino:3162-3179) transcribed verbatim (assert-pinned, 40000 ms) with
  `advanceComboRegion()` semantics reproduced exactly (clip AFTER interpolation), one
  factory over {b 0.30/0.00} x {Vmax 1/3}. Split-by-band objectives: b30 + 0.60 A preload
  = genuinely closed-loop share tracking; b00 unloaded = setpoint-latch cut/restore
  topology coverage — the RESTORE assertions are the suite's first-ever latch-release
  checks. **Live: BT cut 22.021/restore 23.503, FC cut 34.311 (predicted 34.31)/restore
  36.51 — millisecond agreement, fault-free.**
- **Two `ems-ftp75-*` scenarios** (hold-5050, soc-band) on the FIRST 340 s of the EPA
  FTP75 (operator-directed, matching references/Systemic_Scaling_...pdf; the cut lands in
  a native standstill, 0 mph from t=333). Raw ftpcol.txt committed under
  references/drive_cycles/ (sha-pinned, .gitattributes -text guards autocrlf — review M2)
  -> stdlib generator -> generated tools/ftp75_profile.py (234 points, err 4.4e-16,
  import-bound to its generator's constants so a stale/hand-edited module is an
  ImportError — review M3). Peak 56.7 mph @ t=240 -> 3.0 m/s. FTP75_PRELOAD_A 0.65
  (closed-loop gate 100% of the run). socband variant allows OC_FC (ruling b; mechanism
  is the share-bias-at-peak transient — the preload forecloses the charge window, NOT the
  spec'd charging path). Suite gate `--with-ftp75` (default OFF; SKIP records; +11.7 min).
  DP-table variant deferred (~21 min offline; generalizations landed).
- **Ag105 MPPT CORRECTED + EMULATED; open hardware question R1.** Datasheet p.10: the
  MPPT is an INPUT-VOLTAGE-THRESHOLD regulator (default 18 V, MPPTS open), NOT
  perturb-and-observe — CLAUDE.md §3 corrected (see the dated note there), the two stale
  .ino comments (:10029, :10047) deferred to the next firmware round. Threshold gate
  emulated behind `mppt_emulation` (default False, existing traces byte-identical). NEW
  scenario `mppt-tracking` (mppt-harvest strategy, cruise + braking charge windows):
  **the predicted release/re-assert HUNT is CONFIRMED ON HARDWARE — 138 MPPT_DISABLE
  toggles, ~40 ms period (the "80 ms" first recorded here was a mis-derivation —
  corrected by the 2026-08-31 campaign's measured 40.05 ms median, which the
  toggle count itself requires), status 0x09 released-and-refusing observed.** Under the
  datasheet-default threshold, cruise harvest CANNOT hold on a 15.95 V bus: if no MPPTS
  resistor is fitted (R1, operator to check the MPPTSEL header), the real charger hunts
  the same way and the fix is firmware writing reg 0x02 (~12 V).
- **`pi-silence`**: the Pi watchdog's FIRST-EVER exercise — injection alive, commands
  muted at t=8 (PiCommander.mute_after). **Live: carried-in latch cleared at 0.501 s,
  watchdog re-latch at 8.498 s (PI_TIMEOUT_MS 500 + phase), motor halted, State 99 held**
  (injection alive -> no fw v23 run boundary -> latch persists, as derived). New
  `child_tx_healthy` check (shared child_stream_continuity() with the --pi-live excusal)
  is the PI_TIMEOUT-vs-HIL_STALE discriminator (same 0x8010 bit; error_code still not on
  the observation frame — standing protocol item).
- **`share-staircase`**: two-phase characterization (governor rails at 1.2 A: I_fc swept
  0.915 -> 0.300 live vs predicted 0.90/0.30; cut/restore excursions at 0.55 A). New
  `switch_fall_latency_ms` check kind (+ edge:"rise") turns the closed handoff-latency
  tracker into per-campaign measured data — live latencies 16/15/4/17 ms, all in the
  [0,20)+L model. Premise corrected in-source: the 20 ms is COMMAND-ARRIVAL phase
  (PI_CMD_HZ 50), not a firmware tick (SHARE_CTRL_TS_US is 1000 us).
- **`charge-to-full`**: first-ever FULL/CV coverage (suite --soc0 0.990 override). **Live:
  GENSTAT FULL at t=100.32 (predicted ~100), CV flag, full taper, FC_CHARGE held open —
  the firmware's documented no-action-on-FULL baseline asserted positively.**
- **Check-kind extensions** (all with import-shape asserts): aux_bit, value_mask/
  value_equals (closes the hex-string ag105_status float() silent-skip trap),
  signals-side max_value (unmeasured FAILS), switch_fall_latency_ms, child_tx_healthy.
  Plus: strictly_decreases_by windows must clear pi_timeline entries by >= one command
  period (review H2 — the staircase check opened ON its stimulus and lost the 50 Hz
  phase race ~19/20), max_ticks-only bit specs need a companion or vacuity_note, max_ms
  specs refuse stray tick bounds. `run_hil_suite --list` cp1252 crash fixed permanently
  (stdout/stderr utf-8 reconfigure + the two replay-description arrows -> ASCII).
- **Reviews:** data-integrity 2 HIGH (the standing .ino staging exclusion; H2 above) +
  4 MED (M1 mppt toggle ceiling re-derived 10000->2200 vs the reachable 3000; M2
  .gitattributes; M3 generator binding; M4 dp-replay/preload guard) + 9 LOW; contract
  (with sub-agents): Y-table CLEAN row-by-row (both reviewers independently), 3 MED
  (two .ino citation fixes; constants_hash changelog — 19 additive names enumerated by
  running the collector, pre-Round-C hashes not comparable) + LOWs. All accepted, all
  applied.
- **Tests: 927 passed + 27 skipped (.venv_hil, six suites) / 1233 (miniforge, all
  tools/) — orchestrator-rerun.** Live smokes: all six board-testable new scenarios ran
  against fw v23 with the designed outcomes (details above); the four ems-y/ftp75
  variants not smoked live (b30-v1, b00-v3, both ftp75) exercise the same code paths.
- **Untracked, other-session-owned, deliberately NOT committed:** tools/tpm_generator.py
  + test, references/EMS/TPM_{fullsize,scaled}.mat + TPM_generator.m + Pdem_cycles/ +
  generated/ (and the Round-B TPM.mat is deleted in that workstream), docs/
  HIL_SCENARIOS.md, PSCAD/. The owning session should commit them.
- **Next:** first full campaign over the 52-run plan (the new entries' modelled
  thresholds calibrate there); R1 answer (MPPTSEL header) settles the mppt-tracking
  expectation + the reg-0x02 firmware question; FTP75 DP table when wanted
  (--with-ftp75 + ~21 min offline solve).

---

## Status & session addendum (2026-08-31f, TPM toolchain: Markov demand-transition generator)

Parallel EMS-strategizing session's round, committed and recorded here by the SDP session
that consumed it (the TPM session deferred its addendum). Commit db6e7ce; Python tooling
only, FW stays v23.

- **tools/tpm_generator.py (miniforge numpy/scipy; NOT .venv_hil):** Python port of the
  PhD student's references/EMS/TPM_generator.m. Decodes the ten opaque MCOS Simulink
  Pdem cycle files (~315 MB, gitignored, sha256es pinned in the sidecars), replicates
  MATLAB interp1-spline/discretize/colon semantics, and at dt=1.0 reproduces
  TPM_scaled.mat BIT-IDENTICALLY (`--validate` gate; sE cancels under normalization so
  TPM_fullsize.mat is the same matrix). Library API: load_pdem_cycle, build_tpm,
  rescale_gamma (gamma_eff = gamma_base**(dt/dt_base)), matlab_discretize, SM/SL/SE.
  104 tests (tools/test_tpm_generator.py, miniforge pytest).
- **Artifacts in references/EMS/generated/** (each with a .provenance.json sidecar):
  `TPM_dt1_hil.mat` is the primary SDP input — 25x25, `--hil` preset (V2 dropped as a
  bit-identical duplicate of V1, V3 truncated to its native 600 s, cross-file boundary
  transitions excluded, empty rows = self-transition), 0 zero rows, diagonal mass 76.2%.
  Also dt0p5, and parity artifacts incl. TPM_scaled_dt0p02.mat (99.0% diagonal — why
  20 ms is the wrong decision step). Sidecars carry the UNITLESS contract: bins
  partition normalized [0,1]; the CONSUMER owns energy scaling via
  `normalization.p_dem_scaled_min_w/max_w` (-1.1248/+1.6398 W), clamping out-of-range
  to end bins. Sidecar JSONs are LF-normalized with a `* -text` .gitattributes (SDP
  round fix MED-1) so recorded hashes are checkout-independent.
- docs/HIL_SCENARIOS.md (suite scenario catalog) landed with this round.

---

## Status & session addendum (2026-08-31g, SDP EMS strategy: sdp-v1 + ems-sdp + H2 proxy)

Orchestrated tooling round (two parallel Opus implementers, Sonnet test-writer x2 rounds,
parallel Opus data-integrity + Sonnet contract reviews, sequenced fix rounds). Python
tooling + docs; FW stays v23; wire protocol frozen. Ports the PhD student's
references/EMS/SDP_EnergyManagement2.m onto the HIL sim, consuming the TPM toolchain.

- **tools/sdp_ems_solver.py (new, miniforge):** infinite-horizon value iteration over
  (SoC grid 101 pts [0.55,0.65] x 25 TPM demand bins) from TPM_dt1_hil.mat + sidecar
  (min/max read at solve time per the operator ruling), gamma 0.95 via rescale_gamma,
  declared decisions D1-D10. **D1 is load-bearing: per-1s-step |dSoC| is 4.4e-5 vs 1e-3
  grid spacing, so nearest-grid transitions (the MATLAB's min-abs rule) move NOTHING —
  measured: the un-interpolated policy is share=0 everywhere.** J is linearly
  interpolated over SoC (the Round-B DP fix, again). **alpha re-derived 500 ->
  0.2569444** via coulombic-energy scaling (500 x (7.4V x 5Ah)/(720V x 100Ah)) — the
  marginal rate preserving the full-size trade-off; the level-form alternative (0.01367)
  is measurably degenerate (share=0 everywhere; --alpha-mode level keeps it reachable).
  Actions: 21-step share ladder x charge_goal {0,1}; operator ruling (b) baked as
  charge_forbidden_bins 12-24 (dwell-quantile 0.90 + an FC-budget rule). Converged 455
  sweeps, delta 9.8e-13. Bakes tools/sdp_policies/sdp_policy_v1.json (schema
  sdp-policy-v1; policy-block sha256 dbe42d1b... — the STABLE identity; the byte sha
  moves with generated_utc on every --force, never pin it).
- **sdp-v1 strategy (hil_plant_sim.py, stdlib):** SIM-ONLY (fb["soc"] is plant truth).
  SoC0-RELATIVE regulation (soc_rel = 0.6 + soc - soc0, soc-band's capture convention)
  so ems-sdp runs at default soc0 0.7 and is three-way comparable. 1 s decision ZOH
  under the 50 Hz commander. P_dem = V_bus x (I_fc + I_batt) (telemetry-equivalent keys
  only), normalized via the artifact's sidecar-derived min/max, END-BIN CLAMPED —
  **real bus demand (~1-20 W) exceeds the ideal-scaling range (-1.12..+1.64 W), so
  residency pins to bin 24 in practice; counted and reported, a scale-fidelity boundary
  not a bug.** **Hardware-envelope share clamp [0.15, 0.85]** (soc-band's exact clamp;
  fix round): the raw table rails at 1.0, which cuts BT_BUS and runs single-source FC
  into LIMIT_I_FC_MAX (OC_FC at ~13 s, run truncated — the original design, reworked).
  Clamped: governed I_fc 1.16 A at the 1.45 A drain peak, 17% OC margin, fault-free
  full-length run; last_share_raw + clamp counter keep the rail visible. Loader
  validates finiteness + ranges (a NaN share would otherwise emit 0.15 via max()
  semantics; a raw NaN charge_goal diverges logged-vs-board state). Per-run provenance:
  bind_scenario() shas the artifact; meta sidecar gains config.sdp_policy for sdp-v1
  runs. Known documented degeneracy: the SoC-grid FLOOR node (row 0) commands share 0.0
  (D3 clamp-tie, tie-break picks least-hydrogen) — unreachable in ems-sdp (needs 0.05
  SoC fall vs ~0.006), pinned by test.
- **h2_sdp_cum_g CSV column:** the student's static proxy P_fc_stack/(0.5 x 120000),
  same clamped input as the Gfc integrator by construction (one step(), one reset());
  proxy under-reads Gfc ~5.5%. Suite metric final_h2_sdp_cum_g alongside final_h2_cum_g.
  The solver's J is BUS-side P_fc; never difference a J against a logged hydrogen total.
- **ems-sdp scenario:** stimulus IDENTICAL to ems-soc-band (same profile list object,
  duration 61 s, ceiling 0.8 A, drain branch) — the comparison set is now
  soc-band (causal heuristic) / sdp-v1 (causal optimal-policy) / dp-replay (non-causal
  bound) on one stimulus. FAULT_EXPECTATIONS: fault-free, survive_to t=50, five signal
  checks incl. cmd_share_sp >= 0.84 (discriminates vs 0.75 and 0.50) and I_fc >= 1.00 A.
  Charging is structurally unreachable here (bin 24 is forbidden) — asserted, not hoped.
- **Reviews:** contract — 1 MED (undeclared convergence-ordering deviation -> D10: the
  MATLAB's break-before-update keeps a one-sweep-stale J, likely its own bug) + the
  floor-node banner falsity + gamma dt_base note; data-integrity — 4 MED (checkout-
  dependent sidecar sha -> LF + -text fix; missing per-run artifact recording; the alpha
  rationale's "~31x smaller" was wrong in VALUE AND DIRECTION (per watt-second the rig
  moves 1946x MORE; the true figure is the 18.8x per-stage ratio) -> artifact
  regenerated; loader finiteness/range) + LOWs incl. the .gitattributes overclaim. All
  accepted, all applied. Reviewer perturbation sweep: the charge decision is ROBUST
  (600 charge cells under +/-5% alpha, 0.5-0.9 A ceiling, 12-16.5 V bus, -20% capacity;
  flips only at 1.2 A where the FC-budget rule forbids all) — supersedes the
  implementer's "knife-edge ~1.07" impression.
- **Tests: 984 passed + 26 skipped (.venv_hil five-suite set) / 147 (miniforge:
  sdp_ems_solver + gen_dp_ems_table + tpm_generator) / 113 (report-analysis) —
  orchestrator-rerun.** Provenance pins: tpm.sha256 + sidecar sha vs the tree, the
  policy-block digest, the floor-node exception.
- **Untested residuals (declared):** bind_scenario's banner/ignored-args, the solver's
  load_sidecar error branches.
- **Next:** full campaign (all scenarios incl. --with-ftp75) with live
  hil-agent-analysis, then a higher-level utility evaluation of the HIL suite for the
  EMS-testing mission (operator-queued in this round's brief).

---

## Status & session addendum (2026-08-31h, campaign 191509: first full post-A/B/C+SDP campaign + suite evaluation)

Full 53-run campaign (`--with-ftp75`; drive operator-gated SKIP) live-analyzed under
the hil-agent-analysis skill (10 per-run agents + adversarial replay audit + tool
pass). **52 PASS / 0 FAIL / 0 INCONCLUSIVE — every scenario verdict recomputed
right-for-the-right-reason; zero scoring defects; zero board defects.** Ledger:
`HIL Results/hil_report_20260831_191509/HIL_FINDINGS.md`; digest HIL_SUMMARY.md;
program evaluation `HIL Results/HIL_SUITE_EVALUATION_20260831.md`.

- **EMS lever pricing hardware-measured on two independent stimuli:** share-shift
  0.409-0.415 SoC/g (61 s cycle AND 340 s FTP75, 2.3% apart; offline 0.405);
  Ag105 charging ~0.156 SoC/g (offline 0.169) — charging confirmed the ~2.6x
  worse lever. h2 totals repeat Round-B smokes to <0.05%.
- **Three-way EMS on one stimulus:** sdp-v1 0.0125424 g/-0.00166 SoC beat soc-band
  0.0128475/-0.00206 on both axes; dp-replay 0.0116403/-0.00203 (-9.40%);
  dp-vs-sdp sit on the same frontier (equivalent-H2 0.003% apart). HONESTY:
  sdp-v1 emitted a constant clamped 0.85 (demand pinned to TPM bin 24 ~98% of
  decisions under the ruled sidecar map) — plumbing/provenance validated, policy
  interior unreachable. Operator decision queued: re-normalized consumer demand
  map (+ re-solve) vs accepting a constant-0.85 benchmark leg.
- **Firsts validated:** scp i_cut 6.3797373196569644 A now 4/4 bit-exact; fw v23
  any-fault recovery cleared a carried ERR_PI_TIMEOUT (fw v22 would have refused);
  latch-RESTORE both channels/directions; watchdog latch triple-attributed
  (485-vs-250 ms discriminator); FULL/CV repeat to 0.01%; MPPT hunt reproduced;
  FTP75 drive tracking p95 2.96 mm/s incl. the 3 m/s peak; observation round-trip
  floor L ~= 1.9 ms measured; SY0001 rail step 27.92 ms vs 150 ms budget.
- **Fix queue (ranked, in the ledger): 5 MED** — ems-sdp coverage companion;
  dp-table sidecar provenance block; cmd_* CSV column semantics doc (columns move
  at the NOMINAL timeline instant, not the send tick); uv_not_latched on
  TP0178/TP0201 vacuous-untagged (+ the TP0178 "10 ms dwell" record correction);
  fc_bus_restored knife-edge (min_ticks 1500 = 100% of its window — one dropped
  frame fails a correct board) — **plus LOWs** (FTP75 threshold bands + preload
  budget -2.6%; socband_fc_carried re-derivation (governor falsifies its idle
  justification); Y_AUX_LOAD_A ~0.85 for a deliverable b30 bound; SY0001
  drive_min_frac 0.30 de-provisionalization; first-boot fault-bit variability
  note (0xA010 this time — third distinct signature); key_metrics warm-reset
  label). The mppt "80 ms" record error is corrected in place (true period 40 ms).
- **Suite evaluation verdict** (full document in HIL Results/): ready TODAY for
  relative EMS ranking (Mode A) + firmware preemption; one audit away (Pi v4
  parser) from Mode B; one calibration away (Gfc stack identification) from
  absolute H2 prediction. Recommended order: fix round -> Pi parser audit ->
  Mode-B EMS-trio campaign -> SDP re-normalization -> measured-droop sim mode ->
  stack ID.

---

## Status & session addendum (2026-08-31i, fix round + SDP demand-map re-normalization: sdp_policy_v2)

Orchestrated tooling round (two sequential Opus implementers, Sonnet test-writer, parallel
Opus data-integrity + Sonnet contract reviews, Opus fix round) implementing the
campaign-191509 fix queue AND the operator-approved SDP scale-gap fix. Python tooling +
docs; FW stays v23; wire protocol frozen.

- **SDP demand map is now CONSUMER-OWNED at rig scale (solver decision D11).**
  `sdp_ems_solver.py --demand-map MIN MAX` (default **[0, 25] W**, from campaign-191509
  measured P_dem 0–22.887 W; `--demand-map-sidecar` keeps the old path and reproduces
  v1's policy block BIT-IDENTICALLY — the re-map is provably the only change). Re-solved
  → `tools/sdp_policies/sdp_policy_v2.json` (455 sweeps; policy-block sha
  `740c802e99dd…`; charge_forbidden_bins [12..24]→**[6..24]** — the FC-budget rule
  finally binds at real watts; 294 charge-enabled cells vs v1's 0; share ladder
  {0, 0.90, 0.95, 1.00}). Strategy renamed **`sdp-v1` → `sdp-v2`** (no alias — a
  results.json can never silently mix laws); alpha unchanged (map-invariant). Offline
  walk over the campaign trace: **13 demand bins visited (v1: 1), zero clamps, a
  charge window t = 41–58 s** that v1 structurally could not produce. HONESTY: the
  emitted share is STILL a constant 0.8500 — every table value exceeds the [0.15, 0.85]
  hardware clamp; the bang-bang is structural (piecewise-linear stage cost → vertex
  optima). Discriminators are therefore (a) the new **`cmd_share_sp_raw`** CSV tail
  column (pre-clamp table request; None-seeded, blank until the first decision) and
  (b) the **FC_CHARGE switch actually opening** — both scored in the re-derived 8-check
  ems-sdp entry, whose three new checks carry a `provisional_note` (first-campaign
  thresholds; rendering extended so provisional qualifiers ride signals_require too,
  not just events). ⚠️ Derived prediction: **~1 Hz FC_CHARGE chatter** (memoryless
  policy, no hysteresis; charger draw pushes demand into a forbidden bin) — within all
  current budgets; hysteresis is an operator decision if the first v2 campaign shows it
  undesirable. ⚠️ Campaign-191509 sdp-v1 EMS totals are a DIFFERENT DECISION LAW — never
  quote them against v2 runs.
- **Fix queue: all 16 items landed.** Highlights: `config.dp_table` sidecar provenance
  (file sha + LF-normalized data-rows-only `table_sha256`, positional header exclusion);
  TP0178/TP0201 uv_not_latched de-vacuated via new replay check kind
  `v_bus_min_in_band` (12.0, 12.30] — and the TP0178 record CORRECTED: the "10 ms
  dwell" did not survive replay (V_bus floor 12.1489 V is ABOVE the limit, dwell
  0.0 ms); `fault_latched` gained `not_before_s` (ML0217 0.5 s) computed from the
  PERSISTED latch only (review DI-MED-4: the raw whole-run first sighting reads a
  predecessor's carried-in latch and would false-FAIL a back-to-back rerun);
  share-staircase fc_bus_restored 1500→**900** (the 60 % restore-margin rule; measured
  1500/1500 = knife-edge); socband_fc_carried 0.55→**0.95 A** re-derived
  peak-over-window (review DI-MED-1: 0.70 was beaten by the constant-0.50 sibling's own
  0.8275 A window peak); **Y_AUX_LOAD_A 0.60→0.85** (b30 bounds deliverable for the
  first time — at 0.60 BOTH bounds were structurally unreachable) with `_Y_FC_BIAS_W`
  narrowed to R3 and `_Y_FC_FLOOR` re-derived FROM MEASUREMENT to {1.0: 0.50,
  3.0: 0.66} (the modelled {0.58, 0.80} would have failed a correct board — campaign
  true-run R3 peaks 0.5659/0.7606 A); FTP75 h2 totals now two-sided bands as TWO specs
  each (a new import guard REFUSES min_value+max_value on one spec — `_judge_signal_leaf`
  tests min before max and silently drops the ceiling); SY0001 de-provisionalized
  (drive_min_frac 0.30); mppt 40 ms record fixed in the three prose docs too;
  key_metrics label; first-boot variability + charge-sag doc notes.
- **Reviews:** contract lens 2 MED + 1 LOW; data-integrity lens **5 MED + 8 LOW, no
  HIGH** — every finding accepted except the cmd_share_sp_raw analysis figure (queued).
  The data-integrity lens recomputed every changed threshold against the campaign CSVs
  and reproduced the v2 artifact bit-exactly from source; both reviewers confirmed the
  rename sweep, the no-laundering rule, and the CRLF-safety of the new digests.
- **Tests: 1042 passed + 26 skipped (.venv_hil, five suites) / 272 (miniforge, four
  suites) — orchestrator-rerun.** ~50 new tests across solver CLI/artifact pins, digest
  stability, check-kind branches, import guards, provenance blocks, and the
  carried-in/persisted regression.
- **`WORK_QUEUE.md` (repo root, NEW)** is the operator-facing queue: SDP interior
  scenario round (S1 soc_ref-offset FTP75 flip, S2 charge-and-cross limit cycle,
  S3-partial braking-heavy cycle; S4 demand-above-FC-max TABLED pending solver
  action-feasibility masking; true regen harvest TABLED pending the regen-fidelity
  model), **fw v24 dynamic Ag105 MPPT threshold** (operator ruling 2026-08-31: droop
  sags the bus, so reg 0x02 must track dynamically; EPROM-wear budget + hysteresis
  deadband + power-gated writes + ~12.3 V floor; R1 MPPTSEL check still gates the
  value; also fixes the two stale P&O .ino comments), Pi-bridge v4 parser audit →
  Mode B, measured-droop sim mode, Gfc stack ID, FTP75 DP table, and standing
  housekeeping.
- **Next:** first v2 campaign calibrates the three provisional ems-sdp checks and
  observes the predicted chatter. Overnight autonomous plan authorized by the operator
  (2026-08-31): work WORK_QUEUE.md, judgment calls via a Fable-high + Opus-xhigh
  decision pair adjudicated by the orchestrator, up to five suite+analysis+fix cycles
  on the current fw v23 flash, fw v24 prepared but NOT flashed; decisions and findings
  in OVERNIGHT_LOG.md.

---

## Status & session addendum (2026-09-01a, fw v24: dynamic Ag105 MPPT threshold — PREPARED, NOT FLASHED)

Overnight autonomous firmware round (operator-prescribed dual-design decision pair:
Fable-high + Opus-xhigh, orchestrator-adjudicated; then implementer → test-writer →
two-lens reviews → fix round). **fw v24 (commit 128dc40; NOT flashed — the board ran
fw v23 all night; flash requires the usual HIL_SIM edit).** Ledger row 24.

- **Both designers independently resolved R1 from Table 7's own encoding:** reg 0x02
  values 0–250 select register mode, ≥251 the MPPTS resistor — a firmware write
  overrides any fitted resistor, so R1 is documentation, not a design dependency.
  Both also found a LATENT TELEMETRY BUG: below-threshold refusal makes ALL Ag105
  measurement registers read 0xFF (DS §2.11.5), which pollAg105() converted to a
  bogus I_charge = 2.805 A — fixed (0xFF sentinel → I_charge 0, ag105MeasUnavailable
  flag).
- **Adjudicated design:** V_chg (pin 38) windowed-MINIMUM tracking, sampled only
  while FC_CHARGE powers the charger; target = V_chg_min − 3.0 V quantized DOWN,
  clamped to counts [15 = 12.320 V floor, 27 = 13.376 V ceiling] — the ceiling is
  static_assert-anchored to V_BUS_CHARGED_THRESH minus the RT1987 ideal-diode path
  drop (~35 mV servo, NOT a PN Vf — reviewer's 0.4 V assumption corrected), the
  formal no-hunt invariant. Monotone-lower session ratchet (≤2/session, 30 s apart,
  deadband 3 counts, ≤8 physical writes/boot counted AT ATTEMPT + a boot-scoped
  fail gate — the safety review's H1: the original budget missed failing writes and
  refilled on charger power cycles). reg-0x07 cross-check discriminates the 0xFF
  read ambiguity; VERIFY treats a 0xFF readback as undecidable (M1 — else the
  flagship first write self-scores as failure and disables harvest). MPPTD-disabled
  charge semantics are UNVERIFIED on hardware (the two designers read the datasheet
  OPPOSITELY) — so no release-logic semantic change shipped; a 1 s MPPT_DISABLE
  release holdoff bounds any residual hunt to ≤1 Hz under either reading, with
  Fable's ag105ReleaseOk() proposal recorded as the upgrade pending a bench step.
  Layered UV protection: firmware backoff closes FC_CHARGE at 12.8 V/15 ms dwell
  (hover-band protection — it CANNOT pre-empt the 20 ms UV latch on a fast
  collapse, and says so), resume 13.6 V, gated vs busHotPlugUnsafe + the share
  latch (Death-5 conservatism). HIL observation frame 16 → **17 B** (mppt count at
  offset 15, live-mirrored per tick under HIL_SIM); State-98 **'N'** command; 'S'
  dump block; the two stale P&O comments corrected. EPROM endurance is NOT in the
  datasheet — TODO(verify: Silvertel); the structural lifetime bound is ~236 writes.
- **Reviews:** safety 1 HIGH + 7 MED + 8 LOW; correctness 1 MED-HIGH (the HIL
  mirror was one-shot; now live) + the mock_wire transaction counter (the zero-Wire
  tests were structurally vacuous) — all applied. test/mppt_assert_probes.sh pins
  the static_asserts (compile-fail mutation probes, 6/6).
- **Tests: 3787 production + 175 bench + 4268 HIL — all green, orchestrator-rebuilt.**
- **Tooling lockstep NOT yet done** (deliberately): the simulator still emulates the
  fixed 18 V threshold and does not parse the 17 B frame — a pre-flash tooling round
  (frame length-detection, mppt_emulation reads the observed count, mppt-tracking
  expectation flip to ≤6 toggles + threshold-band checks) is REQUIRED before the
  first fw v24 HIL campaign. Queued in WORK_QUEUE.md.
- Operator items: R1 MPPTSEL inspection (now documentation-grade); the MPPTD-
  disabled-charge bench verification; flash order per WORK_QUEUE.

---

## Status & session addendum (2026-09-01b, overnight campaigns 1–4: sdp_policy_v3, the charge-economics finding, interior scenarios, frontier check)

Overnight autonomous session (operator instructions 2026-08-31 evening; full decision
log in OVERNIGHT_LOG.md; commits d5d72e3 → 9cbf83c → 128dc40 → 6971a73 → 1ba2bd9 +
the close-out). Four full campaigns on the fw v23 flash, each live-analyzed under the
hil-agent-analysis discipline; two dual-agent decision pairs; zero board defects all
night.

- **Campaign 1 (222036, 53/53):** second fully-green campaign; first on sdp_policy_v2
  — every offline-walk prediction confirmed to the digit; the predicted FC_CHARGE
  chatter MEASURED (9×1 s windows, 2.0125 s period, 4.63× harvest loss); three-way
  eq-H2 dp 0.011567 < sdp-v2 0.011773 (+1.79 %) < soc-band 0.012852; replay audit
  0 untagged-vacuous (was 7.5 %) and caught the fix round's own ML0217 wrong-gate
  attribution (P0/300 ms, not P1/800 ms — re-anchored to an elapsed-from-State-0
  band). Chatter ruling: 8 s min-dwell hysteresis, consumer-side.
- **Campaign 2 (000816, 53/53):** hysteresis validated to the digit (2 windows /
  15086 ticks; harvest 7.72×; the self-load-subtracted bin proven by a double-dwell
  window) — **and it exposed that Ag105 charging is LOSS-MAKING at rig scale**:
  sdp-v2 fell off the frontier (+12.78 % over the DP bound, worse than soc-band;
  implied lever 0.2364 SoC/g vs the 0.41 exchange rate; the DP charges on ZERO
  stages). No check asserted frontier position — 15/15 passed. Decision pair #2:
  both agents REFUTED the loss-chain hypothesis (the levers' hydrogen basis
  cancels; the model is CONSERVATIVE about charging) and converged on the true
  defect: **the ported α sets a SoC shadow price (α/(1−γ) = 5.14 g/SoC) whose
  admission threshold the added charge control was never tested against** — the
  ported invariant came from a MATLAB source with no charger. Ruling:
  **sdp_policy_v3** — α re-derived by two-sided lever calibration ((1−γ)/√(L_share·
  L_chg) = 0.1629624, from the solver's own constants; window tripwire asserts α
  inside both admission windows), charging rejected ENDOGENOUSLY (0 cells; share
  map identical at operating rows; sha 0443febf…); v2 kept BYTE-FROZEN as the
  demonstration artifact for the dynamics scenarios (frontier_eligible False,
  banner-rendered). Revisit condition: charging returns on its own if the charger
  lever ever exceeds 0.31 SoC/g (e.g. post-fw v24). **Standing rule (new): any
  control ADDED to a ported objective must be checked against the shadow price the
  port's α implies.**
- **SDP interior scenarios (operator-approved S1/S2/S3) + EMS frontier check
  shipped** (6971a73): `soc_ref_offset` strategy parameter; ems-ftp75-sdp (S1,
  δ +0.013 above target → mid-run share flip), ems-sdp-cross (S2, downward
  crossing + charge-threshold limit cycle — the UPWARD share crossing is infeasible
  on this artifact: the two switching surfaces sit one grid node apart and crossing
  up inside a dwell needs 2.4 A single-source FC), ems-sdp-braking (S3,
  decel-plateau charge windows; HONEST caption — SoC rise is FC-fed, regen power is
  floored in the plant). EMS_FRONTIER cross-run eq-H2 check (≤0.98× soc-band,
  ≤1.06× dp; KNIFE-EDGE λ-band; exit-affecting UNVERIFIED split — the combined
  review's H1 caught that the first version failed clean --pi-live campaigns).
  FTP75 DP table baked (dp_ems_table_ems-ftp75-5050.csv): **DP vs soc-band −0.01 %
  at matched terminal SoC — the DP's advantage lives on the low-demand cycle, not
  the drive cycle.**
- **Campaign 3 (024231, 55/56 + 1 scenario-gap FAIL):** the frontier check's first
  live PASS — **the v3 leg landed ON the DP bound (1.0000×) and beat soc-band by
  10 %**; ems-sdp h2 matches the campaign-191509 share-only leg to **8 ppm** (two
  artifacts, identical command, identical energy); the artifact's two switching
  surfaces measured on hardware within 1e-5 SoC of their grid nodes; S1's flip
  landed at 198.5 s vs the walk's 195.9 (+1.35 %). The FAIL was S2's phase-locked
  absence check: the walk's limit-cycle period was wrong 5.7× — root cause: **below
  the 0.55 A gate the firmware runs OPEN-LOOP HOLD and delivered share 0.1656
  against the commanded 0.85** (designed behavior; now a documented
  strategy-authoring rule — walks must model the hold). Frontier honesty caveat:
  the vs-bound arm is STRUCTURALLY ~1.0 for charge-free candidates (both points
  differ only along the share lever, and λ IS that lever's rate) — it detects
  lever-class deviations (as in C2), not optimality; do not tighten it on
  charge-free readings. Calibration round (1ba2bd9): phase-free replacement checks
  (new `max_continuous_ticks` + `edge_count_between` kinds), all S1/S2/S3 pins
  de-provisionalized from measurement, three new OC-margin tripwires (S3's dwell
  overhang peaks I_fc 1.2617 A — the suite's tightest margin, 9.9 %, now asserted).
- **Campaign 4 (validation of the calibrated stack)** — results in OVERNIGHT_LOG.md's
  morning digest.
- **Repeatability ledger across the night:** comm-loss re-close 0.3696 A/ch
  8-for-8 bit-exact; scp i_cut 7-for-7 bit-exact; ftp75 h2 bit-identical across
  campaigns; sag dwell band 19.70–20.13 ms over 4 samples; the sag REGEN-teardown
  event classification settled (bit-identical to the comm-loss reference).
- **Tests at close: 1196 + 26 stdlib / 302 miniforge / 3787 + 175 + 4268 firmware.**
- ⚠️ Comparability: pre-2026-09-01 `ems-sdp` h2/ΔSoC pairs are the v2 law (the C2
  pair is literally the frontier check's FAIL fixture); v1↔v2↔v3 rules are in the
  docs. The overnight decisions and their reversal paths are itemized in
  OVERNIGHT_LOG.md.

---

## Status & session addendum (2026-09-01c, fw v24 flashed: tooling lockstep + campaign 080905 — the applyShareRatio() guard gap)

The operator flashed fw v24; the blocking tooling-lockstep round shipped (commit
739ff64: dual-length 16/17 B observation-frame parse, count-driven MPPT emulation
with 18 V fallback, `mppt_thresh_cnt` CSV column both schemas, mppt-tracking
expectation flip hunt→no-hunt, FW_DELTA_NOTES[24]/TARGET_FW_VERSION 24; review
3 MED + 7 LOW all applied — notably the stale 60 ms backoff-dwell figure (truth:
15 ms, .ino:1764; the .ino:32 changelog line still carries 60 and is queued
(corrected in fw v25, commit b262e98));
tests 1217+26 / 129). Then the FIRST fw v24 campaign ran: **55/56 + drive SKIP**
(hil_report_20260901_080905; HIL_FINDINGS.md + HIL_SUMMARY.md in the folder).

- **fw v24 VALIDATED in emulation:** the MPPT hunt is GONE (68 rises → 3 exactly
  as derived; refusal ticks 1481 → 0; three ~0.98 s clean releases vs the 40 ms
  hunt), cruise harvest exactly DOUBLED (2.005×; brake-window coulombs identical
  to 4 dp), threshold-count arithmetic exact vs `.ino` at 15 quantization
  boundaries, observed count band [15,19] — the FLOOR binds ~85 % of harvest
  (V_chg sags to ~14.45 V → effective margin 2.13 V, not 3.0). OC_FC margin
  16.9 % (the review's MED-3 budget risk did not trip). 17 B frame clean over
  ~1.3 M frames; v23→v24 drive-law comparability empirically confirmed
  (indistinguishable from the v23→v23 repeat-noise floor). ⚠️ The HIL mirror
  bypasses the write policy/deadband/session ratchet/EPROM budget — those remain
  BENCH-ONLY unvalidated; never cite HIL count motion as write-budget evidence.
- **THE FINDING (BOARD-REAL, fw-version-independent): the r-based bus cutoff in
  `applyShareRatio()` is UNGUARDED** — no |I_doomed| ≤ SHARE_CUT_MAX_HANDOFF_A
  term (that guard exists only on the setpoint-latch path, fw v6) and no
  survivor-conducting term. In ems-sdp-braking it opened FC_BUS (the only
  conducting source, i_cut 0.6371 A) 5 ms after BT_BUS restore — inside BT's
  8 ms RT1987 TD_ON — at a charge-window close: bus 14.56 → 12.40 V in 3 ms,
  reactive BT pickup, share slew, I_batt 4.64 A → OC_BT latch (fault response
  CORRECT). Mechanism: during every FC-charge window BT_BUS is held LOW, the
  share loop winds r onto DROOP_R_MIN = 0.15000 EXACTLY (zero margin, identical
  in C3/C4), and the window close makes the pinned cut actionable the same tick
  BT returns; hit = sub-ms tick alignment (2/5 closes vs 0/18 in C3+C4,
  p ≈ 0.04 — fw v24 loop-phase shift is a HYPOTHESIS only; the share code is
  byte-identical, the UV backoff provably never armed, mppt_emulation off).
  A second NON-FATAL instance same run (t = 20.172, BT_BUS, 0.7438 A). No other
  instance campaign-wide (full events.jsonl sweep; the other >0.5 A en_low cuts
  are benign State-99 teardowns). **fw v25 candidate queued in WORK_QUEUE.md
  §0a** (guard both r-based branches + survivor-HIGH < 8 ms blanking +
  regression); the ems-sdp-braking expectation is deliberately NOT relaxed.
- **Every other verdict verified right-for-the-right-reason** (dedicated Opus
  agents on mppt-tracking + the FAIL, consolidated Sonnet pass, adversarial
  Opus replay audit): replay half 27/27 REAL (137 checks, 0 untagged-vacuous),
  carried-in latch chain exact 55/55 + 27/27, scp i_cut bit-exact 9-for-9,
  ems-sdp h2 0.012542582 bit-exact (8 ppm record extends across the flash),
  frontier PASS 0.9003×/1.0000×, charge-cruise OC_FC bit-identical current Δ4 ms
  vs C4. Fix queue (2 MED + LOW batch incl. the mppt first-campaign calibration
  pins) in the ledger and WORK_QUEUE §0a.
- Tests at close: 1217 + 26 (.venv_hil five suites), 129 (miniforge
  report-analysis). Firmware suites untouched this round (fw v24's 3787/175/4268
  stand from commit f8050e1).

---

## Status & session addendum (2026-09-01d, fw v25 + regen-fidelity round: share-cut guards, 18 B frame, regen model, DP/droop/figure extensions)

Large orchestrated round in five work packages (operator-approved scope 2026-09-01),
executed with parallel implementers on disjoint files, per-package reviews, and
combined fix rounds. Commits b262e98 (fw v25) + 89fbad6 (tooling). **fw v25 is
COMMITTED and NOT FLASHED; the flash prerequisite (18 B sim lockstep) is now met —
the next flash carries v25 alone (edit HIL_SIM 0→1 as usual).**

- **fw v25 (WP-A): the campaign-080905 hazard is closed.** Both r-based cut branches
  in applyShareRatio() gained the fw v6 load guard (|I_doomed| ≤ 0.5 A), and BOTH cut
  paths gained survivor-turn-on blanking: writeBusSwitch() chokepoint (all 26
  FC/BT_BUS_ENABLE write sites) timestamps rising edges; cuts refused while the
  survivor's edge is younger than SHARE_CUT_SURVIVOR_BLANK_MS **30 ms** (review H1:
  t_D_ON 8 ms + 100 nF CSS soft-start tON 19.8 ms per the repo's own RT1987 model;
  TODO(calibrate) with the asymmetric failure direction stated — do not shorten on
  the model alone). Refused cuts fall through to a SLEW-LIMITED band-edge clip on
  the controller path only (shareRatioFromController marker — the reviewer's literal
  fix was wrong: powerBalanceLive is State-98-only); one-shot operator writes land
  exactly as commanded. Observation frame 17 → **18 B** (error_code at offset 16,
  XOR 1..16) — PI_TIMEOUT vs HIL_STALE finally wire-distinguishable. Diagnostics:
  load-/blank-refused TICK counters in the 'S' dump (episode counts they are not).
  .ino:32 + ledger row 24 backoff dwell corrected 60 → 15 ms. Tests 3842/175/4324.
- **Regen-fidelity plant model (WP-C): the regen power floor is GONE.** Braking
  energy now flows kinetic → VESC (clipped at VESC_REGEN_I_MAX_A 1.5 A — one number
  sets braking force AND electrical return; ETA_REGEN 0.80; both TODO(verify)) →
  N_MOT bounded-Norton → chopper linear clamp (coalesced chopper_clamp events with
  energy accounting — the chopper-coverage item's enabler) → D-BC-RG → Ag105 → pack.
  Two latent model bugs fixed en route: the bare 1/47 chopper stamp could not hold
  18.1 V (chattered), and the RT1987 ON stamp went NEGATIVE for dv < 35 mV (a closed
  MOT_PWR silently absorbed the harvest) — strict_forward now on MOT_PWR/REGEN/
  FC_CHARGE only; **the scp i_cut record verified bit-identical to 17 digits**, the
  FC/BT boost-OR links deliberately unscoped (parallel-source handoff A/B is future
  bench work). New scenario **regen-harvest-true** (S3-full un-tabled; commanded
  decel unachievable by design so the controller rails). **Baseline era:** the
  ems-y quartet (brakes at −12 A → force 2.7× less under the clip), charge-regen,
  mppt-tracking regen windows and regen-harvest-true are NOT comparable with
  campaigns ≤ 080905; the EMS objective set, all h2 totals, the frontier and all 27
  replays measured out of blast radius. Honest magnitudes: at the 1.5 A clip a
  braking window returns single-digit joules; SoC still falls net.
- **fw v25 sim lockstep + suite batch (WP-B):** 16/17/18 B parse, error_code CSV
  column/dashboard, wire-first 0x8010 attribution (the documented "error_code not
  on the frame" residual is CLOSED; stream-health inference kept as the pre-v25
  fallback). Campaign-080905 batch landed: column_range_at_least + floor_min_value
  + i_fc_max_in_band + min_rows check kinds, mppt calibration pins de-provisionalized,
  TP0010 i_bt_clamp_a 2.8 (TP0053 measured 2.345 — deliberately unclamped),
  ML0151 margin pin, blg sha stamps, and the **share_cut_load_hazard tripwire**
  (review-hardened: whole-run-minus-carried-in anchor with TEARDOWN_LEAD_MS 5 ms —
  teardown cuts lead their latch by 0.095-0.117 ms vs ≥ 13.8 ms for genuine hazards;
  gated on TARGET_FW_VERSION ≥ 25 AND a per-run 18 B observation). Operator rulings
  implemented: ems-ftp75-socband OC_FC allowance RETIRED (h2 two-sided
  [0.070, 0.115]); new **v-bus-sense-offset** scenario is the UV-dwell objective's
  home (8 ms no-latch + 60 ms latch probes bracketing the 20 ms dwell; stall-margin
  hardened + cadence de-vacuation). fw v25 expectation-impact review: NO measured
  pin moves (staircase cuts are setpoint-path and 3 s apart); ems-sdp-braking's
  fault-free expectation becomes reachable again — its FAIL record is fw ≤ 24.
- **EMS extensions (WP-E):** scenario **ems-ftp75-dp** + regenerated DP tables — a
  real generator bug found (chg_ceiling_a header default 0.0 vs solve default 2.5
  would have refused ANY new table; one shared resolver now) — data rows
  byte-identical, −14.33 % and the FTP75 DP≈soc-band tie reproduce; EMS_FRONTIERS
  registry adds the drive-cycle tuple (vs_reference ≤ 1.02 — the offline result is
  a TIE, do not demand a win) with a stimulus-coherence precondition that currently
  renders it **UNVERIFIED: ems-ftp75-sdp runs 0.45 A preload vs the siblings'
  0.65 A** — OPERATOR RULING OUTSTANDING: (a) run the SDP leg at 0.65 (costs its
  measured OC_FC margin) or (b) add a fourth SDP leg at 0.65. **--droop
  {design,measured}** hifi mode (opt-in, default design bit-identical): single
  scaling point over the droop term (copper 0.033 Ω fixed), single-source anchored
  0.16003 V/A; the shared regime lands +8.1 % off the bench fit because the network
  ratio is structurally 2.000 vs the fit's 2.182 — residual ASSERTED by test; the
  ~4× K_DROOP open finding is NOT closed by this mode and says so.
- **Figures (WP-D):** new hil_h2_and_soc figure (Gfc cumulative + sdp static-proxy
  overlay / SoC with ΔSoC) + backfill over all 14 report folders (full renders
  191509 onward; SoC-only degraded with an honest annotation for pre-Round-B
  folders; replays skip). The DP-vs-live-plant boundary is now documented at
  build_demand: the DP's demand model has NO regen term — deliberate, magnitude
  unquantified for the live comparison.
- **Reviews across the round:** WP-A 2 HIGH + 3 MED + 3 LOW; WP-C 1 HIGH + 5 MED;
  WP-E 1 HIGH + 4 MED; WP-B 2 HIGH + 2 MED — all applied; three reviewer fix texts
  were themselves wrong and corrected under the deviation license with evidence
  (powerBalanceLive scope, the post-grace anchor vs scp-inrush's in-grace latch,
  the 2.30 V collapse bound).
- **Tests at close (orchestrator-rerun): 1344 + 28 (.venv_hil five suites), 138 +
  179 (miniforge), 3842/175/4324 firmware.** Plan is now 32 scenarios / 59 runs.
- **Operator items:** flash fw v25 (prerequisite met) → the first fw v25 campaign
  is a triple validation (guard end-to-end via ems-sdp-braking completing, the
  regen-model baseline recalibration, the 18 B attribution); rule on the FTP75
  preload split; **the Pi bridge source ARRIVED** (references/EMS/Pi_2026-09-01/,
  uncommitted — teensy_bridge_node_2026-08-17A.py + ROS2 EMS nodes + Pi-side SDP)
  — the Mode B v4-parser audit is UNBLOCKED and queued for the next session. Bench
  items feeding the new TODO(verify)s: VESC regen commanded-vs-delivered mapping
  (sets VESC_REGEN_I_MAX_A + ETA_REGEN), the 30 ms blanking calibration, MPPTD-
  disabled-charge semantics, Silvertel EPROM endurance. Future protocol flags:
  sw_ring state field; the refused-cut counters are not on the observation frame.
