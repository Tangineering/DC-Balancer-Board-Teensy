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

**The pre-link first boot latches *a* fault, and which one varies.** Before the first
injection frame arrives the board is reading its own floating ADCs, so a `BENCH_TEST=0`
build can indicate and latch a fault during the window between power-on and the simulator
streaming. That is expected, harmless, and **excused pre-grace** by the suite
(`WARM_RESET_GRACE_S`; fw v23's any-fault recovery clears it at the first run boundary) —
but the *bit* is not stable, and a reader who has memorised one signature will
mis-attribute the next. Observed across three campaigns: **`UV_BATT`**, **`OC_FC`**, and
**`INIT_FAIL` (`0xA010`)** — three distinct signatures for one mechanism. A fourth
distinct bit on a future first boot is still the same harmless thing; do not open an
investigation on the bit alone. What *would* be a finding is such a latch appearing
**after** the grace bound, or surviving a run boundary — both of which the suite already
scores.

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

### 3.4 The regen model (WP-C, 2026-09-01)

**This section replaces "The regen floor".** Until WP-C the plant computed motor bus draw
as `p_mech = max(0.0, f_drive · v)` and applied the **unclipped** braking force
mechanically. That was wrong twice over: the braking force was overstated, and the energy
it removed from the flywheel vanished from the model entirely. Braking energy now flows end
to end —

```
flywheel kinetic energy
   → VESC (regen-side current clipped at VESC_REGEN_I_MAX_A)
   → V-MOT node                      ← the RGN-V divider and the chopper sit here
   → TL431/BSP170P chopper clamp     ← the FAST path; burns what the charger cannot take
   → D-BC-RG → VCHG-IN → Ag105       ← the SLOW path; banks the rest
   → pack coulomb count (SoC)
```

**Force/energy consistency.** The regen side of the command is clipped *before* it becomes
force, so one number sets both the braking force and the electrical return:

| Term | Value | Provenance |
|---|---|---|
| `VESC_REGEN_I_MAX_A` | 1.5 A | **`TODO(verify)`.** The bench Battery Regen Max setting (operator, 2026-08-16). Logs 153–162 measured −12 A commanded against ~6 % delivered (CLAUDE.md 2026-08-17b). The commanded-vs-delivered **mapping** was never characterized, and the setting is *battery*-referred while `i_cmd` is *motor*-referred; the model applies it directly to the motor-side command. **M5 (reviewer, 2026-09-01):** this is CONSERVATIVE on both the force axis and the harvest axis, not "conservative-force / optimistic-harvest" as previously stated — at 3 m/s the motor-referred cap yields 2.71 W of motor-side regen power, which maps to only ~0.17 A on the battery side, well below the ~0.7 A battery-side current the same logs actually measured; both directions of the mapping undercount versus what was observed. Closed by the queued "VESC regen-ceiling characterization" bench item. |
| `ETA_REGEN` | 0.80 | **`TODO(verify)`.** Round-trip mechanical→electrical efficiency (motor copper/iron, inverter conduction/switching, link ESR). A modelling choice in the `ETA_BOOST` (0.85) class, de-rated for the harder braking corner. Same bench item. |
| `R_CHOPPER_REG` | 0.5 Ω | **`TODO(verify)`.** The TL431/BSP170P clamp's small-signal output resistance. The clamp is a **linear regulator**, not a switched 47 Ω shunt: a bare shunt cannot hold 18.1 V against anything under 0.385 A, so it chatters across the threshold instead of clamping. 0.5 Ω is stiff (0.19 V of droop at the saturation point) without stiffening the node solve. |
| `V_REGEN_OC_MAX` | 20.0 V | **`TODO(verify)`.** Stands in for the VESC's own DC-link overvoltage cutback, never characterized on this rig. It is the abs-max the ring estimator already uses, comfortably above the 18.1 V clamp, so the **chopper stays the operative limiter** — which is the physical design. |
| `V_CHOPPER_TRIP` / `R_CHOPPER` / `P_CHOPPER_MAX_W` | 18.1 V / 47 Ω / 20 W | Unchanged — bench-calibrated clamp level (2026-08-27) and the BOM dump resistor. |

**The energy balance the model asserts** (written at the site in `Plant.step()` and pinned
by `test_regen_energy_balance` in both engines):

```
ΔKE                       = W_friction + ∫|p_shaft| dt
∫|p_shaft| dt · ETA_REGEN = E_regen_electrical
E_regen_electrical        = E_chopper + E_charger + ΔE(C_MOT_NODE)
```

The old floor violated the second line by setting its right-hand side to zero.

**Where the energy actually goes, and why that is not a tuning knob.** `MOT_PWR` is an
ideal diode, so regen current cannot flow back into VBUS: it charges the motor node until
the chopper clamps at 18.1 V. That reproduces the bench observation — *V_rgn 13.3 → 18.1 V
held, V_bus unmoved* (CLAUDE.md 2026-08-17b) — and the residual bus coupling is bounded by
the RT1987's own 50 mV reverse-comparator band, i.e. the ~0.03–0.06 V the engine's chopper
banner predicts. Meanwhile the Ag105 is dark for its first `AG105_SETTLE_S` (0.5 s) and
then ramps on `AG105_TAU_S` (0.4 s), so the **first half-second of every braking window is
burnt in the chopper, not banked**. That asymmetry — fast clamp primary, slow charger
secondary — *falls out* of the model; it is not hardcoded anywhere.

**Honest magnitudes.** At the 1.5 A clip the braking force is only `K_F · 1.5` = 1.13 N
against 2.00 N of Coulomb friction alone, so most of the flywheel's energy still leaves as
friction and a 3.0 → 0.4 m/s window returns **single-digit joules**. Pack SoC across a
braking window is still a **net fall** (the bus load outweighs the harvest). Read the
harvest off `I_charge`, the `chopper_clamp` event's `energy_j`, and the plant's
`regen_energy_j` / `e_brake_mech_j` counters — never off SoC direction.

**Charger input-power cap.** On the REGEN-fed path the Ag105's ceiling is
`min(configured profile, available input power)`; fed from the bus through `FC_CHARGE` it
is the configured profile verbatim, exactly as before. Without the cap the charger would
draw its 2.5 A profile out of a 3 W brake. The bias runs in **both directions, and they do
not cancel**: `p_regen_w` is the power available **pre-chopper**, so the cap is
**optimistic** by the chopper's own efficiency/share factor — some of that power is lost
across the chopper before it ever reaches the Ag105 input — while separately the cap is
input-referred and compared against an output-referred target, which **understates** the
harvest by roughly `v_in/v_pack ≈ 2×` — the conservative direction. Left in place rather
than papered over with an unmeasured converter efficiency (`TODO(verify)`).

**Observability.** The hi-fi engine emits one coalesced **`chopper_clamp`** event per
braking episode (`dur_s`, `energy_j`, `peak_w`, `peak_v`) and reports `regen_energy_j`,
`chopper_energy_j` and `chopper_episodes` in `summary()`. `chopper_clamp` is deliberately a
*different kind* from `chopper_over_power`, which the suite scores as a **failure** — a
clamp doing its job is an objective, not a defect. `reverse_block` events are coalesced the
same way (a regen episode reverse-blocks and re-arms `MOT_PWR` every few substeps by
construction).

**⚠️ BASELINE ERA.** Every regen-path trace recorded in campaign `20260831_080905` or
earlier was taken under the floor and is **not comparable** with a post-WP-C run — even the
velocity trace differs, since the braking force is now clipped.

**Regen-affected scenario enumeration (MEASURED, reviewer H1, 2026-09-01).** An offline walk
of every EMS objective and all 27 replay entries against the -1.5 A regen clip found:
`regen-harvest-true`, `charge-regen`, `mppt-tracking`, and all four `ems-y-*` scenarios
(`ems-y-b00-v1`, `ems-y-b00-v3`, `ems-y-b30-v1`, `ems-y-b30-v3`) genuinely brake to -12 A for
328-971 ticks past the clip (braking force drops 9.05 N -> 1.13 N, i.e. deceleration at
3 m/s is 2.7x less) and so ARE regen-affected. `ems-sdp-braking` is explicitly **excluded**
from that list despite braking every plateau: it measured **zero** ticks below the -1.5 A
clip, so its charge windows are FC-fed through `FC_CHARGE` on the decel plateaus (see its
own HONEST CAPTION in the scenario table), not regen harvest. Everything else in the EMS
objective set — `ems-ftp75-*` (all variants), `ems-sdp`, `ems-soc-band`, `ems-dp-replay`,
`ems-sdp-cross`, `ems-drive-cycle`, `soc-depletion`, `charge-to-full` — and all 27 replay
entries measured **0** ticks past the regen clip, so their H2/SoC totals and the EMS
frontier comparison are unaffected by the WP-C change.

For those unaffected scenarios: the plant's drive direction is byte-identical (the
`i_cmd >= 0` identity branch is unchanged), pinned by
`test_drive_direction_is_bit_identical_to_the_pre_wpc_model`. The hifi ON-state stamp does
change, but only where `dv < 35 mV` — bounded to (a) SOFT->ON handover transients (<= 90.6 mV
one-tick deviation, decaying to zero within <= 16 ticks, with no state or event change), and
(b) a bus collapse with `MOT_PWR` closed (the State-99 teardown regime: `ΔV_bus` up to
2.30 V, producing 2 new `reverse_block` events — this is intended physics, not a
regression). Deep sag with the boosts still on measures bit-identical to the pre-WP-C model.

**Scoped deviation, flagged not shipped.** The ideal-diode correction that stops a closed
switch conducting *reverse* below its 35 mV forward-regulation point is applied only to the
links whose downstream node carries an active source (`MOT_PWR`, `REGEN`, `FC_CHARGE`).
Applying it to the two boost-OR links is a different experiment — it moves the
hardware-corroborated cold-start pin 0.2224 → 0.2245 A (+0.9 %, INDEPENDENTLY VERIFIED,
reviewer L5, 2026-09-01) and changes which channel blocks during a hand-off (this half of
the claim did NOT reproduce under two tested cold-start stimuli — see the L5 note in
`hil_electrical.py`'s `strict_forward` block; UNVERIFIED as stated) — and needs its own A/B
round against the bench.

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
| `v_bus_offset` (simple mode) | scenario-driven | 0 except during `sag` (§6) — a REAL algebraic disturbance: it is added directly into this node equation, so it is a plant-level event every downstream reader (including the hi-fi engine's own `V_bus` if it were driving this equation) would agree on. |

> **M5 — a named asymmetry between the two electrical modes.** The hi-fi engine's
> equivalent (`ElectricalSim.v_bus_sense_offset`, fed from the same scenario-driven
> `Plant.v_bus_offset`) is **SENSED-RAIL-ONLY**: it is added only in `ElectricalSim._rails()`,
> after the node solve, so the node itself, the diode switches, the boost droop sources and
> the regen chopper never see it and cannot react to or fight it. Stamping it as a real
> Norton disturbance on `N_BUS` (mirroring the simple-mode algebra) was attempted and risks
> destabilizing the node solve against the existing droop sources at the small source
> resistance needed to make it dominate; rather than ship an under-tested network change,
> the attribute was renamed (`v_bus_offset` → `v_bus_sense_offset`) to make the asymmetry
> impossible to miss in code, and it is documented here instead. Practical consequence: the
> `sag` scenario's `-5 V` dip reaches the firmware's `V_bus` reading identically in both
> modes (so the UV fault path, §6's H2, is equally exercisable either way), but in hi-fi
> mode nothing else in the network — the boost regulators, the RT1987 switches, the chopper
> — responds to it, whereas in simple mode the offset participates in the same droop equation
> everything else does.

**Fit provenance.** `V_bus` regressed against `I_fc + I_batt` over quasi-steady 200 ms
blocks of **TP0170–0180** (with **TP0178 excluded** — that is the handoff-sag log, not a
steady operating point), **ML0165** and **ML0169**, all fw v16.

> ### ⚠️ Hi-fi droop is the DESIGN chain, not the bench measurement
>
> **Measured 2026-08-30 from a live HIL trace** (campaign `20260830_203006`,
> `handoff-sag`): the hi-fi engine's realized droop fits at **0.316 Ω shared /
> 0.633 Ω single, ratio exactly 2.000, V₀ = 15.867 V** — i.e. the **designed** MDAC
> droop chain (`R_e = RE_MAX·g = 2.014 × 0.298` ⇒ 0.30 V/A shared), +5 %. The
> bench-measured droop is `K_DROOP_BUS` **0.074 / 0.16 V/A** — about **4× smaller**.
>
> That gap is *by construction*, not a defect, and it means the two electrical modes
> answer different questions:
>
> | | droop | what a sag figure means |
> |---|---|---|
> | `--electrical simple` | bench-measured 0.074 / 0.16 V/A | comparable to a recorded bench log |
> | `--electrical hifi --droop design` *(default)* | design 0.316 / 0.633 Ω | **~4× deeper sag for the same load**, and what EVERY campaign on record ran |
> | `--electrical hifi --droop measured` *(opt-in, 2026-09-01)* | rescaled to the bench fit: **0.160 Ω single / 0.080 Ω shared** | comparable to a bench log, and **not** comparable to any other campaign in the archive |
>
> **Read hi-fi sag depths as CONSERVATIVE**: a UV or sag test that passes in hi-fi
> passes with margin on the real bus. **Do not compare them to a bench log or to a
> simple-mode run.** `charge-regen`'s 0.49 V sag under 1.54 A is exactly
> `1.54 × 0.316` — arithmetic, not an anomaly. Closing the gap means reconciling
> `hil_electrical.py`'s FB-node superposition against the measured fit; until then
> this banner is the disclosure. The same note sits at the `K_DROOP_BUS` definition
> in `hil_plant_sim.py`.

> **⚠ OPEN FINDING — the realized droop is ~4× BELOW the design value, and this is not
> hidden.** The MDAC droop chain predicts a per-channel Thevenin resistance
> `R_e = RE_MAX · g = 2.014 Ω × 0.298 = 0.60 Ω`, i.e. **0.30 V/A** with both channels
> sharing — four times the measured 0.074 V/A. Nothing in the repo explains the gap yet.
> It is worth knowing that the two electrical engines land on **opposite sides** of it:
> the simple node uses the *measured* number, while the hi-fi engine (§8) derives its
> droop from the FB-node superposition and therefore reproduces the *design* number.
> Running the same scenario in both modes displays the discrepancy directly, which is
> the most useful thing this document can do with an unresolved finding.
>
> **`--droop measured` (2026-09-01) DOES NOT CLOSE THIS FINDING.** The hi-fi engine
> can now be asked to realize the bench droop instead of the design one. That makes
> hi-fi sag depths comparable with a bench log, which is the whole point of the
> switch; it explains nothing. Mechanically it is a **single empirical scale factor**
> (`hil_electrical.DROOP_SCALE`) applied at the one point the MDAC chain becomes a
> resistance, `Boost.update()`'s `r_droop = RE_MAX · g · droop_scale`. Nothing else in
> the network moves — the RT1987 state machines, soft-start/TRCB, the chopper, the
> sources, the OPA197 ceiling and every other constant are untouched, and a test pins
> a `design`-mode solved operating point BIT-IDENTICAL to a pre-switch one.
>
> **The scale is taken over the DROOP TERM ALONE, and that matters by 15 %.** Only
> `RE_MAX · g` is rescalable; the series path in front of it — `Boost.R_OUT` 0.010 Ω,
> `RT_R_ON` 0.021 Ω, `R_SHUNT` 0.002 Ω, `DROOP_FIXED_SERIES_OHM` = 0.033 Ω — is fixed
> physical copper the droop code does not set. So
> `s = (0.16 − 0.033) / (0.63287 − 0.033) = 0.21171`. The naive end-to-end ratio
> `0.16 / 0.633` instead lands the single-source regime at 0.1847 V/A, +15 %, because
> it scales the floor down and then re-adds it at full size.
>
> **A residual is left, and it is asserted rather than hidden.** One scalar cannot
> land both regimes: the network is a parallel Thévenin pair, so its shared/single
> ratio is **structurally exactly 2.000**, while the bench fit's is
> 0.1615 / 0.0740 = **2.182**. The scale is anchored on the regime the bench measured
> most tightly — single-source, 0.1615 ± 0.001 V/A (0.6 %) — so the residual falls on
> the shared regime at **0.0800 V/A, +8.1 % over the measured 0.0740 ± 0.004** (5.4 %),
> i.e. ~1.5σ of that fit's own uncertainty. Anchoring the other way would have put
> single-source 8.4 % off a value known to 0.6 %, ~13σ. Both residuals are the same
> structural fact and neither anchor removes it. Measured, by DC solve at four
> currents per regime: design **0.31644 / 0.63287 Ω**, measured **0.08002 / 0.16003**.
>
> **Provenance and scope.** `run_hil_suite.py --droop {design,measured}` (default
> `design`) passes the flag to the SCENARIO half only — every replay entry's
> thresholds were calibrated against design-mode sag depths, so a measured-mode
> replay campaign needs its bands re-derived first, which is an operator decision.
> Every CSV's meta sidecar records `config.droop_mode` / `droop_scale` /
> `droop_applied` **unconditionally**, default included, so a report reader can place
> any sag figure on one side of this finding; REPORT.md states the campaign's mode in
> its header table and again under the standing finding. `V₀` is a property of the FB
> chain and does not move with the mode (15.867 V either way) — the bench intercept
> 15.95 V remains a separate ~0.08 V discrepancy this switch does not address.
>
> Scenario entries may override the mode with a `droop_mode` key (the
> `mppt_emulation` pattern); **no shipped scenario sets it**, so the hook costs
> nothing until a measured-vs-design comparison scenario is wanted.

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

> **⚠️ AND THE LOOP HAS NO AUTHORITY AT ALL BELOW 0.55 A** — a firmware property,
> not a plant one, but it decides what a scenario or an offline walk may claim.
> The firmware enters closed-loop share control above `2·SHARE_MINORITY_I_MIN_A`
> = 0.60 A of source total and drops out below 0.55 A (`.ino:2181/2205`, gate at
> `:9933`). In open-loop mode it does **not** write the MDACs: it holds the last
> converged split. So under 0.55 A a `power_share_setpoint` is accepted, appears
> in `cmd_share_sp`, and is **not acted on** — the codes this section models do
> not move. Campaign `20260901_024231` measured a delivered share of **0.1656**
> against a commanded 0.85 at a 0.355 A cruise, and an offline walk that assumed
> otherwise put a suite check on a limit-cycle period **5.7× wrong** (see the
> `ems-sdp-cross` row in the scenario table). Size a scenario's `aux_preload_a`
> if the loop must be closed, and model the hold if it must not.

### 4.5 Source terminals and path rails

> **Superseded in part by §9 (Source models).** The fixed `V_FC_OPEN − R_FC_INT·I` /
> `V_BT_OPEN − R_BT_INT·I` terminal model described in this subsection has been replaced
> by a PEM polarization model and a coulomb-counted OCV(SOC) pack model, both shared by
> the two electrical engines. The constants named here survive only as the fit targets
> §9 reproduces (≈13 V open circuit, ≈0.45 Ω effective FC sag).

```
    V_fc   = max(0, V_FC_OPEN − R_FC_INT · I_fc)      13.0 V, 0.45 Ω
    V_batt = max(0, V_BT_OPEN − R_BT_INT · I_batt)     8.0 V, 0.05 Ω
    V_chg  = V_bus if ((switch & SW_FC_CHARGE) or
                       ((switch & SW_REGEN) and (switch & SW_MOT_PWR))) else 0
    V_rgn  = V_bus if (switch & SW_MOT_PWR)   else 0
```

`V_FC_OPEN` 13.0 V is the H-20 fuel cell's open-circuit class (the firmware's
`LIMIT_V_FC_MIN` is 6.0 V); `V_BT_OPEN` 8.0 V is a 2S LiPo at mid-charge, inside the
7.4–8.4 V operating window (firmware `LIMIT_V_BATT_MIN` 6.2 V). The two internal
resistances are plausible source impedances — **`TODO(verify)`**, neither is measured in
the repo, and the 2026-08-17b addendum records that the bench supplies were *swapped*
mid-campaign, so no logged stiffness figure is a stable reference for them either.

The charger and regen rails are pure mirrors of the bus, gated by the switches that
actually feed them (**topology corrected 2026-08-30 from schematic sheet 4**: the
`RGN-V` divider sits on V-MOT *upstream* of the REGEN switch — so `V_rgn` is the
firmware's motor-node proxy and follows `MOT_PWR_ENABLE`, not `REGEN_ENABLE` — and both
the REGEN and FC-charge switch outputs join at the single `VCHG-IN` node that `V_chg`
senses). The original `SW_REGEN`-gated `V_rgn` made the staged bring-up's P3 gate
unsatisfiable and every simulated bring-up latch `FAULT_MOT_HOTPLUG`. That is enough to
make the §2 mutual-exclusion sequencing visible in the CSV, and it is all the model
claims for the rails themselves — the charger *behind* those rails is modelled
separately, next.

### 4.6 The Ag105 charger model

Unlike the electrical sections above, the charger is modelled at the **status level**,
mirroring `pollAg105()`'s HIL branch in the firmware (which injects `I_charge` and
`ag105_status` directly and skips I2C entirely, while still reading `chargerHasPower()`
from the real switch pins — the sequencing under test is the firmware's own, not the
host's).

```
    chg_path    = (switch & SW_FC_CHARGE) or ((switch & SW_REGEN) and (switch & SW_MOT_PWR))
    v_chg_in    = V_chg          # the shared VCHG-IN node, fed by either path
    chg_powered = chg_path and v_chg_in >= AG105_V_IN_MIN
```

> **A3 fidelity note — the phase-0 VBUS→Ag105 bleed is a no-op under `RT_TD_ON_S`.**
> Measured on campaign 20260830_214819's `soc-depletion` run: `V_chg` reads
> **0.0000 V for the entire run**. The staged bring-up's phase-0 dwell is **10 ms**,
> while the hi-fi RT1987 model holds a switch in `TD_ON` for `RT_TD_ON_S` = **8 ms**
> before it begins soft-starting — so a charger-path switch closed during that phase
> is still in (or barely out of) its turn-on delay when the phase ends, and the node
> never reaches `AG105_V_IN_MIN`. The consequence is that any *bleed* the phase was
> expected to establish from VBUS into the Ag105 input simply does not occur, and
> `chg_powered` stays false. This is a **timing interaction, not a defect in either
> model** — but it means a scenario cannot rely on phase 0 to pre-power the charger:
> it must open `FC_CHARGE_ENABLE` (or the regen pair) for long enough to clear
> `RT_TD_ON_S` plus soft-start. Charge-path scenarios do this explicitly.

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
| `AG105_I_MAX` | 2.5 A | The firmware's own configured charge-current ceiling (reg `0x00` = `0x01`, `Ag105_Table4_Charge_Current_Select.json`). A scenario may **de-rate** it with the `chg_i_ceiling_a` field (same class of knob as `vesc_cap_f`: it sizes the stimulus, it does not model the firmware). `charge-fault` uses 0.8 A and `charge-regen` 1.6 A so their FC-path draw stays under `LIMIT_I_FC_MAX` 1.4 A; the sim prints a line whenever it is de-rated. |
| `AG105_V_IN_MIN` | 8.0 V | Plant-only input-rail floor — see above. **`TODO(verify)`**. |

**⚠️ DATASHEET CORRECTION (2026-08-31): the Ag105's MPPT is an INPUT-VOLTAGE
THRESHOLD regulator, not a perturb-and-observe tracker.** `AG105_Silvertel.pdf`
p.10: charging commences only when the input voltage exceeds a threshold, settable
11–33 V by an MPPTS resistor or I2C register `0x02`, and **defaulting to 18 V with
MPPTS open**. The "perturb-and-observe" wording that appeared in this document, in
`teensy_controller.ino`'s comments and in CLAUDE.md §3 is repo lore with no
datasheet backing. Nothing in the *firmware* depends on the distinction — it drives
one GPIO either way — but a plant model claiming to emulate MPPT must emulate the
mechanism the part actually has.

`MPPT_DISABLE` is active-low on the real hardware (LOW inhibits tracking, HIGH
releases it). **By default the model reproduces only that polarity's effect on the
two tracking flags** in the status byte, and charging continues regardless of the
pin — matching the firmware's own rationale for asserting it during regen (the fast
TL431/BSP170P chopper, not the Ag105, absorbs the transient — see §3.4).

A scenario may set **`mppt_emulation`** to get the threshold gate as well
(`AG105_MPPT_V_HYST` 0.5 V — the hysteresis is on the voltage *comparison*
only, never on the pin, which is the firmware's output and must not be
filtered). **THE THRESHOLD VALUE IS THE BOARD'S, from fw v24:** the firmware
writes reg `0x02` and reports the count it believes is in force on
observation-frame **byte 15**, and the model converts it with
`ag105_mppt_volts()` (11.0 V + 0.088 V/count, `.ino:1671-1677`).
`AG105_MPPT_V_THRESH` 18.0 V is now only the **fallback**, used when there is
no count to use — a count ≥251 (external-resistor mode / never written, which
*is* the datasheet's 18 V default), a legacy 16-byte frame from a fw v21–v23
flash, or the window before the first observation frame. In all three the
module genuinely sits at its factory threshold, so the fallback is the
physical value rather than a placeholder. Semantics, and the asymmetry is the datasheet's own: the threshold
belongs to the MPPT regulator, so it binds **only while tracking is released** (pin
HIGH). Below the threshold there the module reports GENSTAT **001 Low Power** with
`MPPT_EN` set and `PWR_TRACK` **clear** — released, and refusing to track — and the
current decays on `AG105_TAU_S`. With the pin LOW the existing constant-current
behaviour is verbatim. Default **False**, so every scenario predating the key is
byte-identical. `mppt-tracking` is the only scenario that declares it.

**R1 — RESOLVED AS A DESIGN DEPENDENCY (fw v24).** Table 7's own encoding
settles it: reg `0x02` values 0–250 select **register** mode and ≥251 selects
the external MPPTS resistor, so a firmware write **overrides** any fitted
resistor. Whether the board fits one is now documentation, not a contingency —
it decides the threshold only *before* the first write, which is exactly the
fallback window above. `mppt-tracking`'s expectations no longer move with it.

The battery state of charge IS modelled (§4.2 source models), so the CV/Fully-Charged
branch at `soc >= 0.995` is reachable — `charge-to-full` is the scenario that reaches
it, starting from `--soc0 0.990`. There is still no I2C transport: the config
handshake (reg `0x01`=0x08, reg `0x00`=0x01) is not modelled at all, because the
firmware's HIL branch skips it entirely and just injects the resulting numbers.

### 4.7 Simplifications and their consequences

| Simplification | Consequence |
|---|---|
| **No boost-converter dynamics.** The bus is algebraic in `I_total`; there is no voltage loop, no RHP zero, no compensator lag. | Nothing here reproduces the boost-death class of failure, the τ_r lag the share-loop plant is built on, or a converter's transient response. Do not fit `τ_r` or any converter parameter against a HIL trace. |
| **No RT1987 turn-on transient.** A switch bit change takes effect within the same tick. | The *ordering* of switch operations is fully observable at 1 ms; the *hot-plug energy* that killed a boost (Death 5) is not modelled at all. A HIL pass says the sequencing logic is right, not that a real closure would be survivable. |
| **Split proportional to MDAC code ratio.** Sign- and monotonicity-preserving, wrong gain. | Share-loop *logic* testable; share-loop *tuning* not. |
| **Regen modelled end to end (§3.4, WP-C 2026-09-01) — but on THREE unmeasured constants.** The floor is gone: braking energy reaches the chopper and the Ag105. `VESC_REGEN_I_MAX_A`, `ETA_REGEN` and `R_CHOPPER_REG` are all `TODO(verify)`. | The regen PATH, the chopper clamp and the energy BALANCE are now genuine HIL results. The MAGNITUDES are not: a harvest figure from a HIL run inherits the 1.5 A clip's unmeasured commanded-vs-delivered mapping and the 0.80 efficiency guess. Quote the ratio (what fraction the chopper burnt vs the charger banked), not the absolute joules. Bus-side regen rise is still absent by construction, and correctly so — `MOT_PWR` is an ideal diode. |
| **Charger status-level only; MPPT modelled at the THRESHOLD, not the tracking.** `I_charge` and `ag105_status` are injected (§4.6), so `chargingControl()`'s readiness gating and the GENSTAT fault check are live and testable. SoC and the CV/Fully-Charged branch are modelled (§4.2). **MPPT (2026-08-31, scoped; dynamic from fw v24):** with `mppt_emulation` the part's real mechanism — the **input-voltage threshold** (datasheet p.10; **not** perturb-and-observe) — IS modelled at the value the BOARD reports (observation-frame byte 15), and `MPPT_DISABLE` becomes causal. The **tracking dynamics** (how the module walks its operating point once above the threshold) are **not** modelled, and neither is the I2C transport or config handshake. Off by default. | Sequencing and status-decode logic around the charger are meaningful HIL results, and so is the *threshold gate*'s interaction with the firmware's readiness-gated MPPT release (`mppt-tracking`). Charger **tuning** and **harvest-efficiency** results are still not available. ⚠️ The `mppt-tracking` **hunt is fw v23 history and is now the FAILURE signature** — fw v24 lowers the threshold under the bus, so the scenario asserts harvest holding, not hunting. |
| **Single lumped bus node.** No wiring impedance, no per-source bus segment, no capacitance between nodes. | Handoff-gap phenomena of the TP0178 class (a source dropping out and the other ideal diode picking up only reactively) are not reproduced faithfully; the split here is instantaneous. |
| **No sensor noise, no quantization, no ADC path.** | Steady-state error in a HIL drive run validates the loop's *structure*, not its noise rejection. There is no encoder jitter, so the current-side chatter seen on the bench cannot appear. |

---

## 5. Actuator inputs — what the plant consumes

Everything the plant reads about the board comes from the **17-byte** (fw v24)
observation frame, decoded by `parse_output()` (which validates length, sync
`0xB6` and the length-derived XOR span, returning `None` on any failure). The
**16-byte** fw v21–v23 layout is still accepted — same offsets below byte 15,
XOR over bytes 1–14, and `mppt_cnt` decodes as `None`. `parse_output()` prints
the length once and warns loudly if a run sees both.

| Frame field | Plant use |
|---|---|
| `mppt_cnt` (byte 15, fw v24) | the Ag105 reg-`0x02` count in force → the MPPT threshold the charger model gates on (§4.6); `None` on a legacy frame → the `AG105_MPPT_V_THRESH` fallback. Also written to the CSV as `mppt_thresh_cnt` |
| `switch` bit `SW_FC_BUS` (0x01) | with `AUX_FC_REG` → `fc_live` (§4.1) |
| `switch` bit `SW_BT_BUS` (0x02) | with `AUX_BT_REG` → `bt_live` |
| `switch` bit `SW_MOT_PWR` (0x04) | `mot_live` → gates motor force (§3.3), motor bus draw (§4.3), and `V_rgn` = `V_bus` (the RGN-V divider is on V-MOT — §4.5) |
| `switch` bit `SW_REGEN` (0x08) | with `SW_MOT_PWR` → feeds `V_chg` (shared VCHG-IN node, §4.5) |
| `switch` bit `SW_FC_CHARGE` (0x10) | feeds `V_chg` = `V_bus`, else the regen path or 0 |
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
| `steady` | `i_aux` held at 0.15 A | quiescent baseline: bring-up, Idle, telemetry, the link itself | `V_bus` ≈ `V_BUS_DROOP_V0` (15.95 V) − `k`·`I_total` with the F1-corrected, mode-aware `k` (§4.2: `K_DROOP_BUS_SHARED` 0.074 V/A with both sources live, `K_DROOP_BUS_SINGLE` 0.1615 V/A with one) — at `i_aux` = 0.15 A alone that is a sub-30 mV droop either way, i.e. `V_bus` stays within noise of 15.95 V; `fault_flags == 0`; observation `state` settles at 1 (Idle); simulator rx rate ≈ 1 kHz. This is H1. |
| `step-load` | `i_aux` → 0.15 + **1.2 A** at t = 5 s (step, held) | share loop's disturbance rejection: `I_total` steps, both source currents rise, the droop node sags by `k`·1.2 A — **0.074·1.2 ≈ 0.089 V** with both sources live (the common case), or **0.1615·1.2 ≈ 0.194 V** if only one is (the old single source-agnostic 0.35 V/A figure this table used to quote is retired — see §4.2) | Share loop moves the MDAC codes to restore `power_share_actual` toward its setpoint; the split ratio visibly tracks. Note §4.4 — the *direction* is meaningful, the *gain* is not. |
| `v-bus-sense-offset` **(hifi only)** | `v_bus_offset` = **−5.0 V** for `5.000 ≤ t < 5.012` s (12 ms) and again for `8.000 ≤ t < 8.060` s (60 ms) | `UV_BUS_DWELL_LATCH_MS` (20 ms) from BOTH sides — the first excursion must not latch, the second must | ≈ 10.9 V measured, 1.1 V clear of the limit, so the dwell accrues at the full 1 ms/tick and no sample sits on the boundary. The 3 s gap is 12.5× the 240 ms the `UV_BUS_DWELL_LEAK` 0.05 needs to drain the first excursion, so the second latches on its own 60 ms. **hifi is required, not preferred:** here the offset is sense-path-only (§ the `v_bus_sense_offset` asymmetry below), so nothing but the measured rail moves — in simple mode the same offset is a real disturbance the sources answer, and the dwell measurement would be confounded by the current transient it causes. |
| `sag` | `v_bus_offset` = **−5.0 V** for `5.0 ≤ t < 6.0` s | the **real** undervoltage path: `LIMIT_V_BUS_MIN` 12.0 V with the `UV_BUS_DWELL_*` leaky-integrator filter (`UV_BUS_DWELL_LATCH_MS` 20 ms net dwell to latch) | ≈ 16 − 5 ≈ 11 V, ~1 V under the limit, for 1 s — far past the 20 ms dwell. Expect `mainState` → **99**, the UV bit latched in `fault_flags`, and the switch bitmask going to the State-99 safe combination. Crucially, **no fault before the dwell elapses**. This is H2. Requires the bus to be armed (`uvBusArmed`), i.e. the bring-up must have reached `V_BUS_CHARGED_THRESH` first. |
| `comm-loss` | transmit suppressed for `5.0 ≤ t < 6.0` s; the plant keeps integrating and logging | the two-stage hold-then-zero in `updateSensors()` | ≤ 50 ms: unchanged. 50–250 ms: values **held**, `hilStale` set, and on the **stale entry edge** `haltMotorOutput()` stands the actuator down (setpoint zeroed, Youla state reset, 0 A sent) — the sensors stay held so a missed tick cannot latch a bogus UV fault. > 250 ms: all seven rails and `v_actual` forced to zero, host unbound, and `triggerFault(FAULT_HIL_LINK, ERR_HIL_STALE)` latched — `ERR_HIL_STALE` = 0x10 disambiguates the deliberate `FAULT_PI_TIMEOUT` bit alias. On resume the link re-locks and the accept count resumes. This is H3. |
| `drive` **(operator-required)** | none; `i_aux` at nominal. `run_hil_suite.py` renders this SKIPPED unless `--with-operator` is given — unattended it commands nothing. | whatever the operator commands over USB serial (`'V'`, `'D'`, `'Y'`, `'W'`, State-98 generally) | The plant just stays honest underneath a hand-driven run. `v_actual` in the CSV should converge on the setpoint with no sustained ±12 A rail chatter; `current` should show the Hanus-conditioned ramp and release. This is H4 — and since the model has no encoder noise, it validates the loop's *structure*, not its tuning. |
| `charge-cruise` | pi-command timeline: → Run at 3 s, cruise `v_setpoint` 1.2 m/s at 5 s, **`charge_goal` 1.0 at 8 s** | `chargingControl()`'s cruise branch: `assertFcChargeEnable(true)` on **intent**, the `AG105_SETTLE_MS` window, `ag105IsReady()`, the MPPT release | `switch` gains `SW_FC_CHARGE` (0x10) and **loses** `SW_BT_BUS` (the guard drives it low first); `ag105_status` walks `0x00` → Bring-Up → `0x42` Charging+CC; `aux` bit2 `MPPT_DISABLE` goes **HIGH** (released, active-LOW) once ready. Requires `--electrical` either mode. |
| `charge-regen` **(EMS-driven, redesigned 2026-08-30)** | the `regen-harvest` strategy ramps `v_setpoint` 2.5 → 0.4 m/s at **1.0 m/s²** three times, and asserts `charge_goal` **only inside a braking window**. The old design stepped `v_setpoint` to 0, which is below `V_SP_ZERO_THRESH` (0.07 m/s) — the firmware commanded 0 A and those segments **coasted**, never entering regen at all; and it commanded `charge_goal` simultaneously with acceleration, which opened the single-source `FC_CHARGE` path and latched `OC_FC` 6.4 s before the first brake. A *continuous* commanded deceleration exceeding the coast rate `a_coast(v) = (F_c + b·v)/m` is the only way to hold a negative command past the 0.5 s Ag105 settle; a step rails for at most ~0.8 s. | `chargingControl()`'s regen branch and the REGEN ⇄ FC_CHARGE **mutual exclusion** | During each brake: `SW_REGEN` (0x08) set, `SW_FC_CHARGE` **clear** (never both), `MPPT_DISABLE` driven LOW (inhibited). Between brakes the pair swaps back. |
| `charge-fault` | charging established, then at **t = 20 s** the charger input rail collapses (`plant.chg_fault`) | the charger-loss path: `chargerHasPower()` going false, the settle timer re-arming, the GENSTAT decode in `detectFaults()` | `V_chg` → 0, `I_charge` → 0, `ag105_status` → `0x00` (GENSTAT 000, Battery Disconnect), `ag105IsReady()` drops and the MPPT release is withdrawn. |
| `soc-depletion` | share commanded fully onto the **battery** at t = 5 s, then `i_aux` **ramps** to +2.2 A over 3 s from t = 10 s (reduced from 3.0 A: `share_sp = 0.0` is below `DROOP_R_MIN`, so `updateShareSetpointCutoff()` cuts FC *off the bus* entirely and BT alone carries 0.15 + load — 3.15 A at the old value, over `LIMIT_I_BT_MAX` 3.0 A; now 2.35 A, 22 % margin. **Suite override re-derived 2026-08-30: `--soc0` 0.20, duration 400 s** — the previous 0.15 / 880 s pair used the 2.2 A *bus-side* load as the coulomb current, when the pack sits behind the boost and delivers ≈ 6.19 A, and it ignored that the `UV_BATT` latch is a *state* condition at `soc_latch ≈ 0.113`, which ends the run. From 0.15 the maximum observable SoC fall was 0.037, below the 0.05 signal threshold at **any** duration; from 0.20 the ceiling is 0.087 = 1.74× it, with the latch expected at ≈ 266 s. The signal gate is now disjunctive — the 0.05 fall **or** a post-ramp `UV_BATT` latch — because the two proofs foreclose each other) (staggered: both landing on one tick put 1.47 A on FC for a single sample — 5 mA over `LIMIT_I_FC_MAX` — and latched `OC_FC` 645 s before the objective) | the honest `LIMIT_V_BATT_MIN` / UV_BATT path, driven by a real coulomb count rather than a step | `V_batt` walks **down the OCV curve** (§9.2) as `soc` falls; `Rs(SOC)` steepens the sag below 15 % SOC. **Practical note:** at 5 Ah a multi-amp draw is a ~100 min run — use `--soc0` (the suite passes **0.20**) and/or `--capacity-ah` to bring it inside a bench session. The model is deliberately *not* accelerated: a faked SOC ramp would also fake the RC-pair and `Rs(SOC)` dynamics the UV path actually sees. |
| `ems-soc-band` **(EMS-driven, 2026-08-31)** | 61 s profile plus a **1.0 A bus drain** (`SOC_BAND_DRAIN_LOAD_A`, ramped in from t = 10 and out from t = 38) whose only job is to move the coulomb count out of the `soc-band` policy's deadband inside a bench run. Bounded on both sides: large enough that SoC crosses (pack-side ≈ 1.82 A → 1.01e-4 SoC/s, band exit measured t = 24.30), small enough that the policy's 0.75 share ceiling puts only 1.09 A on FC against `LIMIT_I_FC_MAX` 1.4 A (22 % margin). Charge ceiling de-rated to **0.8 A**, charge-fault's budget verbatim. | The **`soc-band`** EMS law (deadband-P share bias + opportunistic FC-path charging), the share loop under a commanded bias, `chargingControl()`'s cruise branch, and the **H2 metric** (§9.3) end to end. | Commanded `cmd_share_sp` walks 0.50 → **0.75** from t = 24.30, saturating at t = 34.90; `I_fc` rises above the nominal half of the bus total; a charge window opens at t = 41.70 in the 1.0 m/s cruise (`SW_FC_CHARGE` set, `SW_BT_BUS` cleared, `I_charge` > 0.5 A by t ≈ 42.6); `h2_cum_g` accumulates ≈ 5e-3 g. **Expected fault-free.** ⚠️ The policy closes on plant-truth SoC and is **not portable to a real Pi** as written — see the `SocBandStrategy` banner in `tools/hil_plant_sim.py`. |
| `ems-dp-replay` **(EMS-driven, NON-CAUSAL BENCHMARK, 2026-08-31)** | the SAME 61 s profile and the SAME 1.0 A drain as `ems-soc-band` — the scenario entry is *derived* from it and shares the `ems_v_profile` **list object**, and `apply_scenario()` applies one drain branch to both names, so nothing but the decision rule differs. | The **`dp-replay`** playback of an offline dynamic-programming solution (§9.4): the share loop under a commanded rail, and the H2 metric (§9.3) as the comparison surface against `ems-soc-band`. | `cmd_share_sp` **0.250** while the bus is quiet, ramping from t = 4 and **pinned at 0.750 over t = 10.6–40.1** (`I_fc` ≈ 1.10 A of a ~1.46 A bus total), ≈ 0.525 through the low cruise, back to 0.250 by t = 55.5. `charge_goal` is **0 for the whole run** — a result, not a gap (§9.4). **Expected fault-free.** ⚠️ NOT a controller: it reads no feedback, and it refuses to start unless the active scenario's profile fingerprint matches the table's. |
| `ems-sdp` **(EMS-driven, CAUSAL SDP POLICY, 2026-08-31; RE-MAPPED to `v2` the same day; REBOUND to the CALIBRATED `v3` artifact 2026-09-01 — see the role note at the end of this cell)** | the SAME 61 s profile and the SAME 1.0 A drain as `ems-soc-band` and `ems-dp-replay` — the entry is *derived* from the first and shares its `ems_v_profile` LIST OBJECT, and `apply_scenario()` matches all three names on one drain branch, so the three-way comparison is on a bit-identical stimulus. Charge ceiling **0.8 A**, inherited. `electrical: any` (unlike `ems-dp-replay`, this leg has no offline hydrogen accounting that must match the engine). | The **`sdp-v2`** strategy: a STATE-indexed policy (SoC x demand bin) baked offline by stochastic DP (`tools/sdp_ems_solver.py`, artifact `tools/sdp_policies/sdp_policy_v2.json`), looked up every `decision_dt_s` = 1 s and held between decisions. It is the CAUSAL optimal-by-construction leg between the `soc-band` heuristic and the non-causal `dp-replay` bound. ⚠️ **`v1` vs `v2`:** `sdp_policy_v1.json` was solved against the TPM sidecar's IDEAL-SCALING demand span (−1.125…+1.640 W). This rig measures 0…22.887 W, so campaign `hil_report_20260831_191509` clamped ~98 % of decisions into the top bin: the demand axis carried no information and one constant share was emitted for the whole run. `v2` is the SAME TPM re-solved against a **[0.0, 25.0] W consumer demand map** (solver D11 has the derivation); both files declare the same `schema`, so only `normalization` and the policy-block sha distinguish a `v1` trace from a `v2` one. | Measured by an OFFLINE WALK of the strategy's own decision path over the campaign's recorded P_dem/SoC trace (⚠️ open loop — it cannot contain the plant's response to a command `v2` issues and `v1` did not): **61 decisions, ZERO clamps either way, 13 distinct demand bins** (0, 2–7, 9, 10, 12, 16, 17, 22) against `v1`'s single bin 24. The share law is bang-bang by construction (the stage cost is piecewise-linear in the share, so its minimum is at a vertex): the table's whole value set is {0.00, 0.90, 0.95, 1.00}, and on this run it asks **0.95 over the drain plateau** (bin 22, t = 13…38) and **1.00** elsewhere. **Both emit as the HARDWARE-ENVELOPE CLAMP 0.8500** (`[SOC_BAND_SHARE_MIN, SOC_BAND_SHARE_MAX]`, `SdpStrategy.clamp_share()` — the same clamp `soc-band` applies, actuation-side only, table untouched, raw value counted and printed): a rail would sit outside `[DROOP_R_MIN, DROOP_R_MAX]`, cut BT off the bus and run single-source FC into the ~1.45 A drain past `LIMIT_I_FC_MAX` — an OC latch that would truncate the run and destroy the three-way comparison. ⚠️ **So `cmd_share_sp` cannot distinguish `v1` from `v2`; the `cmd_share_sp_raw` column (§7.1) can.** At the clamp the firmware's own governor clips further to `1 − I_min/I_tot` = 0.798 at the **measured 1.4866 A** drain peak: **I_fc 1.1866 A (15.2 % margin under LIMIT_I_FC_MAX)** — campaign `20260831_191509` measured values; the 1.462 A / ~1.16 A / 17 % triple this line used to carry was the pre-campaign estimate, BT minority exactly `SHARE_MINORITY_I_MIN_A` 0.30 A, no cut attempted, so `SHARE_CUT_MAX_HANDOFF_A` never enters. ⚠️ **NEW UNDER `v2`: a charge window is reachable.** The solver's FC-current budget forbids charging above bin 5 and its dwell rule above bin 11, so `charge_goal` = 1 exactly in bins 0–5 (P_dem < 6.0 W) below the relative target — which the walk lands on **t = 41…58**, the same post-drain 1.0 m/s cruise `soc-band` charges in, reached by a different rule. Budget: 5.593 W / 15.95 V = 0.351 A + 0.800 A ceiling = **1.151 A, 18 % margin**, i.e. `ems-soc-band`'s own validated charge-window operating point. ⚠️ **Predicted 1 Hz chatter of `FC_CHARGE_ENABLE`** (derived, not measured): opening the path adds ~0.8 A to I_fc, so the measured P_dem jumps ~5.6 → ~18.3 W = bin 18, which is charge-forbidden, and the next decision withdraws the intent. The policy is memoryless in the demand bin and has no hysteresis (`soc-band` avoids this with its dual i_tot gate), so ~8 open/close cycles are expected, each costing a BT_BUS cut and restore through `assertFcChargeEnable()`. Neither state exceeds a current limit; do **not** assert `I_charge` here the way `ems-soc-band` does, since the Ag105 may never reach `chargerReady` inside a 1 s window. **Expected fault-free over the full 61 s**; `h2_cum_g` ~1e-2 g. ⚠️ Read its `delta_soc` with the hydrogen number. ⚠️ SIM-ONLY (plant-truth SoC), like `soc-band`. PROVENANCE: the artifact's POLICY-BLOCK sha256 is `740c802e…` (`v1`'s was `dbe42d1b…`; recipe `sha256(json.dumps(doc["policy"], sort_keys=True))`) — the decision law, stable across a regeneration that did not change it, and the digest to quote. The FILE sha moves on every regeneration (`generated_utc`), so it is recorded PER RUN in the CSV meta sidecar under `config.sdp_policy` alongside the policy-block sha, `generated_utc`, the grid shape and the TPM sha. ⚠️ **REBOUND TO `sdp-v3` ON 2026-09-01 (the charge-economics ruling).** Campaign `20260901_000816` measured this leg OFF the EMS frontier (+12.78 % over the DP bound, 1.54 % worse than the `soc-band` heuristic), and the cause was the charge action described above: `v2`'s alpha prices SoC at 5.139 g/SoC, i.e. an admission threshold of **0.1946 SoC/g**, while the Ag105's measured charge lever is **0.2364** and the share lever is **0.409-0.415** — every lever in that gap is taken by the solver and scored as a loss. `sdp_policy_v3.json` (policy-block sha256 `0443febf…`) re-derives alpha by two-sided lever calibration and the charge action is then declined **ENDOGENOUSLY**: zero charge cells in all 101 x 25, `forbid_charge_all` FALSE. **So everything in this cell about the charge window is now HISTORY** — under `v3` the suite asserts `charge_path_never_opens` instead, and the chatter/hysteresis paragraphs describe a mechanism this leg no longer reaches. **The share half is unchanged:** the two artifacts' `policy.share` differ on SoC rows 1-2 only, which this trajectory (row 50, falling ~0.0017) never reaches. `sdp_policy_v2.json` is BYTE-FROZEN as the DYNAMICS DEMONSTRATION artifact for `ems-sdp-cross` / `ems-sdp-braking`. |
| `ems-ftp75-sdp` **(EMS-driven, opt-in, SDP-INTERIOR ROUND, 2026-08-31; rebound to `sdp-v3` 2026-09-01)** | the SAME EPA FTP-75 profile LIST OBJECT as the other two FTP-75 scenarios, at a **re-derived 0.45 A preload** (`FTP75_SDP_PRELOAD_A`, not the siblings' 0.65 A), driven by **`sdp-v3`, playing `sdp_policy_v3.json` (policy-block sha256 `0443febf…`)** with **`sdp_soc_ref_offset` = +0.013**. (Every action quoted below was read off the `v2` artifact `740c802e…`; the two share maps are identical on SoC rows 3+ and this trajectory never leaves them — see the row-diff test.) | The SDP policy's **bang-bang SHARE law**, which no run before this round could put on the wire: every earlier `ems-sdp` run started EXACTLY on the policy's target node and could only discharge, so the table sat on its fuel-cell branch and the wire carried ONE constant clamped 0.8500 for the whole run. The offset starts the run 0.013 SoC ABOVE the node, i.e. on the table's OTHER branch (action 0.00, emitted at the `SOC_BAND_SHARE_MIN` clamp as **0.15**), and the cycle's own drain walks the state across the switching boundary. | OFFLINE WALK (2026-08-31, method in the SCENARIOS entry; cross-checked against the MEASURED `ems-ftp75-5050` trace of campaign 20260901_000816, which runs +2.6 % hot against the model): a SINGLE share step **0.15 -> 0.85 at t = 195.9 s**, +/-10 % of drain moving it to 180/205 s and +/-20 % to 158/216 s - hence the suite's (150, 250) s band. Raw table requests {0.00} before, {1.00, 0.95} after. **NO charge stage is reachable** (demand never falls below bin 9 in Run), so this is a pure share-axis test. Currents: on the battery-heavy branch the commanded 0.15 is always below the governor's minority floor, so **I_fc is pinned at 0.300 A** and peak I_bt is 0.676 A (77 % under `LIMIT_I_BT_MAX`); on the fuel-cell branch **I_fc = I_tot - 0.300**, peaking at 1.112 A model / **1.1546 A measured** (the ADDITIVE composition 0.15 + 0.45 + 0.8546 - 0.300; do not scale the model's FC branch by the +2.6 % offset, which also scales the firmware's fixed 0.300 A governor floor and reads 1.141 A) - **17.5 % under `LIMIT_I_FC_MAX`**, which is what sized the preload down from 0.65 A (there the same peak is 1.355 A, 3.2 % of margin, and an OC_FC latch would truncate the run at exactly its post-flip half). **Expected fault-free**; `allow_only: 0`, unlike its socband sibling. ✔ **CALIBRATED, campaign `20260901_024231`** (the `provisional_note` is deleted): flip MEASURED at **198.537 s** (+1.35 % on the walk — an integral quantity inside 1.4 %, this walk's best result), so the band tightened (150, 250) -> **(185, 212)**; `I_fc` peaks 0.3039 A pre-flip / 1.1516 A at the cycle peak (ceilings/floors now 0.35 / 1.08 A); `I_batt` peaks 0.7117 A **at the flip**, newly bounded at 0.90 A; `h2_cum_g` 0.0621749 g, band [0.020, 0.120] -> **[0.056, 0.070]**. Bin 24 was NOT entered, so the 0.89 raw floor deliberately stays at its boundary-case value rather than tightening to the measured 0.95. ⚠️ **REBOUND TO the calibrated `sdp-v3` artifact on 2026-09-01, AND THE WALK TRANSFERS VERBATIM.** The walk above was measured against `v2` and was NOT re-run, because a row-by-row diff settles it: `policy.share` is identical at every SoC row from 3 upward (the two artifacts differ in 30 cells, all on rows 1-2) and this scenario spans rows ~63 down to ~44. On the charge axis, `v2`'s cells sit in demand bins 0-5 only and this walk's demand never falls below bin 9 in Run, so `v3`'s zero map removes cells the trajectory could not visit either way — 'no charge stage is reachable' was already the claim and is now additionally true by construction. |
| `ems-sdp-cross` **(EMS-driven, SDP-INTERIOR ROUND, 2026-08-31)** | a **two-level cruise** - 2.2 m/s to t = 70, then 1.0 m/s to the Run exit at 196 - with **no preload** (`I_AUX_A` alone), 200 s, charge ceiling 0.8 A, `sdp_soc_ref_offset` = **+0.0025**. The high level sits at P_dem ~10.6 W (bin 10, charge-FORBIDDEN) and above the 0.60 A closed-loop gate, so the governor's minority floor keeps 0.30 A on the standby channel and both the pre-flip drain and the post-flip node traverse are fast enough to fit a bench run; the low level sits at P_dem 5.37 W (bin 5, the top charge-admissible bin) - `ems-soc-band`'s own validated charge operating point. | The artifact's **two SoC switching surfaces**, which are one grid node apart: node >= 51 gives share 0.00 with no charging, node 50 gives 0.85 with no charging (a 1e-3-wide dead band), node <= 49 gives 0.85 **with** charging in bins 0-5. So this run crosses the SHARE threshold downward and then cycles on the CHARGE threshold. An UPWARD share crossing is **not reachable on this rig** - it would need a charge ceiling above 2.25 A, which on the single-source FC path is an immediate OC_FC - and nothing in the entry asserts one. | OFFLINE WALK: share **0.15 -> 0.85 at t = 43.85 s** (the run's only share transition), then **three sustained charge windows** - 75.4-83.8, 115.3-123.7, 172.9-180.9 s - each one `SDP_CHG_MIN_DWELL_S` long, period ~50-57 s. One 1.05 s admit-then-drop at t = 73.3 INSIDE the deceleration is EXPECTED and not asserted: the demand falls into bin 5 before the ramp ends and `charge_hold_status()`'s `SDP_CHG_CRUISE_DELTA_MPS` guard withdraws the intent on the next decision - the only live exercise that early-drop branch has ever had. Peak I_fc 1.1372 A (single-source FC carrying 0.337 A of load plus the 0.8 A ceiling), **18.8 % under `LIMIT_I_FC_MAX`**; peak I_bt 0.6087 A. SoC 0.700000 -> 0.697195. **Expected fault-free.** No board-side SHARE-BRANCH check is possible here and the suite entry says so: at 0.67 A of total the governor clips both branches to within 0.07 A of each other. ✔ **CALIBRATED, campaign `20260901_024231`** (the `provisional_note` is deleted) **— AND THIS SCENARIO PRODUCED THE ROUND'S ONE FAILURE.** MEASURED: flip **42.292 s** (-3.5 % on the walk, band (25, 65) -> **(35, 50)**); **NINE** charge windows at a **16.13 s** period, gaps 8.04-8.08 s (sigma 17 ms), 64103 of 120000 ticks over t = 70..190 (released fraction 0.466), longest hold **8.085 s** = `SDP_CHG_MIN_DWELL_S` + 1.1 %; `I_charge` reached its full 0.8000 A ceiling (floor 0.5 -> **0.75 A**); `I_fc` peaked **1.1920 A**, 14.9 % under `LIMIT_I_FC_MAX`, now bounded at 1.28 A. Both switching surfaces located for the first time: share at SoC 0.69800, charge at 0.69700, both on the predicted grid nodes. ⚠️ **THE WALK'S CHARGE PERIOD WAS WRONG BY 5.7x**, and the retired check `sdpx_charge_released_between` asserted the ABSENCE of a window at t = 90..108 s taken from it — so it sat on top of a real window and failed a correct board. Root cause: the walk applied the firmware's CLOSED-LOOP minority governor at a cruise drawing I_tot ~ 0.355 A, below the **0.55 A open-loop drop-out** (`.ino:9933`), where the board HOLDS its last converged split — delivered share **0.1656** against the commanded 0.85, so the real drain is -3.90e-5 SoC/s, not ~6.9e-6. The check is replaced by four PHASE-FREE properties (tick floor 12000 -> **45000**, `max_continuous_ticks` <= 9000, released-fraction ceiling 84000 ticks, `edge_count_between` (6, 12)). |
| `ems-sdp-braking` **(EMS-driven, SDP-INTERIOR ROUND, 2026-08-31)** | **four braking cycles** - 10 s at 2.2 m/s, 3 s decel to 1.0 m/s, 12 s plateau, 6 s accel back - built from the `SDP_BRAKE_*` constants (the profile is GENERATED, and asserts that its last plateau ends exactly at the Run exit), 134 s, no preload, charge ceiling **0.7 A**, `sdp_soc_ref_offset` = **-0.005**. | The policy's **charge decision on the DEMAND axis alone**. Starting below the target node pins the share command at a constant 0.85 for the whole run BY DESIGN, so with the SoC axis held still every FC_CHARGE transition in the trace is attributable to demand: the low plateaus are bin 5 (admissible) and the cruises are bin 10 (forbidden). **HONEST CAPTION: the SoC rise is FUEL-CELL-FED through FC_CHARGE, not regen harvest** - by this scenario's own demand-axis design (the decel plateaus are the charge-admissible bins), this validates the policy's decel-window charge behaviour and NOT regen capture. The zero-regen-power floor this caption used to blame was removed by the regen-fidelity model round (WP-C, shipped 2026-09-01) — regen capture itself is now exercised by `regen-harvest-true`, not by this scenario. | OFFLINE WALK: **four sustained windows, one per plateau** - 21.3-34.4, 52.2-64.8, 83.7-96.3, 114.2-126.0 s, 50.1 s of charging total - and **ZERO charge ticks inside any of the four cruise holds**. Five ~1.05 s admit-then-drop blips (Run entry plus one per deceleration), same cruise-guard mechanism as `ems-sdp-cross`'s, each shorter than `AG105_SETTLE_S` so no charge is actually delivered; expected, not asserted. Peak I_fc **1.1671 A at t = 34.4**, which is the ONE-DECISION charge overhang into the acceleration out of a plateau - the cruise guard withdraws the latch only at the next decision, so the accel current adds to the charger's on the single-source FC channel. That peak is why BOTH `SDP_BRAKE_ACCEL_S` (6.0 s = 0.20 m/s^2) and `SDP_BRAKE_CHG_CEILING_A` (0.7 A) are current-budget constants: at 0.40 m/s^2 and 0.8 A the same peak is 1.379 A, **1.5 %** under `LIMIT_I_FC_MAX`. As shipped it is 16.6 % under. Peak I_bt 0.300 A (the minority floor, all run). SoC 0.700000 -> 0.699662 - very nearly charge-sustained. **Expected fault-free.** ✔ **CALIBRATED, campaign `20260901_024231`** (the `provisional_note` is deleted) **— AND THIS WALK WAS RIGHT, for a stated reason:** these windows are DEMAND-driven, so they land on the profile's own fixed instants rather than on an integrated drain (contrast `ems-sdp-cross`, whose SoC-driven period the same walk missed by 5.7x). MEASURED: four sustained windows of four, **52.479 s** (walk 50.1, +4.7 %; floor 25000 -> **45000** ticks), longest 13.108 s, **ZERO** ticks inside both asserted cruise windows (ceiling 500 -> **100**), and the walk's **five** cruise-guard early drops to the instant (t = 3.008 / 19.175 / 50.390 / 81.624 / 112.842) - the first live exercise of that branch, now censused by `sdpb_charge_edge_census` at 8-10 rising edges = 4 windows + 4-6 drops. `I_charge` reached its full 0.7000 A ceiling (floor 0.4 -> **0.65 A**). ⚠️ Peak `I_fc` **1.2617 A** at t = 65.51 in the one-decision overhang - **9.9 % under `LIMIT_I_FC_MAX`, the tightest margin in the suite** and 8.1 % above the walk's 1.1671 A. Newly asserted by `sdpb_fc_peak_bounded` at 1.32 A; never raise it to make a run green. |
| `handoff-sag` **(hi-fi only)** | cruise from 4 s with a **+0.40 A pre-load** (pre-rail total ~0.74 A: above the 0.60 A closed-loop governor gate, below the cut's 0.5 A/channel handoff guard), share commanded to **0.0** at 6 s so the **FC** channel is cut, then a **+1.5 A** step at 20 s against the surviving BT channel (2.24 A vs `LIMIT_I_BT_MAX` 3.0 A, 25 % margin) | the share **setpoint latch** (`updateShareSetpointCutoff()`, `.ino:9231-9257`) opening a bus switch, its `SHARE_CUT_MAX_HANDOFF_A` 0.5 A load guard, and the single-source sag + UV dwell decision that follows | Bus switch open and held open, a deeper single-source droop, and either a clean ride or a correctly-latched `UV_BUS`. ⚠️ **Not** a reactive-pickup test: a setpoint-latched cut drives the switch EN-low, and an EN-low RT1987 does not conduct — nor will the firmware re-close it (the re-closers gate on `!shareSpCut*`). The rail direction is BT-surviving because at the FC rail the 1.4 A limit leaves too little perturbation budget to excite anything. Refused under `--electrical simple`. |
| `bringup` **(hi-fi only)** | none; plant from dark | the firmware's staged bring-up P0–P3 against the **real** RT1987 `t_D(ON)` 8 ms + soft-start ramps (~19.8 ms on the 100 nF switches, ~1.07 ms on the 5.6 nF ones) | Operator runs `'G'`; the phase timings in the USB log should sit outside the switch delays rather than racing them. |
| `scp-inrush` **(hi-fi only)** | VESC input capacitance forced to the **top of the envelope (0.9 mF)**, and a **three-phase V-MOT load** (behind the switch, *not* `i_aux` on VBUS; 2026-08-31 deterministic redesign): the bring-up P3 ramp runs **unloaded**, a **6.5 A fold pulse** (`SCP_INRUSH_FOLD_LOAD_A`) steps in once V-MOT crosses `SCP_INRUSH_ARM_V` 1.2 V mid-soft-start (above the model's 1.0 V Norton load floor, so the full current appears in one substep and the cut fires inside that same 1 kHz tick — phase-independent of the firmware's OC teardown), a one-shot latch withdraws it, and a **5.0 A run load** at +110 ms latches `OC_FC`. The pre-redesign t = 0 flat 5.0 A load faded in through the Norton floor and its cut raced the firmware's teardown (the 2026-08-31 two-outcome episode); the older-still +6 A at t = 8 s arrived when `MOT_PWR` had been ON since t ≈ 0.62 s, and the foldback branch exists only in `SOFT`: **zero** `scp_cut`/fold events fired. | RT1987 soft-start **foldback** on `MOT_PWR` | `scp_cut` + `sw_ring` entries in the event sidecar. Verified offline: the margin holds at 2 A (soft-start completes, `V_mot` reaches 15.1 V) and breaks at ≥ 4 A into a **64 ms burst-retry cycle** — the Death-5-class ring pattern. **Not** the Death-5 stimulus itself: that was a full-bus hot-plug onto a discharged node, no longer reproducible (`MOT_PWR` carries a 100 nF CSS and the firmware pre-charges the node). This is the nearest *legitimate* case that can still bind the foldback. Ring peaks here stay under the 20 V abs-max because the cut happens at low `V_mot`; a cut at full bus on `--trace-config long` (BT, 3.480 nH) does cross it. |
| `ems-y-b30-v1`, `ems-y-b30-v3` **(EMS-driven, 2026-08-31)** | the firmware's own `'Y'` combined table (16 regions, 40 s), copied VERBATIM from `.ino:3162-3179` into `hil_plant_sim.COMBINED_PROFILE` and walked by `y_profile_at()` — an exact reproduction of `advanceComboRegion()` (`.ino:7806-7836`), including the clip-AFTER-interpolation rule and its intended kink. Vmax 1 and 3 m/s at the firmware's documented bound b = 0.30, plus a **+0.85 A `aux_preload_a`** (`Y_AUX_LOAD_A`, raised from 0.60 A on 2026-08-31) that holds the source total in **1.00–2.27 A**, above the 0.60 A closed-loop governor gate for the whole table. ⚠️ **Why it was raised, and why b30 results do not cross the change:** at 0.60 A the firmware's minority-current governor clipped the share to `1 − I_min/I_tot` = **0.624 / 0.672** at region 6 — *below* the table's own 0.70 clip — so the hi bound was **structurally undeliverable** and every b30 run characterised the governor instead (campaign `hil_report_20260831_191509` measured the rails at 0.632 / 0.679). At 0.85 A the bounds land at 0.714 / 0.743 and both the hi (0.70) and lo (0.30) clips are reachable at both speeds. Worst channel currents 0.999 A FC (28.7 % under `LIMIT_I_FC_MAX`) / 1.475 A BT. ⚠️ The preload **ramps in** over `SOC_LOAD_RAMP_S` from t = 4.0, so the table's first **0.59 s** (was 1.25 s) is still below the gate — inside region 0's settle, so no assertion window is affected. ⚠️ The commands are evaluated at 50 Hz, not the firmware's ~1 kHz: the share axis is unaffected (the share loop's own tick is 50 Hz), and the motor axis quantises to ≤ 12 mm/s at Vmax 3, against `e_sat` ≈ 26.4 mm/s. | **Closed-loop share tracking** under a two-axis cross-coupled excitation — the reason the firmware's table exists — reachable unattended for the first time. | `cmd_share_sp` reaches its clip **0.70** in region 6 (t = 22.0–23.5), sweeps 0.65 → 0.30 across region 10 (t = 32.0–35.0); `cmd_v_sp` reaches ≈ 0.996·Vmax at the region-7 ramp top (t → 27.0); `I_fc` ≥ **0.50 A** (Vmax 1) / **0.66 A** (Vmax 3) through **region 3 alone** (t = 13.0–16.0, where v is held constant so only the share command moves `I_fc`), against measured 0.50-split peaks of 0.4353 / 0.5850 A and measured true-run peaks of 0.5659 / 0.7606 A. ⚠️ Window and floors RE-DERIVED FROM MEASUREMENT 2026-08-31 (campaign `hil_report_20260831_191509`): the previous t = 13–20 window included region 4's ramp, where a 0.50 split alone reaches 0.4915 / 0.9217 A, and the MODELLED 0.58 / 0.80 floors sat above the true run's own region-3 peaks; the 0.45 / 0.60 pair before them belongs to the 0.60 A stimulus. **Expected fault-free.** |
| `ems-y-b00-v1`, `ems-y-b00-v3` **(EMS-driven, 2026-08-31)** | the same table at **b = 0.00** and with **NO preload**. Regions 6 and 11 command share 1.00 and 0.00, outside `[DROOP_R_MIN 0.15, DROOP_R_MAX 0.85]`. The preload is omitted deliberately: the cut is gated on the doomed channel's own current by `SHARE_CUT_MAX_HANDOFF_A` 0.5 A (`.ino:2018`), so a preload would put the load exactly where the latch is REFUSED. Source total spans 0.15–1.41 A. | The **cut-and-RESTORE topology** of `updateShareSetpointCutoff()`, both channels and both directions. The two RESTORE assertions are novel: `handoff-sag` asserts a cut and then perturbs, so nothing in this suite has ever checked that a latch is released. | `SW_BT_BUS` **clear** through region 6 (≤ 100 of ~1100 ticks) and **set** again through region 7 (≥ 2000 of 3000); `SW_FC_BUS` clear across regions 10/11 and set again from region 12. **Expected fault-free.** ⚠️ At Vmax 1 the total **never** reaches the 0.60 A governor gate, so the share loop runs **open-loop feedforward** for the whole run — and Vmax 3 is barely better: campaign `hil_report_20260831_191509` measured only **20.6 %** of that run above the gate. This pair is a **topology** test, not a tracking one; its cut/restore verdicts are sound and any share *amplitude* read off it is not. |
| `ems-ftp75-5050`, `ems-ftp75-socband` **(EMS-driven, opt-in, 2026-08-31)** | the **EPA FTP-75** cycle at raw t = 0..340 s inclusive, 341 samples at 1 Hz (the segment of `references/Systemic_Scaling_of_Powertrain_Models_with_Youla_Driver_Control.pdf`; the raw EPA file is committed at `references/drive_cycles/ftpcol.txt` and `tools/gen_ftp75_profile.py` verifies its sha256 before generating `tools/ftp75_profile.py` — 341 raw samples decimated to 234 points, worst reconstruction error 4.4e-16 m/s). Scaled by ONE constant, 3.0/56.7 m/s per mph, so the 56.7 mph peak lands on 3.0 m/s; shifted to start at t = 5.0; ends at rest (the trace is 0 mph from raw t = 333, so no synthetic tail is appended). 350 s each, `aux_preload_a` **+0.65 A** (`FTP75_PRELOAD_A`) which puts 100.00 % of the post-ramp run above the 0.60 A governor gate at a 0.800 A floor. | The EMS layer as an **endurance** test rather than a transient one: 345 s of continuous 50 Hz commanding, ~30 accelerate/cruise/decelerate/idle cycles, and an H2 total over a cycle a reader outside this project recognises. | `cmd_v_sp` reaches 3.0 m/s at t = 245; peak source total 1.613 A, so `hold-5050`'s fixed 0.50 split puts **0.807 A** on a channel (42 % under `LIMIT_I_FC_MAX`) and `soc-band`'s 0.75 ceiling puts **1.210 A** (14 %); `h2_cum_g` ≈ 5.5e-2 g (`hold-5050`) / 8.2e-2 g (`soc-band` saturated). `ems-ftp75-5050` is expected **fault-free**; `ems-ftp75-socband` **ALLOWS `OC_FC`** — at a 0.75 split a drive-controller transient near the peak spends the remaining margin, and a single-channel overload is the designed outcome (operator ruling (b)), not a defect. ⚠️ The 0.800 A floor is ABOVE `SOC_BAND_CHARGE_ENTER_ITOT_A` 0.60 A, so the policy's **charging branch cannot open here** — by construction, stated so it is not read off a trace as an absence. |
| `mppt-tracking` **(EMS-driven, 2026-08-31)** | the `charge-regen` speed profile (**the same list object** — a comparison across the two is only meaningful on one stimulus) driven by `mppt-harvest`: `charge_goal` on the braking windows (regen path, `MPPT_DISABLE` held LOW by the firmware's own regen branch) **and** on the 0.4 m/s low-cruise plateaus (FC path, tracking released). `mppt_emulation` **True**; `chg_i_ceiling_a` **1.0 A**. The FC path is single-source (`assertFcChargeEnable()` drops BT off the bus), so the budget is 0.15 aux + ~0.06 motor + 1.0 charge = **1.21 A**, 14 % under `LIMIT_I_FC_MAX`. `mppt-harvest` is a SEPARATE function from `regen-harvest`, deliberately: `charge-regen` has pinned measurements across five campaigns and must not move because this scenario's windows did. | The **MPPT input-voltage threshold** against the firmware's readiness-gated MPPT release — the first scenario in which `MPPT_DISABLE` does anything causal. From fw v24 it also exercises the **threshold manager**: the FC path feeds the charger from the ~15.95 V bus, and the firmware must lower reg `0x02` under it rather than hunt against the 18 V default. | ⚠️ **THE OBJECTIVE INVERTED AT fw v24 — the hunt below is now the FAILURE signature.** fw v24's manager writes reg `0x02` to (windowed-min `V_chg` − 3.0 V), clamped in counts to **[15, 27] = 12.320–13.376 V** (`.ino:1671-1690`), so the module stops refusing, `ag105IsReady()` holds and the pin stays released. The suite's retired 2200-tick ceiling is replaced by a phase-free **edge census** (3–8 rises across the cruise windows), the Low-Power check is inverted to an absence bound, `MPPT_EN|PWR_TRACK` — unreachable under fw v23 — becomes the steady state, and the new `mppt_thresh_cnt` column is the positive evidence the manager ran. **THE fw v23 RECORD, kept because a regression reproduces it:** the firmware releases tracking only once the charger reports ready (`ag105IsReady()`, `.ino:10249-10255`), and releasing it is exactly what stopped the charging that made it ready, so the two **hunted**. Measured on hardware (campaign `20260831_191509`): full period **~40.05 ms** median — ⚠️ RECORD CORRECTED 2026-08-31, this line quoted the offline probe's 80.0 ms, which the campaign's 138 MPPT_DISABLE toggles over the cruise windows arithmetically rule out (80 ms would give about half that many). The firmware acts on the previous 50 Hz poll, so it lags by one tick in each direction. Pin HIGH 50.0 % of ticks, GENSTAT 001 on 50.0 %, `MPPT_EN`-without-`PWR_TRACK` on 50.0 %, `I_charge` equilibrium **0.465–0.525 A** — near half the ceiling, which is why the suite's `charging_occurred` floor is 0.25 A and not 0.5. The pin can only be HIGH inside the strategy's INSET cruise-charge windows, i.e. 3 × 1.5 s less 3 × `AG105_SETTLE_S` = **3.0 s**, so the hunt is ~1500 ticks and a stuck-high pin ~3000 — the retired `mppt_not_stuck_high` ceiling was **2200** between them. ⚠️ Under fw v24 the ~3000-tick outcome is the EXPECTED one, which is why that ceiling had to be replaced rather than re-tuned. **Expected fault-free**, though the realized FC-path margin narrows: the hunt used to hold the mean charge current near half the ceiling, and continuous harvest draws the full 1.0 A that the 1.21 A budget already assumes. |
| `charge-to-full` **(2026-08-31)** | `pi_timeline`: MODE_SAFE 0.5, MODE_HYBRID 3.0, `v_setpoint` **0.0** and share 0.5 at 5.0, `charge_goal` 1.0 at 8.0. 130 s, `chg_i_ceiling_a` **1.0 A**, and the suite overrides **`--soc0 0.990`** (the second such override, mirroring `soc-depletion`'s — which starts LOW to reach a UV latch where this one starts next to FULL). 0.995 − 0.990 = 0.005 of a 5 Ah pack = 90 A·s = **90 s** at the ceiling, so FULL is expected ~t = 100. Standstill is load-bearing: `v_setpoint` 0 < `V_SP_ZERO_THRESH` means 0 A to the motor, which is what makes the single-source budget 0.15 + 1.0 = **1.15 A** (18 % margin) work for 120 s. ⚠️ `mppt_emulation` is deliberately **OFF**, and stays off under fw v24 — the 18 V gate would have blocked this very path outright, and the fw v24 clamped threshold would simply be inert on a continuously-fed standstill charge. | The Ag105 **Fully-Charged / CV** branch, never reached by any prior campaign (largest SoC rise on record ~0.0009 against the ~0.29 that `--soc0 0.7` needs), and the firmware's deliberate **no-action** response to it. | `I_charge` ≥ 0.8 A in CC (t = 10–60); GENSTAT **011** and the **CV** flag held ≥ 500 ticks after t = 60; `I_charge` ≤ 0.05 A after t = 125 (the new `max_value` ceiling kind); and `SW_FC_CHARGE` **still set** after t = 110 — the no-action baseline made visible, so a future policy change to it fails a check instead of surprising a reader. **Expected fault-free.** ⚠️ Zero drive-channel coverage. `CHARGER_STAT` (pin 6) is on neither HIL frame and `chargingControl()` does not read it, so its Fully-Charged blink signature is out of scope; carrying it would be a frame extension. |
| `pi-silence` **(EMS-driven, 2026-08-31)** | `hold-5050` with **no `ems_v_profile`**, so it falls back to `EMS_DEFAULT_CRUISE_MPS` = 1.2 m/s — that fallback IS the setpoint here, chosen because the model's ~3.5 A hold current makes the motor cut-off unmistakable. The commander goes **permanently silent at t = 8.0** (`pi_mute_after_s`): `PiCommander.tick()` returns `None` without advancing its timeline, counter or `next_tx`, so a dead Pi neither scripts nor queues. The **injection** stream keeps running at full rate. 14 s. | The firmware's **Pi watchdog** (`checkPiWatchdog()`, `.ino:4976-4985`, `PI_TIMEOUT_MS` 500, armed in State 2/3 once `pi_ever_connected`), isolated from the HIL link. Its clock is stamped **only** by the 22-byte command branch (`:5043-5044`); every prior stimulus gated both streams together (`apply_scenario`'s `tx_enabled`, `:4172`/`:4192`) and tripped the HIL staleness path instead. | **`FAULT_PI_TIMEOUT` REQUIRED**, `not_before_s` 8.0, in State 2 at t = 7.5. Plus `motor_halted`: commanded `current` falls ≥ 2.0 A across the latch — the fault's consequence, not just its flag. ⚠️ 0x0010 is shared with `FAULT_HIL_LINK`, so the entry declares **`child_tx_healthy`**. From **fw v25** that is a DIRECT READ of frame byte 16 (`ERR_PI_TIMEOUT` 0x05 vs `ERR_HIL_STALE` 0x10); on fw v21–v24 it falls back to the older inference **by elimination** (a continuous injection stream rules the alias out). Injection never stops, so no fw v23 run boundary forms and the latch persists; a mid-run warm reset would prove contamination *and* clear `pi_ever_connected`, disarming the watchdog under test — which is why `warm_resets_expected` is deliberately absent. |
| `share-staircase` **(2026-08-31)** | **Motor-free** (`v_setpoint` 0 for the whole run — a drive transient would move I_tot and therefore move the governor rails mid-staircase). **Two loads**, a bespoke `apply_scenario()` branch because the generic `aux_preload_a` ramps a load in once and cannot bring it back down: `STAIRCASE_LOAD_A` **+1.05 A** from t = 4 (I_tot **1.20 A**, so the rails land on the round 0.25/0.75), dropped to `STAIRCASE_LOAD_B` **+0.40 A** at t = 29 (I_tot **0.55 A**), both edges ramped over `SOC_LOAD_RAMP_S`. Timeline: 0.80 → 0.20 in 0.10 steps every 3 s from t = 6, recentre 0.50 at 27, then 0.95 / 0.50 / 0.05 / 0.50 at 33 / 36 / 39 / 42. | **Phase A** — the governor's clip band `SHARE_MINORITY_I_MIN_A/I_tot` = [0.25, 0.75], measured only incidentally by campaign TP0170–0180, swept deliberately in both directions. **Phase B** — `updateShareSetpointCutoff()`'s **cut AND restore** on both channels, with the latency of each. The two loads cannot be one: at 1.20 A a 50/50 split is 0.60 A, over the cut's `SHARE_CUT_MAX_HANDOFF_A` 0.5 A guard, so the latch would **defer** rather than fire. | `cmd_share_sp` reaches 0.80 and sweeps ≥ 0.55 down; `I_fc` ≥ 0.80 A at the top step (the 0.75 rail on 1.20 A is 0.90 A; a run that ignored the command and held 0.50 would show 0.60) and falls ≥ 0.50 A across the sweep; `SW_BT_BUS` and `SW_FC_BUS` each **cut and restored**; and **four latency measurements** via `switch_fall_latency_ms` (both `fall` and `rise` edges), tripwire 40 ms. **Expected fault-free** (worst channel 0.90 A vs 1.4 A). ⚠️ The measured latency is the **deliverable**; the bound is a regression tripwire and must never be raised to make a run pass. Corrected premise: the [0, 20) ms spread is **command-arrival phase** at `PI_CMD_HZ` 50, not a firmware tick — `POWER_BAL_PERIOD_US` and `SHARE_CTRL_TS_US` are both 1000 µs. ⚠️ Phase B's 0.55 A sits ON the closed-loop exit hysteresis, so do not read share-*tracking* numbers off it; Phase A is where the loop is unambiguously closed. |

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

> **`constants_hash` changelog — 2026-08-31: the hash moved.** The DP-EMS round added
> **20 constant names** to `collect_model_constants()` (16 `SOC_BAND_*`, plus
> `H2_GFC_TS_S`, `H2_GFC_DC_GAIN_GPS_PER_W`, `H2_GFC_TAU_DOMINANT_S` and
> `H2_STATIC_PROXY_GPS_PER_W`). The change is **purely additive — no pre-existing
> constant changed value** — but the hash covers the whole set, so a pre-2026-08-31
> `constants_hash` is **not comparable** with a later one even for an otherwise
> identical model. Across that boundary compare the `constants` dict itself, which the
> sidecar carries for exactly this reason. The sidecar and its fields are described in
> `docs/HIL_USER_MANUAL.md` §2.5.

> **`constants_hash` changelog — 2026-08-31 (Round C): the hash moved again.** The
> wave-2 scenario round added **19 constant names** to `collect_model_constants()`:
> `AG105_MPPT_V_THRESH`, `AG105_MPPT_V_HYST`, `COMBINED_PROFILE_S`, `COMBINED_PROFILE_MS`, `EMS_MPPT_CRUISE_LEAD_IN_S`, `EMS_MPPT_CRUISE_LEAD_OUT_S`, `EMS_Y_START_S`, `EMS_Y_END_S`, `EMS_Y_DURATION_S`, `EMS_Y_RUN_EXIT_S`, `Y_AUX_LOAD_A`, `FTP75_DURATION_S`, `FTP75_T_END`, `FTP75_PRELOAD_A`, `FTP75_RUN_EXIT_S`, `FTP75_SCALE_MPH_TO_MPS`, `STAIRCASE_LOAD_A`, `STAIRCASE_LOAD_B`, `STAIRCASE_DROP_S`.
> Again **purely additive — no pre-existing constant changed value**, and no name was
> removed. One of the nineteen is incidental rather than new physics:
> `FTP75_SCALE_MPH_TO_MPS` is re-exported into `hil_plant_sim`'s namespace by the
> generator-binding check added this round (`gen_ftp75_profile.py` is imported so a
> stale generated table cannot load), so the collector now sees a constant that
> already governed the FTP-75 stimulus. The same comparability rule applies and
> compounds: a **pre-Round-C** `constants_hash` is not comparable with a later one,
> and neither is a pre-2026-08-31 one. Compare the `constants` dict across either
> boundary.

> **`constants_hash` changelog — 2026-08-31 (SDP round): the hash moved again.** The
> online-SDP round added **five constant names** to `collect_model_constants()`:
> `H2_SDP_PROXY_ETA_FC`, `H2_SDP_PROXY_Q_LHV_J_PER_G`, `H2_SDP_PROXY_GPS_PER_W` and
> `SDP_RUN_EXIT_S` (plus `SDP_DEFAULT_DECISION_DT_S`, which is a fallback the shipped
> artifact never exercises). **Purely additive — no pre-existing constant changed
> value**, and no name was removed. Note `SDP_RUN_EXIT_S` is *defined as*
> `SOC_BAND_RUN_EXIT_S`, so it records a value already in the set under a second name
> rather than a new model quantity. The comparability rule compounds as before: a
> **pre-SDP-round** `constants_hash` is not comparable with a later one. Compare the
> `constants` dict across the boundary.

> **`constants_hash` changelog — 2026-08-31 (SDP-interior round): the hash moved
> again.** The three `sdp_soc_ref_offset` scenarios added **19 constant names** to
> `collect_model_constants()`: `FTP75_SDP_SOC_REF_OFFSET`, `FTP75_SDP_PRELOAD_A`,
> `SDP_CROSS_SOC_REF_OFFSET`, `SDP_CROSS_CRUISE_HI_MPS`, `SDP_CROSS_CRUISE_LO_MPS`,
> `SDP_CROSS_DECEL_S`, `SDP_CROSS_RUN_EXIT_S`, `SDP_CROSS_DURATION_S`,
> `SDP_BRAKE_SOC_REF_OFFSET`, `SDP_BRAKE_CRUISE_HI_MPS`, `SDP_BRAKE_CRUISE_LO_MPS`,
> `SDP_BRAKE_HI_HOLD_S`, `SDP_BRAKE_DECEL_S`, `SDP_BRAKE_LO_HOLD_S`,
> `SDP_BRAKE_ACCEL_S`, `SDP_BRAKE_CYCLES`, `SDP_BRAKE_CHG_CEILING_A`,
> `SDP_BRAKE_RUN_EXIT_S` and `SDP_BRAKE_DURATION_S`. **Purely additive — no
> pre-existing constant changed value**, and no name was removed. All nineteen are
> SCENARIO STIMULUS constants (speeds, hold lengths, loads, the SoC-axis offsets),
> not plant physics; two of them — `SDP_BRAKE_ACCEL_S` and `SDP_BRAKE_CHG_CEILING_A`
> — are current-budget constants and are derived at their definitions. The
> comparability rule compounds as before: a **pre-SDP-interior-round**
> `constants_hash` is not comparable with a later one. Compare the `constants` dict
> across the boundary.

> **`constants_hash` changelog — 2026-09-01 (charge-economics / strategy-roles
> round): the hash did NOT move.** Recorded because a round that renamed a
> module-level constant is exactly the case a reader would expect to have moved it.
> `SDP_POLICY_FILE` became `SDP_POLICY_FILE_V2` and gained a sibling
> `SDP_POLICY_FILE_V3`, and `EMS_STRATEGY_META` / `SDP_STRATEGY_NAMES` were added —
> but `collect_model_constants()` records only UPPERCASE **numeric** module globals,
> and all four of those are a string, a dict or a frozenset. No numeric constant was
> added, removed or changed, so a pre-round and a post-round `constants_hash` ARE
> comparable. What DID change is the artifact a run plays, which the fingerprint
> deliberately does not cover (it hashes module constants, not a JSON file on disk)
> — that is what `config.sdp_policy` in the CSV's meta sidecar is for, and it is the
> field to compare across this boundary.

> **`ems-sdp` leg changelog — 2026-09-01: the LEG changed, and its h2 / ΔSoC pairs
> are not cross-campaign comparable.** Written in the style of the
> `constants_hash` notes above because it is the same class of trap and the
> fingerprint does *not* catch it: `ems-sdp` was rebound from the `sdp-v2`
> artifact (`740c802e…`) to the calibrated `sdp-v3` benchmark (`0443febf…`).
> Same scenario name, same stimulus object, same duration, same
> `constants_hash` — and a **different decision law**: v2 opens the Ag105
> charger where v3 declines it endogenously in all 101 × 25 cells. So a
> **pre-2026-09-01 `ems-sdp` `h2_cum_g` / `delta_soc` pair is a DIFFERENT LEG**
> from a later one, and the two must never be pooled, averaged, or read as a
> repeatability spread. The concrete case: campaign `20260901_000816`'s v2 leg
> is the FAIL fixture the EMS frontier check is regression-tested against
> (`test_run_hil_suite.py`, `_C2_LEGS`), while campaign `20260831_222036`'s
> numbers are the PASS fixture. Compare `config.sdp_policy.policy_sha256` in the
> meta sidecar before comparing any two `ems-sdp` runs; the share axis is
> unaffected (the two share maps agree on every SoC row from 3 upward), so a
> `cmd_share_sp` trace *is* comparable across the boundary.

### 7.1 CSV schema (`--csv`)

One row per tick. The base schema is **19 columns and is frozen**; everything since is
**appended, never reordered**:

- `soc` (col 20) — battery state of charge, 5 dp. **Simulated runs only.**
- `h2_rate_gps`, `h2_cum_g` (appended last) — **simulated runs only, and
  unconditional there**: this tick's hydrogen rate (g/s) and the run's cumulative
  total (g) from the `Gfc` metric, 9 significant digits (the values are O(1e-4) and
  O(1e-3), so a 4-dp format would round both to zero). Deliberately **absent** in replay
  mode, where the plant integrator is bypassed and a column of zeros would read as "this
  run burned no hydrogen". ⚠️ **The Gfc model's estimate** — scale-portable map, stack
  not identified against this rig (`TODO(calibrate)`); §9.3.
- `h2_sdp_cum_g` (appended after them, 2026-08-31) — **simulated runs only, and
  unconditional there**: the run's cumulative hydrogen on the **student's static
  proxy** `P_fc/(eta_fc·Q_LHV)` at `eta_fc = 0.5`, `Q_LHV = 120000 J/g`
  (`references/EMS/SDP_EnergyManagement2.m:12-13`), computed from the **same
  `P_fc` input** `h2_cum_g` integrates — `H2Consumption.step()` runs both
  accumulators off one clamped input, so the two columns cannot diverge by their
  input, only by their model. No rate column: the proxy is memoryless, so its
  rate carries nothing its cumulative does not. ⚠️ **A SECOND MODEL, NOT A
  CROSS-CHECK.** `Gfc`'s DC gain implies 47.25 % efficiency against the proxy's
  assumed 50 %, so the proxy **under-reads `h2_cum_g` by ~5.5 %** at steady state
  *by construction*: the gap between the columns is arithmetic and is never a
  finding. Rank runs on one axis. It exists so a figure from this rig can sit
  next to the student's SDP/DP work without either side re-deriving the other's
  model.
- `cmd_share_sp_raw` (appended after `h2_sdp_cum_g`, 2026-08-31, ledger MED-1) —
  **simulated runs only, and unconditional there**: the SDP policy's **pre-clamp**
  `power_share_setpoint` request, i.e. the table value before
  `SdpStrategy.clamp_share()` applies the hardware envelope
  `[SOC_BAND_SHARE_MIN, SOC_BAND_SHARE_MAX] = [0.15, 0.85]`. Held between
  decisions exactly as the emitted value is, 4 dp. **BLANK on every run whose
  commander is not an SDP policy** — there is no table request to report and a
  number would be a fabrication (the same discipline `cmd_v_sp`/`cmd_share_sp`
  use under `--pi-live`). ⚠️ **Why it exists:** under the shipped `v2` policy
  every table value the `ems-sdp` walk produces (0.90 / 0.95 / 1.00) clamps to
  the **same** 0.8500, so `cmd_share_sp` alone cannot show that the demand axis
  moved the table at all — which is exactly why campaign
  `hil_report_20260831_191509` could only diagnose the `v1` clamp saturation
  from the exit summary's counters. Read this column, not `cmd_share_sp`, to
  answer "did the policy interior actuate".
- `cmd_v_sp`, `cmd_share_sp` (appended, unconditional within each mode) — what the
  emulated Pi commander **intended to be commanding at this tick**, blank when no
  commander exists (`--pi-live`, or a plain `--replay`). ⚠️ **They move at the
  NOMINAL command instant, not when the packet left** (corrected 2026-08-31,
  campaign `hil_report_20260831_191509` fix queue). `PiCommander.tick()` walks the
  timeline on every 1 kHz tick, *before* the 50 Hz send gate, and the row is written
  from `commander.state`; the 22-byte packet carrying that value leaves **up to one
  command period (20 ms) later**, and its consequence reaches the observed columns a
  further ~1.9 ms of observation round trip after that. **A latency measured from a
  `cmd_*` edge therefore INCLUDES the command-arrival phase** — which is precisely
  the [0, 20) ms spread `share-staircase` and the handoff-sag tracker report. Do not
  read these columns as a transmit timestamp; there is no `cmd_sent_*` column, and
  emitting one is deferred until latency decomposition is a deliverable.
- `elec_substep_hz`, `elec_events` (cols 21–22) — **`--electrical hifi` only**: the
  honestly-measured substep rate this tick and the cumulative electrical-event count.
- `replay_rec` — **replay only**, and in replay mode `soc` and the hi-fi columns are
  deliberately *omitted*, so `replay_rec` keeps its established column index and an
  existing replay parser is unaffected. **`-1` marks a synthetic bring-up preamble
  row** (`REPLAY_PREAMBLE_S` = 2.5 s of healthy nominal rails prepended to every
  replay, 2026-08-30): those rows have no source record, and log time for every other
  row is `t - 2.5 s`. See `docs/HIL_MODE.md` "Synthetic bring-up preamble".

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
| `CHG` — shared VCHG-IN charger input (fed by both the REGEN and FC-charge switches) | 10 µF | **`TODO(verify)`** — no separate cap identified on the schematic |
| `RGN` — **RETIRED** (2026-08-30): the regen node *is* V-MOT; index kept for matrix-shape stability, no links, bleeds to 0 | 10 µF | — |

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
| `SOFT` | VOUT follows a linear ramp over `tON = (VIN/35)·(CSS_nF/0.0023 − 100) µs` — ~19.8 ms at 16 V on the 100 nF switches (`FC_BUS`, `BT_BUS`, `MOT_PWR`), ~1.07 ms on the 5.6 nF ones (`REGEN`, `FC_CHARGE`, `BT_SEQ`). The pass current is the **physical** one — `i ≈ c_load·d(target)/dt + i_load` (see the fourth modelling note) — and both the reported link current and the foldback decision derive from it. Foldback SCP is active **only here**: 8.5 A at ΔV ≤ 5 V falling toward ~5.3 A at ΔV = 16 V, floored at 2.5 A. Held continuously at the clamp for **250 µs** → **CUT**, auto-retry after **64 ms**. **2026-08-30c:** on an episode that starts on a **pre-charged** node (`v_ss_start > RT_SS_PRECHARGED_V` 1.0 V) the ramp's duration *and* endpoint come from the per-episode VIN **high water mark**, not the instantaneous VIN, and the target is capped at VIN. A cold start keeps the original instantaneous-VIN path bit-for-bit. See the note below. |
| `ON` | Forward regulation at `V_FWD` = 35 mV, `R_ON` = 21 mΩ. Fast reverse comparator at **−50 mV** → off, then re-arm **without** a new soft-start once forward again. |

Four modelling notes. First, the soft-start is a **controlled source on the output node**,
not a resistor referenced to the input node: stamping it the latter way (with the offset
computed from the previous substep's `v_in` while the conductance term moved `v_in`
inside the solve) injected a fictitious ~1400 A into the bus. Second, both the foldback
limit and the boost's output-current ceiling are stamped as **equivalent resistances**,
never ideal current sources — an ideal source into a 30 µF node is unbounded within a
single substep (the same principle the H1 fix, §8.3 below, applies to the motor draw/regen
load). Third — **M6, declared here rather than left implicit** — the soft-start stamp is
**charge-NON-CONSERVING**: the output node gets an implicit conductance (so it participates
correctly in the node solve), but the input node is debited *explicitly*, from the
*previous* substep's current estimate rather than the node solve's own current. This is a
deliberate stability trade (see the comment at `Rt1987.stamp()`'s `SOFT` branch), not an
oversight — it only matters during the ~1–20 ms soft-start ramp itself, so treat inrush
current *shape* during that window as approximate, not exact.

Fourth — **the soft-start current is PHYSICAL, and was not always** (2026-08-30 fix). The
operating point used to read the demand as `(target − v_out)/R_ON` with `target` evaluated
at the current substep and `v_out` carried over from the previous one. Those are one
substep apart, so the gap contained the ramp's per-substep step `rate·h` on top of the
genuine tracking lag; across a 21 mΩ pass element that skew reads as **tens of amps** of
demand while the physical current is milliamps (`rate·h/R` at 15 kV/s and h = 50 µs is
~36 A, against a true `C·rate` of ~0.5 A). It made the 5.6 nF switches fold-active for
their entire ~1 ms ramp — so `REGEN` and `FC_CHARGE` cut at 250 µs, retried at 64 ms and
**could never reach `ON`**, which meant no hi-fi charge scenario could power the Ag105 —
and, because `Rt1987.i` is the INA253 sense point, it injected amps of fictitious
`I_fc`/`I_batt` into the bring-up: enough to latch `FAULT_OC_FC` (`LIMIT_I_FC_MAX` 1.4 A,
single-sample) on a `BENCH_TEST=0` HIL boot from a real current of
`C·dV/dt ≈ 35 µF · 16 V / 19.8 ms ≈ 28 mA` (19.8 ms is the model's own `tON` at 16 V
on a 100 nF CSS).

The demand is now `i_phys ≈ c_load·d(target)/dt + i_load`, recovered by evaluating the ramp
target at the **same instant** as `v_out` (one substep back): in tracking equilibrium the
discrete solve settles at `target_prev − v_out = R·(c_load·rate + i_load)`, so the lag term
alone *is* the physical current, with `c_load·rate` kept as a floor. Foldback binds by
scaling the pass resistance by the overdrive ratio `i_phys/i_fold`. **Genuine overload is
untouched**: a node held down by load or a short does not track, the gap grows without
bound, and the clamp/cut/retry fires on physics. Measured after the fix — bus pre-charge
from dark peaks at 0.22 A (was 1.98 A) with zero cuts; `REGEN`/`FC_CHARGE` reach `ON` 10 ms
after enable with zero cuts (was: never); `MOT_PWR` closing into 1.37 mF under the
`scp-inrush` load (6 A at the time of that fix round; since the 2026-08-31 deterministic
redesign the scenario ramps unloaded and steps a 6.5 A pulse in mid-soft-start — see the
`SCP_INRUSH_*` block in `hil_plant_sim.py`) still folds and cuts with the 64 ms retry, and completes
that retry once the load is removed. The reverse-comparator/`_restart_no_ss` handoff path,
the chopper, the droop split and the events schema are unchanged. One event
*population* did shift: a SOFT-state open (EN-low/UVLO mid-ramp) now carries the
physical ~tens-of-mA current, which falls under `_open()`'s 0.05 A ring-estimate
gate — so such opens no longer emit an `sw_ring` event (the old code always did,
at the fictitious fold-scale current). Physically correct: no current, no ring.

Separately — **H1** — the same "never an ideal source into a small node" discipline now
also covers the **motor draw/regen load** on `N_MOT` (§4.3/§8.3): a negative (regen)
`i_motor` used to be stamped as an ideal current source, which is unbounded when `MOT_PWR`
is open and the node has only the 2 kΩ bleed for company (reproduced: the node ran to
~10 kV within seconds, and the resulting kV-scale `sw_ring` events fired the `over_absmax`
Death-5 verdict from a numerical artefact, not a hardware conclusion). It is now stamped as
a Norton conductance referenced to the previous substep's node voltage
(`g = i_motor / max(v_node, V_MOT_LOAD_FLOOR)`), and the node solve additionally clamps any
node that still ends up past `2×V_ABSMAX` to that bound, emitting one `node_runaway` event.
The `sw_ring` `over_absmax` verdict is itself gated on the cutting switch's node voltage
being `<= V_ABSMAX` at cut time, so an implausible node state can no longer manufacture a
Death-5 signature on its own.

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
resistor). The chopper sits directly on V-MOT (2026-08-30 topology fix — upstream of
the REGEN switch, matching the bench observation that the clamp held 18.1 V with
`REGEN_ENABLE` open), so it does not reach the bus through the REGEN path. However,
it **does** couple to `V_bus` through a closed `MOT_PWR`, which conducts BUS ↔ MOT.
At the 18.1 V clamp the shunt draws ≈ 18.1 / 47 = **0.385 A**, and the droop law
(0.074 V/A both-sources, 0.16 V/A single-source) turns that into **≈ 0.03–0.06 V** of
bus sag — small enough to be consistent with the bench observation "`V_bus` unmoved"
(CLAUDE.md 2026-08-17b) rather than contradicting it.
The clamp level is **bench-calibrated at 18.1 V** (operator, 2026-08-27, from the
observed 13.3 → 18.1 V clamping excursion, CLAUDE.md 2026-08-17b; the earlier 16.5 V
`TODO(calibrate)` placeholder is retired).

**The reason the chopper is simulated at all is the power question:** does dissipation
in the 47 Ω dump resistor ever exceed its **20 W rating**? At the 18.1 V clamp the
steady dissipation is `18.1²/47 ≈ 6.97 W`; the rating is only reached through
excursions past `√(20·47) ≈ 30.7 V`. The engine computes `V_rgn²/47` per substep
while the chopper conducts, keeps the worst value (`chopper_peak_w`, reported in
`summary()`), and emits a `chopper_over_power` event once per excursion above
`P_CHOPPER_MAX_W` — which `run_hil_suite.py` turns into a failing check.

### 8.7 Noise injection

Applied to the **injected values**, never to the internal states.

- **ADC quantization** is real and computed from the firmware's own scale constants
  (`teensy_controller.ino:1128-1144`): `V_fc` 3.01 mV/count, `V_batt` 2.11, `V_bus` 4.55,
  `V_chg`/`V_rgn` 7.15, currents **8.06 mA/count**.
- **Gaussian sigmas default to ZERO** (a noise-free run stays deterministic), and
  `NoiseConfig.suggested()` now carries **per-rail sigmas MEASURED from the bench-log
  corpus** (2026-08-27: all 206 logs, 1 s windows, 75 ms moving-mean detrend, quiescent
  plateaus only, additive component `√(sd² − LSB²/12)`): `V_fc` **19 mV** (6.3 LSB — the
  outlier by ~8× in LSB terms; genuine analog noise on the FC sense path, load-independent,
  worth a scope look since it feeds the share loop), `V_batt` 2.4 mV (quantization-
  dominated; rises to ~20 mV under pack sag — quiescent floor only), `V_bus` 1.8 mV (near
  the quantization floor, consistent across 201 logs and both supply batches), `V_rgn`
  4.0 mV (measured at a real 13.3–13.5 V level; heavy-tailed, kurt ~6), `V_chg` 4 mV
  **adopted from V_rgn** (identical 78.7 k/10 k divider — the charger path is unpowered in
  every logged run, so its own channel is censored at 0 counts; `TODO(verify)` after the
  first logged charge run), currents 4.4 mA sensor floor (the 12–57 mA std observed above
  ~80 mA is boost ripple / share-loop dither — ripple physics, deliberately excluded from
  this sensor-noise model).
- **INA253 zero offset is MEASURED and asymmetric between the two fitted parts**
  (per-log minimum mean, bus live, 201 logs): `I_fc` **+19.9 mA median** (the old 0.02 A
  default confirmed to ~1 count), `I_batt` **≈ 0** (+0.2 mA; clipped at zero, so a small
  negative offset cannot be excluded). `NoiseConfig` therefore defaults to a per-channel
  dict `{"I_fc": 0.020, "I_batt": 0.0}` (a plain float is still accepted and applied to
  both).

### 8.8 Events and the sidecar

`ElectricalSim.events` accumulates dicts (`scp_cut`, `sw_ring`, `reverse_block`,
`boost_ovp`, and — as of the M1/M2/H1 fixes — `numeric_fault` and `node_runaway`). With
`--csv PATH` they are now **streamed to `PATH.events.jsonl`** as they happen (drained and
`flush()`ed every simulator tick, M3) rather than written once at exit — the durable record
on disk is current up to the last completed tick even if the process is later killed hard.
`hil_plant_sim.py` trims `ElectricalSim.events` after every drain to bound its own memory on
a long run; the sidecar file (and the driver's own running `elec_events_total` /
over-abs-max tallies used for the exit summary) carry the cumulative totals instead.
`ElectricalSim.summary()`'s own `events`/`event_kinds` fields therefore reflect only
whatever has accumulated since the last drain, not the whole run — read the sidecar (or the
driver's printed totals) for the run-wide picture.

---

### The pre-charged-node soft-start artifact (fixed 2026-08-30c)

`comm-loss` is the only scenario whose bring-up closes `MOT_PWR` onto a node that is
already **pre-charged** — the fw v23 warm recovery runs after V-MOT has bled from
13.86 V to ~4.39 V through its 2 kΩ path, while the bus is live. That combination
exposed a **positive feedback loop** in the SOFT model: `tON` was recomputed from the
*instantaneous* VIN every substep while `v_ss_start` stayed latched, so

> VIN sags → `tON = (VIN/35)·(…)` shrinks → `frac = t_state/tON` and `rate` both grow
> → more displacement demand → more bus draw → VIN sags further.

With `r = 21 mΩ`, a target that also chases the sagging rail turns millivolts of node
ripple into **amps** of apparent demand. Measured: the node ran 0.84 V *above* its own
ramp target and the reported current reached **3.9×** physical on the board (**6.8×**
in a standalone reproduction), enough to latch a spurious `OC_FC` 3 ms after Idle.

Two fixes were tried and **rejected**, both recorded at the code so they are not
re-attempted:

1. *Latch `tON` at SOFT entry.* At entry the input is frequently still dark — the
   staged bring-up closes `FC_BUS`/`BT_BUS` **before** the boosts are enabled — so
   this latches `tON` = 1.24 ms instead of ~19.8 ms, a 16×-too-fast ramp. Measured:
   the cold-start P0 peak goes **0.2226 → 3.81 A**, destroying the one behaviour that
   is triple-corroborated on hardware.
2. *Skip the stamp when `v_out ≥ target`.* True of the device, wrong for the model:
   the conductance-to-target **is** the soft-start servo, and removing it on one side
   turns a stiff servo into a bang-bang. Measured: `I_tot` peak 6.95 A vs 2.82 A with
   the servo left intact.

**What shipped:** the anti-feedback is *scoped to a pre-charged entry*
(`v_ss_start > RT_SS_PRECHARGED_V`). Such an episode derives both the ramp duration
and its endpoint from the per-episode VIN high water mark — a CSS capacitor charging
at a fixed current cannot make an in-progress ramp finish *sooner* because the input
momentarily sagged — and clamps the target to the instantaneous VIN, since a pass
device cannot ramp its output above its own input. A cold start (`v_ss_start ≈ 0`)
takes the original path untouched.

### TRCB during soft-start (added 2026-08-30d)

The first version of the fix above capped the ramp target at the instantaneous VIN
(`target = min(target, v_in)`), on the correct premise that a pass device cannot ramp
its output above its own input. **The premise was right and the mechanism was wrong.**
When the held reference leads a *sagging* rail the cap drives the target BELOW `v_out`,
and the SOFT stamp then sinks the full 47.6 S servo conductance out of `n_out` with
`J[n_in] = 0` — charge annihilated, not transferred. Measured: **-94 A** on 0.3 Vpp of
2 kHz bus ripple, **-345 A** on a bus collapse mid-ramp, while the reported sense
current still read <= 8.5 A. Nothing in the model represented the `v_out > v_in` regime
during soft-start at all, because the reverse-comparator branch ran only in state `ON`.

The datasheet is explicit that this is wrong, and all three points were checked against
`references/Datasheets/RT1987_DS-00.pdf`:

- **17.6** puts the fast reverse comparator under *"when the power path is enabled"*,
  tripping within `t_FRC` (~0.5 us, i.e. inside one substep) whenever `VIN - VOUT`
  falls below `V_FRC` (typ. -50 mV). **No restriction to post-soft-start.**
- **Table 1** gives TRCB's fault response as *"Auto-restart **without** soft-start at
  fault removal"*, FLTB high-impedance — which is exactly the existing
  `_restart_no_ss` path.
- **17.4 condition 1**: *"When the device is first enabled, if any of the following
  conditions exist, the internal power MOSFET will not turn on: 1. VIN - VOUT < V_FRC"*
  — so `t_D(ON)` elapsing is necessary but not sufficient to begin a ramp.

**What shipped:** the reverse-comparator branch now runs in `SOFT` as well as `ON`
(checked *before* the SCP and completion logic, since a reverse event at 0.5 us is
faster than either); the `TD_ON` -> `SOFT` transition is gated on `VIN - VOUT >= V_FRC`,
holding in `TD_ON` until the differential is admissible; and the `min(target, v_in)`
cap is **removed** — the TRCB block replaces it as the guard for that regime.

**Verification (A/B on one driver, pinned 62.5 us substeps).** `i_node` is the current
the SOFT stamp actually delivers into `n_out`; a negative value is the annihilation
bug. "above target" is the worst `v_out - target` excursion *within* an episode.

| case | metric | before | after |
|---|---|---|---|
| cold staged bring-up | P0 peak `I_fc` | 0.222557 A | **0.222557 A** (delta 0, bit-for-bit) |
| cold staged bring-up | P3 peak `I_fc` | 0.473950 A | **0.473950 A** (delta 0, bit-for-bit) |
| warm, quiescent | reported / physical | 6.82x | **1.02x** |
| warm, quiescent | `I_tot` peak | 7.785 A | **0.731 A** |
| warm, quiescent | above target | 0 V | **0 V** |
| warm + 0.3 Vpp ripple | `i_node` min | **-94.40 A** | **0.00 A** |
| warm + 0.3 Vpp ripple | peak `I_fc` | 1.958 A | **0.165 A** |
| warm + 0.3 Vpp ripple | above target | 1.982 V | **0 V** |
| warm + 0.6 Vpp ripple | `i_node` min | **-62.66 A** | **0.00 A** |
| warm + 0.6 Vpp ripple | peak `I_fc` | 3.341 A | **0.270 A** |
| warm + 6 A load step mid-ramp | `i_node` min | **-20.26 A** | **0.00 A** |
| warm + 6 A load step mid-ramp | peak `I_fc` | 4.121 A | **3.381 A** (vs 3.081 A load baseline) |
| warm + bus collapse mid-ramp | `i_node` min | **-344.59 A** | **0.00 A** |
| warm + bus collapse mid-ramp | peak `I_fc` | 2.475 A | **1.185 A** |
| `MOT_PWR` already ON + 6 A | peak `I_fc` | 3.081 A | **3.081 A** (delta 0, reference) |

**The "0 V above target" row is scoped to the QUIESCENT episode, deliberately.** Under
disturbance the pre-fix model reached 1.98 V / 1.32 V / 0.43 V / 7.24 V above target on
the four cases above — an earlier version of this table quoted the quiescent 0 V without
that scope and read as a stronger claim than it was. Post-fix every case reads 0 V,
because TRCB now removes the switch from the network before the node can lead its own
ramp.

The cold figures are the hardware-corroborated ones (P0 0.2226 A / P3 0.4740 A,
reproduced in three separate campaigns), and they do not move.

**`scp-inrush` does NOT lose its event to the new reverse branch** — checked
explicitly, because fold/SCP is a `SOFT`-only mechanism and a reverse trip removes the
switch from `SOFT`, so a trip arriving first would have silently emptied that
scenario's `events_require`. A headless reproduction of the *shipped* sequence (real
`Plant`, real `ElectricalSim` at the scenario's own `vesc_cap_f`, real
`apply_scenario()`, and the actuator word stepped through the firmware's own bring-up
gates evaluated against the plant's rails) gives:

| at the P3 `MOT_PWR` close | value |
|---|---|
| `v_in` (bus) | 15.79 V |
| `v_out` (motor node) | 0.00 → 0.67 V |
| differential `dv` | **+13.89 V — massively forward** |
| event that fires | **`scp_cut`**, `i_cut` = **6.2852 A** |
| vs the on-hardware campaign | 6.290 A — **0.07 % apart** |
| `over_absmax` | 0 |

The motor node is **dark** at P3 (the 5 A load holds it at 0 V), so no reverse
condition can develop. A reverse trip during soft-start needs a **pre-charged** node —
the `comm-loss` warm-recovery shape — which P3 never presents. The two cases are
structurally different and do not compete for the same event.

**One new, inert event does appear in hi-fi runs:** a `reverse_block` on **BT_BUS** at
~62 ms with `dv = −50.4 mV`, tagged `during: "soft_start"`. That is the diode-OR
blocking whichever boost output is momentarily lower — the RT1987's advertised
source-sharing function (§17 intro) — and it is verified inert: with the SOFT reverse
branch disabled, cut counts and **both** bring-up current pins are byte-identical
(Δ 0.000000000 on P0 and P3, with and without the 5 A load). Expect it in the events
sidecar; nothing scores on it.

**SCP retry cadence is preserved** (verified at unit level): after a cut the node is
left dark, so the 64 ms re-arm re-enters soft-start with `v_ss_start` ~ 0 — the COLD
path — and the new `TD_ON` gate never delays it, since a dark node is by definition
forward-biased. One side effect is real and wanted: removing the target cap raises the
apparent overdrive on a *sagging* rail (standalone `scp-inrush`-shaped driver: reported
peak 6.30 -> 8.39 A), because the cap had been quietly shrinking the demand exactly when
the bus browned out. That makes a genuine overload *more* likely to fold, not less.

### Known bias in the ramp shape (not fixed — future work)

Quote a soft-start current from this engine as *physical* only with this in mind.
**17.1/17.3** define `tON` as the **10 % to 90 % rise time**, so the part's true slew is
`0.8 x VIN / tON = 0.8 x 35 / (CSS_nF/0.0023 - 100)` — **independent of VIN**,
645.5 V/s at CSS = 100 nF. This model instead ramps `v_ss_start -> v_ref` *over* `tON`,
conflating slope with endpoint, and inherits a start-dependent error of **opposite
sign** at the two ends:

| episode | model slew | true slew | bias |
|---|---|---|---|
| cold (`v_ss_start` ~ 0) | 806.9 V/s | 645.5 V/s | **+25.0 %** |
| warm (4.4 V -> 15.78 V) | 581.9 V/s | 645.5 V/s | **-9.8 %** |

No single scale factor fixes both. Note also that a test bounding the reported current
by `c_load x rate` computed from `rt1987_t_on_s()` is **self-referential** — it
re-derives the same wrong slope, so it validates internal consistency, not physicality.
The right shape is a constant-slew ramp, and it is deliberately **not** implemented
here: the +25 % cold bias is baked into the hardware-corroborated 0.2226 A / 0.4740 A
bring-up pins, so changing it needs its own A/B round against hardware.

## 9. Source models

Both electrical engines share **one instance each** of the fuel-cell and battery models:
`Plant` owns them and hands them to `ElectricalSim`, so SOC and the FC double-layer state
are integrated exactly once per tick whichever mode is active, and a scenario behaves the
same way in both. They live in `tools/hil_electrical.py` (SOURCE MODELS block).

> **L6 fidelity boundary.** The current fed to these models in hi-fi mode
> (`ElectricalSim.i_fc` / `i_bt`, set from the `FC_BUS`/`BT_BUS` **switch link** current in
> `_substep()`) is the ideal-diode switch's current, not the boost's own input draw. With a
> boost enabled but its bus switch **open** — the `bringup` scenario's operating condition,
> and any stage where a channel is regulating but not yet feeding the bus — the switch
> carries zero current, so the fuel-cell/battery models see zero draw even though the boost
> itself may be drawing from the source. Deliberate (the switch link is the only current this
> network solves for on that side of the boost), but it means FC/SOC dynamics during an
> enabled-but-unbussed boost stage are not modelled by either electrical mode.

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

### 9.3 Hydrogen consumption — the `Gfc` metric

> ### ⚠️ READ THIS BEFORE QUOTING ANY H2 NUMBER FROM A HIL RUN
>
> `Gfc` is a **full-scale (106 kW) fuel-cell hydrogen-consumption model taken verbatim
> from the PhD student's FCHEV dynamic-programming study**. It is the commented-out
> `H2_tf` at `references/EMS/DPtrial.m:51-52`, with its two scalar prefactors folded in:
> `num = [5.51, 2.248e6, 2.488e9, 6.473e11]`,
> `den = [1044, 1.239e10, 2.034e13, 8.21e15, 3.67e16]`. Input is `P_fc` in **watts**,
> output is hydrogen rate in **g/s**.
>
> **Scale portability — resolved (operator ruling, 2026-08-31).** The `720` in
> `den[0] = 1044 = 720 × 1.45` is the full-size **fuel cell's OCV** (an earlier reading of
> it as the battery `Em` — both are 720 V in that model — was wrong). The transfer
> function needs **no adjustment** for this rig: its input (`P_fc`, W) and output (g/s)
> both ride the system's energy scaling factor, so the g/s-per-W map is scale-invariant
> under the systemic scaling methodology
> (`references/Systemic_Scaling_of_Powertrain_Models_with_Youla_Driver_Control.pdf`,
> Tan, Yadav & Assadian). H2 figures from this path are the **model's estimate proper**.
> Remaining caveats — about the model, not the scaling:
>
> 1. **Stack identification.** The coefficients were fit for the full-size stack's
>    consumption behaviour and have **not** been identified against *this* stack.
>    `TODO(calibrate)` — the surviving obligation, and it covers whether the 0.2212 s
>    consumption lag transfers unchanged to a small stack.
> 2. **Efficiency disagreement.** Its DC gain **1.7637602179836514e-05 g/s/W** is
>    **1.164×** the DP's own static proxy `W_H2 = P_fc/(0.55·120000)` (`DPtrial.m:43`) —
>    it implies **η = 47.25 %** where the same script assumes 55 %, a **+16.4 %**
>    disagreement *inside one study*. A model choice to note when comparing against
>    proxy-based numbers.
> 3. **Dynamics.** Its dominant time constant **0.2212 s** is a *consumption*-dynamics
>    claim (fuel delivery / stack thermodynamics) and is a **different quantity** from the
>    *electrical* `FC_TAU_S = 0.020 s` double-layer lag in `hil_electrical.py:405`. They
>    are not alternatives and must not be reconciled with each other.

**Discretization (measured; do not revisit).** A characterization round (scipy,
2026-08-31) established the CT system is stable and minimum-phase, then compared three
discretizations at 1 kHz:

| Form | Max relative error | Verdict |
|---|---|---|
| ZOH modal / parallel first-order | 2.5e-9 | **chosen** |
| Tustin | — | **rejected**: maps the 1.887e6 rad/s pole to `z = −0.9997`, a permanent ringing mode at Nyquist |
| `tf2sos` cascaded biquads | 8.2e-3 | **rejected**: worse than Tustin |

The implementation (`H2Consumption` in `tools/hil_plant_sim.py`) is four **independent
scalar first-order recursions summed**, stdlib only, allocation-free, inside the 1 kHz
tick. The fourth mode has `λ = 0`: it is the ZOH image of the fastest CT pole, **not** a
direct feedthrough — the CT system is strictly proper. DC check:
`Σ gᵢ/(1−λᵢ) = 1.7637602179836473e-05`, 4 ulp from the target gain.

**Input.** `u = P_fc` is **stack** power: `FuelCellSource.v_terminal × FuelCellSource.i`,
plant truth, both electrical modes. Deliberately *not* the CSV's `V_fc × I_fc` — `I_fc` is
the **bus-side** channel current (the boost output) while `V_fc` is the source-side
terminal voltage, so their product understates stack power by roughly
`V_bus/(η·V_fc)`. **Consequence:** the metric is *not* reconstructible from the CSV's
voltage and current columns, which is why `h2_rate_gps` and `h2_cum_g` are logged
(§7.1). Negative `P_fc` is **clamped at zero** — reverse power into the stack is not a
physical operating point here, and a negative rate would be an unphysical hydrogen
*credit* that would silently flatter any strategy that provoked it.

**Scope.** Simulated mode only, by construction: it is stepped from `Plant.step()`, and
`--replay` bypasses the plant integrator. It is a pure **observer** — no plant state, no
injected frame, no policy and no firmware path reads it back, so enabling it cannot change
a trace. The wire protocol was untouched by that round (40 B inject / 16 B observe / 22 B command); **fw v24 grew the observation frame to 17 B** — see §5.

### 9.4 The DP-optimal EMS benchmark — `dp-replay` and its table

> ### ⚠️ A BENCHMARK, NOT A CONTROLLER
> The `dp-replay` strategy plays back a **time-indexed setpoint table** computed
> **offline**, with **full foreknowledge of the entire drive cycle and the entire
> auxiliary load**, by backward dynamic programming. It reads no feedback and reacts to
> nothing. It exists to be the **lower-bound reference** the causal strategies are ranked
> against, and it is **meaningless against any profile other than the one it was generated
> for** — which is why it refuses to start on a fingerprint mismatch.

**Generator:** `tools/gen_dp_ems_table.py` (offline; needs **numpy**, so miniforge, not
`.venv_hil`). **Table:** `tools/dp_tables/dp_ems_table_<scenario>.csv`, checked in,
byte-deterministic, refuses to overwrite without `--force`.

**Provenance.** The *structure* is ported from the PhD student's MATLAB FCHEV study
(`references/EMS/DPtrial.m`, `references/EMS/DP_EnergyManagement2.m`): backward Bellman induction
over an SoC grid with a fuel-cell power control, a hydrogen stage cost, a running
SoC-deviation penalty and a heavy terminal charge-sustaining penalty. **Nothing numeric is
imported from it** — that is a 106 kW vehicle and this is a bench rig. The generator's
module docstring carries the declared port decisions **D1–D11** in full; the ones that
change what the answer *means* are:

| # | Decision | Why |
|---|---|---|
| D1 | **Linear** interpolation of `J(:,k+1)` at `SOC_next`; off-grid transitions are **infeasible**, not clamped | the MATLAB snaps to the nearest grid index (`DP_EnergyManagement2.m:39`), which on its own grid quantizes ~99 % of realistic steps to "no change at all" |
| D2 | the argmin **policy is stored**; the forward pass is a table lookup | the MATLAB re-solves the whole minimisation forward (`:61-95` duplicates `:23-53`) |
| D3 | an infeasible state the forward pass **reaches** raises | the MATLAB silently commands `P_fc = 0` (`:96`), handing the demand to the battery — the limit the feasibility test was protecting |
| D4 | stage cost uses the **`Gfc` DC gain** (§9.3), imported from `hil_plant_sim.py` | makes the objective and the logged `h2_cum_g` the same model; `DPtrial.m:43`'s static proxy disagrees by +16.4 % |
| D6 | SoC dynamics are the **simulator's `BatterySource`** (OCV table, `Rs(SOC)`, coulomb count) | **operator ruling: match the plant.** The MATLAB's constant `Em = 720 V` lossless pack is retired; the problem becomes nonlinear in the state |
| D7 | the demand is **derived from the scenario, imported at generation time** | no hand-copied profile — retuning the scenario changes the fingerprint and invalidates the table |
| D10 | charging is a **discrete second control**, masked to cruise regions and an FC-current budget | on this board a negative pack current can only come from the Ag105, and `assertFcChargeEnable()` drops BT off the bus. Never during acceleration (operator ruling (b)). Precedent: `ems_regen_harvest` windows `charge_goal` off the same profile |
| D11 | `--charger-accounting` picks which hydrogen total the DP minimises | **must match the electrical engine**: hi-fi stamps the Ag105's bus draw, simple mode does not. A `physical` table judged by the simple-mode metric is *beaten by the causal strategy* and is not a bound at all |

**Two structural choices worth stating separately.**

*The running SoC penalty defaults to **zero**.* The reason this table can be called a lower
bound is one line: among trajectories ending at the same terminal SoC the terminal penalty
is identical, so minimising (hydrogen + terminal penalty) is exactly minimising hydrogen.
A *running* penalty is not identical across those trajectories, so it re-ranks them.
Measured at the MATLAB's own ratio (`--lambda-dev 0.05`): the SoC-matched DP came out
**0.07 % worse** in hydrogen than the causal strategy it is meant to bound, purely because
it was paying a running penalty the causal strategy never paid. The MATLAB structure stays
reachable via `--lambda-dev`, for SoC-trajectory shaping — not for generating an optimum
anyone will quote.

*The share control grid is `[0.25, 0.75]`,* the same authority the causal `soc-band` policy
gives itself. Both halves matter: an unconstrained DP sits at 0.15 and 0.85, i.e. exactly
**on** the `updateShareSetpointCutoff()` boundary where a float round-trip decides whether
a bus switch opens (exercising that latch is `handoff-sag`'s job); and a benchmark allowed a
wider split range than the strategy it bounds measures the range, not the policy.

**Result on the shipped `ems-dp-replay` table** (generator's own reduced model, open loop,
`--charger-accounting physical`, terminal SoC matched by bisection):

| | DP (`dp-replay`) | causal (`soc-band`) |
|---|---|---|
| `h2` (physical) | **1.17564e-02 g** | 1.37227e-02 g |
| terminal SoC | 0.698006 | 0.698005 |

i.e. **−14.33 %** hydrogen at matched terminal SoC. ⚠️ Both columns are the Gfc model's
estimates — the map is scale-portable, the stack is not identified against this rig
(`TODO(calibrate)`, §9.3). The **ranking** is robust regardless; quote the absolute grams
with that caveat.

**The `soc-band` timing figures come from here, and only from here.** The generator walks
the real `SocBandStrategy` through the *same* reduced model it solves the DP against
(`--no-compare-heuristic` skips it), and prints
`band exit t= / share saturation t= / first charge t=`. Those three numbers —
**24.30 / 34.90 / 41.70 s** (`I_charge` > 0.5 A by ≈ 42.6 s, after `AG105_SETTLE_S` plus
the ramp) — are the single source used by the scenario entry in `hil_plant_sim.py`, the
`SOC_BAND_DRAIN_LOAD_A` budget, the `run_hil_suite.py` check windows, §6's scenario table
and the user manual's §3.2.2 walkthrough. Reproduce them with:

```
C:\Users\ricky\miniforge3\python.exe tools\gen_dp_ems_table.py --scenario ems-dp-replay --dry-run
```

A second independent offline walk would be a second answer; if the scenario is retuned,
re-read them from this line rather than re-deriving them anywhere else.

**The DP never charges on this cycle**, and that is a finding rather than a gap: shifting
the split toward the fuel cell buys **0.405 SoC per gram**, running the Ag105 buys **0.169**.
Opportunistic charging is simply the worse lever at this rig's numbers.

**Fidelity boundary — what the predicted numbers are not.** The generator's model has no
share loop, no Ag105 settle/ramp, a 0.1 s stage, and uses the `Gfc` **DC gain** rather than
its 0.2212 s dynamics. Its `V_bus` is the both-sources droop at every stage, including the
single-source charge windows (a 0.2 % error on a ~15.9 V rail, taken so the demand stays
independent of the control and the stage cost stays separable). So the −14.33 % is an
*estimate of the gap*, not a measurement of it, and the realised run will differ. Compare
the **measured** runs on the report's `h2_cum_g` / `delta_soc` pair, and treat a hydrogen
difference at visibly different `delta_soc` as uninterpretable.


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
| **H2 model identification** | §9.3. `Gfc` is scale-portable by design (operator ruling 2026-08-31; the `den[0]` provenance question is CLOSED — 720 V is the full-size FC's OCV) but not identified against the actual H-20 class stack. One open item: an identification run against the real stack, which also settles whether the 0.2212 s consumption lag and the η 47.25 %-vs-55 % model choice transfer. |
| **A closed-loop DP** | §9.4's benchmark is open loop and single-profile: it is a solution of ONE cycle, replayed. The natural next steps are (a) an ECMS/co-state extraction from the DP's own value function, which WOULD be causal and Pi-portable, and (b) regenerating the table under `--charger-accounting simple` whenever a campaign is run with `--electrical simple`, since a table optimised for the wrong accounting is not a bound. |
| **A portable SoC estimator** | The `soc-band` EMS strategy closes on plant-truth `fb["soc"]`, which no real Pi can see (v4 telemetry has no SoC field). A `V_batt`-based estimator on the Pi (OCV lookup + coulomb counting off the telemetry `I_batt`) would feed the same law unchanged and make the strategy Mode-B portable. Does not exist. |
| **Battery state of charge / CV taper / MPPT loop** | The Ag105 model (§4.6) is status-level only; a stateful SoC model would let `AG105_ST_FULL` and a genuine CV taper appear in a HIL run. |
