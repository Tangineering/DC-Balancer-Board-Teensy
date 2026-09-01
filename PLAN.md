# Firmware Reconciliation Plan — Board Rev 20260622

> Dated pointer (2026-09-01): status, firmware version history, and campaign findings beyond
> 2026-07-01 live in `CLAUDE.md`'s dated addenda and `docs/firmware-versions.md`, not in this
> plan — this file is the original reconciliation plan and stays historical past that date.

**Goal:** Bring `teensy_controller.ino` into agreement with the actual 20260622 hardware without
touching the motor PI, power-share PI, encoder, or UDP framing logic.

**Authoritative sources consulted:**
- `Scale Car Teensy IO - IO.csv` — pin map (highest authority)
- `Scale Car Design PCB BOM 20260622.csv` — confirmed ICs on board
- `CLAUDE.md` — reconciliation spec
- `references/Datasheets/Ag105_Table3_Charge_Voltage_Select.json` — Ag105 charge voltage lookup (Table 3, DS V1.1)
- `references/Datasheets/Ag105_Table4_Charge_Current_Select.json` — Ag105 charge current lookup (Table 4, DS V1.1)
- `references/Datasheets/Ag105_Table5_Status_Output.json` — Ag105 STAT pin behaviour (Table 5, DS V1.1)
- `references/Datasheets/Ag105_Table6_I2C_Status_Byte.json` — Ag105 I2C status byte structure (Table 6, DS V1.1)
- `references/Datasheets/Ag105_Table7_I2C_Parameters.json` — Ag105 I2C register map (Table 7, DS V1.1)
- `references/Datasheets/ad5426_5432_5443.pdf` — AD5443 MDAC datasheet (SPI interface, bit depth)
- `references/Datasheets/BQ29200_TI.pdf` — BQ29200 cell balancer (DISABLE pin polarity)
- `references/Datasheets/TPS61288LRQQR.pdf` — TPS61288 boost (OVP threshold)

---

## Pre-flight: what the existing code gets wrong

| Issue | Current code | Correct |
|-------|-------------|---------|
| Pin 5 name | `CHARGER_ENABLE` | `MPPT_DISABLE` |
| Pin 6 name | `CHARGER_OK` | `CHARGER_STAT` |
| Pin 9 | missing | `CBAL_DISABLE` (OUT) |
| Pins 27-32 | missing (6 outputs) | `FC_BUS_ENABLE`, `BT_BUS_ENABLE`, `MOT_PWR_ENABLE`, `REGEN_ENABLE`, `FC_CHARGE_ENABLE`, `BT_SEQUENCE_ENABLE` |
| Pin 38 | missing | `CHG_VOLTAGE` (AIN) |
| Pin 39 | `CHRG_CURRENT` (current ADC) | `RGN_VOLTAGE` (voltage ADC) |
| ADC resolution | implicit 10-bit (ADC_MAX 1023) | must call `analogReadResolution(12)`, ADC_MAX 4095 |
| Charger IC | BQ25690 @ 0x6A, `REG_ICHG` register | Silvertel Ag105 @ 0x30, registers 0x00/0x01 |
| Charge-current measurement | `I_charge = analogRead(CHRG_CURRENT)` | ADC path gone; source from Ag105 I2C reg 0x06 instead |
| Power-path switches | never driven | RT1987 ideal-diode controllers require sequenced GPIO control |
| Cell balancer | no code | BQ29200 controlled via `CBAL_DISABLE` (pin 9) |
| Voltage scale factors | placeholder guesses | computable from BOM resistor values |
| Telemetry | includes `I_charge`, missing new rails/switch states | update struct and bump protocol version |
| Pi watchdog scope | `checkPiWatchdog()` fires in all states once Pi connects once | gate to `mainState == 2 \|\| mainState == 3` only |

---

## Step 1 — Pin map (`#define` block + `setup()` + `initX()` helpers)

**Files touched:** `teensy_controller.ino` (top of file, `setup()`)

### 1a. Rename existing defines

```
CHARGER_ENABLE  (5) → MPPT_DISABLE
CHARGER_OK      (6) → CHARGER_STAT
CHRG_CURRENT   (39) → RGN_VOLTAGE
```

Do a global find-and-replace for each old name — every use site must be updated. Verify zero
remaining references to `CHARGER_ENABLE`, `CHARGER_OK`, `CHRG_CURRENT` after the pass.

### 1b. Add missing defines

```cpp
#define CBAL_DISABLE       9    // OUT — BQ29200 cell-balancer disable
#define FC_BUS_ENABLE     27    // OUT — RT1987: FC regulator → VBUS
#define BT_BUS_ENABLE     28    // OUT — RT1987: BT regulator → VBUS
#define MOT_PWR_ENABLE    29    // OUT — RT1987: VBUS → VESC/motor
#define REGEN_ENABLE      30    // OUT — RT1987: regen → charger input
#define FC_CHARGE_ENABLE  31    // OUT — RT1987: VBUS(FC) → charger; BT_BUS_ENABLE and REGEN_ENABLE must be LOW first
#define BT_SEQUENCE_ENABLE 32   // OUT — RT1987: battery-pack sequencing; init LOW, bring HIGH once powered
#define CHG_VOLTAGE       38    // AIN — charger input voltage
// RGN_VOLTAGE is pin 39 (renamed from CHRG_CURRENT above)
```

### 1c. Update `setup()` pin modes

Add `pinMode` + safe default `digitalWrite` for every new output:

```cpp
// All path switches default OFF at boot (fail-safe; bodge resistors also pull EN low)
pinMode(FC_BUS_ENABLE,      OUTPUT); digitalWrite(FC_BUS_ENABLE,      LOW);
pinMode(BT_BUS_ENABLE,      OUTPUT); digitalWrite(BT_BUS_ENABLE,      LOW);
pinMode(MOT_PWR_ENABLE,     OUTPUT); digitalWrite(MOT_PWR_ENABLE,     LOW);
pinMode(REGEN_ENABLE,       OUTPUT); digitalWrite(REGEN_ENABLE,       LOW);
pinMode(FC_CHARGE_ENABLE,   OUTPUT); digitalWrite(FC_CHARGE_ENABLE,   LOW);
pinMode(BT_SEQUENCE_ENABLE, OUTPUT); digitalWrite(BT_SEQUENCE_ENABLE, LOW);

// MPPT_DISABLE (active-LOW): LOW = MPPT loop inhibited (fail-safe: charger off if Teensy resets)
// Source: user-confirmed from PCB schematic — pulling LOW inhibits the MPPT loop.
// [Dated correction, 2026-08-31: the mechanism is an input-voltage-threshold regulator, not
// perturb-and-observe — datasheet p.10, see CLAUDE.md §3. The polarity/sketch above is unaffected.]
pinMode(MPPT_DISABLE, OUTPUT); digitalWrite(MPPT_DISABLE, LOW);

// CBAL_DISABLE (pin 9): LOW = balancer/OVP active, HIGH = disabled.
// No external pull resistor on CB-DISABLE net (source: PCB schematic — direct GPIO connection).
// Enable internal pullup first so pin defaults HIGH (balancer disabled = safe) during any MCU
// reset/high-Z window before setup() runs. Then drive LOW to activate OVP protection.
// Source: user-confirmed from PCB schematic.
pinMode(CBAL_DISABLE, INPUT_PULLUP);            // HIGH during high-Z window — balancer off (safe)
pinMode(CBAL_DISABLE, OUTPUT); digitalWrite(CBAL_DISABLE, LOW);  // OVP active

pinMode(CHARGER_STAT, INPUT);
```

Remove the now-wrong `pinMode(CHARGER_ENABLE, OUTPUT)` and `pinMode(CHARGER_OK, INPUT)` lines.

---

## Step 2 — Power-path sequencing state machine

**Files touched:** `doState0()`, `doState1()`, `doState2()`, `doState3()`, `doState99()`, plus a new guard helper.

### 2a. Ordering rules to encode

These come from the CSV `Notes` column and CLAUDE.md §2:

1. **`BT_SEQUENCE_ENABLE`** — OFF at boot, turn ON once system powered (in State 0, after regulators start).
2. **`FC_CHARGE_ENABLE`** — before asserting, enforce `BT_BUS_ENABLE = LOW` and `REGEN_ENABLE = LOW`.
3. **`MOT_PWR_ENABLE`** — only HIGH in State 2 (Run). LOW in all others.
4. **`REGEN_ENABLE` / `FC_CHARGE_ENABLE`** — mutually exclusive.
5. **Back-feed hazard:** a disabled TPS61288 has a body-diode passthrough. If VESC is regenerating
   and a boost is disabled, regen energy can back-feed and destroy the converter. Safe ordering:
   - When *entering* a state that disables boosts: first assert `REGEN_ENABLE = LOW` (close the regen
     path), *then* disable boosts.
   - When *leaving* run: disable `MOT_PWR_ENABLE` first (no more motor current/regen), then clean up.

### 2b. New helper: `assertFcChargeEnable(bool en)`

```cpp
// Guards the mutual-exclusion rule before touching FC_CHARGE_ENABLE.
void assertFcChargeEnable(bool enable) {
    if (enable) {
        // BT_BUS_ENABLE and REGEN_ENABLE must be LOW before FC_CHARGE_ENABLE goes HIGH
        digitalWrite(BT_BUS_ENABLE, LOW);   // cut BT contribution to VBUS first
        digitalWrite(REGEN_ENABLE,  LOW);   // close regen path before routing FC → charger
        delayMicroseconds(100);             // TODO(calibrate): RT1987 turn-off propagation
        digitalWrite(FC_CHARGE_ENABLE, HIGH);
    } else {
        digitalWrite(FC_CHARGE_ENABLE, LOW);
    }
}
```

### 2c. State 0 (Init) sequence

```
1. FC_REG_ENABLE = HIGH, BT_REG_ENABLE = HIGH  (already in code)
2. All path switches LOW                         (done in setup(); verify they are still LOW)
3. BT_SEQUENCE_ENABLE = HIGH                    (NEW — battery pack now sequenced in)
4. initMdacOutputs()
5. (charger config deferred — see §12; the Ag105 is unpowered in Init and is configured
   lazily by pollAg105() once a power path opens. doState0() no longer calls initAg105Charger.)
6. initEsc()
7. → State 1
```

### 2d. Pi watchdog — scope to States 2 and 3 only

`checkPiWatchdog()` currently fires in every state once `pi_ever_connected` is set. This
means a Pi dropout while sitting in Idle trips State 99 — the system becomes unusable without
a power cycle even though it was never running. Fix by adding a state guard at the top of the
function:

```cpp
void checkPiWatchdog() {
    // Watchdog is only meaningful while the Pi is actively commanding the system.
    // States 0, 1, 98, and 99 must not fault due to Pi absence.
    if (mainState != 2 && mainState != 3) return;
    if (!pi_ever_connected) return;
    if (millis() - last_rx_ms > PI_TIMEOUT_MS) {
        mainState = 99;
        Serial.println("Pi timeout — entering error state");
    }
}
```

This also means State 98 (Testing) does **not** need to manually reset `last_rx_ms` —
the watchdog simply does not execute there.

### 2e. State 1 (Idle)

Add: `MOT_PWR_ENABLE = LOW` (belt-and-suspenders), `REGEN_ENABLE = LOW`.
No change to wait logic. State 1 waits indefinitely for `changeToRun`; it is Pi-independent
except for the fact that only a Pi packet can set that flag (or USB serial `T` for State 98).

### 2f. State 2 (Run)

```
Entry: digitalWrite(MOT_PWR_ENABLE, HIGH)  // allow power to VESC
       // FC_BUS_ENABLE and BT_BUS_ENABLE are managed by powerBalance() or set here
       // REGEN_ENABLE managed by chargingControl()
```

`chargingControl()` decides `REGEN_ENABLE` vs `FC_CHARGE_ENABLE` — they are mutually exclusive.
Braking/regen: `REGEN_ENABLE = HIGH`, `FC_CHARGE_ENABLE = LOW`.
Cruise/coast harvest: `REGEN_ENABLE = LOW`, use `assertFcChargeEnable(true)`.

### 2g. State 3 (Finish)

> **Superseded by §12 (2026-06-24).** Finish is now single-pass and **leaves the bus energized**
> (boosts + `FC_BUS`/`BT_BUS` stay ON) so Idle→Run never re-hot-plugs the 470 µF bus. It no longer
> drains the VBUS caps. The sketch below is the original plan.

```
1. vesc.setCurrent(0)
2. digitalWrite(MOT_PWR_ENABLE, LOW)    // cut motor path before anything else
3. delayMicroseconds(500)              // let motor current decay
4. assertFcChargeEnable(false)
5. digitalWrite(REGEN_ENABLE, LOW)
6. → State 1
```

Remove the stale `digitalWrite(CHARGER_ENABLE, LOW)` here.

### 2h. State 99 (Error)

Safe shutdown order (back-feed hazard):
```
1. vesc.setCurrent(0)
2. digitalWrite(MOT_PWR_ENABLE, LOW)    // stop motor current / regen
3. digitalWrite(REGEN_ENABLE, LOW)      // close regen path before touching boosts
4. assertFcChargeEnable(false)
5. delay(1)                             // TODO(calibrate): settling
6. digitalWrite(FC_REG_ENABLE, LOW)    // now safe to disable boosts
7. digitalWrite(BT_REG_ENABLE, LOW)
// BT_SEQUENCE_ENABLE stays HIGH (per design: no need to turn off again)
// CBAL_DISABLE stays LOW (balancer stays active — OVP protection still wanted)
```

---

## Step 3 — Replace BQ25690 charger code with Ag105 (Silvertel)

**Files touched:** constants block, `initBatteryCharger()` → `initAg105Charger()`, `chargingControl()`,
`setChargerTargetCurrentA()` → delete.

### 3a. Remove BQ25690 artifacts

Delete or replace every reference to:
- `CHARGER_ADDR 0x6A`
- `REG_ICHG 0x02`
- `maxChargeCurrentA`
- `setChargerTargetCurrentA()`
- The ADC read `I_charge = analogRead(CHRG_CURRENT) * SCALE_I` — no analog channel exists.

Do **not** delete the `I_charge` float variable itself. Repurpose it to hold the I2C-sourced
value from Ag105 reg `0x06` (see §3e). The telemetry slot stays; only the measurement source
changes. Update `printToTerminal()` to reflect the new source.

### 3b. Ag105 I2C constants

Values confirmed from `Ag105_Table7_I2C_Parameters.json` (Table 7, Ag105 DS V1.1):

```cpp
// Source: Ag105_Table7_I2C_Parameters.json
#define AG105_ADDR           0x30   // default I2C address (field 0xE5 default value)

// Config registers (Read+Write, stored in EPROM — settings persist across power cycles)
#define AG105_REG_ICHG_CFG   0x00   // Charge Current Setting: 0=ext resistor, 1-12 → 2.5A down to 0.1A
#define AG105_VAL_2500MA     0x01   // value 1 = 2.5 A (highest profile)
#define AG105_REG_VBATT_CFG  0x01   // Battery Voltage Setting: 0=ext resistor, 1-12 → 3.9 V to 12.6 V
#define AG105_VAL_2S         0x08   // 2S / 8.4 V / 100% capacity — Source: Ag105_Table3_Charge_Voltage_Select.json

// Measurement registers (read-only; Ag105 always returns status byte FIRST, then data byte)
#define AG105_REG_VBATT_MEAS 0x05   // Measured battery voltage; scale: 0.064 V/count
#define AG105_REG_ICHG_MEAS  0x06   // Measured charge current;  scale: 0.011 A/count
#define AG105_REG_VIN_MEAS   0x07   // Measured input voltage;   scale: 0.141 V/count

// Charge termination: the 2500mA profile cuts off at 250mA (C/10).
// Source: Ag105_Table4_Charge_Current_Select.json
//
// Power-on defaults when no external resistors are fitted:
//   reg 0x00 = 0x00 → external resistor mode → if no RCS resistor: 1000mA
//   reg 0x01 = 0x00 → external resistor mode → if no RVS resistor: 4.2V (1S)
// initAg105Charger() overrides both with explicit I2C writes at every boot.
//
// I2C read protocol: every Wire.requestFrom(AG105_ADDR, N) must read N+1 bytes.
// The Ag105 always prepends the Table 6 status byte before any requested field.
// Example for a 1-byte field: Wire.requestFrom(AG105_ADDR, 2) → read status, read data.
```

### 3c. `initAg105Charger()`

Both settings are stored in EPROM and persist across power cycles once written; re-writing
each boot is safe and ensures correct config regardless of prior state.

```cpp
void initAg105Charger() {
    // Ag105 power-on default: reg 0x00 = 0x00, reg 0x01 = 0x00 (external resistor mode).
    // Write explicit 2S/8.4V voltage and 2.5A current configs before any charging is allowed.
    // MPPT_DISABLE is LOW (active-LOW); charger output is inhibited during init.

    // Set charge current to 2.5A — Source: Ag105_Table7_I2C_Parameters.json, field 0x00
    Wire.beginTransmission(AG105_ADDR);
    Wire.write(AG105_REG_ICHG_CFG);
    Wire.write(AG105_VAL_2500MA);   // 0x01 = 2.5A
    Wire.endTransmission();

    // Set battery voltage to 2S / 8.4V (100% capacity profile)
    // Source: Ag105_Table3_Charge_Voltage_Select.json — i2c_field_value 8 = 8.4V
    Wire.beginTransmission(AG105_ADDR);
    Wire.write(AG105_REG_VBATT_CFG);
    Wire.write(AG105_VAL_2S);   // 0x08
    Wire.endTransmission();

    // Leave MPPT_DISABLE LOW (inhibited, active-LOW) until State 2 (chargingControl manages it)
}
```

### 3d. `chargingControl()` — Ag105 logic

Strategy: `MPPT_DISABLE` inhibits the MPPT loop during active regen,
released during cruise/coast so Ag105 harvests. The TL431/BSP170P braking chopper handles
fast regen spikes; do not rely on Ag105 for that.
[Dated correction, 2026-08-31: the MPPT mechanism is an input-voltage-threshold regulator, not
perturb-and-observe — datasheet p.10, see CLAUDE.md §3. The enable/release strategy above is
unaffected.]

```cpp
void chargingControl() {
    // charge_goal > 0 means Pi wants charging enabled
    if (charge_goal <= 0.05f) {
        digitalWrite(MPPT_DISABLE, LOW);        // inhibit Ag105 (active-LOW: LOW = inhibit)
        assertFcChargeEnable(false);
        digitalWrite(REGEN_ENABLE, LOW);
        return;
    }

    bool chargerReady = ag105IsReady();  // uses GENSTAT from pollAg105() — see §3e
    // CHARGER_STAT GPIO (pin 6) — Source: Ag105_Table5_Status_Output.json:
    //   Steady HIGH  = Charging
    //   50% duty 2s  = Fully Charged
    //   Pulse trains = error states (1–5 pulses per mode)
    //   Steady LOW   = Input Voltage Removed
    // A single digitalRead() cannot distinguish Charging from error pulse-highs, so
    // GENSTAT from I2C is the authoritative source. CHARGER_STAT steady-LOW can serve
    // as a fast "no input power" guard if desired.

    // Determine if VESC is regenerating (negative current = regen braking)
    bool regenActive = (current < -0.1f);   // threshold TODO(calibrate)

    if (regenActive) {
        // Fast regen: disable MPPT loop so it doesn't fight transient, open regen path
        assertFcChargeEnable(false);        // must be OFF before REGEN_ENABLE can go HIGH
        digitalWrite(REGEN_ENABLE, HIGH);
        digitalWrite(MPPT_DISABLE, LOW);    // inhibit MPPT during regen transient (active-LOW)
    } else {
        // Cruise/coast: close regen path, enable MPPT harvest via FC path
        digitalWrite(REGEN_ENABLE, LOW);
        if (chargerReady) {
            assertFcChargeEnable(true);
            digitalWrite(MPPT_DISABLE, HIGH);   // release MPPT loop — Ag105 harvests (active-LOW: HIGH = enabled)
        } else {
            assertFcChargeEnable(false);
            digitalWrite(MPPT_DISABLE, LOW);    // inhibit MPPT — charger not ready (active-LOW)
        }
    }
}
```

### 3e. New helper: `pollAg105()` + `ag105IsReady()`

Call `pollAg105()` at the **50 Hz telemetry cadence** (same `millis()` gate as `sendTelemetry()`),
not every main-loop tick. This keeps I2C overhead off the fast motor/droop control path.

**I2C read protocol:** the Ag105 always prepends the Table 6 status byte before any data byte.
Every `Wire.requestFrom(AG105_ADDR, N)` for a 1-byte field must read **2 bytes**: status first,
then data.

```cpp
// Table 6 GENSTAT bit patterns (bits 0-2 of status byte)
#define AG105_GENSTAT_CHARGING     0x02   // 010 — actively charging
#define AG105_GENSTAT_FULL         0x03   // 011 — fully charged

uint8_t  ag105_status_raw = 0;   // last raw Table 6 status byte, cached at 50 Hz

void pollAg105() {
    // Read measured charge current — Source: Ag105_Table7_I2C_Parameters.json, field 0x06
    Wire.beginTransmission(AG105_ADDR);
    Wire.write(AG105_REG_ICHG_MEAS);
    Wire.endTransmission(false);           // repeated-start
    if (Wire.requestFrom(AG105_ADDR, 2) == 2) {
        ag105_status_raw = Wire.read();    // Table 6 status byte (always first)
        I_charge = Wire.read() * 0.011f;  // A  (scale from Table 7 field 0x06)
    }
}

// Returns true when the Ag105 is in a state where charging is occurring or complete.
inline bool ag105IsReady() {
    uint8_t genstat = ag105_status_raw & 0x07;
    return (genstat == AG105_GENSTAT_CHARGING || genstat == AG105_GENSTAT_FULL);
}
```

Add the `pollAg105()` call alongside `sendTelemetry()` in `loop()`:

```cpp
if (millis() - lastSend > 20) {
    pollAg105();        // refresh I_charge and ag105_status_raw from I2C
    sendTelemetry();
    lastSend = millis();
}
```

---

## Step 4 — BQ29200 cell-balancer (pin 9)

**Files touched:** `setup()` (already handled in Step 1c), one-line note in `doState0()`.

`CBAL_DISABLE` (pin 9):
- **Confirmed polarity (source: PCB schematic):** LOW = balancer/OVP active; HIGH = disabled.
- **No external pull resistor** on the CB-DISABLE net — the net is wired directly from the
  PCB signal to the Teensy GPIO with no bodge resistor. Enable `INPUT_PULLUP` in `setup()`
  before switching to OUTPUT, so the pin defaults HIGH (balancer disabled = safe) if the GPIO
  ever goes high-Z during a reset or firmware glitch.
- Then drive LOW in `setup()` to activate OVP protection once the rails are stable.
- The `CB_EN` pin of BQ29200 is hardwired to GND in hardware → OVP-only mode; no balancer
  current register to program.
- `BAL-NOK` output is intentionally orphaned on the PCB — do **not** add an input pin for it.
- No additional runtime toggling is needed. The only scenario to drive `CBAL_DISABLE = HIGH`
  would be if the firmware needed to temporarily bypass OVP (not required for this design).

---

## Step 5 — ADC resolution and voltage scaling

**Files touched:** constants block, `updateSensors()`.

### 5a. Set ADC resolution

Add at the top of `setup()`:
```cpp
analogReadResolution(12);   // Teensy 4.1 ADC: 12-bit, 0-4095
```

### 5b. Update `ADC_MAX`

```cpp
#define ADC_MAX  4095.0f    // 12-bit resolution; matches analogReadResolution(12) above
```

### 5c. Recompute voltage scale factors from BOM resistors

Formula: `SCALE_V = Vref * (R1 + R2) / R2 / ADC_MAX`

| Rail | R1 (source) | R2 (source) | Vmax (calc) | SCALE_V |
|------|-------------|-------------|-------------|---------|
| FC   | 27.4 kΩ (BOM R1-FC) | 10 kΩ (BOM R2-FC) | 3.3×(37.4/10) = 12.342 V | 12.342/4095 ≈ 0.003014 |
| BT   | 16.2 kΩ (BOM R1-BT) | 10 kΩ (BOM R2-BT) | 3.3×(26.2/10) = 8.646 V  | 8.646/4095  ≈ 0.002112 |
| BUS  | 46.4 kΩ (BOM R1-BUS)| 10 kΩ (BOM R2-BUS)| 3.3×(56.4/10) = 18.612 V | 18.612/4095 ≈ 0.004545 |
| CHG  | 78.7 kΩ (schematic) | 10 kΩ (schematic) | 3.3×(88.7/10) = 29.271 V | 29.271/4095 ≈ 0.007148 |
| RGN  | 78.7 kΩ (schematic) | 10 kΩ (schematic) | same as CHG               | 29.271/4095 ≈ 0.007148 |

Express each #define symbolically as `ADC_VREF * (R1 + R2) / R2 / ADC_MAX` so the divider
resistor values are visible in the source. `ADC_VREF` is the existing 3.3 V reference constant.

```cpp
// Source: BOM R1-FC=27.4kΩ, R2-FC=10kΩ → Vmax = 3.3*(27.4+10)/10 = 12.342V
#define SCALE_V_FC    (ADC_VREF * (27.4f + 10.0f) / 10.0f / ADC_MAX)
// Source: BOM R1-BT=16.2kΩ, R2-BT=10kΩ → Vmax = 3.3*(16.2+10)/10 = 8.646V
#define SCALE_V_BATT  (ADC_VREF * (16.2f + 10.0f) / 10.0f / ADC_MAX)
// Source: BOM R1-BUS=46.4kΩ, R2-BUS=10kΩ → Vmax = 3.3*(46.4+10)/10 = 18.612V
#define SCALE_V_BUS   (ADC_VREF * (46.4f + 10.0f) / 10.0f / ADC_MAX)
// Source: schematic — R1=78.7kΩ, R2=10kΩ → Vmax = 3.3*(78.7+10)/10 = 29.271V
#define SCALE_V_CHG   (ADC_VREF * (78.7f + 10.0f) / 10.0f / ADC_MAX)
// Source: schematic — same divider as CHG_VOLTAGE (R1=78.7kΩ, R2=10kΩ)
#define SCALE_V_RGN   (ADC_VREF * (78.7f + 10.0f) / 10.0f / ADC_MAX)
```

### 5d. Update current scaling

Current sense is INA253A1 with K_sns = 0.1 V/A (the A1 part was fitted by mistake in place of
the intended A3 = 0.4 V/A; the board is already built, so 0.1 V/A is correct — see CLAUDE.md
§5/§7). Unipolar, 0-ref:
```cpp
// SCALE_I: 12-bit, Vref=3.3V, K_sns=0.1V/A → 3.3/(4095*0.1) = 8.06e-3 A/count
#define SCALE_I  (ADC_VREF / ADC_MAX / K_sns)   // formula unchanged; ADC_MAX now 4095
```

### 5e. Update `updateSensors()`

Remove the stale ADC charge-current read and add the two new voltage reads:
```cpp
// I_charge is no longer from ADC. It is updated by pollAg105() (§3e) at 50 Hz.
// Remove: I_charge = analogRead(CHRG_CURRENT) * SCALE_I;
V_chg = analogRead(CHG_VOLTAGE) * SCALE_V_CHG;
V_rgn = analogRead(RGN_VOLTAGE) * SCALE_V_RGN;
```

Add new float variables:
```cpp
float V_chg = 0;   // charger input voltage (pin 38, ADC)
float V_rgn = 0;   // regen-node voltage    (pin 39, ADC)
// I_charge already declared; source changes from ADC to Ag105 I2C reg 0x06 × 0.011
```

---

## Step 6 — Faults, telemetry, and commands

### 6a. Fault updates

Keep existing `FAULT_OC_FC`, `FAULT_UV_BATT`, `FAULT_OV_BUS`. Adjust limits:

```cpp
#define LIMIT_V_BUS_MAX  (V_BUS_NOMINAL + 1.5f)  // = 17.5 V at the 16.0 V nominal; TPS61288 HW OVP at 19V
                                 // Source: 2026-07-11 RD1=215k FB retune (V0 = 15.91 V no-load);
                                 // the original 17.5V-nominal/18.5f pair is STALE (pre-retune)
#define LIMIT_V_BATT_MIN  6.2f  // V — 2S LiPo cutoff (2 × 3.1V); keep existing

// New fault: illegal switch combination
#define FAULT_SWITCH_CONFLICT  0x08  // FC_CHARGE_ENABLE asserted with BT_BUS or REGEN
```

Add to `detectFaults()`:
```cpp
// Detect illegal FC_CHARGE_ENABLE combination (belt-and-suspenders, guard also prevents it)
if (digitalRead(FC_CHARGE_ENABLE) && 
    (digitalRead(BT_BUS_ENABLE) || digitalRead(REGEN_ENABLE))) {
    fault_flags |= FAULT_SWITCH_CONFLICT;
}
```

### 6b. Telemetry struct — bump to protocol v4 (charger_status reinstated)

Now that `I_charge` is sourced from Ag105 I2C reg 0x06 (§3e) rather than a nonexistent ADC
channel, its **telemetry slot stays at the same offset** — the Pi parser doesn't move. The
only fields that change meaning are `P_motor_actual` (dropped; Pi can compute V_bus × current)
and `power_share_echo` (dropped; Pi echoes its own setpoint). The two freed float slots absorb
`V_rgn` and `V_chg`. (`charger_status` was dropped in v2 in favour of `switch_state`, then
**reinstated in v4** at offset 51 carrying the raw Ag105 status byte — see the v4 note below.)

**v4 layout — 58 bytes, checksum span bytes 1–56:**

The v2 step (above) replaced `P_motor_actual`/`power_share_echo`/`charger_status` with
`V_rgn`/`V_chg`/`switch_state`. v3 then widened `fault_flags` to `uint16_t` (the bitmask
outgrew 8 bits) and appended `error_code` + `error_source_state` so the Pi can surface the
latched root cause of a State-99 entry. **v4 reinstates `charger_status` at its historic
offset 51** — but now carrying the **raw Ag105 Table 6 status byte** (`ag105_status_raw`),
which is a superset of the old BQ25690 off/CC/CV/fault field: the Pi decodes CC (bit 6),
CV (bit 5), and faults (GENSTAT `0x05`–`0x07`) directly from it. `switch_state` and all
following fields shift +1; the checksum moves from byte 56 to byte 57.

| Offset | Bytes | Field | Change |
|--------|-------|-------|--------|
| 0 | 1 | SYNC `0xAA` | — |
| 1 | 4 | timestamp ms | — |
| 5 | 2 | pkt_counter_T | — |
| 7 | 4 | v_actual | — |
| 11 | 4 | V_batt | — |
| 15 | 4 | I_batt | — |
| 19 | 4 | **I_charge** (from Ag105 I2C reg 0x06) | SOURCE CHANGED (v2) |
| 23 | 4 | V_fc | — |
| 27 | 4 | I_fc | — |
| 31 | 4 | V_bus | — |
| 35 | 4 | **V_rgn** (was P_motor_actual) | REPLACED (v2) |
| 39 | 4 | **V_chg** (was power_share_echo) | REPLACED (v2) |
| 43 | 4 | power_share_actual | — |
| 47 | 2 | fc_u16 (droop gain) | — |
| 49 | 2 | bt_u16 (droop gain) | — |
| 51 | 1 | **charger_status** (raw Ag105 Table 6 byte = `ag105_status_raw`) | REINSTATED (v4) — see decode below |
| 52 | 1 | **switch_state** (bitmask) | shifted +1 (v4) — see bitmask below |
| 53 | 2 | **fault_flags** (uint16_t LE) | shifted +1 (v4); WIDENED (v3, was 1 byte) |
| 55 | 1 | **error_code** (ErrorCode_t) | shifted +1 (v4); NEW (v3) |
| 56 | 1 | **error_source_state** (mainState at first fault) | shifted +1 (v4); NEW (v3) |
| 57 | 1 | checksum (XOR of bytes 1–56) | span extended (v4) |

`switch_state` bitmask (bits 6-7 reserved = 0):
```cpp
#define SW_FC_BUS      0x01
#define SW_BT_BUS      0x02
#define SW_MOT_PWR     0x04
#define SW_REGEN       0x08
#define SW_FC_CHARGE   0x10
#define SW_BT_SEQ      0x20
```

`charger_status` (byte 51) is the raw Ag105 Table 6 status byte, forwarded verbatim from
`ag105_status_raw` (cached at 50 Hz by `pollAg105()`; Source:
`references/Datasheets/Ag105_Table6_I2C_Status_Byte.json`). The Pi decodes it directly:

```
bits 0–2  GENSTAT: 0=Battery Disconnect, 1=Low Power, 2=Charging, 3=Fully Charged,
                   4=Bring-Up, 5=OC/Regulation err, 6=Thermal Shutdown, 7=Timeout err
bit 3     MPPT enabled
bit 4     Power Tracking
bit 5     Constant Voltage (CV)
bit 6     Constant Current (CC)
bit 7     Thermal Limiting
```

This restores the old off/CC/CV/fault telemetry (off = GENSTAT 0/1; CC = bit 6; CV = bit 5;
fault = GENSTAT 5/6/7) and supersedes it — the Pi no longer needs to infer charger state from
`I_charge` > 0 or poll I2C separately.

Add a compile-time constant (not an in-packet byte) to let the Pi detect version mismatches:
```cpp
#define TELEMETRY_VERSION 4   // increment whenever the packet layout changes
```

Document the full layout in a block comment directly above `sendTelemetry()`.

### 6c. Commands

The 22-byte command packet is structurally unchanged. The `droop_enable` byte remains reserved
(parsed and discarded). Add a comment noting it is reserved for a future protocol extension:
```cpp
uint8_t droop_enable_reserved = buffer[idx++];   // reserved — not yet wired to hardware
(void)droop_enable_reserved;
```

---

## Step 7 — MDAC / droop verification

**No code changes expected.** Verify these facts against `AD5443` datasheet:

| Claim | Status |
|-------|--------|
| SPI_MODE0, MSBFIRST | TODO(verify: `ad5426_5432_5443.pdf` §SPI timing — file now in `references/Datasheets/`) |
| `transfer16()` (16-bit words) | TODO(verify: `ad5426_5432_5443.pdf` §input data format) |
| `MDAC_res = 4095` (12-bit) | TODO(verify: `ad5426_5432_5443.pdf` §resolution / product overview) |
| OPA197 output ceiling set by 5V rail (bodge) | No firmware change; note in comment |

If verification confirms all four, leave the droop math (`k_eq`, `A_v`, `K_sns`) intact.

---

## Step 8 — Changelog header and final cleanup

Add a block comment at the very top of `teensy_controller.ino` (before `#include`s):

```cpp
/*
 * teensy_controller.ino — Scale Car DC Balancer Board, Rev 20260622
 *
 * CHANGELOG vs. pre-20260622 firmware:
 *  - Pin map rebuilt from Scale_Car_Teensy_IO__IO.csv (CSV is authoritative).
 *  - CHARGER_ENABLE/CHARGER_OK/CHRG_CURRENT renamed; 9 new pins added (27-32, 9, 38, 39).
 *  - BQ25690 charger code (0x6A/REG_ICHG/setChargerTargetCurrentA) removed entirely.
 *    Replaced with Silvertel Ag105 MPPT charger (GPIO MPPT_DISABLE + I2C config).
 *  - RT1987 ideal-diode switches added: 6 new GPIOs with enforced sequencing state machine.
 *  - BQ29200 cell-balancer: CBAL_DISABLE (pin 9) driven LOW by default (OVP active).
 *  - ADC resolution set explicitly to 12-bit; ADC_MAX updated to 4095.
 *  - Voltage scale factors recomputed from BOM resistor values.
 *  - I_charge ADC path removed; I_charge now sourced from Ag105 I2C reg 0x06 (0.011 A/count).
 *  - V_chg and V_rgn added as ADC inputs (pins 38, 39).
 *  - Telemetry bumped to protocol v3 (57 bytes; TELEMETRY_VERSION = 3); switch_state byte
 *    added, fault_flags widened to uint16_t, error_code + error_source_state appended.
 *  - Telemetry bumped to protocol v4 (58 bytes; TELEMETRY_VERSION = 4); charger_status
 *    reinstated at offset 51 as the raw Ag105 Table 6 status byte; switch_state and following
 *    fields shifted +1; checksum span now bytes 1–56.
 *  - Back-feed hazard: REGEN_ENABLE always driven LOW before disabling TPS61288 boosts.
 */
```

---

## Step 9 — Testing State (State 98)

**Files touched:** `teensy_controller.ino` — new `doState98()` function, command parsing in `loop()`.

### 9a. Overview

State 98 is a USB serial-driven hardware exerciser. It is reachable only from State 1 (Idle)
and exits back to State 1 on command or fault. The Pi watchdog (`lastPiMsg` timeout that
transitions to State 99) is **suspended** while in State 98; the drive cycle provides its own
internal timing. `detectFaults()` still runs every main-loop tick — a fault trips State 99
regardless of test mode.

Transition in: while in State 1, receive character `T` (or command `"test"`) on USB Serial.
Transition out: command `Q` (or `"quit"`) → State 1; fault detection → State 99 as normal.

### 9b. Serial command set

All commands are single uppercase characters, processed in `doState98()`:

| Char | Action |
|------|--------|
| `F` | Toggle `FC_REG_ENABLE` (FC boost on/off) |
| `B` | Toggle `BT_REG_ENABLE` (BT boost on/off) |
| `1` | Toggle `FC_BUS_ENABLE` |
| `2` | Toggle `BT_BUS_ENABLE` |
| `3` | Toggle `MOT_PWR_ENABLE` |
| `4` | Toggle `REGEN_ENABLE` (via `assertFcChargeEnable(false)` first if needed) |
| `5` | Toggle `FC_CHARGE_ENABLE` (via `assertFcChargeEnable()` guard) |
| `6` | Toggle `BT_SEQUENCE_ENABLE` |
| `C` | Toggle `CBAL_DISABLE` (HIGH = OVP bypassed; use with caution) |
| `M` | Toggle `MPPT_DISABLE` (HIGH = MPPT enabled; LOW = inhibited) |
| `N` | Dynamic Ag105 MPPT reg-`0x02` threshold status/verify (fw v24) |
| `D` | Start/stop simulated drive cycle (§9c) |
| `S` | Print status (all pin states, all ADC readings, `I_charge`, bench-tool state) |
| `I` | Scan the I2C bus |
| `E` | Read VESC firmware version + telemetry snapshot (incl. live fault code via `vescFaultStr()`) — one-shot |
| `U` | Toggle VESC watch: ~2 Hz `getVescValues()` poll printing a compact line and flagging any fault-code change. Auto-suppressed while any profile runs so those keep production-identical control-loop timing; resumes on stop. **Rebound from `W` on 2026-08-10** (mnemonic: "UART watch") to free `W` for the combined current profile |
| `G` | Staged bus bring-up (`busBringupTick()` P0–P3: bus alone → boosts → dwell → motor node; `X`/`Q` abort → stage dark) |
| `P` | Set power-share setpoint (closed-loop live — prompts for a float; §9e) |
| `O` | Set droop ratio (open-loop direct MDAC write — prompts for a float; §9e) |
| `A` | Set manual motor **current** in A (prompts for a float; §9e) |
| `V` | Set manual motor **velocity** in m/s (prompts for a float; §9e) |
| `R` | Start/stop power-share profile emulator (§9e) |
| `T <Imax> <hold> <rate>` | Start trapezoidal motor-current profile — all three values on one line (peak A / hold s / rate A/s, e.g. `T 6 5 0.5`); bare `T` while running stops it; direct phase-current command, no velocity-chain calibration and no `MOT_PWR_ENABLE` gate (§9f) |
| `Y [Vmax] [b]` | Start combined drive-cycle + power-share profile — sweeps `v_setpoint` **and** `power_share_setpoint` from one 16-region table; both values optional on one line (bare `Y` runs the defaults, e.g. `Y 1 0.3`); bare `Y` while running stops it; same prerequisites as `D` (§9h) |
| `W [Imax] [b]` | Start combined **current** + power-share profile — the same 16-region table with the motor axis in amps; both values optional on one line (bare `W` runs the defaults, e.g. `W 6 0.0`); bare `W` while running stops it; `T`-style prerequisites — no velocity-chain calibration, `MOT_PWR_ENABLE` warn-only (§9i) |
| `X` | Universal stop: cancel any running profile (`D`/`R`/`T`/`Y`/`W`), armed plot-mode run, or bring-up + manual motor + power-share live (motor zeroed; switches parked only if `D`/`R`/`Y`/`W` was running, mirroring their own stop paths) |
| `L` | Toggle Serial-Plotter stream: 50 Hz `share_sp,share_act,gFC,gBT,ifc,ibt,v_sp,v_act,enc_pos,edgeA,edgeB` line (11 fields, fw v19); suppresses the periodic status/phase/`[VW]` lines; `R`/`T` arm with a `PLOT_ARM_DELAY_MS` delay (see the `L` paragraph below §9e) |
| `K` | Single-line SD-logger command (fw v9): empty line = status (card, current/last file, record/drop counts, ownership marker — §9g; status stays live during the bring-up lockout); `K 1` = start a MANUAL log (`ML####.BLG`) for hand-driven runs; `K 0` = stop it (refused on a profile-owned log) |
| `H` / `?` | Print the command list (`printTestHelp()`) |
| `Q` | Exit State 98 → State 1 (forces `MOT_PWR_ENABLE` LOW; closes charge/regen paths; drops plot mode + any armed run) |

**Safety rules still enforced in State 98:**
- `FC_CHARGE_ENABLE` (key `5`) always goes through `assertFcChargeEnable()` — the guard
  drives `BT_BUS_ENABLE` and `REGEN_ENABLE` LOW before asserting the pin.
- `detectFaults()` runs every loop; a fault overrides all test-mode state and latches State 99.
- Toggle operations print the new state to USB Serial for confirmation.

### 9c. Simulated drive cycle

The drive cycle runs as a simple state machine inside `doState98()`, gated on `millis()`.
It requires `MOT_PWR_ENABLE` to be HIGH before starting; if not, print an error and abort.
The profile is pre-programmed and replaces Pi-supplied `v_setpoint`:

```
Phase        Duration   v_setpoint   Action
─────────────────────────────────────────────────────────────────────────
Standstill     2 s        0.0        Verify sensors, confirm no faults
Ramp-up        4 s        0 → 3.0    Linear ramp; motorControl() live
Cruise         6 s        3.0        Steady speed; powerBalance() live
Coast-down     3 s        3 → 0      Linear ramp down
Regen hold     3 s        −0.5       Negative setpoint (regen braking)
Standstill     2 s        0.0        Confirm I_charge > 0 if charger enabled
```

During the drive cycle:
- `motorControl()`, `powerBalance()`, and `chargingControl()` execute normally — do **not**
  modify their logic. The drive cycle only sets `v_setpoint`; the PI controllers do the rest.
- `pollAg105()` and `sendTelemetry()` run at their normal 50 Hz cadence so telemetry is
  live during the test.
- USB Serial prints a one-line status snapshot every 500 ms: timestamp, v_setpoint, v_actual,
  V_bus, I_fc, I_batt, I_charge, fault_flags.
- Drive cycle ends after all phases complete; `v_setpoint` is set to 0 and `MOT_PWR_ENABLE`
  stays at whatever the operator left it (they must toggle it OFF manually with key `3`).

### 9e. Power-share bench tools (manual motor, droop setpoint, power-share profile)

These exercise the **droop / power-share controller** directly (the drive cycle exercises the
velocity half). Numeric values are entered with a **typed key → serial prompt → next line parsed
as a float** flow: the key sets `pendingInput` and prints a prompt; subsequent chars accumulate in
`inputBuf` until newline, then `atof()` dispatches to the setter. This is non-blocking, so
`detectFaults()` keeps running while the operator types (`handlePendingInputChar()`).

**Manual motor (`A` / `V`).** Holds the motor at a constant command so the power-share controller
can be characterized independent of wheel speed. Two modes (`MotorTestMode`):
- `MOTOR_TEST_CURRENT` (`A`): `current = manualMotorCurrent; vesc.setCurrent()` — bypasses the
  velocity PI. Clamped to `±MOTOR_I_CMD_MAX`.
- `MOTOR_TEST_VELOCITY` (`V`): feeds `v_setpoint` and runs the existing `motorControl()` PI.

`applyManualMotor()` applies the active mode each tick. `X` stops it (mode OFF, motor zeroed).

**Power-share setpoint (`P` / `O`).** Two ways to set the droop:
- `P` closed-loop live (`setPowerShareSetpointLive()`): sets `power_share_setpoint` (clamped
  0.01–0.99) and `powerBalanceLive = true`, so `powerBalance()` runs each tick and drives the MDAC
  from the measured `I_fc`/`I_batt` error. Needs current flowing (motor running) to update the MDAC.
- `O` open-loop direct (`applyOpenLoopDroop()`): maps a typed droop ratio straight to the droop
  gains (same math as `powerBalance()`) and writes `setDroopMdac()` immediately — no PI, no current
  needed. Good for bench-calibrating the droop hardware. Clears `powerBalanceLive`.

**Power-share profile emulator (`R`).** Mirrors the drive cycle, but sweeps `power_share_setpoint`
through a phase table (`advancePowerShareProfile()`) while the motor is held at the constant
command set by `A`/`V`, so the share-controller step response can be measured. Preconditions:
`MOT_PWR_ENABLE` HIGH and a manual motor mode set (warns if `V_bus` is low). It deliberately does
**not** call `chargingControl()` (unlike the drive cycle) — the regen/FC-charge paths stay static
under operator control so the only varying input is the droop split. Default profile
(`TODO(calibrate)`):

```
Phase   Duration   power_share_setpoint   Note
──────────────────────────────────────────────────────────
0         3 s       0.5                   settle at 50/50
1         1 s       0.5 → 0.8             step toward FC-heavy
2         4 s       0.8                   hold
3         1 s       0.8 → 0.2             step toward BT-heavy
4         4 s       0.2                   hold
5         2 s       0.2 → 0.5             return to balanced
```

Status snapshot every 500 ms: setpoint, measured share `|I_fc|/(|I_fc|+|I_batt|)`, `I_fc`,
`I_batt`, droop gains, `V_bus`, `fault_flags`. The drive cycle (`D`) and power-share profile (`R`)
are mutually exclusive; starting one clears the other. Both `R`-stop and `Q`-exit zero the motor
and reset the bench-tool state. `X` is the universal stop: it cancels whichever profile is
running (`D`/`R`/`T`) plus the manual modes and the live share loop, mirroring each profile's own
stop semantics (switches parked for `D`/`R`, left as-is for `T`).

**Serial-Plotter stream (`L`).** Toggles a condensed 50 Hz (`PLOT_PERIOD_MS`) output line the
Arduino IDE Serial Plotter parses directly — **eleven** labelled fields, fixed shape (fw v19;
six through fw v6, eight through fw v18):
`share_sp:…,share_act:…,gFC:…,gBT:…,ifc:…,ibt:…,v_sp:…,v_act:…,enc_pos:…,edgeA:…,edgeB:…`
(setpoint, measured share, both droop gains, both channel currents, velocity setpoint and measured
velocity, then the raw encoder diagnostics: `encoderPos` — the ×2 quadrature count — and the
per-channel ISR edge counters `encEdgeCountA`/`encEdgeCountB`). The first eight are naturally 0–3
so the plotter's shared autoscale keeps them readable; the three encoder fields are unbounded
integers and will dominate the autoscale — that is accepted, because their use case is watching a
hand-rotated wheel, and voltages stay on `S`. The field count is **fixed** (the plotter keys its
series off the labels and re-legends the graph if the count varies mid-run), and the
`Serial.availableForWrite()` backpressure guard is sized for the worst-case line **with headroom**
(192 B at fw v19; the itemized worst case is an exact 165 B, and an exact fit is not a guard — one
8-character float would block the USB-CDC write and stall the loop). The itemization lives at the
guard in the source; re-derive it, do not estimate, when adding a field.
While ON, every periodic human-readable line that would break the plotter's parse is
suppressed via `plotSuppressStatus()`: the three profiles' 500 ms snapshots, their phase banners,
and the `[VW]` VESC-watch line (VESC faults latch; re-check after `L` off). One-shot
start/stop/complete notices are kept. Because the IDE 2.x plotter has no send box (and may close
the Serial Monitor), `R` and `T` under plot mode **arm** instead of starting: the run fires
`PLOT_ARM_DELAY_MS` (5 s, `TODO(calibrate)`) later via `plotArmTick()`, giving time to switch
windows. `R`'s preconditions are checked at the keypress (refusal is visible) **and** re-checked
at fire time (a `3` during the countdown cancels the arm). Arming is refused outright while
another profile is already running (the immediate path's takeover semantics would become a
delayed surprise); arming the *other* profile supersedes a pending arm with an explicit cancel
message. The arm is cancelled by: pressing the same key again, `X`, `Q` (which also drops plot
mode — it is a State-98-only tool), turning `L` off, or any bring-up/profile starting during the
window. While plotting, value prompts are newline-terminated and the `[OV]` transient report and
UDP checksum-mismatch print are suppressed too (counters still increment; see `S`); `plotTick()`
drops a sample rather than block when the USB host isn't draining. `D` is deliberately not armed — the plot
fields are share-loop signals, not drive-cycle ones. Plot state resets on `Q` exit; tests cover
the wire format, rate gate, suppression/restore, arm/fire/cancel paths, and the fire-time
precondition re-check.

**Share-governor / slew constant family (`powerBalance()`).** PLAN.md does not otherwise carry a
consolidated list of these; the authoritative derivations live at each constant in
`teensy_controller.ino`. Recorded here because the fw v19 additions are safety-relevant:

| Constant | Value | Role |
|---|---|---|
| `SHARE_MINORITY_I_MIN_A` | 0.30 A | Light-load conduction floor. Closed-loop share control is entered above `2×` it (0.60 A of filtered total) and exited `SHARE_GOV_OL_HYST_A` lower; it also sets the governor's effective-setpoint floor clip. |
| `SHARE_GOV_OL_HYST_A` | 0.05 A | Hysteresis on the CLOSED→OPEN mode exit. |
| `DROOP_RATIO_SLEW_PER_TICK` | 0.02/tick | Nominal per-tick ceiling on the commanded droop-ratio step; bounds the antiphase MDAC slam behind the TP0010/TP0013 dropout cycles. |
| `SHARE_HANDOFF_MIN_A` | **0.15 A** (fw v19) | DARK threshold. A channel below this is **not meaningfully conducting** — its ideal diode is effectively open, so load it is commanded to take up requires an *analog* handoff the reactive RT1987 completes only after the bus sags. Set above TP0201's 0.08 A pre-arm trickle and at half `SHARE_MINORITY_I_MIN_A`, so a channel the governor considers healthy is never called dark. Tested on a **filtered** magnitude (EMA at `SHARE_GOV_FILT_ALPHA`), never a raw ADC read. |
| `SHARE_HANDOFF_LIVE_A` | **0.20 A** (fw v19) | LIVE re-entry threshold — hysteresis on the same test, so a filtered magnitude sitting on 0.15 A cannot chatter the ceiling. |
| `DROOP_RATIO_SLEW_HANDOFF_PER_TICK` | **0.002/tick** (fw v19) | The reduced ceiling used while either channel is dark — 10× slower, ~170 ms for a 0.3-span walk at the ~880 Hz loop rate. |
| `SHARE_HANDOFF_DWELL_MAX_TICKS` | **175 ticks** ≈ 200 ms (fw v19) | Maximum slew-limited ticks **on which the ratio actually moved** per dark event. Past the cap the FULL rate resumes even while the channel stays dark; the allowance re-arms only on a LIVE transition, so a persistently dark channel cannot pin the loop slow. The **motion gate is load-bearing**: TP0201's pre-arm was a ~1.7 s in-band feedforward *hold* with BT dark, so an elapsed-tick counter would have spent the whole allowance before the arming walk and run the hazardous crossing at the full rate. Motion is read from `droopSlew_prev`, the MDAC-truth ratio, with a deliberate one-tick lag. |

`updateShareSlewMode()` runs **once per `powerBalance()` tick**, above the open-loop feedforward
branch (which returns early) so feedforward ticks advance the filters and dwell counter too, and
stores the tick's ceiling; **all three** in-band slew sites (open-loop feedforward,
effective-setpoint reference, closed-loop actuation) read that one stored value, which makes the
fw v6 requirement — reference and actuation cannot disagree — structural rather than accidental.
Evidence, the honest fw v6 review-S4 interaction (S4's ~35-tick bound is **relaxed**, to at most
`SHARE_HANDOFF_DWELL_MAX_TICKS` of slow *walk* plus a fast remainder, once per dark event — the
motion gate leaves that walk-length bound intact, since S4's hazard is the walk itself; the earlier
"disjointness" claim is struck), and the deferred anti-windup residual are recorded at
`updateShareSlewMode()`, in the fw v19 changelog entry, and in `docs/boost-bringup-debug.md`
(TP0178/TP0201 handoff-gap entry). Converged holds with both channels conducting are
bit-identical to fw v18. State is seeded DARK at boot and by `resetShareControlState()`.

**Operator note.** A setpoint-latch release with the re-closed channel still dark walks at the
handoff rate for up to ~200 ms before reverting to the full rate. That lag is the mitigation
working, not a stuck loop.

**Observability.** The slew mode is **not** reconstructible from a bench log — the decision uses
filtered magnitudes, hysteresis state and a dwell counter, none of which are in the BLG record.
The State-98 `'S'` dump's `share slew mode:` line (FULL / HANDOFF / CAPPED, both filtered
magnitudes, the dwell counter and the tick's step) is the only observable. `CAPPED` means the
allowance is *spent*, not that the channel has been dark a long time — a long static hold with a
dark channel reads `HANDOFF` with `dwell` unchanged.

### 9f. Trapezoidal motor-current profile (`T`)

A fourth motor driver (alongside manual current/velocity, the drive cycle, and the power-share
profile), mutually exclusive with the drive cycle (`D`) and the power-share profile
(`R`) — starting it clears both of the others and takes exclusive motor ownership via
`haltMotorOutput()`. Unlike the drive cycle it drives `commandMotorCurrent()` directly, bypassing
the velocity PI entirely, so it does **not** require `velocityChainCalibrated()`.

All three parameters are typed on ONE line with the command: **`T <Imax A> <hold s> <rate A/s>`**
(e.g. `T 6 5 0.5` = 6 A peak, 5 s plateau, 0.5 A/s ramps). The chars after the `T` accumulate
under `PEND_TRAP_PARAMS` and `parseTrapParamsLine()` parses them on the newline. (An earlier
per-value prompt chain broke on line-based terminals: `T`+Enter cancelled at the empty first
prompt, and the digits typed afterwards fell through as switch-toggle commands.) `T` does **not**
gate on `MOT_PWR_ENABLE` — the VESC may be bench-powered from a separate supply; if `MOT_PWR`
really is its only source an unpowered VESC just does nothing, so the handler only WARNs.
Validation (any failure rejects the whole line — no partial parameter set):
- **Peak current (A, ±`TRAP_I_ABS_MAX` = 25 A, the VESC Six EDU continuous rating)** — negative
  values are allowed by design (a braking/regen torque test). Deliberately NOT bounded by
  `MOTOR_I_CMD_MAX` (5 A): that is a source-power budget on the velocity-PI paths, but
  `setCurrent()` commands the VESC's three-PHASE motor current, which does not map 1:1 onto bus
  draw (`I_bus ≈ D·I_mot/η`). The send goes through `commandMotorCurrentLimited()` with the
  25 A ceiling (the P0-3 chokepoint guarantees — non-finite → 0 A, `current` mirror — are kept).
  Refused if `|peak| < 1e-3` (a zero peak is a no-op and would produce a 0 ms ramp).
- **Hold time at peak (s, >= 0)** — 0 is legal (pure up/down triangle, no plateau).
- **Ramp rate (A/s, > 0)** — refused if <= 0 (it is a divisor for the ramp duration).

Ramp duration is derived as `|peak| / rate`, floored at
1 ms. The profile is a symmetric trapezoid (same rate up and down):

```
Phase        Duration            I_cmd
──────────────────────────────────────────────────
Ramp-up      |peak|/rate         0 → peak (linear)
Hold         operator-set        peak
Ramp-down    |peak|/rate         peak → 0 (linear)
```

`advanceTrapProfile()` runs the same structure as `advanceDriveCycle()`/`advancePowerShareProfile()`
but issues the commanded current itself (rate-gated on `rl_motor_last`/`MOTOR_CTRL_PERIOD_US`, the
same gate `motorControl()`/`applyManualMotor()` use, so two writers can never collide in one tick).
`powerBalanceGated()` runs alongside so the FC/BT share can be watched while the motor current
ramps; `chargingControl()` deliberately does **not** run — the charge/regen paths stay static under
operator control, same rationale as the power-share profile. Natural completion (elapsed >= ramp +
hold + ramp) flushes a zero and clears `manualMotorMode` exactly as the `T`-stop path does
(`haltMotorOutput()` symmetry — see design-review-2026-07-28.md P0-2).

**Unlike `D`/`R`, stopping (`T` again, or natural completion) does NOT call `safeAllSwitches()`.**
The trapezoid never touches a path switch, so the operator's configured power paths are an input
to the test, not state to reset — tearing them down on every stop would drop the Death-5 motor-node
pre-charge and force a full `G` bring-up between back-to-back runs. Only the motor is zeroed. `Q`
still forces everything closed on exit as usual (`trapProfileActive` cleared, any half-typed
parameter line dropped, `MOT_PWR_ENABLE` forced LOW).

The VESC watch (`U`, rebound from `W` on 2026-08-10) is auto-suppressed while `trapProfileActive`, same as for `D`/`R`, so the
production control-loop timing isn't perturbed by the ~100 ms blocking `getVescValues()` poll.

Status snapshot every 500 ms: elapsed time, phase, `I_cmd`, `I_fc`, `I_batt`, `V_bus`,
`fault_flags`.

### 9g. SD-card bench logging

The Youla-H power-share controller runs at 1 kHz (`POWER_BAL_PERIOD_US`), but the `L`
Serial-Plotter stream is only 50 Hz — 20x too coarse to see the share loop's actual transient.
State 98 gains on-board logging to the Teensy 4.1's built-in micro-SD (SDIO, its own bus — no
contention with the MDAC SPI), auto-tied to the profile lifecycle, with the same non-blocking
discipline as everything else in the state machine.

**Auto lifecycle, no manual arm.** Logging opens automatically when a profile starts —
`startPowerShareProfile()` (`'R'`), `startTrapProfile()` (`'T'`), `startCombinedProfile()`
(`'Y'`), `startCurrentComboProfile()` (`'W'`), or the `'D'` start block — and closes on every exit
path: natural completion (`advancePowerShareProfile()` / `advanceTrapProfile()` /
`advanceDriveCycle()` / `advanceCombinedProfile()` / `advanceCurrentComboProfile()`), the matching
stop-toggle (`'R'`/`'T'`/`'D'`/`'Y'`/`'W'` again), `'X'` universal stop, `'Q'` exit, and fault. There is no separate arm/disarm command —
a card present at profile start is logged; a missing card is silently skipped (below). The
fault path is deferred: `triggerFault()` only sets a close-request flag (no I/O in the fault
transition itself); the drain in `loop()` finishes writing and closes the file during State 99's
teardown, so the safety transition itself does no SD I/O; the drain is additionally held off
until `state99Phase == 3`, so the teardown's 10 ms dwells run at their intended length.

**Sampling — 1 kHz.** `logSampleTick()` runs in `doState98()`'s post-serial tick section, gated
by the same wrap-safe `rateLimitDue(rl_log_last, POWER_BAL_PERIOD_US)` mechanism the PI
controllers use — one sample per elapsed `POWER_BAL_PERIOD_US`, timestamped with `micros()` per
record (unlike the drifting `millis()` restamp the `'L'` stream warns against). The gate shares
the controllers' no-backfill catch-up semantics: a stalled loop tick skips the control update
AND its sample, so the log records every control update that actually ran, and loop stalls
appear as `t_us` gaps (the decoder reports max interval / missed periods). A sample is a
52-byte memcpy into a ring buffer; no formatting, no I/O on the sampling path.

**Record layout (52 bytes, little-endian, packed):**

> **Format note (current: v7, 106 B, fw v20).** The table below is the ORIGINAL v1 record and is
> kept because every field in it still holds its v1 byte offset — the format has only ever been
> APPENDED to. Subsequent versions: v3 (68 B) added `V_fc`/`V_batt`/`V_chg`/`V_rgn`; v4 (68 B,
> header-only) added the committed per-run profile parameters; v5 (76 B, fw v11) added `u_unsat`
> and `drive_x0`; v6 (92 B, fw v16) added `encoder_pos`, `enc_period_ref_us`,
> `enc_multi_pitch_count`, `enc_spurious_drop_count`; **v7 (106 B, fw v20) added
> `enc_edge_count_a` (offset 92), `enc_edge_count_b` (96), `enc_phase_ewma` (100),
> `enc_duty_a_ewma` (102) and `enc_duty_b_ewma` (104)**. The header layout is unchanged from v4;
> only `hdr[4]` (the format version, now 7) and `hdr[5]` (the record size, now 106) differ.
> Decoders read the record stride from `hdr[5]`, never assume it.
>
> The two v7 **counters** are the raw per-channel ISR edge counts — the direct before/after metric
> for the Schmitt front-end fix, and the only signal that separates a dead channel from a dead
> estimator offline. The three v7 **levels** are quadrature geometry: shift-based integer EWMAs
> (α = 1/4), fixed point in **1/256ths of one slot pitch**, computed in the ISRs. Phase is the
> last accepted A-rising edge to the next B-rising edge over `encPeriodRefUs` (the sensor pair's
> mount geometry, direction-gated to forward and plausibility-gated at `dt < period_ref`); the two
> duties are each channel's rise-to-fall high time over the same reference (that channel's optical
> health, independent of the mount). Expected healthy on this board: **phase 64 (0.25 pitch), both
> duties 128 (0.50)** — the 43° sensor offset is 10.75 pitches, but the sensors were physically
> swapped with the 90-slot wheel, so A leads B forward and the fraction is the complement. All
> three are printed in the State-98 `'S'` dump as pitch fractions.
>
> **Decoder contract — three field classes, and mixing them up produces plausible nonsense:**
> **levels** (`enc_period_ref_us`, `enc_phase_ewma`, `enc_duty_a_ewma`, `enc_duty_b_ewma`) are read
> directly and NEVER differenced, and a 0 means "no measurement yet" rather than a real zero;
> **reset-cleared counters** (`enc_multi_pitch_count`, `enc_spurious_drop_count`) are diffed for a
> rate, where a negative diff is a mid-run `encoderVelReset()` — which also clears all four levels,
> since they are normalised by `enc_period_ref_us`;
> **boot-monotonic counters** (`enc_edge_count_a`/`_b`) are never cleared by anything, so a
> negative diff there is a uint32 wrap or an MCU reset. The authoritative per-field layout is the
> `BenchLogRecord` struct in `teensy_controller/teensy_controller.ino`, whose `offsetof`
> static_asserts pin every offset.

| Field | Type | Source |
|---|---|---|
| `t_us` | u32 | `micros()` at sample |
| `share_sp` | f32 | `power_share_setpoint` — power-share setpoint |
| `share_act` | f32 | actual power share, recomputed locally with the same formula as `plotTick()` |
| `v_sp` | f32 | `v_setpoint` — drive-cycle velocity setpoint |
| `v_act` | f32 | `v_actual` — measured wheel velocity |
| `I_fc`, `I_batt` | f32x2 | FC/BT channel currents |
| `gFC`, `gBT` | f32x2 | `droop_gain_FC_actual` / `droop_gain_BT_actual` |
| `V_bus` | f32 | bus voltage |
| `I_cmd` | f32 | `current` (post-clamp commanded motor current) |
| `fault_flags` | u16 | live fault bitmask |
| `ps_phase` | u8 | `powerShareProfilePhaseIdx`, 0xFF when the PS profile isn't running |
| `dc_phase` | u8 | `driveCyclePhaseIdx`, 0xFF when the drive cycle isn't running |
| `trap_phase` | u8 | `trapPhase`, 0xFF when the trapezoid isn't running |
| `flags` | u8 | bit0 = a profile / live share loop is driving the droop MDACs this tick (gFC/gBT are closed-loop output, not a static operator write); bit1 = velocity chain valid (encoder fitted + `velocityChainCalibrated()`); rest reserved |
| pad | u8x2 | zero |

`v_sp`/`v_act` are logged unconditionally (the globals always exist), but `flags` bit1 tells the
decoder whether they mean anything — bench runs without the flywheel encoder (or with the chain
uncalibrated) log the fields as-is with bit1 clear, and the host decoder blanks those columns
rather than erroring. No code path requires the encoder for logging to work.

The three phase bytes are independent per-profile fields (not one "active profile" byte), and
the header's profile-type field is a bitmask (1=PS, 2=TP, 4=DC), so a future combined DC+PS
profile needs zero format change — both phase bytes are simply non-0xFF at once.

**Header (32 bytes, once per file):** magic `'B','L','G','1'`, format version (u8, =1), record
size (u8, =52), profile type (u8 bitmask), pad, `start_millis` (u32), `start_micros` (u32),
`K_DROOP`x1000 (u16), reserved to 32 B.

**Trailer (one record with `t_us = 0xFFFFFFFF` sentinel):** total records written (u32), dropped
count (u32), close reason (u8: 1=complete, 2=stop, 3=X, 4=Q, 5=fault, 6=io_error), `error_code`
(u8), rest zero. A trailer instead of a header rewrite avoids a seek-back, keeping close cheap.
The write-error path below is what sets reason 6.

**Ring buffer and draining.** A static 1024-record (52 KB) ring covers roughly 1 s of coverage
against a 250 ms pathological card stall with 4x margin. Overflow policy is drop-newest +
count (`logDroppedCount`), never block. `logDrainTick()` runs from `loop()` (not from
`doState98()`, so it keeps draining and can finish a deferred close in State 99 after a fault):
if the SD card reports busy, skip the tick (the SD analogue of `plotTick()`'s
`availableForWrite()` guard); otherwise write at most one chunk (<= 512 B) from the ring per
loop tick — comfortably ahead of the 52 B/ms fill rate, so a stall drains down fast once it
clears. A pending close writes the trailer, truncates the pre-allocated file to its actual
size, and closes once the ring is empty or a 2 s drain deadline passes, whichever comes first;
either way the trailer/truncate/close runs only once State 99 is fully latched (or in Idle),
never between teardown phases. The close is synchronous — `truncate()` walks the 32 MB
pre-allocation, order tens of ms on FAT32 — so it is deliberately confined to states where every
switch is already parked. `TODO(measure)`: `truncate()`/`close()`/`preAllocate()` durations on
the card in use.

**No-card tolerance.** `setup()` probes the card once at boot (with the power stage dark, so
SdFat's multi-second init timeout can never stall the main loop with the converters live);
`logOpenForProfile()` keeps a lazy fallback probe for callers that never ran `setup()`. The
`[SD] no card — logging disabled` warn prints once at the first profile start, not at the probe
(USB Serial may not be enumerated during `setup()`). Profiles run identically with or without a
card. An open failure warns **per run** (it is a per-run condition — a full card, a bad name —
not a latched one). A mid-run write error ends logging for that run after attempting the
trailer, prints one warn line, and the profile continues — SD errors never call
`triggerFault()`; logging is observability-only. The write-error path sets `LOG_CLOSE_IO_ERROR`
(6) as the close reason before calling `logFinishFile(false)`, so the trailer records that the
close was I/O-abandoned rather than a normal exit — previously this landed as an undocumented
reason 0 (`unknown(0)` at decode time).

**File naming.** Profile-prefixed run counter via a directory scan: `PSnnnn.BLG` / `TPnnnn.BLG`
/ `DCnnnn.BLG` / `YPnnnn.BLG` (the combined `PS|DC` profile, §9h) / `WPnnnn.BLG` (the combined
`PS|TP` profile, §9i) in the card root. At open, one scan finds the max `nnnn` across all five
prefixes and uses max+1 — stateless (no counter file to corrupt) and collision-free. The scan
happens once at profile start, not in the control path. A failed or partial directory scan
(root-open failure, or a read error partway through `openNext()`) is a hard refusal to log for
that run rather than a fallback to index 0 — a partial scan must never risk colliding with and
`O_TRUNC`-ing an existing file. Creation itself uses `O_WRITE | O_CREAT | O_EXCL` (not
`O_TRUNC`): it fails closed if the chosen name somehow already exists instead of overwriting it,
and creation never truncates.

**Retrieval and decoding.** Primary retrieval is a card pull (no serial-dump command — that
would add a long-running Serial loop to State 98, the exact failure class the non-blocking
discipline guards against). Decode on the laptop with:

```
python tools/decode_benchlog.py FILE.BLG > run.csv
```

The decoder has its own stdlib-only self-test, `tools/test_decode_benchlog.py` (§10c) — run with
`python tools/test_decode_benchlog.py`, no g++/pytest required.

MTP (mounting the card over USB without pulling it) is a possible future extension, noted here
but not implemented — it requires a USB-type rebuild and MTP_Teensy is semi-experimental.

`TODO(measure)`, bench: (1) real-card open-path latency — `preAllocate(32 MB)` runs at the `'R'`
keypress with a live manual motor command still in effect; if this exceeds ~100 ms on the card
in use, preflight the directory scan + preallocation at State-98 entry instead (adjacent finding
FW-R1-N1, docs/reviews/firmware/run-001-2026-08-10.md). (2) brownout dirent persistence — the
firmware never calls `sync()`, so it is open whether a mid-run power loss leaves the 32 MB
pre-allocated dirent behind or a 0-byte/absent file; one Y-run pull-the-plug datapoint settles
it (log the result via bench-incident).

**`'K'` status + manual logging command (fw v9).** `'K'` is a single-line command like `T`/`Y`/`W`
(`PEND_K_PARAMS`): an empty line prints the status snapshot (card present, current/last file name,
record and drop counts, and — while a log runs — a manual/profile ownership marker); `K 1` opens a
MANUAL log (`LOG_TYPE_MANUAL` = 0x08, prefix `ML`, shared session counter, v4 header param flags 0)
so the operator can drive the car by hand (`A`/`V`, switch toggles) with the 1 kHz log running;
`K 0` requests close of a manual log (`LOG_CLOSE_STOP`; refused when the log is profile-owned).
`K 1` is refused during the staged bring-up (the open path's directory scan + 32 MB preAllocate
must not stall it — enforced at parse time so the status read stays live during the lockout),
while any profile, `T` sweep, or plot-arm is pending (a profile owns the logger; the sweep term
prevents an ML open in a sweep's between-runs window from silently costing the next run its log),
and while a log is already open or closing. `X`/`Q`/fault close a manual log through the normal
drain (`LOG_CLOSE_X`/`_Q`/`_FAULT`); a profile started over a live manual log force-finishes it
via `logOpenForProfile()`'s double-open branch. The status deliberately reports NO free-space
figure: `freeClusterCount()` and friends walk the FAT and block for seconds on a real card, which
is exactly the stall this module exists to avoid.

### 9h. Combined drive-cycle + power-share profile (`Y`)

**Why.** The `D` drive cycle sweeps velocity with the share setpoint static; the `R` profile
sweeps the share with the motor held at a constant command. Neither exercises the
**cross-coupling** — on the vehicle the velocity loop's changing bus draw and the share loop's
changing droop split move at the same time, and the plant the Youla-H controller was synthesised
against (`controller_design/system_model.md`) assumes that interaction is benign. `Y` drives both
setpoints from one table so the coupling appears in a single 1 kHz log.

**Region table (40 s, 16 regions).** Velocity waypoints are **normalised** `[0..1]` and multiplied
by the operator's `Vmax` at runtime (one table serves any bench speed — the vehicle `Vmax` is
still uncalibrated). Share waypoints are **absolute**. Steps happen at region **entry** (a region
whose start value differs from the previous region's end value *is* the step); ramps interpolate
linearly across the region; holds have start == end. The region count is derived from the array,
never a separate constant.

| # | ms | v_start | v_end | s_start | s_end | Purpose |
|---|----|---------|-------|---------|-------|---------|
| 0 | 2000 | 0.0 | 0.0 | 0.50 | 0.50 | settle |
| 1 | 4000 | 0.0 | 0.6 | 0.50 | 0.50 | v ramp up (solo) |
| 2 | 2000 | 0.6 | 0.6 | 0.50 | 0.50 | buffer |
| 3 | 3000 | 0.6 | 0.6 | 0.65 | 0.65 | s step up (solo, intermediate) |
| 4 | 4000 | 0.6 | 1.0 | 0.65 | 0.35 | **BOTH ramp** (v up, s down) — interaction test |
| 5 | 2000 | 1.0 | 1.0 | 0.35 | 0.35 | buffer |
| 6 | 1500 | 1.0 | 1.0 | 1.00 | 1.00 | s step to the hi bound (brief) |
| 7 | 3500 | 1.0 | 1.0 | 0.35 | 0.35 | s step down (solo); long hold doubles as buffer |
| 8 | 3000 | 0.5 | 0.5 | 0.65 | 0.65 | **BOTH step** (v down, s up) — interaction test |
| 9 | 2000 | 0.5 | 0.5 | 0.65 | 0.65 | buffer |
| 10 | 3000 | 0.5 | 0.5 | 0.65 | 0.00 | s ramp down to the lo bound (solo) |
| 11 | 1500 | 0.5 | 0.5 | 0.00 | 0.00 | lo-bound check (brief) |
| 12 | 1500 | 0.5 | 0.5 | 0.50 | 0.50 | s step up, recovery to mid |
| 13 | 2000 | 0.2 | 0.2 | 0.50 | 0.50 | v step down (solo) |
| 14 | 3000 | 0.2 | 0.0 | 0.50 | 0.50 | v coast-down ramp |
| 15 | 2000 | 0.0 | 0.0 | 0.50 | 0.50 | end hold → natural completion |

Each axis gets **solo** excursions (so a per-axis step response can still be fitted from the same
run) plus **two deliberately simultaneous** regions (R4 ramp+ramp, R8 step+step) which are the
actual interaction test. R6 and R11 are brief excursions to the share bounds (all-FC / all-BT) to
check the **channel-cutoff behaviour** at the extremes (they were a droop *clamp* check before the
2026-08-10 full-span actuation change — see the cutoff-interaction paragraph below).

**Per-tick math.** `advanceCombinedProfile()` computes elapsed-in-region, interpolates both
dimensions, then applies:

```cpp
v_setpoint           = v_norm * yProfileVmax;
power_share_setpoint = constrain(s_abs, yProfileBoundLo, 1.0f - yProfileBoundLo);
```

**The clip is applied AFTER interpolation, deliberately.** A ramp that crosses the bound runs at
its normal slope and then **flattens** there — that kink is intended behaviour. Pre-scaling the
waypoints into the band would instead shrink every slope in the table and quietly alter the
excitation the identification is fitted to.

**Parameters** (`[Vmax] [b]`, both optional, one line, e.g. `Y 1 0.3`):
- `Vmax` (m/s, default **1.0**) — must be `> 0` and `<= MANUAL_MOTOR_V_MAX` (5.0 m/s). This is
  the **same** ceiling `setManualMotorVelocity()` (`'V'`) enforces, reused rather than reinvented:
  `Y` closes the identical velocity loop, so a second, looser bound here would let `Y` drive a
  setpoint `V` refuses.
- `b` (share bound, default **0.0** = no clipping) — must satisfy `0 <= b < 0.5`. At `b = 0.5` the
  band `[b, 1-b]` collapses to a point and the whole share axis flattens, so it is refused.
  `b > 0.35` is **accepted with a warning**: above that the clip starts compressing the table's
  intermediate 0.35/0.65 plateaus, not just the 0/1 bound checks, so the run no longer matches the
  table above.

A bare `Y` + newline runs the defaults — the only prompt in State 98 whose parameters are all
optional, so `handlePendingInputChar()` dispatches `PEND_Y_PARAMS` **before** its shared
empty-line cancel. Any validation failure rejects the whole line (no partial parameter set), and a
third value is refused rather than ignored.

**Prerequisites (identical to `D`, checked at the keypress).** Refused if a staged bring-up is
running, if `velocityChainCalibrated()` is false (`printVelocityChainRefusal()`), or if
`MOT_PWR_ENABLE` is LOW. They are deliberately not re-checked at parse time: while the prompt is
pending only digits/sign/point/space reach the buffer and every other key cancels the entry, so no
command can toggle `MOT_PWR_ENABLE` or arm a bring-up in that window.

**Control stack.** The `combinedProfileActive` branch in `doState98()` runs
`advanceCombinedProfile()` first, then — re-checking the flag, exactly as the drive-cycle branch
does — `motorControlGated()` and `powerBalanceGated()` in that order. The re-check exists for the
drive cycle's reason: the completion path zeroes the motor, and letting `motorControl()` run in
the same tick would undo the flush with a negative error (`0 − v_actual`) while the flywheel spins
down, i.e. a "completed" profile commanding regen current.

**`chargingControl()` deliberately does NOT run** — the same omission as the `R` profile, and here
it is load-bearing rather than merely tidy. `Y` sweeps `power_share_setpoint` in order to
**measure** the share axis; with `charge_goal > 0` the cruise branch of `chargingControl()` calls
`assertFcChargeEnable(true)`, whose guard drives `BT_BUS_ENABLE` LOW. That takes the battery off
the bus mid-run: `I_batt → 0`, the measured share pins at 1.0, and every share datapoint after
that instant is garbage. The regen produced by the coast-down regions (R14/R15) is absorbed by the
hardware TL431/BSP170P braking chopper, which is not under firmware control — exactly as in the
`R` and `T` profiles. So the charge/regen paths stay static under operator control for the whole
run, and share experiments have `charge_goal = 0` semantics guaranteed regardless of what the Pi
last commanded.

**Exits.** Stop-toggle (`Y` again): motor zeroed (`haltMotorOutput()`), `safeAllSwitches()`,
`power_share_setpoint = 0.5`, `logRequestClose(LOG_CLOSE_STOP)` — it sweeps the charge/regen paths
like `D`/`R`, so a mid-region stop must leave nothing latched. Natural completion (R15 elapsed):
motor zeroed, share back to 0.5, `LOG_CLOSE_COMPLETE`, switches left as-is (mirroring the `D`/`R`
*natural* completions — only their stop-toggle/`X` paths park switches). `X` treats it exactly like
`D`/`R` (parks switches, resets the share setpoint); `Q` clears the flag with the other three.
Mutual exclusion runs both ways: starting `Y` clears `driveCycleActive`/`powerShareProfileActive`/
`trapProfileActive`/`trapCmdA`, and the `D`/`R`/`T` start paths clear `combinedProfileActive` (an
orphaned flag would otherwise resume with a huge elapsed time when the other profile stopped).
`G` refuses while it runs, and `pollVescWatch()` is suppressed during it.

**Plot mode.** `Y`, like `D`, is **not** arm-delayed — it starts immediately even under plot mode,
despite being the one profile besides `R` that moves the plotted `sp` series. Arming it would mean
a parameter line typed at the prompt fires seconds later with the velocity loop live, and unlike
`R`/`T` its preconditions are checked at the keypress precisely because nothing that reaches the
input buffer can invalidate them — an arming window would reopen that hole. The interaction runs
the other way instead: an armed `R`/`T` is refused over a running `Y` and cancelled by a `Y` that
starts during the countdown.

**A stopped (not completed) run parks all switches** — the bus is dark afterwards and a fresh `G` bring-up is required before the next run. (A natural completion leaves the switches as they are.)

**On a fault mid-run**, `power_share_setpoint` and `combinedProfileActive` are left stale by
design. State 99 is latched and nothing consumes either value there; `doState99()` zeroes the
motor and takes the boosts down on its own schedule, and the latch is only cleared by a power
cycle, which reinitialises both. Adding cleanup to the fault path would put work in front of the
safety transition for no observable benefit.

**Logging.** Opens `logOpenForProfile(LOG_TYPE_PS | LOG_TYPE_DC)` **after** the flags/region index
are set, so the first sample already carries region 0. That combined mask gives the file the new
`YPnnnn.BLG` prefix (the `PS|DC` test comes first in `logNextFileName()`, and `YP` joins the
prefix scan set so the run counter stays monotonic across all four types). `logSampleTick()` writes
the region index into **both** `ps_phase` and `dc_phase` — the "both bytes non-0xFF at once" case
the three independent phase bytes and the header bitmask were designed for. `trap_phase` stays
`0xFF`. **No record-format or decoder change.**


**Interaction with the full-span channel cutoff (2026-08-11).** Since the 2026-08-10 full-span
actuation change, a commanded share ratio outside `[DROOP_R_MIN, DROOP_R_MAX]` no longer clips —
`applyShareRatio()` takes the starved channel **off the bus** by opening its RT1987 bus switch.
This profile drives the share to 1.0 (R6) and 0.0 (R11) by design, so **with a bound below
`DROOP_R_MIN` the run performs two bus-switch openings under load** — the TP0010 stressor class.
Both starts therefore print an explicit warning naming the motor ceiling the switch will open
against and a safe low-current first command; run it scope-armed the first time.

Two consequences for reading the data:
- **While a channel is isolated the share loop is OPEN** — `applyShareRatio()` returns before any
  MDAC write, and the still-active channel holds its previous droop gain. R6/R11 samples are
  **topology events, not droop-response data**; do not fit a plant through them.
- **A latched cutoff cannot outlive the run.** Natural completion calls
  `restoreShareCutoffOnCompletion()`, which re-closes a still-owned channel through
  `applyShareRatio()`'s own re-entry path (so its charged-bus guard and ownership rules apply
  unchanged) and clears the flags. Without it the board would sit single-sourced indefinitely: with
  no profile running, `powerBalance()` never executes, so nothing would ever call the controller
  again. If the bus is not in regulation the restore correctly declines and says so. The stop /
  `X` / `Q` paths need nothing — `safeAllSwitches()` already clears the ownership flags.

Status snapshot every 500 ms (suppressed under plot mode):
`[YP] t=… R<idx> v_sp=… sp=… act=… I_fc=… I_bt=… V_bus=… FLT=…`

### 9i. Combined CURRENT + power-share profile (`W`)

**Why.** `Y` (§9h) needs `velocityChainCalibrated()`, which was 0 when `W` was written —
`ENCODER_SLOTS_PER_REV` and `FLYWHEEL_RADIUS_M` were unmeasured, so `Y` refused outright.
*(Both are measured now and the flag defaults 1 from fw v7; the slot count was corrected again in
fw v8. `W` keeps its value for the reason below: it needs no velocity chain at all.)* `W` is the
same experiment with the motor axis moved from velocity to **commanded current**, which is exactly
the substitution the `T` trapezoid already makes: direct phase current, velocity PI never in the
loop, no calibration needed. It is therefore the combined-axis run that can actually be performed
today, and it stays useful afterwards as the current-mode counterpart of `Y`.

**Same table, one shared walk.** `W` reuses `COMBINED_PROFILE[]` **verbatim** — not a copy. The
two runs are only comparable if their shapes are identical by construction, and a duplicated table
is a shape that drifts. The `v_start`/`v_end` column is reinterpreted as a **normalised current**
scaled by the operator's `Imax`; the share column and its post-interpolation clip are unchanged.
Both `advanceCombinedProfile()` and `advanceCurrentComboProfile()` walk the table through one
shared `advanceComboRegion()` helper (region advance + both interpolations + the clip), which
returns `COMBO_TICK_DONE` / `COMBO_TICK_BOUNDARY` / `COMBO_TICK_RUN`; each caller supplies its own
scaling, command path, completion text, and status line. The parameter grammar is shared too
(`parseTwoOptionalFloats()`), as are the share-bound rules (`validateShareBound()`).

At the default `Imax` = 5.0 A the table's motor plateaus are **0 / 3.0 / 5.0 / 2.5 / 1.0 A**
(normalised 0 / 0.6 / 1.0 / 0.5 / 0.2), with the same ramps, buffers and simultaneous regions as
§9h's table.

**Parameters** (`[Imax] [b]`, both optional, one line, e.g. `W 6 0.0`):
- `Imax` (A, default **5.0**) — must be `> 0` and `<= TRAP_I_ABS_MAX` (25 A). The ceiling is the
  **trapezoid's**, reused with its rationale intact: `setCurrent()` commands PHASE current, which
  does not map 1:1 onto bus draw, so peaks above `MOTOR_I_CMD_MAX` (5 A) are accepted here exactly
  as `T` accepts them. Negative peaks are refused (unlike `T`): the table's motor column is a
  normalised magnitude with its own coast-down, so a negative peak would merely mirror the whole
  profile into braking — use `T` for a braking/regen ramp.
- `b` — identical rules to `Y` (`0 <= b < 0.5`, warn above 0.35), enforced by the same
  `validateShareBound()`.

**Prerequisites — `T` conventions, not `Y` conventions.** Refused only if a staged bring-up is
running. There is **no** `velocityChainCalibrated()` gate (the profile bypasses the velocity PI
entirely, which is precisely what makes it safe uncalibrated) and `MOT_PWR_ENABLE` LOW is a
**warning, not a refusal** (the VESC may be fed from a separate bench supply; if `MOT_PWR` really
is its only source, an unpowered VESC simply ignores the commands).

**Control stack.** The `wProfileActive` branch mirrors the **trapezoid's** call set:
`advanceCurrentComboProfile()` (which sets `power_share_setpoint` and issues the current itself via
`commandMotorCurrentLimited(cmd, TRAP_I_ABS_MAX)`, rate-gated on `rl_motor_last`) followed by
`powerBalanceGated()`. No `motorControlGated()` — there is no velocity loop — and `v_setpoint` is
never written, so no stale setpoint is left behind for whatever runs next (same as `T`).
`chargingControl()` is omitted for the same load-bearing reason as `Y` and `R`: with
`charge_goal > 0` its cruise branch calls `assertFcChargeEnable(true)`, which drives
`BT_BUS_ENABLE` LOW, takes the battery off the bus, and pins the measured share at 1.0 —
destroying the run's only measurement. Coast-down regen is absorbed by the hardware TL431/BSP170P
chopper as always.

**Exits.** Stop-toggle (`W` again): motor zeroed, `power_share_setpoint = 0.5`,
`logRequestClose(LOG_CLOSE_STOP)`, and **`safeAllSwitches()`**. That last one follows the
`Y`/`R` share-profile convention rather than `T`'s leave-them-alone rule even though the motor axis
is current-mode — the deciding factor is the *other* axis: this profile sweeps the share across the
full band, so the bus/source configuration is something the run manipulates, not a static operator
input worth preserving. Natural completion zeroes the motor and the share and leaves switches
as-is (matching every other profile's natural completion). `X` treats it exactly like `D`/`R`/`Y`;
`Q` clears the flag. Mutual exclusion runs both ways against `D`/`R`/`T`/`Y`; `G` refuses while it
runs; `pollVescWatch()` is suppressed during it; a plot-mode arm neither fires into it nor survives
it. `W` is not itself arm-delayed (same reasoning as `Y` — see §9h's plot-mode paragraph).

**A stopped (not completed) run parks all switches** — the bus is dark afterwards and a fresh `G` bring-up is required before the next run. (A natural completion leaves the switches as they are.)

**Interaction with the full-span channel cutoff (2026-08-11).** Since the 2026-08-10 full-span
actuation change, a commanded share ratio outside `[DROOP_R_MIN, DROOP_R_MAX]` no longer clips —
`applyShareRatio()` takes the starved channel **off the bus** by opening its RT1987 bus switch.
This profile drives the share to 1.0 (R6) and 0.0 (R11) by design, so **with a bound below
`DROOP_R_MIN` the run performs two bus-switch openings under load** — the TP0010 stressor class.
Both starts therefore print an explicit warning naming the motor ceiling the switch will open
against and a safe low-current first command; run it scope-armed the first time.

Two consequences for reading the data:
- **While a channel is isolated the share loop is OPEN** — `applyShareRatio()` returns before any
  MDAC write, and the still-active channel holds its previous droop gain. R6/R11 samples are
  **topology events, not droop-response data**; do not fit a plant through them.
- **A latched cutoff cannot outlive the run.** Natural completion calls
  `restoreShareCutoffOnCompletion()`, which re-closes a still-owned channel through
  `applyShareRatio()`'s own re-entry path (so its charged-bus guard and ownership rules apply
  unchanged) and clears the flags. Without it the board would sit single-sourced indefinitely: with
  no profile running, `powerBalance()` never executes, so nothing would ever call the controller
  again. If the bus is not in regulation the restore correctly declines and says so. The stop /
  `X` / `Q` paths need nothing — `safeAllSwitches()` already clears the ownership flags.

**Key rebinding.** `W` was the VESC-watch toggle; the watch moved to **`U`** ("UART watch"). The
`W` keypress starts nothing on its own — it opens a parameter prompt — so an operator with muscle
memory lands on a cancellable prompt, never on a running motor.

**Logging.** `logOpenForProfile(LOG_TYPE_PS | LOG_TYPE_TP)` → the new **`WPnnnn.BLG`** prefix (the
mask-equality tests for `PS|DC` and `PS|TP` both run before the single-bit tests, and `WP` joins
the scan prefix set). `logSampleTick()` writes the region index into **`ps_phase` and
`trap_phase`**, leaving `dc_phase` at `0xFF` — the mirror image of `Y`'s `ps_phase`+`dc_phase`.
No record-format or decoder change; the decoder is format-agnostic about prefixes.

Status snapshot every 500 ms (suppressed under plot mode):
`[WP] t=… R<idx> I_cmd=… sp=… act=… I_fc=… I_bt=… V_bus=… FLT=…`

### 9d. `doState98()` skeleton

```cpp
void doState98() {
    // Suspend Pi watchdog timer while in this state
    lastPiMsg = millis();   // reset watchdog so 99-transition never fires

    // Process one character from USB Serial if available
    if (Serial.available()) {
        char cmd = Serial.read();
        switch (cmd) {
            case 'F': /* toggle FC_REG_ENABLE */ break;
            case 'B': /* toggle BT_REG_ENABLE */ break;
            case '1': /* toggle FC_BUS_ENABLE */ break;
            case '2': /* toggle BT_BUS_ENABLE */ break;
            case '3': /* toggle MOT_PWR_ENABLE */ break;
            case '4': /* toggle REGEN_ENABLE (check assertFcChargeEnable needed?) */ break;
            case '5': assertFcChargeEnable(!digitalRead(FC_CHARGE_ENABLE)); break;
            case '6': /* toggle BT_SEQUENCE_ENABLE */ break;
            case 'C': /* toggle CBAL_DISABLE */ break;
            case 'M': /* toggle MPPT_DISABLE */ break;
            case 'D': /* start/stop drive cycle */ break;
            case 'S': printTestStatus(); break;
            case 'Q': state = 1; return;
        }
    }

    // Run drive cycle step if active
    if (driveCycleActive) advanceDriveCycle();

    // Watchdog reset must be last so it covers the full function body
    lastPiMsg = millis();
}
```

`printTestStatus()` dumps a human-readable snapshot of all pin states and sensor readings
over USB Serial. It does **not** modify any hardware state.

---

## Step 10 — Unit tests

**Files touched:** new `test/` directory; `teensy_controller.ino` is *not* modified.

### 10a. Directory layout

```
test/
  mock_arduino.h      — analogRead(), digitalWrite(), digitalRead(), millis(), micros(),
                        pinMode(), delay(), delayMicroseconds()
  mock_wire.h         — Wire.beginTransmission(), write(), endTransmission(), requestFrom(),
                        read(); injectable byte queue for scripted I2C responses
  mock_spi.h          — SPI.begin(), transfer16(); captures written words for assertion
  mock_vesc.h         — VescUart stub; controls setCurrent() call log, v_actual, current
  mock_sd.h           — in-memory SdFat/SD mock: per-file byte capture, injectable
                        open/write failures, busy-tick stall injection (drives the
                        SD-logging overflow/no-card/write-error tests)
  test_main.cpp       — test runner (no framework dependency; plain assert() + pass/fail counter)
  Makefile            — native build: g++ -std=c++17 -I.. test_main.cpp -o run_tests && ./run_tests
```

The `test/` Makefile includes `..` on the include path so `test_main.cpp` can
`#include "../teensy_controller.ino"` after defining the mock headers that satisfy its
dependencies. Mark any Teensy-specific headers (`<Wire.h>`, `<SPI.h>`, etc.) as provided
by the mocks before the `#include`.

### 10b. Test categories

| Category | Tests |
|----------|-------|
| **Scale factor math** | `SCALE_V_FC`, `SCALE_V_BATT`, `SCALE_V_BUS`, `SCALE_V_CHG`, `SCALE_V_RGN`, `SCALE_I` produce correct Volts/Amps from known ADC counts |
| **Fault detection** | OC/UV/OV thresholds trigger correct `fault_flags` bits; switch-conflict fault fires when `FC_CHARGE_ENABLE` is HIGH with `BT_BUS_ENABLE` or `REGEN_ENABLE` HIGH |
| **PI controllers** | `PI_Controller_Motor()` and `PI_Controller_Power()` converge given step inputs; anti-windup clamps hold on BOTH PIs (§14); live output on sub-sampleTime ticks — no 0.0f sentinel (§14) |
| **Packet parsing** | `parseCommand()` correctly populates `v_setpoint`, `power_share_target`, `charge_goal`, `droop_enable_reserved` from a known 22-byte buffer |
| **Telemetry packing** | `sendTelemetry()` (captured via mock UDP) produces 58-byte packet; SYNC=0xAA at byte 0; XOR over bytes 1–56 matches byte 57; `charger_status` (raw Ag105 byte) at offset 51, `V_chg`, `V_rgn`, `switch_state`, `fault_flags` (u16), `error_code`, `error_source_state` appear at correct offsets |
| **Ag105 constants** | `AG105_ADDR == 0x30`, `AG105_VAL_2S == 0x08`, `AG105_VAL_2500MA == 0x01` |
| **`initAg105Charger()`** | Injected I2C captures show correct write sequence: reg 0x00 ← 0x01, reg 0x01 ← 0x08 |
| **`pollAg105()`** | Injected 2-byte I2C response (status + current byte) populates `ag105_status_raw` and `I_charge` correctly |
| **`assertFcChargeEnable(true)`** | `BT_BUS_ENABLE` and `REGEN_ENABLE` go LOW before `FC_CHARGE_ENABLE` goes HIGH |
| **`assertFcChargeEnable(false)`** | Only `FC_CHARGE_ENABLE` goes LOW; does not disturb `BT_BUS_ENABLE` or `REGEN_ENABLE` |
| **Drive cycle simulation** | `advanceDriveCycle()` transitions through all phases in the correct order given controlled `millis()` injection; `v_setpoint` hits expected values at each phase boundary |
| **MPPT_DISABLE polarity** | `chargingControl()` sets `MPPT_DISABLE` LOW (inhibit) during regen and when `charge_goal ≈ 0`; HIGH (enabled) when charger is ready and no regen |
| **Y combined profile** | parameter parsing + defaults (bare line, one value, two values), refusals (`Vmax` <= 0 / above `MANUAL_MOTOR_V_MAX`, `b` < 0 / >= 0.5, third value) and the `b > 0.35` warn-and-accept, region walk across all 16 regions, clip behaviour at both bounds incl. the post-interpolation kink, `Vmax` scaling of the normalised waypoints, stop-toggle / `'X'` / `'Q'` exits and mutual exclusion with `D`/`R`/`T`, `YP` file naming + the region index in both phase bytes, status line + plot-mode suppression |
| **W current combo profile** | shared-helper equivalence with `Y` (same region walk/clip), `Imax` scaling of the normalised motor column, parameter parsing + defaults and the `TRAP_I_ABS_MAX` ceiling (peaks above `MOTOR_I_CMD_MAX` accepted, negative refused), current issued through `commandMotorCurrentLimited()` with `v_setpoint` untouched, no velocity-chain gate + `MOT_PWR` warn-only, stop/`'X'`/`'Q'` exits and mutual exclusion with `D`/`R`/`T`/`Y`, `WP` naming + region index in `ps_phase`+`trap_phase`, and the `'W'`→`'U'` watch rebinding; a fault mid-run closing the `WP` file from State 99 |
| **Combined x channel cutoff** | one switch opens at an R6-like ratio, the last-source guard blocks the second, hysteresis re-arms on return, a latched cutoff is re-closed by BOTH natural-completion paths (and declines on an unregulated bus), and the stop path clears the ownership flags via `safeAllSwitches()` |
| **Combined boundary tick** | a `COMBO_TICK_BOUNDARY` tick commands nothing — no `setCurrent()` for `W`, no `v_setpoint` rewrite for `Y` (zero-order hold across every region transition) |
| **SD bench logging** | lifecycle on all exit paths (complete/stop/X/Q/fault), 1 kHz rate gate, overflow drop+count, no-card warn-once, write-error mid-run, name collision, record schema, velocity-valid flag + per-profile phase bytes, `'K'` status, plot+log independence, `K 1`/`K 0` manual logging (ML naming + shared counter, header typeMask/param flags, sampling content, every refusal incl. tsweep + drain window, X/Q/fault/takeover lifecycle, no-card, ownership marker) |

`tools/test_decode_benchlog.py` is a separate, stdlib-only self-test for the host-side decoder
(`tools/decode_benchlog.py`) — not part of the C++ suite above, since the decoder is a Python
tool with no Teensy/mock dependency. It covers the wrap-safe modular step check on a synthetic
run whose `t_us` straddles the uint32 wrap, brownout truncation at the true end of data,
`close_reason` 6 (`io_error`), and the gap-statistics output (`max_interval_us`,
`missed_periods`). Run with `python tools/test_decode_benchlog.py`.

### 10c. Running the tests

```bash
cd test
make          # compiles and runs; prints PASS/FAIL per test + summary
```

No Teensy hardware or Arduino IDE needed. Tests should be run locally before each flash.

---

## Execution order

| # | Task | Section | Risk / note |
|---|------|---------|-------------|
| 1 | Rename `CHARGER_ENABLE` → `MPPT_DISABLE` globally | §1a | High — many call sites |
| 2 | Rename `CHARGER_OK` → `CHARGER_STAT` globally | §1a | Medium |
| 3 | Rename `CHRG_CURRENT` → `RGN_VOLTAGE`, change SCALE | §1a, §5 | Medium |
| 4 | Add 9 new `#define` pins | §1b | Low |
| 5 | Add 12-bit `analogReadResolution` + `ADC_MAX = 4095` | §5a-b | Medium |
| 6 | Recompute `SCALE_V_*` from BOM | §5c | Low |
| 7 | Update `updateSensors()`: drop I_charge, add V_chg/V_rgn | §5e | Medium |
| 8 | Update `setup()`: new pin modes + safe defaults | §1c | High — safety-critical defaults |
| 9 | Add `assertFcChargeEnable()` helper | §2b | New code |
| 9a | Scope `checkPiWatchdog()` to States 2 and 3 | §2d | Low — one-line guard |
| 10 | Update all 5 state functions for power-path sequencing | §2c-h | High — safety-critical |
| 11 | Delete BQ25690 artifacts (`CHARGER_ADDR`, `REG_ICHG`, etc.) | §3a | Medium |
| 12 | Add `initAg105Charger()` (real register values; one TODO stub for AG105_VAL_2S) | §3c | Medium |
| 12a | Add `pollAg105()` + `ag105IsReady()` helpers; wire into `loop()` | §3e | Medium |
| 13 | Rewrite `chargingControl()` for Ag105 + MPPT_DISABLE | §3d | High |
| 14 | Verify CBAL_DISABLE setup (already done in §1c) | §4 | Low |
| 15 | Update `detectFaults()` + limits | §6a | Medium |
| 16 | Rewrite `sendTelemetry()` for v3 layout | §6b | High — breaks Pi unless updated together |
| 17 | Update command parser comment for `droop_enable` | §6c | Low |
| 18 | Verify MDAC (no changes expected) | §7 | Low |
| 19 | Add changelog header comment | §8 | Low |
| 20 | Add `doState98()`, drive cycle, `printTestStatus()` | §9 | Medium |
| 21 | Add State 98 transition from State 1 serial parse | §9a | Low |
| 22 | Write mock headers and `test_main.cpp`; wire Makefile | §10 | Medium |

---

## Open items

### Resolved by JSON files

| Item | Resolution | Source |
|------|-----------|--------|
| Ag105 I2C address | `0x30` (reg 0xE5 default) | `Ag105_Table7_I2C_Parameters.json` |
| Charge current register | `0x00`; value `0x01` = 2.5 A | `Ag105_Table7_I2C_Parameters.json` |
| Battery voltage config register | `0x01`; `AG105_VAL_2S = 0x08` = 8.4 V | `Ag105_Table7_I2C_Parameters.json`, `Ag105_Table3_Charge_Voltage_Select.json` |
| Charge cutoff current | 250 mA (C/10 of 2.5 A profile) | `Ag105_Table4_Charge_Current_Select.json` |
| Power-on defaults | 0x00 → external resistor; no RCS/RVS = 1000 mA / 4.2 V (1S) | `Ag105_Table3_Charge_Voltage_Select.json`, `Ag105_Table4_Charge_Current_Select.json` |
| Charge current readable over I2C | Reg `0x06`, scale 0.011 A/count | `Ag105_Table7_I2C_Parameters.json` |
| `CHARGER_STAT` pin polarity | HIGH (steady) = Charging; LOW (steady) = No input; pulsed = error/full | `Ag105_Table5_Status_Output.json` |
| `CHARGER_STAT` readability limit | Cannot decode all states with `digitalRead()` — use I2C GENSTAT | `Ag105_Table5_Status_Output.json` |
| Ag105 status byte structure | GENSTAT bits 0–2, mode flags bits 3–7 | `Ag105_Table6_I2C_Status_Byte.json` |
| I2C read protocol quirk | Status byte always prepended before data | `Ag105_Table6_I2C_Status_Byte.json` |

### Resolved by user-confirmed schematic / hardware data

| Item | Resolution | Source |
|------|-----------|--------|
| `MPPT_DISABLE` GPIO polarity | Active-LOW: LOW inhibits the MPPT loop | User-confirmed from PCB schematic |
| MPPT mechanism (dated correction, 2026-08-31) | Input-voltage-threshold regulator (default 18 V, reg 0x02), not perturb-and-observe | `AG105_Silvertel.pdf` p.10; see `CLAUDE.md` §3 |
| `CBAL_DISABLE` polarity | LOW = balancer/OVP active, HIGH = disabled; no external pull resistor on net; internal pullup needed | User-confirmed from PCB schematic |
| CHG/RGN voltage dividers | R1=78.7kΩ, R2=10kΩ → Vmax=29.271V → SCALE=29.271/4095 | User-confirmed from PCB schematic |
| TPS61288 HW OVP threshold | 19V (built-in). `LIMIT_V_BUS_MAX = V_BUS_NOMINAL + 1.5f` = 17.5V (16.0V nominal + 1.5V SW margin) | 2026-07-11 RD1=215k FB retune; nominal bus = 16.0V (15.9V measured no-load). Original 17.5V nominal is stale |

### Still open — mark `// TODO(verify: <source>)` in code

1. **AD5443 SPI verification** — SPI_MODE0, MSBFIRST, 16-bit word width, 12-bit resolution.
   Datasheet file now available: `references/Datasheets/ad5426_5432_5443.pdf`.
   `// TODO(verify: ad5426_5432_5443.pdf §SPI interface and §resolution)`

---

## What NOT to change

- `PI_Controller_Motor()`, `PI_Controller_Power()`, `motorControl()`, `powerBalance()` control
  math. The drive cycle (§9c) only sets `v_setpoint`. (Two surgical, behaviour-preserving
  exceptions were made during the review round — see §11: the integrator state was hoisted to
  file scope so tests can reset it, and a clamp-based anti-windup bound was added to the motor PI.
  The audit round, §14, added two more user-approved exceptions: the power-share PI gained the
  same anti-windup clamp, and both PIs now always return a live output — the `sampleTime` gate
  applies to the integrator update only, since the old 0.0f sentinel chopped the motor command
  and slammed the droop split on sub-sampleTime ticks.)
- `doEncoderA()`, `doEncoderB()`, `updateWheelSpeed()` algorithm (a guarded buffer-reset hook
  was added to `updateWheelSpeed()` in §11 — the velocity math is unchanged).
- UDP sync bytes, packet counter, XOR checksum algorithm.
- The 5-state machine *structure* (just add hardware sequencing inside each state body).
- `K_sns = 0.1f` (INA253A1 fitted; A3 would be 0.4f), `A_v`, `k_eq` — the droop math is unchanged.

---

## Step 11 — Post-reconciliation hardening (review round, 2026-06-23)

A correctness/robustness review after the initial reconciliation surfaced bugs and latent
hazards; the following changes were applied and covered by new host-native tests. All are
implemented in `teensy_controller.ino` unless noted.

### Correctness fixes

1. **`doState0()` no longer swallows charger init failure.** When `initAg105Charger()` faults
   (I2C NAK) it sets `mainState = 99`; `doState0()` now `return`s on that instead of falling
   through to its unconditional `mainState = 1`. Previously a failed charger config silently
   demoted to Idle and ran with the Ag105 at its 4.2 V / 1S power-on default.
2. **Ag105 GENSTAT decode corrected** in `detectFaults()`. Mask is now `& 0x07` (GENSTAT is
   bits [2:0]; bit 3 is the MPPT EN/DIS flag), and the error set is `0x05` (OC/Regulation),
   `0x06` (Thermal Shutdown), `0x07` (Timeout). The old code masked `0x0F` and tested
   `0x04`/`0x08` — it false-faulted on `0x04` (Bring-Up Charge, a *normal* transient) and
   missed every real error state.
3. **UV faults gated to Run.** `FAULT_UV_FC` and `FAULT_UV_BATT` now only fire in State 2,
   mirroring the existing `FAULT_UV_BUS` gate. With `V_fc`/`V_batt` reading ~0 before the
   regulators ramp, the ungated checks latched State 99 on the first loop tick of every boot.
4. **`pollAg105()` I2C fault is state-gated.** A read failure only latches State 99 in the
   charging-relevant states (2/3); in Init/Idle/Test it marks charger data stale
   (`ag105_status_raw = 0` → `ag105IsReady()` false) without locking the system. The
   `initAg105Charger()` path still validates I2C as `ERR_INIT_FAIL` in State 0.

### Robustness / safety

5. **Non-blocking State 3 and State 99 shutdowns.** The two `delay(10)` calls in each were
   replaced with `millis()`-gated phase machines (timings preserved exactly) so
   `updateSensors()`/`detectFaults()` keep running through the cap-drain and regen-bleed
   windows — the highest-energy moments of shutdown. *(State 3 was later simplified to a
   single-pass shutdown that leaves the bus energized — see §12; State 99 remains a phase machine.)*
6. **State 98 drive cycle runs the real control loop.** `doState98()` now calls
   `chargingControl()` / `motorControl()` / `powerBalance()` during an active drive cycle (it
   previously only updated `v_setpoint`, so nothing was exercised). Stopping the cycle (`D`)
   flushes a zero VESC command and calls the new `safeAllSwitches()` to park every path switch
   LOW; `Q` also forces `MOT_PWR_ENABLE` LOW.
7. **Motor PI anti-windup.** `pi_motor_accum` is clamped to the torque equivalent of
   `MOTOR_I_CMD_MAX` (`= 30.0f` A, `TODO(calibrate)`), so a stalled setpoint or saturated VESC
   can't wind the integrator up unbounded.
8. **PI integrator state hoisted to file scope** (`pi_motor_accum`, `pi_motor_lastMicros`,
   `pi_power_*`) so the unit tests can reset it deterministically between cases. Control math
   and `sampleTime` gating are unchanged.
9. **Wheel-speed buffer reset between runs.** State 3 sets `wheelSpeedResetPending`;
   `updateWheelSpeed()` consumes it to clear `posArr`/`timeArr`/`index`/`lastMicros`, so a new
   run's first velocity samples aren't computed against stale timestamps. (Runs are short, so
   the `int` timestamp storage never approaches its range.)

### Documentation reconciliation

10. **Telemetry version.** This document (§6b, §10b, changelog, exec table) was updated to the
    shipped **v3 / 57-byte** layout (was incorrectly documented as v2 / 54 bytes). *(Later bumped
    to **v4 / 58-byte**: `charger_status` reinstated at offset 51 carrying the raw Ag105 Table 6
    status byte, so the Pi recovers the old off/CC/CV/fault telemetry — and more — directly. See
    §6b for the layout and decode.)*
11. **`K_sns`** in §5d / "What NOT to change" was corrected from `0.4` to **`0.1` V/A** (the
    INA253A1 part actually fitted; `0.4` is the A3 variant that was never installed).

### Reviewed and intentionally left as-is

- A co-occurring UV bit can be absent from `fault_flags` telemetry if an earlier ungated fault
  trips State 99 first in the same `detectFaults()` pass. `error_code` (primary cause) is still
  correct; only the secondary diagnostic bit is lost. Accepted.
- Ag105 GENSTAT `0x00` (Battery Disconnect) / `0x01` (Low Power) are treated as "not ready"
  rather than faults. Confirmed intentional.
- `doState3()`'s static `phase` is not defensively reset on abnormal entry: a fault mid-shutdown
  latches State 99 and the board is only recovered by a power cycle (which re-inits the static),
  so a stale `phase` is unreachable. A comment documents this.

---

## §12 — Bench bring-up round (2026-06-23)

Bench bring-up of the assembled board. **Supersedes parts of §11** — most importantly, the
charger is no longer configured or faulted in `doState0()`.

### Root cause
The Ag105 only has input power when a charger power path is routed to it:
`chargerHasPower()` = `FC_CHARGE_ENABLE || (REGEN_ENABLE && MOT_PWR_ENABLE)`. In Init/Idle all
are LOW, so the charger is unpowered and NACKs I2C — the old State-0 `initAg105Charger()` could
never succeed on real hardware (it faulted to State 99 every boot). An unpowered charger is a
normal mode, not a fault.

### Changes
1. **Deferred + lazy charger config.** `doState0()` no longer calls `initAg105Charger()`.
   `initAg105Charger()` now returns `bool` (no internal fault). `pollAg105()` tracks the power
   edge, waits `AG105_SETTLE_MS` (`TODO(calibrate)`) for bring-up, then on the first ACK writes
   reg 0x00=0x01 / reg 0x01=0x08 and sets `ag105Configured` (re-arms on power loss; EPROM makes
   it idempotent).
2. **Power-based fault gating (supersedes §11.4 state-gating).** `pollAg105()` raises
   `FAULT_I2C_CHARGER` / `FAULT_INIT_FAIL` only when `chargerHasPower() && settled &&
   (State 2|3)`. Unpowered/settling never faults; State 98 excluded. `detectFaults()` GENSTAT
   check unchanged at the time (guarded on `ag105_status_raw != 0`; §14 later replaced that
   guard with the out-of-band `ag105DataValid` flag — GENSTAT 0x00 is a real status).
3. **`chargingControl()` FC-path deadlock fix.** Cruise opens `FC_CHARGE_ENABLE` on intent
   (`charge_goal > 0`) to power/boot the charger; only the MPPT release is gated on
   `ag105IsReady()`. Previously the path was gated on readiness, which could never be reached
   because the charger was never powered.
4. **`BENCH_TEST` made `#ifndef`-overridable; tests compile `-DBENCH_TEST=0`.** The flag relaxes
   `detectFaults()` to overvoltage-only for bench bring-up with unpowered rails (default `1` on
   hardware). Charger config/faults are no longer tied to `BENCH_TEST` (power-gating covers it).
   Also added: `USE_ETHERNET`/`networkUp` UDP guard, State-98 `I` I2C scan, State-99 1 Hz error
   print, State-1 `S` sensor stream.

### Tests
- Test harness `#include` path + Makefile `-I` fixed for the `.ino`'s move into
  `teensy_controller/`. `reset_test_state()` resets `ag105Configured/ag105HadPower/
  ag105PowerOnMs` and sets `networkUp = true`.
- Updated: `test_init_ag105_charger` (bool return), `test_i2c_fault_injection`,
  `test_dostate0_init_fault` → `test_dostate0_reaches_idle_unpowered`,
  `test_pollag105_state_gate` (Run half now powers+settles), `test_charging_control_mppt_polarity`
  sub-test D (FC_CHARGE HIGH on intent).
- New: `test_charger_has_power`, `test_pollag105_unpowered_never_faults`,
  `test_pollag105_settle_window_suppresses_fault`, `test_lazy_config_on_power`,
  `test_config_resets_on_power_loss`, `test_charging_control_fc_bootstrap`.
- **All 205 host-native tests pass** (MSYS2 UCRT64 g++; no `make` on this machine — use
  `mingw32-make` or g++ directly with `-DBENCH_TEST=0`). *(Now **219** after the §12 additions.)*

---

## 12. VBUS controlled bring-up (2026-06-24)

A State-98 bench mishap — enabling `BT_BUS_ENABLE` while both boosts were already running and
VBUS sat at 0 V — destroyed the BT TPS61288 boost and browned out the Teensy. Reconciling against
`references/Datasheets/RT1987_DS-00.pdf` + schematic sheet 4: the RT1987 has back-to-back FETs
(full isolation when disabled) and soft-start + start-up SCP, so raw inrush should have been
protected. VBUS carries a **470 µF** bulk cap; with `CSS = 5.6 nF` (tON ≈ 1.17 ms) a hot-plug
makes the RT1987 SCP-clamp and burst-retry. The real culprit was the **shared 9 V test rail**
(`VBT` feeds the BT boost *and* the LM1084 logic reg), which browned out under those bursts.
FC-first worked because FC's source is isolated and pre-charged the bus. **Never hot-plug a
running boost onto a discharged bus.**

Changes (supersede §2g and the State-3 half of §11.5):
- **`setup()`** leaves the boosts OFF; `doState0()` enables them *after* the bus switches.
- **`doState0()`** is a non-blocking phase machine: bus switches first → settle (`BUS_SETTLE_MS`)
  → boosts (their soft-start ramps the bus) → gate State 0→1 on `V_bus ≥ V_BUS_CHARGED_THRESH`,
  with `BUS_CHARGE_TIMEOUT_MS` → `FAULT_INIT_FAIL` (dead boost / failed switch / no source).
- **`doState3()` (Finish)** is single-pass: stop motor, close motor/regen/charge paths, **leave
  boosts + bus switches ON** so the bus stays armed (only State 99 tears it down). No cap/regen
  drain — the disabled-boost back-feed hazard doesn't apply while the boosts stay enabled.
- **State 98** adds a `busHotPlugUnsafe()` guard on `1`/`2` (refuses ON when the matching boost is
  ON and the bus is low) and a `G` command running `bringUpBus()` (switches → settle → boosts).
- New tunables `V_BUS_CHARGED_THRESH` / `BUS_SETTLE_MS` / `BUS_CHARGE_TIMEOUT_MS` (`TODO(calibrate)`).
  No telemetry change (reuses `FAULT_INIT_FAIL`/`ERR_INIT_FAIL`).

Tests: `test_dostate0_reaches_idle_unpowered` reworked for the phase machine; new
`test_dostate0_bus_charge_timeout`, `test_dostate98_hotplug_guard`,
`test_dostate3_leaves_bus_energized`. **All 219 host-native tests pass** (`-DBENCH_TEST=0`).
The BT TPS61288 has been replaced and the board is functioning again.

---

## 13. Corrected failure mechanism + BENCH_TEST bypass (2026-06-24, supersedes §12's inrush framing)

Bench bring-up from a **current-limited supply** repeated the `VBT→GND` short, which forced two
corrections to §12:
- **Inrush is NOT the cause.** The 470 µF bulk cap is on the **V-MOT/regen node behind
  `MOT_PWR_ENABLE`**, not on VBUS. VBUS carries only ~30–40 µF (RT1987 ceramics), and
  `MOT_PWR_ENABLE` was off in the original State-98 failure too — so there was never meaningful bus
  inrush. (§12's "470 µF bus" / "never hot-plug" framing is wrong; the gentle ordering is still fine,
  just not for the stated reason.)
- **The killer is a boost on a collapsing input.** The Teensy is board-powered (LM1084 off `VBT`).
  A soft/current-limited source sags when the boost loads it → board-powered Teensy browns out →
  resets → `doState0()` re-enables the boost → **motorboating**. Switching with built-up inductor
  current on a sagging/recovering rail destroys the power stage; the destructive energy is from the
  boost's own L/Cout, so a supply current limit does **not** bound it. Same class of event as the
  original weak-9 V-battery incident (replacing the TPS61288 fixed that, confirming the boost, not
  the `VBT` tantalum).
- **Exact mechanism UNCONFIRMED — pending a SW/VOUT scope capture.** Leading candidate (TPS61288
  datasheet SLVSFP3C): a **VOUT overshoot past the 20 V SW/VOUT abs-max**. OVP is at 19 V (≤19.5 V)
  — only ~0.5 V of margin — and the 3×22 µF output caps DC-derate to ~30 µF, so an inductor-
  commutation spike (½·L·I² at the 15 A cycle-by-cycle limit, 2.2 µH, into ~30 µF ≈ +3 V) rings
  over 20 V. Secondary: transient **reverse conduction** (datasheet weakens this — PFM blocks
  negative inductor current, EN-low reverse SW leak is 1 µA — so it's the lesser candidate). The
  scope test discriminates: SW/VOUT ringing >20 V on collapse ⇒ overshoot; clamped at 19 V but the
  part still dies ⇒ reverse-current/thermal. **Do this only on a stiff, instrumented bench setup,
  after the present 0.5 Ω short is repaired** — not on the current-limited supply that triggers the
  thrash.

### Hardware follow-ups (NOT in this firmware change; pending scope confirmation)
- **VIN UVLO that pulls EN low early** (~2.5–3 V, above the part's own ~1.9 V falling UVLO) so the
  boost stops switching *before* the rail sags into the collapse/recovery regime — reduces the
  inductor current present at the moment of collapse. Best layer for this (firmware can't react
  through its own brownout).
- **Voltage-stable output bulk on VOUT-FC / VOUT-BT** (e.g. 47 µF electrolytic/tantalum, immune to
  the ceramic DC-bias derating) to lower the overshoot magnitude. Note: even ~100–200 µF does not
  reliably keep a 15 A commutation under 20 V given the 19 V OVP baseline, so treat this as
  mitigation, not a cure.
- **TVS clamp on VOUT — considered and rejected.** To protect it must clamp <20 V; to not interfere
  it must stand off >19.5 V (OVP max). That <0.5 V window is unachievable for any real TVS
  (clamping ratios ~1.3+): a part that clamps under 20 V would stand off below the 17.5 V operating
  point and conduct in normal operation. So a TVS is not a viable fix here.
- The robust system-level fix remains: **never enable the boost on a source that can collapse** —
  which the `BENCH_TEST` bypass and the "stiff-supply-only for `G` bring-up" rule already enforce.

### Update — supply-transient theories SUPERSEDED (see docs/boost-bringup-debug.md)

A **third** battery boost was then destroyed by `G` (bring-up) on a **stiff ≥5 A supply**, and the
`D-BT-EN` EXP/VOUT-to-GND ohmmeter checks came back clean. Together these **rule out** the
supply-collapse / overshoot / reverse-conduction framing above and the EXP-short hypothesis. The
boosts work standalone; the FC bus connection works; only the **battery bus connection
(`BT_BUS_ENABLE` / `D-BT-EN`)** kills the boost, and it does so dynamically (no static short).
This is an **open hardware fault localized to the battery bus path**, not a bring-up-sequence or
supply problem — so the firmware work here, while sound defensively, does not address it. The
live debug log, datapoints, ruled-out list, FC-vs-BT schematic delta, safety rules (no input
current limit is proven safe — death #2 was 120 mA), and the boost-removed decisive test now live
in **`docs/boost-bringup-debug.md`**. Treat that file as the current source of truth for the
hardware issue.

Bypass:
- **`doState0()` wraps the bring-up in `#if BENCH_TEST`.** Under `BENCH_TEST` (default flash) it
  boots straight to Idle with the **power stage dark** (boosts, bus switches, `BT_SEQUENCE` all LOW;
  no `V_bus` gate); the bus is brought up manually via the State-98 `G` command on a stiff supply.
  Production (`BENCH_TEST=0`) keeps the full bring-up + gate. Shared init → `initControlPeripherals()`.
- **Comments/docs** corrected (`.ino` bring-up block + changelog, CLAUDE.md, README.md) to drop the
  inrush framing.
- **Bench rule:** supply must exceed the logic baseline (≥ ~0.5–1 A) or the Teensy browns out; bring
  the bus up only on a stiff supply.

Tests: new `test_dostate0_bench_bypass` built in a **second `-DBENCH_TEST=1` pass** (`run_tests_bench`);
the `-DBENCH_TEST=0` build keeps the production `doState0` tests. `make` builds + runs both.

---

## 14. Full-codebase audit round (2026-07-01)

A full audit against the authoritative sources (IO CSV, BOM, Ag105 JSON tables) verified the pin
map, Ag105 register values, telemetry v4 arithmetic, and sequencing guards as clean, and surfaced
the following issues, all fixed (user-approved where they touched "What NOT to change" code):

### Correctness / safety fixes
1. **`setup()` was killing the VESC UART.** `pinMode(RX, INPUT)` / `pinMode(TX, OUTPUT)` ran
   *after* `Serial1.begin()`; on Teensy 4.x `pinMode()` reassigns the pad mux from LPUART6 to
   GPIO, silently disconnecting the UART — every `vesc.setCurrent()` (including the safety
   zero-flushes) went nowhere. The two lines are deleted; a comment forbids touching pins 0/1
   after Serial1 init. Not host-testable (the mock `pinMode` is a no-op) — verify on bench.
2. **PI 0.0f sentinel removed (both PIs).** On sub-`sampleTime` ticks the PIs returned 0.0f;
   `motorControl()` runs every loop tick, so the sentinel chopped the VESC command to zero, and
   `powerBalance()` mapped it to droopRatio 0.01 → extreme MDAC gains for that tick. The
   integrator update remains gated to `sampleTime`; the output `Kp·e + Ki·accum` is now always
   computed live.
3. **Power-share PI anti-windup.** `pi_power_accum` clamped so `Ki·accum` stays within ±1.0
   (the droop ratio's full [0.01, 0.99] authority). Defensive: during FC-charge cruise
   (`BT_BUS_ENABLE` LOW) the EMS on the Pi commands `power_share_setpoint ≈ 1.0` to match the
   FC-only bus, so the share error is ~0 by design; the clamp covers off-nominal episodes
   (source loss, sensor dropout) that previously wound the integrator unbounded.
4. **`ag105DataValid` flag.** GENSTAT 0x00 is a *real* Table 6 status (Battery Disconnect), so
   `ag105_status_raw == 0` can't double as the "stale" marker. Validity is now tracked
   out-of-band: set on a successful read, cleared on NAK or power loss. `ag105IsReady()` and the
   `detectFaults()` GENSTAT check both gate on it (a stale error byte can no longer fault; a
   stale CHARGING byte can no longer report ready). Telemetry offset 51 still sends 0x00 when
   stale — the Pi's decode is unchanged.
5. **State 98 `'2'` mutual-exclusion guard.** `'2'` now refuses to raise `BT_BUS_ENABLE` while
   `FC_CHARGE_ENABLE` is HIGH (the IO CSV's illegal combination — previously creatable in test
   mode, and invisible under `BENCH_TEST` where the switch-conflict fault is compiled out).
6. **State 98 `'Q'` closes the charge paths.** Exit now runs `assertFcChargeEnable(false)` +
   `REGEN_ENABLE` LOW in addition to `MOT_PWR_ENABLE` LOW — `doState1()` never touches
   FC_CHARGE, so an operator-latched charge path used to keep the charger powered through Idle.

### Flagged, deliberately NOT changed
- **`LIMIT_V_BATT_MAX = 10.0f` can never trip**: the BT divider (16.2k/10k) saturates the ADC at
  8.646 V. Kept at 10.0 for 9V-battery bench testing per user decision; a `TODO` comment says to
  change it to **8.5f** (real margin below the divider ceiling) when that testing ends. Note the
  old 8.6f value was also unusable (~22 counts below saturation).
- `updateWheelSpeed()` unit chain (rev/s × inch, not m/s) and the `int` `timeArr` micros wrap
  (~35.8 min) — documented as `TODO(calibrate)` comments; velocity math left unchanged.

### Build / docs
- `USE_ETHERNET` is now `#ifndef`-overridable, and a `#warning` fires on the
  `BENCH_TEST=0 && USE_ETHERNET=0` combination (production faults with no Pi link and an inert
  watchdog). The test Makefile passes `-DNO_ETH_WARNING` (it builds that combination on purpose).
- Stale comments fixed: `SCALE_I` "~2.015 mA/count" → ~8.06 (the 2.015 figure was the never-fitted
  A3's); `doState99()` header rewritten to the corrected failure analysis (no TPS61288 body-diode
  claim; 470 µF is on V-MOT, and the phase-1 REGEN/MOT_PWR combination is stored-energy drain,
  intentionally not counted by `chargerHasPower()`); `doState3()` "470 µF bus" line corrected.

### Tests
- Updated: `test_pi_controllers` (live-output semantics + integrator-gating checks),
  `test_genstat_fault` (validity-gated cases incl. stale-error-byte and live-0x00),
  `test_poll_ag105` (validity lifecycle: NAK → invalid → stale-ready refused → re-valid),
  `test_charging_control_mppt_polarity` / `test_charging_control_fc_bootstrap`
  (`ag105DataValid = true` where readiness is expected).
- New: `test_power_pi_antiwindup`, `test_powerbalance_gated_tick_stable`,
  `test_dostate98_bt_bus_fc_charge_guard`, `test_dostate98_quit_closes_charge_paths`.
- **All 283 host-native tests pass** (278 in the `-DBENCH_TEST=0` build + 5 in the
  `-DBENCH_TEST=1` build). Caution: invoking `mingw32-make` from PowerShell can silently reuse
  stale binaries (the recipe's `PATH=` prefix doesn't resolve there) — build from an MSYS2 shell,
  or run g++ directly and check the executables' timestamps.
