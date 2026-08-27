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
    k     = K_DROOP_BUS_SHARED  if both sources live, else K_DROOP_BUS_SINGLE
    V_bus = V_BUS_DROOP_V0 − k · I_total + v_bus_offset
```

The droop is now **measured, and mode-aware**. The old single source-agnostic
`K_DROOP_BUS = 0.35 V/A` placeholder is retired.

| Constant | Value | Provenance |
|---|---|---|
| `V_BUS_NOMINAL` | 16.0 V | The firmware's own `V_BUS_NOMINAL` (post-2026-07-11 RD1 = 215 k FB retune). Kept **for reference only** — the droop law now uses the measured intercept below. |
| `V_BUS_DROOP_V0` | 15.95 V | **Measured** no-load intercept. The per-log fits land in 15.943–15.957 V. |
| `K_DROOP_BUS_SHARED` | 0.074 ± 0.004 V/A | **Measured**, both sources live. |
| `K_DROOP_BUS_SINGLE` | 0.1615 ± 0.001 V/A | **Measured**, exactly one source live. FC-only and BT-only agree within 2 %. |
| `v_bus_offset` | scenario-driven | 0 except during `sag` (§6) |

**Fit provenance.** `V_bus` regressed against `I_fc + I_batt` over quasi-steady 200 ms
blocks of **TP0170–0180** (with **TP0178 excluded** — that is the handoff-sag log, not a
steady operating point), **ML0165** and **ML0169**, all fw v16.

> **⚠ OPEN FINDING — the realized droop is ~4× BELOW the design value, and this is not
> hidden.** The MDAC droop chain predicts a per-channel Thevenin resistance
> `R_e = RE_MAX · g = 2.014 Ω × 0.298 = 0.60 Ω`, i.e. **0.30 V/A** with both channels
> sharing — four times the measured 0.074 V/A. Nothing in the repo explains the gap yet.
> It is worth knowing that the two electrical engines land on **opposite sides** of it:
> the simple node uses the *measured* number, while the hi-fi engine (§8) derives its
> droop from the FB-node superposition and therefore reproduces the *design* number.
> Running the same scenario in both modes displays the discrepancy directly, which is
> the most useful thing this document can do with an unresolved finding.

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

> **Superseded in part by §9 (Source models).** The fixed `V_FC_OPEN − R_FC_INT·I` /
> `V_BT_OPEN − R_BT_INT·I` terminal model described in this subsection has been replaced
> by a PEM polarization model and a coulomb-counted OCV(SOC) pack model, both shared by
> the two electrical engines. The constants named here survive only as the fit targets
> §9 reproduces (≈13 V open circuit, ≈0.45 Ω effective FC sag).

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
| `charge-cruise` | pi-command timeline: → Run at 3 s, cruise `v_setpoint` 1.2 m/s at 5 s, **`charge_goal` 1.0 at 8 s** | `chargingControl()`'s cruise branch: `assertFcChargeEnable(true)` on **intent**, the `AG105_SETTLE_MS` window, `ag105IsReady()`, the MPPT release | `switch` gains `SW_FC_CHARGE` (0x10) and **loses** `SW_BT_BUS` (the guard drives it low first); `ag105_status` walks `0x00` → Bring-Up → `0x42` Charging+CC; `aux` bit2 `MPPT_DISABLE` goes **HIGH** (released, active-LOW) once ready. Requires `--electrical` either mode. |
| `charge-regen` | same, then `v_setpoint` alternated 1.5 ↔ 0 m/s so the drive controller commands negative current | `chargingControl()`'s regen branch and the REGEN ⇄ FC_CHARGE **mutual exclusion** | During each brake: `SW_REGEN` (0x08) set, `SW_FC_CHARGE` **clear** (never both), `MPPT_DISABLE` driven LOW (inhibited). Between brakes the pair swaps back. |
| `charge-fault` | charging established, then at **t = 20 s** the charger input rail collapses (`plant.chg_fault`) | the charger-loss path: `chargerHasPower()` going false, the settle timer re-arming, the GENSTAT decode in `detectFaults()` | `V_chg` → 0, `I_charge` → 0, `ag105_status` → `0x00` (GENSTAT 000, Battery Disconnect), `ag105IsReady()` drops and the MPPT release is withdrawn. |
| `soc-depletion` | `i_aux` → +3.0 A at t = 5 s, share commanded fully onto the **battery** | the honest `LIMIT_V_BATT_MIN` / UV_BATT path, driven by a real coulomb count rather than a step | `V_batt` walks **down the OCV curve** (§9.2) as `soc` falls; `Rs(SOC)` steepens the sag below 15 % SOC. **Practical note:** at 5 Ah a 3 A draw is a ~100 min run — use `--soc0 0.15` and/or `--capacity-ah` to bring it inside a bench session. The model is deliberately *not* accelerated: a faked SOC ramp would also fake the RC-pair and `Rs(SOC)` dynamics the UV path actually sees. |
| `handoff-sag` **(hi-fi only)** | share commanded to the **FC rail** at 6 s, then +1.5 A load step at 20 s | RT1987 forward regulation + reverse comparator: the standby BT diode conducts only once the bus falls below its source minus `V_FWD` (35 mV) | An **unsourced gap** while the bus decays, then a reactive pickup with overshoot — the TP0178/TP0201 signature. Refused under `--electrical simple`, which has no ideal-diode dynamics and would show nothing. |
| `bringup` **(hi-fi only)** | none; plant from dark | the firmware's staged bring-up P0–P3 against the **real** RT1987 `t_D(ON)` 8 ms + soft-start ramps (~19.8 ms on the 100 nF switches, ~1.07 ms on the 5.6 nF ones) | Operator runs `'G'`; the phase timings in the USB log should sit outside the switch delays rather than racing them. |
| `scp-inrush` **(hi-fi only)** | VESC input capacitance forced to the **top of the envelope (0.9 mF)**, and a **6 A draw on the V-MOT node** (behind the switch, *not* `i_aux` on VBUS) from t = 8 s | RT1987 soft-start **foldback** on `MOT_PWR` | `scp_cut` + `sw_ring` entries in the event sidecar. Verified offline: the margin holds at 2 A (soft-start completes, `V_mot` reaches 15.1 V) and breaks at ≥ 4 A into a **64 ms burst-retry cycle** — the Death-5-class ring pattern. **Not** the Death-5 stimulus itself: that was a full-bus hot-plug onto a discharged node, no longer reproducible (`MOT_PWR` carries a 100 nF CSS and the firmware pre-charges the node). This is the nearest *legitimate* case that can still bind the foldback. Ring peaks here stay under the 20 V abs-max because the cut happens at low `V_mot`; a cut at full bus on `--trace-config long` (BT, 3.480 nH) does cross it. |

Three scenario notes. First, `sag` injects an **offset on the bus node**, not a source
failure — `V_fc` and `V_batt` are unaffected, so it is an isolated bus-UV stimulus rather
than a source-dropout stimulus. Second, `comm-loss` is the only scenario that touches the
transmit gate; all others return `tx_enabled = True` unconditionally. Third, `sag` is an
**incidental** charger stimulus too, not a dedicated one: if `FC_CHARGE_ENABLE` happens to
be closed when the offset lands, `V_chg` sags with the bus and can cross below
`AG105_V_IN_MIN` (§4.6), dropping `chg_powered` and resetting the settle timer — worth
watching for in a `sag` trace that also has the charger path open, but not something the
scenario was built to isolate.

### 6.1 Running every scenario in one pass

The table above is per-scenario. To run **all** of them — plus the recorded-log replay
suite — against a flashed board in a single pass, use the wrapper
`tools/run_hil_suite.py` (documented in `docs/HIL_MODE.md`, "Running the full suite").
It launches each scenario as a separate `hil_plant_sim.py` child with a timeout,
picks the electrical engine per scenario (a `hifi`-only scenario always runs hi-fi;
`any` scenarios follow `--electrical-pref`), pauses between runs so the board unbinds
its HIL host, and writes a `REPORT.md` + `results.json` covering observation-frame
counts, achieved tick rate, fault outcome against an expectation table, hi-fi substep
statistics and the event-sidecar counts — including any `sw_ring` above the 20 V
abs-max. The report's "known open findings" section always restates the `K_DROOP_BUS`
design-vs-measured ×4 discrepancy (§4), since every bus-droop number in a suite run is
mode-dependent until that gap is closed.

---

## 7. Data capture

### 7.1 CSV schema (`--csv`)

One row per tick. The base schema is **19 columns and is frozen**; everything since is
**appended, never reordered**:

- `soc` (col 20) — battery state of charge, 5 dp. **Simulated runs only.**
- `elec_substep_hz`, `elec_events` (cols 21–22) — **`--electrical hifi` only**: the
  honestly-measured substep rate this tick and the cumulative electrical-event count.
- `replay_rec` — **replay only**, and in replay mode `soc` and the hi-fi columns are
  deliberately *omitted*, so `replay_rec` keeps its established column index and an
  existing replay parser is unaffected.

Base columns:

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
`ag105_status` (as `I_chg=`/`chg=0x..`), the battery `soc=` percentage, and — under
`--electrical hifi` — the achieved substep rate, substeps per tick and running event
count. Before any observation frame arrives it prints
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

## 8. The high-fidelity electrical engine (`--electrical hifi`)

`tools/hil_electrical.py` is an **optional** replacement for the single droop node of §4.
The default remains `--electrical simple`, which is the right model for sequencing and
fault-logic work. The hi-fi engine exists for one purpose: **recreating electrical
failure modes the bench has actually recorded**, so they become repeatable stimuli.

```
python3 tools/hil_plant_sim.py --scenario handoff-sag --electrical hifi \
        --trace-config short --csv hifi.csv
```

Only the **electrical** section is delegated. The mechanical model (§3) and the Ag105
status logic (§4.6) stay in `Plant`, so a scenario behaves the same way in either mode
apart from the electrical fidelity itself.

### 8.1 Rate architecture — a separate, honestly-reported substep rate

The electrical state is integrated at its **own rate**, decoupled from the 1 kHz
mechanical/frame loop. Within each 1 ms tick the engine takes *n* substeps, and *n* is
chosen **adaptively from measured wall-clock cost**: it times the substep loop, keeps an
EWMA of the per-substep cost, and picks the count that fills `BUDGET_FRAC` (65 %) of the
tick. The frame transmission always keeps its slack; the engine never stalls the 1 kHz
loop.

- `achieved_substep_hz` is **measured, not nominal** — it is reported in the 1 Hz status
  line, in the end-of-run summary, and per-tick in the CSV.
- `DT_SUB_MAX` (50 µs) is an **accuracy** preference, not a stability bound: the engine
  is backward-Euler and therefore L-stable. **Budget wins over the preference** — a host
  that cannot afford the ceiling runs coarser *and says so*, rather than overrunning.
- `N_SUB_MAX` (400) caps the count regardless, so a mis-measured cost cannot stall a frame.

Observed on a typical host: ~20 substeps/tick, **~30–40 kHz achieved**.

### 8.2 The node network

Six capacitive nodes form the ODE state, solved **backward Euler** each substep as
`(G + C/h)·v' = J + (C/h)·v` through a 6×6 Gaussian elimination with partial pivoting:

| Node | Capacitance | Source |
|---|---|---|
| `OFC` / `OBT` — boost outputs | 30 µF / 40.1 µF | derated bulk; BT carries +10.1 µF of bodge caps |
| `BUS` — VBUS proper | 35 µF | 30–40 µF band, midpoint |
| `MOT` — V-MOT, **behind** `MOT_PWR` | 470 µF (ESR 80 mΩ) + VESC input | VESC envelope 0.2–0.9 mF, default 0.5 mF, `--vesc-cap-uf` |
| `CHG` — charger input | 10 µF | **`TODO(verify)`** — no separate cap identified on the schematic |
| `RGN` — regen node | 10 µF | **`TODO(verify)`** — likewise |

Backward Euler is not a stylistic choice: a 22 mΩ ideal-diode switch between two ~35 µF
nodes is a **0.77 µs RC**. An explicit method would need ~µs substeps to stay stable;
backward Euler settles it to the correct quasi-static solution at any substep size. The
cost is that the *transient itself* is not resolved.

### 8.3 The TPS61288 channels — and a deliberate deviation

Each channel is a **droop-regulated Thevenin source behind the validated first-order
voltage-loop lag** `τ_r = 100 µs`, current-limited, with the FB-node superposition
supplying the droop:

```
    h1·v_out + h2·v_op = VREF ,   v_op = A_v·K_sns·g·i      (OPA197, ceiling 4.9 V)
  ⇒ v_out = V0 − (R_D1/R_inj)·v_op = V0 − RE_MAX·g·i        (V0 = 15.907 V, RE_MAX = 2.014 Ω)
```

so the channel is a source of internal resistance `R_e = RE_MAX·g` — the droop stamped
**as a resistance, inside the node solve**, which is both the correct physics and the
only numerically stable form here.

> **Deviation from the requested datasheet structure, and why.** The first
> implementation *was* the literal structure asked for: gm error amp `G_EA`, the exact
> two-state compensation impedance `Z_comp(R_EA, R_C, C_C, C_P)`, and the Norton power
> stage `i_N = K_COMP(1−D)(1 − s/ω_RHPZ)·v_comp` — a time-domain rebuild of
> `controller_design/tps61288_full_model.py`. **It is numerically unusable at this
> substep rate.** That voltage loop crosses at **4–19 kHz** (system_model.md §6e, gate C
> of the full-order model) and a stdlib-Python host achieves **20–40 kHz** substeps on
> this network — crossover essentially at Nyquist. It diverged within three substeps and
> tripped the 19 V OVP on every bring-up. A second attempt kept the compensator but fed
> the measured current back *explicitly*; with a 23 mΩ link between two ~0.6 Ω droop
> sources the explicit loop gain is `R_e/R_link ≈ 26` per substep, and it oscillated
> rail-to-rail. **The limiter is the discretization, not the physics** — resolving that
> loop needs ~1 MHz substeps. The model was therefore dropped to the level this repo has
> already validated for this bandwidth: the simplified share plant of
> `tps61288_full_model.py:188-191` / system_model.md §6d.
>
> **Kept:** the FB-node superposition droop, the OPA197 ceiling, the 19 V OVP trip,
> enable/disable, the disabled-boost body-diode passthrough.
> **Lost:** the RHPZ lead, compensator saturation/recovery shape, and any claim about
> voltage-loop margin. **Do not use this engine to judge boost stability** — that is
> what `tps61288_full_model.py` is for. The full-structure constants are retained in the
> module so the datasheet form can be restored wherever it *can* be integrated.

The **disabled-boost body-diode passthrough** is modelled explicitly, as a Norton source
`(V_in − 0.55 V)` behind 0.15 Ω onto the channel's output node. This is *the* back-feed
hazard path of CLAUDE.md §2: a disabled TPS61288 still conducts input→output, so the bus
can be pulled up through a dark converter and a regen event can push current into it.

### 8.4 RT1987 ideal-diode switches

Six instances, each a state machine — and the element that makes the handoff-gap and
SCP behaviours fall out rather than being scripted:

| State | Behaviour |
|---|---|
| `OFF` | **Full isolation** — back-to-back FETs, **no body-diode path**. Entered on EN low or `VIN < UVLO` (3.175 V). |
| `TD_ON` | 8 ms typ EN-rise delay. |
| `SOFT` | VOUT follows a linear ramp over `tON = (VIN/35)·(CSS_nF/0.0023 − 100) µs` — ~19.8 ms at 16 V on the 100 nF switches (`FC_BUS`, `BT_BUS`, `MOT_PWR`), ~1.07 ms on the 5.6 nF ones (`REGEN`, `FC_CHARGE`, `BT_SEQ`). Foldback SCP is active **only here**: 8.5 A at ΔV ≤ 5 V falling toward ~5.3 A at ΔV = 16 V, floored at 2.5 A. Held continuously at the clamp for **250 µs** → **CUT**, auto-retry after **64 ms**. |
| `ON` | Forward regulation at `V_FWD` = 35 mV, `R_ON` = 21 mΩ. Fast reverse comparator at **−50 mV** → off, then re-arm **without** a new soft-start once forward again. |

Two modelling notes. First, the soft-start is a **controlled source on the output node**,
not a resistor referenced to the input node: stamping it the latter way (with the offset
computed from the previous substep's `v_in` while the conductance term moved `v_in`
inside the solve) injected a fictitious ~1400 A into the bus. Second, both the foldback
limit and the boost's output-current ceiling are stamped as **equivalent resistances**,
never ideal current sources — an ideal source into a 30 µF node is unbounded within a
single substep.

**The handoff gap is emergent.** A standby switch conducts only once its input exceeds
its output by `V_FWD`; so when the live source goes dark, the bus must first *sag* by
that much before the standby diode picks up. That is TP0178/TP0201, reproduced from the
part's specification rather than scripted.

> RT1987 figures here are **typicals**. The datasheet min/max spread is not modelled, so
> a margin that looks thin is thin *in the typical part*, not in the worst part.

### 8.5 Parasitic inductance — analytic, not integrated

| Config (`--trace-config`) | FC | BT | Provenance |
|---|---|---|---|
| `long` | 1.538 nH | 3.480 nH | FastHenry extraction, `papers/Droop_Control/sections/05_bringup_debugging.tex` Table `Lsweep` (lines 182–183) — the as-manufactured loops |
| `short` (default) | ~1.5 nH | ~1.5 nH | post-bodge routing, **inferred FC-like — `TODO(verify)`, no extraction exists** |

> **Prominent deviation.** nH against µF is a **~100 MHz** natural frequency —
> unintegrable in real-time Python at any substep count. The parasitic effect is
> therefore modelled **analytically as switching-event overshoot**:
> `V_peak ≈ V_node + L·di/dt` with `di/dt` from the load-dump slew class (~1.3 A/ns,
> `docs/boost-bringup-debug.md`), emitted as an **event annotation** and compared against
> the **20 V abs-max**. The engine therefore **detects** the Death-5 boost-kill mechanism
> as a flagged event; it does **not** simulate the ringing waveform. An `sw_ring` event
> with `over_absmax: true` is the boost-death signature, and the run summary calls it out.

### 8.6 Regen chopper

The TL431 + BSP170P clamp on the regen node is autonomous — **not** under firmware
control. Above `V_CHOPPER_TRIP` a shunt of `V_rgn / 47 Ω` conducts (47 Ω / 20 W dump
resistor). `V_bus` is unaffected: the chopper sits behind `MOT_PWR`/`REGEN`.
The trip **threshold itself was never measured** — `TODO(calibrate)`, set to 16.5 V;
the *dynamics* it is fitted against are the observed 13.3 → 18.1 V peak clamping
excursion (CLAUDE.md 2026-08-17b).

### 8.7 Noise injection

Applied to the **injected values**, never to the internal states.

- **ADC quantization** is real and computed from the firmware's own scale constants
  (`teensy_controller.ino:1128-1144`): `V_fc` 3.01 mV/count, `V_batt` 2.11, `V_bus` 4.55,
  `V_chg`/`V_rgn` 7.15, currents **8.06 mA/count**.
- **Gaussian sigmas default to ZERO.** No measured per-rail noise figure exists anywhere
  in this repo, so a non-zero default would be invention. `NoiseConfig.suggested()`
  offers order-of-magnitude values, every one of them `TODO(verify)`.
- **INA253 zero offset** defaults to 0.02 A, clipped at zero — 10s-of-mA class,
  `TODO(verify)`, no per-part measurement exists.

### 8.8 Events and the sidecar

`ElectricalSim.events` accumulates dicts (`scp_cut`, `sw_ring`, `reverse_block`,
`boost_ovp`). With `--csv PATH` they are written to **`PATH.events.jsonl`**, one JSON
object per line, and summarized at exit.

---

## 9. Source models

Both electrical engines share **one instance each** of the fuel-cell and battery models:
`Plant` owns them and hands them to `ElectricalSim`, so SOC and the FC double-layer state
are integrated exactly once per tick whichever mode is active, and a scenario behaves the
same way in both. They live in `tools/hil_electrical.py` (SOURCE MODELS block).

Structure and parameter names follow:

> S. Yadav and F. Assadian, **"Robust Energy Management of Fuel Cell Hybrid Electric
> Vehicles Using Fuzzy Logic Integrated with H-Infinity Control"**, *Energies* 2025,
> 18, 2107 — in `references/`.

The paper's **numeric** parameters are for a vehicle-scale stack and pack. This rig is an
H-20 class ~13 V stack and a 2S RC LiPo, so the **model form is the paper's** and the
parameters are fitted to the rig's only known points. Every rig-specific value is marked
`TODO(calibrate)`; **none of them is measured.**

### 9.1 Fuel cell — PEM polarization, paper §2.1

| Term | Paper | Implementation |
|---|---|---|
| Nernst potential | Eq. (3) | `FC_E_NERNST` = 1.15 V/cell, held constant. The reactant-flow states Eqs. (8)–(10) are **not** modelled — this rig has no flow instrumentation. `TODO(calibrate)` |
| Activation (Tafel) | Eq. (4) | `V_act = 0.0268·log((I/A + 1)/0.0027)` |
| Concentration | Eq. (5) | `V_conc = −0.05·log(1 − (I/A + 1)/1500)` |
| Ohmic | Eq. (6) | `V_ohmic = (I/A + 1)·30e−5` |
| Terminal cell voltage | Eq. (7) | `V_cell = E − V_act − V_ohm − V_conc` |
| Double-layer RC | Eq. (11) | first-order state `V_a`, `FC_TAU_S` = 20 ms `TODO(calibrate)` |
| Stack voltage | Eq. (12) | `V_stack = N·(E − V_a − V_ohmic(I))` |

**Deviation from Eq. (11), documented at the site.** The paper writes
`dV_a/dt = I/(A·C) − V_a/(R_a·C)`, whose equilibrium is the *linear* `I·R_a/A`. Here the
equilibrium is instead the **nonlinear activation + concentration pair** of Eqs. (4)–(5):

```
    dV_a/dt = (V_act(I) + V_conc(I) − V_a) / FC_TAU_S
```

so the polarization curve keeps its Tafel and concentration regions while the RC branch
supplies the same first-order dynamics. **This is the point of the model:** a fast load
step is met at first with only the ohmic loss and then sags over `FC_TAU_S` as the
activation overpotential builds — the shape the TP0178 "loose FC supply" hypothesis is
about (`docs/boost-bringup-debug.md`).

**Rig fit.** `N` = 12 cells and `A` = 3.0 cm² (`TODO(calibrate)`) give
`V_stack(0) = 12.97 V`, the ~13 V open-circuit class. The paper's stack terms alone yield
only ~0.04 Ω of slope at this cell area while the bench sees ~0.45 Ω, so a rig harness
term `FC_R_SERIES_RIG = 0.41 Ω` (`TODO(calibrate)`) is **added** to the paper's model —
the balance is wiring and contact resistance, not electrochemistry. Verified fit: 12.97 V
open circuit, 12.08 V at 2 A → **0.447 Ω effective**, against the 0.45 Ω target.

### 9.2 Battery — 2S LiPo equivalent circuit, paper §2.2

```
    V_T   = Em(SOC) − I·Rs(SOC) − V1                 (Eq. 13, one RC pair)
    dV1/dt = I/C1 − V1/(R1·C1)                       (Eq. 14)
    SOC   -= (1/C_batt)·∫I dt                        (Eq. 15;  I > 0 = DISCHARGE)
```

The **sign convention is the paper's**: positive current discharges, negative charges. The
Ag105's charge current therefore enters as a **negative** battery current, which is what
makes a long `charge-cruise` run visibly walk `V_batt` *up* the OCV curve — and lets the
charger reach `AG105_ST_FULL` (GENSTAT 011), which the old SoC-free model never could.

| Parameter | Value | Provenance |
|---|---|---|
| `Em(SOC)` | 9-point per-cell curve 3.30 → 4.20 V, ×2 cells | **Generic LiPo discharge shape, not a measurement of the fitted pack** — `TODO(calibrate)`. Respects the 7.4–8.4 V operating band of the 2026-07-10 system decision. At SOC 0.7 it gives 7.86 V. |
| `C_batt` | 5.0 Ah, `--capacity-ah` | plausible 2S RC pack — `TODO(verify)` |
| `Rs(SOC)` | 0.040 Ω/cell mid-band, rising up to 4× below 15 % SOC | `TODO(calibrate)` |
| `R1`, `C1` | 0.020 Ω, 200 F (τ ≈ 4 s) | single RC pair — `TODO(calibrate)` |

Initial SOC is `--soc0` (default 0.7).

---

## 10. `PiCommander` — driving the firmware from the scenario

Several of the new scenarios need the board to be *commanded*, not just fed sensors:
`charge_goal` reaches the firmware only through the Pi's 22-byte command packet, and the
firmware's charging path had **no scenario coverage at all** before this.

`PiCommander` plays a scenario's `pi_timeline` onto the **same socket and destination**
as the injection frames — the firmware's `receiveCommands()` drains both frame types and
dispatches by length (fw v21 bounded drain).

Packet layout, **verified from `teensy_controller/teensy_controller.ino`
`processPiCommandPacket()` lines 4806-4852** (`SYNC_BYTE_RX` at line 2528) — nothing
guessed, and the firmware body is byte-frozen because the Pi bridge parses fixed offsets:

| Offset | Type | Field | `.ino` |
|---|---|---|---|
| 0 | u8 | sync `0xBB` | :2528, :4810 |
| 1 | u32 | timestamp | :4825–4826 |
| 5 | u16 | `pkt_counter_Pi` | :4828–4829 |
| 7 | f32 | `v_setpoint` (constrained ±20 m/s) | :4842, :4846 |
| 11 | f32 | `power_share_setpoint` (constrained [0,1]) | :4843, :4847 |
| 15 | f32 | `charge_goal` | :4844, :4848 |
| 19 | u8 | `mode_cmd` — 0 HYBRID, 1 FC_ONLY, 2 BATT, 3 CHARGE, 4 SAFE | :4850, :4857 |
| 20 | u8 | `droop_enable` — **reserved**, parsed and discarded | :4851–4852 |
| 21 | u8 | XOR over bytes 1..20 | :4812–4814 |

A timeline is `[(t_seconds, {field: value}), …]`; unspecified fields **hold** their
previous value, matching the firmware, which also holds a field it rejects. The commander
transmits at **50 Hz** and keeps sending the held state between entries, because a
command packet is what marks the Pi link alive (`last_rx_ms`, :4854).

### 10.1 `SCENARIOS` registry

`SCENARIOS` is a plain dict, `{name: {description, electrical, duration_s, pi_timeline?,
vesc_cap_f?}}`, consumed by the CLI (`--list-scenarios`, defaults, the hi-fi refusal) and
— by contract — by `tools/run_hil_suite.py` via `from hil_plant_sim import SCENARIOS`.
`apply_scenario()` remains the behaviour dispatcher; the registry is metadata only. A
scenario marked `"electrical": "hifi"` is **refused** under `--electrical simple` rather
than silently producing a meaningless trace.

---

## 11. Fidelity boundaries and extension roadmap

### 11.1 Validity envelope

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

It is **not** trustworthy for: control gains of any kind, **boost voltage-loop stability
or margin** (§8.3 — use `tps61288_full_model.py`), switching-ripple or converter waveform
behaviour, the parasitic ringing *waveform* (§8.5 detects the event, it does not simulate
it), charger *energy* behaviour beyond the coulomb count (no CV taper, no simulated MPPT
loop — §4.6), encoder/estimator behaviour, or anything the board's analog front end does
beyond the quantization of §8.7.

What **moved out** of that list since the first revision: the bus droop is now measured
(§4.2), sensor quantization exists (§8.7), and hot-plug / handoff / SCP behaviour is
modelled to the degree §8.4–§8.5 describe. What **stays** `TODO(verify)`/`TODO(calibrate)`:
`V_STICTION`, `R_BUS_BLEED`, `ETA_BOOST`, `I_AUX_A`, `AG105_TAU_S`, `AG105_V_IN_MIN`, the
`short` trace-inductance set (§8.5), the chopper trip threshold (§8.6), the charger/regen
node capacitances (§8.2), every gaussian noise sigma and the INA zero offset (§8.7), and
**every rig-specific source-model parameter** (§8). For those, the *shapes* are right and
the *magnitudes* are plausible rather than measured.

### 11.2 Flagged follow-ups

| Item | Scope |
|---|---|
| **`--replay` mode** | Feed decoded BLG runs back as injection frames, turning recorded bench incidents (the ML0151 drag event, the TP0178 handoff sag, the VESC reversal dead window) into repeatable regression stimuli against the firmware. **In progress** as of this writing — a parallel change to the Ag105/`I_charge` injection work this document describes. |
| **Richer electrical model** | **Delivered** as `--electrical hifi` (§8): the `τ_r` lump, RT1987 turn-on/soft-start/foldback, per-node capacitances, and a split derived from the droop network's equivalent resistance rather than the raw code ratio. Still open: the datasheet-structure boost loop (needs a substep rate Python cannot reach — §8.3), integrated parasitics (§8.5), and a switching-level model. |
| **The ~4× droop discrepancy** | §4.2. Measured 0.074 V/A shared vs a design-predicted 0.30 V/A. The two engines sit on opposite sides of it, which makes it visible but does not explain it. This is the highest-value open electrical question in the document. |
| **Source-model calibration** | §9 is the paper's *form* with rig-fitted parameters. A pack capacity/OCV characterization and an FC polarization sweep would convert most of §9's `TODO(calibrate)` markers into measurements. |
| **Measured electrical constants** | Close the `TODO(verify)` list — most cheaply `K_DROOP_BUS` and `I_AUX_A`, both directly observable on a healthy bench run; `AG105_TAU_S` and `AG105_V_IN_MIN` (§4.6) need a bench charge cycle instead. |
| **Decoder bit6 label** | `tools/decode_benchlog.py` should name the HIL provenance bit so a simulated run cannot be mistaken for a measured one downstream. |
| **Battery state of charge / CV taper / MPPT loop** | The Ag105 model (§4.6) is status-level only; a stateful SoC model would let `AG105_ST_FULL` and a genuine CV taper appear in a HIL run. |
