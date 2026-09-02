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

## Archived session history (2026-06-23 through 2026-09-01, fw v2–v25 bring-up and flash era)

The superseded status addenda from that period were moved verbatim to
`docs/claude-md-archive.md` to keep this file under the memory-size limit. Four ranges are
archived. The fourth (rotated 2026-09-02) holds the 2026-09-01a–d addenda, that is the fw v24
dynamic Ag105 MPPT-threshold round, the overnight campaigns 1–4 that produced sdp_policy_v3 and
the charge-economics finding, the fw v24 flash with campaign 080905 and the `applyShareRatio()`
guard gap, and the fw v25 round that closed it (share-cut load guard and survivor blanking, the
18 B observation frame, the regen-fidelity plant model, the DP, droop and figure extensions).
Its load-bearing facts survive in `docs/firmware-versions.md`, `docs/HIL_PLANT.md`,
`WORK_QUEUE.md` and the campaign ledgers under `HIL Results/`. Read it before revisiting fw v24
or fw v25 design intent, the guard-gap incident, or the origin of the regen model. The third
range (rotated 2026-09-01e) holds the 2026-08-31b–i addenda: overnight campaigns
1–4, Rounds A/B/C, the TPM toolchain, sdp-v1, campaign 191509 and its suite evaluation, and the
sdp_policy_v2 fix round; their load-bearing facts survive in WORK_QUEUE.md, docs/HIL_*.md and
the campaign ledgers. The first (2026-06-23 through fw v7, 2026-08-13) covers early bring-up, the
boost-death investigations, the share-controller design round, and fw v2–v7. The second
(rotated 2026-09-01) covers the encoder/BLG era and the HIL tooling bring-up: fw v8–v17 and
fw v20 (encoder pin move, `'K'` manual logging, the Youla-H drive controller, BLG v5–v7, the
edge-period estimator, the K_F force-axis correction, the dpos/fractional-pitch ledger, the
log rounds ML0146–ML0180), and the HIL rounds fw v21–v23 with their tooling follow-ups
(2026-08-27 through 2026-08-31). Every load-bearing fact from the first two ranges survives in
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

## Status & session addendum (2026-09-01e, fw v25 first campaign + EMS test-program round: governor model, matched-DP database, α-sweep, asymmetry fit, preload removal, Pi-bridge audit)

Orchestrated tooling round (operator brief 2026-09-01: WORK_QUEUE §0–§2 + §1 items 1–4, 6;
one supervised campaign; branch `round-20260901e` merged to main). Python tooling + docs +
data; **FW stays v25; wire protocol frozen.** Investigation fan-out (5 agents) → Wave A/B
implementers in parallel with the campaign → test-writers → two-lens reviews → fix rounds →
campaign analysis under hil-agent-analysis → B1/C1 rounds. Operator rulings recorded in memory
(campaign budget 1 ideal / 3 max per supervised round, 5 overnight; branch-then-merge; preload
off DRIVE cycles only — Y_AUX_LOAD_A stays; asymmetry default-on; Pi files reference-only;
online H2 proxy η 0.4; α-sweep all 21 then operator picks 3; DP results database).

- **Campaign hil_report_20260901_151156 (FIRST fw v25, 59-run plan, --with-ftp75): 55/59 PASS +
  3 FALSE FAIL + drive SKIP — zero board defects.** T1 share-cut guard VALIDATED (zero en_low bus
  cuts > 0.5 A outside teardowns campaign-wide; ems-sdp-braking fault-free — at each heavy BT
  restore the load guard refuses for +6…9 ms, blanking carries to +30 ms, cuts land at +35.9/+40.7 ms
  under 0.34 A; the 0.02/tick refused-cut slew seen on hardware; V_bus RISES 13.34→15.74 V where
  080905 collapsed; peak I_batt 0.52 A vs 4.64 A). T3 error_code VALIDATED (pi-silence 0x05
  PI_TIMEOUT vs comm-loss 0x10 HIL_STALE on the wire; a carried-in latch reports the PREDECESSOR's
  cause). T2 regen baselines RECORDED (charge-regen ~39 mC/window at the 1.5 A clip, −97 % vs the
  bus-fed era; ems-y h2 moved ≤ 1.9 %). The three FAILs: v-bus-sense-offset = suite scoring defect
  (`not_before_s` judged the 8 ms probe's TRANSIENT bit; the latch came at 19.90 ms dwell exactly as
  designed) — FIXED (C1); regen-harvest-true = sim event-accounting defect (coalesced chopper_clamp
  truncated by the per-tick drain: 0.0035 J reported vs ~7–9 J burned) — FIXED (C1); mppt-tracking =
  tripwire window overlapping a regen-lifted braking window (count 27 = mirror clamp; cruise peak
  still 19) — re-scoped (C1). Repeatability: scp i_cut 10-for-10 bit-exact; FTP-75 socband h2
  bit-identical across seven campaigns; ems-sdp 8 ppm across the flash; comm-loss re-close peak
  0.3696→0.3591 A/ch (WP-C-attributed; second campaign settles). Replay audit 27/27 real, 0
  untagged-vacuous; the replay half cannot exercise the share guard (documented).
- **tools/governor_model.py (stdlib) + tools/ems_walk.py:** a line-for-line port of the firmware
  share-delivery governor (latch, min-load freeze, 0.60/0.55 A hysteresis, HOLD/feedforward,
  minority clip, slew modes, both r-based cuts with the fw v25 load guard + blanking, refused-cut
  clip, MDAC quantization; Youla NOT ported — slew-limited convergence surrogate, `conv_tau_s` hook
  reported not adopted) validated by replay against campaign MDAC traces (ems-sdp RMS 0.0103 after
  the states-2/98 gating fix; 17/28 runs scoreable, 11 UNSCORED by the new n_moving vacuity guard;
  ems-sdp-braking outside the fidelity claim). The walk drives ANY registered strategy through the DP
  demand/pack/H2 model with the governor at 1 kHz: soc-band governor=False reproduces
  heuristic_walk EXACTLY; governed sdp-v3 on ems-sdp lands +0.48 % of the measured h2. It is the
  offline-walk tool the standing "walks must model the open-loop hold AND the feedforward slew"
  rule lacked (the rule named only the hold until 2026-09-02; open loop has two submodes and the
  feedforward one writes the MDACs). Fixed en route: the
  DP generator's drain whitelist omitted ems-sdp (half demand).
- **ΔSoC-matched DP post-pass + results database (items 2 + 4):** gen_dp_ems_table.py refactored into
  prepare_problem / solve_matched / solve_unmatched (committed tables byte-identical);
  tools/dp_results_db.py (stdlib store tools/dp_db/, key = stimulus fingerprint + model quantities +
  target quantized 1e-5, lookup tolerance **1e-5 SoC** — 5e-4 mis-read +22 % on a 2e-3 swing —
  provenance-drift note/strict, rekey, unique temp names, `prefill --key-fields @file` with era
  overrides); hil_report_analysis.py `--matched-dp {off,lookup,solve}` (default lookup; solve refuses
  > 100 s scenarios without --matched-dp-allow-long) writes per-run pct deviation + the cross-strategy
  table (item 4's per-campaign form). Campaign 151156: dp-replay −0.23 %, sdp-v3 −0.99 %, soc-band
  +10.80 % — consistent with the frontier arithmetic. Stimulus-era overrides reconstruct a run-era
  fingerprint from the sidecar (all DP_FINGERPRINT_META_KEYS), so old-era runs stay solvable after
  a scenario change. Standing notes: DP has no regen term; run h2 is the dynamic Gfc vs the DC-gain
  stage cost.
- **α-sweep (item 3):** tools/sdp_alpha_sweep.py; 21 artifacts (20 geomspace over [0.0514, 0.514] +
  the 0.16296 anchor, whose policy sha equals sdp_policy_v3's); charging enters the table at
  α = 0.23925 (the modelled admission-window edge); α ≤ 0.106 is share-0-everywhere degenerate. Only
  5 points sit inside the lever windows, so sweep artifacts bind through the non-frontier `sdp-v2`
  role. Offline walk on ems-sdp: three legs — greedy (0–6), calibrated (7–13, h2 0.01260 g),
  charge-admitting (14–20: one loss-making window, +16.1 % eq-H2); on ems-ftp75-sdp points 7–20 are
  identical (no admitted bin). Operator picks three live points (ems-sdp is the discriminating
  stimulus).
- **Converter asymmetry (item 6):** tools/benchlog_analysis/asymmetry_fit.py + docs/modeling/
  converter_asymmetry_20260901.md: ΔV0 = **+0.0444 V** [+0.0415, +0.0473] from 385 closed-loop
  windows / 75 runs, stable fw 3–6, confirming CAL-1 (+0.05 V); r_cmd for a delivered 0.50 =
  0.4632 at 1.0 A. M1 vs M2 near-collinear (I_tot lever 2.36×); INA-offset sense arm +0.0120 V →
  inject +0.0444 V on default runs, +0.0324 V under --noise; droop_scale_fc 0.930 [0.834, 1.079]
  (includes 1). **The +8.1 % shared/single residual is NOT explained** (pooled anchor: the identity is
  stationary at equal channels; effect −0.078 %); the ~4× K_DROOP finding reproduces independently
  (R_F 0.086 / R_B 0.110 Ω) and stays open. No open-loop feedforward windows exist in the corpus
  (TODO(calibrate): an 'O' open-loop sweep above 0.60 A). C1 builds it into the plant DEFAULT-ON — with the **M2 consistent pair** (ΔV0 0.013522 V, ρ =
  droop_scale_fc 0.9434): the physics review showed that injecting M1's 0.0444 V together with a
  separately estimated ρ double-counts their collinear component (RMS vs CAL-1: shipped 0.040, M1 alone
  0.025, M2 pair 0.006 — the engine reproduces CAL-1 at 0.0064). The injected ΔV0 scales with
  DROOP_SCALE[droop_mode] (the SHARE deviation is the measured quantity) and the INA sense arm is
  subtracted from the EFFECTIVE injected offsets (0.013522 → 0.001522 under a default NoiseConfig).
  `--asymmetry off` is byte-identical (engine anchor 15.624602041790853). Light-load BT starvation
  threshold ≈ ΔV0/R_B ≈ 21 mA (below I_AUX_A); V_bus is mean-preserved.
- **Campaign fix queue (C1 PART B):** `not_before_s` now judges the LATCH (`fault_first_latch_t`);
  v-bus-sense-offset de-provisionalized (19.90 ms ± 6 ms latch window; 8.3 ms probe); chopper_clamp
  events now emitted whole at episode END (`close_chopper_episode()`, `_EventLog` durable counts) with
  regen-harvest-true re-banded (max_of ≥ 1.0 J, total ≥ 3.0 J, new `max_of` check kind); mppt tripwire
  re-scoped to the cruise window (28.1, 37.0) with a braking-window 27 pin labelled MIRROR ARTIFACT;
  the test-writer caught duplicated FAULT_EXPECTATIONS keys (regen-harvest-true, charge-regen) that
  silently shadowed bands — fixed + an import-time tripwire.
- **Simple-mode split sign bug (found, fixed in C1):** frac_fc = code_fc/(code_fc+code_bt) delivered
  1−r because the firmware gain is ∝ 1/r; hifi mode (every campaign since 2026-08-27) was correct.
- **Preload removal (item 1, B1):** FTP75_PRELOAD_A / FTP75_SDP_PRELOAD_A → 0.0 (campaign 151156 is
  the last preloaded era; constants_hash moves); socband leg gains chg_i_ceiling_a 0.8 (frontier
  splits RESOLVED); sidecar scenario_meta.aux_preload_a; governor-walk re-derived provisional bands
  (walk reproduces the old era to ≤ 1.8 %; preload-0 predictions 5050 0.0281 g, socband 0.0355 g,
  sdp 0.0193 g with the flip at ~275 s; 64.5 % of the FTP-75 Run window is now below the 0.55 A
  open-loop line); FTP-75 DP table regenerated (fingerprint 403c5e71…, h2 0.0397 g); new
  socband_ftp_charge_opened check.
- **Pi bridge audit (§2) — DONE:** docs/PI_BRIDGE_V4_AUDIT_20260901.md + a stand-alone change request
  for the PhD student (docs/pi_bridge_change_request_20260901.md) + tools/test_pi_bridge_v4.py (24).
  The 08-17A bridge is v4-conformant byte for byte; the Pi's sdp_ems_node still reads the 15-element
  layout (switch_state as faults, faults as SoC — unsafe on the SoC branch) and the default launch
  file starts it; both standalone SDP scripts assert the 54 B protocol; the stale-link handler
  overwrites the fault word. Mode B is gated on the Pi running the 08-17A bridge with a fixed node.
- **Tests at close (orchestrator-rerun):** `.venv_hil` tools/ (all stdlib suites, --ignore test_figures.py): **1575 passed + 49 skipped**; miniforge (numpy suites: gen_dp, report-analysis, sdp solver, tpm, alpha sweep, dp_db, ems_walk, governor, pi-bridge, asymmetry, figures): **613 passed + 1 skipped**. Firmware suites untouched this round (fw v25's 3842/175/4324 stand).
- **Next:** operator review → campaign 2 (first zero-preload + asymmetry-era + fixed-tooling campaign;
  calibrates the FTP-75 provisional bands; settles the comm-loss re-baseline); operator's three α
  points; item 5 (governor-aware MPC — the governor model + walk are its prediction model; H2 proxy
  η 0.4); item 7 physics review (seeded: the chopper accounting defect, the mppt mirror REGEN
  exclusion, the comm-loss RT1987 ON-stamp shift, the ftp75-dp −2.15 % table-fidelity gap).

---

## Status & session addendum (2026-09-01f, power-balance figure + refined α-sweep)

Two operator-requested tooling items, orchestrated (two parallel Opus implementers on disjoint
files, Sonnet test-writers, Opus physics/data-integrity reviews, fix rounds). Python tooling + docs
+ data; **FW stays v25; wire protocol frozen**; branch `round-20260901f` merged to main.

- **Power-balance figure `hil_power_balance` in every HIL report.** Six append-only CSV columns
  computed in `Plant.step()` for BOTH engines (after `error_code`, so no older offset moves; blank on
  replay rows): `p_mot_w` = i_motor·V_rgn − p_regen_w (motor node; + draw, − regen; the two branches
  are exclusive by construction), `p_fc_w` = V_bus·I_fc (bus side — NOT the stack power Gfc uses),
  `p_batt_w` = V_bus·I_batt − V_batt·i_charge (net; the charge term is the same current/voltage pair
  the SoC integrator gets), `p_chop_w`, `p_aux_w` = V_bus·i_aux, `p_bal_w` (per-tick residual). The
  figure plots the four terms + the sum, and a residual panel naming the known components. The
  identity is EXACT in simple-mode motoring (aux is the whole residual); hi-fi motoring residual
  −0.375 W mean after aux (RT1987 drops ≤ 35 mW, 470 µF storage, the conductance-stamp transient).
  **Physics finding exposed by the column (HIGH, operator decision queued):** the hi-fi Ag105 is a
  1:1 CURRENT-transfer element (J[N_CHG] −= i_charge; the pack receives the same current), so it
  destroys i_charge·(V_chg − V_batt) — the −11 W charge-window residual (1.4 A × 7.9 V = 11.06 W) —
  and over-draws the bus ~1.8× vs a real buck at η ≈ 0.9; this bears on the campaign-000816
  "charging is loss-making" conclusion and on L_chg 0.2364 SoC/g behind sdp_policy_v3's α. The
  simple engine treats charging as free energy (documented; hifi-only campaigns unaffected); the
  frontier stimulus-coherence check now also compares the resolved electrical mode. Legacy CSVs
  (every campaign ≤ 151156) get a source-powers-only rendering with an explicit annotation — the
  VESC `current` column is a PHASE-current command, not bus current, so no motor proxy is drawn.
  Backfilled across all 14 report folders.
- **Refined α-sweep.** Both transition points bisected through the solver: share-map degeneracy at
  **α = 0.111000013** (±5.1e-8) and charge admission at **0.239249990** (±1.1e-7) — exactly the two
  ends of the modelled admission window ((1−γ)/L_share, (1−γ)/L_chg). That is the solver's own
  closed form re-measured; what the bisection establishes is that the SoC grid, the J interpolation
  and the forbidden-bin mask do not displace the analytic threshold (≤ 1.2e-7 relative). Twenty new
  artifacts (indices 21–40; b × (1 ∓ {0.5, 1, 2, 4, 8} %)) with a stamped `refinement` manifest
  block; 41 points evaluated on ems-sdp and ems-ftp75-sdp (zero-preload era). Within a leg the walk
  totals coincide to 8 decimals although the policy tables differ (26 vs 30: 130 of 2525 cells) — the
  walk trajectory never visits a differing cell, so a live run would not discriminate within a leg
  either. Per-point `walk_currents_and_share.png` / `walk_hil_charger_and_soc.png` (122 files)
  synthesized from the offline governor walk through the report figure builders (suptitle "OFFLINE
  GOVERNOR WALK … not a board run"; `walk_` prefix so no campaign glob ingests them); the document
  embeds one pair per leg and the immediate neighbours of each boundary, plus clustered h2-vs-ΔSoC
  and h2-vs-α step figures. The refined table is priced against the anchor's ΔSoC (a first version
  used idx 21 — fixed).
- **Tests at close (orchestrator-rerun):** `.venv_hil` tools/ **1580 passed + 51 skipped**; miniforge (thirteen numpy suites incl. test_hil_plant_sim and test_figures) **1278 passed + 1 skipped**. One pre-existing WP-C assertion (engine vs plant regen energy ≤ +1 nJ) was relaxed to +1e-4 relative: the hi-fi substep rate is wall-clock adaptive, so a loaded host can exceed it by a few ppm (measured +8 ppm; exact in isolation). Firmware untouched.
- **Next:** operator decision on the charger-efficiency model (WORK_QUEUE §5); campaign 2; the three
  live α points (one per leg — ems-sdp discriminates, the drive cycle does not).

---

## Status & session addendum (2026-09-02, overnight round: Ag105 η = 0.88 in the plant, η-era DP/SDP (sdp_policy_v4), α picks, governor-aware MPC registered, campaign B)

Overnight autonomous session from commit `668d281` (operator brief 2026-09-01 evening, eight verbatim
rulings; decisions and reversal paths in OVERNIGHT_LOG.md §2026-09-01/02). Work packages WP-1A (plant η),
WP-1B1 (DP/SDP/walk/db η), WP-1B2a/b (sdp_policy_v4, sweep, registration), WP-1C (expectation
re-derivation) and the MPC design/implementation/registration chain, each with two-lens reviews and a fix
round. **FW stays v25 and the wire protocol is frozen; the board ran the fw v25 HIL flash all night.**

- **The charger is an energy converter in BOTH engines** (`ETA_CHG` = 0.88, `tools/hil_electrical.py`;
  `AG105_Silvertel.pdf` "Charge Efficiency EFF 88 % typ", Note 2 states 25 °C, 12 Vin, 3S against our
  15–16 Vin, 2S — operator ruled a static value, `TODO(verify)`). One rule: `i_in = i_charge·V_pack/(η·V_input)`,
  `i_out = i_charge`, `p_chg_loss = i_charge·V_pack·(1/η − 1)`. The input node is a switch question both
  engines answer from `chargerHasPower()`: FC_CHARGE bills the bus, the REGEN pair bills the braking power.
  The hi-fi element is a **chord conductance** referred to the previous substep (`G[N_CHG][N_CHG] += i_in/v_prev`),
  never a negative incremental conductance, with a **floor `V_CHG_LOAD_FLOOR` = 8.0 V** pinned to
  `AG105_V_IN_MIN` (physical; bounds the stamp at 2.98 A on a dark node). Probe (6 s FC-fed, 1.4 A ceiling,
  both droop codes mid-scale): residual after aux simple +11.0012 → 0.0000 W, hi-fi −10.6477 → −0.3957 W;
  bus draw 0.9283 against 0.9799 A across engines that were 21.6 W apart. The regen cap is **output-referred
  and NOT netted against the chopper** — netting was measured and rejected, since it destroys 0.64 J hi-fi /
  1.43 J simple of genuine harvest and the chopper is a residual clamp, not a prior claimant. That leaves a
  **6.3 % bus contribution** (+0.0880 J of 1.4016 J). ⚠️ **MECHANISM CORRECTED 2026-09-02 (review
  PLANT-R1-F2):** it is NOT a solver leak and NOT a co-solve problem — `MOT_PWR` is strict-forward, so
  the contribution is ZERO in every bin while the chopper clamps (bus-fed clamping would need
  V_BUS > 18.135 V, above the 17.5 V latch) and appears only AFTER clamp release, as a steady 0.118 W
  of bus-fed CHARGING once V-MOT parks at V_BUS − 35.3 mV and MOT_PWR forward-conducts
  BUS → MOT → REGEN → VCHG-IN (14.93 mA; deleting the stamp gives 0.000000 J). **The co-solve
  `TODO(verify)` is RETIRED** and the 0.15 J / 12 % aggregate test ceiling is replaced by two
  mechanism assertions (bus energy over chopper-active ticks within 1e-6 J of the charger-off run;
  every non-zero dE_bus tick satisfies V_bus − V_rgn ≥ RT_V_FWD). Seventh power column `p_chg_loss_w` follows the six of 2026-09-01f, so
  the identity is `p_mot + p_chg_loss = p_fc + p_batt + p_chop + p_bal`. `constants_hash` `250683275d00874d…`
  → **`6a88d04ba8a36e61…`**; the design-mode bus anchor 15.624602041790853 is unmoved (pinned at
  `i_charge` = 0), so `--asymmetry off` byte-identity survives on charge-free traces. ⚠️ **η = 1.0 does not
  revert this round** — the six-item reversal path is `docs/HIL_PLANT.md` §4.6.2.
- **Era helper `tools/charger_power.py`; an ABSENT `eta_chg` key means the old era** (V_bus billing), so
  every pre-round sidecar, table and database record keeps its meaning. `dp_profile_fingerprint()` omits
  `eta_chg` when None, returning the three table fingerprints to their pre-round values (`02683031` /
  `50fe8c40` / `403c5e71`). DP tables regenerated as η-era solves; old-era regeneration is byte-identical
  and kept as a fixture test.
- **Lever arithmetic.** `L_share` = 0.450450450450 SoC/g is era-invariant. `L_chg` moves 0.208986417 →
  **0.396396396396 = η·L_share exactly**, so the levers are `1/η` = 1.136 apart in place of 2.155. The
  calibrated interval collapses to (0.111000000000, 0.126136363636), whose width in log-α is exactly
  `ln(1/η)` = 0.1278. The admission margin is recorded as `√η` = 0.93808, which is convention-free. A walk
  traced I_fc in a charge window 1.1372 → 0.7894 A.
- **RULING (operator rule 4, α follows the DP): the η-era matched DP charges on ZERO stages on both
  `ems-sdp` and `ems-ftp75-dp`, so `--alpha-mode lever` ships as `sdp_policy_v4.json`** — α
  **0.11832639757736393**, shadow price 2.366528 g/SoC, admission bound 0.422560 SoC/g, **0 charge cells**,
  440 sweeps to sup-norm 9.83e-13, policy sha256 **`8ca7dcee…`** (the log's `6c4843bb…` was a transcription
  error; `sdp_policy_v3` reproduces bit-identically at `0443febf…`). The `charge-edge` candidate (α
  0.1262625, 540 charge cells) is kept as a sweep point, not shipped. sdp-v3 is **demoted** (old era, still
  registered); `ems-sdp` and `ems-ftp75-sdp` are rebound to sdp-v4. ⚠️ The v3 and v4 share maps differ on
  **76 of 2525 cells, all on SoC rows 0.552–0.555**, 45 or more nodes below the target, so walk-derived
  expectations transfer verbatim. `ems-sdp-cross` and `ems-sdp-braking` stay on sdp-v2 deliberately: they
  actuate the CHARGE threshold that v4's all-zero charge map cannot, and the η-era home for that mechanism
  is `ems-sdp-alpha-charge`. The DP margin over soc-band collapses **−14.33 % → −4.31 %**, mostly because
  soc-band's own h2 falls 10.5 %.
- **FINDING — the MEASURED levers INVERT in this era.** The old-era measured charge lever 0.2364 SoC/g
  projects to **0.448393**, above the measured share lever 0.412, while the model puts charge below share by
  exactly `1/η`. No α satisfying "admit share, reject charge" then exists, so the artifact records
  `window_measured` and `in_window_measured` as **null = UNDECIDABLE** rather than a pair it cannot compute.
  A certificate allowance accepts that null only with `window_intent`, `charge_measured_is_projection` and
  the charger block; a bare null still fails. ⚠️ No α decision rests on the projection. `TODO(verify)`:
  re-measure the charge lever on the first η-era campaign. (`docs/HIL_PLANT.md` §4.6.2 quotes 0.4102 SoC/g
  for the same lever at its own probe point; both figures are rescalings, not measurements.)
- **DP backward-pass defect found and fixed.** `solve_dp()` still billed the charger at `V_bus` in the
  backward pass, so a policy was CHOSEN old-era while REPORTED new-era. It is latent for the three committed
  tables, which take 0 charge stages either way, but **live at λ_term 3.5–6** and for 3 of 16 database
  records: at λ 3.5 the old pass takes 0 charge stages at 0.012521819 g and the η-era pass takes **157
  stages at 0.015344009 g**. Old-era results stay byte-identical. Two further B1 HIGHs: ten duplicate
  `--eta-chg` registrations had killed the database CLI, and the fingerprint move had orphaned all 16
  records. **Fingerprint reachability ruling: omit `eta_chg` when None**, which makes 16 of 16 reachable.
- **η-era α sweep** (`tools/sdp_policies/sweep_20260902_eta088/`, 41 artifacts;
  `docs/modeling/sdp_alpha_sweep_eta088_20260902.md`). Both behaviour boundaries bisected through the
  solver: degeneracy **0.110999993716** and charge **0.126136356495**, each −5.66e−08 relative to the
  analytic threshold; the identical error identifies bisection midpoint bias, not a physical offset. Legs
  are defined by behaviour: greedy 0–6 and 21–25, calibrated 7, 8 and 26–35, charge-admitting 9–20 and 36–40
  (540–600 charge cells). The calibrated leg is the eq-H2 minimum on **both** stimuli; charge-admitting
  costs +4.01 % on `ems-sdp` and +0.65 % on FTP-75. **The drive cycle now discriminates all three legs**,
  which it could not in the old era, because the charge boundary moved down to 0.126136 and one charge
  window opens on it. Live picks (`live_picks.json`): greedy **idx 3** α 0.073936, calibrated **idx 7**
  α 0.118326 (the anchor; the leg midpoint coincides structurally), charge-admitting **idx 14** α 0.248413
  with 591 cells. Within a leg the walk totals coincide to nine decimals although the tables differ, so a
  live run cannot discriminate two points inside one leg either.
- **Expectation re-derivation (WP-1C, 566 suite tests),** every band by plant probe or η-era walk. OC
  ceilings **HELD** with predicted peaks falling (sdp-cross 1.19 → ~0.84 A, sdp-braking 1.26 → ~0.95 A, mppt
  1.16 → ~0.72 A; re-pin from the first η campaign). `regen-harvest-true` chopper floors were **LOWERED on
  measurement** (max_of 1.0 → 0.65 J, total_of 3.0 → 1.9 J; probe 1.3043 J per window against 2.1741
  charger-off) — the one previously-measured bound that went down, **flagged for operator review**. The
  socband FTP-75 h2 band moved on two axes, 0.028/0.046 → 0.031/0.052 (era, plus a correction to the
  physical walk figure). The mppt peak tripwire was **deliberately not pre-widened** at ≤ 21 against a
  predicted [15, 21–22]: a FAIL there is a calibration event. Frontier asks held with headroom **14 % →
  2.3 %** (`cycle61` vs_reference predicted 0.859 → 0.958 against the 0.98 ask); `eta_chg` joins the
  frontier stimulus-coherence check, resolved from the sidecars.
- **Governor-aware MPC.** The Fable/Opus design pair was adjudicated to a **hybrid**
  (`docs/modeling/mpc_design_20260901/adjudication.md`): Opus's in-callback anytime search and closed-stage
  surrogate, with Fable's transition-stage exact rolls, shadow governor and three-window charge enumeration;
  a Huber terminal cost at the metric price 2.881 g/SoC, dead band 0.0015; certainty-equivalent demand plus
  a 90 % quantile overcurrent tightening for `mpc-sto`. A worker process was REJECTED as a risk to the 1 kHz
  loop that the budget arithmetic does not require. The review found four defects the original suite could
  not see — the roll slice ran on the 1 Hz decision path and left the table empty on 38 of 61 decisions, so
  the adjudicated hybrid was inert; a completed job with no items published an empty table by replacement;
  `bind_scenario()` did not match the binder contract; the roll table was keyed on the preview grid — plus
  five surviving mutations. After the fix round the mutation battery catches 14 of 14 and the worst callback
  is **10.17 ms at a 10 ms budget**. ⚠️ **Gate 1 FAILS with the roll table actually consulted:
  `ems-soc-band` mean 0.00971 and max 0.25000 against the 5e-03 acceptance**; the earlier 0.00389 was
  measured on a controller that never consulted the table. Mechanism: a 1 Hz re-command landing in an
  **`open_feedforward`** stage drops the governor into a feedforward slew that neither the surrogate nor the
  roll represents, and 50.6 % of that stimulus is open-loop. **DECISION: ship `mpc-det` and `mpc-sto` live
  tonight with the failing gate recorded**, `mpc_share_pred_err` banded at 0.30 provisional, so campaign B
  measures the board-side prediction error; the fallback (full governor rolls on open stages, about 8
  candidates, design §3.5) or a feedforward-aware stage model is a **MORNING decision**. Reversal: drop the
  four `ems-mpc*` scenarios, one commit. Registered: two lazy strategy proxies, four scenarios (`ems-mpc`,
  `ems-mpc-sto`, `ems-mpc-cross`, `ems-ftp75-mpc`), three drain mirrors, `mdac_fc`/`mdac_bt` on the MODE A
  feedback view, three CSV columns after `p_chg_loss_w`, `config.mpc`, eight command-line flags, and the
  `cycle61-mpc` and `ftp75-mpc` frontier tuples. Each leg pins `mpc_max_candidates` = 343 = 7³, the FULL
  enumeration at the shipped ladder, so the cap removes the wall clock from the candidate count without
  dropping a candidate. Gate-2 walk (soc0 0.7, three repeats to six decimals): `ems-mpc` h2 0.010429 g,
  ΔSoC −0.002537, eq-H2 0.016616; `ems-mpc-sto` 0.009313 / −0.002998 / 0.016625; `ems-soc-band` 0.012264 /
  −0.002002 / 0.017146; `ems-sdp` 0.012729 / −0.001600 / 0.016631. `cycle61-mpc` reads vs_reference 0.9691
  and vs_bound 0.9996. ⚠️ **The pair is the result and the hydrogen alone is not**: raising the search
  budget from 12 ms to 1e5 ms moves `ems-mpc-cross` hydrogen by −21 % while its equivalent hydrogen moves
  0.13 %. **Inverse crime:** the walk's plant IS the controller's prediction model, so Gate 2 shows the
  plumbing works and scores nothing.
- **Runtime metadata.** `campaign_meta.json` is written into every report folder with the start and finish
  stamps, `wall_s_total`, `wall_s_runs_sum` and `wall_s_overhead`. The REPORT.md "Campaign runtime" row
  appears only on the final rewrite, so a partial report omits the row rather than quoting a runtime that is
  not one (operator ruling 8).
- **Tests at launch:** `.venv_hil` **1761 passed / 59 skipped** after re-pinning two stale tests; miniforge
  **2022 passed / 1 skipped**. Firmware suites untouched — fw v25's 3842 / 175 / 4324 stand.
- **Commits:** `dec059b` (runtime metadata, MPC design pair, log opened), `390f554` (WP-1A + B1 and the A
  fix round), `e653e90` (sdp_policy_v4 and the η-era sweep), `6702920` (MPC core, unregistered), `d70a620`
  (WP-1B2b + WP-1C), `a932f83` (MPC fix round, Gate 1 re-measured), `887933f` (B1 fix round + MPC
  registration; campaign B launched from it).
- **Campaign B (`hil_report_20260902_011926`, `--with-ftp75 --with-alpha`; the η-era validation, the
  first MPC legs and the three α legs in one run, because `tools/` is edit-frozen during a campaign).**
  66 planned, 65 executed + `drive` SKIP, wall 1:16:45 (`campaign_meta.json`: runs 4240.9 s + overhead
  363.9 s). Suite tally 58/66; **corrected after analysis: 65 of 65 executed runs behaved correctly,
  zero board defects.** Replay half 27/27 real, 0 untagged-vacuous. Ledger: `HIL_FINDINGS.md` +
  `HIL_SUMMARY.md` in the report folder.
  - **Five FAIL classes.** (1) ONE cp1252 console defect behind five FAILs: `ems-sdp-cross` and
    `ems-sdp-braking` never launched (rc=2 — the charger-era mismatch warning raised
    `UnicodeEncodeError` ⊂ `ValueError` inside the sdp-v2 binder, so `ap.error` swallowed it), and
    `ems-mpc`, `ems-mpc-cross`, `ems-ftp75-mpc` completed their runs then crashed printing the
    mpc-det summary line (`U+26A0 U+FE0F`) BEFORE sidecar/event finalization — run data intact,
    sidecars partial, both MPC frontier tuples UNVERIFIED. (2) `regen-harvest-true` — scoring defect,
    structurally impossible check: `scan_signals()` never increments `ticks` on the plain numeric
    path, so `min_ticks 800` on `column: V_rgn` read a zero counter; the physics clears it at **1173
    continuous ticks** ≥ 17.9 V. (3) `mppt-tracking` — the count-27 pin window (37.732, 38.529)
    overhangs the plateau (37.7290 → 38.4631) in BOTH eras; it would have read 23 on 151156 too.
    (4) `ems-ftp75-socband` — walk-fidelity gap, the first campaign this leg ever charged: peak
    `I_fc` 1.1370 A decomposes to 4 dp (motor 0.4359 + aux 0.1500 + charger bus 0.5293 + path 0.0218),
    18.8 % under `LIMIT_I_FC_MAX`, five windows / 42.726 s / 30.608 C. (5) `ems-mpc-cross` — GENUINE,
    a 0.13 % h2 miss (0.0105875032 g vs floor 0.010601, −25.09 % against a −25.00 % band): a real
    divergence of the live MPC from its walk. **Do not widen it.**
  - **The Ag105 η = 0.88 model is validated on every independently measurable axis:** pack current
    unchanged on FC paths; bus draw 0.58–0.69 × `I_charge` (sag-dependent, = `V_batt/(η·V_chg)`);
    regen-fed pack current ×1.87–1.99 (`charge-regen` 75.06 mC/window vs 38.96); `p_chg_loss` =
    `i·V_pack·(1/η − 1)` to 4 dp; bus bookkeeping closing to 1.9 mA; and the charger bus draw on
    hardware within **0.5 %** of the model at a sagged 14.15 V bus (`alpha-charge` 0.8931 A measured
    vs 0.898 predicted from `alpha-cal`'s same-instant load). `charge-cruise` OC_FC at 8.849243 s with
    `I_charge` 1.3834 A = 1.444× the 1:1 era, against 1/0.687 = 1.455. η also WIDENED the soc-band
    hysteresis margin (post-open total 0.893 A vs the 1.30 A exit; 1.16 A at 1:1) and is what made the
    FTP-75 socband charge windows reachable at all.
  - **First live η-era lever measurement** (`ems-sdp-alpha-cal` and `-charge` command an identical
    constant share, so their difference is purely the charge windows): **L_chg 0.33214 SoC/g**,
    **L_share 0.41688 SoC/g**, **ratio 0.797**. Three consequences: (1) the projected inversion is
    **REFUTED** — the model's ordering (charge is the worse lever) is confirmed and the UNDECIDABLE
    window is now answerable; (2) the end-to-end charge round-trip on the board is **0.797, not
    η = 0.88** — the bus sags 15.76 → 14.15 V during the window and the extra FC cost of every amp the
    vehicle also draws is billed to the charge leg (a plant-physics item, not a solver item); (3) under
    the measured levers **v4's α 0.118326 sits 1.4 % below the measured admission window (0.11994,
    0.15055)** and a measured-lever re-solve gives α ≈ 0.13434 — HOLD for campaign C's second reading.
    eq-H2 at λ 0.41: cal 0.0126184, greedy +1.12 %, charge **+3.81 %** (offline +0.71 / +4.01 %) —
    ordering reproduced exactly, **`sdp_policy_v4` is the eq-H2 winner on the board**. `alpha-cal`
    reproduces `ems-sdp` to **0.79 ppm** through the `sdp-sweep` role.
  - **First live governor-aware MPC.** `mpc-det` ties sdp-v4 on the 61 s cycle (`cycle61-mpc` computed
    by hand: 0.96212× vs_reference / 1.00046× vs_bound, against sdp-v4's 0.9632 / 1.00159 — 0.11 %,
    inside repeatability). **Calibration reading:** all 60 decisions mean 0.03236 / max 0.21893;
    closed-loop (n 30) mean 0.00418, MEDIAN 1e-5, max 0.124; open-loop (n 30) mean 0.06054, max
    0.21893 — closed-loop prediction is exact and ALL error is open-loop, exactly the designed
    structure, and the live max sits under the offline Gate-1 0.25. `ems-ftp75-mpc` confirms it over
    345 decisions (closed n 115 median 1e-5 max 0.110; open n 229 mean 0.04450 max 0.19924). Keep the
    0.30 band. Solve times med 4.5–4.6 / max 6.5–6.7 ms, 0 budget hits of 61 000 ticks. The
    information ablation is measured: `mpc-sto` commands cruise share 0.50 against det's 0.6667 for
    26 s, −22.5 % h2 (0.00808750 vs 0.0104346 g) at +38.7 % drain (ΔSoC −0.00351 vs −0.00253); the
    value of preview is 0.36 % of eq-H2. ⚠️ **Cap caveat:** `MPC_CAMPAIGN_MAX_CANDIDATES` 343 equals
    ONE charge option's enumeration (7³) and no-charge is enumerated first, so on every capped decision
    (13 of 61 on mpc-sto) the cap truncated BEFORE the charge axis — **"the MPC chose not to charge" is
    not a supported reading of ANY leg** until the cap is lifted.
  - **Double era boundary (cross-cutting).** Campaign 151156 predates BOTH the charger change and the
    converter-asymmetry default (its sidecars carry no `asymmetry` key; every run here carries
    `asymmetry: measured, dv0 0.013522 V, droop_scale_fc 0.9434`). Every non-charging drift found here
    is asymmetry-era, and three repeatability records BREAK: `ems-sdp` +0.61 % with `cmd_share_sp`
    bit-identical over 61 000 rows (**the 8 ppm record is broken by the plant, not by sdp-v4**;
    `I_fc` first diverges at t = 0.540314 s, 0.0790 → 0.0923 A, the +ΔV0 FC-bias direction),
    `scp-inrush` i_cut **6.362275 vs 6.379737 A (−0.27 %) — the 10-for-10 bit-exact record is broken**,
    `comm-loss` re-close NO LONGER SYMMETRIC (I_fc 0.3802 / I_batt 0.3381 A against 151156's
    0.3591/0.3591; the 0.35915 A mean survives — **report both channels from now on**), plus
    `soc-depletion` latch +272.6 ms and low-current h2 +15–16 %. The conventions claim that non-charging
    legs compare bit-identically across the charger boundary is FALSE across 151156.
  - **Replay share-guard coverage correction.** The 151156 statement "no replay can exercise the fw v25
    share-cut guard" is half wrong: the suite cannot SCORE it (0 `events.jsonl` across 27 folders), but
    the firmware path IS exercised on **163 in-Run FC_BUS/BT_BUS falling edges** across six opt-in
    replays (ML0203 119, YP0196 23, ML0151 13, YP0214 4, ML0165 3, ML0137 1). CSV-bounded `i_cut` over
    0.5 A: 8 on the cut's own row (max 0.6608 A), 4 on the preceding row (max 0.5722) — **not a defect
    claim**, unresolvable at the 1.9 ms round-trip with ~0.08 A tick noise. Also unscored: 58 of
    ML0203's 119 cuts follow a dwell < 5 ms (min 0.5 ms), and ML0151 cuts a channel 2.0 ms after its
    own rise, inside an unfinished CSS soft-start the survivor-keyed blanking does not cover.
  - **Operator note — power-on INIT_FAIL.** The campaign's first run (`steady`) opened with a latch
    already set on the board, **0xa010 / error_code 0x0e INIT_FAIL at t = 0**, after the operator's
    evening re-flash; it self-cleared in grace. Worth a look at the power-on path.
  - **Frontier.** `cycle61` PASS: eq-H2 0.0116428367 g vs reference 0.0120876284 g = **0.9632×**
    (ask ≤ 0.98) and vs bound 0.0116243533 g = **1.0016×** (ask ≤ 1.06), stable over λ ∈ [0.409, 0.415].
    `ftp75` UNVERIFIED (its socband reference failed its own checks) but WOULD have read 0.96559 /
    0.99864; ⚠️ **49.6 % of that candidate's eq-H2 is the λ correction** (ΔSoC gap 21× cycle61's), far
    more λ-sensitive than cycle61 — quote with care. Both MPC tuples UNVERIFIED on the sidecar crash.
    The vs-bound arm remains structurally ≈ 1.0 for any charge-free pair.
- **`docs/HIL_PLANT.md` adversarial review (run 001, `docs/reviews/hil-plant/run-001-2026-09-02.md` +
  `docs/reviews/hil-plant/ledger.md`).** Codex round 1 raised eight findings; round 2 conceded or
  refined every one. Final: **three major** (F1, F2, F4), **five minor** (F3, F5–F8) plus N2 minor and
  N1 nit, and **N4 open-unverified** (`FC_BUS.i` as an INA proxy may under-report a bus load step by
  half at one operating point — needs a reproducible operating-point test before any doc entry). Three
  physics corrections matter beyond the doc. (F2, major) The "6.5 % bus-sourced regen leak" was
  **misattributed**: `MOT_PWR` is strict-forward, so the contribution is exactly ZERO while the chopper
  clamps (bus-fed clamping would need V_BUS > 18.135 V, above the 17.5 V latch) and appears only AFTER
  clamp release, as **0.088059 J / 0.118 W of bus-fed CHARGING** through a forward-conducting `MOT_PWR`
  (V-MOT at V_BUS − 35.3 mV, 14.93 mA; deleting the link gives 0.000000 J) — the co-solve
  `TODO(verify)` is RETIRED and the 0.15 J / 12 % aggregate ceiling is replaced by two mechanism
  assertions. (F4, major) "Open loop never writes the MDACs" is FALSE: the HOLD is conditional and the
  slew-limited **FEEDFORWARD** submode does write them (**356 write ticks measured on `ems-y-b00-v3`**)
  — this is the MPC Gate-1 mechanism, now confirmed in the firmware source and on the board, and the
  standing walk rule becomes "model the open-loop hold **AND** the feedforward slew". (F1, major)
  **Observation-frame byte 15 is a fiat mirror under `HIL_SIM`** — the threshold manager is never
  called, the regen exclusion is bypassed, 11.8 % of ticks differ (max 12 counts), and two suite labels
  assert that the manager ran. Rejected: firmware gating of the mirror, the precharge hypothesis for
  the leak, braking-masked balance plots, unscoring the DP on regen-bearing scenarios, and the
  host-dependent-verdict claim. No firmware, protocol or coefficient change.
- **Fix rounds (docs `7026e3b`, tooling `6c28dd2`).** Docs: the F1–F8/N1/N2 corrections in
  `HIL_PLANT.md`, the manual, `HIL_MODE.md`, `HIL_REPLAY_LOGS.md`, `HIL_SCENARIOS.md` and
  `mpc_design_20260901.md`, plus the conventions file (`asymmetry` added to the run-era fields; the
  bus-draw ratio marked probe-point-specific, 0.5565 → 0.64 at a 14.1 V bus; the replay share-guard
  coverage statement corrected) and the walk rule in this repo's skill. Tooling — **the
  scoring-semantics changes the next campaign's analysts must know:** `scan_signals()` now implements a
  **numeric-column `min_ticks`** threshold counter, with an import guard refusing unimplemented spec
  pairings (`regen_clamp_dwell` KEEPS its 800 floor); the **mppt mirror pin is peak-form** over a window
  clear of the regen-lifted braking windows, and `mppt_threshold_written`/`_moved` are relabelled as a
  carried mirror; the **socband FC tripwire is split** into a charge-free arm ≤ 0.85 A and a
  charge-window arm ≤ 1.25 A, using a new **`exclude_when_switch_bit`** masking term, with
  `socband_fc_carried` re-pointed at the charge-free peak and the h2 band re-derived to [0.034, 0.051];
  a **`substep_resolution`** gate (n_min ≥ 8) with `elec_substep_n` logged; the replay half gains a
  **`share_cut_census`** entry that is a NOTE, not a scored check (baseline 163 cuts / max 0.6608 A),
  and **`not_exercised` markers** so an unexercised check reads as a count rather than a red tick;
  **`MPC_CAMPAIGN_MAX_CANDIDATES` 343 → 1029** so the charge axis is reachable; and the console is
  made **cp1252-lossless with sidecar/event finalization moved into a `finally`** ahead of any summary
  print, with the binder's `except` narrowed so a `UnicodeEncodeError` cannot masquerade as a bind
  failure. Matched-DP prefilled for the seven η-era EMS keys (dp-replay −0.20 %, sdp −0.35 %, soc-band
  +3.87 %, ftp75-5050 +5.73 %, -dp +4.35 %, -sdp +8.53 %, -socband +7.45 %). Suites at close: **1795
  stdlib / 1997 numpy green.**
- **Campaign C (`hil_report_20260902_041414`): <PENDING — filled by the orchestrator>** (launched from
  `6c28dd2`, `--with-ftp75 --with-alpha`; it validates the cp1252/finalize fix on the five re-run legs,
  the numeric `min_ticks`, the mppt peak-form pin, the socband split, the substep gate and the MPC cap
  1029 with the charge axis reachable, and takes a second reading of the η-era levers while re-pinning
  the asymmetry-era baselines).
