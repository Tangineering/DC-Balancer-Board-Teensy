# VESC / Motor Integration — Handoff Notes

**Project:** SC001 Scale Car DC Balancer Board
**Companion to:** `CLAUDE.md` (firmware reconciliation instructions), `docs/design-review-2026-07-28.md`
**Hardware revision:** 20260622 (schematic / BOM / Teensy IO CSV mutually consistent)
**Last revised:** 2026-07-29 — research round + firmware pass; see §13 for what changed.
**Status:** VESC bringup in progress. Motor replacement decision OPEN but now *decidable* — see §8.
Velocity-mode and drive-cycle testing are **firmware-blocked** until the encoder is measured (§9, §10).

---

## 1. Purpose of this document

Captures the state of VESC Six EDU integration and the motor selection decision. Several firmware
constants cannot be finalized until the motor choice, the pole count, and the flywheel encoder
geometry are settled — those dependencies are listed explicitly in §9, and the measurements that
unblock them in §10. §12 is the source power budget that sizes the motor and the current limits.

This document does **not** cover the boost converter / power path work. See `CLAUDE.md` and
`docs/boost-bringup-debug.md` for that.

> **Provenance convention used below.** Values are tagged **[repo]** (from an authoritative file in
> this repository), **[web]** (externally sourced, no repo artifact — treat as verify-before-trust),
> or **[measure]** (not yet known). Nothing in this document is a guess; where a number is unknown
> it says so.

---

## 2. Hardware baseline

### Chassis
- **Traxxas 4-Tec 2.0 BL-2s**, model 83124-4
- 1/10 scale AWD, shaft-driven, dual limited-slip sealed differentials
- **Overall drive ratio: 9.49:1** (stock gearing) **[repo/web — corroborated by Traxxas]**
- Gear pitch: 48
- Tire diameter: 66 mm nominal (2.6 in) — **[measure]** verify with calipers
- Wheel (rim) diameter: 48 mm — not the value VESC wants
- Fixed gear mesh motor plate, 11 gearing positions
- Chassis mass 1.28 kg (2.83 lb) as a roller, **no body and no battery** **[web]**. Built-vehicle
  mass is **[measure]** — nothing in the repo records it, and §12 needs it.

> **Unreconciled discrepancy.** Traxxas advertises 40+ mph for 83124-4, but 3300 KV × 8.4 V through
> 9.49:1 on 66 mm tires is only **22.6 mph** no-load. Two independent sources confirm 9.49:1 and
> 2.6 in tires, so the marketing figure is the outlier — but caliper the tire and count the
> pinion/spur teeth (§10) before any of this goes in the thesis.

### Motor as delivered
**Traxxas BL-2s 3300** (part 3384)

| Parameter | Value |
|---|---|
| Type | Sensorless brushless |
| KV | 3300 |
| Poles | **[measure]** — not published by Traxxas |
| Can diameter | 37 mm |
| Can length | 57 mm |
| Weight | 201 g |
| Wire | 16 AWG |
| Cooling | Integrated fan |
| Rated cells | **2S LiPo (7.4 V nom / 8.4 V max)** or 6–7 cell NiMH |
| Phase connector | Traxxas single quick-connect |
| Sensor provision | None |

### Motor controller — VESC Six EDU
Verified against Trampa's manual and the `vedderb/bldc` hardware target `hwconf/trampa/vesc_edu/`
(`HW_NAME "EDU"`) **[web]**. **It is not electrically a VESC 6** — it is its own target with its own
limits, and the difference matters here:

| | VESC Six EDU | VESC 6 (MkV/MkVI) |
|---|---|---|
| Input voltage | 6–25 V (manual) / 6–26 V (product page); `HW_LIM_VIN 5.5–27 V` | `HW_LIM_VIN 6–57 V` |
| Rated current | **25 A continuous, 50 A burst** | far higher |
| Firmware motor-current default / hard limit | **20 A default, ±50 A hard, 65 A absolute** | ±120–160 A |
| Gate driver | individual half-bridge drivers, explicitly "no DRV chipset" | DRV8301 |
| Shunts | 3 phase shunts, 0.5 mΩ, amp gain **50** (⇒ ±66 A span) | 3 × 0.5 mΩ, gain 20 |
| Dead time | 50 ns | 360 ns |
| Default `foc_f_zv` | 30 kHz | 30 kHz |

The 16 V bus is comfortably inside the input window. **The current ceiling is roughly a sixth of a
VESC 6** — not a constraint here (§12 shows the sources cap out around 5 A of bus current), but do
not carry VESC-6 current intuitions across.

Configured via VESC Tool over USB (desktop).

### Bus
- **16 V nominal** **[repo]** — `V_BUS_NOMINAL = 16.0f`, set by the RD1 = 215k FB bodge (V0 = 15.91 V).
- **13.5 V** bring-up gate — `V_BUS_CHARGED_THRESH = V_BUS_NOMINAL − 2.5`. *(Earlier revisions of
  this document said "13 V droop floor"; the firmware value is 13.5 V.)*
- **12.0 V** Run-time UV fault floor — `LIMIT_V_BUS_MIN`. Distinct from the above; note the 1.5 V
  band where the bus is "not up" but also not faulted.
- **17.0 V** firmware OV fault — `LIMIT_V_BUS_MAX = V_BUS_NOMINAL + 1.0`. TPS61288 hardware OVP is
  at 19 V, so firmware trips first.
- **Braking chopper**: TL431 + BSP170P, **hardware only — not under firmware control**. The
  schematic's own annotation reads **"22V CHOPPER CIRCUIT"** **[repo]**, not the 20 V this document
  previously stated. 20 V appears in `docs/boost-bringup-debug.md` only as a design-target
  discussion. **[measure]** the actual trip point; do not treat either number as verified.

---

## 3. VESC unit history

### Unit #1 — RMA
Faulted `FAULT_CODE_HIGH_OFFSET_CURRENT_SENSOR_2` on every power cycle. Terminal `faults` readout at
time of fault:

```
Voltage         : 14.91
Temperature     : 28.92
Current         : 0.0
Current filtered: 0.0
Duty            : -0.003
RPM             : -0.0
Cycles running  : 0
TIM duty        : -15
TIM top         : 5600
```

Interpretation: clean rail, ambient temperature, **zero control cycles executed**. The startup
phase-2 current-offset self-check failed under ideal conditions with nothing attached. Not caused by
the Teensy, the commanded current (0.1 A), supply sag, or thermal. Pre-existing hardware defect in
the phase-2 sensing chain. The 16-blink LED pattern observed was this same single fault, not a
separate one.

Fault is not clearable — the check runs every boot and fails every boot. Do **not** attempt to loosen
the offset tolerance in firmware; FOC computes phase currents from those amplifiers and a bad offset
can command real current in the wrong direction on a 50 A bridge.

### Unit #2 — in service
Motor detection completed with no faults. **First detection wrote marginal parameters** — motor
emitted a high-pitched buzz and would not start under load. Re-running detection resolved it.

**Takeaway:** detection is not reliably repeatable on this motor. Low inductance (high-KV 540
inrunner, plausibly 5–15 µH) makes flux linkage measurement noisy, and a marginal result can pass
detection without raising a fault while still leaving the observer unable to start cleanly.

**Action item:** record R, L, and flux linkage from the current known-good detection as a reference.
Re-running detection later and comparing against these values distinguishes "detection drifted" from
"hardware changed." Additionally run `measure_ind <duty>` in the VESC terminal and record
`ld_lq_diff` — that number decides the HFI question in §8 outright.

---

## 4. VESC configuration — current state

### Settled
| Setting | Value | Rationale |
|---|---|---|
| Sensor mode | Sensorless | BL-2s has no sensor provision |
| Motor temp sensor type | **Disabled** | No thermistor in the BL-2s harness. Confirmed correct: with `Disabled`, the reading becomes a settable software value and `FAULT_CODE_OVER_TEMP_MOTOR` cannot fire. Leaving `NTC 10K` selected makes an open circuit read as a permanently fake **−100 °C** (the firmware's divide-by-zero guard substitutes it) — no fault, but no diagnostic value either. |
| Wizard motor preset | Inrunner, Small | 540-class can, 37 × 57 mm, 201 g. VESC Tool's own "Small Inrunner (~200 g)" preset is `maxLosses 50 W, openloopErpm 1400, sensorlessErpm 4000, poles 2` **[web]** — useful reference values. |

> ⚠️ **No thermal protection is currently active on the motor.** Combined with a 2S-rated motor on a
> 16 V bus, keep runs short and check the can by hand between attempts. Note §8: a Castle sensored
> motor would restore this, because the ROAR sensor port carries a 10 kΩ NTC.

### Needs setting or verification
| Setting | Current | Should be | Notes |
|---|---|---|---|
| Motor Poles | 2 (wizard default) | **[measure]** | Field is **poles**, not pole pairs, in FW 5.x/6.x/7.x. See the correction below — it is *not* purely cosmetic. |
| Gear Ratio | 13 / 36 = 2.77:1 | represent **9.49:1** | Default is a skateboard preset. Motor Pulley 100 / Wheel Pulley 949 gives exactly 9.49; 2 / 19 gives 9.50 (0.1% error) if fields cap at two digits. |
| Wheel Diameter | 83 mm | **66 mm** **[measure]** | Tire OD, not rim. Caliper the actual mounted tires — RC rubber varies and balloons at speed. |
| Max ERPM cap | not set | see the caveat below | **This is a weaker protection than previously assumed.** |
| **Battery Current Max** | not set / not tracked | **≈4.2 A** | **NEW — this is the setting that actually protects the bus.** See §12.4. |
| **Battery Current Regen Max** | not set / not tracked | **≈1.5 A** | Bounds regen into the bus/charger. |
| `foc_f_zv` (Zero Vector Frequency) | 30 kHz (EDU default) | leave at 30 kHz | See the correction below — it is already at the EDU default *and* at the practical ceiling. |

### ⚠️ Correction: an ERPM cap does **not** protect against mechanical overspeed

Earlier revisions of this document proposed mitigating the Justock family's 2–3S voltage rating with
an ERPM cap. Verified against `bldc/motor/mc_interface.c` **[web]**, that mitigation is much weaker
than assumed:

- `l_max_erpm` / `l_min_erpm` / `l_erpm_start` work by **reducing the drive current only**. They are
  folded into `lo_max` (the motoring limit) and **never into `lo_min`** (the braking limit). This is
  deliberate — the changelog records *"It is now possible to apply break past the RPM limits."*
- Therefore **any overspeed not caused by your own throttle is unbounded**: downhill, freewheeling,
  or a driven wheel on a dyno. The cap is a throttle-authority limit, not a speed governor.
- There *is* a soft ramp (`l_erpm_start`, default 0.8 = start derating at 80% of the cap).
- FW 7.00 added optional Overspeed faults (`l_additional_faults`, **default 0 = all disabled**), and
  even those just cut PWM and coast, auto-clearing after 500 ms — a 500 ms coast/re-arm cycle, not a
  limit. **They do not exist in FW 5.x or 6.x at all.**

**Consequence for §8:** "cap the ERPM" is not a sufficient answer to running a 2–3S-rated motor at
16 V. A motor whose rating actually covers 16 V is worth real money in this decision.

Practical note: stock `l_max_erpm = 100000` with `l_erpm_start = 0.8` means a 4-pole 3300 KV motor at
16 V (105.6k ERPM no-load) is **already** being derated from 80k ERPM. Set these deliberately either
way.

### ⚠️ Correction: pole count is not purely a reporting value
`si_motor_poles` appears **zero times** in `mcpwm_foc.c` / `foc_math.c`, so the earlier claim is right
for the FOC core: observer, openloop, and current control do not use it. But it also scales:
- `COMM_SET_MCCONF_TEMP_SETUP` — converting a *speed* limit into `l_min_erpm`/`l_max_erpm`. **A wrong
  pole count here silently mis-sets your ERPM limits.**
- UAVCAN reported RPM, the LispBM speed PID setpoint, and app-layer speed logic.

Also: VESC Tool's field declares `stepInt = 2`, but Qt's `singleStep` only governs the arrow
increment — a typed **odd** value is accepted and stored, and the firmware then computes
`si_motor_poles / 2.0` as a float without complaint. Sanity-check what actually gets written.

### ⚠️ Correction: "raise FOC switching frequency to 30–40 kHz"
The VESC Tool field is **`foc_f_zv` — Zero Vector Frequency — which is 2× the frequency the MOSFETs
actually switch at.** Verified in `mcpwm_foc.c` (`timer_reinit` uses centre-aligned PWM, so
f_PWM = f_zv/2) and in VESC Tool's own help text **[web]**.

- 30 kHz `foc_f_zv` ⇒ **15 kHz on the FETs**, 15 kHz control loop (V0-only).
- **The EDU already defaults to `foc_f_zv` = 30 kHz** — an override of the firmware-wide 25 kHz. So
  there is nothing to raise.
- The GUI spinbox advertises 0–150 kHz, but the firmware **clamps every write**:
  `HW_LIM_FOC_CTRL_LOOP_FREQ = 3000, 30000` (the EDU does not override it) ⇒ **3–60 kHz for
  `foc_f_zv`** V0-only single-motor, or **3–30 kHz** with V0+V7 sampling. The clamp sits *before*
  `#ifndef DISABLE_HW_LIMITS`, so it survives even `*_no_limits` builds.
- 40 kHz on the FETs would need `foc_f_zv` = 80 kHz, which **is not writable**.
- Raising it is not free: the only measured VESC data found puts **20 kHz as most efficient**, with
  higher frequencies "more stable and consistent above 20kHz, but less efficient". Trampa's guidance
  is incremental: go 20 → 30 kHz and watch MOSFET temperature. **No current-derating table exists —
  treat that absence as undocumented, not as permission.**
- Sampling window shrinks with f_zv: the current-sample guard is a fixed 900 timer counts
  (≈5.36 µs), which is ~70% duty at 30 kHz and a larger fraction as f_zv rises.

### ⚠️ Correction: the ripple argument
The earlier claim — "at 16 V, 25 kHz, 50% duty, ~10 µH, ripple is roughly 16 A pk-pk, enough to
swamp the torque-producing component" — needs three fixes:
1. **Arithmetic is right** (16.0 A), and 25 kHz is the right frequency to use *because it is f_zv* —
   but the FETs are at 12.5 kHz. The two statements are both true; the wording was ambiguous.
2. **Physics is 1.5–2× pessimistic.** `foc_motor_l` is the *per-phase* average of Ld and Lq (its
   sibling `foc_motor_r` is explicitly "half of what is measured between two motor wires"). A
   three-phase bridge sees 1.5–2× that, so the realistic figure is **~8–11 A pk-pk**, not 16.
3. **"Swamps the torque component" is not how VESC frames it, and is quantitatively weak.** Ripple is
   zero-mean over a switching period, FOC regulates the average, and the ADC is deliberately sampled
   inside the zero vector for exactly this reason. At 8 A pk-pk on 5 A DC the RMS copper-loss penalty
   is ~10%. VESC's actual framings are **current-measurement offset** ("reduces current offsets on
   motors with low inductance with high current ripple") and **reaching high ERPM**. The buzz observed
   during the failed startup is more likely marginal detection (§3) than ripple.

A sharper reason to care about f_zv for this motor is **control updates per electrical revolution**:
3300 KV at 16 V is 52.8k ERPM (2-pole) or 105.6k ERPM (4-pole); at 15 kHz control rate that is 17.0
updates/elec-rev at 2 poles but only **8.5 at 4 poles**.

---

## 5. Wiring: VESC ↔ Teensy 4.1

### COMM connector
| VESC COMM pin | Connection |
|---|---|
| TX | Teensy RX (pin 0) |
| RX | Teensy TX (pin 1) |
| GND | PCB GND |
| VCC / 3.3V | **DO NOT CONNECT** |
| Power | **LEAVE FLOATING** |

Pin assignment confirmed against `references/Scale Car Teensy IO - IO.csv` (rows 0 and 1, both noted
"Used for VESC") **[repo]**.

**VCC:** The VESC's 3.3 V pin is an output from its own onboard regulator (~0.5 A on the 6-series).
The Teensy already has a 3.3 V rail from the balancer board. Tying two independently regulated
outputs to the same node risks backfeed into one regulator's output pin. The UART link needs only TX,
RX, GND.

**Power pin:** This is the soft-power / hibernation switch input, not a supply. Trampa's "Option 4:
separate soft start power switch" applies — off-board switching handles main battery
connect/disconnect, so this pin stays unconnected. The VESC powers up whenever B+ is present. Trades
away auto-power-off and roll-to-start, neither of which this architecture needs.

**Ground loops:** single-VESC setup on a common battery/board ground is fine. Do not share COMM GND
with a second VESC.

**Never call `pinMode()` on Teensy pins 0/1.** On Teensy 4.x it reassigns them from LPUART6 to GPIO
and silently kills all VESC communication, including the `setCurrent(0)` safety flushes. Pin
ownership is established by `Serial1.setRX()/setTX()/begin()` alone. This bug was present and is
fixed; the firmware carries a standing warning comment.

**BLE / NRF:** the wireless bridge is typically wired to a UART on VESC hardware and may contend with
the COMM port the Teensy uses. Verify which UART each occupies before enabling BLE. Also confirm
whether the NRF52 module is even populated — it varies by EDU variant. iOS has no USB serial path
(BLE only); Android USB OTG works but has been inconsistent across VESC Tool builds. Desktop USB is
the reliable commissioning path.

---

## 6. Division of responsibility — do not violate

| Domain | Owner |
|---|---|
| Motor detection | VESC Tool (USB) — **cannot** be driven over UART |
| Sensor mode, hall table, app config, BLE, persistent limits | VESC Tool (USB) |
| Runtime current commands | Teensy (UART) |
| Telemetry read (`COMM_GET_VALUES`) | Teensy (UART) |

**Do not implement persistent config writes in `teensy_controller.ino`.** Verified absent: the
firmware issues only `COMM_SET_CURRENT`, `COMM_FW_VERSION` and `COMM_GET_VALUES`, and the vendored
`libraries/VescUart` exposes no method that sends `COMM_SET_MCCONF` / `COMM_SET_APPCONF` at all
(the enum values exist in `datatypes.h`; nothing sends them) **[repo]**.

The reason stands: `COMM_SET_MCCONF` serializes the *entire* config struct as a flat blob with
per-field scaling in a fixed, **firmware-version-specific** order. There is no "set one parameter"
message. VESC Tool handles this by fetching the firmware's parameter description at connect time,
which a hardcoded implementation does not. Getting it wrong writes garbage across the whole motor
configuration.

### ⚠️ Nuance added 2026-07-29: `COMM_SET_MCCONF_TEMP` is a different, safe mechanism
`COMM_SET_MCCONF_TEMP` (48) / `COMM_SET_MCCONF_TEMP_SETUP` (49) are **not** whole-struct writes. The
payload is `store, forward_can, ack, divide_by_controllers` followed by exactly ten scaled floats:
`l_current_min_scale, l_current_max_scale, l_min_erpm, l_max_erpm, l_min_duty, l_max_duty,
l_watt_min, l_watt_max` (+ optional `l_in_current_min/max`) **[web]**.

With **`store = 0` it applies to RAM only — no flash wear** — and `commands_apply_mcconf_hw_limits()`
runs on the result. Read back with `COMM_GET_MCCONF_TEMP` (91).

This is the legitimate way for the Teensy to adjust the ERPM / wattage / battery-current envelope at
runtime if that is ever wanted (e.g. derating the bus current limit as the fuel cell sags). It is
**not** implemented today and is not required — noted so the blanket "no config writes" rule is not
misread as ruling out the one mechanism designed for exactly this.

---

## 7. Firmware gotchas

- **`COMM_SET_CURRENT` takes AMPS in the API, milliamps on the wire** (int32, `current * 1000`).
  Confirmed both during bringup (`0.1` = 100 mA) and in `VescUart.cpp` **[repo]**.
- **The VESC command timeout is 1000 ms and it COASTS, not brakes.** `timeout_msec = 1000` and
  `timeout_brake_current = 0.0` by default; on expiry `mcpwm_foc_set_brake_current(0)` falls below
  `cc_min_current` (0.05 A), which releases the motor → `stop_pwm_hw()` → all FETs off **[web]**. So
  a silent Teensy means the vehicle freewheels. The timeout thread ticks at 100 Hz, so resolution is
  ±10 ms. `COMM_GET_VALUES` bit 21 reports `timeout_has_timeout()` — that is the flag to watch.
- **`COMM_GET_VALUES` bits 2–5 RESET the averaging accumulators on read.** If VESC Tool is connected
  over USB while the Teensy polls over UART, the two masters steal each other's current averages.
  Use `COMM_GET_VALUES_SELECTIVE` (50) with a mask that excludes them, or accept that the numbers are
  valid only for whichever master polled last. **[web]**
- **Reported RPM is ERPM.** Mechanical RPM = ERPM ÷ pole pairs, where pole pairs = poles ÷ 2.
- **Do not derive vehicle speed from VESC ERPM.** Use the flywheel encoder. The flywheel is
  downstream of the 9.49:1 reduction *and* the limited-slip differentials — there is no fixed
  kinematic relationship between wheel position and rotor position. Any side-to-side speed difference
  or tire slip changes the mapping. **Corollary for firmware: the 9.49:1 ratio does NOT belong
  anywhere in the Teensy's velocity chain** — the encoder already turns at wheel speed. It is a
  VESC-Tool-side value only.
- **Flywheel encoder → Teensy, not VESC.** The Teensy 4.1 has hardware quadrature decoders. This
  keeps vehicle-level instrumentation out of the motor control loop, and the encoder is unsuitable
  for commutation regardless.
- **The UART comm stack runs even when drive is faulted or disabled.** Packet framing and
  `COMM_GET_VALUES` parsing can be validated against a faulted unit — useful if unit #2 ever goes
  down.
- **`setCurrent()` backpressures the main loop.** A 9-byte frame at 115200 8N1 is 781 µs of wire
  time, and Teensy `HardwareSerial::write()` blocks on a full TX FIFO. Calling it every tick pinned
  the loop rate (including `detectFaults()`) and queued superseded commands. **Fixed 2026-07-29** —
  see §13; motor commands are now rate-limited to 500 Hz.

---

## 8. OPEN DECISION: motor replacement

### Two problems, one fix

**Problem 1 — overspeed.** BL-2s is rated 2S (8.4 V max). Bus is 16 V nominal.

```
3300 KV × 16.0 V ≈ 52,800 RPM no-load   (on the 16 V bus)
3300 KV ×  8.4 V ≈ 27,700 RPM no-load   (at 2S full charge — the design point)
                   ≈ 1.9× overspeed
```

The binding limit is mechanical — magnet retention adhesive and bearing life in a 540 can — and that
failure mode is abrupt, not gradual. **And per §4, an ERPM cap does not reliably bound it.**

**Problem 2 — sensorless low-speed stutter.** Present and objectionable. Confirmed after successful
detection, so it is inherent to sensorless startup on this motor, not a configuration error.

A lower-KV **sensored** motor addresses both simultaneously.

**Target KV:** ~1600–1750, which reproduces stock shaft speed at 16 V and keeps the 9.49:1 reduction
and 66 mm tires valid. Favour the low end — see the free-run loss finding in §12.3.

### Candidates

Specs re-verified 2026-07-29. **Note the corrections to the previous table.**

| Motor | KV | Poles | Rated | Dia × Len (mm) | Shaft | Weight | RPM @ 16 V | Sensor |
|---|---|---|---|---|---|---|---|---|
| Hobbywing Justock 3650 SD G2.1 **25.5T** | 1600 | 2 | 2–3S | 35.9 × 52.5 | 3.17 | 173 g | 25,600 | plain Hall endbell |
| Hobbywing Justock 3650 SD **21.5T** (prev gen) | **1800** ⚠️ | 2 | 2–3S | 35.9 × 52.5 | 3.17 | 182 g | 28,800 | plain Hall endbell |
| Hobbywing Justock 3650 SD G2.1 **21.5T** | 2050 ⚠️ | 2 | 2–3S | 35.9 × 52.5 | 3.17 | 175 g | 32,800 | plain Hall endbell |
| Castle Creations **1406-1900Kv** (CSE060-0068-00) | 1900 | **4** (12-slot) | **2S–4S** | 36 × 49.5 | 3.175 × 15 mm | 197 g | 30,400 | **ROAR standard port ✅** |
| Hobbywing Xerun AXE 540 **1800KV** FOC | 1800 | 4 | 2–3S | 36 × 48.8 | 3.175 | 173 g | 28,800 | ❌ reject |
| Hobbywing Xerun AXE 540 R2 **2300KV** | 2300 | 4 | 2–3S | 36 × 49.8 | 3.175 | 185 g | 36,800 | ❌ reject |

All RPM-at-16 V figures in the previous revision were recomputed and **reproduce exactly**.

**⚠️ Spec corrections and caveats:**
- **Prev-gen Justock 21.5T is 1800 KV, not 1750.** The 1750 figure could not be substantiated.
  Its published no-load current is **1.3 A** — notably lower than the G2.1's, which matters (§12.3).
- **The "0.075 Ω / 110 W max output / 35 A" figure for the prev-gen 21.5T could not be re-verified**
  and should not be relied on. See §12.4 for why it was misleading anyway.
- **G2.1 21.5T KV is disputed**: Hobbywing, AMain, HobbyTown and hobbywingdirect all say 2050 KV;
  rcmart lists the identical part number as 1900 KV. Probably an rcmart labelling error.
- **G2.1 25.5T**: one source gives 0.104 Ω and 86 W / 25 A at 7.4 V (Hobbywing's own disclaimer says
  this is a test value, not a continuous rating), no-load current **2.8 A**. Lower confidence.
- **No Hobbywing or Tekin candidate was confirmed to carry a thermistor** on the sensor harness.
  Consistent with spec-class RC motors generally.
- **Hobbywing sensor connector is JST-ZH 1.5 mm 6-pin; the VESC SENSE port is JST-PH 2.0 mm 6-pin.**
  Similar-looking, different pitch — an adapter is required, not optional.

**Structural finding from the alternatives search:** true ROAR/IFMAR 2-pole "stock spec" motors in
the 1500–1900 KV band are essentially **all class-restricted to 2–3S**. The only 4S-capable options
at this KV and size are **4-pole crawler-class** motors (Castle 1406; Tekin ROC412 1800 KV, which is
marked discontinued on Horizon Hobby's own page). This is a genuine hardware-availability constraint,
not a gap in the search. Motors that pass on KV and 4S but fail on size/shaft were checked and
rejected: Surpass Rocket 3670/3674 and Leopard 3674 (36 × 73–74 mm can, 5 mm shaft), Turnigy
TrackStar 1900 KV (1/8 scale, 42 × 70 mm, 5 mm shaft); Hobbywing V10 G4/G4R and LRP X22 are 1–3S.

### ✅ RESOLVED: the Castle sensor **is** VESC-compatible

The previous revision's blocking concern — that Castle's "QuietSense" flux shield and secondary sense
magnets might be a proprietary sensor interface unusable as a VESC Hall input — **is unfounded.
Confidence: HIGH** on the electrical question.

1. **Castle's own product page for CSE060-0068-00 states "ROAR standard sensor port and labeled
   connections."** SmartSense is listed as the *only* mode requiring a Castle ESC; "Sensored" and
   "Sensorless" are not.
2. **ROAR §8.4.6.1 defines that port verbatim**: 6-position JST **ZHR-6**, pin 1 = ground,
   pins 2/3/4 = phase C/B/A position signals, **pin 5 = 10 kΩ thermistor referenced to ground**,
   pin 6 = **+5.0 V ±10%**. Nothing serial, encoded, analog or sinusoidal.
3. **ROAR §8.4.6.2 additionally bans dynamic timing** ("timing which varies with motor speed or
   load") — a rules-level guarantee that the output is a static position signal, which is exactly
   what VESC's hall table assumes.
4. **Decisive datapoint on this exact part:** an ODrive user ran a Castle 1406-1900 kV in Hall
   feedback mode, with specs obtained from Castle support: `pole pairs: 2`, `cpr: 12`,
   `sensors: open drain`. Encoder-offset calibration **succeeded**. `cpr 12` = 6 Hall states × 2 pole
   pairs, i.e. the standard six states per electrical revolution — precisely what VESC expects.
5. **Why the concern arose:** QuietSense is a *magnetic* design (shielding the Hall ICs from stator
   field noise), not a change to the output signal; SmartSense is ESC-side firmware. Several AI
   search summaries also mis-attach a real VESC-guide warning about "proprietary encoders" to Castle
   — that warning names **Hobbywing AXE**, never Castle.
6. **Open-drain into VESC pull-ups is the correct pairing:** the VESC 6 schematic shows 212 Ω on the
   hall lines, a 10 kΩ pull-up + 100 nF on `TEMP_MOTOR`, and a solder jumper selecting 5 V vs 3.3 V
   sensor supply; firmware sets hall pins `PAL_MODE_INPUT_PULLUP` in every hwconf.

**Confidence is MEDIUM-HIGH on "works first try on a VESC specifically", for one reason only:
there is zero public precedent.** Exhaustive sweeps of vesc-project.com, Endless Sphere, esk8.news,
pev.dev, RCGroups and `vedderb/bldc` found **no one who has run a Castle sensored motor on a VESC
with the sensor port connected** — success or failure. The residual risk is ordinary integration
friction (connector pitch, NTC pin, hall table offset), not a proprietary-protocol wall.

**Remaining unknown that could actually bite:** whether Castle's Hall ICs are **latching or
non-latching**. A VESC user scoped good and bad motors and found non-latching parts "staying active
longer than intended", giving unequal pulse widths and misaligned state changes. No teardown, scope
trace, or Hall part number for a Castle sensor board exists publicly.

**Buying trap:** Castle's **Direct Connect** wire (011-014x-00) is ROAR on the motor end but
**Castle-proprietary on the ESC end** — useless here. Buy the plain **Motor Sensor Wire 011-0149-00**
(ROAR both ends), plus a **JST ZH 1.5 → PH 2.0 6-pin adapter** (~$4, commodity part).

**10-minute pre-purchase / pre-wiring test, no VESC risk:** power pins 6/1 from a bench 5 V, hang
3× 4.7 kΩ pull-ups to 5 V on pins 2/3/4, and scope those three while hand-turning the rotor. Expect
three ~50% duty square waves 120° apart, six distinct states per electrical rev, two electrical revs
per shaft turn. That one capture confirms open-drain, digital, standard spacing, and latching
behaviour at once.

### The core tradeoff, restated

| | Justock G2.1 25.5T (1600 KV) | Castle 1406-1900Kv |
|---|---|---|
| Voltage rating vs 16 V bus | 2–3S → **16 V is ~27% over rating**, and §4 shows the ERPM-cap mitigation is weak | **2S–4S → 16 V is INSIDE rating** ✅ |
| VESC Hall precedent | plain Hall endbell, the known-good path | ROAR-standard, but **no published VESC precedent** |
| Thermistor → restores thermal protection | **No** | **Yes** — ROAR pin 5, 10 kΩ NTC ✅ |
| KV / RPM match to the 8.4 V design point | 1600 KV → 25,600 RPM, best match, highest Kt | 1900 KV → 30,400 RPM, ~10% over |
| Free-run loss (the dominant cruise load, §12.3) | lowest of the Justock family (but 2.8 A no-load quoted) | **[measure]** — not published |
| Poles | 2 | 4 → halves control updates per elec-rev (§4), 8.5 at 15 kHz |
| Published electrical specs | partial, low confidence | **none found** (no resistance, no current rating) |
| Low-speed smoothness | spec-class racing motor | two independent signals suggest 4-pole Castle needs tuning |

**Neither dominates.** The decision now turns on which risk you prefer: *running a motor 27% over
its voltage rating with no reliable overspeed protection* (Justock), or *being the first person to
put a Castle sensor on a VESC, on a motor with no published electrical specs* (Castle) — with the
compensation that Castle is in-rating and restores motor thermal protection.

**My recommendation: Castle 1406-1900Kv, contingent on the 10-minute scope test above.** The
voltage-rating and thermistor arguments are structural and permanent; the Castle-on-VESC risk is
~$4 of connector and one bench measurement to retire. If the scope test looks wrong, fall back to
the **Justock G2.1 25.5T (1600 KV)** and accept the over-voltage with short runs and hand checks.

*(§12.4 closes the "power ceiling caveat" that previously kept a 3660/3670-class can open: it is not
needed, and would be actively worse. The §10 rearward-length measurement is consequently no longer
on the critical path.)*

### Fallback if the motor is kept: HFI is very unlikely to work

The previous revision suggested "HFI is worth trying before committing to hardware — it costs only
settings time." Research says this is optimistic to the point of being misleading. **For a
low-saliency surface-PM inrunner this is a hard floor, not a tuning problem:**

- **Every HFI variant divides by `p_inv_ld_lq = (1/Lq − 1/Ld)`.** As saliency → 0 the position signal
  amplitude → 0 while noise stays. Vedder's own (since-refactored) code comment: *"this HFI-method
  makes no sense on such a motor and should be handled upstream."* At exactly zero, VESC Tool warns
  of a **CPU reboot** from the division by zero.
- The tracked quantity is the **2nd** FFT harmonic (the saliency signal). The saturation-based path
  that could work without saliency is **commented out** in master, with the note *"It might be
  possible to compensate for that, which would allow HFI on non-salient motors."*
- Raising HFI voltage raises signal **and** noise together, because the relative modulation scales as
  **ΔL/L**, not absolute ΔL.
- **Closest published data point, and it failed on this hardware:** a 4-pole, 200 g, cylindrical
  ferrite inrunner on a **VESC Six EDU** at 24 V — *"the shape doesn't change when rotating the motor
  by hand."* Unresolved, no maintainer reply. Community verdict in-thread: *"HFI is not working with
  every motor."*
- Reference scale: VESC Tool ships `foc_motor_l` = 12.27 µH with `foc_motor_ld_lq_diff` = 3.77 µH,
  i.e. an out-of-box assumption of **≈31% saliency**. A healthy outrunner measures 40–55%. A smooth
  cylindrical surface magnet is a few percent at best.
- Two hardware preconditions before blaming the motor: `foc_f_zv` **≤ 30 kHz** (official: *"HFI and
  VSS only work when the FOC switching frequency is at or below 30 KHz"*), and accurate,
  channel-matched current sense in the **0–3 A** band. The two forum cases where HFI was actually
  *fixed* were both current-sense problems, not gain tuning. The EDU's 3 phase shunts are the good
  case here.
- **NOT FOUND:** any report of HFI on a 2-pole motor, or on anything in this motor's class.

**The 10-minute test that decides it:** run `measure_ind <duty>` from the VESC terminal at several
duties and read the printed `ld_lq_diff`; then enable the HFI plot (`foc_plot 1`) and watch graph 2
(`ld_lq_diff`, µH) while hand-rotating the rotor. **Flat versus rotor angle ⇒ HFI is out.** Note the
editor permits *negative* `ld_lq_diff`, so a noise-driven sign flip would invert the tracking gain
and produce the well-documented "runs backwards" failure. Never leave the field at exactly 0.

**The officially sanctioned low-saliency option is VSS, not HFI.** VESC Tool: *"Vedder Sensorless
Start. Use HFI just after starting the motor to resolve the initial position… **As this also is based
on saturation it can help start some motors with low saliency.**"* Saturation, not saliency — that is
the distinction that matters here. Available from FW 5.03.

Ladder, in order: **Hall sensors / encoder → VSS → plain sensorless FOC with openloop tuning →
BLDC mode with startup boost.** Continuous HFI tracking is the one option the maintainer's own code
comments rule out for a non-salient rotor.

**Openloop tuning levers**, if the motor is kept (exact field names, FW 6.05+ defaults):
`foc_openloop_rpm` (1500; VESC's own Small-Inrunner preset says **1400** — raise, since 1400 ERPM is
only 700–1400 mechanical rpm at 1–2 pole pairs), `foc_sl_erpm` (3500; preset says **4000** — raise
together with openloop), `foc_openloop_rpm_low` (0 — keep low so zero throttle does not spin),
`foc_sl_openloop_time_ramp` (0.1 s — **raise**; a near-zero-inertia 540 rotor plus the firmware's 60°
phase kick is exactly the violent-start case), `foc_sl_openloop_time_lock` (0 — **raise to
0.02–0.05 s** to align the rotor first; a 2-pole SPM has almost no cogging to hold position),
`foc_sl_openloop_hyst` (0.1 s — **lower to 0.02–0.05 s** for quick re-entry when the observer loses a
fast low-inertia rotor), `foc_sl_openloop_boost_q` / `max_q` (FW 6.00+; small boost, bounded — the
tool warns it "potentially makes the start more jittery"), `foc_start_curr_dec` (FW 6.00+; reduce
below 1). On FW 6.05+ `foc_observer_type` already defaults to the **MXLEMMING λ-compensated**
observer, which does not depend on the observer gain — a real advantage over Ortega on FW 5.x.

> **Doc bug worth knowing:** the widely-repeated observer-gain rule of thumb "**600 / L**" comes from
> a stale comment in `mcconf_default.h` and does **not** match the implemented formula, which is
> flux-linkage based: `gain = (1e-3 / λ²) × 1e6`. VESC Tool's own relation is
> λ ≈ 6.048/(Kv · pole_pairs), so 3300 KV gives λ = 1.83 mWb (2-pole) → gain ≈ 298, or 0.92 mWb
> (4-pole) → ≈ 1191. There is also a factor-2 inconsistency between two code paths that compute it.

### VESC Hall wiring, if a sensored motor is adopted
- SENSE port is **6-pin JST-PH 2.0 mm (PHR6)**. Connect 0 V, +5 V, H1, H2, H3.
- RC motors terminate in **JST-ZH 1.5 mm** → **adapter required**. Commercial PH-to-ZH adapters exist
  (~$4), or crimp your own.
- **Check the sensor-supply jumper selects 5 V, not 3.3 V.** ROAR Halls expect 5 V.
- +5 V and GND must be correct. **Hall order does not matter** — Vedder: *"The default hall pinout on
  most hobby motors should match the VESC sensor port 1:1"*, and VESC learns a 6-entry table, so any
  consistent permutation works. ROAR's pin order is reversed (pin 2 = C, pin 4 = A); you do not have
  to unpick it.
- Procedure: **Motor Settings → FOC → Hall Sensors → run measurement** (wheel rocks slightly forward
  and back) → **Apply** → **Write Motor Configuration**. Then `hall_analyze 10` in the terminal —
  **any `255` entries in the table mean an unseen state and are your tell.**
- **Leave the NTC (pin 5) unpopulated on first wiring.** A mismatched temp pin produced a false
  250 °C `OVER_TEMP_MOTOR` that **blocked hall detection entirely** until the pin was pulled. On a
  ROAR plug the NTC sits directly beside +5 V. Once halls are working, connect it and set the sensor
  type — see below.
- **If the harness carries a thermistor** (Castle's ROAR pin 5 does), re-enable the temp sensor and
  restore the protection currently disabled per §4. The VESC expects **R25 = 10 kΩ NTC to GND** with
  an on-board 10 kΩ pull-up to 3.3 V and a β-model referenced to 298.15 K; `m_ntc_motor_beta`
  defaults to **3380 K**. A generic 10 k / β = 3380 part drops straight in; otherwise use "NTC
  Custom" with `m_ntcx_ptcx_res` / `m_ntcx_ptcx_temp_base`. Cutoffs: `l_temp_motor_start` 85 °C
  (derate begins), `l_temp_motor_end` 100 °C (fault). **Castle's β value is unverified — ask support.**
- Sensored spec motors are 2-pole; Castle and AXE are 4-pole. Whichever is chosen, the pole count
  question in §4 resolves as a side effect.

**The single question to ask Castle support** (they have answered this kind of question before):
*"For the 1406-1900Kv sensored motor (CSE060-0068-00): are the three sensor outputs on the ROAR port
plain open-drain digital Hall outputs spaced 120 electrical degrees, are the Hall ICs latching or
non-latching, and what is the beta value of the pin-5 thermistor?"* The latching question is the only
one you cannot easily answer yourself.

---

## 9. Firmware constants and their blockers

**Recategorized 2026-07-29.** The previous table listed pole count and the ERPM cap as *firmware*
blockers. They are not: the firmware never consumes VESC-reported RPM for control (`vesc.data.rpm` is
read at exactly two places, both USB-serial diagnostic prints in State 98), never commands RPM or
duty, and holds no pole-count or ERPM constant. Both are **VESC-Tool-side settings**. Meanwhile the
two constants that genuinely gate the velocity loop were **absent from the old table**.

### Genuine firmware blockers

| Constant | Value | Status |
|---|---|---|
| `ENCODER_SLOTS_PER_REV` | 512 (placeholder) | **BLOCKING — [measure]**. See below. |
| `FLYWHEEL_RADIUS_M` | 0.033 (nominal from 66 mm OD) | **BLOCKING — [measure]** caliper the tire; confirm what the disc is coupled to. |
| `motorConstant` | 0.1 | **BLOCKING** for velocity mode. Not a real k_t — it is the lumped PI-output→amps gain. Calibrate *after* the two above. |
| `MOTOR_I_CMD_MAX` | **5.0 A** (bench) | Set from §12.4. Vehicle value 15.0 A after calibration. |
| `LIMIT_I_FC_MAX` | **1.4 A** (bus-side) | Set from §12.2. `TODO(verify)` — the H-20 datasheet is **not in the repo**. |
| `LIMIT_I_BT_MAX` | **3.0 A** (bus-side) | Validated per-channel envelope. Raise toward 4.2 A only after the scope-ring check. |
| `MOTOR_CTRL_PERIOD_US` / `CHARGING_CTRL_PERIOD_US` / `POWER_BAL_PERIOD_US` | 2000 / 20000 / 1000 µs | `TODO(calibrate)` — first-cut, chosen to clear the UART floor. Profile the real loop period. |
| Nominal bus voltage | 16 V | ready |
| Bus thresholds | 13.5 V gate / 12.0 V UV / 17.0 V OV | ready — but see §2 on the 1.5 V band |
| ADC scaling | fixed by the physical dividers | ready. *Note: these are set by the BOM divider resistors and were **independent** of the 16 V retarget — they never needed to change.* |

**Why `ENCODER_SLOTS_PER_REV` is the critical one.** The encoder is **not a commercial part**: the BOM
fits **2 × OPB829DZ** through-beam optical sensors ("Optical Sensor Through-Beam 0.125in (3.18 mm)
Phototransistor Module", BOM line 71) plus 2 × 4.7 kΩ pull-ups (line 73) — a home-built
beam-interrupt quadrature encoder on a slotted disc **[repo]**. Counts/rev is therefore a property of
the disc, with no datasheet. The decode factor is **×2** per quadrature cycle, verified from the ISRs
(`doEncoderA()` only ever decrements, `doEncoderB()` only ever increments), so
**counts/rev = 2 × slots/rev**.

**Safety consequence — this is why velocity modes are firmware-blocked.** The loop closes on
`v_actual`, so an under-reading feedback makes the PI **over-drive**: it keeps adding current chasing
a setpoint the flywheel has already passed. The new `commandMotorCurrent()` ceiling bounds **amps,
not speed**. With the old broken form the under-read was ~6.6×; with the form corrected but the slot
count still a placeholder it is ~32×. `VELOCITY_CHAIN_CALIBRATED` (default **0**) therefore makes
State 98 refuse `'V'` (manual velocity) and `'D'` (drive cycle) outright. Fixed-current tests (`'A'`)
remain available. **Set the flag to 1 only after measuring both scale constants.**

### VESC-Tool-side, not firmware
| Setting | Status |
|---|---|
| Motor pole count | **[measure]** or resolved by the motor swap (spec motors 2-pole; Castle/AXE 4-pole) |
| Max ERPM cap | Blocked on pole count — **and a weak protection regardless (§4)** |
| Battery Current Max / Regen Max | **≈4.2 A / ≈1.5 A** from §12.4. This is the real bus protection. |
| Gear ratio (9.49:1), wheel diameter (66 mm) | For VESC's own speed/distance reporting only |
| `foc_f_zv` | Already 30 kHz by EDU default, and at the practical ceiling (§4) |

**On the ERPM cap arithmetic:** capping at roughly 2S-equivalent shaft speed means ~27,700 RPM
mechanical, which is 27,700 ERPM on a 2-pole motor and 55,400 ERPM on a 4-pole. That factor of two
is the entire difference between a real limit and no limit, so the pole count must be settled before
the cap means anything — but per §4, even a correct cap does not bound a non-throttle overspeed.

---

## 10. Measurements required

### 🔴 Blocking firmware (do these first — they gate all velocity testing)
- [ ] **Flywheel encoder disc slot count.** Either count the slots directly, or power the board and
      hand-turn the flywheel exactly one revolution and read `encoderPos` (State-98 `'S'` dumps it);
      counts/rev = 2 × slots. → `ENCODER_SLOTS_PER_REV`
- [ ] **What the encoder disc is coupled to** — the wheel/tire, or a separate dyno roller — and its
      effective rolling radius in metres. → `FLYWHEEL_RADIUS_M`
- [ ] **Tire rolling diameter with calipers** (also feeds the VESC wheel-diameter field)
- [ ] Then set `-DVELOCITY_CHAIN_CALIBRATED=1` and calibrate `motorConstant`.

### 🔴 Blocking safety (from `docs/design-review-2026-07-28.md`)
- [ ] Confirm the FC TPS61288 is not shorted and has been replaced if necessary; confirm the FC
      **and** BT local 10 µF + 0.1 µF output-cap bodges
- [ ] DMM-confirm `RD1-FC`, `RD1-BT`, `RC-FC`, `RC-BT` as-built
- [ ] High-bandwidth (10× probe, ground spring) SW/VOUT capture for boost ring margin
- [ ] Correlate `V_rgn` ADC telemetry against V-MOT with a DMM/scope, then calibrate
      `MOT_HOTPLUG_MARGIN`
- [ ] Braking chopper actual trip point (schematic says 22 V, this doc previously said 20 V)

### Drivetrain
- [ ] Pinion tooth count
- [ ] Spur gear tooth count — back out the internal reduction from these plus the stated 9.49
- [ ] Which of the 11 gear-mesh positions is currently used, and travel available each direction

### Motor interface
- [ ] BL-2s shaft diameter (expect 3.17 mm — confirms existing pinion transfers)
- [ ] Shaft protrusion from mounting face (Justock 15 mm, Castle 15 mm, AXE 15.5 mm) — a shorter
      shaft misaligns the pinion relative to the spur
- [ ] Mount hole center-to-center and thread size
- [ ] Mount plate thickness plus screw engagement depth — can depths differ, and a too-long screw
      can bottom out on the stator

### Clearances
- [ ] ~~Available length rearward from mount face~~ — **deprioritized**: this was only needed to keep
      a 3660/3670 open, and §12.4 closes that option. All candidates are ≤ 52.5 mm vs the BL-2s's
      57 mm, so shorter is safe.
- [ ] Radial clearance around the can — **note the BL-2s integrated fan may be what constrains this
      today, not the can itself**
- [ ] Sensor cable exit clearance including connector body and bend radius (nothing occupies this
      space now — easy to overlook)
- [ ] Clearance above the can for a bolt-on cooling fan (Justock and Castle have no integrated fan)

### Motor characterization (decides §8)
- [ ] `measure_ind <duty>` → record `ld_lq_diff` at several duties (decides HFI)
- [ ] **Free-run current vs RPM at 8, 12, 16 V** — this is the dominant cruise load (§12.3) and the
      real motor selection criterion, and no candidate publishes it credibly
- [ ] If Castle: the 3-Hall scope test in §8 before wiring to the VESC
- [ ] **Built vehicle mass on a scale** — §12 needs it and nothing in the repo records it

### Wiring
- [ ] Motor-to-VESC phase lead distance. Replacing the Traxxas quick-connect with bullets anyway —
      make leads **short and equal length**, since added inductance worsens the ripple situation.

---

## 11. Pointers to other open items (non-motor)

Not in scope here, but relevant if firmware work touches the power path. **Status re-verified
2026-07-29.**

- ✅ **DONE — RD1-FC / RD1-BT setpoint solve for 16 V.** Executed in hardware 2026-07-11: RD1 bodged
  237k → 215k on **both** channels, giving V0 = 15.91 V ≈ 16 V. Reflected in firmware
  (`RD1_OVER_RINJ = 215/53.6`, `RE_MAX = 2.014 Ω`, `K_DROOP = 0.30 Ω`). The schematic still shows
  237k. *(Previously listed here as open.)*
- ✅ **DONE — BT output caps.** The actual validated fix is **10 µF + 0.1 µF** ceramics bodged at the
  BT boost output (2026-07-07), confirmed by four consecutive surviving `G` bring-ups. This
  document previously called for "100 nF 50 V X7R 0603", which is only the 0.1 µF half and omits the
  10 µF entirely. **Any future BT boost rework must keep both values.** The firmware delay between
  `BT_BUS_ENABLE` and `BT_REG_ENABLE` — which this document asked to be logged — is
  `BUS_SETTLE_MS = 5 ms`, used by both `doState0()` and State-98 `bringUpBus()`; it is
  `TODO(calibrate)`.
- 🔶 **OPEN — INA253 verification on SNS-BT.** Survived four fault events; verify shunt resistance
  and offset before trusting BT droop telemetry. Nothing in firmware verifies the shunt and there is
  no zero-offset calibration path, so a damaged SNS-BT makes `I_batt` **and the entire droop/share
  loop** silently wrong.
- ✅ **PARTIALLY SUPERSEDED — Ag105 initialization.** The premise here was inverted. The Ag105 is
  **unpowered until a charge path opens** (`chargerHasPower()`), so it cannot ACK I²C *before* charge
  is enabled — configuring it first can never succeed on hardware. The design deliberately opens
  `FC_CHARGE_ENABLE` on *intent* to power the charger, **then** writes config once it ACKs, lazily,
  once per powered session (`ag105Configured`, re-armed on power loss). The "boots to 1S / 4.2 V"
  premise is effectively right but imprecise: it boots to external-resistor mode (reg 0x00 = 0x00),
  which with no RVS/RCS resistors fitted *yields* 4.2 V / 1000 mA.
  **The read-verify recommendation was the one part that was both correct and unimplemented — now
  implemented** (2026-07-29): `ag105WriteConfigRegVerified()` reads the register, skips the write if
  it already matches (no EPROM wear per session), and re-reads to prove the value landed.
- ✅ **DONE — power path sequencing outputs (pins 27–32, RT1987).** This bullet was **flatly wrong**:
  fully implemented since the 2026-06-23 reconciliation. All six enables are defined, defaulted LOW
  in `setup()`, and guarded by `assertFcChargeEnable()`, `busHotPlugUnsafe()`,
  `motPwrHotPlugUnsafe()`, `assertMotPwrEnable()` and `safeAllSwitches()`, with a sequenced
  `doState0()`/`bringUpBus()` bring-up, a phased `doState99()` shutdown, a `switch_state` telemetry
  bitmask and a `FAULT_SWITCH_CONFLICT` check. The independent design review confirms the pin block
  matches the IO CSV row-for-row.
- ✅ **CONFIRMED — BAL-NOK unrouted.** BQ29200 OVP output not tied to any Teensy GPIO; secondary OVP
  is non-functional by design decision. No pin exists; do not add code expecting one.

### Still-open items from the design review that this document had omitted
- 🔴 **State 98 `'G'` runs from any state** (review P0-1) — it can create the IO-CSV-prohibited
  `FC_CHARGE + BT_BUS` combination, and can reconnect a discharged V-MOT at full bus, bypassing the
  Death-5 guard. **Not fixed in this pass.**
- 🔶 **State 98 stop/exit contradicts the motor-node precharge policy** (P1-1). Deliberately left
  open: `haltMotorOutput()` does not touch the power-path switches, so the teardown-vs-precharge
  decision is still the caller's/yours.
- 🔶 **State 98 can command regen without establishing the regen path** (P1-3).
- 🔶 **State 98 boost-enable toggles are not staged** (P1-4).
- 🔶 **`'E'`/`'W'` VESC reads block up to 100–200 ms** while a motor command may be active (P1-6).
- 🔴 **The as-built power stage is not verified** (P0-4), including whether the FC repair and its
  cap bodge are complete. Treat the board itself as the only as-built authority.

---

## 12. Source power budget and motor sizing

**New section, 2026-07-29.** This is what `MOTOR_I_CMD_MAX` and the OC limits are derived from, and
it settles the "is 110 W enough?" question in the previous revision.

### 12.1 The node correction that drives everything

**`I_fc` and `I_batt` are BUS-side (boost-output) currents, not source-input currents.** Verified from
the schematic netlist **[repo]**: `SNS-FC`'s `IS+1/2/3` sit on `VOUT-FC` (the TPS61288 `REG-FC` VOUT
pin) and `IS-1/2/3` on `VBUS-FC` (which feeds `D-FC-EN`'s VIN). Mirrored for `SNS-BT`.

Both overcurrent limits had been set from **source-side** datasheet ratings and compared against
these bus-side measurements, so **neither fault protected its source**:

| Limit | Was | Implied source current | Source rating | Now |
|---|---|---|---|---|
| `LIMIT_I_FC_MAX` | 3.5 A | ~7.7 A from the stack | H-20 ~2.6 A **[web]** | **1.4 A** |
| `LIMIT_I_BT_MAX` | 6.0 A | ~14.1 A from the pack | pack 10 A **[repo]** | **3.0 A** |

The same error made `P_fc_actual` / `P_batt_actual` (source voltage × bus current) neither input nor
output power, under-reporting by ~2×. Both now compute `V_bus × I` = power delivered to the bus.
**The telemetry layout is unchanged but these two values change meaning — update the Pi bridge.**

### 12.2 Source-side budget

Assumptions stated explicitly: η_FC ≈ 0.93, η_BT ≈ 0.92 (TPS61288-class at these ratios,
**not measured on this board**); bus at 16.0 V.

```
FC:  P_stack = 7.8 V × 2.6 A = 20.3 W  →  P_bus = 18.9 W  →  I_bus = 1.18 A
BT:  P_pack  = 7.4 V × 10 A  = 74 W    →  P_bus = 68.1 W  →  I_bus = 4.26 A  (at 8.4 V: 4.83 A)
```

The FC **stack** is the binding element on its channel by ~3× (the boost would pass 3 A). On the BT
channel the binding element is the validated 3 A/channel converter envelope, then the 10 A pack
rating.

| Case | I_bus,FC | I_bus,BT | Total | **P_bus** | Binding element |
|---|---|---|---|---|---|
| **A — bench-validated envelope** | 1.18 A | 3.00 A | 4.18 A | **67 W** | BT converter hot-loop margin (not yet scope-validated) |
| **B — source datasheet ceiling** | 1.18 A | 4.26 A | 5.44 A | **87 W** | 10 A pack rating; 20 W stack |
| C — firmware-permitted **before** this pass | 3.50 A | 6.00 A | 9.50 A | 152 W | *nothing* — both OC limits over-permitted |

Housekeeping is drawn around the boosts, off `VBT` through the LM1084 **linear** regulator:
0.15–0.25 A × 7.4 V ≈ 1.1–1.9 W, plus VESC quiescent, plus the Pi, plus the H-20 blower/purge —
call it **4–8 W off the top**. **Net to the VESC input: ~60 W (case A) to ~80 W (case B).**

> **The H-20 datasheet is not in `references/`.** The 20 W / 7.8 V / 2.6 A figures are externally
> sourced. `LIMIT_I_FC_MAX`'s old comment cited "H-20 datasheet" for a number (3.5 A) that matches
> neither the input rating nor a bus-side referral of it. Get the datasheet and re-derive.

### 12.3 The finding that reframes the whole analysis: free-run loss ≫ traction power

Vehicle demand (m = 2.5 kg design case, C_rr = 0.020, C_dA = 0.010 m², η_dt = 0.85 — all stated
assumptions, see the caveat below):

| v (km/h) | P_wheel | P_shaft | motor rpm |
|---|---|---|---|
| 10 | 1.49 W | 1.75 W | 7,628 |
| 20 | 3.75 W | 4.42 W | 15,256 |
| 30 | 7.56 W | 8.89 W | 22,885 |
| 40 | 13.68 W | 16.10 W | 30,513 |

Rolling resistance dominates below ~30 km/h; aero crosses over around 29 km/h.

**But the Justock G2.1 21.5T is spec'd at 3.0 A no-load** — at ~8.4 V that is ~25 W dissipated at
~17 krpm doing zero useful work. Scaling as rpm^1.5:

| v (km/h) | P_shaft (traction) | P_free-run (if 25 W @ 17 krpm) | **P_bus** |
|---|---|---|---|
| 10 | 1.75 W | 7.4 W | **9.6 W** |
| 20 | 4.42 W | 20.9 W | **26.6 W** |
| 30 | 8.89 W | 38.4 W | **49.7 W** |
| 40 | 16.10 W | 59.1 W | **79.1 W** |

**The motor's own spinning loss is 3–5× the traction power at cruise. It — not aero, not rolling
resistance — sets the vehicle's cruise draw.** Two consequences:

1. **Free-run current at 16 V is the real motor selection criterion**, ahead of power rating. Target
   **≤ 2.5 A**. Favour lower KV: no-load current falls monotonically with turn count across the
   Justock range (21.5T 3.0 A, 17.5T 3.5 A, 13.5T 4.0 A, 10.5T 4.9 A), and the prev-gen G2 21.5T is
   quoted at only **1.3 A**. **[measure]** this — the test voltage behind the "3 A" spec is not
   published.
2. **The H-20's entire 18.9 W bus contribution does not cover the motor's free-run loss at 20 km/h.**
   FC-only cruise is marginal at best; the EMS will be battery-dominated by construction. That is a
   system-level result worth stating in the thesis, and a direct consequence of the 16 V / 9.49:1 /
   high-RPM operating point.

> **Caveat on the vehicle numbers.** Built mass, C_rr and C_dA are all estimates — nothing in the
> repo records vehicle mass (`docs/modeling/bond-graph.md` marks `I:m_veh` as `TODO(calibrate)`), and
> the 2S2P pack's cell type, capacity and C-rate appear nowhere. The 10 A figure is the only pack
> number in the repo. Also note rotating inertia is **not** negligible: the motor rotor reflected
> through 9.49:1 onto a 33 mm radius contributes ~0.45 kg of apparent mass (a ~27% penalty with the
> wheels), dominated by the rotor. Rotor J is **[measure]**.

### 12.4 Verdict: 110 W was the wrong question, and the motor is not the constraint

**"Is 110 W enough?" — yes, overwhelmingly, and it is not the binding constraint.**

The sources ceiling at **67–87 W at the bus**, ~60–80 W at the VESC, **~40–52 W at the wheels**. A
motor that can deliver 110 W mechanical can absorb the entire platform's output and still be loafing.

**Moreover, "110 W max output / 35 A / 0.075 Ω" is a dyno test point, not a capability ceiling.** Back
it out: 110 W / 35 A = 3.14 V of back-EMF; add I·R = 2.63 V → the figure is quoted at a terminal
voltage of **≈5.8 V**, i.e. the peak of the P-out curve at a low fixed test voltage where efficiency
is ~50% by construction. On a 16 V bus the same motor's max-output point is ~468 W mechanical
(thermally unreachable, but it shows the 110 W number carries no information about a 16 V bus). The
real ceilings on a 3650 spec can are **thermal** (~15–20 A continuous with airflow) and **mechanical**
(magnet retention / bearings at 25–33 krpm) — neither of which 110 W describes.

**So: the sources deliver ~60–87 W; every candidate motor could pass 4–7× that. The stack and the
pack are the constraints. Select on KV match, Hall/VESC compatibility, free-run loss, voltage rating
and overspeed — never on power rating.**

**A 3660/3670 is not needed and would be actively worse.** More stator iron and a heavier rotor mean
higher free-run loss (the dominant cruise load) and a larger rotor J, which through the
(9.49/0.033)² ≈ 82,700 reflection multiplier directly inflates apparent mass. Chasing power buys
nothing and costs efficiency and acceleration. **This closes the previous revision's "power ceiling
caveat" and takes the §10 rearward-length measurement off the critical path.**

### What the motor should actually be specified for

| Spec | Value | Basis |
|---|---|---|
| Continuous shaft power | ≥ 20 W | 30 km/h cruise = 8.9 W shaft, ×2 margin |
| Peak shaft power (10 s) | ≥ 70 W | 2 m/s² at 30 km/h = 71 W; capped anyway by the ~52 W the sources can deliver to the wheel |
| Continuous motor current | ≥ 6 A | 2 m/s² at 20 km/h = 5.25 A at KV 1750, + no-load |
| Peak motor current (5 s) | ≥ 15 A | 4 m/s² = 10.0 A + ~3 A no-load + headroom |
| **Free-run current at 16 V, 25–33 krpm** | **≤ 2.5 A — the real criterion** | §12.3 |
| KV | **1600–1750**, favour 1600 | reproduces the 8.4 V / 3300 KV design shaft speed; lower KV → lower loss |
| Voltage rating | 16 V should be **inside** it | §4: the ERPM-cap mitigation is weak |
| Sensor | plain 3-wire Hall (or ROAR port) | §8 |

Every candidate clears the power/current requirements by ≥ 3×.

### Setting `MOTOR_I_CMD_MAX`, and why it does not protect the bus

Motor current maps to bus current as **`I_bus = D · I_mot / η_esc`** — it is *duty-dependent*, which
is why a single motor-current number cannot protect the bus. The bus current a 15 A motor command
actually draws: D = 0.10 → 1.58 A; 0.25 → 3.95 A; 0.50 → 7.89 A; 0.75 → 11.84 A; **0.90 → 14.21 A**.
At high duty a 15 A motor command demands **2.6× the entire source budget**.

1. **`MOTOR_I_CMD_MAX = 30 A` was unsafe** — it exceeds every torque demand computed by ~3× (the
   hardest case, 4 m/s² at KV 1750, needs 10 A) and at high duty would demand ~28 A of bus current
   from a ~4–5 A bus. **Now 5.0 A.**
2. **Bench: 5.0 A.** At KV 1750 that is ~27 mN·m → ~7.8 N at the wheels → ~2.0 m/s² on the ~3.2 kg
   effective mass, and ≤ 4.7 A of bus current even at D = 0.9 — inside already-validated territory
   at any duty. Given `motorConstant` and the velocity chain are still uncalibrated, start here
   regardless.
3. **Vehicle: 15.0 A** once calibrated — covers 4 m/s² at every candidate KV, well under the EDU's
   50 A burst / 25 A continuous. Assumes η_esc 0.95, η_motor 0.80, η_dt 0.85 (bus→wheel 0.646).
4. **Protect the bus in the VESC, not with the motor ceiling.** Set **Battery Current Max = 4.2 A**
   (raise to 5.4 A only after the pack rating and the 3 A/channel envelope are scope-validated) and
   **Battery Current Regen Max ≈ 1.5 A**. This is exactly what the VESC's split motor/battery current
   limits exist for, and it is the only mechanism that bounds bus draw across the whole duty range.

For reference, affordable acceleration given the source ceiling (bus→wheel 0.646):

| P_bus ceiling | 10 km/h | 20 km/h | 30 km/h | 40 km/h |
|---|---|---|---|---|
| 67 W (case A) | 4.8 | **2.3** | 1.4 | 0.8 m/s² |
| 87 W (case B) | 6.2 | **3.0** | 1.8 | 1.2 m/s² |

A fine drive-cycle envelope — but set entirely by the sources, with the motor nowhere near saturated.

### Regen sanity
Braking at −2.0 m/s² from 20 km/h gives ~31 W at the wheel → ~25 W at the bus. The Ag105 at
2.5 A / 8.4 V absorbs ~21 W, so the TL431/BSP170P chopper handles the balance — consistent with the
"Ag105 is the slow secondary harvester" architecture.

---

## 13. Firmware changes made in the 2026-07-29 pass

All in `teensy_controller/teensy_controller.ino`; full detail in the changelog block at the top of
that file. **Tests: 415 production (`-DBENCH_TEST=0`) + 6 bench (`=1`), all passing.**

| Change | Why |
|---|---|
| **`commandMotorCurrent()` chokepoint** — the only caller of `vesc.setCurrent()`. Rejects non-finite (→ 0 A), clamps to ±`MOTOR_I_CMD_MAX`, mirrors the post-clamp value into `current`. | Review P0-3. `MOTOR_I_CMD_MAX` bounded only the PI *integrator*; the proportional term rode through to a 50 A bridge (5 m/s error at `motorConstant` = 0.1 → 50 A). |
| **UDP setpoint sanitization** — non-finite fields hold their previous value; `v_setpoint` clamps to ±`V_SETPOINT_MAX` (20 m/s, new); `power_share_setpoint` to [0,1]. | A bit pattern surviving the XOR checksum can decode as NaN, which permanently poisons the PI integrator. |
| **`haltMotorOutput()` ownership primitive** — used by `'D'` start/stop, `'R'` stop, `'X'`, `'Q'` and both profiles' natural completion. Clears mode, setpoints, `pi_motor_accum`, and flushes 0 A. The drive-cycle branch re-checks `driveCycleActive` before running the control stack. | Review P0-2. `'D'` stop flushed a zero but left `manualMotorMode` set, so the standalone branch reissued the stale manual current **in the same tick**. Natural completion flushed nothing at all, and the caller still ran `motorControl()` — with `v_setpoint` zeroed and the flywheel spinning, that commanded **regen**. |
| **Velocity unit chain corrected** — `v_actual = rpm × RPM_TO_MPS`, `RPM_TO_MPS = (2π/60)·FLYWHEEL_RADIUS_M` (metres). Dead `CPR = 16`, `tireRadius`, `lastEncoderPos` removed; counts/rev derived as slots × ×2 decode. | The old form yielded rev/s·inch. `CPR = 16` actively contradicted `ENCODER_COUNTS_PER_REV = 1024`. |
| **`VELOCITY_CHAIN_CALIBRATED` interlock** (default 0) — State 98 refuses `'V'` and `'D'`. | The form fix alone makes the under-read *worse* (6.6× → 32×) until the slot count is measured, and the current clamp bounds amps, not speed. |
| **OC limits retargeted to the right node** — `LIMIT_I_FC_MAX` 3.5 → 1.4 A, `LIMIT_I_BT_MAX` 6.0 → 3.0 A, `MOTOR_I_CMD_MAX` 30 → 5.0 A. | §12.1–12.4. Neither OC fault protected its source. |
| **`P_fc_actual` / `P_batt_actual` → `V_bus × I`** | They mixed source voltage with bus current. **Pi bridge must be updated** — layout unchanged, values change. |
| **Independent control-loop rate limiting** — `MOTOR_CTRL_PERIOD_US` 2000 (500 Hz), `CHARGING_CTRL_PERIOD_US` 20000 (50 Hz), `POWER_BAL_PERIOD_US` 1000 (1 kHz), each with its own timestamp. Gated wrappers used by `doState2()` and the State-98 drive cycle in the same order as before. The two constant-command keep-alives — `doState1()`'s Idle zero-flush and `applyManualMotor()`'s fixed-current re-send — share the motor gate. Safety flushes (`haltMotorOutput`, State 3, State 99, boot) are **never** gated. | A 9-byte `setCurrent()` frame is 781 µs of wire time and Teensy `write()` blocks on a full TX FIFO, so calling it every tick pinned the loop rate — including `detectFaults()` — and queued superseded commands. `chargingControl()` had no reason to run at the motor rate. 500 Hz is far inside the VESC's 1000 ms command timeout (§7), and that timeout coasts anyway. |
| **Ag105 read-verify-then-write-if-different** — `ag105ReadConfigReg()` / `ag105WriteConfigRegVerified()`. | The blind write returned success on the ACK alone; a write that ACKed but did not land left the charger at its 1S/4.2 V default while the firmware believed it was configured. Also removes an EPROM write per power session. |
| **`I_charge` cleared on charger power loss / I2C failure** | Review P2-1. The Pi saw a positive charge current beside a 0x00 "no data" status byte. |
| **`timeArr[]` retyped to `uint32_t`; incorrect TODO removed; `static_assert` on buffer depth** | The old `int` did **not** corrupt `dt` across a `micros()` wrap (the subtraction promotes bit-preservingly) — the TODO claiming otherwise invited a "fix" to a non-bug. |

**Not fixed in this pass** (listed in §11): review P0-1 (`'G'` from any state), P0-4 (as-built
verification), P1-1, P1-3, P1-4, P1-6.
