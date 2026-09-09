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
- **Coverage inventory:** see PLAN.md §§9–14 and the per-file headers in `test/`.
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
`docs/claude-md-archive.md` to keep this file under the memory-size limit. Eleven ranges are
archived. The eleventh (rotated 2026-09-09, evening) holds the 2026-09-03b and 2026-09-03c daytime addenda (physics review run 002, the governor split law, sdp_policy_v5; then sdp_policy_v6, N8, Step 0, the 4x droop loss, the I_AUX_A 0.09 A era, fw v27 rev 2), superseded by the 2026-09-04 and 2026-09-08 addenda; their load-bearing facts survive in `docs/modeling/governor_split_law_20260903.md`, `docs/modeling/sdp_alpha_resolve_20260903.md`, `docs/firmware-versions.md` row 27, `docs/HIL_PLANT.md` and WORK_QUEUE.md. The tenth (rotated 2026-09-09) holds the 2026-09-03 overnight addendum (fw v26 on the board: campaigns D, E and F, the bleed-era baseline, the loss-map bound, the MPC 0/1 enumeration, the clamp's step-transient limit), superseded by the 2026-09-03b/c and 2026-09-04 addenda; its load-bearing facts survive in `docs/HIL_PLANT.md`, `docs/fw26_current_ceiling_governor.md`, `docs/modeling/` and the campaign ledgers. The ninth (rotated 2026-09-08) holds the 2026-09-02b fw v26 current-ceiling governor addendum, superseded by the 2026-09-03 addendum's board calibration; its load-bearing facts survive in `docs/fw26_current_ceiling_governor.md` and `docs/firmware-versions.md` row 26. The eighth (rotated 2026-09-04) holds the 2026-09-02c DP-bound addendum (per-node bleed, loss map, droop-mode bus law, ftp75c + regen term, grid widening, mpc-sto default), superseded by the 2026-09-03 addenda; its load-bearing facts survive in `docs/HIL_PLANT.md`, `docs/modeling/` and WORK_QUEUE.md. The seventh (rotated 2026-09-03) holds the 2026-09-02 overnight addendum (Ag105 eta 0.88 in
both engines, the eta-era DP/SDP and sdp_policy_v4, the governor-aware MPC, campaigns B and C, the
HIL_PLANT.md adversarial review run 001), superseded by the 2026-09-03 addendum; its load-bearing
facts survive in `docs/HIL_PLANT.md` section 4.6, `docs/reviews/hil-plant/`, `docs/modeling/`,
`WORK_QUEUE.md` and the campaign ledgers. The sixth (rotated 2026-09-02c) holds the 2026-08-16c and 2026-08-25 addenda (fw v14 K_F force-axis correction; fw v18 90-slot wheel and general-Hanus anti-windup), superseded by fw v25 and preserved in `docs/firmware-versions.md`. The fifth (rotated 2026-09-02b) holds the 2026-09-01e–f addenda: the
EMS test-program round (campaign 151156 as the first fw v25 campaign; tools/governor_model.py and
tools/ems_walk.py; the ΔSoC-matched DP post-pass and tools/dp_db/; the α-sweep; the converter-
asymmetry fit and its plant injection; FTP-75 preload removal; the Pi-bridge v4 audit) and the
power-balance figure / refined α-sweep round. Their load-bearing facts survive in
`docs/HIL_USER_MANUAL.md` §3.2.5, `docs/modeling/`, `docs/PI_BRIDGE_V4_AUDIT_20260901.md`,
`WORK_QUEUE.md` and the 151156 ledger. The fourth (rotated 2026-09-02) holds the 2026-09-01a–d addenda, that is the fw v24
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

## Status & session addendum (2026-09-04, overnight: campaigns G + G2 on fw v27 rev 2 - the first board readings of the governor package, one firmware sequencing defect, the tools fix round)

Overnight autonomous session from `22e8cc8` (mandate: "fw v27 is flashed, begin the overnight campaign";
OVERNIGHT_LOG.md session 2026-09-03/04 carries the assumed protocol, decisions D-1 to D-3 and the
morning digest). **fw stays v27 rev 2 (`153562f`) on the board; no flash, no firmware change overnight.**
Campaign G `hil_report_20260903_233736` (75 planned, 61 executed, 14 vacuous SKIPs: `drive`, 3 alpha and
the ten long-cycle legs, which are OPT-IN behind `--with-ftp75 --with-ftp75c --with-alpha` - D-3) + G2
`hil_report_20260904_003108` (the ten long-cycle legs) count as one campaign; tooling `1e0abd4` from a
detached worktree. Suite 63/75 and 3/10; every FAIL classified live; **zero board defects outside fw v27's
own new mechanisms.** Ledgers, FINAL SUMMARY and HIL_SUMMARY in both folders (local-only).

- **Board-real fw v27 SEQUENCING DEFECT (operator, fw v27 rev 3 / v28 - WORK_QUEUE 0d F1):** the
  battery-only arm is suppressed, not disarmed, when an FC-charge window opens, so from a still-cut state
  `assertFcChargeEnable()` re-closes FC_BUS and drops BT_BUS/REGEN in the SAME tick; the RT1987 8 ms turn-on
  delay leaves the bus source-less, V_bus collapses at I_AUX/C_VBUS (2.57 V/ms) to the sim's 5 V aux floor
  and the UV_BUS dwell reaches 19.07 ms (charge-to-full, standstill) / 17.9 ms (ftp75c, two regen early
  releases) against the 20 ms latch. fw v26 on the same stimuli: a 37 mV step. **The arm never releases on
  any cycle whose total stays under the 0.30 A gate** (standstill; the compressed ftp75c cycle, max 0.278 A),
  so those legs run battery-only for the whole run (ftp75c h2 -99 %, the pack drained; regen harvest itself
  unchanged at 19.24 s / 0.7365 C / 5.47 J). Preferred fix: clear the arm one commander period before
  FC_CHARGE opens so the latch's guarded release re-closes FC_BUS onto a live bus. Hardware question: the
  VESC below the sim's 5 V floor (the Teensy is on the battery regulator).
- **Three more fw v27 consequences (design items F3-F5):** totals in 0.25-0.30 A keep the loop closed below
  its own entry gate with an empty minority band -> delivered split pinned at exactly 0.5000 (0.14 A per
  channel) for whole cruise spans (ems-sdp-cross: charge period 17.1 -> 25.2 s); the scheduled k_d saturates
  in single-source charge windows (0.906 ohm, mdac_fc at 4095, single-source droop x3, charge-window sag
  x3); the halved floor now equals SHARE_HANDOFF_MIN_A, so a channel at the floor reads dark and the load
  guard cut/restores it (58 en_low cuts over 90 s on ems-ftp75-sdp, max 0.21 A, safe).
- **What fw v27 measured correctly:** the battery-only start on every leg that reaches Run (cut at State-2
  entry at 0.0576 A, re-entry 3-22 ms after the ~20 ms EMA crosses 0.30 A, exactly one rise; the release
  totals 0.2549-0.3288 A on the replays calibrate the gate); the fw v26 clamp settled at 1.2502 A a third
  time; the sweep passed all 12 regions at I_min 0.15 (peak 1.3295 A); **the joint leg's first execution:
  peak 1.3243 A vs the 1.3241 A bound (one sample; 5.4 % under the limit), and the miss is a NAMED walk
  gap - the share loop's own ~20 ms feedback EMA lets the reference overshoot the clamped rail by ~3 % of
  r for ~12 ms (+0.039 A, half the ceiling margin at 1.57 A; F6)**; bring-up P0 0.1512 A = the AUX-ERA pin;
  scp-inrush 6.354320 A (-0.094 %); soc-depletion latch +12.665 s (54 % of it the linear aux model);
  charge-cruise latch +24.7 ms (98 % the aux era); the re-entry turn-on overshoot on inherited MDAC codes
  (0.2355 A, ~12 ms; F7).
- **Sim / tooling findings:** `comm-loss` = a SIM ARTEFACT (the RT1987 soft-start ramp rates are identical
  only at v_ss_start = 0; the aux-era floor leaves the bus at 0.44 V at the warm re-close and 1.79 A
  circulates through 21 mOhm; the board's OC_FC latch is correct); the one-sided SOFT stamp cuts it to
  3.75 A, the constant-slew ramp (moves the cold pins) is its own A/B round. The MPC delivery table had no
  branch for the firmware-initiated battery-only start (pred ~0.55 vs delivered 0 for 2.7 s on ems-mpc /
  -det / ems-ftp75-mpc; `ems-mpc-single` the positive control at 0.0001) - added, on a BT-only preview.
  Six aux/fw27-era scoring items (charge-cruise's teardown anchor shadowed by a carried-in OC_FC; ems-sdp's
  drain plateau moved to demand bin 21 where both v4 and v6 tables ask 1.00 -> clamped 0.85, board clean,
  ruling on the stimulus knob open; ems-y-b30-v1's 1.02 A guard; sdpx / sdpb pins; mppt window) fixed or
  re-pinned from measurement, never widened. Replay half 27/27 real; fw v27 visible on three unscored axes
  (battery-only starts; FC MDAC codes saturating at 4095 below the 0.906 A crossover; share-cut census x5.3)
  -> a report-only topology census and ratio tagging added.
- **Frontiers:** cycle61-sdp legs comparable (ems-sdp's FAIL is scoring-side; delivered share exactly 0.8500,
  h2 +0.34 % vs the fw v27 walk); the MPC frontiers UNVERIFIED (surrogate-side FAILs, h2 within 0.3 % of the
  walk); the ftp75c frontier meaningless this campaign (battery-only by the defect); all 75 matched-DP
  records are provenance_drift after the I_AUX_A change (re-solve queued).
- **Campaign H (`hil_report_20260904_022637`, tooling `c708d71` = the post-G fix round, full plan):** 63/75, the
  twelve FAILs exactly the pre-classified set, every tools fix validated on the board; the firmware defect
  LATCHED (State 99) on ems-ftp75c-sdp (20.12 ms) and -socband (20.22 ms, via a charge-window handoff - a
  third trigger); the joint leg's transient peak read 1.2699 A (G 1.3243; settled point identical - the bound
  needs a third reading); comm-loss re-close 1.6622 A (still latching; the sim fix over-predicted its residual
  2.26x); `ftp75` the first fw v27-era frontier to VERIFY (0.9703 / 1.0011). Budget 2 of 5; stopped after H.
- **Open operator rulings:** F1-F7 (WORK_QUEUE 0d spec seed); the ems-sdp stimulus knob; the RT1987
  constant-slew ramp A/B; the MPC delivery-table residual past the release (the stale committed plan).

## Status & session addendum (2026-09-08, daytime round: fw v28 source-selector package built and reviewed - PENDING FLASH; the encoder-defect harness; the fw v28 tools mirror queued)

Operator-present round after the campaign G/G2/H digest. Rulings (WORK_QUEUE section 0e, memory
`operator-rulings-2026-09-08-fw28`): F1 fixed the preferred way; the never-closed region SELECTS battery-only or
fuel-cell-only from the commanded share (inclusive 0.85 / 0.15); the forced-0.5 sliver becomes a hold;
`SHARE_MINORITY_I_MIN_A` 0.15 -> **0.125 A** (D = 0.25 V); handoff thresholds 0.10 / 0.12 A; k_d held in
single-source windows; F7 recorded only. Commits `4e20b76` (queue), `a683e25` (encoder harness), `9318e16`
(**fw v28, PENDING FLASH**). fw v27 rev 2 stays on the board until the operator flashes.

- **fw v28 = the source-selector package** (`docs/fw28_source_selector.md`; ledger row 28). (1) **F1:**
  `chargingControl()` DISARMS the selector (on EITHER cut, review S5) instead of calling
  `assertFcChargeEnable(true)` while it holds a channel off the bus, and opens FC_CHARGE only when FC_BUS reads
  HIGH and is out of its turn-on blanking (conduction-gated, not period-counted); the latch's own guarded release
  re-closes FC_BUS onto the battery-fed bus in the same loop iteration (`chargingControl()` precedes
  `powerBalance()`), so the window opens one commander period later. CONSEQUENCES: a non-selector FC cut
  (Pi-commanded 0.0, `shareIsoFC`) keeps the window closed for as long as it stands; the disarm ends the
  never-closed regime for the rest of the profile. The State-98 `'5'` key now REFUSES to open with FC cut and
  FC_BUS LOW (review S6; the S2 restore inside `assertFcChargeEnable()` is unchanged and otherwise unreachable
  from the charge path); `RT1987_T_D_ON_MS` 8 with `static_assert(SHARE_CUT_SURVIVOR_BLANK_MS >= ...)`.
  (2) **The SELECTOR** replaces the battery-only arm's "disarm permanently on an out-of-band command" and its
  FC-charge suppression: commanded share >= `DROOP_R_MAX` selects FC, <= `DROOP_R_MIN` selects BT, in between the
  selection HOLDS (the Pi clamps to 0.85, so the thresholds are inclusive); the effective setpoint is 0.0 or 1.0,
  always latch-owned; a selection change is release -> one returned tick -> entry through the existing guards
  (make-before-break by construction; the 0.5 A load guard always admits under the 0.25 A gate); the gate release
  works from either source. **Review S2 (HIGH, accepted):** FC-only under the gate has no current bound (the fw
  v26 ceiling is inert single-source; OC_FC latches on one raw sample) - a raw `|I_fc| > SHARE_GOV_I_FC_CEIL_A`
  drops the arm immediately while FC is selected (the one deliberate raw-sample gate in the governor). The SDP v6
  policy commands exactly 0.0 above its SoC target and 1.0 below at every low-demand bin, so the selector is
  policy-driven on the ftp75c legs (FC-only below target). (3) **The sliver holds** `share_spEffPrev` bounded to
  `[loD, 1 - loD]`, `loD = min(0.5, SHARE_HANDOFF_MIN_A / I_tot_filt)` (review S3: an unbounded hold could park a
  rail reference at 0.03 A of minority; the live threshold would reproduce the 0.5 pin). (4) **Constants:** gate
  0.25 A, exit 0.20 A, crossover 0.755 A, authority 0.227 V (0.252 V at unity), max scheduled k_d still 0.906 ohm,
  fw v26 reachability still 1.4706 A (floor term 1.375 A); `SHARE_HANDOFF_MIN_A` 0.10 / `SHARE_HANDOFF_LIVE_A`
  0.12 (a minority at the floor reads live; two live channels need 0.24 A, so the HANDOFF slew ceiling is now
  selected whenever the filtered total is under the gate - review S7, spent-dwell escape retained). (5) **k_d**
  targets `K_DROOP` only while FC_CHARGE is HIGH (writes continue, the slew is real); k_d AND its schedule input
  are FROZEN while any `shareIso*`/`shareSpCut*` is set (review S4: a scale slewed with no MDAC writes would be
  applied as a 3x step on release). HIL aux byte bits 6 / 7 = armed / FC selected (frame 18 B unchanged); BLG stays
  v8 (the selection has no bench-log field - inferred from the currents); no wire change; `FW_VERSION` 28.
  Tests **4207 / 175 / 4694**, 0 warnings (fw v27 rev 2: 4114 / 175 / 4596): both selection directions tick by tick,
  the raw-current escape, the `'5'` refusal, the sub-gate handoff rate, the k_d freeze under a real isolation cut
  (the first version was vacuous - self-healed the same tick), F1 from every start state; four `chargingControl()`
  fixtures had passed with FC_BUS never driven HIGH and were repaired. Residuals recorded: F7 (inherited codes on
  every selection change), a BT_BUS opened WITHOUT FC_CHARGE (`'2'`, the backoff's refused re-close) is single-
  source the schedule does not detect, the sliver's strict `lo < hi` at the exact gate, the spent-dwell escape.
  BENCH GATES unchanged in kind: the fw v6 ladder at 0.125/0.875 and the two-axis dropout sweep (CAL-6).
- **fw v28 REV 2 (`ded47f3`, PENDING FLASH; operator ruling from the harness finding): encoder direction-sense
  AUTO-FLIP on positive-feedback runaway, NO fault.** `encDirSign` applied at the six non-zero `v_actual` publish sites
  of `updateWheelSpeed()` (ISRs and velocity math byte-identical; inert under HIL_SIM). A tick qualifies when not in
  State-98 manual-current mode, sign(current) == -sign(v_actual), |v| >= 0.30 m/s, |current| >= 0.5*MOTOR_I_CMD_MAX,
  the magnitude is ratchet-non-decreasing (0.02 m/s tolerance) and `encVelHaveValid`; 500 consecutive ticks AND the
  window must have GROWN by 0.10 m/s (review: a constant-speed drag stall against the rail - incline, dyno - would
  otherwise flip a correctly wired encoder). On a flip: sign inverted, the live `v_actual` negated so the same tick's
  motor command is corrected, `resetDriveControlState()`, one ASCII line, 5 s lockout, cap 4 per boot; the sign
  survives 'Q'/warm reset (a wiring fact; power cycle resets it; no EEPROM). **A wrong flip is SILENT and PERMANENT for
  the boot** (condition 1 fails every tick afterwards), so the entry test is the only real lever; the lockout and cap
  bound repeated genuine detections. No wire-level observable (aux byte and BLG flags full). Harness: the 180 deg
  case now flips exactly once and recovers to +1.00 (rail occupancy 19 900/20 000 -> 804/8000); near-aligned jitter
  never flips. Tests 4318 / 175 / 4699, harness 51, 0 warnings.
- **fw v28 REV 3 (`7482395`, PENDING FLASH; operator ruling): the encoder direction sense PERSISTS across power
  cycles** - a 4-byte EEPROM record at 4276 (magic / sign / generation / checksum) read in `setup()`, written only
  at a runaway flip via `EEPROM.update()` (<= 4 per boot against ~100 000 cycles), a blank or corrupt record leaves
  +1 and writes nothing; a stale stored sign on a re-wired board is corrected and re-stored by the detector within
  the same window; not applied under HIL_SIM (read and mirrored only); State-98 `'Z'` clears it (PLAN.md 9b).
  Residual for the operator: the write is a blocking flash operation on the flip tick, duration TODO(verify: PJRC).
  Tests 4367 / 175 / 4704, harness 51.
- **fw v28 REV 4-6 (`5d281d8`, `a09d1ca`, `f0d82e4`, PENDING FLASH - the flash target is REV 6):** rev 4 defers
  the EEPROM commit off the flip tick (loop-level, `logDrainTick()` discipline, survives a State-99 latch, `'Z'`
  cancels) and keys the k_d single-source hold on bus TOPOLOGY (exactly one bus switch HIGH -> K_DROOP slewed; both
  LOW -> hold; flagged cuts freeze). Rev 5 (operator ruling): THE RE-ENTRY RULE - in the closed-before open-loop
  region an out-of-band command (inclusive 0.15 / 0.85) RE-ARMS the selector with that source and it then behaves
  as the never-closed selector; in-band commands keep the hold; a safety disarm (raw escape, F1) sets an INHIBIT
  that only a strictly in-band command clears; **BLG v9** (116 B: selector_bits @112 - bit0 armed, bit1 FC, bit2
  re-armed, bit3 EEPROM commit pending, bit4 re-arm inhibit; enc_dir_sign i8 @113; enc_dir_flips u8 @114; spare
  @115; drain chunk 4 records = 464 B). Rev 6 (safety review of rev 5): the inhibit survives a full iteration and
  any latched cut (the review's path re-armed before a window opened - the campaign-H UV_BUS class); a 250 ms
  SELECTION-CHANGE dwell (<= 4 commutations/s; an un-dwelled 50 Hz dither would commutate ~32/s and starve the
  gate release by re-zeroing the filter); the frozen path advances the filter for ANY latched cut so the rule is
  reachable when the rail command precedes the fall; Idle clears the selector observables. Tests 4503 / 175 /
  4810, harness 51. Tools follow-ups queued: the governor_model mirror of the topology re-key, the re-entry rule,
  the dwell and the inhibit; the BLG v9 decoder.
- **Host-native encoder-defect harness (WORK_QUEUE 7d, `a683e25`):** `tools/encoder_edge_script.py` (mechanical
  law transcribed from `hil_plant_sim.PlantState.step`, equivalence pytest bit-identical; geometry asserted
  against the `.ino`; five defect scripts; manifest; 41 checks) + `test/encoder_defect_harness.cpp` as the
  fourth target `run_tests_encoder` (43 checks; edges through the real ISRs at their own micros, the drive loop
  closed on the firmware's own estimate). First sweep (2676 runs): **the missing-slot halving basin no longer
  exists** (0 of 1080 absorbing to n = 80 - the fw v15/v17 ledger removed it; the spec's named unknown answers
  "never"); staleness onset = ceil(100 ms / T - 1) pitches; the T/2 basin is unreachable from an isolated bounce;
  **a 180 deg phase error gives a sign-inverted reading with the drive railed for 19 900 of 20 000 ticks and NO
  fault** (no encoder-sign plausibility check exists in `detectFaults()`; `encPhaseEwma` reads 0 under inversion,
  indistinguishable from no data) - an open firmware item for the operator; jitter collapse at ~0.6 of the quarter
  pitch; near-aligned + jitter reproduces the ML0140 signature. `docs/encoder_defect_harness.md`. The `run_tests`
  hook for its regression mode is still to be added to `test/test_main.cpp`.
- **Tools rounds (evening):** the fw v28 mirror parts 1 + 2 (`1549067`, `e7ab118`: governor port + equivalence harness,
  MPC delivery table selector-aware, the 23-leg re-walk table, F6 reported not applied; Gate 1 in-band: mpc-det passes
  5e-3 by 2-3 orders, all four mpc-sto legs fail - first six-leg measurement); the **RT1987 constant-slew ramp A/B**
  (`66dea4b`): LEGACY STAYS THE DEFAULT - constant-slew (datasheet 645.5 V/s, VIN- and start-independent) moves the
  hardware-corroborated cold bring-up pins AWAY from the board (P0 -8 %, P3 -18 %) and neither shape brackets the
  comm-loss re-close (legacy 3.75 A, constant-slew 0.139 A, board 1.66-1.79 A latching OC_FC) - the residual is
  elsewhere (boost output impedance, RT_R_ON, C_VBUS; each a measurement round); both shapes selectable and
  era-fingerprinted. `c11a464`: BLG v9 decoder (v7/v8 unchanged, 464 B drain chunk), `ASYM_SIMPLE_I_MIN_A` 0.08 A
  (better conditioned at the floor than at full load; idle split 0.25 -> 0.365), `--droop measured` = k_d + dV0 +
  R_f scaled together (CAL-1 RMS 0.0090 vs 0.0457 k_d-only; the 39 slope fits prefer a NEGATIVE intercept - the
  +0.033 ohm floor is not bench-supported at 0.2117, awaiting the DMM measurement), governor_model mirror of rev
  4-6 (27 cases / 31 413 rows / max code delta 0). `70e4543` + `0063f8e`: the alpha sweep at the measured billing
  (charge boundary 0.126 -> 0.1385 = x0.88/0.801 exactly; alpha 0.13411 sits 3.2 % BELOW it - v6 rejects charging
  endogenously; the drive cycle lost its charge discrimination) and the three alpha legs rebound (greedy 3 / cal 8 =
  v6 byte-identical / charge 15) under the SUITE walk configuration - the sweep's walk omits the asymmetry triple
  and on a share-0 map that decides the FC floor's delivery (3.3x on the greedy leg). Rulings: ems-sdp accepted as
  a CLAMP WITNESS (the v6 ask flips on the SoC target row, every above-target ask clamps to 0.85); matched-DP
  re-solves HELD until the overnight campaign. Open: WORK_QUEUE 0e item 21 (the mpc-det/mpc-sto bit-identity test
  now fails by 3e-5 - re-adjudicate, not bump).
- **CAMPAIGN READY:** flash fw v28 rev 6 `f0d82e4`; tooling `0063f8e`; detached worktree, opt-in legs on.
- **Queued (WORK_QUEUE 0e items 8-11):** the fw v28 tools mirror (governor model + fw v28 equivalence harness,
  ems_walk, the MPC delivery table selector-aware, FW28-ERA anchors, every designed-total stimulus re-derived at
  0.125 A, F6 in the walk), then the first fw v28 campaign after the operator's flash. Open rulings unchanged
  (`--droop measured` scaling, `ASYM_SIMPLE_I_MIN_A`, the ems-sdp bin-21 knob, the RT1987 ramp A/B, the MPC
  residual past the release, hold vs return-to-battery on re-entry).

## Status & session addendum (2026-09-08/09, overnight: campaign I - the first fw v28 campaign; F1 closed on the board; the operator stops after one campaign for the H2-consumption-model update)

Operator-approved overnight schedule (OVERNIGHT_LOG.md session 2026-09-08/09), then the mid-campaign ruling "once the
current HIL suite completes, stop the campaign - we're going to work on a significant update to the H2 consumption
model". fw v28 rev 6 `f0d82e4` on the board; tooling `60abb34` (`07add95` = WORK_QUEUE 0e item 21, the mpc-det/mpc-sto
test re-adjudicated for the selector hold) from the detached worktree `DC-Balancer-I`. Campaign I
`hil_report_20260908_200836`: 74 executed + `drive` SKIP, suite 66/75 (65 substantive PASS, 9 FAIL, all classified),
944 checks, wall 1:42:15; 27/27 replays substantive. Ledgers local under `HIL Results/`. Budget 1 of 5. The primary
worktree moved to the operator's branch `h20-convex-h2-map` mid-session; the close-out commits are on main from a
separate worktree (`DC-Balancer-main`).

- **Zero board defects. F1 CLOSED on all three recorded triggers with ZERO UV_BUS ticks campaign-wide:** charge-to-
  full (standstill; H dwelled 18.20 ms) - disarm + FC_BUS re-close on one tick at 8.025433 s, FC_CHARGE 39.9 ms
  later (TWO commander periods, the design record says one), V_bus min 15.7342 V; the compressed-cycle regen early
  releases on four legs at 67.223-67.228 s (arm standing 64 s, FC_BUS re-closed within 1.0-1.1 ms onto the battery-
  fed bus, V_bus flat at 15.807 V, no window opens because the intent lapses) and from a RE-ARMED state at 171.053 s;
  the charge-window ENTRY trigger that latched H's socband at 107.9 s is structurally gone (17 windows, all 0x27 ->
  0x35); FC-selected (ftp75c-sdp 67.219 s, sdp-braking 82.678 s) the window opens on the disarm tick with a 16 mV
  excursion. FC recharge inrush 0.115-0.24 A (fw v27 0.75-1.34 A). 40 window openings, dips 59-390 mV.
- **Every fw v28 mechanism measured:** the 0.25 A gate releases at 0.2502-0.2888 A on ramps (fw v27 0.2549-0.3386),
  0.4905 A on a step; every regression-leg h2 move vs H (+0.1 to +1.3 %) is the earlier release, within 0.11 pp of
  the walk. The FIRST FUEL-CELL-ONLY SELECTION on the board (ems-sdp / alpha-cal / alpha-charge / sdp-braking arm FC-
  selected under 0.85, switch 0x25, and RE-ARM FC-only on the coast-down at ~54.17 s; ftp75c-sdp FC-only 64.2 s);
  battery-only re-arms on the 0.15 rail; the in-band HOLD (ems-y-b00-v1 region 7 until the gate re-crossed - the
  check's 2000-tick floor encodes fw v27's isolation release: a scenario re-spec); the re-entry condition from both
  sides (b00-v1 at 0.14 A vs b00-v3 at 0.26 A); the rev 6 inhibit keeps a permanent-rail policy two-source after an
  F1 disarm (ftp75c-sdp, walk -9.5 %); the 250 ms dwell never exercised. The SLIVER HOLD (F3) direction-correct
  with the minority at exactly 0.125 A (0.5562 / 0.4442 / 0.5552 / 0.5436 where fw v27 pinned 0.498-0.501). The k_d
  HOLD (F4): codes 4067 / 717 post-settle in 17 charge legs (fw v27 railed 4095), entered at the slew bound in 21-
  43 ms; mppt-tracking's predicted plateau rise did NOT appear (V_bus -0.02..+0.01 V, a null result). The gate does
  NOT release the arm on the compressed cycle (filtered peak 0.157-0.179 A): the release there IS the F1 disarm - the
  re-walk block's premise is wrong for that family (rows ~39 % low).
- **REAL fw v28 design consequence (operator ruling item): the FC minority chatter SURVIVED F5.** ems-ftp75-sdp: 71
  r-based FC cuts / 90 s at a sustained 0.15 command with the selector disarmed, I_fc 0.134-0.168 A at the cut (above
  both handoff thresholds and the floor): the share PI winds its reference strictly below DROOP_R_MIN chasing the
  split law's delivered 0.17 (R_FC 1.92 vs R_BT 0.39 ohm at the rail), the fw v25 load-guarded r-path cut in
  `applyShareRatio()` fires at light load, re-entry follows at the hysteresis, ~0.8 Hz - fw v6's accepted "rail-
  saturated dropout cycle" (rate +16 % vs fw v27; dwell <= 12.4 ms, i_cut <= 0.2236 A, benign). A 100-tick DP visit
  to 0.15 does not wind through (ems-ftp75-dp 0 cuts); ems-sdp-cross adds 41 bus-switch cuts (28 FC_BUS / 13 BT_BUS; 5 dark / 36 loaded at 0.10 A on the preceding row, 3 at exactly 0 A).
  Candidate closure: clamp the PI reference at DROOP_R_MIN with anti-windup for in-band commands.
- **The MPC ladder's 0.15 / 0.85 endpoints ARE the selector rails:** at stops the 0.15 rung re-arms battery-only and
  the hold costs unbilled FC time (ems-ftp75-mpc 60.75 s, -9.9 % FC coulombs; ftp75c-mpc 70.6 % armed; ems-mpc's 54 s
  re-arm; -det passes because its plan holds the rail). `Planner.delivery_table()` has no armed-HOLD state = 100 % of
  the prediction residual on four legs (H's rise-tick T6 gap is no longer the peak). EMS-design ruling: endpoints
  strictly inside the band, or teach the stage model the hold. ems-mpc-single's 18 exact-0.0 commits executed as fw
  v25 setpoint-latch cuts (0.11-0.49 A, 9-39 ms deferral); eq-H2 ties mpc / det / single to 0.13 %.
- **Tooling defects found:** (1) `tools/ems_walk.py` delivers share EXACTLY 0 on a 0.15 floor reference whenever the
  asymmetry triple is on (401/610 cruise stages on the greedy policy) - the ems-sdp-alpha-greedy FAIL is FALSE: the
  board's 0.0030376 g / delivered 0.1714 is the split law to 0.1 %; the 2026-09-08 rebind's "suite configuration is
  the authority" conclusion inverted (the asymmetry-free walk matched by accident); every 0.15-class band must be re-
  derived after the fix (the suite anchor also omits --r-series 0.033). (2) The 23-leg re-walk table predates the rev
  4-6 mirror (no re-arm tail: 69 % of dp-replay's -1.8 %). (3) The host stall: ems-mpc-cross latched ERR_HIL_STALE at
  49.26 s on a single 314.5 ms simulator blackout (> HIL_ZERO_MS 250 ms; seq gaps 0, board answering, substep rate
  halved 50 ms earlier under the concurrent analysis agents) - leg VOID; the achieved_rate gate is blind to a single
  blackout (a max_tick_overrun_ms tripwire queued); LIVE analysis concurrency capped at two agents (D-2).
- **Frontiers:** `ftp75c` VERIFIED for the first time ever (eq-H2 1.0105 vs reference, 1.0216 vs bound) - but the
  socband reference now charges 447 mC (17 windows; no longer "charge-free by design" - re-adjudicate). The other five
  tuples UNVERIFIED procedurally (the sdp candidates' scoring-side FAILs; the MPC HOLD gap). 61 s cycle eq-H2: six
  strategies within 0.47 %. No matched-DP record cached (re-solves held).
- **Repeatability / anchors:** scp-inrush cut 6.354319729617211 A bit-identical a FOURTH campaign (its h2 is a +/-8 %
  telemetry-phase quantity - one sample on the collapse ramp - dropped as an anchor); the Run-entry arm cut
  0.05763129341080171 A identical to 16 digits on every leg; comm-loss ramp values bit-identical, OC_FC +16 us;
  soc-depletion latch +4.7 ppm; charge-cruise window-to-latch -0.07 %; clamp cruise 1.2502 A (fifth reading), sweep
  1.3302 A, MDAC pairs byte-identical to H bar one LSB; the JOINT bound's third reading 1.2835 A (G 1.3243, H 1.2699:
  a 4.2 % population, no outlier - 1.3241 A not calibrated; the peak is F6, proven from the codes: the reference
  climbs 2.96 % past the rail 14 ms after the clamp binds); same-policy same-campaign floor 56 ppm h2 / 0 ppm SoC.
- **Replay half:** 27/27 substantive, 138-row census = H, all chain links exact, fidelity bit-exact; the five MDAC-
  saturated entries FELL as the 0.755 A crossover predicts (YP0152 92.5 -> 64.6 %, YP0214 77.4 -> 31.4, YP0196 74.5 ->
  52.6, YP0166 69.9 -> 44.3, ML0203 58.3 -> 35.0); **CORRECTED 2026-09-09 (campaign II replay audit): those "after" figures are FC-only fractions against H's TOTAL tag; like-for-like totals 93.1 / 71.0 / 72.0 / 67.1 / 50.3 % - the crossover is worth 3-10 pp on four entries and nothing on YP0152.** sel_fc = 0 on all 27 and zero re-arms - the replay half gives the
  selector ZERO coverage (every log commands 0.50 inside the arm). Share-cut census 1112 / 49 / 25 (a spread).
- **HELD (operator ruling) until after the H2-model update:** the tooling fix queue (WORK_QUEUE 0f), the matched-DP
  re-solves, the ems-mpc-cross re-run; no campaign II. Firmware items for the operator: the chatter ruling, the FC-
  only re-arm persisting to Run exit, the two-period window open (doc). Bench items unchanged (encoder revs 2-4 are
  HIL-invisible; the DMM measurement of the AD5443/OPA197 block).
  residual past the release, hold vs return-to-battery on re-entry).

---

## Status & session addendum (2026-09-09, H-20 convex hydrogen map - phase A on branch `h20-convex-h2-map`, main fast-forwards to it; PHASE B REQUIRED BEFORE ANY CAMPAIGN)

Branch `h20-convex-h2-map`, orchestrated tooling round (Opus implementer, Sonnet tests, two-lens review,
fix round). **The scored hydrogen model is no longer the linear Gfc DC gain.** `tools/h2_map.py` is the
Horizon H-20 brochure map: rate = A0 (6.633e-5 g/s, purge + blower + controller, constant while the
stack is in service) + 1.358e-4 g/s/A * I(P_stack) through the brochure U-I curve (13 cells); P_MAX
23.416 W stack = 1.247 A bus, controls above it INFEASIBLE in the DP/SDP (census as tripwire). Design
note `docs/modeling/h20_hydrogen_map_20260908.md`; plant doc HIL_PLANT.md §9.3a/9.3b. Operator rulings
2026-09-08: constant-offset loss model; no shutdown state (hook `SHUTDOWN_ENABLED`, default off); Gfc
DOCUMENTED, NOT SCORED (`h2_gfc_cum_g`, `gfc_*`); the electrical `FuelCellSource` refit is a SEPARATE
round (the plant's 12-cell flat curve and the map's brochure curve are two curves for one stack; the
map's I(P) inversion is deliberate until then). Wired into the plant `h2_cum_g` (gated on the
FC_REG_ENABLE mirror; A0 accrues from State 0, so whole-run and Run-window figures differ by A0*t),
DP + table header fingerprint, SDP (stack-side, `--h2-map {h20, eta-proxy}`), walk, MPC
(`h2_map="h20"` default; terminal price re-based at a 3.2 W reference, PROVISIONAL), dp_results_db
key (`h2_map`), report regen pricing. Era switch `gen_dp_ems_table.py --h2-map gfc-linear` regenerates
archived tables byte-for-byte. The three `tools/dp_tables/` tables were REGENERATED under h20
(lambda_term 2.855 / 2.108 / 1.695). Measured this round: A0 is 63 % of the rate at the rig median
3.2 W and ~56 % of an FTP-75 total; the SDP SoC term is ~31 % over-weighted until alpha is re-derived
(v6 config admits 46 charge cells under h20); the H-20 ceiling makes FC-charge + traction infeasible
on 1010 of 2525 SDP cells; a linear-map invariant in the walk (single-source bills more) flips sign
by 1e-5 relative under convexity - restated on bus energy.
**Every h2 band, lambda 0.41, the levers, sdp_policy_v4-v6 and all 75 dp_db records are on the retired
axis. Do not launch a campaign until phase B is done: `docs/HANDOFF_H2_MAP_20260909.md` §3.**
Motivation: the PhD student's full-scale governor penalty (3-16 %) is a convex-map operating-point
effect that is identically zero under a linear map (`docs/modeling/fullscale_governor_penalty_20260908.md`).

## Status & session addendum (2026-09-09, phase B of the H-20 hydrogen map: levers, alpha, the walk's real share controller, the suite on Run-window hydrogen; campaign II = the first H-20 campaign and the first board measurement of the H-20 levers)

Continuation of the 2026-09-08/09 overnight session on the trigger from the H2 session (phase A, `cecfc20`, main
fast-forwarded). Commits `354da3d` (A: levers / alpha / v7 / charge admission - REJECTED in part on review), `65978bf`
(C: the 0f-1 mechanism corrected), `849ff13` (E: the real Youla share controller in the walk), `e42577b` (D: the
campaign-I suite items), `b77d4b9` / `f6c52a6` / `9ff4a9e` (C-prime: the joint-walk re-pins, the MPC HOLD mechanism
refuted, the 23-leg re-walk), `8aeafb4` (A-prime: the lens-1 fixes, bands on Run-window deltas, the saturation
refusal), `d753237` (D-8: the lens-2 items + D-9), `db9b146` (close). A host REBOOT at 03:18 killed one agent pair
(five hours lost; resumed at 08:25). Decisions D-3..D-9 in OVERNIGHT_LOG.md with reversal paths. Campaign II
`hil_report_20260909_095715` from `DC-Balancer-II` at `db9b146` (69/75, 1012 checks, wall 1:42:29).

- **The operating point and the levers.** The rig's Run-window median stack power is **14.644 W** (`p_fc_w` /
  ETA_BOOST on campaign I's ems-sdp; campaign II's charge leg measures 14.635 W, -0.06 %), NOT the 3.2 W design
  estimate and NOT agent A's 13.37 W (a map inversion of a rate column recorded under the retired law - 36 % of
  its ticks sit below A0; rejected). `H2_BASIS_REF_P_STACK_W` / `ALPHA_MISMATCH_REF_P_STACK_W` 14.6440; A0 is
  26 % of the rate there (not 63 %). **THE BOARD'S H-20 LEVERS (campaign II, Run-window): L_share 0.5656 / L_chg
  0.3845 SoC/g**, the corrected walk within +0.3 % / +2.7 %; **ratio 0.680, not the charger round trip 0.801** -
  under a convex map the two levers are no longer related by eta, so every alpha construction that used the eta
  identity is on the retired axis. `EMS_EQ_H2_LAMBDA_SOC_PER_G` shipped PROVISIONAL at 0.4673 (the walked
  cal-charge lever) with the frontier's lambda band [0.39, 0.59]; the board's cal-charge lever gives 0.4799
  (+2.7 %, in band; the share construction 0.706 is out of band). The handoff's "roughly 0.57" was the walked
  cal-greedy pair; agent A's "0.423" rested on the wrong operating point AND on a substituted cal leg (the ems-sdp
  v6 walk in the cal row) - both caught by review. L_share carries +/-2 % from the 1e-5 SoC quantization.
- **Alpha and the SDP.** alpha re-derived at the 14.644 W marginal (`--alpha-mode lever-h20`, D16): 0.134110 ->
  0.142475. **The re-solved `sdp_policy_v7` does NOT certify** (alpha 6.7 % above the walked admission window
  [0.0882, 0.1335]; under a convex map the D12 window is necessary but no longer sufficient; 140 charge cells over
  47 SoC rows, bins 0-2, all below target) and `hil_plant_sim` refuses to bind it - **D-9: the frontier SDP is
  `sdp_policy_v6`** (certified, binds, 0 charge cells; campaign II played it, sidecar sha a7fd8893). v7 registered
  frontier-ineligible as the record; the alpha-basis ruling is WORK_QUEUE 0g-1. On the h20 walks v7 beats v6 by
  9-16 % eq-H2 on ems-sdp, loop-mode insensitive. The h20 alpha sweep `sweep_20260909_h20`, picks greedy 2 / cal
  6 / charge 14. The "1010 SDP cells refuse charge" premise was the SPLIT arm; on the charge arm P_MAX adds zero
  refusals (the refusal is physical: single-source windows).
- **The walk (tools/governor_model.py, tools/ems_walk.py).** The "ems_walk delivers 0 at a 0.15 floor" defect
  was MIS-DIAGNOSED in campaign I: the 0.15 reference is INFEASIBLE under the asymmetric split law (minimum
  deliverable 0.1715 at 1.41 A; the board delivers 0.1727 = the law to 0.6 %), the real Youla share controller
  parks at the floor with a +0.024 standing error and cuts on 0.4 % of ticks, the walk's one-tick surrogate cut on
  100 %. `_youla_step()` now ports share_controller.h (three DF2T biquads, integrator, back-calculation anti-
  windup, the prefilter; coefficients read from the generated header; `closed_loop="controller"` default,
  surrogate kept) - harness-equivalent (27 cases code delta 0 + a closed-loop case tick-for-tick) - BUT the walk
  still cuts ~75x more often than the board on low-rail legs (greedy ~61 Hz vs 0.8 Hz) and the ems-sdp in-band
  gap moved +30 % -> -14.6 %: **every hydrogen band is PROVISIONAL (D-6) and campaign II is the calibration
  source** (board vs corrected walk: ems-sdp -3.2 %, dp-replay -5.1 %, soc-band -4.4 %, cal +1 %). Hypothesis
  for the 75x (WORK_QUEUE 0f-15): the firmware reseeds the controller on the re-close edge. The MPC HOLD fix
  was REFUTED by measurement (re_arm_ok fires 0 of 188; an in-band hold made ftp75c-mpc worse): the release
  preview's own stage-0 total (0.24-0.32 A) exceeds the gate while the plant's is 0.09 A - a TOOLING gap in the
  single-source demand preview (0f-2 re-pointed). The walk's hydrogen is blind to cuts by construction.
- **The suite (tools/run_hil_suite.py).** Every hydrogen band is a RUN-WINDOW DELTA (`delta_min/max` +
  `sample_state_in (2,)`; the plant bills A0 from State 0 so whole-run and Run-window differ by A0 x t_entry);
  the frontier scores `h2_run_g`; `h2_saturated_ticks` + a refusal on hydrogen-scored legs (P_MAX 23.416 W
  stack; charge-cruise's 1.40 A latch sits at 92.8 % of P_MAX because the bus sags - saturation is on stack
  power, not the 1.247 A bus equivalence); `max_tick_overrun_ms` with a 250 ms tripwire (a host stall = SIM
  ARTEFACT by definition); `charge_edges_safe` scores F1's conduction gate (fails campaign H's fw v27 socband,
  passes every fw v28 window); `bt_bus_restored` event-shaped (both b00 shapes pass on the board); the joint
  bound re-keyed to the 1.3345 A structural bound with `joint_peak_held_down` on the settled span only (the
  three readings 1.3243 / 1.2699 / 1.2835 A); sdp-cross windows (5, 33) / (34, 190); the interior check retired;
  per-scenario and replay cut censuses (preceding-row / own-row labelled); `exclude_hold_ms` 330 ms on the MPC
  prediction; the walk pins 1.3185 / 1.3237 A. Suites at close: stdlib 2476 / 96 / 1 xfail; numpy 3245 / 18 / 2
  xfail. Campaign-II findings queued: the dp-replay floor is the retired table's rail (the H-20 table commands
  0.625 in the drain and opens a 2.5 s charge window); plumbing-only hydrogen floors score nothing; the
  saturation peak prints bus watts under a stack label; ems-sdp's stack peak is 93 % of P_MAX.
- **Campaign II (H-20, fw v28 rev 6, v6 frontier):** suite 69/75 (48 scenario legs
  + `drive` SKIP; replays 27/27), wall 1:42:29, **zero board defects**, no host stall under the two-agent cap
  (worst tick gap 20.5 ms). (1) **THE BOARD'S H-20 LEVERS** L_share 0.5656 / L_chg 0.3845 SoC/g, ratio 0.680 (the eta identity
  retired); lambda 0.4799 in band; the charge leg's stack median 14.635 W = the reference. (2) **EVERY PLAN INVERTED POLARITY
  under the convex map** - the MPC on all three cycles (ems-ftp75-mpc 0.85 modal, FC coulombs +86 %; ftp75c-mpc no 0.15 rung;
  ems-mpc / -det / -single floors 0.325 / 0.4125; ems-mpc-cross 0.15 -> 0.85 held 119 s with NO arm standing) AND the
  regenerated DP tables (ems-ftp75-dp floor 0.5375 / modal 0.85 / zero charge stages) - the map's economics, not an MPC
  defect; the delivery-table HOLD gap is now on FC-selected arms (four FAILs, all pre-classified; the fix must be source-
  aware). The FIRST FC-only arms at Run entry (mpc-det / -single), FC-only re-arms on all three 61 s legs at the same instants
  campaign I re-armed battery-only, the FIRST exact-1.0 commits (4 FC-only latch cuts 0.115-0.428 A). The eq-H2 tie BROKEN:
  det 0.014790 < single 0.014807 < mpc 0.014962 (1.16 %; I 0.13 %). (3) **F1 clean a second campaign on every trigger, zero
  UV_BUS**: charge-to-full (window +39.6 ms = two periods, V_bus min 15.7342 V bit-identical), the compressed-cycle releases
  from both arm states (battery-only: re-close 0.95-1.0 ms; FC-selected on ftp75c-sdp / -mpc x2: REGEN drops and FC_CHARGE
  opens on the SAME tick, 0 source-less ticks). (4) **The chatter confirmed**: ems-ftp75-sdp 78 FC_BUS falls IDENTICAL to
  campaign I, same class on every axis - the firmware ruling stands; its DP control case lost its stimulus. (5) Calibration:
  board 1-5 % under the corrected walk on the cruise / FTP-75 legs and 17-21 % under on the 61 s MPC family (admitted by the
  -25 % arm); A0 is 33-88 % of the Run-window hydrogen (66 % ftp75-sdp, 74-88 % ftp75c) - the bands discriminate on the
  remainder; stack medians 14.6 W (cruise charge) / 8-10 W (61 s MPC) / 2-5 W (FTP-75) / 1-2 W (ftp75c): a per-leg H2 basis
  is the design question. (6) Frontiers: ftp75c reads 0.9693 vs BOUND (the in-band DP has no selector - re-solve the matched
  DP under the selector first); cycle61-mpc / ftp75-mpc / ftp75c-mpc UNVERIFIED (the HOLD gap). (7) Anchors: the joint bound's
  FOURTH reading 1.2772 A (population 1.2887 +/- 5.4 %); clamp-sweep the first leg above the H-20 knee (63 saturated ticks,
  unscored); ems-mpc-cross complete for the first time; the Gfc bridge reproduces campaign I to 10-600 ppm on every
  unchanged-plan leg (the plant unchanged); the sdp-v6 legs' SoC-threshold events carry 1-3 s of cross-campaign phase.
  Replay half 27/27 substantive, census identical to H and I - and campaign I's "five MDAC-saturated entries FELL as the crossover predicts" was a METRIC MISMATCH (FC-only fractions against H's total tag; like-for-like 3-10 pp on four entries, nothing on YP0152): corrected here. The selector still has zero replay coverage. Tool pass: 74 runs, 0 errors, no cached matched-DP solve (the H-20 re-solves queued); the report-stage eq-H2 at lambda 0.4673 spreads the 61 s strategies 15 % (mpc-single 0.9466 .. sdp-v6 1.0949 vs soc-band; I within 0.47 %) - the convex map discriminates strategies, and the v6 SDP's FC-only clamp is the expensive one at this lambda. Ledgers local under `HIL Results/`. Budget 2 of 5.
