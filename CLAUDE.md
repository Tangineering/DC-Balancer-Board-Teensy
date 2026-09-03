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
`docs/claude-md-archive.md` to keep this file under the memory-size limit. Seven ranges are
archived. The seventh (rotated 2026-09-03) holds the 2026-09-02 overnight addendum (Ag105 eta 0.88 in
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

## Status & session addendum (2026-09-02b, fw v26: FC/BT current-ceiling share clamp — flashed 2026-09-02 evening; calibrated on the board in campaign E, see the 2026-09-03 addendum)

Operator directive (2026-09-02): keep `OC_FC` unchanged, but extend the share governor so that
when the fuel-cell current approaches its limit the delivered FC share is clamped and the
battery supplies the excess; a battery-side ceiling of the same form was ruled in (much
higher, not expected to bind). Shipped as **fw v26** (Opus implementer, Opus safety review,
fix round, orchestrator rebuild 3926 / 175 / 4408 checks, 0 warnings on the production and
HIL builds). `docs/fw26_current_ceiling_governor.md` is the design record; ledger row 26.

- `applyShareCurrentCeilings(sp)`: `sp <= SHARE_GOV_I_FC_CEIL_A / share_govTotAFilt` (**1.25 A**,
  0.15 A under `LIMIT_I_FC_MAX`, which has NO persistence filter — a single raw sample latches)
  and `sp >= 1 - SHARE_GOV_I_BT_CEIL_A / share_govTotAFilt` (**2.70 A**), hysteresis
  `SHARE_GOV_CEIL_HYST_A` 0.05 A on engagement only, against the governor's ~20 ms EMA. Minority
  clip runs FIRST; result constrained into `[DROOP_R_MIN, DROOP_R_MAX]` (can never command a
  cut); applied downstream of the `share_actedSp` bookkeeping (cannot toggle HOLD/FEEDFORWARD);
  HOLD: no clamp, FEEDFORWARD: clamped; suppressed while a deferred cut owns the setpoint;
  bit-identical to fw v25 below the ceilings (fixture MDAC-code comparison). Flags cleared on
  every frozen-loop return, `resetShareControlState()`, `doState3()` and the State-98 `'Q'`
  exit; State 99 freezes them like `fault_flags`. `SHARE_MINORITY_I_MIN_A` is now `constexpr`
  and the ceilings are `static_assert`ed against it.
- ⚠️ **REACHABILITY (the governing number):** the minority clip bounds the commandable FC
  current to `min(0.85·I_tot, I_tot − 0.30)`, so the clamp can act only above **1.55 A of
  TWO-SOURCE total** (first engagement measured 1.60 A). In an FC-charge window
  `assertFcChargeEnable()` holds `BT_BUS` LOW, `I_tot == I_fc`, `r` is pinned at `DROOP_R_MIN`,
  and the clamp is structurally inert — every `OC_FC` latch on record (`charge-cruise` 1.40 A
  single-source) is in that regime. **fw v26 is inert on the entire registered stimulus set**;
  the largest two-source totals in campaigns B and C were ~1.4 A and the largest legitimate FC
  peak is 1.1920 A (`ems-sdp-cross`, campaign B; headroom 0.058 A). Bench validation is the
  State-98 `W 4.0 0.15` profile (design note §8.2.1); a two-source high-total HIL scenario is
  queued for the tools round. A charge-window guard (reduce Ag105 charge current / close the
  path when single-sourced `I_fc` nears the limit) is the mechanism that would address the
  recorded latches — separate design, not in v26.
- Infeasible pair above 3.95 A total (INSIDE the 4.2–5.4 A platform budget): FC bound wins;
  above 4.25 A the governor commands `I_batt > LIMIT_I_BT_MAX` and `ERR_OC_BT` is the intended
  latch. Sustained regime found (4.0 A, sp 0.60): `droopSlew_prev` pins at `DROOP_R_MIN` and the
  load guard refuses the FC cut on every tick — no cut, both switches HIGH, tested.
- Observability, no wire change: HIL observation-frame aux byte **bits 4/5** (FC/BT clamp),
  BLG `flags` **bit7** (either clamp), State-98 `'S'` line (`share I-ceiling:` with both
  commanded channel currents). `switch_state` deliberately untouched (the HIL plant solves the
  network from it); Pi exposure is a protocol-bump follow-up. Neither bit has a suite mask or a
  benchlog decoder helper yet (manual observables this round).
- Tools follow-ups (queued, WORK_QUEUE §7): `governor_model.py` port of the clamp in the
  firmware's order + equivalence test; `ems_walk.py` walks the CLAMPED share; the DP/SDP
  `charge_mask()` delivered-share semantics; the MPC surrogate/rolls; suite `aux_bit` masks
  for bits 4/5; `_ALPHA_FC_CEIL` 1.28 A now exceeds what the board can command;
  `FAULT_EXPECTATIONS["charge-cruise"]` (requires `OC_FC`) needs operator re-adjudication.

---

## Status & session addendum (2026-09-02c, DP-bound round: per-node bleed, loss map, droop-mode bus law, ftp75c compressed cycle + regen term, grid/ladder widening, mpc-sto default)

Daytime round after the overnight session (operator present; rulings in
`WORK_QUEUE.md` §7 and the memory file). Commits `51e20b8` (EMS-comparison stage + N4 rejected),
`82edd3c` (stage 1), `ca2d084` (stage 2 + widening). fw v26 (`45d9c95`) is a separate addendum.

- **N4 rejected by probe:** the hi-fi `I_fc` is the FC_BUS branch current WITH the INA shunt in
  series (INA sits between the TPS61288 output and the RT1987 input); the "half step" was the
  two-source share split; reported step 99.3 % of the boost-output step at the first 1 kHz
  sample. `tools/probes/probe_n4_ina_proxy.py`, four pinning tests.
- **EMS-comparison stage** (`tools/hil_ems_comparison.py`, `EMS_COMPARISON.md` per campaign,
  hand-written Commentary carried across re-renders; skill Stage 0/4). Campaign C FTP-75: four
  charge-free strategies within 0.15 % eq-H2 (unresolved under the λ band), soc-band 3.4 % worse.
- **The dp-replay gap decomposed** (`docs/modeling/dp_loss_map_20260902.md`): +4.35 % (FTP-75) /
  −0.20 % (61 s) = node bleeds at 2 kΩ (+4.90 / +2.58 % of h2) + aux billed at the `--droop
  measured` bus law 0.074 Ω while campaigns run `design` 0.308 Ω (−0.67 / −2.73 %); the 61 s
  figure was a cancellation. Gfc dynamics contribute −0.01 %.
- **Physics change (operator ruling): `R_NODE_BLEED` 2 kΩ → `R_NODE_BLEED_BUS` 30 kΩ /
  `R_NODE_BLEED_OTHER` 60 kΩ** (`TODO(calibrate)`, bench decay capture); simple engine
  `R_BUS_BLEED` 30 kΩ (τ 0.94 → 14.1 s). Every h2 anchor moves (61 s −1.7 %, FTP-75 −2.9 %,
  soc-depletion latch ≈ +1.5 s; scp-inrush/handoff-sag bit-exactness lost) — **BLEED-ERA block in
  run_hil_suite.py; re-pin on the next campaign.** Reversal path in HIL_PLANT.md.
- **Structural loss map** in `build_demand()` / `ems_walk` / `mpc_ems` (lockstep 0.0 over 90
  previews): per-live-node bleed, MOT_PWR drop, bus law V0_EFF 15.871722 V, R_FIX 0.017986 Ω,
  K_G 1.95079 at the firmware-held `g_par` 0.148922 (= K_DROOP/RE_MAX, share cancels: separable).
  Optional fingerprint key `loss_map` (omitted when None; 37/37 records reachable); era guards in
  `DpReplayStrategy.bind_scenario()` (review H1) and `MpcStrategy.bind_scenario()` (run config
  wins). dp-replay deviation ems-ftp75-dp **+0.029 %**, ems-dp-replay **−0.303 %**, bleed-invariant.
  `droop_mode` is a run-era field. `ElectricalSim(substep_pin=)` for deterministic tests.
- **mpc-sto is the frontier MPC** (operator ruling; ems-mpc/-cross/-ftp75-mpc); `ems-mpc-det` is the
  ablation. ⚠️ mpc-sto fails the offline Gate 1 at the measured plant dv0 (mean 0.009 vs 5e-3; a
  forecast error on one open_hold stage) — stated on both MPC frontier notes. The ems-mpc-cross
  share-motion floor 0.12 → 0.05: the 0.12 was unsatisfiable at the previous commit under BOTH
  laws (walk 0.0833) and unchanged by the widening (one ladder step from the low rail).
- **ftp75c** (design `docs/modeling/ftp75c_regen_cycle_design_20260902.md`): FTP-75 at time factor
  0.5 (234 points, 170 s, peak accel ±0.349 m/s²) on the **`scaled-air` drag profile** (k_air
  0.0598069 N/(m/s)², F_c 0, M_EFF 3.5 kg; 51 % regen share — the operator chose it over
  `scaled-air-matched` 79 %; the published scaling did NOT time-scale, this is a separate cycle).
  `tools/regen_power.py` is the one regen chain; `RegenManager` opens REGEN+MOT_PWR on braking for
  every strategy, windows trimmed at **2× the firmware's regenActive threshold** (review H1: a
  force<0 trim commanded charge_goal while the firmware read cruise → the OC_FC path; 6 windows /
  19.6 s). Signed regen term in the DP (share-independent credit, charge/regen exclusivity,
  era-gated grid guard, `drag`/`eta_regen` optional keys). soc-band overrides 0.18074 / 0.33107 A
  (review H2). Regen to pack ≈ 1.17 C / cycle (SoC +6.5e-5): a model validation, NOT an EMS
  discriminator. Bench replication of option 1 needs an external road-load motor on the flywheel
  (single-motor feedforward cannot produce physical regen).
- **Share-range ruling:** every EMS strategy gets the full firmware band [0.15, 0.85]; soc-band
  stays 0.50 ± 0.25 by design; 0/1 single-source in the MPC ONLY (foundation shipped: measured
  single-source bus laws 1.9453×/2.0579×; enumeration held on the cut-guard path-dependence
  question — three resolutions in the MPC design record). DP grid [0.15, 0.85] n_share 57 (edges
  = the SDP clamp's float32): ems-sdp matched-DP −0.35 % → **+0.052 %**; ems-ftp75c-sdp −0.72 %
  residual. MPC ladder 9 points over the band, 0 % expiry, cap 2187. Frontier (walk): cycle61
  0.957 / 1.002, ftp75 0.959–0.966 / 0.992–0.998, ftp75c 1.009–1.017 (candidate WORSE than the
  reference; a PASS asserts "no more than 2 % worse") / 1.009–1.016.
- **Standing corrections:** the same-config h2 repeatability floor is ~50 ppm; the FC_BUS/BT_BUS
  diode drops are billed to neither source (stack current referred at V_bus) — model artefact,
  recorded; `MATCHED_DP_LONG_DURATION_S` 100 s means every FTP-75/ftp75c matched solve needs
  `--matched-dp-allow-long` or a prefill.
- **Suites at close:** miniforge 2734 passed (one known wall-clock flake, WORK_QUEUE hygiene item),
  `.venv_hil` 2047 passed. Firmware: fw v26 3926 / 175 / 4408.

---

## Status & session addendum (2026-09-03, overnight round: fw v26 on the board, campaigns D and E, bleed-era baseline, loss-map bound validated, MPC 0/1 enumeration, the clamp's step-transient limit)

Overnight autonomous session from `201de7b` (operator brief 2026-09-02 evening: "fw v26 is flashed, begin
the overnight campaign(s)"; decisions D-1 to D-4 and their reversal paths in OVERNIGHT_LOG.md
§2026-09-02/03). **FW stays v26 (flashed by the operator); the wire protocol is frozen.** Commits `c8b50ff`
(fw v26 tools mirror + review fixes), `d941170` (post-campaign-D fix round), `5e2e3fd` (conventions
leftovers), `7de3f11` / `4887bd3` (MPC single-source round, merged from an isolated worktree), and the
campaign-E fix round (last commit of the session; hash in the log).

- **Campaign D (`hil_report_20260902_220604`, tooling 201de7b run from a DETACHED WORKTREE so the concurrent
  tools-mirror round could not leak into the children; 71 planned, 70 executed + `drive` SKIP; suite tally
  63/71; wall 1:38:10). Corrected: 70 of 70 correct, zero board defects.** The eight FAILs were four tooling
  artefacts, all classified during the run: (1) `regen-harvest-true` — the `sw_ring` estimator adds a FIXED
  1.95 V Death-5 load-dump term to the node at every cut > 50 mA; with the 60 kΩ bleed the charger node
  sits ON the chopper clamp (18.064 V) when the 65 mA commanded REGEN open lands, and 18.064 + 1.95 =
  20.014 V > the 20 V abs-max — structurally, the estimator's ceiling (18.050 V) is 50 mV below the clamp
  state the scenario REQUIRES; physical ring 0.8 mV. (2) Five `ems-ftp75c-*` legs — the chopper-energy
  aggregator was written into `signals_require` (an `events_require` spec): unnameable ("signal_the") and
  unmeasurable; physics clears the 2.5 J floor 2.2× (5.46–5.49 J). (3) `ems-ftp75c-mpc` / `ems-mpc-cross`
  — the MPC share floor/ceiling constants were left at the pre-widening band (0.15 and 0.2375 are ladder
  rungs 1 and 2). (4) `mppt-tracking` — the fiat mirror freezes across unpowered spans and carried the
  braking-window count 27 into the cruise window's first 849 ticks (the bleed keeps the node clamped to
  the end of the window; C only passed because the 2 kΩ bleed released it early); the harvest operating
  point is unchanged at [15, 19] and the value cannot occur on hardware (the real manager excludes regen).
  A fifth item was a scenario-design gap: the RegenManager's wall-clock trailing edge opened a single-source
  FC_CHARGE handoff (0.37–0.38 A at 171.3 s) when the vehicle stopped before the window ended.
- **Bleed-era predictions confirmed on the board:** loaded 61 s legs h2 −1.2 to −2.0 % (walk −1.7 %),
  `ems-ftp75-5050` −2.88 % (walk −2.9 %), low-current runs −8 % (the removed static bleed is a larger
  fraction of their draw). Every lightly loaded node now parks on its clamp or rail: the regen node at
  18.10 V between windows (out-of-window chopper 1.6 J vs modelled 0.5), the chopper never releases
  mid-window (clamp events 6 → 3, dwell 1962/2100), the 470 µF V-MOT node retains 92 % over a teardown
  (comm-loss warm re-close **0.1088 / 0.0816 A**, −72 %; τ 0.94 → 28.2 s; the cold bring-up peak moved
  −1.5 %), the soc-depletion latch moved **+2.62 s** (predicted +1.5). Anchors re-pinned (scp-inrush
  6.360327 A, handoff-sag 0.370456 A, soc-depletion 273.5935 s, ems-sdp 0.0123898 ± 50 ppm, the FTP-75
  h2 bands, sdp-cross period 16.10–17.12 s with an era-invariant 8.06 s hold, the ems-y quartet). The
  bit-exact asymmetry-era records are retired by the plant boundary as predicted.
- **The loss-map DP bound is validated on the board:** dp-replay legs −0.18 % (61 s) and +0.06 % (FTP-75)
  against walk −0.30 / +0.03 (the sign is the dynamic-Gfc-vs-DC-gain bias; |dev| ≤ ~0.8 % is not a policy
  result); sdp-v4 −0.09 / +0.44 after the widening (was +0.35 % rail deficit); soc-band +3.79 / +3.37;
  MPC legs +0.01 / +0.03 / +0.39. ⚠️ The three α legs first resolved to a WRONG bound (+258 %): the
  `SOC_BAND_DRAIN_SCENARIOS` mirror was hand-typed and omitted them — the 2026-09-01 B2 defect again at
  the identical 0.0034 g. Now derived from `hil_plant_sim.SOC_BAND_DRAIN_SCENARIO_NAMES` in all three
  offline mirrors; records re-solved (alpha-cal bit-identical to ems-sdp's bound); a drain-membership
  witness is stored on new records and compared at read time (the fingerprint does not cover
  membership, so a stale mirror yields a wrong record under a correct key; hashing it would orphan all
  71 records — rejected).
- **First ftp75c physics:** 6 regen windows / 19.2 s (design 6 / 19.6), REGEN never high with FC_CHARGE,
  8 s dwell respected, chopper 5.24–5.49 J per leg, **0.73 C per cycle to the pack = 63 % of the walk's
  1.17 C** (window-length distribution against the ~0.9 s Ag105 dead time, not η_regen), SoC credit
  unresolvable ("model validation, not an EMS discriminator" confirmed). h2 tracks the walk within 2 % on
  the three charge-free legs; the MPC leg is a constant-0.15 hold (h2 −31 % vs walk, drain +14 %).
  **Ruling D-4:** the manager releases `charge_goal` on the observed motor current — arm −0.2 A, release
  −0.1 A (the firmware's own regenActive exit; the first single-level version chattered on measured
  braking grazes and was caught by review) — so the FC_CHARGE handoff windows collapsed on the board
  from 80–280 ms to one 50 Hz commander period (18–20 ms, 0.38–0.47 mC; suppressed entirely on the sdp
  leg); they can still occur at both edges inside one commander period and the new 0.60 A charging arm
  bounds them. The walk keeps the wall-clock end (its feedback view lacks the current), so walk regen
  duty is an upper bound on the live one.
- **fw v26 on the board.** Reachability corrected before the campaign: the clamp binds on
  `ems-y-b30-v3` (12 ticks D / 13 ticks E at t ≈ 27.01 s; the clamp explains 0.05 % of that leg's h2
  delta; the first live engagement fired on a STALE filtered total after a load collapse) and nowhere
  else on the registered set; the replay half gives ZERO coverage (max commanded FC demand 1.165 A;
  open-loop injection cannot drive a reference-side clamp). **Campaign E (`hil_report_20260903_031220`,
  tooling d941170, 73 planned, 72 executed; suite 72/73; wall 1:40:26): 72 of 72 correct, zero board
  defects; all eight D FAILs closed by their fixes acting (not by widening).** `fw26-clamp-cruise` 13/13
  on its first execution — **the clamp's calibration: engagement +3.32 ms after the command (Pi cadence +
  round-trip), duty 1.0000, I_fc 1.2499–1.2502 A at the 1.25 A ceiling (0.016 % overshoot), I_batt
  0.7507, closure ≤ 0.8 mA, hysteresis engagement-only, 0 switch events; it fired on the DEMAND
  (0.75 × 2.00 A) while the delivered current was 1.0005 A — reference-side, proven.**
  `fw26-clamp-sweep` FAILED and it is REAL: at t = 38.000 s the table stepped the velocity setpoint AND
  the share (0.40 → 0.84) upward in one packet; the drive railed to 12 A (I_tot 1.84 → 2.99 A), the clamp
  engaged on the first tick it saw the setpoint, the slew limiter bounded the reference for 9 of 12
  ticks, the 20 ms EMA under-read the rising total by **25.6 % against the 12 % design headroom**
  (decomposition +0.4298 A filter / −0.1910 A plant lag = +0.2388 A; closure 0.2 mA), and OC_FC latched
  at 38.029 s (I_fc 1.489 A). Neither axis alone latches (load step at the converged ratio 1.196 A; share
  step at the settled total 1.2500 A). **The race:** the slew-limited reference crosses the safe delivered
  share in (1.40/I_new − s_prev)/0.02 ticks (4.3) while the EMA needs ln(1 − (I_new − 1.25·I_new/1.40)/
  (I_new − I_old))/ln(0.95) ticks to make the clamp bind (25) — a factor 5.8; **necessary condition
  I_tot > LIMIT_I_FC_MAX / DROOP_R_MAX = 1.647 A; no registered EMS stimulus exceeds 1.4714 A.**
  Firmware closure (α ≥ ~0.25 or slew ≤ 0.0027/tick) was NOT proposed under the design-intent ruling; the
  sweep is bridged (velocity first, share 1.5 s later — the drive rail lasts up to 1.08 s at region 11;
  walked peaks 1.311 A bridged vs 1.722 A unbridged) and the EMS rule "no upward share step in the same
  decision as an upward demand step above 1.65 A two-source" is queued for the MPC stage model (a
  0.0875 rung at 2.0 A is 0.175 A of demand against 0.15 A of headroom). After a State-99 latch every
  aux-bit and MDAC-mirror check reads the frozen value (13 consequential FAILs, ten non-evidence
  PASSes, 499 inherited FC-ceiling ticks on the successor) — aux checks are windowed post-grace.
- **Frontiers:** cycle61 0.9638 / 1.0018 (D) → 0.9635 / 1.0018 (E); **ftp75 0.9656 / 0.9992 → 0.9657 /
  0.9994 (first CERTIFIED ftp75 reading in D)**; cycle61-mpc 0.9638 / 1.0017; ftp75-mpc 0.9653 / 0.9988;
  **ftp75c 1.0091 / 1.0076 and ftp75c-mpc 0.9931 / 0.9916 (first certified in E; D's hand figures
  1.0088 / 1.0107 and 0.9903 / 0.9920)**. sdp-v4 and mpc-sto TIED on both cycles (98 / 341 ppm); the
  four charge-free FTP-75 strategies within 0.15 %; soc-band 3.3–3.8 % worse. Levers third and fourth
  readings L_chg 0.332947 / 0.333298, L_share 0.416279 / 0.416317 SoC/g; v4's α 1.49 / 1.48 % below
  the measured window; eq-H2 ordering greedy +1.11 % / charge +4.08–4.10 % — v4 the eq-H2 winner a
  fourth time. **Same-config floor: ~65 ppm within a campaign, ~250 ppm typical / 800 ppm worst across
  campaigns** (E vs D: scp-inrush bit-exact to 7 digits, five anchors bit-exact, 30 of 43 within
  ±250 ppm). Campaign C's MPC expiry finding is CLOSED (ems-mpc-cross median 10.0 → 5.2 ms, 57.4 → 0 %);
  `CANDIDATE_COST_MS_NOMINAL` 0.0300 → 0.0392 → 0.0360 (two-campaign mean; the ladder still coarsens
  on 100 % of decisions, points searched 4–8 of 9).
- **MPC single-source (0/1) enumeration shipped (ruling: rollout-time cut-guard test).** The board
  executes exact 0/1 through the existing packet (`.ino:5663` constrains to [0, 1], not the band; the
  ems-y-b00 profiles already use it — no protocol change). Two candidate columns at block 0, admissibility
  by a bounded roll of the real governor model from the committed shadow state (seven refusal reasons;
  regen guard on the host key OR the observed REGEN bit; FC-charge, deferred cut, latch), billed on the
  measured single-source bus law with a survivor-referred OC bound; `ems-mpc-single` in the default plan
  (15 ms budget, h2 informational for its first campaign). **Findings:** the load guard never refuses
  permanently above 0.6 A total — the deferral clips the reference into band and walks the doomed channel
  down until the guard admits (a delay, not a verdict; grid worst 118 ticks at 0.75 A / r0 0.85, 1.69×
  under the 200-tick window; 2 of 400 grid points refuse at 0.60 A), contrary to the design record's
  resolution 1; FC-only is admissible and never selected; **the gain is 0.01–0.43 % of equivalent
  hydrogen** while raw hydrogen moves up to 49 % — a control-set completeness change. Plan invariance
  with the feature off verified against d941170 itself (3050 commands identical, sha-pinned). Gate 1 is
  not yet single-source-aware (queued).
- **Tooling data-integrity items found:** `regen_early_releases` was frozen at 0 in every sidecar ever
  written (evaluated before the run loop; fixed in `finalize_meta()`); the sdp-sweep drain mirror
  (above); `share_cut_census` is a SPREAD across campaigns (118 → 157 → 132 under a byte-identical
  scorer; open-loop share-PI branch selection), not a pin; a stray uncommitted duplicate `--eta-chg`
  argparse registration in `tools/dp_results_db.py` killed its CLI and was restored; `steady`'s h2 is
  not comparable between a post-flash campaign and a chained one (499 ticks in State 99).
- **Tests at close:** `.venv_hil` **2178 passed / 80 skipped**; miniforge **2877 passed / 1 skipped**
  (one known wall-clock flake under load). Firmware suites untouched — fw v26's 3926 / 175 / 4408 stand.
- **Campaign budget: 2 of 5 used at the time of writing** (F, if launched, is the third: the bridged
  sweep, the cruise step pins and the first live `ems-mpc-single`). The physics review of
  `docs/HIL_PLANT.md` (run 002: bleed, loss map, regen model, the estimator's physical option) was
  deliberately not run overnight (host load during campaigns) and is queued.
