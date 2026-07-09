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
| 2  | `ENC_A` | IN (INT) | Encoder A |
| 3  | `FC_REG_ENABLE` | OUT | Fuel-cell boost regulator enable |
| 4  | `BT_REG_ENABLE` | OUT | Battery boost regulator enable |
| 5  | `MPPT_DISABLE` | OUT | **Ag105 MPPT disable** (was `CHARGER_ENABLE`) |
| 6  | `CHARGER_STAT` | IN | Ag105 STAT (was `CHARGER_OK`) |
| 7  | `ENC_ENABLE` | OUT | Optical encoder enable |
| 8  | `ENC_B` | IN (INT) | Encoder B |
| 9  | `CBAL_DISABLE` | OUT | **Cell-balancer (BQ29200) disable** — new |
| 11 | `MOSI` | SPI | MDAC |
| 12 | `MISO` | SPI | MDAC |
| 13 | `SCK` | SPI | MDAC |
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
  is **17.5 V**; set `LIMIT_V_BUS_MAX = 18.5f` (1V SW margin; TPS61288 HW OVP triggers at
  19V — confirmed). Battery is **2S**; verify
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
- **Status dump** (`S` command): print all pin states and ADC readings to USB Serial.
- **Exit** (`Q` command): → State 1; `MOT_PWR_ENABLE` forced LOW on exit.

See PLAN.md §9 for the full command set and drive cycle phase table.

---

## 9. Unit tests

A host-native test suite lives in `test/` and can be compiled and run with `make` on any
machine with `g++` — no Teensy or Arduino IDE required.

- **Mock layer:** `mock_arduino.h`, `mock_wire.h`, `mock_spi.h`, `mock_vesc.h` stub out
  all Teensy-specific APIs. Wire mock includes an injectable byte queue for scripted I2C
  responses; SPI mock captures written words for assertion.
- **Coverage targets:** scale factor math, fault detection, PI controller convergence,
  command packet parsing, telemetry packing (58-byte v4 layout + checksum), Ag105 init
  I2C sequence, `pollAg105()` byte decoding, `assertFcChargeEnable()` ordering, drive
  cycle phase transitions, and `MPPT_DISABLE` polarity in `chargingControl()`. The review-round
  additions (PLAN.md §11) added coverage for GENSTAT decode, UV boot-gating, PI anti-windup,
  `doState0()` init-fault handling, `pollAg105()` state gating, and the wheel-speed reset. The
  audit-round additions (PLAN.md §14) cover the live-output PI semantics, power-PI anti-windup,
  gated-tick droop stability, the `ag105DataValid` staleness gate, and the State-98 `'2'` guard
  and `'Q'` path-closing exit.
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

## Status & session addendum (2026-06-23)

**The reconciliation (§§1–10) is implemented.** `teensy_controller.ino` now targets the
20260622 board: rebuilt pin map, RT1987 power-path sequencing, Ag105 charger over I2C +
`MPPT_DISABLE`, BQ29200 `CBAL_DISABLE`, 12-bit ADC + recomputed scales, INA253A1 `K_sns = 0.1`,
v4/58-byte telemetry, State 98 test mode, and the host-native test suite. The changelog block at
the top of the `.ino` records the hardware delta.

A subsequent **correctness/robustness review round** then fixed a set of bugs and latent hazards
found in that firmware. Those changes and the design decisions behind them are catalogued in
**PLAN.md §11**; in brief:

- **Bugs fixed:** `doState0()` no longer swallows a charger-init fault (was demoting State 99 →
  Idle); Ag105 GENSTAT decode corrected (mask `0x07`; errors `0x05`/`0x06`/`0x07`; `0x04`
  Bring-Up is normal); `FAULT_UV_FC`/`FAULT_UV_BATT` gated to Run so unramped rails don't
  boot-lock State 99; `pollAg105()` I2C fault gated to the charging-relevant states.
- **Robustness:** State 3 and State 99 shutdowns are now **non-blocking** phase machines (no
  `delay()`), so `detectFaults()` stays live through the drain windows; State 98's drive cycle
  runs the real `chargingControl/motorControl/powerBalance`, flushes the VESC and parks all
  switches (`safeAllSwitches()`) on stop; the motor PI gained anti-windup
  (`MOTOR_I_CMD_MAX`); wheel-speed buffers reset between runs.
- **Docs:** telemetry corrected to v3/57-byte across PLAN.md; `K_sns` corrected to `0.1` V/A in
  PLAN.md (the A1 part fitted, not the A3).

A later change then **bumped telemetry to v4 / 58 bytes**: the `charger_status` byte (dropped in
v2) was reinstated at its historic offset 51, now carrying the **raw Ag105 Table 6 status byte**
(`ag105_status_raw`). This restores the old off/CC/CV/fault charger telemetry — and supersedes it,
since the Ag105 byte also exposes CC (bit 6), CV (bit 5), MPPT/Power-Tracking/Thermal-Limiting
flags, and the full GENSTAT fault set. `switch_state` and the trailing fields shift +1; the
checksum span is now bytes 1–56. The Pi bridge must be updated in lockstep (it parses fixed
offsets). Layout + bit decode in PLAN.md §6b.

All 177 host-native tests pass (`cd test && make`). Remaining work is bench calibration of the
`TODO(calibrate)` / `TODO(verify)` items (dividers, `motorConstant`, PI gains, `MOTOR_I_CMD_MAX`,
regen threshold, drain delays, AD5443 SPI verification).

---

## Status & session addendum (2026-06-23, bench bring-up)

Bench bring-up of the assembled board drove a set of changes. **These supersede parts of the
earlier addendum** — notably, `doState0()` no longer configures or faults on the charger at all.

- **Charger config is now power-aware and lazy (supersedes "doState0 no longer swallows a
  charger-init fault").** The Ag105 is unpowered until a charger power path is open
  (`chargerHasPower()` = `FC_CHARGE_ENABLE || (REGEN_ENABLE && MOT_PWR_ENABLE)`), so it cannot
  ACK I2C in Init — a State-0 config could never succeed on hardware. `doState0()` no longer
  calls `initAg105Charger()`. Instead `pollAg105()` lazily writes the config the first time the
  charger is powered, past the `AG105_SETTLE_MS` bring-up window, and ACKing; tracked by
  `ag105Configured` (re-arms on power loss; EPROM makes the re-write idempotent).
  `initAg105Charger()` now returns `bool` and raises no fault itself.
- **Charger fault-sensing is power-gated, not just state-gated.** `pollAg105()` faults
  (`FAULT_I2C_CHARGER` / `FAULT_INIT_FAIL`) only when `chargerHasPower() && settled &&
  (State 2|3)`. Unpowered or within the settle window is never a fault; State 98 is excluded.
  The `detectFaults()` GENSTAT check is unchanged (already guarded on `ag105_status_raw != 0`).
- **`chargingControl()` FC-path deadlock fixed.** Cruise opens `FC_CHARGE_ENABLE` on intent
  (`charge_goal > 0`) to power/boot the charger; only the MPPT release is gated on
  `ag105IsReady()`. Without this the FC harvest path could never bootstrap.
- **`BENCH_TEST` flag** (`#ifndef`-overridable): relaxes `detectFaults()` to overvoltage-only
  so the board reaches Idle on the bench with unpowered rails. Defaults to `1` for bench
  flashing; the **test suite compiles `-DBENCH_TEST=0`** (production fault behavior). Charger
  config/faults are no longer tied to `BENCH_TEST` — power-gating handles bench safety.
  Also: `USE_ETHERNET` flag + `networkUp` guard so the UDP functions no-op (don't hard-fault)
  when Ethernet isn't initialized; State-98 `I` I2C-scan command; State-99 1 Hz error print.
- **Test suite path fixed:** the `.ino` now lives in `teensy_controller/`; `test_main.cpp`
  include and the Makefile `-I` were updated. **All 205 host-native tests pass** (run with
  MSYS2 UCRT64 g++: `cd test && mingw32-make`, or g++ directly — there is no `make` on this
  machine). New `AG105_SETTLE_MS` is a `TODO(calibrate)`.

---

## Status & session addendum (2026-06-24, VBUS controlled bring-up)

A bench-test mishap drove a safety fix. In State 98 the operator enabled `BT_BUS_ENABLE` while
both boosts were already running (~17.5 V) and VBUS sat at 0 V; the BT TPS61288 boost was
destroyed (VIN/SW/VOUT all shorted to GND) and the Teensy browned out off USB.

- **Root cause (reconciled against the new `references/Datasheets/RT1987_DS-00.pdf` + schematic
  sheet 4).** The RT1987 has **back-to-back integrated FETs** (full VIN/VOUT isolation when
  disabled — *no* body-diode passthrough) and **soft-start + start-up SCP that re-run on every EN
  edge** (board `CSS = 5.6 nF` → tON ≈ 1.17 ms; POVP→GND → OVP ≈ 33 V). VBUS carries a **470 µF**
  bulk cap, which a 1.17 ms ramp cannot charge within ISCP, so a hot-plug makes the RT1987
  SCP-clamp and burst-retry. The real kill was the **shared 9 V test rail**: `VBT` feeds the BT
  boost *and* the LM1084 logic reg, so the burst browned out the MCU and stressed the boost.
  FC-first worked because FC's source is isolated and pre-charged the bus → BT then saw a ~0 V
  step. Takeaway: **never hot-plug a running boost onto a discharged 470 µF bus.**
- **Boosts default OFF in `setup()`.** They are enabled by `doState0()` *after* the bus switches.
- **`doState0()` is now a non-blocking phase machine** that brings the bus up gently: bus switches
  first (RT1987 soft-starts the bus to ~Vbatt), settle `BUS_SETTLE_MS`, then boosts (their own
  soft-start ramps the bus to 17.5 V). State 0→1 is **gated on `V_bus ≥ V_BUS_CHARGED_THRESH`**,
  with `BUS_CHARGE_TIMEOUT_MS` → `FAULT_INIT_FAIL` (dead boost / failed switch / no source).
- **`doState3()` (Finish) no longer drains the bus.** It stops the motor and closes the
  motor/regen/charge paths but **leaves the boosts + `FC_BUS`/`BT_BUS` ON**, so the bus stays
  armed and Idle→Run never re-hot-plugs. Only **State 99** tears the bus down (latched → power
  cycle → State-0 gentle bring-up). This drops the old two-phase cap/regen drain (the disabled-
  boost back-feed hazard does not apply while the boosts stay enabled).
- **State 98 guard + `G` command.** `1`/`2` refuse to turn a `*_BUS_ENABLE` ON when the matching
  boost is ON and `V_bus` is low (`busHotPlugUnsafe()`); new `G` runs `bringUpBus()` (switches →
  settle → boosts) for a safe manual bring-up.
- No telemetry layout change (reuses `FAULT_INIT_FAIL`/`ERR_INIT_FAIL`). New
  `V_BUS_CHARGED_THRESH`, `BUS_SETTLE_MS`, `BUS_CHARGE_TIMEOUT_MS` are `TODO(calibrate)`.
  The BT TPS61288 has been replaced and the board is functioning again.

### Corrected failure analysis + BENCH_TEST bypass (supersedes the inrush framing above)

Bench bring-up from a **current-limited supply** (no fuel cell, `VBT` from a DC supply) repeated the
`VBT→GND` short. Diagnosis was refined, and two earlier theories were wrong — recorded so the
code/docs stop repeating them:
- **Inrush is NOT the cause.** The 470 µF bulk cap is on the **V-MOT / regen node behind
  `MOT_PWR_ENABLE`**, not on VBUS. With `MOT_PWR_ENABLE` off, VBUS carries only ~30–40 µF (the
  RT1987 ceramics), so bus inrush is negligible — and `MOT_PWR_ENABLE` was off in the original
  State-98 failure too.
- **The recurring killer is the BT boost on a collapsing input.** The Teensy is **board-powered**
  (LM1084 off `VBT`). On a supply that can't carry the logic baseline (Teensy + Ethernet PHY ≈
  150–250 mA through the linear reg), `VBT` sags → Teensy browns out → resets → `doState0()`
  re-enables the boost → **motorboating**. Switching with built-up inductor current on a
  sagging/recovering rail then destroys the power stage. **Exact mechanism is UNCONFIRMED** (pending
  a SW/VOUT scope capture): most likely a **VOUT overshoot past the 20 V SW/VOUT abs-max** — the
  TPS61288 OVP is at 19 V (≤19.5 V), leaving only ~0.5 V margin, and the 3×22 µF output caps
  DC-derate to ~30 µF, so an inductor-commutation spike (½·L·I² at the 15 A limit into ~30 µF) rings
  over 20 V — and/or **transient reverse conduction**. Either way the destructive energy comes from
  the boost's own inductor / output cap, so a **supply current limit does not bound it**. (An
  earlier note here asserted reverse conduction specifically; the datasheet's PFM negative-current
  blocking weakens that, so overshoot is now the leading candidate — to be settled by scope.) Same
  class of event as the first incident (weak 9 V battery sagging under load); replacing the TPS61288
  fixed that one, confirming the boost (not the `VBT` tantalum) is the failure point.
- **`BENCH_TEST` bypass.** `doState0()` now wraps the bring-up in `#if BENCH_TEST`: under
  `BENCH_TEST` (the default bench flash) it boots **straight to Idle with the power stage dark**
  (boosts, bus switches, and `BT_SEQUENCE` all stay LOW; no `V_bus` gate) — so a soft bench supply
  can't trigger the motorboating loop. Bring the bus up manually with the State-98 `G` command on a
  **stiff** supply. Production (`BENCH_TEST=0`) keeps the full bring-up + gate. Source-agnostic init
  is shared via `initControlPeripherals()`.
- **Bench rule:** the supply must comfortably exceed the logic baseline (≥ ~0.5–1 A) or the
  board-powered Teensy browns out; bring the bus up only on a stiff supply (the killer is the boost
  on a collapsing input, independent of any current limit).
- **Tests:** the suite gains a second `-DBENCH_TEST=1` build (`run_tests_bench`) covering the
  bypass (`test_dostate0_bench_bypass`); the `-DBENCH_TEST=0` build keeps the production `doState0`
  tests. `cd test && mingw32-make` builds and runs both.

### ✅ RESOLVED (2026-07-07) — battery boost VBUS-connect deaths: hot-loop layout, fixed with caps

Four battery-side TPS61288 boosts were destroyed on `BT_BUS_ENABLE` bus-connect. **Root cause: the
BT channel's output caps sit 240 mil from the IC output (FC: 40 mil) → ~2.7× output-cap hot-loop
inductance → SW/VOUT overshoot past the 20 V abs-max when driving the bus.** Fix: **10 µF + 0.1 µF
ceramics bodged directly at the BT boost output** — validated by four consecutive surviving `G`
bring-ups under Death-4 conditions (single-variable test; scope captures in
`references/scope_captures/`). **Any future BT boost install must keep these caps** (or a respun
layout with Cout at the IC). **Update 2026-07-08 — Death 5 (FC boost):** the overshoot mechanism is
current-scaled and system-wide. Closing `MOT_PWR_ENABLE` at full bus onto an attached VESC (RT1987
soft-start can't charge 470 µF + VESC caps → SCP burst-retry → 15 A load-dumps) killed the FC boost
from a stiff supply; 9 V batteries sag/UVLO before lethal current, which is why battery runs
survive. Plan: 16 V nominal bus, motor-node pre-charge sequencing (firmware), FC output bodge caps,
high-BW SW-ring margin check (now blocking). Full history, datapoints, and remaining steps in
**`docs/boost-bringup-debug.md`**.

---

## Status & session addendum (2026-07-01, full-codebase audit round)

A full audit against the authoritative sources verified the pin map (matches the IO CSV
row-for-row), all Ag105 register values/scales/GENSTAT codes (match Tables 3/4/6/7), the
telemetry v4 arithmetic, and the sequencing guards. It also found and fixed the following —
full detail in **PLAN.md §14**:

- **VESC UART fix (safety-critical, needs bench verification).** `setup()` called
  `pinMode(RX/TX, …)` *after* `Serial1.begin()`; on Teensy 4.x that reassigns pins 0/1 from
  LPUART6 to GPIO, silently killing all VESC communication (including the `setCurrent(0)`
  safety flushes). The two lines are deleted — never call `pinMode()` on pins 0/1. Not
  host-testable (mock `pinMode` is a no-op).
- **PI live-output semantics (user-approved change to "What NOT to change" code).** Both PIs
  returned a 0.0f sentinel on sub-`sampleTime` ticks, which chopped the motor command and
  slammed the droop split to the 0.01 extreme. The integrator update stays `sampleTime`-gated;
  the output is now always computed. The power-share PI also gained anti-windup (`Ki·accum`
  clamped to ±1.0, the droop ratio's full authority). Note: during FC-charge cruise the EMS on
  the Pi commands `power_share_setpoint ≈ 1.0` (BT is off the bus), so the share error is ~0
  by design — the clamp is a defensive backstop.
- **`ag105DataValid`.** GENSTAT 0x00 = Battery Disconnect is a real Table 6 status, so raw==0
  no longer doubles as the stale marker; validity is tracked out-of-band and gates both
  `ag105IsReady()` and the `detectFaults()` GENSTAT fault.
- **State 98:** `'2'` refuses BT_BUS while FC_CHARGE is HIGH (the CSV's illegal combination);
  `'Q'` now closes FC_CHARGE/REGEN on exit so a charge path can't stay latched into Idle.
- **`LIMIT_V_BATT_MAX` left at 10.0f per user decision** (9V-battery bench testing) but it is
  UNREACHABLE — the BT divider saturates the ADC at 8.646V, so OV_BATT cannot trip (and under
  BENCH_TEST the OV checks are the only armed faults). Change to **8.5f** when 9V testing ends;
  a `TODO` comment marks it.
- **`USE_ETHERNET`** is `#ifndef`-overridable and a `#warning` fires on
  `BENCH_TEST=0 && USE_ETHERNET=0` (production faults, no Pi link, inert watchdog); the test
  Makefile suppresses it with `-DNO_ETH_WARNING`.
- Stale comments corrected (SCALE_I mA/count figure, `doState99()`/`doState3()` shutdown
  rationale vs the corrected failure analysis, `updateWheelSpeed()` unit-chain TODO).

**All 283 host-native tests pass** (278 production + 5 bench build). Build caution: running
`mingw32-make` from PowerShell can silently reuse stale binaries (the recipe's `PATH=` prefix
doesn't resolve there) — build from an MSYS2 shell, or invoke g++ directly and check the
executable timestamps.
