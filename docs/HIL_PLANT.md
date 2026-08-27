# HIL plant model — `tools/hil_plant_sim.py` (fw v21)

This is the **plant-side** reference for HIL mode: what the simulator computes, from
which constants, with which simplifications, and how each of its outputs lands in the
firmware. The **link side** — frame byte tables, link-loss staging, host binding,
build flags, the H1–H5 test plan and the mode's limitations — lives in
[`docs/HIL_MODE.md`](HIL_MODE.md) and is not repeated here. Read that first; this
document assumes it.

Everything below is read out of `tools/hil_plant_sim.py`, the HIL blocks of
`teensy_controller/teensy_controller.ino` (the constants block, the `updateSensors()`
HIL branch, the `receiveCommands()` drain and `hilSendTick()`), and the calibration
record in `controller_design_MIMO/calibration/motor_id_20260815.md`. Values that the
source itself does not justify are marked `TODO(verify)` rather than rationalized.

---

## 1. Architectural overview

The simulator is a **soft-real-time Python process that closes a control loop around
the real Teensy**. The board is the device under test; the plant it thinks it is
attached to does not exist. Nothing in the firmware's control logic is stubbed:
`detectFaults()`, the §2 sequencing guards, the Youla drive controller, the power-share
loop and the state machine all run unmodified on injected values. That is what makes
the rig a fault-*injection* rig rather than a demo.

```
        HOST — tools/hil_plant_sim.py                    TEENSY 4.1  (-DHIL_SIM=1 -DUSE_ETHERNET=1)
   ┌────────────────────────────────────────┐        ┌──────────────────────────────────────────┐
   │ Plant.step(dt, obs)                    │        │ receiveCommands()                        │
   │  ├ mechanical integrator  v            │  40 B  │  drain ≤ UDP_DRAIN_MAX_PER_TICK (8)      │
   │  ├ droop bus node        V_bus         │ ─────► │  parse, NaN/Inf reject, host lock,       │
   │  ├ source split          I_fc, I_batt  │  0xB5  │  commit NEWEST accepted frame            │
   │  ├ path rails            V_chg, V_rgn  │  UDP   │            │                             │
   │  └ Ag105 charger model   I_charge,     │  :5001 │            ▼                             │
   │              ag105_status              │        │ updateSensors()  ── HIL branch ──        │
   │            │                           │        │  V_fc V_batt V_bus V_chg V_rgn           │
   │            ▼                           │        │  I_fc I_batt v_actual  ← frame           │
   │  pack_inject(seq, 7 rails + v_actual   │        │  (engineering units; no SCALE_*;         │
   │      + I_charge + ag105_status)        │        │   updateWheelSpeed() SKIPPED)             │
   │                                        │        │ pollAg105()  ── HIL branch ──             │
   │                                        │        │  I_charge, ag105_status  ← frame          │
   │                                        │        │  (no I2C; chargerHasPower() still real)  │
   │                                        │        │            │                             │
   │                                        │        │            ▼                             │
   │                                        │        │ computeDerivedSignals()                  │
   │                                        │        │ detectFaults()          ← UNMODIFIED     │
   │                                        │        │ state machine 0/1/2/3/98/99              │
   │                                        │        │ motorControl()  powerBalance()           │
   │                                        │        │ chargingControl()  sequencing guards      │
   │                                        │        │   → digitalWrite()                        │
   │  parse_output() → obs                  │  16 B  │ setDroopMdac() → mdacLastCode{FC,BT}     │
   │  ◄──────────────────────────────────── │ ◄───── │            │                             │
   │  switch bits, aux bits, I_cmd,         │  0xB6  │            ▼                             │
   │  MDAC words, fault_flags, state        │  1 kHz │ hilSendTick()  (readSwitchState(),       │
   │            └── actuator inputs ────────┘        │   readHilAuxState(), current, faults)    │
   └────────────────────────────────────────┘        └──────────────────────────────────────────┘
```

**What is real:** the firmware binary, its control laws, its fault detection and dwell
filters, its switch sequencing and guards, its I2C/SPI/serial peripherals, its SD
logging, its UDP stack, and the Teensy's own timing.

**What is simulated:** the mechanics (one translational state, `v`), the bus node and
its two sources, and the charger/regen path *voltages*. Nothing else.

**Where the boundary sits:** at **engineering-unit signal injection**. The frame carries
volts, amps and m/s — not ADC counts. Consequently the ADC front ends, the dividers,
the `SCALE_*` constants, the INA253 sense chain, the RT1987 controllers, the boosts and
the encoder estimator are all *bypassed*, not modelled. This is signal-level
controller-HIL, not power-HIL: a green HIL run says the firmware logic is right, not
that the board is.

One boundary detail worth stating precisely: `updateSensors()`'s HIL branch **returns
before `updateWheelSpeed()`**, so `v_actual` has exactly one writer (the frame). The
encoder ISRs may still fire; they move `encoderPos` and the diagnostic counters only,
which no control path reads. The wrap-guard invariant this creates is documented at
both sites in the firmware and must be restored by any future "fall back to real
sensors mid-run" feature.

---

## 2. The real-time loop

The host loop is one flat `while` at `--rate` (default 1000 Hz, `dt = 1/rate`):

| Step | Behaviour |
|---|---|
| Receive | Non-blocking `recvfrom` **drained to empty**; every frame is validated by `parse_output()`; malformed frames increment `rx_bad`. The **newest** valid frame becomes `obs` — an observation is a state snapshot, not an event, so older queued frames are simply superseded. |
| Scenario | `apply_scenario(plant, scenario, t)` mutates the plant for this tick and returns the transmit-enable flag. The flag is recomputed statelessly from `t` every tick — it is a return value, never latched. |
| Integrate | `plant.step(dt, obs)` — one explicit-Euler tick (§3, §4). With `obs is None` (no frame received yet) the actuators default to all-off, `i_cmd = 0`, and both MDAC fractions to 0.5. |
| Transmit | `pack_inject()` → one 40-byte datagram to `--teensy-ip:--port`; `seq` increments **only on a transmitted tick**. |
| Log | One CSV row (§7). |
| Status | A 1 Hz line (§7). |
| Schedule | Drift-corrected: `next_tick += dt`; `sleep(slack)` when ahead; when behind, accumulate `max_overrun`, and if a single overrun exceeds **0.25 s** resynchronize `next_tick` to now rather than spinning through a burst of catch-up ticks the plant cannot honour. |

At exit the simulator prints ticks, elapsed, **achieved rate**, **max overrun**, and the
tx/rx/malformed counts. Those numbers are the run's validity statement — read them
before trusting any timing-sensitive result.

**Soft vs hard real time.** An RTDS-class simulator guarantees a deterministic step
deadline; CPython on a general-purpose OS does not. A late tick here integrates the same
`dt` at a later wall-clock instant, so the plant's *time base* stretches locally while its
*dynamics* stay nominal, and the firmware — which timestamps everything off its own
`millis()`/`micros()` — sees the plant's state arrive late rather than wrong. The
firmware's link-loss staging (`HIL_STALE_MS` 50 ms hold, `HIL_ZERO_MS` 250 ms zero) exists
precisely to absorb this class of artefact without faulting on it.

**Why 1 kHz is enough for this plant.** Every dynamic in the model is far slower than the
tick:

| Timescale | Value | Source |
|---|---|---|
| Drive-loop crossover | ≈ 17.25 rad/s (≈ 2.7 Hz) | fw v18 re-synthesis, CLAUDE.md fw v18 addendum |
| Drive controller update | 500 Hz (`DRIVE_CTRL_TS_US`) | `drive_controller.h` |
| Mechanical pole | −0.1526 rad/s (`−b_eff/m_eff`) | fw v14 addendum |
| Bus decay when dark | τ = `R_BUS_BLEED·C_BUS_F` = 0.94 s | §4 |
| Injection tick | 1 ms | this loop |

The fastest modelled pole is the 0.94 s bus decay; the fastest *consumer* is the 500 Hz
controller. A 1 ms explicit-Euler step is one to three decades inside both, so the
integration error is negligible compared with the model's structural simplifications
(§4). What 1 kHz does **not** cover is anything the model omits — converter switching,
RT1987 turn-on, encoder edges — and those are omitted by design, not by rate.

---

## 3. Mechanical model

One state, `v` (m/s), interpreted as **flywheel surface speed** — the same terms as
`v_setpoint`, the `'V'`/`'D'`/`'Y'` commands and the BLG `v_sp`/`v_act` columns.

```
    m_eff · dv/dt  =  K_F · I_cmd  −  sign(v) · F_c  −  b_eff · v
```

### 3.1 Constants and provenance

| Constant | Value | Meaning | Provenance |
|---|---|---|---|
| `M_EFF` | 3.5 kg | effective translational mass at the flywheel rim | Direct flywheel-J measurement; **confirmed** by the fw v14 K_F correction round (all three contradicting inference paths close on 3.5 kg once the force axis is corrected) — `motor_id_20260815.md` §"m_eff ruling" + §"K_F force-axis correction (2026-08-16c)" |
| `K_F` | 0.7538 N/A | motor current → tractive force | fw v14 corrected force axis: gear ratio **PHI 6.86** (fitted 29T/70T, triple-confirmed) and force radius **r_tire 0.033 m** (torque reaches the road through the tire; the encoder and inertia belong to the flywheel). Supersedes the retired 0.4516 N/A (×1.669). |
| `F_COULOMB` | 2.00 N | thermal Coulomb friction | fw v14 rescale of the unchanged hold-current data: 2.00 ± 0.42 N (cold 2.19, warm 1.75–1.84) |
| `B_EFF` | 0.534 N·s/m | viscous drag | fw v14 rescale of the retired 0.32 N·s/m |
| `V_STICTION` | 0.02 m/s | static-friction band half-width | Simulator-local numerical parameter — **`TODO(verify)`**: not traceable to a calibration record; see §3.2 |

The drag law these three imply, `i(v) = (F_c + b_eff·v)/K_F`, was validated on hardware
in the fw v14 first-flash log round (holds at 0.89–0.92× prediction across 0.5–2.66 m/s;
rail-acceleration check `a_meas/a_model` = 0.968).

⚠️ **Do not re-fit any pre-v14 force-axis numbers against this model.** Retired values
(`K_F` 0.4516, `b_eff` 0.32, `F_c` 1.2, `K_v` 1.25) appear throughout the older sections
of the calibration record and are explicitly bannered there.

### 3.2 Stiction deadband and the zero-crossing guard

Two numerical protections surround `v = 0`, both aimed at the same failure of a naive
`sign(v)·F_c` term: a Coulomb force that is constant in magnitude will, at small `|v|`,
push the state across zero within one tick and then reverse and push it back — a
1 kHz chatter that is an artefact of the discretization, not of friction.

- **Deadband (`|v| < V_STICTION`).** The Coulomb term is treated as *static*. If
  `|K_F·I_cmd| ≤ F_c` the net force is zeroed **and `v` is snapped to exactly 0.0** —
  the body stays put until the drive force breaks it away. Above that threshold the
  ordinary dynamic expression resumes with the friction sign taken from the drive force.
  Breakaway therefore requires `|I_cmd| > F_c/K_F` ≈ **2.65 A**, which is a real,
  observable property of the rig and not merely a numerical convenience.
- **Zero-crossing guard (`|v| ≥ V_STICTION`).** A trial step `v_try = v + (f_net/m)·dt`
  is computed; if the drive force is exactly zero **and** `v_try` has flipped sign, the
  state is set to 0 and the net force to 0. Friction alone can bring the body to rest but
  never past rest within a tick. Note the guard is deliberately conditioned on
  `f_drive == 0.0`: with drive applied, a genuine commanded reversal must be allowed
  through.

### 3.3 Motor-force gating

`f_drive = K_F · i_cmd` is developed **only when `MOT_PWR_ENABLE` is closed AND the bus
is up**, where "up" is `v_bus > 5.0 V`. A VESC with no bus makes no torque, so a firmware
bug that commands current into an unpowered motor path produces no motion here — which
is the correct observable. With either condition false, `f_drive = 0.0`, and the body
coasts down under friction alone (and the zero-crossing guard applies).

### 3.4 The regen floor

Motor bus draw is computed from `p_mech = max(0.0, f_drive · v)` — **mechanical power is
floored at zero**. This is a modelling decision, not an oversight: on this rig the VESC's
Battery Regen Max setting (1.5 A) is a **torque clip, not a dump path** — the 2026-08-17b
log round found only ~6 % of a −12 A commanded regen actually delivered, with the excess
energy remaining kinetic and the surplus appearing on `V_rgn` at the TL431/BSP170P chopper
clamp rather than on the bus. Modelling regen as negative bus current would therefore be
*less* faithful than flooring it. The consequence, stated plainly: **no HIL run returns
energy to the bus**, so nothing here exercises a regen-driven bus rise, and the charger
path sees no regen energy either (§4.5).

---

## 4. Electrical model

Deliberately simple, and simplified in named places. The whole electrical section is
algebraic except for the dark-bus decay.

### 4.1 Source liveness

```
    fc_live  =  (switch & SW_FC_BUS)  AND  (aux & AUX_FC_REG)
    bt_live  =  (switch & SW_BT_BUS)  AND  (aux & AUX_BT_REG)
    mot_live =  (switch & SW_MOT_PWR)
```

Both conditions are required per source: the ideal-diode bus switch closed **and** that
channel's boost regulator enabled. This is what makes the §2 sequencing rules observable
— a source whose `*_BUS_ENABLE` is high but whose `*_REG_ENABLE` is low contributes
nothing, exactly as on the board.

### 4.2 The bus node

With at least one live source, the bus is a single droop node:

```
    V_bus = V_BUS_NOMINAL − K_DROOP_BUS · I_total + v_bus_offset
```

| Constant | Value | Provenance |
|---|---|---|
| `V_BUS_NOMINAL` | 16.0 V | The firmware's own `V_BUS_NOMINAL` (post-2026-07-11 RD1 = 215 k FB retune; measured no-load 15.9 V). The pre-retune 17.5 V figure is stale. |
| `K_DROOP_BUS` | 0.35 V/A | Aggregate, source-agnostic. The script labels it **"bench-plausible"**. It is *not* the firmware's per-channel `K_DROOP` (0.30 Ω, itself `TODO(calibrate)`). **`TODO(verify)`** — no measurement backs 0.35 V/A. |
| `v_bus_offset` | scenario-driven | 0 except during `sag` (§6) |

With **no** live source the node is not forced to zero — it decays as an RC through the
bulk capacitance:

```
    tau = R_BUS_BLEED · C_BUS_F = 2000 Ω · 470 µF = 0.94 s
    V_bus += (−V_bus / tau) · dt
```

`C_BUS_F` = 470 µF matches the board's bulk capacitance as referenced throughout the
bring-up record. `R_BUS_BLEED` = 2 kΩ is described as an *effective* bleed —
**`TODO(verify)`**, no schematic reference is cited for it. The decay matters mostly for
teardown/State-99 traces, where it keeps `V_bus` falling smoothly instead of stepping,
and it interacts with the 5 V `bus_up` threshold in §3.3. `V_bus` is finally clamped at
`max(0.0, ·)`.

### 4.3 Loads

```
    i_motor = p_mech / (ETA_BOOST · V_bus)     when mot_live and V_bus > 1.0 V, else 0
    I_total = i_motor + i_aux
```

`ETA_BOOST` = 0.85 is the boost-stage efficiency applied to convert mechanical power to
bus current. **`TODO(verify)`** — the value coincides numerically with the drive-train
`η_dt` = 0.85 that the calibration record carries as `TODO(calibrate)`, but the simulator
names it as a converter efficiency, and no source in the repo measures either. The
`V_bus > 1.0 V` guard is a division safeguard, distinct from the 5 V `bus_up` torque gate.

`i_aux` = `I_AUX_A` = 0.15 A is a fixed housekeeping load, raised by the `step-load`
scenario. **`TODO(verify)`** — no measurement cited.

### 4.4 The FC/BT split

When both sources are live, the split follows the ratio of the two droop MDAC codes
recovered from the observation frame:

```
    frac_fc = code_fc / (code_fc + code_bt)          (0.5 if the denominator underflows)
    I_fc    = I_total · frac_fc
    I_batt  = I_total · (1 − frac_fc)
```

With exactly one source live the split degenerates to 1.0 / 0.0 as appropriate; with
none, both currents are zero.

This is **the** named simplification of the electrical model. On the real board the split
is set by the analog droop network's equivalent resistances, which the MDAC codes only
*parametrize*; proportional-to-code preserves the **sign and monotonicity** of the share
loop's authority — raise the FC code, get more FC current — without claiming the true
gain. It is therefore adequate to test that the share loop *closes in the right
direction*, that its cutoff/governor logic fires, and that its MDAC writes reach the
chokepoint. It is **not** adequate to tune share-loop gains, and the plant it implies is
not the plant `controller_design/system_model.md` synthesizes against.

### 4.5 Source terminals and path rails

```
    V_fc   = max(0, V_FC_OPEN − R_FC_INT · I_fc)      13.0 V, 0.45 Ω
    V_batt = max(0, V_BT_OPEN − R_BT_INT · I_batt)     8.0 V, 0.05 Ω
    V_chg  = V_bus if (switch & SW_FC_CHARGE) else 0
    V_rgn  = V_bus if (switch & SW_REGEN)     else 0
```

`V_FC_OPEN` 13.0 V is the H-20 fuel cell's open-circuit class (the firmware's
`LIMIT_V_FC_MIN` is 6.0 V); `V_BT_OPEN` 8.0 V is a 2S LiPo at mid-charge, inside the
7.4–8.4 V operating window (firmware `LIMIT_V_BATT_MIN` 6.2 V). The two internal
resistances are plausible source impedances — **`TODO(verify)`**, neither is measured in
the repo, and the 2026-08-17b addendum records that the bench supplies were *swapped*
mid-campaign, so no logged stiffness figure is a stable reference for them either.

The charger and regen rails are pure mirrors of the bus, gated by their path switches.
That is enough to make the §2 mutual-exclusion sequencing visible in the CSV, and it is
all the model claims for the rails themselves — the charger *behind* those rails is
modelled separately, next.

### 4.6 The Ag105 charger model

Unlike the electrical sections above, the charger is modelled at the **status level**,
mirroring `pollAg105()`'s HIL branch in the firmware (which injects `I_charge` and
`ag105_status` directly and skips I2C entirely, while still reading `chargerHasPower()`
from the real switch pins — the sequencing under test is the firmware's own, not the
host's).

```
    chg_path    = (switch & SW_FC_CHARGE) or ((switch & SW_REGEN) and (switch & SW_MOT_PWR))
    v_chg_in    = V_chg if (switch & SW_FC_CHARGE) else V_rgn
    chg_powered = chg_path and v_chg_in >= AG105_V_IN_MIN
```

`chg_path` mirrors the firmware's own `chargerHasPower()` gate exactly (`FC_CHARGE_ENABLE`
high, or `REGEN_ENABLE` and `MOT_PWR_ENABLE` both high). `AG105_V_IN_MIN` = 8.0 V is a
**plant-only refinement on top of that gate** — a closed path switch onto a collapsed bus
still cannot charge a real module, and `chargerHasPower()` itself has no rail-voltage term
to mirror; this floor is not present in firmware, only in the simulated physics.
**`TODO(verify)`** — no datasheet or bench figure backs 8.0 V specifically.

State machine, driven by `chg_powered` and a `chg_powered_s` timer that resets to 0 the
instant power is lost:

| Condition | `I_charge` | `ag105_status` |
|---|---|---|
| `chg_powered` false | 0.0 A (decays to 0 no ramp) | `AG105_ST_DISCONNECT` (0x00) — matches what the firmware's own failed-read path leaves behind |
| `chg_powered` true, `chg_powered_s < AG105_SETTLE_S` | 0.0 A | `AG105_ST_BRINGUP` (0x04, GENSTAT 100) |
| `chg_powered` true, settled | first-order ramp toward `AG105_I_MAX` with time constant `AG105_TAU_S` | `AG105_ST_CHARGING \| AG105_FLAG_CC` (0x42), plus `AG105_FLAG_MPPT_EN \| AG105_FLAG_PWR_TRACK` (0x18) **only while `MPPT_DISABLE` reads HIGH** (aux bit2 set) |

| Constant | Value | Provenance |
|---|---|---|
| `AG105_SETTLE_S` | 0.5 s | Matches the firmware's own `AG105_SETTLE_MS` (500, `TODO(calibrate)` in the `.ino`) — the bring-up window before `ag105Configured` is trusted. |
| `AG105_TAU_S` | 0.4 s | Simulator-local numerical parameter — **`TODO(verify)`**, no bench figure backs the ramp rate. |
| `AG105_I_MAX` | 2.5 A | The firmware's own configured charge-current ceiling (reg `0x00` = `0x01`, `Ag105_Table4_Charge_Current_Select.json`). |
| `AG105_V_IN_MIN` | 8.0 V | Plant-only input-rail floor — see above. **`TODO(verify)`**. |

`MPPT_DISABLE` is active-low on the real hardware (LOW inhibits the MPPT perturb-and-
observe loop, HIGH releases it — CLAUDE.md §3); the model reproduces only that polarity's
effect on the two tracking flags in the status byte. Charging itself continues regardless
of the pin state, matching the firmware's own rationale for asserting it during regen
(the fast TL431/BSP170P chopper, not the Ag105, absorbs the transient — see §3.4). There
is **no battery state of charge and no CV taper**, so the model never reaches
`AG105_ST_FULL`, and there is no simulated MPPT perturb-and-observe loop or I2C transport
— the config handshake (reg `0x01`=0x08, reg `0x00`=0x01) is not modelled at all, because
the firmware's HIL branch skips it entirely and just injects the resulting numbers.

### 4.7 Simplifications and their consequences

| Simplification | Consequence |
|---|---|
| **No boost-converter dynamics.** The bus is algebraic in `I_total`; there is no voltage loop, no RHP zero, no compensator lag. | Nothing here reproduces the boost-death class of failure, the τ_r lag the share-loop plant is built on, or a converter's transient response. Do not fit `τ_r` or any converter parameter against a HIL trace. |
| **No RT1987 turn-on transient.** A switch bit change takes effect within the same tick. | The *ordering* of switch operations is fully observable at 1 ms; the *hot-plug energy* that killed a boost (Death 5) is not modelled at all. A HIL pass says the sequencing logic is right, not that a real closure would be survivable. |
| **Split proportional to MDAC code ratio.** Sign- and monotonicity-preserving, wrong gain. | Share-loop *logic* testable; share-loop *tuning* not. |
| **Regen floored at zero (§3.4).** | No bus rise under braking, so the `REGEN_ENABLE`+`MOT_PWR_ENABLE` charger-power path (§4.6) can be exercised, but never with genuine regen energy behind it; no `V_rgn` excursion beyond the bus value, so the chopper clamp behaviour seen in the bench logs cannot appear. |
| **Charger status-level only, no SoC/CV/MPPT-loop.** `I_charge` and `ag105_status` are now injected (§4.6), so `chargingControl()`'s readiness gating and the GENSTAT fault check are live and testable — but there is no battery state of charge, no CV taper, no simulated MPPT perturb-and-observe behaviour, and the I2C transport/config handshake are not modelled at all. | Sequencing and status-decode logic around the charger are meaningful HIL results; charger *tuning* or *energy* behaviour is not. |
| **Single lumped bus node.** No wiring impedance, no per-source bus segment, no capacitance between nodes. | Handoff-gap phenomena of the TP0178 class (a source dropping out and the other ideal diode picking up only reactively) are not reproduced faithfully; the split here is instantaneous. |
| **No sensor noise, no quantization, no ADC path.** | Steady-state error in a HIL drive run validates the loop's *structure*, not its noise rejection. There is no encoder jitter, so the current-side chatter seen on the bench cannot appear. |

---

## 5. Actuator inputs — what the plant consumes

Everything the plant reads about the board comes from the 16-byte observation frame,
decoded by `parse_output()` (which validates length, sync `0xB6` and the XOR span over
bytes 1–14, returning `None` on any failure).

| Frame field | Plant use |
|---|---|
| `switch` bit `SW_FC_BUS` (0x01) | with `AUX_FC_REG` → `fc_live` (§4.1) |
| `switch` bit `SW_BT_BUS` (0x02) | with `AUX_BT_REG` → `bt_live` |
| `switch` bit `SW_MOT_PWR` (0x04) | `mot_live` → gates motor force (§3.3) and motor bus draw (§4.3) |
| `switch` bit `SW_REGEN` (0x08) | `V_rgn` = `V_bus`, else 0 |
| `switch` bit `SW_FC_CHARGE` (0x10) | `V_chg` = `V_bus`, else 0 |
| `switch` bit `SW_BT_SEQ` (0x20) | **logged only** — the pack sequencing switch has no modelled effect |
| `aux` bit0 `FC_REG_ENABLE`, bit1 `BT_REG_ENABLE` | source liveness (§4.1) |
| `aux` bit2 `MPPT_DISABLE` | drives the two Ag105 tracking flags in the injected status byte (§4.6) while charging |
| `aux` bit3 `CBAL_DISABLE` | **logged only** — the balancer is not modelled |
| `current` (float32, **post-clamp**) | `i_cmd` → `f_drive = K_F·i_cmd` (§3.3). Post-clamp means the ±`MOTOR_I_CMD_MAX` (12 A) limiter has already been applied by the firmware; the plant sees exactly what the VESC would be told. |
| `mdac_fc`, `mdac_bt` (raw AD5443 words) | `mdac_fraction()` — validates the `0x1000` load-and-update control nibble and returns `(word & 0x0FFF)/4095`; a word with a different nibble returns 0.0. Feeds the split (§4.4). Mirrors captured at the firmware's single `setDroopMdac()` SPI chokepoint, because the AD5443 has no readback path. |
| `state`, `fault_flags` | **logged and printed only** — never fed back into the model. The plant does not change behaviour because the board faulted; that asymmetry is deliberate, so a fault's *plant-side* consequences remain whatever the switch bits say. |
| `seq` echo | logged; round-trip correlation (§7) |

**Before the first observation frame** (`obs is None`) the plant assumes all switches and
aux bits low, `i_cmd = 0`, and **both MDAC fractions 0.5** — a neutral split, chosen so
the pre-lock ticks cannot bias an early trace toward either source.

---

## 6. Scenarios

Selected with `--scenario`; `apply_scenario()` is re-evaluated every tick from `t`.

| Scenario | Perturbation | Firmware path exercised | Expected observable |
|---|---|---|---|
| `steady` | `i_aux` held at 0.15 A | quiescent baseline: bring-up, Idle, telemetry, the link itself | `V_bus` ≈ 16.0 − 0.35·`I_total`; `fault_flags == 0`; observation `state` settles at 1 (Idle); simulator rx rate ≈ 1 kHz. This is H1. |
| `step-load` | `i_aux` → 0.15 + **1.2 A** at t = 5 s (step, held) | share loop's disturbance rejection: `I_total` steps, both source currents rise, the droop node sags by 0.35·1.2 ≈ **0.42 V** | Share loop moves the MDAC codes to restore `power_share_actual` toward its setpoint; the split ratio visibly tracks. Note §4.4 — the *direction* is meaningful, the *gain* is not. |
| `sag` | `v_bus_offset` = **−5.0 V** for `5.0 ≤ t < 6.0` s | the **real** undervoltage path: `LIMIT_V_BUS_MIN` 12.0 V with the `UV_BUS_DWELL_*` leaky-integrator filter (`UV_BUS_DWELL_LATCH_MS` 20 ms net dwell to latch) | ≈ 16 − 5 ≈ 11 V, ~1 V under the limit, for 1 s — far past the 20 ms dwell. Expect `mainState` → **99**, the UV bit latched in `fault_flags`, and the switch bitmask going to the State-99 safe combination. Crucially, **no fault before the dwell elapses**. This is H2. Requires the bus to be armed (`uvBusArmed`), i.e. the bring-up must have reached `V_BUS_CHARGED_THRESH` first. |
| `comm-loss` | transmit suppressed for `5.0 ≤ t < 6.0` s; the plant keeps integrating and logging | the two-stage hold-then-zero in `updateSensors()` | ≤ 50 ms: unchanged. 50–250 ms: values **held**, `hilStale` set, and on the **stale entry edge** `haltMotorOutput()` stands the actuator down (setpoint zeroed, Youla state reset, 0 A sent) — the sensors stay held so a missed tick cannot latch a bogus UV fault. > 250 ms: all seven rails and `v_actual` forced to zero, host unbound, and `triggerFault(FAULT_HIL_LINK, ERR_HIL_STALE)` latched — `ERR_HIL_STALE` = 0x10 disambiguates the deliberate `FAULT_PI_TIMEOUT` bit alias. On resume the link re-locks and the accept count resumes. This is H3. |
| `drive` | none; `i_aux` at nominal | whatever the operator commands over USB serial (`'V'`, `'D'`, `'Y'`, `'W'`, State-98 generally) | The plant just stays honest underneath a hand-driven run. `v_actual` in the CSV should converge on the setpoint with no sustained ±12 A rail chatter; `current` should show the Hanus-conditioned ramp and release. This is H4 — and since the model has no encoder noise, it validates the loop's *structure*, not its tuning. |

Three scenario notes. First, `sag` injects an **offset on the bus node**, not a source
failure — `V_fc` and `V_batt` are unaffected, so it is an isolated bus-UV stimulus rather
than a source-dropout stimulus. Second, `comm-loss` is the only scenario that touches the
transmit gate; all others return `tx_enabled = True` unconditionally. Third, `sag` is an
**incidental** charger stimulus too, not a dedicated one: if `FC_CHARGE_ENABLE` happens to
be closed when the offset lands, `V_chg` sags with the bus and can cross below
`AG105_V_IN_MIN` (§4.6), dropping `chg_powered` and resetting the settle timer — worth
watching for in a `sag` trace that also has the charger path open, but not something the
scenario was built to isolate.

---

## 7. Data capture

### 7.1 CSV schema (`--csv`)

One row per tick, 19 columns:

| Column | Source | Notes |
|---|---|---|
| `t` | `monotonic() − t0`, 6 dp | seconds since loop start, **not** session-absolute |
| `seq` | `sent_seq` | the seq **actually transmitted this tick** — deliberately logged pre-increment, so a row matches the frame it describes and the firmware's echo. **Blank on a non-transmitting tick** (`comm-loss`). |
| `V_fc`, `V_batt`, `V_bus`, `V_chg`, `V_rgn` | plant, 4 dp | volts, injected this tick |
| `I_fc`, `I_batt` | plant, 4 dp | amps |
| `v_actual` | plant, 5 dp | m/s, flywheel surface speed |
| `I_charge` | plant, 4 dp | amps, simulated Ag105 charge current (§4.6) |
| `ag105_status` | plant | raw Table 6 status byte, hex-formatted (`0xNN`) |
| `state`, `switch`, `aux` | last `obs` | **blank until the first observation frame arrives** |
| `current` | last `obs`, 4 dp | post-clamp commanded motor current, A |
| `mdac_fc`, `mdac_bt` | last `obs` | raw 16-bit words; apply `mdac_fraction()` offline to get 0..1 |
| `fault_flags` | last `obs` | uint16 |

Two properties of the actuator columns to keep in mind when analysing: they are the
**last received** observation, not a per-tick fresh one (at 1 kHz both ways they are
typically one tick old, but a host stall re-uses the same row values), and they are
**blank, not zero**, before the first frame — a blank means "unknown", a 0 means "the
board reported 0".

### 7.2 Status line

At 1 Hz the simulator prints board state, switch and aux bytes in hex, `I_cmd`,
`fault_flags`, and the plant's `v`, `V_bus`, `I_fc`, `I_batt`, `I_charge` and
`ag105_status` (as `I_chg=`/`chg=0x..`). Before any observation frame arrives it prints
the tx count and the "is the board flashed with `-DHIL_SIM=1`?" prompt instead — which is
the fastest way to catch a wrong-flag flash or a wrong IP.

### 7.3 Correlating with the board-side BLG log

A HIL run produces two logs: the host CSV and the board's ordinary SD `.BLG`. They line
up through two markers:

- **`flags` bit6 (`0x40`) is set on every BLG record** under a `HIL_SIM=1` build, so a
  decoded run declares that its sensor columns are simulated rather than measured. Record
  size and header are unchanged (BLG stays v7). *Known tooling gap:*
  `tools/decode_benchlog.py` does not yet surface this bit — it passes the flags byte
  through raw, so the check is currently manual.
- **The `seq` echo** in the observation frame is the last *accepted* injection seq, which
  gives a direct round-trip alignment between a CSV row and the board's response to it,
  and a latency measure as a by-product.

Beyond those, the usual conventions apply: the BLG time axis is session-absolute while
the CSV `t` starts at zero, so align on an event (bring-up, the sag edge, a profile start)
rather than on raw timestamps.

---

## 8. Fidelity boundaries and extension roadmap

### 8.1 Validity envelope

The model is trustworthy for:

- **Sequencing and guard logic** — switch ordering at 1 ms resolution, `assertFcChargeEnable()`
  mutual exclusion, State-99 teardown order, the bring-up staging.
- **Fault logic** — threshold crossings, dwell filters, arming conditions, latching, error-code
  attribution. This is the rig's strongest suit, because the stimulus is exact.
- **Link and protocol behaviour** — drain bounds, host locking, frame rejection, the
  hold-then-zero staging, telemetry/command coexistence on one socket.
- **Control-loop structure** — that the drive controller converges, that anti-windup releases
  cleanly, that the share loop moves the codes in the right direction.
- **Charger sequencing and status decode** — `chargerHasPower()` gating, the settle-window
  bring-up, and `detectFaults()`'s GENSTAT check against an injected `ag105_status` (§4.6).

It is **not** trustworthy for: control gains of any kind, converter behaviour, hot-plug
energy, regen energetics, charger *tuning* or *energy* behaviour (no SoC, no CV taper, no
simulated MPPT loop — §4.6), encoder/estimator behaviour, sensor noise, electrical margins,
or anything the board's analog front end does. The constants marked `TODO(verify)` in
§3–§4 (`V_STICTION`, `K_DROOP_BUS`, `R_BUS_BLEED`, `ETA_BOOST`, `I_AUX_A`, `R_FC_INT`,
`R_BT_INT`, plus `AG105_TAU_S` and `AG105_V_IN_MIN` from §4.6) bound the electrical
model's quantitative claims further: the *shapes* are right, the *magnitudes* are
plausible rather than measured.

### 8.2 Flagged follow-ups

| Item | Scope |
|---|---|
| **`--replay` mode** | Feed decoded BLG runs back as injection frames, turning recorded bench incidents (the ML0151 drag event, the TP0178 handoff sag, the VESC reversal dead window) into repeatable regression stimuli against the firmware. **In progress** as of this writing — a parallel change to the Ag105/`I_charge` injection work this document describes. |
| **Richer electrical model** | Boost voltage-loop lag (the `τ_r` lump), an RT1987 turn-on ramp, per-source bus segments, and a split derived from the droop network's equivalent resistances rather than the raw code ratio. Each would extend the validity envelope in §8.1 by exactly one row. |
| **Measured electrical constants** | Close the `TODO(verify)` list — most cheaply `K_DROOP_BUS` and `I_AUX_A`, both directly observable on a healthy bench run; `AG105_TAU_S` and `AG105_V_IN_MIN` (§4.6) need a bench charge cycle instead. |
| **Decoder bit6 label** | `tools/decode_benchlog.py` should name the HIL provenance bit so a simulated run cannot be mistaken for a measured one downstream. |
| **Battery state of charge / CV taper / MPPT loop** | The Ag105 model (§4.6) is status-level only; a stateful SoC model would let `AG105_ST_FULL` and a genuine CV taper appear in a HIL run. |
